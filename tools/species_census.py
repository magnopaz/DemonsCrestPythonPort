#!/usr/bin/env python3
"""Measure the per-species AI surface before porting any of it.

The object dispatcher indexes four 192-entry tables in bank `$82` by
`species * 2` (`$82:8000` update, `$82:8180` secondary, `$82:8300` init,
`$82:8480` aux).  Most entries are 5-byte `JSL $83:xxxx / RTS` stubs; a few
point straight at bank `$82` code.  From there each update routine dispatches
its states through an in-bank pointer table indexed by the `$05` byte offset,
so a species' whole behaviour is `update -> state table -> handlers`.

This tool resolves that chain for every species the ROM actually places and
reports what a port would face: handler addresses, state count, whether the
routine probes collision, spawns objects, or rolls `$BC904B`, and whether a
sprite sheet already exists.  It prints one table (ordered by how many records
the species places) and, with `--json`, the same data for tooling.

Usage:
  python3 tools/species_census.py
  python3 tools/species_census.py --json /tmp/species.json
  python3 tools/species_census.py --species 0x50 --disasm
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

import extract as E  # noqa: E402

TABLES = {"update": 0x8000, "secondary": 0x8180, "init": 0x8300, "aux": 0x8480}
HELPERS = {
    "collide": (0x809CA4, 0x808C31, 0x808BED, 0x808B9C, 0x808BA7),
    "aim": (0x809D8E, 0x809B53, 0x809FA2),
    "spawn": (0x82877B, 0x82873D, 0x828777),
    "random": (0xBC904B,),
    "anim": (0x80F81D, 0x80F83D),
}


def resolve(rom: E.Rom, table: int, species: int):
    """Follow one dispatch entry to (bank, addr), or None."""
    addr = rom.u16(0x82, table + species * 2)
    if addr == 0:
        return None
    if rom.u8(0x82, addr) == 0x22:  # JSL $bank:addr
        bank = rom.u8(0x82, addr + 3)
        target = rom.u8(0x82, addr + 1) | (rom.u8(0x82, addr + 2) << 8)
        return bank, target
    return 0x82, addr


def state_table(rom: E.Rom, bank: int, addr: int):
    """Find the state dispatch inside a handler.

    The pattern is `LDX $05` (state) followed by `JMP (abs,X)` / `JSR (abs,X)`.
    A few species (`$9C`) first dispatch on `$03` (a mode byte) and only then
    reach the `$05` table, so `$05` wins whenever both are present.  Entries are
    read until one leaves the table's neighbourhood (the tables sit between code
    blocks, and the bytes after them are instructions).
    """
    matches = []
    for k in range(64):
        a = addr + k
        if rom.u8(bank, a) != 0xA6 or rom.u8(bank, a + 1) not in (0x05, 0x03):
            continue
        op = rom.u8(bank, a + 2)
        if op not in (0xFC, 0x7C):   # JSR (abs,X) / JMP (abs,X)
            continue
        ptr = rom.u8(bank, a + 3) | (rom.u8(bank, a + 4) << 8)
        handlers = []
        for j in range(16):
            target = rom.u16(bank, ptr + j * 2)
            if not (ptr - 0x200 <= target <= ptr + 0xC00):
                break
            handlers.append(target)
        if len(handlers) >= 2:
            matches.append((rom.u8(bank, a + 1), ptr, handlers))
    if not matches:
        return None
    for var, ptr, handlers in matches:
        if var == 0x05:
            return var, ptr, handlers
    return matches[0]


def handler_features(rom: E.Rom, bank: int, addr: int, reach: int = 320):
    """Scan a handler's first `reach` bytes for the shared helper calls."""
    seen = set()
    for a in range(addr, min(0x10000, addr + reach)):
        if rom.u8(bank, a) != 0x22:  # JSL
            continue
        target = rom.u8(bank, a + 1) | (rom.u8(bank, a + 2) << 8)
        for name, addrs in HELPERS.items():
            if target in addrs:
                seen.add(name)
    return sorted(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path,
                    default=ROOT.parent / "roms" / "Demon's Crest (USA).sfc")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--species", default="",
                    help="hex id(s) to disassemble via the oracle tool")
    ap.add_argument("--disasm", action="store_true")
    args = ap.parse_args()

    rom = E.Rom(args.rom)
    placed = collections.Counter()
    areas = collections.defaultdict(set)
    for area in range(113):
        for rec in rom.object_list(area):
            placed[rec["species"]] += 1
            areas[rec["species"]].add(area)

    sheets = set()
    anim = args.assets / "species_anim.json"
    if anim.is_file():
        sheets = set(json.loads(anim.read_text()).get("species", {}).keys())

    rows = []
    for species, count in placed.most_common():
        init = resolve(rom, TABLES["init"], species)
        update = resolve(rom, TABLES["update"], species)
        state = state_table(rom, update[0], update[1]) if update else None
        feats = handler_features(rom, update[0], update[1]) if update else []
        known = E.SPECIES_KIND_MAP.get(species)
        rows.append({
            "species": species,
            "records": count,
            "areas": len(areas[species]),
            "kind": known or "unknown",
            "handler_kind": "stub" if update and update[0] != 0x82 else "direct",
            "init": f"{init[0]:02X}:{init[1]:04X}" if init else "",
            "update": f"{update[0]:02X}:{update[1]:04X}" if update else "",
            "state_var": state[0] if state else None,
            "states": len(state[2]) if state else 1,
            "state_handlers": [f"{update[0]:02X}:{h:04X}" for h in state[2]]
                               if state else [],
            "features": feats,
            "art": f"{species:02x}" in sheets,
        })

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"census: {len(rows)} species -> {args.json}")
    else:
        print(f"{'sp':>3} {'records':>7} {'areas':>5} {'kind':8} {'states':>6} "
              f"{'art':3} {'update':10} features")
        for r in rows:
            print(f"${r['species']:02X} {r['records']:7d} {r['areas']:5d} "
                  f"{r['kind']:8} {r['states']:6d} "
                  f"{'yes' if r['art'] else ' - ':3} {r['update']:10} "
                  + ",".join(r["features"]))

    if args.species:
        tool = ROOT.parent / "DemonsCrestSNESRecomp" / "tools" / "disasm_range.py"
        if not tool.is_file():
            print(f"census: no disassembler at {tool}", file=sys.stderr)
            return 2
        for token in args.species.split(","):
            species = int(token, 0)
            row = next((r for r in rows if r["species"] == species), None)
            if row is None:
                print(f"census: species {species:#04x} is not placed", file=sys.stderr)
                continue
            update = resolve(rom, TABLES["update"], species)
            state = state_table(rom, update[0], update[1])
            spans = []
            if state:
                starts = state[2]
                for i, start in enumerate(starts):
                    end = starts[i + 1] if i + 1 < len(starts) else start + 0x40
                    if end <= start:
                        end = start + 0x40
                    spans.append((start, min(end, start + 0x120)))
            else:
                spans = [(update[1], update[1] + 0xC0)]
            for start, end in spans:
                print(f"\n===== species ${species:02X} "
                      f"{update[0]:02X}:{start:04X} =====")
                subprocess.run([sys.executable, str(tool),
                                f"{update[0]:02X}:{start:04X}",
                                f"{update[0]:02X}:{end:04X}",
                                "--rom", str(args.rom), "--m", "1", "--x", "1"],
                               cwd=str(tool.parents[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
