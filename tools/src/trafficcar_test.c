// Harness for tools/trafficcar_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     trafficcar_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "physicscar.h"
#include "replay.h"
#include "table.h"
#include "trafficcar.h"
#include "vtable.h"

enum {
    OP_TAG, OP_JUNK, OP_CS, OP_CTI, OP_DRV, OP_SET, OP_NEW, OP_DEL, OP_MOVE,
    OP_POKE, OP_STOP, OP_TABLE, OP_TABLES, OP_DUMP
};

enum { K_FLATDX, K_FLATDZ, K_COUNT };
enum { D_STEER, D_THROTTLE, D_BRAKE };

// ------------------------------------------------------------- the world

static union {
    TrafficCar m;
    unsigned char b[sizeof(TrafficCar)];
} tcu;
static TrafficCar *const tc = &tcu.m;

static Car         car;
static CarTypeInfo cti;
static CarDriver   drv;

// What OP_DEL puts in the vptr before the destructor runs.
#define DEL_JUNK_VPTR 0x00c0ffeeu

// carmodes.c's seam, which trafficcar_install_seams sets.
CarMoverCtorFn gTrafficCarCtorFn;

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

// A float's bits, or "nan" for any NaN: the EE has none, and which one an
// IEEE host or the model makes is neither's to say.
static const char *hx(uint32_t b)
{
    static char bufs[16][12];
    static int k;
    char *s = bufs[k++ & 15];

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu) != 0)
        snprintf(s, 12, "nan");
    else
        snprintf(s, 12, "%08x", b);
    return s;
}

static const char *lab(const void *a)
{
    if (a == NULL)
        return "null";
    if (a == (const void *)tc)
        return "tc";
    if (a == (const void *)&car)
        return "car";
    if (a == (const void *)&car.State)
        return "cs";
    if (a == (const void *)&drv)
        return "drv";
    if (a == (const void *)&cti)
        return "cti";
    return "?";
}

// ------------------------------------------------------------ stand-ins

uint16_t car_get_steering(Car *c)
{
    printf("  steer %s -> %d\n", lab(c), c->pCarDriver->Steering);
    return c->pCarDriver->Steering;
}

void car_put_flat_on_track(Car *c)
{
    printf("  flat %s\n", lab(c));
    car.State.Position.x = car.State.Position.x + fbits(vals[K_FLATDX]);
    car.State.Position.z = car.State.Position.z + fbits(vals[K_FLATDZ]);
}

void carstate_set_wheel_touching_ground(CarState *s, int wheel, int8_t on)
{
    printf("  touch %s %d %d\n", lab(s), wheel, on);
}

void carstate_set_wheel_terrain(CarState *s, int wheel, TerrainType t)
{
    printf("  terrain %s %d %d\n", lab(s), wheel, (int)t);
}

void carstate_calculate_wheel_matrices(CarState *s)
{
    printf("  wmat %s\n", lab(s));
}

void carstate_calculate_geometry_position(CarState *s)
{
    printf("  geom %s\n", lab(s));
}

void car_compute_fake_rpm(Car *c)
{
    printf("  rpm %s\n", lab(c));
}

void carmover_destroy(CarMover *m, int32_t flags)
{
    printf("  carmover dtor %s %d\n", lab(m), flags);
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
        return &(&s->AngularVelocity.x)[id - 8];
    if (id < 16)
        return &s->WheelAngularVelocity[id - 12];
    if (id < 20)
        return &s->WheelAngle[id - 16];
    if (id < 24)
        return &s->WheelZForce[id - 20];
    if (id < 28)
        return &s->WheelBottomOutMagnitude[id - 24];
    if (id < 32)
        return &s->WheelSuspensionHeight[id - 28];
    if (id < 40)
        return &(&s->WheelSlip[0].x)[id - 32];
    if (id < 44)
        return &s->WheelTractionUsage[id - 40];
    if (id == 44) {
        *kind = 'h';
        return &s->Angle;
    }
    if (id == 45) {
        *kind = 'h';
        return &s->SteeringAngle;
    }
    if (id == 46)
        return &s->ForwardSpeed;
    if (id == 47)
        return &s->VelocityMagnitude;
    if (id == 48) {
        *kind = 'w';
        return &s->MatrixValid;
    }
    fprintf(stderr, "no field %d\n", id);
    exit(2);
}

// The mover's fields by the console's offsets.
static float *tc_field(int off)
{
    switch (off) {
    case 12: return &tc->Position.x;
    case 16: return &tc->Position.y;
    case 20: return &tc->Angle;
    case 24: return &tc->Speed;
    case 28: return &tc->Pitch;
    case 32: return &tc->Roll;
    }
    fprintf(stderr, "no mover field %d\n", off);
    exit(2);
}

static const Table *table_of(int which)
{
    switch (which) {
    case 0: return &TrafficAcceleration;
    case 1: return &TrafficBraking;
    case 2: return &StoppingDistanceTable;
    }
    fprintf(stderr, "no table %d\n", which);
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
        at += (size_t)snprintf(buf + at, n - at, k ? " %s" : "%s",
                               hx(w[k]));
}

static void dump(void)
{
    const CarState *c = &car.State;
    char b1[160], b2[160], b3[160], b4[160], b5[160];

    printf("tc vt %08x drv %s car %s pos %s %s ang %s spd %s p %s r %s\n",
           tc->Mover._vtable, lab(tc->Mover.Driver), lab(tc->pCar),
           hx(bitsf(tc->Position.x)), hx(bitsf(tc->Position.y)),
           hx(bitsf(tc->Angle)), hx(bitsf(tc->Speed)), hx(bitsf(tc->Pitch)),
           hx(bitsf(tc->Roll)));
    words(b1, sizeof b1, &c->Position, 4);
    words(b2, sizeof b2, &c->Velocity, 4);
    words(b3, sizeof b3, &c->AngularVelocity, 4);
    printf("cs pos %s vel %s av %s ang %d st %d fs %s vm %s mv %d\n",
           b1, b2, b3, c->Angle, c->SteeringAngle,
           hx(bitsf(c->ForwardSpeed)), hx(bitsf(c->VelocityMagnitude)),
           c->MatrixValid);
    words(b1, sizeof b1, c->WheelAngularVelocity, 4);
    words(b2, sizeof b2, c->WheelAngle, 4);
    words(b3, sizeof b3, c->WheelZForce, 4);
    words(b4, sizeof b4, c->WheelBottomOutMagnitude, 4);
    words(b5, sizeof b5, c->WheelSuspensionHeight, 4);
    printf("cs wav %s wang %s zf %s bo %s sh %s\n", b1, b2, b3, b4, b5);
    words(b1, sizeof b1, c->WheelSlip, 8);
    words(b2, sizeof b2, c->WheelTractionUsage, 4);
    printf("cs slip %s tu %s\n", b1, b2);
}

static void dump_tables(void)
{
    char b[61 * 9 + 8];
    int i;

    for (i = 0; i < 3; i++) {
        const Table *t = table_of(i);
        printf("table %d n %d min %s max %s mul %s\n", i, t->NumEntries,
               hx(bitsf(t->MinArg)), hx(bitsf(t->MaxArg)),
               hx(bitsf(t->IndexMultiplier)));
        words(b, sizeof b, t->pTable, t->NumEntries);
        printf("  data %s\n", b);
    }
}

// ------------------------------------------------------------- the main

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: trafficcar_test ops.bin\n");
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

    vt_reset();
    trafficcar_install_vtables();
    trafficcar_install_seams();
    trafficcar_static_init();

    car.pCarTypeInfo = &cti;
    car.pCarDriver = &drv;

    while (rd < end) {
        int32_t op = next();
        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_JUNK: {
            int32_t seed = next();
            size_t k;
            for (k = 0; k < sizeof tcu.b; k++)
                tcu.b[k] = (unsigned char)(0xa1 + seed + 7 * (int)k);
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
        case OP_DRV: {
            int32_t which = next(), v = next();
            if (which == D_STEER)
                drv.Steering = (uint16_t)v;
            else if (which == D_THROTTLE)
                drv.Throttle = fbits((uint32_t)v);
            else
                drv.Brake = fbits((uint32_t)v);
            break;
        }
        case OP_SET: {
            int32_t k = next();
            vals[k] = (uint32_t)next();
            break;
        }
        case OP_NEW: {
            CarMover *r;
            printf("new\n");
            r = gTrafficCarCtorFn(tc, &car);
            printf("new -> %s\n", lab(r));
            break;
        }
        case OP_DEL: {
            int32_t flags = next();
            const VtEntry *e = vt_slot(tc->Mover._vtable, CARMOVER_VT_DTOR);
            printf("del %d\n", flags);
            // A vptr not its own, so that the destructor's store shows.
            tc->Mover._vtable = DEL_JUNK_VPTR;
            ((CarMoverDtorFn)e->fn)(vt_this(tc, e), flags);
            printf("del vt %08x\n", tc->Mover._vtable);
            break;
        }
        case OP_MOVE: {
            float dt = fbits((uint32_t)next());
            const VtEntry *e = vt_slot(tc->Mover._vtable, CARMOVER_VT_MOVE);
            float r;
            // The mover's driver is the car's, as SetMovementMode leaves it.
            tc->Mover.Driver = &drv;
            printf("move %s\n", hx(bitsf(dt)));
            r = ((CarMoverMoveFn)e->fn)(vt_this(tc, e), dt);
            printf("move -> %s\n", hx(bitsf(r)));
            break;
        }
        case OP_POKE: {
            int32_t off = next(), v = next();
            memcpy(tc_field(off), &v, 4);
            break;
        }
        case OP_STOP: {
            float a = fbits((uint32_t)next());
            float b = fbits((uint32_t)next());
            float r = trafficcar_calculate_stop_distance(tc, a, b);
            printf("stop %s %s -> %s\n", hx(bitsf(a)), hx(bitsf(b)),
                   hx(bitsf(r)));
            break;
        }
        case OP_TABLE: {
            int32_t which = next();
            float a = fbits((uint32_t)next());
            float r = table_get_value(table_of(which), a);
            printf("value %d %s -> %s\n", which, hx(bitsf(a)),
                   hx(bitsf(r)));
            break;
        }
        case OP_TABLES:
            dump_tables();
            break;
        case OP_DUMP:
            dump();
            break;
        default:
            fprintf(stderr, "bad op %d\n", op);
            return 2;
        }
    }
    return 0;
}

// ----------------------------------------------- the snapshots, unreached
// The replay snapshot code in trafficcar.c (TASKS 72d) calls these;
// nothing here takes a snapshot.

static void snapshot_unreached_72d(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    (void)s; (void)p; (void)stored; (void)size; (void)is_signed;
    snapshot_unreached_72d("ReplaySnapshot_MoveData");
}

void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    (void)s; (void)object; (void)name;
    snapshot_unreached_72d("ReplaySnapshot_BeginSection");
}

void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    (void)s;
    snapshot_unreached_72d("ReplaySnapshot_EndSection");
}

void carmover_do_snapshot(CarMover *m, void *snap)
{
    (void)m; (void)snap;
    snapshot_unreached_72d("carmover_do_snapshot");
}
