"""Internal state the simulation owns: personality, needs and emotions. The model never writes these."""
import math

TRAITS = ("curiosity", "sociability", "creativity", "playfulness", "independence", "patience", "cautiousness")
NEEDS = ("hunger", "fatigue", "curiosity", "social", "comfort", "creativity", "play", "safety")
# growth per simulated hour while awake, and the trait that scales it (factor 0.5 + trait)
GROWTH = {"hunger": (0.075, None), "fatigue": (0.044, None), "curiosity": (0.16, "curiosity"),
          "social": (0.04, "sociability"), "comfort": (0.015, None), "creativity": (0.08, "creativity"),
          "play": (0.12, "playfulness"), "safety": (-0.4, None)}
# which need each outcome channel of the world settles
CHANNEL_NEED = {"food": "hunger", "rest": "fatigue", "fun": "play", "expression": "creativity",
                "comfort": "comfort", "shelter": "safety", "wonder": "curiosity", "company": "social"}
URGENT = 0.85
EMOTIONS = ("joy", "sadness", "curiosity", "fear", "frustration", "affection", "excitement", "calmness")


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


class Needs:
    def __init__(self, values=None):
        self.v = {n: 0.25 for n in NEEDS}
        self.v["safety"] = 0.0
        if values:
            self.v.update({k: clamp(float(x)) for k, x in values.items() if k in self.v})

    def update(self, minutes, traits, asleep=False, weather="clear", sheltered=False, is_night=False):
        h = minutes / 60
        for n, (rate, trait) in GROWTH.items():
            r = rate * (0.5 + traits[trait]) if trait else rate
            if asleep and r > 0:
                r *= 0.5 if n == "hunger" else 0.0 if n == "fatigue" else 0.2
            self.v[n] = clamp(self.v[n] + r * h)
        # an independent creature can be lonely, but loneliness alone never becomes an emergency
        self.v["social"] = min(self.v["social"], 1 - 0.5 * traits["independence"])
        if not sheltered:
            if weather != "clear":
                self.v["comfort"] = clamp(self.v["comfort"] + 0.25 * h)
            if weather == "storm":
                self.v["safety"] = clamp(self.v["safety"] + 0.9 * h)
            if is_night and not asleep:
                self.v["comfort"] = clamp(self.v["comfort"] + 0.05 * h)

    def apply(self, effects):
        """Apply outcome channels reported by the world. Positive values settle a need, negative ones raise it."""
        for ch, amount in effects.items():
            n = CHANNEL_NEED.get(ch)
            if n:
                self.v[n] = clamp(self.v[n] - amount)

    def bump(self, need, amount):
        self.v[need] = clamp(self.v[need] + amount)

    def urgent(self):
        return sorted((n for n in NEEDS if self.v[n] >= URGENT), key=lambda n: -self.v[n])

    def advance_offline(self, hours):
        """Bounded catch-up after the program was closed: he is assumed to have looked after himself, roughly."""
        self.v["hunger"] = clamp(min(0.8, self.v["hunger"] + 0.04 * hours))
        self.v["fatigue"] = 0.15 if hours >= 4 else clamp(self.v["fatigue"] + 0.03 * hours)
        for n in ("curiosity", "social", "play", "creativity"):
            self.v[n] = clamp(min(0.85, self.v[n] + 0.05 * hours))
        self.v["comfort"], self.v["safety"] = min(self.v["comfort"], 0.3), 0.0


class Emotions:
    """Each emotion moves towards a target computed from needs and recent events; it never jumps (inertia)."""
    TAU = 20.0        # simulated minutes for an emotion to cover ~63% of the distance to its target
    HALF_LIFE = 30.0  # how long the push from one event lasts

    def __init__(self, values=None, impulses=None):
        self.v = {e: 0.3 for e in EMOTIONS}
        self.v.update(values or {})
        self.impulse = {e: 0.0 for e in EMOTIONS}
        self.impulse.update(impulses or {})

    def feel(self, emotion, amount):
        self.impulse[emotion] = clamp(self.impulse[emotion] + amount, -1, 1)

    def targets(self, needs, traits, affection=0.0):
        n, i = needs.v, self.impulse
        avg, worst = sum(n.values()) / len(n), max(n.values())
        t = {"joy": 0.65 * (1 - avg) - 0.25 * worst + i["joy"],
             "sadness": 0.45 * n["social"] + 0.3 * avg - 0.2 + i["sadness"],
             "curiosity": 0.75 * n["curiosity"] + 0.2 * traits["curiosity"] + i["curiosity"],
             "fear": 0.9 * n["safety"] + i["fear"],
             "frustration": max(0.0, worst - 0.7) + i["frustration"],
             "affection": 0.5 * affection + i["affection"],
             "excitement": 0.3 * n["curiosity"] * (1 - n["fatigue"]) + i["excitement"]}
        t = {k: clamp(v) for k, v in t.items()}
        t["calmness"] = clamp(1 - max(t["fear"], t["frustration"], 0.6 * t["excitement"]) - 0.2 * n["fatigue"])
        return t

    def update(self, minutes, needs, traits, affection=0.0):
        alpha = 1 - math.exp(-minutes / self.TAU)
        for e, target in self.targets(needs, traits, affection).items():
            self.v[e] += alpha * (target - self.v[e])
        decay = 0.5 ** (minutes / self.HALF_LIFE)
        for e in self.impulse:
            self.impulse[e] *= decay

    def mood(self, needs):
        e, n = self.v, needs.v
        if e["fear"] > 0.5:
            return "cautious"
        if e["frustration"] > 0.45:
            return "irritable"
        if n["fatigue"] > 0.75:
            return "sleepy"
        if e["joy"] > 0.5 and e["excitement"] > 0.4:
            return "cheerful"
        if e["curiosity"] > 0.6 and n["fatigue"] < 0.5:
            return "adventurous"
        if e["sadness"] > 0.45:
            return "lonely"
        if e["calmness"] > 0.6:
            return "calm"
        return "content" if e["joy"] > 0.4 else "restless"
