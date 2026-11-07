#!/usr/bin/env python3
"""Experiment: which APU command does an input produce?

Loads a save, settles, then presses one button for a few frames and prints the
CPU->APU port bytes the game emits in response.  This is how the music/SFX ids
are identified without guessing: the driver is silent unless the game has
something to say, so every burst belongs to the action that caused it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, Session  # noqa: E402


def drain(c, cursor):
    """Port events newer than `cursor` (sample index)."""
    out = []
    while True:
        msg = c.port_events(cursor, 8000)
        batch = msg.get("events", [])
        if not batch:
            break
        out.extend(batch)
        cursor = int(batch[-1]["s"]) + 1
        if len(batch) < 8000:
            break
    return out, cursor


def show(events, tag):
    writes = [e for e in events if e["t"] == "cpu_wr"]
    if not writes:
        print(f"  {tag}: no cpu_wr")
        return
    # Collapse into bursts: consecutive frames.
    bur = []
    for e in writes:
        if bur and int(e["aux"]) - int(bur[-1][-1]["aux"]) <= 2:
            bur[-1].append(e)
        else:
            bur.append([e])
    for b in bur:
        seq = " ".join(f"p{e['adr']}={e['val']}" for e in b)
        print(f"  {tag}: f{b[0]['aux']} s{b[0]['s']} n={len(b)}  {seq}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--settle", type=int, default=120)
    ap.add_argument("--hold", type=int, default=4)
    ap.add_argument("--after", type=int, default=40)
    ap.add_argument("--press", default="b,y,a,start,select,x,l,r,up,down,left,right")
    ap.add_argument("--port", type=int, default=4430)
    args = ap.parse_args()

    with Session(save=args.save, recomp=args.recomp, port=args.port) as s:
        c = s.client
        c.run_frames(args.settle)
        _, cursor = drain(c, 0)
        print(f"settled at f{c.frame()}, cursor {cursor}")
        for btn in args.press.split(","):
            btn = btn.strip()
            if not btn:
                continue
            c.cmd(f"set_controller {btn}")
            c.run_frames(args.hold)
            c.cmd("set_controller 0")
            c.run_frames(args.after)
            events, cursor = drain(c, cursor)
            show(events, btn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
