#include "uirender.h"

#ifdef __3DS__
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// RenderHelpCharacter (0x0013f9b8) hashes this name and calls FindFont.
#define HELP_FONT_HASH 0xb85de386u   // bStringHash("BUTTONSOUT")

// The 18-byte table at 0x002e8a10: help character 0x80+i draws this glyph.
static const uint8_t kHelpGlyph[UIR_HELP_COUNT] = {
    'a', 'b', 'd', 'e', 'f', 'g', 'i', 'j', 'h',
    'k', 'n', 'o', 'l', 'm', 'c', 'c', 'c', 'c',
};

// Font::FixedWidthCell is GetWidestCharacter(this, "1234567890:- ") -- the
// widest mAdvance among those characters (Font::Font, 0x0013dd60).
static const char kFixedWidthSet[] = "1234567890:- ";

// gp-relative globals the renderer reads. All are initialised data and
// nothing on this disc writes any of them, so they are constants here.
//   KerningEnabled           1
//   RenderFixedWidthStrings  1
//   TranslationEnable        1
//   ColonCrapola             0  -- so ':' and '.' get a fixed cell like every
//                                  other character; the proportional path
//                                  behind that flag is dead code.
#define KERNING_ENABLED 1
#define COLON_CRAPOLA   0

// ---------------------------------------------------------------------------
// Bundles
// ---------------------------------------------------------------------------

void uirender_init(UIRenderer* r, float targetW, float targetH)
{
    memset(r, 0, sizeof(*r));
    r->targetW = targetW;
    r->targetH = targetH;
}

static uint8_t* read_file(const char* path, size_t* outLen)
{
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len <= 0) { fclose(f); return NULL; }
    uint8_t* buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, f) != (size_t)len) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *outLen = (size_t)len;
    return buf;
}

static float widest_of(const BFont* font, const char* set)
{
    float widest = 0.0f;
    for (const char* s = set; *s; s++) {
        BGlyph g;
        if (bfont_glyph(font, (unsigned char)*s, &g) && g.advance > widest)
            widest = g.advance;
    }
    return widest;
}

static BChunkAction collect_font(uint32_t type, const uint8_t* payload,
                                 uint32_t size, int depth, void* user)
{
    (void)depth;
    UIRenderer* r = (UIRenderer*)user;
    if (BCHUNK_IS_CONTAINER(type)) return BCHUNK_ENTER;
    if (type != BFONT_CHUNK || r->numFonts >= UIR_MAX_FONTS)
        return BCHUNK_SKIP;

    UIFont* f = &r->fonts[r->numFonts];
    if (!bfont_parse(&f->font, payload, size)) return BCHUNK_SKIP;
    // FONT_IMPACTSMALL ships in two bundles, byte-identical. Keep the first.
    for (int i = 0; i < r->numFonts; i++)
        if (r->fonts[i].hash == f->font.hash) return BCHUNK_SKIP;
    f->hash      = f->font.hash;
    f->sheet     = -1;
    f->fixedCell = widest_of(&f->font, kFixedWidthSet);
    r->numFonts++;
    return BCHUNK_SKIP;
}

bool uirender_add_bundle(UIRenderer* r, const char* path)
{
    if (r->numBundles >= UIR_MAX_BUNDLES) return false;
    UIBundle* b = &r->bundles[r->numBundles];
    memset(b, 0, sizeof(*b));
    b->data = read_file(path, &b->len);
    if (!b->data) return false;

    b->hasUI = bui_open(&b->ui, b->data, 0, b->len);
    r->numBundles++;
    bchunk_walk(b->data, 0, b->len, collect_font, r);
    return true;
}

bool uirender_set_language(UIRenderer* r, const char* path)
{
    size_t   len  = 0;
    uint8_t* data = read_file(path, &len);
    if (!data) return false;
    uint32_t       size    = 0;
    const uint8_t* payload = bchunk_find(data, 0, len, LANGTAB_CHUNK, &size);
    if (!payload || !langtab_parse(&r->lang, payload, size)) {
        free(data);
        return false;
    }
    free(r->langData);
    r->langData = data;
    r->langLen  = len;
    r->hasLang  = true;
    return true;
}

void uirender_free(UIRenderer* r)
{
    for (int i = 0; i < r->numTextures; i++)
        if (r->textures[i].valid) C3D_TexDelete(&r->textures[i].tex);
    for (int i = 0; i < r->numBundles; i++) {
        if (r->bundles[i].hasUI) bui_close(&r->bundles[i].ui);
        free(r->bundles[i].data);
    }
    free(r->langData);
    memset(r, 0, sizeof(*r));
}

BUIScreen* uirender_find_screen(UIRenderer* r, uint32_t nameHash, BUI** outUI)
{
    for (int i = 0; i < r->numBundles; i++) {
        if (!r->bundles[i].hasUI) continue;
        BUIScreen* s = bui_find_screen(&r->bundles[i].ui, nameHash);
        if (s) {
            if (outUI) *outUI = &r->bundles[i].ui;
            return s;
        }
    }
    return NULL;
}

uint32_t uirender_screen_count(const UIRenderer* r)
{
    uint32_t n = 0;
    for (int i = 0; i < r->numBundles; i++)
        if (r->bundles[i].hasUI) n += r->bundles[i].ui.numScreens;
    return n;
}

BUIScreen* uirender_screen_at(UIRenderer* r, uint32_t index, BUI** outUI)
{
    for (int i = 0; i < r->numBundles; i++) {
        if (!r->bundles[i].hasUI) continue;
        BUI* ui = &r->bundles[i].ui;
        if (index < ui->numScreens) {
            if (outUI) *outUI = ui;
            return &ui->screens[index];
        }
        index -= ui->numScreens;
    }
    return NULL;
}

// ---------------------------------------------------------------------------
// Texture cache
// ---------------------------------------------------------------------------

// Decodes and uploads on first use. A miss is cached as an invalid entry so a
// screen full of one missing hash does not rescan every bundle every frame.
static int find_texture(UIRenderer* r, uint32_t hash)
{
    for (int i = 0; i < r->numTextures; i++)
        if (r->textures[i].hash == hash) return i;
    if (r->numTextures >= UIR_MAX_TEXTURES) return -1;

    UITexture* slot = &r->textures[r->numTextures];
    memset(slot, 0, sizeof(*slot));
    slot->hash = hash;
    int index = r->numTextures++;

    for (int i = 0; i < r->numBundles; i++) {
        const UIBundle* b = &r->bundles[i];
        TexPack tp;
        for (uint32_t n = 0; texpack_open_nth(&tp, b->data, 0, b->len, n); n++) {
            TexInfo ti;
            if (!texpack_find(&tp, hash, &ti)) continue;
            if (!texpack_upload(&tp, &ti, 0, &slot->tex)) continue;
            slot->w     = ti.width;
            slot->h     = ti.height;
            slot->valid = true;
            return index;
        }
    }
    r->missingTextures++;
    return index;
}

static UIFont* find_font(UIRenderer* r, uint32_t hash)
{
    for (int i = 0; i < r->numFonts; i++)
        if (r->fonts[i].hash == hash) return &r->fonts[i];
    r->missingFonts++;
    return NULL;
}

// A font's glyph sheet is a texture of the same name, so the same hash.
static UITexture* font_sheet(UIRenderer* r, UIFont* f)
{
    if (f->sheet < 0) f->sheet = find_texture(r, f->hash);
    if (f->sheet < 0) return NULL;
    UITexture* t = &r->textures[f->sheet];
    return t->valid ? t : NULL;
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

typedef struct {
    float scale;          // 640x480 -> the render target
    float originX, originY;
    float alpha;          // the renderer's global fade
} UIView;

// A sub-rectangle of a texture, in pixels, with row 0 at the top. v is
// flipped because citro2d's convention puts the first row in memory at v = 1;
// vp6/vp6_display.c builds its subtex the same way over the same upload path,
// and that one is verified on hardware.
static void subtex_from_pixels(Tex3DS_SubTexture* st, float texW, float texH,
                               float x, float y, float w, float h)
{
    st->width  = (uint16_t)w;
    st->height = (uint16_t)h;
    st->left   = x / texW;
    st->right  = (x + w) / texW;
    st->top    = 1.0f - y / texH;
    st->bottom = 1.0f - (y + h) / texH;
}

// PS2 colours are GS scale (0x80 is full intensity, 0x81..0xff is the
// over-bright range), stored r,g,b,a low byte first. C2D_TintMult multiplies
// the tint by the texel, which is what the GS does with a gouraud colour.
static uint32_t tint_color(uint32_t rgba, float alpha)
{
    uint8_t c[4];
    bui_color(rgba, c);
    float a = (float)c[3] * alpha;
    if (a > 255.0f) a = 255.0f;
    if (a < 0.0f)   a = 0.0f;
    return C2D_Color32(c[0], c[1], c[2], (uint8_t)a);
}

static void fill_tint(C2D_ImageTint* tint, const uint32_t rgba[4], float alpha)
{
    // GouradColors run around the quad; C2D wants top-left, top-right,
    // bottom-left, bottom-right.
    static const int kOrder[4] = { 0, 1, 3, 2 };
    for (int i = 0; i < 4; i++)
        C2D_SetImageTint(tint, (C2D_Corner)i,
                         tint_color(rgba[kOrder[i]], alpha), 1.0f);
}

void uirender_override_texture(UIRenderer* r, uint32_t hash, C3D_Tex* tex,
                               uint16_t w, uint16_t h)
{
    int idx = find_texture(r, hash);
    if (idx < 0) return;
    r->textures[idx].override  = tex;
    r->textures[idx].overrideW = w;
    r->textures[idx].overrideH = h;
}

static void draw_bitmap(UIRenderer* r, const BUIObject* o, const UIView* v)
{
    int idx = find_texture(r, o->textureHash);
    if (idx < 0) return;
    UITexture* t = &r->textures[idx];
    if (!t->override && !t->valid) return;

    // An override stands in for the bundle's texture at its own size, so a
    // movie plane scales by the movie's dimensions rather than the blank
    // buffer's -- which happen to match here, and would not have to.
    C3D_Tex* tex = t->override ? t->override : &t->tex;
    uint16_t tw  = t->override ? t->overrideW : t->w;
    uint16_t th  = t->override ? t->overrideH : t->h;

    // RenderSingleFlailerBitmap (0x00140538) takes the size from the
    // TextureInfo and truncates: (int)(width * ScaleX), (int)(height * ScaleY).
    float w = (float)(int)((float)tw * o->scaleX);
    float h = (float)(int)((float)th * o->scaleY);
    if (w <= 0.0f || h <= 0.0f) return;

    // UVs are four corners, but every one on disc is an axis-aligned rect.
    float u0 = o->uv[0], v0 = o->uv[1], u1 = o->uv[0], v1 = o->uv[1];
    for (int i = 1; i < 4; i++) {
        if (o->uv[i * 2 + 0] < u0) u0 = o->uv[i * 2 + 0];
        if (o->uv[i * 2 + 0] > u1) u1 = o->uv[i * 2 + 0];
        if (o->uv[i * 2 + 1] < v0) v0 = o->uv[i * 2 + 1];
        if (o->uv[i * 2 + 1] > v1) v1 = o->uv[i * 2 + 1];
    }
    // The UV rect is in image pixels, but the allocation is padded up to a
    // power of two (texpack_upload), so it is the padded size that turns
    // pixels into UVs.
    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)tex->width, (float)tex->height,
                       u0 * (float)tw, v0 * (float)th,
                       (u1 - u0) * (float)tw, (v1 - v0) * (float)th);

    C2D_ImageTint tint;
    fill_tint(&tint, o->colors, v->alpha);

    C2D_Image img = { tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = v->originX + o->x * v->scale;
    p.pos.y = v->originY + o->y * v->scale;
    p.pos.w = w * v->scale;
    p.pos.h = h * v->scale;
    if (o->animation == BUI_ROTATE_CENTER && o->rotation) {
        p.center.x = p.pos.w * 0.5f;
        p.center.y = p.pos.h * 0.5f;
        p.pos.x += p.center.x;
        p.pos.y += p.center.y;
        p.angle = (float)o->rotation * 3.14159265f / 180.0f;
    }
    C2D_DrawImage(img, &p, &tint);
}

// The string a text object actually draws. LanguageID wins over the inline
// placeholder whenever it is set, which is why the main menu ships 'Speed'
// where the game draws 'World Racing'.
static const char* object_text(UIRenderer* r, const BUIObject* o,
                               size_t* outLen)
{
    if (o->languageID && r->hasLang) {
        const char* s = langtab_get(&r->lang, (int32_t)o->languageID, outLen);
        if (s) return s;
        r->missingStrings++;
    }
    size_t n = 0;
    while (n < o->maxChars && o->string[n]) n++;
    *outLen = n;
    return o->string;
}

// GetScaledWidth (0x0013e8b0): sum the advances, then scale once.
static float measure(UIFont* f, const char* s, size_t len, float scaleX,
                     bool fixedWidth)
{
    if (!fixedWidth) return bfont_measure(&f->font, s, len) * scaleX;

    // GetFixedWidthStringWidth (0x0013faa8): one cell per character that has
    // a glyph. ColonCrapola would give ':' and '.' their own advance instead,
    // but it is 0 in this build and nothing ever writes it.
    float total = 0.0f;
    for (size_t i = 0; i < len; i++) {
        BGlyph g;
        if (!bfont_glyph(&f->font, (unsigned char)s[i], &g)) continue;
        if (COLON_CRAPOLA && (s[i] == ':' || s[i] == '.')) total += g.advance;
        else                                               total += f->fixedCell;
    }
    return total * scaleX;
}

static void draw_glyph(UIRenderer* r, UIFont* f, const BGlyph* g, float x,
                       float y, float w, float h, uint32_t color,
                       const UIView* v)
{
    UITexture* t = font_sheet(r, f);
    if (!t || w <= 0.0f || h <= 0.0f) return;

    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)t->tex.width, (float)t->tex.height,
                       g->posX, g->posY, g->width, g->height);

    C2D_ImageTint tint;
    C2D_PlainImageTint(&tint, tint_color(color, v->alpha), 1.0f);

    C2D_Image img = { &t->tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = v->originX + x * v->scale;
    p.pos.y = v->originY + y * v->scale;
    p.pos.w = w * v->scale;
    p.pos.h = h * v->scale;
    C2D_DrawImage(img, &p, &tint);
}

static void draw_text(UIRenderer* r, const BUIObject* o, const UIView* v)
{
    UIFont* f = find_font(r, o->fontHash);
    if (!f) return;

    size_t      len = 0;
    const char* s   = object_text(r, o, &len);
    if (!s || len == 0) return;

    bool  fixed = (o->format & BUI_FMT_FIXEDWIDTH) != 0;
    float width = measure(f, s, len, o->scaleX, fixed);

    // Render__16FlailerTextChunk (0x0013ff40): right subtracts the whole
    // width, centre subtracts half. Declaration order says otherwise and
    // would right-align every centred label in the game.
    float penX = o->x;
    if (o->format & BUI_FMT_RIGHT)       penX -= width;
    else if (o->format & BUI_FMT_CENTER) penX -= width * 0.5f;

    if (o->format & BUI_FMT_DARKBG) {
        // RenderDarkBackground (0x0013fd80) puts a plain dark quad behind the
        // run. Only 32 objects use it and all of them are left-justified.
        C2D_DrawRectSolid(v->originX + penX * v->scale,
                          v->originY + o->y * v->scale, 0.0f,
                          width * v->scale,
                          f->font.height * o->scaleY * v->scale,
                          C2D_Color32(0, 0, 0, (uint8_t)(160.0f * v->alpha)));
    }

    int prev = -1;
    for (size_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)s[i];

        // 0x80..0x91 are button icons drawn from BUTTONSOUT, not text:
        // IsHelpCharacter (0x0013f9a8) is exactly (u8)(c - 128) < 18.
        if ((unsigned)(ch - UIR_HELP_FIRST) < UIR_HELP_COUNT) {
            UIFont* hf = find_font(r, HELP_FONT_HASH);
            BGlyph  hg;
            if (hf && bfont_glyph(&hf->font, kHelpGlyph[ch - UIR_HELP_FIRST],
                                  &hg)) {
                draw_glyph(r, hf, &hg, penX, o->y + hg.offset * o->scaleY,
                           hg.width * o->scaleX, hg.height * o->scaleY,
                           o->color, v);
                penX += hg.advance * o->scaleX;
            }
            prev = -1;
            continue;
        }

        BGlyph g;
        if (!bfont_glyph(&f->font, ch, &g)) { prev = -1; continue; }

        if (fixed) {
            // RenderStringFixedWidth (0x0013fb78) centres each glyph in a
            // cell of FixedWidthCell and advances by ScaleX * the cell. The
            // centring term is *not* scaled -- the engine adds it to an
            // already-scaled pen -- so this leaves it unscaled too.
            float inset = (f->fixedCell - g.advance) * 0.5f;
            draw_glyph(r, f, &g, penX + inset, o->y + g.offset * o->scaleY,
                       g.width * o->scaleX, g.height * o->scaleY, o->color, v);
            penX += f->fixedCell * o->scaleX;
            prev = -1;
            continue;
        }

        if (KERNING_ENABLED && prev >= 0)
            penX += bfont_kerning(&f->font, prev, ch) * o->scaleX;

        // RenderCharacter (0x0013f698) multiplies the glyph's width by ScaleX
        // *twice* -- mul.s at 0x0013f750 and again at 0x0013f794 -- while the
        // height is scaled once and the pen advances once. That is a shipped
        // bug, and the screens were laid out with it on screen, so it is
        // reproduced here rather than quietly corrected.
        draw_glyph(r, f, &g, penX, o->y + g.offset * o->scaleY,
                   g.width * o->scaleX * o->scaleX, g.height * o->scaleY,
                   o->color, v);
        penX += g.advance * o->scaleX;
        prev = ch;
    }
}

bool uirender_object_bounds(UIRenderer* r, const BUI* ui, uint32_t index,
                            float box[4])
{
    BUIObject o;
    if (!r || !ui || !bui_object(ui, index, &o)) return false;
    if (o.type != BUI_TYPE_BITMAP) return false;

    int idx = find_texture(r, o.textureHash);
    if (idx < 0) return false;
    UITexture* t = &r->textures[idx];
    if (!t->override && !t->valid) return false;

    uint16_t tw = t->override ? t->overrideW : t->w;
    uint16_t th = t->override ? t->overrideH : t->h;
    // The same truncation draw_bitmap() does, because the original takes the
    // size from the TextureInfo and casts.
    box[0] = o.x;
    box[1] = o.y;
    box[2] = o.x + (float)(int)((float)tw * o.scaleX);
    box[3] = o.y + (float)(int)((float)th * o.scaleY);
    return true;
}

void uirender_draw_screen(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                          float alpha)
{
    if (!ui || !screen) return;
    float resX = screen->resX ? (float)screen->resX : 640.0f;
    float resY = screen->resY ? (float)screen->resY : 480.0f;

    UIView v;
    v.scale = r->targetH / resY;
    if (resX * v.scale > r->targetW) v.scale = r->targetW / resX;
    v.originX = (r->targetW - resX * v.scale) * 0.5f;
    v.originY = (r->targetH - resY * v.scale) * 0.5f;
    v.alpha   = alpha;

    C2D_SetTintMode(C2D_TintMult);

    // Z is a layer index, and eDisplayFrame walks the layers in the fixed,
    // mostly descending order spelled out at BUI_LAYER_ORDER. Within one
    // layer the file order is the draw order, because AddFlailerStrip
    // appends to the tail of LayerRenderInfoTable[Z].
    static const uint8_t kOrder[BUI_NUM_LAYERS] = BUI_LAYER_ORDER;
    for (int pass = 0; pass < BUI_NUM_LAYERS; pass++) {
        const int layer = kOrder[pass];
        for (uint32_t i = 0; i < screen->count; i++) {
            BUIObject o;
            if (!bui_object(ui, screen->first + i, &o)) continue;
            if (o.z != layer) continue;
            if (o.visible != BUI_VISIBLE) continue;
            if (o.type == BUI_TYPE_BITMAP)    draw_bitmap(r, &o, &v);
            else if (o.type == BUI_TYPE_TEXT) draw_text(r, &o, &v);
        }
    }
}
#endif  // __3DS__
