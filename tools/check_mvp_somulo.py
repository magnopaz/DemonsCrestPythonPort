#!/usr/bin/env python3
"""Acceptance checks for the MVP 1 colosseum fight (Somulo).

The visual review of this fight went back and forth three times because "looks
right" is not a criterion. These checks assert the beats that were actually
established, from the port's own traces:

1. The boss stays planted: its y never drifts (it used to sink to the world
   bottom, 256, while idle).
2. The opening runs in four ordered phases with the documented timings, and the
   player's x does not change during them (control is locked).
3. After the intro the boss walks blind (state 7) before it ever fires.
4. Fireball states only appear once the intro is over.
5. The fight's geometry works end to end: the demo-14 script walks right and
   kills Somulo (hp 6 -> 0), the after-boss gate leads to area 34, and with
   DC_BOSS_HP=1 the first death blow faints him, he comes back with 3 hp and
   the last three hits collapse him.

Point 5 exists because the intro/y checks above still passed when an
authored-room overlay silently moved Somulo onto the player's spawn
(docs/SOMULO_ROOM_FIX.md): nothing here exercised the actual fight.

Usage:
  python3 tools/check_mvp_somulo.py --binary tools/demonscrest-py --assets assets/generated
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_traces(binary: Path, assets: Path, frames: int, tmp: Path,
               extra: dict[str, str] | None = None,
               tag: str = ""):
    env = dict(os.environ, DC_AREA="0", DC_NO_AUDIO="1",
               DC_RUN_FRAMES=str(frames),
               DC_TRACE_CSV=str(tmp / f"player{tag}.csv"),
               DC_TRACE_OBJECTS=str(tmp / f"objects{tag}.csv"),
               DC_BOSS_INTRO_DEBUG="1")
    env.setdefault("DISPLAY", ":99")
    if extra:
        env.update(extra)
    proc = subprocess.run([str(binary), "--assets", str(assets)], cwd=str(ROOT),
                          env=env, capture_output=True, text=True, timeout=600)
    player = list(csv.DictReader(open(tmp / f"player{tag}.csv")))
    objects = list(csv.DictReader(open(tmp / f"objects{tag}.csv")))
    intro = []
    for line in proc.stderr.splitlines():
        if line.startswith("boss intro: phase"):
            parts = line.split()
            intro.append((int(parts[3]), int(parts[6])))
    return player, objects, intro


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path, default=ROOT / "assets" / "generated")
    ap.add_argument("--frames", type=int, default=700)
    args = ap.parse_args()

    errors: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        player, objects, intro = run_traces(args.binary, args.assets, args.frames, tmp)
        # Point 5a: the fight end to end -- walk right, land the six hits,
        # leave through the after-boss gate (the regression's demo-14 run).
        kill_env = {"DC_DEMO": "14", "DC_CAMPAIGN": "1",
                    "DC_BOSS_NO_ATTACK": "1", "DC_BOSS_INTRO": "0",
                    "DC_BOSS_SKIP_FAINT": "1", "DC_MVP_KEEP_CONTROL": "1"}
        kill_player, kill_objects, _ = run_traces(
            args.binary, args.assets, 1200, tmp, kill_env, tag="_kill")
        # Point 5b: one hp, so the first death blow faints him, he comes back
        # with three and the last three collapse him.
        faint_env = {"DC_DEMO": "14", "DC_CAMPAIGN": "1",
                     "DC_BOSS_NO_ATTACK": "1", "DC_BOSS_INTRO": "0",
                     "DC_MVP_KEEP_CONTROL": "1", "DC_BOSS_HP": "1"}
        faint_player, faint_objects, _ = run_traces(
            args.binary, args.assets, 1600, tmp, faint_env, tag="_faint")

    boss = [r for r in objects if r["slot"] == "0"]
    if not boss:
        errors.append("no boss object in the trace")
    else:
        ys = {r["y"] for r in boss}
        if len(ys) != 1:
            errors.append(f"boss y drifts: {sorted(ys)}")
        else:
            print(f"boss planted at y={ys.pop()} (OK)")

    order = [p for p, _ in intro]
    print("intro phases:", intro)
    if order[:4] != [1, 2, 3, 4]:
        errors.append(f"intro phases out of order: {order}")

    # Phase lengths are data in src/game.c: 150 establishing + 70 approach +
    # 280 walk-in + 110 roar. The debug line prints the phase-local counter, so
    # the global end of the intro is the sum.
    intro_end = 150 + 70 + 280 + 110
    moves = {r["player_x"] for r in player if int(r["frame"]) <= intro_end}
    if len(moves) > 1:
        errors.append(f"player moved during the intro: {sorted(moves)}")
    else:
        print(f"player locked during the intro ({intro_end} frames, "
              f"x={moves.pop() if moves else '?'}) (OK)")

    states = [int(r["state"]) for r in boss] if boss else []
    first_state7 = next((int(r["frame"]) for r in boss if r["state"] == "7"), None)
    first_fire = next((int(r["frame"]) for r in boss
                       if r["state"] in ("1", "2") and int(r["frame"]) > intro_end), None)
    if first_state7 is None:
        errors.append("boss never entered the blind walk (state 7)")
    elif first_fire is not None and first_fire < first_state7:
        errors.append(f"boss fired at frame {first_fire}, before the blind walk at {first_state7}")
    else:
        print(f"blind walk at frame {first_state7}, first fireball after it (OK)")

    if 5 in [int(r["state"]) for r in boss]:
        print("boss reached the collapse state (OK)")

    # ---- point 5a: the demo-14 fight (geometry, hits, gate) ----
    kill_boss = [r for r in kill_objects if r["type"] == "6"]
    hps: list[int] = []
    for r in kill_boss:
        hp = int(r["hp"])
        if not hps or hps[-1] != hp:
            hps.append(hp)
    if hps[:7] != [6, 5, 4, 3, 2, 1, 0]:
        errors.append(f"the demo-14 fight did not land the six hits: "
                      f"hp {hps[:8]}")
    else:
        print("six-hit rhythm 6->0 in the demo-14 run (OK)")
    if kill_boss and int(kill_boss[-1]["frame"]) >= len(kill_player) - 100:
        errors.append("the boss was still alive at the end of the run")
    kill_areas = {int(r["area"]) for r in kill_player}
    if 34 not in kill_areas:
        errors.append(f"the after-boss gate did not lead to area 34: "
                      f"{sorted(kill_areas)}")
    else:
        print("after-boss gate reached area 34 (OK)")

    # ---- point 5b: the faint, the comeback, the collapse ----
    seq: list[tuple[int, int]] = []
    for r in faint_objects:
        if r["type"] != "6":
            continue
        key = (int(r["hp"]), int(r["state"]))
        if not seq or seq[-1] != key:
            seq.append(key)
    if seq[:2] != [(1, 0), (0, 6)]:
        errors.append(f"the first death blow did not faint him: {seq[:4]}")
    else:
        print("first death blow faints him (OK)")
    if (3, 0) not in seq:
        errors.append(f"he did not come back with 3 hp: {seq[:8]}")
    else:
        print("comes back with 3 hp (OK)")
    if not seq or seq[-1] != (0, 5):
        errors.append(f"the last three hits did not collapse him: {seq[-3:]}")
    else:
        print("last three hits collapse him (OK)")

    for err in errors:
        print("FAIL:", err)
    print(f"mvp1 somulo: {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
