#!/usr/bin/env python3
"""Assert the world map is drawn as the original's Mode 7 plane.

Two independent checks:

1. **Projection maths** (pure Python, no window): `_mode7_depth` must shrink
   with distance, `_mode7_project` must put far points nearer the horizon than
   near points, and the same lateral offset must spread further out on screen
   for near points (perspective magnification).  These are the invariants the
   old `Camera2D` view did not have.

2. **The rendered frame** (area 94): the top of the frame must be the dark
   void above the horizon and the lower half must carry the plane, with a
   luminance step at the horizon row.  A flat room render fails this because
   its rows are uniform.

Exit 77 when the binary or the assets are missing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAP_AREA = 94
HORIZON = 37


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def check_projection() -> None:
    from dcpy import mode7 as m
    MODE7_HORIZON = m.HORIZON
    _mode7_depth = m.depth_at
    _mode7_project = m.project
    MODE7_DEPTH_MAX = m.DEPTH_MAX

    if _mode7_depth(MODE7_HORIZON + 5) <= _mode7_depth(200):
        raise SystemExit("mode7: near rows are not closer than far rows")
    if _mode7_depth(MODE7_HORIZON) > MODE7_DEPTH_MAX:
        raise SystemExit("mode7: the far clamp is not applied at the horizon")

    cam_x, cam_y = 500.0, 500.0
    near = _mode7_project(cam_x, cam_y, cam_x, cam_y + 300.0)
    far = _mode7_project(cam_x, cam_y, cam_x, cam_y + 900.0)
    if near is None or far is None:
        raise SystemExit("mode7: a point straight ahead did not project")
    if not (near[1] > far[1] > MODE7_HORIZON):
        raise SystemExit(f"mode7: depth order wrong (near {near[1]}, far {far[1]})")
    if abs(near[0] - 128.0) > 0.01:
        raise SystemExit("mode7: centre of the plane is not at x=128")

    # The same lateral offset must project further from the centre when near.
    near_side = _mode7_project(cam_x, cam_y, cam_x + 40.0, cam_y + 300.0)
    far_side = _mode7_project(cam_x, cam_y, cam_x + 40.0, cam_y + 900.0)
    if near_side is None or far_side is None:
        raise SystemExit("mode7: an offset point did not project")
    if not (near_side[0] - 128.0 > far_side[0] - 128.0 > 0.0):
        raise SystemExit("mode7: perspective does not magnify near rows")

    behind = _mode7_project(cam_x, cam_y, cam_x, cam_y - 10.0)
    if behind is not None:
        raise SystemExit("mode7: a point behind the camera was drawn")


def check_frame(shot: Path) -> tuple[float, float]:
    from PIL import Image

    img = Image.open(shot).convert("L")
    if img.size != (256, 224):
        raise SystemExit(f"mode7: screenshot is {img.size}, expected 256x224")
    px = img.load()
    rows = [sum(px[x, y] for x in range(256)) / 256.0 for y in range(224)]
    sky = sum(rows[:30]) / 30.0
    ground = sum(rows[120:]) / len(rows[120:])
    if sky > 70.0:
        raise SystemExit(f"mode7: the sky band is too bright ({sky:.1f})")
    if ground < sky + 10.0:
        raise SystemExit(f"mode7: no horizon step (sky {sky:.1f}, ground {ground:.1f})")
    # The plane must vary down the frame: a flat fill has near-zero spread.
    spread = max(rows[120:]) - min(rows[120:])
    if spread < 8.0:
        raise SystemExit(f"mode7: the lower half is flat (spread {spread:.1f})")
    return sky, ground


def main() -> int:
    args = parse_args()
    check_projection()
    if not args.binary.is_file():
        print("mode7: skip (no binary)")
        return 77
    if not (args.assets / "world_map.png").is_file():
        print("mode7: skip (no world_map.png)")
        return 77

    with tempfile.TemporaryDirectory(prefix="dc-mode7-") as td:
        tmp = Path(td)
        shot = (tmp / "map.png").resolve()
        env = dict(os.environ,
                   DC_AREA=str(MAP_AREA),
                   DC_RUN_FRAMES="20",
                   DC_SCREENSHOT_RT=str(shot),
                   DC_NO_AUDIO="1",
                   DC_NO_SAVE="1")
        for key in ("DC_STATE", "DC_DEMO", "DC_CAMPAIGN", "DC_START_X",
                    "DC_START_Y", "DC_BOSS_HP"):
            env.pop(key, None)
        proc = subprocess.run([str(args.binary), "--assets", str(args.assets)],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=180)
        if proc.returncode != 0:
            raise SystemExit(f"mode7: binary exited {proc.returncode}\n"
                             + proc.stdout[-1200:])
        sky, ground = check_frame(shot)

    print(f"mode7: PASS (projection invariants, horizon at row {HORIZON},"
          f" sky {sky:.1f} -> ground {ground:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
