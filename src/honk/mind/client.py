"""Model runners. The mind and the Foundry talk to this interface only, so a model is swapped in config, not in code.

There is no fallback: a call that fails (unreachable, bad JSON, wrong shape) raises MindError, the caller skips that
cycle, and the failure is counted.
"""
import json
import re
import urllib.error
import urllib.request


class MindError(Exception):
    pass


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise MindError("no JSON in the answer")
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError as e:
        raise MindError(f"bad JSON: {e}")


def _post(url, body, timeout, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise MindError(f"model runner said {e.code}: {e.read(200).decode('utf-8', 'replace')}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MindError(f"model runner unreachable: {getattr(e, 'reason', e)}")


class Ollama:
    def __init__(self, url, model, timeout=120):
        self.url, self.model, self.timeout, self.name = url.rstrip("/"), model, timeout, f"ollama:{model}"

    def chat(self, name, system, user, schema, temperature=0.8, max_tokens=500):
        out = _post(self.url + "/api/chat", {
            "model": self.model, "stream": False, "format": schema, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "num_ctx": 8192, "num_predict": max_tokens}}, self.timeout)
        return parse_json(out.get("message", {}).get("content", ""))

    def status(self):
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=3) as r:
                names = [m.get("name", "") for m in json.load(r).get("models", [])]
        except Exception:
            return {"up": False, "ready": False, "note": f"Ollama is not answering at {self.url}"}
        ready = any(n in (self.model, self.model + ":latest") for n in names)
        return {"up": True, "ready": ready, "note": "" if ready else f"the model {self.model} is not pulled"}


class OpenAI:
    """Any OpenAI-compatible chat endpoint: llama.cpp's llama-server, LM Studio, OpenRouter."""

    def __init__(self, url, model, timeout=120, key=None):
        url = url.rstrip("/")
        self.url = url if url.endswith("/v1") else url + "/v1"
        self.model, self.timeout, self.key, self.name = model, timeout, key, f"openai:{model}"

    def chat(self, name, system, user, schema, temperature=0.8, max_tokens=500):
        body = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}
        if not self.key:   # a local runner: models that think out loud are told not to
            body["chat_template_kwargs"] = {"enable_thinking": False}
        out = _post(self.url + "/chat/completions", body, self.timeout, {"Authorization": f"Bearer {self.key}"} if self.key else None)
        try:
            return parse_json(out["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            raise MindError("the model runner sent no answer")

    def status(self):
        if self.key:
            return {"up": True, "ready": True, "note": ""}
        try:
            with urllib.request.urlopen(self.url + "/models", timeout=3) as r:
                r.read()
            return {"up": True, "ready": True, "note": ""}
        except Exception:
            return {"up": False, "ready": False, "note": f"no model runner is answering at {self.url}"}


def make(section):
    """A client from a config section ({provider, url, model, timeout_s})."""
    kind = section["provider"]
    if kind == "ollama":
        return Ollama(section["url"], section["model"], section.get("timeout_s", 120))
    if kind == "openai":
        return OpenAI(section["url"], section["model"], section.get("timeout_s", 120))
    if kind == "stub":
        from ..stubs.fake_mind import FakeMind
        return FakeMind()
    raise ValueError(f"unknown model provider {kind!r}")
