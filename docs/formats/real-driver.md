# RealDriver: the human's driver

`RealDriver.obj` (0x00138f90 .. 0x0013ac60), with the static constructor
`_GLOBAL_$I$PowerSlideYawCoef` (0x0013aa88) and `_vt$10RealDriver`
(0x00292a70). This is the last part of task 26's first slice, after
[the joystick layer](joystick.md). It is the one consumer of the pad that
drives a car.

Ported to `3DS Files/source/realdriver.{c,h}`. Cross-checked by
`tools/realdriver_check.py` against `tools/src/realdriver_test.c`, with the
image as the oracle.

## The object

640 bytes: CarDriver's 560, then twenty-six fields of its own. The vptr is
CarDriver's, at 556 (see [car-driver](car-driver.md)).

| Off | Field | Type |
|----:|-------|------|
| 560 | pCar | Car * |
| 564 | Port | JoystickPort; the constructor stores -1 |
| 568 | HandlersAdded | int32_t |
| 572 | StartLineState | int32_t, 1 holds the brake on the grid |
| 576 | StopRightNow | int32_t |
| 580 | ForcedEBrakeStop | float, retail's seconds left (the demo's int) |
| 584 | bPowerSlide | int32_t, a bool |
| 588 | ManualTransmission | 0 auto, 1 manual, 2 sport |
| 592, 593 | JoySteeringDigital, Analog | uint8_t, 128 centred |
| 596 | SteeringInput | float, -1 .. 1, left positive |
| 600 .. 602 | JoyThrottleDigital, Analog, AnalogAlternate | uint8_t |
| 604 | ThrottleInput | float, 0 .. 1 |
| 608 .. 610 | JoyBrakeDigital, Analog, AnalogAlternate | uint8_t |
| 612 | BrakeInput | float |
| 616, 617 | JoyReverseDigital, Analog | uint8_t |
| 620 | ReverseInput | float, set but never read |
| 624, 625 | JoyEBrakeDigital, Analog | uint8_t |
| 628 | EBrakeInput | float |
| 632 | LastNitroRequest | int32_t, a `WorldTimer` tick; 0 means never |
| 636 | Reversing | int32_t, a bool |

The pad sets the bytes and each handler recomputes its float. Once a frame,
`Drive` turns the floats into CarDriver's record: Steering, Throttle, Brake,
EBrake, DesiredGear, SportGear and NitroFlag.

## The handlers

`AddJoyHandlers` registers eleven handlers on seventeen events, from
`STEER` (110) to `NITRO_BOOST` (126), in the image's order, with the
driver as the object. `RemoveJoyHandlers` removes all seventeen in a loop.
It then calls `StopHonkHorn` **through the vtable**, so a horn held down as
the handlers go is let go. Both guard on `HandlersAdded`.

Each handler combines its sources the same way. The digital byte wins
unless it is at rest (128 for the steer, 0 for the rest). The throttle and
the brake then take the larger of their analog and alternate sources. The
exceptions are where the transcription would go wrong:

* **The steer's 255 is exactly -1.** Anything else is `(128 - v) / 128`,
  so 0 is +1.0 and 254 is -0.984375.
* **A stiff pedal reads four times as far.** `DoesJoystickHaveStiffThrottle`
  (in `joystick.c`) is true for types 83, 115 and 121. The throttle's and
  reverse's analog bytes are then shifted left two and capped at 255. The
  brake has no such scaling.
* **The alternate throttle is ×1.07** (`gp-31632`, 0x3f88f5c3), capped at
  255.0 and converted unsigned. The alternate brake is taken as it comes.
* **The analog e-brake is doubled and wrapped, not capped.** It is
  `sll v0,a2,1 ; sb`, so an analog e-brake past half travel reads low
  again. The port keeps it.
* Every float is `v * (1/255)`, from four separate `.lit4` words that all
  hold 0x3b808081.

## The gearbox

`ManualTransmission` picks what the shift buttons do. A value of 0 is the
automatic box and 1 is the manual box, whose gear is `DesiredGear`. Any
other value from `SetManualTransmission` is the sport shift. There,
`DesiredGear` is -2 and `SportGear` is the gear.

* **Manual.** A shift does nothing in reverse (gear 0). Up stops at
  `NumGears + 1`: NumGears counts the forward gears and gear 1 is neutral.
  Down stops at 2.
* **Sport.** Does nothing in a mellow mover. The first shift copies
  `CurrentGear` in and moves on from it; later ones step `SportGear` with
  no limit.
* **Automatic.** The button is passed to the player
  (`Player::RerouteJoyEvent`), which gives it to the camera as a rule.

`SetLowGear` answers 2 in the manual box and -1 otherwise.
`DisableStartLineState` clears the grid hold and calls `SetLowGear`
through the vtable.

## DoThrottleBrakeReverse

The pedals mean different things at different speeds:

| Forward speed | Throttle pedal | Brake pedal |
|---------------|----------------|-------------|
| over `MaxSpeedForReverse` (0.5) | throttle | brake |
| under `MinSpeedForThrottle` (-30), or reversing and under `MinSpeedForThrottleWhenReversing` (-2) | brake | reverse |
| between | throttle | reverse |

`Reversing` latches on when the brake pedal passes **0.6**. That 0.6 is a
`.lit4` literal (`gp-31620`), not the `BrakingSpeed` global beside it,
which holds the same value and is never read. The latch clears once the
car is going forward faster than -2. The reverse is doubled and capped at
1. It takes the throttle, with `DesiredGear` 0, when it is more than 0.2
over the forward pedal. Otherwise the forward pedal is the throttle, and a
car in reverse is put back in low gear through the vtable. The result
is also written to `CarState::Throttle`.

**The e-brake stop is retail's** (12i-3). The demo's `ForcedEBrakeStop`
is an on/off int, and while it is set the e-brake is held. Retail's is a
float, the seconds left:

* `ForceEBrakeStop` (`0x0013b558`) stores it.
* DoThrottleBrakeReverse (`0x0013bb40`) first runs it down by dt and
  stores what is left.
* While time is left and the car is going faster than 20 mph either way
  (`|ForwardSpeed|` over 8.940545, `gp-31532`, `0x410f0c79`), the e-brake
  is pinned at 1 and the throttle at 0.
* Otherwise the timer is cleared to 0 and the pedals are read. So a stop
  ends when its time runs out or when the car slows under 20 mph,
  whichever comes first.

The rest of retail's function is the demo's. Retail's callers are
MonitorRoadBlock (5 s, see [pursuit](pursuit.md)), Munition's
ExplodeWarhead (3.5 s), and tCopManager's ResetAllDamage and the
pullover's end (0, to let go). `main.c` binds the setter to
`gRealDriverForceEBrakeStopFn`.

An e-brake over 0.5, at over 10 m/s, logs a replay event, "EBrake", on
every eighth `WorldLoopCounter`. The image loads `pReplayManager` straight
into the call with no NULL test.

`DoBrake` (0x00139ff0) is the older form of the brake half and has no
caller. It is ported, and the checker covers it.

## DoSteering

This is where the steering feel is. In order:

1. **Where the wheels are now,** in degrees: the Steering BAM times
   360/65536, folded at 180.
2. **The lock the speed allows**, from `SteeringWheelRangeTable` on a wheel
   and `SteeringRangeTable` otherwise, over `ForwardSpeed` 0..160. The
   **port passed in** decides which, not the driver's own. Drive passes
   `Port`.
3. **The power slide** latches on past 7° of yaw and off under 5°, and only
   at a speed of `CounterSteerFadeStart` (13.41) or more.
4. **Counter-steer assist.** Steering against the yaw, in a slide or past
   the table's lock, opens the lock to the yaw itself. The yaw is scaled by
   `PowerSlideYawCoef`, and the lock is capped at 45° times the same
   factor. The coefficient is a **global that DoSteering writes** every
   time: 1.0 on a wheel, and `YawCoeffTable` of the stick's deflection
   otherwise. It is read back straight away and nothing else reads it.
5. **Back through the response curve**, with `SteeringCurveTable`'s
   `InverseLookup`, to where the stick would be now. The step towards the
   stick is limited to `SteeringSpeed × SteeringSpeedTable(speed) × dt`,
   times `SteeringReturnFactor` on the way back to centre, and never under
   0.173.
6. **Forward through the curve again** with `GetValue`, times the lock.
   The result goes to a BAM through the car's steering ratio: `cvt.w.s`,
   an integer divide by 360 that truncates toward zero, then `sh`. The
   port uses `ee_trunc_w` for the conversion, so an out-of-range float
   saturates as the EE's does.

The seven tables are built by the static constructor, which is entry [17]
in `sinit.c`. `SteeringInputTable` and `BrakingCurve` have no reader in the
image. `CounterSteerFadeEnd`, `BrakingSpeed` and `UnBrakingSpeed` are
`.sdata` words nothing reads: what is left of a fade and a brake ramp that
were written and then not used. They are exported so the transcript can
print them.

## Drive

`Drive` (0x00139600) does the following, in order:

1. Passes the car's position, velocity and class to the route editor's
   recorder.
2. Resets the joy values if the pad is unplugged.
3. Runs DoThrottleBrakeReverse, then DoSteering.
4. Applies the two overrides: `StopRightNow` zeroes the throttle input and
   sets the brake input to 1, so it takes hold next frame. `StartLineState`
   sets the brake itself to 1.
5. If the car has a player, switches the radial blur on (alpha 0 → 0.8) on
   the frame the nitro starts, and off on the frame it ends.

`RealDriverAddNearbyDebugTopology` is `jr ra` and is not called.

## The reset, the horn and the nitro

**Reset** needs all of these: no grid hold, a press, a player, and
`Player::IsAllowedToReset`. The speed kept is the forward speed times the
dot product of the body's x axis with the path direction on the ground
plane, neither term below zero, capped at `RollingResetSpeed`. The port
writes `max.s` / `min.s` out as the EE defines them, so a zero keeps its
sign. A cop car (`UsageType` 1) with a cop manager faces the way
`GetResetDirection` says (`cop-manager.md`); any other car faces 1.0. Then
`Car::ResetToRoutePoint` (flag 1) runs, then `Player::PlayerSelectedReset`.

**The horn button** starts or stops the horn through the vtable, and a
press also cancels the route editor's tuning lines. On a cop car the button
is the lights and siren instead. In Be A Cop it goes to the cop manager's
toggle. Otherwise it flips `CopLights`, read with `lb`, so as a signed
byte, between 0 with no siren and 1 with siren mode 1. `StartHonkHorn` and
`StopHonkHorn` make no sound on a cop car, whose siren is its sound.

**The nitro** is only for a cop, and only in Be A Cop. `LastNitroRequest`
is a `WorldTimer` tick, at 4000 a second (0.00025). A value of 0 or INT_MAX
means never. The subtraction is `subu` and wraps, and `cvt.s.w` reads the
difference as signed:

| Query | True when |
|-------|-----------|
| NitroActive | age < `NitrousActiveTime` (4 s) |
| NitroWasActive | 0 ≤ age − `WorldTimeElapsed` < 4 s |
| NitroAvailable | never requested, or age ≥ active + `NitrousRechargeTime` (0) |

## The vtable

`_vt$10RealDriver` is CarDriver's twenty-one slots, with RealDriver's own
entries for the destructor, Drive, both joy-handler calls, SetLowGear,
SetDesiredSpeed (`jr ra`), GetDriverNumber (the car's `DriverNumber`, read
with `lh`) and the two horn calls, and DoSnapshot (24, TASKS 72c).
`realdriver_install_vtable()` runs at boot in `main.c`.

## The seams

Fourteen calls go into classes that other tasks own. Each is a plain `jal`
in the image, and in the port each is a pointer that is NULL until its
class exists. A NULL seam is skipped. A NULL query answers the value that
leaves the game as it would be without the class: no blur, no sound, no
replay event, no reset (`IsAllowedToReset` false), and a reset direction
of 1.0. None of the fourteen feeds the physics.

| Seam | Image | Task |
|------|-------|------|
| `MaybeAddTrackRoutePoint`, `CancelTuningDrivingLines` | 0x001bbd18, 0x001bbd90 | 27 |
| `RadialBlurOn` / `Off` / `Alpha` | 0x0010dc80 .. 0x0010dd38 | 27, bound by 80d (`radial-blur.md`) |
| `ReplayManager::RegisterInterestingEvent` | 0x0013c290 | 29 |
| `Player::RerouteJoyEvent`, `IsAllowedToReset`, `PlayerSelectedReset` | 0x001721b8, 0x0017aab8, 0x0017ab08 | 26 |
| `tCopManager::GetResetDirection`, `BeACopToggleSirenAndLights` | retail's 0x00228ae8, 0x002289b8 (the demo's 0x00214740, 0x00214610) | 26, bound by 74 and 12m-1 |
| `Car::ResetToRoutePoint` | 0x00131480 | 26 |
| `BaseCarSound::StartHonkHorn` / `StopHonkHorn` | 0x00185330, 0x00185370 | 29 |

The route editor's two free functions are **not** dead code. The editor is
built on every track load, so both calls reach it. It records a route only
in its debug mode, but it cancels the tuning flag on every route.

## Not ported

`RealDriver::DoSnapshot` is retail's (0x0013aeb8, the demo's 0x001390b8),
ported with the replay in TASKS 72c. The port comes back as one unsigned
byte (`move t0,zero`); ForcedEBrakeStop goes after ManualTransmission;
pCar and HandlersAdded are not saved.

The image has one call to the constructor, from `RealController`'s
constructor (0x00224788). `RealController` is the controller that
`Car::SetControlMode` builds for a human's car, behind
`gRealControllerCtorFn`; see [car-modes](car-modes.md).

## Cross-check

```
python tools/realdriver_check.py            # 199214 ops, 45443 lines, 0 differ
python tools/realdriver_check.py --mutate   # 140 mutations, 136 caught, 4 equivalent
```

The model runs every RealDriver method but DoSnapshot as shipped in
mipsemu. It also runs, as shipped, everything those methods call that the
port has: the Tables and their constructor, `GetValue` and
`InverseLookup`, `CarState::GetYaw` and `bATan`, `Car::GetRoute` and
`GetRoutePoint`, CarDriver's constructor and destructor, DriveTarget, and
the vtable dispatch. The pad layer's five calls and the fourteen seams are
stubbed by symbol. Each logs what it is handed and answers what the script
says.

Three things make the transcript sharp:

* **A seam mask.** A set bit installs a seam in the harness and lets the
  model's stub log. A clear bit leaves the harness's pointer NULL and
  makes the model's stub silent, answering what the port's NULL case
  assumes. So every mask the script uses checks the port's NULL handling
  against the image as well as the call.
* **Poison.** The model's Car, CarTypeInfo and Player are filled with 0x55,
  and only the fields RealDriver is meant to read are set, image offset by
  image offset. A field read by one side and not the other shows up as a
  difference.
* **Labels.** Every pointer is printed as a name, and the DriveTarget as an
  FNV-1a hash of its 528 bytes.

The scenarios cover:

* the tables, tunables and vtable as built, and `GetValue` and
  `InverseLookup` over every table;
* the constructor over two fills, and the small methods;
* the registration, and every pedal handler over its own events and
  others, with a fuzz;
* the gearbox in each mode;
* the reset, horn and nitro over their guards and the seam masks;
* DoThrottleBrakeReverse and DoBrake over a grid;
* DoSteering over random states and held-stick sequences;
* Drive over random states and nitro transitions;
* every vtable slot, a fuzz of everything interleaved, and the teardown;
* on the retail image, the e-brake stop: the constructor, the setter over
  odd bits, DoThrottleBrakeReverse over a grid (timers, frame times and
  speeds one ulp either side of 20 mph), and timed countdowns.

**The retail run** (12i-3). The demo scenarios keep `ForcedEBrakeStop`
at 0, the one value where the demo's int and retail's float agree. The
last scenario starts with `OP_RETAIL`, which the harness ignores and
which sends the model's ops after it to a retail emulator. There the
constructor (`0x0013ad90`, with DriveTarget's constructor and Clear
silent), ForceEBrakeStop and DoThrottleBrakeReverse run as shipped, with
retail's offsets (`ForwardSpeed` at car+960) and tunables. So does
SetLowGear, through retail's vtable (`0x002aee30`). `OP_EBDUMP` prints
only what DoThrottleBrakeReverse reads and writes, since the rest of the
driver is not set there.

**Seven mutants survived the first pass.** Three were real gaps in the
script:

* **`drive-order`**, which swaps DoThrottleBrakeReverse and DoSteering in
  Drive. The two share no state. The only way to see their order is by
  what each logs: the e-brake's replay event, and the wheel query. No
  drive frame had the e-brake on, so none logged the event. Directed
  frames now do.
* **`reset-cap`**, a `<=` for the `min.s` against `RollingResetSpeed`. The
  two differ only at a tie, and at a tie only in the sign of a zero. The
  reset now runs -0.0 against a +0.0 cap, and the other way round.
* **`nitro-age-scale`**, 0.00025001 for 0.00025. At the 4 s threshold both
  constants flip between the same two ticks. A 1000 s nitro separates
  them, and so does a frame time that falls between two ticks' ages.

Four are equivalent:

* **`steer-slide-off`, `steer-slide-on`.** These move the power-slide
  thresholds from `<` to `<=` (and the other way). The yaw is a BAM
  difference times `BAM_TO_RAD` times 180/π, so it takes one of 65536
  values, and none of them is exactly 5.0 or 7.0. The nearest are
  4.9987793 / 5.0042725 and 6.998291 / 7.003784.
* **`steer-inv-sign`.** r is 0 only when Steering is 0. InverseLookup then
  answers the table's first entry, 0.0, through its
  `|value - first| < 1e-6` early-out. So the two arms differ only in the
  sign of a zero, which the addition after them absorbs.
* **`steer-out-sign`.** At cur = 0 the curve is clamped to MinArg 0.1,
  whose entry is 0.0. The output is a zero of one sign or the other, and
  `cvt.w.s` makes both 0.

At 12i-3, eighteen mutations were added for retail's e-brake stop: the
constructor's clear, the setter, the countdown, both tests and the
20 mph constant one ulp up, and the clear. The first pass caught all of
them.
