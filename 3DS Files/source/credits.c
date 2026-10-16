// Options' Credits (credits.h), retail's in its order: CreditsScreen
// (0x001f1f38 .. 0x001f2240), the movie player (0x001f2240 .. 0x001f25c8),
// the markup parser (0x001f25c8 .. 0x001f2a20), CreditsLine (0x001f2a20 ..
// 0x001f2c68), the slideshow behind the names (0x001f2c68 .. 0x001f2e80)
// and CreditsScroller (0x001f2e80 .. 0x001f33b8).

#include "credits.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "banim.h"
#include "bchunk.h"
#include "bmath.h"
#include "bscreens.h"
#include "eventtree.h"
#include "flailer.h"
#include "fred.h"

// ------------------------------------------------------------------ names

// The screens' config names, gp-16944 .. gp-16924.
#define NAME_EA_CREDITS     "EACredits"
#define NAME_BBG_CREDITS    "BBGCredits"
#define NAME_FE_MOVIE       "Credits FE Movie"
#define NAME_REWARD_MOVIE   "Credits Reward movie"
#define NAME_BBG_MOVIE      "BBG Credits movie"
#define NAME_CREATION_MOVIE "BBG Creation movie"

// The movies, gp-16968 .. gp-16948.
#define MOVIE_INTRO_EN  "MOVIES\\INTRO\\NFSINTRO_EN.AVI"
#define MOVIE_INTRO_FR  "MOVIES\\INTRO\\NFSINTRO_FR.AVI"
#define MOVIE_REWARD_EN "MOVIES\\INTRO\\REWARD_EN.AVI"
#define MOVIE_REWARD_FR "MOVIES\\INTRO\\REWARD_FR.AVI"
#define MOVIE_BBG_LOGO  "MOVIES\\INTRO\\BBGLOGO_EN.AVI"
#define MOVIE_MAKING_OF "MOVIES\\INTRO\\MAKEOF_EN.AVI"

// The menus' movie, which CreditsScreen starts as every Options page does.
#define MOVIE_OPTIONS   "MOVIES\\options_movie_new.AVI"

// TheLanguageManager's CurrLanguage for French.
#define LANGUAGE_FRENCH 1

// ------------------------------------------------------- Credits' objects

// The tSlideOnScreen: the panel (its master, the bitmap at 173,123), its
// group, and Options behind it.
#define OBJ_PANEL       0xaed1a723u
#define GROUP_PANEL     0x718cd8c3u
#define SCREEN_OPTIONS  0x95ad096bu
// tHighlightAnimation's spare text, ANIMATING_MENUITEM, and its colour
// (gp-16136, 0x00000080).
#define OBJ_BLOOM       0xab671c9au
#define BLOOM_COLOR     0x00000080u

// MENUITEM_1 .. 5, and how many there are: the item's hash plus
// 0xad1fc60d, unsigned, under 5.
#define ITEM_FIRST      BSCR_ITEM_MENUITEM(1)
#define ITEM_REWARD     BSCR_ITEM_MENUITEM(5)
#define NUM_ITEMS       5

// HandleEvent's table (0x002ba030): each item ChangeToScreen's with the
// current one pushed.
static const char* const kItemScreens[NUM_ITEMS] = {
    NAME_EA_CREDITS,       // Electronic Arts
    NAME_BBG_MOVIE,        // Black Box Games: the logo, then its names
    NAME_FE_MOVIE,         // View Intro Movie
    NAME_CREATION_MOVIE,   // The Making of HP2
    NAME_REWARD_MOVIE,     // View Reward Movie
};

// ------------------------------------------------- the movie's objects

// On the title screen's Flailer screen, which all four movie screens are:
// its two planes, PRESS START and the title's picture.
#define OBJ_PLANE_43    0x3acf2d73u
#define OBJ_PLANE_LB    0xbfaebf79u
#define OBJ_PRESS_START 0xb070dbc9u
#define GROUP_TITLE     0xb73c8d23u

// ---------------------------------------------------- the scroller's

// The names: every text of this group, top to bottom down the panel, each
// cut to the clip poly's box.
#define GROUP_LINES     0xd2638b19u
#define POLY_CLIP       0xa94bd818u
// The slideshow's two bitmaps, the second over the first.
#define OBJ_BG_A        0xf947e681u
#define OBJ_BG_B        0x4ef4d164u

#define MAX_LINES       64

// BuildCredits' ranges of LanguageIDs: Electronic Arts' and Black Box's.
#define EA_FIRST_ID     501000   // 0x7a508
#define EA_LAST_ID      501614   // 0x7a76e
#define BBG_FIRST_ID    601000   // 0x92ba8
#define BBG_LAST_ID     601226   // 0x92c8a

#define FIRST_LINE_Y    240.0f   // 0x43700000
#define MAX_Y_FLOOR     -10.0f   // GetMaxY's start, 0xc1200000
#define SCROLL_SPEED    30.0f    // Animate, pixels a second, 0x41f00000
#define BIG_FONT_SCALE  0.6f     // gp-27880

// The slideshow's clock: seconds as (RealTimer - start) * 0.00025
// (gp-27876); each picture holds four seconds, then fades over one.
#define BG_HOLD         4.0f
#define BG_SWAP         5.0f
#define BG_PICTURES     8
#define BG_TRIES        10

// The pad's: FrontendSoundEvent 28 for a nudge, MENU_SELECT for a pause.
#define SOUND_NUDGE     28

// ------------------------------------------------------------------ state

typedef struct {
    int             live;
    uint32_t        screen;       // +0
    BSlideOnScreen  slide;        // +4
    BHighlightAnim  highlight;    // +76
} CreditsScreen;

// CreditsLine, 12 bytes: a bTNode and its text.
typedef struct {
    struct FlailerTextChunk* text;   // +8
} CreditsLine;

// The unnamed slideshow, 84 bytes.
typedef struct {
    uint32_t   screen;     // +0
    uint32_t   objA;       // +4
    uint32_t   objB;       // +8
    uint32_t   start;      // +12, RealTimer at the last swap
    uint32_t   texture;    // +16, the picture showing or coming
    float      alphaA;     // +20, objA's authored alpha; nothing reads it
    int        pick;       // +24, a new picture is wanted
    BAnimAlpha fadeB;      // +28
    BAnimAlpha fadeA;      // +56
} CreditsBG;

// CreditsScroller, 116 bytes.
typedef struct {
    int         live;
    uint32_t    screen;               // +0
    CreditsLine line[MAX_LINES];      // +4, the bTList
    int         numLines;
    int32_t     lastId;               // +12
    int32_t     firstId;              // +16
    int32_t     nextId;               // +20
    int32_t     which;                // +24, 0 Electronic Arts, 1 Black Box
    int32_t     paused;               // +28
    CreditsBG   bg;                   // +32
} CreditsScroller;

// The movie player's, 16 bytes ("Credits movie player").
typedef struct {
    int         live;
    int         playing;      // the port's: the file was there
    uint32_t    screen;       // +0
    const char* movie;        // +4
    const char* next;         // +12, the screen after, or back
} CreditsMovie;

static CreditsScreen   sScreen;
static CreditsScroller sScroller;
static CreditsMovie    sMovie;

// ------------------------------------------------------------- helpers

static void trace(BGameFlow* gf, const char* fmt, ...)
{
    char    line[192];
    va_list ap;

    if (!gf->hooks.trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    gf->hooks.trace(gf->hooks.user, line);
}

static BAnim* clock(BGameFlow* gf)
{
    if (gf->anim)
        banim_set_clock(gf->anim, (int32_t)gf->realTimer, gf->realElapsed);
    return gf->anim;
}

static const char* screenName(const BGameFlow* gf)
{
    return gf->screen && gf->screen->name ? gf->screen->name : "";
}

static const char* translate(int32_t id)
{
    const char* s = gFredTranslateFn ? gFredTranslateFn(id) : NULL;
    return s ? s : "";
}

// tHighlightAnimation::HandleMessage (0x00248ae0).
static void highlightMessage(BGameFlow* gf, BHighlightAnim* h,
                             BScreenMessage msg,
                             const BScreenCallbackData* data)
{
    BAnim* a = clock(gf);

    if (!a) return;
    if (msg == BMSG_SCREEN_TICK)
        banim_highlight_animate(a, h);
    else if (msg == BMSG_MENUITEM_HIGHLIGHT && data)
        banim_highlight_set_item(a, h, data->itemHash);
}

// ======================================================== CreditsScreen

// The constructor, 0x001f1f38.
static void screenConstruct(BGameFlow* gf, CreditsScreen* c,
                            uint32_t screen)
{
    BAnim* a = clock(gf);
    int    open;

    memset(c, 0, sizeof *c);
    c->live   = 1;
    c->screen = screen;
    if (a) {
        banim_slide_on_init(a, &c->slide, screen, OBJ_PANEL, GROUP_PANEL,
                            SCREEN_OPTIONS);
        banim_highlight_init(a, &c->highlight, screen, OBJ_BLOOM,
                             (int32_t)BLOOM_COLOR);
    }
    bgf_start_movie(gf, MOVIE_OPTIONS);
    // 0x001f2050: both trees' Ultimates won shows the reward's row, and
    // anything less takes it off the menu.
    open = event_trees_both_ultimates_passed() != 0;
    if (gf->hooks.grayMenuItem)
        gf->hooks.grayMenuItem(gf->hooks.user, screen, ITEM_REWARD,
                               open ? BSCR_GRAY_ENABLE : BSCR_GRAY_HIDE);
    trace(gf, "credits ctor %08x, reward %s", (unsigned)screen,
          open ? "open" : "hidden");
}

// The destructor, 0x001f1ff0: the highlight's leaves nothing, and the
// slide's Disappear puts the panel back and hides Options again.
static void screenDestruct(BGameFlow* gf, CreditsScreen* c)
{
    BAnim* a = clock(gf);

    if (!c->live) return;
    if (a) banim_slide_on_disappear(a, &c->slide);
    c->live = 0;
    trace(gf, "credits dtor");
}

// HandleEvent, 0x001f2070.
static void screenEvent(BGameFlow* gf, CreditsScreen* c, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    highlightMessage(gf, &c->highlight, msg, data);
    if (msg == BMSG_MENUITEM_SELECT) {
        uint32_t i = data ? data->itemHash - ITEM_FIRST : NUM_ITEMS;
        if (i >= NUM_ITEMS) return;
        trace(gf, "credits select %s", kItemScreens[i]);
        bgf_change_to_screen(gf, kItemScreens[i], 1);
    } else if (msg == BMSG_SCREEN_TICK) {
        BAnim* a = clock(gf);
        if (a) banim_slide_on_tick(a, &c->slide);
    }
}

void credits_screen_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data)
{
    CreditsScreen* c = &sScreen;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        screenConstruct(gf, c, data ? data->itemHash : CREDITS_SCREEN);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        screenDestruct(gf, c);
        return;
    }
    if (c->live) screenEvent(gf, c, msg, data);
}

// =========================================================== the movies

// 0x001f1ee8 and 0x001f1f10: the French cut for French, else English.
static const char* introMovie(const BGameFlow* gf)
{
    return gf->currLanguage == LANGUAGE_FRENCH ? MOVIE_INTRO_FR
                                               : MOVIE_INTRO_EN;
}

static const char* rewardMovie(const BGameFlow* gf)
{
    return gf->currLanguage == LANGUAGE_FRENCH ? MOVIE_REWARD_FR
                                               : MOVIE_REWARD_EN;
}

static void objectVisible(uint32_t screen, uint32_t object, int visible)
{
    flailer_set_visibility(screen, object,
                           visible ? FLAILER_OBJECT_VISIBLE
                                   : FLAILER_OBJECT_INVISIBLE);
}

// The constructor, 0x001f2240. The making-of fills the 4:3 plane and the
// rest the letterboxed one. The jukebox and the menus' movie stop, and
// the player takes the file.
static void movieConstruct(BGameFlow* gf, CreditsMovie* m, uint32_t screen,
                           const char* movie, const char* next)
{
    int fullScreen = strcmp(movie, MOVIE_MAKING_OF) == 0;

    memset(m, 0, sizeof *m);
    m->live   = 1;
    m->screen = screen;
    m->movie  = movie;
    objectVisible(screen, OBJ_PLANE_43, fullScreen);
    objectVisible(screen, OBJ_PLANE_LB, !fullScreen);
    if (gf->hooks.jukebox) gf->hooks.jukebox(gf->hooks.user, 0);
    bgf_stop_movie(gf);
    // MoviePlayer::InitFile. A file that is not on the card is a movie
    // that has already ended, as the title's are (gameflow.c).
    m->playing = gf->hooks.movieOpen
                 && gf->hooks.movieOpen(gf->hooks.user, movie);
    objectVisible(screen, OBJ_PRESS_START, 0);
    flailer_set_group_visibility(screen, GROUP_TITLE,
                                 FLAILER_OBJECT_INVISIBLE);
    m->next = next;
    trace(gf, "credits movie %s %s, then %s", movie,
          m->playing ? "open" : "missing", next ? next : "back");
}

// MoviePlayer::Close, without the port's log twice.
static void movieClose(BGameFlow* gf, CreditsMovie* m)
{
    if (!m->playing) return;
    if (gf->hooks.movieClose) gf->hooks.movieClose(gf->hooks.user);
    m->playing = 0;
}

// The destructor, 0x001f2358: the player closed, the jukebox back on.
static void movieDestruct(BGameFlow* gf, CreditsMovie* m)
{
    if (!m->live) return;
    movieClose(gf, m);
    if (gf->hooks.jukebox) gf->hooks.jukebox(gf->hooks.user, 1);
    m->live = 0;
    trace(gf, "credits movie dtor");
}

// 0x001f23b8: Black Box's logo goes on to its names, and the rest back to
// the Credits menu.
static void movieDone(BGameFlow* gf, CreditsMovie* m)
{
    const char* next = m->next;

    trace(gf, "credits movie done, %s", next ? next : "back");
    if (next) bgf_change_to_screen(gf, next, 0);
    else      bgf_move_back_screen(gf, 1);
}

// HandleEvent, 0x001f23d8, with its table at 0x002ba050: A ends the
// movie, the pad and START are silenced, and each tick drives it.
static void movieEvent(BGameFlow* gf, CreditsMovie* m, BScreenMessage msg,
                       BScreenCallbackData* data)
{
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        movieDone(gf, m);
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
    case BMSG_SCREEN_START_BUTTON:
        if (data) data->noise = 0;
        return;
    case BMSG_SCREEN_TICK: {
        // DriveMovie: 1 when it has finished.
        int done = !m->playing || !gf->hooks.movieDrive
                   || gf->hooks.movieDrive(gf->hooks.user) == 1;
        if (!done) return;
        movieClose(gf, m);
        movieDone(gf, m);
        return;
    }
    default:
        return;
    }
}

// Callback, 0x001f2470: the movie and where it goes by the name the
// screen was entered under.
void credits_movie_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data)
{
    CreditsMovie* m = &sMovie;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        const char* name  = screenName(gf);
        const char* movie = NULL;
        const char* next  = NULL;
        if (strcmp(name, NAME_FE_MOVIE) == 0) {
            movie = introMovie(gf);
        } else if (strcmp(name, NAME_REWARD_MOVIE) == 0) {
            movie = rewardMovie(gf);
        } else if (strcmp(name, NAME_CREATION_MOVIE) == 0) {
            movie = MOVIE_MAKING_OF;
        } else if (strcmp(name, NAME_BBG_MOVIE) == 0) {
            movie = MOVIE_BBG_LOGO;
            next  = NAME_BBG_CREDITS;
        }
        if (!movie) {
            // Retail reads through the NULL; nothing enters these
            // screens under another name.
            trace(gf, "credits movie: no movie for %s", name);
            return;
        }
        movieConstruct(gf, m, data ? data->itemHash : 0, movie, next);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        movieDestruct(gf, m);
        return;
    }
    if (m->live) movieEvent(gf, m, msg, data);
}

// ============================================================ the markup

// 0x001f25c8: up to `stop`, which is left where the copy ended. Retail
// has no check for the terminator; this stops there too.
static const char* copyUntil(char* dst, int size, const char* src, char stop)
{
    int n = 0;

    while (*src != stop && *src) {
        if (n + 1 < size) dst[n++] = *src;
        src++;
    }
    dst[n] = '\0';
    return src;
}

// 0x001f2648 and 0x001f2688: to the next digit or letter, or the end.
static const char* skipToDigit(const char* p)
{
    while (*p && !(*p >= '0' && *p <= '9')) p++;
    return p;
}

static const char* skipToLetter(const char* p)
{
    while (*p && !((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')))
        p++;
    return p;
}

// 0x001f26c8: "(r,g,b)", each 128 when it is missing, as an RGBA word
// with the PS2's full alpha.
static uint32_t parseRGB(const char* arg)
{
    char        tmp[32];
    long        c[3] = { 128, 128, 128 };
    const char* p    = skipToDigit(arg);
    int         i;

    for (i = 0; i < 3 && *p; i++) {
        p    = skipToDigit(copyUntil(tmp, sizeof tmp, p, i < 2 ? ',' : ')'));
        c[i] = strtol(tmp, NULL, 10);
    }
    return 0x80000000u | ((uint32_t)c[2] << 16) | ((uint32_t)c[1] << 8)
           | (uint32_t)c[0];
}

// 0x001f27b8: "(NAME)" as the name's hash, or 0 with no name.
static uint32_t parseFont(const char* arg)
{
    char        tmp[32];
    const char* p = skipToLetter(arg);

    if (!*p) return 0;
    copyUntil(tmp, sizeof tmp, p, ')');
    return bchunk_hash(tmp);
}

// 0x001f2808. A tag's argument goes, brackets and all, to its own buffer
// of 32; everything outside a tag to `buf`.
void credits_parse(uint32_t* color, uint32_t* font, char* buf, int len,
                   const char* src)
{
    char        fontArg[32], rgbArg[32];
    char*       arg     = NULL;   // s0, where a tag's argument goes
    char*       argEnd  = NULL;
    int         inParen = 0;      // s3
    int         isFont  = 0;      // s5
    int         isRgb   = 0;      // s6
    int         inTag   = 0;      // s7
    int         n       = 0;
    const char* p       = src;

    memset(fontArg, 0, sizeof fontArg);
    memset(rgbArg, 0, sizeof rgbArg);
    memset(buf, 0, (size_t)len);
    while (*p) {
        char        c    = *p;
        const char* next = p + 1;

        if (c == '$') {
            if (p[1] == '$') {
                // "$$" is the dollar itself.
                p++;
                c    = *p;
                next = p + 1;
            } else {
                if (strncmp("FONT", next, 4) == 0) isFont = 1;
                if (strncmp("RGB", next, 3) == 0)  isRgb  = 1;
                if (isFont || isRgb) inTag = 1;
            }
        }
        if (c == '(') inParen = inTag ? 1 : inParen;
        if (!inTag && !inParen) {
            if (n + 1 < len) buf[n++] = c;
        }
        if (inParen) {
            if (isFont && !arg) arg = fontArg, argEnd = fontArg + 31;
            if (isRgb && !arg)  arg = rgbArg, argEnd = rgbArg + 31;
        }
        if (arg && arg < argEnd) *arg++ = c;
        p = next;
        if (c == ')') {
            inParen = inTag = isRgb = isFont = 0;
            arg     = NULL;
        }
    }
    if (rgbArg[0])  *color = parseRGB(rgbArg);
    if (fontArg[0]) *font  = parseFont(fontArg);
}

// ============================================================ CreditsLine

// SetLanguageID, 0x001f2a30: the line's string from its markup, at `y`.
// Returns its height.
static float lineSet(CreditsLine* l, int32_t id, float y)
{
    struct FlailerTextChunk*   t     = l->text;
    struct FlailerObjectChunk* o     = &t->Object;
    uint32_t                   color = 0, font = 0;
    char                       buf[256];

    credits_parse(&color, &font, buf, (int)sizeof buf, translate(id));
    flailertext_set_color(t, color ? color : 0x80808080u);
    if (font == bchunk_hash("FONT_IMPACTBIG")
        || font == bchunk_hash("FONT_IMPACTNORMAL")) {
        flailerobject_set_scale_x(o, BIG_FONT_SCALE);
        flailerobject_set_scale_y(o, BIG_FONT_SCALE);
        o->DirtyFlag = 1;
        t->FontHash  = font;
    } else {
        flailerobject_set_scale_x(o, 1.0f);
        flailerobject_set_scale_y(o, 1.0f);
        t->FontHash  = bchunk_hash("FONT_STATS");
        o->DirtyFlag = 1;
    }
    if (color || font) flailertext_set_string(t, buf);
    else               flailertext_set_language_id(t, (uint32_t)id);
    flailerobject_set_top_left_y(o, y);
    flailerobject_set_clip_to_poly(o, POLY_CLIP);
    return flailerobject_get_height_float(o);
}

// Animate, 0x001f2bc8: up the panel at 30 a second.
static void lineAnimate(CreditsLine* l, float dt)
{
    float x, y;

    flailerobject_get_top_left(&l->text->Object, &x, &y);
    flailerobject_set_top_left_y(&l->text->Object, y - dt * SCROLL_SPEED);
}

// PleaseResetMe, 0x001f2c20: off the top of the screen.
static int lineGone(CreditsLine* l)
{
    float x, y;

    flailerobject_get_top_left(&l->text->Object, &x, &y);
    return y < 0.0f;
}

// ============================================================ the slideshow

// The constructor, 0x001f2c68: the second picture faded right out.
static void bgInit(BGameFlow* gf, CreditsBG* b, uint32_t screen,
                   uint32_t objA, uint32_t objB)
{
    BAnim* a = clock(gf);

    memset(b, 0, sizeof *b);
    if (a) {
        banim_alpha_init(a, &b->fadeB, screen, objB);
        banim_alpha_init(a, &b->fadeA, screen, objA);
    }
    b->screen  = screen;
    b->objA    = objA;
    b->objB    = objB;
    b->start   = gf->realTimer;
    b->texture = bchunk_hash("CREDITS_BG1");
    b->alphaA  = (float)flailer_get_alpha(screen, objA);
    b->pick    = 1;
    flailer_set_alpha(screen, objB, 0);
}

// The destructor (0x001f59f0): the two fades' saved alphas back.
static void bgRelease(BGameFlow* gf, CreditsBG* b)
{
    BAnim* a = clock(gf);

    if (!a) return;
    banim_alpha_release(a, &b->fadeA);
    banim_alpha_release(a, &b->fadeB);
}

// 0x001f2d28: one of CREDITS_BG1..8 that is not `current`, in ten tries.
static uint32_t bgPick(uint32_t current)
{
    char name[24];
    int  i;

    for (i = 0; i < BG_TRIES; i++) {
        uint32_t h;
        snprintf(name, sizeof name, "CREDITS_BG%d",
                 (int)bRandomI(BG_PICTURES, bViewSeed) + 1);
        h = bchunk_hash(name);
        if (h != current) return h;
    }
    return current;
}

// Tick, 0x001f2d90: four seconds on a picture, then the next fades in
// over one, then the first plane takes it and the clock starts again.
static void bgTick(BGameFlow* gf, CreditsBG* b)
{
    BAnim* a = clock(gf);
    float  t = (float)(int32_t)(gf->realTimer - b->start) * 0.00025f;

    if (b->pick) {
        b->texture = bgPick(b->texture);
        b->pick    = 0;
    }
    if (!(t > BG_HOLD)) return;
    if (t > BG_SWAP) {
        flailer_change_texture(b->screen, b->objA, b->texture);
        b->pick  = 1;
        b->start = gf->realTimer;
        return;
    }
    t -= BG_HOLD;
    flailer_change_texture(b->screen, b->objB, b->texture);
    if (a) {
        banim_alpha_set_scale(a, &b->fadeB, t);
        banim_alpha_set_scale(a, &b->fadeA, 1.0f - t);
    }
}

// ======================================================== CreditsScroller

// GetMaxY, 0x001f30f8: the lowest bottom of a line, -10 at the least.
static float scrollerMaxY(CreditsScroller* s)
{
    float maxY = MAX_Y_FLOOR;
    int   i;

    for (i = 0; i < s->numLines; i++) {
        struct FlailerObjectChunk* o = &s->line[i].text->Object;
        float x, y, bottom;
        flailerobject_get_top_left(o, &x, &y);
        bottom = y + flailerobject_get_height_float(o);
        if (maxY < bottom) maxY = bottom;
    }
    return maxY;
}

// BuildCredits, 0x001f2fa0: a line for each text of the group, then the
// first ids stacked down from 240.
static void scrollerBuild(BGameFlow* gf, CreditsScroller* s, int which)
{
    struct FlailerObjectChunk* o = NULL;
    float                      y = FIRST_LINE_Y;
    int                        i;

    s->lastId = s->firstId = s->nextId = 0;
    if (which == 0) {
        s->lastId  = EA_LAST_ID;
        s->firstId = s->nextId = EA_FIRST_ID;
    } else if (which == 1) {
        s->lastId  = BBG_LAST_ID;
        s->firstId = s->nextId = BBG_FIRST_ID;
    }
    s->numLines = 0;
    while ((o = flailer_find_object_by_group(s->screen, GROUP_LINES,
                                             FLAILER_TYPE_TEXT, o)) != NULL) {
        if (s->numLines >= MAX_LINES) break;
        s->line[s->numLines++].text = (struct FlailerTextChunk*)o;
    }
    for (i = 0; i < s->numLines; i++)
        y += lineSet(&s->line[i], s->nextId++, y);
    trace(gf, "credits build %d: %d lines, ids %d..%d", which, s->numLines,
          (int)s->firstId, (int)s->lastId);
}

// Tock, 0x001f31a8: each line up by `dt` of scrolling, and a line off the
// top takes the next id below the lowest, round to the first after the
// last.
static void scrollerTock(CreditsScroller* s, float dt)
{
    int i;

    for (i = 0; i < s->numLines; i++) {
        CreditsLine* l = &s->line[i];
        if (lineGone(l)) {
            int32_t id = s->nextId++;
            lineSet(l, id, scrollerMaxY(s));
            if (s->lastId < s->nextId) s->nextId = s->firstId;
        } else {
            lineAnimate(l, dt);
        }
    }
}

// The constructor, 0x001f2e80: Electronic Arts' names or Black Box's by
// the name the screen was entered under, and the menus' movie stopped.
static void scrollerConstruct(BGameFlow* gf, CreditsScroller* s,
                              uint32_t screen)
{
    const char* name = screenName(gf);

    memset(s, 0, sizeof *s);
    s->live = 1;
    bgInit(gf, &s->bg, screen, OBJ_BG_A, OBJ_BG_B);
    s->screen = screen;
    s->which  = 1;
    if (strcmp(name, NAME_EA_CREDITS) == 0) s->which = 0;
    if (strcmp(name, NAME_BBG_CREDITS) == 0) s->which = 1;
    scrollerBuild(gf, s, s->which);
    bgf_stop_movie(gf);
    s->paused = 0;
}

// The destructor, 0x001f2f40.
static void scrollerDestruct(BGameFlow* gf, CreditsScroller* s)
{
    if (!s->live) return;
    bgRelease(gf, &s->bg);
    s->live = 0;
    trace(gf, "credits scroller dtor");
}

// HandleEvent, 0x001f3268, with its table at 0x002ba120: A is silent, the
// pad nudges the names on a second's worth, SQUARE pauses them, and each
// tick scrolls them and the slideshow.
static void scrollerEvent(BGameFlow* gf, CreditsScroller* s,
                          BScreenMessage msg, BScreenCallbackData* data)
{
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        if (data) data->noise = 0;
        return;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
        if (data) data->noise = SOUND_NUDGE;
        scrollerTock(s, 1.0f);
        return;
    case BMSG_MENUITEM_SQUARE:
        if (data) data->noise = BSND_MENU_SELECT;
        s->paused = s->paused == 0;
        trace(gf, "credits %s", s->paused ? "paused" : "rolling");
        return;
    case BMSG_SCREEN_TICK:
        if (!s->paused) scrollerTock(s, gf->realElapsed);
        bgTick(gf, &s->bg);
        return;
    default:
        return;
    }
}

void credits_scroller_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data)
{
    CreditsScroller* s = &sScroller;

    if (msg == BMSG_SCREEN_ACTIVATE) {
        scrollerConstruct(gf, s, data ? data->itemHash
                                       : CREDITS_SCROLLER_SCREEN);
        return;
    }
    if (msg == BMSG_SCREEN_UNACTIVATE) {
        scrollerDestruct(gf, s);
        return;
    }
    if (s->live) scrollerEvent(gf, s, msg, data);
}
