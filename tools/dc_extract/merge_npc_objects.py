#!/usr/bin/env python3
"""Add talkable NPC placements from probe dumps into room JSONs.

The room extractor only records the area's object-list entries; scripted NPCs
(seen live in save probes, e.g. species $96 in the city) are missing. This tool
adds them at their probed positions so the port can talk to them.

Usage:
  python tools/dc_extract/merge_npc_objects.py --probe-root <...>/oracle_probe \
      --saves 0ba --rooms assets/generated
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NPC_SPECIES = {0x96}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe-root", type=Path, required=True)
    ap.add_argument("--saves", required=True)
    ap.add_argument("--rooms", type=Path, required=True)
    ap.add_argument("--ground-y", type=float, default=None,
                    help="force the NPC's Y (the extracted room may be shorter)")
    ap.add_argument("--x", type=float, default=None,
                    help="force the NPC's X (for demo placement)")
    ap.add_argument("--clamp", action="store_true",
                    help="clamp X into the room and optionally snap Y")
    args = ap.parse_args()

    for tag in [s.strip() for s in args.saves.split(",") if s.strip()]:
        src = args.probe_root / f"save{tag}"
        info_path = src / "info.json"
        if not info_path.is_file():
            print(f"skip save{tag}: no probe")
            continue
        info = json.loads(info_path.read_text())
        room = args.rooms / f"room_area{info['area']}.json"
        if not room.is_file():
            print(f"skip save{tag}: no {room.name}")
            continue
        data = json.loads(room.read_text())
        objects = data.setdefault("objects", [])
        added = 0
        for ent in info.get("species", []):
            species = int(ent["species"])
            if species not in NPC_SPECIES:
                continue
            if any(o.get("type") == "npc" and
                   int(o.get("species", 0)) == species for o in objects):
                continue
            x = round(ent["x"])
            y = round(ent["y"])
            if args.clamp:
                width = data.get("world", {}).get("width", 256)
                x = max(24, min(int(width) - 24, x))
            if args.x is not None:
                x = round(args.x)
            if args.ground_y is not None:
                y = round(args.ground_y)
            objects.append({"type": "npc", "species": species, "flags": 0,
                            "x": x, "y": y})
            added += 1
        if added:
            room.write_text(json.dumps(data))
        print(f"save{tag}: area {info['area']} +{added} npc "
              f"(now {len(objects)} objects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
