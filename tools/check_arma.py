#!/usr/bin/env python3
"""Assert Arma -> Earth Crest -> area 94 (the world map).

What used to be wrong and is easy to regress:

  * area 3's boss sat at (856, 1180) in the room data - 1024 px below the
    fight, inside solid rock.  The live save (`arma_boss.sav`, $008D = 6,
    camera y = 0) has him at (856, 151);
  * `Game_CompleteArea(3)` awarded CREST_TIME and froze the room with the
    clear banner;
  * the ROM's gate byte for area 3 is $F0, the "back to the map" marker, so
    the extractor dropped the gate and the room had no exit;
  * the port's Arma did not use the ROM's state machine, so he never dived
    into the player's line (the only window where a grounded shot can hit).

The check runs one take: stand under the post and shoot (DC_DEMO=16), walk
right once the boss is gone, with the crest text auto-advanced.  Exit 77 when
the binary or the assets are missing.
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

AREA = 3
MAP_AREA = 94
START_X = 845
START_Y = 170
BOSS_X, BOSS_Y = 856, 151
HOVER_MAX_Y = 84.0          # the post minus the ROM's 81 px hover height


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def run(binary: Path, assets: Path, out: Path, frames: int, extra: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    objs = out / "objects.csv"
    player = out / "player.csv"
    fade = out / "fade.csv"
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_CAMPAIGN="1",
               DC_START_X=str(START_X),
               DC_START_Y=str(START_Y),
               DC_RUN_FRAMES=str(frames),
               DC_TRACE_OBJECTS=str(objs),
               DC_TRACE_CSV=str(player),
               DC_TRACE_FADE=str(fade),
               DC_DEBUG_CREST="1",
               DC_NO_AUDIO="1",
               DC_NO_SAVE="1")
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_BOSS_HP", "DC_DIALOGUE_AUTO",
                "DC_NO_STORY", "DC_BOSS_DEFEATED", "DC_MVP_KEEP_CONTROL"):
        env.pop(key, None)
    env.update(extra)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=600)
    if proc.returncode != 0:
        raise SystemExit(f"arma: binary exited {proc.returncode}\n"
                         + proc.stdout[-1500:])
    return {"objects": list(csv.DictReader(objs.open(newline=""))),
            "player": list(csv.DictReader(player.open(newline=""))),
            "fade": list(csv.DictReader(fade.open(newline="")))
                    if fade.is_file() else [],
            "log": proc.stdout}


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("arma: skip (no binary)")
        return 77
    room = args.assets / f"room_area{AREA}.json"
    if not room.is_file():
        print("arma: skip (no assets)")
        return 77

    doc = json.loads(room.read_text())
    gate = int(doc.get("gate_next_area", -1))
    marker = int(doc.get("gate_marker", 0))
    if gate != MAP_AREA or marker != 0xF0:
        raise SystemExit(f"arma: area 3 gate is {gate} (marker {marker:#04x}),"
                         f" expected {MAP_AREA} from $F0")

    with tempfile.TemporaryDirectory(prefix="dc-arma-") as td:
        tmp = Path(td)
        take = run(args.binary, args.assets, tmp, 1400,
                   {"DC_DEMO": "16", "DC_BOSS_HP": "3",
                    "DC_DIALOGUE_AUTO": "25"})

    boss = [r for r in take["objects"] if r.get("species") == str(0xA5)]
    if not boss:
        raise SystemExit("arma: species a5 never spawned")
    first = boss[0]
    if first["type"] != "6":
        raise SystemExit(f"arma: species a5 has type {first['type']}, expected 6")
    if abs(float(first["x"]) - BOSS_X) > 1 or abs(float(first["y"]) - BOSS_Y) > 1:
        raise SystemExit(f"arma: boss at {first['x']},{first['y']}, expected "
                         f"{BOSS_X},{BOSS_Y}")

    states = {r["state"] for r in boss}
    for needed, what in (("6", "volley"), ("8", "dive"), ("10", "fall"),
                         ("12", "land")):
        if needed not in states:
            raise SystemExit(f"arma: the {what} state ({needed}) never ran "
                             f"(states seen: {sorted(states)})")

    lowest = min(float(r["y"]) for r in boss)
    if lowest > HOVER_MAX_Y:
        raise SystemExit(f"arma: he never reached the post (lowest y {lowest})")

    hps = [int(r["hp"]) for r in boss]
    if min(hps) > 0:
        raise SystemExit(f"arma: hp never reached 0 (saw {sorted(set(hps))})")

    fled = [r for r in boss if r["state"] == "24"]
    if not fled:
        raise SystemExit("arma: the flee state (24) never ran")

    if "granted crest 1" not in take["log"]:
        raise SystemExit("arma: the Earth Crest (crest 1) was never granted")

    areas = [r["area"] for r in take["player"]]
    if str(MAP_AREA) not in areas:
        raise SystemExit(f"arma: the map room never loaded (areas {sorted(set(areas))})")
    fade_areas = {r["area"] for r in take["fade"]}
    if str(MAP_AREA) not in fade_areas:
        raise SystemExit(f"arma: no fade into area {MAP_AREA} "
                         f"(fade areas {sorted(fade_areas)})")
    last = take["player"][-1]
    # The map runs in GAME_OVERWORLD (5): area 94 sits behind the Mode 7 view.
    if last["mode"] != "5":
        raise SystemExit(f"arma: the map did not take over (mode {last['mode']})")

    print("arma: PASS (spawn, states 6/8/10/12, fight to 0 HP, flee,"
          " Earth Crest, fade to area 94)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
