#!/usr/bin/env python3
"""Identify which extracted room an oracle frame belongs to.

The guest builds BG1/BG2 from the ROM block tables the extractor baked into
`room_area<N>.json`, so the live tilemap can be matched against the ROM's
256-screen table (`$8F+set:$8000 + screen*128`).  `room_match` does that with a
row-vote torus scan: it tolerates a screen boundary that falls inside the 64x32
VRAM window (the guest rewrites columns while the camera scrolls) and reports
32/32 rows as an exact match.  Blank/filler screens are excluded so they cannot
win a tie.

Some areas are byte-identical in the ROM — they share both the info block at
`$81:A291` and the grid block at `$81:A6D8` (1/73, 0/72, 30/71, 8/65, 13/74,
9/64, 46/47/48/52-58, …).  No content signal can separate those, so the tie is
reported in `tied_areas`.  Pass `--hint` (the loader id from WRAM `$008D`
divided by two, see `probe_save_room.py`) to pick the hinted member.

Usage:
  python3 tools/oracle/identify_area.py --capture captures/rooms/cem
  python3 tools/oracle/identify_area.py --dir captures/rooms --json captures/areas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "oracle"))

import room_match  # noqa: E402

MIN_MATCH = 0.90


def hint_of(capture_dir: Path) -> int | None:
    meta = capture_dir / "meta.json"
    if not meta.is_file():
        return None
    try:
        doc = json.loads(meta.read_text())
    except json.JSONDecodeError:
        return None
    stage_id = doc.get("stage_id_8d")
    if isinstance(stage_id, int) and stage_id % 2 == 0:
        return stage_id // 2
    return doc.get("area_hint")


def identify(capture_dir: Path, rom, rows_index, screen_areas,
             hint: int | None = None) -> dict:
    r = room_match.identify_dir(capture_dir, rom, rows_index, screen_areas)
    ranked = r["ranked"]
    if not ranked:
        return {"capture": str(capture_dir), "frame": None, "area": None,
                "score": 0.0, "runners_up": [], "tied_areas": [], "method": "none",
                "screen": [], "layer": None, "hint": hint, "hint_matched": False}
    area, score, detail = ranked[0]
    method = "bg1"
    if hint is not None:
        hit = next(((a, v) for _, a, v in ranked if a == hint), None)
        if hit is not None:
            area, detail = hint, hit[1]
            score = detail["score"]
            method = "bg1+hint"
    tied = sorted(a for s, a, _ in ranked if abs(s - score) < 1e-9)
    return {"capture": str(capture_dir), "frame": detail.get("frame"),
            "area": area, "score": round(score, 3), "method": method,
            "screen": list(detail.get("screen", ())), "layer": detail.get("layer"),
            "tied_areas": tied,
            "runners_up": [(a, round(s, 3)) for s, a, _ in ranked
                           if a not in tied][:3],
            "hint": hint,
            "hint_matched": hint is not None and hint == area}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path)
    ap.add_argument("--dir", type=Path, help="parent directory of capture dirs")
    ap.add_argument("--rooms", type=Path, default=ROOT / "assets" / "generated",
                    help="unused; kept for CLI compatibility")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--min-match", type=float, default=MIN_MATCH)
    ap.add_argument("--hint", type=int,
                    help="expected area (WRAM $008D / 2) to break ROM-duplicate ties")
    args = ap.parse_args()

    rom = room_match.load_rom()
    rows_index = room_match.build_screen_rows(rom)
    screen_areas = room_match.build_screen_to_areas(rom)

    dirs = [args.capture] if args.capture else sorted(
        p for p in args.dir.iterdir() if p.is_dir() and list(p.glob("f*.vram.bin")))
    results = []
    for d in dirs:
        hint = args.hint if args.hint is not None else hint_of(d)
        r = identify(d, rom, rows_index, screen_areas, hint)
        results.append(r)
        print(f"{d.name:32s} area={r['area']} score={r['score']} "
              f"screen={r['screen']} ties={r['tied_areas'][:8]} hint={r['hint']} "
              f"runners_up={r['runners_up']}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())