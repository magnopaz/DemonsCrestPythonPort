#!/usr/bin/env python3
"""Dump the CPU->APU port traffic of one save state.

The sound driver is command-driven: the game writes a byte to $2140+n ($F4+n
from the SPC's side) and the driver reacts.  `audio_events <first> <max> 2`
returns exactly those events with the sample index and the console frame, which
is how the music/SFX ids in docs/AUDIO_PLAN.md were first seen.

Usage:
  python3 tools/audio/port_probe.py --save <sav> --frames 600 [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, NATIVE_RATE, Session, find_saves  # noqa: E402


def collect(client, frames: int) -> list[dict]:
    """Every port event the server still holds, drained incrementally."""
    events: list[dict] = []
    cursor = 0
    while True:
        msg = client.port_events(cursor, 8000)
        batch = msg.get("events", [])
        if not batch:
            break
        events.extend(batch)
        last = int(batch[-1]["s"])
        nxt = last + 1
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 8000:
            # Nothing older than the ring's tail is missing; stop when the
            # server reports the ring's oldest index above our cursor.
            if int(msg.get("oldest", 0)) > cursor:
                break
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--save", type=Path)
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--settle", type=int, default=0)
    ap.add_argument("--port", type=int, default=4403)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    with Session(save=args.save, recomp=args.recomp, port=args.port) as s:
        c = s.client
        if args.settle:
            c.run_frames(args.settle)
        base = c.frame()
        c.run_frames(args.frames)
        stats = c.cmd("audio_stats")
        events = collect(c, args.frames)
        print(f"frames {base}..{c.frame()}  produced={stats['produced']} "
              f"cpu_port_writes={stats['cpu_port_writes']} "
              f"ported={len(events)}")
        for ev in events[:400]:
            print(f"  s={ev['s']:>9} f={ev['aux']:>5} {ev['t']:<7} "
                  f"p{ev['adr']} = {ev['val']}")
        if len(events) > 400:
            print(f"  ... {len(events) - 400} more")
        if args.json:
            args.json.write_text(json.dumps(
                {"save": str(args.save), "frames": args.frames,
                 "produced": stats["produced"], "events": events}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
