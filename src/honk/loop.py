"""The sim loop: Honk's life. Code owns the world (clock, feelings, the cargo window, budgets, the vault, the gate for
builds); the model is asked one narrow question at a time and only proposes.

    tick(minutes)   advances the clock: feelings decay, the cargo window moves on, postcards and finished builds come in
    think()         one unit of thought: code picks which typed call runs (unpack, research, ponder, resolve, wonder)

Everything he does traces back to a question, a cargo item or a visitor. Nothing happens because a menu said so.
"""
import json
import queue
import random
import threading
import time

from . import config
from .cargo import manifest
from .cargo.scheduler import ARRIVED, CLOSED, CLOSING, OPEN, Scheduler
from .feelings import appraisal as A, engine, modulation, phrases
from .foundry.foundry import Foundry, make_client as make_foundry
from .gateway.cassette import Cassette
from .gateway.gateway import Gateway, LiveTransport, Refused
from .memory.store import Memory
from .mind import client as mind_client
from .mind.calls import Mind
from .mind.questions import BUILT, Questions
from .reader import sanitize
from .requests.postcards import Postcards
from .textsim import shorten, similarity, topics
from .vault.store import Vault
from .world.sections import Sections


class Sim:
    def __init__(self, db, params=None, mind=None, foundry=None, transport=None, seed=None, threaded=False):
        self.db = db
        self.preset = db.get("preset")
        self.p = params or config.load(preset=self.preset, overrides=db.get("overrides", {}))
        self.rnd = random.Random(seed)
        self.lock = threading.RLock()
        self.clock = db.get("clock", 0.0)
        self.cycle = db.get("cycle", 0)
        self.fs = db.get("feel") or engine.new_state(self.p, self.clock)
        self.sched = Scheduler(self.p, db.get("sched"), self.rnd)
        self.doing = db.get("doing") or {"icon": "🌙", "text": "waking up on the Moon", "where": "nest"}
        self.flags = db.get("flags") or {"sleepy": False, "nudge": True, "last_feel": 0.0, "w_open": 0.0, "budget_said": -1, "slept_at": 0.0, "paused": False}
        self.sections = Sections(config.sections(), db)
        self.client = mind or mind_client.make(self.p["mind"])
        self.mind = Mind(self.client, config.canon(), db, self.now)
        self.questions, self.memory, self.vault, self.postcards = Questions(db, self.p), Memory(db, self.p), Vault(db, self.p), Postcards(db, self.p)
        self.transport = transport or (Cassette(self.p) if self.p["gateway"]["mode"] == "cassette" else LiveTransport(self.p))
        self.gateway = Gateway(self.p, db, self.sched, self.transport, self.now)
        self.foundry = Foundry(foundry or make_foundry(self.p, self.client), self.p, db, self.sections, self.now)
        self.feeds = config.feeds()
        self.threaded, self.outbox, self.building = threaded, queue.Queue(), False
        self.avg = {"n": 0, "connection": 0.0, "purpose": 0.0, "valence": 0.0, "arousal": 0.0}
        self.last_call = 0.0
        self.stop = threading.Event()
        if self.db.val("SELECT COUNT(*) FROM events") == 0:
            self.say("system", "🌙", "Honk wakes up on the Moon. He is the keeper now.")

    # ---------------------------------------------------------------- small helpers
    def now(self):
        return self.clock

    def view(self):
        return engine.view(self.fs, self.p, self.clock)

    def say(self, kind, icon, text, **data):
        """Something for the watcher to see (the diary). Never read back by the model."""
        self.db.insert("events", ts=self.clock, kind=kind, icon=icon, text=shorten(text, 500), data=json.dumps(data) if data else "")

    def do(self, icon, text, where=None):
        self.doing = {"icon": icon, "text": shorten(text, 140), "where": where or self.doing["where"]}

    def feel(self, event):
        ev = {**event, "t": self.clock}
        self.fs = engine.step(self.fs, [ev], self.p, self.clock)
        if ev["kind"] != "web":
            self.flags["last_feel"] = self.clock
        self.db.insert("feeling_trace", ts=self.clock, event_json=json.dumps(event), state_json=json.dumps({k: round(self.fs[k], 4) for k in engine.TARGETS}))

    def words(self):
        return phrases.in_words(self.view(), self.rnd)

    def save(self):
        for k, v in (("clock", self.clock), ("cycle", self.cycle), ("feel", self.fs), ("sched", self.sched.s), ("doing", self.doing), ("flags", self.flags)):
            self.db.put(k, v)

    def set_param(self, key, value, who="panel"):
        with self.lock:
            old = config.set_key(self.p, key, value)
            self.db.insert("param_changes", ts=self.clock, key=key, old=str(old), new=str(config.get_key(self.p, key)), who=who)
            over = self.db.get("overrides", {})
            over[key] = config.get_key(self.p, key)
            self.db.put("overrides", over)
            return config.get_key(self.p, key)

    def set_preset(self, name, who="panel"):
        with self.lock:
            new = config.load(preset=name or None)
            self.db.insert("param_changes", ts=self.clock, key="preset", old=str(self.preset), new=str(name), who=who)
            for k in list(self.p):          # in place: every part of him holds the same dict
                self.p[k] = new[k]
            self.preset = name or None
            self.db.put("preset", self.preset)
            self.db.put("overrides", {})

    # ---------------------------------------------------------------- tick: the world moves on, no model involved
    def tick(self, minutes):
        with self.lock:
            if self.flags.get("paused"):
                return
            self.clock += max(0.0, minutes)
            self.fs = engine.step(self.fs, [], self.p, self.clock)
            v = self.view()
            f = self.p["feelings"]
            self.avg["n"] += 1
            for k in ("connection", "purpose", "valence", "arousal"):
                self.avg[k] += v[k]

            for change in self.sched.tick(self.clock, unpacked=self._unpacked(), asleep=self.fs["asleep"]):
                getattr(self, "_on_" + change)()

            # sleep and waking are rules
            if self.fs["asleep"]:
                cargo_waiting = self.sched.state == ARRIVED and v["energy"] > 0.45
                if v["energy"] > f["wake_above"] or cargo_waiting:
                    self.feel(A.wake())
                    self.say("sleep", "🌅", "Honk wakes up." + (" A cargo is waiting." if cargo_waiting else ""))
                    self.do("🌅", "waking up", "nest")
            elif v["energy"] < f["sleep_below"] and (self.sched.state == CLOSED or v["energy"] < 0.1):
                self.flags["sleepy"] = True

            self._postcards_in()
            self._builds_in()

            w = self.questions.w_open() if self.sched.state in (CLOSED, ARRIVED) else 0.0
            if abs(w - self.flags["w_open"]) > 0.05:      # questions only a cargo can answer build curiosity pressure
                self.flags["w_open"] = w
                self.feel(A.web(w))
            if not self.fs["asleep"] and self.clock - self.flags["last_feel"] > 90:
                self.feel(A.quiet())
            self.save()

    def _unpacked(self):
        return self.sched.state == ARRIVED and not self.db.val("SELECT COUNT(*) FROM cargo_items WHERE window_id = ? AND status = 'packed'", (self.sched.window,))

    def _on_arrived(self):
        s, n = self.sched, self.sched.window
        self.db.insert("cargo_windows", id=n, arrived=self.clock, ledger_left=s.ledger, signal=int(s.story_over))
        self.feel(A.cargo_arrived(s.ledger / max(1, self.p["cargo"]["ledger"])))
        if s.story_over:
            self.say("cargo", "📡", "An unexplained signal arrives at the Hatch. The counted cargos are over, but something still comes.")
        else:
            self.say("cargo", "📦", f"Cargo {n} has landed at the Hatch. {s.ledger} cargos are left.")
        packed = manifest.build(n, self.p, self.db, self.gateway, self.postcards, self.memory.interests(), self.feeds, self.rnd)
        self.memory.add("cargo", f"Cargo {n} landed with {packed} things in it.", self.clock, importance=0.3, tags=("cargo",))
        if not self.fs["asleep"]:
            self.do("📦", f"unpacking cargo {n}", "hatch")

    def _on_open(self):
        self.db.update("cargo_windows", self.sched.window, opened=self.clock)
        self.db.run("UPDATE requests SET status = 'read' WHERE status = 'in cargo' AND window_id = ?", (self.sched.window,))
        self.say("cargo", "🚪", f"The hatch is open for {int(self.p['cargo']['window_min'])} minutes. Honk can look things up.")
        self.flags["nudge"] = True

    def _on_closing(self):
        self.say("cargo", "⏳", "The hatch will close soon.")

    def _on_closed(self):
        n = self.sched.window
        kept = self.db.val("SELECT COUNT(*) FROM cargo_items WHERE window_id = ? AND kept = 1", (n,))
        seen = self.db.val("SELECT COUNT(*) FROM cargo_items WHERE window_id = ? AND status = 'judged'", (n,))
        opened = self.db.val("SELECT opened FROM cargo_windows WHERE id = ?", (n,)) or self.clock
        answered = self.db.val("SELECT COUNT(*) FROM questions WHERE status IN ('answered', 'built') AND last_touched >= ?", (opened,))
        waiting = [q["text"] for q in self.questions.open() if q["needs_web"]][:5]
        summary = f"Cargo {n}: read {seen} things, kept {kept}, answered {answered} questions." + (" Still to look up next time: " + " | ".join(waiting) if waiting else "")
        self.db.update("cargo_windows", n, closed=self.clock, summary=summary, budget_json=json.dumps(self.gateway.budget()))
        self.memory.add("window", summary, self.clock, importance=0.5, tags=("cargo",))
        self.feel(A.hatch_closed(len(waiting)))
        self.say("cargo", "🔒", "The hatch is closed. " + summary)

    def _postcards_in(self):
        for r in self.postcards.waiting():
            vid, name = r["visitor_id"], r["name"]
            text = r["text"]
            if r["answers_question"]:
                ask = next((a for a in self.db.get("asks", []) if a["id"] == r["answers_question"]), None)
                if ask:
                    self.memory.add("told", f"A descendant called {name} told me, about \"{ask['text']}\": {text}", self.clock, importance=0.7, tags=tuple(topics(ask["text"])))
                    text = f'{name} answered my question "{ask["text"]}" with: "{text}". What do I say back?'
            qid, _ = self.questions.add(text, f"{name} wrote to me", f"visitor:{vid}", False, 0.9, self.clock)
            self.postcards.set(r["id"], question_id=qid)
            self.memory.add("postcard", f"{name} wrote: {r['text']}", self.clock, importance=0.6, valence=A.warmth_of(r["text"]), tags=("visitor",))
            self.feel(A.postcard(r["text"], vid))
            self.say("postcard", "✉️", f"A postcard from {name}: {r['text']}")

    # ---------------------------------------------------------------- builds: the Foundry works on its own, results come back here
    def _builds_in(self):
        if not self.threaded:
            done = self.foundry.process()
            if done:
                self.outbox.put(done)
        elif not self.building and self.foundry.busy():
            self.building = True
            threading.Thread(target=self._foundry_worker, daemon=True).start()
        while not self.outbox.empty():
            b = self.outbox.get()
            if b["status"] == "placed":
                self.feel(A.build_placed())
                self.memory.add("built", f"The Foundry made my {b['name']} and it now stands in {self.sections.get(b['section_id'])['name']}. I wanted it because: {b['why']}", self.clock, importance=0.8, valence=0.6, tags=tuple(topics(b["thing"])))
                self.say("build", "🏗️", f"New on the Moon: {b['name']}, in {self.sections.get(b['section_id'])['name']}.", build=b["id"])
                if b["question_id"]:
                    self.db.update("questions", b["question_id"], status=BUILT)
                self.do("✨", f"looking at his new {b['name']}", b["section_id"])
            else:
                self.feel(A.build_dropped())
                self.memory.add("built", f"My {b['thing']} did not work out: {b['drop_reason']}", self.clock, importance=0.5, valence=-0.4, tags=tuple(topics(b["thing"])))
                self.say("build", "💥", f"The {b['thing']} was dropped: {b['drop_reason']}", build=b["id"])
                self.questions.add(f"Why did my {b['thing']} not work out, and what would I try instead?", "a build failed", "feeling:purpose", False, 0.6, self.clock, parent_id=b["question_id"])

    def _foundry_worker(self):
        try:
            done = self.foundry.process()
            if done:
                self.outbox.put(done)
        finally:
            self.building = False

    # ---------------------------------------------------------------- think: code picks the call
    def think(self):
        """One unit of thought. Returns the name of what he did, or '' when nothing called for the model."""
        with self.lock:
            if self.flags.get("paused") or self.fs["asleep"]:
                return ""
            v = self.view()
            if self.flags["sleepy"]:
                return self._sleep(v)
            self.cycle += 1
            st = self.sched.state
            did = ""
            if st == ARRIVED:
                item = self.db.one("SELECT * FROM cargo_items WHERE window_id = ? AND status = 'packed' ORDER BY id LIMIT 1", (self.sched.window,))
                if item:
                    did = self._unpack(item, v)
            if not did:
                q = self.db.one("SELECT * FROM questions WHERE status = 'open' AND origin LIKE 'visitor:%' AND tries = 0 AND needs_web = 0 ORDER BY id LIMIT 1")
                if q:
                    did = self._ponder(q, v)
            if not did and st == OPEN:
                q = self.questions.head(self.cycle, web=True)
                if q and not self.gateway.spent("searches") and not self.gateway.spent("fetches"):
                    did = self._research(q, v)
                elif q and self.flags["budget_said"] != self.sched.window:
                    self.flags["budget_said"] = self.sched.window
                    self.feel(A.budget_out())
                    self.say("cargo", "🔋", "The hatch is humming: this window's budget is used up. Honk has to choose what waits.")
            if not did and modulation.slow(v) and self.rnd.random() < 0.5:
                self.do("🥱", "moving slowly; he is tired")
                return ""
            if not did:
                q = self.questions.to_resolve()
                if q:
                    did = self._resolve(q, v)
            if not did:
                q = self.questions.head(self.cycle, web=False)
                few = len(self.questions.open()) < self.p["mind"]["wonder_below"]
                urgent = any(v["urgent"][k] for k in ("curiosity", "connection", "purpose"))
                rested = self.clock - self.flags.get("wondered_at", -1e9) >= self.p["mind"]["wonder_gap_min"]
                if (self.flags["nudge"] or (rested and (few or urgent))) and (not q or self.flags["nudge"] or self.rnd.random() < 0.35):
                    did = self._wonder(v)
                elif q:
                    did = self._ponder(q, v)
            if not did:
                where = self.rnd.choice(["lookout", "garden", "vault", "memorial", "nest"])
                self.do("🚶", f"wandering to {self.sections.get(where)['name']}", where)
            self.last_call = time.time()
            self.save()
            return did

    # ---------------------------------------------------------------- unpack: Reader (quarantined), then Judge
    def _unpack(self, item, v):
        raw = json.loads(item["extract_json"]).get("raw", {})
        self.do("📦", f"unpacking: {item['title'] or 'something'}", "hatch")
        ex = self.mind.read(raw.get("title", ""), raw.get("text", ""), item["url"])
        if not ex:
            self.db.update("cargo_items", item["id"], status="unreadable")
            return "reader"
        body = ex["title"] + " " + ex["summary"]
        tp = ex["topics"][:3] or topics(body, 3)
        seen = self.db.all("SELECT text FROM memories WHERE kind IN ('cargo', 'kept', 'read') ORDER BY id DESC LIMIT 30")
        novelty = 1.0 - max([similarity(body, m["text"]) for m in seen] + [engine.habit(self.fs, self.p, t, self.clock) for t in tp] + [0.0])
        full = self.vault.full()
        weakest = self.vault.weakest(3) if full else []
        j = self.mind.judge(ex, self.vault.used(), self.vault.size(), weakest, modulation.picky(v), self.words())
        if not j:
            self.db.update("cargo_items", item["id"], status="skipped", extract_json=json.dumps(ex))
            return "judge"
        keep, reason = j["keep"], j["reason"]
        if keep and full:
            gone = self.vault.release(j["release_id"], f"to make room for {ex['title']}: {reason}", self.clock) if j["release_id"] in [w["id"] for w in weakest] else None
            if gone:
                self.feel(A.vault_release())
                self.say("vault", "🕊️", f"Honk lets \"{gone['title']}\" go from the vault to make room.")
            else:
                keep, reason = False, reason + " (The vault was full and he let nothing go.)"
        if keep:
            self.vault.keep(item["id"], ex["title"] or item["title"], reason, (ex["quotes"] or [""])[0], item["url"], j["tags"] or tp, j["interest"], self.clock)
            self.memory.add("kept", f"I kept \"{ex['title']}\" in the vault: {ex['summary']} Why: {reason}", self.clock, importance=0.5 + 0.4 * j["interest"], valence=0.3, tags=tuple(j["tags"] or tp), source=item["url"])
            self.say("vault", "🗄️", f"Kept \"{ex['title']}\": {reason}", item=item["id"])
            self.do("🗄️", f"putting \"{ex['title']}\" on a shelf", "vault")
        else:
            self.memory.add("cargo", f"In a cargo: \"{ex['title']}\". {ex['summary']}", self.clock, importance=0.2 + 0.3 * j["interest"], tags=tuple(tp), source=item["url"])
            self.say("cargo", "📄", f"Read \"{ex['title']}\" and let it pass: {reason}", item=item["id"])
        self.db.update("cargo_items", item["id"], status="judged", kept=int(keep), interest=j["interest"], reason=reason, extract_json=json.dumps(ex))
        self.feel(A.item_judged(keep, j["interest"], novelty, body, tp))
        if j["interest"] > 0.65:
            self.flags["nudge"] = True
        for q in self.db.all("SELECT id, text FROM questions WHERE status = 'answered' AND confidence < 0.8 ORDER BY id DESC LIMIT 30"):
            if similarity(body, q["text"]) > 0.45:      # new evidence from a cargo is the only thing that reopens an answer
                self.questions.reopen(q["id"], self.clock)
                break
        return "judge"

    # ---------------------------------------------------------------- research: only while the hatch is open
    def _research(self, q, v):
        self.do("🔭", f"looking up: {q['text']}", "hatch")
        plan = self.mind.research(q["text"], q["why"])
        if not plan or not plan["queries"]:
            self.questions.touch(q["id"], self.cycle, self.clock)
            return "research"
        evidence, tags = [], []
        try:
            for query in plan["queries"]:
                for hit in self.gateway.search(query, who=f"q{q['id']}")[:3]:
                    if len(evidence) >= 2:
                        break
                    if self.db.val("SELECT COUNT(*) FROM memories WHERE source = ? AND kind = 'read'", (hit["url"],)):
                        continue
                    page = self.gateway.fetch(hit["url"], who=f"q{q['id']}")
                    ex = self.mind.read(page["title"], page["text"], page["url"])
                    if ex:
                        evidence.append(sanitize.wrap(ex))
                        tags += ex["topics"][:2]
                        self.memory.add("read", f"I read \"{ex['title']}\": {ex['summary']}", self.clock, importance=0.4, tags=tuple(ex["topics"][:3]), source=page["url"])
                        self.say("cargo", "📖", f"Read \"{ex['title']}\" for his question: {q['text']}")
        except Refused as e:
            self.say("cargo", "🚫", f"The hatch says: {e}")
        req = self.postcards.for_question(q["id"])
        if req:
            self.postcards.set(req["id"], status="researched")
        if not evidence:
            self.feel(A.no_answer())
            if req and q["tries"] + 1 >= self.p["mind"]["max_tries"]:      # a visitor is owed an honest answer, even "I do not know"
                sorry = "I looked for this every time the hatch was open, and the cargos did not tell me. I do not know. I am sorry."
                self.db.update("questions", q["id"], status="answered", answer=sorry)
                self._reply(q, req, sorry)
            elif self.questions.failed(q, self.cycle, self.clock):
                self.say("thought", "🗃️", f"Honk sets a question aside for now: {q['text']}")
            return "research"
        return self._ponder(q, v, evidence, tags)

    # ---------------------------------------------------------------- ponder
    def _ponder(self, q, v, evidence=None, tags=()):
        visitor = q["origin"].startswith("visitor:")
        req = self.postcards.for_question(q["id"]) if visitor else None
        if not evidence:
            self.do("✉️" if visitor else "💭", f"thinking about: {q['text']}", "postbox" if visitor else "lookout")
        open_text = " ".join(x["text"] for x in self.questions.open()[:8])
        mems = self.memory.texts(q["text"], self.clock, mood=v["mood"], open_text=open_text)
        a = self.mind.ponder(q["text"], mems, evidence, req["name"] if req else None, modulation.reply_words(v))
        if not a:
            self.questions.touch(q["id"], self.cycle, self.clock)
            return "ponder"
        sure = a["confidence"] >= (self.p["visitors"]["answer_confidence"] if visitor else 0.5)
        tp = list(tags) or topics(q["text"], 3)
        if sure:
            mem = self.memory.add("answer", f"I asked: {q['text']} My answer: {a['answer']}", self.clock, importance=0.4 + 0.4 * q["interest"], valence=v["mood"], tags=tuple(tp))
            self.feel(A.answered(a["confidence"] - q["confidence"], q["interest"], tp))
            self.questions.answer(q, a["answer"], a["confidence"], mem, self.cycle, self.clock)
            if visitor:
                self._reply(q, req, a["answer"])
            else:
                self.say("answer", "💡", f"{q['text']} — {a['answer']}", question=q["id"])
            if a["follow_up"]:
                self.questions.add(a["follow_up"], "it followed from an answer", q["origin"] if visitor else "self", False, q["interest"] * 0.8, self.clock, parent_id=q["id"])
            return "ponder"
        self.feel(A.no_answer())
        hatch = self.sched.state in (OPEN, CLOSING)
        if evidence or hatch and q["needs_web"]:
            parked = self.questions.failed(q, self.cycle, self.clock)
            if visitor and q["tries"] + 1 >= self.p["mind"]["max_tries"]:
                self.db.update("questions", q["id"], status="answered", answer=a["answer"])
                self._reply(q, req, a["answer"])
            elif parked:
                self.say("thought", "🗃️", f"Honk could not find it out and sets it aside: {q['text']}")
        else:       # from memory he does not know: it has to wait for a cargo
            self.questions.touch(q["id"], self.cycle, self.clock, needs_web=1, tries=q["tries"] + 1)
            self.say("thought", "💭", f"\"{q['text']}\" He does not know yet. It has to wait for the next cargo.")
            if visitor and req and not req["reply"]:
                self.postcards.set(req["id"], reply=shorten(a["answer"], 300) + " I will look when the next cargo comes, and write again.", reply_ts=self.clock)
        return "ponder"

    def _reply(self, q, req, text):
        self.db.update("questions", q["id"], resolved="reply")
        if not req:
            return
        self.postcards.set(req["id"], status="replied", reply=shorten(text, 600), reply_ts=self.clock)
        self.memory.add("reply", f"I answered {req['name']}, who asked \"{req['text']}\": {text}", self.clock, importance=0.6, valence=0.3, tags=("visitor",))
        self.feel(A.replied())
        self.say("reply", "🪿", f"To {req['name']}: {text}", request=req["id"])
        self.do("✉️", f"sending his answer to {req['name']}", "postbox")

    # ---------------------------------------------------------------- resolve: what to do with an answer
    def _resolve(self, q, v):
        self.do("🤔", f"deciding what to do about: {q['text']}")
        busy = self.foundry.busy() or not self.sections.buildable()
        waiting = bool(self.db.val("SELECT COUNT(*) FROM requests WHERE real_ts > ?", (time.time() - 3600,)))
        r = self.mind.resolve(q["text"], q["answer"], self.sections.buildable(), modulation.favours_building(v), modulation.ambition(v), busy, self.words(), waiting)
        if not r:
            self.db.update("questions", q["id"], resolved="skipped")
            return "resolve"
        choice = r["choice"]
        if choice == "build_request":
            s = self.sections.find(r["section"])
            why = "the Foundry is busy" if busy else "he did not say where" if not s else self.foundry.gate(s["id"], r["thing"])
            if why:
                self.say("build", "🚧", f"Honk wanted {r['thing'] or 'to build something'}, but {why}.")
                choice = "nothing"
            else:
                bid = self.foundry.request(s["id"], r["thing"], r["text"] or q["text"], r["style_brief"], q["id"])
                self.say("build", "📐", f"Honk asks the Foundry for {r['thing']} in {s['name']}: {r['style_brief']}", build=bid)
                self.do("📐", f"waiting at the Foundry for {r['thing']}", s["id"])
        elif choice in ("note", "reply") and r["text"]:
            choice = "note"
            self.db.insert("journal", ts=self.clock, day=int(self.clock // self.p["sim"]["day_min"]) + 1, kind="note", text=r["text"])
            self.memory.add("note", r["text"], self.clock, importance=0.6, valence=v["mood"], tags=tuple(topics(q["text"], 3)))
            self.feel(A.note_written())
            self.say("note", "📝", r["text"], question=q["id"])
            self.do("📝", "writing a note", "nest")
        elif choice == "ask_visitor" and r["text"]:
            asks = self.db.get("asks", [])
            if not any(similarity(a["text"], r["text"]) > 0.6 for a in asks):
                asks.append({"id": (asks[-1]["id"] + 1) if asks else 1, "text": r["text"], "question_id": q["id"], "ts": self.clock})
                self.db.put("asks", asks[-12:])
                self.say("ask", "❓", f"Honk asks the ones who come after: {r['text']}")
                self.do("❓", "leaving a question at the Postbox", "postbox")
        else:
            choice = "nothing"
        self.db.update("questions", q["id"], resolved=choice)
        return "resolve"

    # ---------------------------------------------------------------- wonder
    def _wonder(self, v):
        self.flags["nudge"] = False
        self.flags["wondered_at"] = self.clock
        self.do("💭", "wondering", self.rnd.choice(["lookout", "garden", "memorial", "vault"]))
        open_q = self.questions.open()
        mems = self.memory.texts(" ".join(q["text"] for q in open_q[:3]), self.clock, mood=v["mood"], n=4)
        hatch = self.sched.state in (OPEN, CLOSING)
        qs = self.mind.wonder(self.words(), modulation.wonder_seeds(v), mems, [q["text"] for q in open_q[:12]], modulation.wants_web(v),
                              modulation.temperature(v, self.p["mind"]), hatch)
        if qs is None:
            return "wonder"
        interests = self.memory.interests()
        for x in qs:
            tp = topics(x["text"], 3)
            used = max([engine.habit(self.fs, self.p, t, self.clock) for t in tp] + [0.0])
            liked = max([similarity(x["text"], t) for t in interests] + [0.0])
            qid, verdict = self.questions.add(x["text"], x["why"], "self", x["needs_web"], 0.45 + 0.3 * liked + 0.25 * (1.0 - used) * self.rnd.random(), self.clock)
            if verdict == "new":
                self.say("thought", "❔", x["text"] + (f" ({x['why']})" if x["why"] else ""), question=qid)
                self.fs = engine.step(self.fs, [{"t": self.clock, "kind": "wondered", "topics": tp}], self.p, self.clock)
        parked = self.questions.triage(self.clock)
        if parked:
            self.feel(A.overwhelmed())
            self.say("thought", "🗃️", f"Too many questions at once. Honk sets {len(parked)} aside.")
        return "wonder"

    # ---------------------------------------------------------------- sleep routine
    def _sleep(self, v):
        self.flags["sleepy"] = False
        since = self.flags["slept_at"]
        rows = self.db.all("SELECT text FROM events WHERE ts > ? AND kind IN ('vault', 'answer', 'build', 'reply', 'note', 'postcard') ORDER BY id DESC LIMIT 12", (since,))
        if rows:
            last = self.db.val("SELECT text FROM journal WHERE kind = 'journal' ORDER BY id DESC LIMIT 1")
            entry = self.mind.journal([r["text"] for r in reversed(rows)], self.words(), last)
            if entry:
                self.db.insert("journal", ts=self.clock, day=int(self.clock // self.p["sim"]["day_min"]) + 1, kind="journal", text=entry)
                self.memory.add("journal", entry, self.clock, importance=0.5, valence=v["mood"], tags=("journal",))
                self.say("journal", "📔", entry)
        parked = self.questions.triage(self.clock)
        faded = self.memory.fade(self.clock)
        if self.avg["n"]:
            self.fs = engine.drift(self.fs, self.p, {k: self.avg[k] / self.avg["n"] for k in ("connection", "purpose", "valence", "arousal")})
            self.avg = {k: 0 if k == "n" else 0.0 for k in self.avg}
        self.feel(A.sleep())
        self.flags["slept_at"] = self.clock
        self.say("sleep", "😴", "Honk curls up in his nest and sleeps." + (f" He set {len(parked)} questions aside." if parked else "") + (f" {faded} old memories faded." if faded else ""))
        self.do("😴", "asleep", "nest")
        self.save()
        return "sleep"

    # ---------------------------------------------------------------- running in real time
    def run(self):
        """Tick in real time until stop is set. One thread; a model call blocks it and the clock catches up afterwards."""
        last = time.time()
        while not self.stop.wait(self.p["sim"]["tick_s"]):
            now = time.time()
            self.tick(min(now - last, 300.0) * self.p["sim"]["speed"] / 60.0)
            last = now
            if time.time() - self.last_call >= self.p["mind"]["min_interval_s"]:
                try:
                    self.think()
                except Exception as e:      # a bug in one thought must not end his life
                    self.say("system", "⚠️", f"Something went wrong inside: {type(e).__name__}: {e}")
                    self.last_call = time.time()
