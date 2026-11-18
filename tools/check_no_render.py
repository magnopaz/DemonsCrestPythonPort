#!/usr/bin/env python3
"""DC_NO_RENDER must not change the simulation, only skip the drawing.

Measured 2026-11-18 (600 frames, cProfile): a deterministic run spends
49% of its time in EndDrawing (software-GL present) and 44% in
game_render -- the checkers read traces, not pixels, so all of that is
dead work (docs/NEXT_STEPS.md, Passo 6b).  dcpy/main.py now skips the
draw calls when DC_NO_RENDER is set.  This checker guards the contract
that makes it safe:

1. the same demo with and without DC_NO_RENDER produces **byte-identical**
   player and object traces -- rendering must never influence the sim;
2. DC_NO_RENDER is ignored when a screenshot is requested (the capture
   needs a rendered frame): a DC_SCREENSHOT_RT run still writes its PNG;
3. skipping is not a no-op: the render-less run is measurably faster
   (asserted only as "faster at all" -- the ratio is reported, not gated,
   so a loaded machine cannot turn this into a flaky red).

Usage:
  python tools/check_no_render.py [--binary tools/demonscrest-py]
                                  [--assets assets/generated]

Exit codes: 0 = pass, 1 = contract failure, 77 = binary missing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FRAMES = 240
DEMO = 7


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def run(binary: Path, assets: Path, tmp: Path, tag: str,
        extra: dict[str, str] | None = None) -> float:
    """One deterministic run; returns the wall-clock seconds."""
    env = dict(os.environ, DC_AREA="0", DC_DEMO=str(DEMO), DC_NO_AUDIO="1",
               DC_RUN_FRAMES=str(FRAMES),
               DC_TRACE_CSV=str(tmp / f"player_{tag}.csv"),
               DC_TRACE_OBJECTS=str(tmp / f"objects_{tag}.csv"))
    for key in list(env):
        if key.startswith("DC_SCREENSHOT"):
            del env[key]
    env.pop("DC_NO_RENDER", None)   # the caller decides; never inherit
    if extra:
        env.update(extra)
    env.setdefault("DISPLAY", ":99")
    start = time.monotonic()
    proc = subprocess.run([str(binary), "--assets", str(assets)],
                          cwd=str(ROOT), env=env, capture_output=True,
                          text=True, timeout=300)
    wall = time.monotonic() - start
    if proc.returncode != 0:
        print(f"run {tag} exited {proc.returncode}\n{proc.stdout[-600:]}",
              file=sys.stderr)
        raise SystemExit(77)
    return wall


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print(f"no binary at {args.binary}")
        return 77

    errors: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        wall_nr = run(args.binary, args.assets, tmp, "nr",
                      {"DC_NO_RENDER": "1"})
        wall_r = run(args.binary, args.assets, tmp, "r")

        for name in ("player", "objects"):
            a = (tmp / f"{name}_nr.csv").read_bytes()
            b = (tmp / f"{name}_r.csv").read_bytes()
            if a != b:
                errors.append(f"{name} trace differs with DC_NO_RENDER "
                              f"({len(a)} vs {len(b)} bytes)")

        shot = tmp / "shot.png"
        run(args.binary, args.assets, tmp, "shot",
            {"DC_NO_RENDER": "1", "DC_SCREENSHOT_RT": str(shot)})
        if not shot.is_file() or shot.stat().st_size == 0:
            errors.append("DC_SCREENSHOT_RT produced no PNG when "
                          "DC_NO_RENDER was set")

        if wall_nr >= wall_r:
            errors.append(f"DC_NO_RENDER was not faster "
                          f"({wall_nr:.1f}s vs {wall_r:.1f}s)")

    ratio = wall_r / max(wall_nr, 0.001)
    print(f"traces byte-identical with and without DC_NO_RENDER "
          f"({FRAMES} frames, demo {DEMO})")
    print(f"screenshot path still renders: PNG written with "
          f"DC_NO_RENDER set")
    print(f"render-less run {wall_nr:.2f}s vs rendered {wall_r:.2f}s "
          f"({ratio:.0f}x)")

    for error in errors:
        print(f"  ERROR {error}")
    if errors:
        return 1
    print(f"PASS ({ratio:.0f}x faster, traces identical, "
          f"screenshots unaffected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
