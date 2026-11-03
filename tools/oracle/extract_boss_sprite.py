#!/usr/bin/env python3
"""Extract a boss sprite from live frames by temporal differencing.

Multi-part bosses cannot be attributed reliably from OAM, but they *animate*:
capture several exact frames of the boss scene (`run_to_frame` +
`dump_frame_raw`), diff them to find the animated region, then key out the
static background using the dominant border colour.

Usage:
  python tools/oracle/extract_boss_sprite.py --save save0a --frames 6 \
      --spacing 6 --out assets/generated/boss_33_0.png [--keep-frames DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

RECOMP = Path(r"M:\Opencode\DemonsCrestSNESRecomp")
EXE = RECOMP / "build-trace" / "DemonsCrestSNESRecomp.exe"
ROM = Path(r"M:\Opencode\roms\Demon's Crest (USA).sfc")
SAVES = RECOMP / "build-trace" / "saves"
W, H = 256, 224


class Client:
    def __init__(self, sock):
        self.f = sock.makefile("rwb")

    def cmd(self, text):
        self.f.write((text + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        return json.loads(line) if line else {}

    def frame(self):
        return int(self.cmd("frame")["frame"])


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connect(port: int, timeout: float = 90) -> Client:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            sock.settimeout(60)
            return Client(sock)
        except OSError:
            time.sleep(0.1)
    raise SystemExit("no debug server")


def load_frame(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def components(mask: Image.Image, min_area: int = 120):
    """Simple 4-connected components on a binary ('1'/'0') image."""
    px = mask.load()
    seen = bytearray(W * H)
    out = []
    for y in range(H):
        for x in range(W):
            if seen[y * W + x] or not px[x, y]:
                continue
            stack = [(x, y)]
            seen[y * W + x] = 1
            pts = []
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy),
                               (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < W and 0 <= ny < H and not seen[ny * W + nx] \
                            and px[nx, ny]:
                        seen[ny * W + nx] = 1
                        stack.append((nx, ny))
            if len(pts) >= min_area:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                out.append({"area": len(pts),
                            "bbox": (min(xs), min(ys), max(xs) + 1, max(ys) + 1),
                            "pts": pts})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", required=True)
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--spacing", type=int, default=6)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep-frames", type=Path, default=None)
    ap.add_argument("--pad", type=int, default=14)
    args = ap.parse_args()

    work = args.keep_frames or (args.out.parent / "boss_frames")
    work.mkdir(parents=True, exist_ok=True)
    stem = args.save if args.save.startswith("save") else f"save{args.save}"
    src = next((SAVES / f"{c}.sav" for c in (args.save, stem, f"save_{args.save}")
                if (SAVES / f"{c}.sav").is_file()), None)
    if src is None:
        raise SystemExit(f"save not found: {args.save}")
    tmp = work / "resume.sav"
    shutil.copyfile(src, tmp)

    port = free_port()
    env = dict(os.environ, SNESRECOMP_DEBUG_PORT=str(port),
               SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    log = open(work / "run.log", "wb")
    proc = subprocess.Popen([str(EXE), str(ROM), "--paused",
                             "--resume-state", str(tmp)],
                            cwd=str(RECOMP), env=env, stdout=log, stderr=log)
    try:
        c = connect(port)
        # Resuming starts in forced blank; advance until the picture is visible.
        for _ in range(600):
            ppu = c.cmd("get_ppu_state")
            disp = int(str(ppu.get("inidisp", "0x80")), 16)
            if (disp & 0x0F) >= 0x0C:
                break
            c.cmd(f"run_to_frame {c.frame() + 1}")
            time.sleep(0.01)
        c.cmd(f"run_to_frame {c.frame() + args.warmup}")
        time.sleep(0.2)
        paths = []
        for k in range(args.frames):
            target = c.frame() + (args.spacing if k else 1)
            for attempt in range(12):
                c.cmd(f"run_to_frame {target}")
                time.sleep(0.05)
                path = (work / f"frame{k:02d}.bmp").resolve().as_posix()
                reply = c.cmd(f"screenshot {path}")
                if not reply.get("ok"):
                    print("screenshot failed:", reply)
                    target = c.frame() + 1
                    continue
                with Image.open(path) as probe_img:
                    if probe_img.convert("RGB").getbbox() is not None:
                        paths.append(Path(path))
                        break
                target = c.frame() + 2
        if len(paths) < 2:
            raise SystemExit("not enough visible frames captured")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        tmp.unlink(missing_ok=True)

    frames = [load_frame(p) for p in paths]
    changed = Image.new("L", (W, H), 0)
    for a, b in zip(frames, frames[1:]):
        diff = ImageChops.difference(a, b).convert("L")
        changed = ImageChops.lighter(changed, diff.point(lambda v: 255 if v > 26 else 0))
    changed = changed.filter(ImageFilter.MaxFilter(5))

    comps = components(changed, min_area=150)
    comps.sort(key=lambda c: c["area"], reverse=True)
    if not comps:
        raise SystemExit("no animated region found")
    # The player sits near the screen centre; prefer the largest component whose
    # centre is not within 40 px of the player's usual spot.
    def centre(c):
        x0, y0, x1, y1 = c["bbox"]
        return (x0 + x1) / 2, (y0 + y1) / 2
    pick = None
    for comp in comps:
        cx, cy = centre(comp)
        if abs(cx - W / 2) > 40:
            pick = comp
            break
    pick = pick or comps[0]
    x0, y0, x1, y1 = pick["bbox"]
    x0 = max(0, x0 - args.pad)
    y0 = max(0, y0 - args.pad)
    x1 = min(W, x1 + args.pad)
    y1 = min(H, y1 + args.pad)
    print(f"boss region {x1 - x0}x{y1 - y0} at ({x0},{y0}) "
          f"from {pick['area']} animated px")

    sprite = frames[0].crop((x0, y0, x1, y1)).convert("RGBA")
    mask = changed.crop((x0, y0, x1, y1))
    # Key the static background: keep animated pixels, plus pixels close to the
    # animated region that differ from the dominant border colour.
    border = []
    w, h = sprite.size
    for x in range(w):
        border.append(sprite.getpixel((x, 0))[:3])
        border.append(sprite.getpixel((x, h - 1))[:3])
    for y in range(h):
        border.append(sprite.getpixel((0, y))[:3])
        border.append(sprite.getpixel((w - 1, y))[:3])
    from collections import Counter
    bg = Counter(border).most_common(1)[0][0]
    print("background key:", bg)

    mpx = mask.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opx = out.load()
    spx = sprite.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _ = spx[x, y]
            animated = mpx[x, y] > 0
            far = (abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])) > 60
            if animated or far:
                opx[x, y] = (r, g, b, 255)
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out)
    filled = sum(1 for p in out.getdata() if p[3])
    print(f"wrote {args.out} {out.size} filled={filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
