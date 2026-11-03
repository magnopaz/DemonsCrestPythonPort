#include "projectile.h"

#include <math.h>
#include <string.h>

#define FX_ONE 256
#define PLAYER_FIREBALL_VX_FX 0x0300 /* $80:F222 object: 3.0 px/frame */
#define PLAYER_FIREBALL_X_OFFSET 10  /* spawn at the mouth, not the feet */
#define PLAYER_FIREBALL_Y_OFFSET 18  /* mouth/chest height above the feet */

void Projectiles_Init(ProjectilePool *pool) {
    memset(pool, 0, sizeof(*pool));
}

void Projectiles_Spawn(ProjectilePool *pool, const Player *player) {
    for (int i = 0; i < PROJECTILE_POOL_SIZE; i++) {
        Projectile *p = &pool->slots[i];
        if (p->active)
            continue;
        int dir = player->facing < 0 ? -1 : 1;
        p->x_fx = ((int32_t)floorf(player->x) +
                   PLAYER_FIREBALL_X_OFFSET * dir) * FX_ONE;
        p->y_fx = ((int32_t)floorf(player->y) -
                   PLAYER_FIREBALL_Y_OFFSET) * FX_ONE;
        p->vx_fx = PLAYER_FIREBALL_VX_FX * dir;
        p->element = player->fire_element;
        p->damage = (player->crest_form == CREST_TIME ||
                     player->crest_form == CREST_ULTIMATE ||
                     player->active_talisman == 3) ? 2 : 1;
        p->age = 0;
        p->active = true;
        return; /* $80:F222 allocates the first free slot only */
    }
}

void Projectiles_Update(ProjectilePool *pool, Level *level,
                        const GameCamera *camera) {
    for (int i = 0; i < PROJECTILE_POOL_SIZE; i++) {
        Projectile *p = &pool->slots[i];
        if (!p->active)
            continue;

        p->age++;
        p->x_fx += p->vx_fx;

        float x = (float)p->x_fx / (float)FX_ONE;
        float y = (float)p->y_fx / (float)FX_ONE;

        bool offscreen = x < camera->x || x > camera->x + 256.0f ||
                         y < camera->y || y > camera->y + 224.0f;
        if (Level_IsBreakableAt(level, x, y) &&
            (p->element == 1 || p->damage >= 2)) {
            Level_BreakBlockAt(level, x, y);
            p->active = false;
            continue;
        }
        if (offscreen || Level_IsWallAt(level, x, y)) {
            p->active = false;
            continue;
        }
    }
}
