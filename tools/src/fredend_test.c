// Drives fredend.c for tools/fredend_check.py. A script of ops, one per
// line, fields split on '|'. F is a database: 0 Fred, 1 a second one. A
// car, player, racing car, race or type of -1 is NULL.
//
//   fw|F|OFF|SIZE|V    a 1, 2 or 4 byte write into database F
//   rw|OFF|SIZE|V      the same into TheRaceParameters
//   pl|I|NUM|FIN|SCORE|N2540|CAR  player I's PlayerNumber,
//                      TimeFinishedRacing, TotalScore, New2540, MyCar
//   ps|I|OFF|V         byte OFF of player I's settings
//   players|N|BN0|BN1|BI0|BI1  Player's NumPlayers, pPlayersByNumber and
//                      pPlayersByIndex
//   car|I|DRV|CTI|PL|RC  car I's DriverNumber, type, Player, RacingCar
//   cti|I|BITS         type I's Control.SpeedLimiter
//   rc|I|CAR|POS|FIN|LAPS|LED|REASON|TIME|TOP|AVG  racing car I
//   rclap|I|K|V, rcbest|I|K|V  its LapTimes[K], BestRunningTimes[K]
//   race|W|N|FIN|RC0..RC7  race W's NumRacingCars,
//                      FinishLineBoundaryNumber and pRacingCars
//   cur|W              pCurrentRace race W
//   cop|ON|BITS        pCopManager, and its fBeACopTime
//   seed|V             bDefaultSeed
//   ans|TICKETS|BONUS|ALLFIN|EVR|EVU  what the stubs answer; the event
//                      trees' two answer bit (car & 31) of EVR and EVU
//   task|MIN|NP|GT|NO|NL|SK|LTL|COPS  task -1's tests
//
//   tse|F|K|RC         TransientStatsElement::Construct, F's row K
//   ts|F               TransientStats::Construct on F's, race 0
//   drv|F|D            GetDriver(D), printed as a row
//   opts|F, abort|F, leaving|F, over|F, quit|F, restarted|F
//   bonus|F|RC, award|F|RC   with race 0
//   aborted|F
//   tcc|T|RC           task T's CheckForCompletion, -1 the script's
//   tlist|RC, plist|PTS  the reward lists
//   ctpr               CheckForTaskAndPointRewards(race 0)
//   tunl|CAR|GT, punl|CAR, unl|CAR|GT  the unlocked tests
//
// After each op: the rows of 32 bytes that changed in the two databases
// (0 .. 1720 and 0x106b8 to the end) and in TheRaceParameters, and the
// seed when it moved. The stubs print what they are asked.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "endgame.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "hudscore.h"
#include "nfsrewards.h"
#include "player.h"
#include "race.h"
#include "racefinish.h"
#include "racerun.h"
#include "racesplit.h"

#define NUM_CARS 8
#define NUM_CTI  4

// What fredend.c reads that the linked files do not define.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
Race *pCurrentRace;
tCopManager *pCopManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
void (*gRaceEventKeepStateFn)(void);

static FrontendDatabase fed2;
static Race races[2];
static struct RacingCar rcs[NUM_CARS];
static Car cars[NUM_CARS];
static struct Player players[2];
static CarTypeInfo ctis[NUM_CTI];
static tCopManager copMem;
static NFSTaskParameters customTask;
static int32_t ansTickets, ansBonus, ansAllFin;
static uint32_t ansEvR, ansEvU;

static uint8_t prevFed[2][sizeof(FrontendDatabase)];
static uint8_t prevRp[sizeof(RaceParameters)];
static uint32_t prevSeed;

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static FrontendDatabase *fed(const char *s)
{
    return num(s) ? &fed2 : &Fred;
}

static int fed_index(const void *p)
{
    if (p == &Fred)
        return 0;
    if (p == &fed2)
        return 1;
    return -1;
}

static int car_index(const Car *c)
{
    return c == NULL ? -1 : (int)(c - cars);
}

static int rc_index(const struct RacingCar *rc)
{
    return rc == NULL ? -1 : (int)(rc - rcs);
}

static int player_index(const struct Player *p)
{
    return p == NULL ? -1 : (int)(p - players);
}

static int race_index(const Race *r)
{
    return r == NULL ? -1 : (int)(r - races);
}

static Car *car_at(int64_t i)
{
    return i < 0 ? NULL : &cars[i];
}

static struct RacingCar *rc_at(int64_t i)
{
    return i < 0 ? NULL : &rcs[i];
}

static struct Player *player_at(int64_t i)
{
    return i < 0 ? NULL : &players[i];
}

static void put(uint8_t *b, int64_t size, int64_t v)
{
    uint32_t u = (uint32_t)v;
    int64_t i;

    for (i = 0; i < size; i++)
        b[i] = (uint8_t)(u >> (8 * i));
}

static float flt(int64_t v)
{
    uint32_t u = (uint32_t)v;
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ------------------------------------------- the race's small methods
//
// As racerun.c, race.c and racesplit.c have them; racerun_check,
// racecore_check and racesplit_check check those.

struct Player *racingcar_get_player(const struct RacingCar *rc)
{
    if (rc->pCar == NULL)
        return NULL;
    return rc->pCar->pPlayer;
}

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    (void)r;
    return c->pRacingCar;
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    return &rc->BestRunningTimes[pCurrentRace->FinishLineBoundaryNumber];
}

// fredrace.c's, as fredrace_check checks it.
int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
}

// ------------------------------------------------------------ the stubs

int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c)
{
    printf("tickets %d car %d\n", m == &copMem, car_index(c));
    return ansTickets + car_index(c);
}

int32_t player_get_finish_bonus(struct Player *p, int32_t place)
{
    printf("finish bonus %d place %d\n", player_index(p), place);
    return ansBonus + place * 100;
}

int32_t race_are_all_players_finished_racing(const Race *r)
{
    printf("allfin %d\n", race_index(r));
    return ansAllFin;
}

void race_simulate_race_finish(Race *r)
{
    printf("simulate %d\n", race_index(r));
}

void race_notify_the_race_is_over(Race *r)
{
    printf("notify %d\n", race_index(r));
}

static void record(HighScoreTable *t, Race *r, struct RacingCar *rc)
{
    int f = t == &Fred.ChallengeHighScores ? 0
            : t == &fed2.ChallengeHighScores ? 1 : -1;

    printf("record %d race %d rc %d\n", f, race_index(r), rc_index(rc));
}

static void audio(uint8_t *ao, int32_t a)
{
    int f = ao == Fred.AudioOptionsScreenData ? 0
            : ao == fed2.AudioOptionsScreenData ? 1 : -1;

    printf("audio %d %d\n", f, a);
}

static void post(void)
{
    printf("post results\n");
}

static void discard(void)
{
    printf("discard results\n");
}

static void cycle(void)
{
    printf("cycle results\n");
}

static void keep(void)
{
    printf("keep state\n");
}

static int32_t ev_reward(int32_t car)
{
    printf("evreward %d\n", car);
    return (ansEvR >> (car & 31)) & 1;
}

static int32_t ev_unlock(int32_t car)
{
    printf("evunlock %d\n", car);
    return (ansEvU >> (car & 31)) & 1;
}

// ------------------------------------------------------------- the dump

static void dump_rows(const char *name, const uint8_t *now, uint8_t *prev,
                      size_t lo, size_t hi)
{
    size_t off, i;

    if (memcmp(now + lo, prev + lo, hi - lo) == 0)
        return;
    for (off = lo; off < hi; off += 32) {
        size_t n = hi - off < 32 ? hi - off : 32;

        if (memcmp(now + off, prev + off, n) == 0)
            continue;
        printf("  %s %05zx:", name, off);
        for (i = 0; i < n; i++)
            printf(" %02x", now[off + i]);
        printf("\n");
    }
    memcpy(prev + lo, now + lo, hi - lo);
}

static void dump(void)
{
    static const char *const names[2] = {"fred", "fed2"};
    const FrontendDatabase *f[2] = {&Fred, &fed2};
    int i;

    for (i = 0; i < 2; i++) {
        const uint8_t *b = (const uint8_t *)f[i];

        dump_rows(names[i], b, prevFed[i], 0, 1720);
        dump_rows(names[i], b, prevFed[i], 0x106b8, sizeof(FrontendDatabase));
    }
    dump_rows("rp", (const uint8_t *)&TheRaceParameters, prevRp, 0,
              sizeof(RaceParameters));
    if (bDefaultSeed != prevSeed) {
        printf("  seed %08x\n", (unsigned)bDefaultSeed);
        prevSeed = bDefaultSeed;
    }
}

static void print_row(const TransientStatsElement *e, const FrontendDatabase *f)
{
    if (e == NULL) {
        printf("  row none\n");
        return;
    }
    printf("  row %d of %d\n", fed_index(f),
           (int)(e - f->TransientStatsTable.Stats));
}

// -------------------------------------------------------------- the ops

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;

    if (argc < 2) {
        fprintf(stderr, "usage: fredend_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    gHighScoreMaybeRecordFn = record;
    gSetAudioDataFromSoundFn = audio;
    gRaceEventPostResultsFn = post;
    gRaceEventMaybeDiscardResultsFn = discard;
    gRaceEventCycleResultsFn = cycle;
    gRaceEventKeepStateFn = keep;
    gIsCarAnEventRewardFn = ev_reward;
    gEventTreeIsCarUnlockedFn = ev_unlock;
    pCurrentRace = &races[0];
    prevSeed = bDefaultSeed;

    while (fgets(line, sizeof line, sc)) {
        char *arg[24];
        const char *op;
        int n = 0;
        char *s = line;

        line[strcspn(line, "\r\n")] = 0;
        printf("> %s\n", line);
        while (n < 24) {
            arg[n++] = s;
            s = strchr(s, '|');
            if (s == NULL)
                break;
            *s++ = 0;
        }
        op = arg[0];

        if (strcmp(op, "fw") == 0) {
            put((uint8_t *)fed(arg[1]) + num(arg[2]), num(arg[3]), num(arg[4]));
        } else if (strcmp(op, "rw") == 0) {
            put((uint8_t *)&TheRaceParameters + num(arg[1]), num(arg[2]),
                num(arg[3]));
        } else if (strcmp(op, "pl") == 0) {
            struct Player *p = &players[num(arg[1])];

            p->PlayerNumber = (int32_t)num(arg[2]);
            p->TimeFinishedRacing = (uint32_t)num(arg[3]);
            p->TotalScore = (int32_t)num(arg[4]);
            p->New2540 = (int32_t)num(arg[5]);
            p->MyCar = car_at(num(arg[6]));
        } else if (strcmp(op, "ps") == 0) {
            ((uint8_t *)&players[num(arg[1])].PlayerSettings)[num(arg[2])] =
                (uint8_t)num(arg[3]);
        } else if (strcmp(op, "players") == 0) {
            PlayerNumPlayers = (int32_t)num(arg[1]);
            PlayerPlayersByNumber[0] = player_at(num(arg[2]));
            PlayerPlayersByNumber[1] = player_at(num(arg[3]));
            PlayerPlayersByIndex[0] = player_at(num(arg[4]));
            PlayerPlayersByIndex[1] = player_at(num(arg[5]));
        } else if (strcmp(op, "car") == 0) {
            Car *c = &cars[num(arg[1])];
            int64_t t = num(arg[3]);

            c->DriverNumber = (int16_t)num(arg[2]);
            c->pCarTypeInfo = t < 0 ? NULL : &ctis[t];
            c->pPlayer = player_at(num(arg[4]));
            c->pRacingCar = rc_at(num(arg[5]));
        } else if (strcmp(op, "cti") == 0) {
            ctis[num(arg[1])].Control.SpeedLimiter = flt(num(arg[2]));
        } else if (strcmp(op, "rc") == 0) {
            struct RacingCar *rc = &rcs[num(arg[1])];

            rc->pCar = car_at(num(arg[2]));
            rc->RacePosition = (int8_t)num(arg[3]);
            rc->FinishingOrder = (int8_t)num(arg[4]);
            rc->NumLapsCompleted = (int8_t)num(arg[5]);
            rc->NumLapsLed = (int16_t)num(arg[6]);
            rc->FinishReason = (int16_t)num(arg[7]);
            rc->RaceTime.PackedTime = (uint32_t)num(arg[8]);
            rc->TopSpeed = flt(num(arg[9]));
            rc->AverageSpeed = flt(num(arg[10]));
        } else if (strcmp(op, "rclap") == 0) {
            rcs[num(arg[1])].LapTimes[num(arg[2])].PackedTime =
                (uint32_t)num(arg[3]);
        } else if (strcmp(op, "rcbest") == 0) {
            rcs[num(arg[1])].BestRunningTimes[num(arg[2])].PackedTime =
                (uint32_t)num(arg[3]);
        } else if (strcmp(op, "race") == 0) {
            Race *r = &races[num(arg[1])];
            int i;

            r->NumRacingCars = (int32_t)num(arg[2]);
            r->FinishLineBoundaryNumber = (int8_t)num(arg[3]);
            for (i = 0; i < RACE_MAX_RACING_CARS; i++)
                r->pRacingCars[i] = rc_at(num(arg[4 + i]));
        } else if (strcmp(op, "cur") == 0) {
            pCurrentRace = &races[num(arg[1])];
        } else if (strcmp(op, "cop") == 0) {
            pCopManager = num(arg[1]) ? &copMem : NULL;
            copMem.fBeACopTime = flt(num(arg[2]));
        } else if (strcmp(op, "seed") == 0) {
            bDefaultSeed = (uint32_t)num(arg[1]);
        } else if (strcmp(op, "ans") == 0) {
            ansTickets = (int32_t)num(arg[1]);
            ansBonus = (int32_t)num(arg[2]);
            ansAllFin = (int32_t)num(arg[3]);
            ansEvR = (uint32_t)num(arg[4]);
            ansEvU = (uint32_t)num(arg[5]);
        } else if (strcmp(op, "task") == 0) {
            customTask.MinDamage = flt(num(arg[1]));
            customTask.NumPlayers = (int32_t)num(arg[2]);
            customTask.GameType = (int32_t)num(arg[3]);
            customTask.NumOpponents = (int32_t)num(arg[4]);
            customTask.NumLaps = (int32_t)num(arg[5]);
            customTask.SkillLevel = (int32_t)num(arg[6]);
            customTask.NumLapsToLead = (int32_t)num(arg[7]);
            customTask.Cops = (int32_t)num(arg[8]);
        } else if (strcmp(op, "tse") == 0) {
            FrontendDatabase *f = fed(arg[1]);

            transient_stats_element_construct(
                &f->TransientStatsTable.Stats[num(arg[2])], rc_at(num(arg[3])));
        } else if (strcmp(op, "ts") == 0) {
            transient_stats_construct(&fed(arg[1])->TransientStatsTable,
                                      &races[0]);
        } else if (strcmp(op, "drv") == 0) {
            FrontendDatabase *f = fed(arg[1]);

            print_row(transient_stats_get_driver(&f->TransientStatsTable,
                                                 (int32_t)num(arg[2])), f);
        } else if (strcmp(op, "opts") == 0) {
            fred_get_options_set_from_race(fed(arg[1]));
        } else if (strcmp(op, "bonus") == 0) {
            printf("  = %d\n", fred_figure_out_bonus_points(
                                   fed(arg[1]), &races[0], rc_at(num(arg[2]))));
        } else if (strcmp(op, "award") == 0) {
            fred_award_points_to_player(fed(arg[1]), &races[0],
                                        rc_at(num(arg[2])));
        } else if (strcmp(op, "abort") == 0) {
            fred_check_for_abortion(fed(arg[1]));
        } else if (strcmp(op, "aborted") == 0) {
            printf("  = %d\n", fred_race_was_aborted(fed(arg[1])));
        } else if (strcmp(op, "leaving") == 0) {
            fred_the_race_is_leaving(fed(arg[1]));
        } else if (strcmp(op, "over") == 0) {
            fred_the_race_is_over(fed(arg[1]), &races[0]);
        } else if (strcmp(op, "quit") == 0) {
            fred_the_race_was_quit(fed(arg[1]));
        } else if (strcmp(op, "restarted") == 0) {
            fred_the_race_was_restarted(fed(arg[1]));
        } else if (strcmp(op, "tcc") == 0) {
            int64_t t = num(arg[1]);

            printf("  = %d\n", nfs_task_check_for_completion(
                                   t < 0 ? &customTask : &NFSTasks[t],
                                   rc_at(num(arg[2]))));
        } else if (strcmp(op, "tlist") == 0) {
            const NFSTaskParameters *list[NFS_NUM_TASKS];
            int32_t k, cnt = -7;
            int32_t r = nfs_get_task_reward_list(list, &cnt, rc_at(num(arg[1])));

            printf("  = %d (%d):", r, cnt);
            for (k = 0; k < cnt; k++)
                printf(" %d", (int)(list[k] - NFSTasks));
            printf("\n");
        } else if (strcmp(op, "plist") == 0) {
            const NFSPointsRewards *list[NFS_NUM_POINTS_REWARDS];
            int32_t k, cnt = -7;
            int32_t r = nfs_get_points_reward_list(list, &cnt,
                                                   (int32_t)num(arg[1]));

            printf("  = %d (%d):", r, cnt);
            for (k = 0; k < cnt; k++)
                printf(" %d", (int)(list[k] - NFSPointsRewardsArray));
            printf("\n");
        } else if (strcmp(op, "ctpr") == 0) {
            nfs_check_for_task_and_point_rewards(&races[0]);
        } else if (strcmp(op, "tunl") == 0) {
            printf("  = %d\n", nfs_task_rewards_is_car_unlocked(
                                   (int32_t)num(arg[1]), (int32_t)num(arg[2])));
        } else if (strcmp(op, "punl") == 0) {
            printf("  = %d\n",
                   nfs_points_rewards_is_car_unlocked((int32_t)num(arg[1])));
        } else if (strcmp(op, "unl") == 0) {
            printf("  = %d\n", nfs_is_car_unlocked((int32_t)num(arg[1]),
                                                   (int32_t)num(arg[2])));
        } else {
            printf("  ? %s\n", op);
        }
        dump();
    }
    fclose(sc);
    return 0;
}
