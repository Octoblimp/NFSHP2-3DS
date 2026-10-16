# Display Options and Customize P1 HUD (TASKS 71c)

Options' Display is retail's `tDisplayOptionsScreen`, and its Player 1
Options row opens `tCustomizeHUDScreen` for player 0 (`displayoptions.c`,
`displayoptions.h`). Both are OptionsScreenBase pages (`bscreens.c`'s
`bscr_optbase_*`). Display Options has a scrolling list (`bsetup.c`'s
`bscroll_*`) and both pages have the pulsing arrows (`barrows_*`).

| Config name | Flailer screen | Callback |
|---|---|---|
| "Display Options" | 8bc68340 | `displayopts_callback` (0x001f3ec0) |
| "Customize P1 HUD" | 28891a22 | `customhud_callback` (CallbackP1, 0x001f4960) |
| "Customize P2 HUD" | 28891a22 | not registered (CallbackP2, player 1) |
| "Calibrate display offset" | 7ab428c1 | not registered (a TV's) |

## Display Options

616 bytes in retail: the base, then `tGlobalDisplaySettings` at +100 (a
copy of `Fred.DisplayOptionsData`, 0x002fc19c), the list at +108, the
arrows at +164 and a blurb of its own at +196 (the port uses the base's,
on the same objects).

| Row | Value text | Setting | Left / Right | Noise |
|---|---|---|---|---|
| MENUITEM_1 Track Map | 55cb09f2 | OnePlayerTrackMapMode | the list {0,1,2,3,4,6}, wrapping | 1 / 2 |
| MENUITEM_2 Rearview Mirror | 2e931f1b | RearViewMirror | toggle | 1 / 2 |
| MENUITEM_3 Units | 03d90172 | Units | toggle (mph 140106, km/h 140107) | 1 / 2 |
| MENUITEM_4 Leaderboard | 5610f2f4 | LeaderboardMode | 2 becomes 0, anything else 2 | 1 if changed |
| MENUITEM_5 Jump Cams | 422313cb | byte 6 | toggle | 1 |
| MENUITEM_6 Zone Cams | 8fe4086b | byte 7 | toggle | 1 |
| MENUITEM_7 Player 1 Options | | A: Customize P1 HUD | | |
| MENUITEM_8 Player 2 Options | | hidden in the port | | |
| MENUITEM_9 Calibrate | | hidden in the port | | |

- **The track map's text** (0x001f37d0, by mode): 0 3D Rotation (140101),
  1 3D Standard (140102), 2 2D Rotation (140103), 3 2D Standard (140200),
  4 Fixed (140104), 5 Full size (140105), 6 Off (140115), 7 none, 8 and 9
  the two-player and Be A Cop maps' (140201, 140202).
- **CycleTrackMap** (`tGlobalDisplaySettings`, 0x001ee148) picks the map
  by the flow: Be A Cop's (byte 4) when `TheRaceParameters.BeACop` is set
  and the flow is not IN_FRONTEND, else the one-player map (byte 2) with
  one player, else the two-player map (byte 3). In the frontend it is
  always byte 2. The lists are at 0x003140a0 (six), 0x00331090 (two) and
  0x00331098 (two); 0x001bd8b0 steps one by the direction, wrapping, and a
  mode off the list comes back as the list's first. Then the screen's own
  rule (0x001f3730): byte 2 Off sets bytes 3 and 4 Off, anything else sets
  them to their lists' first (7 and 8).
- **The leaderboard's text** (0x002ba1b8): 0 Off, 1 Top 3 (102001), 2 On.
  Top 3 only comes from a save.
- **Blurbs**: 150700 .. 150703 for rows 1 .. 4, 150705 and 150706 for 5 and
  6, 150707 .. 150709 for 7 .. 9 (150704, the score's, is Customize HUD's).
- **The highlight** (0x001f3b80): the blurb, then the second bloom
  (`BLOOM_TEXT_2`, +60) and the arrows on the row's value text (rows 7 .. 9:
  none, DoHighlight(0)), then HandleHighlight with the list's mask. Left
  and Right ForceStart the second bloom on every row.
- **The list** (0x002ba178): the nine rows and the six values, a window of
  MENUITEM_1 .. 7, `numMenuItemsToScroll` 9; the value arrows are clipped
  to `c67cfb4a`. The port hides rows 8 and 9 with GrayMenuItem's mode 2,
  so the seven left all fit: 7, and the list never scrolls.
- **Up and Down** stop at the ends: Up on MENUITEM_1 and Down on
  MENUITEM_9 set `param` 1. The port's last row is MENUITEM_7.
- **A on row 7** writes the copy into Fred, starts the exit animation to
  "Customize P1 HUD" and hides the arrows. A on any other row is no noise.

## Customize P1 HUD

580 bytes in retail: the base, then the player's `cPlayerSettings` at +100
(a copy of `Fred.FrontendPlayers[n].mPlayerSettings`, Fred+0x10738 +
1744n + 1604), the player at +148, the arrow bitmaps at +152 and +156, a
blurb at +160. The destructor (0x001f4178) copies the settings back.

| Row | Value text | Field | Left / Right |
|---|---|---|---|
| MENUITEM_1 Lookback | 2e018745 | Lookback (+12) | 0 and 1 into each other: 0 Bird's Eye (140118), 1 Lookback (140113) |
| MENUITEM_2 Camera Spring | ffc3dcd2 | CameraSpring (+8) | 0 becomes 1, anything else 0; 1 is Off |
| MENUITEM_3 Gauges | 4ceb3ed2 | PreferredHudFeatures 0x040 | toggle |
| MENUITEM_4 Position | 1054482b | PreferredHudFeatures 0x010 | toggle |
| MENUITEM_5 Lap Info | c7e2117e | PreferredHudFeatures 0x100 | toggle |
| MENUITEM_6 Split Time | 6caf6d10 | SplitTimeType (+6) | 0 .. 4 wrapping |
| MENUITEM_7 Score | 6bd89c11 | New44 (+44) | toggle |

- **Split time** (CycleSplitTime, 0x001ee258): Race Leader (140108), Lap
  Record (140109), Best Lap (140110), Last Lap (140111), Off (140115).
  Off clears feature bit 0x004, anything else sets it.
- **Noise** 1 for Left and 2 for Right on every row; A and START are no
  noise. Up and Down wrap.
- **Blurbs** 150900 .. 150905 for rows 1 .. 6, and 150704 for the score.
- **The highlight** (0x001f47c8): DoHighlight (ArrowAligner, the arrows
  at the object's centre Y, and shown) on MENUITEM_1 and 2 for the first
  two rows and on the value text for the others, the blurb, and the second
  bloom on the value. The tick pulses the arrows (AnimateCursor). The
  port's `barrows_*` does both.
- **B** is the base's: back to Display Options.

## The save prompt

Retail's B on Display Options (0x001f3e10) writes the copy into Fred, and
when `tDisplayOptionsChangeManager::Different` (0x001ee878) says so and
`Fred.Autosave` is set, pushes "Autosave". The change manager (0x0031ad00,
112 bytes) is what Options' Start took on picking Display: Fred's
`DisplayCalibrationData` (8 bytes, Fred+324), `DisplayOptionsData` (8) and
both players' `cPlayerSettings` (48 each).

The port asks instead, with autosave on or off (the user's word,
2026-10-13), the same popup as Audio Options: "Save your changes to the
card?", Yes saves on the Autosave screen (which ends on Options), No puts
all four back as Start found them and moves back, B stays. Customize HUD's
changes count, as they are in Fred by the time Display Options' B runs.

## Testing

`tools/run_azahar_display.ps1` changes every row of both pages, presses
Down past Player 1 Options (it stays), answers the prompt with B, No (the
next way in must show what the first did) and Yes (the Autosave screen's
overwrite question too), and puts `settings.db` back after.
