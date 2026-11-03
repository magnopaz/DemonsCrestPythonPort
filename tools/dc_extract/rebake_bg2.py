#!/usr/bin/env python3
"""Rebuild a room's BG2 layer from a VRAM dump (tilemap AND atlases together).

The port's BG2 tilemap came from the ROM block tables while its atlas came from a
capture, so tile numbers and graphics could disagree - which is what the black
rectangles are. This reads BOTH from the same dump:

  * tilemap at the BG2 screen base from $2109 (BGnSC for BG2, low byte + bit 0
    for the 64-wide flag),
  * CHR at the BG2 tile base from the high nibble of $210B,
  * palettes from CGRAM.

Usage:
  python tools/dc_extract/rebake_bg2.py <dump_dir> --room assets/generated/room_area0.json \
      --out assets/generated --area 0
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from PIL import Image


def tile_pixels(vram: list[int], tile_word: int) -> list[list[int]]:
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


def cgram_colors(cgram: bytes):
    out = []
    for i in range(256):
        lo, hi = cgram[i * 2], cgram[i * 2 + 1]
        v = lo | (hi << 8)
        out.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31,
                    ((v >> 10) & 31) * 255 // 31))
    return out


def bg_atlas(vram, colors, palette: int, base_word: int) -> Image.Image:
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
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--area", type=int, required=True)
    ap.add_argument("--layer", type=int, default=1, help="index in room bg[] (1 = bg2)")
    args = ap.parse_args()

    vram_bytes = (args.dump / "vram.bin").read_bytes()
    cgram = (args.dump / "cgram.bin").read_bytes()
    ppu = json.loads((args.dump / "ppu.json").read_text())
    vram = list(struct.unpack("<32768H", vram_bytes))
    colors = cgram_colors(cgram)

    bgsc = ppu.get("bgXsc") or []
    sc = int(str(bgsc[1] if len(bgsc) > 1 else bgsc[0]), 16)
    sc_base = (sc & 0xFC) << 8            # tilemap word address
    wide = sc & 1

    tile_adr = int(str(ppu.get("bgTileAdr", "0x0500")), 16)
    chr_base = ((tile_adr >> 4) & 0x0F) << 11

    cols = 64 if wide else 32
    rows = 32
    tilemap = []
    pals = set()
    for y in range(rows):
        for x in range(cols):
            off = sc_base + y * cols + x
            word = vram[off & 0x7FFF]
            tilemap.append(word)
            pals.add((word >> 10) & 7)
    print(f"bg2: sc {sc:02x} base word {sc_base} {cols}x{rows}, "
          f"chr base {chr_base}, palettes {sorted(pals)}")

    room = json.loads(args.room.read_text())
    layer = room["bg"][args.layer]
    layer["tilemap"] = tilemap
    layer["map_width"] = cols
    layer["map_height"] = rows
    args.room.write_text(json.dumps(room, indent=1))
    print("room updated:", args.room, layer["name"], cols, "x", rows)

    for pal in sorted(pals):
        bg_atlas(vram, colors, pal, chr_base).save(
            args.out / f"bg2_area{args.area}_pal{pal}.png")
    print("atlases:", sorted(pals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
