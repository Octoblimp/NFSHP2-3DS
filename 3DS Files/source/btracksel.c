// btracksel -- track select. See btracksel.h.

#include "btracksel.h"

#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "eefpu.h"
#include "eframe.h"
#include "emath.h"
#include "flailer.h"
#include "fredrace.h"
#include "highscore.h"
#include "race.h"
#include "realtime.h"
#include "scenerycull.h"
#include "timer.h"

float btracksel_model_angle;

static BTrackSel* g_m;

// ------------------------------------------------------------ the names

#define OBJ_STRIP          0xfe9485f7u  // its width is the thumbnails' step
#define OBJ_TOD_BAR        0x724e34b0u  // behind the current time of day
#define OBJ_TOD_UP         0xedf2e4eeu
#define OBJ_TOD_DOWN       0x20d73d01u
#define OBJ_SHOW_FRONT     0x883beb15u
#define OBJ_SHOW_BACK      0x886bfd7du
#define OBJ_LENGTH         0x79e8a895u
#define OBJ_ELEVATION      0x20a05a3au
#define OBJ_DIFFICULTY     0x0145f386u
#define OBJ_TRACK_NAME     0xf601f2d4u
#define OBJ_LOGO           0xf60114e4u
#define OBJ_MORE_LEFT      0x84f544f3u
#define OBJ_MORE_RIGHT     0xabb370a6u
#define OBJ_HIGHLIGHT      0xab671c9au
#define GROUP_BEST_LAP     0xabcc6035u
#define OBJ_BEST_LAP       0xf3363be5u
#define GROUP_BEST_TOTAL   0xf4bd8abcu
#define OBJ_BEST_TOTAL     0xae5a12ccu
#define OBJ_BEST_LAPS      0x5cc6e73eu
#define GROUP_LOCKED       0x6a096871u
#define OBJ_LOCKED_MASTER  0xa8af730bu
#define OBJ_LOCKED_FADE    0xbea3c79cu
#define OBJ_LOCKED_TEXT    0x2a67e2d5u
#define OBJ_LOCKED_RECT    0x2a65daf9u
#define OBJ_LAPS           0x7e544804u
#define GROUP_LAPS         0x7e9e3688u
#define GROUP_NORMAL       0xb5caff20u

#define LANG_ELEVATION     0xd6eb
#define LANG_CIRCUIT       0xd994
#define LANG_POINT2POINT   0xd995
#define LANG_BEST_LAPS_N   0xd6f1
#define LANG_BEST_LAPS_1   0xd6e9

// The bitmaps' slots, retail's +32 .. +52.
#define BM_PULSE_A 2   // 0x3b89e410
#define BM_PULSE_B 3   // 0x3489f2a3

// Retail's constants, bit for bit.
#define TICKS        0.00025f           // RealTimer's tick, in seconds
#define TOD_ICON_X   530.0f             // gp-29580
#define TOD_BAR_X    525.0f             // gp-29576
#define THUMB_Y      401.0f             // gp-29572
#define LIST_Y       130.0f
#define THUMB_CENTRE 244.0f
#define TOD_ROW      50.0f
#define LOCK_START   650.0f
#define LOCK_SLIDE   640.0f
#define LOCK_DELAY   0.4f               // gp-19764
#define LOCK_TIME    0.5f               // gp-19768
#define PULSE_RATE   9.0f
#define TWO_PI       0x1.921fb4p+2f     // 0x40c90fda
#define RAD_TO_BAM   0x1.45f306p+13f    // 10430.378, 0x4622f983
#define ANGLE_STEP   0.01f
#define MODEL_SCALE  1.0f
#define KM_PER_MILE  1.6093f
#define M_PER_FOOT   0.3f

static const uint32_t kTODIcon[5] = {
    0x132521f5u, 0xa05ac96cu, 0xdaa55f27u, 0x72da223fu, 0xdaa55f27u,
};
static const int32_t kTODLang[5] = {0xd6e0, 0xd6e1, 0xd6e2, 0xd6e3, 0xd70a};
static const int32_t kDifficultyLang[3] = {0xd6dc, 0xd6dd, 0xd6de};
static const char* const kPickLetter[3] = {"A", "B", "C"};
// TOD 4's entry is past the table in retail; the port reads "".
static const char* const kPickTOD[5] = {"", "_OVERCAST", "_SUNSET", "_NIGHT",
                                        ""};

static const bVector3 kEye  = {25.12f, -2.564f, 16.9f, 0.0f};
static const bVector3 kLook = {2.56f, -0.512f, 0.512f, 0.0f};

// ------------------------------------------------------------ the hooks

static const char* tr(const BTrackSelHooks* h, int32_t id)
{
    const char* s = h->translate ? h->translate(h->user, id) : NULL;
    return s ? s : "";
}

static void speechFade(const BTrackSelHooks* h, float level)
{
    if (h->speechFade) h->speechFade(h->user, level);
}

static int32_t language(const BTrackSelHooks* h)
{
    return h->language ? h->language(h->user) : 0;
}

static void highlightItem(SelectTrackScreen* p, uint32_t item)
{
    const BTrackSelHooks* h = &g_m->hooks;
    if (h->highlightSetItem) h->highlightSetItem(h->user, &p->highlight, item);
}

static void trace(const BTrackSelHooks* h, const char* fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void trace(const BTrackSelHooks* h, const char* fmt, ...)
{
    char    line[160];
    va_list ap;
    if (!h->trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    h->trace(h->user, line);
}

static uint32_t hashf(const char* fmt, ...)
    __attribute__((format(printf, 1, 2)));

static uint32_t hashf(const char* fmt, ...)
{
    char    buf[96];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    return bchunk_hash(buf);
}

// bStringHash(const char *, unsigned int): the hash carried on from `h`.
static uint32_t hashOnto(const char* s, uint32_t h)
{
    while (*s) h = h * 33u + (unsigned char)*s++;
    return h;
}

// ----------------------------------------------- feAlphaAnimation

static int isBitmap(const struct FlailerObjectChunk* o)
{
    return o->ObjectType == FLAILER_TYPE_BITMAP;
}

#define BITMAP(o) ((struct FlailerBitmapChunk*)(void*)(o))

static void fadeInit(BTrackSelFade* f, uint32_t screen)
{
    f->screen = screen;
    f->count  = 0;
}

// AddObject: the object, of any type, and its alphas.
static void fadeAdd(BTrackSelFade* f, uint32_t object)
{
    struct FlailerObjectChunk* o =
        flailer_find_object(f->screen, object, FLAILER_TYPE_ANY);
    int32_t i;
    if (!o || f->count >= BTRACKSEL_MAX_FADE) return;
    f->el[f->count].obj = o;
    for (i = 0; i < 4; i++)
        f->el[f->count].alpha[i] =
            (float)(isBitmap(o) ? flailerbitmap_get_alpha(BITMAP(o), i)
                                : flailerobject_get_alpha(o));
    f->count++;
}

// SetAlphaScale (0x002484c0).
static void fadeScale(BTrackSelFade* f, float s)
{
    int32_t n, i;
    for (n = 0; n < f->count; n++) {
        struct FlailerObjectChunk* o = f->el[n].obj;
        if (isBitmap(o)) {
            for (i = 0; i < 4; i++)
                flailerbitmap_set_alpha(BITMAP(o),
                                        ee_trunc_w(f->el[n].alpha[i] * s), i);
        } else {
            flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0] * s));
        }
    }
}

// The destructor (0x00248518): the alphas put back.
static void fadeRestore(BTrackSelFade* f)
{
    int32_t n, i;
    for (n = 0; n < f->count; n++) {
        struct FlailerObjectChunk* o = f->el[n].obj;
        if (isBitmap(o)) {
            for (i = 0; i < 4; i++)
                flailerbitmap_set_alpha(BITMAP(o),
                                        ee_trunc_w(f->el[n].alpha[i]), i);
        } else {
            flailerobject_set_alpha(o, ee_trunc_w(f->el[n].alpha[0]));
        }
    }
    f->count = 0;
}

// ------------------------------------------------- AnimationGroup

static void slidePlace(BTrackSelSlide* a, int32_t x, int32_t y)
{
    if (a->group)
        flailer_set_group_position(a->screen, a->group, a->master, (float)x,
                                   (float)y);
    else
        flailer_set_top_left_position(a->screen, a->master, x, y);
}

// tCubic1D's SetValDesired, inlined.
static void splineAim(BSpline* s, float v)
{
    s->valDesired = v;
    if (v != s->val) s->state = 2;
}

// tCubic1D's snap to the desired value, inlined.
static void splineSnap(BSpline* s)
{
    s->state = 0;
    s->val   = s->valDesired;
    s->dval  = s->dvalDesired;
}

// SetupToAnimate: jump to `start`, head for `end`.
static void slideSetup(BTrackSelSlide* a, float start, float end)
{
    BSpline* s = &a->spline;
    s->flags = 0;
    splineAim(s, start);
    splineSnap(s);
    splineAim(s, end);
    slidePlace(a, ee_trunc_w(s->val), a->savedY);
}

// The constructor (0x00248568).
static void slideInit(BTrackSelSlide* a, uint32_t screen, uint32_t group,
                      uint32_t master, float start, float end, float duration)
{
    memset(&a->spline, 0, sizeof(a->spline));
    a->spline.arrivalThreshold = 1.0f;
    a->spline.flags            = 1;
    a->spline.duration         = 1.0f;
    a->screen = screen;
    a->group  = group;
    a->master = master;
    flailer_get_top_left_position_int(screen, master, &a->savedX, &a->savedY);
    a->spline.duration = duration;
    slideSetup(a, start, end);
}

static void slideAnimate(BTrackSelSlide* a)
{
    bspline_seek(&a->spline, RealTimeElapsed);
    slidePlace(a, ee_trunc_w(a->spline.val), a->savedY);
}

// The destructor: back where it was laid out.
static void slideRestore(BTrackSelSlide* a)
{
    slidePlace(a, a->savedX, a->savedY);
}

// ------------------------------------------------- the track table

// IsTrackUnavailable (0x0019dd20): the knockouts' game types (5 and 7) run
// no point to point track.
static int isTrackUnavailable(int32_t track)
{
    if (Fred.GameType == 5 || Fred.GameType == 7) {
        TrackInfo* ti = track_get_info(track);
        return ti && ti->Point2Point != 0;
    }
    return 0;
}

// DataSelectTrackScreen::CalculateTrackNumberToLoad (0x0019ddc0): the
// variant of the base track for the time of day.
static int32_t trackNumberToLoad(const int32_t* d)
{
    int32_t i;
    for (i = 0; i <= HighestTrackNumber; i++) {
        TrackInfo* ti = track_get_info(i);
        if (ti && ti->SameAsTrackNumber == d[0] && ti->TimeOfDay == d[3])
            return ti->TrackNumber;
    }
    return d[0];
}

// SelectTrackScreen's Visibility: 0 open, 1 not in this game, 2 locked.
static int32_t visibility(const BTrackSelHooks* h, int32_t track,
                          int32_t dir)
{
    int32_t v = h->isTrackUnlocked && h->isTrackUnlocked(h->user, track, dir)
                    ? 0 : 2;
    if (isTrackUnavailable(track)) v = 1;
    return v;
}

// ------------------------------------------------- SelectableTrack

static TrackInfo* curTODInfo(const BTrackSelTrack* t)
{
    return t->curTOD >= 0 ? t->tod[t->curTOD].ti : NULL;
}

// GetTimeOfDay (0x0019e048): the first variant of that time of day.
static int32_t getTimeOfDay(const BTrackSelTrack* t, int32_t tod)
{
    int32_t i;
    for (i = 0; i < t->nTOD; i++)
        if (t->tod[i].ti->TimeOfDay == tod) return i;
    return -1;
}

// SetTimeOfDay (0x0019e018): stored even when there is none.
static int setTimeOfDay(BTrackSelTrack* t, int32_t tod)
{
    t->curTOD = getTimeOfDay(t, tod);
    return t->curTOD >= 0;
}

// ScrollTimeOfDay (0x0019e0a8): round the list either way.
static int scrollTimeOfDay(BTrackSelTrack* t, int32_t dir)
{
    int32_t old = t->curTOD;
    if (old < 0 || t->nTOD == 0) return 0;
    if (dir == 1) t->curTOD = old + 1 < t->nTOD ? old + 1 : 0;
    else if (dir == -1) t->curTOD = old > 0 ? old - 1 : t->nTOD - 1;
    else return 0;
    return old != t->curTOD;
}

// The constructor (0x0019de58).
static void trackInit(BTrackSelTrack* t, TrackInfo* base, int32_t dir,
                      int32_t vis, float x, uint32_t thumb)
{
    int32_t i;
    float   off = 0.0f;
    memset(t, 0, sizeof(*t));
    t->thumb = thumb;
    t->vis   = vis;
    t->dir   = dir;
    t->x     = x;
    t->ti    = base;
    for (i = 0; i <= HighestTrackNumber; i++) {
        TrackInfo* ti = track_get_info(i);
        if (!ti || ti->SameAsTrackNumber != base->TrackNumber) continue;
        if (t->nTOD >= BTRACKSEL_MAX_TODS) continue;
        t->tod[t->nTOD].ti     = ti;
        t->tod[t->nTOD].offset = off;
        t->nTOD++;
        off += TOD_ROW;
    }
    t->height = off;
    setTimeOfDay(t, 0);
    emodel_init(&t->model, hashf("TRACK%d_MINI", base->TrackNumber));
}

// The destructor (0x0019dfc8).
static void trackDestroy(BTrackSelTrack* t)
{
    emodel_delete(&t->model, 2);
    t->nTOD = 0;
}

// DrawTimeOfDay (0x0019e108): the icons down from y, and the bar behind
// the current one.
static void trackDrawTimeOfDay(BTrackSelTrack* t, uint32_t screen, float y)
{
    int32_t i;
    for (i = 0; i < t->nTOD; i++) {
        int32_t tod = t->tod[i].ti->TimeOfDay;
        struct FlailerObjectChunk* o =
            tod >= 0 && tod < 5
                ? flailer_find_object(screen, kTODIcon[tod],
                                      FLAILER_TYPE_BITMAP)
                : NULL;
        if (!o) continue;
        flailerobject_set_top_left_y(o, y + t->tod[i].offset);
        flailerobject_set_top_left_x(o, TOD_ICON_X);
        flailerobject_set_visibility(o, 1);
    }
    if (t->curTOD >= 0)
        flailer_set_top_left_position(
            screen, OBJ_TOD_BAR, ee_trunc_w(TOD_BAR_X),
            ee_trunc_w(y + t->tod[t->curTOD].offset - 5.0f));
}

// ------------------------------------------- SelectableTrackManager

static BTrackSelTrack* mgrCur(BTrackSelManager* m)
{
    return m->cur >= 0 ? &m->tracks[m->cur] : NULL;
}

// BuildList: every base track forward, then every one backward, each
// thumbnail shown or hidden as it goes.
static void mgrBuildList(BTrackSelManager* m, const BTrackSelHooks* h,
                         uint32_t screen, float width)
{
    int32_t dir, i;
    float   x = 0.0f;
    m->spacing = width;
    for (dir = 0; dir < 2; dir++) {
        for (i = 0; i <= HighestTrackNumber; i++) {
            TrackInfo* ti = track_get_info(i);
            int32_t    vis, track;
            uint32_t   thumb;
            if (!ti || ti->SameAsTrackNumber != ti->TrackNumber) continue;
            track = ti->SameAsTrackNumber;
            vis   = visibility(h, track, dir);
            thumb = dir == 1 ? hashf("TN_TRACK%dR", (int)track)
                             : hashf("TN_TRACK%d", (int)track);
            if (vis == 1) {
                flailer_set_visibility(screen, thumb, 0);
                continue;
            }
            if (h->eggActive && h->eggActive(h->user, track, dir)) vis = 0;
            flailer_set_visibility(screen, thumb, 1);
            if (m->count < BTRACKSEL_MAX_TRACKS)
                trackInit(&m->tracks[m->count++], ti, dir, vis, x, thumb);
            x += m->spacing;
        }
    }
}

// FindTrack: the base track's entry in that direction.
static int32_t mgrFindTrack(BTrackSelManager* m, int32_t track, int32_t dir)
{
    TrackInfo* ti = track_get_info(track);
    int32_t    i;
    if (!ti) return -1;
    for (i = 0; i < m->count; i++)
        if (m->tracks[i].ti->TrackNumber == ti->SameAsTrackNumber
            && m->tracks[i].dir == dir)
            return i;
    return -1;
}

// SetCurrentTrack (0x0019e6d0): that track, or the first; that time of
// day, or the first.
static void mgrSetCurrentTrack(BTrackSelManager* m, int32_t track,
                               int32_t dir, int32_t tod)
{
    int32_t i = mgrFindTrack(m, track, dir);
    if (i < 0) i = m->count ? 0 : -1;
    m->cur = i;
    if (i < 0) return;
    if (!setTimeOfDay(&m->tracks[i], tod)) setTimeOfDay(&m->tracks[i], 0);
}

// ScrollSelectedTrack (0x0019e810): it stops at the ends.
static int mgrScroll(BTrackSelManager* m, int32_t dir)
{
    int32_t n = m->cur;
    if (n < 0) return 0;
    if (dir == 1) {
        if (n + 1 < m->count) n++;
    } else if (dir == -1) {
        if (n > 0) n--;
    }
    if (n == m->cur) return 0;
    m->cur = n;
    return 1;
}

// GetDesiredHoriz (0x0019e880): the current thumbnail in the middle.
static float mgrDesiredHoriz(BTrackSelManager* m)
{
    BTrackSelTrack* t = mgrCur(m);
    return THUMB_CENTRE - (t ? t->x : 0.0f);
}

// DrawThumbnails (0x0019e898).
static void mgrDrawThumbnails(BTrackSelManager* m, uint32_t screen, float x,
                              float y)
{
    int32_t i;
    for (i = 0; i < m->count; i++) {
        flailer_set_top_left_position(screen, m->tracks[i].thumb,
                                      ee_trunc_w(x), ee_trunc_w(THUMB_Y));
        x += m->spacing;
    }
    if (mgrCur(m)) trackDrawTimeOfDay(mgrCur(m), screen, y);
}

static void mgrDestroy(BTrackSelManager* m)
{
    int32_t i;
    for (i = 0; i < m->count; i++) trackDestroy(&m->tracks[i]);
    m->count = 0;
    m->cur   = -1;
}

// --------------------------------------------- SelectTrackSlideshow

static void showLoaded(intptr_t param)
{
    ((BTrackSelShow*)param)->loaded = 1;
}

// Pick: a picture of the track, its direction and its time of day, one of
// three at random, or 0 if TSELECT.BIN has none.
static uint32_t showPick(BTrackSelShow* s, const BTrackSelHooks* h)
{
    char            buf[96];
    BTrackSelTrack* t   = s->track;
    TrackInfo*      cur = curTODInfo(t);
    const char*     dir = t->dir == 1 ? "R_" : "";
    int32_t         r   = bRandomI(3, &bDefaultSeed);
    int32_t         tod = cur ? cur->TimeOfDay : 0;
    uint32_t        hash;
    snprintf(buf, sizeof(buf), "TRACK%d%s%s%s", t->ti->TrackNumber, dir,
             kPickLetter[r >= 0 && r < 3 ? r : 0],
             kPickTOD[tod >= 0 && tod < 5 ? tod : 4]);
    hash = bchunk_hash(buf);
    return h->packHasTexture && h->packHasTexture(h->user, s->pack, hash)
               ? hash : 0;
}

// MaybeTriggerLoad: ten goes at a picture other than the last.
static void showMaybeLoad(BTrackSelShow* s, const BTrackSelHooks* h)
{
    int32_t i;
    for (i = 0; i < 10; i++) {
        uint32_t hash = showPick(s, h);
        if (hash == 0 || hash == s->tex) continue;
        s->loaded = 0;
        if (h->packLoad)
            h->packLoad(h->user, s->pack, hash, showLoaded, (intptr_t)s);
        s->tex = hash;
        break;
    }
}

static void showInit(BTrackSelShow* s, const BTrackSelHooks* h,
                     uint32_t screen)
{
    fadeInit(&s->front, screen);
    fadeInit(&s->back, screen);
    s->screen = screen;
    s->pack   = h->packNew ? h->packNew(h->user) : NULL;
    s->track  = NULL;
    s->t0     = 0;
    s->state  = 0;
    s->tex    = 0;
    s->loaded = 0;
    fadeAdd(&s->front, OBJ_SHOW_FRONT);
    fadeAdd(&s->back, OBJ_SHOW_BACK);
}

static void showDestroy(BTrackSelShow* s, const BTrackSelHooks* h)
{
    if (h->packUnloadAll) h->packUnloadAll(h->user, s->pack);
    if (s->pack && h->packDelete) h->packDelete(h->user, s->pack);
    s->pack = NULL;
    fadeRestore(&s->back);
    fadeRestore(&s->front);
}

static void showSetCurrentTrack(BTrackSelShow* s, const BTrackSelHooks* h,
                                BTrackSelTrack* t)
{
    if (t == s->track) return;
    s->track = t;
    flailer_change_texture(s->screen, OBJ_SHOW_FRONT,
                           hashf("TRACK%d", t->ti->TrackNumber));
    fadeScale(&s->front, 1.0f);
    fadeScale(&s->back, 0.0f);
    s->state = 0;
    s->t0    = RealTimer;
    if (h->packUnloadAll) h->packUnloadAll(h->user, s->pack);
    showMaybeLoad(s, h);
}

// Four seconds a picture, then two cross-fading to the next.
static void showUpdate(BTrackSelShow* s, const BTrackSelHooks* h)
{
    int32_t now = RealTimer;
    if (s->state == 0 && 4.0f < (float)(now - s->t0) * TICKS && s->loaded) {
        s->t1    = now;
        s->state = 1;
    }
    if (s->state != 1) return;
    {
        float f = (float)(now - s->t1) * TICKS * 0.5f;
        if (f < 1.0f) {
            flailer_change_texture(s->screen, OBJ_SHOW_BACK, s->tex);
            fadeScale(&s->front, 1.0f - f);
            fadeScale(&s->back, f);
            flailer_set_visibility(s->screen, OBJ_SHOW_BACK, 1);
        } else {
            flailer_change_texture(s->screen, OBJ_SHOW_FRONT, s->tex);
            fadeScale(&s->front, 1.0f);
            flailer_set_visibility(s->screen, OBJ_SHOW_BACK, 0);
            s->state = 0;
            s->t0    = now;
            showMaybeLoad(s, h);
        }
    }
}

// --------------------------------------------------- TODMenuManager

// SetCurrentTrack: the times of day the track has, as menu items numbered
// from 1 in order (a time of day it lacks hides the next number's item,
// which the next one it has shows again); the current one's item number,
// or -1.
static int32_t todSetCurrentTrack(BTrackSelTODMenu* m,
                                  const BTrackSelHooks* h, BTrackSelTrack* t)
{
    int32_t    r = -1, tod, n = 1;
    TrackInfo* cur;
    if (t == m->track) return -1;
    m->track = t;
    cur      = curTODInfo(t);
    for (tod = 0; tod < 5; tod++) {
        uint32_t item = hashf("MENUITEM_%d", (int)n);
        uint32_t back = hashf("TOD_BACKING_%d", (int)n);
        if (getTimeOfDay(t, tod) >= 0) {
            flailer_set_visibility(m->screen, kTODIcon[tod], 1);
            flailer_set_visibility(m->screen, back, 1);
            flailer_set_visibility(m->screen, item, 1);
            flailer_set_language_id(m->screen, item, (uint32_t)kTODLang[tod]);
            if (cur && cur->TimeOfDay == tod) {
                if (h->setActiveMenuItem) h->setActiveMenuItem(h->user, item);
                r = n;
            }
            n++;
        } else {
            flailer_set_visibility(m->screen, kTODIcon[tod], 0);
            flailer_set_visibility(m->screen, item, 0);
            flailer_set_visibility(m->screen, back, 0);
        }
    }
    return r;
}

// ---------------------------------------------- TrackRecordDisplayer

static void recPrintTime(const BTrackSelHooks* h, const Timer* t, char* buf)
{
    Timer copy = *t;
    timer_print_to_string(&copy, buf, 0, language(h));
}

static int validTime(const Timer* t)
{
    return t->PackedTime != 0 && t->PackedTime != HIGH_SCORE_NO_TIME;
}

// DisplayBestTotal: the best total over the current lap count.
static void recDisplayBestTotal(BTrackSelRecords* r, const BTrackSelHooks* h)
{
    char        buf[64];
    const char* name;
    if (r->cur < 0 || r->n == 0 || Fred.MainMenuOpts[0] != 0) {
        flailer_set_group_visibility(r->screen, GROUP_BEST_TOTAL, 0);
        return;
    }
    if (!validTime(&r->rec[r->cur].table->Time)) return;
    recPrintTime(h, &r->rec[r->cur].table->Time, buf);
    name = fred_lookup_player_name_from_table(&Fred,
                                              r->rec[r->cur].table->NameIndex);
    flailer_printf(r->screen, OBJ_BEST_TOTAL, "%s %s", buf, name ? name : "");
    if (r->rec[r->cur].laps >= 2)
        flailer_printf(r->screen, OBJ_BEST_LAPS, tr(h, LANG_BEST_LAPS_N),
                       r->rec[r->cur].laps);
    else
        flailer_printf(r->screen, OBJ_BEST_LAPS, tr(h, LANG_BEST_LAPS_1));
    flailer_set_group_visibility(r->screen, GROUP_BEST_TOTAL, 1);
}

static void recInit(BTrackSelRecords* r, uint32_t screen)
{
    memset(r, 0, sizeof(*r));
    r->screen = screen;
    r->cur    = -1;
    r->flag   = 1;
}

// SetCurrentTrack: the best lap, then the best totals there are.
static void recSetCurrentTrack(BTrackSelRecords* r, const BTrackSelHooks* h,
                               BTrackSelTrack* t)
{
    static const int32_t kLaps[4] = {1, 2, 4, 8};
    int32_t        num = t->ti->TrackNumber;
    int32_t        dir = t->dir;
    int32_t        cls, i;
    FredHighScore* lap;
    Timer          time;
    const char*    name;

    cls = fpi_get_selected_car_class(&Fred.FrontendPlayers[0]);
    if (Fred.NumPlayerCars == 2) {
        int32_t a = fpi_get_selected_car_class(&Fred.FrontendPlayers[0]);
        int32_t b = fpi_get_selected_car_class(&Fred.FrontendPlayers[1]);
        if (b < a) cls = b;
    }
    lap  = fred_get_best_lap_times_table(&Fred, num, cls, dir);
    time = lap->Time;
    name = fred_lookup_player_name_from_table(&Fred, lap->NameIndex);
    if (validTime(&time) && Fred.MainMenuOpts[0] == 0) {
        char buf[64];
        timer_print_to_string(&time, buf, 0, language(h));
        flailer_set_group_visibility(r->screen, GROUP_BEST_LAP, 1);
        flailer_printf(r->screen, OBJ_BEST_LAP, "%s %s", buf,
                       name ? name : "");
    } else {
        flailer_set_group_visibility(r->screen, GROUP_BEST_LAP, 0);
    }

    r->count = 0;
    if (!t->ti->Point2Point) {
        for (i = 0; i < 4; i++) {
            FredHighScore* tbl =
                fred_get_best_total_times_table(&Fred, num, cls, dir,
                                                kLaps[i]);
            if (!validTime(&tbl->Time)) continue;
            r->rec[r->count].laps  = kLaps[i];
            r->rec[r->count].table = tbl;
            r->count++;
        }
    }
    r->cur  = r->count ? 0 : -1;
    r->n    = r->count;
    recDisplayBestTotal(r, h);
    r->flag = 1;
    r->time = RealTimer;
}

// Five seconds a total, a half-second fade out and a half-second back in
// on the next.
static void recUpdate(BTrackSelRecords* r, const BTrackSelHooks* h)
{
    int32_t now = RealTimer;
    float   e   = (float)(now - r->time) * TICKS;
    if (!(5.0f < e)) return;
    if (r->n < 2) {
        r->time = now;
        r->flag = 1;
    } else if (e < 5.5f) {
        flailer_set_group_alpha(r->screen, GROUP_BEST_TOTAL,
                                ee_trunc_w((5.5f - e) * 2.0f * 128.0f));
    } else if (e < 6.0f) {
        flailer_set_group_alpha(
            r->screen, GROUP_BEST_TOTAL,
            ee_trunc_w((1.0f - (6.0f - e) * 2.0f) * 128.0f));
        if (r->flag) {
            r->cur = r->cur + 1 < r->count ? r->cur + 1 : 0;
            recDisplayBestTotal(r, h);
            r->flag = 0;
        }
    } else {
        r->time = now;
        r->flag = 1;
    }
}

// ---------------------------------------------- TrackLockedDisplayer

static void lockedInit(BTrackSelLocked* l, uint32_t screen)
{
    l->x     = flailer_get_top_left_x(screen, OBJ_LOCKED_MASTER);
    l->alpha = flailer_get_alpha(screen, OBJ_LOCKED_FADE);
    slideInit(&l->slide, screen, GROUP_LOCKED, OBJ_LOCKED_MASTER, LOCK_SLIDE,
              l->x, LOCK_TIME);
    l->screen   = screen;
    l->start    = 0;
    l->track    = NULL;
    l->blurb[0] = 0;
}

static void lockedSetCurrentTrack(BTrackSelLocked* l, const BTrackSelHooks* h,
                                  BTrackSelTrack* t)
{
    if (t == l->track) return;
    l->track = t;
    if (t->vis < 2) {
        flailer_set_group_visibility(l->screen, GROUP_LOCKED, 0);
        flailer_set_visibility(l->screen, OBJ_LOCKED_FADE, 0);
    } else if (t->vis == 2) {
        flailer_set_group_visibility(l->screen, GROUP_LOCKED, 1);
        flailer_set_visibility(l->screen, OBJ_LOCKED_FADE, 1);
        flailer_set_visibility(l->screen, OBJ_TOD_UP, 0);
        flailer_set_visibility(l->screen, OBJ_TOD_DOWN, 0);
    }
    flailer_set_visibility(l->screen, OBJ_LOCKED_TEXT, 0);
    if (h->formatUnlockBlurb)
        h->formatUnlockBlurb(h->user, l->blurb, sizeof(l->blurb),
                             t->ti->TrackNumber, t->dir);
    else
        snprintf(l->blurb, sizeof(l->blurb), "This track should be unlocked");
    slideSetup(&l->slide, LOCK_START, l->x);
    l->start = RealTimer;
}

// The box slides on after 0.4 s and fades in over the half-second slide.
static void lockedUpdate(BTrackSelLocked* l)
{
    float e = (float)(RealTimer - l->start) * TICKS;
    float f = (e - LOCK_DELAY) / LOCK_TIME;
    if (LOCK_DELAY < e) slideAnimate(&l->slide);
    else f = 0.0f;
    flailer_set_alpha(l->screen, OBJ_LOCKED_FADE,
                      f < 1.0f ? ee_trunc_w((float)l->alpha * f) : l->alpha);
}

static void lockedRender(BTrackSelLocked* l, const BTrackSelHooks* h)
{
    if (l->track && l->track->vis != 0 && h->renderTextIntoRectangle)
        h->renderTextIntoRectangle(h->user, l->screen, OBJ_LOCKED_TEXT,
                                   OBJ_LOCKED_RECT, l->blurb, 1.0f);
}

static void lockedDestroy(BTrackSelLocked* l)
{
    slideRestore(&l->slide);
}

// ------------------------------------------------- SelectTrackScreen

static SelectTrackScreen s_screen;

static BTrackSelTrack* cur(SelectTrackScreen* p)
{
    return mgrCur(&p->mgr);
}

// LOGOTRACK%2d, R for backward, _FR in French.
static uint32_t logoHash(const BTrackSelHooks* h, int32_t track, int32_t dir)
{
    uint32_t hash = hashf("LOGOTRACK%2d", (int)track);
    if (dir == 1) hash = hashOnto("R", hash);
    if (language(h) == 1) hash = hashOnto("_FR", hash);
    return hash;
}

static void resyncData(SelectTrackScreen* p)
{
    BTrackSelTrack* t = cur(p);
    TrackInfo*      c;
    if (!t) return;
    c          = curTODInfo(t);
    p->data[0] = t->ti->TrackNumber;
    p->data[2] = t->dir;
    p->data[3] = c ? c->TimeOfDay : 0;
}

// ResyncScreen: everything shown about the current track. The answer is
// the time-of-day menu's item number, or -1.
static int32_t resyncScreen(SelectTrackScreen* p)
{
    const BTrackSelHooks* h = &g_m->hooks;
    BTrackSelTrack*       t = cur(p);
    TrackInfo*            base;
    TrackInfo*            c;
    const char*           fmt;
    const char*           kind;
    int32_t               r;

    if (!t) return -1;
    base = t->ti;
    c    = curTODInfo(t);
    if (!c) c = base;
    fmt  = tr(h, LANG_ELEVATION);
    kind = tr(h, base->Point2Point ? LANG_POINT2POINT : LANG_CIRCUIT);
    if (Fred.DisplayOptionsData.Units == 0) {
        flailer_printf(p->screen, OBJ_LENGTH, "%f %s %s",
                       (double)base->Length, "mi", kind);
        flailer_printf(p->screen, OBJ_ELEVATION, fmt,
                       (double)c->MinElevation, (double)c->MaxElevation,
                       "ft");
    } else {
        flailer_printf(p->screen, OBJ_LENGTH, "%f %s %s",
                       (double)(base->Length * KM_PER_MILE), "km", kind);
        flailer_printf(p->screen, OBJ_ELEVATION, fmt,
                       (double)(c->MinElevation * M_PER_FOOT),
                       (double)(c->MaxElevation * M_PER_FOOT), "m");
    }
    if (c->Difficulty >= 0 && c->Difficulty < 3)
        flailer_set_language_id(p->screen, OBJ_DIFFICULTY,
                                (uint32_t)kDifficultyLang[c->Difficulty]);
    flailer_set_language_id(p->screen, OBJ_TRACK_NAME,
                            (uint32_t)(t->dir == 0
                                           ? c->TrackLanguageID
                                           : c->ReverseTrackLanguageID));
    splineAim(&p->x, mgrDesiredHoriz(&p->mgr));
    if (t->nTOD >= 2) {
        flailer_set_visibility(p->screen, OBJ_TOD_UP, 1);
        flailer_set_visibility(p->screen, OBJ_TOD_DOWN, 1);
        flailer_set_top_left_y(p->screen, OBJ_TOD_DOWN,
                               ee_trunc_w(t->height + LIST_Y));
    } else {
        flailer_set_visibility(p->screen, OBJ_TOD_UP, 0);
        flailer_set_visibility(p->screen, OBJ_TOD_DOWN, 0);
    }
    showSetCurrentTrack(&p->show, h, t);
    r = todSetCurrentTrack(&p->todMenu, h, t);
    recSetCurrentTrack(&p->records, h, t);
    lockedSetCurrentTrack(&p->locked, h, t);
    flailer_change_texture(p->screen, OBJ_LOGO,
                           logoHash(h, base->TrackNumber, t->dir));
    flailer_set_visibility(p->screen, OBJ_MORE_LEFT, p->mgr.cur > 0);
    flailer_set_visibility(p->screen, OBJ_MORE_RIGHT,
                           p->mgr.cur + 1 < p->mgr.count);
    return r;
}

static void stopLapSelector(SelectTrackScreen* p)
{
    p->normal = 1;
    flailer_set_group_visibility(p->screen, GROUP_LAPS, 0);
    flailer_set_group_visibility(p->screen, GROUP_NORMAL, 1);
}

static void startLapSelector(SelectTrackScreen* p)
{
    p->normal = 0;
    flailer_printf(p->screen, OBJ_LAPS, "%d", p->data[1]);
    flailer_set_group_visibility(p->screen, GROUP_LAPS, 1);
    flailer_set_group_visibility(p->screen, GROUP_NORMAL, 0);
    highlightItem(p, OBJ_LAPS);
}

// CanSelectLaps: a circuit, in a single race or a two-player knockout.
static int canSelectLaps(const TrackInfo* ti)
{
    return !ti->Point2Point
           && (Fred.GameType == 3
               || (Fred.GameType == 7 && Fred.NumPlayerCars == 2));
}

// StartRace (0x001a0790): the choice into Fred and the race parameters.
static void startRace(SelectTrackScreen* p)
{
    const BTrackSelHooks* h  = &g_m->hooks;
    RaceParameters*       rp = &TheRaceParameters;
    BTrackSelTrack*       t  = cur(p);

    memcpy(Fred.SelectTrackScreenData, p->data, sizeof(p->data));
    rp->TrackDirection = t->dir;
    rp->Point2Point    = t->ti->Point2Point;
    switch (Fred.GameType) {
        case 3:
            rp->RaceType      = 1;
            rp->NumLapsInRace = p->data[1];
            break;
        case 4:
            rp->RaceType      = 4;
            rp->NumLapsInRace = rp->Point2Point ? 1 : 2;
            break;
        case 5: {
            int32_t laps  = rp->NumAICars + rp->NumPlayerCars - 1;
            rp->RaceType      = 3;
            rp->NumLapsInRace = laps > 0 ? laps : 0;
            break;
        }
        case 6:
            rp->RaceType      = 1;
            rp->NumLapsInRace = 0;
            break;
        case 7:
            rp->RaceType      = 1;
            rp->NumLapsInRace = rp->NumPlayerCars == 1 ? 0 : p->data[1];
            break;
        default:
            break;
    }
    rp->TrackNumber   = trackNumberToLoad(Fred.SelectTrackScreenData);
    rp->EventTreeRace = 0;
    trace(h, "tracksel start race %d dir %d laps %d", (int)rp->TrackNumber,
          (int)rp->TrackDirection, (int)rp->NumLapsInRace);
    if (h->startRace) h->startRace(h->user);
}

// The constructor (0x0019f720), on the screen ACTIVATE names.
static SelectTrackScreen* screenNew(BScreenCallbackData* data)
{
    const BTrackSelHooks* h      = &g_m->hooks;
    SelectTrackScreen*    p      = &s_screen;
    uint32_t              screen = data->itemHash;
    static const uint32_t kBitmaps[6] = {
        0xd1cda594u, 0x9345e4a7u, 0x3b89e410u, 0x3489f2a3u, OBJ_TOD_UP,
        OBJ_TOD_DOWN,
    };
    int32_t i;

    memset(p, 0, sizeof(*p));
    p->x.duration = p->x.arrivalThreshold = 1.0f;
    p->x.flags    = 1;
    p->y.duration = p->y.arrivalThreshold = 1.0f;
    p->y.flags    = 1;
    p->mgr.cur    = -1;
    showInit(&p->show, h, screen);
    p->todMenu.screen = screen;
    p->todMenu.track  = NULL;
    recInit(&p->records, screen);
    lockedInit(&p->locked, screen);
    if (h->highlightInit)
        h->highlightInit(h->user, &p->highlight, screen, OBJ_HIGHLIGHT,
                         (int32_t)BANIM_BLOOM_COLOR);
    p->screen   = screen;
    p->speaking = 0;
    memcpy(p->data, Fred.SelectTrackScreenData, sizeof(p->data));
    // Retail finds them d1cda594, 9345e4a7, edf2e4ee, 20d73d01, 3b89e410,
    // 3489f2a3; the lookups have no side effects.
    for (i = 0; i < 6; i++)
        p->bitmaps[i] = (struct FlailerBitmapChunk*)(void*)flailer_find_object(
            screen, kBitmaps[i], FLAILER_TYPE_BITMAP);
    stopLapSelector(p);
    p->x.flags    = 0;
    p->x.duration = 0.5f;
    p->y.flags    = 0;
    p->y.duration = 0.5f;
    mgrBuildList(&p->mgr, h, screen,
                 (float)flailer_get_width(screen, OBJ_STRIP));
    mgrSetCurrentTrack(&p->mgr, p->data[0], p->data[2], p->data[3]);
    resyncData(p);
    splineAim(&p->x, mgrDesiredHoriz(&p->mgr));
    splineSnap(&p->x);
    splineAim(&p->y, LIST_Y);
    splineSnap(&p->y);
    data->param = resyncScreen(p);
    mgrDrawThumbnails(&p->mgr, screen, mgrDesiredHoriz(&p->mgr), LIST_Y);
    p->phase = 0.0f;
    still_camera_mover_init(&p->mover, 1);
    p->haveMover = 1;
    trace(h, "tracksel up, %d tracks, track %d", (int)p->mgr.count,
          (int)p->data[0]);
    return p;
}

// The destructor (0x0019fb60).
static void screenDelete(SelectTrackScreen* p)
{
    const BTrackSelHooks* h = &g_m->hooks;
    memcpy(Fred.SelectTrackScreenData, p->data, sizeof(p->data));
    if (p->haveMover) still_camera_mover_destroy(&p->mover);
    p->haveMover = 0;
    lockedDestroy(&p->locked);
    showDestroy(&p->show, h);
    mgrDestroy(&p->mgr);
}

static void doTick(SelectTrackScreen* p)
{
    const BTrackSelHooks* h = &g_m->hooks;
    int32_t               alpha;

    mgrDrawThumbnails(&p->mgr, p->screen, p->x.val, p->y.val);
    bspline_seek(&p->x, RealTimeElapsed);
    bspline_seek(&p->y, RealTimeElapsed);
    p->phase += PULSE_RATE * RealTimeElapsed;
    if (TWO_PI < p->phase) p->phase -= TWO_PI;
    alpha = ee_trunc_w((bSinF(p->phase) + 1.0f) * 64.0f);
    if (p->bitmaps[BM_PULSE_A])
        flailerbitmap_set_alpha(p->bitmaps[BM_PULSE_A], alpha, -1);
    if (p->bitmaps[BM_PULSE_B])
        flailerbitmap_set_alpha(p->bitmaps[BM_PULSE_B], alpha, -1);
    p->mover.Eye  = kEye;
    p->mover.Look = kLook;
    btracksel_model_angle += ANGLE_STEP;
    if (TWO_PI < btracksel_model_angle) btracksel_model_angle -= TWO_PI;
    showUpdate(&p->show, h);
    recUpdate(&p->records, h);
    lockedUpdate(&p->locked);
    if (h->highlightAnimate) h->highlightAnimate(h->user, &p->highlight);
}

// The track's miniature, turning, and the locked box's text.
static void doRender(SelectTrackScreen* p)
{
    BTrackSelTrack* t = cur(p);
    bMatrix4*       m = (bMatrix4*)eframe_malloc(sizeof(bMatrix4));
    if (t && t->model.Solid && m) {
        eIdentity(m);
        m->v0.x *= MODEL_SCALE;
        m->v1.y *= MODEL_SCALE;
        m->v2.z *= MODEL_SCALE;
        eRotateZ(m, m,
                 (uint16_t)ee_trunc_w(btracksel_model_angle * RAD_TO_BAM));
        if (gEModelRenderFn) gEModelRenderFn(&t->model, m, NULL, 0);
    }
    lockedRender(&p->locked, &g_m->hooks);
}

// PassJoystickTest: the first pad, and the second with two players.
static int passJoystickTest(const BScreenCallbackData* data)
{
    return data->port == 0 || (data->port == 1 && Fred.NumPlayerCars == 2);
}

static void moved(SelectTrackScreen* p, BScreenCallbackData* data,
                  int32_t noise)
{
    resyncData(p);
    resyncScreen(p);
    data->noise = noise;
}

static void normalCallback(SelectTrackScreen* p, BScreenMessage msg,
                           BScreenCallbackData* data)
{
    const BTrackSelHooks* h = &g_m->hooks;
    BTrackSelTrack*       t = cur(p);

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (!passJoystickTest(data) || !t || t->vis != 0) {
                data->noise = 0;
                break;
            }
            if (canSelectLaps(t->ti)) startLapSelector(p);
            else startRace(p);
            break;
        case BMSG_MENUITEM_HIGHLIGHT:
            highlightItem(p, data->itemHash);
            break;
        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
            if (t && scrollTimeOfDay(t, msg == BMSG_MENUITEM_PAD_UP ? -1 : 1)) {
                moved(p, data, msg == BMSG_MENUITEM_PAD_UP ? 11 : 10);
                highlightItem(p, data->itemHash);
            } else {
                data->noise = 0;
                data->param = 1;
            }
            break;
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT:
            if (mgrScroll(&p->mgr, msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1)) {
                moved(p, data, msg == BMSG_MENUITEM_PAD_LEFT ? 11 : 10);
                speechFade(h, 1.0f);
                p->speaking = 0;
            }
            break;
        case BMSG_MENUITEM_SQUARE:
            if (!t || t->vis != 0) break;
            p->speaking = !p->speaking;
            if (p->speaking) {
                if (h->speakTrack) h->speakTrack(h->user, t->ti->TrackNumber);
            } else {
                speechFade(h, 1.0f);
            }
            break;
        case BMSG_SCREEN_START_BUTTON:
            data->noise = 0;
            break;
        case BMSG_SCREEN_TICK:
            doTick(p);
            break;
        case BMSG_SCREEN_RENDER:
            doRender(p);
            break;
        default:
            break;
    }
}

static void lapCallback(SelectTrackScreen* p, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    const BTrackSelHooks* h = &g_m->hooks;

    switch (msg) {
        case BMSG_MENUITEM_SELECT:
        case BMSG_SCREEN_START_BUTTON:
            if (passJoystickTest(data)) startRace(p);
            else data->noise = 0;
            break;
        case BMSG_MENUITEM_PAD_LEFT:
            data->noise = 1;
            p->data[1] >>= 1;
            if (p->data[1] < 2) p->data[1] = 8;
            flailer_printf(p->screen, OBJ_LAPS, "%d", p->data[1]);
            highlightItem(p, OBJ_LAPS);
            break;
        case BMSG_MENUITEM_PAD_RIGHT:
            data->noise = 2;
            p->data[1] *= 2;
            if (p->data[1] > 8) p->data[1] = 2;
            flailer_printf(p->screen, OBJ_LAPS, "%d", p->data[1]);
            highlightItem(p, OBJ_LAPS);
            break;
        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
            data->noise = 0;
            data->param = 1;
            break;
        case BMSG_SCREEN_BACK_BUTTON:
            stopLapSelector(p);
            data->param = 0;
            data->noise = 6;
            resyncScreen(p);
            highlightItem(p, h->getActiveMenuItem
                                 ? h->getActiveMenuItem(h->user) : 0);
            break;
        case BMSG_SCREEN_TICK:
            doTick(p);
            break;
        default:
            break;
    }
}

void btracksel_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data)
{
    const BTrackSelHooks* h;
    (void)gf;

    if (!g_m) return;
    h = &g_m->hooks;
    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            g_m->screen = screenNew(data);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            if (g_m->screen) screenDelete(g_m->screen);
            g_m->screen = NULL;
            speechFade(h, 1.0f);
            break;
        default:
            if (!g_m->screen) break;
            if (g_m->screen->normal) normalCallback(g_m->screen, msg, data);
            else lapCallback(g_m->screen, msg, data);
            break;
    }
}

int btracksel_active(void)
{
    return g_m && g_m->screen != NULL;
}

static uint32_t fadeTexture(const BTrackSelFade* f)
{
    struct FlailerObjectChunk* o = f->count > 0 ? f->el[0].obj : NULL;
    return o && isBitmap(o) ? BITMAP(o)->TextureHash : 0;
}

void btracksel_show_textures(uint32_t out[2])
{
    const SelectTrackScreen* p = g_m ? g_m->screen : NULL;
    out[0] = p ? fadeTexture(&p->show.front) : 0;
    out[1] = p ? fadeTexture(&p->show.back) : 0;
}

void btracksel_init(BTrackSel* m, const BTrackSelHooks* hooks)
{
    memset(m, 0, sizeof(*m));
    if (hooks) m->hooks = *hooks;
    m->screen = NULL;
    g_m = m;
}
