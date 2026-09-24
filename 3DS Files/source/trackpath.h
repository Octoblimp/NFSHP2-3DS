// trackpath -- TrackPath.obj (0x001f4fd8 .. 0x001f6058): the measuring tape
// laid along the track.
//
// TrackPath is not the route system. A TrackRoute is a list of points a car
// can drive; a TrackPath is how far around the lap a position is. Everything
// that asks "who is ahead", "which lap", "how far to the finish" asks it:
// Car keeps a TrackPathCoordinate at 1840, Signpost::SetDistances,
// TrackRoute::SetFirstAndLast and TrackRoutePoint::GetDistanceAway measure
// with one, and CompareDistances has seventeen callers.
//
// The data is a graph of points, each on a numbered path. Each path is a
// run of consecutive points with a distance at each end, and
// TrackPathManager::Init fits a QuickSpline through every path's points
// and calibrates its arc length. UpdatePosition finds the nearest point,
// then the closest parameter on that path's spline, and reads the distance
// out of the spline's w lane.
//
// Everything in the object is here except DoSnapshot, which waits on
// ReplaySnapshot, and PlotToCaffeine, a debug plot into Caffeine that
// nothing calls.
//
// `gTrackPathDistanceFn` is a test seam that is not on the disc.
// tools/trackroute_check.py sets it to a closed form so that TrackRoute's
// arithmetic can be checked without a track. It is NULL on the handheld.
//
// Written up in docs/formats/track-path.md.
#ifndef TRACKPATH_H
#define TRACKPATH_H

#include <stdint.h>

#include "bvector.h"
#include "quickspline.h"

// ------------------------------------------------------------------ the data

// 20 bytes. The nodes of the track's path graph; `NeighbourNumbers` are
// indices into the same table, -1 for "none".
typedef struct TrackPathPoint {
    bVector2 Position;           // 0
    int8_t   PathNumber;         // 8
    int8_t   DontSwitch;         // 9
    int16_t  NeighbourNumbers[3];// 10
    float    Distance;           // 16  distance around the track
} TrackPathPoint;

// 40 bytes, loaded in place. The path's points are
// [BeginPointNumber, EndPointNumber) of the point table.
//
// pQuickSpline is a QuickSpline * on the disc, zero in the bundle and
// filled in by Init. A loaded path *is* the chunk's bytes, so the record
// has to be 40 bytes on every machine the checker or the handheld runs on,
// and a pointer is not four bytes on all of them. Here it is a word:
// zero, or a handle trackpath_path_spline() turns back into the spline.
// Init's test is the disc's -- skip a path whose word is non-zero -- and
// Close zeroes it.
typedef struct TrackPath {
    int8_t   PathNumber;       // 0
    int8_t   Looping;          // 1
    int16_t  BeginPointNumber; // 2
    int16_t  EndPointNumber;   // 4
    int16_t  NumPoints;        // 6
    float    BeginDistance;    // 8
    float    EndDistance;      // 12
    float    DistanceRatio;    // 16
    bVector2 BeginPosition;    // 20
    bVector2 EndPosition;      // 28
    uint32_t pQuickSpline;     // 36, see above
} TrackPath;

typedef char trackpath_layout_check[
    (sizeof(TrackPathPoint) == 20 && sizeof(TrackPath) == 40) ? 1 : -1];

// 24 bytes on the disc. `TheTrackPathManager` at 0x00313768.
typedef struct TrackPathManager {
    float                 TrackLength;          // 0
    int                   ReverseTrackDirection;// 4
    int                   NumPaths;             // 8
    TrackPath            *pPaths;               // 12
    int                   NumPoints;            // 16
    TrackPathPoint       *pPoints;              // 20
} TrackPathManager;

// 40 bytes on the disc.
typedef struct TrackPathCoordinate {
    bVector2        Position;           // 0
    TrackPathPoint *pTrackPoint;        // 8
    float           SplineParam;        // 12
    float           RatioAroundTrack;   // 16
    float           DistanceAroundTrack;// 20
    bVector2        PathDirection;      // 24
    void           *pCaffeineObj;       // 32, 64 bits on the disc
    uint32_t        CaffeineObjHigh;    // 36
} TrackPathCoordinate;

extern TrackPathManager TheTrackPathManager;

// The QuickSplines Init builds, one per path. The disc keeps each in its
// path's pQuickSpline; the port keeps them here and puts a handle in the
// word. Sixty-four is far above the one path the one track on hand has.
#define TRACKPATH_MAX_SPLINES 64

// A path's spline, or NULL when Init has not built one (or its word is
// something the port did not write).
QuickSpline *trackpath_path_spline(const TrackPath *p);

// UpdatePosition's FindClosestParam tolerance, gp-28124 (0x3d4ccccd).
#define TRACKPATH_PARAM_TOLERANCE 0.05f

// How far a coordinate may move before UpdatePosition stops trusting its
// last point and searches the whole table: 128.0 (0x43000000).
#define TRACKPATH_RESEARCH_DISTANCE 128.0f

// ------------------------------------------------------ TrackPathManager

// 0x001f4fd8. Zeroes the lot.
void trackpath_manager_init(TrackPathManager *m);

// 0x001f4ff8 without the delete: Close.
void trackpath_manager_dtor(TrackPathManager *m);

// 0x001f5048, the manager's Init. TrackLength from pPaths[0].EndDistance,
// then for every path whose word is zero a QuickSpline -- LOOP for a
// looping path, EXTRAPOLATED otherwise -- through its points, z and w
// zero, calibrated with 16 samples a segment.
void trackpath_manager_setup(TrackPathManager *m);

// 0x001f51b8. Deletes every path's spline and zeroes its word.
void trackpath_manager_close(TrackPathManager *m);

// 0x001f5238. Takes the two tables and runs Init.
void trackpath_manager_load(TrackPathManager *m, TrackPathPoint *points,
                            int npoints, TrackPath *paths, int npaths);

// 0x001f5250. Close, then zeroes everything but ReverseTrackDirection.
void trackpath_manager_unload(TrackPathManager *m);

// 0x001f5288. Takes the 0x80034147 container: its first sub-chunk
// (0x00034148 on the disc) is the TrackPath table and the second
// (0x00034149) the TrackPathPoint table, taken by position and each counted
// by division, and Loads them in place. Returns 1 when the chunk was this
// one's.
int trackpath_loader(TrackPathManager *m, uint8_t *chunk);

// 0x001f52f8. Unloads.
int trackpath_unloader(TrackPathManager *m, const uint8_t *chunk);

// 0x001f53c8. The nearest point of any path, by the 2D distance; the first
// of equals. NULL with no points.
TrackPathPoint *trackpath_find_closest_point(TrackPathManager *m,
                                             const bVector2 *pos);

// 0x001f54a8. The nearest of `pt` and its neighbours along its own path,
// wrapping round a looping path's ends. `pt` wins a tie.
TrackPathPoint *trackpath_find_closest_adjacent_point(TrackPathManager *m,
                                                      const bVector2 *pos,
                                                      TrackPathPoint *pt);

// 0x001f5620. Measures `pos`: sets every field of the coordinate.
void trackpath_manager_update_position(TrackPathManager *m,
                                       TrackPathCoordinate *c,
                                       const bVector2 *pos);

// 0x001f5928. The inverse, roughly: a position `along` the track and
// `side` to its left, measured from the coordinate's point (or path
// `path`'s first point), then UpdatePosition on it. See trackpath.c --
// it only walks one point per call.
void trackpath_manager_update_position_along(TrackPathManager *m,
                                             TrackPathCoordinate *c,
                                             float along, float side,
                                             int path);

// 0x001f5b70. The signed short way round a loop of TrackLength:
//
//   d = a - b;  if (d < -len/2) d += len;  else if (len/2 < d) d -= len;
//
// d == -len/2 falls through to the second test and comes back unchanged.
float trackpath_compare_distances(const TrackPathManager *m, float a,
                                  float b);

// 0x001f5bc0. The same over percentages: +/-50, wrapping by 100.
float trackpath_compare_percent_distances(const TrackPathManager *m,
                                          float a, float b);

// 0x001f5c28. The same over ratios: +/-0.5, wrapping by 1. Nothing calls
// it.
float trackpath_compare_ratios(const TrackPathManager *m, float a, float b);

// --------------------------------------------------- TrackPathCoordinate

// 0x001f5c90. Everything zero but PathDirection.x, which is 1.0.
void trackpath_coord_init(TrackPathCoordinate *c);

// 0x001f5cc8. The same, then UpdatePosition(pos).
void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos);

// 0x001f5dd0. TheTrackPathManager's UpdatePosition -- or, when the test
// seam is set, the seam's distance and nothing else.
void trackpath_coord_update_position(TrackPathCoordinate *c,
                                     const bVector2 *pos);

// 0x001f5df8. TheTrackPathManager's UpdatePosition(along, side, 0).
void trackpath_coord_update_position_along(TrackPathCoordinate *c,
                                           float along, float side);

// -------------------------------------------------- the global wrappers

void init_track_paths(void);            // 0x001f5f48, Init
void close_track_paths(void);           // 0x001f5f58, Close
int  loader_track_path(uint8_t *chunk);                 // 0x001f5f68
int  unloader_track_path(const uint8_t *chunk);         // 0x001f5f90
void load_track_paths(TrackPathPoint *points, int npoints, TrackPath *paths,
                      int npaths);      // 0x001f5fb8
void unload_track_paths(void);          // 0x001f5fe0

// The test seam. NULL on the handheld; tools/trackroute_check.py points it
// at a closed form so the transcript has non-zero distances to reason about.
typedef float (*TrackPathDistanceFn)(const bVector2 *pos);
extern TrackPathDistanceFn gTrackPathDistanceFn;

#endif
