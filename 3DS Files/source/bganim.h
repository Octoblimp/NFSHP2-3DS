#pragma once
// tGlobalBackgroundAnimation (0x002495f0 .. 0x00249c74), retail's: the
// frontend's moving blueprint. Seventeen of FRONTB's menu screens carry a
// MASTER_BP_OBJECT (GRID_BLUEPRINT1 at alpha 0x3c) and a FADING_BP_OBJECT
// (GRID_BLUEPRINT2 at 0x50) under everything else. On each screen change
// retail hides the master and fades the other in over a second, at full
// alpha, with one of the kept blueprints on it; drifts it to the right
// along a spline for fifty seconds; fades it out over the last one; and
// starts again with another. The demo disc's had the class, with a
// twenty-second drift and a different start; the port had neither, and drew
// the two bitmaps where the bundle put them.
//
// FlailerScreenList owns one (+456, bMalloc(156)). ChangeToScreen
// (0x0016c4c0) hands it the screen's first Flailer hash after Activate, or
// 0 for a NULL name, and Tick (0x0016cca8) ticks it after the song monitor
// while the flow is IN_FRONTEND. The event tree's car logos (eventtreeview.c)
// join the kept textures and are let go on the screen's close.
//
// Free of <3ds.h>: tools/bganim_check.py runs it next to retail's code in
// mipsemu. See docs/formats/frontend-background.md.
#include <stdint.h>

#include "banim.h"

struct FlailerObjectChunk;

// 156 bytes in retail, field for field.
typedef struct BgAnim {
    uint32_t                   screenHash;      // +0
    struct FlailerObjectChunk* grid;            // +4, GRID: found, unused
    struct FlailerObjectChunk* master;          // +8, MASTER_BP_OBJECT
    struct FlailerObjectChunk* fading;          // +12, FADING_BP_OBJECT
    BSpline2D                  spline;          // +16, the fading one's centre
    int32_t                    crossFadeTimer;  // +112, RealTimer at Reset
    int32_t                    gridTimer;       // +116, set, never read
    float                      animParam;       // +120, wraps at 6.283
    uint32_t                   kept[8];         // +124, texture hashes
} BgAnim;

// The constructor (0x002495f0): the spline at (320, 240), still; the
// timers, the objects and the parameter 0; the kept list reset.
void bganim_init(BgAnim* a);

// The kept textures. Add (0x00249730) takes `hash` out first, then puts it
// in the first empty slot, if there is one. Remove (0x00249790) clears every
// slot holding it. Count (0x002497b8) is the slots in use; Nth (0x002497f0)
// the n-th of those, 0 past the last. Reset (0x00249828) empties the list
// and adds GRID_BLUEPRINT1 and GRID_BLUEPRINT2.
void     bganim_keep_add(BgAnim* a, uint32_t hash);
void     bganim_keep_remove(BgAnim* a, uint32_t hash);
int      bganim_keep_count(const BgAnim* a);
uint32_t bganim_keep_nth(const BgAnim* a, int n);
void     bganim_keep_reset(BgAnim* a);

// Reset (0x00249888): with both objects, both hidden, the fading one put
// at a random start, its spline snapped there and aimed further right, and
// a random kept texture on it. Always the cross-fade's clock restarted.
// RealTimer is `realTimer`.
void bganim_reset(BgAnim* a, int32_t realTimer);

// ChangeScreenHash (0x00249a40): the screen's three objects found and the
// animation reset, or for 0 the objects dropped.
void bganim_change_screen_hash(BgAnim* a, uint32_t screen, int32_t realTimer);

// Tick (0x00249ae8): one frame, RealTimer `realTimer` and RealTimeElapsed
// `realElapsed`.
void bganim_tick(BgAnim* a, int32_t realTimer, float realElapsed);
