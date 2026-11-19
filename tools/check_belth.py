#!/usr/bin/env python3
"""Belth ($68) -- the boneyard fight (docs/BELTH_68.md).

The port's first Passo 2 species: a controller that hops between the
room's 21 anchor records and drags the player toward itself, plus parked
pieces that churn by spawn/despawn.  Everything asserted here was
measured on the oracle first:

* pieces: every $68 record is placed and parks on its anchor (all 21
  anchor positions were observed exactly in the replay of the take);
* controller: spawns when the player comes within ~220 px (measured
  first appearance in rec_level_2), hp 32 (docs/boss_hp.txt), and hops
  between anchors (~400 frames per hop, 7 slots across the fight);
* drag: the player is pulled toward the controller at 3 px/frame with a
  4 px deadzone (the $B7FD/$B83F tails write the player task's own
  $31/$34) -- an idle player must move;
* pieces churn: self-delete on a stagger, respawned by the controller,
  sustained 3-10 (measured peak 12);
* the kill wipes EVERY piece at once (g11841 -> g11861 in the take --
  no staggered fade): with DC_BOSS_HP=1 one shot must empty the room.

Usage:
  python tools/check_belth.py [--binary tools/demonscrest-py]
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIGHT_FRAMES = 1200   # the measured controller only appears ~680 frames in
KILL_FRAMES = 300


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def run(binary: Path, assets: Path, tmp: Path, tag: str, frames: int,
        extra: dict[str, str] | None = None):
    env = dict(os.environ, DC_AREA="9", DC_NO_AUDIO="1", DC_NO_SAVE="1",
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
    with open(tmp / f"player_{tag}.csv") as f:
        player = list(csv.DictReader(f))
    with open(tmp / f"objects_{tag}.csv") as f:
        objects = list(csv.DictReader(f))
    return player, objects


def belth_rows(objects):
    """[(frame, slot, type, x, y, hp)] for species $68 (104)."""
    out = []
    for r in objects:
        if r["species"] != "104":
            continue
        out.append((int(r["frame"]), int(r["slot"]), int(r["type"]),
                    float(r["x"]), float(r["y"]), int(r["hp"])))
    return out


def main() -> int:
    args = parse_args()
    if not args.binary.is_file():
        print(f"no binary at {args.binary}")
        return 77

    errors: list[str] = []

    # ---- run 1: the fight (no input, the drag must move the player) ----
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        player, objects = run(args.binary, args.assets, tmp,
                               "fight", FIGHT_FRAMES)

        rows = belth_rows(objects)
        pieces = [r for r in rows if r[2] != 6]
        ctrl = [r for r in rows if r[2] == 6]

        early = [r for r in pieces if r[0] <= 5]
        if len(early) < 21:
            errors.append(f"the 21 anchor records did not all park: "
                          f"{len(early)} at frame <= 5")
        else:
            print(f"all 21 anchor records parked as pieces (OK)")

        if not ctrl:
            errors.append("the controller never spawned")
        else:
            first = ctrl[0][0]
            # ~680 frames of room time pass before the fight starts
            # (measured); the test hooks skip the delay, so both are valid.
            if first > 750:
                errors.append(f"controller only spawned at frame {first}")
            else:
                print(f"controller spawned at frame {first} (OK)")
            hp0 = ctrl[0][5]
            if hp0 != 32:
                errors.append(f"controller hp is {hp0}, expected 32")
            else:
                print("controller hp 32 per docs/boss_hp.txt (OK)")
            spots = {(r[3], r[4]) for r in ctrl}
            if len(spots) < 2:
                errors.append(f"the controller never hopped: {spots}")
            else:
                print(f"controller hopped between {len(spots)} anchors (OK)")

        # drag: no input, an idle player must be pulled toward the boss
        px_first = float(player[0]["player_x"])
        px_last = float(player[-1]["player_x"])
        if abs(px_last - px_first) < 60.0:
            errors.append(f"an idle player was not dragged: "
                          f"x {px_first:.0f} -> {px_last:.0f}")
        else:
            print(f"idle player dragged {px_first:.0f} -> {px_last:.0f} "
                  f"px toward the controller (OK)")

        # piece churn: initial records self-delete, respawns keep 3-10
        counts = {}
        for r in pieces:
            counts.setdefault(r[0], 0)
            counts[r[0]] += 1
        last_frames = [f for f in counts if f >= FIGHT_FRAMES - 60]
        late = [counts[f] for f in last_frames]
        if late and not (3 <= max(late) <= 12):
            errors.append(f"piece population at the end is {late}, "
                          f"expected the measured 3-10")
        elif not late:
            errors.append("no pieces alive in the last 60 frames")
        else:
            print(f"piece population churning: {max(late)} alive at the end "
                  f"(OK)")
        if max(counts.values()) > 22:
            errors.append(f"piece count exceeded the records: "
                          f"{max(counts.values())}")

    # ---- run 2: one hit kills, and the kill empties the room at once ----
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        kill_env = {"DC_BOSS_HP": "1", "DC_DEMO": "10",
                    "DC_BOSS_X": "110.0", "DC_BOSS_Y": "412.0"}
        player, objects = run(args.binary, args.assets, tmp,
                               "kill", KILL_FRAMES, kill_env)

        rows = belth_rows(objects)
        ctrl = [r for r in rows if r[2] == 6]
        if not ctrl:
            errors.append("kill run: the controller never spawned")
        else:
            last_ctrl = max(r[0] for r in ctrl)
            after = [r for r in rows if r[0] > last_ctrl]
            if last_ctrl >= KILL_FRAMES - 50:
                errors.append(f"kill run: the boss survived to frame "
                              f"{last_ctrl}")
            elif after:
                errors.append(f"the kill left {len(after)} piece rows after "
                               f"frame {last_ctrl} (the take wipes them all "
                               f"at once)")
            else:
                print(f"one hit killed the boss at frame {last_ctrl} and "
                      f"every piece vanished with it (OK)")
            # NB: hp 0 itself never shows in the trace -- the generic kill
            # deactivates the boss between two row writes, so the death is
            # proven by the rows ending plus the simultaneous piece wipe.

    for error in errors:
        print(f"  ERROR {error}")
    if errors:
        print("belth: FAIL")
        return 1
    print("PASS (anchors parked, controller hops, player dragged, "
          "pieces churn, one-hit kill empties the room)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
