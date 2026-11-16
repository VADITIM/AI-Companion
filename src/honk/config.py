"""Honk's numbers: config/honk.toml, optionally a preset on top, then the live changes made in the tuning panel."""
import copy
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def presets():
    return sorted(p.stem for p in (CONFIG / "presets").glob("*.toml"))


def load(preset=None, overrides=None, path=None):
    """The whole parameter tree as a plain dict."""
    cfg = load_toml(path or CONFIG / "honk.toml")
    if preset:
        _merge(cfg, load_toml(CONFIG / "presets" / f"{preset}.toml"))
    for key, value in (overrides or {}).items():
        set_key(cfg, key, value)
    return cfg


def sections():
    return load_toml(CONFIG / "sections.toml")["section"]


def feeds():
    return load_toml(CONFIG / "feeds.toml")


def canon():
    return (ROOT / "canon" / "canon.md").read_text("utf-8").strip()


def art_rules():
    return (CONFIG / "art_rules.md").read_text("utf-8").strip()


def get_key(cfg, key):
    node = cfg
    for part in key.split("."):
        node = node[part]
    return node


def set_key(cfg, key, value):
    """Set "feelings.valence_tau" style keys. Only existing keys, and only with a value of the same kind."""
    *path, last = key.split(".")
    node = cfg
    for part in path:
        node = node[part]
    old = node[last]
    if isinstance(old, bool) or isinstance(old, (dict, list)):
        raise ValueError(f"{key} cannot be changed here")
    if isinstance(old, (int, float)):
        value = float(value)
        if isinstance(old, int) and value == int(value):
            value = int(value)
    else:
        value = str(value)
    node[last] = value
    return old


def flat(cfg, prefix=""):
    """Every tunable number and word as {"feelings.valence_tau": 120, ...}."""
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out.update(flat(v, f"{prefix}{k}."))
        elif not isinstance(v, list):
            out[prefix + k] = v
    return out


def clone(cfg):
    return copy.deepcopy(cfg)
