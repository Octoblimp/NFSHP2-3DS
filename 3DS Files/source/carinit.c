// carinit -- see carinit.h.
//
// The retail offsets are each store's in 0x00130a48 and 0x00130ee0. They
// are the demo's plus 16 from DispGear, 32 from vOldVel, 176 from the
// TrackPathCoordinate and 180, then 184, past retail's new fields.

#include "carinit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "espresso.h"
#include "physicscar.h"
#include "realtime.h"
#include "topology.h"
#include "trackpath.h"
#include "vtable.h"

int32_t SoundEnabled = 1;

CarCreateSoundFn         gCreatePlayerCarSoundFn;
CarCreateSoundFn         gCreateAICarSoundFn;
CarCreateSoundFn         gCreateAICopCarSoundFn;
CarBaseCarSoundDestroyFn gBaseCarSoundDestroyFn;
CarDamageCtorFn          gCarDamageCtorFn;
CarDamageFn              gCarDamageFindItemPartsFn;
CarDamageDestroyFn       gCarDamageDestroyFn;
CarInitRenderInfoFn      gCarInitRenderInfoFn;
CarRenderInfoDestroyFn   gCarRenderInfoDestroyFn;
EmAddHandlerFn           gEmAddHandlerFn;
EmRemoveHandlerFn        gEmRemoveHandlerFn;

static void unported(const char *what)
{
    fprintf(stderr, "carinit: %s is not ported\n", what);
    abort();
}

typedef void (*DtorFn)(void *self, int32_t flags);

// `lw v0,V(obj); lh a0,8(v0); lw v1,12(v0); jalr v1; addu a0,obj,a0`,
// with 3 in a1: the object's virtual destructor, and its memory back.
static void virtual_delete(void *obj, uint32_t vtable, int slot)
{
    const VtEntry *e = vt_slot(vtable, slot);

    ((DtorFn)e->fn)(vt_this(obj, e), 3);
}

// --------------------------------------------------------- the constructor

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    OverrideRenderingPosition *orp = &c->TheOverrideRenderingPosition;
    bVector3 at;
    NullController *ctrl;
    NullMover *m;
    CarCollisionBody *b;

    // `lw a1,-20616(gp)` plus Type * 1376: CarTypeInfos[Type], inline.
    carstate_init(&c->State, &c->TheTopologyCoordinate,
                  (CarTypeInfoPrefix *)
                  cartypeinfo_get(driver->CurrentRideInfo.Type));
    orp->BlinkingViewBits = 0;                          // 1304
    orp->VisibleViewBits = 0xffffffffu;                 // 1300
    orp->OverrideViewBits = 0;                          // 1296
    topology_init(&c->TheTopologyCoordinate);
    trackpath_coord_init(&c->TheTrackPathCoordinate);

    // The start is a quadword at 0(sp) with x, y and z zeroed, or *pos. On
    // the console its w lane is whatever the stack held, and it goes into
    // the three old vectors and State.Position; the port's is zero. With a
    // pos, vOldPos and State.Position take its w.
    at.x = 0.0f;
    at.y = 0.0f;
    at.z = 0.0f;
    at.pad = 0.0f;
    c->HeadlightsAndHornStartTime = 0;                  // 2080
    c->fBlownTireControllerRumbleTimer = 0.0f;          // 2128
    c->BlinkTimer = 0;                                  // 2144
    c->ForceBuzzTime = 0;                               // 2188
    c->vOldPos = at;                                    // 1136
    c->vOldVel = at;                                    // 1152
    c->vOldAngVel = at;                                 // 1168
    if (pos != NULL) {
        at = *pos;
        c->vOldPos = *pos;
    }

    // `c.lt.s $f20,zero`: a NaN is not below zero, and searches near it.
    if (dist < 0.0f)
        trackpath_coord_reset_position(&c->TheTrackPathCoordinate,
                                       (const bVector2 *)&at);
    else
        trackpath_coord_reset_position_near(&c->TheTrackPathCoordinate,
                                            (const bVector2 *)&at, dist);

    c->State.Position = at;                             // 96
    c->State.Angle = angle;                             // 932
    c->BlownTireBits = 0;                               // 2124
    c->NumBlownTires = 0;                               // 2125
    c->FrictionBoost = 1.0f;                            // 1108
    c->DraftFactor = 0.0f;                              // 1112
    c->MyDriver = driver;                               // 20
    c->fTractionBoostOverride = 0.0f;                   // 1116
    c->fDamageBoostOverride = 0.0f;                     // 1120
    c->pRideInfo = &driver->CurrentRideInfo;            // 16
    c->CarIndex = 0;                                    // 8
    // `lbu; sll 24; sra 24`: the driver's number, sign-extended.
    c->DriverNumber = driver->UniqueDriverNumber;       // 10
    c->pPlayer = NULL;                                  // 24
    c->pRacingCar = NULL;                               // 28
    // The type read again, and CarTypeInfos[Type] again.
    c->pCarTypeInfo = (CarTypeInfo *)
        cartypeinfo_get(driver->CurrentRideInfo.Type);  // 12

    c->pBaseCarSound = NULL;                            // 2132
    if (SoundEnabled != 0) {
        CarCreateSoundFn create = NULL;

        // Drivers 0 and 1 are the players. Any other car sounds by its
        // usage, and a usage outside the three gets no sound.
        if (c->DriverNumber == 0 || c->DriverNumber == 1)
            create = gCreatePlayerCarSoundFn;
        else if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_COP)
            create = gCreateAICopCarSoundFn;
        else if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_RACING
                 || c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_TRAFFIC)
            create = gCreateAICarSoundFn;
        if (create != NULL)
            c->pBaseCarSound = create(c);
    }

    ctrl = car_new_null_controller(c);
    c->pCarController = &ctrl->Base;                    // 40
    c->pCarDriver = ctrl->Base.Driver;                  // 44

    // NullMover's new and constructor, inline, as SetMovementMode's
    // eNO_MOVEMENT arm has them.
    m = nullmover_new();
    m->pState = &c->State;
    m->Mover._vtable = NULLMOVER_VTABLE;
    c->pCarMover = &m->Mover;                           // 48
    c->pAnimatedDriver = NULL;                          // 1204

    c->pCarDamage = NULL;                               // 2120
    if (c->pCarTypeInfo->UsageType != CAR_USAGE_TYPE_TRAFFIC
        && gCarDamageCtorFn != NULL)
        c->pCarDamage = gCarDamageCtorFn(
            bMalloc(CARDAMAGE_SIZE, "CarDamage", 0, CAR_MEMORY_POOL), c);

    c->TheControlMode = eNO_CONTROL;                    // 32
    c->TheMovementMode = eNO_MOVEMENT;                  // 36
    b = carcollisionbody_init((CarCollisionBody *)carcollisionbody_new(), c);
    c->pLastCarTrailObj = NULL;                         // 2180
    c->pCaffeineObj = NULL;                             // 2176
    c->LeaveCarTrails = 0;                              // 2184
    c->pDynamicCollisionBody = b;                       // 52
    esp_set_attribute_int(0, "CarNumber", c->DriverNumber);

    car_put_flat_on_track(c);
    c->State.CurrentGear = 2;                           // 968, first
    c->DispGear = 1;                                    // 1104
    c->OldSpeed = 0.0f;                                 // 1184
    c->pRenderInfo = NULL;                              // 1200
    if (gCarInitRenderInfoFn != NULL)
        gCarInitRenderInfoFn(c, c->pRideInfo);
    // Read after InitRenderInfo, which is a Car method and could have set it.
    if (c->pCarDamage != NULL) {
        if (gCarDamageFindItemPartsFn == NULL)
            unported("CarDamage's part lookup");
        gCarDamageFindItemPartsFn(c->pCarDamage);
    }

    c->RenderingEnabled = 1;                            // 1192
    c->DriverRenderingEnabled = 1;                      // 1196
    c->ResetMe = 0;                                     // 2136
    c->JustResetFrames = 0;                             // 2140
    // Where PutFlatOnTrack left the car.
    c->LastInTroughPosition.x = c->State.Position.x;    // 2152
    c->LastInTroughPosition.y = c->State.Position.y;    // 2156
    if (gEmAddHandlerFn != NULL)
        gEmAddHandlerFn(car_reflect_event_handler, CAR_EVENT_MASK);

    c->WiperOnTime = 0;                                 // 2108
    c->WiperOffTime = 0;                                // 2112
    c->WiperState = 0;                                  // 2116
    c->TheSirenMode = 0;                                // 2104
    // `sw zero,2056`: retail stores CopLights as a word, and reads it as
    // one, so the three bytes after the demo's byte go too.
    c->CopLights = 0;                                   // 2056
    memset(c->_hole2025, 0, sizeof c->_hole2025);
    c->HeadlightsState = 0;                             // 2100
    c->ForceHeadlightsOn = 0;                           // 2096
    c->WantToBlinkHeadlights = 0;                       // 2068
    c->WantToHonkHorn = 0;                              // 2072
    c->WantTwoHonksAndOrBlinks = 0;                     // 2076
    c->SignalLightState = SIGNAL_LIGHT_ALL_OFF;         // 2060
    c->HeadlightsAndHornStartTime = WorldTimer;         // 2080
    c->HeadlightsAndHornOffDuration = -1.0f;            // 2092
    c->HeadlightsAndHornOnDuration = -1.0f;             // 2084
    c->HeadlightsAndHornSecondOnDuration = -1.0f;       // 2088
    car_stop_blinking(c);

    c->bVisibleOnTrackMap = 1;                          // 2164
    c->AirTimeSwitch = 0.0f;                            // 1188
    c->bPoofed = 0;                                     // 2160
    c->BlinkDuration = 2.0f;                            // 2148
    // WorldTimer in seconds (gp-32016, 1/4000) and back in ticks, rounded:
    // `add.s` of 0.5 before the `cvt.w.s`, which the demo did not have.
    c->ForceBuzzTime = ee_trunc_w((float)WorldTimer * 0.00025f * 4000.0f
                                  + 0.5f);              // 2188
    // bMemSet(NumTimesSkidding, 0, 4).
    memset(c->NumTimesSkidding, 0, sizeof c->NumTimesSkidding); // 2168
    c->RoadBumpBits = 0;                                // 2172
    c->NitroEffectFlag = 0;                             // 2064
    c->InDeepWaterRegistered = 0;                       // 2196
    return c;
}

// ---------------------------------------------------------- the destructor

void car_destruct(Car *c, int32_t flags)
{
    if (c->pCarController != NULL)
        virtual_delete(c->pCarController, c->pCarController->_vtable,
                       CARCONTROLLER_VT_DTOR);
    if (c->pCarMover != NULL)
        virtual_delete(c->pCarMover, c->pCarMover->_vtable,
                       CARMOVER_VT_DTOR);
    if (c->pDynamicCollisionBody != NULL)
        virtual_delete(c->pDynamicCollisionBody,
                       c->pDynamicCollisionBody->Dynamic.Body._vtable,
                       COLLISIONBODY_VT_DESTROY);

    if (c->pCarDamage != NULL) {
        if (gCarDamageDestroyFn == NULL)
            unported("CarDamage's destructor");
        gCarDamageDestroyFn(c->pCarDamage, 3);
        c->pCarDamage = NULL;
    }
    car_close_render_info(c);
    if (c->pCaffeineObj != NULL)
        esp_delete_object(c->pCaffeineObj);
    // Through the sound's vptr at 28, slot 8, with 3.
    if (c->pBaseCarSound != NULL) {
        if (gBaseCarSoundDestroyFn == NULL)
            unported("BaseCarSound's destructor");
        gBaseCarSoundDestroyFn(c->pBaseCarSound, 3);
    }
    if (gEmRemoveHandlerFn != NULL)
        gEmRemoveHandlerFn(car_reflect_event_handler);

    // ~TrackPathCoordinate (0x00208748) is called with 2, and only frees on
    // bit 0; it has nothing else to do. ~TopologyCoordinate is called with
    // 2 as well.
    topology_destroy(&c->TheTopologyCoordinate);

    // `j _$_t6bTNode1Z3Car` with the flags, which is `j _$_5bNode`: bit 0
    // is `j __builtin_delete`.
    if (flags & 1)
        bFree(c);
}

// ------------------------------------------------------------ the helpers

void car_close_render_info(Car *c)
{
    if (c->pRenderInfo != NULL) {
        if (gCarRenderInfoDestroyFn == NULL)
            unported("CarRenderInfo's destructor");
        gCarRenderInfoDestroyFn(c->pRenderInfo, 3);
    }
    c->pRenderInfo = NULL;
}

void car_reflect_event_handler(emEvent *e)
{
    if (e->CarPtr != NULL)
        car_event_handler(e->CarPtr, e);
}
