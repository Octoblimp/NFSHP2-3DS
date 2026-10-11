// raceevent_test -- tools/raceevent_check.py's harness.
//
// Runs raceevent.c over the checker's script, with eventtree.c's state
// classes and raceparams.c's driver table under it, as retail's RaceEvent
// runs on its own. What the port calls outside them is a stub here that
// logs and answers as the model's stubs do: Fred::CalculateStartingPositions,
// EventTrack::SetRace (the seam), RacingCar::GetBestLapTime and
// Timer::SetTime. After each op the event, the state and the race
// parameters print as one line, when it changed.
//
//     raceevent_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "configitems.h"
#include "copmanager.h"
#include "eventtree.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "raceevent.h"
#include "raceinit.h"
#include "raceparams.h"
#include "racesplit.h"
#include "timer.h"

#define NCARS 4
#define FRED_STATE_SPAN 2048

// ---------------------------------------------------- what the port reads

FrontendDatabase Fred;
RaceParameters   TheRaceParameters;
tCopManager     *pCopManager;
uint32_t         bDefaultSeed;
int32_t          bVersionE3;
const char    *(*gFredTranslateFn)(int32_t id);
int32_t        (*gCurrLanguageFn)(void);
EggIsOnFn        gEggIsOnFn;
void          *(*gGetTextureInfoFn)(uint32_t name_hash, int use_default,
                                    int include_unloaded);
int32_t SkipFERearView, SkipFESpeedoMode, SkipFEEnableJumpCam,
        SkipFEEnableZoneCam;

static tCopManager      copmgr;
static struct Car       cars[NCARS];
static struct RacingCar rcs[NCARS];
static Timer            bestlap;
static EventGoal        goal;

// The event's bytes from aOldState on are retail's, in retail's order, on
// any host: only the two pointers before them change size.
typedef char tail_check[
    (sizeof(RaceEvent) - offsetof(RaceEvent, aOldState) == 424
     && offsetof(RaceEvent, aResults) - offsetof(RaceEvent, aOldState) == 328
     && sizeof(EventGoal) == 8 && sizeof(EventReward) == 8
     && sizeof(EventResult) == 12 && sizeof(cPlayerSettings) == 48)
    ? 1 : -1];

// ---------------------------------------------------------------- stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    (void)name;
    (void)flags;
    (void)pool;
    return calloc(1, (size_t)size + 16);
}

void bFree(void *p)
{
    free(p);
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    (void)seed;
    printf("  random %d\n", (int)range);
    return 0;
}

int32_t config_skip_fe(void)
{
    return 0;
}

void player_settings_reset_to_defaults(cPlayerSettings *ps)
{
    memset(ps, 0, sizeof *ps);
}

void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t lang)
{
    (void)flags;
    (void)lang;
    sprintf(buf, "T%d", (int)t->PackedTime);
}

const CarTypeInfo *cartypeinfo_get(int32_t type)
{
    (void)type;
    return NULL;
}

int32_t fred_race_was_aborted(const FrontendDatabase *f)
{
    return f->bRaceWasAborted;
}

void fred_calculate_starting_positions(FrontendDatabase *f)
{
    printf("  csp%s\n", f == &Fred ? "" : " ?fred");
}

static void set_race(const EventTrack *t, RaceParameters *rp)
{
    ptrdiff_t k = t - TheRaceEvent.aTracks;

    printf("  setrace %d%s\n", (int)k, rp == &TheRaceParameters ? "" : " ?rp");
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    printf("  bestlap R%d\n", (int)(rc - rcs));
    return &bestlap;
}

void timer_set_time(Timer *t, float seconds)
{
    uint32_t b;

    memcpy(&b, &seconds, 4);
    printf("  settime %08x\n", (unsigned)b);
    t->PackedTime = (int32_t)(b ^ 0x01234567u);
}

// ---------------------------------------------------------------- the dump

static void hex(char *out, const uint8_t *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        sprintf(out + 2 * i, "%02x", p[i]);
}

static char shown[4096];

static void dump(void)
{
    static char s[4096];
    const RaceEvent *ev = &TheRaceEvent;
    const RaceParameters *rp = &TheRaceParameters;
    char *p = s;
    int i;

    p += sprintf(p, "  = O");
    hex(p, ev->aOldState, 16);
    p += 32;
    p += sprintf(p, " V");
    hex(p, ev->aSavedState, 16);
    p += 32;
    p += sprintf(p, " S");
    if (ev->pState == NULL) {
        p += sprintf(p, "-");
    } else {
        hex(p, ev->pState, 16);
        p += 32;
    }
    p += sprintf(p, " R");
    for (i = 0; i < 8; i++)
        p += sprintf(p, " %d/%d/%d", (int)ev->aResults[i].nPosition,
                     (int)ev->aResults[i].Time.PackedTime,
                     (int)ev->aResults[i].nFinishReason);
    p += sprintf(p, " P%d,%d N%d,%d D", (int)rp->PlayerStartPosition[0],
                 (int)rp->PlayerStartPosition[1], (int)rp->NumPlayerCars,
                 (int)rp->NumAICars);
    for (i = 0; i < RACE_PARAMETERS_MAX_DRIVERS; i++) {
        const DriverInfo *d = &DriverInfoTable[i];

        p += sprintf(p, " %d:%d:%d", (int)d->UniqueDriverNumber,
                     (int)d->EliminatedRank, (int)d->StartingPosition);
    }
    p += sprintf(p, " PS");
    hex(p, (const uint8_t *)&rp->PlayerSettings[0], 48);
    p += 96;
    *p = 0;
    if (strcmp(s, shown) != 0) {
        strcpy(shown, s);
        printf("%s\n", s);
    }
}

// ---------------------------------------------------------------- the ops

static long long num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static int unhex(uint8_t *out, const char *h, int cap)
{
    int n = 0;

    while (h[0] && h[1] && n < cap) {
        unsigned v;

        sscanf(h, "%2x", &v);
        out[n++] = (uint8_t)v;
        h += 2;
    }
    return n;
}

static const char *P(const uint8_t *s)
{
    static char ring[4][24];
    static int k;
    char *b = ring[k++ & 3];

    if (s == NULL)
        return "-";
    if (s >= (const uint8_t *)&Fred && s < (const uint8_t *)&Fred + sizeof Fred)
        snprintf(b, 24, "F%d", (int)(s - (const uint8_t *)&Fred));
    else
        snprintf(b, 24, "?");
    return b;
}

// A state argument: s the event's state, o aOldState, v aSavedState, -
// NULL.
static const uint8_t *which(const char *w)
{
    switch (w[0]) {
    case 's':
        return TheRaceEvent.pState;
    case 'o':
        return TheRaceEvent.aOldState;
    case 'v':
        return TheRaceEvent.aSavedState;
    default:
        return NULL;
    }
}

static int16_t *ev_field(const char *f)
{
    RaceEvent *ev = &TheRaceEvent;

    if (!strcmp(f, "number")) return &ev->nNumber;
    if (!strcmp(f, "type")) return &ev->nType;
    if (!strcmp(f, "class")) return &ev->nClass;
    if (!strcmp(f, "cars")) return &ev->nCars;
    if (!strcmp(f, "tracks")) return &ev->nTracks;
    if (!strcmp(f, "rewards")) return &ev->nRewards;
    if (!strcmp(f, "opp")) return &ev->nOpponents;
    if (!strcmp(f, "players")) return &ev->nInitialPlayers;
    fprintf(stderr, "no event field %s\n", f);
    exit(2);
}

static void clear(void)
{
    memset(&TheRaceEvent, 0, sizeof TheRaceEvent);
    memset(&TheRaceParameters, 0, sizeof TheRaceParameters);
    TheRaceParameters.pDriverInfoTable = DriverInfoTable;
    memset(DriverInfoTable, 0, sizeof DriverInfoTable);
    memset(&Fred, 0, FRED_STATE_SPAN);
    Fred.GameType = 0;
    Fred.bRaceWasAborted = 0;
    Fred.NumPlayerCars = 0;
    memset(&Fred.FrontendPlayers[0].mPlayerSettings, 0,
           sizeof(cPlayerSettings));
    memset(rcs, 0, sizeof rcs);
    memset(cars, 0, sizeof cars);
    bestlap.PackedTime = 0;
    copmgr.fBeACopTime = 0.0f;
    pCopManager = NULL;
}

static void op(char **a, int n)
{
    RaceEvent *ev = &TheRaceEvent;
    RaceParameters *rp = &TheRaceParameters;
    const char *o = a[0];
    uint8_t b[64];
    int32_t r;

    (void)n;
    if (!strcmp(o, "clear")) {
        clear();
    } else if (!strcmp(o, "ev")) {
        *ev_field(a[1]) = (int16_t)num(a[2]);
    } else if (!strcmp(o, "last")) {
        ev->bIsLastOpen = (int32_t)num(a[1]);
    } else if (!strcmp(o, "goal")) {
        unhex((uint8_t *)&ev->Objective, a[1], 8);
    } else if (!strcmp(o, "reward")) {
        unhex((uint8_t *)&ev->aRewards[num(a[1])], a[2], 8);
    } else if (!strcmp(o, "result")) {
        EventResult *res = &ev->aResults[num(a[1])];

        res->nPosition = (int32_t)num(a[2]);
        res->Time.PackedTime = (int32_t)num(a[3]);
        res->nFinishReason = (int32_t)num(a[4]);
    } else if (!strcmp(o, "old")) {
        unhex(ev->aOldState, a[1], 16);
    } else if (!strcmp(o, "saved")) {
        unhex(ev->aSavedState, a[1], 16);
    } else if (!strcmp(o, "state")) {
        r = (int32_t)num(a[1]);
        ev->pState = r < 0 ? NULL : (uint8_t *)&Fred + r;
    } else if (!strcmp(o, "sbytes")) {
        if (ev->pState != NULL)
            unhex(ev->pState, a[1], 16);
    } else if (!strcmp(o, "rp")) {
        long long v = num(a[2]);

        if (!strcmp(a[1], "type")) rp->RaceType = (int32_t)v;
        else if (!strcmp(a[1], "players")) rp->NumPlayerCars = (int32_t)v;
        else if (!strcmp(a[1], "ai")) rp->NumAICars = (int32_t)v;
        else if (!strcmp(a[1], "cop")) rp->BeACop = (int32_t)v;
        else if (!strcmp(a[1], "sp0")) rp->PlayerStartPosition[0] = (int8_t)v;
        else if (!strcmp(a[1], "sp1")) rp->PlayerStartPosition[1] = (int8_t)v;
        else if (!strcmp(a[1], "ndrv")) rp->NumDriverInfo = (int32_t)v;
        else {
            fprintf(stderr, "no rp field %s\n", a[1]);
            exit(2);
        }
    } else if (!strcmp(o, "drv")) {
        DriverInfo *d = &DriverInfoTable[num(a[1])];

        d->UniqueDriverNumber = (int8_t)num(a[2]);
        d->EliminatedRank = (int8_t)num(a[3]);
        d->StartingPosition = (int8_t)num(a[4]);
        d->TheDriverType = (DriverType)num(a[5]);
    } else if (!strcmp(o, "fred")) {
        long long v = num(a[2]);

        if (!strcmp(a[1], "game")) Fred.GameType = (int32_t)v;
        else if (!strcmp(a[1], "aborted")) Fred.bRaceWasAborted = (int32_t)v;
        else if (!strcmp(a[1], "players")) Fred.NumPlayerCars = (int32_t)v;
        else {
            fprintf(stderr, "no fred field %s\n", a[1]);
            exit(2);
        }
    } else if (!strcmp(o, "ps")) {
        unhex((uint8_t *)&Fred.FrontendPlayers[0].mPlayerSettings, a[1], 48);
    } else if (!strcmp(o, "cm")) {
        pCopManager = num(a[1]) ? &copmgr : NULL;
        if (n > 2) {
            uint32_t bits = (uint32_t)num(a[2]);

            memcpy(&copmgr.fBeACopTime, &bits, 4);
        }
    } else if (!strcmp(o, "rc")) {
        int k = (int)num(a[1]);

        rcs[k].pCar = &cars[k];
        cars[k].DriverNumber = (int16_t)num(a[2]);
        rcs[k].FinishReason = (int16_t)num(a[3]);
        rcs[k].RaceTime.PackedTime = (int32_t)num(a[4]);
    } else if (!strcmp(o, "bestlap")) {
        bestlap.PackedTime = (int32_t)num(a[1]);

    // ---- the calls
    } else if (!strcmp(o, "size")) {
        printf("size -> %d\n", (int)raceevent_get_state_size(ev));
    } else if (!strcmp(o, "multi")) {
        printf("multi -> %d\n", (int)raceevent_is_multi_track(ev));
    } else if (!strcmp(o, "aborted")) {
        printf("aborted -> %d\n", (int)raceevent_race_was_aborted(ev));
    } else if (!strcmp(o, "resetres")) {
        printf("resetres\n");
        raceevent_reset_results(ev);
    } else if (!strcmp(o, "r2d")) {
        printf("r2d %d -> %d\n", (int)num(a[1]),
               (int)raceevent_racer_index_from_driver_number(ev,
                                                             (int32_t)num(a[1])));
    } else if (!strcmp(o, "d2r")) {
        printf("d2r %d -> %d\n", (int)num(a[1]),
               (int)raceevent_driver_number_from_racer_index(ev,
                                                             (int32_t)num(a[1])));
    } else if (!strcmp(o, "record")) {
        int k = (int)num(a[1]);

        printf("record R%d %d\n", k, (int)num(a[2]));
        raceevent_record_results(ev, NULL, &rcs[k], (int32_t)num(a[2]));
    } else if (!strcmp(o, "rin")) {
        printf("rin %d -> %d\n", (int)num(a[1]),
               (int)raceevent_racer_in_the_race(ev, (int32_t)num(a[1])));
    } else if (!strcmp(o, "din")) {
        printf("din %d -> %d\n", (int)num(a[1]),
               (int)raceevent_driver_in_the_race(ev, (int32_t)num(a[1])));
    } else if (!strcmp(o, "relim")) {
        printf("relim %d -> %d\n", (int)num(a[1]),
               (int)raceevent_racer_eliminated(ev, (int32_t)num(a[1])));
    } else if (!strcmp(o, "delim")) {
        printf("delim %d -> %d\n", (int)num(a[1]),
               (int)raceevent_driver_eliminated(ev, (int32_t)num(a[1])));
    } else if (!strcmp(o, "lastp")) {
        printf("lastp -> %d\n", (int)raceevent_get_last_place(ev));
    } else if (!strcmp(o, "firstp")) {
        printf("firstp -> %d\n", (int)raceevent_get_first_place(ev));
    } else if (!strcmp(o, "getst")) {
        printf("getst %s %s %s %s\n", P(raceevent_get_rank_state(ev)),
               P(raceevent_get_tournament_state(ev)),
               P(raceevent_get_ko_state(ev)), P(raceevent_get_time_state(ev)));
    } else if (!strcmp(o, "post")) {
        printf("post\n");
        raceevent_post_results(ev);
    } else if (!strcmp(o, "save")) {
        printf("save\n");
        raceevent_save_state(ev);
    } else if (!strcmp(o, "cycle")) {
        printf("cycle\n");
        raceevent_cycle_results(ev);
    } else if (!strcmp(o, "restart")) {
        printf("restart\n");
        raceevent_restart(ev);
    } else if (!strcmp(o, "fell")) {
        printf("fell -> %d\n", (int)raceevent_status_fell(ev));
    } else if (!strcmp(o, "adv")) {
        printf("adv -> %d\n", (int)raceevent_status_advanced(ev));
    } else if (!strcmp(o, "keep")) {
        printf("keep\n");
        raceevent_keep_state(ev);
    } else if (!strcmp(o, "ridx")) {
        printf("ridx -> %d\n", (int)raceevent_get_race_index(ev));
    } else if (!strcmp(o, "rcount")) {
        printf("rcount -> %d\n", (int)raceevent_get_race_count(ev));
    } else if (!strcmp(o, "next")) {
        r = raceevent_setup_next_race(ev);
        printf("next -> %d\n", (int)r);
    } else if (!strcmp(o, "csp")) {
        r = raceevent_calc_starting_positions(ev);
        printf("csp -> %d\n", (int)r);
    } else if (!strcmp(o, "another")) {
        printf("another -> %d\n", (int)raceevent_is_there_another_race(ev));
    } else if (!strcmp(o, "statusof")) {
        printf("statusof %s -> %d\n", a[1],
               (int)raceevent_get_status_of(ev, which(a[1])));
    } else if (!strcmp(o, "statusgoal")) {
        unhex((uint8_t *)&goal, a[1], 8);
        printf("statusgoal %s -> %d\n", a[1],
               (int)raceevent_get_status_goal(ev, &goal));
    } else if (!strcmp(o, "status")) {
        printf("status -> %d\n", (int)raceevent_get_status(ev));
    } else if (!strcmp(o, "oldstatus")) {
        printf("oldstatus -> %d\n", (int)raceevent_get_old_status(ev));
    } else if (!strcmp(o, "resetstate")) {
        printf("resetstate\n");
        raceevent_reset_state(ev);
    } else if (!strcmp(o, "earned")) {
        printf("earned %d %s -> %d\n", (int)num(a[1]), a[2],
               (int)raceevent_reward_earned(ev, (int32_t)num(a[1]),
                                            which(a[2])));
    } else if (!strcmp(o, "anyearned")) {
        printf("anyearned -> %d\n", (int)raceevent_any_reward_earned(ev));
    } else if (!strcmp(o, "won")) {
        printf("won -> %d\n", (int)raceevent_user_won(ev));
    } else {
        fprintf(stderr, "no op %s\n", o);
        exit(2);
    }
    (void)b;
}

int main(int argc, char **argv)
{
    static char line[1024];
    FILE *sc;

    if (argc < 2) {
        fprintf(stderr, "usage: raceevent_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL) {
        perror(argv[1]);
        return 2;
    }
    gEventTrackSetRaceOnFn = set_race;
    clear();
    while (fgets(line, sizeof line, sc)) {
        char *arg[16];
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        for (t = strtok(line, "|"); t != NULL && n < 16; t = strtok(NULL, "|"))
            arg[n++] = t;
        op(arg, n);
        dump();
    }
    fclose(sc);
    return 0;
}
