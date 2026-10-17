// carsnap -- Car::DoSnapshot, retail's 0x00130ff0: the car's part of a
// replay snapshot (TASKS 72b).
//
// The car's own fields, its CarDamage, its modes and skin, then through
// their tables the controller's, the mover's (PhysicsCar's tree) and the
// collision body's snapshots, CarState's, the animated driver's, and the
// track path coordinate's. A restore sets both modes to 0 and back, so the
// controller and mover are made again, and switches the skin if the ride's
// changed.
//
// The port's Car keeps the demo's order with retail's four fields at the
// end (car.h), so each move names its field. The comments give retail's
// offset. A file of its own because it reaches CarDamage, the render info's
// skin, the collision body and the track path, which car.c's checkers do
// not link.
//
// Prototypes: car.h. Cross-check: tools/carsnap_check.py. Write-up:
// docs/formats/car.md, "The replay's snapshot".

#include <stdio.h>
#include <stdlib.h>

#include "car.h"
#include "carcontroller.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "carstate.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "physicscar.h"
#include "replay.h"
#include "trackpath.h"
#include "vtable.h"

AnimatedDriverDoSnapshotFn gAnimatedDriverDoSnapshotFn;

typedef void (*CarSnapshotFn)(void *self, ReplaySnapshot *s);

// 0x00130ff0. The name is bSPrintf'd into 16 bytes of the stack, which the
// section keeps a pointer to, as retail's does.
void car_do_snapshot(Car *c, ReplaySnapshot *s)
{
    char name[16];
    int8_t skin;
    uint8_t bits;
    const VtEntry *e;

    snprintf(name, sizeof name, "Car%d", c->CarIndex);
    ReplaySnapshot_BeginNamedSection(s, name);
    ReplaySnapshot_MoveData(s, &c->CopLights, 1, -1, 0);          // 2056
    ReplaySnapshot_MoveData(s, &c->SignalLightState, 1, 4, 0);    // 2060
    ReplaySnapshot_MoveTimer(s, &c->HeadlightsAndHornStartTime); // 2080
    ReplaySnapshot_MoveFloat(s, &c->HeadlightsAndHornOnDuration); // 2084
    ReplaySnapshot_MoveFloat(s,
                             &c->HeadlightsAndHornSecondOnDuration); // 2088
    ReplaySnapshot_MoveFloat(s, &c->HeadlightsAndHornOffDuration); // 2092
    ReplaySnapshot_MoveBool(s, &c->HeadlightsState, 1);           // 2100
    ReplaySnapshot_MoveBool(s, &c->ForceHeadlightsOn, 1);         // 2096
    ReplaySnapshot_MoveBool(s, &c->WantToBlinkHeadlights, 1);     // 2068
    ReplaySnapshot_MoveBool(s, &c->WantToHonkHorn, 1);            // 2072
    ReplaySnapshot_MoveBool(s, &c->WantTwoHonksAndOrBlinks, 1);   // 2076
    ReplaySnapshot_MoveData(s, &c->TheSirenMode, 1, 4, 0);        // 2104
    ReplaySnapshot_MoveInt(s, (int32_t *)&c->WiperOnTime, 4);     // 2108
    ReplaySnapshot_MoveInt(s, (int32_t *)&c->WiperOffTime, 4);    // 2112
    ReplaySnapshot_MoveData(s, &c->WiperState, 1, 4, 0);          // 2116
    ReplaySnapshot_MoveChar(s, (int8_t *)&c->BlownTireBits, 1);   // 2124
    ReplaySnapshot_MoveChar(s, (int8_t *)&c->NumBlownTires, 1);   // 2125
    // 2128, through the Timer overload: the same four bytes as a float's.
    ReplaySnapshot_MoveFloat(s, &c->fBlownTireControllerRumbleTimer);
    if (c->pCarDamage != NULL)                                    // 2120
        cardamage_do_snapshot(c->pCarDamage, s);
    ReplaySnapshot_MoveData(s, &c->TheControlMode, 1, 4, 0);      //   32
    ReplaySnapshot_MoveData(s, &c->TheMovementMode, 1, 4, 0);     //   36
    skin = c->pRideInfo->SkinNumber;
    ReplaySnapshot_MoveChar(s, &c->pRideInfo->SkinNumber, 1);
    if (s->RestoringSnapshotFlag) {
        ControlMode control = c->TheControlMode;
        MovementMode movement = c->TheMovementMode;

        car_set_control_mode(c, 0);
        car_set_movement_mode(c, 0);
        car_set_control_mode(c, control);
        car_set_movement_mode(c, movement);
        if (skin != c->pRideInfo->SkinNumber)
            car_switch_skin(c, (uint32_t)(int32_t)c->pRideInfo->SkinNumber);
    }
    e = vt_slot(c->pCarController->_vtable, CARCONTROLLER_VT_DO_SNAPSHOT);
    ((CarSnapshotFn)e->fn)(vt_this(c->pCarController, e), s);
    e = vt_slot(c->pCarMover->_vtable, CARMOVER_VT_DO_SNAPSHOT);
    ((CarSnapshotFn)e->fn)(vt_this(c->pCarMover, e), s);
    carstate_do_snapshot(&c->State, s);                           //   64
    e = vt_slot(c->pDynamicCollisionBody->Dynamic.Body._vtable,
                COLLISIONBODY_VT_DO_SNAPSHOT);
    ((CarSnapshotFn)e->fn)(vt_this(c->pDynamicCollisionBody, e), s);
    if (c->pAnimatedDriver != NULL) {                             // 1204
        if (gAnimatedDriverDoSnapshotFn == NULL) {
            fprintf(stderr, "car_do_snapshot: AnimatedDriver is not "
                            "ported\n");
            abort();
        }
        gAnimatedDriverDoSnapshotFn(c->pAnimatedDriver, s);
    }
    ReplaySnapshot_MoveFloat(s, &c->OldSpeed);                    // 1184
    ReplaySnapshot_MoveData(s, &c->DispGear, 1, -1, 0);           // 1104
    ReplaySnapshot_MoveFloat(s, &c->FrictionBoost);               // 1108
    ReplaySnapshot_MoveChar(s, &c->RenderingEnabled, 1);          // 1192
    ReplaySnapshot_MoveBool(s, &c->DriverRenderingEnabled, 1);    // 1196
    ReplaySnapshot_MoveFloat(s, &c->AirTimeSwitch);               // 1188
    trackpath_coord_do_snapshot(&c->TheTrackPathCoordinate, s);   // 2016
    // ResetMe (2136) in the low four bits, JustResetFrames (2140) above.
    if (s->RestoringSnapshotFlag) {
        bits = 0;
        ReplaySnapshot_MoveUChar(s, &bits, 1);
        c->ResetMe = bits & 15;
        c->JustResetFrames = bits >> 4;
    } else {
        bits = (uint8_t)((uint8_t)c->ResetMe
                         + ((uint8_t)c->JustResetFrames << 4));
        ReplaySnapshot_MoveUChar(s, &bits, 1);
    }
    ReplaySnapshot_MoveBool(s, &c->bPoofed, 1);                   // 2160
    ReplaySnapshot_MoveBool(s, &c->bVisibleOnTrackMap, 1);        // 2164
    ReplaySnapshot_MoveData(s, &c->BlinkTimer, 4, -1, 0);         // 2144
    ReplaySnapshot_MoveFloat(s, &c->BlinkDuration);               // 2148
    ReplaySnapshot_MoveVector2(s, &c->LastInTroughPosition);      // 2152
    ReplaySnapshot_MoveData(s, c->NumTimesSkidding, 4, 4, 0);     // 2168
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)
        c->DraftFactor = 0.0f;                                    // 1112
    ReplaySnapshot_MoveBool(s, &c->NitroEffectFlag, 1);           // 2064
    ReplaySnapshot_MoveFloat(s, &c->fTractionBoostOverride);      // 1116
    ReplaySnapshot_MoveFloat(s, &c->fDamageBoostOverride);        // 1120
    ReplaySnapshot_EndNamedSection(s);
}
