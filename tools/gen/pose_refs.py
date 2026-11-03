#!/usr/bin/env python3
"""Cut pose references from an existing species for repainting (Pipeline C).

Stage 4 of docs/AI_CHARACTER_PIPELINE.md ranks pose propagation above free
generation, because a generator cannot keep a character consistent across
frames. The cheapest source of *correct* poses is the game itself: this tool
takes the measured pose boxes that ``bake_enemy_sheets.py`` /
``bake_player_forms.py`` already use for shipped species and turns each pose
into a 1024 px reference an img2img + ControlNet pass can repaint onto a new
creature.

The pixel grid is preserved: the crop is upscaled by an integer factor with
nearest neighbour and then padded on a white canvas, so the control image keeps
the sprite's own pixel steps instead of inventing smooth edges.

Usage:
  python3 tools/gen/pose_refs.py --species 0x2c --out ~/datasets/refs/imp
  python3 tools/gen/pose_refs.py --species 0x2c --out refs --size 768 \\
      --labels walk0,walk1,walk2,walk3
  python3 tools/gen/pose_refs.py --list      # species this tool can cut
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/dc_extract"))

import bake_enemy_sheets as enemies  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--species", default="0x2c",
                    help="species id from bake_enemy_sheets.JOBS (hex or dec)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--size", type=int, default=1024,
                    help="canvas size per reference (square)")
    ap.add_argument("--labels", default="",
                    help="comma list of clip labels, one per pose")
    ap.add_argument("--list", action="store_true", help="list available species")
    return ap.parse_args()


def key_to_white(crop: Image.Image, bg, tol: int = 30) -> Image.Image:
    """Flood the sheet background to white from the crop border."""
    im = crop.convert("RGB")
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    stack = []
    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h):
            continue
        if seen[y * w + x]:
            continue
        seen[y * w + x] = 1
        r, g, b = px[x, y]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > tol:
            continue
        px[x, y] = (255, 255, 255)
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return im


def main() -> int:
    args = parse_args()
    jobs = {f"0x{j[1]:x}": j for j in enemies.JOBS}
    if args.list:
        for key, job in sorted(jobs.items()):
            print(f"{key:8s} {len(job[4])} poses  {job[3]}")
        return 0
    if args.species not in jobs:
        print(f"pose_refs: unknown species {args.species}; try --list",
              file=sys.stderr)
        return 2
    if args.out is None:
        print("pose_refs: --out is required", file=sys.stderr)
        return 2

    key, species, sheet_key, note, boxes, anchor = jobs[args.species]
    sheet_path = ROOT / "docs/sprites" / enemies.SHEETS[sheet_key]
    if not sheet_path.is_file():
        print(f"pose_refs: missing sheet {sheet_path}", file=sys.stderr)
        return 2
    sheet = Image.open(sheet_path)
    bg = enemies.background(sheet)

    labels = [part.strip() for part in args.labels.split(",") if part.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"species": species, "source": sheet_path.name, "note": note,
                "size": args.size, "poses": []}
    for index, box in enumerate(boxes):
        crop = sheet.crop(box)
        crop = key_to_white(crop, bg)
        bbox = crop.getbbox()
        factor = max(1, min(8, args.size // max(1, max(crop.size))))
        big = crop.resize((crop.width * factor, crop.height * factor),
                          Image.NEAREST)
        canvas = Image.new("RGB", (args.size, args.size), (255, 255, 255))
        canvas.paste(big, ((args.size - big.width) // 2,
                           (args.size - big.height) // 2))
        name = f"pose_{index}.png"
        canvas.save(args.out / name)
        label = labels[index] if index < len(labels) else f"pose{index}"
        manifest["poses"].append({"file": name, "label": label,
                                  "box": list(box), "scale": factor,
                                  "crop": list(bbox or (0, 0, 0, 0))})
        print(f"{args.out / name}: {label} box={box} x{factor} -> "
              f"{canvas.size[0]}x{canvas.size[1]}")
    (args.out / "refs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"pose_refs: {len(boxes)} references for species {args.species} "
          f"({note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
