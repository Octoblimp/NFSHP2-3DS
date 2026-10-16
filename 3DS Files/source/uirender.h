#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "bfont.h"
#include "bui.h"
#include "langtab.h"
#include "texpack.h"

// Draws Flailer screens (bui.c) with citro2d. This is the 3DS half of the UI
// system: bui.c gives you the layout, this resolves the texture, font and
// string hashes against the loaded bundles and puts quads on the screen.
//
// Everything it does comes from the renderer's own code rather than from
// guessing -- Render__16FlailerTextChunk (0x0013ff40), RenderCharacter
// (0x0013f698), RenderStringFixedWidth (0x0013fb78) and
// RenderSingleFlailerBitmap (0x00140538). Where the engine does something
// surprising the comment says so and names the address.
//
// Not implemented, because nothing on this disc uses it: the objects' own
// word wrap (BUI_FMT_WRAP) and clipping (BUI_FMT_CLIP); the word wrap
// and clipping of RenderTextIntoRectangle are uirender_queue_text_rect's. RenderOnPoly/ClipToPoly are
// likewise unset on every object in this build.

#define UIR_MAX_BUNDLES  4
#define UIR_MAX_TEXTURES 256
#define UIR_MAX_FONTS    16
#define UIR_MAX_HIDDEN   8

// The two screens an object can draw on. See UIPlacement. BOTTOM_OVER is
// the bottom screen too, drawn after the minimap, so it shows over it.
#define UIR_TARGET_TOP         0
#define UIR_TARGET_BOTTOM      1
#define UIR_TARGET_BOTTOM_OVER 2

// Where one object of one screen draws, or every object of one group:
// the top screen or the bottom, moved by (dx, dy) in the screen's 640x480
// space. The port's own -- the PS2 had one screen -- and set by
// uirender_set_placements. A nameHash of 0 matches by groupHash instead.
typedef struct {
    uint32_t screenHash;
    uint32_t nameHash;
    uint32_t groupHash;
    uint8_t  target;     // UIR_TARGET_*
    float    dx, dy;
} UIPlacement;

// The button icons embedded in UI strings. Retail's IsHelpCharacter
// (0x00141db0) is `(u8)(c + 128) < 30 && c != 0x92`, and RenderHelpCharacter
// maps each to a glyph of the BUTTONSOUT font through a 30-byte table at
// 0x002f09c0. (The demo's was 18 wide.)
#define UIR_HELP_FIRST 0x80
#define UIR_HELP_COUNT 30

#ifdef __3DS__
#include <citro2d.h>

typedef struct {
    uint32_t hash;
    C3D_Tex  tex;
    uint16_t w, h;
    bool     valid;

    // A texture the caller owns, drawn instead of the bundle's own. The movie
    // player needs this: the title screen's planes are authored against
    // SPLASH_SCREEN, which on the disc is 512x256 of opaque black -- the blit
    // target, not art -- and the port decodes the movie into a texture of its
    // own rather than into the bundle's.
    C3D_Tex* override;
    uint16_t overrideW, overrideH;
    bool     overrideFill;   // drawn across the whole target; see draw_bitmap

    // The TextureInfo scroll fields, kept so draw_bitmap() does not have to
    // reopen the pack every frame. See texpack_scroll().
    int8_t   scrollType;
    float    scrollS, scrollT, scrollStep;

    // A slot uirender_forget_texture() gave back, for the next new hash.
    bool     unused;
} UITexture;

typedef struct {
    uint32_t hash;
    BFont    font;
    int      sheet;      // texture-cache index of the glyph sheet, or -1
    float    fixedCell;  // Font::FixedWidthCell -- see uirender.c
} UIFont;

typedef struct {
    uint8_t* data;
    size_t   len;
    BUI      ui;
    bool     hasUI;
    // A Flailer chunk the port rebuilt (debugmenu.h), which `ui` reads in
    // place of the one in `data`; NULL for the others. Freed with them.
    uint8_t* uiData;
} UIBundle;

// Text RenderTextIntoRectangle (retail 0x00144ed0) lays into a box, one
// frame's: the RENDER the current screen gets queues it, and the draw puts
// it in its text object's layer after that layer's objects, as
// AddFlailerStrip appends to LayerRenderInfoTable[Z]. See
// uirender_queue_text_rect().
#define UIR_MAX_STRIPS   4
#define UIR_STRIP_TEXT   512   // the Blurb's bSPrintf buffer

typedef struct {
    const BUI* ui;
    uint32_t   index;          // the text object
    uint32_t   screen;         // its screen's index in ui->screens
    float      tlx, tly;       // the box, in the screen's 640x480 space
    float      brx, bry;
    float      scale;          // the colour's, RenderCharacter's last float
    int32_t    helpLayout;     // the joyhid layout its button icons name
    bool       direct;         // drawn whatever its screen's visibility
    char       text[UIR_STRIP_TEXT];
} UITextStrip;

// A copy of an object drawn this frame, the way RenderFlailerBitmap
// (retail 0x00143078) and RenderFlailerText (0x00142260) draw one: in the
// copy's layer after that layer's objects, whatever the visibility of the
// object or its screen. See uirender_queue_copy().
#define UIR_MAX_COPIES   256
#define UIR_COPY_TEXT    32

typedef struct {
    const BUI* ui;
    uint32_t   screen;         // its screen's index in ui->screens
    BUIObject  o;              // the copy; a text's string is `text`
    float      alpha;          // times the frame's
    bool       clip;           // cut to the box below (MaybeClipPoly)
    float      tlx, tly, brx, bry;
    char       text[UIR_COPY_TEXT];
} UICopy;

// uirender_queue_text_rect's layout for the keys the live one has (the
// race's while it runs, the menus' otherwise).
#define UIR_HELP_LAYOUT_LIVE (-1)

typedef struct {
    UIBundle  bundles[UIR_MAX_BUNDLES];
    int       numBundles;
    UITexture textures[UIR_MAX_TEXTURES];
    int       numTextures;
    UIFont    fonts[UIR_MAX_FONTS];
    int       numFonts;

    uint8_t*  langData;
    size_t    langLen;
    LangTable lang;
    bool      hasLang;

    // Objects the port draws somewhere else, by NameHash. See
    // uirender_hide_object().
    uint32_t  hidden[UIR_MAX_HIDDEN];
    int       numHidden;

    // Where objects draw, the caller's table. See
    // uirender_set_placements().
    const UIPlacement* placements;
    int                numPlacements;

    // This frame's text laid into boxes. See
    // uirender_queue_text_rect().
    UITextStrip strips[UIR_MAX_STRIPS];
    int         numStrips;

    // This frame's object copies. See uirender_queue_copy().
    UICopy      copies[UIR_MAX_COPIES];
    int         numCopies;

    // The port's sheet of the 3DS's buttons (helpglyph.h), made from
    // data/buttons3ds.bin on first use: 0 not yet, 1 made, -1 failed.
    C3D_Tex   iconTex;
    int       iconState;

    float     targetW, targetH;   // the C3D render target, e.g. 400x240
    float     scrollTime;         // seconds, for UV-scrolling textures
    int       missingTextures;    // counters, for a bring-up overlay
    int       missingFonts;
    int       missingStrings;
} UIRenderer;

// citro2d must already be initialised. targetW/targetH are the render
// target's size; a 640x480 screen is fitted into it preserving aspect.
void uirender_init(UIRenderer* r, float targetW, float targetH);
void uirender_free(UIRenderer* r);

// Loads a .BUN/.BIN, keeps it resident, and registers any Flailer project
// and font chunks in it. Textures are decoded lazily on first use.
bool uirender_add_bundle(UIRenderer* r, const char* path);

// Loads a LANGUAGES\FE_*.BIN. Without one, text objects fall back to the
// authoring placeholder baked into the chunk, which is routinely stale.
bool uirender_set_language(UIRenderer* r, const char* path);

// Finds a screen by bStringHash of its name across every loaded bundle.
BUIScreen* uirender_find_screen(UIRenderer* r, uint32_t nameHash, BUI** outUI);

// Screens across every loaded bundle, in load order, so a bring-up viewer
// can page through all 76 without knowing any names. Returns NULL past the
// end; *outUI receives the project the screen belongs to.
BUIScreen* uirender_screen_at(UIRenderer* r, uint32_t index, BUI** outUI);

// How many screens uirender_screen_at() can reach.
uint32_t uirender_screen_count(const UIRenderer* r);

// The clock UV-scrolling textures run off. RenderSingleFlailerBitmap
// (0x00140538) reads the global RealTimer and scales it by 0.00025, i.e.
// RealTimer counts 1/4000 s; gameflow.c keeps the same counter, so a caller
// with a GameFlow passes gf->realTimer * 0.00025f. Nothing scrolls until
// this is called, because it starts at zero and a zero time scrolls nothing.
void uirender_set_time(UIRenderer* r, float seconds);

// Draws `tex` wherever `hash` would be drawn, at `w` x `h`. Passing NULL for
// `tex` puts the bundle's own texture back. This is how a movie reaches the
// screen -- see avimovie.h and MOVIE_PLANE_43 in gameflow.h.
//
// With `fill`, an object drawing it covers the whole render target instead
// of its own rectangle: the port's own departure, so the movies fill the
// top screen rather than sit in the planes the PS2's TV layout put them in.
void uirender_override_texture(UIRenderer* r, uint32_t hash, C3D_Tex* tex,
                               uint16_t w, uint16_t h, bool fill);

// Gives back the slot of a hash no bundle has, and its override with it, so
// a caller that draws many such hashes over time through overrides -- Select
// Track's slideshow, 159 pictures -- does not fill the table. A hash a
// bundle has keeps its slot.
void uirender_forget_texture(UIRenderer* r, uint32_t hash);

// Draws one screen: layers 0..28 in order, objects in file order within a
// layer, which is what FlailerRenderManager's LayerRenderInfoTable does.
// `alpha` is the renderer's global fade, the float every Render() takes.
void uirender_draw_screen(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                          float alpha);

// Draws every screen whose `visible` is set, as eDisplayFrame does: all of
// them share the one layer table, so each layer is drawn across every screen
// before the next. This is how LOADING_TRACK shows under the language screen
// while the frontend loads, and how the flow's screens reach the display.
void uirender_draw_visible(UIRenderer* r, float alpha);

// Passes [from, to) of that walk, BUI_LAYER_ORDER's indices. The frontend's
// eDisplayFrame draws the first UIR_BACK_PASSES of them, layers 24 to 20,
// before its 3D -- the car select's cars and platform -- and the rest
// after.
#define UIR_BACK_PASSES 5
void uirender_draw_visible_passes(UIRenderer* r, float alpha, int from,
                                  int to);

// The scaled width and height of a text object, as FlailerTextChunk's own
// GetScaledWidth/GetScaledHeight compute them -- the pair ScaleAboutCenter
// needs. False if the object is not text; true with both zero if its font
// is missing, which is what the originals return too.
bool uirender_text_extent(UIRenderer* r, const BUI* ui, uint32_t index,
                          float* outW, float* outH);

// FlailerGetBoundingBox (0x00141ed0) for one object, in the screen's own
// 640x480 space: box = { left, top, right, bottom }. Only bitmaps have a
// size the renderer can answer for -- it is the same (int)(texW * ScaleX)
// by (int)(texH * ScaleY) rectangle draw_bitmap() lays down -- so a text
// object or a missing texture returns false. bscreens.c needs this to put
// the two highlight brackets around the current menu item.
bool uirender_object_bounds(UIRenderer* r, const BUI* ui, uint32_t index,
                            float box[4]);

// FlailerObjectChunk::GetWidth (0x00140588), what FlailerGetWidth answers:
// a text object's GetScaledWidth (0x00140d30) truncated -- its glyphs'
// advances summed, no kerning and no fixed-width cell, times ScaleX -- and a
// bitmap's CalculateWidth, (int)(texture width * ScaleX). 0 for anything
// else, a missing font or a missing texture.
int32_t uirender_object_width(UIRenderer* r, const BUI* ui, uint32_t index);
// GetScaledWidth (0x00140d30) itself, the float: the advances of the text
// the object shows -- its language string when it has one -- summed, then
// times ScaleX. 0 if the object is not text or its font is missing.
float uirender_text_scaled_width(UIRenderer* r, const BUI* ui,
                                 uint32_t index);
// The Width and Height of the texture `hash` names, an override's if it
// has one: what FlailerBitmapChunk::GetTextureInfo (0x00141368) hands the
// size questions. False, with both 0, for a texture no bundle has.
bool uirender_texture_size(UIRenderer* r, uint32_t hash, int32_t* w,
                           int32_t* h);
// FlailerObjectChunk::GetHeightFloat (0x00140688): a text object's
// GetScaledHeight (0x00140cd8), ScaleY * (float)(int)font height, and a
// bitmap's CalculateHeightFloat (0x00141488), texture height * ScaleY with
// no truncation. GetHeight (0x001405e0) is this truncated, for both. 0 for
// anything else, a missing font or a missing texture.
float uirender_object_height(UIRenderer* r, const BUI* ui, uint32_t index);
// ---------------------------------------------------------------------------
// The port's own text
// ---------------------------------------------------------------------------
//
// Everything above draws what the disc authored, in the screen's 640x480
// space. This draws what the *port* needs to say -- the bottom-screen blurb
// panel and the bring-up overlays -- in the target's own pixels, with word
// wrap. FlailerTextChunk has a format bit for wrapping (BUI_FMT_WRAP) and no
// screen on this disc sets it, so there is no original to copy here.
//
// It deliberately does not reproduce RenderCharacter's double-ScaleX bug
// (0x0013f750). That bug is kept in the screen path because the disc's own
// layouts were drawn with it on screen; nothing here was, and a wrap width
// has to agree with the width actually laid down or the last word of every
// line hangs off the edge.
typedef struct {
    uint32_t fontHash;   // 0 for the first loaded font that has a sheet
    uint32_t color;      // a plain C2D_Color32 -- NOT a PS2 colour word
    float    scale;      // multiplies the font's own glyph sizes
    float    lineGap;    // extra pixels between one line and the next
    bool     center;     // centre each line inside the box
} UIWrapStyle;

// The height of one line in this style, the gap included. 0 if the font is
// not loaded, which is also what a caller should treat as "draw nothing".
float uirender_line_height(UIRenderer* r, const UIWrapStyle* st);

// How tall `text` comes out wrapped into `boxW` pixels, drawing nothing.
// `len` is the string length, or 0 for strlen.
float uirender_wrap_height(UIRenderer* r, const char* text, size_t len,
                           const UIWrapStyle* st, float boxW);

// Draws it into whatever target C2D_SceneBegin has bound -- (x, y) is the
// top-left of the box -- and returns the height used. Lines break at a
// space, at a newline in the string, and inside a word wider than the box
// on its own. `alpha` scales the style's colour, for a fade.
float uirender_draw_wrapped(UIRenderer* r, const char* text, size_t len,
                            const UIWrapStyle* st, float x, float y,
                            float boxW, float alpha);

// The string a text object draws this frame: the row of the language table
// its LanguageID names, or the placeholder baked into the chunk when it has
// none. The blurb panel mirrors this rather than listening for changes --
// tAnimatedBlurb resolves the translation itself and prints the result into
// the object (banim.c:620), so the object is the only place the line the
// player is meant to be reading actually exists.
const char* uirender_object_string(UIRenderer* r, const BUI* ui,
                                   uint32_t index, size_t* outLen);

// An object the port draws somewhere else and the screen must not draw
// again, by NameHash -- SCROLLING_TEXT and its wipe bar, which now live on
// the bottom screen. Up to UIR_MAX_HIDDEN of them; a hash of 0 empties the
// list. This is a draw-time skip rather than a visibility write because the
// frontend's own animations set that field every frame.
void uirender_hide_object(UIRenderer* r, uint32_t nameHash);

// FlailerRenderManager::RenderTextIntoRectangle's inner (0x00144ed0):
// `text` laid out from text object `index`'s top left in its font, colour
// and ScaleX/ScaleY, word-wrapped where the next word would pass the box's
// right edge and at '@', and each glyph clipped to the box (MaybeClipPoly,
// 0x00141808). Queued for this frame's draw in the object's layer, whether
// the object is visible or not, as the PS2's strip is. False with nothing
// queued when the queue is full, the object is not text, or no screen of
// `ui` holds it.
//
// The port's own: its button icons are the keys of joyhid layout
// `helpLayout` (helpglyph.h), or UIR_HELP_LAYOUT_LIVE's, and the text is
// kept as helpglyph_rewrite has it there -- the pre-race Blurb names the
// keys of the race to come while the menus' are live.
bool uirender_queue_text_rect(UIRenderer* r, const BUI* ui, uint32_t index,
                              float tlx, float tly, float brx, float bry,
                              const char* text, float scale,
                              int32_t helpLayout);
// The same, drawn whatever the visibility of the text's screen: the
// event tree's details lay their text into a box on a screen that is
// never shown, as retail's do.
bool uirender_queue_text_rect_direct(UIRenderer* r, const BUI* ui,
                                     uint32_t index, float tlx, float tly,
                                     float brx, float bry, const char* text,
                                     float scale, int32_t helpLayout);

// RenderFlailerBitmap / RenderFlailerText for a copy `o` of object `index`
// of `ui`: queued for this frame's draw in o->z's layer, after its objects,
// at `alpha` times the frame's, whether the object or its screen is
// visible or not, and moved by the object's placement. A text copy draws
// `text` (at most UIR_COPY_TEXT - 1 characters) when it is not NULL, else
// o's own string or LanguageID. `clip`, when not NULL, is a box (x0, y0,
// x1, y1) in the screen's 640x480 space the copy is cut to, as
// MaybeClipPoly (0x00141808) cuts it: a bitmap with no rotation, and the
// glyphs of a text. False with nothing queued when the queue is full or no
// screen of `ui` holds the object.
bool uirender_queue_copy(UIRenderer* r, const BUI* ui, uint32_t index,
                         const BUIObject* o, const char* text, float alpha,
                         const float* clip);

// Empties the queues, the strips and the copies: once a frame, before the
// current screen's RENDER.
void uirender_clear_strips(UIRenderer* r);

// The table of where objects draw (UIPlacement): the first entry that
// matches an object wins, and an object with none draws on the top screen.
// The table stays the caller's and must outlive the renderer's use of it;
// NULL clears it. Like uirender_hide_object, this is a draw-time choice,
// so the game's own writes to the objects are left alone.
void uirender_set_placements(UIRenderer* r, const UIPlacement* table, int n);

// Draws the objects placed on the bottom screen, into a target of
// targetW x targetH with citro2d's scene already begun on it. Only screens
// with a placement are walked. A 640x480 screen is drawn at targetW / 640
// by targetH / 480, so on the 320x240 bottom screen each object keeps its
// place and its 4:3 shape. Answers whether any such screen was visible.
bool uirender_draw_visible_bottom(UIRenderer* r, float targetW,
                                  float targetH, float alpha);

// The same for the objects placed on UIR_TARGET_BOTTOM_OVER, drawn after
// whatever the caller put over the bottom screen's objects.
void uirender_draw_visible_bottom_over(UIRenderer* r, float targetW,
                                       float targetH, float alpha);
#endif  // __3DS__
