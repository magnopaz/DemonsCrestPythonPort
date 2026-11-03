#!/usr/bin/env python3
"""Bake per-species enemy sprites from `capture_species.py` dumps.

Each capture directory holds OAM/CGRAM/VRAM dumps for one species plus the
object's world position and the measured world->screen offset. This tool:

  * selects the OAM sprites that belong to the injected object (a window around
    its screen position, excluding the player group),
  * composes them with their own palettes from the captured CGRAM,
  * crops the result and records an anchor relative to the object's feet,
  * deduplicates identical poses and writes `enemy_<species>_<n>.png`,
  * emits `species_anim.json` used by `src/assets.c` / `src/render.c`.

Usage:
  python3 tools/dc_extract/extract_species.py \
      --dump captures/species --out assets/generated
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import (Rom, parse_oam, compose_oam, cgram_colors)  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", type=Path, default=ROOT / "captures" / "species")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--radius-x", type=float, default=36.0,
                    help="half-width of the object sprite window")
    ap.add_argument("--radius-y", type=float, default=56.0,
                    help="half-height of the object sprite window")
    ap.add_argument("--pose-frames", type=int, default=6,
                    help="frames each baked pose is shown (default 6)")
    ap.add_argument("--prune", action="store_true",
                    help="replace species_anim.json instead of merging; the "
                         "default preserves hand-baked entries such as bosses")
    return ap.parse_args()


def load_frame(path: Path):
    state = json.loads(path.read_text())
    vram = list(struct.unpack("<32768H",
                              path.with_suffix(".vram.bin").read_bytes()))
    cgram = cgram_colors(bytes.fromhex(state["cgram"].replace(" ", "")))
    ppu = state["ppu"]
    obsel = int(ppu["obsel"], 16) if isinstance(ppu["obsel"], str) else int(ppu["obsel"])
    oam = bytes.fromhex(state["oam"].replace(" ", ""))
    return state, vram, cgram, obsel, oam


def intersects(x, y, w, h, box):
    return not (x + w <= box[0] or x >= box[2] or y + h <= box[1] or y >= box[3])


def player_anchor(sprites, player_world):
    """Feet anchor of the player's OAM group, used to derive world->screen.

    The guest restores the BG scroll registers after rendering, so the PPU
    scroll at dump time is not the render scroll. The player's world position is
    known exactly ($1030/$1033) and its sprite is anchored at the feet, so the
    palette-7 group gives the offset. Groups are clustered because some species
    also draw with palette 7.
    """
    pal7 = [s for s in sprites if s.palette == 7 and s.y < 224]
    if not pal7:
        return None
    clusters: list[list] = []
    for s in pal7:
        for c in clusters:
            if any(abs(s.x - t.x) < 40 and abs(s.y - t.y) < 64 for t in c):
                c.append(s)
                break
        else:
            clusters.append([s])
    best = max(clusters, key=len)
    min_x = min(s.x for s in best)
    max_x = max(s.x + s.size for s in best)
    max_y = max(s.y + s.size for s in best)
    anchor = ((min_x + max_x) / 2.0, float(max_y))
    return ((player_world[0] - anchor[0], player_world[1] - anchor[1]),
            anchor)


def main() -> int:
    args = parse_args()
    manifest_path = args.dump / "manifest.json"
    if not manifest_path.is_file():
        print(f"extract_species: missing {manifest_path}", file=sys.stderr)
        return 77
    manifest = json.loads(manifest_path.read_text())
    args.out.mkdir(parents=True, exist_ok=True)

    out_species: dict[str, dict] = {}
    skipped_player: list[str] = []
    total_png = 0
    for key, entry in sorted(manifest.get("species", {}).items()):
        species = int(key, 16)
        manifest_offset = entry.get("offset")
        use_manifest_offset = bool(entry.get("offset_v2")) and \
            manifest_offset is not None
        frames = []
        seen: list[bytes] = []
        for frame_no in entry["frames"]:
            path = args.dump / f"s{species:02x}" / f"f{frame_no:06d}.json"
            if not path.is_file():
                continue
            state, vram, cgram, obsel, oam = load_frame(path)
            sprites = parse_oam(oam, obsel)
            obj_world = state["object_world"]
            player_world = state["player_world"]
            if use_manifest_offset:
                # The pre-injection capture measured the player anchor while
                # only the player was present. Re-deriving it from the
                # post-injection frame is what let a palette-7 species become
                # the "player" anchor in the old pipeline.
                offset = tuple(manifest_offset)
                player_screen = (player_world[0] - offset[0],
                                 player_world[1] - offset[1])
            else:
                derived = player_anchor(sprites, player_world)
                if derived is None:
                    continue
                offset, player_screen = derived
            obj_screen = (obj_world[0] - offset[0], obj_world[1] - offset[1])
            player_box = (player_screen[0] - 24, player_screen[1] - 56,
                          player_screen[0] + 24, player_screen[1] + 10)
            window = (obj_screen[0] - args.radius_x,
                      obj_screen[1] - args.radius_y,
                      obj_screen[0] + args.radius_x,
                      obj_screen[1] + args.radius_y)
            chosen = []
            for s in sprites:
                if s.y >= 224:
                    continue
                if not intersects(s.x, s.y, s.size, s.size, window):
                    continue
                if intersects(s.x, s.y, s.size, s.size, player_box):
                    continue
                chosen.append(s)
            if not chosen:
                continue
            obj_base = (obsel & 7) << 13
            obj_vram = vram[obj_base:obj_base + 0x2000]
            # Reject species that came out identical to the player sheet: some
            # injections leave the sprite pointer at its default, so the guest
            # draws Firebrand instead of the species.
            pal7 = [s for s in sprites if s.palette == 7 and s.y < 224]
            player_raw = None
            if pal7:
                clusters: list[list] = []
                for s in pal7:
                    for c in clusters:
                        if any(abs(s.x - t.x) < 40 and abs(s.y - t.y) < 64
                               for t in c):
                            c.append(s)
                            break
                    else:
                        clusters.append([s])
                best = max(clusters, key=len)
                try:
                    pimg, _px, _py = compose_oam(obj_vram, cgram, best)
                    pb = pimg.getbbox()
                    if pb:
                        player_raw = pimg.crop(pb).tobytes()
                except SystemExit:
                    player_raw = None
            try:
                img, min_x, min_y = compose_oam(obj_vram, cgram, chosen)
            except SystemExit:
                continue
            bbox = img.getbbox()
            if bbox is None:
                continue
            img = img.crop(bbox)
            min_x += bbox[0]
            min_y += bbox[1]
            raw = img.tobytes()
            if player_raw is not None and raw == player_raw:
                skipped_player.append(key)
                break
            if raw in seen:
                continue
            seen.append(raw)
            name = f"enemy_{species:02x}_{len(frames)}.png"
            img.save(args.out / name)
            total_png += 1
            frames.append({
                "texture": name,
                "anchor_x": round(obj_screen[0] - min_x, 2),
                "anchor_y": round(obj_screen[1] - min_y, 2),
                "duration": max(1, args.pose_frames),
                "width": img.width,
                "height": img.height,
            })
        if frames:
            out_species[key] = {"species": species, "frames": frames,
                                "source": f"capture_species {key}"}
            print(f"  species {key}: {len(frames)} pose(s) "
                  f"{[f['texture'] for f in frames]}")

    # Drop ambiguous sheets: when two species produce byte-identical images the
    # capture did not actually show their own sprite (both fell back to the same
    # object), so rendering them would duplicate one creature everywhere. Those
    # species are left out of the manifest and the renderer draws a silhouette.
    import hashlib
    digest_to_keys: dict[str, list[str]] = {}
    for key, entry in out_species.items():
        for frame in entry["frames"]:
            path = args.out / frame["texture"]
            if path.is_file():
                h = hashlib.sha256(path.read_bytes()).hexdigest()
                digest_to_keys.setdefault(h, []).append(key)
    ambiguous = {k for keys in digest_to_keys.values() if len(set(keys)) > 1
                 for k in keys}
    if ambiguous:
        for key in sorted(ambiguous):
            out_species.pop(key, None)
        print(f"extract_species: dropped ambiguous sheets {sorted(ambiguous)}")

    anim_path = args.out / "species_anim.json"
    existing: dict[str, dict] = {}
    if not args.prune and anim_path.is_file():
        try:
            old = json.loads(anim_path.read_text())
            if isinstance(old.get("species"), dict):
                existing = old["species"]
        except (OSError, ValueError):
            existing = {}
    # Preserve hand-baked boss/form entries unless --prune was requested. The
    # capture pass only owns the species it actually re-baked this run.
    merged = dict(existing)
    merged.update(out_species)
    anim_path.write_text(json.dumps({"species": merged}, indent=1))
    if skipped_player:
        print(f"extract_species: skipped player-lookalikes {skipped_player}")
    print(f"extract_species: {len(out_species)} baked species, "
          f"{total_png} PNGs -> {args.out} "
          f"({len(merged)} entries in {anim_path.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
