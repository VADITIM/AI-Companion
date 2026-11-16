"""Utility-based choice: U(a) = sum_i w_i(a) * N_i + P(a), then feasibility, cooldowns and bounded exploration."""
import math

from .state import CHANNEL_NEED, URGENT
from .world import REGION, SIZE, dist

# instincts: what he expects from a capability before he has ever tried it
PRIORS = {"eat": {"food": 0.4}, "sleep": {"rest": 0.9}, "play": {"fun": 0.4}, "create": {"expression": 0.4},
          "shelter": {"shelter": 0.7}}
VERB = {"eat": "eat from", "sleep": "sleep in", "play": "play with", "create": "make something at",
        "shelter": "take shelter in", "inspect": "look closely at"}


def label(cap, look):
    return f"{VERB[cap]} {look}" if cap in VERB else f"{cap} {look}"


def gain(effects, needs):
    """How much settling these effects is worth right now, and which needs they serve."""
    total, serves = 0.0, []
    for ch, amount in effects.items():
        n = CHANNEL_NEED.get(ch)
        if not n:
            continue
        level = needs.v[n]
        if amount > 0:
            g = min(amount, level) * (0.5 + level)
            if g > 0.03 and amount >= 0.12:          # a sip or a crumb does not count as dealing with a need
                serves.append(n)
            total += g
        else:
            total += amount * 0.8
    return total, serves


def region_center(name):
    i, j = (int(x) for x in name[1:].split("_"))
    return [(i + 0.5) * REGION, (j + 0.5) * REGION]


def all_regions():
    n = int(SIZE / REGION)
    return [f"r{i}_{j}" for i in range(n) for j in range(n)]


def candidates(m):
    """Every activity that is possible right now, scored. `m` is the mind (read only)."""
    needs, traits, out = m.needs, m.traits, []
    cur = needs.v["curiosity"]
    for k in m.know.values():
        if k.get("gone") or k.get("blocked_until", 0) > m.now:
            continue
        d = dist(m.pos, k["pos"])
        if k["state"] == "OBSERVED":
            out.append({"key": f"inspect:{k['id']}", "cap": "inspect", "target": k["id"],
                        "label": label("inspect", k["look"]), "base": 0.6 * cur + 0.12 + 0.1 * traits["curiosity"],
                        "serves": ["curiosity"], "dist": d})
            continue
        for cap in k["caps"]:
            learned = k["effects"].get(cap)
            if learned is not None:
                base, serves = gain(learned, needs)
            elif cap in PRIORS:
                base, serves = gain(PRIORS[cap], needs)
                base += 0.1 * cur
            else:                                    # never tried, no instinct: worth it only out of curiosity
                base, serves = 0.45 * cur * (1 - 0.5 * traits["cautiousness"]) + 0.08, ["curiosity"]
            if cap == "sleep":
                if needs.v["fatigue"] < (0.35 if m.is_night else 0.8):   # sleeps at night, naps only when worn out
                    continue
                if m.is_night and needs.v["fatigue"] > 0.4:
                    base += 0.25
            if base < 0.1 and learned is not None:
                continue
            out.append({"key": f"{cap}:{k['id']}", "cap": cap, "target": k["id"], "label": label(cap, k["look"]),
                        "base": base, "serves": serves, "dist": d, "untried": learned is None})
    unseen = [r for r in all_regions() if r not in m.visited]
    if unseen:
        r = min(unseen, key=lambda r: dist(m.pos, region_center(r)) + m.rng.uniform(0, 6))
        base = 0.5 * cur * (0.5 + traits["curiosity"]) + 0.1
        what = "explore ground I have not seen"
    else:
        r = min((r for r in all_regions() if r != m.region), key=lambda r: m.visited.get(r, 0) + m.rng.uniform(0, 120))
        base, what = 0.22 * cur + 0.05, "wander somewhere I have not been for a while"
    c = region_center(r)
    spot = [min(SIZE - 1, max(1, c[0] + m.rng.uniform(-3, 3))), min(SIZE - 1, max(1, c[1] + m.rng.uniform(-3, 3)))]
    out.append({"key": "explore", "cap": "explore", "target": None, "position": spot, "region": r, "label": what,
                "base": base, "serves": ["curiosity"], "dist": dist(m.pos, spot)})
    out.append({"key": "rest", "cap": "rest", "target": None, "label": "rest where I am",
                "base": 0.15 * needs.v["fatigue"] + 0.4 * needs.v["comfort"] - 0.03, "serves": ["comfort"], "dist": 0})
    out.append({"key": "call_out", "cap": "call_out", "target": None, "label": "call out to see if anyone answers",
                "base": 0.3 * needs.v["social"] * (0.5 + traits["sociability"]), "serves": ["social"], "dist": 0})
    if needs.v["fatigue"] >= 0.8 and not any("sleep" in k["caps"] and not k.get("gone") for k in m.know.values()):
        out.append({"key": "sleep:ground", "cap": "sleep", "target": None, "label": "sleep on the bare ground",
                    "base": gain({"rest": 0.7, "comfort": -0.3}, needs)[0], "serves": ["fatigue"], "dist": 0})
    for c in out:
        u = c["base"] - 0.006 * c["dist"]
        u += m.prefs.get(c["key"], 0.0)                                   # learned likes and dislikes
        u -= 0.15 * sum(1 for key in list(m.recent)[-6:] if key == c["key"])  # do not repeat yourself
        if m.now - m.cooldown.get(c["key"], -1e9) < (120 if c["cap"] == "call_out" else 20):
            u -= 0.3
        if m.goals.advances(c, m):
            u += 0.25
            c["goal"] = True
        c["utility"] = u + m.rng.gauss(0, 0.04 * (0.5 + traits["playfulness"]))
    out.sort(key=lambda c: -c["utility"])
    return out


def choose(cands, m):
    """An urgent need wins outright. Otherwise sample among the best few, so he is not a clockwork."""
    for need in m.needs.urgent():
        serving = [c for c in cands if need in c["serves"] and c["cap"] != "call_out"]
        if serving:
            return serving[0], f"urgent {need}"
        if need in ("hunger", "fatigue"):
            untested = [c for c in cands if c["cap"] == "inspect" or c.get("untried")]
            pick = min(untested, key=lambda c: c["dist"]) if untested else next(c for c in cands if c["cap"] == "explore")
            # looking for an answer counts as acting on the need, so the search itself is not interrupted
            return {**pick, "serves": [*pick["serves"], need]}, f"urgent {need}, nothing known that helps"
    top = cands[:3]
    weights = [math.exp((c["utility"] - top[0]["utility"]) / 0.08) for c in top]
    pick = m.rng.choices(top, weights)[0]
    return pick, "highest utility" if pick is top[0] else "close second, chosen for variety"


def urgent_alternative(cands, m, serving_now):
    """While busy: is there an urgent need the current plan does nothing for, and something that would help?"""
    for need in m.needs.urgent():
        if need in serving_now or m.needs.v[need] < URGENT:
            continue
        if any(need in c["serves"] for c in cands):
            return need
    return None
