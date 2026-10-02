// Host harness for 3DS Files/source/racecore.c: Race's constructor and
// destructor, its boundaries and GetLapNumberExact, RacingCar's
// constructor and the TimeAroundTrackTable. Runs the op script
// tools/racecore_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// racecore.c is the port source under test, with race.c (pCurrentRace and
// TheRaceParameters' fields), trackroute.c (TrackRoutePoint::GetPosition),
// trackpath.c (the TrackPathCoordinate and ComparePercentDistances) and
// bmem.c under it. The harness owns the rest: the position markers, the
// track path's distance (trackpath.c's test seam, over a track one unit
// long, so the ratio is the distance), bFree's hook and the WorldObject
// seam. Each prints its arguments in the model's words.
//
// The track path answers from mix(), a hash of the position that both
// sides compute the same way.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "race.h"
#include "racecore.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "worldobject.h"

#define NROUTE 4
#define NMARK 8
#define NGHOST 4
#define NWOBJ 2
#define PATTERN 0xa5

// What racecore.c reaches outside the sources linked with it.
void (*gWorldObjectDeleteFn)(WorldObject *o);

static const char *const markerNames[NMARK] = {
    "ForwardStartLine", "BackwardStartLine", "ForwardFinishLine",
    "BackwardFinishLine", "SplitTimeBoundary1", "SplitTimeBoundary2",
    "SplitTimeBoundary3", "Nowhere",
};

static _Alignas(16) unsigned char raceMem[sizeof(Race)];
static Race *R = (Race *)(void *)raceMem;
static TimeAroundTrackTable tatt;
static TrackRoute routes[NROUTE];
static TrackPositionMarker markers[NMARK];
static int markerOn[NMARK];
static _Alignas(16) unsigned char ghosts[NGHOST][64];
static WorldObject wobjs[NWOBJ];
static bVector2 posBuf;
static uint32_t seed;
static int umode;

// ------------------------------------------------------------- the names

static const char *nm(const void *p)
{
    static char b16[16][16];
    static int slot;
    char *b = b16[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (p == R)
        return "R";
    if (p == &tatt)
        return "T";
    for (i = 0; i < NGHOST; i++) {
        if (p == ghosts[i]) {
            sprintf(b, "g%d", i);
            return b;
        }
    }
    for (i = 0; i < NWOBJ; i++) {
        if (p == &wobjs[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
    }
    for (i = 0; i < RACE_MAX_RACING_CARS; i++) {
        if (p == &R->RacingCarTable[i]) {
            sprintf(b, "rc%d", i);
            return b;
        }
    }
    for (i = 0; i < NMARK; i++) {
        if (p == &markers[i]) {
            sprintf(b, "m%d", i);
            return b;
        }
    }
    return "?";
}

// The pointers a "G" op can name: null, g0..g3, o0..o1, rc0, T.
static void *named(int k)
{
    if (k < 0)
        return NULL;
    if (k < NGHOST)
        return ghosts[k];
    if (k < NGHOST + NWOBJ)
        return &wobjs[k - NGHOST];
    if (k == NGHOST + NWOBJ)
        return &R->RacingCarTable[0];
    return &tatt;
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *fx(float f)
{
    static char b16[32][12];
    static int slot;
    char *b = b16[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// A word from three, and a float in 2^-7 .. 2^9 of either sign from it.
static uint32_t mixw(uint32_t a, uint32_t b, uint32_t salt)
{
    uint32_t h = a * 0x9e3779b1u + b * 0x85ebca77u + salt * 0xc2b2ae3du
               + seed * 0x27d4eb2fu;

    return h ^ (h >> 15);
}

static float mixf(uint32_t a, uint32_t b, uint32_t salt)
{
    uint32_t h = mixw(a, b, salt);

    return from_bits((h & 0x807fffffu) | ((120u + ((h >> 23) & 15u)) << 23));
}

// ------------------------------------------------------------ the stubs

static void free_hook(void *p)
{
    printf("  delete %s\n", nm(p));
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    fprintf(stderr, "unexpected bMalloc %d %s %d %d\n", size, name, flags,
            pool);
    exit(3);
}

static void wobj_delete(WorldObject *o)
{
    printf("  wodel %s 3\n", nm(o));
}

// trackpath.c's seam: Position and DistanceAroundTrack from here, the ratio
// that over TrackLength, which is 1. With umode 1 the distance is in [0, 1),
// in steps of 2^-24, as a real track's would be.
static float path_distance(const bVector2 *pos)
{
    float r;

    if (umode)
        r = (float)(mixw(bits(pos->x), bits(pos->y), 3) & 0xffffffu)
          * (1.0f / 16777216.0f);
    else
        r = mixf(bits(pos->x), bits(pos->y), 3);

    printf("  upd %s %s -> %s\n", fx(pos->x), fx(pos->y), fx(r));
    return r;
}

TrackPositionMarker *track_get_position_marker_named(const char *name, int i)
{
    TrackPositionMarker *m = NULL;
    int k;

    for (k = 0; k < NMARK; k++)
        if (markerOn[k] && i == 0 && strcmp(name, markerNames[k]) == 0)
            m = &markers[k];
    printf("  marker %s %d -> %s\n", name, i, nm(m));
    return m;
}

// ------------------------------------------------------------- the dumps

static void dump_race(void)
{
    const Race *r = R;
    int i, k;

    printf("  race st %d go %ld cd %ld t %08lx %08lx %08lx n %d fin %d one %d"
           " laps %d force %d %d\n",
           (int)r->RaceStage, (long)r->StartGoTimeFrames,
           (long)r->StartCountdownTimeFrames,
           (unsigned long)r->StartTime.PackedTime,
           (unsigned long)r->RaceTime.PackedTime,
           (unsigned long)r->BestLapTime.PackedTime, (int)r->NumRacingCars,
           (int)r->NumRacingCarsFinished, (int)r->DetectedOneCarRemaining,
           (int)r->NumLapsInRace, (int)r->ForceRaceFinishPosition,
           (int)r->ForceRaceFinishPlayerNum);
    printf("  bound n %d s %d f %d d %s %s %s %s %s\n", (int)r->NumBoundaries,
           (int)r->StartLineBoundaryNumber, (int)r->FinishLineBoundaryNumber,
           fx(r->BoundaryDistances[0]), fx(r->BoundaryDistances[1]),
           fx(r->BoundaryDistances[2]), fx(r->BoundaryDistances[3]),
           fx(r->BoundaryDistances[4]));
    printf("  lines %s %s %s %s\n", fx(r->StartLinePosition.x),
           fx(r->StartLinePosition.y), fx(r->FinishLinePosition.x),
           fx(r->FinishLinePosition.y));
    printf("  ghost %s %s %s %s tatt %s cur %s\n",
           nm(r->pReplayingGhostCarData), nm(r->pReplayingGhostCarWorldObject),
           nm(r->pCapturingGhostCar), nm(r->pCapturingGhostCarData),
           nm(r->pTimeAroundTrackTable), nm(pCurrentRace));
    printf("  name");
    for (i = 0; i < 40; i++)
        printf("%02x", (unsigned)(unsigned char)r->GhostCarDataFilename[i]);
    printf("\n  cars");
    for (i = 0; i < RACE_MAX_RACING_CARS; i++)
        printf(" %s", nm(r->pRacingCars[i]));
    printf("\n");
    for (i = 0; i < RACE_MAX_RACING_CARS; i++) {
        const struct RacingCar *c = &r->RacingCarTable[i];
        const Timer *t[] = {
            c->BoundaryCrossingTimes, c->RunningTimes, c->PreviousRunningTimes,
            c->BestRunningTimes, c->PreviousBestRunningTimes,
        };

        printf("  rc%d %s %d %d %d %d %d %d %d %d %d %d %d %d %s %s %s %s\n",
               i, nm(c->pCar), c->CurrentBoundaryRegion,
               c->HighestBoundaryRegion, c->CurrentLapNumber,
               c->NumLapsCompleted, c->RacePosition, c->PreviousRacePosition,
               c->FinishingOrder, c->CrossedFinishLine, c->CompletedNewLap,
               c->CrossedNewBoundary, c->NumLapsLed, c->FinishReason,
               fx(c->CurrentLapNumberExact), fx(c->dCurrentLapNumberExact),
               fx(c->PreviousDistanceAroundTrack),
               fx(c->FinishedLapNumberExact));
        printf("  rc%d t", i);
        for (k = 0; k < 25; k++)
            printf(" %lx", (unsigned long)t[k / 5][k % 5].PackedTime);
        printf(" |");
        for (k = 0; k < 11; k++)
            printf(" %lx", (unsigned long)c->LapTimes[k].PackedTime);
        printf(" | %lx %s %s\n", (unsigned long)c->RaceTime.PackedTime,
               fx(c->TopSpeed), fx(c->AverageSpeed));
    }
}

static void dump_tatt(void)
{
    int i, k;

    printf("  tatt total %s\n", fx(tatt.TotalTimeAroundTrack));
    for (i = 0; i < TATT_ENTRIES; i += 8) {
        printf("  t%03d", i);
        for (k = i; k < i + 8; k++)
            printf(" %s:%s", fx(tatt.EntryTable[k].Rate),
                   fx(tatt.EntryTable[k].Time));
        printf("\n");
    }
}

// ------------------------------------------------------------ the state

static void reset(void)
{
    int i;

    memset(raceMem, PATTERN, sizeof raceMem);
    memset(&tatt, PATTERN, sizeof tatt);
    for (i = 0; i < NROUTE; i++)
        memset(&routes[i], 0, offsetof(TrackRoute, TrackRoutePointTable));
    memset(&TheTrackRouteManager, 0, sizeof TheTrackRouteManager);
    memset(markers, 0, sizeof markers);
    memset(markerOn, 0, sizeof markerOn);
    memset(&posBuf, PATTERN, sizeof posBuf);
    RaceParametersTrackDirection = TRACK_DIRECTION_FORWARD;
    RaceParametersPoint2Point = 0;
    RaceParametersNumLapsInRace = 2;
    pCurrentRace = NULL;
    seed = 0;
    umode = 0;
}

static void set_global(const char *f, long v)
{
    if (strcmp(f, "dir") == 0)
        RaceParametersTrackDirection = (eTrackDirection)v;
    else if (strcmp(f, "p2p") == 0)
        RaceParametersPoint2Point = (int32_t)v;
    else if (strcmp(f, "laps") == 0)
        RaceParametersNumLapsInRace = (int32_t)v;
    else if (strcmp(f, "seed") == 0)
        seed = (uint32_t)v;
    else if (strcmp(f, "umode") == 0)
        umode = (int)v;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static void point_line(int r, int k, const long *n)
{
    TrackRoutePoint *p = &routes[r].TrackRoutePointTable[k];
    int l;

    p->Position.x = from_bits((uint32_t)n[0]);
    p->Position.y = from_bits((uint32_t)n[1]);
    p->Direction.x = from_bits((uint32_t)n[2]);
    p->Direction.y = from_bits((uint32_t)n[3]);
    for (l = 0; l < TRP_NUM_DRIVING_LINES; l++) {
        p->DrivingLineOffsets[l] = (int16_t)(uint16_t)(n[4] + 37 * l);
        p->DrivingLineSpeeds[l] = (uint8_t)(n[5] + 13 * l);
    }
}

// ------------------------------------------------------------- the ops

static void op(char *line)
{
    char *tok[16];
    long n[16];
    int nt = 0, i;
    char *s;

    for (s = strtok(line, " \t\r\n"); s && nt < 16; s = strtok(NULL, " \t\r\n"))
        tok[nt++] = s;
    if (nt == 0)
        return;
    for (i = 1; i < nt; i++)
        n[i - 1] = strtol(tok[i], NULL, 0);

    if (strcmp(tok[0], "S") == 0) {
        set_global(tok[1], strtol(tok[2], NULL, 0));
    } else if (strcmp(tok[0], "M") == 0) {
        markerOn[n[0]] = 1;
        markers[n[0]].Position.x = from_bits((uint32_t)n[1]);
        markers[n[0]].Position.y = from_bits((uint32_t)n[2]);
    } else if (strcmp(tok[0], "X") == 0) {
        markerOn[n[0]] = 0;
    } else if (strcmp(tok[0], "N") == 0) {
        memset(raceMem, PATTERN, sizeof raceMem);
        printf("  -> %s\n", nm(race_construct(R)));
        dump_race();
    } else if (strcmp(tok[0], "F") == 0) {
        race_figure_out_boundaries(R);
        dump_race();
    } else if (strcmp(tok[0], "SN") == 0) {
        R->NumBoundaries = (int16_t)n[0];
    } else if (strcmp(tok[0], "SB") == 0) {
        R->BoundaryDistances[n[0]] = from_bits((uint32_t)n[1]);
    } else if (strcmp(tok[0], "SF") == 0) {
        R->FinishLineBoundaryNumber = (int8_t)n[0];
    } else if (strcmp(tok[0], "A") == 0) {
        int32_t k = race_add_boundary_position(R, markerNames[n[0]], &posBuf,
                                               from_bits((uint32_t)n[1]));

        printf("  -> %d %s %s\n", (int)k, fx(posBuf.x), fx(posBuf.y));
        dump_race();
    } else if (strcmp(tok[0], "L") == 0) {
        printf("  -> %s\n",
               fx(race_get_lap_number_exact(R, from_bits((uint32_t)n[0]))));
    } else if (strcmp(tok[0], "G") == 0) {
        R->pReplayingGhostCarData = named((int)n[0]);
        R->pReplayingGhostCarWorldObject = named((int)n[1]);
        R->pCapturingGhostCar = named((int)n[2]);
        R->pCapturingGhostCarData = named((int)n[3]);
        R->pTimeAroundTrackTable = named((int)n[4]);
    } else if (strcmp(tok[0], "D") == 0) {
        race_destroy(R, (int32_t)n[0]);
        printf("  cur %s\n", nm(pCurrentRace));
    } else if (strcmp(tok[0], "C") == 0) {
        pCurrentRace = R;
    } else if (strcmp(tok[0], "SG") == 0) {
        race_setup_ghost_cars(R);
        dump_race();
    } else if (strcmp(tok[0], "P") == 0) {
        routes[n[0]].NumPoints = (int32_t)n[1];
    } else if (strcmp(tok[0], "PL") == 0) {
        routes[n[0]].DrivingLineInfoTable[n[1]].Flags = (uint32_t)n[2];
    } else if (strcmp(tok[0], "PT") == 0) {
        point_line((int)n[0], (int)n[1], &n[2]);
    } else if (strcmp(tok[0], "Q") == 0) {
        TheTrackRouteManager.NumRacing = nt - 1;
        for (i = 0; i < nt - 1; i++)
            TheTrackRouteManager.Racing[i] = &routes[n[i]];
    } else if (strcmp(tok[0], "T") == 0) {
        memset(&tatt, PATTERN, sizeof tatt);
        printf("  -> %s\n", nm(tatt_construct(&tatt, (int32_t)n[0])));
        dump_tatt();
    } else if (strcmp(tok[0], "E") == 0 || strcmp(tok[0], "E0") == 0) {
        float t = from_bits(0xa5a5a5a5u);
        TimeTableEntry *e = tatt_get_time_table_entry(
            &tatt, from_bits((uint32_t)n[0]), tok[0][1] ? NULL : &t);

        printf("  -> %ld %s\n", (long)(e - tatt.EntryTable), fx(t));
    } else if (strcmp(tok[0], "TA") == 0) {
        printf("  -> %s\n",
               fx(tatt_get_time_around_track(&tatt,
                                             from_bits((uint32_t)n[0]))));
    } else if (strcmp(tok[0], "TD") == 0) {
        tatt_destroy(&tatt, (int32_t)n[0]);
        printf("  done\n");
    } else {
        fprintf(stderr, "bad op %s\n", tok[0]);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: racecore_test SCRIPT\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    bSetMemoryHooks(malloc_hook, free_hook);
    gWorldObjectDeleteFn = wobj_delete;
    gTrackPathDistanceFn = path_distance;
    TheTrackPathManager.TrackLength = 1.0f;

    while (fgets(line, sizeof line, f)) {
        size_t len = strcspn(line, "\r\n");

        line[len] = 0;
        if (len == 0)
            continue;
        if (line[0] == 'B' && line[1] == ' ') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.40s\n", line);
        op(line);
    }
    fclose(f);
    return 0;
}
