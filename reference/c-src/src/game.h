#ifndef DC_GAME_H
#define DC_GAME_H

#include <stdbool.h>
#include <stdio.h>

#include "assets.h"
#include "camera.h"
#include "input.h"
#include "level.h"
#include "player.h"
#include "projectile.h"
#include "object.h"
#include "raylib.h"
#include "text.h"

/* Native password: 10 symbols, see Game_PasswordEncode. */
#define DC_PASSWORD_LEN 10

typedef struct Game {
    Assets assets;
    Level level;
    Player player;
    ProjectilePool projectiles;
    ObjectPool objects;
    GameCamera camera;
    Input input;
    InputState input_state;
    RenderTexture2D target;
    FILE *trace;
    FILE *projectile_trace;
    FILE *object_trace;
    char asset_dir[512];
    unsigned frame;
    int state_timer;
    int state; /* GameState */
    int menu_cursor;
    int subscreen_row;
    int overworld_node;
    bool stage_select; /* overworld stage list overlay */
    int stage_sel;
    int pause_flash; /* frames the SAVED hint stays visible */
    int intro_timer; /* frames the area-entry banner stays visible */
    /* Somulo's scripted entrance: the player has no control until the roar.
     * 0 = off, otherwise the phase below (1..3). */
    int boss_intro;
    int boss_intro_timer;
    int shake;       /* frames of screen shake left */
    int shake_phase;
    /* Death in an arena restarts the room (entrance included) instead of
     * showing GAME OVER, which is what the recording of Somulo shows. */
    int restart_timer;
    /* Room change fade, measured from the oracle: 28 frames out, 64 black
     * (the load happens there), 28 in. 0 = idle, 1 = out, 2 = black, 3 = in. */
    int transition_phase;
    int transition_timer;
    int transition_area;
    int transition_spawn;
    int talisman_toast;       /* frames the talisman line is shown */
    int talisman_toast_index; /* which talisman was picked up */
    bool attract;    /* title-screen demo running */
    int attract_frame;
    float overworld_x;
    float overworld_y;
    float overworld_angle;
    float overworld_zoom;
    uint8_t stages_cleared;
    uint8_t area_cleared[DC_CAMPAIGN_AREAS]; /* per-area clear flags */
    char password_code[20];
    char password_entry[DC_PASSWORD_LEN + 1];
    int password_pos;
    int password_status; /* 0 neutral, 1 accepted, -1 invalid */
    bool campaign_mode;
    TextScript script;
    int shop_welcome; /* cached text indices (ROM shop dialogue) */
    int shop_full_urn;
    int shop_full_vellum;
    int shop_message;
    int ending_text;   /* cached ROM narration index */
    int ending_variant; /* 0 bad, 1 normal, 2 good, 3 true */
    int ending_phase;   /* 0 narration, 1 epilogue/end card */
    int ending_page;
    int dialogue_text;   /* script entry shown by GAME_DIALOGUE */
    int dialogue_page;
    int dialogue_return; /* state after the last page */
    int crest_text[6];   /* cached "YOU HAVE FOUND THE CREST OF ..." */
    /* City NPC conversation (revealed by the save0ba dialogue capture). */
    int town_greet;      /* "HEY YOU! I HAVEN'T SEEN YOU AROUND HERE BEFORE!" */
    int town_question;   /* "ARE YOU A STRANGER HERE?" */
    int town_story[5];   /* the "Firebrand has risen" explanation pages */
    int talk_seq[10];    /* conversation script indices in order */
    int talk_len;
    int talk_pos;
    int talk_choice;     /* 0 none, 1 waiting on YES/NO */
    int talk_choice_sel; /* 0 YES, 1 NO */
    int fire_text[5];    /* cached "YOU GOT THE PIECE OF THE FIRE CREST ..." */
    int shop_timer;
    int shop_sel; /* 0..4 items, 5 = EXIT */
    int shop_no_money; /* "CHEAPSKATE! ..." */
    int shop_need_vellum; /* "...BRING ME A VELLUM FIRST" */
    bool dialogue_demo; /* DC_DIALOGUE overlay */
    bool script_ready;
    bool has_save;
    bool prev_up;
    bool prev_down;
    bool prev_left;
    bool prev_right;
    bool ready;
} Game;

bool Game_Init(Game *game, const char *asset_dir);
void Game_Update(Game *game);
void Game_Render(Game *game);
void Game_Shutdown(Game *game);
bool Game_TransitionToArea(Game *game, int area_id, int spawn_id);
void Game_BeginTransition(Game *game, int area_id, int spawn_id);
bool Game_UpdateTransition(Game *game);
void Game_EncodePassword(const Game *game, char out[DC_PASSWORD_LEN + 1]);
uint32_t Game_PasswordPayload(const Game *game);
void Game_PasswordEncode(uint32_t payload, char out[DC_PASSWORD_LEN + 1]);
bool Game_PasswordDecode(const char *code, uint32_t *payload);
bool Game_ApplyPassword(Game *game, const char *code);
bool Game_PasswordSelfTest(void);
bool Game_SaveProgress(const Game *game);
bool Game_LoadProgress(Game *game);
bool Game_HasSave(void);

typedef enum GameState {
    GAME_TITLE = 0,
    GAME_PLAYING = 1,
    GAME_PAUSED = 2,
    GAME_CLEAR = 3,
    GAME_SUBSCREEN = 4,
    GAME_OVERWORLD = 5,
    GAME_SHOP = 6,
    GAME_PASSWORD = 7,
    GAME_OPTIONS = 8,
    GAME_OVER = 9,
    GAME_ENDING = 10,
    GAME_DIALOGUE = 11
} GameState;

#endif
