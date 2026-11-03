#!/usr/bin/env python3
"""Turn a recomp low-WRAM trace (SNESRECOMP_WRAM_TRACE_FILE) into a player CSV.

The recomp emits one JSONL line per changed byte:
  {"f":123,"adr":"0x01030","old":"0x00","val":"0x12"}

The Firebrand object used by the gameplay code lives at $1400. The fields that
matter here are the player position pair:

  $140C/$140D  world X, integer pixels
  $140E/$140F  world Y, integer pixels
  $1420-$1422  world X, 24-bit 8.8 fixed
  $1423-$1425  world Y, 24-bit 8.8 fixed
  $00C0/$00C1  BG1 scroll X (camera X)
  $00C4/$00C5  BG1 scroll Y (camera Y)

The trace only records changed bytes, so the parser reconstructs every frame.

Usage:
  python3 tools/oracle/parse_wram_trace.py trace.jsonl -o oracle.csv --area 2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Addresses of bytes we track. Values are reconstructed byte-by-byte.
TRACK = {
    0x0008D,                       # area
    0x00C0, 0x00C1, 0x00C2, 0x00C3,
    0x00C4, 0x00C5, 0x00C6, 0x00C7,
    0x1020, 0x1021, 0x1022, 0x1023,
    0x1030, 0x1031, 0x1032,
    0x1033, 0x1034, 0x1035,
}


def u16(v: dict[int, int], lo: int) -> int:
    return v[lo] | (v[lo + 1] << 8)


def u24(v: dict[int, int], lo: int) -> int:
    return v[lo] | (v[lo + 1] << 8) | (v[lo + 2] << 16)


def build(v: dict[int, int]) -> str:
    # Firebrand's task slot is $1000. Its position is 24-bit 8.8 fixed at
    # $1030 (X) and $1033 (Y); the low 16 bits alone are not the position.
    fx = u24(v, 0x1030) / 256.0
    fy = u24(v, 0x1033) / 256.0
    cam_x = u16(v, 0x00C0)
    cam_y = u16(v, 0x00C4)
    return (f"{fx:.3f},{fy:.3f},{fx - cam_x:.3f},{fy - cam_y:.3f},"
            f"{cam_x},{cam_y}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--area", type=int, default=2,
                    help="start the CSV at the first frame this area is active")
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
    for addr, val in changes.get(1, []):       # first frame dumps all bytes
        values[addr] = val

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as out:
        out.write("frame,frame_rel,area,player_x,player_y,screen_x,screen_y,cam_x,cam_y\n")
        for frame in range(area_frame, max_frame + 1):
            frame_changes = changes.get(frame)
            if frame_changes:
                for addr, val in frame_changes:
                    values[addr] = val
            out.write(f"{frame},{frame - area_frame},{values[0x0008D]},")
            out.write(build(values))

    print(f"parse: area {args.area} starts at frame {area_frame}, "
          f"max frame {max_frame}, wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
