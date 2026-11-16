"""The small JSON shape of every typed call, and a checker for them. A reply that does not fit is a failed call."""

S, B, N = {"type": "string"}, {"type": "boolean"}, {"type": "number"}


def obj(required, **props):
    return {"type": "object", "required": list(required), "properties": props}


def arr(items):
    return {"type": "array", "items": items}


WONDER = obj(["questions"], questions=arr(obj(["text"], text=S, why=S, needs_web=B)))
PONDER = obj(["answer", "confidence"], answer=S, confidence=N, follow_up=S)
RESEARCH = obj(["queries"], queries=arr(S), looking_for=S)
JUDGE = obj(["keep", "reason"], keep=B, reason=S, tags=arr(S), interest=N, feeling=S, release_id=N)
RESOLVE = obj(["choice"], choice={"type": "string", "enum": ["reply", "build_request", "note", "ask_visitor", "nothing"]},
              text=S, section=S, thing=S, style_brief=S)
JOURNAL = obj(["entry"], entry=S)
REVIEW = obj(["ok"], ok=B, reason=S)
RECIPE = obj(["name", "parts"], name=S, parts=arr({"type": "object"}))


def check(value, schema, path="answer"):
    """Raises ValueError unless value fits the schema. Numbers given as text and the like are not accepted."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} is not an object")
        for k in schema.get("required", []):
            if k not in value or value[k] is None:
                raise ValueError(f"{path}.{k} is missing")
        for k, sub in schema.get("properties", {}).items():
            if k in value and value[k] is not None:
                check(value[k], sub, f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} is not a list")
        for i, x in enumerate(value):
            check(x, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} is not text")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}")
    elif t == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} is not true or false")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} is not a number")
    return value
