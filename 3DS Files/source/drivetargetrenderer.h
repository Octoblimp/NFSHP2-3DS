// drivetargetrenderer -- DriveTargetRenderer (0x001c13c0 .. 0x001c1660), the
// AI's debug view of a DriveTarget: twenty WorldObject markers, put down in
// the world at the target's points. It sits in the AI's utility object,
// just before the route helpers in airoute.c.
//
// Only what the shipped game runs is ported. SetTargetToRender's first test
// is RenderDriveTargetPoints, which ships as 0. With it off, the call only
// takes down markers that an earlier call with it on put up. The port can
// never have put any up: CreateTargetMarkers builds WorldObjects, which are
// not ported. So the flag-on path, and a marker that is somehow there,
// abort rather than pretend.
//
// Six call sites: RealController::Think, AICarController::Think (2),
// TrafficDriver::ExecuteCurrentAction and World::UpdateAIDebugRendering
// (2). Each passes TheDriveTargetRenderer.
#ifndef DRIVETARGETRENDERER_H
#define DRIVETARGETRENDERER_H

#include <stdint.h>

#include "drivetarget.h"

#define DRIVETARGETRENDERER_MARKERS 20

// 84 bytes, as each unit's stab has it: `HasTargetMarkers:/021,0,32;
// DriveTargetMarker:/01161=ar1;0;19;361,32,640` (type#1160 in the first).
typedef struct DriveTargetRenderer {
    int32_t             HasTargetMarkers;                               // 0
    struct WorldObject *DriveTargetMarker[DRIVETARGETRENDERER_MARKERS]; // 4
} DriveTargetRenderer;                                                  // 84

extern DriveTargetRenderer TheDriveTargetRenderer;  // 0x0030c640
extern int32_t             RenderDriveTargetPoints; // 0x003242c8, 0

// 0x001c14c0. With RenderDriveTargetPoints off: DestoryTargetMarkers if
// HasTargetMarkers is set, and nothing else. With it on: not ported.
void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t);

// 0x001c1458 (the image spells it "Destory"). With HasTargetMarkers set,
// each marker's destructor with flags 3, each slot cleared, and the flag
// cleared; without it, nothing.
void drivetargetrenderer_destroy_target_markers(DriveTargetRenderer *r);

#endif
