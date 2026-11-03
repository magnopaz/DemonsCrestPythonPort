#!/usr/bin/env python3
"""Bake Scula ($7B/$7C) from the labelled sheet.

The live object pool of `lvl_III_dark-forest-scula-cave_boss` contains
species $7B and $7C at the same arena position (the fight is two enemies that
can be killed in any order); $7F is an effect/part. The sheet has several
full-body rows; use the three clean walking bodies from the row at y=265.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Scula.gif"
GEN = ROOT / "assets/generated"

# Full walking bodies in the row y=265..336 for $7B; the second enemy uses
# the hovering row so the two sheets are not byte-identical.
BOXES_7B = [
    (126, 267, 214, 337),
    (220, 268, 308, 337),
    (312, 267, 400, 337),
]
BOXES_7C = [
    (12, 154, 100, 226),
    (106, 154, 183, 226),
    (189, 155, 270, 226),
]


def main() -> int:
    im = Image.open(SRC).convert("RGB")
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    bg = Counter(small.getdata()).most_common(1)[0][0]
    path = GEN / "species_anim.json"
    anim = json.loads(path.read_text()) if path.is_file() else {"species": {}}
    for key, species, boxes in (("7b", 0x7B, BOXES_7B),
                                ("7c", 0x7C, BOXES_7C)):
        frames = []
        for i, (x0, y0, x1, y1) in enumerate(boxes):
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
            tex = f"enemy_{key}_{i}.png"
            crop.save(GEN / tex)
            frames.append({
                "texture": tex,
                "anchor_x": crop.width // 2,
                "anchor_y": crop.height,
                "duration": 8,
                "width": crop.width,
                "height": crop.height,
            })
            print(f"  {key} frame {i}: {crop.size}")
        anim.setdefault("species", {})[key] = {
            "species": species,
            "frames": frames,
            "states": {"0": list(range(len(frames)))},
            "default": 0,
            "source": "docs/sprites Scula.gif",
        }
    path.write_text(json.dumps(anim, indent=1))
    print(f"Scula: {len(frames)} frames -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
