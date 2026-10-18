#include "uirender.h"

#ifdef __3DS__
#include <malloc.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "buttons3ds_bin.h"
#include "epoly.h"
#include "georender.h"
#include "helpglyph.h"
#include "hudtach.h"
#include "joyhid.h"
#include "replaybar.h"

// RenderHelpCharacter (retail 0x00141dd8) hashes this name and calls
// FindFont.
#define HELP_FONT_HASH 0xb85de386u   // bStringHash("BUTTONSOUT")

// The 30-byte table at retail 0x002f09c0: help character 0x80+i draws this
// glyph of BUTTONSOUT. BUTTONSOUT has only 'a' to 'o', so 0x8e and up find
// no glyph and draw nothing, and 0x92 is not a help character at all.
static const uint8_t kHelpGlyph[UIR_HELP_COUNT] = {
    'a', 'b', 'd', 'e', 'f', 'g', 'i', 'j', 'h', 'k',
    'n', 'o', 'l', 'm', '3', 'w', 'p', 'v', 0x92, 'u',
    'q', 'r', 't', 's', 'c', 'x', '2', 'y', 'z', '1',
};

// IsHelpCharacter (retail 0x00141db0): (u8)(c + 128) < 30 && c != 0x92.
static bool is_help_char(unsigned char c)
{
    return (unsigned char)(c - UIR_HELP_FIRST) < UIR_HELP_COUNT && c != 0x92;
}

// Font::FixedWidthCell is GetWidestCharacter(this, "1234567890:- ") -- the
// widest mAdvance among those characters (Font::Font, 0x0013dd60).
static const char kFixedWidthSet[] = "1234567890:- ";

// gp-relative globals the renderer reads. All are initialised data and
// nothing on this disc writes any of them, so they are constants here.
//   KerningEnabled           1  -- the demo's; retail's Render kerns
//                                  without reading it
//   RenderFixedWidthStrings  1
//   TranslationEnable        1
//   ColonCrapola             0  -- so ':' and '.' get a fixed cell like every
//                                  other character; the proportional path
//                                  behind that flag is dead code.
#define KERNING_ENABLED 1
#define COLON_CRAPOLA   0

// Render (retail 0x0014261c) drops a kerning step bigger than this, after
// ScaleX.
#define KERN_LIMIT 80.0f

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
    if (r->iconState > 0) C3D_TexDelete(&r->iconTex);
    for (int i = 0; i < r->numBundles; i++) {
        if (r->bundles[i].hasUI) bui_close(&r->bundles[i].ui);
        free(r->bundles[i].data);
        free(r->bundles[i].uiData);
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

// The replay bar's PS2 buttons drawn as the 3DS keys the replay hears
// (replaybar.h), from the help line's sheet.
static void retouch_replay_bar(void* ctx, uint8_t* rgba, uint32_t w,
                               uint32_t h)
{
    (void)ctx;
    (void)replaybar_retouch(rgba, w, h, buttons3ds_bin, buttons3ds_bin_size);
}

// Decodes and uploads on first use. A miss is cached as an invalid entry so a
// screen full of one missing hash does not rescan every bundle every frame.
// The replay bar's texture is retouched on the way (retouch_replay_bar).
static int find_texture(UIRenderer* r, uint32_t hash)
{
    int index = -1;
    for (int i = 0; i < r->numTextures; i++) {
        if (r->textures[i].unused) {
            if (index < 0) index = i;
            continue;
        }
        if (r->textures[i].hash == hash) return i;
    }
    if (index < 0) {
        if (r->numTextures >= UIR_MAX_TEXTURES) return -1;
        index = r->numTextures++;
    }

    UITexture* slot = &r->textures[index];
    memset(slot, 0, sizeof(*slot));
    slot->hash = hash;

    for (int i = 0; i < r->numBundles; i++) {
        const UIBundle* b = &r->bundles[i];
        TexPack tp;
        for (uint32_t n = 0; texpack_open_nth(&tp, b->data, 0, b->len, n); n++) {
            TexInfo ti;
            if (!texpack_find(&tp, hash, &ti)) continue;
            if (!texpack_upload_retouched(&tp, &ti, 0, &slot->tex,
                                          hash == REPLAYBAR_TEX_HASH
                                              ? retouch_replay_bar : NULL,
                                          NULL))
                continue;
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

// The port's sheet of the 3DS's buttons, helpglyph.h's: data/buttons3ds.bin,
// RGBA rows from the top, tiled into GPU_RGBA8's (a, b, g, r) words as
// texpack.c's tile_padded lays a disc texture.
static C3D_Tex* icon_sheet(UIRenderer* r)
{
    const uint32_t n = HELPGLYPH_SHEET;

    if (r->iconState == 0) {
        r->iconState = -1;
        if (buttons3ds_bin_size == n * n * 4
            && C3D_TexInit(&r->iconTex, n, n, GPU_RGBA8)) {
            uint32_t* dst = (uint32_t*)r->iconTex.data;
            for (uint32_t y = 0; y < n; y++) {
                for (uint32_t x = 0; x < n; x++) {
                    const uint8_t* s = buttons3ds_bin + (y * n + x) * 4;
                    dst[texpack_tiled_index(x, y, n)] =
                        (uint32_t)s[3] | ((uint32_t)s[2] << 8)
                        | ((uint32_t)s[1] << 16) | ((uint32_t)s[0] << 24);
                }
            }
            C3D_TexFlush(&r->iconTex);
            C3D_TexSetFilter(&r->iconTex, GPU_LINEAR, GPU_LINEAR);
            C3D_TexSetWrap(&r->iconTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
            r->iconState = 1;
        }
    }
    return r->iconState > 0 ? &r->iconTex : NULL;
}

int32_t (*gUiHelpLayoutFn)(void);

// The joyhid layout live now, whose keys the menus' and the HUD's button
// icons name: main.c's answer, as joyhid_read asks it, unless
// gUiHelpLayoutFn has one of its own.
static int32_t live_help_layout(void)
{
    int32_t own = gUiHelpLayoutFn ? gUiHelpLayoutFn() : -1;

    if (own >= 0)
        return own;
    return gJoyHidRaceLayoutFn ? gJoyHidRaceLayoutFn() : JOYHID_LAYOUT_MENU;
}

// RenderHelpCharacter's glyph (retail 0x00141dd8) for help character `c`,
// and the sheet it is in, NULL when there is none: the 3DS key that does
// its job in joyhid layout `layout`, from the port's sheet, or the
// BUTTONSOUT glyph of the help character helpglyph_map leaves -- `c`
// itself for the D-pad, START and SELECT. The port's cells are
// BUTTONSOUT's size and advance, 26 x 28 and 26.
static C3D_Tex* help_glyph(UIRenderer* r, unsigned char c, int32_t layout,
                           BGlyph* out)
{
    int32_t m = helpglyph_map(c, layout);

    if (m >= HELPGLYPH_ICON) {
        int32_t  i = m - HELPGLYPH_ICON;
        C3D_Tex* t = icon_sheet(r);
        if (!t) return NULL;
        memset(out, 0, sizeof *out);
        out->id      = c;
        out->posX    = (float)((i % HELPGLYPH_COLS) * HELPGLYPH_CELL_W);
        out->posY    = (float)((i / HELPGLYPH_COLS) * HELPGLYPH_CELL_H);
        out->width   = (float)HELPGLYPH_CELL_W;
        out->height  = (float)HELPGLYPH_CELL_H;
        out->advance = (float)HELPGLYPH_CELL_W;
        return t;
    }

    UIFont*    hf = find_font(r, HELP_FONT_HASH);
    UITexture* t  = hf ? font_sheet(r, hf) : NULL;
    if (!t || !bfont_glyph(&hf->font, kHelpGlyph[m - UIR_HELP_FIRST], out))
        return NULL;
    return &t->tex;
}

// The port's: text set in BUTTONSOUT itself, such as the frontend's "Help"
// mark ('k', the PS2's Circle), is not help characters, so retail draws
// the PS2 key. A glyph of the help table that helpglyph_map turns into a
// 3DS key draws that key instead: `g` takes the icon's cell (BUTTONSOUT's
// size and advance) and the answer is its sheet. Any other glyph keeps
// `tex`.
static C3D_Tex* buttonsout_key(UIRenderer* r, unsigned char ch, BGlyph* g,
                               C3D_Tex* tex)
{
    for (int32_t i = 0; i < UIR_HELP_COUNT; i++) {
        unsigned char hc     = (unsigned char)(UIR_HELP_FIRST + i);
        int32_t       layout = live_help_layout();
        BGlyph        key;
        C3D_Tex*      t;

        if (kHelpGlyph[i] != ch || !is_help_char(hc)) continue;
        if (helpglyph_map(hc, layout) < HELPGLYPH_ICON) return tex;
        t = help_glyph(r, hc, layout, &key);
        if (!t) return tex;
        *g = key;
        return t;
    }
    return tex;
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

void uirender_forget_texture(UIRenderer* r, uint32_t hash)
{
    for (int i = 0; i < r->numTextures; i++) {
        UITexture* t = &r->textures[i];
        if (t->unused || t->hash != hash) continue;
        if (t->valid) return;
        memset(t, 0, sizeof(*t));
        t->unused = true;
        return;
    }
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

// The box a copy is cut to (MaybeClipPoly, 0x00141808), in the screen's
// 640x480 space.
typedef struct {
    float tlx, tly, brx, bry;
} UIClipBox;

// `clip` NULL draws the whole quad. Otherwise a quad wholly outside the box
// is dropped, and one across its edges is cut to them, its sheet rectangle
// moving in step; a rotated one or a filling override is not cut.
static void draw_bitmap_clipped(UIRenderer* r, const BUIObject* o,
                                const UIView* v, const UIClipBox* clip)
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

    float ox = o->x, oy = o->y;
    if (clip && !(t->override && t->overrideFill)
        && !(o->animation == BUI_ROTATE_CENTER && o->rotation)) {
        float x0 = ox, x1 = ox + w, y0 = oy, y1 = oy + h;
        float pu0 = u0, pu1 = u1, pv0 = v0, pv1 = v1;
        if (x1 < clip->tlx || clip->brx <= x0 || y1 < clip->tly
            || clip->bry <= y0)
            return;
        if (x0 < clip->tlx) {
            pu0 += (clip->tlx - x0) / (x1 - x0) * (pu1 - pu0);
            x0 = clip->tlx;
        }
        if (clip->brx < x1) {
            pu1 -= (x1 - clip->brx) / (x1 - x0) * (pu1 - pu0);
            x1 = clip->brx;
        }
        if (y0 < clip->tly) {
            pv0 += (clip->tly - y0) / (y1 - y0) * (pv1 - pv0);
            y0 = clip->tly;
        }
        if (clip->bry < y1) {
            pv1 -= (y1 - clip->bry) / (y1 - y0) * (pv1 - pv0);
            y1 = clip->bry;
        }
        if (x1 <= x0 || y1 <= y0) return;
        ox = x0;
        oy = y0;
        w  = x1 - x0;
        h  = y1 - y0;
        u0 = pu0;
        u1 = pu1;
        v0 = pv0;
        v1 = pv1;
    }

    float dx = v->originX + ox * v->scaleX;
    float dy = v->originY + oy * v->scaleY;
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

// GetScaledWidth (retail 0x00140d30): sum the advances, then scale once.
static float measure(UIFont* f, const char* s, size_t len, float scaleX,
                     bool fixedWidth)
{
    if (!fixedWidth) return bfont_measure(&f->font, s, len) * scaleX;

    // GetFixedWidthStringWidth (retail 0x00141ec8): one cell per character
    // that has a glyph. ColonCrapola would give ':' and '.' their own advance instead,
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
// port's own wrapped text passes a plain colour of its own without. `tex`
// is the glyph's sheet.
static void draw_glyph(C3D_Tex* tex, const BGlyph* g, float x, float y,
                       float w, float h, uint32_t color, const UIView* v,
                       bool gs)
{
    if (!tex || w <= 0.0f || h <= 0.0f) return;

    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)tex->width, (float)tex->height,
                       g->posX, g->posY, g->width, g->height);

    C2D_ImageTint tint;
    C2D_PlainImageTint(&tint, color, 1.0f);

    C2D_Image img = { tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = v->originX + x * v->scaleX;
    p.pos.y = v->originY + y * v->scaleY;
    p.pos.w = w * v->scaleX;
    p.pos.h = h * v->scaleY;
    draw_image(img, &p, &tint, gs);
}

// RenderCharacter (retail 0x00141a98): the glyph's sheet rectangle at the
// pen, its width times ScaleX *twice* (mul.s at 0x00141b58 and again at
// 0x00141b9c) and its height times ScaleY once, with no mOffset. That is a
// shipped bug the screens were laid out with, so it stays. Fixed-width text
// and the button icons go through here; proportional text does not.
static void draw_character(C3D_Tex* tex, const BGlyph* g, float x, float y,
                           const BUIObject* o, uint32_t color,
                           const UIView* v)
{
    draw_glyph(tex, g, x, y, g->width * o->scaleX * o->scaleX,
               g->height * o->scaleY, color, v, true);
}

// A font's sheet, for draw_glyph.
static C3D_Tex* font_tex(UIRenderer* r, UIFont* f)
{
    UITexture* t = font_sheet(r, f);
    return t ? &t->tex : NULL;
}

// RenderHelpCharacter (retail 0x00141dd8): the glyph for help character
// `c` at the pen, through RenderCharacter -- the key of joyhid layout
// `layout`, help_glyph's. Returns the glyph's advance *unscaled*, which the
// callers add to a scaled pen; 0 when the sheet or the glyph is missing.
static float draw_help_character(UIRenderer* r, unsigned char c, float x,
                                 float y, const BUIObject* o, uint32_t color,
                                 const UIView* v, int32_t layout)
{
    BGlyph   hg;
    C3D_Tex* t = help_glyph(r, c, layout, &hg);
    if (!t) return 0.0f;
    draw_character(t, &hg, x, y, o, color, v);
    return hg.advance;
}

static void draw_clipped_character(UIRenderer* r, UIFont* f, const BGlyph* g,
                                   float x, float y, float w, float h,
                                   uint32_t color, const UIView* v,
                                   const UIClipBox* s);

// Render__16FlailerTextChunk (retail 0x001422f0). `clip` NULL draws every
// glyph whole; otherwise each glyph is cut to the box, as RenderCharacter's
// MaybeClipPoly cuts it.
static void draw_text_clipped(UIRenderer* r, const BUIObject* o,
                              const UIView* v, const UIClipBox* clip)
{
    UIFont* f = find_font(r, o->fontHash);
    if (!f) return;

    size_t      len = 0;
    const char* s   = object_text(r, o, &len);
    if (!s || len == 0) return;

    bool     fixed = (o->format & BUI_FMT_FIXEDWIDTH) != 0;
    float    width = measure(f, s, len, o->scaleX, fixed);
    uint32_t color = tint_color(o->color, v->alpha);

    // Right subtracts the whole width, centre subtracts half. Declaration
    // order says otherwise and would right-align every centred label in the
    // game. RenderStringFixedWidth (0x00141f70) does the same with its own
    // width.
    float penX = o->x;
    if (o->format & BUI_FMT_RIGHT)       penX -= width;
    else if (o->format & BUI_FMT_CENTER) penX -= width * 0.5f;

    // BUI_FMT_DARKBG calls RenderDarkBackground (0x00142110), which draws
    // only when its texture at gp-22416 is set, and nothing on the disc
    // sets it. (Only the debug ScreenPrintf screen has the flag.)

    for (size_t i = 0; i < len; i++) {
        unsigned char ch = (unsigned char)s[i];
        BGlyph        g;

        if (fixed) {
            // RenderStringFixedWidth centres each glyph in a cell of
            // FixedWidthCell and advances by ScaleX * the cell. The centring
            // term is *not* scaled -- the engine adds it to an already-
            // scaled pen -- so this leaves it unscaled too. It has no help
            // characters.
            if (!bfont_glyph(&f->font, ch, &g)) continue;
            float inset = (f->fixedCell - g.advance) * 0.5f;
            if (clip)
                draw_clipped_character(r, f, &g, penX + inset, o->y,
                                       g.width * o->scaleX * o->scaleX,
                                       g.height * o->scaleY, color, v, clip);
            else
                draw_character(font_tex(r, f), &g, penX + inset, o->y, o,
                               color, v);
            penX += f->fixedCell * o->scaleX;
            continue;
        }

        // The button icons are tested before the glyph, so one draws even
        // where the text's own font has no glyph for its code.
        if (is_help_char(ch)) {
            penX += draw_help_character(r, ch, penX, o->y, o, color, v,
                                        live_help_layout());
            continue;
        }
        if (!bfont_glyph(&f->font, ch, &g)) continue;

        // GetKerning against the byte before, whatever it was: a button
        // icon or a character with no glyph still counts as the previous
        // one. Retail scales it, drops it past KERN_LIMIT, then scales the
        // sum of advance and kerning again for the pen.
        float kern = 0.0f;
        if (i > 0) {
            kern = bfont_kerning(&f->font, (unsigned char)s[i - 1], ch)
                   * o->scaleX;
            if (fabsf(kern) > KERN_LIMIT) kern = 0.0f;
        }

        // The proportional path draws the glyph itself, at ScaleX once.
        // A BUTTONSOUT key draws the 3DS one (buttonsout_key) unless it is
        // clipped; no clipped text is in BUTTONSOUT.
        if (clip)
            draw_clipped_character(r, f, &g, penX + kern, o->y,
                                   g.width * o->scaleX, g.height * o->scaleY,
                                   color, v, clip);
        else {
            C3D_Tex* tex = font_tex(r, f);

            if (o->fontHash == HELP_FONT_HASH)
                tex = buttonsout_key(r, ch, &g, tex);
            draw_glyph(tex, &g, penX + kern, o->y, g.width * o->scaleX,
                       g.height * o->scaleY, color, v, true);
        }
        penX += o->scaleX * (g.advance + kern);
    }
}

// ---------------------------------------------------------------------------
// Text laid into a box -- RenderTextIntoRectangle (retail 0x00144ed0)
// ---------------------------------------------------------------------------

// The word-wrap's isspace (0x00144a68) without its NUL: the callers here
// stop at the NUL themselves, where retail's space skip runs past it.
static bool rect_space(unsigned char c)
{
    return c == ' ' || c == '\t';
}

// GetNextWord (0x00144e70) into GetStringWidth (0x00144e28): the advances
// of the glyphs from `p` to the next space, tab or NUL, summed, times
// ScaleX. A character with no glyph adds nothing. Retail copies the word
// into 256 bytes first with no bound; this stops at 255.
static float rect_word_width(UIFont* f, const char* p, float scaleX)
{
    float sum = 0.0f;
    for (int n = 0; n < 255 && p[n] && !rect_space((unsigned char)p[n]);
         n++) {
        BGlyph g;
        if (bfont_glyph(&f->font, (unsigned char)p[n], &g)) sum += g.advance;
    }
    return sum * scaleX;
}

// RenderCharacter (0x00141a98) with RenderTextIntoRectangle's box: the
// glyph's quad at the pen, its width times ScaleX twice and its height
// times ScaleY, as draw_character(). MaybeClipPoly (0x00141808) then drops
// the quad when it is wholly left of, right of, above or below the box,
// and otherwise cuts it to the box -- left, right, top, bottom, in that
// order -- moving the sheet rectangle in step.
static void draw_clipped_character(UIRenderer* r, UIFont* f, const BGlyph* g,
                                   float x, float y, float w, float h,
                                   uint32_t color, const UIView* v,
                                   const UIClipBox* s)
{
    UITexture* t = font_sheet(r, f);
    if (!t || w <= 0.0f || h <= 0.0f) return;

    float x0 = x, x1 = x + w, y0 = y, y1 = y + h;
    float u0 = g->posX, u1 = g->posX + g->width;
    float v0 = g->posY, v1 = g->posY + g->height;
    if (x1 < s->tlx || s->brx <= x0 || y1 < s->tly || s->bry <= y0) return;
    if (x0 < s->tlx) {
        float k = (s->tlx - x0) / (x1 - x0);
        u0 += k * (u1 - u0);
        x0 = s->tlx;
    }
    if (s->brx <= x1) {
        float k = (x1 - s->brx) / (x1 - x0);
        u1 -= k * (u1 - u0);
        x1 = s->brx;
    }
    if (y0 < s->tly) {
        float k = (s->tly - y0) / (y1 - y0);
        v0 += k * (v1 - v0);
        y0 = s->tly;
    }
    if (s->bry <= y1) {
        float k = (y1 - s->bry) / (y1 - y0);
        v1 -= k * (v1 - v0);
        y1 = s->bry;
    }
    if (x1 <= x0 || y1 <= y0) return;

    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)t->tex.width, (float)t->tex.height, u0,
                       v0, u1 - u0, v1 - v0);

    C2D_ImageTint tint;
    C2D_PlainImageTint(&tint, color, 1.0f);

    C2D_Image img = { &t->tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = v->originX + x0 * v->scaleX;
    p.pos.y = v->originY + y0 * v->scaleY;
    p.pos.w = (x1 - x0) * v->scaleX;
    p.pos.h = (y1 - y0) * v->scaleY;
    draw_image(img, &p, &tint, true);
}

// RenderCharacter's colour: each byte of the text's times the scale,
// truncated.
static uint32_t scale_color(uint32_t rgba, float scale)
{
    uint32_t out = 0;
    if (scale == 1.0f) return rgba;
    for (int i = 0; i < 32; i += 8) {
        float b = (float)((rgba >> i) & 0xff) * scale;
        int   n = (int)b;
        if (n < 0)   n = 0;
        if (n > 255) n = 255;
        out |= (uint32_t)n << i;
    }
    return out;
}

// The inner's walk over one queued strip:
//   - the pen starts at the text object's top left;
//   - a button icon draws through RenderHelpCharacter, whose box is the
//     whole screen, and moves the pen by its unscaled advance;
//   - a glyph kerns against the byte before it in the string, whatever it
//     was, scaled and with no limit, and moves the pen by
//     (int)(ScaleX * (advance + kerning)) before anything is decided;
//   - after a space or a tab, the next word's width decides: past the box's
//     right edge, measured from the object's left, the line breaks;
//   - '@' always breaks it;
//   - a line break moves the pen to the left and down (int)(font height);
//   - a character that broke the line or has no glyph is not drawn, and the
//     spaces and tabs after it are skipped.
static void draw_text_rect(UIRenderer* r, const UITextStrip* s,
                           const BUIObject* o, const UIView* v)
{
    UIFont* f = find_font(r, o->fontHash);
    // GetTextureInfo NULL: no strip at all.
    if (!f || !font_sheet(r, f)) return;

    const char* str   = s->text;
    const char* p     = str;
    float       x0    = o->x, x = o->x, y = o->y, sx = o->scaleX;
    float       width = s->brx - o->x;
    float       lineH = (float)(int)f->font.height;
    uint32_t    color = tint_color(scale_color(o->color, s->scale), v->alpha);
    unsigned char c   = (unsigned char)*p++;
    UIClipBox   box   = { s->tlx, s->tly, s->brx, s->bry };

    while (c != 0) {
        if (is_help_char(c)) {
            x += draw_help_character(r, c, x, y, o, color, v,
                                     s->helpLayout);
        } else {
            BGlyph g;
            bool   has = bfont_glyph(&f->font, c, &g);
            bool   brk = false;
            float  px = 0.0f, py = 0.0f;

            if (has) {
                float kern = 0.0f;
                if (p > str + 1)
                    kern = bfont_kerning(&f->font, (unsigned char)p[-2], c)
                           * sx;
                px = x + kern;
                py = y;
                x += (float)(int)(sx * (g.advance + kern));
            }
            if (rect_space(c)
                && width < rect_word_width(f, p, sx) + x - x0) {
                x = x0;
                y += lineH;
                brk = true;
            }
            if (c == '@' && !brk) {
                x = x0;
                y += lineH;
                brk = true;
            }
            if (!brk && has) {
                draw_clipped_character(r, f, &g, px, py,
                                       g.width * sx * sx,
                                       g.height * o->scaleY, color, v, &box);
            } else {
                while (rect_space((unsigned char)*p)) p++;
            }
        }
        c = (unsigned char)*p++;
    }
}

bool uirender_queue_text_rect(UIRenderer* r, const BUI* ui, uint32_t index,
                              float tlx, float tly, float brx, float bry,
                              const char* text, float scale,
                              int32_t helpLayout)
{
    BUIObject o;
    uint32_t  s;

    if (!r || !ui || !text || r->numStrips >= UIR_MAX_STRIPS) return false;
    if (!bui_object(ui, index, &o) || o.type != BUI_TYPE_TEXT) return false;
    for (s = 0; s < ui->numScreens; s++) {
        const BUIScreen* sc = &ui->screens[s];
        if (index >= sc->first && index - sc->first < sc->count) break;
    }
    if (s == ui->numScreens) return false;

    UITextStrip* st = &r->strips[r->numStrips++];
    st->ui     = ui;
    st->index  = index;
    st->screen = s;
    st->tlx    = tlx;
    st->tly    = tly;
    st->brx    = brx;
    st->bry    = bry;
    st->scale  = scale;
    st->direct = false;
    st->helpLayout = helpLayout == UIR_HELP_LAYOUT_LIVE ? live_help_layout()
                                                        : helpLayout;
    snprintf(st->text, sizeof st->text, "%s", text);
    (void)helpglyph_rewrite(st->text, st->helpLayout);
    return true;
}

bool uirender_queue_text_rect_direct(UIRenderer* r, const BUI* ui,
                                     uint32_t index, float tlx, float tly,
                                     float brx, float bry, const char* text,
                                     float scale, int32_t helpLayout)
{
    if (!uirender_queue_text_rect(r, ui, index, tlx, tly, brx, bry, text,
                                  scale, helpLayout))
        return false;
    r->strips[r->numStrips - 1].direct = true;
    return true;
}

bool uirender_queue_copy(UIRenderer* r, const BUI* ui, uint32_t index,
                         const BUIObject* o, const char* text, float alpha,
                         const float* clip)
{
    uint32_t s;

    if (!r || !ui || !o || r->numCopies >= UIR_MAX_COPIES) return false;
    for (s = 0; s < ui->numScreens; s++) {
        const BUIScreen* sc = &ui->screens[s];
        if (index >= sc->first && index - sc->first < sc->count) break;
    }
    if (s == ui->numScreens) return false;

    UICopy* c = &r->copies[r->numCopies++];
    c->ui     = ui;
    c->screen = s;
    c->o      = *o;
    c->alpha  = alpha;
    c->clip   = clip != NULL;
    if (clip) {
        c->tlx = clip[0];
        c->tly = clip[1];
        c->brx = clip[2];
        c->bry = clip[3];
    }
    if (text && o->type == BUI_TYPE_TEXT) {
        size_t n = 0;
        while (n < UIR_COPY_TEXT - 1 && text[n]) {
            c->text[n] = text[n];
            n++;
        }
        c->text[n]     = 0;
        c->o.string     = c->text;
        c->o.maxChars   = (uint32_t)n;
        c->o.languageID = 0;
    }
    return true;
}

void uirender_clear_strips(UIRenderer* r)
{
    if (!r) return;
    r->numStrips = 0;
    r->numCopies = 0;
}

// GetScaledWidth__16FlailerTextChunk (0x0013e8b0) and GetScaledHeight
// (0x0013e858), which are what ScaleAboutCenter divides to find the centre
// it scales about. Width is the same sum draw_text_clipped() lays down; height is
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

// One character's glyph and its sheet (NULL when the font has none), from
// the run's own font or -- for a button icon -- help_glyph's, in the live
// layout: the bottom screen's help line names the keys the menu up hears.
// Same test as draw_text_clipped(); see IsHelpCharacter.
static bool wrap_glyph(UIRenderer* r, UIFont* f, unsigned char ch,
                       C3D_Tex** outTex, BGlyph* out)
{
    if (is_help_char(ch)) {
        *outTex = help_glyph(r, ch, live_help_layout(), out);
        return *outTex != NULL;
    }
    *outTex = font_tex(r, f);
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
        C3D_Tex*      gt;
        BGlyph        g;
        float         adv = 0.0f;

        // A hard break in the string itself: a newline, or '@', which
        // breaks a line in all of retail's text (draw_text_rect above).
        if (ch == 10 || ch == '@') {
            ln.draw = i; ln.next = i + 1; ln.width = w * scale;
            return ln;
        }
        if (wrap_glyph(r, f, ch, &gt, &g)) {
            bool own = !is_help_char(ch);
            if (KERNING_ENABLED && prev >= 0 && own)
                adv += bfont_kerning(&f->font, prev, ch);
            adv += g.advance;
            prev = own ? (int)ch : -1;
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
                C3D_Tex*      gt;
                BGlyph        g;
                bool          own = !is_help_char(ch);
                if (!wrap_glyph(r, f, ch, &gt, &g)) { prev = -1; continue; }
                if (KERNING_ENABLED && prev >= 0 && own)
                    penX += bfont_kerning(&f->font, prev, ch) * scale;
                draw_glyph(gt, &g, penX, top,
                           g.width * scale, g.height * scale, color, &v,
                           false);
                penX += g.advance * scale;
                prev = own ? (int)ch : -1;
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
    // The same truncation draw_bitmap_clipped() does, because the original takes the
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

bool uirender_draw_texture(UIRenderer* r, uint32_t hash, float x, float y,
                           float w, float h, uint32_t left, uint32_t right,
                           float alpha)
{
    if (!r || w <= 0.0f || h <= 0.0f) return false;
    int idx = find_texture(r, hash);
    if (idx < 0) return false;
    UITexture* t = &r->textures[idx];
    if (!t->valid) return false;

    Tex3DS_SubTexture st;
    subtex_from_pixels(&st, (float)t->tex.width, (float)t->tex.height, 0.0f,
                       0.0f, (float)t->w, (float)t->h);
    const uint32_t colors[4] = { left, right, right, left };
    C2D_ImageTint  tint;
    fill_tint(&tint, colors, alpha);

    C2D_Image      img = { &t->tex, &st };
    C2D_DrawParams p;
    memset(&p, 0, sizeof(p));
    p.pos.x = x;
    p.pos.y = y;
    p.pos.w = w;
    p.pos.h = h;
    draw_image(img, &p, &tint, true);
    end_gs_scale();
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

// The box an object's ClipToPoly cuts it to, as the screen render loop
// (0x00145f30) works it out: the first object of that name on the screen,
// visible or not. A text object is cut only when its FormatOptions has
// FORMAT_CLIP, to the poly's integer GetWidth/GetHeight with 4 off the left
// (RenderFlailerText's min and max); a bitmap always, to its float size
// (SetFlailerTextClipWindow, 0x00141798). False: drawn whole.
static bool poly_clip_box(UIRenderer* r, const BUI* ui,
                          const BUIScreen* screen, const BUIObject* o,
                          UIClipBox* box)
{
    if (!o->clipToPoly) return false;
    if (o->type == BUI_TYPE_TEXT && !(o->format & BUI_FMT_CLIP)) return false;
    for (uint32_t i = 0; i < screen->count; i++) {
        uint32_t  idx = screen->first + i;
        BUIObject p;
        if (!bui_object(ui, idx, &p) || p.nameHash != o->clipToPoly) continue;
        float w = 0.0f, h = uirender_object_height(r, ui, idx);
        if (p.type == BUI_TYPE_BITMAP) {
            int32_t tw, th;
            if (uirender_texture_size(r, p.textureHash, &tw, &th))
                w = (float)tw * p.scaleX;
        } else {
            w = (float)uirender_object_width(r, ui, idx);
        }
        if (o->type == BUI_TYPE_TEXT) {
            box->tlx = p.x + 4.0f;
            box->brx = p.x + (float)(int32_t)w;
            box->bry = p.y + (float)(int32_t)h;
        } else {
            box->tlx = p.x;
            box->brx = p.x + w;
            box->bry = p.y + h;
        }
        box->tly = p.y;
        return true;
    }
    return false;
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
    UIClipBox box;
    bool      clip = poly_clip_box(r, ui, screen, &o, &box);
    if (o.type == BUI_TYPE_BITMAP)
        draw_bitmap_clipped(r, &o, &ov, clip ? &box : NULL);
    else if (o.type == BUI_TYPE_TEXT)
        draw_text_clipped(r, &o, &ov, clip ? &box : NULL);
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
           && (target == UIR_TARGET_TOP || screen_placed(r, screen));
}

// Whether a screen's objects can draw on `target` at all, shown or not.
static bool screen_targets(const UIRenderer* r, const BUIScreen* screen,
                           int target)
{
    return target == UIR_TARGET_TOP || screen_placed(r, screen);
}

// The copies and the strips queued for `layer`, after its objects: each
// where its screen draws on `target`, moved by its object's placement.
static void draw_strips(UIRenderer* r, int layer, float alpha, int target)
{
    for (int i = 0; i < r->numCopies; i++) {
        const UICopy*    c      = &r->copies[i];
        const BUIScreen* screen = &c->ui->screens[c->screen];

        if (c->o.z != layer || !screen_targets(r, screen, target)) continue;
        const UIPlacement* p =
            screen_placed(r, screen) ? placement_of(r, screen, &c->o) : NULL;
        if ((p ? p->target : UIR_TARGET_TOP) != target) continue;
        UIView v = screen_view(r, screen, alpha * c->alpha);
        if (p) {
            v.originX += p->dx * v.scaleX;
            v.originY += p->dy * v.scaleY;
        }
        UIClipBox box = { c->tlx, c->tly, c->brx, c->bry };
        if (c->o.type == BUI_TYPE_BITMAP)
            draw_bitmap_clipped(r, &c->o, &v, c->clip ? &box : NULL);
        else if (c->o.type == BUI_TYPE_TEXT)
            draw_text_clipped(r, &c->o, &v, c->clip ? &box : NULL);
    }
    for (int i = 0; i < r->numStrips; i++) {
        const UITextStrip* s      = &r->strips[i];
        const BUIScreen*   screen = &s->ui->screens[s->screen];
        BUIObject          o;

        if (!bui_object(s->ui, s->index, &o) || o.z != layer) continue;
        if (s->direct ? !screen_targets(r, screen, target)
                      : !screen_drawn(r, screen, target))
            continue;
        const UIPlacement* p =
            screen_placed(r, screen) ? placement_of(r, screen, &o) : NULL;
        if ((p ? p->target : UIR_TARGET_TOP) != target) continue;
        UIView v = screen_view(r, screen, alpha);
        if (p) {
            v.originX += p->dx * v.scaleX;
            v.originY += p->dy * v.scaleY;
        }
        draw_text_rect(r, s, &o, &v);
    }
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
            draw_strips(r, layer, alpha, target);
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
        draw_strips(r, layer, alpha, target);
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

void uirender_draw_visible_bottom_over(UIRenderer* r, float targetW,
                                       float targetH, float alpha)
{
    float w = r->targetW, h = r->targetH;

    r->targetW = targetW;
    r->targetH = targetH;
    C2D_SetTintMode(C2D_TintMult);
    draw_visible(r, alpha, UIR_TARGET_BOTTOM_OVER, 0, BUI_NUM_LAYERS);
    end_gs_scale();
    r->targetW = w;
    r->targetH = h;
}
#endif  // __3DS__
