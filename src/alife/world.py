"""The world: physical reality. It owns positions, objects, time and weather, and decides what actually happens.

The mind only ever sends intentions (creature.execute_action); this module checks whether they are physically
possible, carries them out over time and reports what happened. It has no idea what the creature wants or feels.
"""
import copy
import math

SIZE = 40.0            # the island is SIZE x SIZE units
REGION = 10.0          # it is divided into 4 x 4 regions
PERCEPTION = 9.0       # how far the creature notices things
INSPECT_RANGE = 5.0
REACH = 1.6
SPEED = 2.0            # units per simulated minute

# Outcome channels an interaction can produce (positive = pleasant): food, rest, fun, expression, comfort,
# shelter, wonder, company. The mind learns what each interaction gives by doing it.
STATIC = [
    {"id": "nest", "type": "rest_place", "model": "nest", "look": "a nest of dry reeds", "pos": [8.0, 8.0],
     "caps": {"sleep": {"duration": 540, "effects": {"rest": 1.0, "comfort": 0.5}},
              "shelter": {"duration": 30, "effects": {"shelter": 0.9, "comfort": 0.2}}}},
    {"id": "apple_tree", "type": "food_source", "model": "tree", "look": "a tree with round red fruit",
     "pos": [12.0, 28.0], "stock": 4.0, "max_stock": 5, "regrow": 0.5,
     "caps": {"eat": {"duration": 8, "effects": {"food": 0.5}, "uses": True},
              "shake": {"duration": 3, "effects": {"fun": 0.15}}}},
    {"id": "berry_bush", "type": "food_source", "model": "bush", "look": "a low bush with dark berries",
     "pos": [33.0, 7.0], "stock": 6.0, "max_stock": 6, "regrow": 0.4,
     "caps": {"eat": {"duration": 6, "effects": {"food": 0.3}, "uses": True}}},
    {"id": "pond", "type": "water", "model": "pond", "look": "a still pond", "pos": [30.0, 30.0],
     "caps": {"splash": {"duration": 12, "effects": {"fun": 0.45, "comfort": -0.1}},
              "drink": {"duration": 3, "effects": {"food": 0.05, "comfort": 0.1}},
              "gaze": {"duration": 10, "effects": {"wonder": 0.25, "comfort": 0.1}}}},
    {"id": "ball", "type": "toy", "model": "ball", "look": "a light round ball", "pos": [20.0, 18.0],
     "caps": {"play": {"duration": 15, "effects": {"fun": 0.6}}}},
    {"id": "sand_patch", "type": "canvas", "model": "sand", "look": "a patch of smooth sand", "pos": [22.0, 35.0],
     "works": 0, "caps": {"create": {"duration": 20, "effects": {"expression": 0.6}}}},
    {"id": "old_log", "type": "seat", "model": "log", "look": "a mossy fallen log", "pos": [17.0, 11.0],
     "caps": {"sit": {"duration": 12, "effects": {"comfort": 0.4}}}},
    {"id": "glowing_stone", "type": "unknown", "model": "mystery", "color": "#7fe8ff",
     "look": "a faintly glowing stone", "pos": [35.0, 22.0],
     "caps": {"touch": {"duration": 3, "effects": {"wonder": 0.5, "comfort": 0.15}},
              "listen": {"duration": 6, "effects": {"wonder": 0.3}}}},
]

# Things that can turn up later. Some are pleasant, some are not; he only finds out by trying.
MYSTERIES = [
    ("a striped spiral shell", "#ffd28a", {"listen": {"duration": 6, "effects": {"wonder": 0.4, "fun": 0.1}},
                                           "roll": {"duration": 8, "effects": {"fun": 0.35}}}),
    ("a bitter-smelling red mushroom", "#ff6b6b", {"taste": {"duration": 3, "effects": {"food": 0.1, "comfort": -0.35}},
                                                   "touch": {"duration": 2, "effects": {"wonder": 0.1}}}),
    ("a humming seed pod", "#b6ff8a", {"shake": {"duration": 4, "effects": {"fun": 0.4, "wonder": 0.2}},
                                       "taste": {"duration": 3, "effects": {"food": 0.2}}}),
    ("a warm flat rock", "#ffb07a", {"sit": {"duration": 15, "effects": {"comfort": 0.5}}}),
    ("a prickly burr", "#c9a0ff", {"touch": {"duration": 2, "effects": {"comfort": -0.3}},
                                   "play": {"duration": 10, "effects": {"fun": 0.3}}}),
    ("a hollow reed that whistles", "#9ad0ff", {"blow": {"duration": 8, "effects": {"expression": 0.4, "fun": 0.2}},
                                                "listen": {"duration": 4, "effects": {"wonder": 0.2}}}),
]
UNHURRIED = {"rest", "look_around"}   # built-in actions that stretch with the pace, like object interactions
BUILTIN = {  # actions that need no object
    "rest": {"duration": 10, "effects": {"comfort": 0.2}},        # only sleep takes tiredness away
    "wait": {"duration": 2, "effects": {}},
    "look_around": {"duration": 4, "effects": {"wonder": 0.04}},   # taking a place in after walking there
    "call_out": {"duration": 2, "effects": {}},
    "sleep": {"duration": 420, "effects": {"rest": 0.7, "comfort": -0.3}},   # on bare ground: works, but poorly
}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def region_of(pos):
    n = int(SIZE / REGION) - 1
    return f"r{min(n, max(0, int(pos[0] // REGION)))}_{min(n, max(0, int(pos[1] // REGION)))}"


class World:
    def __init__(self, bus, rng, creature_id="honk", pace=1.0):
        self.bus, self.rng, self.creature_id = bus, rng, creature_id
        self.pace = pace                             # stretches how long activities take (not sleep, not walking)
        self.minute = 8 * 60.0                       # simulated minutes since midnight of day 0
        self.weather, self.weather_until = "clear", self.minute + rng.uniform(240, 600)
        self.objects = {o["id"]: copy.deepcopy(o) for o in STATIC}
        self.pos, self.heading = [9.5, 9.5], 0.0
        self.active = None
        self.done = {}                               # action_id -> result already reported (commands are idempotent)
        self.watcher_until = -1.0                    # the watcher counts as present until this minute
        self.next_spawn, self.spawned = self.minute + rng.uniform(300, 540), 0
        self.display = {}                            # what the mind asked the body to show (mood, thought)
        self._obs = 0.0

    # ------------------------------------------------------------------ time
    @property
    def is_night(self):
        m = self.minute % 1440
        return m < 6 * 60 or m >= 21 * 60

    def tick(self, dt):
        for msg in self.bus.drain_world():
            self._command(msg)
        self.minute += dt
        for o in self.objects.values():
            if o.get("regrow"):
                o["stock"] = min(o["max_stock"], o["stock"] + o["regrow"] * dt / 60)
        self._weather(dt)
        if not self.is_night and self.rng.random() < 0.004 * dt:
            self._event("bird_flyby")
        if self.minute >= self.next_spawn:
            self.next_spawn = self.minute + self.rng.uniform(360, 720)
            if sum(1 for o in self.objects.values() if o["id"].startswith("thing_")) < 4:
                self.spawn_mystery()
        self._advance(dt)
        self._obs += dt
        if self._obs >= 0.5:
            self._obs = 0.0
            self.bus.to_mind("world.observation", self.observation(), self.minute)

    def _weather(self, dt):
        if self.minute >= self.weather_until:
            r = self.rng.random()
            new = "clear" if self.weather != "clear" else ("storm" if r < 0.2 else "rain" if r < 0.75 else "clear")
            self.weather_until = self.minute + (self.rng.uniform(240, 600) if new == "clear" else self.rng.uniform(40, 150))
            if new != self.weather:
                self.weather = new
                self._event("weather", weather=new)
        if self.weather == "storm" and self.rng.random() < 0.04 * dt:
            self._event("thunder")

    def _event(self, type_, **data):
        self.bus.to_mind("world.event", {"type": type_, **data}, self.minute)

    def spawn_mystery(self, pos=None):
        look, color, caps = self.rng.choice(MYSTERIES)
        self.spawned += 1
        oid = f"thing_{self.spawned}"
        if pos is None:
            pos = [self.rng.uniform(3, SIZE - 3), self.rng.uniform(3, SIZE - 3)]
        self.objects[oid] = {"id": oid, "type": "unknown", "model": "mystery", "color": color, "look": look,
                             "pos": [round(pos[0], 1), round(pos[1], 1)], "caps": copy.deepcopy(caps)}
        return oid

    def watcher_pet(self):
        self.watcher_until = self.minute + 10
        self._event("watcher_pet")

    # ------------------------------------------------------------------ commands
    def _command(self, msg):
        p, kind = msg["payload"], msg["type"]
        if kind in ("creature.state", "creature.speak"):
            self.display.update(p)
        elif kind == "creature.cancel_action":
            if self.active and self.active["action_id"] == p.get("action_id"):
                self._finish(False, "cancelled")
        elif kind == "creature.execute_action":
            self._execute(p)

    def _execute(self, p):
        aid, action = p.get("action_id"), p.get("action")
        if not isinstance(aid, str) or not isinstance(action, str):
            return
        if aid in self.done:                          # same command again: report the same result, do nothing twice
            self.bus.to_mind("creature.action_completed", self.done[aid], self.minute)
            return
        if self.active:
            if self.active["action_id"] != aid:
                self._reject(aid, action, "busy")
            return
        target = self.objects.get(p.get("target")) if p.get("target") else None
        if p.get("target") and not target:
            return self._reject(aid, action, "no_such_object")
        act = {"action_id": aid, "action": action, "target": p.get("target"), "elapsed": 0.0, "paid": 0.0}
        if action == "move_to":
            dest = target["pos"] if target else p.get("position")
            ok = (isinstance(dest, list) and len(dest) == 2 and all(isinstance(v, (int, float)) for v in dest)
                  and 0 <= dest[0] <= SIZE and 0 <= dest[1] <= SIZE)
            if not ok:
                return self._reject(aid, action, "unreachable")
            act.update(kind="move", dest=list(dest), radius=REACH * 0.7 if target else 0.5)
        elif action == "inspect":
            if not target:
                return self._reject(aid, action, "no_such_object")
            if dist(self.pos, target["pos"]) > INSPECT_RANGE:
                return self._reject(aid, action, "too_far")
            act.update(kind="timed", duration=4.0 * self.pace, effects={})
        else:
            cap = p.get("capability") or action
            if target:
                if dist(self.pos, target["pos"]) > REACH:
                    return self._reject(aid, action, "too_far")
                spec = target["caps"].get(cap)
                if not spec:
                    return self._reject(aid, action, "cannot")
                if spec.get("uses"):
                    if target["stock"] < 1:
                        return self._reject(aid, action, "empty", {"stock": 0})
                    target["stock"] -= 1
            else:
                spec = BUILTIN.get(cap)
                if not spec:
                    return self._reject(aid, action, "cannot")
            slow = self.pace if (target and cap != "sleep") or cap in UNHURRIED else 1.0
            act.update(kind="timed", capability=cap, duration=spec["duration"] * slow, effects=dict(spec["effects"]))
            if cap == "call_out" and self.minute <= self.watcher_until:
                act["effects"] = {"company": 0.2}
        self.active = act

    def _reject(self, aid, action, reason, result=None):
        self._report({"action_id": aid, "action": action, "success": False, "reason": reason, "result": result or {}})

    def _report(self, payload):
        self.done[payload["action_id"]] = payload
        if len(self.done) > 300:
            del self.done[next(iter(self.done))]
        self.bus.to_mind("creature.action_completed", payload, self.minute)

    def _advance(self, dt):
        a = self.active
        if not a:
            return
        a["elapsed"] += dt
        if a["kind"] == "move":
            d = dist(self.pos, a["dest"])
            if d <= a["radius"]:
                return self._finish(True)
            step = min(SPEED * dt, d - a["radius"] * 0.9)
            self.heading = math.atan2(a["dest"][0] - self.pos[0], a["dest"][1] - self.pos[1])
            self.pos[0] += (a["dest"][0] - self.pos[0]) / d * step
            self.pos[1] += (a["dest"][1] - self.pos[1]) / d * step
            return
        frac = min(1.0, a["elapsed"] / a["duration"])
        if frac >= 1.0 or (frac - a["paid"]) * a["duration"] >= 1.0:      # report about once a simulated minute
            share = frac - a["paid"]
            a["paid"] = frac
            self.bus.to_mind("creature.action_progress", {
                "action_id": a["action_id"], "progress": round(frac, 3),
                "effects": {k: round(v * share, 4) for k, v in a["effects"].items()}}, self.minute)
        if frac >= 1.0:
            self._finish(True)

    def _finish(self, success, reason=None):
        a, self.active = self.active, None
        o = self.objects.get(a["target"]) if a["target"] else None
        result = {"position": [round(v, 2) for v in self.pos]}
        if success and a["action"] == "inspect":
            result.update(type=o["type"], look=o["look"], capabilities=sorted(o["caps"]), stock=self._stock(o))
        elif success and o and a["kind"] == "timed":
            if o["model"] == "ball":                    # it rolls away a little
                o["pos"] = [min(SIZE - 2, max(2, o["pos"][0] + self.rng.uniform(-3, 3))),
                            min(SIZE - 2, max(2, o["pos"][1] + self.rng.uniform(-3, 3)))]
            if "works" in o:
                o["works"] += 1
            result["stock"] = self._stock(o)
        payload = {"action_id": a["action_id"], "action": a["action"], "success": success, "result": result}
        if reason:
            payload["reason"] = reason
        self._report(payload)

    @staticmethod
    def _stock(o):
        return int(o["stock"]) if "stock" in o else None

    # ------------------------------------------------------------------ what can be perceived
    def observation(self):
        near = []
        for o in self.objects.values():
            d = dist(self.pos, o["pos"])
            if d <= PERCEPTION:
                item = {"id": o["id"], "type": o["type"], "look": o["look"], "distance": round(d, 2),
                        "position": [round(v, 2) for v in o["pos"]], "visible": True}
                if "stock" in o:
                    item["stock"] = int(o["stock"])
                near.append(item)
        a = self.active
        return {"creature_id": self.creature_id, "position": [round(v, 2) for v in self.pos],
                "region": region_of(self.pos),
                "time": {"minute": round(self.minute, 2), "day": int(self.minute // 1440),
                         "minute_of_day": round(self.minute % 1440, 1), "is_night": self.is_night},
                "weather": self.weather,
                "sheltered": any("shelter" in o["caps"] and dist(self.pos, o["pos"]) <= 2.2 for o in self.objects.values()),
                "watcher_present": self.minute <= self.watcher_until,
                "active_action": {"action_id": a["action_id"], "action": a["action"]} if a else None,
                "nearby_objects": near}

    def advance_offline(self, minutes):
        """The program was closed: move the clock on in one step instead of replaying every tick."""
        self.minute += minutes
        self.active = None
        self.weather, self.weather_until = "clear", self.minute + self.rng.uniform(120, 480)
        for o in self.objects.values():
            if o.get("regrow"):
                o["stock"] = min(o["max_stock"], o["stock"] + o["regrow"] * minutes / 60)

    # ------------------------------------------------------------------ viewer and persistence
    def snapshot(self):
        a = self.active
        return {"minute": round(self.minute, 2), "is_night": self.is_night, "weather": self.weather, "size": SIZE,
                "creature": {"pos": [round(v, 3) for v in self.pos], "heading": round(self.heading, 3),
                             "action": (a.get("capability") or a["action"]) if a else None,
                             "progress": round(min(1, a["elapsed"] / a["duration"]), 3) if a and a["kind"] == "timed" else None},
                "objects": [{"id": o["id"], "model": o["model"], "look": o["look"], "pos": o["pos"],
                             "color": o.get("color"), "stock": self._stock(o), "works": o.get("works")}
                            for o in self.objects.values()],
                "display": self.display}

    def to_dict(self):
        return {"minute": self.minute, "weather": self.weather, "weather_until": self.weather_until,
                "objects": self.objects, "pos": self.pos, "heading": self.heading, "next_spawn": self.next_spawn,
                "spawned": self.spawned}

    def from_dict(self, d):
        for k in ("minute", "weather", "weather_until", "objects", "pos", "heading", "next_spawn", "spawned"):
            setattr(self, k, d[k])
        self.active = None
