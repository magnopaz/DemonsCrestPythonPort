#!/usr/bin/env python3
"""Capture the console's own sound effects, one per APU command.

How the music is removed
------------------------
Two runs start from the same save state.  The second one presses buttons that
make the game send sound commands; the first one does nothing.  Subtracting the
first run's PCM from the second leaves only what the commands added.

That only works when the two runs are sample-identical, and by default they are
not: the emulator produces audio faster than the dummy device drains it, so the
output ring drops samples at wall-clock-dependent points (two "identical" runs
measured a mean absolute difference of ~1,900 LSB).  Pacing the emulation to
real time removes the drops ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â `audio_stats` reports `dropped=0` and the two runs
compare *bit-identical* ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â which is what `paced_run()` does here.

One pair of runs yields every effect the input script triggered: the commands
the game sent are decoded from the run's port traffic, each is cut out of the
difference at its own sample, and the script step it happened under names it.

Usage:
  python3 tools/audio/capture_sfx.py --all
  python3 tools/audio/capture_sfx.py --save <sav> --script file.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apu_commands import POLL, decode, drain  # noqa: E402
from oracle import DEFAULT_RECOMP, NATIVE_RATE, Session, find_saves  # noqa: E402

# A walk / jump / shoot routine that makes the game talk to the sound driver.
# Each step is (buttons, frames); the step's name is what labels the effect.
SCRIPT = [
    ("", "", 20), ("walk", "right", 40), ("jump", "right+b", 5), ("walk", "right", 25),
    ("", "", 40), ("jump", "b", 5), ("", "", 50), ("shoot", "y", 5), ("", "", 30),
    ("walk", "right", 40), ("jump", "b", 5), ("", "", 45), ("shoot", "y", 5),
    ("", "", 25), ("walk", "left", 30), ("jump", "b", 5), ("", "", 40), ("shoot", "y", 5),
    ("", "", 40), ("jump", "right+b", 5), ("walk", "right", 30), ("", "", 30),
]

# Cut window: a little lead-in so the attack is not clipped, and a bounded tail
# because the driver may steal a music voice when it keys the effect.
LEAD_SECONDS = 0.05
MAX_SECONDS = 0.9
FADE_SECONDS = 0.02
TRIM_WINDOW = 0.01        # envelope resolution for the tail search
TRIM_RATIO = 0.20         # tail ends where the envelope falls under 20% peak (RMS)
TRIM_KEEP = 0.04          # keep 40 ms past that point
NORMALISE = 0.85


def read_pcm(path: Path) -> list[int]:
    with wave.open(str(path)) as w:
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    pcm = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    if ch == 2:
        pcm = [(pcm[i] + pcm[i + 1]) // 2 for i in range(0, len(pcm) - 1, 2)]
    return pcm


def write_pcm(path: Path, pcm: list[int], rate: int) -> None:
    clipped = [max(-32768, min(32767, int(v))) for v in pcm]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % len(clipped), *clipped))


def paced_run(client, script, settle: int, chunk: int = 4) -> int:
    """Run frames at ~1x real time so the ring never drops a sample."""
    def advance(frames: int) -> None:
        done = 0
        while done < frames:
            step = min(chunk, frames - done)
            client.run_frames(step)
            done += step
            time.sleep(step / 60.0 * 1.15)

    advance(settle)
    for step in script:
        name, buttons, frames = step
        client.cmd(f"set_controller {buttons or 'none'}")
        advance(frames)
    client.cmd("set_controller none")
    advance(6)
    return client.frame()


def capture(save: Path, recomp: Path, port: int, script, settle: int,
            wav: Path, press: bool) -> tuple[list[int], list, int, dict, int]:
    with Session(save=save, recomp=recomp, port=port) as s:
        c = s.client
        c.run_frames(settle)                       # plain settle, not captured
        _, cursor = drain(c, 0)
        p0 = int(c.cmd("audio_stats")["produced"])
        f0 = c.frame()
        if press:
            paced_run(c, script, 0)
        else:
            paced_run(c, [("", "", f) for _, _, f in script], 0)
        stats = c.cmd("audio_stats")
        total = int(stats["produced"]) - p0
        if stats.get("dropped_audible"):
            raise RuntimeError(f"dropped {stats['dropped_audible']} audible samples")
        c.cmd(f"audio_wav {wav.resolve().as_posix()} {p0} {total}")
        events, cursor = drain(c, cursor)
        return read_pcm(wav), decode(events), p0, stats, f0


def script_steps(script, f0: int) -> list[tuple[int, int, str, str]]:
    """(first_frame, last_frame, name, buttons) per step, in capture frames."""
    out = []
    frame = f0
    for name, buttons, frames in script:
        out.append((frame, frame + frames, name, buttons))
        frame += frames
    return out


def step_for(steps, frame: int) -> tuple[str, str]:
    for lo, hi, name, buttons in steps:
        if lo <= frame < hi:
            return name, buttons
    if steps and frame >= steps[-1][1]:
        return steps[-1][2], steps[-1][3]
    return "", ""


def cut(diff: list[int], centre: int, rate: int) -> list[int]:
    """The effect around `centre`, trimmed and peak-normalised."""
    lo = max(0, centre - int(LEAD_SECONDS * rate))
    hi = min(len(diff), centre + int(MAX_SECONDS * rate) + int(LEAD_SECONDS * rate))
    seg = diff[lo:hi]
    if not seg:
        return []
    peak = max((abs(v) for v in seg), default=0)
    if peak == 0:
        return []

    # The driver answers a command a few dozen milliseconds later, so the cut
    # starts with silence.  Drop it, keeping a 5 ms pre-roll for the attack.
    gate = peak * 0.02
    first = 0
    while first < len(seg) and abs(seg[first]) < gate:
        first += 1
    if first >= len(seg):
        return []
    seg = seg[max(0, first - int(0.005 * rate)):]
    peak = max((abs(v) for v in seg), default=0)
    if peak == 0:
        return []

    # Tail: the last window whose RMS is still above a fraction of the loudest
    # window.  Past that the difference is the music voice the driver stole.
    win = max(1, int(TRIM_WINDOW * rate))
    energies = [sum(v * v for v in seg[i:i + win]) for i in range(0, len(seg), win)]
    if not energies:
        return []
    top = max(energies)
    floor = top * (TRIM_RATIO ** 2)
    end = len(seg)
    for i in range(len(energies) - 1, -1, -1):
        if energies[i] > floor:
            end = min(len(seg), (i + 1) * win + int(TRIM_KEEP * rate))
            break
    # Do not cut inside the attack when the whole effect is short.
    end = max(end, min(len(seg), int(0.09 * rate)))
    seg = seg[:end]

    fade = min(int(FADE_SECONDS * rate), max(1, len(seg) // 4))
    for i in range(fade):
        seg[len(seg) - fade + i] = int(seg[len(seg) - fade + i] * (1.0 - i / fade))

    scale = (NORMALISE * 32767.0) / peak
    return [int(v * scale) for v in seg]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--all", action="store_true", help="run the scripted sweep")
    ap.add_argument("--one-button", default="",
                    help="press only this button (e.g. y) instead of the full "
                         "script; attributes every command to one input")
    ap.add_argument("--sequence", default="",
                    help="custom script: name=buttons/frames,...")
    ap.add_argument("--out", type=Path, default=Path("captures/audio/sfx"))
    ap.add_argument("--settle", type=int, default=90)
    ap.add_argument("--port", type=int, default=4800)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    script = SCRIPT
    if args.one_button:
        script = [("", "", 30), (f"press {args.one_button}", args.one_button, 6),
                  ("", "", 70)]
    elif args.sequence:
        script = []
        for item in args.sequence.split(","):
            name, rest = item.split("=", 1)
            buttons, frames = rest.rsplit("/", 1)
            script.append((name, buttons, int(frames)))
    saves = find_saves(args.recomp)
    jobs: list[tuple[str, Path]] = []
    if args.all:
        for name in ("lvl_I_murkland-cemetery",
                     "lvl_I_murkland-slope",
                     "lvl_II_ruined-city-dark-avenue",
                     "lvl_IV_towers-of-doom-misty-skies",
                     "lvl_V_poseidonia-aquatica",
                     "lvl_VI_mountains-ice-spire"):
            path = saves / f"{name}.sav"
            if path.is_file():
                jobs.append((name, path))
    elif args.save:
        jobs.append((args.save.stem, args.save))
    else:
        raise SystemExit("capture_sfx: pass --save, --all or --sequence")

    report: dict = {"sources": {}, "effects": {}}
    manifest = args.out / "sfx_manifest.json"
    if manifest.is_file():
        try:                      # accumulate across invocations
            previous = json.loads(manifest.read_text())
            report["effects"] = previous.get("effects", {})
            report["sources"] = previous.get("sources", {})
        except ValueError:
            pass
    for job, save in jobs:
        a_wav = args.out / f"_music_{job}.wav"
        b_wav = args.out / f"_with_{job}.wav"
        print(f"{job}: run A (music only)")
        a, _ca, _p0a, _st, _f0a = capture(save, args.recomp, args.port, script,
                                          args.settle, a_wav, press=False)
        print(f"{job}: run B (input)")
        b, cmds, p0, st_b, f0 = capture(save, args.recomp, args.port + 1, script,
                                        args.settle, b_wav, press=True)
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        diff = [b[i] - a[i] for i in range(n)]
        probe = max(1, int(0.4 * NATIVE_RATE))
        residual = sum(abs(v) for v in diff[:probe]) / probe
        print(f"{job}: dropped={st_b.get('dropped')}/{st_b.get('dropped_audible')} "
              f"residual {residual:.2f} LSB")
        if residual > 1.0:
            # The two runs did not cancel: the emulator produced a different
            # number of samples at some point, so this difference is noise.
            print(f"{job}: SKIPPED (music did not cancel)")
            report["sources"][job] = {
                "save": str(save), "dropped": st_b.get("dropped"),
                "residual_lsb": round(residual, 3), "commands": len(cmds),
                "skipped": True,
            }
            continue
        report["sources"][job] = {
            "save": str(save), "dropped": st_b.get("dropped"),
            "residual_lsb": round(residual, 3), "commands": len(cmds),
        }

        steps = script_steps(script, f0)
        for cmd in cmds:
            if cmd.cmd == POLL:
                continue
            centre = cmd.sample - p0
            if not (0 <= centre < len(diff)):
                continue
            seg = cut(diff, centre, NATIVE_RATE)
            if not seg:
                continue
            step, buttons = step_for(steps, cmd.frame)
            name = f"cmd{cmd.cmd:02x}"
            path = args.out / f"{name}.wav"
            # Keep the longest capture of a command: a later run may catch the
            # same effect with a clipped window.
            previous = report["effects"].get(name)
            if previous and previous.get("seconds", 0) > len(seg) / NATIVE_RATE:
                continue
            write_pcm(path, seg, NATIVE_RATE)
            report["effects"][name] = {
                "cmd": cmd.cmd,
                "file": path.name,
                "step": step,
                "buttons": buttons,
                "offset_seconds": round(centre / NATIVE_RATE, 3),
                "seconds": round(len(seg) / NATIVE_RATE, 3),
                "peak": max((abs(v) for v in seg), default=0),
                "source": job,
            }
            print(f"  cmd 0x{cmd.cmd:02x} ({step or '?'} / {buttons or '-'}) "
                  f"-> {path.name} {len(seg) / NATIVE_RATE:.3f} s")

    manifest.write_text(json.dumps(report, indent=1))
    print(f"\ncaptured {len(report['effects'])} effect(s) -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



