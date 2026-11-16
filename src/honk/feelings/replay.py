"""Replay tuning: run the feelings engine over an event log under any preset and print the behaviour metrics.

    python3 -m honk.feelings.replay --days 30 --preset calm      (a made-up but typical life, same seed = same log)
    python3 -m honk.feelings.replay --db data/honk.db            (what really happened to him)

No model calls and no waiting: 30 simulated days take well under a second.
"""
import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from honk import config  # noqa: E402
from honk.feelings import appraisal as A, engine  # noqa: E402


def synthetic(days, params, seed=1):
    """A typical life as a list of feelings events: cargo cycles, answers, postcards, builds."""
    r, c, out, t, end = random.Random(seed), params["cargo"], [], 0.0, days * 1440.0
    ledger, left = c["ledger"], c["ledger"]
    topics = ["tide", "bread", "bell", "map", "choir", "kite", "seed", "clock", "bridge", "loom", "tea", "star"]

    def add(e, at):
        out.append({**e, "t": at})

    while t < end:
        gap = r.uniform(c["gap_min"], c["gap_max"])
        open_web = r.randint(0, 6)
        add(A.web(open_web * 0.6), t)
        for k in range(int(gap // 25)):                       # closed: he ponders from memory, sometimes builds or gets a postcard
            at = t + (k + 0.5) * 25
            if r.random() < 0.7:
                add(A.answered(r.uniform(0.1, 0.5), r.uniform(0.3, 0.9), [r.choice(topics)]), at)
            if r.random() < 0.08:
                add(A.build_placed() if r.random() < 0.8 else A.build_dropped(), at + 5)
            if r.random() < 0.07:
                text = r.choice(["thank you, this is lovely", "hello friend, what is a tide?", "you are stupid and boring", "what do you keep?"])
                add(A.postcard(text, r.choice("abc")), at + 8)
                add(A.replied(), at + 12)
        t += gap
        left = max(0, left - 1)
        add(A.cargo_arrived(left / ledger), t)
        for k in range(c["slots"]):                           # unpacking
            topic = r.choice(topics)
            add(A.item_judged(r.random() < 0.35, r.random(), r.uniform(0.2, 1.0), "", [topic]), t + 1 + k * 0.7)
        t += 10
        add(A.web(0.0), t)
        for k in range(r.randint(2, 7)):                      # the window: research answers what was waiting
            add(A.answered(r.uniform(0.2, 0.7), r.uniform(0.4, 1.0), [r.choice(topics)]), t + (k + 1) * 7)
        if r.random() < 0.3:
            add(A.budget_out(), t + 50)
        t += c["window_min"]
        add(A.hatch_closed(open_web), t)
    return [e for e in out if e["t"] < end], end


def from_db(path):
    con = sqlite3.connect(path)
    rows = con.execute("SELECT ts, event_json FROM feeling_trace ORDER BY ts").fetchall()
    con.close()
    events = [{**json.loads(j), "t": ts} for ts, j in rows]
    return events, (events[-1]["t"] if events else 0.0)


def run(events, end, params, sample=5.0):
    """Step through the log, sleeping and waking by rule, sampling every few minutes. Returns the metrics."""
    f, state, i, t = params["feelings"], engine.new_state(params), 0, 0.0
    has_sleep = any(e["kind"] in ("sleep", "wake") for e in events)
    n = ok = urgent = asleep = 0
    lo, hi, vsum = 1.0, -1.0, 0.0
    while t < end:
        t += sample
        batch = []
        while i < len(events) and events[i]["t"] <= t:
            batch.append(events[i])
            i += 1
        state = engine.step(state, batch, params, t)
        v = engine.view(state, params)
        if not has_sleep:   # a made-up log has no sleep in it: use the same rule the sim loop uses
            if not state["asleep"] and v["energy"] < f["sleep_below"]:
                state = engine.step(state, [{**A.sleep(), "t": t}], params, t)
            elif state["asleep"] and v["energy"] > f["wake_above"]:
                state = engine.step(state, [{**A.wake(), "t": t}], params, t)
        n += 1
        asleep += state["asleep"]
        ok += -0.4 <= v["mood"] <= 0.8
        urgent += (not state["asleep"]) and any(u > f["urgent_enter"] for k, u in v["urgency"].items() if k != "energy")
        lo, hi, vsum = min(lo, v["mood"]), max(hi, v["mood"]), vsum + v["mood"]
    n = max(n, 1)
    return {"samples": n, "mood_in_range": ok / n, "need_urgent": urgent / n, "asleep": asleep / n,
            "mood_min": lo, "mood_max": hi, "mood_mean": vsum / n, "final": engine.view(state, params)}


def table(name, m):
    rows = [("Mood within [-0.4, 0.8]", f"{m['mood_in_range']:.1%}", "> 90%", m["mood_in_range"] > 0.9),
            ("A need urgent while awake", f"{m['need_urgent']:.1%}", "< 15%", m["need_urgent"] < 0.15),
            ("Asleep", f"{m['asleep']:.1%}", "", None),
            ("Mood min / mean / max", f"{m['mood_min']:+.2f} / {m['mood_mean']:+.2f} / {m['mood_max']:+.2f}", "", None)]
    print(f"\n{name}  ({m['samples']} samples)")
    for label, value, target, good in rows:
        print(f"  {label:<28} {value:<24} {target:<7} {'' if good is None else 'ok' if good else 'MISSED'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--preset", action="append", help="a preset name; give it twice to compare two side by side")
    ap.add_argument("--db", help="replay the real feeling trace from this database instead of a made-up life")
    args = ap.parse_args()
    for name in args.preset or [None]:
        params = config.load(preset=name)
        events, end = from_db(args.db) if args.db else synthetic(args.days, params, args.seed)
        table(name or "default", run(events, end, params))


if __name__ == "__main__":
    main()
