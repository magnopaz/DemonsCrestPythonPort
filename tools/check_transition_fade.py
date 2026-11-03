#!/usr/bin/env python3
"""Assert the room-change fade matches the console.

The original fades INIDISP down, holds black while the room loader runs and
fades back up. Measured on the recomp from `lvl_I_murkland-slope_before_door`
(walking through the door, reading INIDISP per frame):

    fade out  28 frames  15 -> 0   FADE_OUT below
    black     64 frames
    fade in   28 frames   1 -> 15  FADE_IN below

The port must reproduce that on a real door crossing, and the area must change
during the black stretch (the console's loader only consumes $008D after the
fade-out). Exits 77 when the binary or the assets are missing, so a tree
without a build skips instead of failing.

Usage:
  python3 tools/check_transition_fade.py [--binary tools/demonscrest-py]
                                         [--assets assets/generated]
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

# Measured values, one entry per frame.
FADE_OUT = [14, 13, 13, 12, 12, 11, 11, 10, 10, 9, 9, 8, 8, 7,
            7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0]
FADE_IN = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 7,
           8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14]
BLACK_FRAMES = 64

# Area 1's gate opens at world-40 (x >= 2008) once the boss is defeated. The
# old exit object at x=1920 became the Hippogriff, so this spawns past the gate
# line with the boss marked cleared; the gate uses the same BeginTransition path
# the door crossing does.
AREA = 1
START_X = 2012
NEXT_AREA = 2


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
               DC_CAMPAIGN="1",
               DC_BOSS_CLEAR="1",
               DC_RUN_FRAMES="200",
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1",
               DC_TRACE_FADE=str(trace))
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_RESUME"):
        env.pop(key, None)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"transition fade: binary exited {proc.returncode}\n"
                         + proc.stdout[-1200:])


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("transition fade: no binary (skip)")
        return 77
    if not (args.assets / f"room_area{AREA}.json").is_file():
        print("transition fade: no assets (skip)")
        return 77

    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-fade-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)
    trace = tmp / "fade.csv"
    run(args.binary, args.assets, trace)

    rows = list(csv.DictReader(trace.open()))
    if not rows:
        print("transition fade: FAIL (empty trace)")
        return 1

    phases = [(int(r["phase"]), int(r["timer"]), int(r["fade"]), int(r["area"]))
              for r in rows]
    out = [f for (p, _t, f, _a) in phases if p == 1]
    black = [x for x in phases if x[0] == 2]
    inn = [f for (p, _t, f, _a) in phases if p == 3]

    errors = []
    if out != FADE_OUT:
        errors.append(f"fade out mismatch: {out}")
    if len(black) != BLACK_FRAMES:
        errors.append(f"black hold {len(black)} frames, expected {BLACK_FRAMES}")
    if any(f != 15 for (_p, _t, f, _a) in black):
        errors.append("black hold is not fully dark")
    if inn != FADE_IN:
        errors.append(f"fade in mismatch: {inn}")

    # The room must change inside the black stretch, never before it.
    first_black = next((i for i, x in enumerate(phases) if x[0] == 2), -1)
    area_before = phases[first_black - 1][3] if first_black > 0 else -1
    area_after = phases[first_black][3] if first_black >= 0 else -1
    if area_before != AREA:
        errors.append(f"area before the load is {area_before}, expected {AREA}")
    if area_after != NEXT_AREA:
        errors.append(f"area after the load is {area_after}, expected {NEXT_AREA}")
    if phases[-1][0] != 0 or phases[-1][2] != 0:
        errors.append(f"transition did not finish: {phases[-1]}")

    if errors:
        print("transition fade: FAIL")
        for e in errors:
            print("  " + e)
        return 1
    print(f"transition fade: PASS ({len(FADE_OUT)}+{BLACK_FRAMES}+{len(FADE_IN)}"
          f" frames, area {AREA}->{NEXT_AREA} inside the black hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
