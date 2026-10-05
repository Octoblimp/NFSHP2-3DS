// cammover -- CameraMover.obj (0x00154380 .. 0x0015c4d0), in part.
//
// A CameraMover decides where a Camera goes. There are eighteen kinds on the
// disc (the enum below is the complete list, lifted from
// GetCameraMoverTypeName at 0x154380) and one base class with a virtual
// Update that each of them overrides.
//
// This file ports the base; drivecam.c ports CM_DRIVE and orbitcam.c
// CM_ORBIT_CAR. The rest are deliberately left: CM_BUMPER and
// CM_REAR_VIEW_MIRROR need the car's wheels, CM_TRACK_CAR and CM_TRACK_FLY
// need a route that can answer "how far around the lap is this" --
// TrackRoute is ported now, but that answer waits on QuickSpline.obj -- the
// CM_ZONE_* ones need the streaming world, and CM_DEBUG_WORLD, CM_MAX and
// CM_TRACK_ROUTE_EDITOR are development tools that were left in the build.
//
// Written up with addresses in docs/formats/camera.md. Checked on retail's
// image by tools/cambase_check.py, and against the demo's model by
// tools/camera_check.py.
#ifndef CAMMOVER_H
#define CAMMOVER_H

#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "camera.h"
#include "camerainfo.h"
#include "eview.h"

// GetCameraMoverTypeName, retail's 0x00157578 (the demo's 0x00154380).
// The numbering is the disc's.
typedef enum CameraMoverType {
    CM_NONE = 0,
    CM_DRIVE,
    CM_DEBUG_WORLD,
    CM_TRACK_ROUTE_EDITOR,
    CM_ORBIT_CAR,
    CM_BUMPER,
    CM_REAR_VIEW_MIRROR,
    CM_TRACK_CAR,
    CM_GARAGE,
    CM_TRACK_FLY,
    CM_MAX,
    CM_SELECT_CAR,
    CM_STILL,
    CM_ZONE_FREEZE,
    CM_ZONE_PREVIEW,
    CM_ZONE_JUMPER,
    CM_ZONE_JUMPER2,
    CM_CUBIC_DAMPER
} CameraMoverType;

// Any other value, negative too, is retail's "CM_UNKNOWN(?)" (0x002b1620);
// the demo's fell through to "CM_NONE".
const char *camera_mover_type_name(CameraMoverType t);

// ------------------------------------------------------------ the base class
//
// 44 bytes on the disc, vtable pointer at offset 40. The constructor takes a
// view id, as the disc's does, and the Camera is the view's:
// eGetView(id)->pCamera. A mover is a bTNode, so enabling it puts it on the
// head of its view's list by its Node, which is what the view mode and the
// projection read.
typedef struct CameraMover CameraMover;
typedef struct CameraMoverVtbl CameraMoverVtbl;

// The offsets are the disc's, from the .mdebug record for CameraMover
// (44 bytes), and retail's are the same.
struct CameraMover {
    bNode           Node;           // 0   on pView's CameraMoverList
    CameraMoverType Type;           // 8
    int             ViewID;         // 12
    int             Enabled;        // 16
    eView          *pView;          // 20
    Camera         *pCamera;        // 24
    void           *pPlayer;        // 28  a Player *
    void           *CarNotToRender; // 32
    int             RenderDash;     // 36
    const CameraMoverVtbl *vtbl;    // 40
};

// Retail's vtable; CameraMover's is at 0x002b1e50. On the PS2 each entry is
// eight bytes, a this-delta and the function, after an eight-byte head; the
// offsets here are the function's. The demo had nine virtuals. Retail put
// three new ones after GetPOV, made Enable and Disable virtual, and moved
// GetCarToFollow up into the base. No retail symbols name the three new
// ones; the names are the port's, from what DriveCameraMover's do (step 7).
struct CameraMoverVtbl {
    void  (*Destroy)(CameraMover *m);              // +12  the destructor
    void  (*Update)(CameraMover *m);               // +20
    void  (*Render)(CameraMover *m, eView *view);  // +28
    void  (*AddJoyHandlers)(CameraMover *m);       // +36
    void  (*RemoveJoyHandlers)(CameraMover *m);    // +44
    const CameraInfo *(*GetCameraInfo)(CameraMover *m); // +52
    const POV *(*GetPOV)(CameraMover *m, int index); // +60
    int   (*IsExteriorView)(CameraMover *m);       // +68
    int   (*IsLookingBack)(CameraMover *m);        // +76
    float (*GetWallGap)(CameraMover *m);           // +84
    void  (*ResetState)(CameraMover *m);           // +92
    void  (*Enable)(CameraMover *m);               // +100
    void  (*Disable)(CameraMover *m);              // +108
    void *(*GetCarToFollow)(CameraMover *m);       // +116 a Car *
    const bVector3 *(*GetTarget)(CameraMover *m);  // +124
};

// The base's, 0x002b1e50. Update, Render, the joystick pair and ResetState
// do nothing (0x001577c8, 0x001577d0, 0x0015fd40, 0x0015fd38, 0x0015fd10);
// GetCameraInfo, GetPOV, IsLookingBack and GetCarToFollow return 0
// (0x0015fd30, 0x0015fd28, 0x0015fd18, 0x0015fcf8); IsExteriorView returns
// 1 (0x0015fd20); GetWallGap returns 0.7 (0x00157920, gp-31288); GetTarget
// is the camera's (0x0015fcb0).
extern const CameraMoverVtbl CameraMoverBaseVtbl;

// The base's do-nothing Update (the joystick pair and ResetState are the
// same) and Render, which the other movers' vtables share.
void camera_mover_nothing(CameraMover *m);
void camera_mover_render(CameraMover *m, eView *view);

// The base's GetCameraInfo, GetPOV, IsExteriorView, IsLookingBack and
// GetWallGap (above), which the orbit mover's vtable shares.
const CameraInfo *camera_mover_get_camera_info(CameraMover *m);
const POV *camera_mover_get_pov(CameraMover *m, int index);
int   camera_mover_is_exterior_view(CameraMover *m);
int   camera_mover_is_looking_back(CameraMover *m);
float camera_mover_get_wall_gap(CameraMover *m);

// Retail's 0x001576e8 (the demo's 0x001544f0). It sets the base vtable. A
// ViewID of -1 leaves the mover detached and disabled; any other value takes
// the view and its camera, sets the camera's far plane to 10000 (gp-31292;
// the demo's was 5000), and enables the mover, which sets the near plane to
// 0.5. The view must have its camera by then: eInitViews gives views 0 to 3
// theirs.
void camera_mover_init(CameraMover *m, int viewID, CameraMoverType type);

// Retail's 0x00157780: the base vtable back, then Disable, by name rather
// than by the vtable. The PS2's delete is the caller's here, as a free.
void camera_mover_destroy(CameraMover *m);

// Retail's 0x001577d8 / 0x00157850 (the demo's 0x001545e0 / 0x00154658),
// the same but for the camera's offsets. Neither is a no-op while CameraStopUpdating is
// set, and they do not treat it the same way. Enable skips the two render
// flags it would push at the camera but still forces the near plane to 0.5;
// Disable does not test the flag at all, and pulls both render flags back
// off the camera on its way out. Both early-out when the flag is already
// where they would put it. Enable attaches the mover to its view and
// Disable unattaches it, each after the flags.
void camera_mover_enable(CameraMover *m);
void camera_mover_disable(CameraMover *m);

// The base's accessors, 0x0015fca0 .. 0x0015fd08: the camera's position and
// direction keys, the target by the vtable, and the player.
const bVector3 *camera_mover_get_position(const CameraMover *m);
const bVector3 *camera_mover_get_direction(const CameraMover *m);
void camera_mover_set_player(CameraMover *m, void *player);

// Retail's 0x00157888: world up (0, 0, 1) turned `roll` about the unit way
// from `eye` to `look`. The mover is not read. TrackCarCameraMover banks
// with it.
void camera_mover_compute_banked_up_vector(CameraMover *m, bVector3 *out,
                                           const bVector3 *eye,
                                           const bVector3 *look,
                                           uint16_t roll);

// Retail's UpdateCameraMovers, 0x0015ef28. For each of the ten views, the
// FIRST mover on its list is updated, by its vtable, and the rest wait. The
// movers read RealTimeElapsed themselves. Two debug tails are left out: the
// JollyRancher feed, which asks bFunkDoesServerExist once and, while a
// server answers, sends view 1's camera every 17 ticks (no server answers
// the shipped game), and CameraMoverAddNearbyDebugTopology on view 1's eye,
// which is empty in retail (0x00203e18).
void update_camera_movers(void);

// Retail's RenderCameraMovers, 0x0015eee0: the view's first mover's Render.
void render_camera_movers(eView *view);

#endif
