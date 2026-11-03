#include "camera.h"

#include "raylib.h"

void Camera_Init(GameCamera *camera, const Level *level) {
    camera->x = level->camera_x;
    camera->y = level->camera_y;
}

void Camera_Update(GameCamera *camera, const Level *level, const Player *player) {
    float screen_x = player->x - camera->x;
    float screen_y = player->y - camera->y;

    /* Original-style deadzone: the camera only moves when Firebrand leaves a
     * central window. The vertical window keeps the ground view stable at
     * spawn and follows high jumps. Tune against the oracle once wider
     * movement traces exist. */
    if (screen_x < 96.0f)
        camera->x = player->x - 96.0f;
    else if (screen_x > 160.0f)
        camera->x = player->x - 160.0f;

    if (screen_y < 96.0f)
        camera->y = player->y - 96.0f;
    else if (screen_y > 176.0f)
        camera->y = player->y - 176.0f;

    float max_x = level->camera_max_x;
    if (max_x < level->camera_min_x)
        max_x = level->camera_min_x;
    if (camera->x < level->camera_min_x)
        camera->x = level->camera_min_x;
    if (camera->x > max_x)
        camera->x = max_x;

    float max_y = level->camera_max_y;
    if (max_y < level->camera_min_y)
        max_y = level->camera_min_y;
    if (camera->y < level->camera_min_y)
        camera->y = level->camera_min_y;
    if (camera->y > max_y)
        camera->y = max_y;
}


/* Centre the view on a world x, clamped to the room. Used by scripted scenes
 * (Somulo's entrance pans with him) where the player is not the subject. */
void Camera_Focus(GameCamera *camera, const Level *level, float x) {
    camera->x = x - 128.0f;
    float max_x = level->camera_max_x;
    if (max_x < level->camera_min_x)
        max_x = level->camera_min_x;
    if (camera->x < level->camera_min_x)
        camera->x = level->camera_min_x;
    if (camera->x > max_x)
        camera->x = max_x;
}
