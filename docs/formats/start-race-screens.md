# The start-race screens and the Starting Grid

Before a race, retail shows one or more Flailer screens over the fly-by
camera. For a quick race this is the "Starting Grid": each racer's name and
car by starting position, the track's name, and "\x86 next" bottom left.
Pressing X (A on the 3DS) ends the fly-by.

The code is retail's PRERACE_STATS module, `0x001e27b8` .. `0x001e3b40`.
Step 11g-2c-2b ported it in `3DS Files/source/startrace.c`. The coordinator
side is in [race-coordinator.md](race-coordinator.md):

- RCSTATE_CAMERA_FLYBY's ACTIVATE calls `EnableStartRaceScreens`;
- its UNACTIVATE calls `DisableStartRaceScreens`;
- its TICK moves to RCSTATE_PRERACE once `FlyByCameraCoordinator` says it
  is finished;
- RC_SKIP moves to RCSTATE_PRERACE at once.

The fly-by itself is in [camera-coordinator.md](camera-coordinator.md).

## `tStartRaceScreenManager`, 24 bytes

`TheStartRaceScreenManager` is at retail `0x0031a3e0`.

| Offset | Field |
|---:|---|
| 0 | `Screens[4]`: name pointers |
| 16 | `NumScreens` |
| 20 | `CurrentScreen` |

A screen is its name's address. The four names are retail's gp-17444 to
gp-17432, and `BACK` compares the pointers, not the strings.

`Enable` (`0x001e2870`):

1. It zeroes the count, the current screen, and `Screens[0]` and
   `Screens[1]`. `Screens[2]` and `Screens[3]` keep what an earlier race
   left in them.
2. It adds the screens in this order, each only when its test is true:

   | Screen | Test |
   |---|---|
   | "Pre Race Blurb" | `NeedToSeeObjective`: with BeACop, one player car; otherwise the race's HasObjective |
   | "Pre Race 2P Be A Cop" | BeACop with two player cars |
   | "Pre Race Stats" | not BeACop, and the game type is not 6 (the challenges' Free Run) |
   | "Pre Race Letterbox" | none of the three above |

3. It changes to `Screens[0]` and pushes the current screen.

`AddScreen` stops adding at four screens. `Disable` calls
`ChangeToScreen(NULL, 0)`. `StartRaceScreensReadyToSkip` answers
`CurrentScreen == NumScreens - 1`.

## The grid, `PreRaceStats`, 400 bytes

The screen is `PRERACE_STATS` in INGAMEB, hash `0x89b2fc0f`. Its callback:

- ACTIVATE allocates a `PreRaceStats` and constructs it;
- UNACTIVATE destroys it;
- every other message goes to `HandleEvent`.

The object is a 16-byte head (the screen's hash, then padding) followed by
eight 48-byte lines:

| Offset | Field |
|---:|---|
| 0 | `StartPosition`: 1 to 8, 0 for an unused line |
| 4 | `CharacterName` |
| 8 | `CarTypeNumber` |
| 12 | `KOStatus`: a LanguageID |
| 16 | `Points` |
| 32 | `Color` (`bVector4`) |

The constructor (`0x001e2d40`) does the following:

1. It sets the track's name on `0xf601f2d4`, from `TrackLanguageID` or
   `ReverseTrackLanguageID` by the race's direction.
2. In a multi-track event, it prints "Race %d of %d" on `0xd0ced2e2`. A
   multi-track event is `UseTheRaceEvent` and RaceType 4 or 5. The race
   number is the event's index plus one, held to the count. Otherwise the
   object is hidden.
3. It zeroes the lines and builds them, in one of three ways:
   - **Default**: a line for each racing car, at most eight. A player's
     line has its PlayerSettings name and the player's colour. Any other
     line has the character's name, or "", and grey (128).
   - **Knockout**: used for game type 4, or game type 8 or 9 on a
     knockout event. It builds the default lines and marks each one
     "racing". It then adds a red line for each driver already
     eliminated, at the place it went out in. These extra lines are not
     held to eight.
   - **Tournament**: used for game type 8 or 9 on a tournament event. It
     builds the default lines, then adds each racer's points from
     `GetTournamentState`, indexed by `RacerIndexFromDriverNumber`.
4. It fills positions 1 to 8. It finds the line with each starting
   position and sets POS_n, NAME_n, TYPE_n and STATUS_n from it (the
   names go through `SprintfAndHash`). A position with no line is hidden.
   TYPE_n is the car's short name, passed through `GetTranslatedString`.
5. It shows "\x87 previous" only when a screen comes before the grid. It
   always shows NEXT.

`HandleEvent` (`0x001e3148`) handles these messages:

- **Up and down** make no sound.
- **BACK** steps back one screen, if there is one, and changes to it
  without a push. When the step lands on the same screen, it makes no
  sound.
- **SELECT** posts RC_SKIP, unless its Param is `JOY_EVENT_START` (7).
  In that case it makes no sound.

The grid's MENUITEM_1 sits off the screen (y 546) and only takes the pad.

The letterbox (`0xa3e1bc36`, three objects) posts RC_SKIP on any SELECT,
START's included.

### SELECT's Param: a bmenu fix

`FlailerMenuItem::JoyHandler` (retail `0x00169d98`, demo `0x001651d8`) puts
the JoyEvent in the callback data's Param, `sw s2,24(sp)`, for every item
message. The port's `bmenu.c` had never done this, and the grid needs it:

- START reaches the item as a SELECT with Param 7, and does not skip;
- X and A arrive with Param 9 and do skip.

`item_joy` now sets `d.param = ev`. `tools/bmenu_check.py` models it and
prints Param on every message line. The check passes with 0 differ on the
demo's FRONTB and on retail's INGAMEB and FRONTB.

## The port

The table below lists the seams set in `main.c`:

| Seam | Bound to |
|---|---|
| `gEnableStartRaceScreensFn`, `gDisableStartRaceScreensFn` | `enable_start_race_screens`, `disable_start_race_screens` |
| `gChangeToScreenFn` | `bgf_change_to_screen` on the flow |
| `gStartRaceTranslateFn`, `gStartRaceTranslateStringFn` | the car selector's string hooks |
| `gRaceEventGetRaceCountFn`, `gRaceEventGetTournamentStateFn` | NULL: RaceEvent is not ported, and quick races do not read it |

"Pre Race Stats" and "Pre Race Letterbox" are rows in `kScreens[]`. The
race draws visible Flailer screens over its view, so the grid draws over
the fly-by on the top screen. The cinema bars are a separate screen,
`0x49c15518`, which the HUD shows in the fly-by and the pre-race
(`playerhud.c`, `HUD_CINEMA_BARS`). The grid's dark backdrop (`0x62229da7`,
y 89 to 391 of 480) covers exactly the part of the view between the bars.

The Blurb (`0x001e3270` on) and the two-player You're The Cop screen
(`0x001e36f0` on) are not ported, because no race the port can start shows
them.

On Azahar, a quick race from the frontend went through these stages:

1. After loading, it showed the grid over the fly-by: Desert Heat II,
   Mika, Wayne, Ashley and Player1, with the player's row in orange.
2. It stayed in RCSTATE_CAMERA_FLYBY for about 20 s, until the script's
   first A press.
3. That A sent the grid a SELECT, which posted RC_SKIP.
4. PRERACE has no coordinator yet (step 11g-2c-2c), so it ended at once,
   and the countdown and the race followed.

Open: in the fly-by, single-pixel specks of 150 to 210 grey show over
the grid's backdrop along distant road lines. They are brighter than
anything under the backdrop could be. Their cause is not known yet. Check
for them on a device.

## The check

`tools/startrace_check.py` runs retail's own module in `retail_model`,
beside the harness `tools/src/startrace_test.c`.

- **Ops:** 4817, giving 18822 transcript lines, 0 differ.
- **Mutations:** 197, from 193 caught (11 of them by a crash or a hang)
  and 4 equivalent:
  - `en-s0`: Enable always adds a screen, so `Screens[0]` is always
    rewritten.
  - `bd-ko`, `bd-pts` and `bk-pts`: the constructor's memset already
    leaves those fields 0.

The mutations include `fred_is_multi_track` in `fredrace.h`.
