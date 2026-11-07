#!/usr/bin/env python3
"""Sweep every save state and fingerprint the music that is playing.

The APU half of a `.sav` snapshot is restored by the `load_state` command even
though the title's own resume context is not, so one oracle process can march
through the whole save collection and record what the sound driver plays in
each one.  That answers the only question the capture step needs: *which areas
share a track*.

The fingerprint is a chroma vector (12 pitch-class bins from the log-magnitude
spectrum) plus a coarse log-band spectrum.  Chroma is what makes two captures
of the same track at different positions of the loop look alike; the band
profile keeps two tracks in the same key apart.

Usage:
  python3 tools/audio/music_survey.py --out captures/audio/music_survey.json
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, NATIVE_RATE, Session, find_saves  # noqa: E402


def to_l3(src: Path, dst: Path) -> Path:
    raw = src.read_bytes()
    dst.write_bytes(b"NS3L" + struct.pack("<I", 1) + raw[8:])
    return dst


def read_wav(path: Path) -> tuple[list[int], int, int]:
    with wave.open(str(path)) as w:
        ch = w.getnchannels()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    n = len(raw) // 2
    pcm = list(struct.unpack("<%dh" % n, raw))
    if ch == 2:  # fold to mono
        pcm = [(pcm[i] + pcm[i + 1]) // 2 for i in range(0, len(pcm) - 1, 2)]
    return pcm, rate, ch


def _fft(re: list[float], im: list[float]) -> None:
    """In-place iterative radix-2 FFT (n a power of two)."""
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wr, wi = math.cos(ang), math.sin(ang)
        half = length >> 1
        for i in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(half):
                ar = re[i + k + half] * cr - im[i + k + half] * ci
                ai = re[i + k + half] * ci + im[i + k + half] * cr
                re[i + k + half] = re[i + k] - ar
                im[i + k + half] = im[i + k] - ai
                re[i + k] += ar
                im[i + k] += ai
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1


def fingerprint(pcm: list[int], rate: int, nfft: int = 2048,
                hop: int = 4096) -> dict:
    """Chroma + log-band profile + RMS of a mono capture."""
    if not pcm:
        return {"rms": 0.0, "chroma": [0.0] * 12, "bands": [0.0] * 16}
    rms = math.sqrt(sum(v * v for v in pcm) / len(pcm))
    chroma = [0.0] * 12
    bands = [0.0] * 16
    frames = 0
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (nfft - 1))
              for i in range(nfft)]
    band_edges = [62.5 * (2 ** (i / 2.0)) for i in range(17)]  # half-octaves
    for start in range(0, len(pcm) - nfft, hop):
        re = [pcm[start + i] * window[i] / 32768.0 for i in range(nfft)]
        im = [0.0] * nfft
        _fft(re, im)
        for bin_ in range(1, nfft // 2):
            freq = bin_ * rate / nfft
            if freq < 50.0 or freq > 4000.0:
                continue
            mag = math.hypot(re[bin_], im[bin_])
            if mag < 1e-6:
                continue
            midi = 69.0 + 12.0 * math.log2(freq / 440.0)
            pc = int(round(midi)) % 12
            chroma[pc] += mag
            for b in range(16):
                if band_edges[b] <= freq < band_edges[b + 1]:
                    bands[b] += mag
                    break
        frames += 1
    if frames:
        for i in range(12):
            chroma[i] /= frames
        for i in range(16):
            bands[i] /= frames
    norm = math.sqrt(sum(v * v for v in chroma)) or 1.0
    chroma = [v / norm for v in chroma]
    norm = math.sqrt(sum(v * v for v in bands)) or 1.0
    bands = [v / norm for v in bands]
    return {"rms": rms, "chroma": chroma, "bands": bands}


def similarity(a: dict, b: dict) -> float:
    c = sum(x * y for x, y in zip(a["chroma"], b["chroma"]))
    s = sum(x * y for x, y in zip(a["bands"], b["bands"]))
    return 0.6 * c + 0.4 * s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--saves", type=Path, default=None)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--settle", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", type=Path,
                    default=Path("captures/audio/music_survey.json"))
    ap.add_argument("--wavdir", type=Path, default=None,
                    help="keep each capture here instead of deleting it")
    ap.add_argument("--port", type=int, default=4445)
    args = ap.parse_args()

    saves_dir = args.saves or find_saves(args.recomp)
    names = sorted(saves_dir.glob("*.sav"))
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        names = [p for p in names if p.stem in wanted]
    if args.limit:
        names = names[:args.limit]
    if not names:
        raise SystemExit("music_survey: no save states")

    work = Path("captures/audio/_l3")
    work.mkdir(parents=True, exist_ok=True)
    tmp = Path("captures/audio/_survey_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    if args.wavdir:
        args.wavdir.mkdir(parents=True, exist_ok=True)

    count = int(args.seconds * NATIVE_RATE)
    out: dict = {"captures": {}}

    with Session(save=names[0], recomp=args.recomp, port=args.port) as s:
        c = s.client
        c.run_frames(20)
        for i, save in enumerate(names):
            l3 = work / (save.stem + ".l3")
            to_l3(save, l3)
            c.cmd(f"load_state {l3.resolve().as_posix()}")
            c.run_frames(args.settle)
            area = c.read(0x8D, 1)[0] // 2
            produced = int(c.cmd("audio_stats")["produced"])
            wav = (tmp / "probe.wav").resolve()
            begin = max(0, produced - count)
            c.cmd(f"audio_wav {wav.as_posix()} {begin} {count}")
            pcm, rate, ch = read_wav(wav)
            fp = fingerprint(pcm, rate)
            fp["area"] = area
            fp["frames"] = [c.frame()]
            out["captures"][save.stem] = fp
            if args.wavdir:
                (args.wavdir / (save.stem + ".wav")).write_bytes(wav.read_bytes())
            print(f"[{i + 1}/{len(names)}] {save.stem:58s} area={area:3d} "
                  f"rms={fp['rms']:7.1f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
