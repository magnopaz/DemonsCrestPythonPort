"""Hunt for the ROM's species -> animation-frame table.

The notes say species $67's init writes $8B-bank frame pointers ($DE7B/$DE6C/$DE87)
into object fields $28/$2A/$2E. If those come from a table indexed by species,
scanning the ROM for a word at index $67 equal to one of those values will find it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "dc_extract"))

from extract import Rom  # noqa: E402

ROM_PATH = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
TARGETS = (0xDE7B, 0xDE6C, 0xDE87, 0xDE87 & 0x7FFF)


def main() -> int:
    rom = Rom(ROM_PATH)
    data = rom.data
    print("rom size", len(data))
    hits = []
    # A candidate table: 16-bit little-endian words where index $67 is one of the
    # known pointers. Scan every bank, every alignment.
    for bank in range(0x80, 0x100):
        base = (bank & 0x7F) * 0x8000
        if base + 0x8000 > len(data):
            continue
        for off in range(0, 0x8000 - 0x70 * 2, 2):
            idx = base + off + 0x67 * 2
            w = data[idx] | (data[idx + 1] << 8)
            if w not in TARGETS:
                continue
            hits.append((bank, off, w))
    print("candidates:", len(hits))
    for bank, off, w in hits[:40]:
        print(f"  bank {bank:02X} offset {off:04X} (cpu {bank:02X}:{0x8000 + off:04X}) "
              f"word[67]={w:04X}")
        # show a few neighbouring entries to judge whether it is a pointer table
        base = (bank & 0x7F) * 0x8000 + off
        words = []
        for i in (0x00, 0x01, 0x02, 0x03, 0x07, 0x09, 0x13, 0x26, 0x2C, 0x33, 0x67):
            p = base + i * 2
            if p + 1 < len(data):
                words.append((hex(i), f"{(data[p] | (data[p + 1] << 8)):04X}"))
        print("     ", words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
