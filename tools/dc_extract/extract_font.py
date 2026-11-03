#!/usr/bin/env python3
"""Bake the BG3 ASCII font from a `capture_menu.py` dump.

The guest's BG3 text uses tile index == ASCII code, so the glyph tiles sit at
the BG3 character base. This tool decodes tiles 0x20..0x7E as 8x8 2bpp, writes
`font.png` (16 columns x 6 rows, transparent background) plus `font.json`
(first/last codepoint and cell size) for `src/text.c`.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FIRST, LAST = 0x20, 0x7E


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", type=Path, default=ROOT / "captures" / "menu")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    vram_path = args.dump / "vram.bin"
    ppu_path = args.dump / "ppu.json"
    if not vram_path.is_file() or not ppu_path.is_file():
        print(f"extract_font: missing {vram_path} (run capture_menu.py)",
              file=sys.stderr)
        return 77
    vram = list(struct.unpack("<32768H", vram_path.read_bytes()))
    ppu = json.loads(ppu_path.read_text())["ppu"]
    # BG3 in mode 1 is 2bpp; its character base is bits 0-3 of $210C.
    tile_adr = int(ppu["bgTileAdr"], 16)
    base = (tile_adr >> 8 & 0x0F) << 12
    cgram_raw = (args.dump / "cgram.bin").read_bytes()
    words = struct.unpack("<256H", cgram_raw)
    cgram = [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
             for c in words]

    count = LAST - FIRST + 1
    cols, rows = 16, (count + 15) // 16
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    filled = 0
    for i in range(count):
        tile = FIRST + i
        cx, cy = (i % cols) * 8, (i // cols) * 8
        any_pixel = False
        for y in range(8):
            w = vram[(base + tile * 8 + y) & 0x7FFF]
            for x in range(8):
                v = ((w >> (7 - x)) & 1) | (((w >> (15 - x)) & 1) << 1)
                if v:
                    # White mask: the renderer tints per context (dialogue,
                    # menus, damage numbers) instead of baking the menu palette.
                    px[cx + x, cy + y] = (255, 255, 255, 255)
                    any_pixel = True
        if any_pixel:
            filled += 1
    args.out.mkdir(parents=True, exist_ok=True)
    img.save(args.out / "font.png")
    (args.out / "font.json").write_text(json.dumps({
        "first": FIRST,
        "last": LAST,
        "cell": 8,
        "columns": cols,
        "filled": filled,
        "source": str(args.dump),
    }, indent=1))
    print(f"extract_font: {filled}/{count} glyphs non-empty -> "
          f"{args.out / 'font.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
