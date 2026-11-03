#!/usr/bin/env python3
"""Install a community full-stage map as a room backdrop.

When a room's ROM tilemap/CHR is unavailable or demonstrably wrong (area 2 is
the current case), the sprite plan allows using a full-stage map as a parallax
image layer. This tool installs it reproducibly and disables the corrupt BG
tile layers while leaving collision and object data untouched.

Usage:
  python tools/dc_extract/install_full_map_backdrop.py \
    --area 2 \
    --map "docs/FullMaps/images/demons-crest-murkland-cemetery-snes-map.webp" \
    --parallax 1.0 --y -70
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--area", type=int, required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--room", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--parallax", type=float, default=1.0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--keep-layers", action="store_true",
                    help="do not replace the room's BG tile layers")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    room_path = args.room or args.out / f"room_area{args.area}.json"
    if not room_path.is_file():
        raise SystemExit(f"install_full_map_backdrop: missing {room_path}")
    if not args.map.is_file():
        raise SystemExit(f"install_full_map_backdrop: missing {args.map}")

    with Image.open(args.map) as image:
        image = image.convert("RGB")
        target = args.out / f"bg_backdrop_area{args.area}.png"
        image.save(target)
        print(f"backdrop {args.area}: {image.size} -> {target}")

    room = json.loads(room_path.read_text())
    if not args.keep_layers:
        # Tile 0 in the baked BG atlases is fully transparent. A one-cell
        # transparent layer satisfies Level_Load while letting the image show.
        room["bg"] = [
            {"name": "bg2", "map_width": 1, "map_height": 1,
             "scroll_x": 0, "scroll_y": 0, "tilemap": [0]},
            {"name": "bg1", "map_width": 1, "map_height": 1,
             "scroll_x": 0, "scroll_y": 0, "tilemap": [0]},
        ]
    room["backdrop_parallax"] = args.parallax
    room["backdrop_y"] = args.y
    room_path.write_text(json.dumps(room, indent=1))
    print(f"room {room_path}: BG layers hidden={not args.keep_layers}, "
          f"parallax={args.parallax}, y={args.y}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
