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

    float     targetW, targetH;   // the C3D render target, e.g. 400x240
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

// Draws `tex` wherever `hash` would be drawn, at `w` x `h`. Passing NULL for
// `tex` puts the bundle's own texture back. This is how a movie reaches the
// screen -- see movie.c and MOVIE_PLANE_43 in gameflow.h.
void uirender_override_texture(UIRenderer* r, uint32_t hash, C3D_Tex* tex,
                               uint16_t w, uint16_t h);

// Draws one screen: layers 0..28 in order, objects in file order within a
// layer, which is what FlailerRenderManager's LayerRenderInfoTable does.
// `alpha` is the renderer's global fade, the float every Render() takes.
void uirender_draw_screen(UIRenderer* r, BUI* ui, const BUIScreen* screen,
                          float alpha);

// FlailerGetBoundingBox (0x00141ed0) for one object, in the screen's own
// 640x480 space: box = { left, top, right, bottom }. Only bitmaps have a
// size the renderer can answer for -- it is the same (int)(texW * ScaleX)
// by (int)(texH * ScaleY) rectangle draw_bitmap() lays down -- so a text
// object or a missing texture returns false. bscreens.c needs this to put
// the two highlight brackets around the current menu item.
bool uirender_object_bounds(UIRenderer* r, const BUI* ui, uint32_t index,
                            float box[4]);
#endif  // __3DS__
