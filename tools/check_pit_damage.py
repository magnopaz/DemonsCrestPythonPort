#!/usr/bin/env python3
"""Assert the pit boss's damage model (docs/boss_hp.txt).

Ovununu's column in that table is 10 HP for the main body and 3 per eye, with
Fire/Buster/Claw/Tidal doing 1, Demon Fire 3, Earth (ground) 2, Earth (air) 1,
Aerial 2 and Legendary/Ultimate 5.  The port wires the body and the eyes into
the projectile-hit path (they used to be inert placeholders), so this check
builds the pool by hand, fires at each and asserts the hit count and the end of
the fight.

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
    PIT_BODY_HP, PIT_BODY_SPECIES, PIT_EYE_HP, PIT_EYE_SPECIES, ObjectPool,
    _pit_damage, _spawn_boss, _spawn_unknown, objects_check_projectiles)
from dcpy.projectile import ProjectilePool  # noqa: E402
from dcpy.util import fx_to_float  # noqa: E402


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
        if o.active and o.species == species:
            return o
    raise AssertionError(f"{species:#x} did not spawn")


def shoot(pool, o, damage=1, player=None):
    """Fire one projectile that starts on the body's own box."""
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

    # Body: 10 hits of 1 damage, then the fight is over.
    pool = ObjectPool()
    body = spawn(pool, PIT_BODY_SPECIES, 128.0, 214.0)
    if body.hp != PIT_BODY_HP:
        errors.append(f"body HP {body.hp}, docs/boss_hp.txt says {PIT_BODY_HP}")
    pool.pit_fight = True
    pool.boss_alive = True
    for hit in range(1, PIT_BODY_HP + 1):
        shoot(pool, body, player=player)
        want = PIT_BODY_HP - hit
        if body.active and body.hp != want:
            errors.append(f"after {hit} hits the body has {body.hp}, "
                          f"expected {want}")
            break
    if body.active:
        errors.append("the body survived 10 fire hits")
    if pool.pit_fight:
        errors.append("the fight did not end when the body died")
    if not pool.boss_defeated:
        errors.append("boss_defeated is still false")
    if not (pool.events & OBJECT_EVENT_BOSS_DEFEATED):
        errors.append("no boss-defeated event")

    # Eye: 3 hits.
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

    # The ultimate form kills an eye in one hit (5 >= 3).
    pool = ObjectPool()
    eye = spawn(pool, PIT_EYE_SPECIES, 96.0, 254.0, flags=0)
    pool.pit_fight = True
    player.crest_form = CREST_ULTIMATE
    shoot(pool, eye, damage=5, player=player)
    player.crest_form = CREST_BASE
    if eye.active:
        errors.append("a 5-damage hit did not kill an eye")

    if errors:
        print("pit damage: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    print("pit damage: PASS (body 10 hits, eye 3, form damage 1/2/1/2/1/5/5; "
          "the fight ends and sets boss_defeated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
