#!/usr/bin/env python3
"""Bake Ovnunu (temple boss, species $16) from its sheet.

The live temple-boss save (`lvl_V_poseidonia-temple-and-hidden-chamber_boss`)
has species $16/$17/$18; the room list incorrectly points at the NPC $96.
The three full eyeball/tentacle examples are on the y=295 row.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Ovnunu.gif"
GEN = ROOT / "assets" / "generated"
BOXES = [(25, 295, 61, 361), (65, 294, 100, 361), (105, 295, 142, 361)]


def main() -> int:
    im = Image.open(SRC).convert("RGB")
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    bg = Counter(small.getdata()).most_common(1)[0][0]
    frames = []
    for i, (x0, y0, x1, y1) in enumerate(BOXES):
        crop = im.crop((x0, y0, x1, y1)).convert("RGBA")
        px = crop.load()
        for y in range(crop.height):
            for x in range(crop.width):
                r, g, b, _a = px[x, y]
                if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= 30:
                    px[x, y] = (0, 0, 0, 0)
        bbox = crop.getbbox()
        if bbox is None:
            continue
        crop = crop.crop(bbox)
        tex = f"enemy_16_{i}.png"
        crop.save(GEN / tex)
        frames.append({
            "texture": tex,
            "anchor_x": crop.width // 2,
            "anchor_y": crop.height,
            "duration": 8,
            "width": crop.width,
            "height": crop.height,
        })
        print(f"  frame {i}: {crop.size}")
    path = GEN / "species_anim.json"
    anim = json.loads(path.read_text()) if path.is_file() else {"species": {}}
    anim.setdefault("species", {})["16"] = {
        "species": 0x16,
        "frames": frames,
        "states": {"0": list(range(len(frames)))},
        "default": 0,
        "source": "docs/sprites Ovnunu.gif (full eyeball examples)",
    }
    path.write_text(json.dumps(anim, indent=1))
    print(f"Ovnunu: {len(frames)} frames -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
