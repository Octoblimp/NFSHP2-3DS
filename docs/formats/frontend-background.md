# The frontend's blueprint background

`tGlobalBackgroundAnimation` (0x002495f0 .. 0x00249c74, retail's): the faint
car blueprint that drifts behind the menus' grid. Retail changed it from
the demo disc's, and the port had no version of it until TASKS 75, so it
drew the two blueprint bitmaps where the bundle put them and never moved
them.

Ported to `3DS Files/source/bganim.{c,h}`, free of `<3ds.h>`, and hooked in
through `gameflow.c` (`bgChangeScreen`, `bgTick`) and `main.c`.

Checked by `tools/bganim_check.py` against `tools/src/bganim_test.c`.
Retail's code runs in mipsemu with only the Flailer stubbed, next to the
port, over 5,173 steps (7,197 lines, 0 differ). The script covers the kept
list full, empty and with duplicates, one screen's whole 53-second cycle at
30 frames a second, screens that lack each object, a NULL name, the
cross-fade's edges, the parameter's wrap, and random mixes on several seeds
with car logos kept. 15 facts are read from the image without running it.
`--mutate` runs 46 mutations: 41 are caught and 5 are equivalent, with the
reasons in the checker.

## The objects

Seventeen of FRONTB's menu screens have two bitmaps at z 10, at (0, 0) and
scale 1.25:

| Object | Texture | Alpha as authored |
|---|---|---|
| `MASTER_BP_OBJECT` | `GRID_BLUEPRINT1` | 0x3c |
| `FADING_BP_OBJECT` | `GRID_BLUEPRINT2` | 0x50 |

The class also looks up a bitmap called `GRID` and never uses it. (The
demo's mdebug has the two pointers' names swapped: the one it calls
`FadingBPObject`, at +8, is the one found as `MASTER_BP_OBJECT`.)

## The object, 156 bytes

| Off | Field | |
|---|---|---|
| 0 | screen hash | the Flailer screen's, or 0 |
| 4 | `GRID` | found, never read |
| 8 | `MASTER_BP_OBJECT` | |
| 12 | `FADING_BP_OBJECT` | |
| 16 | `tCubic2D` | x at 16, y at 64 (banim.h's `BSpline2D`) |
| 112 | CrossFadeTimer | RealTimer at the last Reset |
| 116 | GridTimer | RealTimer at the last screen change, never read |
| 120 | AnimationParam | `+= RealTimeElapsed`, less 6.283 once at or past it; never read |
| 124 | kept textures | 8 hashes, 0 for an empty slot |

`FlailerScreenList`'s constructor makes it with `bMalloc(156)` and keeps it
at +456. The constructor puts the spline at (320, 240) with nothing to seek,
both durations at 50, and resets the kept list.

## The kept list

- **Add** (0x00249730) clears every slot holding the hash, then stores it in
  the first empty slot. A full list drops it.
- **Remove** (0x00249790) clears every slot holding the hash.
- **Count** (0x002497b8) is the number of slots in use.
- **Nth** (0x002497f0) is the n-th slot in use, or 0 past the last.
- **Reset** (0x00249828) empties the list and adds `GRID_BLUEPRINT1` and
  `GRID_BLUEPRINT2`.

The event tree's car-logo slideshow (0x001f8e18) adds each event car's
`CARLOGO_` texture and resets the list on each new event and on close
(`eventtreeview.c`'s `keepTexture` and `releaseKept`). Its own screen has
no blueprint objects. Because the list is reset before the next screen's
Reset, a logo never reaches the blueprint in practice.

## Changing screen

`FlailerScreenList::ChangeToScreen` (0x0016c4c0) calls ChangeScreenHash
(0x00249a40) after Activate. It passes the screen config's first Flailer
hash (`+20`), or 0 when the name is NULL. When a name cannot be found,
there is no call.

ChangeScreenHash stores the hash. For 0 it drops the three objects.
Otherwise it finds them on the screen, as bitmaps, runs Reset, and sets
GridTimer.

## Reset (0x00249888)

When both blueprint objects are there:

1. It draws three values with RandomRange (0x00249570): x0 in 160..165,
   y in 180..300 and x1 in 300..400. RandomRange is
   `bRandom(10000) * 0.0001 * (hi - lo) + lo`, on bDefaultSeed (gp-14472),
   which is the port's `bViewSeed`. The demo's x0 was 180..200.
2. Both objects go to alpha 0. The master stays hidden from then on.
3. The fading one is centred on (x0, y). Its spline is set there and
   snapped, with both lanes still, then aimed at (x1, y).
4. Both durations are set to 50 seconds. The demo used 20.
5. One of the kept textures, picked by `bRandom(Count)`, goes on the fading
   object.

Whether or not the objects are there, CrossFadeTimer is set to RealTimer.

## Tick (0x00249ae8)

FlailerScreenList::Tick (0x0016cca8) runs it after the song monitor, but
only in game flow state 3, IN_FRONTEND. Each tick:

- It sets both durations to 50 and advances AnimationParam.
- Without both objects, it stops there.
- Otherwise, t is `(float)(RealTimer - CrossFadeTimer) * 0.00025`, in
  seconds:
  - Below 1 (CrossFadeTime, gp-15004), the fading object's alpha is
    `(int)(t * 128)`, a fade in to full over the first second.
  - Below 50, the spline seeks by RealTimeElapsed and the object is centred
    on it. The ease takes 50 seconds from x0 to x1.
  - Between 49 and 50, the alpha is `(int)((1 - (t - 49)) * 128)`, a fade
    out over the last second.
  - Past 50, Reset starts the next drift with another texture.

t is never exactly 49 or 50 seconds. A whole number of ticks times
0.00025f steps from 49.99975 to 50.0000038.

None of the constants (gp-15004 1.0, gp-14996 50.0, gp-26476 6.283,
gp-26472 0.00025, gp-26480 0.0001) is written anywhere in the image.
SwitchImageTime (gp-15000, 5.0) is never read.
