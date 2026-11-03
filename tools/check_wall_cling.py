#!/usr/bin/env python3
"""Assert the wall cling ($80:E389) works and slides.

The console clings automatically while descending against a tall wall, then
slides: `$22 += 3` per frame capped at `0x00C0` (0.75 px/frame), B jumps off
and Down releases. The port used to require A and freeze the player at vy = 0.

This runs `DC_DEMO=40` in area 3 beside the tall column at x=336..351 and
checks the trace: state 8 appears, x stays put, y grows, vy ends at the cap,
and the cling ends when the wall does.

Usage: python3 tools/check_wall_cling.py [--binary tools/demonscrest-py]
                                        [--assets assets/generated] [--tmp DIR]
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AREA = 3
START_X = 360
START_Y = 400
FRAMES = 120
CLING_STATE = 8          # PLAYER_WALL_CLING
SLIDE_CAP = 0.7505       # 0x00C0 in 8.8, with a little float slack


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def run(binary: Path, assets: Path, trace: Path) -> None:
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_START_X=str(START_X),
               DC_START_Y=str(START_Y),
               DC_DEMO="40",
               DC_RUN_FRAMES=str(FRAMES),
               DC_TRACE_CSV=str(trace),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1")
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"wall cling: binary exited {proc.returncode}\n"
                         + proc.stdout[-1200:])


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("wall cling: no binary (skip)")
        return 77
    if not (args.assets / f"room_area{AREA}.json").is_file():
        print("wall cling: no assets (skip)")
        return 77

    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-cling-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)
    trace = tmp / "cling.csv"
    run(args.binary, args.assets, trace)

    rows = list(csv.DictReader(trace.open()))
    cling = [r for r in rows if int(r["state"]) == CLING_STATE]
    if not cling:
        print("wall cling: FAIL (the player never entered state 8)")
        print("  states seen: " + str(sorted({r["state"] for r in rows})))
        return 1

    xs = [float(r["player_x"]) for r in cling]
    ys = [float(r["player_y"]) for r in cling]
    vys = [float(r["vy"]) for r in cling]
    last_vy = vys[-1]
    after = [r for r in rows if int(r["frame"]) > int(cling[-1]["frame"])]

    errors = []
    if max(xs) - min(xs) > 1.5:
        errors.append(f"x drifted while clinging: {min(xs):.1f}..{max(xs):.1f}")
    if ys[-1] - ys[0] < 8.0:
        errors.append(f"the cling did not slide (y {ys[0]:.1f}..{ys[-1]:.1f})")
    if last_vy > SLIDE_CAP:
        errors.append(f"slide exceeded the 0x00C0 cap: vy={last_vy:.3f}")
    if last_vy < 0.70:
        errors.append(f"slide never reached the cap: vy={last_vy:.3f}")
    if not after or any(int(r["state"]) == CLING_STATE for r in after):
        errors.append("the cling did not end when the wall did")

    if errors:
        print("wall cling: FAIL")
        for e in errors:
            print("  " + e)
        return 1
    print(f"wall cling: PASS ({len(cling)} frames in state 8, "
          f"x {xs[0]:.1f} fixed, y {ys[0]:.1f}->{ys[-1]:.1f}, vy cap {last_vy:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
