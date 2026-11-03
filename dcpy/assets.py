"""Asset loading (port of assets.c).

Reads the same ROM-derived `assets/generated` tree the C port uses.
"""

from __future__ import annotations

import os

from . import rl
from .anim import (PlayerAnim, ProjectileAnim, anim_load, anim_load_forms,
                   projectile_anim_load)
from .consts import DC_CAMPAIGN_AREAS
from .util import as_float, as_int, eprint, file_exists, read_json

DC_BG_PALETTES = 8
DC_OBJ_PALETTES = 8
DC_SPECIES_MAX = 64
DC_SPECIES_FRAMES = 10
DC_SPECIES_STATES = 16
DC_STATE_FRAMES = 8
DC_SPECIES_PARTS = 8
DC_ENDING_VARIANTS = 4
DC_ENDING_MAX_LINES = 12


class SpeciesFrame:
    __slots__ = ("texture", "flipped", "anchor_x", "anchor_y", "duration")

    def __init__(self):
        self.texture = rl.Texture2D()
        self.flipped = rl.Texture2D()
        self.anchor_x = 0
        self.anchor_y = 0
        self.duration = 6


class SpeciesPart:
    __slots__ = ("texture", "flipped", "dx", "dy")

    def __init__(self):
        self.texture = rl.Texture2D()
        self.flipped = rl.Texture2D()
        self.dx = 0
        self.dy = 0


class SpeciesPartState:
    __slots__ = ("present", "legs", "body", "head")

    def __init__(self):
        self.present = False
        self.legs = True
        self.body = -1
        self.head = -1


class SpeciesParts:
    __slots__ = ("enabled", "names", "parts", "states")

    def __init__(self):
        self.enabled = False
        self.names: list[str] = []
        self.parts: list[SpeciesPart] = []
        self.states = [SpeciesPartState() for _ in range(DC_SPECIES_STATES)]


class SpeciesSheet:
    __slots__ = ("species", "flags", "frames", "duration", "has_states",
                 "states", "hurt_frame", "has_hurt", "default_frame",
                 "has_default", "parts")

    def __init__(self):
        self.species = -1
        self.flags = 0
        self.frames: list[SpeciesFrame] = []
        self.duration = 6
        self.has_states = False
        self.states: list[list[int]] = [[] for _ in range(DC_SPECIES_STATES)]
        self.hurt_frame = 0
        self.has_hurt = False
        self.default_frame = 0
        self.has_default = False
        self.parts = SpeciesParts()


class Assets:
    def __init__(self):
        self.bg_pal: list = []
        # Fixed 8 slots: palettes are indexed by the tile word, so appending
        # would place palette 2 in slot 1 when palette 1 is absent.
        self.bg_area: list = [rl.Texture2D() for _ in range(DC_BG_PALETTES)]
        self.bg2_area: list = [rl.Texture2D() for _ in range(DC_BG_PALETTES)]
        self.backdrop = rl.Texture2D()
        self.backdrop_w = 0
        self.backdrop_h = 0
        self.bg_area_ready = False
        self.bg_area_id = -1
        self.asset_dir = ""
        self.obj_pal: list = []
        self.player = rl.Texture2D()
        self.player_flipped = rl.Texture2D()
        self.item = rl.Texture2D()
        self.heart = rl.Texture2D()
        self.enemy: list = []
        self.enemy_frames = 0
        self.species: list[SpeciesSheet] = []
        self.species_count = 0
        self.boss_sheets: list[SpeciesSheet] = []
        self.boss_sheet_count = 0
        self.endings = {"title": [""] * DC_ENDING_VARIANTS,
                        "lines": [[] for _ in range(DC_ENDING_VARIANTS)],
                        "epilogue": [-1] * DC_ENDING_VARIANTS,
                        "loaded": False}
        self.room_kind = [0] * DC_CAMPAIGN_AREAS
        self.stage_entries: list[int] = []
        self.hud_bar = rl.Texture2D()
        self.hud_slots = rl.Texture2D()
        self.font = rl.Texture2D()
        self.world_map = rl.Texture2D()
        self.room_names = [""] * 113
        self.room_levels = [""] * 113
        self.boss_fireball: list = []
        self.boss_flame: list = []
        self.map_markers: list[tuple[float, float]] = []
        self.player_anim = PlayerAnim()
        self.player_forms = [PlayerAnim() for _ in range(6)]
        self.player_form_count = 0
        self.projectile_anim = ProjectileAnim()
        self.ready = False


def _load_one(directory: str, name: str):
    path = os.path.join(directory, name)
    tex = rl.LoadTexture(os.fsencode(path))
    if not rl.IsTextureValid(tex):
        eprint(f"assets: failed to load {path}", flush=True)
        return None
    rl.SetTextureFilter(tex, 0)
    return tex


def _load_part_texture(part: SpeciesPart, directory: str, name: str) -> bool:
    tex = _load_one(directory, name)
    if tex is None:
        return False
    part.texture = tex
    part.flipped = rl.flip_texture(tex)
    return True


def species_part_index(parts: SpeciesParts, name: str) -> int:
    if parts is None or name is None:
        return -1
    try:
        return parts.names.index(name)
    except ValueError:
        return -1


def _load_species_parts(sheet: SpeciesSheet, entry: dict,
                        directory: str) -> None:
    parts = entry.get("parts")
    if not isinstance(parts, dict):
        return
    dst = sheet.parts
    for state in dst.states:
        state.present = False
        state.legs = True
        state.body = -1
        state.head = -1
    for key, part in parts.items():
        if key in ("states", "source"):
            continue
        if not isinstance(part, dict) or len(dst.parts) >= DC_SPECIES_PARTS:
            continue
        tex_name = part.get("texture")
        if not isinstance(tex_name, str):
            continue
        slot = SpeciesPart()
        if not _load_part_texture(slot, directory, tex_name):
            continue
        slot.dx = as_int(part.get("dx"), 0)
        slot.dy = as_int(part.get("dy"), 0)
        dst.names.append(key)
        dst.parts.append(slot)
    states = parts.get("states")
    if isinstance(states, dict):
        for key, st in states.items():
            if not isinstance(st, dict):
                continue
            try:
                idx = int(key)
            except ValueError:
                continue
            if idx < 0 or idx >= DC_SPECIES_STATES:
                continue
            sel = dst.states[idx]
            body = st.get("body")
            head = st.get("head")
            legs = st.get("legs")
            sel.body = species_part_index(dst, body) if isinstance(body, str) \
                else species_part_index(dst, "body")
            sel.head = species_part_index(dst, head) if isinstance(head, str) \
                else -1
            sel.legs = bool(legs) if isinstance(legs, bool) else True
            sel.present = sel.body >= 0 or sel.head >= 0 or sel.legs
    dst.enabled = len(dst.parts) > 0


def _load_species_sheets(assets: Assets, directory: str) -> None:
    path = os.path.join(directory, "species_anim.json")
    if not file_exists(path):
        return
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return
    # The shipped format (bake_enemy_sheets.py, extract_species.py, the C port)
    # is an object keyed by species hex: {"species": {"2c": {...}}}.  Accept the
    # legacy list form too; iterating a dict directly yields keys and silently
    # loaded zero sheets, which is why every enemy fell back to procedural art.
    raw = root.get("species")
    if isinstance(raw, dict):
        entries = list(raw.values())
    elif isinstance(raw, list):
        entries = raw
    else:
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        boss = entry.get("variant") == "boss"
        bucket = assets.boss_sheets if boss else assets.species
        if len(bucket) >= DC_SPECIES_MAX:
            continue
        frames = entry.get("frames")
        if not isinstance(frames, list):
            continue
        sheet = SpeciesSheet()
        sheet.species = as_int(entry.get("species"), -1)
        sheet.flags = as_int(entry.get("flags"), 0)
        sheet.duration = 6
        for frame in frames:
            if len(sheet.frames) >= DC_SPECIES_FRAMES:
                break
            tex_name = frame.get("texture") if isinstance(frame, dict) else None
            if not isinstance(tex_name, str):
                continue
            slot = SpeciesFrame()
            tex = _load_one(directory, tex_name)
            if tex is None:
                continue
            slot.texture = tex
            slot.flipped = rl.flip_texture(tex)
            slot.anchor_x = int(as_float(frame.get("anchor_x"), 0.0) + 0.5)
            slot.anchor_y = int(as_float(frame.get("anchor_y"), 0.0) + 0.5)
            slot.duration = as_int(frame.get("duration"), 6)
            if slot.duration < 1:
                slot.duration = 6
            sheet.duration = slot.duration
            sheet.frames.append(slot)
        states = entry.get("states")
        if isinstance(states, dict):
            for key, frame_list in states.items():
                if not isinstance(frame_list, list):
                    continue
                try:
                    idx = int(key)
                except ValueError:
                    continue
                if idx < 0 or idx >= DC_SPECIES_STATES:
                    continue
                sheet.states[idx] = [int(v) for v in frame_list
                                     if isinstance(v, (int, float))
                                     ][:DC_STATE_FRAMES]
                if sheet.states[idx]:
                    sheet.has_states = True
        hurt = entry.get("hurt")
        if isinstance(hurt, (int, float)):
            sheet.hurt_frame = int(hurt)
            sheet.has_hurt = True
        default = entry.get("default")
        if isinstance(default, (int, float)):
            sheet.default_frame = int(default)
            sheet.has_default = True
        if sheet.has_hurt and not (0 <= sheet.hurt_frame < len(sheet.frames)):
            sheet.has_hurt = False
        if sheet.has_default and \
                not (0 <= sheet.default_frame < len(sheet.frames)):
            sheet.has_default = False
        _load_species_parts(sheet, entry, directory)
        if sheet.frames:
            bucket.append(sheet)
    assets.species_count = len(assets.species)
    assets.boss_sheet_count = len(assets.boss_sheets)


def _load_room_kinds(assets: Assets, directory: str) -> None:
    path = os.path.join(directory, "campaign.json")
    if not file_exists(path):
        return
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return
    for entry in root.get("stage_entries") or []:
        if isinstance(entry, (int, float)) and len(assets.stage_entries) < 80:
            assets.stage_entries.append(int(entry))
    rooms = root.get("rooms")
    if isinstance(rooms, dict):
        for key, entry in rooms.items():
            if not isinstance(entry, dict):
                continue
            try:
                area = int(key)
            except ValueError:
                continue
            if area < 0 or area >= DC_CAMPAIGN_AREAS:
                continue
            kind = entry.get("kind")
            if kind == "playable":
                assets.room_kind[area] = 1
            elif kind == "partial":
                assets.room_kind[area] = 2
            elif kind == "empty":
                assets.room_kind[area] = 3


def _load_endings(assets: Assets, directory: str) -> None:
    path = os.path.join(directory, "endings.json")
    if not file_exists(path):
        return
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return
    endings = root.get("endings") or {}
    for i, key in enumerate(("bad", "normal", "good", "true")):
        entry = endings.get(key)
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if isinstance(title, str):
            assets.endings["title"][i] = title
        lines = []
        for line in entry.get("lines") or []:
            if isinstance(line, str) and len(lines) < DC_ENDING_MAX_LINES:
                lines.append(line)
        assets.endings["lines"][i] = lines
        epi = entry.get("epilogue")
        assets.endings["epilogue"][i] = int(epi) if isinstance(epi, (int, float)) else -1
    assets.endings["loaded"] = True


def _load_room_names(assets: Assets, directory: str) -> None:
    path = os.path.join(directory, "room_names.json")
    if not file_exists(path):
        return
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return
    if not isinstance(root, dict):
        return
    for key, entry in root.items():
        try:
            area = int(key)
        except ValueError:
            continue
        if area < 0 or area >= 113 or not isinstance(entry, dict):
            continue
        if isinstance(entry.get("map"), str):
            assets.room_names[area] = entry["map"]
        if isinstance(entry.get("level"), str):
            assets.room_levels[area] = entry["level"]


def _load_map_markers(assets: Assets, directory: str) -> None:
    path = os.path.join(directory, "map_markers.json")
    if not file_exists(path):
        return
    try:
        root = read_json(path)
    except (OSError, ValueError):
        return
    for item in root.get("all_positions") or []:
        if len(assets.map_markers) >= 64 or not isinstance(item, list) or \
                len(item) < 2:
            continue
        if isinstance(item[0], (int, float)) and isinstance(item[1], (int, float)):
            assets.map_markers.append((float(int(item[0]) * 4),
                                       float(int(item[1]) * 4)))


def assets_load(assets: Assets, directory: str) -> bool:
    assets.asset_dir = directory
    for i in range(DC_BG_PALETTES):
        tex = _load_one(directory, f"bg_pal{i}.png")
        if tex is None:
            return False
        assets.bg_pal.append(tex)
    for i in range(DC_OBJ_PALETTES):
        tex = _load_one(directory, f"obj_pal{i}.png")
        if tex is None:
            return False
        assets.obj_pal.append(tex)

    player = _load_one(directory, "player_idle.png")
    item = _load_one(directory, "item_00.png")
    if player is None or item is None:
        return False
    assets.player = player
    assets.item = item
    assets.player_flipped = rl.flip_texture(player)

    heart = _load_one(directory, "heart_00.png")
    if heart is None:
        eprint("assets: heart_00.png missing; using item sprite", flush=True)
        assets.heart = assets.item
    else:
        assets.heart = heart

    enemy0 = _load_one(directory, "enemy_00.png")
    if enemy0 is not None:
        assets.enemy.append(enemy0)
        assets.enemy_frames = 1
    enemy1 = _load_one(directory, "enemy_01.png")
    if enemy1 is not None:
        assets.enemy.append(enemy1)
        assets.enemy_frames = 2

    hud_bar = _load_one(directory, "hud_bar.png")
    hud_slots = _load_one(directory, "hud_slots.png")
    if hud_bar is None or hud_slots is None:
        eprint("assets: HUD elements missing; HUD disabled", flush=True)
    if hud_bar is not None:
        assets.hud_bar = hud_bar
    if hud_slots is not None:
        assets.hud_slots = hud_slots

    font = _load_one(directory, "font.png")
    if font is None:
        eprint("assets: font.png missing; dialogue text disabled", flush=True)
    else:
        assets.font = font

    assets.player_form_count = anim_load_forms(assets.player_forms, 6, directory)
    if assets.player_form_count > 0:
        print(f"assets: {assets.player_form_count} crest-form player sheet(s)",
              flush=True)
    if not anim_load(assets.player_anim, directory):
        eprint("assets: player_anim.json missing; using the static idle sprite",
              flush=True)
    if not projectile_anim_load(assets.projectile_anim, directory):
        eprint("assets: fireball_anim.json missing; projectiles render invisible",
              flush=True)

    _load_species_sheets(assets, directory)
    _load_room_kinds(assets, directory)
    _load_endings(assets, directory)

    for i in range(4):
        name = f"boss_fireball_{i}.png"
        if not file_exists(os.path.join(directory, name)):
            break
        tex = _load_one(directory, name)
        if tex is not None:
            assets.boss_fireball.append(tex)
    for i in range(8):
        name = f"boss_flame_{i}.png"
        if not file_exists(os.path.join(directory, name)):
            break
        tex = _load_one(directory, name)
        if tex is not None:
            assets.boss_flame.append(tex)

    _load_room_names(assets, directory)
    _load_map_markers(assets, directory)

    world_map_path = os.path.join(directory, "world_map.png")
    if file_exists(world_map_path):
        tex = rl.LoadTexture(os.fsencode(world_map_path))
        if rl.IsTextureValid(tex):
            # Mode 7 samples one texture row per screen row; with point
            # filtering a single dark row in the baked map shows up as a black
            # scanline across the plane.  The console blends in Mode 7, so the
            # map plane is the one texture that is filtered bilinearly.
            rl.SetTextureFilter(tex, 1)  # TEXTURE_FILTER_BILINEAR
            assets.world_map = tex

    if assets.species_count > 0:
        print(f"assets: {assets.species_count} per-species sprite sheet(s)",
              flush=True)
    assets.ready = True
    return True


def assets_has_area_bg2(assets: Assets) -> bool:
    return any(rl.IsTextureValid(tex) for tex in assets.bg2_area)


def assets_area_bg2(assets: Assets, pal: int):
    if pal < 0 or pal >= DC_BG_PALETTES or pal >= len(assets.bg2_area):
        return rl.Texture2D()
    return assets.bg2_area[pal]


def assets_area_bg(assets: Assets, area: int, pal: int):
    if pal < 0 or pal >= DC_BG_PALETTES or pal >= len(assets.bg_area):
        return assets.bg_pal[0]
    if rl.IsTextureValid(assets.bg_area[pal]):
        return assets.bg_area[pal]
    return assets.bg_pal[pal]


def assets_load_area_bg(assets: Assets, area: int) -> None:
    if area == assets.bg_area_id:
        return
    if assets.bg_area_ready:
        for p in range(DC_BG_PALETTES):
            if p < len(assets.bg_area) and rl.IsTextureValid(assets.bg_area[p]):
                rl.UnloadTexture(assets.bg_area[p])
            if p < len(assets.bg2_area) and rl.IsTextureValid(assets.bg2_area[p]):
                rl.UnloadTexture(assets.bg2_area[p])
        assets.bg_area = [rl.Texture2D() for _ in range(DC_BG_PALETTES)]
        assets.bg2_area = [rl.Texture2D() for _ in range(DC_BG_PALETTES)]
        assets.bg_area_ready = False
        if rl.IsTextureValid(assets.backdrop):
            rl.UnloadTexture(assets.backdrop)
        assets.backdrop = rl.Texture2D()

    assets.bg_area_id = area
    backdrop = _load_one(assets.asset_dir, f"bg_backdrop_area{area}.png")
    if backdrop is not None:
        assets.backdrop = backdrop
        assets.backdrop_w = backdrop.width
        assets.backdrop_h = backdrop.height

    any_bg = False
    for p in range(DC_BG_PALETTES):
        name = f"bg_area{area}_pal{p}.png"
        if not file_exists(os.path.join(assets.asset_dir, name)):
            continue
        tex = _load_one(assets.asset_dir, name)
        if tex is None:
            continue
        assets.bg_area[p] = tex
        any_bg = True
    for p in range(DC_BG_PALETTES):
        name = f"bg2_area{area}_pal{p}.png"
        if not file_exists(os.path.join(assets.asset_dir, name)):
            continue
        tex = _load_one(assets.asset_dir, name)
        if tex is None:
            continue
        assets.bg2_area[p] = tex
        any_bg = True
    assets.bg_area_ready = any_bg
    if not any_bg:
        assets.bg_area_id = -1


def assets_player_anim_for_form(assets: Assets, form: int):
    use_forms = assets.__dict__.get("_use_forms")
    if use_forms is None:
        use_forms = os.environ.get("DC_PLAYER_FORMS") != "0"
        assets._use_forms = use_forms
    if use_forms and 0 <= form < 6 and assets.player_forms[form].ready:
        return assets.player_forms[form]
    return assets.player_anim


def assets_species_sheet(assets: Assets, species: int):
    for sheet in assets.species:
        if sheet.species == species:
            return sheet
    return None


def assets_boss_sheet(assets: Assets, species: int, flags: int):
    fallback = None
    for sheet in assets.boss_sheets:
        if sheet.species != species:
            continue
        if sheet.flags == flags:
            return sheet
        if sheet.flags == 0:
            fallback = sheet
    return fallback


def assets_room_kind(assets: Assets, area: int) -> int:
    if area < 0 or area >= DC_CAMPAIGN_AREAS:
        return 0
    return assets.room_kind[area]
