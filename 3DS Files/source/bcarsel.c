// bcarsel -- see bcarsel.h.

#include "bcarsel.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "flailer.h"
#include "fredrace.h"
#include "realtime.h"

int32_t AllCarsAvailableInCarSelectScreen;

static BCarSel* g_m;

// The objects on the car select screens, by NameHash (or GroupHash).
#define OBJ_FADE_A         0x0015678fu   // group: out as orbit comes in
#define OBJ_FADE_B         0x036e80bfu   // group: in with orbit
#define OBJ_FADE_C         0x0961a600u   // group
#define OBJ_BLACK          0x75c8b565u   // the black over the car
#define OBJ_NEXT_ARROW     0xabb370a6u
#define OBJ_PREV_ARROW     0x84f544f3u
#define OBJ_POINTS         0x736163fcu   // "NFS Points: n"
#define OBJ_UNLOCKED       0x09b562fdu   // "Cars Unlocked: n/m"
#define OBJ_TOP_SPEED      0x0c0384ccu
#define OBJ_ZERO_TO_60     0xe6882001u
#define OBJ_BHP            0xe79e7936u
#define OBJ_CLASS          0x02920d75u
#define OBJ_CLASS_LABEL    0xd8b0bab5u
#define OBJ_INFO_4         0xc86209a4u
#define OBJ_INFO_5         0xc86209a5u
#define OBJ_INFO_6         0xc86209a6u
#define OBJ_CAR_NAME       0x39e91754u
#define OBJ_CAR_LOGO       0xb270d4a5u
#define OBJ_BADGE          0x729a0c4bu
#define OBJ_SWATCH_TOP     0xedf2e4eeu
#define OBJ_SWATCH_BOTTOM  0x20d73d01u
#define OBJ_SWATCH_RING    0x7fe46db3u
#define OBJ_LOCK           0x2561a343u   // before the first locked thumbnail

// The unlock popup's.
#define OBJ_UNLOCK_GROUP   0x6a096871u
#define OBJ_UNLOCK_BOX     0xa8af730bu   // the group's master
#define OBJ_UNLOCK_FADE    0xbea3c79cu
#define OBJ_UNLOCK_TEXT    0x2a67e2d5u   // the font, never shown
#define OBJ_UNLOCK_RECT    0x2a65daf9u   // where the blurb goes

// The popups' FlailerScreenConfigs.
#define POPUP_SCREEN_1P    0x41c2fdc3u
#define POPUP_SCREEN_2P    0x6344da01u
#define POPUP_SCREEN_2P_LO 0x6344da02u

// Language IDs.
#define LANG_NFS_POINTS    0xbfb0
#define LANG_CARS_UNLOCKED 0xbfaf
#define LANG_CLASS         0xbfb1
#define LANG_MPH           0x2234a
#define LANG_KPH           0x2234b
#define LANG_SECONDS       0xa410
#define LANG_BHP           0xabe0
#define LANG_TRANS_MSG     0xbf68
#define LANG_TRANS_AUTO    0xbf7c
#define LANG_TRANS_MANUAL  0xbf86
#define LANG_TRANS_3       0xbf72
#define LANG_HANDLING_MSG  0xbf90
#define LANG_HANDLING_1    0xbf9a
#define LANG_HANDLING_2    0xbfa4
#define LANG_WAITING_MSG   0xbfae

#define THUMB_STEP      39.0f
#define THUMB_BASE_1P   377.0f            // gp-29652
#define THUMB_BASE_2P   395.0f            // gp-29648
#define MAX_CLOAKS      25
#define ORBIT_TIMEOUT   2400              // RealTimeFrames, 40 s
#define MODE_STEP       0.03f
#define TURN_STEP       46

// ------------------------------------------------------------ the hooks

static const char* trId(const BCarSelHooks* h, int32_t id)
{
    const char* s = h && h->translate ? h->translate(h->user, id) : NULL;
    return s ? s : "";
}

static const char* trStr(const BCarSelHooks* h, const char* s)
{
    const char* t = h && h->translateString
                        ? h->translateString(h->user, s) : s;
    return t ? t : "";
}

static void sound(const BCarSelHooks* h, int32_t ev)
{
    if (h->sound) h->sound(h->user, ev);
}

static void trace(const BCarSelHooks* h, const char* fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void trace(const BCarSelHooks* h, const char* fmt, ...)
{
    char    line[160];
    va_list ap;
    if (!h->trace) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    h->trace(h->user, line);
}

static void setHelp(const BCarSelHooks* h, const int32_t* lines)
{
    if (h->setHelpOverride) h->setHelpOverride(h->user, lines);
}

static void speechFade(const BCarSelHooks* h, float level)
{
    if (h->speechFade) h->speechFade(h->user, level);
}

static int soundEnabled(const BCarSelHooks* h)
{
    return h->soundEnabled ? h->soundEnabled(h->user) : 0;
}

// RideInfo::Init(type, -1, 0, 0), what every CarLoader call is handed.
static RideInfo loaderRide(int32_t type)
{
    RideInfo ri;
    ride_info_init(&ri, type, -1, 0, 0);
    return ri;
}

static void loaderLoad(const BCarSelHooks* h, int32_t type)
{
    RideInfo ri = loaderRide(type);
    if (h->loaderLoad) h->loaderLoad(h->user, &ri);
}

static void loaderUnload(const BCarSelHooks* h, int32_t type)
{
    RideInfo ri = loaderRide(type);
    if (h->loaderUnload) h->loaderUnload(h->user, &ri);
}

static int loaderIsLoaded(const BCarSelHooks* h, int32_t type)
{
    RideInfo ri = loaderRide(type);
    return h->loaderIsLoaded ? h->loaderIsLoaded(h->user, &ri) : 1;
}

static void loaderBeginLoading(const BCarSelHooks* h)
{
    if (h->loaderBeginLoading) h->loaderBeginLoading(h->user);
}

// bStrCmp (0x002535f8): signed bytes, the difference where they part.
static int32_t bStrCmp(const char* a, const char* b)
{
    int32_t x, y;
    for (;;) {
        x = (int8_t)*a++;
        y = (int8_t)*b++;
        if (x == 0 || y == 0 || x != y) return x - y;
    }
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

// The skin byte `i` of a car's list, read the way `lbu` reads it.
static int32_t skinAt(const CarStatus* st, int32_t i)
{
    return ((const uint8_t*)st->aSkins)[i];
}

static const CarTypeInfo* cti(int32_t type)
{
    return cartypeinfo_get(type);
}

static int isCop(int32_t type)
{
    return cti(type)->UsageType == CAR_USAGE_TYPE_COP;
}

static int isHP(int32_t type)
{
    return cti(type)->HighPerformance != 0;
}

// The spec ids GetShortName (0x00187eb8, really the full name),
// GetCarSpec0To60, GetCarSpecTopSpeed and GetCarSpecBHP hand to
// GetTranslatedString. pCarSpecs is never NULL on the disc; 0 if it were.
static int32_t specFullName(const CarTypeInfo* c)
{
    return c->pCarSpecs ? c->pCarSpecs->FullName : 0;
}

static const char* fullName(const BCarSelHooks* h, int32_t type)
{
    return trId(h, specFullName(cti(type)));
}

// --------------------------------------------------------- VisibleCar

// SetSkin (0x001942d0): the skin's place in the car's list, if it is there.
static void carSetSkin(VisibleCar* c, int32_t skin)
{
    int32_t i;
    for (i = 0; i < c->status->nSkins; i++) {
        if (skinAt(c->status, i) == skin) {
            c->skinIndex = i;
            return;
        }
    }
}

// NextSkin (0x00194350) and PrevSkin (0x00194380).
static void carNextSkin(VisibleCar* c)
{
    if (++c->skinIndex >= c->status->nSkins) c->skinIndex = 0;
}

static void carPrevSkin(VisibleCar* c)
{
    if (--c->skinIndex < 0) c->skinIndex = c->status->nSkins - 1;
}

// The constructor (0x00194250).
static void carInit(VisibleCar* c, int32_t type, CarStatus* st, int32_t idx)
{
    c->available = 0;
    c->skinIndex = 0;
    c->status    = st;
    c->carIndex  = idx;
    c->type      = type;
    c->thumbHash = hashf("THUMBNAIL_%s", cti(type)->CarTypeName);
    carSetSkin(c, cti(type)->DefaultSkinNumber);
}

static void listAppend(bNode* list, bNode* n)
{
    n->prev          = list->prev;
    n->next          = list;
    list->prev->next = n;
    list->prev       = n;
}

// ------------------------------------------------------ VisibleCarSet

// CarListSort (0x00194728): the available cars first, then the racers
// before the cops, the ordinary before the high performance, the higher
// class first, and last the name. The name only breaks a tie one way:
// a's key gains 1 when it sorts after b, so equal names keep their order.
static const BCarSelHooks* s_sortHooks;

static int32_t carListSort(bNode* na, bNode* nb)
{
    const VisibleCar* a = (const VisibleCar*)na;
    const VisibleCar* b = (const VisibleCar*)nb;
    const CarTypeInfo* ca = cti(a->type);
    const CarTypeInfo* cb = cti(b->type);
    uint32_t ka = a->available ? 0 : 0x40000000u;
    uint32_t kb = b->available ? 0 : 0x40000000u;
    char     nameA[256];

    if (ca->UsageType == CAR_USAGE_TYPE_COP) ka += 0x01000000u;
    if (cb->UsageType == CAR_USAGE_TYPE_COP) kb += 0x01000000u;
    ka += (uint32_t)((int32_t)ca->HighPerformance << 16);
    kb += (uint32_t)((int32_t)cb->HighPerformance << 16);
    ka += (uint32_t)((5 - (int32_t)ca->CarClass) << 8);
    kb += (uint32_t)((5 - (int32_t)cb->CarClass) << 8);

    // The translation may come back in a buffer the next one reuses.
    snprintf(nameA, sizeof(nameA), "%s", trId(s_sortHooks, specFullName(ca)));
    ka += bStrCmp(nameA, trId(s_sortHooks, specFullName(cb))) > 0;
    return !(kb < ka);
}

// The constructor (0x001944e8).
void bcarsel_set_init(VisibleCarSet* s, const BCarSelHooks* h,
                      FrontendPlayerInfo* player, int copsOnly)
{
    int32_t     i, n = 0, unlocked = 0;
    VisibleCar* c;
    bNode*      node;

    memset(s, 0, sizeof(*s));
    s->list.next = s->list.prev = &s->list;

    for (i = 0; i < BCARSEL_MAX_CARS; i++) {
        CarStatus* st = &player->aCarStatus[i];
        RideInfo*  ride;

        if (st->nStatus == CAR_STATUS_HIDDEN
            && !AllCarsAvailableInCarSelectScreen)
            continue;
        c = &s->cars[s->used++];
        carInit(c, i, st, n++);
        listAppend(&s->list, &c->node);
        if (st->nStatus == CAR_STATUS_AVAILABLE
            || (h->eggActive && h->eggActive(h->user, i, copsOnly))) {
            c->available = 1;
            unlocked++;
        } else {
            c->available = 0;
        }
        ride = fpi_get_selected_ride_info(player, Fred.GameType);
        if (ride->Type == i) {
            s->current = c;
            carSetSkin(c, (int8_t)ride->SkinNumber);
        }
    }
    s->total    = n;
    s->unlocked = unlocked;

    // SortVisibleCarList (0x00194830), then each car numbered by its place.
    s_sortHooks = h;
    blist_sort(&s->list, carListSort);
    i = 0;
    for (node = s->list.next; node != &s->list; node = node->next)
        ((VisibleCar*)node)->carIndex = i++;

    if (!s->current && s->list.next != &s->list)
        s->current = (VisibleCar*)s->list.next;
}

// The copy constructor (0x001943d8): the same cars in the same order.
void bcarsel_set_copy(VisibleCarSet* d, const VisibleCarSet* s)
{
    const bNode* node;

    memset(d, 0, sizeof(*d));
    d->list.next = d->list.prev = &d->list;
    d->total     = s->total;
    d->unlocked  = s->unlocked;
    for (node = s->list.next; node != &s->list; node = node->next) {
        const VisibleCar* from = (const VisibleCar*)node;
        VisibleCar*       to   = &d->cars[d->used++];
        to->status    = from->status;
        to->type      = from->type;
        to->available = from->available;
        to->skinIndex = from->skinIndex;
        to->thumbHash = from->thumbHash;
        to->carIndex  = from->carIndex;
        listAppend(&d->list, &to->node);
        if (from == s->current) d->current = to;
    }
    if (!d->current && d->list.next != &d->list)
        d->current = (VisibleCar*)d->list.next;
}

// GetNextCar (0x001943a8) and GetPrevCar (0x001943c0): the car itself at
// either end.
VisibleCar* bcarsel_next_car(VisibleCarSet* s, VisibleCar* c)
{
    return c->node.next == &s->list ? c : (VisibleCar*)c->node.next;
}

VisibleCar* bcarsel_prev_car(VisibleCarSet* s, VisibleCar* c)
{
    return c->node.prev == &s->list ? c : (VisibleCar*)c->node.prev;
}

// ------------------------------------------------------ the preload

void bcarsel_preload(void)
{
    const BCarSelHooks* h;
    static VisibleCarSet set;
    int32_t             i;

    if (!g_m) return;
    h = &g_m->hooks;
    for (i = 0; i < Fred.NumPlayerCars && i < 2; i++) {
        int32_t type;
        bcarsel_set_init(&set, h, &Fred.FrontendPlayers[i],
                         i == 0 && Fred.GameType == GAME_TYPE_BE_A_COP);
        if (!set.current) continue;
        type = set.current->type;
        if (g_m->preloaded[i] == type) continue;
        if (g_m->preloaded[i] != -1) loaderUnload(h, g_m->preloaded[i]);
        g_m->preloaded[i] = type;
        if (h->loaderFrontEnd) h->loaderFrontEnd(h->user);
        loaderLoad(h, type);
        loaderBeginLoading(h);
        trace(h, "carsel preload player %d: %s", (int)i,
              cti(type)->CarTypeName);
    }
}

// 0x00194a00.
static void preloadUnload(void)
{
    int32_t i;
    for (i = 0; i < 2; i++) {
        if (g_m->preloaded[i] == -1) continue;
        loaderUnload(&g_m->hooks, g_m->preloaded[i]);
        g_m->preloaded[i] = -1;
    }
}

// InitSelectCarScreen is InitSpotlights (SC-2's); Close unloads the
// preload, then CloseSpotlights.
void bcarsel_init_screen(void)
{
}

void bcarsel_close_screen(void)
{
    if (g_m) preloadUnload();
}

// ----------------------------------------------- feAlphaAnimation

static int isBitmap(const struct FlailerObjectChunk* o)
{
    return o->ObjectType == FLAILER_TYPE_BITMAP;
}

#define BITMAP(o) ((struct FlailerBitmapChunk*)(void*)(o))

// The constructor (0x00248360): every object of the group, its alphas.
static void fadeInit(BCarSelFade* f, uint32_t screen, uint32_t group)
{
    struct FlailerObjectChunk* o = NULL;
    f->screen = screen;
    f->count  = 0;
    while ((o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                             o)) != NULL
           && f->count < BCARSEL_MAX_FADE) {
        int32_t i;
        f->el[f->count].obj = o;
        for (i = 0; i < 4; i++)
            f->el[f->count].alpha[i] =
                (float)(isBitmap(o) ? flailerbitmap_get_alpha(BITMAP(o), i)
                                    : flailerobject_get_alpha(o));
        f->count++;
    }
}

// SetAlphaScale (0x002484c0).
static void fadeScale(BCarSelFade* f, float s)
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
static void fadeRestore(BCarSelFade* f)
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

static void slidePlace(BCarSelSlide* a, int32_t x, int32_t y)
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

// SetupToAnimate: jump to `start`, head for `end`.
static void slideSetup(BCarSelSlide* a, float start, float end)
{
    BSpline* s = &a->spline;
    s->flags = 0;
    splineAim(s, start);
    s->state = 0;
    s->val   = s->valDesired;
    s->dval  = s->dvalDesired;
    splineAim(s, end);
    slidePlace(a, ee_trunc_w(s->val), a->savedY);
}

// The constructor (0x00248568).
static void slideInit(BCarSelSlide* a, uint32_t screen, uint32_t group,
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

static void slideAnimate(BCarSelSlide* a)
{
    bspline_seek(&a->spline, RealTimeElapsed);
    slidePlace(a, ee_trunc_w(a->spline.val), a->savedY);
}

// The destructor: back where it was laid out.
static void slideRestore(BCarSelSlide* a)
{
    slidePlace(a, a->savedX, a->savedY);
}

// ------------------------------------------------- the unlock popup

static void unlockInit(BCarSelUnlock* u, uint32_t screen)
{
    memset(u, 0, sizeof(*u));
    u->screen = screen;
    u->x      = flailer_get_top_left_x(screen, OBJ_UNLOCK_BOX);
    u->alpha  = flailer_get_alpha(screen, OBJ_UNLOCK_FADE);
    slideInit(&u->slide, screen, OBJ_UNLOCK_GROUP, OBJ_UNLOCK_BOX, 640.0f,
              u->x, 0.5f);
    u->state = 2;
    u->start = 0;
    u->hide  = 0;
    u->car   = NULL;
}

static void unlockShow(BCarSelUnlock* u)
{
    flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 1);
    flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 1);
    slideSetup(&u->slide, 650.0f, u->x);
    u->state = 2;
    u->start = RealTimer;
}

static void unlockHide(BCarSelUnlock* u)
{
    flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 0);
    flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 0);
    u->state = 1;
    u->hide  = RealTimer;
}

// SetCar (0x00194b28). `flag` is FormatUnlockBlurbForCar's last argument:
// both callers pass port == 1 (the ScreenCallback as (port ^ 1) < 1).
static void unlockSetCar(CarSelector* c, VisibleCar* car, int flag)
{
    const BCarSelHooks* h = c->hooks;
    BCarSelUnlock*      u = &c->unlock;

    if (car == u->car) return;
    u->car = car;
    if (car->available || c->allUnlocked) {
        flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 0);
        flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 0);
        u->state = 0;
    } else {
        flailer_set_group_visibility(u->screen, OBJ_UNLOCK_GROUP, 1);
        flailer_set_visibility(u->screen, OBJ_UNLOCK_FADE, 1);
        u->state = 2;
    }
    flailer_set_visibility(u->screen, OBJ_UNLOCK_TEXT, 0);
    snprintf(u->blurb, sizeof(u->blurb), "%s", "This car should be unlocked");
    if (h->formatUnlockBlurb)
        h->formatUnlockBlurb(h->user, u->blurb, (int)sizeof(u->blurb),
                             car->type, Fred.GameType, flag);
    slideSetup(&u->slide, 650.0f, u->x);
    u->start = RealTimer;
}

static void unlockTick(BCarSelUnlock* u)
{
    float t    = (float)(RealTimer - u->start) * 0.00025f;
    float frac = 0.0f;

    if (0.4f < t) {
        frac = (t - 0.4f) / 0.5f;
        slideAnimate(&u->slide);
    }
    flailer_set_alpha(u->screen, OBJ_UNLOCK_FADE,
                      frac < 1.0f ? ee_trunc_w((float)u->alpha * frac)
                                  : u->alpha);
    // hide is in the past, so this never comes true.
    if (u->state == 1 && 40.0f < (float)(u->hide - RealTimer) * 0.00025f)
        unlockShow(u);
}

static void unlockRender(CarSelector* c)
{
    const BCarSelHooks* h = c->hooks;
    BCarSelUnlock*      u = &c->unlock;

    if (!u->car || u->car->available || c->allUnlocked || u->state != 2)
        return;
    flailer_set_visibility(u->screen, OBJ_UNLOCK_TEXT, 0);
    if (h->renderTextIntoRectangle)
        h->renderTextIntoRectangle(h->user, u->screen, OBJ_UNLOCK_TEXT,
                                   OBJ_UNLOCK_RECT, u->blurb, 1.0f);
}

static void unlockJoy(CarSelector* c, int32_t ev, uint8_t pressed)
{
    BCarSelUnlock* u = &c->unlock;

    if (u->state == 2) {
        if (ev == BCARSEL_JOY_CHANGE_MODE && pressed && u->car
            && !u->car->available && !c->allUnlocked) {
            unlockHide(u);
            sound(c->hooks, 5);
        }
    } else if (u->state == 1) {
        if (pressed) {
            unlockShow(u);
            sound(c->hooks, 5);
        }
    }
}

// Hidden, the box comes back on any of the screen's own presses, and
// takes it.
static int unlockCallback(BCarSelUnlock* u, BScreenMessage msg,
                          BScreenCallbackData* data)
{
    if (u->state != 1) return 0;
    switch (msg) {
        case BMSG_MENUITEM_SELECT:
        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT:
        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
        case BMSG_SCREEN_BACK_BUTTON:
            unlockShow(u);
            data->noise = 5;
            return 1;
        default:
            return 0;
    }
}

// ------------------------------------------------------ CarSelector

static VisibleCar* cur(CarSelector* c)
{
    return c->set.current;
}

// The CARCOVER test (UpdateCarCover): a car still to be won, shown
// covered, its name and stats hidden.
static int covered(const CarSelector* c, const VisibleCar* car)
{
    return !car->available && !c->allUnlocked
           && car->status->nStatus == 4;
}

// UpdateCarCover: the cover on both rendering cars, SC-2's.
static void updateCarCover(CarSelector* c)
{
    (void)c;
}

// ShowLoadedCar (0x00197ff8).
static void showLoadedCar(CarSelector* c)
{
    const BCarSelHooks* h = c->hooks;
    RideInfo            ri;

    if (!c->loaded) return;
    // Instance 0, the skin worn, no dash.
    ride_info_init(&ri, c->loaded->type,
                   skinAt(c->loaded->status, c->loaded->skinIndex), 0, 0);
    if (h->showLoadedCar) h->showLoadedCar(h->user, c->playerNum, &ri);
}

// The make's logo: CARLOGO_ and the car's name, which for two players is
// the plain car's, the high performance and cop models having no logo of
// their own at that size.
static uint32_t logoHash(const CarSelector* c, int32_t type)
{
    const CarTypeInfo* ct = cti(type);
    char               buf[40];
    size_t             n;

    snprintf(buf, sizeof(buf), "%s", ct->CarTypeName);
    if (c->twoPlayer) {
        if (ct->HighPerformance) {
            if (strcmp(buf, "SPIDERHP") == 0) {
                snprintf(buf, sizeof(buf), "%s", "SPIDERHP2P");
            } else {
                n = strlen(buf);
                buf[n >= 2 ? n - 2 : 0] = 0;
            }
        } else if (ct->UsageType == CAR_USAGE_TYPE_COP) {
            static const char* const kCops[5][2] = {
                { "CROWNVIC",    "CROWNVICNOCOP" },
                { "BMWM5COP",    "BMWM5" },
                { "MUSTANGCOP",  "MUSTANG" },
                { "CORVETTECOP", "CORVETTE" },
                { "LAMBOCOP",    "MURCIELAGO" },
            };
            int i;
            for (i = 0; i < 5; i++) {
                if (strcmp(buf, kCops[i][0]) == 0) {
                    snprintf(buf, sizeof(buf), "%s", kCops[i][1]);
                    break;
                }
            }
        }
    }
    return hashf("CARLOGO_%s", buf);
}

static uint32_t badgeHash(const CarSelector* c, int32_t type)
{
    if (!c->twoPlayer) return 0;
    if (isCop(type)) return bchunk_hash("LOGO_SHERIFF");
    if (isHP(type)) return bchunk_hash("LOGO_NFS");
    return 0;
}

// UpdateLogo: the name, the logo and the two-player badge.
static void updateLogo(CarSelector* c)
{
    const BCarSelHooks* h   = c->hooks;
    VisibleCar*         car = cur(c);
    uint32_t            badge;

    if (covered(c, car)) {
        flailer_set_visibility(c->screen, OBJ_CAR_NAME, 0);
        flailer_set_visibility(c->screen, OBJ_CAR_LOGO, 0);
        return;
    }
    flailer_set_visibility(c->screen, OBJ_CAR_NAME, 1);
    flailer_set_visibility(c->screen, OBJ_CAR_LOGO, 1);
    flailer_printf(c->screen, OBJ_CAR_NAME, "%s",
                   trStr(h, fullName(h, car->type)));
    flailer_change_texture(c->screen, OBJ_CAR_LOGO, logoHash(c, car->type));
    badge = badgeHash(c, car->type);
    if (badge) {
        flailer_change_texture(c->screen, OBJ_BADGE, badge);
        flailer_set_visibility(c->screen, OBJ_BADGE, 1);
    } else {
        flailer_set_visibility(c->screen, OBJ_BADGE, 0);
    }
}

// FrontendDatabase::UseTreeEvent (0x001841e8): the single race's and the
// championship's game types, 8 and 9, which run off the event trees.
static int useTreeEvent(void)
{
    return Fred.GameType >= 8 && Fred.GameType < 10;
}

// UpdateInfoBarAtTop (0x001978c8): top speed, 0-60, BHP and class, with
// "+" or "-" for the cars that beat their figures; and the cars unlocked.
static void updateInfoBar(CarSelector* c)
{
    static const uint32_t kInfo[8] = {
        OBJ_TOP_SPEED, OBJ_ZERO_TO_60, OBJ_BHP, OBJ_CLASS, OBJ_CLASS_LABEL,
        OBJ_INFO_4, OBJ_INFO_5, OBJ_INFO_6,
    };
    const BCarSelHooks* h   = c->hooks;
    VisibleCar*         car = cur(c);
    const CarTypeInfo*  ct  = cti(car->type);
    int                 cop = ct->UsageType == CAR_USAGE_TYPE_COP;
    int                 i;

    if (covered(c, car) || cop) {
        for (i = 0; i < 8; i++)
            flailer_set_visibility(c->screen, kInfo[i], 0);
    } else {
        int         plus  = ct->HighPerformance || cop;
        int32_t     units = Fred.DisplayOptionsData.Units;
        int32_t     speed = 0;
        const char* value;
        for (i = 0; i < 8; i++)
            flailer_set_visibility(c->screen, kInfo[i], 1);
        if (ct->pCarSpecs) {
            if (units == 1) speed = ct->pCarSpecs->TopSpeedKph;
            else if (units == 0) speed = ct->pCarSpecs->TopSpeedMph;
        }
        // Each figure is translated before its unit, as retail calls them.
        value = trId(h, speed);
        flailer_printf(c->screen, OBJ_TOP_SPEED, "%s%s %s", value,
                       plus ? "+" : "",
                       trId(h, units != 0 ? LANG_KPH : LANG_MPH));
        value = trId(h, ct->pCarSpecs ? ct->pCarSpecs->ZeroTo60 : 0);
        flailer_printf(c->screen, OBJ_ZERO_TO_60, "%s%s %s", value,
                       plus ? "-" : "", trId(h, LANG_SECONDS));
        value = trId(h, ct->pCarSpecs ? ct->pCarSpecs->BHP : 0);
        flailer_printf(c->screen, OBJ_BHP, "%s%s %s", value,
                       plus ? "+" : "", trId(h, LANG_BHP));
        flailer_printf(c->screen, OBJ_CLASS, "%d", ct->CarClass + 1);
        flailer_printf(c->screen, OBJ_CLASS_LABEL, "%s", trId(h, LANG_CLASS));
    }
    flailer_printf(c->screen, OBJ_UNLOCKED, "%s %d/%d",
                   trId(h, LANG_CARS_UNLOCKED), (int)c->set.unlocked,
                   (int)c->set.total);
    flailer_set_visibility(c->screen, OBJ_UNLOCKED, useTreeEvent() ? 0 : 1);
}

// The help bar's lines.
static const int32_t kHelpChooseSingle[] = {800039, 800040, 800401, 800041,
                                            800042, 0};
static const int32_t kHelpChooseChamp[]  = {800053, 800054, 800400, 800055,
                                            800056, 0};
static const int32_t kHelpChooseCop1[]   = {800701, 800702, 800703, 800704, 0};
static const int32_t kHelpChooseCop2[]   = {800705, 800706, 800707, 800708, 0};
static const int32_t kHelpChoose2P[]     = {802000, 802001, 802002, 802003, 0};
static const int32_t kHelpOrbitSingle[]  = {802004, 802005, 802008, 0};
static const int32_t kHelpOrbitChamp[]   = {802010, 802011, 802014, 0};
static const int32_t kHelpOrbit[]        = {800023, 800024, 800027, 0};

// AdjustHelpMessage (0x00196698).
static void adjustHelp(CarSelector* c)
{
    const BCarSelHooks* h   = c->hooks;
    int32_t             gt  = Fred.GameType;
    int32_t             npc = Fred.NumPlayerCars;

    if (c->mode == c->chooseMode) {
        if (gt == 8) {
            setHelp(h, kHelpChooseSingle);
        } else if (gt == 9) {
            setHelp(h, kHelpChooseChamp);
        } else if (gt == GAME_TYPE_BE_A_COP) {
            if (npc == 1) setHelp(h, kHelpChooseCop1);
            else if (npc == 2) setHelp(h, kHelpChooseCop2);
        } else {
            if (npc == 1) setHelp(h, NULL);
            else if (npc == 2) setHelp(h, kHelpChoose2P);
        }
    } else if (c->mode == c->orbitMode) {
        if (gt == 8) setHelp(h, kHelpOrbitSingle);
        else if (gt == 9) setHelp(h, kHelpOrbitChamp);
        else setHelp(h, kHelpOrbit);
    }
}

// SetupSwatches (0x00195c98): one swatch a skin, its colour from the skin.
static void closeSwatches(CarSelector* c)
{
    int32_t i;
    for (i = 0; i < c->nSwatches; i++)
        flailer_set_visibility(c->screen, c->swatchHash[i], 0);
}

static void setupSwatches(CarSelector* c)
{
    VisibleCar* car = cur(c);
    int32_t     i;

    closeSwatches(c);
    c->nSwatches = car->status->nSkins;
    if (c->nSwatches > BCARSEL_MAX_SWATCHES)
        c->nSwatches = BCARSEL_MAX_SWATCHES;
    for (i = 0; i < c->nSwatches; i++) {
        SkinInfo* si = cartypeinfo_get_skin_info(car->type,
                                                 skinAt(car->status, i), 1);
        c->swatchHash[i]   = hashf("SWATCH_%d", (int)i);
        c->swatchColour[i] = si ? si->ColourSwatchHash : 0;
    }
}

// UpdateSwatches (0x00195d78): the column of swatches, the ring round the
// one being worn.
static void updateSwatches(CarSelector* c)
{
    int32_t x, y, i;

    if (c->screen == BCARSEL_SCREEN_2P_LOWER) {
        x = 606;
        y = 321;
    } else if (c->screen == BCARSEL_SCREEN_2P) {
        x = 606;
        y = 77;
    } else {
        x = 587;
        y = 125;
    }
    if (c->nSwatches < 2 || covered(c, cur(c))) {
        flailer_set_visibility(c->screen, OBJ_SWATCH_TOP, 0);
        flailer_set_visibility(c->screen, OBJ_SWATCH_BOTTOM, 0);
        flailer_set_visibility(c->screen, OBJ_SWATCH_RING, 0);
        return;
    }
    flailer_set_visibility(c->screen, OBJ_SWATCH_TOP, 1);
    flailer_set_top_left_position(c->screen, OBJ_SWATCH_TOP, x, y - 22);
    for (i = 0; i < c->nSwatches; i++) {
        flailer_change_texture(c->screen, c->swatchHash[i],
                               c->swatchColour[i]);
        flailer_set_visibility(c->screen, c->swatchHash[i], 1);
        flailer_set_top_left_position(c->screen, c->swatchHash[i], x,
                                      y + 18 * i);
        flailer_set_visibility(c->screen, OBJ_SWATCH_RING, 1);
        if (i == cur(c)->skinIndex)
            flailer_set_top_left_position(c->screen, OBJ_SWATCH_RING, x - 4,
                                          y + 18 * i - 4);
    }
    flailer_set_visibility(c->screen, OBJ_SWATCH_BOTTOM, 1);
    flailer_set_top_left_position(c->screen, OBJ_SWATCH_BOTTOM, x,
                                  18 * c->nSwatches + y + 2);
}

// Where the thumbnail row's left end goes for this car.
static float thumbsTarget(CarSelector* c, VisibleCar* car)
{
    float   base  = c->twoPlayer ? THUMB_BASE_2P : THUMB_BASE_1P;
    float   t     = base - (float)car->carIndex * THUMB_STEP;
    int32_t lockW = flailer_get_width(c->screen, OBJ_LOCK);
    if (!car->available) t -= (float)lockW;
    return t;
}

// SetupThumbnails (0x00196040): the row jumps to the car, and every car's
// thumbnail starts hidden.
static void setupThumbnails(CarSelector* c)
{
    BSpline* s = &c->thumbs;
    int32_t  i;

    s->duration = 0.5f;
    s->flags    = 0;
    splineAim(s, thumbsTarget(c, cur(c)));
    s->state = 0;
    s->val   = s->valDesired;
    s->dval  = s->dvalDesired;
    for (i = 0; i < BCARSEL_MAX_CARS; i++)
        flailer_set_visibility(c->screen,
                               hashf("THUMBNAIL_%s", cti(i)->CarTypeName), 0);
}

// UpdateThumbnails (0x00196170): the row, the lock before the first
// locked car, and a cloak over each covered one.
static void updateThumbnails(CarSelector* c)
{
    bNode*  node;
    int32_t y, i, lockW, off = 0, q = 0, lockShown = 0;

    if (c->screen == BCARSEL_SCREEN_2P_LOWER) y = 265;
    else if (c->screen == BCARSEL_SCREEN_2P) y = 25;
    else y = 402;

    bspline_seek(&c->thumbs, RealTimeElapsed);
    for (i = 0; i < MAX_CLOAKS; i++)
        flailer_set_visibility(c->screen, hashf("THUMBNAIL_CLOAK_%d", (int)i),
                               0);
    flailer_set_visibility(c->screen, OBJ_LOCK, 0);
    lockW = flailer_get_width(c->screen, OBJ_LOCK);

    for (node = c->set.list.next; node != &c->set.list; node = node->next) {
        VisibleCar* car = (VisibleCar*)node;
        int32_t     x   = ee_trunc_w(c->thumbs.val) + off;
        uint32_t    hash;

        if (!car->available && car->node.prev != &c->set.list
            && ((VisibleCar*)car->node.prev)->available) {
            flailer_set_visibility(c->screen, OBJ_LOCK, 1);
            lockShown = 1;
            flailer_set_top_left_position(c->screen, OBJ_LOCK, x, y);
        }
        if (lockShown) x += lockW;
        hash = car->thumbHash;
        if (covered(c, car) && q < MAX_CLOAKS) {
            flailer_set_visibility(c->screen, hash, 0);
            hash = hashf("THUMBNAIL_CLOAK_%d", (int)q++);
        }
        flailer_set_visibility(c->screen, hash, 1);
        off += 39;
        flailer_set_top_left_position(c->screen, hash, x, y);
    }
}

// UpdateFadeGroups (0x001977a8).
static void updateFadeGroups(CarSelector* c)
{
    float s = c->shownMode * 3.0f;
    if (1.0f < s) s = 1.0f;
    fadeScale(&c->fadeA, 1.0f - s);
    fadeScale(&c->fadeB, c->shownMode);
    if (isCop(cur(c)->type)) fadeScale(&c->fadeB, 0.0f);
    if (c->shownMode == c->orbitMode)
        fadeScale(&c->fadeC, 0.0f);
    else if (c->mode == c->chooseMode && c->shownMode < 1.0f / 3.0f)
        fadeScale(&c->fadeC, 1.0f);
}

// EnterOrbitMode (0x001967a0) and EnterChooseMode (0x00196878).
static void enterOrbitMode(CarSelector* c)
{
    const BCarSelHooks* h   = c->hooks;
    VisibleCar*         car = cur(c);

    c->orbitFrame   = RealTimeFrames;
    c->mode         = c->orbitMode;
    c->orbitTouched = 0;
    if (soundEnabled(h) && (h->language ? h->language(h->user) : 0) == 0
        && h->speakCar)
        h->speakCar(h->user, car->type, isCop(car->type), isHP(car->type));
    adjustHelp(c);
    trace(h, "carsel orbit");
}

static void enterChooseMode(CarSelector* c)
{
    c->mode = c->chooseMode;
    adjustHelp(c);
    if (soundEnabled(c->hooks)) speechFade(c->hooks, 1.0f);
    trace(c->hooks, "carsel choose");
}

// CanEnterOrbitMode (0x001968e0).
static int canEnterOrbitMode(CarSelector* c, VisibleCar* car)
{
    const BCarSelHooks* h = c->hooks;
    if (h->helpMenuActive && h->helpMenuActive(h->user)) return 0;
    if (c->mode != c->chooseMode) return 0;
    return car->available || c->allUnlocked;
}

// JoyHandler (0x00196958).
static void selJoy(CarSelector* c, int32_t ev, uint8_t pressed)
{
    unlockJoy(c, ev, pressed);
    if (c->state != 0) return;
    switch (ev) {
        case BCARSEL_JOY_CHANGE_MODE:
            if (!pressed || c->twoPlayer || c->fade != 0) return;
            if (canEnterOrbitMode(c, cur(c))) enterOrbitMode(c);
            else if (c->mode == c->orbitMode) enterChooseMode(c);
            break;
        case BCARSEL_JOY_ORBIT_LEFT:
        case BCARSEL_JOY_ORBIT_RIGHT:
            c->orbitTouched = 1;
            c->orbitFrame   = RealTimeFrames;
            c->orbitSpeedX  = !pressed ? 0.0f
                              : ev == BCARSEL_JOY_ORBIT_LEFT ? -9000.0f
                                                             : 9000.0f;
            break;
        case BCARSEL_JOY_ORBIT_UP:
        case BCARSEL_JOY_ORBIT_DOWN:
            c->orbitTouched = 1;
            c->orbitFrame   = RealTimeFrames;
            c->orbitSpeedY  = !pressed ? 0.0f
                              : ev == BCARSEL_JOY_ORBIT_UP ? 10000.0f
                                                           : -10000.0f;
            break;
        case BCARSEL_JOY_ORBIT_LEFTRIGHT:
            c->orbitTouched = 1;
            c->orbitFrame   = RealTimeFrames;
            c->orbitSpeedX  = ((float)pressed - 128.0f) * 70.3125f;
            break;
        case BCARSEL_JOY_ORBIT_UPDOWN:
            c->orbitTouched = 1;
            c->orbitFrame   = RealTimeFrames;
            c->orbitSpeedY  = ((float)pressed - 128.0f) * -78.125f;
            break;
        default:
            break;
    }
}

// SummonPopup (0x00196bb0): the gearbox, then the handling, then the wait
// for the other player.
static void summonPopup(CarSelector* c)
{
    const BCarSelHooks* h = c->hooks;
    BPopupConfig        cfg;

    memset(&cfg, 0, sizeof(cfg));
    cfg.flags        = BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE;
    cfg.cancelParam  = 0;
    cfg.dismissParam = 6;
    cfg.joyPort      = c->port;
    cfg.timeout      = 0;
    cfg.title        = 0;
    if (c->screen == BCARSEL_SCREEN_1P) cfg.screen = POPUP_SCREEN_1P;
    else if (c->screen == BCARSEL_SCREEN_2P) cfg.screen = POPUP_SCREEN_2P;
    else cfg.screen = POPUP_SCREEN_2P_LO;

    switch (c->state) {
        case 1:
            cfg.numButtons     = 3;
            cfg.button[0]      = LANG_TRANS_AUTO;
            cfg.button[1]      = LANG_TRANS_MANUAL;
            cfg.button[2]      = LANG_TRANS_3;
            cfg.buttonParam[0] = 1;
            cfg.buttonParam[1] = 2;
            cfg.buttonParam[2] = 3;
            cfg.message        = trId(h, LANG_TRANS_MSG);
            cfg.startButton    = c->transmission;
            break;
        case 2:
            cfg.numButtons     = 2;
            cfg.button[0]      = LANG_HANDLING_1;
            cfg.button[1]      = LANG_HANDLING_2;
            cfg.buttonParam[0] = 4;
            cfg.buttonParam[1] = 5;
            cfg.message        = trId(h, LANG_HANDLING_MSG);
            cfg.startButton    = c->handling;
            break;
        case 3:
            cfg.numButtons     = 0;
            cfg.buttonParam[0] = 7;
            cfg.buttonParam[1] = 7;
            cfg.buttonParam[2] = 7;
            cfg.message        = trId(h, LANG_WAITING_MSG);
            cfg.startButton    = 0;
            break;
        default:
            return;
    }
    c->popup = h->summonPopup ? h->summonPopup(h->user, &cfg) : -1;
    trace(h, "carsel popup state %d -> %d", (int)c->state, (int)c->popup);
}

static void dismissPopup(CarSelector* c)
{
    if (c->hooks->dismissPopup)
        c->hooks->dismissPopup(c->hooks->user, c->popup);
}

// AdvanceState (0x00196b78) and DevanceState (0x00196b98).
static void advanceState(CarSelector* c)
{
    if (c->state != 3) c->state++;
    summonPopup(c);
}

static void devanceState(CarSelector* c)
{
    if (c->state != 0) c->state--;
    summonPopup(c);
}

// Tick (0x00196d58).
static void selTick(CarSelector* c)
{
    const BCarSelHooks* h = c->hooks;

    // The car asked for, loaded: shown, if it is still the one chosen.
    if (c->pending && loaderIsLoaded(h, c->pending->type)) {
        c->loaded  = c->pending;
        c->pending = NULL;
        if (c->loaded == cur(c)) {
            updateCarCover(c);
            showLoadedCar(c);
        }
    }
    // Another car chosen, the old one faded out and the row at rest: swap.
    if (c->loaded && c->loaded != cur(c) && c->fade == c->fadeMax
        && c->thumbs.state == 0) {
        c->pending = cur(c);
        loaderUnload(h, c->loaded->type);
        c->loaded = NULL;
        loaderLoad(h, c->pending->type);
        loaderBeginLoading(h);
        trace(h, "carsel load %s", cti(c->pending->type)->CarTypeName);
    }
    if (c->loaded == cur(c)) {
        if (c->fade == c->fadeMax) showLoadedCar(c);
        updateCarCover(c);
        c->fade -= 3;
        if (c->fade < 0) c->fade = 0;
    } else {
        c->fade += 7;
        if (c->fadeMax < c->fade) {
            c->fade = c->fadeMax;
            updateCarCover(c);
        }
    }
    flailer_set_alpha(c->screen, OBJ_BLACK, c->fade);

    if (c->shownMode == c->orbitMode
        && RealTimeFrames - c->orbitFrame > ORBIT_TIMEOUT) {
        c->mode = c->chooseMode;
        adjustHelp(c);
        if (soundEnabled(h)) speechFade(h, 1.0f);
    }
    if (c->shownMode == c->chooseMode || !c->orbitTouched)
        c->turnAngle = (uint16_t)(c->turnAngle + TURN_STEP);

    if (c->shownMode < c->mode) {
        c->shownMode += MODE_STEP;
        if (c->shownMode > c->mode) c->shownMode = c->mode;
    }
    if (c->mode < c->shownMode) {
        c->shownMode -= MODE_STEP;
        if (c->shownMode < c->mode) c->shownMode = c->mode;
    }
    updateFadeGroups(c);
    unlockTick(&c->unlock);
    flailer_set_visibility(c->screen, OBJ_NEXT_ARROW,
                           !(bcarsel_next_car(&c->set, cur(c)) == cur(c)
                             && c->thumbs.state == 0));
    flailer_set_visibility(c->screen, OBJ_PREV_ARROW,
                           !(bcarsel_prev_car(&c->set, cur(c)) == cur(c)
                             && c->thumbs.state == 0));
    updateSwatches(c);
    updateThumbnails(c);
}

// The constructor (0x001950d0).
static void selInit(CarSelector* c, const BCarSelHooks* h, int32_t port,
                    int twoPlayer, int32_t playerNum, uint32_t screen,
                    const VisibleCarSet* set, int32_t points)
{
    memset(c, 0, sizeof(*c));
    c->hooks = h;
    bcarsel_set_copy(&c->set, set);
    c->twoPlayer    = twoPlayer;
    c->playerNum    = playerNum;
    c->screen       = screen;
    c->port         = port;
    c->chooseMode   = 0.0f;
    c->orbitMode    = 1.0f;
    c->shownMode    = 0.0f;
    c->mode         = 0.0f;
    c->state        = 0;
    c->transmission = 0;
    c->handling     = 0;
    c->allUnlocked  = 0;
    c->fadeMax      = 130;
    c->popup        = -1;
    fadeInit(&c->fadeA, screen, OBJ_FADE_A);
    fadeInit(&c->fadeB, screen, OBJ_FADE_B);
    fadeInit(&c->fadeC, screen, OBJ_FADE_C);
    memset(&c->thumbs, 0, sizeof(c->thumbs));
    c->thumbs.arrivalThreshold = 1.0f;
    c->thumbs.duration         = 1.0f;
    c->thumbs.flags            = 1;
    unlockInit(&c->unlock, screen);
    // 0x00196660, the turntable's start.
    c->turnTilt  = 15712;
    c->turnFOV   = 7236;
    c->turnAngle = 16123;

    c->loaded  = NULL;
    c->pending = cur(c);
    loaderLoad(h, c->pending->type);
    loaderBeginLoading(h);
    unlockSetCar(c, cur(c), c->port == 1);
    updateCarCover(c);
    updateLogo(c);
    updateInfoBar(c);
    adjustHelp(c);
    c->nSwatches = 0;
    setupSwatches(c);
    c->fade = c->fadeMax;
    setupThumbnails(c);
    updateFadeGroups(c);
    flailer_printf(screen, OBJ_POINTS, "%s %d", trId(h, LANG_NFS_POINTS),
                   (int)points);
    selTick(c);
    trace(h, "carsel player %d on %08lx: %d cars, %d unlocked, %s",
          (int)playerNum, (unsigned long)screen, (int)c->set.total,
          (int)c->set.unlocked, cti(cur(c)->type)->CarTypeName);
}

// The destructor (0x001957d0).
static void selDestroy(CarSelector* c)
{
    const BCarSelHooks* h = c->hooks;

    dismissPopup(c);
    closeSwatches(c);
    bcarsel_preload();
    bcarsel_preload();
    if (c->loaded) loaderUnload(h, c->loaded->type);
    if (c->pending) loaderUnload(h, c->pending->type);
    if (h->stopSound) h->stopSound(h->user, 12);
    slideRestore(&c->unlock.slide);
    fadeRestore(&c->fadeC);
    fadeRestore(&c->fadeB);
    fadeRestore(&c->fadeA);
}

static int maybeContinue(void);

// ScreenCallback (0x00197390).
static void selCallback(CarSelector* c, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    const BCarSelHooks* h = c->hooks;
    VisibleCar*         car;
    int                 ok = 0;

    if (unlockCallback(&c->unlock, msg, data)) return;
    switch (msg) {
        case BMSG_MENUITEM_SELECT:
            if (c->mode == c->orbitMode) {
                data->noise = 0;
                return;
            }
            if (data->itemHash != BCARSEL_ITEM_CHOOSE) return;
            if (c->state != 0) return;
            if (cur(c)->available || c->allUnlocked) advanceState(c);
            break;

        case BMSG_MENUITEM_PAD_LEFT:
        case BMSG_MENUITEM_PAD_RIGHT: {
            float target;
            if (c->shownMode != c->chooseMode) return;
            car = msg == BMSG_MENUITEM_PAD_RIGHT
                      ? bcarsel_next_car(&c->set, cur(c))
                      : bcarsel_prev_car(&c->set, cur(c));
            unlockSetCar(c, car, c->port == 1);
            if (car == cur(c)) return;
            if (c->fade != c->fadeMax)
                sound(h, msg == BMSG_MENUITEM_PAD_LEFT ? 13 : 12);
            c->set.current = car;
            target = thumbsTarget(c, car);
            splineAim(&c->thumbs, target);
            updateLogo(c);
            updateInfoBar(c);
            setupSwatches(c);
            trace(h, "carsel car %s", cti(car->type)->CarTypeName);
            break;
        }

        case BMSG_MENUITEM_PAD_UP:
        case BMSG_MENUITEM_PAD_DOWN:
            if (c->shownMode == c->chooseMode && c->nSwatches >= 2
                && (cur(c)->available || c->allUnlocked)) {
                if (msg == BMSG_MENUITEM_PAD_UP) carPrevSkin(cur(c));
                else carNextSkin(cur(c));
                sound(h, 14);
                if (c->loaded == cur(c)) showLoadedCar(c);
            }
            data->param = 1;
            break;

        case BMSG_SCREEN_BACK_BUTTON:
            if (c->mode == c->orbitMode) {
                data->param = 0;
                enterChooseMode(c);
                data->noise = 0;
            }
            break;

        case BMSG_SCREEN_TICK:
            selTick(c);
            break;

        case BMSG_SCREEN_RENDER:
            unlockRender(c);
            break;

        case BMSG_POPUP_DISMISS:
            c->popup = -1;
            switch (data->param) {
                case 0: devanceState(c); break;
                case 1: c->transmission = 0; ok = 1; break;
                case 2: c->transmission = 1; ok = 1; break;
                case 3: c->transmission = 2; ok = 1; break;
                case 4: c->handling = 0; ok = 1; break;
                case 5: c->handling = 1; ok = 1; break;
                case 7: ok = 1; break;
                default: break;
            }
            if (ok) {
                if (maybeContinue()) data->noise = 18;
                else advanceState(c);
            }
            break;

        default:
            break;
    }
}

// ------------------------------------------------- SelectCarScreen

static SelectCarScreen s_screen;
static CarSelector     s_selectors[BCARSEL_MAX_SELECTORS];

// Which selector a message belongs to: the pad's, with two players.
static int selectorIndex(const BScreenCallbackData* data)
{
    return Fred.NumPlayerCars == 2 ? data->port != 0 : 0;
}

// The constructor (0x00198420).
static SelectCarScreen* screenNew(void)
{
    const BCarSelHooks* h = &g_m->hooks;
    memset(&s_screen, 0, sizeof(s_screen));
    if (h->loaderFrontEnd) h->loaderFrontEnd(h->user);
    if (h->stopMovie) h->stopMovie(h->user);
    return &s_screen;
}

// ActivateCarSelector (0x00198518).
static void screenActivate(SelectCarScreen* p, BScreenCallbackData* data)
{
    const BCarSelHooks*  h = &g_m->hooks;
    static VisibleCarSet set;
    FrontendPlayerInfo*  player;
    int                  idx = 0;

    if (Fred.NumPlayerCars == 2) {
        if (data->port == -1) return;
        idx = data->port != 0;
    }
    player = &Fred.FrontendPlayers[idx];
    bcarsel_set_init(&set, h, player,
                     idx == 0 && Fred.GameType == GAME_TYPE_BE_A_COP);
    if (!set.current) return;
    selInit(&s_selectors[idx], h, data->port, Fred.NumPlayerCars == 2,
            idx ? 2 : 1, data->itemHash, &set, player->AccumulatedPoints);
    p->selectors[idx] = &s_selectors[idx];
    p->count++;
}

// DeactivateCarSelector (0x00198640).
static void screenDeactivate(SelectCarScreen* p, BScreenCallbackData* data)
{
    int idx = 0;
    if (Fred.NumPlayerCars == 2) {
        if (data->port == -1) return;
        idx = data->port != 0;
    }
    if (!p->selectors[idx]) return;
    selDestroy(p->selectors[idx]);
    p->selectors[idx] = NULL;
    p->count--;
}

// SetSelectedCars (0x001986c8): each player's car, skin, gearbox and
// handling into Fred.
static void screenSetSelectedCars(SelectCarScreen* p)
{
    int32_t i;
    for (i = 0; i < Fred.NumPlayerCars && i < BCARSEL_MAX_SELECTORS; i++) {
        CarSelector*        c = p->selectors[i];
        FrontendPlayerInfo* player;
        VisibleCar*         car;
        if (!c) continue;
        player = &Fred.FrontendPlayers[i];
        car    = cur(c);
        fpi_assign_car_of_type(player, Fred.GameType, car->type,
                               (uint32_t)skinAt(car->status, car->skinIndex),
                               1);
        if (c->transmission == 0) player->mPlayerSettings.TransmissionType = 0;
        else if (c->transmission == 1)
            player->mPlayerSettings.TransmissionType = 1;
        else if (c->transmission == 2)
            player->mPlayerSettings.TransmissionType = 2;
        if (c->handling == 0) player->mPlayerSettings.DrivingStyle = 0;
        else if (c->handling == 1) player->mPlayerSettings.DrivingStyle = 1;
    }
}

static void screenDismissAll(SelectCarScreen* p)
{
    int i;
    for (i = 0; i < BCARSEL_MAX_SELECTORS; i++)
        if (p->selectors[i]) dismissPopup(p->selectors[i]);
}

// AreAllSelectorsReady (0x00198878): one player done at the handling, two
// at the wait.
static int screenAllReady(SelectCarScreen* p)
{
    int i;
    for (i = 0; i < BCARSEL_MAX_SELECTORS; i++) {
        CarSelector* c = p->selectors[i];
        if (c && c->state != (c->twoPlayer ? 3 : 2)) return 0;
    }
    return 1;
}

// MaybeContinueToNextScreen (0x00198b00).
static int maybeContinue(void)
{
    const BCarSelHooks* h = &g_m->hooks;
    SelectCarScreen*    p = g_m->screen;

    if (!p || !screenAllReady(p)) return 0;
    screenSetSelectedCars(p);
    screenDismissAll(p);
    if (Fred.GameType == 8 || Fred.GameType == 9) {
        trace(h, "carsel start race");
        if (h->startRace) h->startRace(h->user);
        return 1;
    }
    trace(h, "carsel on to Select Track");
    if (h->changeToScreen) h->changeToScreen(h->user, "Select Track", 1);
    return 1;
}

void bcarsel_screen_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data)
{
    const BCarSelHooks* h;
    SelectCarScreen*    p;
    (void)gf;

    if (!g_m) return;
    h = &g_m->hooks;
    p = g_m->screen;

    // SelectCarScreen::ScreenCallback (0x001988d8) first.
    if (p) {
        int idx = selectorIndex(data);
        if (p->selectors[idx]) selCallback(p->selectors[idx], msg, data);
    }

    switch (msg) {
        case BMSG_SCREEN_ACTIVATE:
            if (!g_m->screen) g_m->screen = screenNew();
            screenActivate(g_m->screen, data);
            if (Fred.NumPlayerCars == 2 && h->setPerPortJoy)
                h->setPerPortJoy(h->user, 1);
            break;
        case BMSG_SCREEN_UNACTIVATE:
            if (!p) break;
            setHelp(h, NULL);
            screenDeactivate(p, data);
            if (p->count == 0) {
                int i;
                for (i = 0; i < BCARSEL_MAX_SELECTORS; i++) {
                    if (!p->selectors[i]) continue;
                    selDestroy(p->selectors[i]);
                    p->selectors[i] = NULL;
                }
                g_m->screen = NULL;
            }
            if (soundEnabled(h)) speechFade(h, 0.2f);
            if (Fred.NumPlayerCars == 2 && h->setPerPortJoy)
                h->setPerPortJoy(h->user, 0);
            break;
        case BMSG_SCREEN_BACK_BUTTON:
            if (p) screenSetSelectedCars(p);
            break;
        default:
            break;
    }
}

void bcarsel_joy(int port, int32_t event, uint8_t pressed)
{
    int i;
    if (!g_m || !g_m->screen) return;
    for (i = 0; i < BCARSEL_MAX_SELECTORS; i++) {
        CarSelector* c = g_m->screen->selectors[i];
        if (!c) continue;
        // One player listens to both pads; two, each to its own.
        if (c->twoPlayer && c->port != port) continue;
        selJoy(c, event, pressed);
    }
}

int bcarsel_active(void)
{
    return g_m && g_m->screen != NULL;
}

void bcarsel_init(BCarSel* m, const BCarSelHooks* hooks)
{
    memset(m, 0, sizeof(*m));
    if (hooks) m->hooks = *hooks;
    m->screen       = NULL;
    m->preloaded[0] = -1;
    m->preloaded[1] = -1;
    g_m = m;
}
