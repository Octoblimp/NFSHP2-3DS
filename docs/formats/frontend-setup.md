# The race setup screens

Between a Mode Select and car select sits a setup screen: the few settings
the chosen mode takes before the cars. Two are ported. The first is
"You're The Cop", the screen Cops On Mode Select's second item opens
([frontend-screens.md](frontend-screens.md#the-short-version)). The second
is its Setup item's "Be The Cop Setup", the first of the
`RaceSetupBaseClass` screens ([below](#be-the-cop-setup)). With them come
the small classes every setup screen shares.

Everything here is from the retail image, SLES_507.31, disassembled with
`tools/retaildis.py`; each rule cites its address. The port is
`3DS Files/source/bsetup.c`. `tools/setup_check.py` runs You're The Cop
next to retail's own code in `mipsemu` (359 ops, 2293 lines, 0 differ; see
[the check](#the-check)), and `tools/racesetup_check.py` runs Be The Cop
Setup (398 ops, 3420 lines, 0 differ).

| class | address | what it is |
|-------|---------|------------|
| `BeACopChallengeSetup` | `0x001b6c68` .. `0x001b7748` | You're The Cop |
| `RaceSetupBaseClass` | `0x001b7748` .. `0x001b9248` | every race setup screen's rows |
| `BeTheCopSetup` | `0x001b9248` .. `0x001b93e0` | Be The Cop Setup's three rows |
| `tScrollingMenuList` | `0x00249c78` .. `0x0024a888` | a list that slides its items into view |
| `tfeSineWave` | `0x0024a5c0` .. `0x0024a68c` | a value swinging between two bounds |
| (the arrows) | `0x0024a690` .. `0x0024a880` | the two bitmaps either side of a value |

The arrows class has no name in the image. The demo had no such class: each
of its screens drew its two arrows itself. The port calls it `BArrows`.

## The short version

```
ChallengeBeACop (0xe55f1297)
  1 Players      One Player / Two Players   left/right: 1 <-> 2, only with two pads
  2 Skill Level  Beginner / Advanced / Expert   left/right: 0..2, wrapping
  3 Setup
SELECT on 1 or 2  -> "Select Car" (one player) or "Select Car2P" (two)
SELECT on 3       -> "Be The Cop Setup"
```

Two players gray Skill Level and hide its value, since the opponent is the
other player. On a 3DS there is never a second pad, so the count stays at 1
and Players never shows its arrows.

The strings, from `FE_ENGLISH.BIN`:

| id | text | used for |
|----|------|----------|
| 20003, 20004 | One Player, Two Players | the Players value |
| 30015 .. 30017 | Beginner, Advanced, Expert | the Skill Level value (table `0x00313d98`) |
| 19000, 19001 | Solo play, full-screen. / Head-to-head play, split-screen. | Players' blurb |
| 19002 .. 19004 | Fast / Faster / Fastest opponents | Skill Level's blurb, by level |
| 19005 | Customize the current Race Type. | Setup's blurb |
| 805000 .. 805003 | Select / Adjust mode setting, Advance to Car Select, Back to Hot Pursuit Menu | the help lines (`0x0031a490`) |

## Fred's fields

The screen works on a copy of `DataChallengeScreen`, the 20 bytes at Fred+8
(Fred is `0x002fc050`, and the memory card saves it whole).

| offset | field | |
|--------|-------|---|
| +0 | `mNumPlayers` | 1 or 2 |
| +4 | `mChallengeMode` | |
| +8 | `mRaceMode` | copied to `TheRaceParameters.NFSRaceMode` on SELECT |
| +12 | `mSkillLevel` | the Challenge screen's |
| +16 | You're The Cop's skill, 0..2 | retail only |

The demo's structure is 16 bytes. Retail added the fifth word, and You're
The Cop's skill level moved into it. `InitWithDefaults` (`0x001b5e10`) sets
1, 3, 1, 1, 0.

Two more of Fred's words are written: `GameType` at +0x1072c
(`CHALLENGE_GAME_BE_A_COP` is 7) and `NumPlayerCars` at +0x10734.
`MainMenuOpts.mPolice`, at +32, picks the movie.

`TheRaceParameters` is `0x0031a898`. SELECT writes `NumPlayerCars` (+48) and
`NFSRaceMode` (+596). `InitWithDefaults` (`0x001ed5c8`) starts both at 1.

## `Callback` (`0x001b6f18`)

- **SCREEN_ACTIVATE**: `bMalloc(720)`, then the constructor on the screen
  the callback data names, kept at gp-18784.
- **SCREEN_UNACTIVATE**: if there is an instance, its destructor (with
  delete), then the pointer is cleared.
- **Anything else**: `HandleEvent`. Retail doesn't check the instance here.

`bMalloc` doesn't clear, so `CurrentMenuItem` (+28) is whatever the heap
held until the first HIGHLIGHT. Both that and the port's 0 act as "not
Players", and the menu highlights an item as soon as the screen opens.

## The constructor (`0x001b6c68`)

In order:

1. The screen hash, then the `SelectionSet`.
2. The blurb: `tAnimatedBlurb(SCROLLING_TEXT, SCROLLING_TEXT, WHITEOUT_BAR)`.
3. The slide-in, from `FlailerGetTopLeftX(MI_1_MASK)`.
4. Two `tHighlightAnimation`s:
   - the item's, `0xab671c9a`, in the bloom colour (gp-16136, 0x80);
   - the value's, `0x1042eac3`, in its own colour (gp-18792, -1).
5. The arrows, `LEFT_ARROW` `0xd1cda594` and `RIGHT_ARROW` `0x9345e4a7`.
6. The copy of `DataChallengeScreen`. Then `GameType` = 7, and
   `NumPlayerCars` = the copy's count.
7. `MakeChallengeCarsAvailable(Fred)` (`0x00183af8`), then `0x00183ec0(Fred)`.
   The second is retail's own: a jump to `0x00194898`, which builds a
   `VisibleCarSet`, takes the first car's `RideInfo`, and starts the car
   loader on it, so car select's car is on its way before the player gets
   there.
8. The `SelectionSet`'s indicator mode (+144) = 1, then its items:
   MI_1..3_MASK.
9. `MakeJoystickArrowsRight`, `ResyncChangeables`, `StartTheRightMovie`.
10. The exit pointer cleared, then `SetHelpOverride(0x0031a490)`.

## The destructor (`0x001b6e30`)

1. The exit animation's destructor (`0x001b9ad0`), if one is running.
2. Fred's `NumPlayerCars` = the count, `GameType` = 7, and the copy goes
   back to Fred+8. So BACK saves the settings too, not just SELECT.
3. `SetHelpOverride(0)`.
4. The members in reverse: the two blooms, the slide-in (`0x001b9ae0`), the
   blurb (`0x00249280`), the `SelectionSet` (`0x0016e168`).

## `HandleEvent` (`0x001b7438`)

- SCREEN_TICK runs `OnTick` first, whether or not an exit is running.
- While an exit runs, every message goes to its `HandleMessages`
  (`0x00249128`), as a tail call, and nothing else sees it.
- Otherwise:
  - HIGHLIGHT goes to `OnHighlight`;
  - PAD_LEFT and PAD_RIGHT go to `OnScroll`;
  - SELECT is handled inline (`0x001b74f8`);
  - anything else is ignored.

### `OnTick` (`0x001b6fb0`)

1. The arrows' `HandleEvent`, then `Animate` on the slide-in, both blooms and
   the blurb.
2. On Players:
   - with both pads in, the arrows follow the Players value and that's all;
   - otherwise the arrows go, the count goes to 1 through
     `MaybeChangeNumPlayers`, and a change resyncs and rewrites the line.
3. On any other item, without both pads the count goes to 1 and the screen
   resyncs **every tick**, whether anything changed or not.

### `OnHighlight` (`0x001b7188`)

The brackets go to the item's own bounding box, not its mask's as on the
Mode Selects:

- `MI_UNDERSCORE` to the bottom plus -3.0 (gp-16112);
- `MI_OVERSCORE` to the top minus 6.0 (gp-16116).

Each sum is done in float and cut to an int by `FlailerSetTopLeftY(int, int,
float)` (`0x001b9ae8`, `cvt.w.s`). Then:

1. The item's blurb line.
2. The item bloom goes to the item, and the item becomes current.
3. By item:

| item | arrows follow | also | mask | value bloom |
|------|---------------|------|------|-------------|
| Players | the Players value | `MakeJoystickArrowsRight` | MI_1 | the Players value |
| Skill Level | the Skill value | | MI_2 | the Skill value |
| Setup | nothing | | MI_3 | nothing |

### `OnScroll` (`0x001b7330`)

Left is -1 and right +1.

- Players goes through `MaybeChangeNumPlayers(count + d)`.
- Skill Level goes through `MaybeChangeOpponentSkillLevel`.

A change:
1. sets the reply's noise to the menu's left or right sound;
2. blooms the value;
3. resyncs;
4. rewrites the line, with the *scrolled* item's line, which need not be the
   current one.

No change sets the noise to 0, so it's silent.

### SELECT (`0x001b74f8`)

Refused unless the pads allow it: with one player, only port 0 can select;
with two, either port can. Then:

1. The copy goes back to Fred+8. Fred gets `NumPlayerCars` and `GameType` 7.
   `TheRaceParameters` gets `NumPlayerCars` and `NFSRaceMode` (the copy's
   `mRaceMode`).
2. The target:
   - Players or Skill Level (an unsigned range test on the two hashes):
     "Select Car2P" with two players, else "Select Car". Before it,
     `MakeChallengeCarsAvailable` and `SetupRaceParametersAfterRaceSetup`
     (`0x001862b0`, ported in `fredrace.c`; `race-start.md`).
   - Setup: "Be The Cop Setup".
   - Anything else: "", so the screen goes nowhere.
3. `bMalloc(28)`, then `tExitScreenAnimation(screen, target, 1)`.
4. `AddGroup(UNDERSCORE_GROUP, MI_UNDERSCORE, its X, 650, the exit's
   TotalTime)`, so the brackets leave with the items.

### `ResyncChangeables` (`0x001b7680`)

| count | Players value | Skill Level | Skill value |
|-------|---------------|-------------|-------------|
| 1 | 20003 | `GrayMenuItem` 1 (enable) | shown |
| 2 | 20004 | `GrayMenuItem` 0 (gray) | hidden |
| other | untouched | untouched | untouched |

Then, always, `RefreshOpponentSkillLevel` (`0x001b5dc0`), which sets the
Skill value's `LanguageID` from the table at `0x00313d98` by the skill,
unchecked.

## The helpers

- `ValueChanger` (`0x001b5c78`): `v = cur + d`; past `hi` it becomes `lo`,
  below `lo` it becomes `hi`.
- `MaybeChangeNumPlayers` (`0x001b5c90`):
  - 0 or less becomes 2, and 3 or more becomes 1;
  - then 1 if the second pad is out;
  - returns whether the count changed.
- `MaybeChangeOpponentSkillLevel` (`0x001b5d70`): `ValueChanger(skill, d, 0,
  2)`, and whether it changed. With d = ±1 it always does.
- `MakeJoystickArrowsRight` (`0x001b5d00`): unless both pads are in, the
  arrows follow nothing and the count goes to 1. Its result is discarded.
- `StartTheRightMovie` (`0x001b5de0`), by `mPolice`:
  - `MOVIES\hotpursuit_movie.AVI` when set;
  - `MOVIES\worldracing_ movie.AVI` otherwise. The space in the name is on
    the disc.

## `tfeSineWave` (`0x0024a5c0`)

16 bytes: `lo`, `hi`, `rate`, `phase`. The constructor stores the three and
clears the phase.

- `Step(dt)` (`0x0024a5d8`): `phase += rate * dt`, stored, then if `6.283 <
  phase` (gp-26468) 6.283 comes off, **once**. A step of more than a whole
  turn leaves the phase past the wrap, and a phase of exactly 6.283 stays.
- `GetValFloat` (`0x0024a610`), in this order:
  1. `(bSin(phase) + 1) * 0.5`;
  2. `(hi - lo)` times that;
  3. `lo` plus it.
- `GetValInt` (`0x0024a668`): that, cut to an int by `cvt.w.s`.

## The arrows (`0x0024a690`)

32 bytes:

| offset | field |
|--------|-------|
| +0 | the screen |
| +4, +8 | the two bitmaps' chunks |
| +12 | the object followed |
| +16 | a `tfeSineWave(0, 128, 10)` |

The pulse runs alpha 0 to 128 about 1.6 times a second.

- **The constructor** finds both bitmaps once (`FindFlailerObject(screen,
  name, 2)`, bitmaps only), then does `Set(0)`.
- **`Set` (`0x0024a860`)** stores the object, then `UpdateVisibility`.
- **`UpdateVisibility` (`0x0024a800`)** makes each bitmap found visible
  while the pair follows something and hidden otherwise.
- **`HandleEvent` (`0x0024a868`)** runs `Tick` on SCREEN_TICK. Nothing
  else reaches it: its one caller is `OnTick`.
- **`Tick` (`0x0024a730`)**:
  1. Step the pulse by `RealTimeElapsed`.
  2. If following something: `FlailerGetCenterY` of that object, once.
  3. For each bitmap: `SetAlpha(GetValInt(), -1)` (all four corners), then
     `SetCenterY((float)y)`.
  4. `UpdateVisibility` again.

`SetCenterY` (`0x00140930`) puts the top at `y - GetHeightFloat() * 0.5`
and keeps X.

## The Flailer calls this needed

| call | address | what it answers |
|------|---------|-----------------|
| `FlailerGetBoundingBox` | `0x00144280` | left, top = the top left cut to ints (`0x001440d8`); right = left + `GetWidth`, bottom = top + `GetHeight` |
| `FlailerGetCenter`/`CenterY` | `0x001447e0`/`0x00144860` | top + (bottom - top) / 2, rounded toward 0 |
| `GetHeight` | `0x001405e0` | `GetHeightFloat`, cut to an int |
| `GetHeightFloat` | `0x00140688` | text: `GetScaledHeight` (`0x00140cd8`), ScaleY * (float)(int) the font's height; bitmap: `CalculateHeightFloat` (`0x00141488`), texture height * ScaleY; else 0 |
| `FlailerSetTopLeftY` (int) | `0x00144458` | `SetTopLeftY((float)y)` |
| `FlailerSetLanguageID` | `0x001449a8` | finds text objects only |
| `FlailerSetVisibility` | `0x00144968` | any type |

A missing object leaves `GetBoundingBox`'s box as it was. `GetCenter` passes
uninitialized stack, so the centre of a missing object is garbage in retail.
The port's is 0.

`uirender_object_height` is `GetHeightFloat`; main.c's `hookSetup*` are the
rest.

## Be The Cop Setup

```
Be The Cop Setup (0xd1eadbca, title "Setup")
  1 Catch-up   Off / On                          left/right: toggles
  2 Traffic    Minimum / Moderate / Maximum / Off   left/right: 0..3, wrapping
  3 Damage     Off / On                          left/right: toggles
SELECT on any row -> "Select Car" (or "Select Car2P" if Fred.NumPlayerCars is 2)
```

Its defaults are the photo's: Catch-up On, Traffic Minimum, Damage On. The
blurbs are 30502 "Set the catch-up boost on or off.", 30503 "Set the density
of civilian traffic." and 30504 "Set the visual car damage on or off."; the
labels are 30005, 30006 and 30101, and the values 30008/30009 (Off, On) and
30018..30020 (Minimum, Moderate, Maximum).

The Flailer screen is the one every race setup shares. It has eight rows,
`MENUITEM_1..8` at x=153 with their value texts (`0x69a2c757..5e`) at x=494
and masks `MI_1..8_MASK`. A screen fills as many rows as it has and hides
the rest.

### Fred's `DataBeTheCopSetup`

Twenty bytes at Fred+64. `FrontendDatabase::InitWithDefaults` (`0x00183830`)
calls `0x001b93e0` on it, which sets 2, 0, 1, 0, 1:

| offset | field | default |
|--------|-------|---------|
| +0 | opponent grid | 2 |
| +4 | opponent type | 0 |
| +8 | catch-up | 1 |
| +12 | traffic | 0 |
| +16 | damage | 1 |

This screen only shows the last three. `fred.c`'s InitWithDefaults
writes this block and `DataChallengeScreen` with the rest of Fred
(`frontend-database.md`). `bsetup_fred_defaults`, which wrote only these
two, is left for `setup_test`; main.c no longer calls it.

### `RaceSetupBaseClass`

764 bytes; `BeTheCopSetup` is 784, its data at +764.

| offset | member |
|--------|--------|
| +0 | the screen |
| +4 | `bTList<ChangeableItem>` Changeables |
| +12 | CurrentMenuItemHash |
| +16 | SelectionSet (IndicatorMode at +144) |
| +164 | tSlideInAnimation |
| +184, +216 | two tHighlightAnimations: the item's (`0xab671c9a`, BloomTargetColor) and the value's (`0x1042eac3`, -1) |
| +248 | the tExitScreenAnimation, a pointer |
| +252 | tScrollingMenuList |
| +308 | the arrows |
| +340 | tAnimatedBlurb |
| +760 | vptr (`0x002b6920`; BeTheCopSetup's `0x002b6900`) |

A `ChangeableItem` (44 bytes) is one row: MenuItem +8 and ChangeText +12
(both 0 until BuildMenu), LanguageID +16, a pointer to its Value +20, two
pointers to member functions, Change +24 and Refresh +32, and BlurbID +40.
`Attach` (`0x001b7dd8`) appends one.

- **The constructor** (`0x001b8390`), in order: the SelectionSet; the slide
  in to MI_1_MASK's X; the two blooms; the scroller, on MENUITEM_1 to
  MENUITEM_7 with the up and down arrows `0xedf2e4ee`/`0x20d73d01` and the
  clip poly `0xc67cfb4a`; the arrows (`0xd1cda594`, `0x9345e4a7`); the blurb;
  the movie; both arrows clipped to the poly. It sets no help override.
- **BeTheCopSetup's** (`0x001b9248`): the base, Fred's 20 bytes, the three
  rows, `BuildMenu("Be The Cop Setup")`, then `ResyncChangeables`.
- **BuildMenu** (`0x001b85b8`): indicator mode 1 and all eight masks. For
  each row: MenuItem and ChangeText from the tables at `0x00313e38` and
  `0x00313e78`; the text shown; `GrayMenuItem(name, item, screen, 1)`
  (`0x0016d2a8`, the one that finds its screen by name); the label; the text
  shown again. The other items get mode 2 and their texts are hidden. The
  scroller gets the row count, then the texts, then the items.
- **The destructor**: BeTheCopSetup's (`0x001b9348`) puts the data back in
  Fred, then calls `SetupRaceParametersAfterRaceSetup` and
  `MakeChallengeCarsAvailable`, SELECT or not. The base's (`0x001b84f0`)
  turns the help override off, then deletes the exit, the blurb and the
  scroller (which puts every object back where it found it), then the
  slide in.
- **Callback** (`0x001b93d8`) is `BaseCallback` (`0x001b7b20`) with 104:
  ACTIVATE news the screen on `data[0]` into `pInstance` (gp-18780),
  UNACTIVATE deletes it, and everything else goes to `HandleMenuEvent`
  without a null check.

### `HandleMenuEvent` (`0x001b7ea8`)

A TICK animates both blooms first. The arrows see every message. A running
exit takes every message and nothing after it runs. Then the scroller, then
the message:

- **SELECT**: the exit to car select, the brackets' group (`0x97bf4b25`)
  leaving with it, the arrows off.
- **HIGHLIGHT**: the row's blurb; CurrentMenuItemHash; the arrows on the
  value text by the item's index in the table (0 for one not there); the
  SelectionSet and the brackets on the *scroller's* mask, not the item's
  (`SetupHighlight`, `0x001b7d50`, -3.0 under the box and 6.0 over it); the
  two blooms by index.
- **LEFT/RIGHT**: the row's Change with -1 or +1. No change is silent (noise
  0). A change refreshes the text, plays MENU_LEFT or MENU_RIGHT and
  restarts the value's bloom (`ForceStart`, `0x00248ad0`).
- **PAD_UP** on MENUITEM_1 and **PAD_DOWN** on the last row are taken
  (param 1): the menu doesn't wrap.
- **TICK**: the blurb, and the slide in until `IsFinished`.

Catch-up's and Damage's Change (`0x001b7970`, `0x001b7a78`) set the value
to `value == 0` and always answer 1. Traffic's (`0x001b79a8`) is
`ValueChanger(v, dir, 0, 3)`. Each Refresh sets the text's LanguageID from
its table, unchecked.

### `tScrollingMenuList` (`0x00249de0`)

It keeps a list of `tMenuAnimElement`s (64 bytes each: SavedY +8, a
`tCubic1D` +12, the chunk +60), one per object added, and slides them all
together so the current item stays inside the visible area. The area runs
from the first item's Y to the last's, MENUITEM_1 and MENUITEM_7 here.

- **AddObject** (`0x00249f70`): an object the screen has is clipped to the
  poly and gets an element, at rest on its Y.
- **HIGHLIGHT**: `Highlight` places the mask from the item's number, but
  only while it is -1, so only the first highlight does. MENUITEM_7, 8, 9
  and two other hashes all map to the seventh. Then `SetCurrentObject`: an
  item above the area has every element's destination moved by the
  distance that puts it at the top; one below, at the bottom. Then the up
  and down arrows are shown if the list has 8 items or more and something
  is headed out of view.
- **PAD_UP/PAD_DOWN** move the mask, clamped to 0 and to
  `min(7, NumMenuItemsToScroll) - 1`.
- **TICK**: every element seeks its spline by RealTimeElapsed
  (`SplineSeek`, `0x001daec8`) and moves its object there, then the arrows'
  pulse steps and both take it as their alpha.
- **The mask** is `0x0031cfa0`'s seven words, the MI_1..7_MASK hashes that
  its static initialiser (`0x0024a888`) fills.

The scroller's arrows and the clip poly are invisible on this screen, and
three rows never scroll.

## What the port does differently

- `mPolice` is `gf->copsOn`, where bscreens.c keeps it, not Fred+32. Moving
  the frontend's state into the Fred image is its own task.
- `IsJoystickPluggedIn` answers 1 for port 0 and 0 for anything else, so
  the second player never appears.
- `SetHelpOverride` is only logged: the help menu (`tHelpMenu`) is not
  ported yet.
- The three car calls are traced, not run. Car select comes next.
- "Select Car2P" is registered with player one's screen, `0x18dc8e52`. Retail
  gives it one screen per pad (`0x18dc8e53` for port 1). The 3DS can't
  reach it.
- The skill table is read only for 0..3. Beyond that the port reads 0, where
  retail reads whatever follows the table.
- `CurrentMenuItem` starts at 0 instead of heap garbage.

Be The Cop Setup:

- `ClipToPoly` is stored, but `uirender.c` does not clip yet.
- The scroller's elements and the rows live in fixed arrays (16 and 8), not
  malloc'd lists.
- Retail reads unchecked in four places, and the port guards each:
  - a HIGHLIGHT on an item no row has: retail reads BlurbID through a null
    pointer; the port leaves the blurb alone;
  - a value off its row's table: the port reads 0;
  - `SetupHighlight`'s box is uninitialized stack when the mask is missing:
    the port's is 0;
  - a message with no instance: the port ignores it.
- Only one race setup screen is alive at a time, as with retail's
  `pInstance`, so the port keeps one `BRaceSetup`.

## The check

`python tools/setup_check.py` runs the script on both sides.

- **The model**: retail's callback, and everything above it in the image,
  in `retail_model.RetailEmu`, with the real `bSin`.
- **The stubs**, which print what they are asked:
  - the animation kit, at its retail addresses;
  - the Flailer calls;
  - the pads, the movie, the help override and the three Fred calls.
- **The harness** (`tools/src/setup_test.c`): `bsetup.c`, with stand-in
  `banim_*` that print the same lines. It reads Fred at retail's offsets,
  written out, not taken from `bsetup.h`, so a wrong offset there shows.

The script covers:

- Fred with one player, two, three, none and a negative count, with the
  skill at 0..3, and cops on and off.
- Both pads, one, and none.
- The pulse at odd steps, at exactly 6.283, and past a whole turn.
- Every item highlighted, and one more.
- Every scroll both ways through both wraps.
- SELECT on every item from both ports, and on hashes either side of the
  range.
- Every other message, with and without an exit running.
- BACK after changes with no SELECT, over a Fred whose game type and count
  something else changed.
- Objects missing: no arrows, one arrow of the wrong type, no value.
- A `tfeSineWave` on its own, with bounds the arrows never use.

`--mutate` runs 145 mutations over `bsetup.c` and `bsetup.h`. Three survive,
and all three are equivalent:

- `event-any`: the arrows' `HandleEvent` has one caller, and it passes
  SCREEN_TICK.
- `skill-changed`: a ±1 step always changes the level.
- `sel-range-signed`: MENUITEM_1 and MENUITEM_2, `0x52e039f3` and
  `0x52e039f4`, are both below 0x80000000, so a signed test holds the same
  two hashes.

`python tools/racesetup_check.py` does the same for Be The Cop Setup, on
the same harness (its `rmsg`/`rdump` ops). It adds stubs for `ForceStart`,
`IsFinished`, `SplineSeek` (both sides arrive at once; `banim_check.py`
checks the real one), and the Flailer's Y, clip, alpha and by-name gray
calls. `SetTopLeftY` moves the object, so the scroller reads back what it
wrote. The script covers:

- the defaults and another Fred, cops on and off;
- every row both ways, through Traffic's wraps, and a row that isn't there;
- up and down off both ends;
- rows off the visible area both ways, and the seek ticked;
- SELECT with 0, 1, 2, 3 and -1 cars, and every message during the exit;
- BACK after changes, UNACTIVATE twice, and an ACTIVATE over a live screen;
- no arrows, and a row's item and text missing.

`--mutate` runs 86 mutations over the new code. Four survive, and all
four are equivalent:

- `mask-off`: the scroller's mask is -1 at `GetCurrentMenuMask` only
  after a HIGHLIGHT on an item `Highlight`'s switch lacks, and every
  row's item is in it. That item has no row, and there retail reads
  `BlurbID` through a null pointer, so no script sends one.
- `row-index-default`: the default index is read by HIGHLIGHT on an item
  with no row (the same null read) and by PAD_DOWN, where with three
  rows 0 and 1 both answer "not the last".
- `traffic-changed`: Traffic's step is 1 or -1, and `ValueChanger` moves
  any value by one or wraps it to the other end, so it always changes.
- `lr-silent-kept`: no row's `Change` answers 0. Catch-up's and Damage's
  always answer 1, and Traffic's always changes.

The first pass's survivors were holes in the script, and each has a case
now: Fred's defaults per field, BACK after a damage change, the release's
`SetTopLeftY` order, the state a zero delta leaves, the highlight on a
row other than the first, a Catch-up flip over a value that is not 0 or
1, and the highlight box's item. `rpoke` and the moved objects (`obj`'s
tenth field) are there for them.

## What comes next

- **The other race setups** (Single Race, Free Run, Lap KO, Track KO; 100
  to 103 in `BaseCallback`) are `RaceSetupBaseClass` with other rows. They
  wait: racing comes first.
- **"Select Car"** is `SelectCarScreen`. The three car calls above belong to
  it.
