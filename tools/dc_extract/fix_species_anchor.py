#!/usr/bin/env python3
"""Recompute a species sheet's anchors from the art's own alpha bounding box.

Baked sheets often carry transparent padding, and an anchor measured against the
texture edge then sits well below the creature: Somulo's frames are 120x140 with
content only down to y=92, so anchoring at y=140 left him hovering 48 px above
the floor he was standing on.

This measures the union of every frame's non-transparent bbox and moves the
anchor to the bottom-centre of that union, which keeps frames aligned to each
other while putting the feet on the object's own position.

Usage:
  python3 tools/dc_extract/fix_species_anchor.py --species 33
  python3 tools/dc_extract/fix_species_anchor.py --species 33 --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--species", required=True, help="hex key as used in species_anim.json")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--feet-band", default="",
                    help="'x0:x1' fraction of the width holding the legs; anchors "
                         "each frame on that band's lowest opaque row instead of "
                         "the union bbox, so the feet plant every frame")
    ap.add_argument("--center", action="store_true",
                    help="anchor on the texture centre. Small ground props (urns, "
                         "crest pickups) have their object position at the sprite "
                         "centre, and the CHR-tile bake wrote anchor_y 27/26 for "
                         "16 px art, which drew them floating in the air")

    args = ap.parse_args()

    path = args.assets / "species_anim.json"
    doc = json.loads(path.read_text())
    entry = doc["species"].get(args.species.lower().removeprefix("0x"))
    if entry is None:
        raise SystemExit(f"species {args.species} not in {path}")

    if args.center:
        for frame in entry["frames"]:
            w, h = Image.open(args.assets / frame["texture"]).size
            print(f"  {frame['texture']}: anchor {frame.get('anchor_x')},"
                  f"{frame.get('anchor_y')} -> {w / 2.0},{h / 2.0} (centre)")
            if not args.dry_run:
                frame["anchor_x"] = w / 2.0
                frame["anchor_y"] = h / 2.0
        if not args.dry_run:
            path.write_text(json.dumps(doc, indent=1))
            print("written")
        return 0

    band = None
    if args.feet_band:
        lo, hi = (float(v) for v in args.feet_band.split(":"))
        band = (lo, hi)

    if band is not None:
        for frame in entry["frames"]:
            img = Image.open(args.assets / frame["texture"]).convert("RGBA")
            w, h = img.size
            alpha = img.split()[3]
            apx = alpha.load()
            x0, x1 = int(w * band[0]), max(int(w * band[0]) + 1, int(w * band[1]))
            rows = [y for y in range(h)
                    for x in range(x0, x1) if apx[x, y] > 8]
            if not rows:
                continue
            feet = max(rows) + 1
            ax = frame.get("anchor_x", w // 2)
            print(f"  {frame['texture']}: feet row {feet} (was anchor_y "
                  f"{frame.get('anchor_y')})")
            if not args.dry_run:
                frame["anchor_y"] = feet
                frame["anchor_x"] = ax
        if not args.dry_run:
            path.write_text(json.dumps(doc, indent=1))
            print("written")
        return 0

    union = None
    for frame in entry["frames"]:
        img = Image.open(args.assets / frame["texture"]).convert("RGBA")
        box = img.getbbox()
        if box is None:
            continue
        union = box if union is None else (min(union[0], box[0]), min(union[1], box[1]),
                                           max(union[2], box[2]), max(union[3], box[3]))
    if union is None:
        raise SystemExit("all frames are empty")

    anchor_x = (union[0] + union[2]) / 2.0
    anchor_y = float(union[3])
    print(f"species {args.species}: union bbox {union} -> anchor "
          f"({anchor_x:.0f},{anchor_y:.0f})")
    for frame in entry["frames"]:
        print(f"  {frame['texture']}: anchor {frame['anchor_x']},{frame['anchor_y']} "
              f"-> {anchor_x:.0f},{anchor_y:.0f}")
        if not args.dry_run:
            frame["anchor_x"] = int(round(anchor_x))
            frame["anchor_y"] = int(round(anchor_y))

    if not args.dry_run:
        path.write_text(json.dumps(doc, indent=1))
        print("written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
