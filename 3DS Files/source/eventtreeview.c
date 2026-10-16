// eventtreeview -- retail's tEventTreeView, "View Event Tree". See
// eventtreeview.h and docs/formats/event-tree-view.md.
//
// Retail keeps the leaves, groups and object lists on bTLists and bPLists
// of bMalloc'd nodes; the port keeps them in fixed arrays in the one view,
// in the same order. The class names are kept in the comments.

#include "eventtreeview.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "cartypeinfo.h"
#include "emath.h"
#include "eventrace.h"
#include "fred.h"
#include "fredevent.h"
#include "race.h"
#include "startrace.h"
#include "track.h"

#define ETV_MAX_LEAVES   40
#define ETV_MAX_LINKS    16
#define ETV_MAX_OBJS     8
#define ETV_MAX_GROUPS   40
#define ETV_MAX_BARS     40

// The objects.
#define OBJ_TITLE          0xa01f24f0u   // the tree's name
#define OBJ_CLIP_BOX       0xaa5d7d3fu   // the tree's window
#define OBJ_EVENT_PANEL    0xa3b23510u   // the template leaf's panel
#define OBJ_EVENT_NUMBER   0x16b7d629u   // and its number
#define OBJ_HLINE          0x02eca94fu
#define OBJ_VLINE          0x03ea005du
#define OBJ_SMALL_NUMBER   0xcea3b7c2u   // the event blurb's "Event %d"
#define OBJ_STATUS         0x87cfd6c6u
#define OBJ_REWARD         0x35b77247u
#define OBJ_WHITEOUT_BAR   0x70a404ecu
#define OBJ_HELP_ICON      0x027f7503u
#define OBJ_HELP_TEXT      0x0880ac4cu
#define OBJ_CAR_LOGO       0xc6398c48u
#define OBJ_TRACK_LOGO     0xf60114e4u
#define OBJ_TRACK_NAME     0xf601f2d4u
#define OBJ_TRACK_LABEL    0x03c8f634u
#define OBJ_RECT_TEXT      0x7a31036bu   // RenderTextIntoRectangle's text
#define OBJ_RECT_BOX       0x7ad2801eu   // and its box
#define OBJ_REWARD_NAME    0x7e428084u

#define GROUP_LEAF         0xa01bcdc6u   // the template leaf
#define GROUP_EVENT_BLURB  0xa2a16ea1u   // tEventBlurb's panel
#define GROUP_DETAILS      0x2d3f3165u
#define GROUP_REWARD       0x461d42d0u

// eViewStates.
enum {
    VS_TREE = 0,
    VS_TRANSIT_TO_DETAILS = 1,
    VS_DETAILS = 2,
    VS_TRANSIT_TO_TREE = 3,
    VS_TRANSIT_TO_REWARD = 4,
    VS_REWARD = 5,
    VS_TRANSIT_FROM_REWARD = 6,
    VS_POPUP = 7,
};

// The FrontendSoundEvents the view answers with.
#define SND_NONE       0
#define SND_POPUP_OK   5
#define SND_NO_REWARD  8
#define SND_UP_DOWN    19
#define SND_LEFT_RIGHT 20
#define SND_SELECT     21
#define SND_START      22
#define SND_LOCKED     23
#define SND_REWARD     24

static const EtvHooks* s_h;

// ------------------------------------------------------------- the tables

// 0x0031b240: each event's default x, by its number less one. .data
// zeros, and filled by the constructor from the tree's layout string; an
// event the string has no mark for keeps the last tree's value.
static float s_hTable[32];

// 0x0031b3c0 (the World Championship's) and 0x0031b490 (Ultimate Road
// Racer's): ten rows of twenty columns, an x for each event in number
// order, read across.
static const char kLayoutChampionship[201] =
    "        x               x       x         x   x  x  x  x     x x   x "
    "x   x   x  x  x  x x x    x   xx  x   x x x     x       x       x    "
    "          x                   x                   x           ";
static const char kLayoutHotPursuit[201] =
    "        x               x       x         x   x x x   x      x x    x"
    "  x  x  x   x    x   x x x x  xx x      x   x x x       x          x "
    "          x                   x                   x           ";

// The colours (the static initializer, 0x001fb790): r, g, b, a.
static const bVector4 kColourOpen   = { 0.0f, 80.0f, 0.0f, 80.0f };   // 0x0031b560
static const bVector4 kColourLocked = { 60.0f, 0.0f, 0.0f, 80.0f };   // 0x0031b570
static const bVector4 kColourGrey   = { 128.0f, 128.0f, 128.0f, 128.0f }; // 0x0031b590

// The car logos' slots, 0x0031b5b0 and after it.
static const float kLogoY[4] = { 70.0f, 150.0f, 210.0f, 260.0f };
static const float kLogoX[2] = { 140.0f, 280.0f };

// The help menus (0-terminated).
static const int32_t kHelpChampTree[]   = { 800033, 800034, 800035, 0 }; // 0x0031a590
static const int32_t kHelpChampDetail[] = { 800037, 800038, 801000, 0 }; // 0x0031a5a0
static const int32_t kHelpResume[]      = { 800038, 801000, 800041, 0 }; // 0x0031a5b0
static const int32_t kHelpHPTree[]      = { 800045, 800046, 800047, 0 }; // 0x0031a5d8
static const int32_t kHelpHPDetail[]    = { 800049, 800050, 801001, 0 }; // 0x0031a5e8
static const int32_t kHelpChampReward[] = { 800044, 0 };                 // 0x00331538
static const int32_t kHelpHPReward[]    = { 800052, 0 };                 // 0x00331540

// The status names, 0x002ba930.
static const int32_t kStatusNames[5] = { 62000, 62001, 62002, 62003, 62004 };

// The zoom table (gp-16760).
static const float kZoom[2] = { 0.4f, 1.0f };

// ------------------------------------------------------------ the classes

// tEventLeaf, 96 bytes in retail.
typedef struct EtvLeaf {
    EventInfo* info;
    int32_t    nIndex;
    bVector4   center;
    struct FlailerBitmapChunk* master;
    float      masterCx, masterCy;
    struct FlailerObjectChunk* objs[ETV_MAX_OBJS];
    int        nObjs;
    int32_t    generation;
    float      scaleFactor;
    uint32_t   icon;            // retail's pTextureInfo, kept as the hash
    char       rewardName[64];
    struct EtvLeaf* parents[ETV_MAX_LINKS];
    int        nParents;
    struct EtvLeaf* children[ETV_MAX_LINKS];
    int        nChildren;
} EtvLeaf;

typedef struct EtvBar {
    float    x1, x2, y;
    bVector4 colour;
} EtvBar;

// tEventGroup, 40 bytes in retail: a parent and the children it opens,
// joined by a bar.
typedef struct EtvGroup {
    EtvLeaf* members[ETV_MAX_LINKS + 1];
    int      nMembers;
    EtvLeaf* top[ETV_MAX_LINKS + 1];      // retail's +16: the lowest generation
    int      nTop;
    EtvLeaf* bottom[ETV_MAX_LINKS + 1];   // +24: the highest
    int      nBottom;
    EtvBar   bars[ETV_MAX_LINKS + 1];
    int      nBars;
} EtvGroup;

// tEventBlurb, 20 bytes: the panel beside the tree with the event's
// number, status and reward.
typedef struct EtvEventBlurb {
    EventInfo* active;
    uint32_t   screen;
    struct FlailerObjectChunk* master;
    int32_t    newEventTime;
    float      startAlpha;
} EtvEventBlurb;

// tTreeDetails, 596 bytes.
typedef struct EtvDetails {
    struct FlailerObjectChunk* objs[ETV_MAX_OBJS];
    int        nObjs;
    EventInfo* lastKnown;
    char       description[512];
    uint32_t   screen;
    EventTree* tree;
} EtvDetails;

// tTreeReward, 16 bytes.
typedef struct EtvReward {
    uint32_t   screen;
    struct FlailerObjectChunk* objs[ETV_MAX_OBJS];
    int        nObjs;
    EventTree* tree;
} EtvReward;

// The car logos' slideshow, 64 bytes.
typedef struct EtvCarLogos {
    uint32_t screen;
    int32_t  timer;
    uint32_t hashes[8];
    int32_t  count, index, flag;
    float    alpha;
    int32_t  y, x;
} EtvCarLogos;

// The track logo, 84 bytes.
typedef struct EtvTrackLogo {
    uint32_t screen;
    uint32_t hashes[12];
    int32_t  count, index;
    float    origX;
    int32_t  timer;
    float    alpha;
    int32_t  flag;
} EtvTrackLogo;

// The help popup.
typedef struct EtvPopup {
    uint32_t screen;
    struct FlailerObjectChunk* objs[ETV_MAX_OBJS];
    int      nObjs;
    char     text[512];
} EtvPopup;

// tEventTreeView, 2144 bytes.
typedef struct EtvView {
    BGameFlow*    gf;
    EventTree*    tree;
    uint32_t      screen;
    EtvLeaf       leaves[ETV_MAX_LEAVES];
    int           nLeaves;
    EtvGroup      groups[ETV_MAX_GROUPS];
    int           nGroups;
    EtvLeaf*      cur;
    EtvEventBlurb eventBlurb;
    bMatrix4      viewMatrix;
    float         indicatorAnimate;
    int32_t       viewState;
    BSpline       zoom;
    BSpline2D     pan;
    BSpline       alpha;
    int32_t       zoomIndex;
    EtvDetails    details;
    int32_t       idleOnLeafTimer;
    BSpline2D     parallaxer;
    float         clipMin[2], clipMax[2];
    BBlurb        blurby;
    EtvReward     reward;
    EtvCarLogos   carLogos;
    EtvTrackLogo  trackLogo;
    EtvPopup      popup;
} EtvView;

static EtvView s_view;
static int     s_live;

// SetFlailerTextClipWindow / ResetFlailerTextClipWindow (0x001417b0): the
// window RenderSingleFlailerBitmap and RenderFlailerText clip to, (0, 0)
// to (644, 480) when reset.
static float s_clip[4] = { 0.0f, 0.0f, 644.0f, 480.0f };

// ---------------------------------------------------------------- helpers

static void trace(const char* fmt, ...)
{
    char    line[160];
    va_list ap;

    if (!s_h || !s_h->trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    s_h->trace(s_h->user, line);
}

static const char* translate(int32_t id)
{
    const char* s = s_h && s_h->translate ? s_h->translate(s_h->user, id)
                                          : NULL;
    return s ? s : "";
}

static const char* translateString(const char* s)
{
    const char* t = s_h && s_h->translateString
                        ? s_h->translateString(s_h->user, s) : NULL;
    return t ? t : s;
}

static BAnim* anim(void)
{
    return s_h && s_h->anim ? s_h->anim(s_h->user) : NULL;
}

static void setHelpOverride(const int32_t* lines)
{
    if (s_h && s_h->setHelpOverride) s_h->setHelpOverride(s_h->user, lines);
}

static int32_t realTimer(void)
{
    return s_view.gf ? (int32_t)s_view.gf->realTimer : 0;
}

// Timer::SetTime (0x00136dd0): seconds into ticks of 1/4000 s.
static int32_t ticks(float seconds)
{
    return (int32_t)(seconds * 4000.0f + 0.5f);
}

static float secondsSince(int32_t timer)
{
    return (float)(realTimer() - timer) * 0.00025f;
}

static int32_t statusOf(const EventInfo* e)
{
    return e ? event_info_get_status(e, NULL) : 0;
}

static uint32_t trackWord(const uint8_t* b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16
           | (uint32_t)b[3] << 24;
}

// GetTheRightTrackLanguageID(int, eTrackDirection) (0x001dc5a8).
static int32_t trackLanguageId(int32_t track, int32_t dir)
{
    const TrackInfo* ti = track_get_info(track);
    return ti ? get_the_right_track_language_id(ti, dir) : 0;
}

// The cubic's SetValDesired: state 2 when it has somewhere to go.
static void aim(BSpline* s, float v)
{
    s->valDesired = v;
    if (v != s->val) s->state = 2;
}

static void snap(BSpline* s)
{
    s->state = 0;
    s->val   = s->valDesired;
    s->dval  = s->dvalDesired;
}

static void mulPoint(bVector4* out, const bMatrix4* m, float x, float y)
{
    bVector4 v;
    v.x = x;
    v.y = y;
    v.z = 0.0f;
    v.w = 1.0f;
    eMulVector4(out, m, &v);
}

// RandomRange (0x00249570), on the view's seed.
static float randomRange(float lo, float hi)
{
    return ((float)bRandomI(10000, bViewSeed) * 0.0001f) * (hi - lo) + lo;
}

// --------------------------------------------------------- the renderer

// The copies' text, MaxChars 4 as retail's (0x001410e8's text twin).
typedef struct EtvTextCopy {
    union {
        struct FlailerTextChunk t;
        uint8_t bytes[100 + 8];
    } u;
} EtvTextCopy;

static void renderBitmap(struct FlailerBitmapChunk* orig,
                         const struct FlailerBitmapChunk* copy, float alpha)
{
    if (s_h && s_h->renderBitmap)
        s_h->renderBitmap(s_h->user, orig, copy, alpha, s_clip);
}

static void renderText(struct FlailerTextChunk* orig,
                       const struct FlailerTextChunk* copy, float alpha)
{
    const float* clip = (copy->FormatOptions & BUI_FMT_CLIP) ? s_clip : NULL;
    if (s_h && s_h->renderText)
        s_h->renderText(s_h->user, orig, copy, alpha, clip);
}

// An object drawn as it is (RenderFlailerBitmap / RenderFlailerText with
// the object itself).
static void renderObject(struct FlailerObjectChunk* o, float alpha)
{
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        renderBitmap((struct FlailerBitmapChunk*)o,
                     (struct FlailerBitmapChunk*)o, alpha);
    else if (o->ObjectType == FLAILER_TYPE_TEXT)
        renderText((struct FlailerTextChunk*)o, (struct FlailerTextChunk*)o,
                   alpha);
}

static void setClip(const float* min, const float* max)
{
    s_clip[0] = min[0];
    s_clip[1] = min[1];
    s_clip[2] = max[0];
    s_clip[3] = max[1];
}

static void resetClip(void)
{
    s_clip[0] = 0.0f;
    s_clip[1] = 0.0f;
    s_clip[2] = 644.0f;
    s_clip[3] = 480.0f;
}

// The bitmap copy (0x001410e8): everything but the strip, with the state
// flags' low byte.
static void copyBitmap(struct FlailerBitmapChunk* dst,
                       const struct FlailerBitmapChunk* src)
{
    *dst = *src;
    dst->StateFlags &= 0xffu;
    dst->Object.DirtyFlag = 0;
    dst->Object.pFlailerStrip = 0;
}

static void copyText(EtvTextCopy* dst, const struct FlailerTextChunk* src)
{
    memset(dst, 0, sizeof *dst);
    dst->u.t.Object        = src->Object;
    dst->u.t.Object.DirtyFlag = 0;
    dst->u.t.Object.pFlailerStrip = 0;
    dst->u.t.FontHash      = src->FontHash;
    dst->u.t.MaxChars      = 4;
    dst->u.t.FormatOptions = src->FormatOptions;
    dst->u.t.Color         = src->Color;
    dst->u.t.LanguageID    = src->LanguageID;
    memcpy(dst->u.t.String, src->String,
           src->MaxChars < 4 ? (size_t)(src->MaxChars > 0 ? src->MaxChars
                                                          : 0)
                             : 4u);
    dst->u.t.String[3] = 0;
}

// SetObjectColor (0x001f6c18).
static void setObjectColor(struct FlailerObjectChunk* o, const bVector4* c)
{
    uint32_t rgb;

    if (!o) return;
    rgb = (uint32_t)(int32_t)c->x | (uint32_t)(int32_t)c->y << 8
          | (uint32_t)(int32_t)c->z << 16;
    if (o->ObjectType == FLAILER_TYPE_BITMAP)
        flailerbitmap_set_color((struct FlailerBitmapChunk*)o, rgb);
    else if (o->ObjectType == FLAILER_TYPE_TEXT)
        flailertext_set_color((struct FlailerTextChunk*)o, rgb);
    flailerobject_set_alpha(o, (int32_t)c->w);
}

// RenderHLine (0x001f6cf0) and RenderVLine (0x001f6df8).
static void renderHLine(float x1, float x2, float y, const bVector4* col)
{
    struct FlailerBitmapChunk* obj = (struct FlailerBitmapChunk*)
        flailer_find_object(ETV_SCREEN, OBJ_HLINE, FLAILER_TYPE_BITMAP);
    struct FlailerBitmapChunk copy;
    float                     w, h;

    if (!obj) return;
    copyBitmap(&copy, obj);
    w = flailerobject_get_width_float(&obj->Object);
    h = flailerobject_get_height_float(&obj->Object);
    if (x2 < x1) {
        float t = x1;
        x1 = x2;
        x2 = t;
    }
    copy.Object.X = x1;
    copy.Object.Y = y - h * 0.5f;
    copy.Object.ScaleX = w != 0.0f ? (x2 - x1) / w : 0.0f;
    if (col) setObjectColor(&copy.Object, col);
    renderBitmap(obj, &copy, 1.0f);
}

static void renderVLine(float y1, float y2, float x, const bVector4* col)
{
    struct FlailerBitmapChunk* obj = (struct FlailerBitmapChunk*)
        flailer_find_object(ETV_SCREEN, OBJ_VLINE, FLAILER_TYPE_BITMAP);
    struct FlailerBitmapChunk copy;
    float                     w, h;

    if (!obj) return;
    copyBitmap(&copy, obj);
    w = flailerobject_get_width_float(&obj->Object);
    h = flailerobject_get_height_float(&obj->Object);
    if (y2 < y1) {
        float t = y1;
        y1 = y2;
        y2 = t;
    }
    copy.Object.Y = y1;
    copy.Object.X = x - w * 0.5f;
    copy.Object.ScaleY = h != 0.0f ? (y2 - y1) / h : 0.0f;
    if (col) setObjectColor(&copy.Object, col);
    renderBitmap(obj, &copy, 1.0f);
}

// InflateRect: the box scaled about its centre.
static void inflateRect(bVector2* min, bVector2* max, float s)
{
    float hx = (max->x - min->x) * 0.5f, hy = (max->y - min->y) * 0.5f;
    float cx = min->x + hx, cy = min->y + hy;
    min->x = -hx * s + cx;
    min->y = -hy * s + cy;
    max->x = hx * s + cx;
    max->y = hy * s + cy;
}

// ---------------------------------------------------------- FormatStatus

void eventtreeview_format_status(char* buf, int size, const EventInfo* e)
{
    int32_t     status = statusOf(e);
    const char* s;

    if (status < 0 || status >= 5) return;
    s = translate(kStatusNames[status]);
    switch (status) {
    case 0:
    case 1:
        snprintf(buf, (size_t)size, "%s", s);
        break;
    case 2:
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wformat-nonliteral"
#pragma GCC diagnostic ignored "-Wformat-security"
        snprintf(buf, (size_t)size, s, (int)event_info_get_race_index(e),
                 (int)event_info_get_race_count(e));
        break;
    default:
        snprintf(buf, (size_t)size, s, event_info_get_finish_string(e));
#pragma GCC diagnostic pop
        break;
    }
}

void eventtreeview_format_reward(char* buf, int size, const EventInfo* e)
{
    const EventReward* r = e ? event_info_get_reward(e, 0) : NULL;

    if (!r) {
        snprintf(buf, (size_t)size, "%s", translate(0x101d8));
    } else if (r->nType == 0) {
        const CarTypeInfo* ct = cartypeinfo_get(r->nValue1);
        snprintf(buf, (size_t)size, "%s",
                 ct && ct->pCarSpecs
                     ? translateString(translate(ct->pCarSpecs->FullName))
                     : "");
    } else if (r->nType == 1) {
        snprintf(buf, (size_t)size, "%s",
                 translate(trackLanguageId(r->nValue1, r->nValue2)));
    }
}

// --------------------------------------------------------------- tEventLeaf

static EtvLeaf* findLeaf(int32_t number)
{
    for (int i = 0; i < s_view.nLeaves; i++)
        if (s_view.leaves[i].info->nNumber == number)
            return &s_view.leaves[i];
    return NULL;
}

// Icon (0x001f75f0): the panel by the tree and the status, when the status
// names one.
static void leafIcon(EtvLeaf* l)
{
    static const char* const kNames[2][5] = {
        { "SPEED_EVENT_PANEL_LOCKED", "SPEED_EVENT_PANEL_UNLOCKED",
          "SPEED_EVENT_PANEL_UNLOCKED", "SPEED_EVENT_PANEL_UNLOCKED",
          "SPEED_EVENT_PANEL_WON" },
        { "PURSUIT_EVENT_PANEL_LOCKED", "PURSUIT_EVENT_PANEL_UNLOCKED",
          "PURSUIT_EVENT_PANEL_UNLOCKED", "PURSUIT_EVENT_PANEL_UNLOCKED",
          "PURSUIT_EVENT_PANEL_WON" },
    };
    int32_t type   = s_view.tree->nType == 1 ? 1 : 0;
    int32_t status = statusOf(l->info);

    if (s_view.tree->nType != 0 && s_view.tree->nType != 1) return;
    if (status < 0 || status > 4) return;
    l->icon = bchunk_hash(kNames[type][status]);
}

static float leafDefaultH(const EtvLeaf* l)
{
    return l->nIndex >= 0 && l->nIndex < 32 ? s_hTable[l->nIndex] : 0.0f;
}

static float leafDefaultV(const EtvLeaf* l)
{
    return (float)l->generation * 350.0f;
}

static void leafInit(EtvLeaf* l, uint32_t screen, EventInfo* info)
{
    struct FlailerObjectChunk* o;
    const EventReward*         r;

    memset(l, 0, sizeof *l);
    l->info = info;
    leafIcon(l);
    l->nIndex   = event_tree_get_event_index(s_view.tree, info->nNumber);
    l->center.x = leafDefaultH(l);
    l->center.y = leafDefaultV(l);
    l->center.z = 0.0f;
    l->center.w = 1.0f;
    l->master   = (struct FlailerBitmapChunk*)
        flailer_find_object(screen, OBJ_EVENT_PANEL, FLAILER_TYPE_ANY);
    flailer_change_texture(screen, OBJ_EVENT_PANEL, l->icon);
    if (l->master) {
        l->masterCx = l->master->Object.X
            + flailerobject_get_width_float(&l->master->Object) * 0.5f;
        l->masterCy = l->master->Object.Y
            + flailerobject_get_height_float(&l->master->Object) * 0.5f;
    }
    for (o = flailer_find_object_by_group(screen, GROUP_LEAF,
                                          FLAILER_TYPE_ANY, NULL);
         o && l->nObjs < ETV_MAX_OBJS;
         o = flailer_find_object_by_group(screen, GROUP_LEAF,
                                          FLAILER_TYPE_ANY, o))
        l->objs[l->nObjs++] = o;
    l->generation  = 0;
    l->scaleFactor = 1.0f;

    r = event_info_get_reward(info, 0);
    if (r && r->nType == 0) {
        const CarTypeInfo* ct = cartypeinfo_get(r->nValue1);
        snprintf(l->rewardName, sizeof l->rewardName, "%s",
                 ct && ct->pCarSpecs
                     ? translateString(translate(ct->pCarSpecs->FullName))
                     : "");
    } else if (r && r->nType == 1) {
        snprintf(l->rewardName, sizeof l->rewardName, "%s",
                 translate(trackLanguageId(r->nValue1, r->nValue2)));
    }
}

// IsVisible: the two last events only once they can be played, or event
// 32 once either tree's 31 is won.
static int leafIsVisible(const EtvLeaf* l)
{
    int32_t n = l->info->nNumber;

    if (n == 31) return statusOf(l->info) != 0;
    if (n == 32) {
        const EventInfo* a;
        if (statusOf(l->info) != 0) return 1;
        a = gChampionshipTree
                ? event_tree_get_event_number(gChampionshipTree, 31) : NULL;
        if (a && statusOf(a) == 4) return 1;
        a = gHotPursuitTree
                ? event_tree_get_event_number(gHotPursuitTree, 31) : NULL;
        if (a && statusOf(a) == 4) return 1;
        return 0;
    }
    return 1;
}

static int leafIsFogged(const EtvLeaf* l)
{
    int32_t best = 0;
    for (int i = 0; i < l->nParents; i++) {
        int32_t s = statusOf(l->parents[i]->info);
        if (s > best) best = s;
    }
    return statusOf(l->info) == 0 && best <= 0;
}

static int32_t leafGeneration(const EtvLeaf* l)
{
    int32_t n = 0;
    while (l->nParents > 0 && n < ETV_MAX_LEAVES) {
        l = l->parents[0];
        n++;
    }
    return n;
}

// GetBoundingBox (0x001f7ee8): the master panel's size about the leaf's
// default centre.
static void leafBox(EtvLeaf* l, bVector2* min, bVector2* max)
{
    float w = 0.0f, h = 0.0f;

    l->center.x = leafDefaultH(l);
    l->center.y = leafDefaultV(l);
    if (l->master) {
        w = flailerobject_get_width_float(&l->master->Object);
        h = flailerobject_get_height_float(&l->master->Object);
    }
    min->x = l->center.x - w * 0.5f;
    min->y = l->center.y - h * 0.5f;
    max->x = l->center.x + w * 0.5f;
    max->y = l->center.y + h * 0.5f;
}

// UnlockLeaf (0x001f7918), the debug unlock.
static void leafUnlock(EtvLeaf* l)
{
    event_info_unlock_state(l->info);
    leafIcon(l);
    for (int i = 0; i < l->nChildren; i++) leafIcon(l->children[i]);
}

// 0x001f7480: what winning this event opens -- each child's goal on it,
// but the Ultimate's, and the Ultimate itself when this is the last open.
static void leafFillEventsOpened(const EtvLeaf* l, EventsOpened* list)
{
    events_opened_clear(list);
    for (int i = 0; i < l->nChildren; i++) {
        const EtvLeaf* c = l->children[i];
        for (int g = 0; g < c->info->nGoals; g++) {
            const EventGoal* goal = event_info_get_goal(c->info, g);
            if (goal && goal->nEvent == (uint16_t)l->info->nNumber
                && c->info->nNumber != 32)
                events_opened_add(list, goal, c->info->nNumber);
        }
    }
    if (event_info_is_last_open(l->info))
        events_opened_add(list, event_info_get_objective(l->info), 32);
}

// Render (0x001f7978).
static void leafRender(EtvLeaf* l, const bMatrix4* m, float alpha)
{
    bVector4 out;
    bMatrix4 mm = *m;

    if (!leafIsVisible(l)) return;
    l->center.x = leafDefaultH(l);
    l->center.y = leafDefaultV(l);
    // Retail picks the colour by the fog and scales the matrix by 1.0.
    (void)leafIsFogged(l);

    for (int i = 0; i < l->nObjs; i++) {
        struct FlailerObjectChunk* o = l->objs[i];
        if (o->ObjectType != FLAILER_TYPE_BITMAP) continue;
        {
            struct FlailerBitmapChunk copy;

            // The object's top left, as far from the leaf's centre as it
            // is from the master panel's in the screen.
            mulPoint(&out, &mm, l->center.x + o->X - l->masterCx,
                     l->center.y + o->Y - l->masterCy);
            copyBitmap(&copy, (struct FlailerBitmapChunk*)o);
            copy.Object.X      = out.x;
            copy.Object.Y      = out.y;
            copy.Object.ScaleX = mm.v0.x * o->ScaleX;
            copy.Object.ScaleY = mm.v1.y * o->ScaleY;
            if (o->NameHash == OBJ_EVENT_PANEL) copy.TextureHash = l->icon;
            renderBitmap((struct FlailerBitmapChunk*)o, &copy, alpha);
        }
    }
    for (int i = 0; i < l->nObjs; i++) {
        struct FlailerObjectChunk* o = l->objs[i];
        struct FlailerTextChunk*   t = (struct FlailerTextChunk*)o;
        EtvTextCopy                copy;
        float                      h;
        char                       num[8];

        if (o->ObjectType != FLAILER_TYPE_TEXT) continue;
        mulPoint(&out, &mm, l->center.x, l->center.y);
        copyText(&copy, t);
        copy.u.t.Object.X      = out.x;
        copy.u.t.Object.ScaleX = mm.v0.x * o->ScaleX;
        copy.u.t.Object.ScaleY = mm.v1.y * o->ScaleY;
        // SetCenterY: the copy's height is the original's at its scale.
        h = flailerobject_get_height_float(o);
        if (o->ScaleY != 0.0f) h = h * copy.u.t.Object.ScaleY / o->ScaleY;
        copy.u.t.Object.Y = out.y - h * 0.5f;
        copy.u.t.FormatOptions |= BUI_FMT_CLIP;
        if (o->NameHash == OBJ_EVENT_NUMBER) {
            snprintf(num, sizeof num, "%2d", (int)l->info->nNumber);
            flailertext_set_string(&copy.u.t, num);
        }
        flailertext_set_alpha(&copy.u.t, (int32_t)kColourGrey.w);
        renderText(t, &copy.u.t, alpha);
    }

    // The line up to the first parent, from the panel's top to halfway.
    if (l->nParents > 0) {
        bVector2 min, max, pmin, pmax;
        bVector4 v1, v2;

        leafBox(l, &min, &max);
        leafBox(l->parents[0], &pmin, &pmax);
        mulPoint(&v1, &mm, l->center.x, min.y);
        mulPoint(&v2, &mm, l->center.x, pmax.y + (min.y - pmax.y) * 0.5f);
        renderVLine(v1.y + 5.0f, v2.y, v1.x,
                    statusOf(l->info) > 0 ? &kColourOpen : &kColourLocked);
    }
    // The line down to the first child, when it shows.
    if (l->nChildren > 0) {
        bVector2 min, max, cmin, cmax;
        bVector4 v1, v2;
        float    bottom;

        leafBox(l, &min, &max);
        bottom = max.y;
        if (leafIsVisible(l->children[0])) {
            leafBox(l->children[0], &cmin, &cmax);
            mulPoint(&v1, &mm, l->center.x, bottom);
            mulPoint(&v2, &mm, l->center.x,
                     bottom + (cmin.y - bottom) * 0.5f);
            renderVLine(v1.y - (event_info_tree(l->info)->nType == 1
                                    ? 5.0f : 16.0f),
                        v2.y, v1.x,
                        statusOf(l->info) >= 4 ? &kColourOpen
                                               : &kColourLocked);
        }
    }
}

// -------------------------------------------------------------- tEventGroup

static int groupIsMember(const EtvGroup* g, const EtvLeaf* l)
{
    for (int i = 0; i < g->nMembers; i++)
        if (g->members[i] == l) return 1;
    return 0;
}

static void groupMaybeAdd(EtvGroup* g, EtvLeaf* l)
{
    if (!groupIsMember(g, l) && g->nMembers < ETV_MAX_LINKS + 1)
        g->members[g->nMembers++] = l;
}

static EtvGroup* groupOf(const EtvLeaf* l)
{
    for (int i = 0; i < s_view.nGroups; i++)
        if (groupIsMember(&s_view.groups[i], l)) return &s_view.groups[i];
    return NULL;
}

// 0x001f8020.
static void groupFillGenerations(EtvGroup* g)
{
    int32_t lo = 999999999, hi = -1;

    g->nTop = g->nBottom = 0;
    for (int i = 0; i < g->nMembers; i++) {
        int32_t n = g->members[i]->generation;
        if (n < lo) lo = n;
        if (hi < n) hi = n;
    }
    for (int i = 0; i < g->nMembers; i++) {
        if (g->members[i]->generation == lo)
            g->top[g->nTop++] = g->members[i];
        if (g->members[i]->generation == hi)
            g->bottom[g->nBottom++] = g->members[i];
    }
}

// 0x001f81b8: the members sorted by x, greatest first (bList::Sort with
// b.x <= a.x in order, a stable bubble sort), and a bar between each pair
// halfway between the generations.
static void groupMakeBars(EtvGroup* g)
{
    float ylo, yhi;

    for (int i = 1; i < g->nMembers; i++) {
        EtvLeaf* l = g->members[i];
        int      j = i;
        while (j > 0 && g->members[j - 1]->center.x < l->center.x) {
            g->members[j] = g->members[j - 1];
            j--;
        }
        g->members[j] = l;
    }
    ylo = g->nTop > 0 ? g->top[0]->center.y : 0.0f;
    yhi = g->nBottom > 0 ? g->bottom[0]->center.y : 0.0f;
    g->nBars = 0;
    for (int i = 0; i + 1 < g->nMembers; i++) {
        EtvBar* b = &g->bars[g->nBars++];
        b->x1     = g->members[i]->center.x;
        b->x2     = g->members[i + 1]->center.x;
        b->y      = (ylo + yhi) * 0.5f;
        b->colour = kColourLocked;
    }
}

static void groupColourRange(EtvGroup* g, float lo, float hi,
                             const bVector4* col)
{
    if (hi < lo) {
        float t = lo;
        lo = hi;
        hi = t;
    }
    for (int i = 0; i < g->nBars; i++) {
        float mid = (g->bars[i].x1 + g->bars[i].x2) * 0.5f;
        if (lo <= mid && mid <= hi) g->bars[i].colour = *col;
    }
}

// 0x001f8300: the stretch of bar from an open child to each parent whose
// goal it has passed, green.
static void groupColourBars(EtvGroup* g)
{
    for (int i = 0; i < g->nBottom; i++) {
        EtvLeaf* l = g->bottom[i];
        if (statusOf(l->info) <= 0) continue;
        for (int k = 0; k < l->info->nGoals; k++) {
            const EventGoal* goal = event_info_get_goal(l->info, k);
            EtvLeaf*         m    = NULL;
            if (!goal) continue;
            for (int j = 0; j < g->nMembers; j++)
                if (g->members[j]->info->nNumber == (int32_t)goal->nEvent)
                    m = g->members[j];
            // Retail reads through a NULL member.
            if (m && event_info_get_status(m->info, goal) >= 2)
                groupColourRange(g, l->center.x, m->center.x, &kColourOpen);
        }
    }
}

// 0x001f8520.
static void groupRender(const EtvGroup* g, const bMatrix4* m)
{
    for (int i = 0; i < g->nBars; i++) {
        const EtvBar* b = &g->bars[i];
        bVector4      v1, v2;
        mulPoint(&v1, m, b->x1, b->y);
        mulPoint(&v2, m, b->x2, b->y);
        renderHLine(v1.x, v2.x, v1.y, &b->colour);
    }
}

// -------------------------------------------------------------- tEventBlurb

static void eventBlurbInit(EtvEventBlurb* b, uint32_t screen)
{
    b->active = NULL;
    b->screen = screen;
    b->master = flailer_find_object(screen, OBJ_SMALL_NUMBER,
                                    FLAILER_TYPE_ANY);
    b->newEventTime = 0;
    b->startAlpha   = 0.0f;
}

static void eventBlurbSetActive(EtvEventBlurb* b, EventInfo* info)
{
    if (b->active == info) return;
    b->newEventTime = realTimer();
    b->active       = info;
    b->startAlpha   = b->master ? (float)flailerobject_get_alpha(b->master)
                                : 0.0f;
    flailer_set_group_alpha(b->screen, GROUP_EVENT_BLURB, 0);
}

static void eventBlurbRedraw(EtvEventBlurb* b)
{
    char buf[256];

    buf[0] = 0;
    eventtreeview_format_status(buf, sizeof buf, b->active);
    flailer_printf(b->screen, OBJ_STATUS, "%s", buf);
    buf[0] = 0;
    eventtreeview_format_reward(buf, sizeof buf, b->active);
    flailer_printf(b->screen, OBJ_REWARD, "%s", buf);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wformat-nonliteral"
#pragma GCC diagnostic ignored "-Wformat-security"
    flailer_printf(b->screen, OBJ_SMALL_NUMBER, translate(0x111af),
                   b->active ? (int)b->active->nNumber : 0);
#pragma GCC diagnostic pop
}

// Animate: the panel slides in from the right 0.15 s after a new event,
// over 0.2 s, its alpha first fading out from where it was.
static void eventBlurbAnimate(EtvEventBlurb* b)
{
    float t = secondsSince(b->newEventTime);
    float x, a;

    if (!b->master) return;
    if (0.15f < t) {
        if (t < 0.35f)
            x = 382.0f + ((640.0f - 382.0f) * (0.35f - t)) / (0.35f - 0.15f);
        else
            x = 382.0f;
        eventBlurbRedraw(b);
    } else {
        x = b->master->X;
    }
    if (t < 0.15f)
        a = b->startAlpha * (1.0f - t / 0.15f);
    else if (t > 0.15f)
        a = 128.0f;
    else
        a = 0.0f;
    flailer_set_group_position(b->screen, GROUP_EVENT_BLURB,
                               b->master->NameHash, x, b->master->Y);
    flailer_set_group_alpha(b->screen, GROUP_EVENT_BLURB, (int32_t)a);
}

static void eventBlurbRewind(EtvEventBlurb* b)
{
    b->newEventTime += ticks(0.15f);
}

// ------------------------------------------------------------- tTreeDetails

static void collectGroup(uint32_t screen, uint32_t group,
                         struct FlailerObjectChunk** objs, int* n,
                         uint32_t skip1, uint32_t skip2)
{
    struct FlailerObjectChunk* o;

    *n = 0;
    for (o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                          NULL);
         o && *n < ETV_MAX_OBJS;
         o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                          o)) {
        if (o->NameHash == skip1 || o->NameHash == skip2) continue;
        objs[(*n)++] = o;
    }
}

static void detailsInit(EtvDetails* d, EventTree* tree, uint32_t screen)
{
    memset(d, 0, sizeof *d);
    collectGroup(screen, GROUP_DETAILS, d->objs, &d->nObjs, 0, 0);
    d->lastKnown = NULL;
    d->screen    = screen;
    d->tree      = tree;
}

static int isResume(const EventInfo* e)
{
    return event_info_is_multi_track(e) && statusOf(e) == 2;
}

// Render (0x001f6770).
static void detailsRender(EtvDetails* d, EventInfo* info, float alpha)
{
    if (info != d->lastKnown) {
        const uint8_t* tr;
        int32_t        id = 0;

        format_event_description(d->tree, info,
                                 translate(info->mDescriptionString),
                                 d->description, sizeof d->description);
        tr = event_info_get_track(info, event_info_get_race_index(info));
        if (!tr) tr = event_info_get_track(info, 0);
        if (tr) id = trackLanguageId(tr[0], (trackWord(tr) >> 9) & 1);
        flailer_set_language_id(d->screen, OBJ_TRACK_NAME, (uint32_t)id);
        d->lastKnown = info;
        if (!isResume(info)) {
            Fred.GameType = d->tree->nType ? 9 : 8;
            fred_make_event_cars_available(&Fred, d->tree, info);
            if (s_h && s_h->preloadCars) s_h->preloadCars(s_h->user);
        }
    }
    for (int i = 0; i < d->nObjs; i++) renderObject(d->objs[i], alpha);
    if (s_h && s_h->renderTextIntoRectangle)
        s_h->renderTextIntoRectangle(s_h->user, d->screen, OBJ_RECT_TEXT,
                                     OBJ_RECT_BOX, d->description, alpha);
}

static void detailsSyncHelp(const EtvDetails* d, const EventInfo* info)
{
    int resume = info && isResume(info);
    if (d->tree->nType == 0)
        setHelpOverride(resume ? kHelpResume : kHelpChampDetail);
    else if (d->tree->nType == 1)
        setHelpOverride(resume ? kHelpResume : kHelpHPDetail);
}

// StartEvent (0x001f6a28).
static void detailsStartEvent(EtvDetails* d, BScreenCallbackData* data,
                              EtvLeaf* leaf)
{
    EventInfo* e = d->lastKnown;

    Fred.ChallengeScreenData[2]   = 1;
    TheRaceParameters.NFSRaceMode = 1;
    Fred.nCurrentEvent            = e->nNumber;
    event_tree_set_race(d->tree, &TheRaceParameters, e);
    leafFillEventsOpened(leaf, &TheEventsOpened);
    if (isResume(e)) {
        if (data->port != 0) return;
        trace("etv resume event %d", (int)e->nNumber);
        bgf_push_screen(s_view.gf, "View Event Tree");
        fred_continue_multi_track_event(&Fred);
    } else {
        Fred.GameType = d->tree->nType ? 9 : 8;
        fred_make_event_cars_available(&Fred, d->tree, e);
        trace("etv start event %d", (int)e->nNumber);
        bgf_change_to_screen(s_view.gf, "Select Car", 1);
    }
}

static void detailsHandle(EtvDetails* d, BScreenMessage msg,
                          BScreenCallbackData* data, EtvLeaf* leaf)
{
    if (msg >= 10) return;
    if (msg >= 6) {
        data->noise = SND_NONE;
        return;
    }
    if (msg == BMSG_MENUITEM_SELECT && d->lastKnown) {
        if (statusOf(d->lastKnown) > 0) {
            data->noise = SND_START;
            detailsStartEvent(d, data, leaf);
        } else {
            data->noise = SND_LOCKED;
        }
    }
}

// -------------------------------------------------------------- tTreeReward

static void rewardInit(EtvReward* r, EventTree* tree, uint32_t screen)
{
    memset(r, 0, sizeof *r);
    r->screen = screen;
    collectGroup(screen, GROUP_REWARD, r->objs, &r->nObjs, 0, 0);
    r->tree = tree;
}

// Render (0x001f6440). The car or track model is not ported.
static void rewardRender(EtvReward* r, EtvLeaf* leaf, float alpha)
{
    (void)leaf;
    for (int i = 0; i < r->nObjs; i++) renderObject(r->objs[i], alpha);
}

static void rewardHide(EtvReward* r, EtvLeaf* leaf)
{
    flailer_printf(r->screen, OBJ_REWARD_NAME, "%s", leaf->rewardName);
}

static void rewardSyncHelp(const EtvReward* r)
{
    if (r->tree->nType == 0) setHelpOverride(kHelpChampReward);
    else if (r->tree->nType == 1) setHelpOverride(kHelpHPReward);
}

static int rewardHandle(BScreenMessage msg, BScreenCallbackData* data)
{
    if (msg == BMSG_MENUITEM_SQUARE) return 0;
    if (msg == BMSG_SCREEN_BACK_BUTTON) {
        data->param = 0;
        data->noise = SND_NONE;
        return 0;
    }
    if (msg >= 11) return 1;
    if (msg >= 6) {
        data->noise = SND_NONE;
        return 1;
    }
    return 1;
}

// ------------------------------------------------------------ the car logos

static void carLogosSetAlpha(EtvCarLogos* c, float a)
{
    flailer_set_alpha(c->screen, OBJ_CAR_LOGO, (int32_t)a);
}

static void carLogosInit(EtvCarLogos* c, uint32_t screen)
{
    memset(c, 0, sizeof *c);
    c->screen = screen;
    c->timer  = realTimer();
    c->alpha  = (float)flailer_get_alpha(screen, OBJ_CAR_LOGO);
}

static void carLogosRelease(EtvCarLogos* c)
{
    (void)c;
    if (s_h && s_h->releaseKept) s_h->releaseKept(s_h->user);
}

// SetImage (0x001f8d20).
static void carLogosSetImage(EtvCarLogos* c, int move)
{
    if (c->index < c->count)
        flailer_change_texture(c->screen, OBJ_CAR_LOGO, c->hashes[c->index]);
    if (move) {
        c->y = (c->y + bRandomI(3, bViewSeed) + 1) % 4;
        c->x = (c->x + bRandomI(2, bViewSeed)) & 1;
    }
    flailer_set_top_left_y(c->screen, OBJ_CAR_LOGO, (int32_t)kLogoY[c->y]);
    flailer_set_top_left_x(c->screen, OBJ_CAR_LOGO, (int32_t)kLogoX[c->x]);
}

// SetEvent (0x001f8e18).
static void carLogosSetEvent(EtvCarLogos* c, const EventInfo* info)
{
    carLogosRelease(c);
    c->count = 0;
    memset(c->hashes, 0, sizeof c->hashes);
    for (int i = 0; i < info->nCars; i++) {
        const uint8_t*     car = event_info_get_car(info, i);
        const CarTypeInfo* ct  = car ? cartypeinfo_get(car[2]) : NULL;
        uint32_t           hash;
        if (!ct) continue;
        hash = bchunk_hash_from(ct->CarTypeName, bchunk_hash("CARLOGO_"));
        c->hashes[c->count++] = hash;
        if (s_h && s_h->keepTexture) s_h->keepTexture(s_h->user, hash);
        if (c->count == 8) break;
    }
    c->index = c->y = c->x = 0;
    c->flag  = 1;
    carLogosSetImage(c, 0);
    c->timer = realTimer() - ticks(5.5f);
    flailer_set_visibility(c->screen, OBJ_CAR_LOGO, FLAILER_OBJECT_VISIBLE);
}

// 0x001f8f68.
static float ramp(float t, float lo, float hi)
{
    if (t < lo) return 0.0f;
    if (hi < t) return 1.0f;
    return (t - lo) / (hi - lo);
}

// Tick (0x001f8fb0): each logo 5 s, a half-second fade out and in.
static void carLogosTick(EtvCarLogos* c)
{
    float t = secondsSince(c->timer);

    if (5.0f < t && t < 5.5f) {
        carLogosSetAlpha(c, c->alpha * (1.0f - ramp(t, 5.0f, 5.5f)));
        c->flag = 0;
    } else if (5.5f <= t && t < 6.0f) {
        if (!c->flag) {
            if (++c->index >= c->count) c->index = 0;
            carLogosSetImage(c, 1);
            c->flag = 1;
        }
        carLogosSetAlpha(c, c->alpha * ramp(t, 5.5f, 6.0f));
    } else if (t >= 6.0f) {
        c->timer = realTimer();
    }
}

// ------------------------------------------------------------ the track logo

static void trackLogoInit(EtvTrackLogo* l, uint32_t screen)
{
    memset(l, 0, sizeof *l);
    l->timer  = 0;
    l->screen = screen;
    l->origX  = flailer_get_top_left_x(screen, OBJ_TRACK_LOGO);
    l->alpha  = (float)flailer_get_alpha(screen, OBJ_TRACK_LOGO);
    l->flag   = 0;
    flailer_set_visibility(screen, OBJ_TRACK_LOGO, FLAILER_OBJECT_VISIBLE);
}

// 0x0019fb00: LOGOTRACK%2d, R backward, _FR in French.
static uint32_t trackLogoHash(int32_t track, int32_t dir)
{
    char     buf[24];
    uint32_t h;

    snprintf(buf, sizeof buf, "LOGOTRACK%2d", (int)track);
    h = bchunk_hash(buf);
    if (dir == 1) h = bchunk_hash_from("R", h);
    if (gCurrLanguageFn && gCurrLanguageFn() == 1)
        h = bchunk_hash_from("_FR", h);
    return h;
}

// SetEvent (0x001f91f0).
static void trackLogoSetEvent(EtvTrackLogo* l, const EventInfo* info)
{
    l->count = 0;
    memset(l->hashes, 0, sizeof l->hashes);
    for (int i = 0; i < info->nTracks; i++) {
        const uint8_t*   tr = event_info_get_track(info, i);
        const TrackInfo* ti = tr ? track_get_info(tr[0]) : NULL;
        if (!ti) continue;
        l->hashes[l->count++] = trackLogoHash(ti->SameAsTrackNumber,
                                              (trackWord(tr) >> 9) & 1);
        if (l->count == 12) break;
    }
    if (secondsSince(l->timer) < 0.35f)
        flailer_set_top_left_x(l->screen, OBJ_TRACK_LOGO, 640);
    l->index = 0;
    l->timer = realTimer();
    flailer_set_visibility(l->screen, OBJ_TRACK_LOGO, FLAILER_OBJECT_VISIBLE);
}

// Tick (0x001f9318).
static void trackLogoTick(EtvTrackLogo* l)
{
    float t   = secondsSince(l->timer);
    float end = 0.27f + 0.35f;

    if (t < 0.35f) {
        flailer_set_alpha(l->screen, OBJ_TRACK_LOGO,
                          (int32_t)(l->alpha * (1.0f - ramp(t, 0.0f, 0.35f))));
        l->flag = 0;
    } else if (0.35f < t && t <= end) {
        if (!l->flag) {
            flailer_change_texture(l->screen, OBJ_TRACK_LOGO,
                                   l->hashes[l->index]);
            l->flag = 1;
        }
        flailer_set_top_left_x(
            l->screen, OBJ_TRACK_LOGO,
            (int32_t)(ramp(t, 0.35f, end) * (l->origX - 640.0f) + 640.0f));
        flailer_set_alpha(l->screen, OBJ_TRACK_LOGO, (int32_t)l->alpha);
    } else if (end < t) {
        flailer_set_top_left_x(l->screen, OBJ_TRACK_LOGO, (int32_t)l->origX);
    }
}

// ------------------------------------------------------------- the popup

static void popupInit(EtvPopup* p, uint32_t screen)
{
    memset(p, 0, sizeof *p);
    p->screen = screen;
    collectGroup(screen, GROUP_DETAILS, p->objs, &p->nObjs, OBJ_TRACK_LABEL,
                 OBJ_TRACK_NAME);
    snprintf(p->text, sizeof p->text, "%s", translate(0xe32c9));
}

static int popupHandle(BScreenMessage msg, BScreenCallbackData* data)
{
    if (msg >= 10) return 1;
    if (msg >= 6) {
        data->noise = SND_NONE;
        return 1;
    }
    if (msg == BMSG_MENUITEM_SELECT) {
        data->noise = SND_POPUP_OK;
        return 0;
    }
    return 1;
}

static void popupRender(EtvPopup* p, float alpha)
{
    for (int i = 0; i < p->nObjs; i++) renderObject(p->objs[i], alpha);
    if (s_h && s_h->renderTextIntoRectangle)
        s_h->renderTextIntoRectangle(s_h->user, p->screen, OBJ_RECT_TEXT,
                                     OBJ_RECT_BOX, p->text, alpha);
}

// ------------------------------------------------------------- the view

static int shouldRenderTree(int s)    { return s < 2 || s == 3; }
static int shouldRenderDetails(int s) { return (s >= 1 && s <= 4) || s == 6; }
static int shouldRenderReward(int s)  { return s >= 4 && s <= 6; }
static int isInTransit(int s)         { return s == 1 || s == 3 || s == 4 || s == 6; }

static int32_t* keptState(void)
{
    return &Fred.SelectedEventData[3];
}

static void setDesired(float x, float y, const EtvLeaf* l)
{
    bVector2 v;
    v.x = x - l->center.x * s_view.zoom.valDesired;
    v.y = y - l->center.y * s_view.zoom.valDesired;
    bspline2d_set_val_desired(&s_view.pan, &v);
}

static int maybeChangeZoom(int d)
{
    int n = s_view.zoomIndex + d;
    if (n < 0) n = 0;
    if (n > 1) n = 1;
    if (n == s_view.zoomIndex && d != 0) return 0;
    s_view.zoomIndex = n;
    aim(&s_view.zoom, kZoom[n]);
    setDesired(320.0f, 240.0f, s_view.cur);
    return 1;
}

static void maybeChangeView(void)
{
    bVector2 v;
    setDesired(320.0f, 240.0f, s_view.cur);
    v.x = randomRange(0.0f, 320.0f);
    v.y = randomRange(0.0f, 240.0f);
    bspline2d_set_val_desired(&s_view.parallaxer, &v);
}

static EtvLeaf* findClosestInGeneration(const EtvLeaf* l, int32_t gen,
                                        int dir)
{
    EtvLeaf* best = NULL;
    float    bx   = dir < 0 ? -999999.0f : 999999.0f;

    for (int i = 0; i < s_view.nLeaves; i++) {
        EtvLeaf* c = &s_view.leaves[i];
        if (c == l || c->generation != gen) continue;
        if (dir < 0) {
            if (c->center.x < l->center.x && bx < c->center.x) {
                bx   = c->center.x;
                best = c;
            }
        } else if (l->center.x < c->center.x && c->center.x < bx) {
            bx   = c->center.x;
            best = c;
        }
    }
    return best;
}

static EtvLeaf* findClosestInList(const EtvLeaf* l, EtvLeaf* const* list,
                                  int n)
{
    EtvLeaf* best = NULL;
    float    bd   = 999999.0f;

    for (int i = 0; i < n; i++) {
        float d = fabsf(list[i]->center.x - l->center.x);
        if (d < bd) {
            bd   = d;
            best = list[i];
        }
    }
    return best;
}

static void syncHelpMenu(void);

static int maybeChangeLeaf(int dir)
{
    EtvLeaf* cur = s_view.cur;
    EtvLeaf* n   = NULL;
    BAnim*   a;

    if (dir == -1 || dir == 1)
        n = findClosestInGeneration(cur, cur->generation, dir);
    else if (dir == 2)
        n = findClosestInList(cur, cur->parents, cur->nParents);
    else if (dir == -2)
        n = findClosestInList(cur, cur->children, cur->nChildren);
    if (!n || n == cur || !leafIsVisible(n)) return 0;

    cur->scaleFactor = 1.0f;
    s_view.cur       = n;
    n->scaleFactor   = 2.0f;
    eventBlurbSetActive(&s_view.eventBlurb, n->info);
    a = anim();
    if (a) banim_blurb_new_text_id(a, &s_view.blurby, n->info->mTitleString);
    carLogosSetEvent(&s_view.carLogos, n->info);
    trackLogoSetEvent(&s_view.trackLogo, n->info);
    trace("etv leaf %d", (int)n->info->nNumber);
    return 1;
}

static void transitTreeToDetails(void)
{
    s_view.viewState = VS_TRANSIT_TO_DETAILS;
    aim(&s_view.alpha, 0.0f);
    aim(&s_view.zoom, 3.0f);
    setDesired(320.0f, 240.0f, s_view.cur);
    detailsSyncHelp(&s_view.details, s_view.cur->info);
}

static void transitDetailsToTree(void)
{
    aim(&s_view.alpha, 1.0f);
    s_view.viewState = VS_TRANSIT_TO_TREE;
    aim(&s_view.zoom, kZoom[s_view.zoomIndex]);
    setDesired(320.0f, 240.0f, s_view.cur);
    syncHelpMenu();
}

static void transitRewardToDetails(void)
{
    s_view.viewState = VS_TRANSIT_FROM_REWARD;
    aim(&s_view.alpha, 0.0f);
    flailer_set_visibility(s_view.screen, OBJ_CAR_LOGO,
                           FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(s_view.screen, OBJ_TRACK_LOGO,
                           FLAILER_OBJECT_VISIBLE);
    detailsSyncHelp(&s_view.details, s_view.cur->info);
}

static void transitDetailsToReward(void)
{
    s_view.viewState = VS_TRANSIT_TO_REWARD;
    aim(&s_view.alpha, 1.0f);
    flailer_set_visibility(s_view.screen, OBJ_TRACK_LOGO,
                           FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(s_view.screen, OBJ_CAR_LOGO,
                           FLAILER_OBJECT_INVISIBLE);
    rewardSyncHelp(&s_view.reward);
}

// SyncHelpMenu (0x001f9f50).
static void syncHelpMenu(void)
{
    if (s_view.viewState == VS_TRANSIT_TO_DETAILS)
        detailsSyncHelp(&s_view.details, s_view.cur->info);
    else if (s_view.tree->nType == 0)
        setHelpOverride(kHelpChampTree);
    else if (s_view.tree->nType == 1)
        setHelpOverride(kHelpHPTree);
    if (s_view.viewState == VS_POPUP) {
        if (s_h && s_h->hideHelp) s_h->hideHelp(s_h->user);
        flailer_set_visibility(s_view.screen, OBJ_HELP_TEXT,
                               FLAILER_OBJECT_INVISIBLE);
        flailer_set_visibility(s_view.screen, OBJ_HELP_ICON,
                               FLAILER_OBJECT_INVISIBLE);
    } else {
        flailer_set_visibility(s_view.screen, OBJ_HELP_TEXT,
                               FLAILER_OBJECT_VISIBLE);
        flailer_set_visibility(s_view.screen, OBJ_HELP_ICON,
                               FLAILER_OBJECT_VISIBLE);
    }
}

// 0x001faea8.
static void popupClosed(void)
{
    BAnim* a = anim();

    s_view.viewState = *keptState();
    syncHelpMenu();
    if (s_view.viewState == VS_DETAILS) transitTreeToDetails();
    if (a)
        banim_blurb_new_text_id(a, &s_view.blurby,
                                s_view.cur->info->mTitleString);
    flailer_set_visibility(s_view.screen, OBJ_HELP_TEXT,
                           FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(s_view.screen, OBJ_HELP_ICON,
                           FLAILER_OBJECT_VISIBLE);
}

// 0x001f9f10: the Ultimate open and not yet won.
static int ultimateOpen(void)
{
    EtvLeaf* u = findLeaf(EVENT_ULTIMATE);
    int32_t  s = u ? statusOf(u->info) : 0;
    return s > 0 && s != 4;
}

static void splineInit(BSpline* s)
{
    memset(s, 0, sizeof *s);
    s->duration         = 1.0f;
    s->arrivalThreshold = 1.0f;
    s->state            = 0;
    s->flags            = 1;
}

// The constructor (0x001f96b8).
static void viewInit(BGameFlow* gf, uint32_t screen, EventTree* tree)
{
    EtvView*    v = &s_view;
    BAnim*      a = anim();
    const char* layout;
    int32_t     sel, x0, y0, x1, y1;

    memset(v, 0, sizeof *v);
    v->gf = gf;
    eventBlurbInit(&v->eventBlurb, screen);
    splineInit(&v->zoom);
    splineInit(&v->pan.x);
    splineInit(&v->pan.y);
    splineInit(&v->alpha);
    v->tree = tree;
    detailsInit(&v->details, tree, ETV_SCREEN_DETAILS);
    v->idleOnLeafTimer = 0;
    // tParallaxer: from (320, 240) toward 0, half a second an axis.
    v->parallaxer.x.val = 320.0f;
    v->parallaxer.y.val = 240.0f;
    v->parallaxer.x.duration = v->parallaxer.y.duration = 0.5f;
    v->parallaxer.x.arrivalThreshold = v->parallaxer.y.arrivalThreshold = 1.0f;
    v->parallaxer.x.flags = v->parallaxer.y.flags = 1;
    v->parallaxer.x.state = v->parallaxer.y.state = 2;
    if (a)
        banim_blurb_init(a, &v->blurby, screen, ETV_OBJ_SCROLLING,
                         ETV_OBJ_SCROLLING, OBJ_WHITEOUT_BAR);
    rewardInit(&v->reward, tree, ETV_SCREEN_REWARD);
    carLogosInit(&v->carLogos, screen);
    trackLogoInit(&v->trackLogo, screen);
    popupInit(&v->popup, ETV_SCREEN_POPUP);
    v->screen = screen;
    if (s_h && s_h->jukeboxStart) s_h->jukeboxStart(s_h->user);

    // The leaves, one for each event, in order.
    for (int i = 0; i < tree->nEvents && v->nLeaves < ETV_MAX_LEAVES; i++)
        leafInit(&v->leaves[v->nLeaves++], screen, &tree->pEvents[i]);
    // The links: an event's goals are on its parents.
    for (int i = 0; i < v->nLeaves; i++) {
        EtvLeaf* l = &v->leaves[i];
        for (int g = 0; g < l->info->nGoals; g++) {
            const EventGoal* goal = event_info_get_goal(l->info, g);
            EtvLeaf*         p    = goal ? findLeaf(goal->nEvent) : NULL;
            if (!p) continue;
            if (l->nParents < ETV_MAX_LINKS) l->parents[l->nParents++] = p;
            if (p->nChildren < ETV_MAX_LINKS) p->children[p->nChildren++] = l;
        }
    }
    for (int i = 0; i < v->nLeaves; i++)
        v->leaves[i].generation = leafGeneration(&v->leaves[i]);
    // The groups: a parent with its children, or joined to its first
    // child's group.
    for (int i = 0; i < v->nLeaves; i++) {
        EtvLeaf*  l = &v->leaves[i];
        EtvGroup* g;
        if (l->nChildren == 0) continue;
        g = groupOf(l->children[0]);
        if (g) {
            groupMaybeAdd(g, l);
        } else if (v->nGroups < ETV_MAX_GROUPS) {
            g = &v->groups[v->nGroups++];
            groupMaybeAdd(g, l);
            for (int c = 0; c < l->nChildren; c++)
                groupMaybeAdd(g, l->children[c]);
        }
    }
    // The H table, from the layout string.
    layout = tree->nType == 0 ? kLayoutChampionship : kLayoutHotPursuit;
    for (int i = 0; i < v->nLeaves; i++) {
        int32_t n = v->leaves[i].info->nNumber, seen = 0;
        for (int k = 0; k < 201; k++) {
            if (layout[k] == ' ') continue;
            if (++seen == n) {
                if (n >= 1 && n <= 32)
                    s_hTable[n - 1] = 130.0f * (float)(k % 20);
                break;
            }
        }
    }
    for (int i = 0; i < v->nLeaves; i++) {
        v->leaves[i].center.x = leafDefaultH(&v->leaves[i]);
        v->leaves[i].center.y = leafDefaultV(&v->leaves[i]);
    }

    // The current leaf: the one last chosen, but not a locked 31 or 32.
    sel    = data_event_select_get_selected_event(Fred.SelectedEventData,
                                                  tree->nType);
    v->cur = findLeaf(sel);
    if (!v->cur) v->cur = &v->leaves[0];
    if ((v->cur->info->nNumber == 31 || v->cur->info->nNumber == 32)
        && statusOf(v->cur->info) == 0)
        v->cur = &v->leaves[0];

    eventBlurbSetActive(&v->eventBlurb, v->cur->info);
    v->eventBlurb.startAlpha = 0.0f;
    eventBlurbRewind(&v->eventBlurb);
    v->indicatorAnimate = 0.0f;
    if (s_h && s_h->stopMovie) s_h->stopMovie(s_h->user);
    flailer_set_group_visibility(screen, GROUP_LEAF, 0);

    v->zoom.duration = v->pan.x.duration = v->pan.y.duration =
        v->alpha.duration = 0.5f;
    v->zoom.flags = v->pan.x.flags = v->pan.y.flags = v->alpha.flags = 0;
    aim(&v->alpha, 1.0f);
    snap(&v->zoom);
    snap(&v->pan.x);
    snap(&v->pan.y);
    snap(&v->alpha);
    v->zoomIndex = 0;
    maybeChangeZoom(0);
    snap(&v->zoom);
    snap(&v->pan.x);
    snap(&v->pan.y);
    setDesired(320.0f, 240.0f, v->cur);

    flailer_set_language_id(screen, OBJ_TITLE,
                            Fred.GameType == 8 ? 10026u
                            : Fred.GameType == 9 ? 10029u : 0u);

    if (ultimateOpen()) {
        v->viewState = VS_POPUP;
        if (a) banim_blurb_freeze(a, &v->blurby);
    } else {
        v->viewState = *keptState();
        if (v->viewState < VS_TREE || v->viewState > VS_POPUP)
            v->viewState = VS_TREE;
        if (v->viewState == VS_DETAILS) transitTreeToDetails();
        if (a)
            banim_blurb_new_text_id(a, &v->blurby,
                                    v->cur->info->mTitleString);
    }
    v->idleOnLeafTimer = realTimer();
    syncHelpMenu();
    flailer_get_bounding_box(screen, OBJ_CLIP_BOX, &x0, &y0, &x1, &y1);
    v->clipMin[0] = (float)x0;
    v->clipMin[1] = (float)y0;
    v->clipMax[0] = (float)x1;
    v->clipMax[1] = (float)y1;
    carLogosSetEvent(&v->carLogos, v->cur->info);
    for (int i = 0; i < v->nGroups; i++) {
        groupFillGenerations(&v->groups[i]);
        groupMakeBars(&v->groups[i]);
        groupColourBars(&v->groups[i]);
    }
    s_live = 1;
    trace("etv open tree %d event %d state %d leaves %d groups %d",
          (int)tree->nType, (int)v->cur->info->nNumber, (int)v->viewState,
          v->nLeaves, v->nGroups);
}

// The destructor (0x001fa2b8).
static void viewDestroy(void)
{
    BAnim* a = anim();

    if (!s_live) return;
    setHelpOverride(NULL);
    flailer_set_top_left_x(s_view.screen, OBJ_TRACK_LOGO,
                           (int32_t)s_view.trackLogo.origX);
    flailer_set_alpha(s_view.screen, OBJ_TRACK_LOGO,
                      (int32_t)s_view.trackLogo.alpha);
    carLogosRelease(&s_view.carLogos);
    flailer_set_alpha(s_view.screen, OBJ_CAR_LOGO,
                      (int32_t)s_view.carLogos.alpha);
    if (a) banim_blurb_release(a, &s_view.blurby);
    resetClip();
    s_live = 0;
    trace("etv close");
}

// RenderIndicator (0x001fa098): brackets at the current panel's corners,
// pulsing.
static void renderIndicator(EtvLeaf* l, const bMatrix4* m)
{
    bVector2 min, max;
    bVector4 c, p0, p1;
    float    x0, y0, x1, y1, dx, dy;

    leafBox(l, &min, &max);
    inflateRect(&min, &max, 1.05f);
    c.x = 128.0f;
    c.y = 128.0f;
    c.z = 128.0f;
    c.w = (sinf(s_view.indicatorAnimate) + 1.0f) * 64.0f;
    mulPoint(&p0, m, min.x, min.y);
    mulPoint(&p1, m, max.x, max.y);
    x0 = p0.x;
    y0 = p0.y;
    x1 = p1.x;
    y1 = p1.y;
    dx = 0.15f * (x1 - x0);
    dy = 0.15f * (y1 - y0);
    s_view.indicatorAnimate += 0.2f;
    renderHLine(x0, x0 + dx, y0, &c);
    renderHLine(x1 - dx, x1, y0, &c);
    renderHLine(x0, x0 + dx, y1, &c);
    renderHLine(x1 - dx, x1 + 2.0f, y1, &c);
    renderVLine(y0, y0 + dy, x0, &c);
    renderVLine(y1 - dy, y1, x0, &c);
    renderVLine(y0, y0 + dy, x1, &c);
    renderVLine(y1 - dy, y1, x1, &c);
}

// OnRender (0x001fa458).
static void viewRender(void)
{
    EtvView* v = &s_view;
    int      s = v->viewState;

    if (shouldRenderTree(s)) {
        eIdentity(&v->viewMatrix);
        v->viewMatrix.v0.x *= v->zoom.val;
        v->viewMatrix.v0.y *= v->zoom.val;
        v->viewMatrix.v0.z *= v->zoom.val;
        v->viewMatrix.v0.w *= v->zoom.val;
        v->viewMatrix.v1.x *= v->zoom.val;
        v->viewMatrix.v1.y *= v->zoom.val;
        v->viewMatrix.v1.z *= v->zoom.val;
        v->viewMatrix.v1.w *= v->zoom.val;
        v->viewMatrix.v3.x = v->pan.x.val;
        v->viewMatrix.v3.y = v->pan.y.val;
        setClip(v->clipMin, v->clipMax);
        for (int i = 0; i < v->nGroups; i++)
            groupRender(&v->groups[i], &v->viewMatrix);
        for (int i = 0; i < v->nLeaves; i++) {
            EtvLeaf* l = &v->leaves[i];
            if (l != v->cur) {
                setClip(v->clipMin, v->clipMax);
                leafRender(l, &v->viewMatrix, 0.2f);
            } else {
                if (s == VS_TREE) setClip(v->clipMin, v->clipMax);
                else resetClip();
                leafRender(l, &v->viewMatrix,
                           l->info->nNumber == 32 && statusOf(l->info) == 0
                               ? 0.2f : v->alpha.val);
            }
        }
        setClip(v->clipMin, v->clipMax);
        renderIndicator(v->cur, &v->viewMatrix);
        resetClip();
    }
    if (shouldRenderDetails(s))
        detailsRender(&v->details, v->cur->info, 1.0f - v->alpha.val);
    if (shouldRenderReward(s))
        rewardRender(&v->reward, v->cur, v->alpha.val);
    else
        rewardHide(&v->reward, v->cur);
    if (s == VS_POPUP) popupRender(&v->popup, v->alpha.val);
}

// OnTick (0x001fa698).
static void viewTick(void)
{
    EtvView* v  = &s_view;
    float    dt = v->gf ? v->gf->realElapsed : 0.0f;
    BAnim*   a  = anim();

    bspline_seek(&v->zoom, dt);
    bspline2d_seek(&v->pan, dt);
    bspline_seek(&v->alpha, dt);
    eventBlurbAnimate(&v->eventBlurb);
    if (v->alpha.state == 0) {
        switch (v->viewState) {
        case VS_TRANSIT_TO_DETAILS:
            v->viewState = VS_DETAILS;
            *keptState() = VS_DETAILS;
            break;
        case VS_TRANSIT_TO_TREE:
            v->viewState = VS_TREE;
            *keptState() = VS_TREE;
            break;
        case VS_TRANSIT_FROM_REWARD:
            v->viewState = VS_DETAILS;
            *keptState() = VS_DETAILS;
            rewardHide(&v->reward, v->cur);
            break;
        case VS_TRANSIT_TO_REWARD:
            v->viewState = VS_REWARD;
            rewardSyncHelp(&v->reward);
            break;
        default:
            break;
        }
    }
    flailer_set_group_visibility(v->screen, GROUP_EVENT_BLURB,
                                 v->viewState == VS_TREE);
    bspline2d_seek(&v->parallaxer, dt);
    if (a) banim_blurb_animate(a, &v->blurby);
    carLogosTick(&v->carLogos);
    trackLogoTick(&v->trackLogo);
}

// HandleMessage (0x001faf60).
static void viewHandle(BScreenMessage msg, BScreenCallbackData* data)
{
    EtvView* v = &s_view;

    if (isInTransit(v->viewState)) {
        data->noise = SND_NONE;
        data->param = 0;
        return;
    }
    switch (v->viewState) {
    case VS_DETAILS:
        if (msg == BMSG_SCREEN_BACK_BUTTON) {
            transitDetailsToTree();
            data->param = 0;
            data->noise = SND_SELECT;
        } else if (msg == BMSG_MENUITEM_SQUARE) {
            if (v->cur->info->nRewards > 0) {
                data->noise = SND_REWARD;
                transitDetailsToReward();
            } else {
                data->noise = SND_NO_REWARD;
            }
        } else {
            detailsHandle(&v->details, msg, data, v->cur);
        }
        return;
    case VS_REWARD:
        if (!rewardHandle(msg, data)) {
            data->noise = SND_REWARD;
            transitRewardToDetails();
        }
        return;
    case VS_POPUP:
        if (!popupHandle(msg, data)) popupClosed();
        return;
    case VS_TREE:
        break;
    default:
        return;
    }

    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        data_event_select_set_selected_event(Fred.SelectedEventData,
                                             v->tree->nType,
                                             v->cur->info->nNumber);
        transitTreeToDetails();
        data->noise = SND_SELECT;
        break;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        if (maybeChangeLeaf(msg == BMSG_MENUITEM_PAD_LEFT ? -1 : 1)) {
            maybeChangeView();
            data->noise = SND_LEFT_RIGHT;
        } else {
            data->noise = SND_NONE;
        }
        break;
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
        if (maybeChangeLeaf(msg == BMSG_MENUITEM_PAD_UP ? 2 : -2)) {
            maybeChangeView();
            data->noise = SND_UP_DOWN;
        } else {
            data->noise = SND_NONE;
        }
        break;
    case BMSG_SCREEN_L1:
        if (s_h && s_h->debugUnlock && s_h->debugUnlock(s_h->user)) {
            leafUnlock(v->cur);
            for (int i = 0; i < v->nGroups; i++)
                groupColourBars(&v->groups[i]);
        }
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        data_event_select_set_selected_event(Fred.SelectedEventData,
                                             v->tree->nType,
                                             v->cur->info->nNumber);
        break;
    default:
        break;
    }
}

// ------------------------------------------------------------- the callback

void eventtreeview_init(const EtvHooks* h)
{
    s_h = h;
}

int eventtreeview_active(void)
{
    return s_live;
}

void eventtreeview_screen_callback(BGameFlow* gf, BScreenMessage msg,
                                   BScreenCallbackData* data)
{
    switch (msg) {
    case BMSG_SCREEN_ACTIVATE: {
        EventTree* tree = fred_get_event_tree(&Fred);
        viewDestroy();
        if (!tree || tree->nEvents <= 0 || !tree->pEvents) {
            trace("etv no tree");
            return;
        }
        viewInit(gf, ETV_SCREEN, tree);
        return;
    }
    case BMSG_SCREEN_UNACTIVATE:
        viewDestroy();
        return;
    default:
        break;
    }
    if (!s_live) return;
    s_view.gf = gf;
    if (msg == BMSG_SCREEN_RENDER) viewRender();
    else if (msg == BMSG_SCREEN_TICK) viewTick();
    else if (data) viewHandle(msg, data);
}
