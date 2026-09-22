// car -- Car.obj, first slice.
//
// Thirty-four of Car's eighty methods make no call outside the class.
// That is not the same as "can be written today": the count is of `jal`
// targets, so a method whose only calls are to other Car methods lands
// there even when one of those is itself blocked.
//
// Seventeen of the thirty-four can be written today, and they are what this
// file holds. Of the other seventeen, ten dispatch through a driver,
// controller or mover vtable and seven reach a class that belongs to task
// 26 or 27. All of them are listed at the bottom with what each is waiting
// for, so the next slice does not have to re-derive the dependency graph.
//
// Layout, enums and every offset: car.h. Cross-check: tools/car_check.py.
// Write-up: docs/formats/car.md.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "car.h"

// car.h names CarDriver and CarTypeInfo without including their headers, to
// keep out of the cycle cardriver.h -> drivetarget.h -> car.h. GetSteering
// reads through the pointer, so the complete record is needed here.
#include "cardriver.h"

// ----------------------------------------------------------- the two clocks
//
// `WorldTimer` (0x00323cf0) counts ticks of 0.00025 s and `WorldTimeFrames`
// (0x00323cfc) counts frames. Both are engine.c's in the handheld build; the
// declarations are here because Car reads them through `gp` and nothing else
// in this file needs engine.h.
//
// 0.000250000012f is the image's own word, 0x3983126f, and it is written as
// a literal rather than as `1.0f / 4000.0f` only because the image holds a
// literal. The two are the *same* float32: the correctly-rounded float32 of
// 1/4000 is 0x3983126f exactly, and a mutation swapping one spelling for the
// other is a no-op that tools/car_check.py records as such.
//
// What is a different float is 0x3983126e, one ulp down, which is what a
// hand-typed 0.00024999999f gives. That one is separated by the two boundary
// fixtures in the transcript -- [blink tick] and [honk tick] -- because
// nothing else in the slice is sensitive to a single ulp of the tick.
extern int32_t WorldTimer;
extern int32_t WorldTimeFrames;

#define CAR_TICK_SECONDS 0.000250000012f

// 0x001319c0 rounds the wiper's off-time up to a whole number of these.
#define CAR_WIPER_PERIOD_FRAMES 82

// --------------------------------------------------------------- the stubs
//
// Three methods are empty in the shipped image. They are kept rather than
// deleted because they are named in the class and a caller that expects one
// to do something is a bug worth seeing as a call to an empty function
// rather than as a missing symbol.

// 0x00130ff0. `jr ra; nop`.
void car_fake_engine_task(Car *c)
{
    (void)c;
}

// 0x00131db0. `jr ra; nop`. Car registers for events and ignores them.
void car_event_handler(Car *c, void *event)
{
    (void)c;
    (void)event;
}

// 0x00184bc0. Not quite empty in the listing: it opens a 112-byte frame and
// writes a0's six register arguments into the varargs save area before
// tearing the frame straight back down. Nothing reads the save area, so the
// observable behaviour is a no-op, and the debug text this once printed is
// gone from the retail build.
void car_print_above(Car *c, const char *text, int colour)
{
    (void)c;
    (void)text;
    (void)colour;
}

// -------------------------------------------------------------- the blinking
//
// A car blinks -- flashes in and out -- while it is being reset onto the
// track, and is not collideable while it does. The timer is a WorldTimer
// stamp and 0 means "not blinking".

// 0x00131628.
void car_start_blinking(Car *c, float duration)
{
    c->BlinkDuration = duration;
    c->BlinkTimer = WorldTimer;
}

// 0x00131638.
void car_stop_blinking(Car *c)
{
    c->BlinkTimer = 0;
}

// 0x00131640. Two sentinels stop the blink, not one: 0 and 0x7fffffff. The
// listing builds the second with `lui 0x7fff; ori 0xffff` and compares it
// with `xor` and `sltu` rather than a branch, which is why it is easy to
// read past -- but it is a real second early-out, and PleaseResetMeLater
// writes it.
int32_t car_is_blinking(Car *c)
{
    int32_t t = c->BlinkTimer;
    float elapsed;

    if (t == 0 || t == 0x7fffffff)
        return 0;

    // `subu` is a 32-bit wrapping subtract and `cvt.s.w` reads the result as
    // signed, so a WorldTimer that has wrapped past the stamp gives a
    // negative elapsed time and the car keeps blinking. Kept.
    elapsed = (float)(int32_t)((uint32_t)WorldTimer - (uint32_t)t)
              * CAR_TICK_SECONDS;

    return elapsed < c->BlinkDuration;
}

// 0x001315f0. Two seconds is built with `lui at,0x4000`, not loaded.
void car_blink_blink_poof(Car *c)
{
    car_start_blinking(c, 2.0f);
    c->bVisibleOnTrackMap = 0;
    c->bPoofed = 1;
}

// 0x001316f8.
int32_t car_is_poofed(Car *c)
{
    return c->bPoofed;
}

// --------------------------------------------------------------- the state

// `cvt.w.s`, all of it.
//
// Truncation toward zero is the easy half and a C cast already does it. The
// other half is what happens off the ends: the R5900 saturates *by the sign
// of the source*, 0x7fffffff for a value at or above 2^31 and 0x80000000 for
// one below -2^31. A bare C cast does not reproduce that -- the conversion is
// undefined behaviour in C, and the three targets disagree about it in
// practice. ARM's `vcvt.s32.f32` saturates by sign and so agrees with the
// R5900; x86-64's `cvttss2si` returns 0x80000000 for *either* overflow, so
// the host build of this port would disagree with both the console and the
// handheld on a positive one.
//
// So it is written out. tools/camera_check.py's `trunc_w` is the same
// function on the model side and has been since the camera slice. The
// negative threshold there is spelled `<= -2147483649.0`, which selects the
// same set of float32 values as `< -2147483648.0f` does here: the next
// float32 below -2^31 is -2147483904, and nothing lies between them.
//
// Static because Car is the first caller. When a second one appears this
// moves to a header -- not bmath.h or emath.h, which are faithful ports of
// bMath.obj and eMath.obj and own no invented functions.
static int32_t car_trunc_w(float x)
{
    if (x != x)                     // no NaN reaches the EE FPU; defined anyway
        return 0;
    if (x >= 2147483648.0f)
        return (int32_t)0x7fffffff;
    if (x < -2147483648.0f)
        return (int32_t)0x80000000;
    return (int32_t)x;
}

// 0x00130ee0. Position x + y, scaled by 65536 and truncated. A rounding
// conversion would disagree on every negative half.
int32_t car_calculate_debug_checksum(Car *c)
{
    float s = c->State.Position.x + c->State.Position.y;
    return car_trunc_w(s * 65536.0f);
}

// 0x00133128. A quarter per wheel on the ground, summed in wheel order --
// and the order matters, because four float adds of 0.25f do not associate
// freely once the running total leaves the exactly-representable range.
// They do here, but the loop is left in its original shape rather than
// replaced with a count times 0.25f.
float car_get_wheels_on_ground(Car *c)
{
    float n = 0.0f;
    int i;

    for (i = 0; i < 4; i++)
        if (c->State.WheelTouchingGround[i] != 0)
            n = n + 0.25f;

    return n;
}

// 0x001330e0. The larger of the two *diagonals*, not the larger of the two
// axles: the listing pairs wheel 0 with wheel 3 and wheel 1 with wheel 2.
// Reading it as front-and-rear gives the same answer on a symmetric car and
// a different one on every asymmetric slide.
float car_get_wheel_traction(Car *c)
{
    const float *u = c->State.WheelTractionUsage;
    float a = (u[0] + u[3]) * 0.5f;
    float b = (u[1] + u[2]) * 0.5f;

    return (a < b) ? b : a;
}

// 0x00134188.
int32_t car_should_sound_effects_be_generated(Car *c)
{
    if (car_is_poofed(c))
        return 0;

    return c->RenderingEnabled != 0;
}

// 0x00134130. Traffic cars make no visual effects at all, and that test
// comes first -- before the poof test, and before RenderingEnabled is even
// loaded.
int32_t car_should_visual_effects_be_generated(Car *c)
{
    if (c->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)
        return 0;

    if (car_is_poofed(c))
        return 0;

    return c->RenderingEnabled != 0;
}

// 0x00133db8. Below 0.1 of velocity magnitude the direction of travel is
// noise, so the answer is the *magnitude* of the acceleration rather than
// its forward component -- unsigned, and therefore never negative no matter
// which way the car is being pushed. Above it, the forward component is the
// dot of the acceleration with the normalized velocity.
//
// `vrsqrt Q,vf00w,vf01x` is a divide by a square root on the VU, not a fast
// estimate, so `1.0f / sqrtf(len2)` is exact for the port -- the same
// reading wheel.c's normalize3 takes.
float car_get_forward_acceleration(Car *c)
{
    const bVector3 *v = &c->State.Velocity;
    const bVector3 *a = &c->State.Acceleration;
    float len2, inv, nx, ny, nz;

    if (c->State.VelocityMagnitude < 0.1f)
        return sqrtf(a->x * a->x + a->y * a->y + a->z * a->z);

    len2 = v->x * v->x + v->y * v->y + v->z * v->z;
    inv  = 1.0f / sqrtf(len2);

    nx = v->x * inv;
    ny = v->y * inv;
    nz = v->z * inv;

    return nx * a->x + ny * a->y + nz * a->z;
}

// --------------------------------------------------- the horn and the lights

// 0x00132508. A request, not an action: it records what the car wants and
// UpdateHeadlightsAndHorn acts on it. The guard is that the previous
// request's whole cycle -- on, off, on -- has already elapsed, so a second
// honk inside the first one is dropped rather than queued.
//
// The cycle is `On + Off + On` and it is summed in that order, with the
// *old* durations, before the new ones are stored.
void car_honk_and_or_blink_headlights(Car *c, float onDuration,
                                      float offDuration, int32_t blink,
                                      int32_t honk, int32_t two)
{
    float elapsed = (float)(int32_t)((uint32_t)WorldTimer
                                     - (uint32_t)c->HeadlightsAndHornStartTime)
                    * CAR_TICK_SECONDS;
    float cycle = c->HeadlightsAndHornOnDuration
                  + c->HeadlightsAndHornOffDuration
                  + c->HeadlightsAndHornOnDuration;

    if (cycle < elapsed) {
        c->WantTwoHonksAndOrBlinks      = two;
        c->HeadlightsAndHornStartTime   = WorldTimer;
        c->HeadlightsAndHornOnDuration  = onDuration;
        c->HeadlightsAndHornOffDuration = offDuration;
        c->WantToBlinkHeadlights        = blink;
        c->WantToHonkHorn               = honk;
    }
}

// -------------------------------------------------------------- the wipers

// 0x001319c0. Integer frames, not seconds, and the only method in this slice
// that reads WorldTimeFrames rather than WorldTimer.
//
// The shape is a window merge. `WiperOnTime` and `WiperOffTime` are a
// half-open window of frames during which the wipers run; a new request
// either extends the window it overlaps or replaces it if the old one has
// already passed. Then the off-time is rounded *up* to a whole number of
// 82-frame wipes measured from the on-time, so a wipe that has started
// always finishes.
//
// Nothing happens at all while `WiperState` is non-zero: the wipers are
// already being driven and a request would fight the animation.
void car_turn_wipers_on_for_duration(Car *c, int32_t on, int32_t off)
{
    int32_t now = WorldTimeFrames;
    int32_t start, end, span;

    if (c->WiperState != 0)
        return;

    start = c->WiperOnTime;

    if (start < now) {
        // The old window has started. Keep its end if it has not passed
        // yet, otherwise start a fresh one at `on`.
        end = c->WiperOffTime;
        if (!(now < end)) {
            start = on;
            c->WiperOnTime = on;
        }
    } else {
        // The old window has not started. An earlier request wins.
        if (on < start) {
            start = on;
            c->WiperOnTime = on;
        }
        end = c->WiperOffTime;
    }

    if (end < off) {
        c->WiperOffTime = off;
        end = off;
    }

    span = end - start;

    // `(span + 81) / 82 * 82`, a signed divide in the listing. A span that
    // came out negative -- which the merge above can produce when a caller
    // passes an `off` before its own `on` -- divides toward zero and the
    // result lands short of `start`. Kept: the original does the same.
    c->WiperOffTime = (span + (CAR_WIPER_PERIOD_FRAMES - 1))
                      / CAR_WIPER_PERIOD_FRAMES * CAR_WIPER_PERIOD_FRAMES
                      + start;
}

// ------------------------------------------------------ the borrowed fields

// 0x00138e90, and all eight bytes of it:
//
//     00138e90  j     0x001b6ab0   <WorldToCar__8CarStateP8bVector2T1>
//     00138e94  addiu a0,a0,64
//
// A tail call with `this + 64`, which is the embedded CarState. Only the
// 2D overload exists -- there is no `WorldToCar__3CarP8bVector3T1` in the
// image -- and it is one of the six Car methods the compiler emitted
// outside Car.obj.
//
// It is not among the thirty-four, because CarState::WorldToCar is outside
// the class. It is here anyway: the callee has been ported since the
// CarState slice, so nothing is stood in for.
void car_world_to_car(Car *c, bVector2 *out, const bVector2 *in)
{
    carstate_world_to_car2(&c->State, out, in);
}


// 0x00131070. `CarDriver::Steering` is a BAM at 528 and is read with `lhu`,
// so a steering angle past half a turn comes back as a large positive
// number rather than a negative one.
uint16_t car_get_steering(Car *c)
{
    return c->pCarDriver->Steering;
}

// ---------------------------------------------------------------------------
// What is NOT here, and what each one waits on. Measured from the listing,
// not guessed.
//
// Thirty-four methods make no call outside Car. Seventeen of them are in
// this file; the other seventeen split two ways.
//
// Ten dispatch through a vtable. CarController, CarDriver, CarMover,
// CarDamage and CollisionBody are abstract bases whose vtable this port
// models as a stored word, so a call through one cannot be written yet:
//
//   Think, Drive, GetRoute, GetRoutePoint, GetAmountOutOfBounds, UpdateSound,
//   IsCollideable, SetToPhysicsMode, UpdateHeadlightsAndHorn,
//   IsFacingWrongWay (through GetRoutePoint)
//
// Seven call only other Car methods, but those callees reach a class that
// belongs to task 26 or 27 -- which is why "makes no call outside the
// class" is not the same as "can be written today":
//
//   DoWheelForces                Suspension, through PhysicsCar
//   GetCarSpaceBoundingBox,
//     GetLastPenetrationTime     CollisionBody / CarCollisionBody
//   GetTrackedAcceleration       a RealController field at +20
//   SetFrictionBoost             a PhysicsCar field at +108
//   CalculateDraftFactor         pCurrentWorld's car list, and Graph
//   PutFlatOnTrack               FindFlatOnTrackPosition, which needs a real
//                                TopologyCoordinate
//
// 17 + 10 + 7 = 34, and the arithmetic closing is the check that the three
// groups are a partition and not three overlapping lists.
//
// The other forty-six all call out of the class directly: the constructor
// and destructor, the reset and damage groups, the render and sound groups,
// the two force-feedback methods, and among them four that read as though
// they belonged above but do not -- UpdatePosition and MaybeCameraShake
// (the effect system), FixBlownTires (RealDriver::ForceEBrakeStop) and
// FindFlatOnTrackPosition (TopologyCoordinate).
