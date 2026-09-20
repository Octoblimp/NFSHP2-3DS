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
#include "bslotpool.h"
#include "bscreens.h"
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

    // The original builds a SlotPoolManager at load time through
    // _GLOBAL_$I$ (0x00240070); this is that, done explicitly. It has to be
    // up before anything can call bNewSlotPool, and the allocator hook is
    // left at its default, which is malloc -- i.e. the heap heapcfg.c
    // already sized.
    bSlotPoolManagerInit();
    bSetSlotPoolPrintf(slotPoolLog);

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
            if (bmenu_open(&vMenu, vProj, vScr, viewerCallback, NULL)
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

    // Leave through the flow rather than reaching past it into its menu.
    // ChangeToScreen(NULL) hides the screen, sends it SCREEN_UNACTIVATE and
    // only then calls leaveScreen, which is where the menu is torn down --
    // so the screen hears about its own exit in the order it would in the
    // original. Closing the menu directly delivered an UNHIGHLIGHT and a
    // run of UNACTIVATEs to a screen that had never been told it was
    // going away. The viewer's menu is nobody's, so it just closes.
    bgf_change_to_screen(&g_flow, NULL, 0);
    if (vHasMenu) bmenu_unactivate(&vMenu);
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
