#!/usr/bin/env python3
"""Reconstruct Firebrand's sprite rectangle per frame from a recomp WRAM trace.

The OAM buffer lives in low WRAM at $0700 (512-byte low table) and $0900
(32-byte high table). The recomp's SNESRECOMP_WRAM_TRACE_FILE logs every changed
byte of low WRAM, so the parser can reconstruct the OAM image for every frame.

The player is the OAM group using sprite palette 7 in this game. Its slot range
changes as effects are allocated, so filtering by palette is more robust than
tracking fixed slots.

Usage:
  python3 tools/oracle/parse_player_trace.py trace.jsonl -o player.csv --area 2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Low OAM table + high OAM table.
OAM_LO = 0x0700
OAM_HI = 0x0900
OAM_SIZE = 0x220

TRACK = set(range(OAM_LO, OAM_LO + 0x200)) | set(range(OAM_HI, OAM_HI + 0x20))
TRACK |= {0x0008D, 0x00090, 0x00091,
          0x000C0, 0x000C1, 0x000C2, 0x000C3,
          0x000C4, 0x000C5, 0x000C6, 0x000C7}

# Reuse the OAM parser from the extractor.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dc_extract"))
import extract as dc  # noqa: E402


def u16(v: dict[int, int], lo: int) -> int:
    return v[lo] | (v[lo + 1] << 8)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--area", type=int, default=2)
    ap.add_argument("--obsel", type=int, default=3,
                    help="OBSEL for the OAM size table (default 3 for this game)")
    args = ap.parse_args()

    changes: dict[int, list[tuple[int, int]]] = defaultdict(list)
    max_frame = 0
    area_frame: int | None = None

    with args.trace.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                frame = int(rec["f"])
                addr = int(rec["adr"], 16)
                val = int(rec["val"], 16)
            except (ValueError, KeyError, TypeError):
                continue
            if frame > max_frame:
                max_frame = frame
            if addr not in TRACK:
                continue
            changes[frame].append((addr, val))
            if addr == 0x0008D and val == args.area and area_frame is None:
                area_frame = frame

    if area_frame is None:
        print(f"parse: area {args.area} never became active", file=sys.stderr)
        area_frame = 1

    values = {addr: 0 for addr in TRACK}
    for addr, val in changes.get(1, []):
        values[addr] = val

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as out:
        out.write("frame,frame_rel,screen_x,screen_y,w,h,scroll_x,scroll_y,"
                  "player_x,player_y,area\n")
        for frame in range(area_frame, max_frame + 1):
            frame_changes = changes.get(frame)
            if frame_changes:
                for addr, val in frame_changes:
                    values[addr] = val

            oam = bytes(values[OAM_LO + i] for i in range(0x200))
            oam += bytes(values[OAM_HI + i] for i in range(0x20))
            sprites = dc.parse_oam(oam, args.obsel)
            player = [s for s in sprites if s.palette == 7 and s.y < 224]
            if not player:
                continue
            min_x = min(s.x for s in player)
            min_y = min(s.y for s in player)
            max_x = max(s.x + s.size for s in player)
            max_y = max(s.y + s.size for s in player)
            sx, sy = u16(values, 0x00C0), u16(values, 0x00C4)
            center_x = (min_x + max_x) / 2.0
            feet_y = float(max_y)
            out.write(f"{frame},{frame - area_frame},{center_x},{feet_y},"
                      f"{max_x - min_x},{max_y - min_y},{sx},{sy},"
                      f"{center_x + sx},{feet_y + sy},{values[0x0008D]}\n")

    print(f"parse: area {args.area} starts at frame {area_frame}, "
          f"max frame {max_frame}, wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
