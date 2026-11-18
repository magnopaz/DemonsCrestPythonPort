#!/usr/bin/env python3
"""Assert the pit boss's damage model and fight end (docs/boss_hp.txt + ROM).

Ovununu's row in that table is 3 HP per eye, and the damage is per form:
Fire/Buster/Claw/Tidal 1, Demon Fire 3, Earth (ground) 2, Earth (air) 1,
Aerial 2, Legendary/Ultimate 5.  The pit's own reading of the ROM
(docs/PIT_BOSS.md 7.14) adds the rest:

* the body ($6B) has **no** hit points -- its handler never reads the shared
  hurt flag $1DDE, so shots pass through it;
* the fight ends when the ten satellite eyes are dead: $BA4E sees
  $1DF8 == 10 and sets $1DEB=1, the $69's substate-4 script ends with
  $1DEB=2, the body switches to state 4 and plays the twelve-step leave from
  $81:E29A (three frames per step, values 14/0 = a blink), and the central
  eye leaves with it.

This check builds the pool by hand and asserts each link.

Usage: python3 tools/check_pit_damage.py
Exit codes: 0 = pass, 1 = failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dcpy.consts import (  # noqa: E402
    CREST_AIR, CREST_BASE, CREST_EARTH, CREST_TIME, CREST_ULTIMATE,
    CREST_WATER, OBJECT_EVENT_BOSS_DEFEATED)
from dcpy.object import (  # noqa: E402
    PIT_BODY_SPECIES, PIT_EYE_CORE_INDEX, PIT_EYE_HP, PIT_EYE_SPECIES,
    PIT_LEAVE_FRAMES, PIT_LEAVE_STEPS, ObjectPool, _pit_damage,
    _pit_launch_controller, _spawn_boss, _spawn_unknown, objects_check_projectiles,
    objects_update)
from dcpy.projectile import ProjectilePool  # noqa: E402


class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.crest_form = 0
        self.on_ground = True
        self.active_talisman = 0
        self.invuln_timer = 0
        self.hp = 7
        self.max_hp = 7
        self.gold = 0


def spawn(pool, species, x, y, flags=0):
    _spawn_unknown(pool, SimpleNamespace(species=species, flags=flags,
                                         x=x, y=y))
    for o in pool.slots:
        if o.active and o.species == species and (o.flags & 0x0F) == (flags & 0x0F):
            return o
    raise AssertionError(f"{species:#x} flags {flags:#x} did not spawn")


def shoot(pool, o, damage=1, player=None):
    """Fire one projectile that starts on the object's own box."""
    proj = ProjectilePool()
    p = proj.slots[0]
    p.active = True
    p.x_fx = o.x_fx
    p.y_fx = o.y_fx
    p.damage = damage
    objects_check_projectiles(pool, proj, player)


def main() -> int:
    errors: list[str] = []

    # The document's Ovununu column, one row per port form.  Earth splits on
    # whether Firebrand is grounded; the rest are flat.
    player = Player(128.0, 640.0)
    form_damage = [
        (CREST_BASE, True, 1, "Fire"),
        (CREST_EARTH, True, 2, "Earth (ground)"),
        (CREST_EARTH, False, 1, "Earth (air)"),
        (CREST_AIR, True, 2, "Aerial"),
        (CREST_WATER, True, 1, "Tidal"),
        (CREST_TIME, True, 5, "Legendary"),
        (CREST_ULTIMATE, True, 5, "Ultimate"),
    ]
    for form, grounded, want, label in form_damage:
        player.crest_form = form
        player.on_ground = grounded
        got = _pit_damage(player)
        if got != want:
            errors.append(f"{label} damage {got}, expected {want}")
    player.crest_form = CREST_BASE
    player.on_ground = True

    # The body takes no damage: the $6B has no hit points in the ROM.
    pool = ObjectPool()
    body = spawn(pool, PIT_BODY_SPECIES, 128.0, 214.0)
    pool.pit_fight = True
    for _ in range(20):
        shoot(pool, body, player=player)
    if not body.active:
        errors.append("the body left without the eye script")
    if body.hp != 1:
        errors.append(f"the body has hp {body.hp}; the ROM gives it none")
    if pool.pit_dead:
        errors.append(f"a body hit counted as a dead eye ({pool.pit_dead})")

    # Satellite eye: 3 hits, and its death counts ($1DF8).
    pool = ObjectPool()
    eye = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    if eye.hp != PIT_EYE_HP:
        errors.append(f"eye HP {eye.hp}, docs/boss_hp.txt says {PIT_EYE_HP}")
    pool.pit_fight = True
    for hit in range(1, PIT_EYE_HP + 1):
        shoot(pool, eye, player=player)
    if eye.active:
        errors.append("the eye survived 3 fire hits")
    if pool.pit_dead != 1:
        errors.append(f"pit_dead {pool.pit_dead}, expected 1 ($1DF8)")

    # The central eye is welded to the body: shots do nothing to it.
    pool = ObjectPool()
    core = spawn(pool, PIT_EYE_SPECIES, 129.0, 242.0, flags=PIT_EYE_CORE_INDEX)
    pool.pit_fight = True
    for _ in range(5):
        shoot(pool, core, player=player)
    if pool.pit_dead:
        errors.append("the central eye counted toward $1DF8")

    # The ultimate form kills a satellite in one hit (5 >= 3).
    pool = ObjectPool()
    eye = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    pool.pit_fight = True
    player.crest_form = CREST_ULTIMATE
    shoot(pool, eye, damage=5, player=player)
    player.crest_form = CREST_BASE
    if eye.active:
        errors.append("a 5-damage hit did not kill a satellite eye")

    # $BA4E: ten dead eyes open the leave phase ($1DEB=1, $40=6).
    pool = ObjectPool()
    pool.pit_parked = [0] * 10
    pool.pit_dead = 10
    pool.pit_ctl = 2
    _pit_launch_controller(pool)
    if pool.pit_opened != 1:
        errors.append(f"$BA4E left pit_opened at {pool.pit_opened}, expected 1")
    if pool.pit_ctl != 6:
        errors.append(f"$BA4E left the controller at {pool.pit_ctl}, expected 6")

    # The leave: state 4, twelve steps of three frames, then everything is
    # gone and the fight is closed ($1DEB=2).
    pool = ObjectPool()
    body = spawn(pool, PIT_BODY_SPECIES, 128.0, 214.0)
    center = spawn(pool, PIT_EYE_SPECIES, 129.0, 242.0, flags=PIT_EYE_CORE_INDEX)
    satellite = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    pool.pit_fight = True
    pool.pit_opened = 1
    total = len(PIT_LEAVE_STEPS) * PIT_LEAVE_FRAMES
    frame = 0
    while body.active and frame < total:
        frame += 1
        objects_update(pool, None, player)
        if body.active and pool.pit_leave != frame:
            errors.append(f"leave frame {frame}: pit_leave {pool.pit_leave}")
            break
        if not body.active and frame != total:
            errors.append(f"the body left at frame {frame}, expected {total}")
            break
    if body.active:
        errors.append("the body survived its own leave animation")
    if body.state != 4:
        errors.append(f"the leave did not put the body in state 4 ({body.state})")
    if center.active:
        errors.append("the central eye stayed after the body left")
    if satellite.active:
        errors.append("a live satellite stayed after the body left")
    if pool.pit_opened != 2:
        errors.append(f"pit_opened {pool.pit_opened}, expected 2 ($1DEB=2)")
    if pool.pit_fight:
        errors.append("the fight did not close with the leave")
    if not pool.boss_defeated:
        errors.append("boss_defeated is still false")
    if not (pool.events & OBJECT_EVENT_BOSS_DEFEATED):
        errors.append("no boss-defeated event")
    if pool.pit_leave:
        errors.append(f"pit_leave {pool.pit_leave} after the leave finished")

    # ---- the generic boss path ($A5/$82/$33 in a room) ----
    def boss(species, flags=0):
        pool = ObjectPool()
        _spawn_boss(pool, SimpleNamespace(species=species, flags=flags,
                                          x=128.0, y=128.0))
        for o in pool.slots:
            if o.active and o.type == 6:
                return pool, o
        raise AssertionError(f"boss {species:#x} did not spawn")

    # Arma 1: Ultimate 5, Earth (ground) 2, Fire 1.
    pool, arma = boss(0xA5, 0)
    hp = arma.hp
    player.crest_form = CREST_ULTIMATE
    shoot(pool, arma, player=player)
    if arma.hp != hp - 5:
        errors.append(f"Arma 1 ultimate hit: hp {arma.hp}, expected {hp - 5}")
    hp = arma.hp
    player.crest_form = CREST_EARTH
    player.on_ground = True
    shoot(pool, arma, player=player)
    if arma.hp != hp - 2:
        errors.append(f"Arma 1 earth hit: hp {arma.hp}, expected {hp - 2}")
    hp = arma.hp
    player.crest_form = CREST_BASE
    shoot(pool, arma, player=player)
    if arma.hp != hp - 1:
        errors.append(f"Arma 1 fire hit: hp {arma.hp}, expected {hp - 1}")

    # Crawler: the document says Earth (ground) is N/A, so the hit does 0.
    pool, crawler = boss(0x82, 0)
    hp = crawler.hp
    player.crest_form = CREST_EARTH
    player.on_ground = True
    shoot(pool, crawler, player=player)
    if crawler.hp != hp:
        errors.append(f"Crawler earth hit: hp {crawler.hp}, expected {hp}")

    # Somulo has no row: the projectile's own damage is kept (scripted fight).
    pool, somulo = boss(0x33, 128)
    hp = somulo.hp
    player.crest_form = CREST_ULTIMATE
    shoot(pool, somulo, damage=1, player=player)
    if somulo.hp != hp - 1:
        errors.append(f"Somulo hit: hp {somulo.hp}, expected {hp - 1}")
    player.crest_form = CREST_BASE

    if errors:
        print("pit damage: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    print("pit damage: PASS (body unhittable, eye 3 hits, form damage "
          "1/2/1/2/1/5/5; ten eyes -> $1DEB=1 -> the 12x3 leave -> "
          "fight closed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
