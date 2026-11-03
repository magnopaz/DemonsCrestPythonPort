#!/usr/bin/env python3
"""End-to-end campaign playthrough check.

Drives the shipping binary through each campaign transition with deterministic
hooks and asserts the observed game-state sequence:

  title --NEW GAME--> Area 0 (playing)
  boss defeated --> GAME_CLEAR
  GAME_CLEAR --Enter--> overworld
  overworld stage select --Enter--> a real stage entry (playing)
  boss entry --defeat--> GAME_CLEAR
  overworld keep node --Enter--> GAME_ENDING

Hooks used: DC_TITLE, DC_AREA, DC_CAMPAIGN, DC_BOSS_DEFEATED, DC_STATE,
DC_DEMO (13/30/31), DC_OVERWORLD_X/Y, DC_PASSWORD.

Usage: python3 tools/check_playthrough.py [--binary PATH] [--assets DIR]
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
ALPHABET = "BCDFGHJKLMNPQRSTVWXY"  # 20 symbols: DC_PASSWORD_ALPHABET

GAME_TITLE, GAME_PLAYING, GAME_CLEAR = 0, 1, 3
GAME_OVERWORLD, GAME_ENDING = 5, 10


def encode_password(stages: int, max_hp: int, crests: int, form: int,
                    potions: int, scrolls: int, talismans: int) -> str:
    """Mirror of Game_PasswordEncode (payload + FNV-1a checksum, base-20)."""
    payload = ((stages & 0xFF) | ((max_hp & 0xF) << 8) | ((crests & 0x3F) << 12)
               | ((form & 0x7) << 18) | ((potions & 0x7) << 21)
               | ((scrolls & 0x7) << 24) | ((talismans & 0x1F) << 27))
    h = 2166136261
    for i in range(4):
        h ^= (payload >> (i * 8)) & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
    value = payload | ((h & 0xFF) << 32)
    out = []
    for _ in range(10):
        out.append(ALPHABET[value % len(ALPHABET)])
        value //= len(ALPHABET)
    return "".join(reversed(out))


def run(binary: Path, assets: Path, tmp: Path, name: str, env_extra: dict,
        frames: int) -> list[dict]:
    trace = tmp / f"{name}.csv"
    env = dict(os.environ,
               DC_RUN_FRAMES=str(frames),
               DC_NO_AUDIO="1",
               DC_NO_STORY="1",
               DC_TRACE_CSV=str(trace))
    for key in ("DC_STATE", "DC_DEMO", "DC_AREA", "DC_TITLE", "DC_CAMPAIGN",
                "DC_BOSS_DEFEATED", "DC_PASSWORD", "DC_OVERWORLD_X",
                "DC_OVERWORLD_Y", "DC_STAGE_SELECT", "DC_STAGE_INDEX"):
        env.pop(key, None)
    env.update({k: str(v) for k, v in env_extra.items()})
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=180)
    if proc.returncode != 0:
        raise SystemExit(f"{name}: exit {proc.returncode}: {proc.stdout[-200:]}")
    rows = list(csv.DictReader(trace.open(newline="")))
    if not rows:
        raise SystemExit(f"{name}: empty trace")
    return rows


def modes(rows: list[dict]) -> list[int]:
    return [int(r["mode"]) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path)
    args = ap.parse_args()
    binary, assets = args.binary.resolve(), args.assets.resolve()
    if not binary.is_file():
        print(f"check_playthrough: missing binary {binary}", file=sys.stderr)
        return 77

    steps = []

    def check(name: str, ok: bool, detail: str) -> None:
        steps.append({"step": name, "ok": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")

    tmp_parent = str(args.tmp) if args.tmp else os.environ.get("DC_CHECK_TMP_DIR")
    with tempfile.TemporaryDirectory(prefix="dc-play-", dir=tmp_parent) as td:
        tmp = Path(td)

        rows = run(binary, assets, tmp, "newgame", {"DC_TITLE": 1, "DC_DEMO": 13}, 120)
        m, areas = modes(rows), [int(r["area"]) for r in rows]
        check("title -> new game enters Area 0", GAME_PLAYING in m and 0 in areas,
              f"modes={sorted(set(m))} areas={sorted(set(areas))}")

        rows = run(binary, assets, tmp, "clear0",
                   {"DC_AREA": 0, "DC_CAMPAIGN": 1, "DC_BOSS_DEFEATED": 1}, 60)
        check("Area 0 boss defeat clears the area", GAME_CLEAR in modes(rows),
              f"modes={sorted(set(modes(rows)))}")

        rows = run(binary, assets, tmp, "overworld", {"DC_STATE": "clear", "DC_DEMO": 31}, 30)
        check("GAME_CLEAR Enter opens the overworld", GAME_OVERWORLD in modes(rows),
              f"modes={sorted(set(modes(rows)))}")

        rows = run(binary, assets, tmp, "travel", {"DC_STATE": "overworld", "DC_DEMO": 30}, 40)
        check("stage select travels to Area 16", int(rows[-1]["area"]) == 16 and
              GAME_PLAYING in modes(rows), f"last area {rows[-1]['area']}")

        rows = run(binary, assets, tmp, "clear49",
                   {"DC_AREA": 49, "DC_CAMPAIGN": 1, "DC_BOSS_DEFEATED": 1}, 60)
        check("Area 49 boss defeat clears the area", GAME_CLEAR in modes(rows),
              f"modes={sorted(set(modes(rows)))}")

        code = encode_password(0x0F, 8, 0x3F, 2, 5, 1, 0x1F)
        rows = run(binary, assets, tmp, "ending",
                   {"DC_PASSWORD": code, "DC_STATE": "overworld", "DC_DEMO": 31,
                    "DC_OVERWORLD_X": 224, "DC_OVERWORLD_Y": 160}, 40)
        check("overworld keep node opens the ending", GAME_ENDING in modes(rows),
              f"modes={sorted(set(modes(rows)))} (password {code})")

    failed = [s for s in steps if not s["ok"]]
    print(f"check_playthrough: {len(steps) - len(failed)}/{len(steps)} steps passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
