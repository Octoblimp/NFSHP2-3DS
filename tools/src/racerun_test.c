// Host harness for 3DS Files/source/racerun.c: Race::Init, the racing cars
// it adds, sorts and stages, the lap counting under them, and timer.c's
// Timer::Round. Runs the op script tools/racerun_check.py writes and prints
// the transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// racerun.c and timer.c are the port sources under test, with racecore.c
// (GetLapNumberExact and the TimeAroundTrackTable), race.c, trackpath.c
// (ComparePercentDistances and the coordinate), trackroute.c, vtable.c and
// bmem.c under them. The harness owns the rest: the World and its Cars,
// their CarTypeInfos and drivers, the ReplayManager, the clock, bMalloc's
// hook, Car::SetMovementMode, RealDriver::DisableStartLineState, the race
// event's seam, the track path's distance (trackpath.c's test seam) and the
// drivers' GetDesiredSpeed, installed in a vtable at a made-up address.
// Each prints its arguments in the model's words.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "race.h"
#include "racecore.h"
#include "racerun.h"
#include "realdriver.h"
#include "realtime.h"
#include "replay.h"
#include "timer.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

#define NCAR 12
#define NROUTE 2
#define PATTERN 0xa5
#define VTAB_IMAGE 0x01002400u

// What racerun.c and racecore.c reach outside the sources linked with them.
World         *pCurrentWorld;
ReplayManager *pReplayManager;
int32_t        WorldTimer;
int32_t        WorldTimeFrames;
float          WorldTimeElapsed;
void         (*gWorldObjectDeleteFn)(WorldObject *o);

static _Alignas(16) unsigned char raceMem[sizeof(Race)];
static Race *R = (Race *)(void *)raceMem;
static TimeAroundTrackTable tatt;
static World world;
static ReplayManager replay;
static Car cars[NCAR];
static CarTypeInfo ctis[NCAR];
static RealDriver drv[NCAR];
static unsigned char players[NCAR][16];
static float want[NCAR];
static int delta;
static TrackRoute routes[NROUTE];
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
    for (i = 0; i < RACE_MAX_RACING_CARS; i++) {
        if (p == &R->RacingCarTable[i]) {
            sprintf(b, "rc%d", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (p == &drv[i]) {
            sprintf(b, "d%d", i);
            return b;
        }
        if (p == players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
    }
    return "?";
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

// racecore_check's hash: a word from three, and a float in 2^-7 .. 2^9 of
// either sign from it.
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
    printf("  free %s\n", nm(p));
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    printf("  malloc %d %s %d %d\n", size, name, flags, pool);
    return &tatt;
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  move %s %d\n", nm(c), (int)mode);
}

void realdriver_disable_start_line_state(RealDriver *d)
{
    printf("  dsls %s\n", nm(d));
}

static void race_is_leaving(Race *r)
{
    printf("  leaving fdb %s\n", nm(r));
}

static float desired_speed(void *self)
{
    const char *who = "?";
    float w = 0.0f;
    char b[16];
    int i;

    for (i = 0; i < NCAR; i++) {
        if ((char *)self - (char *)&drv[i] == delta) {
            sprintf(b, "d%d", i);
            who = b;
            w = want[i];
        }
    }
    printf("  want %s -> %s\n", who, fx(w));
    return w;
}

// vt_install keeps the pointer, so the table is static.
static void set_vtable(void)
{
    static VtEntry e[CARDRIVER_VT_ENTRIES];

    memset(e, 0, sizeof e);
    e[VT_SLOT(CARDRIVER_VT_GET_DESIRED_SPEED)].delta = (int16_t)delta;
    e[VT_SLOT(CARDRIVER_VT_GET_DESIRED_SPEED)].fn = (VtFn)desired_speed;
    vt_install(VTAB_IMAGE, e, CARDRIVER_VT_ENTRIES);
}

// trackpath.c's seam: Position and DistanceAroundTrack from here, the ratio
// that over TrackLength. With umode 1 the distance is in [0, 1), in steps
// of 2^-24.
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
    fprintf(stderr, "unexpected marker %s %d\n", name, i);
    exit(3);
}

// ------------------------------------------------------------- the dumps

static void dump_head(void)
{
    const Race *r = R;
    int i;

    printf("  race st %d go %ld cd %ld t %08lx n %d tatt %s\n",
           (int)r->RaceStage, (long)r->StartGoTimeFrames,
           (long)r->StartCountdownTimeFrames,
           (unsigned long)r->StartTime.PackedTime, (int)r->NumRacingCars,
           nm(r->pTimeAroundTrackTable));
    printf("  cars");
    for (i = 0; i < RACE_MAX_RACING_CARS; i++)
        printf(" %s", nm(r->pRacingCars[i]));
    printf("\n");
}

static void dump_rc(int i)
{
    const struct RacingCar *c = &R->RacingCarTable[i];
    const Timer *t[] = {
        c->BoundaryCrossingTimes, c->RunningTimes, c->PreviousRunningTimes,
        c->BestRunningTimes, c->PreviousBestRunningTimes,
    };
    int k;

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

static void dump_cars(void)
{
    int i;

    for (i = 0; i < NCAR; i++) {
        const CarDriver *d = &drv[i].Base;

        printf("  c%d rc %s rend %d thr %s brk %s eb %s sls %ld\n", i,
               nm(cars[i].pRacingCar), (int)cars[i].RenderingEnabled,
               fx(d->Throttle), fx(d->Brake), fx(d->EBrake),
               (long)drv[i].StartLineState);
    }
}

static void dump_race(void)
{
    int k;

    dump_head();
    for (k = 0; k < RACE_MAX_RACING_CARS; k++)
        dump_rc(k);
    dump_cars();
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
    R->NumRacingCars = 0;
    R->NumBoundaries = 0;
    R->StartLineBoundaryNumber = 0;
    R->FinishLineBoundaryNumber = 0;
    for (i = 0; i < RACE_MAX_BOUNDARIES; i++)
        R->BoundaryDistances[i] = 0.0f;
    memset(&tatt, PATTERN, sizeof tatt);
    memset(&world, 0, sizeof world);
    for (i = 0; i < NCAR; i++)
        world.CarTable[i] = &cars[i];
    memset(&replay, 0, sizeof replay);
    pCurrentRace = R;
    pCurrentWorld = &world;
    pReplayManager = &replay;
    WorldTimer = 0;
    WorldTimeFrames = 0;
    WorldTimeElapsed = 0.0f;
    RaceParametersRaceType = 0;
    RaceParametersPoint2Point = 0;
    RaceParametersNumPlayerCars = 1;
    RaceParametersBeACop = 0;
    TheTrackPathManager.TrackLength = 1.0f;
    delta = 0;
    set_vtable();
    for (i = 0; i < NCAR; i++) {
        Car *c = &cars[i];

        memset(c, PATTERN, sizeof *c);
        memset(&ctis[i], PATTERN, sizeof ctis[i]);
        memset(&drv[i], PATTERN, sizeof drv[i]);
        c->pCarTypeInfo = &ctis[i];
        c->pCarDriver = &drv[i].Base;
        c->pPlayer = NULL;
        c->TheControlMode = (ControlMode)0;
        c->RenderingEnabled = 0;
        c->State.nWheelsTouchingGround = 0;
        c->State.ForwardSpeed = 0.0f;
        c->State.DistanceMoved = 0.0f;
        c->TheTrackPathCoordinate.RatioAroundTrack = 0.0f;
        c->State.BoostFactor = 1.0f;
        ctis[i].CarClass = 0;
        ctis[i].Control.SpeedLimiter = 0.0f;
        drv[i].Base._vtable = VTAB_IMAGE;
        drv[i].Base.Throttle = 0.0f;
        drv[i].Base.Brake = 0.0f;
        drv[i].Base.EBrake = 0.0f;
        drv[i].StartLineState = 0;
        want[i] = 0.0f;
    }
    for (i = 0; i < NROUTE; i++)
        memset(&routes[i], 0, offsetof(TrackRoute, TrackRoutePointTable));
    memset(&TheTrackRouteManager, 0, sizeof TheTrackRouteManager);
    seed = 0;
    umode = 1;
}

static void set_global(const char *f, long v)
{
    if (strcmp(f, "timer") == 0)
        WorldTimer = (int32_t)v;
    else if (strcmp(f, "frames") == 0)
        WorldTimeFrames = (int32_t)v;
    else if (strcmp(f, "elapsed") == 0)
        WorldTimeElapsed = from_bits((uint32_t)v);
    else if (strcmp(f, "replay") == 0)
        replay.ReplayingFlag = (int32_t)v;
    else if (strcmp(f, "rtype") == 0)
        RaceParametersRaceType = (int32_t)v;
    else if (strcmp(f, "p2p") == 0)
        RaceParametersPoint2Point = (int32_t)v;
    else if (strcmp(f, "npc") == 0)
        RaceParametersNumPlayerCars = (int32_t)v;
    else if (strcmp(f, "cop") == 0)
        RaceParametersBeACop = (int32_t)v;
    else if (strcmp(f, "len") == 0)
        TheTrackPathManager.TrackLength = from_bits((uint32_t)v);
    else if (strcmp(f, "delta") == 0) {
        delta = (int)v;
        set_vtable();
    } else if (strcmp(f, "seed") == 0)
        seed = (uint32_t)v;
    else if (strcmp(f, "umode") == 0)
        umode = (int)v;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static void set_race(const char *f, long v)
{
    if (strcmp(f, "n") == 0)
        R->NumRacingCars = (int32_t)v;
    else if (strcmp(f, "nb") == 0)
        R->NumBoundaries = (int16_t)v;
    else if (strcmp(f, "fin") == 0)
        R->FinishLineBoundaryNumber = (int8_t)v;
    else if (strncmp(f, "bd", 2) == 0)
        R->BoundaryDistances[f[2] - '0'] = from_bits((uint32_t)v);
    else if (strcmp(f, "rt") == 0)
        R->RaceTime.PackedTime = (uint32_t)v;
    else if (strcmp(f, "st") == 0)
        R->RaceStage = (eRaceStage)v;
    else {
        fprintf(stderr, "bad race field %s\n", f);
        exit(2);
    }
}

static void set_rc(int k, const char *f, long v)
{
    struct RacingCar *c = &R->RacingCarTable[k];

    if (strcmp(f, "fo") == 0)
        c->FinishingOrder = (int8_t)v;
    else if (strcmp(f, "fle") == 0)
        c->FinishedLapNumberExact = from_bits((uint32_t)v);
    else if (strcmp(f, "pos") == 0)
        c->RacePosition = (int8_t)v;
    else if (strcmp(f, "lap") == 0)
        c->CurrentLapNumber = (int8_t)v;
    else if (strcmp(f, "done") == 0)
        c->NumLapsCompleted = (int8_t)v;
    else if (strcmp(f, "cur") == 0)
        c->CurrentBoundaryRegion = (int16_t)v;
    else if (strcmp(f, "high") == 0)
        c->HighestBoundaryRegion = (int16_t)v;
    else if (strcmp(f, "prev") == 0)
        c->PreviousDistanceAroundTrack = from_bits((uint32_t)v);
    else if (strcmp(f, "cle") == 0)
        c->CurrentLapNumberExact = from_bits((uint32_t)v);
    else if (strcmp(f, "dcle") == 0)
        c->dCurrentLapNumberExact = from_bits((uint32_t)v);
    else if (strcmp(f, "bct0") == 0)
        c->BoundaryCrossingTimes[0].PackedTime = (uint32_t)v;
    else if (strcmp(f, "top") == 0)
        c->TopSpeed = from_bits((uint32_t)v);
    else {
        fprintf(stderr, "bad racing car field %s\n", f);
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
    } else if (strcmp(tok[0], "RS") == 0) {
        set_race(tok[1], strtol(tok[2], NULL, 0));
    } else if (strcmp(tok[0], "RF") == 0) {
        set_rc((int)n[0], tok[2], strtol(tok[3], NULL, 0));
    } else if (strcmp(tok[0], "W") == 0) {
        world.TotalNumCars = (int32_t)n[0];
        world.AICarPos = (int32_t)n[1];
        world.CopCarPos = (int32_t)n[2];
        world.TrafficCarPos = (int32_t)n[3];
    } else if (strcmp(tok[0], "WT") == 0) {
        world.CarTable[n[0]] = &cars[n[1]];
    } else if (strcmp(tok[0], "CA") == 0) {
        Car *c = &cars[n[0]];

        c->TheControlMode = (ControlMode)n[1];
        c->pPlayer = n[2] ? (Player *)(void *)players[n[0]] : NULL;
        ctis[n[0]].CarClass = (int8_t)n[3];
        c->RenderingEnabled = (int8_t)n[4];
    } else if (strcmp(tok[0], "CF") == 0) {
        Car *c = &cars[n[0]];

        c->State.nWheelsTouchingGround = (int32_t)n[1];
        c->State.ForwardSpeed = from_bits((uint32_t)n[2]);
        c->State.BoostFactor = from_bits((uint32_t)n[3]);
        c->State.DistanceMoved = from_bits((uint32_t)n[4]);
        c->TheTrackPathCoordinate.RatioAroundTrack = from_bits((uint32_t)n[5]);
        ctis[n[0]].Control.SpeedLimiter = from_bits((uint32_t)n[6]);
    } else if (strcmp(tok[0], "CR") == 0) {
        cars[n[0]].TheTrackPathCoordinate.RatioAroundTrack =
            from_bits((uint32_t)n[1]);
    } else if (strcmp(tok[0], "DV") == 0) {
        CarDriver *d = &drv[n[0]].Base;

        d->Throttle = from_bits((uint32_t)n[1]);
        d->Brake = from_bits((uint32_t)n[2]);
        d->EBrake = from_bits((uint32_t)n[3]);
        drv[n[0]].StartLineState = (int32_t)n[4];
        want[n[0]] = from_bits((uint32_t)n[5]);
    } else if (strcmp(tok[0], "RP") == 0) {
        R->pRacingCars[n[0]] = &R->RacingCarTable[n[1]];
    } else if (strcmp(tok[0], "RI") == 0) {
        racingcar_init(&R->RacingCarTable[n[0]], &cars[n[1]]);
        dump_rc((int)n[0]);
        printf("  c%ld rc %s\n", n[1], nm(cars[n[1]].pRacingCar));
    } else if (strcmp(tok[0], "F") == 0) {
        racingcar_fake_startline_crossing(&R->RacingCarTable[n[0]]);
        dump_rc((int)n[0]);
    } else if (strcmp(tok[0], "K") == 0) {
        BoundaryCrossingInfo info;
        int32_t v;

        memset(&info, PATTERN, sizeof info);
        v = racingcar_check_boundary_crossing(&R->RacingCarTable[n[0]], &info,
                                              from_bits((uint32_t)n[1]),
                                              from_bits((uint32_t)n[2]));
        printf("  -> %ld %ld %ld %lx\n", (long)v, (long)info.CrossedForwards,
               (long)info.CrossedBackwards,
               (unsigned long)info.TimeSinceCrossing.PackedTime);
    } else if (strcmp(tok[0], "U") == 0) {
        racingcar_update_lap_counts(&R->RacingCarTable[n[0]]);
        dump_rc((int)n[0]);
    } else if (strcmp(tok[0], "P") == 0) {
        printf("  -> %s\n",
               nm(racingcar_get_player(&R->RacingCarTable[n[0]])));
    } else if (strcmp(tok[0], "I") == 0) {
        race_init(R, (eRaceStage)n[0]);
        dump_race();
        dump_tatt();
    } else if (strcmp(tok[0], "AC") == 0) {
        race_add_racing_cars(R);
        dump_race();
    } else if (strcmp(tok[0], "A") == 0) {
        race_add_racing_car(R, &cars[n[0]]);
        dump_race();
    } else if (strcmp(tok[0], "G") == 0) {
        race_set_race_stage(R, (eRaceStage)n[0]);
        dump_race();
    } else if (strcmp(tok[0], "O") == 0) {
        race_sort_racing_cars_by_leadership(R);
        dump_head();
        for (i = 0; i < RACE_MAX_RACING_CARS; i++)
            dump_rc(i);
    } else if (strcmp(tok[0], "TR") == 0) {
        Timer t;

        t.PackedTime = (uint32_t)strtoul(tok[1], NULL, 0);
        timer_round(&t, from_bits((uint32_t)n[1]));
        printf("  -> %08lx\n", (unsigned long)t.PackedTime);
    } else if (strcmp(tok[0], "TS") == 0) {
        Timer t;

        t.PackedTime = (uint32_t)strtoul(tok[1], NULL, 0);
        printf("  -> %s\n",
               fx(timer_round_seconds(&t, from_bits((uint32_t)n[1]))));
    } else if (strcmp(tok[0], "RTP") == 0) {
        routes[n[0]].NumPoints = (int32_t)n[1];
    } else if (strcmp(tok[0], "RTL") == 0) {
        routes[n[0]].DrivingLineInfoTable[n[1]].Flags = (uint32_t)n[2];
    } else if (strcmp(tok[0], "RTT") == 0) {
        point_line((int)n[0], (int)n[1], &n[2]);
    } else if (strcmp(tok[0], "RTQ") == 0) {
        TheTrackRouteManager.NumRacing = nt - 1;
        for (i = 0; i < nt - 1; i++)
            TheTrackRouteManager.Racing[i] = &routes[n[i]];
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
        fprintf(stderr, "usage: racerun_test SCRIPT\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    bSetMemoryHooks(malloc_hook, free_hook);
    gTrackPathDistanceFn = path_distance;
    gRaceIsLeavingFn = race_is_leaving;

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
