import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import Rom  # noqa: E402

ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
rom = Rom(ROM)
d = rom.data


def dump(bank, addr, n, label):
    off = (bank & 0x7F) * 0x8000 + (addr - 0x8000)
    rows = []
    for i in range(0, n, 16):
        chunk = d[off + i:off + i + 16]
        rows.append(f"{addr + i:04X}: " + " ".join(f"{b:02X}" for b in chunk))
    print("==", label)
    print("\n".join(rows))


dump(0x83, 0xAE20, 0x60, "around AE20")
dump(0x83, 0xB1E0, 0x60, "around B1E0")
