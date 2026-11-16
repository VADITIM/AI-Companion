"""The cargo window and the gateway. Run: python3 -m unittest discover tests"""
import random
import unittest

import helpers
from honk import config
from honk.cargo.scheduler import ARRIVED, CLOSED, CLOSING, OPEN, Scheduler
from honk.db import DB
from honk.gateway import policy
from honk.gateway.cassette import Cassette
from honk.gateway.gateway import CLOSED_MESSAGE, Gateway, Refused


class Window(unittest.TestCase):
    def test_a_day_of_windows(self):
        p = config.load()
        s = Scheduler(p, rnd=random.Random(2))
        log, state_at = [], {}
        for t in range(1, 1441):
            for change in s.tick(float(t), unpacked=s.state == ARRIVED and t - s.s["since"] >= 3):
                log.append((change, t))
            state_at[t] = s.state
        opens = [t for c, t in log if c == "open"]
        closes = [t for c, t in log if c == "closed"]
        arrivals = [t for c, t in log if c == "arrived"]
        self.assertGreater(len(closes), 5)
        for o, c in zip(opens, closes):
            self.assertEqual(c - o, p["cargo"]["window_min"])           # the hatch is open for 60 minutes
            self.assertEqual(state_at[c - 5], CLOSING)                  # and winds down in the last ten
        for c, a in zip(closes, arrivals[1:]):                          # the gap is measured from the close
            self.assertTrue(p["cargo"]["gap_min"] <= a - c <= p["cargo"]["gap_max"] + 1, (c, a))
        self.assertEqual(s.ledger, p["cargo"]["ledger"] - len(arrivals))

    def test_ledger_ends_the_story_but_cargo_keeps_coming(self):
        s = Scheduler(config.load(overrides={"cargo.ledger": 2}), rnd=random.Random(1))
        for t in range(1, 2000):
            s.tick(float(t), unpacked=True)
        self.assertEqual(s.ledger, 0)
        self.assertTrue(s.story_over)
        self.assertGreater(s.window, 3)

    def test_unpacking_waits_while_he_sleeps(self):
        s = Scheduler(config.load(), rnd=random.Random(1))
        t = 0.0
        while s.state == CLOSED:
            t += 1
            s.tick(t)
        for _ in range(200):
            t += 1
            s.tick(t, asleep=True)
        self.assertEqual(s.state, ARRIVED)
        s.tick(t + 1, asleep=False)
        self.assertEqual(s.state, OPEN)


class Hatch(unittest.TestCase):
    def setUp(self):
        self.p = config.load(overrides={"gateway.searches": 2, "gateway.fetches": 3})
        self.s = Scheduler(self.p, rnd=random.Random(1))
        self.db = DB()
        self.g = Gateway(self.p, self.db, self.s, Cassette(self.p))

    def open(self):
        self.s.s.update(state=OPEN, opened=0.0, window=self.s.window + 1)

    def test_closed_hatch_refuses_and_counts(self):
        for call in (lambda: self.g.search("tides"), lambda: self.g.fetch("https://cassette.example/tides"), lambda: self.g.topic("tide"), lambda: self.g.random()):
            with self.assertRaises(Refused) as e:
                call()
            self.assertEqual(str(e.exception), CLOSED_MESSAGE)
        self.assertEqual(self.g.refused, 4)
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM gateway_log WHERE ok = 0"), 4)
        self.assertEqual(self.db.val("SELECT COALESCE(SUM(bytes), 0) FROM gateway_log"), 0)

    def test_feeds_while_unpacking_but_no_research(self):
        self.s.s.update(state=ARRIVED, window=1)
        self.assertTrue(self.g.topic("tide"))
        with self.assertRaises(Refused):
            self.g.search("tides")

    def test_budget_and_cache(self):
        self.open()
        self.g.search("tides")
        self.g.search("tides")                      # the same search again costs nothing
        self.assertEqual(self.g.budget()["searches"]["used"], 1)
        self.g.search("bread")
        with self.assertRaises(Refused):
            self.g.search("bells")
        self.open()                                 # a new window: a new budget
        self.assertEqual(self.g.budget()["searches"]["used"], 0)
        self.assertTrue(self.g.search("bells"))

    def test_every_call_is_logged(self):
        self.open()
        self.g.search("tides", who="q7")
        row = self.db.one("SELECT * FROM gateway_log")
        self.assertEqual((row["kind"], row["who"], row["ok"], row["window_id"]), ("search", "q7", 1, self.s.window))

    def test_private_addresses_are_refused(self):
        for url in ("http://127.0.0.1:8765/api/state", "http://localhost/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/", "http://[::1]/",
                    "file:///etc/passwd", "ftp://example.com/x", "https://user:pw@example.com/", "https://example.com/setup.exe"):
            with self.assertRaises(ValueError, msg=url):
                policy.check_url(url)

    def test_the_mind_has_no_door_of_its_own(self):
        """Only the gateway package may open connections to the outside (model runners are local or the Foundry's API)."""
        import re
        from pathlib import Path
        src = Path(helpers.__file__).resolve().parents[1] / "src" / "honk"
        for f in src.rglob("*.py"):
            if "gateway" in f.parts or f.name == "client.py":
                continue
            self.assertFalse(re.search(r"\b(urlopen|socket\.|http\.client|requests\.get)\b", f.read_text("utf-8")), f)


class Life(unittest.TestCase):
    def test_no_web_outside_the_window(self):
        sim = helpers.make()
        helpers.live(sim, 1440)
        windows = sim.db.all("SELECT id, arrived, opened, closed FROM cargo_windows WHERE closed IS NOT NULL")
        self.assertGreater(len(windows), 3)
        for row in sim.db.all("SELECT ts, kind, window_id FROM gateway_log WHERE ok = 1"):
            w = next(w for w in windows + sim.db.all("SELECT id, arrived, opened, closed FROM cargo_windows WHERE closed IS NULL") if w["id"] == row["window_id"])
            self.assertGreaterEqual(row["ts"], w["arrived"])
            if w["closed"]:
                self.assertLessEqual(row["ts"], w["closed"])
            if row["kind"] in ("search", "fetch"):
                self.assertGreaterEqual(row["ts"], w["opened"])


if __name__ == "__main__":
    unittest.main()
