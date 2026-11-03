"""Decode a ROM metasprite frame pointer and compose its sprite.

The object init code writes $8B-bank pointers (e.g. $DE87 for species $67) into
object fields $28/$2A/$2E. A frame pointer is a part list: nparts, then 5 bytes
per part (dx, dxflip, dy, tile, attr) - the same part format $80:D9A7 uses.

Usage:
  python tools/dc_extract/rom_frame.py 0xDE87 [0xDE7B ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract import Rom, compose_rom_metasprite  # noqa: E402

ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
OUT = Path(r"C:\Users\magno\OneDrive\Documentos\deepseek-harness"
           r"\default-workspace\dcbuild\out\rom_frames")


def s8(v: int) -> int:
    return v - 256 if v >= 128 else v


def read_frame(rom: Rom, bank: int, addr: int, max_parts: int = 24):
    """Read one part list starting at bank:addr."""
    data = rom.data
    off = (bank & 0x7F) * 0x8000 + (addr - 0x8000)
    nparts = data[off]
    parts = []
    p = off + 1
    for _ in range(min(nparts, max_parts)):
        dx, dxf, dy, tile, attr = (data[p], data[p + 1], data[p + 2],
                                   data[p + 3], data[p + 4])
        parts.append({
            "dx": s8(dx), "dx_flip": s8(dxf), "dy": s8(dy),
            "tile": tile, "attr": attr,
            "size": 16 if (attr & 0x10) else 8,
            "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80),
        })
        p += 5
    return nparts, parts


def main(args: list[str]) -> int:
    rom = Rom(ROM)
    obj_vram, _slots = rom.decompress_area_obj_vram(0)
    item_cgram = rom.area_bg_cgram(0)
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in args:
        addr = int(arg, 16)
        n, parts = read_frame(rom, 0x8B, addr)
        print(f"$8B:{addr:04X}: nparts={n}")
        for i, part in enumerate(parts[:8]):
            print(f"   {i}: dx={part['dx']:4d} dy={part['dy']:4d} "
                  f"tile={part['tile']:3d} attr={part['attr']:02X} "
                  f"size={part['size']} hflip={part['hflip']}")
        if not parts or n == 0 or n > 24:
            print("   (not a plausible frame)")
            continue
        try:
            img, _, _ = compose_rom_metasprite(obj_vram, item_cgram, parts)
        except SystemExit as exc:
            print("   compose failed:", exc)
            continue
        dest = OUT / f"frame_{addr:04X}.png"
        img.save(dest)
        print("   ->", dest, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["0xDE87", "0xDE7B", "0xDE6C"]))
