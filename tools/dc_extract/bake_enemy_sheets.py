#!/usr/bin/env python3
"""Bake the regular enemy sheets that still fell back to the shared ghoul art.

Every box below was measured on the labelled community sheet with column and
row ink profiles (``tools/dc_extract/bake_boss_sheets.py`` has the same
contract for bosses), so a frame is one complete body pose and never a caption,
a row fragment or a detached weapon icon:

* ``Enemies 1`` "Scavenger Demon"  -> ``$2C`` skeleton walker (Area 2).
  The four left-hand poses are the walk cycle; the round sprites after them are
  thrown projectiles and are outside every box.
* ``Enemies 1`` "Armor Zombie"     -> ``$26`` armoured undead walker (Areas 2/3).
  The right-hand palette set of the ``Zombie Head | Armor Zombie`` row.
* ``Enemies 2`` "Ogre Demon"       -> ``$08`` forest ogre (Area 5).  Only the
  four unarmed poses; the axes and the two axe-wielding poses are excluded.
* ``Enemies 1`` "Vampire Bat"      -> ``$07`` bat/watcher (Areas 2/3).  The four
  wing-spread flight poses, not the folded roosting frames.

Species ``$24/$2D/$2E`` are ``pickup_crest`` objects in
``tools/dc_extract/extract.py``'s species map, not enemies, so they are not
baked here.

Background removal floods inwards from the crop border, so dark outlines inside
a sprite stay opaque; small detached specks (sheet sparks, bone debris) are
dropped only when the crop has several components and they are a small
fraction of the body.

The script merges into ``species_anim.json`` without touching other species and
is safe to re-run: it deletes its own stale PNGs first.
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
    "enemies1": "SNES - Demon's Crest - Enemies & Bosses - Enemies 1.gif",
    "enemies2": "SNES - Demon's Crest - Enemies & Bosses - Enemies 2.gif",
}

# (key, species, sheet, source note, boxes, anchor)
# Every sheet pose faces left, so frames are mirrored to face right: the
# renderer mirrors again when ``o->facing < 0`` (review P2), which keeps a
# right-moving enemy pointing the right way.
JOBS = [
    ("2c", 0x2C, "enemies1",
     "Enemies 1.gif 'Scavenger Demon' row, four measured walk poses",
     [(53, 643, 82, 688),
      (83, 643, 112, 688),
      (113, 643, 141, 688),
      (142, 643, 171, 688)],
     "bottom"),
    ("26", 0x26, "enemies1",
     "Enemies 1.gif 'Zombie Head | Armor Zombie' row, armoured walk set",
     [(557, 573, 588, 620),
      (588, 573, 616, 620),
      (616, 573, 652, 620)],
     "bottom"),
    ("08", 0x08, "enemies2",
     "Enemies 2.gif 'Ogre Demon' row, four unarmed poses",
     [(84, 98, 112, 150),
      (120, 98, 156, 150),
      (156, 98, 199, 150),
      (199, 98, 244, 150)],
     "bottom"),
    ("07", 0x07, "enemies1",
     "Enemies 1.gif 'Vampire Bat' row, three side-view flight poses",
     [(306, 885, 332, 925),
      (331, 903, 359, 924),
      (358, 905, 386, 942)],
     "center"),
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


def drop_specks(img: Image.Image, keep_ratio: float = 0.08) -> Image.Image:
    """Remove detached debris when it is a small fraction of the body.

    A pose normally keys to one connected body plus a few isolated highlight
    pixels; sheet sparks or bone debris are separate blobs. Keeping every blob
    that is at least ``keep_ratio`` of the largest one leaves the body intact
    (and a wing that is only joined diagonally) while dropping noise.
    """
    px = img.load()
    w, h = img.size
    seen = bytearray(w * h)
    groups: list[tuple[list[int], int]] = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y][3] == 0:
                continue
            q = deque([(x, y)])
            seen[i] = 1
            cells: list[int] = []
            while q:
                cx, cy = q.popleft()
                cells.append(cy * w + cx)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny][3] != 0:
                                seen[j] = 1
                                q.append((nx, ny))
            groups.append((cells, len(cells)))
    if len(groups) < 3:
        return img
    largest = max(g[1] for g in groups)
    floor = max(4, int(largest * keep_ratio))
    keep = bytearray(w * h)
    for cells, area in groups:
        if area >= floor:
            for i in cells:
                keep[i] = 1
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            if keep[y * w + x]:
                dst[x, y] = px[x, y]
    return out


def main() -> int:
    images = {name: Image.open(SPRITES / path).convert("RGB")
              for name, path in SHEETS.items()}
    bgs = {name: background(im) for name, im in images.items()}

    anim_path = GEN / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {
        "species": {}}
    species_map = anim.setdefault("species", {})

    for key, species, sheet, source, boxes, anchor in JOBS:
        for stale in GEN.glob(f"enemy_{key}_[0-9]*.png"):
            stale.unlink()
        frames = []
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            crop = key_background(images[sheet].crop((x0, y0, x1, y1)),
                                  bgs[sheet])
            crop = drop_specks(crop)
            bbox = crop.getbbox()
            if bbox is None:
                print(f"  {key} {x0},{y0}: empty after keying")
                continue
            crop = crop.crop(bbox).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            tex = f"enemy_{key}_{i}.png"
            crop.save(GEN / tex)
            frames.append({
                "texture": tex,
                "anchor_x": crop.width // 2,
                "anchor_y": crop.height if anchor == "bottom"
                            else crop.height // 2,
                "duration": 8,
                "width": crop.width,
                "height": crop.height,
            })
            print(f"  {key}[{i}] {crop.size}")
        if not frames:
            raise SystemExit(f"bake_enemy_sheets: {key} produced no frames")
        cycle = list(range(len(frames)))
        entry = {
            "species": species,
            "boss": False,
            "frames": frames,
            "states": {"0": cycle, "1": cycle},
            "default": 0,
            "source": source,
        }
        species_map[key] = entry
        print(f"{key}: {len(frames)} frames")

    anim_path.write_text(json.dumps(anim, indent=1))
    print(f"wrote {anim_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
