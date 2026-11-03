#!/usr/bin/env python3
"""Bake object sprites from probed saves by OAM clustering.

Bosses (and large enemies) are drawn from many OAM entries that can spread far
from the object's world position; a fixed window grabs the player/HUD too. This
tool:

  1. derives the world→screen offset from the player's palette-7 OAM cluster,
  2. unions OAM sprites into clusters by proximity,
  3. picks the cluster nearest the object's projected screen position,
  4. composes it with each sprite's own palette and records an anchor relative
     to the object's world position,
  5. merges the result into `species_anim.json` without dropping other species.

Usage:
  python tools/dc_extract/bake_object_sprites.py --probe-root <...>/oracle_probe \
      --saves 0a,2a,5a,6a,7a --out assets/generated
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import OamSprite, parse_oam, tile_pixels  # noqa: E402


def cgram_colors(raw: bytes) -> list[tuple[int, int, int]]:
    words = struct.unpack("<%dH" % (len(raw) // 2), raw)
    return [((w & 31) * 8, ((w >> 5) & 31) * 8, ((w >> 10) & 31) * 8)
            for w in words]


def player_offset(sprites: list[OamSprite], player_world) -> tuple[float, float] | None:
    pal7 = [s for s in sprites if s.palette == 7 and s.y < 224]
    if not pal7:
        return None
    clusters: list[list[OamSprite]] = []
    for s in pal7:
        for c in clusters:
            if any(abs(s.x - t.x) < 40 and abs(s.y - t.y) < 56 for t in c):
                c.append(s)
                break
        else:
            clusters.append([s])
    best = max(clusters, key=len)
    feet_x = (min(s.x for s in best) + max(s.x + s.size for s in best)) / 2
    feet_y = max(s.y + s.size for s in best)
    return (player_world[0] - feet_x, player_world[1] - feet_y)


def cluster_sprites(sprites: list[OamSprite], radius: float = 28.0):
    parent = list(range(len(sprites)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(sprites):
        for j in range(i + 1, len(sprites)):
            b = sprites[j]
            ax, ay = a.x + a.size / 2, a.y + a.size / 2
            bx, by = b.x + b.size / 2, b.y + b.size / 2
            if math.hypot(ax - bx, ay - by) <= radius:
                union(i, j)
    groups: dict[int, list[OamSprite]] = {}
    for i, s in enumerate(sprites):
        groups.setdefault(find(i), []).append(s)
    return list(groups.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe-root", type=Path, required=True)
    ap.add_argument("--saves", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cluster-radius", type=float, default=28.0)
    args = ap.parse_args()

    anim_path = args.out / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {"species": {}}

    candidates: dict[int, list[dict]] = {}

    for tag in [s.strip() for s in args.saves.split(",") if s.strip()]:
        src = args.probe_root / f"save{tag}"
        if not (src / "info.json").is_file():
            print(f"skip save{tag}: no probe")
            continue
        info = json.loads((src / "info.json").read_text())
        oam = (src / "oam.bin").read_bytes()
        cgram = cgram_colors((src / "cgram.bin").read_bytes())
        vram = list(struct.unpack(
            "<32768H", (src / "vram.bin").read_bytes()))
        ppu = json.loads((src / "ppu.json").read_text())
        body = ppu.get("ppu", ppu)
        obsel = int(str(body.get("obsel", "3")), 16) if isinstance(
            body.get("obsel"), str) else int(body.get("obsel", 3))
        obj_base = (obsel & 7) << 13
        obj_vram = vram[obj_base:obj_base + 0x2000]

        sprites = parse_oam(oam, obsel)
        off = player_offset(sprites, info["player"])
        if off is None:
            print(f"save{tag}: no player cluster; skipping")
            continue
        groups = cluster_sprites(sprites, args.cluster_radius)
        for ent in info.get("species", []):
            species = int(ent["species"])
            # Skip species that already have a good sheet? No: prefer probing.
            bx, by = ent["x"] - off[0], ent["y"] - off[1]
            best = None
            best_d = 1e9
            for g in groups:
                gx = sum(s.x + s.size / 2 for s in g) / len(g)
                gy = sum(s.y + s.size / 2 for s in g) / len(g)
                d = math.hypot(gx - bx, gy - by)
                if d < best_d:
                    best_d, best = d, g
            if not best or best_d > 96:
                print(f"save{tag}: species {species:02X} no cluster near "
                      f"({bx:.0f},{by:.0f}) d={best_d:.0f}")
                continue
            # Compose with each sprite's OWN palette: painting the merged
            # index image with a single palette was a real bug (every part was
            # coloured as palette 0), which is why multi-palette bosses looked
            # wrong even when the geometry was right.
            min_x = min(s.x for s in best)
            min_y = min(s.y for s in best)
            max_x = max(s.x + s.size for s in best)
            max_y = max(s.y + s.size for s in best)
            img = Image.new("RGBA", (max_x - min_x, max_y - min_y),
                            (0, 0, 0, 0))
            dst = img.load()
            for s in sorted(best, key=lambda s: s.index, reverse=True):
                base = 0x80 + s.palette * 16
                for row in range(s.size):
                    for col in range(s.size):
                        used_col = s.size - 1 - col if s.hflip else col
                        used_row = s.size - 1 - row if s.vflip else row
                        tile = s.tile
                        if s.size == 16:
                            tile &= ~1
                        used_tile = (((tile >> 4) + (used_row >> 3)) << 4) | \
                                    (((tile & 0x0F) + (used_col >> 3)) & 0x0F)
                        p_idx = tile_pixels(obj_vram, used_tile * 16)[
                            used_row & 7][used_col & 7]
                        if p_idx:
                            color = cgram[(base + p_idx) % len(cgram)]
                            dst[s.x - min_x + col, s.y - min_y + row] = (
                                color[0], color[1], color[2], 255)
            bbox = img.getbbox()
            if bbox is None:
                continue
            crop = img.crop(bbox)
            filled = sum(1 for px in crop.getdata() if px[3])
            fill = filled / max(1, crop.width * crop.height)
            aspect = max(crop.width, crop.height) / max(1, min(crop.width,
                                                               crop.height))
            area = crop.width * crop.height
            min_fill = 0.15 if area <= 40 * 40 else 0.42
            plausible = (area >= 64 and fill >= min_fill and aspect <= 3.0)
            candidates.setdefault(species, []).append({
                "img": crop, "tag": tag, "dist": best_d, "fill": fill,
                "aspect": aspect, "plausible": plausible,
                "anchor": (round(bx - (min_x + bbox[0]), 2),
                           round(by - (min_y + bbox[1]), 2)),
                "parts": len(best), "size": crop.size,
            })
            print(f"save{tag}: species {species:02X} cand {crop.size} "
                  f"parts={len(best)} d={best_d:.0f} fill={fill:.2f} "
                  f"aspect={aspect:.1f} plausible={plausible}")

    # Validate sheets already in the manifest; only replace implausible ones
    # with a plausible probe candidate, and never ship a fragmented sheet.
    def sheet_stats(path: Path):
        if not path.is_file():
            return (0.0, 1.0, (0, 0))
        im = Image.open(path).convert("RGBA")
        filled = sum(1 for px in im.getdata() if px[3])
        fill = filled / max(1, im.width * im.height)
        aspect = max(im.width, im.height) / max(1, min(im.width, im.height))
        return (fill, aspect, im.size)

    for key in list(anim["species"]):
        entry = anim["species"][key]
        tex = entry["frames"][0]["texture"] if entry.get("frames") else ""
        fill, aspect, size = sheet_stats(args.out / tex)
        area = size[0] * size[1]
        min_fill = 0.15 if area <= 40 * 40 else 0.42
        ok_existing = (area >= 64 and fill >= min_fill and aspect <= 3.0)
        species = int(key, 16)
        cands = [c for c in candidates.get(species, []) if c["plausible"]]
        if ok_existing:
            continue
        if cands:
            best = min(cands, key=lambda c: c["dist"])
            name = f"enemy_{species:02x}_0.png"
            best["img"].save(args.out / name)
            entry["frames"] = [{
                "texture": name, "anchor_x": best["anchor"][0],
                "anchor_y": best["anchor"][1], "duration": 8,
                "width": best["size"][0], "height": best["size"][1]}]
            entry["source"] = f"probe save{best['tag']} cluster"
            print(f"species {species:02X}: replaced implausible sheet with "
                  f"{best['size']} fill={best['fill']:.2f}")
        else:
            anim["species"].pop(key)
            print(f"species {species:02X}: dropped implausible sheet "
                  f"(silhouette will be used)")

    # Add missing species when we have a plausible candidate.
    for species, cands in candidates.items():
        key = f"{species:02x}"
        if key in anim["species"]:
            continue
        good = [c for c in cands if c["plausible"]]
        if not good:
            print(f"species {species:02X}: no plausible sheet; silhouette")
            continue
        best = min(good, key=lambda c: c["dist"])
        name = f"enemy_{species:02x}_0.png"
        best["img"].save(args.out / name)
        anim["species"][key] = {
            "species": species,
            "frames": [{
                "texture": name, "anchor_x": best["anchor"][0],
                "anchor_y": best["anchor"][1], "duration": 8,
                "width": best["size"][0], "height": best["size"][1]}],
            "source": f"probe save{best['tag']} cluster",
        }
        print(f"species {species:02X}: added {best['size']} "
              f"fill={best['fill']:.2f}")

    anim_path.write_text(json.dumps(anim, indent=1))
    print("species now:", sorted(anim["species"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
