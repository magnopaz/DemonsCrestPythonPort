#!/usr/bin/env python3
"""Capture one oracle frame per identified area and update the BG2 manifest.

`tools/oracle/map_saves_to_areas.py` writes `captures/save_to_area.json`, which
pairs every save state with the extracted room its BG1 matches.  This tool turns
that mapping into per-area captures (`captures/area<N>/fNNNNNN.*`) and rewrites
`tools/dc_extract/bg2_captures.json`, so `extract.py` can bake a real backdrop
for each area instead of the transparent placeholder.

Only areas whose mapping score clears `--min-score` are captured: a wrong area
would paint the wrong backdrop over a room, which is worse than a black one.

Usage:
  python3 tools/oracle/bake_area_captures.py --min-score 0.99 --jobs 2
  python3 tools/oracle/bake_area_captures.py --areas 1,2,48 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

MANIFEST = ROOT / "tools" / "dc_extract" / "bg2_captures.json"
MAPPING = ROOT / "captures" / "save_to_area.json"
SAVES = ROOT.parent / "DemonsCrestSNESRecomp" / "build-trace" / "saves"

# Prefer a settled, decorated room over a transitional state, and a perfect
# mapping over a partial one.
SKIP = ("before_door", "after_door", "just_after_crossing", "boss_dead",
        "cutscene", "_talk", "menu", "widescreen", "initial_cutscene",
        "normal_ending", "persecution", "ending")


def rank(row: dict) -> tuple:
    name = row["save"]
    skip = any(s in name for s in SKIP)
    return (not skip, row.get("score", 0.0), row.get("method") == "stage_id+bg1",
            -len(name))


def pick_per_area(rows: list[dict], min_score: float) -> dict[int, dict]:
    best: dict[int, dict] = {}
    for row in rows:
        area = row.get("area")
        if area is None or row.get("score", 0.0) < min_score:
            continue
        if area not in best or rank(row) > rank(best[area]):
            best[area] = row
    return best


def capture(area: int, save: Path, out: Path, port: int) -> int | None:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).parent / "capture_area_frame.py"),
           "--save", str(save), "--out", str(out), "--offsets", "45",
           "--port", str(port)]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"area {area}: capture failed: {proc.stderr.strip()[-200:]}")
        return None
    meta = out / "capture.json"
    if not meta.is_file():
        print(f"area {area}: capture produced no capture.json")
        return None
    frames = json.loads(meta.read_text()).get("frames") or []
    return frames[-1] if frames else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mapping", type=Path, default=MAPPING)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--saves", type=Path, default=SAVES)
    ap.add_argument("--out-root", type=Path, default=ROOT / "captures")
    ap.add_argument("--min-score", type=float, default=0.99)
    ap.add_argument("--areas", default="", help="comma-separated area ids to limit to")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--port", type=int, default=5200)
    args = ap.parse_args()

    rows = json.loads(args.mapping.read_text())
    chosen = pick_per_area(rows, args.min_score)
    if args.areas:
        wanted = {int(a) for a in args.areas.split(",") if a.strip()}
        chosen = {a: r for a, r in chosen.items() if a in wanted}
    if args.limit:
        chosen = dict(sorted(chosen.items())[:args.limit])

    manifest = json.loads(args.manifest.read_text()) if args.manifest.is_file() else {"areas": {}}
    areas = manifest.setdefault("areas", {})
    done = 0
    for area, row in sorted(chosen.items()):
        save = args.saves / row["save"]
        out = args.out_root / f"area{area}"
        print(f"area {area:3d} <- {row['save']:56s} score={row['score']:.3f} "
              f"method={row['method']}")
        if args.dry_run:
            continue
        if not save.is_file():
            print(f"  missing save {save}")
            continue
        frame = capture(area, save, out, args.port + done)
        if frame is None:
            continue
        areas[str(area)] = {
            "dir": str(out.relative_to(ROOT)),
            "frame": frame,
            "note": f"auto: {row['save']} (score {row['score']:.3f}, {row['method']})",
        }
        done += 1
        # Write after every success so a long run is resumable.
        args.manifest.write_text(json.dumps(manifest, indent=1))
    if not args.dry_run:
        print(f"{done} area captures written; manifest now lists {len(areas)} areas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
