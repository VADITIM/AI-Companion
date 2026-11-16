"""Questions, visitors, builds, the vault and the whole loop. Run: python3 -m unittest discover tests"""
import unittest

import helpers
from honk import config, snapshot
from honk.db import DB
from honk.foundry.foundry import check_recipe
from honk.mind.client import MindError, parse_json
from honk.mind.questions import Questions
from honk.mind import schemas
from honk.stubs.fake_foundry import FakeFoundry
from honk.stubs.fake_mind import FakeMind


class QuestionRules(unittest.TestCase):
    def setUp(self):
        self.p = config.load()
        self.q = Questions(DB(), self.p)

    def add(self, text, origin="self", parent=None, interest=0.5, web=False):
        return self.q.add(text, "", origin, web, interest, 0.0, parent)

    def test_dedupe_merges_the_same_question(self):
        a, v = self.add("What did a lighthouse keeper do at night?")
        b, w = self.add("What did lighthouse keepers do at night?")
        self.assertEqual((v, w, a), ("new", "merged", b))
        self.assertGreater(self.q.get(a)["interest"], 0.5)
        self.assertEqual(self.add("How is bread baked?")[1], "new")

    def test_depth_cap_but_not_for_visitors(self):
        parent = self.add("Why do tides rise at all?")[0]
        texts = ["What pulls the sea water upward?", "How heavy is the whole Moon?", "Who first weighed the Moon?", "Where did that person live?"]
        verdicts = []
        for t in texts:
            parent2, v = self.add(t, parent=parent)
            verdicts.append(v)
            parent = parent2 or parent
        self.assertEqual(verdicts, ["new", "new", "new", "deep"])
        self.assertEqual(self.add("Where did that person live then?", origin="visitor:abc", parent=parent)[1], "new")

    def test_backlog_cap_parks_the_weakest_and_never_a_visitor(self):
        subjects = "tides bread bells kites maps clocks bridges gardens choirs looms teas seeds lamps boats drums flutes wells mills roads ships coins masks dolls stamps knots sails pots inks nets rugs".split()
        for i, s in enumerate(subjects):
            self.add(f"Who invented {s}?", interest=0.2 + i * 0.02)
        self.add("Please tell me about owls", origin="visitor:x", interest=0.01)
        parked = self.q.triage(1.0)
        self.assertEqual(len(self.q.open()), self.p["mind"]["backlog_cap"])
        self.assertTrue(all(not x["origin"].startswith("visitor") for x in parked))
        self.assertLess(max(x["interest"] for x in parked), min(x["interest"] for x in self.q.open() if x["origin"] == "self"))

    def test_lockout_and_parking_after_failed_tries(self):
        qid = self.add("What is a carillon made of?")[0]
        self.assertEqual(self.q.head(10)["id"], qid)
        self.q.failed(self.q.get(qid), 10, 1.0)
        self.assertIsNone(self.q.head(11))                              # locked out for K cycles
        self.assertEqual(self.q.head(10 + self.p["mind"]["lockout_k"])["id"], qid)
        self.q.failed(self.q.get(qid), 20, 2.0)
        self.assertTrue(self.q.failed(self.q.get(qid), 30, 3.0))
        self.assertEqual(self.q.get(qid)["status"], "parked")

    def test_schema_check_and_json(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('<think>hm</think> Sure: {"a": {"b": 2}} done'), {"a": {"b": 2}})
        with self.assertRaises(MindError):
            parse_json("no json here")
        for bad in ({"answer": "x"}, {"answer": "x", "confidence": "high"}, {"answer": 3, "confidence": 0.5}, ["x"]):
            with self.assertRaises(ValueError):
                schemas.check(bad, schemas.PONDER)
        with self.assertRaises(ValueError):
            schemas.check({"choice": "explode"}, schemas.RESOLVE)


class Life(unittest.TestCase):
    def test_a_failed_call_is_skipped_and_counted_and_life_goes_on(self):
        sim = helpers.make(mind=FakeMind(5, fail_every=3))
        helpers.live(sim, 1440)
        failed = sim.db.val("SELECT COUNT(*) FROM calls WHERE ok = 0")
        self.assertGreater(failed, 20)
        self.assertGreater(sim.db.val("SELECT COUNT(*) FROM questions WHERE status = 'answered'"), 5)
        self.assertEqual(snapshot.state(sim)["mind"]["failed"], failed)

    def test_week_stays_in_bounds(self):
        sim = helpers.make()
        helpers.live(sim, 7 * 1440)
        self.assertLessEqual(len(sim.questions.open()), sim.p["mind"]["backlog_cap"])
        self.assertLessEqual(sim.vault.used(), sim.vault.size())
        self.assertGreater(sim.db.val("SELECT COUNT(*) FROM journal WHERE kind = 'journal'"), 3)
        days = sim.db.all("SELECT CAST(ts / 1440 AS INT) d, COUNT(*) n FROM builds GROUP BY d")
        self.assertTrue(all(r["n"] <= sim.p["foundry"]["per_day"] + 1 for r in days), days)
        for s in sim.sections.rows.values():
            self.assertLessEqual(sim.sections.count(s["id"]), s["capacity"])
        self.assertFalse(sim.db.val("SELECT COUNT(*) FROM builds WHERE status = 'placed' AND section_id IN ('hatch', 'postbox')"))
        snap = snapshot.state(sim, with_params=True)
        self.assertEqual(len(snapshot.builds(sim)), sim.db.val("SELECT COUNT(*) FROM builds WHERE status = 'placed'"))
        self.assertIn("feelings.valence_tau", snap["params"])

    def test_saved_and_woken_up_again(self):
        sim = helpers.make()
        helpers.live(sim, 300)
        again = helpers.Sim(sim.db, sim.p, FakeMind(), FakeFoundry(), sim.transport, seed=1)
        self.assertEqual(again.clock, sim.clock)
        self.assertEqual(again.sched.s, sim.sched.s)
        self.assertAlmostEqual(again.view()["mood"], sim.view()["mood"])

    def test_param_change_is_live_and_logged(self):
        sim = helpers.make()
        sim.set_param("feelings.valence_base", 0.9)
        self.assertEqual(sim.p["feelings"]["valence_base"], 0.9)
        row = sim.db.one("SELECT * FROM param_changes")
        self.assertEqual((row["key"], row["old"], row["new"]), ("feelings.valence_base", "0.25", "0.9"))
        for bad in ("feelings.nope", "feelings.W", "feelings"):
            with self.assertRaises((KeyError, ValueError, TypeError)):
                sim.set_param(bad, 1)
        sim.set_preset("calm")
        self.assertEqual(sim.p["feelings"]["valence_base"], 0.3)
        self.assertIs(sim.questions.p, sim.p)

    def test_kill_switch(self):
        sim = helpers.make()
        sim.flags["paused"] = True
        helpers.live(sim, 200)
        self.assertEqual((sim.clock, sim.db.val("SELECT COUNT(*) FROM calls")), (0.0, 0))


class Visitors(unittest.TestCase):
    def card(self, sim, text, name="Mira", answers=None):
        return sim.postcards.accept(name, text, "1.2.3.4", sim.clock, answers)["id"]

    def status(self, sim, rid):
        return next(r for r in sim.postcards.public() if r["id"] == rid)

    def follow(self, sim, rid, minutes):
        seen = []
        for _ in range(minutes * 2):
            sim.tick(0.5) if len(seen) % 1 == 0 and _ % 2 == 0 else sim.think()
            s = self.status(sim, rid)["status"].split(" ")
            s = "in cargo" if s[0] == "in" else s[0]
            if not seen or seen[-1] != s:
                seen.append(s)
            if s == "replied":
                break
        return seen

    def test_request_goes_through_every_state(self):
        sim = helpers.make()
        rid = self.card(sim, "What causes the tides of the sea?")      # nothing he remembers answers this yet; a cargo will
        # "researched" is set too, but research, the answer and the reply happen in one thought, so it is never seen from outside
        self.assertEqual(self.follow(sim, rid, 900), ["queued", "in cargo", "read", "replied"])
        row = sim.db.one("SELECT * FROM requests WHERE id = ?", (rid,))
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM gateway_log WHERE who = ? AND kind = 'fetch' AND ok = 1", (f"q{row['question_id']}",)))
        self.assertIn("Moon", row["reply"])
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM memories WHERE kind = 'reply'"))
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM events WHERE kind = 'reply' AND text LIKE 'To Mira:%'"))

    def test_when_no_cargo_knows_he_says_so(self):
        sim = helpers.make()
        rid = self.card(sim, "What is a zeppelin harbour?")
        self.assertEqual(self.follow(sim, rid, 3000)[-1], "replied")
        self.assertIn("I do not know", sim.db.one("SELECT reply FROM requests WHERE id = ?", (rid,))["reply"])

    def test_he_promises_the_next_cargo_when_he_does_not_know(self):
        sim = helpers.make()
        rid = self.card(sim, "What is a zeppelin harbour?")
        helpers.live(sim, 3)
        row = self.status(sim, rid)
        self.assertEqual(row["status"], "queued")
        self.assertIn("next cargo", row["reply"])

    def test_postcards_are_capped_cleaned_and_rate_limited(self):
        sim = helpers.make()
        rid = self.card(sim, "<script>x</script> " + "long " * 400)
        text = self.status(sim, rid)["text"]
        self.assertLessEqual(len(text), sim.p["visitors"]["max_chars"])
        self.assertNotIn("<", text)
        with self.assertRaises(ValueError):
            self.card(sim, " ")
        for _ in range(sim.p["visitors"]["per_hour"] - 1):
            self.card(sim, "hello again")
        with self.assertRaises(ValueError):
            self.card(sim, "one too many")
        self.card(sim, "someone else may still write", name="Tomas")

    def test_a_harsh_visitor_stings_but_cannot_sink_him(self):
        sim = helpers.make()
        before = sim.view()["mood"]
        for i in range(5):
            self.card(sim, "you are stupid and useless and boring", name="Grump")
        helpers.live(sim, 2, think=False)
        after = sim.view()["mood"]
        self.assertLess(after, before)
        self.assertGreater(after, before - sim.p["feelings"]["cap_per_hour"] - 0.05)

    def test_answering_his_question_is_remembered(self):
        sim = helpers.make()
        sim.db.put("asks", [{"id": 1, "text": "Do you still have bread where you live?", "question_id": None, "ts": 0}])
        self.card(sim, "Yes, we bake it on hot stones.", answers=1)
        helpers.live(sim, 2)
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM memories WHERE kind = 'told' AND text LIKE '%hot stones%'"))


class Builds(unittest.TestCase):
    def test_request_becomes_a_placed_build(self):
        sim = helpers.make()
        self.assertEqual(sim.foundry.gate("garden", "a small tower for tides"), "")
        bid = sim.foundry.request("garden", "a small tower for tides", "to show what a tide is", "quiet, a bit lonely", None)
        self.assertEqual(sim.foundry.gate("garden", "a bell"), "the Foundry is already building something")     # the lock
        helpers.live(sim, 1, think=False)
        b = sim.db.one("SELECT * FROM builds WHERE id = ?", (bid,))
        self.assertEqual((b["status"], b["qc1"][:6], b["qc2"][:6]), ("placed", "passed", "passed"))
        s = sim.sections.get("garden")
        self.assertLessEqual(((b["x"] - s["x"]) ** 2 + (b["z"] - s["z"]) ** 2) ** 0.5, s["r"])
        self.assertEqual(len(snapshot.builds(sim)), 1)
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM memories WHERE kind = 'built'"))
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM events WHERE kind = 'build' AND text LIKE 'New on the Moon%'"))

    def test_a_bad_build_is_dropped_and_he_hears_why(self):
        class Bad(FakeFoundry):
            def chat(self, name, system, user, schema, temperature=0.7, max_tokens=500):
                if name == "foundry_review":
                    return {"ok": True}
                return {"name": "mess", "parts": [{"shape": "box", "pos": [0, 0.5, 0], "scale": [1, 1, 1], "color": "red"},
                                                  {"shape": "box", "pos": [4, 5, 0], "scale": [0.3, 0.3, 0.3], "color": "red"},
                                                  {"shape": "blob", "pos": [0, 0, 0]}, {"shape": "cone", "pos": [-4, 3, 2], "scale": [0.3, 0.3, 0.3]}]}

        sim = helpers.make(foundry=Bad())
        mood = sim.view()["purpose"]
        bid = sim.foundry.request("garden", "a statue of the wind", "because", "airy", None)
        helpers.live(sim, 1, think=False)
        b = sim.db.one("SELECT * FROM builds WHERE id = ?", (bid,))
        self.assertEqual(b["status"], "dropped")
        self.assertIn("float", b["drop_reason"])
        self.assertTrue(b["qc1"].startswith("failed"))
        self.assertEqual(snapshot.builds(sim), [])
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM events WHERE text LIKE '%was dropped%'"))
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM questions WHERE text LIKE 'Why did my a statue of the wind not work out%'"))
        self.assertLess(sim.view()["purpose"], mood)
        self.assertEqual(sim.db.val("SELECT COUNT(*) FROM calls"), 0)             # the Foundry is not the mind

    def test_review_can_reject(self):
        class Picky(FakeFoundry):
            def chat(self, name, *a, **k):
                return {"ok": False, "reason": "It looks like a lamp, not a bell."} if name == "foundry_review" else super().chat(name, *a, **k)

        sim = helpers.make(foundry=Picky())
        sim.foundry.request("garden", "a bell for the choir", "", "", None)
        helpers.live(sim, 1, think=False)
        b = sim.db.one("SELECT * FROM builds")
        self.assertEqual(b["status"], "dropped")
        self.assertIn("not a bell", b["drop_reason"])

    def test_the_gate(self):
        sim = helpers.make()
        self.assertIn("no such section", sim.foundry.gate("basement", "a tower"))
        self.assertIn("nothing may be built", sim.foundry.gate("hatch", "a tower"))
        self.assertIn("content rules", sim.foundry.gate("garden", "a nude statue"))
        sim.foundry.request("garden", "a tower", "", "", None)
        helpers.live(sim, 1, think=False)
        self.assertIn("budget", sim.foundry.gate("garden", "a bench by the pond"))        # one per hour
        sim.clock += 61
        self.assertIn("same thing", sim.foundry.gate("garden", "a tower"))
        self.assertEqual(sim.foundry.gate("garden", "a bench by the pond"), "")

    def test_recipe_checks(self):
        self.assertFalse(check_recipe({"parts": "x"}, "t", 40)["ok"])
        self.assertFalse(check_recipe({"parts": [{"shape": "box"}] * 60}, "t", 40)["ok"])
        self.assertTrue(check_recipe({"parts": [{"shape": "box", "pos": [0, 0.5, 0], "scale": [1, 1, 1], "text": "naked"}] * 3}, "t", 40).get("banned"))
        ok = check_recipe({"parts": FakeFoundry().chat("foundry", "", "The keeper asks for: a lantern", {})["parts"]}, "lantern", 40)
        self.assertTrue(ok["ok"], ok)
        self.assertTrue(all(set(p) == {"shape", "pos", "scale", "rot", "color", "glow"} for p in ok["recipe"]["parts"]))


class VaultRules(unittest.TestCase):
    def test_full_vault_forces_a_release_with_a_reason(self):
        sim = helpers.make(**{"vault.slots": 3, "vault.shelf_bonus": 0})
        helpers.live(sim, 3 * 1440)
        self.assertEqual(sim.vault.used(), sim.vault.size())
        released = sim.vault.items("released")
        self.assertTrue(released)
        self.assertTrue(all(r["released_reason"] for r in released))
        self.assertTrue(sim.db.val("SELECT COUNT(*) FROM events WHERE kind = 'vault' AND text LIKE '%go from the vault%'"))

    def test_a_shelf_makes_room(self):
        sim = helpers.make()
        size = sim.vault.size()
        sim.foundry.request("vault", "a shelf for bells", "", "", None)
        helpers.live(sim, 1, think=False)
        self.assertEqual(sim.vault.size(), size + sim.p["vault"]["shelf_bonus"])


if __name__ == "__main__":
    unittest.main()
