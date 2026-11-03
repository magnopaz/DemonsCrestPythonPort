#!/usr/bin/env python3
"""Restore extracted transitions that an over-eager note merge removed.

`merge_observed_doors.py --trust-notes` used to drop every extracted transition
whose target differed from the notes, which removed real side doors. This tool
re-reads the ROM transition table for each area (with the same row offset logic
as `extract.py`) and appends any extracted transition missing from the room
JSON, leaving the note/save doors untouched.

Usage:
  python tools/dc_extract/restore_transitions.py --rom "<rom>" \
      --rooms assets/generated
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import Rom  # noqa: E402


def row_index_for(rom: Rom, area: int, slot: int = 9) -> int:
    info = rom.area_info(area)
    for i, row in enumerate(info["grid"]):
        if slot in row:
            return i
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    args = ap.parse_args()

    rom = Rom(Path(args.rom))
    restored = 0
    for path in sorted(args.rooms.glob("room_area*.json")):
        data = json.loads(path.read_text())
        area = int(data.get("area_id", path.stem.split("area")[-1]))
        row_offset = row_index_for(rom, area) * 256
        have = {(int(t.get("next_area", -1)), t.get("x"), t.get("y"))
                for t in data.get("transitions", [])}
        added = []
        for tr in rom.area_transitions(area):
            ty = tr["y"] - row_offset
            if ty < 0:
                ty = tr["y"]
            key = (tr["next_area"], tr["x"], ty)
            if key in have:
                continue
            added.append({
                "next_area": tr["next_area"],
                "spawn_id": tr["spawn_id"],
                "pad_mask": tr["pad_mask"],
                "x": tr["x"],
                "y": ty,
                "half_w": max(12, tr["half_w"]),
                "half_h": max(16, tr["half_h"]),
                "type": tr["type"],
                "source": "restored",
            })
        if added:
            data.setdefault("transitions", []).extend(added)
            path.write_text(json.dumps(data))
            restored += len(added)
            print(f"area {area}: restored {len(added)} transition(s) "
                  f"{[(a['next_area'], a['x'], a['y']) for a in added]}")
    print(f"restored {restored} transition(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
