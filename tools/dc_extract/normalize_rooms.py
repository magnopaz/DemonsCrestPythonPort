#!/usr/bin/env python3
"""Make every room's BG1 tilemap agree with the room's own world box.

A room's playable area is `world` (used by collision, spawns and every entity),
while BG1 is drawn from tile row 0.  If the tilemap is taller than the world,
every tile lands lower on screen than the collision grid says it does, and the
whole scene reads as "the characters are floating above the floor".

That is exactly what happened to area 0 (the Somulo arena): its BG1 had 35 rows
(280 px) against a 256 px world, and the extra three 8 px rows sat at the top, so
the floor art was drawn 24 px below the ground the player stood on.  Cropping
those rows put the player's feet exactly on the floor strip again (both at screen
y=176).

Rows are removed from the top, which is where the surplus sat in the one room
that hit this.  Every correction is printed, so a room whose surplus is really at
the bottom shows up in the log instead of being silently shifted.

Usage:
  python3 tools/dc_extract/normalize_rooms.py --rooms assets/generated
  python3 tools/dc_extract/normalize_rooms.py --rooms assets/generated --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fixed = 0
    for path in sorted(args.rooms.glob("room_area*.json")):
        doc = json.loads(path.read_text())
        world = doc.get("world") or {}
        layers = doc.get("bg") or []
        bg1 = next((b for b in layers if b.get("name") == "bg1"), None)
        if not bg1 or not world.get("height"):
            continue
        map_w = bg1["map_width"] * 8
        map_h = bg1["map_height"] * 8
        if map_w != world.get("width"):
            print(f"{path.name}: bg1 width {map_w} != world {world.get('width')} (not touched)")
            continue
        if map_h <= world["height"]:
            continue
        drop = world["height"] // 8
        print(f"area {doc.get('area_id')}: bg1 {map_h}px tall vs world "
              f"{world['height']}px — dropping {bg1['map_height'] - drop} top rows")
        if args.dry_run:
            continue
        bg1["tilemap"] = bg1["tilemap"][(bg1["map_height"] - drop) * bg1["map_width"]:]
        bg1["map_height"] = drop
        path.write_text(json.dumps(doc, indent=1))
        fixed += 1

    print(f"normalize_rooms: {fixed} room(s) trimmed"
          + (" (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
