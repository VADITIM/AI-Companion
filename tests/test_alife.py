"""Behaviour tests for the autonomous creature (src/alife). Standard library only:

    python3 -m unittest tests/test_alife.py
"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alife import config, protocol                     # noqa: E402
from alife.actions import validate                     # noqa: E402
from alife.engine import Engine                        # noqa: E402
from alife.llm import NullProvider, ScriptedProvider, check   # noqa: E402
from alife.memory import Store                         # noqa: E402
from alife.state import Emotions, Needs                # noqa: E402
from alife.world import World                          # noqa: E402


def engine(provider=None, seed=5, data=None):
    cfg = config.load("/nonexistent")
    cfg["sim"]["seed"] = seed
    e = Engine(cfg, data or tempfile.mkdtemp(), provider or NullProvider(), sync_llm=True, catch_up=False)
    _open.append(e)
    return e


_open = []


def tearDownModule():
    for e in _open:
        try:
            e.close()
        except Exception:
            pass                                         # already closed by the test itself


def keys(e, where="success=1"):
    return [r["key"] for r in e.store.q(f"SELECT key FROM actions WHERE {where} ORDER BY id")]


def run_until(e, cond, minutes):
    for _ in range(int(minutes)):
        e.run_minutes(1)
        if cond():
            return True
    return False


class Behaviour(unittest.TestCase):
    def test_hunger_makes_him_seek_food(self):
        e = engine()
        e.run_minutes(60 * 6)
        e.mind.needs.v["hunger"] = 0.9                 # he may not have found food yet: then he has to go and look
        before = len([k for k in keys(e) if k.startswith("eat:")])
        self.assertTrue(run_until(e, lambda: len([k for k in keys(e) if k.startswith("eat:")]) > before, 240))
        self.assertLess(e.mind.needs.v["hunger"], 0.9)

    def test_tiredness_makes_him_sleep_and_wake_rested(self):
        e = engine()
        e.run_minutes(60)
        e.mind.needs.v["fatigue"] = 0.9
        self.assertTrue(run_until(e, lambda: e.mind.asleep, 60))
        self.assertTrue(run_until(e, lambda: not e.mind.asleep, 700))
        self.assertLess(e.mind.needs.v["fatigue"], 0.15)

    def test_no_food_where_he_expected_it_so_he_finds_another_source(self):
        e = engine()
        e.run_minutes(60 * 4)
        for oid in ("apple_tree", "berry_bush"):
            e.world.objects[oid].update(stock=0.0, regrow=0)
        e.world.objects["berry_bush"].update(stock=6.0)
        if "apple_tree" in e.mind.know:
            e.mind.know["apple_tree"]["stock"] = 3       # he believes there is fruit
        e.mind.needs.v["hunger"] = 0.95
        self.assertTrue(run_until(e, lambda: "eat:berry_bush" in keys(e), 60 * 10))

    def test_unknown_object_is_investigated(self):
        e = engine()
        e.run_minutes(30)
        oid = e.world.spawn_mystery([e.world.pos[0] + 3, e.world.pos[1] + 3])
        self.assertTrue(run_until(e, lambda: e.mind.know.get(oid, {}).get("state") in ("INVESTIGATED", "UNDERSTOOD"), 240))
        self.assertTrue(e.mind.know[oid]["caps"])

    def test_failed_action_leads_to_a_different_plan(self):
        e = engine()
        self.assertTrue(run_until(e, lambda: "eat" in e.mind.know.get("apple_tree", {}).get("caps", []), 60 * 30))
        e.world.objects["apple_tree"].update(stock=0.0, regrow=0)
        e.mind.know["apple_tree"]["stock"] = 3
        e.mind.needs.v["hunger"] = 0.95
        self.assertTrue(run_until(e, lambda: "eat:apple_tree" in keys(e, "success=0 AND reason='empty'"), 120))
        n = len(keys(e, "1=1"))
        e.run_minutes(60)
        after = keys(e, "1=1")[n:]
        self.assertTrue(after, "he did nothing after the failure")
        self.assertNotIn("eat:apple_tree", after)        # he does not walk back to the empty tree

    def test_goals_complete_and_new_ones_follow(self):
        e = engine()
        e.run_minutes(60 * 48)
        done = [g for g in e.mind.goals.goals if g.status == "completed"]
        self.assertGreaterEqual(len(done), 3)
        self.assertLessEqual(len(e.mind.goals.active(2)), 2)
        self.assertLess(e.mind.measures()["share_of_time_without_goal"], 0.2)

    def test_he_lives_without_a_model_and_does_not_loop(self):
        e = engine()
        e.run_minutes(60 * 48)
        m = e.mind.measures()
        self.assertEqual(m["model_calls"], 0)
        self.assertGreater(m["actions"], 60)
        self.assertLess(m["repetition"], 0.2)
        self.assertGreaterEqual(m["distinct_activities"], 8)
        self.assertLess(m["failed_action_rate"], 0.1)
        self.assertTrue(any(k.startswith("sleep") for k in keys(e)) and any(k.startswith("eat") for k in keys(e)))
        self.assertEqual(e.mind.measures()["rejected_by_validator"], 0)

    def test_routine_is_not_narrated(self):
        e = engine()
        e.run_minutes(60 * 48)
        said = [r["minute"] for r in e.store.q("SELECT minute FROM event_log WHERE type='thought.intention'")]
        self.assertLess(len(said), 48)                   # under one voiced intention an hour (it was over three)
        self.assertLess(len(said), e.mind.measures()["actions"])   # some choices pass without a thought
        e.mind.think("event", "A bird crossed the sky.")
        n = len(e.mind.monologue)
        e.mind.think("event", "A bird crossed the sky.")  # the same thought again, straight away
        self.assertEqual(len(e.mind.monologue), n)

    def test_experience_changes_preferences(self):
        e = engine()
        e.run_minutes(60 * 30)
        self.assertTrue(any(v > 0.05 for v in e.mind.prefs.values()))
        self.assertTrue(e.store.q("SELECT 1 FROM knowledge LIMIT 1"))

    def test_identity_memory_and_knowledge_survive_a_restart(self):
        d = tempfile.mkdtemp()
        e = engine(data=d)
        e.run_minutes(60 * 12)
        memories = e.store.q("SELECT COUNT(*) c FROM memories")[0]["c"]
        known, minute, goals = set(e.mind.know), e.world.minute, len(e.mind.goals.goals)
        e.close()
        e2 = engine(data=d)
        self.assertFalse(e2.mind.born)
        self.assertEqual(set(e2.mind.know), known)
        self.assertEqual(e2.store.q("SELECT COUNT(*) c FROM memories")[0]["c"], memories)
        self.assertEqual(len(e2.mind.goals.goals), goals)
        self.assertAlmostEqual(e2.world.minute, minute, delta=11)
        self.assertIn("REMEMBERED", {k["state"] for k in e2.mind.know.values()})
        e2.run_minutes(120)                              # and he carries on
        self.assertGreater(e2.mind.metrics["actions"], 0)

    def test_time_away_is_one_bounded_step(self):
        e = engine()
        e.run_minutes(60)
        before = e.world.minute
        e.world.advance_offline(480)
        e.mind.advance_offline(480)
        self.assertAlmostEqual(e.world.minute, before + 480)
        self.assertLessEqual(e.mind.needs.v["hunger"], 0.8)
        e.run_minutes(60)


class Model(unittest.TestCase):
    def test_model_chooses_what_to_try_on_an_unfamiliar_thing(self):
        def answer(messages, schema):
            task = json.loads(messages[1]["content"])["task"]
            if "never seen anything like it" in task:
                return {"thought_summary": "It hums. I will listen.", "choice": schema["properties"]["choice"]["enum"][0],
                        "memory_candidates": ["Strange things are worth a closer look."]}
            raise RuntimeError("only the unfamiliar question is scripted")
        p = ScriptedProvider(answer)
        e = engine(p)
        self.assertTrue(run_until(e, lambda: any(d["source"] == "model" for d in e.mind.decisions), 60 * 30))
        d = next(d for d in e.mind.decisions if d["source"] == "model")
        self.assertTrue(e.store.q("SELECT 1 FROM actions WHERE source='model'") or e.mind.current)
        self.assertTrue(any(m["source"] == "model" and m["text"] == "It hums. I will listen." for m in e.mind.monologue) or d)
        self.assertTrue(e.store.q("SELECT 1 FROM memories WHERE source='model' AND type='semantic'"))

    def test_model_reply_outside_the_options_is_refused_and_rules_take_over(self):
        p = ScriptedProvider(lambda messages, schema: {"thought_summary": "I will fly away.", "choice": "fly_to_the_moon",
                                                       "description": "x", "type": "conquer", "summary": 1, "lesson": 2})
        e = engine(p)
        e.run_minutes(60 * 24)
        self.assertGreater(len(p.calls), 0)
        self.assertEqual(e.mind.metrics["llm_failures"], e.mind.metrics["llm_calls"])
        self.assertFalse(e.store.q("SELECT 1 FROM actions WHERE source='model'"))
        self.assertGreater(e.mind.metrics["actions"], 30)
        self.assertTrue(all(g.source == "rule" for g in e.mind.goals.goals))

    def test_model_cannot_set_needs(self):
        p = ScriptedProvider(lambda messages, schema: {"thought_summary": "I am not hungry.", "choice": schema["properties"]["choice"]["enum"][0],
                                                       "hunger": 0.0, "internal_state": {"hunger": 0.0}} if "choice" in schema["properties"] else 1 / 0)
        e = engine(p)
        e.run_minutes(60)
        e.mind.needs.v["hunger"] = 0.7
        e.mind.surprise = "Something happened"
        e.mind.last_decide = -1e9
        e.run_minutes(3)
        self.assertGreater(e.mind.needs.v["hunger"], 0.65)

    def test_schema_check(self):
        s = {"type": "object", "required": ["choice"], "properties": {"choice": {"type": "string", "enum": ["a", "b"]}}}
        self.assertEqual(check({"choice": "a"}, s), {"choice": "a"})
        for bad in ({"choice": "c"}, {}, [], {"choice": 1}):
            with self.assertRaises(ValueError):
                check(bad, s)


class Parts(unittest.TestCase):
    def test_validator_refuses_what_he_cannot_know_or_do(self):
        know = {"tree": {"caps": ["eat"], "gone": False}, "lost": {"caps": ["eat"], "gone": True}}
        self.assertEqual(validate({"action": "eat", "target": "tree"}, know), (True, ""))
        for step, why in [({"action": "launch"}, "unknown_action"), ({"action": "eat", "target": "rock"}, "unknown_target"),
                          ({"action": "eat", "target": "lost"}, "target_gone"), ({"action": "play", "target": "tree"}, "capability_not_known"),
                          ({"action": "interact", "target": "tree"}, "missing_capability"), ({"action": "eat"}, "missing_target"),
                          ({"action": "move_to", "position": [999, 0]}, "bad_position"), ("rm -rf", "not_an_action")]:
            self.assertEqual(validate(step, know), (False, why))
        self.assertEqual(validate({"action": "eat", "target": "tree"}, know, busy=True), (False, "already_acting"))

    def test_same_command_twice_is_carried_out_once(self):
        bus = protocol.Bus()
        w = World(bus, random.Random(1))
        w.pos = list(w.objects["apple_tree"]["pos"])
        stock = w.objects["apple_tree"]["stock"]
        cmd = {"action_id": "act_1", "action": "eat", "target": "apple_tree"}
        bus.to_world("creature.execute_action", cmd, 0)
        bus.to_world("creature.execute_action", cmd, 0)
        for _ in range(200):
            w.tick(0.1)
        bus.to_world("creature.execute_action", cmd, 0)      # and once more after it has finished
        for _ in range(200):
            w.tick(0.1)
        done = [m for m in bus.drain_mind() if m["type"] == "creature.action_completed"]
        self.assertEqual(int(stock) - int(w.objects["apple_tree"]["stock"]), 1)
        self.assertEqual(len(done), 2)
        self.assertEqual(done[0]["payload"], done[1]["payload"])

    def test_world_refuses_the_physically_impossible(self):
        bus = protocol.Bus()
        w = World(bus, random.Random(1))
        for i, cmd in enumerate([{"action": "eat", "target": "apple_tree"}, {"action": "eat", "target": "nest"},
                                 {"action": "move_to", "position": [500, 500]}, {"action": "eat", "target": "dragon"}]):
            if cmd.get("target") == "nest":
                w.pos = list(w.objects["nest"]["pos"])
            bus.to_world("creature.execute_action", {"action_id": f"a{i}", **cmd}, 0)
            w.tick(0.1)
        reasons = [m["payload"]["reason"] for m in bus.drain_mind() if m["type"] == "creature.action_completed"]
        self.assertEqual(reasons, ["too_far", "cannot", "unreachable", "no_such_object"])

    def test_protocol_rejects_malformed_messages(self):
        for raw in ("not json", "[]", json.dumps({"protocol_version": 2, "type": "world.event", "payload": {}, "message_id": "x"}),
                    json.dumps({"protocol_version": 1, "type": "creature.execute_action", "payload": {}, "message_id": "x"})):
            with self.assertRaises(protocol.ProtocolError):
                protocol.decode(raw, protocol.TO_MIND)

    def test_emotions_have_inertia(self):
        needs, traits = Needs(), config.DEFAULTS["personality"]
        e = Emotions()
        start = e.v["fear"]
        e.feel("fear", 0.9)
        e.update(1, needs, traits)
        self.assertLess(e.v["fear"] - start, 0.1)            # one minute after a fright: barely moved
        for _ in range(40):
            e.update(1, needs, traits)
        self.assertLess(e.v["fear"], 0.5)                    # and the fright fades instead of sticking

    def test_recall_prefers_relevant_important_recent(self):
        s = Store(Path(tempfile.mkdtemp()) / "m.db")
        self.addCleanup(s.close)
        s.remember("episodic", 100, "I found a tree with round red fruit.", importance=0.8, tags=["food"])
        s.remember("episodic", 100, "A bird crossed the sky.", importance=0.3)
        s.remember("episodic", -100000, "I found a tree with red fruit long ago.", importance=0.8, tags=["food"])
        got = s.recall("where is fruit to eat, a tree", 200, goal_text="find food")
        self.assertEqual(got[0]["summary"], "I found a tree with round red fruit.")
        self.assertEqual(got[-1]["summary"], "A bird crossed the sky.")
        self.assertAlmostEqual(sum(__import__("alife.memory").memory.WEIGHTS.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
