"""The Hatch: the one door to the internet. Nothing else in Honk may open a connection to the outside.

Every call is checked against the cargo window, charged to the window's budget, cached, and written to gateway_log.
While the hatch is closed a call is counted and refused with a fixed message; it is never carried out.
"""
import json
import re
import urllib.parse

from ..reader.extract import feed_items, page_text, strip_tags
from . import policy

CLOSED_MESSAGE = "the hatch is closed"
SPENT_MESSAGE = "the hatch is humming: this window's budget is used up"


class Refused(Exception):
    """The gateway said no (closed, out of budget, or an address it will not open)."""


class LiveTransport:
    """Real requests to the public web: GET only, public addresses only."""

    def __init__(self, params):
        self.g = params["gateway"]

    def _get(self, url):
        return policy.http_get(url, self.g["max_page"], self.g["timeout_s"])

    def page(self, url):
        final, ctype, body = self._get(url)
        if not ("html" in ctype or ctype.startswith("text/") or "json" in ctype or "xml" in ctype or not ctype):
            raise ValueError(f"that is not a text page ({ctype})")
        title, text = page_text(body, ctype, self.g["page_text"])
        return {"url": final, "title": title, "text": text, "bytes": len(body)}

    def feed(self, url):
        _, _, body = self._get(url)
        return feed_items(body), len(body)

    def _summary(self, url):
        _, _, body = self._get(url)
        d = json.loads(body)
        if d.get("type") == "disambiguation" or not d.get("extract"):
            return None, len(body)
        return {"title": d.get("title", ""), "url": d.get("content_urls", {}).get("desktop", {}).get("page", url), "text": d["extract"]}, len(body)

    def topic(self, topic):
        hits, n = self.search(topic)
        wiki = [h for h in hits if "wikipedia.org/wiki/" in h["url"]]
        if not wiki:
            return None, n
        got, m = self._summary("https://en.wikipedia.org/api/rest_v1/page/summary/" + wiki[0]["url"].rsplit("/wiki/", 1)[1])
        return got, n + m

    def random(self):
        return self._summary("https://en.wikipedia.org/api/rest_v1/page/random/summary")

    def search(self, q):
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 5, "utf8": 1})
        _, _, body = self._get(url)
        hits = [{"title": h["title"], "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(h["title"].replace(" ", "_")),
                 "snippet": strip_tags(h.get("snippet", ""))} for h in json.loads(body).get("query", {}).get("search", [])]
        return hits, len(body)


class Gateway:
    def __init__(self, params, db, scheduler, transport, now=lambda: 0.0):
        self.p, self.db, self.sched, self.t, self.now = params, db, scheduler, transport, now
        self.window, self.used, self.cache, self.refused = -1, {}, {}, 0

    def _roll(self):
        if self.sched.window != self.window:    # a new cargo: fresh budget, empty cache
            self.window, self.used, self.cache = self.sched.window, {"searches": 0, "fetches": 0, "bytes": 0}, {}

    def budget(self):
        self._roll()
        g = self.p["gateway"]
        return {k: {"used": self.used[k], "of": g[k]} for k in ("searches", "fetches", "bytes")}

    def spent(self, kind):
        b = self.budget()
        return b[kind]["used"] >= b[kind]["of"] or b["bytes"]["used"] >= b["bytes"]["of"]

    def _log(self, kind, what, n, ok, who, note=""):
        self.db.insert("gateway_log", ts=self.now(), window_id=self.sched.window, kind=kind, query_or_url=str(what)[:500], bytes=n, ok=int(ok), who=who, note=note[:200])

    def _call(self, kind, charge, key, who, fn, phase="research"):
        self._roll()
        if not self.sched.web_allowed(phase):
            self.refused += 1
            self._log(kind, key, 0, False, who, CLOSED_MESSAGE)
            raise Refused(CLOSED_MESSAGE)
        if (kind, key) in self.cache:
            return self.cache[(kind, key)]
        if self.spent(charge):
            self._log(kind, key, 0, False, who, "budget")
            raise Refused(SPENT_MESSAGE)
        self.used[charge] += 1
        try:
            result, n = fn()
        except Refused:
            raise
        except Exception as e:      # a dead link, a timeout, an address the policy refuses
            self._log(kind, key, 0, False, who, str(e))
            raise Refused(f"could not be reached ({str(e)[:80]})")
        self.used["bytes"] += n
        self._log(kind, key, n, True, who)
        self.cache[(kind, key)] = result
        return result

    def search(self, query, who="honk"):
        q = re.sub(r"\s+", " ", str(query or "")).strip()[:200]
        if not q:
            raise Refused("empty search")
        return self._call("search", "searches", q.lower(), who, lambda: self.t.search(q))

    def fetch(self, url, who="honk"):
        def go():
            page = self.t.page(url)
            return page, page.pop("bytes", len(page["text"]))
        return self._call("fetch", "fetches", str(url), who, go)

    def feed(self, url, who="manifest"):
        return self._call("feed", "fetches", str(url), who, lambda: self.t.feed(url), phase="feed")

    def topic(self, topic, who="manifest"):
        return self._call("topic", "fetches", str(topic).lower(), who, lambda: self.t.topic(topic), phase="feed")

    def random(self, who="manifest"):
        self._roll()
        self.cache.pop(("random", "random"), None)    # every call is a different page
        return self._call("random", "fetches", "random", who, lambda: self.t.random(), phase="feed")
