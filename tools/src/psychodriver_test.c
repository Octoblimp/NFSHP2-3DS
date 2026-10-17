// Harness for tools/psychodriver_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     psychodriver_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "drivetarget.h"
#include "psychodriver.h"
#include "realdriver.h"
#include "table.h"
#include "vtable.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// The DoSnapshots (TASKS 72c) call these; nothing here takes a
// snapshot.
static void snapshot_unreached(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void drivetarget_do_snapshot(DriveTarget *t, struct ReplaySnapshot *s)
{
    (void)t; (void)s;
    snapshot_unreached("drivetarget_do_snapshot");
}

enum {
    OP_TAG, OP_JUNK, OP_FIELD, OP_CTI, OP_SET, OP_SRC, OP_NEW, OP_DEL,
    OP_DRIVE, OP_SDS, OP_TARGET, OP_SSTP, OP_DRVNUM, OP_HONK, OP_ZS, OP_CLS,
    OP_GDS, OP_GTTS, OP_GSTP, OP_LOWGEAR, OP_BASE, OP_ZT, OP_CT, OP_GETERR,
    OP_MOVIDX, OP_CSTP, OP_CTB, OP_JEEVES, OP_MAXTHR, OP_EBT, OP_WRAP, OP_SS,
    OP_TABLE, OP_POKE, OP_PID, OP_NULLPID, OP_DUMP, OP_STATIC
};

enum {
    K_YAW, K_IPX, K_IPY, K_IPZ, K_IPW, K_NCOLL, K_TWOCAR, K_SOUND,
    K_HONKING, K_COUNT
};

#define SLACK    16
#define MAX_HEAP 16384
#define NCOLLS   64

// ------------------------------------------------------------- the world

static union {
    PsychoDriver  d;
    unsigned char b[sizeof(PsychoDriver)];
} pdu;
static PsychoDriver *const pd = &pdu.d;

static Car              car;
static CarTypeInfo      cti;
static CarCollisionBody ccb;
static DriveTarget      src;
static char             sound_mem[16];
static char             colls[NCOLLS][16];

// realdriver.c's seams, which the harness does not link.
void (*gBaseCarSoundStartHonkHornFn)(struct BaseCarSound *);
void (*gBaseCarSoundStopHonkHornFn)(struct BaseCarSound *);

static uint32_t vals[K_COUNT];

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;
} heap[MAX_HEAP];
static int nheap;

// The console's size of what the port asked for: a PidError is 40 there.
static int console_size(int size, const char *name)
{
    if (strstr(name, "Pid") != NULL && size == (int)sizeof(PidError))
        return 40;
    return size;
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    size_t span = (size > 0 ? (size_t)size : 0) + SLACK;
    void  *p = malloc(span);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    memset(p, 0xcd, span);
    heap[nheap].p = p;
    heap[nheap].span = span;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap,
           console_size(size, name), name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a)
{
    const char *b = (const char *)a;
    int i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    if (a == (const void *)pd) {
        snprintf(buf, n, "pd");
        return;
    }
    if (a == (const void *)&car) {
        snprintf(buf, n, "car");
        return;
    }
    if (a == (const void *)&car.State) {
        snprintf(buf, n, "cs");
        return;
    }
    if (a == (const void *)&ccb.Dynamic.Body) {
        snprintf(buf, n, "body");
        return;
    }
    if (a == (const void *)sound_mem) {
        snprintf(buf, n, "snd");
        return;
    }
    if (a == (const void *)&src) {
        snprintf(buf, n, "src");
        return;
    }
    if (a == (const void *)&cti) {
        snprintf(buf, n, "cti");
        return;
    }
    for (i = 0; i < NCOLLS; i++)
        if (a == (const void *)colls[i]) {
            snprintf(buf, n, "c%d", i);
            return;
        }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (b >= p && b < p + heap[i].span) {
            if (b == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(b - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static const char *lab(const void *a)
{
    static char bufs[16][48];
    static int k;
    char *b = bufs[k++ & 15];

    label(b, 48, a);
    return b;
}

// Logged, never freed, so no address is handed out twice.
static void free_hook(void *p)
{
    printf("  free %s\n", lab(p));
}

// ------------------------------------------------------------ stand-ins

DriveTarget *drivetarget_init(DriveTarget *t)
{
    printf("  dt init %s\n", lab(t));
    memset(t, 0, sizeof *t);
    return t;
}

void drivetarget_clear(DriveTarget *t, Car *c, float speed)
{
    printf("  dt clear %s %s %08x\n", lab(t), lab(c), bitsf(speed));
}

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *s)
{
    printf("  dt assign %s %s\n", lab(dst), lab(s));
    memcpy(dst, s, sizeof *dst);
    return dst;
}

void drivetarget_resample(DriveTarget *t, Car *c)
{
    printf("  resample %s %s\n", lab(t), lab(c));
}

int drivetarget_interpolate_point(DriveTarget *t, Car *c, float dist,
                                  bVector3 *out)
{
    printf("  interp %s %s %08x\n", lab(t), lab(c), bitsf(dist));
    out->x = fbits(vals[K_IPX]);
    out->y = fbits(vals[K_IPY]);
    out->z = fbits(vals[K_IPZ]);
    out->pad = fbits(vals[K_IPW]);
    return 1;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    printf("  getcoll %s %d\n", lab(b), i);
    return (struct Collision *)(void *)colls[i];
}

int32_t collision_is_two_car_collision(Collision *c)
{
    int i = (int)(((char (*)[16])(void *)c) - colls);
    int32_t r = (int32_t)((vals[K_TWOCAR] >> i) & 1);

    printf("  twocar %s -> %d\n", lab(c), r);
    return r;
}

float carstate_get_yaw_always(CarState *s)
{
    printf("  yaw %s -> %08x\n", lab(s), vals[K_YAW]);
    return fbits(vals[K_YAW]);
}

static void snd_start(struct BaseCarSound *s)
{
    printf("  honk start %s\n", lab(s));
}

static void snd_stop(struct BaseCarSound *s)
{
    printf("  honk stop %s\n", lab(s));
}

static int32_t snd_is(struct BaseCarSound *s)
{
    printf("  honk is %s -> %d\n", lab(s), (int32_t)vals[K_HONKING]);
    return (int32_t)vals[K_HONKING];
}

// ------------------------------------------------------------- the script

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

// The script's Car fields, in the checker's order.
static void *car_field(int id, char *kind)
{
    CarState *s = &car.State;

    *kind = 'f';
    if (id < 4)
        return &(&s->Position.x)[id];
    if (id < 8)
        return &(&s->Velocity.x)[id - 4];
    if (id < 12) {
        *kind = 'b';
        return &s->WheelTouchingGround[id - 8];
    }
    switch (id) {
    case 12:
        *kind = 'h';
        return &s->Angle;
    case 13:
        return &s->ForwardSpeed;
    case 14:
        return &s->VelocityMagnitude;
    case 15:
        *kind = 'w';
        return &s->DriverMode;
    case 16:
        *kind = 'h';
        return &car.DriverNumber;
    case 17:
        *kind = 'w';
        return &car.TheControlMode;
    case 18:
        *kind = 'w';
        return &car.TheMovementMode;
    }
    fprintf(stderr, "no field %d\n", id);
    exit(2);
}

static void *poke_field(int off, char *kind)
{
    *kind = 'f';
    switch (off) {
    case 528: *kind = 'h'; return &pd->Base.Steering;
    case 532: return &pd->Base.Throttle;
    case 536: return &pd->Base.Brake;
    case 540: return &pd->Base.EBrake;
    case 544: *kind = 'w'; return &pd->Base.DesiredGear;
    case 564: return &pd->SteerToPoint.x;
    case 568: return &pd->SteerToPoint.y;
    case 572: return &pd->MaxThrottle;
    case 576: return &pd->DesiredSpeed;
    case 580: return &pd->TimeToGetToDesiredSpeed;
    case 584: return &pd->DesiredSpeedTolerance;
    case 588: *kind = 'w'; return &pd->AllowedToUseThrottleAndBrake;
    case 592: return &pd->EBrakeTimer;
    case 600: *kind = 'w'; return &pd->DirectionLatch;
    }
    fprintf(stderr, "no poke %d\n", off);
    exit(2);
}

static PidError **pid_of(int which)
{
    switch (which) {
    case 0: return &pd->pBodyError;
    case 1: return &pd->pHeadingError;
    case 2: return &pd->pVelocityError;
    }
    fprintf(stderr, "no pid %d\n", which);
    exit(2);
}

static float *pid_field(PidError *p, int off)
{
    switch (off) {
    case 4:  return &p->aIntegral.fTotal;
    case 8:  return &p->aIntegral.fAverage;
    case 20: return &p->aDerivative.fTotal;
    case 24: return &p->aDerivative.fAverage;
    case 32: return &p->fCurrentError;
    case 36: return &p->fPreviousError;
    }
    fprintf(stderr, "no pid field %d\n", off);
    exit(2);
}

// ------------------------------------------------------------- the dump

static void words(char *buf, size_t n, const void *p, int count)
{
    const uint32_t *w = (const uint32_t *)p;
    size_t at = 0;
    int k;

    buf[0] = 0;
    for (k = 0; k < count; k++)
        at += (size_t)snprintf(buf + at, n - at, k ? " %08x" : "%08x", w[k]);
}

static const char *vtname(uint32_t v)
{
    static char b[16];

    if (v == PSYCHODRIVER_VTABLE)
        return "psycho";
    if (v == CARDRIVER_VTABLE)
        return "cardriver";
    snprintf(b, sizeof b, "%08x", v);
    return b;
}

static void dump_average(const char *name, const Average *a)
{
    char b[400];

    words(b, sizeof b, a->pData, a->nSlots);
    printf("  %s %d %d %d %08x %08x %s\n", name, a->nSlots, a->nCurrentSlot,
           a->nSamples, bitsf(a->fTotal), bitsf(a->fAverage), b);
}

static void dump(void)
{
    static const char *const names[3] = { "body", "head", "vel" };
    uint32_t sport;
    int i;

    memcpy(&sport, &pd->Base.SportGear, 4);
    printf("pd vt %s steer %d thr %08x brk %08x eb %08x gear %d sport %08x "
           "nitro %d dtn %d\n",
           vtname(pd->Base._vtable), pd->Base.Steering,
           bitsf(pd->Base.Throttle), bitsf(pd->Base.Brake),
           bitsf(pd->Base.EBrake), pd->Base.DesiredGear, sport,
           pd->Base.NitroFlag, pd->Base.MyDriveTarget.NumPoints);
    printf("pd car %s stp %08x %08x mt %08x ds %08x t %08x tol %08x ok %d "
           "ebt %08x latch %d\n",
           lab(pd->pCar), bitsf(pd->SteerToPoint.x),
           bitsf(pd->SteerToPoint.y), bitsf(pd->MaxThrottle),
           bitsf(pd->DesiredSpeed), bitsf(pd->TimeToGetToDesiredSpeed),
           bitsf(pd->DesiredSpeedTolerance),
           pd->AllowedToUseThrottleAndBrake, bitsf(pd->EBrakeTimer),
           pd->DirectionLatch);
    for (i = 0; i < 3; i++) {
        const PidError *p = *pid_of(i);
        printf("pid %s %s\n", names[i], lab(p));
        if (p == NULL)
            continue;
        printf("  err %08x %08x\n", bitsf(p->fCurrentError),
               bitsf(p->fPreviousError));
        dump_average("int", &p->aIntegral);
        dump_average("der", &p->aDerivative);
    }
    printf("g warned %d\n", PsychoDriverWarnedAlready);
}

static void dump_static(void)
{
    static const Table *const tables[7] = {
        &PidProportionalTable, &PidDerivativeTable, &PidIntegralTable,
        &PidSteerToTable, &PsychoSteeringRangeTable,
        &PsychoSteeringSpeedTable, &PsychoSteeringCurveTable,
    };
    static const float *const weights[4] = {
        PsychoSteeringProportionalWeight, PsychoSteeringIntegralWeight,
        PsychoSteeringDerivativeWeight, PsychoDriverSteerToPointSecondsAhead,
    };
    char b[400];
    int i;

    printf("g diff %08x warned %d\n", bitsf(fPsychoCounterDiff),
           PsychoDriverWarnedAlready);
    for (i = 0; i < 7; i++) {
        const Table *t = tables[i];
        words(b, sizeof b, t->pTable, t->NumEntries);
        printf("table %d n %d min %08x max %08x mul %08x data %s\n", i,
               t->NumEntries, bitsf(t->MinArg), bitsf(t->MaxArg),
               bitsf(t->IndexMultiplier), b);
    }
    for (i = 0; i < 4; i++) {
        words(b, sizeof b, weights[i], 5);
        printf("weights %d %s\n", i, b);
    }
}

static const Table *table_of(int i)
{
    switch (i) {
    case 0: return &PidProportionalTable;
    case 1: return &PidDerivativeTable;
    case 2: return &PidIntegralTable;
    case 3: return &PidSteerToTable;
    case 4: return &PsychoSteeringRangeTable;
    case 5: return &PsychoSteeringSpeedTable;
    case 6: return &PsychoSteeringCurveTable;
    }
    fprintf(stderr, "no table %d\n", i);
    exit(2);
}

// ------------------------------------------------------------- the table

typedef void      (*VoidFn)(void *self);
typedef void      (*IntFn)(void *self, int32_t i);
typedef void      (*FloatFn)(void *self, float f);
typedef int32_t   (*GetIntFn)(void *self);
typedef float     (*GetFloatFn)(void *self);
typedef void      (*SdsFn)(void *self, float s, float t, float tol,
                           int32_t ok);
typedef void      (*TargetFn)(void *self, DriveTarget *t);
typedef float     (*MaxSpeedFn)(void *self, DriveTarget *t);
typedef void      (*SetV2Fn)(void *self, bVector2 *p);
typedef bVector2 *(*GetV2Fn)(void *self);

static const VtEntry *slot(int s)
{
    return vt_slot(pd->Base._vtable, s);
}

#define SELF(e) vt_this(pd, e)

// ------------------------------------------------------------- the main

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: psychodriver_test ops.bin\n");
        return 2;
    }
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fp) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fp);

    tags = read_strings(&ntags);
    nflat = next();
    end = rd + (size_t)nflat;

    bSetMemoryHooks(malloc_hook, free_hook);
    vt_reset();
    cardriver_install_vtables();
    psychodriver_install_vtables();
    psychodriver_static_init();
    gBaseCarSoundStartHonkHornFn = snd_start;
    gBaseCarSoundStopHonkHornFn = snd_stop;
    gBaseCarSoundIsHonkingFn = snd_is;

    car.pCarTypeInfo = &cti;
    car.pDynamicCollisionBody = &ccb;

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_JUNK: {
            int32_t seed = next();
            size_t k;
            for (k = 0; k < sizeof pdu.b; k++)
                pdu.b[k] = (unsigned char)(0xa1 + seed + 7 * (int)k);
            break;
        }
        case OP_FIELD: {
            int32_t id = next(), v = next();
            char kind;
            void *p = car_field(id, &kind);
            if (kind == 'h')
                *(uint16_t *)p = (uint16_t)v;
            else if (kind == 'b')
                *(int8_t *)p = (int8_t)v;
            else
                memcpy(p, &v, 4);
            break;
        }
        case OP_CTI:
            cti.Control.Steering = fbits((uint32_t)next());
            break;
        case OP_SET: {
            int32_t k = next(), v = next();
            vals[k] = (uint32_t)v;
            if (k == K_NCOLL)
                ccb.Dynamic.Body.NumCollisions = (int8_t)v;
            else if (k == K_SOUND)
                car.pBaseCarSound = v ? (BaseCarSound *)(void *)sound_mem
                                      : NULL;
            break;
        }
        case OP_SRC: {
            int32_t n = next();
            unsigned char *b = (unsigned char *)&src;
            size_t k;
            for (k = 0; k < sizeof src; k++)
                b[k] = (unsigned char)(0x30 + 5 * (int)k);
            src.NumPoints = (int8_t)n;
            break;
        }
        case OP_NEW: {
            PsychoDriver *r;
            printf("new\n");
            r = psychodriver_init(pd, &car);
            printf("new -> %s\n", lab(r));
            break;
        }
        case OP_DEL: {
            int32_t flags = next();
            const VtEntry *e = slot(CARDRIVER_VT_DTOR);
            printf("del %d\n", flags);
            ((IntFn)e->fn)(SELF(e), flags);
            break;
        }
        case OP_DRIVE: {
            float dt = fbits((uint32_t)next());
            const VtEntry *e = slot(CARDRIVER_VT_DRIVE);
            printf("drive %08x\n", bitsf(dt));
            ((FloatFn)e->fn)(SELF(e), dt);
            break;
        }
        case OP_SDS: {
            float s = fbits((uint32_t)next());
            float t = fbits((uint32_t)next());
            float tol = fbits((uint32_t)next());
            int32_t ok = next();
            const VtEntry *e = slot(CARDRIVER_VT_SET_DESIRED_SPEED);
            ((SdsFn)e->fn)(SELF(e), s, t, tol, ok);
            break;
        }
        case OP_TARGET: {
            int32_t which = next();
            const VtEntry *e = slot(CARDRIVER_VT_SET_TARGET);
            printf("target %s\n", which ? "src" : "null");
            ((TargetFn)e->fn)(SELF(e), which ? &src : NULL);
            break;
        }
        case OP_SSTP: {
            bVector2 p;
            const VtEntry *e = slot(CARDRIVER_VT_SET_STEER_TO_POINT);
            p.x = fbits((uint32_t)next());
            p.y = fbits((uint32_t)next());
            ((SetV2Fn)e->fn)(SELF(e), &p);
            break;
        }
        case OP_DRVNUM: {
            const VtEntry *e = slot(CARDRIVER_VT_GET_DRIVER_NUMBER);
            printf("drvnum -> %d\n", ((GetIntFn)e->fn)(SELF(e)));
            break;
        }
        case OP_HONK: {
            int32_t k = next();
            const VtEntry *e = slot(k == 0 ? CARDRIVER_VT_START_HONK_HORN
                                    : k == 1 ? CARDRIVER_VT_STOP_HONK_HORN
                                    : CARDRIVER_VT_IS_HONKING);
            if (k == 2)
                printf("honking -> %d\n", ((GetIntFn)e->fn)(SELF(e)));
            else
                ((VoidFn)e->fn)(SELF(e));
            break;
        }
        case OP_ZS: {
            const VtEntry *e = slot(CARDRIVER_VT_ZERO_STEERING_MEMORY);
            ((VoidFn)e->fn)(SELF(e));
            break;
        }
        case OP_CLS: {
            const VtEntry *e = slot(CARDRIVER_VT_CLEAR_STEERING_MEMORY);
            ((VoidFn)e->fn)(SELF(e));
            break;
        }
        case OP_GDS: {
            const VtEntry *e = slot(CARDRIVER_VT_GET_DESIRED_SPEED);
            printf("gds -> %08x\n", bitsf(((GetFloatFn)e->fn)(SELF(e))));
            break;
        }
        case OP_GTTS: {
            const VtEntry *e = slot(144);
            printf("gtts -> %08x\n", bitsf(((GetFloatFn)e->fn)(SELF(e))));
            break;
        }
        case OP_GSTP: {
            const VtEntry *e = slot(CARDRIVER_VT_GET_STEER_TO_POINT);
            bVector2 *r = ((GetV2Fn)e->fn)(SELF(e));
            char b[40];
            words(b, sizeof b, r, 2);
            printf("gstp -> %s %s\n",
                   r == &pd->SteerToPoint ? "pd+564" : lab(r), b);
            break;
        }
        case OP_LOWGEAR: {
            const VtEntry *e = slot(CARDRIVER_VT_SET_LOW_GEAR);
            ((VoidFn)e->fn)(SELF(e));
            break;
        }
        case OP_BASE: {
            int32_t s = next();
            const VtEntry *e = slot(s);
            if (s == 112) {
                float r = ((MaxSpeedFn)e->fn)(SELF(e), &src);
                printf("base %d -> %08x\n", s, bitsf(r));
            } else {
                if (s == 152)
                    ((IntFn)e->fn)(SELF(e), 3);
                else
                    ((VoidFn)e->fn)(SELF(e));
                printf("base %d\n", s);
            }
            break;
        }
        case OP_ZT:
            psychodriver_zero_throttle_memory(pd);
            break;
        case OP_CT:
            psychodriver_clear_throttle_memory(pd);
            break;
        case OP_GETERR: {
            float hv[2];
            char b[40];
            int32_t r;
            memset(hv, 0x5a, sizeof hv);
            r = psychodriver_get_error(pd, &hv[0], &hv[1]);
            words(b, sizeof b, hv, 2);
            printf("geterr -> %d %s\n", r, b);
            break;
        }
        case OP_MOVIDX:
            printf("movidx -> %d\n", psychodriver_get_movement_index(pd));
            break;
        case OP_CSTP:
            psychodriver_calc_steer_to_point(pd);
            break;
        case OP_CTB: {
            float tb[2];
            char b[40];
            memset(tb, 0x5a, sizeof tb);
            psychodriver_calc_throttle_and_brake(pd, &tb[0], &tb[1]);
            words(b, sizeof b, tb, 2);
            printf("ctb -> %s\n", b);
            break;
        }
        case OP_JEEVES:
            psychodriver_step_on_it_jeeves(pd);
            break;
        case OP_MAXTHR:
            psychodriver_set_max_throttle(pd, fbits((uint32_t)next()));
            break;
        case OP_EBT:
            psychodriver_set_ebrake_timer(pd, fbits((uint32_t)next()));
            break;
        case OP_WRAP: {
            uint16_t bam = (uint16_t)next();
            printf("wrap %d -> %08x\n", bam, bitsf(radian_wrap(bam)));
            break;
        }
        case OP_SS: {
            int32_t kind = next();
            float d = fbits((uint32_t)next());
            bVector3 out;
            char b[60];
            memset(&out, 0x5a, sizeof out);
            if (kind)
                ai_steer_straight_velocity3d(&out, &car, d);
            else
                ai_steer_straight_vector3d(&out, &car, d);
            words(b, sizeof b, &out, 3);
            printf("ss %d %08x -> %s\n", kind, bitsf(d), b);
            break;
        }
        case OP_TABLE: {
            int32_t i = next();
            float x = fbits((uint32_t)next());
            printf("table %d %08x -> %08x\n", i, bitsf(x),
                   bitsf(table_get_value(table_of(i), x)));
            break;
        }
        case OP_POKE: {
            int32_t off = next(), v = next();
            char kind;
            void *p = poke_field(off, &kind);
            if (kind == 'h')
                *(uint16_t *)p = (uint16_t)v;
            else
                memcpy(p, &v, 4);
            break;
        }
        case OP_PID: {
            int32_t which = next(), off = next(), v = next();
            memcpy(pid_field(*pid_of(which), off), &v, 4);
            break;
        }
        case OP_NULLPID:
            *pid_of(next()) = NULL;
            break;
        case OP_DUMP:
            dump();
            break;
        case OP_STATIC:
            dump_static();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
