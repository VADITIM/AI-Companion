"""Goals. The model may propose them; this manager owns their lifecycle and decides when they are done."""
from dataclasses import asdict, dataclass, field

from .motivation import all_regions

GOAL_TYPES = ("understand", "explore_fraction", "discover", "repeat")
MAX_SHORT = 2
UNDERSTOOD = ("UNDERSTOOD", "REMEMBERED")


@dataclass
class Goal:
    id: str
    description: str
    level: int                    # 2 = short term, 3 = long term (level 1, the immediate goal, is the current plan)
    priority: float
    status: str                   # active | completed | abandoned
    created_at: float
    deadline: float | None
    parent_goal_id: str | None
    success_conditions: dict = field(default_factory=dict)
    source: str = "rule"
    finished_at: float | None = None


class GoalManager:
    def __init__(self, store):
        self.store = store
        self.goals = [Goal(**g) for g in store.load_goals()]
        self.counter = store.get_meta("goal_counter", 0)

    def active(self, level=None):
        return [g for g in self.goals if g.status == "active" and (level is None or g.level == level)]

    def current(self):
        short = self.active(2)
        return max(short, key=lambda g: g.priority) if short else None

    def seed(self, now):
        if self.active(3):
            return
        self.add("Get to know the whole island", 3, 0.5, {"type": "explore_fraction", "value": 1.0}, now)
        self.add("Understand everything I find", 3, 0.5, {"type": "understand_all", "min_objects": 8}, now)

    def add(self, description, level, priority, conditions, now, source="rule", hours=18):
        """Returns the goal, or None when it is refused (too many open goals, or the same goal again)."""
        if level == 2:
            if len(self.active(2)) >= MAX_SHORT:
                return None
            same = lambda g: {k: v for k, v in g.success_conditions.items() if k != "done"} == conditions
            if any(same(g) for g in self.active(2)):
                return None
        self.counter += 1
        parent = None
        if level == 2:
            long = self.active(3)
            want = "explore_fraction" if conditions["type"] in ("explore_fraction", "discover") else "understand_all"
            parent = next((g.id for g in long if g.success_conditions["type"] == want), long[0].id if long else None)
        g = Goal(f"goal_{self.counter:04d}", description[:140], level, priority, "active", now,
                 now + hours * 60 if level == 2 else None, parent, dict(conditions), source)
        self.goals.append(g)
        self.store.set_meta("goal_counter", self.counter)
        self.store.save_goal(asdict(g))
        return g

    def met(self, g, m):
        c = g.success_conditions
        t = c["type"]
        if t == "explore_fraction":
            return len(m.visited) / len(all_regions()) >= c["value"]
        if t == "understand":
            k = m.know.get(c["target"])
            return bool(k) and k["state"] in UNDERSTOOD
        if t == "understand_all":
            live = [k for k in m.know.values() if not k.get("gone")]
            return len(live) >= c["min_objects"] and all(k["state"] in UNDERSTOOD for k in live)
        if t == "discover":
            return sum(1 for k in m.know.values() if k["type"] == c["object_type"]) >= c["count"]
        if t == "repeat":
            return c.get("done", 0) >= c["count"]
        return False

    def check(self, m):
        """Close goals that are met or out of time. Returns the goals that changed."""
        changed = []
        for g in self.active():
            if self.met(g, m):
                g.status = "completed"
            elif g.deadline and m.now > g.deadline:
                g.status = "abandoned"
            elif g.success_conditions["type"] == "understand" and m.know.get(g.success_conditions["target"], {}).get("gone"):
                g.status = "abandoned"
            else:
                continue
            g.finished_at = m.now
            self.store.save_goal(asdict(g))
            changed.append(g)
        return changed

    def note_action(self, cap):
        for g in self.active(2):
            c = g.success_conditions
            if c["type"] == "repeat" and c["action"] == cap:
                c["done"] = c.get("done", 0) + 1
                self.store.save_goal(asdict(g))

    def advances(self, cand, m):
        g = self.current()
        if not g:
            return False
        c = g.success_conditions
        if c["type"] in ("explore_fraction", "discover"):
            return cand["cap"] == "explore" and cand.get("region") not in m.visited
        if c["type"] == "understand":
            return cand.get("target") == c["target"] and (cand["cap"] == "inspect" or cand.get("untried", False))
        if c["type"] == "repeat":
            return cand["cap"] == c["action"]
        return False

    def propose_by_rule(self, m):
        """What he picks when the model is not there to ask: the next unfinished thing, in a fixed order of concern."""
        open_objects = [k for k in m.know.values() if not k.get("gone") and k["state"] not in UNDERSTOOD]
        if open_objects:
            k = m.rng.choice(open_objects)
            return f"Find out what {k['look']} is for", {"type": "understand", "target": k["id"]}
        frac = len(m.visited) / len(all_regions())
        if frac < 1:
            nxt = min(1.0, (int(frac * 4) + 1) / 4)
            return f"See more of the island ({int(nxt * 100)}% of it)", {"type": "explore_fraction", "value": nxt}
        foods = sum(1 for k in m.know.values() if k["type"] == "food_source")
        if foods < 2:
            return "Find a second place to eat", {"type": "discover", "object_type": "food_source", "count": foods + 1}
        caps = sorted({cap for k in m.know.values() if not k.get("gone") for cap in k["caps"]} - {"sleep", "eat", "shelter"})
        lately = {g.success_conditions.get("action") for g in self.goals[-3:]}
        caps = [c for c in caps if c not in lately] or caps      # not the same pastime again and again
        if caps:
            fav = max(caps, key=lambda cap: max((v for key, v in m.prefs.items() if key.startswith(cap + ":")), default=0)
                      + m.rng.uniform(0, 0.15))
            return f"Spend some good time: {fav} three times", {"type": "repeat", "action": fav, "count": 3}
        return None
