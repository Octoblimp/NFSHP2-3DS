// Host harness for the 3DS boot flow.
//
// Builds "3DS Files/source/gameflow.c" for the host and runs a fixed set of
// boot scenarios against a simulated world -- a loader that finishes at the
// end of the frame that asked, a movie that runs five frames, a memory card
// that answers on the second poll -- printing every observable step:
//
//     scenario <name>
//     frame <n> <realTime> <realTimer>
//     <whatever the flow traced: state, begin, end, change, enter, leave,
//      msg, stack, vis, movie, tex, sound, load, language, speech, gray,
//      autoload, demo mode>
//     final <state> <screen> <stackDepth>
//
// tools/bootflow_check.py prints the same from retail's own code, run on
// SLES_507.31 in mipsemu where it can be, and diffs the two. Nothing here
// reads a bundle: the boot flow is behaviour, and the point of the diff is
// to catch a misread of the behaviour.
//
// Usage: gameflow_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gameflow.h"

// ------------------------------------------------------------- the world

#define MOVIE_FRAMES   5
#define LOADER_FRAMES  1
#define TEXTURE_POLLS  2
#define SAVE_POLLS     2
#define MAX_PENDING    4

typedef struct {
    const char* name;
    int videoMode;
    int currLanguage;
    int skipMovies;
    int frontendLaunchType;
    int demoModeStatus;
    int demoDiscActive;
    int haveIntroMovie;   // pretend NFSINTRO_EN.AVI is on the disc
    int forceLegal;       // turn the dead MumboJumbo panels back on
    int frames;
    float dt;
    // up to six scripted inputs: frame number and what to do
    struct { int frame; const char* what; } input[6];
} Scenario;

// A load in flight: what to print when it lands, and its callback.
typedef struct {
    const char*   label;
    BGameFlowDone done;
} Pending;

typedef struct {
    const Scenario* sc;
    BGameFlow*      gf;
    int             movieOpen;
    int             movieLeft;
    int             texPolls;
    int             savePolls;
    int             loaderDue;    // nothing lands before this frame count
    uint32_t        activeItem;   // the highlighted item, for GetActiveMenuItem
    Pending         pending[MAX_PENDING];
    int             numPending;
} World;

static void wTrace(void* user, const char* line)
{
    (void)user;
    printf("%s\n", line);
}

static int wMovieOpen(void* user, const char* path)
{
    World* w = (World*)user;
    // Only MOVIES\INTRO\EALOGO_EN.AVI is really in ZDIR.BIN. The scenario
    // can pretend the NFS intro is there too, which is the only way to
    // exercise the second movie at all.
    int present = strcmp(path, "MOVIES\\INTRO\\EALOGO_EN.AVI") == 0
                  || (w->sc->haveIntroMovie
                      && strcmp(path, "MOVIES\\INTRO\\NFSINTRO_EN.AVI") == 0);
    if (!present) return 0;
    w->movieOpen = 1;
    w->movieLeft = MOVIE_FRAMES;
    return 1;
}

static int wMovieDrive(void* user)
{
    World* w = (World*)user;
    if (w->movieLeft > 0) w->movieLeft--;
    return w->movieLeft == 0;
}

// Closing a movie that is open is traced; closing nothing is not, since
// retail's destructor closes whether or not anything is playing.
static void wMovieClose(void* user)
{
    World* w = (World*)user;
    if (w->movieOpen) printf("movie close\n");
    w->movieOpen = 0;
    w->movieLeft = 0;
}

static void wQueue(World* w, const char* label, BGameFlowDone done)
{
    if (!done) return;
    if (w->numPending >= MAX_PENDING) {
        printf("loader full %s\n", label);
        return;
    }
    w->pending[w->numPending].label = label;
    w->pending[w->numPending].done  = done;
    w->numPending++;
}

static void wLoadResource(void* user, const char* path, BGameFlowDone done)
{
    wQueue((World*)user, path, done);
}

static void wLoadSoundRegions(void* user, BGameFlowDone done)
{
    wQueue((World*)user, "sound regions", done);
}

// ServiceResourceLoading, at the frame's end: MainLoop calls it after
// eDisplayFrame (0x0012f60c). A load asked for during a frame has landed by
// the end of it and its callback runs then; a load that callback asks for
// lands at the next frame's end.
static void wServiceLoads(World* w)
{
    Pending run[MAX_PENDING];
    int     n = w->numPending;
    if ((int)w->gf->frameCounter < w->loaderDue) return;
    memcpy(run, w->pending, sizeof(run[0]) * (size_t)n);
    w->numPending = 0;
    for (int i = 0; i < n; i++) {
        printf("loaded %s\n", run[i].label);
        run[i].done(w->gf);
    }
}

static void wLoadTexture(void* user, uint32_t tex)
{
    (void)tex;
    ((World*)user)->texPolls = 0;
}

static int wTextureReady(void* user, uint32_t tex)
{
    World* w = (World*)user;
    (void)tex;
    return ++w->texPolls >= TEXTURE_POLLS;
}

static void wUnloadTexture(void* user, uint32_t tex) { (void)user; (void)tex; }

static void wSaveStart(void* user) { ((World*)user)->savePolls = 0; }

static int wSavePoll(void* user)
{
    World* w = (World*)user;
    return ++w->savePolls >= SAVE_POLLS;
}

// A new menu starts on its first item.
static void wOpenScreen(void* user, const BScreenConfig* cfg)
{
    ((World*)user)->activeItem = BGF_ITEM_MENUITEM_1;
    printf("ui open %08x\n", (unsigned)cfg->hash);
}

static void wEnterScreen(void* user, const BScreenConfig* cfg)
{
    (void)user;
    printf("ui enter %08x\n", (unsigned)cfg->hash);
}

static void wLeaveScreen(void* user, const BScreenConfig* cfg)
{
    (void)user;
    printf("ui leave %08x\n", (unsigned)cfg->hash);
}

static uint32_t wActiveMenuItem(void* user)
{
    return ((World*)user)->activeItem;
}

static void wSound(void* user, int ev) { (void)user; (void)ev; }
static void wJukebox(void* user, int start)
{
    (void)user;
    printf("jukebox %d\n", start);
}
static void wStartDemoMode(void* user) { (void)user; printf("attract\n"); }
static void wSetScreenVisible(void* u, uint32_t s, int v)
{ (void)u; (void)s; (void)v; }
static void wSetObjectVisible(void* u, uint32_t s, uint32_t o, int v)
{ (void)u; (void)s; (void)o; (void)v; }
static void wSetGroupVisible(void* u, uint32_t s, uint32_t g, int v)
{ (void)u; (void)s; (void)g; (void)v; }
static void wChangeTexture(void* u, uint32_t s, uint32_t o, uint32_t t)
{ (void)u; (void)s; (void)o; (void)t; }

// ---------------------------------------------------------- the two tables

// The screen registry, the subset the boot flow names. Recovered by
// tools/screen_registry.py: `name` is the C++ literal, `hash` is
// bStringHash of the authored name, and they are different strings.
static const BScreenConfig kScreens[] = {
    { "BootAutoload",            BGF_SCREEN_BOOT_AUTOLOAD,
      bgf_boot_autoload_callback },
    { "Language Options Pre FE", BGF_SCREEN_LANGUAGE,
      bgf_language_screen_callback },
    { "Title Screen",            BGF_SCREEN_TITLE,
      bgf_title_screen_callback },
    { "New Main Menu",           BGF_SCREEN_NEW_MAIN_MENU,
      bgf_new_main_menu_callback },
    // Unreachable on the retail build -- ShouldSeeLegalMumboJumbo returns 0
    // -- but registered so a scenario can force it.
    { "Legal MumboJumbo",        BGF_SCREEN_MUMBO_JUMBO,
      bgf_mumbo_jumbo_callback },
};

// LaunchFrontendMenus' push list. The last row that passes is the first
// screen seen.
static const BBootStage kBootStages[] = {
    { "Title Screen",            bgf_should_see_title_sequence },
    { "Legal MumboJumbo",        bgf_should_see_legal_mumbo_jumbo },
    { "Language Options Pre FE", bgf_should_see_language_select },
    { "BootAutoload",            bgf_should_see_autoload },
};

static const BGameFlowStateInfo kGameFlowStates[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         bgf_begin_loading_frontend,
                                  bgf_end_loading_frontend,
                                  bgf_loop_loading_frontend },
    { "UNLOADING_FRONTEND",       bgf_begin_unloading_frontend, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     NULL, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   NULL, NULL, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", NULL, NULL, NULL },
    { "UNLOADING_TRACK_COMMON",   NULL, NULL, NULL },
    { "EXIT_DEMO_DISC",           NULL, NULL, NULL },
};

// ------------------------------------------------------------- scenarios

#define SIXTIETH (1.0f / 60.0f)

// `currLanguage` is what the language is once LoadGlobalChunks has set
// English: 0 leaves it, another language is set through SetCurrLanguage,
// and -1 is written straight over it -- a state the disc never reaches,
// kept for the predicate's first test and the screen's -1 paths.
static const Scenario kScenarios[] = {
    // An NTSC console: no language screen.
    { "ntsc", 1, 0, 0, 1, 0, 0, 0, 0, 40, SIXTIETH, {{0,0}} },
    // The shipped boot, PAL: BootAutoload, then Language Options Pre FE,
    // which waits for a choice.
    { "pal", 0, 0, 0, 1, 0, 0, 0, 0, 40, SIXTIETH, {{0,0}} },
    // No language at all: the first test in the predicate fires whatever
    // the video mode is. BACK there is vetoed and does nothing else, since
    // there is nothing to keep; Spanish is then chosen and the screen moves
    // back to the title, whose movies are Spanish.
    { "nolang", 1, -1, 0, 1, 0, 0, 0, 0, 40, SIXTIETH,
      {{10, "back"}, {14, "item5"}} },
    // SkipMovies: the title screen starts at rest, with no movie.
    { "skipmovies", 1, 0, 1, 1, 0, 0, 0, 0, 30, SIXTIETH, {{0,0}} },
    // A second visit to the frontend with a demo waiting: straight to the
    // main menu, stack reset -- so BACK there pops to nothing and stays.
    { "relaunch", 1, 0, 0, 2, 2, 0, 0, 0, 20, SIXTIETH, {{10, "back"}} },
    // The demo disc: one title movie, the three-panel loading slideshow,
    // and no attract mode. Dead on this disc; here for the branch. The
    // slideshow does not hold the load up -- FRONTB's callback moves the
    // flow on whenever it lands -- so the loader is slow here, ten seconds,
    // or the slideshow would never get past its first panel.
    { "demodisc", 1, 0, 0, 1, 0, 1, 0, 0, 700, SIXTIETH, {{0, "slow600"}} },
    // At rest on the title for over thirty seconds at one second a frame:
    // PRESS START comes up after four, attract mode after thirty.
    { "attract", 1, 0, 1, 1, 0, 0, 0, 0, 40, 1.0f, {{0,0}} },
    // The title comes to rest at frame 9, and PRESS START is up 243 frames
    // later -- the first multiple of 66 ticks over 16000. Select at 14 is
    // too early and does nothing; select at 270 goes to the main menu;
    // select again there does nothing; BACK returns to the title screen,
    // which plays its movies again, and BACK again is vetoed by the title
    // screen's own SCREEN_BACK_BUTTON handler.
    { "select", 1, 0, 0, 1, 0, 0, 0, 0, 300, SIXTIETH,
      {{14, "select"}, {270, "select"}, {282, "select"}, {288, "back"},
       {292, "back"}} },
    // With the NFS intro present. Movie 0 runs over frames 3-7 and movie 1
    // over 8-12, so select at 5 lands inside the EA logo and is ignored --
    // movieIndex is still 0 -- and select at 10 lands inside the NFS intro
    // and stops it: the title comes to rest, still on Title Screen. Select
    // at 20 is before PRESS START and does nothing; select at 262 is after
    // it and goes to the main menu.
    // START at 21, which the title swallows without a sound.
    { "skipintro", 1, 0, 0, 1, 0, 0, 1, 0, 300, SIXTIETH,
      {{5, "select"}, {10, "select"}, {20, "select"}, {21, "start"},
       {262, "select"}} },
    // The intro stopped at frame 10, then left alone at one second a frame:
    // attract mode comes thirty seconds after the skip, not after the
    // screen's arrival, because the skip restarts the Timer at +16.
    { "skipidle", 1, 0, 0, 1, 0, 0, 1, 0, 50, 1.0f, {{10, "select"}} },
    // The same with the movies left to finish: thirty seconds from the
    // moment the title comes to rest, which restarts the Timer too.
    { "restidle", 1, 0, 0, 1, 0, 0, 0, 0, 50, 1.0f, {{0,0}} },
    // The three main-menu items, each of which asks for a screen the port
    // has not registered: the flow is left with no current screen, and BACK
    // pops New Main Menu back. Hot Pursuit and World Racing differ only in
    // CopsOn, which "final" prints.
    { "mainmenu", 1, 0, 1, 1, 0, 0, 0, 0, 40, SIXTIETH,
      {{4, "select"}, {8, "item3"}, {12, "back"}, {16, "item1"}} },
    // Force the legal screen, which the retail predicate never allows.
    { "mumbo", 1, 0, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{12, "mumbo"}} },
    // The same with the two dead predicates turned on, so the legal and
    // anti-piracy panels and their 7-second timers actually run. One second
    // a frame, because 14 seconds at 1/60 is 840 frames of nothing.
    { "legal", 1, 0, 0, 1, 0, 0, 0, 1, 40, 1.0f, {{5, "mumbo"}} },
    // French from the start: the second movie is retail's own French
    // intro, and the LOADING art is the French one.
    { "french", 1, 1, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{0,0}} },
    // PAL, French chosen on the language screen: the table, the speech and
    // the LOADING art all change, the frontend takes its defaults, and the
    // screen moves back to the title -- whose EA logo is EALOGO_FR.
    { "palselect", 0, 0, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{8, "item2"}} },
    // PAL, BACK on the language screen with Italian highlighted: BACK
    // chooses the highlighted language, as SELECT would.
    { "palback", 0, 0, 0, 1, 0, 0, 0, 0, 30, SIXTIETH,
      {{7, "hl4"}, {8, "back"}} },
    // PAL, Load All Languages. Hidden on this disc, and selected anyway:
    // the flag is set and the screen moves back with English kept.
    { "palall", 0, 0, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{8, "item7"}} },
    // PAL, English chosen when English is in: SetLanguage returns at once,
    // and the frontend still takes its defaults.
    { "palsame", 0, 0, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{8, "item1"}} },
    // PAL, French from the start and English chosen: the French LOADING art
    // is swapped back.
    { "palrevert", 0, 1, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{8, "item1"}} },
};
#define NUM_SCENARIOS ((int)(sizeof(kScenarios) / sizeof(kScenarios[0])))

static void runScenario(const Scenario* sc)
{
    BGameFlow      gf;
    BGameFlowHooks hooks;
    World          w;
    BAnim          anim;

    printf("scenario %s\n", sc->name);

    memset(&w, 0, sizeof(w));
    w.sc        = sc;
    w.gf        = &gf;
    w.loaderDue = LOADER_FRAMES;

    memset(&hooks, 0, sizeof(hooks));
    hooks.user             = &w;
    hooks.trace            = wTrace;
    hooks.setScreenVisible = wSetScreenVisible;
    hooks.setObjectVisible = wSetObjectVisible;
    hooks.setGroupVisible  = wSetGroupVisible;
    hooks.changeTexture    = wChangeTexture;
    hooks.openScreen       = wOpenScreen;
    hooks.enterScreen      = wEnterScreen;
    hooks.leaveScreen      = wLeaveScreen;
    hooks.activeMenuItem   = wActiveMenuItem;
    hooks.movieOpen        = wMovieOpen;
    hooks.movieDrive       = wMovieDrive;
    hooks.movieClose       = wMovieClose;
    hooks.loadResource     = wLoadResource;
    hooks.loadSoundRegions = wLoadSoundRegions;
    hooks.loadTexture      = wLoadTexture;
    hooks.textureReady     = wTextureReady;
    hooks.unloadTexture    = wUnloadTexture;
    hooks.saveStart        = wSaveStart;
    hooks.savePoll         = wSavePoll;
    hooks.sound            = wSound;
    hooks.jukebox          = wJukebox;
    hooks.startDemoMode    = wStartDemoMode;

    bgf_init(&gf, kGameFlowStates, BGF_NUM_STATES,
             kScreens, (int)(sizeof(kScreens) / sizeof(kScreens[0])),
             kBootStages, (int)(sizeof(kBootStages) / sizeof(kBootStages[0])),
             &hooks);

    gf.videoMode          = sc->videoMode;
    gf.skipMovies         = sc->skipMovies;
    gf.frontendLaunchType = sc->frontendLaunchType;
    gf.demoModeStatus     = sc->demoModeStatus;
    gf.demoDiscActive     = sc->demoDiscActive;
    gf.forceLegalScreens  = sc->forceLegal;

    // The title's bloom, on an animation kit with no world: nothing on the
    // screen to find, so it only keeps its timers.
    banim_init(&anim, NULL);
    gf.anim = &anim;

    // InitializeEverything's LoadGlobalChunks, then the scenario's language.
    bgf_load_global_chunks(&gf);
    if (sc->currLanguage == -1) {
        printf("input no language\n");
        gf.currLanguage = -1;
    } else if (sc->currLanguage != 0) {
        printf("input language %d\n", sc->currLanguage);
        bgf_set_curr_language(&gf, sc->currLanguage);
    }

    // main (0x0012da88): ask for LOADING_FRONTEND, then hand over to
    // MainLoop. SkipFE would call StartSkipFEGame instead; it ships as 0.
    bgf_change_state(&gf, BGF_LOADING_FRONTEND, BGF_NONE);

    for (int f = 0; f < sc->frames; f++) {
        for (int i = 0; i < 6; i++) {
            const char* what = sc->input[i].what;
            if (!what || sc->input[i].frame != f) continue;
            if (!strcmp(what, "select")) {
                printf("input select\n");
                bgf_screen_event(&gf, BMSG_MENUITEM_SELECT, 0);
            } else if (!strcmp(what, "start")) {
                // START with no menu, as main.c sends it.
                printf("input start\n");
                bgf_screen_event(&gf, BMSG_SCREEN_START_BUTTON, 0);
            } else if (!strcmp(what, "back")) {
                // The pad's BACK, from port 0.
                printf("input back\n");
                bgf_back_button(&gf, 0);
            } else if (!strncmp(what, "item", 4)) {
                // A menu item selected by hash, the way FlailerMenu sends
                // it: "item<n>" is MENUITEM_n.
                unsigned n = (unsigned)(what[4] - '1');
                printf("input %s\n", what);
                bgf_menu_item_event(&gf, BMSG_MENUITEM_SELECT,
                                    BGF_ITEM_MENUITEM_1 + n, 0);
            } else if (!strncmp(what, "hl", 2)) {
                // The highlight moved to MENUITEM_n.
                printf("input %s\n", what);
                w.activeItem = BGF_ITEM_MENUITEM_1 + (unsigned)(what[2] - '1');
            } else if (!strncmp(what, "slow", 4)) {
                // A slow loader: nothing lands before frame n.
                printf("input %s\n", what);
                w.loaderDue = atoi(what + 4);
            } else if (!strcmp(what, "mumbo")) {
                printf("input mumbo\n");
                bgf_push_screen(&gf, "New Main Menu");
                bgf_change_to_screen(&gf, "Legal MumboJumbo", 0);
            }
        }
        bgf_frame(&gf, sc->dt);
        wServiceLoads(&w);
        printf("frame %d %u %u\n", f, (unsigned)gf.realTime,
               (unsigned)gf.realTimer);
    }

    printf("final %s %s %d cops %d language %d\n",
           bgf_state_name(&gf, gf.current),
           gf.screen ? gf.screen->name : "-", gf.stack.index, gf.copsOn,
           gf.currLanguage);
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        for (int i = 0; i < NUM_SCENARIOS; i++) runScenario(&kScenarios[i]);
        return 0;
    }
    for (int a = 1; a < argc; a++) {
        int found = 0;
        for (int i = 0; i < NUM_SCENARIOS; i++) {
            if (strcmp(kScenarios[i].name, argv[a])) continue;
            runScenario(&kScenarios[i]);
            found = 1;
        }
        if (!found) {
            fprintf(stderr, "unknown scenario: %s\n", argv[a]);
            return 2;
        }
    }
    return 0;
}
