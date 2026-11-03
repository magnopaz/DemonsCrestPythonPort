#!/usr/bin/env python3
"""Cut a boss sprite out of a user screenshot.

The reference screenshots are the only clean view of bosses whose OAM parts we
cannot attribute. The colosseum background is purple/violet, so a colour rule can
separate the dragon (gold body, bone-grey ribs) from it: a pixel is background
when blue dominates red and green, or when it is nearly black.

Usage:
  python tools/dc_extract/boss_from_screenshot.py \
      --image somulo_here_the_battle_starts.png --out assets/generated/boss_33.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

W, H = 256, 224


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep-largest", action="store_true", default=True)
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    # Screenshots are an integer-ish upscale of the 256x224 frame; sample back
    # down so the sprite lands on the console pixel grid.
    scale = img.width / W
    small = img.resize((W, H), Image.LANCZOS)
    px = small.load()

    mask = Image.new("L", (W, H), 0)
    mpx = mask.load()
    for y in range(H):
        for x in range(W):
            r, g, b = px[x, y]
            dark = r + g + b < 45
            purple = b > r + 18 and b > g + 18
            if not dark and not purple:
                mpx[x, y] = 255
    # Close small holes in the body (ribs/background showing through).
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(
        ImageFilter.MinFilter(3))

    # Largest connected component.
    seen = bytearray(W * H)
    best = None
    for y in range(H):
        for x in range(W):
            if seen[y * W + x] or not mpx[x, y]:
                continue
            stack = [(x, y)]
            seen[y * W + x] = 1
            pts = []
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1),
                               (cx, cy - 1)):
                    if 0 <= nx < W and 0 <= ny < H and not seen[ny * W + nx] \
                            and mpx[nx, ny]:
                        seen[ny * W + nx] = 1
                        stack.append((nx, ny))
            if best is None or len(pts) > len(best):
                best = pts
    if not best:
        raise SystemExit("no boss-shaped region found")
    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    x0, y0 = max(0, min(xs) - 1), max(0, min(ys) - 1)
    x1, y1 = min(W, max(xs) + 2), min(H, max(ys) + 2)
    print(f"boss region {x1 - x0}x{y1 - y0} at ({x0},{y0}), "
          f"scale {scale:.2f}")

    out = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    opx = out.load()
    keep = set(best)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x, y) in keep:
                r, g, b = px[x, y]
                opx[x - x0, y - y0] = (r, g, b, 255)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    filled = sum(1 for p in out.getdata() if p[3])
    print(f"wrote {args.out} {out.size} filled={filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
