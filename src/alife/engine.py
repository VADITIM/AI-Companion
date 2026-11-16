"""Puts the world, the mind and the memory together and steps them. Nothing here knows about HTTP."""
import json
import random
import threading
import time
from pathlib import Path

from .llm import make_provider
from .memory import Store
from .mind import Mind
from .protocol import Bus
from .world import World

MAX_OFFLINE_MINUTES = 8 * 60      # however long the program was closed, he lives at most this much of it


class Engine:
    def __init__(self, cfg, data_dir, provider=None, sync_llm=False, catch_up=True):
        self.cfg, self.dir = cfg, Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        seed = cfg["sim"].get("seed") or None
        self.bus = Bus()
        self.world = World(self.bus, random.Random(seed), cfg["creature"]["id"], cfg.get("mind", {}).get("pace", 1.0))
        self.world_file = self.dir / "world.json"
        if self.world_file.exists():
            self.world.from_dict(json.loads(self.world_file.read_text()))
        self.store = Store(self.dir / "creature.db")
        self.provider = provider or make_provider(cfg["model"])
        self.mind = Mind(self.bus, self.store, self.provider, cfg, random.Random(seed and seed + 1), sync_llm)
        self.dt = cfg["sim"]["tick_minutes"]
        self.lock = threading.RLock()
        self.speed, self.paused, self.running = 1, False, False
        self._saved_at = self.world.minute
        if catch_up and self.mind.saved_real:
            away = min(MAX_OFFLINE_MINUTES, (time.time() - self.mind.saved_real) * cfg["sim"]["minutes_per_second"])
            if away >= 5:
                self.world.advance_offline(away)
                self.mind.advance_offline(away)

    def step(self):
        with self.lock:
            self.world.tick(self.dt)
            self.mind.tick(self.dt)
            if self.world.minute - self._saved_at >= 10:
                self.save_world()

    def run_minutes(self, minutes):
        for _ in range(int(minutes / self.dt)):
            self.step()

    def run_realtime(self):
        self.running = True
        period = self.dt / self.cfg["sim"]["minutes_per_second"]
        nxt = time.monotonic()
        while self.running:
            if not self.paused:
                for _ in range(self.speed):
                    self.step()
            nxt += period
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.monotonic()

    def save_world(self):
        self._saved_at = self.world.minute
        tmp = self.world_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.world.to_dict()))
        tmp.replace(self.world_file)

    def close(self):
        self.running = False
        with self.lock:
            self.save_world()
            self.mind.shutdown()
            self.store.close()

    def snapshot(self):
        with self.lock:
            return {"world": self.world.snapshot(), "mind": self.mind.snapshot(), "speed": self.speed,
                    "paused": self.paused, "messages": list(self.bus.recent)[-12:]}

    def user_input(self, body):
        """The watcher's hands: stroke him, drop something new into the world, change the speed."""
        with self.lock:
            kind = body.get("type")
            self.world.watcher_until = max(self.world.watcher_until, self.world.minute + 3)
            if kind == "pet":
                self.world.watcher_pet()
            elif kind == "drop":
                pos = body.get("position")
                ok = isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, (int, float)) and 1 <= v <= 39 for v in pos)
                return {"ok": True, "id": self.world.spawn_mystery(pos if ok else None)}
            elif kind == "speed" and body.get("value") in (1, 4, 16):
                self.speed = body["value"]
            elif kind == "pause":
                self.paused = not self.paused
            elif kind != "presence":
                return {"ok": False, "error": "unknown input"}
            return {"ok": True}
