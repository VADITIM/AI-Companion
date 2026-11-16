"""The Moon's sections: the single source of truth for where things may be built and where a new build stands."""
import math

from ..textsim import similarity


class Sections:
    def __init__(self, rows, db):
        self.rows, self.db = {s["id"]: s for s in rows}, db

    def get(self, sid):
        return self.rows.get(sid)

    def find(self, text):
        """The section he means: its id, or the closest name."""
        text = (text or "").strip().lower()
        if text in self.rows:
            return self.rows[text]
        best = max(self.rows.values(), key=lambda s: similarity(text, s["id"] + " " + s["name"]), default=None)
        return best if best and similarity(text, best["id"] + " " + best["name"]) > 0.3 else None

    def buildable(self):
        return [s for s in self.rows.values() if s.get("builds") and self.count(s["id"]) < s["capacity"]]

    def count(self, sid):
        return self.db.val("SELECT COUNT(*) FROM builds WHERE status = 'placed' AND section_id = ?", (sid,)) or 0

    def gate(self, sid):
        """Why a build may not go there, or '' when it may."""
        s = self.rows.get(sid)
        if not s:
            return "there is no such section"
        if not s.get("builds"):
            return f"nothing may be built at {s['name']}"
        if self.count(sid) >= s["capacity"]:
            return f"{s['name']} is full"
        return ""

    def spot(self, sid, radius):
        """A free place in the section for something of this radius: rings around the middle, clear of other builds."""
        s = self.rows[sid]
        taken = [(b["x"], b["z"], footprint(b)) for b in self.db.all("SELECT x, z, recipe_json FROM builds WHERE status = 'placed' AND section_id = ?", (sid,))]
        ring = 0.0
        while ring <= s["r"] - radius * 0.5:
            n = 1 if ring == 0 else max(6, int(2 * math.pi * ring / (2 * radius + 0.6)))
            for i in range(n):
                a = 2 * math.pi * i / n + ring * 0.7
                x, z = s["x"] + math.cos(a) * ring, s["z"] + math.sin(a) * ring
                if all(math.hypot(x - tx, z - tz) > radius + tr + 0.5 for tx, tz, tr in taken):
                    return round(x, 2), round(z, 2), round((math.degrees(math.atan2(s["x"] - x, s["z"] - z)) if ring else 0.0), 1)
            ring += radius + 0.8
        return None


def footprint(build):
    """Rough radius of a placed build on the ground, from its recipe."""
    import json
    try:
        parts = json.loads(build["recipe_json"])["parts"]
    except (TypeError, ValueError, KeyError):
        return 1.5
    r = 0.6
    for p in parts:
        pos, sc = p.get("pos") or [0, 0, 0], p.get("scale") or [1, 1, 1]
        try:
            r = max(r, math.hypot(float(pos[0]), float(pos[2])) + max(float(sc[0]), float(sc[2])) / 2)
        except (TypeError, ValueError, IndexError):
            pass
    return min(r, 3.5)
