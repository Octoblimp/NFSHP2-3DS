#include "uirender.h"

#ifdef __3DS__
#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "epoly.h"
#include "georender.h"
#include "hudtach.h"

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
    // To a 128-byte boundary, as the disc reads a bundle: the track viewer
    // hands GLOBALB's and INGAMEB's texture packs to slot 2 in place, and
    // LoaderTexturePack finds a pack's pixels by rounding an address up to
    // 128, which comes out where texpack.c's file offsets say only if the
    // file starts on one.
    uint8_t* buf = (uint8_t*)memalign(128, (size_t)len);
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

            slot->scrollType = ti.scrollType;
            slot->scrollS    = ti.scrollS;
            slot->scrollT    = ti.scrollT;
            slot->scrollStep = ti.scrollStep;

            // A scrolling coordinate has to wrap, and on the PICA200 it wraps
            // through the whole power-of-two allocation -- so GPU_REPEAT is
            // only the right answer on an axis the image already fills.
            // Both scrolling textures on the disc do fill theirs (ROADLINES
            // is 512 wide and scrolls S, SCREEN_LINES is 256 tall and scrolls
            // T), which is not a coincidence: the GS wrapped the same way.
            // An axis that is padded stays clamped, so a texture authored
            // wrong smears its last row instead of showing the padding.
            if (ti.scrollType) {
                bool repeatS = ti.scrollS != 0.0f
                    && slot->tex.width  == slot->w;
                bool repeatT = ti.scrollT != 0.0f
                    && slot->tex.height == slot->h;
                C3D_TexSetWrap(&slot->tex,
                               repeatS ? GPU_REPEAT : GPU_CLAMP_TO_EDGE,
                               repeatT ? GPU_REPEAT : GPU_CLAMP_TO_EDGE);
            }
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
    // 640x480 -> the render target, and the two axes scale independently.
    // The PS2 drew 4:3 and the 3DS top screen is 400x240, which is 5:3, so
    // fitting the screen inside it preserving aspect -- which is what this
    // used to do -- left 20 px of nothing down each side. Filling the
    // screen instead is what was asked for. Nothing downstream knows:
    // object positions, hit boxes and the menu all stay in the 640x480
    // space the disc authored, and only the final quad is stretched.
    float scaleX, scaleY;
    float originX, originY;   // 0 but for a placement's move (UIPlacement)
    float alpha;              // the renderer's global fade
} UIView;

// A sub-rectangle of a texture, in pixels, with row 0 at the top. v is
// flipped because citro2d's convention puts the first row in memory at v = 1;
// NFSU2-3DS's VP6 player built its subtex the same way over the same upload
// path, and that one is verified on hardware.
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
// over-bright range), stored r,g,b,a low byte first. Every Flailer quad goes
// through the GS's MODULATE: texel times vertex colour over 0x80, alpha
// included, clamped only after the product. C2D_TintMult caps the tint at 1.0
// before it multiplies, so a colour past 0x80 could never lift a texel the
// way the GS does -- and WHITE16X16, under most of the frontend's strips and
// masks, is grey 0x80 at alpha 0x40 on the disc, which is exactly what the
// over-bright colours are there to lift: CHYRON_BG_2..5's alpha 0xc8 is 78%
// on the GS and came out 50%. So the tint is the raw GS byte, and draw_image()
// has texenv 0 double the product, which the combiner then clamps.
static uint32_t tint_color(uint32_t rgba, float alpha)
{
    float a = (float)((rgba >> 24) & 0xff) * alpha;
    if (a > 255.0f) a = 255.0f;
    if (a < 0.0f)   a = 0.0f;
    return C2D_Color32(rgba & 0xff, (rgba >> 8) & 0xff, (rgba >> 16) & 0xff,
                       (uint8_t)a);
}

// Whether the quads citro2d has queued want texenv 0 doubled.
static bool s_gsScale;

static void set_tev_scale(bool gs)
{
    C3D_TexEnvScale(C3D_GetTexEnv(0), C3D_Both,
                    gs ? GPU_TEVSCALE_2 : GPU_TEVSCALE_1);
}

// C2D_DrawImage with a GS colour (`gs`) or a plain C2D one. citro2d rebuilds
// texenv 0 only inside a draw, when the mode changes, and flushes what it had
// queued first, so the scale goes on after the draw; switching the scale
// flushes too, or the quads already queued would take the new one.
static void draw_image(C2D_Image img, const C2D_DrawParams* p,
                       const C2D_ImageTint* tint, bool gs)
{
    if (gs != s_gsScale) {
        C2D_Flush();
        s_gsScale = gs;
    }
    C2D_DrawImage(img, p, tint);
    set_tev_scale(gs);
}

// Puts texenv 0 back as citro2d built it, for whatever draws after the UI.
static void end_gs_scale(void)
{
    if (!s_gsScale) return;
    C2D_Flush();
    set_tev_scale(false);
    s_gsScale = false;
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

void uirender_set_time(UIRenderer* r, float seconds)
{
    r->scrollTime = seconds;
}

void uirender_override_texture(UIRenderer* r, uint32_t hash, C3D_Tex* tex,
                               uint16_t w, uint16_t h, bool fill)
{
    int idx = find_texture(r, hash);
    if (idx < 0) return;
    r->textures[idx].override     = tex;
    r->textures[idx].overrideW    = w;
    r->textures[idx].overrideH    = h;
    r->textures[idx].overrideFill = tex && fill;
}

// The two movie targets. RenderFlailerBitmap (0x00143078) never draws either
// as a picture: a bitmap carrying one is drawn as the movie -- five passes
// over MoviePlayer's MOVIE_<w>_<h>_Y / _UA / _VA / _US / _VS textures -- and
// when the player has no movie open, or no frame decoded yet, it is not drawn
// at all. On the disc both are blank buffers, SPLASH_SCREEN opaque black.
// So a movie plane left visible after its movie stops shows what is behind
// it: which is how retail's title screen appears when the intro is skipped,
// since the skip closes the movie without hiding the plane. (gp-22348 would
// send them down the ordinary path instead; it is 1 on the disc and nothing
// writes it.)
#define UIR_TEX_SPLASH_SCREEN 0xf9117c29u   // the title's two movie planes
#define UIR_TEX_PANELMOVIE    0xc3f0caefu   // the menus' background movie

// RenderSingleFlailerBitmap (0x001428f0) never draws a TACH_GRADIENT bitmap
// as a quad. It hands the bitmap and the list its word at 108 names to
// RenderFlailerTachometer (hudtach.h) and draws the polys that makes, each
// a strip in ePoly::Render's order; with no list, before Init or on the
// demo's layout, nothing. citro2d has no strip with a colour per corner,
// so they draw through georender, after what citro2d has queued, and
// citro2d is set up again after them as the race frame sets it up.
#define UIR_TACH_POLYS 4

typedef struct {
    ePoly polys[UIR_TACH_POLYS];
    int   n;
} TachPolys;

// FlailerStrip::AddPoly (0x00145868): a constructed poly. Past four the
// table's rows are zeros, and their polys nothing.
static ePoly* tach_add_poly(void* ctx)
{
    TachPolys* tp = (TachPolys*)ctx;
    if (tp->n >= UIR_TACH_POLYS) return NULL;
    epoly_init(&tp->polys[tp->n]);
    return &tp->polys[tp->n++];
}

static void draw_tach(UIRenderer* r, const BUIObject* o, const UIView* v,
                      UITexture* t)
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    const struct FlailerBitmapChunk* b =
        (const struct FlailerBitmapChunk*)o->chunk;
    const FlailerTachometerPointList* list;
    TachPolys       tp;
    GeoTexture      gt;
    GeoRenderVertex q[4];

    if (!b || t->override || !t->valid) return;
    list = hudtach_points(b);
    if (!list) return;
    tp.n = 0;
    flailer_render_tachometer(b, list, tach_add_poly, &tp);
    if (tp.n == 0) return;

    // The points' UVs are over the image's next power of two, which the
    // upload's allocation can be bigger than.
    memset(&gt, 0, sizeof gt);
    gt.tex        = &t->tex;
    gt.uvScale[0] = (float)next_power_of_2(t->w) / (float)t->tex.width;
    gt.uvScale[1] = (float)next_power_of_2(t->h) / (float)t->tex.height;

    end_gs_scale();
    C2D_Flush();
    for (int k = 0; k < tp.n; k++) {
        const ePoly* p = &tp.polys[k];
        memset(q, 0, sizeof q);
        for (int i = 0; i < 4; i++) {
            const int n = kStrip[i];
            float     a = (float)p->Colours[n][3] * v->alpha;
            if (a > 255.0f) a = 255.0f;
            if (a < 0.0f)   a = 0.0f;
            q[i].pos[0]    = v->originX + p->Vertices[n].x * v->scaleX;
            q[i].pos[1]    = v->originY + p->Vertices[n].y * v->scaleY;
            q[i].st[0]     = p->UVs[n][0];
            q[i].st[1]     = p->UVs[n][1];
            q[i].colour[0] = p->Colours[n][0];
            q[i].colour[1] = p->Colours[n][1];
            q[i].colour[2] = p->Colours[n][2];
            q[i].colour[3] = (uint8_t)a;
        }
        georender_draw_hud_quad(q, &gt, r->targetW, r->targetH);
    }
    C2D_Prepare();
    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
}

static void draw_bitmap(UIRenderer* r, const BUIObject* o, const UIView* v)
{
    int idx = find_texture(r, o->textureHash);
    if (idx < 0) return;
    UITexture* t = &r->textures[idx];
    if (o->animation == BUI_TACH_GRADIENT) {
        draw_tach(r, o, v, t);
        return;
    }
    if (!t->override && !t->valid) return;
    if (!t->override && (o->textureHash == UIR_TEX_SPLASH_SCREEN
                         || o->textureHash == UIR_TEX_PANELMOVIE))
        return;

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

    float dx = v->originX + o->x * v->scaleX;
    float dy = v->originY + o->y * v->scaleY;
    float dw = w * v->scaleX;
    float dh = h * v->scaleY;
    // A filling override covers the whole target. An object wider than the
    // target loses some of its sides on the way -- the 640x480 space is
    // square pixels on a 4:3 TV, so w / h is the shape the PS2 showed -- but
    // no more than a 32nd of its width each side, about what a TV's
    // overscan hid, and the rest is stretched. Keeping the shape outright
    // would cost the letterboxed intro (640x304, 2.1:1) a tenth of its
    // width each side, and its EA TRAX credit is burned into the frame 23
    // texels from the left edge. An object no wider than the target is
    // stretched across it, the way every 4:3 screen is (UIView), which is
    // the EA logo on the 4:3 plane.
    if (t->override && t->overrideFill) {
        float shape  = w / h;
        float target = r->targetW / r->targetH;
        if (shape > target) {
            float keep = target / shape;
            if (keep < 15.0f / 16.0f) keep = 15.0f / 16.0f;
            float mid  = 0.5f * (u0 + u1);
            float half = 0.5f * (u1 - u0) * keep;
            u0 = mid - half;
            u1 = mid + half;
        }
        dx = v->originX;
        dy = v->originY;
        dw = r->targetW;
        dh = r->targetH;
    }

    // The UV rect is in image pixels, but the allocation is padded up to a
    // power of two (texpack_upload), so it is the padded size that turns
    // pixels into UVs.
    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)tex->width, (float)tex->height,
                       u0 * (float)tw, v0 * (float)th,
                       (u1 - u0) * (float)tw, (v1 - v0) * (float)th);

    // UV scrolling. The original divides its four corners by the power-of-two
    // allocation and only then adds the offset, so the offset is already in
    // the padded texture's space -- exactly the space subtex_from_pixels has
    // just produced, which is why this is added after it and not to u0/v0.
    //
    // T goes the other way: the format counts T down from the top row while
    // subtex_from_pixels has flipped the axis to citro2d's, so the engine's
    // +dv is -dv here. An override is skipped -- it is a different image in a
    // different allocation, and the movie planes are the only ones on disc.
    //
    // Not ported: RenderSingleFlailerBitmap also insets every corner by half
    // a texel of the padded size. That applies to all 397 textures rather
    // than the two that scroll, so it belongs to its own verification pass
    // and is left out here rather than smuggled in with this.
    if (t->scrollType && !t->override) {
        float du = texpack_scroll_axis(r->scrollTime, t->scrollS,
                                       t->scrollType, t->scrollStep);
        float dv = texpack_scroll_axis(r->scrollTime, t->scrollT,
                                       t->scrollType, t->scrollStep);
        st.left   += du;
        st.right  += du;
        st.top    -= dv;
        st.bottom -= dv;
    }

    C2D_ImageTint tint;
    fill_tint(&tint, o->colors, v->alpha);

    C2D_Image img = { tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = dx;
    p.pos.y = dy;
    p.pos.w = dw;
    p.pos.h = dh;
    if (o->animation == BUI_ROTATE_CENTER && o->rotation) {
        p.center.x = p.pos.w * 0.5f;
        p.center.y = p.pos.h * 0.5f;
        p.pos.x += p.center.x;
        p.pos.y += p.center.y;
        p.angle = (float)o->rotation * 3.14159265f / 180.0f;
    }
    draw_image(img, &p, &tint, true);
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

// `color` is a finished C2D colour, the view alpha already in it: the
// screen path passes tint_color(o->color, v->alpha) with `gs` set, and the
// port's own wrapped text passes a plain colour of its own without.
static void draw_glyph(UIRenderer* r, UIFont* f, const BGlyph* g, float x,
                       float y, float w, float h, uint32_t color,
                       const UIView* v, bool gs)
{
    UITexture* t = font_sheet(r, f);
    if (!t || w <= 0.0f || h <= 0.0f) return;

    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)t->tex.width, (float)t->tex.height,
                       g->posX, g->posY, g->width, g->height);

    C2D_ImageTint tint;
    C2D_PlainImageTint(&tint, color, 1.0f);

    C2D_Image img = { &t->tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = v->originX + x * v->scaleX;
    p.pos.y = v->originY + y * v->scaleY;
    p.pos.w = w * v->scaleX;
    p.pos.h = h * v->scaleY;
    draw_image(img, &p, &tint, gs);
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
        C2D_DrawRectSolid(v->originX + penX * v->scaleX,
                          v->originY + o->y * v->scaleY, 0.0f,
                          width * v->scaleX,
                          f->font.height * o->scaleY * v->scaleY,
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
                           tint_color(o->color, v->alpha), v, true);
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
                       g.width * o->scaleX, g.height * o->scaleY,
                       tint_color(o->color, v->alpha), v, true);
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
                   tint_color(o->color, v->alpha), v, true);
        penX += g.advance * o->scaleX;
        prev = ch;
    }
}

// GetScaledWidth__16FlailerTextChunk (0x0013e8b0) and GetScaledHeight
// (0x0013e858), which are what ScaleAboutCenter divides to find the centre
// it scales about. Width is the same sum draw_text() lays down; height is
// the font's line height truncated to an int *before* ScaleY multiplies it,
// which is the cvt.w.s at 0x0013e880 and not a rounding accident. Both are
// 0 for an object whose font is not loaded, exactly as the originals return
// 0 when FindFont fails.
// ---------------------------------------------------------------------------
// The port's own text -- see the UIWrapStyle block in uirender.h
// ---------------------------------------------------------------------------

// The style's font, or the first one loaded that has a glyph sheet. Falling
// back rather than failing is what makes a caller with nothing to say about
// fonts -- the bring-up overlays -- work at all.
static UIFont* wrap_font(UIRenderer* r, const UIWrapStyle* st)
{
    if (st->fontHash) return find_font(r, st->fontHash);
    for (int i = 0; i < r->numFonts; i++)
        if (font_sheet(r, &r->fonts[i])) return &r->fonts[i];
    return NULL;
}

// One character's glyph, from the run's own font or -- for a button icon --
// from BUTTONSOUT. Same test as draw_text(); see IsHelpCharacter.
static bool wrap_glyph(UIRenderer* r, UIFont* f, unsigned char ch,
                       UIFont** outFont, BGlyph* out)
{
    if ((unsigned)(ch - UIR_HELP_FIRST) < UIR_HELP_COUNT) {
        UIFont* hf = find_font(r, HELP_FONT_HASH);
        if (!hf) return false;
        *outFont = hf;
        return bfont_glyph(&hf->font, kHelpGlyph[ch - UIR_HELP_FIRST], out);
    }
    *outFont = f;
    return bfont_glyph(&f->font, ch, out);
}

typedef struct {
    size_t draw;    // characters of this line to draw
    size_t next;    // characters to step over to reach the next line
    float  width;   // what draw covers, scaled
} UIWrapLine;

// Greedy wrap: the longest run of whole words that fits in boxW. A word
// wider than the box on its own is broken at the last character that fits,
// because the alternative is a line that runs off the panel.
//
// Unlike GetScaledWidth (0x0013e8b0) this counts kerning, because the pen
// below moves by it. The engine's own measurement does not, which is a
// disc-accuracy detail of measure() and would be a bug here.
static UIWrapLine wrap_next(UIRenderer* r, UIFont* f, const char* s,
                            size_t len, float scale, float boxW)
{
    UIWrapLine ln;
    size_t     lastSpace = (size_t)-1;
    float      w = 0.0f, wAtSpace = 0.0f;
    int        prev = -1;

    for (size_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)s[i];
        UIFont*       gf = f;
        BGlyph        g;
        float         adv = 0.0f;

        if (ch == 10) {          // a hard break in the string itself
            ln.draw = i; ln.next = i + 1; ln.width = w * scale;
            return ln;
        }
        if (wrap_glyph(r, f, ch, &gf, &g)) {
            if (KERNING_ENABLED && prev >= 0 && gf == f)
                adv += bfont_kerning(&f->font, prev, ch);
            adv += g.advance;
            prev = (gf == f) ? (int)ch : -1;
        } else {
            prev = -1;
        }
        if (ch == ' ') { lastSpace = i; wAtSpace = w; }

        // i > 0 guarantees progress: a single glyph wider than the whole box
        // is drawn anyway rather than breaking before every character.
        if (i > 0 && (w + adv) * scale > boxW) {
            if (lastSpace != (size_t)-1) {
                ln.draw = lastSpace; ln.next = lastSpace + 1;
                ln.width = wAtSpace * scale;
            } else {
                ln.draw = i; ln.next = i; ln.width = w * scale;
            }
            return ln;
        }
        w += adv;
    }
    ln.draw = len; ln.next = len; ln.width = w * scale;
    return ln;
}

// Lays the text out and, when `draw`, puts it on the bound target. One
// function for both, so the height a caller centres against is measured by
// the code that does the drawing and cannot drift from it.
static float wrap_run(UIRenderer* r, const char* text, size_t len,
                      const UIWrapStyle* st, float x, float y, float boxW,
                      float alpha, bool draw)
{
    UIFont*  f;
    UIView   v;
    uint32_t color;
    float    scale, lineH, top;
    size_t   pos   = 0;
    bool     first = true;

    if (!r || !st || !text) return 0.0f;
    if (len == 0) len = strlen(text);
    if (len == 0) return 0.0f;
    f = wrap_font(r, st);
    if (!f) return 0.0f;

    scale = st->scale > 0.0f ? st->scale : 1.0f;
    lineH = f->font.height * scale + st->lineGap;

    // Target pixels, so the view is the identity: the caller has already
    // decided where on the screen this goes.
    v.scaleX = v.scaleY = 1.0f;
    v.originX = v.originY = 0.0f;
    v.alpha   = 1.0f;

    color = st->color;
    if (alpha < 1.0f) {
        float a = (float)(color >> 24) * (alpha > 0.0f ? alpha : 0.0f);
        color = (color & 0x00ffffffu) | ((uint32_t)a << 24);
    }

    top = y;
    while (pos < len) {
        // Leading spaces on a continuation line are the break itself, not
        // an indent.
        if (!first) while (pos < len && text[pos] == ' ') pos++;
        if (pos >= len) break;

        UIWrapLine ln = wrap_next(r, f, text + pos, len - pos, scale, boxW);
        if (draw) {
            float penX = st->center ? x + (boxW - ln.width) * 0.5f : x;
            int   prev = -1;
            for (size_t i = 0; i < ln.draw; i++) {
                unsigned char ch = (unsigned char)text[pos + i];
                UIFont*       gf = f;
                BGlyph        g;
                if (!wrap_glyph(r, f, ch, &gf, &g)) { prev = -1; continue; }
                if (KERNING_ENABLED && prev >= 0 && gf == f)
                    penX += bfont_kerning(&f->font, prev, ch) * scale;
                draw_glyph(r, gf, &g, penX, top + g.offset * scale,
                           g.width * scale, g.height * scale, color, &v,
                           false);
                penX += g.advance * scale;
                prev = (gf == f) ? (int)ch : -1;
            }
        }
        top += lineH;
        if (ln.next == 0) break;
        pos += ln.next;
        first = false;
    }
    return top - y;
}

float uirender_line_height(UIRenderer* r, const UIWrapStyle* st)
{
    UIFont* f;
    if (!r || !st) return 0.0f;
    f = wrap_font(r, st);
    if (!f) return 0.0f;
    return f->font.height * (st->scale > 0.0f ? st->scale : 1.0f)
           + st->lineGap;
}

float uirender_wrap_height(UIRenderer* r, const char* text, size_t len,
                           const UIWrapStyle* st, float boxW)
{
    return wrap_run(r, text, len, st, 0.0f, 0.0f, boxW, 1.0f, false);
}

float uirender_draw_wrapped(UIRenderer* r, const char* text, size_t len,
                            const UIWrapStyle* st, float x, float y,
                            float boxW, float alpha)
{
    // The bitmap path sets this too, and the bottom screen draws no bitmap.
    C2D_SetTintMode(C2D_TintMult);
    return wrap_run(r, text, len, st, x, y, boxW, alpha, true);
}

const char* uirender_object_string(UIRenderer* r, const BUI* ui,
                                   uint32_t index, size_t* outLen)
{
    BUIObject   o;
    const char* s;
    size_t      n = 0;

    if (outLen) *outLen = 0;
    if (!r || !ui || !bui_object(ui, index, &o)) return NULL;
    if (o.type != BUI_TYPE_TEXT) return NULL;
    s = object_text(r, &o, &n);
    if (outLen) *outLen = n;
    return s;
}

void uirender_hide_object(UIRenderer* r, uint32_t nameHash)
{
    if (!r) return;
    if (!nameHash) { r->numHidden = 0; return; }
    for (int i = 0; i < r->numHidden; i++)
        if (r->hidden[i] == nameHash) return;
    if (r->numHidden < UIR_MAX_HIDDEN) r->hidden[r->numHidden++] = nameHash;
}

static bool object_hidden(const UIRenderer* r, uint32_t nameHash)
{
    for (int i = 0; i < r->numHidden; i++)
        if (r->hidden[i] == nameHash) return true;
    return false;
}

void uirender_set_placements(UIRenderer* r, const UIPlacement* table, int n)
{
    if (!r) return;
    r->placements    = table;
    r->numPlacements = table ? n : 0;
}

// Whether any placement names this screen, so a screen with none is
// skipped whole.
static bool screen_placed(const UIRenderer* r, const BUIScreen* screen)
{
    for (int i = 0; i < r->numPlacements; i++)
        if (r->placements[i].screenHash == screen->nameHash) return true;
    return false;
}

static const UIPlacement* placement_of(const UIRenderer* r,
                                       const BUIScreen* screen,
                                       const BUIObject* o)
{
    for (int i = 0; i < r->numPlacements; i++) {
        const UIPlacement* p = &r->placements[i];
        if (p->screenHash != screen->nameHash) continue;
        if (p->nameHash ? p->nameHash == o->nameHash
                        : p->groupHash == o->groupHash)
            return p;
    }
    return NULL;
}

bool uirender_text_extent(UIRenderer* r, const BUI* ui, uint32_t index,
                          float* outW, float* outH)
{
    BUIObject   o;
    UIFont*     f;
    size_t      len = 0;
    const char* str;

    if (outW) *outW = 0.0f;
    if (outH) *outH = 0.0f;
    if (!r || !ui || !bui_object(ui, index, &o)) return false;
    if (o.type != BUI_TYPE_TEXT) return false;
    f = find_font(r, o.fontHash);
    if (!f) return true;               // found, but measures 0 -- as on PS2

    str = object_text(r, &o, &len);
    if (outW && str)
        *outW = measure(f, str, len, o.scaleX,
                        (o.format & BUI_FMT_FIXEDWIDTH) != 0);
    if (outH) *outH = (float)(int)f->font.height * o.scaleY;
    return true;
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

float uirender_text_scaled_width(UIRenderer* r, const BUI* ui,
                                 uint32_t index)
{
    BUIObject o;
    if (!r || !ui || !bui_object(ui, index, &o)) return 0.0f;
    if (o.type != BUI_TYPE_TEXT) return 0.0f;
    UIFont* f = find_font(r, o.fontHash);
    if (!f) return 0.0f;
    size_t      len = 0;
    const char* s   = object_text(r, &o, &len);
    float       sum = 0.0f;
    for (size_t i = 0; s && i < len; i++) {
        BGlyph g;
        if (bfont_glyph(&f->font, (unsigned char)s[i], &g))
            sum += g.advance;
    }
    return o.scaleX * sum;
}

bool uirender_texture_size(UIRenderer* r, uint32_t hash, int32_t* w,
                           int32_t* h)
{
    *w = *h = 0;
    if (!r) return false;
    int idx = find_texture(r, hash);
    if (idx < 0) return false;
    UITexture* t = &r->textures[idx];
    if (!t->override && !t->valid) return false;
    *w = t->override ? t->overrideW : t->w;
    *h = t->override ? t->overrideH : t->h;
    return true;
}

int32_t uirender_object_width(UIRenderer* r, const BUI* ui, uint32_t index)
{
    BUIObject o;
    if (!r || !ui || !bui_object(ui, index, &o)) return 0;
    if (o.type == BUI_TYPE_TEXT)
        return (int32_t)uirender_text_scaled_width(r, ui, index);
    if (o.type == BUI_TYPE_BITMAP) {
        int32_t tw, th;
        if (!uirender_texture_size(r, o.textureHash, &tw, &th)) return 0;
        return (int32_t)((float)tw * o.scaleX);
    }
    return 0;
}

float uirender_object_height(UIRenderer* r, const BUI* ui, uint32_t index)
{
    BUIObject o;
    if (!r || !ui || !bui_object(ui, index, &o)) return 0.0f;
    if (o.type == BUI_TYPE_TEXT) {
        float h = 0.0f;
        uirender_text_extent(r, ui, index, NULL, &h);
        return h;
    }
    if (o.type == BUI_TYPE_BITMAP) {
        int idx = find_texture(r, o.textureHash);
        if (idx < 0) return 0.0f;
        UITexture* t = &r->textures[idx];
        if (!t->override && !t->valid) return 0.0f;
        uint16_t th = t->override ? t->overrideH : t->h;
        return (float)th * o.scaleY;
    }
    return 0.0f;
}

static UIView screen_view(const UIRenderer* r, const BUIScreen* screen,
                          float alpha)
{
    float resX = screen->resX ? (float)screen->resX : 640.0f;
    float resY = screen->resY ? (float)screen->resY : 480.0f;

    UIView v;
    // Stretch to fill rather than fit inside: both origins are 0 and each
    // axis gets its own scale. On the top screen that is 400/640 across
    // and 240/480 down, so the picture comes out 25% wider relative to its
    // height than the disc drew it.
    v.scaleX  = r->targetW / resX;
    v.scaleY  = r->targetH / resY;
    v.originX = 0.0f;
    v.originY = 0.0f;
    v.alpha   = alpha;
    return v;
}

// One object of `layer`, if it is visible there and placed on `target`
// (UIR_TARGET_*), moved by its placement.
static void draw_object(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                        uint32_t index, int layer, const UIView* v,
                        int target, bool placed)
{
    BUIObject o;
    if (!bui_object(ui, index, &o)) return;
    if (o.z != layer) return;
    if (o.visible != BUI_VISIBLE) return;
    // Drawn on the bottom screen instead; see uirender_hide_object.
    if (object_hidden(r, o.nameHash)) return;

    const UIPlacement* p = placed ? placement_of(r, screen, &o) : NULL;
    if ((p ? p->target : UIR_TARGET_TOP) != target) return;
    UIView ov = *v;
    if (p) {
        ov.originX += p->dx * v->scaleX;
        ov.originY += p->dy * v->scaleY;
    }
    if (o.type == BUI_TYPE_BITMAP)    draw_bitmap(r, &o, &ov);
    else if (o.type == BUI_TYPE_TEXT) draw_text(r, &o, &ov);
}

// One screen's share of one layer, in file order.
static void draw_layer(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                       int layer, const UIView* v, int target)
{
    bool placed = screen_placed(r, screen);

    for (uint32_t i = 0; i < screen->count; i++)
        draw_object(r, ui, screen, screen->first + i, layer, v, target,
                    placed);
}

// Z is a layer index, and eDisplayFrame walks the layers in the fixed, mostly
// descending order spelled out at BUI_LAYER_ORDER. Within one layer the file
// order is the draw order, because AddFlailerStrip appends to the tail of
// LayerRenderInfoTable[Z].
static const uint8_t kLayerOrder[BUI_NUM_LAYERS] = BUI_LAYER_ORDER;

void uirender_draw_screen(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                          float alpha)
{
    if (!ui || !screen) return;
    UIView v = screen_view(r, screen, alpha);

    C2D_SetTintMode(C2D_TintMult);
    for (int pass = 0; pass < BUI_NUM_LAYERS; pass++)
        draw_layer(r, ui, screen, kLayerOrder[pass], &v, UIR_TARGET_TOP);
    end_gs_scale();
}

// The layer table is one for the whole frame, and every visible screen adds
// its strips to it: a layer is drawn for all of them before the next layer
// starts, screens in the order the bundles were added.
//
// Built as retail builds LayerRenderInfoTable: one walk of the screens'
// objects appends each visible one to its Z's list, and the layers are
// drawn from the lists (step 13b-4). Asking every object its Z once per
// layer unpacked each of them 29 times a frame. Past UIR_LAYER_ITEMS the
// walk goes a layer at a time, as it did.
#define UIR_LAYER_ITEMS 1024

typedef struct {
    uint32_t index;     // absolute object index
    int16_t  next;      // the next in the layer, or -1
    uint8_t  bundle;
    uint8_t  pad;
    uint16_t screen;
} UILayerItem;

static UILayerItem s_layerItems[UIR_LAYER_ITEMS];

static bool screen_drawn(const UIRenderer* r, const BUIScreen* screen,
                         int target)
{
    return screen->visible
           && (target != UIR_TARGET_BOTTOM || screen_placed(r, screen));
}

static void draw_visible(UIRenderer* r, float alpha, int target, int from,
                         int to)
{
    int16_t head[BUI_NUM_LAYERS], tail[BUI_NUM_LAYERS];
    int     n = 0;

    for (int z = 0; z < BUI_NUM_LAYERS; z++) head[z] = tail[z] = -1;
    for (int b = 0; b < r->numBundles && n >= 0; b++) {
        if (!r->bundles[b].hasUI) continue;
        const BUI* ui = &r->bundles[b].ui;
        for (uint32_t s = 0; s < ui->numScreens && n >= 0; s++) {
            const BUIScreen* screen = &ui->screens[s];
            if (!screen_drawn(r, screen, target)) continue;
            for (uint32_t i = 0; i < screen->count; i++) {
                int visible, z;
                if (!bui_object_layer(ui, screen->first + i, &visible, &z))
                    continue;
                if (visible != BUI_VISIBLE || z < 0 || z >= BUI_NUM_LAYERS)
                    continue;
                if (n >= UIR_LAYER_ITEMS) {
                    n = -1;
                    break;
                }
                s_layerItems[n].index  = screen->first + i;
                s_layerItems[n].next   = -1;
                s_layerItems[n].bundle = (uint8_t)b;
                s_layerItems[n].screen = (uint16_t)s;
                if (tail[z] < 0) head[z] = (int16_t)n;
                else             s_layerItems[tail[z]].next = (int16_t)n;
                tail[z] = (int16_t)n;
                n++;
            }
        }
    }

    for (int pass = from; pass < to; pass++) {
        int layer = kLayerOrder[pass];
        if (n < 0) {
            for (int b = 0; b < r->numBundles; b++) {
                if (!r->bundles[b].hasUI) continue;
                BUI* ui = &r->bundles[b].ui;
                for (uint32_t s = 0; s < ui->numScreens; s++) {
                    const BUIScreen* screen = &ui->screens[s];
                    if (!screen_drawn(r, screen, target)) continue;
                    UIView v = screen_view(r, screen, alpha);
                    draw_layer(r, ui, screen, layer, &v, target);
                }
            }
            continue;
        }
        for (int k = head[layer]; k >= 0; k = s_layerItems[k].next) {
            const UILayerItem* it     = &s_layerItems[k];
            BUI*               ui     = &r->bundles[it->bundle].ui;
            const BUIScreen*   screen = &ui->screens[it->screen];
            UIView             v      = screen_view(r, screen, alpha);
            draw_object(r, ui, screen, it->index, layer, &v, target,
                        screen_placed(r, screen));
        }
    }
}

void uirender_draw_visible(UIRenderer* r, float alpha)
{
    uirender_draw_visible_passes(r, alpha, 0, BUI_NUM_LAYERS);
}

void uirender_draw_visible_passes(UIRenderer* r, float alpha, int from,
                                  int to)
{
    if (from < 0) from = 0;
    if (to > BUI_NUM_LAYERS) to = BUI_NUM_LAYERS;
    if (from >= to) return;
    C2D_SetTintMode(C2D_TintMult);
    draw_visible(r, alpha, UIR_TARGET_TOP, from, to);
    end_gs_scale();
}

// The same walk for the bottom screen's share. The target's size stands
// in for the top screen's while it runs, since screen_view and the
// bitmap paths read it.
bool uirender_draw_visible_bottom(UIRenderer* r, float targetW,
                                  float targetH, float alpha)
{
    float w = r->targetW, h = r->targetH;
    bool  any = false;

    r->targetW = targetW;
    r->targetH = targetH;
    for (int b = 0; b < r->numBundles && !any; b++) {
        if (!r->bundles[b].hasUI) continue;
        const BUI* ui = &r->bundles[b].ui;
        for (uint32_t s = 0; s < ui->numScreens && !any; s++)
            any = screen_drawn(r, &ui->screens[s], UIR_TARGET_BOTTOM);
    }
    C2D_SetTintMode(C2D_TintMult);
    draw_visible(r, alpha, UIR_TARGET_BOTTOM, 0, BUI_NUM_LAYERS);
    end_gs_scale();
    r->targetW = w;
    r->targetH = h;
    return any;
}
#endif  // __3DS__
