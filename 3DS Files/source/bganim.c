// tGlobalBackgroundAnimation, retail's (bganim.h). Every step is in the
// image's order, which tools/bganim_check.py holds it to.
#include "bganim.h"

#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "flailer.h"

// gp-15004 CrossFadeTime and gp-14996 GridSplineDuration (the demo's 20),
// which nothing in retail writes; gp-15000, SwitchImageTime, 5.0, is read
// by nothing. gp-26476 is the parameter's wrap, gp-26472 RealTimer's tick
// in seconds.
#define CROSS_FADE_TIME      1.0f
#define GRID_SPLINE_DURATION 50.0f
#define ANIM_PARAM_WRAP      6.283f
#define TICK_SECONDS         0.00025f

#define BITMAP(o) ((struct FlailerBitmapChunk*)(void*)(o))

// RandomRange (0x00249570): bRandom(10000) on bDefaultSeed (gp-14472, the
// one-argument bRandom at 0x0025a488), the view's seed in the port.
static float randomRange(float lo, float hi)
{
    return ((float)bRandomI(10000, bViewSeed) * 0.0001f) * (hi - lo) + lo;
}

// FlailerObjectChunk::SetCenter (0x0024aae0), retail's: x, then y.
static void setCenter(struct FlailerObjectChunk* o, float x, float y)
{
    flailerobject_set_center_x(o, x);
    flailerobject_set_center_y(o, y);
}

// Inlined in the constructor and in Reset: both lanes put on their
// desired values, still.
static void snapToDesired(BSpline2D* s)
{
    s->x.state = 0;
    s->x.val   = s->x.valDesired;
    s->y.state = 0;
    s->x.dval  = s->x.dvalDesired;
    s->y.val   = s->y.valDesired;
    s->y.dval  = s->y.dvalDesired;
}

void bganim_init(BgAnim* a)
{
    // Retail's bMalloc'd block leaves the coefficients and the parameter
    // as they were; they are read only after a seek rebuilds them.
    static const bVector2 kCentre = { 320.0f, 240.0f };
    memset(a, 0, sizeof(*a));
    a->spline.x.arrivalThreshold = 1.0f;
    a->spline.y.arrivalThreshold = 1.0f;
    a->spline.x.duration         = GRID_SPLINE_DURATION;
    a->spline.y.duration         = GRID_SPLINE_DURATION;
    bspline2d_set_val_desired(&a->spline, &kCentre);
    snapToDesired(&a->spline);
    a->animParam = 0.0f;
    bganim_keep_reset(a);
}

void bganim_keep_remove(BgAnim* a, uint32_t hash)
{
    for (int i = 0; i < 8; i++)
        if (a->kept[i] == hash) a->kept[i] = 0;
}

void bganim_keep_add(BgAnim* a, uint32_t hash)
{
    bganim_keep_remove(a, hash);
    for (int i = 0; i < 8; i++) {
        if (a->kept[i] == 0) {
            a->kept[i] = hash;
            return;
        }
    }
}

int bganim_keep_count(const BgAnim* a)
{
    int n = 0;
    for (int i = 0; i < 8; i++)
        if (a->kept[i] != 0) n++;
    return n;
}

uint32_t bganim_keep_nth(const BgAnim* a, int n)
{
    for (int i = 0; i < 8; i++) {
        if (a->kept[i] == 0) continue;
        if (n == 0) return a->kept[i];
        n--;
    }
    return 0;
}

void bganim_keep_reset(BgAnim* a)
{
    memset(a->kept, 0, sizeof(a->kept));
    bganim_keep_add(a, bchunk_hash("GRID_BLUEPRINT1"));
    bganim_keep_add(a, bchunk_hash("GRID_BLUEPRINT2"));
}

void bganim_reset(BgAnim* a, int32_t realTimer)
{
    if (a->fading && a->master) {
        // The demo's start was 180..200 across; retail's is 160..165.
        float    x0 = randomRange(160.0f, 165.0f);
        float    y  = randomRange(180.0f, 300.0f);
        float    x1 = randomRange(300.0f, 400.0f);
        bVector2 v;
        flailerbitmap_set_alpha(BITMAP(a->fading), 0, FLAILER_ALL_CORNERS);
        flailerbitmap_set_alpha(BITMAP(a->master), 0, FLAILER_ALL_CORNERS);
        setCenter(a->fading, x0, y);
        v.x = x0;
        v.y = y;
        bspline2d_set_val_desired(&a->spline, &v);
        snapToDesired(&a->spline);
        v.x = x1;
        bspline2d_set_val_desired(&a->spline, &v);
        a->spline.x.duration = GRID_SPLINE_DURATION;
        a->spline.y.duration = GRID_SPLINE_DURATION;
        flailerbitmap_change_texture(
            BITMAP(a->fading),
            bganim_keep_nth(a, bRandomI(bganim_keep_count(a), bViewSeed)));
    }
    a->crossFadeTimer = realTimer;
}

void bganim_change_screen_hash(BgAnim* a, uint32_t screen, int32_t realTimer)
{
    a->screenHash = screen;
    if (screen == 0) {
        a->fading = NULL;
        a->grid   = NULL;
        a->master = NULL;
        return;
    }
    a->grid   = flailer_find_object(screen, bchunk_hash("GRID"),
                                    FLAILER_TYPE_BITMAP);
    a->master = flailer_find_object(screen, bchunk_hash("MASTER_BP_OBJECT"),
                                    FLAILER_TYPE_BITMAP);
    a->fading = flailer_find_object(screen, bchunk_hash("FADING_BP_OBJECT"),
                                    FLAILER_TYPE_BITMAP);
    bganim_reset(a, realTimer);
    a->gridTimer = realTimer;
}

void bganim_tick(BgAnim* a, int32_t realTimer, float realElapsed)
{
    const float last = GRID_SPLINE_DURATION - 1.0f;
    float       p, t;

    a->spline.x.duration = GRID_SPLINE_DURATION;
    a->spline.y.duration = GRID_SPLINE_DURATION;
    p            = a->animParam + realElapsed;
    a->animParam = p;
    if (ANIM_PARAM_WRAP <= p) a->animParam = p - ANIM_PARAM_WRAP;

    if (!a->master || !a->fading) return;

    t = (float)(int32_t)((uint32_t)realTimer - (uint32_t)a->crossFadeTimer)
        * TICK_SECONDS;
    if (t < CROSS_FADE_TIME)
        flailerbitmap_set_alpha(BITMAP(a->fading),
                                (int32_t)(t / CROSS_FADE_TIME * 128.0f),
                                FLAILER_ALL_CORNERS);
    if (t < GRID_SPLINE_DURATION) {
        bVector2 v;
        bspline2d_seek(&a->spline, realElapsed);
        bspline2d_get_val(&a->spline, &v);
        setCenter(a->fading, v.x, v.y);
    }
    // The fade out's 1.0 is a literal, not CrossFadeTime.
    if (last < t && t < GRID_SPLINE_DURATION)
        flailerbitmap_set_alpha(BITMAP(a->fading),
                                (int32_t)((1.0f - (t - last)) * 128.0f),
                                FLAILER_ALL_CORNERS);
    if (GRID_SPLINE_DURATION < t) bganim_reset(a, realTimer);
}
