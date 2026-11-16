"""Settings: built-in defaults, overridden by config/alife.toml when it exists."""
import copy
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    "creature": {"id": "honk", "name": "Honk"},
    # all traits 0..1; they scale how fast needs grow and how much each activity is worth
    "personality": {"curiosity": 0.9, "sociability": 0.4, "creativity": 0.7, "playfulness": 0.7,
                    "independence": 0.8, "patience": 0.5, "cautiousness": 0.35},
    "sim": {"minutes_per_second": 1.0,   # simulated minutes per real second (a day is 24 real minutes)
            "tick_minutes": 0.1,         # world step; 10 Hz at the default speed
            "seed": 0},                  # 0 = different every run
    "model": {"provider": "ollama", "name": "qwen2.5:7b", "embed": "nomic-embed-text",
              "url": "http://127.0.0.1:11434", "min_interval_s": 12, "timeout_s": 90, "temperature": 0.7},
    "mind": {"pace": 3.0,              # how long he stays with one activity (1 = short bursts)
             "quiet_minutes": 360,     # a thought he has already had is not voiced again for this long
             "decide_interval": 180},  # least simulated minutes between asking the model to break a tie
    "server": {"port": 8770},
    "paths": {"data": "data/alife"},
}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(path) if path else ROOT / "config" / "alife.toml"
    if path.exists():
        _merge(cfg, tomllib.loads(path.read_text()))
    return cfg
