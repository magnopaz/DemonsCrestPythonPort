#!/usr/bin/env python3
"""Render a sheet's caption lines as one readable strip image.

The community sheets label each animation row with a tiny bitmap caption.
This tool finds the caption lines (the rows that only contain glyph-sized
blobs), crops each one at full width, scales it up with nearest-neighbour and
stacks the strips into a single PNG whose left margin prints the original y
range of every strip.  A person (or an image model) can then read the whole
sheet's vocabulary in one glance, and the numbers map straight back to
``sheet_report.py`` coordinates.

Usage::

  python tools/dc_extract/sheet_captions.py --sheet Arma \
      --out captures/arma_captions.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from sheet_lib import analyse  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--min-width", type=int, default=8,
                    help="ignore words narrower than this")
    ap.add_argument("--chunk", type=int, default=420,
                    help="split each strip into horizontal chunks of this "
                         "many original pixels (keeps the image readable)")
    args = ap.parse_args()
    info = analyse(args.sheet)
    words = [w for w in info.captions
             if w.x1 - w.x0 + 1 >= args.min_width]
    if not words:
        print("no caption words found", file=sys.stderr)
        return 1
    # One strip per caption line (group words whose vertical spans overlap).
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w.y0, w.x0)):
        for line in lines:
            if w.y0 <= max(x.y1 for x in line) + 2 and \
                    w.y1 >= min(x.y0 for x in line) - 2:
                line.append(w)
                break
        else:
            lines.append([w])
    strips = []
    for line in lines:
        y0 = min(w.y0 for w in line) - 1
        y1 = max(w.y1 for w in line) + 1
        for x0 in range(0, info.image.width, args.chunk):
            x1 = min(x0 + args.chunk, info.image.width)
            crop = info.image.crop((x0, y0, x1, y1 + 1))
            strips.append((x0, y0, y1, crop))
    margin = 130
    width = margin + min(args.chunk, info.image.width) * args.scale
    height = sum((s[3].height + 2) * args.scale for s in strips) + 8 * len(strips)
    out = Image.new("RGB", (width, height), (20, 20, 28))
    draw = ImageDraw.Draw(out)
    y = 0
    for x0, y0, y1, crop in strips:
        big = crop.resize((crop.width * args.scale, crop.height * args.scale),
                          Image.NEAREST)
        out.paste(big, (margin, y))
        draw.text((4, y + 4), f"y={y0}..{y1}", fill=(255, 255, 120))
        draw.text((4, y + 18), f"x={x0}..", fill=(120, 255, 120))
        y += big.height + 8
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    print(f"{args.out}  {out.size}  {len(strips)} caption lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
