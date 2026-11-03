"""Decode a ROM metasprite part list and compose it with the area's OBJ CHR.

The live object record gives the pointers ($8B bank) per species; this turns one
into a PNG so the ROM's own art can be compared with what the game shows.

Usage:
  python tools/dc_extract/rom_frame2.py <area> <addr_hex> [addr_hex ...]
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract import Rom, compose_rom_metasprite  # noqa: E402

ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
OUT = Path(r"C:\Users\magno\OneDrive\Documentos\deepseek-harness"
           r"\default-workspace\dcbuild\out\rom_frames")


def s8(v: int) -> int:
    return v - 256 if v >= 128 else v


def read_parts(rom: Rom, bank: int, addr: int, limit: int = 128):
    data = rom.data
    off = (bank & 0x7F) * 0x8000 + (addr - 0x8000)
    n = data[off]
    parts = []
    p = off + 1
    for _ in range(min(n, limit)):
        dx, dxf, dy, tile, attr = (data[p], data[p + 1], data[p + 2],
                                   data[p + 3], data[p + 4])
        parts.append({"dx": s8(dx), "dx_flip": s8(dxf), "dy": s8(dy),
                      "tile": tile, "attr": attr,
                      "size": 16 if (attr & 0x10) else 8,
                      "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80)})
        p += 5
    return n, parts


def main(argv: list[str]) -> int:
    area = int(argv[0], 0)
    rom = Rom(ROM)
    obj_vram, slots = rom.decompress_area_obj_vram(area)
    cgram = rom.gargoyle_palettes() if hasattr(rom, "gargoyle_palettes") else None
    # Area palettes: reuse the BG palette block the port uses for sprites.
    pal_words = struct.unpack_from("<16H", rom.data,
                                   (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
    cgram = [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
             for c in pal_words]
    print("slots:", {hex(k): hex(v) for k, v in list(slots.items())[:10]})
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in argv[1:]:
        addr = int(arg, 16)
        n, parts = read_parts(rom, 0x8B, addr)
        print(f"$8B:{addr:04X}: nparts={n}")
        for i, part in enumerate(parts[:6]):
            print(f"   {i}: dx={part['dx']:4d} dy={part['dy']:4d} "
                  f"tile={part['tile']:3d} attr={part['attr']:02X} "
                  f"size={part['size']}")
        if n == 0 or n > 128:
            print("   (not a plausible part list)")
            continue
        for base in sorted(set(list(slots.values()) + [0])):
            try:
                img, _, _ = compose_rom_metasprite(obj_vram, cgram, parts,
                                                   base, 1)
            except Exception as exc:  # noqa: BLE001
                continue
            if img is None:
                continue
            dest = OUT / f"area{area}_{addr:04X}_base{base:03X}.png"
            img.save(dest)
            print("   ->", dest.name, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["0", "0xD939"]))
