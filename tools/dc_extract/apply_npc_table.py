#!/usr/bin/env python3
"""Place the talkable city NPCs that a bare ROM extraction does not produce.

The retail room list has no `npc` entry for the town: the NPC is spawned by the
area's script, not by `$81:C874`. Without it `Game_TryTalk()` has nothing to
talk to and the town conversation (and the regression's NPC check) never opens.

Coordinates are the spawn point's neighbourhood: `Game_TryTalk()` requires the
player within 30 px horizontally and 36 px vertically, and the town room's
player spawn is (32, 668), so the NPC sits at (52, 668).

Usage:
  python3 tools/dc_extract/apply_npc_table.py --rooms assets/generated
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# area -> (species, x, y, flags)
NPCS = {
    8: (0x96, 52, 668, 0),  # ruined city, town greeter
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=ROOT / "assets" / "generated")
    args = ap.parse_args()
    for area, (species, x, y, flags) in NPCS.items():
        path = args.rooms / f"room_area{area}.json"
        if not path.is_file():
            print(f"area {area}: missing {path.name}, skipped")
            continue
        doc = json.loads(path.read_text())
        objects = doc.setdefault("objects", [])
        entry = {"type": "npc", "species": species, "flags": flags, "x": x, "y": y}
        replaced = False
        for i, obj in enumerate(objects):
            if obj.get("type") == "npc" and obj.get("species") == species:
                objects[i] = entry
                replaced = True
                break
        if not replaced:
            objects.insert(0, entry)
        path.write_text(json.dumps(doc, indent=1))
        print(f"area {area}: npc {species:#04x} at {x},{y} "
              f"({'replaced' if replaced else 'added'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
