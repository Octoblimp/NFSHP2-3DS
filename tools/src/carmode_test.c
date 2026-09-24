// Transcript harness for Car's fourth slice: carmodes, carcontroller,
// collisionbody and NullDriver. Cross-checked by tools/carmode_check.py,
// which runs the same scenarios on the image in mipsemu and compares the
// two transcripts line for line.
//
// This file is not compiled alone. The checker prepends a generated prefix
// -- a dump function and a field table for every struct the four methods
// build, parsed out of the port's headers, the inputs, and the map from
// each port function a table holds to the image's address for it -- and
// compiles the two as one translation unit.
//
// The general heap is hooked (bSetMemoryHooks): every block is logged,
// filled with 0xa5, and on free logged, filled with 0xdd and kept. The
// eight classes task 26 owns are stand-ins behind the seams, with tables of
// their own at fixed addresses, and the model stubs the image's
// constructors with the same stand-ins.

#ifndef CM_GENERATED
#error "carmode_test.c is built by tools/carmode_check.py, which prepends the generated dumps"
#endif

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "bticker.h"
#include "car.h"
#include "collisionbody.h"
#include "p32.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "race.h"
#include "realcontroller.h"

// car.c's, and nothing this harness runs reads it.
int32_t WorldTimeFrames = 0;

static float fb(uint32_t b)
{
    float f;
    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bf(float f)
{
    uint32_t b;
    memcpy(&b, &f, 4);
    return b;
}

// ------------------------------------------------------------ the objects

static Car              *g_car, *g_car2;
static CarCollisionBody *g_ccb, *g_ccb2;
static CarTypeInfo      *g_cti;
static DriverInfo       *g_di;
static DriveTarget      *g_tgt;
static char              g_topo[16];
static int32_t           g_race[4];

// 1 while a dump prints: the current mover's components are named too.
static int g_full;

typedef struct Obj {
    const char   *name;
    const void   *base;
    size_t        size;
    const PcType *t;
} Obj;

// Every block the heap handed out and every stand-in driver, oldest first.
typedef struct Reg {
    char          name[40];
    void         *p;
    size_t        size;
    const PcType *t;
} Reg;

#define CM_MAX_REG 2048
static Reg g_reg[CM_MAX_REG];
static int g_nreg, g_nalloc, g_nfake;

static void reg_add(const char *name, void *p, size_t size, const PcType *t)
{
    if (g_nreg == CM_MAX_REG) {
        fprintf(stderr, "carmode_test: more than %d blocks\n", CM_MAX_REG);
        abort();
    }
    snprintf(g_reg[g_nreg].name, sizeof g_reg[g_nreg].name, "%s", name);
    g_reg[g_nreg].p = p;
    g_reg[g_nreg].size = size;
    g_reg[g_nreg].t = t;
    g_nreg++;
}

static const Reg *reg_find(const void *p)
{
    int i;
    for (i = g_nreg - 1; i >= 0; i--)
        if (g_reg[i].p == p)
            return &g_reg[i];
    return NULL;
}

static const char *const wheel_name[4] = { "wheel0", "wheel1", "wheel2", "wheel3" };
static const char *const susp_name[4] = { "susp0", "susp1", "susp2", "susp3" };

// The model's objects in the model's order.
static int objects(Obj *o)
{
    int n = 0;
    int i;
#define ADD(nm, b, sz, ty)                                                  \
    do {                                                                    \
        if ((b) != NULL) {                                                  \
            o[n].name = (nm); o[n].base = (b);                              \
            o[n].size = (sz); o[n].t = (ty); n++;                           \
        }                                                                   \
    } while (0)
    if (g_car != NULL) {
        ADD("cs", &g_car->State, sizeof(CarState), &pct_CarState);
        ADD("car", g_car, sizeof(Car), NULL);
        ADD("car2", g_car2, sizeof(Car), NULL);
        ADD("ccb", g_ccb, sizeof(CarCollisionBody), NULL);
        ADD("ccb2", g_ccb2, sizeof(CarCollisionBody), NULL);
        ADD("cti", g_cti, 1368, NULL);
        ADD("topo", g_topo, sizeof g_topo, NULL);
        ADD("di", g_di, sizeof(DriverInfo), NULL);
        ADD("tgt", g_tgt, sizeof(DriveTarget), NULL);
        if (g_full && g_car->pCarMover != NULL) {
            CarMover *m = g_car->pCarMover;
            if (g_car->TheMovementMode == eNO_MOVEMENT) {
                ADD("nm", m, sizeof(NullMover), &pct_NullMover);
            } else if (g_car->TheMovementMode == PHYSICS_MOVEMENT) {
                PhysicsCar *pc = (PhysicsCar *)m;
                ADD("pc", pc, sizeof(PhysicsCar), &pct_PhysicsCar);
                ADD("body", pc->pBody, sizeof(RigidBody), &pct_RigidBody);
                ADD("steer", pc->pSteering, sizeof(TwoWheelAckermanSteering),
                    &pct_TwoWheelAckermanSteering);
                for (i = 0; i < 4; i++)
                    ADD(wheel_name[i], pc->pWheel[i], sizeof(Wheel),
                        &pct_Wheel);
                for (i = 0; i < 4; i++)
                    ADD(susp_name[i], pc->pSuspension[i], sizeof(Suspension),
                        &pct_Suspension);
                ADD("engine", pc->pEngine, sizeof(Engine), &pct_Engine);
                ADD("dtrain", pc->pDriveTrain, sizeof(DriveTrain),
                    &pct_DriveTrain);
                ADD("aero", pc->pAerodynamics, sizeof(Aerodynamics),
                    &pct_Aerodynamics);
            } else if (g_car->TheMovementMode == MELLOW_MOVEMENT) {
                MellowMover *mm = (MellowMover *)m;
                ADD("mm", mm, sizeof(MellowMover), &pct_MellowMover);
                ADD("mv", mm->pMellovator, sizeof(Mellovator),
                    &pct_Mellovator);
                ADD("body", mm->pBody, sizeof(RigidBody), &pct_RigidBody);
                ADD("aero", mm->pAerodynamics, sizeof(Aerodynamics),
                    &pct_Aerodynamics);
                for (i = 0; i < 4; i++)
                    ADD(wheel_name[i], mm->pWheels[i], sizeof(Wheel),
                        &pct_Wheel);
            }
        }
    }
    for (i = g_nreg - 1; i >= 0; i--)
        ADD(g_reg[i].name, g_reg[i].p, g_reg[i].size, g_reg[i].t);
#undef ADD
    return n;
}

static const char *label(const void *p)
{
    static char buf[8][96];
    static int k;
    static Obj o[CM_MAX_REG + 64];
    char *s = buf[k++ & 7];
    int n, i, j;

    if (p == NULL)
        return "null";
    n = objects(o);
    for (i = 0; i < n; i++) {
        const char *b = (const char *)o[i].base;
        size_t off;
        if ((const char *)p < b || (const char *)p >= b + o[i].size)
            continue;
        off = (size_t)((const char *)p - b);
        if (o[i].t != NULL) {
            for (j = 0; j < o[i].t->n; j++) {
                const PcField *f = &o[i].t->f[j];
                if (f->hoff <= off && off < f->hoff + f->hsize) {
                    snprintf(s, 96, "%s.%s+%d", o[i].name, f->name,
                             (int)(off - f->hoff));
                    return s;
                }
            }
        }
        snprintf(s, 96, "%s+%d", o[i].name, (int)off);
        return s;
    }
    return "?";
}

// ------------------------------------------------------------ the printing

static void pc_raw(const char *pfx, const char *name, const void *p, size_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    size_t i;

    if (n % 4) {
        printf("%s.%s =", pfx, name);
        for (i = 0; i < n; i++)
            printf(" %02x", b[i]);
        printf("\n");
        return;
    }
    for (i = 0; i < n; i += 16) {
        size_t j;
        if (n <= 16)
            printf("%s.%s =", pfx, name);
        else
            printf("%s.%s@%d =", pfx, name, (int)i);
        for (j = i; j < i + 16 && j < n; j += 4) {
            uint32_t w;
            memcpy(&w, b + j, 4);
            printf(" %08x", w);
        }
        printf("\n");
    }
}

static void pc_ptr(const char *pfx, const char *name, const void *p)
{
    printf("%s.%s -> %s\n", pfx, name, label(p));
}

static const char *pc_sub(const char *pfx, const char *name)
{
    static char buf[8][96];
    static int k;
    char *s = buf[k++ & 7];
    snprintf(s, 96, "%s.%s", pfx, name);
    return s;
}

// ------------------------------------------------------------ the heap

static void *hook_malloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    const PcType *t = NULL;
    int shown = size;
    char nm[40];

    if (p == NULL)
        abort();
    memset(p, 0xa5, (size_t)size);
    // The three records the port has are its own size; the log shows the
    // image's, so a wrong size still shows.
    if (strcmp(name, "PhysicsCar") == 0 && size == (int)sizeof(PhysicsCar)) {
        t = &pct_PhysicsCar;
        shown = CM_IMG_PHYSICSCAR;
    } else if (strcmp(name, "NullController") == 0
               && size == (int)sizeof(NullController)) {
        t = &pct_NullController;
        shown = CM_IMG_NULLCONTROLLER;
    } else if (strcmp(name, "NullDriver") == 0
               && size == (int)sizeof(NullDriver)) {
        shown = CM_IMG_NULLDRIVER;
    } else if (strcmp(name, "RealController") == 0
               && size == (int)sizeof(RealController)) {
        // Ported, though the stand-in still builds in it here.
        shown = CM_IMG_REALCONTROLLER;
    }
    g_nalloc++;
    snprintf(nm, sizeof nm, "%s#%d", name, g_nalloc);
    reg_add(nm, p, (size_t)size, t);
    printf("alloc %s size=%d flags=%d pool=%d\n", nm, shown, flags, pool);
    return p;
}

// Logged and poisoned, never freed: nothing is reused.
static void hook_free(void *p)
{
    const Reg *r = reg_find(p);

    printf("free %s\n", r != NULL ? r->name : label(p));
    if (r != NULL)
        memset(r->p, 0xdd, r->size);
}

// ------------------------------------------------------------ the stand-ins

static uint32_t g_tick;

static uint32_t scripted_tick(void)
{
    g_tick += 1000;
    return g_tick;
}

// physicscar_test.c's plane, normal, terrain and noise.
static float fake_elevation(void *topology, const bVector3 *pos,
                            int32_t *terrainOut, bVector3 *normalOut)
{
    float el = 0.03125f * pos->x + -0.015625f * pos->y;

    printf("elev topo=%s pos=%08x %08x %08x tout=%s nout=%s\n",
           label(topology), bf(pos->x), bf(pos->y), bf(pos->z),
           label(terrainOut), label(normalOut));
    normalOut->x = fb(CM_NORMAL_X);
    normalOut->y = fb(CM_NORMAL_Y);
    normalOut->z = fb(CM_NORMAL_Z);
    normalOut->pad = 0.0f;
    if (terrainOut != NULL)
        *terrainOut = ((int32_t)(pos->x * 0.5f)) & 3;
    return el;
}

static float fake_road_noise(const bVector2 *xy, int32_t terrain)
{
    printf("noise terrain=%d x=%08x\n", (int)terrain, bf(xy->x));
    return 0.25f * (float)terrain + 0.001f * xy->x;
}

static void *topology_of(void *carState)
{
    return ((CarState *)carState)->pTopologyCoordinate;
}

static void fake_skids(Wheel *w, float dt)
{
    printf("skids %s dt=%08x\n", label(w), bf(dt));
}

static TerrainTypeInfo g_terrain[4];

static void build_terrain(void)
{
    int i;
    for (i = 0; i < 4; i++) {
        g_terrain[i].StaticFrictionMultiplier  = fb(CM_TERRAIN[i][0]);
        g_terrain[i].DynamicFrictionMultiplier = fb(CM_TERRAIN[i][1]);
        g_terrain[i].RollingFrictionMultiplier = fb(CM_TERRAIN[i][2]);
    }
}

// ------------------------------------------------ task 26's eight classes

static const char *const mover_cls[4] = {
    "TrafficCar", "DeliveryMover", "CopMover", "BeltMover",
};
static const char *const ctrl_cls[4] = {
    "RealController", "AIDriver", "TrafficDriver", "CopDriver",
};

static uint32_t fake_vt(int controller, int k)
{
    return CM_FAKE_VT + 0x100u * (uint32_t)(controller ? 4 + k : k);
}

static void fake_dtor(const char *cls, void *self, int32_t flags)
{
    printf("dtor %s this=%s flags=%d\n", cls, label(self), (int)flags);
    if (flags & 1)
        bFree(self);
}

static CarDriver *new_fake_driver(void)
{
    CarDriver *d = calloc(1, sizeof(CarDriver));
    char nm[40];

    d->_vtable = CM_FAKE_VT_DRIVER;
    g_nfake++;
    snprintf(nm, sizeof nm, "fdrv#%d", g_nfake);
    reg_add(nm, d, sizeof(CarDriver), NULL);
    return d;
}

// The car's two modes as the constructor finds them: both methods store the
// new mode before the arm, and a class may read it.
static void say_ctor(const char *cls, void *mem, Car *car)
{
    printf("ctor %s mem=%s car=%s modes=%d/%d\n", cls, label(mem),
           label(car), (int)car->TheControlMode, (int)car->TheMovementMode);
}

static CarMover *fake_mover_ctor(int k, void *mem, Car *car)
{
    CarMover *m = mem;

    say_ctor(mover_cls[k], mem, car);
    m->_vtable = fake_vt(0, k);
    return m;
}

static CarController *fake_ctrl_ctor(int k, void *mem, Car *car)
{
    CarController *c = mem;
    CarDriver *d;

    say_ctor(ctrl_cls[k], mem, car);
    d = new_fake_driver();
    c->pCar = car;
    c->Driver = d;
    c->_vtable = fake_vt(1, k);
    return c;
}

static void fake_stpm(int k, void *self, Car *other)
{
    printf("stpm %s this=%s other=%s\n", ctrl_cls[k], label(self),
           label(other));
}

#define FAKE_MOVER(k, cls)                                                  \
    static void fake_##cls##_dtor(void *s, int32_t f)                       \
    { fake_dtor(#cls, s, f); }                                              \
    static CarMover *fake_##cls##_ctor(void *m, Car *c)                     \
    { return fake_mover_ctor(k, m, c); }
#define FAKE_CTRL(k, cls)                                                   \
    static void fake_##cls##_dtor(void *s, int32_t f)                       \
    { fake_dtor(#cls, s, f); }                                              \
    static void fake_##cls##_stpm(void *s, Car *o)                          \
    { fake_stpm(k, s, o); }                                                 \
    static CarController *fake_##cls##_ctor(void *m, Car *c)                \
    { return fake_ctrl_ctor(k, m, c); }

FAKE_MOVER(0, TrafficCar)
FAKE_MOVER(1, DeliveryMover)
FAKE_MOVER(2, CopMover)
FAKE_MOVER(3, BeltMover)
FAKE_CTRL(0, RealController)
FAKE_CTRL(1, AIDriver)
FAKE_CTRL(2, TrafficDriver)
FAKE_CTRL(3, CopDriver)

static void fdrv_dtor(void *self, int32_t flags)
{
    fake_dtor("fdrv", self, flags);
}

static void fdrv_snapshot(void *self, void *snap)
{
    printf("snapshot this=%s snap=%s\n", label(self), label(snap));
}

#define E(f) { 0, 0, (VtFn)(f) }
#define N    { 0, 0, NULL }

static const VtEntry fake_mover_vt[4][2] = {
    { N, E(fake_TrafficCar_dtor) },
    { N, E(fake_DeliveryMover_dtor) },
    { N, E(fake_CopMover_dtor) },
    { N, E(fake_BeltMover_dtor) },
};

// Slots 8 and 88; nothing the four methods do reaches the rest.
#define CTRL_VT(cls)                                                        \
    { N, E(fake_##cls##_dtor), N, N, N, N, N, N, N, N, N,                   \
      E(fake_##cls##_stpm) }
static const VtEntry fake_ctrl_vt[4][12] = {
    CTRL_VT(RealController),
    CTRL_VT(AIDriver),
    CTRL_VT(TrafficDriver),
    CTRL_VT(CopDriver),
};

static const VtEntry fake_driver_vt[4] = {
    N, E(fdrv_dtor), N, E(fdrv_snapshot),
};

#undef CTRL_VT
#undef E
#undef N

static void install_fakes(void)
{
    int k;
    for (k = 0; k < 4; k++) {
        vt_install(fake_vt(0, k), fake_mover_vt[k], 2);
        vt_install(fake_vt(1, k), fake_ctrl_vt[k], 12);
    }
    vt_install(CM_FAKE_VT_DRIVER, fake_driver_vt, 4);

    gTrafficCarCtorFn      = fake_TrafficCar_ctor;
    gDeliveryMoverCtorFn   = fake_DeliveryMover_ctor;
    gCopMoverCtorFn        = fake_CopMover_ctor;
    gBeltMoverCtorFn       = fake_BeltMover_ctor;
    gRealControllerCtorFn  = fake_RealController_ctor;
    gAIDriverCtorFn        = fake_AIDriver_ctor;
    gTrafficDriverCtorFn   = fake_TrafficDriver_ctor;
    gCopDriverCtorFn       = fake_CopDriver_ctor;
}

// ------------------------------------------------------------ the pools

static BSlotPool **const pools[10] = {
    &RigidBodySlotPool, &TwoWheelAckermanSteeringSlotPool, &WheelSlotPool,
    &EngineSlotPool, &DriveTrainSlotPool, &AerodynamicsSlotPool,
    &SuspensionSlotPool, &MellovatorSlotPool, &MellowMoverSlotPool,
    &NullMoverSlotPool,
};
static const char *const pool_name[10] = {
    "RigidBody", "Ackerman", "Wheel", "Engine", "DriveTrain", "Aerodynamics",
    "Suspension", "Mellovator", "MellowMover", "NullMover",
};
static int pool_free0[10];

static void say_pools(void)
{
    int i;
    printf("pools");
    for (i = 0; i < 10; i++)
        printf(" %s=%d", pool_name[i],
               pool_free0[i] - bCountFreeSlots(*pools[i]));
    printf("\n");
}

// ------------------------------------------------------------ the dump

static void car_line(void)
{
    CarMover *m = g_car->pCarMover;

    printf("car ctrl=%d move=%d controller=%s driver=%s mover=%s "
           "mover.drv=%s friction=%08x boost=%08x\n",
           (int)g_car->TheControlMode, (int)g_car->TheMovementMode,
           label(g_car->pCarController), label(g_car->pCarDriver), label(m),
           m != NULL ? label(m->Driver) : "-", bf(g_car->FrictionBoost),
           bf(g_car->State.BoostFactor));
}

static void ccb_line(void)
{
    printf("ccb mode=%d system=%s body=%s\n",
           (int)g_ccb->Dynamic.PhysicsMode, label(g_ccb->Dynamic.pSystem),
           label(g_ccb->Dynamic.pBody));
}

static void mover_dump(void)
{
    CarMover *m = g_car->pCarMover;
    int i;

    switch (g_car->TheMovementMode) {
    case eNO_MOVEMENT:
        dump_NullMover("nm", (NullMover *)m);
        break;
    case PHYSICS_MOVEMENT: {
        PhysicsCar *pc = (PhysicsCar *)m;
        dump_PhysicsCar("pc", pc);
        dump_RigidBody("body", pc->pBody);
        dump_TwoWheelAckermanSteering("steer",
                                      (TwoWheelAckermanSteering *)pc->pSteering);
        for (i = 0; i < 4; i++)
            dump_Wheel(wheel_name[i], pc->pWheel[i]);
        for (i = 0; i < 4; i++)
            dump_Suspension(susp_name[i], pc->pSuspension[i]);
        dump_Engine("engine", pc->pEngine);
        dump_DriveTrain("dtrain", pc->pDriveTrain);
        dump_Aerodynamics("aero", pc->pAerodynamics);
        break;
    }
    case MELLOW_MOVEMENT: {
        MellowMover *mm = (MellowMover *)m;
        dump_MellowMover("mm", mm);
        dump_Mellovator("mv", mm->pMellovator);
        dump_RigidBody("body", mm->pBody);
        dump_Aerodynamics("aero", mm->pAerodynamics);
        for (i = 0; i < 4; i++)
            dump_Wheel(wheel_name[i], mm->pWheels[i]);
        break;
    }
    default:
        printf("mover vt=%08x\n", (unsigned)m->_vtable);
    }
}

static void step(const char *tag, int driver)
{
    g_full = 1;
    printf("-- %s\n", tag);
    car_line();
    ccb_line();
    mover_dump();
    if (g_car->pCarController != NULL)
        dump_CarController("ctrl", g_car->pCarController);
    if (driver)
        pc_raw("drv", "bytes", g_car->pCarDriver, sizeof(CarDriver));
    dump_CarState("cs", &g_car->State);
    say_pools();
    g_full = 0;
}

// ------------------------------------------------- calls through a table

typedef void    (*FnV)(void *);
typedef void    (*FnI)(void *, int32_t);
typedef void    (*FnF)(void *, float);
typedef void    (*FnP)(void *, void *);
typedef void    (*FnPP)(void *, void *, void *);
typedef void    (*FnFFI)(void *, float, float, int32_t);
typedef void   *(*FnRP)(void *);
typedef float   (*FnRF)(void *);
typedef float   (*FnRFF)(void *, float);
typedef float   (*FnRFP)(void *, void *);
typedef int32_t (*FnRI)(void *);

#define SLOT(obj, vt, slot) const VtEntry *e = vt_slot((vt), (slot)); \
                            void *self = vt_this((obj), e)

static void v_v(void *o, uint32_t vt, int s)             { SLOT(o, vt, s); ((FnV)e->fn)(self); }
static void v_i(void *o, uint32_t vt, int s, int32_t i)  { SLOT(o, vt, s); ((FnI)e->fn)(self, i); }
static void v_f(void *o, uint32_t vt, int s, float f)    { SLOT(o, vt, s); ((FnF)e->fn)(self, f); }
static void v_p(void *o, uint32_t vt, int s, void *p)    { SLOT(o, vt, s); ((FnP)e->fn)(self, p); }
static void v_pp(void *o, uint32_t vt, int s, void *p, void *q)
{
    SLOT(o, vt, s);
    ((FnPP)e->fn)(self, p, q);
}
static void v_ffi(void *o, uint32_t vt, int s, float f, float g, int32_t i)
{
    SLOT(o, vt, s);
    ((FnFFI)e->fn)(self, f, g, i);
}
static void   *v_rp(void *o, uint32_t vt, int s)         { SLOT(o, vt, s); return ((FnRP)e->fn)(self); }
static float   v_rf(void *o, uint32_t vt, int s)         { SLOT(o, vt, s); return ((FnRF)e->fn)(self); }
static float   v_rff(void *o, uint32_t vt, int s, float f) { SLOT(o, vt, s); return ((FnRFF)e->fn)(self, f); }
static float   v_rfp(void *o, uint32_t vt, int s, void *p) { SLOT(o, vt, s); return ((FnRFP)e->fn)(self, p); }
static int32_t v_ri(void *o, uint32_t vt, int s)         { SLOT(o, vt, s); return ((FnRI)e->fn)(self); }

#undef SLOT

// ------------------------------------------------------------ the scenarios

static const char *fn_addr(VtFn fn)
{
    static char buf[4][16];
    static int k;
    char *s = buf[k++ & 3];
    int i;

    for (i = 0; i < CM_N(cm_fnmap); i++) {
        if (cm_fnmap[i].fn == fn) {
            snprintf(s, 16, "%08x", (unsigned)cm_fnmap[i].addr);
            return s;
        }
    }
    return "?";
}

static void s_tables(void)
{
    int t, i, n;

    printf("== tables\n");
    for (t = 0; t < CM_N(cm_tables); t++) {
        const VtEntry *e = vt_table(cm_tables[t].vt, &n);
        printf("vt %s n=%d", cm_tables[t].name, n);
        for (i = 1; i < n; i++)
            printf(" %d/%s", (int)e[i].delta,
                   e[i].fn != NULL ? fn_addr(e[i].fn) : "null");
        printf("\n");
    }
}

static void s_setup(void)
{
    CarState *cs;
    int i;

    g_cti = calloc(1, sizeof(CarTypeInfo));
    memcpy(g_cti, cm_cti, 1368);
    g_car = calloc(1, sizeof(Car));
    g_car2 = calloc(1, sizeof(Car));
    g_ccb = calloc(1, sizeof(CarCollisionBody));
    g_ccb2 = calloc(1, sizeof(CarCollisionBody));
    g_di = calloc(1, sizeof(DriverInfo));
    g_tgt = malloc(sizeof(DriveTarget));
    memcpy(g_tgt, cm_tgt, sizeof cm_tgt);
    g_car->pCarTypeInfo = g_cti;
    g_car->MyDriver = g_di;
    g_car->pDynamicCollisionBody = g_ccb;
    g_ccb->pCar = g_car;
    g_ccb2->pCar = g_car2;
    g_car->FrictionBoost = fb(CM_FRICTION0);
    g_car->RenderingEnabled = 1;
    cs = &g_car->State;
    cs->pCarInfo = (CarTypeInfoPrefix *)g_cti;
    cs->pTopologyCoordinate = (TopologyCoordinate *)g_topo;
    cs->Position.z = 0.4375f;
    cs->BodyMatrix.v0.x = 1.0f;
    cs->BodyMatrix.v1.y = 1.0f;
    cs->BodyMatrix.v2.z = 1.0f;
    cs->BodyMatrix.v3.w = 1.0f;
    for (i = 0; i < 4; i++)
        cs->WheelTouchingGround[i] = 1;
    cs->nWheelsTouchingGround = 4;
    cs->BoostFactor = 1.0f;

    printf("== setup\n");
    car_set_movement_mode(g_car, eNO_MOVEMENT);
    step("move null->0", 0);
    car_set_control_mode(g_car, eNO_CONTROL);
    step("ctrl null->0", 1);
}

static void s_move_walk(void)
{
    int i;
    for (i = 0; i + 1 < CM_N(cm_move_walk); i++) {
        printf("== move %d->%d\n", cm_move_walk[i], cm_move_walk[i + 1]);
        car_set_movement_mode(g_car, (MovementMode)cm_move_walk[i + 1]);
        step("after", 0);
    }
}

static void s_ctrl_walk(void)
{
    int i;
    for (i = 0; i + 1 < CM_N(cm_ctrl_walk); i++) {
        printf("== ctrl %d->%d\n", cm_ctrl_walk[i], cm_ctrl_walk[i + 1]);
        car_set_control_mode(g_car, (ControlMode)cm_ctrl_walk[i + 1]);
        step("after", cm_ctrl_walk[i + 1] == 0);
    }
}

static void s_ctrl_under(void)
{
    static const int mv[2] = { 1, 4 };
    static const int ctl[2] = { 2, 0 };
    char tag[16];
    int i, j;

    for (i = 0; i < 2; i++) {
        printf("== ctrl under %d\n", mv[i]);
        car_set_movement_mode(g_car, (MovementMode)mv[i]);
        for (j = 0; j < 2; j++) {
            car_set_control_mode(g_car, (ControlMode)ctl[j]);
            snprintf(tag, sizeof tag, "ctrl %d", ctl[j]);
            step(tag, 0);
        }
    }
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

static void s_stpm(void)
{
    static const char *const kinds[3] = { "none", "null", "fake" };
    int k, m;

    for (k = 0; k < 3; k++) {
        ControlMode want = k == 2 ? AI_CONTROL : eNO_CONTROL;
        for (m = 0; m < 7; m++) {
            CarController *saved;
            printf("== stpm %s %d\n", kinds[k], m);
            if (g_car->TheControlMode != want)
                car_set_control_mode(g_car, want);
            car_set_movement_mode(g_car, (MovementMode)m);
            saved = g_car->pCarController;
            if (k == 0)
                g_car->pCarController = NULL;
            car_set_to_physics_mode(g_car, g_car2);
            if (k == 0)
                g_car->pCarController = saved;
            step("after", 0);
        }
    }
    car_set_control_mode(g_car, eNO_CONTROL);
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

static void s_ccb(void)
{
    static const int runs[3][2] = { { 2, 1 }, { 0, 0 }, { 0, 2 } };
    int r, i;

    for (r = 0; r < 3; r++) {
        for (i = 0; i < CM_N(cm_ccb_other); i++) {
            int o = cm_ccb_other[i];
            if (o < 0)
                printf("== ccb stpm ctrl=%d move=%d other=null\n",
                       runs[r][0], runs[r][1]);
            else
                printf("== ccb stpm ctrl=%d move=%d other=%d\n",
                       runs[r][0], runs[r][1], o);
            if ((int)g_car->TheControlMode != runs[r][0])
                car_set_control_mode(g_car, (ControlMode)runs[r][0]);
            car_set_movement_mode(g_car, (MovementMode)runs[r][1]);
            if (o >= 0)
                g_ccb2->Dynamic.Body.Type = (uint8_t)o;
            // Stale pointers, so the set-up after the call shows even where
            // the mode switch inside it did one already.
            g_ccb->Dynamic.pSystem = (char *)g_cti + 4;
            g_ccb->Dynamic.pBody = (char *)g_cti + 8;
            carcollisionbody_set_to_physics_mode(
                g_ccb, o < 0 ? NULL : &g_ccb2->Dynamic.Body);
            step("after", 0);
        }
    }
    car_set_control_mode(g_car, eNO_CONTROL);
    for (i = 0; i < CM_N(cm_setup_cases); i++) {
        printf("== ccb setup mode=%d move=%d\n", cm_setup_cases[i][0],
               cm_setup_cases[i][1]);
        car_set_movement_mode(g_car, (MovementMode)cm_setup_cases[i][1]);
        g_ccb->Dynamic.PhysicsMode = cm_setup_cases[i][0];
        g_ccb->Dynamic.pSystem = (char *)g_cti + 4;
        g_ccb->Dynamic.pBody = (char *)g_cti + 8;
        carcollisionbody_setup_physics_pointers(g_ccb);
        g_full = 1;
        ccb_line();
        g_full = 0;
    }
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

// The pooled two by their record's size; the rest by what bMalloc was
// asked for.
static size_t mover_extent(int m)
{
    if (m == 0)
        return sizeof(NullMover);
    if (m == 4)
        return sizeof(MellowMover);
    return reg_find(g_car->pCarMover)->size;
}

// Past the mover's last byte is the next slot or the next block, which no
// dump reaches; a store through the wrong type lands there.
static void s_friction(void)
{
    unsigned char before[CM_STRAY];
    int m;
    for (m = 0; m < 7; m++) {
        const unsigned char *end;

        printf("== friction %d\n", m);
        car_set_movement_mode(g_car, (MovementMode)m);
        end = (const unsigned char *)g_car->pCarMover + mover_extent(m);
        memcpy(before, end, sizeof before);
        car_set_friction_boost(g_car, fb(cm_friction[m]));
        printf("past mover %s\n",
               memcmp(before, end, sizeof before) == 0 ? "same" : "written");
        step("after", 0);
    }
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

static void s_nullmover(void)
{
    NullMover *nm = (NullMover *)g_car->pCarMover;
    float r;

    printf("== nullmover\n");
    r = v_rff(nm, nm->Mover._vtable, CARMOVER_VT_MOVE, fb(CM_DT));
    printf("move ret=%08x\n", bf(r));
    v_p(nm, nm->Mover._vtable, CARMOVER_VT_DO_SNAPSHOT, (char *)g_cti + 40);
    step("move", 0);
    v_i(nm, nm->Mover._vtable, CARMOVER_VT_DTOR, 0);
    printf("dtor0 vt=%08x\n", (unsigned)nm->Mover._vtable);
    say_pools();
    nullmover_delete(nm);
    say_pools();
    g_car->pCarMover = NULL;
    car_set_movement_mode(g_car, eNO_MOVEMENT);
    step("again", 0);
}

static void s_nullcontroller(void)
{
    CarController *c = g_car->pCarController;
    float r;

    printf("== nullcontroller\n");
    v_v(c, c->_vtable, CARCONTROLLER_VT_DEBUG_DISPLAY);
    v_f(c, c->_vtable, CARCONTROLLER_VT_THINK, fb(CM_DT));
    v_pp(c, c->_vtable, CARCONTROLLER_VT_SET_CURRENT_ROUTE,
         (char *)g_cti + 16, (char *)g_cti + 32);
    printf("route=%s\n",
           label(v_rp(c, c->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE)));
    printf("point=%s\n",
           label(v_rp(c, c->_vtable,
                      CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT)));
    r = v_rf(c, c->_vtable, CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS);
    printf("oob=%08x\n", bf(r));
    v_v(c, c->_vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);
    v_v(c, c->_vtable, CARCONTROLLER_VT_JUST_RESET);
    v_f(c, c->_vtable, CARCONTROLLER_VT_FORCE_BOOST, fb(CM_BOOST0));
    printf("force boost=%08x\n", bf(g_car->State.BoostFactor));
    v_v(c, c->_vtable, CARCONTROLLER_VT_RELEASE_BOOST);
    printf("release boost=%08x\n", bf(g_car->State.BoostFactor));
    v_f(c, c->_vtable, CARCONTROLLER_VT_FORCE_BOOST, fb(CM_BOOST1));
    c->pCar = NULL;
    v_v(c, c->_vtable, CARCONTROLLER_VT_RELEASE_BOOST);
    printf("release no car boost=%08x\n", bf(g_car->State.BoostFactor));
    v_f(c, c->_vtable, CARCONTROLLER_VT_FORCE_BOOST, fb(CM_BOOST0));
    printf("force no car boost=%08x\n", bf(g_car->State.BoostFactor));
    c->pCar = g_car;
    v_v(c, c->_vtable, CARCONTROLLER_VT_RELEASE_BOOST);
    printf("driver=%s\n", label(carcontroller_get_driver(c)));
    step("after", 0);
}

static void driver_calls(CarDriver *d, int null)
{
    float r;

    if (null)
        v_f(d, d->_vtable, 16, fb(CM_DT));
    v_v(d, d->_vtable, 32);
    v_v(d, d->_vtable, 40);
    if (null) {
        v_v(d, d->_vtable, 48);
        v_ffi(d, d->_vtable, 56, fb(CM_DSPEED0), fb(CM_DSPEED1), 1);
    }
    v_p(d, d->_vtable, 64, g_tgt);
    v_p(d, d->_vtable, 72, (char *)g_cti + 8);
    if (null)
        printf("number=%d\n", (int)v_ri(d, d->_vtable, 80));
    v_v(d, d->_vtable, 88);
    v_v(d, d->_vtable, 96);
    printf("honking=%d\n", (int)v_ri(d, d->_vtable, 104));
    r = v_rfp(d, d->_vtable, 112, g_tgt);
    printf("maxspeed=%08x\n", bf(r));
    v_v(d, d->_vtable, 120);
    v_v(d, d->_vtable, 128);
    r = v_rf(d, d->_vtable, 136);
    printf("speed=%08x\n", bf(r));
    r = v_rf(d, d->_vtable, 144);
    printf("time=%08x\n", bf(r));
    v_i(d, d->_vtable, 152, 1);
    printf("point=%s\n", label(v_rp(d, d->_vtable, 160)));
    pc_raw("drv", "bytes", d, sizeof(CarDriver));
}

static void s_nulldriver(void)
{
    CarDriver *p;

    printf("== nulldriver\n");
    driver_calls(g_car->pCarDriver, 1);
    printf("== cardriver\n");
    p = malloc(sizeof(CarDriver));
    memset(p, 0xa5, sizeof(CarDriver));
    reg_add("cdrv", p, sizeof(CarDriver), NULL);
    cardriver_init(p);
    pc_raw("cdrv", "bytes", p, sizeof(CarDriver));
    driver_calls(p, 0);
    v_i(p, p->_vtable, CARDRIVER_VT_DTOR, 0);
    printf("dtor0 vt=%08x\n", (unsigned)p->_vtable);
    v_i(p, p->_vtable, CARDRIVER_VT_DTOR, 1);
}

static void s_dtors(void)
{
    CarController *c, *cc;
    CarDriver *d;

    printf("== dtor nullcontroller 0\n");
    c = g_car->pCarController;
    v_i(c, c->_vtable, CARCONTROLLER_VT_DTOR, 0);
    printf("ctrl vt=%08x\n", (unsigned)c->_vtable);
    bFree(c);
    g_car->pCarController = NULL;
    car_set_control_mode(g_car, eNO_CONTROL);
    step("again", 1);

    printf("== dtor nulldriver 0\n");
    d = g_car->pCarDriver;
    v_i(d, d->_vtable, CARDRIVER_VT_DTOR, 0);
    printf("drv vt=%08x\n", (unsigned)d->_vtable);
    v_i(d, d->_vtable, CARDRIVER_VT_DTOR, 1);
    g_car->pCarController->Driver = NULL;
    car_set_control_mode(g_car, eNO_CONTROL);
    step("again", 1);

    printf("== dtor nullcontroller fdrv\n");
    c = g_car->pCarController;
    c->Driver = new_fake_driver();
    v_i(c, c->_vtable, CARCONTROLLER_VT_DTOR, 1);
    g_car->pCarController = NULL;
    car_set_control_mode(g_car, eNO_CONTROL);
    step("again", 1);

    printf("== carcontroller\n");
    cc = malloc(sizeof(CarController));
    memset(cc, 0xa5, sizeof(CarController));
    reg_add("cc", cc, sizeof(CarController), &pct_CarController);
    carcontroller_init(cc, g_car);
    cc->Driver = new_fake_driver();
    g_full = 1;
    dump_CarController("cc", cc);
    g_full = 0;
    v_p(cc, cc->_vtable, CARCONTROLLER_VT_DO_SNAPSHOT, (char *)g_cti + 40);
    v_v(cc, cc->_vtable, CARCONTROLLER_VT_DEBUG_DISPLAY);
    v_i(cc, cc->_vtable, CARCONTROLLER_VT_DTOR, 0);
    printf("cc vt=%08x\n", (unsigned)cc->_vtable);
    v_i(cc, cc->_vtable, CARCONTROLLER_VT_DTOR, 1);
    say_pools();
}

int main(void)
{
    int i;

    // Generated for its field table, which types the labels; the dump
    // prints a NullController as the CarController it is.
    (void)dump_NullController;

    setvbuf(stdout, NULL, _IONBF, 0);
    bSlotPoolManagerInit();
    vt_reset();
    physicssystem_install_vtables();
    physcomp_install_vtables();
    physicscar_install_vtables();
    mellowmover_install_vtables();
    nullmover_install_vtables();
    carcontroller_install_vtables();
    cardriver_install_vtables();
    install_fakes();
    wheel_install_seams();
    rigidbody_static_init();
    wheel_static_init();
    aerodynamics_static_init();
    physicscar_static_init();
    car_static_init();
    mellowmover_static_init();
    InitPhysics(8);
    for (i = 0; i < 10; i++)
        pool_free0[i] = bCountFreeSlots(*pools[i]);

    bSetTickerSource(scripted_tick);
    build_terrain();
    gTerrainTypeInfoTable = g_terrain;
    gTopologyGetElevationFn = fake_elevation;
    gTerrainRoadNoiseFn = fake_road_noise;
    gWheelTopologyOfCarStateFn = topology_of;
    gWheelMaybeMakeSkidsFn = fake_skids;
    pCurrentRace = (Race *)(void *)g_race;
    g_race[0] = 4;
    UseNewSuspensionCalibration = 1;
    gUglyTimestepHack = 1.0f;
    bSetMemoryHooks(hook_malloc, hook_free);

    s_tables();
    s_setup();
    s_move_walk();
    s_ctrl_walk();
    s_ctrl_under();
    s_stpm();
    s_ccb();
    s_friction();
    s_nullmover();
    s_nullcontroller();
    s_nulldriver();
    s_dtors();
    return 0;
}
