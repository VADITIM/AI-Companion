"""The cognitive scheduler: observe, update internal state, weigh motivations, check goals, decide, validate, act,
record. The model is asked only at meaningful moments; everything else here is ordinary code, and every
model request has a rule-based fallback, so he keeps living when no model answers.

The inner monologue is written from the state transitions that actually happened. A line marked "model"
is the model's own summary of a decision it really made; nothing is invented after the fact.
"""
import math
import queue
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor

from . import memory
from .actions import step_for, validate
from .goals import GOAL_TYPES, UNDERSTOOD, GoalManager
from .llm import check
from .motivation import all_regions, candidates, choose, label, urgent_alternative
from .state import CHANNEL_NEED, TRAITS, Emotions, Needs, clamp
from .world import PERCEPTION, REACH, dist

SYSTEM = ("You are the reasoning of {name}, a small creature living alone on an island. Nobody gives {name} orders. "
          "Think in the first person, in one or two short plain sentences. You may only choose among the options "
          "you are given. Your internal_state numbers are facts measured by the body: do not change them. "
          "Reply with JSON only.")
FELT = {"food": "it filled me up", "rest": "I feel rested", "fun": "it was fun", "expression": "I made something",
        "comfort": "it felt good", "shelter": "I felt safe", "wonder": "it was strange and wonderful",
        "company": "someone answered"}
PONDER_SECONDS = 45
OBJECT_TYPES = ("food_source", "water", "toy", "rest_place", "canvas", "seat", "unknown")
TRAIT_ACTIVITIES = {"curiosity": ("explore", "inspect"), "playfulness": ("play", "splash", "shake", "roll"),
                    "creativity": ("create", "blow")}


class Mind:
    def __init__(self, bus, store, provider, cfg, rng, sync_llm=False):
        self.bus, self.store, self.provider, self.cfg, self.rng = bus, store, provider, cfg, rng
        self.cid, self.name = cfg["creature"]["id"], cfg["creature"]["name"]
        self.baseline = dict(cfg["personality"])
        self.traits = store.creature(self.cid, self.name, cfg["personality"])
        s, self.saved_real = store.load_state(self.cid)
        self.born = s is None
        s = s or {}
        self.needs = Needs(s.get("needs"))
        self.emotions = Emotions(s.get("emotions"), s.get("impulses"))
        self.now = s.get("now", 480.0)
        self.visited = s.get("visited", {})                 # region -> minute of the last visit
        self.metrics = {"actions": 0, "failed": 0, "rejected": 0, "interrupts": 0, "goals_completed": 0,
                        "goals_abandoned": 0, "llm_calls": 0, "llm_failures": 0, "llm_seconds": 0.0,
                        "minutes": 0.0, "minutes_without_goal": 0.0} | s.get("metrics", {})
        self.action_counter = s.get("action_counter", 0)
        self.last_reflect_day = s.get("last_reflect_day", -1)
        self.last_reflect = s.get("last_reflect", self.now)
        self.last_consolidation = s.get("last_consolidation", self.now)
        self.recent = deque(s.get("recent", []), maxlen=60)
        self.know = {k["id"]: k for k in store.load_objects()}
        for k in self.know.values():                        # what he understood before is now simply remembered
            if k["state"] == "UNDERSTOOD":
                k["state"] = "REMEMBERED"
        self.prefs = store.prefs()
        self.watcher = store.relationship("watcher")
        self.goals = GoalManager(store)
        self.cooldown = {}
        self.pos, self.region, self.is_night, self.weather, self.sheltered = [0.0, 0.0], "", False, "clear", False
        self.ready = False
        self.plan, self.current, self.intention = [], None, None
        self.thought, self.failures, self.surprise = "", 0, None
        self.said, self.focus = {}, None                     # topic -> minute last voiced; the thing he is looking into
        mc = cfg.get("mind", {})
        self.quiet, self.decide_interval = mc.get("quiet_minutes", 360), mc.get("decide_interval", 180)
        self.monologue, self.decisions, self.retrieved = deque(maxlen=40), deque(maxlen=30), []
        self.pending, self.results = {}, queue.Queue()
        self.pool = None if sync_llm else ThreadPoolExecutor(1, thread_name_prefix="model")
        self.last_llm_real, self.token = -1e9, 0
        self.last_decide = self.next_goal_ask = self.last_interrupt = -1e9
        self._acc, self._last_persist = 0.0, self.now

    # ================================================================== the cycle
    def tick(self, dt):
        self.now += dt
        for msg in self.bus.drain_mind():
            self._handle(msg)
        self._apply_model_results()
        self._acc += dt
        if self._acc >= 1.0 and self.ready:
            step, self._acc = self._acc, 0.0
            self.metrics["minutes"] += step
            self.needs.update(step, self.traits, self.asleep, self.weather, self.sheltered, self.is_night)
            self.emotions.update(step, self.needs, self.traits, self.watcher["affection"])
            self._deliberate(step)
            self.bus.to_world("creature.state", {"mood": self.emotions.mood(self.needs), "thought": self.thought,
                                                 "asleep": self.asleep}, self.now)
        if self.now - self.last_consolidation >= 120:
            self.consolidate()
        if self.now - self._last_persist >= 10:
            self.persist()

    @property
    def asleep(self):
        return bool(self.current) and self.current["step"]["action"] == "sleep"

    def think(self, kind, text, source="rule", topic=None):
        """Voice a thought, unless he has had the same one lately: routine is lived, not narrated."""
        topic = topic or text
        if self.now - self.said.get(topic, -1e9) < self.quiet:
            return
        self.said[topic] = self.now
        self.monologue.append({"minute": round(self.now, 1), "kind": kind, "text": text, "source": source})
        if kind in ("intention", "discovery", "goal", "reflection", "event", "failure", "social", "state", "learning"):
            self.thought = text
        self.store.log(self.now, "thought." + kind, {"text": text, "source": source})

    def remember(self, summary, event, importance, tags=(), type_="episodic", source="rule"):
        if importance < 0.3:                                 # not everything deserves to be kept
            return
        top = {e: round(v, 2) for e, v in sorted(self.emotions.v.items(), key=lambda kv: -kv[1])[:3]}
        self.store.remember(type_, self.now, summary, event, self.region, tags, top, importance, source)

    def novelty(self, amount):
        self.needs.apply({"wonder": amount})
        self.emotions.feel("curiosity", amount)
        self.emotions.feel("excitement", amount)

    # ================================================================== messages from the world
    def _handle(self, msg):
        p = msg["payload"]
        {"world.observation": self._on_observation, "world.event": self._on_event,
         "creature.action_progress": self._on_progress, "creature.action_completed": self._on_completed,
         "system.heartbeat": lambda p: None}[msg["type"]](p)

    def _on_observation(self, p):
        self.now, self.pos = p["time"]["minute"], p["position"]
        self.is_night, self.weather, self.sheltered = p["time"]["is_night"], p["weather"], p["sheltered"]
        if not self.ready:
            self.ready = True
            self.goals.seed(self.now)
            if self.born:
                self.think("state", "I am awake. I do not know this place yet.")
                self.remember("I woke up for the first time, on an island I did not know.", "born", 0.9,
                              ["beginning"], "autobiographical")
        if p["region"] != self.region:
            self.region = p["region"]
            if self.region not in self.visited:
                if self.visited:
                    self.novelty(0.1)
                    self.think("explore", f"New ground ({len(self.visited) + 1} of {len(all_regions())} parts of the island).")
                self.remember(f"I walked into a part of the island I had not seen ({self.region}).", "new_region", 0.3,
                              ["exploration"])
        self.visited[self.region] = self.now
        seen = set()
        for o in p["nearby_objects"]:
            seen.add(o["id"])
            k = self.know.get(o["id"])
            if not k:
                k = self.know[o["id"]] = {"id": o["id"], "type": o["type"], "look": o["look"], "pos": o["position"],
                                          "state": "OBSERVED", "caps": [], "effects": {}, "tries": {},
                                          "first_seen": self.now, "stock": None, "gone": False, "blocked_until": 0}
                self.novelty(0.15)
                self.think("discovery", f"Something I have not seen before: {o['look']}.")
                self.remember(f"I found {o['look']}.", "discovered", 0.6, [o["id"], o["type"], "discovery"])
                self.store.save_object(k)
            elif k["gone"]:
                self.think("discovery", f"There it is again: {k['look']}.")
            k.update(pos=o["position"], last_seen=self.now, gone=False)
            if "stock" in o:
                k["stock"] = o["stock"]
                if o["stock"] > 0:
                    k["blocked_until"] = 0
        for k in self.know.values():
            if not k["gone"] and k["id"] not in seen and dist(self.pos, k["pos"]) < PERCEPTION * 0.6:
                k["gone"] = True
                self.think("event", f"{k['look'].capitalize()} is not where I remember it.")
                self.remember(f"I went to where {k['look']} used to be and it was gone.", "gone", 0.5, [k["id"]])

    def _on_event(self, p):
        kind = p["type"]
        self.store.world_event(self.now, kind, p)
        if kind == "weather":
            self.weather = p["weather"]
            if p["weather"] == "storm":
                self.emotions.feel("fear", 0.3)
                self.needs.bump("safety", 0.2)
                self.think("event", "A storm is coming in.")
                self.remember("A storm came over the island.", "storm", 0.5, ["weather"])
                self.surprise = "A storm has started"
            elif p["weather"] == "rain":
                self.emotions.feel("sadness", 0.05)
                self.think("event", "It has started to rain.")
            else:
                self.emotions.feel("joy", 0.15)
                self.think("event", "The sky has cleared.")
        elif kind == "thunder" and not self.sheltered:
            self.needs.bump("safety", 0.3)
            self.emotions.feel("fear", 0.4)
            self.think("event", "Thunder. Too close.")
        elif kind == "bird_flyby" and not self.asleep:
            self.novelty(0.05)
            self.emotions.feel("joy", 0.1)
            self.think("event", "A bird crossed the sky.")
        elif kind == "watcher_pet":
            self.needs.apply({"company": 0.5})
            self.emotions.feel("affection", 0.5)
            self.emotions.feel("joy", 0.2)
            w = self.watcher
            w.update(familiarity=clamp(w["familiarity"] + 0.1), affection=clamp(w["affection"] + 0.08),
                     interactions=w["interactions"] + 1, last_minute=self.now)
            self.store.save_relationship(w)
            self.think("social", "The watcher reached down and stroked me.")
            self.remember("The watcher stroked me. It was gentle.", "watcher_pet", 0.6, ["watcher", "social"])
            self.surprise = "The watcher has just stroked you"

    def _on_progress(self, p):
        c = self.current
        if c and p["action_id"] == c["action_id"]:
            self.needs.apply(p["effects"])
            for ch, v in p["effects"].items():
                c["effects"][ch] = c["effects"].get(ch, 0.0) + v
            c["progress"] = p["progress"]

    def _on_completed(self, p):
        cur = self.current
        if not cur or p["action_id"] != cur["action_id"]:
            return                                            # a stale or repeated result: ignore
        self.current = None
        step = cur["step"]
        act, tid = step["action"], step.get("target")
        cap = step.get("capability") or act
        k = self.know.get(tid)
        res = p.get("result") or {}
        if p["success"] and act == "move_to":
            self.failures = 0
            if self.plan:
                return self._send_next()
            return self._record(cur, True, None, 0.1)         # an exploring walk, finished
        eff = {ch: round(v, 3) for ch, v in cur["effects"].items()}
        valence = sum(min(v, cur["before"][CHANNEL_NEED[ch]]) if v > 0 else v for ch, v in eff.items() if ch in CHANNEL_NEED)
        if not p["success"] and not cur.get("woke_rested"):
            reason = p.get("reason", "failed")
            self.plan, self.focus = [], None
            if reason == "cancelled":
                self._record(cur, False, reason, valence, eff)
                if act == "sleep":
                    self._woke(cur)
                return
            self.failures += 1
            self.metrics["failed"] += 1
            self.emotions.feel("frustration", 0.25)
            if reason == "empty" and k:
                k["blocked_until"], k["stock"] = self.now + 120, 0
                self.think("failure", f"There is nothing left at {k['look']}.")
                self.remember(f"I wanted to {cap} at {k['look']} but there was nothing left.", "empty", 0.5, [k["id"], cap])
            elif reason == "no_such_object" and k:
                k["gone"] = True
                self.think("failure", f"{k['look'].capitalize()} is gone.")
            elif reason == "cannot" and k and cap in k["caps"]:
                k["caps"].remove(cap)
                self.think("failure", f"I cannot {cap} {k['look']} after all.")
            else:
                self.think("failure", f"That did not work ({reason}).")
            if self.failures >= 2:
                self.surprise = "Two things in a row have not worked"
            return self._record(cur, False, reason, -0.3, eff)
        self.failures = 0
        if act == "inspect":
            k.update(type=res["type"], look=res["look"], caps=res["capabilities"], stock=res.get("stock"))
            if k["state"] == "OBSERVED":
                k["state"] = "INVESTIGATED" if k["caps"] else "UNDERSTOOD"
            self.novelty(0.2)
            what = ", ".join(k["caps"]) or "nothing"
            self.think("discovery", f"I looked closely at {k['look']}. What I could do with it: {what}.")
            self.remember(f"I looked closely at {k['look']}. I could {what} there.", "inspected", 0.5, [k["id"], *k["caps"]])
            self.store.save_object(k)
            self._record(cur, True, None, 0.2)
            if k["type"] == "unknown" and k["caps"]:
                self._ask_unfamiliar(k)
            return
        if k:                                                 # an interaction: learn what it really gives
            first = cap not in k["effects"]
            n = k["tries"].get(cap, 0)
            old = k["effects"].get(cap, {})
            k["effects"][cap] = {ch: round((old.get(ch, 0) * n + eff.get(ch, 0)) / (n + 1), 3) for ch in set(old) | set(eff)}
            k["tries"][cap] = n + 1
            if res.get("stock") is not None:
                k["stock"] = res["stock"]
            felt = "; ".join(FELT[ch] if v > 0 else f"it was unpleasant ({ch})" for ch, v in eff.items() if abs(v) > 0.03) or "nothing much happened"
            if first:
                self.novelty(0.2)
                self.think("discovery", f"First time I tried to {cap} {k['look']}: {felt}.")
                self.remember(f"The first time I tried to {cap} {k['look']}: {felt}.", "first_try", 0.65, [k["id"], cap])
            elif abs(valence) >= 0.25:
                self.remember(f"I went to {label(cap, k['look'])}: {felt}.", f"{cap}:{k['id']}", 0.35, [k["id"], cap])
            if k["state"] not in UNDERSTOOD and all(c in k["effects"] for c in k["caps"]):
                k["state"] = "UNDERSTOOD"
                self.think("discovery", f"I think I understand {k['look']} now.")
                self.remember(f"I worked out what {k['look']} is for: {', '.join(k['caps'])}.", "understood", 0.6, [k["id"]])
            self.store.save_object(k)
        self.emotions.feel("joy", valence * 0.5)
        if valence < -0.05:
            self.emotions.feel("frustration", 0.15)
            self.think("failure", "That was unpleasant. I will remember it.")
        self.goals.note_action(cap)
        self._record(cur, True, None, valence, eff)
        if act == "sleep":
            self._woke(cur)

    def _record(self, cur, success, reason, valence, effects=None):
        key = cur["key"]
        step = cur["step"]
        self.store.add_action(self.now, key, step["action"], step.get("target"), success, reason, round(valence, 3),
                              effects or {}, cur["source"])
        self.store.log(self.now, "action", {"key": key, "success": success, "reason": reason, "valence": round(valence, 3)})
        self.metrics["actions"] += 1
        self.recent.append(key)
        self.cooldown[key] = self.now
        self.intention = None

    def _woke(self, cur):
        self.think("state", "I am awake again.")
        day = int(self.now // 1440)
        if self.now - cur["started"] > 120 and day != self.last_reflect_day:
            self.last_reflect_day = day
            self._reflect(day)

    # ================================================================== deciding
    def _deliberate(self, step):
        for g in self.goals.check(self):
            if g.status == "completed":
                self.metrics["goals_completed"] += 1
                self.emotions.feel("joy", 0.3)
                self.emotions.feel("excitement", 0.2)
                self.think("goal", f"I did it: {g.description}.")
                self.remember(f"I finished what I set out to do: {g.description}.", "goal_completed", 0.7, ["goal"])
            else:
                self.metrics["goals_abandoned"] += 1
                self.think("goal", f"I am letting this go: {g.description}.")
        if not self.goals.current():
            self.metrics["minutes_without_goal"] += step
            if "goal" not in self.pending and self.now >= self.next_goal_ask and not self.asleep:
                self.next_goal_ask = self.now + 30
                self._ask_goal()
        if self.current:
            if self.asleep and self.needs.v["fatigue"] <= 0.05:
                self.current["woke_rested"] = True            # waking up rested is the sleep succeeding, not failing
                return self._cancel()
            if self.now - self.last_interrupt > 15 and self.intention:
                need = urgent_alternative(candidates(self), self, self.intention["serves"])
                if need:
                    self.metrics["interrupts"] += 1
                    self.think("interrupt", f"I have to stop this: {need} is too strong to ignore.")
                    self._cancel()
            return
        if self.plan:
            return self._send_next()
        for kind in ("unfamiliar", "decide"):                # pondering: wait for the model, but not for ever
            p = self.pending.get(kind)
            if p:
                if time.monotonic() - p["real"] < PONDER_SECONDS:
                    return
                del self.pending[kind]
                self.metrics["llm_failures"] += 1
        more = self._continue_focus()
        if more:                                             # stay with the thing he is looking into; no fresh decision
            return self._commit(more, "still looking into the same thing", "rule", quiet=True)
        cands = candidates(self)
        reason, wait = self.surprise, 30
        if not reason and len(cands) > 1 and cands[0]["utility"] - cands[1]["utility"] < 0.02 and not self.needs.urgent():
            reason, wait = "Two things pull at you about equally", self.decide_interval
        if reason and self.now - self.last_decide >= wait:
            self.surprise, self.last_decide = None, self.now
            if self._ask_decide(cands[:5], reason):
                return
        self.surprise = None
        pick, why = choose(cands, self)
        self._commit(pick, why, "rule", cands)

    def _continue_focus(self):
        """Having started on something new, keep at it until everything it allows has been tried."""
        k = self.know.get(self.focus)
        if (not k or k["gone"] or k["blocked_until"] > self.now or self.needs.urgent()
                or dist(self.pos, k["pos"]) > PERCEPTION):
            self.focus = None
            return None
        if k["state"] == "OBSERVED":
            cap = "inspect"
        else:
            skip = {"sleep"} | ({"eat"} if self.needs.v["hunger"] < 0.2 else set())
            cap = next((c for c in k["caps"] if c not in k["effects"] and c not in skip), None)
        if not cap:
            self.focus = None
            return None
        return {"key": f"{cap}:{k['id']}", "cap": cap, "target": k["id"], "serves": ["curiosity"],
                "label": label(cap, k["look"]), "utility": 0}

    def _commit(self, c, why, source, cands=(), thought=None, quiet=False):
        if not quiet:
            new = c["target"] and (c["cap"] == "inspect" or c["cap"] not in self.know[c["target"]]["effects"])
            self.focus = c["target"] if new else None
        if c["cap"] == "explore":
            steps = [{"action": "move_to", "position": [round(v, 1) for v in c["position"]]}, {"action": "look_around"}]
        elif not c["target"]:
            steps = [{"action": c["cap"]}]
        else:
            k = self.know[c["target"]]
            steps = [{"action": "move_to", "target": k["id"]}] if dist(self.pos, k["pos"]) > (4.0 if c["cap"] == "inspect" else REACH * 0.9) else []
            steps.append(step_for(c["cap"], k["id"]))
        self.plan = steps
        self.intention = {"label": c["label"], "key": c["key"], "serves": c["serves"], "why": why, "source": source,
                          "for_goal": bool(c.get("goal"))}
        strongest = max(c["serves"], key=lambda n: self.needs.v[n]) if c["serves"] else None
        rule_thought = f"I want to {c['label']}." + (f" ({strongest} is at {round(self.needs.v[strongest] * 100)}%.)" if strongest and self.needs.v[strongest] >= 0.3 else "")
        self.decisions.append({"minute": round(self.now, 1), "choice": c["label"], "why": why, "source": source,
                               "utility": round(c.get("utility", 0), 3),
                               "alternatives": [[x["label"], round(x["utility"], 3)] for x in cands[:4] if x is not c]})
        self.store.log(self.now, "decision", self.decisions[-1])
        if not quiet:
            self.think("intention", thought or rule_thought, source, topic=c["key"])
        self._send_next()

    def _send_next(self):
        step = self.plan.pop(0)
        ok, reason = validate(step, self.know, self.needs, busy=bool(self.current))
        if not ok:
            self.metrics["rejected"] += 1
            self.think("failure", f"I cannot do that ({reason}).")
            self.store.log(self.now, "action.rejected", {"step": step, "reason": reason})
            self.plan, self.intention = [], None
            return
        self.action_counter += 1
        aid = f"act_{self.action_counter:06d}"
        self.bus.to_world("creature.execute_action", {"action_id": aid, **step}, self.now)
        self.current = {"action_id": aid, "step": step, "started": self.now, "effects": {}, "progress": 0,
                        "before": dict(self.needs.v), "key": self.intention["key"], "source": self.intention["source"]}

    def _cancel(self):
        self.bus.to_world("creature.cancel_action", {"action_id": self.current["action_id"]}, self.now)
        self.plan, self.last_interrupt = [], self.now

    # ================================================================== the model, when it is needed
    def _snapshot_for_model(self):
        goal = self.goals.current()
        return {"identity": {"name": self.name, "personality": {t: round(v, 2) for t, v in self.traits.items()}},
                "internal_state": {**{n: round(v, 2) for n, v in self.needs.v.items()},
                                   "mood": self.emotions.mood(self.needs)},
                "current_goal": {"description": goal.description} if goal else None,
                "environment": {"time": "night" if self.is_night else "day", "weather": self.weather,
                                "known_things": [{"id": k["id"], "what": k["look"], "understanding": k["state"].lower(),
                                                  "distance": round(dist(self.pos, k["pos"]))}
                                                 for k in self.know.values() if not k["gone"]],
                                "island_explored": f"{round(100 * len(self.visited) / len(all_regions()))}%"}}

    def _ask(self, kind, task, schema, query, on_result, on_fail=None):
        """Ask the model in the background. Returns True if the question went out (or, in tests, was answered)."""
        real = time.monotonic()
        too_soon = self.pool and real - self.last_llm_real < self.cfg["model"]["min_interval_s"]
        if kind in self.pending or too_soon or not self.provider.available():
            if on_fail and kind not in self.pending:
                on_fail()
            return False
        self.last_llm_real, self.token = real, self.token + 1
        token, now, snap = self.token, self.now, self._snapshot_for_model()
        goal = self.goals.current()
        goal_text, emotions = (goal.description if goal else ""), dict(self.emotions.v)
        temperature = self.cfg["model"]["temperature"]

        def job():
            t0 = time.monotonic()
            try:
                mem = self.store.recall(query, now, goal_text, emotions, 4, self.provider.embed)
                snap["recent_memories"] = [m["summary"] for m in mem]
                messages = [{"role": "system", "content": SYSTEM.format(name=self.name)},
                            {"role": "user", "content": memory.json.dumps({**snap, "task": task})}]
                reply = check(self.provider.generate(messages, schema, temperature), schema)
                return kind, token, reply, mem, time.monotonic() - t0, None
            except Exception as e:                            # any failure means: fall back to the rules
                return kind, token, None, [], time.monotonic() - t0, f"{type(e).__name__}: {e}"

        self.pending[kind] = {"real": real, "token": token, "on_result": on_result, "on_fail": on_fail}
        if self.pool:
            self.pool.submit(job).add_done_callback(lambda f: self.results.put(f.result()))
        else:
            self.results.put(job())
            self._apply_model_results()
        return True

    def _apply_model_results(self):
        while not self.results.empty():
            kind, token, reply, mem, seconds, err = self.results.get()
            p = self.pending.get(kind)
            if not p or p["token"] != token:
                continue                                      # it answered too late; the rules already moved on
            del self.pending[kind]
            self.metrics["llm_calls"] += 1
            self.metrics["llm_seconds"] += seconds
            self.store.log(self.now, "model." + kind, {"reply": reply, "error": err, "seconds": round(seconds, 2),
                                                       "memories": [m["id"] for m in mem]})
            if err:
                self.metrics["llm_failures"] += 1
                if p["on_fail"]:
                    p["on_fail"]()
                continue
            self.retrieved = mem
            for text in (reply.get("memory_candidates") or [])[:2]:
                if isinstance(text, str) and 8 <= len(text) <= 200:
                    self.remember(text, "belief", 0.5, ["belief"], "semantic", "model")
            p["on_result"](reply)

    def _ask_unfamiliar(self, k):
        options = [*k["caps"], "leave it alone"]
        schema = {"type": "object", "required": ["thought_summary", "choice"],
                  "properties": {"thought_summary": {"type": "string"}, "choice": {"type": "string", "enum": options},
                                 "memory_candidates": {"type": "array", "items": {"type": "string"}}}}

        def on_result(r):
            if self.current or self.plan:
                return
            thought = r["thought_summary"][:240]
            if r["choice"] == "leave it alone":
                k["blocked_until"] = self.now + 180
                self.decisions.append({"minute": round(self.now, 1), "choice": f"leave {k['look']} alone",
                                       "why": "unfamiliar thing", "source": "model", "utility": 0, "alternatives": []})
                return self.think("intention", thought, "model", topic=f"leave:{k['id']}")
            c = {"key": f"{r['choice']}:{k['id']}", "cap": r["choice"], "target": k["id"], "serves": ["curiosity"],
                 "label": label(r["choice"], k["look"])}
            self._commit(c, "unfamiliar thing: chosen among what it allows", "model", thought=thought)

        task = (f"You have just looked closely at {k['look']} (id {k['id']}). You have never seen anything like it and "
                f"do not know what it does. Choose one thing to try: {', '.join(options)}. "
                "memory_candidates: at most one short belief worth keeping, or an empty list.")
        self._ask("unfamiliar", task, schema, f"{k['look']} {' '.join(k['caps'])} unknown strange", on_result)

    def _ask_decide(self, top, reason):
        ids = {f"c{i + 1}": c for i, c in enumerate(top)}
        schema = {"type": "object", "required": ["thought_summary", "choice"],
                  "properties": {"thought_summary": {"type": "string"}, "choice": {"type": "string", "enum": list(ids)},
                                 "memory_candidates": {"type": "array", "items": {"type": "string"}}}}

        def on_result(r):
            if self.current or self.plan:
                return
            self._commit(ids[r["choice"]], reason, "model", top, thought=r["thought_summary"][:240])

        task = (f"{reason}. Choose what to do next from these options: "
                + "; ".join(f"{i} = {c['label']}" for i, c in ids.items())
                + ". memory_candidates: at most one short belief worth keeping, or an empty list.")
        return self._ask("decide", task, schema, reason + " " + " ".join(c["label"] for c in top), on_result)

    def _ask_goal(self):
        caps = sorted({cap for k in self.know.values() if not k["gone"] for cap in k["caps"]} - {"sleep", "eat", "shelter"})
        schema = {"type": "object", "required": ["thought_summary", "description", "type"],
                  "properties": {"thought_summary": {"type": "string"}, "description": {"type": "string"},
                                 "type": {"type": "string", "enum": list(GOAL_TYPES)}, "target": {"type": "string"},
                                 "action": {"type": "string"}, "object_type": {"type": "string"},
                                 "count": {"type": "integer"}}}

        def by_rule():
            prop = self.goals.propose_by_rule(self)
            if prop and self.goals.add(prop[0], 2, 0.6, prop[1], self.now):
                self.think("goal", f"I have decided: {prop[0].lower()}.")

        def on_result(r):
            t, cond = r["type"], None
            frac = len(self.visited) / len(all_regions())
            if t == "understand" and r.get("target") in self.know and self.know[r["target"]]["state"] not in UNDERSTOOD:
                cond = {"type": t, "target": r["target"]}
            elif t == "explore_fraction" and frac < 1:
                cond = {"type": t, "value": min(1.0, (int(frac * 4) + 1) / 4)}
            elif t == "discover" and r.get("object_type") in OBJECT_TYPES:
                have = sum(1 for k in self.know.values() if k["type"] == r["object_type"])
                cond = {"type": t, "object_type": r["object_type"], "count": have + 1}
            elif t == "repeat" and r.get("action") in caps:
                cond = {"type": t, "action": r["action"], "count": max(2, min(5, int(r.get("count") or 3)))}
            if not cond:                                      # the model asked for something that cannot be checked
                self.store.log(self.now, "goal.rejected", r)
                return by_rule()
            words = r["description"].strip()
            if not words or "_" in words:                     # it echoed the type name instead of saying what it wants
                words = {"understand": f"Find out what {self.know.get(cond.get('target'), {}).get('look', 'it')} is for",
                         "explore_fraction": "See more of the island", "discover": "Find another thing like the ones I know",
                         "repeat": f"Spend time: {cond.get('action')} {cond.get('count')} times"}[t]
            if self.goals.add(words, 2, 0.6, cond, self.now, "model"):
                said = r["thought_summary"][:240]
                self.think("goal", f"A new aim: {words}." if "_" in said or not said.strip() else said, "model")

        task = ("You have no goal at the moment. Choose ONE thing to work towards over the next day, of one of these "
                "types: understand (target = id of a known thing you do not fully understand yet); explore_fraction "
                "(see more of the island); discover (object_type = one of " + ", ".join(OBJECT_TYPES) + ": find "
                "another thing of that kind); repeat (action = one of: " + (", ".join(caps) or "nothing yet")
                + "; count = how many times). description: the goal as you would say it to yourself, in plain words, under 12 "
                "words, without the type name.")
        self._ask("goal", task, schema, "what do I want " + " ".join(sorted(self.needs.v, key=lambda n: -self.needs.v[n])[:3]),
                  on_result, by_rule)

    # ================================================================== learning
    def consolidate(self):
        report = memory.consolidate(self.store, self.prefs, self.know, self.last_consolidation, self.now)
        self.last_consolidation = self.now
        if report["preferences"]:
            key, v = max(report["preferences"].items(), key=lambda kv: abs(kv[1]))
            cap, _, tid = key.partition(":")
            what = label(cap, self.know[tid]["look"]) if tid in self.know else cap.replace("_", " ")
            self.think("learning", f"I notice I {'like to' if v > 0 else 'do not much like to'} {what}.")
        self.store.log(self.now, "consolidation", report)
        return report

    def _reflect(self, day):
        rows = self.store.q("SELECT key, COUNT(*) n, AVG(valence) v FROM actions WHERE minute>? AND success=1 GROUP BY key ORDER BY n DESC",
                            (self.last_reflect,))
        events = [m["summary"] for m in self.store.memories("archived=0 AND type='episodic' AND importance>=0.5 AND minute>?",
                                                           (self.last_reflect,), 8)]
        self.last_reflect = self.now
        for trait, acts in TRAIT_ACTIVITIES.items():          # temperament drifts, very slowly, towards what went well
            vs = [r["v"] for r in rows if r["key"].split(":")[0] in acts]
            if vs:
                drift = 0.003 if sum(vs) / len(vs) > 0.1 else -0.003
                self.traits[trait] = clamp(self.traits[trait] + drift, self.baseline[trait] - 0.1, self.baseline[trait] + 0.1)
        self.store.save_traits(self.cid, self.traits)
        keys = [r["key"] for r in rows]
        done = ", ".join(f"{r['key'].replace(':', ' ')} x{r['n']}" for r in rows[:6]) or "very little"
        best = max(rows, key=lambda r: r["v"])["key"].replace(":", " ") if rows else None

        def save(summary, lesson, source):
            self.store.x("INSERT OR REPLACE INTO daily_summaries VALUES(?,?,?,?,?)",
                         (day, summary, lesson, source, memory.json.dumps({"actions": [dict(r) for r in rows]})))
            self.remember(f"Day {day}: {summary} {lesson}".strip(), "daily_summary", 0.8, ["day"], "autobiographical", source)
            self.think("reflection", f"{summary} {lesson}".strip(), source)

        def by_rule():
            save(f"I did these things: {done}.", f"The best of it was {best}." if best else "", "rule")

        def on_result(r):
            for ch in (r.get("preference_changes") or [])[:3]:
                if ch.get("key") in keys and isinstance(ch.get("delta"), (int, float)):
                    new = clamp(self.prefs.get(ch["key"], 0.0) + clamp(ch["delta"], -0.05, 0.05), -0.3, 0.3)
                    self.prefs[ch["key"]] = new
                    self.store.x("INSERT INTO preferences VALUES(?,?,0,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 (ch["key"], new, self.now))
            save(r["summary"][:400], r["lesson"][:200], "model")

        if not rows:
            return by_rule()
        schema = {"type": "object", "required": ["summary", "lesson"],
                  "properties": {"summary": {"type": "string"}, "lesson": {"type": "string"},
                                 "preference_changes": {"type": "array", "items": {
                                     "type": "object", "required": ["key", "delta"],
                                     "properties": {"key": {"type": "string", "enum": keys}, "delta": {"type": "number"}}}}}}
        task = ("You have just woken up. Look back on the day before. What you did (activity, times): " + done
                + ". What stood out: " + " | ".join(events)
                + " Write summary (two short sentences, first person) and lesson (one sentence: what you learned or want "
                "more of). preference_changes: up to three small nudges (delta between -0.05 and 0.05) to how much you "
                "like an activity, or an empty list.")
        self._ask("reflect", task, schema, "yesterday " + done, on_result, by_rule)

    # ================================================================== persistence
    def persist(self):
        self._last_persist = self.now
        self.store.save_state(self.cid, {
            "needs": self.needs.v, "emotions": self.emotions.v, "impulses": self.emotions.impulse, "now": self.now,
            "visited": self.visited, "metrics": self.metrics, "action_counter": self.action_counter,
            "last_reflect_day": self.last_reflect_day, "last_reflect": self.last_reflect,
            "last_consolidation": self.last_consolidation, "recent": list(self.recent)}, self.now)
        for k in self.know.values():
            self.store.save_object(k)

    def advance_offline(self, minutes):
        """The program was closed for a while: one bounded step, not a replay."""
        hours = minutes / 60
        self.now += minutes
        self.needs.advance_offline(hours)
        self.last_consolidation = self.last_reflect = self.now
        self.think("state", f"Time has passed while the world was dark: about {hours:.1f} hours.")
        self.remember(f"The world went dark for about {hours:.1f} hours and then came back.", "offline", 0.5,
                      ["offline"], "autobiographical")

    def shutdown(self):
        self.persist()
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)

    # ================================================================== the developer's view
    def measures(self):
        m, keys = self.metrics, list(self.recent)
        counts = Counter(keys)
        entropy = -sum(c / len(keys) * math.log(c / len(keys)) for c in counts.values()) if keys else 0.0
        hours = max(m["minutes"] / 60, 1e-9)
        closed = m["goals_completed"] + m["goals_abandoned"]
        return {"simulated_hours": round(hours, 1), "actions": m["actions"],
                "failed_action_rate": round(m["failed"] / max(1, m["actions"]), 3),
                "rejected_by_validator": m["rejected"], "interrupts": m["interrupts"],
                "goal_completion_rate": round(m["goals_completed"] / closed, 2) if closed else None,
                "goals_completed": m["goals_completed"],
                "share_of_time_without_goal": round(m["minutes_without_goal"] / max(1, m["minutes"]), 3),
                "repetition": round(sum(1 for a, b in zip(keys, keys[1:]) if a == b) / max(1, len(keys) - 1), 3),
                "behavioural_diversity": round(entropy / math.log(len(counts)), 3) if len(counts) > 1 else 0.0,
                "distinct_activities": len(counts),
                "model_calls": m["llm_calls"], "model_failures": m["llm_failures"],
                "model_calls_per_hour": round(m["llm_calls"] / hours, 2),
                "model_seconds_per_call": round(m["llm_seconds"] / m["llm_calls"], 2) if m["llm_calls"] else None}

    def snapshot(self):
        c = self.current
        return {"name": self.name, "minute": round(self.now, 1), "region": self.region,
                "mood": self.emotions.mood(self.needs), "thought": self.thought, "asleep": self.asleep,
                "intention": self.intention,
                "action": {"step": c["step"], "progress": c["progress"], "action_id": c["action_id"]} if c else None,
                "pondering": [k for k in self.pending],
                "needs": {n: round(v, 3) for n, v in self.needs.v.items()},
                "emotions": {e: round(v, 3) for e, v in self.emotions.v.items()},
                "traits": {t: round(self.traits[t], 3) for t in TRAITS},
                "preferences": {k: round(v, 3) for k, v in sorted(self.prefs.items(), key=lambda kv: -abs(kv[1]))[:10]},
                "goals": [{"id": g.id, "description": g.description, "level": g.level, "status": g.status,
                           "source": g.source, "parent": g.parent_goal_id, "conditions": g.success_conditions}
                          for g in self.goals.goals[-14:]],
                "known": [{"id": k["id"], "look": k["look"], "state": k["state"], "caps": k["caps"],
                           "effects": k["effects"], "gone": k["gone"]} for k in self.know.values()],
                "explored": round(len(self.visited) / len(all_regions()), 2),
                "monologue": list(self.monologue)[-14:], "decisions": list(self.decisions)[-8:],
                "retrieved": self.retrieved, "relationship": self.watcher, "model": self.provider.name,
                "model_available": self.provider.available(), "metrics": self.measures()}
