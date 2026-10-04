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
  - the minimap (step 8m-6c, `trackmap.md`), drawn after the rest at
    the same half size, where retail puts it.

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
