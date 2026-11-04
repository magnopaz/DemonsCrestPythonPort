#!/usr/bin/env python3
"""Assert the pad_mask contract on the stage II doors.

Every transition record carries a pad mask. 255 means "any direction" and is
how the plain walk-through exits are stored; 8 is the ROM's up bit. The stage
II takes show 5->6, 6->7 and 7->8 preceded by a tap of up (docs/TAKES.md §6.1),
and the avenue's three interior doors (4->46, 4->47, 4->48) open the same way.

For each door the checker does two runs:

  no input, 60 frames   the player stands on the door box and the area must
                        not change -- this is the regression the old
                        proximity-only Game_CheckTransitions could not pass;
  tap up at frame 20    the destination area must appear after the fade.

It also checks the data contract: the door exists at the measured coordinate,
carries pad_mask 8, and the three avenue doors came from the take table
(`source: "take_door"`, 16x16 box, spawn 0), not from a hand edit.

Area 4's `$96` record is typed `boss` by the extractor (a separate question),
so every run sets DC_BOSS_CLEAR + DC_MVP_KEEP_CONTROL: the first unblocks the
transition loop, the second keeps control instead of clearing the area.
DC_START_ONCE keeps DC_START_X/Y on the boot room, so the player lands on the
destination room's real spawn instead of being teleported by the hook.

Usage:
  DISPLAY=:99 python3 tools/check_up_doors.py [--binary tools/demonscrest-py]
                                              [--assets assets/generated]

Exit codes: 0 = pass, 1 = failure, 77 = binary/assets missing (ctest skip).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (source area, door x, door y, destination area, pad_mask)
DOORS: tuple[tuple[int, float, float, int, int], ...] = (
    (4, 424, 428, 46, 8),
    (4, 664, 428, 47, 8),
    (4, 824, 124, 48, 8),
    (5, 1896, 264, 6, 8),
    (6, 432, 856, 7, 8),
    (7, 976, 136, 8, 8),
)

TAKE_DOOR_AREAS = (4,)
TAKE_DOOR_HALF = 16.0
NEGATIVE_FRAMES = 60
POSITIVE_FRAMES = 180
UP_FRAME = 20
GAME_PLAYING = 1


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def room_path(assets: Path, area: int) -> Path:
    return assets / f"room_area{area}.json"


def check_data(assets: Path, errors: list[str]) -> dict[int, dict]:
    """Check the door records and return the source room documents."""
    rooms: dict[int, dict] = {}
    for src, x, y, dst, mask in DOORS:
        path = room_path(assets, src)
        if not path.is_file():
            errors.append(f"area {src}: missing {path.name}")
            continue
        data = json.loads(path.read_text())
        rooms[src] = data
        match = [tr for tr in data.get("transitions", [])
                 if tr.get("next_area") == dst and
                 abs(float(tr.get("x", -9999)) - x) <= 1.0 and
                 abs(float(tr.get("y", -9999)) - y) <= 1.0]
        if not match:
            errors.append(f"area {src}: no transition to {dst} at ({x:g},{y:g})")
            continue
        tr = match[0]
        if int(tr.get("pad_mask", -1)) != mask:
            errors.append(f"area {src}->{dst}: pad_mask "
                          f"{tr.get('pad_mask')} != {mask}")
        if src in TAKE_DOOR_AREAS:
            if tr.get("source") != "take_door":
                errors.append(f"area {src}->{dst}: source "
                              f"{tr.get('source')!r}, expected 'take_door'")
            if float(tr.get("half_w", 0)) != TAKE_DOOR_HALF or \
                    float(tr.get("half_h", 0)) != TAKE_DOOR_HALF:
                errors.append(f"area {src}->{dst}: box is not "
                              f"{TAKE_DOOR_HALF:g}x{TAKE_DOOR_HALF:g}")
            if int(tr.get("spawn_id", -1)) != 0:
                errors.append(f"area {src}->{dst}: spawn_id "
                              f"{tr.get('spawn_id')} != 0")
    for _src, _x, _y, dst, _mask in DOORS:
        if not room_path(assets, dst).is_file():
            errors.append(f"destination area {dst}: room document missing")
    return rooms


def run(binary: Path, assets: Path, area: int, x: float, y: float,
        frames: int, trace: Path, demo: int | None = None,
        boss_hooks: bool = True) -> list[dict[str, str]]:
    env = dict(os.environ,
               DC_AREA=str(area),
               DC_START_X=str(x),
               DC_START_Y=str(y),
               DC_START_ONCE="1",
               DC_CAMPAIGN="1",
               DC_RUN_FRAMES=str(frames),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1",
               DC_TRACE_CSV=str(trace))
    if boss_hooks:
        env["DC_BOSS_CLEAR"] = "1"
        env["DC_MVP_KEEP_CONTROL"] = "1"
    else:
        env.pop("DC_BOSS_CLEAR", None)
        env.pop("DC_MVP_KEEP_CONTROL", None)
    if demo is None:
        env.pop("DC_DEMO", None)
    else:
        env["DC_DEMO"] = str(demo)
    for key in ("DC_STATE", "DC_TITLE", "DC_RESUME", "DC_PASSWORD"):
        env.pop(key, None)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"up doors: area {area} run exited "
                         f"{proc.returncode}\n" + proc.stdout[-1200:])
    return list(csv.DictReader(trace.open()))


def area_sequence(rows: list[dict[str, str]]) -> list[int]:
    seq: list[int] = []
    for row in rows:
        area = int(row["area"])
        if not seq or seq[-1] != area:
            seq.append(area)
    return seq


def first_row_in(rows: list[dict[str, str]], area: int) -> dict[str, str] | None:
    return next((row for row in rows if int(row["area"]) == area), None)


def check_door(binary: Path, assets: Path, tmp: Path, rooms: dict[int, dict],
               src: int, x: float, y: float, dst: int,
               errors: list[str]) -> None:
    data = rooms.get(src)
    if data is None:
        return
    tr = next((t for t in data.get("transitions", [])
               if t.get("next_area") == dst and
               abs(float(t.get("x", -9999)) - x) <= 1.0 and
               abs(float(t.get("y", -9999)) - y) <= 1.0), None)
    if tr is None:
        return
    half_w = float(tr.get("half_w", 12.0)) + 10.0
    half_h = float(tr.get("half_h", 24.0)) + 10.0
    label = f"{src}->{dst} at ({x:g},{y:g})"

    # --- no input: the player stands on the door and nothing happens ---
    still = run(binary, assets, src, x, y, NEGATIVE_FRAMES,
                tmp / f"up_{src}_{dst}_still.csv")
    if len(still) != NEGATIVE_FRAMES:
        errors.append(f"{label}: still run wrote {len(still)} rows, "
                      f"expected {NEGATIVE_FRAMES}")
        return
    start = still[0]
    px, py = float(start["player_x"]), float(start["player_y"])
    if abs(px - x) > half_w or abs(py - y) > half_h:
        errors.append(f"{label}: player starts at ({px:g},{py:g}), outside "
                      f"the door box -- the negative run proves nothing")
    areas = sorted({int(row["area"]) for row in still})
    if areas != [src]:
        errors.append(f"{label}: area changed without up ({areas})")
    modes = sorted({int(row["mode"]) for row in still})
    if modes != [GAME_PLAYING]:
        errors.append(f"{label}: left GAME_PLAYING without up ({modes})")

    # --- tap up: the destination appears, but only after the press ---
    moved = run(binary, assets, src, x, y, POSITIVE_FRAMES,
                tmp / f"up_{src}_{dst}_up.csv", demo=41)
    if len(moved) != POSITIVE_FRAMES:
        errors.append(f"{label}: up run wrote {len(moved)} rows, "
                      f"expected {POSITIVE_FRAMES}")
        return
    if int(moved[0]["area"]) != src:
        errors.append(f"{label}: up run did not start in area {src}")
    early = {int(row["area"]) for row in moved
             if int(row["frame"]) < UP_FRAME}
    if early != {src}:
        errors.append(f"{label}: area changed before the up press ({early})")
    seq = area_sequence(moved)
    if dst not in seq:
        errors.append(f"{label}: up did not reach area {dst} ({seq})")
        return
    entry = first_row_in(moved, dst)
    dest = rooms.get(dst) or json.loads(room_path(assets, dst).read_text())
    world = dest.get("world") or {}
    world_w = float(world.get("width") or 256)
    world_h = float(world.get("height") or 256)
    if entry is not None:
        ex, ey = float(entry["player_x"]), float(entry["player_y"])
        if not (0.0 <= ex <= world_w and 0.0 <= ey <= world_h):
            errors.append(f"{label}: landed at ({ex:g},{ey:g}) outside the "
                          f"{world_w:g}x{world_h:g} destination room")
    modes_up = sorted({int(row["mode"]) for row in moved})
    if modes_up != [GAME_PLAYING]:
        errors.append(f"{label}: left GAME_PLAYING during the up run "
                      f"({modes_up})")


def check_no_phantom_boss(binary: Path, assets: Path, tmp: Path,
                          errors: list[str]) -> None:
    """The avenue's doors must work in a plain campaign run.

    $96 is the script/NPC actor, but the extractor types it "boss"; spawning
    it as one leaves boss_alive true, which skips every transition in the
    room. The runs above set DC_BOSS_CLEAR, so they cannot catch that. These
    two runs use no hooks at all: the avenue up-door and the library return
    door have to fire on their own.
    """
    rows = run(binary, assets, 4, 424, 428, 180,
               tmp / "up_4_46_plain.csv", demo=41, boss_hooks=False)
    if 46 not in area_sequence(rows):
        errors.append("area 4: the up-door is blocked by a phantom boss "
                      "without DC_BOSS_CLEAR")
    rows = run(binary, assets, 46, 8, 184, 60,
               tmp / "door_46_4_plain.csv", boss_hooks=False)
    if 4 not in area_sequence(rows):
        errors.append("area 46: the return door is blocked by a phantom boss "
                      "without DC_BOSS_CLEAR")


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("up doors: no binary (skip)")
        return 77
    if not (args.assets / "room_area4.json").is_file():
        print("up doors: no assets (skip)")
        return 77

    errors: list[str] = []
    rooms = check_data(args.assets, errors)

    tmp_ctx = tempfile.TemporaryDirectory(prefix="dc-updoors-")
    tmp = args.tmp or Path(tmp_ctx.name)
    tmp.mkdir(parents=True, exist_ok=True)

    for src, x, y, dst, _mask in DOORS:
        check_door(args.binary, args.assets, tmp, rooms, src, x, y, dst,
                   errors)
    check_no_phantom_boss(args.binary, args.assets, tmp, errors)

    if errors:
        print("up doors: FAIL")
        for error in errors:
            print("  - " + error)
        return 1
    print(f"up doors: PASS ({len(DOORS)} doors, pad_mask 8 honoured: "
          "4->46, 4->47, 4->48, 5->6, 6->7, 7->8; no proximity trigger; "
          "4->46 and 46->4 also fire without DC_BOSS_CLEAR)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
