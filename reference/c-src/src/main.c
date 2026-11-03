#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "game.h"
#include "raylib.h"

static const char *FindAssetDir(int argc, char **argv) {
    for (int i = 1; i < argc - 1; i++) {
        if (strcmp(argv[i], "--assets") == 0)
            return argv[i + 1];
    }
    return "assets/generated";
}

int main(int argc, char **argv) {
    /* Password codec self-test: no window/assets needed, suitable for CI. */
    if (getenv("DC_PASSWORD_SELFTEST"))
        return Game_PasswordSelfTest() ? 0 : 1;
    SetTraceLogLevel(LOG_WARNING);
    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_VSYNC_HINT);
    InitWindow(1024, 896, "Demon's Crest - Fan Game");
    if (!IsWindowReady()) {
        fprintf(stderr, "main: InitWindow failed (check DISPLAY)\n");
        return 1;
    }
    SetWindowMinSize(512, 448);
    SetTargetFPS(0); /* presentation is decoupled from the fixed 60 Hz sim */

    /* The Game struct holds the loaded text script (~1 MB), so keep it off the
     * stack. */
    Game *game = (Game *)calloc(1, sizeof(Game));
    if (!game) {
        fprintf(stderr, "main: out of memory for Game\n");
        CloseWindow();
        return 1;
    }
    if (!Game_Init(game, FindAssetDir(argc, argv))) {
        fprintf(stderr, "main: Game_Init failed\n");
        free(game);
        CloseWindow();
        return 1;
    }

    const char *run_frames_env = getenv("DC_RUN_FRAMES");
    int run_limit = run_frames_env ? atoi(run_frames_env) : 0;
    const char *shot = getenv("DC_SCREENSHOT");
    int frames = 0;
    const double step = 1.0 / 60.0;
    double accumulator = 0.0;
    const bool deterministic = run_limit > 0;

    while (deterministic ? (frames < run_limit) : !WindowShouldClose()) {
        if (deterministic) {
            /* Headless captures stay exactly one update per loop so
             * DC_RUN_FRAMES/DC_TRACE_CSV remain reproducible. */
            Game_Update(game);
            frames++;
        } else {
            double dt = GetFrameTime();
            if (dt > 0.25)
                dt = 0.25; /* avoid a huge catch-up after a stall */
            accumulator += dt;
            int updates = 0;
            while (accumulator >= step && updates < 8) {
                Game_Update(game);
                accumulator -= step;
                frames++;
                updates++;
            }
            if (updates == 8 && accumulator >= step)
                accumulator = 0.0; /* drop the backlog rather than spiral */
        }

        Game_Render(game);
        BeginDrawing();
        ClearBackground((Color){0, 0, 0, 255});

        int sw = GetScreenWidth();
        int sh = GetScreenHeight();
        int scale = sw / 256;
        if (sh / 224 < scale)
            scale = sh / 224;
        if (scale < 1)
            scale = 1;
        if (getenv("DC_WINDOW_INFO"))
            fprintf(stderr, "window=%dx%d rt=%dx%d scale=%d\n", sw, sh,
                    game->target.texture.width, game->target.texture.height,
                    scale);
        int dw = 256 * scale;
        int dh = 224 * scale;
        Rectangle dst = {
            (float)((sw - dw) / 2),
            (float)((sh - dh) / 2),
            (float)dw,
            (float)dh
        };
        Rectangle src = {0, 0, 256, -224};
        DrawTexturePro(game->target.texture, src, dst, (Vector2){0, 0}, 0.0f,
                       WHITE);
        if (IsKeyDown(KEY_F3))
            DrawFPS(8, 8);
        EndDrawing();

        if (shot && *shot && deterministic && frames >= run_limit) {
            TakeScreenshot(shot);
            break;
        }
    }

    Game_Shutdown(game);
    free(game);
    CloseWindow();
    return 0;
}
