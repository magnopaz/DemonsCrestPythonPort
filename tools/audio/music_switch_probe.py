#!/usr/bin/env python3
"""Watch the music change when the player walks through a door.

Every `*_before_door` save is one input away from another area, so the sound
driver receives its "start this song" command during the transition.  That
command carries the song number, which is the one reliable label for a track —
far better than trying to cluster the audio.

Usage:
  python3 tools/audio/music_switch_probe.py --saves lvl_I_murkland-cemetery_before_door
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import DEFAULT_RECOMP, Session, find_saves  # noqa: E402


def drain(c, cursor: int) -> tuple[list[dict], int]:
    out: list[dict] = []
    while True:
        msg = c.port_events(cursor, 8000)
        batch = msg.get("events", [])
        if not batch:
            break
        out.extend(batch)
        cursor = int(batch[-1]["s"]) + 1
        if len(batch) < 8000:
            break
    return out, cursor


def run_one(save: Path, recomp: Path, port: int, settle: int, hold: int,
            buttons: str, after: int) -> None:
    with Session(save=save, recomp=recomp, port=port) as s:
        c = s.client
        c.run_frames(settle)
        _, cursor = drain(c, 0)
        area0 = c.read(0x8D, 1)[0] // 2
        c.cmd(f"set_controller {buttons}")
        c.run_frames(hold)
        c.cmd("set_controller none")
        c.run_frames(after)
        area1 = c.read(0x8D, 1)[0] // 2
        events, cursor = drain(c, cursor)
        writes = [e for e in events if e["t"] == "cpu_wr"]
        print(f"{save.stem}: area {area0} -> {area1}, {len(writes)} port writes")
        seq = " ".join(f"f{e['aux']}:p{e['adr']}={e['val']}" for e in writes[:80])
        print("   ", seq)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recomp", type=Path, default=DEFAULT_RECOMP)
    ap.add_argument("--saves", default="")
    ap.add_argument("--buttons", default="up")
    ap.add_argument("--settle", type=int, default=90)
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--after", type=int, default=150)
    ap.add_argument("--port", type=int, default=4450)
    args = ap.parse_args()

    d = find_saves(args.recomp)
    names = (args.saves.split(",") if args.saves
             else [p.stem for p in sorted(d.glob("*before_door*.sav"))])
    for i, stem in enumerate(n for n in names if n):
        try:
            run_one(d / f"{stem}.sav", args.recomp, args.port + i, args.settle,
                    args.hold, args.buttons, args.after)
        except SystemExit as exc:
            print(f"{stem}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
