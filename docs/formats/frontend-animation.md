# The frontend animation layer

Every menu screen in the game is a set of Flailer objects that do not move
([flailer-ui.md](flailer-ui.md)). What makes them move is a small kit of
C++ classes in `FEAnimations.obj`, `ModeSelect.obj` and `bMath`: a cubic
spline integrator, a thing that drags a group of objects along one, four
canned uses of that thing, an alpha fader, a scrolling caption, and a
highlight bloom. Between them they are the entire difference between the
port's menus and the shipped ones -- the items slide in from the right, the
blurb line whites out and scrolls, the current item's label blooms outward
and fades, and leaving a screen slides everything back off before the flow
is allowed to change.

Everything here was decompiled out of `PS2 Files/NFSHP2.ELF` with
`tools/mipsdis.py`; each rule cites the address it came from. The port is
`3DS Files/source/banim.c`, driven through `bscreens.c` and hooked up to the
real Flailer in `main.c`. It is cross-checked against a second, independent
implementation in `tools/banim_check.py` (23 scenarios, 2219 lines, 0
differ), and the screens that use it are re-checked by
`tools/bscreens_check.py` (17 scenarios, 1246 lines, 0 differ).

| class | constructor | object file |
|-------|-------------|-------------|
| `tCubic1D` | -- | `bMath` |
| `AnimationGroup` | `0x00232010` / `0x002320d0` | `FEAnimations.obj` |
| `tSlideAnimation` | -- | `FEAnimations.obj` |
| `tSlideInAnimation` | `0x00232a48` | `FEAnimations.obj` |
| `tSlideOutAnimation` | `0x00232958` | `FEAnimations.obj` |
| `tExitScreenAnimation` | `0x00232b50` | `FEAnimations.obj` |
| `tHighlightAnimation` | `0x00232318` | `FEAnimations.obj` |
| `feAnimAlphaElement` | `0x00231ba8` | `FEAnimations.obj` |
| `tAnimatedBlurb` | `0x00232c18` | `FEAnimations.obj` |
| `SelectionSet` | `0x00169358` | `FlailerMenu.obj` |

## The short version

```
tCubic1D            one float, integrated along a cubic between two values
  SplineSeek        0x001d0790   advance it by dt and decide if it arrived

AnimationGroup      a tCubic1D driving one object's X, dragging its group
  Animate           0x00232290   seek, truncate to int, place
  SetupToAnimate    0x00232190   re-aim it from `start` to `end`

tSlideAnimation     up to 10 AnimationGroups, one per MENUITEM_n_GROUP
  tSlideInAnimation   0x00232a48   650 -> authored,  staggered starts
  tSlideOutAnimation  0x00232958   authored -> 650,  staggered durations
  tExitScreenAnimation 0x00232b50  a slide-out plus "then ChangeToScreen"

feAnimAlphaElement  scales an object's authored alpha by a float
tHighlightAnimation the bloom: a copy of the label, scaled up and faded out
tAnimatedBlurb      the one-line caption: whiteout, swap, scroll in
SelectionSet        which MI_n_MASK is current, and the visibility that implies
```

## tCubic1D and SplineSeek

`tCubic1D` is four floats and two coefficients: `Val`, `dVal`, `ValDesired`,
`dValDesired`, and `a`/`b` made by `MakeCoeffs` (`0x001d0048`). It is the
generic "move a number from here to there over a duration and arrive with a
chosen derivative" primitive; the frontend only ever uses it with both
derivatives 0, which is a plain ease-in-ease-out.

`SplineSeek` (`0x001d0790`) is the whole integrator:

```
if (state != 1) {
    if (state < 2 || state != 2) return;   /* the compiler's own test */
    time = 0;
    if (flags == 0) state = 1;
    MakeCoeffs();
}
t = time + dt / duration;
time = t;
if (t >= arrivalThreshold) {
    if (arrivalThreshold >= 1.0) { val = valDesired; dval = dvalDesired; }
    state = 0;
} else {
    val  = evaluate(t);     /* ((a*t + b)*t + dVal)*t + Val, GetVal       */
    dval = derivative(t);   /* (a*(t*3) + (b + b))*t + dVal, GetdVal      */
}
```

`time` is stored before the arrival test, in the branch's delay slot, so a
spline that arrives keeps the `t` it arrived at. The two evaluations round
in the order shown: `derivative` multiplies `t` by 3 first and doubles `b`
before adding. `bspline_get_dval` had `(a*t)*3 + b + b` until step 8m-4c-2,
whose checker runs retail's own tCubic1D (`hud-nis.md`); `dVal` was off in
its last bit.

Three things about it are worth stating plainly, because they are what the
port has to reproduce rather than improve:

* **The arrival test is `>=`, and the snap is conditional.** A spline whose
  `ArrivalThreshold` is below 1.0 stops *early* and keeps whatever `Val` the
  polynomial had at that point -- it does not jump to `ValDesired`. Every
  frontend spline uses a threshold of exactly 1.0, so every frontend spline
  does snap; but the branch is real and the port keeps it.
* **State 0 means finished, 1 means running, 2 means "aimed, not started".**
  Nothing else is reachable: the `state < 2 || state != 2` above is one
  comparison written twice by the compiler, and it lets state 0 fall through
  and return unchanged. A finished spline that is seeked again does nothing.
* **`flags == 0` is what promotes 2 to 1.** `SetupToAnimate` clears `flags`,
  which is how a group that has been re-aimed starts moving on its next
  seek rather than on the call that aimed it.

`ClampSecondDerivative` (`0x001d01f8`) has a shipped argument bug: the guard
at `0x001d0818` tests the second-derivative limit in `$f22` and the delay
slot at `0x001d0824` then passes the *first*-derivative limit in `$f20`. The
frontend's only caller passes 0 for both, so the bug cannot fire here and the
port does not carry it; `banim.h` records it next to the declaration so the
next caller knows.

## AnimationGroup

One `tCubic1D` plus a screen hash, a group hash, a master object hash, and
the master's authored position. The `.mdebug` gives the class in bWare's own
spelling -- 76 bytes, `ScreenHash` `GroupHash` `MasterHash` `SavedXPos`
`SavedYPos` at `+8` through `+24` and `Spline` at `+28` -- which is what the
port's `BAnimGroup` mirrors. `Animate` (`0x00232290`):

```
SplineSeek(&spline, elapsed, 0, 0)
x = (int)spline.Val
if (Group == 0) FlailerSetTopLeftPosition(Screen, Master, x, SavedYPos)
else            FlailerSetGroupPosition  (Screen, Group, Master, x, SavedYPos)
```

`Group == 0` is not "the group whose hash is zero" -- it is the flag for
"there is no group, just move the master". The blurb's own slide uses the
five-argument constructor (`0x002320d0`), which writes 0 to the group field
at `+12`; the menu rows use the six-argument one (`0x00232010`), which stores
the `MENUITEM_n_GROUP` hash there. Getting this wrong would drag every object
whose `GroupHash` happens to be 0 across the screen.

`FlailerSetGroupPosition` (`0x00142f60`) takes the delta that would put
`Master` at the requested point and applies it to every object on the screen
carrying `Group`. The master itself moves only because `MI_n_MASK` is a
member of `MENUITEM_n_GROUP`.

Two truncations, both deliberate:

* the X handed to the Flailer is `(int)Val`, so an item slides in whole
  pixels;
* `SavedXPos`/`SavedYPos` are read through `FlailerGetTopLeftPosition`'s int
  overload (`0x00141d28`), which `cvt.w.s`'s both. bWare's own debug info
  agrees -- the `.mdebug` entry for `AnimationGroup` declares both as `int`
  -- so these are integers, not rounded floats. Nothing on the disc is
  authored off a whole pixel (all 2252 objects across the four bundles are
  integral), so this never changes a coordinate; the destructor's restore is
  where it would show, and the port truncates so it cannot drift.

`SetupToAnimate` (`0x00232190`) is three inlined `tCubic1D` calls in a row --
`SetValDesired(start)`, `SetVal(start)`, `SetValDesired(end)` -- and the
first one's `state = 2` is overwritten by the second's `state = 0` one
instruction later. The write is dead and the port keeps it anyway, because
"the original does this" is the only thing that makes the two implementations
comparable line for line.

## tSlideAnimation and its three uses

A `tSlideAnimation` is an array of up to ten `AnimationGroup`s plus a total
time. `AddGroup` (`0x002326d8`) appends one. `IsFinished` (`0x00232828`) is
true when every group's spline is in state 0; `HasControl` (`0x002327f0`) is
true while any is not. `GetFractionCompleted` (`0x002328b0`) is the elapsed
fraction of the longest group.

The group hashes are built at runtime, not authored: `SprintfAndHash`
(`0x001d1d98`) formats `"MENUITEM_%d_GROUP"` and `"MI_%d_MASK"` and hashes
the result with `bStringHash`. Because that hash is djb2 (`h = h*33 + c`,
seeded `0xFFFFFFFF`), two names that differ only in one digit differ by a
constant: `33^6 = 1291467969` for the group (six characters follow the
digit) and `33^5 = 39135393` for the mask (five do). So:

```
MENUITEM_n_GROUP = 0x59c1995e + n * 1291467969   (mod 2^32)
MI_n_MASK        = 0x6bdfbaaf + n * 39135393     (mod 2^32)
```

verified against `tools/bhash.py` for n in 0..9. The port computes them the
same way rather than tabling them, which is also how a screen with more items
than anyone authored would still work.

**`tSlideInAnimation`** (`0x00232a48`) walks n = 0..9, skips any
`MENUITEM_n_GROUP` the screen does not have, and gives slot i a group that
runs from `640 + i*10` to the authored X over
`SplineBaseDuration + i * SplineDeltaDuration` seconds -- two statics at
`0x00324db4` and `0x00324db8`, both `0.05`. The stagger is in both the start
position and the duration, which is what makes the rows arrive in sequence
rather than as a block.

**`tSlideOutAnimation`** (`0x00232958`) is the mirror: authored X out to
`650.0` (`0x00322254`), duration `0.05 + i*0.05`. Its total time is therefore
`0.05 * numGroups`, and *that* is where the exit timings come from. The port
used to carry three hand-measured constants for this -- 0.25 s for Cops On,
0.20 s for Cops Off, 0.40 s for Options. They are gone: the durations now
fall out of asking the bundle which `MENUITEM_n_GROUP`s exist, and the
harness prints exactly 0.250, 0.200 and 0.400 back.

**`tExitScreenAnimation`** (`0x00232b50`) is a slide-out plus a destination
name. `HandleMessages` (`0x00232b90`) is the interesting half, because it is
the one piece of the animation layer whose *timing* changes what the game
does:

```
*Noise = 0                                  /* unconditionally, first */
if (msg == 17)                 { *Param = 0; return 0; }   /* RENDER */
if ((unsigned)(msg - 8) < 2)   { *Param = 1; return 0; }   /* UP, DOWN */
if (msg != 18)                              return 0;      /* TICK */
Animate()
if (!IsFinished())                          return 0;
ChangeToScreen(Target, 1)
return 1
```

`Param = 1` on UP and DOWN is how navigation is frozen while the screen is
leaving, `Noise = 0` is how it stays silent, and the screen change happens on
the tick that finishes the slide -- not on a timer, and not on the keypress.

## feAnimAlphaElement

`0x00231ba8` records an object's authored alpha; `SetAlphaScale`
(`0x00231c80`) multiplies it by a float and writes it back. A bitmap has four
corner alphas and everything else has one, which is the only reason the
animation layer ever asks an object its type:
`FlailerObjectChunk::GetAlpha`/`SetAlpha` (`0x0013e098`, `0x0013ea48`) versus
`FlailerBitmapChunk`'s indexed pair (`0x0013efa8`, `0x0013ed50`). Alpha is
the top byte of the colour word in both cases -- `lbu v0,71(a0)` for text,
`lbu v0,67(a0+corner*4)` for a bitmap corner -- and a bitmap `SetAlpha` with
corner -1 writes all four.

## tHighlightAnimation

The bloom behind the current menu item: a second copy of the label, scaled
from 1.0 to 2.0 and faded from alpha 128 to 0 over half a second, repeating
until a four-second timeout. The tuning lives in six statics
(`0x00324d8c`..`0x00324da0`) and the colour is `0x00000080`.

`SetCurrentMenuItem` (`0x00232378`) copies the item's text into the bloom
object, and `Animate` (`0x00232418`) does the rest. Two constructs in it look
redundant and are not removed:

* `bSin` is called **twice** per frame -- once for the scale and again inside
  the alpha expression -- rather than once into a temporary.
* `FlailerGetScale` is called **twice** in `SetCurrentMenuItem`, with the
  scale reset to 1.0 before each.

Both are in the shipped code, both are observable only as instruction count,
and both are kept so the cross-check can compare call for call.

`bSin` itself (`0x00241e98`) is a BAM table walk, not `sinf`: the radians are
multiplied by `10430.37793` and truncated to a 16-bit binary angle, scaled
back by `9.587380191e-05`, range-reduced at `4.712388992` and `1.570796371`,
and finished with a five-term Taylor series. It **overshoots**: at the peak it
returns `1.00000358`, not 1.0. That is the value the bloom's scale and alpha
are computed from, so the port reproduces the routine rather than calling the
C library.

## tAnimatedBlurb

The single caption line under the menu. Three states and three objects: the
text that is sliding in (`SCROLLING_TEXT`, `0x75980cf0`), a copy that is
fading out, and a dark bar (`WHITEOUT_BAR`, `0x70a404ec`) that covers the
swap.

```
WHITEOUT   bar alpha ramps up over 0.6 s (_14tAnimatedBlurb$WhiteoutTime)
           -- but the state only advances 0.5 s after the LAST NewText
              (_14tAnimatedBlurb$IdleTime)
NEW_TEXT   LanguageID <- 0, then FlailerPrintf("%s", LatestText),
           then slide in from 650 over 0.25 s
SETTLED    nothing
```

The idle timer is why holding a direction does not produce a flicker of
captions: every `NewText` restarts it, so a run of highlight changes keeps
the line under the bar and only the last one is ever printed.

`NewText(int)` (`0x00232ef0`) resolves the row through `GetTranslatedString`
(`0x0020b0e0`) first, which is why the port's `translate` hook copies out of
the language table rather than repointing `LanguageID` -- the object has to
be *off* the table (`LanguageID = 0`) for the printed literal to show.

## SelectionSet

`SelectionSet` (`0x00169358`) is the bookkeeping the highlight sits on:
`AddItems` (`0x00169430`) records up to sixteen `MI_n_MASK` objects and
`SetCurrentItem` (`0x001694a8`) makes one of them visible and the rest not.

One detail matters and is easy to lose: `AddItems` increments `NumItems`
**even for a mask the screen does not have**. The array keeps the hole, so
item indices stay aligned with menu item numbers on a screen with a gap in
its `MENUITEM_n` sequence. Compacting the list would silently renumber every
item after the gap.

## Naming

Three of the object hashes that `frontend-screens.md` left unnamed are
cracked, by `tools/bhash_crack.py` working from the names the layer already
uses (`MI_UNDERSCORE`, `MI_OVERSCORE`, `MENUITEM_n_GROUP`):

| hash | name |
|------|------|
| `0x70a404ec` | `WHITEOUT_BAR` |
| `0x6eb9985d` | `NONAME` |
| `0x97bf4b25` | `UNDERSCORE_GROUP` |

`NONAME` is the giveaway for the other two: it is what the Flailer editor
writes when an object is left unnamed, and it appears on nearly every screen
in the bundle. `0xab671c9a` and `0x1042eac3` (the two bloom text objects) are
still uncracked.

## The port

`banim.c` is hook-driven like the rest of the port: it never touches a
Flailer chunk itself. `BAnimHooks` is eighteen function pointers covering
object lookup, position, visibility, alpha, text and scale, plus
`changeToScreen` and `trace`.

The single `user` pointer is shared, and two of the hooks do not belong to
the same owner as the rest: `ChangeToScreen` and the tracing are free
functions on a global in the original. So `bscreens.c` installs the whole
table and then overwrites those two slots with its own functions, which find
the instance through a file-static -- leaving `user` for the Flailer side,
which is what `main.c` fills in.

Time comes from `gameflow.c`. `RealTimer` (the running total) and
`RealTimeElapsed` (`0x00323cdc`, this frame's delta) are separate globals in
the original because the spline integrator wants the delta and everything
else wants the total. Rather than start a second clock, `bscreens.c`
re-slaves its one `BAnim` from both at every entry point.

`main.c` implements the Flailer side against `bui.c` and `uirender.c`. Four
primitives had to be added underneath:

| new | why |
|-----|-----|
| `bui_get_object_alpha` / `bui_set_object_alpha` | the fades; text and bitmap differ, corner -1 means all four |
| `bui_set_object_scale` | the bloom |
| `bui_set_text_string` | `FlailerPrintf`, for the blurb's resolved literal |
| `bui_next_in_group` | `FindFlailerObjectByGroup`, for group moves and existence tests |
| `uirender_text_extent` | `GetScaledWidth`/`GetScaledHeight`, which `ScaleAboutCenter` divides |

`ScaleAboutCenter` (`0x0013eb20`) is the one with geometry in it. It nudges
the anchor by the half-extent the scale change costs, so the glyphs grow out
of the middle, and which coordinate moves depends on the justification bits:

```
halfW = GetScaledWidth()  / (2 * ScaleX)
halfH = GetScaledHeight() / (2 * ScaleY)
LEFT   (0x02): Y += halfH*(ScaleY-s);  X += halfW*(ScaleX-s)
CENTER (0x04): Y += halfH*(ScaleY-s)
RIGHT  (0x01): d = ScaleX-s;  Y += halfH*d;  X -= halfW*d
none:          neither moves
ScaleY = ScaleX = s
```

`GetScaledHeight` (`0x0013e858`) truncates the font's line height to an int
*before* `ScaleY` multiplies it (the `cvt.w.s` at `0x0013e880`), which is
reproduced rather than rounded away.

## Checking it

`tools/banim_check.py` is a second implementation in Python, written from the
disassembly rather than from `banim.c`, and diffed against the C line for
line. Both sides emit a trace of every state change they make; the run is 23
scenarios and 2219 lines.

Float determinism is the whole difficulty. The Python model rounds to float32
after **every** operation, because the EE has no double path here and a
single unrounded intermediate is enough to move a truncated pixel. The
`cvt.w.s` instruction truncates toward zero, which is C's `(int)` cast and
Python's `int()`.

The scenarios cover: a spline arriving normally, early (threshold below 1),
late, and stuck (state 0); `bSin` across its range including the overshoot; a
slide-in on a full screen, on one with a gap, and on an empty one; a
slide-out mid-flight and idle; an exit with and without an underscore group;
a highlight that blooms, one on a half-scale item, one that loops past the
timeout, and one whose object is missing; the alpha element on text, on a
bitmap and on nothing; a blurb run and a blurb interrupted inside its idle
window; and `SelectionSet` in both modes.

Mutation-tested: changing the Taylor coefficient `2.755731884e-06f` to
`e-05f` moves 28 lines, and changing the slide stride `0.05f` to `0.06f`
moves 173. Two earlier attempts at a mutation -- `4.712388992f` to
`4.712389f` and `6.283185482f` to `6.2831855f` -- changed nothing, because
those pairs are the same float32.
