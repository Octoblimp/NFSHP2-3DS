// pausemenu -- the pause menu; pausemenu.h has the map.

#include "pausemenu.h"

#include <string.h>

#include "bmem.h"
#include "flailer.h"
#include "joyevent.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racefinish.h"
#include "raceparams.h"
#include "rcpost.h"
#include "rcstates.h"
#include "replay.h"
#include "trackflow.h"

const char kPauseMenuScreen[] = "Pause Menu";
const char kPauseOptionsScreen[] = "Pause Options";
const char kPauseAudioScreen[] = "Pause audio";
const char kPauseDisplayScreen[] = "Pause display";
const char kPauseDebugMenuScreen[] = "Debug Menu";
const char kPauseRaceObjectiveScreen[] = "Race Objective";
const char kPauseRaceObjective2PBACScreen[] = "Race Objective 2PBAC";
const char kPauseBACControlsScreen[] = "Pause BAC controls";

void (*gGrayMenuItemFn)(uint32_t item, int32_t mode, uint32_t screen);
void (*gSetScreenFilterPortFn)(const char *name, JoystickPort port);
void (*gPortStopForceFn)(JoystickPort port);
void (*gSummonPopupFn)(const BPopupConfig *cfg);
const struct BScreenConfig *(*gFlailerCurrentScreenFn)(void);
const char *(*gPauseTranslateFn)(int32_t id);
BAnim *(*gPauseMenuAnimFn)(void);
int32_t (*gReplayNumInstantReplaySnapshotsFn)(const struct ReplayManager *rm);

// GrayMenuItem's modes.
#define GRAY_DISABLE 0
#define GRAY_ENABLE  1
#define GRAY_HIDE    2

// The popups' Flags: left and right move between Yes and No, and BACK is
// No. The Quit popup stays up after Yes, over the unloading.
#define RESTART_POPUP_FLAGS (BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE)
#define QUIT_POPUP_FLAGS \
    (BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE | BPOPUP_KEEP_VISIBLE)

// ------------------------------------------------------------- the seams

static BAnim *anim(void)
{
    return gPauseMenuAnimFn != NULL ? gPauseMenuAnimFn() : NULL;
}

static void gray_menu_item(uint32_t item, int32_t mode, uint32_t screen)
{
    if (gGrayMenuItemFn != NULL)
        gGrayMenuItemFn(item, mode, screen);
}

static void set_screen_filter_port(const char *name, JoystickPort port)
{
    if (gSetScreenFilterPortFn != NULL)
        gSetScreenFilterPortFn(name, port);
}

static void port_stop_force(JoystickPort port)
{
    if (gPortStopForceFn != NULL)
        gPortStopForceFn(port);
}

static void change_to_screen(const char *name, int32_t push)
{
    if (gChangeToScreenFn != NULL)
        gChangeToScreenFn(name, push);
}

static void set_screen_visibility(uint32_t screen, int visibility)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, visibility);
}

static const char *translate(int32_t id)
{
    return gPauseTranslateFn != NULL ? gPauseTranslateFn(id) : NULL;
}

// RequestUnPause on pRaceCoordinator, which retail passes without a test:
// the menu is up only in a race.
static void request_unpause(UnPauseReasonType reason)
{
    racecoordinator_request_unpause(pRaceCoordinator, reason);
}

// View Replay is there when the replay holds an instant-replay snapshot
// and its word at +12 is clear. Retail reads both through pReplayManager
// with no test, since InitForRace always makes one; the port's is NULL
// until the replay is ported, which reads as no replay.
static int32_t replay_mode(void)
{
    const struct ReplayManager *rm = pReplayManager;

    if (rm == NULL || gReplayNumInstantReplaySnapshotsFn == NULL
        || gReplayNumInstantReplaySnapshotsFn(rm) == 0)
        return GRAY_DISABLE;
    if (gReplayMuteHighlightsFn != NULL && gReplayMuteHighlightsFn(rm) != 0)
        return GRAY_DISABLE;
    return GRAY_ENABLE;
}

// --------------------------------------------------------------- the bloom

void pause_highlight_handle_message(BHighlightAnim *h, BScreenMessage msg,
                                    const BScreenCallbackData *data)
{
    BAnim *a;

    if (msg == BMSG_SCREEN_TICK) {
        if ((a = anim()) != NULL)
            banim_highlight_animate(a, h);
    } else if (msg == BMSG_MENUITEM_HIGHLIGHT) {
        if ((a = anim()) != NULL)
            banim_highlight_set_item(a, h, data->itemHash);
    }
}

// ---------------------------------------------------------------- the class

PauseMenu *pause_menu_construct(PauseMenu *m)
{
    BAnim *a = anim();

    if (a != NULL)
        banim_highlight_init(a, &m->Highlight, PAUSE_MENU_SCREEN,
                             PAUSE_MENU_OBJ_BLOOM,
                             (int32_t)BANIM_BLOOM_COLOR);
    else
        memset(&m->Highlight, 0, sizeof m->Highlight);
    m->ReplayChooser = -1;
    m->State = PAUSE_MENU_STATE_NONE;
    m->ScreenHash = 0;
    m->Port = -1;
    m->OptionsChooser = -1;
    m->PausingPlayer = NULL;
    return m;
}

// ~tHighlightAnimation with 2 frees nothing.
void pause_menu_destroy(PauseMenu *m, int32_t flags)
{
    if (flags & 1)
        bFree(m);
}

void pause_menu_enter_pause(PauseMenu *m, JoystickPort port)
{
    struct Player *p0, *p1;

    m->PausingPlayer = NULL;
    m->Port = port;
    p0 = PlayerPlayersByNumber[0];
    p1 = PlayerPlayersByNumber[1];
    if (p0 != NULL && p0->JoyPort == port)
        m->PausingPlayer = p0;
    else if (p1 != NULL && p1->JoyPort == m->Port)
        m->PausingPlayer = p1;
    if (p0 != NULL)
        port_stop_force(p0->JoyPort);
    if (p1 != NULL)
        port_stop_force(p1->JoyPort);
    set_screen_filter_port(kPauseMenuScreen, m->Port);
    set_screen_filter_port(kPauseOptionsScreen, m->Port);
    set_screen_filter_port(kPauseAudioScreen, m->Port);
    set_screen_filter_port(kPauseDisplayScreen, m->Port);
    set_screen_filter_port(kPauseDebugMenuScreen, m->Port);
    set_screen_filter_port(kPauseRaceObjectiveScreen, m->Port);
    set_screen_filter_port(kPauseRaceObjective2PBACScreen, m->Port);
    set_screen_filter_port(kPauseBACControlsScreen, m->Port);
}

void pause_menu_exit_pause(PauseMenu *m)
{
    m->State = PAUSE_MENU_STATE_NONE;
    m->Port = -1;
    m->PausingPlayer = NULL;
}

void pause_menu_activate(PauseMenu *m, uint32_t hash)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t quit, resume, restart;

    m->ScreenHash = hash;
    m->State = PAUSE_MENU_STATE_MENU;
    gray_menu_item(PAUSE_MENU_ITEM_REPLAY, replay_mode(), m->ScreenHash);
    gray_menu_item(PAUSE_MENU_ITEM_OBJECTIVE,
                   rp->HasObjective || rp->BeACop ? GRAY_ENABLE : GRAY_HIDE,
                   m->ScreenHash);
    gray_menu_item(PAUSE_MENU_ITEM_COP_CONTROLS,
                   rp->BeACop ? GRAY_ENABLE : GRAY_HIDE, m->ScreenHash);
    gray_menu_item(PAUSE_MENU_ITEM_QUIT,
                   race_are_all_players_finished_racing(pCurrentRace)
                       ? GRAY_DISABLE : GRAY_ENABLE,
                   m->ScreenHash);
    // Debug is shown only when 0x0016fdb0 answers true and gp-24040 is
    // clear. On the retail disc 0x0016fdb0 is `return 0`.
    gray_menu_item(PAUSE_MENU_ITEM_DEBUG, GRAY_HIDE, m->ScreenHash);

    if (race_parameters_is_free_run(&TheRaceParameters)) {
        quit = 0x30d48;
        resume = 0x30d4c;
        restart = 0x30d4e;
    } else if (rp->EventTreeRace) {
        quit = 0x30d4a;
        resume = 0x30d4b;
        restart = 0x30d45;
    } else if (rp->BeACop) {
        quit = 0x30d52;
        resume = 0x30d50;
        restart = 0x30d51;
    } else {
        quit = 0x30d46;
        resume = 0x30d4f;
        restart = 0x30d45;
    }
    flailer_set_language_id(m->ScreenHash, PAUSE_MENU_ITEM_QUIT,
                            (uint32_t)quit);
    flailer_set_language_id(m->ScreenHash, PAUSE_MENU_ITEM_RESUME,
                            (uint32_t)resume);
    flailer_set_language_id(m->ScreenHash, PAUSE_MENU_ITEM_RESTART,
                            (uint32_t)restart);
}

void pause_menu_deactivate(PauseMenu *m)
{
    m->ScreenHash = 0;
    m->State = PAUSE_MENU_STATE_MENU;
}

int32_t pause_menu_all_player_joysticks_plugged_in(const PauseMenu *m)
{
    int32_t ok = 1;
    int32_t i;

    (void)m;
    for (i = 0; i < PlayerNumPlayers; i++)
        ok = (ok & IsJoystickPluggedIn(PlayerPlayersByIndex[i]->JoyPort))
             != 0;
    return ok;
}

void pause_menu_check_joysticks(PauseMenu *m)
{
    (void)m;
}

// The Yes/No popup over the menu, and the menu hidden under it. Retail
// leaves DismissParam and PopupID unwritten; nothing on this path reads
// either, and the port zeroes them.
static void summon(PauseMenu *m, uint32_t flags, int32_t yesParam,
                   int32_t message, int32_t title)
{
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons = 2;
    cfg.flags = flags;
    cfg.parent = gFlailerCurrentScreenFn != NULL ? gFlailerCurrentScreenFn()
                                                 : NULL;
    cfg.screen = PAUSE_POPUP_SCREEN;
    cfg.message = translate(message);
    cfg.button[0] = PAUSE_LANG_YES;
    cfg.button[1] = PAUSE_LANG_NO;
    cfg.button[2] = 0;
    cfg.buttonParam[0] = yesParam;
    cfg.buttonParam[1] = 0;
    cfg.buttonParam[2] = 0;
    cfg.cancelParam = 0;
    cfg.startButton = 1;
    cfg.joyPort = m->Port;
    cfg.timeout = 0;
    cfg.title = title;
    if (gSummonPopupFn != NULL)
        gSummonPopupFn(&cfg);
}

void pause_menu_maybe_restart(PauseMenu *m)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t message, title;

    if (!pause_menu_all_player_joysticks_plugged_in(m))
        return;
    if (race_parameters_is_free_run(&TheRaceParameters)) {
        message = 0x3827f;
        title = 0x38289;
    } else if (!rp->EventTreeRace && rp->BeACop) {
        message = 0x38281;
        title = 0x38285;
    } else {
        message = 0x38271;
        title = 0x38279;
    }
    summon(m, RESTART_POPUP_FLAGS, PAUSE_MENU_STATE_RESTART, message, title);
    m->State = PAUSE_MENU_STATE_RESTART;
    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_INVISIBLE);
}

void pause_menu_maybe_quit(PauseMenu *m)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t message, title;

    if (race_parameters_is_free_run(&TheRaceParameters)) {
        message = 0x3827d;
        title = 0x38288;
    } else if (rp->EventTreeRace) {
        message = 0x3827e;
        title = 0x38284;
    } else if (rp->BeACop) {
        message = 0x38282;
        title = 0x38283;
    } else {
        message = 0x38272;
        title = 0x3827b;
    }
    summon(m, QUIT_POPUP_FLAGS, PAUSE_MENU_STATE_QUIT, message, title);
    m->State = PAUSE_MENU_STATE_QUIT;
    set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_INVISIBLE);
}

int32_t pause_menu_maybe_resume(PauseMenu *m, int32_t port)
{
    if (!pause_menu_all_player_joysticks_plugged_in(m))
        return 0;
    // Retail reads the player with no test. EnterPause leaves it NULL
    // only for a port no player is on, which no pause comes from.
    if (m->PausingPlayer == NULL || m->PausingPlayer->JoyPort != port)
        return 0;
    request_unpause(UNPAUSE_REASON_RESUME_RACE);
    if (gRestoreTypeChangedHandlersFn != NULL)
        gRestoreTypeChangedHandlersFn();
    return 1;
}

int32_t pause_choose_who_selected_menu_item(const BScreenCallbackData *data)
{
    if (PlayerNumPlayers == 2)
        return data->port;
    return PlayerPlayersByIndex[0]->JoyPort;
}

// SELECT, in the menu only, on the item.
static void select_item(PauseMenu *m, BScreenCallbackData *data)
{
    const RaceParameters *rp = &TheRaceParameters;

    switch (data->itemHash) {
    case PAUSE_MENU_ITEM_RESUME:
        pause_menu_maybe_resume(m, data->port);
        break;
    case PAUSE_MENU_ITEM_RESTART:
        pause_menu_maybe_restart(m);
        break;
    case PAUSE_MENU_ITEM_OPTIONS:
        m->OptionsChooser = pause_choose_who_selected_menu_item(data);
        change_to_screen(kPauseOptionsScreen, 0);
        break;
    case PAUSE_MENU_ITEM_REPLAY:
        m->ReplayChooser = pause_choose_who_selected_menu_item(data);
        request_unpause(UNPAUSE_REASON_INSTANT_REPLAY);
        break;
    case PAUSE_MENU_ITEM_OBJECTIVE:
        if (rp->NumPlayerCars == 2 && rp->BeACop)
            change_to_screen(kPauseRaceObjective2PBACScreen, 0);
        else
            change_to_screen(kPauseRaceObjectiveScreen, 0);
        break;
    case PAUSE_MENU_ITEM_COP_CONTROLS:
        change_to_screen(kPauseBACControlsScreen, 0);
        break;
    case PAUSE_MENU_ITEM_QUIT:
        pause_menu_maybe_quit(m);
        break;
    case PAUSE_MENU_ITEM_DEBUG:
        change_to_screen(kPauseDebugMenuScreen, 0);
        break;
    default:
        break;
    }
}

// The popup's answer. Yes on Restart keeps what each player changed in
// the pause options for the race again: their PlayerSettings go back to
// TheRaceParameters by PlayerNumber. No shows the menu again; the Quit
// popup, which Dismiss leaves up, is hidden by hand.
static void popup_dismissed(PauseMenu *m, BScreenCallbackData *data)
{
    int32_t i;

    if (m->State == PAUSE_MENU_STATE_RESTART) {
        if (data->param != 0) {
            for (i = 0; i < PlayerNumPlayers; i++) {
                struct Player *p = PlayerPlayersByIndex[i];

                TheRaceParameters.PlayerSettings[p->PlayerNumber] =
                    p->PlayerSettings;
            }
            request_unpause(UNPAUSE_REASON_RESTART_RACE);
            return;
        }
        set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_VISIBLE);
    } else if (m->State == PAUSE_MENU_STATE_QUIT) {
        if (data->param != 0) {
            request_unpause(UNPAUSE_REASON_QUIT_RACE);
            return;
        }
        set_screen_visibility(m->ScreenHash, FLAILER_SCREEN_VISIBLE);
        set_screen_visibility(PAUSE_POPUP_SCREEN, FLAILER_SCREEN_INVISIBLE);
    } else {
        return;
    }
    m->State = PAUSE_MENU_STATE_MENU;
}

void pause_menu_menu_callback(PauseMenu *m, BScreenMessage msg,
                              BScreenCallbackData *data)
{
    pause_highlight_handle_message(&m->Highlight, msg, data);
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (m->State == PAUSE_MENU_STATE_MENU)
            select_item(m, data);
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        data->noise = 0;
        data->param = 0;
        break;
    case BMSG_SCREEN_START_BUTTON:
        if (pause_menu_maybe_resume(m, data->port))
            data->noise = BSND_MENU_START;
        data->param = 1;
        break;
    case BMSG_SCREEN_TICK:
        pause_menu_check_joysticks(m);
        break;
    case BMSG_POPUP_DISMISS:
        popup_dismissed(m, data);
        break;
    default:
        break;
    }
}

void pause_menu_callback(struct BGameFlow *gf, BScreenMessage msg,
                         BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        if (ThePauseMenu->State == PAUSE_MENU_STATE_NONE)
            pause_menu_enter_pause(ThePauseMenu,
                                   pRaceCoordinator->PausedJoystickPort);
        pause_menu_activate(ThePauseMenu, data->itemHash);
        data->param = 0;
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        pause_menu_deactivate(ThePauseMenu);
    } else {
        pause_menu_menu_callback(ThePauseMenu, msg, data);
    }
}
