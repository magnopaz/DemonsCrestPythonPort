#!/usr/bin/env python3
"""Harvest a LoRA-ready image set from the demon's Crest sprite sheets.

The sheets in ``docs/sprites`` are the only style reference this project has,
and they are hostile to training as-is: each one is a big opaque grid of poses
with a flat background colour, sheet captions in the same image, and poses much
smaller than a diffusion model wants. Feeding whole sheets to a trainer is the
usual reason a fan-made style LoRA comes out mushy -- it learns the sheet
layout, the captions and the background instead of the sprites.

This tool cuts per-pose crops and writes them at a resolution the trainer can
use:

1. trusted pose boxes for the six Firebrand form sheets (imported from
   ``tools/dc_extract/bake_player_forms.py`` so the boxes stay in one place),
   plus component-based harvesting for the other sheets;
2. the flat sheet background is keyed to transparency;
3. every pose is padded to a square and upscaled by an **integer** factor with
   nearest neighbour, so the pixel grid stays a pixel grid -- models trained on
   interpolated sprites learn smeared edges;
4. optional palette variants (hue-rotated copies of the same pose) grow a small
   set without inventing new shapes;
5. a ``.txt`` caption per image and a ``manifest.json`` with the counts.

Output goes wherever ``--out`` points; nothing lands in the repo. The doc that
uses this is ``docs/AI_CHARACTER_PIPELINE.md``.

Usage:
  python3 tools/gen/harvest_dataset.py --out ~/datasets/dcrest
  python3 tools/gen/harvest_dataset.py --out ~/datasets/dcrest \\
      --sheets forms,enemies --variants 2 --size 512
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SPRITES = ROOT / "docs/sprites"
sys.path.insert(0, str(ROOT / "tools/dc_extract"))
sys.path.insert(0, str(ROOT / "tools/gen"))

import bake_player_forms as bake  # noqa: E402
from pixelize import recolour  # noqa: E402

ENEMY_SHEETS = [
    "Enemies & Bosses - Enemies 1.gif",
    "Enemies & Bosses - Enemies 2.gif",
    "Enemies & Bosses - Crawler.gif",
    "Enemies & Bosses - Flame Lord.gif",
    "Enemies & Bosses - Gnome.gif",
    "Miscellaneous - NPCs.png",
    "Miscellaneous - Unused Assets.png",
]

STYLE = "dcrest snes style, limited palette, hard pixels, dark outline"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True,
                    help="dataset root (outside the repo, e.g. "
                         "~/datasets/dcrest)")
    ap.add_argument("--sheets", default="forms",
                    help="comma list: forms, enemies, all")
    ap.add_argument("--size", type=int, default=512,
                    help="canvas size per crop; the pose is upscaled by an "
                         "integer factor that fits")
    ap.add_argument("--variants", type=int, default=0,
                    help="extra palette variants per pose (hue rotation)")
    ap.add_argument("--min-area", type=int, default=40,
                    help="component-based harvesting: minimum component area")
    return ap.parse_args()


def key(rgb: Image.Image, bg) -> Image.Image:
    im = rgb.convert("RGBA")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, _a = px[x, y]
            if bake.is_bg((r, g, b), bg):
                px[x, y] = (0, 0, 0, 0)
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im


def place(pose: Image.Image, size: int) -> Image.Image:
    """Integer-scale and centre a pose on a transparent square canvas."""
    factor = max(1, size // max(pose.width, pose.height))
    big = pose.resize((pose.width * factor, pose.height * factor),
                      Image.NEAREST)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(big, ((size - big.width) // 2, (size - big.height) // 2), big)
    return canvas


def emit(out_root: Path, name: str, image: Image.Image, caption: str) -> None:
    image.save(out_root / f"{name}.png")
    (out_root / f"{name}.txt").write_text(caption + "\n")


def harvest_forms(out_root: Path, size: int, variants: int, stats: dict) -> None:
    for _form, form_name, sheet, bands in bake.SHEETS:
        path = SPRITES / f"SNES - Demon's Crest - {sheet}"
        if not path.is_file():
            print(f"harvest: missing sheet {path.name}", file=sys.stderr)
            continue
        im = Image.open(path).convert("RGB")
        bg = bake.background_colour(im)
        boxes = bake.connected_boxes(im, bg)
        for clip, (x0, x1, y0, y1) in bands.items():
            selected = [b for b in boxes
                        if b[0] >= x0 - 2 and b[2] <= x1 + 2 and
                        b[1] >= y0 - 2 and b[3] <= y1 + 2]
            selected.sort(key=lambda b: (b[0], b[1]))
            if clip == "hurt" and selected:
                selected = [max(selected,
                                key=lambda b: bake.pose_brightness(
                                    key(im.crop(b[:4]), bg)))]
            for index, box in enumerate(selected):
                pose = key(im.crop(box[:4]), bg)
                if pose.width < 8 or pose.height < 8:
                    continue
                stem = f"firebrand_{form_name}_{clip}_{index:02d}"
                emit(out_root, stem, place(pose, size),
                     f"{STYLE}, firebrand gargoyle demon, {form_name} form, "
                     f"{clip} pose, side view")
                stats["crops"] += 1
                stats["by_form"][form_name] = stats["by_form"].get(form_name, 0) + 1
                for v in range(variants):
                    tilt = 0.08 * (v + 1) * (1 if v % 2 == 0 else -1)
                    variant = recolour(place(pose, size), tilt, 1.0)
                    emit(out_root, f"{stem}_p{v + 1}", variant,
                         f"{STYLE}, firebrand gargoyle demon, {form_name} form, "
                         f"{clip} pose, side view, palette variant")
                    stats["crops"] += 1
                    stats["variants"] += 1


def harvest_components(out_root: Path, size: int, variants: int, stats: dict,
                       min_area: int) -> None:
    for sheet in ENEMY_SHEETS:
        path = SPRITES / f"SNES - Demon's Crest - {sheet}"
        if not path.is_file():
            continue
        im = Image.open(path).convert("RGB")
        bg = bake.background_colour(im)
        boxes = [b for b in bake.connected_boxes(im, bg) if b[4] >= min_area]
        # captions are short glyph clusters; real poses are taller than 20px
        boxes = [b for b in boxes if (b[3] - b[1]) >= 20 and (b[2] - b[0]) >= 8]
        slug = sheet.replace("SNES - Demon's Crest - ", "").replace(" ", "_")
        slug = Path(slug).stem.lower()
        for index, box in enumerate(sorted(boxes, key=lambda b: (b[1], b[0]))):
            pose = key(im.crop(box[:4]), bg)
            if pose.width < 8 or pose.height < 8:
                continue
            stem = f"{slug}_{index:03d}"
            emit(out_root, stem, place(pose, size),
                 f"{STYLE}, demon's crest creature, side view")
            stats["crops"] += 1
            stats["by_sheet"][slug] = stats["by_sheet"].get(slug, 0) + 1
            for v in range(variants):
                tilt = 0.08 * (v + 1) * (1 if v % 2 == 0 else -1)
                emit(out_root, f"{stem}_p{v + 1}",
                     recolour(place(pose, size), tilt, 1.0),
                     f"{STYLE}, demon's crest creature, side view, "
                     f"palette variant")
                stats["crops"] += 1
                stats["variants"] += 1


def main() -> int:
    args = parse_args()
    wanted = {part.strip() for part in args.sheets.split(",") if part.strip()}
    do_forms = "forms" in wanted or "all" in wanted
    do_enemies = "enemies" in wanted or "all" in wanted
    out_root = args.out.expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    stats = {"crops": 0, "variants": 0, "by_form": {}, "by_sheet": {},
             "size": args.size, "sheets": sorted(wanted)}
    if do_forms:
        harvest_forms(out_root, args.size, args.variants, stats)
    if do_enemies:
        harvest_components(out_root, args.size, args.variants, stats,
                           args.min_area)

    manifest = out_root / "manifest.json"
    manifest.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"harvest: {stats['crops']} images at {args.size}x{args.size} "
          f"({stats['variants']} palette variants) -> {out_root}")
    print(f"harvest: manifest {manifest}")
    if stats["crops"] < 200 and do_forms:
        print("harvest: fewer than 200 crops; add --variants 2 or --sheets all "
              "before training", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
