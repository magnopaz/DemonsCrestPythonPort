#include "text.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"

#define TEXT_GLYPH_W 8
#define TEXT_GLYPH_H 8
#define TEXT_COLUMNS 16
#define TEXT_FIRST 0x20
#define TEXT_LAST 0x7E

/* The ROM script uses ASCII with a few in-band symbols: `[` is an apostrophe,
 * `\` a full stop/quote stand-in and `j` a line break inside one line. Expand
 * them while loading so the renderer only sees printable text. */
static void CopyLine(char *dst, size_t cap, const char *src) {
    size_t n = strlen(src);
    if (n >= cap)
        n = cap - 1;
    for (size_t i = 0; i < n; i++) {
        char c = src[i];
        if (c == '[')
            c = '\'';
        else if (c == '\\')
            c = '.';
        dst[i] = c;
    }
    dst[n] = '\0';
}

/* Splits one ROM line on the in-line break symbol, up to `max` output lines. */
static int SplitLine(char out[TEXT_MAX_LINES][TEXT_LINE_MAX], int start,
                     int max, const char *src) {
    int count = 0;
    char buf[TEXT_LINE_MAX];
    size_t n = 0;
    for (const char *p = src; ; p++) {
        if (*p == 'j' || *p == '\0') {
            buf[n] = '\0';
            if (start + count < max && n > 0) {
                CopyLine(out[start + count], TEXT_LINE_MAX, buf);
                count++;
            }
            n = 0;
            if (!*p)
                break;
        } else if (n + 1 < sizeof(buf)) {
            buf[n++] = *p;
        }
    }
    return count;
}

bool Text_LoadScript(TextScript *script, const char *asset_dir) {
    memset(script, 0, sizeof(*script));
    char path[1200];
    snprintf(path, sizeof(path), "%s/text_strings.json", asset_dir);
    if (!FileExists(path))
        return false;
    char *text = LoadFileText(path);
    if (!text)
        return false;
    cJSON *root = cJSON_Parse(text);
    UnloadFileText(text);
    if (!root)
        return false;
    const cJSON *strings = cJSON_GetObjectItemCaseSensitive(root, "strings");
    const cJSON *entry = NULL;
    int index = 0;
    cJSON_ArrayForEach(entry, strings) {
        if (index >= TEXT_MAX_STRINGS)
            break;
        const cJSON *pages = cJSON_GetObjectItemCaseSensitive(entry, "pages");
        const cJSON *page = NULL;
        int p = 0;
        cJSON_ArrayForEach(page, pages) {
            if (p >= TEXT_MAX_PAGES)
                break;
            const cJSON *line = NULL;
            int l = 0;
            cJSON_ArrayForEach(line, page) {
                if (l >= TEXT_MAX_LINES)
                    break;
                if (cJSON_IsString(line))
                    l += SplitLine(script->pages[index][p], l,
                                   TEXT_MAX_LINES, line->valuestring);
            }
            script->line_count[index][p] = l;
            if (l > 0)
                p++;
        }
        script->page_count[index] = p;
        if (p > 0)
            index++;
    }
    script->count = index;
    cJSON_Delete(root);
    if (getenv("DC_TEXT_DEBUG") && script->count > 0) {
        fprintf(stderr, "text: %d strings, %d pages in [0]\n",
                script->count, script->page_count[0]);
        for (int i = 0; i < script->line_count[0][0]; i++)
            fprintf(stderr, "  line %d: '%s'\n", i, script->pages[0][0][i]);
    }
    return script->count > 0;
}

void Text_UnloadScript(TextScript *script) {
    memset(script, 0, sizeof(*script));
}

/* Loose substring match for script lookups.
 *
 * The ROM script is not plain ASCII: `[` stands for an apostrophe and `\` for a
 * full stop/quote, so the extracted text contains `I HAVEN[T SEEN YOU` while
 * the callers search for `HAVEN'T SEEN YOU`. A byte-for-byte strstr therefore
 * silently failed and left `town_greet` at -1, which disabled the town NPC
 * dialogue. Compare normalised forms instead: uppercase letters and digits
 * only, every other character collapsed into a single space.
 */
static void NormalizeText(char *dst, size_t cap, const char *src) {
    size_t n = 0;
    int pending_space = 0;
    for (const unsigned char *p = (const unsigned char *)src; *p && n + 1 < cap; p++) {
        unsigned char c = *p;
        if (c >= 'a' && c <= 'z')
            c = (unsigned char)(c - 'a' + 'A');
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) {
            if (pending_space && n > 0 && n + 1 < cap)
                dst[n++] = ' ';
            pending_space = 0;
            dst[n++] = (char)c;
        } else {
            pending_space = 1;
        }
    }
    dst[n] = 0;
}

bool Text_ContainsLoose(const char *haystack, const char *needle) {
    if (!haystack || !needle)
        return false;
    char hay[512];
    char pin[256];
    NormalizeText(hay, sizeof hay, haystack);
    NormalizeText(pin, sizeof pin, needle);
    if (!pin[0])
        return false;
    return strstr(hay, pin) != NULL;
}

int Text_Find(const TextScript *script, const char *needle) {
    if (!script || !needle || !*needle)
        return -1;
    for (int i = 0; i < script->count; i++) {
        for (int p = 0; p < script->page_count[i]; p++) {
            for (int l = 0; l < script->line_count[i][p]; l++) {
                if (Text_ContainsLoose(script->pages[i][p][l], needle))
                    return i;
            }
        }
    }
    return -1;
}

int Text_Width(const char *text) {
    int w = 0;
    for (const char *p = text; *p; p++) {
        if (*p == '\n') {
            w = 0;
            continue;
        }
        w += TEXT_GLYPH_W;
    }
    return w;
}

void Text_DrawString(const Assets *assets, const char *text, int x, int y,
                     Color tint) {
    if (!IsTextureValid(assets->font))
        return;
    int cx = x;
    int cy = y;
    for (const char *p = text; *p; p++) {
        unsigned char ch = (unsigned char)*p;
        if (ch == '\n') {
            cx = x;
            cy += TEXT_LINE_H;
            continue;
        }
        if (ch < TEXT_FIRST || ch > TEXT_LAST) {
            cx += TEXT_GLYPH_W;
            continue;
        }
        int index = ch - TEXT_FIRST;
        Rectangle src = {
            (float)((index % TEXT_COLUMNS) * TEXT_GLYPH_W),
            (float)((index / TEXT_COLUMNS) * TEXT_GLYPH_H),
            (float)TEXT_GLYPH_W,
            (float)TEXT_GLYPH_H
        };
        Rectangle dst = {(float)cx, (float)cy, (float)TEXT_GLYPH_W,
                         (float)TEXT_GLYPH_H};
        DrawTexturePro(assets->font, src, dst, (Vector2){0, 0}, 0.0f, tint);
        cx += TEXT_GLYPH_W;
    }
}

int Text_DrawPage(const Assets *assets, const TextScript *script, int index,
                  int page, int x, int y, int width, Color tint) {
    if (index < 0 || index >= script->count)
        return 0;
    if (page < 0 || page >= script->page_count[index])
        return 0;
    int lines = script->line_count[index][page];
    int height = lines * TEXT_LINE_H;
    DrawRectangle(x - 4, y - 4, width + 8, height + 8,
                  (Color){8, 8, 16, 210});
    DrawRectangleLines(x - 4, y - 4, width + 8, height + 8,
                       (Color){200, 180, 120, 180});
    for (int i = 0; i < lines; i++) {
        Text_DrawString(assets, script->pages[index][page][i], x,
                        y + i * TEXT_LINE_H, tint);
    }
    return height;
}
