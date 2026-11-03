#!/usr/bin/env python3
"""Rebake a room BG layer's CHR atlases from a VRAM dump, keeping its tilemap.

The ROM-decompressed BG set is incomplete for areas whose tiles are streamed into
VRAM at run time - those tiles show up as black rectangles. Baking the atlas from
the same VRAM the game uses fills them in.

Usage:
  python tools/dc_extract/rebake_bg_atlas.py <dump_dir> --room room_area0.json \
      --layer 1 --prefix bg_area0 --out assets/generated [--chr-nibble low|high]
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from PIL import Image


def tile_pixels(vram, tile_word):
    rows = []
    for y in range(8):
        w0 = vram[(tile_word + y) & 0x7FFF]
        w1 = vram[(tile_word + 8 + y) & 0x7FFF]
        row = []
        for x in range(8):
            bit = 7 - x
            px = ((w0 >> bit) & 1) | (((w0 >> (8 + bit)) & 1) << 1)
            px |= (((w1 >> bit) & 1) << 2) | (((w1 >> (8 + bit)) & 1) << 3)
            row.append(px)
        rows.append(row)
    return rows


def cgram_colors(cgram):
    out = []
    for i in range(256):
        v = cgram[i * 2] | (cgram[i * 2 + 1] << 8)
        out.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31,
                    ((v >> 10) & 31) * 255 // 31))
    return out


def atlas(vram, colors, palette, base_word):
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    px = img.load()
    for tile in range(1024):
        tx, ty = (tile % 32) * 8, (tile // 32) * 8
        rows = tile_pixels(vram, base_word + tile * 16)
        for y, row in enumerate(rows):
            for x, p in enumerate(row):
                if not p:
                    continue
                r, g, b = colors[palette * 16 + p]
                for qx, qy, fx, fy in ((0, 0, False, False), (256, 0, True, False),
                                       (0, 256, False, True), (256, 256, True, True)):
                    sx = 7 - x if fx else x
                    sy = 7 - y if fy else y
                    px[qx + tx + sx, qy + ty + sy] = (r, g, b, 255)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path)
    ap.add_argument("--room", type=Path, required=True)
    ap.add_argument("--layer", type=int, required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chr-nibble", choices=("low", "high"), default="low")
    args = ap.parse_args()

    vram = list(struct.unpack("<32768H", (args.dump / "vram.bin").read_bytes()))
    colors = cgram_colors((args.dump / "cgram.bin").read_bytes())
    ppu = json.loads((args.dump / "ppu.json").read_text())
    tile_adr = int(str(ppu.get("bgTileAdr", "0x0500")), 16)
    nib = (tile_adr & 0x0F) if args.chr_nibble == "low" else ((tile_adr >> 4) & 0x0F)
    base_word = nib << 11

    room = json.loads(args.room.read_text())
    tilemap = room["bg"][args.layer]["tilemap"]
    pals = sorted({(w >> 10) & 7 for w in tilemap})
    print(f"layer {room['bg'][args.layer]['name']}: {len(tilemap)} entries, "
          f"palettes {pals}, chr base {base_word}")

    for pal in pals:
        atlas(vram, colors, pal, base_word).save(
            args.out / f"{args.prefix}_pal{pal}.png")
    print("wrote", len(pals), "atlases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
