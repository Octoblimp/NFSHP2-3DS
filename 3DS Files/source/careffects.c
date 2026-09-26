// careffects -- Car.obj, slice ten: the smoke, spray and dust a car
// throws up from the ground under it.
//
//   Car::TriggerCarTerrainEffects   0x00131db8   1872 bytes
//
// One method, and a file of its own for carrace.c's reason: it reads the
// terrain table and the topology and asks the body damage, and car.c
// links into checkers that carry none of them. Its one caller is
// World::DoTimestep (0x0014b914), which is not ported. That passes the
// distance to the closest player, and calls only when the distance is
// under 150 and Car::ShouldVisualEffectsBeGenerated agrees -- so from
// there the skid smoke's own test against 150 always passes.
//
// Prototype and seam: car.h. Cross-check: tools/carmode_check.py.
// Write-up: docs/formats/car.md.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "car.h"
#include "cardamage.h"
#include "carstate.h"
#include "engine.h"
#include "physicscar.h"
#include "terraintype.h"
#include "topology.h"

// WorldTimeFrames, the frame clock TurnWipersOnForDuration counts in; car.c
// has the note.
#include "realtime.h"

CarBaseCarSoundSplashFn gBaseCarSoundTriggerSplashFn;

// m/s to mph. gp-32012 and gp-32004 are the same word twice, 0x400f2b02.
#define CAR_MPH_PER_MPS         2.237f
// A flat tire's effect grows from nothing at 4.470272541 mph (gp-32000,
// 0x408f0c79) by 0.04474 a mph (gp-31996, 0x3d37414a).
#define CAR_FLAT_TIRE_MIN_MPH   4.470272541f
#define CAR_FLAT_TIRE_PER_MPH   0.04474f
// The engine smokes above this much visible damage: gp-32008, 0x3f4ccccd.
#define CAR_ENGINE_SMOKE_DAMAGE 0.8f

// The rest are immediates, `lui`. How near the closest player the car must
// be for each effect, and how fast it must go to splash, in m/s:
#define CAR_SKID_SMOKE_RANGE    150.0f
#define CAR_TIRE_SPEW_RANGE      40.0f
#define CAR_SPLASH_RANGE         60.0f
#define CAR_SPLASH_MIN_SPEED     10.0f
// The splash's wipers come on in a second and go off in three, at sixty
// frames a second: `cvt.w.s` of 60.0 and 180.0, the 60.0 being the very
// register the range test compared against.
#define CAR_SPLASH_WIPERS_ON     60
#define CAR_SPLASH_WIPERS_OFF   180

// A wheel's effects name it in the effect's int as TriggerTireBlowOut
// does: 0x50000 for wheel 0, and 0x10000 more for each wheel after.
#define CAR_WHEEL_WHERE0        0x50000
#define CAR_WHEEL_WHERE_STEP    0x10000

// `max.s` against 0, and then `min.s` against 1. Written as compares they
// agree with the R5900 on every value that reaches them: no terrain's
// minimum equals its maximum, so no divide below is by zero and there is
// no NaN. A -0 is not in play either, since only a scale above 0 is
// passed on.
static float max0(float x)
{
    return (x < 0.0f) ? 0.0f : x;
}

static float clamp01(float x)
{
    x = max0(x);
    return (x < 1.0f) ? x : 1.0f;
}

// The emitter group's name: an empty one means the terrain has no such
// effect. The drive-over pair test only the first byte, with no NULL test,
// as the listing does; every name in the table is a string, if an empty
// one.
static int has_group(const char *name)
{
    return name != NULL && name[0] != '\0';
}

static void effect(Car *c, CarEffect fx, float scale, int32_t where,
                   bVector3 *pos)
{
    if (gCarTriggerEffectFn != NULL)
        gCarTriggerEffectFn(c, fx, scale, where, pos);
}

// 0x00131db8. `distance` is from the car to the closest player.
//
// For each wheel on the ground, in wheel order:
//   * skid smoke, from the length of the wheel's slip. The wheel's
//     NumTimesSkidding counts the frames it has skidded, to 255, and is
//     cleared by a frame it does not; the smoke is nothing on the first
//     frame and a quarter, a half and three quarters of itself until the
//     20th, 60th and 120th.
//   * tire spew, rear wheels (2 and 3) only, from the slip's x. It goes
//     off at the slip turned by the wheel's matrix, translation and all,
//     plus the car's velocity -- all four lanes, as `vadd.xyzw` adds them.
//   * a puddle, deep water or mud puddle (4, 5, 20) sets the wheel's bit
//     in `wet`.
//
// With three wheels or four down, the ground under the car: the drive-over
// effect and the second one, each from the speed in mph between its
// terrain's two thresholds. If the two come to more than 1, the one that
// starts at the lower speed gives up twice the excess. Then bottom-out,
// from the four wheels' bottom-out magnitudes summed -- whether or not
// the terrain has a group for it.
//
// Then the splash, the damage, the nitro and the flat tires, which read
// the car and not the terrain.
void car_trigger_car_terrain_effects(Car *c, float distance)
{
    CarState *st = &c->State;
    float mph = st->VelocityMagnitude * CAR_MPH_PER_MPS;
    int32_t down = 0;
    int32_t wet = 0;
    int32_t deep = 0;
    int32_t where = CAR_WHEEL_WHERE0;
    int32_t terrain;
    const TerrainTypeInfo *ti;
    float s;
    int32_t i;

    for (i = 0; i < 4; i++, where += CAR_WHEEL_WHERE_STEP) {
        const bVector2 *slip = &st->WheelSlip[i];
        float mag;

        if (st->WheelTouchingGround[i] == 0)
            continue;
        down++;
        terrain = st->WheelTerrain[i];
        ti = &TerrainTypeInfoTable[terrain];
        if (terrain == TERRAIN_TYPE_PUDDLE || terrain == TERRAIN_TYPE_DEEP_WATER
            || terrain == TERRAIN_TYPE_MUD_PUDDLE) {
            wet |= 1 << i;
            deep |= terrain == TERRAIN_TYPE_DEEP_WATER;
        }
        mag = sqrtf(slip->x * slip->x + slip->y * slip->y);

        if (distance < CAR_SKID_SMOKE_RANGE && ti->SkidSmokeMinSpeed < mag) {
            int32_t n = c->NumTimesSkidding[i] + 1;

            if (n > 255)                    // pminw
                n = 255;
            c->NumTimesSkidding[i] = (uint8_t)n;
            if (has_group(ti->SkidSmokeEmitterGroup)) {
                s = (mag - ti->SkidSmokeMinSpeed)
                    / (ti->SkidSmokeMaxSpeed - ti->SkidSmokeMinSpeed);
                if (n < 2)
                    s = 0.0f;
                else if (n < 20)
                    s = s * 0.25f;
                else if (n < 60)
                    s = s * 0.5f;
                else if (n < 120)
                    s = s * 0.75f;
                s = clamp01(s);
                if (0.0f < s)
                    effect(c, CARFX_SKID_SMOKE, s, where + terrain, NULL);
            }
        } else {
            c->NumTimesSkidding[i] = 0;
        }

        if (!(distance < CAR_TIRE_SPEW_RANGE) || i < 2
            || !(ti->TireSpewMinSpeed < slip->x)
            || !has_group(ti->TireSpewEmitterGroup))
            continue;
        s = clamp01((slip->x - ti->TireSpewMinSpeed)
                    / (ti->TireSpewMaxSpeed - ti->TireSpewMinSpeed));
        if (0.0f < s) {
            bVector3 v, p;

            v.x = slip->x;
            v.y = slip->y;
            v.z = 0.0f;
            v.pad = 0.0f;                   // not read: w is forced to 1
            bMulMatrixVec3(&p, &st->WheelMatrix[i], &v);
            p.x = p.x + st->Velocity.x;
            p.y = p.y + st->Velocity.y;
            p.z = p.z + st->Velocity.z;
            p.pad = p.pad + st->Velocity.pad;
            effect(c, CARFX_TIRE_SPEW, s, where + terrain, &p);
        }
    }

    if (down >= 3) {
        float drive = 0.0f, drive2 = 0.0f, sum = 0.0f;

        topology_get_elevation(&c->TheTopologyCoordinate, &st->Position,
                               &terrain, NULL, NULL);
        ti = &TerrainTypeInfoTable[terrain];
        if (ti->DriveOverEmitterGroup[0] != '\0')
            drive = clamp01((mph - ti->DriveOverMinSpeed)
                            / (ti->DriveOverMaxSpeed - ti->DriveOverMinSpeed));
        if (ti->DriveOver2EmitterGroup[0] != '\0')
            drive2 = clamp01((mph - ti->DriveOver2MinSpeed)
                             / (ti->DriveOver2MaxSpeed
                                - ti->DriveOver2MinSpeed));
        if (0.0f < drive + drive2) {
            float over = (drive + drive2) - 1.0f;

            if (0.0f < over) {
                if (ti->DriveOverMinSpeed < ti->DriveOver2MinSpeed)
                    drive = max0(drive - (over + over));
                else
                    drive2 = max0(drive2 - (over + over));
            }
            if (0.0f < drive)
                effect(c, CARFX_DRIVE_OVER, drive, terrain, NULL);
            if (0.0f < drive2)
                effect(c, CARFX_DRIVE_OVER2, drive2, terrain, NULL);
        }
        for (i = 0; i < 4; i++)
            sum = sum + st->WheelBottomOutMagnitude[i];
        s = clamp01((sum - ti->BottomOutMinImpact)
                    / (ti->BottomOutMaxImpact - ti->BottomOutMinImpact));
        if (0.0f < s)
            effect(c, CARFX_BOTTOM_OUT, s, terrain, NULL);
    }

    // A wet wheel near a player at speed: the wipers, and the sound's
    // splash -- on the right if wheel 1 or 2 is wet, and 3 rather than 1
    // if any wheel is in deep water. `wet` is tested signed, `blez`.
    if (distance < CAR_SPLASH_RANGE && wet > 0
        && CAR_SPLASH_MIN_SPEED < st->VelocityMagnitude) {
        car_turn_wipers_on_for_duration(c,
                                        WorldTimeFrames + CAR_SPLASH_WIPERS_ON,
                                        WorldTimeFrames + CAR_SPLASH_WIPERS_OFF);
        if (c->pBaseCarSound != NULL && gBaseCarSoundTriggerSplashFn != NULL)
            gBaseCarSoundTriggerSplashFn(c->pBaseCarSound, (wet & 6) != 0,
                                         deep ? 3 : 1);
    }

    // The radiator is breakable item 14, and its two bits of damage are
    // the top but two of the word. Any at all and it steams.
    if (c->pCarDamage != NULL) {
        CarDamage *d = c->pCarDamage;

        if (((d->BreakableCarItemDamageAmounts
              >> (2 * BREAKABLE_CAR_ITEM_RADIATOR)) & 3) > 0)
            effect(c, CARFX_DAM_RADIATOR, 1.0f, 0, NULL);
        if (CAR_ENGINE_SMOKE_DAMAGE
            < bodydamage_get_visible_total_damage(&d->TheBodyDamage))
            effect(c, CARFX_DAM_ENGINE, 1.0f, 0, NULL);
    }

    // The nitro flag, or a player's physics car whose engine is on nitro.
    // Under PHYSICS_MOVEMENT the mover is the PhysicsCar itself.
    {
        int32_t engine = 0;

        if (c->pPlayer != NULL && c->TheMovementMode == PHYSICS_MOVEMENT)
            engine = ((PhysicsCar *)(void *)c->pCarMover)->pEngine->NitroFlag
                     != 0;
        if (c->NitroEffectFlag != 0 || engine != 0)
            effect(c, CARFX_NITRO, 1.0f, 0, NULL);
    }

    // Each blown tire on the ground, from its speed in mph. Both bytes are
    // read signed, `lb`.
    if ((int8_t)c->NumBlownTires != 0) {
        for (i = 0; i < 4; i++) {
            if (st->WheelTouchingGround[i] == 0)
                continue;
            if ((((int8_t)c->BlownTireBits >> i) & 1) == 0)
                continue;
            effect(c, CARFX_DRIVE_ON_FLAT_TIRE,
                   clamp01((st->VelocityMagnitude * CAR_MPH_PER_MPS
                            - CAR_FLAT_TIRE_MIN_MPH) * CAR_FLAT_TIRE_PER_MPH),
                   CAR_WHEEL_WHERE0 + i * CAR_WHEEL_WHERE_STEP, NULL);
        }
    }
}
