#!/usr/bin/env python3
"""Compose sprites exactly from a probe's OAM/VRAM/CGRAM dump.

Pipeline A of docs/PLAN_SPRITES_ANIMATION.md. A probe directory holds
`vram.bin`, `cgram.bin`, `oam.bin` and `ppu.json`; this decodes every OAM entry
(including 16x16 quadrant order, flips and palette bits) with the game's own
CGRAM, and writes:

  <out>/oam_layer.png     every sprite, in screen space
  <out>/sprites.json      each sprite: screen rect, palette, tile, size
  <out>/boss.png          the largest cluster, cropped, with a transparent key

Then the port can use `boss.png` with the anchor taken from the cluster bounds
instead of guessing from a screenshot.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import deque
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import parse_oam, compose_oam, cgram_colors  # noqa: E402

W, H = 256, 224
# Probe dumps have been little-endian so far; the flag exists because the
# recomposition gate has not passed yet and this is the first suspect.
BIG_ENDIAN_DUMP = False


def load_probe(folder: Path):
    vram = (folder / "vram.bin").read_bytes()
    cgram = (folder / "cgram.bin").read_bytes()
    oam = (folder / "oam.bin").read_bytes()
    ppu = json.loads((folder / "ppu.json").read_text())
    info_path = folder / "info.json"
    info = json.loads(info_path.read_text()) if info_path.is_file() else {}
    return vram, cgram, oam, ppu, info


OBJ_BASE, OBJ_STRIDE, OBJ_SLOTS = 0x1080, 0x50, 26


def read_pool(wram: bytes):
    """[{slot, species, x, y}] from the object pool ($1080, stride $50)."""
    out = []
    for slot in range(OBJ_SLOTS):
        rec = wram[OBJ_BASE + slot * OBJ_STRIDE:
                   OBJ_BASE + (slot + 1) * OBJ_STRIDE]
        if len(rec) < 0x36 or rec[0] == 0 or rec[2] == 0:
            continue

        def fx24(off):
            return (rec[off] | (rec[off + 1] << 8) | (rec[off + 2] << 16)) / 256.0

        out.append({"slot": slot, "species": rec[2], "x": fx24(0x30),
                    "y": fx24(0x33)})
    return out


def player_offset(sprites, wram: bytes):
    """World->screen offset from the palette-7 player group and $1030/$1033."""
    if len(wram) < 0x1036:
        return None

    def u24(addr):
        return (wram[addr] | (wram[addr + 1] << 8) |
                (wram[addr + 2] << 16)) / 256.0

    pal7 = [s for s in sprites if s.palette == 7 and s.y < 224]
    if not pal7:
        return None
    groups: list[list] = []
    for sprite in pal7:
        for group in groups:
            if any(abs(sprite.x - other.x) < 40 and
                   abs(sprite.y - other.y) < 64 for other in group):
                group.append(sprite)
                break
        else:
            groups.append([sprite])
    best = max(groups, key=len)
    min_x = min(s.x for s in best)
    max_x = max(s.x + s.size for s in best)
    max_y = max(s.y + s.size for s in best)
    anchor = ((min_x + max_x) / 2.0, float(max_y))
    return (u24(0x1030) - anchor[0], u24(0x1033) - anchor[1])


def largest_alpha_crop(img: Image.Image) -> tuple[Image.Image, int, int] | None:
    """Keep the largest connected opaque component (drop ground/HUD scraps)."""
    w, h = img.size
    px = img.load()
    seen = bytearray(w * h)
    best = None
    best_len = 0
    for y in range(h):
        for x in range(w):
            if seen[y * w + x] or px[x, y][3] == 0:
                continue
            q = deque([(x, y)])
            seen[y * w + x] = 1
            pts = []
            while q:
                cx, cy = q.popleft()
                pts.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        if not seen[j] and px[nx, ny][3]:
                            seen[j] = 1
                            q.append((nx, ny))
            if len(pts) > best_len:
                best_len = len(pts)
                best = pts
    if not best:
        return None
    keep = set(best)
    xs = [x for x, _ in best]
    ys = [y for _, y in best]
    x0, y0 = max(0, min(xs) - 1), max(0, min(ys) - 1)
    x1, y1 = min(w, max(xs) + 2), min(h, max(ys) + 2)
    out = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    for x, y in keep:
        out.putpixel((x - x0, y - y0), px[x, y])
    return out, x0, y0


def cgram_colours(cgram: bytes):
    cols = []
    for i in range(256):
        lo, hi = cgram[i * 2], cgram[i * 2 + 1]
        v = lo | (hi << 8)
        r = (v & 0x1F) * 255 // 31
        g = ((v >> 5) & 0x1F) * 255 // 31
        b = ((v >> 10) & 0x1F) * 255 // 31
        cols.append((r, g, b))
    return cols


SIZE_PAIRS = {
    0: (8, 16), 1: (8, 32), 2: (8, 64),
    3: (16, 32), 4: (16, 64), 5: (32, 64),
    6: (16, 32), 7: (32, 64),
}


def sprite_base_words(obsel: int) -> int:
    """OBSEL bits 0..2: sprite pattern base, in 16-bit words (as the verified
    decoder in extract.py uses: (obsel & 7) << 13)."""
    return (obsel & 0x07) << 13


def tile_pixels(vram: bytes, tile: int, palette: int, colours, flip_h, flip_v,
                base_words: int = 0):
    """8x8 4bpp tile -> 64 RGBA tuples.

    SNES 4bpp: words base+0..7 hold planes 0 (low byte) and 1 (high byte) for
    rows 0..7; words base+8..15 hold planes 2 and 3 the same way.
    """
    base = base_words + (tile & 0x1FF) * 16   # word address
    out = [None] * 64
    for y in range(8):
        if BIG_ENDIAN_DUMP:
            w0 = (vram[(base + y) * 2] << 8) | vram[(base + y) * 2 + 1]
            w1 = (vram[(base + 8 + y) * 2] << 8) | vram[(base + 8 + y) * 2 + 1]
        else:
            w0 = vram[(base + y) * 2] | (vram[(base + y) * 2 + 1] << 8)
            w1 = (vram[(base + 8 + y) * 2] |
                  (vram[(base + 8 + y) * 2 + 1] << 8))
        for x in range(8):
            bit = 7 - x
            p0 = (w0 >> bit) & 1
            p1 = (w0 >> (8 + bit)) & 1
            p2 = (w1 >> bit) & 1
            p3 = (w1 >> (8 + bit)) & 1
            idx = p0 | (p1 << 1) | (p2 << 2) | (p3 << 3)
            srcy = 7 - y if flip_v else y
            srcx = 7 - x if flip_h else x
            if idx:
                r, g, b = colours[(0x80 + palette * 16 + idx) & 0xFF]
                out[srcy * 8 + srcx] = (r, g, b, 255)
            else:
                out[srcy * 8 + srcx] = (0, 0, 0, 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("probe", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--big-endian-words", action="store_true")
    ap.add_argument("--object", type=lambda v: int(v, 0), default=None,
                    help="species to cut out by its pool position (e.g. 0x33)")
    args = ap.parse_args()

    global BIG_ENDIAN_DUMP
    BIG_ENDIAN_DUMP = args.big_endian_words
    vram_raw, cgram_raw, oam, ppu, info = load_probe(args.probe)
    vram = list(struct.unpack(
        (">" if BIG_ENDIAN_DUMP else "<") + "32768H", vram_raw))
    colours = cgram_colors(cgram_raw)
    body = ppu.get("ppu", ppu)
    obsel = int(str(body.get("obsel", "0x00")), 16)
    base_words = sprite_base_words(obsel)
    small, large = SIZE_PAIRS.get((obsel >> 5) & 7, (8, 16))
    print(f"obsel {obsel:02x}: tile base word {base_words}, "
          f"sizes {small}/{large}")
    args.out.mkdir(parents=True, exist_ok=True)

    obj_base = (obsel & 7) << 13
    obj_vram = vram[obj_base:obj_base + 0x2000]
    all_sprites = parse_oam(oam, obsel)
    sprites = [s for s in all_sprites
               if s.y < 224 and not (s.x == 0 and s.y == 0 and s.tile == 0)]

    # Use extract.py's verified metaspriter: it flips the whole sprite (not
    # each 8x8 tile independently) and honours OAM quadrant order.
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if sprites:
        composed, min_x, min_y = compose_oam(obj_vram, colours, sprites)
        canvas.paste(composed, (min_x, min_y), composed)
    canvas.save(args.out / "oam_layer.png")

    sprite_rows = []
    for s in sprites:
        sprite_rows.append({
            "index": s.index, "x": s.x, "y": s.y, "tile": s.tile,
            "palette": s.palette, "size16": bool(s.size >= 16),
            "flip_h": s.hflip, "flip_v": s.vflip,
            "width": s.size, "height": s.size})

    if args.object is not None:
        wram_path = args.probe / "wram.bin"
        if wram_path.is_file():
            wram = wram_path.read_bytes()
            pool = read_pool(wram)
            target = [o for o in pool if o["species"] == args.object]
            if target:
                obj = target[0]
                hs = body.get("hScroll", [0])[0]
                vs = body.get("vScroll", [0])[0]
                # The PPU scroll registers can be restored after rendering.
                # Prefer the live player position and its OAM feet anchor.
                offset = player_offset(sprites, wram)
                if offset is not None:
                    sx, sy = obj["x"] - offset[0], obj["y"] - offset[1]
                    def u24(addr):
                        return (wram[addr] | (wram[addr + 1] << 8) |
                                (wram[addr + 2] << 16)) / 256.0
                    player_screen = (u24(0x1030) - offset[0],
                                     u24(0x1033) - offset[1])
                else:
                    sx, sy = obj["x"] - hs, obj["y"] - vs
                    player_screen = None
                near = [s for s in sprites
                        if abs((s.x + s.size / 2) - sx) < 80 and
                        abs((s.y + s.size / 2) - sy) < 96]
                if player_screen is not None:
                    pb = (player_screen[0] - 24, player_screen[1] - 56,
                          player_screen[0] + 24, player_screen[1] + 10)
                    near = [s for s in near
                            if not (s.x + s.size > pb[0] and s.x < pb[2] and
                                    s.y + s.size > pb[1] and s.y < pb[3])]
                if near:
                    crop_img, cx, cy = compose_oam(obj_vram, colours, near)
                    bbox = crop_img.getbbox()
                    if bbox:
                        crop_img = crop_img.crop(bbox)
                        x0, y0 = cx + bbox[0], cy + bbox[1]
                        clean = largest_alpha_crop(crop_img)
                        if clean is not None:
                            crop_img, dx, dy = clean
                            x0 += dx
                            y0 += dy
                        crop_img.save(args.out /
                                      f"object_{args.object:02x}.png")
                        meta = {"species": args.object,
                                "obj_world": [obj["x"], obj["y"]],
                                "scroll": [hs, vs],
                                "obj_screen": [sx, sy],
                                "rect": [x0, y0,
                                         x0 + crop_img.width,
                                         y0 + crop_img.height],
                                "anchor": [sx - x0, sy - y0],
                                "sprites": len(near)}
                        (args.out /
                         f"object_{args.object:02x}.json").write_text(
                            json.dumps(meta, indent=1))
                        print(f"object {args.object:02x}: crop "
                              f"{crop_img.size} anchor {meta['anchor']} "
                              f"from {len(near)} sprites")
    (args.out / "sprites.json").write_text(json.dumps(sprite_rows, indent=1))
    print(f"{len(sprite_rows)} sprites -> {args.out / 'oam_layer.png'}")

    # Largest cluster of sprites = the boss.
    boxes = []
    for s in sprite_rows:
        boxes.append([s["x"], s["y"], s["x"] + s["width"],
                      s["y"] + s["height"]])
    merged = []
    for box in boxes:
        placed = False
        for m in merged:
            if not (box[2] < m[0] - 8 or box[0] > m[2] + 8 or
                    box[3] < m[1] - 8 or box[1] > m[3] + 8):
                m[0] = min(m[0], box[0])
                m[1] = min(m[1], box[1])
                m[2] = max(m[2], box[2])
                m[3] = max(m[3], box[3])
                placed = True
                break
        if not placed:
            merged.append(list(box))
    if merged:
        big = max(merged, key=lambda m: (m[2] - m[0]) * (m[3] - m[1]))
        crop = canvas.crop((max(0, big[0]), max(0, big[1]),
                            min(W, big[2]), min(H, big[3])))
        crop.save(args.out / "boss.png")
        print(f"boss cluster {crop.size} at {big[:2]}")
        (args.out / "boss.json").write_text(json.dumps(
            {"rect": big, "size": crop.size}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
