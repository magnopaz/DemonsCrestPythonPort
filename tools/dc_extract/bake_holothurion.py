#!/usr/bin/env python3
"""Bake Holothurion (area 52 boss, species $96) from his sheet.

The sheet's bottom "Examples" row contains three complete shell/body poses;
the rows above are heads, shells and projectiles. The examples are full boss
sprites, so use their measured boxes and anchor each at the bottom centre.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Holothurion.gif"
GEN = ROOT / "assets/generated"

# Bottom examples: complete shell + body + eyes.
BOXES = [(42, 346, 197, 444), (207, 346, 381, 444), (391, 344, 566, 444)]


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
        tex = f"enemy_6f_{i}.png"
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
    anim.setdefault("species", {}).pop("96_boss", None)
    anim.setdefault("species", {})["6f"] = {
        "species": 0x6F,
        "frames": frames,
        "states": {"0": list(range(len(frames)))},
        "default": 0,
        "source": "docs/sprites Holothurion.gif (Examples row)",
    }
    path.write_text(json.dumps(anim, indent=1))
    print(f"Holothurion: {len(frames)} frames -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
