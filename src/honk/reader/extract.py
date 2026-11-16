"""Page to plain text: scripts, styles, navigation and anything hidden are dropped before a model ever sees the page."""
import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser

HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(\.0+)?\s*(;|$)", re.I)
VOID = {"br", "img", "input", "meta", "link", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "iframe", "template", "aside", "select", "head", "header"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote", "dd", "dt", "table", "main"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.title, self.in_title, self.stack = [], "", False, []   # stack: is each open element hidden?

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = tag in self.SKIP or "hidden" in a or a.get("aria-hidden") == "true" or bool(HIDDEN.search(a.get("style") or ""))
        if tag == "title":
            self.in_title = True
        if tag not in VOID:
            self.stack.append((tag, hidden or (bool(self.stack) and self.stack[-1][1])))
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not (self.stack and self.stack[-1][1]):
            self.out.append(data)

    def handle_comment(self, data):
        pass


def strip_tags(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def page_text(body, ctype="text/html", limit=6000):
    """(title, text) of a fetched page."""
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        p = _Text()
        p.feed(body)
        title, raw = p.title, "".join(p.out)
    else:
        title, raw = "", body
    lines = [re.sub(r"\s+", " ", l).strip() for l in raw.splitlines()]
    text = "\n".join(l for l in lines if len(l) >= 20)
    return re.sub(r"\s+", " ", title).strip()[:200], text[:limit]


def feed_items(xml, limit=8):
    """Items of an RSS or Atom feed: [{title, url, text}]."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        got = {"title": "", "url": "", "text": ""}
        for ch in el:
            name = ch.tag.split("}")[-1]
            if name == "title":
                got["title"] = strip_tags(ch.text or "")[:200]
            elif name == "link":
                got["url"] = got["url"] or (ch.get("href") or (ch.text or "")).strip()
            elif name in ("description", "summary", "content", "encoded") and len(ch.text or "") > len(got["text"]):
                got["text"] = strip_tags(ch.text or "")[:3000]
        if got["title"] and got["url"].startswith("http"):
            out.append(got)
        if len(out) >= limit:
            break
    return out
