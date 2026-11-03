#!/usr/bin/env python3
"""Patch a room's boss object species after a verified save/probe mapping.

The ROM area object list is not reliable for every boss room (area 52 listed
the town-NPC species $96 for the Holothurion fight; the live save has $6F).
This tool changes only boss objects, leaving placements/collision untouched.

Usage:
  python tools/dc_extract/fix_room_boss_species.py \
    --room assets/generated/room_area52.json --old 150 --new 111
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--room", type=Path, required=True)
    ap.add_argument("--old", type=int, required=True)
    ap.add_argument("--new", type=int, required=True)
    args = ap.parse_args()

    data = json.loads(args.room.read_text())
    changed = 0
    for obj in data.get("objects", []):
        if obj.get("type") in ("boss", 6) and obj.get("species") == args.old:
            obj["species"] = args.new
            changed += 1
    if not changed:
        raise SystemExit(f"no boss species {args.old} in {args.room}")
    args.room.write_text(json.dumps(data, indent=1))
    print(f"{args.room}: {changed} boss object(s) {args.old} -> {args.new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
