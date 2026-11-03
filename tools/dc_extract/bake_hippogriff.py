#!/usr/bin/env python3
"""Bake the cemetery Hippogriff (species $09) sheet from per-pose captures.

The guest reloads OBJ CHR per animation frame, so the nine frames of the
`$8B:8000` group `$0E` cannot all be composed from one capture's VRAM: only the
pose that was on screen has its tiles resident. Each pose below therefore comes
from the frame where the guest actually drew it, with the OAM, VRAM and CGRAM
dumped together at that frame by `tools/oracle/replay_capture.py` (or the debug
server directly).

The area-1 take (`rec_20261102_193944`, boot-start) shows these poses:

    gframe 11146  group frame 0  hover
    gframe 11374  group frame 8  feather volley
    gframe 11500  group frame 7  death/rubble (held while the slot frees)

The swoop and the stone statue never draw in that take; they come from the
reference sheet (`docs/sprites/SNES - Demon's Crest - Enemies & Bosses -
Hipogriff.gif`, row 1 charge pose and top-row statue).

Usage:
  python3 tools/dc_extract/bake_hippogriff.py --poses /tmp/hip_poses \\
      --assets assets/generated
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

from extract import Rom, OamSprite, compose_oam_indices, colorize, parse_oam  # noqa: E402
import match_group_from_oam as M  # noqa: E402

ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"
SHEET = ROOT / "docs" / "sprites" / "SNES - Demon's Crest - Enemies & Bosses - Hipogriff.gif"

POSES = {
    # semantic name: (guest frame, group frame index)
    "hover": (11146, 0),
    "volley": (11374, 8),
    "rubble": (11500, 7),
}


def fx(b: bytes):
    return ((b[0] | b[1] << 8 | b[2] << 16) / 256.0,
            (b[3] | b[4] << 8 | b[5] << 16) / 256.0)


def obsel_of(ppu: dict) -> int:
    raw = ppu.get("obsel", 0)
    return int(raw, 16) if isinstance(raw, str) else int(raw)


def boss_parts(pose: dict, parts: list[dict]):
    """Pick exactly the OAM sprites this ROM frame needs (flames are nearby)."""
    sprites = parse_oam(bytes.fromhex(pose["oam"]), obsel_of(pose["ppu"]))
    wram = bytes.fromhex(pose["wram_1000"])
    player = fx(wram[0x30:0x36])
    off = M.player_offset(sprites, player)
    if off is None:
        raise SystemExit("no player sprite to anchor the camera")
    rec = wram[0x80 + 8 * 0x50:0x80 + 9 * 0x50]
    wx, wy = fx(bytes(rec[0x30:0x36]))
    sx, sy = wx - off[0], wy - off[1]
    near = [t for t in sprites if t.palette != 7 and t.y < 224
            and abs(t.x - sx) < 80 and abs(t.y - sy) < 80]
    best = None
    for ref in parts:
        for s in near:
            if s.size != ref["size"]:
                continue
            base = (s.tile - ref["tile"]) & 0xFF
            ox, oy = s.x - ref["dx"], s.y - ref["dy"]
            picked, used = [], set()
            for p in parts:
                want = (p["tile"] + base) & 0xFF
                for k, t in enumerate(near):
                    if k in used or t.size != p["size"]:
                        continue
                    if (t.x == ox + p["dx"] and t.y == oy + p["dy"]
                            and (t.tile & 0xFF) == want
                            and t.hflip == p["hflip"]
                            and t.vflip == p["vflip"]):
                        used.add(k)
                        picked.append(t)
                        break
            score = (len(picked), -abs(ox - sx) - abs(oy - sy))
            if best is None or score > best[0]:
                best = (score, picked, sx, sy)
    if best is None:
        raise SystemExit("no ROM part matched an OAM sprite")
    score, picked, sx, sy = best
    if score[0] < max(6, int(len(parts) * 0.7)):
        raise SystemExit(f"only {score[0]}/{len(parts)} parts matched")
    return picked, picked[0].palette, sx, sy


def compose(pose: dict, sprites, palette: int):
    raw = Path(pose["_vram"]).read_bytes()
    vram = list(struct.unpack("<32768H", raw))
    base = (obsel_of(pose["ppu"]) & 7) << 13
    obj_vram = vram[base:base + 0x2000]
    words = struct.unpack("<256H", bytes.fromhex(pose["cgram"])[:512])
    colors = [((w & 31) * 8, ((w >> 5) & 31) * 8, ((w >> 10) & 31) * 8)
              for w in words]
    oam = [OamSprite(i, t.x, t.y, t.size, t.tile, palette, t.hflip, t.vflip)
           for i, t in enumerate(sprites)]
    img, min_x, min_y = compose_oam_indices(obj_vram, oam)
    bbox = img.getbbox()
    if bbox is None:
        raise SystemExit("empty composition")
    pal = colors[0x80 + palette * 16:0x80 + palette * 16 + 16]
    out = colorize(img.crop(bbox), pal)
    return out, min_x + bbox[0], min_y + bbox[1]


def keyed(crop: Image.Image) -> Image.Image:
    crop = crop.convert("RGBA")
    px = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b, _a = px[x, y]
            if (r, g, b) == (0, 0, 33):   # the sheet's dark-blue paper
                px[x, y] = (0, 0, 0, 0)
    return crop


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--poses", type=Path, required=True,
                    help="directory with pose_<gframe>.json and .vram.bin")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    args = ap.parse_args()
    args.assets.mkdir(parents=True, exist_ok=True)

    rom = Rom(ROM)
    group = rom.parse_metasprite_group(0x0E)
    frames = {}
    for name, (gframe, index) in POSES.items():
        pose = json.loads((args.poses / f"pose_{gframe}.json").read_text())
        pose["_vram"] = args.poses / f"pose_{gframe}.vram.bin"
        sprites, palette, sx, sy = boss_parts(pose, group[index])
        img, top_x, top_y = compose(pose, sprites, palette)
        tex = f"enemy_09_{name}.png"
        img.save(args.assets / tex)
        frames[name] = {
            "texture": tex, "anchor_x": round(sx - top_x, 2),
            "anchor_y": round(sy - top_y, 2), "duration": 8,
            "width": img.width, "height": img.height,
        }
        print(f"{name}: frame {index}, {img.width}x{img.height}")

    sheet = Image.open(SHEET).convert("RGB")
    swoop = keyed(sheet.crop((434, 149, 521, 203)))
    swoop.save(args.assets / "enemy_09_swoop.png")
    statue = keyed(sheet.crop((326, 33, 385, 91)))
    statue.save(args.assets / "enemy_09_statue.png")
    frames["swoop"] = {"texture": "enemy_09_swoop.png", "anchor_x": 43.5,
                       "anchor_y": 40.0, "duration": 8,
                       "width": swoop.width, "height": swoop.height}
    frames["statue"] = {"texture": "enemy_09_statue.png", "anchor_x": 29.5,
                        "anchor_y": 44.0, "duration": 8,
                        "width": statue.width, "height": statue.height}

    order = ["hover", "volley", "swoop", "statue", "rubble"]
    entry = {
        "species": 9,
        "frames": [frames[k] for k in order],
        "states": {"0": [0], "1": [1], "2": [2], "3": [2], "4": [1],
                   "5": [4], "6": [3]},
        "default": 0,
        "source": ("ROM $8B:8000 group $0E from the area-1 take "
                   f"(poses {', '.join(str(p[0]) for p in POSES.values())}) "
                   "+ sheet swoop/statue"),
    }
    path = args.assets / "species_anim.json"
    anim = json.loads(path.read_text())
    anim["species"]["09"] = entry
    path.write_text(json.dumps(anim, indent=1))
    print(f"species_anim.json now has {len(anim['species'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
