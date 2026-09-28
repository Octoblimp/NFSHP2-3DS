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
// Not implemented, because nothing on this disc uses it: word wrap
// (BUI_FMT_WRAP) and clipping (BUI_FMT_CLIP). RenderOnPoly/ClipToPoly are
// likewise unset on every object in this build.

#define UIR_MAX_BUNDLES  4
#define UIR_MAX_TEXTURES 256
#define UIR_MAX_FONTS    16
#define UIR_MAX_HIDDEN   8

// The button icons embedded in UI strings. IsHelpCharacter (0x0013f9a8) is
// literally `(u8)(c - 128) < 18`, and RenderHelpCharacter maps each to a
// glyph of the BUTTONSOUT font through an 18-byte table at 0x002e8a10.
#define UIR_HELP_FIRST 0x80
#define UIR_HELP_COUNT 18

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
} UIBundle;

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
#endif  // __3DS__
