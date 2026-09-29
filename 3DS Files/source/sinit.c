// sinit -- see sinit.h.
//
// One line per ported constructor: the call, then its __CTOR_LIST__ index
// and the _GLOBAL_$I$ it stands for. sinit_check reads those comments, so
// their shape is fixed.
//
// None of the seventeen reads anything another one writes -- sixteen fill
// Tables, Graphs, cameras, list heads, hashes, shakers and constants, and
// the seventeenth builds the slot-pool manager -- so the order is kept
// because it is the image's, not because a different one would be
// observed. The manager comes last for that reason too: it is entry 103,
// long after the physics tables. The joystick's, [23], is named for EventNodeSlotPool but never
// touches it: InitJoystick makes that pool at boot, once the manager is up;
// Track's, [22], leaves TrackPolygonSlotPool for InitTree in the same way,
// and CollisionBody's, [67], its three pools for InitCollisionBody.

#include "sinit.h"

#include "aerodynamics.h"
#include "bslotpool.h"
#include "car.h"
#include "collisionbody.h"
#include "drivetarget.h"
#include "eview.h"
#include "joyevent.h"
#include "mellowmover.h"
#include "physicscar.h"
#include "realdriver.h"
#include "rigidbody.h"
#include "scenery.h"
#include "shake.h"
#include "sky.h"
#include "terraintype.h"
#include "track.h"
#include "wheel.h"

void sinit_run(void)
{
    eview_static_init();        // [2]   0x00114098 _GLOBAL_$I$FloatingVBlankTimeMin
    sky_static_init();          // [6]   0x0011cfb8 _GLOBAL_$I$SkydomeModel
    car_static_init();          // [14]  0x001347c0 _GLOBAL_$I$fDraftFalloff
    physicscar_static_init();   // [15]  0x00137438 _GLOBAL_$I$RigidBodySlotPool
    realdriver_static_init();   // [17]  0x0013aa88 _GLOBAL_$I$PowerSlideYawCoef
    scenery_static_init();      // [21]  0x0014e718 _GLOBAL_$I$CurrentZoneNumber
    track_static_init();        // [22]  0x00150938 _GLOBAL_$I$TrackPositionMarkerList
    joyevent_static_init();     // [23]  0x00152588 _GLOBAL_$I$EventNodeSlotPool
    shake_static_init();        // [24]  0x001537b8 _GLOBAL_$I$bShakeTest
    rigidbody_static_init();    // [41]  0x00193d20 _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo
    wheel_static_init();        // [44]  0x0019b558 _GLOBAL_$I$SliderPositionsX
    aerodynamics_static_init(); // [54]  0x001a4de8 _GLOBAL_$I$FrontDownforceLocation
    terraintype_static_init();  // [66]  0x001ca120 _GLOBAL_$I$TerrainTypeInfoTable
    collisionbody_static_init(); // [67]  0x001ce548 _GLOBAL_$I$TheCollisionStats
    mellowmover_static_init();  // [86]  0x00208420 _GLOBAL_$I$MellowForceFeedbackGraph
    drivetarget_static_init();  // [87]  0x0020ab48 _GLOBAL_$I$__11DriveTarget
    bSlotPoolManagerInit();     // [103] 0x00240080 _GLOBAL_$I$bNewSlotPool__FiiPCci
}
