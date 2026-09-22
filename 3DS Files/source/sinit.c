// sinit -- see sinit.h.
//
// One line per ported constructor: the call, then its __CTOR_LIST__ index
// and the _GLOBAL_$I$ it stands for. sinit_check reads those comments, so
// their shape is fixed.
//
// None of the five reads anything another one writes -- four fill Tables,
// Graphs and constants, and the fifth builds the slot-pool manager -- so the
// order is kept because it is the image's, not because a different one
// would be observed. The manager comes last for that reason too: it is entry
// 103, long after the physics tables.

#include "sinit.h"

#include "bslotpool.h"
#include "car.h"
#include "drivetarget.h"
#include "rigidbody.h"
#include "wheel.h"

void sinit_run(void)
{
    car_static_init();          // [14]  0x001347c0 _GLOBAL_$I$fDraftFalloff
    rigidbody_static_init();    // [41]  0x00193d20 _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo
    wheel_static_init();        // [44]  0x0019b558 _GLOBAL_$I$SliderPositionsX
    drivetarget_static_init();  // [87]  0x0020ab48 _GLOBAL_$I$__11DriveTarget
    bSlotPoolManagerInit();     // [103] 0x00240080 _GLOBAL_$I$bNewSlotPool__FiiPCci
}
