# The HUD's animations (step 8m-4a)

The HUD's moving parts are HudAnimators. One moves one Flailer object, a
text or a bitmap, from a start to an end over a time: its top left, its
scale and its alpha, and a text's colour, each along a straight line. The
Player holds twenty in `pHudAnimations` (Player +1540), each made on
demand. This step ports HudAnimator and the Player functions that start,
run and clear them:

| function | address | port |
|----------|---------|------|
| HudAnimator::HudAnimator | `0x0023b0f8` | `hudanim_init`, `hudanim_new` |
| HudAnimator::~HudAnimator | `0x0023b168` | `hudanim_delete` |
| HudAnimator::StartAnimation (the scored text) | `0x0023b1e0` | `hudanim_start_scored` |
| HudAnimator::StartAnimation (text) | `0x0023b498` | `hudanim_start_text` |
| HudAnimator::StartAnimation (bitmap) | `0x0023b5e0` | `hudanim_start_bitmap` |
| HudAnimator::DoAnimation(Timer) | `0x0023b788` | `hudanim_do` |
| HudAnimator::DoAnimation(Timer *, char *) | `0x0023bb58` | `hudanim_do_scored` |
| HudAnimator::FinishAnimation | `0x0023bf60` | `hudanim_finish` |
| Player::ClearHudAnimations | `0x0017c7c8` | `player_clear_hud_animations` |
| Player::HudStartWrongWay | `0x0017c888` | `player_hud_start_wrong_way` |
| Player::HudStartGrowAnimation | `0x0017cb18` | `player_hud_start_grow_animation` |
| Player::HudStartSpeedAnimation | `0x0017cd30` | `player_hud_start_speed_animation` |
| Player::HudStartAnimation (text) | `0x0017cfb8` | `player_hud_start_text_animation` |
| Player::HudStartAnimation (bitmap) | `0x0017d130` | `player_hud_start_bitmap_animation` |
| Player::HudDoAnimations | `0x0017e038` | `player_hud_do_animations` |
| Player::AddToTotalScore | `0x0017e350` | `player_add_to_total_score` |

All of it is in `hudanim.c`. `main.c` binds the seams that RenderHud,
UpdateHud and the race code call through: HudDoAnimations,
HudStartSpeedAnimation, HudStartGrowAnimation, HudStartWrongWay,
ClearHudAnimations and the animator's delete.

Nothing in retail calls HudStartBlink (`0x0017d2b0`), StartBlink
(`0x0023b700`), DoAnimation(Timer, float) (`0x0023ba48`), SetVisibility
(`0x0023b188`) or StartMusicTitleAnimation (`0x0017da00`), and no data
holds their addresses. The port leaves them out.

## HudAnimator

288 bytes, from `bMalloc(288, 16)`. `hudanim.h` gives the layout. The
fields fall into four groups:

- **What it moves:** `pText` (+72) or `pBitmap` (+76), and `Type`
  (+272): 1 for a simple text or bitmap, 2 for a blink, 3 for a scored
  text.
- **One phase:** `Pos`, `DeltaPos`, `Scale`, `DeltaScale`, `Alpha` (an
  int), `DeltaAlpha` (a float), and a simple text's `Colour` and
  `DeltaColour`.
- **A scored text's other two phases:** `DeltaPos2`, `Scale1`,
  `DeltaScale2`, `Alpha1`, `DeltaAlpha2`, `Colour3` and `DeltaColour3`.
  Its own string goes in `String` (+0, 64 bytes) with `bHasString`.
- **Timing:** `Duration[3]` in seconds, `StartSeconds`, `Phase`,
  `bActive`, `bKeepVisible` and `bRealTimer`.

The constructor sets `Colour` to (128, 64, 0, 0). It clears
`DeltaColour`, `bHasString`, the word at +68, both objects, `bActive`,
`bKeepVisible`, `bRealTimer` and `Type`. The rest is whatever the heap
held.

### Time

A start stores the timer in seconds: WorldTimer (gp-19576) times 1/4000
(the float at gp-26748), or RealTimer (gp-19608) for a scored text started
with `real_timer`. The time each Player function is handed is never read:

- every start reads the timer itself;
- DoAnimation(Timer) reads WorldTimer in place of its argument;
- only the scored DoAnimation reads the Timer it is handed, and
  HudDoAnimations hands it WorldTimer.

`t` runs from 0 at the start to 1 at the end, and is held at 1 after it.
Before the start it is negative and the line runs backwards; nothing
clamps it at 0.

### One frame

A value at `t` is `delta * t + start`. Three things are not plain floats:

- **Position.** The top left goes through an int: `X = (float)(int)x`.
  The scale does not.
- **Alpha.** Only the delta's part is truncated: `Alpha + (int)(DeltaAlpha
  * t)`. Full is 128. Nothing clamps it: SetAlpha keeps only its low
  byte, so 300 shows as 44.
- **Colour.** SetColor gets r, g and b, each truncated into its own byte.
  The fourth component is carried but never used.

### The simple text and bitmap

**StartAnimation (text)** always restarts. It stores the start and the
deltas and sets `Type` to 1. It colours the text from (128, 64, 0) to
(128, 128, 128). The text goes to its start position at once, with its
start alpha, and is shown.

**StartAnimation (bitmap)** sets `Type` to 1 first. If the animator is
already running, that is all it does. Otherwise it stores the start, the
deltas, the bitmap and `keep`, puts the bitmap at its start with SetAlpha
over all four corners (−1), and shows it.

**DoAnimation(Timer)** does nothing unless the animator is running and
its type is 1. It always answers 0.

- **A text:** moved, scaled, faded and coloured. At the end it is hidden
  and stops.
- **A bitmap:** moved, scaled and faded. At the end it gets its last
  alpha and stops, and is hidden unless `bKeepVisible`.
- **Both objects set:** the text wins. This happens when a bitmap is
  started on a text's animator.

### The scored text

**StartAnimation (the scored text)** takes three phases of `d0`, `d1`
and `d2` seconds:

| phase | position | scale | alpha | colour |
|-------|----------|-------|-------|--------|
| 0 | `Pos + DeltaPos·t` | `Scale + DeltaScale·t` | `Alpha + DeltaAlpha·t` | `Colour3 + DeltaColour3·t` |
| 1 | `Pos + DeltaPos` | `Scale1` | `Alpha1` | `Colour3 + DeltaColour3` |
| 2 | `Pos + DeltaPos + DeltaPos2·t` | `Scale1 + DeltaScale2·t` | `Alpha1 + DeltaAlpha2·t` | `Colour3 + DeltaColour3` |

A string that is not NULL is copied into `String`, and that is what the
text shows. Otherwise the caller of DoAnimation names the string each
frame. Retail copies with bSPrintf `"%s"` and no bound; the port bounds it
to 63 characters. The text goes to its start at once and is shown.

**DoAnimation(Timer *, char *)** does nothing unless the animator is
running and its type is 3. It then works through these steps:

1. **Time.** `t` is the time since `StartSeconds` over this phase's
   duration. A phase outside 0 to 2 is not divided by anything, and is
   then set back to 0.
2. **Draw.** With no text, it answers 0 and nothing ends. Otherwise the
   text is placed, faded, given its string and coloured.
3. **End of a phase.** When `t` reaches 1 in phase 0 or 1, the next phase
   starts at `StartSeconds + Duration[phase]`. A late frame therefore
   carries its lateness into the next phase.
4. **End of phase 2.** The text is hidden, the animator stops, and it
   answers 1.

### FinishAnimation

FinishAnimation ends an animation at once, by type:

| type | what happens |
|------|--------------|
| simple text | hidden, and stops |
| simple bitmap | placed at its end with its last alpha; stops; hidden unless kept |
| blink | its bitmap's alpha set to `(int)Colour.w` (StartBlink's first alpha); nothing else |
| scored text | hidden, and stops |
| anything else | nothing |

## The Player

Twenty slots, each made on demand by HudStartAnimation. Slots 10 to 13
are made by StartScoreAnimation (8m-4b).

| slot | holds | runs |
|------|-------|------|
| 0 | the big race position's grow | only with `HUD_RACE_POSITION` (0x200) |
| 1 | the speed's grow | only with `HUD_GAUGES` or `HUD_GAUGES_OUTSIDE` (0x60) |
| 2–8 | the pursuit meter and the radar (8m-4c) | always |
| 10 | the score that counts into the total | scored; shows `strEventScore` |
| 11 | the score's title | scored; shows `strEventTitle` |
| 12 | — | scored; shows `"SCORE"` |
| 13 | — | scored; shows `""` |
| 15 | WRONG WAY | always |
| 16, 17 | — | always |
| 9, 14, 18, 19 | — | never |

**HudDoAnimations** runs a frame of each slot that is running, in the
table's order. When slot 10's scored text ends, `strEventScore` goes to
AddToTotalScore.

**ClearHudAnimations** finishes every slot except 12, 13, 14 and 18. A
running slot 10 first adds `strPrevScore` to the total and stops, and is
then finished like the rest.

**HudStartAnimation** (text and bitmap) takes a start and an end, and
passes the differences on to the animator's StartAnimation. The alpha's
difference is taken in 32 bits and then made a float.

**AddToTotalScore** adds ConvertScoreString's value to `TotalScore`,
wrapping in 32 bits. A total below 0 becomes 0. The total is printed
`"%d"` into the score total's text, when the HUD has one.

### The grow animations

**HudStartGrowAnimation** (slot 0) animates text `a` from text `b`'s
place, scale and alpha. RenderHud calls it with the big race position
when the position changes.

- **grow:** 30 up, scaled to 2, faded from b's alpha to 0 in half a
  second.
- **without grow:** 100 down, scaled to 0.5, faded from 0 to b's alpha in
  a second.

**HudStartSpeedAnimation** (slot 1) does nothing without a speed string
on the HUD. Otherwise it animates `a` from `b` the same way, fading to 0
over a second.

- **grow:** scaled to 2 about b's centre. The end is
  `pos + (w/2 − w/2·2, h/2 − h/2·2)`, from b's width and height.
- **without grow:** 100 down, scaled to 0.5.

### WRONG WAY

**HudStartWrongWay** finds the HUD screen's bitmap `0x89af1a1e` and
starts it in slot 15. It slides from (258, 119), shrinks from 1 to 0.3,
and holds alpha 64 for a second. It is kept up at the end. Because a
bitmap start leaves a running animator be, calling it again while it runs
does nothing.

The end is the start plus an offset:

| case | offset | end |
|------|--------|-----|
| a race | (−105, −80) | (153, 39) |
| a free run | (−240, −100) | (18, 19) |
| the live split shown without the race position | (−95, −80) | (163, 39) |

A free run is RaceType 1 with no laps and not Be The Cop. The live-split
case is tested last, so it wins over a free run.

With two or more players the scale runs from 0.5 to 0.25:

- player 0 slides from (258, 125) to (128, 125);
- player 1 slides from (258, 350) to (128, 350);
- any other player number keeps the end above.

## Where the port differs

- **NULL objects.** Retail writes through a NULL text or bitmap in the
  simple starts. The grow and speed functions read `b` with no check. The
  port skips each of these.
- **The scored text's string** is bounded to 63 characters.

Neither shows in the checker's transcript.

## The checker

**`tools/hudanim_check.py`** runs each retail function above in the
emulator, against the port in the harness `tools/src/hudanim_test.c`.
Both sides run over INGAMEB's Flailer chunk, loaded as
`flailer_check.py` does.

- **The stubbed bMalloc.** Every word of a fresh animator holds a pattern
  by its offset, and the two object pointers hold a dummy object. A field
  that the constructor or a start leaves alone therefore shows the same
  on both sides.
- **What is compared.** After each op: every slot of both Players (the
  allocation number, and the 288 bytes in retail's order with the objects
  by name), `TotalScore`, and every Flailer object's bytes. The scored
  DoAnimation's answer is compared too.

The script covers:

- **The grows:** the race position's grow and shrink, with and without
  the position on the HUD. The speed's, with and without a speed string
  and each gauge.
- **Simple texts and bitmaps** in every slot: running, restarted while
  running, kept, finished, and on a clock run backwards.
- **WRONG WAY** in a race, a free run, with the live split, and in both
  halves of a two-player race.
- **Scored texts** through their three phases on both timers, with their
  own string and the caller's. Also: late frames, a phase and a type out
  of range, no text, and the scored DoAnimation called directly.
- **FinishAnimation** for each type, including a blink.
- **ClearHudAnimations** over every slot, with and without a running
  score.
- **AddToTotalScore** over signs, junk, 32-bit wrap and the floor at 0.

The result is 473 ops, 2829 lines, and 0 differences.

The mutation pass makes 292 mutations: 290 are caught and 2 are
equivalent.

- `lerp-w-dropped` drops the fourth component from the colour's lerp.
  The result goes into a local colour, and only its r, g and b reach
  SetColor.
- `da-inactive-run` lets HudDoAnimations call an animator that has
  stopped. Every animator call it makes checks `bActive` first and does
  nothing; the scored one answers 0.

The first pass had 8 more survivors, and all were gaps in the script.
Most were FinishAnimation's bitmap path (`fin-bitmap-*`), which no case
reached, since slots 16 and 17 held texts. The script now finishes
bitmaps started in the unused slots 6 and 7. It also runs DoAnimation on
a finished text, and runs slot 12's scored text through its third phase.
