// carevents -- retail's Car::TriggerEvents (0x001335c0, 580 bytes) and the
// Player method it calls, Player::TriggerVisibleDrivingLine (0x00180b78).
//
// World::DoTimestep calls TriggerEvents for every car within 100 of a
// player (worldstep.c, through gCarTriggerEventsFn). The point it asks the
// event manager about is a little ahead of the car: GeometryPosition plus
// 0.15 s of its velocity. For each trigger that point is inside:
//
//   - a bush (TRIGGER_EVENT_CAR_ON_FERN): FlattenFern, which is empty, and
//     ShakeFern with the car's velocity. For a player's car going over 30,
//     every fourth loop, the replay hears of it.
//   - a driving line (TRIGGER_EVENT_VIEW_DRIVING_LINE): the player's
//     training line is shown when the trigger's direction byte is the
//     race's, the car goes over 40 and the player is not going the wrong
//     way.
//
// Any other event is taken off the queue at once. The two above stay on it
// for emProcessAllEvents.
//
// A file of its own because it reaches the event manager, the fern
// shaker, the Player, the race and the replay, which car.c's checkers do
// not link. Prototypes: car.h. Cross-check: tools/eventmgr_check.py.
// Write-up: docs/formats/event-manager.md.

#include <stddef.h>
#include <stdint.h>

#include "bmem.h"
#include "car.h"
#include "carstate.h"
#include "eventmgr.h"
#include "fernshaker.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "replay.h"

VisibleDrivingLineCtorFn gVisibleDrivingLineCtorFn;

// gp-31928: how far ahead of the car, in seconds of its velocity, the
// triggers are looked for.
static const float CarEventLookAhead = 0.15f;

// The image calls RegisterInterestingEvent on pReplayManager as it is;
// the port's ReplayManager may not be made yet, as in carfinish.c.
static void interesting(float value, const char *what)
{
    if (pReplayManager != NULL)
        ReplayManager_RegisterInterestingEvent(pReplayManager, value, what);
}

void player_trigger_visible_driving_line(Player *p, int32_t line,
                                         float seconds)
{
    void *mem;

    if (!TheRaceParameters.TrainingLinesEnabled)
        return;
    if (pRaceCoordinator->CurrentRCState != RCSTATE_RACE_IN_PROGRESS)
        return;
    if (p->pVisibleDrivingLine != NULL)
        return;
    if (seconds == 0.0f)
        seconds = 5.0f;
    // `new VisibleDrivingLine(this, line, seconds)`, with no test of the
    // block. The line is not ported: without its constructor the port
    // makes nothing, and takes no memory for it.
    if (gVisibleDrivingLineCtorFn == NULL)
        return;
    mem = bMalloc(VISIBLE_DRIVING_LINE_SIZE, "VisibleDrivingLine", 0, 16);
    p->pVisibleDrivingLine = gVisibleDrivingLineCtorFn(mem, p, line, seconds);
}

// The direction byte: 0 for a forward trigger, anything else for a
// backward one. A race in any other direction sees neither.
static int32_t driving_line_matches(uint32_t parameter)
{
    int32_t backward = (parameter & 0xffu) != 0;

    switch (TheRaceParameters.TrackDirection) {
    case TRACK_DIRECTION_FORWARD:
        return !backward;
    case TRACK_DIRECTION_BACKWARD:
        return backward;
    default:
        return 0;
    }
}

void car_trigger_events(Car *c)
{
    CarState *st = &c->State;
    bVector3  at;
    emEvent **events;

    // The image copies the body matrix to the stack with GeometryPosition
    // as its last row and reads only that row back.
    at.x = st->GeometryPosition.x + st->Velocity.x * CarEventLookAhead;
    at.y = st->GeometryPosition.y + st->Velocity.y * CarEventLookAhead;
    at.z = st->GeometryPosition.z + st->Velocity.z * CarEventLookAhead;
    at.pad = 0.0f;
    events = em_trigger_events(&at);
    if (events == NULL)
        return;
    for (; *events != NULL; events++) {
        emEvent *e = *events;

        if (e->ID == TRIGGER_EVENT_CAR_ON_FERN) {
            uint32_t code = e->pEventTrigger->Parameter;

            flatten_fern(code);
            shake_fern(code, &st->Velocity);
            if (c->pPlayer != NULL && ((WorldLoopCounter + 3) & 3) == 0
                && 30.0f < st->VelocityMagnitude)
                interesting(2.0f, "FlattenFern");
        } else if (e->ID == TRIGGER_EVENT_VIEW_DRIVING_LINE) {
            Player  *p = c->pPlayer;
            uint32_t parameter;

            if (p == NULL)
                continue;
            parameter = e->pEventTrigger->Parameter;
            if (driving_line_matches(parameter)
                && 40.0f < st->VelocityMagnitude && p->bWrongWay == 0)
                player_trigger_visible_driving_line(
                    p, (int32_t)(parameter >> 16),
                    (float)(int32_t)((parameter >> 8) & 0xffu));
        } else {
            em_remove_event(e);
        }
    }
}
