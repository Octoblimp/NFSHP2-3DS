// cartrack -- Car.obj, slices five and seven: the methods that stand the
// car on the ground, and the two that ask it what is under a car in the
// air and at the start of a step.
//
// These are Car's and live in Car.obj, but they are the first of its
// methods to reach into TopologyCoordinate (track.c, task 27). Kept out of
// car.c for the same reason carmodes.c is: car.c links into half a dozen
// checkers that have no business carrying the topology, its slot pool and
// the terrain table with them.
//
// Prototypes: car.h. Cross-check: tools/track_check.py, which has the
// topology loaded already. Write-up: docs/formats/car.md.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "car.h"
#include "carstate.h"
#include "eefpu.h"
#include "emath.h"
#include "rigidbody.h"
#include "topology.h"

// gp-31948 (the demo's gp-32036), 0x46230eac: 65536 / 6.28 in float, the
// BAMs in a radian with 6.28 standing in for two pi. It is 0.05% more than
// 65536 / (2 pi), so a slope comes out a little steeper than it is. Kept.
#define CAR_BAMS_PER_RADIAN 10435.66796875f

// AverageAir's two pool constants: gp-31820, 0x3e99999a, the share of the
// two downforces that counts against the fall, and gp-31816, 0x3eaaaaab,
// the samples per unit of speed times time. The quarter that averages the
// four wheels and the 1 taken off the mean are literals.
#define CAR_AIR_DOWNFORCE_SHARE 0.300000012f
#define CAR_AIR_SAMPLE_RATE     0.333333343f

// BeginMovement's interest box: gp-31992, 0x3d4ccccd, times the speed,
// plus a literal 3.
#define CAR_INTEREST_PER_SPEED  0.0500000007f
#define CAR_INTEREST_BASE       3.0f

// Retail's 0x001326d8 (the demo's 0x00130c58), the same code. Samples the
// ground at pos and a unit step either side of it along x and along y,
// puts pos.z at the centre height plus Wheels[3]'s radius, less its z,
// plus the centre of gravity's z, and makes m the rotation that yaws by
// `angle` and tilts to the two slopes. Only pos.z is written, and m is
// overwritten entirely.
//
// GetElevation is asked for the terrain only, into a local nobody reads.
// The probe's fourth lane is left as the stack had it; GetElevation reads
// x, y and z only, so here it is 0. The image walks its five-element offset
// array once with an empty body before filling it -- the loop an empty
// constructor leaves -- and that is not written out.
//
// The two slopes are each a difference of differences, h1 - h0 less h2 - h0
// and h3 - h0 less h4 - h0, and not h1 - h2: in float the two differ. The
// x slope (east less west) becomes a tilt about y and is negated; the y
// slope becomes a tilt about x as it is. Each truncates through cvt.w.s,
// and only its low sixteen bits are the BAM.
void car_find_flat_on_track_position(Car *c, bMatrix4 *m, bVector3 *pos,
                                     uint16_t angle, TopologyCoordinate *tc)
{
    static const float offs[5][2] = {
        { 0.0f, 0.0f }, { 1.0f, 0.0f }, { -1.0f, 0.0f },
        { 0.0f, 1.0f }, { 0.0f, -1.0f },
    };
    const CarTypeInfo *cti;
    bMatrix4 local;
    bVector3 probe;
    int32_t terrain[5];
    float h[5];
    uint16_t pitch, roll;
    int32_t i;

    for (i = 0; i < 5; i++) {
        probe.x = offs[i][0] + pos->x;
        probe.y = offs[i][1] + pos->y;
        probe.z = pos->z;
        probe.pad = 0.0f;
        h[i] = topology_get_elevation(tc, &probe, &terrain[i], NULL, NULL);
    }

    cti = c->pCarTypeInfo;
    // `subu s1,zero,s1`: a negation that wraps, so unsigned.
    roll = (uint16_t)(0u - (uint32_t)ee_trunc_w(
               (((h[1] - h[0]) - (h[2] - h[0])) * 0.5f) * CAR_BAMS_PER_RADIAN));
    pitch = (uint16_t)ee_trunc_w(
               (((h[3] - h[0]) - (h[4] - h[0])) * 0.5f) * CAR_BAMS_PER_RADIAN);
    pos->z = ((h[0] + cti->Wheels[3].Radius) - cti->Wheels[3].PositionZ)
             + cti->CenterOfGravity.z;

    eIdentity(&local);
    eRotateZ(&local, &local, angle);
    eRotateX(&local, &local, pitch);
    eRotateY(m, &local, roll);
}

// Retail's 0x00132910 (the demo's 0x00130e90). FindFlatOnTrackPosition on
// the car's own body matrix, position, heading and topology, then
// GeometryPosition = Position less the centre of gravity -- in body space,
// not rotated into the world the way CarState::CalculateGeometryPosition
// does it. The subtract is `vsub.xyzw`, so the fourth lane is Position's
// less CenterOfGravity's.
void car_put_flat_on_track(Car *c)
{
    CarState *st = &c->State;
    const bVector3 *cog = &c->pCarTypeInfo->CenterOfGravity;

    car_find_flat_on_track_position(c, &st->BodyMatrix, &st->Position,
                                    st->Angle, &c->TheTopologyCoordinate);
    st->GeometryPosition.x   = st->Position.x   - cog->x;
    st->GeometryPosition.y   = st->Position.y   - cog->y;
    st->GeometryPosition.z   = st->Position.z   - cog->z;
    st->GeometryPosition.pad = st->Position.pad - cog->pad;
}

// Retail's 0x00135b30 (the demo's 0x00133e48). How far off the ground the
// car will be, on average, over the next `*time` seconds of free flight;
// FinishMovement is its one caller.
//
// The starting point is the mean of the four wheels' lowest points: each
// is (0, 0, -radius) put through a wheel matrix and then through the body
// matrix with Position for its translation row and 1 for that row's w.
// The wheel matrix is WheelMatrix[0] for all four -- the image loads its
// address once, before the loop, and the loop only steps through the
// radii -- so the four points differ by their radii alone. Kept.
//
// From there the flight is p + (v + g t) t, where g is straight down by
// gravity plus the two downforces' share scaled by speed over mass. There
// is no half on the g t squared term. The flight is sampled
// trunc(speed * time / 3) times over [0, time]. A sample at or below the
// ground ends it, and puts that sample's time in *time. *height gets the
// greatest clearance any sample saw, the start excepted, and starts at 0.
// The result is the start's clearance, floored at 0, plus the clearance of
// every sample before the ground, over the number of samples, less 1 --
// or the start's clearance alone when there were none. A sample that
// meets the ground is counted in the number but not in the sum.
//
// The first GetElevation passes no out-parameters; the samples' pass a
// normal nobody reads. *time is read again each sample, and after *height
// is zeroed, as the image does.
float car_average_air(Car *c, float *time, float *height)
{
    CarState *st = &c->State;
    TopologyCoordinate *tc = &c->TheTopologyCoordinate;
    const CarTypeInfo *cti;
    bMatrix4 body;
    bVector3 acc, p, vel, fall, q, normal;
    float speed, down, sum, d, t, samples;
    int32_t i, n;

    *height = 0.0f;
    cti = c->pCarTypeInfo;
    speed = st->VelocityMagnitude;
    down = -(speed * ((cti->Aero.FrontDownforce + cti->Aero.RearDownforce)
                      * CAR_AIR_DOWNFORCE_SHARE)
             / cti->Body.Mass + RIGIDBODY_GRAVITY);

    body.v0 = st->BodyMatrix.v0;
    body.v1 = st->BodyMatrix.v1;
    body.v2 = st->BodyMatrix.v2;
    body.v3.x = st->Position.x;
    body.v3.y = st->Position.y;
    body.v3.z = st->Position.z;
    body.v3.w = 1.0f;

    acc.x = 0.0f;
    acc.y = 0.0f;
    acc.z = 0.0f;
    acc.pad = 0.0f;
    for (i = 0; i < 4; i++) {
        p.x = 0.0f;
        p.y = 0.0f;
        p.z = -c->pCarTypeInfo->Wheels[i].Radius;
        p.pad = 0.0f;
        bMulMatrixVec3(&p, &st->WheelMatrix[0], &p);
        bMulMatrixVec3(&p, &body, &p);
        acc.x = p.x * 0.25f + acc.x;
        acc.y = p.y * 0.25f + acc.y;
        acc.z = p.z * 0.25f + acc.z;
    }

    vel = st->Velocity;
    fall.x = 0.0f;
    fall.y = 0.0f;
    fall.z = down;
    fall.pad = 0.0f;

    d = acc.z - topology_get_elevation(tc, &acc, NULL, NULL, NULL);
    n = ee_trunc_w(speed * *time * CAR_AIR_SAMPLE_RATE);
    sum = 0.0f < d ? d : 0.0f;              // max.s against a zero
    i = 1;
    if (i < n) {
        samples = (float)n;
        do {
            t = (*time * (float)i) / samples;
            q.x = (fall.x * t + vel.x) * t + acc.x;
            q.y = (fall.y * t + vel.y) * t + acc.y;
            q.z = (fall.z * t + vel.z) * t + acc.z;
            q.pad = 0.0f;
            d = q.z - topology_get_elevation(tc, &q, NULL, &normal, NULL);
            if (*height < d)
                *height = d;
            if (!(0.0f < d)) {
                *time = t;
                i++;
                break;
            }
            i++;
            sum += d;
        } while (i < n);
    }
    if (i == 1)
        return sum;
    return sum / (float)i - 1.0f;
}

// Retail's 0x00131cc8 (the demo's 0x001303a8). The start of a step. With
// time to move, the position and the velocities are kept as the old ones
// -- the demo's kept only the velocities. The interest box is put round
// Position, 3 plus a twentieth of the speed, and led by the velocity. A
// car over the topology with two wheels or more down keeps its x and y as
// the last place it was in the trough. Then the state's own BeginTimestep,
// a tail call.
//
// The speed is the velocity's length taken afresh, as VU0 does it:
// x x + y y, then + z z. `nWheelsTouchingGround` is compared signed.
void car_begin_movement(Car *c, float dt)
{
    CarState *st = &c->State;
    const bVector3 *v = &st->Velocity;
    float speed;

    if (0.0f < dt) {
        c->vOldPos = st->Position;
        c->vOldVel = st->Velocity;
        c->vOldAngVel = st->AngularVelocity;
    }
    speed = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);
    topology_set_interest_bbox3(&c->TheTopologyCoordinate, &st->Position,
                                speed * CAR_INTEREST_PER_SPEED
                                + CAR_INTEREST_BASE,
                                &st->Velocity);
    if (topology_has_topology(&c->TheTopologyCoordinate,
                              (const bVector2 *)&st->Position)
        && 2 <= st->nWheelsTouchingGround) {
        c->LastInTroughPosition.y = st->Position.y;
        c->LastInTroughPosition.x = st->Position.x;
    }
    carstate_begin_timestep(st);
}
