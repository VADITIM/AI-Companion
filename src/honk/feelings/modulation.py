"""How feelings change the way he thinks: not just words in a prompt, but settings of the calls themselves."""


def temperature(v, mind):
    a = (v["arousal"] + 1.0) / 2.0
    return round(mind["temp_min"] + (mind["temp_max"] - mind["temp_min"]) * a, 2)


def wonder_seeds(v):
    """Hints for the Wonder call, from what he lacks."""
    seeds = []
    if v["urgent"].get("connection"):
        seeds.append("You could wonder about the ones who visit: their world, what they need from you.")
    if v["mood"] < -0.15:
        seeds.append("You could wonder about something small and comforting.")
    if v["weight"] > 0.25:
        seeds.append("You could ask yourself: what must not be lost?")
    if v["urgent"].get("purpose"):
        seeds.append("You could wonder what you might make next, and for whom.")
    return seeds


def wants_web(v):
    """High curiosity pressure: more of his questions should be ones the next cargo can answer."""
    return v["curiosity"] > 0.6


def picky(v):
    """Low purpose makes him choosier about what he keeps."""
    return v["urgent"].get("purpose") or v["purpose"] < 0.3


def favours_building(v):
    return v["urgent"].get("purpose") or v["purpose"] < 0.35


def ambition(v):
    """How big a build he dares: 'small', 'medium' or 'grand'."""
    if v["purpose"] > 0.6 and v["mood"] > 0.3:
        return "grand"
    return "small" if v["mood"] < 0 or v["energy"] < 0.35 else "medium"


def reply_words(v):
    return 40 if v["mood"] < -0.15 or v["energy"] < 0.3 else 80


def slow(v):
    """Low energy: fewer model calls."""
    return v["urgent"].get("energy") or v["energy"] < 0.3
