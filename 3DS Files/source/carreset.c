// carreset -- Car.obj, slice six: putting a car back on the road.
//
// ResetCore and the three that wrap it. Each takes the car out of its
// movement mode, sets it down with PutFlatOnTrack, and puts the mode back,
// so the mover is torn down and built again. That is why this is a file of
// its own: it reaches carmodes.c and cartrack.c both, and car.c links into
// checkers that carry neither.
//
// Prototypes: car.h. Cross-check: tools/carmode_check.py, which has the
// modes, the stand-in controllers and drivers, and the heap. Write-up:
// docs/formats/car.md.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "bmath.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carstate.h"
#include "replay.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"

typedef void (*CarResetVoidFn)(void *self);
typedef void (*CarResetSetRouteFn)(void *self, TrackRoute *route,
                                   TrackRoutePoint *point);

// gp-32024, 0x3dcccccd. Added to the speed to make the length that the
// body's forward axis is normalised to, so a car reset at rest still has a
// velocity of a tenth.
#define CAR_RESET_SPEED_BIAS 0.1f

static void controller_call(Car *c, int slot)
{
    CarController *ctrl = c->pCarController;
    const VtEntry *e = vt_slot(ctrl->_vtable, slot);

    ((CarResetVoidFn)e->fn)(vt_this(ctrl, e));
}

// 0x001312c0. The car is put at `pos` facing `angle`, stood on the ground,
// and given `speed` along its body's forward axis, with its wheels turning
// to match. `pos` is copied whole, all four lanes; its z is replaced by
// PutFlatOnTrack.
//
// The velocity is the body's row 0 normalised to speed + 0.1, and
// VelocityMagnitude is that vector's length -- VU0's (x*x + y*y) + z*z --
// not the speed. bNormalize3To writes three lanes and the copy into
// Velocity is four, so the fourth is what the stack held; it is 0 here.
//
// The wheel speeds read ForwardSpeed back from the state on each of the
// four, and divide by each wheel's own radius.
//
// The pPlayer arm tells the replay that what it holds is no longer worth
// replaying. The image does not test pReplayManager. The port does: it has
// no ReplayManager yet, and without the test a player's car would crash on
// its first reset. In mipsemu, where address 4 reads as 0, the image does
// nothing in that case either.
void car_reset_core(Car *c, const bVector3 *pos, float speed, uint16_t angle)
{
    CarState *st = &c->State;
    MovementMode mode = c->TheMovementMode;
    const CarTypeInfo *cti;
    CarDriver *drv;
    const VtEntry *e;
    bVector3 dir;
    int32_t i;

    car_set_movement_mode(c, eNO_MOVEMENT);
    carstate_reset_car(st);
    trackpath_coord_update_position(&c->TheTrackPathCoordinate,
                                    (const bVector2 *)pos);
    st->Angle = angle;
    st->SteeringAngle = 0;
    st->Position = *pos;
    topology_clear_interest_bbox(&c->TheTopologyCoordinate);
    st->ForwardSpeed = speed;
    car_put_flat_on_track(c);

    dir.pad = 0.0f;
    bNormalize3To(&dir, (const bVector3 *)&st->BodyMatrix.v0,
                  speed + CAR_RESET_SPEED_BIAS);
    st->Velocity = dir;
    st->VelocityMagnitude = sqrtf((dir.x * dir.x + dir.y * dir.y)
                                  + dir.z * dir.z);
    st->MatrixValid = 0;

    cti = c->pCarTypeInfo;
    for (i = 0; i < 4; i++)
        st->WheelAngularVelocity[i] = st->ForwardSpeed / cti->Wheels[i].Radius;
    carstate_calculate_wheel_matrices(st);

    drv = c->pCarDriver;
    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_LOW_GEAR);
    ((CarResetVoidFn)e->fn)(vt_this(drv, e));

    car_set_movement_mode(c, mode);
    if (c->pPlayer != NULL && pReplayManager != NULL)
        ReplayManager_InvalidateInterestingEvents(pReplayManager);
}

// 0x00131418. ResetCore, then the track path from where the car ended up
// -- ResetCore measured from `pos`, and PutFlatOnTrack moved only z, so the
// second update is from the same x and y -- then the controller is told to
// find itself and that it was reset, and the blinking stops. The
// controller is read from the car again for each call.
void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    car_reset_core(c, pos, speed, angle);
    trackpath_coord_update_position(&c->TheTrackPathCoordinate,
                                    (const bVector2 *)&c->State.Position);
    controller_call(c, CARCONTROLLER_VT_FIND_WHERE_I_AM);
    controller_call(c, CARCONTROLLER_VT_JUST_RESET);
    car_stop_blinking(c);
}

// 0x00131480. At `point`, heading along its direction times `direction`
// (so -1 faces back down the route), with the controller put on `route` at
// `point`. Nothing happens without a route or without a point. `blink`
// starts two seconds of blinking.
//
// The position is the point's x, y and elevation. Its fourth lane is a
// stack word nothing wrote, and ResetCore copies it into Position; it is 0
// here. The heading is bATan's, cut to sixteen bits by ResetCore's `andi`.
// Unlike ResetToPosition this one does not call FindWhereIAm.
void car_reset_to_route_point(Car *c, TrackRoute *route,
                              TrackRoutePoint *point, float speed,
                              int32_t blink, float direction)
{
    CarController *ctrl;
    const VtEntry *e;
    bVector3 pos;
    int32_t angle;

    if (route == NULL || point == NULL)
        return;
    pos.x = point->Position.x;
    pos.y = point->Position.y;
    pos.z = point->Elevation;
    pos.pad = 0.0f;
    angle = bATan(point->Direction.x * direction,
                  point->Direction.y * direction);
    car_reset_core(c, &pos, speed, (uint16_t)angle);
    trackpath_coord_update_position(&c->TheTrackPathCoordinate,
                                    (const bVector2 *)&c->State.Position);

    ctrl = c->pCarController;
    e = vt_slot(ctrl->_vtable, CARCONTROLLER_VT_SET_CURRENT_ROUTE);
    ((CarResetSetRouteFn)e->fn)(vt_this(ctrl, e), route, point);
    controller_call(c, CARCONTROLLER_VT_JUST_RESET);

    if (blink)
        car_start_blinking(c, 2.0f);
}

// 0x001317d0. The debug warp: x and y from `pos`, z from the ground, and
// the heading `angle` *relative to the track path* at that point. None of
// ResetCore's clearing is done -- the state, the wheels, the driver and the
// replay are left as they were -- and the velocity is flat, speed along
// the new heading.
//
// The track path is updated from `pos` itself, not from Position. The
// heading goes through the state and is read back for the sine and cosine,
// so it is the sixteen-bit one.
void car_debug_set_position(Car *c, const bVector3 *pos, float speed,
                            uint16_t angle)
{
    CarState *st = &c->State;
    MovementMode mode = c->TheMovementMode;
    const TrackPathCoordinate *tpc = &c->TheTrackPathCoordinate;

    car_set_movement_mode(c, eNO_MOVEMENT);
    st->Position.x = pos->x;
    st->Position.y = pos->y;
    trackpath_coord_update_position(&c->TheTrackPathCoordinate,
                                    (const bVector2 *)pos);
    st->Angle = (uint16_t)(angle + (uint32_t)bATan(tpc->PathDirection.x,
                                                   tpc->PathDirection.y));
    car_put_flat_on_track(c);
    st->ForwardSpeed = speed;
    st->Velocity.x = speed * bCosBam(st->Angle);
    st->Velocity.y = speed * bSinBam(st->Angle);
    st->Velocity.z = 0.0f;
    car_set_movement_mode(c, mode);
}
