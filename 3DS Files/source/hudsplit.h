// hudsplit -- the race HUD on two screens (step 8m-5). The port's own:
// the PS2 drew the whole HUD on one 640x480 screen, and there is no
// retail function behind this.
//
// What the player watches all the time stays on the top screen with the
// road: the speedometer and tach, the radar, the pursuit meter, the
// trackers, the race position and the messages over the road. The race
// position moves from the top left to the bottom left. The rest goes to
// the bottom screen: the lap block (the lap, the times and the record),
// the split times and the live split list, the score, and Be The Cop's
// panel. The minimap (trackmap.c) is drawn there too, after the HUD, at
// the same half size: main.c's trackview_draw_flailer_polys.
//
// RenderHud writes the Flailer objects as on the PS2. The split is made
// when they are drawn (uirender_set_placements), so none of retail's
// logic changes. The bottom screen draws the 640x480 frame at half size,
// so each object keeps retail's position and 4:3 shape.
//
// Written up in docs/formats/hud-split.md.

#ifndef HUDSPLIT_H
#define HUDSPLIT_H

#include "uirender.h"

// The one-player HUD screen in INGAMEB (playerinit.c's
// PLAYER_HUD_SINGLE). The two-player screen is left as it is.
#define HUDSPLIT_SCREEN 0xf1f1f8e5u

#ifdef __3DS__
// Hands uirender the split's table, which is static and stays good.
void hudsplit_install(UIRenderer* r);
#endif

#endif  // HUDSPLIT_H
