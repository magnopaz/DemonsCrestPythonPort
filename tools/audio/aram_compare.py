#!/usr/bin/env python3
"""Dump ARAM at two points of a live run and compare with the offline render.

The .spc resume always derails after a few thousand instructions, while the live
emulator (same SPC700 + DSP cores) plays forever. The .spc carries ARAM, the
DSP registers and the SPC registers, so the divergence must come from state the
format cannot carry. Diffing ARAM byte by byte after the same audio window says
*which* variable diverged first, which points at the input that differs.

Usage:
  python3 tools/audio/aram_compare.py --save <save> --frames 30 \
      --out captures/audio/aram_diff
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
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))
NATIVE_RATE = 32040


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
        deadline = time.monotonic() + 300
        while self.frame() < t:
            if time.monotonic() > deadline: raise RuntimeError("timeout")
            time.sleep(0.005)
    def aram(self):
        return bytes.fromhex(
            self.cmd("dump_apu_ram 0 65536")["hex"].replace(" ", ""))


def connect(port, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("aram_compare: no debug server")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--settle", type=int, default=120)
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--sample-window", type=int, default=0,
                    help="use this many native samples instead of whole frames")
    ap.add_argument("--port", type=int, default=4404)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    exe = RECOMP / "build-trace" / "DemonsCrestSNESRecomp"
    resume = RECOMP / f"_dc_aram_{args.port}.sav"
    shutil.copyfile(args.save, resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(exe), str(ROM), "--paused",
                             "--resume-state", str(resume)],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        client.run_to(client.frame() + args.settle)
        time.sleep(0.2)
        stats = client.cmd("audio_stats")
        p0 = int(stats["produced"])
        a0 = client.aram()
        spc = (args.out / "a0.spc").resolve()
        client.cmd(f"spc_dump {spc}")
        f0 = client.frame()
        if args.sample_window:
            # Whole frames only: pick the smallest frame count that covers it,
            # then compare over the exact sample count the DSP produced.
            client.run_to(f0 + 1)
        else:
            client.run_to(f0 + args.frames)
        time.sleep(0.3)
        stats1 = client.cmd("audio_stats")
        p1 = int(stats1["produced"])
        a1 = client.aram()
    finally:
        if client: 
            try: client.f.close()
            except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        log.close()
        resume.unlink(missing_ok=True)

    (args.out / "a0.aram").write_bytes(a0)
    (args.out / "a1.aram").write_bytes(a1)
    samples = args.sample_window if args.sample_window else p1 - p0

    # offline: load a0.spc, run exactly `samples` native samples, dump ARAM
    tool = ROOT / "build" / "spc_render"
    seconds = samples / NATIVE_RATE
    off_aram = args.out / "b1.aram"
    subprocess.run([str(tool), str(spc), str(args.out / "b.wav"),
                    "--seconds", f"{seconds:.6f}", "--dump-aram", str(off_aram)],
                   check=True, capture_output=True)

    b0 = a0
    b1 = off_aram.read_bytes()
    diff = [i for i in range(0x10000) if a1[i] != b1[i]]
    print(f"frames={args.frames} samples={samples} ({seconds:.3f}s)")
    print(f"ARAM bytes differing live-vs-offline after the window: {len(diff)}")
    for i in diff[:24]:
        print(f"  {i:04X}: live {a1[i]:02X}  offline {b1[i]:02X}"
              f"   (at snapshot: {b0[i]:02X})")
    # low region is the driver's variables; report which changed at all
    changed_live = [i for i in range(0x100) if a1[i] != b0[i]]
    changed_off = [i for i in range(0x100) if b1[i] != b0[i]]
    print(f"zero-page bytes changed by live: {len(changed_live)},"
          f" by offline: {len(changed_off)}")
    both = sorted(set(changed_live) & set(changed_off))
    print("zero-page addresses both changed:", [f"{x:02X}" for x in both][:32])
    (args.out / "diff.json").write_text(json.dumps(
        {"frames": args.frames, "samples": samples, "diff": diff[:256],
         "diff_count": len(diff)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
