#!/usr/bin/env python3
"""Rebuild a room's BG atlases from an oracle capture, at the guest's CHR base.

The per-area atlases baked from ROM CHR leave whole regions blank in some rooms
(the colosseum's BG1 references palette-7 tile 15 in 674 cells and that tile is
empty in the segment-based atlas), which shows up as solid black rectangles where
the guest draws wall.

This bakes the atlas from the VRAM of a capture of that exact room, using the CHR
base the guest had loaded (`bgTileAdr`), so every tile the tilemap can address is
present.

Usage:
  python3 tools/dc_extract/bake_bg_atlas_from_capture.py \
      --dump captures/rooms/somulo_fight_starts --frame f003511 \
      --area 0 --pals 4,5,6,7 --out assets/generated
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))
from extract import cgram_colors, make_bg_atlas  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--frame", default=None, help="f003511 prefix; default newest")
    ap.add_argument("--area", type=int, required=True)
    ap.add_argument("--snes-bg", type=int, default=1)
    ap.add_argument("--pals", default="0,1,2,3,4,5,6,7")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    args = ap.parse_args()

    frame = args.frame
    if frame is None:
        cands = sorted(p.name[:-len(".vram.bin")] for p in args.dump.glob("f*.vram.bin"))
        if not cands:
            raise SystemExit(f"no f*.vram.bin in {args.dump}")
        frame = cands[-1]

    raw = (args.dump / f"{frame}.vram.bin").read_bytes()
    vram = list(struct.unpack(f"<{len(raw) // 2}H", raw))

    # `captures/area<N>/` (the force-loaded rooms) keep cgram and ppu inside the
    # frame JSON instead of beside the dump, so accept both layouts.
    state = {}
    state_path = args.dump / f"{frame}.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text())

    cgram_path = args.dump / "cgram.bin"
    if cgram_path.is_file():
        cgram = cgram_colors(cgram_path.read_bytes())
    elif state.get("cgram"):
        cgram = cgram_colors(bytes.fromhex(state["cgram"]))
    else:
        raise SystemExit(f"no cgram in {args.dump}")

    ppu_path = args.dump / "ppu.json"
    if ppu_path.is_file():
        ppu = json.loads(ppu_path.read_text())
    elif state.get("ppu"):
        ppu = state["ppu"]
    else:
        raise SystemExit(f"no ppu state in {args.dump}")
    if isinstance(ppu, dict) and "ppu" in ppu:
        ppu = ppu["ppu"]

    tile_adr = int(str(ppu.get("bgTileAdr", "0x0500")), 16)
    nib = (tile_adr & 0x0F) if args.snes_bg in (1, 3) else ((tile_adr >> 4) & 0x0F)
    base_word = (nib << 11) & 0x7FFF
    print(f"BG{args.snes_bg}: bgTileAdr 0x{tile_adr:04x} -> chr base word 0x{base_word:04x}")

    pals = [int(p) for p in args.pals.split(",") if p.strip()]
    for pal in pals:
        img = make_bg_atlas(vram, cgram, pal, base_word)
        path = args.out / f"bg_area{args.area}_pal{pal}.png"
        img.save(path)
        print(f"  wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
