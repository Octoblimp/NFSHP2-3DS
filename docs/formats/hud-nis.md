# The NIS overlay (step 8m-4c-2)

When a cop pulls the player over, the race cuts to a NIS, a short scene
in the game's engine. The HUD plays an overlay over it that looks like a
camcorder: a blinking REC light, the date and the time, and a frame. For
a bust, BUSTED! grows in, and a cop in a one-player race also sees the
bounty's points.

NISOverlayManager owns the overlay. Its constructor, destructor,
SetScreen and Finish are in `nisoverlay.c` (`player.md`). This step
ports the rest:

| function | address | size | port |
|----------|---------|------|------|
| NISOverlayManager::Start | `0x00182488` | 360 | `nisoverlay_start` |
| NISOverlayManager::Update(bool) | `0x001825f0` | 344 | `nisoverlay_update` |
| NISOverlayManager::UpdateDateAndTime | `0x00182748` | 512 | `nisoverlay_update_date_and_time` |
| NISOverlayManager::SetVisible(int) | `0x00182a48` | 368 | `nisoverlay_set_visible` |
| NISOverlayManager::StartArrest | `0x001832f8` | 16 | `nisoverlay_start_arrest` |
| NISOverlayManager::StartTicket | `0x00183308` | 16 | `nisoverlay_start_ticket` |
| NISOverlayManager::StartBusted | `0x00228f10` | 16 | `nisoverlay_start_busted` |

All seven are in `hudnis.c`. `main.c` binds:

- `gNisOverlayUpdateFn`, which RenderHud (`hud-render.md`) calls while a
  NIS plays or the BUSTED text should show;
- `gNisOverlaySetVisibleFn`, which SetHudFeatures (`hud-features.md`)
  calls when the NIS_OVERLAY feature changes;
- `gCdReadClockFn`, the 3DS's clock (below).

The three Start* are called by the cops' NIS code, which comes with the
cops in step 12.

`0x00182bb8` and `0x00182c18`, which `retail_match` had once named as
the overlay's, are Player functions that lay out the score texts.
Nothing calls either.

## The fields

NISOverlayManager is 56 bytes (`nisoverlay.h`). The field at +24 is
retail's addition, and the port now names it `PointsDisplay`: Start
finds the "+2000" text there.

| offset | field | |
|--------|-------|-|
| 0 | `LastDateTimeUpdate` | RealTimeFrames at the last date |
| 4 | `ScreenHash` | the overlay's screen, or 0 |
| 8 | `State` | 0 idle, 1 ticket, 2 arrest, 3 busted |
| 12, 16 | `ScaleAnimationTrack`, `AlphaAnimationTrack` | tCubic1D, `banim.h`'s BSpline |
| 20 | `BustedDisplay` | the BUSTED! text |
| 24 | `PointsDisplay` | the "+2000" text |
| 28, 32 | `sx`, `sy` | BUSTED!'s top left, read at Start |
| 36, 40 | `ScaleX`, `ScaleY` | BUSTED!'s scale, read at Start |

## The screens

INGAMEB has three overlay screens, each with the same seven objects:
`3ea89b7c` for one player and Be A Cop, and `d4d25ee7` and `c17316c9`
for the top and bottom halves of a two-player race.

| hash | object | |
|------|--------|-|
| `0000d999` | text | "REC" |
| `001450dd` | text | the date, 17 characters at most |
| `001d380e` | text | the time |
| `76494c5b` | text | "BUSTED!", scale 2, hidden |
| `61cb41df` | bitmap | the REC light |
| `233dfbe1` | text | "+2000", scale 0.7, hidden |
| `9aba325e` | bitmap | the frame, at z 5 |

All seven are in group `97f9252a`.

## Start

Does nothing without a screen. Otherwise:

1. `LastDateTimeUpdate` = 0, and UpdateDateAndTime.
2. SetFlailerScreenVisibility(screen, VISIBLE), the screen enum's 0.
3. `BustedDisplay` and `PointsDisplay` are found, both as texts.
4. `sx` and `sy` are BUSTED!'s top left, and `ScaleX` and `ScaleY` its
   scale, as they are now. Finish puts back the scale SetScreen saved,
   so after a Finish this is the bundle's 2.
5. Each track starts with tCubic1D's methods inlined. Its flags are
   cleared and its duration set to 0.25 seconds. It is aimed at its
   start, snapped there, and aimed at its end:
   - the scale from 5 to `ScaleX`;
   - the alpha from 0 to 128.

To aim is to set `valDesired`, and state 2 when `val` is not already
that, by `c.eq.s`, so a NaN always sets it and −0 equals 0. To snap is
to copy `valDesired` and `dvalDesired` into `val` and `dval`, with state
0. So the second aim always leaves state 2 unless the end equals the
start.

## Update(playing)

1. **BUSTED!**, when there is one:
   - its top left y back to `sy` and its scale y to `ScaleY`;
   - FlailerTextChunk::ScaleAboutCenter to the scale track's value;
   - its alpha to the alpha track's value, truncated as `cvt.w.s` does,
     and the same alpha on the points.

   Its scale and alpha are set every frame, so it shrinks from scale 5
   to its own while it fades in.
2. **The tracks** take a SplineSeek step of `WorldTimeElapsed` each, with
   both clamps 0.
3. **The date** again when `RealTimeFrames − LastDateTimeUpdate`, as a
   wrapping 32-bit difference compared signed, is 31 or more. A
   difference that is negative, as when the frames go back, waits.
4. **The REC light** shows when `playing` and bit 3 of `WorldTimeFrames`
   is clear, so it blinks every 8 world frames. It is hidden otherwise.
5. **The frame** shows when `playing`, and is hidden otherwise.

## UpdateDateAndTime

sceCdReadClock fills an sceCdCLOCK: `stat`, then BCD bytes for second,
minute, hour, a pad, day, month and year. Nothing happens if the call
answers 0 or `stat` is not 0. Otherwise:

1. sceScfGetLocalTimefromRTC turns the clock into local time in place.
2. Each field is decoded as `(b >> 4) × 10 + (b & 15)`, with no check.
   So `0xff` is 165, and a year of 165 prints as "20165".
3. **The month's name.** Months 2 to 12 take ids `0xe86d` to `0xe877`
   from the language tables. Anything else, January and months 0, 13
   and up included, takes `0xe86c`, January. The test is unsigned
   `month − 2 < 11`.
4. **The date** goes into `001450dd`: "%s %d 20%02d" (name, day, year)
   in English (CurrLanguage 0), and "%d %s 20%02d" (day, name, year) in
   any other language. FlailerPrintf cuts it at the text's length, 17
   characters.
5. **The time** goes into `001d380e`: "%02d:%02d:%02d".
6. `LastDateTimeUpdate` takes `RealTimeFrames`.

## SetVisible(on)

Does nothing without a screen, or in a replay. A replay is the race
coordinator's state INSTANT_REPLAY (4), AUTO_REPLAY (5) or POSTRACE (7),
or else IsReplayDemoMode. The state is read inline from the coordinator's
first word.

- `on` 0 hides group `97f9252a`.
- For a ticket or an arrest, the group shows. That is all seven,
  BUSTED! and the points among them. Then the points are set.
- For a bust, the group hides, BUSTED! shows, and then the points are
  set.
- Idle, or any other state, does nothing.

The points show only for a cop (`BeACop` not 0) in a one-player race
(`NumPlayerCars` 1), and are hidden otherwise.

## StartArrest, StartTicket and StartBusted

Each sets `State` (2, 1 and 3) and runs Start. StartBusted is far from
the other two in retail's image.

## The 3DS's clock

`main.c` binds `gCdReadClockFn` to a reader that fills the same eight
bytes from `time()`, as the 3DS's own clock, which the player sets to
local time. It writes BCD second, minute, hour, day, month and the
year's last two digits, with `stat` and the pad 0, and answers 1.
`gScfGetLocalTimeFn` stays NULL: sceScfGetLocalTimefromRTC turns the
PS2's clock, which keeps Japan's time, into the console's time zone, and
the 3DS's clock already is local.

## Where the port differs

- **PointsDisplay.** Update writes the points' alpha through
  `PointsDisplay` whenever BUSTED! is there. Retail does not test it;
  the port skips a NULL one. Both texts are on all three screens.
- **The coordinator.** Retail reads `pRaceCoordinator`'s state
  unchecked. The port treats no coordinator as not a replay.
- **The seams.** No clock reader, a clock that answers 0, and no
  translation all leave the date be. A NULL translation prints as an
  empty name, where retail would print what bSPrintf makes of NULL.
- **The date's wait.** The port writes the difference as an unsigned
  subtraction, since a signed one could overflow, which C leaves
  undefined.
- `nisoverlay_set_visible` takes `on` as `uint32_t`, as
  `gNisOverlaySetVisibleFn` does. Retail's is an int. Only `!on` is
  read.

The checker shows none of these.

## banim.c's GetdVal

This step's checker is the first to run the port's BSpline against
retail's own tCubic1D. It found that `bspline_get_dval` rounded
differently from GetdVal (`0x001da800`, and the demo's `0x001d00c8`):

- retail: `(c0 × (t × 3) + (c1 + c1)) × t + c2`;
- the port: `((c0 × t) × 3 + c1 + c1) × t + c2`.

`dval` was off in its last bit from the third frame on. `banim_check`'s
Python model has its own copy of the curve, and it had the same mistake
in the first product, so the two agreed. Both now follow retail. Only
the frontend's animations and this overlay use the tracks, and GetVal,
MakeCoeffs and the seek were already retail's.

## The checker

**`tools/hudnis_check.py`** runs the seven retail functions in the
emulator, against the port in the harness `tools/src/hudnis_test.c`.
Underneath are retail's SplineSeek, FlailerPrintf with bSPrintf, and the
Flailer runtime on INGAMEB's Flailer chunk. The text and texture sizes
are flailer_check's stub answers.

**The stubs.** The overlay does not own these callees, so both sides
script them the same way and log each call:

- sceCdReadClock: the eight bytes it writes, and its answer.
- sceScfGetLocalTimefromRTC: the bytes it is handed, and what it writes
  over them, if anything.
- GetTranslatedString: the id and the text. Two months have no text
  scripted and answer `M` and the id.
- IsReplayDemoMode: whether it was asked of the coordinator, and its
  answer.
- SetFlailerScreenVisibility: the screen and the value.

**What is compared.** The stubs' logs and, after each op, every line
that changed: the overlay's fields, both tracks' 48 bytes and every
Flailer object's bytes.

**The script** covers:

- **No screen:** Start, the Start*, Update both ways, SetVisible both
  ways, and the date.
- **Start** on the single screen, then 20 frames as the tracks arrive;
  not playing; the REC light's blink on each side of bit 3, at negative
  frames and near the top of the int.
- **The date's wait** at 30 and 31 frames, frames going back, and across
  the int's wrap in both directions.
- **The step:** 0, negative, a tenth, a second and a huge one.
- **The tracks:** alphas between whole numbers, negative, past 128,
  huge, NaN and infinite; scales mid-way; Start with the tracks already
  where they are aimed, at −0, and at NaN; BUSTED! already at scale 5,
  at a NaN scale, and at 2; no BUSTED!, and neither text.
- **The date:** every month in BCD and out of it (0 to 13, `0x0a` to
  `0x0d`, `0x1f`, `0x20`, `0x80`, `0x99`, `0xff`), odd BCD in every other
  field, a clock that answers 0, −1 or 2, a busy `stat`, a local time
  that overwrites the clock, each language, a name too long for the
  text, an empty one, and a negative `RealTimeFrames`.
- **SetVisible:** every overlay state with `on` 1, 0, 2, `0xffffffff`
  and `0x100`; the cop and not, with 0, 1, 2 and −1 players; every
  coordinator state 0 to 9, −1 and 100, each with the replay demo off
  and on.
- **The Start*,** each followed by SetVisible and frames, for the cop
  and not.
- **The other screens:** both two-player halves, a screen without the
  overlay's objects, and the single one again, each with a bust, frames,
  a ticket and the date.

The result is 818 ops, 4359 lines, and 0 differences.

The mutation pass makes 119 mutations. 118 are caught, and 1 is
equivalent:

- `arrest-state-after`: Start reads nothing of `State` and calls
  nothing that does, so `State` comes out the same whether it is set
  before Start or after.

The first pass had 1 survivor that was a gap in the script:
`start-last-kept`. Start zeroes `LastDateTimeUpdate` before it reads
the clock, and every scripted Start had a clock that worked, which
writes the field again. Two Starts are now in the script, one with a
clock that fails and one with a busy clock, each followed by a frame
that shows the wait, and the mutation is caught.
