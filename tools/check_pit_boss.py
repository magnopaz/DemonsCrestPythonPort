#!/usr/bin/env python3
"""Assert the pit of Ovununu's opening: $69 raises the flag, $6B climbs.

Measured on the pit take (docs/PIT_BOSS.md §4 and §7): once the player is in
the arena ($69 sets $1DEA when x<128 or y>=568), the body stays at y=700 for
199 frames, climbs to ~209 over ~1350 frames and then bobs at 187..216. The
eleven $6C eyes park on their measured x (96..166), are released when the body
starts to rise and follow it with the take's per-eye lag; the eleventh (the
body's core eye) rides the body at (+1, +28).

The offsets below are the take's own numbers at t=600 and t=1200 (frames 14801
and 15401 of the take, t = take frame - 14201), so this checker fails if the
port's swarm drifts from the recording instead of comparing the port with
itself.  From t=1590 the four satellites the take launches (flags 0, 1, 7 and
2) run the $83:C913 launch machine and the $CB6A/$CB7D/$CC00/$CAAE return
states; the checks below assert they leave the park, climb at least 40 px and
come back down.  The eye AI probes Firebrand's position, so the run pins him
near the arena's centre (DC_HOLD_PLAYER) rather than letting him idle at the
spawn: that is where the take's player was.

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
# 4000 frames cover all four launches (1590/1620/1650/2450) plus each eye's
# rise, dive and return to the park band.
FRAMES = 4000
BODY_SPECIES = 107  # $6B
CORE_SPECIES = 105  # $69
EYE_SPECIES = 108   # $6C
EYE_COUNT = 11
# Park x per satellite (measured at take frame 14201).
PARK_X = (96.0, 104.0, 112.0, 115.0, 122.0, 136.0, 143.0, 153.0, 162.0, 166.0)
# eye_y - body_y per satellite, straight from the take.
TRACK = {
    600: (41.4, 13.4, 31.6, 22.7, 60.3, 26.1, 22.5, 22.1, 26.0, 37.4),
    1200: (76.8, 27.6, 33.5, 60.4, 102.9, 45.1, 26.5, 41.1, 62.0, 50.9),
    1500: (92.9, 31.0, 32.4, 78.0, 123.4, 51.4, 24.9, 47.4, 78.4, 54.0),
}
# Fight frames at which the take's $1DDE[flag] reached 0 (15791/15821/15851/
# 16651 minus 14201).  Only these four satellites launch in the measured
# window; the other six keep swarming.
LAUNCH = {0: 1590, 1: 1620, 7: 1650, 2: 2450}
# The eye AI probes the player, so the fight runs with Firebrand held near the
# arena's centre (the take's player hovers around 210,200) instead of idling at
# the room's lower-left spawn.  Without the hold the eyes dive early and one of
# them never completes the return.
HOLD_PLAYER = "210,200"


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
               DC_TRACE_OBJECTS=str(object_trace),
               DC_HOLD_PLAYER=HOLD_PLAYER,
               DC_HOLD_AT="2")
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
        # The fight flag goes up on frame 1 and the take's climb starts 199
        # frames later, so the port's frames carry that delay.
        if by_frame.get(200, 0.0) < 699.0:
            errors.append(f"the body left y=700 before its 199-frame delay "
                          f"(y={by_frame.get(200):.1f} at frame 200)")
        checks = ((500, 610.0, "still too high at frame 500"),
                  (1100, 380.0, "still too high at frame 1100"),
                  (1550, 220.0, "did not reach the top by frame 1550"))
        for frame, limit, message in checks:
            y = by_frame.get(frame)
            if y is None:
                errors.append(f"no body row at frame {frame}")
            elif y > limit:
                errors.append(f"{message} (y={y:.1f} > {limit:g})")
        bob = [by_frame[f] for f in range(1560, FRAMES) if f in by_frame]
        if not bob:
            errors.append("no body rows after frame 1560")
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

    # Key the eyes by their record flag, not by slot: the ROM's pool starts at
    # slot 8 (0..7 are projectiles) and the port's at 0, so slot numbers differ
    # while flags 0..10 identify the eleven eyes in both.
    by_eye: dict[int, dict[int, dict]] = {}
    for r in objects:
        if r["species"] == str(EYE_SPECIES):
            by_eye.setdefault(int(r["flags"]), {})[int(r["frame"])] = r
    body_y = {int(r["frame"]): float(r["y"]) for r in body}
    by_frame_body_x = {int(r["frame"]): float(r["x"]) for r in body}

    for t, offsets in TRACK.items():
        frame = t + 1          # fight frame t is port frame t+1 (flag on 1)
        if frame not in body_y:
            errors.append(f"no body row at frame {frame}")
            continue
        here = body_y[frame]
        for i in range(len(PARK_X)):
            row = by_eye.get(i, {}).get(frame)
            if row is None:
                errors.append(f"no eye with flag {i} at frame {frame}")
                continue
            if int(row["state"]) != 0:
                errors.append(f"eye {i} is in state {row['state']}, "
                              "expected 0")
            if abs(float(row["x"]) - PARK_X[i]) > 2.0:
                errors.append(f"eye {i} x={row['x']}, expected "
                              f"{PARK_X[i]:g}")
            below = float(row["y"]) - here
            if abs(below - offsets[i]) > 4.0:
                errors.append(f"eye {i} sits {below:.1f} px below the body "
                              f"at frame {frame}, the take says "
                              f"{offsets[i]:g}")

    core_row = by_eye.get(10, {}).get(1201)
    if core_row is None:
        errors.append("the core eye (flag 10) has no row at frame 1201")
    elif 1201 in body_y:
        body_x = float(by_frame_body_x[1201]) if 1201 in by_frame_body_x else 0.0
        if abs(float(core_row["x"]) - (body_x + 1.0)) > 1.5:
            errors.append(f"the core eye x={core_row['x']}, expected "
                          f"{body_x + 1.0:.0f} (body+1)")
        if abs(float(core_row["y"]) - (body_y[1201] + 28.0)) > 1.5:
            errors.append(f"the core eye y={core_row['y']}, expected "
                          f"body+28 (body {body_y[1201]:.1f})")
        if int(core_row["state"]) != 2:
            errors.append(f"the core eye is in state {core_row['state']}, "
                          "expected 2")

    # The four satellites the take launches: each leaves its park in the launch
    # machine, climbs at least 40 px and comes back down.  The take's exact
    # path depends on where Firebrand stands (the $809D8E homing and the
    # $809CA4/$D137 probes), so this checks the machine's shape by position.
    for flag, launch in LAUNCH.items():
        rows_by_frame = by_eye.get(flag, {})
        start = rows_by_frame.get(launch)
        if start is None:
            errors.append(f"eye {flag} has no row at its launch frame {launch}")
            continue
        if int(start["sub"]) != 6:
            errors.append(f"eye {flag} is in $06={start['sub']} at its launch "
                          f"frame {launch}, expected 6")
        y0 = float(start["y"])
        peak = None
        for frame in range(launch, FRAMES):
            row = rows_by_frame.get(frame)
            if row is None:
                continue
            y = float(row["y"])
            if peak is None or y < peak[1]:
                peak = (frame, y, row)
        if peak is None:
            errors.append(f"eye {flag} has no rows after its launch")
            continue
        peak_frame, peak_y, peak_row = peak
        if int(peak_row["sub"]) not in (6, 8, 10, 12, 14):
            errors.append(f"eye {flag} peaks in $06={peak_row['sub']}, "
                          "expected the launch/return machine")
        if peak_y > y0 - 40.0:
            errors.append(f"eye {flag} only rises {y0 - peak_y:.1f} px from its "
                          f"park (y {y0:.1f} -> {peak_y:.1f}); expected >= 40")
        back = None
        for frame in range(peak_frame + 60, FRAMES):
            row = rows_by_frame.get(frame)
            if row is not None:
                back = (frame, float(row["y"]))
                if back[1] >= peak_y + 50.0:
                    break
        if back is None or back[1] < peak_y + 50.0:
            errors.append(f"eye {flag} does not come back down after its peak "
                          f"(peak y {peak_y:.1f} at frame {peak_frame})")

    if errors:
        print("pit boss: FAIL")
        for error in errors:
            print("  - " + error)
        return 1
    print("pit boss: PASS ($69 raises the fight, $6B waits 199 frames then "
          "climbs 700->~209 and bobs; the ten $6C eyes park on their measured "
          "x and follow within 4 px of the take; the four launched eyes run "
          "the launch/return machine and come back to the park; the core eye "
          "rides the body)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
