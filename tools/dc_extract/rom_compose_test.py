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


# Full 256-entry CGRAM: the area's 16-word sprite palette copied into every
# sprite row so any palette index in a part resolves to real colours.
base_words = struct.unpack_from("<16H", rom.data,
                                (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
cgram = [(0, 0, 0)] * 256
for pal in range(8):
    for i, c in enumerate(base_words):
        cgram[0x80 + pal * 16 + i] = ((c & 31) * 8, ((c >> 5) & 31) * 8,
                                      ((c >> 10) & 31) * 8)


def frame_parts(addr, stride=5, lead=True):
    off = (0x8B & 0x7F) * 0x8000 + (addr - 0x8000)
    n = data[off] if lead else 0
    p = off + 1 if lead else off
    parts = []
    for _ in range(n):
        dx, dxf, dy, tile, attr = (data[p], data[p + 1], data[p + 2],
                                   data[p + 3], data[p + 4])
        parts.append({"dx": s8(dx), "dx_flip": s8(dxf), "dy": s8(dy),
                      "tile": tile, "attr": attr,
                      "size": 16 if (attr & 0x10) else 8,
                      "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80)})
        p += stride
    return n, parts


for addr in (0xD939, 0xD93D, 0xD959):
    n, parts = frame_parts(addr)
    print(f"$8B:{addr:04X} nparts={n}")
    img = compose_rom_metasprite(obj, cgram, parts, 0, 1)
    if img is None:
        print("   empty")
        continue
    dest = OUT / f"rom_frame_{addr:04X}.png"
    img.save(dest)
    print("   ->", dest.name, img.size)
