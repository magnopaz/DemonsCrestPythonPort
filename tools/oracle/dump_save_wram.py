#!/usr/bin/env python3
"""Dump WRAM (and optionally VRAM/CGRAM/OAM/PPU regs) from a recomp save state.

The trace build can resume a `.sav` paused and expose a TCP debug server.  This
tool runs one save, waits for a fully lit frame, then streams the requested
memory ranges to `<out>/<name>.wram.bin` (plus `regs.json`/`ppu.json`).

It is the low-level primitive behind `capture_area_frames.py`: the area id of a
save state is not stored in a readable header, so a full WRAM dump is used to
locate the guest's current-area variable and to record it for the capture
manifest.

Usage:
  python3 tools/oracle/dump_save_wram.py --save build-trace/saves/save7.sav \
      --out captures/wram/save7
  python3 tools/oracle/dump_save_wram.py --save ... --out ... --vram
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECOMP = ROOT.parent / "DemonsCrestSNESRecomp"
DEFAULT_ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")
        self.sock = sock

    def cmd(self, text):
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError(f"No response to {text!r}")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self):
        return int(self.cmd("frame")["frame"])

    def run_to(self, target):
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 300
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.005)

    def read_ram(self, addr, n):
        return bytes.fromhex(self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def close(self):
        try:
            self.f.close()
        finally:
            self.sock.close()


def connect(port, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def ppu_inidisp(client):
    raw = client.cmd("get_ppu_state")
    ppu = raw.get("ppu", raw)
    try:
        return int(str(ppu.get("inidisp", "0x80")), 16)
    except ValueError:
        return 0x80


def wait_visible(client, frames=240):
    for _ in range(frames):
        if (ppu_inidisp(client) & 0x0F) >= 0x0C:
            return True
        client.run_to(client.frame() + 1)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=4421)
    ap.add_argument("--frame", type=int, default=120,
                    help="frames to run after the first lit frame (default 120)")
    ap.add_argument("--vram", action="store_true", help="also dump VRAM/CGRAM/OAM")
    args = ap.parse_args()

    exe = args.recomp / "build-trace" / "DemonsCrestSNESRecomp"
    if not exe.exists():
        raise SystemExit(f"missing trace build: {exe}")
    args.out.mkdir(parents=True, exist_ok=True)
    # The host rewrites the *game directory* prefix of every path argument
    # (snesrecomp_abspath), so a state living outside the recomp tree is
    # silently redirected to a nonexistent path and the load fails. Keep the
    # temporary resume state inside the recomp root: then the rewrite is a
    # no-op. It is one-shot and the host deletes it after a successful load.
    resume = args.recomp / f"_dc_resume_{args.port}.sav"
    shutil.copyfile(args.save, resume)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(exe), str(args.rom), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(args.recomp), env=env,
                            stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        visible = wait_visible(client)
        client.run_to(client.frame() + args.frame)
        frame = client.frame()
        wram = client.read_ram(0, 0x20000)
        (args.out / "wram.bin").write_bytes(wram)
        meta = {"save": str(args.save), "frame": frame, "visible": visible,
                "inidisp": f"0x{ppu_inidisp(client):02x}"}
        if args.vram:
            # The ring holds completed frames only: the live counter's newest
            # frame is not in the buffer yet. `dump_vram` returns the emulator's
            # live buffer, which is mostly empty mid-resume; the ring's frame
            # dump is the proven path (capture_anim.py uses the same one).
            ring = max(0, frame - 1)
            state = client.cmd(f"get_frame_extended {ring}")
            (args.out / "vram.bin").write_bytes(bytes.fromhex(
                client.cmd(f"dump_frame_vram {ring}")["hex"].replace(" ", "")))
            def _hex(value):
                return value["hex"].replace(" ", "") if isinstance(value, dict) else str(value).replace(" ", "")

            (args.out / "cgram.bin").write_bytes(bytes.fromhex(_hex(state["cgram"])))
            (args.out / "oam.bin").write_bytes(bytes.fromhex(_hex(state["oam"])))
            (args.out / "state.json").write_text(json.dumps(state, indent=1))
            meta["ppu"] = state["ppu"]
            meta["ring_frame"] = ring
        (args.out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(f"{args.save.name}: frame={frame} visible={visible} wram={len(wram)}")
        return 0
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        # A *successful* load deletes the one-shot state itself; remove the copy
        # when the load failed so stale files do not accumulate.
        try:
            resume.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
