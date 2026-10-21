# The three screens the main menu leads to

`NewMainMenu` has three items and every one of them calls `ChangeToScreen`
with a name the port had never registered, so the main menu was a dead end:
"Cops On Mode Select", "Cops Off Mode Select" and "Options". All three are
real screens in `FRONTEND\FRONTB.BUN` with real `MENUITEM_n` objects, and all
three are C++ in the image rather than data on disc -- the same arrangement
`FlailerMenu` has ([flailer-menu.md](flailer-menu.md)) and the boot screens
have ([boot-flow.md](boot-flow.md)).

Everything here was decompiled out of `PS2 Files/NFSHP2.ELF` with
`tools/mipsdis.py`; each rule cites the address it came from. Where a claim
could also be checked against the shipped bundle it has been, and the check
is written down next to the claim -- the two halves disagreeing is the most
useful thing that can happen to a decode.

| class | address | object file |
|-------|---------|-------------|
| `CopsOnModeSelect` | `0x00203d28` | `ModeSelect.obj` |
| `CopsOffModeSelect` | `0x002043d0` | `ModeSelect.obj` |
| `tOptionsScreen` | `0x001e09d0` | `OptionsScreen.obj` |
| `OptionsScreenBase` | `0x001e53d0` | `OptionsScreenBase.obj` |

The port is `3DS Files/source/bscreens.c`, cross-checked against a second
implementation by `tools/bscreens_check.py` (17 scenarios, 1246 lines, 0
differ).

## The short version

```
NewMainMenu  MENUITEM_1  -> mPolice = 1 -> "Cops On Mode Select"
             MENUITEM_2  -> mPolice = 0 -> "Cops Off Mode Select"
             MENUITEM_3  ->              -> "Options"

CopsOnModeSelect                     CopsOffModeSelect
  1 Quick Race         -> race         1 Quick Race         -> race
  2 You're The Cop     -> ChallengeBeACop
  3 Challenge          -> Challenge    2 Challenge          -> Challenge
  4 Ultimate Road Racer-> View Event Tree
                                       3 World Championship -> View Event Tree
  5 (no object)        -> Options      4 (no object)        -> Options

tOptionsScreen
  1 Audio         -> Audio Options       (slides out first)
  2 Controller    -> Joystick PreConfig  (slides out first)
  3 Display       -> Display Options     (slides out first, + snapshot)
  4 Save/Load     -> Phils Load Save     (immediately)
  5 Player Names  -> NameEntry           (slides out first)
  6 Credits       -> Credits             (immediately)
  7 Languages     -> Language Options    (immediately; absent on NTSC)
```

Of those eleven destinations exactly one -- "Options" -- is a screen this port
has. The other ten are the next tranche of work, and until they exist the
flow answers `unregistered <name>` and is left with no current screen, which
is what `ChangeToScreen` does in the original too (`0x00167850`; see
[boot-flow.md](boot-flow.md#changetoscreen-0x00167850)).

## The registry rows

`FlailerScreenConfig` is the only thing that joins the name the C++ passes to
`ChangeToScreen` to the name the screen was authored under, and the two are
different strings on all three rows:

| `ScreenName` | `FlailerHashes[0]` | hash |
|--------------|--------------------|------|
| `Cops On Mode Select` | `COPS_ON_MODE_SELECT` | `0x5b35f533` |
| `Cops Off Mode Select` | `COPS_OFF_MODE_SELECT` | `0x033e7771` |
| `Options` | `OPTIONS` | `0x95ad096b` |

`tools/screen_registry.py` recovers the pairs; `tools/bhash.py` confirms the
right-hand column. Note the third row: the registry name and the authored
name happen to be the same word, which is exactly the coincidence that makes
the other two worth spelling out.

## What is on the three screens in `FRONTB.BUN`

`python tools/flailer_dump.py extracted/FRONTEND/FRONTB.BUN` gives:

| screen | objects | `MENUITEM_n` | `MI_n_MASK` |
|--------|---------|--------------|-------------|
| `0x5b35f533` | 31 | 1..4 | 1..4 |
| `0x033e7771` | 28 | 1..3 | 1..3 |
| `OPTIONS` | 42 | 1..7 | 1..7 |

plus, on every one of the three, the same four objects:

| hash | name | what |
|------|------|------|
| `0x32c91dae` | `MI_UNDERSCORE` | the bracket under the current item |
| `0xc671680c` | `MI_OVERSCORE` | the bracket over it |
| `0x75980cf0` | `SCROLLING_TEXT` | the blurb line |
| `0x5e11b599` | `SCROLL_TEXT_CLIP` | the bitmap the blurb is clipped to |

Those four names are not ELF literals -- they were cracked from the hash --
but they are not guesses either: `SCROLLING_TEXT` carries the authoring
placeholder *"This text will scroll sideways across the screen. The string
has to be really long to make it work."* with `LanguageID` 0, which is what
`tAnimatedBlurb::NewText` replaces, and it names `SCROLL_TEXT_CLIP` as its
`ClipToPoly`.

Both Mode Selects have a `MENUITEM_n` case in their switch that the bundle
never draws -- `MENUITEM_5` on Cops On, `MENUITEM_4` on Cops Off -- and in
both it is the row that goes to "Options". The port keeps the case: it is
what the code says, it costs nothing, and it is the one row of the five whose
destination actually exists.

## `CopsOnModeSelect`

### The constructor (`0x00203d28`)

```
FlailerScreenList::StartMovie("MOVIES\hotpursuit_movie.AVI")   0x00168148
new tSlideInAnimation, two tHighlightAnimations, a tAnimatedBlurb
SelectionSet::AddItems(MI_1_MASK .. MI_5_MASK, IndicatorMode 1)
AddJoyHandler(JOYSTICK_PORT_0, JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION)
sound::jukebox::Start()
gp[-16848] = this                                 <- _16CopsOnModeSelect$pInstance
```

`AddItems` is handed the same five-entry table (`0x00313948`) on both Mode
Selects however many items the screen has; `FlailerGetBoundingBox` on a mask
that is not there simply fails, so the extra entries cost nothing.

The movie is not on the disc. Neither is Cops Off's, and neither is the
Options screen's -- `MOVIES\` has no `hotpursuit_movie.AVI`,
`worldracing_ movie.AVI` or `options_movie_new.AVI` in it. All three screens
therefore ask for a file that is not there and carry on, the same way the
title screen's second movie does. (The space in `worldracing_ movie.AVI` is
not a typo in this document; it is the string in the image.)

### `OnHighlight` (`0x00204218`) and `SetupHighlight` (`0x00204160`)

```
tHighlightAnimation::SetCurrentMenuItem(data->ItemHash)   <- the raw hash
n = ItemHash + 0xad1fc60d;  if ((unsigned)n >= 5) return
SetupHighlight(MI_n_MASK, blurb[n])
    FlailerGetBoundingBox(screen, mask, &box)
    FlailerSetTopLeftY(screen, MI_UNDERSCORE, box.bottom + UnderscoreOffset)
    FlailerSetTopLeftY(screen, MI_OVERSCORE,  box.top    - OverscoreOffset)
    tAnimatedBlurb::NewText(blurb)
    SelectionSet::SetCurrentItem(mask)
```

`0xad1fc60d` is `-bStringHash("MENUITEM_1")`, so the add-and-unsigned-compare
is a range check with the subtraction folded in. A hash that is not one of
the consecutive `MENUITEM_n` values falls off the end and the message is
dropped -- sound and all.

`UnderscoreOffset` (`0x00324a1c`) is `-3.0f` and `OverscoreOffset`
(`0x00324a18`) is `+6.0f`, and the overscore's is *subtracted*, so the port
carries `-3.0f` and `-6.0f` as two deltas added to the box. Three pixels is
not much to build an abstraction over, but `OptionsScreenBase` uses a
different pair (below), so averaging them would have been wrong.

Only Y moves. Both brackets keep the X they were authored at, which is why
they run the full width of the panel however short the label is.

### `HandleEvent` (`0x00203f50`)

```
if (msg == SCREEN_TICK) OnTick()
if (pExitAnimation) { pExitAnimation->HandleMessages(msg, data); return; }
if (msg == MENUITEM_HIGHLIGHT) { OnHighlight(msg, data); return; }
if (msg < MENUITEM_UNHIGHLIGHT) {
    if (msg == MENUITEM_SELECT) OnSelect(msg, data);
    return;
}
if (msg == SCREEN_TICK) OnTick()                 <- again
```

The second `SCREEN_TICK` test is real: `CopsOnModeSelect` runs `OnTick`
**twice** for one tick and `CopsOffModeSelect`, which is otherwise the same
file twice, runs it once. `OnTick` (`0x00204120`) is four animation calls
and nothing outside the animation kit can tell, so it changes nothing -- but
it is a genuine difference between two near-identical screens, and a port
that quietly normalises it has lost information. `bscreens.c` keeps a counter
purely so the cross-check can hold the difference still.

### The `MENUITEM_SELECT` switch

| item | label | blurb | what it writes | goes to |
|------|-------|-------|----------------|---------|
| 1 | Quick Race | 10017 | -- | `StartQuickRace` (port 0 only) |
| 2 | You're The Cop | 10014 | `BeACop = 1` | `ChallengeBeACop` |
| 3 | Challenge | 10012 | `Boost = 1`, `BeACop = 0` | `Challenge` |
| 4 | Ultimate Road Racer | 10013 | `GameType = 9`, `NumPlayerCars = 1`, `SetTreeType(..., 1)` | `View Event Tree` (port 0 only) |
| 5 | *(no object)* | 10009 | -- | `Options` |

"port 0 only" is `data->Port != 0 -> data->Noise = 0; return`: on a second
pad the item does nothing and eats the click, because split screen reaches
those two through its own path.

`BeACop` is `Fred.MainMenuOpts.BeACop` (`0x002f3fd8`), `Boost` is
`TheRaceParameters.Boost` (`0x00312804`), `GameType` is `Fred.GameType`
(`0x00304580`) and `NumPlayerCars` is `Fred.NumPlayerCars` (`0x00304588`).
`Fred` itself is `0x002f3fc0`, 70592 bytes; `TheRaceParameters` is
`0x00312520`, 768 bytes, so `Boost` is at `+740` -- which is what the
`.mdebug` type info says `RaceParameters::Boost`'s offset is, and that
agreeing is the check.

The blurb IDs resolve, in `LANGUAGES\FE_ENGLISH.BIN`, to:

| id | text |
|----|------|
| 10017 | Go straight into the action! |
| 10014 | Fill your ticket quota for big points! |
| 10012 | One-player and two-player challenges. |
| 10013 | Beat the heat in 30 events. |
| 10009 | Customize your settings. |

which is the second, independent confirmation that the switch was read in the
right order: nothing in the disassembly says 10014 belongs to the cop item,
and the sentence does.

### `StartChangeToScreen` (`0x00203ec8`)

Selecting anything but Quick Race does **not** change screen. It builds a
`tExitScreenAnimation` (below) and adds one more slide group for the two
brackets; the change happens when the animation finishes, ~0.25s later.

### `JoyHandler` (`0x00205040`)

The one button either Mode Select listens for itself is
`JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION` (23), on port 0 only, and all it
does is store whether the button is down. `StartQuickRace` reads that at the
moment it runs and hands it to `cPlayerSettings::TransmissionType`, so
holding it while picking Quick Race is how a player asks for the other
gearbox. (An earlier read of this file called the argument a two-player flag.
It is not: it lands in `Fred.PlayerInfo[0].mPlayerSettings`, byte 3.)

The button is L1 (scanner row 24), as the Mode Selects' help line 802231
says: "L1 + Cross Manual Transmission in Quick Race". On the 3DS it is L,
held, in `main.c`'s `flowInput`. The port held X until Square moved there
(TASKS 48, when Help took Y).

## `CopsOffModeSelect`

The same file again, with four differences and nothing else:

* three authored items instead of four, and the switch has four cases;
* `OnTick` runs once per tick, not twice;
* the movie is `MOVIES\worldracing_ movie.AVI`;
* the exit animation is 0.20s, because the screen defines one fewer group.

| item | label | blurb | what it writes | goes to |
|------|-------|-------|----------------|---------|
| 1 | Quick Race | 10006 | -- | `StartQuickRace` (port 0 only) |
| 2 | Challenge | 10007 | `Boost = 1`, `BeACop = 0` | `Challenge` |
| 3 | World Championship | 10008 | `GameType = 8`, `NumPlayerCars = 1`, `SetTreeType(..., 0)` | `View Event Tree` (port 0 only) |
| 4 | *(no object)* | 10009 | -- | `Options` |

`GameType` 8 is `FRED_ULTIMATE_GAME` and 9 is `FRED_HOTPURSUIT_GAME`; 2 is
`FRED_EXPRESS_GAME`, which is what Quick Race sets. The tree type argument is
the other half of the same choice -- the cops-on screen asks for the pursuit
tree and the cops-off screen for the road-racing one.

## `tOptionsScreen` on `OptionsScreenBase`

This one is split across two classes and the base sees every message first.

### `OptionsScreenBase` (`0x001e53d0`)

```
new tSlideInAnimation, two tHighlightAnimations, a tAnimatedBlurb
SelectionSet::AddItems(MI_1_MASK .. MI_8_MASK)          <- eight; seven exist
FlailerScreenList::StartMovie("MOVIES\options_movie_new.AVI")
gp[-17632] = this                          <- _17OptionsScreenBase$pInstance
```

No jukebox call and no joy handler, unlike the Mode Selects.

### `tOptionsScreen` (`0x001e09d0`)

One rule, and it is the only thing in these three screens that depends on the
console:

```
if (GetVideoMode() == MODE_NTSC)
    GrayMenuItem(OPTIONS, MENUITEM_7, 2)
```

`GetVideoMode` is `0x001992a0` and `MODE_NTSC` is 1. Mode 2 of `GrayMenuItem`
(`0x00168498`) clears `ENABLED` *and* makes the object invisible; mode 0
would have left the item on screen in the grayed colour, and mode 1 is the
one that turns it back on. On an NTSC console there is no language to pick,
so the item is gone rather than dimmed.

### `FirstCrackAtMessage` (`0x001e56c0`)

```
if (msg == MENUITEM_HIGHLIGHT) HandleHighlight(msg, data, 0)
else if (msg == SCREEN_TICK)   animate the slide-in and both highlights
if (pExitAnimation) { pExitAnimation->HandleMessages(msg, data); return; }
vtable+0x60 -> tOptionsScreen::HandleEvent(msg, data)
```

`HandleHighlight` (`0x001e55a0`) takes an override mask as its third
argument, which the other Options pages use and this one passes 0 for. With 0
it does the `MENUITEM_n` range check itself, and -- this is the part worth
writing down -- an out-of-range hash leaves the mask at **0** and the rest of
the function runs anyway: `SetCurrentItem(0)`, and a bounding box fetched for
an object that does not exist. The port reproduces that rather than adding an
early return, because a screen that silently swallows a bad highlight and one
that clears its own selection behave differently the moment something else
reads `CurrentObject`.

`HandleHighlight` also uses a different pair of bracket offsets: the int
overload of `FlailerSetTopLeftY`, no underscore offset at all, and the same
`-6.0f` over the top.

### `tOptionsScreen::HandleEvent` (`0x001e0ac0`)

| item | label | blurb | goes to | how |
|------|-------|-------|---------|-----|
| 1 | Audio | 100020 | `Audio Options` | slides out first |
| 2 | Controller | 100021 | `Joystick PreConfig` | slides out first |
| 3 | Display | 100022 | `Display Options` | slides out first, after `tDisplayOptionsChangeManager::Start` (`0x001ee6c0`) |
| 4 | Save/Load | 100023 | `Phils Load Save` | immediately |
| 5 | Player Names | 100024 | `NameEntry` | slides out first |
| 6 | Credits | 100025 | `Credits` | immediately |
| 7 | Languages | 100026 | `Language Options` | immediately |

The mix is not a pattern; it is what each destination happened to need. The
one to be careful with is 5, which looks like it belongs with 4 and 6 and
does not.

An item hash that is not a `MENUITEM_n` at all does not fall through to
nothing: the SELECT arm's out-of-range default builds an exit animation to an
**empty string**, which 0.40s later reaches `ChangeToScreen("", 1)` -- and
that pushes the Options screen, unactivates it, and resolves to no screen at
all. The port does the same; `options_unknown` in the cross-check is that
path.

The blurb IDs again resolve into sentences that match their items:

| id | text |
|----|------|
| 100020 | Set the volume and the Jukebox. |
| 100021 | Set up your controllers. |
| 100022 | Set what you want to see. |
| 100023 | Save and load your settings. |
| 100024 | Set your player names. |
| 100025 | See who made this game. |
| 100026 | Select a different language. |

An earlier read of the SELECT and HIGHLIGHT jump tables (`0x0029cbf0` and
`0x0029cc10`) had entries 5 and 6 swapped -- MENUITEM_6 going to Language
Options and MENUITEM_7 to Credits. Reading the tables again shows they are
not: 6 is Credits with blurb 100025 and 7 is Language Options with 100026,
consistently in both tables, and "See who made this game." settles it.

## `tExitScreenAnimation` (`0x00232b50`)

The real thing is a `tSlideOutAnimation`: a list of `AnimationGroup`s, one
per `MENUITEM_i_GROUP` the screen defines, each sliding its objects to
`x = 650` along a cubic spline. Everything outside the animation kit can see
only two things about it -- how long it takes, and that the screen stops
responding while it runs -- so the port models it as a stopwatch.

`HandleMessages` (`0x00232b90`):

```
data->Noise = 0                              <- unconditional; see below
if (msg == SCREEN_BACK_BUTTON) { data->Param = 0; return; }
if (msg == MENUITEM_PAD_UP || msg == MENUITEM_PAD_DOWN) {
    data->Param = 1; return;                 <- consumed
}
if (msg != SCREEN_TICK) return;
if (!IsFinished()) return;
ChangeToScreen(this->name, 1)                <- the free function, 0x0014a438
```

The store that clears `Noise` sits in the *delay slot* of the branch that
tests for `SCREEN_BACK_BUTTON`, and the branch is an ordinary one, so the
store runs whatever the message is: a screen on its way out makes no sound at
all. Clearing `Param` on BACK is how the animation vetoes it; setting `Param`
on the pad is how it freezes the highlight while the items are leaving.

### Where 0.25s, 0.20s and 0.40s come from

`tSlideAnimation`'s duration (`+16`) is the longest of the groups added, and
group *i* runs for `SplineBaseDuration + i * SplineDeltaDuration` seconds.
Both globals are `0.05f` -- `0x00324db4` and `0x00324db8`, which is
`gp[-15932]` and `gp[-15928]` against `_gp = 0x00328bf0`.

Which groups exist is a question about the bundle, and the bundle answers it.
Counting `GroupHash == bStringHash("MENUITEM_i_GROUP")` over each screen's
objects:

| screen | groups | longest | duration |
|--------|--------|---------|----------|
| `0x5b35f533` (Cops On) | 1..4 | 4 | 0.25s |
| `0x033e7771` (Cops Off) | 1..3 | 3 | 0.20s |
| `OPTIONS` | 1..7 | 7 | 0.40s |

(`NEW_MAIN_MENU` defines groups 1..3 as well, but `NewMainMenu` never builds
a `tExitScreenAnimation` -- it changes screen on the spot -- so its groups
only ever run as the slide-*in*.)

`0.05 + 4 * 0.05 = 0.25`. This is the one number in this document that comes
from the data rather than the code. It was originally the reason the port's
exit animation was a plain stopwatch: with no slide to time, the duration had
to be measured here and written down. Now that `banim.c` builds the real
`tSlideOutAnimation`, the table above is what the port *derives* rather than
what it is told, and the three durations come back out of the harness
unchanged.

`IsFinished` (`0x00232828`) answers "no" while the stored start time is 0 or
`0x7fffffff`. `Start` (`0x00232818`) stores `RealTimer`, which counts in
1/4000 s because `Timer::SetTime(float)` (retail `0x00136dd0`) is
`(int)(f * 4000.0f + 0.5f)`. At 60fps `RealTimer` gains 67 a frame (the demo's
truncating SetTime gave 66), so 0.25s is 1000 ticks and the change lands on
the 15th frame after the select.

## `StartQuickRace` (`0x00203ae0`)

This is the demo's. Retail's (`0x00216c18`) also sets the defaults first,
puts the player at the back of the grid, gives a car and starts the race;
[quick-race](quick-race.md) has it, and it is what the port runs.

Twenty-five stores into `TheRaceParameters`, plus three fields outside it.
Every one maps to a named field of `RaceParameters` in the `.mdebug` type
info -- which it did not, until `tools/mdebug_stabs_scan.py` stopped dropping
array members and `PlayerStartPosition` and `sObjective` reappeared.

| offset | field | value |
|--------|-------|-------|
| +0 | `TrackNumber` | `PickTrackNumberForExpressGame()` (`0x00203530`) |
| +16 | `TrafficDensity` | `0.33` |
| +20 | `TrafficOncoming` | `0.5` |
| +32 | `RaceType` | 1 |
| +40 | `Point2Point` | `GetTrackInfo(track)[67]` |
| +44 | `NumLapsInRace` | 2 |
| +48 | `NumPlayerCars` | 1 |
| +52 | `NumAICars` | cops ? 3 : 7 |
| +60 | `PlayerStartPosition[0]` | cops ? 2 : 8 |
| +76 | `TrainingLinesEnabled` | 0 |
| +80 | `HasObjective` | 0 |
| +84 | `sObjective[0]` | 0 (i.e. cleared) |
| +600 | `EventTreeRace` | 0 |
| +604 | `MaxCops` | cops ? 4 : 0 |
| +608 | `Tickets` | cops |
| +612 | `RoadBlocks` | cops |
| +616 | `SpikeStrips` | cops |
| +620 | `Helicopter` | cops |
| +632 | `TicketsBeforeArrest` | cops ? 2 : 0 |
| +636 | `NumBeACopRoadBlocks` | 0 |
| +640 | `NumBeACopChoppers` | 0 |
| +644 | `CopStrength` | 1 |
| +736 | `OpponentStrength` | 1 |
| +740 | `Boost` | 1 |
| +744 | `BoostScale[0..1]` | 1.0, 1.0 |

and outside the block: `Fred.GameType = FRED_EXPRESS_GAME`,
`Fred.NumPlayerCars = 1`, and
`Fred.PlayerInfo[0].mPlayerSettings.TransmissionType` from the joy handler.

`cops` is `Fred.MainMenuOpts.mPolice` (`0x002f3fdc`) -- the same flag
`NewMainMenu` set to pick which Mode Select the player is standing on, so a
Quick Race started from the cops-on screen gets three AI cars, four cops and
grid slot 2, and one started from the cops-off screen gets seven cars, no
cops and grid slot 8.

The track number and `Point2Point` come out of the track database.

## What the port does with this

`3DS Files/source/bscreens.c` is the three screens, free of `<3ds.h>` like
`bui.c`, `bmenu.c` and `gameflow.c` before it. Everything that touches a
screen, a movie, the menu or the race goes out through `BScreensHooks`, and
`3DS Files/source/main.c` implements the eight of them:

| hook | what main.c does |
|------|------------------|
| `grayMenuItem` | `bmenu_set_item_enabled` + `bui_set_object_visible` |
| `setBlurb` | `bui_set_text_language` on `SCROLLING_TEXT` |
| `moveBrackets` | `uirender_object_bounds` on the mask, then `bui_set_object_pos` on both brackets |
| `startMovie` / `stopMovie` | logged; no panel movie is on the disc |
| `jukebox` | logged |
| `displayOptionsStart` | logged |
| `startQuickRace` | retail's `StartQuickRace` (`quickrace.c`), then the race logged |

Two small additions were needed underneath: `bui_set_text_language`, because
`tAnimatedBlurb::NewText` changes which row of the language table a text
object reads (the renderer looks it up every frame, so there is nothing else
to change), and `uirender_object_bounds`, because `FlailerGetBoundingBox`
needs the rendered size of a bitmap and only the renderer knows the texture's
dimensions.

The animation layer added five more underneath that: `bui_get_object_alpha`
/ `bui_set_object_alpha`, `bui_set_object_scale`, `bui_set_text_string`,
`bui_next_in_group` and `uirender_text_extent`. They are listed with their
originals in [frontend-animation.md](frontend-animation.md).

`main.c`'s `menuCallback` also changed. It used to build a fresh
`ScreenCallbackData` and forward `MENUITEM_SELECT` alone; it now passes the
block `FlailerMenu` is holding straight down. Both reply fields matter here:
`Param` is how the exit animation freezes navigation, `Noise` is how it stays
quiet, and `bmenu` reads `Noise` back after the callback returns.

## The animation layer

`tSlideAnimation`, `tSlideInAnimation`, `tSlideOutAnimation`,
`tHighlightAnimation`, `tAnimatedBlurb`, `SelectionSet`, `AnimationGroup` and
`SplineSeek` are a self-contained kit that moves Flailer objects along cubic
splines. It was left out of the first pass on these screens and is now ported
in `3DS Files/source/banim.c`; the decode is written up in
[frontend-animation.md](frontend-animation.md).

One consequence reaches back into this document. The exit timings used to be
three hand-measured constants -- 0.25 s for Cops On, 0.20 s for Cops Off,
0.40 s for Options -- standing in for an animation that was not there. They
are gone. `tSlideOutAnimation` gives slot i a duration of `0.05 + i*0.05`
seconds, so the total is `0.05 * numGroups`, and asking the bundle which
`MENUITEM_n_GROUP`s each screen has produces exactly 0.250, 0.200 and 0.400
back. The numbers were right; they are now derived rather than asserted.

Two of the three unnamed object hashes are also cracked, along with the
group hash the brackets live in:

| hash | name |
|------|------|
| `0x70a404ec` | `WHITEOUT_BAR` -- the dark bar behind the blurb |
| `0x6eb9985d` | `NONAME` -- what the editor writes for an unnamed object, which is why it is on nearly every screen |
| `0x97bf4b25` | `UNDERSCORE_GROUP` -- `MI_UNDERSCORE` and `MI_OVERSCORE` |

`0xab671c9a` (a caption placed off-screen on Cops On, at y=539 of a 480-tall
screen) and `0x1042eac3` are still unnamed. Neither resisted for want of
trying: a 4,185-word list and an exhaustive sweep of every name up to four
characters both came back empty.

## Every name the frontend can reach

`ChangeToScreen` (`0x00167850`) clears `pCurrent` *before* it looks the name
up, so a name with no registry row does not leave the player where they
were: it leaves the list with no current screen at all. On the port that is
a black top screen and one line of trace, `flow unregistered <name>`, and
the only way out is BACK. A name that is merely unported is therefore much
worse than a screen that does nothing, and the fix is not to port the class
-- it is to register the name.

Ten names the port's own C can pass to `bgf_change_to_screen` had no row.
They are registered now, to `bgf_plain_screen_callback`, which is an empty
function: the screen draws, `bmenu` moves the highlight, BACK works, and A
does nothing. Every one of their chunks is already in `FRONTB.BUN`, so
nothing new is loaded.

| name | hash | the ELF's class | reached from |
|------|------|-----------------|--------------|
| `Challenge` | `0x2d62cfe2` | `ChallengeScreenCallback` | both Mode Selects, `bscreens.c:337`, `:348` |
| `ChallengeBeACop` | `0xe55f1297` | `BeACopChallengeSetup` | Cops On Mode Select, `bscreens.c:336` |
| `View Event Tree` | `0x147f8a59` | `tEventTreeView` | both Mode Selects, `bscreens.c:339`, `:350` |
| `Audio Options` | `0xe116761c` | `AudioOptionsScreen` | Options, `bscreens.c:555` |
| `Joystick PreConfig` | `0x8bd5060b` | `JoystickPreConfig` | Options, `bscreens.c:556` |
| `Display Options` | `0x8bc68340` | `tDisplayOptionsScreen` | Options, `bscreens.c:557` |
| `Phils Load Save` | `0x9829bfab` | `LoadSaveWrapper` | Options, `bscreens.c:558` |
| `NameEntry` | `0x617a4e0a` | `NameEntry` | Options, `bscreens.c:559` |
| `Credits` | `0xfd8a3b6d` | `CreditsScreen` | Options, `bscreens.c:560` |
| `Language Options` | `0x632b068e` | `LanguageOptionsScreenBase` | Options, `bscreens.c:561` |

Two of those rows share a screen with a row that was already registered, and
both pairs are in the ELF, not invented here: `Language Options` is the same
chunk and the same class as `Language Options Pre FE`, entered under a
second name once the frontend is up, and `NameEntry` draws the same chunk as
`Username Options`.

`python tools/screen_registry.py --check-port` is the standing check. It
reads `FlailerScreenConfigList` out of the ELF and `kScreens[]` out of
`main.c`, and prints two lists: every port row whose hash disagrees with the
ELF, and every screen name that appears as a string literal anywhere in the
port's sources and has no row. The second list is the one that matters --
the Mode Selects' item tables and the Options pages spell their
destinations out, so a literal that names a registered screen is a name the
player can arrive at. Both lists are empty as of this work, against 62
configs of which 18 are registered.

A registered-but-unported screen says so. `main.c` draws
`kPlainScreenNote` on the bottom panel whenever the current screen's
callback is `bgf_plain_screen_callback`, because the panel takes its line
from `SCROLLING_TEXT` and these screens have no blurb, so it would otherwise
sit empty under the screen's name and read as a bug.
