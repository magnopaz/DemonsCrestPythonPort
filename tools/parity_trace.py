#!/usr/bin/env python3
"""Run the C reference build and the Python port on one deterministic script
and diff their player/object/projectile traces.

This is the parity gate used during the port: the two implementations are
driven with identical DC_* environment variables, and the CSVs must match
byte for byte for the whole run.

Usage:
  python3 tools/parity_trace.py --demo 15 --frames 600 --area 1
  python3 tools/parity_trace.py --demo 12 --frames 300 --area 1 \\
      --start-x 1850 --start-y 168 --env DC_CAMPAIGN=1 --env DC_BOSS_HP=1

Exit 0 when every trace matches.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_C_BINARY = ROOT.parent / "DemonsCrestNativePort" / "build" / "demonscrest"
DEFAULT_ASSETS = ROOT / "assets" / "generated"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--c-binary", type=Path, default=DEFAULT_C_BINARY)
    ap.add_argument("--py-binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    ap.add_argument("--demo", default="0")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--area", default="1")
    ap.add_argument("--start-x", default=None)
    ap.add_argument("--start-y", default=None)
    ap.add_argument("--env", action="append", default=[],
                    help="extra KEY=VALUE for both runs (repeatable)")
    return ap.parse_args()


def run(binary: Path, assets: Path, env: dict[str, str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(binary), "--assets", str(assets)]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=900)


def main() -> int:
    args = parse_args()
    if not args.c_binary.is_file():
        print(f"parity: skip (no C binary at {args.c_binary})")
        return 77
    if not (args.assets / "room_area1.json").is_file():
        print(f"parity: skip (no assets at {args.assets})")
        return 77

    with tempfile.TemporaryDirectory(prefix="dc-parity-") as td:
        tmp = Path(td)
        env = dict(os.environ)
        for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_BOSS_HP",
                    "DC_BOSS_STATUE", "DC_CAMPAIGN"):
            env.pop(key, None)
        env.update({
            "DC_AREA": args.area,
            "DC_RUN_FRAMES": str(args.frames),
            "DC_NO_AUDIO": "1",
            "DC_NO_SAVE": "1",
            "DC_NO_STORY": "1",
            "DC_DEMO": args.demo,
        })
        if args.start_x:
            env["DC_START_X"] = args.start_x
        if args.start_y:
            env["DC_START_Y"] = args.start_y
        for item in args.env:
            key, _, value = item.partition("=")
            env[key] = value

        outputs = {}
        for tag, binary in (("c", args.c_binary), ("py", args.py_binary)):
            target = tmp / tag
            target.mkdir()
            local = dict(env)
            local["DC_TRACE_CSV"] = str(target / "player.csv")
            local["DC_TRACE_OBJECTS"] = str(target / "objects.csv")
            local["DC_TRACE_PROJECTILES"] = str(target / "projectiles.csv")
            run(binary, args.assets, local, target)
            outputs[tag] = target

        ok = True
        for name in ("player.csv", "objects.csv", "projectiles.csv"):
            c_path = outputs["c"] / name
            p_path = outputs["py"] / name
            if not c_path.is_file() and not p_path.is_file():
                continue
            c_text = c_path.read_text().splitlines()
            p_text = p_path.read_text().splitlines()
            if c_text == p_text:
                print(f"{name}: {len(c_text) - 1} rows identical")
                continue
            ok = False
            for i, (a, b) in enumerate(zip(c_text, p_text)):
                if a != b:
                    print(f"{name}: first difference at line {i}\n  C  {a}\n  PY {b}")
                    break
            else:
                print(f"{name}: length differs C={len(c_text)} PY={len(p_text)}")
        print("PARITY OK" if ok else "PARITY MISMATCH")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
