"""What Honk remembers, and how it comes back to him.

Recall score = recency + importance + relevance to what he is thinking about
               + mood congruence (a low mood brings back low memories) + relatedness to his open questions.
"""
import math

from ..textsim import shorten, similarity


class Memory:
    def __init__(self, db, params):
        self.db, self.p = db, params

    def add(self, kind, text, now, importance=0.5, valence=0.0, tags=(), source=""):
        return self.db.insert("memories", ts=now, kind=kind, text=shorten(text, 600), importance=max(0.0, min(1.0, importance)),
                              valence=max(-1.0, min(1.0, valence)), tags=",".join(tags), source=source)

    def recall(self, query, now, mood=0.0, open_text="", n=None, kinds=None, skip=("postcard",)):
        m = self.p["memory"]
        rows = self.db.all("SELECT * FROM memories WHERE faded = 0 ORDER BY id DESC LIMIT ?", (int(m["keep"]),))
        scored = []
        for r in rows:
            if (kinds and r["kind"] not in kinds) or r["kind"] in skip:    # a postcard only repeats the question; it is no knowledge
                continue
            body = r["text"] + " " + r["tags"].replace(",", " ")
            score = (m["w_recency"] * math.exp(-(now - r["ts"]) / m["recency_tau_min"]) + m["w_importance"] * r["importance"]
                     + m["w_relevance"] * similarity(query, body) + m["w_mood"] * (1.0 - abs(r["valence"] - mood) / 2.0)
                     + (m["w_open_q"] * similarity(open_text, body) if open_text else 0.0))
            scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[: int(n or m["recall"])]]

    def texts(self, query, now, **kw):
        return [r["text"] for r in self.recall(query, now, **kw)]

    def fade(self, now):
        """Forgetting: beyond the limit, the oldest unimportant memories leave recall (they stay in the table)."""
        m = self.p["memory"]
        rows = self.db.all("SELECT id, ts, importance FROM memories WHERE faded = 0")
        extra = len(rows) - int(m["keep"])
        if extra <= 0:
            return 0
        rows.sort(key=lambda r: r["importance"] + math.exp(-(now - r["ts"]) / m["recency_tau_min"]))
        for r in rows[:extra]:
            self.db.update("memories", r["id"], faded=1)
        return extra

    def interests(self, n=8):
        """The topics he keeps coming back to: tags of kept things and answers, weighted by importance."""
        score = {}
        for r in self.db.all("SELECT tags, importance FROM memories WHERE faded = 0 AND tags != '' ORDER BY id DESC LIMIT 300"):
            for t in r["tags"].split(","):
                if t:
                    score[t] = score.get(t, 0.0) + r["importance"]
        return [t for t, _ in sorted(score.items(), key=lambda kv: -kv[1])[:n]]
