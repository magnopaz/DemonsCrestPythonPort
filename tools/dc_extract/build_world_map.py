#!/usr/bin/env python3
"""Bake the Mode 7 world map from a recomp capture into `world_map.png`.

Mode 7 layout (SNESdev wiki): the 128x128 tilemap is stored in the LOW byte of
the first 16384 VRAM words; tile pixels are chunky 8bpp in the HIGH byte, 64
pixels per tile (left→right, top→bottom). The result is a 1024x1024 image of the
whole Ghoul Realm.

Usage:
  python tools/dc_extract/build_world_map.py --capture captures/save11 \
      --frame 61 --out assets/generated/world_map.png
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import read_capture_frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, default=ROOT / "captures" / "save11")
    ap.add_argument("--frame", type=int, default=61)
    ap.add_argument("--vram", type=Path,
                    help="raw 64 KiB VRAM dump (default: capture frame)")
    ap.add_argument("--cgram", type=Path,
                    help="raw 512-byte CGRAM dump (default: capture frame)")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "assets" / "generated" / "world_map.png")
    args = ap.parse_args()
    if args.vram and args.cgram:
        vram = list(struct.unpack("<32768H", args.vram.read_bytes()))
        raw_cg = args.cgram.read_bytes()
        words = struct.unpack("<%dH" % (len(raw_cg) // 2), raw_cg)
        cgram = [((w & 31) * 8, ((w >> 5) & 31) * 8, ((w >> 10) & 31) * 8)
                 for w in words]
    else:
        vram, cgram, _regs = read_capture_frame(args.capture, args.frame)
    img = Image.new("RGB", (1024, 1024), (0, 0, 0))
    px = img.load()
    for ty in range(128):
        for tx in range(128):
            tile = vram[ty * 128 + tx] & 0xFF
            if tile == 0:
                continue
            for y in range(8):
                for x in range(8):
                    idx = (vram[(tile * 64 + y * 8 + x) & 0x7FFF] >> 8) & 0xFF
                    px[tx * 8 + x, ty * 8 + y] = cgram[idx]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"wrote {args.out} (1024x1024 world map)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
