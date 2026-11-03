#!/usr/bin/env python3
"""Match a live oracle BG layer against the ROM's 32x32 screen table.

The guest builds BG1/BG2 from the same `$8F+set` superblock tables the extractor
uses, so a live 64x32 VRAM tilemap is a *window* onto one or more 32x32 ROM
screens.  The window is not always screen-aligned: while the camera scrolls the
guest rewrites columns, so a screen boundary can sit in the middle of the
window.  Matching is therefore done per tile row with a torus scan, which still
finds the room when the window is split.

`build_screen_rows` maps a 32-word row blob to every (row, set, screen) that
contains it; a 32x32 window then votes for a screen once per row that matches at
the right row index.  32/32 votes means the window is that screen, cell for
cell.

Two details matter for this ROM:

* the screen table has 256 entries (`$8F+set:$8000 + screen*128`), not 128 —
  most late-game rooms use screen ids above 127;
* the guest rewrites the priority (bit 13) and flip (bits 14/15) bits of the BG
  words when it loads a room, so words are compared with those bits masked.
  Tile number and palette are stable.

Blank/filler screens are excluded: they are shared by dozens of areas and would
otherwise win every tie.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))
from extract import Rom, tilemap_linear  # noqa: E402

ROM_PATH = Path("/home/moop/Projetos/opencode/roms/Demon's Crest (USA).sfc")
CELL = 32
SETS = 4
SCREENS = 256  # the screen table is 32 KiB / 128 B per screen
MIN_NONZERO = 32
WORD_MASK = 0x1FFF


def load_rom(path: Path = ROM_PATH) -> Rom:
    return Rom(path)


def build_screen_rows(rom: Rom) -> dict[bytes, dict[int, list[tuple[int, int]]]]:
    """row blob -> {row: [(set, screen)]} for every non-degenerate ROM screen."""
    index: dict[bytes, dict[int, list[tuple[int, int]]]] = {}
    for set_id in range(SETS):
        for scr in range(SCREENS):
            tm = rom.screen_tilemap(set_id, scr)
            flat = [w & WORD_MASK for row in tm for w in row]
            if sum(1 for w in flat if w) < MIN_NONZERO:
                continue
            for y, row in enumerate(tm):
                blob = b"".join((w & WORD_MASK).to_bytes(2, "little") for w in row)
                index.setdefault(blob, {}).setdefault(y, []).append((set_id, scr))
    return index


def build_screen_to_areas(rom: Rom) -> dict[tuple[int, int], list[tuple[int, tuple[int, int]]]]:
    """(set, screen) -> [(area, (grid_x, grid_y))] from $81:A291 / $81:A6D8."""
    out: dict[tuple[int, int], list[tuple[int, tuple[int, int]]]] = {}
    for area in range(113):
        info = rom.area_info(area)
        rows = [r for r in range(info["height"]) if any(s > 0 for s in info["grid"][r])]
        if not rows:
            continue
        first = rows[0]
        for ry in range(first, rows[-1] + 1):
            for cx, slot in enumerate(info["grid"][ry]):
                if slot <= 0 or slot > len(info["screens"]):
                    continue
                scr = info["screens"][slot - 1]
                out.setdefault((info["set"], scr), []).append((area, (cx, ry - first)))
    return out


def read_frame(frame_json: Path, vram_path: Path, layer: int):
    state = json.loads(frame_json.read_text())
    ppu = state["ppu"]
    raw = vram_path.read_bytes()
    vram = [int.from_bytes(raw[i * 2:i * 2 + 2], "little") for i in range(0x8000)]
    sc = ppu["bgXsc"][layer]
    sc = int(sc, 16) if isinstance(sc, str) else int(sc)
    w, h, tiles = tilemap_linear(vram, sc)
    return w, h, tiles, ppu


def screen_votes(w: int, h: int, tiles: list[int],
                 rows_index) -> dict[tuple[int, int], dict]:
    """Best row-vote score per ROM screen over every torus offset."""
    rows = [[b"".join((int(tiles[y * w + ((x + i) % w)]) & WORD_MASK).to_bytes(2, "little")
                      for i in range(CELL)) for x in range(w)]
            for y in range(h)]
    best: dict[tuple[int, int], dict] = {}
    for oy in range(h):
        for ox in range(w):
            votes: dict[tuple[int, int], int] = {}
            for y in range(CELL):
                by_row = rows_index.get(rows[(oy + y) % h][ox])
                if not by_row:
                    continue
                for set_id, scr in by_row.get(y, ()):
                    votes[(set_id, scr)] = votes.get((set_id, scr), 0) + 1
            for key, n in votes.items():
                cur = best.get(key)
                if cur is None or n > cur["votes"]:
                    best[key] = {"votes": n, "offset": (ox, oy)}
    return best


def identify_dir(probe_dir: Path, rom: Rom, rows_index, screen_areas,
                 layers=(0, 1), min_layer_score: float = 0.999) -> dict:
    """Rank areas for every frame in a probe directory.

    Returns {"ranked": [(score, area, detail)], "frames": [...]}.
    """
    frames = sorted(probe_dir.glob("f*.vram.bin"))
    per_area: dict[int, dict] = {}
    per_frame = []
    for vram_path in frames:
        frame = int(vram_path.name[1:7])
        frame_json = probe_dir / f"f{frame:06d}.json"
        if not frame_json.is_file():
            continue
        frame_best = 0.0
        seen = set()
        for layer in layers:
            try:
                w, h, tiles, ppu = read_frame(frame_json, vram_path, layer)
            except (KeyError, IndexError, ValueError):
                continue
            key = (layer, w, h, hash(bytes(
                b"".join((int(t) & WORD_MASK).to_bytes(2, "little") for t in tiles))))
            if key in seen:
                continue
            seen.add(key)
            votes = screen_votes(w, h, tiles, rows_index)
            if not votes:
                continue
            top = max(v["votes"] for v in votes.values()) / CELL
            frame_best = max(frame_best, top)
            for (set_id, scr), v in votes.items():
                score = v["votes"] / CELL
                for area, pos in screen_areas.get((set_id, scr), ()):
                    cur = per_area.get(area)
                    if cur is None or score > cur["score"]:
                        per_area[area] = {"score": score, "screen": (set_id, scr),
                                          "pos": pos, "layer": layer, "frame": frame,
                                          "offset": v["offset"]}
            if top >= min_layer_score:
                break  # BG1 already identifies the room; BG2 is the backdrop
        per_frame.append({"frame": frame, "best_score": round(frame_best, 3)})
    ranked = sorted(((v["score"], a, v) for a, v in per_area.items()),
                    key=lambda t: (-t[0], t[1]))
    return {"ranked": ranked, "frames": per_frame,
            "best": ranked[0] if ranked else None}


def main() -> int:
    rom = load_rom()
    rows_index = build_screen_rows(rom)
    screen_areas = build_screen_to_areas(rom)
    for name in sys.argv[1:]:
        d = ROOT / "captures" / "rooms" / name
        r = identify_dir(d, rom, rows_index, screen_areas)
        hint = None
        meta = d / "meta.json"
        if meta.is_file():
            hint = json.loads(meta.read_text()).get("area_hint")
        top = r["ranked"][:5]
        print(f"{name:40s} hint={hint} top="
              f"{[(a, round(s, 3), v['screen'], v['layer']) for s, a, v in top]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
