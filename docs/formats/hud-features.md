# The HUD's features (step 8m-2)

Each frame, UpdateHud (`0x0017ecf0`) asks Player::DetermineHudFeatures
(`0x00178da0`) which parts of the HUD the player should see. It then hands
the answer to SetHudFeatures (`0x001796b0`), which shows or hides the
Flailer objects behind each bit that changed and finds the ones UpdateHud
writes into. The Player's destructor calls SetHudFeatures with 0. This step
ports both, along with:

- the gauge helper (`0x001795f8`);
- SetTrackMapMode (`0x00178c90`, the demo's `SetTrackMapMode__6Playeri`);
- IsNisPlaying (`0x00176520`);
- ShouldShowBustedText (`0x00182318`) and the CopManager's
  ShouldDisplayBustedText (`0x002289f8`);
- RaceParameters::IsFreeRun;
- UpdateHud's head (`0x0017ed18` to `0x0017ed34`), which calls
  SetHudFeatures only when DetermineHudFeatures' answer differs from
  `CurrentHudFeatures`. `main.c` binds it to `gPlayerUpdateHudFn`, so
  UpdateNonGameState runs it each frame. The rest of UpdateHud is 8m-3.

`playerhud.c` is the port, and `tools/hudfeatures_check.py` checks it
against the image. The objects are on the player's HUD screen,
`HudScreenHash`:

| screen | hash | objects |
|--------|------|--------:|
| one player | `f1f1f8e5` | 182 |
| two players, top | `a8eb7af0` | 92 |
| two players, bottom | `6283be92` | 80 |

The cinema bars are separate screens: `49c15518` covers the whole view,
and `accbfcb8` and `accbfcb9` are its top and bottom halves. All six
screens exist only in `GLOBAL/INGAMEB.BUN`. [flailer-runtime.md](flailer-runtime.md) covers the
lookups and setters that SetHudFeatures calls.

## The bits

Retail has no symbols, and the demo's stabs give `CurrentHudFeatures`
(Player +768) only as an `unsigned int`. The names are therefore the
port's, and each one is named for what SetHudFeatures does with the bit.

| bit | name | SetHudFeatures |
|-----|------|----------------|
| `00000001` | TRACK_MAP | makes the TrackMap or deletes it |
| `00000002` | TIRE_FORCE | the four tyre-force bitmaps |
| `00000004` | RACE_OVER | the race-over groups, the messages, the speech |
| `00000008` | LAP_COUNTER | the lap block (with BEST_LAP) |
| `00000010` | -- | set by Determine, read by nothing |
| `00000020` | GAUGES | the bumper view's speedo and tach |
| `00000040` | GAUGES_OUTSIDE | the third-person gauge |
| `00000080` | SPLIT_TIMES | the two split texts, hidden |
| `00000100` | -- | set by Determine, read by nothing |
| `00000200` | RACE_POSITION | the position texts (and the live split's place) |
| `00000400` | BEST_LAP | the lap block (with LAP_COUNTER) |
| `00001000` | REAR_VIEW_MIRROR | SetRearViewMirrorCameraMover; moves the radar |
| `00002000` | LETTERBOX | the eView's `LetterBox` byte |
| `00004000` | WRONG_WAY | group `bbbb857c`, HudStartWrongWay |
| `00008000` | PURSUIT | the pursuit meter |
| `00010000` | RESET_PROMPT | group `f74c9d43` |
| `00020000` | SCORE | the score group |
| `00040000` | MUSIC | the EA TRAX group |
| `00080000` | RADAR | the radar group and its twelve lights |
| `00100000` | TRACKER | the tracker group and its seven dots |
| `00200000` | NIS_OVERLAY | NISOverlayManager::SetVisible |
| `00400000` | COP_LOOKING_BACK | set by Determine, read by nothing here |
| `00800000` | LIVE_SPLIT | the live split's four rows |
| `01000000` | BE_THE_COP | the Be The Cop group |
| `02000000` | CINEMA_BARS | the bars screens |
| `04000000` | PURSUIT_HI | the pursuit meter's high copy |
| `08000000` | PURSUIT_NIS | the pursuit meter's NIS copy |
| `10000000` | GAUGES_IN_CAR | the in-car view's digits |

## DetermineHudFeatures

The checks run in order, and the first one that answers wins. Here `np` is
`Player::NumPlayers` and `cop` is `TheRaceParameters.BeACop`.

1. No car, or no HUD screen: 0.
2. `nZoneCurrent` is not 0 (a camera zone): MUSIC alone.
3. The coordinator is in AI_DEMO, REPLAY_DEMO, INSTANT_REPLAY or POSTRACE:
   0. AUTO_REPLAY is not on the list.
4. **A NIS is playing:** the player's own, or, in a two-player Be A Cop
   race, player 0's as seen by player 1. The answer starts as MUSIC:
   - It becomes PURSUIT_NIS | MUSIC when the race has cops, the game is not
     paused and there is one player.
   - It drops PURSUIT_NIS (and RACE_POSITION) when there is a single car in
     the race, a free run, HUD state 1 or 3, or Be A Cop.
   - It adds NIS_OVERLAY unless paused, and CINEMA_BARS for one player or
     for Be A Cop.
   - It adds TRACK_MAP only for player 0 of a two-player race that is not
     Be A Cop and whose two-player map mode is not off.
5. **Busted** (ShouldShowBustedText): MUSIC | NIS_OVERLAY, or MUSIC alone
   when paused.
6. **The stage.** FLYBY or PRERACE gives CINEMA_BARS. COUNTDOWN with one
   player gives CINEMA_BARS | MUSIC.
7. **Finished** (`TimeFinishedRacing` set) while RACE_IN_PROGRESS: MUSIC |
   RACE_OVER. Player 0 of a two-player race also gets TRACK_MAP while
   player 1 is still racing and the two-player mode is not off.
8. **Paused:** MUSIC, or CINEMA_BARS | MUSIC when the state before the
   pause was FLYBY or PRERACE. TRACK_MAP is added for 60 frames of
   `RealTimeFrames` after `TimeTrackMapModeChanged`. Once those frames
   have passed, the stamp is cleared.
9. `nZoneCurrent` 1 or 2: MUSIC | LETTERBOX. Step 2 has already returned
   for any zone, so this check is dead in retail too. The port keeps it.
10. **The HUD state** (`PlayerSettings.PlayersHudState`, the player's
    cycle through HUD layouts), starting from MUSIC:
    - **State 0, the full HUD:**
      - TRACKER, unless the camera is looking back.
      - TRACK_MAP, unless the map mode for the race kind (Be The Cop, two
        players or one) is off (6).
      - COP_LOOKING_BACK for Be A Cop's player 0 when the drive camera's
        `DesiredLookBackParam` is 1.
      - The preference word (`PreferredHudFeatures`):
        - 0x100 gives LAP_COUNTER, BEST_LAP and the bit 0x100;
        - 0x4 gives SPLIT_TIMES;
        - 0x10 gives RACE_POSITION;
        - 0x200 gives LIVE_SPLIT. This needs one player, no Be A Cop, no
          time-trial target (0 or 0x7fffffff), not a free run, and a
          leaderboard mode.
      - REAR_VIEW_MIRROR when the setting is on and the player is not
        looking back.
      - RACE_POSITION goes again in a circuit time trial, with a single car
        in the race, or in a free run.
      - With cops in a race that is not Be A Cop: PURSUIT when the
        preference has 0x100, otherwise PURSUIT_HI; and RADAR unless the
        player is looking back.
      - Be A Cop adds BE_THE_COP. Player 0 drops the lap block, the splits,
        0x100 and the position. Player 1 drops the splits, 0x100 and the
        position.
      - SCORE when the race is not a free run, is not a two-player Be A
        Cop race, and `PlayerSettings.New44` is set.
      - The gauge, from the helper, when the preference has 0x40.
    - **State 1:** PURSUIT_HI with cops (not Be A Cop), and TRACK_MAP for
      one player.
    - **State 2:** PURSUIT_HI with cops (not Be A Cop), until the player
      finishes.
    - **State 3:** PURSUIT_HI with cops (not Be A Cop), and the gauge.
11. Last, for every HUD state:
    - Be A Cop drops RACE_POSITION and both pursuit meters.
    - Two players turn PURSUIT_HI into PURSUIT and drop TRACKER. Player 1
      drops TRACK_MAP.
    - WRONG_WAY when `bWrongWay` is set.
    - RESET_PROMPT when `TimeToDisplayResetPrompt` is neither 0 nor
      0x7fffffff.

The gauge helper picks one gauge for the camera:

| case | gauge |
|------|-------|
| no POV at `DriveCameraPOVIndex` | none |
| exterior view | GAUGES_OUTSIDE |
| two player cars | GAUGES_OUTSIDE |
| bumper POV (0), one player car | GAUGES |
| in-car POV (1) | GAUGES_IN_CAR |
| any other POV | none |

## SetTrackMapMode

The mode is clamped to the modes allowed for the race kind. These are
retail's three word tables, searched by `0x001bd7a8`, `0x001bd7f0` and
`0x001bd838`, and a mode that is not in the table becomes the table's
first entry.

| race | modes | stored in |
|------|-------|-----------|
| one player | 0, 1, 2, 3, 4, 6 | `OnePlayerTrackMapMode` (750) |
| two players | 7, 6 | `TwoPlayerTrackMapMode` (751) |
| Be A Cop | 8, 6 | `BeTheCopTrackMapMode` (752) |

Player 1 of a two-player race always gets 6, which is off. A mode that
differs from the stored one is written to the race parameters' display
settings and stamps `TimeTrackMapModeChanged` with `RealTimeFrames`. The
mode is also written into the TrackMap's word at +160 whether or not it
changed.

## SetHudFeatures

The call first drops the two gauge bits from the current word, so `chg`
always contains the new word's gauge bits. It stores the stripped word
and calls ClearHudAnimations. When the stripped word is 0 and the new one
is not, it shows the HUD screen; when the stripped word is not 0 and the
new one is, it hides it. After that it runs one block per changed bit,
in this order:

- **The mirror.** REAR_VIEW_MIRROR calls SetRearViewMirrorCameraMover.
- **The gauges.** These run every call:
  - **GAUGES:** hides the third-person objects, then shows the bumper
    objects. It calls ChooseLoadableTextures for the car type and units.
    It places the speedo needle, the speed and gear texts and the shift
    light from the car's `HudInfo` (CarTypeInfo +1232). An integrated
    tach is drawn into the speedo; in that case the tach and its gradient
    are hidden and the texts move up 20 or 30.
  - **GAUGES_OUTSIDE:** chooses the third-person texture, or
    `3RDPERSONGAUGE_MPH`/`_KMH` for two players, and swaps the two sets.
  - **Neither bit:** hides all twenty gauge objects.
  - Either gauge finds the needles, gradient, texts and shift light, sets
    `pFlailerTachGear` to NULL, and calls InitializeFlailerTachometer.
- **GAUGES_IN_CAR:** group `cd086c26`, and its own speed, gear and shift
  objects (the bumper hashes plus 1).
- **RACE_POSITION:** the four position texts. In a two-player race,
  player 1's big digits are coloured (0, 79, 128, 128); `0x001831d0` fills
  that colour into `0x002fbb20`.
- **The lap block** (LAP_COUNTER or BEST_LAP):
  - It hides group `b7a3bc7a`, then finds the lap time, the counter and
    the best lap.
  - In a two-player race that is not Be A Cop, it also finds the lead
    title and time.
  - It shows the ten lap objects.
  - It sets the three labels: laps, legs for a point-to-point race, and a
    time trial's target on the third.
  - A free run hides the counter and clears it.
- **SPLIT_TIMES:** the two split texts, hidden in both directions. UpdateHud
  shows them as the splits arrive.
- **LIVE_SPLIT or RACE_POSITION:** the four rows' status, swatch, position
  and background texts. The rows move under anchor `363392ae`, or under
  `363392af` when there is no race position. A row at or past
  `NumRacingCars` hides that row and every row after it.
- **TRACK_MAP:** `new TrackMap` on the current track, the car and the
  player, with the mode for the race kind. HUD state 1 turns the off mode
  into mode 2. Clearing the bit deletes the map.
- **TIRE_FORCE:** five objects shown, and four found.
- **PURSUIT, PURSUIT_HI and PURSUIT_NIS:** three copies of one meter. Each
  shows its group. When the meter is turned on, its block finds the star,
  the four levels (set to alpha 0 and hidden) and the three crosses, and
  reads the four `PURSUIT_DUMMY*_n` positions into `PursuitObjectPos`. It
  also clears `PrevPursuitLevel`. All three copies write the same Player
  fields.
- **SCORE and MUSIC:** each shows or hides its group. Turning the bit on
  finds the four texts and hides them; the score text is set to
  `TotalScore`. Turning it off clears the four pointers.
- **RACE_OVER:** groups `c707e093` and `97f9252a`. Two objects are hidden
  either way. When the bit turns on, FillInRaceOverMessages and
  RaceFinishedSpeech run with the RacingCar's `FinishReason`.
- **WRONG_WAY:** group `bbbb857c`. When the bit turns on, HudStartWrongWay
  runs once for each object in the group, as retail calls it inside the
  loop.
- **RESET_PROMPT:** group `f74c9d43`.
- **LETTERBOX:** the player's eView `LetterBox` byte.
- **CINEMA_BARS:** the bars screen is shown when the bit is set:
  - With one player, the call goes to screen `49c15518`.
  - With two players, outside Be A Cop and outside the flyby and prerace,
    the whole-screen bars are hidden. Each player's half (`accbfcb8` for
    player 0, `accbfcb9` for player 1) then follows the bit.
  - Otherwise, a two-player race uses the whole screen.
- **RADAR:** group `062743f5` and the twelve `RADAR_LIGHTn`. In a
  one-player race the group moves 70 down when the mirror bit changes. On
  the first pass, `fInitialRadarY` records the first light's Y. After that,
  `bRadarOffset` records whether the light has left that Y, and the group
  moves back up when the mirror leaves.
- **BE_THE_COP:** group `068e2c75`, the five damage lights and the four
  tickets. Player 0 gets the three helicopter and roadblock icons; player 1
  gets them hidden. The block also finds `BETHECOP_TIME`.
- **TRACKER:** group `c258f297` and `TRACKER_0` to `TRACKER_6`.
- **Egg 4**, every call: group `06d1f9fb` follows `TheEasterEggs` egg 4.
- **NIS_OVERLAY:** NISOverlayManager::SetVisible on `mFlailerNIS`.

Finally, `CurrentHudFeatures` is set to the new word.

Retail's oddities are kept, among them:

- Preference bit 0x100 controls the lap counter, the best lap and the
  choice of pursuit meter.
- The live split reads the anchor and the swatch twice.
- The gauge lists name `7307c47f` twice.
- The lap label's point-to-point test repeats the time-trial test with the
  race type reversed.
- `or_format` writes `FormatOptions` with no dirty flag in three blocks,
  where the others call SetFormatOptions.

## Departures

- **The seams.** These callees are not ported yet, and each is a function
  pointer that is skipped when NULL. The HUD functions are 8m-3 and 8m-4.
  - SetRearViewMirrorCameraMover (`0x001767a8`)
  - InitializeFlailerTachometer (`0x001434a0`)
  - TrackMap's constructor (`0x001babb8`) behind `bMalloc(176)`, and its
    deleting destructor (`0x001badc8`)
  - FillInRaceOverMessages (`0x00181558`), since ported by RE-2c
    ([race-over-overlay.md](race-over-overlay.md)) and bound in main.c
  - RaceFinishedSpeech (`0x00206ab8`)
  - HudStartWrongWay (`0x0017c888`)
  - NISOverlayManager::SetVisible (`0x00182a48`)
  - ClearHudAnimations (`0x0017c7c8`), which is `rcpost.h`'s
  - the NisManager's playing word, and the egg test
- **NULL tests.** Retail sets formats, alphas and positions on objects it
  has just looked up, and does not test them. The port tests each one and
  skips the call when the object is missing. The comments in
  `playerhud.c` mark each such place. A missing NIS manager counts as not
  playing.

## The checks

`tools/hudfeatures_check.py` runs retail's DetermineHudFeatures,
SetHudFeatures and SetTrackMapMode in `retail_model.RetailEmu`, on
INGAMEB's Flailer chunk loaded by retail's own LoaderFlailerChunk. Under
them run retail's IsNisPlaying, ShouldShowBustedText, IsFreeRun,
bSPrintf, bStringHash and the Flailer runtime. Everything else is stubbed
and prints its arguments: the screen visibility, the seams above, eGetView
and ChooseLoadableTextures. The camera's three virtual calls answer from
the script. `tools/src/hudfeatures_test.c` runs `playerhud.c` over
`flailer.c`, `bui.c`, `bchunk.c`, `copmanager.c` and `raceparams.c` on
the same bundle.

After each op, the checker compares:

- Determine's answer;
- the stubs' calls, in order;
- every line that changed: each Player's HUD fields (the `pFlailer*`
  pointers by object), the four views' `LetterBox`, the display settings,
  and every Flailer object's bytes.

Each pointer field starts on a dummy object, so a field that nothing
writes prints "stray". After each dump both sides clear every object's
`DirtyFlag`, as a drawn frame would, so a setter that stamps a flag the
load already left is still seen.

The script walks Determine through each case. It then turns each
SetHudFeatures bit on and off, one at a time and in pairs, through every
case of each block. It runs the two split screens for each player, with
and without Be A Cop. It tries every SetTrackMapMode mode in each kind of
race. Last, it runs UpdateHud's head for a few frames.

The result: 1298 ops, 10373 lines, 0 differ. Writing the two-player script
found one bug: the port showed the whole bars screen in a two-player race,
where retail hides it and shows the player's half.

The mutation pass (`--mutate`) makes 170 mutations: 164 are caught and 6
are equivalent, with 0 unexplained. The six:

- `det-cop-mask`: in Be A Cop, no HUD state sets PURSUIT_HI. Each one
  that does needs cop == 0, and the gauges never return it, so the mask
  finds it clear.
- `gauges-v-ignored`: SetHudFeatures takes both gauge bits out of the
  current word before the xor. A change in HUD_GAUGES therefore means the
  new word holds it, and the visibility is always 1.
- `music-null-kept`, `music-no-hide` and `over-objects-v`: the music
  texts (`0x6fc12a41`, `0x3c374056` and `0x1f87a436`) and BUSTED
  (`0x76494c5b`) are not on any of the three HUD screens. They are on
  BEST_LAP_TIMES, BEST_TOTAL_TIMES and the busted screens, so the finds
  answer NULL and the visibility calls find nothing to set.
- `wrongway-once`: group `0xbbbb857c` holds exactly one object,
  `0x89af1a1e`, on each HUD screen, so starting the animation once per
  object starts it once.

Six survivors of the first pass were real gaps in the script, now caught:

- Three dirty-flag mutants. The load leaves every text's `DirtyFlag` set
  until a frame clears it, so the checker now clears it after each dump.
- A circuit race with a time-trial time.
- A pursuit meter over an earlier `PrevPursuitLevel`.
- IsFreeRun's Be A Cop test.
