// playerfinish -- see playerfinish.h. Step 11g-2b.

#include "playerfinish.h"

#include <math.h>
#include <stddef.h>

#include "car.h"
#include "player.h"
#include "race.h"
#include "racefinish.h"
#include "realtime.h"
#include "replay.h"

void (*gSpeechClearEventQueueFn)(void);
void (*gTriggerFinishLineSoundFn)(struct Player *p);

// The finish animation's length, in frames.
#define FINISH_ANIMATION_FRAMES 360

// A car this near (`lui 0x41f0`, 30 m) adds to the finish's replay event.
#define FINISH_NEAR 30.0f

// `vsub.xyzw ; vmul.xyz ; vaddy.x ; vaddz.x ; sqrt.s`, of a - b.
static float distance(const bVector3 *a, const bVector3 *b)
{
    float dx = a->x - b->x;
    float dy = a->y - b->y;
    float dz = a->z - b->z;

    return sqrtf((dx * dx + dy * dy) + dz * dz);
}

// The racing cars within 30 m of `car`, the car itself among them.
static int32_t cars_near(const Race *r, const Car *car)
{
    int32_t n = 0;
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        const Car *other = r->pRacingCars[i]->pCar;

        if (distance(&car->State.Position, &other->State.Position)
            < FINISH_NEAR)
            n++;
    }
    return n;
}

void player_set_finished_racing(struct Player *p)
{
    const struct RacingCar *rc;

    if (p->TimeFinishedRacing != 0)
        return;
    p->TimeFinishedRacing = (uint32_t)WorldTimeFrames;
    rc = p->MyCar->pRacingCar;
    if (rc->NumLapsCompleted == pCurrentRace->NumLapsInRace) {
        // RegisterInterestingEvent on pReplayManager, unchecked in the
        // image; the port tests it, as carfinish.c does.
        if (TheRaceParameters.BeACop == 0 && pReplayManager != NULL)
            ReplayManager_RegisterInterestingEvent(
                pReplayManager,
                ((float)cars_near(pCurrentRace, rc->pCar) - 1.0f) * 7.5f
                    + 10.0f,
                "CrossFinishLine");
        if (race_are_all_players_finished_racing(pCurrentRace)
            && gSpeechClearEventQueueFn != NULL)
            gSpeechClearEventQueueFn();
        if (gTriggerFinishLineSoundFn != NULL)
            gTriggerFinishLineSoundFn(p);
    }
    p->FinishAnimationLength = FINISH_ANIMATION_FRAMES;
}
