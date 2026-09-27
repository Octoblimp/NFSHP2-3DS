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
// Controls. SELECT cycles three modes: the boot flow, the screen viewer and
// the geometry viewer.
//   boot flow:       D-pad navigates, A selects, START is the game's start
//                    button, B goes back.
//   screen viewer:   L/R change screen, D-pad navigates, X cycles language,
//                    START exits.
//   geometry viewer: L/R change car, D-pad left/right change solid, D-pad
//                    up/down zoom, circle pad orbits, A draws every solid,
//                    X drops the textures, Y stops the spin, B recentres,
//                    START exits. See source/geoview.c.

#include <3ds.h>
#include <citro2d.h>
#include <citro3d.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bmenu.h"
#include "bsnd.h"
#include "bslotpool.h"
#include "bscreens.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "collision.h"
#include "collisionbody.h"
#include "emath.h"
#include "emodel.h"
#include "esolid.h"
#include "eview.h"
#include "gamedata.h"
#include "fesound.h"
#include "gameflow.h"
#include "heapcfg.h"
#include "geoview.h"
#include "georender.h"
#include "joyevent.h"
#include "joyhid.h"
#include "joypad.h"
#include "movie.h"
#include "mellowmover.h"
#include "physcomp.h"
#include "physicscar.h"
#include "physicssystem.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "realtime.h"
#include "sinit.h"
#include "terraintype.h"
#include "topology.h"
#include "track.h"
#include "trackflow.h"
#include "trackview.h"
#include "uirender.h"
#include "wheel.h"
#include "world.h"

// The top screen's render target is built here rather than by
// C2D_CreateScreenTarget, which asks C3D_RenderTargetCreate for no depth
// buffer at all. 2D does not need one; geoview.c does, and a depth test
// against a target that has no depth buffer silently does nothing. These are
// citro2d's own transfer flags, which is what makes the target still usable
// for C2D_SceneBegin.
static const u32 kDisplayTransferFlags =
    GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(0)
    | GX_TRANSFER_RAW_COPY(0)
    | GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGBA8)
    | GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB8)
    | GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO);

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
    // The three the main menu leads to, ported in bscreens.c. Their
    // callbacks find their state through the module instance bscr_init()
    // installs, so that call has to have happened before the flow gets
    // here; main() makes it next to bgf_init().
    { "Cops On Mode Select",     BSCR_SCREEN_COPS_ON_MODE_SELECT,
      bscr_cops_on_callback },
    { "Cops Off Mode Select",    BSCR_SCREEN_COPS_OFF_MODE_SELECT,
      bscr_cops_off_callback },
    { "Options",                 BSCR_SCREEN_OPTIONS,
      bscr_options_callback },

    // Registered, drawn, and not ported. Every name below is one the port's
    // own code can ChangeToScreen() to -- the two Mode Selects' item tables
    // and the seven Options pages, bscreens.c:334 and :554 -- and every one
    // of their screen chunks is in FRONTB.BUN, which is already loaded. An
    // unregistered name is worse than a dead one: ChangeToScreen clears
    // pCurrent before it looks the name up, so the flow ends with no screen
    // at all and the top screen goes black until BACK. That is what "flow
    // unregistered ChallengeBeACop" looked like.
    //
    // So they draw, the menu is navigable and BACK works, and A does
    // nothing because the class named in each comment -- the one the ELF's
    // own FlailerScreenConfigList points at -- is still to be written. The
    // hashes are the ELF's; `python tools/screen_registry.py --check-port`
    // checks every row of this table against it and lists what is left.
    { "Challenge",               0x2d62cfe2u,   // ChallengeScreenCallback
      bgf_plain_screen_callback },
    { "ChallengeBeACop",         0xe55f1297u,   // BeACopChallengeSetup
      bgf_plain_screen_callback },
    { "View Event Tree",         0x147f8a59u,   // tEventTreeView
      bgf_plain_screen_callback },
    { "Audio Options",           0xe116761cu,   // AudioOptionsScreen
      bgf_plain_screen_callback },
    { "Joystick PreConfig",      0x8bd5060bu,   // JoystickPreConfig
      bgf_plain_screen_callback },
    { "Display Options",         0x8bc68340u,   // tDisplayOptionsScreen
      bgf_plain_screen_callback },
    { "Phils Load Save",         0x9829bfabu,   // LoadSaveWrapper
      bgf_plain_screen_callback },
    { "NameEntry",               0x617a4e0au,   // NameEntry
      bgf_plain_screen_callback },
    { "Credits",                 0xfd8a3b6du,   // CreditsScreen
      bgf_plain_screen_callback },
    // Same Flailer screen as "Language Options Pre FE" above, entered under
    // a second name from the Options menu. The ELF registers both.
    { "Language Options",        0x632b068eu,   // LanguageOptionsScreenBase
      bgf_plain_screen_callback },
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
static BScreens g_uiScreens;

// The geometry viewer's state. Static rather than automatic because it
// carries a mesh and a texture table per solid and is about 100 KB; main's
// stack is not the place for it.
static GeoView g_geo;

// The track viewer's, for the same reason: the cull info alone is 2 KB, and
// the texture packs' indexes ride along.
static TrackView g_track;

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

// bSlotPool's printf hook is handed a PrintAllSlotPools row in up to six
// pieces and only the last of them ends the line, so this buffers until a
// newline arrives. logPrintf ends a line per call, which would otherwise
// split one row across six lines of the log.
static char     g_slotLog[192];
static unsigned g_slotLogLen;

static void slotPoolLog(const char* text)
{
    while (*text) {
        char c = *text++;

        if (c == '\n' || g_slotLogLen == sizeof g_slotLog - 1) {
            g_slotLog[g_slotLogLen] = 0;
            logPrintf("%s\n", g_slotLog);
            g_slotLogLen = 0;
            if (c != '\n') {
                g_slotLog[g_slotLogLen++] = c;
            }
        } else {
            g_slotLog[g_slotLogLen++] = c;
        }
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
    // FlailerMenu hands the screen's own Callback the block it is holding --
    // item hash, port, and the two reply fields -- and reads Noise back
    // afterwards. Passing it straight down is what makes the screens in
    // bscreens.c work: HIGHLIGHT is how the blurb and the brackets move, and
    // an exit animation clears Param on PAD_UP/PAD_DOWN to freeze the
    // selection while the items slide away. A fresh block, which is what
    // this used to build, threw all of that away and forwarded SELECT only.
    if (data) bgf_send(&g_flow, msg, data);
}

// The screen viewer's menu. It browses every screen in every bundle,
// including screens the flow is not on and screens with no behaviour at all,
// so it must not reach the flow: forwarding from here would send one screen's
// MENUITEM_2 to whichever screen the game is actually standing on.
static void viewerCallback(BMenu* m, BScreenMessage msg,
                           BScreenCallbackData* data, void* user)
{
    (void)m; (void)data; (void)user;
    g_lastMsg = msg;
}

// The one driver, as the disc had one bSound. It outlives every screen
// because the banks do: a .SBK loaded for the frontend is still the frontend's
// when a screen comes back.
static BsndDriver gSnd;

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
        b->menu.sound = fesound_play;      // MakeFrontendSound
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
    logLine("flow %s", line);
}

// ------------------------------------------------- the frontend screens
//
// BScreensHooks: everything Cops On / Cops Off / Options do outside their
// own state. All of it works on the screen whose hash the caller passes,
// which is always the screen the flow has entered -- the originals pass
// their own hash too.

static void hookGrayMenuItem(void* user, uint32_t screen, uint32_t item,
                             BScrGrayMode mode)
{
    Boot* b = (Boot*)user;
    if (!b->hasMenu || !b->project || screen != b->screenHash) return;
    for (int i = 0; i < b->menu.numItems; i++) {
        const BMenuItem* mi = &b->menu.items[i];
        if (mi->itemHash != item) continue;
        // GrayMenuItem (0x00168498): mode 1 enables, 0 and 2 disable, and
        // only 1 and 2 touch the object. Mode 0 is the one that leaves the
        // item on screen, drawn in the grayed colour.
        bmenu_set_item_enabled(&b->menu, mi->itemID,
                               mode == BSCR_GRAY_ENABLE);
        if (mode != BSCR_GRAY_DISABLE)
            bui_set_object_visible(b->project, mi->object,
                                   mode == BSCR_GRAY_ENABLE ? BUI_VISIBLE
                                                            : BUI_INVISIBLE);
        logLine("gray item=%08lx mode=%d", (unsigned long)item, (int)mode);
        return;
    }
}

// tAnimatedBlurb::NewText (0x00232ef0). The blurb is one text object per
// screen and the sentence is a row of the language table, so changing it is
// changing the object's LanguageID -- the renderer looks the row up every
// frame, exactly as it does for a label.
static void hookSetBlurb(void* user, uint32_t screen, int blurbId)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    int32_t    idx;
    if (!s || !ui) return;
    idx = bui_find_object(ui, s, BSCR_OBJ_SCROLLING_TEXT, BUI_TYPE_TEXT);
    if (idx < 0) return;
    bui_set_text_language(ui, (uint32_t)idx, (uint32_t)blurbId);
}

// SetupHighlight's other half: FlailerGetBoundingBox on the current item's
// MI_n_MASK, then the two brackets to its edges. Only Y moves -- both
// brackets keep the X they were authored at, which is why they span the
// whole panel however short the label is.
static void hookMoveBrackets(void* user, uint32_t screen, uint32_t mask,
                             float under, float over)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    BUIObject  o;
    float      box[4];
    int32_t    maskIdx, idx;

    // SetCurrentItem(0) happens on an out-of-range highlight, and the
    // bounding box of nothing is not something to go looking for.
    if (!s || !ui || !mask) return;
    maskIdx = bui_find_object(ui, s, mask, BUI_TYPE_BITMAP);
    if (maskIdx < 0) return;
    if (!uirender_object_bounds(b->ui, ui, (uint32_t)maskIdx, box)) return;

    idx = bui_find_object(ui, s, BSCR_OBJ_MI_UNDERSCORE, BUI_TYPE_NONE);
    if (idx >= 0 && bui_object(ui, (uint32_t)idx, &o))
        bui_set_object_pos(ui, (uint32_t)idx, o.x, box[3] + under);
    idx = bui_find_object(ui, s, BSCR_OBJ_MI_OVERSCORE, BUI_TYPE_NONE);
    if (idx >= 0 && bui_object(ui, (uint32_t)idx, &o))
        bui_set_object_pos(ui, (uint32_t)idx, o.x, box[1] + over);
}

// ------------------------------------------- the frontend animation layer
//
// BAnimHooks: what banim.c needs from the Flailer, which is the object
// layer and nothing else. Every one of these resolves the screen hash
// first, because the animations outlive the screen they were built for --
// a slide-out is still ticking while the flow has already left.

static BUIScreen* animScreen(Boot* b, uint32_t screen, BUI** outUI)
{
    *outUI = NULL;
    return uirender_find_screen(b->ui, screen, outUI);
}

// Resolves screen + object name to an index, or -1. `type` follows the
// FindFlailerObject rule: 0 matches anything. BANIM_TYPE_TEXT/BITMAP are
// the BUI_TYPE_ values, so they pass straight through.
static int32_t animFind(Boot* b, uint32_t screen, uint32_t object, int type,
                        BUI** outUI)
{
    BUIScreen* s = animScreen(b, screen, outUI);
    if (!s || !*outUI) return -1;
    return bui_find_object(*outUI, s, object, type);
}

static int hookAnimObjectExists(void* user, uint32_t screen, uint32_t object,
                                int type)
{
    BUI* ui;
    return animFind((Boot*)user, screen, object, type, &ui) >= 0;
}

static int hookAnimGroupExists(void* user, uint32_t screen, uint32_t group,
                               int type)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = animScreen(b, screen, &ui);
    if (!s || !ui) return 0;
    return bui_next_in_group(ui, s, group, type, -1) >= 0;
}

static int hookAnimObjectType(void* user, uint32_t screen, uint32_t object)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return BUI_TYPE_NONE;
    return o.type;
}

static void hookAnimGetTopLeft(void* user, uint32_t screen, uint32_t object,
                               float* x, float* y)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    *x = 0.0f;
    *y = 0.0f;
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    *x = o.x;
    *y = o.y;
}

static void hookAnimSetTopLeft(void* user, uint32_t screen, uint32_t object,
                               float x, float y)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx >= 0) bui_set_object_pos(ui, (uint32_t)idx, x, y);
}

// FlailerSetGroupPosition (0x00142f60): the delta that would put `master`
// at (x, y), applied to every object carrying `group`. The master moves
// only if it is itself in the group -- MENUITEM_n_MASK is, which is why
// the slides can drive a whole row from one object's position.
static void hookAnimSetGroupPos(void* user, uint32_t screen, uint32_t group,
                                uint32_t master, float x, float y)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = animScreen(b, screen, &ui);
    BUIObject  o;
    float      dx, dy;
    int32_t    idx;

    if (!s || !ui) return;
    idx = bui_find_object(ui, s, master, BUI_TYPE_NONE);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    dx = x - o.x;
    dy = y - o.y;

    for (idx = bui_next_in_group(ui, s, group, BUI_TYPE_NONE, -1); idx >= 0;
         idx = bui_next_in_group(ui, s, group, BUI_TYPE_NONE, idx)) {
        if (!bui_object(ui, (uint32_t)idx, &o)) continue;
        bui_set_object_pos(ui, (uint32_t)idx, o.x + dx, o.y + dy);
    }
}

static void hookAnimSetVisible(void* user, uint32_t screen, uint32_t object,
                               int visible)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx >= 0)
        bui_set_object_visible(ui, (uint32_t)idx,
                               visible ? BUI_VISIBLE : BUI_INVISIBLE);
}

static int hookAnimGetAlpha(void* user, uint32_t screen, uint32_t object,
                            int corner)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    int     a;
    if (idx < 0) return 0;
    a = bui_get_object_alpha(ui, (uint32_t)idx, corner);
    return a < 0 ? 0 : a;
}

static void hookAnimSetAlpha(void* user, uint32_t screen, uint32_t object,
                             int corner, int alpha)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx >= 0) bui_set_object_alpha(ui, (uint32_t)idx, corner, alpha);
}

static void hookAnimSetLanguageID(void* user, uint32_t screen,
                                  uint32_t object, int languageID)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_TEXT, &ui);
    if (idx >= 0)
        bui_set_text_language(ui, (uint32_t)idx, (uint32_t)languageID);
}

static void hookAnimPrintText(void* user, uint32_t screen, uint32_t object,
                              const char* str)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_TEXT, &ui);
    if (idx >= 0) bui_set_text_string(ui, (uint32_t)idx, str);
}

// CopyFlailerText (0x0013ec18): src's *drawn* string into dst, which means
// resolving src's LanguageID first -- the bloom is a copy of a menu label
// and a menu label is a language row. dst then goes onto its own inline
// string, or the table would keep winning and the copy never show.
static void hookAnimCopyText(void* user, uint32_t screen, uint32_t dst,
                             uint32_t src)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = animScreen(b, screen, &ui);
    BUIObject  o;
    char       text[128];
    int32_t    si, di;
    size_t     n = 0;

    if (!s || !ui) return;
    si = bui_find_object(ui, s, src, BUI_TYPE_TEXT);
    di = bui_find_object(ui, s, dst, BUI_TYPE_TEXT);
    if (si < 0 || di < 0 || !bui_object(ui, (uint32_t)si, &o)) return;

    if (o.languageID && b->ui->hasLang)
        n = langtab_copy(&b->ui->lang, (int32_t)o.languageID, text,
                         sizeof(text));
    if (n == 0) {
        while (n + 1 < sizeof(text) && n < o.maxChars && o.string[n]) {
            text[n] = o.string[n];
            n++;
        }
        text[n] = 0;
    }
    bui_set_text_language(ui, (uint32_t)di, 0);
    bui_set_text_string(ui, (uint32_t)di, text);
}

// FlailerTextChunk::ScaleAboutCenter (0x0013eb20). The scale is written
// last; before it, X and Y are nudged by the half-extent the change costs,
// so the glyphs grow out of the centre rather than off the anchor. Which
// coordinate moves depends on the justification, and the untagged case --
// no LEFT, CENTER or RIGHT bit -- moves neither.
static void hookAnimScaleAboutCenter(void* user, uint32_t screen,
                                     uint32_t object, float scale)
{
    Boot*     b  = (Boot*)user;
    BUI*      ui = NULL;
    BUIObject o;
    float     w = 0.0f, h = 0.0f, halfW, halfH, x, y;
    int32_t   idx = animFind(b, screen, object, BUI_TYPE_TEXT, &ui);

    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    if (o.scaleX == 0.0f || o.scaleY == 0.0f) return;
    uirender_text_extent(b->ui, ui, (uint32_t)idx, &w, &h);
    halfW = w / (o.scaleX + o.scaleX);
    halfH = h / (o.scaleY + o.scaleY);
    x = o.x;
    y = o.y;

    if (o.format & BUI_FMT_LEFT) {
        y += halfH * (o.scaleY - scale);
        x += halfW * (o.scaleX - scale);
    } else if (o.format & BUI_FMT_CENTER) {
        y += halfH * (o.scaleY - scale);
    } else if (o.format & BUI_FMT_RIGHT) {
        float d = o.scaleX - scale;
        y += halfH * d;
        x -= halfW * d;
    }
    bui_set_object_pos(ui, (uint32_t)idx, x, y);
    bui_set_object_scale(ui, (uint32_t)idx, scale, scale);
}

static void hookAnimSetColor(void* user, uint32_t screen, uint32_t object,
                             uint32_t color)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_TEXT, &ui);
    if (idx >= 0) bui_set_text_color(ui, (uint32_t)idx, color);
}

// FlailerGetScale (0x00142138) reads the authored pair back. A missing
// object answers (1, 1): the highlight multiplies by it, and 0 would make
// every bloom on a screen that has not loaded collapse to nothing.
static void hookAnimGetScale(void* user, uint32_t screen, uint32_t object,
                             float* sx, float* sy)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    *sx = 1.0f;
    *sy = 1.0f;
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    *sx = o.scaleX;
    *sy = o.scaleY;
}

// GetTranslatedString (0x0020b0e0). The caller copies out of this before
// the next call, exactly as the original's shared buffer requires.
static const char* hookAnimTranslate(void* user, int languageID)
{
    Boot*       b = (Boot*)user;
    static char text[BBLURB_MAX_TEXT];
    if (!b->ui->hasLang) return NULL;
    if (langtab_copy(&b->ui->lang, (int32_t)languageID, text,
                     sizeof(text)) == 0)
        return NULL;
    return text;
}

// FlailerScreenList::StartMovie. These are the panel movies that loop
// behind the menu, blitted into the PANELMOVIE texture all three screens
// share -- and not one of the three files is on the disc, so there is
// nothing to open. Logged rather than counted: unlike the title movie, a
// missing one here is the normal case and not a packaging mistake.
static void hookScreenMovie(void* user, const char* path)
{
    (void)user;
    logLine("panel movie %s (not on disc)", path);
}

static void hookScreenMovieStop(void* user) { (void)user; }

static void hookJukebox(void* user, int start)
{
    (void)user;
    logLine("jukebox %s", start ? "start" : "stop");
}

static void hookDisplayOptionsStart(void* user)
{
    (void)user;
    logLine("display options snapshot");
}

// StartQuickRace's parameter block arrives complete; what it feeds -- the
// track database and the race itself -- is Phase 4. Print it, so the one
// thing the frontend produces is visible before there is anywhere to put it.
static void hookStartQuickRace(void* user, const BQuickRace* p)
{
    (void)user;
    bootNote("quick race");
    logLine("quickrace track=%d laps=%d ai=%d start=%d maxcops=%d "
            "tickets=%d boost=%d gearbox=%s",
            p->trackNumber, p->numLapsInRace, p->numAICars,
            p->playerStartPosition, p->maxCops, p->ticketsBeforeArrest,
            p->boost, p->transmissionType ? "manual" : "automatic");
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

static UIBundle* addBundle(UIRenderer* ui, const char* rel)
{
    char path[GAMEDATA_MAX_PATH];
    if (!gamedata_path(rel, path, sizeof(path))) return NULL;
    if (!uirender_add_bundle(ui, path)) {
        logPrintf("  missing %s\n", rel);
        return NULL;
    }
    return &ui->bundles[ui->numBundles - 1];
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

// The only console the port ever puts up, and only on the way out. There
// used to be one on the bottom screen for the whole run; that screen is the
// blurb panel's now, and the two cannot share it -- consoleInit switches
// the bottom screen to RGB565 while citro3d presents BGR8 into the same
// framebuffer, which came out as two half-width copies of the panel under a
// teal dither. So: no console, the log file takes everything (it is opened
// "w", so each boot replaces it), and a failure that has to be readable
// without a card reader gets one on the TOP screen, where nothing else is
// drawing yet.
static void fatalConsole(void)
{
    consoleInit(GFX_TOP, NULL);
}

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

// --------------------------------------------------------- the bottom screen
//
// The disc drew the one-line description -- the "blurb" -- inside the menu
// screen itself, along the bottom of a 640x480 frame. Squeezed onto the 3DS
// top screen that line comes out about five pixels tall and is not reading
// material, so the port takes it off the top screen altogether
// (uirender_hide_object, below) and gives it this whole screen: wrapped,
// and at a size meant for 320x240.
//
// None of this is a port of anything. The PS2 had one screen, so there is
// no original here to be accurate to -- only the game's own font, its red,
// and the line it was trying to show the player.

#define BOT_W     320.0f
#define BOT_H     240.0f
#define BOT_PAD    16.0f
#define BOT_HDR    30.0f     // the header strip, and where the accent sits
#define BOT_FOOT  204.0f     // the rule above the controls line

// citro2d packs a colour r | g<<8 | b<<16 | a<<24, and C2D_Color32 is an
// inline function rather than a macro, so a constant has to pack its own.
#define RGBA8(r, g, b, a) \
    ((u32)(r) | ((u32)(g) << 8) | ((u32)(b) << 16) | ((u32)(a) << 24))

#define BOT_BACK   RGBA8(0x0b, 0x0d, 0x12, 0xff)
#define BOT_HEAD   RGBA8(0x16, 0x1a, 0x23, 0xff)
#define BOT_ACCENT RGBA8(0xc4, 0x1e, 0x24, 0xff)   // the frontend's own red
#define BOT_RULE   RGBA8(0x2b, 0x33, 0x40, 0xff)
#define BOT_TEXT   RGBA8(0xec, 0xef, 0xf4, 0xff)
#define BOT_DIM    RGBA8(0x78, 0x85, 0x99, 0xff)

static C3D_RenderTarget* g_bot;
static uint32_t          g_botFont;   // FONT_A, 357 of the disc's text objects

// A style at a chosen line height in pixels. A font's own height is
// whatever its glyph sheet was authored at, which is not 19 px for any font
// on the disc, so it is asked for and divided out rather than assumed. A
// font that is not loaded measures 0 and the scale is left alone -- nothing
// will draw anyway.
static UIWrapStyle botStyle(UIRenderer* ui, uint32_t color, float px,
                            bool center)
{
    UIWrapStyle st;
    float       h;

    st.fontHash = g_botFont;
    st.color    = color;
    st.scale    = 1.0f;
    st.lineGap  = 0.0f;
    st.center   = center;
    h = uirender_line_height(ui, &st);
    if (h > 0.0f) st.scale = px / h;
    return st;
}

// The bring-up overlays that used to be printf'd to the console on the
// bottom screen. They go to the log now -- and only when the line actually
// changes, because at the emulator's 140 FPS a line a frame is a megabyte a
// minute of the same text. One slot per line of the old overlay, so two
// lines that alternate do not each count as a change of the other.
#define DEV_SLOTS 12

static void devLog(int slot, const char* fmt, ...)
{
    static char last[DEV_SLOTS][192];
    char        line[192];
    va_list     ap;

    if (slot < 0 || slot >= DEV_SLOTS) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (strcmp(line, last[slot]) == 0) return;
    memcpy(last[slot], line, sizeof last[slot]);
    logLine("%s", line);
}

// What the panel is drawing, and how far through a change it is. When the
// screen's line differs from this one the panel dips to nothing, swaps and
// comes back -- the port's stand-in for tAnimatedBlurb's whiteout wipe
// (banim.c:620), which animates an object that is no longer on screen.
#define BLURB_MAX 256
static char  g_blurbShown[BLURB_MAX];
static float g_blurbFade = 1.0f;

// Every screen in FRONTB.BUN ships the same authoring placeholder in
// SCROLLING_TEXT and a screen whose blurb has not been set yet still has
// it. Drawing that would be drawing a note to the artist.
static const char kBlurbPlaceholder[] = "This text will scroll sideways";

// A screen registered to bgf_plain_screen_callback draws and answers the
// D-pad and nothing else, and it has no blurb object, so the panel would
// sit empty under its name and look like a bug. It says what it is instead.
// No apostrophe: FONT_A drops a glyph it has not got, silently.
static const char kPlainScreenNote[] =
    "This screen is drawn from the disc. The class behind it is not ported "
    "yet, so the highlight moves and B is the way out.";

// The line the top screen would be drawing this frame. It is read out of
// the object rather than remembered from the setBlurb hook because the hook
// is not the only thing that writes it: tAnimatedBlurb resolves the
// translation itself and prints the result into the object at the end of
// its wipe, so the object is the one place the current line exists.
static void liveBlurb(Boot* b, char* out, size_t cap)
{
    const char* s;
    size_t      len = 0;
    int32_t     idx;

    out[0] = '\0';
    if (!b->screen || !b->project) return;
    idx = bui_find_object(b->project, b->screen, BSCR_OBJ_SCROLLING_TEXT,
                          BUI_TYPE_TEXT);
    if (idx < 0) return;
    s = uirender_object_string(b->ui, b->project, (uint32_t)idx, &len);
    if (!s || len == 0) return;
    if (len >= sizeof kBlurbPlaceholder - 1
        && memcmp(s, kBlurbPlaceholder, sizeof kBlurbPlaceholder - 1) == 0)
        return;
    // Not a C string: the language table hands back a pointer and a length,
    // and an inline placeholder can fill MaxChars with no terminator.
    if (len > cap - 1) len = cap - 1;
    memcpy(out, s, len);
    out[len] = '\0';
}

static void updateBlurb(Boot* b, float dt)
{
    char live[BLURB_MAX];

    liveBlurb(b, live, sizeof live);
    if (strcmp(live, g_blurbShown) != 0) {
        g_blurbFade -= dt / 0.10f;
        if (g_blurbFade <= 0.0f) {
            g_blurbFade = 0.0f;
            memcpy(g_blurbShown, live, sizeof g_blurbShown);
        }
    } else if (g_blurbFade < 1.0f) {
        g_blurbFade += dt / 0.20f;
        if (g_blurbFade > 1.0f) g_blurbFade = 1.0f;
    }
}

// The flow's screen name, upper-cased for the header. The font has the
// glyphs -- most of the frontend's own labels are upper case.
static void botTitle(char* out, size_t cap, const char* s)
{
    size_t i = 0;
    if (!s) s = "";
    for (; s[i] && i + 1 < cap; i++)
        out[i] = (s[i] >= 'a' && s[i] <= 'z') ? (char)(s[i] - 32) : s[i];
    out[i] = '\0';
}

// title along the top, `body` wrapped and centred in the middle, `hint`
// along the bottom. The body is passed in rather than read from
// g_blurbShown because the two bring-up modes have no blurb and something
// has to fill the panel there.
static void drawBotPanel(UIRenderer* ui, const char* title, const char* body,
                         float alpha, const char* hint)
{
    UIWrapStyle text  = botStyle(ui, BOT_TEXT, 19.0f, true);
    UIWrapStyle small = botStyle(ui, BOT_DIM, 12.0f, false);
    float       boxW  = BOT_W - BOT_PAD * 2.0f;
    float       h, y;

    C2D_DrawRectSolid(0.0f, 0.0f, 0.0f, BOT_W, BOT_H, BOT_BACK);
    C2D_DrawRectSolid(0.0f, 0.0f, 0.0f, BOT_W, BOT_HDR, BOT_HEAD);
    C2D_DrawRectSolid(0.0f, BOT_HDR, 0.0f, BOT_W, 2.0f, BOT_ACCENT);
    if (title && *title)
        uirender_draw_wrapped(ui, title, 0, &small, BOT_PAD, 9.0f, boxW,
                              1.0f);

    // The line is centred as a block between the header and the footer
    // rule rather than pinned under the header: one short sentence floating
    // in the middle of the panel reads as deliberate, and a three-line one
    // still has the room.
    text.lineGap = 4.0f;
    h = uirender_wrap_height(ui, body, 0, &text, boxW);
    y = BOT_HDR + 2.0f + (BOT_FOOT - BOT_HDR - 2.0f - h) * 0.5f;
    if (y < BOT_HDR + 12.0f) y = BOT_HDR + 12.0f;
    uirender_draw_wrapped(ui, body, 0, &text, BOT_PAD, y, boxW, alpha);

    C2D_DrawRectSolid(BOT_PAD, BOT_FOOT, 0.0f, boxW, 1.0f, BOT_RULE);
    if (hint && *hint)
        uirender_draw_wrapped(ui, hint, 0, &small, BOT_PAD, BOT_FOOT + 9.0f,
                              boxW, 1.0f);
}

// Wheel and MellowMover ask for the ground through a seam shaped for the
// four arguments they pass. GetElevation's fifth, the `bool *`, is NULL at
// every one of their call sites (`move t0,zero`), so it is NULL here too.
static float topologyElevation(void* tc, const bVector3* pos,
                               int32_t* terrain, bVector3* normal)
{
    return topology_get_elevation((TopologyCoordinate*)tc, pos, terrain,
                                  normal, NULL);
}

// CheckTerrain's topology is the CarState's, which wheel.c holds untyped.
static void* topologyOfCarState(void* cs)
{
    return ((CarState*)cs)->pTopologyCoordinate;
}

int main(int argc, char** argv)
{
    (void)argc; (void)argv;

    gfxInitDefault();
    initPlatformPerf();
    logOpen();

    // The original runs every _GLOBAL_$I$ through __main before main()
    // does anything of its own; sinit_run() is that walk over the ported
    // ones. Among them is the SlotPoolManager, _GLOBAL_$I$bNewSlotPool
    // (0x00240080 -- 0x00240070 beside it is the $D$), which has to be up
    // before anything can call bNewSlotPool. Its allocator hook is left at
    // the default, malloc -- i.e. the heap heapcfg.c already sized.
    sinit_run();
    bSetSlotPoolPrintf(slotPoolLog);

    // The image's vtables are .data and need nothing done to them; the
    // port's are registered with vtable.c, once, before any object that
    // dispatches through one can be built.
    physicssystem_install_vtables();
    physcomp_install_vtables();
    physicscar_install_vtables();
    mellowmover_install_vtables();
    nullmover_install_vtables();
    carcontroller_install_vtables();
    realcontroller_install_vtables();
    cardriver_install_vtables();
    realdriver_install_vtable();
    collisionbody_install_vtables();
    carcollisionbody_install_vtable();

    // Car::SetControlMode reaches the controllers task 26 brings through
    // seams; a NULL one is a class not ported yet, and the arm aborts.
    gRealControllerCtorFn = realcontroller_construct;

    // RealDriver's reset button puts the car back on its route through
    // Car::ResetToRoutePoint, which carreset.c has ported since task 27's
    // third slice. Left NULL, the button did nothing.
    gCarResetToRoutePointFn = car_reset_to_route_point;

    // Collision.obj is ported (collision.c), so a witness's first touch
    // makes a real Collision, CollisionImpulse adds into it, and a
    // witness's end destroys it. The sound and the particles it calls stay
    // NULL until tasks 29 and 30, and it makes neither.
    gCollisionNewFn        = collision_new;
    gCollisionAddImpulseFn = collision_add_impulse;
    gCollisionDestroyFn    = collision_destroy;

    // World::DoTimestep ends every car's step with Car::FinishMovement,
    // which carfinish.c has ported since task 27's eleventh Car slice.
    // Left NULL, the step aborts. Its four Player calls stay NULL until
    // task 26 brings Player, and only a player's car reaches them.
    gCarFinishMovementFn = car_finish_movement;

    // InitializeEverything runs eMathInit (0x0011b9a0) just before
    // eInitEngine, and nothing else fills eMathIdentityMatrix: StuffScenery
    // hands it to every object drawn where it stands -- the road and the
    // terrain -- and left zero, it folds each of them to a point.
    eMathInit();

    // eInitEngine's share (0x00102a48) that the scenery needs: the model
    // pool eInitSlotPools makes, eModel::Init and its deleting destructor,
    // which LoaderScenery and UnloaderScenery call for every kind's models
    // -- emodel.c since task 27's twenty-third slice -- and eInitViews,
    // which gives views 0 to 3 their ids, targets and cameras. The frame
    // memory is the track viewer's to ask for: 5 MB the frontend never
    // touches.
    emodel_init_slot_pool();
    gEModelInitFn    = emodel_init;
    gEModelDestroyFn = emodel_delete;
    eInitViews();

    // The two calls Suspension makes into Wheel go through pointers, left
    // NULL until something says Wheel is linked -- which, in the game,
    // it always is.
    wheel_install_seams();

    // Track.obj and TerrainType.obj are ported, so the ground queries
    // Wheel and MellowMover make go to the real TopologyCoordinate, and
    // their friction and road noise to the real terrain table. The tree
    // has to hold a track's chunks before anything asks -- GetSquare walks
    // the node table unguarded, in the image as here -- and in the game
    // nothing drives before EndGameFlowLoadingTrackSpecific has loaded
    // one and called InitTree (0x0016461c).
    gTerrainTypeInfoTable      = TerrainTypeInfoTable;
    gTerrainRoadNoiseFn        = track_get_road_noise;
    gTopologyGetElevationFn    = topologyElevation;
    gWheelTopologyOfCarStateFn = topologyOfCarState;

    // The joystick layer: the ring of pad reads, the type monitor and the
    // event-node pool (so after sinit_run, which brings the pool manager
    // up). The 3DS's buttons reach it as a DualShock 2 through joyhid.c.
    // Nothing registers a game handler yet -- the menus below still read
    // kDown -- so for now it runs the type detection, which logs
    // "joystick: port 0 type 121" once ten reads have agreed.
    joyhid_install();
    InitJoystick();

    logPrintf("NFSHP2-3DS -- boot flow\n");
    logPrintf("Heap: asked=%luKB got=%luKB linear=%luKB\n",
              (unsigned long)(g_heapInfo.heapAsked / 1024),
              (unsigned long)(g_heapInfo.heapGot / 1024),
              (unsigned long)(g_heapInfo.linearGot / 1024));

    if (!gamedata_init()) {
        fatalConsole();
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

    // ndsp and the menu banks. Silence is a survivable failure -- a card with
    // no SOUND directory still runs the frontend -- so nothing below checks.
    if (bsnd_hw_init(&gSnd)) {
        fesound_init(&gSnd);
        logPrintf("Sound: %u patches in %u voices\n",
                  (unsigned)gSnd.patchCount, gSnd.voices);
    } else {
        logPrintf("Sound: ndsp unavailable, running silent\n");
    }

    // Four times citro3d's default. A track frame is a draw per object the
    // cull keeps, each with its own matrices, and the default's 256 KB is
    // about 500 of them; GPUCMD_Add drops what does not fit without a word.
    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE * 4);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    C3D_RenderTarget* top = C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8,
                                                   GPU_RB_DEPTH24_STENCIL8);
    if (!top) {
        fatalConsole();
        printf("\nno render target.\n");
        waitForExit();
        C2D_Fini();
        C3D_Fini();
        gfxExit();
        return 1;
    }
    C3D_RenderTargetSetOutput(top, GFX_TOP, GFX_LEFT,
                              kDisplayTransferFlags);
    // No depth buffer on this one: nothing 3D is ever drawn to it.
    g_bot = C2D_CreateScreenTarget(GFX_BOTTOM, GFX_LEFT);
    if (!g_bot) {
        fatalConsole();
        printf("\nno bottom render target.\n");
        waitForExit();
        C2D_Fini();
        C3D_Fini();
        gfxExit();
        return 1;
    }

    static UIRenderer ui;
    uirender_init(&ui, 400.0f, 240.0f);
    addBundle(&ui, BUNDLE_FRONTEND);
    UIBundle* globalBundle = addBundle(&ui, BUNDLE_GLOBAL);
    UIBundle* ingameBundle = addBundle(&ui, BUNDLE_INGAME);

    // The blurb moves to the bottom screen, so the top screen stops drawing
    // it -- and stops drawing the bar tAnimatedBlurb wipes it out with,
    // which on its own over an empty strip is just a flash of grey. The
    // animations still run and still move the object; this is a draw-time
    // skip, so nothing has to know.
    uirender_hide_object(&ui, BSCR_OBJ_SCROLLING_TEXT);
    uirender_hide_object(&ui, BSCR_OBJ_WHITEOUT_BAR);

    // FONT_A is the frontend's body face -- 357 of the disc's 934 text
    // objects use it -- and the panel is its only user here. A bundle
    // without it falls the panel back to whatever font loaded first, which
    // is worth knowing about rather than drawing nothing.
    {
        UIWrapStyle probe;
        memset(&probe, 0, sizeof probe);
        probe.fontHash = bchunk_hash("FONT_A");
        probe.scale    = 1.0f;
        if (uirender_line_height(&ui, &probe) > 0.0f) {
            g_botFont = probe.fontHash;
        } else {
            logPrintf("FONT_A missing; the bottom screen takes what it can\n");
        }
    }

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

    // After bgf_init: bscr_init copies the flow's VIDEO_MODE, which is what
    // decides whether the Options screen has a Languages item at all.
    BScreensHooks scrHooks;
    memset(&scrHooks, 0, sizeof(scrHooks));
    scrHooks.user                = &g_boot;
    scrHooks.grayMenuItem        = hookGrayMenuItem;
    scrHooks.setBlurb            = hookSetBlurb;
    scrHooks.moveBrackets        = hookMoveBrackets;
    scrHooks.startMovie          = hookScreenMovie;
    scrHooks.stopMovie           = hookScreenMovieStop;
    scrHooks.jukebox             = hookJukebox;
    scrHooks.displayOptionsStart = hookDisplayOptionsStart;
    scrHooks.startQuickRace      = hookStartQuickRace;
    bscr_init(&g_uiScreens, &g_flow, &scrHooks);

    // And the animation layer the screens drive. bscr_set_anim_hooks keeps
    // changeToScreen and trace for itself -- those two are free functions
    // on a global in the original and belong to bscreens.c, not here.
    BAnimHooks animHooks;
    memset(&animHooks, 0, sizeof(animHooks));
    animHooks.user             = &g_boot;
    animHooks.objectExists     = hookAnimObjectExists;
    animHooks.groupExists      = hookAnimGroupExists;
    animHooks.objectType       = hookAnimObjectType;
    animHooks.getTopLeft       = hookAnimGetTopLeft;
    animHooks.setTopLeft       = hookAnimSetTopLeft;
    animHooks.setGroupPos      = hookAnimSetGroupPos;
    animHooks.setVisible       = hookAnimSetVisible;
    animHooks.getAlpha         = hookAnimGetAlpha;
    animHooks.setAlpha         = hookAnimSetAlpha;
    animHooks.setLanguageID    = hookAnimSetLanguageID;
    animHooks.printText        = hookAnimPrintText;
    animHooks.copyText         = hookAnimCopyText;
    animHooks.scaleAboutCenter = hookAnimScaleAboutCenter;
    animHooks.setColor         = hookAnimSetColor;
    animHooks.getScale         = hookAnimGetScale;
    animHooks.translate        = hookAnimTranslate;
    bscr_set_anim_hooks(&g_uiScreens, &animHooks);

    // main (0x0012da88): SkipFE ships as 0, so LoadLanguageInfo and then
    // ChangeGameFlow(LOADING_FRONTEND). MainLoop takes it from there.
    bgf_change_state(&g_flow, BGF_LOADING_FRONTEND, BGF_NONE);

    if (!georender_init()) {
        logPrintf("georender: shader would not load\n");
    }
    if (!geoview_init(&g_geo)) {
        logPrintf("geoview: %s\n", g_geo.note);
    } else {
        logPrintf("geoview: %d cars, car pack %s, global pack %s\n",
                  g_geo.numCars,
                  g_geo.hasCarPack ? "open" : "missing",
                  g_geo.hasGlobalPack ? "open" : "missing");
    }
    // The track's textures are partly GLOBALB's and INGAMEB's, which the
    // UI already holds; the viewer loads their packs from these copies.
    bool trackOk = trackview_init(&g_track);
    if (globalBundle)
        trackview_share_bundle(&g_track, globalBundle->data, globalBundle->len);
    if (ingameBundle)
        trackview_share_bundle(&g_track, ingameBundle->data, ingameBundle->len);
    if (!trackOk) {
        logPrintf("trackview: %s\n", g_track.note);
    } else {
        logPrintf("trackview: %d bundles shared, texture files %s %s\n",
                  g_track.numShared,
                  g_track.hasTexFile[0] ? "there" : "missing",
                  g_track.hasTexFile[1] ? "there" : "missing");
    }

    // The bottom screen prints the controls itself now, so these are for
    // the log -- and for the console, in the half second before the first
    // frame paints over it.
    logPrintf("D-pad: menu  A: select  START: start  B: back\n");
    logPrintf("SELECT: screen viewer, geometry, then track\n");
    logPrintf("In the viewer, B: scrolling-texture demo\n");
    // The marker tools/run_azahar_test.ps1 greps for: past this line the
    // bundles are resident, the flow is running and frames are being drawn.
    logLine("entering main loop");

    // SELECT cycles these rather than toggling one flag, because there are
    // now four things to look at and the flow is the one to come back to.
    enum { MODE_FLOW = 0, MODE_SCREENS, MODE_GEO, MODE_TRACK, MODE_COUNT };
    int      mode    = MODE_FLOW;
    uint32_t vIndex  = 0;
    uint32_t vShown  = 0xffffffffu;
    BUI*     vProj   = NULL;
    BUIScreen* vScr  = NULL;
    static BMenu vMenu;
    bool     vHasMenu = false;
    int      redraw   = 1;
    u32      clear    = C2D_Color32(0x10, 0x10, 0x18, 0xFF);

    // The scrolling-texture demo, below. vScrollNum is 0 when nothing on the
    // current screen has been borrowed.
#define VSCROLL_MAX 64
    static struct {
        uint32_t index, hash;
        float    x, y, sx, sy;
    } vScroll[VSCROLL_MAX];
    int      vScrollNum  = 0;
    int      vScrollMode = 0;

    // The clock UV scrolling runs off, in the RealTimer units gameflow.c
    // keeps -- 1/4000 s. The flow's own realTimer would do for MODE_FLOW,
    // but bgf_frame only ticks in that mode and the screen viewer is where
    // there is anything scrolling to look at, so the UI gets its own counter
    // advanced exactly as gameflow.c:321 advances that one.
    uint32_t uiTimer = 0;
    int32_t  joyType = -1;
    bool     clockStarted = false;

    while (aptMainLoop()) {
        hidScanInput();
        u32 kDown = hidKeysDown();

        // bSound::updateCompletedVoices' slot in the frame. Without it the
        // allocator hands out 24 channels and then never another.
        bsnd_update(&gSnd);

        uiTimer += (uint32_t)(int)(BOOT_DT * 4000.0f);
        uirender_set_time(&ui, (float)uiTimer * 0.00025f);

        // MainLoop's clocks (0x0012dbd0). It prepares the real step at the
        // top of a frame from the ticker, and the world's from the real one
        // when there is no race, as there is not yet here. It advances both
        // at the frame's end (0x0012de70), which here is the top of the
        // next one. The ticker's measure is BOOT_DT, since the display is
        // vsynced. FrameCounter is the PS2's vertical-blank count, and so
        // one a frame.
        if (clockStarted) {
            AdvanceRealTime();
            AdvanceWorldTime();
        }
        clockStarted = true;
        FrameCounter++;
        PrepareRealTimestep(BOOT_DT);
        PrepareWorldTimestep(RealTimeElapsed);

        // The PS2 reads the pads from its vertical-blank interrupt; here it
        // is once a frame, after the HID scan the read is built from, and
        // after the clocks, as GenerateJoyEvents is in MainLoop.
        ReadJoystickData();
        GenerateJoyEvents();
        if (GetJoystickType(0) != joyType) {
            joyType = GetJoystickType(0);
            logPrintf("joystick: port 0 type %d\n", (int)joyType);
        }

        if (kDown & KEY_SELECT) {
            mode = (mode + 1) % MODE_COUNT;
            if (mode != MODE_SCREENS && vHasMenu) {
                bmenu_unactivate(&vMenu);
                vHasMenu = false;
            }
            vShown = 0xffffffffu;
            redraw = 1;
            // The first car is read off the card the first time anyone asks
            // to see one, not at boot: it is half a megabyte and a second of
            // texture uploads that the frontend has no use for.
            if (mode == MODE_GEO && g_geo.numCars > 0
                && g_geo.numSolids == 0) {
                geoview_load(&g_geo, 0);
            }
            // The track is 9.1 MB and several seconds of texture uploads,
            // so the same: the first visit reads it, and it stays.
            if (mode == MODE_TRACK && g_track.hasBundle && !g_track.loaded) {
                trackview_load(&g_track);
            }
            // The mode is logged because tools/run_azahar_geo.ps1 has no
            // other way to know a SELECT landed. Sleeping for "long enough"
            // after the boot marker is not the same thing: a faster boot
            // moves the keypress earlier, not later, and the run that found
            // this captured the title screen and called it a car.
            if (mode == MODE_GEO) {
                logPrintf("geoview: entered, %s\n", g_geo.note);
            } else if (mode == MODE_TRACK) {
                logPrintf("trackview: entered, %s\n", g_track.note);
                logPrintf("trackview: %d solids linked, %d models, %d "
                          "without a solid, %d baked, %d tris, %d textures "
                          "(%d missing, %d reduced), %u KB linear free\n",
                          g_track.linkedSolids, g_track.numModels,
                          g_track.modelsWithoutSolid, g_track.bakedSolids,
                          g_track.bakedTris, g_track.numTextures,
                          g_track.missingTextures, g_track.reducedTextures,
                          (unsigned)(linearSpaceFree() / 1024u));
                logPrintf("trackview: %d texture packs, %d flipbooks, %d "
                          "names given the default, %d breaks, files in "
                          "%s %s\n",
                          g_track.numPacks, g_track.numAnims,
                          g_track.defaultedHashes, (int)texturepack_breaks,
                          g_track.texLinear[0] ? "linear" : "heap",
                          g_track.texLinear[1] ? "linear" : "heap");
                logPrintf("trackflow: loaded, InGameFlag %d, "
                          "eDisableFixUpTables %d, reverse %d\n",
                          (int)InGameFlag, (int)eDisableFixUpTables,
                          (int)TheTrackPathManager.ReverseTrackDirection);
            } else {
                logPrintf("mode %d\n", mode);
            }
        }

        if (mode == MODE_FLOW) {
            // ---- the boot flow
            if (kDown & KEY_START) {
                bgf_screen_event(&g_flow, BMSG_SCREEN_START_BUTTON, 0);
                redraw = 1;
            }
            if (kDown & KEY_B) {
                bgf_move_back_screen(&g_flow, 1);
                redraw = 1;
            }
            // JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION. The Mode Selects
            // register a handler for it and do nothing but remember whether
            // it is down; StartQuickRace reads that at the moment it runs.
            // So it is a held button, not a pressed one, and the state goes
            // through every frame rather than on an edge.
            bscr_joy(&g_uiScreens, 0, BSCR_JOY_SELECT_TRANSMISSION,
                     (hidKeysHeld() & KEY_X) ? 1 : 0);

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

            // This used to be five lines of console on the bottom screen.
            // The bottom screen is the blurb's now, and the flow's state is
            // something only a developer reads, so it goes to the log -- on
            // the same edge it used to repaint on, which makes it a trace of
            // what changed rather than a snapshot of where it ended up.
            if (redraw) {
                redraw = 0;
                const BMenuItem* item =
                    g_boot.hasMenu ? bmenu_current(&g_boot.menu) : NULL;
                logLine("flow state %s screen %s %08lx stack %d menu %d "
                        "item %d last %s clock %lu/%lu note %s",
                        bgf_state_name(&g_flow, g_flow.current),
                        g_flow.screen ? g_flow.screen->name : "-",
                        (unsigned long)g_boot.screenHash,
                        g_flow.stack.index,
                        g_boot.hasMenu ? g_boot.menu.numItems : 0,
                        item ? (int)item->itemID : -1,
                        messageName(g_lastMsg),
                        (unsigned long)g_flow.realTime,
                        (unsigned long)g_flow.realTimer,
                        g_boot.note);
            }

            updateBlurb(&g_boot, BOOT_DT);

            C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
            C2D_TargetClear(top, clear);
            C2D_SceneBegin(top);
            if (g_boot.screen && g_boot.project)
                uirender_draw_screen(&ui, g_boot.project, g_boot.screen, 1.0f);
            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            {
                char        title[48];
                const char* body = g_blurbShown;
                float       fade = g_blurbFade;

                botTitle(title, sizeof title,
                         g_flow.screen ? g_flow.screen->name : "");
                if (g_flow.screen
                    && g_flow.screen->callback == bgf_plain_screen_callback) {
                    body = kPlainScreenNote;
                    fade = 1.0f;
                }
                drawBotPanel(&ui, title, body, fade,
                             "A select   B back   START go   SELECT viewer");
            }
            C3D_FrameEnd(0);
            continue;
        }

        if (mode == MODE_GEO) {
            circlePosition pad;

            if (kDown & KEY_START) break;
            hidCircleRead(&pad);
            geoview_input(&g_geo, kDown, hidKeysHeld(), pad.dx, pad.dy,
                          BOOT_DT);

            devLog(0, "geo car %d/%d %s",
                   g_geo.numCars ? g_geo.curCar + 1 : 0, g_geo.numCars,
                   g_geo.numCars ? g_geo.car[g_geo.curCar] : "-");
            devLog(1, "geo solid %d/%d %s  %d tris  %d textures, %d missing",
                   g_geo.numSolids ? g_geo.curSolid + 1 : 0, g_geo.numSolids,
                   geoview_solid_name(&g_geo),
                   g_geo.drawAll ? g_geo.loadedTris
                                 : g_geo.mesh[g_geo.curSolid].numTris,
                   g_geo.numTextures, g_geo.missingTextures);
            devLog(2, "geo note %s", g_geo.note);
            // The camera is framed from the solid's own AABB, so when the
            // top screen is empty these five numbers say whether the model
            // is off camera or was never there.
            devLog(3, "geo at %.1f %.1f %.1f r %.2f d %.2f v %d",
                   g_geo.centre[0], g_geo.centre[1], g_geo.centre[2],
                   g_geo.radius, g_geo.dist,
                   g_geo.mesh[g_geo.curSolid].numVerts);

            C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
            // Not C2D_TargetClear: this target has a depth buffer and the
            // clear has to reach it, or the second frame tests against the
            // first frame's depths. The byte swap is what citro2d does to a
            // C2D_Color32 on its way to the GPU.
            C3D_RenderTargetClear(top, C3D_CLEAR_ALL,
                                  __builtin_bswap32(clear), 0);
            C3D_FrameDrawOn(top);
            geoview_draw(&g_geo);
            // geoview_draw leaves its own shader, attribute layout and depth
            // test bound. C2D_Prepare puts citro2d's back, which is what the
            // other two modes are about to assume; the depth test goes off
            // explicitly because a 2D quad has nothing sensible to compare.
            C2D_Prepare();
            C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);

            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            // FONT_A has no underscore and no angle brackets -- a glyph
            // the font does not have is dropped, and a file name with a
            // character missing is worse than not naming the file.
            drawBotPanel(&ui, "GEOMETRY VIEWER",
                         "Car, solid and camera numbers go to the debug "
                         "log on the SD card.", 1.0f,
                         "L/R car   D-pad solid, zoom   A all   X tex");
            C3D_FrameEnd(0);
            continue;
        }

        if (mode == MODE_TRACK) {
            circlePosition pad;
            // The fog colour TRACKB12's sky would be, near enough, until
            // step 3 brings the sky itself.
            const u32 sky = C2D_Color32(0x8c, 0xa8, 0xc8, 0xFF);

            if (kDown & KEY_START) break;
            hidCircleRead(&pad);
            trackview_input(&g_track, kDown, hidKeysHeld(), pad.dx, pad.dy,
                            BOOT_DT);

            C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
            C3D_RenderTargetClear(top, C3D_CLEAR_ALL,
                                  __builtin_bswap32(sky), 0);
            C3D_FrameDrawOn(top);
            trackview_draw(&g_track);
            C2D_Prepare();
            C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);

            devLog(0, "track %s", g_track.note);
            devLog(1, "track at %.1f %.1f %.1f yaw %.2f pitch %.2f "
                   "speed %.1f stop %d/%d",
                   g_track.pos[0], g_track.pos[1], g_track.pos[2],
                   g_track.yaw, g_track.pitch, g_track.speed,
                   g_track.stop + 1, g_track.numStops);
            devLog(2, "track drew %d of %d (%d in place), %d tris, cull "
                   "zone %d",
                   g_track.drawn, g_track.drawInfos, g_track.drawnInPlace,
                   g_track.drawnTris, (int)CurrentZoneNumber);
            if (g_track.listFrame) {
                logLine("track drew: %s", g_track.drawList);
                g_track.listFrame = false;
            }
            devLog(3, "track gpu peak %d words, %d skipped, frame "
                   "memory failed %d, held back %d (%d sorted, %d "
                   "dropped)",
                   g_track.cmdPeakWords, g_track.cmdSkipped,
                   g_track.frameMallocFails, g_track.numDeferred,
                   g_track.deferredSorted, g_track.deferredDropped);
            devLog(8, "track flipbook frames %d uploaded, %d failed",
                   g_track.frameUploads, g_track.frameFails);

            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            drawBotPanel(&ui, "TRACK VIEWER",
                         g_track.loaded
                             ? "The scenery the game's own cull picks, "
                               "prelit, in the engine's draw order. "
                               "Numbers go to the debug log."
                             : g_track.note,
                         1.0f,
                         "Pad fly  ABXY look  L/R down, up  D-pad speed, stop");
            C3D_FrameEnd(0);
            continue;
        }

        // ---- the screen viewer
        if (kDown & KEY_START) break;
        if (kDown & KEY_R) vIndex = (vIndex + 1) % screenCount;
        if (kDown & KEY_L) vIndex = (vIndex + screenCount - 1) % screenCount;

        // Nothing on the disc draws a scrolling texture. ROADLINES and
        // SCREEN_LINES each occur exactly once in the whole of extracted/ --
        // their own TextureInfo record, and no Flailer bitmap, no other pack
        // and nothing in NFSHP2.ELF -- so the scroll path has no natural
        // subject to be looked at over. B gives it one: it points the
        // current screen's bitmaps at each in turn through the engine's own
        // ChangeTexture, then back to their own textures.
        if ((kDown & KEY_B) && vScr && vProj) {
            static const char* const kScrollTex[] = {
                "ROADLINES", "SCREEN_LINES"
            };
            if (vScrollNum == 0) {
                // Every visible bitmap on the screen, not just the biggest.
                // Both of these textures are nearly featureless -- ROADLINES
                // is a 512x96 asphalt swatch that runs from luma 52 to 67 --
                // so one of them behind the screen's own art is a change of a
                // fraction of a percent a frame, which is indistinguishable
                // from not scrolling at all. Taking the whole screen leaves
                // nothing static in front of it.
                for (uint32_t n = 0; n < vScr->count; n++) {
                    BUIObject o;
                    uint32_t  idx = vScr->first + n;
                    if (vScrollNum >= VSCROLL_MAX) break;
                    if (!bui_object(vProj, idx, &o)) continue;
                    if (o.type != BUI_TYPE_BITMAP) continue;
                    if (o.visible != BUI_VISIBLE) continue;
                    vScroll[vScrollNum].index = idx;
                    vScroll[vScrollNum].hash  = o.textureHash;
                    vScroll[vScrollNum].x     = o.x;
                    vScroll[vScrollNum].y     = o.y;
                    vScroll[vScrollNum].sx    = o.scaleX;
                    vScroll[vScrollNum].sy    = o.scaleY;
                    vScrollNum++;
                }
                vScrollMode = 0;
            }
            if (vScrollNum > 0) {
                vScrollMode = (vScrollMode + 1) % 3;
                for (int n = 0; n < vScrollNum; n++) {
                    uint32_t idx = vScroll[n].index;
                    if (!vScrollMode) {
                        bui_set_bitmap_texture(vProj, idx, vScroll[n].hash);
                        bui_set_object_pos(vProj, idx, vScroll[n].x,
                                           vScroll[n].y);
                        bui_set_object_scale(vProj, idx, vScroll[n].sx,
                                             vScroll[n].sy);
                        continue;
                    }
                    bui_set_bitmap_texture(
                        vProj, idx, bchunk_hash(kScrollTex[vScrollMode - 1]));
                    // Sized to the screen rather than left at the object's
                    // own scale. The authored scales are for the authored
                    // art -- this screen's background is ScaleX 40 -- and a
                    // texture stretched 40 times over travels its whole
                    // width in a frame, which reads as noise however right
                    // the offset is. At 1:1 with the 640x480 screen an
                    // offset of du moves the image by du * 640, which is
                    // something a screenshot can be measured against.
                    float box[4];
                    bui_set_object_pos(vProj, idx, 0.0f, 0.0f);
                    bui_set_object_scale(vProj, idx, 1.0f, 1.0f);
                    if (uirender_object_bounds(&ui, vProj, idx, box)
                        && box[2] > box[0] && box[3] > box[1]) {
                        bui_set_object_scale(vProj, idx,
                                             640.0f / (box[2] - box[0]),
                                             480.0f / (box[3] - box[1]));
                    }
                }
                logPrintf("scroll demo: %d bitmaps -> %s\n", vScrollNum,
                          vScrollMode ? kScrollTex[vScrollMode - 1]
                                      : "their own textures");
                redraw = 1;
            }
        }
        if (kDown & KEY_X) {
            language = (language + 1) % NUM_LANGUAGES;
            hookSetLanguage(&g_boot, language);
            redraw = 1;
        }

        if (vIndex != vShown) {
            // Put the demo's borrowed object back before leaving the screen:
            // the bundle is a single heap copy and the write is to the chunk
            // itself, so it would otherwise still be there on the way round.
            if (vScrollNum > 0 && vProj) {
                for (int n = 0; n < vScrollNum; n++) {
                    bui_set_bitmap_texture(vProj, vScroll[n].index,
                                           vScroll[n].hash);
                    bui_set_object_pos(vProj, vScroll[n].index,
                                       vScroll[n].x, vScroll[n].y);
                    bui_set_object_scale(vProj, vScroll[n].index,
                                         vScroll[n].sx, vScroll[n].sy);
                }
                vScrollNum  = 0;
                vScrollMode = 0;
            }
            if (vHasMenu) bmenu_unactivate(&vMenu);
            vHasMenu = false;
            vShown   = vIndex;
            vScr     = uirender_screen_at(&ui, vIndex, &vProj);
            redraw   = 1;
        }
        if (!vHasMenu && vScr && vProj) {
            g_lastMsg = BMSG_NONE;
            if (bmenu_open(&vMenu, vProj, vScr, viewerCallback, NULL)
                && vMenu.numItems > 0) {
                vMenu.sound = fesound_play;
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

        redraw = 0;                     // nothing on screen waits for it now
        {
            const BMenuItem* item = vHasMenu ? bmenu_current(&vMenu) : NULL;
            devLog(4, "viewer %lu/%lu  hash %08lx  %lu objects",
                   (unsigned long)(vIndex + 1), (unsigned long)screenCount,
                   (unsigned long)(vScr ? vScr->nameHash : 0),
                   (unsigned long)(vScr ? vScr->count : 0));
            devLog(5, "viewer lang %s  menu %d items, on MENUITEM_%d  last %s",
                   kLanguages[language] + 10,
                   vHasMenu ? vMenu.numItems : 0,
                   item ? (int)item->itemID : -1, messageName(g_lastMsg));
            devLog(6, "viewer textures %d cached, %d missing; "
                   "fonts %d missing",
                   ui.numTextures, ui.missingTextures, ui.missingFonts);
            if (vScrollMode) {
                // Twice a second, not every frame: the offsets move
                // continuously and the point is that they are moving.
                const char* nm = vScrollMode == 1 ? "ROADLINES"
                                                  : "SCREEN_LINES";
                uint32_t    h  = bchunk_hash(nm);
                for (int i = 0; i < ui.numTextures; i++) {
                    if (ui.textures[i].hash != h) continue;
                    devLog(7, "scroll %s ty%d t%.1f du %+.4f dv %+.4f", nm,
                           ui.textures[i].scrollType,
                           (double)((int)(ui.scrollTime * 2.0f) * 0.5f),
                           (double)texpack_scroll_axis(
                               ui.scrollTime, ui.textures[i].scrollS,
                               ui.textures[i].scrollType,
                               ui.textures[i].scrollStep),
                           (double)texpack_scroll_axis(
                               ui.scrollTime, ui.textures[i].scrollT,
                               ui.textures[i].scrollType,
                               ui.textures[i].scrollStep));
                    break;
                }
            }
        }

        C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
        C2D_TargetClear(top, clear);
        C2D_SceneBegin(top);
        uirender_draw_screen(&ui, vProj, vScr, 1.0f);

        C2D_TargetClear(g_bot, BOT_BACK);
        C2D_SceneBegin(g_bot);
        drawBotPanel(&ui, "SCREEN VIEWER",
                     "Screen, language and texture numbers go to the debug "
                     "log on the SD card.", 1.0f,
                     "L/R screen   X language   B scroll   START exit");
        C3D_FrameEnd(0);
    }

    // Leaving here rather than crashing looks identical from outside the
    // emulator, so say so, and carry the texture-cache tally out with it --
    // a screen that renders but is missing half its art shows up here as a
    // non-zero "missing" long before anyone squints at a screenshot.
    logLine("left main loop: %d textures cached, %d missing, %d fonts missing",
            ui.numTextures, ui.missingTextures, ui.missingFonts);

    // Leave through the flow rather than reaching past it into its menu.
    // ChangeToScreen(NULL) hides the screen, sends it SCREEN_UNACTIVATE and
    // only then calls leaveScreen, which is where the menu is torn down --
    // so the screen hears about its own exit in the order it would in the
    // original. Closing the menu directly delivered an UNHIGHLIGHT and a
    // run of UNACTIVATEs to a screen that had never been told it was
    // going away. The viewer's menu is nobody's, so it just closes.
    bgf_change_to_screen(&g_flow, NULL, 0);
    if (vHasMenu) bmenu_unactivate(&vMenu);
    geoview_free(&g_geo);
    trackview_free(&g_track);
    {
        // What BeginGameFlowUnloadingTrackSpecific leaves: every list the
        // track filled empty again but the shared bundles' own.
        int solids = 0, models = 0, packs = 0;
        bNode* n;

        for (n = SolidList.next; n != &SolidList; n = n->next) solids++;
        for (n = ModelList.next; n != &ModelList; n = n->next) models++;
        for (n = TexturePackList.next; n != &TexturePackList; n = n->next)
            packs++;
        logLine("trackview: freed, InGameFlag %d, eDisableFixUpTables %d, "
                "%d solids, %d models, %d texture packs left",
                (int)InGameFlag, (int)eDisableFixUpTables, solids, models,
                packs);
    }
    bsnd_hw_close(&gSnd);
    georender_exit();
    uirender_free(&ui);

    // ~SlotPoolManager clears the sentinel and walks an already-emptied
    // list, so the original leaks every pool at shutdown by construction
    // (docs/formats/bslotpool.md). Releasing them first is the port's
    // addition; it costs nothing here and means a leak check on the way out
    // is reading the real number.
    bDeleteAllSlotPools();
    bSlotPoolManagerShutdown();

    C2D_Fini();
    C3D_Fini();
    gfxExit();
    return 0;
}
