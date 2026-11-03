"""Read a live object's animation pointers from its record in WRAM.

Species code writes $8B-bank metasprite frame pointers into object fields
$28/$2A/$2E. Reading them from a live object gives the ROM address of that
species' frames directly - no disassembly and no guessing from screenshots.

Usage: python tools/dc_extract/object_record.py <take> <frame> [species_hex]
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
EXE = RECOMP / "build-trace" / "DemonsCrestSNESRecomp.exe"
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
OUT = Path(r"C:\Users\magno\OneDrive\Documentos\deepseek-harness"
           r"\default-workspace\dcbuild\out")
OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26
HP_ADDR, HP_MAX = 0x62, 10


def build_replay(take: Path, out_path: Path) -> None:
    samples = [json.loads(line) for line in
               (take / "input_log.jsonl").read_text().splitlines() if line.strip()]
    offset = samples[0]["gframe"] - samples[0]["frame"]
    lines = [json.dumps({"frame": f, "inputs": 0, "active": 3},
                        separators=(",", ":")) for f in range(offset)]
    for e in samples:
        lines.append(json.dumps({"frame": e["gframe"], "inputs": e["inputs"],
                                 "active": 3}, separators=(",", ":")))
    out_path.write_text("\n".join(lines) + "\n")


def main(take: Path, target: int, want: int | None) -> int:
    rec = OUT / f"{take.name}_replay.jsonl"
    build_replay(take, rec)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(OUT / "object_record.log", "wb")
    proc = subprocess.Popen([str(EXE), str(ROM)], cwd=str(RECOMP), env=env,
                            stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 90
        sock = None
        while time.monotonic() < deadline and sock is None:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                time.sleep(0.1)
        sock.settimeout(30)
        f = sock.makefile("rwb")

        def cmd(text):
            f.write((text + "\n").encode())
            f.flush()
            line = f.readline()
            return json.loads(line) if line else {}

        def read(addr, n):
            out = b""
            for a in range(addr, addr + n, 0x100):
                out += bytes.fromhex(
                    cmd(f"read_ram {a:x} 256")["hex"].replace(" ", ""))
            return out[:n]

        def fwd(p):
            return str(p).replace(chr(92), "/")

        cmd(f"replay_input {fwd(rec)}")
        while cmd("frame")["frame"] < target:
            cmd(f"write_ram {HP_ADDR:x} {HP_MAX:02x}")
            time.sleep(0.02)
        pool = read(OBJ_BASE, OBJ_STRIDE * OBJ_SLOTS)
        print("frame", cmd("frame")["frame"])
        for slot in range(OBJ_SLOTS):
            r = pool[slot * OBJ_STRIDE:(slot + 1) * OBJ_STRIDE]
            if r[0] == 0 or r[2] == 0:
                continue
            if want is not None and r[2] != want:
                continue
            print(f"slot {slot:2d} species {r[2]:02X} flags {r[0]:02X}")
            for row in range(0, 0x50, 16):
                print(f"   +{row:02X}: " + " ".join(f"{b:02X}" for b in r[row:row + 16]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    return 0


if __name__ == "__main__":
    take = Path(sys.argv[1])
    frame = int(sys.argv[2])
    species = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
    raise SystemExit(main(take, frame, species))
