// zonepreview -- zonecameras.cpp's ZonePreviewCameraMover (CM_ZONE_PREVIEW),
// the preview zone's camera. The addresses are retail's.
//
// With the world paused, the camera flies out along the road ahead, a comet
// running on before it, and back again. The constructor lays out four
// splines from the PreviewRoute, two for the eye (out and back) and two for
// the look point (one along the route, and one for the run out that turns to
// look at what stands on the road), and two Linears that map the run's
// progress onto the splines' parameters; six blends join the camera to the
// run, the run's two halves at its far end, and the run back to the camera.
// Update steps through them: in for 0.25 s, out at 100 m/s (the route's
// length times 0.01), the turn for 0.4 s, back at 300 m/s, and out for
// 0.6 s, holding 0.8 s at each stop on the way out.
//
// Ported: the constructor (0x00161f98), the destructor (0x00163620),
// Update (0x001639d0), Render (0x00163790), Duration (0x001637c8), Enable
// (0x00163978), Disable (0x001639a0), FindRoute (0x00163708) and
// ViolatesTopology (0x00164180), with the free function EnsureTopology
// (0x0015fea0) and Spline::LinearEstimateLength (0x0018a030). The vtable is
// 0x002b2050. The splines are previewspline.c's, the stops previewstops.c's
// and the comet previewcomet.c's; zonecam.c has the Zone Freeze camera.
//
// Written up in docs/formats/camera.md, "The Zone Preview camera"; checked
// on retail's image by tools/zonepreview_check.py.

#ifndef ZONEPREVIEW_H
#define ZONEPREVIEW_H

#include <stddef.h>
#include <stdint.h>

#include "average.h"
#include "banim.h"
#include "bvector.h"
#include "cammover.h"
#include "previewcomet.h"
#include "previewroute.h"
#include "spline.h"
#include "topology.h"

struct Car;

// 1104 bytes, as Player::ChangeCameraMover's bMalloc asks. The demo's
// .mdebug record (880 bytes) names the members it had; retail added the
// run's two times, the stops, the hold and the look-ahead spline.
typedef struct ZonePreviewCameraMover {
    CameraMover        base;               //    0
    BSpline3D         *pEyeBlendIn;        //   44  the camera onto the run
    BSpline3D         *pLookBlendIn;       //   48
    BSpline3D         *pEyeBlendMid;       //   52  the turn at the far end
    BSpline3D         *pLookBlendMid;      //   56
    BSpline3D         *pEyeBlendOut;       //   60  the run back onto the camera
    BSpline3D         *pLookBlendOut;      //   64
    BSpline           *pFocusPull;         //   68
    float              fTime;              //   72  seconds since the start
    float              fTanFov;            //   76
    float              fOutTime;           //   80  the run out, in seconds
    float              fBackTime;          //   84  the run back
    float              fHoldTime;          //   88  left of a stop's hold
    float              fStops[4];          //   92  look parameters, 0 none
    Spline             LookSpline;         //  108  along the route
    Spline             LookAheadSpline;    //  156  the run out's
    Spline             EyeForwardSpline;   //  204
    Spline             EyeBackwardSpline;  //  252
    Linear             EyeParameter;       //  300  progress to the eye's
    Linear             LookParameter;      //  308  and the look's
    PreviewComet       Comet;              //  316
    TopologyCoordinate Topology;           //  364
    // vAnchorEye is a quadword, 16-aligned on the EE.
    uint8_t            _pad1068[4];        // 1068
    bVector3           vAnchorEye;         // 1072  the camera at the start
    bVector3           vAnchorLook;        // 1088
} ZonePreviewCameraMover;                   // 1104

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char zonepreview_layout_check[
    (offsetof(ZonePreviewCameraMover, pFocusPull) == 68
     && offsetof(ZonePreviewCameraMover, fStops) == 92
     && offsetof(ZonePreviewCameraMover, LookSpline) == 108
     && offsetof(ZonePreviewCameraMover, EyeParameter) == 300
     && offsetof(ZonePreviewCameraMover, Comet) == 316
     && offsetof(ZonePreviewCameraMover, Topology) == 364
     && offsetof(ZonePreviewCameraMover, vAnchorEye) == 1072
     && sizeof(ZonePreviewCameraMover) == 1104) ? 1 : -1];
#endif

extern const CameraMoverVtbl ZonePreviewCameraMoverVtbl;

// 0x0015fea0. For each pair, the look's then the eye's: the interest box
// about the midpoint of `anchor` and the point, as big as half the gap,
// then the move from the anchor to the point constrained one way, one
// side. Past 15 the box is 15 and its centre is the half gap times 15 off
// the point, not 15 along it, as the image has it.
void zone_ensure_topology(TopologyCoordinate *tc, bVector3 *anchorEye,
                          bVector3 *eye, bVector3 *anchorLook,
                          bVector3 *look);

// 0x00161f98. `pos` is not read. The six blends and the focus pull are
// bMalloc'd (zonecameras.cpp lines 1049 to 1157); the route is the
// caller's still.
ZonePreviewCameraMover *zone_preview_camera_mover_init(
    ZonePreviewCameraMover *m, int viewID, PreviewRoute *route,
    bVector3 *pos);

// 0x00163620: the vtable back, RadialBlurOff for the player if there is
// one, the blends freed, then the TopologyCoordinate, the comet, the four
// splines and the base.
void zone_preview_camera_mover_destroy(ZonePreviewCameraMover *m);

// 0x001637c8: the in, the run out, 0.8 s for each stop inside the look's
// run, the turn, the run back and the out.
float zone_preview_camera_mover_duration(ZonePreviewCameraMover *m);

// 0x001639d0. Nothing while the game flow is paused; else a RealTimeElapsed
// step, or a hold's, the radial blur by the stage, the matrix and field of
// view to the camera, and with SoundEnabled the zone sample's levels.
void zone_preview_camera_mover_update(ZonePreviewCameraMover *m);

// 0x00163790: the comet, by the run out's progress, until the run out
// ends.
void zone_preview_camera_mover_render(ZonePreviewCameraMover *m,
                                      eView *view);

// 0x00163978 and 0x001639a0: the base's, and the comet's emitters on or
// off with it.
void zone_preview_camera_mover_enable(ZonePreviewCameraMover *m);
void zone_preview_camera_mover_disable(ZonePreviewCameraMover *m);

// 0x00163708, static. A PreviewRoute 40 out and 320 long from the car
// (bMalloc'd, line 1192), or NULL, the route deleted, when it has no
// points or fewer than 4.
PreviewRoute *zone_preview_find_route(struct Car *car);

// 0x00164180. 1 when a walk along the look spline, in steps of about 10
// in its length, crosses a polygon from either side; the topology is its
// own.
int32_t zone_preview_violates_topology(ZonePreviewCameraMover *m);

// For the seams (playercam.h, playerzone.h).
CameraMover *zone_preview_camera_mover_new(void *mem, int viewID,
                                           PreviewRoute *route,
                                           bVector3 *pos);
int32_t zone_preview_violates_topology_fn(CameraMover *m);
float zone_preview_duration_fn(CameraMover *m);


// Spline::LinearEstimateLength, 0x0018a030: with Dirty set, the length
// worked out again as the sum of the straight runs between the control
// points, and Dirty cleared; the length.
float spline_linear_estimate_length(Spline *s);

#endif
