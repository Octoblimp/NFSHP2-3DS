// NFSHP2-3DS -- the boot flow, and the Flailer screen viewer behind it.
//
// This boots the way the PS2 game boots. source/gameflow.c is the port of
// GameFlowStateInfoTable and LaunchFrontendMenus; the three tables that
// drive it are right here, because they are the part a reader wants to see:
//
//   kGameFlowStages[]  the ten game flow states and their Begin/End/Loop
//   kBootStages[]      LaunchFrontendMenus' push list, with its predicates
//   kScreens[]         the screen registry: name -> hash -> callback
//
// kBootStages[] is this game's kVideoStages[]. It is pushed onto a LIFO and
// entered from the top, so the LAST row whose predicate passes is the FIRST
// screen the player sees -- on this disc BootAutoload, then the title
// screen, then the main menu.
//
// The screens themselves are real: source/bui.c parses the 0x80010200 tree
// out of the bundles and source/uirender.c draws it through citro2d with the
// PS2 textures, fonts and translated strings, and source/bmenu.c makes the
// MENUITEM_n objects navigable.
//
// The title movie plays too. MV3 is not decoded on the handheld -- see
// source/movie.c for why not -- so tools/movie_bake.py turns the disc's one
// movie into MOVIES/INTRO/EALOGO_EN.M3V next to the rest of the data, and
// hookMovieOpen() points the title screen's movie plane at it. A movie with
// no baked file answers "not there", which is exactly the path the flow
// already takes for NFSINTRO_EN.AVI, a file that was never pressed.
//
// Controls, boot mode: D-pad navigates, A selects, START is the game's start
// button, B goes back, SELECT switches to the viewer.
// Viewer mode: L/R change screen, D-pad navigates, X cycles language,
// SELECT returns to the boot flow, START exits.

#include <3ds.h>
#include <citro2d.h>
#include <citro3d.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bmenu.h"
#include "gamedata.h"
#include "gameflow.h"
#include "heapcfg.h"
#include "movie.h"
#include "uirender.h"

#define BUNDLE_FRONTEND "FRONTEND/FRONTB.BUN"
#define BUNDLE_GLOBAL   "GLOBAL/GLOBALB.BUN"
#define BUNDLE_INGAME   "GLOBAL/INGAMEB.BUN"

static const char* const kLanguages[] = {
    "LANGUAGES/FE_ENGLISH.BIN", "LANGUAGES/FE_FRENCH.BIN",
    "LANGUAGES/FE_GERMAN.BIN",  "LANGUAGES/FE_ITALIAN.BIN",
    "LANGUAGES/FE_SPANISH.BIN", "LANGUAGES/FE_SWEDISH.BIN",
    "LANGUAGES/FE_LONGEST.BIN", "LANGUAGES/FE_ID.BIN",
};
#define NUM_LANGUAGES ((int)(sizeof(kLanguages) / sizeof(kLanguages[0])))

// ------------------------------------------------------------- the tables

// FlailerScreenConfig, the subset the boot flow names, recovered by
// tools/screen_registry.py. `name` is the C++ literal ChangeToScreen takes;
// `hash` is bStringHash of the name the screen was authored under, which is
// a different string -- "Title Screen" against TITLE_SCREEN. Nothing but
// this table joins the two.
static const BScreenConfig kScreens[] = {
    { "BootAutoload",            BGF_SCREEN_BOOT_AUTOLOAD,
      bgf_boot_autoload_callback },
    { "Language Options Pre FE", BGF_SCREEN_LANGUAGE,
      bgf_plain_screen_callback },
    { "Title Screen",            BGF_SCREEN_TITLE,
      bgf_title_screen_callback },
    { "New Main Menu",           BGF_SCREEN_NEW_MAIN_MENU,
      bgf_new_main_menu_callback },
    // Authored, shipped, and unreachable: ShouldSeeLegalMumboJumbo is
    // `return 0`. Registered anyway so the screen has somewhere to go if a
    // later build turns it back on.
    { "Legal MumboJumbo",        BGF_SCREEN_MUMBO_JUMBO,
      bgf_mumbo_jumbo_callback },
};
#define NUM_SCREENS ((int)(sizeof(kScreens) / sizeof(kScreens[0])))

// LaunchFrontendMenus (0x0016aa40), the boot sequence itself. Pushed in this
// order, entered from the top.
static const BBootStage kBootStages[] = {
    { "Title Screen",            bgf_should_see_title_sequence },
    { "Legal MumboJumbo",        bgf_should_see_legal_mumbo_jumbo },
    { "Language Options Pre FE", bgf_should_see_language_select },
    { "BootAutoload",            bgf_should_see_autoload },
};
#define NUM_BOOT_STAGES ((int)(sizeof(kBootStages) / sizeof(kBootStages[0])))

// GameFlowStateInfoTable (0x002f2eb0). IN_FRONTEND and RACING are the
// resting states and have no functions at all; the track and race states
// belong to phases the port has not reached.
static const BGameFlowStateInfo kGameFlowStages[BGF_NUM_STATES] = {
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

// ----------------------------------------------------------- the 3DS side

typedef struct {
    UIRenderer* ui;

    // what the boot flow has made current
    BUI*        project;
    BUIScreen*  screen;
    uint32_t    screenHash;
    BMenu       menu;
    bool        hasMenu;

    // The title movie. movieTexHash is the plane's own textureHash rather
    // than a constant: MoviePlayer blits into whatever texture pMoviePlane
    // carries, and on this disc that is SPLASH_SCREEN.
    M3VMovie    movie;
    C3D_Tex     movieTex;
    bool        moviePlaying;
    uint32_t    movieTexHash;

    char        note[64];      // last thing worth putting on the status line
    int         missingMovies;
} Boot;

// One pass of the flow per frame, and the display is vsynced, so this is the
// timestep for both the flow's clocks and the movie's.
#define BOOT_DT (1.0f / 60.0f)

static Boot g_boot;
static BGameFlow g_flow;

// ------------------------------------------------------- the run log
//
// sdmc:/nfshp2_debug.txt, the same arrangement NFSU2-3DS uses: the console
// output goes to the bottom screen where only a human can read it, so
// everything worth grepping is also appended here and
// tools/run_azahar_test.ps1 reads it back after an emulator run. It is how
// "did it boot, did the movie play, did it reach the menu" gets answered
// without anyone watching the window.
static FILE* g_log;

static void logOpen(void)
{
    g_log = fopen("sdmc:/nfshp2_debug.txt", "w");
}

static void logLine(const char* fmt, ...)
{
    va_list ap;
    if (!g_log) return;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);           // an emulator kill must not lose the tail
}

// Everything on the console is worth having in the log too.
static void logPrintf(const char* fmt, ...)
{
    va_list ap;
    char    line[256];
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    fputs(line, stdout);
    if (g_log) {
        size_t n = strlen(line);
        while (n > 0 && line[n - 1] == '\n') line[--n] = '\0';
        logLine("%s", line);
    }
}

static void bootNote(const char* what) { snprintf(g_boot.note, sizeof(g_boot.note), "%s", what); }

// The screen's Callback sees everything; here it only records the last
// message so the status line has something to show. The real per-screen
// behaviour lives in gameflow.c for the boot screens.
static BScreenMessage g_lastMsg;

static void menuCallback(BMenu* m, BScreenMessage msg,
                         BScreenCallbackData* data, void* user)
{
    (void)m; (void)user;
    g_lastMsg = msg;
    // A menu item selected on a boot screen is what advances it -- the title
    // screen's MENUITEM_1 is how START reaches "New Main Menu" at all. The
    // item's own hash has to go with it: NewMainMenu routes on nothing else.
    if (msg == BMSG_MENUITEM_SELECT)
        bgf_menu_item_event(&g_flow, msg, data ? data->itemHash : 0, 0);
}

static void hookEnterScreen(void* user, const BScreenConfig* cfg)
{
    Boot* b = (Boot*)user;
    b->project    = NULL;
    b->screen     = uirender_find_screen(b->ui, cfg->hash, &b->project);
    b->screenHash = cfg->hash;
    b->hasMenu    = false;
    if (b->screen && b->project
        && bmenu_open(&b->menu, b->project, b->screen, menuCallback, NULL)
        && b->menu.numItems > 0) {
        bmenu_activate(&b->menu, 0);
        b->hasMenu = true;
    }
}

static void hookLeaveScreen(void* user, const BScreenConfig* cfg)
{
    Boot* b = (Boot*)user;
    (void)cfg;
    if (b->hasMenu) bmenu_unactivate(&b->menu);
    b->hasMenu = false;
    b->screen  = NULL;
    b->project = NULL;
}

static void hookSetScreenVisible(void* user, uint32_t screen, int visible)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    if (s) s->visible = visible != 0;
}

static void hookSetObjectVisible(void* user, uint32_t screen, uint32_t object,
                                 int visible)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    if (!s || !ui) return;
    int32_t idx = bui_find_object(ui, s, object, BUI_TYPE_NONE);
    if (idx < 0) return;
    // FlailerObjectVisibility, which is the opposite way round from the
    // screen enum: INVISIBLE is 0 and VISIBLE is 1. See gameflow.h.
    bui_set_object_visible(ui, (uint32_t)idx,
                           visible ? BUI_VISIBLE : BUI_INVISIBLE);
}

// TitleScreen's pMoviePlane (0x0016a1d0) is fixed to the 4:3 plane at
// construction and never re-fetched, so the texture a movie lands in is that
// object's textureHash -- SPLASH_SCREEN on this disc, 512x256 of opaque black
// on disc because it is a blit target and not art. Read it rather than
// hardcode it: the letterboxed plane happens to share it, and need not.
static uint32_t moviePlaneTexture(Boot* b)
{
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, BGF_SCREEN_TITLE, &ui);
    BUIObject  o;
    int32_t    idx;
    if (!s || !ui) return 0;
    idx = bui_find_object(ui, s, BGF_OBJ_MOVIE_PLANE_43, BUI_TYPE_BITMAP);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return 0;
    return o.textureHash;
}

static void hookMovieClose(void* user)
{
    Boot* b = (Boot*)user;
    if (!b->moviePlaying) return;
    logLine("movie close after %lu/%u frames",
            (unsigned long)b->movie.nextFrame, b->movie.info.frames);
    uirender_override_texture(b->ui, b->movieTexHash, NULL, 0, 0);
    m3v_tex_close(&b->movie, &b->movieTex);
    b->moviePlaying = false;
}

// The port plays the baked .M3V, not the .AVI -- MOVIES\INTRO\EALOGO_EN.AVI
// becomes MOVIES/INTRO/EALOGO_EN.M3V inside the data directory. A movie with
// no baked file answers 0, and gameflow.c treats that as a movie that has
// already finished rather than sitting on a MoviePlayer that never ends.
static int hookMovieOpen(void* user, const char* path)
{
    Boot* b = (Boot*)user;
    char  rel[GAMEDATA_MAX_PATH], full[GAMEDATA_MAX_PATH];

    hookMovieClose(user);
    if (!m3v_baked_path(path, rel, sizeof(rel))
        || !gamedata_path(rel, full, sizeof(full))
        || !m3v_tex_open(&b->movie, &b->movieTex, full)) {
        b->missingMovies++;
        bootNote("movie not baked");
        logLine("movie missing %s", path);
        return 0;
    }

    b->movieTexHash = moviePlaneTexture(b);
    uirender_override_texture(b->ui, b->movieTexHash, &b->movieTex,
                              b->movie.info.width, b->movie.info.height);
    b->moviePlaying = true;
    // gameflow.c already traces the full path; the status line just says it
    // is running, and bootNote's buffer is smaller than a path anyway.
    bootNote("movie playing");
    logLine("movie open %s %ux%u %u frames @ %u fps -> texture %08lx",
            rel, b->movie.info.width, b->movie.info.height,
            b->movie.info.frames, b->movie.info.fps,
            (unsigned long)b->movieTexHash);
    return 1;
}

// DriveMovie (0x0016a060) returns 1 when the movie is finished.
static int hookMovieDrive(void* user)
{
    Boot* b = (Boot*)user;
    if (!b->moviePlaying) return 1;
    return m3v_tex_drive(&b->movie, &b->movieTex, BOOT_DT) ? 1 : 0;
}

// The bundles are already resident by the time the flow starts, so loading
// is instantaneous. The names still go through so the trace is honest about
// what the original would have asked for.
static void hookLoadResource(void* user, const char* path)
{
    (void)user; (void)path;
}

static int hookResourcesReady(void* user) { (void)user; return 1; }

static void hookSetLanguage(void* user, int language)
{
    Boot* b = (Boot*)user;
    char  path[GAMEDATA_MAX_PATH];
    if (language < 0 || language >= NUM_LANGUAGES) return;
    if (!gamedata_path(kLanguages[language], path, sizeof(path))) return;
    uirender_set_language(b->ui, path);
}

// BootAutoLoader's memory card. There is none, so the job is already done --
// the screen keeps its shape (tick until the job finishes, then pop itself)
// and simply pops on its first tick.
static void hookSaveStart(void* user) { (void)user; }
static int  hookSavePoll(void* user)  { (void)user; return 1; }

static void hookTrace(void* user, const char* line)
{
    (void)user;
    printf("%s\n", line);
    logLine("flow %s", line);
}

// ---------------------------------------------------------------- 3DS glue

static void initPlatformPerf(void)
{
    bool isNew3DS = false;
    Result n3dsRes = APT_CheckNew3DS(&isNew3DS);
    if (R_SUCCEEDED(n3dsRes) && isNew3DS) {
        osSetSpeedupEnable(true);
    }
    APT_SetAppCpuTimeLimit(80);
}

static bool addBundle(UIRenderer* ui, const char* rel)
{
    char path[GAMEDATA_MAX_PATH];
    if (!gamedata_path(rel, path, sizeof(path))) return false;
    if (!uirender_add_bundle(ui, path)) {
        logPrintf("  missing %s\n", rel);
        return false;
    }
    return true;
}

static const char* messageName(BScreenMessage msg)
{
    switch (msg) {
        case BMSG_NONE:                 return "-";
        case BMSG_MENUITEM_SELECT:      return "SELECT";
        case BMSG_MENUITEM_ACTIVATE:    return "ACTIVATE";
        case BMSG_MENUITEM_UNACTIVATE:  return "UNACTIVATE";
        case BMSG_MENUITEM_HIGHLIGHT:   return "HIGHLIGHT";
        case BMSG_MENUITEM_UNHIGHLIGHT: return "UNHIGHLIGHT";
        case BMSG_MENUITEM_PAD_LEFT:    return "PAD_LEFT";
        case BMSG_MENUITEM_PAD_RIGHT:   return "PAD_RIGHT";
        case BMSG_MENUITEM_PAD_UP:      return "PAD_UP";
        case BMSG_MENUITEM_PAD_DOWN:    return "PAD_DOWN";
        case BMSG_MENUITEM_SQUARE:      return "SQUARE";
        case BMSG_SCREEN_START_BUTTON:  return "START_BUTTON";
        case BMSG_SCREEN_L1:            return "L1";
        case BMSG_SCREEN_R1:            return "R1";
        default:                        return "?";
    }
}

static const struct { u32 key; BJoyEvent ev; } kBinds[] = {
    { KEY_DUP,    BJOY_SCROLL_UP },
    { KEY_DDOWN,  BJOY_SCROLL_DOWN },
    { KEY_DLEFT,  BJOY_SCROLL_LEFT },
    { KEY_DRIGHT, BJOY_SCROLL_RIGHT },
    { KEY_A,      BJOY_MENU_SELECT },
    { KEY_Y,      BJOY_MENU_SQUARE },
};
#define NUM_BINDS ((int)(sizeof(kBinds) / sizeof(kBinds[0])))

static void waitForExit(void)
{
    printf("\nPress START to exit.\n");
    while (aptMainLoop()) {
        hidScanInput();
        if (hidKeysDown() & KEY_START) break;
        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }
}

int main(int argc, char** argv)
{
    (void)argc; (void)argv;

    gfxInitDefault();
    consoleInit(GFX_BOTTOM, NULL);
    initPlatformPerf();
    logOpen();

    logPrintf("NFSHP2-3DS -- boot flow\n");
    logPrintf("Heap: asked=%luKB got=%luKB linear=%luKB\n",
              (unsigned long)(g_heapInfo.heapAsked / 1024),
              (unsigned long)(g_heapInfo.heapGot / 1024),
              (unsigned long)(g_heapInfo.linearGot / 1024));

    if (!gamedata_init()) {
        printf("\nNo game data found.\n");
        printf("Put the extracted disc on the SD card at\n");
        printf("  sdmc:/3ds/NFSHP2-3DS/data\n");
        printf("or name the directory in %s.\n", GAMEDATA_CONFIG);
        printf("It must contain %s.\n", GAMEDATA_SENTINEL);
        waitForExit();
        gfxExit();
        return 1;
    }
    logPrintf("Data: %s\n", gamedata_root());

    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    C3D_RenderTarget* top = C2D_CreateScreenTarget(GFX_TOP, GFX_LEFT);

    static UIRenderer ui;
    uirender_init(&ui, 400.0f, 240.0f);
    addBundle(&ui, BUNDLE_FRONTEND);
    addBundle(&ui, BUNDLE_GLOBAL);
    addBundle(&ui, BUNDLE_INGAME);

    int language = 0;

    uint32_t screenCount = uirender_screen_count(&ui);
    logPrintf("%lu screens, %d fonts loaded\n",
              (unsigned long)screenCount, ui.numFonts);
    if (screenCount == 0) {
        printf("\nNo Flailer project in the bundles.\n");
        waitForExit();
        C2D_Fini();
        C3D_Fini();
        gfxExit();
        return 1;
    }

    memset(&g_boot, 0, sizeof(g_boot));
    g_boot.ui = &ui;
    bootNote("booting");

    BGameFlowHooks hooks;
    memset(&hooks, 0, sizeof(hooks));
    hooks.user             = &g_boot;
    hooks.setScreenVisible = hookSetScreenVisible;
    hooks.setObjectVisible = hookSetObjectVisible;
    hooks.enterScreen      = hookEnterScreen;
    hooks.leaveScreen      = hookLeaveScreen;
    hooks.movieOpen        = hookMovieOpen;
    hooks.movieDrive       = hookMovieDrive;
    hooks.movieClose       = hookMovieClose;
    hooks.loadResource     = hookLoadResource;
    hooks.resourcesReady   = hookResourcesReady;
    hooks.setLanguage      = hookSetLanguage;
    hooks.saveStart        = hookSaveStart;
    hooks.savePoll         = hookSavePoll;
    hooks.trace            = hookTrace;

    bgf_init(&g_flow, kGameFlowStages, BGF_NUM_STATES,
             kScreens, NUM_SCREENS, kBootStages, NUM_BOOT_STAGES, &hooks);

    // main (0x0012da88): SkipFE ships as 0, so LoadLanguageInfo and then
    // ChangeGameFlow(LOADING_FRONTEND). MainLoop takes it from there.
    bgf_change_state(&g_flow, BGF_LOADING_FRONTEND, BGF_NONE);

    printf("\nD-pad: menu  A: select  START: start  B: back\n");
    printf("SELECT: screen viewer\n");
    // The marker tools/run_azahar_test.ps1 greps for: past this line the
    // bundles are resident, the flow is running and frames are being drawn.
    logLine("entering main loop");

    bool     viewer  = false;
    uint32_t vIndex  = 0;
    uint32_t vShown  = 0xffffffffu;
    BUI*     vProj   = NULL;
    BUIScreen* vScr  = NULL;
    static BMenu vMenu;
    bool     vHasMenu = false;
    int      redraw   = 1;
    u32      clear    = C2D_Color32(0x10, 0x10, 0x18, 0xFF);

    while (aptMainLoop()) {
        hidScanInput();
        u32 kDown = hidKeysDown();

        if (kDown & KEY_SELECT) {
            viewer = !viewer;
            if (!viewer && vHasMenu) { bmenu_unactivate(&vMenu); vHasMenu = false; }
            vShown = 0xffffffffu;
            redraw = 1;
        }

        if (!viewer) {
            // ---- the boot flow
            if (kDown & KEY_START) {
                bgf_screen_event(&g_flow, BMSG_SCREEN_START_BUTTON, 0);
                redraw = 1;
            }
            if (kDown & KEY_B) {
                bgf_move_back_screen(&g_flow, 1);
                redraw = 1;
            }
            if (g_boot.hasMenu) {
                for (int i = 0; i < NUM_BINDS; i++) {
                    if (!(kDown & kBinds[i].key)) continue;
                    bmenu_joy(&g_boot.menu, 0, kBinds[i].ev, true);
                    redraw = 1;
                }
            }

            // MainLoop: one pass of the flow per frame. The display is
            // vsynced below, so the timestep is a frame.
            bgf_frame(&g_flow, BOOT_DT);

            if (redraw) {
                redraw = 0;
                const BMenuItem* item =
                    g_boot.hasMenu ? bmenu_current(&g_boot.menu) : NULL;
                printf("\x1b[s\x1b[16;1H");
                printf("state %-20s          \n",
                       bgf_state_name(&g_flow, g_flow.current));
                printf("screen %-24s %08lx\n",
                       g_flow.screen ? g_flow.screen->name : "-",
                       (unsigned long)g_boot.screenHash);
                printf("stack %d  menu %2d items, on MENUITEM_%-2d   \n",
                       g_flow.stack.index,
                       g_boot.hasMenu ? g_boot.menu.numItems : 0,
                       item ? (int)item->itemID : -1);
                printf("last %-12s  clock %lu/%lu       \n",
                       messageName(g_lastMsg),
                       (unsigned long)g_flow.realTime,
                       (unsigned long)g_flow.realTimer);
                printf("%-40s\n", g_boot.note);
                printf("\x1b[u");
            }

            C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
            C2D_TargetClear(top, clear);
            C2D_SceneBegin(top);
            if (g_boot.screen && g_boot.project)
                uirender_draw_screen(&ui, g_boot.project, g_boot.screen, 1.0f);
            C3D_FrameEnd(0);
            continue;
        }

        // ---- the screen viewer
        if (kDown & KEY_START) break;
        if (kDown & KEY_R) vIndex = (vIndex + 1) % screenCount;
        if (kDown & KEY_L) vIndex = (vIndex + screenCount - 1) % screenCount;
        if (kDown & KEY_X) {
            language = (language + 1) % NUM_LANGUAGES;
            hookSetLanguage(&g_boot, language);
            redraw = 1;
        }

        if (vIndex != vShown) {
            if (vHasMenu) bmenu_unactivate(&vMenu);
            vHasMenu = false;
            vShown   = vIndex;
            vScr     = uirender_screen_at(&ui, vIndex, &vProj);
            redraw   = 1;
        }
        if (!vHasMenu && vScr && vProj) {
            g_lastMsg = BMSG_NONE;
            if (bmenu_open(&vMenu, vProj, vScr, menuCallback, NULL)
                && vMenu.numItems > 0) {
                bmenu_activate(&vMenu, 0);
                vHasMenu = true;
                redraw   = 1;
            }
        }
        if (vHasMenu) {
            for (int i = 0; i < NUM_BINDS; i++) {
                if (!(kDown & kBinds[i].key)) continue;
                bmenu_joy(&vMenu, 0, kBinds[i].ev, true);
                redraw = 1;
            }
        }

        if (redraw) {
            redraw = 0;
            const BMenuItem* item = vHasMenu ? bmenu_current(&vMenu) : NULL;
            printf("\x1b[s\x1b[16;1H");
            printf("viewer %3lu/%lu  hash %08lx  %lu objects   \n",
                   (unsigned long)(vIndex + 1), (unsigned long)screenCount,
                   (unsigned long)(vScr ? vScr->nameHash : 0),
                   (unsigned long)(vScr ? vScr->count : 0));
            printf("lang %-24s\n", kLanguages[language] + 10);
            printf("menu %2d items, on MENUITEM_%-2d        \n",
                   vHasMenu ? vMenu.numItems : 0,
                   item ? (int)item->itemID : -1);
            printf("last %-12s                       \n",
                   messageName(g_lastMsg));
            printf("textures %d cached, %d missing; fonts %d missing \n",
                   ui.numTextures, ui.missingTextures, ui.missingFonts);
            printf("\x1b[u");
        }

        C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
        C2D_TargetClear(top, clear);
        C2D_SceneBegin(top);
        uirender_draw_screen(&ui, vProj, vScr, 1.0f);
        C3D_FrameEnd(0);
    }

    // Leaving here rather than crashing looks identical from outside the
    // emulator, so say so, and carry the texture-cache tally out with it --
    // a screen that renders but is missing half its art shows up here as a
    // non-zero "missing" long before anyone squints at a screenshot.
    logLine("left main loop: %d textures cached, %d missing, %d fonts missing",
            ui.numTextures, ui.missingTextures, ui.missingFonts);

    if (vHasMenu) bmenu_unactivate(&vMenu);
    if (g_boot.hasMenu) bmenu_unactivate(&g_boot.menu);
    uirender_free(&ui);
    C2D_Fini();
    C3D_Fini();
    gfxExit();
    return 0;
}
