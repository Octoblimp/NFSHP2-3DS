// trackpath -- the part of TrackPath.obj (0x001f4fd8 .. 0x001f6058) that
// TrackRoute reaches, and an honest edge where the rest of it will go.
//
// TrackPath is not the route system. A TrackRoute is a list of points a car
// can drive; a TrackPath is the *measuring tape* laid along the track, and
// the one number everything wants from it is "how far around the lap is this
// position". Three functions in trackroute.c ask for that number --
// Signpost::SetDistances, TrackRoute::SetFirstAndLast and
// TrackRoutePoint::GetDistanceAway -- and nothing else in the object does.
//
// So this file carries the three structures, the chunk loader and
// CompareDistances, all ported exactly, and stops at one declared hole:
//
//   TrackPathManager::UpdatePosition (0x001f5620) walks the point graph to
//   the nearest path, then refines against that path's QuickSpline with
//   QuickSpline::FindClosestParam and ::GetPoint. QuickSpline.obj
//   (0x00227e98, 0x1018 bytes) is a separate library -- basis matrices,
//   arc-length calibration, the lot -- and it is not ported yet. See the
//   task list.
//
// While it is not ported, trackpath_coord_update_position() leaves
// DistanceAroundTrack alone, so a route's fStartDistance and fEndDistance
// come out of SetFirstAndLast as zero and every signpost's Distance is zero.
// That is visible rather than silent: trackpath_have_splines() says so, and
// the route viewer prints it.
//
// `gTrackPathDistanceFn` is the seam. It is NULL on the handheld and the
// cross-checker sets it to a closed-form stand-in, which is what lets
// tools/trackroute_check.py exercise SetFirstAndLast's wrap detection --
// the one piece of TrackRoute arithmetic that is only reachable through a
// non-zero distance. It is a test hook and it is not on the disc.
//
// Written up in docs/formats/track-route.md.
#ifndef TRACKPATH_H
#define TRACKPATH_H

#include <stdint.h>

#include "bvector.h"

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

// 40 bytes. One run of points, with a spline fitted through them. pSpline is
// a QuickSpline * on the disc; nothing here builds one, so it stays NULL.
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
    void    *pSpline;          // 36
} TrackPath;

// 24 bytes. `TheTrackPathManager` at 0x00313768.
typedef struct TrackPathManager {
    float                 TrackLength;          // 0
    int                   ReverseTrackDirection;// 4
    int                   NumPaths;             // 8
    TrackPath            *pPaths;               // 12
    int                   NumPoints;            // 16
    TrackPathPoint       *pPoints;              // 20
} TrackPathManager;

// 40 bytes.
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

// ------------------------------------------------------------------ the code

// 0x001f4fd8. Zeroes the lot.
void trackpath_manager_init(TrackPathManager *m);

// 0x001f5288 plus 0x001f5f68. Takes the 0x80034147 container: sub-chunk
// 0x00034148 is the TrackPath table and 0x00034149 the TrackPathPoint table,
// each sized by division rather than by a count field. Returns 1 when the
// chunk was this one's.
//
// TrackPathManager::Init (0x001f5048), which fits a QuickSpline through each
// path and takes TrackLength from pPaths[0].EndDistance, is *not* run: the
// spline half of it does not exist yet. TrackLength is set here instead,
// from the same field, because CompareDistances is useless without it and
// that one line of Init needs nothing.
int trackpath_loader(TrackPathManager *m, const uint8_t *chunk, uint32_t size);

// 0x001f5f90. Drops the tables.
int trackpath_unloader(TrackPathManager *m, const uint8_t *chunk);

// Whether the spline half is available. False for now, everywhere.
int trackpath_have_splines(void);

// 0x001f5b70. The signed short way round a loop of TrackLength:
//
//   d = a - b;  if (d < -len/2) d += len;  else if (d > len/2) d -= len;
//
// Note the asymmetry the compare order gives it -- the first test is `<`
// against -len/2 and the second `<` against +len/2, so d == -len/2 falls
// through to the second test and comes back unchanged.
float trackpath_compare_distances(const TrackPathManager *m, float a,
                                  float b);

// 0x001f5c90. Everything zero but PathDirection.x, which is 1.0.
void trackpath_coord_init(TrackPathCoordinate *c);

// 0x001f5dd0 -> 0x001f5620, the declared hole. Sets Position, and sets
// DistanceAroundTrack only when the seam below is filled in.
void trackpath_coord_update_position(TrackPathCoordinate *c,
                                     const bVector2 *pos);

// The test seam. NULL on the handheld; tools/trackroute_check.py points it
// at a closed form so the transcript has non-zero distances to reason about.
typedef float (*TrackPathDistanceFn)(const bVector2 *pos);
extern TrackPathDistanceFn gTrackPathDistanceFn;

#endif
