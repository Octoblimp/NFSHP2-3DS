// Transcript harness for physicscar. Cross-checked by
// tools/physicscar_check.py, which runs the same scenarios on the image in
// mipsemu and compares the two transcripts line for line.
//
// This file is not compiled alone. The checker prepends a generated prefix
// -- a dump function and a field table for every struct the car owns, parsed
// out of the port's headers, and the scenario inputs as bit patterns -- and
// compiles the two as one translation unit. What is printed, and in what
// order, is the prefix's; what is run is this file's.
//
// Every stand-in here has a twin in the model: the terrain plane, the road
// noise, the ticker that counts up 1000 per read, the skid maker that only
// says it was asked, and the labels, which name what a pointer points at by
// object and field on this side's own layout.

#ifndef PC_GENERATED
#error "physicscar_test.c is built by tools/physicscar_check.py, which prepends the generated dumps"
#endif

#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bslotpool.h"
#include "bticker.h"
#include "cardamage.h"
#include "joystick.h"
#include "p32.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "race.h"
#include "realdriver.h"
#include "vtable.h"

// car.c's, and nothing this harness runs reads it.
int32_t WorldTimeFrames = 0;

// The checker links with --wrap=free, so the destructor's delete can be
// seen: while g_track_frees is set, every block freed is written down.
void __real_free(void *p);
static int         g_track_frees;
static const void *g_freed[8];
static int         g_nfreed;

void __wrap_free(void *p)
{
    if (g_track_frees && p != NULL && g_nfreed < 8)
        g_freed[g_nfreed++] = p;
    __real_free(p);
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

static PhysicsCar  *g_pc;
static Car         *g_car;
static CarDriver   *g_drv;        // the base of g_rdrv
static RealDriver  *g_rdrv;
static CarTypeInfo *g_cti;
static char         g_topo[16];   // the TopologyCoordinate the car carries
static int32_t      g_race[4];    // a Race, as far as its stage

typedef struct Obj {
    const char   *name;
    const void   *base;
    size_t        size;
    const PcType *t;
} Obj;

static const char *const wheel_name[4] = { "wheel0", "wheel1", "wheel2", "wheel3" };
static const char *const susp_name[4]  = { "susp0", "susp1", "susp2", "susp3" };

// The same objects in the same order as the model's, read live off the car
// so a pointer printed during the constructor names what exists so far.
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
    ADD("drv", g_drv, sizeof(CarDriver), NULL);
    ADD("cti", g_cti, 1368, NULL);
    ADD("topo", g_topo, sizeof g_topo, NULL);
    if (g_pc != NULL) {
        ADD("pc", g_pc, sizeof(PhysicsCar), &pct_PhysicsCar);
        ADD("body", g_pc->pBody, sizeof(RigidBody), &pct_RigidBody);
        ADD("steer", g_pc->pSteering, sizeof(TwoWheelAckermanSteering),
            &pct_TwoWheelAckermanSteering);
        for (i = 0; i < 4; i++)
            ADD(wheel_name[i], g_pc->pWheel[i], sizeof(Wheel), &pct_Wheel);
        for (i = 0; i < 4; i++)
            ADD(susp_name[i], g_pc->pSuspension[i], sizeof(Suspension),
                &pct_Suspension);
        ADD("engine", g_pc->pEngine, sizeof(Engine), &pct_Engine);
        ADD("dtrain", g_pc->pDriveTrain, sizeof(DriveTrain), &pct_DriveTrain);
        ADD("aero", g_pc->pAerodynamics, sizeof(Aerodynamics),
            &pct_Aerodynamics);
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

static void say_globals(void);

// ------------------------------------------------------------ the stand-ins

static uint32_t g_tick;

static uint32_t scripted_tick(void)
{
    g_tick += 1000;
    return g_tick;
}

// The plane z = x/32 - y/64, its normal, terrain (int)(x/2) & 3, and a
// road noise of terrain/4 + x/1000.
static float fake_elevation(void *topology, const bVector3 *pos,
                            int32_t *terrainOut, bVector3 *normalOut)
{
    float el = 0.03125f * pos->x + -0.015625f * pos->y;

    printf("elev topo=%s pos=%08x %08x %08x tout=%s nout=%s\n",
           label(topology), bf(pos->x), bf(pos->y), bf(pos->z),
           label(terrainOut), label(normalOut));
    normalOut->x = fb(PC_NORMAL_X);
    normalOut->y = fb(PC_NORMAL_Y);
    normalOut->z = fb(PC_NORMAL_Z);
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

// Wheel::MaybeMakeSkids is the skid renderer's; the model's stub logs the
// same line.
static void fake_skids(Wheel *w, float dt)
{
    printf("skids %s dt=%08x\n", label(w), bf(dt));
}

// Four surfaces. Only the three friction multipliers are read.
static TerrainTypeInfo g_terrain[4];

static void build_terrain(void)
{
    int i;
    for (i = 0; i < 4; i++) {
        g_terrain[i].StaticFrictionMultiplier  = fb(PC_TERRAIN[i][0]);
        g_terrain[i].DynamicFrictionMultiplier = fb(PC_TERRAIN[i][1]);
        g_terrain[i].RollingFrictionMultiplier = fb(PC_TERRAIN[i][2]);
    }
}

// ------------------------------------------------------------ the pools

static BSlotPool **const pools[7] = {
    &RigidBodySlotPool, &TwoWheelAckermanSteeringSlotPool, &WheelSlotPool,
    &EngineSlotPool, &DriveTrainSlotPool, &AerodynamicsSlotPool,
    &SuspensionSlotPool,
};
static const char *const pool_name[7] = {
    "RigidBody", "Ackerman", "Wheel", "Engine", "DriveTrain", "Aerodynamics",
    "Suspension",
};
static int pool_free0[7];

static void say_pools(void)
{
    int i;
    printf("pools");
    for (i = 0; i < 7; i++)
        printf(" %s=%d", pool_name[i],
               pool_free0[i] - bCountFreeSlots(*pools[i]));
    printf("\n");
}

// ------------------------------------------------------------ the dump

static void say_globals(void)
{
    printf("globals ugly=%08x trigger=%d counter=%d resolve=%08x "
           "iterate=%08x aux=%08x tick=%u\n",
           bf(gUglyTimestepHack), (int)TriggerBounce,
           (int)PhysicsCarResolveCounter, bf(ResolveTime), bf(IterateTime),
           bf(AuxTime), (unsigned)g_tick);
}

static void walk(void)
{
    const PhysicsSystem *sys = &g_pc->Vehicle;
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
    pc_raw("pc.Vehicle", "Size", &sys->Size, 4);
}

static void dump_all(const char *tag)
{
    int i;
    printf("-- %s\n", tag);
    dump_PhysicsCar("pc", g_pc);
    dump_RigidBody("body", g_pc->pBody);
    dump_TwoWheelAckermanSteering("steer",
                                  (const TwoWheelAckermanSteering *)g_pc->pSteering);
    for (i = 0; i < 4; i++)
        dump_Wheel(wheel_name[i], g_pc->pWheel[i]);
    for (i = 0; i < 4; i++)
        dump_Suspension(susp_name[i], g_pc->pSuspension[i]);
    dump_Engine("engine", g_pc->pEngine);
    dump_DriveTrain("dtrain", g_pc->pDriveTrain);
    dump_Aerodynamics("aero", g_pc->pAerodynamics);
    dump_CarState("cs", &g_car->State);
    walk();
    say_globals();
}

// What Move writes outside the car: the driver's pedals and gears, and the
// dyno's globals.
static void say_move_extras(void)
{
    printf("drv thr=%08x brk=%08x ebrk=%08x steer=%04x dgear=%d sgear=%d "
           "nitro=%d\n", bf(g_drv->Throttle), bf(g_drv->Brake),
           bf(g_drv->EBrake), (unsigned)g_drv->Steering, (int)g_drv->DesiredGear,
           (int)g_drv->SportGear, (int)g_drv->NitroFlag);
    printf("dyno %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
           bf(SpeedDebugStartTime), bf(SpeedDebugDisplayTime60),
           bf(SpeedDebugDisplayTime100), bf(SpeedDebugDisplayTimeQM),
           bf(SpeedDebug060Time), bf(SpeedDebug0100Time), bf(SpeedDebugQMTime),
           bf(SpeedDebugQMMeasure), bf(SpeedDebugQMSpeed));
    pc_raw("dyno", "X", &SpeedDebugX, 16);
    pc_raw("dyno", "R", &SpeedDebugR, 64);
    printf("seed %08x\n", (unsigned)bDefaultSeed);
}

// ------------------------------------------------------------ the car

static void reset_globals(const PcScen *s)
{
    UseNewSuspensionCalibration = s->newcal;
    TriggerBounce = s->trigger;
    UseMagicForce = s->magic;
    TestRPM = fb(s->testrpm);
    gUglyTimestepHack = 1.0f;
    PhysicsCarResolveCounter = 0;
    ResolveTime = 0.0f;
    IterateTime = 0.0f;
    AuxTime = 0.0f;
    g_tick = 0;

    WorldTimer = s->wtimer;
    WorldTimeElapsed = 0.0f;
    SpeedDebugInfo = s->sdebug;
    RigidBodyDebugInfo = s->dbgprint;
    DriveTrainDebugInfo = s->dbgprint;
    bDefaultSeed = (uint32_t)s->seed;
    SpeedDebugStartTime = 0.0f;
    SpeedDebugDisplayTime60 = fb(s->sd_disp);
    SpeedDebugDisplayTime100 = fb(s->sd_disp);
    SpeedDebugDisplayTimeQM = fb(s->sd_disp);
    SpeedDebug060Time = fb(s->sd_t);
    SpeedDebug0100Time = fb(s->sd_t);
    SpeedDebugQMTime = fb(s->sd_t);
    SpeedDebugQMMeasure = fb(s->sd_qm);
    SpeedDebugQMSpeed = 0.0f;
    memset(&SpeedDebugX, 0, sizeof SpeedDebugX);
    memset(&SpeedDebugR, 0, sizeof SpeedDebugR);
    memset(CurrentJoystickTypes, 0, sizeof CurrentJoystickTypes);
    CurrentJoystickTypes[s->port] = (uint8_t)s->joy;
    RaceParametersDamageEnabled = s->dmgon;
    g_race[0] = s->stage;
}

static void build(const PcScen *s)
{
    CarState *cs;
    int i, j;

    reset_globals(s);
    g_cti = calloc(1, sizeof(CarTypeInfo));
    memcpy(g_cti, pc_cti[s->car], 1368);
    g_cti->Control.MaxZMomentAccExtreme = fb(s->extreme);
    g_cti->Control.YawControl = fb(s->yawctl);
    g_car = calloc(1, sizeof(Car));
    g_rdrv = calloc(1, sizeof(RealDriver));
    g_drv = &g_rdrv->Base;
    g_car->TheControlMode = s->ctrl;
    g_car->DraftFactor = fb(s->draft);

    g_car->MyDriver = calloc(1, sizeof(DriverInfo));
    g_car->MyDriver->TheDriverType = s->dtype;
    g_car->pDynamicCollisionBody = calloc(1, sizeof(CarCollisionBody));
    g_car->pDynamicCollisionBody->LastYawControlCollisionTime.PackedTime =
        (uint32_t)s->ycstamp;
    g_car->RenderingEnabled = (int8_t)s->render;
    g_car->BlownTireBits = (uint8_t)s->blown;
    g_car->fTractionBoostOverride = fb(s->tbo);
    g_car->fDamageBoostOverride = fb(s->dbo);
    if (s->dmg >= 0) {
        g_car->pCarDamage = calloc(1, sizeof(CarDamage));
        g_car->pCarDamage->TheBodyDamage.CompressedTotalDamage =
            (uint16_t)s->dmg;
    }
    if (s->blink) {
        g_car->BlinkTimer = s->blink;
        g_car->BlinkDuration = 2.0f;
    }

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
        cs->WheelAngularVelocity[i] = fb(s->ww);
        cs->WheelTouchingGround[i] = (int8_t)s->touch;
    }
    cs->nWheelsTouchingGround = 4 * s->touch;
    cs->RPM = fb(s->rpm);
    cs->CurrentGear = s->gear;
    cs->ForwardSpeed = fb(s->fwd);
    cs->DriverMode = s->dmode;
    cs->BoostFactor = fb(s->boostf);
    cs->BurnOutState = s->bstate;
    cs->BurnOutTime = fb(s->btime);
    cs->BurnOutTraction = fb(s->btrac);
    cs->BurnOutAllow = fb(s->ballow);

    g_drv->Steering = (uint16_t)s->steer;
    g_drv->Throttle = fb(s->thr);
    g_drv->Brake = fb(s->brk);
    g_drv->EBrake = fb(s->ebrk);
    g_drv->DesiredGear = s->dgear;
    g_drv->SportGear = s->sgear;
    g_drv->NitroFlag = s->nitro;
    g_rdrv->Port = s->port;

    g_pc = calloc(1, sizeof(PhysicsCar));
    printf("== %s\n", s->name);
    physicscar_init(g_pc, g_cti, g_drv, g_car);
    say_pools();
}

static void after_ctor(const PcScen *s)
{
    int i;
    g_pc->pEngine->Throttle = fb(s->eng_thr);
    for (i = 0; i < 4; i++) {
        g_pc->pWheel[i]->Brake = fb(s->w_brake);
        g_pc->pWheel[i]->EBrake = fb(s->w_ebrake);
    }
    if (s->thr_ovr != 0x3f800000u)
        g_pc->pEngine->ThrottleOverride = fb(s->thr_ovr);
    if (s->atq[0] | s->atq[1] | s->atq[2] | s->atq[3])
        for (i = 0; i < 4; i++)
            g_pc->pWheel[i]->AppliedTorque = fb(s->atq[i]);
    for (i = 0; i < 4; i++) {
        if (s->wterr[i] >= 0)
            g_pc->pWheel[i]->Terrain = s->wterr[i];
        if (s->wlock >> i & 1)
            g_pc->pWheel[i]->BrakeLocked = 1;
    }
    if (s->mass != 0)
        ((RigidBodyInfo *)g_pc->pBody->RBI)->Mass = fb(s->mass);
}

// Through the Mover's table, as Car does, or through the PhysicsVehicle's.
static void teardown(int32_t flags, int vehicle)
{
    const VtEntry *e;
    PhysicsCar *pc = g_pc;

    g_nfreed = 0;
    g_track_frees = 1;
    if (!vehicle) {
        e = vt_slot(pc->Mover._vtable, CARMOVER_VT_DTOR);
        ((CarMoverDtorFn)e->fn)(vt_this(&pc->Mover, e), flags);
    } else {
        e = vt_slot(pc->Vehicle._vtable, PHYSICSSYSTEM_VT_DTOR);
        ((PhysicsDtorFn)e->fn)(vt_this(&pc->Vehicle, e), flags);
    }
    g_track_frees = 0;
    // With the delete bit the 116 bytes are gone, vptrs and all.
    if (!(flags & 1)) {
        printf("dtor mover.vt=%08x vehicle.vt=%08x\n",
               (unsigned)pc->Mover._vtable, (unsigned)pc->Vehicle._vtable);
        free(pc);
    }
    g_pc = NULL;
    say_pools();
    free(g_car->MyDriver);
    free(g_car->pDynamicCollisionBody);
    free(g_car->pCarDamage);
    free(g_car);
    free(g_rdrv);
    free(g_cti);
    g_car = NULL;
    g_drv = NULL;
    g_rdrv = NULL;
    g_cti = NULL;
}

static void reinit(const PcScen *s)
{
    if (s->reinit) {
        physicscar_initialize_state_from_car(g_pc);
        dump_all("reinit");
    }
}

static void run_car(const PcScen *s)
{
    int n;
    char tag[32];

    build(s);
    dump_all("ctor");
    after_ctor(s);
    for (n = 0; n < s->steps; n++) {
        if (s->integ)
            physicssystem_integrate_runge_kutta(&g_pc->Vehicle, fb(s->dt));
        else
            physicssystem_integrate_euler(&g_pc->Vehicle, fb(s->dt));
        snprintf(tag, sizeof tag, "step %d", n);
        dump_all(tag);
        physicscar_update_car(g_pc, fb(s->dt));
        printf("-- update %d\n", n);
        dump_CarState("cs", &g_car->State);
    }
    reinit(s);
    teardown(0, 0);
}

// Move, a frame at a time, through the Mover's table as Car::Move calls
// it. Each frame the clock moves on by wstep ticks and the driver's pedals
// are put back -- Move tidies them -- with the throttle and the handbrake
// on only in the frames their patterns name.
static void run_move(const PcScen *s)
{
    const VtEntry *e;
    float r;
    int n;
    char tag[32];

    build(s);
    // The Ackerman matrices are zero out of the constructor; see run_move
    // in physicscar_check.py.
    e = vt_slot(g_pc->pSteering->_vtable, STEERING_VT_SET_STEERING);
    ((SteeringSetSteeringFn)e->fn)(vt_this(g_pc->pSteering, e),
                                   (uint16_t)s->steer);
    physicscar_compute_auxiliaries(g_pc);
    after_ctor(s);
    for (n = 0; n < s->steps; n++) {
        WorldTimer = s->wtimer + n * s->wstep;
        WorldTimeElapsed = (float)s->wstep * 0.00025f;
        g_drv->Steering = (uint16_t)s->steer;
        g_drv->Throttle = ((s->thrpat >> n) & 1) ? fb(s->thr) : 0.0f;
        g_drv->Brake = fb(s->brk);
        g_drv->EBrake = ((s->ebpat >> n) & 1) ? fb(s->ebrk) : 0.0f;
        e = vt_slot(g_pc->Mover._vtable, CARMOVER_VT_MOVE);
        r = ((CarMoverMoveFn)e->fn)(vt_this(&g_pc->Mover, e), fb(s->dt));
        printf("-- move %d ret=%08x\n", n, bf(r));
        snprintf(tag, sizeof tag, "move %d", n);
        dump_all(tag);
        say_move_extras();
    }
    reinit(s);
    teardown(0, 0);
}

// ------------------------------------------------------------ direct calls

static PcScen moving(const char *name)
{
    PcScen s = pc_scen[PC_MOVE_INDEX];
    s.name = name;
    return s;
}

static void s_static(void)
{
    const bVector2 *pts = JumpStabilization.pPoints;
    int i;

    printf("== static\n");
    printf("YawLockThreshold %08x\n", bf(YawLockThreshold));
    printf("JumpStabilization %d", (int)JumpStabilization.NumPoints);
    for (i = 0; i < JumpStabilization.NumPoints; i++)
        printf(" %08x %08x", bf(pts[i].x), bf(pts[i].y));
    printf("\n");
    printf("tuning %d %d %08x %08x %08x %08x %08x %d %08x\n",
           (int)UseNewSuspensionCalibration, (int)TriggerBounce,
           bf(LowSpeedYawBoost), bf(HighSpeedYawBoost), bf(LowSpeedSpeed),
           bf(HighSpeedSpeed), bf(MaxYawBonus), (int)UseMagicForce,
           bf(SkidNormalize));
    printf("move tuning %d %d %08x %08x %08x %08x %08x %08x %08x %08x %08x "
           "%08x %08x %d\n", (int)RigidBodyDebugInfo, (int)DriveTrainDebugInfo,
           bf(NFSAdjust), bf(MaximumTimeStep), bf(BurnOutTorqueValue),
           bf(BurnOutTorqueValueClip), bf(BurnOutCancelTorqueValue),
           bf(BurnOutMaxSpeed), bf(BurnOutTractionValue), bf(BurnOutMinTime),
           bf(BurnOutAllowTime), bf(BurnOutYawMax), bf(BurnOutYawCancel),
           (int)SpeedDebugInfo);
    pc_raw("move", "BrakeSettings", BrakeSettings, 16);
    pc_raw("move", "EBrakeSettings", EBrakeSettings, 16);
    printf("seed %08x\n", (unsigned)bDefaultSeed);
}

static void s_tables(void)
{
    static const struct { const char *name; uint32_t vt; } t[4] = {
        { "CarMover", CARMOVER_VTABLE },
        { "PhysicsCar", PHYSICSCAR_VTABLE },
        { "PhysicsCar$Vehicle", PHYSICSCAR_VEHICLE_VTABLE },
        { "PhysicsVehicle", PHYSICSVEHICLE_VTABLE },
    };
    int i, j, n;

    printf("== tables\n");
    for (i = 0; i < 4; i++) {
        const VtEntry *tab = vt_table(t[i].vt, &n);
        printf("vt %s n=%d", t[i].name, n);
        for (j = 0; j < n; j++) {
            const VtEntry *e = &tab[j];
            if (e->delta != 0
                && e->delta == -(int)offsetof(PhysicsCar, Vehicle))
                printf(" pc/%s", e->fn ? "fn" : "null");
            else
                printf(" %d/%s", (int)e->delta, e->fn ? "fn" : "null");
        }
        printf("\n");
    }
}

static void s_damp(void)
{
    PcScen s = moving("damp");
    RigidBody *rb;
    int t, v, a, k, i, n = 0;

    build(&s);
    printf("-- damp\n");
    rb = g_pc->pBody;
    for (t = 0; t < PC_N(pc_damp_thr); t++)
        for (v = 0; v < PC_N(pc_damp_vec); v++)
            for (a = 0; a < PC_N(pc_damp_vec); a++)
                for (k = 0; k < PC_N(pc_damp_tilt); k++) {
                    float *vel = &rb->Velocity.x;
                    float *av = &rb->AngularVelocity.x;
                    g_drv->Throttle = fb(pc_damp_thr[t]);
                    for (i = 0; i < 3; i++) {
                        vel[i] = fb(pc_damp_vec[v][i]);
                        av[i] = fb(pc_damp_vec[a][(i + 1) % 3]);
                    }
                    rb->State.R.v0.z = fb(pc_damp_tilt[k][0]);
                    rb->State.R.v1.z = fb(pc_damp_tilt[k][1]);
                    printf("damp %d %d\n", n,
                           (int)physicscar_check_damping_suitability(g_pc));
                    n++;
                }
    teardown(0, 0);
}

static void s_bottom(void)
{
    int b, i;
    char name[64];

    for (b = 0; b < PC_N(pc_bottom); b++) {
        const PcBottom *c = &pc_bottom[b];
        PcScen s = moving(NULL);
        float *vel;

        snprintf(name, sizeof name, "bottom-%s", c->name);
        s.name = name;
        s.ctrl = c->mode;
        build(&s);
        after_ctor(&s);
        vel = &g_pc->pBody->Velocity.x;
        for (i = 0; i < 3; i++)
            vel[i] = fb(c->vel[i]);
        g_drv->Throttle = 0.0f;
        for (i = 0; i < c->n; i++) {
            Suspension *sp = g_pc->pSuspension[c->corner[i]];
            sp->State.z = sp->SI->BumpStop[0];
        }
        TriggerBounce = c->trigger;
        gUglyTimestepHack = 1.0f;
        physicscar_bottom_out(g_pc);
        snprintf(name, sizeof name, "bottom %s", c->name);
        dump_all(name);
        teardown(0, 0);
    }
}

static void s_yaw(void)
{
    float *const tune[5] = { &LowSpeedYawBoost, &HighSpeedYawBoost,
                             &LowSpeedSpeed, &HighSpeedSpeed, &MaxYawBonus };
    float saved[5];
    int t, i, y, e, sp, c, m, tl, bo, n = 0;

    printf("== yaw\n");
    for (i = 0; i < 5; i++)
        saved[i] = *tune[i];
    for (t = 0; t < 1 + PC_N(pc_yaw_tuning); t++) {
        for (i = 0; i < 5; i++)
            *tune[i] = t ? fb(pc_yaw_tuning[t - 1][i]) : saved[i];
        for (y = 0; y < PC_N(pc_yaw_yaw); y++)
         for (e = 0; e < PC_N(pc_yaw_ebrake); e++)
          for (sp = 0; sp < PC_N(pc_yaw_speed); sp++)
           for (c = 0; c < PC_N(pc_yaw_ctrl); c++)
            for (m = 0; m < PC_N(pc_yaw_mode); m++)
             for (tl = 0; tl < PC_N(pc_yaw_tilt); tl++)
              for (bo = 0; bo < PC_N(pc_yaw_boost); bo++) {
                  float tilt = fb(pc_yaw_tilt[tl]);
                  float r = YawFrictionBoost(fb(pc_yaw_yaw[y]),
                                             fb(pc_yaw_ebrake[e]),
                                             fb(pc_yaw_speed[sp]),
                                             fb(pc_yaw_ctrl[c][0]),
                                             fb(pc_yaw_ctrl[c][1]),
                                             pc_yaw_mode[m], &tilt,
                                             fb(pc_yaw_boost[bo]));
                  printf("yaw %d %08x %08x\n", n, bf(r), bf(tilt));
                  n++;
              }
    }
    for (i = 0; i < 5; i++)
        *tune[i] = saved[i];
}

static void s_brake(void)
{
    PcScen s = moving("brake");
    int b, w;

    build(&s);
    printf("-- brake\n");
    for (b = 0; b < PC_N(pc_brake_bias); b++) {
        g_cti->Control.BrakeBias = fb(pc_brake_bias[b]);
        for (w = 0; w < 4; w++)
            printf("brake %08x %d %08x\n", pc_brake_bias[b], w,
                   bf(physicscar_get_brake_settings(g_pc, w)));
    }
    teardown(0, 0);
}

static void s_jump(void)
{
    PcScen s = moving("jump");
    RigidBody *rb;
    int w, a, i;
    char pfx[32];

    build(&s);
    printf("-- jump\n");
    rb = g_pc->pBody;
    for (w = 0; w < PC_N(pc_jump_wheels); w++)
        for (a = 0; a < PC_N(pc_jump_av); a++) {
            float *av = &rb->AngularVelocity.x;
            float *m = &rb->MomentAccumulator.x;
            g_car->State.nWheelsTouchingGround = pc_jump_wheels[w];
            for (i = 0; i < 4; i++) {
                av[i] = (i < 3) ? fb(pc_jump_av[a][i]) : 0.0f;
                m[i] = 0.0f;
            }
            physicscar_jump_stabilizer(g_pc);
            snprintf(pfx, sizeof pfx, "jump %d", pc_jump_wheels[w]);
            pc_raw(pfx, "MomentAccumulator", &rb->MomentAccumulator, 16);
        }
    teardown(0, 0);
}

static void s_boost(void)
{
    PcScen s = moving("boost");
    int b, i;

    build(&s);
    for (b = 0; b < PC_N(pc_boost); b++) {
        g_car->DraftFactor = fb(pc_boost[b][1]);
        physicscar_set_boost(g_pc, fb(pc_boost[b][0]));
        printf("-- boost %08x %08x\n", pc_boost[b][0], pc_boost[b][1]);
        pc_raw("engine", "CatchupTorqueMultiplier",
               &g_pc->pEngine->CatchupTorqueMultiplier, 4);
        pc_raw("body", "CatchUpMultiplier", &g_pc->pBody->CatchUpMultiplier, 4);
        dump_Aerodynamics("aero", g_pc->pAerodynamics);
        for (i = 0; i < 4; i++)
            pc_raw(wheel_name[i], "CatchupFrictionMultiplier",
                   &g_pc->pWheel[i]->CatchupFrictionMultiplier, 4);
    }
    physicscar_set_friction_boost(g_pc, 0.75f);
    pc_raw("pc", "FrictionBoost", &g_pc->FrictionBoost, 4);
    teardown(0, 0);
}

static void s_dtors(void)
{
    PcScen s = moving("dtor-vehicle");
    int i;

    s.steps = 0;
    build(&s);
    teardown(0, 1);
    s.name = "dtor-delete";
    build(&s);
    {
        const void *pc = g_pc;
        teardown(1, 0);
        printf("deleted");
        for (i = 0; i < g_nfreed; i++)
            printf(" %s", g_freed[i] == pc ? "pc" : "other");
        printf("\n");
    }
}

static void s_joystick(void)
{
    int c, r;

    printf("== joystick\n");
    for (c = 0; c < 256; c++) {
        CurrentJoystickTypes[1] = (uint8_t)c;
        r = (int)IsJoystickTypeWheel(1);
        if (r)
            printf("wheel %d %d\n", c, r);
    }
    CurrentJoystickTypes[0] = 7;
    CurrentJoystickTypes[1] = 201;
    printf("type %d %d\n", (int)GetJoystickType(0), (int)GetJoystickType(1));
    memset(CurrentJoystickTypes, 0, sizeof CurrentJoystickTypes);
}

static void s_damage(void)
{
    static const uint16_t total[6] = { 0, 1, 4095, 4096, 10240, 65535 };
    BodyDamage b;
    int en, i;

    printf("== damage\n");
    for (en = 0; en < 3; en++) {
        RaceParametersDamageEnabled = en;
        for (i = 0; i < 6; i++) {
            memset(&b, 0, sizeof b);
            b.CompressedTotalDamage = total[i];
            printf("damage %d %u %08x\n", en, (unsigned)total[i],
                   bf(bodydamage_get_visible_total_damage(&b)));
        }
    }
    RaceParametersDamageEnabled = 0;
}

// IterateForces with the pc_locks wheels locked and their contact patches
// still; see LOCKS in physicscar_check.py for why no scenario reaches it.
static void s_lock(void)
{
    PcScen s = moving("lock");
    const VtEntry *e;
    int m, i;
    char tag[32];

    build(&s);
    e = vt_slot(g_pc->pSteering->_vtable, STEERING_VT_SET_STEERING);
    ((SteeringSetSteeringFn)e->fn)(vt_this(g_pc->pSteering, e),
                                   (uint16_t)s.steer);
    for (m = 0; m < PC_N(pc_locks); m++) {
        physicscar_compute_auxiliaries(g_pc);
        for (i = 0; i < 4; i++)
            if (pc_locks[m] >> i & 1) {
                Wheel *w = g_pc->pWheel[i];
                w->BrakeLocked = 1;
                memset(&w->Velocity, 0, sizeof w->Velocity);
            }
        physicscar_iterate_forces(g_pc);
        snprintf(tag, sizeof tag, "lock %x", (unsigned)pc_locks[m]);
        dump_all(tag);
    }
    teardown(0, 0);
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
    wheel_install_seams();
    rigidbody_static_init();
    wheel_static_init();
    aerodynamics_static_init();
    physicscar_static_init();
    car_static_init();
    InitPhysics(8);
    for (i = 0; i < 7; i++)
        pool_free0[i] = bCountFreeSlots(*pools[i]);

    bSetTickerSource(scripted_tick);
    build_terrain();
    gTerrainTypeInfoTable = g_terrain;
    gTopologyGetElevationFn = fake_elevation;
    gTerrainRoadNoiseFn = fake_road_noise;
    gWheelTopologyOfCarStateFn = topology_of;
    gWheelMaybeMakeSkidsFn = fake_skids;
    pCurrentRace = (Race *)(void *)g_race;

    s_static();
    s_tables();
    for (i = 0; i < PC_NSCEN; i++) {
        if (pc_scen[i].move)
            run_move(&pc_scen[i]);
        else
            run_car(&pc_scen[i]);
    }
    s_damp();
    s_bottom();
    s_yaw();
    s_brake();
    s_jump();
    s_boost();
    s_dtors();
    s_joystick();
    s_damage();
    s_lock();
    return 0;
}
