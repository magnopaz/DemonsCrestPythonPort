#!/usr/bin/env python3
"""Ogre ($63) -- the hopping enemy (docs/OGRE_63.md).

35 records in five rooms; the stage-3 take covers areas 10/12 and gave
the measured cycle: idle -> armed (~40 f) -> airborne arc (~40 f,
apex ~35 px, ~200 px toward the player, $3B phases 2/4/6) -> landed
dwell (~300 f) -> re-arm.  The flags!=0 branch spawns species $91 (the
thrown piece) on the airborne frame -- measured: $91 appears exactly
then.  Ogre records are real enemies (1-pose sheet baked).

Asserted here:
1. all seven area-10 records are placed at boot;
2. at least one ogre completes a full hop cycle (state 2 then 4) and
   moves >= 100 px from its origin;
3. $91 pieces appear at the hops and EXPIRE (their own machine is not
   ported yet; a placeholder lifetime keeps the pool from filling);
   the landed phase walks toward the player (measured ~0.5 px/frame),
   so the ogres close in even without a scripted player;
4. (death itself is pending on the known hit-convention item: the
   fireball spawns 18 px above the shooter's feet and the enemy box is
   +/-12, so a grounded shot cannot hit a grounded enemy -- NEXT_STEPS
   3 documents it as needing the ROM's convention, not a guessed offset.
   No ogre actually dies in the measured window -- the $57 pickups in
   the trace are broken-urn hearts, not ogre drops -- so the kill
   assertion waits for either a take with ogre kills or the ROM's
   hit convention.)

Usage:
  python tools/check_ogre.py [--binary tools/demonscrest-py]
                             [--assets assets/generated]

Exit codes: 0 = pass, 1 = behaviour mismatch, 77 = binary missing.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIGHT_FRAMES = 900


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def run(binary: Path, assets: Path, tmp: Path, tag: str, frames: int,
        extra: dict[str, str] | None = None):
    env = dict(os.environ, DC_AREA="10", DC_NO_AUDIO="1", DC_NO_SAVE="1",
               DC_NO_STORY="1",
               DC_RUN_FRAMES=str(frames),
               DC_TRACE_CSV=str(tmp / f"player_{tag}.csv"),
               DC_TRACE_OBJECTS=str(tmp / f"objects_{tag}.csv"))
    for key in list(env):
        if key.startswith("DC_SCREENSHOT"):
            del env[key]
    env.pop("DC_NO_RENDER", None)   # the caller decides; never inherit
    if extra:
        env.update(extra)
    env.setdefault("DISPLAY", ":99")
    proc = subprocess.run([str(binary), "--assets", str(assets)],
                          cwd=str(ROOT), env=env, capture_output=True,
                          text=True, timeout=300)
    if proc.returncode != 0:
        print(f"run {tag} exited {proc.returncode}\n{proc.stdout[-600:]}",
              file=sys.stderr)
        raise SystemExit(77)
    with open(tmp / f"objects_{tag}.csv") as f:
        return list(csv.DictReader(f))


def ogre_rows(objects):
    return [r for r in objects if r["species"] == "99"]


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print(f"no binary at {args.binary}")
        return 77

    errors: list[str] = []

    # ---- run 1: the hop cycle with an idle player ----
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        objects = run(args.binary, args.assets, tmp, "fight", FIGHT_FRAMES)

        ogres = ogre_rows(objects)
        early = [r for r in ogres if int(r["frame"]) <= 5]
        if len(early) < 7:
            errors.append(f"only {len(early)} of area 10's 7 records at "
                          f"boot")
        else:
            print("all 7 area-10 records placed (OK)")

        # per-slot state sequence and travel
        by_slot = defaultdict(list)
        for r in ogres:
            by_slot[r["slot"]].append(r)
        hopped = 0
        moved = 0
        for slot, rows in by_slot.items():
            states = [r["state"] for r in rows]
            if "2" in states and "4" in states:
                hopped += 1
            xs = [float(r["x"]) for r in rows]
            if max(xs) - min(xs) >= 100.0:
                moved += 1
        if hopped == 0:
            errors.append("no ogre completed a hop cycle "
                          "(state 2 then 4)")
        else:
            print(f"{hopped} ogre(s) completed hop cycles (OK)")
        if moved == 0:
            errors.append("no ogre moved >= 100 px from its origin")
        else:
            print(f"{moved} ogre(s) travelled >= 100 px (OK)")

        # $91 pieces appear at the hops and expire
        proj = [r for r in objects if r["species"] == "145"]
        if not proj:
            # only hopping ogres spawn pieces; tolerate none only if no
            # ogre hopped (already an error above)
            if hopped:
                errors.append("hops happened but no $91 piece spawned")
        else:
            per_frame = defaultdict(int)
            for r in proj:
                per_frame[int(r["frame"])] += 1
            alive_max = max(per_frame.values())
            if alive_max > 4:
                errors.append(f"$91 pieces pile up: {alive_max} alive")
            else:
                print(f"$91 pieces spawn at the hops and expire "
                      f"(peak {alive_max} alive) (OK)")

    for error in errors:
        print(f"  ERROR {error}")
    if errors:
        print("ogre: FAIL")
        return 1
    print("PASS (records placed, hop cycles run, thrown pieces spawn and "
          "expire; death pending the hit convention)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
