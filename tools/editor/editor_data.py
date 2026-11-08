#!/usr/bin/env python3
"""Data layer for the Demon's Crest visual editor suite.

The editor is deliberately dependency-free: this module only uses the standard
library and knows the on-disk formats the game already reads.

Layout
------
* ``assets/generated`` is the ROM-derived asset tree and stays as-is.
* ``assets/authored`` is the editable overlay:
  - ``rooms/room_area<N>.json``       room overrides / new rooms
  - ``species_anim.json``             species overrides (merged by the game)
  - ``enemies.json``                  stats / attack patterns / sounds
  - ``sprites/``                      images imported into the editor
  - ``backups/``                      last copy of every file we overwrite

The runtime looks in the authored overlay first, so saving from the editor is
immediately visible to ``python -m dcpy.main`` without copying anything over
the generated tree.
"""

from __future__ import annotations

import ast
import base64
import copy
import json
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Game constants (kept in sync with dcpy/consts.py and dcpy/assets.py)
# ---------------------------------------------------------------------------

MUSIC_NAMES = [
    "None", "Title", "Overworld", "Murkland", "Ruined City", "Dark Forest",
    "Dark Forest Cave", "Towers of Doom", "Poseidonia", "Poseidonia Depths",
    "Mountains", "Mountains Valley", "Phalanx", "Demon Hideout", "Town",
    "Boss", "Boss (common)", "Ending",
]
MUSIC_COUNT = len(MUSIC_NAMES)

SFX_NAMES = [
    "jump", "land", "shoot", "break", "pickup", "hurt", "enemy_hit",
]
SFX_FILES = {
    "jump": "sfx_jump.wav", "land": "sfx_land.wav", "shoot": "sfx_shoot.wav",
    "break": "sfx_break.wav", "pickup": "sfx_pickup.wav",
    "hurt": "sfx_hurt.wav", "enemy_hit": "sfx_enemy_hit.wav",
}
SFX_IDS = {name: i for i, name in enumerate(SFX_NAMES)}

LEVEL_OBJECT_TYPES = [
    "urn", "enemy", "platform", "pickup_crest", "boss", "exit", "npc",
    "talisman", "unknown", "decor", "inert",
]
LEVEL_OBJECT_LABELS = {
    "urn": "Urn (breakable)",
    "enemy": "Enemy",
    "platform": "Moving platform",
    "pickup_crest": "Crest item",
    "boss": "Boss",
    "exit": "Exit trigger",
    "npc": "NPC",
    "talisman": "Talisman",
    "unknown": "Unknown / scripted",
    "decor": "Decor",
    "inert": "Inert record",
}
LEVEL_OBJECT_CAPS = {
    "objects": 64, "transitions": 16, "spawns": 8, "sprites": 16,
}
BG_PALETTES = 8
TILE_SIZE = 8
COLLISION_CELL = 16
MAX_SPECIES_FRAMES = 64
MAX_SPECIES_STATES = 16
MAX_STATE_FRAMES = 8

PLAYER_FORM_COUNT = 6
PLAYER_MAX_STEPS = 64
PLAYER_FORM_NAMES = [
    "Normal", "Ground", "Aerial", "Tidal", "Legendary", "Ultimate",
]
PLAYER_CLIP_NAMES = [
    "idle", "walk", "jump", "hover", "fall", "land", "attack", "spell",
    "flying", "hurt", "death",
]

AI_KINDS = ["walker", "flyer", "charger", "turret", "stationary"]
ATTACK_TYPES = ["projectile", "spread", "burst", "lunge", "melee"]

# Names recovered in docs/TOOLING.md and docs/SPECIES_CENSUS.md.  The tool still
# works for every species id; this just makes the lists readable.
SPECIES_NAMES = {
    0x06: "Cave crawler", 0x07: "Bat / watcher", 0x08: "Forest ogre",
    0x09: "Hippogriff", 0x13: "Grewon", 0x16: "Ovununu eye",
    0x17: "Ovununu", 0x18: "Ovununu part", 0x23: "Murkland enemy",
    0x26: "Armored undead", 0x2C: "Skeleton walker", 0x2D: "Crest pickup",
    0x2E: "Crest pickup", 0x33: "Somulo", 0x34: "Boss fire",
    0x49: "Murkland critter", 0x57: "Murkland critter",
    0x58: "Flame Lord", 0x63: "Ogre", 0x65: "Ruined City enemy",
    0x67: "Ghoul", 0x68: "Belth", 0x69: "Pit core", 0x6B: "Pit body",
    0x6C: "Pit eye", 0x6F: "Holothurion", 0x72: "Flame spirit",
    0x79: "Ruined City enemy", 0x7B: "Scula", 0x7C: "Scula arm",
    0x82: "Crawler", 0x86: "Phalanx", 0x8D: "Ultimate Phalanx",
    0x96: "Town NPC", 0x97: "Town NPC", 0xA5: "Arma",
    0xBC: "Dark Demon",
}

# Filename -> human readable suffix for the map labels.
MAP_NAME_FIXES = {
    "phalanxs": "Phalanx's",
    "demons": "Demon's",
    "holothurion": "Holothurion",
    "ovnunu": "Ovununu",
    "grewon": "Grewon",
    "scula": "Scula",
}

REQUIRED_ROOM_KEYS = (
    "world", "camera", "spawn", "player", "collision", "play", "bg",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def issue(level: str, code: str, message: str, **extra) -> dict:
    out = {"level": level, "code": code, "message": message}
    out.update(extra)
    return out


def clamp_int(value, default: int, lo: int | None = None,
              hi: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    if lo is not None and out < lo:
        out = lo
    if hi is not None and out > hi:
        out = hi
    return out


def clamp_float(value, default: float, lo: float | None = None,
                hi: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    if not math.isfinite(out):
        out = default
    if lo is not None and out < lo:
        out = lo
    if hi is not None and out > hi:
        out = hi
    return out


def humanize_slug(slug: str) -> str:
    parts = []
    for word in str(slug).replace("_", "-").split("-"):
        if not word:
            continue
        low = word.lower()
        parts.append(MAP_NAME_FIXES.get(low, word[:1].upper() + word[1:]))
    return " ".join(parts)


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def png_is_valid(data: bytes) -> tuple[bool, int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return False, 0, 0
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        return False, 0, 0
    return True, width, height


def safe_slug(text: str, fallback: str = "image") -> str:
    stem = Path(str(text)).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem[:80] or fallback


def atomic_write_json(path: Path, data, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(data, indent=1, ensure_ascii=False)
    else:
        text = json.dumps(data, ensure_ascii=False, separators=(", ", ": "))
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def surface_offset(attr: int, local_x: int) -> int:
    """Copy of dcpy.level.level_surface_offset (keeps this server raylib-free)."""
    shape = attr & 0x1F
    local_x &= 15
    if shape in (0x01, 0x15, 0x16, 0x18, 0x19, 0x1A, 0x1B):
        return 0
    if shape in (0x02, 0x17):
        return 8
    if shape == 0x03:
        return ((15 - local_x) >> 1) + 8
    if shape == 0x04:
        return (15 - local_x) >> 1
    if shape == 0x05:
        return local_x >> 1
    if shape == 0x06:
        return (local_x >> 1) + 8
    if shape == 0x07:
        return ((15 - local_x) >> 2) + 12
    if shape == 0x08:
        return ((15 - local_x) >> 2) + 8
    if shape == 0x09:
        return ((15 - local_x) >> 2) + 4
    if shape == 0x0A:
        return (15 - local_x) >> 2
    if shape == 0x0B:
        return local_x >> 2
    if shape == 0x0C:
        return (local_x >> 2) + 4
    if shape == 0x0D:
        return (local_x >> 2) + 8
    if shape == 0x0E:
        return (local_x >> 2) + 12
    if shape == 0x0F:
        return 15 - local_x
    if shape == 0x10:
        return local_x
    if shape == 0x11:
        return local_x >> 1
    if shape == 0x12:
        return (local_x >> 1) + 8
    if shape == 0x13:
        return (15 - local_x) >> 1
    if shape == 0x14:
        return ((15 - local_x) >> 1) + 8
    return -1


def shape_label(value: int) -> str:
    if value == 0:
        return "Empty"
    if value == 0x01:
        return "Solid"
    if value == 0x02:
        return "Half ledge"
    offsets = [surface_offset(value, x) for x in (0, 15)]
    if offsets[0] < 0:
        return f"0x{value:02X}"
    a, b = offsets
    if a == b:
        return f"Flat at {a}px"
    if a > b:
        return "Ramp down →"
    return "Ramp up →"


def shape_preview(value: int) -> list[int]:
    """Surface offset at 16 sample columns, -1 meaning no floor."""
    return [surface_offset(value, x) for x in range(16)]


# ---------------------------------------------------------------------------
# Text blocks (mirrors dcpy/text.py)
# ---------------------------------------------------------------------------

# These caps are the loader's, not the editor's: the editor shows both the raw
# JSON and the pages the game will really draw.  `test_editor.py` re-reads
# dcpy/text.py and proves the numbers still match.
TEXT_MAX_STRINGS = 640
TEXT_MAX_PAGES = 8
TEXT_MAX_LINES = 8
TEXT_LINE_MAX = 48
TEXT_GLYPH_W = 8
TEXT_GLYPH_H = 8
TEXT_LINE_H = 10
TEXT_COLUMNS = 16
TEXT_FIRST = 0x20
TEXT_LAST = 0x7E
TEXT_BREAK = "j"          # the ROM's in-line break symbol
TEXT_APOSTROPHE = "["     # the ROM's in-band apostrophe
TEXT_FULLSTOP = "\\"      # period/quote stand-in


def text_split_line(src: str) -> list[str]:
    """Split one ROM line exactly like ``dcpy.text._split_line``."""
    out: list[str] = []
    buf: list[str] = []
    for ch in src:
        if ch == TEXT_BREAK:
            if buf:
                out.append("".join(buf))
            buf = []
        elif len(buf) + 1 < TEXT_LINE_MAX:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def text_copy_line(src: str) -> str:
    """Apply the runtime's in-band substitutions and trailing truncation."""
    out = []
    for ch in src[:TEXT_LINE_MAX - 1]:
        if ch == TEXT_APOSTROPHE:
            out.append("'")
        elif ch == TEXT_FULLSTOP:
            out.append(".")
        else:
            out.append(ch)
    return "".join(out)


def text_normalize(text: str) -> str:
    """Loose matcher used by ``text_find`` (A-Z/0-9 only, single spaces)."""
    out: list[str] = []
    pending = False
    for ch in text:
        c = ch.upper()
        if ("A" <= c <= "Z") or ("0" <= c <= "9"):
            if pending and out:
                out.append(" ")
            pending = False
            out.append(c)
        else:
            pending = True
    return "".join(out)


def text_simulate(pages) -> dict:
    """Reproduce ``text_load_script`` for one block: what the game displays."""
    out_pages: list[list[str]] = []
    counts: list[int] = []
    page_index = 0
    raw_pages = pages if isinstance(pages, list) else []
    for page in raw_pages:
        if page_index >= TEXT_MAX_PAGES:
            break
        lines: list[str] = []
        for line in page if isinstance(page, list) else []:
            if len(lines) >= TEXT_MAX_LINES:
                break
            if isinstance(line, str):
                for piece in text_split_line(line):
                    if len(lines) < TEXT_MAX_LINES:
                        lines.append(text_copy_line(piece))
        if lines:
            out_pages.append(lines)
            counts.append(len(lines))
            page_index += 1
    return {"pages": out_pages, "line_counts": counts}


def text_page_pieces(page) -> list[str]:
    """Every line a raw page expands to after the 'j' split."""
    pieces: list[str] = []
    for line in page if isinstance(page, list) else []:
        if isinstance(line, str):
            pieces.extend(text_split_line(line))
    return pieces


def text_block_warnings(pages, entry: dict | None = None) -> list[dict]:
    """Everything the loader will silently drop or mangle in one block."""
    entry = entry or {}
    raw_pages = pages if isinstance(pages, list) else []
    warnings: list[dict] = []
    kept = 0
    dropped_pages = 0
    dropped_lines = 0
    long_lines = 0
    bad_chars = 0
    for page in raw_pages:
        pieces = text_page_pieces(page)
        if not pieces:
            continue
        if kept >= TEXT_MAX_PAGES:
            dropped_pages += 1
            continue
        kept += 1
        if len(pieces) > TEXT_MAX_LINES:
            dropped_lines += len(pieces) - TEXT_MAX_LINES
        for line in page if isinstance(page, list) else []:
            if isinstance(line, str) and len(line) >= TEXT_LINE_MAX:
                long_lines += 1
    for page in raw_pages:
        for line in page if isinstance(page, list) else []:
            if isinstance(line, str):
                bad_chars += sum(1 for ch in line
                                 if not (TEXT_FIRST <= ord(ch) <= TEXT_LAST))
    if dropped_pages:
        warnings.append(issue(
            "warning", "text.pages.cap",
            f"{len(raw_pages)} pages; the loader keeps {TEXT_MAX_PAGES} "
            f"({dropped_pages} dropped)"))
    if dropped_lines:
        warnings.append(issue(
            "warning", "text.lines.cap",
            f"{dropped_lines} line(s) past the {TEXT_MAX_LINES}-line page cap "
            "are truncated"))
    if long_lines:
        warnings.append(issue(
            "warning", "text.line.long",
            f"{long_lines} line(s) are {TEXT_LINE_MAX}+ characters; the loader "
            f"cuts them to {TEXT_LINE_MAX - 1}"))
    if bad_chars:
        warnings.append(issue(
            "warning", "text.chars.range",
            f"{bad_chars} character(s) outside the 8x8 font "
            f"(0x{TEXT_FIRST:02X}..0x{TEXT_LAST:02X})"))
    if not text_simulate(raw_pages)["pages"]:
        warnings.append(issue("error", "text.empty",
                              "The game would load no pages from this block"))
    if not entry.get("addr"):
        warnings.append(issue("info", "text.addr.missing",
                              "No ROM address recorded"))
    return warnings


def text_prose(entry: dict) -> bool:
    """Heuristic: dialogue/description rather than font or tile data."""
    chunks = [line for page in entry.get("pages") or [] if isinstance(page, list)
              for line in page if isinstance(line, str)]
    text = " ".join(chunks).strip()
    if len(text) < 8 or " " not in text:
        return False
    readable = sum(1 for ch in text if ch.isalpha() or ch in " .,'!?-")
    return readable / len(text) >= 0.8


def clamp_room_music(room: dict) -> int | None:
    value = room.get("music")
    if isinstance(value, (int, float)) and 0 <= int(value) < MUSIC_COUNT:
        return int(value)
    return None


def default_music_for_area(area: int) -> int:
    """Mirror of dcpy.consts.AREA_MUSIC for the rooms the editor lists."""
    table = {
        0: 15, 34: 15, 2: 3, 4: 3, 6: 3, 8: 4, 10: 4, 18: 4, 20: 5,
        22: 6, 26: 6, 30: 6, 36: 7, 38: 7, 48: 8, 54: 8, 50: 9, 52: 9,
        58: 11, 60: 11, 62: 10, 64: 10, 66: 10, 68: 10, 74: 12, 76: 12,
        78: 12, 80: 12, 82: 12, 84: 16, 86: 12, 88: 13, 90: 13, 92: 14,
        94: 2, 96: 14,
    }
    return table.get(area, 3)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class Workspace:
    def __init__(self, root: Path | str, assets: Path | str | None = None,
                 authored: Path | str | None = None):
        self.root = Path(root).resolve()
        self.assets = Path(assets).resolve() if assets else \
            self.root / "assets" / "generated"
        self.authored = Path(authored).resolve() if authored else \
            self.assets.parent / "authored"
        self.rooms_dir = self.authored / "rooms"
        self.sprites_dir = self.authored / "sprites"
        self.backups_dir = self.authored / "backups"
        self.species_generated = self.assets / "species_anim.json"
        self.species_authored = self.authored / "species_anim.json"
        self.enemies_authored = self.authored / "enemies.json"
        self.player_anim_generated = self.assets / "player_anim.json"
        self.player_anim_authored = self.authored / "player_anim.json"
        self.player_forms_generated = self.assets / "player_forms.json"
        self.player_forms_authored = self.authored / "player_forms.json"
        self.room_names = self._load_optional(self.assets / "room_names.json", {})
        self.campaign = self._load_optional(self.assets / "campaign.json", {})
        self._room_cache: dict[Path, tuple[float, int, dict]] = {}
        self._list_cache: tuple[float, dict] | None = None
        self._coverage_cache: tuple[tuple, dict] | None = None
        self.check_results: dict[str, dict] = {}
        self.check_lock = threading.Lock()
        self.lock = threading.RLock()
        for directory in (self.rooms_dir, self.sprites_dir, self.backups_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # -- io ---------------------------------------------------------------
    @staticmethod
    def _load_optional(path: Path, default):
        try:
            return load_json(path)
        except (OSError, ValueError):
            return default

    def _read_json_cached(self, path: Path) -> dict | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        cached = self._room_cache.get(path)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        try:
            data = load_json(path)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        self._room_cache[path] = (stat.st_mtime, stat.st_size, data)
        return data

    def backup(self, path: Path) -> str | None:
        if not path.is_file():
            return None
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        suffix = time.strftime("%Y%m%d_%H%M%S")
        dest = self.backups_dir / f"{path.name}.{suffix}.bak"
        try:
            shutil.copy2(path, dest)
        except OSError:
            return None
        return str(dest.relative_to(self.root)).replace("\\", "/")

    def asset_url(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            rel = path.resolve().relative_to(self.root / "assets")
        except ValueError:
            return None
        return "/assets/" + quote(rel.as_posix())

    def find_asset(self, name: str) -> Path | None:
        name = str(name).replace("\\", "/").lstrip("/")
        candidates = [
            self.assets / name,
            self.authored / name,
            self.authored / "sprites" / name,
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    def find_generated(self, name: str) -> Path | None:
        path = self.assets / name
        return path if path.is_file() else None

    # -- room paths -------------------------------------------------------
    def room_paths(self, area: int) -> tuple[Path, Path]:
        return (self.rooms_dir / f"room_area{area}.json",
                self.assets / f"room_area{area}.json")

    def all_room_areas(self) -> list[int]:
        areas = set()
        for path in self.assets.glob("room_area*.json"):
            m = re.fullmatch(r"room_area(\d+)\.json", path.name)
            if m:
                areas.add(int(m.group(1)))
        for path in self.rooms_dir.glob("room_area*.json"):
            m = re.fullmatch(r"room_area(\d+)\.json", path.name)
            if m:
                areas.add(int(m.group(1)))
        return sorted(areas)

    def load_room(self, area: int) -> dict | None:
        """Return {'room', 'source', 'path', 'authored', 'generated'}."""
        authored, generated = self.room_paths(area)
        if authored.is_file():
            data = self._read_json_cached(authored)
            if data is not None:
                return {"room": copy.deepcopy(data), "source": "authored",
                        "path": authored, "authored": True,
                        "generated": generated.is_file()}
        if generated.is_file():
            data = self._read_json_cached(generated)
            if data is not None:
                return {"room": copy.deepcopy(data), "source": "generated",
                        "path": generated, "authored": False,
                        "generated": True}
        return None

    def room_label(self, area: int) -> str:
        entry = self.room_names.get(str(area)) or self.room_names.get(area)
        map_name = entry.get("map") if isinstance(entry, dict) else None
        if map_name:
            return f"Area {area} · {humanize_slug(map_name)}"
        if self.room_paths(area)[1].is_file():
            return f"Area {area}"
        return f"Area {area} · New room"

    def room_brief(self, area: int, doc: dict, source: str) -> dict:
        objects = doc.get("objects") if isinstance(doc.get("objects"), list) else []
        transitions = doc.get("transitions") \
            if isinstance(doc.get("transitions"), list) else []
        world = doc.get("world") if isinstance(doc.get("world"), dict) else {}
        widths = [int(world.get("width", 0) or 0),
                  int(world.get("height", 0) or 0)]
        music = clamp_room_music(doc)
        return {
            "area": area,
            "label": self.room_label(area),
            "name": doc.get("name") or f"area{area}",
            "source": source,
            "generated": self.room_paths(area)[1].is_file(),
            "world": {"width": widths[0], "height": widths[1]},
            "objects": len(objects),
            "transitions": len(transitions),
            "music": music,
            "effective_music": music if music is not None
            else default_music_for_area(area),
        }

    def list_rooms(self, refresh: bool = False) -> list[dict]:
        stat_key = []
        for path in (self.assets, self.rooms_dir):
            try:
                stat_key.append((str(path), path.stat().st_mtime))
            except OSError:
                stat_key.append((str(path), 0))
        key = tuple(stat_key)
        if not refresh and self._list_cache and self._list_cache[0] == key:
            return self._list_cache[1]
        rooms = []
        for area in self.all_room_areas():
            loaded = self.load_room(area)
            if loaded is None:
                continue
            rooms.append(self.room_brief(area, loaded["room"], loaded["source"]))
        self._list_cache = (key, rooms)
        return rooms

    # -- coverage ----------------------------------------------------------
    def _coverage_signature(self) -> tuple:
        parts = []
        for area in self.all_room_areas():
            for path in self.room_paths(area):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                parts.append((str(path), stat.st_mtime, stat.st_size))
        for path in (self.species_generated, self.species_authored,
                     self.enemies_authored):
            try:
                stat = path.stat()
            except OSError:
                continue
            parts.append((str(path), stat.st_mtime, stat.st_size))
        return tuple(parts)

    def coverage(self, refresh: bool = False) -> dict:
        """Project-wide view of what is placed, what is ported and what is art.

        This is the JSON behind the Coverage view: every object record in every
        room, grouped by species, plus per-room validation.  It is computed
        from the room files the game already loads, so it always agrees with
        ``tools/report_coverage.py`` for the authored overlay.
        """
        signature = self._coverage_signature()
        with self.lock:
            if (not refresh and self._coverage_cache
                    and self._coverage_cache[0] == signature):
                return self._coverage_cache[1]

        species_entries = self._species_entries()
        definitions = self.enemy_definitions()
        by_species: dict[int, dict] = {}
        rooms: list[dict] = []
        type_totals: dict[str, int] = {}
        music_counts: dict[int, int] = {}
        totals = {
            "rooms": 0, "rooms_with_objects": 0, "objects": 0, "unknown": 0,
            "handled": 0, "transitions": 0, "spawns": 0, "authored_rooms": 0,
            "invalid_rooms": 0, "warnings": 0,
        }

        for area in self.all_room_areas():
            loaded = self.load_room(area)
            if loaded is None:
                continue
            room = loaded["room"]
            objects = room.get("objects") if isinstance(room.get("objects"), list) \
                else []
            transitions = room.get("transitions") \
                if isinstance(room.get("transitions"), list) else []
            spawns = room.get("spawns") if isinstance(room.get("spawns"), list) \
                else []
            unknown = 0
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                kind = str(obj.get("type") or "unknown")
                species_id = clamp_int(obj.get("species"), -1, -1, 65535)
                type_totals[kind] = type_totals.get(kind, 0) + 1
                if kind == "unknown":
                    unknown += 1
                row = by_species.get(species_id)
                if row is None:
                    row = {"species": species_id, "records": 0, "unknown": 0,
                           "rooms": [], "types": {}}
                    by_species[species_id] = row
                row["records"] += 1
                row["types"][kind] = row["types"].get(kind, 0) + 1
                if kind == "unknown":
                    row["unknown"] += 1
                if area not in row["rooms"]:
                    row["rooms"].append(area)

            report = self.validate_room(room, area)
            errors = report.get("errors") or []
            warnings = report.get("warnings") or []
            music = clamp_room_music(room)
            effective = music if music is not None \
                else default_music_for_area(area)
            music_counts[effective] = music_counts.get(effective, 0) + 1
            world = room.get("world") if isinstance(room.get("world"), dict) else {}
            rooms.append({
                "area": area,
                "label": self.room_label(area),
                "name": room.get("name") or f"area{area}",
                "source": loaded["source"],
                "authored": bool(loaded["authored"]),
                "objects": len(objects),
                "unknown": unknown,
                "transitions": len(transitions),
                "spawns": len(spawns),
                "music": music,
                "effective_music": effective,
                "world": {"width": clamp_int(world.get("width"), 0, 0),
                          "height": clamp_int(world.get("height"), 0, 0)},
                "valid": bool(report.get("ok")),
                "errors": len(errors),
                "warnings": len(warnings),
            })
            totals["rooms"] += 1
            totals["objects"] += len(objects)
            totals["unknown"] += unknown
            totals["transitions"] += len(transitions)
            totals["spawns"] += len(spawns)
            if objects:
                totals["rooms_with_objects"] += 1
            if loaded["authored"]:
                totals["authored_rooms"] += 1
            if not report.get("ok"):
                totals["invalid_rooms"] += 1
            totals["warnings"] += len(warnings)

        totals["handled"] = totals["objects"] - totals["unknown"]

        species_rows = []
        for species_id, row in by_species.items():
            row["species_hex"] = f"0x{species_id:02X}" if species_id >= 0 else "—"
            row["name"] = SPECIES_NAMES.get(
                species_id, f"Species {species_id:02X}") \
                if species_id >= 0 else "No species id"
            row["art_frames"] = 0
            row["keys"] = []
            row["canonical_key"] = None
            row["authored"] = False
            row["has_definition"] = False
            row["hp"] = None
            row["boss"] = (row["types"].get("boss", 0) > 0)
            species_rows.append(row)
        row_by_species = {row["species"]: row for row in species_rows}

        best_frames: dict[int, int] = {}
        for key, entry in species_entries.items():
            species_id = clamp_int(entry.get("species"), -1, -1, 65535)
            row = row_by_species.get(species_id)
            if row is None:
                row = {
                    "species": species_id,
                    "species_hex": f"0x{species_id:02X}",
                    "name": SPECIES_NAMES.get(species_id,
                                              f"Species {species_id:02X}"),
                    "records": 0, "unknown": 0, "rooms": [], "types": {},
                    "art_frames": 0, "keys": [], "canonical_key": key,
                    "authored": False, "has_definition": False, "hp": None,
                    "boss": False,
                }
                species_rows.append(row)
                row_by_species[species_id] = row
            raw_frames = entry.get("frames")
            frames = raw_frames if isinstance(raw_frames, list) else []
            row["keys"].append(key)
            row["art_frames"] = max(row["art_frames"], len(frames))
            if len(frames) > best_frames.get(species_id, -1):
                best_frames[species_id] = len(frames)
                row["canonical_key"] = key
            if entry.get("_source") == "authored":
                row["authored"] = True

        for row in species_rows:
            for key in row["keys"]:
                definition = definitions.get(key)
                if not isinstance(definition, dict):
                    continue
                row["has_definition"] = True
                hp = (definition.get("status") or {}).get("hp")
                if row["hp"] is None and hp is not None:
                    row["hp"] = hp
                if key == row["canonical_key"] and definition.get("name"):
                    row["name"] = str(definition["name"])
            row["has_art"] = row["art_frames"] > 0
            row["rooms"].sort()
            row["placeholder_only"] = (row["records"] > 0
                                       and row["unknown"] == row["records"])
        species_rows.sort(key=lambda r: (-r["records"], r["species"]))
        rooms.sort(key=lambda r: r["area"])

        placed_rows = [r for r in species_rows if r["records"] > 0]
        totals.update({
            "species_sheets": len(species_entries),
            "species_with_records": len(placed_rows),
            "species_handled": sum(1 for r in placed_rows
                                   if r["unknown"] < r["records"]),
            "species_fully_handled": sum(1 for r in placed_rows
                                         if r["unknown"] == 0),
            "species_with_art": sum(1 for r in placed_rows if r["has_art"]),
            "species_placeholder_only": sum(1 for r in placed_rows
                                            if r["placeholder_only"]),
            "species_without_art": sum(1 for r in placed_rows
                                       if not r["has_art"]),
            "art_missing_records": sum(r["records"] for r in placed_rows
                                       if not r["has_art"]),
            "boss_records": type_totals.get("boss", 0),
        })
        payload = {
            "totals": totals,
            "species": species_rows,
            "rooms": rooms,
            "types": [{"type": key, "records": value}
                      for key, value in sorted(type_totals.items(),
                                               key=lambda kv: (-kv[1], kv[0]))],
            "music": [{"id": index, "name": MUSIC_NAMES[index],
                       "rooms": music_counts.get(index, 0)}
                      for index in range(MUSIC_COUNT)
                      if music_counts.get(index, 0)],
        }
        with self.lock:
            self._coverage_cache = (signature, payload)
        return payload

    # -- text blocks -------------------------------------------------------
    def _text_document(self) -> tuple[list, dict, dict]:
        root = self._load_optional(self.assets / "text_strings.json", {})
        strings = root.get("strings") if isinstance(root, dict) else None
        if not isinstance(strings, list):
            strings = []
        overlay = self._load_optional(self.authored / "text_strings.json", {})
        overrides = overlay.get("strings") if isinstance(overlay, dict) else None
        if not isinstance(overrides, dict):
            overrides = {}
        return strings, overrides, root

    @staticmethod
    def _text_pages_for(index: int, entry: dict, overrides: dict) -> list:
        pages = entry.get("pages")
        if not isinstance(pages, list):
            pages = []
        override = overrides.get(str(index))
        if isinstance(override, list):
            return override
        if isinstance(override, dict) and isinstance(override.get("pages"), list):
            return override["pages"]
        return pages

    def text_usages(self, blocks: list[dict]) -> list[dict]:
        """Resolve every ``text_find`` needle in dcpy/game.py to a block index.

        The runtime looks text up by substring, so a typo or a block pushed out
        of ``TEXT_MAX_STRINGS`` silently turns into "no dialogue".  This walks
        the game's own source instead of duplicating its needle table.
        """
        game_path = self.root / "dcpy" / "game.py"
        try:
            tree = ast.parse(game_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return []
        found: list[tuple[str, str, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                func_name = func.attr
            elif isinstance(func, ast.Name):
                func_name = func.id
            else:
                continue
            if func_name != "text_find":
                continue
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((arg.value, f"game.py:{node.lineno}",
                              node.lineno, "text_find"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "BOSS_INTRO_TEXT" not in names or not isinstance(node.value, ast.Dict):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if (isinstance(key, ast.Constant)
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    found.append((value.value,
                                  f"BOSS_INTRO_TEXT[{key.value}]",
                                  node.lineno, "boss_intro"))
        entries = []
        seen = set()
        for needle, where, line, source in found:
            if (needle, where) in seen:
                continue
            seen.add((needle, where))
            norm = text_normalize(needle)
            index = -1
            if norm:
                for block in blocks:
                    hit = False
                    for page in block["pages"]:
                        if not isinstance(page, list):
                            continue
                        for text in page:
                            if isinstance(text, str) and norm in text_normalize(text):
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        index = block["index"]
                        break
            entries.append({
                "needle": needle,
                "where": where,
                "line": line,
                "source": source,
                "index": index,
                "found": index >= 0,
                "block_addr": blocks[index]["addr"] if index >= 0 else "",
                "block_preview": blocks[index]["preview"] if index >= 0 else "",
            })
        entries.sort(key=lambda entry: entry["line"])
        return entries

    def text_index(self) -> dict:
        strings, overrides, _root = self._text_document()
        blocks = []
        truncated_lines = 0
        for index, entry in enumerate(strings):
            entry = entry if isinstance(entry, dict) else {}
            pages = self._text_pages_for(index, entry, overrides)
            loaded = text_simulate(pages)
            preview = ""
            for page in loaded["pages"]:
                if page:
                    preview = page[0]
                    break
            kept = 0
            dropped = 0
            for page in pages:
                pieces = text_page_pieces(page)
                if not pieces:
                    continue
                if kept >= TEXT_MAX_PAGES:
                    break
                kept += 1
                dropped += max(0, len(pieces) - TEXT_MAX_LINES)
            truncated_lines += dropped
            blocks.append({
                "index": index,
                "addr": str(entry.get("addr") or ""),
                "length": clamp_int(entry.get("length"), 0, 0),
                "pages": pages,
                "loaded": loaded["pages"],
                "line_counts": loaded["line_counts"],
                "warnings": text_block_warnings(pages, entry),
                "prose": text_prose({"pages": pages}),
                "authored": str(index) in overrides,
                "preview": preview[:72],
                "chars": sum(len(line) for page in pages
                             if isinstance(page, list)
                             for line in page if isinstance(line, str)),
                "truncated_lines": dropped,
                "used_by": [],
            })
        usages = self.text_usages(blocks)
        for usage in usages:
            index = usage["index"]
            if 0 <= index < len(blocks) and usage["needle"] not in blocks[index]["used_by"]:
                blocks[index]["used_by"].append(usage["needle"])
        font = self._load_optional(self.assets / "font.json", {})
        font = font if isinstance(font, dict) else {}
        stats = {
            "blocks": len(blocks),
            "authored": sum(1 for block in blocks if block["authored"]),
            "prose": sum(1 for block in blocks if block["prose"]),
            "with_warnings": sum(1 for block in blocks if block["warnings"]),
            "raw_pages": sum(len(block["pages"]) for block in blocks),
            "shown_pages": sum(len(block["loaded"]) for block in blocks),
            "blocks_over_pages": sum(1 for block in blocks
                                     if len(block["pages"]) > TEXT_MAX_PAGES),
            "blocks_over_lines": sum(
                1 for block in blocks
                if any(len(text_page_pieces(page)) > TEXT_MAX_LINES
                       for page in block["pages"])),
            "truncated_lines": truncated_lines,
        }
        return {
            "blocks": blocks,
            "stats": stats,
            "caps": {
                "strings": TEXT_MAX_STRINGS,
                "pages": TEXT_MAX_PAGES,
                "lines": TEXT_MAX_LINES,
                "line_max": TEXT_LINE_MAX,
                "glyph": TEXT_GLYPH_W,
                "line_height": TEXT_LINE_H,
            },
            "font": {
                "url": self.asset_url(self.find_generated("font.png")),
                "cell": clamp_int(font.get("cell"), TEXT_GLYPH_W, 1, 64),
                "columns": clamp_int(font.get("columns"), TEXT_COLUMNS, 1, 64),
                "rows": clamp_int(font.get("rows"), 6, 1, 64),
                "first": clamp_int(font.get("first"), TEXT_FIRST, 0, 0x7F),
                "last": clamp_int(font.get("last"), TEXT_LAST, 0, 0x7F),
                "filled": clamp_int(font.get("filled"), 0, 0, 1024),
            },
            "usages": usages,
        }

    def load_text(self, index: int) -> dict | None:
        data = self.text_index()
        for block in data["blocks"]:
            if block["index"] == index:
                return {"block": block, "caps": data["caps"],
                        "font": data["font"], "stats": data["stats"]}
        return None

    def save_text(self, index: int, pages) -> dict:
        strings, overrides, _root = self._text_document()
        if index < 0 or index >= len(strings):
            return {"ok": False, "error": f"no text block {index}"}
        if not isinstance(pages, list):
            return {"ok": False, "error": "pages must be a list of pages"}
        errors = []
        clean_pages = []
        for page_no, page in enumerate(pages):
            if not isinstance(page, list):
                errors.append(issue("error", "text.page",
                                    f"Page {page_no + 1} is not a list"))
                continue
            clean_lines = []
            for line_no, line in enumerate(page):
                if not isinstance(line, str):
                    errors.append(issue(
                        "error", "text.line",
                        f"Page {page_no + 1} line {line_no + 1} is not text"))
                    continue
                line = line.replace("\r", "").replace("\t", "    ")
                bad = [ch for ch in line
                       if not (TEXT_FIRST <= ord(ch) <= TEXT_LAST)]
                if bad:
                    errors.append(issue(
                        "error", "text.chars.ascii",
                        f"Page {page_no + 1} line {line_no + 1} has "
                        f"{len(bad)} character(s) the 8x8 font cannot draw"))
                clean_lines.append(line)
            clean_pages.append(clean_lines)
        if errors:
            return {"ok": False, "errors": errors}
        overlay_path = self.authored / "text_strings.json"
        overlay = self._load_optional(overlay_path, {})
        if not isinstance(overlay, dict):
            overlay = {}
        entries = overlay.get("strings")
        if not isinstance(entries, dict):
            entries = {}
        entries[str(index)] = {"pages": clean_pages}
        overlay["source"] = "editor"
        overlay["strings"] = entries
        with self.lock:
            backup = self.backup(overlay_path)
            atomic_write_json(overlay_path, overlay)
        return {
            "ok": True,
            "index": index,
            "pages": clean_pages,
            "warnings": text_block_warnings(
                clean_pages, strings[index] if isinstance(strings[index], dict) else {}),
            "backup": backup,
            "path": str(overlay_path.relative_to(self.root)).replace("\\", "/"),
        }

    def delete_text(self, index: int) -> dict:
        overlay_path = self.authored / "text_strings.json"
        overlay = self._load_optional(overlay_path, {})
        entries = overlay.get("strings") if isinstance(overlay, dict) else None
        if not isinstance(entries, dict) or str(index) not in entries:
            return {"ok": False, "error": "no authored override for this block"}
        with self.lock:
            backup = self.backup(overlay_path)
            del entries[str(index)]
            if entries:
                atomic_write_json(overlay_path, overlay)
            else:
                try:
                    overlay_path.unlink()
                except OSError:
                    pass
        return {"ok": True, "backup": backup}

    # -- checks ------------------------------------------------------------
    def _project_python(self) -> str:
        for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
            path = self.root / rel
            if path.is_file():
                return str(path)
        return sys.executable

    def _display_info(self) -> dict:
        env = os.environ.get("DISPLAY") or ""
        xvfb = Path("/tmp/.X11-unix/X99").exists()
        return {
            "env": env,
            "xvfb": xvfb,
            "available": bool(env or xvfb),
            "default": env or (":99" if xvfb else ""),
            "xvfb_command": "Xvfb :99 -screen 0 1600x1200x24 -nolisten tcp &",
        }

    def list_checks(self) -> dict:
        checks = []
        tools = self.root / "tools"
        paths = sorted(tools.glob("check_*.py"))
        regression = tools / "run_regression.py"
        if regression.is_file():
            paths.append(regression)
        for path in paths:
            source = ""
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                pass
            description = ""
            try:
                description = (ast.get_docstring(ast.parse(source)) or "").strip()
                description = description.split("\n")[0]
            except SyntaxError:
                pass
            name = "regression" if path.name == "run_regression.py" else path.stem
            checks.append({
                "name": name,
                "file": f"tools/{path.name}",
                "label": name[6:].replace("_", " ") if name.startswith("check_")
                else name.replace("_", " "),
                "description": description or name,
                "long": name == "regression",
                "needs_display": "dcpy" in source or "raylib" in source,
                "last": self.check_results.get(name),
            })
        return {
            "checks": checks,
            "display": self._display_info(),
            "python": self._project_python(),
        }

    def run_check(self, name: str, timeout: int = 180) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_]+", name or ""):
            return {"ok": False, "error": "invalid check name"}
        if not (name.startswith("check_") or name == "regression"):
            return {"ok": False, "error": "only project checkers can be run"}
        filename = "run_regression.py" if name == "regression" else f"{name}.py"
        path = self.root / "tools" / filename
        if not path.is_file():
            return {"ok": False, "error": f"no check named {name}"}
        timeout = clamp_int(timeout, 180, 10, 900)
        if not self.check_lock.acquire(blocking=False):
            return {"ok": False, "busy": True,
                    "error": "another check is already running"}
        try:
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith("DC_")}
            if not env.get("DISPLAY"):
                display = self._display_info()
                if display["default"]:
                    env["DISPLAY"] = display["default"]
            command = [self._project_python(), f"tools/{path.name}"]
            started = time.time()
            timed_out = False
            try:
                proc = subprocess.Popen(
                    command, cwd=str(self.root), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, start_new_session=True)
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except OSError:
                        proc.kill()
                    try:
                        stdout, stderr = proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                code = proc.returncode
            except OSError as exc:
                stdout, stderr, code = "", str(exc), -1
            elapsed = int((time.time() - started) * 1000)
            combined = f"{stdout}\n{stderr}"
            if timed_out:
                status = "timeout"
            elif code == 0:
                status = "pass" if "FAIL" not in combined else "warn"
            else:
                status = "fail"
            summary = ""
            for line in reversed(combined.splitlines()):
                if "PASS" in line or "FAIL" in line or "EXIT" in line:
                    summary = line.strip()[:200]
                    break
            result = {
                "ok": True,
                "name": name,
                "status": status,
                "exit_code": code,
                "duration_ms": elapsed,
                "timed_out": timed_out,
                "command": " ".join(command),
                "stdout": stdout[-120_000:],
                "stderr": stderr[-60_000:],
                "summary": summary,
                "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with self.lock:
                self.check_results[name] = result
            return result
        finally:
            self.check_lock.release()

    def room_assets(self, area: int, room: dict) -> dict:
        atlas_area = clamp_int(room.get("bg_atlas_area"), area, 0, 999)
        backdrop = self.find_generated(f"bg_backdrop_area{atlas_area}.png")
        bg1 = []
        for pal in range(BG_PALETTES):
            path = self.find_generated(f"bg_area{atlas_area}_pal{pal}.png")
            if path is None:
                path = self.find_generated(f"bg_pal{pal}.png")
            bg1.append(self._tex(path))
        has_bg2 = any(self.find_generated(f"bg2_area{atlas_area}_pal{p}.png")
                      for p in range(BG_PALETTES))
        bg0 = []
        for pal in range(BG_PALETTES):
            if has_bg2:
                path = self.find_generated(f"bg2_area{atlas_area}_pal{pal}.png")
            else:
                path = self.find_generated(f"bg_area{atlas_area}_pal{pal}.png")
                if path is None:
                    path = self.find_generated(f"bg_pal{pal}.png")
            bg0.append(self._tex(path))
        player = self.find_generated("player_idle.png")
        item = self.find_generated("item_00.png")
        heart = self.find_generated("heart_00.png")
        return {
            "atlas_area": atlas_area,
            "bg0": bg0,
            "bg1": bg1,
            "has_bg2": has_bg2,
            "backdrop": self._tex(backdrop),
            "player": self._tex(player),
            "item": self._tex(item),
            "heart": self._tex(heart),
        }

    def _tex(self, path: Path | None) -> dict | None:
        if path is None:
            return None
        size = png_size(path) or (0, 0)
        return {"url": self.asset_url(path), "width": size[0],
                "height": size[1], "name": path.name}

    # -- rooms ------------------------------------------------------------
    def blank_room(self, area: int, width: int, height: int, name: str,
                   atlas_area: int | None = None) -> dict:
        width = max(256, int(width) // 8 * 8)
        height = max(224, int(height) // 8 * 8)
        cols, rows = width // 16, height // 16
        bg_w, bg_h = width // 8, height // 8
        return normalize_room({
            "name": name or f"area{area}",
            "area_id": area,
            "bg_atlas_area": atlas_area if atlas_area is not None else area,
            "backdrop": [8, 8, 16],
            "backdrop_parallax": 0.5,
            "backdrop_y": 0,
            "world": {"width": width, "height": height},
            "camera": {"x": 0, "y": 0, "min_x": 0, "max_x": max(0, width - 256),
                       "min_y": 0, "max_y": max(0, height - 224)},
            "play": {"min_x": 6, "max_x": width - 6, "min_y": 22,
                     "max_y": height},
            "bg": [
                {"name": "bg2", "map_width": bg_w, "map_height": bg_h,
                 "scroll_x": 0, "scroll_y": 0,
                 "tilemap": [0] * (bg_w * bg_h)},
                {"name": "bg1", "map_width": bg_w, "map_height": bg_h,
                 "scroll_x": 0, "scroll_y": 0,
                 "tilemap": [0] * (bg_w * bg_h)},
            ],
            "collision": {"cell": 16, "width": cols, "height": rows,
                          "attrs": [0] * (cols * rows)},
            "spawn": {"x": 64, "y": min(height - 32, 192)},
            "spawns": [{"x": 64, "y": min(height - 32, 192), "flags": 0}],
            "transitions": [],
            "objects": [],
            "player": {"texture": "player_idle.png", "feet_x": 13,
                       "feet_y": 43},
            "sprites": [],
        })

    def save_room(self, area: int, room: dict,
                  target: str = "authored") -> dict:
        room = normalize_room(room)
        report = self.validate_room(room, area)
        if not report["ok"]:
            return {"ok": False, "validation": report, "saved": False}
        if target == "generated":
            path = self.assets / f"room_area{area}.json"
        else:
            path = self.rooms_dir / f"room_area{area}.json"
        with self.lock:
            backup = self.backup(path)
            atomic_write_json(path, room)
            if target == "generated":
                # A generated edit supersedes a stale authored override, which
                # would otherwise keep winning at load time.
                auth_path = self.rooms_dir / f"room_area{area}.json"
                if auth_path.is_file() and auth_path != path:
                    auth_backup = self.backup(auth_path)
                    auth_path.unlink()
                else:
                    auth_backup = None
            else:
                auth_backup = None
            self._list_cache = None
        return {
            "ok": True, "saved": True, "target": target,
            "path": str(path.relative_to(self.root)).replace("\\", "/"),
            "backup": backup, "removed_override_backup": auth_backup,
            "validation": report, "room": room,
        }

    def revert_room(self, area: int) -> dict:
        path = self.rooms_dir / f"room_area{area}.json"
        if not path.is_file():
            return {"ok": False, "error": "no authored override"}
        with self.lock:
            backup = self.backup(path)
            path.unlink()
            self._list_cache = None
        return {"ok": True, "backup": backup}

    def resize_room(self, room: dict, width: int, height: int,
                    resize_bg0: bool = False,
                    resize_collision: bool = True) -> dict:
        room = normalize_room(room)
        width = max(256, int(width) // 8 * 8)
        height = max(224, int(height) // 8 * 8)
        old_world = room.get("world") or {}
        old_w, old_h = int(old_world.get("width", 0)), \
            int(old_world.get("height", 0))
        room["world"] = {"width": width, "height": height}
        if resize_collision:
            col = room.get("collision") or {}
            cell = int(col.get("cell", 16) or 16)
            cols, rows = width // cell + (1 if width % cell else 0), \
                height // cell + (1 if height % cell else 0)
            attrs = list(col.get("attrs") or [])
            old_cols = int(col.get("width", 0) or 0)
            new_attrs = [0] * (cols * rows)
            for y in range(min(rows, int(col.get("height", 0) or 0))):
                for x in range(min(cols, old_cols)):
                    idx = y * old_cols + x
                    if idx < len(attrs):
                        new_attrs[y * cols + x] = int(attrs[idx])
            room["collision"] = {"cell": cell, "width": cols, "height": rows,
                                 "attrs": new_attrs}
        for index, layer in enumerate(room.get("bg") or []):
            if index == 1 or resize_bg0:
                map_w = width // TILE_SIZE
                map_h = height // TILE_SIZE
                tiles = list(layer.get("tilemap") or [])
                old_mw = int(layer.get("map_width", 0) or 0)
                old_mh = int(layer.get("map_height", 0) or 0)
                new_tiles = [0] * (map_w * map_h)
                for y in range(min(map_h, old_mh)):
                    for x in range(min(map_w, old_mw)):
                        idx = y * old_mw + x
                        if idx < len(tiles):
                            new_tiles[y * map_w + x] = int(tiles[idx])
                layer["map_width"] = map_w
                layer["map_height"] = map_h
                layer["tilemap"] = new_tiles
        # Keep the play/camera rectangles inside the new world.
        play = room.get("play") or {}
        play["max_x"] = min(float(play.get("max_x", width - 6)), width - 6.0)
        play["max_y"] = min(float(play.get("max_y", height)), float(height))
        play["min_x"] = max(0.0, min(float(play.get("min_x", 6)), play["max_x"]))
        play["min_y"] = max(0.0, min(float(play.get("min_y", 22)), play["max_y"]))
        room["play"] = play
        cam = room.get("camera") or {}
        cam["max_x"] = min(float(cam.get("max_x", width - 256)), width - 256.0)
        cam["max_y"] = min(float(cam.get("max_y", height - 224)), height - 224.0)
        cam["min_x"] = max(0.0, min(float(cam.get("min_x", 0)), cam["max_x"]))
        cam["min_y"] = max(0.0, min(float(cam.get("min_y", 0)), cam["max_y"]))
        room["camera"] = cam
        if old_w > 0 and old_h > 0 and (width < old_w or height < old_h):
            for obj in room.get("objects") or []:
                obj["x"] = min(float(obj.get("x", 0)), width - 1.0)
                obj["y"] = min(float(obj.get("y", 0)), height - 1.0)
        return room

    def validate_room(self, room: dict, area: int | None = None) -> dict:
        errors: list[dict] = []
        warnings: list[dict] = []
        if not isinstance(room, dict):
            return {"ok": False, "errors": [issue("error", "room.not_object",
                                                  "Room is not a JSON object")],
                    "warnings": []}
        area = clamp_int(area if area is not None else room.get("area_id"), 0,
                         0, 4095)
        for key in REQUIRED_ROOM_KEYS:
            if not isinstance(room.get(key), (dict, list)):
                errors.append(issue("error", f"room.missing.{key}",
                                    f"Missing '{key}' section"))
        name = room.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(issue("warning", "room.name",
                                  "Room has no name"))
        world = room.get("world") or {}
        width = clamp_int(world.get("width"), 0, 0, 65535)
        height = clamp_int(world.get("height"), 0, 0, 65535)
        if width <= 0 or height <= 0:
            errors.append(issue("error", "room.world",
                                "World width/height must be positive"))
        elif width % TILE_SIZE or height % TILE_SIZE:
            warnings.append(issue("warning", "room.world.align",
                                  "World size is not a multiple of 8 px; "
                                  "tiles will clip"))
        if width and height:
            if width > 4096 or height > 4096:
                warnings.append(issue("warning", "room.world.large",
                                      f"World is {width}x{height}; the editor "
                                      "is fastest below 4096 px"))
            if width < 256 or height < 224:
                warnings.append(issue("warning", "room.world.small",
                                      "World is smaller than one screen "
                                      "(256x224)"))
        camera = room.get("camera") or {}
        for key in ("x", "y"):
            if not isinstance(camera.get(key), (int, float)):
                warnings.append(issue("warning", f"room.camera.{key}",
                                      f"Camera {key} is missing"))
        play = room.get("play") or {}
        if isinstance(play, dict) and width and height:
            if float(play.get("max_x", 0) or 0) <= float(play.get("min_x", 0) or 0):
                errors.append(issue("error", "room.play.x",
                                    "Play bounds max_x must be greater than min_x"))
            if float(play.get("max_y", 0) or 0) <= float(play.get("min_y", 0) or 0):
                errors.append(issue("error", "room.play.y",
                                    "Play bounds max_y must be greater than min_y"))
            if float(play.get("min_x", 0) or 0) < 0 or \
                    float(play.get("min_y", 0) or 0) < 0:
                warnings.append(issue("warning", "room.play.negative",
                                      "Play bounds start outside the world"))
        collision = room.get("collision") or {}
        cell = clamp_int(collision.get("cell"), 0, 0, 256)
        cols = clamp_int(collision.get("width"), 0, 0, 4096)
        rows = clamp_int(collision.get("height"), 0, 0, 4096)
        attrs = collision.get("attrs")
        if cell <= 0:
            errors.append(issue("error", "room.collision.cell",
                                "Collision cell size must be positive"))
        elif cell & (cell - 1):
            errors.append(issue("error", "room.collision.cell.power",
                                "Collision cell size must be a power of two"))
        if not isinstance(attrs, list) or len(attrs) != cols * rows:
            errors.append(issue("error", "room.collision.size",
                                f"Collision attrs length "
                                f"{len(attrs) if isinstance(attrs, list) else 0}"
                                f" != {cols * rows}"))
        else:
            bad = [i for i, v in enumerate(attrs)
                   if not isinstance(v, (int, float)) or int(v) < 0 or
                   int(v) > 255]
            if bad:
                errors.append(issue("error", "room.collision.attrs",
                                    f"{len(bad)} collision values outside "
                                    f"0..255 (first at {bad[0]})"))
        bg = room.get("bg")
        if not isinstance(bg, list) or len(bg) != 2:
            errors.append(issue("error", "room.bg.count",
                                "Room must have exactly 2 BG layers"))
        else:
            for i, layer in enumerate(bg):
                if not isinstance(layer, dict):
                    errors.append(issue("error", f"room.bg{i}.type",
                                        f"BG layer {i} is not an object"))
                    continue
                mw = clamp_int(layer.get("map_width"), 0, 0, 4096)
                mh = clamp_int(layer.get("map_height"), 0, 0, 4096)
                tiles = layer.get("tilemap")
                if mw <= 0 or mh <= 0:
                    errors.append(issue("error", f"room.bg{i}.size",
                                        f"BG layer {i} has no size"))
                elif not isinstance(tiles, list) or len(tiles) != mw * mh:
                    errors.append(issue("error", f"room.bg{i}.tilemap",
                                        f"BG layer {i} tilemap length "
                                        f"{len(tiles) if isinstance(tiles, list) else 0}"
                                        f" != {mw * mh}"))
                if mw and mh and (i == 1) and width and height:
                    if mw * TILE_SIZE < width or mh * TILE_SIZE < height:
                        warnings.append(issue("warning", "room.bg1.coverage",
                                              "BG1 is smaller than the world; "
                                              "the right/bottom edge will be empty"))
        spawn = room.get("spawn") or {}
        if not isinstance(spawn.get("x"), (int, float)) or \
                not isinstance(spawn.get("y"), (int, float)):
            errors.append(issue("error", "room.spawn",
                                "Spawn needs numeric x and y"))
        elif width and height:
            if not (0 <= float(spawn["x"]) <= width and
                    0 <= float(spawn["y"]) <= height):
                warnings.append(issue("warning", "room.spawn.outside",
                                      "Spawn lies outside the world"))
        spawns = room.get("spawns")
        if isinstance(spawns, list) and len(spawns) > LEVEL_OBJECT_CAPS["spawns"]:
            warnings.append(issue("warning", "room.spawns.cap",
                                  f"At most {LEVEL_OBJECT_CAPS['spawns']} "
                                  "spawn points are loaded; the rest stay in "
                                  "the file but are ignored"))
        transitions = room.get("transitions") or []
        if isinstance(transitions, list):
            if len(transitions) > LEVEL_OBJECT_CAPS["transitions"]:
                warnings.append(issue("warning", "room.transitions.cap",
                                      f"At most "
                                      f"{LEVEL_OBJECT_CAPS['transitions']} "
                                      "transitions are loaded; the rest stay "
                                      "in the file but are ignored"))
            for idx, tr in enumerate(transitions):
                if not isinstance(tr, dict):
                    errors.append(issue("error", "room.transition.type",
                                        f"Transition {idx} is not an object"))
                    continue
                nxt = clamp_int(tr.get("next_area"), -1, -1, 4095)
                if nxt < 0:
                    warnings.append(issue("warning", "room.transition.next",
                                          f"Transition {idx} has no next area"))
                elif nxt not in self.all_room_areas():
                    warnings.append(issue("warning", "room.transition.missing",
                                          f"Transition {idx} points at area "
                                          f"{nxt}, which has no room file"))
                if not all(isinstance(tr.get(k), (int, float))
                           for k in ("x", "y")):
                    errors.append(issue("error", "room.transition.pos",
                                        f"Transition {idx} needs numeric x/y"))
        objects = room.get("objects") or []
        if isinstance(objects, list):
            if len(objects) > LEVEL_OBJECT_CAPS["objects"]:
                warnings.append(issue("warning", "room.objects.cap",
                                      f"At most {LEVEL_OBJECT_CAPS['objects']} "
                                      "objects are loaded; the rest stay in the "
                                      "file but are ignored"))
            for idx, obj in enumerate(objects):
                if not isinstance(obj, dict):
                    errors.append(issue("error", "room.object.type",
                                        f"Object {idx} is not an object"))
                    continue
                kind = obj.get("type")
                if kind not in LEVEL_OBJECT_TYPES:
                    errors.append(issue("error", "room.object.kind",
                                        f"Object {idx} has unknown type "
                                        f"{kind!r}"))
                if not isinstance(obj.get("x"), (int, float)) or \
                        not isinstance(obj.get("y"), (int, float)):
                    errors.append(issue("error", "room.object.pos",
                                        f"Object {idx} needs numeric x/y"))
                sp = clamp_int(obj.get("species"), 0, 0, 65535)
                if kind in ("enemy", "boss", "npc", "urn") and sp == 0:
                    warnings.append(issue("warning", "room.object.species",
                                          f"Object {idx} ({kind}) has species 0"))
        music = room.get("music")
        if music is not None:
            if not isinstance(music, (int, float)) or \
                    not (0 <= int(music) < MUSIC_COUNT):
                errors.append(issue("error", "room.music",
                                    f"Music id must be 0..{MUSIC_COUNT - 1}"))
        atlas = room.get("bg_atlas_area")
        if atlas is not None and (not isinstance(atlas, (int, float)) or
                                  int(atlas) < 0):
            errors.append(issue("error", "room.bg_atlas_area",
                                "bg_atlas_area must be a non-negative area id"))
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    # -- species ----------------------------------------------------------
    def _species_entries(self) -> dict[str, dict]:
        generated = self._load_optional(self.species_generated, {})
        authored = self._load_optional(self.species_authored, {})
        out: dict[str, dict] = {}
        for source, root in (("generated", generated), ("authored", authored)):
            entries = root.get("species") if isinstance(root, dict) else None
            if isinstance(entries, list):
                entries = {f"{i:02x}": e for i, e in enumerate(entries)
                           if isinstance(e, dict)}
            if not isinstance(entries, dict):
                continue
            for key, entry in entries.items():
                if isinstance(entry, dict):
                    entry = dict(entry)
                    entry["_source"] = source
                    out[str(key)] = entry
        return out

    def enemy_definitions(self) -> dict[str, dict]:
        root = self._load_optional(self.enemies_authored, {})
        entries = root.get("enemies") if isinstance(root, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {str(k): v for k, v in entries.items() if isinstance(v, dict)}

    def _species_def(self, key: str) -> dict | None:
        defs = self.enemy_definitions()
        return defs.get(key)

    def species_display_name(self, entry: dict, definition: dict | None) -> str:
        species_id = clamp_int(entry.get("species"), 0, 0, 65535)
        if isinstance(definition, dict) and definition.get("name"):
            return str(definition["name"])
        name = SPECIES_NAMES.get(species_id, f"Species {species_id:02X}")
        flags = clamp_int(entry.get("flags"), 0, 0, 255)
        if flags:
            name = f"{name} (flags {flags})"
        return name

    def species_summary(self, key: str, entry: dict, defs: dict) -> dict:
        frames = entry.get("frames") if isinstance(entry.get("frames"), list) \
            else []
        species_id = clamp_int(entry.get("species"), 0, 0, 65535)
        variant = entry.get("variant") or ""
        flags = clamp_int(entry.get("flags"), 0, 0, 255)
        thumb = None
        first_frame = None
        if frames and isinstance(frames[0], dict):
            tex = self.find_asset(str(frames[0].get("texture", "")))
            thumb = self._tex(tex)
            first_frame = {
                "url": thumb["url"] if thumb else None,
                "anchor_x": clamp_float(frames[0].get("anchor_x"), 0.0),
                "anchor_y": clamp_float(frames[0].get("anchor_y"), 0.0),
                "width": thumb["width"] if thumb else 0,
                "height": thumb["height"] if thumb else 0,
            }
        definition = defs.get(key) or {}
        name = self.species_display_name(entry, definition)
        states = entry.get("states") if isinstance(entry.get("states"), dict) else {}
        return {
            "key": key,
            "species": species_id,
            "species_hex": f"0x{species_id:02X}",
            "variant": variant,
            "flags": flags,
            "kind": "boss" if variant == "boss" else
                    ("npc" if species_id == 0x96 else "enemy"),
            "frames": len(frames),
            "states": len(states),
            "source": entry.get("_source", "generated"),
            "name": name,
            "thumb": thumb,
            "first_frame": first_frame,
            "hp": (definition.get("status") or {}).get("hp")
            if isinstance(definition, dict) else None,
        }

    def list_species(self) -> list[dict]:
        entries = self._species_entries()
        defs = self.enemy_definitions()
        out = [self.species_summary(key, entry, defs)
               for key, entry in entries.items()]
        out.sort(key=lambda s: (s["species"], s["flags"], s["key"]))
        return out

    def load_species(self, key: str) -> dict | None:
        entries = self._species_entries()
        entry = entries.get(key)
        if entry is None:
            return None
        entry = copy.deepcopy(entry)
        source = entry.pop("_source", "generated")
        frames = []
        for frame in entry.get("frames") or []:
            frame = copy.deepcopy(frame)
            tex = self.find_asset(str(frame.get("texture", "")))
            frame["url"] = self.asset_url(tex)
            size = png_size(tex) if tex else None
            if size:
                frame["actual_width"], frame["actual_height"] = size
            frames.append(frame)
        entry["frames"] = frames
        definition = copy.deepcopy(self._species_def(key))
        return {"key": key, "source": source, "entry": entry,
                "definition": definition}

    def validate_species(self, key: str, entry: dict,
                         definition: dict | None,
                         all_entries: dict[str, dict] | None = None) -> dict:
        errors: list[dict] = []
        warnings: list[dict] = []
        if not re.fullmatch(r"[0-9a-zA-Z_]{1,24}", key or ""):
            errors.append(issue("error", "species.key",
                                "Key must be 1-24 letters, digits or '_'"))
        if not isinstance(entry, dict):
            return {"ok": False, "errors": [issue("error", "species.entry",
                                                 "Entry is not an object")],
                    "warnings": []}
        species_id = clamp_int(entry.get("species"), -1, -1, 65535)
        if species_id < 0:
            errors.append(issue("error", "species.id",
                                "species must be a non-negative integer"))
        frames = entry.get("frames")
        if not isinstance(frames, list) or not frames:
            errors.append(issue("error", "species.frames.empty",
                                "Add at least one frame"))
            frames = frames if isinstance(frames, list) else []
        if len(frames) > MAX_SPECIES_FRAMES:
            errors.append(issue("error", "species.frames.cap",
                                f"The loader keeps at most "
                                f"{MAX_SPECIES_FRAMES} frames"))
        seen_textures: dict[str, int] = {}
        for idx, frame in enumerate(frames):
            if not isinstance(frame, dict):
                errors.append(issue("error", "species.frame.type",
                                    f"Frame {idx} is not an object"))
                continue
            tex = frame.get("texture")
            if not isinstance(tex, str) or not tex:
                errors.append(issue("error", "species.frame.texture",
                                    f"Frame {idx} has no texture"))
                continue
            path = self.find_asset(tex)
            if path is None:
                errors.append(issue("error", "species.frame.missing",
                                    f"Frame {idx}: {tex} does not exist"))
                continue
            size = png_size(path)
            if size is None:
                errors.append(issue("error", "species.frame.png",
                                    f"Frame {idx}: {tex} is not a PNG"))
                continue
            w, h = size
            if w > 64 or h > 64:
                warnings.append(issue("warning", "species.frame.large",
                                      f"Frame {idx}: {w}x{h} is larger than the "
                                      "64x64 the sprite pipeline targets"))
            ax = clamp_float(frame.get("anchor_x"), 0.0)
            ay = clamp_float(frame.get("anchor_y"), 0.0)
            if ax < -24 or ax > w + 24:
                errors.append(issue("error", "species.frame.anchor_x",
                                    f"Frame {idx}: anchor_x {ax:g} is far "
                                    f"outside 0..{w}"))
            elif ax < 0 or ax > w:
                warnings.append(issue("warning", "species.frame.anchor_x.edge",
                                      f"Frame {idx}: anchor_x {ax:g} is outside "
                                      f"0..{w}"))
            if ay < -2 or ay > h + 16:
                warnings.append(issue("warning", "species.frame.anchor_y",
                                      f"Frame {idx}: anchor_y {ay:g} is outside "
                                      f"0..{h}"))
            for dim, actual in (("width", w), ("height", h)):
                value = frame.get(dim)
                if value is not None and int(value) != actual:
                    warnings.append(issue("warning",
                                          f"species.frame.{dim}.mismatch",
                                          f"Frame {idx}: JSON {dim}={value} but "
                                          f"PNG is {actual}"))
            if frame.get("duration") is not None and \
                    clamp_int(frame.get("duration"), 6, 1, 255) < 1:
                warnings.append(issue("warning", "species.frame.duration",
                                      f"Frame {idx}: duration must be >= 1"))
            if tex in seen_textures:
                warnings.append(issue("warning", "species.frame.duplicate",
                                      f"Frame {idx} reuses frame "
                                      f"{seen_textures[tex]}'s texture"))
            else:
                seen_textures[tex] = idx
        states = entry.get("states")
        if states is not None and not isinstance(states, dict):
            errors.append(issue("error", "species.states.type",
                                "states must be an object keyed 0..15"))
        elif isinstance(states, dict):
            for state_key, seq in states.items():
                try:
                    state_id = int(state_key)
                except (TypeError, ValueError):
                    errors.append(issue("error", "species.state.key",
                                        f"State key {state_key!r} is not a "
                                        "number"))
                    continue
                if state_id < 0 or state_id >= MAX_SPECIES_STATES:
                    errors.append(issue("error", "species.state.range",
                                        f"State {state_id} is outside 0.."
                                        f"{MAX_SPECIES_STATES - 1}"))
                if not isinstance(seq, list):
                    errors.append(issue("error", "species.state.seq",
                                        f"State {state_id} is not a list"))
                    continue
                if len(seq) > MAX_STATE_FRAMES:
                    errors.append(issue("error", "species.state.cap",
                                        f"State {state_id} has {len(seq)} "
                                        f"frames; the loader keeps "
                                        f"{MAX_STATE_FRAMES}"))
                for pos, frame_idx in enumerate(seq):
                    if not isinstance(frame_idx, (int, float)) or \
                            not (0 <= int(frame_idx) < len(frames)):
                        errors.append(issue("error", "species.state.index",
                                            f"State {state_id}[{pos}] -> frame "
                                            f"{frame_idx} does not exist"))
        for field in ("hurt", "default"):
            value = entry.get(field)
            if value is not None:
                if not isinstance(value, (int, float)) or \
                        not (0 <= int(value) < len(frames)):
                    errors.append(issue("error", f"species.{field}",
                                        f"{field} must point at an existing "
                                        f"frame"))
        variant = entry.get("variant")
        if variant not in (None, "", "boss"):
            errors.append(issue("error", "species.variant",
                                "variant must be absent or 'boss'"))
        if variant == "boss" and not (0 <= clamp_int(entry.get("flags"), 0, 0, 255)
                                      <= 255):
            errors.append(issue("error", "species.flags",
                                "flags must be 0..255"))
        # Duplicate image check: the sprite audit rejects the same PNG serving
        # two species, so surface it here before the save.
        if all_entries:
            for other_key, other in all_entries.items():
                if other_key == key:
                    continue
                other_tex = {str(f.get("texture")) for f in
                             (other.get("frames") or [])
                             if isinstance(f, dict)}
                overlap = other_tex.intersection(seen_textures)
                if overlap:
                    warnings.append(issue("warning", "species.frame.shared",
                                          f"{len(overlap)} texture(s) also used "
                                          f"by species {other_key} "
                                          f"({', '.join(sorted(overlap)[:3])})"))
                    break
        # Definition checks.
        if definition:
            errors.extend(self._validate_enemy_def(definition))
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    def _validate_enemy_def(self, definition: dict) -> list[dict]:
        errors: list[dict] = []
        status = definition.get("status") or {}
        hp = clamp_int(status.get("hp"), 1, 1, 255)
        if hp < 1:
            errors.append(issue("error", "enemy.hp", "HP must be at least 1"))
        damage = clamp_int(status.get("contact_damage"), 1, 0, 9)
        if damage < 0:
            errors.append(issue("error", "enemy.damage",
                                "Contact damage cannot be negative"))
        movement = definition.get("movement") or {}
        if movement.get("ai") not in AI_KINDS:
            errors.append(issue("error", "enemy.ai",
                                f"AI must be one of {', '.join(AI_KINDS)}"))
        if not (0 <= clamp_float(movement.get("speed"), 0.5) <= 8):
            errors.append(issue("error", "enemy.speed",
                                "speed must be 0..8 px/frame"))
        attacks = definition.get("attacks") or []
        if len(attacks) > 8:
            errors.append(issue("error", "enemy.attacks.cap",
                                "At most 8 attack patterns"))
        for i, attack in enumerate(attacks):
            if not isinstance(attack, dict):
                errors.append(issue("error", "enemy.attack.type",
                                    f"Attack {i} is not an object"))
                continue
            if attack.get("type") not in ATTACK_TYPES:
                errors.append(issue("error", "enemy.attack.type",
                                    f"Attack {i}: unknown type "
                                    f"{attack.get('type')!r}"))
            if not (1 <= clamp_int(attack.get("cooldown"), 60, 1, 3600) <= 3600):
                errors.append(issue("error", "enemy.attack.cooldown",
                                    f"Attack {i}: cooldown must be 1..3600"))
            if not (0 <= clamp_float(attack.get("range"), 160) <= 4096):
                errors.append(issue("error", "enemy.attack.range",
                                    f"Attack {i}: range must be 0..4096"))
        sounds = definition.get("sounds") or {}
        if isinstance(sounds, dict):
            for slot, value in sounds.items():
                if value and value not in SFX_NAMES:
                    errors.append(issue("error", "enemy.sound",
                                        f"Sound '{slot}' -> unknown effect "
                                        f"{value!r}"))
        return errors

    def save_species(self, key: str, entry: dict,
                     definition: dict | None = None,
                     target: str = "authored") -> dict:
        if not isinstance(entry, dict):
            return {"ok": False,
                    "validation": {"ok": False,
                                   "errors": [issue("error", "species.entry",
                                                    "Entry is not an object")],
                                   "warnings": []}}
        entry = normalize_species_entry(key, entry)
        all_entries = self._species_entries()
        report = self.validate_species(key, entry, definition, all_entries)
        if not report["ok"]:
            return {"ok": False, "validation": report, "saved": False}
        with self.lock:
            path = self.species_generated if target == "generated" \
                else self.species_authored
            root = self._load_optional(path, {"species": {}})
            if not isinstance(root, dict):
                root = {"species": {}}
            entries = root.get("species")
            if not isinstance(entries, dict):
                entries = {}
                root["species"] = entries
            backup = self.backup(path)
            entries[key] = strip_internal(entry)
            # Keep the authored sheet diff-friendly; the generated tree and the
            # player sheets are pretty-printed too.
            atomic_write_json(path, root, pretty=True)
            # Enemy definition sidecar.
            defs = self._load_optional(self.enemies_authored, {})
            if not isinstance(defs, dict):
                defs = {}
            enemies = defs.get("enemies")
            if not isinstance(enemies, dict):
                enemies = {}
                defs["enemies"] = enemies
            defs["version"] = 1
            if definition:
                stamped = dict(definition)
                stamped["key"] = key
                stamped["species"] = entry.get("species", 0)
                stamped["flags"] = entry.get("flags", 0)
                stamped["variant"] = entry.get("variant", "")
                enemies[key] = normalize_enemy_def(stamped)
            else:
                enemies.pop(key, None)
            if enemies:
                atomic_write_json(self.enemies_authored, defs, pretty=True)
            else:
                try:
                    self.enemies_authored.unlink()
                except OSError:
                    pass
        return {
            "ok": True, "saved": True, "target": target,
            "path": str(path.relative_to(self.root)).replace("\\", "/"),
            "backup": backup, "validation": report,
            "entry": entry, "definition": definition or {},
        }

    def delete_species(self, key: str) -> dict:
        with self.lock:
            root = self._load_optional(self.species_authored, {})
            entries = root.get("species") if isinstance(root, dict) else None
            if not isinstance(entries, dict) or key not in entries:
                return {"ok": False, "error": "no authored override"}
            backup = self.backup(self.species_authored)
            del entries[key]
            if entries:
                atomic_write_json(self.species_authored, root, pretty=True)
            else:
                try:
                    self.species_authored.unlink()
                except OSError:
                    pass
            defs = self._load_optional(self.enemies_authored, {})
            enemies = defs.get("enemies") if isinstance(defs, dict) else None
            if isinstance(enemies, dict) and key in enemies:
                del enemies[key]
                if enemies:
                    atomic_write_json(self.enemies_authored, defs, pretty=True)
                else:
                    try:
                        self.enemies_authored.unlink()
                    except OSError:
                        pass
        return {"ok": True, "backup": backup}

    # -- player ----------------------------------------------------------
    @staticmethod
    def player_target(target) -> tuple[str, int] | None:
        text = str(target).strip().lower()
        if text in ("base", "player", "firebrand"):
            return "base", -1
        try:
            index = int(text)
        except (TypeError, ValueError):
            return None
        if 0 <= index < PLAYER_FORM_COUNT:
            return "form", index
        return None

    def _player_authored_forms(self) -> dict[int, dict]:
        root = self._load_optional(self.player_forms_authored, {})
        out: dict[int, dict] = {}
        forms = root.get("forms") if isinstance(root, dict) else None
        for entry in forms if isinstance(forms, list) else []:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("form"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < PLAYER_FORM_COUNT:
                out[index] = entry
        return out

    def _player_generated_forms(self) -> dict[int, dict]:
        root = self._load_optional(self.player_forms_generated, {})
        out: dict[int, dict] = {}
        forms = root.get("forms") if isinstance(root, dict) else None
        for entry in forms if isinstance(forms, list) else []:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("form"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < PLAYER_FORM_COUNT:
                out[index] = entry
        return out

    def _player_base(self) -> dict:
        generated = self._load_optional(self.player_anim_generated, {})
        authored = self._load_optional(self.player_anim_authored, {})
        clips = {}
        for source in (generated, authored):
            if isinstance(source, dict) and isinstance(source.get("clips"), dict):
                clips.update(source["clips"])
        return {"clips": clips}

    def _player_entry(self, target) -> tuple[dict | None, str, bool]:
        parsed = self.player_target(target)
        if parsed is None:
            return None, "generated", False
        kind, index = parsed
        if kind == "base":
            return self._player_base(), \
                "authored" if self.player_anim_authored.is_file() else \
                "generated", self.player_anim_authored.is_file()
        generated = self._player_generated_forms().get(index)
        authored = self._player_authored_forms().get(index)
        if authored is not None:
            return copy.deepcopy(authored), "authored", True
        if generated is not None:
            return copy.deepcopy(generated), "generated", False
        return None, "generated", False

    def player_entry_title(self, kind: str, index: int, entry: dict) -> str:
        if kind == "base":
            return "Firebrand (base animation)"
        name = str(entry.get("name") or "").strip()
        label = PLAYER_FORM_NAMES[index]
        if not name or name.lower() == label.lower():
            return label
        return f"{label} · {name}"

    def player_summary(self, kind: str, index: int, entry: dict,
                       source: str) -> dict:
        clips = entry.get("clips") if isinstance(entry.get("clips"), dict) \
            else {}
        clip_list = []
        thumb = None
        total = 0
        for name in PLAYER_CLIP_NAMES:
            clip = clips.get(name)
            if not isinstance(clip, dict):
                continue
            steps = clip.get("steps") if isinstance(clip.get("steps"), list) \
                else []
            total += len(steps)
            first = None
            if steps and isinstance(steps[0], dict):
                tex = self.find_asset(str(steps[0].get("texture", "")))
                first = self._tex(tex)
                if thumb is None and first is not None:
                    thumb = first
            clip_list.append({
                "name": name, "loop": bool(clip.get("loop")),
                "steps": len(steps), "thumb": first,
            })
        target = "base" if kind == "base" else str(index)
        return {
            "target": target,
            "kind": kind,
            "form": index,
            "name": self.player_entry_title(kind, index, entry),
            "source": source,
            "overridden": source == "authored",
            "clips": clip_list,
            "clip_count": len(clip_list),
            "steps": total,
            "thumb": thumb,
        }

    def list_player(self) -> dict:
        base, base_source, _ = self._player_entry("base")
        forms = []
        for index in range(PLAYER_FORM_COUNT):
            entry, source, _ = self._player_entry(str(index))
            if entry is None:
                continue
            forms.append(self.player_summary("form", index, entry, source))
        return {
            "base": self.player_summary("base", -1, base or {}, base_source),
            "forms": forms,
            "clip_names": list(PLAYER_CLIP_NAMES),
            "form_names": list(PLAYER_FORM_NAMES),
            "limits": {"steps": PLAYER_MAX_STEPS, "forms": PLAYER_FORM_COUNT,
                       "clips": len(PLAYER_CLIP_NAMES)},
        }

    def load_player(self, target) -> dict | None:
        parsed = self.player_target(target)
        if parsed is None:
            return None
        kind, index = parsed
        entry, source, overridden = self._player_entry(target)
        if entry is None:
            return None
        entry = copy.deepcopy(entry)
        clips_in = entry.get("clips") if isinstance(entry.get("clips"), dict) \
            else {}
        clips = {}
        for name in PLAYER_CLIP_NAMES:
            clip = clips_in.get(name)
            if not isinstance(clip, dict):
                continue
            steps = []
            for step in clip.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                step = copy.deepcopy(step)
                tex = self.find_asset(str(step.get("texture", "")))
                step["url"] = self.asset_url(tex)
                size = png_size(tex) if tex else None
                if size:
                    step["actual_width"], step["actual_height"] = size
                steps.append(step)
            clips[name] = {"loop": bool(clip.get("loop")), "steps": steps}
        entry["clips"] = clips
        return {
            "ok": True,
            "target": "base" if kind == "base" else str(index),
            "kind": kind,
            "form": index,
            "source": source,
            "overridden": overridden,
            "entry": entry,
            "title": self.player_entry_title(kind, index, entry),
            "clip_names": list(PLAYER_CLIP_NAMES),
            "limits": {"steps": PLAYER_MAX_STEPS, "forms": PLAYER_FORM_COUNT,
                       "clips": len(PLAYER_CLIP_NAMES)},
        }

    def validate_player(self, target, entry: dict) -> dict:
        parsed = self.player_target(target)
        errors: list[dict] = []
        warnings: list[dict] = []
        if parsed is None:
            return {"ok": False, "errors": [issue(
                "error", "player.target", "Unknown player target")],
                "warnings": []}
        kind, index = parsed
        if not isinstance(entry, dict):
            return {"ok": False, "errors": [issue(
                "error", "player.entry", "Entry is not an object")],
                "warnings": []}
        if kind == "form":
            if clamp_int(entry.get("form"), index) != index:
                errors.append(issue("error", "player.form",
                                    f"form must be {index}"))
            name = str(entry.get("name") or "").strip()
            if not name:
                warnings.append(issue("warning", "player.name",
                                      "Form has no display name"))
        clips = entry.get("clips")
        if not isinstance(clips, dict):
            errors.append(issue("error", "player.clips",
                                "clips must be an object"))
            clips = {}
        total = 0
        for name, clip in clips.items():
            if name not in PLAYER_CLIP_NAMES:
                warnings.append(issue("warning", "player.clip",
                                      f"Unknown clip '{name}' will be ignored"))
                continue
            if not isinstance(clip, dict):
                errors.append(issue("error", "player.clip",
                                    f"Clip {name} must be an object"))
                continue
            steps = clip.get("steps")
            if not isinstance(steps, list):
                errors.append(issue("error", "player.clip",
                                    f"Clip {name} needs a steps array"))
                continue
            if not steps:
                warnings.append(issue("warning", "player.clip.empty",
                                      f"Clip {name} has no frames"))
                continue
            for step_index, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append(issue("error", "player.step",
                                        f"{name}[{step_index}] is not an object"))
                    continue
                tex_name = step.get("texture")
                if not isinstance(tex_name, str) or not tex_name:
                    errors.append(issue("error", "player.step.texture",
                                        f"{name}[{step_index}] has no texture"))
                    continue
                path = self.find_asset(tex_name)
                if path is None:
                    errors.append(issue("error", "player.step.texture",
                                        f"{name}[{step_index}] missing image "
                                        f"'{tex_name}'"))
                    continue
                size = png_size(path)
                ax = clamp_float(step.get("anchor_x"), 0.0)
                ay = clamp_float(step.get("anchor_y"), 0.0)
                if size and not (0 <= ax <= size[0] and 0 <= ay <= size[1]):
                    warnings.append(issue(
                        "warning", "player.step.anchor",
                        f"{name}[{step_index}] anchor ({ax:g},{ay:g}) is "
                        f"outside the {size[0]}x{size[1]} image"))
                if clamp_int(step.get("duration"), 0) < 1:
                    warnings.append(issue(
                        "warning", "player.step.duration",
                        f"{name}[{step_index}] duration must be >= 1"))
                total += 1
        if total > PLAYER_MAX_STEPS:
            errors.append(issue(
                "error", "player.steps",
                f"{total} total frames; the loader keeps {PLAYER_MAX_STEPS}"))
        if total == 0:
            errors.append(issue("error", "player.steps",
                                "The player sheet has no frames"))
        if kind == "base" and "idle" not in clips:
            warnings.append(issue("warning", "player.idle",
                                  "Base player has no idle clip"))
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    @staticmethod
    def normalize_player_entry(target, entry: dict) -> dict:
        parsed = Workspace.player_target(target)
        kind, index = parsed if parsed else ("base", -1)
        clips_in = entry.get("clips") if isinstance(entry, dict) else {}
        clips = {}
        for name in PLAYER_CLIP_NAMES:
            clip = clips_in.get(name) if isinstance(clips_in, dict) else None
            if not isinstance(clip, dict):
                continue
            steps = []
            for step in clip.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                texture = str(step.get("texture", "")).strip()
                if not texture:
                    continue
                steps.append({
                    "texture": texture,
                    "anchor_x": clamp_int(step.get("anchor_x"), 0),
                    "anchor_y": clamp_int(step.get("anchor_y"), 0),
                    "duration": max(1, clamp_int(step.get("duration"), 1)),
                })
            if not steps:
                continue
            clips[name] = {"loop": bool(clip.get("loop")), "steps": steps}
        if kind == "base":
            return {"source": "player editor", "clips": clips}
        return {
            "form": index,
            "name": str(entry.get("name") or PLAYER_FORM_NAMES[index]),
            "clips": clips,
        }

    def save_player(self, target, entry: dict) -> dict:
        parsed = self.player_target(target)
        if parsed is None:
            return {"ok": False, "error": "unknown player target"}
        kind, index = parsed
        validation = self.validate_player(target, entry)
        if not validation["ok"]:
            return {"ok": False, "validation": validation}
        clean = self.normalize_player_entry(target, entry)
        backup = None
        with self.lock:
            if kind == "base":
                backup = self.backup(self.player_anim_authored)
                atomic_write_json(self.player_anim_authored, clean, pretty=True)
            else:
                root = self._load_optional(self.player_forms_authored, {})
                if not isinstance(root, dict):
                    root = {}
                forms = root.get("forms")
                if not isinstance(forms, list):
                    forms = []
                replaced = False
                for i, item in enumerate(forms):
                    if isinstance(item, dict) and \
                            clamp_int(item.get("form"), -1) == index:
                        forms[i] = clean
                        replaced = True
                        break
                if not replaced:
                    forms.append(clean)
                root["forms"] = forms
                backup = self.backup(self.player_forms_authored)
                atomic_write_json(self.player_forms_authored, root, pretty=True)
        loaded = self.load_player(target)
        return {"ok": True, "backup": backup, "validation": validation,
                "entry": loaded["entry"] if loaded else clean,
                "target": loaded["target"] if loaded else str(target),
                "source": loaded["source"] if loaded else "authored"}

    def delete_player(self, target) -> dict:
        parsed = self.player_target(target)
        if parsed is None:
            return {"ok": False, "error": "unknown player target"}
        kind, index = parsed
        with self.lock:
            if kind == "base":
                if not self.player_anim_authored.is_file():
                    return {"ok": False, "error": "no authored override"}
                backup = self.backup(self.player_anim_authored)
                self.player_anim_authored.unlink()
                return {"ok": True, "backup": backup}
            root = self._load_optional(self.player_forms_authored, {})
            forms = root.get("forms") if isinstance(root, dict) else None
            if not isinstance(forms, list):
                return {"ok": False, "error": "no authored override"}
            new_forms = [item for item in forms
                         if not (isinstance(item, dict) and
                                 clamp_int(item.get("form"), -1) == index)]
            if len(new_forms) == len(forms):
                return {"ok": False, "error": "no authored override"}
            backup = self.backup(self.player_forms_authored)
            if new_forms:
                root["forms"] = new_forms
                atomic_write_json(self.player_forms_authored, root, pretty=True)
            else:
                try:
                    self.player_forms_authored.unlink()
                except OSError:
                    pass
            return {"ok": True, "backup": backup}

    def save_upload(self, name: str, data_b64: str,
                    overwrite: bool = False) -> dict:
        try:
            raw = base64.b64decode(data_b64.split(",", 1)[-1], validate=True)
        except Exception:
            return {"ok": False, "error": "invalid base64 payload"}
        if len(raw) > 8 * 1024 * 1024:
            return {"ok": False, "error": "image is larger than 8 MB"}
        ok, width, height = png_is_valid(raw)
        if not ok:
            return {"ok": False, "error": "file is not a valid PNG"}
        stem = safe_slug(name)
        filename = f"{stem}.png"
        self.sprites_dir.mkdir(parents=True, exist_ok=True)
        path = self.sprites_dir / filename
        if path.exists() and not overwrite:
            suffix = time.strftime("%H%M%S")
            filename = f"{stem}_{suffix}.png"
            path = self.sprites_dir / filename
        path.write_bytes(raw)
        return {
            "ok": True,
            "texture": f"sprites/{filename}",
            "url": self.asset_url(path),
            "width": width,
            "height": height,
            "path": str(path.relative_to(self.root)).replace("\\", "/"),
        }

    # -- assets -----------------------------------------------------------
    def list_images(self) -> list[dict]:
        usage = self._image_usage()
        out = []
        for base in (self.assets, self.authored):
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.png")):
                if self.backups_dir in path.parents:
                    continue
                size = png_size(path) or (0, 0)
                rel = path.relative_to(base).as_posix()
                key = rel if base == self.assets else f"authored:{rel}"
                out.append({
                    "key": key,
                    "name": path.name,
                    "path": str(path.relative_to(self.root)).replace("\\", "/"),
                    "url": self.asset_url(path),
                    "width": size[0],
                    "height": size[1],
                    "bytes": path.stat().st_size,
                    "source": "generated" if base == self.assets else "authored",
                    "usage": usage.get(key, []),
                })
        out.sort(key=lambda img: (img["source"] != "generated",
                                  img["path"].lower()))
        return out

    def _image_usage(self) -> dict[str, list[str]]:
        usage: dict[str, list[str]] = {}

        def add(key: str, text: str) -> None:
            if not key:
                return
            usage.setdefault(key, []).append(text)
            # Frames may live in the authored overlay under the same relative
            # name (the asset browser keys those as ``authored:<name>``).
            if not key.startswith("authored:"):
                usage.setdefault(f"authored:{key}", []).append(
                    f"{text} (authored copy)")

        for area in self.all_room_areas():
            loaded = self.load_room(area)
            if not loaded:
                continue
            label = self.room_label(area)
            room = loaded["room"]
            atlas = clamp_int(room.get("bg_atlas_area"), area, 0, 999)
            for pal in range(BG_PALETTES):
                name = f"bg_area{atlas}_pal{pal}.png"
                if (self.assets / name).is_file():
                    add(name, f"{label} Â· BG1 palette {pal}")
                name = f"bg2_area{atlas}_pal{pal}.png"
                if (self.assets / name).is_file():
                    add(name, f"{label} Â· BG0 palette {pal}")
            name = f"bg_backdrop_area{atlas}.png"
            if (self.assets / name).is_file():
                add(name, f"{label} Â· backdrop")
        for key, entry in self._species_entries().items():
            for idx, frame in enumerate(entry.get("frames") or []):
                if isinstance(frame, dict):
                    name = str(frame.get("texture", "")).replace("\\", "/")
                    if name:
                        add(name, f"Species {key} Â· frame {idx}")
        for name, clips in (("player_anim.json", True),
                            ("player_forms.json", False)):
            path = self.assets / name
            data = self._load_optional(path, None)
            if not isinstance(data, dict):
                continue
            if name == "player_anim.json":
                for clip, value in (data.get("clips") or {}).items():
                    for step in value.get("steps") or []:
                        add(str(step.get("texture", "")),
                            f"Player Â· {clip}")
            else:
                for form in data.get("forms") or []:
                    for clip, value in (form.get("clips") or {}).items():
                        for step in value.get("steps") or []:
                            add(str(step.get("texture", "")),
                                f"Player {form.get('name', '')} Â· {clip}")
        for name in ("player_idle.png", "player_idle_0.png", "item_00.png",
                     "heart_00.png", "hud_bar.png", "hud_slots.png",
                     "font.png", "world_map.png"):
            if (self.assets / name).is_file():
                add(name, "Shared UI / player")
        for i in range(BG_PALETTES):
            for stem in ("bg_pal", "obj_pal"):
                name = f"{stem}{i}.png"
                if (self.assets / name).is_file():
                    add(name, "Shared atlas")
        return usage

    def meta(self) -> dict:
        audio_dir = self.assets / "audio"
        music = []
        for index, label in enumerate(MUSIC_NAMES):
            if index == 0:
                music.append({"id": 0, "name": label, "url": None})
                continue
            stem = [
                "music_title", "music_overworld", "music_murkland",
                "music_ruined_city", "music_dark_forest",
                "music_dark_forest_cave", "music_towers_of_doom",
                "music_poseidonia", "music_poseidonia_depths",
                "music_mountains", "music_mountains_valley", "music_phalanx",
                "music_demon_hideout", "music_town", "music_boss",
                "music_boss_common", "music_ending",
            ][index - 1]
            path = audio_dir / f"{stem}.wav"
            music.append({"id": index, "name": label,
                          "url": self.asset_url(path) if path.is_file() else None})
        sfx = []
        for name in SFX_NAMES:
            path = audio_dir / SFX_FILES[name]
            sfx.append({"name": name,
                        "url": self.asset_url(path) if path.is_file() else None})
        shapes = []
        for value in range(0x1C):
            shapes.append({
                "value": value,
                "label": shape_label(value),
                "preview": shape_preview(value) if value else [],
                "solid": value != 0 and surface_offset(value, 0) >= 0,
            })
        return {
            "music": music,
            "sfx": sfx,
            "object_types": [{"value": t, "label": LEVEL_OBJECT_LABELS[t]}
                             for t in LEVEL_OBJECT_TYPES],
            "shape_values": shapes,
            "env_flags": [
                {"value": 0x00, "label": "None"},
                {"value": 0x20, "label": "Hazard"},
                {"value": 0x40, "label": "Breakable"},
                {"value": 0x60, "label": "Water"},
                {"value": 0x80, "label": "Slope ramp"},
            ],
            "limits": {
                "species_frames": MAX_SPECIES_FRAMES,
                "species_states": MAX_SPECIES_STATES,
                "state_frames": MAX_STATE_FRAMES,
                "objects": LEVEL_OBJECT_CAPS["objects"],
                "transitions": LEVEL_OBJECT_CAPS["transitions"],
                "spawns": LEVEL_OBJECT_CAPS["spawns"],
                "bg_palettes": BG_PALETTES,
            },
            "ai_kinds": AI_KINDS,
            "attack_types": ATTACK_TYPES,
            "default_music": {str(area): default_music_for_area(area)
                              for area in self.all_room_areas()},
        }

    def info(self) -> dict:
        return {
            "root": str(self.root),
            "assets": str(self.assets),
            "authored": str(self.authored),
            "assets_url": "/assets",
            "rooms": len(self.all_room_areas()),
            "species": len(self._species_entries()),
            "version": "1.0",
        }


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

ROOM_KEY_ORDER = [
    "name", "area_id", "bg_atlas_area", "gate_next_area", "gate_marker",
    "gate_entry", "music", "backdrop", "backdrop_parallax", "backdrop_y",
    "world", "camera", "play", "bg", "collision", "spawn", "spawns",
    "transitions", "objects", "player", "sprites",
]


def normalize_room(room: dict) -> dict:
    out: dict = {}
    for key in ROOM_KEY_ORDER:
        if key in room:
            out[key] = room[key]
    for key, value in room.items():
        if key not in out:
            out[key] = value
    if isinstance(out.get("world"), dict):
        out["world"]["width"] = clamp_int(out["world"].get("width"), 256, 0)
        out["world"]["height"] = clamp_int(out["world"].get("height"), 224, 0)
    if isinstance(out.get("collision"), dict):
        col = out["collision"]
        col["cell"] = clamp_int(col.get("cell"), 16, 1)
        col["width"] = clamp_int(col.get("width"), 0, 0)
        col["height"] = clamp_int(col.get("height"), 0, 0)
        if isinstance(col.get("attrs"), list):
            col["attrs"] = [clamp_int(v, 0, 0, 255) for v in col["attrs"]]
    if isinstance(out.get("bg"), list):
        for layer in out["bg"]:
            if not isinstance(layer, dict):
                continue
            layer["map_width"] = clamp_int(layer.get("map_width"), 0, 0)
            layer["map_height"] = clamp_int(layer.get("map_height"), 0, 0)
            if isinstance(layer.get("tilemap"), list):
                layer["tilemap"] = [clamp_int(v, 0, 0, 0xFFFF)
                                    for v in layer["tilemap"]]
    for key in ("spawn",):
        if isinstance(out.get(key), dict):
            for axis in ("x", "y"):
                if axis in out[key]:
                    out[key][axis] = clamp_float(out[key][axis], 0.0)
    for collection in ("spawns", "transitions", "objects"):
        if isinstance(out.get(collection), list):
            for item in out[collection]:
                if isinstance(item, dict):
                    for axis in ("x", "y", "half_w", "half_h"):
                        if axis in item:
                            item[axis] = clamp_float(item[axis], 0.0)
    return out


def strip_internal(entry: dict) -> dict:
    out = {}
    for key, value in entry.items():
        if key.startswith("_") or key == "url" or key == "actual_width" or \
                key == "actual_height":
            continue
        out[key] = value
    return out


SPECIES_KEY_ORDER = [
    "species", "flags", "variant", "frames", "duration", "states", "hurt",
    "default", "source",
]


def normalize_species_entry(key: str, entry: dict) -> dict:
    out: dict = {}
    for field in SPECIES_KEY_ORDER:
        if field in entry:
            out[field] = entry[field]
    for field, value in entry.items():
        if field not in out and not field.startswith("_") and field not in (
                "url", "actual_width", "actual_height"):
            out[field] = value
    out["species"] = clamp_int(out.get("species"), 0, 0, 65535)
    if out.get("variant") in ("", None):
        out.pop("variant", None)
    if out.get("variant") == "boss":
        out["flags"] = clamp_int(out.get("flags"), 0, 0, 255)
    elif "flags" in out and not out["flags"]:
        out.pop("flags", None)
    frames = []
    for frame in out.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        clean = {"texture": str(frame.get("texture", ""))}
        for field in ("anchor_x", "anchor_y", "duration", "width", "height"):
            if field in frame:
                clean[field] = clamp_int(frame[field], 0) if field in (
                    "duration", "width", "height") else clamp_float(frame[field], 0.0)
        frames.append(clean)
    out["frames"] = frames
    states = out.get("states")
    if isinstance(states, dict):
        clean_states = {}
        for state_key, seq in states.items():
            try:
                state_id = int(state_key)
            except (TypeError, ValueError):
                continue
            if not (0 <= state_id < MAX_SPECIES_STATES) or \
                    not isinstance(seq, list):
                continue
            clean_states[str(state_id)] = [clamp_int(v, 0)
                                           for v in seq[:MAX_STATE_FRAMES]]
        if clean_states:
            out["states"] = clean_states
        else:
            out.pop("states", None)
    else:
        out.pop("states", None)
    for field in ("hurt", "default"):
        if field in out:
            out[field] = clamp_int(out[field], 0)
    if not out.get("source"):
        out["source"] = f"edited species {key}"
    return out


def normalize_enemy_def(definition: dict) -> dict:
    out = {
        "key": str(definition.get("key") or "")[:24],
        "species": clamp_int(definition.get("species"), 0, 0, 65535),
        "flags": clamp_int(definition.get("flags"), 0, 0, 255),
        "variant": str(definition.get("variant") or "")[:16],
        "name": str(definition.get("name") or "").strip()[:64],
        "status": {
            "hp": clamp_int((definition.get("status") or {}).get("hp"), 2,
                            1, 255),
            "contact_damage": clamp_int(
                (definition.get("status") or {}).get("contact_damage"), 1,
                0, 9),
            "defense": clamp_int((definition.get("status") or {}).get(
                "defense"), 0, 0, 9),
            "invulnerable": bool((definition.get("status") or {}).get(
                "invulnerable")),
        },
        "movement": {
            "ai": (definition.get("movement") or {}).get("ai")
            if (definition.get("movement") or {}).get("ai") in AI_KINDS
            else "walker",
            "speed": round(clamp_float(
                (definition.get("movement") or {}).get("speed"), 0.5, 0, 8),
                3),
            "range": clamp_int((definition.get("movement") or {}).get(
                "range"), 160, 0, 4096),
            "bob": clamp_int((definition.get("movement") or {}).get("bob"),
                             0, -128, 128),
            "gravity": bool((definition.get("movement") or {}).get(
                "gravity", True)),
            "override_ai": bool((definition.get("movement") or {}).get(
                "override_ai", False)),
        },
        "attacks": [],
        "sounds": {},
    }
    for attack in (definition.get("attacks") or [])[:8]:
        if not isinstance(attack, dict):
            continue
        kind = attack.get("type") if attack.get("type") in ATTACK_TYPES \
            else "projectile"
        out["attacks"].append({
            "type": kind,
            "cooldown": clamp_int(attack.get("cooldown"), 90, 1, 3600),
            "range": clamp_int(attack.get("range"), 160, 0, 4096),
            "count": clamp_int(attack.get("count"), 1, 1, 8),
            "spread": clamp_int(attack.get("spread"), 0, 0, 90),
            "speed": round(clamp_float(attack.get("speed"), 1.5, 0.1, 8), 3),
            "damage": clamp_int(attack.get("damage"), 1, 0, 9),
            "species": clamp_int(attack.get("species"), 0x67, 0, 65535),
            "aim": attack.get("aim") if attack.get("aim") in (
                "player", "facing", "up", "down") else "player",
            "sfx": attack.get("sfx") if attack.get("sfx") in SFX_NAMES else "",
            "telegraph": clamp_int(attack.get("telegraph"), 12, 0, 120),
        })
    sounds = definition.get("sounds") or {}
    if isinstance(sounds, dict):
        for slot in ("spawn", "attack", "hurt", "death"):
            value = sounds.get(slot)
            if value in SFX_NAMES:
                out["sounds"][slot] = value
    return out
