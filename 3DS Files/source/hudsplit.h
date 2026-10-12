// hudsplit -- the race HUD on two screens (step 8m-5). The port's own:
// the PS2 drew the whole HUD on one 640x480 screen, and there is no
// retail function behind this.
//
// What the player watches all the time stays on the top screen with the
// road: the speedometer and tach, the radar, the pursuit meter, the
// trackers, the race position and the messages over the road. The race
// position moves from the top left to the bottom left, where the EA TRAX
// box was; the box goes up above it while it is shown. The rest goes to
// the bottom screen: the lap block (the lap, the times and the record),
// the split times and the live split list, the score, and Be The Cop's
// panel. The minimap (trackmap.c) is drawn there too, after the HUD:
// main.c's trackview_draw_flailer_polys. It is moved and made bigger, to
// fill the screen's free lower left (hudsplit_map_place).
//
// RenderHud writes the Flailer objects as on the PS2. The split is made
// when they are drawn (uirender_set_placements), so none of retail's
// logic changes. The bottom screen draws the 640x480 frame at half size,
// so each object keeps retail's position and 4:3 shape.
//
// Written up in docs/formats/hud-split.md.

#ifndef HUDSPLIT_H
#define HUDSPLIT_H

#include <stdint.h>

#include "uirender.h"

// The one-player HUD screen in INGAMEB (playerinit.c's
// PLAYER_HUD_SINGLE). The two-player screen is left as it is.
#define HUDSPLIT_SCREEN 0xf1f1f8e5u

#ifdef __3DS__
// Hands uirender the split's table, which is static and stays good.
void hudsplit_install(UIRenderer* r);

// Once a frame, before the top screen is drawn: the EA TRAX box goes
// above the race position while the position is up, and back to its own
// place otherwise.
void hudsplit_update(UIRenderer* r);

// Where the one-player minimap goes on the bottom screen, for the mode
// Render drew: its box, in the 640x480, goes to x * *scale + *dx and
// y * *scale + *dy. The box is the mode's clipping box, or its Width by
// Height about X, Y for a mode that does not clip. It is made as big as
// fits in the room under the live split list and left of the score's
// lines, keeping its shape, and put at the room's left, halfway down.
// Mode 6, and the two players' mode 7, stay where they are.
void hudsplit_map_place(int32_t mode, float* scale, float* dx, float* dy);
#endif

#endif  // HUDSPLIT_H
