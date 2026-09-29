# The race setup screens

Between a Mode Select and car select sits a setup screen: the few settings
the chosen mode takes before the cars. This is the first of them,
"You're The Cop", the screen Cops On Mode Select's second item opens
([frontend-screens.md](frontend-screens.md#the-short-version)). With it come
the two small classes every setup screen shares.

Everything here is from the retail image, SLES_507.31, disassembled with
`tools/retaildis.py`; each rule cites its address. The port is
`3DS Files/source/bsetup.c`, and `tools/setup_check.py` runs it next to
retail's own code in `mipsemu` (359 ops, 2293 lines, 0 differ; see
[the check](#the-check)).

| class | address | what it is |
|-------|---------|------------|
| `BeACopChallengeSetup` | `0x001b6c68` .. `0x001b7748` | You're The Cop |
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
     (`0x001862b0`).
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

## What comes next

- **"Be The Cop Setup"** is `BeTheCopSetup` on `RaceSetupBaseClass`
  (`0x001b8390`, `0x001b9248`). It shares Flailer screen `0xd1eadbca` with
  Single Race Setup and the other race setups, and is built on
  `tScrollingMenuList`. The arrows are this same class, with `SetClipToPoly`.
- **"Select Car"** is `SelectCarScreen`. The three car calls above belong to
  it.
