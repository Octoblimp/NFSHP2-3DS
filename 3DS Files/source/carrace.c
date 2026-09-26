// carrace -- Car.obj, slice nine: what the race, the AI and the pursuit
// ask of a car.
//
//   Car::GetDistanceAndSpeed   0x001326b0   static
//   Car::FixBlownTires         0x00133450
//   Car::TriggerTireBlowOut    0x00133368
//   Car::PleaseResetMeLater    0x00131580
//   Car::GetDrivingLineSpeed   0x00131700
//   Car::DeliverMeFromEvil     0x001326d0
//
// Each makes one call out of Car, or two. They are a file of their own for
// carreset.c's reason: DeliverMeFromEvil reaches SetMovementMode and
// FixBlownTires RealDriver, and car.c links into checkers that carry
// neither.
//
// Prototypes and seams: car.h. Cross-check: tools/carmode_check.py.
// Write-up: docs/formats/car.md.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "car.h"
#include "carmodes.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "race.h"
#include "realdriver.h"

// How long a blown tire keeps the pad rumbling: `lui 0x40e0`, an
// immediate, not a gp constant.
#define CAR_BLOWN_TIRE_RUMBLE_TIME 7.0f

CarCopManagerIsBeingPursuedFn     gCopManagerIsBeingPursuedFn;
CarAIDrivingLineSpeedFn           gAICarControllerGetCurrentDrivingLineSpeedFn;
CarDeliveryMoverSetDestinationFn  gDeliveryMoverSetDestinationFn;
CarTriggerEffectFn                gCarTriggerEffectFn;
CarBaseCarSoundFn                 gBaseCarSoundTriggerTireBlowOutFn;

static void not_ported(const char *what)
{
    fprintf(stderr, "car: %s is not ported\n", what);
    abort();
}

// 0x001326b0. Static: the distance between two cars, and the speed through
// `speed`, as their collision bodies see it. The body's answer is a stub
// on the disc (collisionbody.h), so this is 0 both ways.
float car_get_distance_and_speed(float *speed, Car *a, Car *b)
{
    return dynamiccollisionbody_get_distance_and_speed(
        speed, (DynamicCollisionBody *)(void *)a->pDynamicCollisionBody,
        (DynamicCollisionBody *)(void *)b->pDynamicCollisionBody);
}

// 0x00133450. All four tires back, and the rumble stopped. Under
// REAL_CONTROL the driver is a RealDriver, and its ForcedEBrakeStop is
// cleared too, by a tail call. The mode is read before the three stores,
// as the listing does.
void car_fix_blown_tires(Car *c)
{
    ControlMode mode = c->TheControlMode;

    c->BlownTireBits = 0;
    c->NumBlownTires = 0;
    c->fBlownTireControllerRumbleTimer = 0.0f;
    if (mode != REAL_CONTROL)
        return;
    realdriver_force_ebrake_stop((RealDriver *)(void *)c->pCarDriver, 0);
}

// 0x00133368. `tires` is a mask, bit i for wheel i. The count is rebuilt
// from every blown tire, old and new, and the effect goes off at each tire
// in the mask, whether or not it was blown already. The effect's int is
// 0x50000 + i * 0x10000, as the listing builds it; TriggerEffect is the
// render path's, and what it reads the word as is its business. Then the
// car's sound, if it has one.
//
// The effect and the sound are seams in RealDriver's style: nothing is
// shown or heard until their classes are ported, and a NULL one is
// skipped.
void car_trigger_tire_blow_out(Car *c, int32_t tires)
{
    int32_t i;

    c->NumBlownTires = 0;
    c->fBlownTireControllerRumbleTimer = CAR_BLOWN_TIRE_RUMBLE_TIME;
    c->BlownTireBits = (uint8_t)(c->BlownTireBits | tires);
    for (i = 0; i < 4; i++) {
        if ((((int8_t)c->BlownTireBits >> i) & 1) == 0)
            continue;
        c->NumBlownTires++;
        if (((tires >> i) & 1) == 0)
            continue;
        if (gCarTriggerEffectFn != NULL)
            gCarTriggerEffectFn(c, CARFX_BLOWN_TIRE, 1.0f,
                                0x50000 + i * 0x10000, NULL);
    }
    if (c->pBaseCarSound != NULL && gBaseCarSoundTriggerTireBlowOutFn != NULL)
        gBaseCarSoundTriggerTireBlowOutFn(c->pBaseCarSound);
}

// 0x00131580. Asks for a reset on the next Move. The one car that is
// refused is an AI racer the cops are chasing in Be A Cop, with cops in
// the race: it has to be caught, not put back on the road. The cop
// manager is read from gp-16500 and handed over untested.
void car_please_reset_me_later(Car *c)
{
    if (RaceParametersBeACop != 0 && RaceParametersMaxCops > 0
        && c->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER) {
        if (gCopManagerIsBeingPursuedFn == NULL)
            not_ported("tCopManager::IsBeingPursued");
        if (gCopManagerIsBeingPursuedFn(pCopManager, c))
            return;
    }
    c->ResetMe = 1;
}

// 0x00131700. The speed the AI's driving line asks for here. Only the AI
// and traffic controllers are AICarControllers; every other mode answers
// 0 without reading the controller.
float car_get_driving_line_speed(Car *c)
{
    ControlMode mode = c->TheControlMode;

    if (mode != AI_CONTROL && mode != TRAFFIC_CONTROL)
        return 0.0f;
    if (gAICarControllerGetCurrentDrivingLineSpeedFn == NULL)
        not_ported("AICarController::GetCurrentDrivingLineSpeed");
    return gAICarControllerGetCurrentDrivingLineSpeedFn(c->pCarController);
}

// 0x001326d0. Hands the car to a DeliveryMover and sends it to `pos`,
// facing `angle`, arriving at `speed` after `time` seconds. pCarMover is
// read after SetMovementMode, so it is the new mover.
void car_deliver_me_from_evil(Car *c, bVector2 *pos, uint16_t angle,
                              float speed, float time)
{
    car_set_movement_mode(c, DELIVERY_MOVEMENT);
    if (gDeliveryMoverSetDestinationFn == NULL)
        not_ported("DeliveryMover::SetDestination");
    gDeliveryMoverSetDestinationFn(c->pCarMover, pos, angle, speed, time);
}
