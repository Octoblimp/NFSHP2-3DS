# Car select (step 16, SC-1)

Every race setup leads to car select: You're The Cop's Setup, a single
race, the championship, and two players. It is retail's SelectCarScreen
and CarSelector (`SLES_507.31`), which the demo disc has only in part.
SC-1 ports them as logic and 2D in `bcarsel.c`. SC-2 adds the car in 3D:
its camera (`selcam.c`), the car and its reflection (`fecar.c`) and
their light (`elight.c`). SC-3d adds the nebula behind it.

| class or function | address | port |
|-------------------|---------|------|
| VisibleCar, SetSkin, NextSkin, PrevSkin | `0x00194250`, `0x001942d0`, `0x00194350`, `0x00194380` | `carInit`, `carSetSkin`, `carNextSkin`, `carPrevSkin` |
| VisibleCarSet, its copy, GetNextCar, GetPrevCar | `0x001944e8`, `0x001943d8`, `0x001943a8`, `0x001943c0` | `bcarsel_set_init`, `bcarsel_set_copy`, `bcarsel_next_car`, `bcarsel_prev_car` |
| CarListSort | `0x00194728` | `carListSort` |
| the preload, its unload | `0x00194898`, `0x00194a00` | `bcarsel_preload`, `preloadUnload` |
| InitSelectCarScreen, CloseSelectCarScreen | `0x00194fa8`, `0x00194fb0` | `bcarsel_init_screen`, `bcarsel_close_screen` |
| the unlock box (no name in the image) | `0x00194a88` .. `0x00194f30` | `unlock*` |
| CarSelector | `0x001950d0` .. `0x00198290` | `sel*` and the rest |
| SelectCarScreen | `0x00198420` .. `0x00198b00` | `screen*`, `maybeContinue` |
| SelectCarScreenCallback | `0x00198928` | `bcarsel_screen_callback` |
| feAlphaAnimation | `0x00248360` | `fade*` |
| AnimationGroup (retail's) | `0x00248568` | `slide*` |
| FormatUnlockBlurbForCar | `0x0024b548` | `nfs_format_unlock_blurb_for_car` (`nfsrewards.c`) |
| FrontendDatabase::UseTreeEvent | `0x001841e8` | `useTreeEvent`, inline |
| the nebula's AcidEmitter constructor, UpdateNebula | `0x001956e8`, `0x001963b8` | `nebulaNew`, `updateNebula` |
| FlailerScreenList::SetEmitterState | `0x0016c3b0` | empty, left out |

Everything outside the selector and the Flailer goes out through
`BCarSelHooks`, which `main.c` fills. Each hook's comment in `bcarsel.h`
names the retail function it stands for.

## The screens

FRONTB has two FlailerScreenConfigs for car select:

| hash | name | |
|------|------|-|
| `b5074ab4` | Select Car | one player |
| `18dc8e52` | Select Car2P | two players, entered once a pad |

The swatches and the thumbnail row also know `18dc8e53`, a third layout
that no config on the disc names. The popups go on `41c2fdc3` for one
player and `6344da01` and `6344da02` for the two halves.

The one menu item is `52e039f3`, CHOOSE, which SELECT goes through.

### The objects

By NameHash, or GroupHash for the groups:

| hash | object |
|------|--------|
| `0015678f` | fade group A: out as the orbit view comes in |
| `036e80bf` | fade group B: in with the orbit view |
| `0961a600` | fade group C |
| `75c8b565` | the black over the car, its alpha the fade |
| `abb370a6`, `84f544f3` | the next and previous arrows |
| `736163fc` | "NFS Points n" |
| `09b562fd` | "Cars Unlocked n/m" |
| `0c0384cc`, `e6882001`, `e79e7936` | top speed, 0-60 and BHP |
| `02920d75`, `d8b0bab5` | the class and its label |
| `c86209a4` .. `c86209a6` | three more of the info bar, shown and hidden with it |
| `39e91754` | the car's name |
| `b270d4a5` | the make's logo, `CARLOGO_` and the name |
| `729a0c4b` | the two-player badge |
| `edf2e4ee`, `20d73d01`, `7fe46db3` | the swatch column's top, bottom and ring |
| `SWATCH_0` .. | one swatch a skin |
| `THUMBNAIL_` + CarTypeName | each car's thumbnail |
| `THUMBNAIL_CLOAK_0` .. `_24` | the cloaks over covered cars |
| `2561a343` | the lock before the first locked thumbnail |
| `6a096871` | the unlock box's group |
| `a8af730b` | the box, the group's master |
| `bea3c79c` | the box's fade |
| `2a67e2d5` | the blurb's font, never shown |
| `2a65daf9` | the rectangle the blurb is wrapped into |

Fade group A has 102 objects on the one-player screen, and 98 and 103
on the two halves. `BCARSEL_MAX_FADE` is 128. It was 48 until the
checker found most of the thumbnail row never fading out in the orbit
view.

## The cars

**VisibleCarSet** is a player's cars: every car type whose status is
not hidden, or every one when `AllCarsAvailableInCarSelectScreen`
(gp-23120, 0 on the disc) is set. A car is available when its status
is available, or when an easter egg makes it so. For You're The Cop's
player one the egg test asks for cops only. The current car is the one
the player's RideInfo for this game type names, in its skin. Otherwise
it is the first in the list.

The port keeps the cars in the set, a slot a car type, where retail
mallocs them. A copy keeps the list's order.

**CarListSort** builds a key for each side:

- `0x40000000` for a car not available;
- `0x01000000` for a cop;
- the high performance flag, shifted 16;
- `5 − class`, shifted 8;
- 1 more on a's side when a's full name sorts after b's by bStrCmp.

It answers `!(kb < ka)`. The name only breaks a tie one way, so two
cars of the same name keep their order. bStrCmp compares signed bytes
and answers the difference where they part. Each car is then numbered
by its place.

## The unlock box

A locked car shows a box saying how to unlock it. It is retail's own
class, 360 bytes, with no name in the image.

- **SetCar** (`0x00194b28`) does nothing for the car it already has.
  For an available car the group and the fade are hidden and the state
  is 0. Otherwise they show and the state is 2. Then the blurb is
  written, and the box slides on from X 650 to its own X.
- **The flag** FormatUnlockBlurbForCar is handed is `port == 1` from
  both callers. The ScreenCallback writes it `(port ^ 1) < 1`, with the
  `sltiu` in the call's delay slot. The port first read it as
  `port ^ 1`. The checker caught that on You're The Cop's locked cars.
- **The tick** takes `t` as the seconds since the slide began, at
  0.00025 a RealTimer tick. After 0.4 s the slide moves, and the fade
  comes up over the next 0.5 s.
- **Hidden** (state 1): pressing CHANGE_MODE on a locked car hides it,
  with sound 5. Any press brings it back, and so do the screen's own
  SELECT, the four directions and BACK. Those take the press, and the
  noise is 5.
- **The render** wraps the blurb into its rectangle when the box shows.

### FormatUnlockBlurbForCar

In order:
1. A task's reward: the task's blurb, through bSPrintf as the format.
2. You're The Cop with the flag 0: "Be A cop Player 1 -- should not see
   this message".
3. An event's reward: the championship's or Hot Pursuit's blurb, with
   the event's number, a signed byte.
4. A points reward: the blurb with the points, grouped by the
   language's separator.
5. Else "This car should be unlocked".

`main.c`'s `findEventForCar` asks the event trees (`eventtree.c`,
[event-tree](event-tree.md)) for the event a car is a reward for: its
tree's type and its number.

## The selector

CarSelector is 1024 bytes in retail. `bcarsel.h` keeps retail's offsets
in its comments.

**The constructor** (`0x001950d0`) copies the set and makes the three
fade groups and the unlock box. It loads the current car, sets the
unlock box's car, the logo, the info bar, the help and the swatches,
and sets the fade to its most, 130. Then it sets up the thumbnails,
writes the points and ticks once. The turntable starts at tilt 15712,
FOV 7236 and angle 16123.

**The tick** (`0x00196d58`):
1. The car asked for, loaded, becomes the loaded car. It is shown if it
   is still the one chosen.
2. Another car chosen, with the fade at its most and the thumbnail row
   at rest: the old car is unloaded and the new one loaded.
3. The loaded car chosen: the fade falls 3 a tick to 0. Otherwise it
   rises 7 a tick to 130.
4. In the orbit view, untouched for more than 2400 RealTimeFrames (40
   s), back to choosing.
5. The turntable turns 46 a tick while choosing, or in an orbit view
   nobody has touched.
6. The shown mode moves 0.03 a tick toward the mode.
7. The fade groups, the unlock box, the arrows, the swatches and the
   thumbnails.

**The fade groups**: A at `1 − min(3 × shown, 1)`; B at the shown mode,
or 0 for a cop; C at 0 in the orbit view, and back to 1 once choosing
with the shown mode under a third.

**The swatches** sit at (587, 125) on one player's screen and (606, 77)
and (606, 321) on the halves, 18 apart, the ring 4 up and left of the
skin worn. With fewer than 2 skins, or a covered car, none show.

**The thumbnail row** is a spline whose target is `base − index × 39`,
less the lock's width for a locked car. The base is 377 for one player
and 395 for two. Each thumbnail is 39 to the right of the one before,
at y 402, 25 or 265. The lock goes before the first locked car after an
available one, and every later thumbnail moves right by its width. A
covered car shows the next of the 25 cloaks.

A car is **covered** when it is not available and its status is 4, a
car still to be won. Its name, logo, info bar and swatches are hidden.

**The logo** is `CARLOGO_` and the car's name. For two players a high
performance car drops the name's last two letters (SPIDERHP is
SPIDERHP2P), and the five cops take their plain model's logo. The badge
shows only for two players: LOGO_SHERIFF for a cop and LOGO_NFS for a
high performance car.

**The info bar** shows top speed in the units' figure, 0-60 and BHP,
each with "+" or "-" for a high performance car, and the class + 1. Each
figure is translated before its unit, as retail calls them. A cop or a
covered car hides all eight objects. "Cars Unlocked" is hidden when the
game type runs off the event trees.

**UseTreeEvent** is game types 8 and 9, the single race and the
championship. It used to be a hook main.c never set.

**The JoyHandler** (`0x00196958`) first lets the unlock box see the
press. Then, only while choosing:
- CHANGE_MODE, pressed, one player, the fade at 0: into the orbit view
  when the help menu is down, the car is available and the selector is
  choosing; back out when already orbiting.
- The orbit's directions set the camera's speeds: ±9000 left and right,
  ±10000 up and down, and the sticks `(v − 128) × 70.3125` and
  `(v − 128) × −78.125`. Each touch marks the view and restarts its
  clock.
- Event 34 would set the selector's c[76], every car open, when
  `0x0016fdb0` says so. That function returns 0, so c[76] stays the
  constructor's 0 and the port leaves the case out.

**The popups**: SELECT on an available car moves to the gearbox
(automatic, manual, the third), then the handling (two), then, for two
players, a wait for the other player. Cancel goes back a step.
AreAllSelectorsReady is one player at the handling, or two at the wait.
Then SetSelectedCars writes each player's car, skin, gearbox and
handling, and the game goes to the race (game types 8 and 9) or to
Select Track.

## The checker

`tools/carsel_check.py` runs retail's SelectCarScreenCallback, the
JoyHandler's bridge (`0x00198e28`), the preload and
CloseSelectCarScreen in mipsemu on the retail image. It runs them over
FRONTB's Flailer chunk and GLOBALB's car records and skins.
`tools/src/carsel_test.c` runs `bcarsel.c` over the same files.

The stubs are scripted the same on both sides and log in the same
words: the translations, the sounds, the help, the popups, the screen
changes, the CarLoader, the easter eggs, the event trees, the text in
its rectangle, the commentary and AssignCarOfType. The 3D's stubs are
SC-2c's (its "The checker" below). The spotlights are silent. The
nebula runs as shipped over logged effect-system calls (`acidfx.md`,
"The car select's nebula (SC-3d)").

After each message, joy event, preload and close, every line that
changed is printed:
- the screen and each selector's fields;
- the car list in order;
- the unlock box, the thumbnail spline and the swatches;
- both rendering cars, the camera's fields and the frame buffer;
- the preload's two cars and the CarLoader's flags;
- both players' gearbox and handling;
- every Flailer object's bytes;
- the nebula's emitters, every byte, and its data's colour keys.

The script runs You're The Cop with one player, a single race in
French with kilometres, the championship in German, and two players on
both halves. It goes across locked, covered, egged and hidden cars and
every skin. It takes the orbit view in and out, including its timeout
at exactly 2400 frames and at 2401. It hides the unlock box and brings
it back, and runs every popup and every way out of it. It also covers
the help menu up, both units and all three languages. The nebula's
data is found by every emitter, by none, and by all but every third,
and its shade goes to a locked car's red and back.

The model is slow: a tick costs about 170 ms in mipsemu, most of it
retail's bSPrintf and FindFlailerObject for the 25 cloaks. The whole
script takes about eight minutes. The mutation pass runs the model once,
and keeps its transcript for the next pass as long as the checker above
its mutations and the sources are unchanged. The mutants build from a
snapshot of the sources and run sixteen at a time (tools/mutpar.py);
the whole pass takes about twelve minutes.

At SC-1 the script was 7282 ops and 430239 lines, with 0 differ. The
mutation pass caught 196 of 201 mutations. The other five can't change
the transcript:
- `slide-init-start`: the constructor's unlockSetCar sets the slide up
  again from 650 before anything reads it.
- `unlock-render-avail` and `unlock-joy-avail`: the box is at state 2
  only with no car or a locked one.
- `badge-1p`: "Select Car" has no BADGE object, so the one-player badge
  goes nowhere.
- `thumbs-hide-all`: car 63, the FIRETRUCK, has no THUMBNAIL_ object on
  any of the three screens.

## The turntable camera (SC-2a)

`selcam.c` is retail's SelectCarCameraMover, camera mover type
CM_SELECT_CAR, from CameraMover.obj.

| function | address | port |
|----------|---------|------|
| the constructor, the destructor | `0x0015a698`, `0x0015a880` | `selcam_init`, `selcam_destroy` |
| the setters | `0x0015a940` .. `0x0015a9f8`, `0x0015fab8` .. `0x0015fad8` | `selcam_set_*`, `selcam_get_mode_param` |
| SetMode | `0x0015aa08` | `selcam_set_mode` |
| Update | `0x0015abb0` | `selcam_update` |
| MyQuaternionMultiply, NormalizeQuaternion | `0x0015aab0`, `0x0015ab58` | `selcam_quat_multiply`, `selcam_quat_normalize` |
| Slerp | `0x001a7280` | `selcam_slerp` |
| the vtable | `0x002b1950` | `SelectCarCameraMoverVtbl` |

The mover blends between two views of the car:
- **The stats view** is still. SetOrientationStats gives its heading
  and tilt. It sits RadiusStats from the car and looks past
  OffsetStats.
- **The orbit view** turns. The selector's sticks set three desired
  speeds: round the car, the tilt and the distance. The car select
  sets the radius to 7.25, the offsets to (0, 0, 0.55) and (0, 0, 0.4),
  the stats heading and tilt to 0x2200 and 0x0900, and the orbit's
  tilt to 0x0c00.

Each frame, Update does this:
1. It moves each speed toward its desired one, at 45000, 23700 and
   17.02 a second, never past it.
2. It turns Blend into t = 1 - (cos(Blend * pi) + 1) / 2, kept within
   0 to 1.
3. When Blend is exactly 0, the orbit starts over: the tilt at 50000,
   the radius at 13.2, and the orbit's quaternion from the stats
   heading.
4. In the orbit, it spins the orbit's quaternion about z. Every 60th
   frame of a counter that all movers share (gp-21664), it then
   renormalises the quaternion.
5. It slerps from the stats view's quaternion to the orbit's by t, and
   moves between the two offsets by t.
6. In the orbit, it moves the tilt and bounces it off its stops, 0xebab
   and 0xc34f. Past the bottom, the tilt goes back to 50000. The speed
   turns round at 0.165 of itself.
7. It tilts by the stats tilt plus t times the difference.
8. In the orbit, it moves the radius between 10.95 and 15.5 and bounces
   it the same way.
9. Also in the orbit, it sets the hum. Its volume follows the fastest
   of the three speeds, each scaled, and its pitch falls as the camera
   backs off.
10. It backs off by RadiusStats plus t times the difference to the
    orbit's radius.
11. It walks Blend 0.03 toward the mode.
12. Unless Camera::StopUpdating is set, it gives the camera a field of
    view of 4500 and the distance as its target distance. Then it sets
    the camera's matrix.

A bounce plays the bump sound at 0.0006 of the new tilt speed, or 0.8
of the new radius speed, when that is over 0.107.

The four sounds are bSamples. They are made only while SoundEnabled
(gp-23056) is set:
- `MenuCarDisplayOn`;
- `MenuCarDisplayOff`;
- `MenuCarDisplayActive`, the orbit's hum;
- `MenuCarOrbitBump`.

SetMode(0) plays Off and stops the hum. SetMode(1) starts the hum at
volume 0 and plays On. The port sends them through `gSelCamSound`,
which SC-2d fills.

Retail's quirks, kept:
- Slerp is not bQuaternion's bSlerp. When the two quaternions point
  apart, it negates the first in place. When they are within 0.05 of
  opposite, it overwrites the second with one at right angles to the
  first. Both writes land in the mover.
- FOVStats and FOVOrbit are stored and never read. The field of view
  is always 4500.
- The constructor never writes the two quaternions. The stats view's
  comes only from SetOrientationStats.
- NormalizeQuaternion has no guard against a zero length.
- SetMode, the bumps and the hum test SoundEnabled, not whether the
  sample was made.

`tools/selcam_check.py` runs retail's constructor, destructor, Update,
setters, SetMode and the three helpers in mipsemu. Retail's CameraMover
base, Camera::SetCameraMatrix and matrix layer run under them, over
retail's own eView table. `tools/src/selcam_test.c` runs the port over
the same script. On both sides the sound is a recorder, and every camera
and mover starts from a byte pattern.

The script covers:
- construction and destruction, with and without sound;
- every setter at its edge values;
- SetMode's sounds, and a mode that is neither;
- the car select's flow: the stats view, into the orbit, the sticks
  against every stop, and back out;
- the stops hit exactly, the counter at its turns, odd and NaN blends,
  a frozen camera and no time;
- two movers sharing the counter;
- Slerp at every branch, off the unit sphere and with NaNs;
- three random walks of 300, 900 and 1500 steps.

It is 11 scenarios, 4266 ops and 52296 lines, with 0 differ. The
mutation pass catches 141 of 143. The other two can't show:
- `dtor-vtbl`: the base's destructor puts its own vtable in straight
  after.
- `upd-pos-pad`: eTranslate takes only x, y and z.

## The turntable car (SC-2b)

`fecar.c` is retail's FrontEndRenderingCar, a car the frontend draws,
from CarRender.obj. `elight.c` has the car select's lighting.

| function | address | port |
|----------|---------|------|
| FrontEndRenderingCar's constructor, ReInit, deleting destructor | `0x0011e5c0`, `0x0011e758`, `0x0011e7d8` | `fecar_init`, `fecar_reinit`, `fecar_delete` |
| RenderFrontEndCar | `0x00123c90` | `render_front_end_car` |
| RenderFrontEndCars | `0x00123d28` | `render_front_end_cars` |
| SetSelectCarLighting | `0x001157c0` | `el_set_select_car_lighting` |
| elSetupLightContext, its frontend branch | `0x00115978` | `el_setup_light_context` |

### FrontEndRenderingCar

The car select has two of these: the car and its reflection. Each one
is 648 bytes and has these parts:
- It is on FrontEndRenderingCarList (gp-23656) and belongs to one view.
- It holds its own copy of a RideInfo, and a CarRenderInfo built from
  that copy with no Car.
- Its owner sets its body, tyre and brake matrices.
- It can hold an eModel of its own, drawn instead of the car.

The constructor sets up a ride of type -1 with the rest 0, and hands the
given ride to ReInit. Then every matrix is the identity, the position is
0, Enabled is 1, and the car joins the list at its tail. ReInit deletes
the CarRenderInfo, if any. With a ride, it copies the ride and builds a
new CarRenderInfo from the copy, from bMalloc's pool 16. The destructor
waits for the renderer and deletes the CarRenderInfo and the eModel,
each with flags 3. Then it leaves the list, and with bit 0 of its flags
it frees the car.

`RenderFrontEndCars(view, cars, reflections, pass8, pass16)` draws every
enabled car of the view that has a CarRenderInfo:
- **A reflection** draws only when `reflections` is set and the view
  mode is 1. Its flags start at 17: flag 1 is no environment map.
- **Any other car** draws when `cars` is set, and its flags start at 0.
- **Flag 8** joins when `pass8` is 0, and **flag 16** when `pass16` is.
  Either also joins when its force flag (gp-23596, gp-23600) is set.
  RenderStrips (`0x0010de10`) reads them: flag 16 skips a solid's
  alpha strips, and flag 8 skips its solid ones. So a car can be drawn
  in two halves. The port's renderer doesn't read them yet.
- **A car with its own eModel** draws that with the body matrix, and
  nothing else.
- **Otherwise the car is centred:** it moves in x by the middle of its
  body's bounding box, so it sits in the middle of the turntable.
- **The forced lights:** headlights give 3, the head and brake lights.
  Cop lights add 8. A reflection gets none.

RenderFrontEndCar sets ForceCarLOD and ForceTireLOD to 0, or to 1 for a
reflection, and calls CarRenderInfo::Render. Afterwards it puts each one
back, unless Render changed it.

eDisplayFrame calls RenderFrontEndCars four times a frame. The first
two run only in the frontend (CurrentGameFlowState 3), for views 1 and
2:
- (view, 1, 0, 1, 0) at `0x00112c1c` draws the cars' solid strips
  (flag 16), before anything else in the view.
- The same call at `0x00112d2c` draws them again into the second
  target of the optional antialiasing pass.
- (view, 0, 1, 1, 1) at `0x001136bc` draws the reflections, after the
  platform and the effects.
- (view, 1, 0, 0, 1) at `0x001136d4` draws the cars' alpha strips
  (flag 8). These go in with the platform's and the effects' alpha
  polygons.

None of the four is for the environment map's faces. In the frontend
the cars' environment map is the texture CARSELECTENVMAP (hash
`0x4ecc769c`).

### The lighting

`SetSelectCarLighting(view, locked, bright)` fills one of two light
sets: the second (`0x002d5ff0`) for view 2, and the first (`0x002d5f70`)
for any other. Each set has three lights, each a colour and a direction,
and an ambient:
- **Locked**, the set is dark. The colours and the ambient are black,
  and the directions are (0, 9.38, -5), (-5, 10, 0) and
  (0.307, 10, 2.82).
- **Otherwise it is lit.** The colours are greys of 80 and 64 and a
  bluish (128, 128, 180), each plus `bright * 30`, at most 255. The
  ambient is 32. The directions are (6.82, -6.1, -8.56), (-5, -1, 0)
  and (1.28, -1.17, 1.28).

The tables are filled by eLight.obj's static initializer
(`0x00117098`). The cap at 255 is the EE's `min.s`, which keeps a NaN,
and the port does the same. Retail leaves the lit colours' w lanes and
the ambient's from its stack. The port writes 0 there, and nothing
reads them.

The selector's Tick calls it at `0x0019729c`:
- `bright` is (1 - the swatch's weighted luminance)^4, so a dark paint
  gets brighter lights.
- `locked` is all four of: gp-23120 is 0, c[76] is 0, the VisibleCar at
  c[80] is there and not available, and the status's nStatus is 2.

elSetupLightContext then lights every model with the set, in the view's
space (`docs/formats/light.md`, "In the frontend").

### The checker

`tools/fecar_check.py` runs retail's FrontEndRenderingCar constructor,
ReInit and destructor, RenderFrontEndCars, SetSelectCarLighting and
elSetupLightContext in mipsemu. eLight.obj's static initializer runs
first, to fill the tables. `tools/src/fecar_test.c` runs `fecar.c` and
`elight.c` over the same script. These calls are stubs that print what
they get, the same on both sides:
- bMalloc;
- CarRenderInfo's constructor, destructor and Render;
- eModel's Render, GetBoundingBox (which answers the script's box) and
  destructor;
- eWaitUntilRenderingDone and the free.

The light context runs over an empty light database, or over a pack the
script links in: a root over two leaves, and six lights of every type
and attenuation. Retail leaves a direction on its stack when its point
light isn't near, so the dumps leave out the words it reaches. Each side
asks its own QueryLightDatabase how many are near, and that is printed
too.

The script covers:
- building, rebuilding and deleting cars on and off the list;
- every pass of RenderFrontEndCars, against cars and reflections, with
  eModels, force flags and Render changing the LODs;
- SetSelectCarLighting for every view, locked and lit, at NaN,
  infinite and out-of-range brightness;
- the light context in and out of the frontend, with and without the
  car select, over three views with and without the pack.

It is 7 scenarios, 1439 ops and 13217 lines, with 0 differ. The
mutation pass catches 124 of 125. The other, `rfcs-unused-arg`, can't
show: RenderFrontEndCar never reads its seventh argument.

## The selector's 3D (SC-2c)

The selector drives the camera, the two cars, the cover, the platform
and the light from its constructor, Tick, RENDER and destructor.

| function | address | port |
|----------|---------|------|
| UpdateCarCover | `0x00195c40` | `updateCarCover` |
| UpdateRenderingCarParameters | `0x00197ce0` | `updateRenderingCarParameters` |
| ShowLoadedCar | `0x00197ff8` | `showLoadedCar` |
| the Tick's light | `0x001970b0` .. `0x0019729c` | `updateLighting` |
| InitSpotlights, UpdateSpotlight | `0x00194fd0`, `0x00196038` | not ported |

Retail bMallocs the two cars and the camera mover and keeps pointers to
them at c[36], c[40] and c[188]. The port keeps them inside the
selector.

**The constructor** adds these, after the joy handlers:
- Two FrontEndRenderingCars for view `playerNum`, with no ride. The
  second is the reflection, with Reflection and Enabled at 1.
- The CARCOVER eModel at c+44, which is Init'd from its name's hash
  only while it has no Solid.
- The SelectCarCameraMover, for view `playerNum`.
- SetSelectCarLighting(playerNum, 0, 0.0), after the info bar.
- The PLATFORM eModel at c+164, after the help, also only while it has
  no Solid.
- The cars' headlights and cop lights (c[380], c[384]), at 0.

**The Tick sets the camera** every frame, after the turntable turns:

| | one player | two players |
|-|------------|-------------|
| RadiusStats | 12.93 (gp-20040) | 16.5 (gp-20036) |
| OffsetStats | (0.27398, 0, -0.53), `0x00310200` | (-0.62, 0, -1.05), `0x003341c0` |
| tilt | 15262 (gp-20044) | 15654 |

Both use OffsetOrbit (0, 0, -0.6384) at `0x003341b0`, heading 0
(gp-20108) and FOV c[226]. selectcar.cpp's static initializer
(`0x00198bc8`) writes the three offsets. After the shown mode, the Tick
calls UpdateRenderingCarParameters for the car with 0 and the
reflection with 1. Then come the fade groups and the light.

The camera's mode follows the selector's. Going into the orbit view
sets it to orbit. Going back to choosing sets it to stats, by the
button or by the timeout. The JoyHandler's directions set the mover's
DesiredHorizSpeed (+152) and DesiredVertSpeed (+160).

**UpdateRenderingCarParameters(car, reflection)** does nothing without
a loaded car. With one:
- The body sits at (0, 0, z). z is the first wheel's radius less its
  height, plus 0.01 (gp-23740). A reflection sits at −z.
- The body matrix is the identity, turned in Z by the turntable's
  angle. A reflection's has the X axis's y and the Z axis's z negated
  first.
- Each wheel's tyre and brake matrices are the identity at the wheel's
  place on the car. Retail turns the tyre in Y by 0. The front two are
  turned in Z by `(1 − Blend) × 4240` (gp-20106), truncated: steered in
  the stats view, straight in the orbit.
- The car's Headlights and CopLights come from c[380] and c[384].

gp-20106 is not past 0x8000, so retail's other blend, for an angle
that is, never runs. The port leaves it out.

**UpdateCarCover** puts the CARCOVER model on both cars while the chosen
car is covered, and takes it off otherwise. RenderFrontEndCars draws a
car's own model in place of the car.

**ShowLoadedCar** ReInits both cars with the loaded car in the skin it
wears, instance 0, no dash. Retail also asks GetSkinInfo for the skin
and drops the answer.

**The light** (`0x001970b0` .. `0x0019729c`):
- The swatch is the first with one skin, or the one worn.
- GetTextureInfo gives its colour texture, with the default allowed.
- On a car that isn't covered, with the texture loaded, the colour is
  the palette's entry for the fourth texel. Loaded means it has an image,
  and palette data unless its palette's size is 0. Retail then reads the
  palette anyway, so a texture with no palette size still lights the
  car. One with no palette data at all would have retail read from
  address 0. The port tests for an image and palette data, and gives
  that texture no light.
- `bright` is `(1 − (0.299 r + 0.587 g + 0.114 b) / 255)^4`, and 0
  otherwise.
- `locked` is as "The lighting" above has it.

**RENDER** frame-mallocs a matrix, sets it to the identity and draws
PLATFORM with it, with no light context and flags 0. With no frame
memory left it draws nothing. Then the unlock box draws its blurb.

**The destructor**, after the popup:
1. UnInits the platform if it has a Solid.
2. Closes the swatches, runs the preload twice and unloads the cars.
3. Takes the cover off both cars, whose destructor would delete it.
4. Deletes the camera, the car and the reflection.
5. UnInits the cover if it has a Solid.
6. Stops sound 12 and puts the slide back.
7. Destroys the platform's model, puts the three fades back and
   destroys the cover's.

**The spotlights are dead code.** InitSpotlights copies BRUSHEDMETAL's
alpha and colour channels into gp-20084 and gp-20080, and nothing reads
them. UpdateSpotlight is empty. The constructor's two buffers the size
of the spotlight's (c[316], c[320]) and its two 1.0s (c[324], c[328])
are never read either. The port has none of them.

**On the device nothing draws yet.** render_model returns outside the
race's draw, and gElInFrontendFn and gElCarSelectActiveFn are still
NULL. ShowLoadedCar does build the two CarRenderInfos, and the light
table is set every tick. SC-2d draws them.

### The checker

`carsel_check` covers all of it. Its 3D stubs log the same on both
sides:
- the FrontEndRenderingCars' constructor, which only clears and keeps
  the view, ReInit and destructor;
- the camera's constructor, destructor and SetMode, and its five
  setters, which keep what they are given;
- eModel's Init (its Solid scripted), UnInit, destructor and Render;
- SetSelectCarLighting;
- GetTextureInfo, which answers each swatch with a texture made from
  its hash, or with nothing, no image, no palette size or no palette.

UpdateRenderingCarParameters, UpdateCarCover, ShowLoadedCar, the light's
sum, eIdentity, the rotations and the frame-malloc run for real, over
a scripted buffer. Retail's static initializer runs first, with
FlailerScreenConfig's constructor stubbed silent. The dump adds both
cars (flags, model, lights, place and every matrix), the camera's
fields and the frame buffer.

The script adds:
- the camera's blend at 0.5, 1, 0.3 and 0, for one player and two;
- the platform with no frame buffer, one just too small, room for one
  and room for two;
- each kind of missing swatch texture;
- two locked cars, one lit by an easter egg;
- models with no Solid.

The whole script is now 7373 ops and 459051 lines, with 0 differ. The
light needed one more kind of car list: the old kinds never listed a
hidden car with AllCarsAvailableInCarSelectScreen set, so a mutant that
dropped the cheat from the light's test survived. The cheat's
single race now lists every status, and its ride is a locked car.

The mutation pass catches 264 of 273 mutations. Nine can't change the
transcript: SC-1's five above, and four of SC-2c's:
- `urcp-flip-y`: the identity's v0.y is 0, and eRotateZ's sums lose the
  sign of the -0 the flip makes.
- `urcp-tire-roll`: eRotateY by 0 multiplies by an exact identity, since
  the table's sine of 0 is 0 and its cosine 1.
- `urcp-wheel-w`: eIdentity has already put 1 in the brake's v3.w, and
  eRotateZ leaves row 3 alone.
- `light-one-skin`: SetSkin, NextSkin and PrevSkin can only leave a
  one-skin car's index at 0.

## The draw on the device (SC-2d)

SC-2d draws SC-2c's cars, cover and platform on the top screen, under
and over the selector's Flailer layers, as retail's frontend
eDisplayFrame (`0x00112c1c`) does. Nothing in it changes what the
selector, the cars or the camera do, so it has no checker of its own.
It is the device's half: what the checkers' stubs stand for.

### FRONTB's engine half

Retail's BeginGameFlowLoadingFrontend loads `FRONTEND\FRONTB.LZC` as a
ResourceFile: every chunk goes through LoadChunks, then PostLoadFixup,
before the flow's callback. The device has read FRONTB at boot, for the
UI, and keeps it. `frontres.c` puts that copy through the same two
calls when the flow asks for the file (main.c's `hookLoadResource`).
FRONTB's top-level chunks:

| chunk | what | loaded by |
|-------|------|-----------|
| `0x80034000` at offset 0, 1,499,656 bytes | the solid list: PLATFORM, the fifteen TRACK*_MINI and CARCOVER | `loader_solid_list`, on a fresh copy |
| `0xb0300001` | the texture pack, 12.5 MB | `loader_texture_pack`, in place |
| `0xb0300100` | the anim pack | in place |
| `0x80010200` | the Flailer chunk | a slot not ported: the UI has it |
| `0x80034a00`, twice | the event trees | `loader_event_tree`, in place ([event-tree](event-tree.md)) |
| `0x15010`, four times | the fonts | not ported: the UI has them |

`loader_solid_list` fixes its tables up in place, and can't do it twice.
Each load takes a fresh copy of the chunk, `memalign`ed so that it sits
as far into its first 128 bytes as it does in the file. That keeps what
the chunk aligns inside itself aligned. The unload runs UnloadChunks
newest chunk first, as TraverseChunksBackwards does, frees the copy and
runs PostLoadFixup again.

The unload is BeginGameFlowUnloadingFrontEnd's loop over
FindResourceFile(1) and UnloadResourceFile. The flow reaches it through
a new hook, `unloadFrontEnd`, after `closeSelectCar`. It isn't traced,
so `bootflow_check` and `bscreens_check` are unchanged.

### The frontend's view

The race's track viewer (`trackview.c`) already turns eModels into
citro3d draws. The frontend gets a second TrackView, `g_feView` in
main.c, which `trackview_attach_frontend` sets up with no track: it
has only the tables for the other solids and for the textures, and no
cull info. It is attached the first time car select draws with FRONTB
loaded.

Its solids and textures are found as they are drawn, as the race's
other solids are. A track's solids keep pointers into its textures; the
frontend's don't have to, so the frontend's view can forget all of
them at once:
- `trackview_forget_later` asks for it when a resource file or a car's
  textures are unloaded (`resUnloadFile`, and `unloadTexturesFromFile`
  in place of `gUnloadTexturesFromFileFn`). Another car can be loaded
  where the old one was.
- `trackview_free_later` asks for it when FRONTB is unloaded, and frees
  the tables too.
- Both happen in `trackview_frame_begun`, called right after
  C3D_FrameBegin, which has waited for the GPU to finish the last frame.

A texture whose TextureInfo has no image yet, a car's that is still
loading, is tried again on the next draw. One that had an image and
failed (no room, or the upload) is not.

### The draw

`trackview_draw_frontend(view, render, user)` is eDisplayFrame's
frontend path for view 1 (Player1Camera, which the
SelectCarCameraMover moves). It returns false, and draws nothing, until
the view is attached and there is frame memory.
1. A new frame's memory, MaybeChangeViewMode, and the view's matrices
   from its camera. The frontend culls nothing.
2. The race's projection, light and seams (`gEModelRenderFn`, the strip
   functions), the fog off, the near and far planes, depth writes on.
3. The environment map is CARSELECTENVMAP (`pTextureInfoCarSelectEnvMap`,
   set by eFixUpTables), where the race's is target 14. elSetupLightContext's
   frontend branch makes this choice. `georender_set_env_texture` puts
   that texture in the sphere map's place for the draw.
4. `render_front_end_cars(view, 1, 0, 1, 0)`: the cars' solid strips.
5. The selector's RENDER: the platform, and the unlock blurb.
6. AttachSolidPolys.
7. `render_front_end_cars(view, 0, 1, 1, 1)`: the reflections, then
   `(view, 1, 0, 0, 1)`: the cars' alpha strips.
8. AttachSolidPolys, then AttachAlphaPolys.
9. UpdateTextureAnimations, and the alpha test and blend left as citro2d
   wants them.

Retail's frontend draws view 0's Flailer layers 24 to 20 between steps
4 and 5. Those layers don't write depth, so the port draws them first,
and steps 4 and 5 land over them the same. `uirender_draw_visible_passes`
draws a range of BUI_LAYER_ORDER, whose first UIR_BACK_PASSES (5) passes
are layers 24 to 20. main.c's `drawCarSelTop` draws those, flushes
citro2d, draws the 3D, prepares citro2d again, and draws the rest of the
layers. The nebula's sprites, between steps 5 and 6, are FrameEffects'
RenderEffects (`acidfx.md`, SC-3c and SC-3d).

**The strips' passes.** RenderStrips' flag 16 leaves out the strips
whose texture has ApplyAlphaSorting, and its flag 8 leaves out the
others. `render_front_end_cars` adds 8 when its `pass8` is 0 and 16
when its `pass16` is 0; a reflection starts from 17. The track viewer's
`render_model` now tests both, for every eModel it draws.

**The blurb.** RENDER reaches the unlock box's blurb inside the 3D,
where citro2d can't draw. While the 3D draws, `hookCarSelRenderText`
queues the blurb (one, of up to 255 characters, CarSelector's size),
and `drawCarSelTop` draws it after the layers. If the 3D can't draw,
`drawCarSelTop` sends RENDER itself after the layers, as before SC-2d.

**The camera.** MainLoop's UpdateCameraMovers runs in every frame. The
port's race frame already ran it; frames in the frontend now do too,
which is what moves the SelectCarCameraMover.

**The fog off.** `georender_set_fog(NULL, …)` bound NULL to texture
unit 1. citro3d's C3D_TexBind reads the type of what it is given for a
unit past 0, so this read address 12. Azahar logs that as an unmapped
read; on the device it is a data abort. The race has done this at
the end of every frame since the fog became a texture. The car select
did it from its first frame. Unit 1 now gets an 8×8 A8 texture of its
own, which no stage reads.

### On Azahar

`tools/run_azahar_carsel.ps1` walks car select: the cop cars, right
twice, left, a skin, the transmission popup, cancel and back. Its
verdict now counts Azahar's unmapped reads as a failure, and finds the
selector's lines, which are `flow carsel …`.

The run is clean: no unmapped reads, and the flow leaves the main loop.
- The Crown Victoria stands lit on the platform, with its reflection in
  the floor, under the name and over the grid. 60 FPS, about 4 ms a
  frame.
- The two locked cars, the BMW M5 and the Mustang, are their own models
  in the dark, behind the LOCKED box.
- Back on the Crown Victoria, the turntable has turned it to show its
  side and then its back.
- The transmission popup dims the car with the rest.
- Back returns to You're The Cop's setup with the car select's 3D gone.

Not done here: the spotlights (dead code, above) and the frontend's
other eModels. TRACK*_MINI is the track select's.

## A Local Wireless race (TASKS 67)

A Local Wireless race has `Fred.NumPlayerCars` 2 for its consoles. The
host's setup sets it (Players reads Local Wireless), and so does a
client's `lobbyStarted` in main.c. Each console still has one player,
who chooses on "Select Car", the one-player screen (`lobby.h`'s
`LOBBY_NEXT_SCREEN`).

Retail's 2 means two pads. Until Session 128, car select took it that
way here, and ran the two-player selector on the one-player screen. A
friend's photo from a 3DS (2026-10-15) showed it:
- the thumbnail row's base was 395, the two-player one, not 377, so each
  icon stood 18 pixels right of its box, half an icon;
- the camera was the two-player one;
- there was no orbit and no nebula, and the help, logo and badge were
  the two-player ones.

`consolePlayers()` in `bcarsel.c` is the players choosing at this
console. It is `Fred.NumPlayerCars`, but 1 when the `wirelessRace` hook
says so (main.c's `netrace_active`, from the lobby's Start until the
link goes down). These read it:
- the preload;
- the help;
- which selector a message belongs to;
- ActivateCarSelector and DeactivateCarSelector, and the two-player
  flag they give the selector;
- SetSelectedCars;
- the per-pad press filter.

So a wireless console's car select is the one-player one, done at the
handling. `netrace_car_chosen` and `netrace_host_start` then take the
car through the `changeToScreen` and `startRace` hooks, as before.
carsel_check leaves the hook NULL, which is retail's.
