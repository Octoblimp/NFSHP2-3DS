// racefinish -- see racefinish.h. Step 8f.
#include "racefinish.h"

#include <stddef.h>

#include "player.h"
#include "racerun.h"
#include "realtime.h"

void (*gRaceFinishCarFn)(Race *r, int32_t index, int32_t a, int32_t b,
                         eRaceFinishReason reason);
void (*gRaceEventRecordResultsFn)(Race *r, struct RacingCar *rc,
                                  int32_t position);

// GetCountdownNumberToDisplay's and GetCountdownProgress's count: the
// float at gp-31436 (and gp-31428), or 1.0 for the cop.
#define RACE_COUNT_SECONDS 0.9f
#define RACE_COP_COUNT_SECONDS 1.0f

// The GO stays up this many frames (`cvt.w.s` of 60.0).
#define RACE_GO_FRAMES 60

// gp-31432, gp-31424 and gp-31420: a frame, in seconds.
#define RACE_FRAME_SECONDS (1.0f / 60.0f)

// WorldTimeFrames since `t`, wrapping as `subu` does.
static int32_t frames_since(int32_t t)
{
    return (int32_t)((uint32_t)WorldTimeFrames - (uint32_t)t);
}

static float count_seconds(void)
{
    return RaceParametersBeACop ? RACE_COP_COUNT_SECONDS : RACE_COUNT_SECONDS;
}

int32_t race_get_countdown_number_to_display(const Race *r)
{
    float count = count_seconds();

    if (r->StartGoTimeFrames != 0)
        return RACE_GO_FRAMES < frames_since(r->StartGoTimeFrames) ? 0 : 4;
    if (r->StartCountdownTimeFrames != 0) {
        float t = (float)frames_since(r->StartCountdownTimeFrames)
                  * RACE_FRAME_SECONDS;

        if (t < count)
            return 3;
        if (t < count + count)
            return 2;
        if (!(t < count * 3.0f))
            return 4;
        return 1;
    }
    return 0;
}

float race_get_countdown_progress(const Race *r)
{
    float count = count_seconds();
    float total = count * 4.0f;
    float t = 0.0f;

    if (r->StartGoTimeFrames != 0)
        t = count * 3.0f
            + (float)frames_since(r->StartGoTimeFrames) * RACE_FRAME_SECONDS;
    else if (r->StartCountdownTimeFrames != 0)
        t = (float)frames_since(r->StartCountdownTimeFrames)
            * RACE_FRAME_SECONDS;
    return t / total;
}

void race_simulate_race_finish(Race *r)
{
    int32_t n = r->NumRacingCars;
    int32_t i;

    for (i = 0; i < n; i++) {
        if (r->pRacingCars[i]->FinishReason != RACING_CAR_NOT_FINISHED)
            continue;
        if (gRaceFinishCarFn != NULL)
            gRaceFinishCarFn(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);
        n = r->NumRacingCars;
    }
    race_sort_racing_cars_by_leadership(r);
}

void race_notify_the_race_is_over(Race *r)
{
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];

        if (gRaceEventRecordResultsFn != NULL)
            gRaceEventRecordResultsFn(r, rc, rc->RacePosition);
    }
}

int32_t race_are_all_players_finished_racing(const Race *r)
{
    int32_t n = PlayerNumPlayers;
    int32_t i;

    (void)r;
    for (i = 0; i < n; i++) {
        if (PlayerPlayersByIndex[i]->TimeFinishedRacing == 0)
            return 0;
    }
    return 1;
}

struct Player *race_get_most_recently_finished_player(const Race *r)
{
    int32_t n = PlayerNumPlayers;
    int32_t best = 0;
    struct Player *latest = NULL;
    int32_t i;

    (void)r;
    for (i = 0; i < n; i++) {
        struct Player *p = PlayerPlayersByIndex[i];
        int32_t t = (int32_t)p->TimeFinishedRacing;

        if (t != 0 && best < t) {
            best = t;
            latest = p;
        }
    }
    return latest;
}
