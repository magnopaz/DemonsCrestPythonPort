#!/usr/bin/env python3
"""Probe one save state and dump everything needed to identify its room.

One emulator run produces, under `--out`:

  f<frame>.json / f<frame>.vram.bin   state + 64 KiB VRAM for each sample frame
  wram.bin                            128 KiB WRAM ($7E:0000-$7F:FFFF)
  cgram.bin                           512 B CGRAM (last sample frame)
  ppu.json                            PPU registers (last sample frame)
  meta.json                           frames, visibility, `$008D` and `area_hint`

Several frames are sampled because a save can land mid-transition (a door
crossing or a fade), where the room is not on screen yet; the matcher takes the
best-matching frame instead of trusting a single one.

The frame files use the same layout as `capture_area_frame.py`, so
`identify_area.py` can read a probe directory directly.

Usage:
  python3 tools/oracle/probe_save_room.py \
      --save build-trace/saves/lvl_I_murkland-cemetery.sav --out captures/rooms/cem
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, wait_visible  # noqa: E402

# `$008D` holds the *byte* offset the room loader adds to the `$81:A291`
# pointer table, i.e. 2 * area index (see docs/PROJECT_STATE.md).  It is the
# cheapest area signal available and is verified against BG1 by the matcher.
STAGE_ID = 0x008D
DEFAULT_OFFSETS = "20,60,120"


def parse_offsets(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()]


def probe(save: Path, out: Path, recomp: Path, rom: Path, port: int,
          settle: int = 90, offsets: list[int] | None = None) -> dict:
    offsets = offsets or parse_offsets(DEFAULT_OFFSETS)
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("f*.json")) + list(out.glob("f*.vram.bin")):
        old.unlink()
    exe = recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.is_file():
        raise SystemExit(f"missing trace build: {exe}")
    resume = (recomp / f"_dc_room_{port}.sav").resolve()
    shutil.copyfile(save.resolve(), resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(out / "probe.log", "wb")
    proc = subprocess.Popen([str(exe), str(rom.resolve()), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(recomp), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(port)
        visible = wait_visible(client)
        client.run_to(client.frame() + settle)
        start = client.frame()
        written = []
        state = None
        for off in offsets:
            client.run_to(start + off)
            client.run_to(client.frame() + 2)
            n = max(0, client.frame() - 1)  # newest completed ring frame
            state = client.cmd(f"get_frame_extended {n}")
            vram = client.cmd(f"dump_frame_vram {n}")
            (out / f"f{n:06d}.json").write_text(json.dumps(state, indent=1))
            (out / f"f{n:06d}.vram.bin").write_bytes(
                bytes.fromhex(vram["hex"].replace(" ", "")))
            written.append(n)
        if state is None:
            raise SystemExit("no frame sampled")
        (out / "ppu.json").write_text(json.dumps(state["ppu"], indent=1))
        cg = state["cgram"]
        if isinstance(cg, dict):
            cg = cg["hex"]
        (out / "cgram.bin").write_bytes(bytes.fromhex(str(cg).replace(" ", "")))
        wram = client.read_ram(0, 0x20000)
        (out / "wram.bin").write_bytes(wram)
        stage_id = wram[STAGE_ID]
        meta = {"save": save.name, "frames": written, "visible": visible,
                "stage_id_8d": stage_id,
                "area_hint": stage_id // 2 if stage_id % 2 == 0 else None,
                "inidisp": state["ppu"].get("inidisp")}
        (out / "meta.json").write_text(json.dumps(meta, indent=1))
        return meta
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path,
                    default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=4600)
    ap.add_argument("--settle", type=int, default=90)
    ap.add_argument("--offsets", default=DEFAULT_OFFSETS)
    args = ap.parse_args()
    meta = probe(args.save, args.out, args.recomp, args.rom, args.port,
                 args.settle, parse_offsets(args.offsets))
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
