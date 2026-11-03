"""Mode 7 world-map projection (pure maths, no rendering).

The original draws area 94 as a Mode 7 plane: a horizon near the top of the
frame, ground rows shrinking with distance, and Firebrand's winged cursor at the
bottom centre (docs/map_compare.png and
docs/sprites/animated/map_mode7_animated.mp4).  The reference frames show the
rows parallel to the screen and the cursor axis-aligned, so this is the
no-rotation case of the Mode 7 matrix: every screen row samples one texture row
and a horizontal window of the plane.

Screen row -> depth:  depth = focal / (sy - horizon)         (world px ahead)
Depth -> screen row:  sy    = horizon + focal / depth
Horizontal:           sx    = 128 + (wx - cam_x) * 128 / depth
                      (the visible world width at `depth` is 2 * depth)

Kept free of raylib so tools/check_map_mode7.py can assert the invariants
without opening a window.
"""

from __future__ import annotations

import math

HORIZON = 37              # first ground row; the reference's ~1/6 of 224
FOCAL = 46500.0           # world px * screen rows
DEPTH_MAX = 2048.0        # far clamp; the horizon would otherwise wrap forever
MAP_SIZE = 1024.0


def depth_at(sy: float) -> float:
    """World depth (px ahead) sampled at screen row `sy`."""
    return min(DEPTH_MAX, FOCAL / max(1.0, sy - HORIZON))


def project(cam_x: float, cam_y: float, wx: float, wy: float):
    """World -> (sx, sy) on the plane, or None when behind/off the frame."""
    depth = wy - cam_y
    if depth <= 0.0:
        return None
    sy = HORIZON + FOCAL / depth
    if sy < HORIZON or sy >= 224.0:
        return None
    sx = 128.0 + (wx - cam_x) * 128.0 / depth
    return sx, sy


def row_segments(cam_x: float, cam_y: float, depth: float):
    """Texture slices for one screen row, wrapped over the 1024 px map.

    Returns `(src_x, row, src_w, dst_x, dst_w)` tuples; `dst_x`/`dst_w` are in
    the 256 px frame.  The segments cover the row exactly once, which is what
    makes the plane continuous across the map's seam.
    """
    src_w = 2.0 * depth
    row = (cam_y + depth) % MAP_SIZE
    left = cam_x - depth
    right = left + src_w
    first = math.floor(left / MAP_SIZE)
    last = math.floor((right - 1e-9) / MAP_SIZE)
    out = []
    for tile in range(first, last + 1):
        tile_start = tile * MAP_SIZE
        a = max(left, tile_start)
        b = min(right, tile_start + MAP_SIZE)
        if b - a <= 0.01:
            continue
        start = a - tile_start
        seg = b - a
        dst_x = (a - left) / src_w * 256.0
        dst_w = seg / src_w * 256.0
        out.append((start, row, seg, dst_x, dst_w))
    return out
