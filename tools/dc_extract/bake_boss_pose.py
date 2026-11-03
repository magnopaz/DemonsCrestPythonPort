#!/usr/bin/env python3
"""Compose a boss pose straight from the OAM the guest drew.

The species -> metasprite map does not cover every boss part: Somulo's head is
group `$09` of `$8B:8000`, but the second half of his sprite (the neck frill and
jaw overlay) is drawn from a table the group decoder does not reach, so matching
the OAM against groups leaves 13 of 28 parts unexplained.  The OAM itself is
exact, though - it is literally what the PPU rendered - so this tool composes
the boss layer from the live OAM and the capture's OBJ VRAM instead of from ROM
group data.

Boss layer selection: sprite palette 1 and tile >= 0x80.  In the colosseum the
dragon relief and the gate pieces are also palette 1 but use tiles 0x00-0x22;
the boss always starts at tile 0x80 in the area's OBJ CHR.  `--tile-min` /
`--tile-max` override that.

The palette is sampled from the capture's screenshot (`sample_palette`), so a
CGRAM that the game restored after drawing cannot tint the result.

Usage:
  python3 tools/dc_extract/bake_boss_pose.py --capture /tmp/cap_fight --sample f002 \
      --out /tmp/pose.png
  python3 tools/dc_extract/bake_boss_pose.py --capture /tmp/cap_fight --all \
      --out-dir /tmp/poses
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from extract import (OamSprite, colorize, compose_oam_indices,  # noqa: E402
                     parse_oam, sample_palette)


def load_sample(d: Path, sample: dict):
    oam = (d / f"{sample['name']}.oam.bin").read_bytes()
    cgram = (d / f"{sample['name']}.cgram.bin").read_bytes()
    vram = list(struct.unpack(
        "<32768H", (d / f"{sample['name']}.vram.bin").read_bytes()))
    ppu = sample.get("ppu", {})
    obsel = ppu.get("obsel", 0)
    obsel = int(str(obsel), 16) if isinstance(obsel, str) else int(obsel)
    return oam, cgram, vram, obsel


def compose(d: Path, sample: dict, tile_min: int, tile_max: int,
            palette: int) -> tuple[Image.Image, int, int] | None:
    oam, cgram, vram, obsel = load_sample(d, sample)
    obj_base = (obsel & 7) << 13
    obj_vram = vram[obj_base:obj_base + 0x2000]
    sprites = [s for s in parse_oam(oam, obsel)
               if s.y < 224 and s.palette == palette
               and tile_min <= s.tile <= tile_max]
    if not sprites:
        return None
    index_img, min_x, min_y = compose_oam_indices(obj_vram, sprites)
    bbox = index_img.getbbox()
    if bbox is None:
        return None
    cropped = index_img.crop(bbox)
    colors = [((w & 31) * 8, ((w >> 5) & 31) * 8, ((w >> 10) & 31) * 8)
              for w in struct.unpack("<256H", cgram)]
    fallback = [colors[0x80 + palette * 16 + i] for i in range(16)]
    shot_path = d / f"{sample['name']}.png"
    shot = Image.open(shot_path).convert("RGB") if shot_path.is_file() else None
    pal = sample_palette(index_img, min_x, min_y, shot, fallback)
    img = colorize(cropped, pal)
    return img, min_x + bbox[0], min_y + bbox[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--sample", default="", help="sample name, e.g. f002")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tile-min", type=lambda v: int(v, 0), default=0x80)
    ap.add_argument("--tile-max", type=lambda v: int(v, 0), default=0x1FF)
    ap.add_argument("--palette", type=int, default=1)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    meta = json.loads((args.capture / "meta.json").read_text())
    samples = meta["samples"]
    if args.all:
        chosen = samples
        out_dir = args.out_dir or Path("/tmp/poses")
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        chosen = [s for s in samples if s["name"] == args.sample]
        if not chosen:
            raise SystemExit(f"sample {args.sample!r} not in {args.capture}")
        out_dir = None
    for s in chosen:
        res = compose(args.capture, s, args.tile_min, args.tile_max,
                      args.palette)
        if res is None:
            print(f"{s['name']}: no boss sprites")
            continue
        img, ox, oy = res
        sx, sy = s["screen"]
        # Anchor measured from the object position, in image pixels: the
        # port draws the frame so that (anchor_x, anchor_y) lands on the
        # object's world position.
        ax, ay = sx - ox, sy - oy
        dest = (out_dir / f"{s['name']}.png") if out_dir else args.out
        img.save(dest)
        print(f"{s['name']} frame={s['frame']} world={s['world']} "
              f"img={img.width}x{img.height} at=({ox},{oy}) "
              f"anchor=({ax:.1f},{ay:.1f}) -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
