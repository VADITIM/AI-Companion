"""A Foundry without a model: fixture recipes, for tests and for running the whole loop offline."""
import random

from ..mind.client import MindError

P = lambda **kw: kw   # noqa: E731

FIXTURES = {
    "cairn": [P(id="a", shape="sphere", color="stone", pos=[0, 0.35, 0], scale=[1.3, 0.7, 1.3]), P(id="b", shape="sphere", color="dark", on="a", side="top", scale=[0.9, 0.55, 0.9]),
              P(id="c", shape="sphere", color="stone", on="b", side="top", scale=[0.6, 0.4, 0.6]), P(shape="sphere", color="yellow", glow=True, on="c", side="top", scale=[0.25, 0.25, 0.25])],
    "lantern": [P(id="foot", shape="cylinder", color="navy", pos=[0, 0.1, 0], scale=[0.6, 0.2, 0.6]), P(id="pole", shape="cylinder", color="navy", on="foot", side="top", scale=[0.1, 1.6, 0.1]),
                P(id="light", shape="box", color="yellow", glow=True, on="pole", side="top", scale=[0.4, 0.45, 0.4]), P(shape="pyramid", color="plum", on="light", side="top", scale=[0.5, 0.3, 0.5])],
    "tower": [P(id="base", shape="cylinder", color="cream", pos=[0, 0.3, 0], scale=[1.6, 0.6, 1.6]), P(id="body", shape="taper", color="white", on="base", side="top", scale=[1.1, 3.2, 1.1]),
              P(id="room", shape="cylinder", color="navy", on="body", side="top", scale=[0.9, 0.5, 0.9]), P(id="lamp", shape="sphere", color="yellow", glow=True, on="room", side="top", scale=[0.5, 0.5, 0.5]),
              P(shape="cone", color="magenta", on="lamp", side="top", scale=[0.8, 0.5, 0.8])],
    "bench": [P(id="seat", shape="rbox", color="wood", pos=[0, 0.5, 0], scale=[1.8, 0.14, 0.6]), P(shape="box", color="bark", on="seat", side="bottom", off=[0.7, 0], scale=[0.14, 0.45, 0.5], mirror="x"),
              P(shape="rbox", color="wood", on="seat", side="top", off=[0, -0.25], scale=[1.8, 0.5, 0.1])],
    "shelf": [P(id="back", shape="box", color="indigo", pos=[0, 1.0, 0], scale=[2.0, 2.0, 0.12]), P(id="s1", shape="box", color="lavender", on="back", side="front", off=[0, -0.5], scale=[2.0, 0.08, 0.5]),
              P(id="s2", shape="box", color="lavender", on="back", side="front", off=[0, 0.3], scale=[2.0, 0.08, 0.5]), P(shape="box", color="mint", on="s1", side="top", off=[-0.5, 0], scale=[0.3, 0.4, 0.3]),
              P(shape="sphere", color="pink", on="s2", side="top", off=[0.4, 0], scale=[0.3, 0.3, 0.3])],
    "arch": [P(id="l", shape="box", color="stone", pos=[-0.9, 1.0, 0], scale=[0.5, 2.0, 0.6]), P(id="r", shape="box", color="stone", pos=[0.9, 1.0, 0], scale=[0.5, 2.0, 0.6]),
             P(id="top", shape="rbox", color="periwinkle", pos=[0, 2.2, 0], scale=[2.6, 0.5, 0.7]), P(shape="sphere", color="mint", glow=True, on="top", side="top", scale=[0.3, 0.3, 0.3])],
    "bell": [P(id="l", shape="cylinder", color="bark", pos=[-0.7, 1.0, 0], scale=[0.16, 2.0, 0.16]), P(id="r", shape="cylinder", color="bark", pos=[0.7, 1.0, 0], scale=[0.16, 2.0, 0.16]),
             P(id="beam", shape="box", color="wood", pos=[0, 2.05, 0], scale=[1.8, 0.16, 0.2]), P(id="bell", shape="dome", color="yellow", on="beam", side="bottom", scale=[0.7, 0.7, 0.7]),
             P(shape="sphere", color="orange", on="bell", side="bottom", scale=[0.16, 0.16, 0.16])],
}
WORDS = {"cairn": "cairn stone pile marker memorial grave", "lantern": "lantern lamp light candle", "tower": "tower lighthouse beacon mast", "bench": "bench seat chair rest",
         "shelf": "shelf case cabinet rack label", "arch": "arch gate bridge door", "bell": "bell chime clock gong"}


class FakeFoundry:
    name = "stub"

    def __init__(self, seed=3, fail_every=0):
        self.rnd, self.fail_every, self.n = random.Random(seed), fail_every, 0

    def chat(self, name, system, user, schema, temperature=0.7, max_tokens=500):
        if name == "foundry_review":
            return {"ok": True, "reason": "It reads as what was asked for."}
        self.n += 1
        if self.fail_every and self.n % self.fail_every == 0:
            raise MindError("the fixture foundry was told to fail")
        first = user.split("\n", 1)[0].lower()
        kind = next((k for k, w in WORDS.items() if any(x in first for x in w.split())), None) or self.rnd.choice(list(FIXTURES))
        return {"name": first.replace("the keeper asks for:", "").strip()[:40] or kind, "parts": [dict(p) for p in FIXTURES[kind]]}

    def status(self):
        return {"up": True, "ready": True, "note": "fixture foundry (no model)"}
