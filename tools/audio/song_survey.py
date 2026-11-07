#!/usr/bin/env python3
"""Group the save states by the song the sound driver is playing.

The driver keeps the current song's sequence data in APU RAM.  Sweeping the
snapshots and hashing that region gives an exact, audio-independent label for
"which track is this area playing" — no spectral clustering, no guessing.

The region was found by diffing the ARAM of three saves that must share a track
(the cemetery rooms) against seven that must not: `$0E00-$12FF` and
`$2D00-$2FFF` are identical inside the first group and differ from every other
save, which is what per-song data looks like.

Usage:
  python3 tools/audio/song_survey.py --out captures/audio/songs.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, Session, find_saves  # noqa: E402

# Per-song sequence data in APU RAM (see the module docstring).  Only the two
# regions that are stable inside one song *and* differ between songs are used:
# $1700-$1DFF holds live channel state (it flips between two saves of the same
# world map) and would split one song into several groups.
SONG_REGIONS = ((0x0E00, 0x1300), (0x2D00, 0x3000))
# One contiguous dump covers all of them: $0E00-$2FFF.
DUMP_BASE, DUMP_LEN = 0x0E00, 0x2200


def to_l3(src: Path, dst: Path) -> Path:
    raw = src.read_bytes()
    dst.write_bytes(b"NS3L" + struct.pack("<I", 1) + raw[8:])
    return dst


def song_key(aram: bytes, base: int = DUMP_BASE) -> str:
    h = hashlib.sha1()
    for lo, hi in SONG_REGIONS:
        h.update(aram[lo - base:hi - base])
    return h.hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--saves", type=Path, default=None)
    ap.add_argument("--settle", type=int, default=30)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("captures/audio/songs.json"))
    ap.add_argument("--port", type=int, default=4480)
    args = ap.parse_args()

    saves_dir = args.saves or find_saves(args.recomp)
    names = sorted(saves_dir.glob("*.sav"))
    if args.limit:
        names = names[:args.limit]
    if not names:
        raise SystemExit("song_survey: no save states")

    work = Path("captures/audio/_l3")
    work.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict] = {}

    with Session(save=names[0], recomp=args.recomp, port=args.port) as s:
        c = s.client
        c.run_frames(20)
        for i, save in enumerate(names):
            l3 = work / (save.stem + ".l3")
            try:
                to_l3(save, l3)
                c.cmd(f"load_state {l3.resolve().as_posix()}")
            except RuntimeError as exc:
                print(f"  {save.stem}: {exc}")
                continue
            c.run_frames(args.settle)
            aram = bytes.fromhex(c.cmd(
                f"dump_apu_ram {DUMP_BASE:x} {DUMP_LEN}")["hex"].replace(" ", ""))
            area = c.read(0x8D, 1)[0] // 2
            key = song_key(aram)
            rows[save.stem] = {"area": area, "song": key}
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(names)} ...")

    groups: dict[str, list[str]] = defaultdict(list)
    for stem, row in rows.items():
        groups[row["song"]].append(stem)

    print(f"\n{len(names)} saves -> {len(groups)} distinct songs")
    for key, stems in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        areas = sorted({rows[s]["area"] for s in stems})
        print(f"  {key}  n={len(stems):3d} areas={areas}")
        print(f"        {', '.join(stems[:6])}{' ...' if len(stems) > 6 else ''}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"saves": rows,
         "groups": {k: sorted(v) for k, v in groups.items()}}, indent=1))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
