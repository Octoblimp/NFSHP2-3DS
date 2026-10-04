// hudtach -- the tach's red band: InitializeFlailerTachometer (retail
// 0x001434a0) and RenderFlailerTachometer (0x00143858), with
// next_power_of_2 (0x0013ff60). The addresses are retail's (SLES_507.31).
//
// A bitmap whose Animation is TACH_GRADIENT (10) is not drawn as a quad.
// Init lays nine points over it -- the centre, then the middle of the
// bottom edge and on round clockwise through each corner and edge middle
// -- and keeps them in the Player's FlailerTachPointList, with the list's
// address in the bitmap at 108. RenderSingleFlailerBitmap (0x001428f0)
// then hands the bitmap and that list to Render instead of drawing it, and
// Render cuts a fan out of the nine points: whole quarters, then one cut at
// an angle the bitmap's Rotation gives. With no list nothing is drawn.
//
// Each piece is an ePoly from FlailerStrip::AddPoly (0x00145868), which
// allocates one, runs its constructor and links it on the strip. Here the
// caller's `add_poly` stands for AddPoly: it hands back a poly epoly_init
// has filled, or NULL when it has no room, where Render stops. The PS2's
// pool has no such limit.
//
// The list's address does not fit the word at 108 on a 64-bit host, so
// the word holds a token: 0 for none, and otherwise 1 + the list's slot in
// a small table here. hudtach_points turns it back. A list the table has
// not seen takes the next slot round, so the last HUDTACH_MAX_LISTS lists
// Init was given stay good, and a new race needs no reset.
//
// Written up in docs/formats/hud-tach.md; checked on retail's image by
// tools/hudtach_check.py.

#ifndef HUDTACH_H
#define HUDTACH_H

#include <stdint.h>

#include "epoly.h"
#include "flailer.h"

// FlailerTachometerPointList, 180 bytes.
typedef struct {
    float x, y, z;                //  0  in 640x480, z the bitmap's layer
    float u, v;                   // 12  over the power-of-two allocation
} FlailerTachometerPoint;         // 20

typedef struct {
    FlailerTachometerPoint Points[9];   // 0  centre, then round from below
} FlailerTachometerPointList;           // 180

typedef char hudtach_layout_check[
    sizeof(FlailerTachometerPointList) == 180 ? 1 : -1];

// How many lists the table at 108 can name: one per Player.
#define HUDTACH_MAX_LISTS 4

// next_power_of_2 (0x0013ff60): 0 for 0, 2 for 1 and 2, and otherwise the
// power of two at or above n.
uint32_t next_power_of_2(uint32_t n);

// InitializeFlailerTachometer, as gInitializeFlailerTachometerFn
// (playerhud.h) takes it. The needle is not read. The size is the
// texture's (gFlailerBitmapTextureSizeFn); with none, nothing is written,
// where the PS2 reads its NULL TextureInfo.
void flailer_initialize_tachometer(struct FlailerObjectChunk *needle,
                                   struct FlailerObjectChunk *gradient,
                                   void *points);

// The list a TACH_GRADIENT bitmap's word at 108 names, or NULL.
FlailerTachometerPointList *hudtach_points(
    const struct FlailerBitmapChunk *b);

// RenderFlailerTachometer. NULL `list` draws nothing.
void flailer_render_tachometer(const struct FlailerBitmapChunk *b,
                               const FlailerTachometerPointList *list,
                               ePoly *(*add_poly)(void *ctx), void *ctx);

#endif
