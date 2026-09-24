// Transcript harness for Wheel.
// Cross-checked by tools/wheel_check.py, which models the same behaviour
// from the disassembly at 0x00199c40..0x0019b9e8 without reading this file.

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "suspension.h"   // for the four .sdata globals Suspension owns
#include "wheel.h"
#include "carstate.h"

static void pf(const char *tag, float x)
{
    printf("%s %.9g\n", tag, x);
}

static void pi(const char *tag, int x)
{
    printf("%s %d\n", tag, x);
}

static void pv(const char *tag, const bVector4 *v)
{
    printf("%s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->w);
}

static void pm(const char *tag, const bMatrix4 *m)
{
    const float *p = (const float *)m;
    int j;
    for (j = 0; j < 16; j++)
        printf("%s[%2d] %.9g\n", tag, j, p[j]);
}

// --------------------------------------------------------------- the seams
//
// Stand-ins for the two terrain calls CheckTerrain makes. Both record how
// often they were reached and what they were handed, because the port's
// only claim about the terrain system is the shape of the call.

static int      g_elev_calls;
static void    *g_elev_topology;
static int32_t *g_elev_terrain_out;   // &w->Terrain in the image; proved, not assumed
static float    g_elev_return;
static bVector3 g_elev_normal;
static bVector3 g_elev_pos;

static float fake_get_elevation(void *topology, const bVector3 *pos,
                                int32_t *terrainOut, bVector3 *normalOut)
{
    g_elev_calls++;
    g_elev_topology = topology;
    g_elev_terrain_out = terrainOut;
    g_elev_pos = *pos;
    *normalOut = g_elev_normal;
    // Write something unmistakable through the out-parameter, so a port
    // that drops it shows up as a stale terrain rather than as the 77
    // every caller in the image gets back.
    if (terrainOut)
        *terrainOut = 77;
    return g_elev_return;
}

static int     g_noise_calls;
static int32_t g_noise_terrain;
static float   g_noise_x, g_noise_y;
static float   g_noise_return;

static float fake_road_noise(const bVector2 *xy, int32_t terrain)
{
    g_noise_calls++;
    g_noise_x = xy->x;
    g_noise_y = xy->y;
    g_noise_terrain = terrain;
    return g_noise_return;
}

static void *g_topology = (void *)(size_t)0x1234;
static int   g_topology_calls;

static void *fake_topology_of(void *carState)
{
    (void)carState;
    g_topology_calls++;
    return g_topology;
}

// ------------------------------------------------------ the replay seams
//
// DoSnapshot's only observable behaviour is the sequence of MoveData calls
// and which fields survive the reset, so the fakes record the calls rather
// than serialising anything. The moved addresses are kept raw and turned
// into offsets by the scenario, because the offsets are what has to agree
// with the image and the addresses are not reproducible.

static int    g_rp_begin, g_rp_end, g_rp_float, g_rp_ints, g_rp_reset_calls;
static void  *g_rp_snap;
static char   g_rp_name[64];
static float *g_rp_fp[8];
static int32_t *g_rp_ip;
static int32_t g_rp_n;
static int    g_rp_reset;

static void fake_rp_begin(void *snap, const char *name)
{
    g_rp_begin++;
    g_rp_snap = snap;
    strncpy(g_rp_name, name ? name : "(null)", sizeof g_rp_name - 1);
    g_rp_name[sizeof g_rp_name - 1] = 0;
}

static void fake_rp_end(void *snap)
{
    g_rp_end++;
    g_rp_snap = snap;
}

static void fake_rp_move_float(void *snap, float *q)
{
    g_rp_snap = snap;
    if (g_rp_float < 8)
        g_rp_fp[g_rp_float] = q;
    g_rp_float++;
}

static void fake_rp_move_ints(void *snap, int32_t *q, int32_t n)
{
    g_rp_snap = snap;
    g_rp_ints++;
    g_rp_ip = q;
    g_rp_n = n;
}

static int32_t fake_rp_should_reset(const void *snap)
{
    (void)snap;
    g_rp_reset_calls++;
    return g_rp_reset;
}

static void install_replay_seams(void)
{
    gReplayBeginSectionFn = fake_rp_begin;
    gReplayEndSectionFn   = fake_rp_end;
    gReplayMoveFloatFn    = fake_rp_move_float;
    gReplayMoveIntsFn     = fake_rp_move_ints;
    gReplayShouldResetFn  = fake_rp_should_reset;
}

static void clear_replay_seams(void)
{
    gReplayBeginSectionFn = NULL;
    gReplayEndSectionFn   = NULL;
    gReplayMoveFloatFn    = NULL;
    gReplayMoveIntsFn     = NULL;
    gReplayShouldResetFn  = NULL;
}

static void reset_replay_record(void)
{
    g_rp_begin = g_rp_end = g_rp_float = g_rp_ints = g_rp_reset_calls = 0;
    g_rp_snap = NULL;
    g_rp_name[0] = 0;
    memset(g_rp_fp, 0, sizeof g_rp_fp);
    g_rp_ip = NULL;
    g_rp_n = -1;
}

static void install_terrain_seams(void)
{
    gTopologyGetElevationFn    = fake_get_elevation;
    gTerrainRoadNoiseFn        = fake_road_noise;
    gWheelTopologyOfCarStateFn = fake_topology_of;
}

static void clear_terrain_seams(void)
{
    gTopologyGetElevationFn    = NULL;
    gTerrainRoadNoiseFn        = NULL;
    gWheelTopologyOfCarStateFn = NULL;
}

// A terrain table the wheel can index. Only the four multipliers matter;
// the rest is filled so a stride error walks into a different number
// rather than into another copy of 1.0.
#define NTERRAIN 6
static TerrainTypeInfo g_terrain[NTERRAIN];

static void build_terrain_table(void)
{
    int i;
    memset(g_terrain, 0, sizeof g_terrain);
    for (i = 0; i < NTERRAIN; i++) {
        g_terrain[i].Type = i;
        g_terrain[i].StaticFrictionMultiplier  = 1.0f + 0.25f * (float)i;
        g_terrain[i].DynamicFrictionMultiplier = 0.9f - 0.10f * (float)i;
        g_terrain[i].RollingFrictionMultiplier = 1.0f + 0.50f * (float)i;
        g_terrain[i].RoadNoiseScale = 2.0f + (float)i;
    }
}

// ------------------------------------------------------------- the fixture

static WheelInfo   g_wi;
static TireInfo    g_ti;
static ControlInfo g_ci;
static CarState   *g_cs;

static void build_info(void)
{
    memset(&g_wi, 0, sizeof g_wi);
    g_wi.PositionX   = 1.4f;
    g_wi.PositionY   = 0.78f;
    g_wi.PositionZ   = -0.35f;
    g_wi.Radius      = 0.32f;
    g_wi.Width       = 0.21f;
    g_wi.WheelNumber = 2;              // a rear wheel, so the pilot path runs

    memset(&g_ti, 0, sizeof g_ti);
    g_ti.MaxSlipAngle               = 0.14f;
    g_ti.MaxLoad                    = 5200.0f;
    g_ti.ForceScale                 = 1.15f;
    g_ti.StaticFrictionCoefficient  = 1.05f;
    g_ti.DynamicFrictionCoefficient = 0.85f;

    memset(&g_ci, 0, sizeof g_ci);
    g_ci.Steering = 0.6f;
    g_ci.Brake    = 1.3f;
    g_ci.EBrake   = 0.75f;

    g_cs = (CarState *)calloc(1, sizeof(CarState));
    g_cs->ForwardSpeed = 20.0f;
    g_cs->DriverMode   = 1;
}

static bMatrix4 g_world;   // a wheel leaning a little, with a translation
static bMatrix4 g_car;
static bMatrix4 g_tilted;  // and one whose third row is not (0, 0, 1, 0)

static void build_matrices(void)
{
    bIdentity(&g_world);
    g_world.v0.x = 0.936293435f;   g_world.v0.y = 0.351175636f;
    g_world.v0.z = -0.0174524058f; g_world.v0.w = 0.5f;
    g_world.v1.x = -0.348570138f;  g_world.v1.y = 0.929229140f;
    g_world.v1.z = 0.121869341f;   g_world.v1.w = -0.25f;
    g_world.v2.x = 0.0523359589f;  g_world.v2.y = -0.111618653f;
    g_world.v2.z = 0.992403865f;   g_world.v2.w = 0.75f;
    g_world.v3.x = 11.5f; g_world.v3.y = -3.25f; g_world.v3.z = 0.44f;
    g_world.v3.w = 1.0f;

    bIdentity(&g_car);
    g_car.v0.x = 0.8f;  g_car.v0.y = 0.6f;
    g_car.v1.x = -0.6f; g_car.v1.y = 0.8f;
    g_car.v3.x = 1.4f;  g_car.v3.y = 0.78f; g_car.v3.z = -0.03f;

    bIdentity(&g_tilted);
    g_tilted.v0.x = 0.78f;  g_tilted.v0.y = 0.55f;  g_tilted.v0.z = -0.3f;
    g_tilted.v1.x = -0.61f; g_tilted.v1.y = 0.74f;  g_tilted.v1.z = 0.28f;
    g_tilted.v2.x = 0.1f;   g_tilted.v2.y = -0.2f;  g_tilted.v2.z = 0.97f;
    g_tilted.v2.w = 0.3f;
    g_tilted.v3.x = 2.5f;   g_tilted.v3.y = -1.25f; g_tilted.v3.z = 0.4f;
}

// A wheel in the middle of a frame: everything the force passes read is
// set, so each scenario only has to move the handful it is about.
static Wheel *fresh(void)
{
    static Wheel w;
    memset(&w, 0, sizeof w);
    wheel_init(&w, &g_wi, &g_ti, &g_ci, g_cs);
    wheel_calibrate(&w);

    w.State.a = 0.75f;
    w.State.w = 31.0f;
    w.WorldMatrix = g_world;
    w.CarMatrix = g_car;
    bIdentity(&w.Matrix);
    w.Velocity.x = 12.0f; w.Velocity.y = 0.5f;
    w.Velocity.z = -0.25f; w.Velocity.w = 0.75f;
    w.ContactNormal.x = 0.1f; w.ContactNormal.y = -0.2f;
    w.ContactNormal.z = 0.96f; w.ContactNormal.w = 0.5f;
    w.ContactPoint.x = 1.5f; w.ContactPoint.y = 0.8f;
    w.ContactPoint.z = -0.4f; w.ContactPoint.w = 0.25f;
    w.WorldGroundForce.x = 120.0f; w.WorldGroundForce.y = -45.0f;
    w.WorldGroundForce.z = 310.0f; w.WorldGroundForce.w = 7.0f;
    w.ZForce = 3900.0f;
    w.Terrain = 2;
    w.TouchingGround = 1;
    w.Slipping = 0;
    w.BrakeLocked = 0;
    w.LastSign = 0;
    w.AppliedTorque = 260.0f;
    w.GroundForce[0] = 140.0f;
    w.GroundForce[1] = -220.0f;
    // A slide already recorded, so the gripping arm clearing it is
    // visible, and two grip multipliers that are not 1.0, so every product
    // they appear in is visible too.
    w.Slip[0] = 7.5f;
    w.Slip[1] = -8.5f;
    w.TractionBoost = 1.25f;
    w.CatchupFrictionMultiplier = 0.9f;
    w.MomentOfInertia = gWheelMomentOfInertia;
    return &w;
}

// The whole record, so a scenario cannot write somewhere nobody looks.
static void dump(const char *tag, const Wheel *w)
{
    char b[96];
#define T(s) (sprintf(b, "%s %s", tag, s), b)
    printf("%s vtable %08x\n", tag, (unsigned)w->_vtable);
    pf(T("State.a"), w->State.a);
    pf(T("State.w"), w->State.w);
    pf(T("MomentOfInertia"), w->MomentOfInertia);
    pm(T("Matrix"), &w->Matrix);
    pm(T("WorldMatrix"), &w->WorldMatrix);
    pm(T("CarMatrix"), &w->CarMatrix);
    pv(T("Velocity"), &w->Velocity);
    pf(T("Slip0"), w->Slip[0]);
    pf(T("Slip1"), w->Slip[1]);
    pf(T("AppliedTorque"), w->AppliedTorque);
    pi(T("BrakeLocked"), (int)w->BrakeLocked);
    pi(T("LastSign"), (int)w->LastSign);
    pf(T("GroundForce0"), w->GroundForce[0]);
    pf(T("GroundForce1"), w->GroundForce[1]);
    pv(T("WorldGroundForce"), &w->WorldGroundForce);
    pv(T("ContactPoint"), &w->ContactPoint);
    pv(T("ContactNormal"), &w->ContactNormal);
    pi(T("Terrain"), (int)w->Terrain);
    pi(T("Slipping"), (int)w->Slipping);
    pi(T("TouchingGround"), (int)w->TouchingGround);
    pi(T("NumTimesSkidding"), (int)w->NumTimesSkidding);
    pf(T("ZForce"), w->ZForce);
    pf(T("RoadNoise"), w->RoadNoise);
    pf(T("CurrentSlip"), w->CurrentSlip);
    pf(T("OldSlip"), w->OldSlip);
    pf(T("TractionUsage"), w->TractionUsage);
    pf(T("Damage"), w->Damage);
    pf(T("Brake"), w->Brake);
    pf(T("EBrake"), w->EBrake);
    pf(T("TractionBoost"), w->TractionBoost);
    pf(T("CatchupFriction"), w->CatchupFrictionMultiplier);
#undef T
}

// ------------------------------------------------------------- the layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("ptr %zu\n", sizeof(void *));
    printf("slack %zu\n", WHEEL_SLACK);
    printf("sizeof Wheel %zu\n", sizeof(Wheel));
    printf("sizeof expected %zu\n", WHEEL_SIZEOF);
    printf("sizeof WheelState %zu\n", sizeof(WheelState));
    printf("sizeof SkidMaker %zu\n", sizeof(SkidMaker));
    printf("sizeof WheelInfo %zu\n", sizeof(WheelInfo));
    printf("sizeof TireInfo %zu\n", sizeof(TireInfo));
    printf("sizeof ControlInfo %zu\n", sizeof(ControlInfo));
    printf("sizeof TerrainTypeInfo %zu\n", sizeof(TerrainTypeInfo));
    printf("sizeof terraininfo expected %zu\n", TERRAININFO_SIZEOF);

#define OFF(t, f) printf("off %-28s %zu\n", #t "." #f, offsetof(t, f))
    OFF(Wheel, pNext);
    OFF(Wheel, pPrev);
    OFF(Wheel, _vtable);
    OFF(Wheel, WI);
    OFF(Wheel, TI);
    OFF(Wheel, CI);
    OFF(Wheel, CS);
    OFF(Wheel, State);
    OFF(Wheel, MomentOfInertia);
    OFF(Wheel, Matrix);
    OFF(Wheel, WorldMatrix);
    OFF(Wheel, CarMatrix);
    OFF(Wheel, Velocity);
    OFF(Wheel, Slip);
    OFF(Wheel, AppliedTorque);
    OFF(Wheel, BrakeLocked);
    OFF(Wheel, LastSign);
    OFF(Wheel, GroundForce);
    OFF(Wheel, WorldGroundForce);
    OFF(Wheel, ContactPoint);
    OFF(Wheel, ContactNormal);
    OFF(Wheel, Terrain);
    OFF(Wheel, Slipping);
    OFF(Wheel, TouchingGround);
    OFF(Wheel, NumTimesSkidding);
    OFF(Wheel, ZForce);
    OFF(Wheel, RoadNoise);
    OFF(Wheel, CurrentSlip);
    OFF(Wheel, OldSlip);
    OFF(Wheel, TractionUsage);
    OFF(Wheel, Damage);
    OFF(Wheel, Brake);
    OFF(Wheel, EBrake);
    OFF(Wheel, TractionBoost);
    OFF(Wheel, CatchupFrictionMultiplier);
    OFF(Wheel, TheSkidMaker);

    OFF(TerrainTypeInfo, Name);
    OFF(TerrainTypeInfo, NameHash);
    OFF(TerrainTypeInfo, Type);
    OFF(TerrainTypeInfo, SkidTextureName);
    OFF(TerrainTypeInfo, RoadNoiseGridSpacingInverse);
    OFF(TerrainTypeInfo, RoadNoiseScale);
    OFF(TerrainTypeInfo, StaticFrictionMultiplier);
    OFF(TerrainTypeInfo, DynamicFrictionMultiplier);
    OFF(TerrainTypeInfo, RollingFrictionMultiplier);
    OFF(TerrainTypeInfo, CollisionScrapeMaxSpeed);

    // WheelState's own two floats. Nothing else pins their order: every
    // access in the port is by name, so a swapped declaration would move
    // both fields and still read correctly from the new places.
    printf("off %-28s %zu\n", "WheelState.a", offsetof(WheelState, a));
    printf("off %-28s %zu\n", "WheelState.w", offsetof(WheelState, w));
#undef OFF

    // The extents, because offsets alone do not pin them.
    printf("arr Slip %zu\n", sizeof(((Wheel *)0)->Slip));
    printf("arr GroundForce %zu\n", sizeof(((Wheel *)0)->GroundForce));
    printf("arr w_pad0 %zu\n", sizeof(((Wheel *)0)->_pad0));
    printf("arr w_pad1 %zu\n", sizeof(((Wheel *)0)->_pad1));
    printf("arr w_pad2 %zu\n", sizeof(((Wheel *)0)->_pad2));

    printf("vtable Wheel %08x\n", (unsigned)WHEEL_VTABLE);
    printf("vtable PhysicsComponent %08x\n", (unsigned)PHYSICSCOMPONENT_VTABLE);
    printf("state floats %d\n", WHEEL_STATE_FLOATS);
    printf("cornering entries %d\n", WHEEL_CORNERING_ENTRIES);
    printf("load entries %d\n", WHEEL_LOAD_TABLE_ENTRIES);
    printf("load tables %d\n", WHEEL_NUM_LOAD_TABLES);
}

// The tuning block, printed under a caller-chosen tag. `constants` prints
// it once at the start; `accessors` prints it again straight after
// SetSliderValue, which is the only way a port that gave that empty
// function a body writing one of these would ever be noticed.
static void dump_globals(const char *tag)
{
    char b[96];
    sprintf(b, "%s WheelMomentOfInertia", tag);
    pf(b, gWheelMomentOfInertia);
    sprintf(b, "%s RollingFriction", tag);
    pf(b, gRollingFriction);
    sprintf(b, "%s MaxStaticSlip", tag);
    pf(b, gMaxStaticSlip);
    sprintf(b, "%s BrakingTorque", tag);
    pf(b, gBrakingTorque);
    sprintf(b, "%s EBrakingTorque", tag);
    pf(b, gEBrakingTorque);
    sprintf(b, "%s StaticToDynamicBrakeForceRatio", tag);
    pf(b, gStaticToDynamicBrakeForceRatio);
    sprintf(b, "%s BrakeLockAngularVelocityFactor", tag);
    pf(b, gBrakeLockAngularVelocityFactor);
    sprintf(b, "%s ZForceScale", tag);
    pf(b, gZForceScale);
    sprintf(b, "%s PilotFactor", tag);
    pf(b, gPilotFactor);
    sprintf(b, "%s WheelDebugInfo", tag);
    pi(b, gWheelDebugInfo);
    sprintf(b, "%s CorneringScale", tag);
    pf(b, gCorneringScale);
    sprintf(b, "%s UseNewTireForces", tag);
    pi(b, gUseNewTireForces);
    sprintf(b, "%s NewCorneringScale", tag);
    pf(b, gNewCorneringScale);
    sprintf(b, "%s LoadFactor", tag);
    pf(b, gLoadFactor);
    sprintf(b, "%s WheelForceFrame", tag);
    pi(b, gWheelForceFrame);
    sprintf(b, "%s TireForceEllipseRatio", tag);
    pf(b, gTireForceEllipseRatio);
    sprintf(b, "%s UglyTimestepHack", tag);
    pf(b, gUglyTimestepHack);
}

static void scenario_constants(void)
{
    printf("[constants]\n");
    pf("k PI", WHEEL_IMAGE_PI);
    pf("k TWO_PI", WHEEL_IMAGE_TWO_PI);
    pf("k HALF_PI", WHEEL_IMAGE_HALF_PI);
    pf("k BAM_TO_RAD", WHEEL_BAM_TO_RAD);
    pf("k ROT_FOLD", WHEEL_ROT_FOLD);
    pf("k ROT_GIVE_UP", WHEEL_ROT_GIVE_UP);
    pf("k SPIN_EPSILON", WHEEL_SPIN_EPSILON);
    pf("k ZFORCE_FLOOR", WHEEL_ZFORCE_FLOOR);
    pf("k EPSILON", WHEEL_EPSILON);
    pf("k REVERSE_DAMP", WHEEL_REVERSE_DAMP);
    pf("k PILOT_SPEED", WHEEL_PILOT_SPEED);
    pf("k PILOT_INV_SPAN", WHEEL_PILOT_INV_SPAN);
    pf("k MPS_TO_MPH", WHEEL_MPS_TO_MPH);
    pf("k RAD_TO_DEG", WHEEL_RAD_TO_DEG);
    pf("k NO_SURFACE", WHEEL_NO_SURFACE);

    dump_globals("g");
}

// ------------------------------------------------------------ the statics

static const float g_table_args[] = {
    -1.0f, 0.0f, 0.001f, 0.05f, 0.1117010859f, 0.2f, 0.223402172f,
    0.3f, 1.0f, 2.5f, 5.0f, 7.5f, 9.999f, 10.0f, 11.0f
};
#define NARGS ((int)(sizeof g_table_args / sizeof g_table_args[0]))

static void scenario_statics(void)
{
    int t, k;

    printf("[statics]\n");
    pf("maxslip", gMaxSlipAngleGlobal);
    pf("cf min", gCorneringForce.MinArg);
    pf("cf max", gCorneringForce.MaxArg);
    pf("cf mult", gCorneringForce.IndexMultiplier);
    pi("cf n", gCorneringForce.NumEntries);
    printf("cf same %d\n", gCorneringForce.pTable == gCorneringForceTable);
    for (k = 0; k < WHEEL_CORNERING_ENTRIES; k++)
        pf("cf entry", gCorneringForceTable[k]);
    for (k = 0; k < NARGS; k++)
        pf("cf value", table_get_value(&gCorneringForce, g_table_args[k]));

    for (t = 0; t < WHEEL_NUM_LOAD_TABLES; t++) {
        printf("ls %d same %d\n", t,
               gLoadSensitivityTable[t] == &gLoadSensitivity[t]);
        pf("ls min", gLoadSensitivity[t].MinArg);
        pf("ls max", gLoadSensitivity[t].MaxArg);
        pf("ls mult", gLoadSensitivity[t].IndexMultiplier);
        pi("ls n", gLoadSensitivity[t].NumEntries);
        for (k = 0; k < WHEEL_LOAD_TABLE_ENTRIES; k++)
            pf("ls entry", gLoadSensitivity[t].pTable[k]);
        for (k = 0; k < NARGS; k++)
            pf("ls value",
               table_get_value(gLoadSensitivityTable[t], g_table_args[k]));
    }
}

// --------------------------------------------------------------- lifetime

static void scenario_lifetime(void)
{
    static Wheel w;
    float st[2];

    printf("[lifetime]\n");

    // calloc's view, so every field Init does not write shows as zero.
    memset(&w, 0, sizeof w);
    wheel_init(&w, &g_wi, &g_ti, &g_ci, g_cs);
    dump("init", &w);
    printf("init WI %d\n", w.WI == &g_wi);
    printf("init TI %d\n", w.TI == &g_ti);
    printf("init CI %d\n", w.CI == &g_ci);
    printf("init CS %d\n", w.CS == (void *)g_cs);
    printf("init skidset %d\n", w.TheSkidMaker.pSkidSet == NULL);

    wheel_calibrate(&w);
    pf("calibrate moi", w.MomentOfInertia);

    pi("size", wheel_get_size(&w));
    printf("getstate %d\n", wheel_get_state(&w) == &w.State);

    wheel_set_state2(&w, 1.25f, -8.5f);
    pf("set2 a", w.State.a);
    pf("set2 w", w.State.w);
    wheel_set_state_w(&w, 3.75f);
    pf("setw a", w.State.a);
    pf("setw w", w.State.w);
    st[0] = 0.0f; st[1] = 0.0f;
    wheel_get_state_array(&w, st);
    pf("getarr 0", st[0]);
    pf("getarr 1", st[1]);
    st[0] = -2.5f; st[1] = 17.0f;
    wheel_set_state_array(&w, st);
    pf("setarr a", w.State.a);
    pf("setarr w", w.State.w);

    wheel_fini(&w);
    printf("fini vtable %08x\n", (unsigned)w._vtable);
}

// ------------------------------------------------------- ComputeAuxiliaries

static void scenario_compute_aux(void)
{
    // rotation, spin, LastSign -- the folds, the three-way sign memory and
    // the clamp that stops a wheel crossing zero inside one frame.
    static const float rots[] = {
        0.75f, 0.0f, -0.4f, 700.0f, 6912.0f, -700.0f, -6912.0f,
        628.317993f, 628.318f, 629.0f, -628.317993f
    };
    static const float spins[] = {
        31.0f, -31.0f, 0.0f, 9.99999975e-06f, -9.99999975e-06f,
        1.0e-05f, -1.0e-05f
    };
    static const int signs[] = { 0, 1, 2, 3 };
    size_t r, s, g;
    char tag[64];

    printf("[compute_aux]\n");
    for (r = 0; r < sizeof rots / sizeof rots[0]; r++) {
        for (s = 0; s < sizeof spins / sizeof spins[0]; s++) {
            for (g = 0; g < sizeof signs / sizeof signs[0]; g++) {
                Wheel *w = fresh();
                sprintf(tag, "ca%u_%u_%u", (unsigned)r, (unsigned)s,
                        (unsigned)g);
                w->State.a = rots[r];
                w->State.w = spins[s];
                w->LastSign = signs[g];
                wheel_compute_auxiliaries(w);
                pf(tag, w->State.a);
                printf("%s w %.9g\n", tag, w->State.w);
                printf("%s sign %d\n", tag, (int)w->LastSign);
            }
        }
    }

    // One full dump, so the matrix and the four cleared accumulators are
    // pinned and not just the three fields above.
    {
        Wheel *w = fresh();
        w->State.a = 0.75f;
        w->State.w = 31.0f;
        w->LastSign = 1;
        w->CurrentSlip = 4.5f;
        wheel_compute_auxiliaries(w);
        dump("ca_full", w);
    }
}

// ---------------------------------------------------------- ExchangeZForces

static void scenario_exchange(void)
{
    // -0.0f is the one that separates `!(0.0f < z)` from `z < 0.0f`.
    // Both send every other input the same way; at negative zero the
    // first is airborne and stores a clean +0, and the second falls
    // into the loaded arm and stores -0.0f * d, which is -0. `%.9g`
    // prints the sign, so the two are one line apart in the diff.
    static const float zs[] = { 0.0f, -0.0f, -1.0f, 1.0e-30f, 4200.0f,
                                12000.0f };
    // Normals from square-under-the-wheel to fully on its side, so the
    // affine map and its 0.3 floor are both crossed.
    static const float nz[] = { 1.0f, 0.99f, 0.9f, 0.8f, 0.5f, 0.0f, -0.6f };
    size_t z, t, n;
    char tag[64];

    printf("[exchange]\n");
    for (t = 0; t < 2; t++) {
        for (z = 0; z < sizeof zs / sizeof zs[0]; z++) {
            for (n = 0; n < sizeof nz / sizeof nz[0]; n++) {
                Wheel *w = fresh();
                float ret;
                w->ContactNormal.x = 0.0f;
                w->ContactNormal.y =
                    (float)sqrt(1.0 - (double)nz[n] * (double)nz[n]);
                w->ContactNormal.z = nz[n];
                w->ContactNormal.w = 0.5f;
                ret = wheel_exchange_z_forces(w, (int32_t)t, zs[z]);
                sprintf(tag, "ex%u_%u_%u", (unsigned)t, (unsigned)z,
                        (unsigned)n);
                pf(tag, ret);
                printf("%s zf %.9g\n", tag, w->ZForce);
                printf("%s tg %d\n", tag, (int)w->TouchingGround);
                printf("%s cp %.9g %.9g %.9g %.9g\n", tag,
                       w->ContactPoint.x, w->ContactPoint.y,
                       w->ContactPoint.z, w->ContactPoint.w);
            }
        }
    }
}

// ------------------------------------------------------------- CheckTerrain

static void scenario_check_terrain(void)
{
    static const float elevs[] = { 0.0f, 0.44f, 1.5f, -2.0f };
    static const float noises[] = { 0.0f, 0.03f, -0.11f };
    // The third faces away from the wheel's z axis, which is the reject.
    // The fourth is inside WHEEL_EPSILON but still positive, so the reject
    // is decided by the epsilon and not by the sign. The fifth has two
    // huge opposed terms and a small one, which is where the dot product's
    // left-to-right association stops being a detail.
    static const float normals[5][3] = {
        { 0.0f, 0.0f, 1.0f },
        { 0.3f, -0.2f, 0.9327379f },
        { 0.9f, 0.4358899f, 0.0f },
        { 0.9f, 0.42f, 0.0f },
        { 1.91073e8f, 8.95907e7f, 0.00100765f },
    };
    size_t e, n, k;
    char tag[64];

    printf("[check_terrain]\n");
    install_terrain_seams();
    for (k = 0; k < 5; k++) {
        for (e = 0; e < sizeof elevs / sizeof elevs[0]; e++) {
            for (n = 0; n < sizeof noises / sizeof noises[0]; n++) {
                Wheel *w = fresh();
                bVector4 pos;
                float h;
                g_elev_calls = g_noise_calls = g_topology_calls = 0;
                g_elev_terrain_out = (int32_t *)(size_t)0xdead;
                g_elev_return = elevs[e];
                g_elev_normal.x = normals[k][0];
                g_elev_normal.y = normals[k][1];
                g_elev_normal.z = normals[k][2];
                g_elev_normal.pad = 0.25f;
                g_noise_return = noises[n];
                pos.x = 11.5f; pos.y = -3.25f; pos.z = 0.44f; pos.w = 1.0f;

                h = wheel_find_driving_surface(w, &pos, &g_world);
                sprintf(tag, "ct%u_%u_%u", (unsigned)k, (unsigned)e,
                        (unsigned)n);
                pf(tag, h);
                printf("%s terrain %d\n", tag, (int)w->Terrain);
                printf("%s noise %.9g\n", tag, w->RoadNoise);
                printf("%s calls %d %d %d\n", tag, g_elev_calls,
                       g_noise_calls, g_topology_calls);
                printf("%s terrain_out_null %d\n", tag,
                       g_elev_terrain_out == NULL);
                printf("%s noise_terrain %d\n", tag, (int)g_noise_terrain);
                printf("%s noise_xy %.9g %.9g\n", tag, g_noise_x, g_noise_y);
                printf("%s pos %.9g %.9g %.9g\n", tag,
                       g_elev_pos.x, g_elev_pos.y, g_elev_pos.z);
                printf("%s topology %d\n", tag, g_elev_topology == g_topology);
                printf("%s normal %.9g %.9g %.9g %.9g\n", tag,
                       w->ContactNormal.x, w->ContactNormal.y,
                       w->ContactNormal.z, w->ContactNormal.w);
            }
        }
    }

    // And with both seams gone, which is the handheld before task 27.
    clear_terrain_seams();
    {
        Wheel *w = fresh();
        bVector4 pos;
        float h;
        pos.x = 11.5f; pos.y = -3.25f; pos.z = 0.44f; pos.w = 1.0f;
        h = wheel_find_driving_surface(w, &pos, &g_world);
        pf("ct_null", h);
        printf("ct_null terrain %d\n", (int)w->Terrain);
        printf("ct_null noise %.9g\n", w->RoadNoise);
        printf("ct_null normal %.9g %.9g %.9g %.9g\n",
               w->ContactNormal.x, w->ContactNormal.y,
               w->ContactNormal.z, w->ContactNormal.w);
    }
    install_terrain_seams();
}

// ------------------------------------------------------------ GetDerivative

static void scenario_derivative(void)
{
    static const float spins[] = { 31.0f, -31.0f, 0.0f };
    static const float slips[] = { 0.0f, 0.4f, -0.9f };
    size_t s, c, locked, slipping, table;
    char tag[64];

    printf("[derivative]\n");
    for (table = 0; table < 2; table++) {
        gTerrainTypeInfoTable = table ? g_terrain : NULL;
        for (s = 0; s < sizeof spins / sizeof spins[0]; s++) {
            for (c = 0; c < sizeof slips / sizeof slips[0]; c++) {
                for (locked = 0; locked < 2; locked++) {
                    for (slipping = 0; slipping < 2; slipping++) {
                        Wheel *w = fresh();
                        float out[2] = { -7.0f, -7.0f };
                        float *r;
                        w->State.w = spins[s];
                        w->CurrentSlip = slips[c];
                        w->BrakeLocked = (int32_t)locked;
                        w->Slipping = (uint8_t)slipping;
                        w->Terrain = 3;
                        r = wheel_get_derivative(w, out);
                        sprintf(tag, "dv%u_%u_%u_%u_%u", (unsigned)table,
                                (unsigned)s, (unsigned)c, (unsigned)locked,
                                (unsigned)slipping);
                        printf("%s ret %d\n", tag, r == NULL);
                        pf(tag, out[0]);
                        printf("%s d1 %.9g\n", tag, out[1]);
                    }
                }
            }
        }
    }
    gTerrainTypeInfoTable = g_terrain;

    // The epsilon guard, which the shipped hack of 1.0 never fails.
    {
        static const float hacks[] = { 1.0f, 0.001f, 0.0005f, 0.0f, 2.0f };
        size_t h;
        float saved = gUglyTimestepHack;
        for (h = 0; h < sizeof hacks / sizeof hacks[0]; h++) {
            Wheel *w = fresh();
            float out[2] = { 0.0f, 0.0f };
            gUglyTimestepHack = hacks[h];
            w->CurrentSlip = 0.4f;
            wheel_get_derivative(w, out);
            sprintf(tag, "dvh%u", (unsigned)h);
            pf(tag, out[1]);
        }
        gUglyTimestepHack = saved;
    }
}

// ------------------------------------------------ CheckForBrakeLock, pilot

static void scenario_brake_lock(void)
{
    static const float vs[] = { 0.0f, 1.0f, 40.0f, 400.0f, 4000.0f };
    static const float brakes[] = { 0.0f, 0.02f, 0.25f, 1.0f };
    static const float spins[] = { 31.0f, -31.0f, 0.0f };
    size_t v, b, e, s;
    char tag[64];

    printf("[brake_lock]\n");
    for (v = 0; v < sizeof vs / sizeof vs[0]; v++) {
        for (b = 0; b < sizeof brakes / sizeof brakes[0]; b++) {
            for (e = 0; e < sizeof brakes / sizeof brakes[0]; e++) {
                for (s = 0; s < sizeof spins / sizeof spins[0]; s++) {
                    Wheel *w = fresh();
                    w->Brake = brakes[b];
                    w->EBrake = brakes[e];
                    w->State.w = spins[s];
                    wheel_check_for_brake_lock(w, vs[v]);
                    sprintf(tag, "bl%u_%u_%u_%u", (unsigned)v, (unsigned)b,
                            (unsigned)e, (unsigned)s);
                    printf("%s locked %d\n", tag, (int)w->BrakeLocked);
                    pf(tag, w->State.w);
                }
            }
        }
    }
}

static void scenario_pilot(void)
{
    static const float speeds[] = {
        0.0f, 13.4108181f, 13.4229679f, 14.0f, 20.0f, 22.351f,
        22.3527927f, 30.0f, -5.0f,
        // t comes out 0.0147753973 here, which is one of the inputs where
        // the blend rounds differently in float than in double. Without it
        // the whole speeds[] list agrees either way and the fptodp/dptofp
        // pair the image emits is unobservable.
        13.5429182f
    };
    size_t s, n;
    char tag[64];

    printf("[pilot]\n");
    for (n = 0; n < 4; n++) {
        for (s = 0; s < sizeof speeds / sizeof speeds[0]; s++) {
            Wheel *w = fresh();
            g_wi.WheelNumber = (int32_t)n;
            g_cs->ForwardSpeed = speeds[s];
            sprintf(tag, "pf%u_%u", (unsigned)n, (unsigned)s);
            pf(tag, wheel_get_pilot_factor(w));
        }
    }
    g_wi.WheelNumber = 2;
    g_cs->ForwardSpeed = 20.0f;

    // The two refusals in front of the wheel number.
    {
        Wheel *w = fresh();
        w->BrakeLocked = 1;
        pf("pf_locked", wheel_get_pilot_factor(w));
    }
    {
        Wheel *w = fresh();
        w->State.w = -0.5f;
        pf("pf_reverse", wheel_get_pilot_factor(w));
    }
    {
        Wheel *w = fresh();
        w->State.w = 0.0f;
        pf("pf_stopped", wheel_get_pilot_factor(w));
    }
}

// ---------------------------------------------------------- GetLateralForce

static void scenario_lateral(void)
{
    // The first eight walk the index from 0 to just past 6 in steps of
    // about one, which is the only way the i < 6 ceiling, the truncation
    // and the interpolation between two neighbouring curves are reached at
    // all: every angle a car actually produces lands far past the end.
    static const float angles[] = {
        0.0f, 0.000222f, 0.000445f, 0.00089f, 0.00134f, 0.00178f,
        0.00222f, 0.00245f, 0.00266f,
        0.01f, 0.0223402f, 0.05f, 0.1f, 0.14f, 0.2f, 0.223402172f,
        0.3f, 0.5f, 1.0f
    };
    static const float zf[] = { 0.0f, 1200.0f, 5200.0f, 9000.0f };
    size_t a, z, model;
    char tag[64];
    int32_t saved = gUseNewTireForces;

    printf("[lateral]\n");
    for (model = 0; model < 2; model++) {
        gUseNewTireForces = (int32_t)model;
        for (z = 0; z < sizeof zf / sizeof zf[0]; z++) {
            for (a = 0; a < sizeof angles / sizeof angles[0]; a++) {
                Wheel *w = fresh();
                sprintf(tag, "lf%u_%u_%u", (unsigned)model, (unsigned)z,
                        (unsigned)a);
                pf(tag, wheel_get_lateral_force(w, zf[z], angles[a]));
            }
        }
    }
    gUseNewTireForces = saved;
}

// --------------------------------------------------------- GuessGroundForce

static void scenario_guess(void)
{
    // Velocities that reach each of the early-outs, each slipping trigger
    // and the low-speed divide; brakes that reach the torque refusals.
    static const float vx[] = { 12.0f, 0.4f, 0.0f, -12.0f, -0.05f };
    static const float vy[] = { 0.5f, 0.0f, -3.0f };
    static const float spins[] = { 37.5f, 0.0f, -10.0f, 1.25f };
    static const float brakes[] = { 0.0f, 0.4f };
    static const float speeds[] = { 20.0f, 0.2f };
    size_t a, b, s, k, e, f;
    bVector2 unused;
    char tag[96];

    printf("[guess]\n");
    unused.x = 99.0f;
    unused.y = -99.0f;
    gTerrainTypeInfoTable = g_terrain;

    for (a = 0; a < sizeof vx / sizeof vx[0]; a++) {
        for (b = 0; b < sizeof vy / sizeof vy[0]; b++) {
            for (s = 0; s < sizeof spins / sizeof spins[0]; s++) {
                for (k = 0; k < 2; k++) {
                    for (e = 0; e < 2; e++) {
                        for (f = 0; f < 2; f++) {
                            Wheel *w = fresh();
                            // The velocity is in world axes and the
                            // function puts it into the wheel's own frame,
                            // so an identity is used here to let vx and vy
                            // be chosen directly. The rotated case is
                            // below.
                            bIdentity(&w->WorldMatrix);
                            w->Velocity.x = vx[a];
                            w->Velocity.y = vy[b];
                            w->Velocity.z = 0.0f;
                            w->Velocity.w = 0.0f;
                            w->State.w = spins[s];
                            w->Brake = brakes[k];
                            w->EBrake = brakes[e];
                            g_cs->ForwardSpeed = speeds[f];
                            wheel_guess_ground_force(w, &unused);
                            sprintf(tag, "gg%u_%u_%u_%u_%u_%u", (unsigned)a,
                                    (unsigned)b, (unsigned)s, (unsigned)k,
                                    (unsigned)e, (unsigned)f);
                            printf("%s gf %.9g %.9g\n", tag,
                                   w->GroundForce[0], w->GroundForce[1]);
                            printf("%s slip %.9g %.9g\n", tag,
                                   w->Slip[0], w->Slip[1]);
                            printf("%s cur %.9g %.9g\n", tag,
                                   w->CurrentSlip, w->OldSlip);
                            printf("%s at %.9g\n", tag, w->AppliedTorque);
                            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                                   (int)w->BrakeLocked);
                            printf("%s spin %.9g\n", tag, w->State.w);
                        }
                    }
                }
            }
        }
    }
    g_cs->ForwardSpeed = 20.0f;

    // The reverse-damp arm, which needs a negative torque, no handbrake
    // and a slip past -gMaxStaticSlip all at once.
    {
        static const float ats[] = { -400.0f, 400.0f, 0.0f };
        size_t t, eb;
        for (t = 0; t < 3; t++) {
            for (eb = 0; eb < 2; eb++) {
                Wheel *w = fresh();
                bIdentity(&w->WorldMatrix);
                w->Velocity.x = 12.0f;
                w->Velocity.y = 0.1f;
                w->Velocity.z = 0.0f;
                w->Velocity.w = 0.0f;
                w->State.w = 0.0f;
                w->AppliedTorque = ats[t];
                w->EBrake = eb ? 0.5f : 0.0f;
                wheel_guess_ground_force(w, &unused);
                sprintf(tag, "gr%u_%u", (unsigned)t, (unsigned)eb);
                printf("%s at %.9g\n", tag, w->AppliedTorque);
                printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                       w->GroundForce[1]);
            }
        }
    }

    // The friction circle small enough to matter. With the shipped
    // ZForce every demand CheckForBrakeLock sees is thousands of newtons
    // and no brake setting can lock anything, so the whole locked half of
    // this function -- the two torque refusals, the locked slipping
    // trigger, and which speed the per-newton scale is taken against --
    // is unreachable until the wheel is barely loaded.
    //
    // spin 32.5 against vx 12 puts the slip at 10, twenty-five times the
    // road speed, which is where dividing by the slide magnitude instead
    // of the road speed stops agreeing.
    //
    // This comment used to claim vx 0.4 with spin 1.25 put the slip at
    // exactly zero and so reached the zero-magnitude early-out. It does
    // not: 1.25 * 0.32f is 0.399999976, which leaves a slip of -2.98e-08
    // and a magnitude to match. The guard was never reached from here at
    // all, and the mutation that deletes it survived the first full pass
    // because of it. The pair that does reach it is in the `gm` block
    // below.
    {
        static const float gvx[] = { 0.4f, 12.0f };
        static const float gvy[] = { 0.0f, -3.0f };
        static const float gspin[] = { 1.25f, 32.5f };
        static const float gzf[] = { 3900.0f, 5.0f };
        static const float gbk[] = { 0.0f, 0.05f, 0.4f };
        size_t a2, b2, s2, z2, k2, l2;
        for (a2 = 0; a2 < 2; a2++)
        for (b2 = 0; b2 < 2; b2++)
        for (s2 = 0; s2 < 2; s2++)
        for (z2 = 0; z2 < 2; z2++)
        for (k2 = 0; k2 < 3; k2++)
        for (l2 = 0; l2 < 2; l2++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = gvx[a2];
            w->Velocity.y = gvy[b2];
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            w->State.w = gspin[s2];
            w->ZForce = gzf[z2];
            w->Brake = gbk[k2];
            w->EBrake = gbk[k2];
            w->BrakeLocked = (int32_t)l2;
            wheel_guess_ground_force(w, &unused);
            sprintf(tag, "gz%u_%u_%u_%u_%u_%u", (unsigned)a2, (unsigned)b2,
                    (unsigned)s2, (unsigned)z2, (unsigned)k2, (unsigned)l2);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s slip %.9g %.9g\n", tag, w->Slip[0], w->Slip[1]);
            printf("%s cur %.9g %.9g\n", tag, w->CurrentSlip, w->OldSlip);
            printf("%s at %.9g\n", tag, w->AppliedTorque);
            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                   (int)w->BrakeLocked);
            printf("%s spin %.9g\n", tag, w->State.w);
        }
    }

    // mag == 0, which is the first early-out and the only guard between
    // GuessGroundForce and a divide by zero. 37.5 * 0.32f is 12 with no
    // rounding at all, so slip is exactly zero; vy is zero, so the
    // magnitude is too; and vx is still 12, so the *second* early-out --
    // vy and vx both zero -- does not fire and cannot stand in for it.
    //
    // perMag is read only on the slipping arm, so each direction is run
    // both loaded-and-free and barely-loaded-and-braked. Free, the wheel
    // grips and maxForce/0 is computed and never used. Braked at 5N of
    // load, CheckForBrakeLock locks the wheel, the slipping arm runs, and
    // the infinity reaches GroundForce. Dragged backwards the slip angle
    // folds to about pi, which is past MaxSlipAngle, so that direction
    // slips whatever the brakes are doing.
    {
        static const float mzspin[] = { 37.5f, -37.5f };
        static const float mzvx[]   = { 12.0f, -12.0f };
        static const float mzzf[]   = { 3900.0f, 5.0f };
        static const float mzbk[]   = { 0.0f, 0.4f };
        size_t d2, q2;
        for (d2 = 0; d2 < 2; d2++)
        for (q2 = 0; q2 < 2; q2++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = mzvx[d2];
            w->Velocity.y = 0.0f;
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            w->State.w = mzspin[d2];
            w->ZForce = mzzf[q2];
            w->Brake = mzbk[q2];
            w->EBrake = mzbk[q2];
            wheel_guess_ground_force(w, &unused);
            sprintf(tag, "gm%u_%u", (unsigned)d2, (unsigned)q2);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s slip %.9g %.9g\n", tag, w->Slip[0], w->Slip[1]);
            printf("%s cur %.9g\n", tag, w->CurrentSlip);
            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                   (int)w->BrakeLocked);
        }
    }

    // |slip| exactly gMaxStaticSlip, with the slip angle small enough that
    // the trigger is the only thing that decides. The pair below it uses a
    // vy of -3 against a vx of 0, which puts the angle far past
    // MaxSlipAngle and sets Slipping on the *second* test whichever way
    // the first one goes -- so it pins the equality for CurrentSlip but
    // not for the branch, and `<` versus `<=` survived it.
    //
    // 1.75 * 0.32f is 0.560000002, and 0.06f subtracts off it to exactly
    // 0.5; spin 0 against vx 0.5f gives exactly -0.5. Both keep vy at zero
    // and vx positive, so the angle is zero and the brakes are off.
    {
        static const float tbspin[] = { 1.75f, 0.0f };
        static const float tbvx[]   = { 0.06f, 0.5f };
        size_t d3;
        for (d3 = 0; d3 < 2; d3++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = tbvx[d3];
            w->Velocity.y = 0.0f;
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            w->State.w = tbspin[d3];
            w->Brake = 0.0f;
            w->EBrake = 0.0f;
            wheel_guess_ground_force(w, &unused);
            sprintf(tag, "gt%u", (unsigned)d3);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s cur %.9g\n", tag, w->CurrentSlip);
            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                   (int)w->BrakeLocked);
        }
    }

    // |slip| exactly gMaxStaticSlip. 1.5625 * 0.32 is 0.5 with no rounding
    // at all, so the trigger's `<` is decided on equality and nothing else.
    {
        static const float sspin[] = { 1.5625f, -1.5625f };
        size_t i2;
        for (i2 = 0; i2 < 2; i2++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = 0.0f;
            w->Velocity.y = -3.0f;
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            w->State.w = sspin[i2];
            wheel_guess_ground_force(w, &unused);
            sprintf(tag, "gs%u", (unsigned)i2);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s cur %.9g\n", tag, w->CurrentSlip);
            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                   (int)w->BrakeLocked);
        }
    }

    // The walking-pace divide, with a friction coefficient on each side of
    // the 0.1 floor that guards it. A traction boost of 0.05 takes the
    // product below the floor without touching anything else.
    {
        static const float boosts[] = { 1.25f, 0.05f };
        size_t i2;
        for (i2 = 0; i2 < 2; i2++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = 0.0f;
            w->Velocity.y = -3.0f;
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            w->State.w = 10.0f;            // slip 3.2, well past the trigger
            w->TractionBoost = boosts[i2];
            g_cs->ForwardSpeed = 0.2f;
            wheel_guess_ground_force(w, &unused);
            sprintf(tag, "gd%u", (unsigned)i2);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s flags %d %d\n", tag, (int)w->Slipping,
                   (int)w->BrakeLocked);
        }
        g_cs->ForwardSpeed = 20.0f;
    }

    // Four with a real world matrix, so the transpose and both folds in
    // the slip angle are exercised rather than stepped over.
    {
        static const float vys[] = { 3.0f, -3.0f };
        static const float vxs[] = { 9.0f, -9.0f };
        size_t i, j;
        for (i = 0; i < 2; i++) {
            for (j = 0; j < 2; j++) {
                Wheel *w = fresh();
                w->Velocity.x = vxs[i];
                w->Velocity.y = vys[j];
                w->Velocity.z = 1.5f;
                w->Velocity.w = 0.25f;
                wheel_guess_ground_force(w, &unused);
                sprintf(tag, "gw%u_%u", (unsigned)i, (unsigned)j);
                dump(tag, w);
            }
        }
    }

    // And with no terrain table, the handheld's state before task 27.
    {
        Wheel *w = fresh();
        gTerrainTypeInfoTable = NULL;
        bIdentity(&w->WorldMatrix);
        w->Velocity.x = 12.0f;
        w->Velocity.y = 0.5f;
        w->Velocity.z = 0.0f;
        w->Velocity.w = 0.0f;
        wheel_guess_ground_force(w, &unused);
        dump("gg_noterrain", w);
        gTerrainTypeInfoTable = g_terrain;
    }
}

// -------------------------------------------------------- ModifyGroundForce

static void scenario_modify(void)
{
    static const float xs[] = { 0.0f, 2.5f, -7.0f };
    static const float ys[] = { 0.0f, 1.5f };
    size_t i, j, m;
    char tag[64];

    printf("[modify]\n");
    for (m = 0; m < 2; m++) {
        for (i = 0; i < sizeof xs / sizeof xs[0]; i++) {
            for (j = 0; j < sizeof ys / sizeof ys[0]; j++) {
                Wheel *w = fresh();
                bVector2 v;
                // g_car's third row is (0, 0, 1, 0), so whatever the
                // function puts in the input's z lands only in the output
                // z, which nothing here reads. g_tilted's is not, which is
                // what makes the zero in that lane observable.
                if (m)
                    w->CarMatrix = g_tilted;
                v.x = xs[i];
                v.y = ys[j];
                wheel_modify_ground_force(w, &v);
                sprintf(tag, "mg%u_%u_%u", (unsigned)m, (unsigned)i,
                        (unsigned)j);
                pf(tag, w->GroundForce[0]);
                printf("%s gf1 %.9g\n", tag, w->GroundForce[1]);
            }
        }
    }
}

// ------------------------------------------------------ FinalizeGroundForce

static void scenario_finalize(void)
{
    static const int frames[] = { 0, 1, 2, 3, 4, 5 };
    static const float torques[] = { 260.0f, -260.0f, 0.0f };
    static const float gf0[] = { 140.0f, 26000.0f, 0.0005f };
    static const float zf[] = { 3900.0f, 0.0f, 0.0002f };
    size_t fr, t, g, z, locked, slipping, touching;
    int32_t savedframe = gWheelForceFrame;
    char tag[96];

    printf("[finalize]\n");
    gTerrainTypeInfoTable = g_terrain;

    for (fr = 0; fr < sizeof frames / sizeof frames[0]; fr++) {
        Wheel *w = fresh();
        gWheelForceFrame = frames[fr];
        wheel_finalize_ground_force(w, 3);
        sprintf(tag, "fr%u", (unsigned)fr);
        printf("%s wgf %.9g %.9g %.9g %.9g\n", tag,
               w->WorldGroundForce.x, w->WorldGroundForce.y,
               w->WorldGroundForce.z, w->WorldGroundForce.w);
        printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
               w->GroundForce[1]);
        printf("%s tu %.9g\n", tag, w->TractionUsage);
    }
    // The dot product associates left to right -- `vmul.xyz` then
    // `vaddy.x` then `vaddz.x`, so `(x + y) + z` -- and float addition is
    // not associative.
    //
    // A one-ulp difference in the dot on its own is not enough: frames 2
    // and 3 spend it on `N * -d + row`, where the two terms are the same
    // size and the last bit of d rounds straight back off. It has to be
    // amplified first, so the row here is very nearly parallel to the
    // contact normal -- v is about 0.9552 * n plus a kick in the sixth
    // decimal. Flattening then cancels almost everything and leaves a
    // residue the size of the kick, which carries the whole error, and
    // frame 3 normalises that residue so the direction moves too. The
    // result shows up in the fifth significant digit of the world force.
    //
    // Frame 2 is run as well and comes out identical either way; it is
    // kept because that is the fact, not because it catches anything.
    {
        static const float dn[3] = { 0.2512f, 0.5665f, -0.7848f };
        static const float dv[3] = { 0.2399223f, 0.5410649f, -0.7495642f };
        static const int dframes[] = { 2, 3 };
        size_t d4;
        for (d4 = 0; d4 < 2; d4++) {
            Wheel *w = fresh();
            gWheelForceFrame = dframes[d4];
            w->ContactNormal.x = dn[0];
            w->ContactNormal.y = dn[1];
            w->ContactNormal.z = dn[2];
            w->ContactNormal.w = 0.5f;
            w->WorldMatrix.v0.x = dv[0];
            w->WorldMatrix.v0.y = dv[1];
            w->WorldMatrix.v0.z = dv[2];
            w->WorldMatrix.v0.w = 0.25f;
            wheel_finalize_ground_force(w, 3);
            sprintf(tag, "fd%u", (unsigned)d4);
            printf("%s wgf %.9g %.9g %.9g %.9g\n", tag,
                   w->WorldGroundForce.x, w->WorldGroundForce.y,
                   w->WorldGroundForce.z, w->WorldGroundForce.w);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
        }
    }
    gWheelForceFrame = savedframe;

    // Both components inside WHEEL_EPSILON. The clamp's second test is
    // the only thing standing between a tiny force and being scaled by a
    // maxForce/mag that is meaningless at that size; with GroundForce[1]
    // pinned at -220 everywhere else, the magnitude is never small enough
    // for that test to decide anything.
    {
        static const float tiny0[] = { 0.0005f, 0.0f };
        static const float tiny1[] = { 0.0002f, 0.0f };
        static const float tinyz[] = { 0.0f, 0.0002f, 3900.0f };
        size_t i2, j2, z2;
        for (i2 = 0; i2 < 2; i2++)
        for (j2 = 0; j2 < 2; j2++)
        for (z2 = 0; z2 < 3; z2++) {
            Wheel *w = fresh();
            w->GroundForce[0] = tiny0[i2];
            w->GroundForce[1] = tiny1[j2];
            w->ZForce = tinyz[z2];
            wheel_finalize_ground_force(w, 1);
            sprintf(tag, "ft%u_%u_%u", (unsigned)i2, (unsigned)j2,
                    (unsigned)z2);
            printf("%s gf %.9g %.9g\n", tag, w->GroundForce[0],
                   w->GroundForce[1]);
            printf("%s tu %.9g\n", tag, w->TractionUsage);
            printf("%s wgf %.9g %.9g %.9g %.9g\n", tag,
                   w->WorldGroundForce.x, w->WorldGroundForce.y,
                   w->WorldGroundForce.z, w->WorldGroundForce.w);
        }
    }

    for (t = 0; t < sizeof torques / sizeof torques[0]; t++) {
        for (g = 0; g < sizeof gf0 / sizeof gf0[0]; g++) {
            for (z = 0; z < sizeof zf / sizeof zf[0]; z++) {
                for (locked = 0; locked < 2; locked++) {
                    for (slipping = 0; slipping < 2; slipping++) {
                        for (touching = 0; touching < 2; touching++) {
                            Wheel *w = fresh();
                            w->AppliedTorque = torques[t];
                            w->GroundForce[0] = gf0[g];
                            w->GroundForce[1] = -220.0f;
                            w->ZForce = zf[z];
                            w->BrakeLocked = (int32_t)locked;
                            w->Slipping = (uint8_t)slipping;
                            w->TouchingGround = (uint8_t)touching;
                            wheel_finalize_ground_force(w, 1);
                            sprintf(tag, "fg%u_%u_%u_%u_%u_%u", (unsigned)t,
                                    (unsigned)g, (unsigned)z,
                                    (unsigned)locked, (unsigned)slipping,
                                    (unsigned)touching);
                            printf("%s gf %.9g %.9g\n", tag,
                                   w->GroundForce[0], w->GroundForce[1]);
                            printf("%s tu %.9g\n", tag, w->TractionUsage);
                            printf("%s wgf %.9g %.9g %.9g %.9g\n", tag,
                                   w->WorldGroundForce.x,
                                   w->WorldGroundForce.y,
                                   w->WorldGroundForce.z,
                                   w->WorldGroundForce.w);
                        }
                    }
                }
            }
        }
    }

    // The lateral bleed, which only applies above walking pace along the
    // wheel's own x -- so a velocity that is and is not.
    {
        static const float vxs[] = { 9.0f, -9.0f, 0.5f, -0.5f, 1.0f };
        size_t i;
        for (i = 0; i < sizeof vxs / sizeof vxs[0]; i++) {
            Wheel *w = fresh();
            bIdentity(&w->WorldMatrix);
            w->Velocity.x = vxs[i];
            w->Velocity.y = 2.0f;
            w->Velocity.z = 0.0f;
            w->Velocity.w = 0.0f;
            wheel_finalize_ground_force(w, 0);
            sprintf(tag, "fb%u", (unsigned)i);
            pf(tag, w->GroundForce[0]);
            printf("%s gf1 %.9g\n", tag, w->GroundForce[1]);
        }
    }

    // One whole record for each of the four live frames.
    {
        int k;
        for (k = 1; k <= 4; k++) {
            Wheel *w = fresh();
            gWheelForceFrame = k;
            wheel_finalize_ground_force(w, 2);
            sprintf(tag, "ff%d", k);
            dump(tag, w);
        }
        gWheelForceFrame = savedframe;
    }

    // And with no terrain table.
    {
        Wheel *w = fresh();
        gTerrainTypeInfoTable = NULL;
        wheel_finalize_ground_force(w, 0);
        dump("fg_noterrain", w);
        gTerrainTypeInfoTable = g_terrain;
    }
}

// --------------------------------------------------- the horizontal forces

static void scenario_horizontal(void)
{
    static const float f0[] = { 140.0f, 0.0f, -300.0f };
    static const float f1[] = { -220.0f, 0.0f };
    size_t i, j;
    char tag[64];

    printf("[horizontal]\n");
    for (i = 0; i < sizeof f0 / sizeof f0[0]; i++) {
        for (j = 0; j < sizeof f1 / sizeof f1[0]; j++) {
            Wheel *w = fresh();
            bVector3 o;
            w->GroundForce[0] = f0[i];
            w->GroundForce[1] = f1[j];
            memset(&o, 0x5a, sizeof o);
            printf("hw%u_%u ret %d\n", (unsigned)i, (unsigned)j,
                   wheel_get_horizontal_ground_force_world(w, &o) == &o);
            sprintf(tag, "hw%u_%u", (unsigned)i, (unsigned)j);
            printf("%s %.9g %.9g %.9g %.9g\n", tag, o.x, o.y, o.z, o.pad);
            memset(&o, 0x5a, sizeof o);
            wheel_get_horizontal_ground_force_car(w, &o);
            sprintf(tag, "hc%u_%u", (unsigned)i, (unsigned)j);
            printf("%s %.9g %.9g %.9g %.9g\n", tag, o.x, o.y, o.z, o.pad);
        }
    }

    // Both particle hooks are `jr ra` in the image; called so that a port
    // which gave them a body would be seen to have done so.
    {
        Wheel *w = fresh();
        wheel_maybe_make_smoke(w, 4.5f);
        wheel_maybe_make_tire_spew(w, 4.5f);
        dump("hooks", w);
    }
}

// -------------------------------------------------------------- accessors

static void scenario_accessors(void)
{
    Wheel *w = fresh();
    bVector4 v;
    bVector2 s;
    bMatrix4 m;
    float *sl;

    printf("[accessors]\n");
    pf("moi", wheel_get_moment_of_inertia(w));
    pf("damage", wheel_get_damage(w));
    wheel_set_damage(w, 0.37f);
    pf("damage2", wheel_get_damage(w));

    g_wi.WheelNumber = 0;
    pi("steer0", wheel_is_steering_wheel(w));
    pi("drive0", wheel_is_drive_wheel(w));
    g_wi.WheelNumber = 1;
    pi("steer1", wheel_is_steering_wheel(w));
    pi("drive1", wheel_is_drive_wheel(w));
    g_wi.WheelNumber = 2;
    pi("steer2", wheel_is_steering_wheel(w));
    pi("drive2", wheel_is_drive_wheel(w));
    g_wi.WheelNumber = 3;
    pi("steer3", wheel_is_steering_wheel(w));
    pi("drive3", wheel_is_drive_wheel(w));
    g_wi.WheelNumber = 2;

    w->OldSlip = 1.5f;
    w->CurrentSlip = -2.5f;
    pf("oldslip", wheel_get_old_slip(w));
    pf("curslip", wheel_get_current_slip(w));

    wheel_set_slipping(w, 1);
    pi("slipping", wheel_is_slipping(w));
    wheel_set_slipping(w, 0);
    pi("slipping2", wheel_is_slipping(w));

    w->AppliedTorque = 100.0f;
    w->BrakeLocked = 0;
    wheel_apply_torque(w, 25.0f);
    pf("torque", w->AppliedTorque);
    w->BrakeLocked = 1;
    wheel_apply_torque(w, 25.0f);
    pf("torque_locked", w->AppliedTorque);
    w->BrakeLocked = 0;

    pf("zforce", wheel_get_z_force(w));
    pf("mass", wheel_get_mass(w));
    pf("radius", wheel_get_radius(w));

    printf("cn %d\n", wheel_get_contact_normal(w) == &w->ContactNormal);
    printf("cp %d\n", wheel_get_contact_point(w) == &w->ContactPoint);
    printf("gfv %d\n",
           wheel_get_ground_force_vector(w) == &w->WorldGroundForce);
    printf("restpos %d\n",
           wheel_get_rest_position_in_geometry_frame(w)
               == (const bVector3 *)&g_wi);
    {
        const bVector3 *rp = wheel_get_rest_position_in_geometry_frame(w);
        printf("restpos v %.9g %.9g %.9g %.9g\n",
               rp->x, rp->y, rp->z, rp->pad);
    }

    v.x = 0.2f; v.y = 0.3f; v.z = 0.9f; v.w = -1.5f;
    wheel_set_contact_normal(w, &v);
    pv("setcn", &w->ContactNormal);
    v.x = 4.0f; v.y = 5.0f; v.z = 6.0f; v.w = 7.0f;
    wheel_set_contact_point(w, &v);
    pv("setcp", &w->ContactPoint);
    v.x = -1.0f; v.y = -2.0f; v.z = -3.0f; v.w = -4.0f;
    wheel_set_velocity(w, &v);
    pv("setvel", &w->Velocity);

    bIdentity(&m);
    m.v3.x = 9.0f;
    wheel_set_car_matrix(w, &m);
    pm("setcar", &w->CarMatrix);
    m.v3.y = -9.0f;
    wheel_set_world_matrix(w, &m);
    pm("setworld", &w->WorldMatrix);

    wheel_set_touching_ground(w, 1);
    pi("tg", wheel_is_touching_ground(w));
    w->RoadNoise = 0.55f;
    pf("noise_on", wheel_get_road_noise(w));
    wheel_set_touching_ground(w, 0);
    pi("tg2", wheel_is_touching_ground(w));
    pf("noise_off", wheel_get_road_noise(w));
    wheel_set_touching_ground(w, 1);

    wheel_set_terrain(w, 4);
    pi("terrain", wheel_get_terrain(w));

    s.x = 3.5f; s.y = -6.5f;
    wheel_set_slip(w, &s);
    pf("slip0", w->Slip[0]);
    pf("slip1", w->Slip[1]);
    pf("slipcur", w->CurrentSlip);
    sl = wheel_get_slip(w);
    printf("slipptr %d\n", sl == w->Slip);

    w->TractionUsage = 0.62f;
    pf("tu", wheel_get_traction_usage(w));

    w->Slipping = 0; w->BrakeLocked = 0;
    pi("mod00", wheel_modifiable(w));
    w->Slipping = 1; w->BrakeLocked = 0;
    pi("mod10", wheel_modifiable(w));
    w->Slipping = 0; w->BrakeLocked = 1;
    pi("mod01", wheel_modifiable(w));
    w->Slipping = 1; w->BrakeLocked = 1;
    pi("mod11", wheel_modifiable(w));
    w->Slipping = 0; w->BrakeLocked = 0;

    printf("matptr %d\n", wheel_get_matrix(w) == &w->Matrix);
    printf("carptr %d\n", wheel_get_car_matrix(w) == &w->CarMatrix);
    pf("at", wheel_get_applied_torque(w));
    pf("tresp", wheel_get_torque_response(w));
    pf("angacc", wheel_get_angular_acceleration(w));
    pf("angvel", wheel_get_angular_velocity(w));
    pf("rot", wheel_get_rotation(w));

    wheel_set_catchup_friction_multiplier(w, 1.35f);
    pf("catchup", w->CatchupFrictionMultiplier);
    wheel_adjust_traction_boost(w, 0.5f);
    pf("boost", w->TractionBoost);
    wheel_set_traction_boost(w, 2.25f);
    pf("boost2", w->TractionBoost);
    wheel_set_ebrake(w, 0.8f);
    pf("ebrake", wheel_get_ebrake(w));
    wheel_set_brake(w, 0.45f);
    pf("brake", w->Brake);

    // The empty one, called so that a port which filled it in shows it.
    // "Shows it" needs somewhere to show: the function takes no wheel and
    // returns nothing, so the only trace a body could leave is in the
    // tuning globals, and they are re-dumped here for that reason. Without
    // this the claim that SetSliderValue is empty was unfalsifiable, and
    // the mutation standing in for it wrote to its own parameters and
    // could not have been caught by anything.
    // 0.375, not 0.5: gMaxStaticSlip already *is* 0.5, so a body that
    // assigned the slider's value to it would have written the number that
    // was there and left no trace. The argument has to be a value no
    // tuning global holds.
    SetSliderValue(7, -1.0f, 0.875f, 0.375f);
    dump_globals("slider");

    // bRotateVector is a free function in the same object file.
    {
        bVector3 o, in;
        bMatrix4 rm;
        bIdentity(&rm);
        rm.v0.x = 0.0f; rm.v0.y = 1.0f;
        rm.v1.x = -1.0f; rm.v1.y = 0.0f;
        rm.v3.x = 100.0f; rm.v3.y = 200.0f; rm.v3.z = 300.0f;
        in.x = 2.0f; in.y = 3.0f; in.z = 4.0f; in.pad = 5.0f;
        memset(&o, 0x5a, sizeof o);
        bRotateVector(&o, &rm, &in);
        printf("rotvec %.9g %.9g %.9g\n", o.x, o.y, o.z);
    }

    dump("acc", w);
}

// ---------------------------------------------------------- the snapshot

static void scenario_snapshot(void)
{
    static const int resets[] = { 0, 1 };
    size_t r;
    char tag[96];
    void *snap = (void *)(size_t)0xbeef;

    printf("[snapshot]\n");

    for (r = 0; r < sizeof resets / sizeof resets[0]; r++) {
        Wheel *w = fresh();
        uint32_t magic = 0xa5a5a5a5u;
        int32_t words[4];
        int j;

        // The four-word move reaches past GroundForce[1] into the
        // alignment pad, so the pad is given a value no float here could
        // produce. A port that moved three words, or that moved the two
        // forces as floats, loses it.
        memcpy(w->_pad2, &magic, sizeof magic);
        // Not the zero fresh() leaves, so a reset that cleared LastSign --
        // which the image's list does not -- would show.
        w->LastSign = 3;
        w->RoadNoise = 0.55f;
        w->Damage = 0.37f;
        w->NumTimesSkidding = 9;
        w->TheSkidMaker.pSkidSet = (void *)(size_t)0x777;

        install_replay_seams();
        reset_replay_record();
        g_rp_reset = resets[r];
        wheel_do_snapshot(w, snap);

        sprintf(tag, "sn%u", (unsigned)r);
        printf("%s calls %d %d %d %d %d\n", tag, g_rp_begin, g_rp_float,
               g_rp_ints, g_rp_reset_calls, g_rp_end);
        printf("%s name %s\n", tag, g_rp_name);
        printf("%s snap %d\n", tag, g_rp_snap == snap);
        printf("%s foff %d %d\n", tag,
               (int)((char *)g_rp_fp[0] - (char *)w),
               (int)((char *)g_rp_fp[1] - (char *)w));
        printf("%s ioff %d n %d\n", tag,
               (int)((char *)g_rp_ip - (char *)w), (int)g_rp_n);
        // Read back through the int pointer the port handed the seam, as
        // raw words, so the pad is pinned alongside the two forces.
        memcpy(words, g_rp_ip, sizeof words);
        for (j = 0; j < 4; j++)
            printf("%s word%d %08x\n", tag, j, (unsigned)words[j]);
        printf("%s skid %d\n", tag, w->TheSkidMaker.pSkidSet
                                         == (void *)(size_t)0x777);
        {
            uint32_t back;
            memcpy(&back, w->_pad2, sizeof back);
            printf("%s pad %08x\n", tag, (unsigned)back);
        }
        dump(tag, w);
    }

    // With no replay attached at all. Nothing should move and nothing
    // should clear -- the reset is behind the same seam as the moves.
    {
        Wheel *w = fresh();
        clear_replay_seams();
        reset_replay_record();
        g_rp_reset = 1;
        wheel_do_snapshot(w, snap);
        printf("snnull calls %d %d %d %d %d\n", g_rp_begin, g_rp_float,
               g_rp_ints, g_rp_reset_calls, g_rp_end);
        dump("snnull", w);
    }

    clear_replay_seams();
    install_terrain_seams();
}

// ------------------------------------------- SetState(CarState *, ...)

static CarState         *g_scs;
static CarTypeInfoPrefix g_sinfo;
static WheelInfo         g_swi[4];

static void build_setstate_fixture(void)
{
    int i;

    memset(&g_sinfo, 0, sizeof g_sinfo);
    g_sinfo.CenterOfGravity.x = 0.02f;
    g_sinfo.CenterOfGravity.y = -0.15f;
    g_sinfo.CenterOfGravity.z = 0.44f;
    g_sinfo.CenterOfGravity.pad = 1.0f;

    for (i = 0; i < 4; i++) {
        g_sinfo.Wheels[i].PositionX = (i & 1) ? -1.4f : 1.4f;
        g_sinfo.Wheels[i].PositionY = (i < 2) ? 0.78f : -0.92f;
        g_sinfo.Wheels[i].PositionZ = -0.35f;
        // Radius is the fourth lane of the quadword the matrices load, so
        // it is given a value that would be visible if the 1.0 that
        // overwrites it were ever missing.
        g_sinfo.Wheels[i].Radius = 0.32f + 0.01f * (float)i;
        g_sinfo.Wheels[i].Width = 0.21f;
        g_sinfo.Wheels[i].WheelNumber = i;
    }

    for (i = 0; i < 4; i++)
        g_swi[i] = g_sinfo.Wheels[i];

    g_scs = (CarState *)calloc(1, sizeof(CarState));
    g_scs->pCarInfo = &g_sinfo;
    g_scs->pTopologyCoordinate = (TopologyCoordinate *)(size_t)0x9abc;
    g_scs->ForwardSpeed = 20.0f;

    // A body that is rotated about all three axes, so none of the twelve
    // products in eMulMatrix cancels, and a position and spin that make
    // the r x omega term nonzero in every lane.
    bIdentity(&g_scs->BodyMatrix);
    g_scs->BodyMatrix.v0.x = 0.936293435f;
    g_scs->BodyMatrix.v0.y = 0.351175636f;
    g_scs->BodyMatrix.v0.z = -0.0174524058f;
    g_scs->BodyMatrix.v0.w = 0.125f;
    g_scs->BodyMatrix.v1.x = -0.348570138f;
    g_scs->BodyMatrix.v1.y = 0.929229140f;
    g_scs->BodyMatrix.v1.z = 0.121869341f;
    g_scs->BodyMatrix.v1.w = -0.0625f;
    g_scs->BodyMatrix.v2.x = 0.0523359589f;
    g_scs->BodyMatrix.v2.y = -0.111618653f;
    g_scs->BodyMatrix.v2.z = 0.992403865f;
    g_scs->BodyMatrix.v2.w = 0.25f;
    g_scs->BodyMatrix.v3.x = 77.0f;
    g_scs->BodyMatrix.v3.y = -88.0f;
    g_scs->BodyMatrix.v3.z = 99.0f;
    g_scs->BodyMatrix.v3.w = 0.5f;

    g_scs->Position.x = 120.5f;
    g_scs->Position.y = -34.25f;
    g_scs->Position.z = 6.75f;
    // The pad, not a zero: row 3 of the placement matrix comes off this
    // quadword, and the four-lane subtract that follows reads it back.
    g_scs->Position.pad = 0.375f;

    g_scs->Velocity.x = 18.0f;
    g_scs->Velocity.y = -2.5f;
    g_scs->Velocity.z = 0.125f;
    g_scs->Velocity.pad = -0.75f;

    g_scs->AngularVelocity.x = 0.21f;
    g_scs->AngularVelocity.y = -0.34f;
    g_scs->AngularVelocity.z = 1.05f;
    g_scs->AngularVelocity.pad = 0.5f;
}

static void scenario_carstate(void)
{
    // Wheel 2 is a rear wheel, so CalculateWheelMatrices leaves the
    // steering out; wheel 0 is a front one, so the same angle turns two
    // matrices. Both are needed: nothing else in this transcript reaches
    // the steering rotation.
    static const int nums[] = { 2, 0 };
    static const float angles[] = { 0.75f, -3.5f };
    static const uint16_t steers[] = { 0, 8192 };
    size_t a, b, c, seam;
    char tag[96], tag2[128];

    printf("[carstate]\n");

    for (seam = 0; seam < 2; seam++) {
        if (seam)
            install_terrain_seams();
        else
            clear_terrain_seams();

        for (a = 0; a < sizeof nums / sizeof nums[0]; a++) {
            for (b = 0; b < sizeof angles / sizeof angles[0]; b++) {
                for (c = 0; c < sizeof steers / sizeof steers[0]; c++) {
                    Wheel *w = fresh();
                    int n = nums[a];

                    w->WI = &g_swi[n];

                    g_elev_calls = 0;
                    g_elev_terrain_out = NULL;
                    g_elev_topology = NULL;
                    memset(&g_elev_pos, 0, sizeof g_elev_pos);
                    g_elev_return = 4.5f;
                    g_elev_normal.x = 0.12f;
                    g_elev_normal.y = -0.3f;
                    g_elev_normal.z = 0.946f;
                    g_elev_normal.pad = 0.625f;

                    memset(g_scs->WheelTouchingGround, 0,
                           sizeof g_scs->WheelTouchingGround);
                    memset(g_scs->WheelTerrain, 0,
                           sizeof g_scs->WheelTerrain);
                    memset(g_scs->CrossedWheelTerrain, 0,
                           sizeof g_scs->CrossedWheelTerrain);
                    g_scs->nWheelsTouchingGround = 0;
                    g_scs->SteeringAngle = 0;

                    wheel_set_state_from_car_state(w, g_scs, &g_sinfo,
                                                   angles[b], -17.5f,
                                                   steers[c], 0.045f);

                    sprintf(tag, "cs%u_%u_%u_%u", (unsigned)seam,
                            (unsigned)a, (unsigned)b, (unsigned)c);
                    printf("%s steer %u\n", tag,
                           (unsigned)g_scs->SteeringAngle);
                    printf("%s wav %.9g\n", tag,
                           g_scs->WheelAngularVelocity[n]);
                    printf("%s wa %.9g\n", tag, g_scs->WheelAngle[n]);
                    printf("%s wsh %.9g\n", tag,
                           g_scs->WheelSuspensionHeight[n]);
                    printf("%s tg %d %d\n", tag,
                           (int)g_scs->WheelTouchingGround[n],
                           (int)g_scs->nWheelsTouchingGround);
                    printf("%s terr %d %d\n", tag,
                           (int)g_scs->WheelTerrain[n],
                           (int)g_scs->CrossedWheelTerrain[n]);
                    sprintf(tag2, "%s wm", tag);
                    pm(tag2, &g_scs->WheelMatrix[n]);
                    sprintf(tag2, "%s bm", tag);
                    pm(tag2, &g_scs->BrakeMatrix[n]);
                    printf("%s elev %d out %d\n", tag, g_elev_calls,
                           g_elev_terrain_out != NULL);
                    printf("%s epos %.9g %.9g %.9g %.9g\n", tag,
                           g_elev_pos.x, g_elev_pos.y, g_elev_pos.z,
                           g_elev_pos.pad);
                    printf("%s etop %d\n", tag,
                           g_elev_topology
                               == (void *)g_scs->pTopologyCoordinate);
                    dump(tag, w);
                }
            }
        }
    }

    install_terrain_seams();
}

// ------------------------------------------------------------- the seams

static void scenario_seams(void)
{
    printf("[seams]\n");
    gWheelFindDrivingSurfaceFn = NULL;
    gWheelExchangeZForcesFn = NULL;
    printf("before %d %d\n", gWheelFindDrivingSurfaceFn != NULL,
           gWheelExchangeZForcesFn != NULL);
    wheel_install_seams();
    printf("after %d %d\n",
           gWheelFindDrivingSurfaceFn == wheel_find_driving_surface,
           gWheelExchangeZForcesFn == wheel_exchange_z_forces);
    wheel_install_seams();
    printf("again %d %d\n",
           gWheelFindDrivingSurfaceFn == wheel_find_driving_surface,
           gWheelExchangeZForcesFn == wheel_exchange_z_forces);
}

int main(void)
{
    wheel_static_init();
    build_info();
    build_matrices();
    build_terrain_table();
    build_setstate_fixture();
    install_terrain_seams();
    gTerrainTypeInfoTable = g_terrain;

    scenario_layout();
    scenario_constants();
    scenario_statics();
    scenario_lifetime();
    scenario_compute_aux();
    scenario_exchange();
    scenario_check_terrain();
    scenario_derivative();
    scenario_brake_lock();
    scenario_pilot();
    scenario_lateral();
    scenario_guess();
    scenario_modify();
    scenario_finalize();
    scenario_horizontal();
    scenario_accessors();
    scenario_snapshot();
    scenario_carstate();
    scenario_seams();
    return 0;
}
