"""What is in a cargo. Code packs it; Honk unpacks it.

Slots (default 12): up to 4 visitor requests (always included, oldest first), about 5 matched to his interests,
about 3 from outside them (serendipity), so he cannot build himself a bubble.
"""
import json

from ..gateway.gateway import Refused
from ..textsim import similarity


def build(window_id, params, db, gateway, postcards, interests, feeds, rnd):
    """Fill cargo_items for this window. Returns the number of items packed."""
    c = params["cargo"]
    seen = {r["url"] for r in db.all("SELECT url FROM cargo_items WHERE url != '' ORDER BY id DESC LIMIT 400")}
    packed = 0

    def pack(slot, source, item, question_id=None, status="packed"):
        nonlocal packed
        if not item or not item.get("text") or item.get("url") in seen or packed >= c["slots"]:
            return False
        seen.add(item.get("url"))
        db.insert("cargo_items", window_id=window_id, slot_type=slot, source=source, title=item.get("title", "")[:200], url=item.get("url", ""),
                  extract_json=json.dumps({"raw": {"title": item.get("title", ""), "text": item["text"][: params["gateway"]["page_text"]]}}),
                  status=status, question_id=question_id)
        packed += 1
        return True

    # visitor requests ride along as slots: they are researched once the hatch is open
    for r in postcards.pending_web(int(c["slots_requests"])):
        db.insert("cargo_items", window_id=window_id, slot_type="request", source="visitor", title=r["text"][:200], url="", extract_json="{}",
                  status="request", question_id=r["question_id"])
        postcards.set(r["id"], status="in cargo", window_id=window_id)
        packed += 1

    topics = list(interests) or list(feeds.get("seed", {}).get("topics", []))
    rnd.shuffle(topics)
    feed_pool = []
    sources = list(feeds.get("feed", []))
    rnd.shuffle(sources)
    for f in sources[:2]:
        try:
            feed_pool += [(f["name"], it) for it in gateway.feed(f["url"])]
        except Refused:
            pass

    matched = 0
    for name, it in feed_pool:      # feed items about things he already cares about
        if matched < 2 and interests and max(similarity(it["title"] + " " + it["text"][:300], t) for t in interests) > 0.2:
            matched += pack("matched", name, it)
    for t in topics:
        if matched >= c["slots_matched"]:
            break
        try:
            matched += pack("matched", "encyclopedia", gateway.topic(t))
        except Refused:
            continue

    lucky = 0
    for name, it in feed_pool:
        if lucky < 1:
            lucky += pack("serendipity", name, it)
    tries = 0
    while lucky < c["slots_serendipity"] and tries < 6:
        tries += 1
        try:
            lucky += pack("serendipity", "a random page", gateway.random())
        except Refused:
            break
    return packed
