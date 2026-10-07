// Harness for tools/beltmover_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     beltmover_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "average.h"
#include "beltmover.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "drivetarget.h"
#include "nearbycar.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "vtable.h"
#include "wheel.h"
#include "world.h"

enum {
    OP_TAG, OP_JUNK, OP_CS, OP_CTI, OP_DTN, OP_DTP, OP_DTL, OP_STEER, OP_SET,
    OP_NEW, OP_DEL, OP_SETBELT, OP_FIND, OP_MOVE, OP_GRAV, OP_MAXACC,
    OP_SLIDE, OP_AIR, OP_GP, OP_GD, OP_GDD, OP_DOT, OP_POKE, OP_CUBIC,
    OP_AVGREC, OP_DUMP, OP_TIMER, OP_NULLP, OP_DDVAL, OP_CPW
};

enum { K_DSPEED, K_DTTS, K_MAXACC, K_VFX, K_DIST, K_FLATDZ, K_COUNT };
enum { CU_U, CU_AX, CU_AY, CU_SX, CU_SY };

#define SLACK     16
#define MAX_HEAP  4096
#define MAX_WHEEL 1024

// The fake tables, at addresses no class of the port's uses.
#define DVT 0x01e06000u
#define WVT 0x01e06200u

// ------------------------------------------------------------- the world

static union {
    BeltMover m;
    unsigned char b[sizeof(BeltMover)];
} bmu;
static BeltMover *const bm = &bmu.m;

static Car             car;
static CarTypeInfo     cti;
static CarDriver       drv;
static AICarController aicc;
static char            world_mem[16];

World *pCurrentWorld;

// carmodes.c's and nearbycar.c's seams, which beltmover_install_seams sets.
CarMoverCtorFn     gBeltMoverCtorFn;
BeltMoverSetBeltFn gBeltMoverSetBeltFn;
BeltMoverGravityFn gBeltMoverGravityFn;

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

static Wheel *wheels[MAX_WHEEL];
static int    nwheels;

// The console's size of what the port asked for, where the host's differs:
// the Average and the QuickSpline by their own sizes, and quickspline.cpp's
// buffer less the port's extra point (quickspline.c).
static int console_size(int size, const char *name, int line)
{
    if (strstr(name, "beltmover.cpp") != NULL) {
        if (line == 124 && size == (int)sizeof(Average))
            return 16;
        if (line == 126 && size == (int)sizeof(QuickSpline))
            return 40;
    }
    if (strstr(name, "quickspline.cpp") != NULL && line == 77)
        return size - (int)sizeof(bVector4);
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
           console_size(size, name, flags), name, flags, pool);
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
    if (a == (const void *)bm) {
        snprintf(buf, n, "bm");
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
    if (a == (const void *)&drv) {
        snprintf(buf, n, "drv");
        return;
    }
    if (a == (const void *)&aicc) {
        snprintf(buf, n, "aicc");
        return;
    }
    if (a == (const void *)world_mem) {
        snprintf(buf, n, "world");
        return;
    }
    if (b >= (const char *)&cti && b < (const char *)(&cti + 1)) {
        if (b == (const char *)&cti)
            snprintf(buf, n, "cti");
        else
            snprintf(buf, n, "cti+%d", (int)(b - (const char *)&cti));
        return;
    }
    for (i = 0; i < nwheels; i++)
        if (a == (const void *)wheels[i]) {
            snprintf(buf, n, "w%d", i);
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

Wheel *wheel_new(void)
{
    Wheel *w = malloc(sizeof(Wheel));

    if (nwheels >= MAX_WHEEL) {
        fprintf(stderr, "wheel log full\n");
        exit(3);
    }
    memset(w, 0xcd, sizeof(Wheel));
    wheels[nwheels++] = w;
    printf("  omalloc pool -> w%d\n", nwheels - 1);
    return w;
}

Wheel *wheel_init(Wheel *w, const WheelInfo *wi, const TireInfo *ti,
                  const ControlInfo *ci, void *cs)
{
    printf("  wheel %s wi %s ti %s ci %s cs %s\n", lab(w), lab(wi), lab(ti),
           lab(ci), lab(cs));
    w->_vtable = WVT;
    w->WI = wi;
    return w;
}

static void fake_wheel_dtor(void *self, int32_t flags)
{
    printf("  wdtor %s %d\n", lab(self), flags);
}

void wheel_set_state_from_car_state(Wheel *w, void *cs, void *ti,
                                    float angle, float angularVelocity,
                                    uint16_t steeringAngle,
                                    float suspensionHeight)
{
    printf("  setstate %s %s %s %08x %08x %d %08x\n", lab(w), lab(cs),
           lab(ti), bitsf(angle), bitsf(angularVelocity), steeringAngle,
           bitsf(suspensionHeight));
}

void wheel_maybe_make_skids(Wheel *w, float dt)
{
    printf("  skids %s %08x\n", lab(w), bitsf(dt));
}

void drivetarget_resample(DriveTarget *t, Car *c)
{
    printf("  resample %s %s\n", lab(t), lab(c));
}

float ai_calculate_max_acceleration(Car *c, float speed)
{
    printf("  maxacc %s %08x\n", lab(c), bitsf(speed));
    return fbits(vals[K_MAXACC]);
}

void car_put_flat_on_track(Car *c)
{
    printf("  flat %s\n", lab(c));
    car.State.Position.z = car.State.Position.z + fbits(vals[K_FLATDZ]);
}

void carstate_calculate_geometry_position(CarState *s)
{
    printf("  geom %s\n", lab(s));
}

int32_t car_should_visual_effects_be_generated(Car *c)
{
    printf("  vfx %s -> %d\n", lab(c), (int32_t)vals[K_VFX]);
    return (int32_t)vals[K_VFX];
}

float world_get_distance_to_closest_player(const World *w, const bVector3 *p)
{
    printf("  dist %s %s %08x %08x %08x -> %08x\n", lab(w),
           p == &car.State.Position ? "pos" : lab(p), bitsf(p->x),
           bitsf(p->y), bitsf(p->z), vals[K_DIST]);
    return fbits(vals[K_DIST]);
}

void car_compute_fake_rpm(Car *c)
{
    printf("  rpm %s\n", lab(c));
}

void carmover_destroy(CarMover *m, int32_t flags)
{
    printf("  carmover dtor %s %d\n", lab(m), flags);
}

static float fake_gds(void *self)
{
    printf("  gds %s\n", lab(self));
    return fbits(vals[K_DSPEED]);
}

static float fake_gtts(void *self)
{
    printf("  gtts %s\n", lab(self));
    return fbits(vals[K_DTTS]);
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

// The script's CarState fields, in the checker's order.
static void *cs_field(int id, char *kind)
{
    CarState *s = &car.State;

    *kind = 'f';
    if (id < 4)
        return &(&s->Position.x)[id];
    if (id < 8)
        return &(&s->Velocity.x)[id - 4];
    if (id < 12)
        return &(&s->BodyMatrix.v0.x)[id - 8];
    if (id < 16)
        return &(&s->BodyMatrix.v1.x)[id - 12];
    if (id < 20)
        return &(&s->AngularVelocity.x)[id - 16];
    if (id < 24)
        return &s->WheelAngularVelocity[id - 20];
    if (id < 28)
        return &s->WheelAngle[id - 24];
    if (id < 36)
        return &(&s->WheelSlip[0].x)[id - 28];
    if (id < 40)
        return &s->WheelTractionUsage[id - 36];
    if (id == 40) {
        *kind = 'h';
        return &s->Angle;
    }
    if (id == 41)
        return &s->ForwardSpeed;
    if (id == 42)
        return &s->VelocityMagnitude;
    if (id == 43) {
        *kind = 'w';
        return &s->MatrixValid;
    }
    fprintf(stderr, "no field %d\n", id);
    exit(2);
}

static BSpline *cubic_of(int which)
{
    switch (which) {
    case CU_U:  return bm->pCubicU;
    case CU_AX: return &bm->pCubicAng->x;
    case CU_AY: return &bm->pCubicAng->y;
    case CU_SX: return &bm->pCubicSlide->x;
    case CU_SY: return &bm->pCubicSlide->y;
    }
    fprintf(stderr, "no cubic %d\n", which);
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

static void dump_cubic(const char *name, const BSpline *c)
{
    char b[160];

    words(b, sizeof b, c, 11);
    printf("%s %s st %d fl %d\n", name, b, c->state, c->flags);
}

static void dump_graph(const char *name, const Graph *g)
{
    char b[160];

    words(b, sizeof b, g->pPoints, 8);
    printf("graph %s %d %s\n", name, g->NumPoints, b);
}

static void dump(void)
{
    const QuickSpline *s = bm->pSpline;
    const Average *a = bm->pAvgAccel;
    const CarState *c = &car.State;
    char b1[160], b2[160], b3[160];
    int i;

    printf("bm vt %08x car %s t %08x s %08x v %08x dv %08x ddv %08x sl %d\n",
           bm->Mover._vtable, lab(bm->pCar), bitsf(bm->fTime),
           bitsf(bm->fScale), bitsf(bm->v), bitsf(bm->dv), bitsf(bm->ddv),
           bm->bSliding);
    printf("bm spl %s u %s ang %s sld %s avg %s w %s %s %s %s\n",
           lab(bm->pSpline), lab(bm->pCubicU), lab(bm->pCubicAng),
           lab(bm->pCubicSlide), lab(bm->pAvgAccel), lab(bm->pWheels[0]),
           lab(bm->pWheels[1]), lab(bm->pWheels[2]), lab(bm->pWheels[3]));
    dump_cubic("u", bm->pCubicU);
    dump_cubic("ax", &bm->pCubicAng->x);
    dump_cubic("ay", &bm->pCubicAng->y);
    dump_cubic("sx", &bm->pCubicSlide->x);
    dump_cubic("sy", &bm->pCubicSlide->y);
    printf("avg %d %d %d %08x %08x\n", a->nSlots, a->nCurrentSlot,
           a->nSamples, bitsf(a->fTotal), bitsf(a->fAverage));
    printf("spl n %d max %d dirty %d minc %d maxp %08x minp %08x len %08x\n",
           s->NumControlPoints, s->MaxControlPoints, s->ControlPointsDirty,
           s->MinControlPoints, bitsf(s->MaxParam), bitsf(s->MinParam),
           bitsf(s->Length));
    for (i = -1; i < (int)s->NumControlPoints + 2; i++) {
        words(b1, sizeof b1, &s->pControlPoints[i], 4);
        printf("  cp%d %s\n", i, b1);
    }
    dump_graph("slide", &BeltSlideGraph);
    dump_graph("sliding", &BeltSlidingGraph);
    words(b1, sizeof b1, &c->Position, 4);
    words(b2, sizeof b2, &c->Velocity, 4);
    words(b3, sizeof b3, &c->AngularVelocity, 3);
    printf("cs pos %s vel %s av %s ang %d fs %08x vm %08x mv %d\n", b1, b2,
           b3, c->Angle, bitsf(c->ForwardSpeed), bitsf(c->VelocityMagnitude),
           c->MatrixValid);
    words(b1, sizeof b1, c->WheelSlip, 8);
    words(b2, sizeof b2, c->WheelTractionUsage, 4);
    printf("cs slip %s tu %s\n", b1, b2);
    printf("timer %08x\n", aicc.OffBeltTimer.PackedTime);
    for (i = 0; i < 4; i++) {
        const Wheel *w = bm->pWheels[i];
        if (w == NULL)
            continue;
        printf("w%d slip %08x %08x sl %d cur %08x\n", i, bitsf(w->Slip[0]),
               bitsf(w->Slip[1]), w->Slipping, bitsf(w->CurrentSlip));
    }
}

// ------------------------------------------------------------- the main

static void vec(const char *name, float t, const bVector3 *r,
                const bVector3 *out)
{
    char b[80];

    words(b, sizeof b, out, 4);
    printf("%s %08x -> %s %s\n", name, bitsf(t), r == out ? "out" : "?", b);
}

int main(int argc, char **argv)
{
    static VtEntry dvt[CARDRIVER_VT_ENTRIES];
    static VtEntry wvt[2];
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: beltmover_test ops.bin\n");
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
    beltmover_install_vtables();
    beltmover_install_seams();
    dvt[VT_SLOT(CARDRIVER_VT_GET_DESIRED_SPEED)].fn = (VtFn)fake_gds;
    dvt[VT_SLOT(144)].fn = (VtFn)fake_gtts;
    vt_install(DVT, dvt, CARDRIVER_VT_ENTRIES);
    wvt[VT_SLOT(PHYSICSCOMPONENT_VT_DTOR)].fn = (VtFn)fake_wheel_dtor;
    vt_install(WVT, wvt, 2);

    pCurrentWorld = (World *)(void *)world_mem;
    car.pCarTypeInfo = &cti;
    car.pCarController = (CarController *)(void *)&aicc;
    car.pCarDriver = &drv;
    drv._vtable = DVT;

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_JUNK: {
            int32_t seed = next();
            size_t k;
            for (k = 0; k < sizeof bmu.b; k++)
                bmu.b[k] = (unsigned char)(0xa1 + seed + 7 * (int)k);
            break;
        }
        case OP_CS: {
            int32_t id = next(), v = next();
            char kind;
            void *p = cs_field(id, &kind);
            if (kind == 'h')
                *(uint16_t *)p = (uint16_t)v;
            else
                memcpy(p, &v, 4);
            break;
        }
        case OP_CTI: {
            int32_t off = next(), v = next();
            memcpy((char *)&cti + off, &v, 4);
            break;
        }
        case OP_DTN:
            drv.MyDriveTarget.NumPoints = (int8_t)next();
            break;
        case OP_DTP: {
            int32_t i = next();
            bVector3 *p = &drv.MyDriveTarget.Points[i];
            p->x = fbits((uint32_t)next());
            p->y = fbits((uint32_t)next());
            p->z = fbits((uint32_t)next());
            p->pad = fbits(0x40400000u + (uint32_t)i);
            break;
        }
        case OP_DTL:
            drv.MyDriveTarget.Length = fbits((uint32_t)next());
            break;
        case OP_STEER:
            drv.Steering = (uint16_t)next();
            break;
        case OP_SET: {
            int32_t k = next();
            vals[k] = (uint32_t)next();
            break;
        }
        case OP_TIMER:
            aicc.OffBeltTimer.PackedTime = (uint32_t)next();
            break;
        case OP_NEW: {
            CarMover *r;
            printf("new\n");
            r = gBeltMoverCtorFn(bm, &car);
            printf("new -> %s\n", lab(r));
            break;
        }
        case OP_DEL: {
            int32_t flags = next();
            const VtEntry *e = vt_slot(bm->Mover._vtable, CARMOVER_VT_DTOR);
            printf("del %d\n", flags);
            ((CarMoverDtorFn)e->fn)(vt_this(bm, e), flags);
            break;
        }
        case OP_SETBELT:
            printf("setbelt\n");
            gBeltMoverSetBeltFn(&bm->Mover);
            break;
        case OP_FIND:
            printf("find\n");
            beltmover_find_coordinates(bm);
            break;
        case OP_MOVE: {
            float dt = fbits((uint32_t)next());
            const VtEntry *e = vt_slot(bm->Mover._vtable, CARMOVER_VT_MOVE);
            float r;
            printf("move %08x\n", bitsf(dt));
            r = ((CarMoverMoveFn)e->fn)(vt_this(bm, e), dt);
            printf("move -> %08x\n", bitsf(r));
            break;
        }
        case OP_GRAV:
            printf("grav -> %08x\n", bitsf(gBeltMoverGravityFn(&bm->Mover)));
            break;
        case OP_MAXACC:
            printf("maxacc -> %08x\n",
                   bitsf(beltmover_get_maximum_acceleration(bm)));
            break;
        case OP_SLIDE: {
            float a = fbits((uint32_t)next());
            float r;
            printf("slide %08x\n", bitsf(a));
            r = beltmover_slide_coef(bm, a);
            printf("slide -> %08x\n", bitsf(r));
            break;
        }
        case OP_AIR: {
            float dt = fbits((uint32_t)next());
            float r = beltmover_average_air(bm, dt);
            printf("air %08x -> %08x\n", bitsf(dt), bitsf(r));
            break;
        }
        case OP_GP:
        case OP_GD:
        case OP_GDD: {
            float t = fbits((uint32_t)next());
            bVector3 out;
            bVector3 *r;
            memset(&out, 0x5a, sizeof out);
            if (op == OP_GP)
                r = beltmover_get_point(bm, &out, t);
            else if (op == OP_GD)
                r = beltmover_get_derivative(bm, &out, t);
            else
                r = beltmover_get_second_derivative(bm, &out, t);
            vec(op == OP_GP ? "gp" : op == OP_GD ? "gd" : "gdd", t, r, &out);
            break;
        }
        case OP_DOT: {
            bVector3 pos, a, b;
            float t, r;
            char ba[80], bb[80];
            pos.x = fbits((uint32_t)next());
            pos.y = fbits((uint32_t)next());
            pos.z = fbits((uint32_t)next());
            pos.pad = fbits((uint32_t)next());
            t = fbits((uint32_t)next());
            memset(&a, 0x5a, sizeof a);
            memset(&b, 0x5a, sizeof b);
            r = beltmover_dot(bm, &pos, &a, &b, t);
            words(ba, sizeof ba, &a, 4);
            words(bb, sizeof bb, &b, 4);
            printf("dot %08x -> %08x a %s b %s\n", bitsf(t), bitsf(r), ba,
                   bb);
            break;
        }
        case OP_POKE: {
            int32_t off = next(), v = next();
            float f = fbits((uint32_t)v);
            switch (off) {
            case 12: bm->fTime = f; break;
            case 16: bm->fScale = f; break;
            case 28: bm->v = f; break;
            case 32: bm->dv = f; break;
            case 36: bm->ddv = f; break;
            case 52: bm->bSliding = v; break;
            default:
                fprintf(stderr, "no poke %d\n", off);
                return 2;
            }
            break;
        }
        case OP_CUBIC: {
            int32_t which = next(), off = next(), v = next();
            char *c = (char *)cubic_of(which);
            if (off >= 44) {
                uint16_t h = (uint16_t)v;
                memcpy(c + off, &h, 2);
            } else {
                memcpy(c + off, &v, 4);
            }
            break;
        }
        case OP_CPW: {
            int32_t i = next(), v = next();
            bm->pSpline->pControlPoints[i].w = fbits((uint32_t)v);
            break;
        }
        case OP_AVGREC:
            average_record(bm->pAvgAccel, fbits((uint32_t)next()));
            break;
        case OP_DDVAL: {
            int32_t which = next();
            float t = fbits((uint32_t)next());
            printf("ddval %d %08x -> %08x\n", which, bitsf(t),
                   bitsf(bspline_get_ddval(cubic_of(which), t)));
            break;
        }
        case OP_NULLP: {
            int32_t k = next();
            if (k == 0)
                bm->pAvgAccel = NULL;
            else if (k == 1)
                bm->pSpline = NULL;
            else
                bm->pWheels[k - 2] = NULL;
            break;
        }
        case OP_DUMP:
            dump();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
