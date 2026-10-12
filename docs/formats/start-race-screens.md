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
| `gFlailerTextIntoRectangleFn` | `flailerTextIntoRectangle`, which queues the strip with `uirender_queue_text_rect` |

"Pre Race Blurb", "Pre Race 2P Be A Cop", "Pre Race Stats" and "Pre Race
Letterbox" are rows in `kScreens[]`. The
race draws visible Flailer screens over its view, so the grid draws over
the fly-by on the top screen. The cinema bars are a separate screen,
`0x49c15518`, which the HUD shows in the fly-by and the pre-race
(`playerhud.c`, `HUD_CINEMA_BARS`). The grid's dark backdrop (`0x62229da7`,
y 89 to 391 of 480) covers exactly the part of the view between the bars.

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

## The Blurb and the 2P screen (12m-4)

The Blurb is `PRERACE_BLURB`, hash `0x887b4d37`. It shows the race's
objective, or the cop's controls in Be A Cop. The two-player Be A Cop
screen is `0xb5ecd7a0`, with one box for each player. Each object is 4
bytes: the screen's hash. Their instances are gp-17380 and gp-17372.

**The callbacks** (`0x001e3640`, `0x001e38b8`) work like the grid's:

- ACTIVATE allocates the 4 bytes, tagged "PreRaceBlurb" or
  "PreRace2PBeACop", and constructs the object.
- UNACTIVATE destroys it with flags 3.
- BACK sets the noise and Param to 0 and goes nowhere.
- Every other message goes to `HandleEvent`.

**The constructors:**

- The Blurb's heading (`0x6a77af98`) is set as follows. In an event-tree
  race, it prints "Event %d Objective:" (63001) with
  `TheRaceEvent.nNumber`. For the cop, it gets the LanguageID "You're The
  Cop" (970000). Otherwise it gets "Objective:" (63000).
- Both constructors show NEXT. Only the Blurb's destructor hides it
  again.

**The text** (`0x001e3320`, no symbol) is chosen like this:

| Race | Text |
|---|---|
| not BeACop, or EventTreeRace | `RaceParameters.sObjective` |
| one player, no pad | "Please insert a controller" (900011) |
| one player, a wheel | 970020 for type 22, otherwise 970017 |
| one player, a pad | by player's TransmissionType: 0 gives 970019 (type 0x41) or 970016; 1 and 2 give 970018 (type 0x41) or 970001; anything else gives NULL |
| two players | player 0 gets 970010 (the cop), player 1 gets 970011 (the speeder) |
| anything else | NULL |

The 3DS pad is type 0, so a cop on one player reads 970016 or 970001.

**HandleEvent** (`0x001e34a8`, `0x001e3750`) handles these messages:

- **Up and down** make no sound.
- **RENDER** (19) is handled differently by the two screens:
  - The Blurb asks for the nitro button's character while pad 0 is
    plugged in (`GetJoystickButtonChar(0, 126)`). The character is kept
    at gp-17376, which starts at 0x89 in the image. The Blurb then
    bSPrintfs the text with that character into 512 bytes, and lays the
    result into its box: text `0xaefe36d8`, box `0xcccf9a75`, scale 1.
  - The 2P screen lays player 0's text and player 1's text into their two
    boxes as they are, with no printf.
- **SELECT** (`0x001e3548`, the same on both) does nothing when its Param
  is `JOY_EVENT_START`. Otherwise it zeroes Param and the noise, then
  steps to the next screen if there is one. If the step lands on the
  same screen, it posts RC_SKIP. If not, it changes to the next screen
  without a push and sets the noise to 5. Retail posts to
  `pRaceCoordinator` without checking it.

These are the port's departures:

- A NULL text reaches bSPrintf as its format in retail. The port prints
  "" instead.
- Retail's bSPrintf has no bound. The port's snprintf stops at 512.

**RENDER in the port.** Retail's `RenderFlailerModels` sends RENDER to the
current screen every frame. `main.c`'s `flowRender` now does the same
for the flow's screen, right after `C2D_SceneBegin(top)`. The car and
track selectors are skipped, because their RENDER hooks draw on their
own. All the other callbacks that see RENDER ignore it: the grid, the
letterbox, the pause menu, the gameflow switches and endgame.

**SkipFE.** A race started with SkipFE goes straight to
RCSTATE_RACE_IN_PROGRESS, as retail does. So the Blurb only shows in a
race started from the frontend.

### RenderTextIntoRectangle

The outer (`0x001451e0`) is ported as `flailer_render_text_into_rectangle`
in `flailerwrap.c`. It finds the box bitmap and the text object. The box
runs from the bitmap's X, Y to that point plus its width and height. It
sets the text's string, then hands it to the seam
`gFlailerTextIntoRectangleFn`.

`main.c` binds the seam to `uirender_queue_text_rect`. That function queues
up to four strips a frame, and `uirender_clear_strips` empties the queue
before each RENDER. `draw_visible` draws each strip after the objects of
its text object's layer, as retail's `AddFlailerStrip` appends to
`LayerRenderInfoTable[Z]`.

The layout is the inner's (`0x00144ed0`):

- The pen starts at the text object's top left.
- A button icon is drawn through `RenderHelpCharacter`, and moves the pen
  by its unscaled advance.
- A glyph is kerned against the byte before it in the string, scaled by
  ScaleX. The pen then moves by `(int)(ScaleX * (advance + kerning))`.
- After a space or a tab, the line breaks if the next word would pass the
  box's right edge. The edge is measured from the object's left.
- '@' always breaks the line.
- A line break moves the pen to the left and down by `(int)` of the font
  height.
- A character that broke the line, or has no glyph, is not drawn. The
  spaces after it are skipped.

Each glyph's quad is ScaleX² wide and ScaleY tall, as `RenderCharacter`
draws it. `MaybeClipPoly` (`0x00141808`) drops a quad that lies wholly
outside the box. Otherwise it trims the quad to the box, left, right,
top and bottom in that order, and moves the UVs in step.

On Azahar, a Be A Cop race from the frontend showed the Blurb as follows:

- The heading read "You're The Cop", with the automatic pad's lines
  (970016) wrapped inside the box and NEXT below.
- An A press skipped the fly-by: the coordinator went from state 1 to 2.
- When the fly-by ended without a press, PRERACE closed the screens.

The cop lines show the PS2's glyphs (R3, L2, R2). The 3DS mapping is
L, R, ZL and ZR, a later task.

## The check

`tools/startrace_check.py` runs retail's own module in `retail_model`,
beside the harness `tools/src/startrace_test.c`.

- **Ops:** 7315, giving 24078 transcript lines, 0 differ. Since 12m-4
  they include the Blurb's text over every branch (players, pads,
  wheels, TransmissionTypes, missing strings), both screens' callbacks
  with every message, and SELECT over each manager shape. The model
  stubs the joystick calls and RenderTextIntoRectangle, which prints its
  string with the bytes outside ASCII as `\xNN`.
- **Mutations:** 278, from 274 caught and 4 equivalent:
  - `en-s0`: Enable always adds a screen, so `Screens[0]` is always
    rewritten.
  - `bd-ko`, `bd-pts` and `bk-pts`: the constructor's memset already
    leaves those fields 0.

The mutations include `fred_is_multi_track` in `fredrace.h`.
