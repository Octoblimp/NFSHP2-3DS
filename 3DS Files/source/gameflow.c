// The boot flow. See gameflow.h, and docs/formats/boot-flow.md for the
// decompilation this is a port of -- every rule below names an address.

#include "gameflow.h"
#include "portlang.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

// ---------------------------------------------------------------- tracing

static void trace(BGameFlow* gf, const char* fmt, ...)
{
    char    line[192];
    va_list ap;
    if (!gf->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    gf->hooks.trace(gf->hooks.user, line);
}

// Hook shims. A missing hook is a no-op, and a missing question answers
// "ready", so a host test only has to supply what it is testing.
#define HOOK_VOID(gf, fn, ...)                                       \
    do {                                                             \
        if ((gf)->hooks.fn) (gf)->hooks.fn((gf)->hooks.user, __VA_ARGS__); \
    } while (0)

// The same, for the hooks that take nothing but `user`.
#define HOOK_VOID0(gf, fn) do { if ((gf)->hooks.fn) (gf)->hooks.fn((gf)->hooks.user); } while (0)

static void screenVisible(BGameFlow* gf, uint32_t screen, int visible)
{
    trace(gf, "vis screen %08x %d", (unsigned)screen, visible);
    HOOK_VOID(gf, setScreenVisible, screen, visible);
}

static void objectVisible(BGameFlow* gf, uint32_t screen, uint32_t object,
                          int visible)
{
    trace(gf, "vis object %08x %08x %d", (unsigned)screen, (unsigned)object,
          visible);
    HOOK_VOID(gf, setObjectVisible, screen, object, visible);
}

static void groupVisible(BGameFlow* gf, uint32_t screen, uint32_t group,
                         int visible)
{
    trace(gf, "vis group %08x %08x %d", (unsigned)screen, (unsigned)group,
          visible);
    HOOK_VOID(gf, setGroupVisible, screen, group, visible);
}

static void changeTexture(BGameFlow* gf, uint32_t screen, uint32_t object,
                          uint32_t texture)
{
    trace(gf, "tex change %08x %08x %08x", (unsigned)screen, (unsigned)object,
          (unsigned)texture);
    HOOK_VOID(gf, changeTexture, screen, object, texture);
}

static void makeSound(BGameFlow* gf, int soundEvent)
{
    if (soundEvent == BSND_NONE) return;
    trace(gf, "sound %d", soundEvent);
    HOOK_VOID(gf, sound, soundEvent);
}

// ------------------------------------------------------------ screen stack

// bStrCpy into a 32-byte slot. ScreenStack::Push (0x00166780) does not
// bound-check either end; this one refuses rather than corrupting memory,
// and says so, because a port that overruns here is very hard to debug.
static void copyName(char* dst, const char* src)
{
    size_t i = 0;
    if (src) {
        for (; i + 1 < BGF_NAME_LEN && src[i]; i++) dst[i] = src[i];
    }
    dst[i] = '\0';
}

void bgf_push_screen(BGameFlow* gf, const char* name)
{
    if (gf->stack.index >= BGF_STACK_DEPTH) {
        trace(gf, "stack overflow %s", name ? name : "");
        return;
    }
    copyName(gf->stack.names[gf->stack.index], name);
    gf->stack.index++;
    trace(gf, "stack push %d %s", gf->stack.index, name ? name : "");
}

const char* bgf_pop_screen(BGameFlow* gf)
{
    if (gf->stack.index == 0) return NULL;
    gf->stack.index--;
    trace(gf, "stack pop %d %s", gf->stack.index,
          gf->stack.names[gf->stack.index]);
    return gf->stack.names[gf->stack.index];
}

void bgf_reset_stack(BGameFlow* gf)
{
    memset(&gf->stack, 0, sizeof(gf->stack));
    trace(gf, "stack reset");
}

void bgf_pop_screens(BGameFlow* gf, int n)
{
    while (n-- > 0 && bgf_pop_screen(gf) != NULL) {
    }
}

const char* bgf_stack_top(const BGameFlow* gf)
{
    // GetCurrentScreenNameFromStack (0x00167bf0) returns the empty string at
    // 0x00323670 when the stack is empty, not NULL.
    if (gf->stack.index == 0) return "";
    return gf->stack.names[gf->stack.index - 1];
}

void bgf_pop_until(BGameFlow* gf, const char* name)
{
    for (;;) {
        const char* top = bgf_stack_top(gf);
        if (top[0] == '\0') return;                  // exhausted
        if (name && strcmp(top, name) == 0) return;  // found it, leave it on
        bgf_pop_screen(gf);
    }
}

// ------------------------------------------------------------- screen list

const BScreenConfig* bgf_find_screen(const BGameFlow* gf, const char* name)
{
    if (!name || !name[0]) return NULL;
    for (int i = 0; i < gf->numScreens; i++)
        if (gf->screens[i].name && strcmp(gf->screens[i].name, name) == 0)
            return &gf->screens[i];
    return NULL;
}

int bgf_send(BGameFlow* gf, BScreenMessage msg, BScreenCallbackData* data)
{
    const BScreenConfig* s = gf->screen;
    if (!s || !s->callback) return 0;
    trace(gf, "msg %s %d", s->name, (int)msg);
    s->callback(gf, msg, data);
    return 1;
}

// The Noise an event starts with, before the callback can change it: what
// the JoyHandler that raises it seeds -- FlailerMenuItem's gives a select
// FE_SOUND_MENU_SELECT (demo 0x001651d8), FlailerMenu's gives the two
// scrolls theirs (demo 0x00165820), and the rest start silent. bmenu.c
// seeds the same. A callback that wants quiet writes 0, as the title does.
static int joyNoise(BScreenMessage msg)
{
    switch (msg) {
        case BMSG_MENUITEM_SELECT:   return BSND_MENU_SELECT;
        case BMSG_MENUITEM_PAD_UP:   return BSND_MENU_UP;
        case BMSG_MENUITEM_PAD_DOWN: return BSND_MENU_DOWN;
        default:                     return BSND_NONE;
    }
}

int bgf_screen_event(BGameFlow* gf, BScreenMessage msg, int port)
{
    BScreenCallbackData data;
    memset(&data, 0, sizeof(data));
    data.port  = port;
    data.param = 1;
    data.noise = joyNoise(msg);
    if (gf->screen) data.itemHash = gf->screen->hash;
    if (!bgf_send(gf, msg, &data)) return 0;
    makeSound(gf, data.noise);
    return 1;
}

int bgf_menu_item_event(BGameFlow* gf, BScreenMessage msg, uint32_t itemHash,
                        int port)
{
    BScreenCallbackData data;
    memset(&data, 0, sizeof(data));
    data.port     = port;
    data.param    = 1;
    data.noise    = joyNoise(msg);
    data.itemHash = itemHash;
    if (!bgf_send(gf, msg, &data)) return 0;
    makeSound(gf, data.noise);
    return 1;
}

// -- the panel movie ---------------------------------------------------------
//
// Retail keeps six texture handles, +460..+480: PANELMOVIE's and the five
// planes of MOVIE_256_384 that the player's frames land in. They are looked
// up by name every StartMovie, and PANELMOVIE's is read without a test, so
// it is always there; +460 is only ever the gate, which is all
// `panelMovie` is. The name goes through bStrCmp (0x002535f8), a strcmp.

void bgf_start_movie(BGameFlow* gf, const char* name)
{
    if (gf->skipMovies) return;
    if (gf->panelMovie) {
        if (strcmp(name, gf->panelMovieName) == 0) return;
        bgf_stop_movie(gf);
    }
    gf->panelMovie = 1;
    HOOK_VOID0(gf, movieClose);
    gf->panelMovieName = name;
    // InitFile's answer is not read.
    if (gf->hooks.panelMovieOpen)
        gf->hooks.panelMovieOpen(gf->hooks.user, name);
}

// Update's answer is 0 or 1, and anything but 1 opens the file again
// (0x0016d074). RealTimeElapsed goes in $f12 and is not read.
void bgf_update_movie(BGameFlow* gf)
{
    if (!gf->panelMovie) return;
    if (gf->hooks.inGame && gf->hooks.inGame(gf->hooks.user)) {
        bgf_stop_movie(gf);
        return;
    }
    if (!gf->hooks.panelMovieUpdate
        || gf->hooks.panelMovieUpdate(gf->hooks.user) == 1)
        return;
    if (gf->hooks.panelMovieOpen)
        gf->hooks.panelMovieOpen(gf->hooks.user, gf->panelMovieName);
}

void bgf_stop_movie(BGameFlow* gf)
{
    if (!gf->panelMovie) return;
    HOOK_VOID0(gf, movieClose);
    gf->panelMovie = 0;
}

int bgf_change_to_screen(BGameFlow* gf, const char* name, int pushCurrent)
{
    const BScreenConfig* old = gf->screen;

    trace(gf, "change %s %d", name ? name : "(null)", pushCurrent);

    if (old) {
        BScreenCallbackData data;
        screenVisible(gf, old->hash, 0);
        // The push happens between hiding and unactivating, and pushes the
        // OUTGOING screen's name -- that is what makes BACK come back here.
        if (pushCurrent) bgf_push_screen(gf, old->name);
        // FlailerScreen::UnActivate (0x0016a940): the item the menu is on,
        // kept for the next Activate; the menu unactivated and deleted;
        // and only then SCREEN_UNACTIVATE, to a screen with no menu.
        if (gf->hooks.closeMenu) {
            int item = gf->hooks.closeMenu(gf->hooks.user, old);
            int row  = (int)(old - gf->screens);
            if (item >= 0 && row >= 0 && row < BGF_MAX_SCREENS)
                gf->savedItem[row] = item;
        }
        memset(&data, 0, sizeof(data));
        data.itemHash = old->hash;
        bgf_send(gf, BMSG_SCREEN_UNACTIVATE, &data);
        HOOK_VOID(gf, leaveScreen, old);
        trace(gf, "leave %s %08x", old->name, (unsigned)old->hash);
        gf->screen = NULL;
    }

    // Anything that does not resolve leaves the flow with no current screen.
    // ChangeToScreen clears pCurrent before it looks the new name up, so a
    // miss is not "stay where you were".
    if (name && name[0]) {
        const BScreenConfig* n = bgf_find_screen(gf, name);
        if (!n) {
            trace(gf, "unregistered %s", name);
        } else {
            BScreenCallbackData data;
            gf->screen = n;
            screenVisible(gf, n->hash, 1);
            trace(gf, "enter %s %08x", n->name, (unsigned)n->hash);
            // FlailerScreen::Activate (0x0016a858) in its order: build the
            // FlailerMenu, send SCREEN_ACTIVATE, then set the current item
            // and activate the menu. The menu exists before the screen's
            // constructor runs, which is what lets the constructor gray an
            // item of it -- the language screen hides MENUITEM_7, Options
            // hides its Languages item on NTSC. The opening
            // MENUITEM_HIGHLIGHT is after, so it reaches a screen object that
            // exists: sent first, the brackets and the blurb stay where the
            // bundle authored them until the player moves.
            HOOK_VOID(gf, openScreen, n);
            memset(&data, 0, sizeof(data));
            data.itemHash = n->hash;
            // The reply: a Param other than -1 puts the menu on item
            // Param - 1 (Select Track answers its time of day's item) and
            // is kept; -1 leaves the item the screen was last left on.
            // The noise is played after the callback, as BACK's is.
            data.param = -1;
            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);
            {
                int row = (int)(n - gf->screens);
                int ok  = row >= 0 && row < BGF_MAX_SCREENS;
                if (data.param != -1 && ok) gf->savedItem[row] = data.param - 1;
                gf->activateItem = data.param != -1 ? data.param - 1
                                 : ok ? gf->savedItem[row] : 0;
            }
            makeSound(gf, data.noise);
            HOOK_VOID(gf, enterScreen, n);
        }
    }
    return gf->screen != NULL;
}

int bgf_move_to_previous_screen(BGameFlow* gf, int n, int sendBackButton,
                                int port)
{
    BScreenCallbackData data;
    char                name[BGF_NAME_LEN];

    // Memset, so ItemHash is 0: BACK names no item.
    memset(&data, 0, sizeof(data));
    data.port  = port;
    data.param = 1;
    data.noise = BSND_MENU_CANCEL;

    if (sendBackButton) {
        bgf_send(gf, BMSG_SCREEN_BACK_BUTTON, &data);
        // The sound is read back AFTER the callback, so a screen that wants
        // silence writes noise = 0 -- which the title screen does.
        makeSound(gf, data.noise);
    }
    if (data.param != 1) {
        trace(gf, "back vetoed");
        return 0;
    }

    name[0] = '\0';
    for (int i = 0; i < n; i++) {
        const char* p = bgf_pop_screen(gf);
        copyName(name, p);
        if (!p) break;
    }
    if (name[0] == '\0') {
        // Popped to nothing. The original tests bStrLen here and simply does
        // not call ChangeToScreen, which is why an exhausted stack leaves
        // the screen where it is instead of blanking it.
        trace(gf, "back to nothing");
        return 0;
    }
    bgf_change_to_screen(gf, name, 0);
    return 1;
}

int bgf_move_back_screen(BGameFlow* gf, int n)
{
    return bgf_move_to_previous_screen(gf, n, 0, -1);
}

int bgf_back_button(BGameFlow* gf, int port)
{
    return bgf_move_to_previous_screen(gf, 1, 1, port);
}

// ---------------------------------------------------------------- the flow

void bgf_change_state(BGameFlow* gf, int desired, int pending)
{
    gf->desired = desired;
    gf->pending = pending;   // never read by ServiceGameFlow; see trackflow.c
    trace(gf, "want %s", bgf_state_name(gf, desired));
}

const char* bgf_state_name(const BGameFlow* gf, int state)
{
    if (state < 0 || state >= gf->numStates) return "?";
    return gf->states[state].name ? gf->states[state].name : "?";
}

void bgf_service(BGameFlow* gf)
{
    // Guard against a Loop that redirects forever. The original has no such
    // guard; it would simply hang, and so would the port without this.
    for (int guard = 0; guard < 64; guard++) {
        const BGameFlowStateInfo* info;
        if (gf->current != gf->desired) {
            // The OLD state's End runs before the NEW state's Begin, which
            // is why EndGameFlowLoadingFrontEnd -- the thing that actually
            // starts the frontend -- runs on the way OUT of LOADING_FRONTEND.
            info = &gf->states[gf->current];
            if (info->end) {
                trace(gf, "end %s", bgf_state_name(gf, gf->current));
                info->end(gf);
            }
            gf->current = gf->desired;
            info = &gf->states[gf->current];
            trace(gf, "state %s", bgf_state_name(gf, gf->current));
            if (info->begin) {
                trace(gf, "begin %s", bgf_state_name(gf, gf->current));
                info->begin(gf);
            }
        }
        info = &gf->states[gf->current];
        if (info->loop) info->loop(gf);
        if (gf->current == gf->desired) return;
    }
    trace(gf, "service stuck %s", bgf_state_name(gf, gf->current));
}

void bgf_advance_time(BGameFlow* gf, float dt)
{
    int n;
    gf->accum += dt;
    n = (int)(gf->accum * 60.0f);
    // At least one tick a frame even when the timestep rounds to zero, so
    // RealTime is a frame counter that tracks wall-clock when frames are slow.
    gf->realTime += (n != 0) ? (uint32_t)n : 1u;
    gf->accum -= (float)n * (1.0f / 60.0f);
    gf->realTimer += (uint32_t)(int)(dt * 4000.0f);
    gf->realElapsed = dt;
    gf->frameCounter++;
}

void bgf_frame(BGameFlow* gf, float dt)
{
    bgf_advance_time(gf, dt);
    bgf_service(gf);
    if (gf->screen) {
        BScreenCallbackData data;
        memset(&data, 0, sizeof(data));
        data.itemHash = gf->screen->hash;
        bgf_send(gf, BMSG_SCREEN_TICK, &data);
    }
    // FlailerScreenList::Tick (0x0016cca8) ticks both popups after the
    // screen, up or not, then the movie and the song monitor.
    bpopup_tick(gf);
    bgf_update_movie(gf);
    HOOK_VOID0(gf, songMonitor);
    bgf_service(gf);
}

void bgf_init(BGameFlow* gf,
              const BGameFlowStateInfo* states, int numStates,
              const BScreenConfig* screens, int numScreens,
              const BBootStage* bootStages, int numBootStages,
              const BGameFlowHooks* hooks)
{
    memset(gf, 0, sizeof(*gf));
    gf->states        = states;
    gf->numStates     = numStates;
    gf->screens       = screens;
    gf->numScreens    = numScreens;
    gf->bootStages    = bootStages;
    gf->numBootStages = numBootStages;
    if (hooks) gf->hooks = *hooks;

    gf->current = BGF_NONE;
    gf->desired = BGF_NONE;

    // The values the PS2 image ships with, read out of .data because
    // nothing in the image writes them.
    gf->frontendLaunchType   = 1;
    gf->skipFE               = 0;
    gf->skipMovies           = 0;
    gf->copsOn               = 0;
    // VIDEO_MODE { MODE_PAL = 0, MODE_NTSC = 1 }, and note which way round
    // that makes ShouldSeeLanguageSelectScreen: NTSC skips the language
    // screen, PAL shows it. InitDisplaySystem (0x00100750) picks it with
    // bFileExists("PAL.TAG"), and the retail disc, SLES_507.31, has PAL.TAG
    // in its ZDIR (entry 405, bf0a6606): it is a PAL disc, and it asks for a
    // language on every boot, as it does on PCSX2.
    gf->videoMode            = 0;
    // LanguageManager's constructor (0x0021dfa8). LoadGlobalChunks sets
    // English before the flow starts; see bgf_load_global_chunks.
    gf->currLanguage         = -1;
    gf->demoModeStatus       = 0;
    gf->legalScreenTimeout   = 7.0f;
    gf->antiPiracyTimeout    = 7.0f;
    gf->beginDemoModeTimeout = 30.0f;

    // FlailerScreenList's constructor makes its two popups.
    bpopup_init(gf);
}

// ---------------------------------------------------------- the predicates

int bgf_should_see_title_sequence(const BGameFlow* gf)
{
    return (unsigned)(gf->frontendLaunchType - 1) < 2u;
}

int bgf_should_see_legal_mumbo_jumbo(const BGameFlow* gf)
{
    // 0x0016aa28 is `return 0`. The screen is authored and shipped
    // (0xdd4197c9 in FRONTB.BUN) and nothing can reach it.
    (void)gf;
    return 0;
}

// Both of these begin, on the disc, with a return 0 for the demo disc
// (TheDemoDiscManager.bActive). The port has no demo disc, so they begin
// after it.
int bgf_should_see_language_select(const BGameFlow* gf)
{
    if (gf->frontendLaunchType == 1 && gf->currLanguage == -1) return 1;
    if (gf->videoMode != 0) return 0;   // NTSC never asks
    return gf->frontendLaunchType == 1;
}

int bgf_should_see_autoload(const BGameFlow* gf)
{
    return gf->frontendLaunchType == 1;
}

// ------------------------------------------------------- LaunchFrontendMenus

void bgf_launch_frontend_menus(BGameFlow* gf)
{
    char name[BGF_NAME_LEN];

    if (gf->frontendLaunchType == 2 && gf->demoModeStatus == 2) {
        bgf_reset_stack(gf);
        bgf_change_to_screen(gf, "New Main Menu", 1);
        return;
    }

    for (int i = 0; i < gf->numBootStages; i++) {
        const BBootStage* stage = &gf->bootStages[i];
        if (stage->shouldSee && !stage->shouldSee(gf)) continue;
        bgf_push_screen(gf, stage->screenName);
    }

    // The stack is a LIFO and this immediately pops its own top, so the LAST
    // stage pushed is the FIRST screen seen. Copy before popping: the
    // original keeps a pointer into the stack, which stays valid only
    // because PopScreens does not clear the slot.
    copyName(name, bgf_stack_top(gf));
    bgf_pop_screens(gf, 1);

    // The original also clears Fred.SelectedEventData here when the name is
    // "View Event Tree". It is a real screen -- FlailerScreenConfigList
    // registers it on tEventTreeView, 0x147f8a59 -- but nothing pushes it as
    // a boot stage, and the name tested here is the one just popped off the
    // boot stack, so the branch can only ever have fired for a caller that
    // no longer exists.
    bgf_change_to_screen(gf, name, 0);
}

static int onStack(const BGameFlow* gf, const char* name)
{
    for (int k = 0; k < gf->stack.index; k++)
        if (!strcmp(gf->stack.names[k], name)) return 1;
    return 0;
}

// ScreenStack::Print, before and after the pops, is a debug dump.
void bgf_unlaunch_frontend_menus(BGameFlow* gf)
{
    int gameType = gf->hooks.gameType ? gf->hooks.gameType(gf->hooks.user)
                                      : 0;
    int demo = gf->hooks.raceDemo ? gf->hooks.raceDemo(gf->hooks.user) : 0;
    const char* back = gf->hooks.raceReturn
                     ? gf->hooks.raceReturn(gf->hooks.user) : NULL;

    // Back to where the game type began: the event tree for 8 and 9
    // (signed, as `slti` compares), the main menu for 2 to 7, and nowhere
    // for the rest. The port's own first: the screen raceReturn names.
    if (back && onStack(gf, back))
        bgf_pop_until(gf, back);
    else if (gameType == 8 || gameType == 9)
        bgf_pop_until(gf, "View Event Tree");
    else if (gameType >= 2 && gameType < 8)
        bgf_pop_until(gf, "New Main Menu");
    bgf_pop_screens(gf, 0);
    bgf_change_to_screen(gf, NULL, 0);
    // SetMainScreen(NULL). The list's pMainScreenName is set to NULL by the
    // constructor and by this, and by nothing else -- so the "arriving at
    // the main screen resets the stack" tail of ChangeToScreen is dead on
    // this build and is not ported.
    HOOK_VOID(gf, jukebox, 0);
    gf->frontendLaunchType = demo ? 2 : 3;
    trace(gf, "unlaunch %d", gf->frontendLaunchType);
    bgf_stop_movie(gf);                // 0x0016fb74, after the launch type
    HOOK_VOID0(gf, songMonitorReset);
    // Then tHelpMenu::Reset (0x001e3db8) when the list has a help menu
    // (+452). The help menu is not ported, so there is none.
}

void bgf_consider_start_demo_mode(BGameFlow* gf, const uint32_t* timer)
{
    // BeginDemoModeTimeout (0x0032feb4) against the Timer's age, signed.
    // The disc also goes at once on the demo disc in attract mode
    // (DemoDiscManager::IsAttractMode); the port has no demo disc.
    int go = gf->beginDemoModeTimeout
             < (float)(int32_t)(gf->realTimer - *timer) * 0.00025f;
    if (!go) return;

    // TheDemoModeReplay (0x002f0960): while one loads, wait for it; once
    // it has loaded, play it and start the race behind it; with none, try
    // to launch one, and start the race only if there is none to launch.
    if (gf->replayLoading) return;
    if (gf->replayLoaded) {
        trace(gf, "replay launch");
        HOOK_VOID0(gf, replayLaunch);
    } else {
        int launching = gf->hooks.replayConsiderLaunching
                            ? gf->hooks.replayConsiderLaunching(gf->hooks.user)
                            : 0;
        trace(gf, "replay consider %d", launching);
        if (launching) return;
    }
    trace(gf, "demo mode");
    bgf_stop_movie(gf);                // StartDemoMode's first call
    HOOK_VOID0(gf, startDemoMode);
}

// ------------------------------------------------------- LanguageManager

// LoadLocalizedSpeechFiles' two callers, 0x0021e250 and 0x0021e280. +20
// says the speech is in, and is written before the call.
static void loadCurrentSpeech(BGameFlow* gf)
{
    if (gf->currLanguage == -1 || gf->speechLoaded) return;
    gf->speechLoaded = 1;
    trace(gf, "speech %d", gf->currLanguage);
    HOOK_VOID(gf, loadSpeech, gf->currLanguage);
}

static void unloadSpeech(BGameFlow* gf)
{
    if (!gf->speechLoaded) return;
    gf->speechLoaded = 0;
    trace(gf, "speech unload");
    HOOK_VOID0(gf, unloadSpeech);
}

void bgf_load_current_speech(BGameFlow* gf)
{
    loadCurrentSpeech(gf);
}

void bgf_unload_current_speech(BGameFlow* gf)
{
    unloadSpeech(gf);
}

void bgf_set_curr_language(BGameFlow* gf, int language)
{
    int old = gf->currLanguage;

    if (language == old) return;
    // The outgoing table's chunks go first (UnloadChunks, 0x001992a8).
    if (old != -1) trace(gf, "language unload %d", old);
    gf->currLanguage = language;
    if (language != -1) {
        // FE_<language>.BIN into the buffer LoadGlobalChunks sized for the
        // longest of them, then LoadChunks.
        trace(gf, "language %d", language);
        HOOK_VOID(gf, setLanguage, language);
    }

    // The tail, 0x0021e1e0. Speech that is in is swapped for the new
    // language's; speech that is not stays out -- FRONTB's load callback is
    // what first brings it in.
    if (gf->speechLoaded) {
        unloadSpeech(gf);
        loadCurrentSpeech(gf);
    }
    // 0x001681b0: the LOADING logo and NFS_LOGO_ALPHA have French art, and
    // gp-21404 says which is in. Retail unloads the LOADING texture, remaps
    // it, reloads it and waits for the pack; the host does all of that.
    if ((language == 1) != (gf->logoFrench != 0)) {
        gf->logoFrench ^= 1;
        trace(gf, "logo art %d", gf->logoFrench);
        HOOK_VOID(gf, swapLogoArt, gf->logoFrench);
    }
    // FlailerUpdateLanguageText (0x00141648) re-reads every text object's
    // string. The port's renderer looks each one up as it draws.
}

// --------------------------------------------------- GAMEFLOW_STATE hooks

// LoadResourceFile, traced. A host with no loader has loaded everything
// already, so the callback runs at once.
static void loadResource(BGameFlow* gf, const char* path, BGameFlowDone done)
{
    trace(gf, "load %s", path);
    if (gf->hooks.loadResource)
        gf->hooks.loadResource(gf->hooks.user, path, done);
    else if (done)
        done(gf);
}

// 0x00168658, LoadSoundRegionsFrontEnd's callback: the frontend is in.
static void frontendSoundsLoaded(BGameFlow* gf)
{
    bgf_change_state(gf, BGF_IN_FRONTEND, BGF_NONE);
}

// 0x00168668, FRONTB's: the speech, then the frontend's sound regions.
static void frontendLoaded(BGameFlow* gf)
{
    loadCurrentSpeech(gf);
    trace(gf, "load sound regions");
    if (gf->hooks.loadSoundRegions)
        gf->hooks.loadSoundRegions(gf->hooks.user, frontendSoundsLoaded);
    else
        frontendSoundsLoaded(gf);
}

void bgf_load_global_chunks(BGameFlow* gf)
{
    bgf_set_curr_language(gf, 0);   // l_ENGLISH, through 0x00100808

    // LOADING_TRACK up. The copyright line is FRONTB's, on TITLE_IMAGE, and
    // FRONTB is not loaded yet, so the second call finds nothing: retail
    // makes it anyway. (The demo disc's slideshow started here instead.)
    screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 1);
    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 1);
    // One frame, outside MainLoop. Nothing draws again until MainLoop runs,
    // so this is the picture that stays up while the frontend loads.
    trace(gf, "display frame");
    HOOK_VOID0(gf, displayFrame);
}

void bgf_begin_loading_frontend(BGameFlow* gf)
{
    // Retail stores RealTime in BeginScreenFadeTime here, for the demo
    // disc's slideshow in the Loop, and nothing else reads it.

    // RaceParameters::InitWithDefaults, then a bCountFreeMemory whose
    // answer is kept for a debug print.
    trace(gf, "race defaults");
    HOOK_VOID0(gf, raceDefaults);

    // FRONTA.BUN is the loading bundle that was meant to stay resident while
    // FRONTB streams in. It is a zero-byte file on this disc, and so are
    // GLOBALA.BUN and INGAMEA.BUN -- the split was never used.
    loadResource(gf, "FRONTEND\\FRONTA.BUN", NULL);

    // The hot-chunking trick: load FRONTB.LZC, then tell the resource system
    // it is called FRONTB.BUN. Only the .LZC is really on the disc. Its
    // callback is what moves the flow on; the demo's language handling here
    // is gone, because LoadGlobalChunks has already set one.
    loadResource(gf, "FRONTEND\\FRONTB.LZC", frontendLoaded);
    trace(gf, "hot chunk %s", "FRONTEND\\FRONTB.BUN");
}

// Retail's LoopGameFlowLoadingFrontend (0x00168718) is the demo disc's
// three-panel slideshow and nothing else, so the port's state has no Loop:
// leaving the state is the load callbacks' job.

void bgf_end_loading_frontend(BGameFlow* gf)
{
    // eFixUpTables, InitCarEffects, InitFrontendSounds, InitSelectCarScreen
    // and InitMoviePlayer run here in the original. On the 3DS the renderer
    // and the bundles are already up by the time the flow starts, so what
    // is left is the fixup, the frontend's sounds, the car selector, the
    // visibility and the launch. (The demo disc hid its slideshow's last
    // panel instead.) The fixup matters after a race: the Begin of
    // unloading set eDisableFixUpTables, and FRONTB loaded under it.
    HOOK_VOID0(gf, fixUpTables);
    HOOK_VOID0(gf, initFrontendSounds);
    HOOK_VOID0(gf, initSelectCar);
    screenVisible(gf, BGF_SCREEN_LOADING_TRACK, 0);
    objectVisible(gf, BGF_SCREEN_LOADING_TRACK, BGF_OBJ_COPYRIGHT, 0);
    bgf_launch_frontend_menus(gf);
}

// BeginGameFlowUnloadingFrontEnd, 0x00168830. StartRace asks for it from
// IN_FRONTEND. Retail waits for the GPU, then UnlaunchFrontendMenus,
// CloseMoviePlayer, CloseSelectCarScreen and TheCarLoader's
// UnloadEverything, the frontend's sounds, car effects and sound regions,
// every frontend resource file, the languages, the demo replay's file and
// the slot pools; it waits for the disc and asks for LOADING_TRACK_COMMON,
// whose Begin runs on the same pass of ServiceGameFlow.
void bgf_begin_unloading_frontend(BGameFlow* gf)
{
    bgf_unlaunch_frontend_menus(gf);
    HOOK_VOID0(gf, closeSelectCar);
    HOOK_VOID0(gf, unInitFrontendSounds);
    HOOK_VOID0(gf, unloadSoundRegions);
    HOOK_VOID0(gf, unloadFrontEnd);
    bgf_change_state(gf, BGF_LOADING_TRACK_COMMON, BGF_NONE);
}

// ------------------------------------------------------- TitleMoviesToPlay

// Retail 0x002fb750 (the demo's 0x002f3770). Eight language rows of two:
// the EA logo in the row's language, then the letterboxed NFS intro, which
// only French has a version of. Every one of them is on the retail disc;
// the demo pressed EALOGO_EN.AVI alone and had NFSINTRO_EN.AVI for French
// too. A file the port cannot open is skipped rather than waited on.
static const BTitleMovie kTitleMovies[8][2] = {
    { { "MOVIES\\INTRO\\EALOGO_EN.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_FR.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_FR.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_GE.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_IT.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_SP.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_SW.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { NULL, 0 }, { NULL, 0 } },   // l_LONGEST_STRING
    { { NULL, 0 }, { NULL, 0 } },   // l_ID_NUM
};

// GetNumTitleMovies. It answers 1 on the demo disc, whose table
// (DemoDiscTitleMoviesToPlay, 0x002f37f0) has the EA logo only.
int bgf_num_title_movies(const BGameFlow* gf)
{
    (void)gf;
    return 2;
}

const BTitleMovie* bgf_title_movie(const BGameFlow* gf, int i)
{
    int lang = gf->currLanguage;
    if (lang < 0 || lang > 7) lang = 0;
    if (i < 0 || i > 1) i = 0;
    return &kTitleMovies[lang][i];
}

// ------------------------------------------------------------- TitleScreen
//
// Retail's (0x0016eef8 to 0x0016f558), which is not the demo's. The demo
// left for New Main Menu on a SELECT during the NFS intro and put PRESS START
// up the moment the movies ended. Retail instead:
//
//   - takes a SELECT during the intro as "stop the movie": the screen comes
//     to rest on the title and stays there -- it does not change screen;
//   - at rest shows the TITLE_IMAGE group (the logo, the bar, the copyright
//     line) and starts a Timer at +20 on the first tick at rest;
//   - shows PRESS START, and takes the SELECT that leaves for New Main Menu,
//     only once that Timer is four seconds old;
//   - blooms PRESS START with a tHighlightAnimation while at rest.

// The title's bloom and the main menu's kit take the kit's clock from the
// flow's, the way bscreens.c's clock() does, so that there is one RealTimer.
static BAnim* flowAnim(BGameFlow* gf)
{
    if (gf->anim)
        banim_set_clock(gf->anim, (int32_t)gf->realTimer, gf->realElapsed);
    return gf->anim;
}

// tHighlightAnimation(TITLE, ANIMATING_MENUITEM, BloomTargetColor), the
// constructor's first act. gp-16136 is 0x00000080, the colour the other
// frontend screens bloom in too.
static void titleBloomInit(BGameFlow* gf)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "bloom init %08x %08x %08x", (unsigned)BGF_SCREEN_TITLE,
          (unsigned)BGF_OBJ_ANIMATING_ITEM, (unsigned)BANIM_BLOOM_COLOR);
    if (a)
        banim_highlight_init(a, &gf->title.highlight, BGF_SCREEN_TITLE,
                             BGF_OBJ_ANIMATING_ITEM,
                             (int32_t)BANIM_BLOOM_COLOR);
}

static void titleBloomSetItem(BGameFlow* gf, uint32_t item)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "bloom item %08x", (unsigned)item);
    if (a) banim_highlight_set_item(a, &gf->title.highlight, item);
}

static void titleBloomStart(BGameFlow* gf)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "bloom start");
    gf->title.tracedAnimate = 0;
    if (a) banim_highlight_force_start(a, &gf->title.highlight);
}

// Every tick at rest. Traced once each time the bloom is (re)started.
static void titleBloomAnimate(BGameFlow* gf)
{
    BAnim* a = flowAnim(gf);
    if (!gf->title.tracedAnimate) trace(gf, "bloom animate");
    gf->title.tracedAnimate = 1;
    if (a) banim_highlight_animate(a, &gf->title.highlight);
}

static int titleOpenMovie(BGameFlow* gf, int index)
{
    const BTitleMovie* d = bgf_title_movie(gf, index);
    BTitleScreen*      t = &gf->title;

    t->playing = 0;
    if (!d->name) {
        trace(gf, "movie none %d", index);
    } else if (gf->hooks.movieOpen
               && gf->hooks.movieOpen(gf->hooks.user, d->name)) {
        t->playing = 1;
        trace(gf, "movie open %s", d->name);
    } else {
        // A movie missing from the card. The original would sit on a
        // MoviePlayer that never finishes; the port treats a file it cannot
        // open as a movie that has already ended, so the sequence advances.
        trace(gf, "movie missing %s", d->name);
    }
    objectVisible(gf, BGF_SCREEN_TITLE,
                  d->letterboxed ? BGF_OBJ_MOVIE_PLANE_LB
                                 : BGF_OBJ_MOVIE_PLANE_43,
                  1);
    return t->playing;
}

// DriveMovie (0x0016ee18) returns 1 when the movie is finished. Retail's
// also records the answer for a replay (0x00183358 / 0x00183498, four bits
// on channel 6), which nothing here plays back.
static int titleDriveMovie(BGameFlow* gf)
{
    if (!gf->title.playing) return 1;
    if (!gf->hooks.movieDrive) return 1;
    return gf->hooks.movieDrive(gf->hooks.user);
}

static void titleCloseMovie(BGameFlow* gf)
{
    if (!gf->title.playing) return;
    HOOK_VOID0(gf, movieClose);
    gf->title.playing = 0;
}

// The Timer at +20 counts as unset at 0 and at 0x7fffffff.
static int titlePressStartSet(const BTitleScreen* t)
{
    return t->pressStart != 0 && t->pressStart != 0x7fffffffu;
}

// 0x0016f4f8, the one new function: four seconds at rest. The difference
// is converted signed (cvt.s.w) and scaled by gp-30496, 0.00025f.
static int titlePressStartReady(const BGameFlow* gf)
{
    const BTitleScreen* t = &gf->title;
    if (!titlePressStartSet(t)) return 0;
    return (float)(int32_t)(gf->realTimer - t->pressStart) * 0.00025f > 4.0f;
}

// The constructor, 0x0016f000.
static void titleActivate(BGameFlow* gf, BScreenCallbackData* data)
{
    BTitleScreen* t = &gf->title;

    memset(t, 0, sizeof(*t));          // +16 and +20 are zeroed first
    t->tracedRest  = -1;
    t->tracedReady = -1;
    titleBloomInit(gf);
    t->port = data ? data->port : 0;
    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_43, 0);
    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_COPYRIGHT, 0);
    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);
    t->movieIndex = 0;

    if (gf->skipMovies) {
        t->mode = 1;
        HOOK_VOID(gf, jukebox, 1);
    } else {
        t->mode = 2;
        // pMoviePlane is fixed to the 4:3 plane here and never re-fetched,
        // even when a letterboxed movie makes the other plane visible.
        // Faithfully reproduced: only the 4:3 plane's texture is written.
        titleOpenMovie(gf, 0);
        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_COPYRIGHT, 0);
    }
    t->timer = gf->realTimer;
    titleBloomSetItem(gf, BGF_OBJ_PRESS_START);
}

// The destructor, 0x0016f190: MoviePlayer::Close, then the bloom's own.
static void titleUnactivate(BGameFlow* gf)
{
    titleCloseMovie(gf);
    memset(&gf->title, 0, sizeof(gf->title));
}

// HandleTick, 0x0016f1f0.
static void titleTick(BGameFlow* gf)
{
    BTitleScreen* t = &gf->title;
    int           cameToRest = 0;
    int           rest, ready;

    if (t->mode == 2) {
        if (titleDriveMovie(gf) == 1) {
            t->movieIndex++;
            titleCloseMovie(gf);
            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_43, 0);
            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);
            if (t->movieIndex == bgf_num_title_movies(gf)) {
                t->mode    = 1;
                t->timer   = gf->realTimer;
                cameToRest = 1;
                HOOK_VOID(gf, jukebox, 1);
            } else {
                titleOpenMovie(gf, t->movieIndex);
            }
        }
    } else if (t->mode == 1) {
        // (The demo disc outside attract mode started its own game here,
        // StartDemoDiscGame, 0x00184de0.)
        bgf_consider_start_demo_mode(gf, &t->timer);
        titleBloomAnimate(gf);
    }

    // Every tick, whatever the mode. The hooks run every time, as the
    // original's calls do; only the trace waits for a change.
    rest = t->mode != 2;
    if (rest != t->tracedRest)
        groupVisible(gf, BGF_SCREEN_TITLE, BGF_GROUP_TITLE_IMAGE, rest);
    else
        HOOK_VOID(gf, setGroupVisible, BGF_SCREEN_TITLE,
                  BGF_GROUP_TITLE_IMAGE, rest);
    t->tracedRest = rest;
    if (rest && !titlePressStartSet(t)) t->pressStart = gf->realTimer;
    ready = titlePressStartReady(gf);
    if (ready != t->tracedReady)
        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_PRESS_START, ready);
    else
        HOOK_VOID(gf, setObjectVisible, BGF_SCREEN_TITLE,
                  BGF_OBJ_PRESS_START, ready);
    t->tracedReady = ready;

    // The screen has come to rest with the sequence over. Traced because it
    // is the one moment a test can point at and say the movies finished.
    if (cameToRest) trace(gf, "title idle");
}

// HandleEvent, 0x0016eef8 -- a 17-entry jump table at 0x002b2f10 on
// message - 1.
static void titleEvent(BGameFlow* gf, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    BTitleScreen* t = &gf->title;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (t->mode == 1) {
                // PRESS START is not up yet: nothing, and no click.
                if (!titlePressStartReady(gf)) {
                    data->noise = 0;
                    break;
                }
                t->timer = gf->realTimer;
                // Noise is left alone, so the select sound plays.
                bgf_change_to_screen(gf, "New Main Menu", 1);
            } else if (t->mode == 2) {
                // The EA logo cannot be skipped and the NFS intro can:
                // during movie 0 movieIndex is still 0.
                if (t->movieIndex == 0) {
                    data->noise = 0;
                    break;
                }
                // Skipping is stopping. The movie planes are left as they
                // are -- nothing hides them until the screen is built again
                // -- but a movie plane with no movie open draws nothing
                // (uirender.c, after RenderFlailerBitmap), so the title
                // shows through.
                titleCloseMovie(gf);
                t->mode  = 1;
                t->timer = gf->realTimer;
                titleBloomStart(gf);
                trace(gf, "title skip");
            } else {
                data->noise = 0;
            }
            break;

        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT:
        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
        case BMSG_MENUITEM_SQUARE:
        case BMSG_SCREEN_START_BUTTON:
            data->noise = 0;   // swallow the UI click
            break;

        case BMSG_SCREEN_BACK_BUTTON:
            data->param = 0;   // veto: BACK does nothing on the title screen
            data->noise = 0;
            break;

        default:
            break;
    }
}

void bgf_title_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data)
{
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:   titleActivate(gf, data); break;
        case BMSG_SCREEN_UNACTIVATE: titleUnactivate(gf);     break;
        case BMSG_SCREEN_TICK:       titleTick(gf);           break;
        default:                     titleEvent(gf, msg, data); break;
    }
}

// -------------------------------------------------------- MumboJumboScreen

// Both 0x0016a648 and 0x0016a650 are `return 0` on this build, so without
// gf->forceLegalScreens neither panel is ever shown. See gameflow.h.
static int shouldSeeLegalScreen(const BGameFlow* gf) { return gf->forceLegalScreens; }
static int shouldSeeAntiPiracy(const BGameFlow* gf)  { return gf->forceLegalScreens; }

static int textureReady(BGameFlow* gf, uint32_t tex)
{
    if (!gf->hooks.textureReady) return 1;
    return gf->hooks.textureReady(gf->hooks.user, tex);
}

static void mumboBeginPanel(BGameFlow* gf, int state, uint32_t tex)
{
    gf->mumbo.state = state;
    objectVisible(gf, BGF_SCREEN_MUMBO_JUMBO, BGF_OBJ_MUMBO_PLANE, 0);
    trace(gf, "tex load %08x", (unsigned)tex);
    HOOK_VOID(gf, loadTexture, tex);
}

static void mumboShowPanel(BGameFlow* gf, int state, uint32_t tex)
{
    gf->mumbo.state = state;
    changeTexture(gf, BGF_SCREEN_MUMBO_JUMBO, BGF_OBJ_MUMBO_PLANE, tex);
    objectVisible(gf, BGF_SCREEN_MUMBO_JUMBO, BGF_OBJ_MUMBO_PLANE, 1);
    gf->mumbo.timer = gf->realTimer;
}

static int mumboExpired(const BGameFlow* gf, float timeout)
{
    // Both timeouts are compared against a RealTimer difference, i.e. in
    // units of 1/4000 s.
    return (float)(gf->realTimer - gf->mumbo.timer) * (1.0f / 4000.0f)
           > timeout;
}

static void mumboTick(BGameFlow* gf)
{
    switch (gf->mumbo.state) {
        case 0:
            if (shouldSeeLegalScreen(gf))
                mumboBeginPanel(gf, 1, BGF_TEX_LEGAL);
            else if (shouldSeeAntiPiracy(gf))
                mumboBeginPanel(gf, 3, BGF_TEX_ANTIPIRACY);
            else
                bgf_move_back_screen(gf, 1);
            break;
        case 1:
            if (textureReady(gf, BGF_TEX_LEGAL))
                mumboShowPanel(gf, 2, BGF_TEX_LEGAL);
            break;
        case 2:
            if (!mumboExpired(gf, gf->legalScreenTimeout)) break;
            trace(gf, "tex unload %08x", (unsigned)BGF_TEX_LEGAL);
            HOOK_VOID(gf, unloadTexture, BGF_TEX_LEGAL);
            if (shouldSeeAntiPiracy(gf))
                mumboBeginPanel(gf, 3, BGF_TEX_ANTIPIRACY);
            else
                bgf_move_back_screen(gf, 1);
            break;
        case 3:
            if (textureReady(gf, BGF_TEX_ANTIPIRACY))
                mumboShowPanel(gf, 4, BGF_TEX_ANTIPIRACY);
            break;
        case 4:
            if (!mumboExpired(gf, gf->antiPiracyTimeout)) break;
            trace(gf, "tex unload %08x", (unsigned)BGF_TEX_ANTIPIRACY);
            HOOK_VOID(gf, unloadTexture, BGF_TEX_ANTIPIRACY);
            bgf_move_back_screen(gf, 1);
            break;
        default:
            break;
    }
}

void bgf_mumbo_jumbo_callback(BGameFlow* gf, BScreenMessage msg,
                              BScreenCallbackData* data)
{
    (void)data;
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            memset(&gf->mumbo, 0, sizeof(gf->mumbo));
            break;
        case BMSG_SCREEN_UNACTIVATE:
            memset(&gf->mumbo, 0, sizeof(gf->mumbo));
            break;
        case BMSG_SCREEN_TICK:
            mumboTick(gf);
            break;
        default:
            break;
    }
}

// --------------------------------------------------------- BootAutoLoader

void bgf_boot_autoload_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data)
{
    // 0x00247ab0. pInstance is set only once the constructor returns, so
    // the popup its constructor summons announces itself to nobody. The
    // constructor is handed ItemHash, not Port (memcard.h).
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            memcard_boot_autoloader_init(&gf->autoload, gf,
                                         data ? data->itemHash : 0,
                                         gf->autoloadManual);
            gf->autoloadActive = 1;
            break;

        case BMSG_SCREEN_UNACTIVATE:
            if (gf->autoloadActive) memcard_boot_autoloader_destroy(&gf->autoload);
            gf->autoloadActive = 0;
            break;

        default:
            if (gf->autoloadActive)
                memcard_boot_autoloader_event(&gf->autoload, msg, data);
            break;
    }
}

// ------------------------------------------- LoadSaveWrapper, Autosaver

void bgf_load_save_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    // 0x00247830: built from ItemHash, the screen's. The original keeps
    // pInstance after the delete and calls through it unchecked.
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            memcard_load_save_init(&gf->loadSave, gf, data ? data->itemHash : 0);
            gf->loadSaveActive = 1;
            break;

        case BMSG_SCREEN_UNACTIVATE:
            if (gf->loadSaveActive) memcard_load_save_destroy(&gf->loadSave);
            gf->loadSaveActive = 0;
            break;

        default:
            if (gf->loadSaveActive)
                memcard_load_save_event(&gf->loadSave, msg, data);
            break;
    }
}

void bgf_autosave_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    // 0x00247d00. As the boot's: the constructor's popup announces itself
    // to nobody.
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            memcard_autosaver_init(&gf->autosaver, gf,
                                   data ? data->itemHash : 0);
            gf->autosaverActive = 1;
            break;

        case BMSG_SCREEN_UNACTIVATE:
            if (gf->autosaverActive) memcard_autosaver_destroy(&gf->autosaver);
            gf->autosaverActive = 0;
            break;

        default:
            if (gf->autosaverActive)
                memcard_autosaver_event(&gf->autosaver, msg, data);
            break;
    }
}

// 0x00247d98 stores the callback through pInstance with no test. The port
// calls it at once when no Autosave screen is up, so a race whose Autosave
// screen could not come up still goes on.
void bgf_set_autosave_completion_callback(BGameFlow* gf, void (*cb)(void))
{
    if (gf->autosaverActive) {
        gf->autosaver.done = cb;
        return;
    }
    trace(gf, "autosave none");
    if (cb) cb();
}

// ------------------------------------------------------------ plain screen

void bgf_plain_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data)
{
    (void)gf;
    (void)data;
    (void)msg;
}

// ------------------------------------------------ LanguageOptionsScreenBase

static void grayMenuItem(BGameFlow* gf, uint32_t screen, uint32_t item,
                         int mode)
{
    trace(gf, "gray %08x %08x %d", (unsigned)screen, (unsigned)item, mode);
    HOOK_VOID(gf, grayMenuItem, screen, item, mode);
}

static uint32_t activeMenuItem(BGameFlow* gf)
{
    if (!gf->hooks.activeMenuItem) return 0;
    return gf->hooks.activeMenuItem(gf->hooks.user);
}

// MENUITEM_1..6 are the languages 0..5 in order: the original adds
// 0xad1fc60d, -MENUITEM_1, and takes anything under 6 unsigned.
static int languageOfItem(uint32_t item, int* language)
{
    uint32_t i = item - BGF_ITEM_MENUITEM_1;
    if (i >= 6u) return 0;
    *language = (int)i;
    return 1;
}

// The constructor, 0x001f1a78.
static void languageCtor(BGameFlow* gf, uint32_t flailer, int fromOptions)
{
    BLanguageScreen* l = &gf->language;
    l->active      = 1;
    l->flailer     = flailer;
    l->fromOptions = fromOptions;
    l->selected    = gf->currLanguage == -1 ? 0 : gf->currLanguage;
    // 0x0016fdb0 is `return 0`, so Load All Languages is always hidden.
    grayMenuItem(gf, flailer, BGF_ITEM_MENUITEM_7, 2);
}

// Both of HandleScreenCallback's ways out once a language is picked:
// SetCurrLanguage, the frontend database's defaults when this is the boot's
// screen (FrontendDatabase::InitWithDefaults, 0x00183830, on 0x002fc050),
// and MoveBackScreen. `backOnUnset` is the one difference between them:
// SELECT returns when CurrLanguage is still -1, BACK moves back anyway.
static void languageChosen(BGameFlow* gf, int backOnUnset)
{
    BLanguageScreen* l = &gf->language;
    bgf_set_curr_language(gf, l->selected);
    if (gf->currLanguage == -1) {
        if (backOnUnset) bgf_move_back_screen(gf, 1);
        return;
    }
    if (!l->fromOptions) HOOK_VOID0(gf, frontendDefaults);
    if (!l->fromOptions) trace(gf, "frontend defaults");
    bgf_move_back_screen(gf, 1);
}

// HandleScreenCallback, 0x001f1b08: a 19-entry jump table at 0x002b9e30 on
// message - 1, of which SELECT, BACK and TICK do anything -- and TICK is a
// virtual that does nothing for this class.
static void languageEvent(BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    BLanguageScreen* l = &gf->language;
    uint32_t         item;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:          // 0x001f1c3c
            item = data->itemHash;
            languageOfItem(item, &l->selected);
            if (item < BGF_ITEM_MENUITEM_1) return;
            if (item > BGF_ITEM_MENUITEM_6) {
                if (item != BGF_ITEM_MENUITEM_7) return;
                gf->loadAllLanguages = 1;
                trace(gf, "load all languages");
                bgf_move_back_screen(gf, 1);
                return;
            }
            languageChosen(gf, 0);
            break;

        case BMSG_SCREEN_BACK_BUTTON:       // 0x001f1b44
            // The list's own pop is always vetoed; the screen pops itself.
            data->param = 0;
            if (gf->currLanguage == -1) return;
            item = activeMenuItem(gf);
            languageOfItem(item, &l->selected);
            // Signed compares, so no menu (item 0) moves back as it is.
            if ((int32_t)item > (int32_t)BGF_ITEM_MENUITEM_6
                || (int32_t)item < (int32_t)BGF_ITEM_MENUITEM_1) {
                bgf_move_back_screen(gf, 1);
                return;
            }
            languageChosen(gf, 1);
            break;

        default:
            break;
    }
}

// Callback, 0x001f1dd8. The class is picked by the name the screen was
// entered under: strcmp on pCurrent's config name, as the original does.
void bgf_language_screen_callback(BGameFlow* gf, BScreenMessage msg,
                                  BScreenCallbackData* data)
{
    const char* name = gf->screen ? gf->screen->name : "";

    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            if (strcmp(name, "Language Options Pre FE") == 0)
                languageCtor(gf, data->itemHash, 0);
            else if (strcmp(name, "Language Options") == 0)
                // LanguageOptionsScreen (0x001f1d70) is this plus a
                // tSlideOnScreen, which the port does not have yet.
                languageCtor(gf, data->itemHash, 1);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            memset(&gf->language, 0, sizeof(gf->language));
            break;
        default:
            // The original calls through pInstance unchecked; nothing sends
            // this screen an event with no instance.
            if (gf->language.active) languageEvent(gf, msg, data);
            break;
    }
}

// ------------------------------------------------------------ NewMainMenu

// Retail's NewMainMenu. Callback (0x00216a10) builds the 636-byte instance on
// SCREEN_ACTIVATE, from the screen's ItemHash, and deletes it on
// SCREEN_UNACTIVATE if pInstance is set. Everything else goes to HandleEvent
// (0x00216638) with pInstance unchecked.
//
// The constructor (0x00216460) does, in order:
//   1. tAnimatedBlurb at +4 (SCROLLING_TEXT twice, WHITEOUT_BAR), then
//      tHighlightAnimation at +424 (ANIMATING_MENUITEM, gp-16136's colour),
//      then tSlideInAnimation at +456 to MI_1_MASK's authored X, then
//      SelectionSet at +480, with the idle Timer (+476) and +632 zeroed;
//   2. FrontendDatabase::MakeChallengeCarsAvailable and
//      RaceParameters::InitWithDefaults;
//   3. the idle Timer set to RealTimer, and jukebox Start(1);
//   4. the SelectionSet's IndicatorMode 1 and its five items (0x0031be40);
//   5. StartMovie (the string at 0x002bc430);
//   6. TheEasterEggs' Start;
//   7. the Easter egg group hidden, and +628, "shown", cleared.
// The movie outlives the screen -- the destructor
// (0x00216598) leaves it -- so the Mode Selects and Options, which start
// their own, are what replace it.
//
// The destructor calls TheEasterEggs' Stop, hides the group again, and
// destroys the four members in reverse. SelectionSet's and
// tHighlightAnimation's do nothing but free; tSlideInAnimation's is
// tSlideAnimation's (0x00248c08), which puts its groups back, and
// tAnimatedBlurb's releases its two alphas and its group.
static const uint32_t kMainMenuMasks[5] = {
    BGF_MI_1_MASK, BGF_MI_2_MASK, BGF_MI_3_MASK, BGF_MI_4_MASK, BGF_MI_5_MASK,
};

// FlailerGetTopLeftX (0x00144140), through the kit's hook.
static float flowTopLeftX(BGameFlow* gf, uint32_t screen, uint32_t object)
{
    float x = 0.0f, y = 0.0f;
    if (gf->anim && gf->anim->hooks.getTopLeft)
        gf->anim->hooks.getTopLeft(gf->anim->hooks.user, screen, object, &x,
                                   &y);
    return x;
}

// The four members' constructors, each traced with what it is given.
static void menuBlurbInit(BGameFlow* gf, uint32_t screen, uint32_t text,
                          uint32_t fadeout, uint32_t bar)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "blurb init %08x %08x %08x %08x", (unsigned)screen,
          (unsigned)text, (unsigned)fadeout, (unsigned)bar);
    if (a) banim_blurb_init(a, &gf->mainMenu.blurb, screen, text, fadeout, bar);
}

static void menuBloomInit(BGameFlow* gf, uint32_t screen, uint32_t object,
                          uint32_t color)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "bloom init %08x %08x %08x", (unsigned)screen, (unsigned)object,
          (unsigned)color);
    if (a)
        banim_highlight_init(a, &gf->mainMenu.bloom, screen, object,
                             (int32_t)color);
}

// Every group slides to the X `object` was authored at; the stagger is in
// the durations.
static void menuSlideInInit(BGameFlow* gf, uint32_t screen, uint32_t object)
{
    BAnim* a = flowAnim(gf);
    float  x = flowTopLeftX(gf, screen, object);
    trace(gf, "slide in %08x %08x %.1f", (unsigned)screen, (unsigned)object, x);
    if (a) banim_slide_in_init(a, &gf->mainMenu.slideIn, screen, x);
}

static void menuSelAddItems(BGameFlow* gf, uint32_t screen,
                            const uint32_t* masks, int n)
{
    BAnim* a = flowAnim(gf);
    char   line[160];
    int    len, i;

    len = snprintf(line, sizeof(line), "sel items %08x mode %d",
                   (unsigned)screen, gf->mainMenu.sel.indicatorMode);
    for (i = 0; i < n && len < (int)sizeof(line); i++)
        len += snprintf(line + len, sizeof(line) - (size_t)len, " %08x",
                        (unsigned)masks[i]);
    trace(gf, "%s", line);
    if (a) bsel_add_items(a, &gf->mainMenu.sel, masks, n);
}

static void mainMenuCtor(BGameFlow* gf)
{
    BNewMainMenu* m = &gf->mainMenu;
    BAnim*        a = flowAnim(gf);

    memset(m, 0, sizeof(*m));
    menuBlurbInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_SCROLLING_TEXT,
                  BGF_OBJ_SCROLLING_TEXT, BGF_OBJ_WHITEOUT_BAR);
    menuBloomInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_OBJ_ANIMATING_ITEM,
                  BANIM_BLOOM_COLOR);
    menuSlideInInit(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_MI_1_MASK);
    m->timer = 0;
    if (a) bsel_init(a, &m->sel, BGF_SCREEN_NEW_MAIN_MENU);
    m->eggTimer = 0;
    trace(gf, "challenge cars");
    HOOK_VOID0(gf, challengeCars);
    trace(gf, "race defaults");
    HOOK_VOID0(gf, raceDefaults);
    m->timer = gf->realTimer;
    HOOK_VOID(gf, jukebox, 1);    // the main menu's
    // IndicatorMode 1, stored before AddItems, as on every screen with one:
    // the mask over the CURRENT item is the one turned off.
    bsel_set_indicator_mode(&m->sel, 1);
    menuSelAddItems(gf, BGF_SCREEN_NEW_MAIN_MENU, kMainMenuMasks, 5);
    bgf_start_movie(gf, "MOVIES\\mainmenu_movie.AVI");
    HOOK_VOID(gf, easterEggs, 1);
    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);
    m->eggShown = 0;
    m->active = 1;
}

static void mainMenuDtor(BGameFlow* gf)
{
    BNewMainMenu* m = &gf->mainMenu;
    BAnim*        a = flowAnim(gf);

    HOOK_VOID(gf, easterEggs, 0);
    groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);
    if (a) {
        banim_slide_release(a, &m->slideIn);
        banim_blurb_release(a, &m->blurb);
    }
    trace(gf, "menu kit released");
    memset(m, 0, sizeof(*m));
}

// OnTick (0x00216718). The Easter eggs' half comes first:
//   - with a help menu up (tHelpMenu::IsActive on the list's +452),
//     TheEasterEggs' +0 is cleared and the idle Timer reset;
//   - otherwise +0 is set, and a code just entered (+4) resets the Timer,
//     plays sound 30, shows the group with the code's LanguageID (+8) on
//     0xf58c1a4b, and sets +628 and +632; gp-16120 set calls 0x0024f968 on
//     TheEasterEggs and clears it.
// Then the idle Timer is reset while popup 0 is up (GetPopupActiveState,
// 0x0016ce00), ConsiderStartDemoMode runs on it, and the three members
// animate: the blurb, the bloom, the slide-in. Last, the group comes down
// three seconds after it went up.
//
// Not ported: the eggs' half, which needs the 78 codes (TheEasterEggs never
// sets +4 without them, so nothing of it is seen).
static void mainMenuTick(BGameFlow* gf)
{
    BNewMainMenu* m = &gf->mainMenu;
    BAnim*        a = flowAnim(gf);

    if (gf->popups[0].active) m->timer = gf->realTimer;
    bgf_consider_start_demo_mode(gf, &m->timer);
    if (!m->tracedAnimate) trace(gf, "menu animate");
    m->tracedAnimate = 1;
    if (a) {
        banim_blurb_animate(a, &m->blurb);
        banim_highlight_animate(a, &m->bloom);
        banim_slide_animate(a, &m->slideIn);
    }
    if (m->eggShown
        && 3.0f < (float)(int32_t)(gf->realTimer - m->eggTimer) * 0.00025f) {
        m->eggShown = 0;
        groupVisible(gf, BGF_SCREEN_NEW_MAIN_MENU, BGF_GROUP_EASTER_EGG, 0);
    }
}

// HandleEvent (0x00216638): a 24-entry jump table on message - 1.
//
//   SELECT (1)  0x0021668c  the three-way test below
//   HIGHLIGHT (4)            OnHighlight (0x00216938): the bloom's item,
//                            then HighlightMenuItem's brackets and blurb
//   BACK (17)   0x00216664  Param and Noise cleared
//   TICK (18)                OnTick (0x00216718)
//   24          0x00216680  the idle Timer set to RealTimer
//
// SELECT's test is the demo's. The two Mode Selects are the same screen
// either side of Fred.MainMenuOpts.mPolice (0x002fc070):
//
//   MENUITEM_1 "Hot Pursuit"  -> CopsOn = 1, "Cops On Mode Select"
//   MENUITEM_2 "World Racing" -> CopsOn = 0, "Cops Off Mode Select"
//   MENUITEM_3 "Options"      ->             "Options"
//
// and the port's (gameflow.h):
//
//   MENUITEM_4 "Local Wireless" ->           "Local Wireless", the lobby
//   MENUITEM_5 "Debug Menu"     ->           "Port Debug Menu"
//
// All push New Main Menu, so BACK from there returns here. Every
// screen name the port's own code can reach is registered (kScreens[] in
// main.c, bscreens.c for the classes). The ten with no class yet are
// registered to bgf_plain_screen_callback so they draw. An unregistered
// name would be worse than a dead one: bgf_change_to_screen traces
// "unregistered" and leaves the flow with no current screen, which is what
// ChangeToScreen does too -- it clears pCurrent before it looks the name
// up. See TASKS.md 33, and `python tools/screen_registry.py --check-port`.
//
// BACK is retail's alone: the demo's table sent it nowhere. With Param 0,
// MoveToPreviousScreen goes nowhere, and with Noise 0 it makes no sound. The
// main menu is where the frontend begins, and the title is behind it for
// good.
//
// HIGHLIGHT is OnHighlight, below, and TICK is OnTick, above. Message 24,
// any button pressed, resets the idle Timer, which only
// ConsiderStartDemoMode reads.
// HighlightMenuItem (0x00216880), in retail's order: the two brackets to the
// item's MI_n_MASK, the blurb's NewText(int), and
// SelectionSet::SetCurrentItem, which the trace stands for. The offsets are
// retail's two constants: MI_UNDERSCORE goes to the box's bottom plus
// gp-16112 (-3.0), MI_OVERSCORE to its top minus gp-16116 (6.0). They are
// bscreens.h's BSCR_UNDER_MODE_SELECT and BSCR_OVER_MODE_SELECT, which is
// what the Mode Selects use too.
//
// The blurb's wipe runs on the top screen's SCROLLING_TEXT, which the 3DS
// keeps hidden: the sentence itself goes to the bottom panel, through
// setBlurb, as on the Mode Selects.
static void mainMenuHighlightItem(BGameFlow* gf, uint32_t mask, int blurb)
{
    BNewMainMenu* m = &gf->mainMenu;
    BAnim*        a = flowAnim(gf);

    HOOK_VOID(gf, moveBrackets, BGF_SCREEN_NEW_MAIN_MENU, mask, -3.0f, -6.0f);
    if (a) banim_blurb_new_text_id(a, &m->blurb, blurb);
    HOOK_VOID(gf, setBlurb, BGF_SCREEN_NEW_MAIN_MENU, blurb);
    if (a) bsel_set_current(a, &m->sel, mask);
    trace(gf, "bracket %08x", (unsigned)mask);
}

// OnHighlight (0x00216938). It first gives the bloom at +424 the item, the
// ScreenCallbackData's ItemHash, whatever it is
// (tHighlightAnimation::SetCurrentMenuItem, 0x002488d0): the echo. Then it
// picks the item's mask and blurb. Any other hash stops there: the brackets
// and the blurb stay where they were.
static void menuBloomSetItem(BGameFlow* gf, uint32_t item)
{
    BAnim* a = flowAnim(gf);
    trace(gf, "bloom item %08x", (unsigned)item);
    if (a) banim_highlight_set_item(a, &gf->mainMenu.bloom, item);
}

static void mainMenuHighlight(BGameFlow* gf, uint32_t itemHash)
{
    menuBloomSetItem(gf, itemHash);
    switch (itemHash) {
        case BGF_ITEM_MENUITEM_1:
            mainMenuHighlightItem(gf, BGF_MI_1_MASK, BGF_BLURB_MENUITEM_1);
            break;
        case BGF_ITEM_MENUITEM_2:
            mainMenuHighlightItem(gf, BGF_MI_2_MASK, BGF_BLURB_MENUITEM_2);
            break;
        case BGF_ITEM_MENUITEM_3:
            mainMenuHighlightItem(gf, BGF_MI_3_MASK, BGF_BLURB_MENUITEM_3);
            break;
        case BGF_ITEM_MENUITEM_4:
            // The port's own two (gameflow.h). Local Wireless's line is
            // the one Challenge's Players had for it (portlang.h).
            mainMenuHighlightItem(gf, BGF_MI_4_MASK,
                                  PORTLANG_LOCAL_WIRELESS_BLURB);
            break;
        case BGF_ITEM_MENUITEM_5: {
            // HighlightMenuItem's three steps, with a sentence of its own,
            // as no language row has one.
            static const char kText[] =
                "Jump into any race, unlock everything, set your NFS points.";
            BNewMainMenu* m = &gf->mainMenu;
            BAnim*        a = flowAnim(gf);
            HOOK_VOID(gf, moveBrackets, BGF_SCREEN_NEW_MAIN_MENU,
                      BGF_MI_5_MASK, -3.0f, -6.0f);
            if (a) banim_blurb_new_text(a, &m->blurb, kText);
            HOOK_VOID(gf, setBlurbText, BGF_SCREEN_NEW_MAIN_MENU, kText);
            if (a) bsel_set_current(a, &m->sel, BGF_MI_5_MASK);
            trace(gf, "bracket %08x", (unsigned)BGF_MI_5_MASK);
            break;
        }
        default:
            break;
    }
}

static void mainMenuEvent(BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    switch (msg) {
        case BMSG_MENUITEM_HIGHLIGHT:
            mainMenuHighlight(gf, data->itemHash);
            break;
        case BMSG_MENUITEM_SELECT:
            switch (data->itemHash) {
                case BGF_ITEM_MENUITEM_1:
                    gf->copsOn = 1;
                    HOOK_VOID(gf, setPolice, 1);
                    bgf_change_to_screen(gf, "Cops On Mode Select", 1);
                    break;
                case BGF_ITEM_MENUITEM_2:
                    gf->copsOn = 0;
                    HOOK_VOID(gf, setPolice, 0);
                    bgf_change_to_screen(gf, "Cops Off Mode Select", 1);
                    break;
                case BGF_ITEM_MENUITEM_3:
                    bgf_change_to_screen(gf, "Options", 1);
                    break;
                // The port's own two, pushing the menu as the others do.
                // The lobby asks the mode itself, once Host is chosen.
                case BGF_ITEM_MENUITEM_4:
                    bgf_change_to_screen(gf, BGF_LOCAL_WIRELESS_NAME, 1);
                    break;
                case BGF_ITEM_MENUITEM_5:
                    bgf_change_to_screen(gf, BGF_DEBUG_MENU_NAME, 1);
                    break;
                default:
                    // Every other item hash falls through the test and
                    // returns, sound and all.
                    break;
            }
            break;
        case BMSG_SCREEN_BACK_BUTTON:
            data->noise = 0;
            data->param = 0;
            break;
        case BMSG_SCREEN_TICK:
            mainMenuTick(gf);
            break;
        case BMSG_ANY_BUTTON_PRESSED:
            gf->mainMenu.timer = gf->realTimer;
            break;
        default:
            break;
    }
}

void bgf_new_main_menu_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data)
{
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            mainMenuCtor(gf);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            if (gf->mainMenu.active) mainMenuDtor(gf);
            break;
        default:
            if (data) mainMenuEvent(gf, msg, data);
            break;
    }
}
