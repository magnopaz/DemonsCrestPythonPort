#!/usr/bin/env python3
"""Extract a playable room from a Demon's Crest (USA) ROM + recomp dump.

The native game does not read the ROM at runtime. This tool bakes the data it
needs into `assets/generated/`:

  * the 64x32 BG tilemaps as loaded in VRAM at the captured frame
  * per-palette 4bpp tile atlases
  * per-palette OBJ tile atlases
  * the player and item sprites composed from OAM
  * a collision grid built from the ROM's block-attribute table

All output is ROM-derived and must stay out of version control.

Usage:
  python3 tools/dc_extract/extract.py \
    --rom "/path/to/Demon's Crest (USA).sfc" \
    --dump captures/graveyard --prefix stage_600 \
    --area 1 --screens 9,10 --out assets/generated
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROM_SHA256 = "18d40a807d5f88c5b6a1ad849eec7e0f189225d9a1586037c850f6680b5844de"
ROM_CRC32 = 0xE8236AD2

# OAM sprite-size table indexed by OBSEL bits 5..7.
OBJ_SIZES = ((8, 16), (8, 32), (8, 64), (16, 32),
             (16, 64), (32, 64), (16, 32), (16, 32))


def lo(bank: int, addr: int) -> int:
    """LoROM SNES address -> file offset."""
    return ((bank & 0x7F) << 15) | (addr & 0x7FFF)


class Rom:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        if len(self.data) == 0x200000 + 512:
            self.data = self.data[512:]  # copier header
        if len(self.data) != 0x200000:
            raise SystemExit(f"ROM must be 2 MiB (got {len(self.data)} bytes)")
        sha = hashlib.sha256(self.data).hexdigest()
        if sha != ROM_SHA256:
            raise SystemExit(f"unexpected ROM SHA-256:\n  {sha}\n  {ROM_SHA256}")
        self.sha256 = sha

    def u8(self, bank: int, addr: int) -> int:
        return self.data[lo(bank, addr)]

    def u16(self, bank: int, addr: int) -> int:
        return struct.unpack_from("<H", self.data, lo(bank, addr))[0]

    # -- level tables -----------------------------------------------------
    def area_info(self, area: int):
        p = self.u16(0x81, 0xA291 + area * 2)
        set_id = self.u8(0x81, p)
        count = self.u8(0x81, p + 1)
        screens = [self.u8(0x81, p + 2 + k) for k in range(count)]
        q = self.u16(0x81, 0xA6D8 + area * 2)
        w, h = self.u8(0x81, q), self.u8(0x81, q + 1)
        grid = [[self.u8(0x81, q + 2 + y * w + x) for x in range(w)]
                for y in range(h)]
        return {"set": set_id, "screens": screens, "grid": grid,
                "width": w, "height": h}

    def screen_blocks(self, set_id: int, screen: int):
        """16x16 block ids for a screen, expanded from 2x2 superblocks."""
        out = [[0] * 16 for _ in range(16)]
        for k in range(64):
            sb = self.u16(0x8F + set_id, 0x8000 + screen * 128 + k * 2)
            sx, sy = (k % 8) * 2, (k // 8) * 2
            for j in range(4):
                b = self.u16(0x92 + set_id, 0x8000 + sb * 8 + j * 2)
                out[sy + j // 2][sx + j % 2] = b
        return out

    def block_attr(self, set_id: int, block: int) -> int:
        return self.u8(0x98, 0x8000 + (set_id << 12) + block)

    def block_tiles(self, set_id: int, block: int):
        return tuple(self.u16(0x95 + set_id, 0x8000 + block * 8 + j * 2)
                     for j in range(4))

    def screen_tilemap(self, set_id: int, screen: int):
        """32x32 tilemap words for one screen, built from its block table."""
        out = [[0] * 32 for _ in range(32)]
        blocks = self.screen_blocks(set_id, screen)
        for by in range(16):
            for bx in range(16):
                tiles = self.block_tiles(set_id, blocks[by][bx])
                for j, word in enumerate(tiles):
                    out[by * 2 + j // 2][bx * 2 + j % 2] = word
        return out

    def object_list(self, index: int):
        """Read one entry of the 3-byte-pointer object-list table at $81:C874.

        Records are 6 bytes: species, flags, X (u16), Y (u16). The high Y
        byte carries the screen-row offset (256 per row).
        """
        base = 0xC874 + index * 3
        ptr = self.u16(0x81, base)
        bank = self.u8(0x81, base + 2)
        offset = lo(bank, ptr)
        count = self.data[offset]
        if count > 64:
            count = 0
        records = []
        for k in range(count):
            start = offset + 1 + k * 6
            rec = self.data[start:start + 6]
            if len(rec) != 6:
                break
            records.append({
                "species": rec[0],
                "flags": rec[1],
                "x": rec[2] | (rec[3] << 8),
                "y": rec[4] | (rec[5] << 8),
            })
        return records

    # -- ROM CHR decompressor ($80:C28C / $80:C2AF / $80:C300) ------------
    def decompress_stream(self, bank: int, addr: int, calls: int) -> bytes:
        """Run $80:C300 `calls` times (16 output bytes per call)."""
        out = bytearray()
        for _ in range(calls):
            def rb() -> int:
                nonlocal bank, addr
                b = self.data[lo(bank, addr)]
                addr += 1
                if addr > 0xFFFF:
                    addr = 0x8000
                    bank += 1
                return b
            m0, m1, fill = rb(), rb(), rb()
            for mask in (m0, m1):
                for bit in range(7, -1, -1):
                    out.append(rb() if ((mask >> bit) & 1) else fill)
        return bytes(out)

    def decompress_d000_into(self, raw_vram: bytearray, dst: int,
                             d000_off: int) -> int:
        """Decompress one $98:D000 entry (16x16 units) via $80:C2AF layout."""
        off = lo(0x98, 0xD000 + d000_off)
        p_lo, p_hi, bank, cnt = struct.unpack_from("<BBBB", self.data, off)
        addr = p_lo | (p_hi << 8)
        for _ in range(cnt):
            for half in range(2):
                cur = dst ^ (0x200 if half else 0)
                chunk = self.decompress_stream(bank, addr, 4)
                # Advance bank/addr by re-running the exact stream steps:
                for _call in range(4):
                    m0 = self.data[lo(bank, addr)]
                    m1 = self.data[lo(bank, addr + 1 if addr < 0xFFFF else 0x8000)]
                    step = 3 + bin(m0).count("1") + bin(m1).count("1")
                    for _s in range(step):
                        addr += 1
                        if addr > 0xFFFF:
                            addr = 0x8000
                            bank += 1
                raw_vram[cur:cur + 64] = chunk
            dst += 0x40
            if dst & 0x200:
                dst += 0x200
        return dst

    def decompress_area_bg_vram(self, area: int) -> list[int]:
        """Decompress BG CHR for `area` via $BD:A04A -> $98:C000 ($80:C28C)."""
        raw = bytearray(0x10000)
        y = self.u16(0xBD, 0xA04A + area * 2)
        dst = 0x0200
        while True:
            x = self.u16(0xBD, y)
            if x & 0x8000:
                break
            cnt = self.u8(0xBD, y + 2)
            off = lo(0x98, 0xC000 + x)
            p_lo, p_hi, bank = self.data[off:off + 3]
            ptr = p_lo | (p_hi << 8)
            chunk = self.decompress_stream(bank, ptr, cnt * 0x20)
            end = min(len(raw), dst + len(chunk))
            raw[dst:end] = chunk[:end - dst]
            dst = end
            y += 3
        return list(struct.unpack("<32768H", raw))

    def decompress_area_obj_vram(self, area: int) -> tuple[list[int], dict[int, int]]:
        """Decompress 16 KiB OBJ CHR ($80:BEF2) and map $81:AE11 slots to base tiles."""
        raw = bytearray(0x4000)
        flags = self.u8(0x81, 0xAD9D + area)
        dst = 0x0000
        slot_tile: dict[int, int] = {}
        if flags & 0x01:
            dst = 0x0C00
            slot_tile[0x00] = 0x000
            slot_tile[0x02] = 0x020
            slot_tile[0x04] = 0x040
        if flags & 0x08:
            slot_tile[0x06] = dst // 32
            dst = self.decompress_d000_into(raw, dst, 0x00)
        if flags & 0x02:
            slot_tile[0x08] = dst // 32
            dst = self.decompress_d000_into(raw, dst, 0xC8)
        if flags & 0x04:
            slot_tile[0x0A] = dst // 32
            dst = self.decompress_d000_into(raw, dst, 0x24)
        if dst < 0x1800:
            dst = 0x1800
        y = self.u16(0xBD, 0x9953 + area * 2)
        ae_slot = 0x02
        while True:
            x = self.u16(0xBD, y)
            if x & 0x8000:
                break
            slot_tile[0x10 + ae_slot] = dst // 32
            dst = self.decompress_d000_into(raw, dst, x)
            ae_slot += 2
            y += 2
        return list(struct.unpack("<8192H", raw)), slot_tile

    def parse_metasprite_group(self, group_id: int) -> list[list[dict]]:
        """Decode one metasprite group from $8B:8000 ($80:D9A7)."""
        off = self.u16(0x8B, 0x8000 + group_id * 3)
        b_delta = self.u8(0x8B, 0x8000 + group_id * 3 + 2)
        addr = 0x8000 + off
        bank = 0x8B + b_delta + (1 if addr > 0xFFFF else 0)
        addr = (addr & 0x7FFF) | 0x8000

        def rb() -> int:
            nonlocal bank, addr
            b = self.data[lo(bank, addr)]
            addr += 1
            if addr > 0xFFFF:
                addr = 0x8000
                bank += 1
            return b

        def s8(v: int) -> int:
            return v - 256 if v >= 128 else v

        nframes = rb()
        for _ in range(nframes * 2):
            rb()  # output offset words in $7F:1000
        frames = []
        for _ in range(nframes):
            nparts = rb()
            parts = []
            for _ in range(nparts):
                dx, dxf, dy, tile, attr = s8(rb()), s8(rb()), s8(rb()), rb(), rb()
                parts.append({
                    "dx": dx,
                    "dx_flip": dxf,
                    "dy": dy,
                    "tile": tile,
                    "attr": attr,
                    "size": 16 if (attr & 0x10) else 8,
                    "hflip": bool(attr & 0x40),
                    "vflip": bool(attr & 0x80),
                })
            frames.append(parts)
        return frames

    def area_spawns(self, area: int) -> list[dict]:
        """Read 5-byte spawn records for `area` from $81:A1A9."""
        p = self.u16(0x81, 0xA1A9 + area * 2)
        next_p = self.u16(0x81, 0xA1A9 + (area + 1) * 2)
        count = max(1, (next_p - p) // 5) if next_p > p else 1
        spawns = []
        for k in range(min(count, 8)):
            sx = self.u16(0x81, p + k * 5)
            sy = self.u16(0x81, p + k * 5 + 2)
            flags = self.u8(0x81, p + k * 5 + 4)
            if sx > 4096 or sy > 8192:
                continue
            spawns.append({"x": sx, "y": sy, "flags": flags})
        return spawns or [{"x": 64, "y": 164, "flags": 0}]

    def area_transitions(self, area: int) -> list[dict]:
        """Read 10-byte bounding-box transition records from $81:981A."""
        p = self.u16(0x81, 0x981A + area * 2)
        if p < 0x8000:
            return []
        count = self.u8(0x81, p)
        if count == 0 or count > 16:
            return []
        out = []
        for k in range(count):
            off = lo(0x81, p + 1 + k * 10)
            nxt_8d, spawn_id, pad_mask, cx, cy, hw, hh, ttype = struct.unpack_from(
                "<BBBHHBBB", self.data, off)
            if nxt_8d > 0xF3 or cx > 4096 or cy > 4096 or hw == 0 or hh == 0:
                continue
            out.append({
                "next_area": nxt_8d // 2 if nxt_8d < 0xF0 else -1,
                "next_8d": nxt_8d,
                "spawn_id": spawn_id,
                "pad_mask": pad_mask,
                "x": cx,
                "y": cy,
                "half_w": hw,
                "half_h": hh,
                "type": ttype,
            })
        return out

    def gate_next_area(self, area: int) -> int:
        """Read $81:97DA boss-gate target area (-1 when >= 0xF0 overworld exit)."""
        nxt_8d = self.u8(0x81, 0x97DA + area)
        return nxt_8d // 2 if nxt_8d < 0xF0 else -1

    def gargoyle_palettes(self) -> list[list[list[int]]]:
        """Extract the 6 Gargoyle form palettes from $99:9100..91BF."""
        forms = []
        for form in range(6):
            off = lo(0x99, 0x9100 + form * 32)
            words = struct.unpack_from("<16H", self.data, off)
            colors = [[(c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8]
                      for c in words]
            forms.append(colors)
        return forms


def read_vram(path: Path) -> list[int]:
    raw = path.read_bytes()
    if len(raw) != 0x10000:
        raise SystemExit(f"{path}: expected 64 KiB VRAM dump")
    return list(struct.unpack("<32768H", raw))


def read_cgram(path: Path) -> list[tuple[int, int, int]]:
    raw = path.read_bytes()
    if len(raw) != 0x200:
        raise SystemExit(f"{path}: expected 512-byte CGRAM dump")
    return cgram_colors(raw)


def cgram_colors(raw: bytes) -> list[tuple[int, int, int]]:
    words = struct.unpack("<256H", raw)
    return [((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
            for c in words]


def _hex_reg(value) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def read_capture_frame(capture_dir: Path, frame: int):
    """Load one `capture_anim.py` frame: VRAM, CGRAM and the PPU BG registers.

    `capture_anim.py` writes `fNNNNNN.json` (per-frame CPU/PPU/OAM/CGRAM state)
    and `fNNNNNN.vram.bin` (64 KiB VRAM). This is the same oracle data the
    Stage-1 dump provides, so a captured frame can bake an area's BG2 backdrop
    and atlas without a hand-made VRAM capture.
    """
    state_path = capture_dir / f"f{frame:06d}.json"
    vram_path = capture_dir / f"f{frame:06d}.vram.bin"
    if not state_path.is_file() or not vram_path.is_file():
        raise SystemExit(f"capture frame {frame} not found in {capture_dir}")
    state = json.loads(state_path.read_text())
    ppu = state.get("ppu", {})
    regs = {
        "bgsc": [_hex_reg(x) for x in ppu.get("bgXsc", [0, 0, 0, 0])],
        "hscroll": [int(x) for x in ppu.get("hScroll", [0, 0, 0, 0])],
        "vscroll": [int(x) for x in ppu.get("vScroll", [0, 0, 0, 0])],
    }
    raw_cgram = bytes.fromhex(state["cgram"].replace(" ", ""))
    if len(raw_cgram) != 0x200:
        raise SystemExit(f"{state_path}: expected 512-byte CGRAM blob")
    vram = read_vram(vram_path)
    return vram, cgram_colors(raw_cgram), regs


def load_bg2_captures(path: Path | None) -> dict[int, dict]:
    """Read the area -> capture-frame manifest used for per-area BG2 backdrops.

    Format::

        {"areas": {"3": {"dir": "captures/anim", "frame": 20614}}}

    Every area with an entry gets that frame's BG2 tilemap, palette and atlas
    instead of the transparent placeholder layer. This is the interim path
    until the ROM-side BG2 generator is decoded; see docs/PROJECT_STATE.md.
    """
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text())
    root = Path(__file__).resolve().parents[2]
    out: dict[int, dict] = {}
    for key, entry in raw.get("areas", {}).items():
        area = int(key)
        cap_dir = Path(entry["dir"])
        if not cap_dir.is_absolute():
            cap_dir = root / cap_dir
        frame = int(entry["frame"])
        if not (cap_dir / f"f{frame:06d}.json").is_file():
            print(f"bg2 capture for area {area} missing "
                  f"({cap_dir}/f{frame:06d}.json); skipping")
            continue
        vram, cgram, regs = read_capture_frame(cap_dir, frame)
        # BG2 is streamed per screen, so a single frame only holds the window
        # the camera currently sees (the rest is zero -> black gaps). Merge the
        # CHR/tilemap words across sampled frames of the same capture so the
        # backdrop covers more of the room.
        merge = int(os.environ.get("DC_BG2_MERGE_FRAMES", "40"))
        if merge > 1:
            frames = sorted(cap_dir.glob("f*.json"))
            step = max(1, len(frames) // merge)
            merged = list(vram)
            for other in frames[::step][:merge]:
                try:
                    n = int(other.stem[1:])
                except ValueError:
                    continue
                if n == frame:
                    continue
                try:
                    ovram, _ocgram, _oregs = read_capture_frame(cap_dir, n)
                except Exception:
                    continue
                for i, w in enumerate(ovram):
                    if not merged[i] and w:
                        merged[i] = w
            vram = merged
            print(f"bg2 capture area {area}: merged {min(merge, len(frames[::step]))} "
                  f"frames for CHR/tilemap coverage")
        out[area] = {"vram": vram, "cgram": cgram, "regs": regs,
                     "dir": cap_dir, "frame": frame}
    return out


def tile_pixels(vram: list[int], tile_word: int, bpp: int = 4) -> list[list[int]]:
    """Decode one 8x8 tile at a VRAM word address."""
    rows = []
    for y in range(8):
        w0 = vram[(tile_word + y) & 0x7FFF]
        w1 = vram[(tile_word + 8 + y) & 0x7FFF]
        row = []
        for x in range(8):
            bit = 7 - x
            px = ((w0 >> bit) & 1) | (((w0 >> (8 + bit)) & 1) << 1)
            if bpp >= 4:
                px |= (((w1 >> bit) & 1) << 2) | (((w1 >> (8 + bit)) & 1) << 3)
            row.append(px)
        rows.append(row)
    return rows


def make_bg_atlas(vram: list[int], cgram, palette: int, base_word: int = 0) -> Image.Image:
    """32x32 tiles, 8x8 each, in four 256x256 flip quadrants.

    Quadrants: normal (0,0), H (256,0), V (0,256), HV (256,256).
    Pre-flipping avoids relying on negative source rectangles in the renderer.
    """
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    px = img.load()
    for tile in range(1024):
        tx, ty = (tile % 32) * 8, (tile // 32) * 8
        rows = tile_pixels(vram, base_word + tile * 16)
        for y, row in enumerate(rows):
            for x, p in enumerate(row):
                if not p:
                    continue
                color = (*cgram[palette * 16 + p], 255)
                for qx, qy, fx, fy in ((0, 0, False, False),
                                       (256, 0, True, False),
                                       (0, 256, False, True),
                                       (256, 256, True, True)):
                    sx = 7 - x if fx else x
                    sy = 7 - y if fy else y
                    px[qx + tx + sx, qy + ty + sy] = color
    return img


def make_heart_sprite(scale: int = 1, pulse: bool = False) -> Image.Image:
    """Original placeholder heart pickup (replaced when the ROM heart OAM is baked)."""
    pattern = [
        "..###..###..",
        ".#####.#####.",
        "############",
        "############",
        ".##########.",
        "..########..",
        "...######...",
        "....####....",
        ".....##.....",
    ]
    if pulse:
        pattern = ["." + row + "." for row in pattern]
    w = len(pattern[0]) * scale
    h = len(pattern) * scale
    img = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(pattern):
        for x, ch in enumerate(row):
            if ch != "#":
                continue
            for sy in range(scale):
                for sx in range(scale):
                    px[1 + x * scale + sx, 1 + y * scale + sy] = (232, 60, 84, 255)
    # A one-pixel dark outline around the silhouette.
    out = img.copy()
    op = out.load()
    for y in range(img.height):
        for x in range(img.width):
            if px[x, y][3]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < img.width and 0 <= ny < img.height and px[nx, ny][3]:
                    op[x, y] = (48, 16, 24, 255)
                    break
    return out


def make_enemy_sprite(frame: int = 0) -> Image.Image:
    """Original placeholder graveyard ghoul (species $67) until its OAM is baked."""
    pattern = [
        "....####....",
        "...######...",
        "..##.##.##..",
        "..########..",
        "...##.##....",
        "...######...",
        "..##.##.##..",
        ".##.####.##.",
        "..#.####.#..",
        "...######...",
        "....####....",
        ".....##.....",
        ".....##.....",
        "....#..#....",
        "...#....#...",
        "..#......#..",
    ]
    if frame:
        pattern = [
            "....####....",
            "...######...",
            "..##.##.##..",
            "..########..",
            "...##.##....",
            "...######...",
            "..##.##.##..",
            ".####.####..",
            ".#.####.##..",
            "...######...",
            "....####....",
            ".....##.....",
            ".....##.....",
            "....#..#....",
            "...#....#...",
            ".##......##.",
        ]
    w, h = len(pattern[0]) + 2, len(pattern) + 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    bone = (216, 208, 168, 255)
    shade = (104, 96, 72, 255)
    for y, row in enumerate(pattern):
        for x, ch in enumerate(row):
            if ch != "#":
                continue
            px[1 + x, 1 + y] = shade if (x + y) % 7 == 0 else bone
    # Red eye socket.
    px[5, 4] = (208, 32, 40, 255)
    px[9, 4] = (208, 32, 40, 255)
    return img


def make_obj_atlas(vram: list[int], cgram, obj_base_word: int, palette: int) -> Image.Image:
    """16x16 tiles, 8x8 each -> 128x128 RGBA. Palette 0 pixel is transparent."""
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    px = img.load()
    for tile in range(256):
        tx, ty = (tile % 16) * 8, (tile // 16) * 8
        for y, row in enumerate(tile_pixels(vram, obj_base_word + tile * 16)):
            for x, p in enumerate(row):
                if p:
                    px[tx + x, ty + y] = (*cgram[0x80 + palette * 16 + p], 255)
    return img


def tilemap_linear(vram: list[int], bgsc: int) -> tuple[int, int, list[int]]:
    """Linearize a SNES BG tilemap (32/64 x 32/64) into world order."""
    base = (bgsc & 0xFC) << 8
    wide = bool(bgsc & 1)
    high = bool(bgsc & 2)
    w = 64 if wide else 32
    h = 64 if high else 32
    out = []
    for y in range(h):
        for x in range(w):
            page_x = 0x400 if (wide and x >= 32) else 0
            if high:
                page_y = 0x800 if (wide and y >= 32) else (0x400 if y >= 32 else 0)
            else:
                page_y = 0
            out.append(vram[(base + page_x + page_y + (y & 31) * 32 + (x & 31)) & 0x7FFF])
    return w, h, out


class OamSprite:
    def __init__(self, index: int, x: int, y: int, size: int, tile: int,
                 palette: int, hflip: bool, vflip: bool):
        self.index = index
        self.x, self.y, self.size = x, y, size
        self.tile, self.palette = tile, palette
        self.hflip, self.vflip = hflip, vflip


def parse_oam(oam: bytes, obsel: int) -> list[OamSprite]:
    if len(oam) != 0x220:
        raise SystemExit("OAM dump must be 544 bytes")
    obj_base = (obsel & 7) << 13
    small, large = OBJ_SIZES[(obsel >> 5) & 7]
    out = []
    for i in range(128):
        oam0, oam1 = struct.unpack_from("<HH", oam, i * 4)
        y = oam0 >> 8
        x = oam0 & 0xFF
        hi = oam[0x200 + (i // 4)]
        x |= ((hi >> ((i % 4) * 2)) & 1) << 8
        if x >= 256:
            x -= 512
        size = large if ((hi >> ((i % 4) * 2 + 1)) & 1) else small
        tile = oam1 & 0xFF
        # Attribute bit 0 is the ninth tile-number bit for 16x16 and larger
        # sprites. It lives in the attribute byte (oam1 >> 8), not in the tile
        # byte: reading the tile byte's LSB silently dropped the 0x100 half of
        # every sprite whose attributes have bit 0 set (the Hippogriff's whole
        # sheet), which composed as scattered tiles.
        if size >= 16:
            tile |= ((oam1 >> 8) & 1) << 8
        out.append(OamSprite(i, x, y, size, tile,
                             (oam1 >> 9) & 7, bool(oam1 & 0x4000),
                             bool(oam1 & 0x8000)))
    return out


def compose_oam(vram: list[int], cgram,
                sprites: list[OamSprite],
                palette_override: int | None = None) -> tuple[Image.Image, int, int]:
    """Compose a group of OAM sprites into one RGBA image.

    The returned image is anchored at (min_x, min_y) in screen coordinates.
    `palette_override` is used when the game has already restored CGRAM by the
    time the dump was written (the player palette is one such case).
    """
    if not sprites:
        raise SystemExit("no OAM sprites to compose")
    min_x = min(s.x for s in sprites)
    min_y = min(s.y for s in sprites)
    max_x = max(s.x + s.size for s in sprites)
    max_y = max(s.y + s.size for s in sprites)
    img = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    px = img.load()
    for s in sorted(sprites, key=lambda s: s.index, reverse=True):
        pal = s.palette if palette_override is None else palette_override
        for row in range(s.size):
            for col in range(s.size):
                used_col = s.size - 1 - col if s.hflip else col
                used_row = s.size - 1 - row if s.vflip else row
                used_tile = (((s.tile >> 4) + (used_row >> 3)) << 4) | \
                            (((s.tile & 0x0F) + (used_col >> 3)) & 0x0F)
                # The caller passes a VRAM slice already rebased to OBJ tile 0.
                p = tile_pixels(vram, used_tile * 16)[used_row & 7][used_col & 7]
                if p:
                    px[s.x - min_x + col, s.y - min_y + row] = \
                        (*cgram[0x80 + pal * 16 + p], 255)
    return img, min_x, min_y


def compose_oam_indices(vram: list[int],
                        sprites: list[OamSprite]) -> tuple[Image.Image, int, int]:
    """Compose OAM sprites into an index image (R = palette index)."""
    min_x = min(s.x for s in sprites)
    min_y = min(s.y for s in sprites)
    max_x = max(s.x + s.size for s in sprites)
    max_y = max(s.y + s.size for s in sprites)
    img = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    px = img.load()
    for s in sorted(sprites, key=lambda s: s.index, reverse=True):
        for row in range(s.size):
            for col in range(s.size):
                used_col = s.size - 1 - col if s.hflip else col
                used_row = s.size - 1 - row if s.vflip else row
                used_tile = (((s.tile >> 4) + (used_row >> 3)) << 4) | \
                            (((s.tile & 0x0F) + (used_col >> 3)) & 0x0F)
                p = tile_pixels(vram, used_tile * 16)[used_row & 7][used_col & 7]
                if p:
                    px[s.x - min_x + col, s.y - min_y + row] = (p, 0, 0, 255)
    return img, min_x, min_y


def sample_palette(index_img: Image.Image, origin_x: int, origin_y: int,
                   framebuffer: Image.Image | None,
                   fallback: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Recover the palette actually used on screen for each sprite index.

    CGRAM at dump time can differ from the CGRAM used while the frame was
    rendered (the game restores/overwrites palette slots). Sampling the
    framebuffer at the sprite's opaque pixels gives the visible colours.
    """
    if framebuffer is None:
        return fallback
    buckets: dict[int, list[tuple[int, int, int]]] = {}
    px = index_img.load()
    w, h = index_img.size
    for y in range(h):
        for x in range(w):
            idx, _g, _b, a = px[x, y]
            if not a:
                continue
            fx, fy = origin_x + x, origin_y + y
            if 0 <= fx < framebuffer.width and 0 <= fy < framebuffer.height:
                buckets.setdefault(idx, []).append(framebuffer.getpixel((fx, fy)))
    out = list(fallback)
    for idx, colors in buckets.items():
        if 1 <= idx <= 15:
            out[idx] = Counter(colors).most_common(1)[0][0]
    return out


def colorize(index_img: Image.Image,
             palette: list[tuple[int, int, int]]) -> Image.Image:
    img = Image.new("RGBA", index_img.size, (0, 0, 0, 0))
    src = index_img.load()
    dst = img.load()
    for y in range(index_img.height):
        for x in range(index_img.width):
            idx, _g, _b, a = src[x, y]
            if a:
                dst[x, y] = (*palette[idx], 255)
    return img


def crop_sprite(img: Image.Image, origin_x: int, origin_y: int):
    """Crop transparent padding; return absolute screen bbox."""
    bbox = img.getbbox()
    if bbox is None:
        raise SystemExit("sprite composition is empty")
    cropped = img.crop(bbox)
    return (cropped,
            origin_x + bbox[0], origin_y + bbox[1],
            bbox[2] - bbox[0], bbox[3] - bbox[1])


def compose_rom_metasprite(obj_vram: list[int], cgram,
                           parts: list[dict], base_tile: int,
                           palette: int) -> Image.Image | None:
    """Compose one ROM metasprite frame ($8B:8000) from decompressed OBJ VRAM."""
    if not parts:
        return None
    sprites = []
    for idx, p in enumerate(parts):
        t = p["tile"]
        old_b4 = t & 0x10
        tile = t + base_tile
        if (tile & 0x10) != old_b4:
            tile += 0x10
        sprites.append(OamSprite(
            idx, p["dx"], p["dy"], p["size"], tile & 0x1FF, palette,
            p["hflip"], p["vflip"]
        ))
    index_img, ox, oy = compose_oam_indices(obj_vram, sprites)
    colors = [cgram[0x80 + palette * 16 + i] for i in range(16)]
    img = colorize(index_img, colors)
    bbox = img.getbbox()
    if bbox is None:
        return None
    return img.crop(bbox)


# Area 1 BG2 HDMA parallax scanline table recovered from $84:AF65..B01C.
AREA1_HDMA_BANDS = [
    {"lines": 32, "factor": 0.25},
    {"lines": 44, "factor": 0.125},
    {"lines": 28, "factor": 0.25},
    {"lines": 46, "factor": 0.50},
    {"lines": 74, "factor": 1.25},
]

SPECIES_KIND_MAP = {
    0x57: "urn",
    0x67: "enemy",
    0x2C: "enemy",
    0x07: "enemy",
    0x26: "enemy",
    0x81: "enemy",
    0x10: "enemy",
    0x08: "enemy",
    0x01: "platform",
    0x49: "pickup_crest",
    0x24: "pickup_crest",
    0x2D: "pickup_crest",
    0x2E: "pickup_crest",
    0x33: "boss",
    0xA5: "boss",
    # $96 is the script/NPC actor, not a fight: shopkeepers and the library
    # old man (46..49/55), the avenue's townsperson (4), the arena controller
    # (52/53/54, same position as the boss). It stays "boss" in the room JSON
    # because the record has no type byte; Objects_Init re-routes it (NPC in a
    # room without a real boss, invisible controller in one with). Typing it
    # boss here made boss_alive true and skipped every transition in the room.
    0x96: "boss",
    0x09: "boss",   # Hippogriff: a real boss object (statue phase included)
    # $72 is the torch flame in the cemetery: a 16x16 five-frame flicker with no
    # collision or damage in its handler ($85:D4CF).  Drawn as decor, never
    # spawned into the object pool.
    0x72: "decor",
    # $9B exists eight times per boss room (areas 52/53/54) as a 2x4 grid of
    # pieces.  Its init sets no metasprite pointers and the oracle draws no OAM
    # for it, with flags 0 or 0x80: it is a script-owned controller, not a
    # visible object.  Typed inert so no placeholder box is invented for it.
    0x9B: "inert",
}


def room_stats(doc: dict) -> dict:
    """Classify a generated room: playable, partial or empty.

    Used for campaign.json metadata and by the audit tooling. A room is
    ``playable`` when it has collision, BG1 geometry and walkable ground under
    its spawn; ``empty`` when it has neither collision nor BG1 tiles (menus and
    padding grids); everything else is ``partial`` (boss arenas whose floor is
    not in the block tables, cutscene stages, ...).
    """
    attrs = doc["collision"]["attrs"]
    col_pct = (100.0 * sum(1 for a in attrs if a) / len(attrs)
               if attrs else 0.0)
    bg1 = doc["bg"][-1]["tilemap"]
    bg1_pct = 100.0 * sum(1 for w in bg1 if w) / len(bg1) if bg1 else 0.0
    sx, sy = doc["spawn"]["x"], doc["spawn"]["y"]
    cw = doc["collision"]["width"]
    ch = doc["collision"]["height"]
    ground = False
    for dy in range(0, 97, 4):
        cx = min(cw - 1, max(0, int(sx) // 16))
        cy = int((sy + dy) // 16)
        if cy >= ch:
            break
        if attrs[cy * cw + cx] & 0x1F:
            ground = True
            break
    if col_pct <= 0.0 and bg1_pct <= 0.0:
        kind = "empty"
    elif col_pct > 0.0 and bg1_pct >= 1.0 and ground:
        kind = "playable"
    else:
        kind = "partial"
    return {
        "kind": kind,
        "collision_pct": round(col_pct, 1),
        "bg1_pct": round(bg1_pct, 1),
        "bg2": bool(sum(1 for w in doc["bg"][0]["tilemap"] if w)),
        "spawn": [sx, sy],
        "ground": ground,
        "gate_next_area": doc.get("gate_next_area", -1),
        "transitions": len(doc.get("transitions", [])),
        "transitions_detail": [
            {"next_area": tr.get("next_area"), "spawn": tr.get("spawn")}
            for tr in doc.get("transitions", [])
        ],
    }


def build_area_room_doc(rom: Rom, area: int, bg2_layer: dict,
                        player_feet_x: int, player_feet_y: int,
                        bg2_captures: dict[int, dict] | None = None) -> dict:
    """Build a complete 2D multi-row room JSON for any ROM area."""
    info = rom.area_info(area)
    set_id = info["set"]
    grid = info["grid"]
    populated_rows = [r for r in range(info["height"])
                      if any(s > 0 for s in grid[r])]
    if not populated_rows:
        populated_rows = [0]
    first_row = populated_rows[0]
    row_offset = first_row * 256
    active_rows = grid[first_row:populated_rows[-1] + 1]
    grid_w = info["width"]
    grid_h = len(active_rows)

    map_w = grid_w * 32
    map_h = grid_h * 32
    full_tiles: list[int] = []
    col_w = grid_w * 16
    col_h = grid_h * 16
    attrs: list[int] = []

    for ry, row_slots in enumerate(active_rows):
        screen_maps = []
        screen_blks = []
        for s in row_slots:
            if s > 0 and s <= len(info["screens"]):
                scr = info["screens"][s - 1]
                screen_maps.append(rom.screen_tilemap(set_id, scr))
                screen_blks.append(rom.screen_blocks(set_id, scr))
            else:
                screen_maps.append([[0] * 32 for _ in range(32)])
                screen_blks.append([[0] * 16 for _ in range(16)])
        for ty in range(32):
            for tm in screen_maps:
                full_tiles.extend(tm[ty])
        for cby in range(16):
            for blks in screen_blks:
                for cbx in range(16):
                    attrs.append(rom.block_attr(set_id, blks[cby][cbx]))

    world_w = map_w * 8
    world_h = map_h * 8
    spawns_raw = rom.area_spawns(area)
    spawns = []
    for sp in spawns_raw:
        sx = sp["x"]
        sy = sp["y"] - row_offset
        if sy < 16 or sy >= world_h:
            sy = max(32, min(world_h - 32, sp["y"] % max(256, world_h)))
        spawns.append({"x": sx, "y": sy, "flags": sp["flags"]})
    spawn0 = spawns[0] if spawns else {"x": 64, "y": min(164, world_h - 32)}

    transitions = []
    for tr in rom.area_transitions(area):
        ty = tr["y"] - row_offset
        if ty < 0:
            ty = tr["y"]
        transitions.append({
            "next_area": tr["next_area"],
            "spawn_id": tr["spawn_id"],
            "pad_mask": tr["pad_mask"],
            "x": tr["x"],
            "y": ty,
            "half_w": max(12, tr["half_w"]),
            "half_h": max(16, tr["half_h"]),
            "type": tr["type"],
        })

    objects = []
    for rec in rom.object_list(area):
        # Every record lands in the room, whether or not the port has a handler
        # for its species: a species with no entry here becomes "unknown" and is
        # drawn as a placeholder.  Dropping it here is how two thirds of the
        # retail object placement used to disappear silently.
        kind = SPECIES_KIND_MAP.get(rec["species"], "unknown")
        objects.append({
            "type": kind,
            "species": rec["species"],
            "flags": rec["flags"],
            "x": rec["x"],
            "y": rec["y"] - row_offset,
            "source": "rom",
        })

    cam_x = max(0, min(max(0, world_w - 256), spawn0["x"] - 128))
    # The vertical deadzone matches the runtime camera: it only follows when the
    # player leaves the 96..176 window. The old -140 guess started the room at
    # cam_y = 32, which lifted every object 32 px above the background.
    cam_y = max(0, min(max(0, world_h - 224), spawn0["y"] - 176))
    # Rooms whose ROM tilemap sits a couple of rows above the game's own layout
    # (the 256-tall world is shown through a 224-tall view, so the missing band
    # has to be filled): pad the top with a wall row and shift the layer.
    bg_pad_rows = {0: 3}.get(area, 0)
    # Area 1's BG1 tilemap is authored 53 px above the world origin: every
    # statue in the original map sits 53 px lower (measured against
    # docs/FullMaps/images/demons-crest-murkland-cemetery-snes-map.webp).
    # Keep scroll_y untouched (area 4 uses it as a camera offset) and expose
    # the correction as offset_y, which the renderers apply for world BG1.
    bg_scroll_y = {0: -2}.get(area, 0)
    bg_offset_y = {1: 53}.get(area, 0)
    if bg_pad_rows and map_w:
        filler = full_tiles[4 * map_w:5 * map_w]
        full_tiles = [x for _ in range(bg_pad_rows) for x in filler] + full_tiles
        map_h += bg_pad_rows
    bg1 = {
        "name": "bg1",
        "map_width": map_w,
        "map_height": map_h,
        "scroll_x": cam_x,
        # The port places a layer at its world origin and scrolls it with the
        # camera, so a tilemap that starts at world 0 must say 0 here. Writing
        # cam_y duplicated the camera offset and lifted the floor by ~31 px,
        # which cut the boss off at the bottom of the screen.
        "scroll_y": bg_scroll_y,
        "offset_y": bg_offset_y,
        "tilemap": full_tiles,
    }
    bg2_copy = dict(bg2_layer)
    capture = (bg2_captures or {}).get(area)
    if capture is not None:
        # The oracle frame was taken at its own BG1 scroll; keep the layer's
        # *relative* offset so the backdrop sits where the original game put it
        # for this room's camera.
        regs = capture["regs"]
        map_w, map_h, tiles = tilemap_linear(capture["vram"], regs["bgsc"][1])
        bg2_copy = {
            "name": "bg2",
            "map_width": map_w,
            "map_height": map_h,
            "scroll_x": cam_x + (regs["hscroll"][1] - regs["hscroll"][0]),
            "scroll_y": (regs["vscroll"][1] - regs["vscroll"][0]),
            "tilemap": tiles,
        }
    elif area != 1:
        # BG2 backdrops are generated at runtime and are not in the ROM block
        # tables; keep the layer transparent until a capture exists.
        bg2_copy["tilemap"] = [0] * len(bg2_layer["tilemap"])
        bg2_copy["scroll_x"] = 0
        bg2_copy["scroll_y"] = 0
        bg2_copy.pop("hdma_bands", None)
    bg2_copy.pop("hdma_bands", None)
    if area == 1:
        bg2_copy["hdma_bands"] = AREA1_HDMA_BANDS
    return {
        "name": f"area{area}_full_room",
        "area_id": area,
        "gate_next_area": rom.gate_next_area(area),
        "backdrop": bg_backdrop_rgb(rom),
        "world": {"width": world_w, "height": world_h},
        "camera": {
            "x": cam_x,
            "y": cam_y,
            "min_x": 0,
            "max_x": max(0, world_w - 256),
            "min_y": 0,
            "max_y": max(0, world_h - 224),
        },
        "play": {
            "min_x": 8,
            "max_x": world_w - 8,
            "min_y": 22,
            "max_y": world_h,
        },
        "bg": [bg2_copy, bg1],
        "collision": {
            "cell": 16,
            "width": col_w,
            "height": col_h,
            "attrs": attrs,
        },
        "spawn": {"x": spawn0["x"], "y": spawn0["y"]},
        "spawns": spawns,
        "transitions": transitions,
        "objects": objects,
        "player": {
            "texture": "player_idle.png",
            "feet_x": player_feet_x,
            "feet_y": player_feet_y,
        },
        "sprites": [],
    }


def area_bg_cgram(rom: Rom, area: int) -> list[tuple[int, int, int]]:
    """ROM BG palette block for `area`: palettes 0/1 fixed, 2..7 per area."""
    colors = [(0, 0, 0)] * 128
    for pal in (0, 1):
        off = lo(0x99, 0x9080 + pal * 32)
        words = struct.unpack_from("<16H", rom.data, off)
        colors[pal * 16:(pal + 1) * 16] = [
            ((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
            for c in words]
    val = rom.u16(0x81, 0x8909 + area * 2)
    base = 0xA900 + (val & 0xFFC0)
    for pal in range(2, 8):
        off = lo(0x99, base + (pal - 2) * 32)
        words = struct.unpack_from("<16H", rom.data, off)
        colors[pal * 16:(pal + 1) * 16] = [
            ((c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8)
            for c in words]
    return colors


def area_used_palettes(rom: Rom, area: int) -> set[int]:
    """BG palettes referenced by the area's ROM block tables."""
    info = rom.area_info(area)
    used = {0}
    for row in info["grid"]:
        for slot in row:
            if not slot:
                continue
            scr = info["screens"][slot - 1]
            for tm in rom.screen_tilemap(info["set"], scr):
                for word in tm:
                    used.add((word >> 10) & 7)
    return used


def write_area_bg_atlases(rom: Rom, out: Path, areas: list[int],
                          bg2_captures: dict[int, dict] | None = None) -> None:
    """Bake per-area BG tile atlases.

    Two sets are produced:

    * `bg_area<area>_pal<p>.png` from the ROM-decompressed BG CHR at base 0 —
      used for BG1 (the level geometry), exactly as before.
    * `bg2_area<area>_pal<p>.png` from the captured frame's VRAM at the BG2 CHR
      base from `$210B` (high nibble) — used only for the BG2 backdrop, whose
      streamed CHR lives at a different address than the ROM set.

    Areas without a capture have no BG2 atlas (the layer stays transparent).
    """
    captures = bg2_captures or {}
    for area in areas:
        used = area_used_palettes(rom, area)
        rom_vram = rom.decompress_area_bg_vram(area)
        rom_cgram = area_bg_cgram(rom, area)
        capture = captures.get(area)
        if capture is not None:
            cap_vram = capture["vram"]
            cap_cgram = capture["cgram"]
            _w, _h, bg2_tiles = tilemap_linear(cap_vram,
                                               capture["regs"]["bgsc"][1])
            cap_pals = {(word >> 10) & 7 for word in bg2_tiles}
            tile_adr = int(str(capture["regs"].get("bgTileAdr", "0x0500")), 16)
            base_word = ((tile_adr >> 4) & 0x0F) << 11
            for pal in sorted(cap_pals):
                make_bg_atlas(cap_vram, cap_cgram, pal, base_word).save(
                    out / f"bg2_area{area}_pal{pal}.png")
        for pal in sorted(used):
            make_bg_atlas(rom_vram, rom_cgram, pal).save(
                out / f"bg_area{area}_pal{pal}.png")


def bg_backdrop_rgb(rom: Rom) -> list[int]:
    """BG palette 0 colour 0 ($99:9080), the SNES backdrop colour."""
    off = lo(0x99, 0x9080)
    c = rom.data[off] | (rom.data[off + 1] << 8)
    return [(c & 31) * 8, ((c >> 5) & 31) * 8, ((c >> 10) & 31) * 8]


def valid_campaign_areas(rom: Rom) -> list[int]:
    """Area indices with a sane 2D grid in $81:A291 / $81:A6D8."""
    out = []
    for area in range(113):
        p = rom.u16(0x81, 0xA291 + area * 2)
        q = rom.u16(0x81, 0xA6D8 + area * 2)
        set_id = rom.u8(0x81, p)
        w, h = rom.u8(0x81, q), rom.u8(0x81, q + 1)
        if set_id > 2 or w == 0 or h == 0 or w > 10 or h > 10:
            continue
        pop = any(rom.u8(0x81, q + 2 + y * w + x)
                  for y in range(h) for x in range(w))
        if pop:
            out.append(area)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", required=True, type=Path)
    ap.add_argument("--dump", required=True, type=Path)
    ap.add_argument("--prefix", default="stage_600")
    ap.add_argument("--area", type=int, default=1,
                    help="ROM area index at $81:A291 (default 1 for graveyard stage_600)")
    ap.add_argument("--screens", help="screen slots, e.g. 9,10 (default: bottom row first two)")
    ap.add_argument("--full-grid", action="store_true",
                    help="with --full-room: compose every used row of the area's "
                         "screen grid, not just the reference row")
    ap.add_argument("--full-room", action="store_true",
                    help="build every screen in the captured screen row from the "
                         "ROM block tables (2048 px wide for Area 1)")
    ap.add_argument("--object-list-index", type=int, default=None,
                    help="row index into the $81:C874 object-list pointer table "
                         "(default: the ROM area index; Area 1 = 1)")
    ap.add_argument("--player-oam", default="1-11",
                    help="OAM slots composing the player (default 1-11)")
    ap.add_argument("--player-palette", type=int, default=2,
                    help="CGRAM OBJ palette used by the player at render time "
                         "(default 2 for this graveyard capture)")
    ap.add_argument("--item-oam", default="0",
                    help="OAM slot for the visible item (default 0; 'none' to skip)")
    ap.add_argument("--item-palette", type=int, default=0,
                    help="CGRAM OBJ palette for the item (default 0; -1 = use OAM bits)")
    ap.add_argument("--fb", type=Path,
                    help="framebuffer BMP for palette matching (default: <dump>/<prefix>.fb.bmp)")
    ap.add_argument("--bg2-map", type=Path,
                    default=Path(__file__).with_name("bg2_captures.json"),
                    help="area -> capture-frame manifest for per-area BG2 "
                         "backdrops (default: tools/dc_extract/bg2_captures.json)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    rom = Rom(args.rom)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    bg2_captures = load_bg2_captures(args.bg2_map)
    if bg2_captures:
        print(f"bg2 captures: {sorted(bg2_captures)} from {args.bg2_map}")

    vram = read_vram(args.dump / f"{args.prefix}.vram.bin")
    cgram = read_cgram(args.dump / f"{args.prefix}.cgram.bin")
    oam = (args.dump / f"{args.prefix}.oam.bin").read_bytes()
    regs = json.loads((args.dump / f"{args.prefix}.regs.json").read_text())
    fb_path = args.fb or (args.dump / f"{args.prefix}.fb.bmp")
    framebuffer = Image.open(fb_path).convert("RGB") if fb_path.exists() else None

    mode = regs["bgmode"] & 7
    if mode not in (0, 1, 2, 3):
        raise SystemExit(f"unsupported BG mode {mode} (this extractor handles 4bpp modes)")
    if regs.get("inidisp", 0) & 0x80:
        raise SystemExit("capture is in forced blank; choose a visible gameplay frame")

    info = rom.area_info(args.area)
    set_id = info["set"]
    if args.screens:
        slots = [int(s) for s in args.screens.split(",")]
    else:
        slots = info["grid"][info["height"] - 1][:2]
    if len(slots) != 2:
        raise SystemExit("this extractor expects exactly two reference screens")

    # --- tilemaps -------------------------------------------------------
    # BG2 always comes from the captured VRAM ring buffer: it is a looping
    # backdrop rather than part of the block-table room. BG1 uses the ROM
    # block tables for the full screen row when --full-room is requested.
    bg2_sc = regs["bgsc"][1]
    bg2_w, bg2_h, bg2_tiles = tilemap_linear(vram, bg2_sc)
    bg_layers = [{
        "name": "bg2",
        "map_width": bg2_w,
        "map_height": bg2_h,
        "scroll_x": regs["hscroll"][1],
        "scroll_y": regs["vscroll"][1],
        "hdma_bands": AREA1_HDMA_BANDS,
        "tilemap": bg2_tiles,
    }]

    room_screens = None
    row_index = 0
    grid_rows_used = None
    if args.full_room and args.full_grid:
        grid = info["grid"]
        gw, gh = info["width"], info["height"]
        used = [y for y in range(gh)
                if any(1 <= grid[y][x] <= len(info["screens"])
                       for x in range(gw))]
        if not used:
            raise SystemExit(f"area {args.area} has no populated grid rows")
        grid_rows_used = used
        map_w = gw * 32
        map_h = len(used) * 32
        screen_maps = {}
        row_tiles = []
        for y in used:
            tiles_row = []
            for x in range(gw):
                slot = grid[y][x]
                screen = (info["screens"][slot - 1]
                          if 1 <= slot <= len(info["screens"]) else None)
                if screen is None:
                    tiles_row.append([[0] * 32 for _ in range(32)])
                    continue
                if screen not in screen_maps:
                    screen_maps[screen] = rom.screen_tilemap(set_id, screen)
                tiles_row.append(screen_maps[screen])
            row_tiles.append(tiles_row)
        full_tiles = []
        for tiles_row in row_tiles:
            for ty in range(32):
                for tiles in tiles_row:
                    full_tiles.extend(tiles[ty])
        room_screens = [info["screens"][grid[y][x] - 1]
                        for y in used for x in range(gw)
                        if 1 <= grid[y][x] <= len(info["screens"])]
        bg1 = {
            "name": "bg1",
            "map_width": map_w,
            "map_height": map_h,
            "scroll_x": regs["hscroll"][0],
            "scroll_y": regs["vscroll"][0],
            "tilemap": full_tiles,
        }
        row_index = 0
    elif args.full_room:
        # Use every screen in the same grid row as the captured reference
        # slots. Area 1's other grid row is empty padding (all-zero BG1 and
        # collision), so the populated row is the actual room.
        found_row = next((i for i, row in enumerate(info["grid"])
                          if slots[0] in row), None)
        if found_row is None:
            raise SystemExit(f"screen slot {slots[0]} is not in the area grid")
        row_index = found_row
        room_screens = [info["screens"][s - 1]
                        for s in info["grid"][row_index]]
        map_w = len(room_screens) * 32
        map_h = 32
        screen_maps = [rom.screen_tilemap(set_id, screen)
                       for screen in room_screens]
        full_tiles = []
        for ty in range(32):
            for tm in screen_maps:
                full_tiles.extend(tm[ty])
        bg1 = {
            "name": "bg1",
            "map_width": map_w,
            "map_height": map_h,
            "scroll_x": regs["hscroll"][0],
            "scroll_y": regs["vscroll"][0],
            # Area 1's tilemap is authored 53 px above the world origin.
            "offset_y": 53 if args.area == 1 else 0,
            "tilemap": full_tiles,
        }
    else:
        bg1_sc = regs["bgsc"][0]
        bg1_w, bg1_h, bg1_tiles = tilemap_linear(vram, bg1_sc)
        bg1 = {
            "name": "bg1",
            "map_width": bg1_w,
            "map_height": bg1_h,
            "scroll_x": regs["hscroll"][0],
            "scroll_y": regs["vscroll"][0],
            "offset_y": 53 if args.area == 1 else 0,
            "tilemap": bg1_tiles,
        }
    bg_layers.append(bg1)

    # --- palettes & ROM-decompressed OBJ sprites ------------------------
    campaign_areas = valid_campaign_areas(rom)
    for p in range(8):
        make_bg_atlas(vram, cgram, p).save(out / f"bg_pal{p}.png")
    write_area_bg_atlases(rom, out, campaign_areas, bg2_captures)

    rom_obj_vram, slot_tiles = rom.decompress_area_obj_vram(args.area)
    item_cgram = list(cgram)
    item_pal_words = struct.unpack_from("<16H", rom.data, lo(0x99, 0x9240))
    for i, c in enumerate(item_pal_words):
        item_cgram[0x80 + i] = ((c & 31) * 8, ((c >> 5) & 31) * 8,
                                ((c >> 10) & 31) * 8)

    heart_group = rom.parse_metasprite_group(0x6B)
    heart_base_tile = slot_tiles.get(0x06, 0x60)
    heart0 = compose_rom_metasprite(rom_obj_vram, item_cgram, heart_group[3],
                                    heart_base_tile, 0)
    heart1 = compose_rom_metasprite(rom_obj_vram, item_cgram, heart_group[2],
                                    heart_base_tile, 0)
    (heart0 or make_heart_sprite(1)).save(out / "heart_00.png")
    (heart1 or make_heart_sprite(1, pulse=True)).save(out / "heart_01.png")

    ghoul_group = rom.parse_metasprite_group(0x03)
    ghoul_base_tile = slot_tiles.get(0x14, 0xC2)
    enemy0 = compose_rom_metasprite(rom_obj_vram, cgram, ghoul_group[0],
                                    ghoul_base_tile, 1)
    enemy1 = compose_rom_metasprite(rom_obj_vram, cgram, ghoul_group[1],
                                    ghoul_base_tile, 1)
    (enemy0 or make_enemy_sprite(0)).save(out / "enemy_00.png")
    (enemy1 or make_enemy_sprite(1)).save(out / "enemy_01.png")

    # OBJ base for the current OBSEL.
    obj_base = (regs["obsel"] & 7) << 13
    for p in range(8):
        make_obj_atlas(vram, cgram, obj_base, p).save(out / f"obj_pal{p}.png")

    # --- OAM sprites ----------------------------------------------------
    oam_sprites = parse_oam(oam, regs["obsel"])
    player_slots = set()
    if args.player_oam.lower() != "none":
        for part in args.player_oam.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                player_slots |= set(range(int(a), int(b) + 1))
            else:
                player_slots.add(int(part))
    player_sprites = [s for s in oam_sprites if s.index in player_slots]
    # The OBJ tile base is already in the VRAM word addresses; compose_oam
    # expects a vram array where OBJ tile 0 starts at word 0.
    obj_vram = vram[obj_base:obj_base + 0x2000]
    player_index, player_ox, player_oy = compose_oam_indices(
        obj_vram, player_sprites)
    if args.player_palette >= 0:
        player_colors = [cgram[0x80 + args.player_palette * 16 + i]
                         for i in range(16)]
    else:
        player_fallback = [cgram[0x80 + 7 * 16 + i] for i in range(16)]
        player_colors = sample_palette(player_index, player_ox, player_oy,
                                       framebuffer, player_fallback)
    player_img = colorize(player_index, player_colors)
    player_img, bx, by, bw, bh = crop_sprite(player_img, player_ox, player_oy)
    player_img.save(out / "player_idle.png")
    player_feet_x = bw // 2
    player_feet_y = bh

    sprites = []
    if args.item_oam.lower() != "none":
        item_slots = set()
        for part in args.item_oam.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                item_slots |= set(range(int(a), int(b) + 1))
            else:
                item_slots.add(int(part))
        item_sprites = [s for s in oam_sprites if s.index in item_slots]
        if item_sprites:
            item_index, item_ox, item_oy = compose_oam_indices(
                obj_vram, item_sprites)
            if args.item_palette >= 0:
                item_colors = [cgram[0x80 + args.item_palette * 16 + i]
                               for i in range(16)]
            else:
                item_fallback = [cgram[0x80 + item_sprites[0].palette * 16 + i]
                                 for i in range(16)]
                item_colors = sample_palette(item_index, item_ox, item_oy,
                                             framebuffer, item_fallback)
            item_img = colorize(item_index, item_colors)
            item_img, ibx, iby, ibw, ibh = crop_sprite(
                item_img, item_ox, item_oy)
            item_img.save(out / "item_00.png")
            sprites.append({
                "texture": "item_00.png",
                "x": regs["hscroll"][0] + ibx,
                "y": regs["vscroll"][0] + iby,
            })

    # --- collision ------------------------------------------------------
    attrs = []
    if args.full_room and args.full_grid:
        grid = info["grid"]
        gw = info["width"]
        col_w = gw * 16
        col_h = len(grid_rows_used) * 16
        block_cache = {}
        for y in grid_rows_used:
            for cby in range(16):
                for x in range(gw):
                    slot = grid[y][x]
                    screen = (info["screens"][slot - 1]
                              if 1 <= slot <= len(info["screens"]) else None)
                    if screen is None:
                        attrs.extend([0] * 16)
                        continue
                    if screen not in block_cache:
                        block_cache[screen] = rom.screen_blocks(set_id, screen)
                    g = block_cache[screen]
                    for cbx in range(16):
                        attrs.append(rom.block_attr(set_id, g[cby][cbx]))
    elif args.full_room:
        col_w = len(room_screens) * 16
        col_h = 16
        for cby in range(col_h):
            for gx, screen in enumerate(room_screens):
                g = rom.screen_blocks(set_id, screen)
                for cbx in range(16):
                    b = g[cby][cbx]
                    attrs.append(rom.block_attr(set_id, b))
    else:
        col_w, col_h = 32, 16
        for cby in range(col_h):
            for cbx in range(col_w):
                slot = slots[cbx // 16]
                block = info["screens"][slot - 1] if slot else None
                if block is None:
                    attrs.append(0)
                    continue
                g = rom.screen_blocks(set_id, block)
                b = g[cby][cbx % 16]
                attrs.append(rom.block_attr(set_id, b))

    # --- data-driven objects -------------------------------------------
    world_w = bg1["map_width"] * 8
    world_h = bg1["map_height"] * 8
    objects = []
    object_list_index = args.object_list_index
    if object_list_index is None and args.full_room:
        object_list_index = args.area
    if object_list_index is not None:
        row_offset = (0 if args.full_grid
                      else (row_index * 256) if args.full_room else 0)
        type_by_species = SPECIES_KIND_MAP
        for rec in rom.object_list(object_list_index):
            # Same rule as build_area_room_doc: place every record, type the
            # unknown species as "unknown" for the runtime placeholder.
            x = rec["x"]
            y = rec["y"] - row_offset
            kind = type_by_species.get(rec["species"], "unknown")
            objects.append({
                "type": kind,
                "species": rec["species"],
                "flags": rec["flags"],
                "x": x,
                "y": y,
                "source": "rom",
            })
        if any(obj["type"] == "urn" for obj in objects):
            # The visible OAM item is the same urn; the object pool owns it now.
            sprites = []

    # --- room document --------------------------------------------------
    spawn_x = regs["hscroll"][0] + bx + bw // 2
    spawn_y = regs["vscroll"][0] + by + bh
    if args.full_room:
        camera = {
            "x": regs["hscroll"][0], "y": regs["vscroll"][0],
            "min_x": 0, "max_x": max(0, world_w - 256),
            "min_y": 0, "max_y": max(0, world_h - 224),
        }
        play = {
            "min_x": 8,
            "max_x": world_w - 8,
            "min_y": 22,
            "max_y": world_h,
        }
    else:
        camera = {
            "x": regs["hscroll"][0], "y": regs["vscroll"][0],
            "min_x": regs["hscroll"][0], "max_x": regs["hscroll"][0],
            "min_y": regs["vscroll"][0], "max_y": regs["vscroll"][0],
        }
        play = {
            "min_x": regs["hscroll"][0] + 15,
            "max_x": regs["hscroll"][0] + 241,
            "min_y": 22,
            "max_y": world_h,
        }
    row_offset = (row_index * 256) if args.full_room else 0
    spawns = []
    for sp in rom.area_spawns(args.area):
        spawns.append({
            "x": sp["x"],
            "y": max(22, sp["y"] - row_offset),
            "flags": sp["flags"],
        })
    transitions = []
    for tr in rom.area_transitions(args.area):
        transitions.append({
            "next_area": tr["next_area"],
            "spawn_id": tr["spawn_id"],
            "pad_mask": tr["pad_mask"],
            "x": tr["x"],
            "y": max(0, tr["y"] - row_offset),
            "half_w": max(12, tr["half_w"]),
            "half_h": max(16, tr["half_h"]),
            "type": tr["type"],
        })
    room = {
        "name": f"area{args.area}_{'full_room' if args.full_room else 'room'}",
        "area_id": args.area,
        "gate_next_area": rom.gate_next_area(args.area),
        "backdrop": bg_backdrop_rgb(rom),
        "world": {"width": world_w, "height": world_h},
        "camera": camera,
        "play": play,
        "bg": bg_layers,
        "collision": {"cell": 16, "width": col_w, "height": col_h,
                      "attrs": attrs},
        "spawn": {"x": spawn_x, "y": spawn_y},
        "spawns": spawns,
        "transitions": transitions,
        "objects": objects,
        "player": {
            "texture": "player_idle.png",
            "feet_x": player_feet_x,
            "feet_y": player_feet_y,
        },
        "sprites": sprites,
    }
    (out / "room.json").write_text(json.dumps(room, indent=1))
    (out / f"room_area{args.area}.json").write_text(json.dumps(room, indent=1))

    # Emit multi-area campaign rooms and campaign.json
    room_meta = {}
    for area_id in campaign_areas:
        if area_id == args.area and args.full_room:
            continue
        doc = build_area_room_doc(rom, area_id, bg_layers[0],
                                  player_feet_x, player_feet_y,
                                  bg2_captures)
        (out / f"room_area{area_id}.json").write_text(json.dumps(doc, indent=1))
        room_meta[str(area_id)] = room_stats(doc)

    if str(args.area) not in room_meta:
        room_meta[str(args.area)] = room_stats(room)

    kinds = {"playable": 0, "partial": 0, "empty": 0}
    for meta in room_meta.values():
        kinds[meta["kind"]] += 1

    # Stage entries: rooms no other room targets through a transition or a boss
    # gate. These are what the overworld stage select can travel to; every room
    # is reachable from this set (see tools/campaign_graph.py).
    incoming = set()
    for meta in room_meta.values():
        for target in (meta.get("gate_next_area"),):
            if isinstance(target, int) and target >= 0:
                incoming.add(target)
        for tr in meta.get("transitions_detail", []):
            target = tr.get("next_area")
            if isinstance(target, int):
                incoming.add(target)
    entries = sorted(int(a) for a in room_meta if int(a) not in incoming)

    campaign_doc = {
        "rom_sha256": rom.sha256,
        "areas": campaign_areas,
        "stage_entries": entries,
        "rooms": room_meta,
        "room_kinds": kinds,
        "gargoyle_palettes": rom.gargoyle_palettes(),
        "hdma_area1": AREA1_HDMA_BANDS,
    }
    (out / "campaign.json").write_text(json.dumps(campaign_doc, indent=1))

    manifest = {
        "rom_sha256": rom.sha256,
        "area": args.area,
        "screens": room_screens or slots,
        "full_room": bool(args.full_room),
        "campaign_areas": campaign_areas,
        "object_list_index": object_list_index,
        "objects": len(objects),
        "bg2_captures": sorted(bg2_captures),
        "source": f"{args.prefix} ({args.dump})",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "dc_extract 0.4",
        "tile_size": 8,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    print(f"room: {out / 'room.json'}")
    print(f"player: {player_img.width}x{player_img.height}, "
          f"feet=({player_feet_x},{player_feet_y}), spawn=({spawn_x},{spawn_y}), "
          f"palette={args.player_palette}")
    print(f"collision: {len(attrs)} cells ({col_w}x{col_h}), "
          f"screens {room_screens or slots}, tileset set {set_id}")
    print(f"objects: {len(objects)} from list index {object_list_index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
