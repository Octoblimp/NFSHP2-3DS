// carinit -- Car's constructor and destructor, from retail.
//
// Car(DriverInfo *, bVector3 *pos, unsigned short angle, float dist) is
// retail's 0x00130a48 (1176 bytes; the demo's 0x0012f240 is 1052), and
// ~Car is 0x00130ee0 (the demo's 0x0012f660). Both are ported from retail,
// onto the demo's layout of Car as car.h keeps it. The retail offsets are
// in carinit.c's comments, and docs/formats/car.md has the whole map.
//
// Retail's constructor differs from the demo's in five ways:
//
// - It takes a distance along the track. A negative one resets the
//   TrackPathCoordinate as the demo did; any other picks the nearest point
//   whose own distance is near it (trackpath_coord_reset_position_near), so
//   that a car placed where the track crosses itself lands on the right leg.
// - It zeroes retail's new fields and one the demo left alone,
//   fBlownTireControllerRumbleTimer. It sets the second horn duration to -1
//   with the other two.
// - It saves the start position as vOldPos too.
// - Once the render info is made, it has CarDamage look up its breakable
//   parts in the car's model.
// - ForceBuzzTime is rounded, not truncated.
//
// The callees the port does not have yet are seams. Those that only make
// the car sound or draw are skipped when NULL, and the car is built without
// them. Those that can only be reached with something a seam made abort
// when NULL, in carmodes.h's style.

#ifndef CARINIT_H
#define CARINIT_H

#include <stdint.h>

#include "car.h"

// 7emEvent, 36 bytes (the stabs). The event manager's; Car only reads
// CarPtr. The links are the list's, as 32-bit slots, as in BodyDamage.
typedef struct emEvent {
    uint32_t pNext;               //  0  bTNode<emEvent>
    uint32_t pPrev;               //  4
    uint32_t ReferenceCount;      //  8
    int32_t  ID;                  // 12
    void    *pEventTrigger;       // 16
    Car     *CarPtr;              // 20
    uint32_t Parameter0;          // 24
    uint32_t Parameter1;          // 28
    uint32_t Parameter2;          // 32
} emEvent;                        // 36

// CarDamage's bMalloc size in retail, which grew 16 bytes over the demo's
// 212 (cardamage.h). It becomes sizeof(CarDamage) when the damage system is
// ported.
#define CARDAMAGE_SIZE 228

// The events the constructor asks for: emAddHandler's mask.
#define CAR_EVENT_MASK 0x10000u

// SoundEnabled (the demo's gp-23628, retail's gp-23056), 1 in .sdata. The
// sound layer's; it is here until that is ported. With it clear no car
// gets a sound.
extern int32_t SoundEnabled;

// -------------------------------------------------------------- the seams
//
//   sound::CreatePlayerCarSound(Car *)   0x0018eb28  skipped
//   sound::CreateAICarSound(Car *)       0x0018eb70  skipped
//   sound::CreateAICopCarSound(Car *)    0x0018ebb8  skipped
//   BaseCarSound's destructor            vptr 28, slot 8, aborts
//   CarDamage::CarDamage(Car *)          0x001b54b0  skipped
//   CarDamage, the parts                 0x001b5598  aborts
//   CarDamage::~CarDamage                0x001b5538  aborts
//   Car::InitRenderInfo(RideInfo *)      0x0011dc80  skipped
//   CarRenderInfo::~CarRenderInfo        0x0011fac0  aborts
//   emAddHandler(fn, mask)               0x001ba2d0  skipped
//   emRemoveHandler(fn)                  0x001ba3a8  skipped
//
// The part lookup is new in retail and nameless: for each of fifteen
// breakable items it finds the item's part by name in the car's model and
// keeps its index, in the bytes CarDamage grew by. The handler is skipped
// because what it reflects to, Car::EventHandler, is empty.
typedef BaseCarSound *(*CarCreateSoundFn)(Car *c);
typedef void          (*CarBaseCarSoundDestroyFn)(BaseCarSound *s,
                                                  int32_t flags);
typedef CarDamage    *(*CarDamageCtorFn)(void *mem, Car *c);
typedef void          (*CarDamageFn)(CarDamage *d);
typedef void          (*CarDamageDestroyFn)(CarDamage *d, int32_t flags);
typedef void          (*CarInitRenderInfoFn)(Car *c, RideInfo *ride);
typedef void          (*CarRenderInfoDestroyFn)(CarRenderInfo *ri,
                                                int32_t flags);
typedef void          (*EmHandlerFn)(emEvent *e);
typedef int32_t       (*EmAddHandlerFn)(EmHandlerFn fn, uint32_t mask);
typedef void          (*EmRemoveHandlerFn)(EmHandlerFn fn);

extern CarCreateSoundFn         gCreatePlayerCarSoundFn;
extern CarCreateSoundFn         gCreateAICarSoundFn;
extern CarCreateSoundFn         gCreateAICopCarSoundFn;
extern CarBaseCarSoundDestroyFn gBaseCarSoundDestroyFn;
extern CarDamageCtorFn          gCarDamageCtorFn;
extern CarDamageFn              gCarDamageFindItemPartsFn;
extern CarDamageDestroyFn       gCarDamageDestroyFn;
extern CarInitRenderInfoFn      gCarInitRenderInfoFn;
extern CarRenderInfoDestroyFn   gCarRenderInfoDestroyFn;
extern EmAddHandlerFn           gEmAddHandlerFn;
extern EmRemoveHandlerFn        gEmRemoveHandlerFn;

// ------------------------------------------------------------ the methods

// 0x00130a48. Builds `c` in place for the driver, at `pos` (NULL for the
// origin) facing `angle`, `dist` along the track (negative for anywhere).
// Returns `c`.
Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist);

// 0x00130ee0. The controller, the mover and the collision body through
// their destructors, then the damage, the render info, the Espresso object
// and the sound; the handler off; the two coordinates. `flags & 1` frees
// the car, as the bNode destructor it ends in does.
void car_destruct(Car *c, int32_t flags);

// 0x0011e280. The render info through its destructor, and the pointer
// cleared.
void car_close_render_info(Car *c);

// 0x00130a28, CarReflectEventHandler: the event to its car's
// EventHandler, when it names one.
void car_reflect_event_handler(emEvent *e);

#endif
