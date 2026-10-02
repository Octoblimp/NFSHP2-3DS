// racecore -- see racecore.h.

#include "racecore.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "eefpu.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "worldobject.h"

// FigureOutBoundaries' marker names, at 0x002af498 .. 0x002af528.
#define FORWARD_START_LINE    "ForwardStartLine"
#define BACKWARD_START_LINE   "BackwardStartLine"
#define FORWARD_FINISH_LINE   "ForwardFinishLine"
#define BACKWARD_FINISH_LINE  "BackwardFinishLine"
#define SPLIT_TIME_BOUNDARY_1 "SplitTimeBoundary1"
#define SPLIT_TIME_BOUNDARY_2 "SplitTimeBoundary2"
#define SPLIT_TIME_BOUNDARY_3 "SplitTimeBoundary3"

// Boundary `i`, read and written as the image does: the number shifted
// and added to BoundaryDistances, unchecked. A number of -1 -- a finish
// line with no marker and nowhere to go -- reads the four bytes before the
// array, NumBoundaries and the two numbers, as a float; a sixth boundary
// would land on StartLinePosition. So these go through the Race's bytes
// rather than index the array.
static float boundary_at(const Race *r, int i)
{
    float f;

    memcpy(&f, (const unsigned char *)r + offsetof(Race, BoundaryDistances)
                   + 4 * i, sizeof f);
    return f;
}

static void boundary_set(Race *r, int i, float f)
{
    memcpy((unsigned char *)r + offsetof(Race, BoundaryDistances) + 4 * i, &f,
           sizeof f);
}

// ------------------------------------------------------ TimeAroundTrackTable

// A driving line's lateral offset, Q8 in a halfword: `lh; sll 8; cvt.s.w`
// and a multiply by 2^-16.
static float line_offset(const TrackRoutePoint *p, int line)
{
    return (float)((int32_t)p->DrivingLineOffsets[line] * 256)
           * (1.0f / 65536.0f);
}

// A driving line's speed, a whole number in a byte: `lbu; sll 16;
// cvt.s.w` and the same multiply.
static float line_speed(const TrackRoutePoint *p, int line)
{
    return (float)((int32_t)p->DrivingLineSpeeds[line] << 16)
           * (1.0f / 65536.0f);
}

TimeAroundTrackTable *tatt_construct(TimeAroundTrackTable *t,
                                     int32_t car_class)
{
    TrackRouteManager *m = &TheTrackRouteManager;
    int   line = car_class * 2;
    float time, prev;
    int   i, k;

    memset(t->EntryTable, 0, sizeof t->EntryTable);
    t->TotalTimeAroundTrack = 0.0f;

    for (i = 0; i < m->NumRacing; i++) {
        TrackRoute *r = m->Racing[i];
        uint32_t flags = r->DrivingLineInfoTable[line].Flags;
        TrackPathCoordinate c;

        if (!(flags & DLI_IS_VALID) && !(flags & DLI_IS_FAKE))
            continue;
        trackpath_coord_init(&c);
        for (k = 0; k < r->NumPoints - 1; k++) {
            TrackRoutePoint *p0 = &r->TrackRoutePointTable[k];
            TrackRoutePoint *p1 = &r->TrackRoutePointTable[k + 1];
            TimeTableEntry *e;
            bVector2 a, b;
            float lap0, lap1, dlap, dx, dy, dist, rate;

            trpoint_get_position2(p0, &a, 0.0f, line_offset(p0, line));
            trpoint_get_position2(p1, &b, 0.0f, line_offset(p1, line));
            trackpath_coord_update_position(&c, &a);
            lap0 = race_get_lap_number_exact(pCurrentRace,
                                             c.RatioAroundTrack * 100.0f);
            trackpath_coord_update_position(&c, &b);
            lap1 = race_get_lap_number_exact(pCurrentRace,
                                             c.RatioAroundTrack * 100.0f);

            // Across the line one of the two has wrapped.
            dlap = lap1 - lap0;
            if (0.5f < dlap) {
                lap0 += 1.0f;
                dlap = lap1 - lap0;
            } else if (0.5f < lap0 - lap1) {
                lap1 += 1.0f;
                dlap = lap1 - lap0;
            }

            dx = a.x - b.x;
            dy = a.y - b.y;
            dist = sqrtf(dx * dx + dy * dy);
            rate = dlap / (dist / line_speed(p0, line));
            e = tatt_get_time_table_entry(t, lap0, NULL);
            if (0.0f < rate && e->Rate == 0.0f)
                e->Rate = rate;
        }
    }

    // gp-31484: a lap in three minutes where nothing says otherwise.
    time = 0.0f;
    prev = 1.0f / 180.0f;
    for (k = 0; k < TATT_ENTRIES; k++) {
        TimeTableEntry *e = &t->EntryTable[k];
        float rate = e->Rate;

        e->Time = time;
        if (rate == 0.0f) {
            e->Rate = prev;
            rate = prev;
        }
        time += (1.0f / 256.0f) / rate;
        prev = rate;
    }
    t->TotalTimeAroundTrack = time;
    return t;
}

void tatt_destroy(TimeAroundTrackTable *t, int32_t flags)
{
    if (flags & 1)
        bFree(t);
}

TimeTableEntry *tatt_get_time_table_entry(TimeAroundTrackTable *t, float lap,
                                          float *time)
{
    TimeTableEntry *e;
    float whole, frac;
    int32_t slot;

    if (lap < 0.0f)
        lap = 0.0f;
    whole = (float)ee_trunc_w(lap);
    frac = lap - whole;
    slot = ee_trunc_w(frac * 256.0f);
    e = &t->EntryTable[slot];
    if (time) {
        float before = whole * t->TotalTimeAroundTrack + e->Time;
        float into = (frac - (float)slot * (1.0f / 256.0f)) / e->Rate;

        *time = before + into;
    }
    return e;
}

float tatt_get_time_around_track(TimeAroundTrackTable *t, float lap)
{
    float time;

    tatt_get_time_table_entry(t, lap, &time);
    return time;
}

// ------------------------------------------------------------- RacingCar

struct RacingCar *racingcar_construct(struct RacingCar *rc)
{
    int i;

    for (i = 0; i < 5; i++)
        rc->BoundaryCrossingTimes[i].PackedTime = 0;
    for (i = 0; i < 5; i++)
        rc->RunningTimes[i].PackedTime = 0;
    for (i = 0; i < 5; i++)
        rc->PreviousRunningTimes[i].PackedTime = 0;
    for (i = 0; i < 5; i++)
        rc->BestRunningTimes[i].PackedTime = 0;
    for (i = 0; i < 5; i++)
        rc->PreviousBestRunningTimes[i].PackedTime = 0;
    for (i = 0; i < 11; i++)
        rc->LapTimes[i].PackedTime = 0;
    rc->RaceTime.PackedTime = 0;
    return rc;
}

void racingcar_uninit(struct RacingCar *rc)
{
    (void)rc;
}

// ------------------------------------------------------------------ Race

Race *race_construct(Race *r)
{
    int i;

    r->StartTime.PackedTime = 0;
    r->RaceTime.PackedTime = 0;
    r->BestLapTime.PackedTime = 0;
    for (i = 0; i < RACE_MAX_RACING_CARS; i++)
        racingcar_construct(&r->RacingCarTable[i]);

    pCurrentRace = r;
    r->RaceStage = RACE_STAGE_NONE;
    r->NumLapsInRace = RaceParametersNumLapsInRace;
    if (RaceParametersNumLapsInRace && RaceParametersPoint2Point)
        r->NumLapsInRace = 1;

    r->ForceRaceFinishPosition = 0;
    r->ForceRaceFinishPlayerNum = 0;
    r->StartTime.PackedTime = 0;
    r->RaceTime.PackedTime = 0;
    r->NumRacingCars = 0;
    r->NumRacingCarsFinished = 0;
    r->DetectedOneCarRemaining = 0;
    r->pReplayingGhostCarWorldObject = NULL;
    r->pReplayingGhostCarData = NULL;
    r->pCapturingGhostCar = NULL;
    r->pCapturingGhostCarData = NULL;
    r->StartCountdownTimeFrames = 0;
    r->StartGoTimeFrames = 0;
    r->StartLinePosition.x = 0.0f;
    r->StartLinePosition.y = 0.0f;
    r->FinishLinePosition.x = 0.0f;
    r->FinishLinePosition.y = 0.0f;
    r->BestLapTime.PackedTime = 0x7fffffffu;
    race_figure_out_boundaries(r);
    r->pTimeAroundTrackTable = NULL;
    return r;
}

void race_destroy(Race *r, int32_t flags)
{
    int i;

    for (i = 0; i < r->NumRacingCars; i++)
        racingcar_uninit(&r->RacingCarTable[i]);

    // The WorldObject goes only with the data: the test of it is inside
    // the other's.
    if (r->pReplayingGhostCarData) {
        bFree(r->pReplayingGhostCarData);
        if (r->pReplayingGhostCarWorldObject && gWorldObjectDeleteFn)
            gWorldObjectDeleteFn(r->pReplayingGhostCarWorldObject);
    }
    if (r->pCapturingGhostCarData)
        bFree(r->pCapturingGhostCarData);
    if (r->pTimeAroundTrackTable)
        tatt_destroy(r->pTimeAroundTrackTable, 3);

    pCurrentRace = NULL;
    if (flags & 1)
        bFree(r);
}

int32_t race_add_boundary_position(Race *r, const char *name, bVector2 *pos,
                                   float dist)
{
    TrackPositionMarker *m;
    int16_t n;

    if (100.0f < dist)
        dist -= 100.0f;
    pos->x = 0.0f;
    pos->y = 0.0f;

    m = track_get_position_marker_named(name, 0);
    if (m) {
        TrackPathCoordinate c;

        trackpath_coord_init_at(&c, &m->Position);
        n = r->NumBoundaries;
        boundary_set(r, n, c.RatioAroundTrack * 100.0f);
        pos->y = m->Position.y;
        pos->x = m->Position.x;
        r->NumBoundaries = (int16_t)(n + 1);
        return (int16_t)(n + 1) - 1;
    }
    if (0.0f <= dist) {
        n = r->NumBoundaries;
        boundary_set(r, n, dist);
        r->NumBoundaries = (int16_t)(n + 1);
        return (int16_t)(n + 1) - 1;
    }
    return -1;
}

void race_figure_out_boundaries(Race *r)
{
    bVector2 pos;
    int32_t  finish = 0;

    r->NumBoundaries = 0;
    if (RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD) {
        r->StartLineBoundaryNumber =
            (int8_t)race_add_boundary_position(r, FORWARD_START_LINE, &pos,
                                               5.0f);
        r->StartLinePosition = pos;
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3, &pos, -1.0f);
        if (RaceParametersPoint2Point)
            finish = race_add_boundary_position(r, FORWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 95.0f);
    } else {
        r->StartLineBoundaryNumber =
            (int8_t)race_add_boundary_position(r, BACKWARD_START_LINE, &pos,
                                               5.0f);
        r->StartLinePosition = pos;
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_3, &pos, -1.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_2, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 33.0f);
        race_add_boundary_position(r, SPLIT_TIME_BOUNDARY_1, &pos,
            boundary_at(r, r->StartLineBoundaryNumber) + 66.0f);
        if (RaceParametersPoint2Point)
            finish = race_add_boundary_position(r, BACKWARD_FINISH_LINE, &pos,
                boundary_at(r, r->StartLineBoundaryNumber) + 95.0f);
    }

    if (RaceParametersPoint2Point) {
        r->FinishLineBoundaryNumber = (int8_t)finish;
        r->FinishLinePosition = pos;
    } else {
        r->FinishLineBoundaryNumber = r->StartLineBoundaryNumber;
        r->FinishLinePosition = r->StartLinePosition;
    }
}

float race_get_lap_number_exact(Race *r, float pct)
{
    float d = trackpath_compare_percent_distances(
        &TheTrackPathManager, pct,
        boundary_at(r, r->FinishLineBoundaryNumber));

    if (d < 0.0f)
        d += 100.0f;
    return d * 0.01f;
}

void race_setup_ghost_cars(Race *r)
{
    (void)r;
}
