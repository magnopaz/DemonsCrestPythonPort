#!/usr/bin/env python3
"""Turn a generated (or hand-drawn, or photographed) image into a sprite the
port can actually load.

Diffusion models hand back 1024x1024 gradients with thousands of colours and
soft alpha. The engine -- and the SNES the game imitates -- wants a small
image, one transparent index, binary alpha, <=15 opaque colours, anchors
measured from the body, and an 8x8 tile footprint. This tool is the only place
that conversion should happen, so the result is deterministic and auditable.

What it does, in order:

1. keys the background (alpha channel if the input has one, otherwise the
   dominant border colour) to a single transparent index;
2. crops to the opaque bounding box;
3. resizes to ``--height`` pixels (``box`` by default: it keeps tone, which
   survives palette reduction better than nearest neighbour);
4. builds a palette of at most ``--colors`` entries by weighted median cut
   over the *opaque* pixels only, snaps every entry to the SNES 15-bit
   (BGR555) colour space, and maps pixels to it;
5. despeckles (drops alpha components below ``--min-component`` pixels) and
   forces binary alpha;
6. measures the anchors the engine uses: ``anchor_y`` from the feet (bottom
   opaque row), ``anchor_x`` from the body centre of the lower part of the
   pose (same rule as ``tools/dc_extract/bake_player_forms.py``);
7. pads to an 8x8 tile grid, bottom-centred, and reports the OAM footprint;
8. writes the PNG plus a JSON sidecar that can be pasted into
   ``species_anim.json`` / ``player_forms.json``, and exits non-zero when a
   hard constraint (colours, size, transparency, fragmentation) is violated.

Pure Pillow, no numpy: it runs on the Pi as well as on the GPU box.

Usage:
  python3 tools/gen/pixelize.py out/gen_raw/imp_01.png --height 48 \\
      --out assets/generated/spr_imp_idle_0.png
  python3 tools/gen/pixelize.py in.png --height 32 --colors 15 --palette \\
      120808,381010,703030,f0d0b0 --tile-pad
  python3 tools/gen/pixelize.py in.png --height 64 --dither --json entry.json
"""

from __future__ import annotations

import argparse
import colorsys
import json
import sys
from collections import Counter, deque
from pathlib import Path

from typing import cast

from PIL import Image

MAX_OAM = 64          # SNES object sizes are 8/16/32/64 on a side
MAX_COLORS = 15       # 4bpp = 16 entries, index 0 is transparency
BINARY_ALPHA = 128


# ---------------------------------------------------------------- background

def border_colour(im: Image.Image) -> tuple[int, int, int]:
    px = im.load()
    w, h = im.size
    counts: Counter = Counter()
    for x in range(w):
        counts[px[x, 0][:3]] += 1
        counts[px[x, h - 1][:3]] += 1
    for y in range(h):
        counts[px[0, y][:3]] += 1
        counts[px[w - 1, y][:3]] += 1
    return counts.most_common(1)[0][0]


def has_alpha(im: Image.Image) -> bool:
    if im.mode not in ("RGBA", "LA", "PA"):
        return False
    alpha = im.getchannel("A")
    lo, _hi = alpha.getextrema()
    return lo < 250


def key_background(im: Image.Image, key: str, tol: int) -> Image.Image:
    """Return RGBA with the background replaced by alpha 0."""
    im = im.convert("RGBA")
    if key == "alpha":
        if not has_alpha(im):
            print("pixelize: --bg alpha requested but the input is opaque; "
                  "falling back to border key", file=sys.stderr)
            key = "auto"
        else:
            return im
    if key == "auto":
        bg = border_colour(im)
    else:
        bg = parse_hex(key)
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) <= tol:
                px[x, y] = (0, 0, 0, 0)
    return im


def parse_hex(text: str) -> tuple[int, int, int]:
    text = text.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


# ------------------------------------------------------------------ palette

def bgr555(colour: tuple[int, int, int]) -> tuple[int, int, int]:
    """Snap a colour to the SNES 15-bit space (5 bits per channel)."""
    out = []
    for value in colour:
        five = min(31, round(value / 8))
        out.append(five * 8 + (0 if five < 31 else 7))
    return (out[0], out[1], out[2])


def median_cut(colours: Counter, n: int) -> list[tuple[int, int, int]]:
    """Weighted median cut over an RGB histogram."""
    boxes: list[list[tuple[tuple[int, int, int], int]]] = [
        list(colours.items())
    ]

    def score(box) -> tuple[int, int]:
        lo = [min(c[i] for c, _ in box) for i in range(3)]
        hi = [max(c[i] for c, _ in box) for i in range(3)]
        spans = [hi[i] - lo[i] for i in range(3)]
        channel = spans.index(max(spans))
        return (max(spans), channel)

    while len(boxes) < n:
        boxes.sort(key=lambda b: (-score(b)[0], -len(b)))
        box = boxes[0]
        span, channel = score(box)
        if span == 0 or len(box) < 2:
            break
        box.sort(key=lambda item: item[0][channel])
        total = sum(count for _, count in box)
        run = 0
        split = 1
        for index, (_c, count) in enumerate(box):
            run += count
            if run >= total / 2:
                split = min(max(index, 1), len(box) - 1)
                break
        boxes[0:1] = [box[:split], box[split:]]

    palette = []
    for box in boxes:
        total = sum(count for _, count in box) or 1
        mix = [0.0, 0.0, 0.0]
        for (r, g, b), count in box:
            mix[0] += r * count
            mix[1] += g * count
            mix[2] += b * count
        palette.append(bgr555((round(mix[0] / total), round(mix[1] / total),
                               round(mix[2] / total))))
    seen = []
    for colour in palette:
        if colour not in seen:
            seen.append(colour)
    return seen


def map_to_palette(im: Image.Image, palette) -> tuple[Image.Image, Counter]:
    px = im.load()
    cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    used: Counter = Counter()
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dst = out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a < BINARY_ALPHA:
                continue
            rgb = (r, g, b)
            hit = cache.get(rgb)
            if hit is None:
                best = None
                best_d = 1 << 30
                for colour in palette:
                    d = ((r - colour[0]) ** 2 * 3 + (g - colour[1]) ** 2 * 4 +
                         (b - colour[2]) ** 2 * 2)
                    if d < best_d:
                        best_d = d
                        best = colour
                hit = best
                cache[rgb] = hit
            if hit is None:            # pragma: no cover - empty palette
                continue
            dst[x, y] = (hit[0], hit[1], hit[2], 255)
            used[hit] += 1
    return out, used


def dither_ordered(im: Image.Image, palette, strength: int = 24) -> Image.Image:
    """4x4 ordered dither against a fixed palette, applied before mapping."""
    matrix = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    px = im.load()
    out = im.copy()
    dst = out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a < BINARY_ALPHA:
                continue
            bias = (matrix[y % 4][x % 4] / 16.0 - 0.5) * strength
            dst[x, y] = (clamp(r + bias), clamp(g + bias), clamp(b + bias), a)
    return out


def clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def recolour(im: Image.Image, hue_shift: float, sat_scale: float) -> Image.Image:
    """Palette variant of a finished sprite (cheap dataset augmentation)."""
    out = im.copy()
    px = out.load()
    cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a < BINARY_ALPHA:
                continue
            key = (r, g, b)
            hit = cache.get(key)
            if hit is None:
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                h = (h + hue_shift) % 1.0
                s = max(0.0, min(1.0, s * sat_scale))
                nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
                hit = (round(nr * 255), round(ng * 255), round(nb * 255))
                cache[key] = hit
            px[x, y] = (hit[0], hit[1], hit[2], a)
    return out


# -------------------------------------------------------- structure, anchors

def components(im: Image.Image, min_px: int) -> tuple[Image.Image, list[int]]:
    """Drop alpha components smaller than ``min_px``; report kept sizes."""
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    drop = []
    keep = []
    for y0 in range(h):
        for x0 in range(w):
            i = y0 * w + x0
            if seen[i]:
                continue
            seen[i] = 1
            if px[x0, y0][3] < BINARY_ALPHA:
                continue
            queue = deque([(x0, y0)])
            cells = []
            while queue:
                x, y = queue.pop()
                cells.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        if not seen[j]:
                            seen[j] = 1
                            if px[nx, ny][3] >= BINARY_ALPHA:
                                queue.append((nx, ny))
            if len(cells) < min_px:
                drop.extend(cells)
            else:
                keep.append(len(cells))
    if drop:
        for x, y in drop:
            px[x, y] = (0, 0, 0, 0)
    return im, sorted(keep, reverse=True)


def foot_anchor_x(im: Image.Image) -> int:
    px = im.load()
    w, h = im.size
    start = max(0, int(h * 0.55))
    total = 0
    weighted = 0
    for y in range(start, h):
        for x in range(w):
            if px[x, y][3]:
                total += 1
                weighted += x
    return max(0, min(w, round(weighted / total))) if total else w // 2


def pad_tiles(im: Image.Image) -> tuple[Image.Image, int, int]:
    """Pad to an 8x8 grid, sprite bottom-centred (the engine's anchor rule)."""
    w, h = im.size
    tw = max(8, ((w + 7) // 8) * 8)
    th = max(8, ((h + 7) // 8) * 8)
    if (tw, th) == (w, h):
        return im, w // 8, h // 8
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas.paste(im, ((tw - w) // 2, th - h))
    return canvas, tw // 8, th // 8


# ---------------------------------------------------------------------- main

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--height", type=int, default=48,
                    help="target sprite height in pixels (SNES poses are "
                         "typically 24-64)")
    ap.add_argument("--colors", type=int, default=MAX_COLORS,
                    help="palette size, index 0 is transparency (default 15)")
    ap.add_argument("--filter", default="box",
                    choices=("box", "nearest", "lanczos", "bilinear"))
    ap.add_argument("--bg", default="auto",
                    help="'auto' (border colour), 'alpha', or #RRGGBB")
    ap.add_argument("--tol", type=int, default=30,
                    help="background key tolerance, sum of |dr|+|dg|+|db|")
    ap.add_argument("--palette", default=None,
                    help="fixed palette: hex list (120808,381010,...) or a PNG "
                         "to read colours from")
    ap.add_argument("--min-component", type=int, default=4,
                    help="alpha components smaller than this are dropped")
    ap.add_argument("--dither", action="store_true",
                    help="4x4 ordered dither before palette mapping")
    ap.add_argument("--tile-pad", action="store_true",
                    help="pad to an 8x8 tile grid, bottom-centred")
    ap.add_argument("--mirror", action="store_true",
                    help="also emit the faced-right mirror as _flip.png")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path, default=None,
                    help="where to write the metadata entry (default: next to "
                         "the PNG with .json)")
    ap.add_argument("--clip", default="idle",
                    help="clip tag for the metadata entry (idle/walk/.../die)")
    ap.add_argument("--duration", type=int, default=8,
                    help="frame duration for the metadata entry")
    ap.add_argument("--species", default=None,
                    help="species key for a species_anim.json entry, e.g. 0x2c")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args()


def load_palette(spec: str) -> list[tuple[int, int, int]]:
    path = Path(spec)
    if path.suffix.lower() in (".png", ".gif", ".bmp") and path.exists():
        im = Image.open(path).convert("RGBA")
        colours = []
        for _count, colour in cast(list, im.getcolors(maxcolors=1 << 22) or []):
            rgb = colour[:3]
            if colour[3] >= BINARY_ALPHA and rgb not in colours:
                colours.append(rgb)
        return [bgr555(c) for c in colours]
    return [bgr555(parse_hex(part)) for part in spec.split(",") if part.strip()]


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        print(f"pixelize: no such file: {args.input}", file=sys.stderr)
        return 2

    source = Image.open(args.input)
    source.load()
    im = key_background(source, args.bg, args.tol)
    bbox = im.getbbox()
    if bbox is None:
        print("pixelize: the whole image keyed to transparent "
              "(background colour wrong or sprite missing)", file=sys.stderr)
        return 1
    im = im.crop(bbox)

    # --- resize to the target height
    scale = args.height / im.height
    width = max(1, round(im.width * scale))
    resample = {"box": Image.BOX, "nearest": Image.NEAREST,
                "lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR}[args.filter]
    im = im.resize((width, args.height), resample)

    # --- palette
    if args.palette:
        palette = load_palette(args.palette)
    else:
        hist: Counter = Counter()
        for count, colour in cast(list, im.getcolors(maxcolors=1 << 22) or []):
            if colour[3] >= BINARY_ALPHA:
                hist[colour[:3]] += count
        palette = median_cut(hist, max(1, min(args.colors, MAX_COLORS)))
    if args.dither:
        im = dither_ordered(im, palette)
    im, used = map_to_palette(im, palette)

    # --- structure
    im, component_sizes = components(im, args.min_component)
    bbox = im.getbbox()
    if bbox is None:
        print("pixelize: nothing left after despeckling", file=sys.stderr)
        return 1
    im = im.crop(bbox)

    anchor_x = foot_anchor_x(im)
    anchor_y = im.height                      # feet = bottom opaque row
    tiles_x = tiles_y = 0
    if args.tile_pad:
        im, tiles_x, tiles_y = pad_tiles(im)

    # --- hard checks
    errors = []
    if im.width > MAX_OAM or im.height > MAX_OAM:
        errors.append(f"{im.width}x{im.height} exceeds the {MAX_OAM}px OAM limit")
    if len(used) > args.colors:
        errors.append(f"{len(used)} colours used, limit {args.colors}")
    histogram = im.getchannel("A").histogram()
    alpha_levels = {value for value, count in enumerate(histogram) if count}
    if not alpha_levels <= {0, 255}:
        errors.append("alpha is not binary")
    if len(component_sizes) > 6:
        errors.append(f"{len(component_sizes)} separate blobs (fragmented sprite)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    im.save(args.out)
    if args.mirror:
        flip = args.out.with_name(args.out.stem + "_flip" + args.out.suffix)
        im.transpose(Image.FLIP_LEFT_RIGHT).save(flip)

    entry = {
        "texture": args.out.name,
        "clip": args.clip,
        "duration": args.duration,
        "anchor_x": anchor_x,
        "anchor_y": anchor_y,
        "width": im.width,
        "height": im.height,
        "colors": len(used),
        "palette": ["#%02x%02x%02x" % c for c in sorted(used, key=lambda c: -(used[c]))],
        "components": component_sizes[:8],
        "tiles": [tiles_x or (im.width + 7) // 8, tiles_y or (im.height + 7) // 8],
        "source": str(args.input),
        "errors": errors,
    }
    if args.species:
        entry["species"] = args.species
    json_path = args.json or args.out.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(entry, indent=2) + "\n")

    if not args.quiet:
        print(f"{args.out}: {im.width}x{im.height} tile {entry['tiles'][0]}x"
              f"{entry['tiles'][1]} colors={len(used)} anchor=({anchor_x},"
              f"{anchor_y}) blobs={len(component_sizes)} "
              f"{'OK' if not errors else 'FAIL: ' + '; '.join(errors)}")
    if errors:
        for err in errors:
            print(f"pixelize: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
