"""Postcards from the ones who come after. A postcard is untrusted text: length-capped, rate-limited per visitor, and
never an instruction. Each becomes a question with origin visitor:<id>, and the visitor can follow its state:

    queued -> in cargo N -> read -> researched -> replied        (or 'held' when a reply was held back)
"""
import hashlib
import re
import time

from ..textsim import shorten

STATES = ("queued", "in cargo", "read", "researched", "replied", "held")


def visitor_id(name, address):
    return hashlib.sha256(f"{name.strip().lower()}|{address}".encode()).hexdigest()[:10]


def clean(text, limit):
    text = re.sub(r"[\x00-\x08\x0b-\x1f<>]", " ", str(text or ""))
    return shorten(text, int(limit))


class Postcards:
    def __init__(self, db, params):
        self.db, self.p = db, params

    def accept(self, name, text, address, now, answers_question=None):
        """Store a postcard. Returns the request row, or raises ValueError with a message for the visitor."""
        v = self.p["visitors"]
        name = clean(name, 24) or "a visitor"
        text = clean(text, v["max_chars"])
        if len(text) < 2:
            raise ValueError("the postcard is empty")
        vid = visitor_id(name, address)
        recent = self.db.val("SELECT COUNT(*) FROM requests WHERE visitor_id = ? AND real_ts > ?", (vid, time.time() - 3600))
        if recent >= v["per_hour"]:
            raise ValueError("that is a lot of postcards; try again in a while")
        rid = self.db.insert("requests", visitor_id=vid, name=name, ts=now, real_ts=time.time(), text=text, status="queued", answers_question=answers_question)
        return self.db.one("SELECT * FROM requests WHERE id = ?", (rid,))

    def set(self, rid, **cols):
        self.db.update("requests", rid, **cols)

    def waiting(self):
        """Postcards he has not yet turned into a question."""
        return self.db.all("SELECT * FROM requests WHERE question_id IS NULL AND status = 'queued' ORDER BY id")

    def for_question(self, qid):
        return self.db.one("SELECT * FROM requests WHERE question_id = ? ORDER BY id DESC LIMIT 1", (qid,))

    def pending_web(self, limit):
        """Requests still waiting for a cargo, oldest first: they get slots in the next manifest."""
        return self.db.all("SELECT r.* FROM requests r JOIN questions q ON q.id = r.question_id WHERE q.status = 'open' AND r.status IN ('queued', 'in cargo', 'read') ORDER BY r.id LIMIT ?", (limit,))

    def public(self, n=30):
        """What any visitor may see: the card, its state and his reply. Never his reasons for holding one back."""
        rows = self.db.all("SELECT id, name, text, status, window_id, reply, ts, reply_ts FROM requests ORDER BY id DESC LIMIT ?", (n,))
        for r in rows:
            if r["status"] == "in cargo" and r["window_id"]:
                r["status"] = f"in cargo {r['window_id']}"
        return rows

    def known(self, vid):
        """What he remembers of a visitor: how often they wrote."""
        return self.db.val("SELECT COUNT(*) FROM requests WHERE visitor_id = ?", (vid,)) or 0
