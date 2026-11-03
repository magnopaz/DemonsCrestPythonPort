#ifndef DC_RENDER_H
#define DC_RENDER_H

#include "assets.h"
#include "camera.h"
#include "level.h"
#include "player.h"
#include "projectile.h"
#include "object.h"

void Render_SetFade(float alpha);
void Render_DrawFade(void);

void Render_Game(const Assets *assets, const Level *level, const GameCamera *camera,
                 const Player *player, const ProjectilePool *projectiles,
                 const ObjectPool *objects, bool show_hud,
                 bool debug_collision);

#endif
