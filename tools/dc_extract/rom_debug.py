import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import Rom, compose_rom_metasprite  # noqa: E402

rom = Rom(Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc"))
obj, slots = rom.decompress_area_obj_vram(0)
data = rom.data
off = (0x8B & 0x7F) * 0x8000 + (0xD939 - 0x8000)
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

pal = struct.unpack_from("<16H", rom.data,
                         (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
cgram = [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8) for c in pal]
print("obj vram words", len(obj))
try:
    img = compose_rom_metasprite(obj, cgram, parts, 0, 1)
    print("ok", None if img is None else img.size)
except Exception:  # noqa: BLE001
    traceback.print_exc()
