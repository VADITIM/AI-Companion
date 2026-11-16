#!/usr/bin/env python3
"""Honk's local server: serves the world viewer and gives Honk his tools.

Standard library only. Run it from anywhere:

    python3 src/honk/server.py

then open http://127.0.0.1:8765/

Endpoints (JSON in, JSON out):
  GET  /api/status           model and search settings, and whether the model runner answers
  POST /api/llm              {messages, schema?, options?} -> {content}; forwarded to Ollama /api/chat
  POST /api/search           {query} -> {source, results: [{title, url, snippet}]}
  POST /api/fetch            {url} -> {url, title, text, links}; public http(s) pages only, reduced to text.
                             url "random" opens a random encyclopedia page
  POST /api/share            {project, title, note}; shares one of his programs on his GitHub account: straight away
                             if config/accounts.json says "share": "auto", otherwise it waits in the outbox
  GET  /api/outbox           programs waiting for the watcher's OK
  POST /api/outbox           {id, action: "approve" | "discard"}
  POST /api/workspace/write  {path, content}; only workspace/projects/<name>/<file>, old versions kept
  GET  /api/state            Honk's memory (data/honk-state.json)
  POST /api/state            save Honk's memory (never replaces a newer memory version with an older one)
  POST /api/log              append one event to data/events.jsonl (the archive; never trimmed)
  POST /api/settings         {"code_model": false} switches the code model off: a program it is writing stops at once, and
                             programs and builds use HONK_MODEL from then on; true switches it back on
  POST /api/models/reset     stops everything the models are writing and unloads them from Ollama
  POST /api/reset            {"confirm": "erase everything"}; deletes his memory, the archive and workspace/projects

Settings (environment variables):
  HONK_MODEL    model name in Ollama            (default qwen2.5:7b)
  HONK_CODE_MODEL  optional bigger model used only for writing programs and building (e.g. qwen2.5-coder:14b)
  OLLAMA_URL    where Ollama listens            (default http://127.0.0.1:11434)
  HONK_PORT     port for this server            (default 8765)
  HONK_DATA, HONK_WORKSPACE   folders for his memory and his programs (default data/ and workspace/)
  HONK_SEARXNG  optional SearXNG base URL with JSON output enabled; otherwise DuckDuckGo,
                with Wikipedia as the fallback

Accounts (config/accounts.json, git-ignored; you create the accounts, Honk never sees a password or token):
  {"github": {"user": "his-github-name", "token": "github_pat_...", "share": "ask"}}
  The token is a fine-grained personal access token limited to his own repositories, with
  Administration and Contents set to read and write. "share": "ask" (default) puts each share in the outbox
  for you to approve in the Works panel; "auto" lets him share on his own.
"""

import base64
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("HONK_DATA") or ROOT / "data")                 # a separate copy here keeps test runs away from his real memory
WORKSPACE = Path(os.environ.get("HONK_WORKSPACE") or ROOT / "workspace")
STATIC = {"World": ROOT / "World", "workspace": WORKSPACE}
ACCOUNTS_FILE = ROOT / "config" / "accounts.json"
GITHUB_API = os.environ.get("HONK_GITHUB_API", "https://api.github.com").rstrip("/")
RANDOM_PAGE = "https://en.wikipedia.org/wiki/Special:Random"

MODEL = os.environ.get("HONK_MODEL", "qwen2.5:7b")
CODE_MODEL = os.environ.get("HONK_CODE_MODEL", "").strip()   # optional: a bigger model just for programs and builds
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PORT = int(os.environ.get("HONK_PORT", "8765"))
SEARXNG = os.environ.get("HONK_SEARXNG", "").rstrip("/")
UA = "Mozilla/5.0 (compatible; HonkResearchBot/0.1; local personal prototype)"

MAX_REQUEST = 4_000_000     # bytes accepted in one request body
MAX_DOWNLOAD = 2_000_000    # bytes read from one web page
MAX_PAGE_TEXT = 6_000       # characters of page text handed to the model
MAX_FILE = 300_000          # bytes per file Honk writes
MAX_PROJECTS = 80
MAX_STATE = 3_000_000

SAFE_FILE = re.compile(r"^projects/[a-z0-9][a-z0-9-]{0,47}/[a-z0-9][a-z0-9_.-]{0,63}\.(html|css|js|json|md|txt|svg)$")


# ---------------------------------------------------------------- outbound requests (public internet only)

def check_url(url):
    """Allow only http(s) URLs whose host resolves to public addresses."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http and https URLs can be opened")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None)
    except socket.gaierror:
        raise ValueError(f"cannot find the host {parts.hostname}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise ValueError("only public internet addresses can be opened")


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


PUBLIC = urllib.request.build_opener(CheckedRedirect)


def fetch(url, data=None, headers=None, trusted=False, timeout=15):
    if not trusted:
        check_url(url)
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en", **(headers or {})})
    opener = urllib.request.build_opener() if trusted else PUBLIC
    with opener.open(req, timeout=timeout) as r:
        body = r.read(MAX_DOWNLOAD)
        charset = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), r.headers.get("Content-Type", ""), body.decode(charset, "replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "iframe", "template", "aside", "select"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote", "dd", "dt", "table", "main"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_title = [], 0, "", False
        self.links, self.href, self.anchor = [], None, []   # links in the readable part of the page, in reading order

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag == "a" and not self.skip:
            self.href, self.anchor = dict(attrs).get("href"), []
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag == "a" and self.href:
            self.links.append((self.href, re.sub(r"\s+", " ", "".join(self.anchor)).strip()))
            self.href = None
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)
            if self.href:
                self.anchor.append(data)


JUNK_LINK = re.compile(r"^(edit|\[\d+\]|\d+|log ?in|sign ?(in|up)|privacy|cookies?|terms|help|donate|subscribe|share|next|previous|more|here|read more|skip.*)$", re.I)


def pick_links(base, raw, limit=12):
    """Links worth following: absolute http(s), with real words as their text, not back to the same page."""
    out, seen, page = [], set(), urllib.parse.urldefrag(base)[0]
    for href, text in raw:
        url = urllib.parse.urldefrag(urllib.parse.urljoin(base, href))[0]
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or url == page or url in seen or len(text) < 4 or JUNK_LINK.match(text):
            continue
        if "/wiki/" in parts.path and ":" in parts.path.split("/wiki/", 1)[1]:
            continue  # Wikipedia's Special:, File:, Help: and talk pages
        seen.add(url)
        out.append({"text": text[:80], "url": url})
        if len(out) >= limit:
            break
    return out


def read_page(url):
    if url.lower() == "random":
        url = RANDOM_PAGE
    final, ctype, body = fetch(url)
    links = []
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        p = TextExtractor()
        p.feed(body)
        title, raw, links = p.title, "".join(p.out), pick_links(final, p.links)
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        title, raw = "", body
    else:
        raise ValueError(f"that is not a text page ({ctype or 'unknown type'})")
    lines = [re.sub(r"\s+", " ", l).strip() for l in raw.splitlines()]
    text = "\n".join(l for l in lines if len(l) >= 20)
    return {"url": final, "title": re.sub(r"\s+", " ", title).strip()[:200], "text": text[:MAX_PAGE_TEXT], "links": links}


# ---------------------------------------------------------------- web search

def search_searxng(q):
    _, _, body = fetch(f"{SEARXNG}/search?" + urllib.parse.urlencode({"q": q, "format": "json"}), trusted=True)
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": strip_tags(r.get("content", ""))}
            for r in json.loads(body).get("results", [])[:6]]


DDG_BLOCKED_UNTIL = 0.0


def search_duckduckgo(q):
    global DDG_BLOCKED_UNTIL
    if time.time() < DDG_BLOCKED_UNTIL:
        return []
    _, _, html = fetch("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": q}).encode(),
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "anomaly" in html.lower() and "result__title" not in html:
        DDG_BLOCKED_UNTIL = time.time() + 1800  # it asked for a bot check; leave it alone for a while
        raise ValueError("DuckDuckGo asked for a bot check")
    results = []
    for chunk in html.split('class="result__title"')[1:]:
        a = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not a:
            continue
        href = unescape(a.group(1))
        if href.startswith("//"):
            href = "https:" + href
        uddg = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg")
        if uddg:
            href = uddg[0]
        if not href.startswith("http") or "duckduckgo.com/y.js" in href:
            continue  # adverts
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', chunk, re.S)
        results.append({"title": strip_tags(a.group(2)), "url": href, "snippet": strip_tags(snippet.group(1)) if snippet else ""})
        if len(results) >= 6:
            break
    return results


def search_duckduckgo_answers(q):
    """DuckDuckGo's Instant Answer API: short abstracts and related topics, no full web results."""
    _, _, body = fetch("https://api.duckduckgo.com/?" + urllib.parse.urlencode({"q": q, "format": "json", "no_html": 1, "skip_disambig": 1}))
    data, results = json.loads(body), []
    if data.get("AbstractURL") and data.get("AbstractText"):
        results.append({"title": data.get("Heading") or q, "url": data["AbstractURL"], "snippet": data["AbstractText"][:300]})
    topics = []
    for t in data.get("RelatedTopics", []):
        topics.extend(t.get("Topics", []) if "Topics" in t else [t])
    for t in topics:
        if t.get("FirstURL") and t.get("Text") and "duckduckgo.com/" not in t["FirstURL"]:
            results.append({"title": t["Text"].split(" - ")[0][:120], "url": t["FirstURL"], "snippet": t["Text"][:300]})
    return results[:6]


def search_wikipedia(q):
    _, _, body = fetch("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 6, "utf8": 1}))
    return [{"title": h["title"], "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(h["title"].replace(" ", "_")),
             "snippet": strip_tags(h.get("snippet", ""))} for h in json.loads(body).get("query", {}).get("search", [])]


def search(q):
    q = str(q or "").strip()[:200]
    if not q:
        raise ValueError("empty search")
    if SEARXNG:
        engines = [("searxng", search_searxng)]
    else:
        engines = [("duckduckgo", search_duckduckgo), ("duckduckgo answers", search_duckduckgo_answers), ("wikipedia", search_wikipedia)]
    errors, merged, sources = [], [], []
    for name, fn in engines:
        try:
            results = fn(q)
        except Exception as e:  # try the next engine
            errors.append(f"{name}: {e}")
            continue
        if results and name == "duckduckgo":
            return {"source": name, "results": results}
        if results:
            sources.append(name)
            merged += [r for r in results if r["url"] not in {m["url"] for m in merged}]
    if merged:
        return {"source": " + ".join(sources), "results": merged[:6]}
    if errors and len(errors) == len(engines):
        raise ValueError("search failed (" + "; ".join(errors) + ")")
    return {"source": " + ".join(n for n, _ in engines), "results": []}


# ---------------------------------------------------------------- model runner (Ollama)

def ollama_status(model=None):
    model = model or MODEL
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:
        return False, False
    return True, any(n in (model, model + ":latest") for n in names)


def llm(body):
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages missing")
    clean = [{"role": m["role"], "content": str(m["content"])} for m in messages
             if isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")]
    opts = {k: v for k, v in (body.get("options") or {}).items() if k in ("temperature", "num_predict", "top_p", "seed")}
    # programs and builds go to the code model when there is one (and it is pulled); everything else to the everyday model
    model = CODE_MODEL if code_model_on() and body.get("purpose") in ("code", "build") and ollama_status(CODE_MODEL)[1] else MODEL
    # programs and builds are streamed, so the page can show the code as he types it (GET /api/live)
    live = body.get("purpose") in ("code", "build")
    payload = {"model": model, "messages": clean, "stream": live, "keep_alive": "15m",
               "options": {"num_ctx": 8192, "temperature": 0.9, **opts}}
    if isinstance(body.get("schema"), dict):
        payload["format"] = body["schema"]
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    started_epoch = GEN["epoch"]
    try:
        # a big code model that does not fit on the GPU writes slowly: give it up to 40 minutes
        with urllib.request.urlopen(req, timeout=2400 if model == CODE_MODEL else 600) as r:
            if not live:
                out = json.load(r)
                return {"content": out.get("message", {}).get("content", ""), "tokens": out.get("eval_count")}
            with LIVE_LOCK:
                LIVE.update(id=LIVE["id"] + 1, tag=str(body.get("tag") or "")[:40], purpose=body.get("purpose"), model=model, text="", tokens=0, done=False, started=time.time())
            parts, tokens = [], None
            for line in r:
                if GEN["epoch"] != started_epoch:
                    raise ValueError("stopped: the models were reset")
                if model == CODE_MODEL and not code_model_on():
                    raise ValueError("stopped: the code model was switched off")
                if not line.strip():
                    continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    parts.append(piece)
                    with LIVE_LOCK:
                        LIVE["text"] += piece
                        LIVE["tokens"] += 1
                if chunk.get("done"):
                    tokens = chunk.get("eval_count")
                    break
            return {"content": "".join(parts), "tokens": tokens}
    except urllib.error.HTTPError as e:
        raise ValueError(f"model runner said {e.code}: {e.read(300).decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        raise ValueError(f"model runner unreachable at {OLLAMA}: {e.reason}")
    finally:
        if live:
            with LIVE_LOCK:
                LIVE["done"] = True
            # stopped part-way (switched off, or the models were reset): now that the stream is closed, drop the model from memory
            if (model == CODE_MODEL and not code_model_on()) or GEN["epoch"] != started_epoch:
                threading.Thread(target=unload, args=(model,), daemon=True).start()


# the code model can be switched off from the page (the 🧠 button); remembered in data/settings.json
def load_settings():
    f = DATA / "settings.json"
    try:
        return json.loads(f.read_text("utf-8")) if f.exists() else {}
    except (ValueError, OSError):
        return {}


SETTINGS = {}


def code_model_on():
    if "code_model" not in SETTINGS:
        SETTINGS["code_model"] = load_settings().get("code_model", True) is not False
    return bool(CODE_MODEL) and SETTINGS["code_model"]


# every generation remembers the epoch it started in; a reset bumps it, and running streams stop
GEN = {"epoch": 0}


def unload(model):
    """Ask Ollama to drop a model from memory right away (it loads again fresh on the next request)."""
    if not model:
        return False
    req = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def reset_models(body=None):
    """Stop everything the models are writing and unload them, so the next request starts clean."""
    GEN["epoch"] += 1
    with LIVE_LOCK:
        LIVE.update(text="", tokens=0, done=True)
    unloaded = [m for m in dict.fromkeys([MODEL, CODE_MODEL]) if m and unload(m)]
    print("Models reset: " + (", ".join(unloaded) or "none were loaded"), flush=True)
    return {"ok": True, "unloaded": unloaded}


def set_settings(body):
    if not isinstance(body, dict) or not isinstance(body.get("code_model"), bool):
        raise ValueError('send {"code_model": true or false}')
    SETTINGS["code_model"] = body["code_model"]
    settings = {**load_settings(), "code_model": body["code_model"]}
    DATA.mkdir(exist_ok=True)
    (DATA / "settings.json").write_text(json.dumps(settings), "utf-8")
    if not body["code_model"]:
        threading.Thread(target=unload, args=(CODE_MODEL,), daemon=True).start()   # free the GPU for the everyday model
    return {"ok": True, "code_model": CODE_MODEL, "code_model_on": code_model_on()}


# what the code model is writing right now (or last wrote), for the page's live terminal
LIVE = {"id": 0, "tag": "", "purpose": None, "model": None, "text": "", "tokens": 0, "done": True, "started": 0}
LIVE_LOCK = threading.Lock()


# ---------------------------------------------------------------- Honk's files and memory

def write_workspace(path, content):
    path = str(path or "")
    if not SAFE_FILE.match(path):
        raise ValueError("Honk may only write projects/<name>/<file> with a text extension")
    data = str(content).encode("utf-8")
    if len(data) > MAX_FILE:
        raise ValueError("file too big")
    target = WORKSPACE / path
    project = target.parent
    if not project.exists():
        existing = [p for p in (WORKSPACE / "projects").glob("*") if p.is_dir()] if (WORKSPACE / "projects").exists() else []
        if len(existing) >= MAX_PROJECTS:
            raise ValueError("too many projects")
    project.mkdir(parents=True, exist_ok=True)
    if target.exists():
        history = project / ".history"
        history.mkdir(exist_ok=True)
        shutil.copy2(target, history / f"{target.stem}.{time.strftime('%Y%m%d-%H%M%S')}{target.suffix}")
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return {"ok": True, "path": path, "bytes": len(data)}


def load_state():
    f = DATA / "honk-state.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


WRITER = {"tab": "", "at": 0.0}   # the page that last saved his memory


def save_state(state):
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    # an older page (an older memory format) must never overwrite a newer memory
    try:
        stored = load_state().get("v", 0)
    except (ValueError, OSError):
        stored = 0
    if isinstance(stored, int) and stored > (state.get("v") if isinstance(state.get("v"), int) else 0):
        raise ValueError(f"this memory is version {stored}; refusing to overwrite it with version {state.get('v')}")
    # pages running older code (an older "cv") may not save over newer code's memory either
    stored_cv = load_state().get("cv", 0) if (DATA / "honk-state.json").exists() else 0
    if isinstance(stored_cv, int) and stored_cv > (state.get("cv") if isinstance(state.get("cv"), int) else 0):
        raise ValueError("this page runs older code: reload it")
    # only one page at a time lives Honk's life: another tab that saved in the last 30 seconds wins until it goes quiet
    tab, now = str(state.pop("_tab", "") or ""), time.time()
    if tab and WRITER["tab"] and WRITER["tab"] != tab and now - WRITER["at"] < 30:
        raise ValueError("Honk is already running in another tab")
    if tab:
        WRITER.update(tab=tab, at=now)
    data = json.dumps(state, ensure_ascii=False)
    if len(data) > MAX_STATE:
        raise ValueError("state too big")
    DATA.mkdir(exist_ok=True)
    tmp = DATA / "honk-state.json.tmp"
    tmp.write_text(data, "utf-8")
    tmp.replace(DATA / "honk-state.json")
    return {"ok": True}


def append_log(event):
    DATA.mkdir(exist_ok=True)
    with open(DATA / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **(event if isinstance(event, dict) else {"event": event})}, ensure_ascii=False) + "\n")
    return {"ok": True}


def erase_all(body):
    """Forget everything: memory, the event archive and every program he wrote."""
    if not isinstance(body, dict) or body.get("confirm") != "erase everything":
        raise ValueError('send {"confirm": "erase everything"}')
    removed = []
    for name in ("honk-state.json", "honk-state.json.tmp", "events.jsonl", "outbox.json"):
        f = DATA / name
        if f.exists():
            f.unlink()
            removed.append(f"data/{name}")
    projects = WORKSPACE / "projects"
    if projects.exists():
        count = sum(1 for p in projects.iterdir())
        shutil.rmtree(projects)
        removed.append(f"workspace/projects ({count} entries)")
    projects.mkdir(parents=True, exist_ok=True)
    print("Erased: " + (", ".join(removed) or "nothing to erase"), flush=True)
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------- accounts and sharing (secrets stay here, never in a prompt)

def load_accounts():
    try:
        data = json.loads(ACCOUNTS_FILE.read_text("utf-8")) if ACCOUNTS_FILE.exists() else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"config/accounts.json could not be read: {e}", file=sys.stderr, flush=True)
        return {}
    gh = data.get("github") if isinstance(data, dict) else None
    return {"github": gh} if isinstance(gh, dict) and gh.get("user") and gh.get("token") else {}


def account_names():
    """What Honk may know about his accounts: the site and his name there, nothing else."""
    return [f"github ({a['user']})" for k, a in load_accounts().items() if k == "github"]


def github(method, path, body=None):
    gh = load_accounts().get("github")
    if not gh:
        raise ValueError("no GitHub account is set up (config/accounts.json)")
    req = urllib.request.Request(GITHUB_API + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={
        "Authorization": f"Bearer {gh['token']}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "honk-companion", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            e.close()
            return 404, {}
        raise ValueError(f"GitHub said {e.code}: {e.read(300).decode('utf-8', 'replace')}")


def project_files(slug):
    folder = WORKSPACE / "projects" / slug
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", slug or "") or not folder.is_dir():
        raise ValueError("no such program")
    return [f for f in sorted(folder.iterdir()) if f.is_file() and SAFE_FILE.match(f"projects/{slug}/{f.name}")]


def publish_github(slug, note):
    """Create (or reuse) the repository <slug> on his account and put the program's files in it."""
    user = load_accounts()["github"]["user"]
    files = project_files(slug)
    if not files:
        raise ValueError("that program has no files")
    code, repo = github("GET", f"/repos/{user}/{slug}")
    if code == 404:
        _, repo = github("POST", "/user/repos", {"name": slug, "description": str(note)[:300], "auto_init": False})
    for f in files:
        path = f"/repos/{user}/{slug}/contents/{urllib.parse.quote(f.name)}"
        code, old = github("GET", path)
        body = {"message": f"Honk updates {f.name}", "content": base64.b64encode(f.read_bytes()).decode()}
        if code != 404 and old.get("sha"):
            body["sha"] = old["sha"]
        github("PUT", path, body)
    return repo.get("html_url") or f"https://github.com/{user}/{slug}"


def load_outbox():
    f = DATA / "outbox.json"
    try:
        return json.loads(f.read_text("utf-8")) if f.exists() else []
    except (OSError, json.JSONDecodeError):
        return []


def save_outbox(items):
    DATA.mkdir(exist_ok=True)
    tmp = DATA / "outbox.json.tmp"
    tmp.write_text(json.dumps(items, ensure_ascii=False), "utf-8")
    tmp.replace(DATA / "outbox.json")


def share(body):
    accounts = load_accounts()
    if "github" not in accounts:
        raise ValueError("Honk has no account to share on yet")
    slug = str(body.get("project", ""))
    project_files(slug)  # checks it exists
    item = {"id": f"{int(time.time() * 1000):x}", "project": slug, "title": str(body.get("title") or slug)[:80],
            "note": str(body.get("note") or "")[:300], "account": account_names()[0], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if accounts["github"].get("share") == "auto":
        url = publish_github(slug, item["note"])
        append_log({"kind": "shared", "project": slug, "url": url})
        return {"status": "published", "project": slug, "url": url}
    items = [i for i in load_outbox() if i.get("project") != slug] + [item]
    save_outbox(items[-20:])
    return {"status": "waiting", "project": slug, "id": item["id"]}


def outbox_decide(body):
    items = load_outbox()
    item = next((i for i in items if i.get("id") == body.get("id")), None)
    if not item:
        raise ValueError("nothing like that is waiting")
    if body.get("action") == "approve":
        url = publish_github(item["project"], item["note"])
        result = {"status": "published", "project": item["project"], "url": url}
    elif body.get("action") == "discard":
        result = {"status": "discarded", "project": item["project"]}
    else:
        raise ValueError('action must be "approve" or "discard"')
    save_outbox([i for i in items if i is not item])
    append_log({"kind": "outbox", **result})
    return result


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "Honk/0.1"

    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/World/main-hub.html")
            self.end_headers()
        elif path == "/api/status":
            up, has = ollama_status()
            self.send_json({"model": MODEL, "llm": up, "has_model": has, "llm_url": OLLAMA,
                            "search": "searxng" if SEARXNG else "duckduckgo (wikipedia fallback)", "accounts": account_names(),
                            "code_model": CODE_MODEL, "code_model_on": code_model_on()})
        elif path == "/api/live":
            with LIVE_LOCK:
                self.send_json({**LIVE, "elapsed": round(time.time() - LIVE["started"], 1) if LIVE["started"] else 0})
        elif path == "/api/outbox":
            self.send_json({"items": load_outbox()})
        elif path == "/api/state":
            self.send_json(load_state())
        else:
            self.serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname not in ("127.0.0.1", "localhost"):
            return self.send_json({"error": "forbidden origin"}, 403)
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_json({"error": "send JSON"}, 415)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_REQUEST:
            return self.send_json({"error": "request too big"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            # while one page is living Honk's life, other pages (another tab, an old page) may not think or write for him
            tab = self.headers.get("X-Honk-Tab", "")
            if path in ("/api/llm", "/api/workspace/write", "/api/log", "/api/share") and WRITER["tab"] and tab != WRITER["tab"] and time.time() - WRITER["at"] < 30:
                return self.send_json({"error": "Honk is already running in another tab"}, 409)
            routes = {
                "/api/llm": lambda: llm(body),
                "/api/search": lambda: search(body.get("query")),
                "/api/fetch": lambda: read_page(str(body.get("url", "")).strip()),
                "/api/workspace/write": lambda: write_workspace(body.get("path"), body.get("content", "")),
                "/api/state": lambda: save_state(body),
                "/api/log": lambda: append_log(body),
                "/api/reset": lambda: erase_all(body),
                "/api/share": lambda: share(body),
                "/api/outbox": lambda: outbox_decide(body),
                "/api/settings": lambda: set_settings(body),
                "/api/models/reset": lambda: reset_models(body),
            }
            if path not in routes:
                return self.send_json({"error": "not found"}, 404)
            self.send_json(routes[path]())
        except (ValueError, urllib.error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError) as e:
            self.send_json({"error": str(getattr(e, "reason", e))}, 400 if isinstance(e, (ValueError, json.JSONDecodeError)) else 502)
        except urllib.error.HTTPError as e:
            self.send_json({"error": f"the site answered {e.code}"}, 502)

    def serve_static(self, path):
        head, _, rest = urllib.parse.unquote(path).lstrip("/").partition("/")
        base = STATIC.get(head)
        if not base or not rest:
            return self.send_error(404)
        base = base.resolve()
        target = (base / rest).resolve()
        if base not in target.parents:
            return self.send_error(404)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self.send_error(404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if head == "workspace":  # Honk's own programs run in a sandbox, away from this server's API
            self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-modals allow-pointer-lock")
        self.end_headers()
        self.wfile.write(data)


def main():
    (WORKSPACE / "projects").mkdir(parents=True, exist_ok=True)
    up, has = ollama_status()
    print(f"Honk's world: http://127.0.0.1:{PORT}/", flush=True)
    print(f"Model: {MODEL} at {OLLAMA} -> " + ("ready" if has else "model not pulled (ollama pull " + MODEL + ")" if up else "Ollama not reachable"), flush=True)
    if CODE_MODEL:
        print(f"Code model (programs and builds): {CODE_MODEL}" + ("" if not up or ollama_status(CODE_MODEL)[1] else f" -> not pulled yet (ollama pull {CODE_MODEL})"), flush=True)
    print("Search: " + ("SearXNG at " + SEARXNG if SEARXNG else "DuckDuckGo, Wikipedia as fallback"), flush=True)
    print("Accounts: " + (", ".join(account_names()) or "none (see config/accounts.json in HONK.md)"), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
