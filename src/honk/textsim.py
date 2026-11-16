"""Cheap word similarity: enough to catch a question asked twice and to find memories about a topic. No model needed."""
import math
import re

STOP = set("""the and for with that this what why how its about from into more some find out get make want see can will just own new
very really also then than them they their there here have has had are was were been being not but all any who whom which while when
where again does did would could should you your him his her she our one two something anything thing things much many like into""".split())


def _stem(w):
    w = re.sub(r"(ings?|ed|es|s|ly)$", "", w)
    return re.sub(r"(.)\1$", r"\1", w)


def words(text):
    return [s for s in (_stem(w) for w in re.findall(r"[a-z]{3,}", str(text or "").lower()) if w not in STOP) if len(s) > 2]


def similarity(a, b):
    """0 nothing in common .. 1 the same words (cosine over word counts)."""
    A, B = words(a), words(b)
    if not A or not B:
        return 0.0
    ca, cb = {}, {}
    for w in A:
        ca[w] = ca.get(w, 0) + 1
    for w in B:
        cb[w] = cb.get(w, 0) + 1
    dot = sum(n * cb.get(w, 0) for w, n in ca.items())
    return dot / math.sqrt(sum(n * n for n in ca.values()) * sum(n * n for n in cb.values()))


def topics(text, n=4):
    """The few longest distinct words: a rough label for what a text is about."""
    seen = []
    for w in sorted(set(words(text)), key=lambda w: (-len(w), w)):
        seen.append(w)
        if len(seen) >= n:
            break
    return seen


def shorten(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
