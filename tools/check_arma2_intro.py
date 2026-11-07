#!/usr/bin/env python3
"""Assert the first-encounter boss dialogue (Arma 2, area 23).

The stage-IV take shows the Arma fight with an intro dialogue the first time
and without it on the second encounter.  The port models that with
``story_flags``, one bit per area, saved with the game: entering area 23 the
first time opens the Arma text block ("I AM ARMA..."), and any later visit goes
straight to the fight.

Three runs:

1. fresh state: the game must enter GAME_DIALOGUE and come back to GAME_PLAYING
   (4 pages auto-advanced every 20 frames);
2. ``DC_STORY_FLAGS`` with the area bit set: no dialogue at all;
3. ``DC_NO_STORY``: the demo guard wins, so timed demos never stall.

Usage:
  DISPLAY=:99 python3 tools/check_arma2_intro.py \
      [--binary tools/demonscrest-py] [--assets assets/generated]

Exit codes: 0 = pass, 1 = failure, 77 = binary/assets missing.
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

AREA = 23
FRAMES = 300
GAME_PLAYING = 1
GAME_DIALOGUE = 11

# Game-state column in the DC_TRACE_CSV row (no header):
# frame,x,y,vx,vy,state,camx,camy,hp,maxhp,area,form,gold,element,state
ROW_STATE = 14


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def run(binary: Path, assets: Path, trace: Path,
        extra: dict[str, str]) -> list[list[str]] | None:
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_RUN_FRAMES=str(FRAMES),
               DC_NO_AUDIO="1",
               DC_INTRO_FORCE="1",
               DC_DIALOGUE_AUTO="20",
               DC_TRACE_CSV=str(trace))
    # A save round-trip must keep the save enabled (DC_NO_SAVE wins over the
    # force flag in dcpy/game.py).
    if "DC_SAVE_PATH" not in extra:
        env["DC_NO_SAVE"] = "1"
    for key in ("DC_NO_STORY", "DC_STORY_FLAGS", "DC_STATE", "DC_TITLE",
                "DC_RESUME", "DC_DEMO", "DC_BOSS_CLEAR", "DC_BOSS_DEFEATED",
                "DC_KILL_AT", "DC_START_X", "DC_START_Y"):
        env.pop(key, None)
    env.update(extra)
    try:
        proc = subprocess.run(
            [str(binary), "--assets", str(assets)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        print("arma2 intro: timeout")
        return None
    if proc.returncode != 0:
        print(f"arma2 intro: exit {proc.returncode}\n{proc.stdout[-600:]}")
        return None
    if not trace.is_file():
        print("arma2 intro: no trace")
        return None
    return [row for row in csv.reader(trace.open(newline="")) if row]


def dialogue_frames(rows: list[list[str]]) -> list[int]:
    out = []
    for row in rows:
        try:
            if int(row[ROW_STATE]) == GAME_DIALOGUE:
                out.append(int(row[0]))
        except (IndexError, ValueError):
            continue
    return out


def main() -> int:
    args = parse_args()
    binary = args.binary.resolve()
    assets = args.assets.resolve()
    if not binary.is_file() or not assets.is_dir():
        print("arma2 intro: skip (binary/assets missing)")
        return 77

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dc-arma2-intro-",
                                     dir=str(args.tmp) if args.tmp else None) as td:
        td = Path(td)

        rows = run(binary, assets, td / "fresh.csv", {})
        if rows is None:
            return 1
        dial = dialogue_frames(rows)
        if not dial:
            errors.append("fresh area 23 never entered GAME_DIALOGUE")
        elif dial[0] > 10:
            errors.append(f"dialogue started at frame {dial[0]}, expected <= 10")
        if dial and int(rows[-1][ROW_STATE]) != GAME_PLAYING:
            errors.append(
                f"after the dialogue the state is {rows[-1][ROW_STATE]}, "
                f"expected {GAME_PLAYING}")
        # Four pages at 20 frames each: the block must last longer than one page
        # but not hang the fight.
        if dial and not (40 <= len(dial) <= 200):
            errors.append(f"dialogue lasted {len(dial)} frames, expected 40..200")

        rows = run(binary, assets, td / "seen.csv",
                   {"DC_STORY_FLAGS": str(1 << AREA)})
        if rows is None:
            return 1
        if dialogue_frames(rows):
            errors.append("area 23 replayed the intro with the story bit set")

        rows = run(binary, assets, td / "nostory.csv", {"DC_NO_STORY": "1"})
        if rows is None:
            return 1
        if dialogue_frames(rows):
            errors.append("DC_NO_STORY did not suppress the intro")

        # The flag lives in the save: write it, read it back, and the next
        # session must not replay the intro.
        save_path = td / "save.json"
        save_env = {"DC_CAMPAIGN": "1", "DC_SAVE_FORCE": "1",
                    "DC_SAVE_PATH": str(save_path)}
        rows = run(binary, assets, td / "save.csv", save_env)
        if rows is None:
            return 1
        if not dialogue_frames(rows):
            errors.append("save run: the intro did not play")
        try:
            saved = json.loads(save_path.read_text())
        except (OSError, ValueError) as exc:
            errors.append(f"save file was not written: {exc}")
            saved = {}
        if not (int(saved.get("story_flags", 0)) & (1 << AREA)):
            errors.append("story_flags was not saved with area 23's bit")
        rows = run(binary, assets, td / "resume.csv",
                   {**save_env, "DC_RESUME": "1"})
        if rows is None:
            return 1
        if dialogue_frames(rows):
            errors.append("resuming the save replayed the intro")

    if errors:
        print("arma2 intro: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    print("arma2 intro: PASS (area 23 shows the Arma text once; "
          "story bit and DC_NO_STORY suppress it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
