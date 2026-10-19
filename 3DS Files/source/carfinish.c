// carfinish -- Car.obj, slice eleven: Car::FinishMovement, the end of a
// car's step.
//
// World::DoTimestep calls it for every car once every car has moved and
// the collisions are done (worldstep.c, through gCarFinishMovementFn). It
// takes the accelerations from the step's change in velocity, runs the
// odometer, measures the car along the track, decides whether the car is
// lost enough to be put back, and turns the lights on or off. Then, for a
// player's car, it runs the jump cam and tells the replay what was worth
// watching.
//
// A file of its own because it reaches Collision, the world's car table
// and the Player, none of which car.c's checkers link.
//
// Prototypes: car.h. Cross-check: tools/carmode_check.py's finish
// scenario. Write-up: docs/formats/car.md.

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "car.h"
#include "carstate.h"
#include "collision.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "player.h"
#include "realtime.h"
#include "replay.h"
#include "topology.h"
#include "trackpath.h"
#include "world.h"

// Retail's gp offsets; the demo's are 80 lower (gp-32068 for the first).

// gp-31988. Further than this from the track path's nearest point and the
// car is lost: it is put back, unless the camera tuner has the AI boring.
#define CAR_LOST_DISTANCE 5000.0f

// 300.0 (0x43960000). Further than this and, every sixtieth step, the
// track path coordinate forgets its point and searches the whole table.
#define CAR_RESEARCH_DISTANCE 300.0f

// The tick, 1/4000 s, as gp-31976, -31972, -31968 and -31952 each hold it.
#define CAR_FINISH_TICK 0.00025f

// gp-31984 and gp-31956: 3.14/32 and 3.14/8. A car in the air counts as
// flying straight under the first; a car on the ground counts as sliding
// over the second.
#define CAR_AIR_STRAIGHT_YAW 0.098125f
#define CAR_SLIDING_YAW      0.3925f

// gp-31980. A jump shorter than this, in seconds, keeps the jump cam up
// for five seconds; a longer one for half of it.
#define CAR_SHORT_JUMP 0.9f

// Retail's. Under 5.0 (0x40a00000) a player still racing is "GoingSlow".
// Each cop within 40 is worth gp-31964, 0.05; the speed times gp-31960,
// 1/150 (0x3bda740e), is "Speed".
#define CAR_GOING_SLOW      5.0f
#define CAR_CLOSE_COP_VALUE 0.05f
#define CAR_SPEED_VALUE     (1.0f / 150.0f)

// ------------------------------------------------------------- the seams

PlayerClearZoneFn          gPlayerClearZoneFn;
PlayerRequestZoneFn        gPlayerRequestZoneFn;
PlayerIsJumpCamAvailableFn gPlayerIsJumpCamAvailableFn;
PlayerCleanUpJumpCamFn     gPlayerCleanUpJumpCamFn;

static void no_player(const char *name)
{
    fprintf(stderr, "carfinish: Player::%s is not ported\n", name);
    abort();
}

static void clear_zone(Player *p, int32_t sound)
{
    if (gPlayerClearZoneFn == NULL)
        no_player("ClearZone");
    gPlayerClearZoneFn(p, sound);
}

static int32_t request_zone(Player *p, int32_t zone, int32_t force,
                            int32_t b2, int32_t b3)
{
    if (gPlayerRequestZoneFn == NULL)
        no_player("RequestZone");
    return gPlayerRequestZoneFn(p, zone, force, b2, b3);
}

static int32_t is_jump_cam_available(Player *p)
{
    if (gPlayerIsJumpCamAvailableFn == NULL)
        no_player("IsJumpCamAvailable");
    return gPlayerIsJumpCamAvailableFn(p);
}

static void clean_up_jump_cam(Player *p)
{
    if (gPlayerCleanUpJumpCamFn == NULL)
        no_player("CleanUpJumpCam");
    gPlayerCleanUpJumpCamFn(p);
}

// The image calls RegisterInterestingEvent on pReplayManager without a
// test, as carreset.c's reset does. The port tests it for the reason
// carreset.c gives: there is no ReplayManager yet.
static void interesting(float value, const char *what)
{
    if (pReplayManager != NULL)
        ReplayManager_RegisterInterestingEvent(pReplayManager, value, what);
}

// How far the coordinate's position is from its nearest point, in the
// plane; 0 with no point. FinishMovement works it out twice, the same way
// each time.
static float track_offset(const TrackPathCoordinate *t)
{
    float dx, dy;

    if (t->pTrackPoint == NULL)
        return 0.0f;
    dx = t->Position.x - t->pTrackPoint->Position.x;
    dy = t->Position.y - t->pTrackPoint->Position.y;
    return sqrtf(dx * dx + dy * dy);
}

// ---------------------------------------------------------------- the step

// Retail's 0x00131da8; the demo's is 0x00130480. Retail's is the demo's
// with four things added, marked "Retail" below, and the debug tail gone.
// In order:
//
//   * For a positive dt, Acceleration and AngularAcceleration are the
//     change from vOldVel and vOldAngVel times 1/dt, all four lanes (VU0's
//     vsub and vmulx). A denormal dt is positive, and the EE's div.s reads
//     it as zero, so 1/dt is ee_div's FLT_MAX.
//   * The odometer adds speed * dt, unless the speed is below zero or
//     above 1000. The tests are `<`, so a NaN speed is added.
//   * Retail: DistanceMoved adds how far Position is from vOldPos (x x +
//     y y, then + z z, as VU0 sums them), whatever dt is, and vOldPos
//     becomes Position, all four lanes. BeginMovement saved it; the race
//     results' average speed is DistanceMoved over the race time.
//   * The track path coordinate is moved to the car. Every thirty-second
//     step, a car that is moving and has no topology under it, nor a metre
//     to its +x, is marked ResetMe.
//   * A car more than 5000 from the track path's point is marked ResetMe,
//     unless BoringAIForCameraTuningOn. One more than 300 away and moving
//     has its coordinate searched afresh every sixtieth step (a signed
//     remainder, so a negative counter counts too).
//   * The headlights and horn.
//
// Then only for a car with a Player. A player in the jump cam's zone or
// the one after it, with a wheel down, is taken out of it with a sound.
// Everything after that runs every eighth step, on the speed as it stood
// on entry to it:
//
//   * CarInAir, 2: above 40, fewer than four wheels down, and flying
//     straight.
//   * The jump cam, unless g_DisableAutoReplay: a player in neither zone,
//     no wheel down, not going the wrong way and above 30 asks AverageAir
//     how long (from 3 seconds) and how high the jump will be. AirTimeSwitch
//     becomes when the jump cam should give way. A jump higher than 1.5
//     and longer than half a second asks for the jump cam, if the player
//     can have one, and gives up the preview route if the request fails.
//   * In the jump cam's zone: the highest point the car reaches while
//     falling is kept in EyeVerts[2].z, and past AirTimeSwitch the player
//     is moved to the zone after, without a sound.
//   * Retail: GoingSlow, -10, under 5 while the player's
//     TimeFinishedRacing is 0. A NaN speed is not under 5.
//   * CloseCars, half a point each: above 40, every AI car within 40 of
//     this one. The world is not tested for NULL, nor is the car itself
//     skipped; the loop runs AICarPos up to CopCarPos.
//   * Retail: CloseCops, 0.05 each, the same way over CopCarPos up to
//     TrafficCarPos, still above 40.
//   * Retail: Speed, the speed / 150, at any speed.
//   * Above 30: CarSlidingSideways, 1, for a yaw past 3.14/8. Then the
//     car's first collision, if a player is in it and it touched in the
//     last half second: CarCollision, 3, for two cars above 40, and
//     otherwise SmokeableCollision for a smokeable body: 2.5 in retail,
//     where the demo had 5 and tested `30 < speed` again.
//
// One thing in the listing is left out, because it has no effect: after
// CarCollision it asks for the colliding cars and swaps the two when the
// second is the player's own. Nothing reads either local afterwards. The
// call is kept; it only reads. The demo's tail, a debug print's reads
// when DoScreenPrintf or TerminalPrintPosition was set, is gone in retail.
void car_finish_movement(Car *c, float dt)
{
    CarState *st = &c->State;
    TrackPathCoordinate *tpc = &c->TheTrackPathCoordinate;
    Player *p;
    int32_t wheels, zone;
    float speed;

    if (0.0f < dt) {
        float inv = ee_div(1.0f, dt);

        st->Acceleration.x = (st->Velocity.x - c->vOldVel.x) * inv;
        st->Acceleration.y = (st->Velocity.y - c->vOldVel.y) * inv;
        st->Acceleration.z = (st->Velocity.z - c->vOldVel.z) * inv;
        st->Acceleration.pad = (st->Velocity.pad - c->vOldVel.pad) * inv;
        st->AngularAcceleration.x =
            (st->AngularVelocity.x - c->vOldAngVel.x) * inv;
        st->AngularAcceleration.y =
            (st->AngularVelocity.y - c->vOldAngVel.y) * inv;
        st->AngularAcceleration.z =
            (st->AngularVelocity.z - c->vOldAngVel.z) * inv;
        st->AngularAcceleration.pad =
            (st->AngularVelocity.pad - c->vOldAngVel.pad) * inv;
    }

    speed = st->VelocityMagnitude;
    if (!(speed < 0.0f) && !(1000.0f < speed))
        st->Odometer = st->Odometer + speed * dt;

    {
        float dx = c->vOldPos.x - st->Position.x;
        float dy = c->vOldPos.y - st->Position.y;
        float dz = c->vOldPos.z - st->Position.z;

        st->DistanceMoved = st->DistanceMoved
                          + sqrtf((dx * dx + dy * dy) + dz * dz);
        c->vOldPos = st->Position;
    }

    trackpath_coord_update_position(tpc, (const bVector2 *)&st->Position);

    if (((WorldLoopCounter + 7) & 31) == 0 && c->TheMovementMode != 0
        && !topology_has_topology(&c->TheTopologyCoordinate,
                                  (const bVector2 *)&st->Position)) {
        bVector2 q;

        q.x = st->Position.x + 1.0f;
        q.y = st->Position.y;
        if (!topology_has_topology(&c->TheTopologyCoordinate, &q))
            c->ResetMe = 1;
    }

    if (CAR_LOST_DISTANCE < track_offset(tpc)) {
        if (!BoringAIForCameraTuningOn)
            c->ResetMe = 1;
    } else if (CAR_RESEARCH_DISTANCE < track_offset(tpc)
               && WorldLoopCounter % 60 == 0 && c->TheMovementMode != 0) {
        trackpath_coord_reset_position(tpc, (const bVector2 *)&st->Position);
    }

    car_update_headlights_and_horn(c);

    p = c->pPlayer;
    if (p == NULL)
        return;
    wheels = st->nWheelsTouchingGround;
    if (p->nZoneCurrent == PLAYER_ZONE_JUMP_CAM
        || p->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP) {
        if (wheels > 0)
            clear_zone(p, 1);
    }
    if (((WorldLoopCounter + 3) & 7) != 0)
        return;

    speed = st->VelocityMagnitude;
    if (40.0f < speed && wheels < 4
        && fabsf(carstate_get_yaw(st)) < CAR_AIR_STRAIGHT_YAW)
        interesting(2.0f, "CarInAir");

    zone = p->nZoneCurrent;
    if (!g_DisableAutoReplay && zone != PLAYER_ZONE_JUMP_CAM
        && zone != PLAYER_ZONE_AFTER_JUMP && wheels == 0
        && c->pPlayer->bWrongWay == 0 && 30.0f < speed) {
        float t = 3.0f, h;
        float now;

        car_average_air(c, &t, &h);
        now = (float)WorldTimer * CAR_FINISH_TICK;
        if (t < CAR_SHORT_JUMP)
            c->AirTimeSwitch = now + 5.0f;
        else
            c->AirTimeSwitch = t * 0.5f + now;
        if (1.5f < h && 0.5f < t && is_jump_cam_available(p)
            && !request_zone(p, PLAYER_ZONE_JUMP_CAM, 0, 1, 1))
            clean_up_jump_cam(p);
        zone = p->nZoneCurrent;
    }

    if (zone == PLAYER_ZONE_JUMP_CAM) {
        if (st->Velocity.z < 0.0f && p->EyeVerts[2].z < st->Position.z)
            p->EyeVerts[2].z = st->Position.z;
        if (c->AirTimeSwitch < (float)WorldTimer * CAR_FINISH_TICK) {
            clear_zone(p, 0);
            request_zone(p, PLAYER_ZONE_AFTER_JUMP, 0, 0, 1);
        }
    }

    if (speed < CAR_GOING_SLOW && p->TimeFinishedRacing == 0)
        interesting(-10.0f, "GoingSlow");

    if (40.0f < speed) {
        World *w = pCurrentWorld;
        bVector3 pos = st->Position;
        int32_t i, n = 0;

        for (i = 0; i < w->CopCarPos - w->AICarPos; i++) {
            const Car *o = w->CarTable[w->AICarPos + i];
            float dx = o->State.Position.x - pos.x;
            float dy = o->State.Position.y - pos.y;
            float dz = o->State.Position.z - pos.z;

            if (sqrtf((dx * dx + dy * dy) + dz * dz) < 40.0f)
                n++;
        }
        if (n > 0)
            interesting((float)n * 0.5f, "CloseCars");
        n = 0;
        for (i = 0; i < w->TrafficCarPos - w->CopCarPos; i++) {
            const Car *o = w->CarTable[w->CopCarPos + i];
            float dx = o->State.Position.x - pos.x;
            float dy = o->State.Position.y - pos.y;
            float dz = o->State.Position.z - pos.z;

            if (sqrtf((dx * dx + dy * dy) + dz * dz) < 40.0f)
                n++;
        }
        if (n > 0)
            interesting((float)n * CAR_CLOSE_COP_VALUE, "CloseCops");
    }
    interesting(speed * CAR_SPEED_VALUE, "Speed");

    if (30.0f < speed) {
        Collision *col;

        if (CAR_SLIDING_YAW < fabsf(carstate_get_yaw(st)))
            interesting(1.0f, "CarSlidingSideways");
        col = collisionbody_get_collision(
            &c->pDynamicCollisionBody->Dynamic.Body, 0);
        if (col != NULL && collision_is_player_involved(col)
            && (float)(int32_t)((uint32_t)WorldTimer
                                - col->LastContactTime.PackedTime)
                   * CAR_FINISH_TICK < 0.5f) {
            if (collision_is_two_car_collision(col) && 40.0f < speed) {
                Car *a, *b;

                interesting(3.0f, "CarCollision");
                collision_get_colliding_cars(col, &a, &b);
            } else if (collision_is_smokeable_involved(col)) {
                interesting(2.5f, "SmokeableCollision");
            }
        }
    }
}
