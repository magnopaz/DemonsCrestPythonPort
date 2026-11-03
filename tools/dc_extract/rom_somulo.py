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
addr = 0xD939
off = (0x8B & 0x7F) * 0x8000 + (addr - 0x8000)
n = data[off]


def s8(v):
    return v - 256 if v >= 128 else v


parts = []
p = off + 1
for _ in range(n):
    dx, dxf, dy, tile, attr = (data[p], data[p + 1], data[p + 2],
                               data[p + 3], data[p + 4])
    parts.append({"dx": s8(dx), "dx_flip": s8(dxf), "dy": s8(dy),
                  "tile": tile, "attr": attr,
                  "size": 16 if (attr & 0x10) else 8,
                  "hflip": bool(attr & 0x40), "vflip": bool(attr & 0x80)})
    p += 5
tiles = sorted({x["tile"] for x in parts})
print("nparts", n, "tiles min/max", tiles[0], tiles[-1], "n distinct", len(tiles))

pal = struct.unpack_from("<16H", rom.data,
                         (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
cgram = [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8) for c in pal]

for base in (0x00, 0x60, 0xC0, 0x100, 0x126):
    try:
        img = compose_rom_metasprite(obj, cgram, parts, base, 1)
    except Exception as exc:  # noqa: BLE001
        print(f"base {base:03X}: {type(exc).__name__}: {exc}")
        continue
    if img is None:
        print(f"base {base:03X}: None")
        continue
    dest = OUT / f"rom_somulo_{base:03X}.png"
    img.save(dest)
    print(f"base {base:03X}: {img.size} -> {dest.name}")
