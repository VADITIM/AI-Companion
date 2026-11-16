"""Model providers. The mind talks to this interface only, so the model can be swapped without touching the creature."""
import json
import time
import urllib.request


class Unavailable(Exception):
    pass


class NullProvider:
    """No model at all: every request fails at once and the deterministic fallbacks take over."""
    name = "none"

    def available(self):
        return False

    def generate(self, messages, schema=None, temperature=0.7):
        raise Unavailable("no model configured")

    def embed(self, texts):
        return None


class ScriptedProvider(NullProvider):
    """For tests: answers come from a function."""
    name = "scripted"

    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def available(self):
        return True

    def generate(self, messages, schema=None, temperature=0.7):
        self.calls.append(messages)
        return self.fn(messages, schema)


class OllamaProvider:
    def __init__(self, cfg):
        self.url, self.model, self.embed_model = cfg["url"].rstrip("/"), cfg["name"], cfg.get("embed")
        self.timeout, self.name = cfg.get("timeout_s", 90), f"ollama:{cfg['name']}"
        self._down_until, self._embed_ok = 0.0, True

    def _post(self, path, body, timeout):
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            self._down_until = time.monotonic() + 60       # do not hammer a runner that is not answering
            raise Unavailable(str(e)) from None

    def available(self):
        return time.monotonic() >= self._down_until

    def generate(self, messages, schema=None, temperature=0.7):
        if not self.available():
            raise Unavailable("model runner did not answer recently")
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_ctx": 4096, "num_predict": 400}}
        if schema:
            body["format"] = schema
        out = self._post("/api/chat", body, self.timeout)
        try:
            return json.loads(out["message"]["content"])
        except (KeyError, TypeError, ValueError) as e:
            raise Unavailable(f"reply was not JSON: {e}") from None

    def embed(self, texts):
        if not (self.embed_model and self._embed_ok and self.available()):
            return None
        try:
            return self._post("/api/embed", {"model": self.embed_model, "input": texts}, 30).get("embeddings")
        except Unavailable:
            self._embed_ok = False
            self._down_until = 0.0     # a missing embedding model must not switch the chat model off
            return None


def make_provider(cfg):
    return OllamaProvider(cfg) if cfg.get("provider") == "ollama" else NullProvider()


def check(obj, schema, path="reply"):
    """A small JSON-schema check (object, array, string, number, integer, enum, required). Raises ValueError."""
    t = schema.get("type")
    if "enum" in schema and obj not in schema["enum"]:
        raise ValueError(f"{path}: {obj!r} is not one of the allowed values")
    if t == "object":
        if not isinstance(obj, dict):
            raise ValueError(f"{path}: expected an object")
        for key in schema.get("required", []):
            if key not in obj:
                raise ValueError(f"{path}: missing {key}")
        for key, sub in schema.get("properties", {}).items():
            if key in obj:
                check(obj[key], sub, f"{path}.{key}")
    elif t == "array":
        if not isinstance(obj, list):
            raise ValueError(f"{path}: expected a list")
        for i, item in enumerate(obj):
            check(item, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string" and not isinstance(obj, str):
        raise ValueError(f"{path}: expected text")
    elif t in ("number", "integer") and (isinstance(obj, bool) or not isinstance(obj, (int, float))):
        raise ValueError(f"{path}: expected a number")
    return obj
