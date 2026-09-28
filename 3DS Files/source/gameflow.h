#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "banim.h"
#include "bmenu.h"

// The boot flow: main() to the main menu.
//
// This is the port of two mechanisms that between them get the PS2 game from
// its entry point to "New Main Menu", decompiled in docs/formats/boot-flow.md
// with an address for every rule here.
//
//  * GameFlowStateInfoTable (0x002f2eb0) and ServiceGameFlow (0x001636f8):
//    ten states, each with an optional Begin/End/Loop, serviced in a loop
//    until the desired state stops moving.
//  * LaunchFrontendMenus (0x0016aa40) and FlailerScreenList: a LIFO of
//    screen names that the boot fills backwards and immediately pops.
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

#define BGF_TEX_LEGAL             0xa7ebc389u  // both out of GLOBAL\DYNTEX.BIN
#define BGF_TEX_ANTIPIRACY        0x38258033u

typedef struct BGameFlow BGameFlow;

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
typedef struct {
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

    // The UI layer: a screen became current, or stopped being current. This
    // is where a port builds its BMenu and starts drawing. Both fire after
    // the matching message, not before: the screen is live for the whole of
    // enterScreen..leaveScreen, so the menu's opening highlight lands on a
    // screen that exists. See bgf_change_to_screen.
    void (*enterScreen)(void* user, const BScreenConfig* cfg);
    void (*leaveScreen)(void* user, const BScreenConfig* cfg);

    // MoviePlayer. `open` returns 0 if the file is not there, which on this
    // disc is the normal case for the second title movie -- see gameflow.c.
    // `drive` returns 1 when the movie has finished.
    int  (*movieOpen)(void* user, const char* path);
    int  (*movieDrive)(void* user);
    void (*movieClose)(void* user);

    // LoadResourceFile / IsResourceLoadingComplete, and the language.
    void (*loadResource)(void* user, const char* path);
    int  (*resourcesReady)(void* user);
    void (*setLanguage)(void* user, int language);

    // pDynamicTexturePack, for the legal and anti-piracy panels.
    void (*loadTexture)(void* user, uint32_t texture);
    int  (*textureReady)(void* user, uint32_t texture);
    void (*unloadTexture)(void* user, uint32_t texture);

    // BootAutoLoader's memory card, which the 3DS does not have. `poll`
    // returns 1 when the save job has finished.
    void (*saveStart)(void* user);
    int  (*savePoll)(void* user);

    void (*sound)(void* user, int soundEvent);   // MakeFrontendSound
    void (*jukebox)(void* user, int start);      // sound::jukebox::Start/Stop
    void (*startDemoMode)(void* user);           // attract mode

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

// BootAutoLoader (0x00231370): 1 loading, 2 saving, 0 done.
typedef struct {
    int state;
    int port;
} BBootAutoLoader;

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
    int currLanguage;         // TheLanguageManager.CurrLanguage, -1 = unset
    int demoDiscActive;       // TheDemoDiscManager.bActive, always 0
    // DemoDiscManager::IsAttractMode (0x0012eaf0). Only read when the demo
    // disc is active, so dead on retail like the rest of the demo branch.
    int demoAttractMode;
    int needToSetLanguage;
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

    BTitleScreen      title;
    BMumboJumboScreen mumbo;
    BBootAutoLoader   autoload;
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

// ChangeGameFlow (0x001636e8): two stores, no validation, no transition
// table. `pending` is recorded; ServiceGameFlow never reads it, and only
// BeginGameFlowUnloadingTrackSpecific does.
void bgf_change_state(BGameFlow* gf, int desired, int pending);

// ServiceGameFlow (0x001636f8). Loops until the desired state stops moving,
// so a Begin or Loop that redirects is serviced in the same call and costs
// no frame. The OLD state's End runs before the NEW state's Begin.
void bgf_service(BGameFlow* gf);

// AdvanceRealTime (0x00199410): both clocks and the frame counter.
void bgf_advance_time(BGameFlow* gf, float dt);

// One pass of MainLoop: advance the clocks, service, tick the current
// screen, service again. MainLoop calls ServiceGameFlow twice a frame
// (0x0012dc18 and 0x0012dc4c), once either side of the frame's work.
void bgf_frame(BGameFlow* gf, float dt);

const char* bgf_state_name(const BGameFlow* gf, int state);

// ------------------------------------------------------------- screen list

// FlailerScreenList::FindScreen (0x00167c58): a linear walk by name.
const BScreenConfig* bgf_find_screen(const BGameFlow* gf, const char* name);

// ChangeToScreen (0x00167850). Hides and unactivates the current screen,
// optionally pushing its name so BACK returns to it, then activates `name`.
//
// A name that is NULL, empty or unregistered leaves the flow with NO current
// screen -- the outgoing one is unactivated either way. Callers that might
// pop to nothing test the name first; MoveToPreviousScreen does.
//
// Returns 1 if a screen is current afterwards.
int bgf_change_to_screen(BGameFlow* gf, const char* name, int pushCurrent);

// MoveToPreviousScreen (0x00167a00). With `sendBackButton`, the current
// screen gets SCREEN_BACK_BUTTON first and can veto by clearing `param` or
// silence the click by clearing `noise`; the sound is read back AFTER the
// callback, which is how the title screen swallows it. Then `n` names are
// popped and the last one becomes current. Returns 1 if it moved.
int bgf_move_to_previous_screen(BGameFlow* gf, int n, int sendBackButton,
                                int port);

// MoveBackScreen (0x0016b220): MoveToPreviousScreen(n, 1, port 0).
int bgf_move_back_screen(BGameFlow* gf, int n);

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

// ------------------------------------------------------------ screen stack

void        bgf_push_screen(BGameFlow* gf, const char* name);  // 0x00166780
const char* bgf_pop_screen(BGameFlow* gf);                     // 0x001667a0
void        bgf_reset_stack(BGameFlow* gf);                    // 0x001667c8
void        bgf_pop_screens(BGameFlow* gf, int n);             // 0x00167af8

// PopUntil (0x00167b48): pops while the top is neither empty nor `name`,
// leaving `name` itself on the stack.
void bgf_pop_until(BGameFlow* gf, const char* name);

// GetCurrentScreenNameFromStack (0x00167bf0): the top, or "" when empty.
const char* bgf_stack_top(const BGameFlow* gf);

// ------------------------------------------------------------- boot flow

// LaunchFrontendMenus (0x0016aa40): push every stage whose predicate passes,
// then enter the top of the stack -- which is the last one pushed.
void bgf_launch_frontend_menus(BGameFlow* gf);

// UnlaunchFrontendMenus (0x0016ab70), the mirror run when a race starts.
// Sets frontendLaunchType so a second visit skips the boot sequence.
void bgf_unlaunch_frontend_menus(BGameFlow* gf, int raceInProgress);

// The four predicates, all in Frontend.obj and all reading
// frontendLaunchType (0x00323724, ships as 1).
int bgf_should_see_title_sequence(const BGameFlow* gf);      // 0x0016aa30
int bgf_should_see_legal_mumbo_jumbo(const BGameFlow* gf);   // 0x0016aa28
int bgf_should_see_language_select(const BGameFlow* gf);     // 0x0016a9b8
int bgf_should_see_autoload(const BGameFlow* gf);            // 0x0016a990

// ConsiderStartDemoMode (0x00169f98): half a minute idle on PRESS START.
void bgf_consider_start_demo_mode(BGameFlow* gf, uint32_t since);

// ------------------------------------------- the ten game flow state hooks

void bgf_begin_loading_frontend(BGameFlow* gf);       // 0x00163ad8
void bgf_loop_loading_frontend(BGameFlow* gf);        // 0x00163b78
void bgf_end_loading_frontend(BGameFlow* gf);         // 0x00163c58
void bgf_begin_unloading_frontend(BGameFlow* gf);     // 0x00163cc8

// ---------------------------------------------------- the boot screens

// Retail's TitleScreen::Callback, 0x0016f440 (the demo's is 0x0016a590).
void bgf_title_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);
void bgf_mumbo_jumbo_callback(BGameFlow* gf, BScreenMessage msg,
                              BScreenCallbackData* data);     // 0x0016a8b0
void bgf_boot_autoload_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data);   // 0x00231488

// bStringHash of the three items NEW_MAIN_MENU defines, which are the three
// constants NewMainMenu::HandleEvent compares against.
#define BGF_ITEM_MENUITEM_1  0x52e039f3u   // "Hot Pursuit"
#define BGF_ITEM_MENUITEM_2  0x52e039f4u   // "World Racing"
#define BGF_ITEM_MENUITEM_3  0x52e039f5u   // "Options"

void bgf_new_main_menu_callback(BGameFlow* gf, BScreenMessage msg,
                                BScreenCallbackData* data);   // 0x00203a48

// A screen the flow can name but that has no behaviour of its own yet:
// activates, draws, and leaves on BACK. "Language Options Pre FE" uses it
// until its own class is ported.
void bgf_plain_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);

// TitleMoviesToPlay (0x002f3770): eight language rows of two movies.
typedef struct {
    const char* name;
    int         letterboxed;   // picks the plane: 0 is 4:3, 1 is letterboxed
} BTitleMovie;

int                bgf_num_title_movies(const BGameFlow* gf);   // 0x0016a130
const BTitleMovie* bgf_title_movie(const BGameFlow* gf, int i);  // 0x0016a0e0
