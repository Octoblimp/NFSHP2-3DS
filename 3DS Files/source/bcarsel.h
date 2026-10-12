// bcarsel -- car select: retail's SelectCarScreen and CarSelector, the
// screen You're The Cop's Setup and every other race setup lead to, as
// logic and 2D (step 16, slice SC-1).
//
// What is ported, retail's addresses (SLES_507.31):
//
//   VisibleCar             0x00194250  a car the selector shows, its skin
//     SetSkin / NextSkin   0x001942d0 / 0x00194350, PrevSkin 0x00194380
//   VisibleCarSet          0x001944e8  the player's cars, sorted; the copy
//                                      0x001943d8, GetNextCar 0x001943a8,
//                                      GetPrevCar 0x001943c0
//   CarListSort            0x00194728  the order the thumbnails go in
//   the preload            0x00194898  each player's car on its way before
//                                      car select is entered (Fred's
//                                      0x00183ec0 jumps here); the unload
//                                      0x00194a00
//   InitSelectCarScreen    0x00194fa8  and CloseSelectCarScreen 0x00194fb0
//   the unlock popup       0x00194a88 .. 0x00194f30, retail's own class with
//                                      no name in the image: the "how to
//                                      unlock this car" box over a locked car
//   CarSelector            0x001950d0 .. 0x00198290
//   SelectCarScreen        0x00198420 .. 0x00198b00
//
// and from the frontend animation kit, privately, the two classes the
// selector keeps: feAlphaAnimation (0x00248360), a group's alphas saved and
// scaled, and AnimationGroup (0x00248568), a group slid along X on a
// spline. banim.c has the demo's AnimationGroup, whose saved position is a
// float pair and whose constructor differs; this is retail's.
//
// The car in 3D (SC-2c): each selector keeps its two FrontEndRenderingCars
// (fecar.c), the car and its reflection; the CARCOVER model, which both
// wear while the car is covered; the PLATFORM model, the turntable, drawn
// on each RENDER; and its SelectCarCameraMover (selcam.c). The Tick sets the
// camera, the cars' matrices (UpdateRenderingCarParameters) and the light
// (SetSelectCarLighting, elight.c). Retail's spotlights are dead: the
// BRUSHEDMETAL channels InitSpotlights copies are never read, and
// UpdateSpotlight is empty, so neither is ported.
//
// The nebula (SC-3d): one player's selector rings the turntable with 20
// emitters of XE_SelectCarNebula on FrameEffects, which UpdateNebula
// (0x001963b8) places each Tick and colours from blue to red-brown as the
// car shown is locked. FlailerScreenList::SetEmitterState (0x0016c3b0),
// which the destructor calls, is empty.
//
// The Flailer calls are flailer.c's own, so tools/carsel_check.py runs
// retail's code in mipsemu over the same FRONTB screens. The 3D calls go
// straight to fecar.c, selcam.c, emodel.c, elight.c and texturepack.c,
// each checked on its own; everything else goes out through BCarSelHooks.
// Written up in docs/formats/car-select.md.

#ifndef BCARSEL_H
#define BCARSEL_H

#include <stdint.h>

#include "banim.h"
#include "blist.h"
#include "bmenu.h"
#include "bpopup.h"
#include "car.h"
#include "fecar.h"
#include "fred.h"
#include "scenery.h"
#include "selcam.h"

// The two FlailerScreenConfigs' hashes: one player's, and the two-player
// screen, which is entered once a pad. 0x18dc8e53 is a third layout the
// swatches and the thumbnails know; no config on the disc names it.
#define BCARSEL_SCREEN_1P        0xb5074ab4u   // "Select Car"
#define BCARSEL_SCREEN_2P        0x18dc8e52u   // "Select Car2P"
#define BCARSEL_SCREEN_2P_LOWER  0x18dc8e53u

// The one menu item the screen has, which SELECT goes through.
#define BCARSEL_ITEM_CHOOSE      0x52e039f3u

// JoyEvents 33 .. 43 (joyeventid.h), the ones the selector registers for.
#define BCARSEL_JOY_CHANGE_MODE     33
#define BCARSEL_JOY_UNLOCK          34
#define BCARSEL_JOY_ORBIT_LEFT      35
#define BCARSEL_JOY_ORBIT_RIGHT     36
#define BCARSEL_JOY_ORBIT_UP        37
#define BCARSEL_JOY_ORBIT_DOWN      38
#define BCARSEL_JOY_ORBIT_IN        39
#define BCARSEL_JOY_ORBIT_OUT       40
#define BCARSEL_JOY_ORBIT_LEFTRIGHT 41
#define BCARSEL_JOY_ORBIT_UPDOWN    42
#define BCARSEL_JOY_ORBIT_INOUT     43

#define BCARSEL_MAX_CARS     64
#define BCARSEL_MAX_SWATCHES 10
#define BCARSEL_MAX_SELECTORS 2
#define BCARSEL_MAX_NEBULA   64            // the array's room; 20 are made

// gp-23120, AllCarsAvailableInCarSelectScreen: 0 on the disc. Set, the
// hidden cars are listed too.
extern int32_t AllCarsAvailableInCarSelectScreen;

// ------------------------------------------------------------ the hooks

// Everything the selector does outside the Flailer and its own state.
// Every hook is optional: a missing one does nothing and answers 0 (or,
// for the strings, "").
typedef struct BCarSelHooks {
    void* user;

    // GetTranslatedString(int) (0x0021e560) and the by-name one
    // (0x0021e508), which answers the string itself when it is not in the
    // table. The answer may be overwritten by the next call; the selector
    // copies what it keeps.
    const char* (*translate)(void* user, int32_t id);
    const char* (*translateString)(void* user, const char* s);

    // MakeFrontendSound (0x0016e038) and StopFrontendSound.
    void (*sound)(void* user, int32_t event);
    void (*stopSound)(void* user, int32_t event);

    // SetHelpOverride (0x0016d448): `lines` 0-terminated, or NULL.
    void (*setHelpOverride)(void* user, const int32_t* lines);
    // CanEnterOrbitMode's first test: the help menu is up.
    int (*helpMenuActive)(void* user);

    // FlailerScreenList::SummonPopup and DismissPopup (bpopup.c): the
    // popup's index, or -1. The selector fills everything but `parent`.
    int (*summonPopup)(void* user, BPopupConfig* cfg);
    void (*dismissPopup)(void* user, int popup);

    // ChangeToScreen (0x0016cad0) and FrontendDatabase::StartRace
    // (0x00184f68), MaybeContinueToNextScreen's two ways on.
    void (*changeToScreen)(void* user, const char* name, int push);
    void (*startRace)(void* user);

    // TheCarLoader (0x0031ba38): InFrontEndFlag and RoundRobinFlag set,
    // Load, IsLoaded (`requested` 0), Unload and BeginLoading(NULL), each
    // on a RideInfo::Init(type, -1, 0, 0).
    void (*loaderFrontEnd)(void* user);
    void (*loaderLoad)(void* user, const RideInfo* ri);
    int (*loaderIsLoaded)(void* user, const RideInfo* ri);
    void (*loaderUnload)(void* user, const RideInfo* ri);
    void (*loaderBeginLoading)(void* user);

    // The easter eggs' test (0x0024f8f8 on TheEasterEggs): a car the egg
    // makes available. `copsOnly` is You're The Cop's player one.
    int (*eggActive)(void* user, int32_t carType, int copsOnly);

    // FormatUnlockBlurbForCar (0x0024b548): how the car is unlocked, into
    // buf. A missing hook leaves retail's last answer, "This car should be
    // unlocked".
    void (*formatUnlockBlurb)(void* user, char* buf, int len,
                              int32_t carType, int32_t gameType,
                              int flag);
    // FlailerRenderManager::RenderTextIntoRectangle (0x001451e0): `text`
    // wrapped into the rectangle `rect`, in `object`'s font.
    void (*renderTextIntoRectangle)(void* user, uint32_t screen,
                                    uint32_t object, uint32_t rect,
                                    const char* text, float scale);

    // The commentary: EnterOrbitMode's line about the car (speech
    // events 211 for a cop and 146 for the rest, by ConvertCarType), and
    // speech::mgr_t::fade.
    void (*speakCar)(void* user, int32_t carType, int cop, int hp);
    void (*speechFade)(void* user, float level);
    // gp-23056, SoundEnabled, and the language (0 English).
    int (*soundEnabled)(void* user);
    int32_t (*language)(void* user);

    // 0x0016caa8: the screen list's per-pad press filter, on while two
    // players choose at once.
    void (*setPerPortJoy)(void* user, int on);
    // FlailerScreenList::StopMovie, from SelectCarScreen's constructor.
    void (*stopMovie)(void* user);

    void (*trace)(void* user, const char* line);
} BCarSelHooks;

// ------------------------------------------------------------ the cars

// VisibleCar, 32 bytes in retail: a node and the car.
typedef struct VisibleCar {
    bNode       node;        //  0
    CarStatus*  status;      //  8  the player's aCarStatus[type]
    int32_t     type;        // 12
    int32_t     available;   // 16
    int32_t     skinIndex;   // 20  into status->aSkins
    uint32_t    thumbHash;   // 24  "THUMBNAIL_" + CarTypeName
    int32_t     carIndex;    // 28  its place in the sorted list
} VisibleCar;

// VisibleCarSet, 20 bytes in retail and its cars from bMalloc. The port
// keeps the cars in the set, one slot a car type, so a set is one block
// and a copy is a copy of the list's order.
typedef struct VisibleCarSet {
    VisibleCar* current;     //  0
    int32_t     total;       //  4
    int32_t     unlocked;    //  8
    bNode       list;        // 12
    int32_t     used;        // the port's: slots taken
    VisibleCar  cars[BCARSEL_MAX_CARS];
} VisibleCarSet;

void bcarsel_set_init(VisibleCarSet* s, const BCarSelHooks* h,
                      FrontendPlayerInfo* player, int copsOnly);
void bcarsel_set_copy(VisibleCarSet* d, const VisibleCarSet* s);
VisibleCar* bcarsel_next_car(VisibleCarSet* s, VisibleCar* c);
VisibleCar* bcarsel_prev_car(VisibleCarSet* s, VisibleCar* c);

// ------------------------------------------------------- the selector

// feAlphaAnimation: a group's elements, each with its four alphas saved.
// Retail's list has no bound; FRONTB's largest group is 103 objects (fade
// group A on the lower half of two players).
#define BCARSEL_MAX_FADE 128

typedef struct BCarSelFade {
    uint32_t screen;
    int32_t  count;
    struct {
        struct FlailerObjectChunk* obj;
        float alpha[4];
    } el[BCARSEL_MAX_FADE];
} BCarSelFade;

// Retail's AnimationGroup: +8 screen, +12 group, +16 master, +20 and +24
// the master's top left as ints, +28 the spline.
typedef struct BCarSelSlide {
    uint32_t screen, group, master;
    int32_t  savedX, savedY;
    BSpline  spline;
} BCarSelSlide;

// The unlock popup, 360 bytes in retail.
typedef struct BCarSelUnlock {
    VisibleCar*  car;          //   0
    uint32_t     screen;       //   4
    float        x;            //   8  the box's resting X
    int32_t      alpha;        //  12  the box's alpha as laid out
    BCarSelSlide slide;        //  16
    char         blurb[256];   //  92
    int32_t      start;        // 348  RealTimer when it last slid on
    int32_t      state;        // 352  0 none, 1 hidden, 2 shown
    int32_t      hide;         // 356  RealTimer when it was hidden
} BCarSelUnlock;

// CarSelector, 1024 bytes in retail. The offsets are retail's. Retail
// bMallocs the two rendering cars and the camera mover and keeps
// pointers; the port keeps them in place.
typedef struct CarSelector {
    VisibleCarSet set;          //   0
    int32_t     port;           //  20
    int32_t     twoPlayer;      //  24
    int32_t     playerNum;      //  28  1 or 2, the cars' and camera's view
    uint32_t    screen;         //  32
    FrontEndRenderingCar car;        //  36
    FrontEndRenderingCar reflection; //  40  Reflection 1
    eModel      cover;          //  44  CARCOVER, both cars' while covered
    int32_t     fadeMax;        //  68  130
    int32_t     fade;           //  72  the black over the car
    int32_t     allUnlocked;    //  76
    VisibleCar* loaded;         //  80
    VisibleCar* pending;        //  84
    float       chooseMode;     //  88  0
    float       orbitMode;      //  92  1
    float       shownMode;      //  96  moves toward mode by 0.03
    float       mode;           // 100
    int32_t     orbitFrame;     // 104
    int32_t     orbitTouched;   // 108
    int32_t     state;          // 112  0 choosing, 1 gearbox, 2 handling,
                                //      3 waiting for the other player
    int32_t     popup;          // 116
    int32_t     transmission;   // 120  0 automatic, 1 manual, 2 ...
    int32_t     handling;       // 124
    BCarSelFade fadeA;          // 128  0x0015678f, out as orbit comes in
    BCarSelFade fadeB;          // 140  0x036e80bf, in with orbit
    BCarSelFade fadeC;          // 152  0x0961a600
    eModel      platform;       // 164  PLATFORM, the turntable
    SelectCarCameraMover mover; // 188
    // 192 .. 216: four words the turntable's start sets and nothing reads.
    uint16_t    turnTilt;       // 224
    uint16_t    turnFOV;        // 226
    uint16_t    turnAngle;      // 228  the turntable, 46 a frame
    int32_t     nSwatches;      // 232
    uint32_t    swatchHash[BCARSEL_MAX_SWATCHES];    // 236
    uint32_t    swatchColour[BCARSEL_MAX_SWATCHES];  // 276
    // 316 .. 328: the spotlights' two buffers and two 1.0s, unread.
    BSpline     thumbs;         // 332  the thumbnail row's X
    int32_t     headlights;     // 380  the cars' Headlights and CopLights:
    int32_t     copLights;      // 384  0 from the constructor on
    struct AcidEmitter* nebula[BCARSEL_MAX_NEBULA]; // 388
    int32_t     nNebula;        // 644  20, or 0 for two players
    float       nebulaLocked;   // 648  0 blue .. 1 a locked car's red
    BCarSelUnlock unlock;       // 652
    const BCarSelHooks* hooks;
} CarSelector;

// ------------------------------------------------------ the screen

typedef struct SelectCarScreen {
    int32_t      count;
    CarSelector* selectors[BCARSEL_MAX_SELECTORS];
} SelectCarScreen;

// The module: the hooks, the screen (pSelectCarScreen, gp-19968) and the
// preload's two cached car types (gp-20104 and gp-20100).
typedef struct BCarSel {
    BCarSelHooks     hooks;
    SelectCarScreen* screen;
    int32_t          preloaded[2];
} BCarSel;

void bcarsel_init(BCarSel* m, const BCarSelHooks* hooks);

// The ScreenCallback both "Select Car" and "Select Car2P" register.
// SelectCarScreen::SelectCarScreenCallback (0x00198928).
void bcarsel_screen_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data);

// 0x00194898 (Fred's 0x00183ec0): each player's first car loading before
// car select is entered. And InitSelectCarScreen / CloseSelectCarScreen,
// at the frontend's load and unload; Close also unloads the preload.
// Init only jumps to InitSpotlights, whose copies of BRUSHEDMETAL nothing
// reads, so it is empty.
void bcarsel_preload(void);
void bcarsel_init_screen(void);
void bcarsel_close_screen(void);

// Whether a selector is up (IsCarSelectScreenActive, 0x00198418).
int bcarsel_active(void);

#endif
