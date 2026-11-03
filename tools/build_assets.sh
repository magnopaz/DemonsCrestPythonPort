#!/usr/bin/env bash
# Rebuild every ROM-derived asset from scratch.
#
# Reproduces the documented asset state from:
#   - the player's own ROM (required)
#   - captures/graveyard/stage_600.*   (BG1/OBJ atlases, player idle, all 113 rooms)
#   - captures/anim/                   (player/fireball/HUD clips)
#   - captures/save*/ , captures/nb/*  (per-area BG2 backdrops)
#
# Post-extraction patches that cannot come from the ROM tables are applied
# afterwards, in order, and are idempotent:
#   apply_boss_table.py   -> boss objects from tools/check_bosses.py's table
#   apply_door_table.py   -> save-observed doors (if present)
#
# Usage:
#   tools/build_assets.sh [--rom PATH] [--out DIR] [--no-captures]
#
# Everything it writes is git-ignored. Re-running it never needs a recomp
# capture as long as captures/ is populated; delete captures/ to force a full
# oracle pass.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Python with Pillow/numpy if the caller has one (this repo's .venv does).
PY="${PYTHON:-python3}"
# Note: the ROM file name contains an apostrophe and parentheses, which bash
# mis-parses inside a `${VAR:-default}` expansion. Keep it in its own variable.
DEFAULT_ROM="$ROOT/../roms/Demon's Crest (USA).sfc"
ROM="${ROM:-$DEFAULT_ROM}"
OUT="${OUT:-$ROOT/assets/generated}"
DUMP="${DUMP:-$ROOT/captures/graveyard}"
PREFIX="${PREFIX:-stage_600}"
SKIP_CAPTURES=0
SKIP_AUDIO=0

while [ $# -gt 0 ]; do
  case "$1" in
    --rom) ROM="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --no-captures) SKIP_CAPTURES=1; shift ;;
    --no-audio) SKIP_AUDIO=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$ROOT"
need() { [ -e "$1" ] || { echo "build_assets: missing $1" >&2; exit 1; }; }
need "$ROM"
need "$DUMP/$PREFIX.vram.bin"

echo "== 1/6 rooms, atlases, campaign =="
"$PY" tools/dc_extract/extract.py --rom "$ROM" --dump "$DUMP" --prefix "$PREFIX" \
    --area 1 --screens 9,10 --full-room --out "$OUT"

echo "== 2/6 player / fireball / HUD animations =="
if [ -d "$ROOT/captures/anim" ]; then
  "$PY" tools/dc_extract/extract_anim.py --dump "$ROOT/captures/anim" --out "$OUT" --clean
else
  echo "   captures/anim missing; animations fall back to player_idle.png"
fi

echo "== 3/6 font + endings =="
# The pause subscreen draws its labels with the BG3 ASCII font (tile index ==
# ASCII code), so `captures/menu` is the authoritative source. The graveyard
# frame also carries the HUD digits but not the whole printable set.
if [ -d "$ROOT/captures/menu" ]; then
  "$PY" tools/dc_extract/extract_font.py --dump "$ROOT/captures/menu" --out "$OUT"
elif [ -d "$ROOT/captures/font" ]; then
  "$PY" tools/dc_extract/extract_font.py --dump "$ROOT/captures/font" --out "$OUT"
else
  echo "   no menu capture; run tools/oracle/capture_menu.py for the BG3 font"
fi
"$PY" tools/dc_extract/build_endings.py --out "$OUT"

# Mode 7 overworld: bake from a capture of the map screen. `build_world_map.py`
# wants the frame number, so take it from the capture's own filename.
if [ -d "$ROOT/captures/map11" ]; then
  frame_file=$(ls "$ROOT"/captures/map11/f*.json 2>/dev/null | head -1)
  if [ -n "$frame_file" ]; then
    frame_num=$(basename "$frame_file" .json)
    frame_num=${frame_num#f}
    frame_num=$((10#$frame_num))
    "$PY" tools/dc_extract/build_world_map.py --capture "$ROOT/captures/map11" \
        --frame "$frame_num" --out "$OUT/world_map.png"
  fi
else
  echo "   captures/map11 missing; the overworld falls back to the procedural map"
fi

echo "== 4/7 boss objects from the check table =="
"$PY" tools/dc_extract/apply_boss_table.py --rooms "$OUT"

# Boss gates: $81:97DA stores the next room byte, except for the special
# markers >= $F0.  Area 3 stores $F0, the "back to the map" marker, which the
# extractor drops; this re-applies the verified destinations (area 3 -> 94).
echo "== 4b/7 boss-gate table =="
"$PY" tools/dc_extract/apply_gate_table.py --rom "$ROM" --rooms "$OUT"

# Somulo's own art: the walk cycle comes from the reference GIF kept in
# docs/reference, and its anchors are measured from the art's feet (the baker's
# own anchor assumes screen-space numbers that drift when the camera moves).
if [ -f docs/reference/somulo_walk.gif ]; then
  echo "== bake Somulo (species 33) from the reference GIF =="
  "$PY" tools/dc_extract/bake_somulo_gif.py \
    --gif docs/reference/somulo_walk.gif --out "$OUT"
  "$PY" tools/dc_extract/fix_species_anchor.py --species 33 \
    --feet-band 0:0.4 --assets "$OUT"
  # Body / legs / head parts, composed at runtime for the poses the walk cycle
  # does not have (head lowered, roar, fainted).
  echo "== Somulo body/legs/head parts =="
  "$PY" tools/dc_extract/bake_somulo_parts.py --assets "$OUT"
fi

# Ground props (urns, crest pickups) sit on their object's centre; the CHR-tile
# bake wrote anchor_y 27/26 for 16 px art and they floated in mid-air.
for sp in 57 2d 2e 49; do
  "$PY" tools/dc_extract/fix_species_anchor.py --species "$sp" \
    --center --assets "$OUT"
done

echo "== 5/7 room names (needs the save->area mapping) =="
if [ -f "$ROOT/captures/save_to_area.json" ]; then
  "$PY" tools/dc_extract/build_room_names.py \
      --areas "$ROOT/captures/save_to_area.json" --out "$OUT/room_names.json"
else
  echo "   captures/save_to_area.json missing; the banner falls back to STAGE <n>"
fi

echo "== 6/7 talkable city NPCs =="
"$PY" tools/dc_extract/apply_npc_table.py --rooms "$OUT"

echo "== 7/7 save-observed doors (optional) =="
if [ -f tools/dc_extract/apply_door_table.py ]; then
  "$PY" tools/dc_extract/apply_door_table.py --rooms "$OUT"
else
  echo "   apply_door_table.py not present yet; ROM transitions only"
fi

# Area 0's atlases must come from the guest's own VRAM: the ROM-segment bake
# leaves palette-7 tile 15 empty, and that one tile is referenced 674 times in
# the colosseum's BG1 (it was the solid black rectangles in the wall). Any dump
# of the room will do; the colosseum save state is the one we have.
if [ -d captures/rooms/somulo_fight_starts ]; then
  echo "== rebake area 0 atlases from the colosseum capture =="
  "$PY" tools/dc_extract/bake_bg_atlas_from_capture.py \
    --dump captures/rooms/somulo_fight_starts --area 0 --pals 4,5,6,7 \
    --out "$OUT"
fi

# Last writer: make BG1 agree with each room's world box, otherwise the whole
# scene is drawn at a different y than collision and entities look airborne.
"$PY" tools/dc_extract/normalize_rooms.py --rooms "$OUT"

# ROM music. The tracks are captured from the oracle's own DSP output (a bare
# .spc does not survive this game's driver - see docs/AUDIO_PLAN.md) and cut to
# their measured loop period. Captures are reused when present; without the
# oracle the game keeps its procedural stand-ins, so this step never blocks a
# from-scratch asset build on a machine without the recomp checkout.
if [ "$SKIP_AUDIO" -eq 0 ] && [ -f tools/audio/music_tracks.json ]; then
  RECOMP="${RECOMP_DIR:-$ROOT/../DemonsCrestSNESRecomp}"
  echo "== music (ROM audio via the oracle) =="
  if python3 tools/audio/make_music_asset.py --use-capture --outdir "$OUT/audio"; then
    :
  elif [ -d "$RECOMP/build-trace" ]; then
    "$PY" tools/audio/make_music_asset.py --recomp "$RECOMP" --outdir "$OUT/audio"
  else
    echo "   no captures/audio and no oracle; music stays procedural"
  fi
fi

if [ "$SKIP_CAPTURES" -eq 0 ]; then
  echo "== verify: room/BG2 coverage =="
  "$PY" - "$OUT" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
rooms = sorted(out.glob("room_area*.json"))
with_bg2 = 0
for path in rooms:
    doc = json.loads(path.read_text())
    bg2 = [b for b in doc["bg"] if b["name"] == "bg2"]
    if bg2 and any(t & 0x3FF for t in bg2[0]["tilemap"]):
        with_bg2 += 1
print(f"rooms={len(rooms)} with_non_empty_bg2={with_bg2}")
PY
fi

echo "build_assets: done -> $OUT"
