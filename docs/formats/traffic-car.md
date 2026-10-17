# TrafficCar

`TrafficCar.obj` (0x00167a08 .. 0x00168098), all of it. `DoSnapshot`
(0x00167a60) came with the replay ([replay.md](replay.md), TASKS 72d). This is
step 11h-1, the first of the traffic: a traffic car's mover. TrafficDriver
(11h-2) drives it, and TrafficTeleporter (11h-3) places it.

Ported to `3DS Files/source/trafficcar.{c,h}`. Cross-checked by
`tools/trafficcar_check.py` against `tools/src/trafficcar_test.c`, with the
retail image (SLES_507.31) running in mipsemu as the oracle.

## The shape of it

A traffic car is not simulated. The mover keeps its own place on the
ground plane, its heading and its speed. Each frame it moves them as a
**bicycle**:

- With the wheel nearly centred, the car goes straight on along the
  heading.
- Otherwise it goes round the circle that the steering angle and the
  wheelbase make.

The driver's pedals set the speed through two Tables, which is then held
between 0 and 55 mph. After that the mover writes the CarState outright:

- the position, with the height left to PutFlatOnTrack;
- a velocity along the step, as long as the speed;
- the heading, and a yaw rate from how it changed;
- the steering;
- the four wheels, turning at the speed, on the road, with nothing on
  them.

`Car::SetMovementMode`'s TRAFFIC_MOVEMENT arm (mode 2) builds one through
`gTrafficCarCtorFn` ([car-modes.md](car-modes.md)). main.c points that seam
at `trafficcar_construct`, and `TRAFFICCAR_SIZE` is `sizeof(TrafficCar)`.

## The record, 36 bytes

The mdebug record's names.

| Off | Field | Type |
|----:|-------|------|
| 0 | Mover | `CarMover`: Driver at 0, vptr at 4 |
| 8 | pCar | `Car *` |
| 12 | Position | `bVector2`, on the ground plane |
| 20 | Angle | `float`, the heading in radians, never wrapped |
| 24 | Speed | `float`, m/s, 0 .. 24.5865 |
| 28 | Pitch | `float`, zeroed, never read |
| 32 | Roll | `float`, zeroed, never read |

`_vt$10TrafficCar` is at 0x002b2190, in CarMover's layout:

| Slot | Entry |
|-----:|-------|
| 8 | the destructor, 0x00168088 |
| 16 | Move, 0x00167af8 |
| 24 | DoSnapshot, 0x00167a60 (`trafficcar_do_snapshot`) |

## The tuning

The .lit4 pool, gp-30556 .. gp-30516. The checker reads each one back out
of the image.

| gp | Bits | Value | Use |
|---:|------|-------|-----|
| -30556, -30548 | 38c90fdb | 9.58738e-05 | BAM to radians: the heading, the steering |
| -30552, -30532 | 3fc90fdc | 1.5707965 | the quarter turn `bSin` adds for a cosine |
| -30544 | 40490fd0 | 3.14159 | the steering's wrap |
| -30540 | 40c90fd0 | 6.28318 | what the wrap takes off |
| -30536 | 3c23d70a | 0.01 | "straight" is under 0.01 x the wheelbase |
| -30528, -30516 | 41c4b127 | 24.5865 | 55 mph, the Tables' top and the speed's |
| -30524 | 4622f983 | 10430.378 | radians to BAM |
| -30520 | 38c90fda | 9.5873795e-05 | BAM to radians, for the yaw rate: an ulp under -30556 |

**The Tables.** The start-up code `_GLOBAL_$I$TrafficAccelerationTable`
builds three of them. Retail's is at 0x00167fe0; the demo's is at
0x001635f0, `__CTOR_LIST__` [28]. Each is over 0 .. 24.5865 m/s.

| Table | At | Data | Entries | Values |
|-------|----|------|--------:|--------|
| TrafficAcceleration | 0x002fad50 | 0x002fad40 | 4 | 3.576 2.682 2.012 1.341 m/s² |
| TrafficBraking | 0x002fad78 | 0x002fad68 | 4 | 6.705 13.41 20.12 26.82 m/s² |
| StoppingDistanceTable | 0x002fae88 | 0x002fad90 | 61 | 0 .. 19.34 m |

The faster a traffic car goes, the less its throttle pushes and the harder
its brake bites. StoppingDistanceTable is CalculateStopDistance's
(0x00167fb8), and **nothing in retail calls that**: there is no jal to it,
and no word holding its address. It is ported for the Table it reads.

## Construction and destruction

**The constructor** (0x00167a08) writes every word but the Driver, which
SetMovementMode's tail stores. In order:

1. the vptr;
2. the car;
3. its CarState's x and y;
4. the heading: `(float)(int)Angle x 9.58738e-05`, where the CarState's
   BAM `Angle` is read unsigned, so it lands in 0 .. 2π;
5. the speed: VelocityMagnitude, not ForwardSpeed;
6. Pitch and Roll as 0.

**The destructor** (0x00168088) stores its own vptr, then jumps to
`~CarMover` with the call's flags. The delete is CarMover's.

## Move (0x00167af8)

`dt` comes in and goes out unchanged.

**The heading.** Let `rear` be the type's `Wheels[3].PositionX`, and the
wheelbase `wb = Wheels[0].PositionX + -rear`. Then:

- `fwd = (bSin(Angle + quarter), bSin(Angle))`. The quarter-turn sine is
  taken first.
- `side = (-fwd.y, fwd.x)`, to the left.
- `dist = Speed x dt`.

**The steering.** `steer = (float)GetSteering x k`, where GetSteering is
the unsigned halfword. If it is over π' (3.14159), 6.28318 comes off it.
No halfword gives exactly π': 32767 makes 40490e49 and 32768 makes
40490fdb.

**Straight on.** The test is `steer < wb x 0.01 && -(wb x 0.01) < steer`.
When it holds, Position += fwd x dist, x then y.

**Round the circle.** Otherwise, the turn is computed with the EE's divide
throughout:

1. `r = wb / steer`.
2. `front = Position + fwd x rear`. This is bScaleAdd, so the point is the
   rear axle's distance *behind*, since `rear` is negative.
3. `turn = dist / r`.
4. `center = front + side x r`.
5. With `c, s` as bSin of `turn` plus a quarter turn, and of `turn`, the
   Position rotates about the centre:

       n = (c rx - s ry, s rx + c ry),  (rx, ry) = Position - center
       Position = center + n

6. `Angle += turn`. Nothing wraps the Angle.

**The speed.** `drv` is the mover's Driver, the car's CarDriver:

    push  = (dt x Throttle) x TrafficAcceleration(Speed)
    brake = (dt x Brake)    x TrafficBraking(Speed)
    Speed = Speed + (push - brake)

Below 0 the speed becomes 0. Otherwise, over 24.5865 it becomes 24.5865.
A sum of -0 stays -0, because it is not below 0.

**The CarState.** In retail's order:

1. Position: the mover's x and y, and the old z. The fourth lane comes
   from a stack word Move never writes; **the port keeps the old one**.
2. PutFlatOnTrack.
3. The velocity: the new Position minus the old in all four lanes (a
   VU0 `vsub.xyzw`), then bNormalize to `Speed`. bNormalize writes x, y
   and z, so the fourth lane stays the step's.
4. VelocityMagnitude: `sqrt((x² + y²) + z²)` of that velocity.
5. ForwardSpeed: the speed.
6. MatrixValid: 0.
7. Angle: `(uint16)cvt.w.s(Angle x 10430.378)`. The EE's conversion
   saturates, which is `ee_trunc_w`.
8. AngularVelocity: `(0, 0, (int16)(new - old) x k' / dt, w)`. The divide
   is the EE's. `w` is another unwritten stack word, and **the port
   writes 0**.
9. SteeringAngle: GetSteering again.
10. For each wheel `i`, 0 to 3:
    - its angular velocity is `Speed / Wheels[i].Radius` (the EE's
      divide);
    - its angle grows by that x dt;
    - its suspension height is 0;
    - SetWheelTouchingGround(i, 1), then SetWheelTerrain(i, 1);
    - its slip, traction usage and Z force are 0;
    - **all four** bottom-out magnitudes are cleared, 3 down to 0, on each
      pass of the loop.
11. CalculateWheelMatrices, CalculateGeometryPosition, then the car's
    ComputeFakeRPM.

### Retail's CarState is 4 bytes longer after 876

Move's stores show where retail's CarState fields sit:

| Field | Retail | Port |
|-------|-------:|-----:|
| ForwardSpeed | 896 | 892 |
| VelocityMagnitude | 900 | 896 |
| MatrixValid | 1024 | 1008 |

The checker maps these fields by name.

## The seams

| Seam | Set by | For |
|------|--------|-----|
| `gTrafficCarCtorFn` | `trafficcar_install_seams` | SetMovementMode's TRAFFIC_MOVEMENT arm |

`trafficcar_install_vtables` installs `_vt$10TrafficCar`.
`sinit.c`'s `trafficcar_static_init` is the start-up code, [28].

## The checker

`tools/trafficcar_check.py`.

**As shipped:** retail's Move, the constructor, the destructor,
CalculateStopDistance and the start-up code run in mipsemu, over Table's
constructor and GetValue, bSin, bScaleAdd and bNormalize. The
pool is asserted against the image.

**Stood in on both sides:** GetSteering (the driver's halfword),
PutFlatOnTrack (a scripted step in x and z), SetWheelTouchingGround,
SetWheelTerrain, CalculateWheelMatrices, CalculateGeometryPosition,
ComputeFakeRPM and `~CarMover`. Each one prints its call.

**The two unwritten stack words** are preset in the model: the old
fourth lane, and 0.

**NaNs** print as "nan" on both sides. The EE has none, and which one an
IEEE host or the model makes is neither's to say.

**Scenarios:**
- the Tables at their edges, past them, at ±inf and at 30 random speeds;
  CalculateStopDistance, NaN included;
- the constructor over six headings and speeds;
- the destructor with each flag, called with a vptr not its own;
- straight on, and small steering either side;
- nine turns;
- the straight-ahead limit exactly, an LSB either side, for a wheelbase
  found to land on it each way;
- no wheelbase and a backwards one, the wheel centred included (0 / 0);
- the speed's clamps: below 0, past the most, exactly 0, exactly the
  most and an ulp over, -1, -0, and -0 throttled by -0;
- both pedals, and pedals reversed;
- dt 0, dt negative, and dt large;
- radius 0;
- PutFlatOnTrack moving the car, including an infinite fourth word;
- eleven headings out to ±3e9, where the BAM conversion saturates;
- the yaw rate's wrap, and a car whose heading is not the mover's;
- a 90-frame drive and 40 random cars.

7947 ops, 10693 lines, 0 differ.

### The mutation pass

148 mutations: 145 caught, 6 of them by crashing the harness, and 3
equivalent. The 6 are ct-vt, ct-car, vt-move, vt-dtor, sd-arg (a NaN
index into the Table) and seam.

| Mutation | Why it cannot show |
|----------|--------------------|
| st-pi-le | No steering is π' as an angle (see above). |
| sp-hi-le | At exactly the most, the speed is the most either way. |
| sp-hi-else | A speed below 0 is not above the most. |

The destructor's own vptr store (dt-vt) and the velocity's fourth lane
(ve-w) each needed a scenario. dt-vt showed once the destructor ran
under a vptr not its own. ve-w showed once a fourth word was infinite,
since inf - inf is the only step that is not 0.
