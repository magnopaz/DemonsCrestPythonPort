#!/usr/bin/env python3
"""Assert the species $67 ghoul runs its ROM state machine.

The ghoul's handler ($83:AF74) has five states with four substates each. In
area 1 the four ghouls start perched, so the port must take them through the
volley (state 4, 32 frames of windup + three children 64 frames apart + 32 of
hold), then the small hop loop (state 0) and the long hop (state 2), while the
children damage the player.

This check runs the binary with the player on the first ghoul's ledge, reads
`DC_TRACE_OBJECTS` and asserts that order plus the children. Exit 77 when the
binary/assets are missing.

Usage: python3 tools/check_ghoul.py [--binary tools/demonscrest-py]
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

# Area 1's first $67 sits at (958, 76); spawning short of it puts the player on
# the same ledge without needing an input script.
AREA = 1
START_X = 920
START_Y = 76
FRAMES = 600

VOLLEY_END = (250, 270)   # measured: state 4 ends at frame 257
HOP_END = (390, 430)      # measured: state 0 hands over to state 2 at 401


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
               DC_RUN_FRAMES=str(FRAMES),
               DC_TRACE_OBJECTS=str(trace),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1")
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_CAMPAIGN"):
        env.pop(key, None)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"ghoul: binary exited {proc.returncode}\n"
                         + proc.stdout[-1200:])


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("ghoul: no binary (skip)")
        return 77
    if not (args.assets / f"room_area{AREA}.json").is_file():
        print("ghoul: no assets (skip)")
        return 77

    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-ghoul-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)
    trace = tmp / "objects.csv"
    run(args.binary, args.assets, trace)

    rows = list(csv.DictReader(trace.open()))
    ghouls = [r for r in rows if r["species"] == str(0x67) and r["type"] == "3"]
    if not ghouls:
        print("ghoul: FAIL (no species $67 object in the trace)")
        return 1

    # Follow one slot so interleaved objects don't look like state changes.
    slot = ghouls[0]["slot"]
    seq = [(int(r["frame"]), int(r["state"])) for r in ghouls if r["slot"] == slot]
    changes = []
    prev = None
    for frame, state in seq:
        if state != prev:
            changes.append((frame, state))
            prev = state

    errors = []
    states = [s for _f, s in changes]
    if 4 not in states or 0 not in states or 2 not in states:
        errors.append(f"states seen: {changes} (want 4 -> 0 -> 2)")

    def first(state: int) -> int | None:
        for f, s in changes:
            if s == state:
                return f
        return None

    end4 = first(0)
    end0 = first(2)
    if end4 is not None and not (VOLLEY_END[0] <= end4 <= VOLLEY_END[1]):
        errors.append(f"volley ended at frame {end4}, expected {VOLLEY_END}")
    if end0 is not None and not (HOP_END[0] <= end0 <= HOP_END[1]):
        errors.append(f"hop loop ended at frame {end0}, expected {HOP_END}")

    children = [r for r in rows if r["type"] == "7"]
    if not children:
        errors.append("the volley spawned no children (OBJECT_ENEMY_SHOT)")

    ys = [float(r["y"]) for r in ghouls if r["slot"] == slot]
    if ys and max(ys) - min(ys) < 40.0:
        errors.append(f"ghoul never left its perch (y range {min(ys):.0f}..{max(ys):.0f})")

    if errors:
        print("ghoul: FAIL")
        for e in errors:
            print("  " + e)
        return 1
    print(f"ghoul: PASS (states {changes}, {len(children)} child object frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
