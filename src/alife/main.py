#!/usr/bin/env python3
"""Run the creature.

    python3 src/alife/main.py                    world + mind + viewer at http://127.0.0.1:8770/
    python3 src/alife/main.py --no-model         the same, without ever asking the model
    python3 src/alife/main.py --headless 1440    simulate 1440 minutes as fast as possible, print the measures
    python3 src/alife/main.py --fresh            start a new life (asks before erasing the old one)
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alife import config                      # noqa: E402
from alife.engine import Engine               # noqa: E402
from alife.llm import NullProvider            # noqa: E402
from alife.server import serve                # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headless", type=float, metavar="MINUTES", help="simulate this many minutes without the viewer")
    ap.add_argument("--no-model", action="store_true", help="never call the model; rules only")
    ap.add_argument("--data", help="folder for his memory and the world (default data/alife)")
    ap.add_argument("--port", type=int)
    ap.add_argument("--fresh", action="store_true", help="erase the saved creature and world first")
    args = ap.parse_args()
    cfg = config.load()
    data = Path(args.data) if args.data else config.ROOT / cfg["paths"]["data"]
    if args.fresh and data.exists():
        if input(f"Erase everything in {data}? Type 'erase' to confirm: ").strip() != "erase":
            return print("Nothing erased.")
        shutil.rmtree(data)
    headless = args.headless is not None
    provider = NullProvider() if args.no_model else None
    engine = Engine(cfg, data, provider, sync_llm=headless, catch_up=not headless)
    try:
        if headless:
            engine.run_minutes(args.headless)
            print(json.dumps(engine.mind.measures(), indent=2))
        else:
            port = args.port or cfg["server"]["port"]
            serve(engine, port)
            print(f"{cfg['creature']['name']} is alive. Watch at http://127.0.0.1:{port}/  (model: {engine.provider.name})", flush=True)
            engine.run_realtime()
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()


if __name__ == "__main__":
    main()
