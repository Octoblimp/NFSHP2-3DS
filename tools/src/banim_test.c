// Host harness for the frontend animation layer.
//
// Builds "3DS Files/source/banim.c" for the host and drives it against a
// small made-up screen -- five menu items in groups, a blurb line, a
// whiteout bar, a bloom target and an underscore -- printing everything
// observable: the module's own trace, and every hook call it makes.
//
//     scenario <name>
//     <the module's trace: group, slidein, slideout, exit, bloom, blurb...>
//     hook <what> ...
//     <per-frame state, where the scenario prints it>
//
// tools/banim_check.py prints the same from an independent Python model and
// diffs the two, the way bscreens_check.py does for the screens. The model
// there is written from docs/formats/frontend-animation.md rather than from
// this code, so a misread of the PS2 maths shows up as a diff rather than as
// two copies of the same mistake.
//
// Floats are printed as %.9g: that is more significant digits than a float32
// holds, so the text is an exact record of the bits and Python's repr of the
// same float32 must match it character for character. Anywhere the original
// converts to int -- every position, every alpha -- the int is printed
// instead, because that is what the hardware would see.
//
// Usage: banim_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "banim.h"
#include "bmath.h"

#define SIXTIETH (1.0f / 60.0f)

// --------------------------------------------------------------- the world

#define W_MENU  0xaaaa0001u
#define W_EMPTY 0xaaaa0002u

// The hashes the real screens use, from docs/formats/frontend-screens.md.
#define H_SCROLLING_TEXT 0x75980cf0u
#define H_WHITEOUT_BAR   0x70a404ecu
#define H_BLOOM_TEXT     0xab671c9au
#define H_MI_UNDERSCORE  0x32c91daeu
#define H_UNDERSCORE_GRP 0x97bf4b25u
#define H_MENUITEM(n)    (0x52e039f2u + (unsigned)(n))

// bStringHash("MENUITEM_0_GROUP") / ("MI_0_MASK") and the two strides, so a
// reader can check the harness against tools/bhash.py without running it.
#define H_GROUP(i) (0x59c1995eu + (unsigned)(i) * 1291467969u)
#define H_MASK(i)  (0x6bdfbaafu + (unsigned)(i) * 39135393u)

typedef struct WObject {
    uint32_t screen;
    uint32_t name;
    uint32_t group;
    int      type;
    float    x, y;
    float    scaleX, scaleY;
    int      alpha[4];
    int      visible;
    int      languageID;
    uint32_t color;
    char     text[64];
} WObject;

// Five items in groups 1..5 -- group 0 is deliberately absent, because the
// slide loop runs from 0 and the real screens start at 1, so the skip is on
// the path every time. The masks are bitmaps and the labels are text, which
// is also how FRONTB.BUN has it.
static WObject g_world[] = {
    { W_MENU, H_MASK(1), H_GROUP(1), BANIM_TYPE_BITMAP,
      100.0f,  50.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
    { W_MENU, H_MASK(2), H_GROUP(2), BANIM_TYPE_BITMAP,
      100.0f,  70.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
    { W_MENU, H_MASK(3), H_GROUP(3), BANIM_TYPE_BITMAP,
      100.0f,  90.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
    { W_MENU, H_MASK(4), H_GROUP(4), BANIM_TYPE_BITMAP,
      100.0f, 110.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
    { W_MENU, H_MASK(5), H_GROUP(5), BANIM_TYPE_BITMAP,
      100.0f, 130.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
    { W_MENU, H_MENUITEM(1), H_GROUP(1), BANIM_TYPE_TEXT,
      120.0f,  50.0f, 1.5f, 1.5f, {128,0,0,0}, 1, 3, 0, "Quick Race" },
    { W_MENU, H_MENUITEM(2), H_GROUP(2), BANIM_TYPE_TEXT,
      120.0f,  70.0f, 1.5f, 1.5f, {128,0,0,0}, 1, 4, 0, "Championship" },
    { W_MENU, H_MENUITEM(3), H_GROUP(3), BANIM_TYPE_TEXT,
      120.0f,  90.0f, 0.5f, 0.5f, {128,0,0,0}, 1, 5, 0, "Hot Pursuit" },
    { W_MENU, H_MENUITEM(4), H_GROUP(4), BANIM_TYPE_TEXT,
      120.0f, 110.0f, 1.5f, 1.5f, {128,0,0,0}, 1, 6, 0, "Options" },
    { W_MENU, H_MENUITEM(5), H_GROUP(5), BANIM_TYPE_TEXT,
      120.0f, 130.0f, 1.5f, 1.5f, {128,0,0,0}, 1, 7, 0, "Quit" },
    { W_MENU, H_SCROLLING_TEXT, 0, BANIM_TYPE_TEXT,
       40.0f, 200.0f, 1.0f, 1.0f, {100,0,0,0}, 1, 9, 0, "" },
    { W_MENU, H_WHITEOUT_BAR, 0, BANIM_TYPE_BITMAP,
       40.0f, 198.0f, 1.0f, 1.0f, {128,96,64,32}, 1, 0, 0, "" },
    { W_MENU, H_BLOOM_TEXT, 0, BANIM_TYPE_TEXT,
        0.0f,   0.0f, 1.0f, 1.0f, {128,0,0,0}, 1, 0, 0, "" },
    { W_MENU, H_MI_UNDERSCORE, H_UNDERSCORE_GRP, BANIM_TYPE_BITMAP,
       95.0f, 150.0f, 1.0f, 1.0f, {128,128,128,128}, 1, 0, 0, "" },
};
#define NUM_WORLD ((int)(sizeof(g_world) / sizeof(g_world[0])))

// The world is reset before every scenario, because a slide leaves the
// objects wherever it parked them and the next scenario must not inherit it.
static WObject g_initial[NUM_WORLD];

static void worldReset(void)
{
    memcpy(g_world, g_initial, sizeof(g_world));
}

static WObject* find(uint32_t screen, uint32_t name, int type)
{
    for (int i = 0; i < NUM_WORLD; i++) {
        if (g_world[i].screen != screen || g_world[i].name != name) continue;
        if (type != BANIM_TYPE_ANY && g_world[i].type != type) continue;
        return &g_world[i];
    }
    return NULL;
}

// ------------------------------------------------------------ the hooks

static void wTrace(void* u, const char* line)
{
    (void)u;
    printf("%s\n", line);
}

static int hObjectExists(void* u, uint32_t s, uint32_t o, int t)
{
    (void)u;
    return find(s, o, t) != NULL;
}

static int hGroupExists(void* u, uint32_t s, uint32_t g, int t)
{
    (void)u;
    if (!g) return 0;
    for (int i = 0; i < NUM_WORLD; i++) {
        if (g_world[i].screen != s || g_world[i].group != g) continue;
        if (t != BANIM_TYPE_ANY && g_world[i].type != t) continue;
        return 1;
    }
    return 0;
}

static int hObjectType(void* u, uint32_t s, uint32_t o)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    return p ? p->type : BANIM_TYPE_ANY;
}

static void hGetTopLeft(void* u, uint32_t s, uint32_t o, float* x, float* y)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    if (!p) return;
    *x = p->x;
    *y = p->y;
}

static void hSetTopLeft(void* u, uint32_t s, uint32_t o, float x, float y)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    printf("hook settopleft %08x %d %d\n", (unsigned)o, (int)x, (int)y);
    if (!p) return;
    p->x = x;
    p->y = y;
}

// FlailerSetGroupPosition moves the master to (x, y) and every other object
// carrying the group by the same delta -- so the master's own offset inside
// the group is what the rest follow.
static void hSetGroupPos(void* u, uint32_t s, uint32_t g, uint32_t m,
                         float x, float y)
{
    WObject* master = find(s, m, BANIM_TYPE_ANY);
    float    dx, dy;
    (void)u;
    printf("hook setgrouppos %08x %08x %d %d\n", (unsigned)g, (unsigned)m,
           (int)x, (int)y);
    if (!master) return;
    dx = x - master->x;
    dy = y - master->y;
    for (int i = 0; i < NUM_WORLD; i++) {
        if (g_world[i].screen != s || g_world[i].group != g) continue;
        g_world[i].x += dx;
        g_world[i].y += dy;
    }
    // The master moves whether or not it is in the group; when it is, the
    // loop above already did it, and adding the delta twice would be wrong.
    if (master->group != g) {
        master->x = x;
        master->y = y;
    }
}

static void hSetVisible(void* u, uint32_t s, uint32_t o, int v)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    printf("hook visible %08x %d\n", (unsigned)o, v);
    if (p) p->visible = v;
}

static int hGetAlpha(void* u, uint32_t s, uint32_t o, int corner)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    return p ? p->alpha[corner] : 0;
}

static void hSetAlpha(void* u, uint32_t s, uint32_t o, int corner, int a)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    printf("hook alpha %08x %d %d\n", (unsigned)o, corner, a);
    if (p) p->alpha[corner] = a;
}

static void hSetLanguageID(void* u, uint32_t s, uint32_t o, int id)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    printf("hook langid %08x %d\n", (unsigned)o, id);
    if (p) p->languageID = id;
}

static void hPrintText(void* u, uint32_t s, uint32_t o, const char* str)
{
    WObject* p = find(s, o, BANIM_TYPE_TEXT);
    (void)u;
    printf("hook print %08x \"%s\"\n", (unsigned)o, str);
    if (!p) return;
    strncpy(p->text, str, sizeof(p->text) - 1);
    p->text[sizeof(p->text) - 1] = '\0';
}

static void hCopyText(void* u, uint32_t s, uint32_t dst, uint32_t src)
{
    WObject* d = find(s, dst, BANIM_TYPE_TEXT);
    WObject* q = find(s, src, BANIM_TYPE_TEXT);
    (void)u;
    printf("hook copytext %08x <- %08x \"%s\"\n", (unsigned)dst,
           (unsigned)src, q ? q->text : "");
    if (d && q) memcpy(d->text, q->text, sizeof(d->text));
}

static void hScaleAboutCenter(void* u, uint32_t s, uint32_t o, float scale)
{
    WObject* p = find(s, o, BANIM_TYPE_TEXT);
    (void)u;
    printf("hook scale %08x %.9g\n", (unsigned)o, (double)scale);
    if (!p) return;
    p->scaleX = scale;
    p->scaleY = scale;
}

static void hSetColor(void* u, uint32_t s, uint32_t o, uint32_t c)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    printf("hook color %08x %08x\n", (unsigned)o, (unsigned)c);
    if (p) p->color = c;
}

static void hGetScale(void* u, uint32_t s, uint32_t o, float* sx, float* sy)
{
    WObject* p = find(s, o, BANIM_TYPE_ANY);
    (void)u;
    if (!p) return;
    *sx = p->scaleX;
    *sy = p->scaleY;
}

// Stand-in for GetTranslatedString: the harness has no LANGTAB, so the id
// comes back as a string. The point is that the blurb asks and prints what
// it is given, not what the table says.
static const char* hTranslate(void* u, int id)
{
    static char buf[32];
    (void)u;
    if (id < 0) return NULL;
    snprintf(buf, sizeof(buf), "<string %d>", id);
    return buf;
}

static void hChangeToScreen(void* u, const char* name, int push)
{
    (void)u;
    printf("hook changetoscreen %s %d\n", name ? name : "(null)", push);
}

static void setupHooks(BAnimHooks* h)
{
    memset(h, 0, sizeof(*h));
    h->objectExists     = hObjectExists;
    h->groupExists      = hGroupExists;
    h->objectType       = hObjectType;
    h->getTopLeft       = hGetTopLeft;
    h->setTopLeft       = hSetTopLeft;
    h->setGroupPos      = hSetGroupPos;
    h->setVisible       = hSetVisible;
    h->getAlpha         = hGetAlpha;
    h->setAlpha         = hSetAlpha;
    h->setLanguageID    = hSetLanguageID;
    h->printText        = hPrintText;
    h->copyText         = hCopyText;
    h->scaleAboutCenter = hScaleAboutCenter;
    h->setColor         = hSetColor;
    h->getScale         = hGetScale;
    h->translate        = hTranslate;
    h->changeToScreen   = hChangeToScreen;
    h->trace            = wTrace;
}

// ------------------------------------------------------------- reporting

static void dumpMasks(void)
{
    for (int i = 1; i <= 5; i++) {
        WObject* p = find(W_MENU, H_MASK(i), BANIM_TYPE_ANY);
        WObject* l = find(W_MENU, H_MENUITEM(i), BANIM_TYPE_ANY);
        printf("  mask %d at %d,%d vis %d  label at %d,%d\n", i,
               (int)p->x, (int)p->y, p->visible, (int)l->x, (int)l->y);
    }
}

static void dumpObject(uint32_t name, const char* label)
{
    WObject* p = find(W_MENU, name, BANIM_TYPE_ANY);
    if (!p) { printf("  %s absent\n", label); return; }
    printf("  %s at %d,%d vis %d alpha %d,%d,%d,%d scale %.9g lang %d "
           "color %08x \"%s\"\n", label, (int)p->x, (int)p->y, p->visible,
           p->alpha[0], p->alpha[1], p->alpha[2], p->alpha[3],
           (double)p->scaleX, p->languageID, (unsigned)p->color, p->text);
}

// ------------------------------------------------------------- scenarios

// The curve on its own, with no Flailer around it. Prints the whole state
// each step, because the point here is the tCubic1D maths and not what it
// is driving.
static void scSpline(float threshold, int16_t flags, float duration)
{
    BSpline s;
    memset(&s, 0, sizeof(s));
    s.val              = 0.0f;
    s.dval             = 0.0f;
    s.valDesired       = 100.0f;
    s.dvalDesired      = 0.0f;
    s.duration         = duration;
    s.arrivalThreshold = threshold;
    s.flags            = flags;
    s.state            = 2;
    for (int i = 0; i < 14; i++) {
        bspline_seek(&s, SIXTIETH);
        printf("step %2d state %d t %.9g val %.9g dval %.9g "
               "c %.9g %.9g %.9g %.9g\n", i, s.state, (double)s.time,
               (double)s.val, (double)s.dval, (double)s.coeff[0],
               (double)s.coeff[1], (double)s.coeff[2], (double)s.coeff[3]);
    }
}

static void scBsin(void)
{
    // Every eighth of a turn, plus the three places the argument reduction
    // changes branch, plus a negative one to show the wrap.
    static const float kAngles[] = {
        0.0f, 0.1f, 0.5f, 0.78539816f, 1.0f, 1.5707963f, 1.5708f, 2.0f,
        3.1415927f, 3.5f, 4.712389f, 4.7123890f, 5.5f, 6.2831853f, 7.0f,
        -0.5f, -1.5707963f, 0.0099f, 1.57075f, 0.7853750f
    };
    for (int i = 0; i < (int)(sizeof(kAngles) / sizeof(kAngles[0])); i++) {
        float r = bSinF(kAngles[i]);
        printf("bsin %.9g = %.9g\n", (double)kAngles[i], (double)r);
    }
}

static void scSlideIn(BAnim* a, uint32_t screen, float targetX, int frames)
{
    BSlideAnim s;
    banim_slide_in_init(a, &s, screen, targetX);
    printf("total %.9g groups %d control %d\n", (double)s.totalTime,
           s.numGroups, banim_slide_has_control(&s));
    for (int f = 0; f < frames; f++) {
        banim_tick(a, SIXTIETH);
        banim_slide_animate(a, &s);
        printf("frame %d timer %d fin %d frac %.9g\n", f, a->timer,
               banim_slide_finished(&s),
               (double)banim_slide_fraction(a, &s));
    }
    dumpMasks();
    banim_slide_release(a, &s);
    printf("released\n");
    dumpMasks();
}

static void scSlideOut(BAnim* a, int startIt, int frames)
{
    BSlideAnim s;
    banim_slide_out_init(a, &s, W_MENU);
    printf("total %.9g groups %d control %d fin %d\n", (double)s.totalTime,
           s.numGroups, banim_slide_has_control(&s),
           banim_slide_finished(&s));
    if (startIt) banim_slide_start(a, &s);
    for (int f = 0; f < frames; f++) {
        banim_tick(a, SIXTIETH);
        banim_slide_animate(a, &s);
        printf("frame %d fin %d frac %.9g\n", f, banim_slide_finished(&s),
               (double)banim_slide_fraction(a, &s));
    }
    dumpMasks();
}

static void scExit(BAnim* a, int withUnderscore)
{
    BExitAnim e;
    int32_t   param, noise;
    int       done = 0;

    banim_exit_init(a, &e, W_MENU, "Cops On Mode Select");
    if (withUnderscore) {
        // What CopsOnModeSelect::StartChangeToScreen (0x00203ec8) adds on
        // top of the constructor, so the brackets leave with the items.
        float x = 0.0f, y = 0.0f;
        hGetTopLeft(NULL, W_MENU, H_MI_UNDERSCORE, &x, &y);
        banim_slide_add_group(a, &e.slide, H_UNDERSCORE_GRP,
                              H_MI_UNDERSCORE, x, BANIM_OFFSCREEN_X,
                              e.slide.totalTime);
    }
    printf("total %.9g groups %d\n", (double)e.slide.totalTime,
           e.slide.numGroups);

    // The three messages a screen sends while it is leaving. Each call is
    // its own statement: C does not order a function call against the other
    // arguments of the printf it sits in, and gcc reads param and noise
    // first, so writing it as one expression prints the values from before
    // the call rather than the ones it wrote.
    static const struct { int msg; const char* label; } kMsgs[3] = {
        { 17, "back" }, { 8, "up  " }, { 1, "sel " }
    };
    for (int k = 0; k < 3; k++) {
        int r;
        param = -1;
        noise = -1;
        r = banim_exit_message(a, &e, kMsgs[k].msg, &param, &noise);
        printf("%s -> %d param %d noise %d\n", kMsgs[k].label, r, param,
               noise);
    }

    for (int f = 0; f < 40 && !done; f++) {
        banim_tick(a, SIXTIETH);
        param = -1; noise = -1;
        done = banim_exit_message(a, &e, 18, &param, &noise);
        printf("frame %d tick -> %d param %d noise %d\n", f, done, param,
               noise);
    }
    dumpMasks();
    dumpObject(H_MI_UNDERSCORE, "underscore");
}

static void scHighlight(BAnim* a, uint32_t item, int frames)
{
    BHighlightAnim h;
    banim_highlight_init(a, &h, W_MENU, H_BLOOM_TEXT, BANIM_BLOOM_COLOR);
    banim_highlight_set_item(a, &h, item);
    for (int f = 0; f < frames; f++) {
        banim_tick(a, SIXTIETH);
        banim_highlight_animate(a, &h);
    }
    printf("timer %d start %.9g end %.9g\n", h.timer, (double)h.startScale,
           (double)h.endScale);
    dumpObject(H_BLOOM_TEXT, "bloom");
}

static void scAlpha(BAnim* a, uint32_t object, const char* label)
{
    BAnimAlpha e;
    static const float kScales[] = { 1.0f, 0.5f, 0.25f, 0.0f, 1.0f, 2.0f };
    banim_alpha_init(a, &e, W_MENU, object);
    printf("exists %d bitmap %d saved %.9g %.9g %.9g %.9g\n", e.exists,
           e.isBitmap, (double)e.savedAlpha[0], (double)e.savedAlpha[1],
           (double)e.savedAlpha[2], (double)e.savedAlpha[3]);
    for (int i = 0; i < (int)(sizeof(kScales) / sizeof(kScales[0])); i++)
        banim_alpha_set_scale(a, &e, kScales[i]);
    banim_alpha_release(a, &e);
    dumpObject(object, label);
}

// The blurb, driven the way a menu drives it: a highlight arrives, a couple
// of frames pass, another highlight arrives before the first has settled.
static void scBlurb(BAnim* a, int interrupt)
{
    BBlurb b;
    banim_blurb_init(a, &b, W_MENU, H_SCROLLING_TEXT, H_SCROLLING_TEXT,
                     H_WHITEOUT_BAR);
    printf("desired %.9g state %d\n", (double)b.desiredX, b.state);
    banim_blurb_new_text(a, &b, "Race against three rivals.");
    for (int f = 0; f < 70; f++) {
        banim_tick(a, SIXTIETH);
        if (interrupt && f == 20)
            banim_blurb_new_text(a, &b, "Outrun the cops.");
        if (interrupt && f == 45)
            banim_blurb_new_text_id(a, &b, 1234);
        banim_blurb_animate(a, &b);
        printf("frame %d state %d started %d\n", f, b.state,
               b.animationStarted);
    }
    dumpObject(H_SCROLLING_TEXT, "blurb");
    dumpObject(H_WHITEOUT_BAR, "bar");
    banim_blurb_release(a, &b);
    printf("released\n");
    dumpObject(H_SCROLLING_TEXT, "blurb");
    dumpObject(H_WHITEOUT_BAR, "bar");
}

static void scSelSet(BAnim* a, int indicatorMode)
{
    BSelSet  s;
    // Six masks, of which MI_6_MASK is not on the screen -- the hole is the
    // point, because AddItem counts it anyway and every later index shifts
    // if a port drops it.
    static const uint32_t kMasks[6] = {
        H_MASK(1), H_MASK(2), H_MASK(3), H_MASK(4), H_MASK(5), H_MASK(6)
    };
    bsel_init(a, &s, W_MENU);
    bsel_set_indicator_mode(&s, indicatorMode);
    bsel_add_items(a, &s, kMasks, 6);
    printf("items %d\n", s.numItems);
    for (int i = 0; i < 6; i++)
        printf("  slot %d %08x\n", i, (unsigned)s.items[i]);

    bsel_set_current(a, &s, H_MASK(3));
    printf("current %08x\n", (unsigned)s.current);
    bsel_set_current(a, &s, H_MASK(1));
    printf("current %08x\n", (unsigned)s.current);
    bsel_set_current(a, &s, H_MASK(6));       // counted, but never found
    printf("current %08x\n", (unsigned)s.current);
    bsel_set_current(a, &s, 0xdeadbeefu);
    printf("current %08x\n", (unsigned)s.current);
    s.mode = 0;                                // SelectionSetMode != 1
    bsel_set_current(a, &s, H_MASK(2));
    printf("current %08x\n", (unsigned)s.current);
    bsel_update(&s);
    dumpMasks();
}

// ------------------------------------------------------------------- main

typedef struct Scenario {
    const char* name;
    void (*run)(BAnim* a);
} Scenario;

static void rSplineNormal(BAnim* a)   { (void)a; scSpline(1.0f, 0, 0.1f); }
static void rSplineEarly(BAnim* a)    { (void)a; scSpline(0.5f, 0, 0.1f); }
static void rSplineLate(BAnim* a)     { (void)a; scSpline(1.5f, 0, 0.1f); }
// flags non-zero: the state never leaves 2, so the curve is rebuilt every
// step and Val never moves. Nothing on the disc does this, but it is the
// one branch in SplineSeek a reader will not believe without seeing.
static void rSplineStuck(BAnim* a)    { (void)a; scSpline(1.0f, 1, 0.1f); }
static void rBsin(BAnim* a)           { (void)a; scBsin(); }

static void rSlideIn(BAnim* a)        { scSlideIn(a, W_MENU, 100.0f, 36); }
static void rSlideInFar(BAnim* a)     { scSlideIn(a, W_MENU, -40.0f, 36); }
static void rSlideInEmpty(BAnim* a)   { scSlideIn(a, W_EMPTY, 100.0f, 4); }
static void rSlideOut(BAnim* a)       { scSlideOut(a, 1, 36); }
static void rSlideOutIdle(BAnim* a)   { scSlideOut(a, 0, 36); }
static void rExit(BAnim* a)           { scExit(a, 0); }
static void rExitUnder(BAnim* a)      { scExit(a, 1); }

static void rHighlight(BAnim* a)      { scHighlight(a, H_MENUITEM(1), 40); }
// A smaller authored scale: the bloom is relative to it, so this is 0.5 to
// 1.0 rather than 1.0 to 2.0.
static void rHighlightSmall(BAnim* a) { scHighlight(a, H_MENUITEM(3), 40); }
// Past the timeout and round again -- 4 s is 240 frames.
static void rHighlightLoop(BAnim* a)  { scHighlight(a, H_MENUITEM(2), 250); }
// An item the screen does not have: the copy is hidden instead.
static void rHighlightGone(BAnim* a)  { scHighlight(a, 0xdeadbeefu, 8); }

static void rAlphaText(BAnim* a)   { scAlpha(a, H_SCROLLING_TEXT, "blurb"); }
static void rAlphaBitmap(BAnim* a) { scAlpha(a, H_WHITEOUT_BAR, "bar"); }
static void rAlphaGone(BAnim* a)   { scAlpha(a, 0xdeadbeefu, "gone"); }

static void rBlurb(BAnim* a)          { scBlurb(a, 0); }
static void rBlurbInterrupt(BAnim* a) { scBlurb(a, 1); }

static void rSelSet0(BAnim* a)        { scSelSet(a, 0); }
static void rSelSet1(BAnim* a)        { scSelSet(a, 1); }

static const Scenario kScenarios[] = {
    { "spline_normal",    rSplineNormal },
    { "spline_early",     rSplineEarly },
    { "spline_late",      rSplineLate },
    { "spline_stuck",     rSplineStuck },
    { "bsin",             rBsin },
    { "slidein",          rSlideIn },
    { "slidein_far",      rSlideInFar },
    { "slidein_empty",    rSlideInEmpty },
    { "slideout",         rSlideOut },
    { "slideout_idle",    rSlideOutIdle },
    { "exit",             rExit },
    { "exit_underscore",  rExitUnder },
    { "highlight",        rHighlight },
    { "highlight_small",  rHighlightSmall },
    { "highlight_loop",   rHighlightLoop },
    { "highlight_gone",   rHighlightGone },
    { "alpha_text",       rAlphaText },
    { "alpha_bitmap",     rAlphaBitmap },
    { "alpha_gone",       rAlphaGone },
    { "blurb",            rBlurb },
    { "blurb_interrupt",  rBlurbInterrupt },
    { "selset_mode0",     rSelSet0 },
    { "selset_mode1",     rSelSet1 },
};
#define NUM_SCENARIOS ((int)(sizeof(kScenarios) / sizeof(kScenarios[0])))

static void runScenario(const Scenario* sc)
{
    BAnim      a;
    BAnimHooks hooks;

    printf("scenario %s\n", sc->name);
    worldReset();
    setupHooks(&hooks);
    banim_init(&a, &hooks);
    // Not 0: TimeStarted 0 means "never started", so a slide built on the
    // very first tick of a run would read as stopped. The original never
    // sees it because RealTimer has been counting since the disc spun up;
    // starting the harness at a plausible mid-run value says so.
    banim_set_clock(&a, 1000000, 0.0f);
    sc->run(&a);
}

int main(int argc, char** argv)
{
    memcpy(g_initial, g_world, sizeof(g_world));
    if (argc < 2) {
        for (int i = 0; i < NUM_SCENARIOS; i++) runScenario(&kScenarios[i]);
        return 0;
    }
    for (int a = 1; a < argc; a++) {
        int found = 0;
        for (int i = 0; i < NUM_SCENARIOS; i++) {
            if (strcmp(kScenarios[i].name, argv[a])) continue;
            runScenario(&kScenarios[i]);
            found = 1;
        }
        if (!found) {
            fprintf(stderr, "unknown scenario: %s\n", argv[a]);
            return 2;
        }
    }
    return 0;
}
