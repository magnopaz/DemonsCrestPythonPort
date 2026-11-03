#!/usr/bin/env python3
"""Recover a species' metasprite pointers from the live object record.

The object loop runs a species init when bit 0 of an object's `$00` word is
set, so writing a minimal record into a free slot makes the guest initialise
that species in place.  The init writes `$8B`-bank frame pointers into record
fields `$28/$2A/$2E` (and sometimes `$24/$26`); those point into the metasprite
block at the end of bank `$8B` and are the authoritative species -> art map.

This probe injects one species, then samples the record while the object is
alive, printing every field that changes and every value that looks like a
`$8B`-bank pointer.  It also keeps the OAM/CGRAM/VRAM of the sample frame so a
capture can be compared with the ROM composition.

Usage:
  python3 tools/oracle/dump_species_metasprite.py --species 0x57,0x10,0x67
  python3 tools/oracle/dump_species_metasprite.py --species 0x81 --out /tmp/probe
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

OBJ_BASE = 0x1080
OBJ_STRIDE = 0x50
OBJ_SLOTS = 26
PTR_FIELDS = (0x24, 0x26, 0x28, 0x2A, 0x2C, 0x2E)


class Client:
    def __init__(self, sock: socket.socket):
        self.f = sock.makefile("rwb")
        self.sock = sock

    def cmd(self, text: str) -> dict:
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("debug server closed")
        msg = json.loads(line)
        if "error" in msg:
            raise RuntimeError(f"{text!r}: {msg['error']}")
        return msg

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int) -> None:
        if self.frame() >= target:
            return
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 300
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.005)

    def read(self, addr: int, n: int) -> bytes:
        return bytes.fromhex(
            self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def write(self, addr: int, data: bytes) -> None:
        self.cmd(f"write_ram {addr:x} {data.hex()}")

    def dump(self, command: str) -> bytes:
        return bytes.fromhex(self.cmd(command)["hex"].replace(" ", ""))


def connect(port: int, timeout: float) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return Client(socket.create_connection(("127.0.0.1", port),
                                                   timeout=3))
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"no debug server on port {port}")


def ppu_inidisp(client: Client) -> int:
    raw = client.cmd("get_ppu_state")
    ppu = raw.get("ppu", raw)
    try:
        return int(str(ppu.get("inidisp", "0x80")), 16)
    except ValueError:
        return 0x80


def wait_visible(client: Client, frames: int = 240) -> bool:
    for _ in range(frames):
        if (ppu_inidisp(client) & 0x0F) >= 0x0C:
            return True
        client.run_to(client.frame() + 1)
    return False


def fx(value: float) -> bytes:
    n = int(round(value * 256.0)) & 0xFFFFFF
    return bytes([n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF])


def world_pos(raw: bytes) -> tuple[float, float]:
    x = (raw[0] | (raw[1] << 8) | (raw[2] << 16)) / 256.0
    y = (raw[3] | (raw[4] << 8) | (raw[5] << 16)) / 256.0
    return x, y


def oam_visible_span(oam: bytes) -> tuple[float, float] | None:
    """Feet anchor of the largest palette-7 OAM cluster (the player)."""
    if len(oam) != 0x220:
        return None
    groups: list[list[tuple[int, int, int]]] = []
    for i in range(128):
        x = oam[i * 4]
        y = oam[i * 4 + 1]
        attr = oam[i * 4 + 3]
        hi = oam[0x200 + i // 4]
        x |= ((hi >> ((i % 4) * 2)) & 1) << 8
        if x >= 256:
            x -= 512
        size = 16 if ((hi >> ((i % 4) * 2 + 1)) & 1) else 8
        if y >= 224 or ((attr >> 1) & 7) != 7:
            continue
        for group in groups:
            if any(abs(x - gx) < 40 and abs(y - gy) < 64
                   for gx, gy, _s in group):
                group.append((x, y, size))
                break
        else:
            groups.append([(x, y, size)])
    if not groups:
        return None
    best = max(groups, key=len)
    min_x = min(x for x, _y, _s in best)
    max_x = max(x + s for x, _y, s in best)
    max_y = max(y + s for _x, y, s in best)
    return ((min_x + max_x) / 2.0, float(max_y))


def probe(args, species: int) -> dict | None:
    out = args.out / f"s{species:02x}"
    out.mkdir(parents=True, exist_ok=True)
    resume = Path(args.recomp) / f"_dc_species_{args.port}.sav"
    shutil.copyfile(args.save, resume)
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(args.port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(out / "capture.log", "wb")
    proc = subprocess.Popen(
        [str(Path(args.recomp) / "build-trace" / "DemonsCrestSNESRecomp"),
         str(args.rom), "--paused", "--resume-state", str(resume)],
        cwd=str(args.recomp), env=env, stdout=log, stderr=log)
    try:
        client = connect(args.port, 120.0)
        wait_visible(client)
        client.run_to(client.frame() + args.settle)
        player = world_pos(client.read(0x1030, 6))
        span = oam_visible_span(client.dump("dump_oam"))
        offset = (player[0] - span[0], player[1] - span[1]) if span else (0.0, 0.0)
        screen_x = player[0] - offset[0]
        side = 72.0 if screen_x < 160.0 else -72.0

        rec = bytearray(OBJ_STRIDE)
        rec[0x00] = 0x01
        rec[0x02] = species
        rec[0x0A] = 0x30
        rec[0x26] = 0x40
        rec[0x30:0x33] = fx(player[0] + side)
        rec[0x33:0x36] = fx(player[1] - 16.0)
        rec[0x37] = 0x1F
        client.write(OBJ_BASE, bytes(rec))

        samples = []
        first = None
        for step in [int(x) for x in args.frames.split(",") if x.strip()]:
            client.run_to(client.frame() + step)
            slot = client.read(OBJ_BASE, OBJ_STRIDE)
            if not slot[0]:
                samples.append({"frame": client.frame(), "alive": False})
                continue
            if first is None:
                first = slot
            ptrs = {}
            for f in PTR_FIELDS:
                v = slot[f] | (slot[f + 1] << 8)
                if v:
                    ptrs[f"${f:02X}"] = f"${v:04X}"
            sample = {
                "frame": client.frame(),
                "alive": True,
                "flags": f"${slot[0]:02X}",
                "record": slot.hex(),
                "ptrs": ptrs,
                "world": list(world_pos(bytes([slot[0x30], slot[0x31],
                                               slot[0x32], slot[0x33],
                                               slot[0x34], slot[0x35]]))),
            }
            # The draw routine $80:D9A7 reads a group id byte through the
            # per-object script pointer in record +$14, so dump that script
            # (it lives in low WRAM) and the low WRAM page around it.
            script_ptr = slot[0x14] | (slot[0x15] << 8)
            sample["script_ptr"] = f"${script_ptr:04X}"
            if script_ptr:
                sample["script"] = client.read(script_ptr, 48).hex()
            if first is slot or len(samples) == 0:
                sample["wram_low"] = client.read(0, 0x200).hex()
            if len(samples) == 0 or args.dump:
                sample["oam"] = client.dump("dump_oam").hex()
                sample["cgram"] = client.dump("dump_cgram").hex()
                (out / f"f{client.frame():06d}.vram.bin").write_bytes(
                    client.dump("dump_vram"))
            samples.append(sample)
        data = {"species": species, "player": list(player),
                "offset": list(offset), "samples": samples}
        (out / "probe.json").write_text(json.dumps(data, indent=1))
        return data
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        resume.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path,
                    default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--save", type=Path,
                    default=DEFAULT_RECOMP / "build-trace" / "saves" / "save0.sav")
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "species_probe")
    ap.add_argument("--species", default="0x57")
    ap.add_argument("--frames", default="2,4,8,12,20,30,45,60")
    ap.add_argument("--port", type=int, default=4417)
    ap.add_argument("--settle", type=int, default=40)
    ap.add_argument("--dump", action="store_true",
                    help="dump OAM/CGRAM/VRAM at every sample")
    args = ap.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    args.save = args.save.resolve()
    args.rom = args.rom.resolve()
    ids = [int(p, 0) for p in args.species.split(",") if p.strip()]

    summary = {}
    for sid in ids:
        print(f"== species {sid:#04x}")
        try:
            data = probe(args, sid)
        except Exception as exc:  # noqa: BLE001 - one bad init can wedge the guest
            print(f"   FAILED ({exc})")
            continue
        if not data:
            continue
        seen = {}
        for s in data["samples"]:
            if not s.get("alive"):
                print(f"   f{s['frame']}: dead")
                continue
            key = tuple(sorted(s["ptrs"].items()))
            if key not in seen:
                seen[key] = s
                print(f"   f{s['frame']}: flags={s['flags']} "
                      f"ptrs={s['ptrs']} world={s['world']}")
        summary[f"{sid:02x}"] = {k: v["ptrs"] for k, v in
                                 ((s["frame"], s) for s in data["samples"]
                                  if s.get("alive"))}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
