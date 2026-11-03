"""Demon's Crest — Python port entry point (port of main.c)."""

from __future__ import annotations

import os
import sys
import time

from . import consts as C
from . import rl
from .game import (Game, game_init, game_password_selftest, game_render,
                   game_shutdown, game_update)


def find_asset_dir(argv: list[str]) -> str:
    for i in range(1, len(argv) - 1):
        if argv[i] == "--assets":
            return argv[i + 1]
    env = os.environ.get("DC_ASSETS")
    if env:
        return env
    candidates = [
        "assets/generated",
        os.path.join("..", "DemonsCrestNativePort", "assets", "generated"),
        os.path.expanduser("~/Projetos/opencode/DemonsCrestNativePort/"
                           "assets/generated"),
    ]
    for path in candidates:
        if os.path.isfile(os.path.join(path, "player_anim.json")):
            return path
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    if "DC_PASSWORD_SELFTEST" in os.environ:
        return 0 if game_password_selftest() else 1

    rl.SetTraceLogLevel(4)  # LOG_WARNING
    rl.SetConfigFlags(rl.FLAG_WINDOW_RESIZABLE | rl.FLAG_VSYNC_HINT)
    rl.InitWindow(1024, 896, b"Demon's Crest - Python Port")
    if not rl.IsWindowReady():
        print("main: InitWindow failed (check DISPLAY)", file=sys.stderr,
              flush=True)
        return 1
    rl.SetWindowMinSize(512, 448)
    rl.SetTargetFPS(0)

    game = Game()
    if not game_init(game, find_asset_dir(argv)):
        print("main: Game_Init failed", file=sys.stderr, flush=True)
        rl.CloseWindow()
        return 1

    run_limit = int(os.environ.get("DC_RUN_FRAMES", "0") or "0")
    shot = os.environ.get("DC_SCREENSHOT", "")
    shot_rt = os.environ.get("DC_SCREENSHOT_RT", "")
    frames = 0
    step = 1.0 / 60.0
    accumulator = 0.0
    deterministic = run_limit > 0

    while frames < run_limit if deterministic else not rl.WindowShouldClose():
        if deterministic:
            game_update(game)
            frames += 1
        else:
            dt = rl.GetFrameTime()
            if dt > 0.25:
                dt = 0.25
            accumulator += dt
            updates = 0
            while accumulator >= step and updates < 8:
                game_update(game)
                accumulator -= step
                frames += 1
                updates += 1
            if updates == 8 and accumulator >= step:
                accumulator = 0.0

        game_render(game)
        rl.BeginDrawing()
        rl.ClearBackground(rl.rgb(0, 0, 0))
        sw = rl.GetScreenWidth()
        sh = rl.GetScreenHeight()
        scale = sw // 256
        if sh // 224 < scale:
            scale = sh // 224
        if scale < 1:
            scale = 1
        if "DC_WINDOW_INFO" in os.environ:
            print(f"window={sw}x{sh} rt={game.target.texture.width}x"
                  f"{game.target.texture.height} scale={scale}",
                  file=sys.stderr, flush=True)
        dw = 256 * scale
        dh = 224 * scale
        dst = rl.Rectangle(float((sw - dw) // 2), float((sh - dh) // 2),
                           float(dw), float(dh))
        src = rl.Rectangle(0.0, 0.0, 256.0, -224.0)
        rl.DrawTexturePro(game.target.texture, src, dst, rl.Vector2(0, 0), 0.0,
                          rl.rgb(255, 255, 255))
        if rl.IsKeyDown(rl.KEY_F3):
            rl.DrawFPS(8, 8)
        rl.EndDrawing()

        if deterministic and frames >= run_limit:
            if shot_rt:
                rl.BeginTextureMode(game.target)  # ensure the RT is complete
                rl.EndTextureMode()
                image = rl.LoadImageFromTexture(game.target.texture)
                # Render textures are stored bottom-up; export them upright so
                # the file matches the scaled window DrawTexturePro produces.
                rl.ImageFlipVertical(rl.ffi.addressof(image))
                rl.ExportImage(image, os.fsencode(shot_rt))
                rl.UnloadImage(image)
            if shot:
                rl.TakeScreenshot(os.fsencode(shot))
            break

    game_shutdown(game)
    rl.CloseWindow()
    time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
