#ifndef DC_TEXT_H
#define DC_TEXT_H

#include <stdbool.h>

#include "assets.h"
#include "raylib.h"

#define TEXT_MAX_STRINGS 512
#define TEXT_MAX_PAGES 6
#define TEXT_MAX_LINES 8
#define TEXT_LINE_MAX 48
#define TEXT_LINE_H 10 /* glyph 8px + 2px leading */

typedef struct TextScript {
    int count;
    int page_count[TEXT_MAX_STRINGS];
    char pages[TEXT_MAX_STRINGS][TEXT_MAX_PAGES][TEXT_MAX_LINES][TEXT_LINE_MAX];
    int line_count[TEXT_MAX_STRINGS][TEXT_MAX_PAGES];
} TextScript;

/* Loads `text_strings.json` (produced by tools/dc_extract/extract_text.py).
 * Only the first TEXT_MAX_STRINGS entries are kept. */
bool Text_LoadScript(TextScript *script, const char *asset_dir);
void Text_UnloadScript(TextScript *script);

/* Index of the first string containing `needle`, or -1. */
int Text_Find(const TextScript *script, const char *needle);

/* Normalised substring match ("HAVEN'T" matches "HAVEN[T"): the ROM script
 * uses `[` for an apostrophe and `\` for a period/quote. */
bool Text_ContainsLoose(const char *haystack, const char *needle);

/* Draws one line with the baked BG3 ASCII font (8x8, white mask). */
void Text_DrawString(const Assets *assets, const char *text, int x, int y,
                     Color tint);
int Text_Width(const char *text);

/* Draws a page inside a dialogue-style box; returns the box height. */
int Text_DrawPage(const Assets *assets, const TextScript *script, int index,
                  int page, int x, int y, int width, Color tint);

#endif
