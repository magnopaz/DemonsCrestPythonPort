#!/usr/bin/env python3
"""Capture per-species sprites from the recomp by injecting object records.

The guest's object loop treats bit 0 of an object's `$00` word as "run the
species init handler", so writing a minimal record into a free slot makes the
game initialise and draw that species in the current room. No area travel or
save state with live enemies is needed.

For each species the tool:

  1. starts the trace build paused with a fresh copy of the save state,
  2. dumps OAM once before injection to derive the world->screen offset from
     the player sprite (the guest restores the BG scroll registers after
     rendering, so the PPU scroll cannot be used directly),
  3. injects a record into the first object slot with `$00 = 1`,
  4. dumps OAM/CGRAM/VRAM/PPU at a few later frames,
  5. records the species, the object world position and the measured offset.

The extractor (`tools/dc_extract/extract_species.py`) turns these dumps into
per-species PNGs.

Usage:
  python3 tools/oracle/capture_species.py --rom "..." \
      --save DemonsCrestSNESRecomp/build-trace/saves/save0.sav \
      --species 0x57,0x67,0x2c --out captures/species
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
DEFAULT_SPECIES = [0x57, 0x67, 0x26, 0x07, 0x2C, 0x2D, 0x2E, 0x81, 0x10,
                   0x08, 0x49, 0x24, 0x33, 0xA5, 0x96]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path,
                    default=os.environ.get("RECOMP_DIR",
                                           str(ROOT.parent / "DemonsCrestSNESRecomp")))
    ap.add_argument("--rom", default=os.environ.get("ROM", ""))
    ap.add_argument("--save", default="")
    ap.add_argument("--out", type=Path, default=ROOT / "captures" / "species")
    ap.add_argument("--species", default="",
                    help="comma-separated species ids (hex or decimal)")
    ap.add_argument("--frames", default="2,4,8,12,20,30,45,60",
                    help="frames after injection to dump; longer samples are "
                         "needed for walk/attack cycles (default 2..60)")
    ap.add_argument("--port", type=int, default=4406)
    ap.add_argument("--settle", type=int, default=40)
    ap.add_argument("--timeout", type=float, default=120.0)
    return ap.parse_args()


def parse_ids(text: str) -> list[int]:
    if not text:
        return DEFAULT_SPECIES
    out = []
    for part in text.split(","):
        part = part.strip()
        if part:
            out.append(int(part, 0))
    return out


class Client:
    def __init__(self, sock: socket.socket):
        self._file = sock.makefile("rwb")

    def cmd(self, text: str) -> dict:
        self._file.write((text + "\n").encode())
        self._file.flush()
        line = self._file.readline()
        if not line:
            raise RuntimeError("debug server closed")
        return json.loads(line)

    def frame(self) -> int:
        return int(self.cmd("frame")["frame"])

    def run_to(self, target: int) -> None:
        self.cmd(f"run_to_frame {target}")
        deadline = time.monotonic() + 180.0
        while self.frame() < target:
            if time.monotonic() > deadline:
                raise RuntimeError(f"timeout waiting for frame {target}")
            time.sleep(0.01)
        time.sleep(0.04)

    def read(self, addr: int, n: int) -> bytes:
        return bytes.fromhex(
            self.cmd(f"read_ram {addr:x} {n}")["hex"].replace(" ", ""))

    def write(self, addr: int, data: bytes) -> None:
        self.cmd(f"write_ram {addr:x} {data.hex()}")

    def dump(self, command: str) -> bytes:
        return bytes.fromhex(self.cmd(command)["hex"].replace(" ", ""))


def connect(port: int, timeout: float) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"capture_species: no debug server on port {port}")


def fx(value: float) -> bytes:
    n = int(round(value * 256.0)) & 0xFFFFFF
    return bytes([n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF])


def world_pos(raw: bytes) -> tuple[float, float]:
    x = (raw[0] | (raw[1] << 8) | (raw[2] << 16)) / 256.0
    y = (raw[3] | (raw[4] << 8) | (raw[5] << 16)) / 256.0
    return x, y


def oam_visible_span(oam: bytes) -> tuple[float, float] | None:
    """Feet anchor of the visible palette-7 player group (before injection).

    The OAM low-table byte order is X, Y, tile, attr. Groups are split by
    proximity because some rooms draw another palette-7 object; the largest
    group before injection is the player in the normal case.
    """
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


def run_species(args, species: int, save: Path, rom: Path) -> dict | None:
    binary = Path(args.recomp) / "build-trace" / "DemonsCrestSNESRecomp.exe"
    if not binary.is_file():
        binary = Path(args.recomp) / "build-trace" / "DemonsCrestSNESRecomp"
    out = args.out / f"s{species:02x}"
    out.mkdir(parents=True, exist_ok=True)
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
        sock = connect(args.port, args.timeout)
        client = Client(sock)
        client.run_to(client.frame() + args.settle)
        player = world_pos(client.read(0x1030, 6))
        oam_before = client.dump("dump_oam")
        span = oam_visible_span(oam_before)
        if span is None:
            print(f"  species {species:#04x}: no player OAM, skipping")
            return None
        offset = (player[0] - span[0], player[1] - span[1])

        # Keep the injected object inside the 256px viewport. At the old
        # fixed +72, a player near the right edge put the object off-screen,
        # so the extractor captured whatever ambient sprite was at the
        # projected location instead.
        player_screen_x = player[0] - offset[0]
        side = 72.0 if player_screen_x < 160.0 else -72.0
        rec = bytearray(0x50)
        rec[0x00] = 0x01
        rec[0x02] = species
        rec[0x0A] = 0x30
        rec[0x26] = 0x40
        rec[0x30:0x33] = fx(player[0] + side)
        rec[0x33:0x36] = fx(player[1] - 16.0)
        rec[0x37] = 0x1F
        client.write(0x1080, bytes(rec))

        frames = []
        for step in [int(x) for x in args.frames.split(",") if x.strip()]:
            client.run_to(client.frame() + step)
            slot = client.read(0x1080, 0x50)
            if not slot[0]:
                continue
            state = {
                "species": species,
                "frame": client.frame(),
                "slot": slot.hex(),
                "object_world": list(world_pos(bytes([slot[0x30], slot[0x31],
                                                      slot[0x32], slot[0x33],
                                                      slot[0x34], slot[0x35]]))),
                "player_world": list(world_pos(client.read(0x1030, 6))),
                "offset": list(offset),
                "ppu": client.cmd("get_ppu_state"),
                "oam": client.dump("dump_oam").hex(),
                "cgram": client.dump("dump_cgram").hex(),
            }
            vram = client.dump("dump_vram")
            (out / f"f{state['frame']:06d}.json").write_text(json.dumps(state))
            (out / f"f{state['frame']:06d}.vram.bin").write_bytes(vram)
            frames.append(state["frame"])
        if not frames:
            print(f"  species {species:#04x}: object did not stay active")
            return None
        print(f"  species {species:#04x}: {len(frames)} frames "
              f"(object at {world_pos(bytes([slot[0x30], slot[0x31], slot[0x32], slot[0x33], slot[0x34], slot[0x35]]))})")
        return {"species": species, "frames": frames,
                "offset": list(offset), "offset_v2": True,
                "player": list(player)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        tmp_save.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    rom = Path(args.rom).resolve() if args.rom else None
    if not rom or not rom.is_file():
        raise SystemExit("capture_species: pass --rom or set ROM")
    save = Path(args.save) if args.save else (
        Path(args.recomp) / "build-trace" / "saves" / "save0.sav")
    if not save.is_file():
        raise SystemExit(f"capture_species: missing save {save}")
    save = save.resolve()
    # The recomp process runs with its own cwd, so every path handed to it
    # (`--resume-state`) must be absolute.
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    species = parse_ids(args.species)

    manifest = {"save": str(save), "rom": str(rom), "species": {}}
    for sid in species:
        print(f"capture_species: {sid:#04x}")
        try:
            result = run_species(args, sid, save, rom)
        except Exception as exc:  # a bad init can wedge the guest; keep going
            print(f"  species {sid:#04x}: FAILED ({exc})")
            result = None
        if result:
            manifest["species"][f"{sid:02x}"] = result
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"capture_species: {len(manifest['species'])}/{len(species)} "
          f"species captured -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
