#!/usr/bin/env python3
"""Cold-boot the oracle and capture the APU as early as possible.

A .spc resumed mid-game derails, so the port cannot boot the driver from a
mid-play snapshot. The console's own boot is the right starting point: the game
uploads the driver byte by byte through the IPL, the driver initialises itself
(timers, tables, zeroed song state), and only later does the first song command
arrive. Capturing ARAM in that window gives a *clean* post-boot image, which is
what the port's embedded APU needs.

Prints the SPC state and writes aram.bin + spc/meta.json per sample frame.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")
    def cmd(self, t):
        self.f.write((t + "\n").encode()); self.f.flush()
        line = self.f.readline()
        if not line: raise RuntimeError("closed")
        m = json.loads(line)
        if "error" in m: raise RuntimeError(f"{t}: {m['error']}")
        return m
    def frame(self): return int(self.cmd("frame")["frame"])
    def run_to(self, t):
        self.cmd(f"run_to_frame {t}")
        dl = time.monotonic() + 300
        while self.frame() < t:
            if time.monotonic() > dl: raise RuntimeError("timeout")
            time.sleep(0.005)


def connect(port, timeout=90.0):
    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("boot_capture: no debug server")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", type=int, nargs="+", default=[20, 40, 60, 90, 120])
    ap.add_argument("--port", type=int, default=4405)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "boot.log", "wb")
    proc = subprocess.Popen([str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"),
                             str(ROM), "--paused"],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        start = client.frame()
        print("boot start frame", start)
        rows = []
        for f in args.frames:
            client.run_to(start + f)
            time.sleep(0.15)
            apu = client.cmd("get_apu_state")
            pc = int(apu["spc"]["pc"], 16)
            produced = int(client.cmd("audio_stats")["produced"])
            aram = bytes.fromhex(
                client.cmd("dump_apu_ram 0 65536")["hex"].replace(" ", ""))
            (args.out / f"aram_f{f:04d}.bin").write_bytes(aram)
            has_driver = aram[0x46A:0x47A] != b"\x00" * 16
            print(f"  frame +{f:4d}: pc={pc:04X} sp={apu['spc']['sp']} "
                  f"driver_in_aram={has_driver} timer0={apu['timer'][0]}")
            rows.append({"frame": start + f, "pc": pc, "driver": has_driver,
                         "produced": produced, "timer0": apu["timer"][0]})
        # Every CPU->APU port write since boot, with its absolute sample index:
        # that is the command stream the driver expects (song start, SFX ids).
        events = client.cmd("audio_events 0 8000 2")["events"]
        lines = []
        for ev in events:
            if ev["t"] == "cpu_wr":
                lines.append(f'{int(ev["s"])} {int(ev["adr"], 16)} {int(ev["val"], 16)}')
        (args.out / "ports.txt").write_text("\n".join(lines) + "\n")
        print(f"  cpu->apu port writes: {len(lines)}")
        for ln in lines[:12]:
            print("   ", ln)
        (args.out / "boot.json").write_text(json.dumps(rows, indent=1))
        return 0
    finally:
        if client:
            try: client.f.close()
            except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        log.close()


if __name__ == "__main__":
    sys.exit(main())
