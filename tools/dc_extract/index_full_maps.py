#!/usr/bin/env python3
"""Index the community full-stage maps in docs/FullMaps/images.

Each map is a 1:1 stitch of the original room's screens, so a map's pixel size
gives the room's true screen grid: ceil(width/256) x ceil(height/224). The index
is used to sanity-check (and eventually rebuild) the extracted room sizes.

Usage:
  python tools/dc_extract/index_full_maps.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MAPS = ROOT / "docs" / "FullMaps" / "images"
OUT = ROOT / "docs" / "FullMaps" / "index.json"

GROUPS = {
    "murkland": "Level I (Murkland)",
    "ruined-city": "Level II (Ruined City)",
    "dark-forest": "Level III (Dark Forest)",
    "towers-of-doom": "Level IV (Towers of Doom)",
    "mountains": "Level V (Mountains)",
    "poseidonia": "Level VI (Poseidonia)",
    "phalanxs-fortress": "Final (Phalanx's Fortress)",
    "demons-hideout": "Secret (Demon's Hideout)",
    "trio-the-pagos": "Minigame shop",
}


def group_of(name: str) -> str:
    for key, label in GROUPS.items():
        if key in name:
            return label
    return "Other"


def main() -> int:
    entries = []
    for path in sorted(MAPS.glob("*.webp")):
        with Image.open(path) as im:
            width, height = im.size
        entries.append({
            "file": path.name,
            "name": path.stem.replace("demons-crest-", "")
                             .replace("-snes-map", ""),
            "group": group_of(path.name),
            "width": width,
            "height": height,
            "screens": [math.ceil(width / 256), math.ceil(height / 224)],
        })
    index = {"maps": entries, "count": len(entries)}
    OUT.write_text(json.dumps(index, indent=1))
    print(f"indexed {len(entries)} maps -> {OUT}")
    for group in dict.fromkeys(e["group"] for e in entries):
        rows = [e for e in entries if e["group"] == group]
        print(f"  {group}: {len(rows)} maps, "
              f"screens {sorted({tuple(r['screens']) for r in rows})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
