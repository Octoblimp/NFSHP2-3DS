# The HUD each frame (step 8m-3)

Player::UpdateHud (`0x0017ecf0`) runs once a frame for each player, from
UpdateNonGameState. [hud-features.md](hud-features.md) covers its head:
which parts of the HUD to show, and the Flailer objects found for them.
This step ports the rest of UpdateHud and all of RenderHud
(`0x0017f040`, 6812 bytes, no symbol), which writes the frame's numbers
into those objects. Their helpers come with them:

| function | address | port |
|----------|---------|------|
| Player::UpdateHud | `0x0017ecf0` | `player_update_hud` |
| Player::RenderHud | `0x0017f040` | `player_render_hud` |
| the score's fade | `0x0017d7c8` | `player_fade_score` |
| Player::GetCurrentBestLapRecord | `0x0017ef60` | `player_get_current_best_lap_record` |
| Player::ConvertScoreString | `0x0017e220` | `player_convert_score_string` |
| Player::DisplayDebugInfo | `0x00181230` | `player_display_debug_info` |
| GetLetterForGear | `0x00178b70` | `get_letter_for_gear` |
| TriggerTimerWarningSound | `0x001afb80` | `trigger_timer_warning_sound` |
| RacingCar::GetFinishReasonId | `0x00146788` | `racingcar_get_finish_reason_id` |
| RacingCar::GetLastStartLineCrossingTime | `0x00147540` | `racingcar_get_last_start_line_crossing_time` |
| RacingCar::GetLastLapTime | `0x00147570` | `racingcar_get_last_lap_time` |
| RacingCar::GetBestLapTime | `0x00147588` | `racingcar_get_last_best_lap_time` |
| RacingCar::GetPreviousBestLapTime | `0x001475a0` | `racingcar_get_last_previous_best_lap_time` |
| Race::CalculateSplitTime | `0x001487e8` | `race_calculate_split_time` |
| bSPrintf, bVSPrintf | `0x00251398`, `0x00251440` | `b_snprintf`, `b_vsnprintf` |

`hudrender.c` holds the HUD, `racesplit.c` the Race and RacingCar
accessors, and `bprintf.c` bWare's printf. Two checkers test them against
the image: `tools/hudrender_check.py` and `tools/bprintf_check.py`.

The callees still to port (8m-4) are seams that the port skips while they
are NULL. `main.c` binds the translation seam:

- HudDoAnimations (`0x0017e038`)
- UpdateScoring (`0x0017e820`)
- StartScore (`0x0017e558`)
- HudStartSpeedAnimation (`0x0017cd30`)
- HudStartGrowAnimation (`0x0017cb18`)
- UpdatePursuitMeter (`0x0017c380`)
- UpdateRadarDetector (`0x0017be70`)
- DrawTracker (`0x0017c278`)
- NISOverlayManager::Update (`0x001825f0`)
- GetTranslatedString (`0x0021e560`)

## UpdateHud

1. UpdateHud's head: DetermineHudFeatures, and SetHudFeatures when the
   answer changed.
2. HudDoAnimations.
3. The score's fade: the score title and total fade in over half a second
   from `tScoreAnimation`, hold until 4.5 s, and fade out by 5 s. Alpha
   128 is full. After 5 s both are hidden and the stamp goes back to
   `0x7fffffff`. An unset stamp, or a missing object, skips the fade.
4. In a race at stage 4 (racing), when the coordinator is in none of
   PAUSE, INSTANT_REPLAY, POSTRACE, AUTO_REPLAY or REPLAY_DEMO_MODE:
   - **The start bonus**, once a race. `New2736` (Player +2736) records
     that it has run.
     - With two players and no driver knocked out (NumEliminated,
       `0x001edcd0`), the places behind the player are marked in
       `baPlaceReached`. When the player is last, the place just behind
       is left out.
     - Otherwise each place from last up to the player's is marked and
       scores its ScoreInfoTable "TOOK Nth PLACE" entry. The entry for
       the place k from last is `NumRacingCars + 14 - k`, read through
       ConvertScoreString. A total that is not 0 is printed `"+%d"` into
       `strEventScore` and goes to StartScore as `SCORING_START_BONUS`
       (15).
   - UpdateScoring.
5. RenderHud, when `CurrentHudFeatures` is not 0.

ScoreInfoTable (`0x002fbbf0`) has thirty 36-byte entries in eScoring
order: the string id, the English name (20 bytes) and the score as text
(12 bytes). ConvertScoreString reads an optional `-` or `+` and then
digits, wrapping in 32 bits. Anything else stops it.

## RenderHud

The car is the player's, or the camera's when `CameraFollowDefaultCar`
(gp-21532) is 0 and WorldGetCarByDriverNumber finds
`CameraFollowThisCarInstead` (gp-21528). The gauges' ranges and angles,
the red line and the max rpm always come from the player's own car's
CarTypeInfo. The RacingCar is the race's for that car. The sections run
in this order:

| section | when | retail |
|---------|------|--------|
| speedo, tach | any gauge bit (GAUGES, GAUGES_OUTSIDE, GAUGES_IN_CAR); else `LastSpeed` = 999 | `0x0017f0d8`-`0x0017f708` |
| lead | LAP_TIME or LAP_COUNTER, a RacingCar, `pFlailerLeadTitle` | `0x0017f710`-`0x0017f7b0` |
| lap time | LAP_TIME, a RacingCar, the object | `0x0017f7b4`-`0x0017f98c` |
| best lap | BEST_LAP, the object | |
| splits | SPLIT_TIMES, a RacingCar, both objects | `0x0017fa1c`-`0x0017fcdc` |
| leaderboard | LIVE_SPLIT, a RacingCar | `0x0017fcec`-`0x001800b4` |
| lap counter | LAP_COUNTER, the object | `0x001800cc`-`0x00180190` |
| position change | a RacingCar | |
| race position | RACE_POSITION, the object | `0x001801e4`-`0x00180344` |
| tyres | TIRE_FORCE | `0x00180368`-`0x00180414` |
| pursuit meter | PURSUIT, PURSUIT_HI or PURSUIT_NIS | |
| radar | RADAR | |
| Be The Cop | BE_THE_COP and a cop manager | `0x00180478`-`0x001808b0` |
| NIS overlay | NIS_OVERLAY, and a NIS playing or the busted text | |
| trackers | TRACKER in a race at stage 4; else all seven hidden | `0x00180900`-`0x00180a94` |
| debug strings | always | DisplayDebugInfo |

The HUD info floats (CarTypeInfo +1232) the gauges use:

| offset | value |
|-------:|-------|
| 4, 8 | the tach's angles |
| 24, 28 | the MPH dial's angles |
| 32, 36 | the KPH dial's angles |
| 40, 44 | the MPH range |
| 48, 52 | the KPH range |

### The speedo

The speed is `ForwardSpeed` × 3.6 with `Units` 1 (km/h). For every other
setting it is × 2.237 (mph). Each unit has its own range and angles.

**The top speed.**

- `TopSpeed` 0 is first set to `SpeedFactor` × max, truncated.
- `bNewTopSpeed` is cleared every frame.
- A frame under `SpeedMinFactor` (0.7) of the max arms `bCheckTopSpeed`.
- Once armed, a frame that has these four conditions raises `SpeedFactor`
  by 0.1 (to at most 1), disarms the check and sets `bNewTopSpeed`:
  - not Be A Cop;
  - slower than `LastSpeed`;
  - `TopSpeed` under `LastSpeed`;
  - `SpeedFactor` under the speed's ratio of the max.

**The needle** is the speed's fraction of the range, clamped to [0, 1].
It turns from angle 0 to angle 1, going up through 360 when angle 1 is
the smaller. An angle over 360 loses 360. An angle under 0 becomes 360
less the angle; that is retail's arithmetic, not a wrap.

**The digits** print `"%3d"` of the truncated absolute speed. Outside the
in-car view, passing a multiple of 50 from 100 to 400 since `LastSpeed`
first prints the second text. HudStartSpeedAnimation then runs on the
two texts, with WorldTimer and flag 1. `LastSpeed` ends as the truncated
speed.

### The tach, the shift light, the gear

- The rpm is the car's, unless `TachTestRpm` (gp-18380) is not 100; then
  it is `TachTestRpm`. Its fraction of `MaxRPM` is clamped to [0, 1].
- The angles are the HUD info's for GAUGES. The other views use 45 to
  215.
- The shift light shows only with `TransmissionType` 1 (manual). It is
  `80008000` at or over the red line in a forward gear, and `80002000`
  otherwise.
- The red gradient turns to angle 0, plus the red line in whole 500s
  over `MaxRPM` × (angle 1 − angle 0).
- The gear letter comes from GetLetterForGear's ten pairs at
  `0x002fbaf8`: A, R, N, 1 to 7 for gears −1 to 8, and X for anything
  else. Its colour is `00808080` with the clutch engaged and `00404040`
  without.

### Laps and splits

The Timer words are ticks of 1/4000 s, and 0 or `0x7fffffff` means unset.
Times print through Timer::PrintToString in the game's language.
[realtime.md](realtime.md) covers that.

**The lead** (two players). Race::CalculateSplitTime of the other
player's RacingCar against this one prints with a sign, in fixed-width
digits (format option `0x40`, `BUI_FMT_FIXEDWIDTH`). The title is `0x18e73` ("ahead") when the text starts
with `+`, and `0x18e74` otherwise.

**The lap time.** This is WorldTimer less the last start-line crossing.

- When both it and the race's `TimeTrialTime` are set, it counts down
  instead: the time-trial time less that time.
  - In the first 3 s of a lap it is the time-trial time less the last
    lap's time, when that is set.
  - Past 0 it is shown as a positive number, coloured `400535be`.
  - Under 10 s it is coloured `4004d5e2` and ticks TimerCountdown once
    for each whole second.
  - Otherwise it is coloured `402aae01`.
- An unset lap time prints as 0.

**The best lap.** GetCurrentBestLapRecord picks the time. With no valid
time it prints `--:--:--`.

- The record is the player's total-time record point to point, and the
  lap record otherwise.
- In a race of laps that is not a time trial, the car's
  `BestRunningTimes` at the finish line wins when it is set and the record
  is not, or when it is lower. The splits use `PreviousBestRunningTimes`
  there instead.

**The splits.**

- The region is `(HighestBoundaryRegion + 5) % 5`. A negative remainder
  hides both texts.
- The running time shows for 5 s after that region's crossing, while its
  running time is set. It prints in FONT_A.
- The comparison depends on `SplitTimeType`:

  | type | compared with |
  |-----:|---------------|
  | 0 | the leader; the second when the player leads and there are two or more cars |
  | 1 | the previous best lap, at the line (region 0) only |
  | 2 | the previous best running time at the region |
  | 3 | the previous running time at the region |

- A comparison that is already showing reprints only when
  `LiveUpdateSplitTimeRate` (gp-20944, 0) is set and divides
  `WorldLoopCounter`.
- A hidden comparison prints when the rate is set, or within 0.2 s of the
  crossing.

**Race::CalculateSplitTime(out, a, b)** is how far b is behind a.
Finished means FinishReason 1.

| case | result |
|------|--------|
| both finished | b's RaceTime less a's |
| a finished | the time around the track from b's FinishedLapNumberExact back to a's NumLapsCompleted, less a's time done |
| b finished | from b's NumLapsCompleted back to a's FinishedLapNumberExact, plus b's time done |
| neither | from b's FinishedLapNumberExact back to a's |

A car's time done is WorldTimer − RaceTime − the race's StartTime,
unsigned.

### The leaderboard

There are four rows: the leader, then three from `start`. `start` is 2,
except with `LeaderboardMode` 2: then it follows the player, at RacePosition − 1
held under `NumRacingCars` − 2, and 2 when that is 1 or less.

Each row's place digit is `'0' + n`. The colour swatch is the car's skin's
`ColourSwatchHash`, from CarTypeInfo::GetSkinInfo(type, skin, 1). The
player's row moves `pFlailerLiveSplitBar` to the row's background and
hides the background. The status text is, in order:

1. In the first 100 of every 500 frames (`WorldTimeFrames`), or before
   the car has crossed the start line: a name. On odd 500s it is the car's
   short name (CarSpecs `ShortName`, translated). Otherwise it is the
   player's name for the player's car, and the driver's
   CharacterInfo name for the others.
2. A finish reason's string. These are the six words at `0x002f0bc0`:
   `49448`, `49445`, `49447`, `49449`, then `ecd12` twice.
3. The player's name, on the player's row.
4. `0x49446` "pulled over", from the cop manager's CarPullovers by
   CarIndex.
5. The gap. The laps between the two cars' `CurrentLapNumberExact`,
   truncated, print as `"%d %s"` with `0x494aa` "LAP" or `0x494ae` "LAPS".
   On the same lap the gap is the split time, signed and fixed-width.

Every status but the split clears the fixed-width option.

### Position, lap counter, tyres

**The lap counter.**

- Around a circuit it prints `"%d/%d"`: laps done + 1 of the race's laps.
- Point to point it prints `"%5.1f %%"`. The figure is the progress from
  the start line's lap number (Race::GetLapNumberExact of the start
  boundary's distance) to 1, clamped to [0, 1], times 100.

**A change of position** stamps `PosChangeTime` (WorldTimer / 4000). It
sets `PositionFlag` to 1 for a gain and −1 for a loss.

**The race position** prints in a big text, with a total and an ordinal
after it.

- A set `PositionFlag` first prints the new or the last place in the
  second text and starts the grow animation. The animation's flag is 1
  for a gain.
- The total is `"/%d"` of the cars in the race. In a lap knockout it is
  the cars still racing.
- The ordinal is string `0xeeac` + the place. A player whose
  `PreferredGender` is 1 gets `0xeeb5` for first.

**The tyres.** Each wheel's `WheelTractionUsage` u is held against a
threshold of 0.9.

- Under it, the colour is `80008000` + trunc(u / 0.9 × 255).
- At or over it, the colour is `80000080` + (trunc((1 − (u − 0.9) / 0.1)
  × 255) << 8).

### Be The Cop's panel

- **The time left** prints `"%3.0f"` over 10 s and `"%3.1f"` otherwise.
- **The helicopters and roadblocks.** Each has three lights, coloured in
  turn: one per item used (`ff005000`), one for an item coming
  (`ff500000`), and the rest left (`ff000050`).
  - A helicopter counts as coming unless one can be called.
    `0x00224ec0` decides that: the World has one (`World+24`), the race
    allows it (`New624`), its word at +960 is 0, and the manager's
    `bChopperBusy` is clear.
  - A roadblock counts as coming when the player cop's pursuit has
    `New1560` set.
- **The chased car's damage** sets five lights (`ff000070` on, `ff000020`
  off). The number on is damage × 5, truncated, plus 1 for any damage at
  all, and at most 5.
- **The tickets.** In a race of one, every AI racer's tickets are summed
  over four lights. Otherwise the other player's (`pPlayersByIndex[1]`)
  are shown over three.

### The trackers

The trackers are dots over the AI racers and then the cops.

1. All seven are hidden.
2. Each car being drawn gets DrawTracker with its tracker index. Indexes
   run on through both blocks up to 7. Racers are coloured `ff0035ac`
   and cops `ff800000`.

### The debug strings

DisplayDebugInfo runs every frame.

1. It finds its four texts on the HUD screen on first use: `fa10332f`,
   `2df92633`, `d8f8bd54` and `f8c20c4a`.
2. It writes their visibility byte directly from `DisplayPlayerDebugInfo`
   (gp-20700).
3. When that is set, it prints:
   - `"C: %dfps"` and `"G: %dfps"` of the two frame rates;
   - `"%.0f %.0f %.0f s%d"` of the car's position and the zone;
   - `"%f km"` of the odometer.

## bSPrintf

The HUD's numbers go through bWare's printf: FlailerPrintf calls
bVSPrintf, and the start bonus and the debug strings call bSPrintf.
`%d`, `%s` and the like print as the C library's do, but `%f` does not.
`bprintf.c` keeps those differences on top of `snprintf`:

- **Precision.** With no precision, `%f` has 3 places, not 6:
  `"%f km"` of 12.3455 is `12.345 km`.
- **Rounding.** The last place rounds half away from 0. `%.1f` of 0.25
  is `0.3`, and of −7.25 is `-7.3`. The C library rounds both ties to
  even.
- **The sign** is printed only for a value below 0: −0 prints as `0`. A
  negative value that rounds to 0 keeps it: −0.4 at `%.0f` is `-0`.
- **Size letters.** `h`, `l` and `L` are the only ones, in any order and
  number. Any `h` makes a short: `%lhd` of 70000 is `4464`. Everything
  else is 32 bits.
- **`%p`** is eight upper-case hex digits, padded to the width.
- **`%n`** takes its pointer and writes nothing.
- **Unknown letters** print as themselves and take no argument.
- **Large values.** Past about 1e23, retail's digits drift from the exact
  value. The port prints the exact one.

bWare has its own conversions as well, for fixed point and vectors:
`%b %t %v %w %y %z %B %C %S %I %N`. The vector printer's
`"[%*.*z,%*.*z]"` is at `0x002bf728`, and an argument that is not a vector
prints `bPrintf:invalid bVector`. `%e`, `%g` and `%F` differ too:

- `%e` has three exponent digits and three places.
- `%g` is `%e`.
- `%F` prints nothing and then the next spec as text.

Nothing the port prints uses any of these, so they are not ported.

## What the port does differently

The port checks things retail does not. Each case reads garbage or
memory the HUD does not own in retail. A real game never reaches them,
and the checker leaves them out.

- **The helicopter lights** are an array of three. With four or more
  helicopters used, retail's loop runs on into `Roadblock[0..]`
  (Player +1384). The roadblock loop then sets those again, so the
  screen is the same. The port stops at three.
- **The ticket lights** are an array of four. A fifth ticket in a race of
  one runs on into `pFlailerLiveSplitStatus` (Player +1300) and the
  leaderboard pointers after it. In Be The Cop those are NULL, since the
  game never sets LIVE_SPLIT or RACE_POSITION there. The port stops at
  four.
- **The lead.** Retail does not check `pOtherPlayer`, its car, the other
  RacingCar or `pFlailerLeadTime`. A two-player race always has them.
- **The trackers.** Retail does not check the World or the CarTable's
  cars.
- **Be The Cop with two players.** Retail checks `pPlayersByIndex[1]` but
  not its car.
- **CalculateSplitTime** reads through a NULL TimeAroundTrackTable in
  retail. The port takes 0.
- **The RacingCar accessors** index by a signed byte with no bound. For a
  number outside [0, 4] the port hands back an unset Timer.
- **GetFinishReasonId** has no bound in retail. The port answers 0
  outside the six.
- **Pulled over, and the chased car's damage,** read the cop manager's
  arrays by `CarIndex` with no bound in retail. The port answers "not
  pulled over" and 0 damage past 14 cars.

## The checks

**`tools/hudrender_check.py`.** The model is retail's own: UpdateHud,
RenderHud and GetCurrentBestLapRecord run in `retail_model.RetailEmu`.
Under them run retail's DetermineHudFeatures, SetHudFeatures, the Flailer
runtime, Timer::PrintToString, CalculateSplitTime and the accessors,
NumEliminated, bSPrintf and bVSPrintf.

- **The stubs** are the 8m-4 seams, plus WorldGetCarByDriverNumber,
  GetSkinInfo, the zone, GetLapNumberExact, the TimeAroundTrackTable and
  the sample player. They print their arguments and answer from the
  script.
- **The harness** is `tools/src/hudrender_test.c`. It runs `hudrender.c`,
  `racesplit.c`, `timer.c`, `playerhud.c`, `flailer.c`, `bprintf.c`,
  `bui.c`, `bchunk.c`, `copmanager.c` and `raceparams.c` on the same
  INGAMEB bundle.
- **After each op** the checker compares the stubs' calls, each Player's
  HUD fields, and every Flailer object's bytes.

The script sets up two players, a six-car race, a World and a cop
manager. It then walks every section through its cases:

- **Gauges:** speeds through each fifty, the top-speed check, both units,
  dials that wrap, the test rpm, the red line exactly, each gear.
- **Laps and splits:** time-trial countdowns over and under 10 s, each
  best-lap source, each split type with and without its time. Each
  comparison is printed: fresh crossings for every split type and best,
  either side of the 0.2 s window on a hidden comparison, and the live
  rate on and off its frames.
- **The leaderboard:** each status and mode 2 at every place.
- **Position and tyres:** positions, knockouts, both genders, tyre
  thresholds.
- **Pursuit and Be The Cop:** the pursuit levels, and every count of
  helicopters, roadblocks, damage and tickets.
- **The rest:** NIS and busted, the trackers over each mix of cars, the
  follow camera, the debug strings, two players, and UpdateHud's fade,
  start bonus and skipped states.
- **ConvertScoreString** on its own, over signs, junk and 32-bit wrap.

The result is 1278 ops, 7620 lines, and 0 differences.

Writing the checker found two bugs:

- The port printed with the C library. Its `%f` gave six places and
  rounded ties to even. That is why `bprintf.c` exists.
- CarSpecs' field names were off by one. The retail record has a seventh
  word (the top speed in km/h) that the demo's lacks, which put the
  leaderboard's `ShortName` one slot out.

The mutation pass makes 156 mutations: 152 are caught and 4 are
equivalent.

- `lead-not-signed` drops RenderHud's OR of `BUI_FMT_FIXEDWIDTH` on the
  lead time. SetHudFeatures sets the same bit whenever it finds the
  object, so the OR changes nothing.
- `pos-grow-shows-new` and `pos-grow-flag-reversed` change the test that
  starts the big position's grow. RenderHud stores the position into
  LastRacePosition just before the test, so the two values are always
  equal there.
- `rs-boundary-unbounded` removes the port's bound on the boundary
  index. Retail reads past BoundaryCrossingTimes for a
  StartLineBoundaryNumber of 5 or more, and the script leaves that out.

The first pass had 12 more survivors, and all were gaps in the script.
Eight were in the splits: the comparison was printed on too few frames
to show each split type, best, sign and window. The others were the
score's fade at its unset stamp and its 4 s hold, the shift light exactly
at the red line, and the lead with no lap counter. The script now covers
each one.

**`tools/bprintf_check.py`** runs retail's bSPrintf in the emulator
against `b_snprintf`, with a guard behind the buffer. Retail has no
bound, so a buffer of N bytes is compared as the first N − 1 bytes of
retail's text, with retail's whole length as the answer. The script
covers:

- 28 `%f` forms over about 170 values. These include ties at every
  place, values either side of a tie, −0, denormals, and values up to
  1e22.
- The integer, character, string and pointer conversions, with every
  flag.
- The size letters, `*` widths and precisions, and unknown letters.
- The HUD's own formats.
- Buffers from 0 to 17 bytes.

The result is 5879 ops, 11758 lines, and 0 differences. The mutation
pass makes 36 mutations: 35 are caught and 1 is equivalent.
`h-on-c-too` is equivalent because the C library ignores `h` on `%c`, on
the host and in the 3DS's newlib.
