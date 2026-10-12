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

// The live split list's move while the race position shows: from
// LIVE_SPLIT_POSITION_A, under the race position at y 106, up to
// LIVE_SPLIT_POSITION_B's y 26, where it sits without one. The race
// position is on the top screen, so nothing is above the list here.
#define LIVE_SPLIT_UP -80.0f

#define TOP    UIR_TARGET_TOP
#define BOTTOM UIR_TARGET_BOTTOM
#define OVER   UIR_TARGET_BOTTOM_OVER

// kSplit's first six entries, the list that moves with the race
// position, whose dy hudsplit_set_features sets.
#define NUM_LIVE_SPLIT 6

// By name, or by group with a name of 0. The first entry that matches
// wins, so the names in group 457755c9, which also holds the gauges, come
// first.
static UIPlacement kSplit[] = {
    // The live split list: LIVE_SPLIT_POSITION_A, its anchor,
    // LIVE_SPLIT_BG_HIGHLIGHT, the bar that follows the player's row, and
    // the four rows.
    { HUDSPLIT_SCREEN, 0x363392aeu, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0xa3e3b399u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b6u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b7u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b8u, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0xc0e6d1b9u, BOTTOM, 0.0f, 0.0f },
    // LIVE_SPLIT_POSITION_B, the anchor without the race position.
    { HUDSPLIT_SCREEN, 0x363392afu, 0, BOTTOM, 0.0f, 0.0f },

    // The race position: BIGRACE_POSITION, _POSITION_2 (the grow),
    // _EXTENSION and _TOTAL.
    { HUDSPLIT_SCREEN, 0x004e27a0u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x4c769c11u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x9a492668u, 0, TOP, 0.0f, POSITION_DY },
    { HUDSPLIT_SCREEN, 0x84bb420fu, 0, TOP, 0.0f, POSITION_DY },

    // The split times in 457755c9: RUNNING_SPLIT_TIME,
    // COMPARISON_SPLIT_TIME, TIME_TRIAL_BACKING, at the top middle.
    { HUDSPLIT_SCREEN, 0x89c3ac59u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0xd1e5c713u, 0, BOTTOM, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0x77477d17u, 0, BOTTOM, 0.0f, 0.0f },

    // The lap block: LAP_COUNTER, LAP_TIME, BEST_LAP_TIME, the three
    // TIME_TITLEs and their backings, at the top right.
    { HUDSPLIT_SCREEN, 0, 0xb7a3bc7au, BOTTOM, 0.0f, 0.0f },
    // The score: the event's title and points fly from the right of the
    // minimap up to the total, so they draw over the map. The total and
    // its title are under the lap block.
    { HUDSPLIT_SCREEN, 0xa3ff1482u, 0, OVER, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0xa3e99d3cu, 0, OVER, 0.0f, 0.0f },
    { HUDSPLIT_SCREEN, 0, 0x5c9c03a7u, BOTTOM, 0.0f, 0.0f },
    // Be The Cop's panel: the helicopters, the cop cars, the damage
    // lights, the busts and the time left, at the top right.
    { HUDSPLIT_SCREEN, 0, 0x068e2c75u, BOTTOM, 0.0f, 0.0f },
};

void hudsplit_install(UIRenderer* r)
{
    uirender_set_placements(r, kSplit,
                            (int)(sizeof kSplit / sizeof kSplit[0]));
}

void hudsplit_set_features(uint32_t features)
{
    float dy = (features & HUD_RACE_POSITION) ? LIVE_SPLIT_UP : 0.0f;
    int   i;

    for (i = 0; i < NUM_LIVE_SPLIT; i++)
        kSplit[i].dy = dy;
}

// The minimap's room, in the 640x480: everything under the top band.
// The band's lowest lines are the split times' comparison and the
// score's total, which end by y 140. The map is centred in the room.
#define MAP_LEFT    16.0f
#define MAP_RIGHT   624.0f
#define MAP_TOP     150.0f
#define MAP_BOTTOM  472.0f

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
    *dx    = (MAP_LEFT + MAP_RIGHT) * 0.5f - cx * s;
    *dy    = (MAP_TOP + MAP_BOTTOM) * 0.5f - cy * s;
}

#endif  // __3DS__
