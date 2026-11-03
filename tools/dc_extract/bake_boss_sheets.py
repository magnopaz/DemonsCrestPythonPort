#!/usr/bin/env python3
"""Bake the boss sheets the port still lacked: $82, $86, $8D, $58, $BC.

Every box below was measured on the labelled sheet (column/row profiles), so a
frame is one complete body pose and never a caption or a row fragment:

* ``Crawler.gif``          -> ``$82``  "Moving" row, three clean bodies.
* ``Phalanx.gif``          -> ``$86``  First Fight "Idle / Gesturing" row.
* ``Ultimate Phalanx.gif`` -> ``$8D``  "Examples" row: the assembled head +
  arms + serpent body, which is the second form the port spawns after $86 dies.
* ``Flame Lord.gif``       -> ``$58``  "Idle" group (the left part of the row is
  the teleport flame effect, not the boss).
* ``Dark Demon.gif``       -> ``$BC``  top "Idle / Charge / Attack" body row.

Background removal floods from the sheet border instead of keying every
background-coloured pixel, so dark outlines inside a sprite stay opaque.

The script merges into ``species_anim.json`` (it does not overwrite the other
species) and is safe to re-run: it first deletes its own stale PNGs.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SPRITES = ROOT / "docs" / "sprites"
GEN = ROOT / "assets" / "generated"

SHEETS = {
    "crawler": "SNES - Demon's Crest - Enemies & Bosses - Crawler.gif",
    "phalanx": "SNES - Demon's Crest - Enemies & Bosses - Phalanx.gif",
    "ultimate": "SNES - Demon's Crest - Enemies & Bosses - Ultimate Phalanx.gif",
    "flame": "SNES - Demon's Crest - Enemies & Bosses - Flame Lord.gif",
    "dark": "SNES - Demon's Crest - Enemies & Bosses - Dark Demon.gif",
}

# (key, species, sheet, source note, boxes, boss variant flags)
JOBS = [
    ("82", 0x82, "crawler",
     "Crawler.gif 'Moving' row, measured body boxes",
     [(13, 137, 111, 230),
      (115, 137, 215, 230),
      (219, 137, 321, 230)],
     None),
    ("86", 0x86, "phalanx",
     "Phalanx.gif First Fight 'Idle / Gesturing' row",
     [(8, 84, 59, 172),
      (66, 84, 106, 172),
      (112, 84, 157, 172),
      (162, 84, 204, 172)],
     None),
    ("8d", 0x8D, "ultimate",
     "Ultimate Phalanx.gif 'Examples' row (assembled second form)",
     [(194, 429, 322, 628),
      (332, 429, 492, 628),
      (510, 429, 625, 628)],
     0),
    ("58", 0x58, "flame",
     "Flame Lord.gif 'Idle' group",
     [(329, 29, 377, 111),
      (382, 29, 427, 111),
      (432, 29, 476, 111),
      (482, 29, 528, 111)],
     None),
    ("bc", 0xBC, "dark",
     "Dark Demon.gif top 'Idle / Charge / Attack' body row",
     [(5, 44, 133, 149),
      (139, 44, 273, 149),
      (279, 44, 401, 149),
      (420, 44, 534, 149)],
     None),
]


def background(im: Image.Image) -> tuple[int, int, int]:
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    colors = small.convert("RGB").getcolors(maxcolors=1 << 24) or []
    best = max(colors, key=lambda item: item[0])
    return cast(tuple[int, int, int], best[1])


def key_background(crop: Image.Image, bg: tuple[int, int, int],
                   tolerance: int = 40) -> Image.Image:
    """Clear the sheet backdrop, flooding inwards from the crop border."""
    crop = crop.convert("RGBA")
    px = crop.load()
    w, h = crop.size

    def is_bg(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        return bool(a) and (abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
                            <= tolerance)

    seen = [[False] * w for _ in range(h)]
    queue: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not seen[y][x] and is_bg(x, y):
                seen[y][x] = True
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y][x] and is_bg(x, y):
                seen[y][x] = True
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and is_bg(nx, ny):
                seen[ny][nx] = True
                queue.append((nx, ny))
    return crop


def main() -> int:
    images = {name: Image.open(SPRITES / path).convert("RGB")
              for name, path in SHEETS.items()}
    bgs = {name: background(im) for name, im in images.items()}

    anim_path = GEN / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {
        "species": {}}
    species_map = anim.setdefault("species", {})

    for key, species, sheet, source, boxes, flags in JOBS:
        for stale in GEN.glob(f"enemy_{key}_[0-9]*.png"):
            stale.unlink()
        frames = []
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            crop = key_background(images[sheet].crop((x0, y0, x1, y1)),
                                  bgs[sheet])
            bbox = crop.getbbox()
            if bbox is None:
                print(f"  {key} {x0},{y0}: empty after keying")
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
            print(f"  {key}[{i}] {crop.size}")
        if not frames:
            raise SystemExit(f"bake_boss_sheets: {key} produced no frames")
        entry = {
            "species": species,
            "frames": frames,
            "states": {"0": list(range(len(frames)))},
            "default": 0,
            "source": source,
        }
        if flags is not None:
            entry["variant"] = "boss"
            entry["flags"] = flags
        species_map[key] = entry
        print(f"{key}: {len(frames)} frames")

    anim_path.write_text(json.dumps(anim, indent=1))
    print(f"wrote {anim_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
