#!/usr/bin/env python3
"""Assert the death hub: RETRY / SELECT A STAGE / END.

Measured on the stage II takes (docs/TAKES.md §6.3): dying is not a game over.
The death animation runs for ~1.5 s, then the hub appears over the frozen
scene. RETRY reloads the same room at spawn 0 with full HP, SELECT A STAGE
opens the Mode 7 map, and END shows the 4x4 PASS WORD screen, which leads
back to the map.

Area 9's spawn record is (48,412) in ROM coordinates; Player_Init snaps the
feet to the floor 20 px below, so the port's trace reads (48,432) -- the same
+20 offset the avenue spawns show (64,428 -> 64,448). The checker compares
against the port's spawn-0 placement, not the raw ROM coordinate.

The END screen is the retail 4x4 shape filled with the native codec
(zero-padded to 16 base-20 digits); the retail codec is still not inverted.
The pixel check asserts all 16 cells carry a letter.

Usage:
  DISPLAY=:99 python3 tools/check_death_menu.py [--binary tools/demonscrest-py]
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

AREA = 9
KILL_AT = 10
DEATH_MENU_DELAY = 90
SPAWN_X, SPAWN_Y = 48.0, 432.0   # port placement of the (48,412) spawn
START_X, START_Y = 600.0, 400.0  # DC_START placement, snapped to (584,384)

GAME_PLAYING = 1
GAME_OVERWORLD = 5
GAME_CONTINUE = 12
GAME_PASSWORD_VIEW = 13

# The PASS WORD layout in dcpy/game.py: 4x4 cells, 20 px each, starting at
# (88,64); each cell is a 18x18 box with a size-14 letter at cy+3.
GRID_X, GRID_Y, CELL = 88, 64, 20
CELL_LETTER_MIN_PIXELS = 8
LIT_THRESHOLD = 140


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def run(binary: Path, assets: Path, trace: Path, frames: int,
        demo: int | None = None, extra: dict[str, str] | None = None
        ) -> list[dict[str, str]]:
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_CAMPAIGN="1",
               DC_RUN_FRAMES=str(frames),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1",
               DC_TRACE_CSV=str(trace))
    if demo is None:
        env.pop("DC_DEMO", None)
    else:
        env["DC_DEMO"] = str(demo)
    if extra:
        env.update(extra)
    for key in ("DC_STATE", "DC_TITLE", "DC_RESUME", "DC_PASSWORD",
                "DC_START_X", "DC_START_Y", "DC_START_ONCE", "DC_KILL_AT",
                "DC_SCREENSHOT_RT"):
        env.pop(key, None)
    if extra:
        for key in extra:
            if key in ("DC_STATE", "DC_START_X", "DC_START_Y",
                       "DC_START_ONCE", "DC_KILL_AT", "DC_SCREENSHOT_RT"):
                env[key] = extra[key]
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"death menu: run exited {proc.returncode}\n"
                         + proc.stdout[-1200:])
    return list(csv.DictReader(trace.open()))


def modes(rows: list[dict[str, str]]) -> list[int]:
    return [int(row["mode"]) for row in rows]


def first_row(rows: list[dict[str, str]], mode: int) -> dict[str, str] | None:
    return next((row for row in rows if int(row["mode"]) == mode), None)


def check_menu_appears(binary: Path, assets: Path, tmp: Path,
                       errors: list[str]) -> None:
    rows = run(binary, assets, tmp / "death_menu.csv", 150,
               extra={"DC_KILL_AT": str(KILL_AT)})
    if len(rows) != 150:
        errors.append(f"menu: {len(rows)} trace rows, expected 150")
        return
    seq = modes(rows)
    if seq[0] != GAME_PLAYING:
        errors.append(f"menu: run did not start in GAME_PLAYING ({seq[0]})")
    if GAME_CONTINUE not in seq:
        errors.append(f"menu: death never opened the continue hub ({seq[-1]})")
        return
    entry = first_row(rows, GAME_CONTINUE)
    if entry is not None and int(entry["frame"]) < KILL_AT + DEATH_MENU_DELAY:
        errors.append(f"menu: hub opened at frame {entry['frame']}, before the "
                      f"{DEATH_MENU_DELAY}-frame death animation")
    if seq[-1] != GAME_CONTINUE:
        errors.append(f"menu: run ended in mode {seq[-1]}, not the hub")
    if entry is not None and int(entry["hp"]) != 0:
        errors.append(f"menu: hub shows hp {entry['hp']}, expected 0")


def check_retry(binary: Path, assets: Path, tmp: Path,
                errors: list[str]) -> None:
    rows = run(binary, assets, tmp / "death_retry.csv", 280, demo=42,
               extra={"DC_START_X": str(START_X),
                      "DC_START_Y": str(START_Y),
                      "DC_START_ONCE": "1",
                      "DC_KILL_AT": str(KILL_AT)})
    seq = modes(rows)
    if GAME_CONTINUE not in seq:
        errors.append(f"retry: the hub never appeared ({sorted(set(seq))})")
        return
    start = rows[0]
    if abs(float(start["player_x"]) - START_X) > 32.0:
        errors.append(f"retry: started at x={start['player_x']}, expected the "
                      f"DC_START placement near {START_X:g}")
    if seq[-1] != GAME_PLAYING:
        errors.append(f"retry: run ended in mode {seq[-1]}, not GAME_PLAYING")
    last = rows[-1]
    if int(last["area"]) != AREA:
        errors.append(f"retry: reloaded area {last['area']}, expected {AREA}")
    if abs(float(last["player_x"]) - SPAWN_X) > 1.0 or \
            abs(float(last["player_y"]) - SPAWN_Y) > 1.0:
        errors.append(f"retry: respawned at ({last['player_x']},"
                      f"{last['player_y']}), expected spawn 0 "
                      f"({SPAWN_X:g},{SPAWN_Y:g})")
    if int(last["hp"]) != int(last["max_hp"]) or int(last["hp"]) <= 0:
        errors.append(f"retry: hp {last['hp']}/{last['max_hp']}, expected full")


def check_select_stage(binary: Path, assets: Path, tmp: Path,
                       errors: list[str]) -> None:
    rows = run(binary, assets, tmp / "death_select.csv", 80, demo=43,
               extra={"DC_STATE": "continue"})
    seq = modes(rows)
    if GAME_OVERWORLD not in seq:
        errors.append(f"select: SELECT A STAGE did not open the map "
                      f"({sorted(set(seq))})")
    if seq[-1] != GAME_OVERWORLD:
        errors.append(f"select: run ended in mode {seq[-1]}, not the map")


def check_end_screen(binary: Path, assets: Path, tmp: Path,
                     errors: list[str]) -> None:
    shot = (tmp / "death_password.png").resolve()
    rows = run(binary, assets, tmp / "death_end.csv", 70, demo=44,
               extra={"DC_STATE": "continue", "DC_SCREENSHOT_RT": str(shot)})
    seq = modes(rows)
    if GAME_PASSWORD_VIEW not in seq:
        errors.append(f"end: END did not open the PASS WORD screen "
                      f"({sorted(set(seq))})")
        return
    if seq[-1] != GAME_PASSWORD_VIEW:
        errors.append(f"end: run ended in mode {seq[-1]}, not the PASS WORD "
                      "screen")
    if not shot.is_file():
        errors.append(f"end: no screenshot at {shot}")
        return
    try:
        from PIL import Image
    except ImportError:
        errors.append("end: PIL is not installed, cannot check the screen")
        return
    img = Image.open(shot).convert("L")
    if img.size != (256, 224):
        errors.append(f"end: screenshot is {img.size}, expected 256x224")
        return
    px = img.load()
    lit = 0
    for i in range(16):
        cx = GRID_X + (i % 4) * CELL
        cy = GRID_Y + (i // 4) * CELL
        count = sum(1 for x in range(cx + 1, cx + CELL - 1)
                    for y in range(cy + 1, cy + CELL - 1)
                    if px[x, y] > LIT_THRESHOLD)
        if count >= CELL_LETTER_MIN_PIXELS:
            lit += 1
        else:
            errors.append(f"end: cell {i + 1} has {count} letter pixels")
    if lit != 16:
        errors.append(f"end: only {lit}/16 cells carry a letter")
    title = sum(1 for y in range(18, 44) for x in range(256)
                if px[x, y] > LIT_THRESHOLD)
    if title < 40:
        errors.append("end: the PASS WORD title is not drawn")
    push = sum(1 for y in range(172, 192) for x in range(256)
               if px[x, y] > LIT_THRESHOLD)
    if push < 30:
        errors.append("end: PUSH START BUTTON is not drawn")


def check_password_to_map(binary: Path, assets: Path, tmp: Path,
                          errors: list[str]) -> None:
    rows = run(binary, assets, tmp / "death_password_map.csv", 140, demo=45,
               extra={"DC_STATE": "continue"})
    seq = modes(rows)
    if GAME_PASSWORD_VIEW not in seq:
        errors.append("end: the PASS WORD screen never appeared")
        return
    after = seq[seq.index(GAME_PASSWORD_VIEW):]
    if GAME_OVERWORLD not in after:
        errors.append(f"end: START on the PASS WORD screen did not open the "
                      f"map ({sorted(set(after))})")


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("death menu: no binary (skip)")
        return 77
    if not (args.assets / f"room_area{AREA}.json").is_file():
        print("death menu: no assets (skip)")
        return 77

    errors: list[str] = []
    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-death-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)

    check_menu_appears(args.binary, args.assets, tmp, errors)
    check_retry(args.binary, args.assets, tmp, errors)
    check_select_stage(args.binary, args.assets, tmp, errors)
    check_end_screen(args.binary, args.assets, tmp, errors)
    check_password_to_map(args.binary, args.assets, tmp, errors)

    if errors:
        print("death menu: FAIL")
        for error in errors:
            print("  - " + error)
        return 1
    print("death menu: PASS (death animation -> RETRY / SELECT A STAGE / END; "
          "retry at spawn 0 with full HP; END draws 16 letters and returns "
          "to the map)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
