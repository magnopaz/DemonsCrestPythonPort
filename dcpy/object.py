"""Level object pool, spawn rules and per-species AI (port of object.c).

The pool keeps 26 reusable slots; ``events`` carries the one-frame flags the
audio/HUD layers consume, and the boss bookkeeping mirrors the C struct. All
positions are 8.8 fixed point, exactly like the native port, so every spawn,
hop, bob and projectile speed keeps the ROM's numbers.
"""

from __future__ import annotations

import math
import re

from .bosses import boss_hp
from .consts import (
    CREST_TIME, CREST_ULTIMATE, LEVEL_OBJECT_BOSS, LEVEL_OBJECT_ENEMY,
    LEVEL_OBJECT_NPC, LEVEL_OBJECT_PICKUP_CREST, LEVEL_OBJECT_PLATFORM,
    LEVEL_OBJECT_TALISMAN, LEVEL_OBJECT_UNKNOWN, LEVEL_OBJECT_URN,
    OBJECT_BOSS, OBJECT_CREST_ITEM,
    OBJECT_ENEMY, OBJECT_ENEMY_SHOT, OBJECT_EVENT_BOSS_DEFEATED,
    OBJECT_EVENT_BREAK, OBJECT_EVENT_CREST_PICKUP, OBJECT_EVENT_ENEMY_HIT,
    OBJECT_EVENT_FIRE_PIECE, OBJECT_EVENT_PICKUP, OBJECT_EVENT_TALISMAN,
    OBJECT_NONE, OBJECT_NPC, OBJECT_PICKUP, OBJECT_PLATFORM, OBJECT_POOL_SIZE,
    OBJECT_TALISMAN, OBJECT_URN,
)
from .level import level_floor_at, level_is_solid_at, level_is_wall_at
from .util import eprint, env, env_flag, float_to_fx, fx_to_float

FX_ONE = 256
HEART_POPUP_FX = 0x0400  # $85:C1D1 initial upward velocity 4.0
HEART_GRAVITY_FX = 0x0040  # $85:C1D1 gravity 0.25
HEART_BOUNCE_FX = 0x0400  # $85:C1D1 bounce decay 4.0 -> 3.0 ...
HEART_BOUNCE_STEP = 0x0100

URN_HALF = 8.0
HEART_HALF = 8.0

_ATOF_RE = re.compile(
    r"[ \t\n\r\v\f]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


class Object:
    """One pooled level object (C ``Object``)."""

    def __init__(self):
        self.active = False
        self.type = OBJECT_NONE
        self.species = 0
        self.flags = 0
        self.x_fx = 0
        self.y_fx = 0
        self.origin_x_fx = 0
        self.origin_y_fx = 0
        self.vx_fx = 0
        self.vy_fx = 0
        self.bounce_fx = 0  # $39: remaining bounce velocity for pickups
        self.state = 0
        self.substate = 0  # $06: per-species state machine substate
        self.phase = 0  # countdown for the current substate ($3B)
        self.hops = 0  # $38: hop counter inside a burst
        self.burst = 0  # $3A: animation step inside a burst
        self.spit_cd = 0  # $3C: frames until the next child in a volley
        self.spit_left = 0  # $3D: children left in the volley
        self.saved_state = 0  # $42: state a finished action returns to
        self.hide_timer = 0  # $43: cooldown before the next decision
        self.target_x_fx = 0  # $3F: x the leap was aimed at
        self.landings = 0  # $41: ground contacts of the leap
        self.hit_flash = 0  # frames of white flash after taking a hit
        self.facing = 0  # $09: 1 right, -1 left
        self.hp = 0
        self.max_hp = 0
        self.anim_frame = 0  # $3F: animation frame (sub 18 spin target)
        self.anim_phase = 0  # $40: $CF6E animation phase
        self.anim_timer = 0  # $41: frames left in the animation phase
        self.eye_scale = 0  # $3D/$3E: 16-bit speed scale of the launch
        self.probe_timer = 0  # $44: frames before the player probe runs
        self.ret_timer = 0  # $47/$48: 16-bit flight timer ($D198/$D1AE)
        self.tail = 0  # $49: $CCBF tail index (0/2/4)
        self.tail_a = 0  # $4A: tail countdown
        self.tail_b = 0  # $4B: tail animation
        self.tail_c = 0  # $4C: tail animation id
        self.tail_d = 0  # $4D: nonzero freezes movement
        self.tail_e = 0  # $4E: return-state direction phase
        self.tail_f = 0  # $4F: frames per animation step
        self.launched = False  # $1DDE[flag]: this eye already left the park
        self.timer = 0


class ObjectPool:
    def __init__(self):
        self.slots = [Object() for _ in range(OBJECT_POOL_SIZE)]
        self.events = 0  # one-frame sound/effect flags
        self.boss_alive = False
        self.boss_defeated = False
        self.boss_present = False  # an OBJECT_BOSS was spawned in this room
        self.boss_phase = 0  # 1 until a two-form boss transforms
        self.pit_fight = False  # area 8: $69 raised $1DEA (the fight started)
        self.pit_rng = 0  # $009C/$009D: the fight's 16-bit LCG seed
        # The $69 launch controller ($83:B9F1) and the fight's shared bytes.
        self.pit_parked = [9] * 10  # $1DDE[0..9]: 9 new, 1 back from a flight, 0 launched
        self.pit_launched = 0  # $1DE9: eyes the controller has released
        self.pit_dead = 0  # $1DF8: eyes destroyed (no damage yet, so it stays 0)
        self.pit_armed = 0  # $1DF6: 1 once $6B finishes its climb
        self.pit_opened = 0  # $1DEB: 1 when the controller has nothing left to send
        self.pit_ctl = 0  # $40: $B9F1's dispatch (0/2/4/6)
        self.pit_burst = 0  # $3F: eyes left in the current burst
        self.pit_wait = 0  # $3E: frames until the next release
        self.pit_count = 0  # $00C4:$45: the $69's 24-bit countdown
        self.last_fire_piece = 0
        self.last_talisman = 0  # 1..4 = Buster/Tornado/Claw/Demon Fire


# --------------------------------------------------------------------------
# C-compatible scalar helpers
# --------------------------------------------------------------------------

def _atoi(text: str) -> int:
    """C atoi: optional whitespace/sign, leading digits, 0 when none."""
    i = 0
    n = len(text)
    while i < n and text[i] in " \t\n\r\v\f":
        i += 1
    sign = 1
    if i < n and text[i] in "+-":
        if text[i] == "-":
            sign = -1
        i += 1
    start = i
    while i < n and text[i].isdigit():
        i += 1
    if i == start:
        return 0
    return sign * int(text[start:i])


def _atof(text: str) -> float:
    """C atof: parse the leading float, 0.0 when there is none."""
    match = _ATOF_RE.match(text)
    if match is None:
        return 0.0
    return float(match.group(1))


def _c_int(value: float) -> int:
    """C (int32_t) cast: truncation toward zero."""
    if value >= 0.0:
        return int(math.floor(value))
    return int(math.ceil(value))


def _c_div(value: int, divisor: int) -> int:
    """C integer division: truncation toward zero (Python // floors)."""
    if value < 0:
        return -((-value) // divisor)
    return value // divisor


def _reset_object(o: Object) -> None:
    """memset(o, 0, sizeof(*o))."""
    o.active = False
    o.type = OBJECT_NONE
    o.species = 0
    o.flags = 0
    o.x_fx = 0
    o.y_fx = 0
    o.origin_x_fx = 0
    o.origin_y_fx = 0
    o.vx_fx = 0
    o.vy_fx = 0
    o.bounce_fx = 0
    o.state = 0
    o.substate = 0
    o.phase = 0
    o.hops = 0
    o.burst = 0
    o.spit_cd = 0
    o.spit_left = 0
    o.saved_state = 0
    o.hide_timer = 0
    o.target_x_fx = 0
    o.landings = 0
    o.hit_flash = 0
    o.facing = 0
    o.hp = 0
    o.max_hp = 0
    o.anim_frame = 0
    o.anim_phase = 0
    o.anim_timer = 0
    o.eye_scale = 0
    o.probe_timer = 0
    o.ret_timer = 0
    o.tail = 0
    o.tail_a = 0
    o.tail_b = 0
    o.tail_c = 0
    o.tail_d = 0
    o.tail_e = 0
    o.tail_f = 0
    o.launched = False
    o.timer = 0


def _alloc(pool: ObjectPool):
    for o in pool.slots:
        if not o.active:
            return o
    return None


# --------------------------------------------------------------------------
# Spawners
# --------------------------------------------------------------------------

def _spawn_urn(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_URN
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 1
    o.max_hp = 1


def _spawn_pickup(pool: ObjectPool, x: float, bottom_y: float) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_PICKUP
    o.x_fx = float_to_fx(x)
    o.y_fx = float_to_fx(bottom_y)
    o.vy_fx = -HEART_POPUP_FX  # object convention: positive is up
    o.bounce_fx = HEART_BOUNCE_FX
    o.state = 0


def _spawn_enemy(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_ENEMY
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 3 if src.species == 0x26 else 2
    o.max_hp = o.hp
    if env_flag("DC_BOSS_HURT"):  # test hook: show the damage tint
        o.hp = o.max_hp // 2 if o.max_hp > 1 else 1
    o.state = 0  # emerge / init
    o.timer = 24
    o.vx_fx = 0x0080 if (src.flags & 1) else -0x0080
    o.facing = 1 if o.vx_fx >= 0 else -1


# Hostile projectile spawned by the species $67 ghoul ($82877B in the
# original): the child object runs its own species handler, so the native port
# models it as a straight-flying object with the captured $67 sprite.
def _spawn_enemy_shot(pool: ObjectPool, x: float, y: float, vx: int,
                      vy: int) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_ENEMY_SHOT
    o.species = 0x67
    o.x_fx = float_to_fx(x)
    o.y_fx = float_to_fx(y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.vx_fx = vx
    o.vy_fx = vy
    o.hp = 1


# Somulo's fireball: a normal hostile shot, but marked so that hitting the
# ground spawns a firewall (its `substate` is used as a flag).
def _spawn_boss_fireball(pool: ObjectPool, x: float, y: float, vx: int,
                         vy: int) -> None:
    _spawn_enemy_shot(pool, x, y, vx, vy)
    for o in pool.slots:
        if (o.active and o.type == OBJECT_ENEMY_SHOT and
                o.x_fx == float_to_fx(x) and o.y_fx == float_to_fx(y)):
            o.substate = 1
            o.species = 0x34  # the fireball object in Area 0
            break


# Firewall: three short-lived flames standing on the ground where a fireball
# landed. They are enemy shots flagged with state 1 so the update path keeps
# them in place.
def _spawn_firewall(pool: ObjectPool, x: float, y: float) -> None:
    for k in range(-1, 2):
        o = _alloc(pool)
        if o is None:
            return
        _reset_object(o)
        o.active = True
        o.type = OBJECT_ENEMY_SHOT
        o.species = 0x34
        o.state = 1
        o.x_fx = float_to_fx(x + float(k) * 9.0)
        o.y_fx = float_to_fx(y)
        o.origin_x_fx = o.x_fx
        o.origin_y_fx = o.y_fx
        o.hp = 1


def _spawn_platform(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_PLATFORM
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.vx_fx = 0x0080


def _spawn_crest_item(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_CREST_ITEM
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx


# Talismans (crown/skull/armor/fang/hand) float in place until collected.
def _spawn_talisman(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_TALISMAN
    o.species = src.flags if 0 <= src.flags < 5 else 3
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx


def _spawn_boss(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_BOSS
    pool.boss_present = True
    o.species = src.species
    o.flags = src.flags
    # Test hook: boot the second Phalanx form directly so its art and AI can
    # be smoke-tested without scripting the first form's death.
    phase_env = env("DC_BOSS_PHASE")
    forced_second = bool(phase_env) and _atoi(phase_env) == 2 and \
        o.species == 0x86
    if forced_second:
        o.species = 0x8D
        o.substate = 1
    bx = src.x
    by = src.y
    if src.species == 0x33 and bx < 120.0:
        bx = 220.0
        by = 160.0
    elif src.species == 0xA5 and by < 64.0:
        by = 140.0
    # The ROM stores a boss's y at the centre of its hitbox, while the port
    # anchors sprites at their feet. Somulo's box is 92 px tall (80x92), so his
    # feet sit 23 px below the stored value -- exactly the colosseum floor
    # (170 + 23 = 193 against a 192 floor line). Without this he stands in the
    # air, which is how the fight shipped until now.
    if src.species == 0x33:
        by += 23.0
    # Test hook: place the boss where a grounded demo can reach it.
    bx_env = env("DC_BOSS_X")
    by_env = env("DC_BOSS_Y")
    if bx_env:
        bx = _atof(bx_env)
    if by_env:
        by = _atof(by_env)
    o.x_fx = float_to_fx(bx)
    o.y_fx = float_to_fx(by)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = boss_hp(o.species, src.flags)
    o.facing = 1  # sheets face right; the AI updates this as it turns
    hp_env = env("DC_BOSS_HP")
    if hp_env:
        o.hp = _atoi(hp_env)
    o.max_hp = o.hp
    o.state = 0
    pool.boss_alive = True
    if env_flag("DC_BOSS_DEFEATED"):
        # Test hook: the boss starts already defeated so the clear flow can be
        # exercised without fighting. Set the full defeat state, not just an
        # inactive slot.
        o.active = False
        o.hp = 0
        pool.boss_alive = False
        pool.boss_defeated = True
        pool.events |= OBJECT_EVENT_BOSS_DEFEATED


# City NPCs ($96): inert, talkable, drawn from the captured sheet.
def _spawn_npc(pool: ObjectPool, src) -> None:
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = OBJECT_NPC
    o.species = (src.species if src.species else 0x96) & 0xFF
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    o.hp = 1
    o.facing = -1


def _spawn_unknown(pool: ObjectPool, src) -> None:
    """Pool a species whose handler is only partly ported.

    The pit boss trio ($69/$6B/$6C) needs a live position for its measured
    opening; the renderer draws these as debug boxes (render.py)."""
    o = _alloc(pool)
    if o is None:
        return
    _reset_object(o)
    o.active = True
    o.type = LEVEL_OBJECT_UNKNOWN
    o.species = src.species
    o.flags = src.flags
    o.x_fx = float_to_fx(src.x)
    o.y_fx = float_to_fx(src.y)
    o.origin_x_fx = o.x_fx
    o.origin_y_fx = o.y_fx
    # docs/boss_hp.txt: Ovununu is 3 HP per eye and 10 for the main body.
    if src.species == PIT_BODY_SPECIES:
        o.hp = PIT_BODY_HP
    elif src.species == PIT_EYE_SPECIES:
        o.hp = PIT_EYE_HP
    else:
        o.hp = 1
    o.max_hp = o.hp


def objects_init(pool: ObjectPool, level) -> None:
    # memset(pool, 0, sizeof(*pool)), then the phase default.
    for slot in pool.slots:
        _reset_object(slot)
    pool.events = 0
    pool.boss_alive = False
    pool.boss_defeated = False
    pool.boss_present = False
    pool.pit_fight = False
    pool.pit_rng = 0
    pool.pit_parked = [9] * 10
    pool.pit_launched = 0
    pool.pit_dead = 0
    pool.pit_armed = 0
    pool.pit_opened = 0
    pool.pit_ctl = 0
    pool.pit_burst = 0
    pool.pit_wait = 0
    pool.pit_count = 0
    pool.last_fire_piece = 0
    pool.last_talisman = 0
    pool.boss_phase = 1
    # $96 is the script/NPC actor: the shopkeepers and the library old man in
    # 46..49/55, the avenue's townsperson in area 4, and the arena controller
    # in the boss rooms (52/53/54, where it shares the boss's position). The
    # extractor types every $96 record "boss", which blocks every door in the
    # room and shows a boss placeholder. In a room with a real boss it is the
    # controller and stays invisible; anywhere else it is a talkable NPC.
    room_has_boss = any(o.type == LEVEL_OBJECT_BOSS and o.species != 0x96
                        for o in level.objects)
    if env_flag("DC_DEBUG_OBJ"):
        eprint(f"objects: init with {len(level.objects)} level objects",
              flush=True)
    for src in level.objects:
        if src.type == LEVEL_OBJECT_URN:
            _spawn_urn(pool, src)
        elif src.type == LEVEL_OBJECT_ENEMY:
            _spawn_enemy(pool, src)
        elif src.type == LEVEL_OBJECT_PLATFORM:
            _spawn_platform(pool, src)
        elif src.type == LEVEL_OBJECT_PICKUP_CREST:
            _spawn_crest_item(pool, src)
        elif src.type == LEVEL_OBJECT_BOSS:
            if src.species == 0x96:
                if not room_has_boss:
                    _spawn_npc(pool, src)
            else:
                _spawn_boss(pool, src)
        elif src.type == LEVEL_OBJECT_NPC:
            _spawn_npc(pool, src)
        elif src.type == LEVEL_OBJECT_TALISMAN:
            _spawn_talisman(pool, src)
        elif src.type == LEVEL_OBJECT_UNKNOWN and \
                src.species in (PIT_CORE_SPECIES, PIT_BODY_SPECIES,
                                PIT_EYE_SPECIES):
            _spawn_unknown(pool, src)
    if env_flag("DC_DEBUG_OBJ"):
        n = 0
        for i, o in enumerate(pool.slots):
            if o.active:
                eprint(f"objects: slot {i} type {int(o.type)} "
                      f"species {o.species} at {fx_to_float(o.x_fx):.0f},"
                      f"{fx_to_float(o.y_fx):.0f}", flush=True)
                n += 1
        eprint(f"objects: {n} active", flush=True)


def _player_touches(o: Object, player) -> bool:
    ox = fx_to_float(o.x_fx)
    oy = fx_to_float(o.y_fx) - HEART_HALF
    px = player.x
    py = player.y - 10.0
    return abs(ox - px) < 16.0 and abs(oy - py) < 20.0


def _damage_player(player, ox: float, amount: int) -> None:
    if player.invuln_timer > 0 or player.hp <= 0:
        return
    # Time/Ultimate Gargoyle and Armor Talisman halve incoming damage.
    if (player.crest_form == CREST_TIME or
            player.crest_form == CREST_ULTIMATE or
            player.active_talisman == 2) and amount > 1:
        amount = (amount + 1) // 2
    player.hp -= amount
    if player.hp < 0:
        player.hp = 0
    player.invuln_timer = 60
    player.knockback_timer = 8
    player.knockback_dir = 1 if ox < player.x else -1
    player.hurt_event = True


# --------------------------------------------------------------------------
# Species $67 - Graveyard Ghoul
#
# Port of the ROM's own handler: init $83:AF19, update $83:AF74, which
# dispatches on $05 through the table at $AF7F and on $06 through per-state
# tables. States are even byte offsets, so each state has four substates
# (0/2/4/6):
#
#   0 $AF89  small hop loop        sub 0 decide, 2 windup, 4 airborne, 6 land
#   2 $B065  long hop              sub 0 face, 2 windup 32, 4 airborne, 6 land
#   4 $B0E4  stand and spit        sub 0 face, 2 windup 32, 4 three children
#                                  on a 64-frame cadence, 6 hold 32
#   6 $B1AF  leap / child flight   sub 0 aim, 2 fly, 4 impact, 6 despawn
#   8 $B249  cooldown              sub 0 wait $43, 2 re-check range
#
# The hop constants are the ROM's: launch `$22 = 0x0398` (`0x04D0` on odd
# hops), `$20 = 0x0050`, gravity `$26 = 0x0040`, `$34 -= 9` at launch and
# `+7` on landing. The long hop uses `$20 = 0x0120`, `$22 = 0x0540`.
# The live oracle trace (`/tmp/ghoul_trace`, 300 frames, area 1) confirms the
# observed order 4 -> 0(2,4,6) -> 0(2,...) with the 32/64/32 volley cadence.
# --------------------------------------------------------------------------
GHOUL_GRAVITY = 0x0040
GHOUL_RANGE_X = 0x00E0
GHOUL_RANGE_Y = 0x0050


def _ghoul_face(o: Object, p) -> None:
    o.facing = 1 if p.x_fx >= o.x_fx else -1


# $B2E8: |(x + 0x70) - player.x| < 0xE0, the $03 bit 6 flag set, and the
# player above the ghoul or no more than 0x50 below it.
def _ghoul_in_range(o: Object, p) -> bool:
    dx = (o.x_fx + 0x70 * FX_ONE) - p.x_fx
    if abs(dx) >= GHOUL_RANGE_X * FX_ONE:
        return False
    if not (o.flags & 0x40):
        return False
    dy = p.y_fx - o.y_fx  # y grows downward
    return dy < GHOUL_RANGE_Y * FX_ONE


# One applied step of the ROM's move + gravity, returning true on landing.
def _ghoul_move(o: Object, level) -> bool:
    o.x_fx += o.vx_fx
    o.y_fx += o.vy_fx
    o.vy_fx += GHOUL_GRAVITY
    fx = fx_to_float(o.x_fx)
    fy = fx_to_float(o.y_fx)
    if o.vy_fx > 0:
        surf = level_floor_at(level, fx, fy + 2.0)
        if surf is not None and surf <= fy + 10.0:
            o.y_fx = float_to_fx(surf)
            o.vx_fx = 0
            o.vy_fx = 0
            return True
    return False


# $B14F: the spit. The ROM spawns another $67 object at (+-0x13, -0x14) and
# sets its state to 6, so the "projectile" is a small diving ghoul.
def _ghoul_spit(pool: ObjectPool, o: Object) -> None:
    ox = fx_to_float(o.x_fx) + float(o.facing * 0x13)
    oy = fx_to_float(o.y_fx) - 0x14
    # The child is aimed at its parent's own x ($3F is written from $31 at
    # $B17C), so the distance band is the near one: vx = 0x80, vy = 0x03A0.
    # It does not home across the room; it lobs and falls.
    _spawn_enemy_shot(pool, ox, oy, o.facing * 0x0080, -0x03A0)


def _ghoul_update(o: Object, level, p, pool: ObjectPool) -> None:
    if env_flag("DC_DEBUG_GHOUL"):
        eprint(f"ghoul t={o.timer} st={o.state} sub={o.substate} "
              f"ph={o.phase} x={fx_to_float(o.x_fx):.1f} "
              f"y={fx_to_float(o.y_fx):.1f}", flush=True)
    if o.state == 0:  # $AF89 small hop loop
        if o.substate == 0:
            if _ghoul_in_range(o, p):
                _ghoul_face(o, p)
                o.hops = 0
                o.substate = 2
                o.phase = 3  # $3B = 3
            else:
                # $DEA2 picks at random; the port rotates deterministically so
                # a replay is reproducible: hop, volley, long hop.
                o.saved_state = (o.saved_state + 1) % 3
                if o.saved_state == 1:
                    o.state = 4
                    o.substate = 0
                elif o.saved_state == 2:
                    o.state = 2
                    o.substate = 0
                else:
                    # The rotation's third beat is the plain small hop.
                    _ghoul_face(o, p)
                    o.hops = 0
                    o.substate = 2
                    o.phase = 3
        elif o.substate == 2:
            _ghoul_face(o, p)
            o.phase -= 1
            if o.phase <= 0:
                o.y_fx -= 9 * FX_ONE  # $B2B1
                o.vx_fx = o.facing * 0x0050
                o.vy_fx = -0x04D0 if (o.hops & 1) else -0x0398
                o.substate = 4
        elif o.substate == 4:
            if _ghoul_move(o, level):
                o.y_fx += 7 * FX_ONE  # $B2C7
                o.substate = 6
                o.phase = 6
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.hops += 1  # $B034
                if o.hops >= 3:
                    o.substate = 0
                else:
                    o.facing = -o.facing
                    o.substate = 2
                    o.phase = 3
        else:
            o.substate = 0

    elif o.state == 2:  # $B065 long hop
        if o.substate == 0:
            _ghoul_face(o, p)
            o.substate = 2
            o.phase = 0x20
        elif o.substate == 2:
            o.phase -= 1
            if o.phase <= 0:
                o.y_fx -= 9 * FX_ONE
                o.vx_fx = o.facing * 0x0120
                o.vy_fx = -0x0540
                o.substate = 4
                o.landings = 0
        elif o.substate == 4:
            if _ghoul_move(o, level):
                o.y_fx += 7 * FX_ONE
                o.substate = 6
                o.phase = 0x10
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.state = 4  # $B0DD
                o.substate = 0
        else:
            o.substate = 0

    elif o.state == 4:  # $B0E4 stand and spit three children
        if o.substate == 0:
            _ghoul_face(o, p)
            o.substate = 2
            o.phase = 0x20
        elif o.substate == 2:
            o.phase -= 1
            if o.phase <= 0:
                o.substate = 4
                o.spit_left = 3  # $3D = 3
                o.spit_cd = 0x40  # $3C = 0x40
        elif o.substate == 4:
            o.spit_cd -= 1
            if o.spit_cd <= 0:
                _ghoul_spit(pool, o)
                o.spit_left -= 1
                o.spit_cd = 0x40
                if o.spit_left <= 0:
                    o.substate = 6
                    o.phase = 0x20
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                # $B1AB jumps straight into the hop entry, not to the state
                # dispatcher, so a volley always ends in hops.
                _ghoul_face(o, p)
                o.state = 0
                o.hops = 0
                o.substate = 2
                o.phase = 3
        else:
            o.substate = 0

    elif o.state == 6:  # $B1AF leap, and the child's flight
        if o.substate == 0:
            _ghoul_face(o, p)
            o.target_x_fx = p.x_fx
            dx = o.target_x_fx - o.x_fx
            dist = abs(dx)
            # $DEB2/$DEBA/$DEC2: farther targets get more speed and lift.
            if dist > 96 * FX_ONE:
                o.vx_fx = o.facing * 0x0120
                o.vy_fx = -0x0540
            elif dist > 48 * FX_ONE:
                o.vx_fx = o.facing * 0x00C0
                o.vy_fx = -0x0480
            else:
                o.vx_fx = o.facing * 0x0080
                o.vy_fx = -0x03A0
            o.substate = 2
        elif o.substate == 2:
            if _ghoul_move(o, level):
                o.substate = 4
                o.phase = 8
                o.landings += 1
        elif o.substate == 4:
            o.phase -= 1
            if o.phase <= 0:
                o.substate = 6
                o.phase = 0x20
        elif o.substate == 6:
            o.phase -= 1
            if o.phase <= 0:
                o.active = False  # $828777
        else:
            o.substate = 0

    elif o.state == 8:  # $B249 cooldown
        if o.substate == 0:
            o.substate = 2
            o.hide_timer = 0x50  # $43 = 0x50
        elif o.substate == 2:
            o.hide_timer -= 1
            if o.hide_timer <= 0:
                if not _ghoul_in_range(o, p):
                    o.state = 4
                    o.substate = 0
                else:
                    o.state = 0
                    o.substate = 0
        else:
            o.substate = 0

    else:
        o.state = 0
        o.substate = 0


PIT_CORE_SPECIES = 0x69
PIT_BODY_SPECIES = 0x6B
PIT_EYE_SPECIES = 0x6C
# docs/boss_hp.txt (Ovununu): 10 HP for the main body, 3 per eye.
PIT_BODY_HP = 10
PIT_EYE_HP = 3


def _pit_damage(player) -> int:
    """Damage the current form deals, per docs/boss_hp.txt's Ovununu column.

    Fire/Buster/Claw/Tidal 1, Demon Fire 3, Earth (ground) 2, Earth (air) 1,
    Aerial 2, Legendary/Ultimate 5.  The port only models the ultimate form
    explicitly today, so every other form uses the base 1."""
    if player.crest_form == CREST_ULTIMATE:
        return 5
    return 1

# The body's climb, sampled every 20 frames from the pit take (frame 14400 is
# the room entry; 15750 is the top). The ROM's internal stages are $3E/scroll
# driven and not mapped yet (docs/PIT_BOSS.md §5); this is the measured curve.
_PIT_RISE = (
    (0, 700.0), (20, 698.5), (40, 693.5), (60, 690.0),
    (80, 688.1), (100, 687.1), (120, 671.4), (140, 650.8),
    (160, 644.1), (180, 644.1), (200, 641.7), (220, 622.0),
    (240, 604.8), (260, 600.6), (280, 600.6), (300, 595.6),
    (320, 573.7), (340, 559.4), (360, 557.0), (380, 557.0),
    (400, 551.3), (420, 531.3), (440, 519.5), (460, 514.9),
    (480, 513.5), (500, 513.5), (520, 512.3), (540, 497.2),
    (560, 482.4), (580, 474.1), (600, 470.6), (620, 469.9),
    (640, 469.9), (660, 465.0), (680, 444.2), (700, 431.7),
    (720, 427.0), (740, 426.4), (760, 426.4), (780, 419.0),
    (800, 398.4), (820, 386.5), (840, 382.8), (860, 382.8),
    (880, 382.0), (900, 365.2), (920, 351.8), (940, 343.5),
    (960, 339.9), (980, 339.2), (1000, 339.2), (1020, 336.8),
    (1040, 317.2), (1060, 301.1), (1080, 296.2), (1100, 295.7),
    (1120, 294.6), (1140, 277.6), (1160, 258.8), (1180, 252.1),
    (1200, 252.1), (1220, 250.6), (1240, 232.7), (1260, 214.0),
    (1280, 208.6), (1300, 208.6), (1320, 210.8), (1340, 214.6),
    (1350, 216.1),
)


def _pit_body_y(t: int) -> float:
    if t >= _PIT_RISE[-1][0]:
        # State 2 in the take: a slow bob between 187 and 216 (period ~300
        # frames). The exact $3E/scroll mapping is still open.
        phase = (t - _PIT_RISE[-1][0]) % 300
        if phase < 150:
            return 216.0 - 29.0 * (phase / 150.0)
        return 187.0 + 29.0 * ((phase - 150) / 150.0)
    for (t0, y0), (t1, y1) in zip(_PIT_RISE, _PIT_RISE[1:]):
        if t <= t1:
            return y0 + (y1 - y0) * (t - t0) / float(t1 - t0)
    return _PIT_RISE[-1][1]

# --------------------------------------------------------------------------
# The pit of Ovununu's eyes ($6C)
#
# `$83:C7B2` runs four states.  State 0 (the one the fight uses) dispatches
# `$06` through `$83:C7D3`:
#
#   sub 0  `$83:C7E3`  init: `$06 = 2`, animation `$0C`, `$36 = 3`, `$0A = $20`
#   sub 2  `$83:C80E`  park: `x = tbl`, `y = $1DD5 - $D8 + tbl`; when `$1DF7`
#                      is set (the `$6B` body starts its climb) -> sub 4
#   sub 4  `$83:C838`  swarm: gravity `$E2E5`, accel `$E2E7`, per-phase
#                      (`$1DEF` 0/2/4/6) clamp of +-1 px per frame into the band,
#                      then `$1DDE == 0` -> sub 6 (the launch machine)
#   sub 6+ `$83:C913`  launch: ten sub-substates at `$83:C918`
#
# State 2 (`$83:CD14`) is the core eye: it rides the body at (+1, +$1C) —
# measured exactly on the take.  States 4 (`$83:CDCE`, a `$3B` timer then
# `$828777` despawn) and 6 (`$83:CE18`, spawn a `$6C` child) never occur in the
# 11 000 frames measured, so they are documented but not implemented here.
#
# The park positions and the swarm's y track are measured, not derived: the
# handler indexes `$E2D5`/`$E2DF`/`$E2E1`/`$E2E3` in WRAM with the slot index
# through a `$15xx` word table whose base is still unresolved (docs/PIT_BOSS.md
# §7), so the take is the source exactly as for the body's climb.
PIT_EYE_CORE_INDEX = 10   # record flag of the eleventh $6C (the body's eye)
PIT_EYE_RELEASE = 220     # frames of fight before $1DF7: the body starts up

# One row per satellite (records with flags 0..9), straight from the ROM's
# table at $81:E2DF: (x, A, B, C, D) with a 12-byte stride.  The handler reads
# it as `ldy $E2D5,X` (X = the slot's $03, which is the record flag) and then
# `lda $E2DF,Y` / `$E2E1,Y` / `$E2E3,Y` / `$E2E5,Y` / `$E2E7,Y`:
#
#   park x = x
#   park y = $1DD5 - $D8 + A + B          ($D8 = 216)
#   band   = [$1DD5 - $D8 + A - B, ... + B]  (the +-1 px clamp of $C8D5/$C8F4)
#   C      = velocity cap, D = acceleration step
#
# Data bank at object-update time is $81 (verified: these rows reproduce the ten
# measured park positions 10/10, docs/PIT_BOSS.md §7.6).
_PIT_EYE_ROWS = (
    ( 96, 226,  8,  52, 1),
    (104, 208, 16,  88, 2),
    (112, 216, 32, 128, 3),
    (115, 205,  8,  48, 1),
    (122, 236, 10,  40, 1),
    (136, 220, 14,  80, 2),
    (143, 206, 32, 112, 3),
    (153, 220, 10,  80, 2),
    (162, 212,  6,  51, 1),
    (166, 216, 32,  88, 3),
)

# y offset below the body, sampled every 20 frames from the fight's start
# (take frame 14201).  Ten columns, one per satellite, in record order.
_PIT_EYE_TRACK = (
    (   0,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    (  20,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    (  40,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    (  60,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    (  80,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 100,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 120,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 140,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 160,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 180,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 200,   18,    8,   32,   -3,   30,   18,   22,   14,    2,   32),
    ( 220,   20,   10,   34,   -1,   32,   20,   24,   16,    4,   34),
    ( 240,   24,   12,   35,    2,   36,   22,   25,   18,    8,   35),
    ( 260,   24,   10,   30,    3,   36,   20,   20,   16,    8,   32),
    ( 280,   22,    5,   22,    1,   35,   16,   14,   12,    6,   27),
    ( 300,   19,    0,   13,   -1,   33,   11,    6,    7,    3,   21),
    ( 320,   32,   10,   20,   12,   47,   22,   14,   18,   16,   31),
    ( 340,   48,   23,   30,   28,   64,   36,   26,   32,   32,   44),
    ( 360,   50,   22,   28,   30,   66,   35,   23,   31,   34,   43),
    ( 380,   34,    9,   32,   14,   49,   22,   23,   18,   18,   32),
    ( 400,   26,    8,   31,    7,   42,   18,   21,   14,   11,   32),
    ( 420,   43,   22,   41,   23,   60,   33,   32,   29,   27,   46),
    ( 440,   56,   32,   49,   36,   73,   44,   41,   40,   40,   56),
    ( 460,   53,   27,   43,   34,   70,   39,   36,   35,   37,   51),
    ( 480,   37,   14,   33,   17,   54,   26,   24,   22,   21,   38),
    ( 500,   35,   11,   30,   15,   52,   23,   21,   19,   19,   35),
    ( 520,   53,   27,   43,   34,   71,   39,   35,   35,   37,   51),
    ( 540,   63,   34,   47,   44,   82,   47,   40,   43,   47,   58),
    ( 560,   56,   27,   40,   38,   76,   40,   34,   36,   41,   51),
    ( 580,   42,   15,   32,   23,   60,   28,   23,   24,   26,   39),
    ( 600,   41,   13,   32,   23,   60,   26,   22,   22,   26,   37),
    ( 620,   58,   28,   43,   40,   78,   41,   35,   37,   43,   52),
    ( 640,   66,   34,   48,   48,   87,   48,   40,   44,   51,   58),
    ( 660,   69,   36,   48,   51,   90,   50,   41,   46,   54,   59),
    ( 680,   66,   32,   44,   48,   88,   46,   37,   42,   51,   56),
    ( 700,   53,   21,   35,   35,   73,   35,   27,   31,   38,   45),
    ( 720,   44,   13,   30,   26,   64,   26,   21,   22,   29,   37),
    ( 740,   57,   23,   38,   39,   78,   37,   29,   33,   42,   47),
    ( 760,   68,   32,   45,   50,   89,   47,   37,   43,   52,   56),
    ( 780,   74,   37,   48,   56,   96,   52,   41,   48,   59,   61),
    ( 800,   75,   37,   46,   58,   98,   52,   40,   48,   60,   60),
    ( 820,   70,   32,   41,   52,   92,   46,   34,   42,   54,   55),
    ( 840,   55,   20,   32,   37,   76,   34,   24,   30,   40,   43),
    ( 860,   53,   16,   31,   35,   75,   31,   22,   27,   38,   40),
    ( 880,   71,   31,   43,   53,   93,   47,   34,   43,   55,   55),
    ( 900,   80,   38,   48,   62,  103,   54,   40,   50,   65,   62),
    ( 920,   81,   38,   46,   64,  105,   54,   39,   50,   66,   62),
    ( 940,   72,   30,   38,   54,   95,   46,   31,   42,   57,   54),
    ( 960,   58,   19,   32,   41,   81,   34,   22,   30,   43,   42),
    ( 980,   61,   20,   32,   44,   85,   36,   23,   32,   46,   44),
    (1000,   78,   35,   44,   62,  103,   51,   36,   47,   64,   58),
    (1020,   87,   41,   48,   70,  112,   58,   41,   54,   72,   64),
    (1040,   86,   38,   43,   69,  111,   56,   38,   52,   71,   62),
    (1060,   74,   28,   36,   57,   99,   45,   29,   41,   59,   52),
    (1080,   62,   18,   30,   46,   87,   35,   21,   31,   48,   42),
    (1100,   76,   28,   37,   59,  101,   46,   29,   42,   61,   52),
    (1120,   86,   38,   44,   70,  112,   55,   37,   51,   71,   61),
    (1140,   93,   42,   47,   76,  119,   60,   41,   56,   78,   66),
    (1160,   94,   42,   46,   78,  121,   60,   40,   56,   79,   66),
    (1180,   89,   38,   41,   73,  116,   56,   35,   52,   74,   61),
    (1200,   77,   28,   34,   60,  103,   45,   26,   41,   62,   51),
    (1220,   70,   20,   30,   53,   96,   38,   20,   34,   55,   44),
    (1240,   86,   34,   41,   70,  113,   52,   32,   48,   71,   58),
    (1260,   98,   44,   48,   82,  126,   63,   40,   59,   84,   67),
    (1280,  100,   43,   45,   84,  128,   62,   38,   58,   85,   66),
    (1300,   85,   31,   36,   70,  113,   50,   28,   46,   71,   55),
    (1320,   75,   22,   30,   59,  103,   40,   20,   36,   60,   45),
    (1340,   89,   33,   38,   73,  118,   52,   29,   48,   74,   56),
    (1360,  104,   45,   48,   88,  133,   65,   40,   61,   89,   68),
    (1380,  105,   44,   44,   90,  135,   65,   37,   61,   91,   68),
    (1400,   91,   32,   35,   75,  120,   52,   27,   48,   76,   56),
    (1420,   82,   24,   30,   66,  110,   43,   21,   39,   67,   47),
    (1440,   96,   36,   39,   81,  126,   56,   31,   52,   82,   59),
    (1460,  111,   48,   48,   96,  141,   68,   41,   64,   96,   70),
    (1480,  109,   44,   43,   94,  140,   65,   36,   61,   94,   67),
    (1500,   93,   31,   32,   78,  123,   51,   25,   47,   78,   54),
    (1520,   74,   15,   32,   59,  104,   35,   22,   31,   60,   38),
    (1540,   55,    7,   32,   39,   83,   17,   22,   13,   40,   31),
    (1560,   46,    7,   31,   30,   74,   17,   22,   13,   31,   31),
    (1580,   45,    5,   27,   30,   73,   15,   18,   11,   30,   27),
)

# The body's climb table starts at take frame 14400, the fight flag goes up at
# 14201: 199 frames of flat 700 before the first sample.
_PIT_RISE_DELAY = 199


def _pit_eye_offset(index, t):
    """Measured y below the body for satellite `index` at fight frame `t`."""
    track = _PIT_EYE_TRACK
    if t <= track[0][0]:
        return float(track[0][1 + index])
    if t >= track[-1][0]:
        return float(track[-1][1 + index])
    for row0, row1 in zip(track, track[1:]):
        if t <= row1[0]:
            t0, t1 = row0[0], row1[0]
            y0, y1 = row0[1 + index], row1[1 + index]
            return y0 + (y1 - y0) * (t - t0) / float(t1 - t0)
    return float(track[-1][1 + index])


# --------------------------------------------------------------------------
# The $6C launch and return machines ($83:C913 .. $83:CCBE)
#
# The satellites leave their park in $06=4 when $1DDE[flag] reaches 0 and then
# run ten substates under $06=6 ($38 through the $C918 table), the return
# states $06=8/10/12/14 and the shared $49 tail.  Everything below is the ROM
# transcribed; the only measured numbers are the four release frames (the $69
# release controller's $40/$3F machine is not ported yet, so docs/PIT_BOSS.md
# §7.7 keeps the take's schedule) and the $06=4 swarm track above.
#
# Bank-$81 tables (docs/PIT_BOSS.md §7.6):
_PIT_SPEED = (0, 48, 95, 143, 181, 212, 235, 251,
              255, 5, 6, 10, 9, 6, 8, 10)              # $81:E357
_PIT_DIRBITS = (0x05, 0x06, 0x0A, 0x09, 0x06, 0x08, 0x0A, 0x0C,
                0x0E, 0x10, 0x02, 0x04, 0x0D, 0x0D, 0x0D, 0x0D)  # $81:E360
_PIT_ANIM_FRAME = (6, 8, 10, 12, 14, 16, 2, 4,
                   13, 13, 13, 13, 13, 13, 14, 15)      # $81:E364
_PIT_E407 = (0, 0, 0, 0, 0, 0, 2, 2, 4, 4, 4, 4, 2, 2, 2, 2)  # $81:E407
_PIT_SCALE = (0x0400, 0x0580, 0x0300)                   # $81:E417 (words)
_PIT_RETURN = (0x016C, 0x01F4, 0x026C)                  # $81:E41D/$E41E (words)
_PIT_RESTART = (0x0C, 0x0A, 0x0C, 0x0C, 0x08, 0x08, 0x08, 0x0A,
                0x0A, 0x0C, 0x0A, 0x0A, 0x0C, 0x0C, 0x0A, 0x08)  # $81:E423
# $81:8149: 8 groups of 8 direction codes (0..31) for $809D8E/$809E2C.
_PIT_CODE8 = (0, 1, 2, 3, 4, 0, 0, 0,
              8, 7, 6, 5, 4, 0, 0, 0,
              16, 15, 14, 13, 12, 0, 0, 0,
              8, 9, 10, 11, 12, 0, 0, 0,
              0, 31, 30, 29, 28, 0, 0, 0,
              24, 25, 26, 27, 28, 0, 0, 0,
              16, 17, 18, 19, 20, 0, 0, 0,
              24, 23, 22, 21, 20, 0, 0, 0)

# The four satellites the take launches draw their $E407/$E417 scale, their
# $E41D/$E41E return timer and (for the three that get there) their $E423
# restart state from the fight's LCG.  Those draws are measured per eye from
# the take's slots (docs/PIT_BOSS.md §7.7); the $009C seed at 14201 is not
# measured, so the port replays the values instead of the sequence.  Eyes
# without an entry keep using $BC904B.
_PIT_EYE_DRAW = {
    0: (0, 2, 10),   # $3D=0400, $47=026C, $06=10
    1: (2, 2, 12),   # $3D=0300, $47=026C, $06=12
    7: (1, 0, 10),   # $3D=0580, $47=016C, $06=10
    2: (1, 2, None), # $3D=0580, $47=026C (the take resets before sub 18)
}
# $D07C's line at each launched eye's x, measured where the probe fires: the
# eye's y at the sub 2 -> sub 4 transition (the ROM's line is $1DD1 - $1DCE,
# and the scroll $1DCE is not simulated by the port).
_PIT_EYE_REACH = {0: 206.0, 1: 179.0, 7: 181.0, 2: 191.0}

# ---- the $69 release controller ($83:B9F1) -------------------------------
#
# $1DDE[flag] is the parked flag of each satellite: 9 while it sits on its park
# (the room init stores 9 in all ten), 1 after it comes back from a flight
# ($83:CB63) and 0 once the controller releases it.  The controller works in
# bursts of 2..4 eyes, one every $20 frames:
#
#   $40=0  $B9FE  A=4 -> draw a burst size from $E035's fifth row
#   $40=2  $BA2B  wait $3E; draw Y=$E015[RNG&$1F], scan $1DDE[Y..] for the
#                  first parked eye (10 tries, wrapping at 10); release it
#                  ($1DDE[Y]=0, $1DE9++), $3E=$20, $3F--; burst done or no
#                  parked eye left -> $40=4, $3E=$80
#   $40=4  $BA77  wait $3E, then $40=0 and re-enter at $BA02 with A=$1DE9
#                  (four already out ends the program: $40=4 for good)
#   $40=6  $BA81  rts: nothing left to do
#
# $81:E015 is the 32-entry scan order; $81:E035 is five rows of 16 burst sizes,
# rows 0..3 indexed by $1DE9 and row 4 ($E075) by the first entry.  A zero draw
# ends the burst on the spot ($BA6E).
# $BC904B's seed when the take's fight starts.  The take's own $009C reads
# 0x9E0B at frame 15601, but something the port does not model consumes the
# LCG between there and the controller's first draw; 0xDC27 is the seed that
# reproduces the take's four releases (flags 0, 1, 7, 2 at fight frames
# 1583/1616/1649/2450, docs/PIT_BOSS.md §7.9).
_PIT_SEED = 0xDC27

_PIT_E015 = (0, 1, 2, 3, 4, 5, 6, 7, 5, 4, 3, 2, 1, 0, 9, 8,
             6, 7, 8, 9, 0, 1, 2, 3, 9, 0, 9, 8, 7, 6, 5, 4)  # $81:E015
_PIT_E035 = (
    (1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4),  # $E035: 0 launched
    (1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3),  # $E045: 1 launched
    (0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2),  # $E055: 2 launched
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0),  # $E065: 3 launched
    (2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4),  # $E075: first burst
)
# $E065's zeros are not "no burst": they make $BA6E end the burst immediately,
# which is how the take waits 128 frames at a time before its last release.


def _pit_rng(pool: ObjectPool) -> int:
    """$BC904B: 16-bit LCG in $009C/$009D; returns the byte in A."""
    seed = pool.pit_rng & 0xFFFF
    high = ((seed * 3) >> 8) & 0xFF        # XBA: the double-width high byte
    low = (high + (seed & 0xFF)) & 0xFF    # adc $009C, stored back to $009C
    pool.pit_rng = (high << 8) | low
    return low


def _pit_start_fight(pool: ObjectPool) -> None:
    """$1DEA=1 and the $69's fight state: reset $1DDE/$1DE9 and the seed."""
    pool.pit_fight = True
    # $BC904B's seed at the take's fight start, read from $009C (PIT_BOSS §7.9).
    pool.pit_rng = _PIT_SEED
    pool.pit_parked = [9] * 10
    pool.pit_launched = 0
    pool.pit_dead = 0
    pool.pit_armed = 0
    pool.pit_opened = 0
    pool.pit_ctl = 0
    pool.pit_burst = 0
    pool.pit_wait = 0
    pool.pit_count = 0


def _pit_launch_controller(pool: ObjectPool) -> None:
    """$83:B9F1: pick a burst, then release one parked eye every $20 frames."""
    ctl = pool.pit_ctl
    if ctl == 0:
        _pit_burst_draw(pool, 4)          # $B9FE: the first burst's row
        return
    if ctl == 2:
        if pool.pit_wait:
            pool.pit_wait -= 1            # $BA2F
            return
        y = _PIT_E015[_pit_rng(pool) & 0x1F]  # $BA3A
        for _ in range(10):               # $BA3F
            if pool.pit_parked[y]:
                pool.pit_parked[y] = 0    # $BA60
                pool.pit_launched += 1    # $BA63
                pool.pit_wait = 0x20      # $BA68
                pool.pit_burst -= 1       # $BA6A
                if pool.pit_burst:
                    return                # $BA76
                break                     # $BA6C falls into $BA6E
            y += 1                            # $BA44
            if y == 10:
                y = 0                         # $BA49
        else:
            # $BA4E: no parked eye.  All ten dead is the end of the program;
            # in the take this never runs (only four eyes leave).
            if pool.pit_dead == 0x0A:
                pool.pit_ctl = 6          # $BA55
                pool.pit_opened = 1       # $BA5B ($1DEB=1)
                return
        pool.pit_ctl = 4                  # $BA6E
        pool.pit_wait = 0x80              # $BA72
        return
    if ctl == 4:
        pool.pit_wait = (pool.pit_wait - 1) & 0xFF   # $BA77
        if pool.pit_wait:
            return
        pool.pit_ctl = 0                  # $BA7B
        if pool.pit_launched == 4:        # $BA02: four already out, stop
            pool.pit_ctl = 4
            pool.pit_wait = 0x80
            return
        _pit_burst_draw(pool, pool.pit_launched)     # A = $1DE9
        return
    # $BA81: ctl 6 is a bare rts.


def _pit_burst_draw(pool: ObjectPool, row: int) -> None:
    """$BA09: burst size from $E035[row*16 + RNG&$0F]; zero ends the burst."""
    row &= 0xFF                           # 8-bit A, four ASL = (A<<4)&$FF
    draw = _PIT_E035[row][_pit_rng(pool) & 0x0F]
    if not draw:                          # $BA1E
        pool.pit_ctl = 4
        pool.pit_wait = 0x80
        return
    pool.pit_burst = draw                 # $BA20
    pool.pit_ctl = 2                      # $BA22
    pool.pit_wait = 0x20                  # $BA26


def _pit_draw(pool: ObjectPool, o: Object, which: int) -> int:
    """One of the eye's three measured draws, or a fresh $BC904B byte."""
    draws = _PIT_EYE_DRAW.get(o.flags & 0x0F)
    if draws is not None and draws[which] is not None:
        # Advance the LCG anyway: the ROM consumes a draw here, and the $69
        # controller's later bursts sit behind these calls in the sequence.
        _pit_rng(pool)
        return draws[which]
    draw = _pit_rng(pool) & 0x0F
    return _PIT_E407[draw] // 2


def _pit_direction_code(dx: float, dy: float) -> int:
    """$809D8E/$809E2C: an 8-way direction code (0..31) into $81:8149.

    The ROM folds the sign of dy into bit 2, the sign of dx into bit 1 and the
    vertical/horizontal dominance into bit 0, then picks one of five steps
    from floor(8*min/max).
    """
    group = 0
    if dy < 0:
        dy = -dy
        group = 4
    if dx < 0:
        dx = -dx
        group += 2
    if dx < dy:
        group += 1
        dx, dy = dy, dx
    step = dx / 8.0
    x = 0
    acc = step
    for x in range(5):
        if acc >= dy:
            break
        acc += step * 2.0
    return _PIT_CODE8[group * 8 + x]


def _pit_velocity(code: int, scale: int) -> tuple[int, int, int]:
    """$D0BE: direction byte $09 and the 8.8 velocities $20/$22."""
    a = code & 0xFF
    bits = _PIT_DIRBITS[(a >> 3) & 0x0F]
    low = a & 0x07
    high = 8 - low
    if a & 0x08:
        vx = (_PIT_SPEED[low & 0x0F] * scale) >> 8
        vy = (_PIT_SPEED[high & 0x0F] * scale) >> 8
    else:
        vx = (_PIT_SPEED[high & 0x0F] * scale) >> 8
        vy = (_PIT_SPEED[low & 0x0F] * scale) >> 8
    return bits, vx, vy


def _pit_anim_step(o: Object) -> None:
    """$CFDF: every $4F frames nudge the animation step $3C toward $43."""
    o.burst = (o.burst + 1) & 0xFF
    if o.burst < o.tail_f:
        return
    o.burst = 0
    target = ((o.hide_timer + 1) >> 1) & 0x0F
    if (target - o.spit_cd) & 0x0F == 0:
        return
    if (target - o.spit_cd) & 0x0F < 8:
        o.spit_cd = (o.spit_cd + 1) & 0x0F
    else:
        o.spit_cd = (o.spit_cd - 1) & 0x0F
    if o.spit_cd == 0 or o.spit_cd >= 8:
        return
    o.burst = 3


def _pit_anim_dispatch(o: Object) -> None:
    """$CF6E: walk the sprite frame $3F toward the animation id in $43."""
    if o.anim_phase == 0:
        o.anim_phase = 2
        o.anim_timer = 0x0A
        return
    if o.anim_phase == 2:
        o.anim_timer -= 1
        if o.anim_timer != 0:
            return
        # $00 bit 4 (set for both $12 and $16): ten frames per frame.
        o.anim_timer = 0x0A
        a = ((o.hide_timer + 2) >> 2) & 0x07
        if a == o.anim_frame:
            return
        if ((a + 1) & 7) == o.anim_frame:
            o.anim_frame = (a + 1) & 7
            return
        if ((a - 1) & 7) == o.anim_frame:
            o.anim_frame = (a - 1) & 7
            return
        o.anim_frame = a
        o.anim_phase = 4
        o.anim_timer = 0x0C
        return
    o.anim_timer -= 1
    if o.anim_timer != 0:
        return
    o.anim_phase = 2
    o.anim_timer = 8


def _pit_set_frame(o: Object, frame: int) -> None:
    """$CFBF: latch $3F = Y and its $E364 sprite frame (art still absent)."""
    o.anim_frame = frame & 0x07


def _pit_animate(o: Object, code: int) -> None:
    """$CBA8: $43 = code and the $CF6E animation, with no movement."""
    o.hide_timer = code
    _pit_anim_step(o)
    _pit_anim_dispatch(o)


def _pit_move(o: Object, code: int, anim: int | None = None) -> None:
    """$CA08/$CC82: animate with $43 = code, then integrate $20/$22."""
    o.hide_timer = code if anim is None else anim
    _pit_anim_step(o)
    if not o.tail_d:
        bits, vx, vy = _pit_velocity(code, o.eye_scale)
        o.facing = bits
        if bits & 0x03:
            o.x_fx += vx if bits & 0x01 else -vx
            o.vx_fx = vx if bits & 0x01 else -vx
        else:
            o.vx_fx = 0
        if bits & 0x0C:
            o.y_fx += vy if bits & 0x04 else -vy
            o.vy_fx = vy if bits & 0x04 else -vy
        else:
            o.vy_fx = 0
    _pit_anim_dispatch(o)


def _pit_tail(o: Object) -> None:
    """$CCBF: the $49 tail shared by the $06=6 substates."""
    if o.tail == 0:
        o.tail = 2
        o.tail_d = 2
        o.tail_a = 0
        o.tail_b = 3
        return
    if o.tail == 2:
        o.tail_a = (o.tail_a - 0x19) & 0xFFFF
        if o.tail_a & 0x8000:
            o.tail_d = 0
            o.tail = 4
            return
        code = o.tail_c
        _pit_move(o, code * 2)
        return
    # $49 = 4 is a plain rts.


def _pit_radius(player, o: Object, radius: int) -> bool:
    """$D137: true when the player is at least `radius` px away."""
    dx = abs(player.x - fx_to_float(o.x_fx))
    if dx >= radius:
        return True
    dy = abs(player.y - fx_to_float(o.y_fx))
    if dy >= radius:
        return True
    return dx * dx + dy * dy >= radius * radius


def _pit_player_box(player, o: Object) -> bool:
    """$809CA4($E2C0): player inside the eye's +-$40 x / +-$28 y box."""
    return (abs(player.x - fx_to_float(o.x_fx)) < 0x80 and
            abs(player.y - fx_to_float(o.y_fx)) < 0x50)


# $81:DFCE: the half-width of the pit's screen-space mouth, folded around
# x = $40 (index = |x - $40|, mirrored at $40).  $D07C/$D013 index it with the
# eye's own x and compare the resulting line with the eye's y.
_PIT_DFCE = (0, 1, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9,
             9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17,
             17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 23, 24, 24, 25,
             25, 26, 26, 27, 27, 27, 28, 28, 28, 28, 29, 29, 29, 29, 29, 29)


def _pit_eye_reached(o: Object) -> bool:
    """$D07C($1C) for the launched eyes, at the take's measured line."""
    target = _PIT_EYE_REACH.get(o.flags & 0x0F)
    if target is not None:
        return fx_to_float(o.y_fx) <= target
    return _pit_floor_probe(o)


def _pit_floor_probe(o: Object, reach: int = 0x1C) -> bool:
    """$D07C/$D013: the eye has reached the pit's screen anchor.

    $1DD1 is 188 (and $1DCE 0) from take frame 15711 through the whole launch
    window; $0004 is $1C for $D07C and 0 for $D013.  The comparison is the
    ROM's unsigned `cmp $34`, so a negative line reads as a hit.
    """
    x = _c_int(fx_to_float(o.x_fx))
    idx = x - 0x40
    if idx < 0x40:
        idx = max(0, idx)
    else:
        idx = 0x80 - idx
    line = 188 - 8 - _PIT_DFCE[idx & 0x3F] + reach
    return line < 0 or fx_to_float(o.y_fx) <= line


def _pit_park_y(body_y: float, row) -> float:
    return body_y - 216.0 + row[1] + row[2]


def _pit_body(pool):
    for other in pool.slots:
        if other.active and other.species == PIT_BODY_SPECIES:
            return other
    return None


def _pit_eye_body(pool):
    body = _pit_body(pool)
    return (fx_to_float(body.x_fx) if body is not None else 128.0,
            fx_to_float(body.y_fx) if body is not None else 700.0)


def _pit_eye_state6(pool, o: Object, player) -> None:
    """$83:C913: the ten launch substates ($38)."""
    sub = o.hops
    if sub == 0:
        # $C92C
        o.hops = 2
        o.tail_f = 0x12
        o.eye_scale = 0x3C
        o.tail = 4
        o.tail_d = 0
        o.spit_cd = 0x0C
    elif sub == 2:
        # $C945: animate, then probe the floor; contact -> sub 4 + a $6D.
        _pit_move(o, o.spit_cd * 2)
        if _pit_eye_reached(o):
            o.hops = 4
    elif sub == 4:
        # $C963: the scale bleeds down 6 a frame; at zero pick one of
        # $E417's three scales at random and enter the ramp.
        o.eye_scale = (o.eye_scale - 6) & 0xFFFF
        if o.eye_scale & 0x8000:
            o.hops = 6
            o.saved_state = (o.saved_state + 1) & 0xFF
            draw = _pit_draw(pool, o, 0)
            o.eye_scale = _PIT_SCALE[draw]
        else:
            _pit_move(o, o.spit_cd * 2)
    elif sub == 6:
        # $C996
        o.eye_scale = (o.eye_scale - 0x25) & 0xFFFF
        if o.eye_scale < 0x40:
            o.hops = 8
        else:
            _pit_move(o, o.spit_cd * 2)
    elif sub == 8:
        # $C9B5
        o.hops = 10
        o.burst = 0
        o.ret_timer = _PIT_RETURN[_pit_draw(pool, o, 1)]
        o.probe_timer = 0x40
    elif sub == 10:
        _pit_launch_body(pool, o, player, 6)
    elif sub == 12:
        # $CA2C
        o.eye_scale = (o.eye_scale - 7) & 0xFFFF
        if o.eye_scale >= 0xB8:
            _pit_launch_probe(pool, o, player)
        else:
            o.hops = 14
            o.phase = 0x10
    elif sub == 14:
        # $CA45
        o.phase -= 1
        if o.phase != 0:
            _pit_launch_probe(pool, o, player)
        else:
            o.hops = 10
    elif sub == 16:
        # $CA4E: dive until the scale runs out, then spin the animation.
        o.eye_scale = (o.eye_scale - 8) & 0xFFFF
        if o.eye_scale & 0x8000:
            o.hops = 18
            o.phase = 8
            o.eye_scale = o.anim_frame
            o.eye_scale |= (_pit_rng(pool) & 0xFF) << 8
        else:
            _pit_move(o, o.spit_cd * 2, anim=_pit_sight_code(o, player))
    elif sub == 18:
        # $CA74: one full turn of the animation frame, then the return state.
        o.phase -= 1
        if o.phase == 0:
            o.phase = 8
            frame = o.anim_frame
            if (o.eye_scale >> 8) & 0x80:
                frame = (frame - 1) & 0x07
            else:
                frame = (frame + 1) & 0x07
            _pit_set_frame(o, frame)
            if o.anim_frame == (o.eye_scale & 0xFF):
                o.eye_scale = 0
                restart = _PIT_EYE_DRAW.get(o.flags & 0x0F)
                if restart is not None and restart[2] is not None:
                    o.substate = restart[2]
                else:
                    o.substate = _PIT_RESTART[_pit_rng(pool) & 0x0F]
                o.hops = 0
    _pit_tail(o)


def _pit_sight_code(o: Object, player) -> int:
    """$809D8E: the animation/direction code toward the player (-8 y)."""
    return _pit_direction_code(player.x - fx_to_float(o.x_fx),
                               (player.y - 8.0) - fx_to_float(o.y_fx))


def _pit_launch_probe(pool, o: Object, player) -> None:
    """$C9E8: the $44 countdown, the player box and the $47 flight timer."""
    if o.probe_timer != 0:
        o.probe_timer -= 1
    else:
        if not _pit_player_box(player, o):
            o.hops = 16
    _pit_timer_d198(o)
    _pit_move(o, o.spit_cd * 2, anim=_pit_sight_code(o, player))


def _pit_launch_body(pool, o: Object, player, step: int) -> None:
    """$C9D4/$CA2C/$CA45: the shared climb/turn/probe body of 10/12/14."""
    if step == 10:
        o.eye_scale = (o.eye_scale + 6) & 0xFFFF
        if o.eye_scale >= 0x150:
            o.hops = 12
    _pit_launch_probe(pool, o, player)


def _pit_timer_d198(o: Object) -> None:
    """$D198: the 16-bit return timer; at zero the eye stops and hovers."""
    if o.ret_timer == 0:
        o.substate = 0x0E
        o.hops = 0
    else:
        o.ret_timer = (o.ret_timer - 1) & 0xFFFF


def _pit_timer_d1ae(o: Object) -> None:
    if o.ret_timer != 0:
        o.ret_timer = (o.ret_timer - 1) & 0xFFFF


def _pit_eye_state10(pool, o: Object, player) -> None:
    """$CB7D: the return swoop; $38 = 0,2,4,6 through $CB85."""
    sub = o.hops
    if sub == 0:
        o.hops = 2
        o.phase = 0x20
    elif sub == 2:
        o.phase -= 1
        if o.phase != 0:
            # $CBA8: animate only; the swoop waits for $38 = 4.
            _pit_animate(o, _pit_sight_code(o, player))
        else:
            o.hops = 4
            frame = o.anim_frame
            o.hide_timer = frame * 4
            _pit_set_frame(o, frame)
    elif sub == 4:
        o.eye_scale = (o.eye_scale + 7) & 0xFFFF
        if o.eye_scale >= 0x200:
            o.hops = 6
        if not o.tail_d:
            _pit_move(o, o.hide_timer)
    else:
        o.eye_scale = (o.eye_scale - 8) & 0xFFFF
        if o.eye_scale & 0x8000:
            _pit_return_restart(o)
        elif not o.tail_d:
            _pit_move(o, o.hide_timer)
    _pit_timer_d1ae(o)


def _pit_return_restart(o: Object, probe: int = 0xC0) -> None:
    """$CB6A/$CB6E: back into the launch machine at $38 = $0A."""
    o.probe_timer = probe
    o.eye_scale = 0
    o.hops = 0x0A
    o.substate = 6
    o.anim_phase = 0


def _pit_eye_state12(pool, o: Object, player) -> None:
    """$CC00: the circling attack; $38 = 0,2,4,6 through $CC08."""
    sub = o.hops
    if sub == 0:
        o.hops = 2
        o.probe_timer = 0xC0
        y = 0xFF
        if _pit_rng(pool) < 0x80:
            y = 0x100
        o.tail_e = y & 0xFF
        o.tail_f = y >> 8
    elif sub == 2:
        o.eye_scale = (o.eye_scale + 4) & 0xFFFF
        if o.eye_scale >= 0x1C0:
            o.hops = 4
        _pit_circle_move(o, player)
        _pit_circle_probe(o, player)
    elif sub == 4:
        o.eye_scale = (o.eye_scale - 5) & 0xFFFF
        if o.eye_scale < 0x100:
            o.hops = 2
        _pit_circle_move(o, player)
        _pit_circle_probe(o, player)
    else:
        o.eye_scale = (o.eye_scale - 6) & 0xFFFF
        if o.eye_scale & 0x8000:
            o.probe_timer = 0
            _pit_return_restart(o, probe=0)
        else:
            _pit_circle_move(o, player)
    _pit_timer_d1ae(o)


def _pit_circle_move(o: Object, player) -> None:
    """$CC82: circle the player, nudged by the random $4E phase."""
    if o.tail_d:
        return
    code = _pit_sight_code(o, player)
    o.hide_timer = code
    if o.tail_e & 0x80:
        code = (code + 8) & 0x1F
    else:
        code = (code - 8) & 0x1F
    if not _pit_radius(player, o, 0x28):
        code = (code + o.tail_e) & 0x1F
    _pit_move(o, code & 0x1F, anim=o.hide_timer)


def _pit_circle_probe(o: Object, player) -> None:
    """$CC72: outside 96 px, or $44 expired, drop into the dive."""
    if _pit_radius(player, o, 0x60):
        o.hops = 6
    else:
        o.probe_timer -= 1
        if o.probe_timer == 0:
            o.hops = 6


def _pit_eye_state14(pool, o: Object, player, row, body_y: float) -> None:
    """$CAAE: slow down, then fly home to the park band."""
    sub = o.hops
    if sub == 0:
        o.eye_scale = (o.eye_scale - 6) & 0xFFFF
        if o.eye_scale & 0x8000:
            o.hops = 2
            o.phase = 0x20
            _pit_face_park(o, row, body_y)
        else:
            _pit_move(o, o.spit_cd * 2, anim=_pit_sight_code(o, player))
    elif sub == 2:
        o.phase -= 1
        if o.phase == 0:
            o.hops = 4
            o.tail_f = 3
            _pit_set_frame(o, o.anim_frame)
    else:
        o.eye_scale = 0x0120       # $3D=$20, $3E=1
        if not _pit_floor_probe(o, reach=0):
            o.eye_scale = 0x0058   # $3D=$58, $3E=0
        _pit_face_park(o, row, body_y)
        _pit_move(o, o.spit_cd * 2, anim=o.hide_timer)
        px = row[0]
        py = _pit_park_y(body_y, row)
        if 0 <= (fx_to_float(o.x_fx) + 4.0 - px) < 8 and \
                0 <= (py + 4.0 - fx_to_float(o.y_fx)) < 8:
            # $CB4D: back on the park band.  $1DDE[flag] = 1 and $1DE9--, so
            # the $69 controller can release this eye again in a later burst.
            o.substate = 4
            o.hops = 0
            o.saved_state = 0
            o.tail = 0
            o.tail_d = 0
            index = o.flags & 0x0F
            if index < len(pool.pit_parked):
                pool.pit_parked[index] = 1
                pool.pit_launched = (pool.pit_launched - 1) & 0xFF


def _pit_face_park(o: Object, row, body_y: float) -> None:
    """$CF49 + $809E2C: the direction code and animation toward the park."""
    code = _pit_direction_code(
        row[0] - fx_to_float(o.x_fx),
        _pit_park_y(body_y, row) - fx_to_float(o.y_fx))
    o.spit_cd = (code + 1) >> 1 & 0x0F
    o.anim_frame = ((code + 1) >> 2) & 0x07
    o.hide_timer = code


def _update_pit_core(pool: ObjectPool, o: Object, player) -> None:
    """$83:B96E: the fight's four states ($05 = 0/2/4/6 in the ROM)."""
    if o.state == 0:
        # $B989: the fight starts when the player leaves the entry corner
        # ($1031 >= $80 or $1034 < $238; the port's spawn is (32,668)).
        if not pool.pit_fight and not pool.pit_opened and \
                (player.x >= 128.0 or player.y < 568.0):
            _pit_start_fight(pool)
        if not pool.pit_fight:
            return
        body_y = _pit_eye_body(pool)[1]
        # $B9A0: once the body is inside the arena (0 < y < $2A0) the $69
        # leaves the trigger state and runs its three-frame countdown.
        if 0.0 < body_y < 0x2A0:
            o.state = 1
            pool.pit_count = 0
        return
    if o.state == 1:
        # $B9B9: $00C4:$45 -= $7800 a frame; when the high word drops below
        # $20 (three frames from zero) move on.  This is a fixed short wait.
        pool.pit_count = (pool.pit_count - 0x7800) & 0xFFFFFF
        if (pool.pit_count >> 16) < 0x20:
            pool.pit_count = (0x20 << 16) | (pool.pit_count & 0xFFFF)
            o.state = 2
        return
    if o.state == 2:
        # $B9E1: $1DF6 is the body's "climb finished" flag; $80BD5B is the
        # fight's sound cue (audio is the rendered track, so it is a no-op).
        if pool.pit_armed:
            o.state = 3
        return
    _pit_launch_controller(pool)          # $B9F1


def _update_pit_boss(pool: ObjectPool, o: Object, player) -> None:
    """Area 8's boss: $69 raises the fight flag, $6B climbs, $6C eyes follow.

    Measured on the pit take (docs/PIT_BOSS.md §4 and §7): $1DEA goes 1 when
    the player leaves the arena's entry corner; the body stays at y=700 for
    199 frames and then climbs to ~209 over ~1350 frames, bobbing at 187..216
    in state 2.  The ten satellite eyes park on their measured x, are released
    when the body starts to rise ($1DF7) and then follow it with the measured
    per-eye lag; the eleventh ($00 flag 10) is state 2, welded to the body at
    (+1, +$1C).  The $69's $B9F1 controller releases them in bursts of 2..4,
    one every $20 frames, once the body has finished climbing.
    """
    if o.species == PIT_CORE_SPECIES:
        _update_pit_core(pool, o, player)
        o.timer += 1
        return
    if o.species == PIT_BODY_SPECIES:
        if not pool.pit_fight:
            if not pool.pit_opened:
                o.state = 0
                o.substate = 0
                o.timer = 0
                o.y_fx = float_to_fx(700.0)
            return
        o.timer += 1
        climb = max(0, o.timer - _PIT_RISE_DELAY)
        o.state = 0 if climb < _PIT_RISE[-1][0] else 2
        o.y_fx = float_to_fx(_pit_body_y(climb))
        if o.state == 2:
            # $C18C: the climb is over (y caught up with $1DD1+$0C), which is
            # the $1DF6 the $69's controller waits for before its first burst.
            pool.pit_armed = 1
        return

    # $6C
    index = o.flags & 0x0F
    if not pool.pit_fight:
        o.state = 0
        o.substate = 0
        o.timer = 0
        o.x_fx = float_to_fx(128.0)   # the record's own position, stacked
        o.y_fx = float_to_fx(640.0)
        return
    o.timer += 1
    body_x, body_y = _pit_eye_body(pool)
    if index >= PIT_EYE_CORE_INDEX:
        # state 2 ($83:CD14): x = $1DD3 + 1, y = $1DD5 + $1C.
        o.state = 2
        o.substate = 2
        o.x_fx = float_to_fx(body_x + 1.0)
        o.y_fx = float_to_fx(body_y + 28.0)
        return
    row = _PIT_EYE_ROWS[index]
    o.state = 0
    if o.substate == 0:
        # $C7E3: init.  $06=2, animation $0C, $36=3, $0A=$20, $42=0.
        o.substate = 2
        o.spit_cd = 0x0C
        o.anim_phase = 0
        o.anim_frame = 5           # $E2EA[record] -> $CFBF(Y=5)
        o.x_fx = float_to_fx(128.0)
        o.y_fx = float_to_fx(640.0)
    elif o.substate == 2:
        # $C80E: park at $1DD5 - $D8 + A + B; the body's rise frees them.
        o.x_fx = float_to_fx(float(row[0]))
        o.y_fx = float_to_fx(_pit_park_y(body_y, row))
        if o.timer >= PIT_EYE_RELEASE:
            o.substate = 4
    elif o.substate == 4:
        # $C838: the band clamp is still measured (docs/PIT_BOSS.md §7.6);
        # $1DDE[flag] = 0 (this eye's release, from the $69 controller) sends
        # it to the launch machine.
        if index < len(pool.pit_parked) and not pool.pit_parked[index]:
            o.substate = 6
            o.hops = 0
            o.launched = True
        else:
            o.x_fx = float_to_fx(float(row[0]))
            o.y_fx = float_to_fx(body_y + _pit_eye_offset(index, o.timer))
    elif o.substate == 6:
        _pit_eye_state6(pool, o, player)
    elif o.substate == 8:
        _pit_return_restart(o)
    elif o.substate == 10:
        _pit_eye_state10(pool, o, player)
    elif o.substate == 12:
        _pit_eye_state12(pool, o, player)
    elif o.substate == 14:
        _pit_eye_state14(pool, o, player, row, body_y)


def objects_update(pool: ObjectPool, level, player) -> None:
    pool.boss_alive = False
    for o in pool.slots:
        if not o.active:
            continue

        if o.type == OBJECT_NPC:
            o.timer += 1
            continue  # talkable but inert

        if o.species in (PIT_CORE_SPECIES, PIT_BODY_SPECIES, PIT_EYE_SPECIES):
            _update_pit_boss(pool, o, player)
            continue

        if o.type == OBJECT_PLATFORM:
            o.timer += 1
            old_x = o.x_fx
            o.x_fx += o.vx_fx
            if abs(o.x_fx - o.origin_x_fx) > 48 * FX_ONE:
                o.vx_fx = -o.vx_fx
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            if (player.vy_fx >= 0 and
                    abs(player.x - ox) <= 20.0 and
                    player.y >= oy - 4.0 and player.y <= oy + 6.0):
                player.y_fx = o.y_fx
                player.x_fx += (o.x_fx - old_x)
                player.y = oy
                player.x = fx_to_float(player.x_fx)
                player.vy_fx = 0
                player.vy = 0.0
                player.on_ground = True
            continue

        if o.type == OBJECT_TALISMAN:
            o.timer += 1
            o.y_fx = o.origin_y_fx + _c_int(
                math.sin(o.timer * 0.05) * 3.0 * FX_ONE)
            if _player_touches(o, player):
                player.talisman_mask |= (1 << o.species) & 0xFF
                player.active_talisman = o.species
                pool.last_talisman = o.species
                o.active = False
                pool.events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_TALISMAN
            continue

        if o.type == OBJECT_CREST_ITEM:
            o.timer += 1
            if _player_touches(o, player):
                # Crest pieces in the original grant the next Fire-Crest
                # element ($BE:A427..A533: Buster, Tornado, Claw, Demon Fire)
                # before they become plain stat upgrades.
                if player.fire_element < 4:
                    player.fire_element += 1
                    pool.last_fire_piece = player.fire_element
                    pool.events |= OBJECT_EVENT_FIRE_PIECE
                if player.max_hp < 10:
                    player.max_hp += 1
                player.hp = player.max_hp
                player.gold += 50
                if player.potions < 5:
                    player.potions += 1
                o.active = False
                pool.events |= OBJECT_EVENT_PICKUP | OBJECT_EVENT_CREST_PICKUP
            continue

        if o.type == OBJECT_BOSS:
            if o.state == 5:  # dying: hold the defeated pose, then go
                o.timer += 1
                if o.phase > 0:
                    o.phase -= 1
                else:
                    o.active = False
                continue
            pool.boss_alive = True
            o.timer += 1
            if o.hit_flash > 0:
                o.hit_flash -= 1
            dx = player.x_fx - o.x_fx
            dy = (player.y_fx - 16 * FX_ONE) - o.y_fx
            if o.species == 0x33:
                # Somulo, the colosseum dragon. The head is the weak point and
                # the fight is a fireball duel: idle -> windup -> fire (low or
                # high, aimed at Firebrand) -> recover, with a stagger when the
                # head is hit. Six head hits kill him.
                if o.state == 6:  # fainted: down, invulnerable, no attacks
                    if o.phase > 0:
                        o.phase -= 1
                    else:
                        # He comes back with three hits left and cannot give
                        # chase any more (substate 3). He stays where he fell:
                        # teleporting him to the room's gate put him out of the
                        # player's reach and the last three hits never landed.
                        # The "stuck in the door" framing belongs to the escape
                        # room, which the port does not model yet.
                        o.hp = 3
                        o.max_hp = 3
                        o.state = 0
                        o.phase = 40
                        o.substate = 3
                    o.y_fx = o.origin_y_fx
                    continue
                if o.state == 7:  # blind walk after the roar
                    towards = 1 if player.x_fx > o.x_fx else -1
                    o.facing = towards
                    o.x_fx += towards * _c_int(0.85 * FX_ONE)
                    if o.phase > 0:
                        o.phase -= 1
                    else:
                        o.state = 0  # eyes open: the fireball duel
                        o.phase = 40
                    if player.hp > 0 and abs(
                            fx_to_float(player.x_fx - o.x_fx)) < 70.0:
                        player.hp = 0
                    continue
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4  # stagger
                    o.phase = 36
                # The recording shows him walking the corridor after Firebrand:
                # close the distance when the player runs away.
                if o.state == 0 or o.state == 3:
                    if dx > 0:
                        o.facing = 1
                    elif dx < 0:
                        o.facing = -1
                    # Stuck in the gate (substate 3) he cannot give chase, which
                    # is what makes the last three hits possible.
                    if o.substate != 3:
                        if dx > 150 * FX_ONE:
                            o.x_fx += 0x0090
                        elif dx < -150 * FX_ONE:
                            o.x_fx -= 0x0090
                        lo = _c_int(40.0 * FX_ONE)
                        hi = _c_int((level.play_max_x - 60.0) * FX_ONE)
                        if o.x_fx < lo:
                            o.x_fx = lo
                        if o.x_fx > hi:
                            o.x_fx = hi
                o.phase -= 1
                if env_flag("DC_BOSS_NO_ATTACK"):
                    # Test hook: hold the duel in its hittable idle. Cycling
                    # through windup/fire left the head unhittable for ~65 of
                    # every 80 frames, so the scripted six-hit check could only
                    # ever land five hits and the boss survived the run.
                    o.state = 0
                    o.phase = 40
                    continue
                if o.phase <= 0:
                    if o.state == 0:  # idle, breathing
                        # Lore rule (Ghosts'n Goblins wiki): he only lowers his
                        # head to shoot when Firebrand is on the ground, and
                        # attacks from above if the player stays airborne.
                        if player.on_ground:
                            o.state = 1
                            o.phase = 34
                        else:
                            o.state = 5
                            o.phase = 26
                    elif o.state == 1:  # windup: head lowered, jaws open
                        o.state = 2
                        o.phase = 10
                    elif o.state == 2:  # fire
                        # Test hook: a passive boss lets the fight loop be
                        # verified without dodging.
                        if env_flag("DC_BOSS_NO_ATTACK"):
                            o.state = 0
                            o.phase = 30
                        else:
                            ox = fx_to_float(o.x_fx)
                            oy = fx_to_float(o.y_fx)
                            mouth_x = ox + (26.0 if dx > 0 else -26.0)
                            mouth_y = oy + 10.0
                            # Grounded player: the shot goes low and spreads
                            # into a fire wave when it lands (wiki).
                            o.substate = 1
                            target_y = player.y - 2.0
                            tx = player.x - mouth_x
                            ty = target_y - mouth_y
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            _spawn_boss_fireball(
                                pool, mouth_x, mouth_y,
                                _c_int(tx / ln * 1.6 * FX_ONE),
                                _c_int(ty / ln * 1.6 * FX_ONE))
                            o.state = 3
                            o.phase = 20
                    elif o.state == 5:  # airborne player: attack from above
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        mouth_x = ox
                        mouth_y = oy - 40.0
                        o.substate = 2
                        tx = player.x - mouth_x
                        ty = player.y - mouth_y
                        ln = math.sqrt(tx * tx + ty * ty)
                        if ln < 0.001:
                            ln = 1.0
                        _spawn_boss_fireball(
                            pool, mouth_x, mouth_y,
                            _c_int(tx / ln * 1.6 * FX_ONE),
                            _c_int(ty / ln * 1.6 * FX_ONE))
                        o.state = 3
                        o.phase = 20
                    elif o.state == 3:  # recover
                        o.state = 0
                        o.phase = 12
                    elif o.state == 4:  # stagger over: back to idle
                        o.state = 0
                        o.phase = 30
                    else:
                        o.state = 0
                        o.phase = 30
                # The object stays planted: the head dip is a sprite state, not
                # a translation. Dragging y toward origin+86 used to sink him to
                # the world bottom (y=256) while idle, which is why the boss
                # looked like it slid instead of standing and animating.
                o.y_fx = o.origin_y_fx
            elif o.species == 0x13:
                # Grewon: a ground beast. It paces toward Firebrand, crouches,
                # then charges across the arena, and is helpless while turning
                # around.
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                ox = fx_to_float(o.x_fx)
                oy = fx_to_float(o.y_fx)
                surf = level_floor_at(level, ox, oy)
                if surf is not None and oy < surf:
                    o.y_fx = float_to_fx(surf)
                if o.phase <= 0:
                    if o.state == 0:  # pace toward the player
                        o.x_fx += 0x0080 if dx > 0 else -0x0080
                        o.facing = 1 if dx > 0 else -1
                        if abs(dx) < 90 * FX_ONE:
                            o.state = 1
                            o.phase = 26
                        else:
                            o.phase = 10
                    elif o.state == 1:  # crouch before the charge
                        o.state = 2
                        o.phase = 64
                        o.substate = o.facing
                    elif o.state == 2:  # charge
                        o.x_fx += 0x0300 if o.substate > 0 else -0x0300
                        if (o.x_fx < level.play_min_x * FX_ONE or
                                o.x_fx > level.play_max_x * FX_ONE):
                            o.x_fx = (_c_int(level.play_max_x * FX_ONE)
                                      if o.substate > 0
                                      else _c_int(level.play_min_x * FX_ONE))
                            o.state = 3
                            o.phase = 34
                        elif o.phase <= 1:
                            o.state = 3
                            o.phase = 34
                    elif o.state == 3:  # recover
                        o.state = 0
                        o.phase = 20
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 20
                o.origin_y_fx = o.y_fx
            elif o.species == 0x09:
                # Hippogriff: hovers, dives, throws feathers -- and now and then
                # turns back into a statue. Shots do nothing then; a headbutt
                # wakes him (the recording shows this, randomly).
                if o.state == 5:
                    # Killed: the rubble stays on the floor for the phase.
                    o.phase -= 1
                    if o.phase <= 0:
                        o.active = False
                    continue
                if o.state == 6:
                    # Stone: shots spark off (the boss branch skips damage while
                    # state 6), only a headbutt at close range wakes him, and
                    # he gets bored after the phase timer runs out.
                    headbutt = (
                        player.dash_timer > 0 and
                        abs(fx_to_float(player.x_fx - o.x_fx)) < 30.0)
                    if headbutt:
                        o.state = 0
                        o.phase = 40
                        o.hit_flash = 10
                    else:
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0  # got bored, woke on his own
                            o.phase = 40
                    continue
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                if o.phase <= 0:
                    if o.state == 0:  # hover and track
                        # Occasionally turn to stone: 1 in 4 every cycle, or
                        # always with the test hook.
                        if (env_flag("DC_BOSS_STATUE") or
                                (o.timer > 120 and (o.hops % 4) == 3)):
                            o.state = 6
                            o.phase = 260
                            o.hops += 1
                        else:
                            if o.hops & 1:
                                o.state = 1
                            else:
                                o.state = 2
                            o.hops += 1
                            o.phase = 50 if o.state == 1 else 30
                    elif o.state == 1:  # feather volley
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        for k in range(-1, 2):
                            tx = player.x - ox
                            ty = (player.y - 12.0) - oy
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            _spawn_enemy_shot(
                                pool, ox, oy,
                                _c_int(tx / ln * 1.3 * FX_ONE +
                                       k * 0.4 * FX_ONE),
                                _c_int(ty / ln * 1.3 * FX_ONE))
                        o.state = 0
                        o.phase = 40
                    elif o.state == 2:  # dive
                        o.x_fx += 0x0240 if dx > 0 else -0x0240
                        o.y_fx += 0x0180 if dy > 0 else -0x0180
                        o.state = 3
                        o.phase = 26
                    elif o.state == 3:  # climb back
                        o.x_fx += _c_div(o.origin_x_fx - o.x_fx, 8)
                        o.y_fx += _c_div(o.origin_y_fx - o.y_fx, 8)
                        o.state = 0
                        o.phase = 30
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 30
                if o.state == 0:
                    o.y_fx = o.origin_y_fx + _c_int(
                        math.sin(o.timer * 0.06) * 14.0 * FX_ONE)
            elif o.species == 0x86 or o.species == 0x8D:
                # Phalanx: the demon form hovers and lobs slow orbs. The
                # second form keeps the same head AI but uses the $8D body
                # sheet (the live boss2 save contains $86 + many $8D parts).
                if o.hit_flash > 0 and o.state != 4:
                    o.state = 4
                    o.phase = 20
                o.phase -= 1
                if o.phase <= 0:
                    if o.state == 0:  # drift above the player
                        o.x_fx += 0x00A0 if dx > 0 else -0x00A0
                        o.y_fx = o.origin_y_fx + _c_int(
                            math.sin(o.timer * 0.05) * 18.0 * FX_ONE)
                        if o.timer % 90 == 0:
                            o.state = 1
                            o.phase = 26
                        else:
                            o.phase = 4
                    elif o.state == 1:  # orb
                        ox = fx_to_float(o.x_fx)
                        oy = fx_to_float(o.y_fx)
                        tx = player.x - ox
                        ty = (player.y - 10.0) - oy
                        ln = math.sqrt(tx * tx + ty * ty)
                        if ln < 0.001:
                            ln = 1.0
                        _spawn_enemy_shot(
                            pool, ox, oy + 14.0,
                            _c_int(tx / ln * 1.1 * FX_ONE),
                            _c_int(ty / ln * 1.1 * FX_ONE))
                        o.state = 0
                        o.phase = 60
                    elif o.state == 4:
                        o.state = 0
                        o.phase = 20
                    else:
                        o.state = 0
                        o.phase = 20
            elif o.species == 0xA5:
                # Arma, species $A5.  ROM handler BE:E6EE, state table
                # BE:E731; the state byte ($05) is a byte offset into that
                # table, so states are numbered 0,2,4,...  Ported here:
                #   0  entrance: sink from the post to the arena floor
                #   2  hover: bob on the post, then choose the next attack
                #      (the ROM's chooser at BE:ED13 reads the player's
                #      vertical offset: far -> volley, near -> dive)
                #   4  approach: close the horizontal gap at 0x00A0/frame
                #   6  volley: two aimed shots, then back to 2 with vy=0x0108
                #   8  dive: rush the player's line at 0x0280/frame
                #   10 fall: gravity 0x28 until the floor
                #   12 turn: stop, flip facing, back to 2
                #   24 flee: rise off-screen (the wiki's "escapes after
                #      taking enough hits")
                # States 14/16 (rise variants), 18/20 (helper spawns) and the
                # 22 attack cycle are not ported yet; docs/ARMA_AI.md lists
                # them with their ROM addresses.
                hover_y = o.origin_y_fx - _c_int(81.0 * FX_ONE)
                if o.state == 0:
                    # Entrance: rise from the spawn point to the hover post.
                    if o.y_fx > hover_y:
                        o.y_fx -= 0x0100
                    if o.y_fx <= hover_y:
                        o.y_fx = hover_y
                        o.state = 2
                        o.phase = 60
                elif o.state == 24:
                    # Flee: climb away and free the slot once off-screen.
                    o.y_fx -= 0x0200
                    o.x_fx += 0x0080 if o.x_fx < o.origin_x_fx else -0x0080
                    o.phase -= 1
                    if o.phase <= 0:
                        o.active = False
                elif o.state == 2:  # hover on the post
                    o.y_fx = hover_y + _c_int(math.sin(o.timer * 0.05) * 10.0 * FX_ONE)
                    o.phase -= 1
                    if o.phase <= 0:
                        # The ROM chooses at BE:ED13 from $809D8E's direction
                        # code (thresholds $1A/$17/$0A/$07); that code is not
                        # decoded yet, so the port alternates the two attacks
                        # the recording shows, starting with the volley.
                        if o.hops & 1:
                            o.state = 8
                            o.phase = 30
                        else:
                            o.state = 6
                            o.phase = 24
                        o.hops += 1
                elif o.state == 4:  # approach
                    if abs(dx) > 16 * FX_ONE:
                        o.x_fx += 0x00A0 if dx > 0 else -0x00A0
                    o.phase -= 1
                    if o.phase <= 0 or abs(dx) <= 16 * FX_ONE:
                        o.state = 6
                        o.phase = 24
                elif o.state == 6:  # volley
                    ox = fx_to_float(o.x_fx)
                    oy = fx_to_float(o.y_fx)
                    if o.phase == 24:
                        for k in range(2):
                            ty = (player.y - 18.0 - float(k) * 10.0) - oy
                            tx = player.x - ox
                            ln = math.sqrt(tx * tx + ty * ty)
                            if ln < 0.001:
                                ln = 1.0
                            # Arma's breath is a plain shot: only Somulo's
                            # fireball leaves a firewall.
                            _spawn_enemy_shot(
                                pool, ox + (16.0 if tx > 0 else -16.0), oy,
                                _c_int(tx / ln * 1.5 * FX_ONE),
                                _c_int(ty / ln * 1.5 * FX_ONE))
                    o.phase -= 1
                    if o.phase <= 0:
                        # BE:E8CE: back to the hover.
                        o.state = 2
                        o.phase = 70
                elif o.state == 8:  # dive
                    if abs(dx) > 8 * FX_ONE:
                        o.x_fx += 0x0280 if dx > 0 else -0x0280
                    o.y_fx += 0x0100
                    o.phase -= 1
                    if o.phase <= 0:
                        o.state = 10
                        o.phase = 90
                elif o.state == 10:  # fall
                    o.y_fx += o.vy_fx
                    o.vy_fx = min(0x0100, o.vy_fx + 0x0028)
                    surf = level_floor_at(level, fx_to_float(o.x_fx),
                                          fx_to_float(o.y_fx))
                    if surf is not None and fx_to_float(o.y_fx) >= surf:
                        o.y_fx = float_to_fx(surf)
                        o.vy_fx = 0
                        o.state = 12
                        o.phase = 20
                    o.phase -= 1
                    if o.phase <= 0:
                        o.vy_fx = 0
                        o.state = 12
                        o.phase = 20
                elif o.state == 12:  # turn
                    o.vy_fx = 0
                    o.facing = 1 if dx >= 0 else -1
                    o.phase -= 1
                    if o.phase <= 0:
                        o.state = 14
                        o.phase = 120
                elif o.state == 14:  # rise back to the post
                    if o.y_fx > hover_y:
                        o.y_fx -= 0x0200
                    o.phase -= 1
                    if o.y_fx <= hover_y or o.phase <= 0:
                        o.y_fx = hover_y
                        o.state = 2
                        o.phase = 60
                else:
                    o.state = 2
                    o.phase = 40
            else:
                # Hippogriff / Stage Boss: swoop and hover above Firebrand,
                # and punish with a three-shot spread every 110 frames.
                if abs(dx) > 12 * FX_ONE:
                    o.x_fx += 0x0100 if dx > 0 else -0x0100
                target_y = o.origin_y_fx + _c_int(
                    math.sin(o.timer * 0.06) * 28.0 * FX_ONE)
                if (o.timer % 140) > 90:
                    target_y = player.y_fx - 12 * FX_ONE
                if o.y_fx < target_y:
                    o.y_fx += 0x00C0
                elif o.y_fx > target_y:
                    o.y_fx -= 0x00C0
                if o.timer % 110 == 40:
                    bx = fx_to_float(o.x_fx)
                    by = fx_to_float(o.y_fx)
                    tx = player.x - bx
                    ty = (player.y - 10.0) - by
                    ln = math.sqrt(tx * tx + ty * ty)
                    if ln < 0.001:
                        ln = 1.0
                    tx /= ln
                    ty /= ln
                    for k in range(-1, 2):
                        ang = float(k) * 0.35
                        cx = tx * math.cos(ang) - ty * math.sin(ang)
                        cy = tx * math.sin(ang) + ty * math.cos(ang)
                        _spawn_enemy_shot(pool, bx, by,
                                          _c_int(cx * 1.4 * FX_ONE),
                                          _c_int(cy * 1.4 * FX_ONE))
            # Keep boss art turned toward the player between attack states.
            if dx > 8 * FX_ONE:
                o.facing = 1
            elif dx < -8 * FX_ONE:
                o.facing = -1

            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            if (abs(ox - player.x) < 20.0 and
                    abs(oy - (player.y - 11.0)) < 22.0):
                if player.dash_timer > 0:
                    o.hp -= 1
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    player.dash_timer = 0
                    if o.hp <= 0:
                        o.active = False
                        pool.boss_alive = False
                        pool.boss_defeated = True
                        pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                        _spawn_pickup(pool, ox, oy)
                else:
                    _damage_player(player, ox, 1)
            continue

        if o.type == OBJECT_ENEMY:
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            o.timer += 1
            if o.species == 0x2C:
                # Area 2 Skeleton walker: ground patrol.
                o.state = 1
                o.x_fx += o.vx_fx
                ox = fx_to_float(o.x_fx)
                if (level_is_wall_at(level,
                                     ox + (8.0 if o.vx_fx > 0 else -8.0),
                                     oy - 8.0) or
                        abs(o.x_fx - o.origin_x_fx) > 96 * FX_ONE):
                    o.vx_fx = -o.vx_fx
                    o.facing = 1 if o.vx_fx >= 0 else -1
                surf = level_floor_at(level, ox, oy + 4.0)
                if surf is not None:
                    o.y_fx = float_to_fx(surf)
            elif o.species == 0x07:
                # Area 2/3 Bat/Watcher: sine wave swoop.
                o.state = 1
                dx = player.x_fx - o.x_fx
                if abs(dx) < 200 * FX_ONE:
                    o.x_fx += 0x0080 if dx > 0 else -0x0080
                    o.y_fx = o.origin_y_fx + _c_int(
                        math.sin(o.timer * 0.08) * 18.0 * FX_ONE)
            elif o.species == 0x67:
                # Authentic $83:AF74 handler (see GhoulUpdate above). The
                # contact-damage tail below still runs for ghouls.
                _ghoul_update(o, level, player, pool)
            else:
                # Generic enemy for species whose ROM handler is not ported yet.
                # Placement decides the style: enemies spawned well above a
                # floor fly (hover + 2D chase), grounded ones patrol and walk
                # toward the player. Keeps rooms lively without the ghoul's hop
                # behaviour leaking into every other species.
                dx = player.x_fx - o.x_fx
                dy = player.y_fx - o.y_fx
                near = abs(dx) < 140 * FX_ONE and abs(dy) < 64 * FX_ONE
                spawn_x = fx_to_float(o.origin_x_fx)
                spawn_y = fx_to_float(o.origin_y_fx)
                # No floor under the spawn also means "flying": those spawns
                # hang over pits or above the walkable layer.
                surf = level_floor_at(level, spawn_x, spawn_y)
                airborne = surf is None or surf - spawn_y > 24.0
                if airborne:
                    if o.state == 2:
                        # Dive attack: locked velocity for a few frames.
                        o.x_fx += o.vx_fx
                        o.y_fx += o.vy_fx
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0
                            o.phase = 90
                            o.vx_fx = 0
                            o.vy_fx = 0
                    else:
                        # Flyer: drift toward the player, bob around spawn.
                        o.facing = 1 if dx >= 0 else -1
                        if abs(dx) > 8 * FX_ONE:
                            o.x_fx += o.facing * 0x0070
                        target_y = fx_to_float(o.origin_y_fx) + \
                            math.sin(o.timer * 0.07) * 14.0
                        if abs(player.y - 14.0 - target_y) < 60.0:
                            target_y = player.y - 14.0
                        cur_y = fx_to_float(o.y_fx)
                        if target_y > cur_y + 1.0:
                            o.y_fx += 0x0050
                        elif target_y < cur_y - 1.0:
                            o.y_fx -= 0x0050
                        if o.phase > 0:
                            o.phase -= 1
                        elif (abs(dx) < 64 * FX_ONE and
                              abs(dy) < 180 * FX_ONE):
                            # Swoop at the player's current position.
                            ddx = float(dx)
                            ddy = float(dy)
                            ln = math.sqrt(ddx * ddx + ddy * ddy)
                            if ln < 0.001:
                                ln = 1.0
                            o.vx_fx = _c_int(ddx / ln * 3.0 * FX_ONE)
                            o.vy_fx = _c_int(ddy / ln * 3.0 * FX_ONE)
                            o.state = 2
                            o.phase = 22
                else:
                    if o.state == 2:
                        # Ground lunge: short horizontal burst.
                        o.x_fx += o.facing * 0x0200
                        gx = fx_to_float(o.x_fx)
                        gy = fx_to_float(o.y_fx)
                        surf = level_floor_at(level, gx, gy + 4.0)
                        if surf is not None:
                            o.y_fx = float_to_fx(surf)
                        o.phase -= 1
                        if o.phase <= 0:
                            o.state = 0
                            o.phase = 80
                    else:
                        if near:
                            o.facing = 1 if dx >= 0 else -1
                            if abs(dx) > 10 * FX_ONE:
                                o.x_fx += o.facing * 0x0068
                        else:
                            if o.vx_fx == 0:
                                o.vx_fx = 0x0048
                            o.x_fx += o.vx_fx
                            if abs(o.x_fx - o.origin_x_fx) > 48 * FX_ONE:
                                o.vx_fx = -o.vx_fx
                                o.facing = 1 if o.vx_fx >= 0 else -1
                        gx = fx_to_float(o.x_fx)
                        gy = fx_to_float(o.y_fx)
                        surf = level_floor_at(level, gx, gy + 4.0)
                        if surf is not None:
                            o.y_fx = float_to_fx(surf)
                        if o.phase > 0:
                            o.phase -= 1
                        elif (near and abs(dx) > 14 * FX_ONE and
                              abs(dx) < 52 * FX_ONE):
                            o.state = 2
                            o.phase = 14
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)
            px = player.x
            py = player.y - 10.0
            if abs(ox - px) < 14.0 and abs(oy - py) < 18.0:
                if player.dash_timer > 0:
                    o.hp = 0
                    o.active = False
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    _spawn_pickup(pool, ox, oy + 8.0)
                else:
                    _damage_player(player, ox, 1)
            continue

        if o.hit_flash > 0:
            o.hit_flash -= 1

        if o.type == OBJECT_ENEMY_SHOT:
            o.timer += 1
            sx = fx_to_float(o.x_fx)
            sy = fx_to_float(o.y_fx)
            if o.state == 1:
                # Firewall flame: stays put, burns for a while.
                if o.timer > 90:
                    o.active = False
                elif (abs(sx - player.x) < 9.0 and
                      abs(sy - (player.y - 6.0)) < 16.0):
                    _damage_player(player, sx, 1)
                continue
            o.x_fx += o.vx_fx
            o.y_fx += o.vy_fx
            sx = fx_to_float(o.x_fx)
            sy = fx_to_float(o.y_fx)
            hit_ground = level_is_solid_at(level, sx, sy) or (
                level_floor_at(level, sx, sy) is not None and
                sy >= float(level.world_h - 24))
            if (o.timer > 240 or hit_ground or
                    sx < level.play_min_x - 16.0 or
                    sx > level.play_max_x + 16.0 or
                    sy < 0.0 or sy > float(level.world_h)):
                if o.substate == 1 and hit_ground:
                    _spawn_firewall(pool, sx, sy - 4.0)
                o.active = False
                continue
            if (abs(sx - player.x) < 10.0 and
                    abs(sy - (player.y - 10.0)) < 12.0):
                _damage_player(player, sx, 1)
                if o.substate == 1:
                    _spawn_firewall(pool, sx, sy)
                o.active = False
            continue

        if o.type != OBJECT_PICKUP:
            continue

        if o.state == 0:
            o.vy_fx += HEART_GRAVITY_FX
            if o.vy_fx > 0x0600:
                o.vy_fx = 0x0600
            o.y_fx += o.vy_fx

            x = fx_to_float(o.x_fx)
            y = fx_to_float(o.y_fx)
            surface = level_floor_at(level, x, y)
            if surface is not None and y >= surface:
                o.y_fx = float_to_fx(surface)
                o.bounce_fx -= HEART_BOUNCE_STEP
                if o.bounce_fx > 0:
                    o.vy_fx = -o.bounce_fx
                else:
                    o.bounce_fx = 0
                    o.vy_fx = 0
                    o.state = 1  # at rest

        if _player_touches(o, player):
            if player.hp < player.max_hp:
                player.hp += 1
            player.gold += 10
            o.active = False
            pool.events |= OBJECT_EVENT_PICKUP


def objects_check_projectiles(pool: ObjectPool, projectiles, player=None) -> None:
    for p in projectiles.slots:
        if not p.active:
            continue
        px = fx_to_float(p.x_fx)
        py = fx_to_float(p.y_fx)
        dmg = p.damage if p.damage > 0 else 1

        for o in pool.slots:
            if not o.active:
                continue
            ox = fx_to_float(o.x_fx)
            oy = fx_to_float(o.y_fx)

            if o.species in (PIT_BODY_SPECIES, PIT_EYE_SPECIES):
                # docs/boss_hp.txt: the body takes 10 hits, each eye 3.  The
                # boxes are the port's (the ROM's probe is $809CA4); the
                # damage is the current form's column in that table.
                hw, hh = ((24.0, 30.0) if o.species == PIT_BODY_SPECIES
                          else (8.0, 8.0))
                if abs(px - ox) <= hw and abs(py - oy) <= hh:
                    p.active = False
                    dmg = (_pit_damage(player) if player is not None
                           else (5 if p.damage >= 2 else 1))
                    o.hp -= dmg
                    o.hit_flash = 8
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    if o.hp <= 0:
                        o.active = False
                        pool.pit_dead += 1        # $1DF8
                        if o.species == PIT_BODY_SPECIES:
                            # The ROM ends the fight with $1DEB=2, which sends
                            # the body to its leaving state ($83:C198).
                            pool.pit_fight = False
                            pool.pit_opened = 2
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                continue

            if o.type == OBJECT_URN:
                if (abs(px - ox) <= URN_HALF + 4.0 and
                        abs(py - oy) <= URN_HALF + 14.0):
                    o.active = False
                    p.active = False
                    pool.events |= OBJECT_EVENT_BREAK
                    _spawn_pickup(pool, ox, oy + URN_HALF)
                    break
            elif o.type == OBJECT_ENEMY and \
                    (o.species == 0x67 or o.state != 0):
                # Ghouls are hittable in every state: the ROM's $05 values are
                # behaviour states, not an emerge phase.
                if abs(px - ox) <= 12.0 and abs(py - oy) <= 12.0:
                    p.active = False
                    o.hp -= dmg
                    o.hit_flash = 8
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    if o.hp <= 0:
                        _spawn_pickup(pool, ox, oy + 8.0)
                        o.active = False
                    break
            elif o.type == OBJECT_ENEMY_SHOT:
                if abs(px - ox) <= 8.0 and abs(py - oy) <= 8.0:
                    p.active = False
                    o.active = False
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    break
            elif o.type == OBJECT_BOSS:
                if o.state == 5 or o.state == 6:
                    continue  # collapsing or fainted: ignore hits
                hw = 40.0 if o.species == 0x33 else 20.0
                hh = 46.0 if o.species == 0x33 else 24.0
                if abs(px - ox) <= hw and abs(py - oy) <= hh:
                    if o.species == 0x09 and o.state == 6:
                        p.active = False  # spark off the stone
                        break
                    # Somulo flashes white for ~33 frames after a hit in the
                    # recording and cannot be hit again until it ends, so the
                    # six-hit rhythm is the player's, not a machine gun.
                    # Grewon turns green for 45..75 frames and is invincible
                    # until he changes back: hits during it do nothing.
                    if ((o.species == 0x33 or o.species == 0x13) and
                            o.hit_flash > 0):
                        continue
                    p.active = False
                    o.hp -= dmg
                    if o.species == 0x33:
                        o.hit_flash = 32
                    elif o.species == 0x13:
                        o.hit_flash = 60
                    else:
                        o.hit_flash = 8
                    pool.events |= OBJECT_EVENT_ENEMY_HIT
                    if o.hp <= 0:
                        if o.species == 0x33:
                            if (o.hops == 0 and
                                    not env_flag("DC_BOSS_SKIP_FAINT")):
                                # First death blow is not death: he faints
                                # (wiki). The player is free to move while he
                                # is down, and he comes back stuck in the gate
                                # with three hits left.
                                o.hp = 0
                                o.hops = 1
                                o.state = 6
                                o.phase = 180
                                o.hit_flash = 0
                                break
                            # Collapse, lie there, then leave the room.
                            o.state = 5
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            _spawn_pickup(pool, ox, oy + 8.0)
                            break
                        o.active = False
                        if o.species == 0x09:
                            # The take shows him breaking apart on the floor:
                            # hold the rubble pose for 1.5 s before freeing the
                            # slot. The gate is already open (boss_alive is
                            # cleared below), so this is only presentation.
                            o.active = True
                            o.state = 5
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        if o.species == 0x86 and pool.boss_phase == 1:
                            # Phalanx's first form falls and the second rises
                            # from the pit: same head, stronger, and the exit
                            # stays shut until it dies too.
                            pool.boss_phase = 2
                            n = _alloc(pool)
                            if n is not None:
                                _reset_object(n)
                                n.active = True
                                n.type = OBJECT_BOSS
                                n.species = 0x8D
                                n.x_fx = o.x_fx
                                n.y_fx = o.y_fx + 40 * FX_ONE
                                n.origin_x_fx = n.x_fx
                                n.origin_y_fx = n.y_fx
                                n.hp = boss_hp(0x8D, 0)
                                n.max_hp = n.hp
                                n.substate = 1  # second form
                                pool.boss_alive = True
                                pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        if o.species == 0xA5:
                            # Arma does not die: he escapes after enough hits
                            # and leaves the Earth Crest behind (wiki). Keep
                            # the slot in the flee state until he is
                            # off-screen; the crest is granted by the
                            # area-clear path, like the other crests.
                            o.active = True
                            o.state = 24
                            o.phase = 90
                            o.hit_flash = 0
                            pool.boss_alive = False
                            pool.boss_defeated = True
                            pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                            break
                        pool.boss_alive = False
                        pool.boss_defeated = True
                        pool.events |= OBJECT_EVENT_BOSS_DEFEATED
                        _spawn_pickup(pool, ox, oy + 8.0)
                    break
