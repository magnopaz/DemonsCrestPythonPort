#!/usr/bin/env python3
"""Match a large object's live OAM against `$8B:8000` metasprite groups.

`match_group_from_oam.py` requires the OAM near an object to equal a ROM frame
exactly, which only works for sprites that fit inside its search window.  A boss
is bigger than the window and shares the screen with other objects, so this tool
searches the other way round: every part of a candidate ROM frame must appear in
the live OAM at the same relative offset (extras allowed), which recovers the
group, frame and object origin even when the sprite is 130 px tall.

Usage:
  python3 tools/oracle/match_big_group.py --report /tmp/slotprobe/report.json \
      --out /tmp/big_votes.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dc_extract"))

from extract import Rom  # noqa: E402

ROM = ROOT.parent / "roms" / "Demon's Crest (USA).sfc"


def load_groups(rom: Rom, max_frames: int, max_parts: int):
    groups = {}
    for gid in range(256):
        try:
            frames = rom.parse_metasprite_group(gid)
        except Exception:  # noqa: BLE001 - junk ids decode to junk
            continue
        frames = [f for f in frames if f]
        if not frames or len(frames) > max_frames:
            continue
        if max(len(f) for f in frames) > max_parts:
            continue
        groups[gid] = frames
    return groups


def match_frame(parts, sprites, tol=0):
    """Return (base, ox, oy) if every part appears in `sprites`, else None."""
    p0 = parts[0]
    best = None
    for s in sprites:
        if s["size"] != p0["size"] or s["hflip"] != p0["hflip"] \
                or s["vflip"] != p0["vflip"]:
            continue
        base = (s["tile"] - p0["tile"]) & 0xFF
        ox = s["x"] - p0["dx"]
        oy = s["y"] - p0["dy"]
        used = {s["i"]}
        ok = True
        for p in parts[1:]:
            want_tile = (p["tile"] + base) & 0xFF
            hit = None
            for t in sprites:
                if t["i"] in used or t["size"] != p["size"]:
                    continue
                if t["x"] == ox + p["dx"] and t["y"] == oy + p["dy"] \
                        and t["tile"] == want_tile \
                        and t["hflip"] == p["hflip"] \
                        and t["vflip"] == p["vflip"]:
                    hit = t["i"]
                    break
            if hit is None:
                ok = False
                break
            used.add(hit)
        if ok:
            score = (len(parts), -len(sprites))
            if best is None or score > best[0]:
                best = (score, base, ox, oy)
    if best is None:
        return None
    return best[1], best[2], best[3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-frames", type=int, default=32)
    ap.add_argument("--max-parts", type=int, default=80)
    ap.add_argument("--min-parts", type=int, default=8)
    args = ap.parse_args()

    rom = Rom(ROM)
    groups = load_groups(rom, args.max_frames, args.max_parts)
    print(f"{len(groups)} candidate groups")
    doc = json.loads(args.report.read_text())
    votes = defaultdict(lambda: defaultdict(int))
    detail = []
    for sample in doc["samples"]:
        sprites = sample["near"]
        if len(sprites) < args.min_parts:
            continue
        for gid, frames in groups.items():
            for fi, parts in enumerate(frames):
                if len(parts) < args.min_parts:
                    continue
                hit = match_frame(parts, sprites)
                if hit is None:
                    continue
                base, ox, oy = hit
                dx = ox - sample["screen"][0]
                dy = oy - sample["screen"][1]
                votes[gid][fi] += 1
                detail.append({"frame": sample["frame"], "group": gid,
                               "frame_index": fi, "base": base,
                               "origin": [ox, oy],
                               "screen": sample["screen"],
                               "obj_offset": [sample["screen"][0] - ox,
                                              sample["screen"][1] - oy],
                               "parts": len(parts)})
    print(f"{len(detail)} matches")
    for gid in sorted(votes, key=lambda g: -sum(votes[g].values())):
        tot = sum(votes[gid].values())
        top = sorted(votes[gid].items(), key=lambda kv: -kv[1])[:12]
        print(f"group {gid:02X}: {tot} votes, frames "
              + ", ".join(f"{fi}x{n}" for fi, n in top))
    if args.out:
        args.out.write_text(json.dumps(
            {"votes": {f"{g:02x}": dict(v) for g, v in votes.items()},
             "detail": detail}, indent=1))
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
