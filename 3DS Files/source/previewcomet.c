// previewcomet -- zonecameras.cpp's PreviewComet. See previewcomet.h.

#include "previewcomet.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bmatrix.h"
#include "bmem.h"
#include "eefpu.h"
#include "eframe.h"
#include "emath.h"
#include "epoly.h"
#include "texturepack.h"

// new[]'s cookie: the count at the block's start, the array 16 bytes on.
#define COMET_COOKIE 16

// ------------------------------------------------------------ the params
//
// _GLOBAL_$I$ZonePreviewCometParams (0x00167208) clears each to zero and
// then stores what is below; every word it leaves alone is zero here too.
// All four name the effect group "ZONE_PREVIEW". The Zone Preview's comet
// has 32 segments to the driving line's 64, its own texture, no altitude
// where theirs sits 1.25 down, a tail knee at (0.5, 0.47) where theirs is
// at (1, 0.4), and runs from an opaque yellow at its head to a clear red;
// the driving line's three differ only in their colours (green, olive and
// blue). The floats come from gp-30656 .. gp-30596 and lui pairs.

PreviewCometParams ZonePreviewCometParams = {
    "ZONE_PREVIEW", 32, -15.0f, 0x954c4637u, 1.5f, 0.0f, 0.0f, 0.1f,
    5, { { 0.0f, 0.2f }, { 0.05f, 0.7f }, { 0.1f, 1.0f }, { 0.5f, 1.0f },
         { 1.0f, 0.5f } },
    3, { { 0.0f, 0.05f }, { 0.8f, 0.95f }, { 1.0f, 0.95f }, { 0.0f, 0.0f },
         { 0.0f, 0.0f } },
    4, { { 0.0f, -0.04f }, { 0.5f, 0.47f }, { 0.95f, 0.9f }, { 1.0f, 0.95f },
         { 0.0f, 0.0f } },
    { 0, 0, 0 },
    { 240.0f, 200.0f, 20.0f, 255.0f },
    { 180.0f, 40.0f, 0.0f, 0.0f }
};

PreviewCometParams DrivingLineCometParamsEasy = {
    "ZONE_PREVIEW", 64, -15.0f, 0x1fb22c32u, 1.5f, 0.0f, -1.25f, 0.1f,
    5, { { 0.0f, 0.2f }, { 0.05f, 0.7f }, { 0.1f, 1.0f }, { 0.5f, 1.0f },
         { 1.0f, 0.5f } },
    3, { { 0.0f, 0.05f }, { 0.8f, 0.95f }, { 1.0f, 0.95f }, { 0.0f, 0.0f },
         { 0.0f, 0.0f } },
    4, { { 0.0f, -0.04f }, { 1.0f, 0.4f }, { 0.95f, 0.9f }, { 1.0f, 0.95f },
         { 0.0f, 0.0f } },
    { 0, 0, 0 },
    { 50.0f, 160.0f, 0.0f, 255.0f },
    { 20.0f, 40.0f, 0.0f, 0.0f }
};

PreviewCometParams DrivingLineCometParamsMedium = {
    "ZONE_PREVIEW", 64, -15.0f, 0x1fb22c32u, 1.5f, 0.0f, -1.25f, 0.1f,
    5, { { 0.0f, 0.2f }, { 0.05f, 0.7f }, { 0.1f, 1.0f }, { 0.5f, 1.0f },
         { 1.0f, 0.5f } },
    3, { { 0.0f, 0.05f }, { 0.8f, 0.95f }, { 1.0f, 0.95f }, { 0.0f, 0.0f },
         { 0.0f, 0.0f } },
    4, { { 0.0f, -0.04f }, { 1.0f, 0.4f }, { 0.95f, 0.9f }, { 1.0f, 0.95f },
         { 0.0f, 0.0f } },
    { 0, 0, 0 },
    { 130.0f, 130.0f, 0.0f, 255.0f },
    { 80.0f, 80.0f, 0.0f, 0.0f }
};

PreviewCometParams DrivingLineCometParamsHard = {
    "ZONE_PREVIEW", 64, -15.0f, 0x1fb22c32u, 1.5f, 0.0f, -1.25f, 0.1f,
    5, { { 0.0f, 0.2f }, { 0.05f, 0.7f }, { 0.1f, 1.0f }, { 0.5f, 1.0f },
         { 1.0f, 0.5f } },
    3, { { 0.0f, 0.05f }, { 0.8f, 0.95f }, { 1.0f, 0.95f }, { 0.0f, 0.0f },
         { 0.0f, 0.0f } },
    4, { { 0.0f, -0.04f }, { 1.0f, 0.4f }, { 0.95f, 0.9f }, { 1.0f, 0.95f },
         { 0.0f, 0.0f } },
    { 0, 0, 0 },
    { 60.0f, 60.0f, 180.0f, 255.0f },
    { 0.0f, 0.0f, 80.0f, 0.0f }
};

// ------------------------------------------------------------ the comet

void preview_comet_init(PreviewComet *c, Spline *look,
                        PreviewCometParams *params)
{
    AcidEmitterData *d = NULL;
    int32_t          n, i;

    graph_init(&c->Width, params->vPreviewCometWidth,
               params->nPreviewCometWidths);
    graph_init(&c->Head, params->vPreviewCometHead,
               params->nPreviewCometHeads);
    graph_init(&c->Tail, params->vPreviewCometTail,
               params->nPreviewCometTails);
    c->pLookSpline = look;
    c->pParams = params;
    c->pEmitters = NULL;
    c->nEmitters = 0;

    // The group's datas counted, the name hashed again for each.
    while ((d = afx_get_emitter_data(
                0, bchunk_hash(c->pParams->EmitterGroupName), d)) != NULL)
        c->nEmitters++;

    n = c->nEmitters;
    if (n != 0) {
        uint8_t     *block;
        AcidEmitter *e;

        // new AcidEmitter[n]: retail's size is `192 * n | 16`, which is
        // the cookie added, 192 * n having its low six bits clear.
        block = (uint8_t *)bMalloc(COMET_COOKIE
                                   + n * (int32_t)sizeof(AcidEmitter),
                                   "ZonePreview Emitters", 0, 16);
        *(int32_t *)(void *)block = n;
        e = (AcidEmitter *)(void *)(block + COMET_COOKIE);
        // AcidEmitter's constructor, inline: zero from the eighth byte
        // (bMemSet, 184 bytes), and counted. The links are left.
        for (i = 0; i < n; i++) {
            memset(&e[i].NameHash, 0,
                   sizeof e[i] - offsetof(AcidEmitter, NameHash));
            NumAcidEmitters++;
        }
        c->pEmitters = e;

        // The datas again, from the head, each given to the next emitter,
        // which is turned ON whatever SetEmitterData answers. Nothing
        // bounds this walk by the count.
        i = 0;
        d = NULL;
        while ((d = afx_get_emitter_data(
                    0, bchunk_hash(c->pParams->EmitterGroupName), d))
               != NULL) {
            acid_emitter_set_emitter_data(&c->pEmitters[i], d);
            c->pEmitters[i].State = ACID_ON;
            i++;
        }
    }
    c->Enabled = 0;
    preview_comet_enable(c);
    c->pCometTexture = (struct TextureInfo *)GetTextureInfo(
        c->pParams->nPreviewCometTexture, 1, 0);
}

void preview_comet_destroy(PreviewComet *c)
{
    preview_comet_disable(c);
    if (c->pEmitters != NULL) {
        uint8_t     *block = (uint8_t *)(void *)c->pEmitters - COMET_COOKIE;
        AcidEmitter *e = c->pEmitters + *(int32_t *)(void *)block;

        // delete[]: each from the last, by the cookie's count, with
        // flags 0, then the block (__builtin_vec_delete, bFree).
        while (e != c->pEmitters) {
            e--;
            acid_emitter_delete(e, 0);
        }
        bFree(block);
    }
}

void preview_comet_enable(PreviewComet *c)
{
    int32_t i;

    if (c->Enabled != 0)
        return;
    for (i = 0; i < c->nEmitters; i++)
        acid_system_add_auto_emitter(&FrameEffects, &c->pEmitters[i]);
    c->Enabled = 1;
}

void preview_comet_disable(PreviewComet *c)
{
    int32_t i;

    if (c->Enabled == 0)
        return;
    for (i = 0; i < c->nEmitters; i++)
        acid_system_remove_auto_emitter(&FrameEffects, &c->pEmitters[i]);
    c->Enabled = 0;
}

// ------------------------------------------------------------ the drawing

// `vmul.xyz ; vaddy.x ; vaddz.x`: (x*x + y*y) + z*z, left to right.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfA,vfB,vfA`, A cross B, with
// A's w lane kept.
static void cross3(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    o->x = x;
    o->y = y;
    o->z = z;
    o->pad = a->pad;
}

// `vrsqrt Q,vf00w,vf01x ; vaddq.x ; vmulx.xyzw`: all four lanes over the
// length of three. A zero length divides the EE's way, FLT_MAX.
static void normalize4(bVector3 *v)
{
    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));

    v->x = v->x * inv;
    v->y = v->y * inv;
    v->z = v->z * inv;
    v->pad = v->pad * inv;
}

// `vmulx.xyzw`, all four lanes by one.
static void scale4(bVector3 *v, float k)
{
    v->x = v->x * k;
    v->y = v->y * k;
    v->z = v->z * k;
    v->pad = v->pad * k;
}

// Inline in Render: the parameter of the spline's last point. A LOOP's
// lap is NumControlPoints, CLAMP's and EXTRAPOLATE's run NumControlPoints
// less one, and any other type 0.
static float spline_end_param(const Spline *s)
{
    if (s->Type == SPLINE_LOOP)
        return (float)s->NumControlPoints;
    if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)
        return (float)(s->NumControlPoints - 1);
    return 0.0f;
}

void preview_comet_render(PreviewComet *c, struct eView *view, float t)
{
    bMatrix4 *local_world;
    ePoly     poly;
    bVector3  axis, p, side, along, up, pull;
    float     head, tail, step, scroll, base;
    int32_t   i, a, b;

    (void)view;
    // The frame memory's inline, 64 bytes for the matrix Render3D is
    // handed; out of frame memory, nothing is drawn and nothing moves.
    local_world = (bMatrix4 *)eframe_malloc(64);
    if (local_world == NULL)
        return;
    epoly_init(&poly);
    // World up. Retail stores x, y and z on the stack and leaves w, which
    // reaches no output.
    axis.x = 0.0f;
    axis.y = 0.0f;
    axis.z = 1.0f;
    axis.pad = 0.0f;
    a = 0;
    b = 1;
    bIdentity(local_world);
    head = graph_get_value(&c->Head, t);
    tail = graph_get_value(&c->Tail, t);
    step = (tail - head) / (float)c->pParams->nPreviewCometSegments;
    // The texture's scroll, the fraction of t * DV (floor, not trunc).
    scroll = t * c->pParams->fPreviewCometTextureDV;
    base = (float)ee_trunc_w(scroll);
    if (scroll < base)
        base = base - 1.0f;
    scroll = scroll - base;

    // Every other point: the image's counter is i + 1 after the head's
    // frame (0x00161c20, 0x00161cb4) and goes up by one more at the loop's
    // end (0x00161f2c), so a 32-segment comet is 16 quads, each two steps
    // long, and an odd last point is never reached.
    for (i = 0; i <= c->pParams->nPreviewCometSegments; i += 2) {
        const PreviewCometParams *pp;
        const Spline             *s = c->pLookSpline;
        float                     fi, u, k, w, rest, fade, d, v;

        // Point i of the ribbon, from the head's place on the spline to
        // the tail's.
        fi = (float)i;
        u = spline_end_param(s) * (head + step * fi);
        spline_get_point(s, &p, u);
        spline_get_derivative(s, &along, u);
        spline_get_second_derivative(s, &pull, u);
        pp = c->pParams;
        p.z = p.z + pp->fPreviewCometAltitude;

        // The frame: along the spline; sideways, level; up, leaned into
        // the curve by the sideways share of the second derivative; then
        // sideways and up again square to the way along.
        normalize4(&along);
        cross3(&side, &axis, &along);
        normalize4(&side);
        k = pp->fPreviewCometLateralCoeff * dot3(&pull, &side);
        up.x = side.x * k + axis.x;
        up.y = side.y * k + axis.y;
        up.z = side.z * k + axis.z;
        up.pad = side.pad * k + axis.pad;
        cross3(&side, &up, &along);
        normalize4(&side);
        cross3(&up, &along, &side);
        normalize4(&up);

        // The head's frame to each ON emitter until the head's second
        // knee, and then the emitter OFF. eIdentity, then x, y and z of
        // each row: side, up, along and the point.
        if (i == 0) {
            bMatrix4 m;
            int32_t  j;

            eIdentity(&m);
            m.v0.x = side.x;
            m.v0.y = side.y;
            m.v0.z = side.z;
            m.v1.x = up.x;
            m.v1.y = up.y;
            m.v1.z = up.z;
            m.v2.x = along.x;
            m.v2.y = along.y;
            m.v2.z = along.z;
            m.v3.x = p.x;
            m.v3.y = p.y;
            m.v3.z = p.z;
            for (j = 0; j < c->nEmitters; j++) {
                AcidEmitter *e = &c->pEmitters[j];

                if (e->State != ACID_ON)
                    continue;
                if (t < c->pParams->vPreviewCometHead[1].x)
                    e->LocalWorld = m;
                else
                    e->State = ACID_OFF;
            }
        }

        // Its two corners, half the width either side and LineHeight up,
        // at v = scroll + i/n; corners a and b swap with the other pair
        // each step, so the poly is always this point's two and the last's.
        fi = fi / (float)pp->nPreviewCometSegments;
        rest = 1.0f - fi;
        fade = 1.0f;
        w = graph_get_value(&c->Width, fi);
        pp = c->pParams;
        scale4(&side, pp->fPreviewCometLineWidth * (w * 0.5f));
        poly.Vertices[a].x = p.x + side.x;
        poly.Vertices[a].y = p.y + side.y;
        poly.Vertices[a].z = (p.z + side.z) + pp->fPreviewCometLineHeight;
        poly.Vertices[b].x = p.x - side.x;
        poly.Vertices[b].y = p.y - side.y;
        poly.Vertices[b].z = (p.z - side.z) + pp->fPreviewCometLineHeight;
        v = scroll + fi;
        poly.UVs[a][1] = v;
        poly.UVs[b][1] = v;

        // Past the head's second knee the alpha fades to nothing at t = 1.
        d = t - pp->vPreviewCometHead[1].x;
        if (0.0f <= d)
            fade = 1.0f - d / (1.0f - pp->vPreviewCometHead[1].x);

        // Colour0 at the head to Colour1 at the tail, cvt.w.s into bytes.
        poly.Colours[a][0] = (uint8_t)ee_trunc_w(
            rest * pp->vPreviewCometColour0.x + fi * pp->vPreviewCometColour1.x);
        poly.Colours[a][1] = (uint8_t)ee_trunc_w(
            rest * pp->vPreviewCometColour0.y + fi * pp->vPreviewCometColour1.y);
        poly.Colours[a][2] = (uint8_t)ee_trunc_w(
            rest * pp->vPreviewCometColour0.z + fi * pp->vPreviewCometColour1.z);
        poly.Colours[a][3] = (uint8_t)ee_trunc_w(
            fade * (rest * pp->vPreviewCometColour0.w
                    + fi * pp->vPreviewCometColour1.w));
        poly.Colours[b][0] = poly.Colours[a][0];
        poly.Colours[b][1] = poly.Colours[a][1];
        poly.Colours[b][2] = poly.Colours[a][2];
        poly.Colours[b][3] = poly.Colours[a][3];

        // The first point only starts the ribbon.
        if (i > 0 && gEPolyRender3DFn != NULL)
            gEPolyRender3DFn(&poly, (TextureInfo *)c->pCometTexture,
                             local_world, 0);
        a ^= 3;
        b ^= 3;
    }
    // ePoly's destructor (0x00114db8, flags 2) does nothing to a poly on
    // the stack.
}

// ------------------------------------------------------------ spline.c's

void spline_get_second_derivative(const Spline *s, bVector3 *o, float t)
{
    float base = (float)ee_trunc_w(t);
    float u, c0, c1, c2, c3;

    if (t < base)
        base = base - 1.0f;
    u = t - base;
    // In the image's order, each weight halved last.
    c0 = (u * -6.0f + 4.0f) * 0.5f;
    c1 = (u * 18.0f - 10.0f) * 0.5f;
    c2 = (u * -18.0f + 8.0f) * 0.5f;
    c3 = (u * 6.0f - 2.0f) * 0.5f;
    spline_evaluate(s, o, base, c0, c1, c2, c3);
}
