#!/usr/bin/env python3
"""Assert the cemetery's torch flames ($72) exist and are drawn as decor.

Species `$72` is the 16x16 five-frame flame flicker on the Murkland cemetery
trees.  Its handler (`$85:D4CF`) has no movement and no contact damage, so the
port types it as ``decor``: the renderer draws the baked species sheet and the
object pool never sees it.  Before this, 13 records in area 1 were unknown
species and showed up as magenta placeholder boxes on every torch.

What this checks:

  * the room JSON keeps all 13 `$72` records, typed ``decor``, at the ROM's
    positions;
  * the species has a multi-frame sheet in `species_anim.json`;
  * the game boots area 1 and the renderer draws every decor record;
  * area 1 shows no placeholder boxes any more (it has no unknown species).

Exit 77 when the binary or the assets are missing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = 1
SPECIES = 0x72


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--tmp", type=Path, default=None)
    return ap.parse_args()


def run_trace(binary: Path, assets: Path, tmp: Path) -> dict[str, int]:
    player = tmp / "flame_player.csv"
    env = dict(os.environ,
               DC_AREA=str(AREA),
               DC_RUN_FRAMES="4",
               DC_NO_AUDIO="1",
               DC_NO_SAVE="1",
               DC_TRACE_PLACEHOLDERS="1",
               DC_TRACE_CSV=str(player))
    for key in ("DC_DEMO", "DC_STATE", "DC_TITLE", "DC_CAMPAIGN",
                "DC_START_X", "DC_START_Y"):
        env.pop(key, None)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=120)
    if proc.returncode != 0:
        raise SystemExit(f"flame: binary exited {proc.returncode}\n"
                         + proc.stdout[-1500:])
    counts = {}
    for line in proc.stdout.splitlines():
        for field in ("placeholders_drawn", "placeholders_visible",
                      "decor_drawn", "decor_visible"):
            for part in line.split():
                if part.startswith(field + "="):
                    counts[field] = int(part.split("=", 1)[1])
    missing = [f for f in ("placeholders_drawn", "placeholders_visible",
                           "decor_drawn", "decor_visible") if f not in counts]
    if missing:
        raise SystemExit("flame: no trace fields " + ", ".join(missing)
                         + "\n" + proc.stdout[-1500:])
    return counts


def main() -> int:
    args = parse_args()
    room_path = args.assets / f"room_area{AREA}.json"
    anim_path = args.assets / "species_anim.json"
    if not room_path.is_file() or not anim_path.is_file():
        print("flame: skip (no assets)")
        return 77

    room = json.loads(room_path.read_text())
    flames = [o for o in room.get("objects", [])
              if int(o.get("species", 0)) == SPECIES]
    errors = []
    if len(flames) != 13:
        errors.append(f"area {AREA}: {len(flames)} $72 records, expected 13")
    for o in flames:
        if o.get("type") != "decor":
            errors.append(f"area {AREA}: $72 at {o.get('x')} is typed "
                          f"{o.get('type')!r}, expected 'decor'")
        if o.get("source", "rom") != "rom":
            errors.append(f"area {AREA}: $72 at {o.get('x')} lost its ROM "
                          f"source ({o.get('source')!r})")

    anim = json.loads(anim_path.read_text()).get("species", {})
    sheet = anim.get(f"{SPECIES:02x}") or anim.get(str(SPECIES))
    if not sheet or len(sheet.get("frames", [])) < 2:
        errors.append("species_anim.json has no multi-frame sheet for $72")
    else:
        print(f"flame: $72 sheet has {len(sheet['frames'])} frames")

    if errors or not args.binary.is_file():
        if not args.binary.is_file() and not errors:
            print("flame: skip runtime (no binary)")
            return 77
        for message in errors:
            print(f"  - {message}")
        print("flame: FAIL")
        return 1

    with tempfile.TemporaryDirectory(prefix="dc-flame-") as td:
        counts = run_trace(args.binary, args.assets, Path(td))
    print(f"flame: area {AREA} drew decor={counts['decor_drawn']} "
          f"(visible {counts['decor_visible']}), "
          f"placeholders={counts['placeholders_drawn']} "
          f"(visible {counts['placeholders_visible']})")
    if counts["decor_drawn"] != len(flames):
        errors.append(f"renderer drew {counts['decor_drawn']} of {len(flames)} "
                      f"decor records")
    if counts["decor_visible"] <= 0:
        errors.append("no flame was inside the initial viewport")
    if counts["placeholders_visible"] != 0:
        errors.append(f"area {AREA} still shows "
                      f"{counts['placeholders_visible']} placeholder box(es)")

    if errors:
        print("flame: FAIL")
        for message in errors:
            print(f"  - {message}")
        return 1
    print("flame: PASS (all 13 $72 flames drawn as decor, no placeholders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
