#!/usr/bin/env python3
"""Capture the whole CPU->APU conversation of a cold boot, from sample 0.

The port ring holds the last 65536 events, so one dump cannot cover a boot with
~96k port events. Sampling it repeatedly and merging on the sample clock gives
the complete stream, which is what a cold-reset replay needs: the embedded APU
then follows the console's own timeline instead of resuming a snapshot.

Writes <out>/ports.txt as "<sample> <port> <value>" lines.
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
    raise SystemExit("capture_boot_ports: no debug server")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--port", type=int, default=4411)
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
        seen: dict[tuple, None] = {}
        order: list[tuple] = []
        f = 2
        while f <= args.until:
            client.run_to(f)
            time.sleep(0.03)
            tsv = (args.out / f"ring_{f:04d}.tsv").resolve()
            dumped = client.cmd(f"port_events {tsv}")
            for line in tsv.read_text().splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.split("\t")
                if fields[1] != "cpu_wr":
                    continue
                # cycle stamp is the last column; it is the clock a faithful
                # replay must use (a sample index resolves only 32 cycles)
                cycle = int(fields[9]) if len(fields) > 9 else int(fields[4]) * 32
                key = (cycle, int(fields[2]), int(fields[3], 16))
                if key not in seen:
                    seen[key] = None
                    order.append(key)
            tsv.unlink()
            print(f"frame {f}: ring {dumped.get('events')} of"
                  f" {dumped.get('total')}, merged {len(order)}")
            f += args.every
        order.sort(key=lambda w: w[0])
        (args.out / "ports.txt").write_text(
            "\n".join(f"{s} {p} {v}" for s, p, v in order) + "\n")
        (args.out / "meta.json").write_text(json.dumps(
            {"writes": len(order), "first": order[0] if order else None,
             "last": order[-1] if order else None,
             "until_frame": args.until}, indent=1))
        print(f"wrote {len(order)} writes; first {order[0] if order else None},"
              f" last {order[-1] if order else None}")
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
