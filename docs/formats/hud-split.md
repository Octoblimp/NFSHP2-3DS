# The HUD on two screens (step 8m-5)

The PS2 drew the race HUD on one 640×480 screen. On the 3DS it is split
over the two screens. The split is the port's own, and no retail
function is behind it. The user placed it on 2026-10-03:

- **The top screen** keeps what the player watches all the time, beside
  the road:
  - the speedometer and tach, where retail has them;
  - the race position, moved from the top left to the bottom left;
  - the radar and the pursuit meter, where retail has them.
- **The bottom screen** takes the rest:
  - the lap block: the lap, the lap time and the record;
  - the split times and the live split list;
  - the score and the event bonuses;
  - Be The Cop's panel;
  - the minimap (step 8m-6c, `trackmap.md`), drawn after the rest. The
    user asked for it bigger on 2026-10-04, so it fills the screen's
    free lower left (see "The minimap's place").

## How it is made

RenderHud and SetHudFeatures write the Flailer objects as on the PS2,
so none of retail's logic changes. The split is made when the objects
are drawn:

- `uirender_set_placements` takes a table of `UIPlacement`s. Each one
  names a screen and an object, or a whole group, and says which screen
  it draws on, moved by (dx, dy) in the 640×480 space. The first match
  wins. An object with no match draws on the top screen.
- `uirender_draw_visible` draws the top screen and skips the objects
  placed on the bottom.
- `uirender_draw_visible_bottom` draws only the objects placed on the
  bottom, from the screens that have a placement. It draws the 640×480
  frame at half size into the 320×240 screen, so each object keeps
  retail's position and its 4:3 shape. It answers whether such a screen
  was visible.
- `hudsplit.c` holds the HUD's table. `main.c` installs it at boot. In a
  race, the bottom screen draws the HUD's half when the HUD is up, and
  the frontend's panel otherwise.

## The table

All on the one-player HUD screen, `f1f1f8e5`. The two-player screens are
left as they are.

| what | objects | screen |
|------|---------|--------|
| the race position | BIGRACE_POSITION, _POSITION_2, _EXTENSION, _TOTAL | top, 360 lower |
| the split times | RUNNING_SPLIT_TIME, COMPARISON_SPLIT_TIME, TIME_TRIAL_BACKING | bottom |
| the live split list | LIVE_SPLIT_POSITION_A and _B, LIVE_SPLIT_BG_HIGHLIGHT; groups `c0e6d1b6` to `c0e6d1b9` | bottom |
| the lap block | group `b7a3bc7a` | bottom |
| the score | group `5c9c03a7` | bottom |
| Be The Cop's panel | group `068e2c75` | bottom |

The names in group `457755c9` are listed one by one, because that group
also holds the chase view's gauges.

**The race position's move.** Its objects span y 7 to 113:
BIGRACE_POSITION's font is 106 high. Moved down by 360, the block ends
7 above the bottom edge, as it started 7 below the top. The grow
(BIGRACE_POSITION_2) moves with it.

**The live split list** sits under LIVE_SPLIT_POSITION_A when the race
position shows, and at LIVE_SPLIT_POSITION_B otherwise
(`show_live_split`). It keeps that place on the bottom screen.

## The minimap's place

At retail's place and half size, mode 0's map was a 70 by 46 pixel box
at the bottom screen's left. Everything below the live split list was
empty. `hudsplit_map_place` moves and scales the map's polys in the
640×480 before they go to the screen, so Render, DrawMap and the
checked trackmap code are not changed:

- **The room** is x 16 to 368 and y 204 to 466. Above it, the live
  split list's rows reach y 190. To its right, the score's event lines
  are right-justified at x 547, from y 281 up, at half scale. The lap
  block and Be The Cop's panel are at the top right.
- **The box** is the displayed mode's clipping box. A mode that does
  not clip (a ClippingWidth of 1000) uses its Width by Height about its
  X, Y instead.
- The box is made as big as fits in the room, keeping its shape, and
  put at the room's left, halfway down. Each vertex goes to
  `x × scale + dx`, `y × scale + dy`.
- Modes 6 (off) and 7 (two players) are left as they are, and so is
  every mode in a race of more than one player.

| modes | box | scale | on the bottom screen |
|-------|-----|-------|----------------------|
| 0, 1 (3D) | 139 × 91.3 at 92, 240 | 2.53 | 176 × 116 pixels at 8, 110 |
| 2, 3, 10 (2D) | 100 × 100 at 72, 243 | 2.62 | 131 × 131 at 8, 102 |
| 4, 8 (fixed) | 130 × 130 at 79, 256 | 2.02 | 131 × 131 at 8, 102 |
| 5, 9 (maximum size) | 262 × 262 at 320, 243 | 1 | 131 × 131 at 8, 102 |

The road's lines, the dots and the frame scale with the map, as a
closer view would show them. Modes 5 and 9 keep retail's size, since
their box already fills the room's height; they only move left, out of
the screen's middle.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65`, track 12, mode 0), with
shots in `out/azahar_13b3`, and before and after side by side in
`out/minimap_before_after.png`:

- The map's box is 176 by 115 pixels, with its top left 8 in from the
  left edge and 110 down. Before, it was 70 by 46.
- The road, the start line and the player's arrow keep their shape and
  their places in the box.
- The lap block and the live split list's row are where they were.
- 20 FPS, as before.

Not checked yet: the 2D, fixed and maximum-size modes, Be The Cop's
modes, and the score's event lines beside the map. Each needs a race
that the port cannot start yet, or a map mode the options set.

## What stays on the top

Everything not in the table, among it:

- the gauges of both views, and their texts and shift lights;
- the radar (`062743f5`), the pursuit meter's three placements
  (`0b603727`, `ed9fd777`, `a19ae030`) and the trackers (`c258f297`);
- WRONG WAY, the reset message, the race-over lines and the reticle;
- the cinema bars and the glass backing (`97f9252a`).

## How it was checked

No retail function is behind the split, so there is no checker and no
mutation pass. What each object shows is checked by `hudrender_check`
and the other HUD checkers. The split only chooses where it is drawn.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65`, OPEL, car 37, in the chase
view), with shots in `out/azahar_8m5`:

- The top screen shows the speedometer, the tach's band, the gear and
  the speed, and nothing else of the HUD.
- The bottom screen shows the lap block at its top right, at half size,
  and the live split list's row ("1 Player1") at its top left.
- The race position is not shown. SetHudFeatures turns it off in a race
  of one car (`NumPlayerCars + NumAICars == 1`). SkipFE's race has one,
  because the AI is not ported: with three AI cars the race aborts in
  carmodes ("AIDriver is not ported").
- A one-run test build drew the lap block on the top screen with the
  race position's move of 360. It came out at the bottom right, 360
  lower, so the move works. That build was not kept.
- 20 FPS. No crash in 15 seconds.

**Not checked:**

- the race position at the top screen's bottom left;
- the score, the split times and Be The Cop's panel on the bottom
  screen.

Each needs a race the port cannot start yet: AI cars, cops, or a time
trial with a record. Look at them when steps 11 and 12 bring those
races.
