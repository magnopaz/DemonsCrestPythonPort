#ifndef DC_ANIM_H
#define DC_ANIM_H

#include <stdbool.h>

#include "raylib.h"

#define DC_ANIM_MAX_STEPS 64

typedef enum AnimClipId {
    ANIM_IDLE = 0,
    ANIM_WALK,
    ANIM_JUMP,
    ANIM_HOVER,
    ANIM_FALL,
    ANIM_LAND,
    ANIM_ATTACK,
    ANIM_SPELL,
    ANIM_FLYING,
    ANIM_HURT,
    ANIM_DIE,
    ANIM_CLIP_COUNT
} AnimClipId;

typedef struct AnimStep {
    Texture2D texture;
    Texture2D flipped; /* pre-baked horizontal mirror (left facing) */
    int anchor_x;   /* pixels from the image left edge to the body centre */
    int anchor_y;   /* pixels from the image top edge to the feet */
    int duration;   /* game frames */
} AnimStep;

typedef struct AnimClip {
    int first_step;
    int step_count;
    bool loop;
} AnimClip;

typedef struct PlayerAnim {
    AnimStep steps[DC_ANIM_MAX_STEPS];
    int step_count;
    AnimClip clips[ANIM_CLIP_COUNT];
    bool ready;
} PlayerAnim;

#define DC_PROJECTILE_MAX_STEPS 16

typedef struct ProjectileAnim {
    AnimStep steps[DC_PROJECTILE_MAX_STEPS];
    int step_count;
    bool loop;
    bool ready;
} ProjectileAnim;

bool Anim_Load(PlayerAnim *anim, const char *dir);
/* player_forms.json: one PlayerAnim per crest form (index = form id). */
int Anim_LoadForms(PlayerAnim *anims, int max_forms, const char *dir);
void Anim_UnloadForms(PlayerAnim *anims, int count);
void Anim_Unload(PlayerAnim *anim);
const AnimStep *Anim_Step(const PlayerAnim *anim, int clip, int index);

bool ProjectileAnim_Load(ProjectileAnim *anim, const char *dir);
void ProjectileAnim_Unload(ProjectileAnim *anim);
const AnimStep *ProjectileAnim_Step(const ProjectileAnim *anim, int index);

#endif
