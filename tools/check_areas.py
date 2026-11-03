#!/usr/bin/env python3
"""Load every campaign area in the native build and validate the result.

For each `room_area<N>.json` the binary runs headless with `DC_AREA=N`, a fixed
frame budget and a trace CSV. The tool checks that the process exits cleanly,
emits the expected number of frames, keeps the player inside the room and does
not drop the player through the world. Results are printed as a table and
optionally written to JSON.

Usage:
  python3 tools/check_areas.py --binary tools/demonscrest-py --assets assets/generated
  python3 tools/check_areas.py --areas 0,1,2,3 --frames 90
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


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--areas", default="", help="comma-separated area ids")
    ap.add_argument("--frames", type=int, default=90)
    ap.add_argument("--json", type=Path, help="write the full report")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--tmp", type=Path,
                    help="scratch directory for trace CSVs (default: system temp; "
                         "set it when the game process may only write to a "
                         "specific tree)")
    return ap.parse_args()


def area_dirs(assets: Path) -> list[int]:
    return sorted(int(p.stem.split("room_area")[1]) for p in assets.glob("room_area*.json"))


def main() -> int:
    args = parse_args()
    binary = args.binary.resolve()
    assets = args.assets.resolve()
    if not binary.is_file():
        print(f"check_areas: missing binary {binary}", file=sys.stderr)
        return 77
    rooms = area_dirs(assets)
    if not rooms:
        print(f"check_areas: no room_area*.json under {assets}", file=sys.stderr)
        return 77
    areas = ([int(a, 0) for a in args.areas.split(",") if a.strip()]
             if args.areas else rooms)

    rows = []
    failures = 0
    tmp_parent = str(args.tmp) if args.tmp else os.environ.get("DC_CHECK_TMP_DIR")
    with tempfile.TemporaryDirectory(prefix="dc-areas-", dir=tmp_parent) as td:
        out = Path(td)
        for area in areas:
            room_path = assets / f"room_area{area}.json"
            if not room_path.is_file():
                rows.append({"area": area, "status": "missing-room"})
                failures += 1
                continue
            room = json.loads(room_path.read_text())
            world = room.get("world", {})
            trace = out / f"area{area}.csv"
            env = dict(os.environ,
                       DC_AREA=str(area),
                       DC_RUN_FRAMES=str(args.frames),
                       DC_NO_AUDIO="1",
                       DC_TRACE_CSV=str(trace))
            for key in ("DC_SAVE_PATH", "DC_SAVE_FORCE", "DC_RESUME",
                        "DC_DIALOGUE", "DC_STATE", "DC_DEMO",
                        "DC_START_X", "DC_START_Y", "DC_PASSWORD"):
                env.pop(key, None)
            status = "ok"
            detail = ""
            try:
                proc = subprocess.run([str(binary), "--assets", str(assets)],
                                      cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      timeout=args.timeout)
                if proc.returncode != 0:
                    status = "exit"
                    detail = f"exit {proc.returncode}: {proc.stdout.strip()[-80:]}"
            except subprocess.TimeoutExpired:
                status = "timeout"
                detail = f">{args.timeout:.0f}s"
            last = None
            if trace.is_file():
                with trace.open(newline="") as f:
                    data = list(csv.DictReader(f))
                if len(data) != args.frames:
                    status = "frames" if status == "ok" else status
                    detail = detail or f"{len(data)}/{args.frames} rows"
                if data:
                    last = data[-1]
            else:
                if status == "ok":
                    status = "no-trace"
            if last:
                try:
                    x = float(last["player_x"])
                    y = float(last["player_y"])
                except (KeyError, ValueError):
                    x = y = float("nan")
                w = float(world.get("width", 0))
                h = float(world.get("height", 0))
                if not (x == x and y == y):
                    status = "nan" if status == "ok" else status
                elif w and h and not (-32 <= x <= w + 32 and -64 <= y <= h + 32):
                    status = "outside" if status == "ok" else status
                    detail = detail or f"({x:.0f},{y:.0f}) vs {w:.0f}x{h:.0f}"
            rows.append({"area": area, "status": status,
                         "player": [last["player_x"], last["player_y"]] if last else None,
                         "detail": detail})
            if status != "ok":
                failures += 1

    for r in rows:
        if r["status"] != "ok":
            print(f"  area {r['area']:3d}: {r['status']:9s} {r.get('detail', '')}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"check_areas: {len(rows)} areas, " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "counts": counts}, indent=1))
        print(f"report: {args.json}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
