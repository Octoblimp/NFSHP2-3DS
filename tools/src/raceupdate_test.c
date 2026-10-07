// Harness for tools/raceupdate_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     raceupdate_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "aidriver.h"
#include "bmem.h"
#include "car.h"
#include "copmanager.h"
#include "player.h"
#include "playerfinish.h"
#include "race.h"
#include "racecore.h"
#include "racefinish.h"
#include "racerun.h"
#include "racesplit.h"
#include "raceupdate.h"
#include "realtime.h"
#include "replay.h"
#include "timer.h"
#include "worldobject.h"

enum {
    OP_TAG, OP_RESET, OP_RACE, OP_RC, OP_CAR, OP_PLAYER, OP_GLOBAL,
    OP_SAMPLE, OP_UPDATE, OP_FINISH, OP_FINISH_CAR, OP_PROJECT, OP_MONITOR,
    OP_SAVE_GHOST, OP_UPDATE_GHOST, OP_LEADING, OP_FINISHER, OP_NEXT_RANK,
    OP_SIMULATE, OP_SET_FINISHED, OP_DUMP
};

enum {
    F_STAGE, F_GO, F_COUNTDOWN, F_START, F_RACETIME, F_BEST, F_NUM, F_NFIN,
    F_LAPS, F_FPOS, F_FPLAYER, F_STARTLINE, F_FINISHLINE, F_ORDER, F_CAPCAR,
    F_CAPDATA, F_REPDATA, F_WO
};

enum {
    R_CAR, R_LAPS, R_POS, R_PREV, R_ORDER, R_CROSSED, R_NEWLAP, R_LED,
    R_REASON, R_CLE, R_FLE, R_RACETIME, R_BCT = 20, R_RUN = 25, R_BEST = 30
};

enum {
    C_PLAYER, C_RC, C_MODE, C_CTRL, C_FORCE, C_TIMEOUT, C_SPEED,
    C_POS = 10, C_BODY = 20
};

enum { PL_CAR, PL_NUMBER, PL_TFR, PL_FAL };

enum {
    G_TIMER, G_FRAMES, G_NPLAYERS, G_BYINDEX0, G_BYINDEX1, G_RACETYPE, G_TT,
    G_BEACOP, G_PULLTO, G_COPMGR, G_COPIDX, G_GETSAMPLE, G_G1_TIME,
    G_G1_SAMPLES, G_G2_TIME, G_G2_LAPS, G_WO_ENABLED, G_COP = 20
};

#define NCARS    8
#define NPLAYERS 2
#define NCOPS    7

// ------------------------------------------------------------- the world

static Race   race;
static Car    cars[NCARS];
static AICarController aicc[2][NCARS];  // a0..a7, and b0..b7 SetControlMode
                                        // builds
static struct Player players[NPLAYERS];
static union {
    tCopManagerHead h;
    char            b[256];
} copmgr;
static tCop       cops[NCOPS];
static struct GhostCarData *g1, *g2;
static WorldObject wo;
static ReplayManager rm;
static Timer      start_scratch;
static uint32_t   sample[16];
static int32_t    sample_answer;

// What the linked files leave to the game.
int32_t        WorldTimer;
int32_t        WorldTimeFrames;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
tCopManager   *pCopManager;
ReplayManager *pReplayManager;
float          AIActionPullOverCrossFinishLineTimeout;

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static void die(const char *what, int32_t v)
{
    fprintf(stderr, "%s %d\n", what, v);
    exit(2);
}

static Car *car_of(int32_t i)
{
    if (i == -1)
        return NULL;
    if (i < 0 || i >= NCARS)
        die("no car", i);
    return &cars[i];
}

static struct Player *player_of(int32_t i)
{
    if (i == -1)
        return NULL;
    if (i < 0 || i >= NPLAYERS)
        die("no player", i);
    return &players[i];
}

static struct RacingCar *rc_of(int32_t j)
{
    if (j == -1)
        return NULL;
    if (j < 0 || j >= NCARS)
        die("no racing car", j);
    return &race.RacingCarTable[j];
}

static void label(char *buf, size_t n, const void *a)
{
    int i, k;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    if (a == (const void *)&race) {
        snprintf(buf, n, "race");
        return;
    }
    if (a == (const void *)&race.StartTime) {
        snprintf(buf, n, "race+12");
        return;
    }
    if (a == (const void *)&race.RaceTime) {
        snprintf(buf, n, "race+16");
        return;
    }
    for (i = 0; i < NCARS; i++) {
        if (a == (const void *)&cars[i]) {
            snprintf(buf, n, "c%d", i);
            return;
        }
        if (a == (const void *)&race.RacingCarTable[i]) {
            snprintf(buf, n, "r%d", i);
            return;
        }
        for (k = 0; k < 2; k++)
            if (a == (const void *)&aicc[k][i]) {
                snprintf(buf, n, "%c%d", "ab"[k], i);
                return;
            }
    }
    for (i = 0; i < NPLAYERS; i++)
        if (a == (const void *)&players[i]) {
            snprintf(buf, n, "p%d", i);
            return;
        }
    if (a == (const void *)g1) {
        snprintf(buf, n, "g1");
        return;
    }
    if (a == (const void *)g2) {
        snprintf(buf, n, "g2");
        return;
    }
    if (a == (const void *)&wo) {
        snprintf(buf, n, "wo");
        return;
    }
    if (a == (const void *)&rm) {
        snprintf(buf, n, "rm");
        return;
    }
    if (a == (const void *)&start_scratch) {
        snprintf(buf, n, "start");
        return;
    }
    snprintf(buf, n, "?");
}

static const char *lab(const void *a)
{
    static char bufs[16][32];
    static int k;
    char *b = bufs[k++ & 15];

    label(b, 32, a);
    return b;
}

static const char *matrix_str(const bMatrix4 *m)
{
    static char b[160];
    uint32_t w[16];
    size_t at = 0;
    int k;

    memcpy(w, m, sizeof w);
    for (k = 0; k < 16; k++)
        at += (size_t)snprintf(b + at, sizeof b - at, k ? " %08x" : "%08x",
                               w[k]);
    return b;
}

// ------------------------------------------------------------ the frees

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    (void)size; (void)name; (void)flags; (void)pool;
    fprintf(stderr, "unexpected alloc\n");
    exit(4);
}

// Logged, never freed: the ghost data is the harness's.
static void free_hook(void *p)
{
    printf("  delete %s\n", lab(p));
}

// ------------------------------------------------------------ stand-ins

void racingcar_update_lap_counts(struct RacingCar *rc)
{
    printf("  laps %s\n", lab(rc));
}

void race_set_race_stage(Race *r, eRaceStage stage)
{
    printf("  stage %d\n", (int32_t)stage);
    r->RaceStage = stage;
}

void race_sort_racing_cars_by_leadership(Race *r)
{
    printf("  sort %s\n", lab(r));
}

// racerun.c's (0x001475b8), which racerun_check checks: the car's player,
// or NULL with no car.
struct Player *racingcar_get_player(const struct RacingCar *rc)
{
    if (rc->pCar == NULL)
        return NULL;
    return rc->pCar->pPlayer;
}

// Car::SetControlMode: the mode, and a new controller for AI_CONTROL,
// b<car>, as SetControlMode builds an AIDriver (its constructor's
// ForceCurrentAction NONE and PullOverTimeout 1e7).
void car_set_control_mode(Car *c, ControlMode mode)
{
    int i = (int)(c - cars);

    printf("  mode %s %d\n", lab(c), (int32_t)mode);
    c->TheControlMode = mode;
    if (mode == AI_CONTROL) {
        aicc[1][i].ForceCurrentAction = AIACTION_NONE;
        aicc[1][i].PullOverTimeout = 1e7f;
        c->pCarController = (CarController *)(void *)&aicc[1][i];
    }
}

void car_blink_blink_poof(Car *c)
{
    printf("  blink %s\n", lab(c));
}

void ReplayManager_RegisterInterestingEvent(ReplayManager *m, float value,
                                            const char *description)
{
    printf("  event %s %08x %s\n", lab(m), bitsf(value), description);
}

float tatt_get_time_around_track(TimeAroundTrackTable *t, float lap)
{
    (void)t; (void)lap;
    fprintf(stderr, "tatt called\n");
    exit(4);
}

static void record_results(Race *r, struct RacingCar *rc, int32_t position)
{
    printf("  record %s %s %d\n", lab(r), lab(rc), position);
}

static void lap_speech(Car *c, int32_t laps)
{
    printf("  lapspeech %s %d\n", lab(c), laps);
}

static void clear_queue(void)
{
    printf("  clearqueue\n");
}

static void finish_sound(struct Player *p)
{
    printf("  finishsound %s\n", lab(p));
}

static void add_sample(struct GhostCarData *d, const bMatrix4 *m, Timer *t)
{
    printf("  addsample %s t %08x m %s\n", lab(d), t->PackedTime,
           matrix_str(m));
}

static int32_t get_sample(struct GhostCarData *d, bMatrix4 *m, Timer *t)
{
    printf("  getsample %s %s %08x -> %d\n", lab(d), lab(t), t->PackedTime,
           sample_answer);
    memcpy(m, sample, sizeof sample);
    return sample_answer;
}

static void write_file(const char *name, void *data, int32_t size)
{
    printf("  write %s %s %d\n", name, lab(data), size);
}

// ------------------------------------------------------------- the dump

static void dump(void)
{
    int i, k;

    printf("race st %d go %d cd %d start %08x time %08x best %08x n %d "
           "fin %d laps %d fpos %d fpl %d cap %s capd %s\n",
           (int32_t)race.RaceStage, race.StartGoTimeFrames,
           race.StartCountdownTimeFrames, race.StartTime.PackedTime,
           race.RaceTime.PackedTime, race.BestLapTime.PackedTime,
           race.NumRacingCars, race.NumRacingCarsFinished, race.NumLapsInRace,
           race.ForceRaceFinishPosition, race.ForceRaceFinishPlayerNum,
           lab(race.pCapturingGhostCar), lab(race.pCapturingGhostCarData));
    printf("order");
    for (i = 0; i < NCARS; i++)
        printf(" %s", lab(race.pRacingCars[i]));
    printf("\n");
    for (i = 0; i < NCARS; i++) {
        const struct RacingCar *rc = &race.RacingCarTable[i];

        printf("r%d car %s laps %d pos %d prev %d ord %d x %d nl %d led %d "
               "why %d cle %08x fle %08x t %08x best",
               i, lab(rc->pCar), rc->NumLapsCompleted, rc->RacePosition,
               rc->PreviousRacePosition, rc->FinishingOrder,
               rc->CrossedFinishLine, rc->CompletedNewLap, rc->NumLapsLed,
               rc->FinishReason, bitsf(rc->CurrentLapNumberExact),
               bitsf(rc->FinishedLapNumberExact), rc->RaceTime.PackedTime);
        for (k = 0; k < 5; k++)
            printf(" %08x", rc->BestRunningTimes[k].PackedTime);
        printf("\n");
    }
    for (i = 0; i < NCARS; i++) {
        const Car *c = &cars[i];
        const AICarController *a =
            (const AICarController *)(const void *)c->pCarController;

        if (a != NULL)
            printf("c%d mode %d ctl %s force %d to %08x\n", i,
                   (int32_t)c->TheControlMode, lab(a),
                   (int32_t)a->ForceCurrentAction,
                   bitsf(a->PullOverTimeout));
        else
            printf("c%d mode %d ctl null\n", i, (int32_t)c->TheControlMode);
    }
    for (i = 0; i < NPLAYERS; i++)
        printf("p%d tfr %08x fal %d\n", i, players[i].TimeFinishedRacing,
               (int32_t)players[i].FinishAnimationLength);
    printf("wo en %d m %s\n", wo.Enabled, matrix_str(&wo.Matrix));
    printf("g1 t %08x g2 t %08x\n", g1->RaceTime.PackedTime,
           g2->RaceTime.PackedTime);
}

// ------------------------------------------------------------- the pokes

static void reset(void)
{
    int i;

    memset(&race, 0, sizeof race);
    memset(cars, 0, sizeof cars);
    memset(aicc, 0, sizeof aicc);
    memset(players, 0, sizeof players);
    memset(&copmgr, 0, sizeof copmgr);
    memset(cops, 0, sizeof cops);
    memset(g1, 0, sizeof *g1);
    memset(g2, 0, sizeof *g2);
    memset(&wo, 0, sizeof wo);
    memset(sample, 0, sizeof sample);
    sample_answer = 0;
    for (i = 0; i < NCARS; i++) {
        race.pRacingCars[i] = &race.RacingCarTable[i];
        race.RacingCarTable[i].pCar = &cars[i];
        cars[i].pRacingCar = &race.RacingCarTable[i];
        cars[i].pCarController = (CarController *)(void *)&aicc[0][i];
    }
    strcpy(race.GhostCarDataFilename, "host0:ghost.dat");
    WorldTimer = 0;
    WorldTimeFrames = 0;
    PlayerNumPlayers = 0;
    PlayerPlayersByIndex[0] = PlayerPlayersByIndex[1] = NULL;
    pCopManager = NULL;
    TheRaceParameters.RaceType = 0;
    TheRaceParameters.TimeTrialTime.PackedTime = 0;
    TheRaceParameters.BeACop = 0;
    AIActionPullOverCrossFinishLineTimeout = 15.0f;
}

static void poke_race(int32_t f, int32_t v)
{
    switch (f) {
    case F_STAGE:      race.RaceStage = (eRaceStage)v; break;
    case F_GO:         race.StartGoTimeFrames = v; break;
    case F_COUNTDOWN:  race.StartCountdownTimeFrames = v; break;
    case F_START:      race.StartTime.PackedTime = (uint32_t)v; break;
    case F_RACETIME:   race.RaceTime.PackedTime = (uint32_t)v; break;
    case F_BEST:       race.BestLapTime.PackedTime = (uint32_t)v; break;
    case F_NUM:        race.NumRacingCars = v; break;
    case F_NFIN:       race.NumRacingCarsFinished = v; break;
    case F_LAPS:       race.NumLapsInRace = v; break;
    case F_FPOS:       race.ForceRaceFinishPosition = v; break;
    case F_FPLAYER:    race.ForceRaceFinishPlayerNum = v; break;
    case F_STARTLINE:  race.StartLineBoundaryNumber = (int8_t)v; break;
    case F_FINISHLINE: race.FinishLineBoundaryNumber = (int8_t)v; break;
    case F_ORDER:      race.pRacingCars[v >> 4 & 7] = rc_of(v & 15); break;
    case F_CAPCAR:     race.pCapturingGhostCar = car_of(v); break;
    case F_CAPDATA:    race.pCapturingGhostCarData = v ? g1 : NULL; break;
    case F_REPDATA:    race.pReplayingGhostCarData = v ? g2 : NULL; break;
    case F_WO:         race.pReplayingGhostCarWorldObject = v ? &wo : NULL;
                       break;
    default:           die("race field", f);
    }
}

static void poke_rc(int32_t j, int32_t f, int32_t v)
{
    struct RacingCar *rc = rc_of(j);

    if (f >= R_BCT && f < R_BCT + 5) {
        rc->BoundaryCrossingTimes[f - R_BCT].PackedTime = (uint32_t)v;
        return;
    }
    if (f >= R_RUN && f < R_RUN + 5) {
        rc->RunningTimes[f - R_RUN].PackedTime = (uint32_t)v;
        return;
    }
    if (f >= R_BEST && f < R_BEST + 5) {
        rc->BestRunningTimes[f - R_BEST].PackedTime = (uint32_t)v;
        return;
    }
    switch (f) {
    case R_CAR:      rc->pCar = car_of(v); break;
    case R_LAPS:     rc->NumLapsCompleted = (int8_t)v; break;
    case R_POS:      rc->RacePosition = (int8_t)v; break;
    case R_PREV:     rc->PreviousRacePosition = (int8_t)v; break;
    case R_ORDER:    rc->FinishingOrder = (int8_t)v; break;
    case R_CROSSED:  rc->CrossedFinishLine = (int8_t)v; break;
    case R_NEWLAP:   rc->CompletedNewLap = (int8_t)v; break;
    case R_LED:      rc->NumLapsLed = (int16_t)v; break;
    case R_REASON:   rc->FinishReason = (int16_t)v; break;
    case R_CLE:      rc->CurrentLapNumberExact = fbits((uint32_t)v); break;
    case R_FLE:      rc->FinishedLapNumberExact = fbits((uint32_t)v); break;
    case R_RACETIME: rc->RaceTime.PackedTime = (uint32_t)v; break;
    default:         die("racing car field", f);
    }
}

static void poke_car(int32_t i, int32_t f, int32_t v)
{
    Car *c = car_of(i);

    if (f >= C_POS && f < C_POS + 4) {
        float *p = &c->State.Position.x;
        p[f - C_POS] = fbits((uint32_t)v);
        return;
    }
    if (f >= C_BODY && f < C_BODY + 16) {
        uint32_t w = (uint32_t)v;
        memcpy((char *)&c->State.BodyMatrix + 4 * (f - C_BODY), &w, 4);
        return;
    }
    switch (f) {
    case C_PLAYER:  c->pPlayer = player_of(v); break;
    case C_RC:      c->pRacingCar = rc_of(v); break;
    case C_MODE:    c->TheControlMode = (ControlMode)v; break;
    case C_CTRL:
        c->pCarController = v < 0 ? NULL
            : (CarController *)(void *)&aicc[v & 1][i];
        break;
    case C_FORCE:   aicc[0][i].ForceCurrentAction = (AIActionType)v; break;
    case C_TIMEOUT: aicc[0][i].PullOverTimeout = fbits((uint32_t)v); break;
    case C_SPEED:   c->State.VelocityMagnitude = fbits((uint32_t)v); break;
    default:        die("car field", f);
    }
}

static void poke_player(int32_t i, int32_t f, int32_t v)
{
    struct Player *p = player_of(i);

    switch (f) {
    case PL_CAR:    p->MyCar = car_of(v); break;
    case PL_NUMBER: p->PlayerNumber = v; break;
    case PL_TFR:    p->TimeFinishedRacing = (uint32_t)v; break;
    case PL_FAL:    p->FinishAnimationLength = (uint32_t)v; break;
    default:        die("player field", f);
    }
}

static void poke_global(int32_t f, int32_t v)
{
    if (f >= G_COP && f < G_COP + NCOPS) {
        int k = f - G_COP;
        if (v == -2) {
            copmgr.h.Cops[k] = NULL;
        } else {
            copmgr.h.Cops[k] = &cops[k];
            cops[k].pMyCar = car_of(v);
        }
        return;
    }
    switch (f) {
    case G_TIMER:      WorldTimer = v; break;
    case G_FRAMES:     WorldTimeFrames = v; break;
    case G_NPLAYERS:   PlayerNumPlayers = v; break;
    case G_BYINDEX0:   PlayerPlayersByIndex[0] = player_of(v); break;
    case G_BYINDEX1:   PlayerPlayersByIndex[1] = player_of(v); break;
    case G_RACETYPE:   TheRaceParameters.RaceType = v; break;
    case G_TT:         TheRaceParameters.TimeTrialTime.PackedTime =
                           (uint32_t)v;
                       break;
    case G_BEACOP:     TheRaceParameters.BeACop = v; break;
    case G_PULLTO:     AIActionPullOverCrossFinishLineTimeout =
                           fbits((uint32_t)v);
                       break;
    case G_COPMGR:     pCopManager = v ? (tCopManager *)(void *)&copmgr
                                       : NULL;
                       break;
    case G_COPIDX:     copmgr.h.nPlayerCopIndex = v; break;
    case G_GETSAMPLE:  sample_answer = v; break;
    case G_G1_TIME:    g1->RaceTime.PackedTime = (uint32_t)v; break;
    case G_G1_SAMPLES: g1->NumSamples = v; break;
    case G_G2_TIME:    g2->RaceTime.PackedTime = (uint32_t)v; break;
    case G_G2_LAPS:    g2->NumLaps = v; break;
    case G_WO_ENABLED: wo.Enabled = v; break;
    default:           die("global", f);
    }
}

// ------------------------------------------------------------- the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **out = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

// ------------------------------------------------------------- the main

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;

    if (argc != 2) {
        fprintf(stderr, "usage: raceupdate_test ops.bin\n");
        return 2;
    }
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fp) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fp);

    tags = read_strings(&ntags);
    nflat = next();
    end = rd + (size_t)nflat;

    bSetMemoryHooks(malloc_hook, free_hook);
    g1 = calloc(1, sizeof *g1);
    g2 = calloc(1, sizeof *g2);
    pCurrentRace = &race;
    pReplayManager = &rm;
    gRaceFinishCarFn = race_finish_car;
    gRaceEventRecordResultsFn = record_results;
    gLapFinishedSpeechFn = lap_speech;
    gSpeechClearEventQueueFn = clear_queue;
    gTriggerFinishLineSoundFn = finish_sound;
    gGhostCarDataAddSampleFn = add_sample;
    gGhostCarDataGetSampleFn = get_sample;
    gBWriteToFileFn = write_file;
    reset();

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_RESET:
            reset();
            break;
        case OP_RACE: {
            int32_t f = next(), v = next();
            poke_race(f, v);
            break;
        }
        case OP_RC: {
            int32_t j = next(), f = next(), v = next();
            poke_rc(j, f, v);
            break;
        }
        case OP_CAR: {
            int32_t i = next(), f = next(), v = next();
            poke_car(i, f, v);
            break;
        }
        case OP_PLAYER: {
            int32_t i = next(), f = next(), v = next();
            poke_player(i, f, v);
            break;
        }
        case OP_GLOBAL: {
            int32_t f = next(), v = next();
            poke_global(f, v);
            break;
        }
        case OP_SAMPLE: {
            int32_t k = next(), v = next();
            if (k < 0 || k >= 16)
                die("sample word", k);
            sample[k] = (uint32_t)v;
            break;
        }
        case OP_UPDATE:
            printf("update\n");
            race_update(&race);
            dump();
            break;
        case OP_FINISH: {
            int32_t i = next(), pos = next(), blink = next(), why = next();
            printf("finish %d %d %d %d\n", i, pos, blink, why);
            race_finish_car(&race, i, pos, blink, why);
            dump();
            break;
        }
        case OP_FINISH_CAR: {
            int32_t c = next(), pos = next(), blink = next(), why = next();
            printf("finishcar %s %d %d %d\n", lab(car_of(c)), pos, blink,
                   why);
            race_finish_car_by_car(&race, car_of(c), pos, blink, why);
            dump();
            break;
        }
        case OP_PROJECT: {
            int32_t j = next(), laps = next(), start = next();
            start_scratch.PackedTime = (uint32_t)start;
            printf("project %s %d %08x\n", lab(rc_of(j)), laps,
                   (uint32_t)start);
            racingcar_project_race_time(rc_of(j), laps, &start_scratch);
            dump();
            break;
        }
        case OP_MONITOR:
            printf("monitor\n");
            race_monitor_leadership(&race);
            dump();
            break;
        case OP_SAVE_GHOST: {
            int32_t j = next();
            printf("saveghost %s\n", lab(rc_of(j)));
            race_maybe_save_ghost_car_data(&race, rc_of(j));
            dump();
            break;
        }
        case OP_UPDATE_GHOST:
            printf("updateghost\n");
            race_update_ghost_car(&race);
            dump();
            break;
        case OP_LEADING:
            printf("leading -> %s\n",
                   lab(race_get_leading_unfinished_car(&race)));
            break;
        case OP_FINISHER: {
            int32_t rank = next();
            printf("finisher %d -> %s\n", rank,
                   lab(race_get_finisher(&race, rank)));
            break;
        }
        case OP_NEXT_RANK:
            printf("nextrank -> %d\n", race_get_next_finish_rank(&race));
            break;
        case OP_SIMULATE:
            printf("simulate\n");
            race_simulate_race_finish(&race);
            dump();
            break;
        case OP_SET_FINISHED: {
            int32_t p = next();
            printf("setfinished %s\n", lab(player_of(p)));
            player_set_finished_racing(player_of(p));
            dump();
            break;
        }
        case OP_DUMP:
            dump();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
