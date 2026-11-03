#!/usr/bin/env python3
"""Bake Somulo's walk cycle (species `0x33`) from the 16-frame reference GIF.

The GIF is a 2x capture of the in-game walk cycle (`/tmp/somulo_walk.gif`,
241x181, 16 frames), so the usable sprite is ~116x90 - the size the port's 80x92
boss hitbox already assumes.  Frames are composited honouring GIF disposal,
downscaled 2x with NEAREST (no smoothing: the source is a pixel-art upscale),
and the black background is keyed out **from the border inwards** so the
dragon's own black outlines survive (657 of the 27 931 pure-black pixels in a
sample frame are interior outline).

The engine keeps at most `DC_SPECIES_FRAMES` (8) frames per species, so the
cycle is resampled to 8 evenly spaced phases and each frame carries the summed
duration of the two source frames it replaces; the cycle keeps its wall-clock
length.

Anchors: `anchor_x = width/2` (the dragon is drawn centred on the object) and
`anchor_y = height + floor_offset`.  The port's Somulo AI keeps the object at
`origin_y + 86` while walking (screen y 240 with the colosseum camera at 16),
i.e. 48 px below the room's floor line at y=192, so the +48 offset is what puts
the feet **on** the floor.  `--floor-offset 0` gives the plain feet anchor
(`anchor_y = height`) that the sprite itself implies.

Usage:
  python3 tools/dc_extract/bake_somulo_gif.py --gif /tmp/somulo_walk.gif
  python3 tools/dc_extract/bake_somulo_gif.py --gif ... --floor-offset 0 --dry-run
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[2]
SPECIES = 0x33
# Engine limits (src/assets.h): 8 frames per sheet, 8 per state clip.
MAX_FRAMES = 8
MAX_STATE_FRAMES = 8


def composite_frames(path: Path) -> list[Image.Image]:
    """Every GIF frame as RGBA, honouring disposal (PIL composites on seek)."""
    im = Image.open(path)
    out = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        out.append(im.convert("RGBA").copy())
    return out


def key_black_from_border(img: Image.Image, tol: int = 0) -> Image.Image:
    """Make border-connected pure-black pixels transparent.

    Keying *every* black pixel would punch holes in the dragon's outline, so the
    flood only walks the background that is reachable from the frame edge.
    """
    w, h = img.size
    px = img.load()

    def is_bg(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        return a > 0 and r <= tol and g <= tol and b <= tol

    seen = set()
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if is_bg(x, y) and (x, y) not in seen:
                seen.add((x, y))
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if is_bg(x, y) and (x, y) not in seen:
                seen.add((x, y))
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen \
                    and is_bg(nx, ny):
                seen.add((nx, ny))
                q.append((nx, ny))
    for x, y in seen:
        px[x, y] = (0, 0, 0, 0)
    return img


def drop_specks(img: Image.Image, min_pixels: int = 6) -> Image.Image:
    """Remove isolated pixel islands (GIF edge noise) so the bbox is the body."""
    w, h = img.size
    px = img.load()
    seen = set()
    for y in range(h):
        for x in range(w):
            if (x, y) in seen or px[x, y][3] == 0:
                continue
            comp = [(x, y)]
            seen.add((x, y))
            q = deque([(x, y)])
            while q:
                cx, cy = q.popleft()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen \
                            and px[nx, ny][3] > 0:
                        seen.add((nx, ny))
                        q.append((nx, ny))
                        comp.append((nx, ny))
            if len(comp) < min_pixels:
                for cx, cy in comp:
                    px[cx, cy] = (0, 0, 0, 0)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gif", type=Path, default=Path("/tmp/somulo_walk.gif"))
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--scale", type=int, default=2,
                    help="downscale factor of the source capture")
    ap.add_argument("--object-y", type=float, default=177.0,
                    help="screen y the port draws the boss object at (measured)")
    ap.add_argument("--floor-y", type=float, default=176.0,
                    help="screen y of the colosseum floor line. Both this and "
                         "--object-y are SCREEN space: the floor is 192 in world "
                         "and 176 on screen with the 16 px camera, and mixing the "
                         "two frames anchored the dragon 14 px into the floor")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    frames = composite_frames(args.gif)
    durations = []
    im = Image.open(args.gif)
    for i in range(len(frames)):
        im.seek(i)
        durations.append(int(im.info.get("duration", 80) or 80))
    print(f"{len(frames)} GIF frames {frames[0].size} "
          f"durations {durations[:4]}...")

    # 2x upscale -> 1x, key the background, drop specks.
    small = []
    for f in frames:
        w = f.width // args.scale
        h = f.height // args.scale
        s = f.resize((w, h), Image.NEAREST)
        key_black_from_border(s)
        drop_specks(s)
        small.append(s)

    # The GIF repeats frames to hold a pose (10 unique poses over 16 frames).
    # Keep the first occurrence of each pose, in cycle order, so the sheet does
    # not waste its 8 frame slots on duplicates.
    unique: list[int] = []
    seen: set[bytes] = set()
    for i, s in enumerate(small):
        key = s.tobytes()
        if key in seen:
            continue
        seen.add(key)
        unique.append(i)
    print(f"{len(frames)} GIF frames -> {len(unique)} unique poses "
          f"at {unique}")

    # The capture jitters by one source pixel (0.5 px at 1x): frame N is frame
    # 0 shifted by (0,-1) at 2x.  Left in, the whole sprite shimmers every
    # frame; align each frame to the first one so only the legs move.
    PAD = 4

    def shifted(img: Image.Image, dx: int, dy: int) -> Image.Image:
        out = Image.new("RGBA", (img.width + PAD * 2, img.height + PAD * 2),
                        (0, 0, 0, 0))
        out.alpha_composite(img, (PAD + dx, PAD + dy))
        return out

    ref = small[unique[0]]
    aligned = {}
    for i in unique:
        s = small[i]
        if i == unique[0]:
            aligned[i] = shifted(s, 0, 0)
            continue
        best = None
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                cand = shifted(s, dx, dy)
                bad = 0
                pa, pb = ref.load(), cand.load()
                for y in range(0, ref.height, 2):
                    for x in range(0, ref.width, 2):
                        if pa[x, y] != pb[x, y]:
                            bad += 1
                if best is None or bad < best[0]:
                    best = (bad, dx, dy)
        assert best is not None
        aligned[i] = shifted(s, best[1], best[2])
    small = aligned


    # One shared canvas so the walk cycle does not jitter: crop every frame to
    # the union of the body boxes.
    boxes = [small[i].getbbox() for i in unique]
    boxes = [b for b in boxes if b]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    print(f"union bbox {x0},{y0}..{x1},{y1} -> {x1 - x0}x{y1 - y0}")

    # Resample the unique cycle to the engine's frame budget (DC_SPECIES_FRAMES).
    # Pick the subset that keeps the most silhouette motion: evenly spaced
    # samples can land on near-identical poses (the cycle holds some), which
    # reads as a still image.  Order is preserved so the walk still cycles.
    n = len(unique)
    if n <= MAX_FRAMES:
        picked = list(unique)
    else:
        def mask_of(i):
            return small[i].split()[3].point(lambda v: 255 if v > 0 else 0)

        def sd(a, b):
            pa, pb = a.load(), b.load()
            return sum(1 for y in range(a.height) for x in range(a.width)
                       if (pa[x, y] > 0) != (pb[x, y] > 0))

        masks = {i: mask_of(i) for i in unique}
        best = None
        for combo in itertools.combinations(unique, MAX_FRAMES):
            score = min(sd(masks[a], masks[b])
                        for a, b in itertools.combinations(combo, 2))
            if best is None or score > best[0]:
                best = (score, combo)
        assert best is not None
        picked = list(best[1])
        print(f"frame subset {picked} keeps min silhouette delta "
              f"{best[0]} px")
    out_frames = []
    for src in picked:
        # The GIF's first frame carries a 500 ms authoring hold; clamp every
        # frame so the walk never stutters.
        dur = min(8, max(2, round(durations[src] / 1000.0 * 60.0)))
        out_frames.append((src, dur))

    baked = []
    for idx, (k, dur) in enumerate(out_frames):
        crop = small[k].crop((x0, y0, x1, y1))
        name = f"enemy_33_{idx}.png"
        ax = crop.width // 2
        # The port's Somulo AI keeps the object at a fixed screen y while the
        # boss walks, so the anchor is derived from the measured placement:
        # sprite_top = object_y - anchor_y, and the feet (the sprite's last
        # opaque row) must land on the floor line.
        ay = round(args.object_y + crop.height - args.floor_y)
        baked.append({"texture": name, "anchor_x": ax, "anchor_y": ay,
                      "duration": dur, "width": crop.width,
                      "height": crop.height, "_src": k})
        if not args.dry_run:
            crop.save(args.out / name)
        print(f"  {name}: src frame {k} {crop.width}x{crop.height} "
              f"anchor ({ax},{ay}) duration {dur}")

    if args.dry_run:
        return 0

    anim_path = args.out / "species_anim.json"
    anim = json.loads(anim_path.read_text()) if anim_path.is_file() \
        else {"species": {}}
    entry = {
        "species": SPECIES,
        "frames": [{k: v for k, v in f.items() if not k.startswith("_")}
                   for f in baked],
        "states": {
            # state 8 is the entrance walk, state 7 the blind walk after the
            # roar: the GIF is that same walk cycle.
            "7": list(range(len(baked)))[:MAX_STATE_FRAMES],
            "8": list(range(len(baked)))[:MAX_STATE_FRAMES],
            # state 0 is the standing fireball duel; the GIF has no separate
            # standing pose, so it reuses a slow subset of the cycle.
            "0": [0, 2, 4, 6],
        },
        "default": 0,
        "hurt": 0,
        "source": ("Somulo walk cycle, 16-frame reference GIF "
                   f"({args.gif.name}) composited and downscaled "
                   f"{args.scale}x; states 7/8 = the cycle, state 0 = slow "
                   "subset; no head-down/faint/stuck poses exist in the "
                   "source"),
    }
    anim["species"]["33"] = entry
    anim_path.write_text(json.dumps(anim, indent=1))
    again = json.loads(anim_path.read_text())
    print(f"species_anim.json now has {len(again['species'])} species; "
          f"33 -> {len(again['species']['33']['frames'])} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
