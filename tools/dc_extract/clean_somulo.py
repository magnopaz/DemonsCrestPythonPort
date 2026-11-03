#!/usr/bin/env python3
"""Clean the native Somulo reference and place it on the floor.

The recording reference has two purple background pillars baked in at columns
144-146 and 152-154.  Those columns are not part of the body (every column to
their left ends at x=143 before the tail/ground starts), so they can be cleared
without touching the sprite.  The frame was also anchored at y=70, which pushed
most of the 174 px body below the floor; the native pose is re-anchored at the
bottom centre.

Run after regenerating the capture:
  python tools/dc_extract/clean_somulo.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/somulo_native_reference.png"
GEN = ROOT / "assets/generated"
TEX = "enemy_33_native.png"
BAR_COLUMNS = ((144, 147), (152, 155))


def main() -> int:
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    for x0, x1 in BAR_COLUMNS:
        for y in range(im.height):
            for x in range(x0, min(x1, im.width)):
                px[x, y] = (0, 0, 0, 0)
    im.save(GEN / TEX)

    path = GEN / "species_anim.json"
    anim = json.loads(path.read_text())
    frame = anim["species"]["33"]["frames"][3]
    if frame.get("texture") != TEX:
        raise SystemExit(f"unexpected Somulo native frame: {frame}")
    frame["anchor_x"] = im.width // 2
    frame["anchor_y"] = im.height
    frame["width"] = im.width
    frame["height"] = im.height
    path.write_text(json.dumps(anim, indent=1))
    print(f"Somulo: cleared {len(BAR_COLUMNS)} pillar columns, "
          f"anchor=({frame['anchor_x']},{frame['anchor_y']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
