"""Property tests for the feelings engine. Run: python3 -m unittest discover tests"""
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from honk import config  # noqa: E402
from honk.feelings import appraisal as A, engine, phrases, replay  # noqa: E402

P = config.load()


def random_events(seed, n=200, span=3000.0):
    r = random.Random(seed)
    out = []
    for _ in range(n):
        e = {"t": r.uniform(0, span), "kind": "x", "source": r.choice(["a", "b", "c"]),
             "appraisal": {ax: r.uniform(-1, 1) for ax in r.sample(engine.AXES, 3)}, "topics": [r.choice("pqrs")]}
        if r.random() < 0.1:
            e["set"] = {"asleep": r.random() < 0.5, "w_open": r.uniform(0, 5), "ledger": r.random()}
        out.append(e)
    return sorted(out, key=lambda e: e["t"])


class Feelings(unittest.TestCase):
    def test_values_stay_in_range(self):
        for seed in range(20):
            s = engine.step(engine.new_state(P), random_events(seed), P, 3000)
            v = engine.view(s, P)
            for k in engine.NEEDS:
                self.assertTrue(0 <= v[k] <= 1, (k, v[k]))
            self.assertTrue(P["feelings"]["mood_floor"] <= v["mood"] <= 1)
            self.assertTrue(-1 <= v["arousal"] <= 1)
            self.assertTrue(0 <= v["weight"] <= P["feelings"]["weight_cap"])

    def test_same_events_same_state(self):
        ev = random_events(3)
        self.assertEqual(engine.step(engine.new_state(P), ev, P, 3000), engine.step(engine.new_state(P), ev, P, 3000))

    def test_step_does_not_touch_the_old_state(self):
        s = engine.new_state(P)
        before = repr(s)
        engine.step(s, random_events(1), P, 3000)
        self.assertEqual(before, repr(s))

    def test_fast_forward_equals_step_by_step(self):
        ev = random_events(5)
        whole = engine.step(engine.new_state(P), ev, P, 3000)
        s, i = engine.new_state(P), 0
        for t in range(1, 3001):          # one-minute ticks
            batch = []
            while i < len(ev) and ev[i]["t"] <= t:
                batch.append(ev[i])
                i += 1
            s = engine.step(s, batch, P, t)
        for k in engine.TARGETS:
            self.assertAlmostEqual(whole[k], s[k], places=9, msg=k)

    def test_higher_sensitivity_never_reverses_a_direction(self):
        for ax in engine.AXES:
            lo, hi = engine.new_state(P), engine.new_state(P)
            hi["sens"][ax] = 2.0
            for x in (-0.6, 0.6):
                e = [{"t": 1, "kind": "x", "appraisal": {ax: x}}]
                a, b, base = engine.step(lo, e, P, 1), engine.step(hi, e, P, 1), engine.step(lo, [], P, 1)
                for k in engine.TARGETS:
                    self.assertGreaterEqual((a[k] - base[k]) * (b[k] - base[k]), -1e-12, (ax, k))

    def test_curiosity_is_relieved_by_learning_not_by_acting(self):
        s = engine.step(engine.new_state(P), [{"t": 0, **A.web(4.0)}], P, 600)
        high = engine.view(s, P)["curiosity"]
        self.assertGreater(high, 0.8)
        acted = engine.step(s, [{"t": 600, **A.no_answer()}], P, 600)
        self.assertGreaterEqual(engine.view(acted, P)["curiosity"], high - 1e-9)
        learned = engine.step(s, [{"t": 600, **A.answered(0.6, 0.9)}], P, 600)
        self.assertLess(engine.view(learned, P)["curiosity"], high - 0.2)

    def test_one_source_cannot_sink_his_mood(self):
        s = engine.new_state(P)
        start = engine.view(s, P)["mood"]
        harsh = [{"t": i, **A.postcard("you are stupid and useless", "troll")} for i in range(1, 40)]
        s = engine.step(s, harsh, P, 40)
        self.assertGreater(engine.view(s, P)["mood"], start - P["feelings"]["cap_per_hour"] - 0.05)

    def test_habituation(self):
        s = engine.new_state(P)
        self.assertEqual(engine.habit(s, P, "tide", 0), 0)
        s = engine.step(s, [{"t": 1, "kind": "x", "topics": ["tide"]}] * 4, P, 2)
        used = engine.habit(s, P, "tide", 2)
        self.assertGreater(used, 0.7)
        self.assertLess(engine.habit(s, P, "tide", 2 + 5 * P["feelings"]["habit_tau"]), 0.05)

    def test_urgency_has_hysteresis(self):
        f = P["feelings"]
        s = engine.new_state(P)
        s["connection"], s["base"]["connection"] = 0.05, 0.05
        s = engine.step(s, [], P, 1)
        self.assertTrue(s["urgent"]["connection"])
        s["connection"] = s["base"]["connection"] = f["setpoint"]      # u = 0.5: between leave and enter, so it stays urgent
        self.assertTrue(engine.step(s, [], P, 2)["urgent"]["connection"])
        s["connection"] = s["base"]["connection"] = 0.9
        self.assertFalse(engine.step(s, [], P, 3)["urgent"]["connection"])

    def test_weight_is_capped_and_recovers(self):
        s = engine.step(engine.new_state(P), [{"t": 1, "kind": "x", "direct": {"weight": 5}, "set": {"ledger": 0.0}}], P, 1)
        self.assertLessEqual(s["weight"], P["feelings"]["weight_cap"])
        later = engine.view(s, P, 5000)
        self.assertLess(later["weight"], s["weight"])
        self.assertGreater(later["mood"], P["feelings"]["mood_floor"])

    def test_prompt_carries_at_most_two_feelings_and_no_numbers(self):
        s = engine.new_state(P)
        s.update(energy=0.05, connection=0.02, purpose=0.02, valence=-0.5, weight=0.5)
        s = engine.step(s, [], P, 1)
        v = engine.view(s, P)
        self.assertLessEqual(len(phrases.salient(v)), 2)
        self.assertFalse(any(ch.isdigit() for ch in phrases.in_words(v, random.Random(1))))
        calm = engine.view(engine.new_state(P), P)
        self.assertEqual(phrases.salient(calm), [])

    def test_thirty_days_replay_in_seconds_and_within_targets(self):
        t0 = time.time()
        results = {}
        for name in (None, "calm", "restless", "curious"):
            p = config.load(preset=name)
            events, end = replay.synthetic(30, p, seed=1)
            results[name] = replay.run(events, end, p)
        self.assertLess(time.time() - t0, 20)
        self.assertTrue(any(m["mood_in_range"] > 0.9 and m["need_urgent"] < 0.15 for m in results.values()), results)


if __name__ == "__main__":
    unittest.main()
