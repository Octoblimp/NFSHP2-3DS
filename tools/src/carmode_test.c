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
#include "beltmover.h"
#include "car.h"
#include "cardamage.h"
#include "collision.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "difficultyinfo.h"
#include "engine.h"
#include "p32.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "player.h"
#include "race.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "replay.h"
#include "terraintype.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"
#include "world.h"

// The clock object's globals that the linked files read. Defined here
// rather than linked from realtime.c, which would bring the joylog in
// behind it. The tick and the step are the image's 0; nothing this
// harness runs reads the frame count.
int32_t WorldTimer = 0;
int32_t WorldTimeFrames = 0;
float   WorldTimeElapsed = 0.0f;
// FinishMovement's phase count: the disc's 100000 outside slice eleven.
int32_t WorldLoopCounter = 100000;

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

// The resets' fixtures: the replay and its four snapshots, a player, a
// route (only ever passed along), a route point and the position handed
// in. Set by s_reset; the labels name them from then on.
static ReplayManager    *g_rm;
static ReplaySnapshot    g_snaps[CM_NSNAPS];
static char              g_player[16];
static char              g_route[16];
static TrackRoutePoint   g_rpt;
static bVector3          g_vec;
static uint32_t          g_track[CM_N(cm_track)];
static ReplayManager     g_rm_store;

// The step's: an animated driver and an editor object that are only ever
// labels, the car's player and the two by number, whose cars are car3
// (a blank one) and car2, and the three cars' RacingCars. Set by s_move.
static char              g_adrv[CM_ADRV_SIZE];
static char              g_caff[16];
static struct Player     g_plc, g_pl[2];
static struct RacingCar  g_rc[3];
static Car              *g_car3;
static int               g_nmove;

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
        ADD("tc", &g_car->TheTopologyCoordinate, sizeof(TopologyCoordinate),
            NULL);
        ADD("tpc", &g_car->TheTrackPathCoordinate,
            sizeof(TrackPathCoordinate), NULL);
        ADD("car", g_car, sizeof(Car), NULL);
        ADD("car2", g_car2, sizeof(Car), NULL);
        ADD("ccb", g_ccb, sizeof(CarCollisionBody), NULL);
        ADD("ccb2", g_ccb2, sizeof(CarCollisionBody), NULL);
        ADD("cti", g_cti, 1368, NULL);
        ADD("topo", g_topo, sizeof g_topo, NULL);
        ADD("di", g_di, sizeof(DriverInfo), NULL);
        ADD("tgt", g_tgt, sizeof(DriveTarget), NULL);
        if (g_rm != NULL) {
            static const char *const snap_name[CM_NSNAPS] = {
                "snap0", "snap1", "snap2", "snap3", "snap4",
            };
            ADD("rm", g_rm, sizeof(ReplayManager), NULL);
            for (i = 0; i < CM_NSNAPS; i++)
                ADD(snap_name[i], &g_snaps[i], sizeof(ReplaySnapshot), NULL);
            ADD("player", g_player, sizeof g_player, NULL);
            ADD("route", g_route, sizeof g_route, NULL);
            ADD("rpt", &g_rpt, sizeof g_rpt, NULL);
            ADD("pos", &g_vec, sizeof g_vec, NULL);
        }
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

// 1 while the track path loads: its QuickSplines' blocks are neither logged
// nor registered, on either side.
static int g_quiet;

static void *hook_malloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    const PcType *t = NULL;
    int shown = size;
    char nm[40];

    if (p == NULL)
        abort();
    if (g_quiet) {
        memset(p, 0, (size_t)size);
        return p;
    }
    memset(p, 0xa5, (size_t)size);
    // The six records the port has are its own size; the log shows the
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
    } else if (strcmp(name, "BeltMover") == 0
               && size == (int)sizeof(BeltMover)) {
        // Ported too (11e-6), and a stand-in here like RealController.
        shown = CM_IMG_BELTMOVER;
    } else if (strcmp(name, "AIDriver") == 0
               && size == (int)sizeof(AIDriver)) {
        // Ported (11f-2): retail's 736, the demo's 720, which this runs.
        shown = CM_IMG_AIDRIVER;
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
    if (normalOut != NULL) {
        normalOut->x = fb(CM_NORMAL_X);
        normalOut->y = fb(CM_NORMAL_Y);
        normalOut->z = fb(CM_NORMAL_Z);
        normalOut->pad = 0.0f;
    }
    if (terrainOut != NULL)
        *terrainOut = ((int32_t)(pos->x * 0.5f)) & 3;
    return el;
}

// The topology cartrack.c and carreset.c call, which track.c has and this
// harness does not link: the same plane, and a clear that logs.
float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    (void)found;
    return fake_elevation(tc, pt, terrain, normal);
}

void topology_clear_interest_bbox(TopologyCoordinate *tc)
{
    printf("clearbbox tc=%s\n", label(tc));
}

// cartrack.c's BeginMovement calls these two. Nothing here runs it --
// track_check does, over the real topology -- so reaching one is a
// harness bug.
void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    (void)tc; (void)pos; (void)r; (void)vel;
    printf("set_interest_bbox3 reached\n");
    abort();
}

// FinishMovement's topology test: the answers slice eleven's case scripts,
// in order. Reaching it with none left is a harness bug.
static int32_t g_fm_topo[2];
static int     g_fm_ntopo;

int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy)
{
    int32_t r;

    if (g_fm_ntopo == 0) {
        printf("has_topology reached with no answer scripted\n");
        abort();
    }
    r = g_fm_topo[0];
    g_fm_topo[0] = g_fm_topo[1];
    g_fm_ntopo--;
    printf("hastopo tc=%s xy=%08x %08x -> %d\n", label(tc), bf(xy->x),
           bf(xy->y), (int)r);
    return r;
}

// collisionbody.c's TrackPolygonCollisionBody wants the tree; carmode
// links collisionbody.c for the car's body, and never makes a polygon's.
TopologyTree TheTopologyTree;

TrackPolygon *topotree_assign(TopologyTree *t, TopologyTreePolygon *p)
{
    (void)t; (void)p;
    printf("topotree_assign reached\n");
    abort();
}

void topotree_unassign(TopologyTree *t, TrackPolygon *tp)
{
    (void)t; (void)tp;
    printf("topotree_unassign reached\n");
    abort();
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

// The three the resets reach.
static void fake_setroute(int k, void *self, TrackRoute *route,
                          TrackRoutePoint *point)
{
    printf("setroute %s this=%s route=%s point=%s\n", ctrl_cls[k],
           label(self), label(route), label(point));
}

static void fake_findwhere(int k, void *self)
{
    printf("findwhere %s this=%s\n", ctrl_cls[k], label(self));
}

static void fake_justreset(int k, void *self)
{
    printf("justreset %s this=%s\n", ctrl_cls[k], label(self));
}

// The step's: each mover's Move, which answers 0.5, 0.75, ... in turn, and
// the route and point a controller hands Move's reset.
static float fake_move(int k, void *self, float dt)
{
    float r = fb(CM_MOVE_RET0) + 0.25f * (float)g_nmove++;

    printf("mover-move %s this=%s dt=%08x -> %08x\n", mover_cls[k],
           label(self), bf(dt), bf(r));
    return r;
}

static TrackRoute *fake_getroute(int k, void *self)
{
    printf("getroute %s this=%s\n", ctrl_cls[k], label(self));
    return (TrackRoute *)(void *)g_route;
}

static TrackRoutePoint *fake_getpoint(int k, void *self)
{
    printf("getpoint %s this=%s\n", ctrl_cls[k], label(self));
    return &g_rpt;
}

#define FAKE_MOVER(k, cls)                                                  \
    static void fake_##cls##_dtor(void *s, int32_t f)                       \
    { fake_dtor(#cls, s, f); }                                              \
    static CarMover *fake_##cls##_ctor(void *m, Car *c)                     \
    { return fake_mover_ctor(k, m, c); }                                    \
    static float fake_##cls##_move(void *s, float dt)                       \
    { return fake_move(k, s, dt); }
#define FAKE_CTRL(k, cls)                                                   \
    static void fake_##cls##_dtor(void *s, int32_t f)                       \
    { fake_dtor(#cls, s, f); }                                              \
    static void fake_##cls##_stpm(void *s, Car *o)                          \
    { fake_stpm(k, s, o); }                                                 \
    static void fake_##cls##_setroute(void *s, TrackRoute *r,               \
                                      TrackRoutePoint *p)                   \
    { fake_setroute(k, s, r, p); }                                          \
    static void fake_##cls##_findwhere(void *s)                             \
    { fake_findwhere(k, s); }                                               \
    static void fake_##cls##_justreset(void *s)                             \
    { fake_justreset(k, s); }                                               \
    static TrackRoute *fake_##cls##_getroute(void *s)                       \
    { return fake_getroute(k, s); }                                         \
    static TrackRoutePoint *fake_##cls##_getpoint(void *s)                  \
    { return fake_getpoint(k, s); }                                         \
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

static void fdrv_lowgear(void *self)
{
    printf("lowgear fdrv this=%s\n", label(self));
}

#define E(f) { 0, 0, (VtFn)(f) }
#define N    { 0, 0, NULL }

// Slots 8 and 16, the destructor and the step's Move.
static const VtEntry fake_mover_vt[4][3] = {
    { N, E(fake_TrafficCar_dtor), E(fake_TrafficCar_move) },
    { N, E(fake_DeliveryMover_dtor), E(fake_DeliveryMover_move) },
    { N, E(fake_CopMover_dtor), E(fake_CopMover_move) },
    { N, E(fake_BeltMover_dtor), E(fake_BeltMover_move) },
};

// Slots 8 and 88, the resets' 40, 72 and 80, and the step's 48 and 56;
// nothing the methods do reaches the rest.
#define CTRL_VT(cls)                                                        \
    { N, E(fake_##cls##_dtor), N, N, N, E(fake_##cls##_setroute),           \
      E(fake_##cls##_getroute), E(fake_##cls##_getpoint), N,                \
      E(fake_##cls##_findwhere), E(fake_##cls##_justreset),                 \
      E(fake_##cls##_stpm) }
static const VtEntry fake_ctrl_vt[4][12] = {
    CTRL_VT(RealController),
    CTRL_VT(AIDriver),
    CTRL_VT(TrafficDriver),
    CTRL_VT(CopDriver),
};

static const VtEntry fake_driver_vt[7] = {
    N, E(fdrv_dtor), N, E(fdrv_snapshot), N, N, E(fdrv_lowgear),
};

#undef CTRL_VT
#undef E
#undef N

static void install_fakes(void)
{
    int k;
    for (k = 0; k < 4; k++) {
        vt_install(fake_vt(0, k), fake_mover_vt[k], 3);
        vt_install(fake_vt(1, k), fake_ctrl_vt[k], 12);
    }
    vt_install(CM_FAKE_VT_DRIVER, fake_driver_vt, 7);

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

// ------------------------------------------------------------ the resets

static void reset_setup(void)
{
    uint32_t *head;
    uint32_t ring[CM_NSNAPS + 1];
    int i;

    printf("== reset setup\n");
    memcpy(g_track, cm_track, sizeof g_track);
    g_quiet = 1;
    i = loader_track_path((uint8_t *)g_track);
    g_quiet = 0;
    printf("loader -> %d\n", i);
    WorldTimer = CM_WORLD_TIMER;

    g_rm = &g_rm_store;
    g_rm->FreeReplaySnapshotList[0] = p32_of(g_rm->FreeReplaySnapshotList);
    g_rm->FreeReplaySnapshotList[1] = p32_of(g_rm->FreeReplaySnapshotList);
    head = g_rm->ReplaySnapshotList;
    for (i = 0; i < CM_NSNAPS; i++) {
        snprintf(g_snaps[i].Name, sizeof g_snaps[i].Name, "%s",
                 cm_snap_name[i]);
        g_snaps[i].TotalInterestingValue = fb(cm_snap_tiv[i]);
    }
    ring[0] = p32_of(head);
    for (i = 0; i < CM_NSNAPS; i++)
        ring[1 + i] = p32_of(&g_snaps[i]);
    for (i = 0; i <= CM_NSNAPS; i++) {
        uint32_t *node = p32_ptr(ring[i]);
        node[0] = ring[(i + 1) % (CM_NSNAPS + 1)];
        node[1] = ring[(i + CM_NSNAPS) % (CM_NSNAPS + 1)];
    }
    memcpy(&g_rpt, cm_rpt, sizeof cm_rpt);
}

static void reset_prep(int ctrl, int move, int player)
{
    if ((int)g_car->TheControlMode != ctrl)
        car_set_control_mode(g_car, (ControlMode)ctrl);
    car_set_movement_mode(g_car, (MovementMode)move);
    g_car->pPlayer = player != 0 && player != 4
                         ? (Player *)(void *)g_player : NULL;
    pReplayManager = player == 3 ? NULL : g_rm;
    g_rm->CapturingFlag = player == 2 || player == 4;
    g_car->BlinkTimer = CM_BLINK0_TIMER;
    g_car->BlinkDuration = fb(CM_BLINK0_DURATION);
}

static void reset_dump(void)
{
    const TrackPathCoordinate *t = &g_car->TheTrackPathCoordinate;
    int i;

    step("after", 0);
    printf("tpc pos=%08x %08x pt=%d param=%08x ratio=%08x dist=%08x "
           "dir=%08x %08x\n", bf(t->Position.x), bf(t->Position.y),
           t->pTrackPoint != NULL
               ? (int)(t->pTrackPoint - TheTrackPathManager.pPoints) : -1,
           bf(t->SplineParam), bf(t->RatioAroundTrack),
           bf(t->DistanceAroundTrack), bf(t->PathDirection.x),
           bf(t->PathDirection.y));
    printf("blink timer=%d duration=%08x\n", (int)g_car->BlinkTimer,
           bf(g_car->BlinkDuration));
    printf("replay tiv=");
    for (i = 0; i < CM_NSNAPS; i++)
        printf("%s%08x", i ? " " : "", bf(g_snaps[i].TotalInterestingValue));
    printf("\n");
}

static void s_reset(void)
{
    int i;

    reset_setup();
    for (i = 0; i < CM_N(cm_resets); i++) {
        const CmReset *r = &cm_resets[i];
        static const char *const kind[3] = { "pos", "core", "debug" };

        printf("== reset %d %s\n", i, kind[r->kind]);
        reset_prep(r->ctrl, r->move, r->player);
        g_vec.x = fb(r->pos[0]);
        g_vec.y = fb(r->pos[1]);
        g_vec.z = fb(r->pos[2]);
        g_vec.pad = fb(r->pos[3]);
        if (r->kind == 0)
            car_reset_to_position(g_car, &g_vec, fb(r->speed),
                                  (uint16_t)r->angle);
        else if (r->kind == 1)
            car_reset_core(g_car, &g_vec, fb(r->speed), (uint16_t)r->angle);
        else
            car_debug_set_position(g_car, &g_vec, fb(r->speed),
                                   (uint16_t)r->angle);
        reset_dump();
    }
    for (i = 0; i < CM_N(cm_route_resets); i++) {
        const CmRouteReset *r = &cm_route_resets[i];

        printf("== reset route %d\n", i);
        reset_prep(r->ctrl, r->move, r->player);
        car_reset_to_route_point(g_car,
                                 r->route ? (TrackRoute *)(void *)g_route
                                          : NULL,
                                 r->point ? &g_rpt : NULL, fb(r->speed),
                                 r->blink, fb(r->dir));
        reset_dump();
    }
    car_set_control_mode(g_car, eNO_CONTROL);
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

// ------------------------------------------------------------ the step

static void adrv_begin_gear(AnimatedDriver *d)
{
    printf("adrv begin-gear this=%s\n", label(d));
}

static void adrv_begin_back(AnimatedDriver *d)
{
    printf("adrv begin-back this=%s\n", label(d));
}

static void adrv_end_back(AnimatedDriver *d)
{
    printf("adrv end-back this=%s\n", label(d));
}

static void fake_esp(void *obj, bVector3 *pos)
{
    printf("esp obj=%s pos=%s\n", label(obj), label(pos));
}

static void move_setup(void)
{
    int i;

    printf("== move setup\n");
    reg_add("adrv", g_adrv, sizeof g_adrv, NULL);
    reg_add("caff", g_caff, sizeof g_caff, NULL);
    g_car3 = calloc(1, sizeof(Car));
    g_plc.MyCar = g_car;
    g_pl[0].MyCar = g_car3;
    g_pl[1].MyCar = g_car2;
    for (i = 0; i < 2; i++) {
        g_pl[i].PlayerNumber = i;
        PlayerPlayersByNumber[i] = &g_pl[i];
    }
    g_car->pRacingCar = &g_rc[0];
    g_car3->pRacingCar = &g_rc[1];
    g_car2->pRacingCar = &g_rc[2];
    printf("tracklength=%08x\n", bf(TheTrackPathManager.TrackLength));
}

// Only the catchup's knees: the harness loads retail's chunk, the image the
// demo's, and the knees are the same in both. difficulty_check has the rest.
static void diff_dump(void)
{
    const uint32_t *w =
        (const uint32_t *)(const void *)TheDifficultyInfo.TwoPlayerCatchup;
    int j;

    printf("diff knees =");
    for (j = 0; j < 8; j++)
        printf(" %08x", (unsigned)w[j]);
    printf("\n");
}

static void move_case(int i, const CmMove *m)
{
    CarState *cs = &g_car->State;
    float r;
    int k;

    printf("== move %d\n", i);
    if ((int)g_car->TheControlMode != m->ctl)
        car_set_control_mode(g_car, (ControlMode)m->ctl);
    if ((int)g_car->TheMovementMode != m->move)
        car_set_movement_mode(g_car, (MovementMode)m->move);
    cs->CurrentGear = m->gear;
    g_car->DispGear = m->disp;
    g_car->pAnimatedDriver = m->adrv ? (AnimatedDriver *)(void *)g_adrv
                                     : NULL;
    g_car->ResetMe = m->reset;
    g_car->BlinkTimer = (int32_t)m->bt;
    g_car->BlinkDuration = fb(m->bd);
    g_ccb->LastPenetrationTime.PackedTime = m->pen;
    g_car->pCaffeineObj = m->caff ? g_caff : NULL;
    g_car->pPlayer = m->player != CM_NO_PLAYER ? &g_plc : NULL;
    g_plc.PlayerNumber = m->player;
    RaceParametersBoost = m->boost;
    PlayerNumPlayers = m->np;
    for (k = 0; k < 3; k++)
        g_rc[k].CurrentLapNumberExact = fb(m->laps[k]);
    cs->BoostFactor = fb(CM_BOOST_MARK);
    WorldTimer = (int32_t)m->now;
    r = car_move(g_car, fb(CM_MOVE_DT));
    printf("moved -> %08x gear=%d disp=%d resetme=%d blink=%d/%08x "
           "boost=%08x\n", bf(r), (int)cs->CurrentGear, (int)g_car->DispGear,
           (int)g_car->ResetMe, (int)g_car->BlinkTimer,
           bf(g_car->BlinkDuration), bf(cs->BoostFactor));
    if (m->full)
        step("after", 0);
}

static void s_move(void)
{
    uint8_t good[CM_N(cm_diff)], bad[CM_N(cm_diff)];
    int i;

    move_setup();
    memcpy(good, cm_diff, sizeof good);
    memcpy(bad, cm_diff, sizeof bad);
    bad[0] ^= 1;
    printf("== difficulty\n");
    printf("unload %d %d\n", unloader_difficulty_info(bad),
           unloader_difficulty_info(good));
    printf("load bad -> %d\n", loader_difficulty_info(bad));
    diff_dump();
    for (i = 0; i < CM_N(cm_catchup); i++)
        move_case(-1 - i, &cm_catchup[i]);
    printf("load -> %d\n", loader_difficulty_info(good));
    diff_dump();
    for (i = 0; i < CM_N(cm_moves); i++)
        move_case(i, &cm_moves[i]);
    car_set_control_mode(g_car, eNO_CONTROL);
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

// ------------------------------------------------------------ slice nine

static float   g_dist;
static char    g_snd[CM_SND_SIZE];
static char    g_copmgr[CM_COPMGR_SIZE];
static char    g_dpos[8];
static int32_t g_pursued;
static int     g_nline;

// RealDriver::ForceEBrakeStop is realdriver.c's, which is not linked here;
// the model stubs the image's, and each side logs the call.
void realdriver_force_ebrake_stop(RealDriver *d, int32_t on)
{
    printf("ebrake drv=%s on=%d\n", label(d), (int)on);
}

static void fake_effect(Car *c, CarEffect fx, float scale, int32_t where,
                        bVector3 *pos)
{
    printf("effect car=%s fx=%d scale=%08x where=%08x pos=%s", label(c),
           (int)fx, bf(scale), (unsigned)where, label(pos));
    if (pos != NULL)
        printf(" at=%08x %08x %08x %08x", bf(pos->x), bf(pos->y),
               bf(pos->z), bf(pos->pad));
    printf("\n");
}

static void fake_snd_blow(BaseCarSound *snd)
{
    printf("sound blowout %s\n", label(snd));
}

static int32_t fake_pursued(tCopManager *m, Car *c)
{
    printf("pursued mgr=%s car=%s -> %d\n", label(m), label(c),
           (int)g_pursued);
    return g_pursued;
}

static float fake_line_speed(CarController *ctl)
{
    float r = fb(CM_LINE_SPEED0) + 0.5f * (float)g_nline++;

    printf("linespeed ctl=%s -> %08x\n", label(ctl), bf(r));
    return r;
}

static void fake_setdest(CarMover *m, bVector2 *pos, uint16_t angle,
                         float speed, float time)
{
    printf("setdest mover=%s pos=%s angle=%d speed=%08x time=%08x\n",
           label(m), label(pos), (int)angle, bf(speed), bf(time));
}

static void blown(const char *what)
{
    printf("%s bits=%02x num=%d timer=%08x\n", what,
           (unsigned)g_car->BlownTireBits, (int)g_car->NumBlownTires,
           bf(g_car->fBlownTireControllerRumbleTimer));
}

static void set_blown(int32_t bits, int32_t num)
{
    g_car->BlownTireBits = (uint8_t)bits;
    g_car->NumBlownTires = (uint8_t)num;
    g_car->fBlownTireControllerRumbleTimer = fb(CM_RACE_TIMER0);
}

static void s_race(void)
{
    DriverType dtype = g_di->TheDriverType;
    uint32_t mark = CM_DIST_MARK;
    float r;
    int i;

    printf("== race setup\n");
    reg_add("dist", &g_dist, sizeof g_dist, NULL);
    reg_add("snd", g_snd, sizeof g_snd, NULL);
    reg_add("copmgr", g_copmgr, sizeof g_copmgr, NULL);
    reg_add("dpos", g_dpos, sizeof g_dpos, NULL);
    for (i = 0; i < 2; i++) {
        printf("== dist %d\n", i);
        memcpy(&g_dist, &mark, 4);
        r = car_get_distance_and_speed(&g_dist, i ? g_car2 : g_car,
                                       i ? g_car : g_car2);
        printf("dist -> %08x speed=%08x\n", bf(r), bf(g_dist));
    }
    for (i = 0; i < CM_N(cm_fix); i++) {
        printf("== fix %d\n", i);
        if ((int32_t)g_car->TheControlMode != cm_fix[i])
            car_set_control_mode(g_car, (ControlMode)cm_fix[i]);
        set_blown(0x0b, 3);
        car_fix_blown_tires(g_car);
        blown("fixed");
    }
    car_set_control_mode(g_car, eNO_CONTROL);
    for (i = 0; i < CM_N(cm_blow); i++) {
        const CmBlow *b = &cm_blow[i];
        printf("== blow %d\n", i);
        set_blown(b->bits, b->num);
        g_car->pBaseCarSound = b->snd ? (BaseCarSound *)(void *)g_snd : NULL;
        car_trigger_tire_blow_out(g_car, b->tires);
        blown("blown");
    }
    g_car->pBaseCarSound = NULL;
    set_blown(0, 0);
    g_car->fBlownTireControllerRumbleTimer = 0.0f;
    for (i = 0; i < CM_N(cm_later); i++) {
        const CmLater *l = &cm_later[i];
        printf("== later %d\n", i);
        RaceParametersBeACop = l->beacop;
        RaceParametersMaxCops = l->maxcops;
        g_di->TheDriverType = l->dtype;
        g_pursued = l->pursued;
        pCopManager = l->mgr ? (tCopManager *)(void *)g_copmgr : NULL;
        g_car->ResetMe = CM_RESET_MARK;
        car_please_reset_me_later(g_car);
        printf("later resetme=%d\n", (int)g_car->ResetMe);
    }
    RaceParametersBeACop = 0;
    RaceParametersMaxCops = 0;
    g_di->TheDriverType = dtype;
    pCopManager = NULL;
    g_car->ResetMe = 0;
    for (i = 0; i < CM_N(cm_line); i++) {
        printf("== line %d\n", i);
        if ((int32_t)g_car->TheControlMode != cm_line[i])
            car_set_control_mode(g_car, (ControlMode)cm_line[i]);
        r = car_get_driving_line_speed(g_car);
        printf("line -> %08x\n", bf(r));
    }
    car_set_control_mode(g_car, eNO_CONTROL);
    for (i = 0; i < CM_N(cm_deliver); i++) {
        const CmDeliver *d = &cm_deliver[i];
        printf("== deliver %d\n", i);
        if ((int32_t)g_car->TheMovementMode != d->from)
            car_set_movement_mode(g_car, (MovementMode)d->from);
        car_deliver_me_from_evil(g_car, (bVector2 *)(void *)g_dpos,
                                 (uint16_t)d->angle, fb(d->speed),
                                 fb(d->time));
        printf("delivered move=%d mover=%s\n", (int)g_car->TheMovementMode,
               label(g_car->pCarMover));
    }
    car_set_movement_mode(g_car, eNO_MOVEMENT);
}

// ------------------------------------------------------------ slice eleven

// FinishMovement's player: only the zone, the wrong way flag and the jump
// cam's height are read, and the four Player calls are stand-ins that log.
// ClearZone empties the zone; RequestZone answers as the case says, and
// moves the player into the zone when it says yes.
static struct Player g_fmplayer;
static int32_t       g_fm_jc, g_fm_rz;

static void fake_clear_zone(Player *p, int32_t sound)
{
    printf("clearzone p=%s sound=%d zone=%d\n", label(p), (int)sound,
           (int)p->nZoneCurrent);
    p->nZoneCurrent = 0;
}

static int32_t fake_request_zone(Player *p, int32_t zone, int32_t force,
                                 int32_t b2, int32_t b3)
{
    printf("requestzone p=%s zone=%d force=%d b2=%d b3=%d -> %d\n", label(p),
           (int)zone, (int)force, (int)b2, (int)b3, (int)g_fm_rz);
    if (g_fm_rz)
        p->nZoneCurrent = zone;
    return g_fm_rz;
}

static int32_t fake_jump_cam(Player *p)
{
    printf("jumpcam p=%s -> %d\n", label(p), (int)g_fm_jc);
    return g_fm_jc;
}

static void fake_clean_up(Player *p)
{
    printf("cleanupjumpcam p=%s\n", label(p));
}

static void put4(bVector3 *v, const uint32_t w[4])
{
    v->x = fb(w[0]);
    v->y = fb(w[1]);
    v->z = fb(w[2]);
    v->pad = fb(w[3]);
}

static void identity(bMatrix4 *m)
{
    float *f = (float *)(void *)m;
    int k;
    for (k = 0; k < 16; k++)
        f[k] = k % 5 == 0 ? 1.0f : 0.0f;
}

static void s_finish(void)
{
    Car *c = g_car;
    CarState *cs = &c->State;
    TrackPathCoordinate *t = &c->TheTrackPathCoordinate;
    CollisionBody *self = &g_ccb->Dynamic.Body;
    CollisionBodyWitness *const end =
        (CollisionBodyWitness *)(void *)&CollisionBodyWitnessList;
    Car *others[CM_FM_NCARS - 1];
    World *world;
    Collision *col;
    CollisionBodyWitness *wit;
    CollisionBody *body;
    CollisionBodyWitnessNode wlist0;
    int8_t type0[2];
    MovementMode mode0;
    Player *player0;
    int paths0;
    ReplayManager *rm0;
    int n, i, k;

    printf("== finish setup\n");
    car_set_control_mode(c, eNO_CONTROL);
    reg_add("fmplayer", &g_fmplayer, sizeof g_fmplayer, NULL);
    world = calloc(1, sizeof(World));
    reg_add("world", world, sizeof(World), NULL);
    for (i = 0; i < CM_FM_NCARS - 1; i++) {
        char nm[16];
        snprintf(nm, sizeof nm, "other%d", i);
        others[i] = calloc(1, sizeof(Car));
        reg_add(nm, others[i], sizeof(Car), NULL);
        world->CarTable[i + 1] = others[i];
    }
    world->CarTable[0] = c;
    col = calloc(1, sizeof(Collision));
    reg_add("col", col, sizeof(Collision), NULL);
    wit = calloc(1, sizeof(CollisionBodyWitness));
    reg_add("wit", wit, sizeof(CollisionBodyWitness), NULL);
    body = calloc(1, sizeof(CollisionBody));
    reg_add("obody", body, sizeof(CollisionBody), NULL);
    col->pWitness = wit;
    wlist0 = CollisionBodyWitnessList;
    type0[0] = g_ccb->Dynamic.Body.Type;
    type0[1] = g_ccb2->Dynamic.Body.Type;
    mode0 = c->TheMovementMode;
    player0 = c->pPlayer;
    paths0 = TheTrackPathManager.NumPaths;
    rm0 = pReplayManager;
    identity(&cs->BodyMatrix);
    identity(&cs->WheelMatrix[0]);
    g_rm->CapturingFlag = 1;
    pCurrentWorld = world;
    for (n = 0; n < CM_N(cm_fm); n++) {
        const CmFm *x = &cm_fm[n];
        const TrackPathPoint *pt;

        printf("== finish %d\n", n);
        put4(&cs->Acceleration, cm_fm_acc);
        put4(&cs->AngularAcceleration, cm_fm_acc);
        put4(&cs->Velocity, x->vel);
        put4(&c->vOldVel, cm_fm_oldvel);
        put4(&cs->AngularVelocity, cm_fm_ang);
        put4(&c->vOldAngVel, cm_fm_oldang);
        put4(&cs->Position, x->pos);
        cs->Odometer = fb(x->odo);
        cs->VelocityMagnitude = fb(x->vmag);
        cs->nWheelsTouchingGround = x->wheels;
        cs->ForwardSpeed = fb(x->fwd);
        cs->Angle = (uint16_t)x->angle;
        t->Position.x = fb(x->pos[0]);
        t->Position.y = fb(x->pos[1]);
        t->pTrackPoint = x->tp < 0 ? NULL : TheTrackPathManager.pPoints + x->tp;
        TheTrackPathManager.NumPaths = x->nopaths ? 0 : paths0;
        c->TheMovementMode = (MovementMode)x->mode;
        c->ResetMe = 0;
        c->ForceHeadlightsOn = x->lights;
        c->HeadlightsState = 0;
        WorldLoopCounter = x->loop;
        WorldTimer = x->now;
        BoringAIForCameraTuningOn = x->boring;
        g_DisableAutoReplay = x->disable;
        c->pPlayer = x->player ? &g_fmplayer : NULL;
        g_fmplayer.nZoneCurrent = x->zone;
        g_fmplayer.bWrongWay = x->wrong;
        g_fmplayer.EyeVerts[2].z = fb(x->eye);
        c->AirTimeSwitch = fb(x->ats);
        g_fm_ntopo = x->ntopo;
        g_fm_topo[0] = x->topo[0];
        g_fm_topo[1] = x->topo[1];
        g_fm_jc = x->jc;
        g_fm_rz = x->rz;
        world->AICarPos = x->ai;
        world->CopCarPos = x->cop;
        for (i = 0; i < CM_FM_NCARS - 1; i++) {
            others[i]->State.Position.x = fb(x->table[i][0]);
            others[i]->State.Position.y = fb(x->table[i][1]);
            others[i]->State.Position.z = fb(x->table[i][2]);
        }
        if (x->col) {
            CollisionBody *other = x->iscar ? &g_ccb2->Dynamic.Body : body;
            other->Type = (int8_t)x->type;
            self->Type = (int8_t)x->selftype;
            self->NumCollisions = 1;
            wit->pBody1 = x->order == 0 ? self : other;
            wit->pBody2 = x->order == 0 ? other : self;
            wit->pCollision = x->has ? col : NULL;
            wit->Link.next = end;
            wit->Link.prev = end;
            CollisionBodyWitnessList.next = wit;
            CollisionBodyWitnessList.prev = wit;
            col->LastContactTime.PackedTime =
                (uint32_t)x->now - (uint32_t)x->ago;
        }
        pReplayManager = x->rm ? g_rm : NULL;
        for (i = 0; i < CM_NSNAPS; i++)
            g_snaps[i].TotalInterestingValue = 0.0f;
        car_finish_movement(c, fb(x->dt));
        if (g_fm_ntopo != 0) {
            printf("finish %d left HasTopology answers\n", n);
            abort();
        }
        CollisionBodyWitnessList = wlist0;
        g_ccb->Dynamic.Body.Type = type0[0];
        g_ccb2->Dynamic.Body.Type = type0[1];
        self->NumCollisions = 0;
        pt = t->pTrackPoint;
        printf("fm acc=%08x %08x %08x %08x ang=%08x %08x %08x %08x odo=%08x "
               "resetme=%d lights=%d\n",
               bf(cs->Acceleration.x), bf(cs->Acceleration.y),
               bf(cs->Acceleration.z), bf(cs->Acceleration.pad),
               bf(cs->AngularAcceleration.x), bf(cs->AngularAcceleration.y),
               bf(cs->AngularAcceleration.z),
               bf(cs->AngularAcceleration.pad), bf(cs->Odometer),
               (int)c->ResetMe, (int)c->HeadlightsState);
        printf("fm tpc=%08x %08x pt=%d zone=%d eye=%08x ats=%08x tiv=",
               bf(t->Position.x), bf(t->Position.y),
               pt == NULL ? -1 : (int)(pt - TheTrackPathManager.pPoints),
               (int)g_fmplayer.nZoneCurrent, bf(g_fmplayer.EyeVerts[2].z),
               bf(c->AirTimeSwitch));
        for (k = 0; k < CM_NSNAPS; k++)
            printf("%s%08x", k ? " " : "",
                   bf(g_snaps[k].TotalInterestingValue));
        printf("\n");
    }
    c->pPlayer = player0;
    c->TheMovementMode = mode0;
    c->ResetMe = 0;
    pCurrentWorld = NULL;
    WorldLoopCounter = CM_LOOP0;
    BoringAIForCameraTuningOn = 0;
    g_DisableAutoReplay = 0;
    pReplayManager = rm0;
    TheTrackPathManager.NumPaths = paths0;
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
    gAnimatedDriverBeginGearChangeFn = adrv_begin_gear;
    gAnimatedDriverBeginDrivingBackwardsFn = adrv_begin_back;
    gAnimatedDriverEndDrivingBackwardsFn = adrv_end_back;
    gEspSetObjectPositionFn = fake_esp;
    gCarTriggerEffectFn = fake_effect;
    gBaseCarSoundTriggerTireBlowOutFn = fake_snd_blow;
    gCopManagerIsBeingPursuedFn = fake_pursued;
    gAICarControllerGetCurrentDrivingLineSpeedFn = fake_line_speed;
    gDeliveryMoverSetDestinationFn = fake_setdest;
    gPlayerClearZoneFn = fake_clear_zone;
    gPlayerRequestZoneFn = fake_request_zone;
    gPlayerIsJumpCamAvailableFn = fake_jump_cam;
    gPlayerCleanUpJumpCamFn = fake_clean_up;
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
    s_reset();
    s_move();
    s_race();
    s_finish();
    return 0;
}
