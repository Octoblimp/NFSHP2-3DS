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
// screen the player sees -- on this disc the language screen, then
// BootAutoload, then the title screen, then the main menu.
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
#include <signal.h>
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
#include "bmath.h"
#include "bmem.h"
#include "heapmap.h"
#include "bmenu.h"
#include "bsnd.h"
#include "bslotpool.h"
#include "bsound.h"
#include "bticker.h"
#include "c3dwrap.h"
#include "bumpercam.h"
#include "rvmcam.h"
#include "camera.h"
#include "cameracoord.h"
#include "democam.h"
#include "demomode.h"
#include "dmreplay.h"
#include "drivecam.h"
#include "drivetarget.h"
#include "cammover.h"
#include "bscreens.h"
#include "bcarsel.h"
#include "btracksel.h"
#include "nfsrewards.h"
#include "bsetup.h"
#include "carcontroller.h"
#include "cardamage.h"
#include "cardamageabove.h"
#include "estripdata.h"
#include "cardriver.h"
#include "carinfo.h"
#include "carinit.h"
#include "carloader.h"
#include "carmodes.h"
#include "carrenderinfo.h"
#include "carsound.h"
#include "enginesound.h"
#include "carstate.h"
#include "cartriggereffect.h"
#include "characterinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "collisionsound.h"
#include "configitems.h"
#include "debugmenu.h"
#include "lobby.h"
#include "lockhash.h"
#include "nameentry.h"
#include "audiooptions.h"
#include "displayoptions.h"
#include "joyconfig.h"
#include "helpglyph.h"
#include "credits.h"
#include "netrace.h"
#include "netstep.h"
#include "wireless.h"
#include "wirelesstest.h"
#include "cop.h"
#include "copdriver.h"
#include "copmgr.h"
#include "playercop.h"
#include "pursuit.h"
#include "pursuitchopper.h"
#include "pullover.h"
#include "pursuitspeech.h"
#include "fillerspeech.h"
#include "racespeech.h"
#include "nisinfo.h"
#include "nismanager.h"
#include "playernis.h"
#include "chopper.h"
#include "choppersound.h"
#include "barricade.h"
#include "difficultyinfo.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "edisplay.h"
#include "eenvmap.h"
#include "elight.h"
#include "elightflare.h"
#include "emath.h"
#include "emodel.h"
#include "esolid.h"
#include "eventmgr.h"
#include "eventtree.h"
#include "eventtreeview.h"
#include "eview.h"
#include "gamedata.h"
#include "fernshaker.h"
#include "fesound.h"
#include "flailer.h"
#include "flailerwrap.h"
#include "frameprof.h"
#include "fred.h"
#include "fredend.h"
#include "fredevent.h"
#include "fredrace.h"
#include "frontres.h"
#include "gameflow.h"
#include "capture.h"
#include "hangwatch.h"
#include "threadguard.h"
#include "coresample.h"
#include "heapcfg.h"
#include "helisheet.h"
#include "helpmenu.h"
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
#include "joylog.h"
#include "joyhid.h"
#include "joypad.h"
#include "jbstream.h"
#include "jukebox.h"
#include "songmon.h"
#include "sound.h"
#include "sound3d.h"
#include "soundscape.h"
#include "sedwedge.h"
#include "speechmgr.h"
#include "speechconv.h"
#include "spch.h"
#include "speechnoise.h"
#include "selcam.h"
#include "player.h"
#include "playerfinish.h"
#include "cartypeinfo.h"
#include "avimovie.h"
#include "mainloop.h"
#include "mellowmover.h"
#include "munition.h"
#include "p32.h"
#include "pausemenu.h"
#include "pauseoptions.h"
#include "pausereplay.h"
#include "endevent.h"
#include "endgame.h"
#include "endresults.h"
#include "endtimes.h"
#include "highscore.h"
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
#include "quickrace.h"
#include "race.h"
#include "racecoord.h"
#include "radialblur.h"
#include "raceevent.h"
#include "eventrace.h"
#include "raceinit.h"
#include "raceovermsg.h"
#include "racerun.h"
#include "racesplit.h"
#include "raceupdate.h"
#include "raceparams.h"
#include "rcauto.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "realtime.h"
#include "replay.h"
#include "replaymgr.h"
#include "replayscreen.h"
#include "resource.h"
#include "sinit.h"
#include "shake.h"
#include "skids.h"
#include "smokeable.h"
#include "spikestrip.h"
#include "startrace.h"
#include "terraineffect.h"
#include "terraintype.h"
#include "tiresound.h"
#include "texpack.h"
#include "texturepack.h"
#include "texturestream.h"
#include "topology.h"
#include "track.h"
#include "trackcarcam.h"
#include "trackflycam.h"
#include "sky.h"
#include "sun.h"
#include "efog.h"
#include "weatherman.h"
#include "trackflow.h"
#include "trackgraph.h"
#include "trackview.h"
#include "trafficcar.h"
#include "trafficdriver.h"
#include "traffictele.h"
#include "uirender.h"
#include "vclip.h"
#include "vtable.h"
#include "warp.h"
#include "wheel.h"
#include "world.h"
#include "worldobject.h"
#include "zonecam.h"
#include "zonepreview.h"

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
    // Where You're The Cop's Setup goes: BeTheCopSetup on
    // RaceSetupBaseClass.
    { "Be The Cop Setup",        BSETUP_SCREEN_BE_THE_COP_SETUP,
      bsetup_btc_callback },
    // Both Mode Selects' Challenge (ChallengeScreen), and the four its
    // Setup goes to by race type -- the same RaceSetupBaseClass screen
    // under four more names.
    { "Challenge",               BSETUP_SCREEN_CHALLENGE,
      bsetup_challenge_callback },
    { "Single Race Setup",       BSETUP_SCREEN_RACE_SETUP,
      bsetup_single_race_callback },
    { "Knockout Setup",          BSETUP_SCREEN_RACE_SETUP,
      bsetup_knockout_callback },
    { "Lap Knockout Setup",      BSETUP_SCREEN_RACE_SETUP,
      bsetup_lap_knockout_callback },
    { "Free Run Setup",          BSETUP_SCREEN_RACE_SETUP,
      bsetup_free_run_callback },
    // Options' Load/Save (memcard.c's LoadSaveWrapper): Save, Load, and
    // the Autosave line, onto settings.db in sdmc:/NFSHP2/SAVES.
    { "Phils Load Save",         0x9829bfabu,
      bgf_load_save_callback },

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
    { "View Event Tree",         0x147f8a59u,   // tEventTreeView
      eventtreeview_screen_callback },
    { "Audio Options",           AUDIOOPTS_SCREEN,   // AudioOptionsScreen
      audioopts_callback },
    { "JukeBox Music",           JUKEBOX_SCREEN,   // JukeBoxMusicScreen
      jukeboxscreen_callback },
    { "Joystick PreConfig",      JOYPRECONFIG_SCREEN,   // JoystickPreConfig
      joypreconfig_callback },
    { "Joystick Config Port1",   JOYCONFIG_SCREEN,   // JoystickConfigScreen
      joyconfig_callback },
    { "Display Options",         DISPLAYOPTS_SCREEN,   // tDisplayOptionsScreen
      displayopts_callback },
    { "Customize P1 HUD",        CUSTOMHUD_SCREEN,   // tCustomizeHUDScreen
      customhud_callback },
    { "NameEntry",               NAMEENTRY_SCREEN,   // NameEntry
      nameentry_callback },
    { "Credits",                 CREDITS_SCREEN,   // CreditsScreen
      credits_screen_callback },
    // Its two scrollers share one Flailer screen, and its four movies play
    // on the title's; each callback picks what it is by the name.
    { "EACredits",               CREDITS_SCROLLER_SCREEN,   // CreditsScroller
      credits_scroller_callback },
    { "BBGCredits",              CREDITS_SCROLLER_SCREEN,   // CreditsScroller
      credits_scroller_callback },
    { "Credits FE Movie",        BGF_SCREEN_TITLE,   // the movie player
      credits_movie_callback },
    { "Credits Reward movie",    BGF_SCREEN_TITLE,
      credits_movie_callback },
    { "BBG Credits movie",       BGF_SCREEN_TITLE,
      credits_movie_callback },
    { "BBG Creation movie",      BGF_SCREEN_TITLE,
      credits_movie_callback },
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
      btracksel_screen_callback },
    // Same Flailer screen as "Language Options Pre FE" above, entered under
    // a second name from the Options menu. The ELF registers both, to one
    // Callback that picks the class by name; this one's slide-on is still
    // to be ported.
    { "Language Options",        0x632b068eu,   // LanguageOptionsScreen
      bgf_language_screen_callback },

    // The race's, in INGAMEB: the screens EnableStartRaceScreens puts over
    // the fly-by (startrace.c). The Blurb is the objective, or You're The
    // Cop's controls; the two-player cop screen is each player's lines.
    // The Starting Grid is every race's but You're The Cop's and Free
    // Run's; the letterbox is up when no other is.
    { "Pre Race Blurb",          STARTRACE_SCREEN_BLURB,
      pre_race_blurb_callback },
    { "Pre Race 2P Be A Cop",    STARTRACE_SCREEN_2P_BEACOP,
      pre_race_2p_be_a_cop_callback },
    { "Pre Race Stats",          STARTRACE_SCREEN_STATS,
      pre_race_stats_callback },
    { "Pre Race Letterbox",      STARTRACE_SCREEN_LETTERBOX,
      pre_race_letterbox_callback },
    // RCSTATE_PAUSE's (pausemenu.c), and the pages it leads to
    // (pauseoptions.c). Its "Debug Menu" row never shows on the retail
    // disc, so that screen is not registered.
    { "Pause Menu",              PAUSE_MENU_SCREEN,
      pause_menu_callback },
    { "Pause Options",           PAUSE_OPTIONS_SCREEN,
      pause_options_callback },
    { "Pause audio",             PAUSE_AUDIO_SCREEN,
      pause_audio_callback },
    { "Pause display",           PAUSE_DISPLAY_SCREEN,
      pause_display_callback },
    { "Race Objective",          STARTRACE_SCREEN_BLURB,
      pause_race_objective_callback },
    { "Pause BAC controls",      STARTRACE_SCREEN_BLURB,
      pause_view_controls_callback },
    // The end of the race (endgame.c): EndGameScreens' list, each on the
    // one callback that makes its class by name. The four reward screens
    // share one Flailer screen. The classes not ported yet are the bare
    // EndGameMenusBase, which SELECT passes and BACK walks back from. The
    // Lap Times screens View Lap Times goes to have their own callback
    // (endtimes.c). Autosave is memcard.c's Autosaver, on BootAutoload's
    // Flailer screen, which INGAMEB has a copy of.
    { "Autosave",                BGF_SCREEN_BOOT_AUTOLOAD,
      bgf_autosave_callback },
    { "Points Rewards",          END_GAME_REWARDS_SCREEN,
      endgame_screen_callback },
    { "Task Rewards",            END_GAME_REWARDS_SCREEN,
      endgame_screen_callback },
    { "Events Unlocked",         END_GAME_REWARDS_SCREEN,
      endgame_screen_callback },
    { "Reward menu",             END_GAME_REWARDS_SCREEN,
      endgame_screen_callback },
    { "Race Results",            END_GAME_RACE_RESULTS_SCREEN,
      endgame_screen_callback },
    { "Tourney Standings",       END_GAME_TOURNEY_SCREEN,
      endgame_screen_callback },
    { "Best Lap Times",          END_GAME_BEST_LAP_SCREEN,
      endgame_screen_callback },
    { "Best Total Times",        END_GAME_BEST_TOTAL_SCREEN,
      endgame_screen_callback },
    { "End Game Menu",           END_GAME_MENU_SCREEN,
      endgame_screen_callback },
    { "Be The Cop Results 1P",   END_GAME_BTC_1P_SCREEN,
      endgame_screen_callback },
    { "Be The Cop Results 2P",   END_GAME_BTC_2P_SCREEN,
      endgame_screen_callback },
    { "Lap Times 1P",            END_GAME_LAP_TIMES_1P_SCREEN,
      lap_times_display_callback },
    { "Lap Times 2P",            END_GAME_LAP_TIMES_2P_SCREEN,
      lap_times_display_callback },
    // The port's own, which FRONTB gains at boot (debugmenu.h).
    { BGF_DEBUG_MENU_NAME,       DEBUGMENU_SCREEN,
      debugmenu_callback },
    { DEBUGMENU_RACE_NAME,       DEBUGMENU_RACE_SCREEN,
      debugmenu_race_callback },
    // The port's too: the Local Wireless lobby, the main menu's fourth row
    // (TASKS 63), where the host's setup comes back to (bsetup.c's
    // twoPlayersCarSelect). It has no Flailer screen of its own, so its
    // popups sit on black, as BootAutoload's do.
    { LOBBY_SCREEN_NAME,         0,
      lobby_callback },
    // And the wait for the other consoles' cars or the host's race
    // (netrace.h), the same way.
    { NETRACE_SCREEN_NAME,       0,
      netrace_callback },
};
#define NUM_SCREENS ((int)(sizeof(kScreens) / sizeof(kScreens[0])))

// LaunchFrontendMenus (retail's 0x0016f950), the boot sequence itself.
// Pushed in this order, entered from the top. Retail pushes BootAutoload
// before the language screen, the demo (0x0016aa40) after it: the language
// screen resets Fred to its defaults when a language is chosen, so it has
// to come first, and the card's load after it (TASKS 56).
static const BBootStage kBootStages[] = {
    { "Title Screen",            bgf_should_see_title_sequence },
    { "Legal MumboJumbo",        bgf_should_see_legal_mumbo_jumbo },
    { "BootAutoload",            bgf_should_see_autoload },
    { "Language Options Pre FE", bgf_should_see_language_select },
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

// FRONTB and INGAMEB as the UI holds them: both read at boot and kept.
// Retail loads FRONTB with the frontend and INGAMEB with the track's
// common files, and unloads each with them.
static UIBundle* g_frontBundle;
static UIBundle* g_ingameBundle;

// A bundle's screens as its load leaves them: every one down.
static void hideBundleScreens(UIBundle* b)
{
    if (b == NULL || !b->hasUI) return;
    for (uint32_t i = 0; i < b->ui.numScreens; i++)
        b->ui.screens[i].visible = false;
}

static void flowBeginUnloadingTrackCommon(BGameFlow* gf)
{
    gTrackFlowGameFlow = gf;
    BeginGameFlowUnloadingTrackCommon();
    // INGAMEB's screens go with its file, and the frontend that loads next
    // has FRONTB's all down. Here both stay, and a find takes FRONTB's of
    // the three screens they share: Quit Race's popup, KEEP_VISIBLE, is
    // FRONTB's POPUP, still up. The LOADING screen is GLOBALB's.
    hideBundleScreens(g_ingameBundle);
    hideBundleScreens(g_frontBundle);
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
// FlailerScreenList's tHelpMenu (+452), the HELP panel Y summons
// (helpmenu.h).
static HelpMenu g_help;
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

// The frontend's 3D view, the car select's (trackview_attach_frontend).
// FRONTB as the UI holds it, whose engine half frontres loads, is with
// INGAMEB's, above.
static TrackView g_feView;

// ------------------------------------------------------- the run log
//
// sdmc:/nfshp2_debug.txt, the same arrangement NFSU2-3DS uses: the console
// output goes to the bottom screen where only a human can read it, so
// everything worth grepping is also appended here and
// tools/run_azahar_test.ps1 reads it back after an emulator run. It is how
// "did it boot, did the movie play, did it reach the menu" gets answered
// without anyone watching the window.
static FILE* g_log;

// abort() raises SIGABRT and never runs atexit: the lines the writer has
// not put on the card yet go there first, before the process does.
static void logOnAbort(int sig)
{
    (void)sig;
    logwriter_drain();
}

static void logOpen(void)
{
    // Only when the config file says "DebugLog 1", or "GPULog 1" or
    // "PauseLog 1", whose timing frames' and pause frames' lines have
    // nowhere else to go (configitems.h). The words are read again, and
    // logged, by readConfigItems.
    {
        static char text[4096];
        FILE*  f = fopen(CONFIG_ITEMS_FILE, "rb");
        size_t n;
        int    skipFE = 0;

        if (f != NULL) {
            n = fread(text, 1, sizeof text - 1, f);
            fclose(f);
            text[n] = '\0';
            config_items_apply_text(text, &skipFE, NULL);
        }
    }
    if (ConfigDebugLog || ConfigGpuLog || ConfigPauseLog)
        g_log = fopen("sdmc:/nfshp2_debug.txt", "w");
    // The lines go to the card from a thread of their own (logwriter.h):
    // written in place, a race's once-a-second lines cost the device that
    // second's frame, and more while the card was slow.
    if (g_log) {
        WorldStepProfOn = 1;    // worldstep's timings, for logWorldStep
        logwriter_start(g_log);
        atexit(logwriter_stop);
        signal(SIGABRT, logOnAbort);
    }
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
    //
    // The main menu's rows are the port's to lay out (debugmenu.h, TASKS
    // 68): a row highlighted is scrolled into the window before the screen
    // moves the brackets to its mask, and the window laid out again after,
    // as SelectionSet has then shown the mask of the row left.
    bool mainMenu = msg == BMSG_MENUITEM_HIGHLIGHT && data && g_flow.screen
                    && g_flow.screen->hash == BGF_SCREEN_NEW_MAIN_MENU;
    int  top      = mainMenu ? debugmenu_main_show(data->itemHash) : -1;
    if (data) bgf_send(&g_flow, msg, data);
    if (mainMenu) {
        static int shownTop = -1;
        debugmenu_main_show(data->itemHash);
        if (top >= 0 && top != shownTop) {
            logLine("main menu: rows from %d", top);
            shownTop = top;
        }
    }
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

// That bSound (0x00336900, gp-13696): the regions, the samples and the
// voice records over gSnd (bsound.h).
static BSound gSound;

// Fred (0x002fc050), the frontend database (fred.h), which the card loads
// over whole. The jukebox and the volumes read its audio options at +148.
#define FRED_AUDIO_OPTIONS offsetof(FrontendDatabase, AudioOptionsScreenData)

// sound::jukebox (0x003115d0), the EA TRAX player, and what it asks of the
// game. The flow's CurrentGameFlowState is its gp-21420; the VBlank count
// is FrameCounter; nothing sets cops yet.
static JBSound g_jukebox;

static int      jbState(void* c) { (void)c; return g_flow.current; }
// TheLanguageManager's CurrLanguage, for GetSkinNumber's cop skins.
static int32_t  currLanguage(void) { return g_flow.currLanguage; }
static int      jbMaxCops(void* c) { (void)c; return 0; }
static uint32_t jbVBlank(void* c) { (void)c; return (uint32_t)FrameCounter; }

static const JBWorld kJukeboxWorld = {
    NULL, jbState, jbMaxCops, jbVBlank,
};

// Sound.obj's statics (sound.h): the game's own sound module over gSound,
// the regions it loads and the per-frame update, and what it reads of the
// game. The modules it drives that are not ported yet stay NULL.
static SoundModule gSoundModule;
static char        gSoundDir[GAMEDATA_MAX_PATH];

static int   sndGameState(void* c) { (void)c; return g_flow.current; }
static int   sndPaused(void* c) { (void)c; return is_game_flow_paused(); }
static float sndDt(void* c) { (void)c; return WorldTimeElapsed; }
// The wait loops step bSound once a vertical blank. The port's banks load
// in the call that asks for them, so there is nothing to wait a blank
// for: each ask is a new one.
static uint32_t sndVBlank(void* c)
{
    static uint32_t n;
    (void)c;
    return ++n;
}

// bFileExists("sound\\NAME.msh"): the card has NAME.SBK where the disc has
// NAME.MSH and .MSB (tools/audio_pack.py).
static int sndFileExists(void* c, const char* path)
{
    char        file[GAMEDATA_MAX_PATH + 40];
    const char* name = strrchr(path, '\\');
    const char* dot;
    struct stat st;
    (void)c;
    name = name ? name + 1 : path;
    dot = strrchr(name, '.');
    snprintf(file, sizeof(file), "%s/%.*s.SBK", gSoundDir,
             (int)(dot ? dot - name : (ptrdiff_t)strlen(name)), name);
    return stat(file, &st) == 0;
}

// eFlashScreen's colour is a debug build's cue; the log says why.
static void sndFlash(void* c, int r, int g, int b, const char* why,
                     float seconds)
{
    (void)c; (void)seconds;
    logLine("sound: flash %d,%d,%d \"%s\"", r, g, b, why);
}

static int sndRaceState(void* c)
{
    (void)c;
    return pRaceCoordinator
        ? (int)racecoordinator_get_current_state(pRaceCoordinator) : -1;
}

// The players shown: a wireless race's console hears its own alone
// (player.h).
static int sndNumPlayers(void* c) { (void)c; return PLAYER_NUM_SHOWN(); }

static void sndPlayerZone(void* c, int i, int* muffle, int* zone,
                          float* volume)
{
    // gp-20928: by index, the order they were made.
    const struct Player* p = player_shown(i);
    (void)c;
    if (p == NULL) return;          // the port's; retail reads it untested
    *muffle = p->bZoneMuffleSound;
    *zone   = p->nZoneCurrent;
    *volume = p->fZoneMuffleVolume;
}

static const char* sndTrackRegion(void* c)
{
    (void)c;
    return CurrentTrackInfo ? CurrentTrackInfo->SoundRegion : NULL;
}

// The driver's car type's Sound, the name of its engine's region.
static const char* sndDriverRegion(void* c, int driver)
{
    const DriverInfo* d =
        race_parameters_get_driver_info_by_driver_number(driver);
    (void)c;
    if (d == NULL || d->EliminatedRank > 0) return NULL;
    return cartypeinfo_get(d->CurrentRideInfo.Type)->Sound.BaseName;
}

static int sndHelicopter(void* c)
{
    (void)c;
    return pCurrentWorld != NULL && pCurrentWorld->Helicopter != NULL;
}

static int sndJoylogReplaying(void* c) { (void)c; return Joylog_ReplayingFlag; }
static int32_t sndJoylogGet(void* c, int bits, int channel)
{
    (void)c;
    return Joylog_GetData(bits, channel);
}
static void sndJoylogAdd(void* c, int32_t value, int bits, int channel)
{
    (void)c;
    Joylog_AddData(value, bits, channel);
}

// sound3d_oneshot (14-2b), which sound::Initialize, Close, Update and
// the mutes call.
static void sndOneshotInit(void* c)   { (void)c; sound3d_oneshot_init(); }
static void sndOneshotClose(void* c)  { (void)c; sound3d_oneshot_close(); }
static void sndOneshotUpdate(void* c) { (void)c; sound3d_oneshot_update(); }
static void sndOneshotMute(void* c, int on)
{
    (void)c;
    sound3d_oneshot_mute(on);
}

// collision_sound (14-6), which LoadSoundRegionsInGame registers,
// UnLoadSoundRegions unregisters, and sound::Update and the mutes call.
static void sndCollisionRegister(void* c)   { (void)c; collision_sound_register(); }
static void sndCollisionUnregister(void* c) { (void)c; collision_sound_unregister(); }
static void sndCollisionUpdate(void* c)     { (void)c; collision_sound_update(); }
static void sndCollisionMute(void* c, int on)
{
    (void)c;
    collision_sound_mute(on);
}

// sound_scape (14-7), which sound::Update and the mutes call.
static void sndScapeUpdate(void* c) { (void)c; sound_scape_update(); }
static void sndScapeMute(void* c, int on)
{
    (void)c;
    sound_scape_mute(on);
}

// SpeechNoise (14-8a): the radio's squelch and static. Its samples are
// asked for by LoadSoundRegionsInGame and unloaded by UnLoadSoundRegions;
// sound::Update and the mutes call the rest.
static void sndNoiseRequest(void* c)
{
    (void)c;
    speechnoise_request_samples(speechnoise_get_instance());
}
static void sndNoiseUnload(void* c)
{
    (void)c;
    speechnoise_unload_samples(speechnoise_get_instance());
}
static void sndNoiseUpdate(void* c)
{
    (void)c;
    speechnoise_update(speechnoise_get_instance());
}
static void sndNoiseMute(void* c, int on)
{
    (void)c;
    speechnoise_mute(speechnoise_get_instance(), on);
}

// cSEDWedge (14-8d): made at the end of InitializeSoundDriver, updated by
// sound::Update; the gameflow's language hooks load and unload its files.
static void sndSedCreate(void* c)
{
    (void)c;
    sedwedge_create();
}
static void sndSedUpdate(void* c)
{
    SedWedge* w = sedwedge_sound_instance();
    (void)c;
    if (w != NULL) sedwedge_update(w);
}

// The finish's ClearEventQueue, on the wedge when there is one.
static void speechClearEventQueue(void)
{
    SedWedge* w = sedwedge_sound_instance();
    if (w != NULL) sedwedge_clear_event_queue(w);
}

// speech::mgr_t (14-9): sound::Update runs its update and the mutes its
// Mute; the race's ends and the cop manager flush its queue, the cop
// manager shuffles its voices, and the jukebox and the cop manager's
// filler speech wait on previousSedPlaybackState.
static void sndSpeechUpdate(void* c)
{
    (void)c;
    speechmgr_update(speechmgr_get_instance());
}
static void sndSpeechMute(void* c, int on)
{
    (void)c;
    speechmgr_mute(speechmgr_get_instance(), on);
}
static void sndSpeechFlush(void* c)
{
    (void)c;
    speechmgr_flush_queue(speechmgr_get_instance());
}
static int sndSpeechSedPlaying(void* c)
{
    (void)c;
    return speechmgr_get_instance()->previousSedPlaybackState;
}
static void speechFlushQueue(void)
{
    speechmgr_flush_queue(speechmgr_get_instance());
}
static void speechAllocateVoices(void)
{
    speechmgr_allocate_voices(speechmgr_get_instance());
}
static int32_t speechPlaybackState(void)
{
    return speechmgr_get_instance()->previousSedPlaybackState;
}

// The chases' raises that go straight to speech::mgr_t (14-10a), each with
// its arguments in retail's order.
static void speechRaiseCrashTow(uint32_t was, uint32_t now)
{
    speechmgr_raise_crash_tow(speechmgr_get_instance(), was, now);
}
static void speechRaiseCrash(uint32_t was, uint32_t now)
{
    speechmgr_raise_crash(speechmgr_get_instance(), was, now);
}
static void speechRaiseFlatTire(uint32_t was, uint32_t now)
{
    speechmgr_raise_flat_tire(speechmgr_get_instance(), was, now);
}
static void speechRaiseSuperRequest(uint32_t speaker)
{
    speechmgr_raise_super_request(speechmgr_get_instance(), speaker);
}
static void speechRaisePursuitCopHit(uint32_t speaker, int32_t where)
{
    speechmgr_raise_pursuit_cop_hit(speechmgr_get_instance(), speaker, where);
}
static void speechRaiseSuspectCrashTraffic(uint32_t speaker, int32_t b)
{
    speechmgr_raise_suspect_crash_traffic(speechmgr_get_instance(), speaker,
                                          b);
}
static void speechRaiseSpikeStripTireBlow(uint32_t speaker, int32_t b)
{
    speechmgr_raise_spike_strip_tire_blow(speechmgr_get_instance(), speaker,
                                          b);
}
static void speechRaiseRequestAnotherRoadblock(uint32_t speaker, int32_t b)
{
    speechmgr_raise_request_another_roadblock(speechmgr_get_instance(),
                                              speaker, b);
}
static void speechRaiseSpikeStripRequest(uint32_t speaker, int32_t b)
{
    speechmgr_raise_spike_strip_request(speechmgr_get_instance(), speaker, b);
}
static void speechRaiseRoadblockRequest(uint32_t speaker, int32_t b)
{
    speechmgr_raise_roadblock_request(speechmgr_get_instance(), speaker, b);
}
static void speechRaiseDispatchRoadBlockNA(uint32_t speaker)
{
    speechmgr_raise_dispatch_road_block_na(speechmgr_get_instance(), speaker);
}
static void speechRaiseRotorRequest(uint32_t speaker, int32_t supervisor)
{
    speechmgr_raise_rotor_request(speechmgr_get_instance(), speaker,
                                  supervisor);
}
static void speechRaiseRotorConfirm(void)
{
    speechmgr_raise_rotor_confirm(speechmgr_get_instance());
}
static void speechRaiseDispatchHelicopterNA(uint32_t speaker)
{
    speechmgr_raise_dispatch_helicopter_na(speechmgr_get_instance(), speaker);
}
static void speechRaiseRacerCaught(uint32_t speaker, uint32_t n,
                                   int32_t arrestType)
{
    speechmgr_raise_racer_caught(speechmgr_get_instance(), speaker,
                                 (int32_t)n, arrestType);
}

// The reward screens' RewardCarSpeech (racespeech.h, RE-5): they don't
// read whether it was said.
static void rewardCarSpeech(int32_t carType)
{
    (void)reward_car_speech(carType);
}

// The chopper's sound (14-7): Chopper::UpdateSound and Mute, which
// sound.c calls only with a helicopter.
static void sndChopperUpdate(void* c)
{
    (void)c;
    chopper_update_sound(pCurrentWorld->Helicopter);
}
static void sndChopperMute(void* c, int on)
{
    (void)c;
    chopper_mute(pCurrentWorld->Helicopter, on);
}

// The car sounds (14-3): UpdateCarSounds, and Mute's walk of
// pCurrentWorld's CarList, each car's BaseCarSound muted through its table.
static void sndCarSoundsUpdate(void* c)
{
    (void)c;
    carsound_update_car_sounds();
}
static int sndNumCars(void* c)
{
    const Car* car;
    int n = 0;
    (void)c;
    if (pCurrentWorld == NULL) return 0;
    for (car = (const Car*)pCurrentWorld->CarList.next;
         car != (const Car*)&pCurrentWorld->CarList;
         car = (const Car*)car->Link.next)
        n++;
    return n;
}
static void* sndCarSound(void* c, int i)
{
    const Car* car;
    (void)c;
    if (pCurrentWorld == NULL) return NULL;
    for (car = (const Car*)pCurrentWorld->CarList.next;
         car != (const Car*)&pCurrentWorld->CarList;
         car = (const Car*)car->Link.next)
        if (i-- == 0) return car->pBaseCarSound;
    return NULL;
}
static void sndCarSoundMute(void* c, void* sound, int on)
{
    const VtEntry* e = vt_slot(((Sound3d*)sound)->_vtable, SOUND3D_VT_MUTE);
    (void)c;
    ((void (*)(void*, int32_t))e->fn)(vt_this(sound, e), on);
}

// joyhid's race layout, X the horn: only while the race runs, so a race's
// menus -- the pause screen's included -- keep X as the scanners' "back".
// The frontend's layout has main.c's keys: B back, X Square, Y help. In
// Be A Cop, in the player cop's car, L calls the roadblock and R the
// helicopter as well (the user's mapping of 2026-10-11).
static int32_t joyhidRaceLayout(void)
{
    // This console's player: in a wireless race the pad read here is its.
    const struct Player *p = player_shown(0);
    const tCop *cop;

    if (pRaceCoordinator == NULL)
        return JOYHID_LAYOUT_FE;
    if (racecoordinator_get_current_state(pRaceCoordinator)
        != RCSTATE_RACE_IN_PROGRESS)
        return JOYHID_LAYOUT_MENU;
    cop = copmanager_get_player_cop(pCopManager);
    if (RaceParametersBeACop && cop != NULL && p != NULL
        && cop->pMyCar == p->MyCar)
        return JOYHID_LAYOUT_COP;
    return JOYHID_LAYOUT_RACE;
}

// The help glyphs' own layout (uirender.h's gUiHelpLayoutFn): the
// Controller page's, and while a ReplayScreen is up the scanners' menu
// layout, which the replay's events alone hear -- its help's Triangle is
// X and its Square B (helpglyph.h). -1 leaves joyhidRaceLayout's.
static int32_t uiHelpLayout(void)
{
    int32_t own = joyconfig_help_layout();

    if (own >= 0)
        return own;
    if (pRaceCoordinator != NULL && pRaceCoordinator->pReplayScreen != NULL)
        return HELPGLYPH_LAYOUT_SCANNERS;
    return -1;
}

static SoundHooks gSoundHooks = {
    .game_state       = sndGameState,
    .paused           = sndPaused,
    .dt               = sndDt,
    .vblank           = sndVBlank,
    .file_exists      = sndFileExists,
    .flash            = sndFlash,
    .race_state       = sndRaceState,
    .num_players      = sndNumPlayers,
    .player_zone      = sndPlayerZone,
    .track_region     = sndTrackRegion,
    .driver_region    = sndDriverRegion,
    .helicopter       = sndHelicopter,
    .joylog_replaying = sndJoylogReplaying,
    .joylog_get       = sndJoylogGet,
    .joylog_add       = sndJoylogAdd,
    .num_cars         = sndNumCars,
    .car_sound        = sndCarSound,
    .car_sounds_update = sndCarSoundsUpdate,
    .car_sound_mute   = sndCarSoundMute,
    .oneshot_init     = sndOneshotInit,
    .oneshot_close    = sndOneshotClose,
    .oneshot_update   = sndOneshotUpdate,
    .oneshot_mute     = sndOneshotMute,
    .collision_register   = sndCollisionRegister,
    .collision_unregister = sndCollisionUnregister,
    .collision_update     = sndCollisionUpdate,
    .collision_mute       = sndCollisionMute,
    .scape_update     = sndScapeUpdate,
    .scape_mute       = sndScapeMute,
    .noise_request    = sndNoiseRequest,
    .noise_unload     = sndNoiseUnload,
    .noise_update     = sndNoiseUpdate,
    .noise_mute       = sndNoiseMute,
    .sed_create       = sndSedCreate,
    .sed_update       = sndSedUpdate,
    .speech_update    = sndSpeechUpdate,
    .speech_mute      = sndSpeechMute,
    .speech_flush     = sndSpeechFlush,
    .speech_sed_playing = sndSpeechSedPlaying,
    .chopper_update   = sndChopperUpdate,
    .chopper_mute     = sndChopperMute,
    .sound_path       = gSoundDir,
    .skip_missing     = 1,
};

// The bSample calls the race's modules make through their seams
// (playerinit.h, playerzone.h, rcstates.h): `struct bSample` there is
// bsound.h's BSample.
static struct bSample* sndGetInGameSample(const char* name)
{
    return (struct bSample*)sound_get_in_game_sample(&gSoundModule, name);
}
static void sndSampleDelete(struct bSample* s)
{
    if (s) bsample_delete((BSample*)s);
}
static float sndGetCategoryVolume(uint32_t category)
{
    return bsound_get_category_volume(&gSound, category);
}
static struct bSample* sndNewSample(void)
{
    return (struct bSample*)bsample_new(0);
}
static void sndSampleInitialize(struct bSample* s, struct bSample* from)
{
    bsample_initialize_copy((BSample*)s, (const BSample*)from);
}
static void sndSampleSetCategory(struct bSample* s, uint32_t category)
{
    bsample_set_category((BSample*)s, category);
}
static struct bSample* sndCommonRegionSample(const char* name)
{
    return (struct bSample*)bregion_sample(bsound_common_region(&gSound),
                                           name);
}
static int32_t sndSampleIsPlaying(struct bSample* s)
{
    return s != NULL && bsample_is_playing((const BSample*)s);
}
static void sndSamplePlay(struct bSample* s, float volume, float a, float b)
{
    bsample_play((BSample*)s, volume, a, b);
}
static void sndSampleSetAzimuth(struct bSample* s, uint16_t azimuth)
{
    bsample_set_azimuth((BSample*)s, azimuth);
}
static void sndSampleSetPitch(struct bSample* s, float pitch)
{
    bsample_set_pitch((BSample*)s, pitch);
}
static void sndSampleSetVolume(struct bSample* s, float volume)
{
    bsample_set_volume((BSample*)s, volume);
}
static void sndTriggerFinishLine(struct Player* p)
{
    (void)p;
    sound_trigger_finish_line_sound(&gSoundModule);
}
static void sndMuteReplay(int32_t on)
{
    sound_mute_replay(&gSoundModule, on);
    logLine("sound mute replay %d", (int)on);
}

// ReplayScreen's (72g-2): its buttons' menu effects from the common
// region, and MakeFrontendSound's.
static void replayPlaySample(const char* name, float volume)
{
    sound_play_common_region_sample(&gSoundModule, name, volume);
}

static void replayFrontendSound(int32_t event)
{
    fesound_play((int)event, NULL);
}

// The flow's tHelpMenu is g_help: IsActive, and 0x0016ca40's toggle on a
// press (1), which then answers IsActive.
static int32_t replayHelpActive(void)
{
    return helpmenu_is_active(&g_help);
}

static int32_t replayToggleHelp(const int32_t* lines, int32_t value)
{
    if (value == 1)
        helpmenu_toggle(&g_help, lines);
    return helpmenu_is_active(&g_help);
}

// SelectCarCameraMover's four (selcam.h): each a new bSample copied from
// the "FrontEnd" region's, at category 3, deleted by its destructor.
static const char* const kSelCamSample[SELCAM_SND_COUNT] = {
    "MenuCarDisplayOn", "MenuCarDisplayOff", "MenuCarDisplayActive",
    "MenuCarOrbitBump",
};
static BSample* gSelCamSample[SELCAM_SND_COUNT];

static void selcamCreate(int i)
{
    BRegion* r = bsound_region(&gSound, "FrontEnd");
    BSample* s = bsample_new(0);
    gSelCamSample[i] = s;
    bsample_initialize_copy(s, bregion_sample(r, kSelCamSample[i]));
    bsample_set_category(s, JB_CAT_MENU_SFX);
}
static void selcamDestroy(int i)
{
    if (gSelCamSample[i]) bsample_delete(gSelCamSample[i]);
    gSelCamSample[i] = NULL;
}
static void selcamPlay(int i, float volume, float a, float b)
{
    bsample_play(gSelCamSample[i], volume, a, b);
}
static void selcamStop(int i) { bsample_stop(gSelCamSample[i]); }
static void selcamSetVolume(int i, float volume)
{
    if (gSelCamSample[i]) bsample_set_volume(gSelCamSample[i], volume);
}
static void selcamSetPitch(int i, float pitch)
{
    if (gSelCamSample[i]) bsample_set_pitch(gSelCamSample[i], pitch);
}
static const SelCamSoundFns kSelCamSound = {
    selcamCreate, selcamDestroy, selcamPlay, selcamStop, selcamSetVolume,
    selcamSetPitch,
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

// SetScreenFilterPort (0x0016d4c8): only `port` drives the screen `name`
// from then on. Retail keeps it on the FlailerScreen, which lives as long
// as its pack; the port keeps it here, by the screen's hash, until set
// again. The screen's menu takes it when it is made (FlailerMenu's
// FilterPort is the screen's), and the screen's own START and BACK filter
// on it (FlailerScreen::JoyHandler). The pause sets it for its eight
// screens, so only the pad that paused drives them.
#define SCREEN_FILTERS 16
static struct {
    uint32_t hash;
    int32_t  port;
} g_screenFilter[SCREEN_FILTERS];
static int g_screenFilters;

static int32_t screenFilterPort(uint32_t hash)
{
    for (int i = 0; i < g_screenFilters; i++)
        if (g_screenFilter[i].hash == hash) return g_screenFilter[i].port;
    return -1;
}

static void hookSetScreenFilterPort(const char* name, JoystickPort port)
{
    const BScreenConfig* cfg = bgf_find_screen(&g_flow, name);
    int i;

    if (cfg == NULL) return;
    for (i = 0; i < g_screenFilters; i++)
        if (g_screenFilter[i].hash == cfg->hash) break;
    if (i == g_screenFilters) {
        if (g_screenFilters == SCREEN_FILTERS) return;
        g_screenFilters++;
    }
    g_screenFilter[i].hash = cfg->hash;
    g_screenFilter[i].port = port;
}

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
        b->menu.filterPort = screenFilterPort(cfg->hash);
        b->hasMenu = true;
        // The main menu in the port's order, Local Wireless above Options
        // (debugmenu.h): the moves follow the rows as drawn.
        if (cfg->hash == BGF_SCREEN_NEW_MAIN_MENU)
            bmenu_reorder(&b->menu, debugmenu_main_rank);
    }
}

static void hookEnterScreen(void* user, const BScreenConfig* cfg)
{
    Boot* b = (Boot*)user;
    (void)cfg;
    // On the item SCREEN_ACTIVATE's reply asked for, else the first.
    if (b->hasMenu) bmenu_activate(&b->menu, g_flow.activateItem);
}

// FlailerScreen::UnActivate's menu half, before SCREEN_UNACTIVATE: the
// item the menu is on, its UnActivate, and the delete that puts each
// label's colour back. A gray or an active-item read after this finds no
// menu, as retail's do.
static int hookCloseMenu(void* user, const BScreenConfig* cfg)
{
    Boot* b    = (Boot*)user;
    int   item = -1;
    (void)cfg;
    if (b->hasMenu) {
        item = b->menu.current >= 0 ? b->menu.current : 0;
        bmenu_unactivate(&b->menu);
        bmenu_close(&b->menu);
    }
    b->hasMenu = false;
    return item;
}

static void hookLeaveScreen(void* user, const BScreenConfig* cfg)
{
    Boot* b = (Boot*)user;
    (void)cfg;
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
        int trees = 0;
        for (bNode* n = gEventTrees.next; n != &gEventTrees; n = n->next)
            trees++;
        logLine("frontres: FRONTB %s; %d event trees, %d reward cars earned",
                ok ? "loaded" : "not loaded, no room", trees,
                (int)event_trees_num_cars_unlocked());
    }
    bootQueue((Boot*)user, path, done);
}

// LoadSoundRegionsFrontEnd (0x001ae9a0): the jukebox to the menu's list
// and the "FrontEnd" region asked for; sound::Update calls the flow back
// once it is in.
static BGameFlowDone gFeSoundsDone;

static void feSoundsLoaded(intptr_t param)
{
    BGameFlowDone done = gFeSoundsDone;
    gFeSoundsDone = NULL;
    logLine("loaded sound regions");
    if (done) done((BGameFlow*)param);
}

static void hookLoadSoundRegions(void* user, BGameFlowDone done)
{
    (void)user;
    gFeSoundsDone = done;
    sound_load_regions_front_end(&gSoundModule, feSoundsLoaded,
                                 (intptr_t)&g_flow);
}

// UnLoadSoundRegions (0x001af420): the frontend's region, or the race's.
static void soundUnloadRegions(void)
{
    sound_unload_regions(&gSoundModule);
    logLine("sound regions unloaded");
}

static void hookUnloadSoundRegions(void* user)
{
    (void)user;
    soundUnloadRegions();
}

// EndGameFlowLoadingFrontEnd's start. With the flag left set by the race's
// unloading, the platform's texture table kept the pointers it was loaded
// with, and the turntable drew with whatever texture was bound last.
static void hookFixUpTables(void* user)
{
    (void)user;
    eDisableFixUpTables = 0;
    efix_up_tables();
}

static void hookInitFrontendSounds(void* user)
{
    (void)user;
    fesound_init_frontend();
}

static void hookUnInitFrontendSounds(void* user)
{
    (void)user;
    fesound_uninit_frontend();
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

// LoadLocalizedSpeechFiles and UnLoadLocalizedSpeechFiles (sedwedge.c):
// the language's BAN and DAT under SOUND/SPEECH into the wedge. A card
// without them loads nothing.
static void hookLoadSpeech(void* user, int language)
{
    (void)user;
    sedwedge_load_localized_speech_files(language);
    logLine("speech bank %d: %s", language,
            sedwedge_sound_instance() != NULL
                && sedwedge_sound_instance()->initialized
                ? "loaded" : "not loaded");
}

static void hookUnloadSpeech(void* user)
{
    (void)user;
    sedwedge_unload_localized_speech_files();
}

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

// The controller's keys (joyconfig.h), which Fred has no room for: in
// controls.bin beside settings.db, written with its every save and read
// with its every load (hookFredLoaded). No file, or not one joyhid takes,
// is the defaults.
#define CONTROLS_FILE SAVES_DIR "/controls.bin"

static void controlsSave(void)
{
    uint8_t buf[JOYHID_FILE_SIZE];
    FILE*   f;
    size_t  put;

    joyhid_bindings_pack(&gJoyHidBindings, buf);
    f = fopen(CONTROLS_FILE, "wb");
    if (!f) {
        logLine("memcard: could not open %s", CONTROLS_FILE);
        return;
    }
    put = fwrite(buf, 1, sizeof buf, f);
    if (fclose(f) != 0 || put != sizeof buf) {
        logLine("memcard: could not write %s", CONTROLS_FILE);
        return;
    }
    logLine("memcard: saved %s", CONTROLS_FILE);
}

static void controlsLoad(void)
{
    uint8_t buf[JOYHID_FILE_SIZE + 1];
    FILE*   f = fopen(CONTROLS_FILE, "rb");
    size_t  got;

    if (!f) {
        joyhid_default_bindings(&gJoyHidBindings);
        logLine("memcard: no %s, the default keys", CONTROLS_FILE);
        return;
    }
    got = fread(buf, 1, sizeof buf, f);
    fclose(f);
    if (!joyhid_bindings_unpack(buf, (uint32_t)got, &gJoyHidBindings)) {
        joyhid_default_bindings(&gJoyHidBindings);
        logLine("memcard: %s is not one (%u bytes), the default keys",
                CONTROLS_FILE, (unsigned)got);
        return;
    }
    logLine("memcard: loaded %s", CONTROLS_FILE);
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
    if (!strcmp(c->name, BMC_SAVE_NAME)) controlsSave();
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
            // What the saver reads to ask before overwriting (+1460).
            fs->fileExists = fs->lastError == BMC_OK;
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
    sound_set_audio_mode(&gSoundModule, mode);
    logLine("audio options loaded: mode %d", mode);
    controlsLoad();
}

// FlailerSetLanguageID: the Load/Save screen's Autosave line.
static void hookSetLanguageId(void* user, uint32_t screen, uint32_t object,
                              int id)
{
    (void)user;
    flailer_set_language_id(screen, object, (uint32_t)id);
}

// FrontendDatabase::InitWithDefaults' calls out (fred.h): the audio
// options' defaults (0x001ef1c8), which want the jukebox's tunes, and
// GetTranslatedString (0x0021e560) for the two players' default names.
static void fredAudioDefaults(uint8_t* ao)
{
    jb_audio_init_with_defaults(&g_jukebox, ao,
                                sound_get_audio_mode(&gSoundModule));
}

// Retail's answer is the table's own string, whole. At 64 bytes the
// Credits' lines lost their ends: their markup takes 39 of them
// ("$RGB(134,96,48)$FONT(FONT_IMPACTNORMAL)Senior Development Direc").
static const char* fredTranslate(int32_t id)
{
    static char text[512];
    if (!g_boot.ui || !g_boot.ui->hasLang) return NULL;
    if (langtab_copy(&g_boot.ui->lang, id, text, sizeof(text)) == 0)
        return NULL;
    return text;
}

// GetTranslatedString for the race-over overlay (raceovermsg.c), whose
// strings ran past fredTranslate's 64 bytes then (German's 59017 is 73).
static const char* raceOverTranslate(int32_t id)
{
    static char text[256];
    if (!g_boot.ui || !g_boot.ui->hasLang) return NULL;
    if (langtab_copy(&g_boot.ui->lang, id, text, sizeof(text)) == 0)
        return NULL;
    return text;
}

// GetTranslatedString for EventTree::SetRace (eventrace.c): the reward's
// name, then the event's description, which can run past the other
// buffers before it is cut to the objective's 511.
static const char* eventRaceTranslate(int32_t id)
{
    static char text[1024];
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

// SeedRandomNumber (0x0012ee30), which InitializeEverything runs after
// InitJoylog and before LoadConfig. The seed is the ticker plus 0x12345678,
// which AddData logs to the joylog, or the joylog's own when one is
// replaying; on a retail console Joylog::Init leaves pRepeat NULL, so the
// ticker it is and the log takes nothing. Every draw on bDefaultSeed comes
// after it -- Quick Race's track (PickTrackNumberForExpressGame) and car
// (GenerateRandomRideInfo) among them -- so without it each boot drew the
// same ones.
static void seedRandomNumber(void)
{
    uint32_t seed;

    if (Joylog_ReplayingFlag) {
        seed = (uint32_t)Joylog_GetData(32, 0);
    } else {
        seed = bGetTicker() + 0x12345678u;
        Joylog_AddData((int32_t)seed, 32, 0);
    }
    bSetRandomSeed(seed, &bDefaultSeed);
    logLine("seed: %08lx", (unsigned long)seed);
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

// The heap in pieces (heapmap.h): each free piece of 256 KB or more and
// what is in use before it. A second race's bundles need theirs whole.
static void logHeapLine(const char* text) { logLine("%s", text); }
static void logHeapMap(void) { heapmap_lines(logHeapLine, 256u * 1024); }

// bMalloc's last word before its abort (bmem.h): the map, to stderr, the
// file a device keeps when the debug log is off (nfshp2_stderr.txt).
static void stderrHeapLine(const char* text)
{
    fprintf(stderr, "%s\n", text);
}

static void bMallocFailed(int size, const char* name)
{
    HeapMap hm;

    (void)size;
    (void)name;
    heapmap_take(&hm);
    fprintf(stderr, "heap: %lu KB used, %lu KB free, %lu KB the largest of "
            "%lu pieces\n", (unsigned long)hm.used / 1024,
            (unsigned long)hm.free / 1024, (unsigned long)hm.largest / 1024,
            (unsigned long)hm.pieces);
    heapmap_lines(stderrHeapLine, 64u * 1024);
    fflush(stderr);
}

// The pool's top (bmem.h): the image's temporaries, from the linear heap.
// They live through a load, and the linear heap is near empty then (63 MB
// free as a track's own load begins, on Azahar's smallest); the view's
// meshes and textures come after the bundles are in, the temporaries
// gone. Never the last LINEAR_TOP_SPARE of it, for the GPU's: a block
// that would take that comes from malloc's, as every block did before.
#define LINEAR_TOP_SPARE (8u * 1024 * 1024)

extern u32 __ctru_linear_heap;
extern u32 __ctru_linear_heap_size;

static u32 g_topLive, g_topLiveMost;

static void* bMallocTop(size_t size, size_t align)
{
    void* p;

    if ((size_t)linearSpaceFree() < size + LINEAR_TOP_SPARE) return NULL;
    p = linearMemAlign(size, align);
    if (p != NULL) {
        g_topLive += linearGetSize(p);
        if (g_topLive > g_topLiveMost) g_topLiveMost = g_topLive;
    }
    return p;
}

static int bFreeTop(void* p)
{
    u32 a = (u32)(uintptr_t)p;

    if (a < __ctru_linear_heap
        || a - __ctru_linear_heap >= __ctru_linear_heap_size)
        return 0;
    g_topLive -= linearGetSize(p);
    linearFree(p);
    return 1;
}

static void logTopLine(const char* text)
{
    logLine("race: top block %s", text);
}

static void hookTrace(void* user, const char* line)
{
    (void)user;
    // Each state's Begin carries the malloc heap's use: the track's bundles
    // are the largest blocks the port asks for, and a bMalloc that fails
    // aborts.
    if (strncmp(line, "begin ", 6) == 0) {
        struct mallinfo mi = mallinfo();
        HeapMap         hm;

        heapmap_take(&hm);
        logLine("flow %s (heap: %lu KB used, %lu KB free, %lu KB the "
                "largest of %lu pieces; linear %lu KB free)",
                line, (unsigned long)mi.uordblks / 1024,
                (unsigned long)(g_heapInfo.heapGot - mi.uordblks) / 1024,
                (unsigned long)hm.largest / 1024, (unsigned long)hm.pieces,
                (unsigned long)linearSpaceFree() / 1024);
        if (strstr(line, "TRACK_SPECIFIC") != NULL) logHeapMap();
        return;
    }
    // A screen's TICK is every frame's, and would be most of the log: the
    // host harness reads the trace whole, the card only what changes.
    if (strncmp(line, "msg ", 4) == 0) {
        const char* n = strrchr(line, ' ');

        if (n && atoi(n + 1) == BMSG_SCREEN_TICK) return;
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

// The same blurb with the port's own sentence: LanguageID 0, so the
// renderer draws the object's string, and the sentence in it.
static void hookSetBlurbText(void* user, uint32_t screen, const char* text)
{
    Boot*      b  = (Boot*)user;
    BUI*       ui = NULL;
    BUIScreen* s  = uirender_find_screen(b->ui, screen, &ui);
    int32_t    idx;
    if (!s || !ui) return;
    idx = bui_find_object(ui, s, BSCR_OBJ_SCROLLING_TEXT, BUI_TYPE_TEXT);
    if (idx < 0) return;
    bui_set_text_language(ui, (uint32_t)idx, 0);
    bui_set_text_string(ui, (uint32_t)idx, text);
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

// tNewSongMonitor::Reset (0x0016bde8), from UnlaunchFrontendMenus. The
// port's takes the box down as well (songmon.c).
static void hookSongMonitorReset(void* user)
{
    (void)user;
    bsm_reset(&g_songMonitor);
}

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

// IsJoystickPluggedIn (0x001542f0). Port 0 is the console's own buttons,
// and there is no second pad to plug in: the mode screens' Players is 1,
// as on a PS2 with one pad. Local Wireless is the main menu's own row
// (TASKS 63), and only the host's setup from there has two players
// (g_setup.wirelessPlayers, lobbySetup).
static int hookSetupJoystickPluggedIn(void* user, int port)
{
    (void)user;
    return port == 0;
}

// The Local Wireless lobby's link (lobby.h): wireless.h's, with the time
// and the log put in, and each peer's link for its messages.
static int lobbyNetStart(void)
{
    return wireless_start(logLine, (uint32_t)osGetTime());
}

static int lobbyNetSend(int i, uint8_t type, const void* data, size_t n)
{
    WlLink* l = wireless_peer_link(i);
    return l ? wl_link_send(l, type, data, n, 1) : 0;
}

static int lobbyNetRecv(int i, WlMsg* out)
{
    WlLink* l = wireless_peer_link(i);
    return l ? wl_link_recv(l, out) : 0;
}

static int lobbyNetPeek(int i, WlMsg* out)
{
    WlLink* l = wireless_peer_link(i);
    return l ? wl_link_peek(l, out) : 0;
}

static void lobbyLog(const char* line)
{
    logLine("%s", line);
}

// A lockstep race's checksum differs from a place's (netstep.h): the
// world's parts and the draws on bDefaultSeed up to that frame, once.
static void lockDiffers(int place, uint32_t frame)
{
    (void)place;
    lockhash_differs(frame);
}

// The console's wireless communication off (TASKS 62), or the config's
// WirelessOff, Azahar's never being.
static int lobbyNetRadioOff(void)
{
    return ConfigWirelessOff || wireless_radio_off();
}

// A wireless race's frames (netstep.h): unreliable, each message
// repeating what the other side still needs.
static int netStepSend(int i, uint8_t type, const void* data, size_t n)
{
    WlLink* l = wireless_peer_link(i);
    return l ? wl_link_send(l, type, data, n, 0) : 0;
}

static const NetStepNet kNetStepNet = {
    .peerAlive   = wireless_peer_alive,
    .send        = netStepSend,
    .recv        = lobbyNetRecv,
    .peek        = lobbyNetPeek,
    .setPatience = wireless_set_patience,
};

// The lockstep frame (lockFrameBegin): begun, its pad put and its record
// awaited; and whether the last loop ran one, whose clocks then advance.
static bool g_lockWaiting;
static bool g_lockRan;
static bool g_lockRaced;    // a lockstep frame ran with the coordinator up
static bool g_lockEnd;      // the frame asked for the end's save (37f)
static u32  g_lockMenu;     // the flow's presses since the last begin
static bool g_lockFinished; // WirelessTestFinish's finish made (37f-2)
static bool g_lockBack;     // back after a restart, no host's record yet
// A console lost (37g): the places racing at GO, those dropped since
// (their cars the CPU's), the CPU's notice (its places, when it went up,
// in ms) and the hold's mute.
#define LOCK_NOTE_MS   4000
#define LOCK_REJOIN_MS 2000
static uint8_t  g_lockLive;
static uint8_t  g_lockCpu;
static uint8_t  g_lockNote;
static uint32_t g_lockNoteAt;
static bool     g_lockMuted;
// A console back (37g-2): a client's last try at finding its host, and
// whether WirelessTestDropFrame's deafness was made.
static uint32_t g_lockRejoinAt;
static bool     g_lockDropped;
// A console back after a restart (37g-3), well behind the race: its
// frames undrawn but for its progress every LOCK_CATCH_DRAW_MS, and its
// sound down until it is in step.
#define LOCK_CATCH_DRAW_MS 250
static uint32_t g_lockCatchDrawAt;
static bool     g_lockCatchMuted;

static const LobbyNet kLobbyNet = {
    .start      = lobbyNetStart,
    .stop       = wireless_stop,
    .host       = wireless_host,
    .setOpen    = wireless_set_open,
    .scan       = wireless_scan,
    .join       = wireless_join,
    .leave      = wireless_leave,
    .state      = wireless_state,
    .peerCount  = wireless_peer_count,
    .peerAlive  = wireless_peer_alive,
    .peerName   = wireless_peer_name,
    .forgetLost = wireless_forget_lost,
    .selfName   = wireless_self_name,
    .send       = lobbyNetSend,
    .recv       = lobbyNetRecv,
    .radioOff   = lobbyNetRadioOff,
    .setPatience = wireless_set_patience,
};

// The host's first count of CPU racers (lobby.h, TASKS 37c-2), from the
// race setup the lobby came from: a Single Race's Opponents row (None or
// Full Grid for two players; none with the cops, as retail's two race
// alone) and a knockout's two, retail's for two players. Free Run has no
// AI racers, and Be A Cop's are TASKS 61's.
// The lobby's host setting the race up (lobby_on_setup): the setup
// screens' Players is Local Wireless until the lobby is back.
static void lobbySetup(int on)
{
    g_setup.wirelessPlayers = on;
}

// Start (lobby_on_start). A client comes from the main menu, so before
// its car select it takes the host's mode, as the host's Challenge set
// it: the game type, two players, the cops, and the cars the mode makes
// available. Then the race's setup over the link (netrace.h).
static void lobbyStarted(const LobbyRace* race)
{
    if (race->place != 0 && race->gameType >= 0) {
        Fred.GameType        = race->gameType;
        Fred.NumPlayerCars   = 2;
        g_flow.copsOn        = race->copsOn;
        Fred.MainMenuOpts[1] = race->copsOn;   // hookSetPolice's
        fred_make_challenge_cars_available(&Fred);
        logLine("lobby: the host's mode, game type %d, cops %d",
                race->gameType, race->copsOn);
    }
    netrace_begin(race);
}

static int lobbyCpuWish(void)
{
    switch (Fred.GameType) {
        case 3:
            if (Fred.MainMenuOpts[1]) return 0;
            if (Fred.SingleRaceSetupData[0] == 2) return LOBBY_CPU_FULL;
            return Fred.SingleRaceSetupData[0] == 1 ? 1 : 0;
        case 4:
        case 5:
            return 2;
        default:
            return LOBBY_CPU_NONE;
    }
}

// A console back in a race after a restart (37g-3): let in by lockstep.
static int netRaceRejoin(int p)
{
    return netstep_rejoin(p, (uint32_t)osGetTime());
}

static uint8_t netRaceRejoining(void)
{
    return netstep_rejoining(NULL);
}

// A wireless race's setup (netrace.h): the same link, and the game's
// StartRace, rides, characters and flow.
static const NetRaceNet kNetRaceNet = {
    .state       = wireless_state,
    .peerAlive   = wireless_peer_alive,
    .peerName    = wireless_peer_name,
    .send        = lobbyNetSend,
    .recv        = lobbyNetRecv,
    .setPatience = wireless_set_patience,
    .busy        = netstep_ending,
    .peek        = lobbyNetPeek,
    .rejoin      = netRaceRejoin,
    .rejoining   = netRaceRejoining,
    .drop        = wireless_drop,
    .setPeerPatience = wireless_set_peer_patience,
};

static void netRaceStartRace(void)
{
    fred_start_race(&Fred);
    logRaceStart();
}

static RideInfo* netRaceSelectedRide(int p)
{
    return fpi_get_selected_ride_info(&Fred.FrontendPlayers[p], Fred.GameType);
}

// StartRace's own change: from the frontend, unload it first.
static void netRaceStartLoading(void)
{
    bgf_change_state(&g_flow, g_flow.current == BGF_IN_FRONTEND
                              ? BGF_UNLOADING_FRONTEND
                              : BGF_LOADING_TRACK_COMMON, BGF_NONE);
}

// GO: the race runs in lockstep from its first frame (netstep.h), every
// place with a car racing. The pad each console's port 0 last read, its
// own, was this console's alone: the first frame's edges are read against
// a pad at rest instead, the same on every console. Port 1 has read
// nothing on every console.
static void netRaceGoRacing(void)
{
    const LobbyRace* r = netrace_race();
    uint8_t          racing = 0;
    NetStepPad       rest;
    uint8_t*         last = (uint8_t*)PadRingData[0][
        (JoystickRingBufferBottom - 1) & (JOYPAD_RING - 1)].ThePadData;

    for (int p = 0; p < r->consoles && p < NETSTEP_MAX; p++)
        if (netrace_driver(p) >= 0) racing |= (uint8_t)(1u << p);
    racing |= (uint8_t)(1u << r->place);
    netstep_start(r->place, r->consoles, r->peer, racing);
    lockhash_start(lobbyLog);
    netstep_rest(&rest);
    joyhid_from_wire(rest.ds2, last);
    g_lockWaiting = false;
    g_lockRan = false;
    g_lockRaced = false;
    g_lockEnd = false;
    g_lockMenu = 0;
    g_lockFinished = false;
    g_lockBack = netrace_back_in() != 0;
    g_lockLive = racing;
    g_lockCpu = 0;
    g_lockNote = 0;
    g_lockRejoinAt = (uint32_t)osGetTime() - LOCK_REJOIN_MS;
    g_lockDropped = false;
    logLine("netstep: clocks at GO: real %ld frames %ld, world %ld frames "
            "%ld", (long)RealTimer, (long)RealTimeFrames, (long)WorldTimer,
            (long)WorldTimeFrames);
    trackflow_go_racing();
}

// The player a wireless race shows on this console (PlayerNetLocal): its
// own, place 1's player 1 and every other place's player 0, or the other
// once a knockout has put its own out of the event, which racecoord then
// never makes (37f-2): this console watches the other's race.
static int netShownPlayer(void)
{
    int               own = netrace_place() == 1 ? 1 : 0;
    const DriverInfo* d = race_parameters_get_driver_info_by_driver_number(own);

    return d != NULL && d->EliminatedRank > 0 ? 1 - own : own;
}

// WirelessTestFinish (configitems.h): the race finished on that lockstep
// frame, or the first after it that is racing, before its checksum. Every
// console runs the same frames, so each finishes it on the same one.
static void lockTestFinish(void)
{
    if (ConfigWirelessTestFinish <= 0 || g_lockFinished
        || pRaceCoordinator == NULL || pCurrentRace == NULL
        || netstep_frame() < (uint32_t)ConfigWirelessTestFinish
        || pRaceCoordinator->CurrentRCState != RCSTATE_RACE_IN_PROGRESS
        || race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING)
        return;
    g_lockFinished = true;
    logLine("lockstep: frame %lu, the test's finish",
            (unsigned long)netstep_frame());
    racecoordinator_the_race_has_finished(pRaceCoordinator);
}

// TestFinish (configitems.h): a race on this console alone finished that
// many seconds after its GO (StartGoTimeFrames), once. The player's car
// crosses in place TestFinishPlace, behind the first cars of the
// leadership order; the race finish does the rest. A race whose players
// have all finished is left alone, so a tournament's next race gets its
// own. TestFinishTime sets the player's lap instead of projecting it.
static void raceTestFinish(void)
{
    Race*   r = pCurrentRace;
    int32_t place = ConfigTestFinishPlace > 0 ? ConfigTestFinishPlace : 1;
    int32_t ahead = 0, i;

    if (ConfigTestFinish <= 0 || r == NULL || pRaceCoordinator == NULL
        || pRaceCoordinator->CurrentRCState != RCSTATE_RACE_IN_PROGRESS
        || race_get_race_stage(r) != RACE_STAGE_RACING
        || race_are_all_players_finished_racing(r)
        || r->StartGoTimeFrames == 0
        || WorldTimeFrames - r->StartGoTimeFrames < ConfigTestFinish * 60)
        return;
    if (TheRaceParameters.BeACop && pCopManager != NULL) {
        // Be A Cop: each racer arrested as an arrest's pullover ends
        // (copmanager_end_pullover), and the last arrest wins the race
        // for the cop with the clock's time left (TASKS 69g).
        for (i = 0; i < r->NumRacingCars; i++) {
            struct RacingCar* rc = r->pRacingCars[i];
            tCarPulloverInfo* pl;

            if (rc->FinishReason != RACING_CAR_NOT_FINISHED
                || racingcar_get_player(rc) != NULL)
                continue;
            pl            = &pCopManager->CarPullovers[rc->pCar->CarIndex];
            pl->bArrest   = 1;
            pl->nCopIndex = -1;
            copmanager_end_pullover(pCopManager, rc->pCar->CarIndex);
        }
        logLine("race: the test's finish, %ld s in, %ld arrests, %.1f s left",
                (long)ConfigTestFinish,
                (long)pCopManager->nBeACopNumArrestsMade,
                (double)pCopManager->fBeACopTime);
        racecoordinator_the_race_has_finished(pRaceCoordinator);
        return;
    }
    for (i = 0; i < r->NumRacingCars && ahead < place - 1; i++) {
        struct RacingCar* rc = r->pRacingCars[i];

        if (rc->FinishReason != RACING_CAR_NOT_FINISHED
            || racingcar_get_player(rc) != NULL)
            continue;
        race_finish_car(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);
        ahead++;
    }
    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar* rc = r->pRacingCars[i];
        uint32_t          lap = (uint32_t)ConfigTestFinishTime * 4000u;

        if (rc->FinishReason != RACING_CAR_NOT_FINISHED
            || racingcar_get_player(rc) == NULL)
            continue;
        if (ConfigTestFinishTime <= 0) {
            race_finish_car(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);
            continue;
        }
        // TestFinishTime: each lap that long. A place given keeps the
        // times as set, where none projects them.
        racingcar_get_last_best_lap_time(rc)->PackedTime = lap;
        rc->RaceTime.PackedTime = lap * (uint32_t)r->NumLapsInRace;
        race_finish_car(r, i, race_get_next_finish_rank(r), 0,
                        RACING_CAR_NORMAL_COMPLETION);
    }
    logLine("race: the test's finish, %ld s in, place %ld, lap %ld s",
            (long)ConfigTestFinish, (long)place, (long)ConfigTestFinishTime);
    racecoordinator_the_race_has_finished(pRaceCoordinator);
}

// With TestFinish on, the End Game Menu in the log, once each time it
// comes up: whether its first row is Next Race (endgame.c, has_next_race),
// its rows that can be chosen, the one highlighted and whether it wraps,
// so run_azahar_career.ps1 knows how far Quit is.
static void raceTestMenuLog(void)
{
    static bool logged;
    const BScreenConfig* s = g_flow.screen;
    const BMenu*         m = &g_boot.menu;
    int                  rows = 0;

    if (ConfigTestFinish <= 0) return;
    if (s == NULL || s->name == NULL || strcmp(s->name, kEndGameMenuScreen)) {
        logged = false;
        return;
    }
    if (logged || !g_boot.hasMenu || m->current < 0) return;
    for (int i = 0; i < m->numItems; i++)
        if (m->items[i].state & BMENU_ENABLED) rows++;
    logged = true;
    logLine("race: the test's end game menu, next race %d, rows %d, row %d,"
            " loop %d",
            (int)(fred_is_multi_track(&Fred)
                  && fred_is_there_another_race(&Fred)),
            rows, m->current, (int)m->looping);
}

static const NetRaceGame kNetRaceGame = {
    .startRace     = netRaceStartRace,
    .selectedRide  = netRaceSelectedRide,
    .characterInfo = get_character_info,
    .startLoading  = netRaceStartLoading,
    .goRacing      = netRaceGoRacing,
};

// SetHelpOverride (0x0016d448): the lines Y's HELP panel shows instead of
// the screen's, and the help on. They are logged too.
static void hookSetupHelpOverride(void* user, const int32_t* lines)
{
    (void)user;
    helpmenu_set_override(&g_help, lines);
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

// FrontendDatabase::SetupRaceParametersAfterRaceSetup (0x001862b0), which
// the setup screens call on the global Fred.
static void hookSetupRaceAfterSetup(void* user)
{
    (void)user;
    fred_setup_race_parameters_after_race_setup(&Fred);
    logLine("fred race setup game=%ld ai=%ld cops=%ld beacop=%ld",
            (long)Fred.GameType, (long)TheRaceParameters.NumAICars,
            (long)TheRaceParameters.nMaxCops, (long)TheRaceParameters.BeACop);
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

// What UnlaunchFrontendMenus (0x0016fa80) reads: Fred.GameType, for the
// screen it pops back to, and whether the race is a demo, for the launch
// type the frontend comes back with.
static int hookGameType(void* user)
{
    (void)user;
    return (int)Fred.GameType;
}

static int hookRaceDemo(void* user)
{
    (void)user;
    return RaceParametersAIDemoMode != 0 || RaceParametersReplayDemoMode != 0;
}

// A wireless race comes back to the lobby, the link up (TASKS 37f).
static const char* hookRaceReturn(void* user)
{
    (void)user;
    return netrace_active() ? LOBBY_SCREEN_NAME : NULL;
}

// The race's music. RaceCoordinator's cleanup stops it (sound::jukebox::Stop,
// 0x001aec90); RACE_IN_PROGRESS's first TICK at RACING starts it six seconds
// on (DelayedStart, 0x001aec88), which sound::Update counts down; and
// RESTART_RACE parks the timer at 9e9 for the next start.
static void raceJukeboxStop(void)
{
    jb_music_stop(&g_jukebox);
    logLine("jukebox stop: race");
}

static void raceJukeboxDelayedStart(float seconds)
{
    jb_music_delayed_start(&g_jukebox, seconds);
    logLine("jukebox delayed start: %.1f s", (double)seconds);
}

// LoadSoundRegionsInGame (0x001ae798): DelayedStart's timer and the mute
// cleared, the jukebox to the racing list, then "InGame", the track's
// region and the two drivers' cars', one after another; sound::Update
// calls `done` once they are in.
static void hookLoadSoundRegionsInGame(void (*done)(intptr_t), intptr_t param)
{
    sound_load_regions_in_game(&gSoundModule, done, param);
    logLine("sound regions: %s %s %s %s", gSoundModule.region[0].name,
            gSoundModule.region[1].name, gSoundModule.region[2].name,
            gSoundModule.region[3].name);
}

// TheEasterEggs' Start and Stop, NewMainMenu's. The 78 codes it listens for
// are not ported, so the pad is not handed to it: the log says when retail
// would have.
static void hookEasterEggs(void* user, int start)
{
    (void)user;
    logLine("easter eggs %s", start ? "start" : "stop");
}

// tDisplayOptionsChangeManager::Start: displayoptions.c keeps the snapshot.
static void hookDisplayOptionsStart(void* user)
{
    (void)user;
    displayopts_start();
}

static void hookDisplayOptsLog(void* user, const char* line)
{
    (void)user;
    logLine("%s", line);
}

// The Controller page's text, in the language up (joyconfig.h).
static size_t hookJoyConfigText(void* user, int32_t id, char* out,
                                size_t cap)
{
    (void)user;
    if (cap) out[0] = '\0';
    if (!g_boot.ui || !g_boot.ui->hasLang) return 0;
    return langtab_copy(&g_boot.ui->lang, id, out, cap);
}

// Quick Race: retail's StartQuickRace (quickrace.h) fills the race and
// calls StartRace, whose ChangeGameFlow takes the flow out of the frontend.
// StopMovie inside it is the screen list's.
static void quickRaceStopMovie(void)
{
    bgf_stop_movie(&g_flow);
}

static void hookStartQuickRace(void* user, int transmission)
{
    (void)user;
    bootNote("quick race");
    gQuickRaceStopMovieFn = quickRaceStopMovie;
    start_quick_race(transmission);
    logLine("quickrace: track %d %s, time of day %d, %d AI, grid %d, "
            "%d cops, car %d skin %d, gearbox %s",
            (int)TheRaceParameters.TrackNumber,
            TheRaceParameters.TrackDirection ? "backwards" : "forwards",
            (int)TheRaceParameters.TrackTimeOfDay,
            (int)TheRaceParameters.NumAICars,
            (int)TheRaceParameters.PlayerStartPosition[0],
            (int)TheRaceParameters.nMaxCops,
            (int)Fred.FrontendPlayers[0].RideInfoByGameMode[Fred.GameType].Type,
            (int)Fred.FrontendPlayers[0].RideInfoByGameMode[Fred.GameType]
                .SkinNumber,
            transmission ? "manual" : "automatic");
    logRaceStart();
}

// NewMainMenu's CopsOn, where retail keeps it.
static void hookSetPolice(void* user, int copsOn)
{
    (void)user;
    Fred.MainMenuOpts[1] = copsOn;
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
    // FRONTB's Flailer chunk gains the debug menu's item and screen
    // (debugmenu.h). The rebuilt chunk is what the runtime reads from here
    // on; the bundle keeps its textures and fonts.
    if (b->hasUI && strcmp(rel, BUNDLE_FRONTEND) == 0) {
        size_t   n   = 0;
        uint8_t* buf = debugmenu_patch_frontend(b->data, b->len, &n);
        if (buf) {
            bui_close(&b->ui);
            b->hasUI  = bui_open(&b->ui, buf, 0, n);
            b->uiData = buf;
            if (ConfigDebugMenu) debugmenu_reveal();
        } else
            logPrintf("  %s: no debug menu\n", rel);
    }
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

// RenderTextIntoRectangle's inner (0x00144ed0): the strip queued for the
// frame's layers (uirender_queue_text_rect). Its only users are the
// pre-race screens' -- the Blurb and Be A Cop's two-player pages -- which
// tell the race's controls while the menus' keys are live, so with a race
// coordinator the button icons are the race's: the cop's in Be A Cop,
// whose one-player Blurb is the cop's (pre_race_blurb_text), as
// joyhidRaceLayout has them once the race runs.
static void flailerTextIntoRectangle(struct FlailerTextChunk* t,
                                     const char* str, float tlx,
                                     float tly, float brx, float bry,
                                     float scale)
{
    BUI*     ui  = NULL;
    uint32_t idx = 0;
    int32_t  layout = UIR_HELP_LAYOUT_LIVE;
    if (!flailer_object_index(&t->Object, &ui, &idx)) return;
    if (pRaceCoordinator != NULL)
        layout = RaceParametersBeACop ? JOYHID_LAYOUT_COP
                                      : JOYHID_LAYOUT_RACE;
    (void)uirender_queue_text_rect(g_boot.ui, ui, idx, tlx, tly, brx, bry,
                                   str, scale, layout);
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

// CarRenderInfo::Render's eRenderLightFlare, whose answer it does not read.
// The cars' flares asked for and drawn since the race log's last line,
// and of them the cops' red, blue and white (types 4 to 6).
static int s_flaresAsked, s_flaresDrawn, s_copFlaresAsked, s_copFlaresDrawn;

static void render_light_flare_seam(eView* view, eLightFlare* flare,
                                    bMatrix4* local_world, float intensity)
{
    int cop = flare->Type >= 4 && flare->Type <= 6;
    int drew = el_render_light_flare(view, flare, local_world, intensity);

    s_flaresAsked++;
    s_flaresDrawn += drew != 0;
    s_copFlaresAsked += cop;
    s_copFlaresDrawn += cop && drew != 0;
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
        // LoaderNisInfo: the 8 ticket and arrest NISes' records (nisinfo.h).
        // Without them every NIS is 0 frames long and a pullover's ends at
        // once.
        taken += loader_nis_info(c);
        c += 8 + size;
    }
    logPrintf("car data: %d chunks, %d skins, %d characters, %d tracks, "
              "%d NISes; %d texture chunks\n",
              taken, (int)NumSkinInfo, (int)NumCharacterInfo,
              (int)HighestTrackNumber, (int)NumNisInfos, packs);
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
    // Y is MENU_HELP, retail's Circle (the user, 2026-10-16): flowInput
    // toggles the HELP panel with it, and no menu does more. Square, which
    // it was before, is X.
    { KEY_Y,      BJOY_MENU_HELP },
    { KEY_X,      BJOY_MENU_SQUARE },
    // The shoulders, as SCREEN_L1 and SCREEN_R1: JukeBox Music's L turns a
    // genre on and off.
    { KEY_L,      BJOY_MENU_L1 },
    { KEY_R,      BJOY_MENU_R1 },
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
// and at a size meant for 320x240, in a dialog made of the frontend's own
// art (drawBotDialog). With no line to show it is the game's logo.
//
// None of this is a port of anything. The PS2 had one screen, so there is
// no original here to be accurate to -- only the game's own art and fonts,
// and the line it was trying to show the player.

#define BOT_W     320.0f
#define BOT_H     240.0f
#define BOT_PAD    16.0f

// citro2d packs a colour r | g<<8 | b<<16 | a<<24, and C2D_Color32 is an
// inline function rather than a macro, so a constant has to pack its own.
#define RGBA8(r, g, b, a) \
    ((u32)(r) | ((u32)(g) << 8) | ((u32)(b) << 16) | ((u32)(a) << 24))

#define BOT_BACK   RGBA8(0x00, 0x00, 0x00, 0xff)
#define BOT_ACCENT RGBA8(0xc4, 0x1e, 0x24, 0xff)   // the frontend's own red
#define BOT_TEXT   RGBA8(0xec, 0xef, 0xf4, 0xff)

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
// a popup keeps its message while the screen goes on translating. Each
// holds FE_ENGLISH's longest string (about 360 bytes, an event's
// description); at 256 the tree's details and the Pre Race Blurb lost the
// end of the long ones (TASKS 69g).
#define CARSEL_RING     8
#define CARSEL_RING_LEN 512

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

// SoundEnabled (gp-23056), which the selector asks before it fades the
// speech, speech::mgr_t::fade.
static int hookCarSelSoundEnabled(void* user)
{
    (void)user;
    return SoundEnabled;
}
static void hookCarSelSpeechFade(void* user, float level)
{
    (void)user;
    speechmgr_fade(speechmgr_get_instance(), level);
}

// StopFrontendSound (0x0016e0e8), CarSelector's destructor's.
static void hookCarSelStopSound(void* user, int32_t event)
{
    (void)user;
    fesound_stop((int)event);
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
    // A wireless race's client sends its car and waits for the host's
    // track instead.
    if (!strcmp(name, "Select Track") && netrace_car_chosen(&g_flow)) return;
    bgf_change_to_screen(&g_flow, name, push);
}

// A wireless race's car select is the one-player one (TASKS 67).
static int hookCarSelWirelessRace(void* user)
{
    (void)user;
    return netrace_active();
}

// FrontendDatabase::StartRace, for the single race and the championship.
// A wireless race's host builds it once every car is in (netrace.c); a
// client's car select that starts a race straight away sends its car.
static void hookCarSelStartRace(void* user)
{
    (void)user;
    if (netrace_active()
        && (netrace_host_start(&g_flow) || netrace_car_chosen(&g_flow)))
        return;
    fred_start_race(&Fred);
    logRaceStart();
}

// The debug menu's scroll: the highlight to another row of its menu.
static void hookDebugSetActiveItem(void* user, uint32_t itemHash)
{
    Boot* b = (Boot*)user;
    if (b->hasMenu) bmenu_set_active_item(&b->menu, itemHash);
}

static void hookDebugLog(void* user, const char* line)
{
    (void)user;
    logLine("debug menu: %s", line);
}

// Player Names' keyboard (nameentry.h): the 3DS's own, libctru's swkbd.
// Its filter holds the name to tKeyboard's characters, and the hint is the
// row's blurb, Latin-1 made UTF-8 for the applet. The main thread waits in
// the applet, between frames: the flow's input is before C3D_FrameBegin.
static SwkbdCallbackResult nameKeyboardFilter(void* user,
                                              const char** message,
                                              const char* text,
                                              size_t length)
{
    (void)user;
    for (size_t i = 0; i < length; i++) {
        if (!nameentry_char_ok((unsigned char)text[i])) {
            *message = "Names can have letters, numbers, spaces, "
                       "! . and #.";
            return SWKBD_CALLBACK_CONTINUE;
        }
    }
    return SWKBD_CALLBACK_OK;
}

// The sound held while an applet has the main thread (the user's word,
// 2026-10-13: it went wild when the keyboard closed). Every ndsp channel
// -- bsnd's voices and streams, the jukebox's, the movies' -- that plays
// is paused, and the master volume is 0. The streams' workers only queue
// waves, so nothing un-pauses a channel while the main thread waits; their
// queues fill and stop.
//
// On a 3DS the channels go on as the applet closes, and the volume comes
// back over a quarter second. Azahar stops the whole console while its
// keyboard dialog is open (QtKeyboard::Execute waits on the dialog), and
// its audio stretcher, fed nothing, slows to its floor of 5%; fed again,
// it swings fast, slow and back for about three seconds (TimeStretcher::
// Process, simulated). There the hold lasts 3.5 s, so the swing is over
// silence, then the channels go on.
#define AUDIO_HOLD_EMU_MS 3500u
#define AUDIO_FADE_MS     250u

enum { HOLD_NONE, HOLD_APPLET, HOLD_WAIT, HOLD_FADE };

static bool     gAudioUp;
static int      gHold;
static bool     gHeld[BSND_MAX_VOICES];  // the channels the hold paused
static uint64_t gHoldUntil;              // HOLD_WAIT's end, a tick
static uint64_t gFadeFrom;               // HOLD_FADE's start

// svcGetSystemInfo's 0x20000 is Citra's and Azahar's own (EMULATOR_ID, 1
// and 2); a 3DS's kernel has no such type and returns an error.
static bool onEmulator(void)
{
    static int known = -1;
    s64        id    = 0;

    if (known < 0)
        known = R_SUCCEEDED(svcGetSystemInfo(&id, 0x20000, 0)) && id != 0;
    return known != 0;
}

static void audioHoldTick(void)
{
    uint64_t now;
    float    v;

    if (gHold != HOLD_WAIT && gHold != HOLD_FADE) return;
    now = svcGetSystemTick();
    if (gHold == HOLD_WAIT) {
        if (now < gHoldUntil) return;
        for (int ch = 0; ch < BSND_MAX_VOICES; ch++) {
            if (gHeld[ch]) ndspChnSetPaused(ch, false);
            gHeld[ch] = false;
        }
        gHold     = HOLD_FADE;
        gFadeFrom = now;
    }
    v = (float)((now - gFadeFrom) / CPU_TICKS_PER_MSEC) / (float)AUDIO_FADE_MS;
    if (v >= 1.0f) {
        ndspSetMasterVol(1.0f);
        gHold = HOLD_NONE;
        logLine("audio: back after the applet");
        return;
    }
    ndspSetMasterVol(v);
}

static void holdAudio(bool hold)
{
    if (!gAudioUp) return;
    if (hold) {
        // A hold still letting go keeps what it paused.
        for (int ch = 0; ch < BSND_MAX_VOICES; ch++) {
            if (!ndspChnIsPaused(ch)) {
                gHeld[ch] = true;
                ndspChnSetPaused(ch, true);
            }
        }
        ndspSetMasterVol(0.0f);
        gHold = HOLD_APPLET;
        return;
    }
    gHold      = HOLD_WAIT;
    gHoldUntil = svcGetSystemTick();
    if (onEmulator())
        gHoldUntil += (uint64_t)(AUDIO_HOLD_EMU_MS * CPU_TICKS_PER_MSEC);
    audioHoldTick();
}

static int hookNameKeyboard(void* user, const char* hint, char* name,
                            int size)
{
    SwkbdState  kb;
    SwkbdButton button;
    char        hintUtf8[256];
    char        typed[4 * NAMEENTRY_MAX_CHARS + 1];
    size_t      n = 0;
    int         i, j;

    (void)user;
    for (i = 0; hint[i] != '\0' && n + 3 < sizeof hintUtf8; i++) {
        unsigned char c = (unsigned char)hint[i];
        if (c < 0x80) {
            hintUtf8[n++] = (char)c;
        } else {
            hintUtf8[n++] = (char)(0xc0 | (c >> 6));
            hintUtf8[n++] = (char)(0x80 | (c & 0x3f));
        }
    }
    hintUtf8[n] = '\0';
    swkbdInit(&kb, SWKBD_TYPE_QWERTY, 2, NAMEENTRY_MAX_CHARS);
    swkbdSetHintText(&kb, hintUtf8);
    swkbdSetInitialText(&kb, name);
    swkbdSetValidation(&kb, SWKBD_ANYTHING, SWKBD_FILTER_CALLBACK, 0);
    swkbdSetFilterCallback(&kb, nameKeyboardFilter, NULL);
    swkbdSetFeatures(&kb, SWKBD_DARKEN_TOP_SCREEN);
    memset(typed, 0, sizeof typed);
    holdAudio(true);
    hangwatch_applet(true);
    button = swkbdInputText(&kb, typed, sizeof typed);
    hangwatch_applet(false);
    holdAudio(false);
    if (button != SWKBD_BUTTON_CONFIRM) {
        logLine("name entry: keyboard closed, %s (%d)",
                button == SWKBD_BUTTON_NONE ? "no button" : "cancel",
                (int)swkbdGetResult(&kb));
        return 0;
    }
    // The filter has passed every character; this keeps the name to them
    // and to its length whatever the applet hands back.
    for (i = j = 0; typed[i] != '\0' && j < NAMEENTRY_MAX_CHARS
                    && j < size - 1; i++)
        if (nameentry_char_ok((unsigned char)typed[i]))
            name[j++] = typed[i];
    name[j] = '\0';
    return 1;
}

static void hookNameEntryLog(void* user, const char* line)
{
    (void)user;
    logLine("name entry: %s", line);
}

static void hookAudioOptsLog(void* user, const char* line)
{
    (void)user;
    logLine("%s", line);
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

// FlailerScreenList::RenderFlailerModels' RENDER to the screen with
// models: the car select, which draws its platform and, through the hook,
// its unlock blurb; or Select Track, its turning miniature and its locked
// box's blurb.
static void carselRender(void* user)
{
    (void)user;
    if (g_flow.screen
        && (g_flow.screen->callback == bcarsel_screen_callback
            || g_flow.screen->callback == btracksel_screen_callback)) {
        BScreenCallbackData rd;
        memset(&rd, 0, sizeof(rd));
        rd.itemHash = g_flow.screen->hash;
        g_flow.screen->callback(&g_flow, BMSG_SCREEN_RENDER, &rd);
    }
}

// RenderFlailerModels' RENDER to every other screen, before the layers
// are drawn: the pre-race Blurb lays its text into its box then. The
// frame's strips go first, as the PS2's layer table empties each frame.
static void flowRender(UIRenderer* ui)
{
    uirender_clear_strips(ui);
    if (g_flow.screen && g_flow.screen->callback
        && g_flow.screen->callback != bcarsel_screen_callback
        && g_flow.screen->callback != btracksel_screen_callback) {
        BScreenCallbackData rd;
        memset(&rd, 0, sizeof(rd));
        rd.itemHash = g_flow.screen->hash;
        g_flow.screen->callback(&g_flow, BMSG_SCREEN_RENDER, &rd);
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

// EnterOrbitMode's line about the car (0x001967a0): a cop's is event 211
// with Speech::ConvertCarType's number; the rest's is 146 with whether the
// car is a high-performance one, then the number.
static void hookCarSelSpeakCar(void* user, int32_t carType, int cop, int hp)
{
    int32_t name = speech_convert_car_type(carType);
    int32_t got;

    (void)user;
    if (cop)
        got = spch_add_event_v(211, 1, name);
    else
        got = spch_add_event_v(146, 2, hp ? 1 : 0, name);
    logLine("carsel speech: car %ld, event %d, name %ld, queued %ld",
            (long)carType, cop ? 211 : 146, (long)name, (long)got);
}

// IsCarAnEventReward and FindEventThatCarIsARewardFor (eventtree.c), as
// FormatUnlockBlurbForCar asks them: the event's tree type and number.
static int hookFindEventForCar(void* user, int32_t carType, int32_t* treeType,
                               int32_t* eventNumber)
{
    EventInfo* e;
    (void)user;
    if (!is_car_an_event_reward(carType))
        return 0;
    e = find_event_that_car_is_a_reward_for(carType);
    *treeType    = event_info_tree(e)->nType;
    *eventNumber = e->nNumber;
    return 1;
}

// FormatUnlockBlurbForCar, nfsrewards.c's.
static void hookCarSelFormatUnlockBlurb(void* user, char* buf, int len,
                                        int32_t carType, int32_t gameType,
                                        int flag)
{
    NFSRewardHooks h;
    memset(&h, 0, sizeof(h));
    h.user      = user;
    h.translate = hookCarSelTranslate;
    h.language  = hookCarSelLanguage;
    h.findEventForCar = hookFindEventForCar;
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

// ------------------------------------------------------------ track select
//
// BTrackSelHooks, for btracksel.c: retail's SelectTrackScreen (12m-3c).
// The language table, the speech's fade, the blurb's text and the race's
// start are car select's.

static BTrackSel g_tracksel;

// The slideshow's TexturePack (12m-3c-2), retail's: "TrackSelect", its
// table read from FRONTEND\TSELECT.BIN and its 159 pictures streamed in one
// at a time (texturestream.h).
static TexturePack* g_trackSelPack;

static void* hookTrackSelPackNew(void* user)
{
    (void)user;
    g_trackSelPack = newStreamedPack("pTrackSelectTexturePack", "TrackSelect",
                                     "FRONTEND\\TSELECT.BIN");
    return g_trackSelPack;
}

static void hookTrackSelPackDelete(void* user, void* pack)
{
    (void)user;
    texturepack_destruct((TexturePack*)pack, 3);
    if (pack == g_trackSelPack) g_trackSelPack = NULL;
}

static void hookTrackSelPackUnloadAll(void* user, void* pack)
{
    (void)user;
    if (pack) texturepack_unload_all_textures_from_file((TexturePack*)pack);
}

static int hookTrackSelPackHas(void* user, void* pack, uint32_t hash)
{
    (void)user;
    return pack && texturepack_get_texture((TexturePack*)pack, hash) != NULL;
}

static void hookTrackSelPackLoad(void* user, void* pack, uint32_t hash,
                                 void (*cb)(intptr_t param), intptr_t param)
{
    (void)user;
    if (pack)
        texturepack_load_textures_from_file((TexturePack*)pack, &hash, 1, cb,
                                            param);
}

// The slideshow's pictures on the GPU, the port's. Retail's Flailer finds a
// bitmap's texture through GetTextureInfo, which has a TSELECT.BIN record
// once the pack has loaded it; the port's renderer draws from its bundles.
// So a picture one of the slideshow's two bitmaps shows is decoded from the
// pack's loaded record into a texture here and drawn in its place
// (uirender_override_texture); one neither bitmap shows is freed, and its
// slot given back. Run as the frame begins, when the GPU is done with the
// last one.
typedef struct {
    uint32_t hash;
    C3D_Tex  tex;
} TrackSelPicture;

static TrackSelPicture g_trackSelPictures[2];

// The record's pixels and palette, one after the other in a block of their
// own as texsrc_stage lays out a read, through texpack_upload.
static bool trackSelUpload(TextureInfo* t, C3D_Tex* out)
{
    size_t   pixels  = (size_t)t->ImageSize;
    size_t   palette = t->PaletteSize > 0 ? (size_t)t->PaletteSize : 0;
    uint8_t* stage;
    TexPack  tp;
    TexInfo  ti;
    bool     ok;

    if (!t->ImageData || pixels == 0 || (palette && !t->PaletteData))
        return false;
    stage = (uint8_t*)malloc(pixels + palette);
    if (!stage) return false;
    memcpy(stage, t->ImageData, pixels);
    if (palette) memcpy(stage + pixels, t->PaletteData, palette);
    memset(&tp, 0, sizeof(tp));
    tp.info     = (const uint8_t*)t;
    tp.infoSize = TEXPACK_RECORD_SIZE;
    tp.count    = 1;
    tp.data     = stage;
    tp.dataSize = (uint32_t)(pixels + palette);
    ok = texpack_get(&tp, 0, &ti);
    if (ok) {
        ti.pixelOff = 0;
        ti.clutOff  = (uint32_t)pixels;
        ok = texpack_upload(&tp, &ti, 0, out);
    }
    free(stage);
    return ok;
}

static void trackSelSyncPictures(UIRenderer* ui)
{
    uint32_t shown[2] = { 0, 0 };
    int      i, j;

    if (btracksel_active()) btracksel_show_textures(shown);
    for (i = 0; i < 2; i++) {
        TrackSelPicture* p = &g_trackSelPictures[i];
        if (!p->hash || p->hash == shown[0] || p->hash == shown[1]) continue;
        uirender_override_texture(ui, p->hash, NULL, 0, 0, false);
        uirender_forget_texture(ui, p->hash);
        C3D_TexDelete(&p->tex);
        logLine("tracksel picture %08lx down", (unsigned long)p->hash);
        p->hash = 0;
    }
    if (!g_trackSelPack) return;
    for (j = 0; j < 2; j++) {
        TrackSelPicture* spare = NULL;
        TextureInfo*     t;

        if (!shown[j]) continue;
        for (i = 0; i < 2; i++) {
            if (g_trackSelPictures[i].hash == shown[j]) break;
            if (!g_trackSelPictures[i].hash && !spare)
                spare = &g_trackSelPictures[i];
        }
        if (i < 2 || !spare) continue;
        t = texturepack_get_loaded_texture(g_trackSelPack, shown[j]);
        if (!t || !trackSelUpload(t, &spare->tex)) continue;
        spare->hash = shown[j];
        uirender_override_texture(ui, shown[j], &spare->tex, t->Width,
                                  t->Height, false);
        logLine("tracksel picture %08lx up, %s", (unsigned long)shown[j],
                t->DebugName);
    }
}

// SQUARE: SPCH_AddEventV(155, 1, Speech::ConvertTrackNumber(track)), the
// track's name.
static void hookTrackSelSpeak(void* user, int32_t track)
{
    (void)user;
    spch_add_event_v(155, 1, speech_convert_track_number(track));
}

static int hookTrackSelUnlocked(void* user, int32_t track, int32_t dir)
{
    (void)user;
    return is_track_unlocked(track, dir) != 0;
}

// IsTrackAnEventReward and FindEventThatTrackIsARewardFor, as
// FormatUnlockBlurbForTrack asks them.
static int hookFindEventForTrack(void* user, int32_t track, int32_t dir,
                                 int32_t* treeType, int32_t* eventNumber)
{
    EventInfo* e;
    (void)user;
    if (!is_track_an_event_reward(track, dir))
        return 0;
    e = find_event_that_track_is_a_reward_for(track, dir);
    if (!e)
        return 0;
    *treeType    = event_info_tree(e)->nType;
    *eventNumber = e->nNumber;
    return 1;
}

static void hookTrackSelFormatUnlockBlurb(void* user, char* buf, int len,
                                          int32_t track, int32_t dir)
{
    NFSRewardHooks h;
    memset(&h, 0, sizeof(h));
    h.user              = user;
    h.translate         = hookCarSelTranslate;
    h.language          = hookCarSelLanguage;
    h.findEventForTrack = hookFindEventForTrack;
    nfs_format_unlock_blurb_for_track(&h, buf, len, track, dir);
}

// SetActiveMenuItem (0x0016d3d0): the time of day's item in the screen's
// menu. During SCREEN_ACTIVATE the menu is not up yet; ACTIVATE's answer
// picks the item then (hookEnterScreen).
static void hookTrackSelSetActive(void* user, uint32_t item)
{
    Boot* b = (Boot*)user;
    if (b->hasMenu) (void)bmenu_set_active_item(&b->menu, item);
}

// tHighlightAnimation, on the flow's kit with the flow's clock, as the
// popups' bloom.
static BAnim* trackSelKit(void)
{
    if (g_flow.anim)
        banim_set_clock(g_flow.anim, (int32_t)g_flow.realTimer,
                        g_flow.realElapsed);
    return g_flow.anim;
}

static void hookTrackSelHighlightInit(void* user, BHighlightAnim* hl,
                                      uint32_t screen, uint32_t object,
                                      int32_t color)
{
    BAnim* a = trackSelKit();
    (void)user;
    if (a) banim_highlight_init(a, hl, screen, object, color);
}

static void hookTrackSelHighlightItem(void* user, BHighlightAnim* hl,
                                      uint32_t item)
{
    BAnim* a = trackSelKit();
    (void)user;
    if (a) banim_highlight_set_item(a, hl, item);
}

static void hookTrackSelHighlightAnimate(void* user, BHighlightAnim* hl)
{
    BAnim* a = trackSelKit();
    (void)user;
    if (a) banim_highlight_animate(a, hl);
}

// ------------------------------------------------------------ the event tree
//
// EtvHooks, for eventtreeview.c: retail's tEventTreeView, the career's
// "View Event Tree" (TASKS 69). The view copies Flailer objects each frame
// and hands the copies over; they go to the renderer's copy queue, drawn in
// their layers after the screens' own objects.

// The renderer's object for `orig`, moved and scaled as `copy` is.
static bool etvObject(struct FlailerObjectChunk* orig,
                      const struct FlailerObjectChunk* copy, BUI** ui,
                      uint32_t* idx, BUIObject* o)
{
    if (!flailer_object_index(orig, ui, idx) || !bui_object(*ui, *idx, o))
        return false;
    o->x        = copy->X;
    o->y        = copy->Y;
    o->scaleX   = copy->ScaleX;
    o->scaleY   = copy->ScaleY;
    o->z        = copy->Z;
    o->rotation = copy->Rotation;
    return true;
}

// RenderFlailerBitmap (0x00143078).
static void hookEtvRenderBitmap(void* user, struct FlailerBitmapChunk* orig,
                                const struct FlailerBitmapChunk* copy,
                                float alpha, const float* clip)
{
    Boot*     b   = (Boot*)user;
    BUI*      ui  = NULL;
    uint32_t  idx = 0;
    BUIObject o;

    if (!etvObject(&orig->Object, &copy->Object, &ui, &idx, &o)) return;
    o.textureHash = copy->TextureHash;
    memcpy(o.colors, copy->Colors, sizeof o.colors);
    memcpy(o.uv, copy->UV, sizeof o.uv);
    (void)uirender_queue_copy(b->ui, ui, idx, &o, NULL, alpha, clip);
}

// RenderFlailerText (0x00142260). A copy's characters are its own; the
// object drawn as it is keeps the chunk's.
static void hookEtvRenderText(void* user, struct FlailerTextChunk* orig,
                              const struct FlailerTextChunk* copy,
                              float alpha, const float* clip)
{
    Boot*     b   = (Boot*)user;
    BUI*      ui  = NULL;
    uint32_t  idx = 0;
    BUIObject o;
    char      text[UIR_COPY_TEXT];
    int32_t   n = 0;

    if (!etvObject(&orig->Object, &copy->Object, &ui, &idx, &o)) return;
    o.fontHash   = copy->FontHash;
    o.format     = copy->FormatOptions;
    o.color      = copy->Color;
    o.languageID = copy->LanguageID;
    if (copy == orig || copy->LanguageID) {
        (void)uirender_queue_copy(b->ui, ui, idx, &o, NULL, alpha, clip);
        return;
    }
    while (n < copy->MaxChars && n < UIR_COPY_TEXT - 1 && copy->String[n]) {
        text[n] = copy->String[n];
        n++;
    }
    text[n] = '\0';
    (void)uirender_queue_copy(b->ui, ui, idx, &o, text, alpha, clip);
}

// RenderTextIntoRectangle (0x001451e0) for the details' description and
// the popup's help: RENDER comes before the layers are drawn, so the text
// waits for them, and is then wrapped into the box in the port's style, as
// car select's blurb is. Retail's `scale` is the view's fade.
static struct {
    bool     queued;
    uint32_t screen, object, rect;
    float    alpha;
    char     text[512];             // tTreeDetails' description
} g_etvText;

static void hookEtvRenderTextRect(void* user, uint32_t screen,
                                  uint32_t object, uint32_t rect,
                                  const char* text, float scale)
{
    (void)user;
    if (!text) return;
    g_etvText.queued = true;
    g_etvText.screen = screen;
    g_etvText.object = object;
    g_etvText.rect   = rect;
    g_etvText.alpha  = scale;
    snprintf(g_etvText.text, sizeof g_etvText.text, "%s", text);
}

// A GS colour (0x80 is full, r g b a low byte first) as citro2d's plain one.
static uint32_t gsPlainColor(uint32_t gs)
{
    uint32_t out = 0;
    for (int i = 0; i < 4; i++) {
        uint32_t c = ((gs >> (8 * i)) & 0xffu) * 2u;
        out |= (c > 0xffu ? 0xffu : c) << (8 * i);
    }
    return out;
}

// After the top screen's layers. The inner (0x00144ed0) starts the pen at
// the text object's top left and breaks a line at the box's right edge:
// the box is the whole panel, the text object sits under the track's name.
// The details' description is in the port's style. The Ultimate's popup is
// in its text object's own, as retail draws both: FRONTB's narrow face
// (fb79e54c, 27 high on the PS2's 480 lines) in grey. In the details' white
// FONT_A at 10 the outline drowned it on the popup's bright picture.
static void etvDrawText(UIRenderer* ui)
{
    float       x = 0.0f, y = 0.0f, bx = 0.0f, by = 0.0f, w, h;
    float       sx = 400.0f / 640.0f, sy = 240.0f / 480.0f;
    UIWrapStyle st;
    struct FlailerTextChunk* t;

    if (!g_etvText.queued) return;
    g_etvText.queued = false;
    t = (struct FlailerTextChunk*)flailer_find_object(
        g_etvText.screen, g_etvText.object, FLAILER_TYPE_TEXT);
    if (g_etvText.alpha <= 0.0f || !t
        || !flailer_find_object(g_etvText.screen, g_etvText.rect,
                                FLAILER_TYPE_BITMAP))
        return;
    flailer_get_top_left_position(g_etvText.screen, g_etvText.object, &x, &y);
    flailer_get_top_left_position(g_etvText.screen, g_etvText.rect, &bx, &by);
    w = bx + (float)flailer_get_width(g_etvText.screen, g_etvText.rect) - x;
    if (w <= 0.0f) return;
    st = botStyle(ui, C2D_Color32(0xff, 0xff, 0xff, 0xff), 10.0f, false);
    if (g_etvText.screen == ETV_SCREEN_POPUP) {
        UIWrapStyle own = st;
        own.fontHash = t->FontHash;
        own.color    = gsPlainColor(t->Color);
        own.scale    = 1.0f;
        h = uirender_line_height(ui, &own);
        if (h > 0.0f) {
            own.scale = t->Object.ScaleY * sy;
            st = own;
        }
    }
    uirender_draw_wrapped(ui, g_etvText.text, 0, &st, x * sx, y * sy, w * sx,
                          g_etvText.alpha > 1.0f ? 1.0f : g_etvText.alpha);
}

// The Mode Selects' event tree row (CopsOffModeSelect::HandleEvent
// 0x002045f8, CopsOnModeSelect's 0x00203f50): the career's game type, one
// player, and the tree the selected event is kept for.
static void hookSetEventTree(void* user, int gameType, int numPlayerCars,
                             int treeType)
{
    (void)user;
    Fred.GameType      = gameType;
    Fred.NumPlayerCars = numPlayerCars;
    data_event_select_set_tree_type(Fred.SelectedEventData, treeType);
    logLine("event tree game=%d players=%d tree=%d", gameType,
            numPlayerCars, treeType);
}

static BAnim* hookEtvAnim(void* user)
{
    (void)user;
    return trackSelKit();
}

// 0x001e3dd0: the help off while the tree's popup is up, until the next
// SetHelpOverride.
static void hookEtvHideHelp(void* user)
{
    (void)user;
    helpmenu_disable(&g_help);
    logLine("help off");
}

static void hookEtvJukebox(void* user)
{
    hookJukebox(user, 1);
}

// ------------------------------------------------------- the HELP panel
//
// HelpMenuHooks (helpmenu.h): the strings car select's way, the common
// region's MenuSelect, the screen by retail's enum, the flow's kit.

static const char* helpTranslate(void* user, int32_t id)
{
    return hookCarSelTranslate(user, id);
}

static int helpSoundEnabled(void* user)
{
    (void)user;
    return SoundEnabled;
}

static void helpPlaySelect(void* user)
{
    (void)user;
    fesound_play(5, NULL);   // MenuSelect
}

static void helpScreenVisibility(void* user, uint32_t screen,
                                 int32_t visibility)
{
    (void)user;
    raceScreenVisibility(screen, visibility);
    logLine("help %s", visibility == FLAILER_SCREEN_VISIBLE ? "shown"
                                                           : "hidden");
}

static BAnim* helpAnim(void* user)
{
    (void)user;
    return trackSelKit();
}

// CarSelector::CanEnterOrbitMode's tHelpMenu::IsActive.
static int hookCarSelHelpActive(void* user)
{
    (void)user;
    return helpmenu_is_active(&g_help);
}

static EtvHooks g_etvHooks;

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
// ReplayManager is retail's (replaymgr.c, TASKS 72f): InitForRace's `new
// ReplayManager` is its constructor, the TICK at RACING marks the
// beginning of time, and MainLoop's BeginFrame and EndFrame (raceFrame)
// capture each frame from there into the log and the snapshots.
// RACE_IN_PROGRESS's TICK reads the beginning of time through an accessor
// retail inlines.
static int32_t replayGetBeginningOfTime(const ReplayManager* rm)
{
    return rm->BeginningOfTime;
}

// RCSTATE_POSTRACE plays the race's highlights behind the end screens
// (TASKS 72g-1): its ACTIVATE begins them, and its TICK begins the next
// once WorldLoopCounter reaches the end of the current one. The two words
// it reads, as do the End Game Menu and the pause menu, through accessors
// retail inlines (lw 12 and lw 160 of the manager).
static int32_t replayMuteHighlights(const ReplayManager* rm)
{
    return rm->MuteHighlightSoundFlag;
}

static int32_t replayEndCurrentHighlightTime(const ReplayManager* rm)
{
    return rm->EndCurrentHighlightTime;
}

// The pause menu's View Replay is there while the manager holds an
// instant replay (TASKS 72g-3): its count at +140, read inline.
static int32_t replayNumInstantReplaySnapshots(const ReplayManager* rm)
{
    return rm->NumInstantReplaySnapshots;
}

// ReplayManager::HandleSpecialEvent (0x0013e4a8), a jump to
// HandlePauseMenuReplaySpecialEvents (pausereplay.c): a pause page's
// change made as it happens and again in a replay (TASKS 72h-1). The log
// says which, by the manager's replaying flag.
static void replayHandleSpecialEvent(const ReplaySpecialEventInfo* e)
{
    int32_t known = pause_menu_replay_special_event(e);

    logPrintf("replay: special event %d (%d, %d) loop %d%s%s\n",
              (int)e->Type, (int)e->A, (int)e->B, (int)e->LoopCount,
              pReplayManager != NULL && pReplayManager->ReplayingFlag
                  ? ", replayed" : "",
              known ? "" : ", unknown");
}

// FrontendDatabase::StartRace's (0x0018549c): with a demo replay active,
// the race is the replay's, and its file goes until the track's loading
// loads it again (TASKS 72h-2a).
static void demoModeReplayStartRace(void)
{
    if (!DemoModeReplayActiveFlag)
        return;
    dmreplay_restore_race_parameters_snapshot();
    dmreplay_unload_resource_file();
    logPrintf("demo replay: file %d, track %d\n",
              (int)TheDemoModeReplay.CurrentSnapshotFileNumber,
              (int)TheRaceParameters.TrackNumber);
}

// ConsiderStartDemoMode's three (gameflow.c, TASKS 72h-2b): TheDemoModeReplay's
// ConsiderLaunching and Launch, and StartDemoMode once the flow has stopped
// the movie. The flow reads the replay's two flags as its own, which the
// main loop copies in before each pass. With "DemoReplays 0", the default
// (configitems.h), there is no replay to launch and the race is the AI's.
static int hookReplayConsiderLaunching(void* user)
{
    (void)user;
    if (!ConfigDemoReplays) return 0;
    return dmreplay_consider_launching();
}

static void hookReplayLaunch(void* user)
{
    (void)user;
    dmreplay_launch();
}

static void hookStartDemoMode(void* user)
{
    (void)user;
    demomode_start();
}

// FrontendDatabase::StartDemoMode's tail-jump to StartRace.
static void demoModeStartRace(FrontendDatabase* f)
{
    fred_start_race(f);
    logRaceStart();
}

// ReplayCheck (configitems.h), the port's own test of the replay (TASKS
// 72f-2). The race captures as retail's does; this plays two parts of it
// back and counts what does not come out the same. Round 1 sets the four
// checksum loops 600 to 900 loops into the capture and, once they are
// taken, restores the last lap snapshot before them. Round 2 sets them
// 30 to 120 loops on and then restores the older instant replay, as View
// Replay will (72g). Each replay runs on to the loop the capture had got
// to, the world's checksum (log channel 2) checked on every frame and the
// checksum snapshots verified against the race; capture then goes on.
// Each round logs the frames that did not match, the snapshot sections
// that did not verify, the snapshots held, and the slowest BeginFrame.
static struct {
    const ReplayManager* rm;   // the race's manager, to start again on a new one
    int32_t  round;            // 1 and 2 the rounds, 3 done
    int32_t  restoreAt;        // the loop the round restores on
    int32_t  replaying;        // restored, not yet back at the capture's end
    int32_t  from, to;         // the replay's loops
    int32_t  worldBad, firstWorldBad;
    int32_t  breaks, breakLines;
    int32_t  replayed;         // frames BeginFrame said replay, this round
    int32_t  verified;         // checksum snapshots it verified, this round
    u64      worst;            // the slowest BeginFrame this round, in ticks
    int32_t  worstLoop;
} g_replayCheck;

static void replayCheckPostMessage(struct RaceCoordinator* rc, int32_t msg,
                                   int32_t param)
{
    // World::VerifyDebugChecksums: a replayed frame whose checksum differs
    // from the captured one.
    if (msg == RC_SKIP_REPLAY && g_replayCheck.replaying
        && g_replayCheck.worldBad++ == 0)
        g_replayCheck.firstWorldBad = WorldLoopCounter;
    racecoordinator_post_message(rc, msg, param);
}

static void replayCheckBreak(const ReplaySnapshot* s)
{
    char    path[192];
    size_t  n = 0;
    int32_t d;

    g_replayCheck.breaks++;
    if (g_replayCheck.breakLines >= 24) return;
    g_replayCheck.breakLines++;
    path[0] = '\0';
    for (d = 0; d <= s->CurrentSectionDepth && d < REPLAY_SNAPSHOT_SECTIONS;
         d++) {
        const char* name = p32_ptr(s->SectionInfo[d].Name);
        int         k    = snprintf(path + n, sizeof path - n, "%s%s#%u",
                                    d ? " / " : "", name ? name : "?",
                                    (unsigned)s->SectionInfo[d].Number);

        if (k < 0 || (size_t)k >= sizeof path - n) break;
        n += (size_t)k;
    }
    logLine("replaycheck: %s does not verify at loop %d: %s", s->Name,
            (int)WorldLoopCounter, path);
}

// After BeginFrame: its time, the snapshots it took counted in, and
// whether it replayed, verifying a checksum snapshot (as
// maybe_do_checksum_snapshot does, the first of the four times this loop).
static void replayCheckFrame(u64 ticks)
{
    const ReplayManager* rm = pReplayManager;
    int                  i;

    if (!g_replayCheck.replaying && ticks > g_replayCheck.worst) {
        g_replayCheck.worst     = ticks;
        g_replayCheck.worstLoop = WorldLoopCounter;
    }
    if (!g_replayCheck.replaying || !rm->ReplayingFlag) return;
    g_replayCheck.replayed++;
    if (rm->ReplayPausedThisFrame) return;
    for (i = 0; i < 4; i++)
        if (ChecksumSnapshotTimes[i] == WorldLoopCounter) {
            char name[16];

            snprintf(name, sizeof name, "CHECKSUM%d", i);
            if (replaymgr_find_snapshot(pReplayManager, name, 0) != NULL)
                g_replayCheck.verified++;
            break;
        }
}

static void replayCheckReport(void)
{
    ReplayManager*        rm   = pReplayManager;
    const void*           head = rm->ReplaySnapshotList;
    const ReplaySnapshot* s;

    logLine("replaycheck: round %d replayed loops %d..%d (%d frames, %d "
            "checksum snapshots verified): %d frames off (the first at "
            "loop %d), %d sections did not verify, %d breaks in all",
            (int)g_replayCheck.round, (int)g_replayCheck.from,
            (int)g_replayCheck.to, (int)g_replayCheck.replayed,
            (int)g_replayCheck.verified, (int)g_replayCheck.worldBad,
            (int)g_replayCheck.firstWorldBad, (int)g_replayCheck.breaks,
            (int)replay_breaks);
    logLine("replaycheck: the slowest BeginFrame captured %.2f ms, at loop %d",
            clockTicksMs((u32)g_replayCheck.worst),
            (int)g_replayCheck.worstLoop);
    // EndLoopTime is a highlight's (the instant replay it was made from).
    for (s = p32_ptr(rm->ReplaySnapshotList[0]); (const void*)s != head;
         s = p32_ptr(s->pNext)) {
        char loops[24];

        if (s->EndLoopTime != 0)
            snprintf(loops, sizeof loops, "loops %d..%d",
                     (int)s->BeginLoopTime, (int)s->EndLoopTime);
        else
            snprintf(loops, sizeof loops, "loop %d", (int)s->BeginLoopTime);
        logLine("replaycheck:   %-20s %-16s %d of %d bytes%s", s->Name, loops,
                (int)s->DataPosition, (int)REPLAY_SNAPSHOT_DATA_SIZE,
                s->OverflowedFlag ? ", overflowed" : "");
    }
}

static void replayCheckSetChecksums(int32_t first, int32_t spacing)
{
    static const char* const kNames[4] = {
        "CHECKSUM0", "CHECKSUM1", "CHECKSUM2", "CHECKSUM3"};
    int i;

    for (i = 0; i < 4; i++) {
        while (replaymgr_delete_snapshot_named(pReplayManager, kNames[i]))
            ;
        ChecksumSnapshotTimes[i] = first + i * spacing;
    }
    g_replayCheck.restoreAt = first + 3 * spacing + 30;
    logLine("replaycheck: round %d: checksums from loop %d every %d, "
            "the restore at %d", (int)g_replayCheck.round, (int)first,
            (int)spacing, (int)g_replayCheck.restoreAt);
}

static void replayCheckRestore(void)
{
    ReplayManager*  rm = pReplayManager;
    ReplaySnapshot* s  = NULL;
    ReplaySnapshot* t;
    int32_t         k;

    if (g_replayCheck.round == 1) {
        // The last lap snapshot before the first checksum.
        for (k = 0; (t = replaymgr_find_snapshot(rm, "LAP_SNAPSHOT", k)) != NULL;
             k++)
            if (t->BeginLoopTime < ChecksumSnapshotTimes[0]
                && (s == NULL || t->BeginLoopTime > s->BeginLoopTime))
                s = t;
    } else {
        // The older instant replay, as View Replay's.
        for (k = 0; (t = replaymgr_find_snapshot(rm, "INSTANT_REPLAY", k)) != NULL;
             k++)
            if (s == NULL || t->BeginLoopTime < s->BeginLoopTime) s = t;
    }
    if (s == NULL) {
        logLine("replaycheck: round %d: no snapshot to restore",
                (int)g_replayCheck.round);
        g_replayCheck.round = 3;
        return;
    }
    g_replayCheck.from       = s->BeginLoopTime;
    g_replayCheck.to         = rm->EndCapturingLoopCount;
    g_replayCheck.worldBad   = 0;
    g_replayCheck.breaks     = 0;
    g_replayCheck.breakLines = 0;
    g_replayCheck.replayed   = 0;
    g_replayCheck.verified   = 0;
    logLine("replaycheck: round %d restores %s from loop %d (%.1f s back) "
            "at loop %d", (int)g_replayCheck.round, s->Name,
            (int)s->BeginLoopTime,
            (double)(WorldTimer - s->Time) * 0.00025, (int)WorldLoopCounter);
    replaymgr_restore_snapshot(rm, s);
    g_replayCheck.replaying = 1;
}

// Each race frame, after the coordinator's TICK.
static void replayCheckTick(void)
{
    ReplayManager* rm = pReplayManager;

    if (!ConfigReplayCheck || rm == NULL) return;
    if (rm != g_replayCheck.rm) {
        memset(&g_replayCheck, 0, sizeof g_replayCheck);
        g_replayCheck.rm = rm;
    }
    if (rm->pRepeat == 0 || g_replayCheck.round == 3) return;
    if (g_replayCheck.replaying) {
        if (WorldLoopCounter < g_replayCheck.to) return;
        g_replayCheck.replaying = 0;
        replayCheckReport();
        g_replayCheck.worst = 0;
        if (++g_replayCheck.round == 2)
            replayCheckSetChecksums(WorldLoopCounter + 30, 30);
        else
            logLine("replaycheck: done");
        return;
    }
    if (g_replayCheck.round == 0) {
        g_replayCheck.round = 1;
        replayCheckSetChecksums(rm->BeginCapturingLoopCount + 600, 100);
        return;
    }
    if (WorldLoopCounter >= g_replayCheck.restoreAt) replayCheckRestore();
}

// The packs' ranges still being read in: CarLoader's skins and the HUD's,
// which the race's first frames bring. By LoadingCompleted, and not by
// NumNotYetLoadedTextureDatas, which a callback's range leaves one up
// (texturestream.c).
static int racePacksStreaming(void)
{
    int    n = 0;
    bNode* p;

    for (p = TexturePackList.next; p != &TexturePackList; p = p->next) {
        const TexturePack* tp = (const TexturePack*)(void*)p;
        const bNode*       d;

        for (d = tp->LoadedTextureDataList.next;
             d != &tp->LoadedTextureDataList; d = d->next) {
            if (!((const LoadedTextureData*)(const void*)d)
                     ->LoadingCompleted) {
                n++;
            }
        }
    }
    return n;
}

static double ticksMs(uint64_t ticks)
{
    return (double)ticks * 1000.0 / SYSCLOCK_ARM11;
}

// eDisplayFrame draws what the views hold, and the port's is trackview's
// draw. In a race it draws the track the flow loaded: TRACKB<n>.LZC, which
// the resource system read and the loaders have already run over, so
// trackview reads and loads nothing and the camera is the race's. It is
// attached on the first frame of a race whose streamed textures are in,
// and everything the race can draw is made then (trackview_prepare): a
// bake or an upload mid-race is a hitch. The Begin of loading renamed the
// file for hot chunking, so it goes by its .BUN name.
//
// Until then the race's frames draw nothing (raceHoldsLoadingScreen), so
// the Loading screen stays up through the attach's seconds and the first
// frame shown is the fly-by under the Starting Grid, as retail's is
// (TASKS 41). The streams are read in place first, for up to two seconds:
// a read is made whole in the service and its callback runs in the next,
// so the frames' wait is only for a stream that takes longer.
static bool raceAttachGaveUp;

// The GPU done with the frame C3D_FrameEnd sent, so what that frame reads
// can be freed. citro3d's context starts with its GX queue (hangwatch.c
// reads it the same way), and the queue runs from the frame's end to the
// next C3D_FrameBegin, which the flow's pass is between. Half a second at
// most.
extern u8 __C3D_Context[];

static void waitRenderingDone(void)
{
    gxCmdQueue_s* q = (gxCmdQueue_s*)(void*)__C3D_Context;

    if (!gxCmdQueueWait(q, 500000000LL))
        logLine("race: the GPU not done in 0.5 s at the track's unload");
}

// gTrackFlowViewUnloadFn: the race's view lets go as the Begin of
// unloading the track starts, before the track's files go
// (trackflow.h). The loop's check for a race gone came after the flow's
// pass, and Next Race's unload goes on to the next race's load in that
// same pass: the view kept its meshes and textures (about 49 MB of the
// linear heap) and its heap through the next load, still pointing into
// the freed bundle, and TRACKB's 9 MB found no room left whole (TASKS
// 37f-2). The last frame drawn may still be on the GPU.
static void raceDetachTrack(void)
{
    struct mallinfo mi;

    if (!g_track.attached) return;
    waitRenderingDone();
    trackview_free(&g_track);
    mi = mallinfo();
    logLine("race: track detached (heap: %lu KB used; linear %lu KB free)",
            (unsigned long)mi.uordblks / 1024,
            (unsigned long)linearSpaceFree() / 1024);
    logHeapMap();
}

static bool raceAttachTrack(void)
{
    static int    waits;
    static u64    readMs;
    char          name[32];
    ResourceFile* rf;
    uint64_t      t0;
    int           bakes, uploads, frames;

    if (g_track.loaded) return g_track.attached;
    if (raceAttachGaveUp) return false;
    t0 = osGetTime();
    while (racePacksStreaming() > 0 && osGetTime() - t0 < 2000)
        (void)service_resource_loading();
    readMs += osGetTime() - t0;
    // A few frames, and no more than 150 of them.
    if (racePacksStreaming() > 0 && waits < 150) {
        waits++;
        return false;
    }
    snprintf(name, sizeof name, "TRACKS\\TRACKB%d.BUN",
             (int)RaceParametersTrackNumber);
    rf = find_resource_file(name);
    if (!rf || !rf->pFirstChunk) {
        logLine("race: track not attached: %s not loaded", name);
        raceAttachGaveUp = true;
        return false;
    }
    g_track.track = (int)RaceParametersTrackNumber;
    if (!trackview_attach(&g_track, rf->pFirstChunk,
                          (size_t)rf->SizeofChunks)) {
        logLine("race: track not attached: %s", g_track.note);
        raceAttachGaveUp = true;
        return false;
    }
    logTrackView("attached to");
    logLine("race: the top's blocks in the linear heap: %lu KB live, %lu KB "
            "the most", (unsigned long)g_topLive / 1024,
            (unsigned long)g_topLiveMost / 1024);
    heapmap_named(logTopLine, __ctru_linear_heap,
                  __ctru_linear_heap + __ctru_linear_heap_size);
    t0      = svcGetSystemTick();
    bakes   = g_track.bakes;
    uploads = g_track.uploads;
    frames  = g_track.frameUploads;
    trackview_prepare(&g_track);
    logLine("race: prepared in %.0f ms after %llu ms of reads and %d "
            "frames' wait (%d still streaming): %d models, %d bakes, %d "
            "uploads (%d past the models', %d left out, %lu KB), %d "
            "flipbook frames; %d other solids, %d textures (%d in VRAM, "
            "%lu KB, %lu KB of VRAM free), %lu KB linear free, %lu KB "
            "heap free",
            ticksMs(svcGetSystemTick() - t0), (unsigned long long)readMs,
            waits, racePacksStreaming(),
            g_track.preparedModels, g_track.bakes - bakes,
            g_track.uploads - uploads, g_track.preparedTextures,
            g_track.preparedSkipped,
            (unsigned long)g_track.preparedSkippedKB,
            g_track.frameUploads - frames,
            g_track.numOther, g_track.numTextures,
            g_track.vramTextures, (unsigned long)g_track.vramKB,
            (unsigned long)vramSpaceFree() / 1024,
            (unsigned long)linearSpaceFree() / 1024,
            (unsigned long)(g_heapInfo.heapGot - mallinfo().uordblks)
                / 1024);
    g_track.worstTicks = 0;
    waits = 0;
    readMs = 0;
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

// A race is up and its track is still to be attached: the frame draws
// nothing, and the screens keep the last one drawn, the Loading screen.
static bool raceHoldsLoadingScreen(void)
{
    return pRaceCoordinator != NULL && !g_track.loaded && !raceAttachGaveUp;
}

// Where the race is, once a second: the coordinator's state, the race's
// stage, the world's clock, player 1's car and the view's camera; and a
// camera zone's start and end as they come, as the jump cam's last a
// second or two.
// The helicopter's munitions (12k-6): those in flight, the most at once,
// and the explosions still playing.
static void logMunitions(const struct Chopper* h)
{
    const bNode* e;
    int          effects = 0;

    if (h == NULL || RocketSlotPool == NULL) return;
    if (TheMunitionEffectsHandler != NULL) {
        for (e = TheMunitionEffectsHandler->List.next;
             e != &TheMunitionEffectsHandler->List; e = e->next)
            effects++;
    }
    logLine("race: munitions: run %d plan %d salvos %d of %d, rockets %d "
            "(most %d), smoke bombs %d (%d), spikes %d (%d), effects %d",
            (int)h->BombRunType, (int)h->Plan, (int)h->NumSalvosReleased,
            (int)h->TotalSalvos, (int)RocketSlotPool->numAllocatedSlots,
            (int)RocketSlotPool->mostNumAllocatedSlots,
            (int)SmokeBombSlotPool->numAllocatedSlots,
            (int)SmokeBombSlotPool->mostNumAllocatedSlots,
            (int)DroppedSpikesSlotPool->numAllocatedSlots,
            (int)DroppedSpikesSlotPool->mostNumAllocatedSlots, effects);
}

static void logRaceState(void)
{
    static int32_t next;
    static int32_t lastZone;
    const eView*   view = eGetView(EVIEW_ID_PLAYER1);
    const World*   w    = pCurrentWorld;
    const struct Player* p = PlayerNumPlayers > 0 ? PlayerPlayersByIndex[0]
                                                  : NULL;

    // With no log (DebugLog 0), none of the second's sums are made.
    if (!g_log) return;
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
    if (pReplayManager != NULL) {
        const ReplayManager* rm = pReplayManager;

        logLine("race: replay log %d, capturing %d, replaying %d, paused %d, "
                "loops %d..%d at %d, snapshots: instant %d, laps %d, "
                "highlights %d",
                rm->pRepeat != 0, (int)rm->CapturingFlag,
                (int)rm->ReplayingFlag, (int)rm->PausedFlag,
                (int)rm->BeginCapturingLoopCount,
                (int)rm->EndCapturingLoopCount, (int)WorldLoopCounter,
                (int)rm->NumInstantReplaySnapshots, (int)rm->NumLapSnapshots,
                (int)rm->NumHighlightSnapshots);
    }
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
        // The player's nitro, as careffects.c reads it for the flames.
        if (c->TheMovementMode == PHYSICS_MOVEMENT && c->pCarMover != NULL
            && ((PhysicsCar*)(void*)c->pCarMover)->pEngine != NULL
            && ((PhysicsCar*)(void*)c->pCarMover)->pEngine->NitroFlag != 0)
            logLine("race: car 0 nitro on");
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
    // The traffic: where TrafficTeleporter put each car, or last moved it,
    // and its clock.
    if (w) {
        int i;

        for (i = w->TrafficCarPos;
             i < (int)w->TotalNumCars && i < WORLD_MAX_CARS; i++) {
            const Car* c = w->CarTable[i];

            if (!c) continue;
            logLine("race: traffic car %d at %.1f %.1f %.1f, DAT %.1f, speed "
                    "%.2f, mode %d, control %d, drawn %d, skin %d",
                    i, (double)c->State.Position.x,
                    (double)c->State.Position.y, (double)c->State.Position.z,
                    (double)c->TheTrackPathCoordinate.DistanceAroundTrack,
                    (double)c->State.ForwardSpeed, (int)c->TheMovementMode,
                    (int)c->TheControlMode, (int)c->RenderingEnabled,
                    c->pRideInfo ? (int)c->pRideInfo->SkinNumber : -99);
        }
        if (w->Teleporter)
            logLine("race: teleporter next in %.2f, last %d, totals %u "
                    "and %u",
                    (double)w->Teleporter->TimeUntilTeleport,
                    (int)w->Teleporter->LastCar,
                    (unsigned)w->Teleporter->ForwardTotals[
                        TRAFFIC_ROUTES_EACH - 1],
                    (unsigned)w->Teleporter->BackwardTotals[
                        TRAFFIC_ROUTES_EACH - 1]);
    }
    logLine("race: track drew %d of %d (%d sky), %d tris; %s",
            g_track.drawn, g_track.drawInfos, g_track.skyDrawn,
            g_track.drawnTris, g_track.note);
    logLine("race: minimap %d polys (%d failed)", g_track.flailerPolys,
            g_track.flailerFailed);
    logLine("race: radial blur %d frames blended, %d failed",
            g_track.blurBlends, g_track.blurFailed);
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
    logLine("race: other solids %d (%d failed, %d dropped), %d bakes "
            "failed, textures %d "
            "(%d missing, %d reduced, %d unchained, %d evicted), deferred "
            "%d dropped; strips %d (%d dropped, %d joined); %lu KB linear free",
            g_track.numOther, g_track.otherFailed, g_track.otherDropped,
            g_track.bakesFailed,
            g_track.numTextures, g_track.missingTextures,
            g_track.reducedTextures, g_track.unchainedTextures,
            g_track.evictedTextures,
            g_track.deferredDropped,
            g_track.stripsDrawn, g_track.stripsDropped,
            g_track.stripsJoined,
            (unsigned long)linearSpaceFree() / 1024);
    {
        const bNode*        n;
        const tPursuitNode* s;
        int                 objects = 0, on = 0, strips = 0;

        for (n = WorldObjectList.next; n != &WorldObjectList; n = n->next) {
            objects++;
            on += ((const WorldObject*)(const void*)n)->Enabled != 0;
        }
        if (pCopManager != NULL) {
            for (s = pCopManager->SpikeStripList.Next;
                 s != &pCopManager->SpikeStripList; s = s->Next) {
                strips++;
            }
        }
        logLine("race: world objects %d (%d on), spike strips %d, heli "
                "sheet %d polys; drive target NaN resamples %d", objects, on,
                strips, TheHeliSheet != NULL ? TheHeliSheet->NumPolys : -1,
                (int)DriveTargetNaNResamples);
    }
    if (pCopManager != NULL) {
        // The chases, the first one's helicopter side, and the helicopter.
        const tPursuitNode*   n;
        const tPursuit*       first = NULL;
        const struct Chopper* h = pCurrentWorld != NULL
                                      ? pCurrentWorld->Helicopter : NULL;
        int                   chases = 0;

        // The first chase, or the first with the helicopter.
        for (n = pCopManager->PursuitList.Next;
             n != &pCopManager->PursuitList; n = n->Next) {
            const tPursuit* q = (const tPursuit*)(const void*)n;

            if (chases++ == 0
                || (q->pChopper != NULL && first->pChopper == NULL))
                first = q;
        }
        logLine("race: chases %d, first behaviours %08lx chopper state %d "
                "timer %.1f; helicopter %s plan %d at %.0f %.0f %.0f, busy "
                "%d", chases,
                first != NULL ? (unsigned long)first->BehaviourFlags : 0ul,
                first != NULL ? (int)first->ChopperState : -1,
                first != NULL ? (double)first->fChopperAttackTimer : 0.0,
                h != NULL ? "up" : "none", h != NULL ? (int)h->Plan : -1,
                h != NULL ? (double)h->CurrentPos.x : 0.0,
                h != NULL ? (double)h->CurrentPos.y : 0.0,
                h != NULL ? (double)h->CurrentPos.z : 0.0,
                (int)pCopManager->bChopperBusy);
        logMunitions(h);
        if (p != NULL && p->MyCar != NULL) {
            // Player 0's pullover NIS (12l-2): playing or not, which NIS
            // and camera, when it ends, the next of each kind, and the
            // tickets so far.
            const NisManager* nm = p->pNisManager;

            logLine("race: player NIS %s, playing %d nis %d cam %d end %ld, "
                    "next ticket %d arrest %d, tickets %d",
                    nm != NULL ? "up" : "none",
                    nm != NULL ? (int)nm->Playing : 0,
                    nm != NULL ? (int)nm->NisNumber : -1,
                    nm != NULL ? (int)nm->CamNumber : -1,
                    nm != NULL ? (long)nm->EndTime : 0l,
                    (int)p->TicketNisIndex, (int)p->ArrestNisIndex,
                    (int)copmanager_get_num_tickets(pCopManager,
                                                    p->MyCar));
        }
    } else if (pCurrentWorld != NULL && pCurrentWorld->Helicopter != NULL) {
        // ForceChopper's helicopter in a race with no cops.
        const struct Chopper* h = pCurrentWorld->Helicopter;

        logLine("race: helicopter plan %d at %.0f %.0f %.0f", (int)h->Plan,
                (double)h->CurrentPos.x, (double)h->CurrentPos.y,
                (double)h->CurrentPos.z);
        logMunitions(h);
    }
    if (pCurrentWorld != NULL) {
        // The cop cars, those with their lights on, and their red, blue
        // and white flares; then the flares drawn since the last line.
        int cops = 0, lit = 0, copFlares = 0, i;

        for (i = 0; i < pCurrentWorld->TotalNumCars && i < WORLD_MAX_CARS;
             i++) {
            const Car*   c = pCurrentWorld->CarTable[i];
            const bNode* n;
            DriverType   t;

            if (c == NULL || c->MyDriver == NULL)
                continue;
            t = c->MyDriver->TheDriverType;
            if (t != DRIVER_TYPE_COP && t != DRIVER_TYPE_SUPER_COP)
                continue;
            cops++;
            lit += c->CopLights != 0;
            if (c->pRenderInfo == NULL)
                continue;
            for (n = c->pRenderInfo->LightFlareList.next;
                 n != &c->pRenderInfo->LightFlareList; n = n->next) {
                const eLightFlare* f = (const eLightFlare*)(const void*)n;

                copFlares += f->Type >= 4 && f->Type <= 6;
            }
        }
        logLine("race: cop cars %d, %d lights on, %d cop flares; flares "
                "asked %d drawn %d, cop asked %d drawn %d", cops, lit,
                copFlares, s_flaresAsked, s_flaresDrawn, s_copFlaresAsked,
                s_copFlaresDrawn);
        s_flaresAsked = s_flaresDrawn = 0;
        s_copFlaresAsked = s_copFlaresDrawn = 0;
    }
    {
        // What the race baked and uploaded since the last line: after
        // trackview_prepare, each one is a hitch.
        static int      lastBakes, lastUploads, lastRefreshes;
        static uint64_t lastBakeTicks, lastUploadTicks, lastRefreshTicks;

        if (g_track.bakes < lastBakes || g_track.uploads < lastUploads) {
            // Another race's view: trackview_free starts the counts again.
            lastBakes = lastUploads = 0;
            lastBakeTicks = lastUploadTicks = 0;
        }
        if (g_track.bakes != lastBakes || g_track.uploads != lastUploads) {
            logLine("race: made %d bakes in %.1f ms and %d uploads in "
                    "%.1f ms, the longest %.1f ms: %s",
                    g_track.bakes - lastBakes,
                    ticksMs(g_track.bakeTicks - lastBakeTicks),
                    g_track.uploads - lastUploads,
                    ticksMs(g_track.uploadTicks - lastUploadTicks),
                    ticksMs(g_track.worstTicks), g_track.lateNames);
        }
        g_track.lateNames[0] = '\0';
        if (g_track.refreshes < lastRefreshes) {
            lastRefreshes = 0;
            lastRefreshTicks = 0;
        }
        if (g_track.refreshes != lastRefreshes) {
            logLine("race: refreshed %d damaged meshes in %.1f ms",
                    g_track.refreshes - lastRefreshes,
                    ticksMs(g_track.refreshTicks - lastRefreshTicks));
        }
        lastRefreshes      = g_track.refreshes;
        lastRefreshTicks   = g_track.refreshTicks;
        lastBakes          = g_track.bakes;
        lastUploads        = g_track.uploads;
        lastBakeTicks      = g_track.bakeTicks;
        lastUploadTicks    = g_track.uploadTicks;
        g_track.worstTicks = 0;
    }
    {
        // Each time more are missing: which, and whether they had pixels
        // (none is a pack not streamed in; with them, no room or no
        // upload), and the mirror's two.
        static int lastMissing;
        int        i;

        if (g_track.missingTextures != lastMissing) {
            lastMissing = g_track.missingTextures;
            for (i = 0; i < g_track.numTextures; i++) {
                const TrackTex* t = &g_track.texture[i];

                if (!t->valid && !t->evicted && t->info) {
                    logLine("race: texture %.24s missing, pixels %p, "
                            "%ux%u, %d bits, %lu KB linear free",
                            t->info->DebugName,
                            (const void*)t->info->ImageData,
                            (unsigned)t->info->Width,
                            (unsigned)t->info->Height,
                            (int)t->info->BitDepth,
                            (unsigned long)linearSpaceFree() / 1024);
                }
            }
            logLine("race: RVM %p, RVM_MASK %p", pTextureInfoRVMInfo,
                    pTextureInfoRVMMask);
        }
    }
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

// A hangwatch mark, and the thread guard's check there (threadguard.h,
// with "ThreadGuard 1"): a write over the audio workers' blocks is caught
// at the next mark, and the report names the two it fell between.
static void frameMark(const char* where)
{
    hangwatch_mark(where);
    threadguard_check(where);
}

// The guard's report's last line: where the game was.
static void guardNote(FILE* f)
{
    const Race* r = pCurrentRace;
    fprintf(f, "threadguard: flow %d, race %s, stage %d, %d racing cars\n",
            (int)g_flow.current, r ? "up" : "none",
            r ? (int)r->RaceStage : -1, r ? (int)r->NumRacingCars : 0);
}

// MainLoop's race half (0x0012f3c8 .. 0x0012f5fc), after the flow's
// service: the coordinator, the world's step, and the cameras. The calls
// the port does not have yet are named where they would be.
// ForceChopper (configitems.h), the port's own test of the helicopter's
// munitions with no chase. In an R-held race the helicopter egg is on
// (eggIsOn below), so InitCars makes the helicopter even with no cops and
// it follows the player's car (Chopper::DoTweakerTriggers); no chase can
// take it (its word at 960). Each time it is back in PURSUIT this waits a
// few seconds and starts a bombing run of the kind the item names. With
// no cop manager (SkipFEMaxCops 0) a spike belt has no list for its strip
// (DroppedSpikes::Explode), so the belt becomes a smoke bomb. 6 only
// follows.
static int32_t eggIsOn(int32_t n)
{
    return n == EGG_HELICOPTER && g_flow.skipFE && ConfigForceChopper > 0;
}

static void forceChopperTick(float dt)
{
    static const struct Chopper* last;
    static float                 wait;
    static int                   turn;
    struct Chopper*              h;
    ChopperAttackType            type;

    if (!eggIsOn(EGG_HELICOPTER) || pCurrentWorld == NULL) return;
    h = pCurrentWorld->Helicopter;
    // The replay's snapshots clear an idle helicopter, its word at 960
    // too (copsnap.c, TASKS 72e-1), so the follow is set again.
    if (h != NULL) h->New960 = 1;
    if (ConfigForceChopper >= 6) return;
    if (h == NULL || h->CurrentCar == NULL) return;
    if (h != last) {
        last = h;
        wait = 5.0f;
        turn = 0;
    }
    if (h->Plan != CHOPPLAN_PURSUIT) return;
    wait -= dt;
    if (wait > 0.0f) return;
    wait = 4.0f;
    if (ConfigForceChopper >= 5)
        type = (ChopperAttackType)(turn++ % 4);
    else
        type = (ChopperAttackType)(ConfigForceChopper - 1);
    if (type == CHOPATTACK_SPIKE_BELT && pCopManager == NULL)
        type = CHOPATTACK_SMOKE_BOMB_1;
    if (chopper_attack_car(h, type))
        logLine("race: ForceChopper bombing run %d", (int)type);
}

static void raceFrame(void)
{
    RaceCoordinator* rc = pRaceCoordinator;
    World*           w;

    // The coordinator's queued messages, CheckForDemoDiscTimeout (the
    // demo disc's, and the port runs as retail with DemoDiscManager off),
    // a TICK, and ServiceGameFlow again.
    frameMark("race: coordinator");
    racecoordinator_execute_queued_messages(rc);
    racecoordinator_send_message(rc, RC_TICK, 0);
    bgf_service(&g_flow);
    if (pRaceCoordinator == NULL) return;
    replayCheckTick();

    // UpdateStomper is empty, and 0x0012f190 is the joylog's checksum.
    // Then the players' handlers for the coordinator's state: racing is
    // what gives the car the pad.
    determine_all_players_input_modes();
    if (pReplayManager != NULL)
        replaymgr_do_fancy_joylog_debugging(pReplayManager);

    // The flow paused (the coordinator in PAUSE) steps the world by 0, as
    // a paused world does, and neither is a replay's frame. Otherwise
    // MainLoop asks for the World and the ReplayManager with no test:
    // InitForRace made both with the coordinator. BeginFrame says whether
    // the frame captures or replays. A replay paused this frame (the
    // replay screen's pause, or three frames in four of its slow motion)
    // steps by 0, its events still read; otherwise the world steps.
    // EndFrame moves the capture on.
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
            u64 t0 = ConfigReplayCheck ? svcGetSystemTick() : 0;

            frameMark("race: the replay's frame");
            replaymgr_begin_frame(pReplayManager);
            if (ConfigReplayCheck)
                replayCheckFrame(svcGetSystemTick() - t0);
            if (pReplayManager->ReplayPausedThisFrame) {
                PrepareWorldTimestep(0.0f);
                GenerateJoyEvents();
                MainLoopTiming.GenerateJoyEvents = bGetTicker();
            } else {
                // A replay's step spins out the frame to the step the
                // capture logged; frameprof times that wait apart.
                uint32_t spin = bGetTicker();
                float step = world_get_timestep(w);

                if (pReplayManager->ReplayingFlag)
                    FrameProfReplayWait = bGetTicker() - spin;
                PrepareWorldTimestep(step);
                GenerateJoyEvents();
                MainLoopTiming.GenerateJoyEvents = bGetTicker();
                frameMark("race: the world's step");
                forceChopperTick(step);
                world_do_timestep(w, step);
            }
            replaymgr_end_frame(pReplayManager);
        }
    }
    MainLoopTiming.WorldDoTimestep = bGetTicker();
    frameMark("race: the cameras");

    // MenuSystemTick is bgf_frame's. ReplayScreen::Update runs on the race
    // coordinator's screen, which the instant replay's state makes (72g-3).
    // UpdateCameraCoordinators (0x00199bd0) takes the real step
    // (RealTimeElapsed, retail's gp-19596), as MainLoop gives it.
    // sound::Update runs at the top of the frame, and UpdatePortRumblers
    // has no rumble to drive.
    update_players_non_game_state();
    if (pRaceCoordinator != NULL && pRaceCoordinator->pReplayScreen != NULL)
        replayscreen_update(pRaceCoordinator->pReplayScreen);
    update_camera_coordinators(RealTimeElapsed);
    update_camera_movers();
    MainLoopTiming.UpdateCameraMovers = bGetTicker();
    update_camera_shakers();
    frameMark("race: the log");
    logRaceState();
}

static int flowInput(u32 kDown, int port);

// gJoypadRead: in a lockstep frame each port reads its place's pad from
// the frame's record (netstep.h), as the DualShock joyhid builds; else the
// console's own buttons on port 0.
static int32_t joypadRead(int32_t port, uint8_t* buf)
{
    const NetStepFrame* r = netstep_current();

    if (r == NULL) return joyhid_read(port, buf);
    joyhid_from_wire(r->pad[port].ds2, buf);
    return 1;
}

// A pause whose port's place is dropped (37g) goes, with its popup, to the
// lowest place still racing that has a port, on every console alike: else
// no pad would reach the pause's screens (pause_menu_enter_pause filters
// them to the pauser's port), and the race would stay paused for good.
static void lockPauseHandOver(uint8_t live)
{
    RaceCoordinator* rc = pRaceCoordinator;
    int              from = -1, to = -1;

    if (rc == NULL || ThePauseMenu == NULL) return;
    if (ThePauseMenu->State != PAUSE_MENU_STATE_NONE)
        from = ThePauseMenu->Port;
    else if (rc->CurrentRCState == RCSTATE_PAUSE)
        from = rc->PausedJoystickPort;
    if (from < 0 || from >= JOYSTICK_PORTS || ((live >> from) & 1)) return;
    for (int p = 0; p < JOYSTICK_PORTS && to < 0; p++)
        if ((live >> p) & 1) to = p;
    if (to < 0) return;
    rc->PausedJoystickPort = to;
    if (ThePauseMenu->State != PAUSE_MENU_STATE_NONE)
        pause_menu_enter_pause(ThePauseMenu, to);
    for (int i = 0; i < BPOPUP_COUNT; i++) {
        BPopup* pp = &g_flow.popups[i];

        if (!pp->active || pp->cfg.joyPort != from) continue;
        pp->cfg.joyPort = to;
        for (int b = 0; b < 3; b++) pp->items[b].joyPort = to;
    }
    logLine("lockstep: frame %lu, the pause from port %d to port %d",
            (unsigned long)netstep_frame(), from, to);
}

// Well behind the race's last record: a console back after a restart,
// running the race from GO on the host's records (37g-3). It is from its
// GO, before its first record says how far behind: it shows none of the
// race's start (the grid, the fly-by, the countdown), and is straight
// back in the race once it has caught up. The first NETSTEP_DELAY records
// are its own, made at GO, and say nothing of the host's.
static bool lockCatchingUp(void)
{
    return g_lockBack || netstep_behind() > NETSTEP_BEHIND;
}

// The cars of the places dropped from the record (37g: a console lost past
// its hold, or gone) go to the CPU on the frame of the first record without
// them, before its world step: the same frame on every console. A car not
// made yet, or not yet a player's, is tried again each frame. A cop's car
// waits for TASKS 61. The CPU's notice is shown a few seconds, but not by a
// console catching up: that is the race's past.
static void lockHandOver(void)
{
    const NetStepFrame* r = netstep_current();
    uint8_t             gone;

    if (r == NULL) return;
    gone = (uint8_t)(g_lockLive & ~r->live & ~g_lockCpu);
    if (gone) {
        uint32_t now = (uint32_t)osGetTime();

        logLine("lockstep: frame %lu, places %02x dropped",
                (unsigned long)netstep_frame(), (unsigned)gone);
        if (!lockCatchingUp()) {
            if (now - g_lockNoteAt >= LOCK_NOTE_MS) g_lockNote = 0;
            g_lockNote |= gone;
            g_lockNoteAt = now;
        }
        g_lockCpu |= gone;
        lockPauseHandOver(r->live);
    }
    if (g_lockCpu == 0 || pCurrentWorld == NULL) return;
    for (int p = 0; p < NETSTEP_MAX; p++) {
        int  driver = netrace_driver(p);
        Car* car;

        if (!((g_lockCpu >> p) & 1) || driver < 0) continue;
        car = world_get_car_by_driver_number(driver);
        if (car == NULL || car->TheControlMode != REAL_CONTROL) continue;
        car_set_control_mode(car, AI_CONTROL);
        logLine("lockstep: frame %lu, place %d's car (driver %d) to the CPU",
                (unsigned long)netstep_frame(), p, driver);
    }
}

// A console lost (37g-2). The host lets it back into its place while the
// race holds for it: the place whose peer it is, among those held for
// now. A client that lost its host looks for it again each
// LOCK_REJOIN_MS while it holds for it (the scan blocks the loop, the race
// held already).
static int lockRejoinOk(int peer)
{
    const LobbyRace* r = netrace_race();
    uint8_t          held = netstep_held((uint32_t)osGetTime(), NULL);

    for (int p = 1; p < r->consoles && p < NETSTEP_MAX; p++)
        if (r->peer[p] == peer) return (held >> p) & 1;
    return 0;
}

static void lockRejoin(uint32_t now)
{
    uint8_t held = netstep_held(now, NULL);

    if (wireless_is_host()) {
        wireless_set_rejoin(held != 0, lockRejoinOk);
        return;
    }
    if (!(held & 1) || wireless_state() != WIRELESS_LOST) return;
    if (now - g_lockRejoinAt < LOCK_REJOIN_MS) return;
    g_lockRejoinAt = now;
    (void)wireless_rejoin();
}

// WirelessTestDropFrame (configitems.h): this console deaf from that
// lockstep frame for WirelessTestDropMs, its links lost at both ends.
static void lockTestDrop(void)
{
    if (ConfigWirelessTestDropFrame <= 0 || g_lockDropped
        || netstep_frame() < (uint32_t)ConfigWirelessTestDropFrame)
        return;
    g_lockDropped = true;
    logLine("lockstep: frame %lu, deaf for the test",
            (unsigned long)netstep_frame());
    wireless_test_deaf(ConfigWirelessTestDropMs > 0
                       ? (uint32_t)ConfigWirelessTestDropMs : 5000u);
}

// WirelessTestBlindFrame (configitems.h): this lockstep frame undrawn for
// the test, and its first said.
static bool lockTestBlind(void)
{
    static bool said;
    uint32_t    f = netstep_frame();
    bool        blind = ConfigWirelessTestBlindFrame > 0
                        && f >= (uint32_t)ConfigWirelessTestBlindFrame
                        && f - (uint32_t)ConfigWirelessTestBlindFrame
                           < (uint32_t)ConfigWirelessTestBlindFrames;

    if (blind && !said) {
        said = true;
        logLine("lockstep: frame %lu, undrawn for the test, %ld frames",
                (unsigned long)f, (long)ConfigWirelessTestBlindFrames);
    }
    return blind;
}

// The race held for a lost console (37g) is muted, as the pause mutes it,
// unless it was muted already; the hold's end, or lockstep's, unmutes it.
// No lockstep frame runs in a hold, so the pause cannot change it under.
static void raceSoundMute(int32_t on);

static void lockHoldMute(bool held)
{
    if (held == g_lockMuted) return;
    if (held && (gSoundModule.jb == NULL || gSoundModule.jb->muted)) return;
    raceSoundMute(held ? 1 : 0);
    g_lockMuted = held;
}

// A console catching up (37g-3) runs the race's past fast: its sound the
// game's as ever, under the master volume, down until it is in step and
// then faded in as after an applet. The game's own mute is the past's to
// change (a pause in it), so it is left alone.
static void lockCatchUpMute(bool on)
{
    if (on == g_lockCatchMuted) return;
    g_lockCatchMuted = on;
    logLine("lockstep: frame %lu, catching up %s",
            (unsigned long)netstep_frame(), on ? "begins" : "is over");
    if (!gAudioUp) return;
    if (on) {
        ndspSetMasterVol(0.0f);
        gHold = HOLD_APPLET;
        return;
    }
    gHold      = HOLD_WAIT;
    gHoldUntil = svcGetSystemTick();
    audioHoldTick();
}

// A wireless race's frame in lockstep (netstep.h), at the top of the loop
// where the real step is measured. A frame begins by putting this
// console's pad and its step -- from the last frame's begin to this one's
// -- for the frame NETSTEP_DELAY on; it runs once its record is in, on the
// record's step. A record a few milliseconds late is waited for here; one
// later than that, the loop draws and pumps the link without stepping, and
// asks again on the next. 1 when the frame runs.
#define LOCK_SPIN_MS 8

static bool lockFrame(uint32_t* ticker)
{
    const NetStepFrame* r;

    if (!g_lockWaiting) {
        NetStepPad pad;
        uint8_t    buf[32];

        prepare_real_timestep_from_ticker(ticker);
        if (joyhid_read(0, buf))
            memcpy(pad.ds2, buf + 2, NETSTEP_PAD_BYTES);
        else
            netstep_rest(&pad);
        pad.menu = (uint16_t)g_lockMenu;
        g_lockMenu = 0;
        netstep_put(&pad, (uint8_t)RealTimeElapsedQuantized);
        g_lockWaiting = true;
    }
    for (int tries = 0;; tries++) {
        uint32_t now = (uint32_t)osGetTime();

        if (wireless_state() != WIRELESS_OFF) wireless_pump(now);
        if (netstep_poll(now)) break;
        if (tries == LOCK_SPIN_MS) return false;
        svcSleepThread(1000000LL);
    }
    r = netstep_current();
    if (netstep_frame() >= NETSTEP_DELAY) g_lockBack = false;
    RealTimeElapsedQuantized = r->q;
    RealTimeElapsed = GetRealTimeElapsedFromQuantized(r->q);
    g_lockWaiting = false;
    lockHandOver();
    return true;
}

// The record's presses for the flow, each place's on its port: the two
// players' (a third place's on, 37d-2). Each frame's presses are logged
// with the screen they reach, as every console hears them.
static int lockFlowInput(void)
{
    const NetStepFrame* r = netstep_current();
    int                 redraw = 0;

    for (int p = 0; r != NULL && p < JOYSTICK_PORTS; p++) {
        if (!((r->live >> p) & 1)) continue;
        if (r->pad[p].menu != 0)
            logLine("lockstep: frame %lu, port %d's presses %04x, screen %08lx",
                    (unsigned long)netstep_frame(), p,
                    (unsigned)r->pad[p].menu,
                    (unsigned long)(g_flow.screen ? g_flow.screen->hash : 0));
        redraw |= flowInput(r->pad[p].menu, p);
    }
    return redraw;
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
// Whether the line before this one had any text: the popup fades in and
// out with the line only when it comes up from the logo or goes back to it.
static bool  g_blurbHad;

// Every screen in FRONTB.BUN ships the same authoring placeholder in
// SCROLLING_TEXT and a screen whose blurb has not been set yet still has
// it. Drawing that would be drawing a note to the artist. The event tree's
// blurb has its own, which shows again while the Ultimate's popup has the
// blurb frozen (banim_blurb_freeze empties it).
static const char* const kBlurbPlaceholders[] = {
    "This text will scroll sideways",
    "This is The Title of the Event",
};

// A screen registered to bgf_plain_screen_callback draws and answers the
// D-pad and nothing else, and it has no blurb object, so the panel says
// so. 0x87 is the B button's icon in the menus (helpglyph.h).
static const char kPlainScreenNote[] =
    "This screen is not available yet. Press \x87 to go back.";

// While View Replay plays (the pause menu's or the End Game Menu's), the
// panel says how to leave it: START is the replay's SKIP (scannertab.c's
// 92), which goes back to the menu it came from, and retail marks it on
// the bar with an eject symbol alone (the user's of 2026-10-19). The HUD
// is down in a replay (playerhud.c), so the panel takes the whole bottom
// screen. 0x80 is START's glyph and 0x89 Circle's, Y in the replay's
// scanners layout (helpglyph.h).
static const char kReplayNote[] =
    "Press START to leave the replay and go back to the menu.";
static const char kReplayHint[] = "\x80 Back to menu    \x89 Help";

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
    // The event tree's blurb has a name of its own.
    if (idx < 0)
        idx = bui_find_object(b->project, b->screen, ETV_OBJ_SCROLLING,
                              BUI_TYPE_TEXT);
    if (idx < 0) return;
    s = uirender_object_string(b->ui, b->project, (uint32_t)idx, &len);
    if (!s || len == 0) return;
    for (size_t i = 0;
         i < sizeof kBlurbPlaceholders / sizeof kBlurbPlaceholders[0]; i++) {
        size_t n = strlen(kBlurbPlaceholders[i]);
        if (len >= n && memcmp(s, kBlurbPlaceholders[i], n) == 0) return;
    }
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
            g_blurbHad  = g_blurbShown[0] != '\0';
            memcpy(g_blurbShown, live, sizeof g_blurbShown);
        }
    } else if (g_blurbFade < 1.0f) {
        g_blurbFade += dt / 0.20f;
        if (g_blurbFade > 1.0f) g_blurbFade = 1.0f;
    }
}

// The bottom screen (TASKS 70, the user's of 2026-10-16). With nothing to
// say it is the game's logo, centred on black. With a line it is the
// frontend's popup (FRONTB's POPUP): the title plate, the red rule under
// it, the grey panel fading to the right and the light rule closing it,
// the line in the popup's italic. The buttons' help is under it, in the
// main menu's "Help" font, and the logo beside it, small, where the main
// menu has its own. The art is the disc's. A texture that is not loaded
// is left out, and FONT_A stands in for a font that is not.
#define BOT_TEX_PLATE  0xc5a905afu   // the title plate, 512 x 24
#define BOT_TEX_RULE   0x9d8cef61u   // 8 x 8, the red in its middle rows
#define BOT_TEX_LINE   0xe5f201a7u   // the light rule
#define BOT_TEX_WHITE  0xe2a5c626u   // WHITE16X16
#define BOT_TEX_LOGO   0xc9f75a5bu   // NFS_LOGO_ALPHA, GLOBALB's, 296 x 80
#define BOT_FONT_ITAL  0xa2d444f6u   // the popup's
#define BOT_FONT_HELP  0xa9bfda04u   // the main menu's "Help"

#define BOT_BOX_TOP      6.0f
#define BOT_PLATE_H     22.0f
#define BOT_BOX_BOT    192.0f
#define BOT_GS_FULL    0x80808080u   // GS white, r g b a low byte first
#define BOT_GS_FADED   0x19808080u   // the rules' right end
#define BOT_GS_PANEL_L 0x40808080u   // the panel, left and right
#define BOT_GS_PANEL_R 0x20808080u

// botStyle in font `font`, or in FONT_A when that one is not loaded.
static UIWrapStyle botFontStyle(UIRenderer* ui, uint32_t font,
                                uint32_t color, float px, bool center)
{
    UIWrapStyle st = botStyle(ui, color, px, center);
    UIWrapStyle f  = st;
    float       h;

    f.fontHash = font;
    f.scale    = 1.0f;
    h = uirender_line_height(ui, &f);
    if (h <= 0.0f) return st;
    f.scale = px / h;
    return f;
}

// The middle of NFS_LOGO_ALPHA's lettering, as a fraction of the texture:
// its bright pixels run x 54..273 and y 10..74 of the 296 x 80. The faint
// streaks run on to x 8 on the left only, so the texture's own middle
// reads as right of centre (the user's 3DS, 2026-10-16).
#define BOT_LOGO_MID_X (163.5f / 296.0f)
#define BOT_LOGO_MID_Y (42.0f / 80.0f)

// The logo at `scale`, its lettering centred on (cx, cy), on whole pixels.
static void drawBotLogo(UIRenderer* ui, float cx, float cy, float scale,
                        float alpha)
{
    int32_t w = 0, h = 0;

    if (alpha <= 0.0f || !uirender_texture_size(ui, BOT_TEX_LOGO, &w, &h))
        return;
    (void)uirender_draw_texture(ui, BOT_TEX_LOGO,
                                floorf(cx - (float)w * scale * BOT_LOGO_MID_X),
                                floorf(cy - (float)h * scale * BOT_LOGO_MID_Y),
                                (float)w * scale, (float)h * scale,
                                BOT_GS_FULL, BOT_GS_FULL, alpha);
}

// `body` wrapped and centred in the popup, at `alpha`; the popup itself,
// `title` on its plate, `hint` and the small logo at `frame`. An empty
// body is the logo alone, at `alpha`.
static void drawBotDialog(UIRenderer* ui, const char* title, const char* body,
                          float alpha, float frame, const char* hint)
{
    static const float kPx[] = { 18.0f, 16.0f, 14.0f };
    uint32_t    text  = C2D_Color32(0xe0, 0xe0, 0xe0, 0xff);
    float       boxW  = BOT_W - BOT_PAD * 2.0f;
    float       top   = BOT_BOX_TOP + BOT_PLATE_H + 6.0f;
    float       bot   = BOT_BOX_BOT - 4.0f;
    UIWrapStyle st;
    float       h = 0.0f;

    if (!body || !*body) {
        drawBotLogo(ui, BOT_W * 0.5f, BOT_H * 0.5f, 1.0f, alpha);
        return;
    }
    if (frame > 0.0f) {
        (void)uirender_draw_texture(ui, BOT_TEX_WHITE, 0.0f,
                                    BOT_BOX_TOP + BOT_PLATE_H, BOT_W,
                                    BOT_BOX_BOT - BOT_BOX_TOP - BOT_PLATE_H,
                                    BOT_GS_PANEL_L, BOT_GS_PANEL_R, frame);
        (void)uirender_draw_texture(ui, BOT_TEX_PLATE, 0.0f, BOT_BOX_TOP,
                                    BOT_W, BOT_PLATE_H, BOT_GS_FULL,
                                    BOT_GS_FULL, frame);
        (void)uirender_draw_texture(ui, BOT_TEX_RULE, 0.0f,
                                    BOT_BOX_TOP + BOT_PLATE_H - 3.0f, BOT_W,
                                    8.0f, BOT_GS_FULL, BOT_GS_FADED, frame);
        (void)uirender_draw_texture(ui, BOT_TEX_LINE, 0.0f,
                                    BOT_BOX_BOT - 2.0f, BOT_W, 4.0f,
                                    BOT_GS_FULL, BOT_GS_FADED, frame);
        if (title && *title) {
            st = botFontStyle(ui, BOT_FONT_ITAL,
                              C2D_Color32(0xc8, 0xc8, 0xc8, 0xff), 14.0f,
                              false);
            uirender_draw_wrapped(ui, title, 0, &st, 10.0f, BOT_BOX_TOP + 4.0f,
                                  boxW, frame);
        }
        if (hint && *hint) {
            // The last line where a one-line hint goes; more lines grow up
            // into the gap under the popup, never into it. The small logo's
            // left edge is at about x 176.
            float hintW = BOT_W - 164.0f, hintY;
            st    = botFontStyle(ui, BOT_FONT_HELP, BOT_TEXT, 14.0f, false);
            hintY = BOT_H - 25.0f + uirender_line_height(ui, &st)
                  - uirender_wrap_height(ui, hint, 0, &st, hintW);
            if (hintY < BOT_BOX_BOT + 4.0f) hintY = BOT_BOX_BOT + 4.0f;
            uirender_draw_wrapped(ui, hint, 0, &st, 10.0f, hintY, hintW,
                                  frame);
        }
        // Where it was when the texture's middle was centred, at x 242.
        drawBotLogo(ui, BOT_W - 70.0f, BOT_H - 21.0f, 0.5f, frame);
    }

    // The biggest size the line fits at, centred as a block in the panel.
    for (size_t i = 0; i < sizeof kPx / sizeof kPx[0]; i++) {
        st = botFontStyle(ui, BOT_FONT_ITAL, text, kPx[i], true);
        st.lineGap = 1.0f;
        h = uirender_wrap_height(ui, body, 0, &st, boxW);
        if (h <= bot - top) break;
    }
    uirender_draw_wrapped(ui, body, 0, &st, BOT_PAD,
                          h < bot - top ? top + (bot - top - h) * 0.5f : top,
                          boxW, alpha);
}

// The viewers' panel: `title` on the plate, `body` in the popup, `hint`
// under it.
static void drawBotPanel(UIRenderer* ui, const char* title, const char* body,
                         float alpha, const char* hint)
{
    drawBotDialog(ui, title, body, alpha, 1.0f, hint);
}

// Over a wireless race held for a lost console (37g), a box across the top
// screen: whose link was lost and the time left. Past the hold, for a few
// seconds, whose car the CPU drives now. For a console back after a
// restart (37g-3), loading or catching up, that it is coming back and how
// far; on that console, how far it has caught up. The port's own, in the
// panel's colours: retail had no link to lose.
#define HELD_BOX_X   24.0f
#define HELD_BOX_PAD 10.0f
#define HELD_BACK    RGBA8(0x0b, 0x0d, 0x12, 0xe0)

static void drawLockHeld(UIRenderer* ui)
{
    char        text[320];
    uint32_t    now = (uint32_t)osGetTime(), left, behind = netstep_behind();
    uint8_t     pct, back = netstep_rejoining(&pct);
    uint8_t     held = netstep_held(now, &left) & (uint8_t)~back;
    UIWrapStyle st;
    float       boxW = 400.0f - HELD_BOX_X * 2.0f, textW, h, y;

    text[0] = 0;
    if (lockCatchingUp()) {
        uint32_t ran = netstep_frame();

        netrace_catch_up_text(&g_flow, ran + behind
                              ? (int)((uint64_t)ran * 100u / (ran + behind))
                              : 0, text, sizeof text);
    } else {
        if (held) netrace_held_text(&g_flow, held, left, text, sizeof text);
        if (back) netrace_back_text(&g_flow, back, pct, text, sizeof text);
        if (!held && !back && g_lockNote && now - g_lockNoteAt < LOCK_NOTE_MS)
            netrace_cpu_text(&g_flow, g_lockNote, text, sizeof text);
    }
    if (!text[0]) return;
    // '@' breaks a line in retail's text; the wrap breaks at a newline.
    for (char* c = text; *c; c++)
        if (*c == '@') *c = '\n';
    st = botStyle(ui, BOT_TEXT, 16.0f, true);
    st.lineGap = 3.0f;
    textW = boxW - HELD_BOX_PAD * 2.0f;
    h = uirender_wrap_height(ui, text, 0, &st, textW);
    if (h <= 0.0f) return;
    y = (240.0f - h) * 0.5f - HELD_BOX_PAD;
    C2D_DrawRectSolid(HELD_BOX_X, y, 0.0f, boxW, h + HELD_BOX_PAD * 2.0f,
                      HELD_BACK);
    C2D_DrawRectSolid(HELD_BOX_X, y, 0.0f, boxW, 2.0f, BOT_ACCENT);
    uirender_draw_wrapped(ui, text, 0, &st, HELD_BOX_X + HELD_BOX_PAD,
                          y + HELD_BOX_PAD, textW, 1.0f);
}

// A console catching up (37g-3), a few times a second: its progress over
// a black top screen, the race's past not worth the drawing.
static void lockCatchUpDraw(UIRenderer* ui)
{
    uint32_t now = (uint32_t)osGetTime();

    if (now - g_lockCatchDrawAt < LOCK_CATCH_DRAW_MS) return;
    g_lockCatchDrawAt = now;
    C3D_FrameBegin(0);
    C2D_Prepare();
    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
    C2D_TargetClear(g_top, C2D_Color32(0, 0, 0, 0xFF));
    C2D_SceneBegin(g_top);
    drawLockHeld(ui);
    C2D_Flush();
    C2D_TargetClear(g_bot, BOT_BACK);
    C2D_SceneBegin(g_bot);
    drawBotLogo(ui, BOT_W * 0.5f, BOT_H * 0.5f, 1.0f, 1.0f);
    C3D_FrameEnd(0);
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
    C2D_SceneBegin(g_bot);
    drawBotLogo(b->ui, BOT_W * 0.5f, BOT_H * 0.5f, 1.0f, 1.0f);
    C3D_FrameEnd(0);
}

// ~bTList<AcidEmitter> deletes each emitter it takes off a car's effect
// list with AcidEmitter's deleting destructor, 3.
static void acidEmitterDelete(bNode* emitter, int32_t flags)
{
    acid_emitter_delete((AcidEmitter*)emitter, flags);
}

// Collision::AddImpulse fires the ground's impacts and scrapes on
// pTerrainEffectEmitters with no test; the port skips them while there is
// no World to have made it.
static void terrainEffectTrigger(void* emitters, int32_t effect,
                                 int32_t terrain, float scale,
                                 const bVector3* at,
                                 const bVector3* velocity)
{
    if (emitters != NULL)
        terrain_effect_emitters_trigger((TerrainEffectEmitters*)emitters,
                                        effect, terrain, scale, at, velocity);
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

// FlyByCameraCoordinator::Update's `new TrackFlyCameraMover` and its
// IsFinished, on the mover's base.
static CameraMover* track_fly_mover_new(void* mem, int32_t viewID,
                                        CameraDataItems* cd, struct Car* car)
{
    return &track_fly_camera_mover_init((TrackFlyCameraMover*)mem, viewID,
                                        cd, car)->base;
}

static int32_t track_fly_mover_is_finished(CameraMover* m)
{
    return track_fly_camera_mover_is_finished((const TrackFlyCameraMover*)m);
}

// DemoCameraCoordinator::Update's `new TrackCarCameraMover` and `new
// DriveCameraMover`, in retail's 1136 and 1008 bytes.
typedef char demo_camera_mover_size_check[
    (sizeof(TrackCarCameraMover) <= 1136
     && sizeof(DriveCameraMover) <= 1008) ? 1 : -1];

static CameraMover* track_car_mover_new(void* mem, int32_t viewID,
                                        struct Car* car,
                                        const CameraDataItems* cd,
                                        const CameraShake* shake,
                                        int32_t focusEffects)
{
    return &track_car_camera_mover_init((TrackCarCameraMover*)mem, viewID,
                                        car, cd, shake, focusEffects)->base;
}

static CameraMover* drive_mover_new(void* mem, int32_t viewID,
                                    struct Car* car, int32_t pov,
                                    float lookbackSpeed, int32_t disableLag,
                                    int32_t lookBack, int32_t perfectFocus)
{
    drive_cam_init((DriveCameraMover*)mem, viewID, car, pov, lookbackSpeed,
                   disableLag, lookBack, perfectFocus);
    return &((DriveCameraMover*)mem)->base;
}

// ChangeToScreen (0x0014cc78) for the race's code: the flow's, which hides
// and unactivates the screen up, pushes it when asked, and activates the
// new one with its menu, which then has the pad.
//
// The port's guard: a screen with no kScreens row would be a change to
// nothing, with the race paused under it. The pause menu's Options, View
// Objective and View Cop Controls are such screens until they are ported,
// so for them the screen up stays, and the log says which was asked for.
static void flowChangeToScreen(const char* name, int32_t push)
{
    if (name != NULL && name[0] && bgf_find_screen(&g_flow, name) == NULL) {
        logLine("race: screen \"%s\" not ported, the screen up stays", name);
        return;
    }
    bgf_change_to_screen(&g_flow, name, push);
}

// The Starting Grid's two GetTranslatedStrings, into the car select's
// ring: the grid prints each car's name before it asks for the next.
static const char* startRaceTranslate(int32_t id)
{
    return hookCarSelTranslate(&g_boot, id);
}

static const char* startRaceTranslateString(const char* s)
{
    return hookCarSelTranslateString(&g_boot, s);
}

// ------------------------------------------------------- the pause menu
//
// pausemenu.c's seams. ThePauseMenu is the coordinator's, made on its
// bMalloc; the screen and its popups are the flow's.

static struct PauseMenu* pauseMenuNew(void* mem)
{
    return pause_menu_construct((PauseMenu*)mem);
}

// The race view's numbers for the pause's frames (capture.h): what the
// track drew this frame, beside its picture. `drawTick` is the draw's
// start, after C3D_FrameBegin.
static void notePauseFrame(uint32_t drawTick)
{
    const eView*   view = eGetView(EVIEW_ID_PLAYER1);
    PauseFrameNote n;
    int            k;

    memset(&n, 0, sizeof n);
    n.frame = eFrameCounter;
    n.world = WorldTimeSeconds;
    if (view->pCamera != NULL) {
        const CameraParams* c = &view->pCamera->CurrentKey;

        for (k = 0; k < 3; k++) {
            n.pos[k] = (&c->Position.x)[k];
            n.dir[k] = (&c->Direction.x)[k];
        }
    }
    n.zone     = CurrentZoneNumber;
    n.drawn    = g_track.drawn;
    n.infos    = g_track.drawInfos;
    n.sky      = g_track.skyDrawn;
    n.tris     = g_track.drawnTris;
    n.skipped  = g_track.cmdSkipped;
    n.sunQuads = g_track.sunQuads;
    n.sunAlpha = g_track.sunAlpha;
    n.sunSky   = g_track.sunSky;
    n.strips   = g_track.stripsDrawn;
    n.sprites  = g_track.spritesDrawn;
    n.cpuMs    = bGetTickerDifference(drawTick, bGetTicker());
    n.gpuMs    = C3D_GetDrawingTime();
    capture_pause_note(&n);
}

// RCSTATE_PAUSE's way in: the port that asked, and in a wireless race the
// lockstep frame, so the log says whose pause it is.
static void pauseEnter(struct PauseMenu* m, JoystickPort port)
{
    if (netstep_on())
        logLine("pause: port %d, frame %lu", (int)port,
                (unsigned long)netstep_frame());
    else
        logLine("pause: port %d", (int)port);
    pause_menu_enter_pause((PauseMenu*)m, port);
}

// GrayMenuItem (0x0016d198), in retail's argument order.
static void pauseGrayMenuItem(uint32_t item, int32_t mode, uint32_t screen)
{
    hookGrayMenuItem(&g_boot, screen, item, (BScrGrayMode)mode);
}

// SummonPopup on TheFlailerScreenList: the flow's. The popup's answer goes
// to the parent's callback, the Pause Menu's.
static void pauseSummonPopup(const BPopupConfig* cfg)
{
    if (bpopup_summon(&g_flow, cfg) < 0)
        logLine("pause: no popup free");
}

static const struct BScreenConfig* flowCurrentScreen(void)
{
    return g_flow.screen;
}

// The bloom draws with the flow's animation kit, on the flow's clock.
static BAnim* pauseMenuAnim(void)
{
    banim_set_clock(g_flow.anim, (int32_t)g_flow.realTimer,
                    g_flow.realElapsed);
    return g_flow.anim;
}

// ------------------------------------------------------- the end of the race
//
// endgame.c's seams, and the FED's two that TheRaceHasFinished asks.

// SetAutosaveCompletionCallback (0x00247d98): what comes after the save,
// once the Autosave screen is done -- or now, with none up. A wireless
// race leaves lockstep after this frame, the same one on every console:
// each saves its own player's progress on its own card, its own pad
// answering (TASKS 37f).
static void endGameAutosaveNow(void (*cb)(void))
{
    if (netstep_on()) g_lockEnd = true;
    bgf_set_autosave_completion_callback(&g_flow, cb);
}

static int32_t fedIsThereAnotherRace(void)
{
    return fred_is_there_another_race(&Fred);
}

static int32_t fedIsMultiTrack(void)
{
    return fred_is_multi_track(&Fred);
}

// ------------------------------------------------------- the race event
//
// RaceEvent.obj (raceevent.c) on TheRaceEvent, for the files that call it
// through seams. Until EventTree::SetRace (RE-6c) copies an event in,
// TheRaceEvent is zeroed and its state NULL, which reads as zeros.

static int32_t raceEventGetStatus(void)
{
    return raceevent_get_status(&TheRaceEvent);
}

static void raceEventResetState(void)
{
    raceevent_reset_state(&TheRaceEvent);
}

static int32_t raceEventGetRaceIndex(void)
{
    return raceevent_get_race_index(&TheRaceEvent);
}

static int32_t raceEventGetRaceCount(void)
{
    return raceevent_get_race_count(&TheRaceEvent);
}

static int32_t raceEventIsThereAnotherRace(void)
{
    return raceevent_is_there_another_race(&TheRaceEvent);
}

// StartRace's 0x00200598 on GetKoState: player `player`'s place on the
// grid. Retail reads a NULL state's bottom of memory; here it is 0.
static int32_t raceEventKoStartPosition(int32_t player)
{
    const uint8_t* s = raceevent_get_ko_state(&TheRaceEvent);

    return s != NULL ? ko_state_get_start_position(s, player) : 0;
}

// StartRace's UserRank (0x00200768) on GetTournamentState.
static int32_t raceEventTournamentUserRank(void)
{
    const uint8_t* s = raceevent_get_tournament_state(&TheRaceEvent);

    return s != NULL ? tournament_state_user_rank(s) : 0;
}

static int32_t raceEventDriverEliminated(int32_t number)
{
    return raceevent_driver_eliminated(&TheRaceEvent, number);
}

// SetupCarsForRace's GetRank (0x00200220) on the state itself, not
// GetKoState, by RacerIndexFromDriverNumber.
static int32_t raceEventEliminatedRank(int32_t number)
{
    const uint8_t* s = TheRaceEvent.pState;

    if (s == NULL)
        return 0;
    return ko_state_get_rank(
        s, raceevent_racer_index_from_driver_number(&TheRaceEvent, number));
}

// CalculateStartingPositions' 0x002022c0; its answer is dropped.
static void raceEventStartingPositions(void)
{
    raceevent_calc_starting_positions(&TheRaceEvent);
}

static void raceEventPostResults(void)
{
    raceevent_post_results(&TheRaceEvent);
}

// MaybeDiscardResults (0x00201a80) is the state saved into aSavedState.
static void raceEventSaveState(void)
{
    raceevent_save_state(&TheRaceEvent);
}

static void raceEventCycleResults(void)
{
    raceevent_cycle_results(&TheRaceEvent);
}

// The End Game Menu's 0x00200b30(ev, i, ev+8): reward `i` against the
// state before the race.
static int32_t raceEventRewardTest(int32_t i)
{
    return raceevent_reward_earned(&TheRaceEvent, i, TheRaceEvent.aOldState);
}

static int32_t raceEventStatusAdvanced(void)
{
    return raceevent_status_advanced(&TheRaceEvent);
}

static int32_t raceEventStatusFell(void)
{
    return raceevent_status_fell(&TheRaceEvent);
}

static void raceEventKeepState(void)
{
    raceevent_keep_state(&TheRaceEvent);
}

// ShouldSeeRewardScreen's count (0x001f7458): the events this race opened
// whose goals TheRaceEvent's state now passes (fredevent.c).
static int32_t raceEventNumOpened(void)
{
    return events_opened_num_passed(&TheEventsOpened, &TheRaceEvent);
}

// Restart Event's grid in a wireless race: netrace's build's again (the
// CPU racers in front by performance, then the two players, then the
// rest of the consoles in the order of their places) where retail's reset
// would sort the consoles in AI racers' places in among the CPU racers.
// The same on every console: each runs it on the same driver table.
static void netRaceGrid(void)
{
    RaceParameters* rp = &TheRaceParameters;
    int             humans = 0, cpu, i;

    for (int p = 0; p < WIRELESS_MAX_CONSOLES; p++)
        if (netrace_driver(p) >= 100) humans++;
    cpu = rp->NumAICars - humans;
    if (cpu < 0) cpu = 0;
    rp->PlayerStartPosition[0] = (int8_t)(cpu + 1);
    rp->PlayerStartPosition[1] = (int8_t)(cpu + 2);
    for (i = 0; i < rp->NumDriverInfo; i++) {
        DriverInfo* d = &rp->pDriverInfoTable[i];
        int         n = d->UniqueDriverNumber;

        if (n >= 0 && n < 2)
            d->StartingPosition = rp->PlayerStartPosition[n];
        else if (n >= 100 && n < 100 + humans)
            d->StartingPosition = (int8_t)(cpu + 3 + (n - 100));
        else
            d->StartingPosition = 0;
    }
    fred_calculate_starting_positions(&Fred);
    logLine("netrace: the event's grid again, %d CPU racers, %d players in "
            "AI places", cpu, humans);
}

static void raceEventRestart(void)
{
    raceevent_restart(&TheRaceEvent);
    if (netrace_active()) netRaceGrid();
}

// StartRace's EventTrack::SetRace (fredrace.c): the track of the event's
// race index, of TheRaceEvent's eight.
static void eventTrackSetRace(int32_t index, RaceParameters* rp)
{
    if (index >= 0 && index < 8)
        event_track_set_race(&TheRaceEvent.aTracks[index], rp);
}

// NumAvailableCars' first byte of reward `i` (TheRaceEvent+244), and
// 0x00200b30 on it with no state: the event's own.
static int32_t raceEventRewardType(int32_t i)
{
    return (uint32_t)i < 8u ? TheRaceEvent.aRewards[i].nType : 0;
}

static int32_t raceEventRewardEarned(int32_t i)
{
    return raceevent_reward_earned(&TheRaceEvent, i, NULL);
}

static int32_t raceEventUserWon(void)
{
    return raceevent_user_won(&TheRaceEvent);
}

static void raceEventRecordResults(Race* r, struct RacingCar* rc,
                                   int32_t position)
{
    raceevent_record_results(&TheRaceEvent, r, rc, position);
}

static const uint8_t* raceEventGetTournamentState(void)
{
    return raceevent_get_tournament_state(&TheRaceEvent);
}

// FrontendDatabase::SetupNextRace (0x00184270): RaceEvent::SetupNextRace
// when the game uses the race event. That puts the frontend's first
// player's settings in the race's; a wireless race's are the host's on
// every console (netrace.c's take), and stay as raced (37f-2).
static void fedSetupNextRace(void)
{
    cPlayerSettings keep = TheRaceParameters.PlayerSettings[0];

    if (!fred_use_the_race_event(&Fred)) return;
    raceevent_setup_next_race(&TheRaceEvent);
    if (netrace_active()) TheRaceParameters.PlayerSettings[0] = keep;
}

// RenderTextIntoGroup on the flow's screens: the reward screens' blurbs
// and car counts (endresults.c).
static void endRenderTextIntoGroup(uint32_t screen, uint32_t group,
                                   const char* str)
{
    bpopup_render_text_into_group(&g_flow, screen, group, str);
}

// The end of the race on Fred (fredend.c): what it keeps of the race, the
// points and the rewards earned, when the race is over, quit, restarted
// or left; the rows the post-race camera picks its player by.
static void fedTheRaceIsOver(Race* r)
{
    const TransientStats* ts = &Fred.TransientStatsTable;

    fred_the_race_is_over(&Fred, r);
    logLine("race over: %d rows, task reward %d, points reward %d, "
            "points %d", (int)ts->NumStats, (int)ts->TaskRewardEarned,
            (int)ts->PointsRewardEarned,
            (int)Fred.FrontendPlayers[0].AccumulatedPoints);
}

static void fedCheckForAbortion(void)
{
    fred_check_for_abortion(&Fred);
}

static void fedTheRaceWasQuit(void)
{
    fred_the_race_was_quit(&Fred);
}

static void fedTheRaceWasRestarted(void)
{
    fred_the_race_was_restarted(&Fred);
}

static void fedTheRaceIsLeaving(Race* r)
{
    (void)r;
    fred_the_race_is_leaving(&Fred);
}

// The challenge records (highscore.c): what TheRaceIsOver records for each
// player's car, logged, and the records to beat each player car's HUD
// shows from the start (rcstates.c).
static int32_t fedMaybeRecordHighScore(HighScoreTable* t, Race* r,
                                       struct RacingCar* rc)
{
    int32_t place = high_score_table_maybe_record_high_score(t, r, rc);
    const struct Player* p = racingcar_get_player(rc);

    logLine("high score: total place %d, lap record %s", (int)place,
            p != NULL && p->BestLapRecordData != NULL ? "set" : "none");
    return place;
}

static void fedSetRecordTimesToBeat(int32_t player)
{
    fred_set_record_times_to_beat(&Fred, player);
}

static const TransientStatsElement* fedTransientStatsGetDriver(int32_t n)
{
    return transient_stats_get_driver(&Fred.TransientStatsTable, n);
}

// SetAudioDataFromSound (0x001eef60), the jukebox's: the race's audio
// options back into Fred's.
static void fedAudioFromSound(uint8_t* ao, int32_t tunes)
{
    jb_audio_from_sound(&g_jukebox, ao, tunes,
                        sound_get_audio_mode(&gSoundModule));
}

// ChangeGameFlow (0x001680d8) for RCSTATE_NONE: Quit Race's unloading, and
// NEXT_RACE's.
static void raceChangeGameFlow(int32_t desired, int32_t pending)
{
    logLine("race: change game flow %d pending %d", (int)desired,
            (int)pending);
    bgf_change_state(&g_flow, desired, pending);
}

// sound::Mute (0x001af850): the pause's, and RESTART_RACE's unmute.
static void raceSoundMute(int32_t on)
{
    sound_mute(&gSoundModule, on);
    logLine("sound mute %d", (int)on);
}

// FlailerScreenList::JoyHandler and FlailerMenu's: this frame's presses on
// `port` to the popups, the screen up and its menu. Nonzero when one went
// anywhere. Port 0 is the console's; a wireless race's second player's
// come on port 1 (netstep.h).
static int flowInput(u32 kDown, int port)
{
    int redraw = 0;

    // ChangeToScreen (0x0016c4c0) adds the list's JoyHandler for its
    // sixteen events when a screen comes up out of none, and removes it
    // when the list is left with none (0x0016c5d4). So with no screen up --
    // a race, from Pre Race Stats going until the pause -- the popups, the
    // screen and its menu hear nothing, and BACK cannot pop the frontend's
    // stack under the race.
    u32 listDown = g_flow.screen ? kDown : 0;

    // A screen given a port (hookSetScreenFilterPort) hears no other's;
    // its menu filters the same.
    int32_t filter = screenFilterPort(g_boot.screenHash);
    bool    takes  = filter == -1 || filter == port;

    // The list's MENU_HELP first (0x0016cab0, 0x0016ca40), Y on the 3DS:
    // with no popup up, from a port the screen hears, a press summons the
    // HELP panel with the override's lines or the screen's, or sends it
    // away. While it is coming in or there, the popups, the screen and its
    // menu hear nothing.
    if ((listDown & KEY_Y) && !(g_boot.hasMenu && g_boot.menu.ignoreJoystick)
        && !bpopup_any_active(&g_flow) && takes) {
        helpmenu_toggle(&g_help,
                        helpmenu_lines(&g_help, helpmenu_screen_lines(
                                                    g_flow.screen->name)));
        redraw = 1;
    }
    if (helpmenu_is_active(&g_help)) {
        if (listDown) redraw = 1;
        listDown = 0;
    }

    // A popup that is up has each event before the screen and its menu,
    // and takes every one -- the memory card's messages ignore SELECT and
    // BACK, but the title underneath does not get them either.
    u32 flowDown = listDown;
    if (listDown && bpopup_any_active(&g_flow)) {
        static const struct { u32 key; BJoyEvent ev; } kPopupBinds[] = {
            { KEY_START, BJOY_START },
            { KEY_B,     BJOY_MENU_BACK },
        };
        for (int i = 0; i < NUM_BINDS; i++)
            if ((listDown & kBinds[i].key)
                && bpopup_joy(&g_flow, port, kBinds[i].ev, 1))
                flowDown &= ~kBinds[i].key;
        for (int i = 0; i < 2; i++)
            if ((listDown & kPopupBinds[i].key)
                && bpopup_joy(&g_flow, port, kPopupBinds[i].ev, 1))
                flowDown &= ~kPopupBinds[i].key;
        if (flowDown != listDown) redraw = 1;
    }
    // The port's debug menu (debugmenu.h): L, R and D-Pad Up held together
    // on the main menu, the last of them pressed this frame, show its item.
    // The menu is entered again to find it, on it. The three go no further.
    if (port == 0 && g_flow.screen
        && g_flow.screen->hash == BGF_SCREEN_NEW_MAIN_MENU
        && !bpopup_any_active(&g_flow)) {
        const u32 chord = KEY_L | KEY_R | KEY_DUP;
        if ((hidKeysHeld() & chord) == chord && (flowDown & chord)) {
            flowDown &= ~chord;
            if (debugmenu_reveal()) {
                logLine("debug menu shown");
                fesound_play(30, NULL);   // an Easter egg's
                bgf_change_to_screen(&g_flow, "New Main Menu", 0);
                if (g_boot.hasMenu)
                    bmenu_set_active_item(&g_boot.menu, BGF_ITEM_MENUITEM_5);
            }
            redraw = 1;
        }
    }
    // START goes through the menu, as FlailerMenu's JoyHandler takes it:
    // the screen has it as SCREEN_START_BUTTON first, and unless the screen
    // consumes it, the current item has it as a select. That second half
    // is how START leaves PRESS START and skips the NFS intro; the title
    // screen only swallows the click.
    if (flowDown & KEY_START) {
        if (g_boot.hasMenu) {
            bmenu_joy(&g_boot.menu, port, BJOY_START, true);
        } else if (takes) {
            bgf_screen_event(&g_flow, BMSG_SCREEN_START_BUTTON, 0);
        }
        redraw = 1;
    }
    // FlailerScreenList::JoyHandler's BACK: the screen hears
    // SCREEN_BACK_BUTTON first and may veto the pop. A START that left no
    // screen took the handler with it, and RemoveEvent cleared the frame's
    // queued BACK.
    if ((flowDown & KEY_B) && g_flow.screen && takes) {
        bgf_back_button(&g_flow, port);
        redraw = 1;
    }
    // JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION. The Mode Selects register a
    // handler for it and do nothing but remember whether it is down;
    // StartQuickRace reads that at the moment it runs. So it is a held
    // button, not a pressed one, and the state goes through every frame
    // rather than on an edge. Retail's is L1, as the Mode Selects' help
    // says ("L1 + Cross Manual Transmission in Quick Race"): L on the 3DS.
    // It is the Mode Selects' own handler, not the list's, so the HELP
    // panel does not stop it.
    if (port == 0)
        bscr_joy(&g_uiScreens, 0, BSCR_JOY_SELECT_TRANSMISSION,
                 (hidKeysHeld() & KEY_L) ? 1 : 0);

    if (g_boot.hasMenu) {
        for (int i = 0; i < NUM_BINDS; i++) {
            if (!(flowDown & kBinds[i].key)) continue;
            bmenu_joy(&g_boot.menu, port, kBinds[i].ev, true);
            redraw = 1;
        }
    }
    return redraw;
}

// The wreck and the repair, whose seams take the damage as void * (cop.h,
// copmgr.h).
static void car_damage_wreck_seam(void* damage)
{
    cardamage_wreck((CarDamage*)damage);
}

static void car_damage_repair_all_seam(void* damage)
{
    cardamage_repair_all((CarDamage*)damage);
}

// The walk changed a car's solid: both views' meshes of it are dirty.
static void solid_vertices_changed(const eSolid* s)
{
    trackview_solid_changed(&g_track, s);
    trackview_solid_changed(&g_feView, s);
}

// tAICop::ClearPursuit drops RemoveCopFromPursuit's answer.
static void pursuit_remove_cop_seam(tPursuit* p, tCop* c)
{
    tpursuit_remove_cop_from_pursuit(p, c);
}

// Car::PleaseResetMeLater tests IsBeingPursued's pursuit for nonzero.
static int32_t copmanager_is_being_pursued_seam(tCopManager* m, Car* c)
{
    return copmanager_is_being_pursued(m, c) != NULL;
}

// The roadblock's barrels are smokeables of "CS_RoadBlock_Barrel"'s info,
// found again for each delete (barricade.h).
static void barricade_delete_barrel_seam(int16_t id)
{
    smokeable_delete(id,
                     find_smokeable_info(bchunk_hash("CS_RoadBlock_Barrel")));
}

// A fading barrel blinks: the smokeable's byte at 1123.
static void barricade_mark_body_fading_seam(CollisionBody* body)
{
    smokeable_set_blinking((Smokeable*)(void*)body, 1);
}

// Retail's VClip restart: World::Random (0x0014e520) on pCurrentWorld,
// which a walk only reaches inside a world's step.
static int32_t vclipWorldRandom(int32_t range)
{
    return pCurrentWorld != NULL ? world_random_i(pCurrentWorld, range) : 0;
}

// `fmt` added at `used` in `line`, which stays terminated when it is full.
static int appendLine(char* line, size_t size, int used, const char* fmt, ...)
{
    va_list ap;
    int     n;

    if (used < 0 || (size_t)used >= size)
        return used;
    va_start(ap, fmt);
    n = vsnprintf(line + used, size - (size_t)used, fmt, ap);
    va_end(ap);
    if (n < 0)
        return used;
    return (size_t)(used + n) < size ? used + n : (int)size - 1;
}

// A car table slot as the race lines name it: player, AI racer, cop or
// traffic, and the slot.
static const char* carSlotKind(const World* w, int i)
{
    if (w == NULL)              return "car";
    if (i < w->AICarPos)        return "player";
    if (i < w->CopCarPos)       return "ai";
    if (i < w->TrafficCarPos)   return "cop";
    return "traffic";
}

static void clearWorldStep(void)
{
    memset(&WorldStepProfile, 0, sizeof WorldStepProfile);
    VClipCalls = 0;
    VClipSteps = 0;
    VClipRestarts = 0;
}

// With DebugLog 1, after each "frame:" line: the world steps since the last
// one, on average by part (world.h's WorldStepProf), the three cars whose
// think and drive took longest, the witnesses and contact rounds, and
// VClip's walks. Then the sums start again.
static void logWorldStep(void)
{
    static const char* const parts[WSP_PARTS] = {
        "cops", "think", "drive", "heli", "begin", "move", "witnesses",
        "tests", "resolve", "collisions", "finish", "events", "effects",
        "rest"
    };
    const WorldStepProf* p = &WorldStepProfile;
    const World* w = pCurrentWorld;
    char   line[1024];
    int    used = 0;
    int    top[3] = { -1, -1, -1 };
    double ms;
    double steps;
    int    i, k;

    if (p->steps != 0) {
        uint32_t total = 0;

        steps = (double)p->steps;
        ms = 1.0 / (294912.0 * steps);
        for (i = 0; i < WSP_PARTS; i++)
            total += p->ticks[i];
        used = appendLine(line, sizeof line, used,
                          "world: %.2f ms a step over %lu, worst %.2f;",
                          total * ms, (unsigned long)p->steps,
                          p->worst / 294912.0);
        for (i = 0; i < WSP_PARTS; i++)
            used = appendLine(line, sizeof line, used, " %s %.2f%s",
                              parts[i], p->ticks[i] * ms,
                              i + 1 < WSP_PARTS ? "," : ";");
        for (i = 0; i < WORLD_MAX_CARS; i++) {
            uint32_t t = p->think[i] + p->drive[i];

            for (k = 0; k < 3; k++) {
                if (top[k] < 0
                    || t > p->think[top[k]] + p->drive[top[k]]) {
                    int m;

                    for (m = 2; m > k; m--)
                        top[m] = top[m - 1];
                    top[k] = i;
                    break;
                }
            }
        }
        used = appendLine(line, sizeof line, used,
                          " slowest cars (think+drive)");
        for (k = 0; k < 3 && top[k] >= 0; k++)
            used = appendLine(line, sizeof line, used, " %s %d %.2f+%.2f",
                              carSlotKind(w, top[k]), top[k],
                              p->think[top[k]] * ms, p->drive[top[k]] * ms);
        used = appendLine(line, sizeof line, used,
                          "; %.1f witnesses, %.2f rounds (most %lu); "
                          "vclip %.1f calls, %.2f steps each, "
                          "%.2f restarts",
                          p->witnesses / steps, p->rounds / steps,
                          (unsigned long)p->roundsMax, VClipCalls / steps,
                          VClipCalls ? (double)VClipSteps / VClipCalls : 0.0,
                          VClipRestarts / steps);
        logLine("%s", line);
    }
    clearWorldStep();
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
    // The audio workers' tripwire, for "ThreadGuard 1" only (logOpen read
    // the config): off, its checks cost the game's core nothing.
    if (ConfigThreadGuard)
        threadguard_enable();
    threadguard_note = guardNote;
    // Where the draw's time goes, sampled from the third core, for
    // "CoreSample 1" only (coresample.h).
    if (ConfigCoreSample)
        coresample_start(logLine);
    // exit() frees the heap, and the stacks of the threads that made it
    // with it, before it ends the process: a watcher that woke in between
    // pushed onto unmapped memory, Luma's data abort on closing from HOME
    // or powering off (crash_dump_00000002 and 3, 2026-10-12). atexit runs
    // last first: the sampler, the guard, the watchdog, then the log's
    // writer above.
    atexit(hangwatch_stop);
    atexit(threadguard_stop);
    atexit(coresample_stop);

    // bMalloc's, before its first block (bmem.h): the pool's top from the
    // linear heap, the large blocks' names for the heap's map, and a
    // bMalloc that fails puts the map in stderr before its abort.
    gBMemTopAllocFn = bMallocTop;
    gBMemTopFreeFn  = bFreeTop;
    gBMemNoteFn     = heapmap_note;
    gBMemForgetFn   = heapmap_forget;
    gBMemFailFn     = bMallocFailed;

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
    smokeable_install_vtables();
    munition_install_vtables();
    carcollisionbody_install_vtable();
    aiaction_install_vtables();
    aiactions_install_vtables();
    copmgr_install_vtables();
    cop_install_vtables();
    pursuit_install_vtables();
    spikestrip_install_vtables();
    barricade_install_vtables();
    aicarcontroller_install_vtables();
    beltmover_install_vtables();
    copmover_install_vtables();
    copdriver_install_vtables();
    trackgraph_install_vtables();
    psychodriver_install_vtables();
    aidriver_install_vtables();
    trafficcar_install_vtables();
    trafficdriver_install_vtables();
    cameracoord_install_vtables();
    democam_install_vtables();
    sound3d_install_vtables();
    carsound_install_vtables();
    enginesound_install_vtables();
    tiresound_install_vtables();
    collisionsound_install_vtables();
    choppersound_install_vtables();
    soundscape_init();

    // The car sounds (14-3): Car's constructor and destructor, the splash
    // and the tyre pop, and the drivers' horn.
    gCreatePlayerCarSoundFn = carsound_create_player;
    gCreateAICarSoundFn = carsound_create_ai;
    gCreateAICopCarSoundFn = carsound_create_ai_cop;
    gBaseCarSoundDestroyFn = carsound_delete;
    gBaseCarSoundTriggerSplashFn = basecarsound_trigger_splash;
    gBaseCarSoundTriggerTireBlowOutFn = basecarsound_trigger_tire_blow_out;
    gBaseCarSoundStartHonkHornFn = basecarsound_start_honk_horn;
    gBaseCarSoundStopHonkHornFn = basecarsound_stop_honk_horn;
    gBaseCarSoundIsHonkingFn = basecarsound_is_honking;
    // RealDriver's Player calls (TASKS 73): until these, the reset button
    // did nothing and an automatic box's shift buttons went nowhere.
    // Retail's NitroAvailable asks about the NIS, and its horn ends in
    // Easter egg 5's chopper attack.
    gPlayerRerouteJoyEventFn = player_reroute_joy_event;
    gPlayerIsAllowedToResetFn = player_is_allowed_to_reset;
    gPlayerSelectedResetFn = player_selected_reset;
    gPlayerIsNisPlayingFn = player_is_nis_playing;
    gChopperHonkAttackFn = chopper_honk_attack;
    // Retail's VClip restarts a walk from vertices World::Random draws on
    // pCurrentWorld (TASKS 73).
    gVClipWorldRandomFn = vclipWorldRandom;
    // Their engines (14-4), which BaseCarSound's constructors make.
    gCreatePlayerEngineFn = enginesound_create_player;
    gCreateAIEngineFn = enginesound_create_ai;
    // And their tyres (14-5).
    gCreatePlayerTireFn = tiresound_create_player;
    gCreateAITireFn = tiresound_create_ai;
    gTireSoundTriggerBlowOutFn = tiresound_trigger_blow_out;
    gTireSoundScaleRoadNoiseFn = tiresound_scale_road_noise;
    // The crashes and scrapes (14-6): a collision's sample, its release
    // and its scrape, the race's reset, and the busted roadblock.
    gCollisionSoundCreateSampleFn = collision_sound_create_sample;
    gCollisionSoundReleaseSampleFn = collision_sound_release_sample;
    gCollisionSoundPlayScrapeFn = collision_sound_play_scrape;
    gCollisionSoundResetFn = collision_sound_reset;
    gCollisionSoundPlayBustRoadBlockFn = collision_sound_play_bust_road_block;
    // The chopper's rotor (14-7), which Chopper's constructor makes.
    gCreateChopperSoundFn = choppersound_create;

    // Car::SetControlMode reaches the controllers task 26 brings through
    // seams; a NULL one is a class not ported yet, and the arm aborts.
    gRealControllerCtorFn = realcontroller_construct;
    gAIDriverCtorFn = aidriver_construct;
    gTrafficDriverCtorFn = trafficdriver_construct;

    // BELT_MOVEMENT's mover, its SetBelt for AICarController::Think and
    // its slope for CalculateMaxAcceleration (11e-6).
    beltmover_install_seams();

    // TRAFFIC_MOVEMENT's mover (11h-1).
    trafficcar_install_seams();

    // COP_MOVEMENT's mover (12c), which a cop car rides away from the
    // players, and the CopDriver that steers it (12d).
    copmover_install_seams();
    copdriver_install_seams();

    // The camera coordinators (11g-2c-1): BeginCountdownCameras builds a
    // CountdownCameraCoordinator, and Player's and the race coordinator's
    // deletes, enables and disables go through the coordinators' own.
    // The countdown finds no COUNTDOWN_n camera on the retail disc, so it
    // builds no BumperCameraMover and the car's drive camera shows the
    // 3-2-1, as retail's does.
    gCountdownCameraCoordinatorFn = countdown_camera_coordinator_construct;
    gCameraCoordinatorDeleteFn = camera_coordinator_delete;
    gCameraCoordinatorEnableFn = camera_coordinator_enable;
    gCameraCoordinatorDisableFn = camera_coordinator_disable;
    // The fly-by coordinator's TrackFlyCameraMover (11g-2c-2a), and the
    // coordinator itself (11g-2c-2b): CAMERA_FLYBY builds it on view 1
    // and waits on it, which with the track's fly-bys loaded is until the
    // Starting Grid's select posts RC_SKIP.
    gTrackFlyCameraMoverFn = track_fly_mover_new;
    gTrackFlyCameraMoverIsFinishedFn = track_fly_mover_is_finished;
    gFlyByCameraCoordinatorCtorFn = flyby_camera_coordinator_construct;
    gFlyByCameraIsFinishedFn = flyby_camera_coordinator_is_finished;
    // The pre-race coordinator (11g-2c-2c): PRERACE builds it on view 1
    // once the grid is gone and waits on it, flying INGAMEB's four
    // pre-race cameras round the cars it picked, each on a
    // BumperCameraMover (11g-2c-2c-2) until both its splines run out. The
    // countdown's COUNTDOWN_n cameras would use the same mover. No car has
    // an AnimatedDriver yet, so the animation seam stays NULL.
    gPreRaceCameraCoordinatorCtorFn = prerace_camera_coordinator_construct;
    gPreRaceCameraIsFinishedFn = prerace_camera_coordinator_is_finished;
    gBumperCameraMoverFn = bumper_camera_mover_construct;
    gBumperCameraMoverIsFinishedFn = bumper_camera_mover_is_finished_fn;
    // The demo coordinator (RE-4): the race-over states and a finished
    // player's camera show the car through the track's highlight cameras
    // where one holds it, on TrackCar, Bumper or TrackFly movers, and on
    // a DriveCameraMover at a random POV between them.
    gDemoCameraCoordinatorCtorFn = demo_camera_coordinator_construct;
    gPlayerBeginDemoCamerasFn = player_begin_demo_cameras;
    gTrackCarCameraMoverFn = track_car_mover_new;
    gDriveCameraMoverFn = drive_mover_new;
    // The rear-view mirror: SetHudFeatures puts its mover on view 3
    // while the HUD has HUD_REAR_VIEW_MIRROR, which turns target 7 on;
    // trackview_draw_mirror draws the view into it.
    gPlayerSetRearViewMirrorCameraMoverFn =
        player_set_rear_view_mirror_camera_mover;
    // The screens over the fly-by (11g-2c-2b, startrace.c): CAMERA_FLYBY's
    // ACTIVATE and UNACTIVATE put them up and take them down through the
    // flow's ChangeToScreen, which the pause's "Pause Menu" also goes
    // through.
    gEnableStartRaceScreensFn = enable_start_race_screens;
    gDisableStartRaceScreensFn = disable_start_race_screens;
    gChangeToScreenFn = flowChangeToScreen;
    gStartRaceTranslateFn = startRaceTranslate;
    gStartRaceTranslateStringFn = startRaceTranslateString;

    // The pause menu (pausemenu.c): the coordinator makes ThePauseMenu,
    // RCSTATE_PAUSE enters and leaves it, and mutes the music under it.
    // One pad, no rumble and no instant replay: the filter, the force and
    // the snapshot count stay NULL. RESTART_RACE and QUIT_RACE go through
    // RCSTATE_NONE, QUIT_RACE on to the unloading.
    gPauseMenuCtorFn = pauseMenuNew;
    gPauseMenuDestroyFn = pause_menu_destroy;
    gPauseMenuEnterPauseFn = pauseEnter;
    gSetScreenFilterPortFn = hookSetScreenFilterPort;
    gPauseMenuExitPauseFn = pause_menu_exit_pause;
    gGrayMenuItemFn = pauseGrayMenuItem;
    gSummonPopupFn = pauseSummonPopup;
    gFlailerCurrentScreenFn = flowCurrentScreen;
    gPauseTranslateFn = startRaceTranslate;
    gPauseMenuAnimFn = pauseMenuAnim;
    // Display's HUD row and the HUD hotkey (Player::CycleHud).
    gPlayerCycleHudFn = player_cycle_hud;
    // The end of the race (endgame.c): TheRaceHasFinished makes the
    // screens' list, POSTRACE puts them up and takes them down, and the
    // End Game Menu's popups and bloom are the pause menu's. Its OK posts
    // RESTART_RACE, NEXT_RACE or QUIT_RACE to POSTRACE, which goes on
    // through RCSTATE_NONE. The race event's calls are bound below; the
    // events the race opened (0x001f7458) stay NULL until RE-6c.
    gEndGameScreensCtorFn = endgame_screens_construct;
    gEndGameScreensDestroyFn = endgame_screens_destroy;
    gEndGameScreensResumeFn = endgame_screens_resume;
    gEndGameScreensSuspendFn = endgame_screens_suspend;
    gEndGameTranslateFn = startRaceTranslate;
    gEndGameMenuAnimFn = pauseMenuAnim;
    gSetAutosaveCompletionCallbackFn = endGameAutosaveNow;
    // Quit and Next Race always end at the Autosave screen, which asks
    // before it makes or overwrites the save (g_flow.saveAskCreate).
    gEndGameAlwaysAskToSave = 1;
    gFEDIsThereAnotherRaceFn = fedIsThereAnotherRace;
    gFEDIsMultiTrackFn = fedIsMultiTrack;
    // The results (endresults.c): Race Results, Points Rewards and Task
    // Rewards. The race event's rewards are bound below.
    gEndGameScreenCtorFns[END_GAME_CLASS_RACE_RESULTS] =
        race_results_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_POINTS_REWARDS] =
        points_rewards_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_TASK_REWARDS] =
        task_rewards_construct;
    gRenderTextIntoGroupFn = endRenderTextIntoGroup;
    // The records (endtimes.c, highscore.c): Best Lap Times, Best Total
    // Times, what the race records and the records to beat. The record
    // speeches stay NULL until 14-10c.
    gEndGameScreenCtorFns[END_GAME_CLASS_BEST_LAP_TIMES] =
        best_lap_times_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_BEST_TOTAL_TIMES] =
        best_total_times_construct;
    // The career's screens (endevent.c, RE-6d): Tourney Standings, the
    // event's Reward menu, Events Unlocked and the two You're The Cop
    // results.
    gEndGameScreenCtorFns[END_GAME_CLASS_TOURNEY_STANDINGS] =
        tourney_standings_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_REWARD_MENU] =
        event_reward_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_EVENTS_UNLOCKED] =
        events_unlocked_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_BTC_RESULTS_1P] =
        btc_results_1p_construct;
    gEndGameScreenCtorFns[END_GAME_CLASS_BTC_RESULTS_2P] =
        btc_results_2p_construct;
    gHighScoreMaybeRecordFn = fedMaybeRecordHighScore;
    gFEDSetRecordTimesToBeatFn = fedSetRecordTimesToBeat;
    // Fred's end of the race (fredend.c): TransientStats, the points, the
    // task and points rewards the End Game screens read, and which cars
    // they unlock, the event trees' cars among them (eventtree.c). The high
    // scores are bound above.
    gFEDCheckForAbortionFn = fedCheckForAbortion;
    gFEDTheRaceIsOverFn = fedTheRaceIsOver;
    gFEDTheRaceWasQuitFn = fedTheRaceWasQuit;
    gFEDTheRaceWasRestartedFn = fedTheRaceWasRestarted;
    gRaceIsLeavingFn = fedTheRaceIsLeaving;
    gTransientStatsGetDriverFn = fedTransientStatsGetDriver;
    gSetAudioDataFromSoundFn = fedAudioFromSound;
    gIsCarUnlockedFn = nfs_is_car_unlocked;
    gIsCarAnEventRewardFn = is_car_an_event_reward;
    gEventTreeIsCarUnlockedFn = event_tree_is_car_unlocked_any;
    // The race event (raceevent.c, RE-6b) on TheRaceEvent: StartRace's and
    // SetupCarsForRace's reads, each finish recorded, the results posted,
    // saved and cycled, the End Game Menu's tests, the rewards, the grid's
    // race count and points, and NEXT_RACE's SetupNextRace. EventTrack's
    // SetRace (eventrace.c, RE-6c) puts the event's track for the race
    // into the race parameters. FrontendDatabase's event calls (fredevent.c,
    // RE-6c-2): the challenge knockout's fake event, the tree's event word
    // and opponents, the multi-track event's car, and the events opened.
    gRaceEventGetStatusFn = raceEventGetStatus;
    gRaceEventResetStateFn = raceEventResetState;
    gRaceEventGetRaceIndexFn = raceEventGetRaceIndex;
    gRaceEventGetRaceCountFn = raceEventGetRaceCount;
    gRaceEventIsThereAnotherRaceFn = raceEventIsThereAnotherRace;
    gRaceEventKoStartPositionFn = raceEventKoStartPosition;
    gRaceEventTournamentUserRankFn = raceEventTournamentUserRank;
    gRaceEventDriverEliminatedFn = raceEventDriverEliminated;
    gRaceEventEliminatedRankFn = raceEventEliminatedRank;
    gRaceEventStartingPositionsFn = raceEventStartingPositions;
    gRaceEventRecordResultsFn = raceEventRecordResults;
    gRaceEventPostResultsFn = raceEventPostResults;
    gRaceEventMaybeDiscardResultsFn = raceEventSaveState;
    gRaceEventCycleResultsFn = raceEventCycleResults;
    gRaceEventRewardTestFn = raceEventRewardTest;
    gRaceEventStatusAdvancedFn = raceEventStatusAdvanced;
    gRaceEventStatusFellFn = raceEventStatusFell;
    gRaceEventKeepStateFn = raceEventKeepState;
    gRaceEventNumOpenedFn = raceEventNumOpened;
    gRaceEventRestartFn = raceEventRestart;
    gRaceEventRewardTypeFn = raceEventRewardType;
    gRaceEventRewardEarnedFn = raceEventRewardEarned;
    gRaceEventUserWonFn = raceEventUserWon;
    gRaceEventGetTournamentStateFn = raceEventGetTournamentState;
    gFEDSetupNextRaceFn = fedSetupNextRace;
    gEventTrackSetRaceFn = eventTrackSetRace;
    gEventTrackSetRaceOnFn = event_track_set_race;
    gSetupFakeRaceEventForChallengeKnockoutFn =
        fred_setup_fake_race_event_for_challenge_knockout;
    gFredEventWordFn = fred_event_word;
    gFredEventOpponentFn = fred_event_opponent;
    gFredMaybeSetSelectedCarForMultiTrackEventFn =
        fred_maybe_set_selected_car_for_multi_track_event;
    // EventTree::SetRace's reward name and description.
    gEventRaceTranslateFn = eventRaceTranslate;
    gEventRaceTranslateStringFn = startRaceTranslateString;
    // StartRace's RaceParameters New784 (fredrace.c): the trees' reward
    // cars earned, 0x001ff978.
    gEventRewardCarsUnlockedFn = event_trees_num_cars_unlocked;
    gChangeGameFlowFn = raceChangeGameFlow;
    gSoundMuteFn = raceSoundMute;
    gSoundMuteReplayFn = sndMuteReplay;
    // ReplayScreen (72g-2): its radial blur is radialblur.c's, on view 1;
    // the disc test answers 1.
    gReplayScreenRadialBlurFn = radialblur_replay;
    gReplayScreenPlaySampleFn = replayPlaySample;
    gReplayScreenFrontendSoundFn = replayFrontendSound;
    gReplayScreenHelpActiveFn = replayHelpActive;
    gReplayScreenToggleHelpFn = replayToggleHelp;
    // TheDemoModeReplay (dmreplay.c, TASKS 72h-2a): its static
    // constructor; slot 29's chunks; the manager's BeginFrame; the replay
    // screen's demo keys; and, while a demo is active, the track's loading
    // and unloading and StartRace. Save writes through the PS2's host link
    // and stays unbound, as does bRefreshTweaker.
    dmreplay_construct();
    gDemoModeReplayLoaderFn = dmreplay_loader;
    gDemoModeReplayUnloaderFn = dmreplay_unloader;
    gDemoModeReplayServiceFn = dmreplay_service;
    gDemoModeReplayCanTestFn = dmreplay_can_test_demo_mode;
    gDemoModeReplayBeginTestFn = dmreplay_begin_demo_mode_test;
    gDemoModeReplayTestGoesOnFn = dmreplay_test_goes_on;
    gDemoModeReplayServiceDemoModeFn = dmreplay_service_demo_mode;
    gDemoModeReplayEndDemoModeFn = dmreplay_end_demo_mode;
    gDemoModeReplayBeginRecordingFn = dmreplay_begin_recording_snapshot;
    gDemoModeReplayEndRecordingFn = dmreplay_end_recording_snapshot;
    gDemoModeReplayLoadFn = dmreplay_load_resource_file;
    gDemoModeReplayUnloadFn = dmreplay_unload_resource_file;
    gDemoModeReplayStartRaceFn = demoModeReplayStartRace;
    // Attract mode's race (demomode.c) and its two states (rcdemo.c, which
    // gRCStateCallbacks names).
    gDemoModeStartRaceFn = demoModeStartRace;
    // The bSamples the race's modules make and play, on gSound.
    gGetInGameSampleFn        = sndGetInGameSample;
    gSampleDeleteFn           = sndSampleDelete;
    gSoundGetCategoryVolumeFn = sndGetCategoryVolume;
    gNewSampleFn              = sndNewSample;
    gSampleInitializeFn       = sndSampleInitialize;
    gSampleSetCategoryFn      = sndSampleSetCategory;
    gCommonRegionSampleFn     = sndCommonRegionSample;
    gSampleIsPlayingFn        = sndSampleIsPlaying;
    gSamplePlayFn             = sndSamplePlay;
    gSampleSetAzimuthFn       = sndSampleSetAzimuth;
    gSampleSetPitchFn         = sndSampleSetPitch;
    gSampleSetVolumeFn        = sndSampleSetVolume;
    gTriggerFinishLineSoundFn = sndTriggerFinishLine;
    gSpeechClearEventQueueFn  = speechClearEventQueue;
    gSpeechFlushQueueFn        = speechFlushQueue;
    gCopSpeechFlushQueueFn     = speechFlushQueue;
    gCopSpeechAllocateVoicesFn = speechAllocateVoices;
    gCopSpeechPlaybackStateFn  = speechPlaybackState;
    gSelCamSound              = &kSelCamSound;

    // World::DoTimestep's Race::Update and SimulateRaceFinish's
    // Race::FinishCar (11g-2b): the countdown's end, the laps and the
    // finishes.
    gRaceUpdateFn = race_update;
    gRaceFinishCarFn = race_finish_car;

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
    gCollisionDoSnapshotFn = collision_do_snapshot;
    gCollisionDestroyFn    = collision_destroy;

    // World::DoTimestep ends every car's step with Car::FinishMovement,
    // which carfinish.c has ported since task 27's eleventh Car slice.
    // Left NULL, the step aborts. Only a player's car reaches its four
    // Player calls. CleanUpJumpCam is playerinit.c's since step 8a; the
    // jump cam is playerzone.c's: IsJumpCamAvailable's PreviewRoute ahead
    // of the car, RequestZone's zones 6 and 7 with their slow motion and
    // TrackCarCameraMovers, and ClearZone as the car lands. The freeze and
    // preview zones (1 and 2) have their movers below (TASKS 80a, 80b).
    gCarFinishMovementFn = car_finish_movement;
    // TASKS 73: Car::TriggerEvents for every car near a player, which
    // shakes the bushes it drives into (fernshaker.h), and the event queue
    // emptied at the end of the step. Car's constructor adds its handler,
    // Car::EventHandler, which is empty, and its destructor takes it off.
    gCarTriggerEventsFn = car_trigger_events;
    gEmProcessAllEventsFn = em_process_all_events;
    gEmAddHandlerFn = em_add_handler;
    gEmRemoveHandlerFn = em_remove_handler;
    gPlayerCleanUpJumpCamFn = player_clean_up_jump_cam;
    gPlayerIsJumpCamAvailableFn = player_is_jump_cam_available;
    gPlayerRequestZoneFn = player_request_zone;
    gPlayerClearZoneFn = player_clear_zone;
    gPlayerJumpCamMoverFn = player_jump_cam_mover;
    gPreviewRouteDeleteFn = preview_route_delete;
    // The radial blur (radialblur.c, TASKS 80d): the nitro's, the zones'
    // and the NIS's off. trackview.c draws it.
    gRadialBlurOnFn    = radialblur_on;
    gRadialBlurOffFn   = radialblur_off;
    gRadialBlurAlphaFn = radialblur_alpha;
    // The freeze zone's camera (zonecam.c, TASKS 80a).
    gZoneFreezeCameraMoverFn = zone_freeze_camera_mover_new;
    gZoneFreezeDurationFn = zone_freeze_camera_mover_duration;
    // The preview zone's (zonepreview.c, TASKS 80b): the route ahead, the
    // camera that runs out along it and back, its topology check and its
    // length. Its comet draws from render_camera_movers.
    gZonePreviewCameraMoverFn = zone_preview_camera_mover_new;
    gZonePreviewFindRouteFn = zone_preview_find_route;
    gZonePreviewViolatesTopologyFn = zone_preview_violates_topology_fn;
    gZonePreviewDurationFn = zone_preview_duration_fn;

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
    // The race-over overlay's message (raceovermsg.c), which SetHudFeatures
    // fills in when RACE_OVER comes on. The knockout speech waits for
    // 14-10c.
    gPlayerFillInRaceOverMessagesFn = player_fill_in_race_over_messages;
    gRaceOverTranslateFn = raceOverTranslate;
    gPlayerClearHudAnimationsFn = player_clear_hud_animations;
    gHudAnimatorDeleteFn = hudanim_delete;
    // The race's bonus scores (hudscore.c): UpdateHud runs UpdateScoring
    // each frame and starts the start bonus through StartScore(e, value).
    gUpdateScoringFn = player_update_scoring;
    gStartScoreFn = player_start_score_value;
    // The HUD's cop parts (hudcop.c): the radar detector, the trackers and
    // the pursuit meter, which UpdateHud calls when the HUD shows them. The
    // radar reads the cop manager's GetRadarDetectorIntensity (copmgr.c).
    gUpdateRadarDetectorFn = player_update_radar_detector;
    gCopManagerGetRadarDetectorIntensityFn =
        copmanager_get_radar_detector_intensity;
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

    // InitializeEverything's emEventManagerInit (retail 0x001ba078), after
    // InitQueuedFiles and before eMathInit: the event and handler pools.
    // LoaderTable slot 7 takes the track's event triggers (eventmgr.h).
    em_event_manager_init();

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
    // eInitSlotPools (0x0010a008) makes the eVertexAnimator pool (272
    // bytes, 16 slots, gp-25192) here too: LoaderSolidList takes one for
    // the first frame of every vertex-animated solid, and a race from the
    // frontend loads its track's before the track viewer starts.
    emodel_init_slot_pool();
    esolid_init_slot_pool();
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
    // TASKS 60: a car's bursts -- a broken part's glass, steam and smoke,
    // a blown tire, the ground under its wheels -- through
    // Car::TriggerEffect (cartriggereffect.h), and the ground's own
    // emitters for each terrain, made with the World and deleted with it,
    // which the wheels' and a collision's impacts and scrapes fire
    // (terraineffect.h).
    gCarTriggerEffectFn           = car_trigger_effect;
    gInitTerrainEffectEmittersFn  = init_terrain_effect_emitters;
    gCloseTerrainEffectEmittersFn = close_terrain_effect_emitters;
    gTerrainEffectTriggerFn       = terrainEffectTrigger;
    // TASKS 73: retail's BottomOut asks for a car that has lain on its
    // roof a second to be put back on the road.
    gPhysicsCarPleaseResetMeLaterFn = car_please_reset_me_later;

    // elInit, and eLight.obj's two calls the solids and the cars make
    // through seams: elGetLightMaterial, which eFixUpTables uses to fill
    // every solid's light materials, and elSetupLightContext, which the
    // car's and the world's draws make before each model.
    el_init();
    gElGetLightMaterialFn  = get_light_material_seam;
    gElSetupLightContextFn = setup_light_context_seam;

    // The flares' half: PostLoadFixup's eLightUpdateTextures finds the
    // three flare textures in GLOBALB, and CarRenderInfo::Render draws each
    // lit flare of a car through eRenderLightFlare.
    gELightUpdateTexturesFn = el_update_textures;
    gERenderLightFlareFn    = render_light_flare_seam;

    // Car's constructor builds the car's render info through
    // Car::InitRenderInfo, and its destructor deletes it -- carrenderinfo.c
    // since step 6, reached from step 8b's InitCars. The emitter positions
    // and the flares come out of two pools: retail makes the first in
    // InitCarEffects and the second in eInitSlotPools, and the port makes
    // both here.
    carrenderinfo_init_slot_pools();
    gCarInitRenderInfoFn    = car_init_render_info;
    gCarRenderInfoDestroyFn = carrenderinfo_delete;

    // CarDamage (task 51): a racer's damage built after its render info,
    // its items found on the model's markers, its body's models added by
    // InitRenderInfo, the hits from CarCollisionBody, the wreck the
    // munitions and the bust make, and the cop manager's repair.
    gCarDamageCtorFn           = cardamage_construct;
    gCarDamageFindItemPartsFn  = cardamage_find_item_parts;
    gCarDamageDestroyFn        = cardamage_destroy;
    gBodyDamageSetALevelInfoFn = bodydamage_set_alevel_info;
    gBodyDamageAddModelFn      = bodydamage_add_model;
    gCarDamageAddDamageFn      = cardamage_add_damage;
    gCarDamageWreckFn          = car_damage_wreck_seam;
    gCarDamageRepairAllFn      = car_damage_repair_all_seam;
    gESolidVerticesChangedFn   = solid_vertices_changed;

    // RenderCars' Car::DamageAbove (51d): every drawn car's fAngleToCamera,
    // which the cop HUD's trackers read, and in You're The Cop the marker
    // over each suspect. Left NULL, the angle stayed 0.
    gCarDamageAboveFn          = car_damage_above;

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
    // The type detection logs "joystick: port 0 type 121" once 32 reads
    // have agreed (retail's count). A new type makes the cars driven from
    // that port drop what they held, and the replay and the pause menu's
    // resume register the type monitor again so it does (retail's).
    joyhid_install();
    gJoypadRead = joypadRead;
    gJoyHidRaceLayoutFn = joyhidRaceLayout;
    gJoyResetPortDriversFn = realdriver_reset_port_joy_values;
    gRestoreTypeChangedHandlersFn = RestoreTypeChangedHandlers;
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

    // TASKS 37a's link soak between two consoles, in place of the game:
    // "WirelessTest 1" in the config hosts, "2" joins (wirelesstest.h).
    if (ConfigWirelessTest == 1 || ConfigWirelessTest == 2) {
        fatalConsole();
        wirelesstest_run((int)ConfigWirelessTest,
                         (int)ConfigWirelessTestSeconds,
                         (int)ConfigWirelessTestConsoles, logLine);
        waitForExit();
        gfxExit();
        return 0;
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

    // ndsp. Silence is a survivable failure -- a card with no SOUND
    // directory still runs the frontend -- so nothing below checks.
    bool soundUp = bsnd_hw_init(&gSnd);
    gAudioUp = soundUp;
    if (!gamedata_path("SOUND", gSoundDir, sizeof(gSoundDir)))
        gSoundDir[0] = '\0';
    // Sound.obj's statics, bSound's constructor and sound::jukebox's: with
    // no ndsp there is no driver, bSound's status stays 0 and the jukebox
    // has no host -- LoadCartridge does nothing and every Start finds no
    // cartridge.
    sound_init(&gSoundModule, &gSound, soundUp ? &gSnd : NULL, &g_jukebox,
               Fred.AudioOptionsScreenData, &gSoundHooks);
    bsound_init(&gSound, NULL, NULL, NULL);
    jb_sound_init(&g_jukebox,
                  soundUp ? jbstream_host(gSound.categoryVolume,
                                          jukeboxAssert)
                          : &kNoJukeboxHost,
                  &kJukeboxWorld);
    g_jukebox.randomRaceOpener = 1;     // jukebox.md, "The race's music"
    g_jukebox.quietSkip = 1;
    // InitializeEverything's (0x0012ee98): InitializeSoundDriver
    // (0x001ae608) -- bSound up, "common" in, the EA TRAX cartridge, each
    // category's shipped volume -- and InitFlailerMenuSystem's
    // InitGlobalMenuSound (0x0016ded8), the menus' own noises.
    sound_initialize_driver(&gSoundModule);
    fesound_init_global();
    if (soundUp) {
        logPrintf("Sound: %u patches in %u voices, common %s\n",
                  (unsigned)gSnd.patchCount, gSnd.voices,
                  gSoundModule.commonLoaded ? "in" : "missing");
    } else {
        logPrintf("Sound: ndsp unavailable, running silent\n");
    }
    logPrintf("Jukebox: %s, %u tunes\n",
              jb_is_cartridge_loaded(&g_jukebox.jukebox) ? "loaded" : "none",
              (unsigned)g_jukebox.jukebox.numTunes);

    // Four times citro3d's default. A track frame is a draw per object the
    // cull keeps, each with its own matrices, and the default's 256 KB is
    // about 500 of them; GPUCMD_Add drops what does not fit without a word.
    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE * 4);
    c3d_lean_log(logLine);
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
    hangwatch_gpu_top(top->frameBuf.colorBuf, top->frameBuf.depthBuf);
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
    hooks.closeMenu        = hookCloseMenu;
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
    hooks.setLanguageId    = hookSetLanguageId;
    hooks.raceDefaults     = hookRaceDefaults;
    hooks.frontendDefaults = hookFrontendDefaults;
    hooks.challengeCars    = hookChallengeCars;
    // The title screen's Start once its movies are done, NewMainMenu's
    // constructor's, and UnlaunchFrontendMenus' Stop.
    hooks.jukebox          = hookJukebox;
    hooks.songMonitor      = hookSongMonitor;
    hooks.songMonitorReset = hookSongMonitorReset;
    hooks.gameType         = hookGameType;
    hooks.raceDemo         = hookRaceDemo;
    hooks.raceReturn       = hookRaceReturn;
    hooks.easterEggs       = hookEasterEggs;
    hooks.initSelectCar    = hookCarSelInit;
    hooks.closeSelectCar   = hookCarSelClose;
    hooks.fixUpTables      = hookFixUpTables;
    hooks.initFrontendSounds   = hookInitFrontendSounds;
    hooks.unInitFrontendSounds = hookUnInitFrontendSounds;
    hooks.unloadSoundRegions   = hookUnloadSoundRegions;
    hooks.setPolice        = hookSetPolice;
    hooks.unloadFrontEnd   = hookUnloadFrontEnd;
    hooks.moveBrackets     = hookMoveBrackets;   // NewMainMenu's highlight
    hooks.setBlurb         = hookSetBlurb;
    hooks.setBlurbText     = hookSetBlurbText;
    hooks.trace            = hookTrace;
    // Attract mode, from the title and the main menu (TASKS 72h-2b).
    hooks.replayConsiderLaunching = hookReplayConsiderLaunching;
    hooks.replayLaunch     = hookReplayLaunch;
    hooks.startDemoMode    = hookStartDemoMode;

    bgf_init(&g_flow, kGameFlowStages, BGF_NUM_STATES,
             kScreens, NUM_SCREENS, kBootStages, NUM_BOOT_STAGES, &hooks);
    // FlailerScreenList's constructor makes its song monitor (0x0016c25c).
    bsm_init(&g_songMonitor, &kSongMonitorHooks);
    g_flow.fred = fred_bytes();
    // The Autosave screen asks before it makes the save file, as the end
    // of a race always goes through it.
    g_flow.saveAskCreate = 1;
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
    seedRandomNumber();
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
    g_ingameBundle = ingameBundle;
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
    // GameFlowLoadingTrackCommonPart2's copies of the solids a second car
    // of a type draws and dents, and the Begin of unloading's delete.
    gEDuplicateSolidFn             = eduplicate_solid;
    gEDeleteAllDuplicatedSolidsFn  = edelete_all_duplicated_solids;
    gSetFlailerScreenVisibilityFn = raceScreenVisibility;
    // The Flailer runtime (flailer.h) behind the race's object calls: the
    // Player's HUD lookups, the countdown's, and the NIS overlay's BUSTED.
    gFlailerTextScaledWidthFn   = flailerTextWidth;
    gFlailerTextScaledHeightFn  = flailerTextHeight;
    gFlailerBitmapTextureSizeFn = flailerTextureSize;
    gFlailerTextIntoRectangleFn = flailerTextIntoRectangle;
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
    // ReplayManager is retail's (replaymgr.c): the TICK at RACING marks its
    // beginning of time, TheRaceHasFinished its end. RealDriver's and the
    // chopper's fire register the race's interesting moments with it, and
    // World::VerifyDebugChecksums posts RC_SKIP_REPLAY when a replayed
    // frame comes out differently (ReplayCheck counts those).
    // InitAIPlans and CloseAIPlans: the AI actions' slot pool, made as a
    // track loads and deleted as it unloads.
    gInitAIPlansFn           = ai_init_ai_plans;
    gCloseAIPlansFn          = ai_close_ai_plans;
    gNewRaceCoordinatorFn    = racecoordinator_new;
    gDeleteRaceCoordinatorFn = racecoordinator_destroy;
    gRCCleanUpAutoReplayFn   = racecoordinator_clean_up_auto_replay;
    gReplayManagerCtorFn     = replaymgr_construct;
    gReplayManagerDestroyFn  = replaymgr_destroy;
    gReplayManagerGetData    = replaymgr_get_data;
    gReplayManagerAddData    = replaymgr_add_data;
    gReplayGetBeginningOfTimeFn       = replayGetBeginningOfTime;
    gReplayMarkTheBeginningOfTimeFn   = replaymgr_mark_the_beginning_of_time;
    gReplayMarkTheEndOfTimeFn         = replaymgr_mark_the_end_of_time;
    gReplayRegisterInterestingEventFn = ReplayManager_RegisterInterestingEvent;
    gReplayBeginRaceHighlightsFn      = replaymgr_begin_race_highlights;
    gReplayBeginNextRaceHighlightFn   = replaymgr_begin_next_race_highlight;
    gReplayMuteHighlightsFn           = replayMuteHighlights;
    gReplayEndCurrentHighlightTimeFn  = replayEndCurrentHighlightTime;
    gReplayNumInstantReplaySnapshotsFn = replayNumInstantReplaySnapshots;
    // The pause pages' changes, made and replayed (TASKS 72h-1).
    gReplayHandleSpecialEventFn       = replayHandleSpecialEvent;
    // A disc replay's cars carry retail's driver sections (car.h).
    gCarSnapshotRetailDrivers         = &DemoModeReplayActiveFlag;
    gRaceCoordinatorPostMessageFn = ConfigReplayCheck
                                        ? replayCheckPostMessage
                                        : racecoordinator_post_message;
    if (ConfigReplayCheck) gReplayChecksumBreakFn = replayCheckBreak;
    // The race's sound: the regions hook loads the race's banks and turns
    // the jukebox to the racing list as the track loads, the TICK starts
    // the music six seconds after GO, the cleanup stops it and the
    // unloading lets the banks go.
    gLoadSoundRegionsInGameFn = hookLoadSoundRegionsInGame;
    gUnLoadSoundRegionsFn     = soundUnloadRegions;
    gJukeboxDelayedStartFn    = raceJukeboxDelayedStart;
    gJukeboxDelayedStartTimer = &g_jukebox.delayedStart;
    gJukeboxStopFn            = raceJukeboxStop;
    gSound3dOneshotResetFn    = sound3d_oneshot_reset;
    // World's constructor makes its TrafficTeleporter, and its destructor
    // deletes it and any car left on CarList. AddTrafficCar places each
    // traffic car with it, and World's step moves them out of sight.
    gTrafficTeleporterCtorFn        = traffic_teleporter_construct;
    gTrafficTeleporterDestroyFn     = traffic_teleporter_destroy;
    gTrafficTeleporterPlaceNewCarFn = traffic_teleporter_place_new_car;
    gTrafficTeleporterDoTimestepFn  = traffic_teleporter_do_timestep;
    gCarDestroyFn                   = car_destruct;
    // World's constructor makes the cop manager when the race has cops,
    // and its destructor deletes it (copmgr.h).
    gInitCopsFn    = copmgr_init_cops;
    gCleanupCopsFn = copmgr_cleanup_cops;
    // And the racing routes' graph, which the cops search for roadblock
    // and radar-trap spots (trackgraph.h).
    gInitTrackGraphFn    = trackgraph_init;
    gCleanupTrackGraphFn = trackgraph_cleanup;
    // A collision tells it of hits on the cars it is watching.
    gCopManagerMonitorImpactFn = copmgr_car_impact;
    gCopManagerGetCopByCarFn   = copmanager_get_cop_by_car;
    // A chased racer in Be A Cop is not put back on the road (carrace.c).
    gCopManagerIsBeingPursuedFn = copmanager_is_being_pursued_seam;
    // A hard enough hit on an AI cop's car disables it (cop.h).
    gAICopDisableMyCarFn       = cop_disable_my_car;
    // A cop leaving its chase, and a wreck's speaker change (pursuit.h).
    gPursuitRemoveCopFromPursuitFn = pursuit_remove_cop_seam;
    gPursuitRemovePrimarySpeakerFn = tpursuit_remove_primary_speaker;
    // A cop asking to chase a car, and each chase's step in the manager's
    // Think, over once it returns nonzero, with its roadblocks (pursuit.h).
    gCopManagerRequestPursuitFn = copmanager_request_pursuit;
    // Be A Cop's player cop (12m-1): the horn picks the speeder to chase
    // or turns the chase to the next, and the cop's Think keeps the lights
    // and siren with it (playercop.h).
    gPlayerCopThinkFn = tplayercop_think;
    gCopManagerBeACopToggleSirenAndLightsFn =
        copmanager_be_a_cop_toggle_siren_and_lights;
    // Which way the player cop faces when reset (TASKS 74): at the
    // chased car, or along the route (copmgr.h).
    gCopManagerGetResetDirectionFn = copmanager_get_reset_direction;
    // And the manager's side (12m-2): the clock and its end, the
    // dispatch's call and the wrecked cars.
    gCopManagerBeACopThinkFn = copmanager_be_a_cop_think;
    gPursuitUpdateFn            = tpursuit_update;
    gPursuitCreateRoadBlockFn   = tpursuit_create_road_block;
    gRealDriverForceEBrakeStopFn = realdriver_force_ebrake_stop;
    gPursuitUpdateRoadBlocksFn  = tpursuit_update_road_blocks;
    // A cop out of limbo to a radar trap ahead of a racer (copmgr.h).
    gCopManagerSpawnSpeedTrapsFn = copmanager_spawn_speed_traps;
    // A roadblock's spike strip, laid along the road as world objects, and
    // the manager's watch over the strips: each car whose wheels cross one
    // has those tires blown (spikestrip.h). The track's load and unload
    // make and empty the world objects' pool (worldobject.h).
    gCopManagerAddSpikeStripFn     = copmanager_add_spike_strip;
    gCopManagerMonitorSpikeBeltsFn = copmanager_monitor_spike_belts;
    gSpikeStripBlinkBlinkPoofFn    = tspikestrip_blink_blink_poof;
    gInitWorldObjectsFn            = init_world_objects;
    gCloseWorldObjectsFn           = close_world_objects;
    // The fern shakers: a bush a car drives into is drawn as a world
    // object, and its leaves fly. The World makes and closes them, and a
    // replay's restore flushes them (fernshaker.h).
    gInitFernShakersFn             = init_fern_shakers;
    gCloseFernShakersFn            = close_fern_shakers;
    gFlushFernShakersFn            = flush_fern_shakers;
    // The smokeables (14b): the track's cones, signs, fences and barrels.
    // Each waits as a virgin in the scenery until a car touches it, then
    // turns into a body that flies, breaks and settles; one far away or
    // long asleep goes back. The roadblock's barrels are spawned ones
    // (smokeable.h, barricade.h).
    gInitSmokeablesFn             = init_smokeables;
    gCloseSmokeablesFn            = close_smokeables;
    gSpawnSmokeablesFn            = spawn_smokeables;
    gClearSmokeablesFn            = clear_smokeables;
    gConvertToSmokeableFn         = smokeable_convert_body;
    gSmokeableBreakFn             = smokeable_break;
    gDeleteFarAwaySmokeableCollisionBodiesFn =
        delete_far_away_smokeable_collision_bodies;
    gFindSmokeableInfoFn          = find_smokeable_info;
    gSmokeableSpawnFn             = smokeable_spawn;
    gBarricadeDeleteBarrelFn      = barricade_delete_barrel_seam;
    gBarricadeMarkBodyFadingFn    = barricade_mark_body_fading_seam;
    // The helicopter's munitions (12k-6): rockets, smoke bombs and
    // spikes, smokeables of their own made with the world; their
    // explosions play out in the handler the helicopter steps
    // (munition.h, chopperfire.c).
    gInitMunitionsFn              = init_munitions;
    gCloseMunitionsFn             = close_munitions;
    gMunitionEffectsDoTimestepFn  = munition_effects_do_timestep;
    // The skid marks (TASKS 78): the sets and the 64 m clans that keep
    // them, made and closed with the world and flushed by its snapshot; a
    // wheel's destructor finishes its maker's set (skids.h). Each mover
    // lays them through MaybeMakeSkids once a frame a wheel (78b).
    gInitClansFn                  = init_clans;
    gInitSkidsFn                  = init_skids;
    gCloseClansFn                 = close_clans;
    gCloseSkidsFn                 = close_skids;
    gFlushClansFn                 = flush_clans;
    gSkidSetFinishedAddingFn      = skidset_finished_adding_seam;
    gWheelMaybeMakeSkidsFn        = skids_maybe_make_skids;
    // The race's cop drivers each get a car, in limbo -- unseen, parked,
    // not colliding -- until a radar trap or a roadblock calls it out
    // (copmgr.h).
    gAddCopCarToRaceFn         = copmgr_add_cop_car_to_race;
    // World's step thinks for the cops, and uncloaks the graph's cloaked
    // edges once a racer reaches a landmark that says to (copmgr.h).
    gGlobalCopThinkFn          = copmgr_global_cop_think;
    // The helicopter (12k): made with a race's cops and deleted with the
    // race, flown in World's step, asked for by each chase that may have
    // one and sent at its chased car (pursuitchopper.h), drawn with the
    // world objects. Be A Cop's requests ask for it and for a roadblock
    // (playerinput.h). Its attacks fire the munitions above (12k-6), and
    // World's replay snapshot takes and restores it (copsnap.c, 72e-1).
    gChopperCtorFn                      = chopper_construct;
    gChopperDestroyFn                   = chopper_destruct;
    gChopperFlyFn                       = chopper_fly;
    gChopperDoSnapshotFn                = chopper_do_snapshot;
    // The cop manager's own snapshot (copmgrsnap.c, 72e-3): the pursuits,
    // the cops and the strips, made again on a restore, and the rest.
    gCopManagerDoSnapshotFn             = copmanager_do_snapshot;
    gChopperNew960Fn                    = pursuitchopper_new960;
    gChopperFollowThisCarFn             = pursuitchopper_follow_this_car;
    gPursuitUpdateChopperFn             = tpursuit_update_chopper;
    gCopManagerBeACopRequestChopperFn   = tcopmanager_be_a_cop_request_chopper;
    gCopManagerBeACopRequestRoadBlockFn =
        tcopmanager_be_a_cop_request_road_block;
    // The eggs (the cheats) are not ported; only ForceChopper's helicopter
    // egg is ever on.
    gEggIsOnFn                          = eggIsOn;
    // The pullovers (12l): a chase or a spike strip that stops its car pulls
    // it over, a ticket or an arrest, and the cop manager's think ends each
    // one when its hold runs out or its NIS finishes (pullover.h).
    gCopManagerCreatePulloverFn = copmanager_create_pullover;
    gCopManagerEndPulloverFn    = copmanager_end_pullover;
    // A player's pullover plays the next ticket or arrest NIS (12l-2): each
    // player gets a NisManager and its shuffled NISes, and World's step
    // runs UpdatePlayersGameState, which ends the NIS once its time is up
    // and calls the pullover's callback, and keeps the wrong-way flag, the
    // trouble watch and the speed ratio (playernis.h). The NIS player --
    // Load, the posing, the animation and its camera -- is not ported, so
    // the view stays on the stopped car under the TICKET or ARREST overlay.
    gNewNisManagerFn               = nismanager_new;
    gDeleteNisManagerFn            = nismanager_delete;
    gNisManagerIsPlayingFn         = nismanager_is_playing;
    gNisManagerStopFn              = nismanager_stop;
    gPlayerCreateRandomNisArrayFn  = player_create_random_nis_array;
    gPlayerPlayNextNisFn           = player_play_next_nis;
    gUpdatePlayersGameStateFn      = player_update_players_game_state;
    // What the cops say on the radio (14-10a): each chase's own speeches
    // (pursuitspeech.h), its filler (fillerspeech.h, 14-10b) and the
    // raises it, its helicopter, its roadblocks and its pullovers make
    // straight to speech::mgr_t.
    gPursuitStartSpeechFn              = tpursuit_start_pursuit_speech;
    gPursuitJoinSpeechFn               = tpursuit_join_pursuit_speech;
    gPursuitBackOffSpeechFn            = tpursuit_cop_back_off_speech;
    gPursuitDeclareSpeechFn            = tpursuit_declare_pursuit_speech;
    gPursuitRaiseBackupSpeechFn        = tpursuit_raise_backup_speech;
    gPursuitBeginCollisionSpeechFn     =
        tpursuit_begin_pursuit_collision_speech;
    gPursuitRoadblockFailedSpeechFn    = tpursuit_roadblock_failed_speech;
    gPursuitRoadBlockSetSpeechFn       = tpursuit_road_block_set_speech;
    gPursuitAITicketSpeechFn           = tpursuit_ai_ticket_speech;
    gPursuitCanSupervisorInitiateFn    = tpursuit_can_supervisor_initiate;
    gPursuitSuperInitiatesFn           = tpursuit_super_initiates;
    gSayFillerSpeechFn                 = say_filler_speech;
    gSpeechRaiseCrashTowFn             = speechRaiseCrashTow;
    gSpeechRaiseCrashFn                = speechRaiseCrash;
    gSpeechRaiseFlatTireFn             = speechRaiseFlatTire;
    gSpeechRaiseSuperRequestFn         = speechRaiseSuperRequest;
    gSpeechRaisePursuitCopHitFn        = speechRaisePursuitCopHit;
    gSpeechRaiseSuspectCrashTrafficFn  = speechRaiseSuspectCrashTraffic;
    gSpeechRaiseSpikeStripTireBlowFn   = speechRaiseSpikeStripTireBlow;
    gSpeechRaiseRequestAnotherRoadblockFn =
        speechRaiseRequestAnotherRoadblock;
    gSpeechRaiseSpikeStripRequestFn    = speechRaiseSpikeStripRequest;
    gSpeechRaiseRoadblockRequestFn     = speechRaiseRoadblockRequest;
    gSpeechRaiseDispatchRoadBlockNAFn  = speechRaiseDispatchRoadBlockNA;
    gSpeechRaiseRotorRequestFn         = speechRaiseRotorRequest;
    gSpeechRaiseRotorConfirmFn         = speechRaiseRotorConfirm;
    gSpeechRaiseDispatchHelicopterNAFn = speechRaiseDispatchHelicopterNA;
    gSpeechRaiseRacerCaughtFn          = speechRaiseRacerCaught;
    // The race's own speech (racespeech.h, RE-5): the announcer at the
    // finish, after each lap, over a knockout, the records and the
    // rewards, a pullover and Be A Cop's arrests. RaceEvent's won test
    // stays NULL until RaceEvent is ported, so an event's win says nothing.
    gRaceFinishedSpeechFn              = race_finished_speech;
    gLapFinishedSpeechFn               = lap_finished_speech;
    gMaybeDoKnockoutRaceOverSpeechFn   = maybe_do_knockout_race_over_speech;
    gPostGameLapRecordFn               = post_game_lap_record;
    gPostGameTimeRecordFn              = post_game_time_record;
    gRewardCarSpeechFn                 = rewardCarSpeech;
    gPointsScreenSpeechFn              = points_screen_speech;
    gSpeechPulloverEventFn             = pullover_speech;
    gSpeechBeACopArrestFn              = be_a_cop_arrest_speech;
    logPrintf("car loader: pool %s\n", LoadedCarSlotPool ? "up" : "missing");

    // The blurb moves to the bottom screen, so the top screen stops drawing
    // it -- and stops drawing the bar tAnimatedBlurb wipes it out with,
    // which on its own over an empty strip is just a flash of grey. The
    // animations still run and still move the object; this is a draw-time
    // skip, so nothing has to know.
    uirender_hide_object(&ui, BSCR_OBJ_SCROLLING_TEXT);
    uirender_hide_object(&ui, BSCR_OBJ_WHITEOUT_BAR);
    uirender_hide_object(&ui, ETV_OBJ_SCROLLING);

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
    scrHooks.setEventTree        = hookSetEventTree;
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
    animHooks.setScreenVisible = hookSetScreenVisible;
    bscr_set_anim_hooks(&g_uiScreens, &animHooks);
    // The title's bloom runs on the same kit, as tHighlightAnimation is one
    // class for every screen in the original.
    g_flow.anim = &g_uiScreens.anim;

    // FlailerScreenList's constructor makes its tHelpMenu, on GLOBALB's
    // help screen, which is loaded by now.
    {
        static const HelpMenuHooks helpHooks = {
            .user                = &g_boot,
            .translate           = helpTranslate,
            .soundEnabled        = helpSoundEnabled,
            .playSelect          = helpPlaySelect,
            .setScreenVisibility = helpScreenVisibility,
            .anim                = helpAnim,
        };
        helpmenu_construct(&g_help, &helpHooks, trackSelKit());
        logLine("help: backdrop %s",
                g_help.fade.exists ? "found" : "missing");
    }

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
    setupHooks.printText           = hookAnimPrintText;
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
    lobby_init(&kLobbyNet, lobbyLog);
    netrace_init(&kNetRaceNet, &kNetRaceGame, lobbyLog);
    netstep_init(&kNetStepNet, lobbyLog);
    netstep_set_hold(ConfigWirelessHoldSeconds > 0
                     ? (uint32_t)ConfigWirelessHoldSeconds * 1000u : 0u);
    netstep_on_differ(lockDiffers);
    lobby_on_start(lobbyStarted);
    lobby_on_setup(lobbySetup);
    lobby_cpu_wish(lobbyCpuWish);
    gTrackFlowHoldRaceFn = netrace_hold;
    gTrackFlowViewUnloadFn = raceDetachTrack;

    BCarSelHooks carselHooks;
    memset(&carselHooks, 0, sizeof(carselHooks));
    carselHooks.user               = &g_boot;
    carselHooks.translate          = hookCarSelTranslate;
    carselHooks.translateString    = hookCarSelTranslateString;
    carselHooks.sound              = hookCarSelSound;
    carselHooks.stopSound          = hookCarSelStopSound;
    carselHooks.setHelpOverride    = hookSetupHelpOverride;
    carselHooks.helpMenuActive     = hookCarSelHelpActive;
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
    carselHooks.speakCar           = hookCarSelSpeakCar;
    carselHooks.speechFade         = hookCarSelSpeechFade;
    carselHooks.soundEnabled       = hookCarSelSoundEnabled;
    carselHooks.language           = hookCarSelLanguage;
    carselHooks.stopMovie          = hookCarSelStopMovie;
    carselHooks.wirelessRace       = hookCarSelWirelessRace;
    carselHooks.trace              = hookTrace;
    bcarsel_init(&g_carsel, &carselHooks);

    BTrackSelHooks trackselHooks;
    memset(&trackselHooks, 0, sizeof(trackselHooks));
    trackselHooks.user              = &g_boot;
    trackselHooks.translate         = hookCarSelTranslate;
    trackselHooks.speechFade        = hookCarSelSpeechFade;
    trackselHooks.speakTrack        = hookTrackSelSpeak;
    trackselHooks.isTrackUnlocked   = hookTrackSelUnlocked;
    trackselHooks.formatUnlockBlurb = hookTrackSelFormatUnlockBlurb;
    trackselHooks.renderTextIntoRectangle = hookCarSelRenderText;
    trackselHooks.setActiveMenuItem = hookTrackSelSetActive;
    trackselHooks.getActiveMenuItem = hookActiveMenuItem;
    trackselHooks.packNew           = hookTrackSelPackNew;
    trackselHooks.packDelete        = hookTrackSelPackDelete;
    trackselHooks.packUnloadAll     = hookTrackSelPackUnloadAll;
    trackselHooks.packHasTexture    = hookTrackSelPackHas;
    trackselHooks.packLoad          = hookTrackSelPackLoad;
    trackselHooks.highlightInit     = hookTrackSelHighlightInit;
    trackselHooks.highlightSetItem  = hookTrackSelHighlightItem;
    trackselHooks.highlightAnimate  = hookTrackSelHighlightAnimate;
    trackselHooks.language          = hookCarSelLanguage;
    trackselHooks.startRace         = hookCarSelStartRace;
    trackselHooks.trace             = hookTrace;
    btracksel_init(&g_tracksel, &trackselHooks);

    g_etvHooks.user                    = &g_boot;
    g_etvHooks.translate               = hookCarSelTranslate;
    g_etvHooks.translateString         = hookCarSelTranslateString;
    g_etvHooks.anim                    = hookEtvAnim;
    g_etvHooks.renderBitmap            = hookEtvRenderBitmap;
    g_etvHooks.renderText              = hookEtvRenderText;
    g_etvHooks.renderTextIntoRectangle = hookEtvRenderTextRect;
    g_etvHooks.setHelpOverride         = hookSetupHelpOverride;
    g_etvHooks.hideHelp                = hookEtvHideHelp;
    g_etvHooks.stopMovie               = hookCarSelStopMovie;
    g_etvHooks.jukeboxStart            = hookEtvJukebox;
    g_etvHooks.preloadCars             = hookSetupPreloadCars;
    g_etvHooks.trace                   = hookTrace;
    eventtreeview_init(&g_etvHooks);

    DebugMenuHooks debugHooks;
    memset(&debugHooks, 0, sizeof debugHooks);
    debugHooks.user          = &g_boot;
    debugHooks.setActiveItem = hookDebugSetActiveItem;
    debugHooks.startRace     = hookCarSelStartRace;
    debugHooks.log           = hookDebugLog;
    debugmenu_init(&debugHooks);

    NameEntryHooks nameHooks;
    memset(&nameHooks, 0, sizeof nameHooks);
    nameHooks.keyboard = hookNameKeyboard;
    nameHooks.log      = hookNameEntryLog;
    nameentry_init(&nameHooks);

    AudioOptionsHooks audioHooks;
    memset(&audioHooks, 0, sizeof audioHooks);
    audioHooks.log     = hookAudioOptsLog;
    audioHooks.jukebox = &g_jukebox;
    audioHooks.sound   = &gSoundModule;
    audioopts_init(&audioHooks);

    // The pause menu's pages (71e) set bSound's volumes and the mode.
    PauseOptionsHooks pauseHooks;
    memset(&pauseHooks, 0, sizeof pauseHooks);
    pauseHooks.log     = hookAudioOptsLog;
    pauseHooks.jukebox = &g_jukebox;
    pauseHooks.sound   = &gSoundModule;
    pause_options_init(&pauseHooks);

    DisplayOptionsHooks displayHooks;
    memset(&displayHooks, 0, sizeof displayHooks);
    displayHooks.log = hookDisplayOptsLog;
    displayopts_init(&displayHooks);

    JoyConfigHooks joyConfigHooks;
    memset(&joyConfigHooks, 0, sizeof joyConfigHooks);
    joyConfigHooks.log   = hookDisplayOptsLog;
    joyConfigHooks.noise = fesound_play;
    joyConfigHooks.text  = hookJoyConfigText;
    joyconfig_init(&joyConfigHooks);
    // Options' Controller page names the keys themselves (joyconfig.h),
    // and a replay the scanners' (uiHelpLayout).
    gUiHelpLayoutFn = uiHelpLayout;

    // Retail's main (0x0012f000), after InitializeEverything: with SkipFE
    // set, StartSkipFEGame on Fred, whose StartRace asks for
    // LOADING_TRACK_COMMON straight from NONE; else
    // ChangeGameFlow(LOADING_FRONTEND). MainLoop takes it from there.
    gFredGameFlowStateFn  = fredFlowState;
    gFredChangeGameFlowFn = fredChangeFlow;
    if (g_flow.skipFE) {
        // Retail's SkipFE comes from a joylog, whose replay carries the
        // type-changed event. The port's (R held) races with no frontend
        // frames before it, and a race in progress pauses for a port with
        // no controller (player_update_non_game_state); so the type
        // detection's reads, 32 in retail, are made here.
        for (int i = 0; i < 64 && !IsJoystickPluggedIn(0); i++)
            GenerateJoyEvents();
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
    if (!trackview_mirror_init()) {
        logPrintf("georender: no room for the rear-view mirror\n");
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
        FrameProfReplayWait = 0;
        hidScanInput();
        u32 kDown = hidKeysDown();
        // The Circle Pad moves through the menus as the D-pad does (TASKS
        // 42). Only the flow's input hears it: a race steers with it, and
        // the viewers pan with it.
        u32 menuDown;
        {
            static JoyHidMenuPad menuPad;
            circlePosition cp;
            hidCircleRead(&cp);
            menuDown = kDown | joyhid_menu_pad(&menuPad, cp.dx, cp.dy);
        }

        // sound::Update (0x001af4c0): the regions' poll, then -- past its
        // 8 ms gate, which passes at any frame rate up to 125 -- the
        // jukebox's Update, a delayed start, bSound::Update and the
        // muffler. The delayed start counts down by the world's step
        // (gp-19560), which is still the last frame's here: the clocks
        // advance below. Then the port's stream feed for the jukebox.
        frameMark("sound");
        sound_update(&gSoundModule);
        if (soundUp) jbstream_poll(&g_jukebox.jukebox);
        {
            // The log's note of each tune that starts, the race's too.
            static uint32_t lastTune = 0xffffffffu;
            const JBPlayer* jp = &g_jukebox.jukebox;
            uint32_t tune = jp->statePlay == JB_PLAYING
                ? (jp->curCatNum << 16) | jp->curTuneNum : 0xffffffffu;
            if (tune != lastTune && tune != 0xffffffffu) {
                logLine("jukebox playing: %s",
                        jb_tune_name(&g_jukebox.jukebox, jp->curCatNum,
                                     jp->curTuneNum));
            }
            lastTune = tune;
        }
        MainLoopTiming.UpdateSound = bGetTicker();

        // MainLoop's clocks (0x0012f378). It prepares the real step at the
        // top of a frame from the ticker (0x0012f43c), and the world's from
        // the real one when there is no race. It advances both at the
        // frame's end (0x0012f62c), which here is the top of the next one.
        // FrameCounter is the vertical-blank count PSX2VBlank keeps: the
        // top screen's, from citro3d (realtime.h).
        //
        // A wireless race steps in lockstep (lockFrame): a loop that runs
        // no race frame advances no clock, and the step is the record's.
        bool lockOn = netstep_on();
        bool raceStep = true;
        g_lockMenu |= menuDown;
        if (clockStarted && (!lockOn || g_lockRan)) {
            AdvanceRealTime();
            AdvanceWorldTime();
        }
        g_lockRan = false;
        clockStarted = true;
        FrameCounter = (int32_t)C3D_FrameCounter(0);
        if (lockOn) {
            raceStep = lockFrame(&frameTicker);
            lockHoldMute(netstep_held((uint32_t)osGetTime(), NULL) != 0
                         || netstep_rejoining(NULL) != 0);
            lockCatchUpMute(lockCatchingUp());
            lockRejoin((uint32_t)osGetTime());
        } else {
            prepare_real_timestep_from_ticker(&frameTicker);
        }

        if (raceStep) uiTimer += (uint32_t)(int)(RealTimeElapsed * 4000.0f);
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
        // They are developer tools, so only with the debug menu: "DebugMenu
        // 1" or the main menu's L + R + D-Pad Up (launch blocker 1,
        // 2026-10-16). The flow never has SELECT otherwise.
        if ((kDown & KEY_SELECT) && !raceUp && !g_track.attached
            && (ConfigDebugMenu || debugmenu_revealed())) {
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

        audioHoldTick();

        if (mode == MODE_FLOW) {
            // ---- the boot flow
            // In the frontend the screens have the pad before the flow's
            // pass. A race's have it after the coordinator's queue and
            // the players' events, below.
            // Options' Controller page has its keys first: X, and every
            // key while it waits for one (joyconfig.h).
            if (!raceUp) {
                u32 took = joyconfig_input(kDown);
                if (took) redraw = 1;
                menuDown &= ~took;
            }
            if (!raceUp && flowInput(menuDown, 0)) redraw = 1;

            // The local wireless link, on whichever screen: what came in,
            // the resends and the network's status, before the screens
            // read it (TASKS 37). A lockstep race's was pumped in its wait.
            if (wireless_state() != WIRELESS_OFF && !lockOn)
                wireless_pump((uint32_t)osGetTime());
            // A wireless race's end: the host's last frames served, a
            // client's stop said (netstep.h).
            if (netstep_ending()) netstep_drain((uint32_t)osGetTime());
            // And a wireless race's setup, through the loads too.
            if (netrace_active()) netrace_frame(&g_flow);
            // A wireless race shows this console's player alone (player.h)
            // from its load on, until the race is gone. A place past the
            // two players' is player 0's view for now (37d-2).
            if (netrace_active() && netrace_stage() >= NR_LOADING) {
                PlayerNetLocal = netShownPlayer();
            } else if (pRaceCoordinator == NULL) {
                PlayerNetLocal = -1;
            }
            eViewShowOne = PlayerNetLocal >= 0;

            // TheDemoModeReplay's +4 and +8 and Fred.DemoModeStatus, which
            // the flow keeps as its own (gameflow.h).
            g_flow.replayLoading = TheDemoModeReplay.LoadingFlag;
            g_flow.replayLoaded = TheDemoModeReplay.LoadedFlag;
            g_flow.demoModeStatus = Fred.DemoModeStatus;

            // MainLoop: one pass of the flow per frame, by the real step.
            // bgf_frame is the flow's service and the menus' tick both.
            // With no race the race's three stamps are the same tick.
            frameMark("flow");
            if (raceStep) {
                bgf_frame(&g_flow, RealTimeElapsed);
                // FlailerScreenList::Tick's last: the HELP panel's slide.
                helpmenu_tick(&g_help, RealTimeElapsed);
            }
            // The main menu's rows where its window puts them, over the
            // slide-in's groups (debugmenu.h).
            if (g_flow.screen
                && g_flow.screen->hash == BGF_SCREEN_NEW_MAIN_MENU)
                debugmenu_main_tick();
            MainLoopTiming.ServiceGameFlow = bGetTicker();
            MainLoopTiming.MenuSystemTick = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.GenerateJoyEvents = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.WorldDoTimestep = MainLoopTiming.ServiceGameFlow;
            MainLoopTiming.UpdateCameraMovers = MainLoopTiming.ServiceGameFlow;
            if (raceUp && pRaceCoordinator != NULL) {
                if (raceStep) raceFrame();
                if (!lockOn && pRaceCoordinator != NULL) raceTestFinish();
                if (!lockOn) raceTestMenuLog();
                // GenerateJoyEvents hands the Flailer and the players the
                // same events, after ExecuteQueuedMessages: the START that
                // resumes the race posts the unpause, and the players,
                // still paused, let it go. Before the queue it would be
                // racing again by the players' turn, and pause again.
                // In lockstep the presses are the record's.
                if (lockOn) {
                    if (raceStep && lockFlowInput()) redraw = 1;
                } else if (flowInput(menuDown, 0)) {
                    redraw = 1;
                }
                // Not when the coordinator's own tick went on to the
                // unload: a Next Race's Begins of unloading and loading
                // run in it, and the attach found the next track's bundle
                // only begun, failed in geo_open, and freed its 3.6 MB of
                // tables in the middle of the load (Session 109).
                frameMark("race: the track's attach");
                if (pRaceCoordinator != NULL) (void)raceAttachTrack();
            } else if (raceUp) {
                // The coordinator went in the flow's pass (Quit Race's
                // unloading): the pad is the screen's that is up.
                if (flowInput(menuDown, 0)) redraw = 1;
            } else if (g_flow.current == BGF_IN_FRONTEND) {
                // MainLoop's UpdateCameraMovers, which raceFrame makes in
                // a race; in the frontend the car select's camera is the
                // one mover.
                update_camera_movers();
            }
            // The lockstep frame ran: the world's checksum after it, in
            // parts (lockhash.h), and on to the next. Lockstep ends after
            // the frame that asked for the end's save, or with the race
            // gone (the pause's Quit), not before its coordinator was
            // ever up (the GO loop's flow makes it): the race's end, and
            // the lobby next (37f).
            if (lockOn && raceStep) {
                lockTestFinish();
                lockTestDrop();
                netstep_done(lockhash_ran(netstep_frame(), pCurrentWorld));
                g_lockRan = true;
                if (pRaceCoordinator != NULL) g_lockRaced = true;
            }
            if (netstep_on()
                && (g_lockEnd
                    || (g_lockRaced && pRaceCoordinator == NULL))) {
                uint32_t now = (uint32_t)osGetTime();

                netstep_stop(now);
                lockhash_stop();
                netrace_end();
                netstep_drain(now);
                g_lockEnd = false;
                lockHoldMute(false);
                lockCatchUpMute(false);
                wireless_set_rejoin(0, NULL);
            }

            // The view let go in the Begin of unloading
            // (raceDetachTrack); this is only for a race gone without it.
            if (pRaceCoordinator == NULL) raceAttachGaveUp = false;
            if (pRaceCoordinator == NULL && g_track.attached)
                raceDetachTrack();

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

            // The frame the flow makes the race in, and any the attach
            // waits on, draw nothing: the Loading screen stays up until
            // the track is attached (raceAttachTrack). They keep the blank's
            // pace and the loads' service.
            if (raceHoldsLoadingScreen()) {
                frameMark("race: the Loading screen held");
                C3D_FrameSync();
                (void)service_resource_loading();
                bootServiceLoads(&g_boot);
                continue;
            }

            // A console back after a restart, well behind (37g-3): the
            // race's frames as fast as they run, undrawn but for the
            // progress now and then; the loads served still.
            if (lockOn && lockCatchingUp()) {
                frameMark("race: catching up");
                lockCatchUpDraw(&ui);
                (void)service_resource_loading();
                bootServiceLoads(&g_boot);
                continue;
            }
            // WirelessTestBlindFrame's frames (configitems.h): undrawn,
            // two blanks each, as the race's pace.
            if (lockOn && lockTestBlind()) {
                frameMark("race: undrawn for the test");
                C3D_FrameSync();
                C3D_FrameSync();
                (void)service_resource_loading();
                bootServiceLoads(&g_boot);
                continue;
            }

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
            CoreSampleStage = CS_STAGE_WAITS;
            frameMark("C3D_FrameSync: the vertical blank");
            if (g_track.attached && C3D_FrameCounter(0) == lastSync)
                C3D_FrameSync();
            C3D_FrameSync();
            uint32_t gpuTick = bGetTicker();
            hangwatch_gpu_race(g_track.attached);
            capture_race(g_track.attached);
            warp_race(g_track.attached);
            frameMark("C3D_FrameBegin: the GPU's last frame");
            C3D_FrameBegin(0);
            hangwatch_gpu_begin();
            hangwatch_gpu_sends_begin(g_track.attached && ConfigGpuSends);
            // The last frame's picture for the pause's frames, ahead of
            // anything this frame sends (capture.h).
            capture_pause_frame(top, pRaceCoordinator != NULL
                                && pRaceCoordinator->CurrentRCState
                                       == RCSTATE_PAUSE);
            uint32_t drawTick = bGetTicker();
            // The GPU is done with the last frame: what the frontend's view
            // let go of since can be freed, and the slideshow's pictures.
            trackview_frame_begun(&g_feView);
            trackview_frame_begun(&g_track);
            trackSelSyncPictures(&ui);
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

                frameMark("the sun's depth read");
                if (capture_read(top))
                    trackview_capture_names(&g_track);
                trackview_read_depth(&g_track, top);
                trackview_draw_envmap(&g_track);
                FRAMEPROF_STAMP(FRAMEPROF_ENVMAP);
                // The envmap's faces to the GPU while the mirror is built,
                // then the mirror while the view is (hangwatch.h's sends).
                hangwatch_gpu_send();
                trackview_draw_mirror(&g_track);
                FRAMEPROF_STAMP(FRAMEPROF_MIRROR);
                hangwatch_gpu_send();
                // Two fills, the colour's and the depth's, so the view's
                // draws wait for the depth's end (c3dwrap.c, TASKS 64).
                C3D_RenderTargetClear(top, C3D_CLEAR_ALL,
                                      __builtin_bswap32(sky), 0);
                C3D_FrameDrawOn(top);
                trackview_draw(&g_track);
                notePauseFrame(drawTick);
                C2D_Prepare();
                C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
            } else {
                C2D_TargetClear(top, clear);
            }
            C2D_SceneBegin(top);
            flowRender(&ui);
            if (!g_track.attached && (bcarsel_active() || btracksel_active()))
                drawCarSelTop(&ui);
            else
                uirender_draw_visible(&ui, 1.0f);
            etvDrawText(&ui);
            if (g_track.attached && netstep_on()) drawLockHeld(&ui);
            C2D_Flush();
            hangwatch_gpu_stage("the top screen's HUD");
            FRAMEPROF_STAMP(FRAMEPROF_HUD);
            // The top screen to the GPU, and nothing left for
            // C2D_TargetClear's split, which flushes nothing.
            hangwatch_gpu_send();
            C2D_TargetClear(g_bot, BOT_BACK);
            C2D_SceneBegin(g_bot);
            // In a race the bottom screen is the HUD's other half
            // (hudsplit.h), and the frontend's panel when the HUD is down.
            if (PLAYER_NUM_SHOWN() == 1 && player_shown(0) != NULL)
                hudsplit_set_features(player_shown(0)->CurrentHudFeatures);
            // The pause takes the HUD down, its bottom half with it, and
            // leaves its screen up: the panel then, so the logo shows on
            // the pause and its pages and not a black screen.
            bool racePaused = pRaceCoordinator != NULL
                && pRaceCoordinator->CurrentRCState == RCSTATE_PAUSE;
            // View Replay's panel (kReplayNote), whatever the HUD left up.
            bool replayUp = pRaceCoordinator != NULL
                && pRaceCoordinator->pReplayScreen != NULL;
            if (!racePaused && !replayUp
                && uirender_draw_visible_bottom(&ui, BOT_W, BOT_H, 1.0f)) {
                // eDisplayFrame's RenderTrackMap for each player, after
                // the Flailer layers: the minimap, made bigger under the
                // bottom screen's top band (hudsplit_map_place).
                if (g_track.loaded) {
                    float mapScale = 1.0f, mapDx = 0.0f, mapDy = 0.0f;

                    for (int i = 0; i < PLAYER_NUM_SHOWN(); i++) {
                        player_render_track_map(player_shown(i));
                    }
                    if (PLAYER_NUM_SHOWN() == 1
                        && player_shown(0)->pTrackMap != NULL) {
                        hudsplit_map_place(
                            player_shown(0)->pTrackMap
                                ->CurrentlyDisplayedMode,
                            &mapScale, &mapDx, &mapDy);
                    }
                    C2D_Flush();
                    trackview_draw_flailer_polys(&g_track, BOT_W, BOT_H,
                                                 mapScale, mapDx, mapDy);
                    C2D_Prepare();
                    C3D_DepthTest(false, GPU_GREATER, GPU_WRITE_COLOR);
                }
                // The score's event lines, over the map.
                uirender_draw_visible_bottom_over(&ui, BOT_W, BOT_H, 1.0f);
            } else {
                // 0x86 and 0x87 are the A and B buttons' icons in the
                // menus (helpglyph.h).
                const char* title = NULL;
                const char* body  = g_blurbShown;
                float       fade  = g_blurbFade;
                float       frame = g_blurbHad ? 1.0f : g_blurbFade;
                const char* hint  = "\x86 Select    \x87 Back";

                if (g_flow.screen
                    && g_flow.screen->callback == bgf_plain_screen_callback) {
                    body = kPlainScreenNote;
                    fade = frame = 1.0f;
                }
                if (replayUp) {
                    body = kReplayNote;
                    hint = kReplayHint;
                    fade = frame = 1.0f;
                }
                if (g_flow.screen
                    && g_flow.screen->callback == joyconfig_callback) {
                    const char* b = joyconfig_bottom_body();
                    const char* h = joyconfig_bottom_hint();
                    if (b) {
                        body = b;
                        fade = frame = 1.0f;
                    }
                    if (h) hint = h;
                }
                if (g_flow.screen
                    && g_flow.screen->callback == debugmenu_callback) {
                    title = "Debug Menu";
                    hint  = DEBUGMENU_HINT;
                }
                if (g_flow.screen
                    && g_flow.screen->callback == debugmenu_race_callback) {
                    title = "Debug Race";
                    hint  = DEBUGMENU_HINT;
                }
                drawBotDialog(&ui, title, body, fade, frame, hint);
            }
            C2D_Flush();
            hangwatch_gpu_stage("the bottom screen");
            FRAMEPROF_STAMP(FRAMEPROF_BOTTOM);
            hangwatch_gpu_sends_end();
            C3D_FrameEnd(0);
            hangwatch_gpu_frame_end();
            CoreSampleStage = CS_STAGE_OTHER;
            // eDisplayFrame's end (0x00113fd0), its packets sent: FrameEffects,
            // car select's nebula, a sixtieth of a second on (gp-32668) each
            // frame drawn, the race's as well.
            acid_system_do_time_step(&FrameEffects, 1.0f / 60.0f);
            MainLoopTiming.DisplayFrame = bGetTicker();
            // MainLoop's ServiceResourceLoading, after eDisplayFrame: the
            // resource system's, then the frontend's bundles (bootQueue).
            frameMark("the loads");
            (void)service_resource_loading();
            bootServiceLoads(&g_boot);
            MainLoopTiming.ServiceFileSystem = bGetTicker();
            frameMark("the frame's sums");

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
                    char line[1536];

                    FrameProfDraw.jukeboxDecode = decode - jbDecode;
                    FrameProfDraw.jukeboxRead = read - jbRead;
                    frameprof_add(&prof, &MainLoopTiming,
                                  C3D_GetProcessingTime(),
                                  C3D_GetDrawingTime());
                    if (frameprof_line(&prof, line, sizeof line)) {
                        logLine("%s", line);
                        if (coresample_line(line, sizeof line))
                            logLine("%s", line);
                        logWorldStep();
                    }
                    jbLineTick = MainLoopTiming.LimitFrameRate;
                    jbLineDecode = decode;
                    jbLineRead = read;
                } else {
                    uint32_t span = MainLoopTiming.LimitFrameRate
                                  - jbLineTick;

                    frameprof_reset(&prof);
                    clearWorldStep();
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
    // ChangeToScreen(NULL) hides the screen, closes its menu (closeMenu)
    // and then sends it SCREEN_UNACTIVATE, the order FlailerScreen::
    // UnActivate has. The viewer's menu is nobody's, so it just closes.
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
