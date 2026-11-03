#!/usr/bin/env python3
"""Check that a probe's live room matches our extracted room JSON.

The live BG1 is a 32x32 screen-sized map; our room JSON is the whole room. So we
slide a 32x32 window across the room's tilemap and report the best match. A high
best match means `$008D` really is the grid index we assume and the room mapping
is sound; a low best match means the save was in a different room.

Usage:
  python tools/check_room_mapping.py --probes <...>/oracle_probe \
      --rooms assets/generated --saves lvl_II_ruined-city-dark-avenue,...
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

W = 32
H = 32


def live_screen(vram_words: list[int], bgsc0: int) -> tuple[list[int], int]:
    """Return the live 32x32 BG1 screen and its map width in tiles."""
    base = (bgsc0 & 0xFC) << 8
    map_size = (bgsc0 >> 4) & 3  # 0: 32x32, 1: 64x32, 2: 32x64, 3: 64x64
    width = 64 if map_size in (1, 3) else 32
    words = [vram_words[(base + i) & 0x7FFF] for i in range(width * H)]
    return words, width


def best_window(room: list[int], room_w: int, live: list[int],
                live_w: int) -> tuple[float, int]:
    best = (0.0, 0)
    for off in range(0, max(1, room_w - W + 1)):
        same = 0
        for y in range(H):
            for x in range(W):
                lx = x if live_w == W else (x if x < W else x - W)
                if room[y * room_w + off + x] == live[y * live_w + lx]:
                    same += 1
        ratio = same / (W * H)
        if ratio > best[0]:
            best = (ratio, off)
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes", type=Path, required=True)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--saves", required=True)
    args = ap.parse_args()

    for name in [s.strip() for s in args.saves.split(",") if s.strip()]:
        probe = args.probes / name
        if not (probe / "info.json").is_file():
            print(f"skip {name}: no probe")
            continue
        info = json.loads((probe / "info.json").read_text())
        ppu = json.loads((probe / "ppu.json").read_text())
        body = ppu.get("ppu", ppu)
        bgsc = body.get("bgXsc", [0, 0, 0, 0])
        bgsc0 = int(str(bgsc[0]), 16) if isinstance(bgsc[0], str) else int(bgsc[0])
        raw = (probe / "vram.bin").read_bytes()
        vram = list(struct.unpack("<%dH" % (len(raw) // 2), raw))
        live, live_w = live_screen(vram, bgsc0)

        area = int(info["area"])
        room_path = args.rooms / f"room_area{area}.json"
        if not room_path.is_file():
            print(f"{name}: no room_area{area}.json")
            continue
        room = json.loads(room_path.read_text())
        layer = next((b for b in room.get("bg", []) if b.get("name") == "bg1"),
                     None)
        if not layer:
            print(f"{name}: area {area} has no bg1")
            continue
        room_w = int(layer.get("map_width") or 32)
        ratio, off = best_window(layer["tilemap"], room_w, live, live_w)
        verdict = "OK" if ratio >= 0.80 else ("partial" if ratio >= 0.4 else "MISMATCH")
        print(f"{name}: area {area} best {ratio:.1%} at column {off} "
              f"(room {room_w} tiles wide) -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
