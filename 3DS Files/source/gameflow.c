// The boot flow. See gameflow.h, and docs/formats/boot-flow.md for the
// decompilation this is a port of -- every rule below names an address.

#include "gameflow.h"

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

int bgf_screen_event(BGameFlow* gf, BScreenMessage msg, int port)
{
    BScreenCallbackData data;
    memset(&data, 0, sizeof(data));
    data.port  = port;
    data.param = 1;
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
    data.itemHash = itemHash;
    if (!bgf_send(gf, msg, &data)) return 0;
    makeSound(gf, data.noise);
    return 1;
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
            memset(&data, 0, sizeof(data));
            data.itemHash = n->hash;
            bgf_send(gf, BMSG_SCREEN_ACTIVATE, &data);
            // After the message, not before. There is no enterScreen in the
            // original -- it is the port's name for "build the menu" -- and
            // in the original the menu is built by the screen's own
            // constructor, which runs on SCREEN_ACTIVATE. A port that builds
            // it first delivers the menu's opening MENUITEM_HIGHLIGHT to a
            // screen object that does not exist yet, and the screen loses
            // the one highlight it never asked for and always gets: the
            // brackets and the blurb stay where the bundle authored them
            // until the player moves. leaveScreen is already after
            // SCREEN_UNACTIVATE for the same reason.
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

    memset(&data, 0, sizeof(data));
    data.port  = port;
    data.param = 1;
    data.noise = BSND_MENU_CANCEL;
    if (gf->screen) data.itemHash = gf->screen->hash;

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
    return bgf_move_to_previous_screen(gf, n, 1, 0);
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
    // bFileExists("PAL.TAG") -- and PAL.TAG is a zero-size ZDIR entry, so
    // which one the retail disc is cannot be settled from the ELF. NTSC is
    // the default here because only the English movie is on the disc.
    gf->videoMode            = 1;
    gf->currLanguage         = 0;
    gf->demoDiscActive       = 0;
    gf->demoModeStatus       = 0;
    gf->legalScreenTimeout   = 7.0f;
    gf->antiPiracyTimeout    = 7.0f;
    gf->beginDemoModeTimeout = 30.0f;
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

int bgf_should_see_language_select(const BGameFlow* gf)
{
    if (gf->frontendLaunchType == 1 && gf->currLanguage == -1) return 1;
    if (gf->demoDiscActive) return 0;
    if (gf->videoMode != 0) return 0;   // NTSC never asks
    return gf->frontendLaunchType == 1;
}

int bgf_should_see_autoload(const BGameFlow* gf)
{
    if (gf->demoDiscActive) return 0;
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

void bgf_unlaunch_frontend_menus(BGameFlow* gf, int raceInProgress)
{
    bgf_pop_screens(gf, 0);
    bgf_change_to_screen(gf, NULL, 0);
    // SetMainScreen(NULL) at 0x0016ac3c. The list's pMainScreenName is set
    // to NULL by the constructor and by this, and by nothing else -- so the
    // "arriving at the main screen resets the stack" tail of ChangeToScreen
    // is dead on this build and is not ported.
    HOOK_VOID(gf, jukebox, 0);
    gf->frontendLaunchType = raceInProgress ? 2 : 3;
    trace(gf, "unlaunch %d", gf->frontendLaunchType);
}

void bgf_consider_start_demo_mode(BGameFlow* gf, uint32_t since)
{
    float idle = (float)(gf->realTimer - since) * (1.0f / 4000.0f);
    if (idle <= gf->beginDemoModeTimeout) return;
    trace(gf, "demo mode");
    HOOK_VOID0(gf, startDemoMode);
}

// --------------------------------------------------- GAMEFLOW_STATE hooks

void bgf_begin_loading_frontend(BGameFlow* gf)
{
    gf->beginScreenFadeTime = 0;

    // FRONTA.BUN is the loading bundle that was meant to stay resident while
    // FRONTB streams in. It is a zero-byte file on this disc, and so are
    // GLOBALA.BUN and INGAMEA.BUN -- the split was never used.
    HOOK_VOID(gf, loadResource, "FRONTEND\\FRONTA.BUN");

    if (gf->currLanguage == -1) gf->needToSetLanguage = 1;
    HOOK_VOID(gf, setLanguage, gf->currLanguage < 0 ? 0 : gf->currLanguage);

    // The hot-chunking trick: load FRONTB.LZC, then tell the resource system
    // it is called FRONTB.BUN. Only the .LZC is really on the disc.
    HOOK_VOID(gf, loadResource, "FRONTEND\\FRONTB.BUN");
}

void bgf_loop_loading_frontend(BGameFlow* gf)
{
    uint32_t elapsed = gf->realTime - gf->beginScreenFadeTime;

    // The demo disc's three-panel slideshow, three seconds each: 181, 361
    // and 541 are RealTime ticks at 60Hz. Dead on retail, because
    // TheDemoDiscManager.bActive is 0 and nothing ever sets it.
    if (gf->demoDiscActive && elapsed < 541) {
        if (elapsed >= 361) {
            screenVisible(gf, BGF_SCREEN_SLIDE2, 0);
            screenVisible(gf, BGF_SCREEN_DISCLAIMER, 1);
        } else if (elapsed >= 181) {
            screenVisible(gf, BGF_SCREEN_FIRSTLEGAL, 0);
            screenVisible(gf, BGF_SCREEN_SLIDE2, 1);
        }
        return;
    }

    // The original tests IsResourceLoadingComplete() and then
    // IsSoundRegionLoadingComplete(); the port has one loader, so one hook
    // answers for both.
    if (gf->hooks.resourcesReady && !gf->hooks.resourcesReady(gf->hooks.user))
        return;
    if (gf->needToSetLanguage) {
        HOOK_VOID(gf, setLanguage, -1);
        gf->needToSetLanguage = 0;
    }
    bgf_change_state(gf, BGF_IN_FRONTEND, BGF_NONE);
}

void bgf_end_loading_frontend(BGameFlow* gf)
{
    // eFixUpTables, InitCarEffects, InitFrontendSounds, InitSelectCarScreen
    // and InitMoviePlayer run here in the original. On the 3DS the renderer
    // and the bundles are already up by the time the flow starts, so the
    // only part of this that has an effect is the visibility and the launch.
    screenVisible(gf,
                  gf->demoDiscActive ? BGF_SCREEN_DISCLAIMER
                                     : BGF_SCREEN_LOADING_TRACK,
                  0);
    bgf_launch_frontend_menus(gf);
}

void bgf_begin_unloading_frontend(BGameFlow* gf)
{
    bgf_change_to_screen(gf, NULL, 0);
    bgf_reset_stack(gf);
}

// ------------------------------------------------------- TitleMoviesToPlay

// 0x002f3770. Eight language rows of two. Only EALOGO_EN.AVI is actually on
// the disc -- NFSINTRO_EN.AVI is in none of the 3,321 names in ZDIR.BIN, so
// on this build the sequence is one movie long. The port keeps the whole
// table because the flow reads its length, and skips what it cannot open.
static const BTitleMovie kTitleMovies[8][2] = {
    { { "MOVIES\\INTRO\\EALOGO_EN.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
    { { "MOVIES\\INTRO\\EALOGO_FR.AVI", 0 },
      { "MOVIES\\INTRO\\NFSINTRO_EN.AVI", 1 } },
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

// DemoDiscTitleMoviesToPlay (0x002f37f0) is the same table with the EA logo
// only, which is why GetNumTitleMovies answers 1 there.
int bgf_num_title_movies(const BGameFlow* gf)
{
    return gf->demoDiscActive ? 1 : 2;
}

const BTitleMovie* bgf_title_movie(const BGameFlow* gf, int i)
{
    int lang = gf->currLanguage;
    if (lang < 0 || lang > 7) lang = 0;
    if (i < 0 || i > 1) i = 0;
    return &kTitleMovies[lang][i];
}

// ------------------------------------------------------------- TitleScreen

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
        // NFSINTRO_EN.AVI is not on the disc. The original would sit on a
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

// DriveMovie (0x0016a060) returns 1 when the movie is finished.
static int titleDriveMovie(BGameFlow* gf)
{
    if (!gf->title.playing) return 1;
    if (!gf->hooks.movieDrive) return 1;
    return gf->hooks.movieDrive(gf->hooks.user);
}

static void titleActivate(BGameFlow* gf, BScreenCallbackData* data)
{
    BTitleScreen* t = &gf->title;

    memset(t, 0, sizeof(*t));
    t->port       = data ? data->port : 0;
    t->movieIndex = 0;

    if (gf->skipMovies) {
        t->mode  = 1;
        t->timer = gf->realTimer;
        HOOK_VOID(gf, jukebox, 1);
        return;
    }
    t->mode = 2;
    // pMoviePlane is fixed to the 4:3 plane at construction and never
    // re-fetched, even when a letterboxed movie makes the other plane
    // visible. Faithfully reproduced: only the 4:3 plane is ever blitted.
    titleOpenMovie(gf, 0);
    objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_PRESS_START, 0);
}

static void titleUnactivate(BGameFlow* gf)
{
    if (gf->title.playing) {
        HOOK_VOID0(gf, movieClose);
        gf->title.playing = 0;
    }
    memset(&gf->title, 0, sizeof(gf->title));
}

// HandleTick, 0x0016a360.
static void titleTick(BGameFlow* gf)
{
    BTitleScreen* t = &gf->title;

    if (t->mode == 2) {
        if (titleDriveMovie(gf) != 1) return;
        t->movieIndex++;
        if (gf->demoDiscActive)
            screenVisible(gf, BGF_SCREEN_TITLE, 0);
        else
            objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_PRESS_START, 1);
        if (t->playing) {
            HOOK_VOID0(gf, movieClose);
            t->playing = 0;
        }
        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_43, 0);
        objectVisible(gf, BGF_SCREEN_TITLE, BGF_OBJ_MOVIE_PLANE_LB, 0);

        if (t->movieIndex == bgf_num_title_movies(gf)) {
            t->timer = gf->realTimer;
            t->mode  = 1;
            // The screen is now at rest with PRESS START up, waiting either
            // for the button or for the attract-mode timeout. Traced because
            // it is the one moment a test can point at and say the title
            // sequence finished.
            trace(gf, "title idle");
            if (!gf->demoDiscActive) HOOK_VOID(gf, jukebox, 1);
            return;
        }
        titleOpenMovie(gf, t->movieIndex);
        return;
    }
    if (t->mode == 1) bgf_consider_start_demo_mode(gf, t->timer);
}

// HandleEvent, 0x0016a148 -- a 17-entry jump table on message - 1.
static void titleEvent(BGameFlow* gf, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    BTitleScreen* t = &gf->title;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            // The EA logo cannot be skipped and the NFS intro can: during
            // movie 0 movieIndex is still 0 and this test fails.
            if (t->mode == 1 || (t->mode == 2 && t->movieIndex != 0)) {
                if (gf->demoDiscActive) {
                    data->noise = 0;
                    return;
                }
                bgf_change_to_screen(gf, "New Main Menu", 1);
            }
            data->noise = 0;
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
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            memset(&gf->autoload, 0, sizeof(gf->autoload));
            gf->autoload.port  = data ? data->port : 0;
            gf->autoload.state = 1;             // loading
            // The constructor calls FlailerScreenList::StopMovie first.
            HOOK_VOID0(gf, movieClose);
            HOOK_VOID0(gf, saveStart);
            trace(gf, "autoload start");
            break;

        case BMSG_SCREEN_TICK:
            // The original polls the memory card from HandleEvent and only
            // tests state here. There are no memcard events on the 3DS, so
            // the poll moves into the tick; the shape -- tick until an
            // asynchronous job finishes, then pop yourself -- is the same.
            if (gf->autoload.state == 1 || gf->autoload.state == 2) {
                if (!gf->hooks.savePoll
                    || gf->hooks.savePoll(gf->hooks.user)) {
                    gf->autoload.state = 0;
                    trace(gf, "autoload done");
                }
            }
            if (gf->autoload.state == 0) bgf_move_back_screen(gf, 1);
            break;

        case BMSG_SCREEN_UNACTIVATE:
            memset(&gf->autoload, 0, sizeof(gf->autoload));
            break;

        default:
            break;
    }
}

// ------------------------------------------------------------ plain screen

void bgf_plain_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data)
{
    (void)gf;
    (void)data;
    (void)msg;
}

// ------------------------------------------------------------ NewMainMenu

// HandleEvent, 0x00203768: a 24-entry jump table on message - 1, of which
// only SELECT, TICK and HIGHLIGHT do anything. SELECT is a three-way test on
// the item hash, and the two Mode Selects are the same screen either side of
// a global:
//
//   MENUITEM_1 "Hot Pursuit"  -> CopsOn = 1, "Cops On Mode Select"   0x00203800
//   MENUITEM_2 "World Racing" -> CopsOn = 0, "Cops Off Mode Select"  0x00203818
//   MENUITEM_3 "Options"      ->             "Options"               0x00203830
//
// All three push New Main Menu, so BACK returns here, and all three are in
// the port's screen registry (kScreens[] in main.c, bscreens.c for the
// classes). Every screen name the port's own code can reach is registered
// now; the ten that have no class yet are registered to
// bgf_plain_screen_callback so they draw. An unregistered name would be
// worse than a dead one: bgf_change_to_screen traces "unregistered" and
// leaves the flow with no current screen, which is what ChangeToScreen does
// too -- it clears pCurrent before it looks the name up -- so the top
// screen goes black and BACK is the only way out. See TASKS.md 33, and
// `python tools/screen_registry.py --check-port` for what is left.
void bgf_new_main_menu_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data)
{
    if (msg != BMSG_MENUITEM_SELECT || !data) return;

    switch (data->itemHash) {
        case BGF_ITEM_MENUITEM_1:
            gf->copsOn = 1;
            bgf_change_to_screen(gf, "Cops On Mode Select", 1);
            break;
        case BGF_ITEM_MENUITEM_2:
            gf->copsOn = 0;
            bgf_change_to_screen(gf, "Cops Off Mode Select", 1);
            break;
        case BGF_ITEM_MENUITEM_3:
            bgf_change_to_screen(gf, "Options", 1);
            break;
        default:
            // Every other item hash falls off the end of the jump table
            // entry and returns, sound and all.
            break;
    }
}
