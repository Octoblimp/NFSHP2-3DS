// wheel -- see wheel.h.

#include "wheel.h"

#include <math.h>
#include <string.h>

#include "bmath.h"
#include "emath.h"      // eMulMatrix, for SetState(CarState *, ...)
#include "suspension.h"   // gLoadFactor, gWheelForceFrame,
                          // gTireForceEllipseRatio, gUglyTimestepHack --
                          // one .sdata block, and Suspension defines it.
#include "carstate.h"
#include "replay.h"
#include "table.h"

// The shipped values, read out of .sdata in the ELF.
float   gWheelMomentOfInertia           = 0.00999999978f;
float   gRollingFriction                = 0.00200000009f;
float   gMaxStaticSlip                  = 0.5f;
float   gBrakingTorque                  = 4.0f;
float   gEBrakingTorque                 = 10.0f;
float   gStaticToDynamicBrakeForceRatio = 1.20000005f;
float   gBrakeLockAngularVelocityFactor = 0.100000001f;
float   gZForceScale                    = 1.0f;
float   gPilotFactor                    = 0.850000024f;
int32_t gWheelDebugInfo                 = 0;
float   gCorneringScale                 = 1.0f;
int32_t gUseNewTireForces               = 1;
float   gNewCorneringScale              = 2.5f;

// Zero in the image; wheel_static_init writes 0.223402172f.
float gMaxSlipAngleGlobal = 0.0f;

const TerrainTypeInfo *gTerrainTypeInfoTable = NULL;

TopologyGetElevationFn    gTopologyGetElevationFn    = NULL;
TerrainRoadNoiseFn        gTerrainRoadNoiseFn        = NULL;
WheelTopologyOfCarStateFn gWheelTopologyOfCarStateFn = NULL;
WheelMaybeMakeSkidsFn     gWheelMaybeMakeSkidsFn     = NULL;

// The eight curves, out of .data at 0x00308e28..0x00308f08.
const float gCorneringForceTable[WHEEL_CORNERING_ENTRIES] = {
    0.0f, 0.400000006f, 0.800000012f, 1.20000005f, 1.60000002f, 1.75f,
    1.64999998f
};
const float gZeroDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f
};
const float gTwoDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.20000005f, 2.29999995f, 3.0f, 3.0f, 2.79999995f
};
const float gFourDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.70000005f, 3.20000005f, 4.30000019f, 5.0999999f, 5.19999981f
};
const float gSixDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.79999995f, 3.5f, 4.9000001f, 5.80000019f, 6.0999999f
};
const float gEightDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.83000004f, 3.5999999f, 5.0f, 5.96000004f, 6.4000001f
};
const float gTenDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.86000001f, 3.70000005f, 5.0999999f, 6.13000011f, 6.69999981f
};
const float gTwelveDegreeTable[WHEEL_LOAD_TABLE_ENTRIES] = {
    0.0f, 1.89999998f, 3.79999995f, 5.19999981f, 6.30000019f, 7.0999999f
};

Table  gLoadSensitivity[WHEEL_NUM_LOAD_TABLES];
Table *gLoadSensitivityTable[WHEEL_NUM_LOAD_TABLES];
Table  gCorneringForce;

WheelFindDrivingSurfaceFn gWheelFindDrivingSurfaceFn;
WheelExchangeZForcesFn    gWheelExchangeZForcesFn;

// 0x0019b558. The static constructor. The seven load curves all span
// [0, 10]; the cornering curve spans [0, MAX_SLIP_ANGLE] and sets that
// global on the way past, which is the only place it is ever written.
void wheel_static_init(void)
{
    static const float *const entries[WHEEL_NUM_LOAD_TABLES] = {
        gZeroDegreeTable,  gTwoDegreeTable,   gFourDegreeTable,
        gSixDegreeTable,   gEightDegreeTable, gTenDegreeTable,
        gTwelveDegreeTable
    };
    int i;

    gMaxSlipAngleGlobal = 0.223402172f;
    table_init(&gCorneringForce, gCorneringForceTable,
               WHEEL_CORNERING_ENTRIES, 0.0f, gMaxSlipAngleGlobal);

    for (i = 0; i < WHEEL_NUM_LOAD_TABLES; ++i) {
        table_init(&gLoadSensitivity[i], entries[i],
                   WHEEL_LOAD_TABLE_ENTRIES, 0.0f, 10.0f);
        gLoadSensitivityTable[i] = &gLoadSensitivity[i];
    }
}

void wheel_install_seams(void)
{
    gWheelFindDrivingSurfaceFn = wheel_find_driving_surface;
    gWheelExchangeZForcesFn    = wheel_exchange_z_forces;
}

// --------------------------------------------------------- VU idioms
//
// `vmul.xyz` then `vaddy.x` then `vaddz.x` -- the sum associates left to
// right as `(x + y) + z`, which is not what a compiler would choose and
// is not the same number.
static float dot3(const bVector4 *a, const bVector4 *b)
{
    float x = a->x * b->x;
    float y = a->y * b->y;
    float z = a->z * b->z;
    return (x + y) + z;
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfD,vfB,vfA` is A cross B, and
// it writes xyz only -- the destination keeps whatever w it had, which in
// every use here is the w of A because the two share a register.
static void cross3(bVector4 *o, const bVector4 *a, const bVector4 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;
    o->x = x;
    o->y = y;
    o->z = z;
    o->w = a->w;
}

// `vrsqrt Q,vf00w,vf01x` then `vaddq.x`: 1/sqrt of the squared length,
// then a broadcast multiply. The reciprocal square root is a divide by a
// sqrt on the VU, not a fast estimate.
static void normalize3(bVector4 *v)
{
    float len2 = dot3(v, v);
    float inv  = 1.0f / sqrtf(len2);
    v->x *= inv;
    v->y *= inv;
    v->z *= inv;
    v->w *= inv;
}

// 0x00199c30. Empty in the shipped image.
void SetSliderValue(int32_t which, float lo, float hi, float value)
{
    (void)which;
    (void)lo;
    (void)hi;
    (void)value;
}

// 0x0019b230.
void bRotateVector(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    float x, y, z;

    x = m->v0.x * v->x;
    x = x + m->v1.x * v->y;
    x = x + m->v2.x * v->z;
    o->x = x;

    y = m->v0.y * v->x;
    y = y + m->v1.y * v->y;
    y = y + m->v2.y * v->z;
    o->y = y;

    z = m->v0.z * v->x;
    z = z + m->v1.z * v->y;
    z = z + m->v2.z * v->z;
    o->z = z;
}

// --------------------------------------------------------------- lifetime

// 0x00199c40. Nine fields and no more -- the matrices, the forces and the
// contact record are all left as whatever the slot pool handed back, and
// the first ComputeAuxiliaries is what makes them mean anything.
Wheel *wheel_init(Wheel *w, const WheelInfo *wi, const TireInfo *ti,
                  const ControlInfo *ci, void *cs)
{
    w->_vtable = WHEEL_VTABLE;
    w->CS = cs;
    w->WI = wi;
    w->TI = ti;
    w->CI = ci;
    w->LastSign = 1;
    w->CatchupFrictionMultiplier = 1.0f;
    w->TheSkidMaker.pSkidSet = NULL;
    w->TractionBoost = 1.0f;
    w->NumTimesSkidding = 0;
    w->OldSlip = 0.0f;
    w->RoadNoise = 0.0f;
    return w;
}

// 0x0019b9e0. The image runs `_$_9SkidMaker(this + 384, 2)` and then
// `_$_16PhysicsComponent(this, 0)`, the second argument in each being the
// old-g++ "also free me" flag. What SkidMaker's destructor does with the
// skid set is task 27's to say, so this does not guess at it -- the only
// part of the chain that belongs to Wheel is the vtable handover, which
// PhysicsComponent's destructor performs.
void wheel_fini(Wheel *w)
{
    w->_vtable = PHYSICSCOMPONENT_VTABLE;
}

// 0x0019a068. The load argument the other Calibrate methods take is not
// in this one's signature at all -- the moment of inertia is a global.
void wheel_calibrate(Wheel *w)
{
    w->MomentOfInertia = gWheelMomentOfInertia;
}

// ------------------------------------------------------------- the state

void wheel_set_state2(Wheel *w, float a, float wv)
{
    w->State.w = wv;
    w->State.a = a;
}

void wheel_set_state_w(Wheel *w, float wv)
{
    w->State.w = wv;
}

// 0x0019b9a0 / 0x0019b9b8. One unaligned 64-bit move each way: the pair
// is copied as a unit, not as two floats.
void wheel_set_state_array(Wheel *w, const float *in)
{
    w->State.a = in[0];
    w->State.w = in[1];
}

void wheel_get_state_array(const Wheel *w, float *out)
{
    out[0] = w->State.a;
    out[1] = w->State.w;
}

WheelState *wheel_get_state(Wheel *w)
{
    return &w->State;
}

int32_t wheel_get_size(const Wheel *w)
{
    (void)w;
    return WHEEL_STATE_FLOATS;
}

// 0x0019a3d0. Returns NULL rather than `out` -- Suspension's GetDerivative
// returns its buffer and this one does not, and both are reached through
// the same virtual slot.
float *wheel_get_derivative(Wheel *w, float *out)
{
    float rollingMul = 1.0f;
    float acc;

    if (gTerrainTypeInfoTable != NULL)
        rollingMul = gTerrainTypeInfoTable[w->Terrain].RollingFrictionMultiplier;

    out[0] = w->State.w;

    acc = w->AppliedTorque - w->GroundForce[0] * w->WI->Radius;
    acc = acc - (w->State.w * rollingMul) * gRollingFriction;
    acc = acc / w->MomentOfInertia;
    out[1] = acc;

    if (w->BrakeLocked != 0)
        out[1] = 0.0f;

    // Not `if (!Slipping && hack > eps)` in one test -- the image reloads
    // the hack into the delay slot of the Slipping branch, so the guard is
    // only reached when the wheel is gripping.
    if (w->Slipping == 0 && WHEEL_EPSILON < gUglyTimestepHack) {
        float d = w->WI->Radius * gUglyTimestepHack;
        out[1] = out[1] - w->CurrentSlip / d;
    }

    return NULL;
}

// 0x0019a078. Called once a frame before the forces are resolved.
void wheel_compute_auxiliaries(Wheel *w)
{
    float c, s, a;
    int32_t sign;

    bIdentity(&w->Matrix);

    a = w->State.a;
    c = bSinF(a + WHEEL_IMAGE_HALF_PI);
    s = bSinF(a);

    w->Matrix.v2.z = c;
    w->Matrix.v0.z = -s;
    w->Matrix.v0.x = c;
    w->Matrix.v2.x = s;

    w->GroundForce[0] = 0.0f;
    w->GroundForce[1] = 0.0f;
    w->AppliedTorque  = 0.0f;
    w->CurrentSlip    = 0.0f;

    // Fold the spin angle back into one turn's worth. A wheel that has
    // somehow gained ten folds' worth in a frame is zeroed rather than
    // folded again -- the second test is against ten times the first.
    if (WHEEL_ROT_FOLD < a) {
        float f = a - WHEEL_ROT_FOLD;
        w->State.a = f;
        if (WHEEL_ROT_GIVE_UP < f)
            w->State.a = 0.0f;
    } else if (a < -WHEEL_ROT_FOLD) {
        float f = a + WHEEL_ROT_FOLD;
        w->State.a = f;
        if (f < -WHEEL_ROT_GIVE_UP)
            w->State.a = 0.0f;
    }

    // LastSign is a three-way memory of which way the wheel was turning:
    // 0 forward, 2 backward, 1 stopped. A wheel that was going one way is
    // not allowed to cross zero within a frame -- it is clamped to a stop
    // first and picks the new sign up next frame.
    sign = w->LastSign;
    if (sign == 0) {
        if (w->State.w < 0.0f)
            w->State.w = 0.0f;
    } else if (sign == 2) {
        if (0.0f < w->State.w)
            w->State.w = 0.0f;
    }

    if (WHEEL_SPIN_EPSILON < w->State.w)
        w->LastSign = 0;
    else if (w->State.w < -WHEEL_SPIN_EPSILON)
        w->LastSign = 2;
    else
        w->LastSign = 1;
}

// ------------------------------------------------------------- the seams

// 0x0019a1c8.
//
// **This returns 0.0f and it is not an oversight of the port.** Both arms
// end `mtc1 zero,$f0` before `jr ra`: the airborne arm stores a zero into
// ZForce and returns the same register, and the loaded arm stores the real
// force into ZForce and then clears $f0 on the way out.
// Suspension::ResolveForces (0x0019c0e0) writes what comes back straight
// into Suspension::GroundForce at offset 160, so that field is zero on
// every frame of the shipped game. Nothing in Suspension reads it back --
// the only two accesses to offset 160 in the whole class are this store
// and a stack slot that happens to share the number. Whether Car or
// PhysicsCar reads it is for those slices to find out; this one records
// that the value they would read is zero.
float wheel_exchange_z_forces(Wheel *w, int32_t touching, float z)
{
    w->TouchingGround = (uint8_t)touching;

    if (touching != 0) {
        float r = -w->WI->Radius;
        w->ContactPoint.x = w->ContactNormal.x * r + w->WorldMatrix.v3.x;
        w->ContactPoint.y = w->ContactNormal.y * r + w->WorldMatrix.v3.y;
        w->ContactPoint.z = w->ContactNormal.z * r + w->WorldMatrix.v3.z;
        w->ContactPoint.w = w->ContactNormal.w * r + w->WorldMatrix.v3.w;
    }

    if (!(0.0f < z)) {
        w->ZForce = 0.0f;
        return 0.0f;
    }

    {
        // ((up x N) x up) . N -- the part of the wheel's own up axis that
        // survives being flattened against the contact normal twice. It is
        // 0 when the wheel is on its side and 1 when the ground is square
        // under it, and the affine map below turns that into a multiplier
        // that floors at 0.3 rather than falling to nothing.
        bVector4 t, u;
        float d;

        cross3(&t, &w->WorldMatrix.v1, &w->ContactNormal);
        cross3(&u, &t, &w->WorldMatrix.v1);
        d = dot3(&u, &w->ContactNormal);

        d = d * 4.0f;
        d = d - 3.0f;
        if (d < WHEEL_ZFORCE_FLOOR)
            d = WHEEL_ZFORCE_FLOOR;

        w->ZForce = z * d;
    }

    return 0.0f;
}

// 0x0019a2c8.
float wheel_check_terrain(Wheel *w, bVector3 *normalOut, int32_t *terrainOut,
                          const bVector3 *pos, const bMatrix4 *r)
{
    bVector4 probe;
    bVector4 delta;
    float elev = 0.0f;
    float noise = 0.0f;
    float align;

    if (gTopologyGetElevationFn != NULL) {
        void *topo = gWheelTopologyOfCarStateFn
                         ? gWheelTopologyOfCarStateFn(w->CS)
                         : NULL;
        // terrainOut goes straight through: a2 arrives holding it and
        // nothing before the `jal` touches a2. The `move t0,zero` at
        // 0x0019a300 is the fifth argument, the `bool *` the seam leaves
        // out -- register 8, not 6. GetElevation writes the polygon's
        // type through a non-NULL pointer (0x0014f714), so the
        // `lw a1,0(s4)` after the call feeds GetRoadNoise the terrain it
        // just reported, not a stale one.
        elev = gTopologyGetElevationFn(topo, pos, terrainOut, normalOut);
    } else {
        // The normal only. With no topology there is no surface to report,
        // so Terrain keeps whatever SetTerrain last put there.
        normalOut->x = 0.0f;
        normalOut->y = 0.0f;
        normalOut->z = 1.0f;
        normalOut->pad = 0.0f;
    }

    {
        bVector2 xy;
        xy.x = pos->x;
        xy.y = pos->y;
        if (gTerrainRoadNoiseFn != NULL)
            noise = gTerrainRoadNoiseFn(&xy, *terrainOut);
    }
    w->RoadNoise = noise;

    // The probe is the query point with its z replaced by the ground
    // height. Its w lane is never written on the PS2 -- `lqc2 vf1,0(sp)`
    // reads a stack slot the function has not touched, and the `vsub`
    // that follows carries the junk into delta.w -- but the only consumer
    // is a `vmul.xyz`, so it cannot reach the result. Zeroed here because
    // a defined value is worth more than an imitation of uninitialised
    // stack, and the transcript proves the choice cannot be observed.
    probe.x = pos->x;
    probe.y = pos->y;
    probe.z = elev + noise;
    probe.w = 0.0f;

    align = (normalOut->x * r->v2.x + normalOut->y * r->v2.y)
            + normalOut->z * r->v2.z;

    // A surface facing away from the wheel is not a surface. The terrain
    // type is cleared with it, so the caller does not keep reading the
    // friction of ground it is not on.
    if (align < WHEEL_EPSILON) {
        *terrainOut = 0;
        return WHEEL_NO_SURFACE;
    }

    delta.x = probe.x - pos->x;
    delta.y = probe.y - pos->y;
    delta.z = probe.z - pos->z;
    delta.w = probe.w - pos->pad;

    {
        float num = (normalOut->x * delta.x + normalOut->y * delta.y)
                    + normalOut->z * delta.z;
        return num / align;
    }
}

// 0x0019a2a0.
float wheel_find_driving_surface(Wheel *w, const bVector4 *pos,
                                 const bMatrix4 *r)
{
    return wheel_check_terrain(w, (bVector3 *)&w->ContactNormal, &w->Terrain,
                               (const bVector3 *)pos, r);
}

// ----------------------------------------------------------- the braking

// 0x0019a480. `v` arrives already scaled by the ground force over the
// speed; this multiplies it by the radius and adds a tenth of the spin.
void wheel_check_for_brake_lock(Wheel *w, float v)
{
    float torque = (gBrakingTorque * w->Brake) * w->CI->Brake
                   + (gEBrakingTorque * w->EBrake) * w->CI->EBrake;
    float threshold = torque * gStaticToDynamicBrakeForceRatio;
    float demand = v * w->WI->Radius
                   + fabsf(w->State.w) * gBrakeLockAngularVelocityFactor;

    if (demand < threshold) {
        // A locked wheel and a stopped wheel are different things: below
        // one newton-metre of static threshold the wheel is simply stopped
        // and BrakeLocked stays clear.
        w->BrakeLocked = (1.0f < threshold) ? 1 : 0;
        w->State.w = 0.0f;
    } else {
        w->BrakeLocked = 0;
    }
}

// 0x0019a520. Only the rear wheels have one, only while they are turning
// forwards and not locked, and it ramps out with speed.
float wheel_get_pilot_factor(Wheel *w)
{
    float t;
    const CarState *cs;

    if (w->BrakeLocked != 0)
        return 1.0f;
    if (w->State.w < 0.0f)
        return 1.0f;
    if (w->WI->WheelNumber < 2)
        return 1.0f;

    cs = (const CarState *)w->CS;
    t = (cs->ForwardSpeed - WHEEL_PILOT_SPEED) * WHEEL_PILOT_INV_SPAN;
    if (1.0f < t)
        t = 1.0f;
    else if (t < 0.0f)
        t = 0.0f;

    // The image calls fptodp/dpsub/dpmul/dpadd/dptofp here: the blend is
    // done in double and rounded once at the end, not in float. Spelling
    // it in float instead moves the last bit on most inputs.
    return (float)((double)gPilotFactor
                   + (1.0 - (double)gPilotFactor) * (double)t);
}

// --------------------------------------------------------- the tyre model

// The slip angle both force passes derive the same way: put the wheel's
// world velocity into the wheel's own frame, take the atan of its x and y,
// scale the BAM to radians and fold it into (-pi, pi].
static float wheel_slip_angle(Wheel *w, bVector3 *localVel)
{
    bMatrix4 t;
    float angle;

    bTransposeMatrix(&t, &w->WorldMatrix);
    t.v0.w = 0.0f;
    t.v1.w = 0.0f;
    t.v2.w = 0.0f;
    bMulMatrixVec3(localVel, &t, (const bVector3 *)&w->Velocity);

    angle = (float)bATan(localVel->x, localVel->y) * WHEEL_BAM_TO_RAD;
    if (WHEEL_IMAGE_PI < angle)
        angle -= WHEEL_IMAGE_TWO_PI;

    // Behind the wheel's own x axis the atan comes back off by half a
    // turn, and the correction is folded a second time. Both folds use the
    // object's pi, not bMath's.
    if (localVel->x < 0.0f) {
        angle += WHEEL_IMAGE_PI;
        if (WHEEL_IMAGE_PI < angle)
            angle -= WHEEL_IMAGE_TWO_PI;
    }
    return angle;
}

// 0x0019aa20. Two models behind gUseNewTireForces: one curve of force
// against slip angle, or seven curves of force against load picked by the
// slip angle and interpolated between.
float wheel_get_lateral_force(Wheel *w, float zforce, float slipAngle)
{
    if (gUseNewTireForces == 0) {
        float f = table_get_value(&gCorneringForce, slipAngle);
        return (gCorneringScale * f) * (w->ZForce * gZForceScale);
    }

    {
        const TireInfo *ti = w->TI;
        float load  = (zforce * gLoadFactor) / ti->MaxLoad;
        // `lui at,0x4140`: twelve, so a slip angle equal to the tyre's own
        // MaxSlipAngle lands the index on 6, the last curve, exactly.
        float scale = 12.0f / ti->MaxSlipAngle;
        float index = ((slipAngle * WHEEL_RAD_TO_DEG) * scale) * 0.5f;
        int32_t i   = (int32_t)index;          // cvt.w.s, toward zero
        float frac  = index - (float)i;

        // `slti` is signed and there is no floor on the index, only a
        // ceiling: a negative slip angle would index behind the array.
        // Every caller passes an absolute value, so it cannot happen in
        // the game; it is recorded rather than guarded because adding a
        // guard would be a change, not a port.
        if (i < 6) {
            float a = table_get_value(gLoadSensitivityTable[i], load);
            float b = table_get_value(gLoadSensitivityTable[i + 1], load);
            float v = a + frac * (b - a);
            return (w->TI->ForceScale * gNewCorneringScale) * v;
        }

        {
            float v = table_get_value(gLoadSensitivityTable[6], load);
            return (w->TI->ForceScale * gNewCorneringScale) * v;
        }
    }
}

// 0x0019a638. The bVector2 argument is never read; the results go into
// the wheel's own GroundForce and Slip.
void wheel_guess_ground_force(Wheel *w, const bVector2 *unused)
{
    bVector3 vel;
    float brakeTorque, ebrakeTorque, ebrakeMagnitude;
    float angle, slip, mag, vx, vy;
    // Only read on the path that sets `slipping`, which is the only path
    // that can reach them; initialised so the compiler can see that too.
    // dynamic starts at 1.0 because $f22 does -- `lui at,0x3f80` at
    // 0x0019a7e4, before the two early-outs. Nothing on those paths reads
    // it, so the value is unobservable; it is written the image's way
    // rather than a tidier one so the listing and the C agree on sight.
    float dynamic = 1.0f, maxForce = 0.0f, perSpeed = 0.0f, perMag = 0.0f;
    int slipping = 0;

    (void)unused;

    brakeTorque  = (gBrakingTorque * w->Brake) * w->CI->Brake;
    ebrakeTorque = (gEBrakingTorque * w->EBrake) * w->CI->EBrake;
    // Kept unsigned: the image tests $f22, the magnitude, against zero
    // further down, not the signed copy it added to the torque. The two
    // agree under `==` because -0.0f equals 0.0f, but only by accident.
    ebrakeMagnitude = ebrakeTorque;

    // Both brake torques oppose the spin, and both are refused outright
    // once the wheel has locked -- a locked wheel is stopped by
    // CheckForBrakeLock, not by more torque.
    if (0.0f < w->State.w)
        brakeTorque = -brakeTorque;
    if (w->BrakeLocked == 0)
        w->AppliedTorque += brakeTorque;

    if (0.0f < w->State.w)
        ebrakeTorque = -ebrakeTorque;
    else
        ebrakeTorque = +ebrakeTorque;
    if (w->BrakeLocked == 0)
        w->AppliedTorque += ebrakeTorque;

    angle = wheel_slip_angle(w, &vel);
    vx = vel.x;
    vy = vel.y;

    slip = w->State.w * w->WI->Radius - vx;
    w->CurrentSlip = slip;
    w->OldSlip = slip;

    // A wheel being dragged backwards hard, with no handbrake on, has its
    // driving torque cut to fifteen per cent rather than fighting.
    if (slip < -gMaxStaticSlip) {
        if (w->AppliedTorque < 0.0f && ebrakeMagnitude == 0.0f)
            w->AppliedTorque = w->AppliedTorque * WHEEL_REVERSE_DAMP;
    }

    slip = w->CurrentSlip;
    mag = sqrtf(slip * slip + vy * vy);

    if (mag == 0.0f)
        goto resolve;
    if (vy == 0.0f && vx == 0.0f)
        goto resolve;

    {
        float dynMul = 1.0f;
        if (gTerrainTypeInfoTable != NULL)
            dynMul = gTerrainTypeInfoTable[w->Terrain].DynamicFrictionMultiplier;

        dynamic = (w->TI->DynamicFrictionCoefficient
                   * w->CatchupFrictionMultiplier)
                  * (w->TractionBoost * dynMul);
        if (((const CarState *)w->CS)->DriverMode == 1)
            dynamic = dynamic * wheel_get_pilot_factor(w);
    }
    maxForce = (gZForceScale * w->ZForce) * dynamic;

    perMag   = maxForce / mag;
    perSpeed = maxForce / sqrtf(vx * vx + vy * vy);
    wheel_check_for_brake_lock(w, fabsf(vx) * perSpeed);

    if (gMaxStaticSlip < fabsf(slip))
        slipping = 1;
    else if (w->TI->MaxSlipAngle < fabsf(angle))
        slipping = 1;
    else if (w->BrakeLocked != 0)
        slipping = 1;

resolve:
    if (slipping) {
        // Sliding: the force is the friction circle pointed down the slip
        // vector, and below walking pace it is divided by the friction
        // again so a stationary car does not get shoved by its own tyres.
        float fx = perMag * slip;
        float fy = -perMag * vy;

        w->Slipping = 1;
        w->GroundForce[0] = fx;
        w->GroundForce[1] = fy;

        if (((const CarState *)w->CS)->ForwardSpeed * WHEEL_MPS_TO_MPH < 1.0f
            && 0.100000001f < dynamic) {
            w->GroundForce[1] = fy / dynamic;
            w->GroundForce[0] = fx / dynamic;
        }
        w->Slip[1] = vy;
        w->Slip[0] = slip;
    } else {
        // Gripping: the longitudinal force is whatever the driveline is
        // asking for, and the lateral one comes off the tyre curve.
        float lateral;
        float sign = -1.0f;

        w->Slipping = 0;
        if (0.0f < vx)
            sign = 1.0f;
        w->GroundForce[0] = w->AppliedTorque / w->WI->Radius;

        lateral = wheel_get_lateral_force(w, gZForceScale * w->ZForce,
                                          fabsf(angle));
        if (0.0f < angle)
            lateral = -lateral;
        w->GroundForce[1] = sign * lateral;
        w->Slip[1] = 0.0f;
        w->Slip[0] = 0.0f;
    }
}

// 0x0019ab80. The correction the integrator applies once it knows what
// the rest of the car did with the force this wheel asked for.
void wheel_modify_ground_force(Wheel *w, const bVector2 *v)
{
    bMatrix4 m;
    bVector3 in, out;
    float radius, moment, spin, delta;

    m.v0 = w->CarMatrix.v0;
    m.v1 = w->CarMatrix.v1;
    m.v2 = w->CarMatrix.v2;
    m.v3.x = 0.0f;
    m.v3.y = 0.0f;
    m.v3.z = 0.0f;
    m.v3.w = 1.0f;

    in.x = v->x;
    in.y = v->y;
    in.z = 0.0f;
    in.pad = 0.0f;
    bMulMatrixVec3(&out, &m, &in);

    radius = wheel_get_radius(w);
    moment = wheel_get_moment_of_inertia(w);

    spin  = w->AppliedTorque - w->GroundForce[0] * radius;
    spin  = spin / moment;
    delta = spin * w->WI->Radius;
    delta = delta - out.x;
    delta = delta * w->MomentOfInertia;
    delta = delta / w->WI->Radius;

    w->GroundForce[0] = w->GroundForce[0] + delta;
}

// 0x0019ac60. Clamps the force into the friction circle, records how much
// of the tyre is being used, and rotates the result into the world.
void wheel_finalize_ground_force(Wheel *w, int32_t slider)
{
    bMatrix4 frame;
    bVector3 localVel, force, world;
    float mag, maxForce, angle, lateralSin, lateralCos;
    int ellipsed = 0;

    // Driving torque widens the circle into an ellipse along the wheel's
    // own x. The widening is undone below if the clamp did not bite.
    if (0.0f < w->AppliedTorque && w->BrakeLocked == 0) {
        ellipsed = 1;
        w->GroundForce[0] = w->GroundForce[0] * gTireForceEllipseRatio;
    }

    mag = sqrtf(w->GroundForce[0] * w->GroundForce[0]
                + w->GroundForce[1] * w->GroundForce[1]);

    {
        float statMul = 1.0f;
        if (gTerrainTypeInfoTable != NULL)
            statMul = gTerrainTypeInfoTable[w->Terrain].StaticFrictionMultiplier;

        maxForce = ((gZForceScale * w->CatchupFrictionMultiplier)
                    * (statMul * w->TI->StaticFrictionCoefficient))
                   * (w->ZForce * w->TractionBoost);
        if (((const CarState *)w->CS)->DriverMode == 1)
            maxForce = maxForce * wheel_get_pilot_factor(w);
    }

    if (maxForce < mag && WHEEL_EPSILON < mag) {
        float k = maxForce / mag;
        w->GroundForce[0] = w->GroundForce[0] * k;
        w->GroundForce[1] = w->GroundForce[1] * k;
    } else if (ellipsed) {
        w->GroundForce[0] = w->GroundForce[0] / gTireForceEllipseRatio;
    }

    if (WHEEL_EPSILON < maxForce) {
        float u = mag / maxForce;
        w->TractionUsage = u;
        if (1.0f < u)
            w->TractionUsage = 1.0f;
    } else {
        w->TractionUsage = 1.0f;
    }

    // A wheel that is sliding or locked is using all of its tyre by
    // definition, and a wheel in the air is using none of it.
    if (!(w->Slipping == 0 && w->BrakeLocked == 0))
        w->TractionUsage = 1.0f;
    if (w->TouchingGround == 0)
        w->TractionUsage = 0.0f;

    angle = wheel_slip_angle(w, &localVel);

    lateralSin = bSinF(angle) * w->GroundForce[1];
    lateralCos = bSinF(angle + WHEEL_IMAGE_HALF_PI) * w->GroundForce[1];
    // The pair is stored to a stack vector that nothing reads -- a
    // debug leftover. Only the first is used, and only above walking pace.
    (void)lateralCos;

    if (1.0f < fabsf(localVel.x))
        w->GroundForce[0] = w->GroundForce[0] - lateralSin * 0.5f;

    // gWheelDebugInfo is 0 in the image; the arm behind it compares a
    // value and discards the result, so there is nothing to port.

    SetSliderValue(slider, 0.0f, 1.0f, w->TractionUsage);

    // Which frame the ground force is expressed in. The debug menu moves
    // gWheelForceFrame; the shipped build is 1, the wheel's own world
    // matrix, and the other three re-square it against the contact normal
    // in different ways. Anything outside 1..4 leaves the identity, which
    // puts the force in world axes unrotated.
    bIdentity(&frame);
    if (gWheelForceFrame == 1) {
        frame.v0 = w->WorldMatrix.v0;
        frame.v1 = w->WorldMatrix.v1;
        frame.v2 = w->WorldMatrix.v2;
    } else if (gWheelForceFrame == 2) {
        float d0 = dot3(&w->ContactNormal, &w->WorldMatrix.v0);
        float d1 = dot3(&w->ContactNormal, &w->WorldMatrix.v1);

        frame.v0.x = w->ContactNormal.x * -d0 + w->WorldMatrix.v0.x;
        frame.v0.y = w->ContactNormal.y * -d0 + w->WorldMatrix.v0.y;
        frame.v0.z = w->ContactNormal.z * -d0 + w->WorldMatrix.v0.z;
        frame.v0.w = 0.0f;

        frame.v1.x = w->ContactNormal.x * -d1 + w->WorldMatrix.v1.x;
        frame.v1.y = w->ContactNormal.y * -d1 + w->WorldMatrix.v1.y;
        frame.v1.z = w->ContactNormal.z * -d1 + w->WorldMatrix.v1.z;
        frame.v1.w = 0.0f;

        frame.v2 = w->ContactNormal;
        frame.v2.w = 0.0f;
    } else if (gWheelForceFrame == 3) {
        float d = dot3(&w->ContactNormal, &w->WorldMatrix.v0);

        frame.v0.x = w->ContactNormal.x * -d + w->WorldMatrix.v0.x;
        frame.v0.y = w->ContactNormal.y * -d + w->WorldMatrix.v0.y;
        frame.v0.z = w->ContactNormal.z * -d + w->WorldMatrix.v0.z;
        frame.v0.w = w->ContactNormal.w * -d + w->WorldMatrix.v0.w;
        normalize3(&frame.v0);
        frame.v0.w = 0.0f;

        frame.v2 = w->ContactNormal;
        frame.v2.w = 0.0f;

        cross3(&frame.v1, &frame.v2, &frame.v0);
        frame.v1.w = 0.0f;
    } else if (gWheelForceFrame == 4) {
        // Note the w lanes: rows 0 and 1 keep WorldMatrix's, only row 2's
        // is cleared. Frames 2 and 3 clear all three.
        frame.v0 = w->WorldMatrix.v0;
        frame.v1 = w->WorldMatrix.v1;
        frame.v2 = w->ContactNormal;
        frame.v2.w = 0.0f;
    }

    force.x = w->GroundForce[0];
    force.y = w->GroundForce[1];
    force.z = w->ZForce;
    force.pad = 0.0f;
    bMulMatrixVec3(&world, &frame, &force);
    w->WorldGroundForce.x = world.x;
    w->WorldGroundForce.y = world.y;
    w->WorldGroundForce.z = world.z;
    w->WorldGroundForce.w = world.pad;
}

// 0x0019b120 / 0x0019b1a8. The same function twice over two different
// matrices; the z lane of the input is zero, so only the horizontal part
// of the force is rotated.
static bVector3 *ground_force_in(const bMatrix4 *src, float fx, float fy,
                                 bVector3 *out)
{
    bMatrix4 m;
    bVector3 in;

    m.v0 = src->v0;
    m.v1 = src->v1;
    m.v2 = src->v2;
    m.v3.x = 0.0f;
    m.v3.y = 0.0f;
    m.v3.z = 0.0f;
    m.v3.w = 1.0f;

    in.x = fx;
    in.y = fy;
    in.z = 0.0f;
    in.pad = 0.0f;
    bMulMatrixVec3(out, &m, &in);
    return out;
}

bVector3 *wheel_get_horizontal_ground_force_world(Wheel *w, bVector3 *out)
{
    return ground_force_in(&w->WorldMatrix, w->GroundForce[0],
                           w->GroundForce[1], out);
}

bVector3 *wheel_get_horizontal_ground_force_car(Wheel *w, bVector3 *out)
{
    return ground_force_in(&w->CarMatrix, w->GroundForce[0],
                           w->GroundForce[1], out);
}

// 0x0019b2c8 and 0x0019b548. Both are `jr ra` in the shipped image: the
// particle work they used to do was compiled out, unlike MaybeMakeSkids,
// which still has a body and is a seam until task 27.
void wheel_maybe_make_smoke(Wheel *w, float v)
{
    (void)w;
    (void)v;
}

void wheel_maybe_make_tire_spew(Wheel *w, float v)
{
    (void)w;
    (void)v;
}

void wheel_maybe_make_skids(Wheel *w, float dt)
{
    if (gWheelMaybeMakeSkidsFn)
        gWheelMaybeMakeSkidsFn(w, dt);
}

// Retail's 0x001a3f60 (the demo's 0x00199c90), the replay's. The int move
// is MoveData(int *, int) with 4: LastSign alone, four bytes. Taking or
// restoring then clears the rest of the record but MomentOfInertia,
// LastSign, RoadNoise and the pad behind GroundForce; retail's last clear,
// Damage, is new.
void wheel_do_snapshot(Wheel *w, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "Wheel");

    // One MoveData each, not the 64-bit pair move SetState/GetState use.
    ReplaySnapshot_MoveFloat(s, &w->State.a);
    ReplaySnapshot_MoveFloat(s, &w->State.w);
    ReplaySnapshot_MoveInt(s, &w->LastSign, 4);

    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        // Twenty-four bMemSet calls, in the image's order. Written as the
        // fields they clear rather than as offsets and lengths, because
        // the offsets move on a 64-bit host and the fields do not.
        memset(&w->Matrix, 0, sizeof w->Matrix);
        memset(&w->WorldMatrix, 0, sizeof w->WorldMatrix);
        memset(&w->CarMatrix, 0, sizeof w->CarMatrix);
        memset(&w->Velocity, 0, sizeof w->Velocity);
        w->Slip[0] = 0.0f;
        w->Slip[1] = 0.0f;
        w->AppliedTorque = 0.0f;
        w->BrakeLocked = 0;
        w->GroundForce[0] = 0.0f;
        w->GroundForce[1] = 0.0f;
        memset(&w->WorldGroundForce, 0, sizeof w->WorldGroundForce);
        memset(&w->ContactPoint, 0, sizeof w->ContactPoint);
        memset(&w->ContactNormal, 0, sizeof w->ContactNormal);
        w->Terrain = 0;
        w->Slipping = 0;
        w->TouchingGround = 0;
        w->NumTimesSkidding = 0;
        w->ZForce = 0.0f;
        w->CurrentSlip = 0.0f;
        w->OldSlip = 0.0f;
        w->TractionUsage = 0.0f;
        w->Brake = 0.0f;
        w->EBrake = 0.0f;
        // To zero, not to the 1.0 the constructor gave them. A wheel
        // restored from a rewind has no grip multiplier at all until
        // something outside this object writes one, and nothing in here
        // does.
        w->TractionBoost = 0.0f;
        w->CatchupFrictionMultiplier = 0.0f;
        w->Damage = 0.0f;
    }

    ReplaySnapshot_EndNamedSection(s);
}

// 0x00199e90. Places the wheel from a CarState: the replay and network
// path, and the only method in the object that learns a terrain type.
void wheel_set_state_from_car_state(Wheel *w, void *carState, void *cti,
                                    float angle, float angularVelocity,
                                    uint16_t steeringAngle,
                                    float suspensionHeight)
{
    CarState *cs = (CarState *)carState;
    int32_t n = w->WI->WheelNumber;
    bMatrix4 place;
    bMatrix4 world;
    bVector4 r;
    bVector4 c;
    bVector3 normal;
    bVector4 contact;
    int32_t terrain = 0;
    float elev;

    // The CarTypeInfo arrives in a2 and nothing ever reads it -- a2 is
    // overwritten with a stack address before the first use.
    (void)cti;

    wheel_set_state2(w, angle, angularVelocity);

    cs->SteeringAngle = steeringAngle;
    cs->WheelAngularVelocity[n] = angularVelocity;
    cs->WheelAngle[n] = angle;
    cs->WheelSuspensionHeight[n] = suspensionHeight;
    carstate_calculate_wheel_matrices_one(cs, n);

    // The body's rotation with the car's position as its translation. Row
    // 3 is loaded as a quadword from Position -- so its fourth lane is
    // bVector3::pad -- and then the w is forced to 1.0 by a separate
    // store.
    place.v0 = cs->BodyMatrix.v0;
    place.v1 = cs->BodyMatrix.v1;
    place.v2 = cs->BodyMatrix.v2;
    place.v3.x = cs->Position.x;
    place.v3.y = cs->Position.y;
    place.v3.z = cs->Position.z;
    place.v3.w = 1.0f;

    // eMulMatrix(o, a, b) is o = a * b -- see emath.h. The wheel's own
    // matrix first, then the body's placement.
    eMulMatrix(&world, &cs->WheelMatrix[n], &place);

    w->CarMatrix = cs->WheelMatrix[n];
    w->WorldMatrix = world;

    // r is a four-lane subtract, so its w is world.v3.w minus Position's
    // pad rather than zero.
    r.x = world.v3.x - cs->Position.x;
    r.y = world.v3.y - cs->Position.y;
    r.z = world.v3.z - cs->Position.z;
    r.w = world.v3.w - cs->Position.pad;

    // vopmula.xyz ACC,vf01,vf03 / vopmsub.xyz vf01,vf03,vf01 with r in the
    // first operand, so this is r x omega and not the omega x r that
    // Suspension::GetPointVelocity computes. The port takes it in the
    // image's order rather than deciding which one is right. xyz only, so
    // the w survives from r.
    c.x = r.y * cs->AngularVelocity.z - cs->AngularVelocity.y * r.z;
    c.y = r.z * cs->AngularVelocity.x - cs->AngularVelocity.z * r.x;
    c.z = r.x * cs->AngularVelocity.y - cs->AngularVelocity.x * r.y;
    c.w = r.w;

    w->Velocity.x = c.x + cs->Velocity.x;
    w->Velocity.y = c.y + cs->Velocity.y;
    w->Velocity.z = c.z + cs->Velocity.z;
    w->Velocity.w = c.w + cs->Velocity.pad;

    // A terrain out-parameter again, but a stack slot this time --
    // `addiu a2,sp,192` -- rather than the wheel's own field, which
    // CheckTerrain forwards. The topology comes straight
    // out of CarState rather than through the seam CheckTerrain needs,
    // because here the CarState is typed.
    if (gTopologyGetElevationFn != NULL) {
        elev = gTopologyGetElevationFn(cs->pTopologyCoordinate,
                                       (const bVector3 *)&world.v3,
                                       &terrain, &normal);
    } else {
        elev = 0.0f;
        normal.x = 0.0f;
        normal.y = 0.0f;
        normal.z = 1.0f;
        normal.pad = 0.0f;
    }

    carstate_set_wheel_touching_ground(cs, n, 1);
    carstate_set_wheel_terrain(cs, n, terrain);

    contact.x = world.v3.x;
    contact.y = world.v3.y;
    contact.z = elev;
    // sp+172 is never written by this function; the quadword store that
    // follows picks up whatever the stack held. A defined zero is written
    // instead, and the mutation list checks that claim rather than
    // asserting it.
    contact.w = 0.0f;

    w->ContactPoint = contact;
    w->ContactNormal.x = normal.x;
    w->ContactNormal.y = normal.y;
    w->ContactNormal.z = normal.z;
    w->ContactNormal.w = normal.pad;
    w->Terrain = terrain;
    // Unconditionally. This function does not check whether the wheel
    // reached the ground -- the state it is restoring already decided.
    w->TouchingGround = 1;
}

// -------------------------------------------------------- the accessors

float wheel_get_moment_of_inertia(const Wheel *w) { return w->MomentOfInertia; }
float wheel_get_damage(const Wheel *w)            { return w->Damage; }
void  wheel_set_damage(Wheel *w, float v)         { w->Damage = v; }

int32_t wheel_is_steering_wheel(const Wheel *w)
{
    return w->WI->WheelNumber < 2;
}

int32_t wheel_is_drive_wheel(const Wheel *w)
{
    return (w->WI->WheelNumber < 2) ^ 1;
}

float wheel_get_old_slip(const Wheel *w)     { return w->OldSlip; }
float wheel_get_current_slip(const Wheel *w) { return w->CurrentSlip; }
void  wheel_set_slipping(Wheel *w, uint8_t v) { w->Slipping = v; }
int8_t wheel_is_slipping(const Wheel *w)     { return (int8_t)w->Slipping; }

// Refused while the wheel is locked, like the brake torques.
void wheel_apply_torque(Wheel *w, float t)
{
    if (w->BrakeLocked == 0)
        w->AppliedTorque = w->AppliedTorque + t;
}

float wheel_get_z_force(const Wheel *w) { return w->ZForce; }

// There is no mass field. The image returns a literal 1.0.
float wheel_get_mass(const Wheel *w) { (void)w; return 1.0f; }

float wheel_get_radius(const Wheel *w) { return w->WI->Radius; }

bVector4 *wheel_get_contact_normal(Wheel *w)     { return &w->ContactNormal; }
bVector4 *wheel_get_contact_point(Wheel *w)      { return &w->ContactPoint; }
bVector4 *wheel_get_ground_force_vector(Wheel *w) { return &w->WorldGroundForce; }

// WheelInfo's first three floats are the position, so the image hands the
// WheelInfo back and lets the caller read it as a vector.
const bVector3 *wheel_get_rest_position_in_geometry_frame(const Wheel *w)
{
    return (const bVector3 *)w->WI;
}

void wheel_set_contact_normal(Wheel *w, const bVector4 *v) { w->ContactNormal = *v; }
void wheel_set_contact_point(Wheel *w, const bVector4 *v)  { w->ContactPoint = *v; }
void wheel_set_velocity(Wheel *w, const bVector4 *v)       { w->Velocity = *v; }
void wheel_set_car_matrix(Wheel *w, const bMatrix4 *m)     { w->CarMatrix = *m; }
void wheel_set_world_matrix(Wheel *w, const bMatrix4 *m)   { w->WorldMatrix = *m; }

void   wheel_set_touching_ground(Wheel *w, uint8_t v) { w->TouchingGround = v; }
int8_t wheel_is_touching_ground(const Wheel *w) { return (int8_t)w->TouchingGround; }
void   wheel_set_terrain(Wheel *w, int32_t t)   { w->Terrain = t; }
int32_t wheel_get_terrain(const Wheel *w)       { return w->Terrain; }

float wheel_get_road_noise(const Wheel *w)
{
    return w->TouchingGround != 0 ? w->RoadNoise : 0.0f;
}

// CurrentSlip is written from Slip[0] by a second load of the same word,
// not from the register the first store used.
void wheel_set_slip(Wheel *w, const bVector2 *v)
{
    w->Slip[0] = v->x;
    w->Slip[1] = v->y;
    w->CurrentSlip = v->x;
}

float *wheel_get_slip(Wheel *w)             { return w->Slip; }
float wheel_get_traction_usage(const Wheel *w) { return w->TractionUsage; }

int32_t wheel_modifiable(const Wheel *w)
{
    if (w->Slipping != 0)
        return 0;
    return w->BrakeLocked == 0;
}

bMatrix4 *wheel_get_matrix(Wheel *w)     { return &w->Matrix; }
bMatrix4 *wheel_get_car_matrix(Wheel *w) { return &w->CarMatrix; }
float wheel_get_applied_torque(const Wheel *w) { return w->AppliedTorque; }

float wheel_get_torque_response(const Wheel *w)
{
    return 1.0f / wheel_get_moment_of_inertia(w);
}

float wheel_get_angular_acceleration(const Wheel *w)
{
    float r = wheel_get_radius(w);
    float m = wheel_get_moment_of_inertia(w);
    return (w->AppliedTorque - w->GroundForce[0] * r) / m;
}

float wheel_get_angular_velocity(const Wheel *w) { return w->State.w; }
float wheel_get_rotation(const Wheel *w)         { return w->State.a; }

void wheel_set_catchup_friction_multiplier(Wheel *w, float v)
{
    w->CatchupFrictionMultiplier = v;
}

void wheel_adjust_traction_boost(Wheel *w, float v)
{
    w->TractionBoost = w->TractionBoost * v;
}

void  wheel_set_traction_boost(Wheel *w, float v) { w->TractionBoost = v; }
float wheel_get_ebrake(const Wheel *w)            { return w->EBrake; }
void  wheel_set_ebrake(Wheel *w, float v)         { w->EBrake = v; }
void  wheel_set_brake(Wheel *w, float v)          { w->Brake = v; }
