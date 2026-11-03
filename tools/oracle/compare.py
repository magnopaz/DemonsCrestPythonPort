#!/usr/bin/env python3
"""Compare a native DC_TRACE_CSV against an oracle player CSV.

Both traces use world-space player positions; the absolute origin differs
between the recomp and the native engine (the original's level Y origin is
offset), so the comparison aligns at the first frame and compares deltas.

Usage:
  python3 tools/oracle/compare.py native.csv oracle.csv \
      --oracle-start 600 --threshold 2.0
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def load_native(path: Path):
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "frame": int(r["frame"]),
                "x": float(r["player_x"]),
                "y": float(r["player_y"]),
            })
    return rows


def load_oracle(path: Path, start: int):
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            rel = int(r["frame_rel"])
            if rel < start:
                continue
            rows.append({
                "frame": rel,
                "x": float(r["player_x"]),
                "y": float(r["player_y"]),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("native", type=Path)
    ap.add_argument("oracle", type=Path)
    ap.add_argument("--oracle-start", type=int, default=600,
                    help="oracle frame_rel that matches native frame 0")
    ap.add_argument("--threshold", type=float, default=2.0,
                    help="report the first absolute delta above this many pixels")
    ap.add_argument("--limit", type=int, default=0,
                    help="compare at most N frames (0 = all)")
    args = ap.parse_args()

    native = load_native(args.native)
    oracle = load_oracle(args.oracle, args.oracle_start)
    if not native or not oracle:
        print("compare: empty trace", file=sys.stderr)
        return 1

    nx0, ny0 = native[0]["x"], native[0]["y"]
    ox0, oy0 = oracle[0]["x"], oracle[0]["y"]

    n = min(len(native), len(oracle))
    if args.limit > 0:
        n = min(n, args.limit)

    max_dx = max_dy = 0.0
    sum_dx = sum_dy = 0.0
    first = None
    print("frame,dx,dy,native_x,native_y,oracle_x,oracle_y")
    for i in range(n):
        dx = (native[i]["x"] - nx0) - (oracle[i]["x"] - ox0)
        dy = (native[i]["y"] - ny0) - (oracle[i]["y"] - oy0)
        max_dx = max(max_dx, abs(dx))
        max_dy = max(max_dy, abs(dy))
        sum_dx += abs(dx)
        sum_dy += abs(dy)
        if first is None and (abs(dx) > args.threshold or
                              abs(dy) > args.threshold):
            first = (i, dx, dy)
        if i < 80 or i % 30 == 0:
            print(f"{i},{dx:.2f},{dy:.2f},{native[i]['x']:.2f},"
                  f"{native[i]['y']:.2f},{oracle[i]['x']:.2f},"
                  f"{oracle[i]['y']:.2f}")

    print()
    print(f"frames compared: {n}")
    print(f"max delta: x={max_dx:.2f}px y={max_dy:.2f}px")
    print(f"mean delta: x={sum_dx / n:.2f}px y={sum_dy / n:.2f}px")
    if first:
        print(f"first > {args.threshold}px: frame {first[0]} "
              f"dx={first[1]:.2f} dy={first[2]:.2f}")
    else:
        print(f"all frames within {args.threshold}px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
