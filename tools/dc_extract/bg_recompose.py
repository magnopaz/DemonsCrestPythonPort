#!/usr/bin/env python3
"""Recompose a frame's background layers from a VRAM dump and compare.

The same recomposition gate that settled the sprite decoder: draw BG1 and BG2
from the dump with the dump's own registers, put the result next to the game's
recorded frame, and let the pixels say whether the data or the renderer is wrong.

Units matter: BGnSC's base field ($2107..$210A) is in **1 KB steps** and the CHR
base from $210B is in **4 KB steps**.

Usage:
  python tools/dc_extract/bg_recompose.py <dump_dir> [--frame frame_001200.bmp]
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 256, 224


def tile_rows(vram, word, bpp):
    rows = []
    for y in range(8):
        w0 = vram[(word + y) & 0x7FFF]
        w1 = vram[(word + 8 + y) & 0x7FFF] if bpp == 4 else 0
        row = []
        for x in range(8):
            bit = 7 - x
            p = ((w0 >> bit) & 1) | (((w0 >> (8 + bit)) & 1) << 1)
            if bpp == 4:
                p |= (((w1 >> bit) & 1) << 2) | (((w1 >> (8 + bit)) & 1) << 3)
            row.append(p)
        rows.append(row)
    return rows


def cgram_colors(cgram):
    out = []
    for i in range(256):
        v = cgram[i * 2] | (cgram[i * 2 + 1] << 8)
        out.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31,
                    ((v >> 10) & 31) * 255 // 31))
    return out


def sc_map_base_words(sc: int) -> int:
    # BGnSC bits 2..7 are the tilemap base in 1 KB units. The old code
    # divided by two as if this were a byte address, reading half a map early.
    return (sc & 0xFC) << 8


def chr_base_words(tile_adr: int, layer: int) -> int:
    # BGnNBA selects the character base in 4 KB units; tile_rows() consumes
    # 16-bit VRAM words, so the byte base is divided by two.
    nib = (tile_adr & 0x0F) if layer in (1, 3) else ((tile_adr >> 4) & 0x0F)
    return nib << 11


def render_layer(vram, colors, sc, chr_base, bpp, hscroll, vscroll):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()
    size = sc & 3
    cols = 64 if (size & 1) else 32
    rows = 64 if (size & 2) else 32
    map_base = sc_map_base_words(sc)
    cache = {}
    for sy in range(H):
        wy = (sy + vscroll) % (rows * 8)
        ty, py = divmod(wy, 8)
        for sx in range(W):
            wx = (sx + hscroll) % (cols * 8)
            tx, pxx = divmod(wx, 8)
            word = vram[(map_base + ty * cols + tx) & 0x7FFF]
            tile = word & 0x3FF
            pal = (word >> 10) & 7
            key = (tile, pal)
            rows_px = cache.get(key)
            if rows_px is None:
                rows_px = tile_rows(vram, chr_base + tile * (16 if bpp == 4 else 8),
                                    bpp)
                cache[key] = rows_px
            yy = 7 - py if (word & 0x8000) else py
            xx = 7 - pxx if (word & 0x4000) else pxx
            idx = rows_px[yy][xx]
            if idx:
                r, g, b = colors[pal * 16 + idx]
                px[sx, sy] = (r, g, b, 255)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path)
    ap.add_argument("--frame", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or (args.dump / "bg_recompose.png")

    vram = list(struct.unpack("<32768H", (args.dump / "vram.bin").read_bytes()))
    colors = cgram_colors((args.dump / "cgram.bin").read_bytes())
    ppu = json.loads((args.dump / "ppu.json").read_text())
    bgmode = ppu.get("bgmode", 1)
    bgsc = [int(str(v), 16) for v in ppu.get("bgXsc", [0, 0, 0, 0])]
    hs = ppu.get("hScroll", [0, 0, 0, 0])
    vs = ppu.get("vScroll", [0, 0, 0, 0])
    tile_adr = int(str(ppu.get("bgTileAdr", "0x0500")), 16)

    print(f"bgmode {bgmode} sc {[hex(v) for v in bgsc[:2]]} "
          f"h {hs[:2]} v {vs[:2]} tileAdr {hex(tile_adr)}")

    # Mode 1: BG1 and BG2 are 4bpp, BG3 is 2bpp.
    bg2 = render_layer(vram, colors, bgsc[1], chr_base_words(tile_adr, 2), 4,
                       hs[1], vs[1])
    bg1 = render_layer(vram, colors, bgsc[0], chr_base_words(tile_adr, 1), 4,
                       hs[0], vs[0])

    # Keep the layers separate as well: stitching a room backdrop needs each
    # layer at its own scroll, not the flattened composite.
    bg2_path = out.with_name(out.stem + "_bg2.png")
    bg1_path = out.with_name(out.stem + "_bg1.png")
    bg2.convert("RGB").save(bg2_path)
    bg1.convert("RGB").save(bg1_path)

    comp = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    comp.alpha_composite(bg2)
    comp.alpha_composite(bg1)
    comp.convert("RGB").save(out)

    tiles = [bg2.convert("RGB"), bg1.convert("RGB"),
             comp.convert("RGB")]
    labels = ["BG2", "BG1", "BG2+BG1"]
    if args.frame and args.frame.is_file():
        tiles.append(Image.open(args.frame).convert("RGB").resize((W, H)))
        labels.append("game")

    sheet = Image.new("RGB", (W * len(tiles) + 8 * (len(tiles) - 1), H + 14),
                      (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (im, label) in enumerate(zip(tiles, labels)):
        sheet.paste(im, (i * (W + 8), 14))
        d.text((i * (W + 8) + 2, 1), label, fill=(255, 255, 0))
    side = out.with_name("bg_recompose_side.png")
    sheet.save(side)
    print("wrote", out, bg2_path.name, bg1_path.name, "and", side.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
