#!/usr/bin/env python3
"""Convert batch-probed save states into species-capture records.

`probe_saves_batch.py` writes one directory per save with `info.json`, `oam.bin`,
`cgram.bin`, `vram.bin`. This tool turns every live object of a probed save into
`extract_species.py` frame records (`s<species>/f<id>.json` + `.vram.bin`) and a
`manifest.json`, so real gameplay sprites can be baked like injected captures.

Usage:
  python tools/dc_extract/probe_to_species.py \
      --probe-root <...>/oracle_probe --saves 0a,2a,5a,6a,7a --out captures/probed
  python tools/dc_extract/extract_species.py --dump captures/probed --out assets/generated
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe-root", type=Path, required=True)
    ap.add_argument("--saves", required=True,
                    help="comma separated suffixes, e.g. 0a,2a,5a")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    counts: dict[int, int] = {}

    for tag in [s.strip() for s in args.saves.split(",") if s.strip()]:
        src = args.probe_root / f"save{tag}"
        info_path = src / "info.json"
        if not info_path.is_file():
            print(f"skip save{tag}: no info.json")
            continue
        info = json.loads(info_path.read_text())
        oam = (src / "oam.bin").read_bytes()
        cgram = (src / "cgram.bin").read_bytes()
        vram = (src / "vram.bin").read_bytes()
        ppu = json.loads((src / "ppu.json").read_text())
        body = ppu.get("ppu", ppu)
        frame = 0
        for i, ent in enumerate(info.get("species", [])):
            species = int(ent["species"])
            key = f"{species:02x}"
            fid = 9000 + i
            d = args.out / f"s{species:02x}"
            d.mkdir(exist_ok=True)
            state = {
                "frame": fid,
                "ppu": body,
                "cgram": cgram.hex(),
                "oam": oam.hex(),
                "object_world": [ent["x"], ent["y"]],
                "player_world": info["player"],
            }
            (d / f"f{fid:06d}.json").write_text(json.dumps(state))
            shutil.copyfile(src / "vram.bin", d / f"f{fid:06d}.vram.bin")
            entry = manifest.setdefault(
                key, {"species": species, "frames": [],
                      "offset": [0.0, 0.0],
                      "player": info["player"]})
            entry["frames"].append(fid)
            counts[species] = counts.get(species, 0) + 1
            print(f"save{tag}: species {species:02X} object {i} -> f{fid}")

    if not manifest:
        print("no species found in the selected probes")
        return 1
    (args.out / "manifest.json").write_text(json.dumps({
        "save": "batch-probed save states",
        "rom": "(see probe)"
        if False else "batch",
        "species": manifest,
    }, indent=1))
    print("species counts:",
          {f"{k:02x}": v for k, v in sorted(counts.items())})
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
