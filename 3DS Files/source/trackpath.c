// trackpath -- see trackpath.h and docs/formats/track-path.md.
#include "trackpath.h"

#include <math.h>
#include <stddef.h>

#include "bchunk.h"
#include "bmem.h"
#include "eefpu.h"
#include "replay.h"

#define CHUNK_TRACKPATH        0x80034147u
#define CHUNK_TRACKPATH_PATHS  0x00034148u
#define CHUNK_TRACKPATH_POINTS 0x00034149u

TrackPathManager    TheTrackPathManager;
TrackPathDistanceFn gTrackPathDistanceFn;

// ------------------------------------------------------------ the splines

static QuickSpline *Splines[TRACKPATH_MAX_SPLINES];

QuickSpline *trackpath_path_spline(const TrackPath *p)
{
    uint32_t h = p->pQuickSpline;

    if (h == 0 || h > TRACKPATH_MAX_SPLINES)
        return NULL;
    return Splines[h - 1];
}

static int free_slot(void)
{
    int k;

    for (k = 0; k < TRACKPATH_MAX_SPLINES; k++)
        if (Splines[k] == NULL)
            return k;
    return -1;
}

// The distance UpdatePosition and the two searches measure: 2D, x term
// plus y term, sqrt.s.
static float dist2(float dx, float dy)
{
    return sqrtf(dx * dx + dy * dy);
}

// ------------------------------------------------------ TrackPathManager

// 0x001f4fd8.
void trackpath_manager_init(TrackPathManager *m)
{
    m->NumPaths              = 0;
    m->pPaths                = NULL;
    m->NumPoints             = 0;
    m->pPoints               = NULL;
    m->TrackLength           = 0.0f;
    m->ReverseTrackDirection = 0;
}

// 0x001f4ff8.
void trackpath_manager_dtor(TrackPathManager *m)
{
    trackpath_manager_close(m);
}

// 0x001f5048.
void trackpath_manager_setup(TrackPathManager *m)
{
    int i;

    // `lwc1 $f0,12(v0)` sits ahead of the count test, with its store in
    // the branch's delay slot: TrackLength is pPaths[0].EndDistance even
    // when there are no paths, as long as there is a table to read. With
    // no table at all the image reads address 12; the port reads nothing.
    m->TrackLength = m->pPaths != NULL ? m->pPaths[0].EndDistance : 0.0f;

    for (i = 0; i < m->NumPaths; i++) {
        TrackPath   *path = &m->pPaths[i];
        QuickSpline *s;
        int          slot, j;

        // A path that already has a spline keeps it, so a second Init --
        // InitTrackPaths after the loader's -- builds nothing.
        if (path->pQuickSpline != 0)
            continue;

        // The port's one limit: no handle, no spline, and the path
        // measures nothing. Sixty-four is not approached.
        slot = free_slot();
        if (slot < 0)
            continue;

        // new QuickSpline(Looping ? LOOP : EXTRAPOLATED, OVERHAUSER,
        // NumPoints), from bMalloc(40, "..\indep\src\trackpath.cpp", 73,
        // 16). `movn s0,zero,v0`: any non-zero Looping byte is a loop.
        s = bMalloc((int)sizeof(QuickSpline), "..\\indep\\src\\trackpath.cpp",
                    73, 16);
        quickspline_init(s, path->Looping != 0 ? QUICKSPLINE_LOOP
                                               : QUICKSPLINE_EXTRAPOLATED,
                         QUICKSPLINE_OVERHAUSER, path->NumPoints);
        Splines[slot] = s;
        path->pQuickSpline = (uint32_t)slot + 1u;
        quickspline_set_num_control_points(s, path->NumPoints);

        // The path's points, flat: z and w zero. CalibrateLength fills
        // the w lanes in.
        for (j = 0; j < path->NumPoints; j++) {
            const TrackPathPoint *pt =
                &m->pPoints[path->BeginPointNumber + j];
            bVector4 *cp = &s->pControlPoints[j];

            cp->x = pt->Position.x;
            cp->y = pt->Position.y;
            cp->z = 0.0f;
            cp->w = 0.0f;
            s->ControlPointsDirty = 1;
        }
        quickspline_calibrate_length(s, 16);
    }
}

// 0x001f51b8.
void trackpath_manager_close(TrackPathManager *m)
{
    int i;

    for (i = 0; i < m->NumPaths; i++) {
        TrackPath   *path = &m->pPaths[i];
        QuickSpline *s;

        if (path->pQuickSpline == 0)
            continue;
        // `delete`: the destructor with flags 3, which frees the buffer
        // and then the spline. A word the port did not write has nothing
        // behind it to free; the image would free whatever it pointed at.
        s = trackpath_path_spline(path);
        if (s != NULL) {
            Splines[path->pQuickSpline - 1] = NULL;
            quickspline_destroy(s, 3);
        }
        path->pQuickSpline = 0;
    }
}

// 0x001f5238.
void trackpath_manager_load(TrackPathManager *m, TrackPathPoint *points,
                            int npoints, TrackPath *paths, int npaths)
{
    m->NumPaths  = npaths;
    m->pPaths    = paths;
    m->NumPoints = npoints;
    m->pPoints   = points;
    trackpath_manager_setup(m);
}

// 0x001f5250. Note what it does *not* clear: ReverseTrackDirection keeps
// whatever the last track set.
void trackpath_manager_unload(TrackPathManager *m)
{
    trackpath_manager_close(m);
    m->TrackLength = 0.0f;
    m->NumPaths    = 0;
    m->pPaths      = NULL;
    m->NumPoints   = 0;
    m->pPoints     = NULL;
}

// 0x001f5288. The original loads in place -- the tables it points at are
// the chunk's own bytes, still owned by the bundle, and Init writes each
// path's spline word into them -- and so does this. It takes the two
// sub-chunks by position, not by type: the paths are whatever comes first,
// the points whatever starts where the first one's payload ends. Neither
// sub-chunk's type is read, and nor is the container's own size.
//
// Both counts come from a division (`divu`): `size / 40` paths and
// `size / 20` points. There is no count field anywhere in the chunk. On
// TRACKB12 it is one looping path of 55 points and a table of 56.
int trackpath_loader(TrackPathManager *m, uint8_t *chunk)
{
    uint8_t *first, *second;
    uint32_t pathSize, pointSize;

    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;

    first     = chunk + 8;
    pathSize  = bchunk_u32(first + 4);
    second    = first + 8 + pathSize;
    pointSize = bchunk_u32(second + 4);

    trackpath_manager_load(m,
                           (TrackPathPoint *)(uintptr_t)(second + 8),
                           (int)(pointSize / 20u),
                           (TrackPath *)(uintptr_t)(first + 8),
                           (int)(pathSize / 40u));
    return 1;
}

// 0x001f52f8.
int trackpath_unloader(TrackPathManager *m, const uint8_t *chunk)
{
    if (bchunk_u32(chunk) != CHUNK_TRACKPATH) return 0;
    trackpath_manager_unload(m);
    return 1;
}

// 0x001f53c8.
TrackPathPoint *trackpath_find_closest_point(TrackPathManager *m,
                                             const bVector2 *pos)
{
    TrackPathPoint *best = NULL;
    float           bestd = 0.0f;
    int             i, j;

    for (i = 0; i < m->NumPaths; i++) {
        const TrackPath *path = &m->pPaths[i];

        for (j = path->BeginPointNumber; j < path->EndPointNumber; j++) {
            TrackPathPoint *p;
            float           d;

            // A negative index is a NULL point in the image, read at
            // address 0. No bundle has one.
            if (j < 0)
                continue;
            p = &m->pPoints[j];
            d = dist2(p->Position.x - pos->x, p->Position.y - pos->y);
            // `c.lt.s d,best`: the first of equals.
            if (best == NULL || d < bestd) {
                bestd = d;
                best = p;
            }
        }
    }
    return best;
}

// 0x00207d48, retail only.
TrackPathPoint *trackpath_find_closest_point_near(TrackPathManager *m,
                                                  const bVector2 *pos,
                                                  float dist)
{
    TrackPathPoint *best = NULL;
    float           bestd = 0.0f;
    int             i, j;

    // `sub.s $f21,$f0,$f21`: TrackLength - dist, not dist - TrackLength.
    if (m->ReverseTrackDirection)
        dist = m->TrackLength - dist;
    for (i = 0; i < m->NumPaths; i++) {
        const TrackPath *path = &m->pPaths[i];

        for (j = path->BeginPointNumber; j < path->EndPointNumber; j++) {
            TrackPathPoint *p;
            float           d;

            // As in FindClosestPoint: the image reads a negative index's
            // NULL point at address 0, and no bundle has one.
            if (j < 0)
                continue;
            p = &m->pPoints[j];
            d = dist2(p->Position.x - pos->x, p->Position.y - pos->y);
            d += fabsf(trackpath_compare_distances(m, p->Distance, dist)
                       * 0.25f);
            if (best == NULL || d < bestd) {
                bestd = d;
                best = p;
            }
        }
    }
    return best;
}

// 0x001f54a8.
TrackPathPoint *trackpath_find_closest_adjacent_point(TrackPathManager *m,
                                                      const bVector2 *pos,
                                                      TrackPathPoint *pt)
{
    TrackPathPoint  *cand[3];
    const TrackPath *path = &m->pPaths[pt->PathNumber];
    int              idx = (int)(pt - m->pPoints);
    int              n = 1, k;
    TrackPathPoint  *best = NULL;
    float            bestd = 0.0f;

    // The point itself first, so it wins a tie; then the one before and
    // the one after, round the ends of a looping path. A negative index
    // at a looping end is a NULL candidate in the image; no bundle has
    // one, and the port leaves it out.
    cand[0] = pt;
    if (idx != path->BeginPointNumber) {
        cand[n++] = pt - 1;
    } else if (path->Looping != 0 && path->EndPointNumber - 1 >= 0) {
        cand[n++] = &m->pPoints[path->EndPointNumber - 1];
    }
    if (idx != path->EndPointNumber - 1) {
        cand[n++] = pt + 1;
    } else if (path->Looping != 0 && path->BeginPointNumber >= 0) {
        cand[n++] = &m->pPoints[path->BeginPointNumber];
    }

    for (k = 0; k < n; k++) {
        TrackPathPoint *q = cand[k];
        float d = dist2(pos->x - q->Position.x, pos->y - q->Position.y);

        if (best == NULL || d < bestd) {
            best = q;
            bestd = d;
        }
    }
    return best;
}

// 0x001f5620.
void trackpath_manager_update_position(TrackPathManager *m,
                                       TrackPathCoordinate *c,
                                       const bVector2 *pos)
{
    TrackPathPoint *pt = c->pTrackPoint;
    TrackPathPoint *old;
    TrackPath      *path;
    QuickSpline    *s;
    bVector3        p;
    bVector4        v;
    bVector2        dir;
    float           best, guess, param, dist;
    int             k;

    // The last point is a fine place to start from unless the coordinate
    // has jumped more than 128 units since.
    if (pt == NULL
        || TRACKPATH_RESEARCH_DISTANCE < dist2(pos->x - c->Position.x,
                                               pos->y - c->Position.y))
        pt = trackpath_find_closest_point(m, pos);

    // No points at all: the coordinate is put where it was asked to be,
    // facing +x, at distance zero. Its point and parameter are left alone.
    if (pt == NULL) {
        c->Position = *pos;
        c->PathDirection.x = 1.0f;
        c->RatioAroundTrack = 0.0f;
        c->PathDirection.y = 0.0f;
        c->DistanceAroundTrack = 0.0f;
        return;
    }

    pt = trackpath_find_closest_adjacent_point(m, pos, pt);
    best = dist2(pos->x - pt->Position.x, pos->y - pt->Position.y);
    old = c->pTrackPoint;
    guess = c->SplineParam;

    // Then across to another path, through the graph's links. Each link
    // is read off the point that is nearest *so far*, so a switch at the
    // first link means the next two are the new point's.
    for (k = 0; k < 3; k++) {
        int16_t         nb = pt->NeighbourNumbers[k];
        TrackPathPoint *q;
        float           d;

        if (nb < 0)
            continue;
        q = &m->pPoints[nb];
        d = dist2(pos->x - q->Position.x, pos->y - q->Position.y);
        if (d < best) {
            pt = q;
            best = d;
        }
    }

    // A new point restarts the search from that point's own parameter; the
    // same point carries on from the last answer.
    path = &m->pPaths[pt->PathNumber];
    if (pt != old) {
        c->pTrackPoint = pt;
        guess = (float)((int)(pt - m->pPoints) - path->BeginPointNumber);
    }

    // A path Init never reached has no spline, and the image would fault
    // on it. The port stops with the point found and nothing measured.
    s = trackpath_path_spline(path);
    if (s == NULL) {
        c->Position = *pos;
        return;
    }

    p.x = pos->x;
    p.y = pos->y;
    p.z = 0.0f;
    param = quickspline_find_closest_param(s, &p, guess,
                                           TRACKPATH_PARAM_TOLERANCE);

    // The image evaluates the position three times over: once into a
    // temporary nothing reads, once for the tangent, once more for the w.
    // The first is left out; it can only run FindClosestParam's fixups a
    // second time, and those are already clean.
    quickspline_get_point(s, &v, param, 1);
    dir.x = v.x;
    dir.y = v.y;
    quickspline_get_point(s, &v, param, 0);
    bNormalize2(&dir, &dir);

    // The w lane is arc length along this path; the path says where it
    // starts and how its length scales to the lap's.
    dist = path->BeginDistance + v.w * path->DistanceRatio;
    if (m->ReverseTrackDirection != 0) {
        dir.x = -dir.x;
        dir.y = -dir.y;
        dist = m->TrackLength - dist;
    }

    c->SplineParam = param;
    c->Position = *pos;
    c->PathDirection = dir;
    c->DistanceAroundTrack = dist;
    c->RatioAroundTrack = ee_div(dist, m->TrackLength);
}

// 0x001f5928's direction lives in the first eight bytes of its frame, and
// one path out of the function reads it without writing it -- so it reads
// what the previous call left there. The only caller,
// CalculateRacerPositions, calls it in a loop from one frame with nothing
// in between, so "the previous call's direction" is exactly what the image
// gets. Before the first call the image's slot holds whatever an earlier
// function left at that depth; the port's holds zero.
static bVector2 AlongDirection;

// Pointer order the way `sltu` sees it, NULL lowest.
static int ptr_below(const void *a, const void *b)
{
    return (uintptr_t)a < (uintptr_t)b;
}

// 0x001f5928.
void trackpath_manager_update_position_along(TrackPathManager *m,
                                             TrackPathCoordinate *c,
                                             float along, float side,
                                             int path)
{
    TrackPathPoint  *pt = c->pTrackPoint;
    const TrackPath *tp;
    TrackPathPoint  *first, *last;
    int              left;
    bVector2         p, perp;

    // A fresh coordinate starts at path `path`'s first point. (`beq
    // v0,zero` tests the path's address, which is NULL only with no table
    // and path 0.)
    if (pt == NULL) {
        if (m->pPaths != NULL && m->pPoints != NULL
            && m->pPaths[path].BeginPointNumber >= 0)
            pt = &m->pPoints[m->pPaths[path].BeginPointNumber];
        if (pt == NULL) {
            c->RatioAroundTrack = 0.0f;
            c->PathDirection.x = 1.0f;
            c->Position.x = 0.0f;
            c->Position.y = 0.0f;
            c->PathDirection.y = 0.0f;
            c->DistanceAroundTrack = 0.0f;
            return;
        }
    }

    // The path's ends, once: the walk never leaves the path.
    tp = &m->pPaths[pt->PathNumber];
    last = tp->EndPointNumber - 1 >= 0
         ? &m->pPoints[tp->EndPointNumber - 1] : NULL;
    first = tp->BeginPointNumber >= 0
          ? &m->pPoints[tp->BeginPointNumber] : NULL;

    // Walk to the point whose distance brackets `along`. The step count
    // starts at NumPoints and the loop goes round again only when it
    // reaches *zero* (`beq a1,zero`): any other count leaves after one
    // step, before the direction is worked out, and the position below is
    // built from whatever direction the last call left. It reads like a
    // `--left == 0` meant as `!= 0`; it is kept.
    for (left = m->NumPoints;;) {
        TrackPathPoint *next = ptr_below(pt, last) ? pt + 1 : NULL;
        TrackPathPoint *prev = ptr_below(first, pt) ? pt - 1 : NULL;

        if (along < pt->Distance && prev != NULL) {
            pt = prev;
        } else if (pt->Distance < along && next != NULL
                   && next->Distance < along) {
            // The image loads next->Distance without testing next, so at
            // a path's last point it reads address 16. No shipped call
            // gets there; the port does not follow it.
            pt = next;
        } else {
            // Here: along the path from this point, or into it from the
            // one before at the path's end. A one-point path has neither,
            // and the image reads address 0; the port measures nothing.
            if (next != NULL) {
                AlongDirection.x = next->Position.x - pt->Position.x;
                AlongDirection.y = next->Position.y - pt->Position.y;
            } else if (prev != NULL) {
                AlongDirection.x = pt->Position.x - prev->Position.x;
                AlongDirection.y = pt->Position.y - prev->Position.y;
            } else {
                AlongDirection.x = 0.0f;
                AlongDirection.y = 0.0f;
            }
            bNormalize2(&AlongDirection, &AlongDirection);
            break;
        }
        left = left - 1;
        if (left != 0)
            break;
    }

    // `along` from the point -- the whole of it, not the part past the
    // point's own distance -- and `side` to the left of the direction.
    bScaleAdd2(&p, &pt->Position, &AlongDirection, along);
    perp.x = AlongDirection.y;
    perp.y = -AlongDirection.x;
    bScaleAdd2(&p, &p, &perp, side);
    trackpath_manager_update_position(m, c, &p);
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

// 0x001f5bc0.
float trackpath_compare_percent_distances(const TrackPathManager *m,
                                          float a, float b)
{
    float d = a - b;

    (void)m;
    if (d < -50.0f) return d + 100.0f;
    if (50.0f < d)  return d - 100.0f;
    return d;
}

// 0x001f5c28.
float trackpath_compare_ratios(const TrackPathManager *m, float a, float b)
{
    float d = a - b;

    (void)m;
    if (d < -0.5f) return d + 1.0f;
    if (0.5f < d)  return d - 1.0f;
    return d;
}

// --------------------------------------------------- TrackPathCoordinate

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

// 0x001f5cc8.
void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos)
{
    trackpath_coord_init(c);
    trackpath_coord_update_position(c, pos);
}

// 0x001f5dd0.
void trackpath_coord_update_position(TrackPathCoordinate *c,
                                     const bVector2 *pos)
{
    // The seam: a closed-form distance and nothing else, for the TrackRoute
    // checker. Not on the disc.
    if (gTrackPathDistanceFn) {
        c->Position = *pos;
        c->DistanceAroundTrack = gTrackPathDistanceFn(pos);
        c->RatioAroundTrack    = TheTrackPathManager.TrackLength != 0.0f
                               ? c->DistanceAroundTrack
                                     / TheTrackPathManager.TrackLength
                               : 0.0f;
        return;
    }
    trackpath_manager_update_position(&TheTrackPathManager, c, pos);
}

// 0x00134f18, in Car.obj; retail's is 0x00208838, in TrackPath.obj.
void trackpath_coord_reset_position(TrackPathCoordinate *c,
                                    const bVector2 *pos)
{
    c->pTrackPoint = NULL;
    trackpath_coord_update_position(c, pos);
}

// 0x00208848, retail only.
void trackpath_coord_reset_position_near(TrackPathCoordinate *c,
                                         const bVector2 *pos, float dist)
{
    TrackPathPoint *p;

    c->pTrackPoint = NULL;
    p = trackpath_find_closest_point_near(&TheTrackPathManager, pos, dist);
    if (p != NULL)
        trackpath_coord_update_position(c, &p->Position);
    trackpath_coord_update_position(c, pos);
}

// 0x001f5df8.
void trackpath_coord_update_position_along(TrackPathCoordinate *c,
                                           float along, float side)
{
    trackpath_manager_update_position_along(&TheTrackPathManager, c, along,
                                            side, 0);
}

// -------------------------------------------------- the global wrappers

void init_track_paths(void)
{
    trackpath_manager_setup(&TheTrackPathManager);
}

void close_track_paths(void)
{
    trackpath_manager_close(&TheTrackPathManager);
}

int loader_track_path(uint8_t *chunk)
{
    return trackpath_loader(&TheTrackPathManager, chunk);
}

int unloader_track_path(const uint8_t *chunk)
{
    return trackpath_unloader(&TheTrackPathManager, chunk);
}

void load_track_paths(TrackPathPoint *points, int npoints, TrackPath *paths,
                      int npaths)
{
    trackpath_manager_load(&TheTrackPathManager, points, npoints, paths,
                           npaths);
}

void unload_track_paths(void)
{
    trackpath_manager_unload(&TheTrackPathManager);
}

// ---------------------------------------------------------------- the replay

// 0x00207bd0. The index is the byte difference times 5's inverse, shifted
// down two: an exact division by the point's 20 bytes.
void trackpath_manager_do_snapshot(TrackPathManager *m, TrackPathPoint **pp,
                                   ReplaySnapshot *s)
{
    int16_t index = -1;

    if (*pp != NULL)
        index = (int16_t)(*pp - m->pPoints);
    ReplaySnapshot_MoveShort(s, &index, 2);
    if (index == -1)
        *pp = NULL;
    else if (index < 0)
        *pp = NULL;
    else
        *pp = m->pPoints + index;
}

// 0x00208768.
void trackpath_coord_do_snapshot(TrackPathCoordinate *c, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "TrackPathCoordinate");
    ReplaySnapshot_MoveVector2(s, &c->Position);
    trackpath_manager_do_snapshot(&TheTrackPathManager, &c->pTrackPoint, s);
    ReplaySnapshot_MoveFloat(s, &c->SplineParam);
    ReplaySnapshot_MoveFloat(s, &c->RatioAroundTrack);
    ReplaySnapshot_MoveFloat(s, &c->DistanceAroundTrack);
    ReplaySnapshot_MoveVector2(s, &c->PathDirection);
    ReplaySnapshot_EndNamedSection(s);
}
