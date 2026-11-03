#!/usr/bin/env python3
"""Extract frames from a video with the bundled ffmpeg.

Usage:
  python tools/video_frames.py <video.mp4> [--out DIR] [--every N]
                              [--fps F] [--start SEC] [--end SEC]
                              [--sheet] [--scale W]

`--every N` keeps one frame out of every N; `--fps F` asks ffmpeg for F frames
per second. With `--sheet` it also writes contact_sheet.png with frame labels, so
a whole take can be skimmed in one image.

The ffmpeg binary comes from imageio-ffmpeg (`pip install imageio-ffmpeg`), so no
system install is required.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:  # pragma: no cover - dependency hint
        raise SystemExit("install it first: pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(exe: str, video: Path) -> dict:
    """Read stream info from ffmpeg's stderr banner."""
    proc = subprocess.run([exe, "-i", str(video)], capture_output=True, text=True)
    text = proc.stderr
    info = {}
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", text)
    if m:
        h, mi, s = m.groups()
        info["duration"] = int(h) * 3600 + int(mi) * 60 + float(s)
    m = re.search(r"Stream #\d+:\d+.*?Video: (\w+).*?(\d{2,5})x(\d{2,5})", text)
    if m:
        info["codec"], info["width"], info["height"] = (
            m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d+(?:\.\d+)?) fps", text)
    if m:
        info["fps"] = float(m.group(1))
    return info


def extract(exe: str, video: Path, out: Path, every: int, fps: float | None,
            start: float | None, end: float | None, scale: int | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start}"]
    if end is not None:
        cmd += ["-to", f"{end}"]
    cmd += ["-i", str(video)]
    filters = []
    if every and every > 1:
        filters.append(f"select='not(mod(n\\,{every}))'")
        cmd += ["-vsync", "vfr"]
    if fps:
        filters.append(f"fps={fps}")
    if scale:
        filters.append(f"scale={scale}:-1:flags=neighbor")
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += [str(out / "frame_%05d.png")]
    print("running:", " ".join(cmd[:8]), "...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"ffmpeg failed ({proc.returncode})")
    frames = sorted(out.glob("frame_*.png"))
    print(f"{len(frames)} frames -> {out}")
    return len(frames)


def contact_sheet(out: Path, cols: int = 6) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    frames = sorted(out.glob("frame_*.png"))
    if not frames:
        return None
    thumbs = []
    for path in frames:
        im = Image.open(path).convert("RGB")
        thumbs.append((path.stem, im))
    w, h = thumbs[0][1].size
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 14)), (16, 16, 20))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(thumbs):
        x, y = (i % cols) * w, (i // cols) * (h + 14)
        sheet.paste(im, (x, y + 14))
        d.text((x + 2, y + 1), name.replace("frame_", ""), fill=(255, 255, 0))
    dest = out / "contact_sheet.png"
    sheet.save(dest)
    print("sheet ->", dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--every", type=int, default=10,
                    help="keep one frame out of N (default 10)")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--scale", type=int, default=None)
    ap.add_argument("--sheet", action="store_true")
    args = ap.parse_args()

    if not args.video.is_file():
        raise SystemExit(f"no such video: {args.video}")
    exe = ffmpeg_exe()
    info = probe(exe, args.video)
    print("video:", args.video.name, json.dumps(info))

    out = args.out or args.video.with_suffix("")
    count = extract(exe, args.video, out, args.every, args.fps, args.start,
                    args.end, args.scale)
    if args.sheet and count:
        contact_sheet(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
