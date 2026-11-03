#!/usr/bin/env python3
"""Resolve species -> $8B:8000 metasprite group by matching live OAM to ROM data.

The species -> metasprite mapping is resolved at runtime: each species init
writes `$8B`-bank pointers into the live object record and the guest draws the
group those resolve to.  The oracle frame captures store the OAM the guest
actually rendered plus the object records in WRAM, so the group can be
recovered exactly: a metasprite frame has a signature (part count, each part's
tile index, size, flip bits and (dx, dy) offset from the object origin), and
matching that signature against the OAM around an object identifies the group
and frame the game used - no sheet guessing.

Usage:
  python3 tools/dc_extract/match_group_from_oam.py --captures captures/rooms
  python3 tools/dc_extract/match_group_from_oam.py --captures captures/rooms \
      --out /tmp/group_votes.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from extract import Rom, parse_oam  # noqa: E402

ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"
OBJ_STRIDE, OBJ_SLOTS = 0x50, 26


def fx(raw) -> tuple[float, float]:
    return ((raw[0] | (raw[1] << 8) | (raw[2] << 16)) / 256.0,
            (raw[3] | (raw[4] << 8) | (raw[5] << 16)) / 256.0)


def load_capture(d: Path, f: Path):
    doc = json.loads(f.read_text())
    oam = bytes.fromhex(doc["oam"]) + bytes.fromhex(doc["highOam"])
    wram = bytes.fromhex(doc["wram_1000"])
    vram_path = f.with_suffix(".vram.bin")
    if not vram_path.is_file():
        vram_path = d / "vram.bin"
    vram = list(struct.unpack("<32768H", vram_path.read_bytes()))
    ppu = doc.get("ppu", {})
    obsel = int(str(ppu.get("obsel", "0")), 16) if isinstance(
        ppu.get("obsel"), str) else int(ppu.get("obsel", 0))
    return doc, oam, wram, vram, obsel


def player_offset(sprites, player):
    groups = []
    for s in sprites:
        if s.palette != 7 or s.y >= 224:
            continue
        for g in groups:
            if any(abs(s.x - gx) < 40 and abs(s.y - gy) < 64 for gx, gy, _z in g):
                g.append((s.x, s.y, s.size))
                break
        else:
            groups.append([(s.x, s.y, s.size)])
    if not groups:
        return None
    best = max(groups, key=len)
    cx = (min(x for x, _y, _s in best) + max(x + s for x, _y, s in best)) / 2.0
    fy = max(y + s for _x, y, s in best)
    return player[0] - cx, player[1] - fy


def normalise(items):
    """Origin/tile-base invariant signature plus the reference item index.

    `items` are (x, y, size, tile, hflip, vflip) tuples.  The reference item is
    chosen by geometry only, so the same choice is made for a ROM frame and for
    the OAM that renders it (positions shift by the object origin, tiles by the
    base tile).
    """
    if not items:
        return None
    ref = min(range(len(items)),
              key=lambda i: (items[i][0], items[i][1], items[i][2]))
    x0, y0, _s0, t0, _h0, _v0 = items[ref]
    return (ref, len(items), tuple(sorted(
        (x - x0, y - y0, s, (t - t0) & 0xFF, h, v)
        for x, y, s, t, h, v in items)))


def build_index(groups):
    index: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for gid, frames in groups.items():
        for fi, parts in enumerate(frames):
            if not parts:
                continue
            items = [(p["dx"], p["dy"], p["size"], p["tile"],
                      p["hflip"], p["vflip"]) for p in parts]
            sig = normalise(items)
            if sig is None:
                continue
            index[(sig[1], sig[2])].append((gid, fi))
    return index


def verify(parts, sprites, base, ox, oy):
    used = set()
    for p in parts:
        want = (p["tile"] + base) & 0xFF
        hit = None
        for k, t in enumerate(sprites):
            if k in used or t.size != p["size"]:
                continue
            if t.x == ox + p["dx"] and t.y == oy + p["dy"] \
                    and (t.tile & 0xFF) == want and t.hflip == p["hflip"] \
                    and t.vflip == p["vflip"]:
                hit = k
                break
        if hit is None:
            return False
        used.add(hit)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--captures", type=Path, default=ROOT / "captures" / "rooms")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--window", type=int, default=72)
    ap.add_argument("--min-parts", type=int, default=3)
    ap.add_argument("--species", default="",
                    help="comma-separated hex species ids to report")
    args = ap.parse_args()

    only = {int(x, 16) for x in args.species.split(",") if x.strip()}
    rom = Rom(ROM)
    groups = {}
    for gid in range(256):
        try:
            groups[gid] = rom.parse_metasprite_group(gid)
        except Exception:  # noqa: BLE001 - bogus ids decode to junk
            continue
    index = build_index(groups)

    votes: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    detail = []
    dirs = sorted(p for p in args.captures.iterdir() if p.is_dir())
    if args.limit:
        dirs = dirs[:args.limit]
    for d in dirs:
        files = sorted(d.glob("f*.json"))
        for f in files:
            run_one(d, f, args, index, groups, votes, detail)

    print(f"{len(detail)} matches")
    for species in sorted(votes):
        top = sorted(votes[species].items(), key=lambda kv: -kv[1])[:4]
        print(f"species {species:02X}: " +
              ", ".join(f"group {g:02X}x{n}" for g, n in top))
    if args.out:
        args.out.write_text(json.dumps(
            {"votes": {f"{k:02x}": dict(v) for k, v in votes.items()},
             "detail": detail}, indent=1))
        print("wrote", args.out)
    return 0


def run_one(d, f, args, index, groups, votes, detail):
    only = {int(x, 16) for x in args.species.split(",") if x.strip()}
    if True:
        try:
            doc, oam, wram, vram, obsel = load_capture(d, f)
        except Exception as exc:  # noqa: BLE001
            print(f"{d.name}/{f.name}: skip ({exc})")
            return
        sprites = parse_oam(oam, obsel)
        player = fx(wram[0x30:0x36])
        off = player_offset(sprites, player)
        if off is None:
            return
        for slot in range(OBJ_SLOTS):
            r = wram[0x80 + slot * OBJ_STRIDE: 0x80 + (slot + 1) * OBJ_STRIDE]
            if len(r) < OBJ_STRIDE or r[0] == 0 or r[2] == 0:
                continue
            species = r[2]
            if only and species not in only:
                continue
            wx, wy = fx(bytes([r[0x30], r[0x31], r[0x32],
                               r[0x33], r[0x34], r[0x35]]))
            sx, sy = wx - off[0], wy - off[1]
            near = [s for s in sprites
                    if s.palette != 7 and s.y < 224
                    and abs(s.x - sx) < args.window
                    and abs(s.y - sy) < args.window]
            if len(near) < args.min_parts:
                continue
            items = [(s.x, s.y, s.size, s.tile, s.hflip, s.vflip)
                     for s in near]
            sig = normalise(items)
            if sig is None:
                continue
            ref_idx, n, key = sig
            best = None
            for gid, fi in index.get((n, key), ()):
                parts = groups[gid][fi]
                p0 = parts[ref_idx] if ref_idx < len(parts) else None
                if p0 is None:
                    continue
                base = (near[ref_idx].tile - p0["tile"]) & 0xFF
                ox = near[ref_idx].x - p0["dx"]
                oy = near[ref_idx].y - p0["dy"]
                if not verify(parts, near, base, ox, oy):
                    continue
                d_obj = abs(ox - sx) + abs(oy - sy)
                score = (n, -d_obj)
                if best is None or score > best[0]:
                    best = (score, gid, fi, ox, oy, base)
            if best is None:
                continue
            _score, gid, fi, ox, oy, base = best
            if abs(ox - sx) > 24 or abs(oy - sy) > 32:
                continue
            votes[species][gid] += 1
            detail.append({"dir": d.name, "frame": doc["frame"], "slot": slot,
                           "species": species, "group": gid, "frame_index": fi,
                           "origin": [ox, oy], "object_screen": [sx, sy],
                           "base": base, "parts": n,
                           "palette": near[0].palette})


if __name__ == "__main__":
    raise SystemExit(main())
