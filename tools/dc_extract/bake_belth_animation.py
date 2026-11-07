#!/usr/bin/env python3
"""Bake Belth's full pose set from the community boss sheet.

The generated asset only had the walking row (three frames) because
``bake_boss_rows.py`` was pointed at one measured row.  The labelled sheet in
``docs/sprites`` already contains the rest of the animations, ripped from the
same ROM tiles.  This tool slices the measured animation bands, keys the flat
sheet background, removes caption letters/specks, and writes an *authored*
species entry (32 frames, state map) plus PNGs under
``assets/authored/sprites``.

The Python port's loader keeps up to 32 frames; the frozen C reference keeps
10, so this file is Python-only authored content.

Usage:
  python tools/dc_extract/bake_belth_animation.py
  python tools/dc_extract/bake_belth_animation.py --dry-run --out captures/belth_test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from sheet_row import (background_colour, is_bg, remove_small_components)  # noqa: E402

SHEET = ROOT / "docs" / "sprites" / \
    "SNES - Demon's Crest - Enemies & Bosses - Belth.gif"
SPECIES = 0x68

# name, x0, x1, y0, y1; None means "split on empty columns".  Manual boxes are
# needed where a weapon arc connects two adjacent poses.
BANDS = [
    ("idle", 10, 228, 25, 95, None),
    ("taunt", 225, 460, 25, 95, None),
    ("walk", 475, 805, 25, 95, None),
    ("attack", 0, 540, 118, 228, None),
    ("jump", 545, 860, 150, 228, None),
    ("charge", 0, 420, 248, 340, [
        (23, 252, 113, 334), (118, 261, 208, 334),
        (214, 257, 283, 334), (289, 277, 406, 334),
    ]),
    ("turn", 530, 860, 270, 348, None),
    ("hurt", 40, 140, 350, 425, None),
    ("death", 660, 725, 398, 425, [(660, 398, 725, 425)]),
]
EXPECTED = {"idle": 3, "taunt": 3, "walk": 4, "attack": 7, "jump": 4,
            "charge": 4, "turn": 5, "hurt": 1, "death": 1}


def split_runs(band: Image.Image, bg) -> list[tuple[int, int]]:
    px = band.load()
    runs = []
    start = None
    for x in range(band.width):
        hit = any(not is_bg(px[x, y], bg) for y in range(band.height))
        if hit and start is None:
            start = x
        elif not hit and start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, band.width - 1))
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] - 1 <= 1:
            merged[-1] = [merged[-1][0], run[1]]
        else:
            merged.append(list(run))
    return [(a, b) for a, b in merged]


def largest_component_anchor(img: Image.Image) -> tuple[int, int]:
    """Place the object anchor on the largest pose component's bottom centre."""
    px = img.load()
    w, h = img.size
    seen = bytearray(w * h)
    best = None
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y][3] == 0:
                continue
            stack = [(x, y)]
            seen[i] = 1
            n = 0
            minx = maxx = x
            miny = maxy = y
            while stack:
                cx, cy = stack.pop()
                n += 1
                minx = min(minx, cx); maxx = max(maxx, cx)
                miny = min(miny, cy); maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny][3] != 0:
                                seen[j] = 1
                                stack.append((nx, ny))
            if best is None or n > best[0]:
                best = (n, minx, maxx, miny, maxy)
    if best is None:
        return img.width // 2, img.height
    _n, minx, maxx, _miny, maxy = best
    return (minx + maxx + 1) // 2, maxy + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", type=Path, default=SHEET)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "assets" / "authored",
                    help="authored root (sprites/ and species_anim.json)")
    args = ap.parse_args()
    if not args.sheet.is_file():
        raise SystemExit(f"bake_belth: missing sheet {args.sheet}")
    im = Image.open(args.sheet).convert("RGB")
    bg = background_colour(im)
    sprites = args.out / "sprites"
    sprites.mkdir(parents=True, exist_ok=True)
    for stale in sprites.glob("belth_*.png"):
        stale.unlink()

    frames = []
    states: dict[str, list[int]] = {}
    labels: dict[str, tuple[int, int]] = {}
    for name, x0, x1, y0, y1, manual in BANDS:
        band = im.crop((x0, y0, x1, y1))
        entry_indices = []
        if manual is not None:
            for box in manual:
                crop = im.crop(box).convert("RGBA")
                cleaned = _clean(crop, bg)
                if cleaned is not None:
                    entry_indices.append(_add_frame(
                        cleaned, name, frames, sprites))
        else:
            for a, b in split_runs(band, bg):
                crop = band.crop((a, 0, b + 1, band.height)).convert("RGBA")
                cleaned = _clean(crop, bg)
                if cleaned is not None:
                    entry_indices.append(_add_frame(
                        cleaned, name, frames, sprites))
        if entry_indices:
            states[str(len(states))] = entry_indices
            labels[name] = (entry_indices[0], entry_indices[-1])
            print(f"  {name}: {len(entry_indices)} frames "
                  f"[{entry_indices[0]}..{entry_indices[-1]}]")
        else:
            print(f"  {name}: NO FRAMES", file=sys.stderr)
    counts = {name: (hi - lo + 1) for name, (lo, hi) in labels.items()}
    print("counts", counts)
    if counts != EXPECTED:
        raise SystemExit(f"bake_belth: expected {EXPECTED}, got {counts}")
    entry = {
        "species": SPECIES,
        "frames": frames,
        "duration": 8,
        "states": states,
        "state_names": {key: name for key, name in enumerate(labels)},
        "hurt": labels["hurt"][0],
        "default": 0,
        "source": ("Belth.gif: idle, taunt, walk, attack, jump, charge, "
                   "turn, hurt, death rows"),
    }
    path = args.out / "species_anim.json"
    anim = {"species": {}}
    if path.is_file():
        anim = json.loads(path.read_text())
    anim.setdefault("species", {})[f"{SPECIES:02x}"] = entry
    path.write_text(json.dumps(anim, indent=1) + "\n")
    print(f"{len(frames)} frames -> {path}")
    return 0


def _clean(crop: Image.Image, bg) -> Image.Image | None:
    cpx = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            if is_bg(cpx[x, y], bg):
                cpx[x, y] = (0, 0, 0, 0)
    crop = remove_small_components(crop)
    bbox = crop.getbbox()
    if bbox is None:
        return None
    crop = crop.crop(bbox)
    if crop.width < 8 or crop.height < 12:
        return None
    return crop


def _add_frame(crop: Image.Image, name: str, frames: list,
               sprites: Path) -> int:
    ax, ay = largest_component_anchor(crop)
    index = len(frames)
    tex = f"belth_{index:02d}_{name}.png"
    crop.save(sprites / tex)
    frames.append({
        "texture": f"sprites/{tex}",
        "anchor_x": ax,
        "anchor_y": ay,
        "duration": 10 if name in ("idle", "taunt") else 8,
        "width": crop.width,
        "height": crop.height,
    })
    return index


if __name__ == "__main__":
    raise SystemExit(main())
