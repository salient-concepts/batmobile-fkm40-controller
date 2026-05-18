#!/usr/bin/env python3
"""
Sound effect sweep for Track A Batmobile.

Plays sounds 1..N with operator-paced advancement. Operator listens, types
a label, and the script writes sounds.json with the catalog.

Usage (on batbridge, after `bat-connect`):
  python3 sound_sweep.py --count 20

Output: sounds.json {"1": "Engine rev", "2": "...", ...}
"""

from __future__ import annotations
import argparse, json, os, signal, sys, time
from batmobile_controller import BatmobileController

OUT = os.path.join(os.path.dirname(__file__), "sounds.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20, help="indices to probe")
    ap.add_argument("--start", type=int, default=1)
    args = ap.parse_args()

    bat = BatmobileController()
    catalog: dict[str, str] = {}
    if os.path.exists(OUT):
        try:
            catalog = json.load(open(OUT))
            print(f"Loaded existing catalog with {len(catalog)} entries from {OUT}")
        except Exception:
            pass

    def cleanup(*_):
        print("\nShutdown...")
        bat.shutdown()
        json.dump(catalog, open(OUT, "w"), indent=2, sort_keys=True)
        print(f"Wrote {len(catalog)} entries to {OUT}")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    bat.connect()
    print(f"\nSound sweep: indices {args.start}..{args.start + args.count - 1}")
    print("Type a short label after each (or blank to skip, 'q' to quit, 'r' to replay)\n")

    i = args.start
    end = args.start + args.count
    while i < end:
        bat.play_sound(i)
        print(f"  Index {i}: ", end="", flush=True)
        time.sleep(2.0)
        try:
            label = input().strip()
        except EOFError:
            cleanup()
        if label == "q":
            break
        if label == "r":
            continue
        if label:
            catalog[str(i)] = label
            json.dump(catalog, open(OUT, "w"), indent=2, sort_keys=True)
        i += 1

    cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
