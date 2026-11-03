#!/usr/bin/env python3
"""Match extracted rooms to the community full-stage maps.

Each room's BG1 is rendered from its tilemap plus the baked per-palette atlases
(`bg_area<N>_pal<P>.png`), then compared against every map (downscaled to a
common width) on grayscale, ignoring exact colours since the maps may have been
captured with different palettes.

Output: assets/generated/map_matches.json with the best map per room, the score
and the grid comparison (our screens vs the map's screens).

Usage:
  python tools/dc_extract/match_maps.py --rooms assets/generated \
      --maps docs/FullMaps/images --out assets/generated/map_matches.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image

TILE = 8
ATLAS_TILES_W = 32
SCALE = 0.25  # compare at a quarter resolution


def render_bg1(room_dir: Path, area: int, layer: dict) -> Image.Image | None:
    tilemap = layer.get("tilemap") or []
    width = int(layer.get("map_width") or 32)
    height = int(layer.get("map_height") or 32)
    if not tilemap:
        return None
    atlases: dict[int, Image.Image] = {}
    for pal in range(8):
        path = room_dir / f"bg_area{area}_pal{pal}.png"
        if path.is_file():
            atlases[pal] = Image.open(path).convert("RGB")
    if not atlases:
        return None
    img = Image.new("RGB", (width * TILE, height * TILE), (0, 0, 0))
    for ty in range(height):
        for tx in range(width):
            word = tilemap[(ty * width + tx) % len(tilemap)]
            tile = word & 0x3FF
            pal = (word >> 10) & 7
            atlas = atlases.get(pal)
            if atlas is None:
                continue
            qx = 256 if (word & 0x4000) else 0
            qy = 256 if (word & 0x8000) else 0
            sx = qx + (tile % ATLAS_TILES_W) * TILE
            sy = qy + (tile // ATLAS_TILES_W) * TILE
            if sx + TILE > atlas.width or sy + TILE > atlas.height:
                continue
            img.paste(atlas.crop((sx, sy, sx + TILE, sy + TILE)),
                      (tx * TILE, ty * TILE))
    return img


def mask_thumb(img: Image.Image, width: int = 96, height: int = 32) -> bytes:
    """Content mask (non-black) resized to a fixed grid, aspect ignored."""
    gray = img.convert("L").resize((width, height), Image.BILINEAR)
    return bytes(255 if v > 18 else 0 for v in gray.tobytes())


def score(a: bytes, b: bytes) -> float:
    """1 - IoU of the two content masks (lower is better)."""
    inter = union = 0
    for x, y in zip(a, b):
        if x or y:
            union += 1
            if x and y:
                inter += 1
    if union == 0:
        return 1.0
    return 1.0 - inter / union


def density(a: bytes) -> float:
    return sum(1 for v in a if v) / max(1, len(a))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rooms", type=Path, default=Path("assets/generated"))
    ap.add_argument("--maps", type=Path, default=Path("docs/FullMaps/images"))
    ap.add_argument("--out", type=Path,
                    default=Path("assets/generated/map_matches.json"))
    args = ap.parse_args()

    maps = []
    for path in sorted(args.maps.glob("*.webp")):
        with Image.open(path) as im:
            thumb = mask_thumb(im.convert("RGB"))
            if density(thumb) < 0.02:
                continue
            maps.append((path.stem.replace("demons-crest-", "")
                         .replace("-snes-map", ""), thumb))
    if not maps:
        print("no maps found")
        return 1

    results = {}
    for path in sorted(args.rooms.glob("room_area*.json")):
        data = json.loads(path.read_text())
        area = int(data.get("area_id", 0))
        layer = next((b for b in data.get("bg", []) if b.get("name") == "bg1"),
                     None)
        if not layer:
            continue
        rendered = render_bg1(args.rooms, area, layer)
        if rendered is None:
            continue
        thumb = mask_thumb(rendered)
        if density(thumb) < 0.02:
            continue
        scored = sorted(((score(thumb, m), name) for name, m in maps))[:3]
        best = scored[0]
        world = data.get("world", {})
        ours = [math.ceil((world.get("width") or 0) / 256),
                math.ceil((world.get("height") or 0) / 224)]
        map_name = best[1]
        map_entry = next((p for p in json.loads(
            (args.maps.parent / "index.json").read_text())["maps"]
            if p["name"] == map_name), None)
        results[str(area)] = {
            "best": map_name,
            "score": round(best[0], 1),
            "runner_up": [{"name": n, "score": round(s, 1)}
                          for s, n in scored[1:]],
            "our_screens": ours,
            "map_screens": (map_entry or {}).get("screens"),
        }
        print(f"area {area:3d}: {map_name} (score {best[0]:.1f}) "
              f"ours {ours} map {(map_entry or {}).get('screens')}")

    args.out.write_text(json.dumps(results, indent=1))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
