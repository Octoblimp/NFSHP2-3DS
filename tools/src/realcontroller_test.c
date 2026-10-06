// Harness for tools/realcontroller_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the stand-ins, the heap,
// the arena and why every pointer prints as a label.
//
//     realcontroller_test ops.bin > out.txt
//
// The world clock's globals are defined here rather than linked from
// realtime.c, which would bring the joylog in behind it. The loop counter
// starts at the image's 100000.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "average.h"
#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "collisionbody.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "joyevent.h"
#include "joystick.h"
#include "player.h"
#include "quickspline.h"
#include "race.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"

int32_t WorldTimer;
int32_t WorldTimeFrames;
float   WorldTimeElapsed;
int32_t WorldLoopCounter = 100000;

enum {
    OP_TAG, OP_CLEAR, OP_WORDS, OP_ROUTE, OP_SIGNS, OP_RESET, OP_ADD,
    OP_FILL, OP_INIT, OP_TINIT, OP_DUMP, OP_CARF, OP_GLOB, OP_CTLF, OP_CALL,
    OP_VT, OP_TGT, OP_STATIC
};

enum {
    F_THINK, F_TTHINK, F_FIND, F_OOB, F_SET_ROUTE, F_GET_ROUTE, F_GET_POINT,
    F_GET_ACC, F_JUST_RESET, F_LINE, F_RDP, F_COMBO, F_LATERAL, F_DESTROY,
    F_TDESTROY
};

#define ARENA_SIZE  0x80000
#define NSIGNS      256
#define MAX_ROUTES  64
#define HDR         1064
#define PT          112
#define TGT_SIZE    528
#define HEAP_FILL   0xC3
#define OUT_FILL    0x7F7F7F7Fu
#define MAX_BLOCKS  4096

// QuickSpline's buffer holds this many more points than the image's; see
// QUICKSPLINE_SLACK_POINTS in quickspline.c.
#define QS_SLACK_BYTES 16

// ------------------------------------------------------------ the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **out = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float bitsf(int32_t b)
{
    float f;

    memcpy(&f, &b, sizeof f);
    return f;
}

static uint32_t fnv_add(uint32_t h, const void *p, size_t n)
{
    const uint8_t *b = p;
    size_t         i;

    for (i = 0; i < n; i++)
        h = (h ^ b[i]) * 0x01000193u;
    return h;
}

// ---------------------------------------------------------- the objects

static _Alignas(16) uint8_t arena[ARENA_SIZE];
static Signpost              signs[NSIGNS];
static int32_t               route_off[MAX_ROUTES];

static Car                car;
static CarTypeInfo        cti;
static struct Player      player;
static CarCollisionBody   body;
static _Alignas(16) uint8_t ctlmem[2][sizeof(RealController)];
static DriveTarget        tgt;
static float              out_pos, out_vel;

static RealController *ctl(int slot)
{
    return (RealController *)(void *)ctlmem[slot];
}

// The heap: every block bMalloc handed out, in order, never freed.
static struct {
    uint8_t *p;
    size_t   size;
} blocks[MAX_BLOCKS];
static int nblocks;

static int32_t arena_i32(int32_t off)
{
    int32_t v;

    memcpy(&v, arena + off, sizeof v);
    return v;
}

// An arena offset, or -1 for NULL.
static void *ref(int32_t off)
{
    if (off < 0)
        return NULL;
    if (off >= ARENA_SIZE) {
        fprintf(stderr, "ref %d outside the arena\n", (int)off);
        exit(2);
    }
    return arena + off;
}

// ------------------------------------------------------------ the labels

static int is_block(const void *p)
{
    int i;

    for (i = 0; i < nblocks; i++)
        if (blocks[i].p == p)
            return 1;
    return 0;
}

// What the model prints for the same object: a fixed one's name, a heap
// block's, a route's or one of its points', an offset into the arena, a
// word of one repeated byte, or `?`.
static const char *label(const void *a)
{
    static char buf[8][64];
    static int  which;
    char       *b = buf[which++ & 7];
    uintptr_t   u = (uintptr_t)a;
    int         i, s;

    if (a == NULL)                       return "null";
    if (a == &car)                       return "car";
    if (a == &cti)                       return "cti";
    if (a == &player)                    return "pl";
    if (a == &body)                      return "body";
    if (a == ctlmem[0])                  return "c0";
    if (a == ctlmem[1])                  return "c1";
    if (a == &tgt)                       return "tgt";
    if (a == QuickSplineBasisMatricies)  return "basis";
    for (i = 0; i < nblocks; i++) {
        uint8_t *p = blocks[i].p;

        if ((const uint8_t *)a >= p && (const uint8_t *)a < p + blocks[i].size) {
            if ((const uint8_t *)a == p)
                snprintf(b, 64, "h%d", i);
            else
                snprintf(b, 64, "h%d+%d", i, (int)((const uint8_t *)a - p));
            return b;
        }
    }
    if ((const uint8_t *)a >= arena && (const uint8_t *)a < arena + ARENA_SIZE) {
        int32_t off = (int32_t)((const uint8_t *)a - arena);

        for (s = 0; s < MAX_ROUTES; s++) {
            int32_t base = route_off[s], t, np;

            if (base < 0)
                continue;
            if (off == base) {
                snprintf(b, 64, "r%d", s);
                return b;
            }
            t = base + HDR;
            np = arena_i32(base + 16);
            if (np > 0 && off >= t && off < t + PT * np && (off - t) % PT == 0) {
                snprintf(b, 64, "r%d.p%d", s, (int)((off - t) / PT));
                return b;
            }
        }
        snprintf(b, 64, "a%+d", (int)off);
        return b;
    }
    {
        uintptr_t lo = u & 0xff, rep = 0;

        for (i = 0; i < (int)sizeof(uintptr_t); i++)
            rep = (rep << 8) | lo;
        if (u == rep) {
            snprintf(b, 64, "fill%02x", (unsigned)lo);
            return b;
        }
    }
    return "?";
}

static const char *vtname(uint32_t v, char *buf)
{
    switch (v) {
    case TRACKEDCONTROLLER_VTABLE: return "tc";
    case REALCONTROLLER_VTABLE:    return "rc";
    case CARCONTROLLER_VTABLE:     return "cc";
    case REALDRIVER_VTABLE:        return "rd";
    case CARDRIVER_VTABLE:         return "cd";
    }
    sprintf(buf, "%08x", (unsigned)v);
    return buf;
}

// ------------------------------------------------------- the stand-ins

static void fail(const char *what)
{
    fprintf(stderr, "%s: a RealDriver here never adds its handlers\n", what);
    exit(3);
}

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    (void)port; (void)ev; (void)fn; (void)obj;
    fail("AddJoyHandler");
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    (void)port; (void)ev;
    fail("RemoveJoyHandler");
}

int32_t IsJoystickPluggedIn(JoystickPort port)
{
    (void)port;
    fail("IsJoystickPluggedIn");
    return 0;
}

int32_t IsJoystickTypeWheel(JoystickPort port)
{
    (void)port;
    fail("IsJoystickTypeWheel");
    return 0;
}

int32_t DoesJoystickHaveStiffThrottle(JoystickPort port)
{
    (void)port;
    fail("DoesJoystickHaveStiffThrottle");
    return 0;
}

// carmodes.c's, which would bring the movers with it.
void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  set-movement-mode %s %d\n", label(c), (int)mode);
}

static void s_blur_off(int32_t view)
{
    printf("  blur-off %d\n", (int)view);
}

// ------------------------------------------------------------- the heap

static void free_hook(void *p)
{
    if (p != NULL)
        printf("  free %s\n", label(p));
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    int      shown = size;
    uint8_t *p;

    // The image's size for each record the port's is wider than.
    if (strcmp(name, "RealDriver") == 0 && size == (int)sizeof(RealDriver))
        shown = 640;
    else if (strcmp(name, "AverageInRealController") == 0
             && size == (int)sizeof(Average))
        shown = 24;
    else if (strcmp(name, "QuickSplineInRealController") == 0
             && size == (int)sizeof(QuickSpline))
        shown = 40;
    else if (strcmp(name, "..\\indep\\src\\quickspline.cpp") == 0)
        shown = size - QS_SLACK_BYTES;
    // The model is the demo's image, whose Average names line 120 of
    // table.cpp; the port's is retail's, line 167.
    if (strcmp(name, "..\\indep\\src\\table.cpp") == 0 && flags == 167)
        flags = 120;
    if (nblocks == MAX_BLOCKS) {
        fprintf(stderr, "out of blocks\n");
        exit(2);
    }
    p = malloc((size_t)size + 16);
    if (p == NULL) {
        fprintf(stderr, "malloc %d\n", size);
        exit(2);
    }
    memset(p, strcmp(name, "..\\indep\\src\\quickspline.cpp") == 0
                  ? 0 : HEAP_FILL, (size_t)size);
    blocks[nblocks].p = p;
    blocks[nblocks].size = (size_t)size;
    printf("  malloc %s %d flags %d pool %d -> h%d\n", name, shown, flags,
           pool, nblocks);
    nblocks++;
    return p;
}

// ------------------------------------------------------------- the fields

static void set_carf(int32_t field, int32_t v)
{
    float f = bitsf(v);

    switch (field) {
    case 0:  car.DriverNumber = (int16_t)v; break;
    case 1:  car.TheMovementMode = (MovementMode)v; break;
    case 2:  car.State.Position.x = f; break;
    case 3:  car.State.Position.y = f; break;
    case 4:  car.State.Position.z = f; break;
    case 5:  car.State.Position.pad = f; break;
    case 6:  car.State.Velocity.x = f; break;
    case 7:  car.State.Velocity.y = f; break;
    case 8:  car.State.Velocity.z = f; break;
    case 9:  car.State.Velocity.pad = f; break;
    case 10: car.State.Acceleration.x = f; break;
    case 11: car.State.Acceleration.y = f; break;
    case 12: car.State.BodyMatrix.v1.x = f; break;
    case 13: car.State.BodyMatrix.v1.y = f; break;
    case 14: car.State.Angle = (uint16_t)v; break;
    case 15: car.State.ForwardSpeed = f; break;
    case 16: car.State.VelocityMagnitude = f; break;
    case 17: car.State.BoostFactor = f; break;
    case 18: car.TheTrackPathCoordinate.DistanceAroundTrack = f; break;
    case 19: cti.CarClass = v; break;
    case 20: player.PlayerNumber = v; break;
    case 21: player.bWrongWay = v; break;
    case 22: body.Dynamic.LocalBBMin.x = f; break;
    case 23: body.Dynamic.LocalBBMin.y = f; break;
    case 24: body.Dynamic.LocalBBMin.z = f; break;
    case 25: body.Dynamic.LocalBBMax.x = f; break;
    case 26: body.Dynamic.LocalBBMax.y = f; break;
    case 27: body.Dynamic.LocalBBMax.z = f; break;
    default:
        fprintf(stderr, "carf %d\n", (int)field);
        exit(2);
    }
}

static void set_glob(int32_t id, int32_t v)
{
    switch (id) {
    case 0: WorldTimer = v; break;
    case 1: CameraFollowThisCarInstead = v; break;
    case 2: DoSpeedDifferencePrinting = v; break;
    case 3: TheDriveTargetRenderer.HasTargetMarkers = v; break;
    case 4: TheTrackPathManager.TrackLength = bitsf(v); break;
    case 5: RaceParametersTrackDirection = (eTrackDirection)v; break;
    case 6: NumSignposts = (uint32_t)v; break;
    default:
        fprintf(stderr, "glob %d\n", (int)id);
        exit(2);
    }
}

static void set_ctlf(RealController *c, int32_t field, int32_t v)
{
    TrackedController *t = &c->Base;

    if (field >= 6 && field < 14) {
        NearestRoutePointInfo *e = &c->PreviousRoutePoints[(field - 6) / 2];

        if ((field - 6) % 2 == 0)
            e->Route = ref(v);
        else
            e->Point = ref(v);
        return;
    }
    switch (field) {
    case 0:  t->RoutePoint = ref(v); break;
    case 1:  t->TimeBeforeUpdate = bitsf(v); break;
    case 2:  t->Acceleration = bitsf(v); break;
    case 3:  t->PrevSpeed = bitsf(v); break;
    case 4:  c->PreviousLateralOffsetFromLine = bitsf(v); break;
    case 5:  c->NumPreviousRoutePoints = v; break;
    case 14: t->Base.Driver = NULL; break;
    case 15: c->LateralVelocityWRTLineAverage = NULL; break;
    case 16: c->DrivingLineSpline = NULL; break;
    default:
        fprintf(stderr, "ctlf %d\n", (int)field);
        exit(2);
    }
}

// ------------------------------------------------------------- the prints

static void print_target(const DriveTarget *t, const char *who)
{
    const uint8_t *raw = (const uint8_t *)t;
    uint32_t       pads = 0x811c9dc5u;
    int            i;

    pads = fnv_add(pads, raw + 1, 15);
    pads = fnv_add(pads, raw + 501, 3);
    pads = fnv_add(pads, raw + 516, 12);
    printf("  %s n %d tt %d wp %d wpct %d wpt %d len %08x pads %08x\n", who,
           (int)t->NumPoints, (int)t->TType, (int)t->WhichPointIPicked,
           (int)t->WhichPointIPickedCalculationTime,
           (int)t->WhichPointIPickedTime, (unsigned)fbits(t->Length),
           (unsigned)pads);
    for (i = 0; i < DRIVETARGET_MAX_POINTS; i++) {
        const bVector3 *p = &t->Points[i];

        printf("   p%d %08x %08x %08x spd %08x r %d n %d dl %d\n", i,
               (unsigned)fbits(p->x), (unsigned)fbits(p->y),
               (unsigned)fbits(p->z),
               (unsigned)fbits(t->CalculatedSpeed[i]), (int)t->Route[i],
               (int)t->RoutePointNumber[i], (int)t->DrivingLine[i]);
    }
}

static void dump(int slot)
{
    RealController    *c = ctl(slot);
    TrackedController *t = &c->Base;
    CarController     *b = &t->Base;
    char               vb[16], prev[256];
    int                i, n = 0;

    for (i = 0; i < REALCONTROLLER_PREVIOUS_POINTS; i++) {
        const char *r = label(c->PreviousRoutePoints[i].Route);
        const char *p = label(c->PreviousRoutePoints[i].Point);

        n += snprintf(prev + n, sizeof prev - (size_t)n, "%s%s/%s",
                      i ? " " : "", r, p);
    }
    printf("c%d vt %s car %s drv %s rp %s tbu %08x acc %08x ps %08x "
           "caf %s %08x lat %08x avg %s np %d prev %s spl %s rend %d "
           "boost %08x\n",
           slot, vtname(b->_vtable, vb), label(b->pCar), label(b->Driver),
           label(t->RoutePoint), (unsigned)fbits(t->TimeBeforeUpdate),
           (unsigned)fbits(t->Acceleration), (unsigned)fbits(t->PrevSpeed),
           label(t->pCaffeineObj), (unsigned)t->CaffeineObjHigh,
           (unsigned)fbits(c->PreviousLateralOffsetFromLine),
           label(c->LateralVelocityWRTLineAverage),
           (int)c->NumPreviousRoutePoints, prev,
           label(c->DrivingLineSpline),
           (int)TheDriveTargetRenderer.HasTargetMarkers,
           (unsigned)fbits(car.State.BoostFactor));

    if (is_block(c->LateralVelocityWRTLineAverage)) {
        const Average *a = c->LateralVelocityWRTLineAverage;
        char           vals[200] = "";
        int            k, m = 0;

        if (is_block(a->pData))
            for (k = 0; k < a->nSlots && k < 8; k++)
                m += snprintf(vals + m, sizeof vals - (size_t)m, "%s%08x",
                              k ? " " : "", (unsigned)fbits(a->pData[k]));
        printf("  avg n %d cur %d ns %d tot %08x av %08x data %s %s\n",
               (int)a->nSlots, (int)a->nCurrentSlot, (int)a->nSamples,
               (unsigned)fbits(a->fTotal), (unsigned)fbits(a->fAverage),
               label(a->pData), vals);
    }
    if (is_block(c->DrivingLineSpline)) {
        const QuickSpline *s = c->DrivingLineSpline;
        int                k;

        printf("  spl ept %d bt %d max %08x min %08x len %08x dirty %d "
               "ba %d minc %d maxc %d num %d buf %s cp %s basis %s\n",
               (int)s->EndPointType, (int)s->BasisType,
               (unsigned)fbits(s->MaxParam), (unsigned)fbits(s->MinParam),
               (unsigned)fbits(s->Length), (int)s->ControlPointsDirty,
               (int)s->BufferWasAllocated, (int)s->MinControlPoints,
               (int)s->MaxControlPoints, (int)s->NumControlPoints,
               label(s->pControlPointBuffer), label(s->pControlPoints),
               label(s->pBasisMatricies));
        if (is_block(s->pControlPointBuffer))
            for (k = 0; k < (s->MaxControlPoints < 8 ? s->MaxControlPoints
                                                     : 8) + 3; k++) {
                const bVector4 *q = &s->pControlPointBuffer[k];

                printf("   b%d %08x %08x %08x %08x\n", k,
                       (unsigned)fbits(q->x), (unsigned)fbits(q->y),
                       (unsigned)fbits(q->z), (unsigned)fbits(q->w));
            }
    }
    if (is_block(b->Driver)) {
        const RealDriver *d = (const RealDriver *)(const void *)b->Driver;

        printf("  drv vt %s car %s port %d ha %d\n",
               vtname(d->Base._vtable, vb), label(d->pCar), (int)d->Port,
               (int)d->HandlersAdded);
        print_target(&d->Base.MyDriveTarget, "dtgt");
    }
}

static const char *portname(VtFn fn)
{
    if (fn == NULL) return "null";
#define N(f) if (fn == (VtFn)(f)) return #f;
    N(trackedcontroller_destroy) N(realcontroller_destroy)
    N(carcontroller_debug_display) N(trackedcontroller_think)
    N(realcontroller_think) N(trackedcontroller_set_current_route)
    N(trackedcontroller_get_current_route)
    N(trackedcontroller_get_current_route_point)
    N(trackedcontroller_get_amount_out_of_bounds)
    N(trackedcontroller_find_where_i_am) N(trackedcontroller_just_reset)
    N(carcontroller_set_to_physics_mode) N(carcontroller_force_boost)
    N(carcontroller_release_boost)
#undef N
    return "?";
}

static void print_static(void)
{
    static const struct { const char *name; uint32_t vt; } tabs[2] = {
        { "tc", TRACKEDCONTROLLER_VTABLE }, { "rc", REALCONTROLLER_VTABLE },
    };
    int k, s;

    for (k = 0; k < 2; k++) {
        int            count;
        const VtEntry *e = vt_table(tabs[k].vt, &count);

        for (s = 1; s < count; s++)
            printf("vt %s %d %d %d %s\n", tabs[k].name, 8 * s,
                   (int)e[s].delta, (int)e[s].index, portname(e[s].fn));
    }
}

// ------------------------------------------------------------- the calls

typedef void             (*VVoid)(void *);
typedef void             (*VInt)(void *, int32_t);
typedef void             (*VFloat)(void *, float);
typedef void             (*VRoute)(void *, TrackRoute *, TrackRoutePoint *);
typedef void             (*VCar)(void *, Car *);
typedef TrackRoute      *(*RRoute)(void *);
typedef TrackRoutePoint *(*RPoint)(void *);
typedef float            (*RFloat)(void *);

static const char *const fname[] = {
    "Think", "Think", "FindWhereIAm", "GetAmountOutOfBounds",
    "SetCurrentRoute", "GetCurrentRoute", "GetCurrentRoutePoint",
    "GetAcceleration", "JustReset", "PlayerDriveLineNumber",
    "RouteDeltaPredict", "ComboPredict",
    "CalculateLateralPostionAndVelocityWRTDrivingLine", "_$_14RealController",
    "_$_17TrackedController",
};

static void call(int32_t fn, int slot, int32_t a, int32_t b, int32_t c,
                 int32_t d)
{
    RealController    *rc = ctl(slot);
    TrackedController *tc = &rc->Base;

    switch (fn) {
    case F_THINK:
    case F_TTHINK:
        printf("%s c%d %08x\n", fname[fn], slot, (unsigned)a);
        if (fn == F_THINK)
            realcontroller_think(rc, bitsf(a));
        else
            trackedcontroller_think(tc, bitsf(a));
        break;
    case F_SET_ROUTE:
        printf("%s c%d %s %s\n", fname[fn], slot, label(ref(a)),
               label(ref(b)));
        trackedcontroller_set_current_route(tc, ref(a), ref(b));
        break;
    case F_RDP:
    case F_COMBO:
        printf("%s c%d %08x %08x %s %s\n", fname[fn], slot, (unsigned)a,
               (unsigned)b, label(ref(c)), label(ref(d)));
        if (fn == F_RDP)
            realcontroller_route_delta_predict(rc, &tgt, bitsf(a), bitsf(b),
                                               ref(c), ref(d));
        else
            realcontroller_combo_predict(rc, &tgt, bitsf(a), bitsf(b),
                                         ref(c), ref(d));
        print_target(&tgt, "tgt");
        break;
    case F_LATERAL: {
        uint32_t fill = OUT_FILL;
        int32_t  r;

        printf("%s c%d %08x %s %s\n", fname[fn], slot, (unsigned)a,
               label(ref(b)), label(ref(c)));
        memcpy(&out_pos, &fill, 4);
        memcpy(&out_vel, &fill, 4);
        r = realcontroller_calculate_lateral(rc, &out_pos, &out_vel,
                                             bitsf(a), ref(b), ref(c));
        printf("  ret %d pos %08x vel %08x\n", (int)r,
               (unsigned)fbits(out_pos), (unsigned)fbits(out_vel));
        break;
    }
    case F_DESTROY:
    case F_TDESTROY:
        printf("%s c%d %d\n", fname[fn], slot, (int)a);
        if (fn == F_DESTROY)
            realcontroller_destroy(rc, a);
        else
            trackedcontroller_destroy(tc, a);
        break;
    default:
        printf("%s c%d\n", fname[fn], slot);
        switch (fn) {
        case F_FIND:
            trackedcontroller_find_where_i_am(tc);
            break;
        case F_OOB:
            printf("  ret %08x\n", (unsigned)fbits(
                       trackedcontroller_get_amount_out_of_bounds(tc)));
            break;
        case F_GET_ROUTE:
            printf("  ret %s\n",
                   label(trackedcontroller_get_current_route(tc)));
            break;
        case F_GET_POINT:
            printf("  ret %s\n",
                   label(trackedcontroller_get_current_route_point(tc)));
            break;
        case F_GET_ACC:
            printf("  ret %08x\n",
                   (unsigned)fbits(trackedcontroller_get_acceleration(tc)));
            break;
        case F_JUST_RESET:
            trackedcontroller_just_reset(tc);
            break;
        case F_LINE:
            printf("  ret %d\n",
                   (int)realcontroller_player_drive_line_number(rc));
            break;
        default:
            fprintf(stderr, "call %d\n", (int)fn);
            exit(2);
        }
    }
}

static void vcall(int slot, int32_t vslot, int32_t a, int32_t b)
{
    CarController *c = &ctl(slot)->Base.Base;
    const VtEntry *e = vt_slot(c->_vtable, vslot);
    void          *self = vt_this(c, e);

    printf("vt c%d %d %s\n", slot, (int)vslot, portname(e->fn));
    switch (vslot) {
    case 8:
        ((VInt)e->fn)(self, a);
        break;
    case 32:
    case 96:
        ((VFloat)e->fn)(self, bitsf(a));
        break;
    case 40:
        ((VRoute)e->fn)(self, ref(a), ref(b));
        break;
    case 48:
        printf("  ret %s\n", label(((RRoute)e->fn)(self)));
        break;
    case 56:
        printf("  ret %s\n", label(((RPoint)e->fn)(self)));
        break;
    case 64:
        printf("  ret %08x\n", (unsigned)fbits(((RFloat)e->fn)(self)));
        break;
    case 88:
        ((VCar)e->fn)(self, &car);
        break;
    default:
        ((VVoid)e->fn)(self);
    }
}

// ------------------------------------------------------------------ main

int main(int argc, char **argv)
{
    FILE   *f;
    long    len;
    int32_t ntags, total, i;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: realcontroller_test ops.bin\n");
        return 2;
    }
    f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = fread(words_in, 4, (size_t)len / 4, f);
    fclose(f);

    tags = read_strings(&ntags);
    total = next();
    end = rd + (size_t)total;
    for (i = 0; i < MAX_ROUTES; i++)
        route_off[i] = -1;
    SignpostArray = signs;
    NumSignposts = 0;

    vt_reset();
    carcontroller_install_vtables();
    cardriver_install_vtables();
    realdriver_install_vtable();
    realcontroller_install_vtables();
    bSetMemoryHooks(malloc_hook, free_hook);
    gRadialBlurOffFn = s_blur_off;

    car.pCarTypeInfo = &cti;
    car.pPlayer = &player;
    car.pDynamicCollisionBody = &body;

    while (rd < end) {
        int32_t code = next(), nargs = next();
        size_t  after = rd + (size_t)nargs;

        switch (code) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_CLEAR:
            memset(arena, 0, sizeof arena);
            for (i = 0; i < MAX_ROUTES; i++)
                route_off[i] = -1;
            break;
        case OP_WORDS: {
            int32_t off = next(), k;

            for (k = 0; k < nargs - 1; k++) {
                int32_t w = next();
                memcpy(arena + off + 4 * k, &w, 4);
            }
            break;
        }
        case OP_ROUTE: {
            int32_t slot = next();
            route_off[slot] = next();
            break;
        }
        case OP_SIGNS: {
            int32_t first = next(), k;

            for (k = 0; k < (nargs - 1) / 2; k++) {
                int32_t w[2];
                w[0] = next();
                w[1] = next();
                memcpy(&signs[first + k], w, 8);
            }
            break;
        }
        case OP_RESET:
            trmgr_init(&TheTrackRouteManager);
            break;
        case OP_ADD:
            trmgr_add_route_to_right_list(&TheTrackRouteManager,
                                          ref(next()));
            break;
        case OP_FILL: {
            int32_t slot = next(), byte = next();

            memset(ctlmem[slot], byte & 0xff, sizeof ctlmem[slot]);
            break;
        }
        case OP_INIT: {
            int32_t slot = next();

            printf("init c%d\n", slot);
            printf("  -> %s\n",
                   label(realcontroller_construct(ctlmem[slot], &car)));
            break;
        }
        case OP_TINIT: {
            int32_t slot = next();

            printf("tinit c%d\n", slot);
            printf("  -> %s\n", label(trackedcontroller_init(
                                    (TrackedController *)(void *)ctlmem[slot],
                                    &car)));
            break;
        }
        case OP_DUMP:
            dump(next());
            break;
        case OP_CARF: {
            int32_t field = next(), v = next();

            set_carf(field, v);
            break;
        }
        case OP_GLOB: {
            int32_t id = next(), v = next();

            set_glob(id, v);
            break;
        }
        case OP_CTLF: {
            int32_t slot = next(), field = next(), v = next();

            set_ctlf(ctl(slot), field, v);
            break;
        }
        case OP_CALL: {
            int32_t fn = next(), slot = next(), a = next(), b = next(),
                    c = next(), d = next();

            call(fn, slot, a, b, c, d);
            break;
        }
        case OP_VT: {
            int32_t slot = next(), vslot = next(), a = next(), b = next();

            vcall(slot, vslot, a, b);
            break;
        }
        case OP_TGT: {
            int32_t k;

            if (nargs * 4 != (int32_t)sizeof tgt) {
                fprintf(stderr, "target of %d words\n", (int)nargs);
                return 2;
            }
            for (k = 0; k < nargs; k++) {
                int32_t w = next();

                memcpy((uint8_t *)&tgt + 4 * k, &w, 4);
            }
            break;
        }
        case OP_STATIC:
            print_static();
            break;
        default:
            fprintf(stderr, "op %d\n", (int)code);
            return 2;
        }
        if (rd != after) {
            fprintf(stderr, "op %d read %d of %d args\n", (int)code,
                    (int)(rd - (after - (size_t)nargs)), (int)nargs);
            return 2;
        }
    }
    return 0;
}
