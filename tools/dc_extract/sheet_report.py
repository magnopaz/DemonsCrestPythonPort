#!/usr/bin/env python3
"""Print the measured layout of a labelled sheet (rows, captions, poses).

This is the measuring step of ``docs/SPRITE_SHEET_EXTRACTION.md`` turned into
a tool: it lists the caption words as ASCII art (the captions are a tiny
bitmap font, so this is how a human reads them without OCR), the row bands,
and every pose with its measured box and the caption it sits under.

Examples::

  python tools/dc_extract/sheet_report.py --sheet Arma
  python tools/dc_extract/sheet_report.py --sheet Belth --bands
  python tools/dc_extract/sheet_report.py --sheet Arma --caps-y 30:60
  python tools/dc_extract/sheet_report.py --sheet Crawler --map
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from sheet_lib import analyse, is_bg  # noqa: E402


def print_map(info, cell: int) -> None:
    """Coarse ASCII map: one character per ``cell`` x ``cell`` block."""
    im, bg = info.image, info.bg
    w, h = im.size
    px = im.load()
    print(f"# map of {info.path.name}, 1 char = {cell}px")
    header = "     "
    for x in range(0, w, cell):
        header += str((x // 100) % 10) if x % 100 == 0 else " "
    print(header)
    for y0 in range(0, h, cell):
        row = []
        for x0 in range(0, w, cell):
            ink = 0
            total = 0
            for y in range(y0, min(y0 + cell, h)):
                for x in range(x0, min(x0 + cell, w)):
                    total += 1
                    if not is_bg(px[x, y], bg):
                        ink += 1
            frac = ink / max(1, total)
            row.append("#" if frac > 0.45 else
                       "+" if frac > 0.12 else
                       "'" if frac > 0 else " ")
        print(f"{y0:4d} " + "".join(row))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--bands", action="store_true", help="print rows/poses")
    ap.add_argument("--caps", action="store_true", help="print caption art")
    ap.add_argument("--caps-y", default=None,
                    help="only captions whose top is in Y0:Y1")
    ap.add_argument("--map", action="store_true", help="coarse sheet map")
    ap.add_argument("--cell", type=int, default=8)
    ap.add_argument("--no-ascii", action="store_true")
    ap.add_argument("--min-word-width", type=int, default=8,
                    help="ignore caption words narrower than this")
    ap.add_argument("--min-area", type=int, default=0,
                    help="hide poses smaller than this")
    args = ap.parse_args()
    info = analyse(args.sheet)
    print(f"# {info.path.name}  size={info.size}  bg={info.bg}")
    print(f"# components={len(info.components)} words={len(info.captions)} "
          f"bands={len(info.bands)}")
    if args.map:
        print_map(info, args.cell)
    want_caps = args.caps or not (args.bands or args.map)
    if want_caps:
        lo, hi = -10_000, 10_000
        if args.caps_y:
            lo, hi = (int(v) for v in args.caps_y.split(":"))
        print("\n## captions")
        for i, cap in enumerate(info.captions):
            if not (lo <= cap.y0 <= hi):
                continue
            if cap.x1 - cap.x0 + 1 < args.min_word_width:
                continue
            print(f"[{i:02d}] box=({cap.x0},{cap.y0})-({cap.x1},{cap.y1}) "
                  f"w={cap.x1 - cap.x0 + 1} cx={cap.cx:.0f}")
            if not args.no_ascii:
                for line in cap.art(info.image, info.bg).splitlines():
                    print("     " + line)
    if args.bands:
        print("\n## bands")
        for b, band in enumerate(info.bands):
            labels = ", ".join(f"[{i}]" for i in
                               (info.captions.index(c) for c in band.labels))
            print(f"\nband {b}: y={band.y0}..{band.y1} poses={len(band.poses)} "
                  f"labels={labels}")
            for p, pose in enumerate(band.poses):
                area = (pose.x1 - pose.x0 + 1) * (pose.y1 - pose.y0 + 1)
                if area < args.min_area:
                    continue
                lab = band.label_for(pose)
                tag = f"cap[{info.captions.index(lab)}]" if lab else "--"
                print(f"  pose {p:02d} box=({pose.x0},{pose.y0})"
                      f"-({pose.x1},{pose.y1}) "
                      f"size={pose.x1 - pose.x0 + 1}x{pose.y1 - pose.y0 + 1}"
                      f" cx={pose.cx:.0f} {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
