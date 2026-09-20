#include "bui.h"

#include <stdlib.h>
#include <string.h>

#include "bchunk.h"

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
            continue;
        }
        if (ui->objects) {
            ui->objects[*objCursor].payload = it.payload;
            ui->objects[*objCursor].size    = it.size;
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

bool bui_object(const BUI* ui, uint32_t index, BUIObject* out)
{
    if (index >= ui->numObjects) return false;
    const uint8_t* p    = ui->objects[index].payload;
    uint32_t       size = ui->objects[index].size;
    if (size < 56) return false;

    memset(out, 0, sizeof(*out));
    out->nameHash     = bchunk_u32(p + 8);
    out->groupHash    = bchunk_u32(p + 12);
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

int32_t bui_find_object(const BUI* ui, const BUIScreen* screen,
                        uint32_t nameHash, int type)
{
    if (!screen) return -1;
    for (uint32_t i = 0; i < screen->count; i++) {
        uint32_t       idx = screen->first + i;
        const uint8_t* p   = ui->objects[idx].payload;
        if (ui->objects[idx].size < 56) continue;
        if (bchunk_u32(p + 8) != nameHash) continue;
        // FindFlailerObject compares Type only when the argument is non-zero.
        if (type != BUI_TYPE_NONE && (int8_t)p[16] != (int8_t)type) continue;
        return (int32_t)idx;
    }
    return -1;
}

// The chunk payloads are pointers into the caller's buffer. Writing through
// them is exactly what the engine does -- see bui.h -- so the const here is
// about the reading API, not about the storage.
static uint8_t* writable(BUI* ui, uint32_t index, uint32_t need)
{
    if (index >= ui->numObjects || ui->objects[index].size < need) return NULL;
    return (uint8_t*)ui->objects[index].payload;
}

bool bui_set_text_color(BUI* ui, uint32_t index, uint32_t rgb)
{
    uint8_t* p = writable(ui, index, 76);
    if (!p || (int8_t)p[16] != BUI_TYPE_TEXT) return false;
    uint32_t cur = bchunk_u32(p + 68);
    uint32_t val = (cur & 0xff000000u) | (rgb & 0x00ffffffu);
    if (val == cur) return true;      // SetColor skips the dirty flag too
    bchunk_put_u32(p + 68, val);
    p[19] = 7;                        // DirtyFlag, as SetColor sets it
    return true;
}

bool bui_set_object_pos(BUI* ui, uint32_t index, float x, float y)
{
    uint8_t* p = writable(ui, index, 56);
    if (!p) return false;
    bchunk_put_f32(p + 24, x);
    bchunk_put_f32(p + 28, y);
    p[19] = 7;
    return true;
}

bool bui_set_object_visible(BUI* ui, uint32_t index, int visibility)
{
    uint8_t* p = writable(ui, index, 56);
    if (!p) return false;
    p[17] = (uint8_t)(int8_t)visibility;
    p[19] = 7;
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
