"""Honk's feelings as a pure function: step(state, events, params, t) -> state. No model, no clock, no I/O.

Layers (see the refactor plan, section 7):
  temperament  state["base"], state["sens"]     drifts a little each sleep
  needs        energy, connection, purpose (level, 1 = satisfied) and curiosity (pressure, 1 = bursting)
  mood         valence, arousal (-1..1)
  weight       the existential weight of being the last keeper (0..cap), taken from mood when it is read
  emotion      a label derived when the state is read, never stored

Every value is stored as it was at state["t"] and decays lazily: reading it at a later time uses the closed form
x = b + (x0 - b) * exp(-dt / tau). So the tick rate does not matter and fast-forward is exact.

Time is simulated minutes. An event is a dict:
  {"t": minutes, "kind": str, "source": str, "appraisal": {axis: -1..1}, "direct": {name: delta}, "topics": [str],
   "set": {"asleep": bool, "w_open": float, "ledger": 0..1}}
"""
import copy
import math

AXES = ("novelty", "expectedness", "mission_relevance", "learning_gain", "warmth", "effort", "agency")
NEEDS = ("energy", "curiosity", "connection", "purpose")
TARGETS = NEEDS + ("valence", "arousal", "weight")


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def new_state(params, t=0.0):
    f = params["feelings"]
    return {
        "t": float(t), "asleep": False, "w_open": 0.0, "ledger": 1.0,
        "energy": 1.0, "curiosity": f["curiosity_base"], "connection": f["connection_base"], "purpose": f["purpose_base"],
        "valence": f["valence_base"], "arousal": f["arousal_base"], "weight": 0.0,
        "base": {"connection": f["connection_base"], "purpose": f["purpose_base"], "valence": f["valence_base"], "arousal": f["arousal_base"]},
        "sens": {a: 1.0 for a in AXES},
        "habit": {}, "caps": {}, "urgent": {n: False for n in NEEDS}, "last": None,
    }


def _toward(x0, base, tau, dt):
    return base + (x0 - base) * math.exp(-dt / tau)


def _push(x, d, lo, hi):
    """Move x by d, but only by that share of the room left: a full push never leaves the range and never overshoots."""
    d = clamp(d, -1.0, 1.0)
    return clamp(x + d * (hi - x) if d > 0 else x + d * (x - lo), lo, hi)


def _weight_rest(state, f):
    return f["weight_cap"] * f["weight_ledger"] * (1.0 - state["ledger"])


def _settled(state, params, t):
    """The seven stored numbers as they are at time t (t >= state["t"])."""
    f, dt = params["feelings"], max(0.0, t - state["t"])
    if state["asleep"]:
        energy = _toward(state["energy"], 1.0, f["energy_tau_asleep"], dt)
    else:
        energy = _toward(state["energy"], 0.0, f["energy_tau_awake"], dt)
    if state["w_open"] > 0:      # bounded growth: open web questions he cannot look into yet
        curiosity = 1.0 - (1.0 - state["curiosity"]) * math.exp(-f["curiosity_rate"] * state["w_open"] * dt)
    else:
        curiosity = _toward(state["curiosity"], f["curiosity_base"], f["curiosity_tau"], dt)
    b = state["base"]
    return {
        "energy": energy, "curiosity": curiosity,
        "connection": _toward(state["connection"], b["connection"], f["connection_tau"], dt),
        "purpose": _toward(state["purpose"], b["purpose"], f["purpose_tau"], dt),
        "valence": _toward(state["valence"], b["valence"], f["valence_tau"], dt),
        "arousal": _toward(state["arousal"], b["arousal"], f["arousal_tau"], dt),
        "weight": _toward(state["weight"], _weight_rest(state, f), f["weight_tau"], dt),
    }


def _advance(state, params, t):
    if t > state["t"]:
        state.update(_settled(state, params, t))
        state["t"] = t


def habit(state, params, topic, t):
    """How used to a topic he is at time t (0 new .. 1 completely familiar)."""
    h = state["habit"].get(topic)
    return 0.0 if not h else h[0] * math.exp(-max(0.0, t - h[1]) / params["feelings"]["habit_tau"])


def levels(values):
    """Each need as a level where low means lacking (curiosity is stored as pressure, so it is turned round)."""
    return {"energy": values["energy"], "curiosity": 1.0 - values["curiosity"], "connection": values["connection"], "purpose": values["purpose"]}


def urgency(level, f):
    return 1.0 / (1.0 + math.exp(-f["urgency_k"] * (f["setpoint"] - level)))


def _apply(state, params, ev):
    f = params["feelings"]
    for k, v in (ev.get("set") or {}).items():
        if k in ("asleep", "w_open", "ledger"):
            state[k] = bool(v) if k == "asleep" else clamp(float(v), 0.0, 1e6 if k == "w_open" else 1.0)
    a = ev.get("appraisal") or {}
    vec = [clamp(float(a.get(ax, 0.0)), -1.0, 1.0) * state["sens"][ax] for ax in AXES]
    delta = {tg: sum(w * x for w, x in zip(f["W"][tg], vec)) for tg in TARGETS}
    for k, v in (ev.get("direct") or {}).items():
        if k in delta:
            delta[k] += float(v)
    for n in NEEDS:
        state[n] = _push(state[n], delta[n], 0.0, 1.0)
    # mood: bad news weighs more, and one source can only move it so far in an hour
    dv = delta["valence"] * (f["negative_gain"] if delta["valence"] < 0 else 1.0)
    src = str(ev.get("source") or ev.get("kind") or "world")
    recent = [(t, m) for t, m in state["caps"].get(src, []) if state["t"] - t < 60.0]
    room = max(0.0, f["cap_per_hour"] - sum(m for _, m in recent))
    dv = math.copysign(min(abs(dv), room), dv)
    if dv:
        recent.append((state["t"], abs(dv)))
    state["caps"] = {k: v for k, v in state["caps"].items() if k != src and any(state["t"] - t < 60.0 for t, _ in v)}
    if recent:
        state["caps"][src] = recent
    state["valence"] = _push(state["valence"], dv, f["mood_floor"], 1.0)
    state["arousal"] = _push(state["arousal"], delta["arousal"], -1.0, 1.0)
    state["weight"] = _push(state["weight"], delta["weight"], 0.0, f["weight_cap"])
    for topic in ev.get("topics") or []:
        h = habit(state, params, topic, state["t"])
        state["habit"][topic] = [h + (1.0 - h) * f["habit_gain"], state["t"]]
    if len(state["habit"]) > 200:   # forget what he has not met in a long time
        keep = sorted(state["habit"].items(), key=lambda kv: -habit(state, params, kv[0], state["t"]))[:150]
        state["habit"] = dict(keep)
    strongest = max(AXES, key=lambda ax: abs(a.get(ax, 0.0))) if a else None
    if strongest and abs(a.get(strongest, 0.0)) >= 0.3:
        state["last"] = [strongest, 1 if a[strongest] > 0 else -1, state["t"]]


def step(state, events, params, t):
    """A new state at time t, after the events (in time order) have happened. The old state is not touched."""
    s = copy.deepcopy(state)
    t = max(float(t), s["t"])
    for ev in sorted(events, key=lambda e: e.get("t", t)):
        _advance(s, params, clamp(float(ev.get("t", t)), s["t"], t))
        _apply(s, params, ev)
    _advance(s, params, t)
    f = params["feelings"]
    for n, lv in levels(s).items():   # hysteresis: a need becomes urgent at one level and stops being urgent at a lower one
        u = urgency(lv, f)
        if u > f["urgent_enter"]:
            s["urgent"][n] = True
        elif u < f["urgent_leave"]:
            s["urgent"][n] = False
    return s


def view(state, params, t=None):
    """What he feels at time t, for prompts and for the viewer. Reads only."""
    f = params["feelings"]
    t = state["t"] if t is None else max(t, state["t"])
    v = _settled(state, params, t)
    lv = levels(v)
    out = dict(v)
    out["mood"] = clamp(v["valence"] - f["weight_mood"] * v["weight"], f["mood_floor"], 1.0)
    out["urgency"] = {n: urgency(lv[n], f) for n in NEEDS}
    out["urgent"] = dict(state["urgent"])
    out["asleep"] = state["asleep"]
    out["emotion"] = emotion(state, out, t)
    return out


def emotion(state, v, t):
    if state["asleep"]:
        return "asleep"
    if state["urgent"].get("energy"):
        return "tired"
    last = state.get("last")
    if last and t - last[2] < 30.0:
        word = {("learning_gain", 1): "delighted", ("warmth", 1): "touched", ("warmth", -1): "stung", ("agency", 1): "proud",
                ("agency", -1): "frustrated", ("novelty", 1): "intrigued", ("mission_relevance", 1): "purposeful",
                ("expectedness", -1): "restless", ("effort", 1): "worn"}.get((last[0], last[1]))
        if word:
            return word
    if v["weight"] > 0.3 and v["mood"] < 0.2:
        return "wistful"
    if v["mood"] > 0.15:
        return "excited" if v["arousal"] > 0.2 else "content"
    if v["mood"] < -0.15:
        return "uneasy" if v["arousal"] > 0.2 else "low"
    return "curious" if v["curiosity"] > 0.6 else "calm"


def drift(state, params, averages):
    """Temperament moves a little toward how his days have been (called once per sleep)."""
    s, f = copy.deepcopy(state), params["feelings"]
    for k in ("connection", "purpose", "valence", "arousal"):
        if k in averages:
            home = f[f"{k}_base"]
            moved = s["base"][k] + clamp(averages[k] - s["base"][k], -f["drift"], f["drift"])
            s["base"][k] = clamp(moved, home - f["drift_clamp"], home + f["drift_clamp"])
    return s
