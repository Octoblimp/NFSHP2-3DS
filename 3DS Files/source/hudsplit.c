// hudsplit -- see hudsplit.h.

#include "hudsplit.h"

#ifdef __3DS__

#include "playerhud.h"
#include "trackmap.h"

// The race position's offset, in the 640x480 space. Its three objects
// span y 7 to 113 at the top left: BIGRACE_POSITION's font is 106 high.
// Moved down by 360, the block ends 7 above the bottom edge, as it
// started 7 below the top.
#define POSITION_DY 360.0f

#define TOP    UIR_TARGET_TOP
#define BOTTOM UIR_TARGET_BOTTOM

// By name, or by group with a name of 0. The first entry that matches
// wins, so the names in group 457755c9, which also holds the gauges, come
// first.
static const UIPlacement kSplit[] = {
    // The race position: BIGRACE_POSITION, _POSITION_2 (the grow),
    // _EXTENSION and _TOTAL.
    { HUDSPLIT_SCREEN, 0x004e27a0u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x4c769c11u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x9a492668u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x84bb420fu, 0, TOP, 0.0f, POSITION_DY },

    // The split times and the live split list's own parts in 457755c9:
    // RUNNING_SPLIT_TIME, COMPARISON_SPLIT_TIME, TIME_TRIAL_BACKING,
    // LIVE_SPLIT_POSITION_A and _B, LIVE_SPLIT_BG_HIGHLIGHT.
    { HUDSPLIT_SCREEN, 0x89c3ac59u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0xd1e5c713u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0x77477d17u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0x363392aeu, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0x363392afu, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0xa3e3b399u, 0, BOTTOM, 0.0f, 0.0f },

    // The lap block: LAP_COUNTER, LAP_TIME, BEST_LAP_TIME, the three
    // TIME_TITLEs and their backings.
    { HUDSPLIT_SCREEN, 0, 0xb7a3bc7au, BOTTOM, 0.0f, 0.0f },
    // The live split list's four rows.
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b6u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b7u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b8u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b9u, BOTTOM, 0.0f, 0.0f },
    // The score and the event bonuses.
    { HUDSPLIT_SCREEN, 0, 0x5c9c03a7u, BOTTOM, 0.0f, 0.0f },
    // Be The Cop's panel: the helicopters, the cop cars, the damage
    // lights, the busts and the time left.
    { HUDSPLIT_SCREEN, 0, 0x068e2c75u, BOTTOM, 0.0f, 0.0f },
};

void hudsplit_install(UIRenderer* r)
{
    uirender_set_placements(r, kSplit,
                            (int)(sizeof kSplit / sizeof kSplit[0]));
}

// The minimap's room, in the 640x480. Above it, the live split list's
// rows reach y 190. To its right, the score's event lines are
// right-justified at x 547, from y 281 up, at half scale.
#define MAP_LEFT    16.0f
#define MAP_RIGHT   368.0f
#define MAP_TOP     204.0f
#define MAP_BOTTOM  466.0f

void hudsplit_map_place(int32_t mode, float* scale, float* dx, float* dy)
{
    const TrackMapModeInformation* mi;
    float cx, cy, w, h, s;

    *scale = 1.0f;
    *dx    = 0.0f;
    *dy    = 0.0f;
    if (mode < 0 || mode >= TRACKMAP_NUM_MODES || mode == TRACKMAP_MODE_OFF
        || mode == TRACKMAP_MODE_2_PLAYER) {
        return;
    }
    mi = &TrackMapModeInfo[mode];
    if (mi->ClippingWidth < 1000.0f) {
        cx = mi->ClippingX;
        cy = mi->ClippingY;
        w  = mi->ClippingWidth;
        h  = mi->ClippingHeight;
    } else {
        cx = mi->X;
        cy = mi->Y;
        w  = mi->Width;
        h  = mi->Height;
    }
    if (w <= 0.0f || h <= 0.0f) {
        return;
    }
    s = (MAP_RIGHT - MAP_LEFT) / w;
    if ((MAP_BOTTOM - MAP_TOP) / h < s) {
        s = (MAP_BOTTOM - MAP_TOP) / h;
    }
    *scale = s;
    *dx    = MAP_LEFT + w * s * 0.5f - cx * s;
    *dy    = (MAP_TOP + MAP_BOTTOM) * 0.5f - cy * s;
}

#endif  // __3DS__
