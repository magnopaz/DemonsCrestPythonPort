#!/usr/bin/env python3
"""Campaign completion smoke test: every stage entry that has a boss must clear.

For each room that spawns a boss the binary runs with `DC_CAMPAIGN=1`,
`DC_BOSS_DEFEATED=1` and a fixed frame budget. Success means the run reaches
`GameState::GAME_CLEAR` (mode 7 in the trace) without an exit error. Entries
without a boss are reported separately (they are traversal stages).

Usage:
  python3 tools/check_campaign.py
  python3 tools/check_campaign.py --areas 0,3,4 --frames 120 --json report.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAR_MODE = 3  # GameState::GAME_CLEAR


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--areas", default="", help="comma-separated area ids")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--tmp", type=Path, help="scratch dir for trace CSVs")
    ap.add_argument("--json", type=Path)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    binary = args.binary.resolve()
    assets = args.assets.resolve()
    if not binary.is_file():
        print(f"check_campaign: missing binary {binary}", file=sys.stderr)
        return 77

    entries = []
    campaign = assets / "campaign.json"
    if campaign.is_file():
        entries = json.loads(campaign.read_text()).get("stage_entries", [])
    rooms = {}
    for path in glob.glob(str(assets / "room_area*.json")):
        area = int(re.search(r"room_area(\d+)", path).group(1))
        rooms[area] = json.loads(Path(path).read_text())
    if args.areas.strip():
        areas = [int(a, 0) for a in args.areas.split(",") if a.strip()]
    else:
        areas = entries or sorted(rooms)

    tmp_parent = str(args.tmp) if args.tmp else os.environ.get("DC_CHECK_TMP_DIR")
    rows = []
    failures = 0
    with tempfile.TemporaryDirectory(prefix="dc-campaign-", dir=tmp_parent) as td:
        out = Path(td)
        for area in areas:
            doc = rooms.get(area)
            if doc is None:
                continue
            bosses = [o for o in doc.get("objects", []) if o.get("type") == "boss"]
            if not bosses:
                rows.append({"area": area, "status": "no-boss"})
                continue
            trace = out / f"a{area}.csv"
            env = dict(os.environ,
                       DC_AREA=str(area),
                       DC_CAMPAIGN="1",
                       DC_BOSS_DEFEATED="1",
                       DC_RUN_FRAMES=str(args.frames),
                       DC_NO_AUDIO="1",
                       DC_NO_STORY="1",
                       DC_TRACE_CSV=str(trace))
            for key in ("DC_STATE", "DC_DEMO", "DC_START_X", "DC_START_Y",
                        "DC_RESUME", "DC_STAGE_SELECT"):
                env.pop(key, None)
            status = "ok"
            detail = ""
            try:
                proc = subprocess.run([str(binary), "--assets", str(assets)],
                                      cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      timeout=90)
                if proc.returncode != 0:
                    status = "exit"
                    detail = proc.stdout.strip()[-80:]
            except subprocess.TimeoutExpired:
                status = "timeout"
            modes = []
            if trace.is_file():
                with trace.open(newline="") as f:
                    modes = [int(r["mode"]) for r in csv.DictReader(f)]
            cleared = CLEAR_MODE in modes
            if status == "ok" and not cleared:
                status = "no-clear"
                detail = f"modes={sorted(set(modes))}"
            rows.append({"area": area, "status": status,
                         "cleared": cleared, "detail": detail})
            if status not in ("ok", "no-boss"):
                failures += 1

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    for r in rows:
        if r["status"] not in ("ok", "no-boss"):
            print(f"  area {r['area']:3d}: {r['status']:8s} {r.get('detail', '')}")
    print("check_campaign: " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "counts": counts}, indent=1))
        print(f"report: {args.json}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
