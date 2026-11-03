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


pal = struct.unpack_from("<16H", rom.data,
                         (0x99 & 0x7F) * 0x8000 + (0xA900 - 0x8000))
cgram = [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8) for c in pal]

for addr in (0xD939,):
    off = (0x8B & 0x7F) * 0x8000 + (addr - 0x8000)
    n = data[off]
    print(f"== ${addr:04X}: leading byte {n}")
    for stride in (4, 5):
        parts = []
        p = off + 1
        tile_max = 0
        for _ in range(min(n, 96)):
            if stride == 4:
                dx, dy, tile, attr = data[p], data[p + 1], data[p + 2], data[p + 3]
            else:
                dx, dy, tile, attr = (data[p], data[p + 2], data[p + 3],
                                      data[p + 4])
            parts.append({"dx": s8(dx), "dy": s8(dy), "tile": tile,
                          "attr": attr, "size": 16 if (attr & 0x10) else 8,
                          "hflip": bool(attr & 0x40),
                          "vflip": bool(attr & 0x80), "dx_flip": 0})
            tile_max = max(tile_max, tile)
            p += stride
        ok = None
        for base in (0x00, 0x60, 0xC0, 0x100, 0x126, 0x180):
            try:
                img = compose_rom_metasprite(obj, cgram, parts, base, 1)
            except Exception:  # noqa: BLE001
                continue
            if img is None:
                continue
            ok = (base, img)
            break
        print(f"   stride {stride}: {len(parts)} parts, max tile {tile_max}, "
              f"compose {'ok base 0x%03X' % ok[0] if ok else 'failed'}")
        if ok:
            dest = OUT / f"somulo_stride{stride}.png"
            ok[1].save(dest)
            print("      ->", dest.name, ok[1].size)
