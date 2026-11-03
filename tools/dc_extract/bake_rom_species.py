#!/usr/bin/env python3
"""Bake exact ROM metasprite art for enemy species from oracle-resolved groups.

The species -> metasprite mapping is not stored as a table in the ROM: each
species init writes `$8B`-bank pointers into the live object record, and the
guest draws whatever `$8B:8000` group those resolve to.  `match_group_from_oam`
recovers that group by matching the OAM the guest rendered against the ROM
group data.  This tool turns such a resolved group into per-species PNG frames
and merges them into `species_anim.json`.

Frames are composed from the oracle frame's live OBJ VRAM (the same CHR the
guest had loaded), with the base tile and palette the guest used, so the art is
bit-exact ROM data - never a crop of a screenshot or a sheet guess.

Spec format (JSON):
  {"species": {"10": {"group": 89, "base": 224, "palette": 0,
                      "capture": "_dc_probe", "frames": [4, 5, 6]}}}

`capture` names a directory under --captures holding `f*.json` +
`f*.vram.bin`.  When `frames` is omitted the tool starts at the frame index the
oracle showed and keeps consecutive frames whose part count stays within 30%,
up to --max-frames.

Usage:
  python3 tools/dc_extract/bake_rom_species.py --spec /tmp/spec.json \
      --out assets/generated
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from extract import OamSprite, Rom, compose_oam_indices, colorize  # noqa: E402

ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"


def load_capture(d: Path):
    files = sorted(d.glob("f*.json"))
    if not files:
        raise SystemExit(f"no frame json in {d}")
    doc = json.loads(files[0].read_text())
    vram_path = files[0].with_suffix(".vram.bin")
    if not vram_path.is_file():
        vram_path = d / "vram.bin"
    vram = list(struct.unpack("<32768H", vram_path.read_bytes()))
    cgram = bytes.fromhex(doc["cgram"])
    colors = [((w & 31) * 8, ((w >> 5) & 31) * 8, ((w >> 10) & 31) * 8)
              for w in struct.unpack("<256H", cgram)]
    ppu = doc.get("ppu", {})
    obsel = int(str(ppu.get("obsel", "0")), 16) if isinstance(
        ppu.get("obsel"), str) else int(ppu.get("obsel", 0))
    obj_base = (obsel & 7) << 13
    return vram[obj_base:obj_base + 0x2000], colors


def compose(obj_vram, colors, parts, base_tile, palette, obj_offset=(0.0, 0.0)):
    """Return (image, anchor_x, anchor_y) for one ROM metasprite frame.

    `obj_offset` is (object_position - metasprite_origin) measured from the
    oracle frame.  The guest draws the metasprite origin at a fixed offset above
    the object position (about 19 px for the enemies checked), so the port -
    which draws relative to the object position - needs that offset folded into
    the anchor.  Without it every sprite sits ~19 px too low.
    """
    sprites = []
    for idx, p in enumerate(parts):
        t = p["tile"]
        old_b4 = t & 0x10
        tile = t + base_tile
        if (tile & 0x10) != old_b4:  # $80:DA33 tile-base carry rule
            tile += 0x10
        sprites.append(OamSprite(idx, p["dx"], p["dy"], p["size"],
                                 tile & 0x1FF, palette, p["hflip"], p["vflip"]))
    index_img, min_x, min_y = compose_oam_indices(obj_vram, sprites)
    bbox = index_img.getbbox()
    if bbox is None:
        return None
    cropped = index_img.crop(bbox)
    pal = [colors[0x80 + palette * 16 + i] for i in range(16)]
    img = colorize(cropped, pal)
    # The image's top-left sits at (bbox[0]-min_x, bbox[1]-min_y) relative to
    # the metasprite origin; the anchor is measured from the object position.
    # `min_x`/`min_y` are the index-image origin (the leftmost/topmost part in
    # metasprite coordinates), so the image's top-left is (min_x + bbox[0],
    # min_y + bbox[1]) relative to the metasprite origin.
    return (img,
            obj_offset[0] - min_x - bbox[0],
            obj_offset[1] - min_y - bbox[1])


def pick_frames(frames, start, max_frames):
    if start is None or start >= len(frames):
        start = 0
    ref = len(frames[start])
    out = []
    for i in range(start, len(frames)):
        n = len(frames[i])
        if out and abs(n - ref) > max(1, ref * 0.3):
            break
        out.append(i)
        if len(out) >= max_frames:
            break
    if len(out) < 2:
        out = list(range(min(max_frames, len(frames))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--captures", type=Path, default=ROOT / "captures" / "rooms")
    ap.add_argument("--max-frames", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())
    rom = Rom(ROM)
    anim_path = args.out / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() else {"species": {}}

    report = {}
    for key, ent in sorted(spec["species"].items()):
        species = int(key, 16) if isinstance(key, str) else int(key)
        species = ent.get("species", species)
        key = f"{species:02x}"
        if key in anim["species"]:
            print(f"species {key}: already present, refusing to overwrite")
            continue
        group = int(ent.get("group", -1))
        if "parts" in ent:
            # A sprite the guest draws as one fixed CHR tile (no resolvable
            # group frame): the part list is stated explicitly in the spec.
            frames = [ent["parts"]]
            group = -1
        else:
            frames = rom.parse_metasprite_group(group)
        if not frames:
            print(f"species {key}: group {group:02X} has no frames")
            continue
        obj_vram, colors = load_capture(args.captures / ent["capture"])
        base = int(ent["base"])
        palette = int(ent["palette"])
        offset = tuple(ent.get("obj_offset", (0.0, 0.0)))
        indices = ent.get("frames") or pick_frames(
            frames, ent.get("frame_index"), args.max_frames)
        baked = []
        for i in indices:
            if i >= len(frames):
                continue
            res = compose(obj_vram, colors, frames[i], base, palette, offset)
            if res is None:
                print(f"species {key}: frame {i} composed empty")
                continue
            img, ax, ay = res
            name = f"enemy_{key}_{len(baked)}.png"
            if not args.dry_run:
                img.save(args.out / name)
            baked.append({"texture": name, "anchor_x": ax, "anchor_y": ay,
                          "duration": 8, "width": img.width,
                          "height": img.height, "_group_frame": i})
        if not baked:
            print(f"species {key}: nothing baked")
            continue
        for f in baked:
            f.pop("_group_frame", None)
        if group >= 0:
            source = (f"ROM $8B:8000 metasprite group ${group:02X} "
                      f"(oracle OAM match, {ent['capture']})")
        else:
            source = (f"ROM OBJ CHR tile (oracle OAM, {ent['capture']}; "
                      "metasprite group unresolved)")
        entry = {
            "species": species,
            "frames": baked,
            "source": source,
            "states": {"0": list(range(len(baked)))},
            "default": 0,
        }
        if "flags" in ent:
            entry["flags"] = int(ent["flags"])
        if not args.dry_run:
            anim["species"][key] = entry
        report[key] = {"group": group, "frames": len(baked),
                       "size": [baked[0]["width"], baked[0]["height"]],
                       "anchor": [baked[0]["anchor_x"], baked[0]["anchor_y"]]}
        print(f"species {key}: group ${group:02X} -> {len(baked)} frames "
              f"{baked[0]['width']}x{baked[0]['height']}")

    if not args.dry_run:
        anim_path.write_text(json.dumps(anim, indent=1))
        # Prove the merge parses and kept every pre-existing entry.
        again = json.loads(anim_path.read_text())
        print(f"species_anim.json now has {len(again['species'])} species")
    (args.out / "rom_species_report.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
