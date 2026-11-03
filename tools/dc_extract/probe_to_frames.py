#!/usr/bin/env python3
"""Convert batch-probe dumps into extractor capture frames.

Each probe directory gets `f<frame>.json` + `f<frame>.vram.bin` in the format
`read_capture_frame` expects, so `bg2_captures.json` can point at it.

Usage:
  python tools/dc_extract/probe_to_frames.py --probe-root <...>/oracle_probe \
      --saves 0a,4a,6a --out-root captures
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

FRAME = 90000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe-root", type=Path, required=True)
    ap.add_argument("--saves", required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    args = ap.parse_args()

    for tag in [s.strip() for s in args.saves.split(",") if s.strip()]:
        src = args.probe_root / f"save{tag}"
        if not (src / "info.json").is_file():
            print(f"skip save{tag}: no probe data")
            continue
        out = args.out_root / f"save{tag}"
        out.mkdir(parents=True, exist_ok=True)
        info = json.loads((src / "info.json").read_text())
        ppu = json.loads((src / "ppu.json").read_text())
        body = ppu.get("ppu", ppu)
        state = {
            "frame": FRAME,
            "ppu": body,
            "cgram": (src / "cgram.bin").read_bytes().hex(),
            "oam": (src / "oam.bin").read_bytes().hex(),
            "wram_1000": "",
            "zeropage": "",
        }
        (out / f"f{FRAME:06d}.json").write_text(json.dumps(state))
        shutil.copyfile(src / "vram.bin", out / f"f{FRAME:06d}.vram.bin")
        print(f"save{tag}: area {info['area']} -> {out}/f{FRAME:06d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
