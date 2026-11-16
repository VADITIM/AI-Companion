"""What the viewer shows: one read-only picture of Honk and his Moon. Nothing here changes him."""
import json

from . import config
from .feelings import phrases

START = 480


def state(sim, since=0, with_params=False):
    db, v, p = sim.db, sim.view(), sim.p
    day = p["sim"]["day_min"]
    win = sim.sched.window
    out = {
        # he first woke at 08:00 on day 1; "min" is minutes since then, "start" turns it into time of day
        "clock": {"min": round(sim.clock, 2), "start": START, "day": int((sim.clock + START) // day) + 1, "tod": ((sim.clock + START) % day) / day},
        "honk": {"doing": sim.doing, "asleep": v["asleep"], "emotion": v["emotion"],
                 "feel": {k: round(v[k], 3) for k in ("energy", "curiosity", "connection", "purpose", "mood", "arousal", "weight")},
                 "urgent": [k for k, u in v["urgent"].items() if u], "salient": phrases.salient(v)},
        "cargo": {"state": sim.sched.state, "window": win, "ledger": sim.sched.ledger, "ledger_size": p["cargo"]["ledger"], "story_over": sim.sched.story_over,
                  "minutes_left": round(sim.sched.minutes_left(sim.clock), 1), "budget": sim.gateway.budget(), "refused": sim.gateway.refused,
                  "items": db.all("SELECT id, slot_type, source, title, status, kept, reason FROM cargo_items WHERE window_id = ? ORDER BY id", (win,)),
                  "windows": db.all("SELECT id, arrived, opened, closed, ledger_left, summary FROM cargo_windows ORDER BY id DESC LIMIT 8")},
        "questions": {"open": db.all("SELECT id, text, why, origin, interest, needs_web, tries FROM questions WHERE status = 'open' ORDER BY interest DESC, id LIMIT 30"),
                      "recent": db.all("SELECT id, text, answer, status, resolved, confidence, origin FROM questions WHERE status != 'open' ORDER BY last_touched DESC LIMIT 25"),
                      "counts": {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM questions GROUP BY status")}},
        "vault": {"used": sim.vault.used(), "size": sim.vault.size(),
                  "items": db.all("SELECT id, title, note, quote, url, tags, interest, kept_ts FROM vault WHERE state = 'kept' ORDER BY kept_ts DESC"),
                  "released": db.all("SELECT title, released_reason, released_ts FROM vault WHERE state = 'released' ORDER BY released_ts DESC LIMIT 10")},
        "builds": db.all("SELECT id, name, thing, section_id, status, why, brief, drop_reason, qc1, qc2, ts FROM builds ORDER BY id DESC LIMIT 40"),
        "builds_rev": db.val("SELECT COALESCE(MAX(placed_ts), 0) + COUNT(*) FROM builds WHERE status = 'placed'"),
        "sections": [{**{k: s.get(k) for k in ("id", "name", "theme", "x", "z", "r", "builds", "capacity", "kind")}, "count": sim.sections.count(s["id"])} for s in sim.sections.rows.values()],
        "journal": db.all("SELECT id, ts, day, kind, text FROM journal ORDER BY id DESC LIMIT 30"),
        "postcards": sim.postcards.public(), "asks": db.get("asks", [])[-6:],
        "events": db.all("SELECT id, ts, kind, icon, text FROM events WHERE id > ? ORDER BY id DESC LIMIT 80", (since,))[::-1],
        "mind": {"model": getattr(sim.client, "name", "?"), "foundry": getattr(sim.foundry.client, "name", "?"), "building": sim.foundry.busy(),
                 "calls": db.val("SELECT COUNT(*) FROM calls"), "failed": db.val("SELECT COUNT(*) FROM calls WHERE ok = 0"),
                 "last_error": sim.mind.last_error, "paused": bool(sim.flags.get("paused")), "speed": p["sim"]["speed"],
                 "preset": sim.preset, "presets": config.presets(), "gateway": p["gateway"]["mode"]},
    }
    if with_params:
        out["params"] = config.flat(p)
        out["param_changes"] = db.all("SELECT ts, key, old, new, who FROM param_changes ORDER BY id DESC LIMIT 20")
        out["gateway_log"] = db.all("SELECT ts, window_id, kind, query_or_url, bytes, ok, who, note FROM gateway_log ORDER BY id DESC LIMIT 40")
        rows = db.all("SELECT ts, state_json FROM feeling_trace ORDER BY id DESC LIMIT 240")[::-1]
        out["trace"] = [{"ts": r["ts"], **json.loads(r["state_json"])} for r in rows]
    return out


def builds(sim):
    """Everything that stands on the Moon, with the shapes to draw it."""
    rows = sim.db.all("SELECT id, name, thing, section_id, x, z, rot, recipe_json, why, placed_ts FROM builds WHERE status = 'placed' ORDER BY id")
    return [{"id": r["id"], "name": r["name"], "thing": r["thing"], "section": r["section_id"], "x": r["x"], "z": r["z"], "rot": r["rot"], "why": r["why"],
             "placed": r["placed_ts"], "parts": json.loads(r["recipe_json"])["parts"]} for r in rows]
