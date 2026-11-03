import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import Rom, compose_rom_metasprite  # noqa: E402

OUT = Path(r"C:\Users\magno\OneDrive\Documentos\deepseek-harness"
           r"\default-workspace\dcbuild\out")
rom = Rom(Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc"))
obj, slots = rom.decompress_area_obj_vram(0)
data = rom.data


def s8(v):
    return v - 256 if v >= 128 else v


base_words = struct.unpack_from("<16H", rom.data,
                                (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
cgram = [(0, 0, 0)] * 256
for pal in range(8):
    for i, c in enumerate(base_words):
        cgram[0x80 + pal * 16 + i] = ((c & 31) * 8, ((c >> 5) & 31) * 8,
                                      ((c >> 10) & 31) * 8)


def parse_order(addr: int, order: str, stride: int):
    off = (0x8B & 0x7F) * 0x8000 + (addr - 0x8000)
    n = data[off]
    parts = []
    p = off + 1
    for _ in range(n):
        a, b, c, d, e = (data[p], data[p + 1], data[p + 2], data[p + 3],
                         data[p + 4])
        if order == "dxy_tile_attr":
            dx, dy, tile, attr = s8(a), s8(b), c, d
        else:  # dx, flip, dy, tile, attr (the group format)
            dx, dy, tile, attr = s8(a), s8(c), d, e
        parts.append({"dx": dx, "dy": dy, "tile": tile, "attr": attr,
                      "size": 16 if (attr & 0x10) else 8,
                      "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80),
                      "dx_flip": 0})
        p += stride
    return n, parts


for addr in (0xD939, 0xD93D):
    for order in ("dxy_tile_attr", "group"):
        n, parts = parse_order(addr, order, 5)
        img = compose_rom_metasprite(obj, cgram, parts, 0, 1)
        tag = f"{addr:04X}_{order}"
        if img is None:
            print(tag, "empty")
            continue
        dest = OUT / f"romtest_{tag}.png"
        img.save(dest)
        print(tag, img.size, "->", dest.name)
