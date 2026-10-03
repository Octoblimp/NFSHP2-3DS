// flailer -- retail's Flailer runtime: the lookups, the object methods and
// the global Flailer* wrappers the game calls by (screen, object) hash. The
// addresses are retail's (SLES_507.31).
//
// The objects are the chunk bytes themselves, as on the PS2: a
// FlailerObjectChunk* is the payload of the object's chunk inside the loaded
// bundle, and every setter writes into it. bui.c reads the same bytes back
// every frame, so what the game changes here is what uirender.c draws. The
// structs below are retail's layout -- the demo's plus the 24-byte name at
// 16 -- and only retail's bundles are taken.
//
// What is not here:
//
//   - The lists. LoaderFlailerChunk (0x0013fba0) links the projects, their
//     screens and the screens' objects through the chunks' bTNodes. bui.c
//     already holds each screen's objects in file order, which is the order
//     the loader links them in and nothing reorders, so the objects are
//     walked from its tables and the node words are left as the disc has
//     them. Only FindFlailerScreen reorders anything, and the order it
//     keeps is kept here (flailer_add_project).
//   - The strips. FlailerStrip is the PS2's cached geometry; uirender.c
//     builds nothing ahead, so pFlailerStrip stays 0 and DeleteFlailerStrip
//     has nothing to free.
//   - FlailerRenderManager, and with it the chunk version of
//     FlailerSetScreenVisibility (0x00145c50). Screen visibility is still
//     main.c's hook over BUIScreen::visible.
//   - The fonts and the textures. A text object's width is its glyphs' and
//     a bitmap's its texture's, which the renderer has; see the seams.
//
// Written up in docs/formats/flailer-runtime.md; checked on retail's image
// by tools/flailer_check.py.

#ifndef FLAILER_H
#define FLAILER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bui.h"
#include "bvector.h"

// FlailerObjectType, the byte at 40.
#define FLAILER_TYPE_ANY    0
#define FLAILER_TYPE_TEXT   1
#define FLAILER_TYPE_BITMAP 2

// FlailerObjectVisibility, the byte at 41. The opposite way round from
// FlailerScreenVisibility (trackflow.h), where VISIBLE is 0.
#define FLAILER_OBJECT_INVISIBLE 0
#define FLAILER_OBJECT_VISIBLE   1

// The bitmap's corner argument that means all four.
#define FLAILER_ALL_CORNERS (-1)

// FlailerScreenChunk, 40 bytes: the 0x00010203 chunk in each screen.
struct FlailerScreenChunk {
    uint32_t Next, Prev;          //  0  bTNode, the loader's; not used here
    uint32_t NameHash;            //  8
    uint32_t CallbackHash;        // 12
    uint32_t HelpMenuHash;        // 16
    uint32_t BackgroundHash;      // 20
    uint16_t ResX, ResY;          // 24
    uint16_t NumObjects;          // 28
    int16_t  Visible;             // 30  FlailerScreenVisibility
    uint32_t ObjectList[2];       // 32  bTList, the loader's; not used here
};

// FlailerObjectChunk, 80 bytes, the head of every object. Pointers are
// words, so the layout is the PS2's on the host too.
struct FlailerObjectChunk {
    uint32_t Next, Prev;          //  0  bTNode, the loader's; not used here
    uint32_t NameHash;            //  8
    uint32_t GroupHash;           // 12
    char     Name[24];            // 16  retail's
    int8_t   ObjectType;          // 40  FLAILER_TYPE_*
    int8_t   Visibility;          // 41  FLAILER_OBJECT_*
    int8_t   Z;                   // 42  the render layer
    int8_t   DirtyFlag;           // 43  what the last setter changed
    uint32_t pFlailerStrip;       // 44  always 0 here
    float    X, Y;                // 48  top-left, in 640x480
    float    ScaleX, ScaleY;      // 56
    int32_t  Rotation;            // 64
    int32_t  Animation;           // 68
    uint32_t RenderOnPoly;        // 72
    uint32_t ClipToPoly;          // 76
};

// FlailerTextChunk, 100 + MaxChars bytes: the characters are inline.
struct FlailerTextChunk {
    struct FlailerObjectChunk Object;   //   0
    uint32_t FontHash;            //  80
    int32_t  MaxChars;            //  84
    uint32_t FormatOptions;       //  88  BUI_FMT_*
    uint32_t Color;               //  92  RGBA, alpha the top byte
    uint32_t LanguageID;          //  96  0, or the string's key
    char     String[];            // 100  MaxChars of them
};

// FlailerBitmapChunk, 144 bytes.
struct FlailerBitmapChunk {
    struct FlailerObjectChunk Object;   //   0
    uint32_t TextureHash;         //  80
    uint32_t pTextureInfo;        //  84  GetTextureInfo's cache; 0 here
    uint32_t Colors[4];           //  88  per corner
    uint32_t StateFlags;          // 104
    uint32_t pTachPointList;      // 108
    float    UV[8];               // 112
};

typedef char flailer_layout_check[
    (offsetof(struct FlailerScreenChunk, Visible) == 30
     && sizeof(struct FlailerScreenChunk) == 40
     && offsetof(struct FlailerObjectChunk, ObjectType) == 40
     && offsetof(struct FlailerObjectChunk, X) == 48
     && sizeof(struct FlailerObjectChunk) == 80
     && offsetof(struct FlailerTextChunk, String) == 100
     && offsetof(struct FlailerBitmapChunk, Colors) == 88
     && sizeof(struct FlailerBitmapChunk) == 144)
    ? 1 : -1];

// ----------------------------------------------------------------- seams

// GetScaledWidth (0x00140d30) and GetScaledHeight (0x00140cd8), which read
// the font. NULL answers 0, as a missing font does on the PS2.
extern float (*gFlailerTextScaledWidthFn)(struct FlailerTextChunk *t);
extern float (*gFlailerTextScaledHeightFn)(struct FlailerTextChunk *t);
// FlailerBitmapChunk::GetTextureInfo (0x00141368)'s Width and Height, the
// halfwords at 36 and 38 of the TextureInfo for TextureHash. False for a
// texture that is not there, or with the seam NULL: the PS2 reads through
// the NULL, and here the size questions answer 0 and the setters that
// need it do nothing.
extern bool (*gFlailerBitmapTextureSizeFn)(struct FlailerBitmapChunk *b,
                                           int32_t *w, int32_t *h);

// ------------------------------------------------------------- projects

// LoaderFlailerChunk (0x0013fba0) for one bundle bui_open() has read: the
// project goes on the tail of the list FindFlailerScreen searches, each
// screen's Visible is set INVISIBLE (1), and each screen's
// UpdateLanguageText (0x001402a0) stamps DirtyFlag 5 on its text. False,
// with nothing taken, for a bundle in the demo's layout, an object that is
// not word-aligned, or a full list.
bool flailer_add_project(BUI *ui);

// Forgets every project. Nothing in the game unloads one; the checker does.
void flailer_reset(void);

// The project and the index bui_object() takes for an object, or false if
// `o` is not an object of any project.
bool flailer_object_index(const struct FlailerObjectChunk *o, BUI **ui,
                          uint32_t *index);

// The BUIScreen behind a screen chunk FindFlailerScreen gave, or NULL.
BUIScreen *flailer_screen_of(const struct FlailerScreenChunk *s, BUI **ui);

// The project `n` places down FindFlailerScreen's list, and its linked
// screens' indices in their list's order. NULL past the end.
BUI *flailer_project_at(int n, const uint32_t **order, uint32_t *count);

// ---------------------------------------------------------------- lookups

// FindFlailerScreen (0x00140378): the first screen with this NameHash, the
// projects in their list's order and each one's screens in theirs. A
// screen found past the first two it looked at is moved to the head of
// its project's list, and the project to the head of theirs. NULL if none.
struct FlailerScreenChunk *flailer_find_screen(uint32_t screen);

// FindFlailerObject (0x00143d50): the first object on the screen with this
// NameHash and, unless `type` is FLAILER_TYPE_ANY, this ObjectType.
struct FlailerObjectChunk *flailer_find_object(uint32_t screen,
                                               uint32_t object,
                                               int32_t type);

// FindFlailerObjectByGroup (0x00143dd8): the same by GroupHash, from the
// head or from the object after `after`.
struct FlailerObjectChunk *flailer_find_object_by_group(
    uint32_t screen, uint32_t group, int32_t type,
    struct FlailerObjectChunk *after);

// ------------------------------------------------------ FlailerObjectChunk

int32_t flailerobject_get_alpha(struct FlailerObjectChunk *o);  // 0x00140518
void flailerobject_set_z(struct FlailerObjectChunk *o, int32_t z); // 0x00140568
int32_t flailerobject_get_width(struct FlailerObjectChunk *o);  // 0x00140588
int32_t flailerobject_get_height(struct FlailerObjectChunk *o); // 0x001405e0
float flailerobject_get_width_float(struct FlailerObjectChunk *o);  // 0x00140638
float flailerobject_get_height_float(struct FlailerObjectChunk *o); // 0x00140688
void flailerobject_set_alpha(struct FlailerObjectChunk *o, int32_t a); // 0x001406d8
void flailerobject_set_rotation(struct FlailerObjectChunk *o, float r); // 0x00140708
void flailerobject_set_visibility(struct FlailerObjectChunk *o, int32_t v); // 0x00140728
void flailerobject_set_color(struct FlailerObjectChunk *o,
                             const bVector4 *c);                // 0x00140740
void flailerobject_set_scale_x(struct FlailerObjectChunk *o, float sx); // 0x001407d0
void flailerobject_set_scale_y(struct FlailerObjectChunk *o, float sy); // 0x001407f8
// 0x00140770 and 0x001407a0: a bitmap's scale set so the texture is `w`
// (or `h`) across; a text object's own (0x00140f98, 0x00140fa0) are empty.
void flailerobject_set_width(struct FlailerObjectChunk *o, float w);
void flailerobject_set_height(struct FlailerObjectChunk *o, float h);
// 0x00140820: the scale set to `s` both ways, the position moved so the
// object grows about its middle; see flailer.c for the text's alignments.
void flailerobject_scale_about_center(struct FlailerObjectChunk *o, float s);
void flailerobject_get_center(struct FlailerObjectChunk *o, float *x,
                              float *y);                        // 0x00140850
void flailerobject_set_center_x(struct FlailerObjectChunk *o, float x); // 0x001408e8
void flailerobject_set_center_y(struct FlailerObjectChunk *o, float y); // 0x00140930
void flailerobject_get_top_left(struct FlailerObjectChunk *o, float *x,
                                float *y);                      // 0x00140978
void flailerobject_set_top_left_x(struct FlailerObjectChunk *o, float x); // 0x00140a20
void flailerobject_set_top_left_y(struct FlailerObjectChunk *o, float y); // 0x00140a48
void flailerobject_set_clip_to_poly(struct FlailerObjectChunk *o,
                                    uint32_t poly);             // 0x00140a70
void flailerobject_delete_strip(struct FlailerObjectChunk *o);  // 0x00140b78

// -------------------------------------------------------- FlailerTextChunk

void flailertext_set_format_options(struct FlailerTextChunk *t,
                                    uint32_t f);                // 0x00140c68
void flailertext_clear_format_options(struct FlailerTextChunk *t,
                                      uint32_t f);              // 0x00140c80
void flailertext_set_color(struct FlailerTextChunk *t, uint32_t c); // 0x00140ca0
void flailertext_set_string(struct FlailerTextChunk *t, const char *s); // 0x00140e20
void flailertext_update_language_text(struct FlailerTextChunk *t); // 0x00140e98
void flailertext_set_language_id(struct FlailerTextChunk *t,
                                 uint32_t id);                  // 0x00140ea8
void flailertext_set_alpha(struct FlailerTextChunk *t, int32_t a); // 0x00140ed0
int32_t flailertext_get_alpha(struct FlailerTextChunk *t);      // 0x00140f08
void flailertext_set_color_vector(struct FlailerTextChunk *t,
                                  const bVector4 *c);           // 0x00140f10

// ------------------------------------------------------ FlailerBitmapChunk

void flailerbitmap_set_alpha(struct FlailerBitmapChunk *b, int32_t a,
                             int32_t corner);                   // 0x001411d8
void flailerbitmap_set_rotation(struct FlailerBitmapChunk *b, float r); // 0x00141258
void flailerbitmap_set_color(struct FlailerBitmapChunk *b, uint32_t c); // 0x00141288
void flailerbitmap_set_color_vector(struct FlailerBitmapChunk *b,
                                    const bVector4 *c);         // 0x001412b0
void flailerbitmap_change_texture(struct FlailerBitmapChunk *b,
                                  uint32_t texture);            // 0x00141350
int32_t flailerbitmap_get_alpha(struct FlailerBitmapChunk *b,
                                int32_t corner);                // 0x001413e8
float flailerbitmap_width_float(struct FlailerBitmapChunk *b);  // 0x00141448
float flailerbitmap_height_float(struct FlailerBitmapChunk *b); // 0x00141488

// ---------------------------------------------------------------- wrappers
//
// Each finds the object with FindFlailerObject -- a text object for the
// text ones, a bitmap for ChangeTexture, any type for the rest -- and does
// nothing (or answers 0) if it is not there.

// FlailerPrintf (0x00143e70 and 0x00143f08): bVSPrintf into a buffer of
// 128, then SetString. The length printed, or 0 for no object.
int32_t flailer_printf(uint32_t screen, uint32_t object, const char *fmt,
                       ...);
int32_t flailer_printf_chunk(struct FlailerTextChunk *t, const char *fmt,
                             ...);
void flailer_set_text_color(uint32_t screen, uint32_t object,
                            uint32_t c);                        // 0x00143f88
void flailer_set_text_format_option(uint32_t screen, uint32_t object,
                                    uint32_t f);                // 0x00143ff0
void flailer_clear_text_format_option(uint32_t screen, uint32_t object,
                                      uint32_t f);              // 0x00144030
// 0x00144070: 0, 0 for no object.
void flailer_get_top_left_position(uint32_t screen, uint32_t object,
                                   float *x, float *y);
// 0x001440d8: the same, each truncated.
void flailer_get_top_left_position_int(uint32_t screen, uint32_t object,
                                       int32_t *x, int32_t *y);
float flailer_get_top_left_x(uint32_t screen, uint32_t object); // 0x00144140
float flailer_get_top_left_y(uint32_t screen, uint32_t object); // 0x00144168
int32_t flailer_get_width(uint32_t screen, uint32_t object);    // 0x00144190
int32_t flailer_get_height(uint32_t screen, uint32_t object);   // 0x001441c8
void flailer_set_width(uint32_t screen, uint32_t object, float w);  // 0x00144200
void flailer_set_height(uint32_t screen, uint32_t object, float h); // 0x00144240
// 0x00144280: the top left truncated, and that plus GetWidth and
// GetHeight. All four are left alone for no object.
void flailer_get_bounding_box(uint32_t screen, uint32_t object,
                              int32_t *left, int32_t *top, int32_t *right,
                              int32_t *bottom);
void flailer_set_clip_to_poly(uint32_t screen, uint32_t object,
                              uint32_t poly);                   // 0x00144358
void flailer_set_top_left_position(uint32_t screen, uint32_t object,
                                   int32_t x, int32_t y);       // 0x00144398
void flailer_set_z(uint32_t screen, uint32_t object, int32_t z); // 0x00144418
void flailer_set_top_left_y(uint32_t screen, uint32_t object,
                            int32_t y);                         // 0x00144458
void flailer_set_top_left_x(uint32_t screen, uint32_t object,
                            int32_t x);                         // 0x001444a0
// 0x001444e8: *sx and *sy are left alone for no object.
void flailer_get_scale(uint32_t screen, uint32_t object, float *sx,
                       float *sy);
void flailer_set_scale_x(uint32_t screen, uint32_t object, float sx); // 0x00144530
void flailer_set_scale_y(uint32_t screen, uint32_t object, float sy); // 0x00144570
void flailer_scale_about_center(uint32_t screen, uint32_t object,
                                float s);                       // 0x001445b0
void flailer_set_center(uint32_t screen, uint32_t object, int32_t x,
                        int32_t y);                             // 0x001445f0
void flailer_set_center_y(uint32_t screen, uint32_t object,
                          int32_t y);                           // 0x001446e0
// 0x00144760: retail centres X on the object's *height*. Kept.
void flailer_set_center_x(uint32_t screen, uint32_t object, int32_t x);
// 0x001447e0: the middle of the bounding box, each half rounded toward 0.
// 0, 0 for no object, where the PS2 hands back what was on its stack.
void flailer_get_center(uint32_t screen, uint32_t object, int32_t *x,
                        int32_t *y);
int32_t flailer_get_center_y(uint32_t screen, uint32_t object); // 0x00144860
int32_t flailer_get_center_x(uint32_t screen, uint32_t object); // 0x00144888
int32_t flailer_get_alpha(uint32_t screen, uint32_t object);    // 0x001448b0
void flailer_set_alpha(uint32_t screen, uint32_t object, int32_t a); // 0x001448e8
void flailer_set_rotation(uint32_t screen, uint32_t object, float r); // 0x00144928
void flailer_set_visibility(uint32_t screen, uint32_t object,
                            int32_t v);                         // 0x00144968
void flailer_set_language_id(uint32_t screen, uint32_t object,
                             uint32_t id);                      // 0x001449a8
void flailer_set_object_color(uint32_t screen, uint32_t object,
                              const bVector4 *c);               // 0x001449e8
void flailer_change_texture(uint32_t screen, uint32_t object,
                            uint32_t texture);                  // 0x00144a28
// 0x00145308: every object of the group moved by what would put
// `anchor` at (x, y). Nothing for no anchor.
void flailer_set_group_position(uint32_t screen, uint32_t group,
                                uint32_t anchor, float x, float y);
void flailer_offset_group(uint32_t screen, uint32_t group, int32_t dx,
                          int32_t dy);                          // 0x001453d0
// 0x00145488: RenderOnPoly stored straight in, nothing marked dirty.
void flailer_set_group_render_on_poly(uint32_t screen, uint32_t group,
                                      uint32_t poly);
// 0x001454e8: Visibility stored straight into every object of the group,
// with no DeleteFlailerStrip.
void flailer_set_group_visibility(uint32_t screen, uint32_t group,
                                  int32_t v);
void flailer_set_group_alpha(uint32_t screen, uint32_t group,
                             int32_t a);                        // 0x00145560
// 0x001455e8: the bitmap stretched down from y1 to y2, whichever is lower
// first, by its ScaleY.
void flailer_make_vertical_line(uint32_t screen, uint32_t object, float y1,
                                float y2);
// 0x00145690: the same from 4 below the bottom of `top` to 3 below the top
// of `bottom`. Nothing unless both are there.
void flailer_make_vertical_line_between(uint32_t screen, uint32_t object,
                                        uint32_t top, uint32_t bottom);

#endif
