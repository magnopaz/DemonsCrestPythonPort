#!/usr/bin/env python3
"""Compare the embedded APU against the live console over the same window.

Everything so far measured the embedded render in isolation ("rms 0.0 => broken"),
which cannot distinguish "the driver is not playing" from "this is what the game
plays right now". This probe takes the same moment twice:

  1. live: run to FRAME, capture 10 s of the oracle's DSP output;
  2. embedded: dump the .spc at that same frame and render it with spc_render;
  3. print both per-second RMS profiles side by side.

If the profiles match, the embedded APU is faithful and any silence is the game's
own state; if they diverge, the divergence point is where to look.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get("RECOMP_DIR", ROOT.parent / "DemonsCrestSNESRecomp"))
ROM = Path(os.environ.get("ROM", ROOT.parent / "roms" / "Demon's Crest (USA).sfc"))
NATIVE = 32040


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")

    def cmd(self, t):
        self.f.write((t + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("closed")
        m = json.loads(line)
        if "error" in m:
            raise RuntimeError(f"{t}: {m['error']}")
        return m

    def frame(self):
        return int(self.cmd("frame")["frame"])

    def run_to(self, t):
        if self.frame() >= t:
            return
        self.cmd(f"run_to_frame {t}")
        dl = time.monotonic() + 300
        while self.frame() < t:
            if time.monotonic() > dl:
                raise RuntimeError("timeout")
            time.sleep(0.005)


def connect(port, timeout=90.0):
    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("compare_ab: no debug server")


def rms_profile(path: Path, step: float = 1.0) -> list[float]:
    with wave.open(str(path)) as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    n = len(s) // 2
    out = []
    stride = max(1, int(rate * step))
    for i in range(0, n, stride):
        seg = s[i * 2:min(n, i + stride) * 2]
        if not seg:
            break
        out.append(math.sqrt(sum(v * v for v in seg) / len(seg)))
        if len(out) >= 10:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frame", type=int, default=200)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--port", type=int, default=4410)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "oracle.log", "wb")
    proc = subprocess.Popen([str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"),
                             str(ROM), "--paused"],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        client.run_to(args.frame)
        time.sleep(0.2)
        spc = (args.out / "at.spc").resolve()
        client.cmd(f"spc_dump {spc}")
        produced = int(client.cmd("audio_stats")["produced"])
        # Live window: run for the same wall-clock the render will cover.
        client.run_to(args.frame + int(args.seconds * 60))
        time.sleep(0.3)
        produced2 = int(client.cmd("audio_stats")["produced"])
        count = min(produced2 - produced, int(args.seconds * NATIVE))
        live = (args.out / "live.wav").resolve()
        client.cmd(f"audio_wav {live} {produced2 - count} {count}")
        print(f"frame {args.frame}: live window {count} samples")
    finally:
        if client:
            try:
                client.f.close()
            except Exception:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    embedded = args.out / "embedded.wav"
    tool = ROOT / "build" / "spc_render"
    for name, extra in (("echo-on", []), ("no-echo", ["DC_SPC_NO_ECHO=1"]),
                        ("no-dsp", ["DC_SPC_NO_DSP=1"])):
        out = args.out / f"embedded_{name}.wav"
        env2 = dict(os.environ)
        for e in extra:
            k, v = e.split("=")
            env2[k] = v
        subprocess.run([str(tool), str(args.out / "at.spc"), str(out),
                        "--seconds", str(args.seconds)],
                       check=True, capture_output=True, env=env2)
        print(f"{name:8s} rms profile:", " ".join(f"{v:7.0f}"
                                                  for v in rms_profile(out)))
    print(f"{'live':8s} rms profile:", " ".join(f"{v:7.0f}"
                                                for v in rms_profile(live)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
