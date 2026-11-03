#!/usr/bin/env python3
"""Assert the cemetery Hippogriff fight: spawn, stone phase, gate.

Three things used to be silently wrong and are easy to regress:

  * species `$09` was typed "exit" by the extractor, so the object at
    (1920, 168) never spawned a boss;
  * the stone state woke on the next frame unless `DC_BOSS_STATUE` was set,
    because its wake test treated the test hook as a wake condition;
  * the boss death ran Game_CompleteArea(1), which awarded the Air Crest and
    froze the room instead of opening the gate to area 2.

The check runs the binary twice: once with the statue hook to measure how long
state 6 really lasts, and once with DC_BOSS_HP=1 to kill him and walk through
the gate. Exit 77 when the binary/assets are missing.
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

AREA = 1
START_X = 1850
START_Y = 168
BOSS_X, BOSS_Y = 1920, 168


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
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_START_X=str(START_X),
               DC_START_Y=str(START_Y),
               DC_RUN_FRAMES=str(frames),
               DC_TRACE_OBJECTS=str(objs),
               DC_TRACE_CSV=str(player),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_NO_SAVE="1")
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_BOSS_HP",
                "DC_BOSS_STATUE", "DC_CAMPAIGN", "DC_MVP_KEEP_CONTROL"):
        env.pop(key, None)
    env.update(extra)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(f"hippogriff: binary exited {proc.returncode}\n"
                         + proc.stdout[-1200:])
    return {"objects": list(csv.DictReader(objs.open(newline=""))),
            "player": list(csv.DictReader(player.open(newline="")))}


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print("hippogriff: skip (no binary)")
        return 77
    if not (args.assets / "room_area1.json").is_file():
        print("hippogriff: skip (no assets)")
        return 77

    with tempfile.TemporaryDirectory(prefix="dc-hippogriff-",
                                     dir=str(args.tmp) if args.tmp else None) as td:
        tmp = Path(td)

        # -- run 1: the boss exists and the stone phase lasts --------------
        a = run(args.binary, args.assets, tmp / "a", 420,
                {"DC_DEMO": "12", "DC_BOSS_STATUE": "1"})
        boss = [r for r in a["objects"] if r.get("species") == "9"]
        if not boss:
            raise SystemExit("hippogriff: species 09 never spawned")
        first = boss[0]
        if first["type"] != "6":
            raise SystemExit(f"hippogriff: species 09 has type {first['type']},"
                             " expected 6 (OBJECT_BOSS)")
        if (abs(float(first["x"]) - BOSS_X) > 1 or
                abs(float(first["y"]) - BOSS_Y) > 1):
            raise SystemExit(f"hippogriff: boss at {first['x']},{first['y']},"
                             f" expected {BOSS_X},{BOSS_Y}")

        stone = [int(r["frame"]) for r in boss if r["state"] == "6"]
        if not stone:
            raise SystemExit("hippogriff: the stone state never happened")
        longest = run_len = 1
        for prev, cur in zip(stone, stone[1:]):
            run_len = run_len + 1 if cur == prev + 1 else 1
            longest = max(longest, run_len)
        if longest < 120:
            raise SystemExit(
                f"hippogriff: stone phase lasted only {longest} frames -"
                " the statue wakes itself")

        # -- run 2: killing him opens the gate to area 2 -------------------
        b = run(args.binary, args.assets, tmp / "b", 300,
                {"DC_DEMO": "12", "DC_CAMPAIGN": "1", "DC_BOSS_HP": "1"})
        boss_b = [r for r in b["objects"] if r.get("species") == "9"]
        if not boss_b or int(boss_b[-1]["frame"]) > 200:
            raise SystemExit("hippogriff: the boss survived a 1 HP hit")
        areas = [r["area"] for r in b["player"]]
        if "2" not in areas:
            raise SystemExit(
                "hippogriff: the area never advanced to 2 after the kill"
                f" (areas seen: {sorted(set(areas))})")
        if b["player"][-1]["mode"] != "1":
            raise SystemExit("hippogriff: the game did not keep playing after"
                             f" the kill (mode {b['player'][-1]['mode']})")

    print("hippogriff: PASS (spawn, %d-frame stone phase, gate to area 2)"
          % longest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
