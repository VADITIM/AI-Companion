"""Feelings in words. A prompt carries at most two, and never a number."""

BANK = {
    "energy": ["Your eyes keep closing.", "You are worn out and want your nest.", "Your wings feel heavy."],
    "curiosity": ["Questions are piling up and you are itching to look things up.", "You are hungry to find things out.",
                  "There is so much you want to know and cannot reach yet."],
    "connection": ["It has been quiet for a long time; you wonder about the ones who come after.", "You miss hearing from someone.",
                   "You would like someone to tell things to."],
    "purpose": ["You feel you have not done much that matters lately.", "You want to make or keep something that counts.",
                "Your wings itch to do something worth doing."],
    "mood_high": ["You feel light and glad.", "You are in a bright mood.", "Something has you quietly happy."],
    "mood_low": ["You feel a bit low.", "Your heart is heavy today.", "Things feel grey right now."],
    "aroused": ["You are wide awake and buzzing.", "You feel stirred up.", "Your thoughts are quick today."],
    "weight": ["You keep thinking about how much has been lost.", "The counted cargos sit on your mind.",
               "You feel the size of what you are looking after."],
}


def salient(v, n=2):
    """The strongest few feelings as keys of BANK, strongest first. Needs that are not urgent are left out."""
    found = [(v["urgency"][k], k) for k in ("energy", "curiosity", "connection", "purpose") if v["urgent"].get(k) or v["urgency"][k] > 0.7]
    if v["mood"] > 0.45:
        found.append((v["mood"], "mood_high"))
    if v["mood"] < -0.15:
        found.append((0.6 - v["mood"], "mood_low"))
    if v["arousal"] > 0.45:
        found.append((v["arousal"], "aroused"))
    if v["weight"] > 0.25:
        found.append((0.4 + v["weight"], "weight"))
    return [k for _, k in sorted(found, reverse=True)[:n]]


def in_words(v, rnd, n=2):
    return " ".join(rnd.choice(BANK[k]) for k in salient(v, n))
