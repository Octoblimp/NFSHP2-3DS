#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "banim.h"
#include "bmenu.h"
#include "bpopup.h"
#include "memcard.h"

// The boot flow: main() to the main menu.
//
// This is the port of two mechanisms that between them get the PS2 game from
// its entry point to "New Main Menu", decompiled in docs/formats/boot-flow.md
// with an address for every rule here.
//
//  * GameFlowStateInfoTable and ServiceGameFlow (0x001680e8): ten states,
//    each with an optional Begin/End/Loop, serviced in a loop until the
//    desired state stops moving.
//  * LaunchFrontendMenus (0x0016f950) and FlailerScreenList: a LIFO of
//    screen names that the boot fills backwards and immediately pops.
//
// Addresses are retail's, SLES_507.31, unless they say the demo's.
//
// There is no BootFlowManager class in the game -- that is what task 14 went
// looking for and did not find. The sequence is a table plus a stack.
//
// Like bui.c and bmenu.c this is free of <3ds.h>: everything that touches a
// screen, a movie, a texture or the clock goes through BGameFlowHooks, so
// tools/bootflow_check.py can drive it on the host and diff it against a
// second implementation.

#define BGF_STACK_DEPTH 12
#define BGF_NAME_LEN    32

// GameFlowState, verbatim from the .mdebug type info. IN_FRONTEND and RACING
// are the two resting states and have no functions at all.
typedef enum {
    BGF_NONE = 0,
    BGF_LOADING_FRONTEND,
    BGF_UNLOADING_FRONTEND,
    BGF_IN_FRONTEND,
    BGF_LOADING_TRACK_COMMON,
    BGF_LOADING_TRACK_SPECIFIC,
    BGF_RACING,
    BGF_UNLOADING_TRACK_SPECIFIC,
    BGF_UNLOADING_TRACK_COMMON,
    BGF_EXIT_DEMO_DISC,
    BGF_NUM_STATES,
} BGameFlowState;

// The screens the boot flow names, and the objects on them. A screen's hash
// is bStringHash of the *authored* name, which is not the string the flow
// code passes to ChangeToScreen -- see BScreenConfig.
#define BGF_SCREEN_TITLE          0xb5761d00u  // "Title Screen"
#define BGF_SCREEN_NEW_MAIN_MENU  0xae0f8aa1u  // "New Main Menu"
#define BGF_SCREEN_LANGUAGE       0x632b068eu  // "Language Options Pre FE"
#define BGF_SCREEN_BOOT_AUTOLOAD  0xfa2ac5c6u  // "BootAutoload"
#define BGF_SCREEN_MUMBO_JUMBO    0xdd4197c9u  // "Legal MumboJumbo"
#define BGF_SCREEN_LOADING_TRACK  0xd0131dd1u  // LOADING_TRACK, hidden on exit
#define BGF_SCREEN_FIRSTLEGAL     0x8139ec90u  // demo-disc slideshow, 0-3s
#define BGF_SCREEN_SLIDE2         0xa7227ae8u  // demo-disc slideshow, 3-6s
#define BGF_SCREEN_DISCLAIMER     0x8254cc20u  // demo-disc slideshow, 6-9s

// Retail's object chunks carry their own names (a char[24] the demo's do
// not have), which is where these come from.
#define BGF_OBJ_MOVIE_PLANE_43    0x3acf2d73u  // TITLE_FULLSCREEN, 4:3 plane
#define BGF_OBJ_MOVIE_PLANE_LB    0xbfaebf79u  // TITLE_LETTERBOX
#define BGF_OBJ_PRESS_START       0xb070dbc9u  // PRESS_START_1
#define BGF_OBJ_COPYRIGHT         0x807d4c5cu  // COPYRIGHT_TEXT, in TITLE_IMAGE
#define BGF_OBJ_ANIMATING_ITEM    0xab671c9au  // ANIMATING_MENUITEM, the bloom
#define BGF_OBJ_MUMBO_PLANE       0xdd479599u  // the legal/anti-piracy plane

// bStringHash("TITLE_IMAGE"), hashed at run time from 0x002b2f58. The group
// is the logo, the bar under it and COPYRIGHT_TEXT -- everything the title
// shows once no movie is playing.
#define BGF_GROUP_TITLE_IMAGE     0xb73c8d23u

// NEW_MAIN_MENU's Easter egg pair: "Unlocked" (LanguageID 62001) over the
// egg's name, text object 0xf58c1a4b. Retail named neither the group nor
// the object: both carry their hash as their name. NewMainMenu hides the
// group as it is built and as it is torn down, and shows it for three
// seconds when a code has just been entered (OnTick, 0x00216718).
#define BGF_GROUP_EASTER_EGG      0x74e404b4u

#define BGF_TEX_LEGAL             0xa7ebc389u  // both out of GLOBAL\DYNTEX.BIN
#define BGF_TEX_ANTIPIRACY        0x38258033u

typedef struct BGameFlow BGameFlow;

// A load's completion callback: LoadResourceFile's and
// LoadSoundRegionsFrontEnd's, run by the host once the load is done.
typedef void (*BGameFlowDone)(BGameFlow* gf);

// GameFlowStateInfo (0x002f2eb0), 16 bytes in the original and the same four
// fields here. A NULL function is a state that does nothing, which is how
// IN_FRONTEND and RACING rest.
typedef struct {
    const char* name;
    void (*begin)(BGameFlow* gf);
    void (*end)(BGameFlow* gf);
    void (*loop)(BGameFlow* gf);
} BGameFlowStateInfo;

typedef void (*BScreenCallback)(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data);

// FlailerScreenConfig, cut down to the three fields the flow needs.
//
// `name` and `hash` are two different strings and that is not a mistake:
// `name` is the C++ literal ChangeToScreen takes ("Title Screen"), `hash` is
// bStringHash of the name the screen was authored under ("TITLE_SCREEN").
// bhash("Title Screen") is in no bundle on the disc. FlailerScreenConfig is
// the only thing in the game that joins the two namespaces, so the port has
// to carry the same join.
typedef struct BScreenConfig {
    const char*     name;
    uint32_t        hash;
    BScreenCallback callback;
} BScreenConfig;

// One row of the boot sequence: LaunchFrontendMenus' push list, which is the
// kVideoStages[] of this game. Rows are pushed onto a LIFO in order and the
// flow enters the one on top, so the LAST row whose predicate passes is the
// FIRST screen the player sees.
typedef struct {
    const char* screenName;
    int (*shouldSee)(const BGameFlow* gf);
} BBootStage;

// Everything the flow does to the outside world. All of it is optional: a
// NULL hook is a no-op, and the ones that answer a question answer "ready"
// so a host test needs only the hooks it cares about.
typedef struct {
    void* user;

    // FlailerSetScreenVisibility / FlailerSetVisibility. Both take
    // `visible` as a bool here. The original's two enums have OPPOSITE
    // polarity -- FlailerScreenVisibility is VISIBLE=0/INVISIBLE=1 while
    // FlailerObjectVisibility is INVISIBLE=0/VISIBLE=1, used one line apart
    // in TitleScreen::HandleTick -- and reproducing that here would only
    // spread the trap.
    void (*setScreenVisible)(void* user, uint32_t screen, int visible);
    void (*setObjectVisible)(void* user, uint32_t screen, uint32_t object,
                             int visible);
    // FlailerSetGroupVisibility (0x001454e8): every object on `screen`
    // whose GroupHash is `group`. Object polarity, so again a bool here.
    void (*setGroupVisible)(void* user, uint32_t screen, uint32_t group,
                            int visible);
    void (*changeTexture)(void* user, uint32_t screen, uint32_t object,
                          uint32_t texture);

    // The UI layer, in the three steps of FlailerScreen::Activate
    // (0x0016a858). `openScreen` comes BEFORE SCREEN_ACTIVATE: Activate
    // builds the screen's FlailerMenu first, so a constructor can gray an
    // item of it (LanguageOptionsScreenBase does). `enterScreen` comes
    // after: that is where the menu takes its current item and sends the
    // opening highlight, to a screen object that exists by then.
    // `leaveScreen` fires after SCREEN_UNACTIVATE. See bgf_change_to_screen.
    void (*openScreen)(void* user, const BScreenConfig* cfg);
    void (*enterScreen)(void* user, const BScreenConfig* cfg);
    void (*leaveScreen)(void* user, const BScreenConfig* cfg);

    // GrayMenuItem (0x0016d2a8): item `item` of the menu on the Flailer
    // screen `screen`. Mode 1 enables it and shows it, 0 disables it (drawn
    // grayed) and 2 disables it and hides it. BScrGrayMode's values.
    void (*grayMenuItem)(void* user, uint32_t screen, uint32_t item,
                         int mode);
    // GetActiveMenuItem (0x0016d3f0): the hash of the current screen's
    // highlighted item, or 0 with no menu.
    uint32_t (*activeMenuItem)(void* user);

    // MoviePlayer. `open` returns 0 if the file is not there, which on this
    // disc is the normal case for the second title movie -- see gameflow.c.
    // `drive` returns 1 when the movie has finished.
    int  (*movieOpen)(void* user, const char* path);
    int  (*movieDrive)(void* user);
    void (*movieClose)(void* user);
    // The menus' movie, FlailerScreenList's (bgf_start_movie below), on the
    // same MoviePlayer, which `movieClose` closes. `panelMovieOpen` is
    // InitFile (0x00237ad8), into PANELMOVIE; `panelMovieUpdate` is Update
    // (0x002380a8) in retail's pacing, 0 once the movie is over -- and at
    // once for a file that would not open. No hook answers 1: playing.
    int  (*panelMovieOpen)(void* user, const char* path);
    int  (*panelMovieUpdate)(void* user);
    // InGameFlag (0x00330540), trackflow.c's: a race's world is in.
    int  (*inGame)(void* user);

    // LoadResourceFile (0x00199640). `done`, when not NULL, is the file's
    // completion callback: the host calls it, with the flow, once the file
    // is resident -- ServiceResourceLoading runs the callbacks, after the
    // frame's eDisplayFrame (MainLoop, 0x0012f60c). Retail loads the
    // frontend this way: the state moves on from FRONTB's callback, not
    // from a poll.
    void (*loadResource)(void* user, const char* path, BGameFlowDone done);
    // LoadSoundRegionsFrontEnd (0x001ae9a0), with its completion callback.
    void (*loadSoundRegions)(void* user, BGameFlowDone done);
    // LanguageManager::SetLanguage's file load: FE_<language>.BIN.
    void (*setLanguage)(void* user, int language);
    // LoadLocalizedSpeechFiles (0x001ae4d8) and its Un- (0x001ae5e8).
    void (*loadSpeech)(void* user, int language);
    void (*unloadSpeech)(void* user);
    // 0x001681b0: the dynamic pack's LOADING and NFS_LOGO_ALPHA textures
    // take their French art (LOADING_FR, NFS_LOGO_ALPHA_FR) when `french`
    // is 1, and their own again when it is 0.
    void (*swapLogoArt)(void* user, int french);
    // eDisplayFrame (0x00112858), called once outside MainLoop: by
    // LoadGlobalChunks, so the LOADING screen is up while the rest loads.
    void (*displayFrame)(void* user);

    // pDynamicTexturePack, for the legal and anti-piracy panels.
    void (*loadTexture)(void* user, uint32_t texture);
    int  (*textureReady)(void* user, uint32_t texture);
    void (*unloadTexture)(void* user, uint32_t texture);

    // cDBFileSys's constructor, which MemcardTester's calls (memcard.h):
    // the card's file system, or NULL for none. With no hook, or a NULL
    // answer, the card is memcard.c's blank one -- there, formatted, empty.
    BMemcardFileSys* (*newFileSys)(void* user);

    void (*sound)(void* user, int soundEvent);   // MakeFrontendSound
    void (*jukebox)(void* user, int start);      // sound::jukebox::Start/Stop
    // TheEasterEggs (0x0031d7e8), the port's name: retail's ELF has no
    // symbols, and the class is not on the demo disc. Start (0x0024f488)
    // gives it the pad's sixteen button events, 133..148, and Stop
    // (0x0024f610) takes them back. NewMainMenu's constructor and
    // destructor are its only callers. `start` is 1 for Start, 0 for Stop.
    void (*easterEggs)(void* user, int start);
    // NewMainMenu::HighlightMenuItem (0x00216880), the same pair bscreens.h
    // gives the menus it has classes for. moveBrackets is its
    // FlailerGetBoundingBox on the item's MI_n_MASK and the two SetTopLeftYs:
    // MI_UNDERSCORE to the box's bottom plus `under`, MI_OVERSCORE to its
    // top plus `over`. setBlurb is its tAnimatedBlurb::NewText.
    void (*moveBrackets)(void* user, uint32_t screen, uint32_t mask,
                         float under, float over);
    void (*setBlurb)(void* user, uint32_t screen, int blurbId);
    // StartDemoMode (0x0016ecd8): the attract race. It begins with
    // StopMovie, which the flow runs before the hook; the track it takes in
    // turn and Fred's demo race are the host's.
    void (*startDemoMode)(void* user);
    // TheDemoModeReplay (0x002f0960), a replay to show in attract mode.
    // ConsiderLaunching (0x0013f120) picks one and starts it loading,
    // returning 1, or returns 0 when the disc has none -- which is what no
    // hook answers. Launch (0x0013f1c0) plays the one that has loaded.
    // While one loads, the host keeps replayLoading (+4) and then
    // replayLoaded (+8) set in the flow.
    int  (*replayConsiderLaunching)(void* user);
    void (*replayLaunch)(void* user);

    // Transcript. Every observable step calls this, which is what
    // tools/bootflow_check.py diffs.
    void (*trace)(void* user, const char* line);
} BGameFlowHooks;

// ScreenStack (type#724, 388 bytes): twelve 32-byte names and an index.
// Push does not bound-check in the original; this one drops the push and
// says so in the transcript rather than running off the end.
typedef struct {
    char names[BGF_STACK_DEPTH][BGF_NAME_LEN];
    int  index;
} BScreenStack;

// TitleScreen, retail's (0x0016f000): 56 bytes, the demo's 20 plus the
// PRESS START delay at +20 and a tHighlightAnimation at +24. `playing` is
// the port's own: the original assumes MoviePlayer::InitFile always
// succeeds.
typedef struct {
    int            port;        // +4
    int            movieIndex;  // +8
    int            mode;        // +12: 1 = at rest on the title, 2 = a movie
    uint32_t       timer;       // +16: RealTimer at the last mode change
    // +20, a Timer: RealTimer when the title first came to rest. 0 or
    // 0x7fffffff is unset. PRESS START appears, and SELECT is taken, only
    // four seconds after it -- the "loading" pause the logo sits through.
    uint32_t       pressStart;
    BHighlightAnim highlight;   // +24: the bloom on PRESS START
    int            playing;     // a movie file is actually open
    // The port's trace, not the screen's state. HandleTick sets the
    // TITLE_IMAGE group and PRESS START on every tick and the bloom animates
    // on every tick at rest; the trace says so only when the answer changes,
    // or a minute on the title would be ten thousand lines of the same three.
    // -1 is "nothing traced yet".
    int            tracedRest;
    int            tracedReady;
    int            tracedAnimate;
} BTitleScreen;

// MumboJumboScreen (0x0016a8b0): state in +12, one plane whose texture is
// swapped. Dead on the retail build -- both its predicates return 0 -- but
// it is the shape every "show a picture for N seconds" screen here uses.
typedef struct {
    int      state;
    uint32_t timer;
} BMumboJumboScreen;

// LanguageOptionsScreenBase (0x001f1a78), 16 bytes: +12 is the vtable.
// `active` stands for pInstance (gp-16972) being set.
typedef struct {
    int      active;
    int      selected;      // +0: SelectedLanguage
    uint32_t flailer;       // +4: the Flailer screen, ACTIVATE's ItemHash
    int      fromOptions;   // +8: 0 before the frontend, 1 from Options
} BLanguageScreen;

// NewMainMenu, retail's (0x00216460): 636 bytes, of which the port holds
// only what it has ported. `active` stands for pInstance (gp-16132) being
// set, which Callback tests before it deletes.
typedef struct {
    int active;
} BNewMainMenu;

struct BGameFlow {
    const BGameFlowStateInfo* states;
    int                       numStates;
    const BScreenConfig*      screens;
    int                       numScreens;
    const BBootStage*         bootStages;
    int                       numBootStages;
    BGameFlowHooks            hooks;

    int current;      // CurrentGameFlowState, 0x0032362c
    int desired;      // DesiredGameFlowState, 0x00323630
    // PendingGameFlowState, 0x00323634. ServiceGameFlow never reads it;
    // BeginGameFlowUnloadingTrackSpecific does (trackflow.c).
    int pending;

    BScreenStack         stack;
    const BScreenConfig* screen;   // FlailerScreenList::pCurrent, +412
    // FlailerScreenList's panel movie. +460, PANELMOVIE's texture, is found
    // by StartMovie and forgotten by StopMovie, and is the gate all three
    // read; +484 is the file StartMovie was given, which StopMovie leaves.
    int         panelMovie;
    const char* panelMovieName;

    // AdvanceRealTime (0x00199410). `realTime` is 60 Hz ticks and advances
    // by at least 1 every frame; `realTimer` is in 1/4000 s units because
    // Timer::SetTime(float) (0x00134ef0) is (int)(f * 4000.0f).
    uint32_t realTime;
    uint32_t realTimer;
    // RealTimeElapsed (0x00323cdc), the frame's own delta in seconds. It is
    // a separate global from RealTimer because the spline integrator wants
    // the delta and everything else wants the running total; banim.c reads
    // both through banim_set_clock rather than starting a second clock.
    float    realElapsed;
    uint32_t frameCounter;
    float    accum;
    uint32_t beginScreenFadeTime;

    // The gp globals the boot flow reads, at the values the PS2 image ships
    // with. Nothing but UnlaunchFrontendMenus writes frontendLaunchType.
    int frontendLaunchType;   // 1
    int demoModeStatus;       // Fred.DemoModeStatus
    int skipFE;               // 0x00322f04, 0
    int skipMovies;           // 0x00322fbc, 0
    int videoMode;            // VIDEO_MODE: MODE_PAL = 0, MODE_NTSC = 1
    // TheLanguageManager (0x0031c1c8): +0 CurrLanguage, -1 until
    // LoadGlobalChunks sets English, and +20, the speech files are loaded.
    int currLanguage;
    int speechLoaded;
    int demoDiscActive;       // TheDemoDiscManager.bActive, always 0
    // DemoDiscManager::IsAttractMode (0x0012eaf0). Only read when the demo
    // disc is active, so dead on retail like the rest of the demo branch.
    int demoAttractMode;
    int logoFrench;           // gp-21404: the LOADING art is LOADING_FR
    int loadAllLanguages;     // gp-16016, MENUITEM_7 of the language screen
    int copsOn;               // 0x002f3fdc -- which of the two Mode Selects

    // Port-only. MumboJumboScreen::ShouldSeeLegalScreen (0x0016a648) and
    // ShouldSeeAntiPiracy (0x0016a650) are both `return 0` on the disc, so
    // the screen's timed states can never run. This turns them on, which is
    // the only way tools/bootflow_check.py can cover that shape -- and the
    // shape is worth covering, because every "show a picture for N seconds"
    // screen in the game is built the same way.
    int forceLegalScreens;

    float legalScreenTimeout;    // 0x00323710, 7.0f
    float antiPiracyTimeout;     // 0x00323714, 7.0f
    float beginDemoModeTimeout;  // 0x00322f78, 30.0f

    // The animation kit the title screen's bloom runs on -- bscreens.c's,
    // so that there is one RealTimer. NULL runs the title without it.
    BAnim*            anim;

    // FlailerScreenList's two popups (+392, +396), bpopup.h.
    BPopup            popups[BPOPUP_COUNT];

    // Fred (0x002fc050), the frontend's database, as the image the memory
    // card loads over: BMC_SAVE_SIZE bytes, the host's. NULL loads nothing.
    uint8_t*          fred;

    // TheDemoModeReplay's +4 and +8: a replay is loading, one has loaded.
    int               replayLoading;
    int               replayLoaded;

    BTitleScreen      title;
    BMumboJumboScreen mumbo;
    // BootAutoLoader::pInstance (gp-15084): `autoloadActive` is it being
    // set, which happens only once the constructor has returned.
    BBootAutoLoader   autoload;
    int               autoloadActive;
    // Port-only, like forceLegalScreens: the boot's loader in MANUAL mode,
    // the Options screen's, so its prompts can be driven before that screen
    // is ported.
    int               autoloadManual;
    BLanguageScreen   language;
    BNewMainMenu      mainMenu;
};

// ---------------------------------------------------------------- lifecycle

// Fills in the shipped defaults and wires up the three tables. `hooks` may
// be NULL. Does not start the flow; call bgf_change_state() for that, the
// way main() (0x0012da88) does.
void bgf_init(BGameFlow* gf,
              const BGameFlowStateInfo* states, int numStates,
              const BScreenConfig* screens, int numScreens,
              const BBootStage* bootStages, int numBootStages,
              const BGameFlowHooks* hooks);

// ChangeGameFlow (0x001680d8): two stores, no validation, no transition
// table. `pending` is recorded; ServiceGameFlow never reads it, and only
// BeginGameFlowUnloadingTrackSpecific does.
void bgf_change_state(BGameFlow* gf, int desired, int pending);

// LoadGlobalChunks (0x001682d0), the flow's part: from SetCurrLanguage(
// ENGLISH) to its one eDisplayFrame, which puts LOADING_TRACK up -- the
// first thing the game shows. InitializeEverything calls it before main
// asks for LOADING_FRONTEND, so the port calls it before bgf_change_state.
// The files it loads around that (GLOBALB, the three texture packs) are the
// host's to load: the LOADING art is in GLOBALB.BUN and DYNTEX.BIN.
void bgf_load_global_chunks(BGameFlow* gf);

// LanguageManager::SetCurrLanguage (0x00100818 -> 0x0021e0d0), with its
// tail (0x0021e1e0): the FE_<language>.BIN table, the speech files, and the
// French LOADING art (0x001681b0). The same language again does nothing.
void bgf_set_curr_language(BGameFlow* gf, int language);

// ServiceGameFlow (0x001680e8). Loops until the desired state stops moving,
// so a Begin or Loop that redirects is serviced in the same call and costs
// no frame. The OLD state's End runs before the NEW state's Begin.
void bgf_service(BGameFlow* gf);

// AdvanceRealTime (0x001a3500): both clocks and the frame counter.
void bgf_advance_time(BGameFlow* gf, float dt);

// One pass of MainLoop: advance the clocks, service, tick the current
// screen, service again. MainLoop calls ServiceGameFlow twice a frame
// (0x0012dc18 and 0x0012dc4c), once either side of the frame's work.
void bgf_frame(BGameFlow* gf, float dt);

const char* bgf_state_name(const BGameFlow* gf, int state);

// ------------------------------------------------------------- screen list

// FlailerScreenList::FindScreen (0x0016c8c8): a linear walk by name.
const BScreenConfig* bgf_find_screen(const BGameFlow* gf, const char* name);

// ChangeToScreen (0x0016c4c0). Hides and unactivates the current screen,
// optionally pushing its name so BACK returns to it, then activates `name`.
//
// A name that is NULL, empty or unregistered leaves the flow with NO current
// screen -- the outgoing one is unactivated either way. Callers that might
// pop to nothing test the name first; MoveToPreviousScreen does.
//
// Returns 1 if a screen is current afterwards.
int bgf_change_to_screen(BGameFlow* gf, const char* name, int pushCurrent);

// MoveToPreviousScreen (0x0016c670). With `sendBackButton`, the current
// screen gets SCREEN_BACK_BUTTON first and can veto by clearing `param` or
// silence the click by clearing `noise`; the sound is read back AFTER the
// callback, which is how the title screen swallows it. Then `n` names are
// popped and the last one becomes current. Returns 1 if it moved.
int bgf_move_to_previous_screen(BGameFlow* gf, int n, int sendBackButton,
                                int port);

// MoveBackScreen (0x00170320): MoveToPreviousScreen(n, 0, port -1). No
// SCREEN_BACK_BUTTON: this is how a screen leaves on its own -- BootAutoload
// when its job is done, the language screen once a language is chosen.
int bgf_move_back_screen(BGameFlow* gf, int n);

// The pad's BACK, FlailerScreenList::JoyHandler (0x0016cab0):
// MoveToPreviousScreen(1, 1, port). The screen hears SCREEN_BACK_BUTTON
// first and can veto the pop.
int bgf_back_button(BGameFlow* gf, int port);

// Sends a message to the current screen's callback. Returns 0 if there is
// no current screen or it has no callback.
int bgf_send(BGameFlow* gf, BScreenMessage msg, BScreenCallbackData* data);

// One pad/UI event for the current screen, with a fresh callback data block.
int bgf_screen_event(BGameFlow* gf, BScreenMessage msg, int port);

// The same, but carrying the hash of the menu item that was selected rather
// than the screen's own. FlailerMenu fills ScreenCallbackData::ItemHash from
// the MENUITEM_n object; a screen like NewMainMenu reads nothing else, so a
// caller that substitutes the screen hash gets a three-way test that can
// never match.
int bgf_menu_item_event(BGameFlow* gf, BScreenMessage msg, uint32_t itemHash,
                        int port);

// The menus' movie, which loops behind them in PANELMOVIE.
//
// StartMovie (0x0016ce30): nothing with SkipMovies set, or when `name` is
// the movie already started; another is stopped first. Then the player is
// closed, whatever it held, and the file opened. `name` is kept, not
// copied: every caller passes a literal.
void bgf_start_movie(BGameFlow* gf, const char* name);
// UpdateMovie (0x0016d028), from FlailerScreenList::Tick after the popups
// (bgf_frame). In a race it stops the movie. Otherwise it updates the
// player, and when that answers the movie is over opens the same file
// again: the loop, and for a file that is not there, a try every frame.
void bgf_update_movie(BGameFlow* gf);
// StopMovie (0x0016d0a0): with a movie started, closes the player.
void bgf_stop_movie(BGameFlow* gf);

// ------------------------------------------------------------ screen stack

void        bgf_push_screen(BGameFlow* gf, const char* name);  // 0x0016b418
const char* bgf_pop_screen(BGameFlow* gf);                     // 0x0016b438
void        bgf_reset_stack(BGameFlow* gf);                    // 0x0016b460
void        bgf_pop_screens(BGameFlow* gf, int n);             // 0x0016c768

// PopUntil (0x0016c7b8): pops while the top is neither empty nor `name`,
// leaving `name` itself on the stack.
void bgf_pop_until(BGameFlow* gf, const char* name);

// GetCurrentScreenNameFromStack (0x0016c860): the top, or "" when empty.
const char* bgf_stack_top(const BGameFlow* gf);

// ------------------------------------------------------------- boot flow

// LaunchFrontendMenus (0x0016f950): push every stage whose predicate passes,
// then enter the top of the stack -- which is the last one pushed.
void bgf_launch_frontend_menus(BGameFlow* gf);

// UnlaunchFrontendMenus (0x0016fa80), the mirror run when a race starts.
// Sets frontendLaunchType so a second visit skips the boot sequence.
void bgf_unlaunch_frontend_menus(BGameFlow* gf, int raceInProgress);

// The four predicates, all in Frontend.obj and all reading
// frontendLaunchType, which ships as 1.
int bgf_should_see_title_sequence(const BGameFlow* gf);      // 0x0016f940
int bgf_should_see_legal_mumbo_jumbo(const BGameFlow* gf);   // 0x0016f938
int bgf_should_see_language_select(const BGameFlow* gf);     // 0x0016f8c8
int bgf_should_see_autoload(const BGameFlow* gf);            // 0x0016f8a0

// ConsiderStartDemoMode (0x0016ed50): half a minute idle since `*timer`,
// or the demo disc in attract mode, starts the attract race -- through a
// replay, if one loads.
void bgf_consider_start_demo_mode(BGameFlow* gf, const uint32_t* timer);

// ------------------------------------------- the ten game flow state hooks

void bgf_begin_loading_frontend(BGameFlow* gf);       // 0x00168698
void bgf_loop_loading_frontend(BGameFlow* gf);        // 0x00168718
void bgf_end_loading_frontend(BGameFlow* gf);         // 0x001687a8
void bgf_begin_unloading_frontend(BGameFlow* gf);     // 0x00168830

// ---------------------------------------------------- the boot screens

// Retail's TitleScreen::Callback, 0x0016f440 (the demo's is 0x0016a590).
void bgf_title_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);
void bgf_mumbo_jumbo_callback(BGameFlow* gf, BScreenMessage msg,
                              BScreenCallbackData* data);     // 0x0016f810
void bgf_boot_autoload_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data);   // demo 0x00231488

// LanguageOptionsScreenBase::Callback (0x001f1dd8), for "Language Options
// Pre FE": the six languages on MENUITEM_1..6, and MENUITEM_7, Load All
// Languages, hidden. A language chosen, by SELECT or by BACK on its item,
// is set and the screen moves back. "Language Options", the same screen
// entered from Options, is LanguageOptionsScreen (0x001f1d70), which adds a
// slide-on animation; the port gives it the base class until that is
// ported.
void bgf_language_screen_callback(BGameFlow* gf, BScreenMessage msg,
                                  BScreenCallbackData* data);

// bStringHash of the three items NEW_MAIN_MENU defines, which are the three
// constants NewMainMenu::HandleEvent compares against.
#define BGF_ITEM_MENUITEM_1  0x52e039f3u   // "Hot Pursuit"
#define BGF_ITEM_MENUITEM_2  0x52e039f4u   // "World Racing"
#define BGF_ITEM_MENUITEM_3  0x52e039f5u   // "Options"
// bStringHash("MI_n_MASK") for the three, and the blurb OnHighlight
// (0x00216938) gives each: the LanguageIDs of the sentence under the menu.
#define BGF_MI_1_MASK        0x6e34e350u
#define BGF_MI_2_MASK        0x708a0bf1u
#define BGF_MI_3_MASK        0x72df3492u
#define BGF_BLURB_MENUITEM_1 10016
#define BGF_BLURB_MENUITEM_2 10015
#define BGF_BLURB_MENUITEM_3 10009
// The language screen's: MENUITEM_1..6 are the six languages in
// e_Languages order, MENUITEM_7 is Load All Languages.
#define BGF_ITEM_MENUITEM_6  0x52e039f8u
#define BGF_ITEM_MENUITEM_7  0x52e039f9u

// NewMainMenu::Callback, retail's (0x00216a10; the demo's is 0x00203a48).
void bgf_new_main_menu_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data);

// A screen the flow can name but that has no behaviour of its own yet:
// activates, draws, and leaves on BACK.
void bgf_plain_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);

// TitleMoviesToPlay (0x002f3770): eight language rows of two movies.
typedef struct {
    const char* name;
    int         letterboxed;   // picks the plane: 0 is 4:3, 1 is letterboxed
} BTitleMovie;

int                bgf_num_title_movies(const BGameFlow* gf);   // 0x0016eee0
const BTitleMovie* bgf_title_movie(const BGameFlow* gf, int i);  // 0x0016ee90
