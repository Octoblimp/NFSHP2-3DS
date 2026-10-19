// playerinput -- see playerinput.h.
#include "playerinput.h"

#include <stddef.h>

#include "cammover.h"
#include "car.h"
#include "cardriver.h"
#include "copmanager.h"
#include "drivecam.h"
#include "joystick.h"
#include "player.h"
#include "playercam.h"
#include "race.h"
#include "racecoord.h"
#include "racefinish.h"
#include "rcstates.h"
#include "realdriver.h"
#include "realtime.h"
#include "vtable.h"
#include "world.h"

int32_t DebugCamerasEnabled;              // gp-23080

void (*gPlayerCycleHudFn)(struct Player *p, int32_t dir);
void (*gCopManagerBeACopRequestRoadBlockFn)(struct tCopManager *m);
void (*gCopManagerBeACopRequestChopperFn)(struct tCopManager *m);
void (*gAnimatedDriverBeginLookingBackwardsFn)(struct AnimatedDriver *d);
void (*gAnimatedDriverEndLookingBackwardsFn)(struct AnimatedDriver *d);

typedef void (*PlayerInputDriverFn)(void *self);

// 0x00330790, by camera zone: freeze and preview hold the player.
static const int8_t ZoneFreezesInput[8] = { 0, 1, 1, 0, 0, 0, 0, 0 };

// By the RaceCoordinator's state, the jump table at 0x002b3b80.
static const int32_t ModeByRCState[10] = {
    PLAYER_MODE_NONE,           // NONE
    PLAYER_MODE_PRERACE,        // CAMERA_FLYBY
    PLAYER_MODE_PRERACE,        // PRERACE
    PLAYER_MODE_CAR_RACING,     // RACE_IN_PROGRESS
    PLAYER_MODE_INSTANT_REPLAY, // INSTANT_REPLAY
    PLAYER_MODE_INSTANT_REPLAY, // AUTO_REPLAY
    PLAYER_MODE_PAUSEMENU,      // PAUSE
    PLAYER_MODE_INSTANT_REPLAY, // POSTRACE
    PLAYER_MODE_AI_DEMO,        // AI_DEMO_MODE
    PLAYER_MODE_INSTANT_REPLAY, // REPLAY_DEMO_MODE
};

// The debug camera's cycles, 0x002b3c60 and 0x002b3c70.
static const CameraMoverType DebugCamerasAIDemo[3] = {
    CM_NONE, CM_ORBIT_CAR, CM_DEBUG_WORLD
};
static const CameraMoverType DebugCameras[4] = {
    CM_DRIVE, CM_ORBIT_CAR, CM_DEBUG_WORLD, CM_TRACK_ROUTE_EDITOR
};

// ------------------------------------------------------- choosing the mode

void determine_all_players_input_modes(void)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++)
        player_determine_input_mode(PlayerPlayersByIndex[i]);
}

void player_determine_input_mode(struct Player *p)
{
    uint32_t st = (uint32_t)pRaceCoordinator->CurrentRCState;
    int32_t  mode = st < 10 ? ModeByRCState[st] : PLAYER_MODE_NONE;

    if (p->TimeFinishedRacing != 0)
        mode = PLAYER_MODE_FINISH_RACE;
    // Retail indexes the table with no bound; nZoneCurrent is 0 to 7.
    if (ZoneFreezesInput[p->nZoneCurrent] != 0)
        mode = PLAYER_MODE_FROZEN_ZONE;
    if (p->PlayerInputMode != mode)
        player_set_input_mode(p, mode);
}

// --------------------------------------------------------- the handler set

// Whether the player's car is Be A Cop's player cop's.
static int is_player_cop_car(const struct Player *p)
{
    tCop *cop = copmanager_get_player_cop(pCopManager);

    return cop != NULL && cop->pMyCar == p->MyCar;
}

static void call_driver_slot(CarDriver *d, int slot)
{
    const VtEntry *e = vt_slot(d->_vtable, slot);

    ((PlayerInputDriverFn)e->fn)(vt_this(d, e));
}

static void remove_mover_handlers(CameraMover *m)
{
    if (m != NULL)
        m->vtbl->RemoveJoyHandlers(m);
}

static void add_mover_handlers(CameraMover *m)
{
    if (m != NULL)
        m->vtbl->AddJoyHandlers(m);
}

void player_set_input_mode(struct Player *p, int32_t mode)
{
    JoystickPort port = p->JoyPort;
    int32_t      old = p->PlayerInputMode;
    JoyHandler   racing = player_racing_joy_handler_bridge;
    Car         *c;

    switch ((uint32_t)old) {
    case PLAYER_MODE_CAR_RACING:
    case PLAYER_MODE_INSTANT_REPLAY:
        if (old == PLAYER_MODE_CAR_RACING) {
            RemoveJoyHandler(port, JOY_EVENT_PAUSE);
            RemoveJoyHandler(port, JOY_EVENT_CAMERA_POV_CHANGE);
            RemoveJoyHandler(port, JOY_EVENT_CYCLE_HUD);
        }
        RemoveJoyHandler(port, JOY_EVENT_CAMERA_LOOKBACK);
        if (RaceParametersBeACop) {
            if (is_player_cop_car(p)) {
                RemoveJoyHandler(port, JOY_EVENT_REQUEST_ROADBLOCK);
                RemoveJoyHandler(port, JOY_EVENT_REQUEST_HELICOPTER);
            }
        } else {
            RemoveJoyHandler(port, JOY_EVENT_ZONE_FREEZE);
            RemoveJoyHandler(port, JOY_EVENT_ZONE_PREVIEW);
            RemoveJoyHandler(port, JOY_EVENT_ZONE_SLOMO);
            RemoveJoyHandler(port, JOY_EVENT_ZONE_WARP);
        }
        // Whatever the control mode; the add below asks for REAL_CONTROL.
        c = p->MyCar;
        if (c != NULL && c->pCarDriver != NULL)
            call_driver_slot(c->pCarDriver,
                             CARDRIVER_VT_REMOVE_JOY_HANDLERS);
        remove_mover_handlers(p->pCameraMover);
        remove_mover_handlers(p->pSavedCameraMover);
        remove_mover_handlers(p->pSavedCameraMover2);
        break;
    case PLAYER_MODE_FROZEN_ZONE:
        RemoveJoyHandler(port, JOY_EVENT_PAUSE);
        break;
    case PLAYER_MODE_PRERACE:
    case PLAYER_MODE_FINISH_RACE:
        RemoveJoyHandler(port, JOY_EVENT_SKIP);
        RemoveJoyHandler(port, JOY_EVENT_PAUSE);
        break;
    default:
        break;
    }
    if (p->PlayerNumber == 0
        && IsJoyHandlerAdded(1, JOY_EVENT_CHANGE_DEBUG_CAMERA))
        RemoveJoyHandler(1, JOY_EVENT_CHANGE_DEBUG_CAMERA);

    p->PlayerInputMode = mode;
    switch ((uint32_t)mode) {
    case PLAYER_MODE_CAR_RACING:
    case PLAYER_MODE_INSTANT_REPLAY:
        if (p->PlayerInputMode == PLAYER_MODE_CAR_RACING) {
            AddJoyHandler(port, JOY_EVENT_PAUSE, racing, p);
            AddJoyHandler(port, JOY_EVENT_CAMERA_POV_CHANGE, racing, p);
            AddJoyHandler(port, JOY_EVENT_CYCLE_HUD, racing, p);
        }
        AddJoyHandler(port, JOY_EVENT_CAMERA_LOOKBACK, racing, p);
        if (RaceParametersBeACop) {
            if (is_player_cop_car(p)) {
                AddJoyHandler(port, JOY_EVENT_REQUEST_ROADBLOCK, racing, p);
                AddJoyHandler(port, JOY_EVENT_REQUEST_HELICOPTER, racing, p);
            }
        } else {
            AddJoyHandler(port, JOY_EVENT_ZONE_FREEZE, racing, p);
            AddJoyHandler(port, JOY_EVENT_ZONE_PREVIEW, racing, p);
            AddJoyHandler(port, JOY_EVENT_ZONE_SLOMO, racing, p);
            AddJoyHandler(port, JOY_EVENT_ZONE_WARP, racing, p);
        }
        // A REAL_CONTROL car's driver is a RealDriver: the port goes in
        // before its handlers do.
        c = p->MyCar;
        if (c != NULL && c->TheControlMode == REAL_CONTROL
            && c->pCarDriver != NULL) {
            ((RealDriver *)(void *)c->pCarDriver)->Port = p->JoyPort;
            call_driver_slot(c->pCarDriver, CARDRIVER_VT_ADD_JOY_HANDLERS);
        }
        add_mover_handlers(p->pCameraMover);
        add_mover_handlers(p->pSavedCameraMover);
        add_mover_handlers(p->pSavedCameraMover2);
        break;
    case PLAYER_MODE_FROZEN_ZONE:
        AddJoyHandler(port, JOY_EVENT_PAUSE, racing, p);
        break;
    case PLAYER_MODE_PRERACE:
        AddJoyHandler(port, JOY_EVENT_SKIP, player_pre_race_joy_handler, p);
        AddJoyHandler(port, JOY_EVENT_PAUSE, player_pre_race_joy_handler, p);
        break;
    case PLAYER_MODE_FINISH_RACE:
        AddJoyHandler(port, JOY_EVENT_SKIP, player_finish_race_joy_handler,
                      p);
        AddJoyHandler(port, JOY_EVENT_PAUSE, player_finish_race_joy_handler,
                      p);
        break;
    default:
        break;
    }
    if ((p->PlayerInputMode == PLAYER_MODE_CAR_RACING
         || p->PlayerInputMode == PLAYER_MODE_AI_DEMO)
        && PlayerNumPlayers < 2 && p->PlayerNumber == 0)
        AddJoyHandler(1, JOY_EVENT_CHANGE_DEBUG_CAMERA,
                      player_change_debug_camera_joy_handler_bridge, p);
}

// ------------------------------------------------------------ the handlers

void player_racing_joy_handler_bridge(JoystickPort port, JoyEvent ev,
                                      uint8_t value, void *obj)
{
    player_racing_joy_handler((struct Player *)obj, port, ev, value);
}

void player_change_debug_camera_joy_handler_bridge(JoystickPort port,
                                                   JoyEvent ev,
                                                   uint8_t value, void *obj)
{
    player_change_debug_camera_joy_handler((struct Player *)obj, port, ev,
                                           value);
}

void player_racing_joy_handler(struct Player *p, JoystickPort port,
                               JoyEvent ev, uint8_t value)
{
    CameraMover *m;
    Car         *c;

    switch (ev) {
    case JOY_EVENT_PAUSE:
        racecoordinator_request_pause(pRaceCoordinator, port);
        break;
    case JOY_EVENT_CAMERA_POV_CHANGE:
        // More than a second (RealTimer is 4000 a second, gp-30396 its
        // reciprocal) since a Be A Cop request held it off.
        if (!(1.0f < (float)(RealTimer
                             - (int32_t)p->tIgnoreNextPovChange.PackedTime)
                         * 0.00025f))
            break;
        if (p->PlayerInputMode != PLAYER_MODE_CAR_RACING)
            break;
        m = p->pCameraMover;
        if (m == NULL || m->Type != CM_DRIVE)
            break;
        p->PlayerSettings.DriveCameraPOVIndex = (int8_t)
            player_cycle_drive_camera_pov_index(
                p, p->PlayerSettings.DriveCameraPOVIndex + 1);
        break;
    case JOY_EVENT_CAMERA_LOOKBACK:
        p->bLookBack = value != 0;
        if (TweakerPauseWorld == 0)
            p->tAutoZoneTimers[0].PackedTime = (uint32_t)WorldTimer;
        // The drive camera, else the saved one if that is a drive camera.
        m = p->pCameraMover;
        if (m == NULL || m->Type != CM_DRIVE)
            m = p->pSavedCameraMover;
        if (m != NULL && m->Type == CM_DRIVE)
            ((DriveCameraMover *)(void *)m)->DesiredLookBackParam =
                p->bLookBack ? 1.0f : 0.0f;
        // Retail's Car keeps pAnimatedDriver at 1204.
        c = p->MyCar;
        if (c->pAnimatedDriver != NULL) {
            if (value != 0) {
                if (gAnimatedDriverBeginLookingBackwardsFn != NULL)
                    gAnimatedDriverBeginLookingBackwardsFn(
                        c->pAnimatedDriver);
            } else if (gAnimatedDriverEndLookingBackwardsFn != NULL) {
                gAnimatedDriverEndLookingBackwardsFn(c->pAnimatedDriver);
            }
        }
        break;
    case JOY_EVENT_ZONE_FREEZE:
    case JOY_EVENT_ZONE_PREVIEW:
    case JOY_EVENT_ZONE_SLOMO:
        if (gPlayerRequestZoneFn != NULL)
            gPlayerRequestZoneFn(p, ev - JOY_EVENT_ZONE_FREEZE + 1, 1, 1, 1);
        break;
    case JOY_EVENT_REQUEST_ROADBLOCK:
        if (gCopManagerBeACopRequestRoadBlockFn != NULL)
            gCopManagerBeACopRequestRoadBlockFn(pCopManager);
        p->tIgnoreNextPovChange.PackedTime = (uint32_t)RealTimer;
        break;
    case JOY_EVENT_REQUEST_HELICOPTER:
        if (gCopManagerBeACopRequestChopperFn != NULL)
            gCopManagerBeACopRequestChopperFn(pCopManager);
        p->tIgnoreNextPovChange.PackedTime = (uint32_t)RealTimer;
        break;
    case JOY_EVENT_CYCLE_HUD:
        if (p->PlayerSettings.New40 != 0 && gPlayerCycleHudFn != NULL)
            gPlayerCycleHudFn(p, 1);
        break;
    default:
        // ZONE_WARP among them: registered, and nothing.
        break;
    }
}

void player_reroute_joy_event(struct Player *p, JoystickPort port,
                              JoyEvent ev, uint8_t value)
{
    JoyEvent to;

    if (ev == JOY_EVENT_SHIFTUP) {
        if (RaceParametersBeACop) {
            if (!is_player_cop_car(p))
                return;
            to = JOY_EVENT_REQUEST_ROADBLOCK;
        } else {
            to = JOY_EVENT_ZONE_PREVIEW;
        }
    } else if (ev == JOY_EVENT_SHIFTDOWN) {
        if (RaceParametersBeACop) {
            if (!is_player_cop_car(p))
                return;
            to = JOY_EVENT_REQUEST_HELICOPTER;
        } else {
            to = JOY_EVENT_ZONE_FREEZE;
        }
    } else {
        return;
    }
    player_racing_joy_handler(p, port, to, value);
}

void player_pre_race_joy_handler(JoystickPort port, JoyEvent ev,
                                 uint8_t value, void *obj)
{
    struct Player   *p = (struct Player *)obj;
    RaceCoordinator *rc = pRaceCoordinator;

    (void)value;
    if (ev == JOY_EVENT_PAUSE) {
        if (p->TimeFinishedRacing == 0)
            racecoordinator_request_pause(rc, port);
    } else if (ev == JOY_EVENT_SKIP) {
        if (rc->CurrentRCState != RCSTATE_CAMERA_FLYBY
            && !RaceParametersBeACop)
            racecoordinator_post_message(rc, RC_SKIP, 0);
    }
}

void player_finish_race_joy_handler(JoystickPort port, JoyEvent ev,
                                    uint8_t value, void *obj)
{
    RaceCoordinator *rc = pRaceCoordinator;
    RCState          st;
    int              replaying;

    (void)value;
    (void)obj;
    if (ev != JOY_EVENT_PAUSE)
        return;
    st = rc->CurrentRCState;
    replaying = st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE
                || st == RCSTATE_AUTO_REPLAY
                || racecoordinator_is_replay_demo_mode(rc);
    if (!replaying && race_are_all_players_finished_racing(pCurrentRace))
        racecoordinator_request_pause(rc, port);
}

// The first index after `cur` in `list`, wrapping, or -1 if `cur` is not
// in it.
static int next_debug_camera(const CameraMoverType *list, int n,
                             CameraMoverType cur)
{
    int i;

    for (i = 0; i < n; i++)
        if (list[i] == cur)
            return (i + 1) % n;
    return -1;
}

void player_change_debug_camera_joy_handler(struct Player *p,
                                            JoystickPort port, JoyEvent ev,
                                            uint8_t value)
{
    CameraMoverType cur, t;
    int             i;

    (void)port;
    (void)ev;
    (void)value;
    if (!DebugCamerasEnabled)
        return;
    cur = p->pCameraMover != NULL ? p->pCameraMover->Type : CM_NONE;
    if (p->PlayerInputMode == PLAYER_MODE_AI_DEMO) {
        i = next_debug_camera(DebugCamerasAIDemo, 3, cur);
        if (i < 0)
            return;
        t = DebugCamerasAIDemo[i];
        if (t != CM_NONE)
            racecoordinator_suspend_demo_cameras(pRaceCoordinator);
        player_change_camera_mover(p, t, 0);
        if (t == CM_NONE)
            racecoordinator_resume_demo_cameras(pRaceCoordinator);
    } else {
        i = next_debug_camera(DebugCameras, 4, cur);
        if (i < 0)
            return;
        player_change_camera_mover(p, DebugCameras[i], 0);
    }
}
