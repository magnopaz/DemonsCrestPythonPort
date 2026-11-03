#!/usr/bin/env python3
"""Fill a room's empty BG1 cells from oracle captures of that same room.

Some rooms only get the screens the reference capture covered, so most of their
grid is zero and they render as a black band under the HUD (areas 43, 42, 30,
29).  Their atlases are complete — the *tilemap* is the gap.

Positioning: the guest's BG1 scroll register is the camera position in world
space, so `round(hscroll / 8)` lands the capture inside the room's grid.  A
±N-tile search around that value picks the exact offset (the scroll is
pixel-granular).  Correlation over the whole grid is kept only as a fallback,
because it is ambiguous when most of the room is empty.

Safety: only empty cells are written, and a cell is filled only when its
non-empty neighbours in the room already agree with the capture — a locally
consistent window is trusted, an isolated mismatch is not.  A wrong tile is
worse than a black one.

Usage:
  python3 tools/oracle/merge_capture_bg1.py --area 43 --capture captures/tour43
  python3 tools/oracle/merge_capture_bg1.py --area 43 --capture captures/tour43 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))
from extract import tilemap_linear  # noqa: E402

MASK = 0x1FFF  # priority/flip bits are rewritten by the guest on load


def iter_capture_frames(capture_dir: Path, frame: int | None):
    """Yield (w, h, tiles, frame, hscroll, vscroll) for every dumped frame."""
    if frame is not None:
        frames = [frame]
    else:
        frames = sorted(int(p.name[1:7]) for p in capture_dir.glob("f*.vram.bin"))
    for n in frames:
        vram_path = capture_dir / f"f{n:06d}.vram.bin"
        state_path = capture_dir / f"f{n:06d}.json"
        if not vram_path.is_file() or not state_path.is_file():
            continue
        state = json.loads(state_path.read_text())
        ppu = state["ppu"]
        raw = vram_path.read_bytes()
        vram = [int.from_bytes(raw[i * 2:i * 2 + 2], "little") for i in range(0x8000)]
        bgsc = ppu["bgXsc"]
        if isinstance(bgsc, (list, tuple)):
            bgsc = bgsc[0]
        bgsc = int(bgsc, 16) if isinstance(bgsc, str) else int(bgsc)
        w, h, tiles = tilemap_linear(vram, bgsc)
        yield (w, h, tiles, n, int(ppu["hScroll"][0]), int(ppu["vScroll"][0]))


def agreement(tiles, W, H, cap, cap_w, cap_h, ox, oy):
    agree = total = 0
    for y in range(cap_h):
        ty = oy + y
        if ty < 0 or ty >= H:
            continue
        for x in range(cap_w):
            tx = ox + x
            if tx < 0 or tx >= W:
                continue
            a = tiles[ty * W + tx]
            b = cap[y * cap_w + x]
            if a and b:
                total += 1
                if (a & MASK) == (b & MASK):
                    agree += 1
    return agree, total


def local_support(tiles, W, H, cap, cap_w, cap_h, ox, oy, x, y) -> bool:
    """True when at least two orthogonal neighbours agree with the capture."""
    hit = 0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if nx < 0 or ny < 0 or nx >= cap_w or ny >= cap_h:
            continue
        ty, tx = oy + ny, ox + nx
        if ty < 0 or ty >= H or tx < 0 or tx >= W:
            continue
        a = tiles[ty * W + tx]
        b = cap[ny * cap_w + nx]
        if a and b and (a & MASK) == (b & MASK):
            hit += 1
    return hit >= 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--area", type=int, required=True)
    ap.add_argument("--capture", type=Path, action="append", required=True,
                    help="capture dir; repeat to merge several tours")
    ap.add_argument("--rooms", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--min-overlap", type=int, default=24,
                    help="agreeing cells required before a window is trusted")
    ap.add_argument("--search", type=int, default=3,
                    help="tiles searched around round(scroll/8)")
    ap.add_argument("--no-support-check", action="store_true",
                    help="fill every empty cell (unsafe: no neighbour guard)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    room_path = args.rooms / f"room_area{args.area}.json"
    doc = json.loads(room_path.read_text())
    bg1 = [b for b in doc["bg"] if b["name"] == "bg1"][0]
    W, H, tiles = bg1["map_width"], bg1["map_height"], bg1["tilemap"]

    total_filled = 0
    for cap_path in args.capture:
        for cap_w, cap_h, cap, frame, hs, vs in iter_capture_frames(cap_path, args.frame):
            cx = int(round(hs / 8.0))
            cy = int(round(vs / 8.0))
            best = (0, 0, 0, 0)  # agree, ox, oy, total
            for oy in range(cy - args.search, cy + args.search + 1):
                for ox in range(cx - args.search, cx + args.search + 1):
                    agree, total = agreement(tiles, W, H, cap, cap_w, cap_h, ox, oy)
                    if agree > best[0]:
                        best = (agree, ox, oy, total)
            agree, ox, oy, total = best
            if agree < args.min_overlap:
                print(f"area {args.area}: frame {frame} skipped "
                      f"({agree} < {args.min_overlap})")
                continue

            filled = 0
            for y in range(cap_h):
                for x in range(cap_w):
                    ty, tx = oy + y, ox + x
                    if ty < 0 or ty >= H or tx < 0 or tx >= W:
                        continue
                    idx = ty * W + tx
                    word = cap[y * cap_w + x]
                    if (tiles[idx] & 0x3FF) or not (word & 0x3FF):
                        continue
                    if not args.no_support_check and not local_support(
                            tiles, W, H, cap, cap_w, cap_h, ox, oy, x, y):
                        continue
                    tiles[idx] = word
                    filled += 1
            total_filled += filled
            print(f"area {args.area}: frame {frame} at ({ox},{oy}) "
                  f"agree={agree}/{total} filled={filled}")

    count = sum(1 for t in tiles if t & 0x3FF)
    print(f"area {args.area}: filled {total_filled} cells "
          f"({count}/{W * H} non-zero, {count / (W * H):.0%})")
    if not args.dry_run and total_filled:
        room_path.write_text(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
