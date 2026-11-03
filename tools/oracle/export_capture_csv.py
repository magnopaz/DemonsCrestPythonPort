#!/usr/bin/env python3
"""Export a player-position CSV from a capture_anim.py output directory.

capture_anim.py stores one JSON snapshot per guest frame, including the
$1000 player task and the low zero page. This tool turns those snapshots into
the same CSV shape as parse_wram_trace.py so the result can be fed directly to
compare.py:

  frame,frame_rel,area,player_x,player_y,screen_x,screen_y,cam_x,cam_y

player_x/player_y are the 24-bit 8.8 world positions at $1030/$1033; the
camera comes from $00C0/$00C4. The $1000 Y value oscillates by up to one pixel
during idle (see PROJECT_STATE trap #8), so use the same 1 px acceptance
threshold that the oracle comparison documents.

Usage:
  python3 tools/oracle/export_capture_csv.py captures/anim_phys \
      -o /tmp/oracle_phys.csv
  python3 tools/oracle/compare.py /tmp/native.csv /tmp/oracle_phys.csv \
      --oracle-start 0 --threshold 1.0
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def u16(buf: bytes, addr: int) -> int:
    return buf[addr] | (buf[addr + 1] << 8)


def u24(buf: bytes, addr: int) -> int:
    return buf[addr] | (buf[addr + 1] << 8) | (buf[addr + 2] << 16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path,
                    help="capture_anim.py output directory (contains f*.json)")
    ap.add_argument("-o", "--out", type=Path, required=True,
                    help="output CSV path")
    ap.add_argument("--start-frame", type=int, default=None,
                    help="first guest frame in frame_rel (default: first capture)")
    args = ap.parse_args()

    paths = sorted(args.capture.glob("f*.json"))
    if not paths:
        print(f"export: no f*.json frames in {args.capture}", file=sys.stderr)
        return 1

    frames: list[tuple[int, bytes, bytes]] = []
    for path in paths:
        state = json.loads(path.read_text())
        frame = int(state["frame"])
        frames.append((frame,
                       bytes.fromhex(state["wram_1000"]),
                       bytes.fromhex(state["zeropage"])))
    frames.sort()
    start = args.start_frame if args.start_frame is not None else frames[0][0]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["frame", "frame_rel", "area", "player_x", "player_y",
                    "screen_x", "screen_y", "cam_x", "cam_y"])
        for frame, wram, zp in frames:
            x = u24(wram, 0x1030 - 0x1000) / 256.0
            y = u24(wram, 0x1033 - 0x1000) / 256.0
            cam_x = u16(zp, 0x00C0)
            cam_y = u16(zp, 0x00C4)
            w.writerow([frame, frame - start, zp[0x008D],
                        f"{x:.3f}", f"{y:.3f}",
                        f"{x - cam_x:.3f}", f"{y - cam_y:.3f}",
                        cam_x, cam_y])
    print(f"export: wrote {len(frames)} frames from {args.capture} to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
