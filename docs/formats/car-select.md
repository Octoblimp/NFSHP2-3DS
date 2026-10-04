# Car select (step 16, SC-1)

Every race setup leads to car select: You're The Cop's Setup, a single
race, the championship, and two players. It is retail's SelectCarScreen
and CarSelector (`SLES_507.31`), which the demo disc has only in part.
SC-1 ports them as logic and 2D in `bcarsel.c`. SC-2 adds the car in 3D,
and SC-3 the nebula behind it.

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

The event trees are not ported, so `findEventForCar` is NULL in
`main.c` and step 3 never answers on the device.

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
its rectangle, ShowLoadedCar, the commentary and AssignCarOfType. The
3D car, the camera mover, the platform, the lighting, the spotlights
and the nebula are silent. GetTextureInfo answers 0: its only callers
are the tick's swatch texture, which feeds only SetSelectCarLighting,
and InitSpotlights, which does nothing without its texture.

After each message, joy event, preload and close, every line that
changed is printed:
- the screen and each selector's fields;
- the car list in order;
- the unlock box, the thumbnail spline and the swatches;
- the camera's two orbit speeds;
- the preload's two cars and the CarLoader's flags;
- both players' gearbox and handling;
- every Flailer object's bytes.

The script runs You're The Cop with one player, a single race in
French with kilometres, the championship in German, and two players on
both halves. It goes across locked, covered, egged and hidden cars and
every skin. It takes the orbit view in and out, including its timeout
at exactly 2400 frames and at 2401. It hides the unlock box and brings
it back, and runs every popup and every way out of it. It also covers
the help menu up, both units and all three languages.

The model is slow: a tick costs about 170 ms in mipsemu, most of it
retail's bSPrintf and FindFlailerObject for the 25 cloaks. The whole
script takes about seven minutes. The mutation pass runs the model once
and each mutant's harness in about two seconds.

The script is 7282 ops and 430239 lines, with 0 differ. The mutation
pass catches 196 of 201 mutations. The other five can't change the
transcript:
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
