#!/usr/bin/env python3
"""Compare a C-port window screenshot with a Python-port render-target dump.

The C build's DC_SCREENSHOT captures the 1024x896 window (raylib's
TakeScreenshot ignores the directory part of the path and writes the basename
into its working directory); the Python port's DC_SCREENSHOT_RT exports the
256x224 render target, already upright. This tool downscales the former with
NEAREST and reports the measured difference.

Usage:
  python3 tools/compare_frames.py C.png P.png [--save side.png]
Exit code 0 when the frames match within the default tolerance.
"""

from __future__ import annotations

import argparse
import sys

from PIL import Image
import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("c_shot")
    ap.add_argument("p_shot")
    ap.add_argument("--save", default=None, help="write a side-by-side PNG")
    ap.add_argument("--max-mean", type=float, default=1.0,
                    help="tolerated mean absolute channel difference")
    ap.add_argument("--max-diff-pct", type=float, default=2.0,
                    help="tolerated %% of pixels differing by more than 8")
    args = ap.parse_args()

    c = Image.open(args.c_shot).convert("RGB")
    if c.size != (256, 224):
        factor = c.width // 256
        c = c.resize((256, 224), Image.NEAREST)
        print(f"C shot {Image.open(args.c_shot).size} -> 256x224 (1/{factor})")
    p = Image.open(args.p_shot).convert("RGB")
    if p.size != (256, 224):
        print(f"P shot is {p.size}, expected 256x224 (DC_SCREENSHOT_RT)")
        p = p.resize((256, 224), Image.NEAREST)

    a = np.asarray(c, dtype=np.int16)
    b = np.asarray(p, dtype=np.int16)
    diff = np.abs(a - b)
    mean = float(diff.mean())
    pct = float((diff.max(axis=2) > 8).mean() * 100.0)
    print(f"mean abs diff {mean:.3f}   pixels >8: {pct:.2f}%")
    if args.save:
        Image.fromarray(np.concatenate([a, b], axis=1).astype(np.uint8)).save(
            args.save)
        print(f"wrote {args.save}")

    ok = mean <= args.max_mean and pct <= args.max_diff_pct
    print("MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
