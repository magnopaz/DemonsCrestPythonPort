#!/usr/bin/env python3
"""Bake one labelled enemy-sheet row into frames.

The community sheets group sprites by name, but a row usually contains a
caption plus several poses. This tool crops the caller's measured band, splits
it on background columns, keys the sheet's flat background, and updates
``species_anim.json``. It is deliberately simple: the y band must exclude the
caption row.

Example:
  python tools/sheet_row.py \
    --sheet "docs/sprites/SNES - Demon's Crest - Enemies & Bosses - Enemies 1.gif" \
    --species 2c --x0 0 --x1 420 --y0 300 --y1 380 \
    --source "Scavenger Demon row" --state 0
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", type=Path, required=True)
    ap.add_argument("--species", required=True,
                    help="species id in hex or decimal (e.g. 0x2c or 44)")
    ap.add_argument("--x0", type=int, required=True)
    ap.add_argument("--x1", type=int, required=True)
    ap.add_argument("--y0", type=int, required=True)
    ap.add_argument("--y1", type=int, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--source", default="measured sheet row")
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--anchor", choices=("bottom", "center"), default="bottom")
    ap.add_argument("--state", type=int, default=None,
                    help="optional object state to bind this row to")
    ap.add_argument("--min-width", type=int, default=8)
    ap.add_argument("--min-height", type=int, default=12)
    return ap.parse_args()


def background_colour(im: Image.Image) -> tuple[int, int, int]:
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    return Counter(small.getdata()).most_common(1)[0][0]


def is_bg(pixel, bg) -> bool:
    return abs(pixel[0] - bg[0]) + abs(pixel[1] - bg[1]) + \
        abs(pixel[2] - bg[2]) <= 30


def remove_small_components(img: Image.Image, min_area: int = 24,
                            max_text_height: int = 11) -> Image.Image:
    """Drop detached caption letters/sparks, keeping the main pose."""
    px = img.load()
    w, h = img.size
    seen = bytearray(w * h)
    keep = bytearray(w * h)
    groups = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y][3] == 0:
                continue
            q = deque([(x, y)])
            seen[i] = 1
            cells = []
            minx = maxx = x
            miny = maxy = y
            while q:
                cx, cy = q.popleft()
                cells.append(cy * w + cx)
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny][3] != 0:
                                seen[j] = 1
                                q.append((nx, ny))
            groups.append((cells, minx, miny, maxx, maxy))
    if not groups:
        return img
    largest = max(len(g[0]) for g in groups)
    for cells, minx, miny, maxx, maxy in groups:
        area = len(cells)
        height = maxy - miny + 1
        # Text letters are small, near the top, and detached from the body.
        if area < min_area and height <= max_text_height and \
                area < largest * 0.02:
            continue
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
    args = parse_args()
    species = int(args.species, 0)
    im = Image.open(args.sheet).convert("RGB")
    x1 = min(args.x1, im.width)
    y1 = min(args.y1, im.height)
    if args.x0 < 0 or args.y0 < 0 or args.x1 <= args.x0 or args.y1 <= args.y0:
        raise SystemExit("sheet_row: invalid crop rectangle")
    band = im.crop((args.x0, args.y0, x1, y1))
    bg = background_colour(im)
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
    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] - 1 <= 1:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(list(run))

    args.out.mkdir(parents=True, exist_ok=True)
    frames = []
    for idx, (rx0, rx1) in enumerate(merged):
        ys = [y for y in range(band.height)
              if any(not is_bg(px[x, y], bg) for x in range(rx0, rx1 + 1))]
        if not ys:
            continue
        crop = band.crop((rx0, min(ys), rx1 + 1, max(ys) + 1)).convert("RGBA")
        cpx = crop.load()
        for y in range(crop.height):
            for x in range(crop.width):
                if is_bg(cpx[x, y], bg):
                    cpx[x, y] = (0, 0, 0, 0)
        crop = remove_small_components(crop)
        bbox = crop.getbbox()
        if bbox is None:
            continue
        crop = crop.crop(bbox)
        if crop.width < args.min_width or crop.height < args.min_height:
            continue
        name = f"enemy_{species:02x}_{len(frames)}.png"
        crop.save(args.out / name)
        frames.append({
            "texture": name,
            "anchor_x": crop.width // 2,
            "anchor_y": crop.height if args.anchor == "bottom"
                        else crop.height // 2,
            "duration": max(1, args.duration),
            "width": crop.width,
            "height": crop.height,
        })
        print(f"  frame {len(frames) - 1}: {name} {crop.size}")

    if not frames:
        print("sheet_row: no frames survived", file=sys.stderr)
        return 1
    anim_path = args.out / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {
        "species": {}}
    entry = {
        "species": species,
        "frames": frames,
        "source": args.source,
        "default": 0,
    }
    if args.state is not None:
        entry["states"] = {str(args.state): list(range(len(frames)))}
    anim.setdefault("species", {})[f"{species:02x}"] = entry
    anim_path.write_text(json.dumps(anim, indent=1))
    print(f"sheet_row: {len(frames)} frames -> {anim_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
