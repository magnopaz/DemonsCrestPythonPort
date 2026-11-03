#include "assets.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

static bool LoadOne(Texture2D *out, const char *dir, const char *name) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, name);
    *out = LoadTexture(path);
    if (!IsTextureValid(*out)) {
        fprintf(stderr, "assets: failed to load %s\n", path);
        return false;
    }
    SetTextureFilter(*out, TEXTURE_FILTER_POINT);
    return true;
}

static int JsonNum(const cJSON *obj, const char *key, int fallback) {
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    return cJSON_IsNumber(item) ? item->valueint : fallback;
}

static double JsonDouble(const cJSON *obj, const char *key, double fallback) {
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    return cJSON_IsNumber(item) ? item->valuedouble : fallback;
}

/* Load a part texture plus its pre-baked mirror, like the species frames. */
static bool LoadPartTexture(SpeciesPart *part, const char *dir,
                            const char *name) {
    if (!LoadOne(&part->texture, dir, name))
        return false;
    Image img = LoadImageFromTexture(part->texture);
    ImageFlipHorizontal(&img);
    part->flipped = LoadTextureFromImage(img);
    UnloadImage(img);
    if (IsTextureValid(part->flipped))
        SetTextureFilter(part->flipped, TEXTURE_FILTER_POINT);
    return true;
}

/* `parts`: body / legs / head textures with measured offsets from the feet
 * anchor, plus a per-state recipe ("body": name, "legs": bool, "head": name).
 * Only Somulo has one; everything else keeps the single-image frames. */
static void LoadSpeciesParts(SpeciesSheet *sheet, const cJSON *entry,
                             const char *dir) {
    const cJSON *parts = cJSON_GetObjectItemCaseSensitive(entry, "parts");
    if (!cJSON_IsObject(parts))
        return;
    SpeciesParts *dst = &sheet->parts;
    for (int i = 0; i < DC_SPECIES_STATES; i++) {
        dst->states[i].body = -1;
        dst->states[i].head = -1;
        dst->states[i].legs = true;
    }
    const cJSON *part = NULL;
    cJSON_ArrayForEach(part, parts) {
        if (!part->string || strcmp(part->string, "states") == 0 ||
            strcmp(part->string, "source") == 0)
            continue;
        if (!cJSON_IsObject(part) || dst->count >= DC_SPECIES_PARTS)
            continue;
        const cJSON *tex = cJSON_GetObjectItemCaseSensitive(part, "texture");
        if (!cJSON_IsString(tex))
            continue;
        SpeciesPart *slot = &dst->parts[dst->count];
        if (!LoadPartTexture(slot, dir, tex->valuestring))
            continue;
        slot->dx = JsonNum(part, "dx", 0);
        slot->dy = JsonNum(part, "dy", 0);
        snprintf(dst->names[dst->count], sizeof(dst->names[0]), "%s",
                 part->string);
        dst->count++;
    }
    const cJSON *states = cJSON_GetObjectItemCaseSensitive(parts, "states");
    if (cJSON_IsObject(states)) {
        const cJSON *st = NULL;
        cJSON_ArrayForEach(st, states) {
            if (!cJSON_IsObject(st))
                continue;
            int idx = atoi(st->string ? st->string : "-1");
            if (idx < 0 || idx >= DC_SPECIES_STATES)
                continue;
            SpeciesPartState *sel = &dst->states[idx];
            const cJSON *body = cJSON_GetObjectItemCaseSensitive(st, "body");
            const cJSON *head = cJSON_GetObjectItemCaseSensitive(st, "head");
            const cJSON *legs = cJSON_GetObjectItemCaseSensitive(st, "legs");
            sel->body = cJSON_IsString(body)
                            ? Species_PartIndex(dst, body->valuestring)
                            : Species_PartIndex(dst, "body");
            sel->head = cJSON_IsString(head)
                            ? Species_PartIndex(dst, head->valuestring)
                            : -1;
            sel->legs = cJSON_IsBool(legs) ? cJSON_IsTrue(legs) : true;
            sel->present = sel->body >= 0 || sel->head >= 0 || sel->legs;
        }
    }
    dst->enabled = dst->count > 0;
}

int Species_PartIndex(const SpeciesParts *parts, const char *name) {
    if (!parts || !name)
        return -1;
    for (int i = 0; i < parts->count; i++) {
        if (strcmp(parts->names[i], name) == 0)
            return i;
    }
    return -1;
}

/* `species_anim.json` is produced by tools/dc_extract/extract_species.py from
 * injected-object oracle captures: one entry per species with per-pose texture
 * and anchor. Missing file simply means "fall back to the shared enemy sheet". */
static void LoadSpeciesSheets(Assets *assets, const char *dir) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/species_anim.json", dir);
    if (!FileExists(path))
        return;
    char *text = LoadFileText(path);
    if (!text)
        return;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!root)
        return;
    const cJSON *species = cJSON_GetObjectItemCaseSensitive(root, "species");
    const cJSON *entry = NULL;
    cJSON_ArrayForEach(entry, species) {
        const cJSON *variant =
            cJSON_GetObjectItemCaseSensitive(entry, "variant");
        bool boss = cJSON_IsString(variant) &&
                    strcmp(variant->valuestring, "boss") == 0;
        int *count = boss ? &assets->boss_sheet_count : &assets->species_count;
        if (*count >= DC_SPECIES_MAX)
            continue;
        const cJSON *frames = cJSON_GetObjectItemCaseSensitive(entry, "frames");
        if (!cJSON_IsArray(frames))
            continue;
        SpeciesSheet *sheet = boss ? &assets->boss_sheets[*count]
                                   : &assets->species[*count];
        memset(sheet, 0, sizeof(*sheet));
        sheet->species = JsonNum(entry, "species", -1);
        sheet->flags = JsonNum(entry, "flags", 0);
        sheet->duration = 6;
        const cJSON *frame = NULL;
        cJSON_ArrayForEach(frame, frames) {
            if (sheet->frame_count >= DC_SPECIES_FRAMES)
                break;
            const cJSON *tex =
                cJSON_GetObjectItemCaseSensitive(frame, "texture");
            if (!cJSON_IsString(tex))
                continue;
            SpeciesFrame *slot = &sheet->frames[sheet->frame_count];
            if (!LoadOne(&slot->texture, dir, tex->valuestring))
                continue;
            {
                Image img = LoadImageFromTexture(slot->texture);
                ImageFlipHorizontal(&img);
                slot->flipped = LoadTextureFromImage(img);
                UnloadImage(img);
                if (IsTextureValid(slot->flipped))
                    SetTextureFilter(slot->flipped, TEXTURE_FILTER_POINT);
            }
            slot->anchor_x = (int)(JsonDouble(frame, "anchor_x", 0.0) + 0.5);
            slot->anchor_y = (int)(JsonDouble(frame, "anchor_y", 0.0) + 0.5);
            slot->duration = JsonNum(frame, "duration", 6);
            if (slot->duration < 1)
                slot->duration = 6;
            sheet->duration = slot->duration;
            sheet->frame_count++;
        }
        const cJSON *states =
            cJSON_GetObjectItemCaseSensitive(entry, "states");
        if (cJSON_IsObject(states)) {
            const cJSON *st = NULL;
            cJSON_ArrayForEach(st, states) {
                if (!cJSON_IsArray(st))
                    continue;
                int idx = atoi(st->string ? st->string : "-1");
                if (idx < 0 || idx >= DC_SPECIES_STATES)
                    continue;
                StateClip *clip = &sheet->states[idx];
                const cJSON *fv = NULL;
                cJSON_ArrayForEach(fv, st) {
                    if (clip->count >= DC_STATE_FRAMES || !cJSON_IsNumber(fv))
                        continue;
                    clip->frames[clip->count++] = fv->valueint;
                }
                if (clip->count > 0)
                    sheet->has_states = true;
            }
        }
        const cJSON *hurt = cJSON_GetObjectItemCaseSensitive(entry, "hurt");
        if (cJSON_IsNumber(hurt)) {
            sheet->hurt_frame = hurt->valueint;
            sheet->has_hurt = true;
        }
        const cJSON *def = cJSON_GetObjectItemCaseSensitive(entry, "default");
        if (cJSON_IsNumber(def)) {
            sheet->default_frame = def->valueint;
            sheet->has_default = true;
        }
        if (sheet->has_hurt &&
            (sheet->hurt_frame < 0 || sheet->hurt_frame >= sheet->frame_count))
            sheet->has_hurt = false;
        if (sheet->has_default &&
            (sheet->default_frame < 0 ||
             sheet->default_frame >= sheet->frame_count))
            sheet->has_default = false;
        LoadSpeciesParts(sheet, entry, dir);
        if (sheet->frame_count > 0)
            (*count)++;
        else
            memset(sheet, 0, sizeof(*sheet));
    }
    cJSON_Delete(root);
}

/* campaign.json carries the extractor's per-room classification. Empty rooms
 * (menus/padding grids, currently none) must never be entered as gameplay. */
static void LoadRoomKinds(Assets *assets, const char *dir) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/campaign.json", dir);
    if (!FileExists(path))
        return;
    char *text = LoadFileText(path);
    if (!text)
        return;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!root)
        return;
    const cJSON *entries = cJSON_GetObjectItemCaseSensitive(root, "stage_entries");
    if (cJSON_IsArray(entries)) {
        const cJSON *it = NULL;
        cJSON_ArrayForEach(it, entries) {
            if (cJSON_IsNumber(it) && assets->stage_count <
                                          (int)(sizeof(assets->stage_entries) /
                                                sizeof(assets->stage_entries[0])))
                assets->stage_entries[assets->stage_count++] = it->valueint;
        }
    }
    const cJSON *rooms = cJSON_GetObjectItemCaseSensitive(root, "rooms");
    const cJSON *entry = NULL;
    cJSON_ArrayForEach(entry, rooms) {
        if (!cJSON_IsObject(entry))
            continue;
        int area = atoi(entry->string ? entry->string : "-1");
        if (area < 0 || area >= DC_CAMPAIGN_AREAS)
            continue;
        const cJSON *kind = cJSON_GetObjectItemCaseSensitive(entry, "kind");
        if (!cJSON_IsString(kind))
            continue;
        if (strcmp(kind->valuestring, "playable") == 0)
            assets->room_kind[area] = 1;
        else if (strcmp(kind->valuestring, "partial") == 0)
            assets->room_kind[area] = 2;
        else if (strcmp(kind->valuestring, "empty") == 0)
            assets->room_kind[area] = 3;
    }
    cJSON_Delete(root);
}

int Assets_RoomKind(const Assets *assets, int area) {
    if (area < 0 || area >= DC_CAMPAIGN_AREAS)
        return 0;
    return assets->room_kind[area];
}

/* endings.json: the four campaign endings (narration transcribed from the
 * reference ending screenshots; epilogue indexes the ROM text script). */
static void LoadEndings(Assets *assets, const char *dir) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/endings.json", dir);
    if (!FileExists(path))
        return;
    char *text = LoadFileText(path);
    if (!text)
        return;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!root)
        return;
    static const char *kIds[DC_ENDING_VARIANTS] = {"bad", "normal", "good",
                                                  "true"};
    const cJSON *endings = cJSON_GetObjectItemCaseSensitive(root, "endings");
    for (int i = 0; i < DC_ENDING_VARIANTS; i++) {
        const cJSON *e = cJSON_GetObjectItemCaseSensitive(endings, kIds[i]);
        if (!cJSON_IsObject(e))
            continue;
        const cJSON *title = cJSON_GetObjectItemCaseSensitive(e, "title");
        if (cJSON_IsString(title))
            snprintf(assets->endings.title[i], sizeof(assets->endings.title[i]),
                     "%s", title->valuestring);
        const cJSON *lines = cJSON_GetObjectItemCaseSensitive(e, "lines");
        int n = 0;
        const cJSON *line = NULL;
        cJSON_ArrayForEach(line, lines) {
            if (!cJSON_IsString(line) || n >= DC_ENDING_MAX_LINES)
                break;
            snprintf(assets->endings.lines[i][n],
                     sizeof(assets->endings.lines[i][n]), "%s",
                     line->valuestring);
            n++;
        }
        assets->endings.line_count[i] = n;
        const cJSON *epi = cJSON_GetObjectItemCaseSensitive(e, "epilogue");
        assets->endings.epilogue[i] = cJSON_IsNumber(epi) ? epi->valueint : -1;
    }
    assets->endings.loaded = true;
    cJSON_Delete(root);
}

const PlayerAnim *Assets_PlayerAnimForForm(const Assets *assets, int form) {
    /* The form sheets are baked from connected pose components now, so their
     * clips are clean enough to be the default. DC_PLAYER_FORMS=0 keeps the
     * captured base animation as an escape hatch for comparison. */
    static int use_forms = -1;
    if (use_forms < 0) {
        const char *env = getenv("DC_PLAYER_FORMS");
        use_forms = (env && env[0] == '0' && env[1] == '\0') ? 0 : 1;
    }
    if (use_forms && form >= 0 && form < 6 &&
        assets->player_forms[form].ready)
        return &assets->player_forms[form];
    return &assets->player_anim;
}

const SpeciesSheet *Assets_SpeciesSheet(const Assets *assets, int species) {
    for (int i = 0; i < assets->species_count; i++) {
        if (assets->species[i].species == species)
            return &assets->species[i];
    }
    return NULL;
}

const SpeciesSheet *Assets_BossSheet(const Assets *assets, int species,
                                     int flags) {
    const SpeciesSheet *fallback = NULL;
    for (int i = 0; i < assets->boss_sheet_count; i++) {
        const SpeciesSheet *sheet = &assets->boss_sheets[i];
        if (sheet->species != species)
            continue;
        if (sheet->flags == flags)
            return sheet;
        if (sheet->flags == 0)
            fallback = sheet;
    }
    return fallback;
}

/* room_names.json: { "<area>": { "map": "...", "level": "III" } } */
static void LoadRoomNames(Assets *assets, const char *dir) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/room_names.json", dir);
    char *text = LoadFileText(path);
    if (!text)
        return;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!cJSON_IsObject(root))
        return;
    for (cJSON *item = root->child; item; item = item->next) {
        int area = atoi(item->string);
        if (area < 0 || area >= 113)
            continue;
        const cJSON *map = cJSON_GetObjectItemCaseSensitive(item, "map");
        const cJSON *level = cJSON_GetObjectItemCaseSensitive(item, "level");
        if (cJSON_IsString(map))
            snprintf(assets->room_names[area], sizeof(assets->room_names[area]),
                     "%s", map->valuestring);
        if (cJSON_IsString(level))
            snprintf(assets->room_levels[area],
                     sizeof(assets->room_levels[area]), "%s",
                     level->valuestring);
    }
    cJSON_Delete(root);
}

/* map_markers.json: {"all_positions": [[x, y], ...]} in map-space units;
 * the map texture is 1024x1024, so a marker sits at (x*4, y*4). */
static void LoadMapMarkers(Assets *assets, const char *dir) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/map_markers.json", dir);
    char *text = LoadFileText(path);
    if (!text)
        return;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!cJSON_IsObject(root))
        return;
    const cJSON *positions = cJSON_GetObjectItemCaseSensitive(root,
                                                             "all_positions");
    if (cJSON_IsArray(positions)) {
        const cJSON *item = NULL;
        cJSON_ArrayForEach(item, positions) {
            if (assets->map_marker_count >= 64)
                break;
            const cJSON *mx = cJSON_GetArrayItem(item, 0);
            const cJSON *my = cJSON_GetArrayItem(item, 1);
            if (!cJSON_IsNumber(mx) || !cJSON_IsNumber(my))
                continue;
            assets->map_markers[assets->map_marker_count][0] =
                (float)mx->valueint * 4.0f;
            assets->map_markers[assets->map_marker_count][1] =
                (float)my->valueint * 4.0f;
            assets->map_marker_count++;
        }
    }
    cJSON_Delete(root);
}

bool Assets_Load(Assets *assets, const char *dir) {
    memset(assets, 0, sizeof(*assets));
    for (int i = 0; i < DC_BG_PALETTES; i++) {
        char name[32];
        snprintf(name, sizeof(name), "bg_pal%d.png", i);
        if (!LoadOne(&assets->bg_pal[i], dir, name)) {
            Assets_Unload(assets);
            return false;
        }
    }
    snprintf(assets->asset_dir, sizeof(assets->asset_dir), "%s", dir);
    assets->bg_area_id = -1;
    for (int i = 0; i < DC_OBJ_PALETTES; i++) {
        char name[32];
        snprintf(name, sizeof(name), "obj_pal%d.png", i);
        if (!LoadOne(&assets->obj_pal[i], dir, name)) {
            Assets_Unload(assets);
            return false;
        }
    }
    if (!LoadOne(&assets->player, dir, "player_idle.png") ||
        !LoadOne(&assets->item, dir, "item_00.png")) {
        Assets_Unload(assets);
        return false;
    }
    Image player_image = LoadImageFromTexture(assets->player);
    ImageFlipHorizontal(&player_image);
    assets->player_flipped = LoadTextureFromImage(player_image);
    UnloadImage(player_image);
    if (!IsTextureValid(assets->player_flipped)) {
        Assets_Unload(assets);
        return false;
    }
    SetTextureFilter(assets->player_flipped, TEXTURE_FILTER_POINT);
    if (!LoadOne(&assets->heart, dir, "heart_00.png")) {
        fprintf(stderr, "assets: heart_00.png missing; using item sprite\n");
        assets->heart = assets->item;
    }
    if (LoadOne(&assets->enemy[0], dir, "enemy_00.png"))
        assets->enemy_frames = 1;
    if (LoadOne(&assets->enemy[1], dir, "enemy_01.png"))
        assets->enemy_frames = 2;
    if (!LoadOne(&assets->hud_bar, dir, "hud_bar.png") ||
        !LoadOne(&assets->hud_slots, dir, "hud_slots.png")) {
        fprintf(stderr, "assets: HUD elements missing; HUD disabled\n");
    }
    if (!LoadOne(&assets->font, dir, "font.png")) {
        fprintf(stderr, "assets: font.png missing; dialogue text disabled\n");
        memset(&assets->font, 0, sizeof(assets->font));
    }
    assets->player_form_count =
        Anim_LoadForms(assets->player_forms, 6, dir);
    if (assets->player_form_count > 0)
        printf("assets: %d crest-form player sheet(s)\n",
               assets->player_form_count);
    if (!Anim_Load(&assets->player_anim, dir)) {
        fprintf(stderr,
                "assets: player_anim.json missing; using the static idle sprite\n");
    }
    if (!ProjectileAnim_Load(&assets->projectile_anim, dir)) {
        fprintf(stderr,
                "assets: fireball_anim.json missing; projectiles render invisible\n");
    }
    LoadSpeciesSheets(assets, dir);
    LoadRoomKinds(assets, dir);
    LoadEndings(assets, dir);

    /* Somulo's fireball / firewall frames from the sprite sheet. */
    for (int i = 0; i < 4; i++) {
        char name[32];
        snprintf(name, sizeof(name), "boss_fireball_%d.png", i);
        char path[1200];
        snprintf(path, sizeof(path), "%s/%s", dir, name);
        if (!FileExists(path))
            break;
        if (LoadOne(&assets->boss_fireball[assets->boss_fireball_count], dir,
                    name))
            assets->boss_fireball_count++;
    }
    for (int i = 0; i < 8; i++) {
        char name[32];
        snprintf(name, sizeof(name), "boss_flame_%d.png", i);
        char path[1200];
        snprintf(path, sizeof(path), "%s/%s", dir, name);
        if (!FileExists(path))
            break;
        if (LoadOne(&assets->boss_flame[assets->boss_flame_count], dir, name))
            assets->boss_flame_count++;
    }

    LoadRoomNames(assets, dir);
    LoadMapMarkers(assets, dir);

    {
        char wm_path[1200];
        snprintf(wm_path, sizeof(wm_path), "%s/world_map.png", dir);
        if (FileExists(wm_path)) {
            assets->world_map = LoadTexture(wm_path);
            if (IsTextureValid(assets->world_map))
                SetTextureFilter(assets->world_map, TEXTURE_FILTER_POINT);
            else
                memset(&assets->world_map, 0, sizeof(assets->world_map));
        }
    }
    if (assets->species_count > 0)
        printf("assets: %d per-species sprite sheet(s)\n", assets->species_count);
    assets->ready = true;
    return true;
}

void Assets_Unload(Assets *assets) {
    for (int i = 0; i < DC_BG_PALETTES; i++) {
        if (IsTextureValid(assets->bg_pal[i]))
            UnloadTexture(assets->bg_pal[i]);
    }
    if (assets->bg_area_ready) {
        for (int p = 0; p < DC_BG_PALETTES; p++) {
            if (IsTextureValid(assets->bg_area[p]))
                UnloadTexture(assets->bg_area[p]);
        }
    }
    for (int i = 0; i < DC_OBJ_PALETTES; i++) {
        if (IsTextureValid(assets->obj_pal[i]))
            UnloadTexture(assets->obj_pal[i]);
    }
    if (IsTextureValid(assets->player))
        UnloadTexture(assets->player);
    if (IsTextureValid(assets->player_flipped))
        UnloadTexture(assets->player_flipped);
    if (IsTextureValid(assets->item))
        UnloadTexture(assets->item);
    if (IsTextureValid(assets->heart) &&
        assets->heart.id != assets->item.id)
        UnloadTexture(assets->heart);
    for (int i = 0; i < assets->enemy_frames; i++) {
        if (IsTextureValid(assets->enemy[i]))
            UnloadTexture(assets->enemy[i]);
    }
    for (int i = 0; i < assets->species_count; i++) {
        for (int f = 0; f < assets->species[i].frame_count; f++) {
            if (IsTextureValid(assets->species[i].frames[f].texture))
                UnloadTexture(assets->species[i].frames[f].texture);
            if (IsTextureValid(assets->species[i].frames[f].flipped))
                UnloadTexture(assets->species[i].frames[f].flipped);
        }
    }
    for (int i = 0; i < assets->boss_sheet_count; i++) {
        for (int f = 0; f < assets->boss_sheets[i].frame_count; f++) {
            if (IsTextureValid(assets->boss_sheets[i].frames[f].texture))
                UnloadTexture(assets->boss_sheets[i].frames[f].texture);
            if (IsTextureValid(assets->boss_sheets[i].frames[f].flipped))
                UnloadTexture(assets->boss_sheets[i].frames[f].flipped);
        }
    }
    if (IsTextureValid(assets->hud_bar))
        UnloadTexture(assets->hud_bar);
    if (IsTextureValid(assets->hud_slots))
        UnloadTexture(assets->hud_slots);
    if (IsTextureValid(assets->font))
        UnloadTexture(assets->font);
    if (IsTextureValid(assets->world_map))
        UnloadTexture(assets->world_map);
    for (int i = 0; i < assets->boss_fireball_count; i++)
        UnloadTexture(assets->boss_fireball[i]);
    for (int i = 0; i < assets->boss_flame_count; i++)
        UnloadTexture(assets->boss_flame[i]);
    Anim_UnloadForms(assets->player_forms, 6);
    Anim_Unload(&assets->player_anim);
    ProjectileAnim_Unload(&assets->projectile_anim);
    memset(assets, 0, sizeof(*assets));
}

bool Assets_HasAreaBg2(const Assets *assets) {
    for (int p = 0; p < DC_BG_PALETTES; p++)
        if (IsTextureValid(assets->bg2_area[p]))
            return true;
    return false;
}

Texture2D Assets_AreaBg2(const Assets *assets, int pal) {
    if (pal < 0 || pal >= DC_BG_PALETTES)
        return (Texture2D){0};
    return assets->bg2_area[pal];
}

Texture2D Assets_AreaBg(const Assets *assets, int area, int pal) {
    (void)area;
    if (pal < 0 || pal >= DC_BG_PALETTES)
        return assets->bg_pal[0];
    if (IsTextureValid(assets->bg_area[pal]))
        return assets->bg_area[pal];
    return assets->bg_pal[pal];
}

void Assets_LoadAreaBg(Assets *assets, int area) {
    if (area == assets->bg_area_id)
        return;
    if (assets->bg_area_ready) {
        for (int p = 0; p < DC_BG_PALETTES; p++) {
            if (IsTextureValid(assets->bg_area[p]))
                UnloadTexture(assets->bg_area[p]);
            memset(&assets->bg_area[p], 0, sizeof(assets->bg_area[p]));
            if (IsTextureValid(assets->bg2_area[p]))
                UnloadTexture(assets->bg2_area[p]);
            memset(&assets->bg2_area[p], 0, sizeof(assets->bg2_area[p]));
        }
        assets->bg_area_ready = false;
        if (IsTextureValid(assets->backdrop))
            UnloadTexture(assets->backdrop);
        memset(&assets->backdrop, 0, sizeof(assets->backdrop));
    }
    assets->bg_area_id = area;
    {
        char name[48];
        snprintf(name, sizeof(name), "bg_backdrop_area%d.png", area);
        if (LoadOne(&assets->backdrop, assets->asset_dir, name)) {
            assets->backdrop_w = assets->backdrop.width;
            assets->backdrop_h = assets->backdrop.height;
        }
    }
    bool any = false;
    for (int p = 0; p < DC_BG_PALETTES; p++) {
        char name[48];
        snprintf(name, sizeof(name), "bg_area%d_pal%d.png", area, p);
        char path[1200];
        snprintf(path, sizeof(path), "%s/%s", assets->asset_dir, name);
        if (!FileExists(path))
            continue;
        Texture2D tex = LoadTexture(path);
        if (!IsTextureValid(tex))
            continue;
        SetTextureFilter(tex, TEXTURE_FILTER_POINT);
        assets->bg_area[p] = tex;
        any = true;
    }
    /* BG2 atlases are baked from the captured frame's streamed CHR and live at
     * a different base than the ROM BG1 set, so they are loaded separately. */
    for (int p = 0; p < DC_BG_PALETTES; p++) {
        char name[48];
        snprintf(name, sizeof(name), "bg2_area%d_pal%d.png", area, p);
        char path[1200];
        snprintf(path, sizeof(path), "%s/%s", assets->asset_dir, name);
        if (!FileExists(path))
            continue;
        Texture2D tex = LoadTexture(path);
        if (!IsTextureValid(tex))
            continue;
        SetTextureFilter(tex, TEXTURE_FILTER_POINT);
        assets->bg2_area[p] = tex;
        any = true;
    }
    assets->bg_area_ready = any;
    if (!any)
        assets->bg_area_id = -1;
}
