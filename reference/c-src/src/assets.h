#ifndef DC_ASSETS_H
#define DC_ASSETS_H

#include <stdbool.h>
#include <stdint.h>
#include "anim.h"
#include "raylib.h"

#define DC_BG_PALETTES 8
#define DC_OBJ_PALETTES 8
#define DC_CAMPAIGN_AREAS 128
#define DC_SPECIES_MAX 64
/* The Hippogriff needs 9 ROM poses plus his statue. */
#define DC_SPECIES_FRAMES 10

typedef struct SpeciesFrame {
    Texture2D texture;
    Texture2D flipped;  /* pre-baked mirror: negative source rects are unreliable
                         * in raylib, so the flip is baked at load time. */
    int anchor_x;       /* whole pixels: fractional anchors truncated when drawn */
    int anchor_y;
    int duration;       /* game frames this pose is shown */
} SpeciesFrame;

#define DC_ENDING_VARIANTS 4
#define DC_ENDING_MAX_LINES 12

typedef struct EndingData {
    char title[DC_ENDING_VARIANTS][16];
    char lines[DC_ENDING_VARIANTS][DC_ENDING_MAX_LINES][52];
    int line_count[DC_ENDING_VARIANTS];
    int epilogue[DC_ENDING_VARIANTS]; /* text_strings index or -1 */
    bool loaded;
} EndingData;

/* Animation clips per object state (review P1): the JSON can map an object's
 * state byte to a list of frames instead of every species needing an `if` in
 * the renderer. */
#define DC_SPECIES_STATES 16
#define DC_STATE_FRAMES 8

typedef struct StateClip {
    int count;
    int frames[DC_STATE_FRAMES];
} StateClip;

/* Somulo is drawn the way the hardware draws him: a torso, a leg sprite and a
 * head+neck sprite that is swapped per state. `parts` in species_anim.json
 * names the part textures, their offset from the object's feet anchor, and
 * which parts each object state composes. A species without that block keeps
 * the single-image frames above. */
#define DC_SPECIES_PARTS 8

typedef struct SpeciesPart {
    Texture2D texture;
    Texture2D flipped;
    int dx; /* from the object's feet anchor to the part's left edge */
    int dy; /* from the object's feet anchor to the part's top edge */
} SpeciesPart;

typedef struct SpeciesPartState {
    bool present;
    bool legs;  /* draw the "legs" part */
    int body;   /* part index, -1 for none */
    int head;   /* part index, -1 for none */
} SpeciesPartState;

typedef struct SpeciesParts {
    bool enabled;
    int count;
    char names[DC_SPECIES_PARTS][24];
    SpeciesPart parts[DC_SPECIES_PARTS];
    SpeciesPartState states[DC_SPECIES_STATES];
} SpeciesParts;

typedef struct SpeciesSheet {
    int species;
    int flags;        /* object flags selecting a palette/encounter variant */
    int frame_count;
    int duration;
    bool has_states;
    StateClip states[DC_SPECIES_STATES];
    int hurt_frame;   /* pose while hit_flash > 0 (review P1) */
    bool has_hurt;
    int default_frame; /* pose for states with no clip */
    bool has_default;
    SpeciesParts parts;
    SpeciesFrame frames[DC_SPECIES_FRAMES];
} SpeciesSheet;

typedef struct Assets {
    Texture2D bg_pal[DC_BG_PALETTES];
    Texture2D bg_area[DC_BG_PALETTES];
    Texture2D bg2_area[DC_BG_PALETTES];
    /* Optional wide backdrop (sky/trees) drawn behind the tile layers, for rooms
     * whose BG2 was never captured - the cemetery and friends. */
    Texture2D backdrop;
    int backdrop_w;
    int backdrop_h;
    bool bg_area_ready;
    int bg_area_id;
    char asset_dir[1024];
    Texture2D obj_pal[DC_OBJ_PALETTES];
    Texture2D player;
    Texture2D player_flipped;
    Texture2D item;
    Texture2D heart;
    Texture2D enemy[2];
    int enemy_frames;
    SpeciesSheet species[DC_SPECIES_MAX];
    int species_count;
    /* Optional per-species boss variants (same species id, different art). */
    SpeciesSheet boss_sheets[DC_SPECIES_MAX];
    int boss_sheet_count;
    EndingData endings;
    uint8_t room_kind[DC_CAMPAIGN_AREAS]; /* 0 unknown, 1 playable, 2 partial, 3 empty */
    int stage_entries[80]; /* rooms no other room targets (stage select) */
    int stage_count;
    Texture2D hud_bar;
    Texture2D hud_slots;
    Texture2D font;
    Texture2D world_map; /* 1024x1024 Mode 7 map (optional) */
    /* Map names resolved from the level saves (room_names.json), by area id;
     * empty when unknown. */
    char room_names[113][40];
    char room_levels[113][8];
    /* Overworld stage markers (map_markers.json), in map-space * 4 pixels. */
    Texture2D boss_fireball[4];
    int boss_fireball_count;
    Texture2D boss_flame[8];
    int boss_flame_count;
    int map_marker_count;
    float map_markers[64][2]; /* BG3 ASCII font mask (font.png + font.json) */
    PlayerAnim player_anim;
    PlayerAnim player_forms[6];
    int player_form_count;
    ProjectileAnim projectile_anim;
    bool ready;
} Assets;

bool Assets_Load(Assets *assets, const char *dir);
void Assets_Unload(Assets *assets);
void Assets_LoadAreaBg(Assets *assets, int area);
Texture2D Assets_AreaBg(const Assets *assets, int area, int pal);
Texture2D Assets_AreaBg2(const Assets *assets, int pal);
bool Assets_HasAreaBg2(const Assets *assets);
const SpeciesSheet *Assets_SpeciesSheet(const Assets *assets, int species);
const SpeciesSheet *Assets_BossSheet(const Assets *assets, int species,
                                     int flags);
/* Index of a named part inside a sheet's `parts` block, -1 when absent. */
int Species_PartIndex(const SpeciesParts *parts, const char *name);
/* Per-crest-form player animation; falls back to player_anim. */
const PlayerAnim *Assets_PlayerAnimForForm(const Assets *assets, int form);
int Assets_RoomKind(const Assets *assets, int area);

#endif
