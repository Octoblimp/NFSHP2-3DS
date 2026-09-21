// carstate -- CarState.obj (0x001b6170 .. 0x001b6f60). See carstate.h for
// what the object is and docs/formats/car-state.md for how it was read.
#include "carstate.h"

#include <string.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bvector.h"
#include "emath.h"

// --------------------------------------------------------- the constants
//
// Four floats out of this object's corner of the constant pool:
//
//   0x003219e8  0x38c90fdb   2pi/65536, BAM -> radians
//   0x003219ec  0x40490fd0   pi
//   0x003219f0  0x40c90fd0   2pi
//   0x003219f4  0x4622f983   65536/2pi, radians -> BAM
//
// The two scales are bit-identical to bMath's own copies, so they are taken
// from bmath.h rather than spelled again here.
//
// The middle two are NOT. bMath holds 0x40490fdb and 0x40c90fdb, which are
// float(pi) and float(2pi) correctly rounded; CarState's pool holds
// 0x40490fd0 and 0x40c90fdb's cousin 0x40c90fd0, which are not. Whoever
// wrote this file spelled the digits out by hand and got the low bits
// wrong, and every yaw the game ever wrapped carries that. They are
// deliberately not shared with bMath and deliberately not M_PI: either
// substitution moves the result of GetYawAlways for every angle that
// wraps. The cross-checker has a mutation for exactly this.

static float carstate_f32(uint32_t bits)
{
    float f;
    memcpy(&f, &bits, sizeof f);
    return f;
}

#define BAM_TO_RAD  BMATH_BAM_TO_RAD
#define RAD_TO_BAM  BMATH_RAD_TO_BAM
#define IMAGE_PI    carstate_f32(0x40490fd0u)
#define IMAGE_TWOPI carstate_f32(0x40c90fd0u)

// GetYaw's cutoff, 0x40a00000.
#define YAW_MIN_SPEED 5.0f

// ---------------------------------------------------------------- lifetime

// 0x001b6170. The listing opens with three empty countdown loops -- the
// compiler's leavings from inlining bVector3's do-nothing constructor three
// times -- which is why nothing here corresponds to them.
void carstate_init(CarState *s, TopologyCoordinate *topo,
                   CarTypeInfoPrefix *info)
{
    s->Odometer = 0.0f;

    s->Position.x = 0.0f;
    s->Position.y = 0.0f;
    s->Position.z = 0.0f;

    s->GeometryPosition.x = 0.0f;
    s->GeometryPosition.y = 0.0f;
    s->GeometryPosition.z = 0.0f;

    s->DriverMode = 0;

    s->pTopologyCoordinate = topo;
    s->pCarInfo            = info;

    carstate_reset_car(s);
}

// 0x001b6570.
void carstate_reset_car(CarState *s)
{
    int i;

    s->Velocity.x = 0.0f;
    s->Velocity.y = 0.0f;
    s->Velocity.z = 0.0f;

    s->Acceleration.x = 0.0f;
    s->Acceleration.y = 0.0f;
    s->Acceleration.z = 0.0f;

    bIdentity(&s->BodyMatrix);

    s->AngularVelocity.x = 0.0f;
    s->AngularVelocity.y = 0.0f;
    s->AngularVelocity.z = 0.0f;

    s->AngularAcceleration.x = 0.0f;
    s->AngularAcceleration.y = 0.0f;
    s->AngularAcceleration.z = 0.0f;

    s->Angle         = 0;
    s->SteeringAngle = 0;

    for (i = 0; i < 4; i++) {
        s->WheelAngularVelocity[i]    = 0.0f;
        s->WheelAngle[i]              = 0.0f;
        s->WheelZForce[i]             = 0.0f;
        s->WheelRoadNoise[i]          = 0.0f;
        s->WheelBottomOutMagnitude[i] = 0.0f;
        s->WheelSuspensionHeight[i]   = 0.0f;
        s->WheelTractionUsage[i]      = 0.0f;
        s->WheelTouchingGround[i]     = 1;
        s->WheelTerrain[i]            = TERRAIN_DEFAULT;
        s->CrossedWheelTerrain[i]     = TERRAIN_DEFAULT;
        s->WheelSlip[i].x             = 0.0f;
        s->WheelSlip[i].y             = 0.0f;
    }

    s->nWheelsTouchingGround = 4;

    carstate_calculate_wheel_matrices(s);

    s->TractionUsage   = 0.0f;
    s->SkidLeft        = 0.0f;
    s->SkidRight       = 0.0f;
    s->ForwardSpeed    = 0.0f;
    s->VelocityMagnitude = 0.0f;
    s->Throttle        = 0.0f;
    s->BurnOutState    = 0;
    s->BurnOutTime     = 0.0f;

    s->RPM             = 1000.0f;
    s->RedLineSyncRPM  = -1.0f;
    s->ClutchEngaged   = 1;
    s->BurnOutTraction = 1.0f;
    s->CurrentGear     = 1;
    s->BoostFactor     = 1.0f;

    // bMemSet in the original, which is plain memset over the 64 bytes.
    memset(&s->RelCoordMatrix, 0, 64);
    s->MatrixValid = 0;
}

// 0x001b6718. ResetCar's wheel loop minus WheelRoadNoise, plus RPM, and
// none of the body, matrix or drivetrain work. The omission of road noise
// is deliberate in the original -- the sound driver is mid-crossfade on it
// when this is called -- and BurnOut, gear, clutch and boost are left alone
// for the same reason. It also does not rebuild the wheel matrices, so a
// caller that wants them rebuilt has to say so.
void carstate_reset_car_for_sound(CarState *s)
{
    int i;

    s->RPM = 1000.0f;

    for (i = 0; i < 4; i++) {
        s->WheelAngularVelocity[i]    = 0.0f;
        s->WheelAngle[i]              = 0.0f;
        s->WheelZForce[i]             = 0.0f;
        s->WheelBottomOutMagnitude[i] = 0.0f;
        s->WheelSuspensionHeight[i]   = 0.0f;
        s->WheelTractionUsage[i]      = 0.0f;
        s->WheelTouchingGround[i]     = 1;
        s->WheelTerrain[i]            = TERRAIN_DEFAULT;
        s->CrossedWheelTerrain[i]     = TERRAIN_DEFAULT;
        s->WheelSlip[i].x             = 0.0f;
        s->WheelSlip[i].y             = 0.0f;
    }

    s->SkidRight             = 0.0f;
    s->nWheelsTouchingGround = 4;
    s->VelocityMagnitude     = 0.0f;
    s->TractionUsage         = 0.0f;
    s->SkidLeft              = 0.0f;
}

// 0x001b67e8. The original counts down from wheel 3 to wheel 0; the order
// cannot matter, but it is written the same way so the transcript is.
void carstate_begin_timestep(CarState *s)
{
    int i;

    for (i = 3; i >= 0; i--)
        s->CrossedWheelTerrain[i] = TERRAIN_DEFAULT;
}

// ------------------------------------------------------------------- yaw

// 0x001b6820.
float carstate_get_yaw(CarState *s)
{
    if (s->ForwardSpeed < YAW_MIN_SPEED)
        return 0.0f;

    return carstate_get_yaw_always(s);
}

// 0x001b6868. bATan takes (x, y) in that order and returns a BAM, so the
// subtraction below is BAM arithmetic and the mask is the wrap. Only then
// does it become radians.
float carstate_get_yaw_always(CarState *s)
{
    int32_t  heading = bATan(s->Velocity.x, s->Velocity.y);
    uint16_t delta   = (uint16_t)((uint32_t)s->Angle - (uint32_t)heading);
    float    rad     = (float)(int32_t)delta * BAM_TO_RAD;

    // One-sided: the result is (-pi, pi] coming out of a full turn's worth
    // of BAM, so only the top half needs folding.
    if (IMAGE_PI < rad)
        rad -= IMAGE_TWOPI;

    return rad;
}

// ------------------------------------------------------- the cached basis

// 0x001b68d0. Two ways to the same matrix. Above walking pace the car's
// basis is taken from where it is *going*, which keeps a drifting car's
// relative coordinates aligned with its path rather than its bodywork;
// below it, from where it points, because a stationary car has no direction
// of travel. The threshold is on the squared length, against 1.0.
bMatrix4 *carstate_get_transform_matrix(CarState *s)
{
    bVector4 v;
    float    lensq;

    if (s->MatrixValid)
        return &s->RelCoordMatrix;

    // The original loads Velocity as a quadword, so the fourth lane is
    // Velocity.pad. It only ever reads x and y back out, so the pad's value
    // cannot reach the result -- but it is negated along with the rest.
    v.x = s->Velocity.x;
    v.y = s->Velocity.y;
    v.z = s->Velocity.z;
    v.w = s->Velocity.pad;

    if (s->ForwardSpeed < 0.0f) {
        // vsub.xyzw vf01,vf00,vf01 against VU0's constant register: xyz are
        // negated and w becomes 1 - w. Reversing is a heading flip, done by
        // flipping the velocity rather than the angle.
        v.x = 0.0f - v.x;
        v.y = 0.0f - v.y;
        v.z = 0.0f - v.z;
        v.w = 1.0f - v.w;
    }

    bIdentity(&s->RelCoordMatrix);

    lensq = v.x * v.x + v.y * v.y + v.z * v.z;

    if (1.0f < lensq) {
        s->RelCoordMatrix.v0.x =  v.y;
        s->RelCoordMatrix.v0.y = -v.x;
        s->RelCoordMatrix.v0.z =  0.0f;
        s->RelCoordMatrix.v0.w =  0.0f;

        s->RelCoordMatrix.v1.x =  v.x;
        s->RelCoordMatrix.v1.y =  v.y;
        s->RelCoordMatrix.v1.z =  0.0f;
        s->RelCoordMatrix.v1.w =  0.0f;
    } else {
        float c = bCosBam(s->Angle);
        float n = bSinBam(s->Angle);

        s->RelCoordMatrix.v0.x =  n;
        s->RelCoordMatrix.v0.y = -c;
        s->RelCoordMatrix.v0.z =  0.0f;
        s->RelCoordMatrix.v0.w =  0.0f;

        s->RelCoordMatrix.v1.x =  c;
        s->RelCoordMatrix.v1.y =  n;
        s->RelCoordMatrix.v1.z =  0.0f;
        s->RelCoordMatrix.v1.w =  0.0f;
    }

    s->RelCoordMatrix.v2.x = 0.0f;
    s->RelCoordMatrix.v2.y = 0.0f;
    s->RelCoordMatrix.v2.z = 1.0f;
    s->RelCoordMatrix.v2.w = 0.0f;

    s->RelCoordMatrix.v3.x = 0.0f;
    s->RelCoordMatrix.v3.y = 0.0f;
    s->RelCoordMatrix.v3.z = 0.0f;
    s->RelCoordMatrix.v3.w = 1.0f;

    eOrthonormalizeMatrix(&s->RelCoordMatrix, &s->RelCoordMatrix);

    s->MatrixValid = 1;
    return &s->RelCoordMatrix;
}

// ------------------------------------------------------------- transforms

// 0x001b6ab0.
void carstate_world_to_car2(CarState *s, bVector2 *out, const bVector2 *in)
{
    bMatrix4 t;
    bVector3 d, r;

    bTransposeMatrix(&t, carstate_get_transform_matrix(s));

    d.x   = in->x - s->Position.x;
    d.y   = in->y - s->Position.y;
    d.z   = 0.0f;
    d.pad = 0.0f;

    eMulVector3(&r, &t, &d);

    out->x = r.x;
    out->y = r.y;
}

// 0x001b6b40. The 3D overload subtracts Position as a quadword, so the pad
// takes part; it is written back out as part of the result vector.
void carstate_world_to_car3(CarState *s, bVector3 *out, const bVector3 *in)
{
    bMatrix4 t;
    bVector3 d, r;

    bTransposeMatrix(&t, carstate_get_transform_matrix(s));

    d.x   = in->x   - s->Position.x;
    d.y   = in->y   - s->Position.y;
    d.z   = in->z   - s->Position.z;
    d.pad = in->pad - s->Position.pad;

    eMulVector3(&r, &t, &d);

    *out = r;
}

// 0x001b6bb0.
void carstate_car_to_world_unadjusted(CarState *s, bVector2 *out,
                                      const bVector2 *in)
{
    bMatrix4 *m = carstate_get_transform_matrix(s);
    bVector3  v, r;

    v.x   = in->x;
    v.y   = in->y;
    v.z   = 0.0f;
    v.pad = 0.0f;

    eMulVector3(&r, m, &v);

    out->x = r.x;
    out->y = r.y;
}

// 0x001b6c18. Returns bVector2 by value in the original, through a hidden
// first argument; written through `out` here.
void carstate_car_to_world(CarState *s, bVector2 *out, const bVector2 *in)
{
    bVector2 t;

    carstate_car_to_world_unadjusted(s, &t, in);

    out->x = t.x + s->Position.x;
    out->y = t.y + s->Position.y;
}

// ----------------------------------------------------------------- wheels

// 0x001b6c90. The count only moves on a transition, which is what makes
// writing WheelTouchingGround directly a bug rather than a shortcut.
void carstate_set_wheel_touching_ground(CarState *s, int wheel, int8_t on)
{
    int8_t was = s->WheelTouchingGround[wheel];

    s->WheelTouchingGround[wheel] = on;

    if (was == 0) {
        if (on != 0)
            s->nWheelsTouchingGround++;
    } else {
        if (on == 0)
            s->nWheelsTouchingGround--;
    }
}

// 0x001b6ce0.
void carstate_set_wheel_terrain(CarState *s, int wheel, TerrainType t)
{
    s->WheelTerrain[wheel] = t;

    if (s->CrossedWheelTerrain[wheel] < t)
        s->CrossedWheelTerrain[wheel] = t;
}

// 0x001b6d10. WheelMatrix gets spin, steering and the suspension lift;
// BrakeMatrix gets steering only, at the unlifted hub. Wheels 0 and 1 are
// the steering pair.
//
// The two matrices start from eIdentity, not bIdentity -- the same result
// by a different route, and the original calls the eMath one here and the
// bMath one in ResetCar.
void carstate_calculate_wheel_matrices_one(CarState *s, int wheel)
{
    const WheelInfo *wi;
    bMatrix4 wm, bm;
    uint16_t spin;

    eIdentity(&wm);
    eIdentity(&bm);

    // WheelAngle is radians; the rotate takes a BAM. The truncation is the
    // original's cvt.w.s, which rounds toward zero, and the mask is its
    // andi -- so a large angle wraps rather than saturating.
    spin = (uint16_t)((int32_t)(s->WheelAngle[wheel] * RAD_TO_BAM) & 0xffff);

    eRotateY(&wm, &wm, spin);

    if (wheel < 2) {
        eRotateZ(&wm, &wm, s->SteeringAngle);
        eRotateZ(&bm, &bm, s->SteeringAngle);
    }

    wi = &s->pCarInfo->Wheels[wheel];

    // Both row 3s come off the same quadword load, so the fourth lane is
    // WheelInfo.Radius for exactly as long as it takes to overwrite it.
    bm.v3.x = wi->PositionX;
    bm.v3.y = wi->PositionY;
    bm.v3.z = wi->PositionZ;
    bm.v3.w = 1.0f;

    wm.v3.x = wi->PositionX;
    wm.v3.y = wi->PositionY;
    wm.v3.z = wi->PositionZ + s->WheelSuspensionHeight[wheel];
    wm.v3.w = 1.0f;

    s->WheelMatrix[wheel] = wm;
    s->BrakeMatrix[wheel] = bm;
}

// 0x001b6e58.
void carstate_calculate_wheel_matrices(CarState *s)
{
    int i;

    for (i = 0; i < 4; i++)
        carstate_calculate_wheel_matrices_one(s, i);
}

// 0x001b6ea8. The simulation tracks the centre of gravity; the model was
// drawn around a different origin. This is the difference, rotated into
// world space and subtracted.
void carstate_calculate_geometry_position(CarState *s)
{
    bVector3 cog;

    bMulMatrixVec3(&cog, &s->BodyMatrix, &s->pCarInfo->CenterOfGravity);

    s->GeometryPosition.x   = s->Position.x   - cog.x;
    s->GeometryPosition.y   = s->Position.y   - cog.y;
    s->GeometryPosition.z   = s->Position.z   - cog.z;
    s->GeometryPosition.pad = s->Position.pad - cog.pad;
}

// 0x001b6c88. Empty in the shipped build.
void carstate_print_state(CarState *s)
{
    (void)s;
}
