// previewroute -- PreviewRoute, the road ahead of a car as a run of racing
// route points, and PreviewRoutePoint. The addresses are retail's; the
// class is zonecameras.cpp's (its bMalloc names that file).
//
// The jump cam is built from one. Player::IsJumpCamAvailable makes a
// PreviewRoute 50 out and 75 long from the player's car, and asks for at
// least five points. The jump cam's two movers (ChangeCameraMover's types
// 15 and 16) read the route's last points for where the camera stands and
// looks. The zone preview (type 14) has its own route, from
// ZonePreviewCameraMover::FindRoute, which is not ported.
//
// The route starts at the car's route point, or the racing route point
// nearest the car, and steps one route point at a time. Each point keeps
// the route and route point it is on, the lateral offset it sits at (a
// driving line's, or 0 on the centre), and which driving line that is. At
// a route's end it jumps to the nearest point ahead on any racing route,
// and keeps how far off to the side the jump landed (fRouteGap).
//
// Written up in docs/formats/camera.md, "The jump cam's route"; checked on
// retail's image by tools/prevroute_check.py.

#ifndef PREVIEWROUTE_H
#define PREVIEWROUTE_H

#include <stdint.h>

#include "bvector.h"
#include "trackroute.h"

struct Car;

// PreviewRoutePoint, 24 bytes (.mdebug type#2712).
typedef struct PreviewRoutePoint {
    TrackRoute      *pRoute;      //  0
    TrackRoutePoint *pPoint;      //  4
    float            fLength;     //  8  to the next point, in 3D
    float            fOffset;     // 12  to the right of the route point
    int32_t          nLine;       // 16  the driving line, -1 for the centre
    float            fRouteGap;   // 20  how far off a route change landed
} PreviewRoutePoint;

// PreviewRoute, 24 bytes (.mdebug type#2720). No vtable.
typedef struct PreviewRoute {
    PreviewRoutePoint *pPoints;          //  0
    int32_t            nPoints;          //  4
    bVector2           vTrackDirection;  //  8  the car's PathDirection
    float              fDistance;        // 16  asked for, then walked
    float              fOffset;          // 20  the car to the right of point 0
} PreviewRoute;

typedef char previewroute_layout_check[
    (sizeof(void *) != 4
     || (sizeof(PreviewRoutePoint) == 24 && sizeof(PreviewRoute) == 24))
    ? 1 : -1];

// What the searches start from: 1000000.0, retail's gp-30712 and gp-30708.
#define PREVIEW_ROUTE_FAR 1000000.0f

// 0x00164630. `length` / 4 points (cvt.w.s) are allocated. The first is
// the car's route point at the nearest of the car class's two driving
// lines, if the car has a route and route point and that is within
// `radius`; with no route or point, ClosestPoint's pick. Then NextPoint
// until the points run out, one fails, or the walk is longer than
// `length`; the count and the walked length are what is kept. If the
// first point fails, the points are freed and the count is 0.
PreviewRoute *preview_route_init(PreviewRoute *pr, struct Car *car,
                                 float radius, float length);

// 0x00164848. Frees the points, and with flag 1 the route.
void preview_route_destroy(PreviewRoute *pr, int32_t flags);

// The destructor with flag 3, for playercam.h's gPreviewRouteDeleteFn.
void preview_route_delete(PreviewRoute *pr);

// 0x001648a0. Point `i` from point i - 1: the next route point on the same
// route at the same line, or past the route's end ClosestPoint from point
// i - 1's place. Point i - 1's fLength becomes the 3D distance between the
// two, which comes back; 0 if ClosestPoint failed.
float preview_route_next_point(PreviewRoute *pr, int32_t i, float radius,
                               int32_t line);

// 0x00164aa0. Where on `point` `pos` is nearest: the first of driving
// lines 2 * line and 2 * line + 1 the route has (IsValid or IsFake), or,
// with neither, the centre when the point runs the car's way. Fills `out`'s
// route, point, offset and line, and answers the distance in the XY plane;
// PREVIEW_ROUTE_FAR if nothing was measured.
float preview_route_closest_distance(const PreviewRoute *pr,
                                     PreviewRoutePoint *out, TrackRoute *r,
                                     TrackRoutePoint *point,
                                     const bVector2 *pos, int32_t line);

// 0x00164c80. Over every racing route, in the manager's order, the point
// FindClosestPoint finds ahead of `pos` within `radius`, `prev` skipped,
// measured by ClosestDistance; the nearest goes to point `index`. 0 if the
// last route's search found nothing, if no route gave a point, or, on a
// point-to-point race, if the point is behind `prev` around the track.
int32_t preview_route_closest_point(PreviewRoute *pr, const bVector2 *pos,
                                    float radius, int32_t line,
                                    int32_t index, TrackRoutePoint *prev);

// PreviewRoutePoint::GetPosition, 0x00164418 and 0x00164428: the point's
// place, `along` the route point and `across` it (the first form: 0 and
// the point's offset).
void preview_route_point_get_position(const PreviewRoutePoint *pt,
                                      bVector3 *o);
void preview_route_point_get_position_at(const PreviewRoutePoint *pt,
                                         bVector3 *o, float along,
                                         float across);

#endif
