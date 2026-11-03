#!/usr/bin/env python3
"""Open the guest's pause subscreen and dump VRAM/CGRAM so the BG3 font can be
baked.

The subscreen draws its labels with the BG3 ASCII font (tile index == ASCII
code), so its VRAM contains the glyph tiles at the BG3 character base.

Usage:
  python3 tools/oracle/capture_menu.py --rom "..." \
      --save DemonsCrestSNESRecomp/build-trace/saves/save0.sav --out captures/menu
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=os.environ.get("RECOMP_DIR",
                                           str(ROOT.parent / "DemonsCrestSNESRecomp")))
    ap.add_argument("--rom", default=os.environ.get("ROM", ""))
    ap.add_argument("--save", default="")
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "menu")
    ap.add_argument("--port", type=int, default=4408)
    ap.add_argument("--timeout", type=float, default=120.0)
    return ap.parse_args()


class Client:
    def __init__(self, sock: socket.socket):
        self._file = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self._file.write((text + "\n").encode())
        self._file.flush()
        line = self._file.readline()
        return json.loads(line) if line else {}

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int) -> None:
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 180.0
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError("timeout")
            time.sleep(0.01)
        time.sleep(0.05)

    def dump(self, command: str) -> bytes:
        return bytes.fromhex(self.cmd(command)["hex"].replace(" ", ""))


def connect(port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"capture_menu: no debug server on port {port}")


def main() -> int:
    args = parse_args()
    rom = Path(args.rom).resolve() if args.rom else None
    if not rom or not rom.is_file():
        raise SystemExit("capture_menu: pass --rom or set ROM")
    save = Path(args.save) if args.save else (
        Path(args.recomp) / "build-trace" / "saves" / "save0.sav")
    if not save.is_file():
        raise SystemExit(f"capture_menu: missing save {save}")
    save = save.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    binary = Path(args.recomp) / "build-trace" / "DemonsCrestSNESRecomp.exe"
    if not binary.is_file():
        binary = Path(args.recomp) / "build-trace" / "DemonsCrestSNESRecomp"
    tmp_save = out / "resume.sav"
    shutil.copyfile(save, tmp_save)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(out / "capture.log", "wb")
    proc = subprocess.Popen([str(binary), str(rom), "--paused",
                             "--resume-state", str(tmp_save)],
                            cwd=str(Path(args.recomp)), env=env,
                            stdout=log, stderr=log)
    try:
        client = Client(connect(args.port, args.timeout))
        client.run_to(client.frame() + 30)
        client.cmd("set_controller start")
        client.run_to(client.frame() + 2)
        client.cmd("set_controller 0")
        client.run_to(client.frame() + 70)
        frame = client.frame()
        (out / "vram.bin").write_bytes(client.dump("dump_vram"))
        (out / "cgram.bin").write_bytes(client.dump("dump_cgram"))
        ppu = client.cmd("get_ppu_state")
        (out / "ppu.json").write_text(json.dumps({"frame": frame, "ppu": ppu}))
        print(f"capture_menu: frame {frame} -> {out}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        tmp_save.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
