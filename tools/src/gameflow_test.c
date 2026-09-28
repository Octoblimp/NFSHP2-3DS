// Host harness for the 3DS boot flow.
//
// Builds "3DS Files/source/gameflow.c" for the host and runs a fixed set of
// boot scenarios against a simulated world -- a loader that finishes after
// three frames, a movie that runs five, a memory card that answers on the
// second poll -- printing every observable step:
//
//     scenario <name>
//     frame <n> <realTime> <realTimer>
//     <whatever the flow traced: state, begin, end, change, enter, leave,
//      msg, stack, vis, movie, tex, sound, autoload, demo mode>
//     final <state> <screen> <stackDepth>
//
// tools/bootflow_check.py prints the same from an independent Python model
// of the same disassembly and diffs the two, the way bmenu_check.py does for
// the menus. Nothing here reads a bundle: the boot flow is behaviour, and
// the point of the diff is to catch a misread of the behaviour.
//
// Usage: gameflow_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "gameflow.h"

// ------------------------------------------------------------- the world

#define MOVIE_FRAMES   5
#define LOADER_FRAMES  3
#define TEXTURE_POLLS  2
#define SAVE_POLLS     2

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
    // up to four scripted inputs: frame number and what to do
    struct { int frame; const char* what; } input[4];
} Scenario;

typedef struct {
    const Scenario* sc;
    BGameFlow*      gf;
    int             movieLeft;
    int             texPolls;
    int             savePolls;
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
    w->movieLeft = MOVIE_FRAMES;
    return 1;
}

static int wMovieDrive(void* user)
{
    World* w = (World*)user;
    if (w->movieLeft > 0) w->movieLeft--;
    return w->movieLeft == 0;
}

static void wMovieClose(void* user) { ((World*)user)->movieLeft = 0; }

static void wLoadResource(void* user, const char* path)
{
    (void)user;
    printf("load %s\n", path);
}

static int wResourcesReady(void* user)
{
    World* w = (World*)user;
    return (int)w->gf->frameCounter >= LOADER_FRAMES;
}

static void wSetLanguage(void* user, int language)
{
    (void)user;
    printf("language %d\n", language);
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
      bgf_plain_screen_callback },
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

static const Scenario kScenarios[] = {
    // The shipped boot, on an NTSC console: no language screen.
    { "ntsc", 1, 0, 0, 1, 0, 0, 0, 0, 40, SIXTIETH, {{0,0}} },
    // The same on PAL, which adds Language Options Pre FE.
    { "pal", 0, 0, 0, 1, 0, 0, 0, 0, 40, SIXTIETH, {{0,0}} },
    // No language chosen yet: the first test in the predicate fires whatever
    // the video mode is.
    { "nolang", 1, -1, 0, 1, 0, 0, 0, 0, 40, SIXTIETH, {{0,0}} },
    // SkipMovies: the title screen starts idle on PRESS START.
    { "skipmovies", 1, 0, 1, 1, 0, 0, 0, 0, 30, SIXTIETH, {{0,0}} },
    // A second visit to the frontend with a demo waiting: straight to the
    // main menu, stack reset -- so BACK there pops to nothing and stays.
    { "relaunch", 1, 0, 0, 2, 2, 0, 0, 0, 20, SIXTIETH, {{10, "back"}} },
    // The demo disc: one title movie, the three-panel loading slideshow,
    // and no attract mode. Dead on this disc; here for the branch.
    { "demodisc", 1, 0, 0, 1, 0, 1, 0, 0, 700, SIXTIETH, {{0,0}} },
    // Idle on PRESS START for over thirty seconds at one second a frame.
    { "attract", 1, 0, 1, 1, 0, 0, 0, 0, 40, 1.0f, {{0,0}} },
    // Select once the title screen is idle goes to the main menu; select
    // again there does nothing; BACK returns to the title screen, and BACK
    // again is vetoed by the title screen's own SCREEN_BACK_BUTTON handler.
    { "select", 1, 0, 0, 1, 0, 0, 0, 0, 40, SIXTIETH,
      {{14, "select"}, {26, "select"}, {32, "back"}, {36, "back"}} },
    // With the NFS intro present. Movie 0 runs over frames 3-7 and movie 1
    // over 8-12, so select at 5 lands inside the EA logo and is ignored --
    // movieIndex is still 0 -- and select at 10 lands inside the NFS intro
    // and skips straight to the main menu.
    { "skipintro", 1, 0, 0, 1, 0, 0, 1, 0, 40, SIXTIETH,
      {{5, "select"}, {10, "select"}, {0, 0}} },
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
    // French: the second movie is retail's own French intro.
    { "french", 1, 1, 0, 1, 0, 0, 0, 0, 30, SIXTIETH, {{0,0}} },
};
#define NUM_SCENARIOS ((int)(sizeof(kScenarios) / sizeof(kScenarios[0])))

static void runScenario(const Scenario* sc)
{
    BGameFlow      gf;
    BGameFlowHooks hooks;
    World          w;

    printf("scenario %s\n", sc->name);

    memset(&w, 0, sizeof(w));
    w.sc = sc;
    w.gf = &gf;

    memset(&hooks, 0, sizeof(hooks));
    hooks.user             = &w;
    hooks.trace            = wTrace;
    hooks.setScreenVisible = wSetScreenVisible;
    hooks.setObjectVisible = wSetObjectVisible;
    hooks.changeTexture    = wChangeTexture;
    hooks.enterScreen      = wEnterScreen;
    hooks.leaveScreen      = wLeaveScreen;
    hooks.movieOpen        = wMovieOpen;
    hooks.movieDrive       = wMovieDrive;
    hooks.movieClose       = wMovieClose;
    hooks.loadResource     = wLoadResource;
    hooks.resourcesReady   = wResourcesReady;
    hooks.setLanguage      = wSetLanguage;
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
    gf.currLanguage       = sc->currLanguage;
    gf.skipMovies         = sc->skipMovies;
    gf.frontendLaunchType = sc->frontendLaunchType;
    gf.demoModeStatus     = sc->demoModeStatus;
    gf.demoDiscActive     = sc->demoDiscActive;
    gf.forceLegalScreens  = sc->forceLegal;

    // main (0x0012da88): ask for LOADING_FRONTEND, then hand over to
    // MainLoop. SkipFE would call StartSkipFEGame instead; it ships as 0.
    bgf_change_state(&gf, BGF_LOADING_FRONTEND, BGF_NONE);

    for (int f = 0; f < sc->frames; f++) {
        for (int i = 0; i < 4; i++) {
            if (!sc->input[i].what || sc->input[i].frame != f) continue;
            if (!strcmp(sc->input[i].what, "select")) {
                printf("input select\n");
                bgf_screen_event(&gf, BMSG_MENUITEM_SELECT, 0);
            } else if (!strcmp(sc->input[i].what, "back")) {
                printf("input back\n");
                bgf_move_back_screen(&gf, 1);
            } else if (!strncmp(sc->input[i].what, "item", 4)) {
                // A menu item selected by hash, the way FlailerMenu sends
                // it. "item1".."item3" are NEW_MAIN_MENU's three.
                unsigned n = (unsigned)(sc->input[i].what[4] - '1');
                printf("input %s\n", sc->input[i].what);
                bgf_menu_item_event(&gf, BMSG_MENUITEM_SELECT,
                                    BGF_ITEM_MENUITEM_1 + n, 0);
            } else if (!strcmp(sc->input[i].what, "mumbo")) {
                printf("input mumbo\n");
                bgf_push_screen(&gf, "New Main Menu");
                bgf_change_to_screen(&gf, "Legal MumboJumbo", 0);
            }
        }
        bgf_frame(&gf, sc->dt);
        printf("frame %d %u %u\n", f, (unsigned)gf.realTime,
               (unsigned)gf.realTimer);
    }

    printf("final %s %s %d cops %d\n", bgf_state_name(&gf, gf.current),
           gf.screen ? gf.screen->name : "-", gf.stack.index, gf.copsOn);
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
