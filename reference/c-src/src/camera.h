#ifndef DC_CAMERA_H
#define DC_CAMERA_H

#include "level.h"
#include "player.h"

typedef struct GameCamera {
    float x;
    float y;
} GameCamera;

void Camera_Init(GameCamera *camera, const Level *level);
void Camera_Update(GameCamera *camera, const Level *level, const Player *player);
void Camera_Focus(GameCamera *camera, const Level *level, float x);

#endif
