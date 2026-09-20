#include "banim.h"

#include "bmath.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

// The frontend's animation layer. See banim.h for the shape and
// docs/formats/frontend-animation.md for the decompilation, which names an
// address for every rule in here.
//
// Two conventions worth stating once:
//
// * Every float -> int conversion in this file is a C cast, because that is
//   truncation toward zero and `cvt.w.s` on the R5900 truncates toward zero
//   whatever FCR31 says. Positions and alphas both go through one, and the
//   difference between truncating and rounding is a pixel.
//
// * All of the state is in the caller's struct. The original news every one
//   of these objects out of bMalloc and hangs them off the screen; nothing
//   here allocates, so a screen embeds its kit and the destructors become
//   the _release calls.

static void trace(BAnim* a, const char* fmt, ...)
{
    char    line[192];
    va_list ap;
    if (!a->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    a->hooks.trace(a->hooks.user, line);
}

void banim_init(BAnim* a, const BAnimHooks* hooks)
{
    memset(a, 0, sizeof(*a));
    if (hooks) a->hooks = *hooks;
    a->elapsed = 0.0f;
}

void banim_tick(BAnim* a, float dt)
{
    a->timer  += (int32_t)(dt * BANIM_TICKS_PER_SEC);
    a->elapsed = dt;
}

void banim_set_clock(BAnim* a, int32_t timer, float elapsed)
{
    a->timer   = timer;
    a->elapsed = elapsed;
}

// Seconds between two RealTimer readings. DAT_00322244 and its two copies
// are all 0.00025f, not 1/4000 computed at compile time, and the two are
// not the same number in single precision -- 0.00025f is 0x3983126f and
// 1.0f/4000.0f rounds to 0x3983126e. One ulp, but a comparison against
// HighlightAnimationTime can land on either side of it.
#define BANIM_TICK_SECONDS 0.00025f

static float sinceTicks(int32_t now, int32_t then)
{
    return (float)(now - then) * BANIM_TICK_SECONDS;
}

// ------------------------------------------------------------ hook helpers
//
// A missing hook has to behave like a screen with nothing on it, because
// that is how the cross-check runs half its scenarios.

static int hObjectExists(BAnim* a, uint32_t screen, uint32_t object, int type)
{
    if (!a->hooks.objectExists) return 0;
    return a->hooks.objectExists(a->hooks.user, screen, object, type);
}

static int hGroupExists(BAnim* a, uint32_t screen, uint32_t group, int type)
{
    if (!a->hooks.groupExists) return 0;
    return a->hooks.groupExists(a->hooks.user, screen, group, type);
}

static void hGetTopLeft(BAnim* a, uint32_t screen, uint32_t object,
                        float* x, float* y)
{
    *x = 0.0f;
    *y = 0.0f;
    if (a->hooks.getTopLeft) a->hooks.getTopLeft(a->hooks.user, screen,
                                                 object, x, y);
}

static float hGetTopLeftX(BAnim* a, uint32_t screen, uint32_t object)
{
    float x, y;
    hGetTopLeft(a, screen, object, &x, &y);
    return x;
}

// The tail of both AnimationGroup movers: FlailerSetGroupPosition when the
// group is set, FlailerSetTopLeftPosition when it is not. Both take ints.
static void placeGroup(BAnim* a, const BAnimGroup* g, float x, float y)
{
    if (g->group == 0) {
        if (a->hooks.setTopLeft)
            a->hooks.setTopLeft(a->hooks.user, g->screen, g->master,
                                (float)(int)x, y);
        return;
    }
    if (a->hooks.setGroupPos)
        a->hooks.setGroupPos(a->hooks.user, g->screen, g->group, g->master,
                             (float)(int)x, y);
}

// --------------------------------------------------------------- tCubic1D

void bspline_make_coeffs(BSpline* s)
{
    float d = s->valDesired - s->val;
    float v = s->dval;
    s->coeff[3] = s->val;
    s->coeff[2] = v;
    s->coeff[0] = (v + s->dvalDesired) - (d + d);
    s->coeff[1] = (d * 3.0f - s->dvalDesired) - (v + v);
}

float bspline_get_val(const BSpline* s, float t)
{
    return ((s->coeff[0] * t + s->coeff[1]) * t + s->coeff[2]) * t
           + s->coeff[3];
}

float bspline_get_dval(const BSpline* s, float t)
{
    return (s->coeff[0] * t * 3.0f + s->coeff[1] + s->coeff[1]) * t
           + s->coeff[2];
}

void bspline_seek(BSpline* s, float dt)
{
    float t;

    if (s->state != 1) {
        if (s->state < 2) return;
        if (s->state != 2) return;
        // A fresh seek: restart the parameter and build the curve. Note the
        // `flags` test -- with flags non-zero the state stays at 2, so time
        // is reset and the coefficients are rebuilt on EVERY step and the
        // spline never advances. AnimationGroup's constructor leaves flags
        // at 1 and SetupToAnimate clears it, which is the only reason any
        // of this moves.
        s->time = 0.0f;
        if (s->flags == 0) s->state = 1;
        // ClampDerivative / ClampSecondDerivative would go here; the
        // frontend's only caller passes 0 for both limits.
        bspline_make_coeffs(s);
    }

    t = s->time + dt / s->duration;
    s->time = t;
    if (s->arrivalThreshold <= t) {
        // Landing snaps to the destination only when the threshold is at or
        // past 1.0 -- a shorter threshold is a deliberate early-out and
        // leaves Val wherever the curve had got to.
        if (1.0f <= s->arrivalThreshold) {
            s->val  = s->valDesired;
            s->dval = s->dvalDesired;
        }
        s->state = 0;
    } else {
        s->val  = bspline_get_val(s, t);
        s->dval = bspline_get_dval(s, t);
    }
}

// ---------------------------------------------------------- AnimationGroup

void banim_group_init(BAnim* a, BAnimGroup* g, uint32_t screen,
                      uint32_t group, uint32_t master,
                      float start, float end, float duration)
{
    memset(g, 0, sizeof(*g));
    g->screen = screen;
    g->group  = group;
    g->master = master;

    g->spline.val              = 0.0f;
    g->spline.dval             = 0.0f;
    g->spline.valDesired       = 0.0f;
    g->spline.dvalDesired      = 0.0f;
    g->spline.state            = 0;
    g->spline.flags            = 1;
    g->spline.arrivalThreshold = 1.0f;
    g->spline.duration         = 1.0f;

    // The authored position comes first, so SavedYPos is the Y the group
    // keeps for its whole life: only X is animated, and the destructor puts
    // both back. SavedXPos/SavedYPos are ints in the original -- the
    // constructor reads them through FlailerGetTopLeftPosition's int
    // overload (0x00141d28), which cvt.w.s's both -- so truncate here too.
    // Nothing on the disc is authored off a whole pixel (2252 objects, all
    // integral), so this never changes a position; it changes what the type
    // is, and the destructor's restore is the place that would show it.
    hGetTopLeft(a, screen, master, &g->savedX, &g->savedY);
    g->savedX = (float)(int)g->savedX;
    g->savedY = (float)(int)g->savedY;

    g->spline.duration = duration;
    banim_group_setup(a, g, start, end);
}

void banim_group_setup(BAnim* a, BAnimGroup* g, float start, float end)
{
    BSpline* s = &g->spline;

    // Three inlined tCubic1D calls: SetValDesired(start), SetVal(start),
    // SetValDesired(end). The first one's state = 2 is overwritten by the
    // second's state = 0 one instruction later and can never be observed;
    // it is here because it is what 0x002321b8 does.
    s->valDesired = start;
    s->flags      = 0;
    if (start != s->val) s->state = 2;
    s->state      = 0;
    s->val        = s->valDesired;
    s->valDesired = end;
    s->dval       = s->dvalDesired;
    if (end != s->val) s->state = 2;

    placeGroup(a, g, s->val, g->savedY);
    trace(a, "group %08x/%08x setup %d -> %d in %.3f", (unsigned)g->group,
          (unsigned)g->master, (int)start, (int)end, s->duration);
}

int banim_group_finished(const BAnimGroup* g)
{
    return g->spline.state == 0;
}

void banim_group_animate(BAnim* a, BAnimGroup* g)
{
    bspline_seek(&g->spline, a->elapsed);
    placeGroup(a, g, g->spline.val, g->savedY);
}

float banim_group_desired_x(const BAnimGroup* g)
{
    return g->spline.valDesired;
}

void banim_group_release(BAnim* a, BAnimGroup* g)
{
    placeGroup(a, g, g->savedX, g->savedY);
}

// --------------------------------------------------------- tSlideAnimation

// "MENUITEM_%d_GROUP" and "MI_%d_MASK" through SprintfAndHash (0x001d1d98),
// which is sprintf followed by bStringHash. Both families are consecutive
// in the hash because bStringHash is h * 33 + c and only the digit moves:
// the step is 33 ** (characters after the digit), 33**6 for the group and
// 33**5 for the mask. Spelling it that way rather than tabulating ten
// constants is what makes it checkable against tools/bhash.py.
#define BANIM_POW33_5 39135393u
#define BANIM_POW33_6 1291467969u

// bStringHash("MENUITEM_0_GROUP") and bStringHash("MI_0_MASK").
#define BANIM_GROUP0 0x59c1995eu
#define BANIM_MASK0  0x6bdfbaafu

static uint32_t menuItemGroup(int i)
{
    return (uint32_t)(BANIM_GROUP0 + (uint32_t)i * BANIM_POW33_6);
}

static uint32_t menuItemMask(int i)
{
    return (uint32_t)(BANIM_MASK0 + (uint32_t)i * BANIM_POW33_5);
}

void banim_slide_init(BAnim* a, BSlideAnim* s, uint32_t screen)
{
    (void)a;
    memset(s, 0, sizeof(*s));
    s->screen      = screen;
    s->numGroups   = 0;
    s->timeStarted = 0;
    s->totalTime   = 0.0f;
}

void banim_slide_add_group(BAnim* a, BSlideAnim* s, uint32_t group,
                           uint32_t master, float start, float end,
                           float duration)
{
    if (s->totalTime < duration) s->totalTime = duration;
    if (s->numGroups >= BANIM_MAX_GROUPS) {
        // The original's list has no limit; this array is sized to the most
        // any caller on the disc asks for. Say so rather than drop it
        // silently, because a new caller would otherwise animate short.
        trace(a, "slide overflow %08x", (unsigned)group);
        return;
    }
    banim_group_init(a, &s->groups[s->numGroups], s->screen, group, master,
                     start, end, duration);
    s->numGroups++;
}

// SplineBaseDuration + i * SplineDeltaDuration, both 0.05f (0x00324db4,
// 0x00324db8). Group 0 therefore runs for 0.05 s and group 9 for 0.5 s,
// and the whole animation is as long as its slowest group.
static float slideDuration(int i)
{
    return 0.05f + (float)i * 0.05f;
}

void banim_slide_in_init(BAnim* a, BSlideAnim* s, uint32_t screen,
                         float targetX)
{
    banim_slide_init(a, s, screen);
    for (int i = 0; i < BANIM_SLIDE_SLOTS; i++) {
        uint32_t group  = menuItemGroup(i);
        uint32_t master = menuItemMask(i);
        if (!hGroupExists(a, screen, group, BANIM_TYPE_ANY)) continue;
        // ObjectDeltaPos is 10.0f (0x00324dbc): each group starts ten
        // pixels further off the right than the one before, so they arrive
        // in order even though they all aim at the same X.
        banim_slide_add_group(a, s, group, master,
                              640.0f + (float)i * 10.0f, targetX,
                              slideDuration(i));
    }
    s->timeStarted = a->timer;
    trace(a, "slidein %d groups -> %d", s->numGroups, (int)targetX);
}

void banim_slide_out_init(BAnim* a, BSlideAnim* s, uint32_t screen)
{
    banim_slide_init(a, s, screen);
    for (int i = 0; i < BANIM_SLIDE_SLOTS; i++) {
        uint32_t group  = menuItemGroup(i);
        uint32_t master = menuItemMask(i);
        if (!hGroupExists(a, screen, group, BANIM_TYPE_ANY)) continue;
        banim_slide_add_group(a, s, group, master,
                              hGetTopLeftX(a, screen, master),
                              BANIM_OFFSCREEN_X, slideDuration(i));
    }
    s->timeStarted = 0;
    trace(a, "slideout %d groups", s->numGroups);
}

void banim_slide_start(BAnim* a, BSlideAnim* s)
{
    s->timeStarted = a->timer;
}

int banim_slide_has_control(const BSlideAnim* s)
{
    return s->timeStarted != 0 && s->timeStarted != BANIM_STOPPED;
}

int banim_slide_finished(const BSlideAnim* s)
{
    if (!banim_slide_has_control(s)) return 0;
    // An empty slide is finished the moment it starts, because this is an
    // AND over no groups. Both Mode Selects rely on it: a screen with no
    // MENUITEM_i_GROUP still changes screen, on the next tick.
    for (int i = 0; i < s->numGroups; i++)
        if (!banim_group_finished(&s->groups[i])) return 0;
    return 1;
}

float banim_slide_fraction(const BAnim* a, const BSlideAnim* s)
{
    if (!banim_slide_has_control(s)) return 0.0f;
    if (banim_slide_finished(s)) return 1.0f;
    return sinceTicks(a->timer, s->timeStarted) / s->totalTime;
}

void banim_slide_animate(BAnim* a, BSlideAnim* s)
{
    // The guard is IsFinished, not HasControl, and IsFinished answers 0
    // for a slide that was never started -- so an unstarted slide DOES
    // animate here. That is only safe because nothing ticks a bare
    // tSlideOutAnimation: the one caller wraps it in tExitScreenAnimation,
    // whose constructor starts it. GetFractionCompleted is the function
    // that cares about the difference, and it checks HasControl itself.
    if (banim_slide_finished(s)) return;
    for (int i = 0; i < s->numGroups; i++)
        banim_group_animate(a, &s->groups[i]);
}

void banim_slide_release(BAnim* a, BSlideAnim* s)
{
    for (int i = 0; i < s->numGroups; i++)
        banim_group_release(a, &s->groups[i]);
    s->numGroups = 0;
}

// ----------------------------------------------------- tExitScreenAnimation

void banim_exit_init(BAnim* a, BExitAnim* e, uint32_t screen,
                     const char* target)
{
    banim_slide_out_init(a, &e->slide, screen);
    e->target = target;
    banim_slide_start(a, &e->slide);
    trace(a, "exit start %s %.3fs", target ? target : "(null)",
          e->slide.totalTime);
}

int banim_exit_message(BAnim* a, BExitAnim* e, int message,
                       int32_t* param, int32_t* noise)
{
    // The first store in HandleMessages is unconditional -- it sits in the
    // delay slot of the test for SCREEN_BACK_BUTTON -- so nothing the
    // screen does while sliding out makes a sound.
    if (noise) *noise = 0;

    if (message == 17) {                       // SCREEN_BACK_BUTTON
        if (param) *param = 0;                 // vetoed: BACK does nothing
        return 0;
    }
    if ((unsigned)(message - 8) < 2) {         // MENUITEM_PAD_UP / _DOWN
        if (param) *param = 1;                 // claimed: no moving now
        return 0;
    }
    if (message != 18) return 0;               // SCREEN_TICK

    banim_slide_animate(a, &e->slide);
    if (!banim_slide_finished(&e->slide)) return 0;

    trace(a, "exit finish %s", e->target ? e->target : "(null)");
    if (a->hooks.changeToScreen)
        a->hooks.changeToScreen(a->hooks.user, e->target, 1);
    return 1;
}

// --------------------------------------------------- tHighlightAnimation

void banim_highlight_init(BAnim* a, BHighlightAnim* h, uint32_t screen,
                          uint32_t textObject, int32_t targetColor)
{
    memset(h, 0, sizeof(*h));
    h->screen      = screen;
    h->timer       = a->timer;
    h->textObject  = textObject;
    h->targetColor = targetColor;
    h->startScale  = BANIM_HL_START_SCALE;
    h->endScale    = BANIM_HL_END_SCALE;
    h->timeout     = BANIM_HL_TIMEOUT;
    h->currentItem = 0;
}

void banim_highlight_set_item(BAnim* a, BHighlightAnim* h, uint32_t item)
{
    float sx = 1.0f, sy = 1.0f;

    h->currentItem = item;
    h->timer       = a->timer;
    // FlailerGetScale twice, on the same object, into two different pairs of
    // stack slots. The compiler did not fold it; neither does this, because
    // the second read is what the second multiply uses and a hook with a
    // side effect would see both.
    if (a->hooks.getScale)
        a->hooks.getScale(a->hooks.user, h->screen, item, &sx, &sy);
    h->startScale = sx * BANIM_HL_START_SCALE;
    sx = 1.0f;
    sy = 1.0f;
    if (a->hooks.getScale)
        a->hooks.getScale(a->hooks.user, h->screen, item, &sx, &sy);
    h->endScale = sx * BANIM_HL_END_SCALE;
    trace(a, "bloom item %08x scale %.3f..%.3f", (unsigned)item,
          h->startScale, h->endScale);
}

void banim_highlight_force_start(BAnim* a, BHighlightAnim* h)
{
    h->timer = a->timer;
}

void banim_highlight_animate(BAnim* a, BHighlightAnim* h)
{
    float t = sinceTicks(a->timer, h->timer);

    if (t < BANIM_HL_TIME) {
        // DAT_00322248 is 1.57075f, not pi/2 -- a five-decimal rounding
        // that shipped. At t = HighlightAnimationTime the argument is
        // therefore just short of the peak and bSin returns 0.99999994.
        float u     = (t * 1.57075f) / BANIM_HL_TIME;
        float s     = bSinF(u);
        float alpha = BANIM_HL_START_ALPHA
                      + (BANIM_HL_END_ALPHA - BANIM_HL_START_ALPHA)
                        * bSinF(u);
        int   src   = hObjectExists(a, h->screen, h->currentItem,
                                    BANIM_TYPE_TEXT);
        int   dst   = hObjectExists(a, h->screen, h->textObject,
                                    BANIM_TYPE_TEXT);
        if (!src) {
            // Nothing to copy: hide the spare object. This is a raw store
            // to the chunk's Visibility byte in the original rather than a
            // SetVisibility call, but it is the same write.
            if (dst && a->hooks.setVisible)
                a->hooks.setVisible(a->hooks.user, h->screen, h->textObject,
                                    0);
        } else if (dst) {
            if (a->hooks.copyText)
                a->hooks.copyText(a->hooks.user, h->screen, h->textObject,
                                  h->currentItem);
            if (a->hooks.scaleAboutCenter)
                a->hooks.scaleAboutCenter(
                    a->hooks.user, h->screen, h->textObject,
                    h->startScale + (h->endScale - h->startScale) * s);
            if (a->hooks.setAlpha)
                a->hooks.setAlpha(a->hooks.user, h->screen, h->textObject,
                                  0, (int)alpha);
            if (h->targetColor != -1 && a->hooks.setColor)
                a->hooks.setColor(a->hooks.user, h->screen, h->textObject,
                                  (uint32_t)h->targetColor);
        }
    }

    // Past the timeout the cycle restarts. Between the animation ending at
    // 0.5 s and the timeout at 4.0 s the copy is left exactly where the
    // last frame put it -- scaled to 2x and at alpha 0 -- so it is invisible
    // rather than removed, which is why nothing hides it.
    if (h->timeout < t) h->timer = a->timer;
}

// ------------------------------------------------------ feAnimAlphaElement

void banim_alpha_init(BAnim* a, BAnimAlpha* e, uint32_t screen,
                      uint32_t object)
{
    memset(e, 0, sizeof(*e));
    e->screen = screen;
    e->object = object;
    e->exists = hObjectExists(a, screen, object, BANIM_TYPE_ANY);
    e->isBitmap = 0;
    if (!e->exists) return;

    if (a->hooks.objectType)
        e->isBitmap = a->hooks.objectType(a->hooks.user, screen, object)
                      == BANIM_TYPE_BITMAP;
    for (int i = 0; i < 4; i++) {
        int v = 0;
        if (a->hooks.getAlpha)
            v = a->hooks.getAlpha(a->hooks.user, screen, object,
                                  e->isBitmap ? i : 0);
        e->savedAlpha[i] = (float)v;
    }
}

void banim_alpha_set_scale(BAnim* a, BAnimAlpha* e, float scale)
{
    if (!e->exists || !a->hooks.setAlpha) return;
    if (!e->isBitmap) {
        a->hooks.setAlpha(a->hooks.user, e->screen, e->object, 0,
                          (int)(e->savedAlpha[0] * scale));
        return;
    }
    for (int i = 0; i < 4; i++)
        a->hooks.setAlpha(a->hooks.user, e->screen, e->object, i,
                          (int)(e->savedAlpha[i] * scale));
}

void banim_alpha_release(BAnim* a, BAnimAlpha* e)
{
    banim_alpha_set_scale(a, e, 1.0f);
}

// ---------------------------------------------------------- tAnimatedBlurb

void banim_blurb_init(BAnim* a, BBlurb* b, uint32_t screen,
                      uint32_t slideText, uint32_t fadeout,
                      uint32_t whiteout)
{
    float x;

    memset(b, 0, sizeof(*b));
    b->newTextTimer = 0;
    x = hGetTopLeftX(a, screen, slideText);
    // No group: the line is one object and moves alone. It starts off the
    // right at 650 and its home is wherever the bundle put it.
    banim_group_init(a, &b->slideInText, screen, 0, slideText,
                     BANIM_OFFSCREEN_X, x, BBLURB_SLIDE_TIME);
    banim_alpha_init(a, &b->fadeoutText, screen, fadeout);
    banim_alpha_init(a, &b->whiteoutBar, screen, whiteout);

    b->screen           = screen;
    b->slideText        = slideText;
    b->desiredX         = banim_group_desired_x(&b->slideInText);
    b->idleTimer        = 0;
    b->animationStarted = 0;
    b->state            = BBLURB_SLIDING_IN;
}

void banim_blurb_new_text(BAnim* a, BBlurb* b, const char* s)
{
    // Only a settled or about-to-settle line restarts the wipe. A NewText
    // while the bar is already up (state 1) just replaces the string, which
    // is what makes holding a direction on the menu read as one wipe rather
    // than one per item.
    if ((unsigned)(b->state - BBLURB_NEW_TEXT) < 2) {
        b->state            = BBLURB_WHITEOUT;
        b->newTextTimer     = a->timer;
        b->animationStarted = 0;
    }
    b->idleTimer = a->timer;
    if (!s) s = "";
    strncpy(b->latestText, s, BBLURB_MAX_TEXT - 1);
    b->latestText[BBLURB_MAX_TEXT - 1] = '\0';
    trace(a, "blurb text \"%s\" state %d", b->latestText, b->state);
}

void banim_blurb_new_text_id(BAnim* a, BBlurb* b, int languageID)
{
    const char* s = NULL;
    if (a->hooks.translate) s = a->hooks.translate(a->hooks.user, languageID);
    banim_blurb_new_text(a, b, s);
}

void banim_blurb_animate(BAnim* a, BBlurb* b)
{
    int   state    = b->state;
    float whiteout = sinceTicks(a->timer, b->newTextTimer);
    float idle     = sinceTicks(a->timer, b->idleTimer);

    if (state == BBLURB_WHITEOUT) {
        float f = 1.0f;
        if (whiteout < BBLURB_WHITEOUT_TIME)
            f = whiteout / BBLURB_WHITEOUT_TIME;
        banim_alpha_set_scale(a, &b->fadeoutText, 1.0f - f);
        banim_alpha_set_scale(a, &b->whiteoutBar, f);
        // The bar comes up over 0.6 s but the switch happens 0.5 s after
        // the LAST NewText, so a run of highlight changes holds the line
        // under the bar and only the final one gets printed.
        if (idle > BBLURB_IDLE_TIME) {
            b->animationStarted = 0;
            b->state            = BBLURB_NEW_TEXT;
            state               = BBLURB_NEW_TEXT;
        }
    }

    if (state == BBLURB_NEW_TEXT || state == BBLURB_SLIDING_IN) {
        banim_alpha_set_scale(a, &b->fadeoutText, 1.0f);
        banim_alpha_set_scale(a, &b->whiteoutBar, 0.0f);
        if (!b->animationStarted) {
            // LanguageID 0 puts the object back on its own inline string,
            // which FlailerPrintf then overwrites -- the translated text is
            // already resolved, so it goes in as a literal.
            if (a->hooks.setLanguageID)
                a->hooks.setLanguageID(a->hooks.user, b->screen,
                                       b->slideText, 0);
            if (a->hooks.printText)
                a->hooks.printText(a->hooks.user, b->screen, b->slideText,
                                   b->latestText);
            banim_group_setup(a, &b->slideInText, BANIM_OFFSCREEN_X,
                              b->desiredX);
            b->animationStarted = 1;
        } else if (!banim_group_finished(&b->slideInText)) {
            banim_group_animate(a, &b->slideInText);
        } else {
            b->state = BBLURB_SETTLED;
        }
    }
}

void banim_blurb_release(BAnim* a, BBlurb* b)
{
    banim_alpha_release(a, &b->whiteoutBar);
    banim_alpha_release(a, &b->fadeoutText);
    banim_group_release(a, &b->slideInText);
}

// ------------------------------------------------------------- SelectionSet

void bsel_init(BAnim* a, BSelSet* s, uint32_t screen)
{
    (void)a;
    memset(s, 0, sizeof(*s));
    s->screen        = screen;
    s->numItems      = 0;
    s->current       = 0;
    s->indicatorMode = 0;
    s->mode          = 1;
    // The original's constructor bMemSets only the first 64 bytes, which is
    // Objects[16] -- the Animate[16] array that follows it is left
    // uninitialised. Nothing reads it, because Update is empty.
}

void bsel_set_indicator_mode(BSelSet* s, int mode)
{
    s->indicatorMode = mode;
}

static void selSetVisible(BAnim* a, BSelSet* s, uint32_t object, int visible)
{
    if (!object || !a->hooks.setVisible) return;
    a->hooks.setVisible(a->hooks.user, s->screen, object, visible);
}

void bsel_add_items(BAnim* a, BSelSet* s, const uint32_t* hashes, int n)
{
    for (int i = 0; i < n; i++) {
        uint32_t found = hObjectExists(a, s->screen, hashes[i],
                                       BANIM_TYPE_ANY) ? hashes[i] : 0u;
        if (found) selSetVisible(a, s, found, s->indicatorMode == 0 ? 0 : 1);
        // A mask the screen does not define still takes a slot: AddItem
        // increments NumItems outside the null test. Dropping it would
        // renumber every mask after the hole.
        if (s->numItems < BSEL_MAX_ITEMS) s->items[s->numItems] = found;
        s->numItems++;
    }
}

void bsel_set_current(BAnim* a, BSelSet* s, uint32_t object)
{
    uint32_t next = 0;
    int      n    = s->numItems;

    if (s->mode != 1) return;

    if (s->current) selSetVisible(a, s, s->current,
                                  s->indicatorMode == 0 ? 0 : 1);
    s->current = 0;
    if (n > BSEL_MAX_ITEMS) n = BSEL_MAX_ITEMS;
    for (int i = 0; i < n; i++) {
        if (s->items[i] && s->items[i] == object) { next = s->items[i]; break; }
    }
    s->current = next;
    if (s->current) {
        selSetVisible(a, s, s->current, s->indicatorMode != 0 ? 0 : 1);
        trace(a, "indicator %08x", (unsigned)s->current);
    }
}

void bsel_update(BSelSet* s)
{
    (void)s;
}
