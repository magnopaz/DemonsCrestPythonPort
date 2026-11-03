"""Camera deadzone (port of camera.c)."""

from __future__ import annotations


class GameCamera:
    __slots__ = ("x", "y")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0


def camera_init(camera: GameCamera, level) -> None:
    camera.x = level.camera_x
    camera.y = level.camera_y


def camera_update(camera: GameCamera, level, player) -> None:
    screen_x = player.x - camera.x
    screen_y = player.y - camera.y

    if screen_x < 96.0:
        camera.x = player.x - 96.0
    elif screen_x > 160.0:
        camera.x = player.x - 160.0

    if screen_y < 96.0:
        camera.y = player.y - 96.0
    elif screen_y > 176.0:
        camera.y = player.y - 176.0

    max_x = level.camera_max_x
    if max_x < level.camera_min_x:
        max_x = level.camera_min_x
    if camera.x < level.camera_min_x:
        camera.x = level.camera_min_x
    if camera.x > max_x:
        camera.x = max_x

    max_y = level.camera_max_y
    if max_y < level.camera_min_y:
        max_y = level.camera_min_y
    if camera.y < level.camera_min_y:
        camera.y = level.camera_min_y
    if camera.y > max_y:
        camera.y = max_y


def camera_focus(camera: GameCamera, level, x: float) -> None:
    camera.x = x - 128.0
    max_x = level.camera_max_x
    if max_x < level.camera_min_x:
        max_x = level.camera_min_x
    if camera.x < level.camera_min_x:
        camera.x = level.camera_min_x
    if camera.x > max_x:
        camera.x = max_x
