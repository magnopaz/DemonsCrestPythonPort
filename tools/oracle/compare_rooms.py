#!/usr/bin/env python3
"""Compare a native room render against the oracle's own frame for the same save.

The recomp's debug server can hand back the presented frame (`screenshot
<path>`), and the native port can render a room headless with
`DC_AREA`/`DC_RUN_FRAMES`/`DC_SCREENSHOT`.  Putting the two side by side is the
only honest check that a room's tiles, palette and backdrop actually match the
original instead of merely being non-empty.

The camera and the player's spawn differ between the two, so the comparison
searches a horizontal shift (and a small vertical one) and reports the best
alignment plus the mean per-channel difference on the overlapping area.  It
also writes a side-by-side PNG, which is what a human should look at before
trusting the score.

Usage:
  python3 tools/oracle/compare_rooms.py \
      --save ../DemonsCrestSNESRecomp/build-trace/saves/lvl_I_murkland-cemetery.sav \
      --area 1 --out /tmp/cmp_cemetery
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, wait_visible  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def oracle_screenshot(save: Path, recomp: Path, rom: Path, out: Path, port: int,
                      settle: int = 60) -> Image.Image:
    exe = recomp / "build-trace" / "DemonsCrestSNESRecomp"
    resume = (recomp / f"_dc_cmp_{port}.sav").resolve()
    shutil.copyfile(save.resolve(), resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(out / "oracle.log", "wb")
    proc = subprocess.Popen([str(exe), str(rom.resolve()), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(recomp), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(port)
        wait_visible(client)
        client.run_to(client.frame() + settle)
        shot = (out / "oracle.png").resolve()
        client.cmd(f"screenshot {shot}")
        return Image.open(shot).convert("RGB")
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        try:
            resume.unlink()
        except FileNotFoundError:
            pass


def native_screenshot(binary: Path, assets: Path, area: int, out: Path,
                      frames: int = 40) -> Image.Image:
    env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":99"),
               DC_AREA=str(area), DC_RUN_FRAMES=str(frames), DC_NO_AUDIO="1",
               DC_SCREENSHOT="native_cmp.png")
    subprocess.run([str(binary), "--assets", str(assets)], cwd=str(out), env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    path = out / "native_cmp.png"
    if not path.is_file():
        raise SystemExit(f"native screenshot missing ({path})")
    img = Image.open(path).convert("RGB")
    # raylib dumps the window, which is an integer multiple of the 256x224
    # render target (1024x896 here). Comparing it against the oracle's 256x224
    # frame without downscaling produced meaningless scores and a "different
    # room" verdict for rooms that actually match.
    if img.size != (256, 224):
        img = img.resize((256, 224), Image.NEAREST)
    return img


def best_shift(a: Image.Image, b: Image.Image, max_dx: int = 96,
               max_dy: int = 24) -> tuple[int, int, float, float]:
    """Brute-force the shift of `b` that best matches `a`; returns (dx, dy, mad, overlap)."""
    aw, ah = a.size
    bw, bh = b.size
    pa, pb = a.load(), b.load()
    best = (0, 0, 1e9, 0.0)
    for dy in range(-max_dy, max_dy + 1, 4):
        for dx in range(-max_dx, max_dx + 1, 2):
            x0, x1 = max(0, dx), min(aw, bw + dx)
            y0, y1 = max(0, dy), min(ah, bh + dy)
            if x1 - x0 < 128 or y1 - y0 < 96:
                continue
            total = 0
            count = 0
            for y in range(y0, y1, 2):
                for x in range(x0, x1, 2):
                    ca = pa[x, y]
                    cb = pb[x - dx, y - dy]
                    total += abs(ca[0] - cb[0]) + abs(ca[1] - cb[1]) + abs(ca[2] - cb[2])
                    count += 3
            mad = total / count if count else 1e9
            if mad < best[2]:
                best = (dx, dy, mad, (x1 - x0) * (y1 - y0) / (aw * ah))
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--area", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--binary", type=Path, default=ROOT / "build" / "demonscrest")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--port", type=int, default=5100)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    oracle = oracle_screenshot(args.save, args.recomp, args.rom, args.out, args.port)
    native = native_screenshot(args.binary, args.assets, args.area, args.out)
    dx, dy, mad, overlap = best_shift(oracle, native)
    side = Image.new("RGB", (oracle.size[0] * 2 + 8, oracle.size[1]), (24, 24, 24))
    side.paste(oracle, (0, 0))
    side.paste(native, (oracle.size[0] + 8, 0))
    side.save(args.out / "side_by_side.png")
    report = {"save": str(args.save), "area": args.area, "shift": [dx, dy],
              "mean_abs_diff": round(mad, 2), "overlap": round(overlap, 3),
              "oracle": str(args.out / "oracle.png"),
              "native": str(args.out / "native_cmp.png")}
    (args.out / "compare.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
