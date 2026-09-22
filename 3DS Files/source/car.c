// car -- Car.obj, slices one and two.
//
// Thirty-four of Car's eighty methods make no call outside the class.
// That is not the same as "can be written today": the count is of `jal`
// targets, so a method whose only calls are to other Car methods lands
// there even when one of those is itself blocked.
//
// Slice one was the seventeen of the thirty-four that touch nothing but
// Car. Slice two adds the vtable seam (vtable.h) and, with it, the nine
// methods that only dispatch through a controller, driver, sound or
// collision body; the three that read one field of a class Car points at;
// and the draft, both overloads, with the static initialiser that builds
// its tables. Thirty of the thirty-four are here now. The four that are
// not are listed at the bottom with what each is waiting for, so the next
// slice does not have to re-derive the dependency graph.
//
// Layout, enums, globals and every prototype: car.h. Cross-check:
// tools/car_check.py. Write-up: docs/formats/car.md.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "car.h"

// car.h names CarDriver and CarTypeInfo without including their headers, to
// keep out of the cycle cardriver.h -> drivetarget.h -> car.h. GetSteering
// reads through the pointer and four methods dispatch through its vptr, so
// the complete record is needed here.
#include "cardriver.h"
#include "sound3d.h"
#include "vtable.h"
#include "world.h"

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

// ------------------------------------------------------- the static tables
//
// `_GLOBAL_$I$fDraftFalloff`, 0x001347c0, the object's one static
// initialiser. The image runs it from its constructor list at boot, which
// the handheld build does not have, so whoever brings the game up calls it
// once before the first car thinks.
//
// fDraftFalloff is not written here: it is the one table the image carries
// initialised in .data. Everything else is built by stores. The three
// Graphs and the Table alias their arrays rather than copying them, so the
// order of the stores against the inits is visible only through the arrays
// -- but it is kept anyway.

const float fDraftFalloff[6] = {
    1.0f, 0.9f, 0.75f, 0.55f, 0.3f, 0.0f
};

bVector2 vDraftSpeedRange[4];
Table    tDraftFalloff;
Graph    gDraftSpeedRange;
bVector2 vRoadNoiseSpeedData[2];
Graph    gRoadNoiseSpeedScale;
bVector3 ObjectPoints[13];
bVector4 DamageAboveMatrix[4];
bVector2 PostCollisionYawControlProfileData[4];
Graph    PostCollisionYawControlProfile;

static void set2(bVector2 *v, float x, float y)
{
    v->x = x;
    v->y = y;
}

// x, y and z only: the initialiser never stores an ObjectPoints pad lane,
// so each stays the zero the image's .bss gives it.
static void set3(bVector3 *v, float x, float y, float z)
{
    v->x = x;
    v->y = y;
    v->z = z;
}

static void set4(bVector4 *v, float x, float y, float z, float w)
{
    v->x = x;
    v->y = y;
    v->z = z;
    v->w = w;
}

void car_static_init(void)
{
    // (speed, factor) -- and CalculateDraftFactor also reads two of these
    // knees directly as thresholds: [1].x is the slowest car worth drafting
    // and [3].y is the farthest one can be.
    set2(&vDraftSpeedRange[0],   0.0f,  0.0f);
    set2(&vDraftSpeedRange[1],   1.0f,  0.0f);
    set2(&vDraftSpeedRange[2],   5.0f, 10.0f);
    set2(&vDraftSpeedRange[3], 150.0f, 60.0f);

    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 1.0f);
    graph_init(&gDraftSpeedRange, vDraftSpeedRange, 4);

    // 5 km/h and 50 km/h in metres per second, as the image rounds them:
    // 0x3fb1c71d and 0x415e38e4, loaded from gp-31900 and gp-31896.
    set2(&vRoadNoiseSpeedData[0],  1.388889f, 0.0f);
    set2(&vRoadNoiseSpeedData[1], 13.888889f, 1.0f);
    graph_init(&gRoadNoiseSpeedScale, vRoadNoiseSpeedData, 2);

    // Thirteen points above the car: the origin, then three rings of four
    // at heights 3, 4 and 9 with radii 3, 1 and 3, each ring in the order
    // +x, -y, -x, +y.
    set3(&ObjectPoints[0],   0.0f,  0.0f, 0.0f);
    set3(&ObjectPoints[1],   3.0f,  0.0f, 3.0f);
    set3(&ObjectPoints[2],   0.0f, -3.0f, 3.0f);
    set3(&ObjectPoints[3],  -3.0f,  0.0f, 3.0f);
    set3(&ObjectPoints[4],   0.0f,  3.0f, 3.0f);
    set3(&ObjectPoints[5],   1.0f,  0.0f, 4.0f);
    set3(&ObjectPoints[6],   0.0f, -1.0f, 4.0f);
    set3(&ObjectPoints[7],  -1.0f,  0.0f, 4.0f);
    set3(&ObjectPoints[8],   0.0f,  1.0f, 4.0f);
    set3(&ObjectPoints[9],   3.0f,  0.0f, 9.0f);
    set3(&ObjectPoints[10],  0.0f, -3.0f, 9.0f);
    set3(&ObjectPoints[11], -3.0f,  0.0f, 9.0f);
    set3(&ObjectPoints[12],  0.0f,  3.0f, 9.0f);

    // Half scale, lifted one unit, as four rows -- all sixteen words
    // stored, the last row's w included.
    set4(&DamageAboveMatrix[0], 0.5f, 0.0f, 0.0f, 0.0f);
    set4(&DamageAboveMatrix[1], 0.0f, 0.5f, 0.0f, 0.0f);
    set4(&DamageAboveMatrix[2], 0.0f, 0.0f, 0.5f, 0.0f);
    set4(&DamageAboveMatrix[3], 0.0f, 0.0f, 1.0f, 1.0f);

    // 0.4 is 0x3ecccccd from gp-31892; the 2.0 is built with `lui 0x4000`.
    set2(&PostCollisionYawControlProfileData[0], 0.0f, 0.0f);
    set2(&PostCollisionYawControlProfileData[1], 0.4f, 1.0f);
    set2(&PostCollisionYawControlProfileData[2], 1.0f, 1.0f);
    set2(&PostCollisionYawControlProfileData[3], 2.0f, 0.0f);

    // The listing's last instruction is a `j` to the Graph constructor: a
    // tail call.
    graph_init(&PostCollisionYawControlProfile,
               PostCollisionYawControlProfileData, 4);
}

// --------------------------------------------------------------- the draft
//
// A car close behind another, pointed at it and fast enough, gets a factor
// the physics reads as reduced drag. The two constants in the cone test are
// the image's own words: 0.95f (0x3f733333, gp-32092) and 19.999996f
// (0x419ffffe, gp-32088) -- 1 / (1 - 0.95f) as float32 arithmetic gives it,
// not the 20.0f a person would type.

#define CAR_DRAFT_CONE_COS   0.95f
#define CAR_DRAFT_CONE_SCALE 19.999996f

// 0.9f at gp-32084 and again at gp-32080: two literal-pool words holding
// the same value, one the loop's early-out and one the `min.s` cap. They
// get two names because they are two words, and a mutation that moves one
// of them without the other is a real change.
#define CAR_DRAFT_EARLY_OUT 0.9f
#define CAR_DRAFT_CAP       0.9f

// 0x0012ffc8. What `other`, running ahead, gives `c`.
//
// VU order throughout: `vmul.xyz` then `vaddy.x` then `vaddz.x`, so each
// length and dot is ((x + y) + z). The distance's square root is the FPU's
// `sqrt.s`; the velocity's is `vrsqrt`, a divide by a square root, read as
// `1.0f / sqrtf` the way car_get_forward_acceleration reads it.
float car_calculate_draft_factor_from(Car *c, Car *other)
{
    float speed = other->State.VelocityMagnitude;
    const bVector3 *v = &other->State.Velocity;
    float dx, dy, dz, dist, len2, inv, nx, ny, nz, dot, f, g;

    if (speed < vDraftSpeedRange[1].x)
        return 0.0f;

    // `vsub.xyzw`, but the w lane is never read again.
    dx = other->State.Position.x - c->State.Position.x;
    dy = other->State.Position.y - c->State.Position.y;
    dz = other->State.Position.z - c->State.Position.z;
    dist = sqrtf((dx * dx + dy * dy) + dz * dz);

    if (vDraftSpeedRange[3].y < dist)
        return 0.0f;

    len2 = (v->x * v->x + v->y * v->y) + v->z * v->z;
    inv  = 1.0f / sqrtf(len2);
    nx = v->x * inv;
    ny = v->y * inv;
    nz = v->z * inv;

    // Positive when `other` is ahead along its own direction of travel.
    // The cosine of the angle off its tail, shifted and scaled so the edge
    // of the cone is 0 and dead astern is about 1.
    dot = (dx * nx + dy * ny) + dz * nz;
    f = (dot / dist - CAR_DRAFT_CONE_COS) * CAR_DRAFT_CONE_SCALE;

    // `c.lt.s f, 0` then bc1f: a NaN is not less than zero, so it goes on
    // to the lookups rather than returning here. Kept.
    if (f < 0.0f)
        return 0.0f;

    g = graph_get_value(&gDraftSpeedRange, speed);
    return table_get_value(&tDraftFalloff, dist / (f * g));
}

// 0x001300f0. Every car in the world but this one, summed, stopping as
// soon as the running total reaches the cap and returning it capped.
//
// Three things the loop does exactly as the listing does:
//
//   * pCurrentWorld is reloaded at the top of every pass, and so is the
//     count.
//   * the early-out runs after every car, this one included -- skipping
//     `c` skips the add, not the test.
//   * nothing bounds the index but TotalNumCars. The table holds fourteen,
//     and a count above that reads past it in the image as it would here.
//
// The cap is `min.s`. Written as a compare it agrees with the R5900 for
// every value the sum can hold, a NaN included: the EE's min orders a NaN
// pattern as a large positive number and so returns the cap, which is the
// answer `sum < CAR_DRAFT_CAP` gives by failing.
float car_calculate_draft_factor(Car *c)
{
    float sum = 0.0f;
    int32_t i;

    for (i = 0; i < pCurrentWorld->TotalNumCars; i++) {
        Car *o = pCurrentWorld->CarTable[i];

        if (o != c)
            sum = sum + car_calculate_draft_factor_from(c, o);
        if (CAR_DRAFT_EARLY_OUT <= sum)
            break;
    }

    return (sum < CAR_DRAFT_CAP) ? sum : CAR_DRAFT_CAP;
}

// ---------------------------------------------------------- the dispatchers
//
// Each of these is the four-instruction call vtable.h describes: the vptr
// from the object's own offset, the entry at the slot's byte offset, the
// delta added to the object pointer, the call. A slot's real signature is
// one of the typedefs below, and the entry's `fn` is cast to it at the call
// and nowhere else.

typedef void             (*VtVoidFn)(void *self);
typedef void             (*VtVoidFloatFn)(void *self, float f);
typedef int32_t          (*VtBoolFn)(void *self);
typedef float            (*VtFloatFn)(void *self);
typedef TrackRoute      *(*VtRouteFn)(void *self);
typedef TrackRoutePoint *(*VtRoutePointFn)(void *self);
typedef void             (*VtSoundUpdateFn)(void *self, float a,
                                            uint16_t b, float c);

// 0x00130180. The draft factor first, stored, then the controller's Think
// with the same dt, which the listing keeps across the first call in f20.
void car_think(Car *c, float dt)
{
    CarController *ctl;
    const VtEntry *e;

    c->DraftFactor = car_calculate_draft_factor(c);

    ctl = c->pCarController;
    e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_THINK);
    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), dt);
}

// 0x001301d0. The driver's vptr is at 556, after the embedded DriveTarget.
void car_drive(Car *c, float dt)
{
    CarDriver *d = c->pCarDriver;
    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DRIVE);

    ((VtVoidFloatFn)e->fn)(vt_this(d, e), dt);
}

// 0x00131740.
TrackRoute *car_get_route(Car *c)
{
    CarController *ctl = c->pCarController;
    const VtEntry *e = vt_slot(ctl->_vtable,
                               CARCONTROLLER_VT_GET_CURRENT_ROUTE);

    return ((VtRouteFn)e->fn)(vt_this(ctl, e));
}

// 0x00131770.
TrackRoutePoint *car_get_route_point(Car *c)
{
    CarController *ctl = c->pCarController;
    const VtEntry *e = vt_slot(ctl->_vtable,
                               CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);

    return ((VtRoutePointFn)e->fn)(vt_this(ctl, e));
}

// 0x001317a0.
float car_get_amount_out_of_bounds(Car *c)
{
    CarController *ctl = c->pCarController;
    const VtEntry *e = vt_slot(ctl->_vtable,
                               CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS);

    return ((VtFloatFn)e->fn)(vt_this(ctl, e));
}

// 0x00133480. Nothing without a sound. Otherwise Update(1.0f, 0, 1.0f):
// both floats from one `lui 0x3f80`, copied to f13, and the short in a1,
// zeroed in the delay slot of the null test.
//
// BaseCarSound is opaque to the port until task 29; its first base is
// Sound3d at offset 0, and this is Sound3d's vptr.
void car_update_sound(Car *c)
{
    BaseCarSound *snd = c->pBaseCarSound;
    const VtEntry *e;

    if (!snd)
        return;

    e = vt_slot(((Sound3d *)snd)->_vtable, SOUND3D_VT_UPDATE);
    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 0, 1.0f);
}

// 0x001316a0. A blinking car is never collideable, and the body is not
// asked. Otherwise the body's own AreCollisionsEnabled, normalised to 0 or
// 1 by `sltu s1,zero,v0`.
int32_t car_is_collideable(Car *c)
{
    CarCollisionBody *b;
    const VtEntry *e;

    if (car_is_blinking(c))
        return 0;

    b = c->pDynamicCollisionBody;
    e = vt_slot(b->Dynamic.Body._vtable,
                COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED);
    return ((VtBoolFn)e->fn)(vt_this(b, e)) != 0;
}

// 0x001318b8. The car's forward axis against the route's direction, in the
// ground plane only: BodyMatrix row 0 is Car+144 and Car+148, and the route
// point's Direction is at +12 and +16.
//
// Wrong way is "not strictly positive", so a car exactly across the road --
// and a NaN -- is facing the wrong way.
int32_t car_is_facing_wrong_way(Car *c)
{
    TrackRoutePoint *rp = car_get_route_point(c);
    const bVector4 *fwd = &c->State.BodyMatrix.v0;
    float dot = fwd->x * rp->Direction.x + fwd->y * rp->Direction.y;

    return (0.0f < dot) ? 0 : 1;
}

// 0x00132568. Acts on what car_honk_and_or_blink_headlights asked for.
// Player cars are skipped entirely.
//
// The request is a cycle of on, off, on, measured from the stamp, and `lit`
// says whether this moment is in an on phase. Two things about it are easy
// to get backwards:
//
//   * during the *off* phase, `lit` is `WantTwoHonksAndOrBlinks == 0`. A
//     single request stays on straight through the gap, and only a double
//     one goes dark in it.
//   * after the second on phase the answer is simply off -- the elapsed
//     time is not reduced modulo anything.
//
// The horn is edge-driven through the driver: IsHonking is asked first, and
// Start or Stop is called only on a change. The driver pointer is reloaded
// from the car before the second call of each pair.
void car_update_headlights_and_horn(Car *c)
{
    float elapsed, on, t;
    int32_t lit, honk;
    CarDriver *d;
    const VtEntry *e;

    if (c->pPlayer)
        return;

    elapsed = (float)(int32_t)((uint32_t)WorldTimer
                               - (uint32_t)c->HeadlightsAndHornStartTime)
              * CAR_TICK_SECONDS;
    on = c->HeadlightsAndHornOnDuration;

    if (elapsed < on) {
        lit = 1;
    } else {
        t = elapsed - on;
        if (t < c->HeadlightsAndHornOffDuration)
            lit = (c->WantTwoHonksAndOrBlinks == 0);
        else
            lit = (t - c->HeadlightsAndHornOffDuration < on);
    }

    c->HeadlightsState = (lit && c->WantToBlinkHeadlights)
                         ? 1 : (c->ForceHeadlightsOn != 0);

    honk = lit ? (c->WantToHonkHorn != 0) : 0;

    d = c->pCarDriver;
    e = vt_slot(d->_vtable, CARDRIVER_VT_IS_HONKING);

    if (honk) {
        if (((VtBoolFn)e->fn)(vt_this(d, e)))
            return;
        d = c->pCarDriver;
        e = vt_slot(d->_vtable, CARDRIVER_VT_START_HONK_HORN);
        ((VtVoidFn)e->fn)(vt_this(d, e));
    } else {
        if (!((VtBoolFn)e->fn)(vt_this(d, e)))
            return;
        d = c->pCarDriver;
        e = vt_slot(d->_vtable, CARDRIVER_VT_STOP_HONK_HORN);
        ((VtVoidFn)e->fn)(vt_this(d, e));
    }
}

// ------------------------------------------ the borrowed fields, continued

// 0x001334c0. Two quadword copies, the pad lanes included, min before max.
void car_get_car_space_bounding_box(Car *c, bVector3 *min, bVector3 *max)
{
    CarCollisionBody *b = c->pDynamicCollisionBody;

    *min = b->Dynamic.LocalBBMin;
    *max = b->Dynamic.LocalBBMax;
}

// 0x001334e0. The Timer is one word and comes back in v0.
Timer car_get_last_penetration_time(Car *c)
{
    return c->pDynamicCollisionBody->LastPenetrationTime;
}

// 0x0012ff40. Only a REAL_CONTROL car's controller is a TrackedController;
// every other mode answers 0 without reading the controller at all -- the
// load is in the delay slot of a `beql`, annulled when the test fails.
float car_get_tracked_acceleration(Car *c)
{
    if (c->TheControlMode == REAL_CONTROL)
        return ((TrackedController *)c->pCarController)->Acceleration;

    return 0.0f;
}

// ---------------------------------------------------------------------------
// What is NOT here, and what each one waits on. Measured from the listing,
// not guessed.
//
// Thirty of the thirty-four no-outside-call methods are in this file: the
// seventeen of slice one, nine dispatchers, the three borrowed-field reads
// above, and CalculateDraftFactor's no-argument form. The other four:
//
//   SetToPhysicsMode    dispatches through the controller, and its other
//                       arm tail-calls SetMovementMode(MELLOW_MOVEMENT),
//                       whose jump table constructs every mover. It comes
//                       with SetMovementMode and PhysicsCar.
//   SetFrictionBoost    stores into PhysicsCar at +108 when the car is
//                       under PHYSICS_MOVEMENT; PhysicsCar's slice.
//   DoWheelForces       `if (pPlayer) CalcForceParameters(...)`, and that
//                       is the force-feedback method: six
//                       PortSetForceConditionData calls, six
//                       PortSetForcePeriodicData, PortPlayShake. Not
//                       physics -- the wheel peripheral's motors.
//   PutFlatOnTrack      FindFlatOnTrackPosition, which needs a real
//                       TopologyCoordinate (task 27).
//
// 30 + 4 = 34, and the arithmetic closing is the check that the groups are
// a partition and not overlapping lists.
//
// Of the forty-six that call out of the class directly, two are here:
// CalculateDraftFactor(Car *), whose calls are Graph and Table, and
// car_world_to_car, whose `j` leaves the class for CarState::WorldToCar.
// The other forty-four are the constructor and destructor, the reset and
// damage groups, the render and sound groups, the two force-feedback
// methods, and among them four that read as though they belonged above but
// do not --
// UpdatePosition and MaybeCameraShake (the effect system), FixBlownTires
// (RealDriver::ForceEBrakeStop) and FindFlatOnTrackPosition
// (TopologyCoordinate).
//
// The eighty are the whole class. Seventy-four are in Car.obj; the other
// six were emitted in other objects, car_world_to_car and car_print_above
// among them. car_static_init is the object's static initialiser, which is
// not a method at all.
