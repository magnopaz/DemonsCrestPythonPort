#!/usr/bin/env python3
"""Cold boot, press Start, and record what the CPU says to the APU afterwards.

The boot capture showed the driver uploaded and then idle: no song command while
the game sits on its first screen. This probe finds the actual music trigger by
pressing buttons, recording every CPU->APU port write and measuring whether the
live DSP actually produced sound.
"""
from __future__ import annotations

import argparse, json, math, os, socket, struct, subprocess, sys, time, wave
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
    raise SystemExit("press_probe: no debug server")


def wav_rms(path: Path) -> float:
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
    if not raw:
        return 0.0
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    return math.sqrt(sum(v * v for v in s) / len(s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--boot-frames", type=int, default=600)
    ap.add_argument("--after-frames", type=int, default=900)
    ap.add_argument("--button", default="start")
    ap.add_argument("--port", type=int, default=4406)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(args.out / "press.log", "wb")
    proc = subprocess.Popen([str(RECOMP / "build-trace" / "DemonsCrestSNESRecomp"),
                             str(ROM), "--paused"],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    client = None
    try:
        client = connect(args.port)
        client.run_to(client.frame() + args.boot_frames)
        time.sleep(0.2)
        apu = client.cmd("get_apu_state")
        produced0 = int(client.cmd("audio_stats")["produced"])
        aram = bytes.fromhex(
            client.cmd("dump_apu_ram 0 65536")["hex"].replace(" ", ""))
        (args.out / "aram_before.bin").write_bytes(aram)
        print(f"before: pc={apu['spc']['pc']} produced={produced0}")

        # press the button for a few frames, then let the game settle
        client.cmd(f"set_controller {args.button}")
        client.run_to(client.frame() + 6)
        client.cmd("set_controller 0")
        client.run_to(client.frame() + args.after_frames)
        time.sleep(0.4)

        produced1 = int(client.cmd("audio_stats")["produced"])
        live = (args.out / "live.wav").resolve()
        count = min(4 * 32040, produced1)
        client.cmd(f"audio_wav {live} {produced1 - count} {count}")
        print(f"after : produced={produced1} live_rms={wav_rms(live):.1f}")

        events = client.cmd("audio_events 0 8000 2")["events"]
        lines = [f'{int(e["s"])} {int(e["adr"], 16)} {int(e["val"], 16)}'
                 for e in events if e["t"] == "cpu_wr"]
        after = [ln for ln in lines if int(ln.split()[0]) > produced0]
        (args.out / "ports_after.txt").write_text("\n".join(after) + "\n")
        print(f"cpu->apu writes after the capture point: {len(after)}")
        for ln in after[:24]:
            print("   ", ln)
        (args.out / "meta.json").write_text(json.dumps(
            {"produced0": produced0, "produced1": produced1,
             "pc": apu["spc"]["pc"], "button": args.button}, indent=1))
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
