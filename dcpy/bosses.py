"""Boss HP and per-form damage from ``docs/boss_hp.txt`` (user, 2026-11-06).

The port spawns bosses from the room documents rather than from the ROM's
object records, so the hit count and the damage each Firebrand form deals have
to live somewhere.  This module is that single place::

    hp = boss_hp(species, flags)
    dmg = boss_damage(species, flags, crest_form, grounded)

``flags`` is the record's second byte.  For Arma (``$A5``) and the Hippogriff
(``$09``) it selects the encounter — 0/2/4 — and each of the three fights has
its own row in the document.  For other species the byte is a record flag
(Belth's thirty records in area 9 carry 129..244), so those live in
``SPECIES_HP``/``SPECIES_DAMAGE`` and ignore it.

Every entry names the boss exactly as ``docs/boss_hp.txt`` does, so
``tools/check_boss_hp.py`` re-reads the document and proves both tables match
it.  Entries whose boss is not in the document (Somulo's scripted 3+3) are
marked ``documented=False`` and skipped by that comparison.

The document's columns Fire/Buster/Claw/Demon Fire/... are forms and attacks of
Firebrand.  The port maps its six crest forms onto the form columns (base =
Fire, Earth = Earth ground/air, Air = Aerial, Water = Tidal, Time = Legendary,
Ultimate = Ultimate); ``Buster``, ``Claw`` and ``Demon Fire`` are attacks the
port does not model yet, so they are stored but unused.  ``None`` means the
document says N/A — that form cannot hurt the boss (0 damage).  A tuple is a
two-form boss ("2/1"), indexed by ``phase``.
"""

from __future__ import annotations

from typing import NamedTuple

from .consts import (
    CREST_AIR, CREST_BASE, CREST_EARTH, CREST_TIME, CREST_ULTIMATE, CREST_WATER)


class BossHp(NamedTuple):
    name: str
    hp: int
    note: str = ""
    documented: bool = True


class BossDamage(NamedTuple):
    """One row of docs/boss_hp.txt: damage dealt by each form/attack."""

    fire: int | tuple | None = None
    buster: int | tuple | None = None
    claw: int | tuple | None = None
    demon_fire: int | tuple | None = None
    earth_ground: int | tuple | None = None
    earth_air: int | tuple | None = None
    aerial: int | tuple | None = None
    tidal: int | tuple | None = None
    legendary: int | tuple | None = None
    ultimate: int | tuple | None = None

    def for_form(self, form: int, grounded: bool = True,
                 phase: int = 0) -> int:
        """Damage the port's crest ``form`` deals to this boss."""
        if form == CREST_BASE:
            value = self.fire
        elif form == CREST_EARTH:
            value = self.earth_ground if grounded else self.earth_air
        elif form == CREST_AIR:
            value = self.aerial
        elif form == CREST_WATER:
            value = self.tidal
        elif form == CREST_TIME:
            value = self.legendary
        elif form == CREST_ULTIMATE:
            value = self.ultimate
        else:
            value = None
        if value is None:
            return 0  # the document says N/A: this form cannot hurt it
        if isinstance(value, tuple):
            return value[min(max(phase, 0), len(value) - 1)]
        return value


DOC = "docs/boss_hp.txt"

# No entry at all means the boss is not modelled yet.  Eight is the old
# fallback and stays visible: the checker fails on any boss species that is
# missing from these tables.
DEFAULT_BOSS_HP = 8

# (species, flags) -> BossHp, for bosses whose flags pick the encounter.
BOSS_HP: dict[tuple[int, int], BossHp] = {
    # Arma: three fights, flags 0/2/4.
    (0xA5, 0x00): BossHp("Arma 1", 16),
    (0xA5, 0x02): BossHp("Arma 2", 32),
    (0xA5, 0x04): BossHp("Arma 3", 72),
    # Hippogriff: three fights, flags 0/2/4.
    (0x09, 0x00): BossHp("Hippogriff 1", 16),
    (0x09, 0x02): BossHp("Hippogriff 2", 24),
    (0x09, 0x04): BossHp("Hippogriff 3", 64),
    # Stage bosses.  Scula is two linked species: the document gives 24 for the
    # tossing half and 10 for the rolling one; the ROM's per-slot HP would say
    # which is which, until then the larger body ($7B, the standing one in the
    # baked art) is the 24.
    (0x7B, 0x00): BossHp("Scula", 24, "Toss half"),
    (0x7C, 0x00): BossHp("Scula", 10, "Roll half"),
    (0x6F, 0x00): BossHp("Holothurion", 72),
    (0x16, 0x00): BossHp("Ovununu", 10, "main body; the eyes are $6C (3)"),
    (0x82, 0x00): BossHp("Crawler", 36),
    (0x58, 0x00): BossHp("Flame Lord", 26, "land form; flying form is 20"),
    (0x86, 0x00): BossHp("Phalanx", 50),
    (0x8D, 0x00): BossHp("Phalanx 2 (with Heaven Crest)", 127),
    (0xBC, 0x00): BossHp("Dark Demon - Three Headed/Fallen Angel", 200),
}

# species -> BossHp, for bosses whose record flags are not an encounter id.
SPECIES_HP: dict[int, BossHp] = {
    # Not in boss_hp.txt: the prologue is scripted as 3 hits (faint) + 3 hits
    # (head stuck in the gate), see docs/LORE.md.
    0x33: BossHp("Somulo", 6, "scripted 3+3", documented=False),
    # Grewon's two fights both have 64 HP, so the flags (0/2) do not matter.
    0x13: BossHp("Grewon 1", 64, "Grewon 2 is also 64"),
    # Belth's thirty records carry record flags (129..244), never a variant.
    0x68: BossHp("Belth", 32),
}

# (species, flags) -> BossDamage.  One row per fight, straight from the doc.
BOSS_DAMAGE: dict[tuple[int, int], BossDamage] = {
    (0xA5, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=2, tidal=1, legendary=5, ultimate=5),                   # Arma 1
    (0xA5, 0x02): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=2, tidal=1, legendary=5, ultimate=5),                   # Arma 2
    (0xA5, 0x04): BossDamage(
        fire=3, buster=1, claw=1, demon_fire=6, earth_ground=2, earth_air=1,
        aerial=2, tidal=1, legendary=10, ultimate=10),                 # Arma 3
    (0x09, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=4, tidal=1, legendary=5, ultimate=5),            # Hippogriff 1
    (0x09, 0x02): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=4, tidal=1, legendary=5, ultimate=5),            # Hippogriff 2
    (0x09, 0x04): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=4, tidal=1, legendary=5, ultimate=5),            # Hippogriff 3
    # Scula's two halves share the row.
    (0x7B, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=1, earth_air=1,
        aerial=None, tidal=1, legendary=5, ultimate=5),                 # Scula
    (0x7C, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=1, earth_air=1,
        aerial=None, tidal=1, legendary=5, ultimate=5),                 # Scula
    (0x6F, 0x00): BossDamage(
        fire=None, buster=1, claw=1, demon_fire=3, earth_ground=2,
        earth_air=1, aerial=None, tidal=3, legendary=5, ultimate=5),
    (0x16, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=2, earth_air=1,
        aerial=2, tidal=1, legendary=5, ultimate=5),                 # Ovununu
    (0x82, 0x00): BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=None,
        earth_air=2, aerial=None, tidal=1, legendary=5, ultimate=5),
    (0x58, 0x00): BossDamage(
        fire=None, buster=1, claw=1, demon_fire=3, earth_ground=2,
        earth_air=1, aerial=1, tidal=3, legendary=5, ultimate=5),
    (0x86, 0x00): BossDamage(
        fire=2, buster=1, claw=1, demon_fire=6, earth_ground=2, earth_air=1,
        aerial=None, tidal=1, legendary=5, ultimate=5),               # Phalanx
    (0x8D, 0x00): BossDamage(
        fire=2, buster=1, claw=1, demon_fire=6, earth_ground=2, earth_air=1,
        aerial=None, tidal=1, legendary=5, ultimate=5),          # Phalanx 2
    (0xBC, 0x00): BossDamage(
        fire=(2, 1), buster=None, claw=None, demon_fire=None,
        earth_ground=None, earth_air=None, aerial=None, tidal=None,
        legendary=None, ultimate=(4, 2)),                    # Dark Demon
}

# species -> BossDamage, for bosses whose record flags are not an encounter id.
SPECIES_DAMAGE: dict[int, BossDamage] = {
    # Grewon's two encounters share the row (the document repeats it).
    0x13: BossDamage(
        fire=4, buster=1, claw=1, demon_fire=6, earth_ground=2, earth_air=1,
        aerial=None, tidal=1, legendary=10, ultimate=10),             # Grewon
    0x68: BossDamage(
        fire=1, buster=1, claw=1, demon_fire=3, earth_ground=3, earth_air=1,
        aerial=None, tidal=1, legendary=5, ultimate=5),                 # Belth
}

# Species whose boss fight is not spawned from a room boss record yet, so a
# table entry would be dead code: Flier 1 (24) and Flier 2 (48) are listed in
# boss_hp.txt but their species is still unknown (docs/NEXT_STEPS.md, Passo 4).
UNMODELLED = ("Flier 1", "Flier 2", "Phalanx 3 (lava stage)")


def _lookup(species: int, flags: int) -> BossHp | None:
    key = (species & 0xFF, flags & 0xFF)
    entry = BOSS_HP.get(key)
    if entry is None:
        entry = BOSS_HP.get((key[0], key[1] & 0x0F))
    if entry is None:
        entry = SPECIES_HP.get(key[0])
    return entry


def boss_hp(species: int, flags: int) -> int:
    """HP for a boss record; the documented value or the visible fallback."""
    entry = _lookup(species, flags)
    return entry.hp if entry is not None else DEFAULT_BOSS_HP


def boss_name(species: int, flags: int) -> str:
    entry = _lookup(species, flags)
    return entry.name if entry is not None else f"species {species:#04x}"


def _damage_row(species: int, flags: int) -> BossDamage | None:
    key = (species & 0xFF, flags & 0xFF)
    row = BOSS_DAMAGE.get(key)
    if row is None:
        row = BOSS_DAMAGE.get((key[0], key[1] & 0x0F))
    if row is None:
        row = SPECIES_DAMAGE.get(key[0])
    return row


def boss_damage(species: int, flags: int, form: int, grounded: bool = True,
                phase: int = 0) -> int | None:
    """Damage ``form`` deals to this boss, or None if it has no row.

    None lets the caller keep the projectile's own damage (Somulo, whose
    prologue is scripted and which the document does not list).
    """
    row = _damage_row(species, flags)
    if row is None:
        return None
    return row.for_form(form, grounded, phase)


def all_entries():
    """Every (species, flags, BossHp) the module knows."""
    out = [(key[0], key[1], entry) for key, entry in BOSS_HP.items()]
    out += [(species, None, entry) for species, entry in SPECIES_HP.items()]
    return out


def documented_entries():
    """Entries whose boss is named in docs/boss_hp.txt."""
    return [(s, f, entry) for s, f, entry in all_entries() if entry.documented]


def damage_entries():
    """Every (species, flags, BossDamage) the module knows."""
    out = [(key[0], key[1], row) for key, row in BOSS_DAMAGE.items()]
    out += [(species, None, row) for species, row in SPECIES_DAMAGE.items()]
    return out
