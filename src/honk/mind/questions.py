"""The question queue: the unit of Honk's curiosity. Every behaviour traces back to a question, a cargo item or a visitor.

Rules that keep it from looping (plan, section 5.3): dedupe, a depth cap on follow-up chains, a backlog cap with triage,
a lockout so the same question does not come straight back, and answered-is-answered.
"""
from ..textsim import shorten, similarity

OPEN, ANSWERED, PARKED, DROPPED, BUILT = "open", "answered", "parked", "dropped", "built"


class Questions:
    def __init__(self, db, params):
        self.db, self.p = db, params

    def get(self, qid):
        return self.db.one("SELECT * FROM questions WHERE id = ?", (qid,))

    def open(self):
        return self.db.all("SELECT * FROM questions WHERE status = 'open' ORDER BY interest DESC, id")

    def recent(self, n=40):
        return self.db.all("SELECT * FROM questions WHERE status != 'open' ORDER BY last_touched DESC LIMIT ?", (n,))

    def w_open(self):
        """Interest-weighted count of open questions that need the web: what curiosity pressure grows on."""
        return self.db.val("SELECT COALESCE(SUM(interest), 0) FROM questions WHERE status = 'open' AND needs_web = 1") or 0.0

    def add(self, text, why, origin, needs_web, interest, now, parent_id=None):
        """Returns (id, verdict): 'new', 'merged' into an existing question (its id), 'deep' (chain too long) or 'empty'."""
        text = shorten(text, 200)
        if len(text) < 8:
            return None, "empty"
        visitor = origin.startswith("visitor:")
        depth = 0
        if parent_id:
            parent = self.get(parent_id)
            depth = (parent["depth"] if parent else 0) + 1
            if depth > self.p["mind"]["depth_cap"] and not visitor:
                return None, "deep"
        if not visitor:     # a visitor's question is always taken as asked
            for q in self.open() + self.recent(40):
                if similarity(text, q["text"]) >= self.p["mind"]["dedupe"]:
                    if q["status"] == OPEN:
                        self.db.update("questions", q["id"], interest=min(1.0, q["interest"] + 0.08), last_touched=now)
                    return q["id"], "merged"
        qid = self.db.insert("questions", ts=now, text=text, why=shorten(why, 160), origin=origin, parent_id=parent_id, depth=depth,
                             interest=max(0.05, min(1.0, interest)), needs_web=int(bool(needs_web)), last_touched=now)
        return qid, "new"

    def head(self, cycle, web=None, resolved=None):
        """The open question he most wants that is not locked out. web: True/False filters on needs_web."""
        for q in self.open():
            if web is not None and bool(q["needs_web"]) != web:
                continue
            if cycle - q["last_cycle"] < self.p["mind"]["lockout_k"]:
                continue
            return q
        return None

    def touch(self, qid, cycle, now, **cols):
        self.db.update("questions", qid, last_cycle=cycle, last_touched=now, **cols)

    def failed(self, q, cycle, now, needs_web=None):
        """He could not answer it this time. After a few tries it is parked."""
        tries = q["tries"] + 1
        cols = {"tries": tries}
        if needs_web is not None:
            cols["needs_web"] = int(needs_web)
        if tries >= self.p["mind"]["max_tries"] and not q["origin"].startswith("visitor:"):
            cols["status"] = PARKED
        self.touch(q["id"], cycle, now, **cols)
        return cols.get("status") == PARKED

    def answer(self, q, answer, confidence, mem_id, cycle, now):
        self.touch(q["id"], cycle, now, status=ANSWERED, answer=shorten(answer, 700), confidence=confidence, answer_mem_id=mem_id)

    def to_resolve(self):
        """Answered, and he has not yet decided what to do with it."""
        return self.db.one("SELECT * FROM questions WHERE status = 'answered' AND resolved IS NULL ORDER BY interest DESC, id LIMIT 1")

    def reopen(self, qid, now):
        """Only new evidence from a cargo reopens an answered question."""
        self.db.update("questions", qid, status=OPEN, resolved=None, needs_web=0, tries=0, last_touched=now)

    def triage(self, now):
        """Over the backlog cap: park the questions he cares least about. Returns the parked ones."""
        rows = self.open()
        cap = int(self.p["mind"]["backlog_cap"])
        if len(rows) <= cap:
            return []
        keep_first = sorted(rows, key=lambda q: (not q["origin"].startswith("visitor:"), -q["interest"], q["id"]))
        parked = keep_first[cap:]
        for q in parked:
            self.db.update("questions", q["id"], status=PARKED, last_touched=now)
        return parked
