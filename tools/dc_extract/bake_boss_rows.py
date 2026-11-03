#!/usr/bin/env python3
"""Bake measured full-pose boxes from a labelled boss sheet.

This is the small generic path for bosses whose sheet has complete body poses
in one row (Crawler, Belth, ...). Each box becomes a frame of the species'
idle animation, anchored at the bottom centre.

Usage:
  python tools/dc_extract/bake_boss_rows.py \
    --sheet "docs/sprites/...Crawler.gif" --species 0x82 \
    --boxes "14,139,110,228;116,142,214,228;220,142,320,228" \
    --source "Crawler.gif moving row"
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", type=Path, required=True)
    ap.add_argument("--species", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--boxes", required=True,
                    help="semicolon-separated x0,y0,x1,y1 boxes")
    ap.add_argument("--source", default="measured boss sheet row")
    ap.add_argument("--variant", choices=("boss",), default=None,
                    help="mark the entry as a boss variant for the same species")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    im = Image.open(args.sheet).convert("RGB")
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    bg = Counter(small.getdata()).most_common(1)[0][0]
    frames = []
    for raw in args.boxes.split(";"):
        if not raw.strip():
            continue
        x0, y0, x1, y1 = (int(v) for v in raw.split(","))
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
        tex = f"enemy_{args.species:02x}_{len(frames)}.png"
        crop.save(args.out / tex)
        frames.append({
            "texture": tex,
            "anchor_x": crop.width // 2,
            "anchor_y": crop.height,
            "duration": 8,
            "width": crop.width,
            "height": crop.height,
        })
        print(f"  frame {len(frames)-1}: {crop.size}")
    if not frames:
        raise SystemExit("bake_boss_rows: no frames survived")
    path = args.out / "species_anim.json"
    anim = json.loads(path.read_text()) if path.is_file() else {"species": {}}
    key = f"{args.species:02x}"
    entry = {
        "species": args.species,
        "frames": frames,
        "states": {"0": list(range(len(frames)))},
        "default": 0,
        "source": args.source,
    }
    if args.variant:
        entry["variant"] = args.variant
    anim.setdefault("species", {})[key] = entry
    path.write_text(json.dumps(anim, indent=1))
    print(f"{key}: {len(frames)} frames -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
