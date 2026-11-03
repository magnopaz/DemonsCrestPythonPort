#!/usr/bin/env python3
"""Force the recompiled oracle to load an arbitrary area id and capture it.

Why this exists
---------------
The area id is not a "load this room" switch: writing WRAM `$008D` alone does
nothing (PROJECT_STATE trap 22).  The guest only builds a room from `$008D`
while it runs the *room-load task* (task id 4 -> `$80:B71A`), and that task is
entered from the game's own transition code, which is what writes `$008D` in
the first place:

    80:BB58  lda $008D       ; current area byte offset
    80:BB69  sta $0E56       ; remember the old room
    80:BB6C  lsr / tax
    80:BB6E  lda $97DA,X     ; next area byte offset (sequential progression)
    80:BB75  sta $008D       ; <-- the only writer during a screen transition
    80:BB7F  jmp $BAB7       ; -> "switch current task to id 4" (room loader)

The loader reads `$008D` again *after* the fade-out, so a write that lands in
the window between the transition starting and the room build wins.  This tool
therefore:

  1. resumes a save that stands in front of a door (the cemetery right door by
     default) and holds the walk button until `$008D` changes,
  2. overwrites `$008D` with `2 * target` every frame for the next ~30 frames,
  3. samples the frames after the build and scores the live BG1 against the
     ROM screen table (`room_match`), keeping only screens that belong to the
     target area, so a window that is really still the old room cannot score,
  4. writes `fNNNNNN.json` + `fNNNNNN.vram.bin` (the format
     `capture_area_frame.py` and the extractor use) into `captures/area<N>/`,
     keeping only the winning frame.

Verification is the point: a capture is only accepted when the live 64x32 BG1
window matches a screen of the target area at >= 0.9 (row-vote score, i.e. the
same test `map_saves_to_areas.py` uses to identify a save's room), so a "loaded"
room that is really still the old one is rejected and retried with the next
trigger save.  When nothing verifies the tool prints the areas the frame *does*
look like instead of writing a capture.

Usage
-----
  python3 tools/oracle/load_area.py --area 70
  python3 tools/oracle/load_area.py --area 35 --save build-trace/saves/foo.sav
  python3 tools/oracle/load_area.py --area 99 --out captures/area99
  python3 tools/oracle/load_area.py --area 16 --walk-chunk 1 --attempts 5
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dump_save_wram import DEFAULT_RECOMP, DEFAULT_ROM, connect, ppu_inidisp, wait_visible  # noqa: E402
import room_match as RM  # noqa: E402

AREA_PTR = 0x008D          # WRAM byte offset into the area pointer table ($81:A291)
OLD_AREA = 0x0E56          # previous room, copied by the transition code
MIN_ROW_CONTENT = 8        # nonzero words for a window row to count as content

# Saves that stand in front of a door with a short, reliable walk.  Each entry
# is (save name, button).  The cemetery right door is the default: 2 -> 4 is
# the first transition of the game and it needs no crests or bosses dead.
TRIGGERS = [
    ("lvl_I_murkland-cemetery_before_door.sav", "right"),
    ("lvl_II_ruined-city-dark-avenue_before_door.sav", "right"),
    ("lvl_I_murkland-slope_before_door.sav", "right"),
    ("lvl_IV_towers-of-doom-gryphon-spire_before_door.sav", "right"),
    ("lvl_VII_phalanxs-fortress-front-hall_before_door.sav", "right"),
    ("lvl_VI_mountains-ice-crevasse_before_door_grewon.sav", "right"),
]


# --------------------------------------------------------------------------- #
# ROM side: which screens belong to an area, and how well a live BG1 matches
# --------------------------------------------------------------------------- #
_ROM_CACHE: dict = {}


def rom_index(rom):
    """(rom, row index, screen->areas) cached: building it takes ~2 s."""
    key = str(getattr(rom, "path", "rom"))
    if key not in _ROM_CACHE:
        _ROM_CACHE[key] = (rom, RM.build_screen_rows(rom),
                           RM.build_screen_to_areas(rom))
    return _ROM_CACHE[key]


class AreaMatcher:
    """Score a live BG1 window against the screens that belong to one area.

    The metric is `room_match`'s row-vote score, restricted to the screens of
    the target area: 1.0 means a 32x32 window of the live 64x32 BG1 tilemap is
    one of the area's ROM screens cell for cell.  A room that is still the old
    one cannot score, and a window split across two screens (the guest aligns
    its VRAM ring to the camera, so a tall room's window can straddle a screen
    row) scores its best half - which is why `rows_matched` is reported too.
    """

    def __init__(self, area: int, rom=None):
        self.area = area
        self.rom, self.rows_index, self.screen_areas = rom_index(rom or RM.load_rom())
        self.screens = {k for k, v in self.screen_areas.items()
                        if any(a == area for a, _pos in v)}
        info = self.rom.area_info(area)
        self.info = {"set": info["set"], "width": info["width"],
                     "height": info["height"],
                     "screens": len(info["screens"])}

    def score(self, frame_json: Path, vram_path: Path, layer: int = 0) -> dict:
        try:
            w, h, tiles, ppu = RM.read_frame(frame_json, vram_path, layer)
        except (KeyError, IndexError, ValueError) as exc:
            return {"score": 0.0, "screen": None, "error": str(exc)}
        votes = RM.screen_votes(w, h, tiles, self.rows_index)
        best = {"score": 0.0, "screen": None, "votes": 0, "offset": None}
        for (set_id, scr), v in votes.items():
            if (set_id, scr) not in self.screens:
                continue
            sc = v["votes"] / RM.CELL
            if sc > best["score"]:
                best = {"score": sc, "screen": (set_id, scr),
                        "votes": v["votes"], "offset": v["offset"]}
        # Diagnostic: how many content-bearing rows of that window are rows of
        # the area's screens (a low score with high coverage means the room is
        # right but the VRAM ring is only partly rewritten).
        best["rows_matched"] = self._rows_matched(w, h, tiles, best["offset"])
        return best

    def _rows_matched(self, w: int, h: int, tiles: list[int], offset) -> int:
        if offset is None:
            return 0
        ox, oy = offset
        matched = 0
        for y in range(RM.CELL):
            yy = (oy + y) % h
            row = [int(tiles[yy * w + ((ox + i) % w)]) & RM.WORD_MASK
                   for i in range(RM.CELL)]
            if sum(1 for t in row if t) < MIN_ROW_CONTENT:
                continue
            blob = b"".join(t.to_bytes(2, "little") for t in row)
            by_row = self.rows_index.get(blob)
            if by_row and any((s, sc) in self.screens
                              for lst in by_row.values() for (s, sc) in lst):
                matched += 1
        return matched


def diagnose(out: Path, matcher: "AreaMatcher", limit: int = 4) -> list:
    """Rank every area for the best frame in `out` (what actually loaded)."""
    if not list(out.glob("f*.json")):
        return []
    r = RM.identify_dir(out, matcher.rom, matcher.rows_index, matcher.screen_areas)
    return [(a, round(sc, 3), v["screen"], v["layer"])
            for sc, a, v in r["ranked"][:limit]]


# --------------------------------------------------------------------------- #
# Guest driving
# --------------------------------------------------------------------------- #
class Oracle:
    def __init__(self, recomp: Path, rom: Path, save: Path, port: int,
                 log_path: Path | None = None):
        self.recomp = recomp
        self.rom = rom
        self.save = save
        self.port = port
        self.log_path = log_path
        self.proc = None
        self.client = None
        self.log = None
        self.resume = None

    def __enter__(self):
        exe = self.recomp / "build-trace" / "DemonsCrestSNESRecomp"
        if not exe.is_file():
            raise SystemExit(f"missing trace build: {exe}")
        # The host rewrites the game-directory prefix of every path argument, so
        # the one-shot resume state must live inside the recomp tree.
        self.resume = (self.recomp / f"_dc_loadarea_{self.port}.sav").resolve()
        shutil.copyfile(self.save.resolve(), self.resume)
        env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(self.port),
                   SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        self.log = open(self.log_path or
                        self.recomp / f"_dc_loadarea_{self.port}.log", "wb")
        self.proc = subprocess.Popen(
            [str(exe), str(self.rom.resolve()), "--paused",
             "--resume-state", str(self.resume)],
            cwd=str(self.recomp), env=env, stdout=self.log, stderr=self.log)
        self.client = connect(self.port)
        return self

    def __exit__(self, *exc):
        try:
            if self.client is not None:
                self.client.close()
        finally:
            if self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            if self.log is not None:
                self.log.close()
            try:
                if self.resume is not None:
                    self.resume.unlink()
            except FileNotFoundError:
                pass
        return False

    # --- memory / frames
    def area_byte(self) -> int:
        return self.client.read_ram(AREA_PTR, 1)[0]

    def area(self) -> int:
        return self.area_byte() // 2

    def run(self, n: int = 1):
        self.client.run_to(self.client.frame() + n)

    def poke_area(self, area: int):
        # dump_save_wram.Client has no write helper; the server takes hex bytes.
        r = self.client.cmd(f"write_ram {AREA_PTR:x} {(area * 2) & 0xFF:02x}")
        if "error" in r:
            raise RuntimeError(f"write_ram failed: {r['error']}")

    def inidisp(self) -> int:
        return ppu_inidisp(self.client)

    def dump(self, out: Path, ring_back: int = 1) -> int:
        out.mkdir(parents=True, exist_ok=True)
        n = max(0, self.client.frame() - ring_back)
        state = self.client.cmd(f"get_frame_extended {n}")
        vram = self.client.cmd(f"dump_frame_vram {n}")
        (out / f"f{n:06d}.json").write_text(json.dumps(state, indent=1))
        (out / f"f{n:06d}.vram.bin").write_bytes(
            bytes.fromhex(vram["hex"].replace(" ", "")))
        return n


def drive_transition(oracle: Oracle, area: int, button: str,
                     walk_frames: int, walk_chunk: int,
                     poke_frames: int, verbose: bool) -> dict:
    """Hold `button` until the room transition starts, then retarget it."""
    old = oracle.area_byte()
    oracle.client.cmd(f"set_controller {button}")
    changed_at = None
    frames = 0
    while frames < walk_frames:
        oracle.run(walk_chunk)
        frames += walk_chunk
        cur = oracle.area_byte()
        if cur != old:
            changed_at = frames
            break
    if changed_at is None:
        oracle.client.cmd("clear_controller")
        return {"ok": False, "reason": "no transition (walk never left the room)",
                "frames": frames}
    if verbose:
        print(f"    transition at +{changed_at} frames: $008D "
              f"{old:#04x} -> {oracle.area_byte():#04x} (area {oracle.area()})")

    # The loader reads $008D again after the fade-out; keep it pinned to the
    # target for the whole window so a late read cannot win.
    for _ in range(poke_frames):
        oracle.poke_area(area)
        oracle.run(1)
    oracle.client.cmd("clear_controller")
    return {"ok": True, "frames": frames, "changed_at": changed_at,
            "area_byte_before": old}


def wait_and_score(oracle: Oracle, matcher: AreaMatcher, out: Path,
                   samples: int, sample_step: int,
                   min_score: float, verbose: bool) -> dict:
    """Sample the frames after the build and keep the best match.

    The room is in VRAM as soon as the build runs, so a dark frame verifies
    too - and it is often the *only* good frame: the guest drops the player at
    the target room's spawn point, which for a room that is not the door's real
    destination can be mid-air, so the room fades back in and then fades to
    black on the death.  A lit frame is still preferred when two frames tie,
    because that is what the extractor's other captures look like.
    """
    best = {"score": 0.0, "score_split": 0.0}
    lit_seen = False
    for i in range(samples):
        if i:
            oracle.run(sample_step)
        disp = oracle.inidisp()
        lit = (disp & 0x0F) >= 0x0C
        lit_seen = lit_seen or lit
        n = oracle.dump(out)
        r = matcher.score(out / f"f{n:06d}.json", out / f"f{n:06d}.vram.bin", 0)
        r.update(frame=n, inidisp=disp, area=oracle.area(), lit=lit)
        if verbose:
            print(f"    f{n}: area={r['area']} score={r['score']:.3f} "
                  f"rows={r.get('rows_matched', 0)}/{RM.CELL} "
                  f"screen={r['screen']} inidisp={disp:#04x}")
        better = (r["score"] > best["score"] or
                  (r["score"] == best["score"] and lit and not best.get("lit")))
        if better:
            best = r
        if r["score"] >= min_score and lit:
            break
    best["lit_seen"] = lit_seen
    return best


def finish(area: int, out: Path, save: Path, button: str, oracle: Oracle,
           r: dict, start_area: int, attempts: list, method: str) -> dict:
    """Write the winning frame + capture.json and report success."""
    # Keep only the winning frame: the capture dir must hold one fNNNNNN pair,
    # like capture_area_frame.py writes.
    for stray in list(out.glob("f*.json")) + list(out.glob("f*.vram.bin")):
        if not stray.name.startswith(f"f{r['frame']:06d}."):
            stray.unlink()
    meta = {"save": str(save), "button": button, "target_area": area,
            "area_byte": oracle.area_byte(), "frames": [r["frame"]],
            "visible": bool(r.get("lit")), "score": r["score"],
            "screen": r["screen"], "rows_matched": r.get("rows_matched", 0),
            "start_area": start_area, "method": method}
    (out / "capture.json").write_text(json.dumps(meta, indent=1))
    print(f"[area {area}] OK score={r['score']:.3f} screen={r['screen']} "
          f"frame={r['frame']} -> {out}")
    return {"ok": True, "area": area, "out": str(out), **meta,
            "attempts": attempts}


def load_area(area: int, args) -> dict:
    matcher = AreaMatcher(area)
    out = Path(args.out) if args.out else ROOT / "captures" / f"area{area}"
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("f*.json")) + list(out.glob("f*.vram.bin")):
        old.unlink()

    triggers = [(Path(args.save), args.button)] if args.save else [
        (Path(args.saves_dir) / name, btn) for name, btn in TRIGGERS]
    attempts = []
    for attempt, (save, button) in enumerate(triggers[: args.attempts]):
        if not save.is_file():
            attempts.append({"save": str(save), "ok": False,
                             "reason": "missing save"})
            continue
        print(f"[area {area}] trigger {save.name} ({button})")
        try:
            # A fresh port per attempt: the previous guest may still be shutting
            # down and a reused port races the old listener.
            with Oracle(Path(args.recomp), Path(args.rom), save,
                        args.port + attempt, out / "capture.log") as o:
                if not wait_visible(o.client):
                    attempts.append({"save": save.name, "ok": False,
                                     "reason": "screen never lit"})
                    continue
                o.run(args.settle)
                start_area = o.area()
                if start_area == area:
                    # Already there: nothing to force, capture what is on screen.
                    r = wait_and_score(o, matcher, out, args.samples,
                                       args.sample_step, args.min_score, True)
                    if r["score"] >= args.min_score:
                        return finish(area, out, save, button, o, r, start_area,
                                      attempts, "save-already-there")
                    attempts.append({"save": save.name, "ok": False,
                                     "reason": "save already in the target area",
                                     "start_area": start_area, **r})
                    continue
                step = drive_transition(o, area, button, args.walk_frames,
                                        args.walk_chunk, args.poke_frames, True)
                if not step["ok"]:
                    attempts.append({"save": save.name, **step})
                    continue
                r = wait_and_score(o, matcher, out, args.samples,
                                   args.sample_step, args.min_score, True)
                r["start_area"] = start_area
                if r["score"] < args.min_score:
                    r["diagnosis"] = diagnose(out, matcher)
                    print(f"[area {area}] not verified: best areas by BG1 = "
                          f"{r['diagnosis']}")
                attempts.append({"save": save.name, "ok": r["score"] >= args.min_score,
                                 **step, **r})
                if r["score"] >= args.min_score:
                    return finish(area, out, save, button, o, r, start_area,
                                  attempts, "transition-retarget")
        except Exception as exc:  # noqa: BLE001 - a failed trigger must not stop the batch
            attempts.append({"save": save.name, "ok": False, "error": repr(exc)})
            print(f"[area {area}] trigger failed: {exc!r}")
    print(f"[area {area}] FAILED - no trigger produced a matching room")
    return {"ok": False, "area": area, "attempts": attempts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", type=int, required=True, help="extractor area id 0..112")
    ap.add_argument("--out", type=Path, default=None,
                    help="capture dir (default captures/area<N>)")
    ap.add_argument("--save", type=Path, default=None,
                    help="resume this save instead of the built-in door triggers")
    ap.add_argument("--saves-dir", type=Path,
                    default=ROOT.parent / "DemonsCrestSNESRecomp" / "build-trace" / "saves")
    ap.add_argument("--recomp", type=Path,
                    default=Path(os.environ.get("RECOMP_DIR", DEFAULT_RECOMP)))
    ap.add_argument("--rom", type=Path, default=Path(os.environ.get("ROM", DEFAULT_ROM)))
    ap.add_argument("--port", type=int, default=4630)
    ap.add_argument("--button", default="right", help="walk button for --save")
    ap.add_argument("--settle", type=int, default=90, help="frames after the first lit frame")
    ap.add_argument("--walk-frames", type=int, default=900, help="max frames to reach the door")
    ap.add_argument("--walk-chunk", type=int, default=4,
                    help="frames per poll while walking (smaller = catches the "
                         "transition earlier)")
    ap.add_argument("--poke-frames", type=int, default=30,
                    help="frames to keep $008D pinned to the target")
    ap.add_argument("--samples", type=int, default=24, help="frames to score")
    ap.add_argument("--sample-step", type=int, default=12,
                    help="frames between scored samples")
    ap.add_argument("--min-score", type=float, default=0.9)
    ap.add_argument("--attempts", type=int, default=3, help="trigger saves to try")
    ap.add_argument("--json", type=Path, default=None, help="write a result report")
    args = ap.parse_args()

    if not 0 <= args.area <= 112:
        raise SystemExit("--area must be 0..112")
    result = load_area(args.area, args)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
