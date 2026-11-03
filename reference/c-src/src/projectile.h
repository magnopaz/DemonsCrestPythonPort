#ifndef DC_PROJECTILE_H
#define DC_PROJECTILE_H

#include <stdbool.h>
#include <stdint.h>

#include "camera.h"
#include "level.h"
#include "player.h"

#define PROJECTILE_POOL_SIZE 7

/* Player fireball slot ($1080..$1260, 7 slots of $50 bytes). */
typedef struct Projectile {
    bool active;
    int32_t x_fx;  /* 8.8 world X */
    int32_t y_fx;  /* 8.8 horizontal/vertical world Y */
    int32_t vx_fx; /* 8.8 horizontal velocity */
    int damage;
    int element;
    int age;       /* frames since spawn; 0 = spawn frame, not drawn yet */
} Projectile;

typedef struct ProjectilePool {
    Projectile slots[PROJECTILE_POOL_SIZE];
} ProjectilePool;

void Projectiles_Init(ProjectilePool *pool);
void Projectiles_Spawn(ProjectilePool *pool, const Player *player);
void Projectiles_Update(ProjectilePool *pool, Level *level,
                        const GameCamera *camera);

#endif
