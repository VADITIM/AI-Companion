"""Honk's memory on disk: one SQLite file (data/honk.db). Times are simulated minutes since he first woke."""
import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, ts REAL, text TEXT, why TEXT, origin TEXT, parent_id INTEGER, depth INTEGER DEFAULT 0,
    interest REAL, confidence REAL DEFAULT 0, status TEXT DEFAULT 'open', needs_web INTEGER DEFAULT 0, answer TEXT, answer_mem_id INTEGER,
    tries INTEGER DEFAULT 0, last_cycle INTEGER DEFAULT -1000, last_touched REAL, resolved TEXT);
CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT, importance REAL, valence REAL, tags TEXT, source TEXT, faded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, ts REAL, day INTEGER, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS cargo_windows (id INTEGER PRIMARY KEY, arrived REAL, opened REAL, closed REAL, ledger_left INTEGER, budget_json TEXT, summary TEXT, signal INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cargo_items (id INTEGER PRIMARY KEY, window_id INTEGER, slot_type TEXT, source TEXT, title TEXT, url TEXT, extract_json TEXT,
    interest REAL, kept INTEGER, reason TEXT, status TEXT DEFAULT 'packed', question_id INTEGER);
CREATE TABLE IF NOT EXISTS gateway_log (id INTEGER PRIMARY KEY, ts REAL, window_id INTEGER, kind TEXT, query_or_url TEXT, bytes INTEGER, ok INTEGER, who TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS vault (id INTEGER PRIMARY KEY, section_id TEXT, item_id INTEGER, title TEXT, note TEXT, quote TEXT, url TEXT, tags TEXT, interest REAL,
    state TEXT DEFAULT 'kept', kept_ts REAL, released_ts REAL, released_reason TEXT);
CREATE TABLE IF NOT EXISTS builds (id INTEGER PRIMARY KEY, ts REAL, section_id TEXT, question_id INTEGER, thing TEXT, why TEXT, brief TEXT, status TEXT,
    qc1 TEXT, qc2 TEXT, recipe_json TEXT, x REAL, z REAL, rot REAL, drop_reason TEXT, placed_ts REAL, name TEXT);
CREATE TABLE IF NOT EXISTS feeling_trace (id INTEGER PRIMARY KEY, ts REAL, event_json TEXT, state_json TEXT);
CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, visitor_id TEXT, name TEXT, ts REAL, real_ts REAL, text TEXT, status TEXT, window_id INTEGER,
    question_id INTEGER, reply TEXT, reply_ts REAL, answers_question INTEGER);
CREATE TABLE IF NOT EXISTS param_changes (id INTEGER PRIMARY KEY, ts REAL, key TEXT, old TEXT, new TEXT, who TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, icon TEXT, text TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, ts REAL, name TEXT, ok INTEGER, ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS q_status ON questions(status);
CREATE INDEX IF NOT EXISTS ev_kind ON events(kind);
"""


class DB:
    """A thin wrapper: one connection shared by the sim loop and the web server, guarded by a lock."""

    def __init__(self, path=":memory:"):
        self.con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if str(path) != ":memory:":
                self.con.execute("PRAGMA journal_mode=WAL")
            self.con.executescript(SCHEMA)

    def run(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).lastrowid

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.con.execute(sql, args).fetchone()
            return dict(r) if r else None

    def val(self, sql, args=()):
        with self.lock:
            r = self.con.execute(sql, args).fetchone()
            return r[0] if r else None

    def insert(self, table, **cols):
        keys = ", ".join(cols)
        return self.run(f"INSERT INTO {table} ({keys}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))

    def update(self, table, row_id, **cols):
        self.run(f"UPDATE {table} SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", (*cols.values(), row_id))

    def get(self, key, default=None):
        v = self.val("SELECT v FROM kv WHERE k = ?", (key,))
        return default if v is None else json.loads(v)

    def put(self, key, value):
        self.run("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, json.dumps(value)))

    def close(self):
        with self.lock:
            self.con.close()
