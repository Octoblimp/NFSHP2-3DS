// rcdemo -- the race coordinator's demo states. TASKS 72h-2b; rcdemo.h has
// the map and docs/formats/replay.md the decode.
#include "rcdemo.h"

#include <stddef.h>

#include "demomode.h"
#include "dmreplay.h"
#include "fred.h"
#include "joyevent.h"
#include "playercam.h"
#include "race.h"
#include "rcpost.h"
#include "rcstates.h"
#include "replay.h"
#include "replaymgr.h"
#include "trackflow.h"

// gp-31380: a race Timer tick in seconds.
#define SECONDS_PER_TICK 0.00025f

// Both ports' skip.
#define RC_DEMO_PORTS 2

// ---------------------------------------------------------- the helpers

static void screen_visibility(uint32_t screen, int visibility)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, visibility);
}

// The overlay up, the skip on both ports and the demo camera made.
static void demo_activate(RaceCoordinator *rc)
{
    JoystickPort port;

    screen_visibility(RC_DEMO_SCREEN, 0);
    for (port = 0; port < RC_DEMO_PORTS; port++)
        AddJoyHandler(port, JOY_EVENT_SKIP_DEMO_MODE,
                      racecoordinator_joystick_handler, rc);
    racecoordinator_resume_demo_cameras(rc);
}

// The overlay down, the skip taken away and the demo camera deleted.
static void demo_unactivate(RaceCoordinator *rc)
{
    JoystickPort port;

    screen_visibility(RC_DEMO_SCREEN, 1);
    for (port = 0; port < RC_DEMO_PORTS; port++)
        RemoveJoyHandler(port, JOY_EVENT_SKIP_DEMO_MODE);
    if (rc->pDemoCameraCoordinator != NULL
        && gCameraCoordinatorDeleteFn != NULL)
        gCameraCoordinatorDeleteFn(rc->pDemoCameraCoordinator);
    rc->pDemoCameraCoordinator = NULL;
}

// Out of the race: QUIT_RACE sent on once the state is NONE, which takes it.
static void quit_race(RaceCoordinator *rc)
{
    racecoordinator_change_state(rc, RCSTATE_NONE);
    racecoordinator_send_message(rc, RC_QUIT_RACE, 0);
}

static void end_demo(RaceCoordinator *rc, int32_t status)
{
    Fred.DemoModeStatus = status;
    quit_race(rc);
}

// The race's time in seconds. Retail reads pCurrentRace unchecked; with
// none, the low memory a NULL reads, which is 0.
static float race_seconds(void)
{
    if (pCurrentRace == NULL)
        return 0.0f;
    return (float)(int32_t)pCurrentRace->RaceTime.PackedTime
           * SECONDS_PER_TICK;
}

// ------------------------------------------------------ RCSTATE_AI_DEMO_MODE

int32_t rc_state_ai_demo_mode_callback(RaceCoordinator *rc, RCMessage msg,
                                       int32_t param)
{
    (void)param;
    switch (msg) {
    case RC_ACTIVATE:
        demo_activate(rc);
        return 1;
    case RC_UNACTIVATE:
        demo_unactivate(rc);
        return 1;
    case RC_TICK:
        if (DemoModeTimeout < race_seconds())
            end_demo(rc, DEMO_MODE_TIMEDOUT);
        return 1;
    case RC_SKIP:
        end_demo(rc, DEMO_MODE_SKIPPED);
        return 1;
    case RC_QUIT_RACE:
        quit_race(rc);
        return 1;
    case RC_TAKE_AUTOSNAPSHOT:
        return 1;
    default:
        return 0;
    }
}

// -------------------------------------------------- RCSTATE_REPLAY_DEMO_MODE

int32_t rc_state_replay_demo_mode_callback(RaceCoordinator *rc,
                                           RCMessage msg, int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        dmreplay_begin_demo_mode();
        demo_activate(rc);
        return 1;
    case RC_UNACTIVATE:
        demo_unactivate(rc);
        dmreplay_end_demo_mode();
        if (gRestoreTypeChangedHandlersFn != NULL)
            gRestoreTypeChangedHandlersFn();
        return 1;
    case RC_TICK:
        if (!dmreplay_test_goes_on())
            end_demo(rc, DEMO_MODE_TIMEDOUT);
        return 1;
    case RC_SKIP:
    case RC_SKIP_REPLAY:
        end_demo(rc, DEMO_MODE_SKIPPED);
        return 1;
    case RC_QUIT_RACE:
        quit_race(rc);
        return 1;
    case RC_TAKE_AUTOSNAPSHOT:
        return 1;
    case RC_MOVE_REPLAY:
        replaymgr_restore_snapshot(pReplayManager,
                                   (ReplaySnapshot *)(intptr_t)param);
        racecoordinator_suspend_demo_cameras(rc);
        racecoordinator_resume_demo_cameras(rc);
        return 1;
    default:
        return 0;
    }
}
