"""Game state machine, menus and overlays (port of game.c)."""

from __future__ import annotations

import json
import math
import os

from . import rl
from . import consts as C
from .consts import LEVEL_OBJECT_EXIT
from .assets import (assets_load, assets_load_area_bg, assets_player_anim_for_form,
                     assets_room_kind)
from .audio import (audio_get_volume, audio_init, audio_play, audio_set_track,
                    audio_set_volume, audio_shutdown, audio_start_music,
                    audio_update)
from .camera import GameCamera, camera_focus, camera_init, camera_update
from .input import Input, InputState, input_read
from .level import level_load, level_load_area, level_unload
from .object import ObjectPool, objects_check_projectiles, objects_init, \
    objects_update
from .player import (Player, player_animate, player_cycle_form, player_form_name,
                     player_init, player_update)
from .projectile import (ProjectilePool, projectiles_init, projectiles_spawn,
                         projectiles_update)
from .render import render_draw_fade, render_game, render_set_fade
from .text import (TextScript, text_draw_page, text_draw_string, text_find,
                   text_load_script)
from .util import eprint, env, env_float, env_int, lround, read_json

DC_SAVE_VERSION = 2
DC_PASSWORD_LEN = 10
DC_PASSWORD_ALPHABET = "BCDFGHJKLMNPQRSTVWXYZ"

CAMPAIGN_COLOSSEUM = 0
CAMPAIGN_GRAVEYARD = 1
CAMPAIGN_CATACOMBS = 2
CAMPAIGN_RUINS = 3
CAMPAIGN_LAKE = 4
CAMPAIGN_DEMON_KEEP = 5

_FIRE_NAMES = ["FIREBALL", "BUSTER", "TORNADO", "CLAW", "DEMON FIRE"]
_TALISMAN_NAMES = ["CROWN", "SKULL", "ARMOR", "FANG", "HAND"]

_FADE_OUT = [14, 13, 13, 12, 12, 11, 11, 10, 10, 9, 9, 8, 8, 7,
             7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0]
_FADE_IN = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 7,
            8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14]
DC_FADE_OUT_FRAMES = 28
DC_FADE_BLACK_FRAMES = 64
DC_FADE_IN_FRAMES = 28

_SHOP_STOCK = [
    ("MERCURY", 6, 0),
    ("SULFUR", 10, 0),
    ("HERB", 25, 1),
    ("ELIXIR", 100, 2),
    ("GINSENG", 140, 3),
]
SHOP_STOCK_COUNT = len(_SHOP_STOCK)


class Game:
    def __init__(self):
        self.assets = None
        self.level = None
        self.player = Player()
        self.projectiles = ProjectilePool()
        self.objects = ObjectPool()
        self.camera = GameCamera()
        self.input = Input()
        self.input_state = InputState()
        self.target = rl.RenderTexture2D()
        self.trace = None
        self.projectile_trace = None
        self.object_trace = None
        self.asset_dir = ""
        self.frame = 0
        self.state_timer = 0
        self.state = C.GAME_TITLE
        self.menu_cursor = 0
        self.subscreen_row = 0
        self.overworld_node = 0
        self.stage_select = False
        self.stage_sel = 0
        self.pause_flash = 0
        self.intro_timer = 0
        self.boss_intro = 0
        self.boss_intro_timer = 0
        self.shake = 0
        self.shake_phase = 0
        self.restart_timer = 0
        self.transition_phase = 0
        self.transition_timer = 0
        self.transition_area = 0
        self.transition_spawn = 0
        self.talisman_toast = 0
        self.talisman_toast_index = 0
        self.attract = False
        self.attract_frame = 0
        self.overworld_x = 0.0
        self.overworld_y = 0.0
        self.overworld_angle = 0.0
        self.overworld_zoom = 1.0
        self.stages_cleared = 0
        self.area_cleared = bytearray(C.DC_CAMPAIGN_AREAS)
        self.password_code = ""
        self.password_entry = ""
        self.password_pos = 0
        self.password_status = 0
        self.campaign_mode = False
        self.script = TextScript()
        self.shop_welcome = -1
        self.shop_full_urn = -1
        self.shop_full_vellum = -1
        self.shop_message = -1
        self.ending_text = -1
        self.ending_variant = 0
        self.ending_phase = 0
        self.ending_page = 0
        self.dialogue_text = -1
        self.dialogue_page = 0
        self.dialogue_return = C.GAME_TITLE
        self.crest_text = [-1] * 6
        self.town_greet = -1
        self.town_question = -1
        self.town_story = [-1] * 5
        self.talk_seq = [-1] * 10
        self.talk_len = 0
        self.talk_pos = 0
        self.talk_choice = 0
        self.talk_choice_sel = 0
        self.fire_text = [-1] * 5
        self.shop_timer = 0
        self.shop_sel = 0
        self.shop_no_money = -1
        self.shop_need_vellum = -1
        self.dialogue_demo = False
        self.script_ready = False
        self.has_save = False
        self.prev_up = False
        self.prev_down = False
        self.prev_left = False
        self.prev_right = False
        self.ready = False


# --- helpers ---------------------------------------------------------------

def game_reset(game: Game) -> None:
    game.intro_timer = 110
    player_init(game.player, game.level)
    projectiles_init(game.projectiles)
    objects_init(game.objects, game.level)
    camera_init(game.camera, game.level)
    game.objects.boss_alive = False
    game.objects.boss_defeated = False
    game.transition_phase = 0
    game.transition_timer = 0
    render_set_fade(0.0)
    if "DC_BOSS_CLEAR" in os.environ:
        game.objects.boss_alive = False
        game.objects.boss_defeated = True
    game.state_timer = 0


def game_transition_to_area(game: Game, area_id: int, spawn_id: int) -> bool:
    if area_id < 0 or area_id >= C.DC_CAMPAIGN_AREAS:
        return False
    if assets_room_kind(game.assets, area_id) == 3:
        eprint(f"game: refusing empty room {area_id}", flush=True)
        return False
    # C copies the Player struct by value; Python must snapshot the fields
    # before Player_Init overwrites the live object, or the carried progress
    # becomes the fresh spawn kit (6 max HP / 4 HP).
    saved = {field: getattr(game.player, field) for field in (
        "max_hp", "hp", "crests_mask", "crest_form", "talisman_mask",
        "active_talisman", "potions", "scrolls", "gold")}
    prev_area = game.level.area_id
    if not level_load_area(game.level, game.assets, game.asset_dir, area_id):
        level_load_area(game.level, game.assets, game.asset_dir, prev_area)
        assets_load_area_bg(game.assets, game.level.area_id)
        return False
    assets_load_area_bg(game.assets, game.level.area_id)
    player_init(game.player, game.level)
    game.intro_timer = 110
    if "DC_BOSS_CLEAR" in os.environ:
        game.objects.boss_alive = False
        game.objects.boss_defeated = True
    p = game.player
    p.max_hp = saved["max_hp"] if saved["max_hp"] > 0 else 6
    p.hp = saved["hp"] if saved["hp"] > 0 else p.max_hp
    p.crests_mask = saved["crests_mask"]
    p.crest_form = saved["crest_form"]
    p.talisman_mask = saved["talisman_mask"]
    p.active_talisman = saved["active_talisman"]
    p.potions = saved["potions"]
    p.scrolls = saved["scrolls"]
    p.gold = saved["gold"]
    if len(game.level.spawns) > 1 and 0 < spawn_id < len(game.level.spawns):
        sp = game.level.spawns[spawn_id]
        p.x_fx = lround(sp.x * 256.0)
        p.y_fx = lround(sp.y * 256.0)
        p.x = sp.x
        p.y = sp.y
    projectiles_init(game.projectiles)
    objects_init(game.objects, game.level)
    camera_init(game.camera, game.level)
    game.objects.boss_alive = False
    game.objects.boss_defeated = False
    game.state = C.GAME_PLAYING
    game.state_timer = 0
    return True


_fade_trace = [None, False]


def _game_trace_fade(game: Game, fade: float) -> None:
    if not _fade_trace[1]:
        _fade_trace[1] = True
        path = env("DC_TRACE_FADE")
        if path:
            _fade_trace[0] = open(path, "w")
            _fade_trace[0].write("frame,phase,timer,fade,area\n")
    handle = _fade_trace[0]
    if not handle:
        return
    handle.write(f"{game.frame},{game.transition_phase},"
                 f"{game.transition_timer},{lround(fade * 15.0)},"
                 f"{game.level.area_id}\n")
    handle.flush()


def game_begin_transition(game: Game, area_id: int, spawn_id: int) -> None:
    if game.transition_phase != 0:
        return
    if game.restart_timer > 0:
        return
    if area_id < 0 or area_id >= C.DC_CAMPAIGN_AREAS or \
            area_id == game.level.area_id:
        return
    game.transition_phase = 1
    game.transition_timer = 0
    game.transition_area = area_id
    game.transition_spawn = spawn_id


def game_update_transition(game: Game) -> bool:
    if game.transition_phase == 0:
        return False
    if game.transition_phase == 1:
        render_set_fade(_FADE_OUT[game.transition_timer] / 15.0)
        _game_trace_fade(game, _FADE_OUT[game.transition_timer] / 15.0)
        game.transition_timer += 1
        if game.transition_timer >= DC_FADE_OUT_FRAMES:
            game.transition_phase = 2
            game.transition_timer = 0
            game_transition_to_area(game, game.transition_area,
                                    game.transition_spawn)
            render_set_fade(1.0)
    elif game.transition_phase == 2:
        render_set_fade(1.0)
        _game_trace_fade(game, 1.0)
        game.transition_timer += 1
        if game.transition_timer >= DC_FADE_BLACK_FRAMES:
            game.transition_phase = 3
            game.transition_timer = 0
    elif game.transition_phase == 3:
        render_set_fade(_FADE_IN[game.transition_timer] / 15.0)
        _game_trace_fade(game, _FADE_IN[game.transition_timer] / 15.0)
        game.transition_timer += 1
        if game.transition_timer >= DC_FADE_IN_FRAMES:
            game.transition_phase = 0
            game.transition_timer = 0
            render_set_fade(0.0)
            _game_trace_fade(game, 0.0)
    else:
        game.transition_phase = 0
        render_set_fade(0.0)
        return False
    game.frame += 1
    return True


def _password_checksum(payload: int) -> int:
    h = 2166136261
    for i in range(4):
        h ^= (payload >> (i * 8)) & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h & 0xFF


def game_password_encode(payload: int) -> str:
    value = (payload & 0xFFFFFFFF) | (_password_checksum(payload) << 32)
    out = ["B"] * DC_PASSWORD_LEN
    for i in range(DC_PASSWORD_LEN - 1, -1, -1):
        out[i] = DC_PASSWORD_ALPHABET[value % 20]
        value //= 20
    return "".join(out)


def game_password_decode(code: str):
    value = 0
    n = 0
    for ch in code:
        if n >= DC_PASSWORD_LEN:
            break
        index = DC_PASSWORD_ALPHABET.find(ch)
        if index < 0:
            return None
        value = value * 20 + index
        n += 1
    if n != DC_PASSWORD_LEN:
        return None
    payload = value & 0xFFFFFFFF
    if ((value >> 32) & 0xFF) != _password_checksum(payload):
        return None
    return payload


def _clamp(value: int, lo: int, hi: int) -> int:
    return lo if value < lo else (hi if value > hi else value)


def game_password_payload(game: Game) -> int:
    p = game.player
    v = game.stages_cleared & 0xFF
    v |= _clamp(p.max_hp, 1, 15) << 8
    v |= (p.crests_mask & 0x3F) << 12
    v |= _clamp(p.crest_form, 0, 7) << 18
    v |= _clamp(p.potions, 0, 7) << 21
    v |= _clamp(p.scrolls, 0, 7) << 24
    v |= (p.talisman_mask & 0x1F) << 27
    return v


def game_apply_password(game: Game, code: str) -> bool:
    payload = game_password_decode(code)
    if payload is None:
        return False
    p = game.player
    game.stages_cleared = payload & 0xFF
    p.max_hp = _clamp((payload >> 8) & 0xF, 1, 15)
    p.hp = p.max_hp
    p.crests_mask = (payload >> 12) & 0x3F
    p.crest_form = (payload >> 18) & 0x7
    if p.crest_form >= C.CREST_COUNT:
        p.crest_form = C.CREST_BASE
    p.potions = (payload >> 21) & 0x7
    p.scrolls = (payload >> 24) & 0x7
    p.talisman_mask = (payload >> 27) & 0x1F
    if not (p.talisman_mask & (1 << p.active_talisman)):
        p.active_talisman = 0
    return True


def game_encode_password(game: Game) -> str:
    return game_password_encode(game_password_payload(game))


def game_password_selftest() -> bool:
    state = 0x12345678
    for i in range(2000):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        payload = state
        code = game_password_encode(payload)
        if game_password_decode(code) != payload:
            eprint(f"password selftest: FAIL at {i} ({code})", flush=True)
            return False
    eprint("password selftest: OK (2000 round-trips)", flush=True)
    return True


def _save_path() -> str:
    return env("DC_SAVE_PATH") or "saves/dc_save.json"


def _save_disabled() -> bool:
    if "DC_NO_SAVE" in os.environ:
        return True
    if "DC_RUN_FRAMES" in os.environ and "DC_SAVE_FORCE" not in os.environ:
        return True
    return False


def game_has_save() -> bool:
    if _save_disabled():
        return False
    return os.path.isfile(_save_path())


def game_save_progress(game: Game) -> bool:
    if _save_disabled() or not game.campaign_mode:
        return False
    p = game.player
    data = {
        "version": DC_SAVE_VERSION,
        "area": game.level.area_id,
        "stages_cleared": game.stages_cleared,
        "area_cleared": bytes(game.area_cleared).hex(),
        "max_hp": p.max_hp,
        "hp": p.hp,
        "crests": p.crests_mask,
        "form": p.crest_form,
        "talismans": p.talisman_mask,
        "talisman": p.active_talisman,
        "fire_element": p.fire_element,
        "potions": p.potions,
        "scrolls": p.scrolls,
        "gold": p.gold,
        "volume": audio_get_volume(),
    }
    path = _save_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "w") as handle:
            json.dump(data, handle, indent=1)
    except OSError:
        eprint(f"game: cannot write save {path}", flush=True)
        return False
    return True


def game_load_progress(game: Game) -> bool:
    if _save_disabled():
        return False
    path = _save_path()
    try:
        with open(path, "rb") as handle:
            raw = handle.read(65537)
        if not raw or len(raw) > 65536:
            return False
        root = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return False
    if root.get("version") != DC_SAVE_VERSION:
        return False
    area = root.get("area", game.level.area_id)
    if isinstance(area, (int, float)) and 0 <= area < C.DC_CAMPAIGN_AREAS \
            and area != game.level.area_id:
        game_transition_to_area(game, int(area), 0)
    p = game.player
    p.max_hp = _as_int(root.get("max_hp"), p.max_hp)
    if p.max_hp < 1:
        p.max_hp = 6
    if p.max_hp > 12:
        p.max_hp = 12
    p.hp = _as_int(root.get("hp"), p.max_hp)
    if p.hp < 1:
        p.hp = 1
    if p.hp > p.max_hp:
        p.hp = p.max_hp
    p.crests_mask = _as_int(root.get("crests"), p.crests_mask) & 0xFF
    form = _as_int(root.get("form"), p.crest_form)
    p.crest_form = form if 0 <= form < C.CREST_COUNT else C.CREST_BASE
    p.talisman_mask = _as_int(root.get("talismans"), p.talisman_mask) & 0xFF
    talisman = _as_int(root.get("talisman"), p.active_talisman)
    p.active_talisman = talisman if 0 <= talisman < 5 else 0
    p.fire_element = _as_int(root.get("fire_element"), p.fire_element) % 5
    p.potions = _as_int(root.get("potions"), p.potions)
    p.scrolls = _as_int(root.get("scrolls"), p.scrolls)
    p.gold = _as_int(root.get("gold"), p.gold)
    game.stages_cleared = _as_int(root.get("stages_cleared"),
                                  game.stages_cleared) & 0xFF
    cleared = root.get("area_cleared")
    if isinstance(cleared, str):
        for i in range(C.DC_CAMPAIGN_AREAS):
            byte = cleared[i * 2:i * 2 + 2]
            if len(byte) < 2:
                break
            try:
                game.area_cleared[i] = int(byte, 16)
            except ValueError:
                break
    volume = root.get("volume")
    if isinstance(volume, (int, float)):
        audio_set_volume(float(volume))
    game.has_save = True
    return True


def _as_int(value, fallback: int) -> int:
    return int(value) if isinstance(value, (int, float)) else fallback


def game_init(game: Game, asset_dir: str) -> bool:
    from .assets import Assets
    from .level import Level

    game.asset_dir = asset_dir
    game.assets = Assets()
    game.level = Level()
    if not assets_load(game.assets, asset_dir):
        eprint("game: asset load failed (run tools/dc_extract first)", flush=True)
        return False
    if not level_load(game.level, game.assets, asset_dir):
        return False
    assets_load_area_bg(game.assets, game.level.area_id)
    player_init(game.player, game.level)
    game.intro_timer = 110
    projectiles_init(game.projectiles)
    objects_init(game.objects, game.level)
    camera_init(game.camera, game.level)
    game.target = rl.LoadRenderTexture(256, 224)
    if not rl.IsRenderTextureValid(game.target):
        eprint("game: failed to create 256x224 render target", flush=True)
        return False
    rl.SetTextureFilter(game.target.texture, 0)

    trace_path = env("DC_TRACE_CSV")
    if trace_path:
        try:
            game.trace = open(trace_path, "w")
            game.trace.write("frame,player_x,player_y,vx,vy,state,camera_x,"
                             "camera_y,hp,max_hp,area,form,gold,fire,mode\n")
        except OSError:
            eprint(f"game: cannot open trace file {trace_path}", flush=True)

    proj_trace_path = env("DC_TRACE_PROJECTILES")
    if proj_trace_path:
        try:
            game.projectile_trace = open(proj_trace_path, "w")
            game.projectile_trace.write("frame,slot,x,y,vx,age\n")
        except OSError:
            eprint(f"game: cannot open projectile trace {proj_trace_path}",
                  flush=True)

    object_trace_path = env("DC_TRACE_OBJECTS")
    if object_trace_path:
        try:
            game.object_trace = open(object_trace_path, "w")
            game.object_trace.write("frame,slot,type,x,y,vx,vy,state,hp,flash,"
                                    "species,flags\n")
        except OSError:
            eprint(f"game: cannot open object trace {object_trace_path}",
                  flush=True)

    game.ready = True
    game.has_save = game_has_save()
    if text_load_script(game.script, asset_dir):
        game.script_ready = True
        game.shop_welcome = text_find(game.script, "BLACK LOTUS")
        game.shop_full_urn = text_find(game.script, "NEED AN URN")
        game.shop_full_vellum = text_find(game.script, "VELLUM IS")
        game.shop_no_money = text_find(game.script, "CHEAPSKATE")
        game.shop_need_vellum = text_find(game.script, "VELLUM FIRST")
        game.ending_text = text_find(game.script, "PHALANX WOULD")
        game.town_greet = text_find(game.script, "HAVEN'T SEEN YOU")
        game.town_question = text_find(game.script, "ARE YOU A STRANGER")
        game.town_story[0] = text_find(game.script, "FIREBRAND HAS RISEN")
        game.town_story[1] = text_find(game.script, "BURNT THE DEMON REALM")
        game.town_story[2] = text_find(game.script, "RESCUED US")
        game.town_story[3] = text_find(game.script, "ARROGANT FOOL")
        game.town_story[4] = text_find(game.script,
                                       "ESCAPED FROM THE COLOSSEUM")
        game.crest_text[C.CREST_EARTH] = text_find(game.script,
                                                   'CREST OF "EARTH"')
        game.crest_text[C.CREST_AIR] = text_find(game.script, 'CREST OF "AIR"')
        game.crest_text[C.CREST_WATER] = text_find(game.script,
                                                   'CREST OF "WATER"')
        game.crest_text[C.CREST_TIME] = text_find(game.script,
                                                  'CREST OF "TIME"')
        game.fire_text[1] = text_find(game.script, '"BUSTER"')
        game.fire_text[2] = text_find(game.script, '"TORNADO"')
        game.fire_text[3] = text_find(game.script, '"CLAW"')
        game.fire_text[4] = text_find(game.script, '"DEMON FIRE"')
        game.dialogue_demo = "DC_DIALOGUE" in os.environ

    password_env = env("DC_PASSWORD")
    if password_env:
        if game_apply_password(game, password_env):
            game.campaign_mode = True
            eprint("game: password applied", flush=True)
        else:
            eprint("game: invalid DC_PASSWORD", flush=True)

    demo = env("DC_DEMO")
    force_title = "DC_TITLE" in os.environ
    automated = not force_title and ("DC_RUN_FRAMES" in os.environ or
                                     (demo and demo != "0"))
    game.state = C.GAME_PLAYING if automated else C.GAME_TITLE
    if "DC_CAMPAIGN" in os.environ:
        game.campaign_mode = True
    state_env = env("DC_STATE")
    if state_env:
        if state_env == "title":
            game.state = C.GAME_TITLE
        elif state_env == "overworld":
            game.campaign_mode = True
            game_open_overworld(game)
        elif state_env == "subscreen":
            game.state = C.GAME_SUBSCREEN
        elif state_env == "pause":
            game.state = C.GAME_PAUSED
        elif state_env == "shop":
            game.state = C.GAME_SHOP
        elif state_env == "password":
            game.state = C.GAME_PASSWORD
        elif state_env == "options":
            game.state = C.GAME_OPTIONS
        elif state_env == "clear":
            game.campaign_mode = True
            game_complete_area(game)
        elif state_env == "gameover":
            game.state = C.GAME_OVER
        elif state_env == "ending":
            game_start_ending(game)
    game.state_timer = 0

    if "DC_STAGE_SELECT" in os.environ:
        game.stage_select = True
    stage_sel_env = env("DC_STAGE_INDEX")
    if stage_sel_env:
        game.stage_sel = int(stage_sel_env)

    fire_test = env("DC_FIRE_TEST")
    if fire_test and game.script_ready:
        piece = int(fire_test)
        if 1 <= piece <= 4 and game.fire_text[piece] >= 0:
            game.dialogue_text = game.fire_text[piece]
            page = env("DC_STORY_PAGE")
            game.dialogue_page = int(page) if page else 0
            game.dialogue_return = C.GAME_TITLE
            game.state = C.GAME_DIALOGUE

    gold = env("DC_GOLD")
    if gold:
        game.player.gold = int(gold)

    talk = env("DC_TALK")
    if talk and game.script_ready:
        game_start_town_talk(game)
        for _ in range(int(talk)):
            if game.talk_choice == 1:
                story = [game.town_story[0], game.town_story[1],
                         game.town_story[2], game.town_story[3], -1, -1]
                for index in story:
                    if index >= 0 and game.talk_len < 10:
                        game.talk_seq[game.talk_len] = index
                        game.talk_len += 1
                game.talk_choice = 0
            if game.talk_pos + 1 < game.talk_len:
                game.talk_pos += 1
                game.dialogue_text = game.talk_seq[game.talk_pos]
                game.dialogue_page = 0
            if game.dialogue_text == game.town_question and \
                    game.talk_pos + 1 >= game.talk_len:
                game.talk_choice = 1

    story_test = env("DC_STORY_TEST")
    if "DC_STORY_DEBUG" in os.environ:
        eprint(f"story: ready={1 if game.script_ready else 0} "
              f"crest_text={game.crest_text}", flush=True)
    if story_test and game.script_ready:
        crest = int(story_test)
        if 0 <= crest < C.CREST_COUNT and game.crest_text[crest] >= 0:
            game.dialogue_text = game.crest_text[crest]
            page = env("DC_STORY_PAGE")
            game.dialogue_page = int(page) if page else 0
            game.dialogue_return = C.GAME_TITLE
            game.state = C.GAME_DIALOGUE

    audio_init(game.asset_dir)
    if "DC_RESUME" in os.environ and game.has_save:
        if game_load_progress(game):
            game.campaign_mode = True
            game.state = C.GAME_PLAYING
            game.state_timer = 0
    audio_start_music()
    return True


def game_narrative_enabled() -> bool:
    return "DC_RUN_FRAMES" not in os.environ and "DC_NO_STORY" not in os.environ


def game_update_simulation(game: Game) -> None:
    game.objects.events = 0
    game.objects.last_fire_piece = 0
    player_update(game.player, game.level, game.input)
    if game.player.jump_started:
        audio_play(C.SFX_JUMP)
    if game.player.landed_event:
        audio_play(C.SFX_LAND)

    shot = game.player.shot_fired
    projectiles_update(game.projectiles, game.level, game.camera)
    if shot:
        projectiles_spawn(game.projectiles, game.player)
        game.player.shot_fired = False
        audio_play(C.SFX_SHOOT)
    objects_check_projectiles(game.objects, game.projectiles)
    objects_update(game.objects, game.level, game.player)
    if (game.objects.events & C.OBJECT_EVENT_FIRE_PIECE) and \
            game_narrative_enabled():
        piece = game.objects.last_fire_piece
        if 1 <= piece <= 4 and game.fire_text[piece] >= 0:
            game.dialogue_text = game.fire_text[piece]
            game.dialogue_page = 0
            game.dialogue_return = C.GAME_PLAYING
            game.state = C.GAME_DIALOGUE
            game.state_timer = 0
    if game.objects.events & C.OBJECT_EVENT_TALISMAN:
        talisman = game.objects.last_talisman
        if 0 <= talisman < 5:
            game.talisman_toast = 150
            game.talisman_toast_index = talisman
            audio_play(C.SFX_PICKUP)
    if game.talisman_toast > 0:
        game.talisman_toast -= 1
    if game.player.hurt_event:
        audio_play(C.SFX_HURT)
    if game.objects.events & C.OBJECT_EVENT_BREAK:
        audio_play(C.SFX_BREAK)
    if game.objects.events & C.OBJECT_EVENT_PICKUP:
        audio_play(C.SFX_PICKUP)
    if game.objects.events & C.OBJECT_EVENT_ENEMY_HIT:
        audio_play(C.SFX_ENEMY_HIT)
    if game.objects.events & C.OBJECT_EVENT_BOSS_DEFEATED:
        audio_play(C.SFX_BREAK)
    if game.objects.events & C.OBJECT_EVENT_CREST_PICKUP:
        audio_play(C.SFX_PICKUP)

    player_animate(game.player,
                   assets_player_anim_for_form(game.assets,
                                               game.player.crest_form))
    camera_update(game.camera, game.level, game.player)

    for obj in game.level.objects:
        if obj.type != LEVEL_OBJECT_EXIT:
            continue
        if abs(game.player.x - obj.x) >= 16.0 or \
                abs(game.player.y - obj.y) >= 32.0:
            continue
        if game.objects.boss_alive:
            break
        if not game.campaign_mode:
            game.state = C.GAME_CLEAR
            game.state_timer = 0
            break
        nxt = game.level.gate_next_area
        if nxt >= 0:
            game_begin_transition(game, nxt, 0)
        else:
            game.campaign_mode = True
            game_open_overworld(game)
        return

    if game.projectile_trace:
        for i, p in enumerate(game.projectiles.slots):
            if not p.active:
                continue
            game.projectile_trace.write(
                f"{game.frame},{i},{p.x_fx / 256.0:.3f},"
                f"{p.y_fx / 256.0:.3f},{p.vx_fx / 256.0:.3f},{p.age}\n")
    if game.object_trace:
        for i, o in enumerate(game.objects.slots):
            if not o.active:
                continue
            game.object_trace.write(
                f"{game.frame},{i},{o.type},{o.x_fx / 256.0:.3f},"
                f"{o.y_fx / 256.0:.3f},{o.vx_fx / 256.0:.3f},"
                f"{o.vy_fx / 256.0:.3f},{o.state},{o.hp},{o.hit_flash},"
                f"{o.species},{o.flags}\n")
    game.frame += 1


def _player_inside_transition(player, tr) -> bool:
    return abs(player.x - tr.x) <= tr.half_w + 10.0 and \
        abs(player.y - tr.y) <= tr.half_h + 10.0


def game_check_transitions(game: Game) -> None:
    if not game.campaign_mode:
        return
    if "DC_BOSS_CLEAR" in os.environ and game.objects.boss_alive and \
            game.objects.boss_present:
        game.objects.boss_alive = False
        game.objects.boss_defeated = True
    player = game.player
    if not game.objects.boss_alive:
        for tr in game.level.transitions:
            if tr.next_area < 0 or tr.next_area >= 113 or \
                    tr.next_area == game.level.area_id:
                continue
            if _player_inside_transition(player, tr):
                game_begin_transition(game, tr.next_area, tr.spawn_id)
                return
    if "DC_DEBUG_OBJ" in os.environ:
        eprint(f"gate: next={game.level.gate_next_area} "
              f"present={1 if game.objects.boss_present else 0} "
              f"alive={1 if game.objects.boss_alive else 0} "
              f"defeated={1 if game.objects.boss_defeated else 0} "
              f"x={player.x:.0f} w={game.level.world_w}", flush=True)
    if 0 <= game.level.gate_next_area < 113 and game.objects.boss_present and \
            not game.objects.boss_alive:
        gate_x = float(game.level.world_w) - 40.0
        if player.x >= gate_x:
            game_begin_transition(game, game.level.gate_next_area, 0)


def game_update_boss_intro(game: Game) -> bool:
    if game.level.area_id != 0 or not game.objects.boss_alive:
        if game.level.area_id != 0:
            game.boss_intro = 0
    boss = None
    for o in game.objects.slots:
        if o.active and o.type == C.OBJECT_BOSS:
            boss = o
            break
    if boss is None:
        game.boss_intro = 0
        return False

    inp = game.input
    inp.left = False
    inp.right = False
    inp.up = False
    inp.down = False
    inp.jump_pressed = False
    inp.jump_held = False
    inp.shot_pressed = False
    inp.shot_held = False

    game.boss_intro_timer += 1
    f = game.boss_intro_timer
    camera_focus(game.camera, game.level, boss.x_fx / 256.0)
    if game.shake > 0:
        game.camera.x += float((game.shake % 5) - 2)

    if game.boss_intro == 1:
        boss.x_fx = int(-70.0 * 256)
        camera_focus(game.camera, game.level, game.player.x)
        if f == 1 or (f % 46) == 0:
            game.shake = 10
        if f > 150:
            game.boss_intro = 2
            game.boss_intro_timer = 0
    elif game.boss_intro == 2:
        boss.x_fx = int(-70.0 * 256)
        if f == 1 or (f % 22) == 0:
            game.shake = 14
        if f > 70:
            game.boss_intro = 3
            game.boss_intro_timer = 0
    elif game.boss_intro == 3:
        boss.state = 8
        if boss.x_fx < int(40.0 * 256):
            boss.x_fx += int(1.3 * 256)
        if (f % 24) == 5:
            game.shake = 16
        if f > 280:
            game.boss_intro = 4
            game.boss_intro_timer = 0
            game.shake = 26
    elif game.boss_intro == 4:
        boss.state = 4
        if f == 1:
            game.shake = 60
            boss.hit_flash = 0
        if f > 110:
            game.boss_intro = 0
            game.boss_intro_timer = 0
            boss.state = 7
            boss.phase = 420
            boss.substate = 0
    else:
        game.boss_intro = 0
    if "DC_BOSS_INTRO_DEBUG" in os.environ:
        last = getattr(game, "_boss_intro_last", -1)
        if game.boss_intro != last:
            eprint(f"boss intro: phase {game.boss_intro} at frame {f} "
                  f"(boss x={boss.x_fx / 256.0:.1f})", flush=True)
            game._boss_intro_last = game.boss_intro
    return True


def game_handle_death(game: Game) -> None:
    if game.player.hp > 0 or game.state != C.GAME_PLAYING:
        return
    if game.restart_timer > 0:
        return
    if game.level.area_id == 0 and "DC_DEATH_GAMEOVER" not in os.environ:
        game.restart_timer = 90
        return
    game.state = C.GAME_OVER
    game.state_timer = 0


def game_overworld_hook_position(game: Game) -> None:
    ox = env("DC_OVERWORLD_X")
    oy = env("DC_OVERWORLD_Y")
    if ox:
        game.overworld_x = float(ox)
    if oy:
        game.overworld_y = float(oy)
    oa = env("DC_OVERWORLD_ANGLE")
    if oa:
        game.overworld_angle = float(oa)
    oz = env("DC_OVERWORLD_ZOOM")
    if oz:
        game.overworld_zoom = float(oz)


def game_open_overworld(game: Game) -> None:
    game_save_progress(game)
    game.state = C.GAME_OVERWORLD
    game.state_timer = 0
    game.overworld_x = 96.0
    game.overworld_y = 176.0
    game.overworld_angle = 0.0
    if game.overworld_zoom <= 0.0:
        game.overworld_zoom = 1.0
    game.overworld_node = CAMPAIGN_GRAVEYARD
    game_overworld_hook_position(game)


def game_complete_area(game: Game) -> None:
    area = game.level.area_id
    if 0 <= area < 8:
        game.stages_cleared |= 1 << area
    if 0 <= area < C.DC_CAMPAIGN_AREAS:
        game.area_cleared[area] = 1
    granted = -1
    if area == 0:
        granted = C.CREST_EARTH
    elif area == 1:
        granted = C.CREST_AIR
    elif area == 2:
        granted = C.CREST_WATER
    elif area == 3:
        granted = C.CREST_TIME
    elif area == 4:
        granted = C.CREST_ULTIMATE
    if granted >= 0:
        bits = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20]
        game.player.crests_mask |= bits[granted]
    game.password_code = game_encode_password(game)
    game.state = C.GAME_CLEAR
    game.state_timer = 0
    game_save_progress(game)
    if granted >= 0 and granted < C.CREST_COUNT and \
            game.crest_text[granted] >= 0 and game_narrative_enabled():
        game.dialogue_text = game.crest_text[granted]
        game.dialogue_page = 0
        game.dialogue_return = C.GAME_CLEAR
        game.state = C.GAME_DIALOGUE
        game.state_timer = 0


def game_update_overworld(game: Game) -> None:
    count = len(game.assets.stage_entries)
    if game.input.subscreen_pressed and count > 0:
        game.stage_select = not game.stage_select
        return
    if game.stage_select:
        if count <= 0:
            game.stage_select = False
        else:
            if game.stage_sel >= count:
                game.stage_sel = count - 1
            if game.stage_sel < 0:
                game.stage_sel = 0
            if game.input.up and game.stage_sel > 0:
                game.stage_sel -= 1
            if game.input.down and game.stage_sel + 1 < count:
                game.stage_sel += 1
            if game.input.right and game.stage_sel + 6 < count:
                game.stage_sel += 6
            if game.input.left and game.stage_sel >= 6:
                game.stage_sel -= 6
            if game.input.start_pressed:
                area = game.assets.stage_entries[game.stage_sel]
                if "DC_STAGE_DEBUG" in os.environ:
                    eprint(f"stage: travel frame {game.frame} sel "
                          f"{game.stage_sel} area {area}", flush=True)
                if game_transition_to_area(game, area, 0):
                    game.campaign_mode = True
                    game.stage_select = False
                    return
            return

    speed = 1.6
    dx = 0.0
    dy = 0.0
    if game.input.left:
        dx -= speed
    if game.input.right:
        dx += speed
    if game.input.up:
        dy -= speed
    if game.input.down:
        dy += speed
    game.overworld_x += dx
    game.overworld_y += dy
    game.overworld_x = min(232.0, max(24.0, game.overworld_x))
    game.overworld_y = min(208.0, max(152.0, game.overworld_y))
    game.overworld_angle += (1.5 if game.input.right else 0.0) - \
        (1.5 if game.input.left else 0.0)
    while game.overworld_angle >= 360.0:
        game.overworld_angle -= 360.0
    while game.overworld_angle < 0.0:
        game.overworld_angle += 360.0
    if game.overworld_zoom <= 0.0:
        game.overworld_zoom = 1.0
    if game.input.form_next_pressed:
        game.overworld_zoom = min(2.0, game.overworld_zoom * 1.12)

    nodes = [
        (CAMPAIGN_COLOSSEUM, 40.0, 168.0),
        (CAMPAIGN_GRAVEYARD, 96.0, 176.0),
        (CAMPAIGN_CATACOMBS, 144.0, 184.0),
        (CAMPAIGN_RUINS, 192.0, 176.0),
        (CAMPAIGN_LAKE, 64.0, 200.0),
        (CAMPAIGN_DEMON_KEEP, 224.0, 160.0),
    ]
    nearest = 1
    best = 1e9
    for node, nx, ny in nodes:
        ddx = nx - game.overworld_x
        ddy = ny - game.overworld_y
        d2 = ddx * ddx + ddy * ddy
        if d2 < best:
            best = d2
            nearest = node
    game.overworld_node = nearest

    if game.input.start_pressed:
        if nearest == CAMPAIGN_DEMON_KEEP:
            if (game.stages_cleared & 0x0F) == 0x0F:
                game_start_ending(game)
                return
            return
        game_transition_to_area(game, nearest, 0)
        game.campaign_mode = True
    elif game.input.special_pressed:
        game.state = C.GAME_SHOP
        game.state_timer = 0


def game_update_subscreen(game: Game, left_pressed: bool, right_pressed: bool,
                          up_pressed: bool, down_pressed: bool) -> None:
    p = game.player
    if left_pressed:
        player_cycle_form(p, -1)
    if right_pressed:
        player_cycle_form(p, 1)
    if up_pressed and game.subscreen_row > 0:
        game.subscreen_row -= 1
    if down_pressed and game.subscreen_row < 5:
        game.subscreen_row += 1
    if game.input.special_pressed:
        p.fire_element = (p.fire_element + 1) % 5
    if game.input.shot_pressed:
        p.active_talisman = (p.active_talisman + 1) % 5
        if not (p.talisman_mask & (1 << p.active_talisman)):
            p.active_talisman = 0
    if game.input.jump_pressed and p.potions > 0:
        p.potions -= 1
        if p.hp < p.max_hp:
            p.hp += 1
        audio_play(C.SFX_PICKUP)
    if game.input.form_next_pressed and p.scrolls > 0:
        p.scrolls -= 1
        if p.hp > 0:
            p.hp -= 1
        audio_play(C.SFX_SHOOT)
    if game.input.subscreen_pressed or game.input.start_pressed or \
            game.input.pause_pressed:
        game.state = C.GAME_PLAYING
        game.state_timer = 0


def game_update_title(game: Game, up_pressed: bool, down_pressed: bool) -> None:
    item_count = 5 if game.has_save else 4
    if game.state_timer > 600 and "DC_NO_ATTRACT" not in os.environ:
        game.campaign_mode = False
        game.attract = True
        game.attract_frame = 0
        game.menu_cursor = 0
        if not game_transition_to_area(game, CAMPAIGN_COLOSSEUM, 0):
            game_reset(game)
        game.state = C.GAME_PLAYING
        game.state_timer = 0
        game.intro_timer = 0
        return
    if up_pressed and game.menu_cursor > 0:
        game.menu_cursor -= 1
    if down_pressed and game.menu_cursor < item_count - 1:
        game.menu_cursor += 1
    if not game.input.start_pressed:
        return
    item = game.menu_cursor
    if game.has_save:
        if item == 0:
            if game_load_progress(game):
                game.campaign_mode = True
                game.state = C.GAME_PLAYING
                game.state_timer = 0
            return
        item -= 1
    if item == 0:
        game.campaign_mode = True
        game.stages_cleared = 0
        game.menu_cursor = 0
        player_init(game.player, game.level)
        if not game_transition_to_area(game, CAMPAIGN_COLOSSEUM, 0):
            game_reset(game)
            game.state = C.GAME_PLAYING
    elif item == 1:
        game.campaign_mode = True
        game_open_overworld(game)
    elif item == 2:
        game.password_entry = game_encode_password(game)
        game.password_pos = 0
        game.password_status = 0
        game.state = C.GAME_PASSWORD
        game.state_timer = 0
    elif item == 3:
        game.state = C.GAME_OPTIONS
        game.state_timer = 0


def game_shop_stock_for_area(game: Game) -> int:
    return 4 if game.level.area_id == 110 else SHOP_STOCK_COUNT


def game_shop_buy(game: Game) -> None:
    stock = game_shop_stock_for_area(game)
    if game.shop_sel >= stock:
        game.campaign_mode = True
        game_open_overworld(game)
        return
    price = _SHOP_STOCK[game.shop_sel][1]
    if game.player.gold < price:
        game.shop_message = game.shop_no_money
        game.shop_timer = 120
        return
    if _SHOP_STOCK[game.shop_sel][2] == 0 and game.player.potions >= 5:
        game.shop_message = game.shop_full_urn
        game.shop_timer = 120
        return
    game.player.gold -= price
    kind = _SHOP_STOCK[game.shop_sel][2]
    if kind == 0:
        game.player.potions += 1
    elif kind == 1:
        game.player.hp = min(game.player.max_hp, game.player.hp + 4)
    elif kind == 2:
        if game.player.max_hp < 10:
            game.player.max_hp += 1
        game.player.hp = game.player.max_hp
    elif kind == 3:
        game.player.hp = game.player.max_hp
    audio_play(C.SFX_PICKUP)


def game_update_shop(game: Game, up_pressed: bool, down_pressed: bool) -> None:
    if game.shop_timer > 0:
        game.shop_timer -= 1
    stock = game_shop_stock_for_area(game)
    if up_pressed:
        game.shop_sel = (game.shop_sel + stock) % (stock + 1)
    if down_pressed:
        game.shop_sel = (game.shop_sel + 1) % (stock + 1)
    if game.input.start_pressed:
        game_shop_buy(game)
    if game.input.pause_pressed:
        game.campaign_mode = True
        game_open_overworld(game)


def game_update_password(game: Game, up_pressed: bool, down_pressed: bool,
                         left_pressed: bool, right_pressed: bool) -> None:
    if not game.password_entry:
        game.password_entry = game_encode_password(game)
        game.password_pos = 0
    if left_pressed and game.password_pos > 0:
        game.password_pos -= 1
    if right_pressed and game.password_pos < DC_PASSWORD_LEN - 1:
        game.password_pos += 1
    if up_pressed or down_pressed:
        direction = 1 if down_pressed else -1
        chars = list(game.password_entry)
        ch = chars[game.password_pos]
        index = DC_PASSWORD_ALPHABET.find(ch)
        if index < 0:
            index = 0
        index = (index + direction + 20) % 20
        chars[game.password_pos] = DC_PASSWORD_ALPHABET[index]
        game.password_entry = "".join(chars)
        game.password_status = 0
    if game.input.start_pressed:
        if game_apply_password(game, game.password_entry):
            game.password_status = 1
            game.campaign_mode = True
            game.has_save = True
            game_open_overworld(game)
        else:
            game.password_status = -1
    elif game.input.pause_pressed:
        game.state = C.GAME_TITLE
        game.state_timer = 0


def game_update_options(game: Game) -> None:
    if game.input.left:
        audio_set_volume(audio_get_volume() - 0.1)
    if game.input.right:
        audio_set_volume(audio_get_volume() + 0.1)
    if game.input.start_pressed or game.input.pause_pressed:
        game.state = C.GAME_TITLE
        game.state_timer = 0


def game_sync_music(game: Game) -> None:
    track = C.MUSIC_STAGE
    if game.state == C.GAME_PLAYING and game.restart_timer > 0:
        t_left = game.restart_timer
        if t_left > 60:
            fade = float(90 - t_left) / 30.0
        elif t_left < 20:
            fade = float(t_left) / 20.0
        else:
            fade = 1.0
        render_set_fade(fade)
        game.restart_timer -= 1
        if game.restart_timer == 0:
            area = game.level.area_id
            game_transition_to_area(game, area, 0)
            game.player.hp = game.player.max_hp
            game.boss_intro = 0
            game.shake_phase = 0
            game.shake = 0
            render_set_fade(0.0)
        return

    if game.state == C.GAME_PLAYING and game.boss_intro > 0 and \
            game_update_boss_intro(game):
        return

    if game.state == C.GAME_TITLE:
        track = C.MUSIC_TITLE
    elif game.state == C.GAME_ENDING:
        track = C.MUSIC_ENDING
    elif game.state in (C.GAME_PLAYING, C.GAME_PAUSED, C.GAME_SUBSCREEN,
                        C.GAME_SHOP):
        track = C.MUSIC_BOSS if (game.objects.boss_present and
                                 game.objects.boss_alive) else C.MUSIC_STAGE
    else:
        track = C.MUSIC_STAGE
    audio_set_track(track)


def game_start_talk(game: Game, pages: list[int]) -> None:
    game.talk_len = 0
    for index in pages:
        if index >= 0 and game.talk_len < 10:
            game.talk_seq[game.talk_len] = index
            game.talk_len += 1
    if game.talk_len == 0:
        return
    game.talk_pos = 0
    game.talk_choice = 0
    game.talk_choice_sel = 0
    game.dialogue_text = game.talk_seq[0]
    game.dialogue_page = 0
    game.state = C.GAME_DIALOGUE
    game.state_timer = 0


def game_start_town_talk(game: Game) -> None:
    game_start_talk(game, [game.town_greet, game.town_question, -1])


def game_try_talk(game: Game) -> None:
    if "DC_DEBUG_OBJ" in os.environ:
        eprint(f"trytalk: player {game.player.x:.0f},{game.player.y:.0f}",
              flush=True)
    for i, o in enumerate(game.objects.slots):
        if not o.active:
            continue
        ox = o.x_fx / 256.0
        oy = o.y_fx / 256.0
        if abs(ox - game.player.x) > 30.0 or abs(oy - game.player.y) > 36.0:
            continue
        if "DC_DEBUG_OBJ" in os.environ:
            eprint(f"talk: slot {i} type {o.type} species {o.species} at "
                  f"{ox:.0f},{oy:.0f} (player {game.player.x:.0f},"
                  f"{game.player.y:.0f})", flush=True)
        if o.species == 0x96 and game.town_greet >= 0:
            game_start_town_talk(game)
            return
        if o.species == 0x10:
            game.state = C.GAME_SHOP
            game.state_timer = 0
            return


def game_trace_frame(game: Game) -> None:
    if not game.trace:
        return
    p = game.player
    game.trace.write(
        f"{game.frame},{p.x:.3f},{p.y:.3f},{p.vx:.3f},{p.vy:.3f},{p.state},"
        f"{game.camera.x:.3f},{game.camera.y:.3f},{p.hp},{p.max_hp},"
        f"{game.level.area_id},{p.crest_form},{p.gold},{p.fire_element},"
        f"{game.state}\n")


def game_update(game: Game) -> None:
    input_read(game.input, game.input_state)
    if game.attract:
        cancel = game.input.start_pressed or game.input.pause_pressed or \
            game.input.jump_pressed or game.input.special_pressed
        if cancel:
            game.attract = False
            game.state = C.GAME_TITLE
            game.state_timer = 0
            game.intro_timer = 0
            return
        game.attract_frame += 1
        f = game.attract_frame
        right = 30 < f < 260
        shoot = (f % 20) == 0
        game.input.left = False
        game.input.up = False
        game.input.down = False
        game.input.jump_held = False
        game.input.jump_pressed = False
        game.input.special_pressed = False
        game.input.special_held = False
        game.input.subscreen_pressed = False
        game.input.form_next_pressed = False
        game.input.start_pressed = False
        game.input.pause_pressed = False
        game.input.right = right
        game.input.shot_pressed = shoot
        game.input.shot_held = shoot

    game.state_timer += 1
    if game.shake > 0:
        game.shake -= 1

    up_pressed = game.input.up and not game.prev_up
    down_pressed = game.input.down and not game.prev_down
    left_pressed = game.input.left and not game.prev_left
    right_pressed = game.input.right and not game.prev_right
    game.prev_up = game.input.up
    game.prev_down = game.input.down
    game.prev_left = game.input.left
    game.prev_right = game.input.right

    if game.state == C.GAME_TITLE:
        game_update_title(game, up_pressed, down_pressed)
    elif game.state == C.GAME_PLAYING:
        if game_update_transition(game):
            pass
        else:
            has_exit = any(o.type == LEVEL_OBJECT_EXIT
                           for o in game.level.objects)
            if game.level.area_id == 0 and game.boss_intro == 0 and \
                    game.shake_phase == 0 and "DC_BOSS_INTRO" not in os.environ:
                game.boss_intro = 1
                game.boss_intro_timer = 0
                game.shake_phase = 1
            if game.campaign_mode and not has_exit and \
                    game.level.gate_next_area < 0 and \
                    game.input.start_pressed:
                game_open_overworld(game)
            elif game.input.special_pressed:
                game_try_talk(game)
                if game.state == C.GAME_PLAYING:
                    _game_playing_step(game)
            else:
                _game_playing_step(game)
    elif game.state == C.GAME_PAUSED:
        items = 3
        if up_pressed and game.menu_cursor > 0:
            game.menu_cursor -= 1
        if down_pressed and game.menu_cursor < items - 1:
            game.menu_cursor += 1
        if game.input.pause_pressed:
            game.state = C.GAME_PLAYING
            game.state_timer = 0
        elif game.input.start_pressed:
            if game.menu_cursor == 0:
                game.state = C.GAME_PLAYING
            elif game.menu_cursor == 1:
                if game_save_progress(game):
                    game.pause_flash = 90
            else:
                game.menu_cursor = 0
                if game.campaign_mode:
                    game_open_overworld(game)
                else:
                    game.state = C.GAME_TITLE
            game.state_timer = 0
    elif game.state == C.GAME_SUBSCREEN:
        game_update_subscreen(game, left_pressed, right_pressed, up_pressed,
                              down_pressed)
    elif game.state == C.GAME_OVERWORLD:
        game_update_overworld(game)
    elif game.state == C.GAME_CLEAR:
        if game.input.start_pressed:
            if game.campaign_mode:
                game_open_overworld(game)
            else:
                game_reset(game)
                game.state = C.GAME_PLAYING
    elif game.state == C.GAME_SHOP:
        game_update_shop(game, up_pressed, down_pressed)
    elif game.state == C.GAME_PASSWORD:
        game_update_password(game, up_pressed, down_pressed, left_pressed,
                             right_pressed)
    elif game.state == C.GAME_OPTIONS:
        game_update_options(game)
    elif game.state == C.GAME_OVER:
        if game.input.start_pressed:
            game.player.hp = game.player.max_hp
            game.campaign_mode = True
            game_open_overworld(game)
    elif game.state == C.GAME_DIALOGUE:
        _game_dialogue_step(game, up_pressed, down_pressed)
    elif game.state == C.GAME_ENDING:
        _game_ending_step(game)

    if game.pause_flash > 0:
        game.pause_flash -= 1
    if game.state == C.GAME_PLAYING and game.intro_timer > 0:
        game.intro_timer -= 1
    game_trace_frame(game)
    game_sync_music(game)
    audio_update()


def _game_playing_step(game: Game) -> None:
    if game.input.subscreen_pressed:
        game.state = C.GAME_SUBSCREEN
        game.state_timer = 0
    elif game.input.pause_pressed:
        game.state = C.GAME_PAUSED
        game.menu_cursor = 0
        game.state_timer = 0
    else:
        area_before = game.level.area_id
        game_update_simulation(game)
        game_handle_death(game)
        if game.state != C.GAME_PLAYING:
            return
        if game.objects.boss_defeated and game.level.area_id == area_before:
            game.objects.boss_defeated = False
            game.player.max_hp = game.player.max_hp + 1 \
                if game.player.max_hp < 10 else game.player.max_hp
            game.player.hp = game.player.max_hp
            keep_control = game.campaign_mode and \
                game.level.gate_next_area >= 0 and \
                ("DC_MVP_KEEP_CONTROL" in os.environ or
                 game.level.area_id == 1)
            if not keep_control:
                game.campaign_mode = True
                game_complete_area(game)
        else:
            game_check_transitions(game)


def _game_dialogue_step(game: Game, up_pressed: bool,
                        down_pressed: bool) -> None:
    pages = game.script.page_count[game.dialogue_text] \
        if 0 <= game.dialogue_text < game.script.count else 0
    if game.talk_len > 0:
        last = game.talk_pos + 1 >= game.talk_len
        if last and game.talk_choice == 0 and \
                game.dialogue_text == game.town_question:
            game.talk_choice = 1
        if game.talk_choice == 1:
            if up_pressed or down_pressed:
                game.talk_choice_sel = 1 - game.talk_choice_sel
            if game.input.start_pressed:
                if game.talk_choice_sel == 0:
                    story = [game.town_story[0], game.town_story[1],
                             game.town_story[2], game.town_story[3], -1, -1]
                    for index in story:
                        if index >= 0 and game.talk_len < 10:
                            game.talk_seq[game.talk_len] = index
                            game.talk_len += 1
                    game.talk_choice = 0
                    game.talk_pos += 1
                    game.dialogue_text = game.talk_seq[game.talk_pos]
                    game.dialogue_page = 0
                else:
                    game.talk_len = 0
                    game.state = game.dialogue_return
                    game.state_timer = 0
            return
        if game.input.start_pressed:
            if game.talk_pos + 1 < game.talk_len:
                game.talk_pos += 1
                game.dialogue_text = game.talk_seq[game.talk_pos]
                game.dialogue_page = 0
            else:
                game.talk_len = 0
                game.state = game.dialogue_return
                game.state_timer = 0
        return
    if game.input.start_pressed:
        if game.dialogue_page + 1 < pages:
            game.dialogue_page += 1
        else:
            game.state = game.dialogue_return
            game.state_timer = 0


def _game_ending_step(game: Game) -> None:
    ed = game.assets.endings
    variant = game.ending_variant
    lines = len(ed["lines"][variant]) if ed["loaded"] else 0
    narr_pages = (lines + 1) // 2
    if not game.input.start_pressed:
        return
    if game.ending_phase == 0:
        if game.ending_page + 1 < narr_pages:
            game.ending_page += 1
        else:
            game.ending_phase = 1
            game.ending_page = 0
    else:
        epi = ed["epilogue"][variant] if ed["loaded"] else -1
        epi_pages = game.script.page_count[epi] \
            if (epi >= 0 and game.script_ready and epi < game.script.count) else 0
        if game.ending_page + 1 < epi_pages:
            game.ending_page += 1
        else:
            game.ending_page = 0
            game.ending_phase = 0
            game.state = C.GAME_TITLE


# --- rendering -------------------------------------------------------------

def _draw_centered(text: str, y: int, size: int, color) -> None:
    font = rl.GetFontDefault()
    encoded = rl.cstr(text)
    measure = rl.MeasureTextEx(font, encoded, float(size), 1.0)
    rl.DrawTextEx(font, encoded,
                  rl.Vector2((256.0 - measure.x) * 0.5, float(y)),
                  float(size), 1.0, color)


def _pretty_name(name: str) -> str:
    return "".join(" " if ch == "-" else ch.upper() for ch in name[:47])


def _draw_stage_select(game: Game) -> None:
    count = len(game.assets.stage_entries)
    rl.DrawRectangle(0, 0, 256, 224, rl.rgb(6, 8, 14))
    _draw_centered("STAGE SELECT", 14, 14, rl.rgb(240, 220, 150))
    cleared = sum(1 for area in game.assets.stage_entries
                  if game.area_cleared[area])
    _draw_centered(f"{count} stages   {cleared} cleared", 32, 9,
                   rl.rgb(150, 200, 240))
    first = (game.stage_sel // 6) * 6
    for i in range(6):
        if first + i >= count:
            break
        idx = first + i
        area = game.assets.stage_entries[idx]
        selected = idx == game.stage_sel
        kind = assets_room_kind(game.assets, area)
        done = game.area_cleared[area] != 0
        tag = "DONE " if done else ("STAGE" if kind == 1 else
                                    ("BOSS " if kind == 2 else "---- "))
        col = rl.rgb(255, 255, 210) if selected else \
            (rl.rgb(150, 230, 170) if done else rl.rgb(200, 200, 210))
        if selected:
            rl.DrawRectangle(20, 46 + i * 20, 216, 18, rl.rgb(50, 44, 70))
        name = game.assets.room_names[area] if area < 113 else ""
        font = rl.GetFontDefault()
        if name:
            text = rl.cstr(f"{tag} {_pretty_name(name)}")
            rl.DrawTextEx(font, text, rl.Vector2(26, 49 + i * 20), 12.0, 1.0,
                          col)
        else:
            text = rl.cstr(f"{tag} AREA {area:02d}")
            rl.DrawTextEx(font, text, rl.Vector2(26, 49 + i * 20), 14.0, 1.0,
                          col)
    _draw_centered(f"PAGE {game.stage_sel // 6 + 1} / {(count + 5) // 6}", 170,
                   9, rl.rgb(180, 180, 190))
    _draw_centered("UP/DOWN SELECT   LEFT/RIGHT PAGE", 188, 9,
                   rl.rgb(200, 220, 255))
    _draw_centered("ENTER TRAVEL   X CLOSE", 204, 9, rl.rgb(200, 220, 255))


def _draw_world_map_view(game: Game) -> bool:
    if not rl.IsTextureValid(game.assets.world_map):
        return False
    wx = (game.overworld_x - 24.0) / (232.0 - 24.0) * 1024.0
    wy = (game.overworld_y - 152.0) / (208.0 - 152.0) * 1024.0
    zoom = game.overworld_zoom if game.overworld_zoom > 0.0 else 1.0
    angle = game.overworld_angle
    while angle < 0.0:
        angle += 360.0
    while angle >= 360.0:
        angle -= 360.0
    src = rl.Rectangle(0, 0, 1024.0, 1024.0)
    dst = rl.Rectangle(0, 0, 1024.0, 1024.0)
    cam = rl.Camera2D()
    cam.offset = rl.Vector2(128.0, 112.0)
    cam.target = rl.Vector2(wx, wy)
    cam.rotation = -angle
    cam.zoom = zoom
    rl.BeginMode2D(cam)
    rl.DrawTexturePro(game.assets.world_map, src, dst, rl.Vector2(0, 0), 0.0,
                      rl.rgb(255, 255, 255))
    for mx, my in game.assets.map_markers:
        d = math.hypot(mx - wx, my - wy)
        col = rl.rgb(255, 236, 140) if d < 40.0 else rl.rgb(235, 235, 245)
        rl.DrawRectangle(int(mx - 3), int(my - 3), 7, 7, col)
        rl.draw_rect_lines(int(mx - 4), int(my - 4), 9, 9, rl.rgb(40, 40, 60))
    rl.EndMode2D()
    rl.DrawCircleV(rl.Vector2(128.0, 112.0), 7.0, rl.rgb(255, 220, 120, 60))
    if rl.IsTextureValid(game.assets.player):
        psrc = rl.Rectangle(0, 0, float(game.assets.player.width),
                            float(game.assets.player.height))
        pdst = rl.Rectangle(128.0 - 8.0, 112.0 - 12.0, 16.0, 16.0)
        rl.DrawTexturePro(game.assets.player, psrc, pdst, rl.Vector2(8.0, 12.0),
                          0.0, rl.rgb(255, 255, 255))
    else:
        rl.DrawCircleV(rl.Vector2(128.0, 112.0), 2.0, rl.rgb(200, 60, 40))
    return True


def _draw_overworld(game: Game) -> None:
    if _draw_world_map_view(game):
        if 0 <= game.talisman_toast_index < 5 and game.talisman_toast > 0:
            name = _TALISMAN_NAMES[game.talisman_toast_index]
            rl.DrawText(rl.cstr(f"{name} TALISMAN"), 60, 196, 10,
                        rl.rgb(255, 236, 170))
        rl.DrawText(b"OVERWORLD", 8, 6, 10, rl.rgb(240, 232, 200))
        rl.DrawText(rl.cstr(f"GOLD {game.player.gold}"), 190, 6, 10,
                    rl.rgb(255, 224, 120))
        rl.DrawText(b"X STAGE SELECT   ENTER LAND   Q/E ZOOM", 8, 208, 8,
                    rl.rgb(200, 220, 255))
        return

    rl.ClearBackground(rl.rgb(6, 8, 14))
    for y in range(224):
        t = float(y) / 223.0
        depth = 1.0 / (0.08 + t * 0.92)
        w = 256.0 * depth
        x = 128.0 - w * 0.5
        if y < 70:
            col = rl.rgb(14 + int(t * 20), 10 + int(t * 16), 32 + int(t * 30))
        else:
            band = math.sin(t * 38.0 + game.overworld_angle * 0.05)
            g = 60 + int(band * 18.0)
            col = rl.rgb(18, g, 34)
            if abs(t - 0.62) < 0.02 or abs(t - 0.78) < 0.025:
                col = rl.rgb(86, 74, 44)
        rl.DrawRectangle(int(x), y, int(w) + 1, 1, col)

    nodes = [
        (0, 40.0, 168.0, "COLOSSEUM"),
        (1, 96.0, 176.0, "GRAVEYARD"),
        (2, 144.0, 184.0, "CATACOMBS"),
        (3, 192.0, 176.0, "RUINS"),
        (4, 64.0, 200.0, "LAKE"),
        (5, 224.0, 160.0, "DEMON KEEP"),
    ]
    for node, nx, ny, label in nodes:
        active = game.overworld_node == node
        col = rl.rgb(255, 220, 90) if active else rl.rgb(150, 140, 120)
        if node == 5 and (game.stages_cleared & 0x0F) != 0x0F:
            col = rl.rgb(120, 70, 90)
        rl.DrawCircle(int(nx), int(ny), 5 if active else 3, col)
        if active:
            encoded = rl.cstr(label)
            width = rl.MeasureText(encoded, 10)
            rl.DrawText(encoded, int(nx) - width // 2, int(ny) + 8, 10,
                        rl.rgb(255, 240, 200))

    rl.DrawCircle(int(game.overworld_x), int(game.overworld_y), 4,
                  rl.rgb(240, 90, 60))
    rl.DrawTriangle(rl.Vector2(game.overworld_x - 4, game.overworld_y - 8),
                    rl.Vector2(game.overworld_x + 4, game.overworld_y - 8),
                    rl.Vector2(game.overworld_x, game.overworld_y - 2),
                    rl.rgb(255, 200, 120))
    rl.DrawRectangle(0, 0, 256, 18, rl.rgb(0, 0, 0, 170))
    rl.DrawText(b"OVERWORLD", 6, 5, 10, rl.rgb(235, 225, 195))
    rl.DrawText(rl.cstr(f"GOLD {game.player.gold}"), 170, 5, 10,
                rl.rgb(235, 210, 120))
    _draw_centered("ARROWS FLY   ENTER LAND   C SHOP", 208, 10,
                   rl.rgb(200, 200, 200))


def game_completion_percent(game: Game) -> int:
    have = 0
    total = 0
    for i in range(5):
        total += 1
        if game.player.crests_mask & (1 << i):
            have += 1
    total += 4
    have += min(4, game.player.fire_element)
    for i in range(5):
        total += 1
        if game.player.talisman_mask & (1 << i):
            have += 1
    total += 5
    have += min(5, game.player.potions)
    total += 5
    have += min(5, game.player.scrolls)
    total += 5
    life = game.player.max_hp - 5
    have += min(5, max(0, life))
    return have * 100 // total if total > 0 else 0


def game_ending_variant(game: Game) -> int:
    pct = game_completion_percent(game)
    if pct >= 100:
        return 2
    if pct >= 50:
        return 1
    return 0


def game_start_ending(game: Game) -> None:
    game.ending_variant = game_ending_variant(game)
    value = env("DC_ENDING")
    if value in ("bad", "normal", "good", "true"):
        game.ending_variant = ("bad", "normal", "good", "true").index(value)
    game.ending_page = 0
    game.ending_phase = 0
    game.state = C.GAME_ENDING
    game.state_timer = 0


def _draw_area_banner(game: Game) -> None:
    if game.intro_timer <= 0 or game.state != C.GAME_PLAYING:
        return
    t = game.intro_timer
    alpha = 1.0
    if t > 90:
        alpha = float(110 - t) / 20.0
    elif t < 25:
        alpha = float(t) / 25.0
    alpha = min(1.0, max(0.0, alpha))
    a = int(alpha * 235.0)
    kind = assets_room_kind(game.assets, game.level.area_id)
    tag = "STAGE" if kind == 1 else ("BOSS STAGE" if kind == 2 else "AREA")
    name = game.assets.room_names[game.level.area_id] \
        if 0 <= game.level.area_id < 113 else ""
    pretty = _pretty_name(name) if name else ""
    rl.DrawRectangle(40, 30, 176, 36, rl.rgb(8, 8, 16, int(a * 0.85)))
    rl.draw_rect_lines(40, 30, 176, 36, rl.rgb(200, 176, 110, a))
    if pretty:
        _draw_centered(pretty, 34, 11, rl.rgb(240, 232, 200, a))
    else:
        _draw_centered(f"{tag} {game.level.area_id:02d}", 34, 12,
                       rl.rgb(240, 232, 200, a))
    if "DC_DEBUG_BANNER" in os.environ:
        _draw_centered(f"{tag} {game.level.area_id:02d}   WORLD "
                       f"{game.level.world_w}x{game.level.world_h}", 52, 9,
                       rl.rgb(170, 180, 200, a))


def _draw_subscreen(game: Game) -> None:
    p = game.player
    rl.DrawRectangle(0, 0, 256, 224, rl.rgb(8, 8, 18, 235))
    rl.DrawText(b"CREST / ITEM SUBSCREEN", 12, 8, 10, rl.rgb(230, 210, 150))
    rl.DrawText(rl.cstr(f"FORM: {player_form_name(p.crest_form)}"), 12, 28, 10,
                rl.rgb(200, 230, 255))
    rl.DrawText(rl.cstr(f"FIRE: {_FIRE_NAMES[p.fire_element]}"), 12, 44, 10,
                rl.rgb(255, 180, 120))
    rl.DrawText(rl.cstr(f"TALISMAN: {_TALISMAN_NAMES[p.active_talisman]}"),
                12, 60, 10, rl.rgb(200, 255, 200))
    rl.DrawText(rl.cstr(f"HP {p.hp}/{p.max_hp}"), 12, 80, 10,
                rl.rgb(240, 120, 140))
    rl.DrawText(rl.cstr(f"URNS {p.potions}/5   SPELLS {p.scrolls}/5   "
                        f"GOLD {p.gold}"), 12, 96, 10, rl.rgb(240, 220, 140))
    rl.DrawText(b"LEFT/RIGHT FORM  A FIRE  Y TALISMAN", 12, 128, 10,
                rl.rgb(190, 190, 190))
    rl.DrawText(b"Z USE URN  Q CAST SPELL  TAB CLOSE", 12, 144, 10,
                rl.rgb(190, 190, 190))
    rl.DrawText(b"OWNED CRESTS:", 12, 172, 10, rl.rgb(220, 220, 220))
    for i in range(C.CREST_COUNT):
        col = rl.rgb(230, 220, 160) if (p.crests_mask & (1 << i)) else \
            rl.rgb(70, 70, 80)
        rl.DrawRectangle(14 + i * 24, 188, 18, 10, col)
        if i == p.crest_form:
            rl.draw_rect_lines(13 + i * 24, 187, 20, 12, rl.rgb(255, 255, 255))


def _draw_overlay(game: Game) -> None:
    menu = ["NEW GAME", "OVERWORLD MAP", "PASSWORD", "OPTIONS"]
    menu_save = ["CONTINUE", "NEW GAME", "OVERWORLD MAP", "PASSWORD",
                 "OPTIONS"]
    if game.attract and game.state == C.GAME_PLAYING:
        rl.DrawRectangle(0, 216, 256, 12, rl.rgb(0, 0, 0, 170))
        _draw_centered("DEMO   PRESS START", 217, 9, rl.rgb(230, 220, 180))
    if game.state == C.GAME_TITLE:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(0, 0, 0, 185))
        _draw_centered("DEMON'S CREST", 34, 24, rl.rgb(238, 232, 214))
        _draw_centered("NATIVE FAN PORT", 62, 10, rl.rgb(196, 168, 92))
        items = menu_save if game.has_save else menu
        for i, label in enumerate(items):
            col = rl.rgb(255, 230, 120) if game.menu_cursor == i else \
                rl.rgb(190, 190, 190)
            _draw_centered(label, 92 + i * 16, 10, col)
        _draw_centered("ARROWS SELECT   ENTER CONFIRM", 186, 10,
                       rl.rgb(150, 150, 150))
        _draw_centered("F1 COLLISION   ESC PAUSE", 200, 10,
                       rl.rgb(150, 150, 150))
    elif game.state == C.GAME_PAUSED:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(0, 0, 0, 150))
        _draw_centered("PAUSED", 84, 24, rl.rgb(238, 232, 214))
        labels = ["RESUME", "SAVE",
                  "RETURN TO MAP" if game.campaign_mode else "QUIT TO TITLE"]
        for i, label in enumerate(labels):
            col = rl.rgb(255, 230, 120) if game.menu_cursor == i else \
                rl.rgb(200, 200, 200)
            _draw_centered(label, 124 + i * 16, 10, col)
        if game.pause_flash > 0:
            _draw_centered("SAVED", 184, 10, rl.rgb(150, 230, 170))
    elif game.state == C.GAME_CLEAR:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(0, 0, 0, 185))
        _draw_centered("AREA CLEAR", 62, 24, rl.rgb(238, 232, 214))
        _draw_centered(f"AREA {game.level.area_id} CONQUERED", 96, 10,
                       rl.rgb(196, 168, 92))
        _draw_centered(f"PASSWORD {game.password_code}", 114, 10,
                       rl.rgb(160, 220, 255))
        _draw_centered(f"MAX HP {game.player.max_hp}   GOLD {game.player.gold}",
                       132, 10, rl.rgb(240, 220, 140))
        if (game.state_timer // 30) % 2 == 0:
            _draw_centered("PRESS ENTER FOR OVERWORLD", 160, 10,
                           rl.rgb(255, 255, 255))
    elif game.state == C.GAME_SUBSCREEN:
        _draw_subscreen(game)
    elif game.state == C.GAME_SHOP:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(10, 8, 14, 240))
        if game.level.area_id == 98 and game.player.scrolls <= 0:
            if game.shop_need_vellum >= 0:
                text_draw_page(game.assets, game.script, game.shop_need_vellum,
                               0, 16, 40, 220, rl.rgb(240, 236, 220))
            _draw_centered("ESC LEAVE", 208, 10, rl.rgb(170, 170, 170))
            return
        y = 10
        if game.shop_welcome >= 0:
            y += text_draw_page(game.assets, game.script, game.shop_welcome, 0,
                                16, y, 220, rl.rgb(240, 236, 220))
        y += 6
        stock = game_shop_stock_for_area(game)
        for i in range(stock + 1):
            selected = game.shop_sel == i
            col = rl.rgb(255, 236, 140) if selected else rl.rgb(190, 190, 200)
            label = _SHOP_STOCK[i][0] if i < stock else "EXIT"
            rl.DrawText(rl.cstr(f"{'>' if selected else ' '} {label}"), 44,
                        y + i * 12, 10, col)
            if i < stock:
                rl.DrawText(rl.cstr(f"{_SHOP_STOCK[i][1]:4d} GP"), 152,
                            y + i * 12, 10, col)
        rl.DrawText(rl.cstr(f"GOLD {game.player.gold}"), 152, 190, 10,
                    rl.rgb(255, 224, 120))
        rl.DrawText(rl.cstr(f"URNS {game.player.potions}/5"), 44, 190, 10,
                    rl.rgb(200, 220, 255))
        if game.shop_timer > 0 and game.shop_message >= 0:
            text_draw_page(game.assets, game.script, game.shop_message, 0, 16,
                           170, 220, rl.rgb(255, 210, 160))
        _draw_centered("UP/DOWN  ENTER BUY  ESC LEAVE", 212, 8,
                       rl.rgb(170, 170, 170))
    elif game.state == C.GAME_PASSWORD:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(6, 10, 16, 240))
        _draw_centered("PASSWORD", 40, 20, rl.rgb(230, 220, 170))
        cw = 16
        start = 128 - (DC_PASSWORD_LEN * cw) // 2
        for i in range(DC_PASSWORD_LEN):
            ch = game.password_entry[i] if i < len(game.password_entry) else "-"
            active = i == game.password_pos
            col = rl.rgb(255, 230, 120) if active else rl.rgb(150, 230, 255)
            rl.DrawText(rl.cstr(ch), start + i * cw + 5, 86, 20, col)
            if active:
                rl.draw_rect_lines(start + i * cw, 84, cw, 26, col)
        if game.password_status < 0:
            _draw_centered("INVALID CODE", 124, 12, rl.rgb(255, 120, 120))
        elif game.password_status > 0:
            _draw_centered("PROGRESS RESTORED", 124, 12, rl.rgb(150, 255, 170))
        _draw_centered("UP/DOWN LETTER   LEFT/RIGHT SELECT", 160, 10,
                       rl.rgb(190, 190, 190))
        _draw_centered("ENTER APPLY   ESC BACK", 178, 10, rl.rgb(190, 190, 190))
    elif game.state == C.GAME_OPTIONS:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(8, 8, 14, 240))
        _draw_centered("OPTIONS", 40, 20, rl.rgb(230, 220, 170))
        _draw_centered(f"VOLUME {int(audio_get_volume() * 100)}%", 96, 12,
                       rl.rgb(200, 230, 255))
        _draw_centered("LEFT/RIGHT ADJUST", 120, 10, rl.rgb(190, 190, 190))
        _draw_centered("ENTER / ESC BACK", 168, 10, rl.rgb(190, 190, 190))
    elif game.state == C.GAME_OVER:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(16, 0, 4, 230))
        _draw_centered("GAME OVER", 76, 24, rl.rgb(240, 90, 90))
        _draw_centered("THE DEMON'S CREST IS LOST", 108, 10,
                       rl.rgb(200, 160, 160))
        if (game.state_timer // 30) % 2 == 0:
            _draw_centered("PRESS ENTER TO CONTINUE", 148, 10,
                           rl.rgb(255, 255, 255))
    elif game.state == C.GAME_DIALOGUE:
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(4, 6, 12, 235))
        if game.dialogue_text >= 0:
            text_draw_page(game.assets, game.script, game.dialogue_text,
                           game.dialogue_page, 16, 64, 224,
                           rl.rgb(240, 236, 220))
        if game.talk_choice == 1:
            cy = rl.rgb(255, 236, 140) if game.talk_choice_sel == 0 else \
                rl.rgb(150, 150, 160)
            cn = rl.rgb(255, 236, 140) if game.talk_choice_sel == 1 else \
                rl.rgb(150, 150, 160)
            text_draw_string(game.assets, "YES", 96, 150, cy)
            text_draw_string(game.assets, "NO", 160, 150, cn)
        if (game.state_timer // 30) % 2 == 0:
            _draw_centered("PRESS ENTER", 196, 10, rl.rgb(200, 200, 200))
    elif game.state == C.GAME_ENDING:
        if rl.IsTextureValid(game.assets.world_map):
            src = rl.Rectangle(0, 0, 1024.0, 1024.0)
            dst = rl.Rectangle(0, 0, 256.0, 224.0)
            rl.DrawTexturePro(game.assets.world_map, src, dst,
                              rl.Vector2(0, 0), 0.0, rl.rgb(110, 110, 150))
        rl.DrawRectangle(0, 0, 256, 224, rl.rgb(4, 6, 12, 205))
        ed = game.assets.endings
        variant = game.ending_variant
        if not ed["loaded"]:
            _draw_centered("THE DEMON'S CREST", 96, 16, rl.rgb(240, 220, 150))
        elif game.ending_phase == 0:
            first = game.ending_page * 2
            _draw_centered(ed["title"][variant], 24, 14, rl.rgb(240, 220, 150))
            for i in range(2):
                idx = first + i
                if idx >= len(ed["lines"][variant]):
                    break
                text_draw_string(game.assets, ed["lines"][variant][idx], 12,
                                 84 + i * 22, rl.rgb(240, 236, 220))
        else:
            epi = ed["epilogue"][variant]
            if epi >= 0 and game.script_ready:
                text_draw_page(game.assets, game.script, epi,
                               game.ending_page, 16, 56, 224,
                               rl.rgb(240, 236, 220))
            else:
                _draw_centered("THE END", 96, 20, rl.rgb(240, 220, 150))
        if (game.state_timer // 30) % 2 == 0:
            _draw_centered("PRESS ENTER", 206, 10, rl.rgb(200, 200, 200))


def game_render(game: Game) -> None:
    rl.BeginTextureMode(game.target)
    cinematic = game.level.area_id == 0
    show_hud = not cinematic and game.state in (C.GAME_PLAYING, C.GAME_PAUSED,
                                                C.GAME_SUBSCREEN)
    if game.state == C.GAME_OVERWORLD:
        _draw_overworld(game)
        if game.stage_select:
            _draw_stage_select(game)
    else:
        render_game(game.assets, game.level, game.camera, game.player,
                    game.projectiles, game.objects, show_hud,
                    game.input.debug_collision)
        _draw_area_banner(game)
    if game.state != C.GAME_PLAYING:
        _draw_overlay(game)
    if game.dialogue_demo and game.script_ready and game.script.count > 0:
        pages = game.script.page_count[0]
        page = (game.state_timer // 120) % pages if pages > 0 else 0
        if "DC_FONT_TEST" in os.environ:
            text_draw_string(game.assets, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", 8, 120,
                             rl.rgb(240, 236, 220))
            text_draw_string(game.assets, "abcdefghijklmnopqrstuvwxyz", 8, 130,
                             rl.rgb(240, 236, 220))
            text_draw_string(game.assets, "0123456789 .,:;!?-'", 8, 140,
                             rl.rgb(240, 236, 220))
            height = 24
        else:
            height = text_draw_page(game.assets, game.script, 0, page, 16, 150,
                                    216, rl.rgb(240, 236, 220))
        if height > 0:
            text_draw_string(game.assets, "ENTER NEXT", 16, 150 + height + 6,
                             rl.rgb(170, 170, 185))
    render_draw_fade()
    rl.EndTextureMode()


def game_shutdown(game: Game) -> None:
    if game.ready and game.campaign_mode:
        game_save_progress(game)
    audio_shutdown()
    for handle in (game.trace, game.projectile_trace, game.object_trace):
        if handle:
            handle.close()
    if rl.IsRenderTextureValid(game.target):
        rl.UnloadRenderTexture(game.target)
    level_unload(game.level)
