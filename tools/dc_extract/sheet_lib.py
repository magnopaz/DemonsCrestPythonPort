#!/usr/bin/env python3
"""Shared helpers for slicing the labelled community sprite sheets.

The sheets in ``docs/sprites`` are single static GIFs (one drawing per file
frame) laid out as horizontal rows of poses with a small bitmap caption above
each group.  This module does the mechanical part of the extraction:

* find the flat sheet background and every foreground component;
* find the caption glyphs (small isolated components) and group them into
  words, so a row's poses can be split by the caption they belong to;
* split a row into individual poses on background columns;
* key the background, delete caption pixels/specks, crop, and compute the
  body anchor (largest component's bottom centre);
* write a contact sheet for review.

It deliberately does no scaling, antialiasing or palette work: the port draws
these PNGs at 1:1.  Sheet-specific decisions (which rows belong to which
state, which drawings are effects rather than the body) live in
``sheet_specs.py`` and the per-sheet bake tools.

Usage as a library::

    from sheet_lib import analyse, extract_pose, save_frames

    info = analyse("docs/sprites/... Arma.gif")
    for band in info.bands:
        print(band.y0, band.y1, [p.box for p in band.poses])
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SHEET_DIR = ROOT / "docs" / "sprites"

BG_TOLERANCE = 30
# A caption glyph is small and isolated; the biggest letter is 8 px tall and
# the widest is a merged pair, still under 16 px.
TEXT_MAX_HEIGHT = 9
TEXT_MAX_WIDTH = 16
TEXT_MAX_AREA = 90
# Two drawings in a row are separated by more than this many empty columns.
POSE_GAP = 2


def sheet_path(name: str) -> Path:
    """Resolve a sheet by exact filename or by a unique fragment."""
    direct = SHEET_DIR / name
    if direct.is_file():
        return direct
    sheets = list(SHEET_DIR.glob("*.gif")) + list(SHEET_DIR.glob("*.png"))
    # Exact stem first ("Arma" must not win "Ultimate Arma"): the sheet names
    # are "SNES - Demon's Crest - <category> - <name>", so compare the tail.
    exact = [p for p in sheets
             if p.stem.split(" - ")[-1].lower() == name.lower()]
    if len(exact) == 1:
        return exact[0]
    hits = [p for p in sheets if name.lower() in p.name.lower()]
    if len(hits) == 1:
        return hits[0]
    raise FileNotFoundError(f"sheet {name!r} matched {len(hits)} files")


def background_colour(im: Image.Image) -> tuple[int, int, int]:
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    return Counter(small.getdata()).most_common(1)[0][0]


def is_bg(pixel, bg, tolerance: int = BG_TOLERANCE) -> bool:
    return abs(pixel[0] - bg[0]) + abs(pixel[1] - bg[1]) + \
        abs(pixel[2] - bg[2]) <= tolerance


@dataclass
class Component:
    area: int
    x0: int
    y0: int
    x1: int
    y1: int
    pixels: list[tuple[int, int]] = field(default_factory=list)
    colour: tuple[int, int, int] = (0, 0, 0)

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1 + 1, self.y1 + 1)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1 + 1) / 2


def components(im: Image.Image, bg) -> list[Component]:
    """Every 8-connected foreground blob on the sheet."""
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    out: list[Component] = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or is_bg(px[x, y], bg):
                continue
            queue = deque([(x, y)])
            seen[i] = 1
            pixels: list[tuple[int, int]] = []
            minx = maxx = x
            miny = maxy = y
            while queue:
                cx, cy = queue.popleft()
                pixels.append((cx, cy))
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and not is_bg(px[nx, ny], bg):
                                seen[j] = 1
                                queue.append((nx, ny))
            colours = Counter(px[x, y] for x, y in pixels)
            out.append(Component(len(pixels), minx, miny, maxx, maxy, pixels,
                                 colours.most_common(1)[0][0]))
    return out


def is_caption_glyph(c: Component) -> bool:
    return (c.height <= TEXT_MAX_HEIGHT and c.width <= TEXT_MAX_WIDTH
            and c.area <= TEXT_MAX_AREA)


@dataclass
class Caption:
    """One word of sheet caption text (a run of glyph components)."""
    x0: int
    y0: int
    x1: int
    y1: int
    glyphs: list[Component]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1 + 1) / 2

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1 + 1, self.y1 + 1)

    def art(self, im: Image.Image, bg) -> str:
        """ASCII art of the word, so a human can read it without OCR."""
        px = im.load()
        rows = []
        for y in range(self.y0, self.y1 + 1):
            rows.append("".join(
                "#" if not is_bg(px[x, y], bg) else "."
                for x in range(self.x0, self.x1 + 1)))
        return "\n".join(rows)


def text_colour(comps: list[Component]) -> tuple[int, int, int] | None:
    """The sheet's caption colour: the colour of most glyph-sized blobs.

    Every sheet draws its captions in one flat colour that is not used by the
    drawings, so the majority colour among the small isolated components is
    the text colour.  Returns None when no colour dominates.
    """
    small = [c for c in comps if is_caption_glyph(c)]
    if not small:
        return None
    counts = Counter(c.colour for c in small)
    colour, n = counts.most_common(1)[0]
    return colour if n >= max(4, len(small) * 0.4) else None


def captions(comps: list[Component],
             colour: tuple[int, int, int] | None = None) -> list[Caption]:
    """Group caption glyphs into words by line and horizontal proximity."""
    glyphs = [c for c in comps if is_caption_glyph(c)]
    if colour is not None:
        glyphs = [c for c in glyphs if is_bg(c.colour, colour, 8)]
    glyphs.sort(key=lambda c: (c.y0, c.x0))
    lines: list[list[Component]] = []
    for g in glyphs:
        for line in lines:
            if g.y0 <= max(c.y1 for c in line) + 2 and \
                    g.y1 >= min(c.y0 for c in line) - 2:
                line.append(g)
                break
        else:
            lines.append([g])
    words: list[Caption] = []
    for line in lines:
        line.sort(key=lambda c: c.x0)
        run = [line[0]]
        for g in line[1:]:
            # The caption font is variable width with a 1-2 px letter gap;
            # a real word gap is much wider.
            if g.x0 - max(c.x1 for c in run) <= 4:
                run.append(g)
            else:
                words.append(_caption_from(run))
                run = [g]
        words.append(_caption_from(run))
    # A single isolated glyph is usually sprite debris, not a caption.
    return [w for w in words if len(w.glyphs) >= 2]


def _caption_from(run: list[Component]) -> Caption:
    return Caption(min(c.x0 for c in run), min(c.y0 for c in run),
                   max(c.x1 for c in run), max(c.y1 for c in run), run)


@dataclass
class Pose:
    """One drawing: a run of non-background columns inside a band."""
    x0: int
    x1: int
    y0: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1 + 1) / 2

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1 + 1, self.y1 + 1)


@dataclass
class Band:
    """A horizontal row of drawings, optionally labelled by captions above."""
    y0: int
    y1: int
    poses: list[Pose]
    labels: list[Caption]
    groups: list[list[Pose]] = field(default_factory=list)

    def label_for(self, pose: Pose) -> Caption | None:
        if not self.labels:
            return None
        return min(self.labels, key=lambda c: abs(c.cx - pose.cx))


@dataclass
class SheetInfo:
    path: Path
    size: tuple[int, int]
    bg: tuple[int, int, int]
    components: list[Component]
    captions: list[Caption]
    bands: list[Band]
    image: Image.Image
    caption_pixels: set[tuple[int, int]] = field(default_factory=set)


def _column_runs(im: Image.Image, bg, y0: int, y1: int,
                 x0: int = 0, x1: int | None = None) -> list[tuple[int, int]]:
    """Columns inside the band that contain ink, merged across tiny gaps."""
    px = im.load()
    x1 = im.width - 1 if x1 is None else x1
    runs: list[list[int]] = []
    start = None
    for x in range(x0, x1 + 1):
        hit = any(not is_bg(px[x, y], bg) for y in range(y0, y1 + 1))
        if hit and start is None:
            start = x
        elif not hit and start is not None:
            runs.append([start, x - 1])
            start = None
    if start is not None:
        runs.append([start, x1])
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] - 1 <= POSE_GAP:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(a, b) for a, b in merged]


def analyse(name: str | Path, *, caption_boxes=None) -> SheetInfo:
    path = sheet_path(str(name)) if not Path(name).is_file() else Path(name)
    im = Image.open(path).convert("RGB")
    bg = background_colour(im)
    comps = components(im, bg)
    ink = text_colour(comps)
    words = captions(comps, ink)
    if caption_boxes:
        keep = [(x0, y0, x1, y1) for x0, y0, x1, y1 in caption_boxes]
        words = [w for w in words
                 if any(w.x0 >= x0 and w.y0 >= y0 and w.x1 <= x1 and
                        w.y1 <= y1 for x0, y0, x1, y1 in keep)]
    glyph_boxes = {(g.x0, g.y0) for w in words for g in w.glyphs}
    poses_comps = [c for c in comps
                   if (c.x0, c.y0) not in glyph_boxes
                   and not any(_inside(c, w) for w in words)]
    # Rows: components whose vertical extents overlap or nearly touch.
    poses_comps.sort(key=lambda c: (c.y0, c.x0))
    rows: list[list[Component]] = []
    for c in poses_comps:
        for row in rows:
            if c.y0 <= max(k.y1 for k in row) + 5:
                row.append(c)
                break
        else:
            rows.append([c])
    bands: list[Band] = []
    for row in rows:
        y0 = min(c.y0 for c in row)
        y1 = max(c.y1 for c in row)
        row_init = _column_runs(im, bg, y0, y1)
        poses = []
        for x0, x1 in row_init:
            ys = [y for y in range(y0, y1 + 1)
                  if any(not is_bg(im.getpixel((x, y)), bg)
                         for x in range(x0, x1 + 1))]
            if not ys:
                continue
            poses.append(Pose(x0, x1, min(ys), max(ys)))
        if not poses:
            continue
        labels = [w for w in words if 0 < y0 - w.y1 <= 26]
        bands.append(Band(y0, y1, poses, labels))
    caption_pixels = {(x, y) for w in words for g in w.glyphs
                      for x, y in g.pixels}
    return SheetInfo(path, im.size, bg, comps, words, bands, im,
                     caption_pixels)


def _inside(c: Component, w: Caption) -> bool:
    return (c.x0 >= w.x0 and c.x1 <= w.x1 and c.y0 >= w.y0 and c.y1 <= w.y1)


def key_crop(im: Image.Image, box, bg) -> Image.Image:
    """Crop ``box`` and clear the sheet backdrop, flooding from the border.

    Flooding inwards only removes background that is actually connected to the
    crop edge, so dark interior pixels (eye sockets, ribcages, shadows) stay
    opaque even when they are close to the backdrop colour.
    """
    crop = im.crop(box).convert("RGBA")
    px = crop.load()
    w, h = crop.size
    seen = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not seen[y * w + x] and is_bg(px[x, y], bg):
                seen[y * w + x] = 1
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and is_bg(px[x, y], bg):
                seen[y * w + x] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if not seen[j] and is_bg(px[nx, ny], bg):
                    seen[j] = 1
                    queue.append((nx, ny))
    return crop


def remove_small_components(img: Image.Image, min_area: int = 24,
                            max_text_height: int = 11) -> Image.Image:
    """Drop detached caption letters and sparkles, keeping the main pose."""
    px = img.load()
    w, h = img.size
    seen = bytearray(w * h)
    keep = bytearray(w * h)
    groups: list[tuple[list[int], int, int, int, int]] = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y][3] == 0:
                continue
            queue = deque([(x, y)])
            seen[i] = 1
            cells = []
            minx = maxx = x
            miny = maxy = y
            while queue:
                cx, cy = queue.popleft()
                cells.append(cy * w + cx)
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny][3] != 0:
                                seen[j] = 1
                                queue.append((nx, ny))
            groups.append((cells, minx, miny, maxx, maxy))
    if not groups:
        return img
    largest = max(len(g[0]) for g in groups)
    for cells, _minx, miny, _maxx, maxy in groups:
        area = len(cells)
        height = maxy - miny + 1
        if area < min_area and height <= max_text_height and \
                area < largest * 0.02:
            continue
        for i in cells:
            keep[i] = 1
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            if keep[y * w + x]:
                dst[x, y] = px[x, y]
    return out


def largest_component_anchor(img: Image.Image) -> tuple[int, int]:
    """Anchor on the largest blob's bottom centre (the body, not a weapon)."""
    px = img.load()
    w, h = img.size
    seen = bytearray(w * h)
    best = None
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y][3] == 0:
                continue
            stack = [(x, y)]
            seen[i] = 1
            n = 0
            minx = maxx = x
            maxy = y
            while stack:
                cx, cy = stack.pop()
                n += 1
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                maxy = max(maxy, cy)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny][3] != 0:
                                seen[j] = 1
                                stack.append((nx, ny))
            if best is None or n > best[0]:
                best = (n, minx, maxx, maxy)
    if best is None:
        return img.width // 2, img.height
    _n, minx, maxx, maxy = best
    return (minx + maxx + 1) // 2, maxy + 1


def extract_pose(info: SheetInfo, box, *, min_width: int = 8,
                 min_height: int = 12) -> Image.Image | None:
    """Crop/clean one pose; returns None when nothing usable survives.

    Caption glyph pixels are cleared explicitly: a band that starts a few
    pixels too high then loses the letters instead of baking a label strip
    into the frame (``remove_small_components`` alone misses letters that
    touch their neighbour).
    """
    crop = key_crop(info.image, box, info.bg)
    if info.caption_pixels:
        px = crop.load()
        bx, by = box[0], box[1]
        for y in range(crop.height):
            for x in range(crop.width):
                if (x + bx, y + by) in info.caption_pixels:
                    px[x, y] = (0, 0, 0, 0)
    crop = remove_small_components(crop)
    bbox = crop.getbbox()
    if bbox is None:
        return None
    crop = crop.crop(bbox)
    if crop.width < min_width or crop.height < min_height:
        return None
    return crop


def contact_sheet(files: list[Path], out: Path, *, cols: int = 8,
                  scale: int = 1) -> Path:
    """Grid of frames with their file name, for visual review."""
    if not files:
        raise ValueError("contact sheet needs at least one frame")
    cards = []
    for path in files:
        im = Image.open(path).convert("RGBA")
        if scale != 1:
            im = im.resize((im.width * scale, im.height * scale),
                           Image.NEAREST)
        cards.append((path.name, im))
    cell_w = max(im.width for _n, im in cards) + 12
    cell_h = max(im.height for _n, im in cards) + 24
    rows = (len(cards) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h),
                      (32, 32, 40, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(cards):
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        draw.rectangle([cx + 1, cy + 1, cx + cell_w - 2, cy + cell_h - 2],
                       outline=(70, 70, 90, 255))
        sheet.alpha_composite(im, (cx + (cell_w - im.width) // 2,
                                   cy + 4 + (cell_h - 24 - im.height) // 2))
        draw.text((cx + 4, cy + cell_h - 16), name, fill=(220, 220, 230, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out)
    return out
