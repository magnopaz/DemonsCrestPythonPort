#!/usr/bin/env python3
"""Deterministic native regression checks for the Demon's Crest fan port.

Runs the built game in its headless DC_RUN_FRAMES mode, writes trace CSVs,
and asserts the recovered physics/object/HUD invariants. It does not touch
the recomp or ROM: local oracle comparison stays a separate workflow.

Usage:
  python3 tools/run_regression.py
  python3 tools/run_regression.py --binary tools/demonscrest-py --assets assets/generated

Exit codes: 0 = pass, 1 = failure, 77 = assets/binary missing (ctest skip).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path,
                    default=ROOT / "tools" / "demonscrest-py")
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    return ap.parse_args()


def wrapper(binary: Path) -> list[str]:
    cmd = [str(binary)]
    # Always prefer a virtual display on Linux: CI and desktop sessions may
    # advertise DISPLAY without a usable GL context for the test binary.
    if sys.platform.startswith("linux") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    return cmd


PASSWORD_ALPHABET = "BCDFGHJKLMNPQRSTVWXYZ"


def encode_password(stages_cleared: int, max_hp: int, crests: int, form: int,
                    potions: int, scrolls: int, talismans: int) -> str:
    """Mirror of Game_PasswordEncode (32-bit payload + FNV-1a checksum)."""
    payload = ((stages_cleared & 0xFF)
               | ((max_hp & 0xF) << 8)
               | ((crests & 0x3F) << 12)
               | ((form & 0x7) << 18)
               | ((potions & 0x7) << 21)
               | ((scrolls & 0x7) << 24)
               | ((talismans & 0x1F) << 27))
    h = 2166136261
    for i in range(4):
        h ^= (payload >> (i * 8)) & 0xFF
        h = (h * 16777619) & 0xFFFFFFFF
    value = payload | ((h & 0xFF) << 32)
    out = []
    for _ in range(10):
        out.append(PASSWORD_ALPHABET[value % 20])
        value //= 20
    return "".join(reversed(out))


def run_demo(base: list[str], out: Path, demo: int, frames: int,
             env_extra: dict[str, str] | None = None) -> dict[str, Path]:
    player = out / f"demo{demo}_player.csv"
    objects = out / f"demo{demo}_objects.csv"
    projectiles = out / f"demo{demo}_projectiles.csv"
    env = dict(os.environ)
    env.update({
        "DC_DEMO": str(demo),
        "DC_RUN_FRAMES": str(frames),
        "DC_NO_AUDIO": "1",
        "DC_TRACE_CSV": str(player),
        "DC_TRACE_OBJECTS": str(objects),
        "DC_TRACE_PROJECTILES": str(projectiles),
    })
    if env_extra:
        env.update(env_extra)
    print(f"regression: running demo {demo} ({frames} frames)", flush=True)
    try:
        proc = subprocess.run(base, cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"regression: TIMEOUT demo {demo} ({frames} frames)",
              flush=True)
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"demo {demo} exited {proc.returncode}\n{proc.stdout}")
    return {"player": player, "objects": objects, "projectiles": projectiles}


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def close(a: float, b: float, eps: float = 0.01) -> bool:
    return abs(a - b) <= eps


def main() -> int:
    # Every helper script boots the binary itself, so a headless run needs an X
    # display for the whole process, not only for the demos (wrapper() below).
    if (sys.platform.startswith("linux") and not os.environ.get("DISPLAY")
            and shutil.which("xvfb-run")):
        os.execvp("xvfb-run", ["xvfb-run", "-a", sys.executable,
                               str(Path(__file__).resolve()),
                               *sys.argv[1:]])
    args = parse_args()
    binary = args.binary.resolve()
    assets = args.assets.resolve()
    if not binary.is_file():
        print(f"regression: missing binary {binary} (build first)", file=sys.stderr)
        return 77
    needed = ["room.json", "player_anim.json", "fireball_anim.json",
              "hud_bar.png", "hud_slots.png"]
    missing = [name for name in needed if not (assets / name).is_file()]
    if missing:
        print(f"regression: missing assets {missing}; run the extract steps",
              file=sys.stderr)
        return 77

    base = wrapper(binary)
    failures: list[str] = []

    # Sprite gate: structural checks catch the "tilemap fragment baked as an
    # enemy" class of regression before the game draws it.
    audit = Path(__file__).with_name("audit_sprites.py")
    if audit.is_file() and (assets / "species_anim.json").is_file():
        print("regression: auditing generated sprites", flush=True)
        audit_proc = subprocess.run(
            [sys.executable, str(audit), "--assets", str(assets), "--strict"],
            cwd=ROOT, text=True)
        if audit_proc.returncode != 0:
            failures.append("sprite audit failed (see output above)")

    def check(ok: bool, message: str):
        if not ok:
            failures.append(message)

    with tempfile.TemporaryDirectory(prefix="dc-regression-") as td:
        out = Path(td)

        # ---- Boss data contract and runtime presence ----
        boss_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_bosses.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--runtime", "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(boss_proc.returncode == 0,
              "bosses: data/runtime check failed\n" + boss_proc.stdout[-800:])

        # ---- MVP 1: the Somulo fight's beats (planted boss, intro order,
        # control lock, blind walk before the first fireball) ----
        mvp_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_mvp_somulo.py"),
             "--binary", str(binary), "--assets", str(assets)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(mvp_proc.returncode == 0,
              "mvp1: somulo beat check failed\n" + mvp_proc.stdout[-800:])

        # ---- ROM audio: the asset is loopable and the port really plays it,
        # and audio cannot perturb the simulation (on/off traces identical).
        # 77 means no rendered audio yet, which is not a regression.
        audio_check = Path(__file__).with_name("check_audio_assets.py")
        if audio_check.is_file():
            print("regression: checking ROM audio assets", flush=True)
            audio_proc = subprocess.run(
                [sys.executable, str(audio_check), "--binary", str(binary),
                 "--assets", str(assets)],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=600)
            if audio_proc.returncode == 77:
                print("regression: audio assets absent; skipped (procedural "
                      "stand-ins in use)", flush=True)
            else:
                check(audio_proc.returncode == 0,
                      "audio: asset/playback/determinism check failed\n"
                      + audio_proc.stdout[-1200:])

        # ---- Step 3: walk / tap-jump / hold-jump / hover replay ----
        d6 = run_demo(base, out, 6, 603)
        rows = csv_rows(d6["player"])
        check(len(rows) == 603, f"demo6: expected 603 frames, got {len(rows)}")
        if rows:
            first = rows[0]
            check(close(float(first["player_x"]), 332.0),
                  "demo6: spawn X is not 332")
            check(close(float(first["player_y"]), 164.0),
                  "demo6: spawn Y is not 164 (slope snap)")
            check(first["hp"] == "4" and first["max_hp"] == "6",
                  "demo6: initial HP is not 4/6")
            xs = [float(r["player_x"]) for r in rows]
            ys = [float(r["player_y"]) for r in rows]
            check(close(min(xs), 332.0), "demo6: walk-left bound changed")
            check(close(max(xs), 347.383, 0.02),
                  "demo6: 11-frame walk distance changed")
            check(close(max(ys), 164.0, 0.01), "demo6: slope descent changed")
            check(min(ys) < 93.0, "demo6: hold-jump apex is too low")
            check(all(float(r["vy"]) <= 6.01 for r in rows),
                  "demo6: terminal fall clamp exceeded")
            hover = rows[235:256]
            if hover:
                y0 = float(hover[0]["player_y"])
                check(all(close(float(r["player_y"]), y0, 0.001)
                          for r in hover),
                      "demo6: hover did not freeze vertical motion")
                check(all(r["state"] == "3" for r in hover),
                      "demo6: hover state was not stable")

        # ---- Step 4: fireball spawn/velocity/pillar despawn ----
        d7 = run_demo(base, out, 7, 120)
        proj = csv_rows(d7["projectiles"])
        check(len(proj) > 0, "demo7: no projectiles spawned")
        first_shot = [r for r in proj if r["frame"] == "49"]
        check(bool(first_shot), "demo7: expected a shot at frame 49")
        if first_shot:
            p = first_shot[0]
            check(close(float(p["x"]), 376.0) and close(float(p["y"]), 142.0),
                  "demo7: fireball spawn offset changed")
            check(close(float(p["vx"]), 3.0), "demo7: fireball velocity changed")
        check(not any(float(r["x"]) > 384.0 for r in proj
                      if float(r["vx"]) > 0),
              "demo7: right shot passed through the stone pillar")

        # ---- Step 6: urn -> bouncing heart -> heal ----
        d9 = run_demo(base, out, 9, 180)
        rows9 = csv_rows(d9["player"])
        objs9 = csv_rows(d9["objects"])
        hp9 = [int(r["hp"]) for r in rows9]
        check(max(hp9) > min(hp9), "demo9: heart pickup did not heal HP")
        pickups = [r for r in objs9 if r["type"] == "2"]
        check(bool(pickups), "demo9: no pickup object was spawned")
        if pickups:
            ys = [float(r["y"]) for r in pickups]
            vys = [float(r["vy"]) for r in pickups]
            check(min(ys) < 105.0, "demo9: heart pop-up arc is too short")
            check(max(ys) <= 128.01, "demo9: heart fell below the pillar top")
            check(any(close(v, -3.0, 0.01) for v in vys),
                  "demo9: heart did not bounce at the 3.0/frame decrement")

        # ---- Campaign: crest-form cycling (Crest system) ----
        d11 = run_demo(base, out, 11, 180,
                       {"DC_AREA": "1", "DC_CAMPAIGN": "1",
                        "DC_UNLOCK_ALL": "1"})
        rows11 = csv_rows(d11["player"])
        forms = []
        for r in rows11:
            f = int(r.get("form", 0))
            if not forms or forms[-1] != f:
                forms.append(f)
        check(len(set(forms)) >= 3,
              f"demo11: Crest forms did not cycle (got {forms})")
        check(4 in forms or 5 in forms,
              "demo11: Ultimate/Air forms were never selected")

        # ---- Campaign: Area 0 boss gate -> Area 17 transition ----
        d12 = run_demo(base, out, 12, 1200,
                       {"DC_AREA": "0", "DC_CAMPAIGN": "1",
                        "DC_BOSS_INTRO": "0",
                        "DC_BOSS_DEFEATED": "1"})
        rows12 = csv_rows(d12["player"])
        areas12 = []
        for r in rows12:
            a = int(r["area"])
            if not areas12 or areas12[-1] != a:
                areas12.append(a)
        check(areas12 and areas12[0] == 0,
              f"demo12: campaign did not start in Area 0 ({areas12})")
        # With the boss-defeat hook the area clears immediately, so the run
        # pages through GAME_CLEAR into the overworld instead of walking to a
        # gate. Assert that flow.
        modes12 = [int(r["mode"]) for r in rows12]
        check(3 in modes12, f"demo12: area 0 never reached GAME_CLEAR ({sorted(set(modes12))})")
        # GAME_CLEAR -> overworld needs an Enter press; the dedicated check
        # below covers that transition, so only assert the clear here.
        d_clear = run_demo(base, out, 13, 30, {"DC_STATE": "clear"})
        clear_modes = [int(r["mode"]) for r in csv_rows(d_clear["player"])]
        check(5 in clear_modes,
              f"campaign: GAME_CLEAR did not open the overworld ({sorted(set(clear_modes))})")

        # ---- Campaign: direct multi-row area loads ----
        for area in (2, 3):
            d = run_demo(base, out, 2, 20, {"DC_AREA": str(area)})
            rows_a = csv_rows(d["player"])
            check(bool(rows_a) and int(rows_a[0]["area"]) == area,
                  f"area {area}: room_area{area}.json was not loaded")
            if rows_a:
                check(float(rows_a[0]["camera_x"]) >= 0.0,
                      f"area {area}: camera X is negative")

        # ---- Campaign: title -> New Game -> Area 0 ----
        d13 = run_demo(base, out, 13, 120, {"DC_TITLE": "1"})
        rows13 = csv_rows(d13["player"])
        check(any(int(r["area"]) == 0 for r in rows13),
              "demo13: title NEW GAME did not enter Area 0")

        # ---- Attract mode: idle title starts a demo, Start cancels it ----
        at = run_demo(base, out, 0, 700, {"DC_TITLE": "1"})
        at_modes = [int(r["mode"]) for r in csv_rows(at["player"])]
        check(0 in at_modes and at_modes[-1] == 1,
              f"title: attract demo did not start ({sorted(set(at_modes))})")
        at2 = run_demo(base, out, 33, 700, {"DC_TITLE": "1"})
        at2_modes = [int(r["mode"]) for r in csv_rows(at2["player"])]
        check(at2_modes and at2_modes[-1] == 0,
              f"title: Start did not cancel the attract demo ({sorted(set(at2_modes))})")

        # ---- Observed doors from the level saves (M1 navigation) ----
        # Area 4's observed door (x=2025) lies outside the extracted world
        # (1024 wide) -- see the "needs wider extraction" report in
        # check_navigation.py; it is skipped until the room is re-extracted.
        # The old 8->10 hop was removed with its door: the save belonged to
        # the avenue (area 4) and the box sat on the pit's spawn.
        for src_area, sx, sy, dst_area in ((2, 1706, 300, 4),
                                           (0, 740, 190, 34),
                                           (10, 1264, 104, 18),
                                           (20, 440, 144, 22),
                                           (76, 226, 141, 78),
                                           (58, 224, 128, 60)):
            # 140 frames: a room change is 28 fade-out + 64 black + 28 fade-in
            # on the console, and the area only appears once the new room runs.
            hop = run_demo(base, out, 36, 140, {
                "DC_AREA": str(src_area),
                "DC_START_X": str(sx),
                "DC_START_Y": str(sy),
                "DC_CAMPAIGN": "1",
                "DC_BOSS_CLEAR": "1",
            })
            hop_rows = csv_rows(hop["player"])
            hop_areas = {int(r["area"]) for r in hop_rows}
            check(dst_area in hop_areas,
                  f"door: area {src_area} door did not reach area {dst_area} "
                  f"(saw {sorted(hop_areas)})")

        # ---- City NPC conversation (A near the NPC opens the dialogue) ----
        npc = run_demo(base, out, 0, 100,
                       {"DC_AREA": "8", "DC_DEMO": "34"})
        npc_modes = [int(r["mode"]) for r in csv_rows(npc["player"])]
        check(11 in npc_modes, "npc: talking to the city NPC did not open dialogue")

        # ---- Ending variants render ----
        for variant in ("bad", "normal", "good", "true"):
            er = run_demo(base, out, 0, 12,
                          {"DC_STATE": "ending", "DC_ENDING": variant})
            modes_e = [int(r["mode"]) for r in csv_rows(er["player"])]
            check(10 in modes_e, f"ending: variant {variant} did not render")

        # ---- Pause menu SAVE writes progress ----
        pause_save = out / "pause_save.json"
        if pause_save.exists():
            pause_save.unlink()
        run_demo(base, out, 32, 20,
                 {"DC_STATE": "pause", "DC_CAMPAIGN": "1",
                  "DC_SAVE_PATH": str(pause_save), "DC_SAVE_FORCE": "1"})
        check(pause_save.is_file(), "pause: SAVE did not write a save file")
        if pause_save.is_file():
            data = json.loads(pause_save.read_text())
            check(isinstance(data.get("area"), int),
                  "pause: save file has no area field")

        # ---- Wall cling: automatic, sliding, capped at 0x00C0 ----
        cling_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_wall_cling.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(cling_proc.returncode == 0,
              "wall cling: check failed\n" + cling_proc.stdout[-800:])

        # ---- Species $67: the ROM ghoul state machine ----
        ghoul_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_ghoul.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(ghoul_proc.returncode == 0,
              "ghoul: state machine check failed\n" + ghoul_proc.stdout[-800:])

        # ---- Species $09: the cemetery Hippogriff fight ----
        hip_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_hippogriff.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(hip_proc.returncode == 0,
              "hippogriff: fight check failed\n" + hip_proc.stdout[-800:])

        # ---- Species $A5: Arma, the Earth Crest and the map room ----
        arma_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_arma.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(arma_proc.returncode == 0,
              "arma: crest/map check failed\n" + arma_proc.stdout[-800:])

        # ---- The world map is drawn as a Mode 7 plane ----
        mode7_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_map_mode7.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(mode7_proc.returncode == 0,
              "mode7: map projection check failed\n" + mode7_proc.stdout[-800:])

        # ---- Object placement: every retail record reaches the room ----
        obj_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_objects.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(obj_proc.returncode == 0,
              "objects: placement/placeholder check failed\n"
              + obj_proc.stdout[-800:])

        # ---- Species $72: the cemetery's torch flames, drawn as decor ----
        flame_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_flame.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(flame_proc.returncode == 0,
              "flame: $72 decor check failed\n" + flame_proc.stdout[-800:])

        # ---- Room transition: the console's 28+64+28 INIDISP fade ----
        fade_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_transition_fade.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(fade_proc.returncode == 0,
              "transition: fade profile failed\n" + fade_proc.stdout[-800:])

        # ---- pad_mask: the up-doors and the 5->6/6->7/7->8 gates ----
        # Standing on a door without pressing up must not change the area;
        # the avenue's three take-measured doors must open when up is tapped.
        up_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_up_doors.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(up_proc.returncode == 0,
              "up doors: pad_mask check failed\n" + up_proc.stdout[-800:])

        # ---- Death: the continue hub, not a game over ----
        death_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_death_menu.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(death_proc.returncode == 0,
              "death menu: continue hub check failed\n"
              + death_proc.stdout[-800:])

        # ---- Pit of Ovununu: the boss opening + the $6C launch/return ----
        pit_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_pit_boss.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(pit_proc.returncode == 0,
              "pit boss: opening/launch check failed\n"
              + pit_proc.stdout[-800:])

        # ---- Pit of Ovununu: HP and damage (docs/boss_hp.txt) ----
        pit_dmg = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_pit_damage.py")],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=120)
        check(pit_dmg.returncode == 0,
              "pit damage: HP/damage check failed\n" + pit_dmg.stdout[-800:])

        # ---- Boss HP from docs/boss_hp.txt (table + rooms + runtime) ----
        boss_hp = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_boss_hp.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(boss_hp.returncode == 0,
              "boss hp: table/runtime check failed\n" + boss_hp.stdout[-800:])

        # ---- Arma 2's first-encounter dialogue (story flag) ----
        arma2_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_arma2_intro.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=600)
        check(arma2_proc.returncode == 0,
              "arma2 intro: story-flag dialogue check failed\n"
              + arma2_proc.stdout[-800:])

        # ---- End-to-end campaign playthrough ----
        play = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_playthrough.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(play.returncode == 0,
              "playthrough: campaign flow failed\n" + play.stdout[-800:])

        # ---- Boss entries clear when the boss is defeated ----
        boss_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_campaign.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--areas", "0,3,4,23,36,46,49", "--frames", "120",
             "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(boss_proc.returncode == 0,
              "campaign: boss entries did not clear\n" + boss_proc.stdout[-600:])

        # ---- Overworld stage select travels to a real stage entry ----
        st = run_demo(base, out, 30, 40, {"DC_STATE": "overworld"})
        st_rows = csv_rows(st["player"])
        check(bool(st_rows) and int(st_rows[-1]["area"]) == 16,
              "stage select: travel did not reach area 16")

        # ---- Fire crest piece: walking into the pickup grants an element ----
        fire_demo = run_demo(base, out, 1, 200,
                             {"DC_AREA": "3", "DC_START_X": "400",
                              "DC_START_Y": "440"})
        fire_rows = csv_rows(fire_demo["player"])
        fire_vals = [int(r["fire"]) for r in fire_rows]
        check(fire_vals and fire_vals[0] == 0 and fire_vals[-1] >= 1,
              "fire: crest piece pickup did not grant a fire element")

        # ---- Campaign load coverage: representative areas ----
        subset = "0,1,2,3,4,5,17,21,25,46,92,109"
        area_proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_areas.py"),
             "--binary", str(binary), "--assets", str(assets),
             "--areas", subset, "--frames", "30", "--tmp", str(out)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300)
        check(area_proc.returncode == 0,
              "areas: load-check failed\n" + area_proc.stdout[-600:])

        # ---- Save/options persistence: autosave, then resume ----
        save_path = out / "dc_save.json"
        save_path.unlink(missing_ok=True)
        run_demo(base, out, 12, 200,
                 {"DC_AREA": "0", "DC_CAMPAIGN": "1",
                  "DC_BOSS_DEFEATED": "1", "DC_SAVE_PATH": str(save_path),
                  "DC_SAVE_FORCE": "1"})
        check(save_path.is_file(), "save: autosave did not write a save file")
        if save_path.is_file():
            data = json.loads(save_path.read_text())
            check(int(data.get("version", 0)) == 2, "save: unexpected version")
            resumed = out / "resume_player.csv"
            env = dict(os.environ,
                       DC_RESUME="1", DC_RUN_FRAMES="2", DC_NO_AUDIO="1",
                       DC_SAVE_PATH=str(save_path), DC_SAVE_FORCE="1",
                       DC_TRACE_CSV=str(resumed))
            proc = subprocess.run(base, cwd=ROOT, env=env,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  timeout=120)
            check(proc.returncode == 0, "save: resume run failed")
            rows_s = csv_rows(resumed) if resumed.is_file() else []
            check(bool(rows_s), "save: resume produced no trace")
            if rows_s:
                first = rows_s[0]
                check(int(first["max_hp"]) == int(data["max_hp"]),
                      "save: max_hp was not restored")
                check(int(first["gold"]) == int(data["gold"]),
                      "save: gold was not restored")
                check(int(first["area"]) == int(data["area"]),
                      "save: area was not restored")

        # ---- Password codec: self-test and applying a code ----
        env_self = dict(os.environ, DC_PASSWORD_SELFTEST="1")
        proc = subprocess.run(base, cwd=ROOT, env=env_self,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              timeout=60)
        check(proc.returncode == 0,
              f"password: codec selftest failed ({proc.stdout.strip()})")
        code = encode_password(3, 8, 0x3F, 2, 5, 4, 0x1F)
        d_pw = run_demo(base, out, 2, 4, {"DC_PASSWORD": code})
        rows_pw = csv_rows(d_pw["player"])
        check(bool(rows_pw) and int(rows_pw[0]["max_hp"]) == 8,
              f"password: max_hp not restored from {code}")
        check(bool(rows_pw) and int(rows_pw[0]["form"]) == 2,
              f"password: form not restored from {code}")

        # ---- Campaign: Somulo defeat ends the area ----
        d14 = run_demo(base, out, 7, 300,
                       {"DC_AREA": "0", "DC_CAMPAIGN": "1",
                        "DC_BOSS_INTRO": "0", "DC_BOSS_SKIP_FAINT": "1",
                        "DC_BOSS_HP": "1", "DC_START_X": "560",
                        "DC_START_Y": "172", "DC_BOSS_X": "600",
                        "DC_BOSS_Y": "150"})
        rows14 = csv_rows(d14["player"])
        modes14 = [int(r["mode"]) for r in rows14]
        check(bool(rows14) and any(m != 1 for m in modes14),
              "demo12/boss: Somulo defeat did not leave GAME_PLAYING")

        # ---- MVP: the Somulo fight, start to gate ----
        d14 = run_demo(base, out, 14, 1200,
                       {"DC_AREA": "0", "DC_CAMPAIGN": "1",
                        "DC_BOSS_NO_ATTACK": "1",
                        "DC_BOSS_INTRO": "0", "DC_BOSS_SKIP_FAINT": "1",
                        "DC_MVP_KEEP_CONTROL": "1"})
        rows14 = csv_rows(d14["player"])
        objs14 = csv_rows(d14["objects"])
        areas14 = [int(r["area"]) for r in rows14]
        check(0 in areas14, f"MVP: area 0 never ran ({sorted(set(areas14))})")
        check(34 in areas14,
              f"MVP: the gate after Somulo did not lead to area 34 "
              f"({sorted(set(areas14))})")
        boss14 = [r for r in objs14 if int(r["type"]) == 6]
        hps = []
        for r in boss14:
            hp = int(r["hp"])
            if not hps or hps[-1] != hp:
                hps.append(hp)
        # The first death blow is not death: Somulo faints, comes back with three
        # hits left and then collapses. That shape is asserted separately below
        # with DC_BOSS_HP=1; this run uses DC_BOSS_SKIP_FAINT so the gate after
        # the fight can still be exercised in one pass.
        check(hps[:7] == [6, 5, 4, 3, 2, 1, 0],
              f"MVP: the six-hit rhythm is wrong: hp went {hps}")
        check(boss14 and int(boss14[-1]["frame"]) < len(rows14) - 100,
              "MVP: the boss was still alive at the end of the run")

        # ---- MVP: the post-faint phase (3 hits left, then the collapse) ----
        d4 = run_demo(base, out, 14, 1600,
                       {"DC_AREA": "0", "DC_CAMPAIGN": "1",
                        "DC_BOSS_NO_ATTACK": "1", "DC_BOSS_INTRO": "0",
                        "DC_MVP_KEEP_CONTROL": "1", "DC_BOSS_HP": "1"})
        boss4 = [r for r in csv_rows(d4["objects"]) if r["type"] == "6"]
        seq4 = []
        for r in boss4:
            key = (int(r["hp"]), int(r["state"]))
            if not seq4 or seq4[-1] != key:
                seq4.append(key)
        check(seq4[:2] == [(1, 0), (0, 6)],
              f"MVP: the first death blow did not faint him: {seq4}")
        check((3, 0) in seq4,
              f"MVP: he did not come back with 3 hp: {seq4}")
        check(seq4[-1] == (0, 5),
              f"MVP: the last three hits did not collapse him: {seq4}")

        # 420 frames: the authentic ghoul spends its first 256 in the volley
        # (32 + 3x64 + 32) before the hop that takes it off the ledge.
        d10 = run_demo(base, out, 10, 420,
                       {"DC_START_X": "930", "DC_START_Y": "160"})
        rows10 = csv_rows(d10["player"])
        hp10 = [int(r["hp"]) for r in rows10]
        check(any(hp10[i] < hp10[i - 1] for i in range(1, len(hp10))),
              "demo10: the species 67 ghoul did not damage the player")
        check(any(hp10[i] > hp10[i - 1] for i in range(1, len(hp10))),
              "demo10: no healing pickup was collected")
        enemies10 = [r for r in csv_rows(d10["objects"]) if r["type"] == "3"]
        check(bool(enemies10), "demo10: no enemy objects spawned")
        # The authentic $83:AF74 ghoul is a ranged attacker: state 2 fires
        # species $67 projectiles (object type 7). Contact damage still happens
        # when it leaps, but kills need a ground target, checked below.
        shots = [r for r in csv_rows(d10["objects"]) if r["type"] == "7"]
        check(bool(shots), "demo10: the ghoul never fired a projectile")
        # The $B2E8 decision must let a perched ghoul leave its ledge and drop
        # to the player's floor (its y grows by more than a tile).
        perch: dict[str, list[float]] = {}
        for r in enemies10:
            perch.setdefault(r["slot"], []).append(float(r["y"]))
        check(any(max(v) - v[0] > 40.0 for v in perch.values()),
              "demo10: no ghoul descended from its perch")

        # ---- Fireballs damage enemies: area 2's floating sentry ----
        # This used to stand on the floor at (360,430) and assert a skeleton
        # died. It only passed because the player died first and the trace
        # stopped at frame 229: ground-level fireballs fly 18 px above the
        # feet while the enemy box is +/-12 around the spawn origin, so they
        # miss (a Passo 2 gap). The continue hub keeps the scene running, which
        # exposed the false pass. Stand on the upper ledge at (1000,300), where
        # the fireball line (y=334) meets the floating enemy at y=332, and
        # assert the hit -- a real projectile/enemy collision.
        d10b = run_demo(base, out, 10, 260,
                        {"DC_AREA": "2", "DC_START_X": "1000",
                         "DC_START_Y": "300"})
        enemies_b = [r for r in csv_rows(d10b["objects"]) if r["type"] == "3"]
        hp_b: dict[str, list[int]] = {}
        for r in enemies_b:
            hp_b.setdefault(r["slot"], []).append(int(r["hp"]))
        check(bool(hp_b), "area2: no enemies spawned")
        check(any(any(b < a for a, b in zip(v, v[1:])) for v in hp_b.values()),
              "area2: no enemy took fireball damage")

    if failures:
        print("regression: FAIL")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("regression: PASS (demos 6,7,9,10,11,12,13, boss data/runtime, "
          "hippogriff fight, arma crest/map chain, mode 7 map, "
          "object placement/placeholders, $72 flames, up-door pad_mask, "
          "death continue hub, pit boss opening/launch + damage, "
          "boss hp/damage (boss_hp.txt), arma2 intro flag, "
          "boss defeat + multi-area loads)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
