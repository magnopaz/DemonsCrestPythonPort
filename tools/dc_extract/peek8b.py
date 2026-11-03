import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import Rom  # noqa: E402

rom = Rom(Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc"))
d = rom.data


def dump(addr, n=0x50):
    off = (0x8B & 0x7F) * 0x8000 + (addr - 0x8000)
    for i in range(0, n, 16):
        print(f"{addr + i:04X}: " + " ".join(f"{b:02X}" for b in d[off + i:off + i + 16]))


for a in (0xD939, 0xD93D, 0xD959, 0xD900):
    print(f"== {a:04X}")
    dump(a)
