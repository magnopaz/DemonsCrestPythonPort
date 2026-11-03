#!/usr/bin/env python3
"""Prove which species frame a screenshot shows (sprite fingerprint match).

The port's animation bugs are invisible to the eye when every frame looks like
"a dragon", so this matches the screenshot against the baked PNGs pixel for
pixel: the frame that reproduces the on-screen sprite exactly (same colours at
the same offsets) is the frame the engine drew.

The engine mirrors a sprite when the object faces left and clips it at the
screen edges, so the matcher also tries the horizontally flipped texture and
only scores the pixels that are actually on screen.

Usage:
  python3 tools/verify_frame_match.py --shot /tmp/seq_260.png --count 8
  python3 tools/verify_frame_match.py --shot /tmp/seq_260.png --window 0,40,256,224
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_shot(path: Path, scale: int = 4) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im.resize((im.width // scale, im.height // scale), Image.NEAREST)


def opaque_pixels(img: Image.Image):
    px = img.load()
    out = []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a > 0:
                out.append((x, y, (r, g, b)))
    return out


def match(shot: Image.Image, sprite: Image.Image, window,
          rng: random.Random, min_visible: float = 0.55):
    """Return (mismatches, x, y, scored, total) for the best placement."""
    pts = opaque_pixels(sprite)
    probe = rng.sample(pts, min(40, len(pts)))
    sp = shot.load()
    sw, sh = shot.size
    best = None
    for y0 in range(window[1], window[3]):
        for x0 in range(window[0], window[2]):
            scored = 0
            ok = True
            for x, y, c in probe:
                sx, sy = x0 + x, y0 + y
                if not (0 <= sx < sw and 0 <= sy < sh):
                    continue
                if sp[sx, sy] != c:
                    ok = False
                    break
            if not ok:
                continue
            bad = 0
            for x, y, c in pts:
                sx, sy = x0 + x, y0 + y
                if not (0 <= sx < sw and 0 <= sy < sh):
                    continue
                scored += 1
                if sp[sx, sy] != c:
                    bad += 1
            if scored < len(pts) * min_visible:
                continue
            if best is None or bad < best[0]:
                best = (bad, x0, y0, scored, len(pts))
    return best or (10 ** 9, -1, -1, 0, len(pts))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shot", type=Path, required=True)
    ap.add_argument("--textures", default=str(ROOT / "assets" / "generated" /
                                             "enemy_33_{i}.png"))
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--window", default="0,40,256,224")
    args = ap.parse_args()
    shot = load_shot(args.shot, args.scale)
    win = tuple(int(v) for v in args.window.split(","))
    print(f"{args.shot.name}:")
    results = []
    for i in range(args.count):
        p = Path(args.textures.format(i=i))
        if not p.is_file():
            continue
        base = Image.open(p).convert("RGBA")
        for flipped in (False, True):
            sprite = base.transpose(Image.FLIP_LEFT_RIGHT) if flipped else base
            bad, x0, y0, scored, total = match(
                shot, sprite, win, random.Random(7))
            if scored == 0:
                continue
            results.append((bad, i, flipped, x0, y0, scored, total))
    for r in sorted(results)[:6]:
        bad, i, fl, x0, y0, scored, total = r
        print(f"  frame {i}{' (mirrored)' if fl else ''}: "
              f"{bad}/{scored} mismatches at ({x0},{y0})")
    ok = [r for r in results if r[0] <= max(2, r[5] * 0.01)]
    if ok:
        best = sorted(ok)[0]
        print(f"  -> drawn frame {best[1]}"
              f"{' mirrored' if best[2] else ''} ({best[0]} mismatches)")
    else:
        print("  -> no frame reproduces the screen (clipped/tinted/other art)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
