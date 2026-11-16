"""Persistent memory and identity (SQLite): the event log, experiences, knowledge, preferences, goals and state.

Retrieval scores each memory as R = 0.35 S + 0.20 I + 0.20 T + 0.15 G + 0.10 E
(similarity, importance, recency, goal relevance, emotional fit). Consolidation turns experience into
preferences and knowledge, and archives what is not worth keeping.
"""
import json
import math
import re
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS creatures(id TEXT PRIMARY KEY, name TEXT, created_real REAL);
CREATE TABLE IF NOT EXISTS personality_traits(creature_id TEXT, trait TEXT, value REAL, baseline REAL,
    PRIMARY KEY(creature_id, trait));
CREATE TABLE IF NOT EXISTS internal_states(creature_id TEXT PRIMARY KEY, json TEXT, saved_real REAL, saved_minute REAL);
CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, json TEXT, status TEXT, level INTEGER);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, minute REAL, key TEXT, action TEXT,
    target TEXT, success INTEGER, reason TEXT, valence REAL, effects TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, minute REAL, location TEXT,
    event TEXT, summary TEXT, tags TEXT, emotion TEXT, importance REAL, source TEXT, archived INTEGER DEFAULT 0,
    access_count INTEGER DEFAULT 0, embedding TEXT);
CREATE TABLE IF NOT EXISTS knowledge(subject TEXT, predicate TEXT, value TEXT, confidence REAL, minute REAL,
    PRIMARY KEY(subject, predicate));
CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, value REAL, samples INTEGER, minute REAL);
CREATE TABLE IF NOT EXISTS relationships(who TEXT PRIMARY KEY, familiarity REAL, affection REAL, interactions INTEGER,
    last_minute REAL);
CREATE TABLE IF NOT EXISTS world_objects(id TEXT PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS world_events(id INTEGER PRIMARY KEY AUTOINCREMENT, minute REAL, type TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS daily_summaries(day INTEGER PRIMARY KEY, summary TEXT, lesson TEXT, source TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS event_log(id INTEGER PRIMARY KEY AUTOINCREMENT, real REAL, minute REAL, type TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""
WEIGHTS = {"S": 0.35, "I": 0.20, "T": 0.20, "G": 0.15, "E": 0.10}
STOP = set("a an the i it is was to of and in at my me that this for on with from what have has had not".split())


def tokens(text):
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()      # the model worker thread reads memories while the loop writes
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def close(self):
        with self.lock:
            self.db.close()

    # ---- small things
    def get_meta(self, key, default=None):
        r = self.q("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r else default

    def set_meta(self, key, value):
        self.x("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))

    def log(self, minute, type_, data):
        """Append-only: enough to reconstruct why he ended up in any state."""
        self.x("INSERT INTO event_log(real, minute, type, json) VALUES(?,?,?,?)",
               (time.time(), minute, type_, json.dumps(data)))

    def world_event(self, minute, type_, data):
        self.x("INSERT INTO world_events(minute, type, json) VALUES(?,?,?)", (minute, type_, json.dumps(data)))

    # ---- identity and state
    def creature(self, cid, name, traits):
        if not self.q("SELECT 1 FROM creatures WHERE id=?", (cid,)):
            self.x("INSERT INTO creatures VALUES(?,?,?)", (cid, name, time.time()))
            for t, v in traits.items():
                self.x("INSERT INTO personality_traits VALUES(?,?,?,?)", (cid, t, v, v))
        return {r["trait"]: r["value"] for r in self.q("SELECT trait, value FROM personality_traits WHERE creature_id=?", (cid,))}

    def save_traits(self, cid, traits):
        for t, v in traits.items():
            self.x("UPDATE personality_traits SET value=? WHERE creature_id=? AND trait=?", (v, cid, t))

    def save_state(self, cid, state, minute):
        self.x("INSERT OR REPLACE INTO internal_states VALUES(?,?,?,?)", (cid, json.dumps(state), time.time(), minute))

    def load_state(self, cid):
        r = self.q("SELECT * FROM internal_states WHERE creature_id=?", (cid,))
        return (json.loads(r[0]["json"]), r[0]["saved_real"]) if r else (None, None)

    def save_goal(self, g):
        self.x("INSERT OR REPLACE INTO goals VALUES(?,?,?,?)", (g["id"], json.dumps(g), g["status"], g["level"]))

    def load_goals(self):
        return [json.loads(r["json"]) for r in self.q("SELECT json FROM goals ORDER BY id")]

    def save_object(self, k):
        self.x("INSERT OR REPLACE INTO world_objects VALUES(?,?)", (k["id"], json.dumps(k)))

    def load_objects(self):
        return [json.loads(r["json"]) for r in self.q("SELECT json FROM world_objects")]

    def prefs(self):
        return {r["key"]: r["value"] for r in self.q("SELECT key, value FROM preferences")}

    def relationship(self, who):
        r = self.q("SELECT * FROM relationships WHERE who=?", (who,))
        return dict(r[0]) if r else {"who": who, "familiarity": 0.0, "affection": 0.0, "interactions": 0, "last_minute": 0}

    def save_relationship(self, r):
        self.x("INSERT OR REPLACE INTO relationships VALUES(?,?,?,?,?)",
               (r["who"], r["familiarity"], r["affection"], r["interactions"], r["last_minute"]))

    def add_action(self, minute, key, action, target, success, reason, valence, effects, source):
        self.x("INSERT INTO actions(minute,key,action,target,success,reason,valence,effects,source) VALUES(?,?,?,?,?,?,?,?,?)",
               (minute, key, action, target, int(success), reason, valence, json.dumps(effects), source))

    # ---- memories
    def remember(self, type_, minute, summary, event="", location="", tags=(), emotion=None, importance=0.5, source="rule"):
        return self.x("INSERT INTO memories(type,minute,location,event,summary,tags,emotion,importance,source) VALUES(?,?,?,?,?,?,?,?,?)",
                      (type_, minute, location, event, summary, json.dumps(list(tags)), json.dumps(emotion or {}),
                       importance, source))

    def memories(self, where="archived=0", args=(), limit=500):
        return [dict(r) for r in self.q(f"SELECT * FROM memories WHERE {where} ORDER BY minute DESC LIMIT {int(limit)}", args)]

    def embed_missing(self, embed):
        """Give memories an embedding when the model runner can supply one; otherwise word overlap is used."""
        rows = self.q("SELECT id, summary FROM memories WHERE archived=0 AND embedding IS NULL LIMIT 64")
        if not rows:
            return
        vectors = embed([r["summary"] for r in rows])
        if vectors and len(vectors) == len(rows):
            for r, v in zip(rows, vectors):
                self.x("UPDATE memories SET embedding=? WHERE id=?", (json.dumps([round(x, 5) for x in v]), r["id"]))

    def recall(self, query, now, goal_text="", emotions=None, k=4, embed=None):
        if embed:
            try:
                self.embed_missing(embed)
                qv = embed([query])
                qv = qv[0] if qv else None
            except Exception:
                qv = None
        else:
            qv = None
        qt, gt, scored = tokens(query), tokens(goal_text), []
        for m in self.memories():
            text = tokens(m["summary"] + " " + " ".join(json.loads(m["tags"])))
            s = jaccard(qt, text)
            if qv and m["embedding"]:
                s = max(s, cosine(qv, json.loads(m["embedding"])))
            felt = json.loads(m["emotion"])
            shared = [e for e in felt if emotions and e in emotions]
            e = 1 - sum(abs(felt[x] - emotions[x]) for x in shared) / len(shared) if shared else 0.5
            parts = {"S": s, "I": m["importance"], "T": math.exp(-max(0, now - m["minute"]) / 60 / 48),
                     "G": jaccard(gt, text), "E": e}
            scored.append((sum(WEIGHTS[x] * parts[x] for x in parts), m, parts))
        scored.sort(key=lambda t: -t[0])
        best = scored[:k]
        for _, m, _ in best:
            self.x("UPDATE memories SET access_count=access_count+1 WHERE id=?", (m["id"],))
        return [{"id": m["id"], "summary": m["summary"], "type": m["type"], "minute": m["minute"],
                 "score": round(score, 3), "parts": {x: round(v, 2) for x, v in parts.items()}} for score, m, parts in best]


def consolidate(store, prefs, know, since, now):
    """Learn from what happened since `since`. Returns a short report of what changed."""
    report = {"preferences": {}, "knowledge": 0, "merged": 0, "archived": 0}
    # 1. preferences: how each activity actually turned out moves how much he likes it
    rows = store.q("SELECT key, AVG(valence) v, COUNT(*) n FROM actions WHERE minute>? AND key!='' AND reason IS NOT 'cancelled' GROUP BY key", (since,))
    for r in rows:
        old = prefs.get(r["key"], 0.0)
        new = max(-0.3, min(0.3, old + 0.25 * (r["v"] * 0.6 - old)))
        if abs(new - old) > 0.004:
            prefs[r["key"]] = new
            report["preferences"][r["key"]] = round(new, 3)
        store.x("INSERT INTO preferences VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "samples=samples+excluded.samples, minute=excluded.minute", (r["key"], new, r["n"], now))
    # 2. knowledge: what each thing gives, as plain facts
    for k in know.values():
        for cap, eff in k["effects"].items():
            good = ", ".join(f"{c} {v:+.2f}" for c, v in sorted(eff.items())) or "nothing much"
            store.x("INSERT OR REPLACE INTO knowledge VALUES(?,?,?,?,?)",
                    (k["id"], cap, good, min(1.0, k["tries"].get(cap, 1) / 5), now))
            report["knowledge"] += 1
    # 3. many similar small experiences become one remembered habit
    groups = store.q("SELECT event, location, COUNT(*) n, MAX(id) keep FROM memories WHERE archived=0 AND type='episodic' "
                     "AND importance<0.6 AND event!='' GROUP BY event, location HAVING n>=4")
    for g in groups:
        last = store.q("SELECT summary FROM memories WHERE id=?", (g["keep"],))[0]["summary"]
        store.x("UPDATE memories SET archived=1 WHERE archived=0 AND type='episodic' AND importance<0.6 AND event=? AND location=?",
                (g["event"], g["location"]))
        store.x("DELETE FROM memories WHERE type='autobiographical' AND event=? AND location=?", ("habit:" + g["event"], g["location"]))
        store.remember("autobiographical", now, f"This has happened to me many times: {last}", "habit:" + g["event"],
                       g["location"], ["habit"], importance=0.55)
        report["merged"] += g["n"]
    # 4. forget: old, unimportant, never recalled
    cur = store.x("UPDATE memories SET archived=1 WHERE archived=0 AND type='episodic' AND importance<0.35 AND access_count=0 AND minute<?",
                  (now - 24 * 60,))
    extra = store.q("SELECT id FROM memories WHERE archived=0 ORDER BY importance DESC, minute DESC LIMIT -1 OFFSET 400")
    for r in extra:
        store.x("UPDATE memories SET archived=1 WHERE id=?", (r["id"],))
    report["archived"] = len(extra)
    return report
