# Joystick: the pad ring, the events and the scanner tables

The first slice of task 26. Everything between the pad and a `JoyHandler`:

| Object | Range | Port |
|--------|-------|------|
| `Joystick.obj` | 0x00150a50 .. 0x00152860 | `joyevent.{c,h}` |
| `JoystickPS2.obj`, the ring | 0x0011d150 .. 0x0011da60 | `joypad.{c,h}` |
| `Joylog`'s two accessors | 0x0017b920, 0x0017ba60 | `joylog.{c,h}` |
| `ScannerConfigTable`, `ValidJoystickConfigurationTable`, `EventNameTable` | 0x002dc6c0, 0x002de3a0, 0x002f22f8 | `scannertab.c`, generated |
| the 3DS's buttons as a DualShock 2 | -- | `joyhid.{c,h}` |

`tools/gen_scanner_tables.py` writes `scannertab.c` and `joyeventid.h` from
the image and the stabs, and `--check`s they are current.
`tools/joystick_check.py` holds the port to the image in mipsemu (below);
`tools/joyhid_check.py` holds the 3DS map to what `joyhid.h` promises.

## The shape of it

Every consumer of input -- the menus, `RealDriver`, the replay, the
cameras -- calls `AddJoyHandler(port, event, fn, obj)`. That makes an
`EventNode` on the port's `Joystick`, and connects it: finds the
`ScannerConfig` row that says which bits of the pad buffer mean that event
for the controller now in the port. Once a frame `GenerateJoyEvents` runs
each node's scanner over the newest reads, queues whatever comes back, and
then calls the handlers in queue order.

Nothing in the object knows what a button is. Every binding in the game is
a row of `ScannerConfigTable`, and the pad buffer is the DualShock 2's 32
bytes. That is what lets the 3DS in without a second table: `joyhid.c`
builds a DualShock 2 buffer and every row works as shipped.

### The frame

`ReadJoystickData` (the PS2 calls it from the vertical-blank interrupt; the
3DS from the main loop, once a frame) reads both ports into a 32-deep ring.
`GenerateJoyEvents` then:

1. Empties the queue.
2. If the joylog is replaying, queues its recorded events and skips the
   pads. Otherwise, unless a fancy replay is running, drains every ring
   entry since the last frame: `PrepareToGetJoystickData` fixes how far to
   go and works out each read's controller type, and for each read and
   each port `Joystick::GenerateEventsFromScanners` runs the scanners. A
   port that raised anything stamps `DemoDiscManager.LastActivityTime`
   (`RegisterActivity`, inline). Only the demo disc's timeout reads that,
   so the port leaves the stamp out. The frame's queue goes to the joylog.
3. With a replay, feeds the fancy replay's next scripted event, then either
   records the queue into the replay or -- when it is playing back and not
   paused -- replaces it with the recorded one.
4. Calls each queued handler. A handler may remove handlers, which clears
   their queued entries (`RemoveEvent` nulls `Handler`); `NumEvents` and
   each `Handler` are read fresh, so that takes effect in the same frame.

The queue holds 256. The 257th event in a frame is dropped.

A logged event -- the joylog's and the replay's unit -- is
`event | value << 8 | port << 16`, written in 19 bits; each frame's count
goes first, in 8.

## The DualShock 2 buffer

`ScannerConfigTable`'s shift numbers are bit numbers into the 32 bytes read
as little-endian words: bit `s` is `word[s >> 5] >> (s & 31)`, and a byte
field is the eight bits from there.

| Bytes | Bits | Content |
|-------|------|---------|
| 0 | 0-7 | 0 on a good read |
| 1 | 8-15 | the mode: the controller type below |
| 2 | 16-23 | SELECT, L3, R3, START, Up, Right, Down, Left |
| 3 | 24-31 | L2, R2, L1, R1, Triangle, Circle, Cross, Square |
| 4-7 | 32, 40, 48, 56 | right stick X, Y; left stick X, Y. 128 centre, 0 left / up |
| 8-19 | 64 .. 152 | pressures: Right, Left, Up, Down, Triangle, Circle, Cross, Square, L1, R1, L2, R2; 0 released .. 255 |

The buttons are **active low**: a released button reads 1.

### Controller types

`ReadRegularController` answers the mode byte on a good read and -1
otherwise. `ValidJoystickConfigurationTable` lists the types the game
knows, the user configurations each allows (the options screen's layouts),
and the dead zone and hysteresis for its three analog devices:

| Type | Mode | Configurations | Steer hyst / dz | Throttle, brake hyst / dz |
|-----:|------|----------------|-----------------|---------------------------|
| 65 | 0x41 digital pad | 10-13 | 0 / 0 | 0 / 0 |
| 83 | 0x53 analog joystick | 20-24 | 4 / 20 | 12 / 20 |
| 115 | 0x73 DualShock, analog mode | 20-24 | 4 / 20 | 12 / 20 |
| 121 | 0x79 DualShock 2, pressure | 30-34 | 4 / 20 | 12 / 20 |
| 35 | 0x23 NeGcon | 40 | 4 / 8 | 12 / 8 |
| 21, 22 | Logitech wheels | 50, 51 | 2 / 0 | 12 / 8 |

`IsJoystickTypeWheel` is true for 21, 22 and 35, and
`DoesJoystickHaveStiffThrottle` (0x0011daf8) for 83, 115 and 121: the pads
whose analog pedal travels a quarter as far, which RealDriver's throttle
and reverse handlers read four times over (see
[real-driver](real-driver.md)). A type not in the table
gets the defaults, hysteresis 12 and dead zone 20. The configuration a port
uses is its user configuration if the type allows it, and the type's first
otherwise; a type with no row has configuration 0.

### Type detection

A read whose type differs from the port's `CurrentType` is not believed at
once: it has to repeat, unchanged, for ten more reads. Only then does the
port take it, choose each analog device's dead zone and hysteresis for it,
and reconnect every node -- the rows are per configuration, so a new type
means new rows. Until the first type is believed `CurrentType` is -1,
configuration 0, and configuration 0 matches only the type-change row: a
node registered before the pad is recognised is idle until then.

The type monitor is two nodes that `InitJoystick` registers, one per port,
for `TYPE_CHANGED` with `TypeChangedHandler`, which writes
`CurrentJoystickTypes[port]`. 255 there (the byte of -1) means nothing is
plugged in.

### Calibration

Each port has four `AnalogJoystickCalibration`s, indexed by a row's
`AnalogDevice`. `ChooseDeadZoneAndHysterysis` gives device 1 the steer's
numbers, 2 the throttle's and 3 the brake's, and 0 the steer's hysteresis
with the default dead zone. The rows disagree: the throttle rows read
device 3 and the brake rows device 2. Every type's throttle and brake
numbers are the same, so nothing can tell. Each is a four-point
`Graph`: `(lo, 0) (128 - dz, 128) (128 + dz, 128) (hi, 255)`, so the dead
zone is a flat run at 128 either side of the centre. `lo` and `hi` are 0
and 255 until the options screen calibrates them.

## The rows

A `ScannerConfig` is 32 bytes: eight configuration numbers (-1 is every
configuration, 0 an unused slot), the event, the scanner, then `Xor1`,
`Xor2`, `Shift1`, `Shift2`, `Param`, `AnalogDevice`, `ValidDuringReplay`,
the button glyph (`eButtonChars`) and the button's name for the options
screen. `FindScannerConfig` takes the first row for the event that lists
the configuration.

### The scanners

| Scanner | Returns |
|---------|---------|
| `TypeChanged` | the type, when it changes |
| `DigitalAnyButton` | 1 when any of `Param` bits from `Shift1` goes from all-released to one pressed (`Xor1` inverts the lot) |
| `DigitalDown`, `DigitalDownPlus` | `Param` (1 if 0) on the press |
| `DigitalUpOrDown`, `DigitalUpOrDownPlus` | `Param` on the press, 0 on the release |
| `DigitalDoublePress` | 0 at the release that ends a press of 2-11 reads, a gap of 3-12 and a second press of 3-12 |
| `DigitalRepeat` | 1 on the press; 2 on the 26th read held, and every 7th after; 0 on the release |
| `DigitalSteer` | two buttons as a stick: 0, 255, or 128 for neither or both |
| `DigitalAnalog` | a stick as a button, two axes, the first to say anything wins: `Param` 1 is 1 on crossing below 8 from 9 or more, 2 is 1 on reaching 248 from below 247; repeats on `DigitalRepeat`'s timing; 0 back at 9 / below 247 |
| `Analog` | a byte through the device's calibration; `Param` 1 folds the low half onto 0..255, 2 the high half. Sent on the first read, then when it moves by more than the hysteresis, or moves at all onto 0, 128 or 255; a `Shift2` button, released, holds it |

The digital scanners share one test, `digital_pressed`. `Shift1` is the
button, `(bit ^ Xor1) & 1`, and 1 is pressed -- so `Xor1` is 1 for an
active-low button. A `Shift2` adds a second button, and what it means
depends on `Xor2`:

* **`Xor2` 1: a combo.** The second button has to be held this read and
  the last, and the first has to be newly pressed this read. `TRIANGLE + L2`
  is this.
* **`Xor2` 0: a veto.** `(bit ^ 0) & 1` is 1 while the second button is
  *released*, so the row fires only while it is up. `SHIFTDOWN` is L2 with
  Triangle as its veto: L2 alone shifts, Triangle + L2 is the zone freeze
  instead.

Other things the table does that are easy to misread:

* **`CAMERA_POV_CHANGE` fires when Triangle is released.** Its `Xor1` is 0,
  so "pressed" reads the raw bit, which goes to 1 on the release. Triangle
  is also the combos' modifier, and changing the camera on the release is
  what lets it be held for a combo first. It still changes the camera after
  one.
* **An analog row's `Xor1` of 1 flips bit 0 only.** The throttle, brake and
  stick rows all have it, so a pressure of 255 reads 254 and full lock is
  253 after the curve, never 255. The image does the same; the physics was
  tuned on it.
* **`TOGGLE_TRACK_MARKER` (row 91) can never fire.** It is a double press
  of the combo L2 + R2, and a combo's first button reads as pressed only on
  the read it went down. The counter needs two to eleven consecutive
  pressed reads to leave the first window, so it goes back to 0 every time.
  The checker's `DoublePress` scenarios feed the row anyway; it is dead on
  the disc as well.

### Configuration 30

The default for the DualShock 2, and so for the 3DS (below). The menu rows
(configuration -1) are shared by every type.

| Event | Button |
|-------|--------|
| `MENU_SELECT` / `MENU_BACK` / `MENU_HELP` / `MENU_SQUARE` | Cross / Triangle / Circle / Square |
| `SCROLL_*` | D-pad, repeating |
| `MENU_ANALOG_*` | left stick |
| `STEER_ANALOG` | left stick X |
| `STEER` | D-pad Left / Right |
| `THROTTLE_ANALOG`, `BRAKE_ANALOG` | Cross, Square pressure |
| `THROTTLE_ANALOG_ALTERNATE`, `BRAKE_ANALOG_ALTERNATE` | right stick up, down |
| `EBRAKE_ANALOG` | R1 pressure, Triangle vetoes |
| `SHIFTUP`, `SHIFTDOWN` | R2, L2, Triangle vetoes |
| `CAMERA_LOOKBACK` | L1, Triangle vetoes |
| `CAMERA_POV_CHANGE` | Triangle, on the release |
| `ZONE_FREEZE` / `REQUEST_HELICOPTER` | Triangle + L2 |
| `ZONE_PREVIEW` / `REQUEST_ROADBLOCK` | Triangle + R2 |
| `NITRO_BOOST` | R3 |
| `HONK_HORN` | Circle |
| `CYCLE_HUD` | D-pad Up |

Configurations 31-34 move the throttle, brake, e-brake and horn around;
34 is the "triggers" layout, R2 throttle and L2 brake with the gears on the
right stick.

## The 3DS

`joyhid.c` is `gJoypadRead`. It answers port 0 with a DualShock 2 buffer in
pressure mode, so the port reads as type 121 and takes configuration 30,
and leaves port 1 empty, which reads as nothing plugged in.

| 3DS | DualShock 2 | In a race (configuration 30) |
|-----|-------------|------------------------------|
| A | Cross | throttle; menu select |
| B | Square | brake |
| X | Triangle; Circle racing | menu back; horn while racing |
| Y | Circle; Triangle racing | menu help; camera (on release), combo modifier while racing |
| L, R | L1, R1 | look back, e-brake; in Be A Cop, the roadblock and the helicopter |
| ZL, ZR | L2, R2 | shift down, up; with Y (X in a menu) held, zone / pursuit calls |
| D-pad | D-pad | digital steer, HUD (Up); menus |
| D-pad Down | Down and R3 | nitro |
| START, SELECT | START, SELECT | |
| Circle Pad | left stick | steering; menu analog |
| C-Stick | right stick | alternate throttle (up) and brake (down) |

A and B take the throttle and brake because they sit next to each other,
as Cross and Square do; the price is that the frontend's "back", which is
`MENU_BACK` and so Triangle, is X rather than B.

**The race layout.** While the race coordinator is in `RACE_IN_PROGRESS`
(`gJoyHidRaceLayoutFn`, which `main.c` binds), `joyhid_build` swaps X and
Y before the map: X reads as Circle, the horn -- or a cop car's lights and
siren -- and Y as Triangle, the camera and the combo modifier. The user
asked for the horn on X (2026-10-09). The flyby, the countdown, the pause
screen, the replays and the results keep the menu layout, so X is "back"
wherever there is a menu. The swap is upstream of the scanners, so the
joylog and replays see the DualShock buttons as before. R3 goes on D-pad Down
because nothing reads R3 in a menu or Down in a race. A held button's
pressure byte reads 255 and a released one 0. A stick maps
±`JOYHID_STICK_FULL` (144 of the Circle Pad's nominal 156, which a worn pad
or a diagonal falls short of) onto 0..255, Y inverted -- the DualShock's Y
is 0 at the top. ZL, ZR and the C-Stick are the New 3DS's; an Old 3DS reads
them as released and centred.

**Be A Cop's L and R.** The user's mapping of 2026-10-11, which replaced
12m-3's D-pad calls: in Be A Cop, in the cop's car, L calls a roadblock
and R the helicopter. X, the horn, stays the cop's target: in retail
`HONK_HORN` goes to `BeACopToggleSirenAndLights`, which changes the chase
target. The nitro stays on D-pad Down. Retail's two calls are combos,
`REQUEST_HELICOPTER` TRIANGLE + L2 and `REQUEST_ROADBLOCK` TRIANGLE + R2
(rows 178 and 180 in configuration 30), so the race layout's Y + ZL and
Y + ZR make them too. `gJoyHidRaceLayoutFn` answers `JOYHID_LAYOUT_COP` in
a Be A Cop race when player 1's car is the player cop's, and
`joyhid_cop_keys` then rewrites the keys before the map:

- L and R are dropped, so the cop has no look back or e-brake.
- A new press of L sends Y (Triangle) for one reading, then Y + ZR (the
  roadblock), then Y alone, so R2 lets go behind Triangle's veto and
  shifts nothing. R does the same with ZL (the helicopter). Pressing
  both at once calls the helicopter.
- Triangle lets go on the next reading, which raises `CAMERA_POV_CHANGE`.
  The request's handler (`playerinput.c`) has just set
  tIgnoreNextPovChange, which holds that off for a second, the same as
  for the combo pressed by hand.
- A press during a call's three readings is dropped. Holding the key
  calls once. A key held into the cop layout calls nothing, since the
  keys held in the other layouts are noted too.

The D-pad steers as in any race, Up still cycles the HUD and Down is
still the nitro (R3).

**The Circle Pad in the menus.** TASKS 42, asked for on 2026-10-11: the
Circle Pad moves through every menu as the D-pad does. The port's menus
read the 3DS keys, not the joystick layer's events (`main.c`'s
`flowInput`, for the frontend, the pause and the screens after a race),
so nothing heard the stick's `MENU_ANALOG_*` rows. `joyhid_menu_pad`
turns each reading of the Circle Pad into a D-pad press:

- The farther axis picks the direction once the stick is past
  `JOYHID_MENU_PRESS` (96) on it.
- That direction is held until its axis falls under
  `JOYHID_MENU_RELEASE` (48). The gap keeps a stick resting near the edge
  from pressing over and over.
- A push is one press, as the D-pad's is. Nothing repeats while it is
  held.

The main loop ORs the newly pressed direction into the frame's presses,
but only for `flowInput`. A race steers with the stick and the viewers
pan with it, so neither hears it. The pad's state is kept every frame, so
a stick held from the race into the pause presses nothing until it goes
back past the release and out again. `joyhid_check.py` walks the stick
through presses, holds, the gap, a change of direction without passing
the centre, and the diagonals. Eleven mutations of `joyhid_menu_pad` are
all caught.

On Azahar, whose Circle Pad is the arrow keys:

- `run_azahar_coprace.ps1 -CirclePad`: one push down moved Cops On Mode
  Select from item 1 to item 2 (You're The Cop), with no second step.
- `run_azahar_quickrace.ps1 -Presses "77:5,40:5,40:5,38:5,38:5,77:5"`:
  in a race's pause menu, down, down, up, up went through items 1, 2, 3,
  2 and 1, and START resumed the race.

`joyhid_check.py` presses each key and stick through `joyhid_build`, the
ring, the scanners and the tables, and checks that each raises the event
above -- including that X + ZL is the zone freeze and not a downshift,
and that in the race layout X honks and Y + ZL is the zone freeze. In the
cop layout, L and R each raise their request on the second frame and
only there, with the camera change on the fourth and no look back,
e-brake, gear change or horn. The checks cover both keys at once, a
press during a call, a key held over from the race layout, a second
press, the D-pad's steer, X's horn, and Up and Down. Thirteen mutations
of `joyhid_cop_keys` are all caught.

`main.c` installs the map and calls `InitJoystick` at boot, and runs
`ReadJoystickData` and `GenerateJoyEvents` once a frame after the HID scan,
with `RealTimer` and `FrameCounter` set from the loop. RealDriver's
handlers are ported, but nothing builds a RealDriver until a race builds
a `RealController`. No menu handler is registered yet either: the
frontend's own registration (`AddNormalMenuJoyHandlers`) comes with the
menus that use it. So for now it runs the type monitor, and logs
`joystick: port 0 type 121` once ten reads agree.

## Not ported

* `JoystickDoSnapshot` (0x001514b0), which needs `ReplaySnapshot`.
* `PrintAllRegisteredJoyHandlers` (0x00151538), which prints nothing on the
  retail build.
* The Logitech wheel layer (`UpdateLogitechWheels`, `GetWheelDevice`,
  `ConvertLogitechToDualShock`): the 3DS has no wheel, so
  `LogitechDeviceID` is always -1.
* The joystick monkey, a debug feature the retail build never turns on.
* `bRepeat`, behind the joylog. `Joylog::Init` returns at once unless
  `bPSX2PlatformType` is 1, and on a retail console it is 0, so `pRepeat`
  stays NULL and both accessors do nothing. The image's `Joylog::GetData`
  also has an end-of-data arm -- it tells the repeat buffer it is finished
  and clears `pRepeat` and `ReplayingFlag` -- that the port does not carry:
  it is unreachable without a `bRepeat`, and the checker's never runs out.
* `ReplayManager`: `replay.h` has all 116 bytes of it, and the 332 of
  `ReplaySnapshot`. `RegisterInterestingEvent` and
  `InvalidateInterestingEvents` are ported, for Car's resets
  ([car](car.md)). `GetData` and `AddData` are still seams, and
  `pReplayManager` stays NULL until the replay is ported.

## The checker

`tools/joystick_check.py` writes one script of ops -- register a handler,
set a pad, read it into the ring, run a frame, call one scanner on one
buffer, look a config up -- and runs it twice: on the image in mipsemu, and
on the port through `tools/src/joystick_test.c`, which reads the same ops
from a file. Both print the same transcript.

On the image, the platform reads, the slot pool, `ReplayManager`'s two
accessors, `bRepeat`'s two and the handlers are stubs; everything in
`Joystick.obj`, `Graph`, `bStrCmp` and `TypeChangedHandler` run as shipped.
The scenarios are every lookup over every event and a spread of types and
user configurations; the calibration calls; each scanner over long
run-length-coded button and stick sequences from the table's own rows and
from fuzzed ones; and a play session through `GenerateJoyEvents` -- type
detection and flicker, mode changes, the ring overflowing, handlers added
and removed from inside a handler, a queue past 256, the replay and the
joylog in each of their states, and the teardown. The two type predicates are asked about all 256 type
codes. 64,240 ops, 75,891 lines, no difference.

`--mutate` runs 250 mutants of `joyevent.c`, `joypad.c`, `joylog.c`,
`joystick.c` and the generated tables against that transcript: 246
caught, 4 equivalent, none unexplained. The equivalents are
`choosedz-break` (each type has one row in
`ValidJoystickConfigurationTable`, so the last match is also the first),
`find-zero` (`FindScannerConfig` has already tested for configuration 0)
`platforminit-state` (nothing reads the port state that scePad's
state machine would keep) and `gen-count` (retail's one reader of the
scanners' count is the demo disc's activity stamp, which the port leaves
out).
