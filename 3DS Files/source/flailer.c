#include "flailer.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "eefpu.h"

float (*gFlailerTextScaledWidthFn)(struct FlailerTextChunk *t);
float (*gFlailerTextScaledHeightFn)(struct FlailerTextChunk *t);
bool (*gFlailerBitmapTextureSizeFn)(struct FlailerBitmapChunk *b, int32_t *w,
                                    int32_t *h);

// ------------------------------------------------------------- projects

// The bundles UIR_MAX_BUNDLES allows, and room to spare.
#define FLAILER_MAX_PROJECTS 8

// One LoaderFlailerChunk's project. `order` is its ScreenList: the indices
// of the screens the loader linked, which are those with a screen chunk,
// in the list's current order.
typedef struct {
    BUI      *ui;
    uint32_t *order;
    uint32_t  numLinked;
} FlailerProject;

static FlailerProject sProjects[FLAILER_MAX_PROJECTS];
// The project list, gp-22424: indices into sProjects, head first.
static int sList[FLAILER_MAX_PROJECTS];
static int sNumProjects;

static struct FlailerScreenChunk *screen_chunk(const BUIScreen *s)
{
    return (struct FlailerScreenChunk *)s->def;
}

static struct FlailerObjectChunk *object_chunk(const BUI *ui, uint32_t i)
{
    return (struct FlailerObjectChunk *)ui->objects[i].payload;
}

bool flailer_add_project(BUI *ui)
{
    FlailerProject *p;
    uint32_t        i, j;

    if (ui == NULL || sNumProjects >= FLAILER_MAX_PROJECTS) return false;
    for (i = 0; i < ui->numObjects; i++) {
        const BUIObjectRef *r = &ui->objects[i];
        if (r->shift != BUI_NAME_LEN
            || r->size < sizeof(struct FlailerObjectChunk)
            || ((uintptr_t)r->payload & 3) != 0)
            return false;
    }
    for (i = 0; i < ui->numScreens; i++)
        if (ui->screens[i].def != NULL
            && ((uintptr_t)ui->screens[i].def & 3) != 0)
            return false;

    p = &sProjects[sNumProjects];
    p->ui = ui;
    p->order = (uint32_t *)malloc((ui->numScreens ? ui->numScreens : 1)
                                  * sizeof(uint32_t));
    if (p->order == NULL) return false;
    p->numLinked = 0;
    for (i = 0; i < ui->numScreens; i++) {
        const BUIScreen *s = &ui->screens[i];
        if (s->def == NULL) continue;
        p->order[p->numLinked++] = i;
        screen_chunk(s)->Visible = 1;          // FLAILER_SCREEN_INVISIBLE
        // 0x001402a0, the screen's UpdateLanguageText.
        for (j = 0; j < s->count; j++) {
            struct FlailerObjectChunk *o = object_chunk(ui, s->first + j);
            if (o->ObjectType == FLAILER_TYPE_TEXT)
                flailertext_update_language_text(
                    (struct FlailerTextChunk *)o);
        }
    }
    sList[sNumProjects] = sNumProjects;
    sNumProjects++;
    return true;
}

void flailer_reset(void)
{
    int i;
    for (i = 0; i < sNumProjects; i++) free(sProjects[i].order);
    memset(sProjects, 0, sizeof(sProjects));
    sNumProjects = 0;
}

bool flailer_object_index(const struct FlailerObjectChunk *o, BUI **ui,
                          uint32_t *index)
{
    const uint8_t *a = (const uint8_t *)o;
    int            p;

    if (o == NULL) return false;
    // A project's objects are in file order, so their addresses rise.
    for (p = 0; p < sNumProjects; p++) {
        BUI     *u  = sProjects[p].ui;
        uint32_t lo = 0, hi = u->numObjects;
        while (lo < hi) {
            uint32_t mid = lo + (hi - lo) / 2;
            if (u->objects[mid].payload < a) lo = mid + 1;
            else                             hi = mid;
        }
        if (lo < u->numObjects && u->objects[lo].payload == a) {
            if (ui) *ui = u;
            if (index) *index = lo;
            return true;
        }
    }
    return false;
}

BUIScreen *flailer_screen_of(const struct FlailerScreenChunk *s, BUI **ui)
{
    int      p;
    uint32_t i;

    if (s == NULL) return NULL;
    for (p = 0; p < sNumProjects; p++) {
        BUI *u = sProjects[p].ui;
        for (i = 0; i < u->numScreens; i++)
            if (u->screens[i].def == (const uint8_t *)s) {
                if (ui) *ui = u;
                return &u->screens[i];
            }
    }
    return NULL;
}

BUI *flailer_project_at(int n, const uint32_t **order, uint32_t *count)
{
    const FlailerProject *p;
    if (n < 0 || n >= sNumProjects) return NULL;
    p = &sProjects[sList[n]];
    if (order) *order = p->order;
    if (count) *count = p->numLinked;
    return p->ui;
}

// ---------------------------------------------------------------- lookups

// The walk counts every screen it passes over, across the projects, and
// never resets: a match after two or more is pulled to the front, and its
// project with it, so the screens asked for every frame are found first.
static BUIScreen *find_screen(uint32_t hash, BUI **outUI)
{
    uint32_t skipped = 0;
    int      n;

    for (n = 0; n < sNumProjects; n++) {
        FlailerProject *p = &sProjects[sList[n]];
        uint32_t        i;
        for (i = 0; i < p->numLinked; i++) {
            BUIScreen *s = &p->ui->screens[p->order[i]];
            if (screen_chunk(s)->NameHash != hash) {
                skipped++;
                continue;
            }
            if (skipped >= 2) {
                uint32_t idx  = p->order[i];
                int      proj = sList[n];
                memmove(&p->order[1], &p->order[0], i * sizeof(uint32_t));
                p->order[0] = idx;
                memmove(&sList[1], &sList[0], (size_t)n * sizeof(int));
                sList[0] = proj;
            }
            if (outUI) *outUI = p->ui;
            return s;
        }
    }
    return NULL;
}

struct FlailerScreenChunk *flailer_find_screen(uint32_t screen)
{
    BUIScreen *s = find_screen(screen, NULL);
    return s ? screen_chunk(s) : NULL;
}

struct FlailerObjectChunk *flailer_find_object(uint32_t screen,
                                               uint32_t object,
                                               int32_t type)
{
    BUI       *ui = NULL;
    BUIScreen *s  = find_screen(screen, &ui);
    uint32_t   i;

    if (s == NULL) return NULL;
    for (i = 0; i < s->count; i++) {
        struct FlailerObjectChunk *o = object_chunk(ui, s->first + i);
        if (o->NameHash != object) continue;
        if (type == FLAILER_TYPE_ANY || o->ObjectType == type) return o;
    }
    return NULL;
}

struct FlailerObjectChunk *flailer_find_object_by_group(
    uint32_t screen, uint32_t group, int32_t type,
    struct FlailerObjectChunk *after)
{
    BUI       *ui = NULL;
    BUIScreen *s  = find_screen(screen, &ui);
    uint32_t   i  = 0;

    if (s == NULL) return NULL;
    if (after != NULL) {
        // The walk resumes at after->Next. `after` is on this screen in
        // every call the game makes; one that is not ends the walk.
        while (i < s->count && object_chunk(ui, s->first + i) != after) i++;
        if (i == s->count) return NULL;
        i++;
    }
    for (; i < s->count; i++) {
        struct FlailerObjectChunk *o = object_chunk(ui, s->first + i);
        if (o->GroupHash != group) continue;
        if (type == FLAILER_TYPE_ANY || o->ObjectType == type) return o;
    }
    return NULL;
}

// ------------------------------------------------------ FlailerObjectChunk

#define TEXT(o)   ((struct FlailerTextChunk *)(o))
#define BITMAP(o) ((struct FlailerBitmapChunk *)(o))

int32_t flailerobject_get_alpha(struct FlailerObjectChunk *o)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        return flailertext_get_alpha(TEXT(o));
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        return flailerbitmap_get_alpha(BITMAP(o), 0);
    return 0;
}

void flailerobject_set_z(struct FlailerObjectChunk *o, int32_t z)
{
    if (o->Z == z) return;
    o->Z = (int8_t)z;
    o->DirtyFlag = 2;
}

// CalculateWidth and CalculateHeight are the float ones truncated, and the
// text cases truncate GetScaledWidth and GetScaledHeight the same way.
int32_t flailerobject_get_width(struct FlailerObjectChunk *o)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT
        || o->ObjectType == FLAILER_TYPE_BITMAP)
        return ee_trunc_w(flailerobject_get_width_float(o));
    return 0;
}

int32_t flailerobject_get_height(struct FlailerObjectChunk *o)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT
        || o->ObjectType == FLAILER_TYPE_BITMAP)
        return ee_trunc_w(flailerobject_get_height_float(o));
    return 0;
}

float flailerobject_get_width_float(struct FlailerObjectChunk *o)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        return gFlailerTextScaledWidthFn ? gFlailerTextScaledWidthFn(TEXT(o))
                                         : 0.0f;
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        return flailerbitmap_width_float(BITMAP(o));
    return 0.0f;
}

float flailerobject_get_height_float(struct FlailerObjectChunk *o)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        return gFlailerTextScaledHeightFn
             ? gFlailerTextScaledHeightFn(TEXT(o)) : 0.0f;
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        return flailerbitmap_height_float(BITMAP(o));
    return 0.0f;
}

void flailerobject_set_alpha(struct FlailerObjectChunk *o, int32_t a)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        flailertext_set_alpha(TEXT(o), a);
    else if (o->ObjectType == FLAILER_TYPE_BITMAP)
        flailerbitmap_set_alpha(BITMAP(o), a, FLAILER_ALL_CORNERS);
}

void flailerobject_set_rotation(struct FlailerObjectChunk *o, float r)
{
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        flailerbitmap_set_rotation(BITMAP(o), r);
}

// The byte is stored whatever it was; only hiding lets the strip go.
void flailerobject_set_visibility(struct FlailerObjectChunk *o, int32_t v)
{
    o->Visibility = (int8_t)v;
    if (v == FLAILER_OBJECT_INVISIBLE) flailerobject_delete_strip(o);
}

void flailerobject_set_color(struct FlailerObjectChunk *o, const bVector4 *c)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        flailertext_set_color_vector(TEXT(o), c);
    else if (o->ObjectType == FLAILER_TYPE_BITMAP)
        flailerbitmap_set_color_vector(BITMAP(o), c);
}

void flailerobject_set_scale_x(struct FlailerObjectChunk *o, float sx)
{
    if (o->ScaleX == sx) return;
    o->ScaleX = sx;
    o->DirtyFlag = 3;
}

void flailerobject_set_scale_y(struct FlailerObjectChunk *o, float sy)
{
    if (o->ScaleY == sy) return;
    o->ScaleY = sy;
    o->DirtyFlag = 3;
}

static bool texture_size(struct FlailerBitmapChunk *b, int32_t *w,
                         int32_t *h)
{
    *w = *h = 0;
    return gFlailerBitmapTextureSizeFn != NULL
        && gFlailerBitmapTextureSizeFn(b, w, h);
}

// A text object's SetWidth and SetHeight are empty.
void flailerobject_set_width(struct FlailerObjectChunk *o, float w)
{
    int32_t tw, th;
    if (o->ObjectType != FLAILER_TYPE_BITMAP) return;
    if (!texture_size(BITMAP(o), &tw, &th)) return;
    flailerobject_set_scale_x(o, w / (float)tw);
}

void flailerobject_set_height(struct FlailerObjectChunk *o, float h)
{
    int32_t tw, th;
    if (o->ObjectType != FLAILER_TYPE_BITMAP) return;
    if (!texture_size(BITMAP(o), &tw, &th)) return;
    flailerobject_set_scale_y(o, h / (float)th);
}

// The text's (0x00140fa8) works from its alignment, the half sizes being
// the scaled ones over twice the scale. FORMAT_LEFT, here and nowhere else
// tested, moves both edges; CENTER only Y, its X being the middle already;
// RIGHT moves X the other way, and moves Y by ScaleX where the others use
// ScaleY -- retail's, kept. With none of the three it only scales.
// DirtyFlag is 3 whether or not anything changes.
static void text_scale_about_center(struct FlailerTextChunk *t, float s)
{
    struct FlailerObjectChunk *o = &t->Object;
    float    hw, hh;
    uint32_t f;

    o->DirtyFlag = 3;
    hw = flailerobject_get_width_float(o) / (o->ScaleX + o->ScaleX);
    hh = flailerobject_get_height_float(o) / (o->ScaleY + o->ScaleY);
    f = t->FormatOptions;
    if (f & BUI_FMT_LEFT) {
        o->Y = o->Y + hh * (o->ScaleY - s);
        o->X = o->X + hw * (o->ScaleX - s);
    } else if (f & BUI_FMT_CENTER) {
        o->Y = o->Y + hh * (o->ScaleY - s);
    } else if (f & BUI_FMT_RIGHT) {
        o->Y = o->Y + hh * (o->ScaleX - s);
        o->X = o->X - hw * (o->ScaleX - s);
    }
    o->ScaleY = s;
    o->ScaleX = s;
}

// The bitmap's (0x00141588): half the texture each way.
static void bitmap_scale_about_center(struct FlailerBitmapChunk *b, float s)
{
    struct FlailerObjectChunk *o = &b->Object;
    int32_t tw, th;
    float   dx, dy;

    o->DirtyFlag = 3;
    texture_size(b, &tw, &th);
    dx = (float)tw * 0.5f * (o->ScaleX - s);
    dy = (float)th * 0.5f * (o->ScaleY - s);
    o->ScaleY = s;
    o->ScaleX = s;
    o->X = o->X + dx;
    o->Y = o->Y + dy;
}

void flailerobject_scale_about_center(struct FlailerObjectChunk *o, float s)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        text_scale_about_center(TEXT(o), s);
    else if (o->ObjectType == FLAILER_TYPE_BITMAP)
        bitmap_scale_about_center(BITMAP(o), s);
}

// Both halves add half the *width*: the height is asked for and dropped.
// Retail's own, and kept -- the callers have been placed by it.
void flailerobject_get_center(struct FlailerObjectChunk *o, float *x,
                              float *y)
{
    float halfW = flailerobject_get_width_float(o);
    float l, t;

    (void)flailerobject_get_height_float(o);
    flailerobject_get_top_left(o, &l, &t);
    halfW = halfW * 0.5f;
    *x = l + halfW;
    flailerobject_get_top_left(o, &l, &t);
    *y = t + halfW;
}

void flailerobject_set_center_x(struct FlailerObjectChunk *o, float x)
{
    flailerobject_set_top_left_x(
        o, x - flailerobject_get_width_float(o) * 0.5f);
}

void flailerobject_set_center_y(struct FlailerObjectChunk *o, float y)
{
    flailerobject_set_top_left_y(
        o, y - flailerobject_get_height_float(o) * 0.5f);
}

// A text object's X is where its alignment puts it: the right edge for
// FORMAT_RIGHT, the middle for FORMAT_CENTER, which wins when both are set.
void flailerobject_get_top_left(struct FlailerObjectChunk *o, float *x,
                                float *y)
{
    if (o->ObjectType == FLAILER_TYPE_TEXT) {
        float    w = flailerobject_get_width_float(o);
        uint32_t f = TEXT(o)->FormatOptions;
        if (f & BUI_FMT_CENTER)     *x = o->X - w * 0.5f;
        else if (f & BUI_FMT_RIGHT) *x = o->X - w;
        else                        *x = o->X;
    } else {
        *x = o->X;
    }
    *y = o->Y;
}

void flailerobject_set_top_left_x(struct FlailerObjectChunk *o, float x)
{
    if (o->X == x) return;
    o->X = x;
    o->DirtyFlag = 4;
}

void flailerobject_set_top_left_y(struct FlailerObjectChunk *o, float y)
{
    if (o->Y == y) return;
    o->Y = y;
    o->DirtyFlag = 4;
}

void flailerobject_set_clip_to_poly(struct FlailerObjectChunk *o,
                                    uint32_t poly)
{
    if (o->ClipToPoly == poly) return;
    o->DirtyFlag = 4;
    o->ClipToPoly = poly;
    if (o->ObjectType == FLAILER_TYPE_TEXT)
        flailertext_set_format_options(TEXT(o), BUI_FMT_CLIP);
}

// On the PS2 a strip the renderer is still drawing is only marked, and any
// other is unlinked and destroyed. No strip is built here.
void flailerobject_delete_strip(struct FlailerObjectChunk *o)
{
    if (o->pFlailerStrip == 0) return;
    o->pFlailerStrip = 0;
}

// -------------------------------------------------------- FlailerTextChunk

void flailertext_set_format_options(struct FlailerTextChunk *t, uint32_t f)
{
    t->Object.DirtyFlag = 5;
    t->FormatOptions |= f;
}

void flailertext_clear_format_options(struct FlailerTextChunk *t, uint32_t f)
{
    t->Object.DirtyFlag = 5;
    t->FormatOptions &= ~f;
}

// The alpha stays the chunk's; SetAlpha is how it changes.
void flailertext_set_color(struct FlailerTextChunk *t, uint32_t c)
{
    uint32_t v = (t->Color & 0xff000000u) | (c & 0x00ffffffu);
    if (v == t->Color) return;
    t->Color = v;
    t->Object.DirtyFlag = 7;
}

// Retail copies MaxChars bytes from `s` whatever its length, the bytes past
// its end included, and then cuts at MaxChars - 1. Only the characters up
// to the NUL are ever read back, so the copy stops there. Setting a string
// drops the LanguageID: the text is now its own.
void flailertext_set_string(struct FlailerTextChunk *t, const char *s)
{
    int32_t i;

    if (strcmp(s, t->String) == 0) return;
    t->Object.DirtyFlag = 5;
    for (i = 0; i < t->MaxChars && s[i] != 0; i++) t->String[i] = s[i];
    if (i < t->MaxChars) t->String[i] = 0;
    if (t->MaxChars > 0) t->String[t->MaxChars - 1] = 0;
    t->LanguageID = 0;
}

// The string itself is looked up as it is drawn.
void flailertext_update_language_text(struct FlailerTextChunk *t)
{
    t->Object.DirtyFlag = 5;
}

void flailertext_set_language_id(struct FlailerTextChunk *t, uint32_t id)
{
    if (t->LanguageID == id) return;
    t->LanguageID = id;
    t->Object.DirtyFlag = 5;
    t->String[0] = 0;
    flailertext_update_language_text(t);
}

void flailertext_set_alpha(struct FlailerTextChunk *t, int32_t a)
{
    uint32_t v = (t->Color & 0x00ffffffu) | ((uint32_t)a << 24);
    if (v == t->Color) return;
    t->Color = v;
    t->Object.DirtyFlag = 6;
}

int32_t flailertext_get_alpha(struct FlailerTextChunk *t)
{
    return (int32_t)(t->Color >> 24);
}

void flailertext_set_color_vector(struct FlailerTextChunk *t,
                                  const bVector4 *c)
{
    uint32_t r = (uint32_t)ee_trunc_w(c->x);
    uint32_t g = (uint32_t)ee_trunc_w(c->y);
    uint32_t b = (uint32_t)ee_trunc_w(c->z);
    int32_t  a = ee_trunc_w(c->w);
    flailertext_set_color(t, r | g << 8 | b << 16);
    flailertext_set_alpha(t, a);
}

// ------------------------------------------------------ FlailerBitmapChunk

// DirtyFlag is stamped whether or not anything changes. Retail indexes the
// corners unchecked; a corner outside -1..3 is a caller's bug, and here it
// changes nothing.
void flailerbitmap_set_alpha(struct FlailerBitmapChunk *b, int32_t a,
                             int32_t corner)
{
    uint32_t top = (uint32_t)a << 24;
    int      i;

    b->Object.DirtyFlag = 6;
    if (corner == FLAILER_ALL_CORNERS) {
        for (i = 0; i < 4; i++)
            b->Colors[i] = (b->Colors[i] & 0x00ffffffu) | top;
        return;
    }
    if (corner >= 0 && corner < 4)
        b->Colors[corner] = (b->Colors[corner] & 0x00ffffffu) | top;
}

void flailerbitmap_set_rotation(struct FlailerBitmapChunk *b, float r)
{
    int32_t v = ee_trunc_w(r);
    if (b->Object.Rotation == v) return;
    b->Object.Rotation = v;
    b->Object.DirtyFlag = 9;
}

// All four corners take the colour, alpha and all; only the first is asked
// whether that is a change.
void flailerbitmap_set_color(struct FlailerBitmapChunk *b, uint32_t c)
{
    if (b->Colors[0] != c) b->Object.DirtyFlag = 7;
    b->Colors[3] = c;
    b->Colors[0] = c;
    b->Colors[1] = c;
    b->Colors[2] = c;
}

void flailerbitmap_set_color_vector(struct FlailerBitmapChunk *b,
                                    const bVector4 *c)
{
    uint32_t r = (uint32_t)ee_trunc_w(c->x);
    uint32_t g = (uint32_t)ee_trunc_w(c->y);
    uint32_t bl = (uint32_t)ee_trunc_w(c->z);
    int32_t  a = ee_trunc_w(c->w);
    flailerbitmap_set_color(b, r | g << 8 | bl << 16);
    flailerbitmap_set_alpha(b, a, FLAILER_ALL_CORNERS);
}

void flailerbitmap_change_texture(struct FlailerBitmapChunk *b,
                                  uint32_t texture)
{
    b->TextureHash = texture;
    b->Object.DirtyFlag = 10;
    b->pTextureInfo = 0;
}

int32_t flailerbitmap_get_alpha(struct FlailerBitmapChunk *b, int32_t corner)
{
    return (int32_t)(b->Colors[corner] >> 24);
}

float flailerbitmap_width_float(struct FlailerBitmapChunk *b)
{
    int32_t w, h;
    if (!texture_size(b, &w, &h)) return 0.0f;
    return (float)w * b->Object.ScaleX;
}

float flailerbitmap_height_float(struct FlailerBitmapChunk *b)
{
    int32_t w, h;
    if (!texture_size(b, &w, &h)) return 0.0f;
    return (float)h * b->Object.ScaleY;
}

// ---------------------------------------------------------------- wrappers

// FlailerPrintf's two buffers, 0x00333f80 and 0x00334000, 128 bytes each.
// bVSPrintf has no bound and runs on into whatever follows; here a longer
// result is cut, and its length is still the whole one.
static char sPrintfBuffer[128];
static char sPrintfChunkBuffer[128];

int32_t flailer_printf(uint32_t screen, uint32_t object, const char *fmt,
                       ...)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);
    va_list ap;
    int     n;

    if (o == NULL) return 0;
    va_start(ap, fmt);
    n = vsnprintf(sPrintfBuffer, sizeof(sPrintfBuffer), fmt, ap);
    va_end(ap);
    flailertext_set_string(TEXT(o), sPrintfBuffer);
    return n;
}

int32_t flailer_printf_chunk(struct FlailerTextChunk *t, const char *fmt, ...)
{
    va_list ap;
    int     n;

    if (t == NULL) return 0;
    va_start(ap, fmt);
    n = vsnprintf(sPrintfChunkBuffer, sizeof(sPrintfChunkBuffer), fmt, ap);
    va_end(ap);
    flailertext_set_string(t, sPrintfChunkBuffer);
    return n;
}

void flailer_set_text_color(uint32_t screen, uint32_t object, uint32_t c)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);
    if (o) flailertext_set_color(TEXT(o), c);
}

void flailer_set_text_format_option(uint32_t screen, uint32_t object,
                                    uint32_t f)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);
    if (o) flailertext_set_format_options(TEXT(o), f);
}

void flailer_clear_text_format_option(uint32_t screen, uint32_t object,
                                      uint32_t f)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);
    if (o) flailertext_clear_format_options(TEXT(o), f);
}

void flailer_get_top_left_position(uint32_t screen, uint32_t object,
                                   float *x, float *y)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) {
        flailerobject_get_top_left(o, x, y);
        return;
    }
    *y = 0.0f;
    *x = 0.0f;
}

void flailer_get_top_left_position_int(uint32_t screen, uint32_t object,
                                       int32_t *x, int32_t *y)
{
    float fx, fy;
    flailer_get_top_left_position(screen, object, &fx, &fy);
    *x = ee_trunc_w(fx);
    *y = ee_trunc_w(fy);
}

float flailer_get_top_left_x(uint32_t screen, uint32_t object)
{
    float x, y;
    flailer_get_top_left_position(screen, object, &x, &y);
    return x;
}

float flailer_get_top_left_y(uint32_t screen, uint32_t object)
{
    float x, y;
    flailer_get_top_left_position(screen, object, &x, &y);
    return y;
}

int32_t flailer_get_width(uint32_t screen, uint32_t object)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    return o ? flailerobject_get_width(o) : 0;
}

int32_t flailer_get_height(uint32_t screen, uint32_t object)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    return o ? flailerobject_get_height(o) : 0;
}

void flailer_set_width(uint32_t screen, uint32_t object, float w)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_width(o, w);
}

void flailer_set_height(uint32_t screen, uint32_t object, float h)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_height(o, h);
}

// The sizes are asked first; the corner is looked up again, by hash.
void flailer_get_bounding_box(uint32_t screen, uint32_t object,
                              int32_t *left, int32_t *top, int32_t *right,
                              int32_t *bottom)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    int32_t w, h, x = 0, y = 0;

    if (o == NULL) return;
    w = flailerobject_get_width(o);
    h = flailerobject_get_height(o);
    flailer_get_top_left_position_int(screen, object, &x, &y);
    *left   = x;
    *right  = x + w;
    *top    = y;
    *bottom = y + h;
}

void flailer_set_clip_to_poly(uint32_t screen, uint32_t object,
                              uint32_t poly)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_clip_to_poly(o, poly);
}

void flailer_set_top_left_position(uint32_t screen, uint32_t object,
                                   int32_t x, int32_t y)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o == NULL) return;
    flailerobject_set_top_left_x(o, (float)x);
    flailerobject_set_top_left_y(o, (float)y);
}

void flailer_set_z(uint32_t screen, uint32_t object, int32_t z)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_z(o, z);
}

void flailer_set_top_left_y(uint32_t screen, uint32_t object, int32_t y)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_top_left_y(o, (float)y);
}

void flailer_set_top_left_x(uint32_t screen, uint32_t object, int32_t x)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_top_left_x(o, (float)x);
}

void flailer_get_scale(uint32_t screen, uint32_t object, float *sx,
                       float *sy)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o == NULL) return;
    *sx = o->ScaleX;
    *sy = o->ScaleY;
}

void flailer_set_scale_x(uint32_t screen, uint32_t object, float sx)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_scale_x(o, sx);
}

void flailer_set_scale_y(uint32_t screen, uint32_t object, float sy)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_scale_y(o, sy);
}

void flailer_scale_about_center(uint32_t screen, uint32_t object, float s)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_scale_about_center(o, s);
}

// With the sizes truncated, both asked before either edge moves.
void flailer_set_center(uint32_t screen, uint32_t object, int32_t x,
                        int32_t y)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    int32_t w, h;

    if (o == NULL) return;
    w = flailerobject_get_width(o);
    h = flailerobject_get_height(o);
    flailerobject_set_top_left_x(o, (float)x - (float)w * 0.5f);
    flailerobject_set_top_left_y(o, (float)y - (float)h * 0.5f);
}

void flailer_set_center_y(uint32_t screen, uint32_t object, int32_t y)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o == NULL) return;
    flailerobject_set_top_left_y(
        o, (float)y - (float)flailerobject_get_height(o) * 0.5f);
}

void flailer_set_center_x(uint32_t screen, uint32_t object, int32_t x)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o == NULL) return;
    flailerobject_set_top_left_x(
        o, (float)x - (float)flailerobject_get_height(o) * 0.5f);
}

void flailer_get_center(uint32_t screen, uint32_t object, int32_t *x,
                        int32_t *y)
{
    int32_t l = 0, t = 0, r = 0, b = 0;

    flailer_get_bounding_box(screen, object, &l, &t, &r, &b);
    *y = t + (b - t) / 2;
    *x = l + (r - l) / 2;
}

int32_t flailer_get_center_y(uint32_t screen, uint32_t object)
{
    int32_t x, y;
    flailer_get_center(screen, object, &x, &y);
    return y;
}

int32_t flailer_get_center_x(uint32_t screen, uint32_t object)
{
    int32_t x, y;
    flailer_get_center(screen, object, &x, &y);
    return x;
}

int32_t flailer_get_alpha(uint32_t screen, uint32_t object)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    return o ? flailerobject_get_alpha(o) : 0;
}

void flailer_set_alpha(uint32_t screen, uint32_t object, int32_t a)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_alpha(o, a);
}

void flailer_set_rotation(uint32_t screen, uint32_t object, float r)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_rotation(o, r);
}

void flailer_set_visibility(uint32_t screen, uint32_t object, int32_t v)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_visibility(o, v);
}

void flailer_set_language_id(uint32_t screen, uint32_t object, uint32_t id)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);
    if (o) flailertext_set_language_id(TEXT(o), id);
}

void flailer_set_object_color(uint32_t screen, uint32_t object,
                              const bVector4 *c)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_ANY);
    if (o) flailerobject_set_color(o, c);
}

void flailer_change_texture(uint32_t screen, uint32_t object,
                            uint32_t texture)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_BITMAP);
    if (o) flailerbitmap_change_texture(BITMAP(o), texture);
}

// The group walks below go through the screen's list the other way, from
// its last object; each object is set on its own, so the order is not
// seen.
static BUIScreen *group_screen(uint32_t screen, BUI **ui)
{
    struct FlailerScreenChunk *s = flailer_find_screen(screen);
    return s ? flailer_screen_of(s, ui) : NULL;
}

void flailer_set_group_position(uint32_t screen, uint32_t group,
                                uint32_t anchor, float x, float y)
{
    struct FlailerObjectChunk *a =
        flailer_find_object(screen, anchor, FLAILER_TYPE_ANY);
    BUI       *ui = NULL;
    BUIScreen *s;
    float      dx, dy;
    uint32_t   i;

    if (a == NULL) return;
    dy = y - a->Y;
    dx = x - a->X;
    s = group_screen(screen, &ui);
    if (s == NULL) return;
    for (i = s->count; i-- > 0;) {
        struct FlailerObjectChunk *o = object_chunk(ui, s->first + i);
        if (o->GroupHash != group) continue;
        flailerobject_set_top_left_x(o, o->X + dx);
        flailerobject_set_top_left_y(o, o->Y + dy);
    }
}

void flailer_offset_group(uint32_t screen, uint32_t group, int32_t dx,
                          int32_t dy)
{
    BUI       *ui = NULL;
    BUIScreen *s  = group_screen(screen, &ui);
    uint32_t   i;

    if (s == NULL) return;
    for (i = s->count; i-- > 0;) {
        struct FlailerObjectChunk *o = object_chunk(ui, s->first + i);
        if (o->GroupHash != group) continue;
        flailerobject_set_top_left_x(o, o->X + (float)dx);
        flailerobject_set_top_left_y(o, o->Y + (float)dy);
    }
}

void flailer_set_group_render_on_poly(uint32_t screen, uint32_t group,
                                      uint32_t poly)
{
    BUI       *ui = NULL;
    BUIScreen *s  = group_screen(screen, &ui);
    uint32_t   i;

    if (s == NULL) return;
    for (i = s->count; i-- > 0;) {
        struct FlailerObjectChunk *o = object_chunk(ui, s->first + i);
        if (o->GroupHash == group) o->RenderOnPoly = poly;
    }
}

// Retail looks the first one up once before its loop and drops the answer;
// that search is still made, for the screen order it leaves.
void flailer_set_group_visibility(uint32_t screen, uint32_t group, int32_t v)
{
    struct FlailerObjectChunk *o;

    (void)flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY, NULL);
    for (o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                          NULL);
         o != NULL;
         o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY, o))
        o->Visibility = (int8_t)v;
}

void flailer_set_group_alpha(uint32_t screen, uint32_t group, int32_t a)
{
    struct FlailerObjectChunk *o;

    for (o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                          NULL);
         o != NULL;
         o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY, o))
        flailerobject_set_alpha(o, a);
}

// The texture's own height is the bitmap's scaled one over its ScaleY.
void flailer_make_vertical_line(uint32_t screen, uint32_t object, float y1,
                                float y2)
{
    struct FlailerObjectChunk *o =
        flailer_find_object(screen, object, FLAILER_TYPE_BITMAP);
    float unit, lo = y1, hi = y2;

    if (o == NULL) return;
    unit = flailerbitmap_height_float(BITMAP(o)) / o->ScaleY;
    if (y2 < y1) {
        lo = y2;
        hi = y1;
    }
    flailerobject_set_top_left_y(o, lo);
    flailerobject_set_scale_y(o, (hi - lo) / unit);
}

// Both are looked up before either is tested.
void flailer_make_vertical_line_between(uint32_t screen, uint32_t object,
                                        uint32_t top, uint32_t bottom)
{
    struct FlailerObjectChunk *a =
        flailer_find_object(screen, top, FLAILER_TYPE_ANY);
    struct FlailerObjectChunk *b =
        flailer_find_object(screen, bottom, FLAILER_TYPE_ANY);

    if (a == NULL || b == NULL) return;
    flailer_make_vertical_line(screen, object,
                               (a->Y + flailerobject_get_height_float(a))
                                   + 4.0f,
                               b->Y + 3.0f);
}
