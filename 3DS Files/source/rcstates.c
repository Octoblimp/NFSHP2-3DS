// rcstates -- the race coordinator's states up to the finish. Step 8f;
// rcstates.h has the map and docs/formats/race-coordinator.md the decode.
#include "rcstates.h"

#include <stddef.h>

#include "bmem.h"
#include "car.h"
#include "eefpu.h"
#include "gameflow.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "racefinish.h"
#include "racerun.h"
#include "rcauto.h"
#include "rcpost.h"
#include "rcreplay.h"
#include "realtime.h"
#include "replay.h"
#include "trackflow.h"
#include "world.h"

// The pool and the file every allocation here names.
#define RC_POOL 16
static const char kRCFile[] = "..\\indep\\src\\racecoordinator.cpp";
#define RC_FLYBY_LINE    1289
#define RC_PRERACE_LINE  1378
#define RC_DEMO_LINE     1082

static const char kPreRaceAnim[] = "GLOBAL\\PRERACEANIM.LZC";

// gp-31376: the GO's sample plays below this progress.
#define RC_GO_SAMPLE_BEFORE 0.8f

// gp-31384, which RESTART_RACE stores in the jukebox's delayed start.
#define RC_MUSIC_NEVER 8999999488.0f

// The delayed start the TICK gives the music once the race is RACING.
#define RC_MUSIC_DELAY 6.0f

// A Timer not yet set (`lui 0x7fff; ori 0xffff`), or 0.
#define RC_TIMER_UNSET 0x7fffffff

RCStateCallbackFn gRCStateCallbacks[NUM_RCSTATES] = {
    [RCSTATE_NONE]             = rc_state_none_callback,
    [RCSTATE_CAMERA_FLYBY]     = rc_state_camera_flyby_callback,
    [RCSTATE_PRERACE]          = rc_state_prerace_callback,
    [RCSTATE_RACE_IN_PROGRESS] = rc_state_race_in_progress_callback,
    [RCSTATE_INSTANT_REPLAY]   = rc_state_instant_replay_callback,
    [RCSTATE_AUTO_REPLAY]      = rc_state_auto_replay_callback,
    [RCSTATE_PAUSE]            = rc_state_pause_callback,
    [RCSTATE_POSTRACE]         = rc_state_post_race_callback,
};

void (*gSoundMuteFn)(int32_t on);
void (*gFEDSetupNextRaceFn)(void);
void (*gFEDSetRecordTimesToBeatFn)(int32_t player);
void (*gFEDCheckForAbortionFn)(void);
void (*gFEDTheRaceIsOverFn)(Race *r);
int32_t (*gFEDIsThereAnotherRaceFn)(void);
int32_t (*gFEDIsMultiTrackFn)(void);
const tGlobalDisplaySettings *gFEDGlobalDisplaySettings;
void (*gJukeboxDelayedStartFn)(float seconds);
float *gJukeboxDelayedStartTimer;
void (*gChangeGameFlowFn)(int32_t desired, int32_t pending);
void *(*gFlyByCameraCoordinatorCtorFn)(void *mem, int32_t a);
void *(*gPreRaceCameraCoordinatorCtorFn)(void *mem, int32_t a);
void *(*gDemoCameraCoordinatorCtorFn)(void *mem, int32_t a, struct Car *car);
int32_t (*gFlyByCameraIsFinishedFn)(void *coord);
int32_t (*gPreRaceCameraIsFinishedFn)(void *coord);
void (*gEnableStartRaceScreensFn)(void);
void (*gDisableStartRaceScreensFn)(void);
void (*gAnimatedDriverCancelAllAnimationsFn)(struct AnimatedDriver *d);
int32_t (*gReplayGetBeginningOfTimeFn)(const struct ReplayManager *rm);
void (*gReplayMarkTheBeginningOfTimeFn)(struct ReplayManager *rm);
void (*gReplayMarkTheEndOfTimeFn)(struct ReplayManager *rm);
void (*gPlayerBeginDemoCamerasFn)(struct Player *p, struct Car *car);
struct EndGameScreens *(*gEndGameScreensCtorFn)(void *mem,
                                                eContinueRaceType type);
int32_t (*gSampleIsPlayingFn)(struct bSample *s);
void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);
int32_t (*gFlailerObjectVisibilityFn)(struct FlailerObjectChunk *o);
void (*gFlailerSetVisibilityFn)(uint32_t screen, uint32_t object,
                                int32_t visibility);
void (*gFlailerSetAlphaFn)(uint32_t screen, uint32_t object, int32_t alpha);
void (*gFlailerScaleAboutCenterFn)(uint32_t screen, uint32_t object,
                                   float scale);

// ---------------------------------------------------------- the helpers

static void delete_camera(void *coord)
{
    if (gCameraCoordinatorDeleteFn != NULL)
        gCameraCoordinatorDeleteFn(coord);
}

static void screen_visibility(uint32_t screen, int visibility)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, visibility);
}

static struct bSample *in_game_sample(const char *name)
{
    return gGetInGameSampleFn != NULL ? gGetInGameSampleFn(name) : NULL;
}

static void play_sample(struct bSample *s)
{
    if (gSamplePlayFn != NULL)
        gSamplePlayFn(s, 1.0f, 0.0f, 0.0f);
}

// REQUEST_PAUSE in the flyby, the prerace and the race: the port that
// asked and the state to come back to, then PAUSE.
static void request_pause(RaceCoordinator *rc, int32_t port)
{
    rc->PausedJoystickPort = port;
    rc->BeforePauseRCState = rc->CurrentRCState;
    racecoordinator_change_state(rc, RCSTATE_PAUSE);
}

// 0x001842a8, FrontendDatabase's, which has no symbol: SetRecordTimesToBeat
// for each player car, the count re-read every pass.
static void fed_set_all_record_times_to_beat(void)
{
    int32_t i;

    for (i = 0; i < RaceParametersNumPlayerCars; i++) {
        if (gFEDSetRecordTimesToBeatFn != NULL)
            gFEDSetRecordTimesToBeatFn(i);
    }
}

// The eight bytes RESTART_RACE and NEXT_RACE copy, `ldl/ldr` and
// `sdl/sdr`.
static void copy_display_settings(void)
{
    if (gFEDGlobalDisplaySettings != NULL)
        RaceParametersGlobalDisplaySettings = *gFEDGlobalDisplaySettings;
}

static void change_game_flow(int32_t desired, int32_t pending)
{
    if (gChangeGameFlowFn != NULL)
        gChangeGameFlowFn(desired, pending);
}

// ------------------------------------------------------------- RCSTATE_NONE

int32_t rc_state_none_callback(RaceCoordinator *rc, RCMessage msg,
                               int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
    case RC_UNACTIVATE:
    case RC_TICK:
        return 1;
    case RC_RESTART_RACE:
        racecoordinator_cleanup_after_race(rc);
        racecoordinator_init_for_race(rc);
        if (gSoundMuteFn != NULL)
            gSoundMuteFn(0);
        fed_set_all_record_times_to_beat();
        copy_display_settings();
        if (gJukeboxDelayedStartTimer != NULL)
            *gJukeboxDelayedStartTimer = RC_MUSIC_NEVER;
        return 1;
    case RC_NEXT_RACE:
        if (param != 0 && gFEDSetupNextRaceFn != NULL)
            gFEDSetupNextRaceFn();
        fed_set_all_record_times_to_beat();
        copy_display_settings();
        change_game_flow(BGF_UNLOADING_TRACK_SPECIFIC,
                         BGF_LOADING_TRACK_SPECIFIC);
        return 1;
    case RC_QUIT_RACE:
        // Retail asks DemoDiscManager first, and an active demo disc ends
        // its attract mode instead. It is never active on the retail disc.
        change_game_flow(BGF_UNLOADING_TRACK_SPECIFIC, BGF_NONE);
        return 1;
    default:
        return 0;
    }
}

// ----------------------------------------------------- RCSTATE_CAMERA_FLYBY

int32_t rc_state_camera_flyby_callback(RaceCoordinator *rc, RCMessage msg,
                                       int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        if (rc->pFlyByCameraCoordinator == NULL
            && gFlyByCameraCoordinatorCtorFn != NULL) {
            void *mem = bMalloc(FLYBY_CAMERA_COORDINATOR_SIZE, kRCFile,
                                RC_FLYBY_LINE, RC_POOL);

            rc->pFlyByCameraCoordinator = gFlyByCameraCoordinatorCtorFn(mem, 1);
        }
        if (gEnableStartRaceScreensFn != NULL)
            gEnableStartRaceScreensFn();
        return 1;
    case RC_UNACTIVATE:
        if (gDisableStartRaceScreensFn != NULL)
            gDisableStartRaceScreensFn();
        return 1;
    case RC_TICK:
        if (rc->pFlyByCameraCoordinator != NULL
            && gFlyByCameraIsFinishedFn != NULL
            && !gFlyByCameraIsFinishedFn(rc->pFlyByCameraCoordinator))
            return 1;
        // Retail tests BeACop here and does the same on both branches.
        race_set_race_stage(pCurrentRace, RACE_STAGE_PRERACE);
        racecoordinator_change_state(rc, RCSTATE_PRERACE);
        return 1;
    case RC_SKIP:
        race_set_race_stage(pCurrentRace, RACE_STAGE_PRERACE);
        racecoordinator_change_state(rc, RCSTATE_PRERACE);
        return 1;
    case RC_REQUEST_PAUSE:
        request_pause(rc, param);
        return 1;
    default:
        return 0;
    }
}

// ---------------------------------------------------------- RCSTATE_PRERACE

int32_t rc_state_prerace_callback(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        if (rc->pPreRaceCameraCoordinator == NULL
            && gPreRaceCameraCoordinatorCtorFn != NULL) {
            void *mem = bMalloc(PRERACE_CAMERA_COORDINATOR_SIZE, kRCFile,
                                RC_PRERACE_LINE, RC_POOL);

            rc->pPreRaceCameraCoordinator =
                gPreRaceCameraCoordinatorCtorFn(mem, 1);
        }
        if (rc->pFlyByCameraCoordinator != NULL) {
            delete_camera(rc->pFlyByCameraCoordinator);
            rc->pFlyByCameraCoordinator = NULL;
        }
        return 1;
    case RC_UNACTIVATE: {
        World *w = pCurrentWorld;
        CarNode *n = (CarNode *)w->CarList.next;
        void *f;

        // The World is re-read after each call.
        while ((void *)n != (void *)&w->CarList) {
            Car *c = (Car *)n;

            if (c->pAnimatedDriver != NULL) {
                if (gAnimatedDriverCancelAllAnimationsFn != NULL)
                    gAnimatedDriverCancelAllAnimationsFn(c->pAnimatedDriver);
                w = pCurrentWorld;
            }
            n = c->Link.next;
        }
        f = gFindResourceFileByNameFn != NULL
                ? gFindResourceFileByNameFn(kPreRaceAnim) : NULL;
        if (f != NULL && gUnloadResourceFileFn != NULL)
            gUnloadResourceFileFn(f);
        return 1;
    }
    case RC_TICK:
        if (race_get_race_stage(pCurrentRace) != RACE_STAGE_PRERACE)
            return 1;
        if (rc->pPreRaceCameraCoordinator != NULL
            && gPreRaceCameraIsFinishedFn != NULL
            && !gPreRaceCameraIsFinishedFn(rc->pPreRaceCameraCoordinator))
            return 1;
        race_set_race_stage(pCurrentRace, RACE_STAGE_COUNTDOWN);
        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);
        return 1;
    case RC_SKIP:
        race_set_race_stage(pCurrentRace, RACE_STAGE_COUNTDOWN);
        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);
        return 1;
    case RC_REQUEST_PAUSE:
        request_pause(rc, param);
        return 1;
    default:
        return 0;
    }
}

// -------------------------------------------------- RCSTATE_RACE_IN_PROGRESS

// Whether the player has finished and its finish animation has run.
static int finish_shown(const struct Player *p)
{
    return (int32_t)(p->TimeFinishedRacing + p->FinishAnimationLength)
           < WorldTimeFrames;
}

static void race_in_progress_tick(RaceCoordinator *rc)
{
    struct ReplayManager *rm = pReplayManager;
    int32_t n, i;

    racecoordinator_display_countdown_number(
        rc, race_get_countdown_number_to_display(pCurrentRace));
    if (rm != NULL && gReplayGetBeginningOfTimeFn != NULL) {
        int32_t begun = gReplayGetBeginningOfTimeFn(rm);

        // bCountFreeMemory(16) between the two is unused.
        if ((begun == 0 || begun == RC_TIMER_UNSET)
            && race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING) {
            if (gReplayMarkTheBeginningOfTimeFn != NULL)
                gReplayMarkTheBeginningOfTimeFn(rm);
            if (gJukeboxDelayedStartFn != NULL)
                gJukeboxDelayedStartFn(RC_MUSIC_DELAY);
        }
    }

    // With no players all have finished and none is the latest; retail
    // reads the NULL player's times there.
    if (race_are_all_players_finished_racing(pCurrentRace)) {
        struct Player *last =
            race_get_most_recently_finished_player(pCurrentRace);

        if (last != NULL && finish_shown(last))
            racecoordinator_the_race_has_finished(rc);
    }

    // With two players, one who has finished watches the other's car.
    n = PlayerNumPlayers;
    if (n < 2)
        return;
    for (i = 0; i < n; i++) {
        struct Player *p = PlayerPlayersByIndex[i];
        int all;
        int32_t j;

        if (p->TimeFinishedRacing == 0 || !finish_shown(p))
            continue;
        all = race_are_all_players_finished_racing(pCurrentRace);
        n = PlayerNumPlayers;
        if (all)
            continue;
        for (j = 0; j < n; j++) {
            struct Player *q;

            if (j == i)
                continue;
            q = PlayerPlayersByIndex[j];
            if (q->TimeFinishedRacing == 0) {
                if (gPlayerBeginDemoCamerasFn != NULL)
                    gPlayerBeginDemoCamerasFn(p, q->MyCar);
                n = PlayerNumPlayers;
                break;
            }
        }
    }
}

int32_t rc_state_race_in_progress_callback(RaceCoordinator *rc,
                                           RCMessage msg, int32_t param)
{
    switch (msg) {
    case RC_ACTIVATE:
        if (rc->pPreRaceCameraCoordinator != NULL) {
            delete_camera(rc->pPreRaceCameraCoordinator);
            rc->pPreRaceCameraCoordinator = NULL;
        }
        return 1;
    case RC_UNACTIVATE:
        racecoordinator_display_countdown_number(rc, 0);
        return 1;
    case RC_TICK:
        race_in_progress_tick(rc);
        return 1;
    case RC_SKIP:
        if (race_are_all_players_finished_racing(pCurrentRace))
            racecoordinator_the_race_has_finished(rc);
        return 1;
    case RC_REQUEST_PAUSE:
        request_pause(rc, param);
        return 1;
    case RC_REQUEST_AUTO_REPLAY:
        racecoordinator_change_state(rc, RCSTATE_AUTO_REPLAY);
        return 1;
    case RC_NEXT_RACE:
        racecoordinator_change_state(rc, RCSTATE_NONE);
        racecoordinator_send_message(rc, RC_NEXT_RACE, param);
        return 1;
    case RC_TAKE_AUTOSNAPSHOT:
        return 1;
    default:
        return 0;
    }
}

// ------------------------------------------------------ the countdown

// Animate321GoElement (0x0014b108): before `start` the number is hidden.
// From it the number shows, fading in and shrinking from four times its
// size over the first sixth of its window, with the "CountDownLow" sample
// as it appears.
static void animate_321_go_element(float start, float end, float progress,
                                   uint32_t screen, uint32_t object)
{
    struct FlailerObjectChunk *o;
    float t;

    if (!(start < progress)) {
        if (gFlailerSetVisibilityFn != NULL)
            gFlailerSetVisibilityFn(screen, object, 0);
        return;
    }
    t = 1.0f;
    if (progress < end)
        t = (progress - start) / (end - start);
    t = t * 6.0f;
    if (1.0f < t)
        t = 1.0f;
    o = gFindFlailerObjectFn != NULL ? gFindFlailerObjectFn(screen, object, 0)
                                     : NULL;
    if (o != NULL && gFlailerObjectVisibilityFn != NULL
        && gFlailerObjectVisibilityFn(o) == 0) {
        struct bSample *s = in_game_sample("CountDownLow");

        if (s != NULL)
            play_sample(s);
    }
    if (gFlailerSetVisibilityFn != NULL)
        gFlailerSetVisibilityFn(screen, object, 1);
    if (gFlailerSetAlphaFn != NULL)
        gFlailerSetAlphaFn(screen, object, ee_trunc_w(t * 128.0f));
    if (gFlailerScaleAboutCenterFn != NULL)
        gFlailerScaleAboutCenterFn(screen, object, t * -3.0f + 4.0f);
}

void racecoordinator_display_countdown_number(RaceCoordinator *rc,
                                              int32_t n)
{
    float progress = race_get_countdown_progress(pCurrentRace);

    (void)rc;
    if (n == 4 && progress < RC_GO_SAMPLE_BEFORE) {
        struct bSample *s = in_game_sample("CountDownHigh");

        if (s != NULL
            && !(gSampleIsPlayingFn != NULL && gSampleIsPlayingFn(s)))
            play_sample(s);
    }
    if (1.0f < progress || n == 0 || n == 4) {
        screen_visibility(RC_COUNTDOWN_SCREEN, 1);
        return;
    }
    screen_visibility(RC_COUNTDOWN_SCREEN, 0);
    animate_321_go_element(0.0f, 0.25f, progress, RC_COUNTDOWN_SCREEN,
                           RC_COUNTDOWN_3);
    animate_321_go_element(0.25f, 0.5f, progress, RC_COUNTDOWN_SCREEN,
                           RC_COUNTDOWN_2);
    animate_321_go_element(0.5f, 0.75f, progress, RC_COUNTDOWN_SCREEN,
                           RC_COUNTDOWN_1);
}

// --------------------------------------------------------- the finish

void racecoordinator_the_race_has_finished(RaceCoordinator *rc)
{
    eContinueRaceType next;

    if (pReplayManager != NULL && gReplayMarkTheEndOfTimeFn != NULL)
        gReplayMarkTheEndOfTimeFn(pReplayManager);
    if (gFEDCheckForAbortionFn != NULL)
        gFEDCheckForAbortionFn();
    race_simulate_race_finish(pCurrentRace);
    race_notify_the_race_is_over(pCurrentRace);
    if (gFEDTheRaceIsOverFn != NULL)
        gFEDTheRaceIsOverFn(pCurrentRace);
    if (gFEDIsThereAnotherRaceFn != NULL && gFEDIsThereAnotherRaceFn())
        next = CONTINUE_RACE_TYPE_NEXT_RACE;
    else if (gFEDIsMultiTrackFn != NULL && gFEDIsMultiTrackFn())
        next = CONTINUE_RACE_TYPE_NONE;
    else
        next = CONTINUE_RACE_TYPE_RESTART;
    // Retail's active demo disc ends here instead (SetEndReason,
    // ChangeState(NONE), SendMessage(QUIT_RACE)). Not on the retail disc.
    if (gEndGameScreensCtorFn != NULL) {
        void *mem = bMalloc(END_GAME_SCREENS_SIZE, "EndGameScreens", 0,
                            RC_POOL);

        rc->pEndGameScreens = gEndGameScreensCtorFn(mem, next);
    }
    racecoordinator_change_state(rc, RCSTATE_POSTRACE);
}

// ---------------------------------------------- the small ones

void racecoordinator_joystick_handler(JoystickPort port, JoyEvent ev,
                                      uint8_t value, void *obj)
{
    (void)port;
    (void)value;
    (void)obj;
    if (ev == JOY_EVENT_SKIP_DEMO_MODE)
        racecoordinator_post_message(pRaceCoordinator, RC_SKIP, 0);
}

void racecoordinator_request_pause(RaceCoordinator *rc, int32_t port)
{
    racecoordinator_post_message(rc, RC_REQUEST_PAUSE, port);
}

void racecoordinator_request_unpause(RaceCoordinator *rc,
                                     UnPauseReasonType reason)
{
    racecoordinator_post_message(rc, RC_REQUEST_UNPAUSE, reason);
}

void racecoordinator_resume_demo_cameras(RaceCoordinator *rc)
{
    void *mem;

    if (rc->pDemoCameraCoordinator != NULL
        || gDemoCameraCoordinatorCtorFn == NULL)
        return;
    mem = bMalloc(DEMO_CAMERA_COORDINATOR_SIZE, kRCFile, RC_DEMO_LINE,
                  RC_POOL);
    rc->pDemoCameraCoordinator = gDemoCameraCoordinatorCtorFn(
        mem, 1, PlayerPlayersByIndex[0]->MyCar);
}

void racecoordinator_suspend_demo_cameras(RaceCoordinator *rc)
{
    if (rc->pDemoCameraCoordinator == NULL)
        return;
    delete_camera(rc->pDemoCameraCoordinator);
    rc->pDemoCameraCoordinator = NULL;
}
