// carmove -- Car.obj, slice eight: one step of a car.
//
//   Car::Move                            0x00130200
//   Car::ChangeGear                      0x00130ff8
//   Car::CalculateNewCatchupMultipliers  0x001334f0
//   Car::UpdatePosition                  0x00130388
//
// Move is what the world calls for each car on each step. It sets the
// catchup, hands the step to the mover, tells the editor link and the
// animated driver what came of it, puts back a car that asked to be reset,
// and keeps a car blinking while it is still inside something. It is a
// file of its own for carreset.c's reason: it reaches the resets, and
// car.c links into checkers that carry neither.
//
// Prototypes and seams: car.h. Cross-check: tools/carmode_check.py, which
// has the stand-in movers and controllers. Write-up: docs/formats/car.md.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "car.h"
#include "carstate.h"
#include "difficultyinfo.h"
#include "graph.h"
#include "physicscar.h"
#include "player.h"
#include "race.h"
#include "timer.h"
#include "trackpath.h"
#include "vtable.h"

// WorldTimer.
#include "realtime.h"

// gp-23488, 0x00323030: the speed a car asked to be reset is put back at.
#define CAR_RESET_ME_SPEED 15.0f

// gp-23484, 0x00323034: the last half second of a blink, and how recent a
// penetration has to be to stretch it by as much again.
#define CAR_BLINK_OVERLAP_TIME 0.5f

// gp-32076, 0x00320ea4: seconds per WorldTimer tick. car.c's
// CAR_TICK_SECONDS, which is file-local there.
#define CAR_MOVE_TICK_SECONDS 0.000250000012f

CarAnimatedDriverFn gAnimatedDriverBeginGearChangeFn;
CarAnimatedDriverFn gAnimatedDriverBeginDrivingBackwardsFn;
CarAnimatedDriverFn gAnimatedDriverEndDrivingBackwardsFn;

// A seam nobody set is an AnimatedDriver the port cannot build yet, and
// nothing sets pAnimatedDriver until one can; reaching it is a bug.
static void animated_driver_call(CarAnimatedDriverFn fn, AnimatedDriver *d,
                                 const char *what)
{
    if (fn == NULL) {
        fprintf(stderr, "car: AnimatedDriver::%s is not ported\n", what);
        abort();
    }
    fn(d);
}

// 0x00130388. The Espresso editor's live link: with an editor object, the
// car's position goes to it. The one store into pCaffeineObj in the image
// is the constructor's zero (0x0012f514, `sw zero,1992(s2)`), so the arm is
// dead on the disc, and the seam aborts if the port ever reaches it
// unset.
void car_update_position(Car *c, bVector3 *pos)
{
    void *obj = c->pCaffeineObj;

    if (obj == NULL)
        return;
    if (gEspSetObjectPositionFn == NULL) {
        fprintf(stderr, "car: espSetObjectPosition is not ported\n");
        abort();
    }
    gEspSetObjectPositionFn(obj, pos);
}

// 0x00130ff8. DispGear is the gear the animated driver has been told about.
// A change out of neutral (1), or on a car with no driver model, is only
// stored. Otherwise leaving reverse ends the backwards pose, every change
// queues the gear-change animation, and going into reverse starts the pose.
//
// pAnimatedDriver is read once for the test and the first call, then again
// for each of the other two, as the listing does; nothing between them can
// change it.
void car_change_gear(Car *c, Gear gear)
{
    Gear old = c->DispGear;
    AnimatedDriver *d;

    if (gear == old)
        return;
    if (old == 1) {
        c->DispGear = gear;
        return;
    }
    d = c->pAnimatedDriver;
    if (d == NULL) {
        c->DispGear = gear;
        return;
    }
    if (old == 0)
        animated_driver_call(gAnimatedDriverEndDrivingBackwardsFn, d,
                             "EndDrivingBackwards");
    animated_driver_call(gAnimatedDriverBeginGearChangeFn, c->pAnimatedDriver,
                         "BeginGearChange");
    if (gear == 0)
        animated_driver_call(gAnimatedDriverBeginDrivingBackwardsFn,
                             c->pAnimatedDriver, "BeginDrivingBackwards");
    c->DispGear = gear;
}

// 0x001334f0. Two players racing with Boost on: the car's BoostFactor is
// the catchup graph at how far it leads the other player, in metres --
// laps times the track's length, each car's own product, then the
// difference. A car behind gets more than 1.
//
// The other player is pPlayersByNumber[PlayerNumber == 0 ? 1 : 0], so a
// PlayerNumber of 1 or anything else reads player 0. Neither the entry
// nor either RacingCar is tested for NULL. The Graph is built on the
// stack over TheDifficultyInfo's four knees for each call.
void car_calculate_new_catchup_multipliers(Car *c)
{
    struct RacingCar *me, *other;
    struct Player *op;
    float lead, len;
    Graph g;

    if (c->pPlayer == NULL || RaceParametersBoost == 0
        || PlayerNumPlayers != 2)
        return;
    me = race_get_racing_car(pCurrentRace, c);
    op = PlayerPlayersByNumber[c->pPlayer->PlayerNumber == 0 ? 1 : 0];
    other = race_get_racing_car(pCurrentRace, op->MyCar);
    len = TheTrackPathManager.TrackLength;
    lead = me->CurrentLapNumberExact * len
           - other->CurrentLapNumberExact * len;
    graph_init(&g, TheDifficultyInfo.TwoPlayerCatchup, 4);
    c->State.BoostFactor = graph_get_value(&g, lead);
}

// 0x00130200. The step, and what the mover's answer is carried past: the
// mover's float is Move's return on every path.
//
// The blink tail keeps a car blinking -- and so uncollideable -- while it
// is still inside something. If the blink is in its last half second and
// the body last penetrated less than half a second ago, the stamp moves
// on by Timer::SetTime(0.5), 2000 ticks. Both tests are strict and the
// second is two: `s < 0.5`, then `0 <= s`, so a penetration stamped after
// WorldTimer is not one. A last penetration of 0 or 0x7fffffff is none.
// The two elapsed times are each a 32-bit wrapping subtract read as
// signed, like IsBlinking's.
float car_move(Car *c, float dt)
{
    CarMover *m;
    const VtEntry *e;
    TrackRoute *route;
    TrackRoutePoint *point;
    uint32_t pen, now;
    float r, s;
    Timer t;

    car_calculate_new_catchup_multipliers(c);
    m = c->pCarMover;
    e = vt_slot(m->_vtable, CARMOVER_VT_MOVE);
    r = ((CarMoverMoveFn)e->fn)(vt_this(m, e), dt);
    car_update_position(c, &c->State.Position);
    car_change_gear(c, c->State.CurrentGear);

    // GetRoute before GetRoutePoint, as the listing calls them. Written as
    // two statements: C leaves the order of a call's arguments open, and
    // gcc on the host evaluates these two right to left.
    if (c->ResetMe) {
        route = car_get_route(c);
        point = car_get_route_point(c);
        car_reset_to_route_point(c, route, point, CAR_RESET_ME_SPEED, 1,
                                 1.0f);
        c->ResetMe = 0;
        return r;
    }

    pen = car_get_last_penetration_time(c).PackedTime;
    if (!car_is_blinking(c) || pen == 0 || pen == 0x7fffffffu)
        return r;
    now = (uint32_t)WorldTimer;
    if (!(c->BlinkDuration - CAR_BLINK_OVERLAP_TIME
          < (float)(int32_t)(now - (uint32_t)c->BlinkTimer)
                * CAR_MOVE_TICK_SECONDS))
        return r;
    s = (float)(int32_t)(now - pen) * CAR_MOVE_TICK_SECONDS;
    if (!(s < CAR_BLINK_OVERLAP_TIME) || !(0.0f <= s))
        return r;
    timer_set_time(&t, CAR_BLINK_OVERLAP_TIME);
    c->BlinkTimer = (int32_t)((uint32_t)c->BlinkTimer + t.PackedTime);
    return r;
}
