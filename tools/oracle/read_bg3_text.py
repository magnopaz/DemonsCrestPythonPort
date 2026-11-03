#!/usr/bin/env python3
"""Read the dialogue text drawn on a probed save's BG3 layer.

The game uses BG3 with an ASCII-indexed font (tile index == ASCII code), so the
BG3 tilemap of a dialogue frame can be decoded back to text. This is how a
cutscene save maps to the extracted script entries.

Usage:
  python tools/oracle/read_bg3_text.py --probe <...>/oracle_probe/save8a
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dc_extract"))

MAP_W = 32
MAP_H = 32


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", type=Path, required=True)
    args = ap.parse_args()
    info = json.loads((args.probe / "info.json").read_text())
    ppu = json.loads((args.probe / "ppu.json").read_text())
    body = ppu.get("ppu", ppu)
    vram = list(struct.unpack("<32768H", (args.probe / "vram.bin").read_bytes()))
    bgsc = body.get("bgXsc", [0, 0, 0, 0])
    # BG3 map base: bits 2-7 of $2109 low byte (bgsc[2])
    reg = int(str(bgsc[2]), 16) if isinstance(bgsc[2], str) else int(bgsc[2])
    base = (reg & 0xFC) << 8
    print(f"{args.probe.name}: area {info['area']} BG3 map base {base:#06x}")
    for ty in range(MAP_H):
        row = ""
        for tx in range(MAP_W):
            word = vram[(base + ty * MAP_W + tx) & 0x7FFF]
            code = word & 0x3FF
            if 0x20 <= code <= 0x7E:
                row += chr(code)
            else:
                row += " "
        if row.strip():
            print(f"{ty:2d} |{row.rstrip()}|")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
