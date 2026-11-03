#!/usr/bin/env python3
"""Bake the generic town NPC used by species $96 (area 8).

Species $96 is reused by both the Holothurion boss and a town NPC. The boss
art lives in the separate `96_boss` variant; this tool keeps the NPC sheet
entry from showing the boss or the old Firebrand-like probe capture.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs/sprites/SNES - Demon's Crest - Miscellaneous - NPCs.png"
GEN = ROOT / "assets/generated"


def main() -> int:
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.load()
    # The first NPC is the top-left town character.
    x0, y0, x1, y1 = 0, 0, min(w, 45), min(h, 52)
    mask = bytearray(w * h)
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y]
            # NPCs.png has a white sheet background, not the usual black.
            if not (r > 235 and g > 235 and b > 235):
                mask[y * w + x] = 1
    seen = bytearray(w * h)
    best = None
    for y in range(y0, y1):
        for x in range(x0, x1):
            if seen[y * w + x] or not mask[y * w + x]:
                continue
            q = deque([(x, y)])
            seen[y * w + x] = 1
            pts = []
            while q:
                cx, cy = q.popleft()
                pts.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] \
                            and mask[ny * w + nx]:
                        seen[ny * w + nx] = 1
                        q.append((nx, ny))
            if best is None or len(pts) > len(best):
                best = pts
    if not best:
        raise SystemExit("bake_npc96: no NPC pixels")
    xs = [x for x, _ in best]
    ys = [y for _, y in best]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    out = Image.new("RGBA", (bx1 - bx0, by1 - by0), (0, 0, 0, 0))
    op = out.load()
    for x, y in best:
        r, g, b = px[x, y]
        op[x - bx0, y - by0] = (r, g, b, 255)
    tex = "enemy_96_0.png"
    out.save(GEN / tex)

    path = GEN / "species_anim.json"
    anim = json.loads(path.read_text()) if path.is_file() else {"species": {}}
    anim.setdefault("species", {})["96"] = {
        "species": 0x96,
        "frames": [{
            "texture": tex,
            "anchor_x": out.width // 2,
            "anchor_y": out.height,
            "duration": 8,
            "width": out.width,
            "height": out.height,
        }],
        "default": 0,
        "source": "docs/sprites NPCs.png (top-left town NPC)",
    }
    path.write_text(json.dumps(anim, indent=1))
    print(f"NPC 96: {out.size} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
