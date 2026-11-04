#!/usr/bin/env python3
"""Assert the pit of Ovununu's opening: $69 raises the flag, $6B climbs.

Measured on the pit take (docs/PIT_BOSS.md §4): once the player is in the
arena ($69 sets $1DEA when x<128 or y>=568), the body climbs from y=700 to
~209 over ~1350 frames and then bobs at 187..216. The 11 $6C eyes are present
but still placeholders; this checker covers the measured opening only.

The run uses the room's own spawn (32,668). Area 8's old 8->10 door-table
entry sat on that spawn and exited the room on frame 1; it was removed from
apply_door_table.py (the save belonged to the avenue, area 4, and the ROM
table has no 8->10), so the pit is reachable in campaign mode.

Usage:
  DISPLAY=:99 python3 tools/check_pit_boss.py [--binary tools/demonscrest-py]
                                              [--assets assets/generated]

Exit codes: 0 = pass, 1 = failure, 77 = binary/assets missing (ctest skip).
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

AREA = 8
FRAMES = 1600
BODY_SPECIES = 107  # $6B
CORE_SPECIES = 105  # $69
EYE_SPECIES = 108   # $6C
EYE_COUNT = 11


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("pit boss: no binary (skip)")
        return 77
    if not (args.assets / f"room_area{AREA}.json").is_file():
        print("pit boss: no assets (skip)")
        return 77

    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-pit-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)
    player_trace = tmp / "pit_player.csv"
    object_trace = tmp / "pit_objects.csv"
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_CAMPAIGN="1",
               DC_RUN_FRAMES=str(FRAMES),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1",
               DC_TRACE_CSV=str(player_trace),
               DC_TRACE_OBJECTS=str(object_trace))
    for key in ("DC_STATE", "DC_TITLE", "DC_DEMO", "DC_RESUME",
                "DC_START_X", "DC_START_Y", "DC_START_ONCE",
                "DC_BOSS_CLEAR", "DC_BOSS_DEFEATED", "DC_KILL_AT"):
        env.pop(key, None)
    proc = subprocess.run([str(args.binary), "--assets", str(args.assets)],
                          cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        print("pit boss: FAIL (binary exited "
              f"{proc.returncode})\n" + proc.stdout[-1200:])
        return 1

    errors: list[str] = []
    players = list(csv.DictReader(player_trace.open()))
    if len(players) != FRAMES:
        errors.append(f"player trace has {len(players)} rows, expected "
                      f"{FRAMES}")
    if players and {int(r["area"]) for r in players} != {AREA}:
        errors.append("the player left area 8 during the run "
                      f"({sorted({int(r['area']) for r in players})})")

    objects = list(csv.DictReader(object_trace.open()))
    body = [r for r in objects if r["species"] == str(BODY_SPECIES)]
    core = [r for r in objects if r["species"] == str(CORE_SPECIES)]
    eyes = {r["slot"] for r in objects if r["species"] == str(EYE_SPECIES)}
    if not body:
        errors.append("the $6B body never entered the object pool")
    if not core:
        errors.append("the $69 core never entered the object pool")
    if len(eyes) != EYE_COUNT:
        errors.append(f"found {len(eyes)} $6C eyes, expected {EYE_COUNT}")

    if body:
        first = body[0]
        if abs(float(first["x"]) - 130.0) > 2.0:
            errors.append(f"the body starts at x={first['x']}, expected 130")
        if float(first["y"]) < 695.0:
            errors.append(f"the body starts at y={first['y']}, expected 700")
        by_frame = {int(r["frame"]): float(r["y"]) for r in body}
        checks = ((300, 610.0, "still too high at frame 300"),
                  (900, 380.0, "still too high at frame 900"),
                  (1350, 220.0, "did not reach the top by frame 1350"))
        for frame, limit, message in checks:
            y = by_frame.get(frame)
            if y is None:
                errors.append(f"no body row at frame {frame}")
            elif y > limit:
                errors.append(f"{message} (y={y:.1f} > {limit:g})")
        bob = [by_frame[f] for f in range(1400, FRAMES) if f in by_frame]
        if not bob:
            errors.append("no body rows after frame 1400")
        else:
            if min(bob) < 180.0 or max(bob) > 225.0:
                errors.append(f"the bob leaves 180..225 "
                              f"(min {min(bob):.1f}, max {max(bob):.1f})")
        xs = {round(float(r["x"]), 1) for r in body}
        if len(xs) != 1:
            errors.append(f"the body moved horizontally: {sorted(xs)[:5]}")

    if core:
        if abs(float(core[0]["x"]) - 128.0) > 1.0 or \
                abs(float(core[0]["y"]) - 640.0) > 1.0:
            errors.append(f"the $69 core is at ({core[0]['x']},"
                          f"{core[0]['y']}), expected (128,640)")

    if errors:
        print("pit boss: FAIL")
        for error in errors:
            print("  - " + error)
        return 1
    print("pit boss: PASS ($69 raises the fight, $6B climbs 700->~209 over "
          "~1350 frames and bobs; 11 $6C eyes present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
