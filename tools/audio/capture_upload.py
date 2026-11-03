#!/usr/bin/env python3
"""Capture one CPU->APU upload window from a cold boot, with a clean ARAM first.

The APU event ring only keeps the most recent events, and the DSP produces
thousands of register writes per second, so a window that is fetched minutes
after it happened is gone. This probe therefore:

  1. boots, runs to --aram-frame, dumps ARAM (driver loaded, nothing playing),
  2. runs to --end-frame (just past the music-bank upload) and immediately
     fetches the CPU->APU writes for the window,
  3. writes aram.bin, ports.txt (port/value/order, no timestamps needed for a
     handshake replay) and meta.json.

Usage:
  python3 tools/audio/capture_upload.py --out captures/audio/upload --aram-frame 60 --end-frame 150
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
        self.cmd(f"run_to_frame {t}")
        dl = time.monotonic() + 300
        while self.frame() < t:
            if time.monotonic() > dl:
                raise RuntimeError("timeout")
            time.sleep(0.004)


def connect(port, timeout=90.0):
    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        try:
            return Client(socket.create_connection(("127.0.0.1", port), timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit("capture_upload: no debug server")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--aram-frame", type=int, default=60)
    ap.add_argument("--end-frame", type=int, default=150)
    ap.add_argument("--port", type=int, default=4408)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "capture.log", "wb")
    proc = subprocess.Popen([str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"),
                             str(ROM), "--paused"],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        client.run_to(args.aram_frame)
        time.sleep(0.15)
        apu = client.cmd("get_apu_state")
        produced0 = int(client.cmd("audio_stats")["produced"])
        aram = bytes.fromhex(
            client.cmd("dump_apu_ram 0 65536")["hex"].replace(" ", ""))
        (args.out / "aram.bin").write_bytes(aram)

        client.run_to(args.end_frame)
        time.sleep(0.15)
        # `port_events` reads the dedicated port ring (65536 entries) instead of
        # the general event ring, which the DSP's register writes flood within a
        # second - that is why `audio_events` lost the upload.
        tsv = (args.out / "apu.tsv").resolve()
        dumped = client.cmd(f"port_events {tsv}")
        writes = []
        for line in tsv.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            frame, kind, port, value, sample = line.split("\t")
            if kind != "cpu_wr":
                continue
            s = int(sample)
            if s > produced0:
                writes.append((s, int(port), int(value, 16)))
        print("port ring:", dumped.get("events"), "events, total",
              dumped.get("total"))
        elapsed = int(client.cmd("audio_stats")["produced"]) - produced0
        (args.out / "ports.txt").write_text(
            "\n".join(f"{s} {p} {v}" for s, p, v in writes) + "\n")
        meta = {
            "aram_frame": args.aram_frame,
            "end_frame": args.end_frame,
            "entry_pc": apu["spc"]["pc"],
            "produced_at_aram": produced0,
            "samples_in_window": elapsed,
            "port_writes": len(writes),
            "first_write": writes[0] if writes else None,
            "first_write_offset": (writes[0][0] - produced0) if writes else None,
        }
        (args.out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps(meta, indent=1))
        return 0
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


if __name__ == "__main__":
    sys.exit(main())
