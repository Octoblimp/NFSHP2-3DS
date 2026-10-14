#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Flailer -- bWare's UI system, chunk 0x80010200. Every screen in the game is
// a Flailer screen: the frontend menus, the HUD, the pause menus, the results
// tables. Layout and provenance: docs/formats/flailer-ui.md.
//
// This half is the data: walk the chunk, hand back screens and their objects
// with the fields already unpacked. It draws nothing and is free of <3ds.h>,
// so tools/bui_check.py can diff it against tools/flailer_dump.py. The
// citro2d side lives in uirender.c.
//
// What is *not* here, because it is not on disc: menus. FlailerMenu and
// FlailerMenuItem exist in the type info but no chunk of either ships --
// navigation and highlight behaviour are assembled in the frontend C++ from
// the objects a screen already contains, so they have to be ported
// separately. This gives you the layout, not the behaviour.

#define BUI_CHUNK_FLAILER   0x80010200u   // one per file
#define BUI_CHUNK_PROJECT   0x00010213u   // FlailerProjectChunk, 20 bytes
#define BUI_CHUNK_SCREEN    0x80010201u   // container, one per screen
#define BUI_CHUNK_SCREENDEF 0x00010203u   // FlailerScreenChunk, 40 bytes
#define BUI_CHUNK_BITMAP    0x00010210u   // FlailerBitmapChunk, 144 bytes
#define BUI_CHUNK_TEXT      0x00010212u   // FlailerTextChunk, 100 + MaxChars

// Retail's objects carry their own name, a char[24] at +16, which the demo's
// don't; everything the demo has from +16 on sits this much later, so the
// demo's bitmap is 120 bytes and its text 76 + MaxChars. bui.c reads either
// and tells them apart per object.
#define BUI_NAME_LEN 24

// The empty string's bStringHash, used as "unset" throughout the format.
#define BUI_HASH_NONE 0xffffffffu

// FlailerRenderManager::LayerRenderInfoTable has exactly this many slots and
// FlailerObjectChunk::Z indexes it directly.
#define BUI_NUM_LAYERS 29

// Back-to-front draw order for those 29 layers.
//
// Z is a layer index, not a depth: AddFlailerStrip (0x00143990) appends the
// object's strip to LayerRenderInfoTable[Z], and RenderLayer (0x00143a68)
// walks one such list in insertion order. eDisplayFrame calls RenderLayer
// from four separate loops, and every one of them counts DOWN, so a higher Z
// inside a group is further back:
//
//   0x00112b58   24 -> 20   before the world, with the render targets
//   0x00113680   15 -> 0    the main pass
//   0x001136c0   19 -> 16
//   0x00113708   28 -> 25   last, so 25 is the frontmost layer of all
//
// The four ranges cover 0..28 exactly once, which is how we know there is no
// fifth loop. Flattened, earliest drawn first:
#define BUI_LAYER_ORDER                                               \
    { 24, 23, 22, 21, 20,                                             \
      15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,           \
      19, 18, 17, 16,                                                 \
      28, 27, 26, 25 }

typedef enum {
    BUI_TYPE_NONE = 0, BUI_TYPE_TEXT, BUI_TYPE_BITMAP,
    BUI_TYPE_POINT, BUI_TYPE_LINE, BUI_TYPE_SCREEN,
} BUIObjectType;

typedef enum {
    BUI_INVISIBLE = 0, BUI_VISIBLE, BUI_PSX2_ONLY, BUI_XBOX_ONLY,
} BUIVisibility;

typedef enum {
    BUI_ROTATE_NONE = 0, BUI_ROTATE_AROUND, BUI_ROTATE_CENTER,
    BUI_ROTATE_LEFT, BUI_ROTATE_RIGHT, BUI_TRANSLATE_LEFT,
    BUI_TRANSLATE_RIGHT, BUI_ANIMATE_LEFT, BUI_ANIMATE_RIGHT,
    BUI_SLIDE_UP, BUI_TACH_GRADIENT,
} BUIAnimation;

// FormatOptions. These are #defines in the original, so they are not in the
// type info -- the bit values come from Render__16FlailerTextChunk itself.
// Declaration order is not bit order: RIGHT is 0x01 and CENTER is 0x04, and
// swapping them right-aligns every centred label in the game.
#define BUI_FMT_RIGHT       0x01
#define BUI_FMT_LEFT        0x02   // the default; never actually tested
#define BUI_FMT_CENTER      0x04
#define BUI_FMT_DARKBG      0x08
#define BUI_FMT_CLIP        0x10
#define BUI_FMT_WRAP        0x20
#define BUI_FMT_FIXEDWIDTH  0x40

typedef struct {
    uint32_t nameHash;
    uint32_t groupHash;      // FlailerSetGroupVisibility's key
    char     name[BUI_NAME_LEN + 1];   // retail only; "" on the demo's
    int8_t   type;           // BUIObjectType -- what the renderer switches on
    int8_t   visible;        // BUIVisibility
    int8_t   z;              // render layer, 0..28
    float    x, y;           // top-left, in the screen's 640x480 space
    float    scaleX, scaleY;
    int32_t  rotation;
    int32_t  animation;      // BUIAnimation
    uint32_t renderOnPoly;   // nameHash of the object to draw onto
    uint32_t clipToPoly;     // nameHash of the object to clip against
    // The object itself on retail's layout, the FlailerObjectChunk
    // (flailer.h) the setters write; NULL on the demo's.
    const uint8_t* chunk;

    // BUI_TYPE_BITMAP
    uint32_t textureHash;
    uint32_t colors[4];      // per-corner RGBA, PS2 scale: 0x80 is full
    float    uv[8];          // four (u,v) corners

    // BUI_TYPE_TEXT
    uint32_t fontHash;
    uint32_t format;         // BUI_FMT_*
    uint32_t color;
    uint32_t languageID;     // 0, or the key into FE_*.BIN that wins
    const char* string;      // the authoring placeholder -- routinely stale
    uint32_t maxChars;
} BUIObject;

typedef struct {
    uint32_t nameHash;
    uint16_t resX, resY;     // 640x480 on every screen on disc
    uint16_t numObjects;     // the chunk's own count
    uint32_t first;          // index into BUI::objects
    uint32_t count;          // objects actually parsed
    // The loader forces every screen invisible at load and the game turns
    // one on with FlailerSetScreenVisibility, so the file's Visible field is
    // padding. This is the runtime state, and it starts out false.
    bool     visible;
    // The screen chunk's own payload, which is what retail's
    // FindFlailerScreen hands back (flailer.h). NULL for a container that
    // has none, which the loader never links.
    const uint8_t* def;
} BUIScreen;

typedef struct {
    const uint8_t* payload;
    uint32_t       size;
    uint32_t       shift;    // BUI_NAME_LEN on retail's layout, 0 the demo's
} BUIObjectRef;

typedef struct {
    uint32_t      projectHash;
    BUIScreen*    screens;
    uint32_t      numScreens;
    BUIObjectRef* objects;   // every object in the file, screens index in
    uint32_t      numObjects;
} BUI;

// Parses the first 0x80010200 chunk in buf[off, off+len), allocating the
// screen and object tables. The buffer must outlive the BUI: nothing is
// copied, and object payloads are pointers into it.
bool bui_open(BUI* ui, const uint8_t* buf, size_t off, size_t len);
void bui_close(BUI* ui);

// The screen with this NameHash, or NULL. Names come from ELF literals --
// NEW_MAIN_MENU, RACE_RESULTS, PAUSE_AUDIO -- via bchunk_hash().
BUIScreen* bui_find_screen(BUI* ui, uint32_t nameHash);

// Unpacks object `index` (absolute, i.e. screen->first + n).
bool bui_object(const BUI* ui, uint32_t index, BUIObject* out);

// Object `index`'s Visible (BUIVisibility) and Z, as bui_object reads
// them, without the rest. False where bui_object fails on the fields
// every object has.
bool bui_object_layer(const BUI* ui, uint32_t index, int* visible, int* z);

// Finds an object by NameHash inside one screen. `type` is a BUIObjectType
// to require, or BUI_TYPE_NONE for "any" -- FindFlailerObject (0x001419c8)
// only compares Type when the argument is non-zero. Returns an absolute
// object index for bui_object(), or -1.
int32_t bui_find_object(const BUI* ui, const BUIScreen* screen,
                        uint32_t nameHash, int type);

// Walks the objects on a screen that carry a GroupHash. -1 for `after`
// starts at the head; feed the previous result back to get the next one.
// Returns -1 when there are no more. GroupHash is not a name -- several
// objects share one, which is the whole point of a group.
int32_t bui_next_in_group(const BUI* ui, const BUIScreen* screen,
                          uint32_t groupHash, int type, int32_t after);

// Writes a text object's Color back into the loaded chunk, which is how the
// engine changes one: the renderer reads FlailerTextChunk::Color out of the
// bundle every frame and there is no separate runtime copy.
// SetColor__16FlailerTextChunk (0x0013e820) replaces only the low 24 bits
// and keeps the chunk's existing alpha, so this does too -- writing the
// whole word would force every recoloured label to full opacity.
//
// The buffer handed to bui_open() has to be writable for this. It is: the
// port keeps each bundle as a heap copy (UIBundle::data) and bui.c points
// into it rather than copying payloads.
bool bui_set_text_color(BUI* ui, uint32_t index, uint32_t rgb);

// The whole Color word, alpha too, with DirtyFlag left alone: the plain
// store ~FlailerMenuItem (0x001697a0) makes to put back the colour it read
// when the menu was made.
bool bui_put_text_color(BUI* ui, uint32_t index, uint32_t color);

// Repoints a text object at a different row of the language table --
// tAnimatedBlurb::NewText (0x00232ef0), which is how the one blurb line on
// a menu screen says something different about each item. Same caveat about
// a writable buffer.
bool bui_set_text_language(BUI* ui, uint32_t index, uint32_t languageID);

// Moves an object. Same caveat about a writable buffer.
bool bui_set_object_pos(BUI* ui, uint32_t index, float x, float y);

// FlailerObjectChunk::SetClipToPoly: ClipToPoly, and FORMAT_CLIP on a text
// object. uirender.c does not clip yet, so this only records it. Same
// caveat about a writable buffer.
bool bui_set_object_clip(BUI* ui, uint32_t index, uint32_t poly);

// FlailerSetVisibility: writes BUIVisibility back into the loaded chunk.
// Note the polarity -- BUI_INVISIBLE is 0 and BUI_VISIBLE is 1, which is the
// OPPOSITE of FlailerScreenVisibility on a screen. See gameflow.h.
bool bui_set_object_visible(BUI* ui, uint32_t index, int visibility);

// An object's alpha: the top byte of its colour word, or of one of a
// bitmap's four corner words. `corner` is ignored on a text object, exactly
// as FlailerObjectChunk::GetAlpha ignores it. -1 if the object has no
// colour (a group node, or a chunk too short to hold one).
int bui_get_object_alpha(const BUI* ui, uint32_t index, int corner);

// Writes it back. On a bitmap, corner -1 means all four -- that is the
// FlailerBitmapChunk::SetAlpha convention and the only one the frontend's
// fades use. Same caveat about a writable buffer.
bool bui_set_object_alpha(BUI* ui, uint32_t index, int corner, int alpha);

// Writes ScaleX/ScaleY. Same caveat about a writable buffer.
bool bui_set_object_scale(BUI* ui, uint32_t index, float sx, float sy);

// Repoints a bitmap object at another texture by hash --
// FlailerBitmapChunk::ChangeTexture (0x0013eee0). Same caveat about a
// writable buffer.
bool bui_set_bitmap_texture(BUI* ui, uint32_t index, uint32_t textureHash);

// Replaces a text object's inline string, truncating to the room the chunk
// has. Returns the number of characters kept, 0 if the object is not text.
// Note this only shows through if LanguageID is 0: the renderer prefers the
// language table whenever one is set. See uirender.c's object_text().
uint32_t bui_set_text_string(BUI* ui, uint32_t index, const char* s);

// CopyFlailerText (0x0013ec18; retail 0x001410a0, the same but for the
// name's shift): src's 64 bytes from ObjectType on, over dst's -- the
// visibility, Z, position, scale, font, format, colour, LanguageID and the
// String pointer, all of it but the two hashes and dst's pFlailerStrip --
// then DirtyFlag 8. On the PS2 the two then share one string; here each
// keeps its characters inline, so src's are copied, as far as dst has room.
// Same caveat about a writable buffer.
bool bui_copy_text(BUI* ui, uint32_t dst, uint32_t src);

// Splits a PS2 colour word into 0..255 components. The bytes are GS
// convention -- 0x80 is full intensity, and the 0x81..0xff seen on some
// corners is the over-bright range -- so this doubles and clamps, exactly as
// texpack.c does for texture alpha.
void bui_color(uint32_t rgba, uint8_t out[4]);
