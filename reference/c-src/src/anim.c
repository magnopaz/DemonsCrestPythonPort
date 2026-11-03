#include "anim.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

static const char *const kClipNames[ANIM_CLIP_COUNT] = {
    "idle", "walk", "jump", "hover", "fall", "land", "attack", "spell",
    "flying", "hurt", "death"
};

static char *ReadText(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long size = ftell(f);
    if (size < 0) {
        fclose(f);
        return NULL;
    }
    rewind(f);
    char *text = malloc((size_t)size + 1);
    if (!text) {
        fclose(f);
        return NULL;
    }
    size_t got = fread(text, 1, (size_t)size, f);
    fclose(f);
    text[got] = '\0';
    return text;
}

static int ReadInt(cJSON *obj, const char *key, int *out) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(v))
        return 0;
    *out = v->valueint;
    return 1;
}

static bool LoadStepTextures(AnimStep *step, const char *path) {
    Image image = LoadImage(path);
    if (!image.data) {
        fprintf(stderr, "anim: failed to load %s\n", path);
        return false;
    }
    step->texture = LoadTextureFromImage(image);
    ImageFlipHorizontal(&image);
    step->flipped = LoadTextureFromImage(image);
    UnloadImage(image);
    if (!IsTextureValid(step->texture) || !IsTextureValid(step->flipped)) {
        fprintf(stderr, "anim: failed to create textures for %s\n", path);
        if (IsTextureValid(step->texture))
            UnloadTexture(step->texture);
        if (IsTextureValid(step->flipped))
            UnloadTexture(step->flipped);
        memset(step, 0, sizeof(*step));
        return false;
    }
    SetTextureFilter(step->texture, TEXTURE_FILTER_POINT);
    SetTextureFilter(step->flipped, TEXTURE_FILTER_POINT);
    return true;
}

void Anim_Unload(PlayerAnim *anim) {
    for (int i = 0; i < anim->step_count; i++) {
        if (IsTextureValid(anim->steps[i].texture))
            UnloadTexture(anim->steps[i].texture);
        if (IsTextureValid(anim->steps[i].flipped))
            UnloadTexture(anim->steps[i].flipped);
    }
    memset(anim, 0, sizeof(*anim));
}

/* Parse a "clips" object into an animation. Shared by the single player sheet
 * and the per-form player_forms.json. */
static bool ParseClips(PlayerAnim *anim, const cJSON *clips, const char *dir) {
    memset(anim, 0, sizeof(*anim));
    if (!cJSON_IsObject(clips))
        return false;

    bool ok = true;
    for (int clip_id = 0; clip_id < ANIM_CLIP_COUNT && ok; clip_id++) {
        cJSON *clip = cJSON_GetObjectItemCaseSensitive(clips,
                                                       kClipNames[clip_id]);
        if (!clip)
            continue;
        cJSON *steps = cJSON_GetObjectItemCaseSensitive(clip, "steps");
        if (!cJSON_IsArray(steps)) {
            ok = false;
            break;
        }
        AnimClip *dst = &anim->clips[clip_id];
        dst->first_step = anim->step_count;
        dst->loop = cJSON_IsTrue(
            cJSON_GetObjectItemCaseSensitive(clip, "loop"));
        int count = cJSON_GetArraySize(steps);
        if (count <= 0 || anim->step_count + count > DC_ANIM_MAX_STEPS) {
            ok = false;
            break;
        }
        for (int i = 0; i < count && ok; i++) {
            cJSON *item = cJSON_GetArrayItem(steps, i);
            cJSON *tex = cJSON_GetObjectItemCaseSensitive(item, "texture");
            AnimStep *step = &anim->steps[anim->step_count];
            if (!cJSON_IsString(tex) ||
                !ReadInt(item, "anchor_x", &step->anchor_x) ||
                !ReadInt(item, "anchor_y", &step->anchor_y)) {
                ok = false;
                break;
            }
            if (!ReadInt(item, "duration", &step->duration) ||
                step->duration < 1)
                step->duration = 1;

            char tex_path[1024];
            snprintf(tex_path, sizeof(tex_path), "%s/%s", dir,
                     tex->valuestring);
            if (!LoadStepTextures(step, tex_path)) {
                ok = false;
                break;
            }
            anim->step_count++;
        }
        dst->step_count = count;
    }

    if (!ok) {
        Anim_Unload(anim);
        return false;
    }
    anim->ready = anim->step_count > 0;
    return anim->ready;
}

bool Anim_Load(PlayerAnim *anim, const char *dir) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/player_anim.json", dir);
    char *text = ReadText(path);
    if (!text)
        return false;
    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root)
        return false;
    bool ok = ParseClips(anim, cJSON_GetObjectItemCaseSensitive(root, "clips"),
                         dir);
    cJSON_Delete(root);
    return ok;
}

int Anim_LoadForms(PlayerAnim *anims, int max_forms, const char *dir) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/player_forms.json", dir);
    char *text = ReadText(path);
    if (!text)
        return 0;
    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root)
        return 0;
    const cJSON *forms = cJSON_GetObjectItemCaseSensitive(root, "forms");
    int count = 0;
    const cJSON *entry = NULL;
    cJSON_ArrayForEach(entry, forms) {
        if (count >= max_forms)
            break;
        const cJSON *form = cJSON_GetObjectItemCaseSensitive(entry, "form");
        if (!cJSON_IsNumber(form))
            continue;
        int index = form->valueint;
        if (index < 0 || index >= max_forms)
            continue;
        if (ParseClips(&anims[index],
                       cJSON_GetObjectItemCaseSensitive(entry, "clips"), dir))
            count++;
    }
    cJSON_Delete(root);
    return count;
}

void Anim_UnloadForms(PlayerAnim *anims, int count) {
    for (int i = 0; i < count; i++)
        Anim_Unload(&anims[i]);
}

const AnimStep *Anim_Step(const PlayerAnim *anim, int clip, int index) {
    if (!anim->ready || clip < 0 || clip >= ANIM_CLIP_COUNT)
        return NULL;
    const AnimClip *c = &anim->clips[clip];
    if (c->step_count <= 0)
        return NULL;
    if (index < 0)
        index = 0;
    if (index >= c->step_count)
        index = c->step_count - 1;
    return &anim->steps[c->first_step + index];
}

bool ProjectileAnim_Load(ProjectileAnim *anim, const char *dir) {
    memset(anim, 0, sizeof(*anim));
    char path[1024];
    snprintf(path, sizeof(path), "%s/fireball_anim.json", dir);
    char *text = ReadText(path);
    if (!text)
        return false;

    cJSON *root = cJSON_Parse(text);
    free(text);
    if (!root)
        return false;

    cJSON *steps = cJSON_GetObjectItemCaseSensitive(root, "steps");
    if (!cJSON_IsArray(steps)) {
        cJSON_Delete(root);
        return false;
    }
    anim->loop = cJSON_IsTrue(
        cJSON_GetObjectItemCaseSensitive(root, "loop"));

    int count = cJSON_GetArraySize(steps);
    if (count <= 0 || count > DC_PROJECTILE_MAX_STEPS) {
        cJSON_Delete(root);
        return false;
    }

    bool ok = true;
    for (int i = 0; i < count && ok; i++) {
        cJSON *item = cJSON_GetArrayItem(steps, i);
        cJSON *tex = cJSON_GetObjectItemCaseSensitive(item, "texture");
        AnimStep *step = &anim->steps[i];
        if (!cJSON_IsString(tex) ||
            !ReadInt(item, "anchor_x", &step->anchor_x) ||
            !ReadInt(item, "anchor_y", &step->anchor_y)) {
            ok = false;
            break;
        }
        if (!ReadInt(item, "duration", &step->duration) ||
            step->duration < 1)
            step->duration = 1;

        char tex_path[1024];
        snprintf(tex_path, sizeof(tex_path), "%s/%s", dir,
                 tex->valuestring);
        if (!LoadStepTextures(step, tex_path)) {
            ok = false;
            break;
        }
        anim->step_count++;
    }

    cJSON_Delete(root);
    if (!ok) {
        ProjectileAnim_Unload(anim);
        return false;
    }
    anim->ready = anim->step_count > 0;
    return anim->ready;
}

void ProjectileAnim_Unload(ProjectileAnim *anim) {
    for (int i = 0; i < anim->step_count; i++) {
        if (IsTextureValid(anim->steps[i].texture))
            UnloadTexture(anim->steps[i].texture);
        if (IsTextureValid(anim->steps[i].flipped))
            UnloadTexture(anim->steps[i].flipped);
    }
    memset(anim, 0, sizeof(*anim));
}

const AnimStep *ProjectileAnim_Step(const ProjectileAnim *anim, int index) {
    if (!anim->ready || anim->step_count <= 0)
        return NULL;
    if (index < 0)
        index = 0;
    if (index >= anim->step_count) {
        if (!anim->loop)
            index = anim->step_count - 1;
        else
            index %= anim->step_count;
    }
    return &anim->steps[index];
}
