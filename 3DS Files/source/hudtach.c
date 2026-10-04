// hudtach -- see hudtach.h.

#include "hudtach.h"

#include <string.h>

#include "eefpu.h"

// The four points of each quarter, by row (0x002f09e0): the centre, then
// three round the edge. Rows 4 to 27, the data after the table, are
// zeros, and row 28 holds pointers, which a Rotation of -2160 or below
// reaches. Every row from 4 on is zeros here.
static const int32_t kQuarters[4][4] = {
    { 0, 7, 8, 1 },
    { 0, 5, 6, 7 },
    { 0, 3, 4, 5 },
    { 0, 1, 2, 3 },
};
static const int32_t kNoQuarter[4] = { 0, 0, 0, 0 };

// gp-31488: 1/45, a quarter's half in degrees.
#define ONE_OVER_45 0x1.6c16c2p-6f

// The lists the word at 108 names, a slot each. A new list takes the next
// slot round, so the last HUDTACH_MAX_LISTS stay good.
static FlailerTachometerPointList *sLists[HUDTACH_MAX_LISTS];
static int sNextList;

static uint32_t token_of(FlailerTachometerPointList *l)
{
    int i;

    for (i = 0; i < HUDTACH_MAX_LISTS; i++)
        if (sLists[i] == l) return (uint32_t)i + 1;
    i = sNextList;
    sNextList = (sNextList + 1) % HUDTACH_MAX_LISTS;
    sLists[i] = l;
    return (uint32_t)i + 1;
}

FlailerTachometerPointList *hudtach_points(const struct FlailerBitmapChunk *b)
{
    uint32_t t = b->pTachPointList;

    if (t == 0 || t > HUDTACH_MAX_LISTS) return NULL;
    return sLists[t - 1];
}

uint32_t next_power_of_2(uint32_t n)
{
    uint32_t v = 2;

    if (n == 0) return 0;
    for (n = (n - 1) >> 1; n != 0; n >>= 1)
        v <<= 1;
    return v;
}

static void set_point(FlailerTachometerPoint *p, float x, float y, float z,
                      float u, float v)
{
    p->x = x;
    p->y = y;
    p->z = z;
    p->u = u;
    p->v = v;
}

void flailer_initialize_tachometer(struct FlailerObjectChunk *needle,
                                   struct FlailerObjectChunk *gradient,
                                   void *points)
{
    struct FlailerBitmapChunk *b = (struct FlailerBitmapChunk *)gradient;
    FlailerTachometerPointList *l = (FlailerTachometerPointList *)points;
    struct FlailerObjectChunk  *o = &b->Object;
    int32_t  w, h, sw, sh;
    uint32_t pw, ph;
    float    umax, vmax, uhalf, vhalf, cx, cy, right, bottom, z;

    (void)needle;
    if (gFlailerBitmapTextureSizeFn == NULL
        || !gFlailerBitmapTextureSizeFn(b, &w, &h))
        return;
    pw = next_power_of_2((uint32_t)w);
    ph = next_power_of_2((uint32_t)h);
    // The size is unsigned to the PS2, and so are its conversions.
    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX);
    sh = ee_trunc_w((float)(uint32_t)h * o->ScaleY);
    umax = ee_div((float)(uint32_t)w, (float)pw);
    vmax = ee_div((float)(uint32_t)h, (float)ph);

    cx     = o->X + (float)(sw / 2);
    cy     = o->Y + (float)(sh / 2);
    right  = o->X + (float)sw;
    bottom = o->Y + (float)sh;
    uhalf  = 0.0f + umax * 0.5f;
    vhalf  = 0.0f + vmax * 0.5f;
    umax   = 0.0f + umax;
    vmax   = 0.0f + vmax;
    z      = (float)o->Z;

    b->pTachPointList = token_of(l);
    set_point(&l->Points[0], cx,    cy,     z, uhalf, vhalf);
    set_point(&l->Points[1], cx,    bottom, z, uhalf, vmax);
    set_point(&l->Points[2], o->X,  bottom, z, 0.0f,  vmax);
    set_point(&l->Points[3], o->X,  cy,     z, 0.0f,  vhalf);
    set_point(&l->Points[4], o->X,  o->Y,   z, 0.0f,  0.0f);
    set_point(&l->Points[5], cx,    o->Y,   z, uhalf, 0.0f);
    set_point(&l->Points[6], right, o->Y,   z, umax,  0.0f);
    set_point(&l->Points[7], right, cy,     z, umax,  vhalf);
    set_point(&l->Points[8], right, bottom, z, umax,  vmax);
}

static const int32_t *quarter(int32_t i)
{
    return i >= 0 && i < 4 ? kQuarters[i] : kNoQuarter;
}

static void set_corner(ePoly *p, int c, const FlailerTachometerPoint *pt)
{
    p->UVs[c][0]     = pt->u;
    p->UVs[c][1]     = pt->v;
    p->Vertices[c].x = pt->x;
    p->Vertices[c].y = pt->y;
}

// The Flailer's ALPHA_1, gp-22356 to -22351: (Cs - Cd) * As + Cd, on.
static void set_alpha(ePoly *p)
{
    p->AlphaEnabled = 1;
    p->AlphaA       = EPOLY_ALPHA_CS;
    p->AlphaB       = EPOLY_ALPHA_CD;
    p->AlphaC       = 0;            // As
    p->AlphaD       = EPOLY_ALPHA_CD;
    p->AlphaFix     = 0x80;
}

void flailer_render_tachometer(const struct FlailerBitmapChunk *b,
                               const FlailerTachometerPointList *list,
                               ePoly *(*add_poly)(void *ctx), void *ctx)
{
    const FlailerTachometerPoint *pa, *pb;
    const int32_t *row;
    ePoly  *p;
    int32_t a, q, s = 2, i, c;
    float   r, t, z;

    // The quarters before the needle's, and how far into its own.
    a = ee_trunc_w(360.0f - (float)b->Object.Rotation);
    q = a / 90;
    r = (float)(a % 90);
    if (45.0f < r) {
        r = r - 45.0f;
        s = 1;
    }
    t = 1.0f - r * ONE_OVER_45;
    if (list == NULL) return;

    for (i = 1; i < q; i++) {
        p = add_poly(ctx);
        if (p == NULL) return;
        row = quarter(i);
        for (c = 0; c < 4; c++)
            set_corner(p, c, &list->Points[row[c]]);
        z = (float)b->Object.Z;
        for (c = 0; c < 4; c++)
            p->Vertices[c].z = z;
        set_alpha(p);
        memcpy(p->Colours, b->Colors, sizeof p->Colours);
        p->Flailer = 1;
    }

    // The cut: corner 1 between corners s and s + 1, and on from s + 1.
    // With s 2, corner 2 keeps the constructor's.
    p = add_poly(ctx);
    if (p == NULL) return;
    row = quarter(i);
    set_corner(p, 0, &list->Points[row[0]]);
    pa = &list->Points[row[s]];
    pb = &list->Points[row[s + 1]];
    p->UVs[1][0]     = pa->u + t * (pb->u - pa->u);
    p->UVs[1][1]     = pa->v + t * (pb->v - pa->v);
    p->Vertices[1].x = pa->x + t * (pb->x - pa->x);
    p->Vertices[1].y = pa->y + t * (pb->y - pa->y);
    for (c = s + 1; c < 4; c++)
        set_corner(p, c, &list->Points[row[c]]);
    set_alpha(p);
    z = (float)b->Object.Z;
    for (c = 0; c < 4; c++)
        p->Vertices[c].z = z;
    memset(p->Colours, 0x80, sizeof p->Colours);
    p->Flailer = 1;
}
