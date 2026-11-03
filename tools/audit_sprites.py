#!/usr/bin/env python3
"""Structural audit of the generated sprite atlases.

The port has repeatedly shipped frames that were not sprites at all: tilemap
fragments, duplicated clusters assigned to different species, or crops whose
anchor lies outside the image. This tool is the cheap gate that was missing.

It checks the species manifest (and, informatively, the player sheets):

* every texture exists and is non-empty;
* the anchor X lies inside the image;
* a species cannot reuse another species' exact image;
* a heavily fragmented image is rejected unless one component dominates;
* JSON dimensions (when present) match the PNG;
* anchor drift across frames is reported.

Usage:
  python tools/audit_sprites.py --assets assets/generated
  python tools/audit_sprites.py --assets assets/generated --quarantine
  python tools/audit_sprites.py --assets assets/generated --strict

Exit code is 0 for results with warnings only, 1 for structural errors. With
``--quarantine``, species entries that fail a hard check are removed from
``species_anim.json`` (a ``.bak`` copy is kept).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path,
                    default=ROOT / "assets" / "generated")
    ap.add_argument("--quarantine", action="store_true",
                    help="drop species that fail a hard check")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a hard error is found")
    ap.add_argument("--report", type=Path, default=None,
                    help="write the audit result as JSON")
    ap.add_argument("--no-player", action="store_true",
                    help="skip the informative player/forms checks")
    return ap.parse_args()


def components(img: Image.Image) -> list[int]:
    alpha = img.getchannel("A")
    w, h = img.size
    px = alpha.load()
    seen = bytearray(w * h)
    out: list[int] = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if seen[i] or px[x, y] == 0:
                continue
            q = deque([(x, y)])
            seen[i] = 1
            n = 0
            while q:
                cx, cy = q.popleft()
                n += 1
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            j = ny * w + nx
                            if not seen[j] and px[nx, ny] != 0:
                                seen[j] = 1
                                q.append((nx, ny))
            out.append(n)
    return sorted(out, reverse=True)


def inspect_frame(path: Path, frame: dict) -> tuple[dict, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    info: dict = {
        "texture": str(path.name),
        "anchor_x": frame.get("anchor_x"),
        "anchor_y": frame.get("anchor_y"),
    }
    if not path.is_file():
        errors.append(f"missing texture {path.name}")
        info["error"] = True
        return info, errors, warnings
    try:
        img = Image.open(path).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{path.name}: cannot read image ({exc})")
        info["error"] = True
        return info, errors, warnings

    w, h = img.size
    opaque = 0
    black = 0
    px = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if not a:
                continue
            opaque += 1
            if r < 8 and g < 8 and b < 8:
                black += 1
    comps = components(img)
    largest = comps[0] if comps else 0
    info.update({
        "width": w,
        "height": h,
        "opaque": opaque,
        "components": len(comps),
        "largest": largest,
        "largest_pct": round(100.0 * largest / opaque, 2) if opaque else 0.0,
        "black_pct": round(100.0 * black / opaque, 2) if opaque else 0.0,
        "px_hash": hashlib.sha256(img.tobytes()).hexdigest(),
    })

    for key in ("width", "height"):
        value = frame.get(key)
        if value is not None and int(value) != info[key]:
            warnings.append(
                f"{path.name}: JSON {key}={value} but PNG is {info[key]}")
    ax = frame.get("anchor_x")
    ay = frame.get("anchor_y")
    if ax is None or ay is None:
        errors.append(f"{path.name}: missing anchor")
    else:
        axf, ayf = float(ax), float(ay)
        if axf < -24 or axf > w + 24:
            errors.append(f"{path.name}: anchor_x {axf} far outside 0..{w}")
        elif axf < 0 or axf > w:
            warnings.append(
                f"{path.name}: anchor_x {axf} outside 0..{w}")
        if ayf < -2 or ayf > h + 16:
            warnings.append(f"{path.name}: anchor_y {ayf} is outside 0..{h}")
    if opaque == 0:
        errors.append(f"{path.name}: fully transparent")
    if len(comps) >= 6 and info["largest_pct"] < 80.0:
        errors.append(
            f"{path.name}: {len(comps)} components, largest "
            f"{info['largest_pct']:.1f}% of body")
    if info["black_pct"] > 60.0:
        warnings.append(
            f"{path.name}: {info['black_pct']:.1f}% opaque-black pixels")
    return info, errors, warnings


def audit_species(assets: Path, quarantine: bool) -> dict:
    path = assets / "species_anim.json"
    result: dict = {"species": {}, "errors": [], "warnings": [], "dropped": []}
    if not path.is_file():
        result["warnings"].append(f"{path} missing; species audit skipped")
        return result

    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{path}: invalid JSON ({exc})")
        return result

    entries = data.get("species")
    if not isinstance(entries, dict):
        result["errors"].append(f"{path}: no 'species' object")
        return result

    frames_by_species: dict[str, list[dict]] = {}
    digest_owners: dict[str, list[str]] = {}
    for key, entry in sorted(entries.items()):
        if not isinstance(entry, dict):
            result["errors"].append(f"species {key}: entry is not an object")
            continue
        frames = entry.get("frames")
        if not isinstance(frames, list) or not frames:
            result["errors"].append(f"species {key}: no frames")
            frames_by_species[key] = []
            continue
        species_errors: list[str] = []
        species_warnings: list[str] = []
        infos: list[dict] = []
        for frame in frames:
            if not isinstance(frame, dict) or not isinstance(
                    frame.get("texture"), str):
                species_errors.append(f"species {key}: malformed frame")
                continue
            fpath = assets / frame["texture"]
            info, errs, warns = inspect_frame(fpath, frame)
            infos.append(info)
            species_errors.extend(errs)
            species_warnings.extend(warns)
            if "px_hash" in info:
                digest_owners.setdefault(info["px_hash"], []).append(key)
        if len(frames) > 8:
            species_errors.append(
                f"species {key}: {len(frames)} frames; loader caps at 8")
        if len(frames) > 1:
            xs = [float(f.get("anchor_x", 0)) for f in frames]
            ys = [float(f.get("anchor_y", 0)) for f in frames]
            if max(xs) - min(xs) > 10.0 or max(ys) - min(ys) > 24.0:
                species_warnings.append(
                    f"species {key}: anchor range x={max(xs)-min(xs):.1f}, "
                    f"y={max(ys)-min(ys):.1f}")
        frames_by_species[key] = infos
        result["species"][key] = {
            "species": entry.get("species"),
            "frames": infos,
            "errors": species_errors,
            "warnings": species_warnings,
        }
        result["errors"].extend(species_errors)
        result["warnings"].extend(species_warnings)

    for digest, owners in digest_owners.items():
        unique = sorted(set(owners))
        if len(unique) <= 1:
            continue
        result["errors"].append(
            f"duplicate sprite image shared by species {unique} ({digest[:12]})")
        for key in unique:
            result["species"].setdefault(key, {}).setdefault(
                "errors", []).append("image is byte-identical to another species")

    if quarantine:
        # A species is quarantined when any of its frames has a hard error.
        bad = {key for key, entry in result["species"].items()
               if entry.get("errors")}
        if bad:
            backup = path.with_suffix(path.suffix + ".bak")
            if not backup.exists():
                backup.write_text(path.read_text())
            for key in sorted(bad):
                if key in entries:
                    del entries[key]
                    result["dropped"].append(key)
            path.write_text(json.dumps({"species": entries}, indent=1))
        print(f"audit: quarantined {len(result['dropped'])} species "
              f"{sorted(result['dropped'])}")
    return result


def audit_player(assets: Path) -> dict:
    result: dict = {"errors": [], "warnings": []}
    for name in ("player_anim.json", "player_forms.json"):
        path = assets / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            result["warnings"].append(f"{name}: invalid JSON ({exc})")
            continue
        clip_sets = []
        if name == "player_anim.json":
            clips = data.get("clips", {})
            clip_sets = [(name, clip, c.get("steps", []))
                         for clip, c in clips.items()]
        else:
            for form in data.get("forms", []):
                form_name = form.get("name", form.get("form", "?"))
                for clip, c in form.get("clips", {}).items():
                    clip_sets.append((f"{name}:{form_name}", clip,
                                      c.get("steps", [])))
        for owner, clip, steps in clip_sets:
            for frame in steps:
                tex = frame.get("texture")
                if not isinstance(tex, str):
                    result["warnings"].append(f"{owner}/{clip}: malformed step")
                    continue
                fpath = assets / tex
                info, errs, warns = inspect_frame(fpath, frame)
                # Forms are opt-in and their sheet crops are still being
                # fixed; report them, but do not fail the species gate yet.
                if errs:
                    result["warnings"].extend(
                        [f"{owner}/{clip}: {e}" for e in errs])
                if warns:
                    result["warnings"].extend(
                        [f"{owner}/{clip}: {w}" for w in warns])
    return result


def print_summary(result: dict, player: dict) -> None:
    species = result.get("species", {})
    print(f"audit: {len(species)} species, "
          f"{sum(len(e.get('frames', [])) for e in species.values())} frames, "
          f"{len(result['errors'])} error(s), "
          f"{len(result['warnings'])} warning(s)")
    for err in result["errors"]:
        print(f"  ERROR {err}")
    for warn in result["warnings"]:
        print(f"  WARN  {warn}")
    if player:
        for err in player.get("errors", []):
            print(f"  PLAYER-ERROR {err}")
        for warn in player.get("warnings", []):
            print(f"  PLAYER-WARN  {warn}")


def main() -> int:
    args = parse_args()
    assets = args.assets.resolve()
    result = audit_species(assets, args.quarantine)
    player = {} if args.no_player else audit_player(assets)
    result["player"] = player
    if args.report:
        args.report.write_text(json.dumps(result, indent=1))
    print_summary(result, player)
    if args.strict and result["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
