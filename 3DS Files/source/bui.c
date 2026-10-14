#include "bui.h"

#include <stdlib.h>
#include <string.h>

#include "bchunk.h"

// Retail's FlailerObjectChunk carries the object's own name, a char[24], at
// +16, and every field the demo has from +16 on sits 24 bytes later: a
// bitmap is 144 bytes rather than 120, a text object 100 + MaxChars rather
// than 76. NameHash and GroupHash, at +8 and +12, come before it and don't
// move. The demo's +16 is ObjectType (1..5) and +17 Visible (0..3); retail
// has the first two characters of a name there, and every name on the disc
// starts with a letter. So the layout is told apart per object, and the
// same reader takes either game's bundles -- the checkers still run on the
// demo's. See docs/formats/flailer-ui.md.
static uint32_t object_shift(const uint8_t* p, uint32_t size)
{
    if (size < 56) return 0;          // too short for either; rejected later
    if (p[16] >= BUI_TYPE_TEXT && p[16] <= BUI_TYPE_SCREEN &&
        p[17] <= BUI_XBOX_ONLY)
        return 0;
    return BUI_NAME_LEN;
}

// LoaderFlailerChunk (0x0013d890) walks the top level looking for exactly two
// chunk types and, inside a screen container, special-cases the screen
// definition and treats *every other chunk* as an object -- it never looks at
// the object's chunk id. Objects are told apart at render time by
// ObjectType, so this does the same: anything that is not 0x00010203 inside a
// screen is an object.
static void walk_screen(BUI* ui, const uint8_t* payload, uint32_t size,
                        BUIScreen* screen, uint32_t* objCursor)
{
    BChunkIter it;
    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it)) {
        if (it.type == BUI_CHUNK_SCREENDEF) {
            if (!screen || it.size < 40) continue;
            screen->nameHash   = bchunk_u32(it.payload + 8);
            screen->resX       = bchunk_u16(it.payload + 24);
            screen->resY       = bchunk_u16(it.payload + 26);
            screen->numObjects = bchunk_u16(it.payload + 28);
            screen->visible    = false;
            screen->def        = it.payload;
            continue;
        }
        if (ui->objects) {
            ui->objects[*objCursor].payload = it.payload;
            ui->objects[*objCursor].size    = it.size;
            ui->objects[*objCursor].shift   = object_shift(it.payload,
                                                           it.size);
        }
        (*objCursor)++;
        if (screen) screen->count++;
    }
}

// One pass over the project. With ui->screens == NULL it only counts, which
// is how the tables get sized without a realloc.
static void walk_project(BUI* ui, const uint8_t* payload, uint32_t size)
{
    uint32_t  screenCursor = 0, objCursor = 0;
    BChunkIter it;
    bchunk_begin(&it, payload, 0, size);
    while (bchunk_next(&it)) {
        if (it.type == BUI_CHUNK_PROJECT) {
            if (it.size >= 12) ui->projectHash = bchunk_u32(it.payload + 8);
            continue;
        }
        if (it.type != BUI_CHUNK_SCREEN) continue;

        BUIScreen* s = NULL;
        if (ui->screens) {
            s = &ui->screens[screenCursor];
            memset(s, 0, sizeof(*s));
            s->nameHash = BUI_HASH_NONE;
            s->first    = objCursor;
        }
        screenCursor++;
        walk_screen(ui, it.payload, it.size, s, &objCursor);
    }
    ui->numScreens = screenCursor;
    ui->numObjects = objCursor;
}

bool bui_open(BUI* ui, const uint8_t* buf, size_t off, size_t len)
{
    memset(ui, 0, sizeof(*ui));
    ui->projectHash = BUI_HASH_NONE;

    uint32_t       size    = 0;
    const uint8_t* payload = bchunk_find(buf, off, len, BUI_CHUNK_FLAILER,
                                         &size);
    if (!payload) return false;

    walk_project(ui, payload, size);
    if (ui->numScreens == 0) return false;

    uint32_t nScreens = ui->numScreens, nObjects = ui->numObjects;
    ui->screens = (BUIScreen*)calloc(nScreens, sizeof(BUIScreen));
    ui->objects = nObjects
                ? (BUIObjectRef*)calloc(nObjects, sizeof(BUIObjectRef))
                : NULL;
    if (!ui->screens || (nObjects && !ui->objects)) {
        bui_close(ui);
        return false;
    }
    walk_project(ui, payload, size);
    return true;
}

void bui_close(BUI* ui)
{
    free(ui->screens);
    free(ui->objects);
    memset(ui, 0, sizeof(*ui));
}

BUIScreen* bui_find_screen(BUI* ui, uint32_t nameHash)
{
    for (uint32_t i = 0; i < ui->numScreens; i++)
        if (ui->screens[i].nameHash == nameHash) return &ui->screens[i];
    return NULL;
}

// Object `index` from ObjectType on, shifted so that the offsets used below
// are the demo's whichever layout the chunk is in, or NULL if it has fewer
// than `need` bytes at those offsets. *room, if asked for, is how many it
// has. NameHash and GroupHash are read from the unshifted payload.
static const uint8_t* fields(const BUI* ui, uint32_t index, uint32_t need,
                             uint32_t* room)
{
    const BUIObjectRef* r;
    if (index >= ui->numObjects) return NULL;
    r = &ui->objects[index];
    if (r->size - r->shift < need) return NULL;
    if (room) *room = r->size - r->shift;
    return r->payload + r->shift;
}

bool bui_object(const BUI* ui, uint32_t index, BUIObject* out)
{
    uint32_t       size = 0;
    const uint8_t* p    = fields(ui, index, 56, &size);
    if (!p) return false;
    const uint8_t* base = ui->objects[index].payload;

    memset(out, 0, sizeof(*out));
    out->nameHash     = bchunk_u32(base + 8);
    out->groupHash    = bchunk_u32(base + 12);
    if (ui->objects[index].shift)
        memcpy(out->name, base + 16, BUI_NAME_LEN);   // name[24] stays 0
    out->type         = (int8_t)p[16];
    out->visible      = (int8_t)p[17];
    out->z            = (int8_t)p[18];
    // p[19] is DirtyFlag and p[20..23] pFlailerStrip: runtime only.
    out->x            = bchunk_f32(p + 24);
    out->y            = bchunk_f32(p + 28);
    out->scaleX       = bchunk_f32(p + 32);
    out->scaleY       = bchunk_f32(p + 36);
    out->rotation     = (int32_t)bchunk_u32(p + 40);
    out->animation    = (int32_t)bchunk_u32(p + 44);
    out->renderOnPoly = bchunk_u32(p + 48);
    out->clipToPoly   = bchunk_u32(p + 52);
    out->chunk        = ui->objects[index].shift ? base : NULL;

    if (out->type == BUI_TYPE_BITMAP) {
        if (size < 120) return false;
        out->textureHash = bchunk_u32(p + 56);
        // p[60] is pTextureInfo, resolved at load; p[80] StateFlags, 0 on
        // every bitmap on disc; p[84] a tachometer point list.
        for (int i = 0; i < 4; i++)
            out->colors[i] = bchunk_u32(p + 64 + 4 * i);
        for (int i = 0; i < 8; i++)
            out->uv[i] = bchunk_f32(p + 88 + 4 * i);
    } else if (out->type == BUI_TYPE_TEXT) {
        if (size < 76) return false;
        out->fontHash   = bchunk_u32(p + 56);
        out->maxChars   = bchunk_u32(p + 60);
        out->format     = bchunk_u32(p + 64);
        out->color      = bchunk_u32(p + 68);
        out->languageID = bchunk_u32(p + 72);
        // The class ends in `char *String`, but on disc the characters sit
        // inline where the pointer would be, so the chunk is 76 + MaxChars
        // rounded up to 4. Trust the chunk's size, not MaxChars.
        out->string = (const char*)p + 76;
        if (out->maxChars > size - 76) out->maxChars = size - 76;
    }
    return true;
}

bool bui_object_layer(const BUI* ui, uint32_t index, int* visible, int* z)
{
    const uint8_t* p = fields(ui, index, 56, NULL);
    if (!p) return false;
    *visible = (int8_t)p[17];
    *z       = (int8_t)p[18];
    return true;
}

int32_t bui_find_object(const BUI* ui, const BUIScreen* screen,
                        uint32_t nameHash, int type)
{
    if (!screen) return -1;
    for (uint32_t i = 0; i < screen->count; i++) {
        uint32_t       idx = screen->first + i;
        const uint8_t* p   = fields(ui, idx, 56, NULL);
        if (!p) continue;
        if (bchunk_u32(ui->objects[idx].payload + 8) != nameHash) continue;
        // FindFlailerObject compares Type only when the argument is non-zero.
        if (type != BUI_TYPE_NONE && (int8_t)p[16] != (int8_t)type) continue;
        return (int32_t)idx;
    }
    return -1;
}

// FindFlailerObjectByGroup (0x00141a50). The original takes the object to
// resume after and returns the next one, which is how the group walks are
// written; here that is an index, and -1 starts at the head. Same wildcard
// rule as bui_find_object: type BUI_TYPE_NONE matches anything.
int32_t bui_next_in_group(const BUI* ui, const BUIScreen* screen,
                          uint32_t groupHash, int type, int32_t after)
{
    if (!screen) return -1;
    for (uint32_t i = 0; i < screen->count; i++) {
        uint32_t       idx = screen->first + i;
        if ((int32_t)idx <= after) continue;
        const uint8_t* p   = fields(ui, idx, 56, NULL);
        if (!p) continue;
        if (bchunk_u32(ui->objects[idx].payload + 12) != groupHash) continue;
        if (type != BUI_TYPE_NONE && (int8_t)p[16] != (int8_t)type) continue;
        return (int32_t)idx;
    }
    return -1;
}

// The chunk payloads are pointers into the caller's buffer. Writing through
// them is exactly what the engine does -- see bui.h -- so the const here is
// about the reading API, not about the storage.
static uint8_t* writable(BUI* ui, uint32_t index, uint32_t need,
                         uint32_t* room)
{
    return (uint8_t*)fields(ui, index, need, room);
}

bool bui_set_text_color(BUI* ui, uint32_t index, uint32_t rgb)
{
    uint8_t* p = writable(ui, index, 76, NULL);
    if (!p || (int8_t)p[16] != BUI_TYPE_TEXT) return false;
    uint32_t cur = bchunk_u32(p + 68);
    uint32_t val = (cur & 0xff000000u) | (rgb & 0x00ffffffu);
    if (val == cur) return true;      // SetColor skips the dirty flag too
    bchunk_put_u32(p + 68, val);
    p[19] = 7;                        // DirtyFlag, as SetColor sets it
    return true;
}

bool bui_put_text_color(BUI* ui, uint32_t index, uint32_t color)
{
    uint8_t* p = writable(ui, index, 76, NULL);
    if (!p || (int8_t)p[16] != BUI_TYPE_TEXT) return false;
    bchunk_put_u32(p + 68, color);
    return true;
}

bool bui_set_text_language(BUI* ui, uint32_t index, uint32_t languageID)
{
    uint8_t* p = writable(ui, index, 76, NULL);
    if (!p || (int8_t)p[16] != BUI_TYPE_TEXT) return false;
    if (bchunk_u32(p + 72) == languageID) return true;
    bchunk_put_u32(p + 72, languageID);
    p[19] = 7;                        // DirtyFlag, same as SetColor
    return true;
}

bool bui_set_object_pos(BUI* ui, uint32_t index, float x, float y)
{
    uint8_t* p = writable(ui, index, 56, NULL);
    if (!p) return false;
    bchunk_put_f32(p + 24, x);
    bchunk_put_f32(p + 28, y);
    p[19] = 7;
    return true;
}

// SetClipToPoly__18FlailerObjectChunki (retail 0x00140a70): nothing if the
// poly is already the one, else ClipToPoly and DirtyFlag 4; and a text
// object's SetFormatOptions(FORMAT_CLIP) (0x00140c68), which ORs the bit
// in and stamps DirtyFlag 5.
bool bui_set_object_clip(BUI* ui, uint32_t index, uint32_t poly)
{
    uint32_t room = 0;
    uint8_t* p    = writable(ui, index, 56, &room);
    if (!p) return false;
    if (bchunk_u32(p + 52) == poly) return true;
    p[19] = 4;
    bchunk_put_u32(p + 52, poly);
    if ((int8_t)p[16] == BUI_TYPE_TEXT && room >= 68) {
        bchunk_put_u32(p + 64, bchunk_u32(p + 64) | BUI_FMT_CLIP);
        p[19] = 5;
    }
    return true;
}

bool bui_set_object_visible(BUI* ui, uint32_t index, int visibility)
{
    uint8_t* p = writable(ui, index, 56, NULL);
    if (!p) return false;
    p[17] = (uint8_t)(int8_t)visibility;
    p[19] = 7;
    return true;
}

// GetAlpha__16FlailerTextChunk (0x0013ea80) is `lbu v0,71(a0)` and
// GetAlpha__18FlailerBitmapChunki (0x0013efa8) is `lbu v0,67(a0+corner*4)`:
// the alpha of a colour word is its top byte, and the only difference
// between the two object types is which of the five words is meant. A text
// object ignores `corner`, as FlailerObjectChunk::GetAlpha (0x0013e098)
// does by passing 0. Returns -1 for an object that has no colour at all.
// (Those are the demo's offsets; retail's are 24 further on, like the rest.)
int bui_get_object_alpha(const BUI* ui, uint32_t index, int corner)
{
    uint32_t       room = 0;
    const uint8_t* p    = fields(ui, index, 56, &room);
    if (!p) return -1;
    if ((int8_t)p[16] == BUI_TYPE_TEXT)
        return room >= 76 ? p[71] : -1;
    if ((int8_t)p[16] == BUI_TYPE_BITMAP) {
        if (room < 120) return -1;
        if (corner < 0 || corner > 3) corner = 0;
        return p[67 + 4 * corner];
    }
    return -1;
}

// SetAlpha__16FlailerTextChunk (0x0013ea48) and
// SetAlpha__18FlailerBitmapChunkii (0x0013ed50). Two differences worth
// keeping: the text one skips the write when the alpha is already right
// (and so leaves DirtyFlag alone) while the bitmap one always stamps it,
// and a bitmap corner of -1 means all four. Both write DirtyFlag 6, not
// the 7 SetColor uses -- 6 is "colours changed", 7 is "and the string".
bool bui_set_object_alpha(BUI* ui, uint32_t index, int corner, int alpha)
{
    uint32_t room = 0;
    uint8_t* p    = writable(ui, index, 56, &room);
    uint32_t a    = (uint32_t)(alpha & 0xff) << 24;
    if (!p) return false;

    if ((int8_t)p[16] == BUI_TYPE_TEXT) {
        uint32_t cur, val;
        if (room < 76) return false;
        cur = bchunk_u32(p + 68);
        val = (cur & 0x00ffffffu) | a;
        if (val == cur) return true;
        bchunk_put_u32(p + 68, val);
        p[19] = 6;
        return true;
    }
    if ((int8_t)p[16] == BUI_TYPE_BITMAP) {
        int i, first, last;
        if (room < 120) return false;
        p[19] = 6;
        first = corner < 0 ? 0 : corner;
        last  = corner < 0 ? 3 : corner;
        if (first > 3 || last > 3) return false;
        for (i = first; i <= last; i++) {
            uint32_t cur = bchunk_u32(p + 64 + 4 * i);
            bchunk_put_u32(p + 64 + 4 * i, (cur & 0x00ffffffu) | a);
        }
        return true;
    }
    return false;
}

// ChangeTexture__18FlailerBitmapChunki (0x0013eee0): repoints a bitmap at a
// different texture by hash. The original then caches the resolved
// TextureInfo* in the chunk at +60; the port resolves by hash through
// uirender.c's own cache every draw and never reads that field, so it is
// left alone rather than filled with a host pointer the chunk has no room
// for. DirtyFlag 10 is the engine's own value here, distinct from the 6 and
// 7 the colour setters use.
//
// Nothing in this build calls it -- FlailerChangeTexture (0x00142678) is the
// wrapper, and no screen on the disc uses it -- so this exists for the
// scrolling-texture demo in main.c, which is the only way to see a scrolling
// texture on screen at all. Same caveat about a writable buffer.
bool bui_set_bitmap_texture(BUI* ui, uint32_t index, uint32_t textureHash)
{
    uint8_t* p = writable(ui, index, 120, NULL);
    if (!p || (int8_t)p[16] != BUI_TYPE_BITMAP) return false;
    if (bchunk_u32(p + 56) == textureHash) return true;   // as the original
    bchunk_put_u32(p + 56, textureHash);
    p[19] = 10;
    return true;
}

// The scale half of FlailerTextChunk::ScaleAboutCenter -- the position half
// is the caller's, because only the renderer knows how wide the object is.
// Same caveat about a writable buffer.
bool bui_set_object_scale(BUI* ui, uint32_t index, float sx, float sy)
{
    uint8_t* p = writable(ui, index, 56, NULL);
    if (!p) return false;
    bchunk_put_f32(p + 32, sx);
    bchunk_put_f32(p + 36, sy);
    p[19] = 7;
    return true;
}

// FlailerPrintf (0x00141ae8) with a bare "%s": replaces a text object's
// inline string. On PS2 String is a heap block of MaxChars+1 and the
// formatter writes straight into it; here the characters live inside the
// chunk, so the room is whatever the chunk has after the 76-byte header
// (100 on retail) -- which is MaxChars rounded up to 4, never less.
// Truncates rather than overrun, and reports how much it kept.
uint32_t bui_set_text_string(BUI* ui, uint32_t index, const char* s)
{
    uint32_t size = 0, room, n = 0;
    uint8_t* p    = writable(ui, index, 76, &size);
    if (!p || (int8_t)p[16] != BUI_TYPE_TEXT) return 0;
    room = size - 76;
    if (room == 0) return 0;
    if (!s) s = "";
    while (n + 1 < room && s[n]) { p[76 + n] = (uint8_t)s[n]; n++; }
    p[76 + n] = 0;
    p[19] = 7;
    return n;
}

bool bui_copy_text(BUI* ui, uint32_t dst, uint32_t src)
{
    uint32_t       droom = 0, sroom = 0, n = 0;
    uint8_t*       d = writable(ui, dst, 76, &droom);
    const uint8_t* s = fields(ui, src, 76, &sroom);
    uint8_t        strip[4];

    if (!d || !s || d == s) return false;
    memcpy(strip, d + 20, 4);          // the jal's delay slot saves it
    memmove(d + 16, s + 16, 76 - 16);
    memcpy(d + 20, strip, 4);
    d[19] = 8;
    // The String pointer, the 64th byte's word: here, the characters.
    while (76 + n + 1 < droom && 76 + n < sroom && s[76 + n]) {
        d[76 + n] = s[76 + n];
        n++;
    }
    if (76 + n < droom) d[76 + n] = 0;
    return true;
}

void bui_color(uint32_t rgba, uint8_t out[4])
{
    for (int i = 0; i < 4; i++) {
        uint32_t c = (rgba >> (8 * i)) & 0xff;
        c *= 2;                       // GS scale: 0x80 is full intensity
        out[i] = (uint8_t)(c > 255 ? 255 : c);
    }
}
