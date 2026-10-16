// banim -- the Flailer frontend's animation layer.
//
// bscreens.c decides *what* moves when a menu item is highlighted or
// selected. This decides *when it gets there*. Without it every change is
// instant: brackets teleport, items appear already in place, and a screen
// that is supposed to slide its items off before changing changes on the
// frame the button went down.
//
// Eight classes out of the ELF, all in one object file there and all small:
//
//   tCubic1D      (fields in .mdebug)      the easing curve, a cubic Hermite
//   AnimationGroup   0x00232010            one object or group moving in X
//   tSlideAnimation  0x00232660            up to ten groups, staggered
//     tSlideInAnimation  0x00232a48        ... arriving from off the right
//     tSlideOutAnimation 0x00232958        ... leaving to off the right
//       tExitScreenAnimation 0x00232b50    ... and then changing screen
//   tHighlightAnimation 0x00232318         the bloom on the selected item
//   tAnimatedBlurb      0x00232c18         the one-line description
//   feAnimAlphaElement  0x00231ba8         fade a Flailer object by a factor
//   SelectionSet        0x00169358         which MI_n_MASK is uncovered
//
// Written up in docs/formats/frontend-animation.md. Nothing here includes
// <3ds.h>: every Flailer operation goes out through BAnimHooks, so
// tools/src/banim_test.c can run the same code on the host and
// tools/banim_check.py can check it against an independent model.
#ifndef BANIM_H
#define BANIM_H

#include <stdint.h>

#include "bvector.h"

// ---------------------------------------------------------------- the world

// FlailerObjectType, as FindFlailerObject takes it: 0 matches any type.
enum {
    BANIM_TYPE_ANY    = 0,
    BANIM_TYPE_TEXT   = 1,
    BANIM_TYPE_BITMAP = 2
};

typedef struct BAnimHooks {
    void* user;

    // FindFlailerObject (0x001419c8). Non-zero if the screen has an object
    // with that hash; the animation layer only ever asks whether it exists.
    int (*objectExists)(void* user, uint32_t screen, uint32_t object,
                        int type);
    // FindFlailerObjectByGroup (0x00141a50) with a null "after" pointer:
    // non-zero if ANY object on the screen carries that GroupHash. This is
    // a different question from objectExists, and the slide animations ask
    // only this one -- MENUITEM_3_GROUP is a group, never an object name.
    int (*groupExists)(void* user, uint32_t screen, uint32_t group,
                       int type);
    // FlailerObjectChunk::Type, for the one place it matters: a bitmap has
    // four corner alphas and everything else has one. See BAnimAlpha.
    int (*objectType)(void* user, uint32_t screen, uint32_t object);

    // FlailerGetTopLeftPosition / FlailerSetTopLeftPosition (0x00141d28,
    // 0x00141fe8). A missing object reads back (0, 0) and ignores writes.
    void (*getTopLeft)(void* user, uint32_t screen, uint32_t object,
                       float* x, float* y);
    void (*setTopLeft)(void* user, uint32_t screen, uint32_t object,
                       float x, float y);

    // FlailerSetGroupPosition (0x001d7018): put `master` at (x, y) and move
    // every object whose GroupHash is `group` by the same delta. The master
    // is the reference point; it moves too only if it is in the group.
    void (*setGroupPos)(void* user, uint32_t screen, uint32_t group,
                        uint32_t master, float x, float y);

    // FlailerObjectChunk::SetVisibility (0x0013e2a8). 0 invisible, 1 visible
    // -- the FlailerObjectVisibility order, not the screen enum's.
    void (*setVisible)(void* user, uint32_t screen, uint32_t object,
                       int visible);

    // FlailerBitmapChunk::GetAlpha/SetAlpha (0x0013efa8, 0x0013ed50) for a
    // bitmap corner, FlailerObjectChunk::GetAlpha/SetAlpha (0x0013e098,
    // 0x0013ea48) otherwise -- in which case `corner` is 0 and ignored.
    int  (*getAlpha)(void* user, uint32_t screen, uint32_t object,
                     int corner);
    void (*setAlpha)(void* user, uint32_t screen, uint32_t object,
                     int corner, int alpha);

    // Text objects. `setLanguageID` is FlailerSetLanguageID (0x001425f8),
    // `printText` is FlailerPrintf with a bare "%s" (0x00141ae8), `copyText`
    // is CopyFlailerText (0x0013ec18) -- src's string into dst.
    void (*setLanguageID)(void* user, uint32_t screen, uint32_t object,
                          int languageID);
    void (*printText)(void* user, uint32_t screen, uint32_t object,
                      const char* s);
    void (*copyText)(void* user, uint32_t screen, uint32_t dst,
                     uint32_t src);
    // FlailerTextChunk::ScaleAboutCenter (0x0013eb20) and SetColor
    // (0x0013e820); FlailerGetScale (0x00142138) reads the authored scale.
    void (*scaleAboutCenter)(void* user, uint32_t screen, uint32_t object,
                             float scale);
    void (*setColor)(void* user, uint32_t screen, uint32_t object,
                     uint32_t color);
    void (*getScale)(void* user, uint32_t screen, uint32_t object,
                     float* sx, float* sy);

    // The four reads tPopupMenu needs (bpopup.c); addresses are retail's.
    // `nextInGroup` is FindFlailerObjectByGroup (0x00143dd8) walked:
    // `after` is -1 to start, or what the last call returned, and the answer
    // is a handle on the next object of `type` whose GroupHash is `group`,
    // in the screen's file order, or -1. `*hash` gets that object's name.
    int32_t (*nextInGroup)(void* user, uint32_t screen, uint32_t group,
                           int type, int32_t after, uint32_t* hash);
    // FlailerTextChunk's MaxChars (+84) and GetScaledHeight (0x00140cd8):
    // ScaleY times the font's height, the height truncated to an int
    // first. 0 for a missing object or font.
    int   (*textMaxChars)(void* user, uint32_t screen, uint32_t object);
    float (*textScaledHeight)(void* user, uint32_t screen, uint32_t object);
    // FlailerObjectChunk's Color (+92), what FlailerMenuItem saves. 0 for a
    // missing object.
    uint32_t (*getColor)(void* user, uint32_t screen, uint32_t object);

    // GetTranslatedString (0x0020b0e0), for the blurb's NewText(int).
    const char* (*translate)(void* user, int languageID);

    // ChangeToScreen (0x0014a438), for tExitScreenAnimation.
    void (*changeToScreen)(void* user, const char* name, int pushCurrent);

    // FlailerSetScreenVisibility (0x0016eb68), for tSlideOnScreen: 1 shows
    // the screen and 0 hides it, the port's order -- FlailerScreenVisibility
    // has VISIBLE at 0.
    void (*setScreenVisible)(void* user, uint32_t screen, int visible);

    // Optional. Every state change the layer makes goes through here, which
    // is what the cross-check reads.
    void (*trace)(void* user, const char* line);
} BAnimHooks;

// The two clocks the original keeps as globals: RealTimer (0x00323cd0), an
// int counting 1/4000 s, and RealTimeElapsed (0x00323cdc), the frame's own
// delta in seconds. Timer::SetTime (0x00134ef0) is (int)(f * 4000.0f), so
// at 60 fps the counter gains 66 a frame and the elapsed float is 1/60.
#define BANIM_TICKS_PER_SEC 4000.0f

typedef struct BAnim {
    BAnimHooks hooks;
    int32_t    timer;     // RealTimer
    float      elapsed;   // RealTimeElapsed
} BAnim;

void banim_init(BAnim* a, const BAnimHooks* hooks);
// One frame, when banim owns the clock: `dt` is seconds and the tick counter
// takes (int)(dt * 4000), the same rounding AdvanceRealTime (0x00199410)
// does. The host harness uses this.
void banim_tick(BAnim* a, float dt);
// One frame, when something else already keeps RealTimer -- which in this
// port is gameflow.c. Both are one global each in the original, so the two
// must not be allowed to drift apart into two clocks.
void banim_set_clock(BAnim* a, int32_t timer, float elapsed);

// ------------------------------------------------------------- tCubic1D

// The easing curve, 48 bytes in the original and field-for-field here.
// State is 0 idle, 1 running, 2 "a new seek was asked for, rebuild the
// coefficients on the next step".
typedef struct BSpline {
    float   val, dval;
    float   valDesired, dvalDesired;
    float   coeff[4];
    float   time;               // normalised, 0..arrivalThreshold
    float   duration;           // seconds
    float   arrivalThreshold;
    int16_t state, flags;
} BSpline;

// MakeCoeffs (0x001d0048): the Hermite basis, written so that GetVal(0) is
// Val, GetVal(1) is ValDesired and both derivatives match at the ends.
void  bspline_make_coeffs(BSpline* s);
float bspline_get_val(const BSpline* s, float t);
float bspline_get_dval(const BSpline* s, float t);
// SplineSeek (0x001d0790) for the cPoint/tCubic1D overload, minus the two
// clamps: its only caller in the frontend passes 0 for both limits, so
// ClampDerivative (0x001d0198) and ClampSecondDerivative (0x001d01f8) never
// run. They are not ported; port them here if a caller ever passes one --
// and read 0x001d0818 first, because the guard tests the third argument
// while the call one instruction later passes the second.
void  bspline_seek(BSpline* s, float dt);
// GetddVal, retail's 0x001da830: the curve's second derivative in its own
// parameter, `a * (t * 6) + (b + b)`. The BeltMover is its one caller, and
// throws the answer away.
float bspline_get_ddval(const BSpline* s, float t);

// ------------------------------------------------------------- tCubic2D

// Two tCubic1Ds, x at 0 and y at 48: 96 bytes in the original. The
// BeltMover's two are its only users. Retail's addresses: SetVal
// 0x001daa00, SetdVal 0x001daa50, SetValDesired 0x001daaa0, GetVal
// 0x001dab38, GetdVal 0x001dab50 and cPoint::SplineSeek(tCubic2D *, float)
// 0x001db000. Each setter stores both lanes and marks a lane for a new seek
// (state 2) when the value it stored differs from that lane's partner:
// SetVal and SetdVal test against the desired values, SetValDesired against
// the current one. The seek is the tCubic1D one on x, then on y, both with
// their clamps at 0 -- which is bspline_seek.
typedef struct BSpline2D {
    BSpline x;
    BSpline y;
} BSpline2D;

void bspline2d_set_val(BSpline2D* s, const bVector2* v);
void bspline2d_set_dval(BSpline2D* s, const bVector2* v);
void bspline2d_set_val_desired(BSpline2D* s, const bVector2* v);
void bspline2d_get_val(const BSpline2D* s, bVector2* out);
void bspline2d_get_dval(const BSpline2D* s, bVector2* out);
void bspline2d_seek(BSpline2D* s, float dt);

// ---------------------------------------------------------- AnimationGroup

typedef struct BAnimGroup {
    uint32_t screen;
    uint32_t group;      // 0 moves the master alone
    uint32_t master;
    float    savedX, savedY;
    BSpline  spline;
} BAnimGroup;

// The two constructors, 0x00232010 (with a group) and 0x002320d0 (without).
// Both read the master's authored position first, so the Y the group is
// pinned to is whatever the bundle says: only X animates.
void  banim_group_init(BAnim* a, BAnimGroup* g, uint32_t screen,
                       uint32_t group, uint32_t master,
                       float start, float end, float duration);
// SetupToAnimate (0x00232190): jump to `start`, then seek to `end`.
void  banim_group_setup(BAnim* a, BAnimGroup* g, float start, float end);
int   banim_group_finished(const BAnimGroup* g);
void  banim_group_animate(BAnim* a, BAnimGroup* g);
float banim_group_desired_x(const BAnimGroup* g);
// ~AnimationGroup (0x00232228): puts the objects back where they started.
// The original frees the node here too; the port owns the storage, so this
// is only the restore.
void  banim_group_release(BAnim* a, BAnimGroup* g);

// -------------------------------------------------------- tSlideAnimation

// The loop in both subclasses runs i = 0..9 and asks the screen whether
// MENUITEM_<i>_GROUP exists, so ten is the ceiling there. The eleventh is
// UNDERSCORE_GROUP, which CopsOn/CopsOffModeSelect::StartChangeToScreen
// (0x00203ec8, 0x00204570) append to the exit animation so the two
// selection brackets leave with the items.
#define BANIM_SLIDE_SLOTS 10
#define BANIM_MAX_GROUPS  11

// TimeStarted is the whole state: 0 is "built but never started" and
// 0x7fffffff is "stopped". HasControl is neither of those.
#define BANIM_STOPPED 0x7fffffff

typedef struct BSlideAnim {
    uint32_t   screen;
    BAnimGroup groups[BANIM_MAX_GROUPS];
    int        numGroups;
    int32_t    timeStarted;
    float      totalTime;    // the longest group duration, not the sum
} BSlideAnim;

// tSlideAnimation (0x00232660): an empty list on one screen.
void banim_slide_init(BAnim* a, BSlideAnim* s, uint32_t screen);
// AddGroup (0x002326d8). Also raises TotalTime if this group is the
// longest, which is where the exit animation's duration comes from.
void banim_slide_add_group(BAnim* a, BSlideAnim* s, uint32_t group,
                           uint32_t master, float start, float end,
                           float duration);

// tSlideInAnimation (0x00232a48): every MENUITEM_<i>_GROUP that exists
// comes in from x = 640 + 10i to `targetX`, over 0.05 + 0.05i seconds,
// with MI_<i>_MASK as the group's master. Started immediately, by the
// constructor.
void banim_slide_in_init(BAnim* a, BSlideAnim* s, uint32_t screen,
                         float targetX);
// tSlideOutAnimation (0x00232958): from wherever each group's master is now
// to x = 650, over the same staggered durations. NOT started -- either
// banim_slide_start or tExitScreenAnimation does that.
void banim_slide_out_init(BAnim* a, BSlideAnim* s, uint32_t screen);

void  banim_slide_start(BAnim* a, BSlideAnim* s);
// HasControl (0x002327f0) and GetFractionCompleted (0x002328b0) have zero
// callers on this disc, like AlignBar in bmenu.c. Ported because they are
// two lines each and because "nothing calls it" is worth being able to show.
int   banim_slide_has_control(const BSlideAnim* s);
int   banim_slide_finished(const BSlideAnim* s);
// 0 before it starts, 1 once finished, otherwise elapsed / totalTime. Note
// this is wall-clock against the longest group, not per-group progress.
float banim_slide_fraction(const BAnim* a, const BSlideAnim* s);
void  banim_slide_animate(BAnim* a, BSlideAnim* s);
void  banim_slide_release(BAnim* a, BSlideAnim* s);

// ----------------------------------------------------- tExitScreenAnimation

// A slide-out that changes screen when it lands, and swallows input while
// it runs. `target` is a ScreenName ("Cops On Mode Select"), not a hash,
// and is not copied -- the original stores the same const char * pointer.
typedef struct BExitAnim {
    BSlideAnim  slide;
    const char* target;
} BExitAnim;

void banim_exit_init(BAnim* a, BExitAnim* e, uint32_t screen,
                     const char* target);
// HandleMessages (0x00232b90). Returns 1 if the exit animation finished and
// the screen change went out. `param`/`noise` are the reply fields of
// ScreenCallbackData and are written the way the original writes them:
// noise is always cleared, and PAD_UP/PAD_DOWN come back claimed so the
// selection cannot move while the items are leaving.
int banim_exit_message(BAnim* a, BExitAnim* e, int message,
                       int32_t* param, int32_t* noise);

// --------------------------------------------------------- tSlideOnScreen

// An Options page's sub-page (the Credits menu, the languages, Load/Save)
// coming on over the Options page: the page's group slides in from x = 650
// to where its master object was authored, on a tCubic1D of half a second,
// and the screen behind -- Options -- is shown while it is up. 0x001ee918
// .. 0x001eeb74, 48 + 24 bytes. The spline's flags are left at 1, so every
// step rebuilds the curve from where it has got to (bspline_seek): the
// page eases in rather than landing at half a second.
typedef struct BSlideOnScreen {
    uint32_t screen;     // +0
    uint32_t other;      // +4, the screen shown behind this one
    uint32_t object;     // +8, the group's master
    uint32_t group;      // +12
    float    x, y;       // +16, the master's authored top left
    BSpline  spline;     // +24, x
} BSlideOnScreen;

// The constructor (0x001ee918): reads the authored position, then Appear.
void banim_slide_on_init(BAnim* a, BSlideOnScreen* s, uint32_t screen,
                         uint32_t object, uint32_t group, uint32_t other);
// Appear (0x001eead8): from 650 again, the other screen shown, one Tick.
void banim_slide_on_appear(BAnim* a, BSlideOnScreen* s);
// Disappear (0x001eea80), all the destructor does: the group back where it
// was authored, and the other screen hidden.
void banim_slide_on_disappear(BAnim* a, BSlideOnScreen* s);
// Tick (0x001ee9f8): the spline stepped by RealTimeElapsed, and the group
// put at it while the master is on the screen.
void banim_slide_on_tick(BAnim* a, BSlideOnScreen* s);

// ---------------------------------------------------- tHighlightAnimation

// The bloom on the selected item: a copy of its text, scaled up and faded
// out over half a second, repeating every four seconds. `textObject` is the
// spare text object the copy is drawn into. The shipped tuning is the
// class's six static members, all of them in .data and none of them
// written at runtime:
#define BANIM_HL_TIME        0.5f    // _19tHighlightAnimation$HighlightAnimationTime
#define BANIM_HL_START_SCALE 1.0f    // $StartHighlightScale
#define BANIM_HL_END_SCALE   2.0f    // $EndHighlightScale
#define BANIM_HL_START_ALPHA 128.0f  // $StartAlpha
#define BANIM_HL_END_ALPHA   0.0f    // $EndAlpha
#define BANIM_HL_TIMEOUT     4.0f    // $HighlightTimeout

// BloomTargetColor (0x00324a08), the colour every frontend screen but one
// passes: 0x00000080. SetColor keeps the chunk's alpha and replaces the low
// 24 bits, and the byte order is the GS's, so this is full-intensity red.
#define BANIM_BLOOM_COLOR 0x00000080u

typedef struct BHighlightAnim {
    uint32_t screen;
    uint32_t currentItem;    // the item object whose text gets copied
    int32_t  timer;
    uint32_t textObject;
    int32_t  targetColor;    // -1 leaves the copy the colour it came with
    float    startScale, endScale, timeout;
} BHighlightAnim;

void banim_highlight_init(BAnim* a, BHighlightAnim* h, uint32_t screen,
                          uint32_t textObject, int32_t targetColor);
// SetCurrentMenuItem (0x00232378): restart, and re-read the item's authored
// scale so the bloom is relative to it.
void banim_highlight_set_item(BAnim* a, BHighlightAnim* h, uint32_t item);
void banim_highlight_force_start(BAnim* a, BHighlightAnim* h);
void banim_highlight_animate(BAnim* a, BHighlightAnim* h);

// bSin used to live here as banim_bsin, because the bloom's easing is the
// only thing in the frontend that calls it and bMath had not been ported
// yet. It is bmath.h's bSinF now; banim.c includes that.

// ------------------------------------------------------ feAnimAlphaElement

// A Flailer object plus the alpha it was authored with, so a fade is a
// factor rather than a value. Bitmaps keep four; everything else uses [0].
typedef struct BAnimAlpha {
    uint32_t screen;
    uint32_t object;
    int      exists;
    int      isBitmap;
    float    savedAlpha[4];
} BAnimAlpha;

void banim_alpha_init(BAnim* a, BAnimAlpha* e, uint32_t screen,
                      uint32_t object);
void banim_alpha_set_scale(BAnim* a, BAnimAlpha* e, float scale);
// ~feAnimAlphaElement (0x00231d50): writes the saved alphas back.
void banim_alpha_release(BAnim* a, BAnimAlpha* e);

// ---------------------------------------------------------- tAnimatedBlurb

// The one line of description under a menu. A new highlight wipes the old
// line out with a bar, then the new text slides in from off the right.
// The .mdebug calls the states STAGE_START / STAGE_1 / STAGE_2 / STAGE_3;
// these are the same four, named for what they do.
enum {
    BBLURB_SLIDING_IN = 0,   // print the text and start the slide
    BBLURB_WHITEOUT   = 1,   // the bar is covering the old line
    BBLURB_NEW_TEXT   = 2,   // the bar is up; put the new line under it
    BBLURB_SETTLED    = 3    // the slide finished; nothing to do
};

#define BBLURB_MAX_TEXT      256     // LatestText[256]
#define BBLURB_WHITEOUT_TIME 0.6f    // _14tAnimatedBlurb$WhiteoutTime
#define BBLURB_IDLE_TIME     0.5f    // _14tAnimatedBlurb$IdleTime
#define BBLURB_SLIDE_TIME    0.25f   // the constructor's own literal
#define BANIM_OFFSCREEN_X    650.0f  // where everything parks, 0x00322254

typedef struct BBlurb {
    uint32_t   screen;
    uint32_t   slideText;     // the line itself -- SCROLLING_TEXT
    int32_t    newTextTimer;
    int        animationStarted;
    BAnimGroup slideInText;
    BAnimAlpha fadeoutText;   // the line, faded out under the bar
    BAnimAlpha whiteoutBar;   // WHITEOUT_BAR, faded in over it
    char       latestText[BBLURB_MAX_TEXT];
    float      desiredX;
    int32_t    idleTimer;
    int        state;
    int        frozen;        // retail's; see banim_blurb_freeze
} BBlurb;

// 0x00232c18. `fadeout` and `whiteout` are the two objects the wipe uses;
// on every screen on disc `fadeout` is the same object as `slideText`.
void banim_blurb_init(BAnim* a, BBlurb* b, uint32_t screen,
                      uint32_t slideText, uint32_t fadeout,
                      uint32_t whiteout);
// NewText (0x00232f20 / 0x00232ef0). The int form goes through the
// translate hook; both restart the wipe if the line had already settled.
void banim_blurb_new_text(BAnim* a, BBlurb* b, const char* s);
void banim_blurb_new_text_id(BAnim* a, BBlurb* b, int languageID);
void banim_blurb_animate(BAnim* a, BBlurb* b);
void banim_blurb_release(BAnim* a, BBlurb* b);
// Freeze (retail 0x002492f0): the line emptied and faded, and Animate
// stopped until the next NewText.
void banim_blurb_freeze(BAnim* a, BBlurb* b);

// ------------------------------------------------------------- SelectionSet

// Not an animation, but it lives in the same kit and OnTick calls it in the
// same breath: the MI_<n>_MASK bitmaps are an indicator, and with
// IndicatorMode 1 -- which is what every screen that uses one sets -- the
// mask over the CURRENT item is the one turned off. Objects[] keeps its
// holes: a mask the screen does not define is still counted, because
// AddItem (0x001693c0) increments NumItems whether or not it found one.
#define BSEL_MAX_ITEMS 16

typedef struct BSelSet {
    uint32_t screen;
    uint32_t items[BSEL_MAX_ITEMS];   // 0 where the screen has no such mask
    int      numItems;
    uint32_t current;                 // CurrentObject, 0 for none
    int      mode;                    // SelectionSetMode; 1 from the ctor
    int      indicatorMode;           // 0 until the screen sets it
} BSelSet;

void bsel_init(BAnim* a, BSelSet* s, uint32_t screen);
void bsel_set_indicator_mode(BSelSet* s, int mode);
// AddItems (0x00169430): a table of name hashes, looked up on the screen.
void bsel_add_items(BAnim* a, BSelSet* s, const uint32_t* hashes, int n);
void bsel_set_current(BAnim* a, BSelSet* s, uint32_t object);
// Update (0x001695a0) is `jr ra; nop`. It is here so that a reader who goes
// looking for it finds the answer rather than the absence.
void bsel_update(BSelSet* s);

#endif  // BANIM_H
