// Transcript harness for mellowmover. Cross-checked by
// tools/mellowmover_check.py, which runs the same scenarios on the image in
// mipsemu and compares the two transcripts line for line.
//
// This file is not compiled alone. The checker prepends a generated prefix
// -- a dump function and a field table for every struct the mover owns,
// parsed out of the port's headers, and the inputs as bit patterns -- and
// compiles the two as one translation unit.
//
// The stand-ins are physicscar_test.c's and so are their twins in the
// model: the terrain plane, the road noise, the ticker that counts up 1000
// per read, the skid maker that only says it was asked, and the labels.

#ifndef MM_GENERATED
#error "mellowmover_test.c is built by tools/mellowmover_check.py, which prepends the generated dumps"
#endif

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "bticker.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "collisionsound.h"
#include "epositionmarker.h"
#include "p32.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "race.h"
#include "vtable.h"

// The clock object's globals that the linked files read. Defined here
// rather than linked from realtime.c, which would bring the joylog in
// behind it. The tick and the step are the image's 0; nothing this
// harness runs reads the frame count.
int32_t WorldTimer = 0;
int32_t WorldLoopCounter;   // realtime.c's too; ReplaySnapshot_Init reads it
int32_t WorldTimeFrames = 0;
float   WorldTimeElapsed = 0.0f;

// carrace.c's, which the harness does not link.
CarTriggerEffectFn gCarTriggerEffectFn;

// cardamage.c's write side calls these, as in physicscar_test.c; nothing
// this harness runs takes a hit, so each stops the run if reached.
static void unreached(const char *what)
{
    fprintf(stderr, "%s reached\n", what);
    exit(3);
}

ePositionMarker *eFindPositionMarker(uint32_t name_hash, uint32_t type_hash,
                                     ePositionMarker *prev)
{
    (void)name_hash; (void)type_hash; (void)prev;
    unreached("eFindPositionMarker");
    return NULL;
}

void collision_sound_play_glass(const bVector3 *pos)
{
    (void)pos;
    unreached("collision_sound_play_glass");
}

void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri)
{
    (void)ri;
    unreached("carrenderinfo_update_car_replacement_textures");
}

void emodel_set_environment_mapping(eModel *m, uint32_t hash, int32_t on)
{
    (void)m; (void)hash; (void)on;
    unreached("emodel_set_environment_mapping");
}

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

static MellowMover *g_mm;
static Car         *g_car;
static CarDriver   *g_drv;
static CarTypeInfo *g_cti;
static CarState    *g_cs2;       // a CarState of the mover's own, or NULL
static char         g_topo[16];   // the TopologyCoordinate the car carries
static int32_t      g_race[4];

typedef struct Obj {
    const char   *name;
    const void   *base;
    size_t        size;
    const PcType *t;
} Obj;

static const char *const wheel_name[4] = { "wheel0", "wheel1", "wheel2", "wheel3" };

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
    }
    ADD("cs2", g_cs2, sizeof(CarState), &pct_CarState);
    ADD("drv", g_drv, sizeof(CarDriver), NULL);
    ADD("cti", g_cti, 1368, NULL);
    ADD("topo", g_topo, sizeof g_topo, NULL);
    if (g_mm != NULL) {
        ADD("mm", g_mm, sizeof(MellowMover), &pct_MellowMover);
        ADD("mv", g_mm->pMellovator, sizeof(Mellovator), &pct_Mellovator);
        ADD("body", g_mm->pBody, sizeof(RigidBody), &pct_RigidBody);
        ADD("aero", g_mm->pAerodynamics, sizeof(Aerodynamics),
            &pct_Aerodynamics);
        for (i = 0; i < 4; i++)
            ADD(wheel_name[i], g_mm->pWheels[i], sizeof(Wheel), &pct_Wheel);
    }
#undef ADD
    return n;
}

static const char *label(const void *p)
{
    static char buf[8][96];
    static int k;
    char *s = buf[k++ & 7];
    Obj o[32];
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

static void hex4(const float *v)
{
    printf("%08x %08x %08x %08x", bf(v[0]), bf(v[1]), bf(v[2]), bf(v[3]));
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
    normalOut->x = fb(MM_NORMAL_X);
    normalOut->y = fb(MM_NORMAL_Y);
    normalOut->z = fb(MM_NORMAL_Z);
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
        g_terrain[i].StaticFrictionMultiplier  = fb(MM_TERRAIN[i][0]);
        g_terrain[i].DynamicFrictionMultiplier = fb(MM_TERRAIN[i][1]);
        g_terrain[i].RollingFrictionMultiplier = fb(MM_TERRAIN[i][2]);
    }
}

// ------------------------------------------------------------ the pools

static BSlotPool **const pools[9] = {
    &RigidBodySlotPool, &TwoWheelAckermanSteeringSlotPool, &WheelSlotPool,
    &EngineSlotPool, &DriveTrainSlotPool, &AerodynamicsSlotPool,
    &SuspensionSlotPool, &MellovatorSlotPool, &MellowMoverSlotPool,
};
static const char *const pool_name[9] = {
    "RigidBody", "Ackerman", "Wheel", "Engine", "DriveTrain", "Aerodynamics",
    "Suspension", "Mellovator", "MellowMover",
};
static int pool_free0[9];

static void say_pools(void)
{
    int i;
    printf("pools");
    for (i = 0; i < 9; i++)
        printf(" %s=%d", pool_name[i],
               pool_free0[i] - bCountFreeSlots(*pools[i]));
    printf("\n");
}

// ------------------------------------------------------------ the dump

static void say_globals(void)
{
    printf("globals ugly=%08x gpi=%08x maxi=%08x newcal=%d tick=%u\n",
           bf(gUglyTimestepHack), bf(gGroundPenaltyImpulse),
           bf(MaxiMellowTimeStep), (int)UseNewSuspensionCalibration,
           (unsigned)g_tick);
}

static void walk(void)
{
    const PhysicsSystem *sys = &g_mm->Vehicle;
    const PhysicsComponent *c;
    int n;

    printf("list fwd");
    n = 0;
    for (c = p32_ptr(sys->pNext); (const void *)c != (const void *)sys && n < 32;
         c = p32_ptr(c->pNext), n++)
        printf(" %s", label(c));
    printf("\n");
    printf("list back");
    n = 0;
    for (c = p32_ptr(sys->pPrev); (const void *)c != (const void *)sys && n < 32;
         c = p32_ptr(c->pPrev), n++)
        printf(" %s", label(c));
    printf("\n");
    pc_raw("mm.Vehicle", "Size", &sys->Size, 4);
}

static void dump_all(const char *tag)
{
    int i;
    printf("-- %s\n", tag);
    dump_MellowMover("mm", g_mm);
    dump_Mellovator("mv", g_mm->pMellovator);
    dump_RigidBody("body", g_mm->pBody);
    dump_Aerodynamics("aero", g_mm->pAerodynamics);
    for (i = 0; i < 4; i++)
        dump_Wheel(wheel_name[i], g_mm->pWheels[i]);
    dump_CarState("cs", &g_car->State);
    if (g_cs2 != NULL)
        dump_CarState("cs2", g_cs2);
    walk();
    say_globals();
}

// ------------------------------------------------------------ the mover

static void build(const MmScen *s)
{
    CarState *cs;
    int i, j;

    UseNewSuspensionCalibration = s->newcal;
    gUglyTimestepHack = 1.0f;
    g_tick = 0;
    g_cti = calloc(1, sizeof(CarTypeInfo));
    memcpy(g_cti, mm_cti[s->car], 1368);
    g_car = calloc(1, sizeof(Car));
    g_drv = calloc(1, sizeof(CarDriver));
    g_car->MyDriver = calloc(1, sizeof(DriverInfo));
    g_car->MyDriver->TheDriverType = s->dtype;
    g_car->DraftFactor = fb(s->draft);
    g_car->RenderingEnabled = (int8_t)s->render;

    cs = &g_car->State;
    cs->pCarInfo = (CarTypeInfoPrefix *)g_cti;
    cs->pTopologyCoordinate = (TopologyCoordinate *)g_topo;
    cs->Position.x = fb(s->pos[0]);
    cs->Position.y = fb(s->pos[1]);
    cs->Position.z = fb(s->pos[2]);
    cs->Velocity.x = fb(s->vel[0]);
    cs->Velocity.y = fb(s->vel[1]);
    cs->Velocity.z = fb(s->vel[2]);
    cs->AngularVelocity.x = fb(s->avel[0]);
    cs->AngularVelocity.y = fb(s->avel[1]);
    cs->AngularVelocity.z = fb(s->avel[2]);
    for (i = 0; i < 3; i++) {
        bVector4 *row = (i == 0) ? &cs->BodyMatrix.v0
                      : (i == 1) ? &cs->BodyMatrix.v1 : &cs->BodyMatrix.v2;
        float *r = &row->x;
        for (j = 0; j < 3; j++)
            r[j] = fb(s->mat[3 * i + j]);
    }
    cs->BodyMatrix.v3.w = 1.0f;
    for (i = 0; i < 4; i++) {
        cs->WheelAngle[i] = fb(s->wa);
        cs->WheelAngularVelocity[i] = fb(s->ww[i]);
        cs->WheelTouchingGround[i] = (int8_t)(i < s->ntouch);
    }
    cs->nWheelsTouchingGround = s->ntouch;
    cs->ForwardSpeed = fb(s->fwd);
    cs->DriverMode = s->dmode;
    cs->BoostFactor = fb(s->boostf);

    g_drv->Steering = (uint16_t)s->steer;
    g_drv->Throttle = fb(s->thr);
    g_drv->Brake = fb(s->brk);
    g_drv->EBrake = fb(s->ebrk);
    g_drv->DesiredGear = s->dgear;

    g_cs2 = NULL;
    if (s->apart) {
        g_cs2 = malloc(sizeof(CarState));
        memcpy(g_cs2, &g_car->State, sizeof(CarState));
        g_cs2->ForwardSpeed = fb(s->fwd2);
    }

    printf("== %s\n", s->name);
    g_mm = mellowmover_new();
    mellowmover_init(g_mm, g_car, g_cti, g_drv,
                     g_cs2 != NULL ? g_cs2 : &g_car->State);
    say_pools();
}

// Through the Mover's table, as Car does, or through the PhysicsVehicle's.
// Without the delete bit the slot goes back by hand.
static void teardown(int32_t flags, int vehicle)
{
    const VtEntry *e;
    MellowMover *mm = g_mm;

    if (!vehicle) {
        e = vt_slot(mm->Mover._vtable, CARMOVER_VT_DTOR);
        ((CarMoverDtorFn)e->fn)(vt_this(&mm->Mover, e), flags);
    } else {
        e = vt_slot(mm->Vehicle._vtable, PHYSICSSYSTEM_VT_DTOR);
        ((PhysicsDtorFn)e->fn)(vt_this(&mm->Vehicle, e), flags);
    }
    if (!(flags & 1)) {
        printf("dtor mover.vt=%08x vehicle.vt=%08x\n",
               (unsigned)mm->Mover._vtable, (unsigned)mm->Vehicle._vtable);
        mellowmover_delete(mm);
    }
    g_mm = NULL;
    say_pools();
    free(g_car->MyDriver);
    free(g_car);
    free(g_drv);
    free(g_cti);
    free(g_cs2);
    g_cs2 = NULL;
    g_car = NULL;
    g_drv = NULL;
    g_cti = NULL;
}

static void run_move(const MmScen *s)
{
    const VtEntry *e;
    float r;
    int n;
    char tag[32];

    build(s);
    dump_all("ctor");
    for (n = 0; n < s->steps; n++) {
        e = vt_slot(g_mm->Mover._vtable, CARMOVER_VT_MOVE);
        r = ((CarMoverMoveFn)e->fn)(vt_this(&g_mm->Mover, e), fb(s->dt));
        printf("-- move %d ret=%08x\n", n, bf(r));
        snprintf(tag, sizeof tag, "move %d", n);
        dump_all(tag);
    }
    teardown(1, 0);
}

// ------------------------------------------------------------ direct calls

static MmScen named(const char *name)
{
    MmScen s = mm_scen[0];
    s.name = name;
    return s;
}

static MmScen moving(const char *name)
{
    MmScen s = mm_scen[MM_MOVING_INDEX];
    s.name = name;
    return s;
}

// Through the Mellovator's own table, as the system calls it.
static const VtEntry *mv_slot(int slot)
{
    return vt_slot(g_mm->pMellovator->_vtable, slot);
}

static void mv_aux(void)
{
    const VtEntry *e = mv_slot(PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(g_mm->pMellovator, e));
}

static void s_static(void)
{
    const Graph *g[2] = { &MellowForceFeedbackGraph, &MellowJumpStabilization };
    const char *nm[2] = { "MellowForceFeedbackGraph", "MellowJumpStabilization" };
    int k, i;

    printf("== static\n");
    for (k = 0; k < 2; k++) {
        const bVector2 *pts = g[k]->pPoints;
        printf("%s %d", nm[k], (int)g[k]->NumPoints);
        for (i = 0; i < g[k]->NumPoints; i++)
            printf(" %08x %08x", bf(pts[i].x), bf(pts[i].y));
        printf("\n");
    }
    printf("MaxiMellowTimeStep %08x gGroundPenaltyImpulse %08x\n",
           bf(MaxiMellowTimeStep), bf(gGroundPenaltyImpulse));
}

static void s_tables(void)
{
    static const struct { const char *name; uint32_t vt; } t[3] = {
        { "Mellovator", MELLOVATOR_VTABLE },
        { "MellowMover", MELLOWMOVER_VTABLE },
        { "MellowMover$Vehicle", MELLOWMOVER_VEHICLE_VTABLE },
    };
    int i, j, n;

    printf("== tables\n");
    for (i = 0; i < 3; i++) {
        const VtEntry *tab = vt_table(t[i].vt, &n);
        printf("vt %s n=%d", t[i].name, n);
        for (j = 0; j < n; j++) {
            const VtEntry *e = &tab[j];
            if (e->delta != 0
                && e->delta == -(int)offsetof(MellowMover, Vehicle))
                printf(" mm/%s", e->fn ? "fn" : "null");
            else
                printf(" %d/%s", (int)e->delta, e->fn ? "fn" : "null");
        }
        printf("\n");
    }
}

// The model's `edge`: a shift point equal to the RPM the box will see,
// read by a probe in a fixed gear, with the neighbour that could shift the
// car back cleared.
static void edge(Mellovator *m, int32_t g, int up)
{
    float su[9], sd[9];
    uint32_t probe;
    int i;

    m->CurrentGear = g;
    m->DesiredGear = 4;
    m->Brake = 0.0f;
    for (i = 0; i < 4; i++) {
        m->State.ww[i] = fb(MM_EDGE_WW);
        m->BrakeLocked[i] = 0;
    }
    mv_aux();
    probe = bf(m->RPM);
    memcpy(su, m->ShiftUpRPM, sizeof su);
    memcpy(sd, m->ShiftDownRPM, sizeof sd);
    if (up) {
        m->ShiftUpRPM[g] = fb(probe);
        m->ShiftDownRPM[g] = 0.0f;
        m->ShiftDownRPM[g + 1] = 0.0f;
    } else {
        m->ShiftUpRPM[g] = fb(MM_FLT_MAX_BITS);
        m->ShiftDownRPM[g] = fb(probe);
        m->ShiftDownRPM[g - 1] = 0.0f;
    }
    m->CurrentGear = g;
    m->DesiredGear = AUTOMATIC;
    m->Brake = 0.0f;
    for (i = 0; i < 4; i++) {
        m->State.ww[i] = fb(MM_EDGE_WW);
        m->BrakeLocked[i] = 0;
    }
    mv_aux();
    printf("edge %s g=%d probe=%08x -> gear=%d rpm=%08x\n", up ? "up" : "down",
           (int)g, (unsigned)probe, (int)m->CurrentGear, bf(m->RPM));
    memcpy(m->ShiftUpRPM, su, sizeof su);
    memcpy(m->ShiftDownRPM, sd, sizeof sd);
}

static void s_gearbox(void)
{
    MmScen s = moving("gearbox");
    Mellovator *m;
    int d, g, w, b, k, i;

    build(&s);
    m = g_mm->pMellovator;
    for (d = 0; d < MM_N(mm_gear_desired); d++)
        for (g = 0; g < MM_N(mm_gear_start); g++)
            for (w = 0; w < MM_N(mm_gear_ww); w++) {
                m->CurrentGear = mm_gear_start[g];
                m->DesiredGear = mm_gear_desired[d];
                m->Brake = 0.0f;
                for (i = 0; i < 4; i++) {
                    m->State.ww[i] = fb(mm_gear_ww[w]);
                    m->BrakeLocked[i] = 0;
                }
                mv_aux();
                printf("gear d=%d g0=%d ww=%08x -> gear=%d rpm=%08x\n",
                       (int)mm_gear_desired[d], (int)mm_gear_start[g],
                       (unsigned)mm_gear_ww[w], (int)m->CurrentGear,
                       bf(m->RPM));
            }
    for (b = 0; b < MM_N(mm_lock_brake); b++)
        for (k = 0; k < MM_N(mm_lock_before); k++) {
            m->CurrentGear = FIRST_GEAR;
            m->DesiredGear = AUTOMATIC;
            m->Brake = fb(mm_lock_brake[b]);
            for (i = 0; i < 4; i++) {
                m->State.ww[i] = fb(mm_lock_ww[i]);
                m->BrakeLocked[i] = mm_lock_before[k] >> i & 1;
            }
            mv_aux();
            printf("lock brk=%08x before=%x -> ww=", (unsigned)mm_lock_brake[b],
                   (unsigned)mm_lock_before[k]);
            hex4(m->State.ww);
            printf(" locked=%d %d %d %d\n", (int)m->BrakeLocked[0],
                   (int)m->BrakeLocked[1], (int)m->BrakeLocked[2],
                   (int)m->BrakeLocked[3]);
        }
    edge(m, MM_EDGE_UP, 1);
    edge(m, MM_EDGE_DOWN, 0);
    dump_Mellovator("mv", m);
    teardown(1, 0);
}

static void s_derivative(void)
{
    MmScen s = moving("derivative");
    Mellovator *m;
    RigidBody *rb;
    float out[4];
    const VtEntry *e;
    int r, t, bo, br, sp, lk, i;

    build(&s);
    m = g_mm->pMellovator;
    rb = g_mm->pBody;
    e = mv_slot(PHYSICSCOMPONENT_VT_GET_DERIVATIVE);
    for (r = 0; r < MM_N(mm_deriv_rpm); r++)
     for (t = 0; t < MM_N(mm_deriv_thr); t++)
      for (bo = 0; bo < MM_N(mm_deriv_boost); bo++)
       for (br = 0; br < MM_N(mm_deriv_brake); br++)
        for (sp = 0; sp < MM_N(mm_deriv_speed); sp++)
         for (lk = 0; lk < MM_N(mm_deriv_locks); lk++) {
            float *ret;
            m->RPM = (mm_deriv_rpm[r] == 0xffffffffu) ? g_cti->Engine.IdleRPM
                                                      : fb(mm_deriv_rpm[r]);
            m->Throttle = fb(mm_deriv_thr[t]);
            m->CurrentBoost = fb(mm_deriv_boost[bo]);
            m->Brake = fb(mm_deriv_brake[br]);
            rb->Velocity.x = fb(mm_deriv_speed[sp]);
            for (i = 0; i < 4; i++) {
                m->State.ww[i] = fb(mm_deriv_ww[i]);
                m->BrakeLocked[i] = mm_deriv_locks[lk] >> i & 1;
                m->WheelForce[i].x = fb(mm_deriv_force[i]);
            }
            memset(out, 0, sizeof out);
            ret = ((PhysicsGetDerivativeFn)e->fn)(vt_this(m, e), out);
            printf("deriv rpm=%08x thr=%08x boost=%08x brk=%08x v=%08x "
                   "lock=%x -> ", bf(m->RPM), (unsigned)mm_deriv_thr[t],
                   (unsigned)mm_deriv_boost[bo], (unsigned)mm_deriv_brake[br],
                   (unsigned)mm_deriv_speed[sp], (unsigned)mm_deriv_locks[lk]);
            hex4(out);
            printf(" %s\n", ret == out ? "out" : "?");
        }
    teardown(1, 0);
}

static void s_bottom(void)
{
    MmScen s = named("bottom");
    Mellovator *m;
    RigidBody *rb;
    int p, v, i;

    build(&s);
    m = g_mm->pMellovator;
    rb = g_mm->pBody;
    for (p = 0; p < MM_N(mm_bottom_pen); p++)
        for (v = 0; v < MM_N(mm_bottom_vel); v++) {
            float ret;
            float *vel = &rb->Velocity.x;
            float *av = &rb->AngularVelocity.x;
            for (i = 0; i < 3; i++) {
                vel[i] = fb(mm_bottom_vel[v][0][i]);
                av[i] = fb(mm_bottom_vel[v][1][i]);
            }
            for (i = 0; i < 4; i++) {
                m->GroundPenetration[i] = fb(mm_bottom_pen[p][i]);
                m->SuspensionPosition[i] = 0.0625f * (float)i;
            }
            ret = mellovator_bottom_out(m, &g_car->State);
            printf("bottom pen=%08x %08x %08x %08x v=%08x %08x %08x %08x "
                   "%08x %08x ret=%08x\n",
                   (unsigned)mm_bottom_pen[p][0], (unsigned)mm_bottom_pen[p][1],
                   (unsigned)mm_bottom_pen[p][2], (unsigned)mm_bottom_pen[p][3],
                   (unsigned)mm_bottom_vel[v][0][0],
                   (unsigned)mm_bottom_vel[v][0][1],
                   (unsigned)mm_bottom_vel[v][0][2],
                   (unsigned)mm_bottom_vel[v][1][0],
                   (unsigned)mm_bottom_vel[v][1][1],
                   (unsigned)mm_bottom_vel[v][1][2], bf(ret));
            dump_RigidBody("body", rb);
            pc_raw("cs", "WheelBottomOutMagnitude",
                   g_car->State.WheelBottomOutMagnitude, 16);
        }
    teardown(1, 0);
}

static void s_jump(void)
{
    MmScen s = named("jump");
    CarState *cs;
    RigidBody *rb;
    int n, k, v, i, j;

    build(&s);
    cs = &g_car->State;
    rb = g_mm->pBody;
    for (n = 0; n < MM_N(mm_jump_n); n++)
        for (k = 0; k < MM_N(mm_jump_mat); k++)
            for (v = 0; v < MM_N(mm_jump_vel); v++) {
                float *vel = &cs->Velocity.x;
                float *av = &rb->AngularVelocity.x;
                cs->nWheelsTouchingGround = mm_jump_n[n];
                for (i = 0; i < 3; i++) {
                    bVector4 *row = (i == 0) ? &cs->BodyMatrix.v0
                                  : (i == 1) ? &cs->BodyMatrix.v1
                                             : &cs->BodyMatrix.v2;
                    float *rw = &row->x;
                    vel[i] = fb(mm_jump_vel[v][i]);
                    for (j = 0; j < 3; j++)
                        rw[j] = fb(mm_jump_mat[k][3 * i + j]);
                    av[i] = fb(mm_jump_av[i]);
                }
                memset(&rb->ForceAccumulator, 0, sizeof rb->ForceAccumulator);
                memset(&rb->MomentAccumulator, 0, sizeof rb->MomentAccumulator);
                mellowmover_jump_stabilizer(g_mm);
                printf("jump n=%d up=%08x v=%08x %08x %08x\n",
                       (int)mm_jump_n[n], (unsigned)mm_jump_mat[k][8],
                       (unsigned)mm_jump_vel[v][0], (unsigned)mm_jump_vel[v][1],
                       (unsigned)mm_jump_vel[v][2]);
                dump_RigidBody("body", rb);
            }
    teardown(1, 0);
}

static void s_boost(void)
{
    MmScen s = named("boost");
    CarState *cs;
    int f, md, fw;

    s.boostf = 0x3fa00000u;   // 1.25
    s.draft = 0x3e4ccccdu;    // 0.2
    build(&s);
    cs = &g_car->State;
    for (f = 0; f < MM_N(mm_boost_f); f++)
        for (md = 0; md < MM_N(mm_boost_mode); md++)
            for (fw = 0; fw < MM_N(mm_boost_fwd); fw++) {
                cs->DriverMode = mm_boost_mode[md];
                cs->ForwardSpeed = fb(mm_boost_fwd[fw]);
                mellowmover_set_boost(g_mm, fb(mm_boost_f[f]));
                printf("boost f=%08x mode=%d fwd=%08x -> aero=%08x %08x "
                       "catchup=%08x boost=%08x friction=%08x\n",
                       (unsigned)mm_boost_f[f], (int)mm_boost_mode[md],
                       (unsigned)mm_boost_fwd[fw],
                       bf(g_mm->pAerodynamics->Boost),
                       bf(g_mm->pAerodynamics->Draft),
                       bf(g_mm->pBody->CatchUpMultiplier),
                       bf(g_mm->pMellovator->CurrentBoost),
                       bf(g_mm->pMellovator->CurrentFrictionBoost));
            }
    teardown(1, 0);
}

// The model's `knee_boost`: the friction boost whose knee, boost * 0.05,
// is the slip's magnitude exactly.
static int knee_boost(float s, float l, float *mag, float *boost)
{
    const float k = 0.05f;
    float b, e;
    int n;

    *mag = sqrtf(s * s + l * l);
    if (!(*mag > 0.0f))
        return 0;
    b = *mag / k;
    for (n = 0; n < 64; n++) {
        e = b * k;
        if (e == *mag) {
            *boost = b;
            return 1;
        }
        b = fb(bf(b) + (e < *mag ? 1u : 0xffffffffu));
    }
    return 0;
}

static void s_access(void)
{
    MmScen s = moving("access");
    Mellovator *m;
    const VtEntry *e;
    float buf[4];
    int i;

    build(&s);
    m = g_mm->pMellovator;
    e = mv_slot(PHYSICSCOMPONENT_VT_GET_SIZE);
    printf("size %d\n", (int)((PhysicsGetSizeFn)e->fn)(vt_this(m, e)));
    e = mv_slot(PHYSICSCOMPONENT_VT_GET_STATE);
    printf("state -> %s\n",
           label(((PhysicsGetStateFn)e->fn)(vt_this(m, e))));
    for (i = 0; i < 4; i++)
        buf[i] = fb(mm_access_state[i]);
    e = mv_slot(PHYSICSCOMPONENT_VT_SET_STATE_ARRAY);
    ((PhysicsStateArrayFn)e->fn)(vt_this(m, e), buf);
    memset(buf, 0, sizeof buf);
    e = mv_slot(PHYSICSCOMPONENT_VT_GET_STATE_ARRAY);
    ((PhysicsStateArrayFn)e->fn)(vt_this(m, e), buf);
    printf("get state ");
    hex4(buf);
    printf("\n");
    mellovator_set_throttle(m, 0.375f);
    mellovator_set_brake(m, 0.8125f);
    mellovator_set_steering(m, 0xf123);
    mellovator_set_desired_gear(m, 5);
    mellovator_set_current_boost(m, 1.125f);
    mellovator_set_current_friction_boost(m, 0.875f);
    printf("rpm %08x gear %d\n", bf(mellovator_get_rpm(m)),
           (int)mellovator_get_current_gear(m));
    for (i = 0; i < 4; i++) {
        m->TouchingGround[i] = mm_access_touch[i];
        m->bSlipping[i] = mm_access_slip[i];
    }
    for (i = 0; i < 4; i++)
        printf("wheel %d touch=%d force=%08x pos=%08x slipping=%d slip=%s "
               "ww=%08x\n", i, (int)mellovator_get_touching_ground(m, i),
               bf(mellovator_get_suspension_force(m, i)),
               bf(mellovator_get_suspension_position(m, i)),
               (int)mellovator_get_wheel_slipping(m, i),
               label(mellovator_get_wheel_slip(m, i)),
               bf(mellovator_get_wheel_angular_velocity(m, i)));

    // ResolveForces clears every wheel's slipping flag first.
    for (i = 0; i < 4; i++)
        m->bSlipping[i] = 1;
    e = mv_slot(PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(m, e));
    printf("rf slipping %d %d %d %d\n", (int)m->bSlipping[0],
           (int)m->bSlipping[1], (int)m->bSlipping[2], (int)m->bSlipping[3]);

    // The grip knee, met exactly.
    for (i = 0; i < 4; i++) {
        float mag, b;
        if (!mm_access_touch[i])
            continue;
        if (!knee_boost(m->WheelSlip[i].x, m->WheelSlip[i].y, &mag, &b))
            continue;
        m->CurrentFrictionBoost = b;
        e = mv_slot(PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
        ((PhysicsVoidFn)e->fn)(vt_this(m, e));
        printf("knee wheel=%d mag=%08x boost=%08x force=%08x %08x\n", i,
               bf(mag), bf(b), bf(m->WheelForce[i].x), bf(m->WheelForce[i].y));
        break;
    }
    if (i == 4)
        printf("knee none\n");

    // SetState(ffff) clears the locks and the suspension.
    for (i = 0; i < 4; i++) {
        m->BrakeLocked[i] = 1;
        m->SuspensionPosition[i] = 0.25f;
    }
    mellovator_set_state4(m, fb(mm_access_set4[0]), fb(mm_access_set4[1]),
                          fb(mm_access_set4[2]), fb(mm_access_set4[3]));
    dump_Mellovator("mv", m);
    teardown(1, 0);
}

static void s_calibrate(void)
{
    MmScen s = moving("calibrate");
    RigidBody *b;
    float *ib;
    int i;

    build(&s);
    b = g_mm->pBody;
    b->Mass = 2.0f;
    b->Mass_inv = 0.5f;
    ib = &b->I_body_inv.v0.x;
    for (i = 0; i < 16; i++)
        ib[i] = 0.25f;
    mellowmover_calibrate(g_mm);
    dump_RigidBody("body", b);
    dump_Mellovator("mv", g_mm->pMellovator);
    teardown(1, 0);
}

static void s_dtors(void)
{
    MmScen s = named("dtor-mover-0");
    Mellovator *mv, *p;
    const VtEntry *e;

    build(&s);
    mv = g_mm->pMellovator;
    teardown(0, 0);
    // A freed slot keeps all but its first word.
    printf("freed mv.vt=%08x\n", (unsigned)mv->_vtable);
    s.name = "dtor-vehicle-1";
    build(&s);
    teardown(1, 1);
    s.name = "dtor-vehicle-0";
    build(&s);
    teardown(0, 1);

    // The Mellovator's own destructor without the delete bit.
    s.name = "dtor-mellovator-0";
    build(&s);
    p = mellovator_init(mellovator_new(), g_cti, g_mm->pBody,
                        (TopologyCoordinate *)g_topo);
    e = vt_slot(p->_vtable, PHYSICSCOMPONENT_VT_DTOR);
    ((PhysicsDtorFn)e->fn)(vt_this(p, e), 0);
    printf("mellovator dtor 0 vt=%08x\n", (unsigned)p->_vtable);
    say_pools();
    mellovator_delete(p);
    say_pools();
    teardown(1, 0);
}

int main(void)
{
    int i;

    setvbuf(stdout, NULL, _IONBF, 0);
    bSlotPoolManagerInit();
    vt_reset();
    physicssystem_install_vtables();
    physcomp_install_vtables();
    physicscar_install_vtables();
    mellowmover_install_vtables();
    wheel_install_seams();
    rigidbody_static_init();
    wheel_static_init();
    aerodynamics_static_init();
    physicscar_static_init();
    car_static_init();
    mellowmover_static_init();
    InitPhysics(8);
    for (i = 0; i < 9; i++)
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

    s_static();
    s_tables();
    for (i = 0; i < MM_NSCEN; i++)
        run_move(&mm_scen[i]);
    s_gearbox();
    s_derivative();
    s_bottom();
    s_jump();
    s_boost();
    s_access();
    s_calibrate();
    s_dtors();
    return 0;
}
