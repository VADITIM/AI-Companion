"""A whole Honk for tests: scripted mind, fixture Foundry, recorded pages, a database in memory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honk import config  # noqa: E402
from honk.db import DB  # noqa: E402
from honk.gateway.cassette import Cassette  # noqa: E402
from honk.loop import Sim  # noqa: E402
from honk.stubs.fake_foundry import FakeFoundry  # noqa: E402
from honk.stubs.fake_mind import FakeMind  # noqa: E402


def make(seed=5, mind=None, foundry=None, **over):
    p = config.load(overrides=over)
    p["gateway"]["mode"] = "cassette"
    return Sim(DB(), p, mind or FakeMind(seed), foundry or FakeFoundry(), Cassette(p), seed=seed)


def live(sim, minutes, think=True):
    for _ in range(int(minutes)):
        sim.tick(1.0)
        if think:
            sim.think()
