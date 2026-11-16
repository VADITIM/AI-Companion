"""A mind without a model: scripted, seeded answers in the right shapes. For tests, and for watching the whole loop
run offline (mind.provider = "stub"). It is not clever; it only keeps the machinery moving."""
import random
import re

from ..mind.client import MindError
from ..textsim import words

WONDERS = ["What did {a} sound like?", "Who looked after the {a} when nobody was watching?", "Could I make a {a} here on the Moon?",
           "Why did people care so much about {a}?", "What would the ones who come after want to know about {a}?", "How did a {a} and a {b} belong together?",
           "What is the smallest thing about {a} worth keeping?", "What did people feel when they saw a {a}?"]
THINGS = ["a small tower for {a}", "a cairn that remembers {a}", "a lantern for {a}", "a bench to think about {a}", "an arch for {a}", "a bell for {a}", "a shelf for {a}"]
SEEDS = ["tide", "bread", "bell", "kite", "garden", "lullaby", "map", "clock", "bridge", "choir", "tea", "lighthouse"]


def _lines(user, header):
    m = re.search(re.escape(header) + r"\n((?:- .*\n?)+)", user)
    return [l[2:].strip() for l in m.group(1).splitlines()] if m else []


class FakeMind:
    name = "stub"

    def __init__(self, seed=7, fail_every=0):
        self.rnd, self.fail_every, self.n = random.Random(seed), fail_every, 0

    def status(self):
        return {"up": True, "ready": True, "note": "scripted mind (no model)"}

    def chat(self, name, system, user, schema, temperature=0.8, max_tokens=500):
        self.n += 1
        if self.fail_every and self.n % self.fail_every == 0:
            raise MindError("the scripted mind was told to fail")
        return getattr(self, "_" + name)(user)

    def _topic(self, text):
        w = [x for x in words(text) if len(x) > 3]
        return self.rnd.choice(w) if w else self.rnd.choice(SEEDS)

    def _wonder(self, user):
        mem = _lines(user, "On your mind:")
        out = []
        for _ in range(self.rnd.choice([1, 1, 2, 2, 3])):
            a = self._topic(self.rnd.choice(mem)) if mem and self.rnd.random() < 0.7 else self.rnd.choice(SEEDS)
            out.append({"text": self.rnd.choice(WONDERS).format(a=a, b=self.rnd.choice(SEEDS)), "why": f"I keep thinking about {a}.",
                        "needs_web": self.rnd.random() < (0.6 if "hungry" in user else 0.35)})
        return {"questions": out}

    def _ponder(self, user):
        q = re.search(r"The question: (.*)", user).group(1)
        read = re.findall(r"^(?:summary|fact): (.*)$", user, re.M)
        mem = [m for m in _lines(user, "What you remember:") if set(words(m)) & set(words(q))]
        if read:
            return {"answer": "From what I read: " + " ".join(read[:2]), "confidence": round(self.rnd.uniform(0.65, 0.9), 2),
                    "follow_up": self.rnd.choice(["", "", self.rnd.choice(WONDERS).format(a=self._topic(read[0]), b="bell")])}
        if mem:
            return {"answer": "I think I know a little: " + mem[0], "confidence": round(self.rnd.uniform(0.5, 0.75), 2), "follow_up": ""}
        return {"answer": "I do not know yet. The next cargo may tell me.", "confidence": round(self.rnd.uniform(0.1, 0.35), 2), "follow_up": ""}

    def _research(self, user):
        q = re.search(r"find out: (.*)", user).group(1)
        return {"queries": [" ".join(sorted(set(words(q)), key=len, reverse=True)[:2]) or "tide"], "looking_for": "anything that explains it plainly"}

    def _reader(self, user):
        body = user.replace("<page>", "").replace("</page>", "").strip()
        title, _, text = body.partition("\n")
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 20]
        return {"summary": " ".join(sentences[:2]), "key_facts": sentences[1:5], "quotes": sentences[:1], "topics": [w for w in words(title)][:3] or ["misc"],
                "reliability_note": "A plain description; nothing checks it."}

    def _judge(self, user):
        title = (re.search(r"title: (.*)", user) or [None, "something"])[1]
        keep = self.rnd.random() < (0.3 if "choosy" in user else 0.5)
        out = {"keep": keep, "reason": (f"The ones who come after should know about {title.lower()}." if keep else f"{title} is nice, but it is not for the shelf."),
               "tags": words(title)[:3] or ["misc"], "interest": round(self.rnd.uniform(0.2, 0.95), 2), "feeling": self.rnd.choice(["warm", "curious", "wistful", "glad"])}
        ids = re.findall(r"^(\d+): ", user, re.M)
        if keep and ids:
            out["release_id"] = int(ids[0])
        return out

    def _resolve(self, user):
        q = re.search(r"You asked yourself: (.*)", user).group(1)
        a = self._topic(q)
        locked = "Foundry is busy" in user
        roll = self.rnd.random()
        if roll < 0.4 and not locked:
            ids = re.findall(r"^- (\w+): ", user, re.M)
            sections = [i for i in ids if i not in ("note", "ask_visitor", "nothing", "build_request")]
            return {"choice": "build_request", "text": f"I want something here that shows {a}.", "section": self.rnd.choice(sections or ["garden"]),
                    "thing": self.rnd.choice(THINGS).format(a=a), "style_brief": "simple and warm, a little lonely, with one small light"}
        if roll < 0.75:
            return {"choice": "note", "text": f"About {a}: " + re.search(r"Your answer: (.*)", user).group(1)[:200]}
        if roll < 0.87:
            return {"choice": "ask_visitor", "text": f"Do you still have {a} where you live? What is it like?"}
        return {"choice": "nothing", "text": ""}

    def _journal(self, user):
        h = _lines(user, "What happened since then:")
        return {"entry": "Today: " + " ".join(h[:3]) + " I am glad to be the one who looks after it."}
