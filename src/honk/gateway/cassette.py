"""A cassette gateway: recorded pages instead of the internet. Tuning runs and tests spend nothing and repeat exactly."""
import json
from pathlib import Path

from ..reader.extract import page_text
from ..textsim import similarity

DEFAULT = Path(__file__).resolve().parents[3] / "tests" / "cassette" / "pages.json"


class Cassette:
    def __init__(self, params=None, path=None):
        self.pages = json.loads(Path(path or DEFAULT).read_text("utf-8"))["pages"]
        self.limit = (params or {}).get("gateway", {}).get("page_text", 6000)
        self.i = 0

    def _item(self, p):
        title, text = page_text(p["html"], "text/html", self.limit)
        return {"title": p.get("title") or title, "url": p["url"], "text": text}

    def page(self, url):
        for p in self.pages:
            if p["url"] == url:
                return {**self._item(p), "bytes": len(p["html"])}
        raise ValueError("not on the cassette")

    def feed(self, url):
        items = [self._item(p) for p in self.pages if p.get("feed")]
        return items, sum(len(i["text"]) for i in items)

    def search(self, q):
        scored = sorted(((similarity(q, p["title"] + " " + " ".join(p.get("topics", []))), p) for p in self.pages), key=lambda x: -x[0])
        hits = [{"title": p["title"], "url": p["url"], "snippet": self._item(p)["text"][:160]} for s, p in scored[:4] if s > 0.05]
        return hits, 200 * len(hits)

    def topic(self, topic):
        hits, n = self.search(topic)
        if not hits:
            return None, n
        item = self._item(next(p for p in self.pages if p["url"] == hits[0]["url"]))
        return item, n + len(item["text"])

    def random(self):
        p = self.pages[self.i % len(self.pages)]
        self.i += 1
        item = self._item(p)
        return item, len(item["text"])
