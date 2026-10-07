// NFSHP2-3DS -- the boot flow, and the Flailer screen viewer behind it.
//
// This boots the way the PS2 game boots. source/gameflow.c is the port of
// GameFlowStateInfoTable and LaunchFrontendMenus; the three tables that
// drive it are right here, because they are the part a reader wants to see:
//
//   kGameFlowStages[]  the nine game flow states and their Begin/End/Loop
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
// The title movies play too, straight off the card: source/avimovie.c
// streams the disc's own MOVIES/INTRO/*.AVI and source/mv3.c decodes their
// MV3 video, and hookMovieOpen() points the title screen's movie plane at
// the texture they land in. A movie that is not on the card answers "not
// there", and the flow moves on to the next.
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
#include <malloc.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#include "acidsys.h"
#include "aiaction.h"
#include "aiactions.h"
#include "aicarcontroller.h"
#include "aidriver.h"
#include "bchunk.h"
#include "bchunkload.h"
#include "beltmover.h"
#include "bmem.h"
#include "bmenu.h"
#include "bsnd.h"
#include "bslotpool.h"
#include "bticker.h"
#include "camera.h"
#include "cammover.h"
#include "bscreens.h"
#include "bcarsel.h"
#include "nfsrewards.h"
#include "bsetup.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carinfo.h"
#include "carinit.h"
#include "carloader.h"
#include "carmodes.h"
#include "carrenderinfo.h"
#include "carstate.h"
#include "characterinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "difficultyinfo.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "edisplay.h"
#include "eenvmap.h"
#include "elight.h"
#include "emath.h"
#include "emodel.h"
#include "esolid.h"
#include "eview.h"
#include "gamedata.h"
#include "fesound.h"
#include "flailer.h"
#include "frameprof.h"
#include "fred.h"
#include "fredrace.h"
#include "frontres.h"
#include "gameflow.h"
#include "capture.h"
#include "hangwatch.h"
#include "heapcfg.h"
#include "logwriter.h"
#include "geoview.h"
#include "georender.h"
#include "hudanim.h"
#include "hudcop.h"
#include "hudnis.h"
#include "hudrender.h"
#include "hudscore.h"
#include "hudsplit.h"
#include "hudtach.h"
#include "trackmap.h"
#include "joyevent.h"
#include "joyhid.h"
#include "joypad.h"
#include "jbstream.h"
#include "jukebox.h"
#include "songmon.h"
#include "avimovie.h"
#include "mainloop.h"
#include "mellowmover.h"
#include "physcomp.h"
#include "physicscar.h"
#include "physicssystem.h"
#include "psychodriver.h"
#include "nisoverlay.h"
#include "playercam.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playerinput.h"
#include "playerupdate.h"
#include "playerzone.h"
#include "previewroute.h"
#include "queuedfile.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "realtime.h"
#include "replay.h"
#include "resource.h"
#include "sinit.h"
#include "shake.h"
#include "terraintype.h"
#include "texturepack.h"
#include "texturestream.h"
#include "topology.h"
#include "track.h"
#include "sky.h"
#include "sun.h"
#include "efog.h"
#include "weatherman.h"
#include "trackflow.h"
#include "trackview.h"
#include "traffictele.h"
#include "uirender.h"
#include "warp.h"
#include "wheel.h"
#include "world.h"

// The race's frame rates on the HUD (step 13b-2): Player::DisplayDebugInfo's
// "C: %dfps" and "G: %dfps", with the car's position and odometer, which
// retail shows with its pause debug menu's "Show debug Info"
// (DisplayPlayerDebugInfo). 1 shows them, on the top screen's left; the
// build the user plays has 0.
#define SHOW_FRAME_RATES 0

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
// One of the three texture packs the game loads at boot (docs/formats/
// zdir-archive.md). Retail keeps the title screen's Need for Speed logo,
// LOADING, only here; the demo had a second copy in GLOBALB.BUN, so the port
// never needed this file until it ran on retail data.
#define BUNDLE_DYNTEX   "GLOBAL/DYNTEX.BIN"

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
      bgf_language_screen_callback },
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
    // Cops On's You're The Cop, bsetup.c; the same module instance rule,
    // made by bsetup_init().
    { "ChallengeBeACop",         BSETUP_SCREEN_BEACOP,
      bsetup_beacop_callback },
    // Where You're The Cop's Setup goes: BeTheCopSetup, the one
    // RaceSetupBaseClass screen ported.
    { "Be The Cop Setup",        BSETUP_SCREEN_BE_THE_COP_SETUP,
      bsetup_btc_callback },

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
    // Where You're The Cop and its Setup go. The two-player car select has
    // a screen per pad, and this is player one's -- the 3DS never gets
    // there, as it never has a second pad.
    { "Select Car",              0xb5074ab4u,   // SelectCarScreen
      bcarsel_screen_callback },
    { "Select Car2P",            0x18dc8e52u,   // SelectCarScreen
      bcarsel_screen_callback },
    // Where car select goes on to for every game type but the single race
    // and the championship, You're The Cop's included.
    { "Select Track",            0x15417b53u,   // TrackSelectScreenCallback
      bgf_plain_screen_callback },
    // Same Flailer screen as "Language Options Pre FE" above, entered under
    // a second name from the Options menu. The ELF registers both, to one
    // Callback that picks the class by name; this one's slide-on is still
    // to be ported.
    { "Language Options",        0x632b068eu,   // LanguageOptionsScreen
      bgf_language_screen_callback },
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

// The track states are trackflow.c's, which change the flow through
// gTrackFlowGameFlow: each Begin makes it the flow that entered the state,
// and its load callbacks run on it later.
static void flowBeginLoadingTrackCommon(BGameFlow* gf)
{
    gTrackFlowGameFlow = gf;
    BeginGameFlowLoadingTrackCommon();
}

static void flowBeginLoadingTrackSpecific(BGameFlow* gf)
{
    gTrackFlowGameFlow = gf;
    BeginGameFlowLoadingTrackSpecific();
}

static void flowEndLoadingTrackSpecific(BGameFlow* gf)
{
    (void)gf;
    EndGameFlowLoadingTrackSpecific();
}

static void flowBeginUnloadingTrackSpecific(BGameFlow* gf)
{
    gTrackFlowGameFlow = gf;
    BeginGameFlowUnloadingTrackSpecific();
}

static void flowBeginUnloadingTrackCommon(BGameFlow* gf)
{
    gTrackFlowGameFlow = gf;
    BeginGameFlowUnloadingTrackCommon();
}

// GameFlowStateInfoTable, retail's 0x002faea0. IN_FRONTEND and RACING are
// the resting states and have no functions at all, and LOADING_TRACK_
// SPECIFIC's Loop (0x00169160) is empty. A SkipFE boot's StartRace asks for
// LOADING_TRACK_COMMON; the frontend's own way into a race is not ported.
static const BGameFlowStateInfo kGameFlowStages[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         bgf_begin_loading_frontend,
                                  bgf_end_loading_frontend, NULL },
    { "UNLOADING_FRONTEND",       bgf_begin_unloading_frontend, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     flowBeginLoadingTrackCommon, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   flowBeginLoadingTrackSpecific,
                                  flowEndLoadingTrackSpecific, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", flowBeginUnloadingTrackSpecific, NULL,
                                  NULL },
    { "UNLOADING_TRACK_COMMON",   flowBeginUnloadingTrackCommon, NULL, NULL },
};

// ----------------------------------------------------------- the 3DS side

#define BOOT_MAX_LOADS 4

typedef struct {
    UIRenderer* ui;

    // what the boot flow has made current
    BUI*        project;
    BUIScreen*  screen;
    uint32_t    screenHash;
    BMenu       menu;
    bool        hasMenu;

    // TheMoviePlayer: the title's movies and the menus' take turns in it.
    // movieTexHash is what the one playing draws into -- the title plane's
    // own textureHash, which MoviePlayer blits into whatever pMoviePlane
    // carries (on this disc SPLASH_SCREEN), or PANELMOVIE. movieAttached:
    // the override for it is in -- the title's at open, the menus' at their
    // first frame, since a panel draws nothing until Update fills it. The
    // title's movie can be in the player while the menus' gate is still up
    // (BACK from the main menu), and UpdateMovie then drives it too.
    AviPlayer   movie;
    bool        moviePlaying;
    uint32_t    movieTexHash;
    bool        movieAttached;
    const char* panelMissing;  // the last menu movie not found, logged once

    char        note[64];      // last thing worth putting on the status line
    int         missingMovies;

    // Loads the flow has asked for and not yet been told about; see
    // hookLoadResource.
    struct { const char* what; BGameFlowDone done; } pending[BOOT_MAX_LOADS];
    int         numPending;
} Boot;

static Boot g_boot;
static BGameFlow g_flow;
static BScreens g_uiScreens;
static BSetup   g_setup;

// The top screen's render target. A global because the flow draws a frame of
// its own before the main loop is reached: LoadGlobalChunks' eDisplayFrame,
// which puts LOADING up while the frontend loads.
static C3D_RenderTarget* g_top;

// The geometry viewer's state. Static rather than automatic because it
// carries a mesh and a texture table per solid and is about 100 KB; main's
// stack is not the place for it.
static GeoView g_geo;

// The track viewer's, for the same reason: the cull info alone is 2 KB, and
// the texture packs' indexes ride along.
static TrackView g_track;

// The frontend's 3D view, the car select's (trackview_attach_frontend),
// and FRONTB as the UI holds it, whose engine half frontres loads.
static TrackView g_feView;
static UIBundle* g_frontBundle;

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
    // The lines go to the card from a thread of their own (logwriter.h):
    // written in place, a race's once-a-second lines cost the device that
    // second's frame, and more while the card was slow.
    logwriter_start(g_log);
    atexit(logwriter_drain);
    // stderr is where bMalloc and the other fatal paths say why they abort,
    // just before they do; on the device it would otherwise go nowhere.
    // It stays unbuffered and in place, so the reason is on the card
    // before abort() takes the process down.
    if (freopen("sdmc:/nfshp2_stderr.txt", "w", stderr) != NULL)
        setvbuf(stderr, NULL, _IONBF, 0);
}

static void logLine(const char* fmt, ...)
{
    char    line[2048];
    va_list ap;
    int     n;

    if (!g_log) return;
    va_start(ap, fmt);
    n = vsnprintf(line, sizeof line - 1, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if ((size_t)n > sizeof line - 2) n = (int)(sizeof line - 2);
    line[n++] = '\n';
    logwriter_put(line, (size_t)n);
}

// gNewTrackMapFn: trackmap_new, with a line in the log for each map made,
// so a run shows whether the map found its seven textures.
static struct TrackMap *newTrackMapLogged(TrackInfo *track, struct Car *car,
                                          struct Player *p)
{
    TrackMap *m = trackmap_new(track, car, p);
    const TextureInfo *tex[7] = {
        m->TrackMapTexture, m->CarMarkerNonrotatingTexture,
        m->CarMarkerRotatingTexture, m->OverlayTexture, m->UnderlayTexture,
        m->StartFinishLineTexture, m->RoadblockTexture,
    };

    logLine("trackmap: track %d, sufficient %d",
            track != NULL ? (int)track->TrackNumber : -1,
            (int)m->SufficientDataToRenderMe);
    for (int i = 0; i < 7; i++) {
        if (tex[i] != NULL) {
            logLine("trackmap: texture %d %.24s %dx%d, %d bits, semi %d",
                    i, tex[i]->DebugName, (int)tex[i]->Width,
                    (int)tex[i]->Height, (int)tex[i]->BitDepth,
                    (int)tex[i]->IsAnySemitransparencyFlag);
        } else {
            logLine("trackmap: texture %d none", i);
        }
    }
    return m;
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

// Fred (0x002fc050), the frontend database (fred.h), which the card loads
// over whole. The jukebox and the volumes read its audio options at +148.
#define FRED_AUDIO_OPTIONS offsetof(FrontendDatabase, AudioOptionsScreenData)

// sound::jukebox (0x003115d0), the EA TRAX player, and what it asks of the
// game. The flow's CurrentGameFlowState is its gp-21420; the VBlank count
// is FrameCounter; nothing pauses the flow or sets cops yet.
static JBSound g_jukebox;
static int     g_audioMode = 1;     // gp-18892, stereo

static int      jbState(void* c) { (void)c; return g_flow.current; }
// TheLanguageManager's CurrLanguage, for GetSkinNumber's cop skins.
static int32_t  currLanguage(void) { return g_flow.currLanguage; }
static int      jbMaxCops(void* c) { (void)c; return 0; }
static uint32_t jbVBlank(void* c) { (void)c; return (uint32_t)FrameCounter; }
static int      jbPaused(void* c) { (void)c; return 0; }

static const JBWorld kJukeboxWorld = {
    NULL, jbState, jbMaxCops, jbVBlank, jbPaused,
};

static void jukeboxAssert(int line)
{
    logLine("jukebox: retail asserts at line %d", line);
}

// No ndsp: bSound::GetStatus() is not 1, and that is all LoadCartridge
// asks before it gives up.
static int jbSoundDown(void* c) { (void)c; return 0; }
static const JBHost kNoJukeboxHost = {
    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL, jbSoundDown, NULL,
};

// FlailerScreen::Activate (0x0016a858) builds the screen's FlailerMenu
// before its Callback hears SCREEN_ACTIVATE, and activates it after: the
// Callback can gray items the menu already has -- the language screen hides
// Load All Languages in its constructor -- and the highlight then skips them.
static void hookOpenScreen(void* user, const BScreenConfig* cfg)
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
        b->hasMenu = true;
    }
}

static void hookEnterScreen(void* user, const BScreenConfig* cfg)
{
    Boot* b = (Boot*)user;
    (void)cfg;
    if (b->hasMenu) bmenu_activate(&b->menu, 0);
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

// SetFlailerScreenVisibility (0x0014cbf8) for the code past the flow:
// trackflow's loading screen, the coordinator's screens and the NIS
// overlay. They pass retail's enum, where FLAILER_SCREEN_VISIBLE is 0.
static void raceScreenVisibility(uint32_t screen, int visibility)
{
    hookSetScreenVisible(&g_boot, screen,
                         visibility == FLAILER_SCREEN_VISIBLE);
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

// FlailerSetGroupVisibility (0x001454e8): the Visibility byte of every object
// on the screen whose GroupHash is `group`, stored directly. The original
// looks the first one up once and throws the answer away before its loop;
// that is a wasted search and nothing else.
static void hookSetGroupVisible(void* user, uint32_t screen, uint32_t group,
                                int visible)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    int32_t    idx;
    if (!s || !ui) return;
    for (idx = bui_next_in_group(ui, s, group, BUI_TYPE_NONE, -1); idx >= 0;
         idx = bui_next_in_group(ui, s, group, BUI_TYPE_NONE, idx))
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

// MoviePlayer::Close (0x00237fc8) empties the player's five texture slots,
// and RenderFlailerBitmap (0x00143078) draws a SPLASH_SCREEN plane only from
// those slots -- so a closed movie's plane draws nothing, whether or not it
// is still visible. Dropping the override is the same thing here: uirender.c
// draws a movie texture only while something stands in for it.
static void hookMovieClose(void* user)
{
    Boot* b = (Boot*)user;
    const AviMovie* m = &b->movie.movie;
    if (!b->moviePlaying) return;
    aviplayer_halt(&b->movie);
    // Read is every frame the clock passed, or the worker got to; decoded
    // is the ones it drew.
    logLine("movie close after %lu/%u frames, %lu decoded, %lu skipped, "
            "sound %lu bytes in, %lu samples queued, error %d",
            (unsigned long)m->nextFrame, (unsigned)m->info.frames,
            (unsigned long)m->decoded, (unsigned long)m->skipped,
            (unsigned long)b->movie.snd.pushed,
            (unsigned long)b->movie.audioSamples, m->error);
    if (b->movie.started && b->movie.threaded) {
        double secs = (double)(svcGetSystemTick() - b->movie.startTick)
                      / SYSCLOCK_ARM11;
        double ms   = 1000.0 / SYSCLOCK_ARM11;
        unsigned long n = m->nextFrame ? (unsigned long)m->nextFrame : 1;
        unsigned long c = b->movie.calls ? (unsigned long)b->movie.calls : 1;
        logLine("movie cost: %lu calls in %.1f s, %.3f ms a call; core %d "
                "%.2f ms a frame reading, %.2f decoding, %.2f converting; "
                "%lu waits",
                (unsigned long)b->movie.calls, secs,
                (double)b->movie.stepTicks * ms / c, b->movie.workerCore,
                (double)m->readClocks * ms / n,
                (double)m->decodeClocks * ms / n,
                (double)b->movie.showTicks * ms / n,
                (unsigned long)b->movie.waits);
    } else if (b->movie.started) {
        double secs = (double)(svcGetSystemTick() - b->movie.startTick)
                      / SYSCLOCK_ARM11;
        double ms   = 1000.0 / SYSCLOCK_ARM11;
        unsigned long n = m->decoded ? (unsigned long)m->decoded : 1;
        logLine("movie cost: %lu calls in %.1f s, %.2f ms a step (%.2f "
                "reading, %.2f decoding), %.2f ms a show",
                (unsigned long)b->movie.calls, secs,
                (double)b->movie.stepTicks * ms / n,
                (double)m->readClocks * ms / n,
                (double)m->decodeClocks * ms / n,
                (double)b->movie.showTicks * ms / n);
    }
    uirender_override_texture(b->ui, b->movieTexHash, NULL, 0, 0, false);
    aviplayer_close(&b->movie);
    b->moviePlaying = false;
}

// The flow names the disc's files, MOVIES\INTRO\EALOGO_EN.AVI; the card has
// the same tree under the data directory. A movie that is not there answers
// 0, and gameflow.c treats that as a movie that has already finished rather
// than sitting on a MoviePlayer that never ends.
static bool movieFile(const char* path, char* rel, char* full)
{
    size_t i;
    for (i = 0; path[i] && i + 1 < GAMEDATA_MAX_PATH; i++)
        rel[i] = path[i] == '\\' ? '/' : path[i];
    rel[i] = '\0';
    return !path[i] && gamedata_path(rel, full, GAMEDATA_MAX_PATH);
}

static int hookMovieOpen(void* user, const char* path)
{
    Boot*           b = (Boot*)user;
    const AviInfo*  in = &b->movie.movie.info;
    char            rel[GAMEDATA_MAX_PATH], full[GAMEDATA_MAX_PATH];

    hookMovieClose(user);
    if (!movieFile(path, rel, full) || !aviplayer_open(&b->movie, full)) {
        b->missingMovies++;
        bootNote("movie missing");
        logLine("movie missing %s", path);
        return 0;
    }

    // Filled across the top screen rather than drawn in the plane: the EA
    // logo stretched from 4:3 like every menu, the letterboxed intro trimmed
    // a little at the sides and stretched (uirender.c, draw_bitmap).
    b->movieTexHash = moviePlaneTexture(b);
    uirender_override_texture(b->ui, b->movieTexHash, &b->movie.tex,
                              in->width, in->height, true);
    b->moviePlaying = true;
    b->movieAttached = true;
    // gameflow.c already traces the full path; the status line just says it
    // is running, and bootNote's buffer is smaller than a path anyway.
    bootNote("movie playing");
    logLine("movie open %s %lux%lu %lu frames @ %.3f fps, sound %s at %lu Hz "
            "-> texture %08lx", rel, (unsigned long)in->width,
            (unsigned long)in->height, (unsigned long)in->frames,
            (double)in->rate / (double)in->scale,
            b->movie.sound ? "on" : "off", (unsigned long)avisound_rate_hz(),
            (unsigned long)b->movieTexHash);
    return 1;
}

// DriveMovie (0x0016a060) returns 1 when the movie is finished. The movie
// keeps its own clock, the console's tick, so the picture stays with the
// sound however long a pass of the loop takes.
static int hookMovieDrive(void* user)
{
    Boot* b = (Boot*)user;
    if (!b->moviePlaying) return 1;
    return aviplayer_drive(&b->movie) ? 1 : 0;
}

// The menus' movie, MOVIES\*.AVI, into PANELMOVIE: InitFile (0x00237ad8)
// for FlailerScreenList. It is drawn in its plane at its own size, as any
// bitmap is, and not before its first frame: RenderFlailerBitmap draws a
// movie texture from the player's planes, empty until Update fills them. A
// file that is not there is tried again every frame by UpdateMovie, so it
// is logged and counted the first time only.
#define PANELMOVIE_TEXTURE 0xc3f0caefu

static int hookPanelMovieOpen(void* user, const char* path)
{
    Boot* b = (Boot*)user;
    char  rel[GAMEDATA_MAX_PATH], full[GAMEDATA_MAX_PATH];

    hookMovieClose(user);
    if (!movieFile(path, rel, full) || !aviplayer_init(&b->movie, full)) {
        if (b->panelMissing != path) {
            b->panelMissing = path;
            b->missingMovies++;
            bootNote("movie missing");
            logLine("panel movie missing %s", path);
        }
        return 0;
    }
    b->panelMissing = NULL;
    b->movieTexHash = PANELMOVIE_TEXTURE;
    b->moviePlaying = true;
    b->movieAttached = false;
    logLine("panel movie open %s %lux%lu %lu frames @ %.3f fps", rel,
            (unsigned long)b->movie.movie.info.width,
            (unsigned long)b->movie.movie.info.height,
            (unsigned long)b->movie.movie.info.frames,
            (double)b->movie.movie.info.rate / (double)b->movie.movie.info.scale);
    return 1;
}

// Update (0x002380a8): 0 once the movie is over, or with nothing open.
static int hookPanelMovieUpdate(void* user)
{
    Boot* b = (Boot*)user;
    bool  more;
    if (!b->moviePlaying) return 0;
    more = aviplayer_update(&b->movie);
    if (!b->movieAttached && b->movie.movie.shown >= 0) {
        uirender_override_texture(b->ui, b->movieTexHash, &b->movie.tex,
                                  (uint16_t)b->movie.movie.info.width,
                                  (uint16_t)b->movie.movie.info.height, false);
        b->movieAttached = true;
    }
    return more ? 1 : 0;
}

static int hookInGame(void* user)
{
    (void)user;
    return InGameFlag != 0;
}

// LoadResourceFile. The bundles are read synchronously -- the frontend's
// straight after LoadGlobalChunks' frame, in main() -- so a load has always
// landed by the time the flow asks. What stays asynchronous is the callback:
// the original's runs from ServiceResourceLoading at the end of the frame
// that finished it, after eDisplayFrame, and a callback that asks for more
// hears back a frame later. bootServiceLoads is that, after C3D_FrameEnd.
static void bootQueue(Boot* b, const char* what, BGameFlowDone done)
{
    if (!done) return;
    if (b->numPending >= BOOT_MAX_LOADS) {
        logLine("load queue full, %s dropped", what);
        return;
    }
    b->pending[b->numPending].what = what;
    b->pending[b->numPending].done = done;
    b->numPending++;
}

static void hookLoadResource(void* user, const char* path, BGameFlowDone done)
{
    // FRONTB, which the UI has read already: its chunks go through the
    // LoaderTable here, as the ResourceFile's would, before the callback.
    if (strcmp(path, "FRONTEND\\FRONTB.LZC") == 0 && g_frontBundle) {
        bool ok = frontres_load(g_frontBundle->data, g_frontBundle->len);
        logLine("frontres: FRONTB %s", ok ? "loaded" : "not loaded, no room");
    }
    bootQueue((Boot*)user, path, done);
}

// LoadSoundRegions. fesound_init loaded the frontend's banks at boot;
// LoadSoundRegionsFrontEnd (0x001ae9a0) starts with the jukebox's list, the
// menu's.
static void hookLoadSoundRegions(void* user, BGameFlowDone done)
{
    jb_music_set_selection(&g_jukebox, Fred.AudioOptionsScreenData,
                           JB_CAT_MENU_MUSIC);
    bootQueue((Boot*)user, "sound regions", done);
}

// The callbacks due this frame. Ones they queue wait for the next.
static void bootServiceLoads(Boot* b)
{
    int n = b->numPending;
    struct { const char* what; BGameFlowDone done; } run[BOOT_MAX_LOADS];
    memcpy(run, b->pending, sizeof(run[0]) * (size_t)n);
    b->numPending = 0;
    for (int i = 0; i < n; i++) {
        logLine("loaded %s", run[i].what);
        run[i].done(&g_flow);
    }
}

static void hookSetLanguage(void* user, int language)
{
    Boot* b = (Boot*)user;
    char  path[GAMEDATA_MAX_PATH];
    if (language < 0 || language >= NUM_LANGUAGES) return;
    if (!gamedata_path(kLanguages[language], path, sizeof(path))) return;
    uirender_set_language(b->ui, path);
}

// The speech bank is the in-game commentary's, and there is no in-game yet;
// the flow keeps the loaded flag, so these only say so.
static void hookLoadSpeech(void* user, int language)
{
    (void)user;
    logLine("speech bank %d (not ported)", language);
}

static void hookUnloadSpeech(void* user) { (void)user; }

// The French LOADING art, LOADING_FR and NFS_LOGO_ALPHA_FR in place of the
// English pair. Not in any bundle the port reads yet.
static void hookSwapLogoArt(void* user, int french)
{
    (void)user;
    logLine("logo art %s (not ported)", french ? "french" : "english");
}

// ------------------------------------------------------- the memory card
//
// cDBFileSys, on the SD card (memcard.h): the one card, always there and
// formatted, with its files in sdmc:/NFSHP2/SAVES -- made the first time
// one is saved, so a card that has never saved has no folder and no file.
// Every job finishes on the first Service after it starts, as memcard.c's
// blank card's do; the loader's own two-second waits are what the player
// sees.

#define SAVES_DIR "sdmc:/NFSHP2/SAVES"

typedef struct {
    BMemcardFileSys base;
    int             pending;    // the job, or BMC_FS_IDLE
    BMemcardDone    done;
    void*           param;
    char            name[32];   // SetFileData's
    void*           data;
    int             size;
} SdCard;

static int sdPath(const SdCard* c, char* out, size_t cap)
{
    return snprintf(out, cap, SAVES_DIR "/%s", c->name) < (int)cap;
}

// The whole file, or nothing: a short one is a failed load, as a card that
// came out mid-read would be.
static int sdLoad(SdCard* c)
{
    char  path[96];
    FILE* f;
    long  got;
    if (!sdPath(c, path, sizeof(path))) return BMC_ERROR;
    f = fopen(path, "rb");
    if (!f) return BMC_FILE_NOT_FOUND;
    got = c->data && c->size > 0 ? (long)fread(c->data, 1, (size_t)c->size, f)
                                 : 0;
    fclose(f);
    if (got != c->size) {
        logLine("memcard: %s is %ld bytes, not %d", path, got, c->size);
        return BMC_ERROR;
    }
    logLine("memcard: loaded %s", path);
    return BMC_OK;
}

static int sdSave(SdCard* c)
{
    char  path[96];
    FILE* f;
    long  put;
    if (!sdPath(c, path, sizeof(path)) || !c->data || c->size <= 0)
        return BMC_ERROR;
    mkdir("sdmc:/NFSHP2", 0777);
    mkdir(SAVES_DIR, 0777);
    f = fopen(path, "wb");
    if (!f) return BMC_ERROR;
    put = (long)fwrite(c->data, 1, (size_t)c->size, f);
    if (fclose(f) != 0 || put != c->size) {
        logLine("memcard: could not write %s", path);
        return BMC_ERROR;
    }
    logLine("memcard: saved %s", path);
    return BMC_OK;
}

static void sdDestroy(BMemcardFileSys* fs) { free(fs); }

static void sdService(BMemcardFileSys* fs, int port, int slot)
{
    SdCard*      c = (SdCard*)fs;
    BMemcardDone done;
    struct stat  st;
    char         path[96];
    (void)port;
    (void)slot;
    if (c->pending == BMC_FS_IDLE) return;
    switch (c->pending) {
        case BMC_FS_LOAD:
            fs->lastError = sdLoad(c);
            break;
        case BMC_FS_SAVE:
            fs->lastError = sdSave(c);
            break;
        case BMC_FS_CHECK_EXISTENCE:
            fs->lastError = sdPath(c, path, sizeof(path))
                                    && stat(path, &st) == 0
                                ? BMC_OK
                                : BMC_FILE_NOT_FOUND;
            break;
        default:            // VERIFY, and the rest the boot never asks for
            fs->lastError = BMC_OK;
            break;
    }
    c->pending = BMC_FS_IDLE;
    done       = c->done;
    c->done    = NULL;
    if (done) done(c->param);
}

static void sdSetFileData(BMemcardFileSys* fs, const char* name, void* data,
                          int size)
{
    SdCard* c = (SdCard*)fs;
    snprintf(c->name, sizeof(c->name), "%s", name ? name : "");
    c->data = data;
    c->size = size;
}

// CalculateFreeSpaceRequired (0x0012d1a0), as the blank card has it.
static int sdCalcFree(BMemcardFileSys* fs, int size)
{
    (void)fs;
    return (size + 1023) / 1024 + 5;
}

// The SD card's free space in KB, or an empty 8 MB card's if the archive
// will not say.
static int sdFreeSpace(BMemcardFileSys* fs)
{
    FS_ArchiveResource res;
    uint64_t           kb;
    (void)fs;
    if (R_FAILED(FSUSER_GetSdmcArchiveResource(&res))) return 8192;
    kb = (uint64_t)res.freeClusters * res.clusterSize / 1024u;
    return kb > 0x7fffffffu ? 0x7fffffff : (int)kb;
}

static int sdSetState(BMemcardFileSys* fs, int state, BMemcardDone done,
                      void* param)
{
    SdCard* c = (SdCard*)fs;
    if (c->pending != BMC_FS_IDLE || state <= BMC_FS_IDLE
        || state >= BMC_FS_WAITING)
        return 0;
    c->pending = state;
    c->done    = done;
    c->param   = param;
    return 1;
}

static const BMemcardFileSysVtbl kSdCard = {
    sdDestroy, sdService, sdSetFileData, sdCalcFree, sdFreeSpace, sdSetState,
};

static BMemcardFileSys* hookNewFileSys(void* user)
{
    SdCard* c = (SdCard*)calloc(1, sizeof(*c));
    (void)user;
    if (!c) return NULL;
    c->base.vt        = &kSdCard;
    c->base.lastError = BMC_OK;
    return &c->base;
}

// OverwriteFred's calls after the copy: the audio options' ApplySettings
// (0x001ef120) so far.
static void hookFredLoaded(void* user, uint8_t* fred)
{
    (void)user;
    int mode = jb_audio_apply(&g_jukebox, fred + FRED_AUDIO_OPTIONS);
    g_audioMode = mode;             // sound::SetAudioMode
    logLine("audio options loaded: mode %d", mode);
}

// FrontendDatabase::InitWithDefaults' calls out (fred.h): the audio
// options' defaults (0x001ef1c8), which want the jukebox's tunes, and
// GetTranslatedString (0x0021e560) for the two players' default names.
static void fredAudioDefaults(uint8_t* ao)
{
    jb_audio_init_with_defaults(&g_jukebox, ao, g_audioMode);
}

static const char* fredTranslate(int32_t id)
{
    static char text[64];
    if (!g_boot.ui || !g_boot.ui->hasLang) return NULL;
    if (langtab_copy(&g_boot.ui->lang, id, text, sizeof(text)) == 0)
        return NULL;
    return text;
}

// sceCdReadClock, for the NIS overlay's date and time (hudnis.c): the
// 3DS's clock in the drive's BCD. The 3DS keeps local time, so time() is
// the wall clock already and gmtime_r reads it as it stands.
static uint8_t toBcd(int v)
{
    return (uint8_t)(((v / 10) << 4) | (v % 10));
}

static int32_t cdReadClock(NisClock* c)
{
    time_t now = time(NULL);
    struct tm t;
    if (gmtime_r(&now, &t) == NULL) return 0;
    c->stat = 0;
    c->second = toBcd(t.tm_sec);
    c->minute = toBcd(t.tm_min);
    c->hour = toBcd(t.tm_hour);
    c->pad = 0;
    c->day = toBcd(t.tm_mday);
    c->month = toBcd(t.tm_mon + 1);
    c->year = toBcd(t.tm_year % 100);
    return 1;
}

// RaceParameters::InitWithDefaults, InitWithDefaults and
// MakeChallengeCarsAvailable, where the flow calls them (gameflow.h).
static void logFredDefaults(void)
{
    const FrontendPlayerInfo* p = Fred.FrontendPlayers;
    logLine("fred defaults: %s (%s), %s (%s), car %d / %d",
            p[0].mPlayerSettings.PlayerName, p[0].mCharacterInfo.CharacterName,
            p[1].mPlayerSettings.PlayerName, p[1].mCharacterInfo.CharacterName,
            (int)p[0].RideInfoByGameMode[0].Type,
            (int)p[1].RideInfoByGameMode[0].Type);
}

static void hookRaceDefaults(void* user)
{
    (void)user;
    race_parameters_init_with_defaults(&TheRaceParameters);
}

static void hookFrontendDefaults(void* user)
{
    (void)user;
    fred_init_with_defaults(&Fred);
    logFredDefaults();
}

static void hookChallengeCars(void* user)
{
    (void)user;
    fred_make_challenge_cars_available(&Fred);
}

// StartRace's game flow (fredrace.h): CurrentGameFlowState, and
// ChangeGameFlow(state, NONE) on the flow. The race events' seams stay
// NULL; no game type the port reaches uses them yet.
static int32_t fredFlowState(void)
{
    return g_flow.current;
}

static void fredChangeFlow(int32_t state)
{
    bgf_change_state(&g_flow, state, BGF_NONE);
}

static void logConfigLine(const char* line)
{
    logLine("%s", line);
}

// The port's config file (configitems.h), in place of LoadConfigItems'
// joylog: its words, and SkipFE as R held sets it. No file, no change.
static void readConfigItems(void)
{
    static char text[4096];
    FILE* f = fopen(CONFIG_ITEMS_FILE, "rb");
    size_t n;
    int set;

    if (f == NULL)
        return;
    n = fread(text, 1, sizeof text - 1, f);
    fclose(f);
    text[n] = '\0';
    set = config_items_apply_text(text, &g_flow.skipFE, logConfigLine);
    logLine("config: %d items from %s", set, CONFIG_ITEMS_FILE);
    if (g_flow.skipFE)
        logLine("SkipFE: on");
}

// What StartRace leaves in TheRaceParameters: the race, then a line a
// driver.
static void logRaceStart(void)
{
    const RaceParameters* rp = &TheRaceParameters;
    logLine("race start: track %d, %d laps, race type %d, %d player, "
            "%d AI, %d cops, %d drivers",
            (int)rp->TrackNumber, (int)rp->NumLapsInRace, (int)rp->RaceType,
            (int)rp->NumPlayerCars, (int)rp->NumAICars, (int)rp->nMaxCops,
            (int)rp->NumDriverInfo);
    for (int32_t i = 0; i < rp->NumDriverInfo; i++) {
        const DriverInfo* d = race_parameters_get_driver_info(i);
        logLine("  driver %d: type %d, car %d skin %d, character %d, "
                "skill %d, grid %d",
                (int)d->UniqueDriverNumber, (int)d->TheDriverType,
                (int)d->CurrentRideInfo.Type,
                (int)d->CurrentRideInfo.SkinNumber,
                (int)d->CharacterNumber, (int)d->SkillLevel,
                (int)d->StartingPosition);
    }
}

static void hookTrace(void* user, const char* line)
{
    (void)user;
    // Each state's Begin carries the malloc heap's use: the track's bundles
    // are the largest blocks the port asks for, and a bMalloc that fails
    // aborts.
    if (strncmp(line, "begin ", 6) == 0) {
        struct mallinfo mi = mallinfo();
        logLine("flow %s (heap: %lu KB used, %lu KB free; linear %lu KB free)",
                line, (unsigned long)mi.uordblks / 1024,
                (unsigned long)(g_heapInfo.heapGot - mi.uordblks) / 1024,
                (unsigned long)linearSpaceFree() / 1024);
        return;
    }
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
        // You're The Cop resyncs every tick off Players, as retail does, so
        // only a call that differs from the last one is worth a line.
        {
            static uint32_t lastItem;
            static int      lastMode = -1;
            if (item != lastItem || (int)mode != lastMode)
                logLine("gray item=%08lx mode=%d", (unsigned long)item,
                        (int)mode);
            lastItem = item;
            lastMode = (int)mode;
        }
        return;
    }
}

// The flow's GrayMenuItem, for the language screen: the same call.
static void hookFlowGrayMenuItem(void* user, uint32_t screen, uint32_t item,
                                 int mode)
{
    hookGrayMenuItem(user, screen, item, (BScrGrayMode)mode);
}

// GetActiveMenuItem (0x0016d3f0): the highlighted item's hash, 0 with no menu.
static uint32_t hookActiveMenuItem(void* user)
{
    Boot*            b = (Boot*)user;
    const BMenuItem* mi;
    if (!b->hasMenu) return 0;
    mi = bmenu_current(&b->menu);
    return mi ? mi->itemHash : 0;
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

// CopyFlailerText (0x0013ec18): the whole of src but its names over dst --
// its position, scale, Z, visibility, LanguageID and string (bui.h). The
// bloom is a copy of a menu label, so it starts where the label is: on the
// main menu ANIMATING_MENUITEM is authored off the bottom of the screen, at
// y 534, and only the copy brings it up.
static void hookAnimCopyText(void* user, uint32_t screen, uint32_t dst,
                             uint32_t src)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = animScreen(b, screen, &ui);
    int32_t    si, di;

    if (!s || !ui) return;
    si = bui_find_object(ui, s, src, BUI_TYPE_TEXT);
    di = bui_find_object(ui, s, dst, BUI_TYPE_TEXT);
    if (si < 0 || di < 0) return;
    bui_copy_text(ui, (uint32_t)di, (uint32_t)si);
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

// ------------------------------------------------------------- EA TRAX

// FlailerScreenList's tNewSongMonitor (songmon.h), and what it asks: the
// jukebox, RealTimer, and GLOBALB's CHYRON screen.
static BSongMonitor g_songMonitor;

static int smIsPlaying(void* user)
{
    (void)user;
    return jb_music_is_playing(&g_jukebox);
}

static uint32_t smCurrentTrack(void* user)
{
    (void)user;
    return jb_current_track(&g_jukebox);
}

static const char* smTrack(void* user, int field)
{
    (void)user;
    return jb_track_string(&g_jukebox, -1, -1, field);
}

static uint32_t smRealTimer(void* user)
{
    (void)user;
    return g_flow.realTimer;
}

static int32_t smWidth(void* user, uint32_t screen, uint32_t object)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0) return 0;
    return uirender_object_width(((Boot*)user)->ui, ui, (uint32_t)idx);
}

// FlailerGetScale (0x001444e8): the pair left alone for no such object.
static void smGetScale(void* user, uint32_t screen, uint32_t object,
                       float* sx, float* sy)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    *sx = o.scaleX;
    *sy = o.scaleY;
}

static void smSetScaleX(void* user, uint32_t screen, uint32_t object,
                        float sx)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    bui_set_object_scale(ui, (uint32_t)idx, sx, o.scaleY);
}

static const BSongMonitorHooks kSongMonitorHooks = {
    &g_boot, smIsPlaying, smCurrentTrack, smTrack, smRealTimer,
    hookSetScreenVisible, hookAnimPrintText, smWidth, smGetScale,
    smSetScaleX,
};

static void hookSongMonitor(void* user)
{
    (void)user;
    int printed = g_songMonitor.printed;
    bsm_update(&g_songMonitor);
    if (!printed && g_songMonitor.printed) {
        const char* artist = smTrack(NULL, JB_TRACK_ARTIST);
        const char* name   = smTrack(NULL, JB_TRACK_NAME);
        logLine("ea trax: %s / %s", artist ? artist : "(null)",
                name ? name : "(null)");
    }
}

// The four reads tPopupMenu makes (banim.h). A handle is bui.c's object
// index, which is what bui_next_in_group walks on.
static int32_t hookAnimNextInGroup(void* user, uint32_t screen, uint32_t group,
                                   int type, int32_t after, uint32_t* hash)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = animScreen(b, screen, &ui);
    BUIObject  o;
    int32_t    idx;
    *hash = 0;
    if (!s || !ui) return -1;
    idx = bui_next_in_group(ui, s, group, type, after);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return -1;
    *hash = o.nameHash;
    return idx;
}

static int hookAnimTextMaxChars(void* user, uint32_t screen, uint32_t object)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_TEXT, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return 0;
    return (int)o.maxChars;
}

static float hookAnimTextScaledHeight(void* user, uint32_t screen,
                                      uint32_t object)
{
    Boot*   b  = (Boot*)user;
    BUI*    ui = NULL;
    float   w = 0.0f, h = 0.0f;
    int32_t idx = animFind(b, screen, object, BUI_TYPE_TEXT, &ui);
    if (idx >= 0) uirender_text_extent(b->ui, ui, (uint32_t)idx, &w, &h);
    return h;
}

static uint32_t hookAnimGetColor(void* user, uint32_t screen, uint32_t object)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return 0;
    return o.color;
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

// FlailerScreenList::StartMovie and StopMovie, for the Mode Selects and
// Options: the flow's, which the main menu calls too.
static void hookScreenMovie(void* user, const char* path)
{
    (void)user;
    bgf_start_movie(&g_flow, path);
}

static void hookScreenMovieStop(void* user)
{
    (void)user;
    bgf_stop_movie(&g_flow);
}

// ------------------------------------------------ the race setup screens
//
// BSetupHooks, for bsetup.c: the Flailer calls You're The Cop makes under
// retail's names, on the same object layer as the animation kit's. The
// arrows find their two bitmaps once, as bitmaps, so the three chunk calls
// look them up the same way.

static void hookSetupBitmapAlpha(void* user, uint32_t screen, uint32_t object,
                                 int alpha)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_BITMAP, &ui);
    if (idx >= 0) bui_set_object_alpha(ui, (uint32_t)idx, -1, alpha);
}

// FlailerObjectChunk::SetCenterY (0x00140930): the top at y less half of
// GetHeightFloat, X kept.
static void hookSetupBitmapCenterY(void* user, uint32_t screen,
                                   uint32_t object, float y)
{
    Boot*     b = (Boot*)user;
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind(b, screen, object, BUI_TYPE_BITMAP, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    bui_set_object_pos(ui, (uint32_t)idx, o.x,
                       y - uirender_object_height(b->ui, ui, (uint32_t)idx)
                               * 0.5f);
}

static void hookSetupBitmapVisible(void* user, uint32_t screen,
                                   uint32_t object, int visible)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_BITMAP, &ui);
    if (idx >= 0)
        bui_set_object_visible(ui, (uint32_t)idx,
                               visible ? BUI_VISIBLE : BUI_INVISIBLE);
}

// FlailerGetBoundingBox (0x00144280): the top left cut to ints
// (FlailerGetTopLeftPosition, 0x001440d8), then GetWidth and GetHeight
// (0x00140588, 0x001405e0) added. A missing object leaves the box alone.
static void hookSetupBoundingBox(void* user, uint32_t screen, uint32_t object,
                                 int32_t box[4])
{
    Boot*     b = (Boot*)user;
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind(b, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    box[0] = (int32_t)o.x;
    box[1] = (int32_t)o.y;
    box[2] = box[0] + uirender_object_width(b->ui, ui, (uint32_t)idx);
    box[3] = box[1]
             + (int32_t)uirender_object_height(b->ui, ui, (uint32_t)idx);
}

// FlailerGetCenterY (0x00144860), through FlailerGetCenter (0x001447e0):
// the box's top plus half its height, halved toward 0. Retail's box is
// stack garbage for a missing object; this one is 0.
static int32_t hookSetupCenterY(void* user, uint32_t screen, uint32_t object)
{
    int32_t box[4] = {0, 0, 0, 0};
    hookSetupBoundingBox(user, screen, object, box);
    return box[1] + (box[3] - box[1]) / 2;
}

// FlailerSetTopLeftY (0x00144458), the int one: SetTopLeftY((float)y).
static void hookSetupTopLeftY(void* user, uint32_t screen, uint32_t object,
                              int32_t y)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    bui_set_object_pos(ui, (uint32_t)idx, o.x, (float)y);
}

static float hookSetupTopLeftX(void* user, uint32_t screen, uint32_t object)
{
    float x, y;
    hookAnimGetTopLeft(user, screen, object, &x, &y);
    return x;
}

// FlailerGetTopLeftY (0x00144168): 0 for a missing object.
static float hookSetupGetTopLeftY(void* user, uint32_t screen,
                                  uint32_t object)
{
    float x, y;
    hookAnimGetTopLeft(user, screen, object, &x, &y);
    return y;
}

// FlailerObjectChunk::SetTopLeftY (0x00140a48), the float one: X kept.
static void hookSetupObjectTopLeftY(void* user, uint32_t screen,
                                    uint32_t object, float y)
{
    BUI*      ui;
    BUIObject o;
    int32_t   idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx < 0 || !bui_object(ui, (uint32_t)idx, &o)) return;
    bui_set_object_pos(ui, (uint32_t)idx, o.x, y);
}

// FlailerSetClipToPoly (0x00144358).
static void hookSetupClipToPoly(void* user, uint32_t screen, uint32_t object,
                                uint32_t poly)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx >= 0) bui_set_object_clip(ui, (uint32_t)idx, poly);
}

// FlailerSetAlpha (0x001448e8), through ObjectChunk::SetAlpha (0x001406d8):
// a text object's alpha, or all four of a bitmap's corners.
static void hookSetupAlpha(void* user, uint32_t screen, uint32_t object,
                           int alpha)
{
    BUI*    ui;
    int32_t idx = animFind((Boot*)user, screen, object, BUI_TYPE_NONE, &ui);
    if (idx >= 0) bui_set_object_alpha(ui, (uint32_t)idx, -1, alpha);
}

// GrayMenuItem(char*, int, int, int) (0x0016d2a8) finds its screen by name;
// the setup screens pass their own, which is the one the flow is on.
static void hookSetupGrayNamed(void* user, const char* name, uint32_t screen,
                               uint32_t item, int mode)
{
    (void)name;
    hookGrayMenuItem(user, screen, item, (BScrGrayMode)mode);
}

// IsJoystickPluggedIn (0x001542f0). The 3DS is one player's: port 0 is the
// console's own buttons, and there is no second pad to plug in.
static int hookSetupJoystickPluggedIn(void* user, int port)
{
    (void)user;
    return port == 0;
}

// SetHelpOverride (0x0016d448). The help menu (tHelpMenu) is not ported;
// the table is logged so the screen's lines can be checked.
static void hookSetupHelpOverride(void* user, const int32_t* lines)
{
    (void)user;
    if (!lines) {
        logLine("help override off");
        return;
    }
    logLine("help override %ld %ld %ld %ld", (long)lines[0],
            lines[0] ? (long)lines[1] : 0L,
            lines[0] && lines[1] ? (long)lines[2] : 0L,
            lines[0] && lines[1] && lines[2] ? (long)lines[3] : 0L);
}

// The three FrontendDatabase calls car select starts with. The first is
// fred.c's; the other two come with car select.
static void hookSetupChallengeCars(void* user)
{
    (void)user;
    fred_make_challenge_cars_available(&Fred);
}

// 0x00183ec0, which jumps to car select's preload (bcarsel.c).
static void hookSetupPreloadCars(void* user)
{
    (void)user;
    bcarsel_preload();
}

static void hookSetupRaceAfterSetup(void* user)
{
    (void)user;
    logLine("fred SetupRaceParametersAfterRaceSetup (not ported)");
}

static void hookSetupRaceParameters(void* user, int32_t numPlayerCars,
                                    int32_t nfsRaceMode)
{
    (void)user;
    RaceParametersNumPlayerCars = numPlayerCars;
    RaceParametersNFSRaceMode   = nfsRaceMode;
    logLine("race parameters cars=%ld mode=%ld", (long)numPlayerCars,
            (long)nfsRaceMode);
}

// sound::jukebox::Start and Stop (0x001aeab0, 0x001aec90).
static void hookJukebox(void* user, int start)
{
    (void)user;
    if (start) {
        jb_music_start(&g_jukebox, Fred.AudioOptionsScreenData, 1);
    } else {
        jb_music_stop(&g_jukebox);
    }
    logLine("jukebox %s: %s", start ? "start" : "stop",
            jb_is_cartridge_loaded(&g_jukebox.jukebox)
                ? jb_tune_name(&g_jukebox.jukebox,
                               g_jukebox.jukebox.curCatNum,
                               g_jukebox.jukebox.curTuneNum)
                : "no cartridge");
}

// TheEasterEggs' Start and Stop, NewMainMenu's. The 78 codes it listens for
// are not ported, so the pad is not handed to it: the log says when retail
// would have.
static void hookEasterEggs(void* user, int start)
{
    (void)user;
    logLine("easter eggs %s", start ? "start" : "stop");
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

// The loop the CPU's clock is read by (step 13b-3): CLOCK_LOOPS turns of a
// subs and a bne, timed by the system tick, which counts 268 MHz at either
// clock. Only the ratio between two runs means anything.
#define CLOCK_LOOPS 2000000u

static u32 clockLoopTicks(void)
{
    u32 n = CLOCK_LOOPS;
    u64 t0 = svcGetSystemTick();

    __asm__ volatile("1: subs %0, %0, #1\n\tbne 1b" : "+r"(n) : : "cc");
    return (u32)(svcGetSystemTick() - t0);
}

static double clockTicksMs(u32 ticks)
{
    return (double)ticks * 1000.0 / SYSCLOCK_ARM11;
}

// Whether the speedup took (step 13b-3). libctru's osSetSpeedupEnable goes
// through ptm:sysm, so its opening is logged. On a New 3DS with it, the
// loop runs as launched, then with the speedup off and back on: the last
// two's ratio is the clock's, about 3 when the speedup takes, and the
// first says which the launch gave. The speedup is left on, as
// initPlatformPerf left it.
static void logClock(bool isNew3DS)
{
    Result sysm = ptmSysmInit();
    u32    launched, slow, fast;

    if (R_SUCCEEDED(sysm)) ptmSysmExit();
    launched = clockLoopTicks();
    if (!isNew3DS || R_FAILED(sysm)) {
        logPrintf("clock: ptm:sysm %08lx; %u loops in %.2f ms as launched\n",
                  (unsigned long)sysm, CLOCK_LOOPS, clockTicksMs(launched));
        return;
    }
    osSetSpeedupEnable(false);
    slow = clockLoopTicks();
    osSetSpeedupEnable(true);
    fast = clockLoopTicks();
    logPrintf("clock: ptm:sysm open; %u loops in %.2f ms as launched, "
              "%.2f ms without the speedup, %.2f ms with it (x%.2f)\n",
              CLOCK_LOOPS, clockTicksMs(launched), clockTicksMs(slow),
              clockTicksMs(fast), fast ? (double)slow / fast : 0.0);
}

// What the console gave (step 13b-2): its model, whether it is a New 3DS
// and so asked for the speedup, the memory type, the grant, the heap and
// core 1's limit. Then the clock (logClock).
static void logConsole(void)
{
    static const char* const kModels[] = {
        "3DS", "3DS XL", "New 3DS", "2DS", "New 3DS XL", "New 2DS XL",
    };
    u8   model = 0xff;
    bool isNew3DS = false;
    u32  core1 = 0;
    bool cfg = R_SUCCEEDED(cfguInit());

    if (cfg) {
        if (R_FAILED(CFGU_GetSystemModel(&model))) model = 0xff;
        cfguExit();
    }
    (void)APT_CheckNew3DS(&isNew3DS);
    if (R_FAILED(APT_GetAppCpuTimeLimit(&core1))) core1 = 0;
    logPrintf("console: %s (model %d), %s, speedup %s, memory type %lu, "
              "grant %luKB, heap %luKB, linear %luKB, core 1 limit %lu%%\n",
              model < 6 ? kModels[model] : "unknown", (int)model,
              isNew3DS ? "New 3DS" : "Old 3DS", isNew3DS ? "asked" : "not asked",
              (unsigned long)osGetApplicationMemType(),
              (unsigned long)(g_heapInfo.commitMax / 1024),
              (unsigned long)(g_heapInfo.heapGot / 1024),
              (unsigned long)(g_heapInfo.linearGot / 1024),
              (unsigned long)core1);
    logClock(isNew3DS);
}

static void initPlatformPerf(void)
{
    bool isNew3DS = false;
    Result n3dsRes = APT_CheckNew3DS(&isNew3DS);
    if (R_SUCCEEDED(n3dsRes) && isNew3DS) {
        osSetSpeedupEnable(true);
    }
    APT_SetAppCpuTimeLimit(80);
}

// Each bundle with a Flailer chunk is also LoaderFlailerChunk's project,
// on the tail of the list, in the order retail loads them: GLOBALB at
// boot, FRONTB with the frontend, INGAMEB with the race (flailer.h). Three
// screens are in both FRONTB and INGAMEB, and the order decides which one
// a find gets.
static UIBundle* addBundle(UIRenderer* ui, const char* rel)
{
    char path[GAMEDATA_MAX_PATH];
    if (!gamedata_path(rel, path, sizeof(path))) return NULL;
    if (!uirender_add_bundle(ui, path)) {
        logPrintf("  missing %s\n", rel);
        return NULL;
    }
    UIBundle* b = &ui->bundles[ui->numBundles - 1];
    if (b->hasUI && !flailer_add_project(&b->ui))
        logPrintf("  %s: not a retail Flailer project\n", rel);
    return b;
}

// The renderer's answers to the Flailer runtime's size questions
// (flailer.h): the text's GetScaledWidth and GetScaledHeight, by the
// object's place in its bundle, and a bitmap's TextureInfo size.
static float flailerTextWidth(struct FlailerTextChunk* t)
{
    BUI*     ui  = NULL;
    uint32_t idx = 0;
    if (!flailer_object_index(&t->Object, &ui, &idx)) return 0.0f;
    return uirender_text_scaled_width(g_boot.ui, ui, idx);
}

static float flailerTextHeight(struct FlailerTextChunk* t)
{
    BUI*     ui  = NULL;
    uint32_t idx = 0;
    if (!flailer_object_index(&t->Object, &ui, &idx)) return 0.0f;
    return uirender_object_height(g_boot.ui, ui, idx);
}

static bool flailerTextureSize(struct FlailerBitmapChunk* b, int32_t* w,
                               int32_t* h)
{
    return uirender_texture_size(g_boot.ui, b->TextureHash, w, h);
}

// The countdown's read of an object's Visibility byte (rcstates.h).
static int32_t flailerObjectVisibility(struct FlailerObjectChunk* o)
{
    return o->Visibility;
}

// The resource system (resource.h) behind the seams that reach it: the car
// loader's LoadResourceFile, ServiceResourceLoading and UnloadResourceFile,
// and the two FindResourceFile, the track flow's and the race
// coordinator's.
static void* resLoadFile(const char* name, int type, int flags,
                         CarLoaderDoneFn done, intptr_t param)
{
    return load_resource_file(name, type, flags, done, param);
}

static void resService(void)
{
    (void)service_resource_loading();
}

static void resUnloadFile(void* file)
{
    unload_resource_file((ResourceFile*)file);
    trackview_forget_later(&g_feView);
}

// CarLoader's UnloadTexturesFromFile: the skins' pixels go, and another
// car's may come in where they were.
static void unloadTexturesFromFile(TexturePack* p, uint32_t* hashes, int n)
{
    texturepack_unload_textures_from_file(p, hashes, n);
    trackview_forget_later(&g_feView);
}

static void* resFindByType(int type)
{
    return find_resource_file_by_type(type);
}

static void* resFindByName(const char* name)
{
    return find_resource_file(name);
}

// LoadGlobalChunks' streamed packs (0x001683a0 and 0x0016856c): a
// TexturePack with no file name, its table read from `file`, and none of
// its pixels until they are asked for (texturestream.h).
static TexturePack* newStreamedPack(const char* var, const char* name,
                                    const char* file)
{
    TexturePack* p = texturepack_construct(
        (TexturePack*)bMalloc((int)sizeof(TexturePack), var, 0, 16), name,
        NULL);
    texturepack_load_texture_table_from_file(p, file);
    return p;
}

// LoadGlobalChunks' two waits (0x00168458, 0x001685f8): the resource
// system serviced, and with it the queued reads, until nothing is loading
// and DynTextures is reading nothing.
static void waitForGlobalChunks(void)
{
    while (!is_resource_loading_complete()
           || pDynamicTexturePack->CurrentLoadingTextureData != NULL)
        (void)service_resource_loading();
}

// eLight.obj's two calls, through eviewmatrix.h's seams.
static void* get_light_material_seam(uint32_t name_hash)
{
    return el_get_light_material(name_hash);
}

static void setup_light_context_seam(eLightContext* lc,
                                     const bMatrix4* local_world,
                                     const bMatrix4* hack,
                                     const bVector4* eye, eView* view)
{
    el_setup_light_context(lc, local_world, hack, eye, view);
}

// LoadGlobalChunks' LoadResourceFile hands every top-level chunk of GLOBALB
// to LoadChunks, slots 2 and 16 among them: LoaderTexturePack, whose pack
// and flipbooks stay on TexturePackList for the whole game -- CARBOTTOM,
// TIRE, WINDOW, the plates and the default texture are its -- and
// LoaderCarInfo (carinfo.c), which points CarTypeInfoArray and
// SkinInfoTable into the bundle and makes the 64 acceleration tables. The
// port offers those slots GLOBALB's chunks in the file's order, cars
// before skins as on the disc, and the UI reads the rest as it is. The
// bundle stays resident, as the records and the pixels must.
static void loadGlobalCarInfo(UIBundle* b)
{
    uint8_t* c;
    uint8_t* end;
    int taken = 0;
    int packs = 0;

    if (!b) return;
    c = b->data;
    end = b->data + b->len;
    while (end - c >= 8) {
        uint32_t size = bchunk_u32(c + 4);
        if (size > (size_t)(end - c) - 8) break;
        packs += loader_texture_pack(c);
        taken += loader_car_info(c);
        // LoaderCharacterInfo's two (characterinfo.h), and LoaderTrackGeometry
        // for the track info table: the only chunk of its seven GLOBALB has.
        // The others fall through to the topology tree's, which is the
        // track bundle's.
        taken += loader_character_info(c);
        if (bchunk_u32(c) == 0x34201) taken += track_loader_geometry(c);
        // LoaderLightList's light materials, GLOBALB's first chunk.
        if (bchunk_u32(c) == 0x3401e) taken += loader_light_list(c);
        // LoaderAcidFX: GLOBALB's 111 emitter datas, then its 112 library
        // emitters onto WorldEffects (acidsys.c).
        taken += loader_acid_fx(c);
        // LoaderDifficultyInfo, GLOBALB's last chunk: TheDifficultyInfo,
        // the AI's skill tables and the catchup knees. Without it every
        // SpeedFactor is 0 and an AI racer's desired speed with it.
        taken += loader_difficulty_info(c);
        c += 8 + size;
    }
    logPrintf("car data: %d chunks, %d skins, %d characters, %d tracks; "
              "%d texture chunks\n",
              taken, (int)NumSkinInfo, (int)NumCharacterInfo,
              (int)HighestTrackNumber, packs);
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

// ------------------------------------------------------------ car select
//
// BCarSelHooks, for bcarsel.c: retail's SelectCarScreen and CarSelector
// (step 16, SC-1). The selector writes its own objects through flailer.c;
// these are the rest -- the language table, the car loader, the popups and
// the flow.

static BCarSel g_carsel;

// GetTranslatedString's answers, into a ring: one Printf can hold two, and
// a popup keeps its message while the screen goes on translating.
#define CARSEL_RING     8
#define CARSEL_RING_LEN 256

static char* carselRing(void)
{
    static char ring[CARSEL_RING][CARSEL_RING_LEN];
    static int  next;
    return ring[next++ % CARSEL_RING];
}

static const char* hookCarSelTranslate(void* user, int32_t id)
{
    Boot* b   = (Boot*)user;
    char* out = carselRing();
    if (!b->ui || !b->ui->hasLang) return NULL;
    if (langtab_copy(&b->ui->lang, id, out, CARSEL_RING_LEN) == 0)
        return NULL;
    return out;
}

// GetTranslatedString(const char*) (0x0021e508): by the English text's
// hash, and the text itself when the table has no row for it.
static const char* hookCarSelTranslateString(void* user, const char* s)
{
    Boot*       b = (Boot*)user;
    const char* t;
    size_t      len = 0;
    char*       out;

    if (!s || !b->ui || !b->ui->hasLang) return s;
    t = langtab_get_english(&b->ui->lang, (int32_t)bchunk_hash(s), &len);
    if (!t) return s;
    out = carselRing();
    if (len >= CARSEL_RING_LEN) len = CARSEL_RING_LEN - 1;
    memcpy(out, t, len);
    out[len] = 0;
    return out;
}

static void hookCarSelSound(void* user, int32_t event)
{
    fesound_play((int)event, user);
}

// StopFrontendSound: the port's frontend sounds are one-shots with nothing
// to stop.
static void hookCarSelStopSound(void* user, int32_t event)
{
    (void)user;
    (void)event;
}

static int hookCarSelSummonPopup(void* user, BPopupConfig* cfg)
{
    (void)user;
    cfg->parent = g_flow.screen;
    return bpopup_summon(&g_flow, cfg);
}

static void hookCarSelDismissPopup(void* user, int popup)
{
    (void)user;
    bpopup_dismiss(&g_flow, popup);
}

static void hookCarSelChangeToScreen(void* user, const char* name, int push)
{
    (void)user;
    bgf_change_to_screen(&g_flow, name, push);
}

// FrontendDatabase::StartRace, for the single race and the championship.
static void hookCarSelStartRace(void* user)
{
    (void)user;
    fred_start_race(&Fred);
    logRaceStart();
}

static void hookCarSelLoaderFrontEnd(void* user)
{
    (void)user;
    TheCarLoader.InFrontEndFlag = 1;
    TheCarLoader.RoundRobinFlag = 1;
}

static void hookCarSelLoaderLoad(void* user, const RideInfo* ri)
{
    (void)user;
    (void)carloader_load(&TheCarLoader, ri);
}

static int hookCarSelLoaderIsLoaded(void* user, const RideInfo* ri)
{
    (void)user;
    return carloader_is_loaded(&TheCarLoader, ri, 0);
}

static void hookCarSelLoaderUnload(void* user, const RideInfo* ri)
{
    (void)user;
    carloader_unload(&TheCarLoader, ri);
}

static void hookCarSelLoaderBeginLoading(void* user)
{
    (void)user;
    carloader_begin_loading(&TheCarLoader, NULL);
}

// RENDER reaches the car select inside the frontend's 3D, where citro2d
// can't draw: the blurb waits there for the Flailer layers to be done.
static struct {
    bool     defer;
    bool     queued;
    uint32_t screen, object, rect;
    char     text[256];             // CarSelector's blurb's size
} g_carselText;

// RenderTextIntoRectangle (0x001451e0): the blurb wrapped into the
// rectangle bitmap's box, from its top left. The disc's text object only
// lends its font; the port draws in FONT_A at the top screen's scale, as
// the bottom panel does.
static void hookCarSelRenderText(void* user, uint32_t screen,
                                 uint32_t object, uint32_t rect,
                                 const char* text, float scale)
{
    Boot*       b = (Boot*)user;
    float       x = 0.0f, y = 0.0f;
    float       sx = 400.0f / 640.0f, sy = 240.0f / 480.0f;
    UIWrapStyle st;

    (void)scale;
    if (g_carselText.defer) {
        g_carselText.queued = true;
        g_carselText.screen = screen;
        g_carselText.object = object;
        g_carselText.rect   = rect;
        snprintf(g_carselText.text, sizeof g_carselText.text, "%s", text);
        return;
    }
    if (!flailer_find_object(screen, object, FLAILER_TYPE_TEXT)
        || !flailer_find_object(screen, rect, FLAILER_TYPE_BITMAP))
        return;
    flailer_get_top_left_position(screen, rect, &x, &y);
    st = botStyle(b->ui, C2D_Color32(0xff, 0xff, 0xff, 0xff), 10.0f, false);
    uirender_draw_wrapped(b->ui, text, 0, &st, x * sx, y * sy,
                          (float)flailer_get_width(screen, rect) * sx, 1.0f);
}

// FlailerScreenList::RenderFlailerModels' RENDER to the car select,
// which draws its platform and, through the hook, its unlock blurb.
static void carselRender(void* user)
{
    (void)user;
    if (g_flow.screen && g_flow.screen->callback == bcarsel_screen_callback) {
        BScreenCallbackData rd;
        memset(&rd, 0, sizeof(rd));
        rd.itemHash = g_flow.screen->hash;
        bcarsel_screen_callback(&g_flow, BMSG_SCREEN_RENDER, &rd);
    }
}

// The frontend's eDisplayFrame with a selector up: view 0's Flailer
// layers 24 to 20, the cars and the platform over them, and the rest of
// the layers over those; then the blurb RENDER queued.
static void drawCarSelTop(UIRenderer* ui)
{
    bool drawn;

    if (!g_feView.loaded && frontres_loaded())
        (void)trackview_attach_frontend(&g_feView);
    // citro2d's depth test is left off for the layers: they write no depth
    // for the cars to meet.
    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
    uirender_draw_visible_passes(ui, 1.0f, 0, UIR_BACK_PASSES);
    C2D_Flush();
    g_carselText.defer  = true;
    g_carselText.queued = false;
    drawn = trackview_draw_frontend(&g_feView, carselRender, NULL);
    g_carselText.defer = false;
    C2D_Prepare();
    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
    uirender_draw_visible_passes(ui, 1.0f, UIR_BACK_PASSES, BUI_NUM_LAYERS);
    if (!drawn)
        carselRender(NULL);
    // The nebula, a line a second: FrameEffects' auto emitters and active
    // groups, the particles RenderEffects found visible, the sprites drawn.
    if (drawn && RealTimeFrames % 60 == 0) {
        const bNode* n;
        int          groups = 0;

        for (n = FrameEffects.ActiveGroupList.next;
             n != NULL && n != &FrameEffects.ActiveGroupList; n = n->next) {
            groups++;
        }
        logLine("carsel: nebula %d auto emitters, %d groups, %d particles "
                "visible; %d sprites drawn (%d dropped, %d refused)",
                (int)FrameEffects.NumAutoEmitters, groups,
                (int)FrameEffects.NumVisibleParticles, g_feView.spritesDrawn,
                g_feView.spritesDropped, g_feView.spritesRefused);
    }
    if (g_carselText.queued) {
        g_carselText.queued = false;
        hookCarSelRenderText(&g_boot, g_carselText.screen,
                             g_carselText.object, g_carselText.rect,
                             g_carselText.text, 1.0f);
    }
}

static int32_t hookCarSelLanguage(void* user)
{
    (void)user;
    return g_flow.currLanguage;
}

// FormatUnlockBlurbForCar, nfsrewards.c's. The event trees are not ported,
// so no car is an event's reward yet.
static void hookCarSelFormatUnlockBlurb(void* user, char* buf, int len,
                                        int32_t carType, int32_t gameType,
                                        int flag)
{
    NFSRewardHooks h;
    memset(&h, 0, sizeof(h));
    h.user      = user;
    h.translate = hookCarSelTranslate;
    h.language  = hookCarSelLanguage;
    nfs_format_unlock_blurb_for_car(&h, buf, len, carType, gameType, flag);
}

static void hookCarSelStopMovie(void* user)
{
    (void)user;
    bgf_stop_movie(&g_flow);
}

static void hookCarSelInit(void* user)
{
    (void)user;
    bcarsel_init_screen();
}

// BeginGameFlowUnloadingFrontEnd's CloseSelectCarScreen and
// TheCarLoader.UnloadEverything.
static void hookCarSelClose(void* user)
{
    (void)user;
    bcarsel_close_screen();
    carloader_unload_everything(&TheCarLoader);
}

// BeginGameFlowUnloadingFrontEnd's resource loop: FRONTB goes, and the
// frontend's view with it, when the next frame begins.
static void hookUnloadFrontEnd(void* user)
{
    (void)user;
    frontres_unload();
    trackview_free_later(&g_feView);
    logLine("frontres: FRONTB unloaded");
}

// elSetupLightContext's two questions: the frontend's lights are the
// flow's IN_FRONTEND state's, and the car select's while a selector is up.
static int elInFrontend(void)
{
    return g_flow.current == BGF_IN_FRONTEND;
}

// The bring-up overlays that used to be printf'd to the console on the
// bottom screen. They go to the log now -- and only when the line actually
// changes, because at the emulator's 140 FPS a line a frame is a megabyte a
// minute of the same text. One slot per line of the old overlay, so two
// lines that alternate do not each count as a change of the other.
#define DEV_SLOTS 12

// The regions on one of WeatherMan's lists.
static int weatherRegions(const bNode* head)
{
    const bNode* n = head->next;
    int          count = 0;

    while (n != head && count < 100000) {
        count++;
        n = n->next;
    }
    return count;
}

// What the viewer holds, for the log: tools/run_azahar_track.ps1 waits for
// the first line, and the rest are what a walk is read against. `event` is
// "entered" as SELECT enters the mode, "switched to" after ZL or ZR.
static void logTrackView(const char* event)
{
    logPrintf("trackview: %s TRACKB%d, %s\n", event, g_track.track,
              g_track.note);
    logPrintf("trackview: %d solids linked, %d models, %d "
              "without a solid, %d baked, %d tris, %d textures "
              "(%d missing, %d reduced, %d unchained), %u KB linear "
              "free, %lu KB heap free\n",
              g_track.linkedSolids, g_track.numModels,
              g_track.modelsWithoutSolid, g_track.bakedSolids,
              g_track.bakedTris, g_track.numTextures,
              g_track.missingTextures, g_track.reducedTextures,
              g_track.unchainedTextures,
              (unsigned)(linearSpaceFree() / 1024u),
              (unsigned long)(g_heapInfo.heapGot - mallinfo().uordblks)
                  / 1024);
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
    logPrintf("sky: SKYDOME %s, the envmap views' %s; sun %s "
              "at %.0f %.0f %.0f\n",
              SkydomeModel.Solid ? "drawn by StuffSky" : "none",
              SkydomeEnvmapModel.NameHash
                      == SKY_HASH_SKYDOME_ENVMAP ? "its own"
              : SkydomeEnvmapModel.NameHash == SKY_HASH_SKYDOME
                      ? "SKYDOME" : "none",
              SunInfo ? "chunk version 2" : "none",
              (double)SunPosition.x, (double)SunPosition.y,
              (double)SunPosition.z);
    logPrintf("weather: %d rain, %d fog, %d snow, %d wind "
              "regions, %d off; DrawFog %d, modes %d %d, "
              "FogPower %.2f, depth into alpha %d\n",
              weatherRegions(&WeatherRegionLists[WEATHER_RAIN]),
              weatherRegions(&WeatherRegionLists[WEATHER_FOG]),
              weatherRegions(&WeatherRegionLists[WEATHER_SNOW]),
              weatherRegions(&WeatherRegionLists[WEATHER_WIND]),
              weatherRegions(&WeatherRegionInactiveList),
              (int)DrawFog, (int)FogMode1, (int)FogMode2,
              (double)FogPower, (int)EnableDepthIntoAlpha);
    for (int i = 0; i < NUM_SUN_TEXTURES; i++) {
        const TextureInfo *t = SunTextures[i];

        logPrintf("sun texture %d: %.24s, order %d\n", i,
                  t ? t->DebugName : "none",
                  t ? t->RenderingOrder : -1);
    }
}

// ------------------------------------------------------------- the race
//
// ReplayManager is 20664 bytes in retail and not ported. World::GetTimestep
// and DoTimestep's checksum read pReplayManager with no test, so
// InitForRace's `new ReplayManager` gets a block with every flag clear: not
// replaying, not capturing. The other readers test pReplayManager or a flag
// first, and with CapturingFlag clear nothing walks the snapshot lists.
static ReplayManager* replayStandIn(void* mem)
{
    memset(mem, 0, REPLAY_MANAGER_SIZE);
    return (ReplayManager*)mem;
}

static void replayStandInDestroy(ReplayManager* rm, int32_t flags)
{
    if (flags & 1) bFree(rm);
}

// ReplayManager::GetData (0x0013eb88) and AddData (0x0013ec20), as far as
// retail's heads: GetData reads only while replaying with no error, and
// AddData records only while capturing. GenerateJoyEvents hands every
// frame's events to AddData, and the stand-in does neither, so neither
// reaches bRepeat, which is not ported.
static void replayNoRepeat(void)
{
    fprintf(stderr, "replay: bRepeat is not ported\n");
    abort();
}

static int32_t replayGetData(ReplayManager* rm, int32_t bits, int32_t channel)
{
    (void)bits;
    (void)channel;
    if (!rm->ReplayingFlag || rm->RemoveDataError) return 0;
    replayNoRepeat();
    return 0;
}

static void replayAddData(ReplayManager* rm, int32_t value, int32_t bits,
                          int32_t channel)
{
    (void)value;
    (void)bits;
    (void)channel;
    if (rm->CapturingFlag) replayNoRepeat();
}

// eDisplayFrame draws what the views hold, and the port's is trackview's
// draw. In a race it draws the track the flow loaded: TRACKB<n>.LZC, which
// the resource system read and the loaders have already run over, so
// trackview reads and loads nothing and the camera is the race's. It is
// attached on the first frame of a race. The Begin of loading renamed the
// file for hot chunking, so it goes by its .BUN name.
static bool raceAttachTrack(void)
{
    char          name[32];
    ResourceFile* rf;

    if (g_track.loaded) return g_track.attached;
    snprintf(name, sizeof name, "TRACKS\\TRACKB%d.BUN",
             (int)RaceParametersTrackNumber);
    rf = find_resource_file(name);
    if (!rf || !rf->pFirstChunk) return false;
    g_track.track = (int)RaceParametersTrackNumber;
    if (!trackview_attach(&g_track, rf->pFirstChunk,
                          (size_t)rf->SizeofChunks)) {
        logLine("race: track not attached: %s", g_track.note);
        return false;
    }
    logTrackView("attached to");
    {
        bNode* n;

        for (n = TexturePackList.next; n != &TexturePackList; n = n->next) {
            const TexturePack* tp = (const TexturePack*)(void*)n;

            logLine("race: pack %s (%s), %d textures, %d waiting",
                    tp->Name, tp->Filename, (int)tp->NumTextures,
                    (int)tp->NumNotYetLoadedTextureDatas);
        }
        for (n = ResourceFileList.next; n != &ResourceFileList;
             n = n->next) {
            const ResourceFile* f = (const ResourceFile*)(void*)n;

            logLine("race: file %s, %ld bytes of chunks",
                    f->Filename, (long)f->SizeofChunks);
        }
    }
    return true;
}

// Where the race is, once a second: the coordinator's state, the race's
// stage, the world's clock, player 1's car and the view's camera; and a
// camera zone's start and end as they come, as the jump cam's last a
// second or two.
static void logRaceState(void)
{
    static int32_t next;
    static int32_t lastZone;
    const eView*   view = eGetView(EVIEW_ID_PLAYER1);
    const World*   w    = pCurrentWorld;
    const struct Player* p = PlayerNumPlayers > 0 ? PlayerPlayersByIndex[0]
                                                  : NULL;

    if (p && p->nZoneCurrent != lastZone) {
        logLine("race: zone %d -> %d at world frame %ld, mover %d, "
                "time scale %.2f", (int)lastZone, (int)p->nZoneCurrent,
                (long)WorldTimeFrames,
                p->pCameraMover ? (int)p->pCameraMover->Type : -1,
                w ? (double)w->fTimeScale : 0.0);
        lastZone = p->nZoneCurrent;
    }

    if (WorldTimeFrames < next && next - WorldTimeFrames <= 60) return;
    next = WorldTimeFrames + 60;
    logLine("race: rc %d, stage %d, world %ld frames, %d cars; car 0 at "
            "%.1f %.1f %.1f; mover %d, zone %d, camera at %.1f %.1f %.1f",
            (int)racecoordinator_get_current_state(pRaceCoordinator),
            pCurrentRace ? (int)race_get_race_stage(pCurrentRace) : -1,
            (long)WorldTimeFrames, w ? (int)w->TotalNumCars : -1,
            w ? (double)w->CarPositionTable[0].x : 0.0,
            w ? (double)w->CarPositionTable[0].y : 0.0,
            w ? (double)w->CarPositionTable[0].z : 0.0,
            p && p->pCameraMover ? (int)p->pCameraMover->Type : -1,
            p ? (int)p->nZoneCurrent : -1,
            view->pCamera ? (double)view->pCamera->CurrentKey.Position.x : 0.0,
            view->pCamera ? (double)view->pCamera->CurrentKey.Position.y : 0.0,
            view->pCamera ? (double)view->pCamera->CurrentKey.Position.z : 0.0);
    if (p && p->MyCar) {
        const Car* c = p->MyCar;

        logLine("race: car 0 angle %u, nose %.2f %.2f %.2f, speed %.2f, "
                "vel %.3g %.3g %.3g, mode %d, %d wheels down",
                (unsigned)c->State.Angle, (double)c->State.BodyMatrix.v0.x,
                (double)c->State.BodyMatrix.v0.y,
                (double)c->State.BodyMatrix.v0.z,
                (double)c->State.ForwardSpeed, (double)c->State.Velocity.x,
                (double)c->State.Velocity.y, (double)c->State.Velocity.z,
                (int)c->TheMovementMode,
                (int)c->State.nWheelsTouchingGround);
        {
            const CollisionBody* b;
            int bodies = 0, dynamic = 0;

            for (b = CollisionBodyList.next;
                 b != (const CollisionBody*)(const void*)&CollisionBodyList;
                 b = b->Link.next) {
                bodies++;
                dynamic += b->Dynamic != 0;
            }
            logLine("race: car 0 mover %p, driver %p throttle %.2f brake "
                    "%.2f steer %.2f; %d bodies, %d dynamic; world dt %.4f",
                    (void*)c->pCarMover, (void*)c->pCarDriver,
                    c->pCarDriver ? (double)c->pCarDriver->Throttle : -1.0,
                    c->pCarDriver ? (double)c->pCarDriver->Brake : -1.0,
                    c->pCarDriver ? (double)c->pCarDriver->Steering : -1.0,
                    bodies, dynamic, (double)WorldTimeElapsed);
        }
    }
    // Each AI racer: where it is, its modes, the action it is carrying
    // out and what its PsychoDriver is asked for and does.
    if (w) {
        int i;

        for (i = 0; i < (int)w->TotalNumCars && i < WORLD_MAX_CARS; i++) {
            Car* c = w->CarTable[i];
            const AICarController* ai;
            const PsychoDriver* d;

            if (!c || c->TheControlMode != AI_CONTROL) continue;
            ai = car_ai_controller(c);
            d  = (const PsychoDriver*)(const void*)c->pCarDriver;
            logLine("race: AI car %d at %.1f %.1f %.1f, speed %.2f, mode %d, "
                    "action %d, stand %d; wants %.2f in %.2f, throttle %.2f "
                    "brake %.2f steer %.2f",
                    i, (double)c->State.Position.x,
                    (double)c->State.Position.y, (double)c->State.Position.z,
                    (double)c->State.ForwardSpeed, (int)c->TheMovementMode,
                    ai && ai->CurrentAction ? (int)ai->CurrentAction->Type
                                            : -1,
                    ai ? (int)ai->BrakeStanding : -1,
                    d ? (double)d->DesiredSpeed : -1.0,
                    d ? (double)d->TimeToGetToDesiredSpeed : -1.0,
                    d ? (double)d->Base.Throttle : -1.0,
                    d ? (double)d->Base.Brake : -1.0,
                    d ? (double)d->Base.Steering : -1.0);
            if (ai) {
                const DrivingLocation* l = ai->CurrentDrivingLocation;
                int32_t sk = c->MyDriver ? c->MyDriver->SkillLevel : -99;
                int lineSpeed = -1;

                if (l && l->pRoute && l->pRoutePoint
                    && l->DrivingLine >= 0
                    && l->DrivingLine < TRP_NUM_DRIVING_LINES)
                    lineSpeed = ((const uint8_t*)l->pRoutePoint)[
                        offsetof(TrackRoutePoint, DrivingLineSpeeds)
                        + l->DrivingLine];
                logLine("race: AI car %d: route %p point %p line %d speed "
                        "byte %d, uses line %d, skill %d factor %.3f, "
                        "boost %.3f, next think %.2f",
                        i, l ? (void*)l->pRoute : NULL,
                        l ? (void*)l->pRoutePoint : NULL,
                        l ? (int)l->DrivingLine : -9, lineSpeed,
                        ai->CurrentAction
                            ? (int)ai->CurrentAction->UseDrivingLineSpeed : -1,
                        (int)sk,
                        (sk >= 0 && sk < 10)
                            ? (double)TheDifficultyInfo.AISkillLevel[sk]
                                  .SpeedFactor : -1.0,
                        (double)c->State.BoostFactor,
                        (double)ai->SecondsBeforeNextActionEvaluation);
            }
        }
    }
    logLine("race: track drew %d of %d (%d sky), %d tris; %s",
            g_track.drawn, g_track.drawInfos, g_track.skyDrawn,
            g_track.drawnTris, g_track.note);
    logLine("race: minimap %d polys (%d failed)", g_track.flailerPolys,
            g_track.flailerFailed);
    logLine("race: sun %d quads (%d failed), last at %.0f %.0f alpha %d; "
            "Z rect at %d %d, %d read back, %d of it sky",
            g_track.sunQuads, g_track.sunQuadsFailed,
            (double)g_track.sunAt[0], (double)g_track.sunAt[1],
            g_track.sunAlpha, g_track.sunRectX, g_track.sunRectY,
            g_track.sunRects, g_track.sunSky);
    // Step 13b-1's measure: against the wall clock, the real and world
    // clocks should keep pace, and the frames drawn and the blanks give
    // the frame rate and the blanks a frame.
    logLine("race: clock wall %.3f s, real %.3f s, world %.3f s; step "
            "%.4f; %ld blanks, %lu frames drawn",
            (double)svcGetSystemTick() / SYSCLOCK_ARM11,
            (double)RealTimer * 0.00025, (double)WorldTimeSeconds,
            (double)RealTimeElapsed, (long)FrameCounter,
            (unsigned long)eFrameCounter);
    logLine("race: other solids %d (%d failed, %d dropped), textures %d "
            "(%d missing, %d reduced, %d unchained), deferred %d dropped; "
            "strips %d (%d dropped)",
            g_track.numOther, g_track.otherFailed, g_track.otherDropped,
            g_track.numTextures, g_track.missingTextures,
            g_track.reducedTextures, g_track.unchainedTextures,
            g_track.deferredDropped,
            g_track.stripsDrawn, g_track.stripsDropped);
    {
        // The effects: WorldEffects' auto emitters and active groups, the
        // particles RenderEffects found visible, and the sprites drawn.
        const bNode* n;
        int          groups = 0;

        for (n = WorldEffects.ActiveGroupList.next;
             n != NULL && n != &WorldEffects.ActiveGroupList; n = n->next) {
            groups++;
        }
        logLine("race: effects %d auto emitters, %d groups, %d particles "
                "visible; %d sprites drawn (%d dropped, %d refused)",
                (int)WorldEffects.NumAutoEmitters, groups,
                (int)WorldEffects.NumVisibleParticles, g_track.spritesDrawn,
                g_track.spritesDropped, g_track.spritesRefused);
    }
    {
        // Once, the other solids and what each texture slot draws with.
        static int listed;
        int        i, k;

        for (i = listed; i < g_track.numOther; i++) {
            const GeoSolid*   s = &g_track.solid[g_track.numSolids + i];
            const TrackSolid* r = &g_track.info[g_track.numSolids + i];
            char              line[512];
            size_t            n;

            n = (size_t)snprintf(line, sizeof line, "race: solid %.24s %d "
                                 "strips %d batches:", s->name, s->numStrips,
                                 r->mesh.numBatches);
            for (k = 0; k < s->numTextures && n + 40 < sizeof line; k++) {
                const TrackTex* t = r->tex ? r->tex[k] : NULL;

                n += (size_t)snprintf(line + n, sizeof line - n,
                                      " %.20s%s%s",
                                      t && t->info ? t->info->DebugName
                                                   : "(none)",
                                      t && !t->valid ? "!" : "",
                                      t && t->pass.blend ? "+" : "");
            }
            logLine("%s", line);
            listed = i + 1;
        }
    }
    {
        char     line[160];
        size_t   n = 0;
        uint32_t i, count = uirender_screen_count(g_boot.ui);

        line[0] = '\0';
        for (i = 0; i < count && n + 12 < sizeof line; i++) {
            BUI*       ui = NULL;
            BUIScreen* sc = uirender_screen_at(g_boot.ui, i, &ui);

            if (sc && sc->visible)
                n += (size_t)snprintf(line + n, sizeof line - n, " %08lx",
                                      (unsigned long)sc->nameHash);
        }
        logLine("race: screens up:%s", n ? line : " none");
    }
}

// MainLoop's race half (0x0012f3c8 .. 0x0012f5fc), after the flow's
// service: the coordinator, the world's step, and the cameras. The calls
// the port does not have yet are named where they would be.
static void raceFrame(void)
{
    RaceCoordinator* rc = pRaceCoordinator;
    World*           w;

    // The coordinator's queued messages, CheckForDemoDiscTimeout (the
    // demo disc's, and the port runs as retail with DemoDiscManager off),
    // a TICK, and ServiceGameFlow again.
    hangwatch_mark("race: coordinator");
    racecoordinator_execute_queued_messages(rc);
    racecoordinator_send_message(rc, RC_TICK, 0);
    bgf_service(&g_flow);
    if (pRaceCoordinator == NULL) return;

    // UpdateStomper is empty, and 0x0012f190 is the joylog's checksum.
    // Then the players' handlers for the coordinator's state: racing is
    // what gives the car the pad.
    determine_all_players_input_modes();

    // The flow paused (the coordinator in PAUSE) steps the world by 0.
    // Otherwise MainLoop asks for the World with no test: InitForRace made
    // it with the coordinator. ReplayManager's BeginFrame and EndFrame are
    // not ported; the stand-in is never playing back, so the step is the
    // world's own.
    // MainLoopTiming's ticks (mainloop.h) are stamped where MainLoop
    // stamps them: after the events, and after the world's step.
    w = pCurrentWorld;
    if (is_game_flow_paused() || w == NULL) {
        PrepareWorldTimestep(0.0f);
        GenerateJoyEvents();
        MainLoopTiming.GenerateJoyEvents = bGetTicker();
    } else {
        world_update_world_paused(w);
        if (world_is_world_paused(w)) {
            PrepareWorldTimestep(0.0f);
            GenerateJoyEvents();
            MainLoopTiming.GenerateJoyEvents = bGetTicker();
        } else {
            float step = world_get_timestep(w);

            PrepareWorldTimestep(step);
            GenerateJoyEvents();
            MainLoopTiming.GenerateJoyEvents = bGetTicker();
            hangwatch_mark("race: the world's step");
            world_do_timestep(w, step);
        }
    }
    MainLoopTiming.WorldDoTimestep = bGetTicker();
    hangwatch_mark("race: the cameras");

    // MenuSystemTick is bgf_frame's. ReplayScreen::Update and
    // UpdateCameraCoordinators (0x00199bd0) are not ported: no coordinator
    // is built yet. sound::Update runs at the top of the frame, and
    // UpdatePortRumblers has no rumble to drive.
    update_players_non_game_state();
    update_camera_movers();
    MainLoopTiming.UpdateCameraMovers = bGetTicker();
    update_camera_shakers();
    hangwatch_mark("race: the log");
    logRaceState();
}

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
// LoadGlobalChunks' eDisplayFrame (0x00112858): one frame, drawn before the
// frontend is loaded, so the LOADING screen is up while it loads.
static void hookDisplayFrame(void* user)
{
    Boot* b = (Boot*)user;
    C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
    C2D_TargetClear(g_top, C2D_Color32(0, 0, 0, 0xFF));
    C2D_SceneBegin(g_top);
    uirender_draw_visible(b->ui, 1.0f);
    C2D_TargetClear(g_bot, BOT_BACK);
    C3D_FrameEnd(0);
}

// ~bTList<AcidEmitter> deletes each emitter it takes off a car's effect
// list with AcidEmitter's deleting destructor, 3.
static void acidEmitterDelete(bNode* emitter, int32_t flags)
{
    acid_emitter_delete((AcidEmitter*)emitter, flags);
}

// RaceCoordinator's cleanup kills the world's effects.
static void killAllWorldEffects(void)
{
    acid_system_kill_all_active_effects(&WorldEffects);
}

// World's step (0x0014e110): WorldEffects' TweakerCheck, then its
// DoTimeStep.
static void worldEffectsTweakerCheck(void)
{
    acid_system_tweaker_check(&WorldEffects);
}

static void worldEffectsDoTimeStep(float dt)
{
    acid_system_do_time_step(&WorldEffects, dt);
}

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
    // Where the main loop was if it stops (hangwatch.h): the first race on
    // a New 3DS XL drew a frame and stopped there.
    hangwatch_start(logLine);

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
    aiaction_install_vtables();
    aiactions_install_vtables();
    aicarcontroller_install_vtables();
    beltmover_install_vtables();
    psychodriver_install_vtables();
    aidriver_install_vtables();

    // Car::SetControlMode reaches the controllers task 26 brings through
    // seams; a NULL one is a class not ported yet, and the arm aborts.
    gRealControllerCtorFn = realcontroller_construct;
    gAIDriverCtorFn = aidriver_construct;

    // BELT_MOVEMENT's mover, its SetBelt for AICarController::Think and
    // its slope for CalculateMaxAcceleration (11e-6).
    beltmover_install_seams();

    // Car::GetDrivingLineSpeed asks an AI or traffic car's controller,
    // an AICarController since step 11e-1.
    gAICarControllerGetCurrentDrivingLineSpeedFn =
        aicarcontroller_line_speed_seam;

    // DrivingChoice::AdvancePoint asks the controller's SignPostDecision,
    // ported in step 11e-2. drivingchoice_check keeps its stand-in here.
    gAISignPostDecisionFn = aicarcontroller_sign_post_decision;

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
    // Left NULL, the step aborts. Only a player's car reaches its four
    // Player calls. CleanUpJumpCam is playerinit.c's since step 8a; the
    // jump cam is playerzone.c's: IsJumpCamAvailable's PreviewRoute ahead
    // of the car, RequestZone's zones 6 and 7 with their slow motion and
    // TrackCarCameraMovers, and ClearZone as the car lands. The freeze and
    // preview zones (1 and 2) stay a dead button until their movers are
    // ported, and the zones' sounds wait for the sample seams.
    gCarFinishMovementFn = car_finish_movement;
    gPlayerCleanUpJumpCamFn = player_clean_up_jump_cam;
    gPlayerIsJumpCamAvailableFn = player_is_jump_cam_available;
    gPlayerRequestZoneFn = player_request_zone;
    gPlayerClearZoneFn = player_clear_zone;
    gPlayerJumpCamMoverFn = player_jump_cam_mover;
    gPreviewRouteDeleteFn = preview_route_delete;

    // Player::CleanupAfterRace takes the player's handlers off through
    // SetInputMode(NONE); playerinput.c has it.
    gPlayerSetInputModeFn = player_set_input_mode;

    // Player::SetHudFeatures (playerhud.c), which the destructor calls with
    // 0 and UpdateHud every frame with DetermineHudFeatures' answer.
    gPlayerSetHudFeaturesFn = player_set_hud_features;
    // Player::UpdateHud (hudrender.c), which UpdateNonGameState runs each
    // frame: SetHudFeatures when DetermineHudFeatures' answer changed, the
    // start bonus, and RenderHud's numbers into the HUD's Flailer objects.
    // GetTranslatedString is the same lookup Fred's defaults use; every HUD
    // caller copies the text out before the next call.
    gPlayerUpdateHudFn = player_update_hud;
    gHudTranslateFn = fredTranslate;
    // The HUD's animations (hudanim.c): UpdateHud runs them each frame,
    // RenderHud starts the speed's and the position's grows, SetHudFeatures
    // starts WRONG WAY, SetHudFeatures and BeginPause clear them, and the
    // Player's destructor frees them.
    gHudDoAnimationsFn = player_hud_do_animations;
    gHudStartSpeedAnimationFn = player_hud_start_speed_animation;
    gHudStartGrowAnimationFn = player_hud_start_grow_animation;
    gPlayerHudStartWrongWayFn = player_hud_start_wrong_way;
    gPlayerClearHudAnimationsFn = player_clear_hud_animations;
    gHudAnimatorDeleteFn = hudanim_delete;
    // The race's bonus scores (hudscore.c): UpdateHud runs UpdateScoring
    // each frame and starts the start bonus through StartScore(e, value).
    gUpdateScoringFn = player_update_scoring;
    gStartScoreFn = player_start_score_value;
    // The HUD's cop parts (hudcop.c): the radar detector, the trackers and
    // the pursuit meter, which UpdateHud calls when the HUD shows them. The
    // radar's GetRadarDetectorIntensity comes with the cops (step 12); until
    // then it reads 0.
    gUpdateRadarDetectorFn = player_update_radar_detector;
    gDrawTrackerFn = player_draw_tracker;
    gUpdatePursuitMeterFn = player_update_pursuit_meter;
    // The NIS overlay (hudnis.c): RenderHud updates it, SetHudFeatures shows
    // and hides it, and its date and time come off the 3DS's clock, which
    // is local already, so gScfGetLocalTimeFn stays NULL. The Start* that
    // play it come with the NIS.
    gNisOverlayUpdateFn = nisoverlay_update;
    gNisOverlaySetVisibleFn = nisoverlay_set_visible;
    gCdReadClockFn = cdReadClock;
    // The tach's red band (hudtach.c): SetHudFeatures lays the points over
    // the gradient, and uirender.c cuts the band out of them as it draws.
    gInitializeFlailerTachometerFn = flailer_initialize_tachometer;
    // The minimap (trackmap.c): SetHudFeatures makes one when the HUD's
    // TRACK_MAP feature comes on, and the race's frame renders it on the
    // bottom screen, after the HUD's half there.
    gNewTrackMapFn = newTrackMapLogged;
    gDeleteTrackMapFn = trackmap_delete;
    gTrackMapRenderFn = trackmap_render;

    // Car::MaybeCameraShake, which World::DoTimestep asks of each player's
    // car: shake.c. Only a car with a player shakes, and none has one until
    // step 8.
    gCarMaybeCameraShakeFn = car_maybe_camera_shake;

    // InitializeEverything's InitQueuedFiles (0x001a32b8; retail's
    // 0x001ada10), after LoadConfig and before eMathInit: the pool of the
    // reads ResourceFile and the texture packs queue (queuedfile.h).
    init_queued_files();
    gServiceQueuedFilesFn = service_queued_files;

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
    // touches. eFixUpTables looks every solid's textures up through
    // GetTextureInfo; left NULL, a race's track draws with none.
    emodel_init_slot_pool();
    gEModelInitFn     = emodel_init;
    gEModelDestroyFn  = emodel_delete;
    gGetTextureInfoFn = texturepack_get_texture_info;
    eInitViews();

    // eInitEngine's eInitEnvMap (0x00102f68): views 4 to 9 on targets 8 to
    // 13, the cameras the cars' reflections are drawn from.
    eenvmap_init();

    // InitializeEverything's afxInit (0x00126d70), after InitDisplaySystem
    // and before LoadGlobalChunks: the effect system's particle, group and
    // emitter pools (acidsys.c). PostLoadFixup's afxUpdateTextures gives
    // each emitter data its texture. Each car copies its effects' emitters
    // out of WorldEffects through afxGetEmitters, and deletes them again;
    // the race's cleanup kills the world's effects. World's step runs the
    // world's auto emitters and ages their particles; DoTimeStep reads the
    // game's flow state for the frontend's.
    afx_init();
    gAfxUpdateTexturesFn        = afx_update_textures;
    gAfxGetEmittersFn           = afx_get_emitters;
    gAcidEmitterDeleteFn        = acidEmitterDelete;
    gKillAllActiveEffectsFn     = killAllWorldEffects;
    gWorldEffectsTweakerCheckFn = worldEffectsTweakerCheck;
    gWorldEffectsDoTimeStepFn   = worldEffectsDoTimeStep;
    gAcidGameFlowStateFn        = fredFlowState;

    // elInit, and eLight.obj's two calls the solids and the cars make
    // through seams: elGetLightMaterial, which eFixUpTables uses to fill
    // every solid's light materials, and elSetupLightContext, which the
    // car's and the world's draws make before each model.
    el_init();
    gElGetLightMaterialFn  = get_light_material_seam;
    gElSetupLightContextFn = setup_light_context_seam;

    // Car's constructor builds the car's render info through
    // Car::InitRenderInfo, and its destructor deletes it -- carrenderinfo.c
    // since step 6, reached from step 8b's InitCars. The emitter positions
    // and the flares come out of two pools: retail makes the first in
    // InitCarEffects and the second in eInitSlotPools, and the port makes
    // both here.
    carrenderinfo_init_slot_pools();
    gCarInitRenderInfoFn    = car_init_render_info;
    gCarRenderInfoDestroyFn = carrenderinfo_delete;

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
    {
        // The PICA reaches a vertex buffer only within 256 MB of the
        // attribute buffers' base, so where the linear heap sits matters.
        extern u32 __ctru_linear_heap, __ctru_linear_heap_size;
        u32 pa = osConvertVirtToPhys((void*)__ctru_linear_heap);

        logPrintf("Linear heap: physical %08lx to %08lx\n", (unsigned long)pa,
                  (unsigned long)(pa + __ctru_linear_heap_size));
    }
    logConsole();

    // The port is for the New 3DS alone (the user's call, 2026-10-05). On
    // an Old 3DS a race's track ran the heap out (bMalloc's abort, back to
    // the Homebrew Launcher), and its CPU is a third of the speed, so it
    // says so here rather than failing at the first race.
    {
        bool isNew3DS = false;
        if (R_SUCCEEDED(APT_CheckNew3DS(&isNew3DS)) && !isNew3DS) {
            logPrintf("console: not a New 3DS, so the port stops here\n");
            fatalConsole();
            printf("\nThis port needs a New 3DS, New 3DS XL\n");
            printf("or New 2DS XL.\n\n");
            printf("A race needs more memory and a faster CPU\n");
            printf("than an Old 3DS or 2DS can give it.\n");
            waitForExit();
            gfxExit();
            return 1;
        }
    }

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
    bool soundUp = bsnd_hw_init(&gSnd);
    if (soundUp) {
        fesound_init(&gSnd);
        logPrintf("Sound: %u patches in %u voices\n",
                  (unsigned)gSnd.patchCount, gSnd.voices);
    } else {
        logPrintf("Sound: ndsp unavailable, running silent\n");
    }
    // InitializeSoundDriver's jukebox half (0x001ae608): the EA TRAX
    // cartridge off the disc, then each category's shipped volume. With no
    // ndsp the jukebox is still made, with no host: GetStatus is not 1, so
    // LoadCartridge does nothing and every Start finds no cartridge.
    jb_sound_init(&g_jukebox,
                  soundUp ? jbstream_host(g_jukebox.categoryVolume,
                                          jukeboxAssert)
                          : &kNoJukeboxHost,
                  &kJukeboxWorld);
    jb_load_cartridge(&g_jukebox.jukebox, "SOUND\\JukeboxM.JBC", false);
    jb_default_category_volumes(&g_jukebox);
    logPrintf("Jukebox: %s, %u tunes\n",
              jb_is_cartridge_loaded(&g_jukebox.jukebox) ? "loaded" : "none",
              (unsigned)g_jukebox.jukebox.numTunes);

    // Four times citro3d's default. A track frame is a draw per object the
    // cull keeps, each with its own matrices, and the default's 256 KB is
    // about 500 of them; GPUCMD_Add drops what does not fit without a word.
    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE * 4);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    C3D_RenderTarget* top = C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8,
                                                   GPU_RB_DEPTH24_STENCIL8);
    g_top = top;
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

    // InitializeEverything's LoadGlobalChunks (0x001682d0) first: GLOBALB
    // and the texture packs, English, and one frame with LOADING up, all
    // before the frontend is read -- LOADING is the first thing on screen.
    // LOADING_TRACK is GLOBALB's, and its NFS logo is DYNTEX's.
    static UIRenderer ui;
    uirender_init(&ui, 400.0f, 240.0f);
    UIBundle* globalBundle = addBundle(&ui, BUNDLE_GLOBAL);
    loadGlobalCarInfo(globalBundle);
    // InitCarInfo (0x00188d08), next in InitializeEverything: each car
    // type's pCarSpecs.
    if (CarTypeInfoArray) init_car_info();
    addBundle(&ui, BUNDLE_DYNTEX);

    memset(&g_boot, 0, sizeof(g_boot));
    g_boot.ui = &ui;
    bootNote("booting");

    BGameFlowHooks hooks;
    memset(&hooks, 0, sizeof(hooks));
    hooks.user             = &g_boot;
    hooks.setScreenVisible = hookSetScreenVisible;
    hooks.setObjectVisible = hookSetObjectVisible;
    hooks.setGroupVisible  = hookSetGroupVisible;
    hooks.openScreen       = hookOpenScreen;
    hooks.enterScreen      = hookEnterScreen;
    hooks.leaveScreen      = hookLeaveScreen;
    hooks.grayMenuItem     = hookFlowGrayMenuItem;
    hooks.activeMenuItem   = hookActiveMenuItem;
    hooks.movieOpen        = hookMovieOpen;
    hooks.movieDrive       = hookMovieDrive;
    hooks.movieClose       = hookMovieClose;
    hooks.panelMovieOpen   = hookPanelMovieOpen;
    hooks.panelMovieUpdate = hookPanelMovieUpdate;
    hooks.inGame           = hookInGame;
    hooks.loadResource     = hookLoadResource;
    hooks.loadSoundRegions = hookLoadSoundRegions;
    hooks.setLanguage      = hookSetLanguage;
    hooks.loadSpeech       = hookLoadSpeech;
    hooks.unloadSpeech     = hookUnloadSpeech;
    hooks.swapLogoArt      = hookSwapLogoArt;
    hooks.displayFrame     = hookDisplayFrame;
    hooks.newFileSys       = hookNewFileSys;
    hooks.fredLoaded       = hookFredLoaded;
    hooks.raceDefaults     = hookRaceDefaults;
    hooks.frontendDefaults = hookFrontendDefaults;
    hooks.challengeCars    = hookChallengeCars;
    // The title screen's Start once its movies are done, NewMainMenu's
    // constructor's, and UnlaunchFrontendMenus' Stop.
    hooks.jukebox          = hookJukebox;
    hooks.songMonitor      = hookSongMonitor;
    hooks.easterEggs       = hookEasterEggs;
    hooks.initSelectCar    = hookCarSelInit;
    hooks.closeSelectCar   = hookCarSelClose;
    hooks.unloadFrontEnd   = hookUnloadFrontEnd;
    hooks.moveBrackets     = hookMoveBrackets;   // NewMainMenu's highlight
    hooks.setBlurb         = hookSetBlurb;
    hooks.trace            = hookTrace;
    // TheDemoModeReplay has no replays to offer (no hook answers "none"),
    // and StartDemoMode's race is not ported: ConsiderStartDemoMode runs
    // and only traces.

    bgf_init(&g_flow, kGameFlowStages, BGF_NUM_STATES,
             kScreens, NUM_SCREENS, kBootStages, NUM_BOOT_STAGES, &hooks);
    // FlailerScreenList's constructor makes its song monitor (0x0016c25c).
    bsm_init(&g_songMonitor, &kSongMonitorHooks);
    g_flow.fred = fred_bytes();
    // Player's POV cycle reads SkipFE (gp-23220), which the flow holds.
    gPlayerCamSkipFE = &g_flow.skipFE;
    // Retail sets SkipFE only from a joylog's config items (LoadConfigItems,
    // 0x0012faf0, early in InitializeEverything), and the port reads no
    // joylog: R held as the app starts is the port's switch. InitFred and
    // the players' settings read it, so it is set before them.
    hidScanInput();
    if (hidKeysHeld() & KEY_R) {
        g_flow.skipFE = 1;
        logLine("SkipFE: R held at boot");
    }
    readConfigItems();
    gCurrLanguageFn = currLanguage;
    // LoadGlobalChunks' first pack, DynTextures, and its LOADING, which is
    // waited on before the frame. Retail sets English between the table
    // and the ask; on a fresh boot that renames nothing, so the port's
    // bgf_load_global_chunks sets it after. The frame itself is drawn from
    // the UI's DYNTEX bundle, not from this pack.
    pDynamicTexturePack = newStreamedPack("pDynamicTexturePack",
                                          "DynTextures", "GLOBAL\\DYNTEX.BIN");
    if (texturepack_get_loaded_texture(pDynamicTexturePack, 0xab0e817d)
        == NULL) {
        uint32_t loading = 0xab0e817d;   // bStringHash("LOADING")
        texturepack_load_textures_from_file(pDynamicTexturePack, &loading, 1,
                                            NULL, 0);
    }
    waitForGlobalChunks();
    bgf_load_global_chunks(&g_flow);
    // After the frame, the HUD's and the cars' packs, and the wait again.
    pHudTexturePack = newStreamedPack("HudTexturePack", "HudTextures",
                                      "GLOBAL\\HUDTEX.BIN");
    pCarTexturePack = newStreamedPack("pCarTexturePack", "CarTextures",
                                      "CARS\\TEXTURES.BIN");
    waitForGlobalChunks();
    // What CarLoader and the track flow stream through: the cars' skins
    // and the HUD's textures.
    gLoadTexturesFromFileFn      = texturepack_load_textures_from_file;
    gUnloadTexturesFromFileFn    = unloadTexturesFromFile;
    gUnloadAllTexturesFromFileFn = texturepack_unload_all_textures_from_file;
    logPrintf("streamed packs: DynTextures %d, HudTextures %d, "
              "CarTextures %d textures\n",
              (int)pDynamicTexturePack->NumTextures,
              (int)pHudTexturePack->NumTextures,
              (int)pCarTexturePack->NumTextures);
    logLine("global chunks loaded, LOADING drawn");
    // InitFred (0x00183820), after the car data and the sound driver as in
    // InitializeEverything: FrontendDatabase::InitWithDefaults on Fred.
    gFredAudioOptionsDefaultsFn = fredAudioDefaults;
    gFredTranslateFn = fredTranslate;
    init_fred();
    logFredDefaults();

    // What BeginGameFlowLoadingFrontend asks for, FRONTB, read here rather
    // than behind the loader; and INGAMEB, which the track viewer shares.
    g_frontBundle = addBundle(&ui, BUNDLE_FRONTEND);
    UIBundle* ingameBundle = addBundle(&ui, BUNDLE_INGAME);
    gElInFrontendFn      = elInFrontend;
    gElCarSelectActiveFn = bcarsel_active;
    // InitializeEverything's InitCarLoader (0x001b0260), after the
    // frontend: the pool the car and skin entries come from. Its loads go
    // through the resource system; nothing asks it for a car yet.
    init_car_loader();
    gCarLoadResourceFileFn    = resLoadFile;
    gServiceResourceLoadingFn = resService;
    gUnloadResourceFileFn     = resUnloadFile;
    gFindResourceFileFn       = resFindByType;
    gFindResourceFileByNameFn = resFindByName;
    gSetFlailerScreenVisibilityFn = raceScreenVisibility;
    // The Flailer runtime (flailer.h) behind the race's object calls: the
    // Player's HUD lookups, the countdown's, and the NIS overlay's BUSTED.
    gFlailerTextScaledWidthFn   = flailerTextWidth;
    gFlailerTextScaledHeightFn  = flailerTextHeight;
    gFlailerBitmapTextureSizeFn = flailerTextureSize;
    gFindFlailerObjectFn        = flailer_find_object;
    gFlailerChunkGetTopLeftFn   = flailerobject_get_top_left;
    gFlailerObjectVisibilityFn  = flailerObjectVisibility;
    gFlailerSetVisibilityFn     = flailer_set_visibility;
    gFlailerSetAlphaFn          = flailer_set_alpha;
    gFlailerScaleAboutCenterFn  = flailer_scale_about_center;
    gFlailerGetScaleFn          = flailer_get_scale;
    gFlailerGetTopLeftYFn       = flailer_get_top_left_y;
    gFlailerChunkSetScaleXFn    = flailerobject_set_scale_x;
    gFlailerChunkSetScaleYFn    = flailerobject_set_scale_y;
    gFlailerChunkSetTopLeftYFn  = flailerobject_set_top_left_y;
    {
        int      n = 0;
        uint32_t linked = 0, count;
        while (flailer_project_at(n, NULL, &count)) {
            linked += count;
            n++;
        }
        logPrintf("flailer: %d projects, %lu screens\n", n,
                  (unsigned long)linked);
    }
    // EndGameFlowLoadingTrackSpecific's last call, `new RaceCoordinator`,
    // whose constructor builds the race -- InitForRace's players, Race,
    // World and cars -- and the Begin of unloading's delete. InitForRace's
    // ReplayManager is the stand-in above.
    // InitAIPlans and CloseAIPlans: the AI actions' slot pool, made as a
    // track loads and deleted as it unloads.
    gInitAIPlansFn           = ai_init_ai_plans;
    gCloseAIPlansFn          = ai_close_ai_plans;
    gNewRaceCoordinatorFn    = racecoordinator_new;
    gDeleteRaceCoordinatorFn = racecoordinator_destroy;
    gReplayManagerCtorFn     = replayStandIn;
    gReplayManagerDestroyFn  = replayStandInDestroy;
    gReplayManagerGetData    = replayGetData;
    gReplayManagerAddData    = replayAddData;
    // World's constructor makes its TrafficTeleporter, and its destructor
    // deletes it and any car left on CarList.
    gTrafficTeleporterCtorFn    = traffic_teleporter_construct;
    gTrafficTeleporterDestroyFn = traffic_teleporter_destroy;
    gCarDestroyFn               = car_destruct;
    logPrintf("car loader: pool %s\n", LoadedCarSlotPool ? "up" : "missing");

    // The blurb moves to the bottom screen, so the top screen stops drawing
    // it -- and stops drawing the bar tAnimatedBlurb wipes it out with,
    // which on its own over an empty strip is just a flash of grey. The
    // animations still run and still move the object; this is a draw-time
    // skip, so nothing has to know.
    uirender_hide_object(&ui, BSCR_OBJ_SCROLLING_TEXT);
    uirender_hide_object(&ui, BSCR_OBJ_WHITEOUT_BAR);

    // The race HUD on two screens (hudsplit.h): what the player watches
    // stays on the top screen, and the lap block, the splits, the score
    // and Be The Cop's panel go to the bottom one.
    hudsplit_install(&ui);

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
    animHooks.nextInGroup      = hookAnimNextInGroup;
    animHooks.textMaxChars     = hookAnimTextMaxChars;
    animHooks.textScaledHeight = hookAnimTextScaledHeight;
    animHooks.getColor         = hookAnimGetColor;
    bscr_set_anim_hooks(&g_uiScreens, &animHooks);
    // The title's bloom runs on the same kit, as tHighlightAnimation is one
    // class for every screen in the original.
    g_flow.anim = &g_uiScreens.anim;

    // The race setup screens, on the same kit and the flow's clock.
    BSetupHooks setupHooks;
    memset(&setupHooks, 0, sizeof(setupHooks));
    setupHooks.user                = &g_boot;
    setupHooks.findObject          = hookAnimObjectExists;
    setupHooks.setBitmapAlpha      = hookSetupBitmapAlpha;
    setupHooks.setBitmapCenterY    = hookSetupBitmapCenterY;
    setupHooks.setBitmapVisible    = hookSetupBitmapVisible;
    setupHooks.getCenterY          = hookSetupCenterY;
    setupHooks.getBoundingBox      = hookSetupBoundingBox;
    setupHooks.setTopLeftY         = hookSetupTopLeftY;
    setupHooks.getTopLeftX         = hookSetupTopLeftX;
    setupHooks.setLanguageID       = hookAnimSetLanguageID;
    setupHooks.setVisible          = hookAnimSetVisible;
    setupHooks.grayMenuItem        = hookFlowGrayMenuItem;
    setupHooks.grayMenuItemNamed   = hookSetupGrayNamed;
    setupHooks.getTopLeftY         = hookSetupGetTopLeftY;
    setupHooks.setObjectTopLeftY   = hookSetupObjectTopLeftY;
    setupHooks.setClipToPoly       = hookSetupClipToPoly;
    setupHooks.setAlpha            = hookSetupAlpha;
    setupHooks.isJoystickPluggedIn = hookSetupJoystickPluggedIn;
    setupHooks.startMovie          = hookScreenMovie;
    setupHooks.setHelpOverride     = hookSetupHelpOverride;
    setupHooks.makeChallengeCarsAvailable = hookSetupChallengeCars;
    setupHooks.preloadCars         = hookSetupPreloadCars;
    setupHooks.setupRaceParametersAfterRaceSetup = hookSetupRaceAfterSetup;
    setupHooks.setRaceParameters   = hookSetupRaceParameters;
    setupHooks.trace               = hookTrace;
    bsetup_init(&g_setup, &g_flow, &setupHooks);

    BCarSelHooks carselHooks;
    memset(&carselHooks, 0, sizeof(carselHooks));
    carselHooks.user               = &g_boot;
    carselHooks.translate          = hookCarSelTranslate;
    carselHooks.translateString    = hookCarSelTranslateString;
    carselHooks.sound              = hookCarSelSound;
    carselHooks.stopSound          = hookCarSelStopSound;
    carselHooks.setHelpOverride    = hookSetupHelpOverride;
    carselHooks.summonPopup        = hookCarSelSummonPopup;
    carselHooks.dismissPopup       = hookCarSelDismissPopup;
    carselHooks.changeToScreen     = hookCarSelChangeToScreen;
    carselHooks.startRace          = hookCarSelStartRace;
    carselHooks.loaderFrontEnd     = hookCarSelLoaderFrontEnd;
    carselHooks.loaderLoad         = hookCarSelLoaderLoad;
    carselHooks.loaderIsLoaded     = hookCarSelLoaderIsLoaded;
    carselHooks.loaderUnload       = hookCarSelLoaderUnload;
    carselHooks.loaderBeginLoading = hookCarSelLoaderBeginLoading;
    carselHooks.renderTextIntoRectangle = hookCarSelRenderText;
    carselHooks.formatUnlockBlurb  = hookCarSelFormatUnlockBlurb;
    carselHooks.language           = hookCarSelLanguage;
    carselHooks.stopMovie          = hookCarSelStopMovie;
    carselHooks.trace              = hookTrace;
    bcarsel_init(&g_carsel, &carselHooks);

    // Retail's main (0x0012f000), after InitializeEverything: with SkipFE
    // set, StartSkipFEGame on Fred, whose StartRace asks for
    // LOADING_TRACK_COMMON straight from NONE; else
    // ChangeGameFlow(LOADING_FRONTEND). MainLoop takes it from there.
    gFredGameFlowStateFn  = fredFlowState;
    gFredChangeGameFlowFn = fredChangeFlow;
    if (g_flow.skipFE) {
        fred_start_skip_fe_game(&Fred);
        logRaceStart();
    } else {
        bgf_change_state(&g_flow, BGF_LOADING_FRONTEND, BGF_NONE);
    }

    if (!georender_init()) {
        logPrintf("georender: shader would not load\n");
    } else if (!trackview_envmap_init()) {
        logPrintf("georender: no room for the environment map\n");
    }
    if (!geoview_init(&g_geo)) {
        logPrintf("geoview: %s\n", g_geo.note);
    } else {
        logPrintf("geoview: %d cars, car pack %s, global pack %s\n",
                  g_geo.numCars,
                  g_geo.hasCarPack ? "open" : "missing",
                  g_geo.hasGlobalPack ? "open" : "missing");
    }
    // The track's textures are partly GLOBALB's, whose packs the boot has
    // loaded, and INGAMEB's, which the UI already holds; the viewer loads
    // INGAMEB's packs from that copy.
    bool trackOk = trackview_init(&g_track, TRACKVIEW_TRACK);
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
    // MainLoop's s2, the tick its measure starts from, read first at its
    // entry (0x0012f3a0).
    uint32_t frameTicker = bGetTicker();
    // The top screen's blank count when the last frame's sync returned.
    u32      lastSync = 0;
    // The race's phases, a line a second (frameprof.h), and the jukebox
    // worker's sums at the last frame's end. Out of a race the worker has
    // a line of its own every five seconds: its sums and the tick at the
    // last one.
    FrameProf prof;
    uint32_t  jbDecode = 0, jbRead = 0;
    uint32_t  jbLineTick = frameTicker, jbLineDecode = 0, jbLineRead = 0;
    frameprof_reset(&prof);
    DisplayPlayerDebugInfo = SHOW_FRAME_RATES;

    while (hangwatch_main_loop()) {
        MainLoopTiming.StartTime = bGetTicker();
        hidScanInput();
        u32 kDown = hidKeysDown();

        // bSound::updateCompletedVoices' slot in the frame. Without it the
        // allocator hands out 24 channels and then never another.
        hangwatch_mark("sound");
        bsnd_update(&gSnd);
        // sound::Update's jukebox (0x001af4c0): its Update and a delayed
        // start, then bSound::Update's -- the sample's callbacks. Its 8 ms
        // gate passes at any frame rate up to 125. The delayed start counts
        // down by the world's step (gp-19560), which is still the last
        // frame's here: the clocks advance below.
        jb_music_update(&g_jukebox, Fred.AudioOptionsScreenData,
                        WorldTimeElapsed);
        if (soundUp) jbstream_poll(&g_jukebox.jukebox);
        MainLoopTiming.UpdateSound = bGetTicker();

        // MainLoop's clocks (0x0012f378). It prepares the real step at the
        // top of a frame from the ticker (0x0012f43c), and the world's from
        // the real one when there is no race. It advances both at the
        // frame's end (0x0012f62c), which here is the top of the next one.
        // FrameCounter is the vertical-blank count PSX2VBlank keeps: the
        // top screen's, from citro3d (realtime.h).
        if (clockStarted) {
            AdvanceRealTime();
            AdvanceWorldTime();
        }
        clockStarted = true;
        FrameCounter = (int32_t)C3D_FrameCounter(0);
        prepare_real_timestep_from_ticker(&frameTicker);

        uiTimer += (uint32_t)(int)(RealTimeElapsed * 4000.0f);
        uirender_set_time(&ui, (float)uiTimer * 0.00025f);
        // A race up as the frame begins takes its world step, and the
        // events, after the coordinator's TICK: raceFrame. One the flow
        // makes in this frame starts on the next.
        bool raceUp = pRaceCoordinator != NULL;
        if (!raceUp) PrepareWorldTimestep(RealTimeElapsed);

        // The PS2 reads the pads from its vertical-blank interrupt; here it
        // is once a frame, after the HID scan the read is built from, and
        // after the clocks, as GenerateJoyEvents is in MainLoop.
        ReadJoystickData();
        if (!raceUp) GenerateJoyEvents();
        if (GetJoystickType(0) != joyType) {
            joyType = GetJoystickType(0);
            logPrintf("joystick: port 0 type %d\n", (int)joyType);
        }

        // The viewers are the frontend's: the track viewer would read a
        // second track over the race's, and the race stops for neither.
        if ((kDown & KEY_SELECT) && !raceUp && !g_track.attached) {
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
                logTrackView("entered");
            } else {
                logPrintf("mode %d\n", mode);
            }
        }

        if (mode == MODE_FLOW) {
            // ---- the boot flow
            // FlailerScreenList::JoyHandler: a popup that is up has each
            // event before the screen and its menu, and takes every one --
            // the memory card's messages ignore SELECT and BACK, but the
            // title underneath does not get them either.
            u32 flowDown = kDown;
            if (bpopup_any_active(&g_flow)) {
                static const struct { u32 key; BJoyEvent ev; } kPopupBinds[] = {
                    { KEY_START, BJOY_START },
                    { KEY_B,     BJOY_MENU_BACK },
                };
                for (int i = 0; i < NUM_BINDS; i++)
                    if ((kDown & kBinds[i].key)
                        && bpopup_joy(&g_flow, 0, kBinds[i].ev, 1))
                        flowDown &= ~kBinds[i].key;
                for (int i = 0; i < 2; i++)
                    if ((kDown & kPopupBinds[i].key)
                        && bpopup_joy(&g_flow, 0, kPopupBinds[i].ev, 1))
                        flowDown &= ~kPopupBinds[i].key;
                if (flowDown != kDown) redraw = 1;
            }
            // START goes through the menu, as FlailerMenu's JoyHandler takes
            // it: the screen has it as SCREEN_START_BUTTON first, and unless
            // the screen consumes it, the current item has it as a select.
            // That second half is how START leaves PRESS START and skips
            // the NFS intro; the title screen only swallows the click.
            if (flowDown & KEY_START) {
                if (g_boot.hasMenu) {
                    bmenu_joy(&g_boot.menu, 0, BJOY_START, true);
                } else {
                    bgf_screen_event(&g_flow, BMSG_SCREEN_START_BUTTON, 0);
                }
                redraw = 1;
            }
            // FlailerScreenList::JoyHandler's BACK: the screen hears
            // SCREEN_BACK_BUTTON first and may veto the pop.
            if (flowDown & KEY_B) {
                bgf_back_button(&g_flow, 0);
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
                    if (!(flowDown & kBinds[i].key)) continue;
                    bmenu_joy(&g_boot.menu, 0, kBinds[i].ev, true);
                    redraw = 1;
                }
            }

            // MainLoop: one pass of the flow per frame, by the real step.
            // bgf_frame is the flow's service and the menus' tick both.
            // With no race the race's three stamps are the same tick.
            hangwatch_mark("flow");
            bgf_frame(&g_flow, RealTimeElapsed);
            MainLoopTiming.ServiceGameFlow = bGetTicker();
            MainLoopTiming.MenuSystemTick = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.GenerateJoyEvents = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.WorldDoTimestep = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.UpdateCameraMovers = MainLoopTiming.ServiceGameFlow;
            if (raceUp && pRaceCoordinator != NULL) {
                raceFrame();
                hangwatch_mark("race: the track's attach");
                (void)raceAttachTrack();
            } else if (g_flow.current == BGF_IN_FRONTEND) {
                // MainLoop's UpdateCameraMovers, which raceFrame makes in
                // a race; in the frontend the car select's camera is the
                // one mover.
                update_camera_movers();
            }
            // The Begin of unloading deleted the coordinator and is
            // unloading the track's files: the view lets go of the bundle
            // before anything else can read it.
            if (pRaceCoordinator == NULL && g_track.attached) {
                trackview_free(&g_track);
                logLine("race: track detached");
            }

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

            updateBlurb(&g_boot, RealTimeElapsed);

            // The race is paced at 30 (step 13b-1): a frame takes two
            // vertical blanks at least, so none is 16.7 ms between two of
            // 33.3. C3D_FrameBegin's sync waits for the next blank; when
            // none has come since the last frame's, one more wait first.
            // A slower frame is not held back further. The frontend and
            // the movies stay at 60.
            //
            // C3D_FRAME_SYNCDRAW's sync is made here, so the wait for the
            // blank and C3D_FrameBegin's wait for the GPU are timed apart
            // (step 13b-2). The second is eWaitUntilRenderingDone's, which
            // eDisplayFrame times into WaitBufferSwapTime. VifTime is the
            // GPU's last frame, on the same scale (frame-profiler.md).
            uint32_t syncTick = bGetTicker();
            hangwatch_mark("C3D_FrameSync: the vertical blank");
            if (g_track.attached && C3D_FrameCounter(0) == lastSync)
                C3D_FrameSync();
            C3D_FrameSync();
            uint32_t gpuTick = bGetTicker();
            hangwatch_gpu_race(g_track.attached);
            capture_race(g_track.attached);
            warp_race(g_track.attached);
            hangwatch_mark("C3D_FrameBegin: the GPU's last frame");
            C3D_FrameBegin(0);
            hangwatch_gpu_begin();
            uint32_t drawTick = bGetTicker();
            // The GPU is done with the last frame: what the frontend's view
            // let go of since can be freed.
            trackview_frame_begun(&g_feView);
            frameprof_begin_draw(syncTick, gpuTick, drawTick);
            lastSync = C3D_FrameCounter(0);
            WaitBufferSwapTime = (int32_t)bGetFixTickerDifference(gpuTick,
                                                                  drawTick);
            VifTime = (int32_t)bGetFixTickerDifference(
                0, (uint32_t)(C3D_GetDrawingTime()
                              * (float)(BTICKER_RATE_HZ / 1000u)));
            if (g_track.attached) {
                // eDisplayFrame: the race's view, then the Flailer screens
                // over it. The sun's Z rects are read first, from the last
                // frame's depth, as the track viewer reads them.
                const u32 sky = C2D_Color32(0x8c, 0xa8, 0xc8, 0xFF);

                hangwatch_mark("the sun's depth read");
                if (capture_read(top))
                    trackview_capture_names(&g_track);
                trackview_read_depth(&g_track, top);
                trackview_draw_envmap(&g_track);
                FRAMEPROF_STAMP(FRAMEPROF_ENVMAP);
                C3D_RenderTargetClear(top, C3D_CLEAR_ALL,
                                      __builtin_bswap32(sky), 0);
                C3D_FrameDrawOn(top);
                trackview_draw(&g_track);
                C2D_Prepare();
                C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
            } else {
                C2D_TargetClear(top, clear);
            }
            C2D_SceneBegin(top);
            if (!g_track.attached && bcarsel_active())
                drawCarSelTop(&ui);
            else
                uirender_draw_visible(&ui, 1.0f);
            C2D_Flush();
            hangwatch_gpu_stage("the top screen's HUD");
            FRAMEPROF_STAMP(FRAMEPROF_HUD);
            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            // In a race the bottom screen is the HUD's other half
            // (hudsplit.h), and the frontend's panel when the HUD is down.
            if (uirender_draw_visible_bottom(&ui, BOT_W, BOT_H, 1.0f)) {
                // eDisplayFrame's RenderTrackMap for each player, after
                // the Flailer layers: the minimap, made bigger in the
                // bottom screen's free lower left (hudsplit_map_place).
                if (g_track.loaded) {
                    float mapScale = 1.0f, mapDx = 0.0f, mapDy = 0.0f;

                    for (int i = 0; i < PlayerNumPlayers; i++) {
                        player_render_track_map(PlayerPlayersByIndex[i]);
                    }
                    if (PlayerNumPlayers == 1
                        && PlayerPlayersByIndex[0]->pTrackMap != NULL) {
                        hudsplit_map_place(
                            PlayerPlayersByIndex[0]->pTrackMap
                                ->CurrentlyDisplayedMode,
                            &mapScale, &mapDx, &mapDy);
                    }
                    C2D_Flush();
                    trackview_draw_flailer_polys(&g_track, BOT_W, BOT_H,
                                                 mapScale, mapDx, mapDy);
                    C2D_Prepare();
                    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
                }
            } else {
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
            C2D_Flush();
            hangwatch_gpu_stage("the bottom screen");
            FRAMEPROF_STAMP(FRAMEPROF_BOTTOM);
            C3D_FrameEnd(0);
            hangwatch_gpu_frame_end();
            // eDisplayFrame's end (0x00113fd0), its packets sent: FrameEffects,
            // car select's nebula, a sixtieth of a second on (gp-32668) each
            // frame drawn, the race's as well.
            acid_system_do_time_step(&FrameEffects, 1.0f / 60.0f);
            MainLoopTiming.DisplayFrame = bGetTicker();
            // MainLoop's ServiceResourceLoading, after eDisplayFrame: the
            // resource system's, then the frontend's bundles (bootQueue).
            hangwatch_mark("the loads");
            (void)service_resource_loading();
            bootServiceLoads(&g_boot);
            MainLoopTiming.ServiceFileSystem = bGetTicker();
            hangwatch_mark("the frame's sums");

            // MainLoop's end (0x0012f664): the last tick, then
            // CalculateFrameRate and MaybePrintTiming. The race's phases go
            // to the log a second at a time.
            MainLoopTiming.LimitFrameRate = bGetTicker();
            CalculateFrameRate();
            MaybePrintTiming();
            {
                uint32_t decode, read;

                jbstream_busy(&decode, &read);
                if (g_track.attached) {
                    char line[1024];

                    FrameProfDraw.jukeboxDecode = decode - jbDecode;
                    FrameProfDraw.jukeboxRead = read - jbRead;
                    frameprof_add(&prof, &MainLoopTiming,
                                  C3D_GetProcessingTime(),
                                  C3D_GetDrawingTime());
                    if (frameprof_line(&prof, line, sizeof line))
                        logLine("%s", line);
                    jbLineTick = MainLoopTiming.LimitFrameRate;
                    jbLineDecode = decode;
                    jbLineRead = read;
                } else {
                    uint32_t span = MainLoopTiming.LimitFrameRate
                                  - jbLineTick;

                    frameprof_reset(&prof);
                    if (span >= 5u * BTICKER_RATE_HZ) {
                        // Milliseconds a second: the ticks over the
                        // span's, times 1000.
                        if (decode != jbLineDecode || read != jbLineRead)
                            logLine("jukebox: decode %.2f ms a second, "
                                    "read %.2f, over %.1f s",
                                    (double)(decode - jbLineDecode) * 1000.0
                                        / span,
                                    (double)(read - jbLineRead) * 1000.0
                                        / span,
                                    (double)span / BTICKER_RATE_HZ);
                        jbLineTick = MainLoopTiming.LimitFrameRate;
                        jbLineDecode = decode;
                        jbLineRead = read;
                    }
                }
                jbDecode = decode;
                jbRead = read;
            }
            continue;
        }

        if (mode == MODE_GEO) {
            circlePosition pad;

            if (kDown & KEY_START) break;
            hidCircleRead(&pad);
            geoview_input(&g_geo, kDown, hidKeysHeld(), pad.dx, pad.dy,
                          RealTimeElapsed);

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
            // The fog colour TRACKB12's sky would be, near enough, where
            // the dome StuffSky draws does not reach.
            const u32 sky = C2D_Color32(0x8c, 0xa8, 0xc8, 0xFF);

            if (kDown & KEY_START) break;
            // ZL and ZR: the track before or after it on the card. The
            // Begin of unloading closes this one, as the game does between
            // races, and the other loads in its place while the loop waits.
            if (kDown & (KEY_ZL | KEY_ZR)) {
                int next = trackview_next_track(g_track.track,
                                                (kDown & KEY_ZR) ? 1 : -1);

                if (next != g_track.track) {
                    trackview_switch(&g_track, next);
                    logTrackView("switched to");
                }
            }
            hidCircleRead(&pad);
            trackview_input(&g_track, kDown, hidKeysHeld(), pad.dx, pad.dy,
                            RealTimeElapsed);

            C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
            // The last frame is drawn now, and its depth is still there:
            // the sun's Z rects, before the clear takes it.
            trackview_read_depth(&g_track, top);
            if (g_track.probe[0]) {
                logLine("sun %s", g_track.probe);
                g_track.probe[0] = '\0';
            }
            trackview_draw_envmap(&g_track);
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
            devLog(2, "track drew %d of %d (%d in place, %d sky), %d "
                   "tris, cull zone %d",
                   g_track.drawn, g_track.drawInfos, g_track.drawnInPlace,
                   g_track.skyDrawn, g_track.drawnTris,
                   (int)CurrentZoneNumber);
            if (g_track.listFrame) {
                logLine("track drew: %s", g_track.drawList);
                logLine("track frame %lu, eFrameCounter's",
                        (unsigned long)g_track.fogFrame);
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
            devLog(9, "sun %d quads (%d failed), last at %.0f %.0f alpha "
                   "%d; Z rect at %d %d, %d read back, %d of it sky",
                   g_track.sunQuads, g_track.sunQuadsFailed,
                   (double)g_track.sunAt[0], (double)g_track.sunAt[1],
                   g_track.sunAlpha, g_track.sunRectX, g_track.sunRectY,
                   g_track.sunRects, g_track.sunSky);
            devLog(10, "fog %s, mode %d, %06lx x%.3f from %.1f, root %.20s "
                   "+ %d; keep at 250..4000 %.3f %.3f %.3f %.3f %.3f, sky "
                   "%.3f; %d view, %d unfit",
                   g_track.fogOn ? "on" : "off", g_track.fogMode,
                   (unsigned long)g_track.fogColour,
                   (double)g_track.fogAmount, (double)g_track.fogStart,
                   g_track.fogRegion ? g_track.fogRegion : "none",
                   g_track.fogHits, (double)g_track.fogKeep[0],
                   (double)g_track.fogKeep[1], (double)g_track.fogKeep[2],
                   (double)g_track.fogKeep[3], (double)g_track.fogKeep[4],
                   (double)g_track.fogSkyKeep, g_track.fogViews,
                   g_track.fogUnfit);

            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            char title[32];

            snprintf(title, sizeof title, "TRACK VIEWER  TRACKB%d",
                     g_track.track);
            drawBotPanel(&ui, title,
                         g_track.loaded
                             ? "The scenery the game's own cull picks, "
                               "prelit, in the engine's draw order. "
                               "Numbers go to the debug log."
                             : g_track.note,
                         1.0f,
                         "Pad fly  ABXY look  L/R down, up  D-pad speed, "
                         "stop  ZL/ZR track");
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
    if (soundUp) {
        JBStreamStats js;
        jbstream_stats(&js);
        logLine("jukebox stream: %u pairs read, %u samples queued, "
                "%u played, volume %.3f",
                (unsigned)js.pairsRead, (unsigned)js.samplesQueued,
                (unsigned)js.samplesPlayed, (double)js.mix);
    }
    jb_music_stop(&g_jukebox);
    jb_close(&g_jukebox.jukebox);
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
