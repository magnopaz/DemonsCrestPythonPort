#!/usr/bin/env python3
"""Assert the Phalanx chamber and the bad-ending flow (area 42).

The take `rec_bad_ending` (docs/TAKES.md §7) boots area 42 -- `$008D = 84`,
`phalanxs-fortress-phalanxs-chamber` -- fights Phalanx there and shows his
intro box on entry.  The port used to have none of that: the room's `$86` was an
untyped placeholder, the boss lived in area 84 ("BOSS STAGE 04", no ROM record)
and killing him returned to the map.

Two kinds of checks:

1. in-process (fast, no raylib): the ending rule (Time Crest / talismans), and
   the two-form chain -- `$86` dies and `$8D` rises with docs/boss_hp.txt's 127,
   `$8D` dies and the pool records the species the ending trigger keys on;
2. runtime, through the binary: area 42 spawns the boss from the ROM record,
   the intro box opens on entry, killing `$8D` enters `GAME_ENDING`, and a boss
   in any other area still goes to the normal area-clear path.

Usage:
  DISPLAY=:99 python3 tools/check_bad_ending.py \
      [--binary tools/demonscrest-py] [--assets assets/generated]

Exit codes: 0 = pass, 1 = failure, 77 = binary/assets missing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dcpy.bosses as bosses  # noqa: E402
from dcpy import consts as C  # noqa: E402
from dcpy.game import game_ending_variant  # noqa: E402
from dcpy.object import (ObjectPool, _spawn_boss,  # noqa: E402
                         objects_check_projectiles)
from dcpy.projectile import ProjectilePool  # noqa: E402

AREA = 42
OTHER_AREA = 1          # Hippogriff's room: a boss that must NOT roll the ending
FRAMES = 140
GAME_PLAYING = 1
GAME_CLEAR = 3
GAME_ENDING = 10
GAME_DIALOGUE = 11

# DC_TRACE_CSV row: frame,x,y,vx,vy,state,camx,camy,hp,maxhp,area,form,gold,
# element,state (no header).
ROW_STATE = 14


class Player:
    """The few fields objects_check_projectiles reads."""

    def __init__(self):
        self.x = 64.0
        self.y = 172.0
        self.crest_form = C.CREST_BASE
        self.on_ground = True
        self.active_talisman = 0
        self.invuln_timer = 0
        self.hp = 6
        self.max_hp = 6
        self.gold = 0


def shoot(pool, o, player, damage=1):
    proj = ProjectilePool()
    p = proj.slots[0]
    p.active = True
    p.x_fx = o.x_fx
    p.y_fx = o.y_fx
    p.damage = damage
    objects_check_projectiles(pool, proj, player)


def live_boss(pool, species):
    for o in pool.slots:
        if o.active and o.type == C.OBJECT_BOSS and o.species == species:
            return o
    return None


def kill(pool, species, player, limit=400):
    """Hit one species' boss until it leaves the pool; returns the hits.

    Looked up by species on every iteration on purpose: the death branch frees
    the slot and the next body is allocated into it, so holding the object
    reference would keep shooting the replacement.
    """
    hits = 0
    while hits < limit:
        o = live_boss(pool, species)
        if o is None:
            break
        shoot(pool, o, player)
        hits += 1
    return hits


def check_rules(errors: list[str]) -> None:
    earth_air = (1 << C.CREST_EARTH) | (1 << C.CREST_AIR)
    time = 1 << C.CREST_TIME
    cases = [
        (earth_air, 0x00, 0, "Ground+Air only -> bad"),
        (earth_air | time, 0x00, 1, "Time -> normal"),
        (earth_air | time, 0x1F, 2, "Time + all talismans -> good"),
        (earth_air, 0x1F, 0, "talismans without Time -> bad"),
        (0, 0x00, 0, "no crests -> bad"),
    ]
    for crests, talismans, want, label in cases:
        game = SimpleNamespace(player=SimpleNamespace(
            crests_mask=crests, talisman_mask=talismans))
        got = game_ending_variant(game)  # type: ignore[arg-type]
        if got != want:
            errors.append(f"{label}: variant {got}, expected {want}")
    if game_ending_variant(SimpleNamespace(player=SimpleNamespace(  # type: ignore[arg-type]
            crests_mask=0x3F, talisman_mask=0x1F))) != 2:
        errors.append("a full crest set with all talismans is not 'good'")


def check_chain(errors: list[str]) -> None:
    player = Player()
    pool = ObjectPool()
    pool.boss_phase = 1          # objects_init's default; the $86 branch needs it
    _spawn_boss(pool, SimpleNamespace(species=0x86, flags=0, x=256.0, y=136.0))
    first = live_boss(pool, 0x86)
    if first is None:
        errors.append("the $86 record did not spawn as a boss")
        return
    if first.hp != bosses.boss_hp(0x86, 0):
        errors.append(f"$86 hp {first.hp}, table says {bosses.boss_hp(0x86, 0)}")
    hits = kill(pool, 0x86, player)
    if pool.boss_phase != 2:
        errors.append(f"killing $86 left boss_phase {pool.boss_phase}, expected 2")
    second = live_boss(pool, 0x8D)
    if second is None:
        errors.append("the second form ($8D) did not rise")
        return
    if second.hp != bosses.boss_hp(0x8D, 0):
        errors.append(f"$8D hp {second.hp}, table says "
                      f"{bosses.boss_hp(0x8D, 0)}")
    if pool.boss_defeated:
        errors.append("killing the first form already set boss_defeated")
    kill(pool, 0x8D, player)
    if not pool.boss_defeated:
        errors.append("killing $8D did not set boss_defeated")
    if pool.boss_killed_species != 0x8D:
        errors.append(f"boss_killed_species {pool.boss_killed_species:#x}, "
                      f"expected 0x8d (the ending trigger keys on it)")
    dmg = bosses.boss_damage(0x86, 0, C.CREST_BASE, True, 0) or 0
    if not (dmg > 0 and (hits - 1) * dmg < bosses.boss_hp(0x86, 0) <= hits * dmg):
        errors.append(f"the first form took {hits} hits of {dmg}, which does "
                      f"not add up to {bosses.boss_hp(0x86, 0)} hp")


def run(binary: Path, assets: Path, trace: Path, extra: dict[str, str],
        area: int = AREA) -> list[list[str]] | None:
    env = dict(os.environ,
               DC_AREA=str(area),
               DC_RUN_FRAMES=str(FRAMES),
               DC_NO_AUDIO="1",
               DC_NO_SAVE="1",
               DC_BOSS_NO_ATTACK="1",
               DC_TRACE_CSV=str(trace))
    for key in ("DC_STATE", "DC_DEMO", "DC_BOSS_CLEAR", "DC_BOSS_DEFEATED",
                "DC_BOSS_PHASE", "DC_KILL_AT", "DC_BOSS_KILL_AT",
                "DC_START_X", "DC_START_Y", "DC_INTRO_FORCE", "DC_NO_STORY",
                "DC_STORY_FLAGS", "DC_RESUME", "DC_ENDING"):
        env.pop(key, None)
    env.update(extra)
    try:
        proc = subprocess.run([str(binary), "--assets", str(assets)],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("bad ending: timeout")
        return None
    if proc.returncode != 0:
        print(f"bad ending: exit {proc.returncode}\n{proc.stdout[-600:]}")
        return None
    if not trace.is_file():
        print("bad ending: no trace")
        return None
    return [row for row in csv.reader(trace.open(newline="")) if row]


def states(rows: list[list[str]]) -> list[int]:
    out = []
    for row in rows:
        try:
            out.append(int(row[ROW_STATE]))
        except (IndexError, ValueError):
            out.append(-1)
    return out


def check_runtime(binary: Path, assets: Path, tmp: Path,
                  errors: list[str]) -> None:
    # 1. The intro box opens on entry (the take shows it before any hit).
    rows = run(binary, assets, tmp / "intro.csv", {"DC_INTRO_FORCE": "1"})
    if rows is None:
        errors.append("runtime: intro run failed")
    else:
        st = states(rows)
        if GAME_DIALOGUE not in st:
            errors.append("area 42 did not open the Phalanx intro box")
        elif st[-1] not in (GAME_PLAYING, GAME_DIALOGUE):
            errors.append(f"after the intro the state is {st[-1]}")

    # 2. Killing the second form rolls the ending (bad: no Time Crest).
    rows = run(binary, assets, tmp / "ending.csv",
               {"DC_NO_STORY": "1", "DC_BOSS_KILL_AT": "30,70"})
    if rows is None:
        errors.append("runtime: ending run failed")
    else:
        st = states(rows)
        if GAME_ENDING not in st:
            errors.append("killing $8D in area 42 did not enter GAME_ENDING")
        elif st[-1] != GAME_ENDING:
            errors.append(f"the ending did not stay up (state {st[-1]})")
        if GAME_CLEAR in st:
            errors.append("area 42 also ran the area-clear path")

    # 3. A boss in any other area keeps the normal clear path.
    rows = run(binary, assets, tmp / "other.csv",
               {"DC_NO_STORY": "1", "DC_BOSS_KILL_AT": "30"}, area=OTHER_AREA)
    if rows is None:
        errors.append("runtime: control run failed")
    else:
        st = states(rows)
        if GAME_ENDING in st:
            errors.append(f"area {OTHER_AREA} rolled the ending")
        if GAME_CLEAR not in st:
            errors.append(f"area {OTHER_AREA} skipped the area-clear path")


def main() -> int:
    args = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    args.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    args.add_argument("--tmp", type=Path, default=None)
    opts = args.parse_args()

    binary = opts.binary.resolve()
    assets = opts.assets.resolve()
    if not binary.is_file() or not assets.is_dir():
        print("bad ending: skip (binary/assets missing)")
        return 77

    errors: list[str] = []
    check_rules(errors)
    check_chain(errors)
    with tempfile.TemporaryDirectory(prefix="dc-bad-ending-",
                                     dir=str(opts.tmp) if opts.tmp else None) as td:
        check_runtime(binary, assets, Path(td), errors)

    if errors:
        print("bad ending: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    print("bad ending: PASS (area 42 spawns $86, the intro box opens, "
          "$8D -> GAME_ENDING with the bad variant; other areas stay on the "
          "clear path)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
