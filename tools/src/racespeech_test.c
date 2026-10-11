// racespeech_test -- tools/racespeech_check.py's harness.
//
// Runs racespeech.c and the speech conversions over the checker's script.
// Everything they call is a stub here that logs its arguments and answers
// from the script, as the model's stubs do: bRandom, SPCH_AddEventV,
// RaceEvent::GetStatus and its won test, RacingCar::GetLastLapTime and
// GetBestLapTimesTable. IsReplayDemoMode is retail's one compare. The
// two lap speeches' builders print all four fields; only TypeA is said.
//
//     racespeech_test script.txt > out.txt

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "fred.h"
#include "fredrace.h"
#include "highscore.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racesplit.h"
#include "racespeech.h"
#include "spch.h"
#include "speechconv.h"

#define NCARS 4
#define NCTI  71                        // car types -2 .. 68
#define QN    16

// ---------------------------------------------------- what the port reads

RaceParameters   TheRaceParameters;
RaceEventFields  TheRaceEventFields;
FrontendDatabase Fred;
Race            *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
tCopManager     *pCopManager;
struct Player   *PlayerPlayersByNumber[2];
uint32_t         bDefaultSeed;
int32_t        (*gRaceEventGetStatusFn)(void);

static Race            race;
static RaceCoordinator rco;
static tCopManager     cm;
static Player          players[2];
static Car             cars[NCARS];
static RacingCar       rcs[NCARS];
static CarTypeInfo     cti[NCTI];
static TransientStatsElement rows[2];
static uint8_t         reward[4];
static Timer           lastlap;
static FredHighScore   best[HIGH_SCORE_RECORDS];

typedef struct Queue {
    uint32_t q[QN];
    int      n, i;
    uint32_t answer;
} Queue;

static Queue randq, statusq, wonq;

static uint32_t next(Queue *q)
{
    return q->i < q->n ? q->q[q->i++] : q->answer;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ---------------------------------------------------------------- stubs

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    int32_t r = (int32_t)next(&randq);

    printf("  random%s %d -> %d\n", seed == &bDefaultSeed ? "" : " ?seed",
           (int)range, (int)r);
    return r;
}

int32_t spch_add_event_v(uint32_t id, int32_t count, ...)
{
    va_list ap;
    int32_t i;

    printf("  spch %d %d", (int)id, (int)count);
    va_start(ap, count);
    for (i = 0; i < count; i++)
        printf(" %d", (int)va_arg(ap, int32_t));
    va_end(ap);
    printf("\n");
    return 1;
}

static int32_t get_status(void)
{
    int32_t r = (int32_t)next(&statusq);

    printf("  status -> %d\n", (int)r);
    return r;
}

static int32_t user_won(void)
{
    int32_t r = (int32_t)next(&wonq);

    printf("  won -> %d\n", (int)r);
    return r;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    return rc->CurrentRCState == RCSTATE_REPLAY_DEMO_MODE;
}

static int rc_index(const struct RacingCar *rc)
{
    int i;

    for (i = 0; i < NCARS; i++)
        if (rc == &rcs[i])
            return i;
    return -1;
}

Timer *racingcar_get_last_lap_time(struct RacingCar *rc)
{
    printf("  lastlap R%d -> %d\n", rc_index(rc), (int)lastlap.PackedTime);
    return &lastlap;
}

FredHighScore *fred_get_best_lap_times_table(FrontendDatabase *f,
                                             int32_t track,
                                             int32_t carClass,
                                             int32_t direction)
{
    printf("  best%s %d %d %d -> %d\n", f == &Fred ? "" : " ?fred",
           (int)track, (int)carClass, (int)direction,
           (int)best[0].Time.PackedTime);
    return best;
}

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return &cti[carType + 2];
}

// ------------------------------------------------------------- the script

static char *fields[40];
static int   nfields;

static int split(char *s)
{
    nfields = 0;
    while (nfields < 40) {
        char *bar = strchr(s, '|');

        fields[nfields++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return nfields;
}

static int32_t I(int j)
{
    return (int32_t)strtoll(fields[j], NULL, 0);
}

static uint32_t U(int j)
{
    return (uint32_t)strtoull(fields[j], NULL, 0);
}

static void fill(Queue *q)
{
    int j;

    q->n = 0;
    q->i = 0;
    for (j = 1; j < nfields && q->n < QN; j++)
        q->q[q->n++] = U(j);
}

static void rp(const char *f, int32_t v)
{
    RaceParameters *p = &TheRaceParameters;

    if (!strcmp(f, "Track"))          p->TrackNumber = v;
    else if (!strcmp(f, "Dir"))       p->TrackDirection = v;
    else if (!strcmp(f, "RaceType"))  p->RaceType = v;
    else if (!strcmp(f, "Laps"))      p->NumLapsInRace = v;
    else if (!strcmp(f, "Players"))   p->NumPlayerCars = v;
    else if (!strcmp(f, "AI"))        p->NumAICars = v;
    else if (!strcmp(f, "EventTree")) p->EventTreeRace = v;
    else if (!strcmp(f, "BeACop"))    p->BeACop = v;
    else {
        fprintf(stderr, "no field %s\n", f);
        exit(2);
    }
}

static Player *player_at(int32_t k)
{
    return k < 0 ? NULL : &players[k];
}

static void flags(void)
{
    printf("  P0 %d %d P1 %d %d\n", (int)players[0].HasHeardRaceOverSpeech,
           (int)players[0].New2696, (int)players[1].HasHeardRaceOverSpeech,
           (int)players[1].New2696);
}

static void run(void)
{
    const char *o = fields[0];

    if (!strcmp(o, "rp")) {
        rp(fields[1], I(2));
    } else if (!strcmp(o, "race")) {
        race.BestLapTime.PackedTime = U(1);
        race.NumRacingCars = I(2);
    } else if (!strcmp(o, "rc")) {
        if (I(1) < 0) {
            pRaceCoordinator = NULL;
        } else {
            rco.CurrentRCState = I(1);
            pRaceCoordinator = &rco;
        }
    } else if (!strcmp(o, "cm")) {
        pCopManager = I(1) ? &cm : NULL;
    } else if (!strcmp(o, "arrest")) {
        cm.CarPullovers[I(1)].bArrest = I(2);
    } else if (!strcmp(o, "player")) {
        Player *p = &players[I(1)];

        p->MyCar = I(2) < 0 ? NULL : &cars[I(2)];
        p->HasHeardRaceOverSpeech = I(3);
        p->New2696 = I(4);
    } else if (!strcmp(o, "ppn")) {
        PlayerPlayersByNumber[I(1)] = player_at(I(2));
    } else if (!strcmp(o, "car")) {
        Car *c = &cars[I(1)];
        RacingCar *r = &rcs[I(1)];

        c->CarIndex = (int16_t)I(2);
        c->pCarTypeInfo = &cti[I(3) + 2];
        c->pPlayer = player_at(I(4));
        c->pRacingCar = r;
        r->RacePosition = (int8_t)I(5);
        r->CurrentLapNumberExact = bf(U(6));
    } else if (!strcmp(o, "cti")) {
        CarTypeInfo *t = &cti[I(1) + 2];

        t->UsageType = I(2);
        t->HighPerformance = (int8_t)I(3);
        t->CarClass = (int8_t)I(4);
    } else if (!strcmp(o, "gametype")) {
        Fred.GameType = I(1);
    } else if (!strcmp(o, "event")) {
        TheRaceEventFields.Number = (int16_t)I(1);
        TheRaceEventFields.EventWord = I(2);
    } else if (!strcmp(o, "row")) {
        rows[I(1)].FinishReason = I(2);
    } else if (!strcmp(o, "reward")) {
        reward[0] = (uint8_t)I(1);
        reward[1] = (uint8_t)I(2);
        reward[2] = (uint8_t)I(3);
    } else if (!strcmp(o, "lastlap")) {
        lastlap.PackedTime = U(1);
    } else if (!strcmp(o, "best")) {
        best[0].Time.PackedTime = U(1);
    } else if (!strcmp(o, "randq")) {
        fill(&randq);
    } else if (!strcmp(o, "rand")) {
        randq.answer = U(1);
    } else if (!strcmp(o, "statusq")) {
        fill(&statusq);
    } else if (!strcmp(o, "status")) {
        statusq.answer = U(1);
    } else if (!strcmp(o, "wonq")) {
        fill(&wonq);
    } else if (!strcmp(o, "won")) {
        wonq.answer = U(1);
    } else if (!strcmp(o, "conv")) {
        const char *n = fields[1];
        int32_t v = I(2), r;

        if (!strcmp(n, "reward"))      r = speech_convert_reward_car_type(v);
        else if (!strcmp(n, "hpa"))    r = speech_convert_hp_event_a(v);
        else if (!strcmp(n, "hpb"))    r = speech_convert_hp_event_b(v);
        else if (!strcmp(n, "cha"))    r = speech_convert_championship_event_a(v);
        else if (!strcmp(n, "chb"))    r = speech_convert_championship_event_b(v);
        else if (!strcmp(n, "track"))  r = speech_convert_track_number(v);
        else                           r = speech_convert_unlock_track(v);
        printf("conv %s %d -> %d\n", n, (int)v, (int)r);
    } else if (!strcmp(o, "finished")) {
        printf("finished C%d %d\n", (int)I(1), (int)I(2));
        race_finished_speech(&cars[I(1)], I(2));
        flags();
    } else if (!strcmp(o, "lap")) {
        printf("lap C%d %d\n", (int)I(1), (int)I(2));
        lap_finished_speech(&cars[I(1)], I(2));
        flags();
    } else if (!strcmp(o, "lap1") || !strcmp(o, "lap2")) {
        DuringRaceSpeech d = { 0, 0, 0, 0 };

        if (!strcmp(o, "lap1"))
            one_player_lap_speech(&d, &cars[I(1)], I(2));
        else
            two_player_lap_speech(&d, &cars[I(1)], I(2));
        printf("%s C%d %d -> %x %x %x %x\n", o, (int)I(1), (int)I(2),
               (unsigned)d.TypeA, (unsigned)d.TypeB, (unsigned)d.TypeC,
               (unsigned)d.TypeD);
    } else if (!strcmp(o, "ko")) {
        printf("ko P%d %d\n", (int)I(1), (int)I(2));
        maybe_do_knockout_race_over_speech(player_at(I(1)), I(2));
        flags();
    } else if (!strcmp(o, "lapr") || !strcmp(o, "timer")) {
        printf("%s %d %d W%d\n", o, (int)I(1), (int)I(2), (int)I(3));
        if (!strcmp(o, "lapr"))
            post_game_lap_record(I(1), I(2), &rows[I(3)]);
        else
            post_game_time_record(I(1), I(2), &rows[I(3)]);
    } else if (!strcmp(o, "tour")) {
        printf("tour %d %d\n", (int)I(1), (int)I(2));
        tournament_race_speech(I(1), I(2));
    } else if (!strcmp(o, "evspeech")) {
        printf("evspeech P%d W%d\n", (int)I(1), (int)I(2));
        race_event_speech(player_at(I(1)), I(2) < 0 ? NULL : &rows[I(2)]);
        flags();
    } else if (!strcmp(o, "evreward")) {
        printf("evreward P%d %d %d\n", (int)I(1), (int)I(2), (int)I(3));
        race_event_reward_speech(player_at(I(1)), I(2),
                                 I(3) ? reward : NULL);
    } else if (!strcmp(o, "rcar")) {
        int32_t r = reward_car_speech(I(1));

        printf("rcar %d -> %d\n", (int)I(1), (int)r);
    } else if (!strcmp(o, "rtrack")) {
        int32_t r = reward_track_speech(I(1), I(2));

        printf("rtrack %d %d -> %d\n", (int)I(1), (int)I(2), (int)r);
    } else if (!strcmp(o, "points")) {
        printf("points %d\n", (int)I(1));
        points_screen_speech(I(1));
    } else if (!strcmp(o, "pullover")) {
        printf("pullover\n");
        pullover_speech();
    } else if (!strcmp(o, "arrest4")) {
        printf("arrest4 %d %d %d %d\n", (int)I(1), (int)I(2), (int)I(3),
               (int)I(4));
        be_a_cop_arrest_speech(I(1), I(2), I(3), I(4));
    } else if (!strcmp(o, "busted")) {
        printf("busted\n");
        play_busted_speech();
    } else {
        fprintf(stderr, "bad op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: racespeech_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCurrentRace = &race;
    gRaceEventGetStatusFn = get_status;
    gRaceEventUserWonFn = user_won;
    while (fgets(line, sizeof line, f) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        split(line);
        run();
    }
    fclose(f);
    return 0;
}
