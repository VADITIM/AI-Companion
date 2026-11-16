"""Turns things that happen into appraisal vectors, by rules. Each function returns a feelings event (without its time)."""
import re

KIND = re.compile(r"\b(thank|thanks|love|lovely|kind|wonderful|beautiful|proud|happy|glad|hello|hi|please|friend|miss|care|hug|great|amazing|sweet|dear)\b", re.I)
HARSH = re.compile(r"\b(stupid|dumb|hate|ugly|useless|worthless|shut up|idiot|boring|pathetic|fake|liar|die|trash|garbage|annoying|loser)\b", re.I)
LOSS = re.compile(r"\b(extinct|extinction|lost|last|vanish|vanished|ruin|ruins|died|death|forgotten|war|famine|flood|collapse|abandoned|grave|mourning)\b", re.I)


def warmth_of(text):
    """-1 harsh .. +1 kind, from plain words. A postcard is data: this only colours how it feels to read."""
    k, h = len(KIND.findall(text or "")), len(HARSH.findall(text or ""))
    if not k and not h:
        return 0.15
    return max(-1.0, min(1.0, (k - 1.5 * h) / max(2.0, k + h)))


def ev(kind, source=None, topics=None, direct=None, set_=None, **appraisal):
    e = {"kind": kind, "source": source or kind, "appraisal": appraisal}
    if topics:
        e["topics"] = topics
    if direct:
        e["direct"] = direct
    if set_:
        e["set"] = set_
    return e


def cargo_arrived(ledger_fraction):
    return ev("cargo_arrived", novelty=0.5, expectedness=0.3, mission_relevance=0.5, set_={"ledger": ledger_fraction})


def item_judged(keep, interest, novelty, text="", topics=None, source="cargo"):
    loss = 0.04 if LOSS.search(text or "") else 0.0
    return ev("item_kept" if keep else "item_passed", source=source, topics=topics, direct={"weight": loss} if loss else None,
              novelty=novelty, mission_relevance=(0.3 + 0.6 * interest) if keep else 0.05, agency=0.3 if keep else 0.0, effort=0.1)


def answered(gain, interest, topics=None):
    """gain = confidence gained on a question he cares about: the only thing that relieves curiosity."""
    g = max(0.0, gain) * (0.4 + 0.6 * interest)
    return ev("answered", topics=topics, learning_gain=min(1.0, g * 1.6), agency=0.25 * min(1.0, g * 2), novelty=0.1)


def no_answer():
    return ev("no_answer", learning_gain=0.0, agency=-0.15, effort=0.2)


def postcard(text, visitor):
    w = warmth_of(text)
    return ev("postcard", source=f"visitor:{visitor}", warmth=w, novelty=0.35, mission_relevance=0.3)


def replied():
    return ev("replied", warmth=0.35, mission_relevance=0.5, agency=0.35)


def note_written():
    return ev("note", agency=0.25, mission_relevance=0.15)


def build_placed():
    return ev("build_placed", source="build", agency=0.9, mission_relevance=0.6, effort=0.3, novelty=0.3)


def build_dropped():
    return ev("build_dropped", source="build", agency=-0.6, effort=0.5)


def vault_release():
    return ev("vault_release", effort=0.4, mission_relevance=0.3, novelty=0.1)


def hatch_closed(open_web):
    return ev("hatch_closed", expectedness=-min(0.6, 0.1 * open_web), novelty=-0.1)


def budget_out():
    return ev("budget_out", expectedness=-0.3, effort=0.2)


def overwhelmed():
    return ev("overwhelmed", effort=0.5, agency=-0.2)


def quiet():
    return ev("quiet", novelty=-0.3, expectedness=0.3)


def web(w_open):
    return {"kind": "web", "set": {"w_open": w_open}}


def sleep():
    return {"kind": "sleep", "set": {"asleep": True}}


def wake():
    return {"kind": "wake", "set": {"asleep": False}}
