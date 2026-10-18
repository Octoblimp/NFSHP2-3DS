// replayscreen -- ReplayScreen from retail (0x001ebda8 .. 0x001ed4e0).
// See replayscreen.h.

#include "replayscreen.h"

#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "cammover.h"
#include "democam.h"
#include "flailer.h"
#include "player.h"
#include "playercam.h"
#include "playerhud.h"
#include "playernis.h"
#include "race.h"
#include "racecoord.h"
#include "racesplit.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realdriver.h"
#include "realtime.h"
#include "replaymgr.h"
#include "timer.h"
#include "trackflow.h"

// Timers' 1/4000 s in seconds.
#define REPLAY_SCREEN_SECONDS       0.00025f

// The objects on the screen. Retail hashes the markers' names at run time.
#define RS_TIMELINE                 0xbd2bc882u  // the timeline, a bitmap
#define RS_TIME_MARKER              0xb8e8186fu  // the time, a bitmap
#define RS_INSTANT_REPLAY_MARKER    0xadaa0f01u
#define RS_DEMO_PLAYING             0xacf8f0b5u
#define RS_DEMO_RECORDING           0xd32490beu
#define RS_DEMO_WANT_RECORDING      0x4b53438fu
#define RS_ONE_PLAYER_ONLY          0xc9b7f0c0u  // a bitmap
#define RS_PLAYER_NUMBER            0x18b2dbc8u
#define RS_LAP                      0x6486623bu
#define RS_LAP_LABEL                0x51072bf1u
#define RS_PLACE                    0x3405c44eu
#define RS_PLACE_LABEL              0x98071aa4u
#define RS_TIME                     0x15e0f0a8u
#define RS_TIME_LABEL               0xd53d9dbeu
#define RS_TIME_LABEL_ID            0x61a8a

// A highlight marker's bar: 8 high, at 46 and green for a highlight's
// snapshot, else at 40 and orange.
#define RS_BAR_HEIGHT               8.0f
#define RS_BAR_Y_HIGHLIGHT          46
#define RS_BAR_Y_OTHER              40
#define RS_BAR_COLOR_HIGHLIGHT      0x50a040c0u
#define RS_BAR_COLOR_OTHER          0x80f08020u

// The replay pauses at the capture's end, and the end screens skip it
// after this many seconds of that.
#define RS_END_SKIP_SECONDS         4.0f
// PREVIOUS_MARKER goes back past a marker begun less than this ago.
#define RS_PREVIOUS_SLACK           1.0f
// The demo indicators blink: shown for 11 of every 24 frames.
#define RS_BLINK_PERIOD             24
#define RS_BLINK_SHOWN_FROM         13

#define RS_DRIVE_CAMERA_MOVER_SIZE  1008
#define RS_LOOKBACK_SPEED           300.9f

const int32_t ReplayCameraTypes[4] = { 0, 1, 2, 3 };

const int32_t ReplayScreenHelpIDs[9] = {
    802250, 802251, 802252, 802253, 802254, 802255, 802256, 802257, 0,
};

int32_t DemoModeReplay_WantToBeErasingSnapshot;
ReplaySnapshot *DemoModeReplay_pCurrentRecordingSnapshot;
ReplaySnapshot *DemoModeReplay_pCurrentPlayingSnapshot;
int16_t DemoDiscManager_InactiveTimeout;
int16_t DemoDiscManager_TotalTimeout;

void (*gReplayScreenPlaySampleFn)(const char *name, float volume);
void (*gReplayScreenFrontendSoundFn)(int32_t event);
int32_t (*gReplayScreenHelpActiveFn)(void);
int32_t (*gReplayScreenToggleHelpFn)(const int32_t *lines, int32_t value);
int32_t (*gReplayScreenIsThereACDFn)(void);
void (*gReplayScreenRadialBlurFn)(int32_t on);
int32_t (*gDemoModeReplayCanTestFn)(void);
void (*gDemoModeReplayBeginTestFn)(void);
int32_t (*gDemoModeReplayTestGoesOnFn)(void);
void (*gDemoModeReplayServiceDemoModeFn)(int32_t forward);
void (*gDemoModeReplayEndDemoModeFn)(void);
void (*gDemoModeReplayBeginRecordingFn)(void);
void (*gDemoModeReplayEndRecordingFn)(int32_t keep);

// ---------------------------------------------------------------- calls out

static void screen_visibility(uint32_t screen, int v)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, v);
}

static void play_sample(const char *name)
{
    if (gReplayScreenPlaySampleFn != NULL)
        gReplayScreenPlaySampleFn(name, 1.0f);
}

static void frontend_sound(int32_t event)
{
    if (gReplayScreenFrontendSoundFn != NULL)
        gReplayScreenFrontendSoundFn(event);
}

static void show(struct FlailerObjectChunk *o, int32_t v)
{
    if (o != NULL)
        flailerobject_set_visibility(o, v);
}

static struct Player *player_of(const ReplayScreen *s)
{
    return PlayerPlayersByNumber[s->PlayerNumber];
}

static int32_t usage_type(const struct Car *car)
{
    return car->pCarTypeInfo->UsageType;
}

static int32_t language(void)
{
    return gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;
}

// ---------------------------------------------------------------- the class

ReplayScreen *replayscreen_construct(void *mem, int32_t playerNumber)
{
    ReplayScreen *s = mem;
    ReplayManager *rm;
    struct FlailerObjectChunk *o;

    s->ReplayEndedTime = 0;
    screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_VISIBLE);
    s->PlayerNumber = playerNumber;
    s->NumLapMarkers = 0;
    s->NumHighlightMarkers = 0;
    s->HideTimeline = 0;
    s->LastJoyLoop = 0;
    s->ReplayEndedTime = 0;
    s->CameraMode = 0;

    rm = pReplayManager;
    s->EndOfTime = (float)rm->EndOfTime * REPLAY_SCREEN_SECONDS;
    s->BeginningOfTime = (float)rm->BeginningOfTime * REPLAY_SCREEN_SECONDS;
    if (s->EndOfTime <= s->BeginningOfTime)
        s->EndOfTime = s->BeginningOfTime + 1.0f;

    s->TimelinePositionX = 10;
    s->TimelineWidthX = 100;
    o = flailer_find_object(REPLAY_SCREEN_HASH, RS_TIMELINE,
                            FLAILER_TYPE_BITMAP);
    if (o != NULL) {
        s->TimelinePositionX = (int32_t)o->X;
        s->TimelineWidthX = (int32_t)flailerbitmap_width_float(
            (struct FlailerBitmapChunk *)o);
    }
    s->pTimeMarkerBitmap = (struct FlailerBitmapChunk *)flailer_find_object(
        REPLAY_SCREEN_HASH, RS_TIME_MARKER, FLAILER_TYPE_BITMAP);
    replayscreen_setup_markers(s, 1);

    s->pDemoModeIndicator[0] = flailer_find_object(
        REPLAY_SCREEN_HASH, RS_DEMO_PLAYING, FLAILER_TYPE_ANY);
    s->pDemoModeIndicator[1] = flailer_find_object(
        REPLAY_SCREEN_HASH, RS_DEMO_RECORDING, FLAILER_TYPE_ANY);
    s->pDemoModeIndicator[2] = flailer_find_object(
        REPLAY_SCREEN_HASH, RS_DEMO_WANT_RECORDING, FLAILER_TYPE_ANY);
    replayscreen_add_joy_handlers(s, 0);
    replayscreen_add_joy_handlers(s, 1);

    s->pDriveCameraMover = NULL;
    s->pDemoCameraCoordinator = NULL;
    s->pNisCameraCoordinator = NULL;
    replayscreen_change_camera_mover(s);

    o = flailer_find_object(REPLAY_SCREEN_HASH, RS_ONE_PLAYER_ONLY,
                            FLAILER_TYPE_BITMAP);
    if (o != NULL)
        flailerobject_set_visibility(o, PlayerNumPlayers == 1 ? 1 : 0);
    if (gSoundMuteReplayFn != NULL)
        gSoundMuteReplayFn(0);
    return s;
}

static void delete_drive_mover(ReplayScreen *s)
{
    struct CameraMover *m = s->pDriveCameraMover;

    m->vtbl->Destroy(m);
    bFree(m);
}

static void delete_demo_coordinator(ReplayScreen *s)
{
    if (gCameraCoordinatorDeleteFn != NULL)
        gCameraCoordinatorDeleteFn(s->pDemoCameraCoordinator);
}

void replayscreen_destroy(ReplayScreen *s, int32_t flags)
{
    if (s->HideTimeline)
        screen_visibility(REPLAY_SCREEN_HIDDEN_HASH, FLAILER_SCREEN_INVISIBLE);
    else
        screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_INVISIBLE);
    replayscreen_setup_markers(s, 0);
    replayscreen_remove_joy_handlers(s, 0);
    replayscreen_remove_joy_handlers(s, 1);
    replayscreen_pause(s, 0);
    pReplayManager->SlowMotionFlag = 0;
    if (s->pDriveCameraMover != NULL)
        delete_drive_mover(s);
    if (s->pDemoCameraCoordinator != NULL)
        delete_demo_coordinator(s);
    replayscreen_stop_watching_nis(s);
    if (gDemoModeReplayEndRecordingFn != NULL)
        gDemoModeReplayEndRecordingFn(0);
    if (gDemoModeReplayEndDemoModeFn != NULL)
        gDemoModeReplayEndDemoModeFn();
    DemoModeReplay_WantToBeErasingSnapshot = 0;
    if (flags & 1)
        bFree(s);
}

void replayscreen_setup_markers(ReplayScreen *s, int32_t build)
{
    ReplaySnapshot *snap;
    int32_t i, k = 0, lap = 1, instant = 0;
    char name[128];

    for (i = 0; i < s->NumLapMarkers; i++)
        show(s->LapMarkers[i].pObject, 0);
    for (i = 0; i < s->NumHighlightMarkers; i++)
        show(s->HighlightMarkers[i].pObject, 0);
    if (!build)
        return;

    s->NumLapMarkers = 0;
    s->NumHighlightMarkers = 0;
    while ((snap = replaymgr_get_snapshot(pReplayManager, k++)) != NULL) {
        ReplayScreenMarker *m = NULL;

        if (strcmp(snap->Name, "LAP_SNAPSHOT") == 0) {
            m = &s->LapMarkers[s->NumLapMarkers++];
            b_snprintf(name, sizeof name, "LAP_MARKER%d", lap++);
            m->pObject = flailer_find_object(REPLAY_SCREEN_HASH,
                                             bchunk_hash(name),
                                             FLAILER_TYPE_BITMAP);
        } else if (strcmp(snap->Name, "HIGHLIGHT_SNAPSHOT") == 0) {
            // Retail marks none of the highlights' snapshots.
        } else if (strcmp(snap->Name, "DEMO_MODE_SNAPSHOT") == 0) {
            m = &s->HighlightMarkers[s->NumHighlightMarkers++];
            b_snprintf(name, sizeof name, "HIGHLIGHT_MARKER%d",
                       s->NumHighlightMarkers);
            m->pObject = flailer_find_object(REPLAY_SCREEN_HASH,
                                             bchunk_hash(name),
                                             FLAILER_TYPE_BITMAP);
        } else if (!instant && strcmp(snap->Name, "INSTANT_REPLAY") == 0) {
            m = &s->LapMarkers[s->NumLapMarkers++];
            instant = 1;
            m->pObject = flailer_find_object(REPLAY_SCREEN_HASH,
                                             RS_INSTANT_REPLAY_MARKER,
                                             FLAILER_TYPE_BITMAP);
        }
        if (m == NULL || m->pObject == NULL)
            continue;
        m->pSnapshot = snap;
        m->EndTime = (float)snap->EndTime * REPLAY_SCREEN_SECONDS;
        m->BeginTime = (float)snap->Time * REPLAY_SCREEN_SECONDS;
        flailerobject_set_visibility(m->pObject, 1);
    }

    for (i = 0; i < s->NumLapMarkers; i++) {
        ReplayScreenMarker *m = &s->LapMarkers[i];

        if (m->pObject != NULL)
            flailerobject_set_top_left_x(
                m->pObject,
                (float)replayscreen_timeline_position_x(s, m->BeginTime));
    }
    for (i = 0; i < s->NumHighlightMarkers; i++) {
        ReplayScreenMarker *m = &s->HighlightMarkers[i];
        int32_t w;

        if (m->pObject == NULL)
            continue;
        flailerobject_set_top_left_x(
            m->pObject,
            (float)replayscreen_timeline_position_x(s, m->BeginTime));
        w = replayscreen_timeline_position_x(s, m->EndTime);
        w -= replayscreen_timeline_position_x(s, m->BeginTime);
        flailerobject_set_width(m->pObject, (float)w);
        flailerobject_set_height(m->pObject, RS_BAR_HEIGHT);
        if (strcmp(m->pSnapshot->Name, "HIGHLIGHT_SNAPSHOT") == 0) {
            flailerobject_set_top_left_y(m->pObject,
                                         (float)RS_BAR_Y_HIGHLIGHT);
            flailerbitmap_set_color((struct FlailerBitmapChunk *)m->pObject,
                                    RS_BAR_COLOR_HIGHLIGHT);
        } else {
            flailerobject_set_top_left_y(m->pObject, (float)RS_BAR_Y_OTHER);
            flailerbitmap_set_color((struct FlailerBitmapChunk *)m->pObject,
                                    RS_BAR_COLOR_OTHER);
        }
    }
}

int32_t replayscreen_should_watch_nis(ReplayScreen *s)
{
    return player_is_nis_playing(player_of(s)) != 0;
}

void replayscreen_stop_watching_nis(ReplayScreen *s)
{
    if (s->pNisCameraCoordinator == NULL)
        return;
    if (gNisDeleteCameraCoordinatorFn != NULL)
        gNisDeleteCameraCoordinatorFn(player_of(s)->pNisManager,
                                      s->pNisCameraCoordinator);
    s->pNisCameraCoordinator = NULL;
}

int32_t replayscreen_has_camera_mover(ReplayScreen *s)
{
    return s->pDriveCameraMover != NULL || s->pDemoCameraCoordinator != NULL
           || s->pNisCameraCoordinator != NULL;
}

static struct CameraMover *new_drive_mover(struct Car *car, int32_t pov,
                                           int32_t lookBack)
{
    void *mem;

    if (gDriveCameraMoverFn == NULL)
        return NULL;
    mem = bMalloc(RS_DRIVE_CAMERA_MOVER_SIZE, "DriveCameraMover", 0, 16);
    return gDriveCameraMoverFn(mem, 1, car, pov, RS_LOOKBACK_SPEED, 0,
                               lookBack, 1);
}

void replayscreen_change_camera_mover(ReplayScreen *s)
{
    struct Player *p = player_of(s);
    struct Car *car = p->MyCar;
    int32_t blur = p->nZoneCurrent != 0;

    if (car->TheControlMode == REAL_CONTROL)
        blur |= realdriver_nitro_active((RealDriver *)car->pCarDriver) != 0;
    if (gReplayScreenRadialBlurFn != NULL)
        gReplayScreenRadialBlurFn(blur);

    if (s->pDriveCameraMover != NULL) {
        delete_drive_mover(s);
        s->pDriveCameraMover = NULL;
    }
    if (s->pDemoCameraCoordinator != NULL) {
        delete_demo_coordinator(s);
        s->pDemoCameraCoordinator = NULL;
    }
    replayscreen_stop_watching_nis(s);

    if (replayscreen_should_watch_nis(s)) {
        s->pNisCameraCoordinator =
            gNisCreateCameraCoordinatorFn != NULL
                ? gNisCreateCameraCoordinatorFn(p->pNisManager, 1) : NULL;
        return;
    }
    switch (ReplayCameraTypes[s->CameraMode]) {
    case 0:
        if (gDemoCameraCoordinatorCtorFn != NULL)
            s->pDemoCameraCoordinator = gDemoCameraCoordinatorCtorFn(
                bMalloc(DEMO_CAMERA_COORDINATOR_SIZE,
                        "DemoCameraCoordinator", 0, 16),
                1, car);
        break;
    case 1:
        s->pDriveCameraMover = new_drive_mover(car, 1, 0);
        break;
    case 2:
        s->pDriveCameraMover = new_drive_mover(car, 1, 1);
        break;
    case 3:
        s->pDriveCameraMover = new_drive_mover(car, 0, 0);
        break;
    }
}

// The loops the capture has left, wrapping as retail's subu does.
static int32_t loops_left(const ReplayManager *rm)
{
    return (int32_t)((uint32_t)rm->EndCapturingLoopCount
                     - (uint32_t)WorldLoopCounter);
}

void replayscreen_tick(ReplayScreen *s)
{
    ReplayManager *rm = pReplayManager;

    if (loops_left(rm) <= 0 && !rm->PausedFlag) {
        s->ReplayEndedTime = RealTimer;
        replayscreen_pause(s, 1);
    }
    rm = pReplayManager;
    if (pRaceCoordinator->pEndGameScreens != NULL
        && loops_left(rm) <= 0
        && rm->PausedFlag
        && RS_END_SKIP_SECONDS
               < (float)(int32_t)((uint32_t)RealTimer
                                  - (uint32_t)s->ReplayEndedTime)
                     * REPLAY_SCREEN_SECONDS)
        racecoordinator_post_message(pRaceCoordinator, RC_SKIP_REPLAY, 0);
    if (DemoModeReplay_pCurrentPlayingSnapshot != NULL
        && (gDemoModeReplayTestGoesOnFn != NULL
                ? gDemoModeReplayTestGoesOnFn() : 1) != 1)
        replayscreen_pause(s, 1);
}

// A demo indicator: blinking while its word of TheDemoModeReplay is set.
static void indicator(struct FlailerObjectChunk *o, int32_t on)
{
    if (o == NULL)
        return;
    if (on)
        flailerobject_set_visibility(
            o, !(RealTimeFrames % RS_BLINK_PERIOD < RS_BLINK_SHOWN_FROM));
    else
        flailerobject_set_visibility(o, 0);
}

void replayscreen_update(ReplayScreen *s)
{
    struct Car *car;
    struct RacingCar *rc;
    struct FlailerObjectChunk *lap, *lapLabel, *place, *placeLabel, *o;
    Timer t;
    char buf[64];

    replayscreen_setup_markers(s, 1);
    replayscreen_set_bitmap_position(
        s, s->pTimeMarkerBitmap, (float)WorldTimer * REPLAY_SCREEN_SECONDS);
    car = player_of(s)->MyCar;
    rc = race_get_racing_car(pCurrentRace, car);
    flailer_printf(REPLAY_SCREEN_HASH, RS_PLAYER_NUMBER, "%d",
                   s->PlayerNumber + 1);

    lap = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP, FLAILER_TYPE_ANY);
    lapLabel = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP_LABEL,
                                   FLAILER_TYPE_ANY);
    place = flailer_find_object(REPLAY_SCREEN_HASH, RS_PLACE,
                                FLAILER_TYPE_ANY);
    placeLabel = flailer_find_object(REPLAY_SCREEN_HASH, RS_PLACE_LABEL,
                                     FLAILER_TYPE_ANY);
    if (usage_type(car) == 1) {
        show(lap, 0);
        show(lapLabel, 0);
        show(place, 0);
        show(placeLabel, 0);
    } else {
        int32_t cars;

        // Retail finds the lap's object again here.
        o = flailer_find_object(REPLAY_SCREEN_HASH, RS_LAP,
                                FLAILER_TYPE_ANY);
        if (pCurrentRace->NumLapsInRace == 1
            || TheRaceParameters.Point2Point) {
            show(o, 0);
            show(lapLabel, 0);
        } else {
            int32_t n = rc->NumLapsCompleted + 1;

            show(o, 1);
            show(lapLabel, 1);
            if (n > pCurrentRace->NumLapsInRace)
                n = pCurrentRace->NumLapsInRace;
            flailer_printf(REPLAY_SCREEN_HASH, RS_LAP, "%d/%d", n,
                           pCurrentRace->NumLapsInRace);
        }

        cars = pCurrentRace->NumRacingCars;
        if (PlayerNumPlayers >= 2) {
            int32_t other = (s->PlayerNumber + 1) % PlayerNumPlayers;

            if (other != s->PlayerNumber
                && usage_type(PlayerPlayersByNumber[other]->MyCar) == 1)
                cars--;
        }
        if (cars >= 2) {
            show(place, 1);
            show(placeLabel, 1);
            flailer_printf(REPLAY_SCREEN_HASH, RS_PLACE, "%d/%d",
                           rc->RacePosition, cars);
        } else {
            show(place, 0);
            show(placeLabel, 0);
        }
    }

    t = pCurrentRace->RaceTime;
    timer_print_to_string(&t, buf, 0, language());
    o = flailer_find_object(REPLAY_SCREEN_HASH, RS_TIME, FLAILER_TYPE_ANY);
    if (rc->FinishReason == 2 || rc->FinishReason == 3) {
        show(o, 0);
        flailer_set_language_id(REPLAY_SCREEN_HASH, RS_TIME_LABEL,
                                (uint32_t)racingcar_get_finish_reason_id(
                                    rc->FinishReason));
    } else {
        show(o, 1);
        flailer_printf(REPLAY_SCREEN_HASH, RS_TIME, "%s", buf);
        flailer_set_language_id(REPLAY_SCREEN_HASH, RS_TIME_LABEL,
                                RS_TIME_LABEL_ID);
    }

    indicator(s->pDemoModeIndicator[0],
              DemoModeReplay_pCurrentPlayingSnapshot != NULL);
    indicator(s->pDemoModeIndicator[1],
              DemoModeReplay_pCurrentRecordingSnapshot != NULL);
    indicator(s->pDemoModeIndicator[2],
              DemoModeReplay_WantToBeErasingSnapshot != 0);

    if (!replayscreen_has_camera_mover(s))
        replayscreen_change_camera_mover(s);
    if ((replayscreen_should_watch_nis(s) && s->pNisCameraCoordinator == NULL)
        || (!replayscreen_should_watch_nis(s)
            && s->pNisCameraCoordinator != NULL))
        replayscreen_change_camera_mover(s);
}

void replayscreen_add_joy_handlers(ReplayScreen *s, JoystickPort port)
{
    JoyEvent ev;

    for (ev = JOY_EVENT_REPLAY_SKIP; ev <= JOY_EVENT_REPLAY_ERASE_DEMO; ev++)
        AddJoyHandler(port, ev, replayscreen_joy_handler_bridge, s);
}

void replayscreen_remove_joy_handlers(ReplayScreen *s, JoystickPort port)
{
    JoyEvent ev;

    (void)s;
    for (ev = JOY_EVENT_REPLAY_SKIP; ev <= JOY_EVENT_REPLAY_ERASE_DEMO; ev++)
        RemoveJoyHandler(port, ev);
}

// PREVIOUS_MARKER's: the last lap marker begun more than a second ago.
static ReplayScreenMarker *previous_marker(ReplayScreen *s)
{
    ReplayScreenMarker *found = NULL;
    int32_t i;

    for (i = 0; i < s->NumLapMarkers; i++)
        if (RS_PREVIOUS_SLACK < (float)WorldTimer * REPLAY_SCREEN_SECONDS
                                    - s->LapMarkers[i].BeginTime)
            found = &s->LapMarkers[i];
    return found;
}

// NEXT_MARKER's: the first lap marker not begun yet.
static ReplayScreenMarker *next_marker(ReplayScreen *s)
{
    int32_t i;

    for (i = 0; i < s->NumLapMarkers; i++)
        if ((float)WorldTimer * REPLAY_SCREEN_SECONDS
            < s->LapMarkers[i].BeginTime)
            return &s->LapMarkers[i];
    return NULL;
}

void replayscreen_joy_handler(ReplayScreen *s, JoystickPort port,
                              JoyEvent ev, uint8_t value)
{
    ReplayManager *rm;
    ReplayScreenMarker *m;
    int32_t other, active;

    (void)port;
    if (ev != JOY_EVENT_REPLAY_HELP && gReplayScreenHelpActiveFn != NULL
        && gReplayScreenHelpActiveFn())
        return;
    if (RealLoopCounter == s->LastJoyLoop)
        return;
    s->LastJoyLoop = RealLoopCounter;

    switch (ev) {
    case JOY_EVENT_REPLAY_SKIP:
        play_sample("MenuUpDown");
        racecoordinator_post_message(pRaceCoordinator, RC_SKIP_REPLAY, 0);
        break;

    case JOY_EVENT_REPLAY_PAUSE:
        play_sample("MenuUpDown");
        rm = pReplayManager;
        if (!rm->PausedFlag)
            replayscreen_pause(s, 1);
        else if (loops_left(rm) > 0)
            replayscreen_pause(s, 0);
        break;

    case JOY_EVENT_REPLAY_PREVIOUS_MARKER:
    case JOY_EVENT_REPLAY_NEXT_MARKER:
        play_sample("MenuLeftRight");
        if (DemoModeReplay_pCurrentPlayingSnapshot != NULL) {
            if (gDemoModeReplayServiceDemoModeFn != NULL)
                gDemoModeReplayServiceDemoModeFn(
                    ev == JOY_EVENT_REPLAY_NEXT_MARKER);
            break;
        }
        m = ev == JOY_EVENT_REPLAY_PREVIOUS_MARKER ? previous_marker(s)
                                                    : next_marker(s);
        if (m == NULL)
            break;
        replayscreen_pause(s, 0);
        replayscreen_stop_watching_nis(s);
        racecoordinator_post_message(pRaceCoordinator, RC_MOVE_REPLAY,
                                     (int32_t)(intptr_t)m->pSnapshot);
        break;

    case JOY_EVENT_REPLAY_PLAYBACK_SPEED:
        play_sample("MenuUpDown");
        rm = pReplayManager;
        if (rm->PausedFlag) {
            replayscreen_pause(s, 0);
            pReplayManager->SlowMotionFlag = 1;
        } else {
            rm->SlowMotionFlag = rm->SlowMotionFlag ? 0 : 1;
        }
        break;

    case JOY_EVENT_REPLAY_CAMERA_ANGLE:
        s->CameraMode = (s->CameraMode + 1) & 3;
        replayscreen_change_camera_mover(s);
        frontend_sound(3);
        break;

    case JOY_EVENT_REPLAY_CAMERA_TARGET:
        if (PlayerNumPlayers != 2)
            break;
        other = (s->PlayerNumber + 1) % PlayerNumPlayers;
        if (other == s->PlayerNumber)
            break;
        replayscreen_stop_watching_nis(s);
        s->PlayerNumber = other;
        replayscreen_change_camera_mover(s);
        frontend_sound(5);
        break;

    case JOY_EVENT_REPLAY_HELP:
        active = gReplayScreenToggleHelpFn != NULL
                     ? gReplayScreenToggleHelpFn(ReplayScreenHelpIDs, value)
                     : 0;
        if (loops_left(pReplayManager) <= 0)
            break;
        replayscreen_pause(s, active ? 1 : 0);
        break;

    case JOY_EVENT_REPLAY_HIDE_TIMELINE:
        s->HideTimeline = s->HideTimeline == 0;
        if (s->HideTimeline) {
            screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_INVISIBLE);
            screen_visibility(REPLAY_SCREEN_HIDDEN_HASH,
                              FLAILER_SCREEN_VISIBLE);
        } else {
            screen_visibility(REPLAY_SCREEN_HIDDEN_HASH,
                              FLAILER_SCREEN_INVISIBLE);
            screen_visibility(REPLAY_SCREEN_HASH, FLAILER_SCREEN_VISIBLE);
        }
        frontend_sound(5);
        break;

    case JOY_EVENT_REPLAY_MARK_DEMO:
        if (gReplayScreenIsThereACDFn == NULL || gReplayScreenIsThereACDFn())
            break;
        if (value) {
            DemoDiscManager_TotalTimeout = 32767;
            DemoDiscManager_InactiveTimeout = 32767;
            if (gDemoModeReplayBeginRecordingFn != NULL)
                gDemoModeReplayBeginRecordingFn();
        } else if (gDemoModeReplayEndRecordingFn != NULL) {
            gDemoModeReplayEndRecordingFn(0);
        }
        break;

    case JOY_EVENT_REPLAY_TEST_DEMO:
        if (gDemoModeReplayCanTestFn == NULL || !gDemoModeReplayCanTestFn())
            break;
        if (DemoModeReplay_pCurrentPlayingSnapshot == NULL) {
            if (gDemoModeReplayBeginTestFn != NULL)
                gDemoModeReplayBeginTestFn();
        } else if (gDemoModeReplayEndDemoModeFn != NULL) {
            gDemoModeReplayEndDemoModeFn();
        }
        replayscreen_pause(s, 0);
        break;

    case JOY_EVENT_REPLAY_ERASE_DEMO:
        if (!value)
            DemoModeReplay_WantToBeErasingSnapshot = 0;
        else if (DemoModeReplay_pCurrentPlayingSnapshot != NULL)
            DemoModeReplay_WantToBeErasingSnapshot = 1;
        break;
    }
}

int32_t replayscreen_timeline_position_x(const ReplayScreen *s, float t)
{
    return (int32_t)((float)s->TimelineWidthX
                     * ((t - s->BeginningOfTime)
                        / (s->EndOfTime - s->BeginningOfTime)))
           + s->TimelinePositionX;
}

void replayscreen_set_bitmap_position(ReplayScreen *s,
                                      struct FlailerBitmapChunk *b, float t)
{
    if (b != NULL)
        flailerobject_set_top_left_x(
            (struct FlailerObjectChunk *)b,
            (float)replayscreen_timeline_position_x(s, t));
}

void replayscreen_pause(ReplayScreen *s, int32_t on)
{
    (void)s;
    pReplayManager->PausedFlag = on;
    if (gSoundMuteReplayFn != NULL)
        gSoundMuteReplayFn(on != 0);
}

void replayscreen_joy_handler_bridge(JoystickPort port, JoyEvent ev,
                                     uint8_t value, void *obj)
{
    replayscreen_joy_handler((ReplayScreen *)obj, port, ev, value);
}
