// trackpath -- see trackpath.h. The measuring tape, minus the spline.
#include "trackpath.h"

#include <stddef.h>

#include "bchunk.h"

#define CHUNK_TRACKPATH        0x80034147u
#define CHUNK_TRACKPATH_PATHS  0x00034148u
#define CHUNK_TRACKPATH_POINTS 0x00034149u

TrackPathManager    TheTrackPathManager;
TrackPathDistanceFn gTrackPathDistanceFn;

// 0x001f4fd8.
void trackpath_manager_init(TrackPathManager *m)
{
    m->TrackLength           = 0.0f;
    m->ReverseTrackDirection = 0;
    m->NumPaths              = 0;
    m->pPaths                = NULL;
    m->NumPoints             = 0;
    m->pPoints               = NULL;
}

// 0x001f5288. The original loads in place -- the tables it points at are the
// chunk's own bytes, still owned by the bundle -- and so does this. It also
// takes the two sub-chunks positionally, by walking past the first one's
// size rather than by matching a type, which is why a bundle whose author
// swapped them would load paths as points without complaint. The type check
// below is ours, not the disc's, and it costs nothing.
//
// Both counts come from a division: `size / 40` paths and `size / 20`
// points. There is no count field anywhere in the chunk.
int trackpath_loader(TrackPathManager *m, const uint8_t *chunk, uint32_t size)
{
    uint32_t       pathSize  = 0;
    uint32_t       pointSize = 0;
    const uint8_t *paths;
    const uint8_t *points;

    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;

    paths  = bchunk_find(chunk, 8, size, CHUNK_TRACKPATH_PATHS, &pathSize);
    points = bchunk_find(chunk, 8, size, CHUNK_TRACKPATH_POINTS, &pointSize);
    if (!paths || !points) return 0;

    // In place, into the bundle's own bytes, exactly as the original does.
    m->pPaths    = (TrackPath *)(uintptr_t)paths;
    m->NumPaths  = (int)(pathSize / sizeof(TrackPath));
    m->pPoints   = (TrackPathPoint *)(uintptr_t)points;
    m->NumPoints = (int)(pointSize / sizeof(TrackPathPoint));

    // The one line of TrackPathManager::Init (0x001f5048) that needs no
    // spline: TrackLength is pPaths[0].EndDistance. On TRACKB12 that is
    // 7164.28 over a single looping path of 55 points.
    m->TrackLength = m->NumPaths > 0 ? m->pPaths[0].EndDistance : 0.0f;
    return 1;
}

// 0x001f5f90 -> 0x001f5250. Close() deletes each path's QuickSpline; there
// are none. Note what Unload does *not* clear: ReverseTrackDirection keeps
// whatever the last track set, which is the disc's behaviour and not an
// oversight here.
int trackpath_unloader(TrackPathManager *m, const uint8_t *chunk)
{
    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;
    m->TrackLength = 0.0f;
    m->NumPaths    = 0;
    m->pPaths      = NULL;
    m->NumPoints   = 0;
    m->pPoints     = NULL;
    return 1;
}

int trackpath_have_splines(void)
{
    return 0;
}

// 0x001f5b70.
float trackpath_compare_distances(const TrackPathManager *m, float a, float b)
{
    float len = m->TrackLength;
    float d   = a - b;

    if (d < -len * 0.5f) return d + len;
    if (len * 0.5f < d)  return d - len;
    return d;
}

// 0x001f5c90.
void trackpath_coord_init(TrackPathCoordinate *c)
{
    c->Position.x          = 0.0f;
    c->Position.y          = 0.0f;
    c->pTrackPoint         = NULL;
    c->SplineParam         = 0.0f;
    c->RatioAroundTrack    = 0.0f;
    c->DistanceAroundTrack = 0.0f;
    c->PathDirection.x     = 1.0f;
    c->PathDirection.y     = 0.0f;
    c->pCaffeineObj        = NULL;
    c->CaffeineObjHigh     = 0;
}

// 0x001f5dd0 -> 0x001f5620. The hole.
//
// What the original does, for whoever fills it in: if the coordinate already
// has a point and has moved less than 128 units, it starts from that point,
// otherwise it calls FindClosestPoint over the whole table; it then walks up
// to three neighbours to the nearest adjacent point on the same path, finds
// the closest parameter on that path's QuickSpline, and sets
//
//   DistanceAroundTrack = path->BeginDistance
//                       + splineArcLength(param) * path->DistanceRatio
//
// flipped about TrackLength when ReverseTrackDirection is set, with
// RatioAroundTrack the same over TrackLength and PathDirection the
// normalised spline tangent.
void trackpath_coord_update_position(TrackPathCoordinate *c,
                                     const bVector2 *pos)
{
    c->Position = *pos;
    if (gTrackPathDistanceFn) {
        c->DistanceAroundTrack = gTrackPathDistanceFn(pos);
        c->RatioAroundTrack    = TheTrackPathManager.TrackLength != 0.0f
                               ? c->DistanceAroundTrack
                                     / TheTrackPathManager.TrackLength
                               : 0.0f;
    }
}
