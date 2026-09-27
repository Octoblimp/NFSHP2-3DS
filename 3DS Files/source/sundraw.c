// sundraw -- see sundraw.h.

#include "sundraw.h"

#include "bmath.h"
#include "camera.h"
#include "eefpu.h"
#include "emath.h"
#include "epoly.h"
#include "realtime.h"

SunZBuffer SunZBuffers[NUM_SUN_ZBUFFERS];   // 0x002dfe00

float   SunPosX;                            // gp-24140
float   SunPosY;                            // gp-24136
float   GlareDist = 1.0f;                   // gp-24132
int32_t bStartGlare;                        // gp-24128
int32_t bResetGlare;                        // gp-24124
float   GlareStartTime;                     // gp-24120
int32_t iGlarePhase;                        // gp-24116

float PhaseTimes[NUM_GLARE_PHASES] = {      // 0x00290e50
    0.05f, 0.2f, 0.65f, 5.0f
};

void (*gETransferZBufferRectFn)(uint8_t *dst, int x, int y, int w, int h);

// WorldTimer's ticks in seconds, gp-32212 and gp-32208: one for the start
// and one for now.
#define GLARE_START_SECONDS 0.00025f
#define GLARE_NOW_SECONDS   0.00025f

// gp-32204: the glare's largest size, over the layers'.
#define GLARE_SIZE 1.9f

// The screen is 4096 pixels across, with the render target at the middle.
#define SCREEN_OFFSET 2048.0f

// A pixel counts as open sky with a Z under this.
#define SKY_Z 64

// The sun's position as the render target's pixels in *sx and *sy, or
// SunPosX and SunPosY when either is not 0. 0 when it is behind the view.
static int project(eView *view, const bVector4 *pos, float halfW,
                   float halfH, float *sx, float *sy)
{
    bVector4 screen, eye;

    eRotTransPers(&screen, view->WorldScreenMatrix, pos);
    eMulVector4(&eye, view->WorldViewMatrix, pos);
    *sx = (screen.x - SCREEN_OFFSET) + halfW;
    *sy = (screen.y - SCREEN_OFFSET) + halfH;
    if (SunPosX != 0.0f || SunPosY != 0.0f) {
        *sx = SunPosX;
        *sy = SunPosY;
    }
    return !(eye.z < 0.0f);
}

// The largest CENTER layer's Size, and never under 0.
static float largest_center(const SunChunkInfoE *info)
{
    float m = 0.0f;
    int   i;

    for (i = 0; i < SUN_NUM_LAYERS; i++) {
        const SunLayer *l = &info->SunLayers[i];

        if (l->Texture == SUNTEX_CENTER && m < l->Size) {
            m = l->Size;
        }
    }
    return m;
}

// Whether a quad `m` across fits at (sx, sy) on a w by h target.
static int on_target(float sx, float sy, float m, float w, float h)
{
    if (sx < -m || w + m < sx) {
        return 0;
    }
    if (sy < -m || h + m < sy) {
        return 0;
    }
    return 1;
}

// What both draws set up once, after the constructor.
static void begin_poly(ePoly *p)
{
    epoly_init(p);
    p->AlphaEnabled = 1;
    p->AlphaFix     = 64;
    p->UVs[0][0]    = 0.0f;
    p->UVs[0][1]    = 0.0f;
    p->UVs[1][0]    = 1.0f;
    p->UVs[1][1]    = 0.0f;
    p->UVs[2][0]    = 1.0f;
    p->UVs[2][1]    = 1.0f;
    p->UVs[3][0]    = 0.0f;
    p->UVs[3][1]    = 1.0f;
}

// One layer's quad, and its Render. `half` is half the quad across,
// `intensity` its strength, and `fade` what a positive intensity is scaled
// by. `span` is the target's width plus `m`.
static void draw_layer(ePoly *p, const SunLayer *l, TextureInfo *tex,
                       float sx, float sy, float m, float span, float half,
                       float intensity, float fade)
{
    float    frac, s, c, hs, hc, a, b, cx, cy, alpha;
    uint16_t angle;
    uint8_t  ab;
    int      i;

    frac  = (sx + m) / (span + m);
    angle = (uint16_t)((uint16_t)l->Angle
                       + ee_trunc_w(l->SweepAngleAmount * frac * 65536.0f));
    s  = bSinBam(angle);
    c  = bCosBam(angle);
    hc = half * c;
    hs = half * s;
    b  = hc - hs;
    a  = hs + hc;
    if (intensity < 0.0f) {
        alpha = -intensity * 128.0f;
    } else {
        alpha = fade * (intensity * 128.0f);
    }
    ab = (uint8_t)ee_trunc_w(alpha);

    // + 0.0f makes a -0 a +0, as the image's does.
    cx = (sx + 0.0f) + l->OffsetX;
    cy = (sy + 0.0f) + l->OffsetY;
    for (i = 0; i < 4; i++) {
        p->Colours[i][0] = l->Colour[0];
        p->Colours[i][1] = l->Colour[1];
        p->Colours[i][2] = l->Colour[2];
        p->Colours[i][3] = ab;
    }
    p->Vertices[0].x = cx - a;
    p->Vertices[0].y = cy - b;
    p->Vertices[1].x = cx + b;
    p->Vertices[1].y = cy - a;
    p->Vertices[2].x = cx + a;
    p->Vertices[2].y = cy + b;
    p->Vertices[3].x = cx - b;
    p->Vertices[3].y = cy + a;
    p->AlphaA  = EPOLY_ALPHA_CS;
    p->AlphaB  = l->AlphaType == SUNALPHA_BLEND ? EPOLY_ALPHA_CD
                                                : EPOLY_ALPHA_ZERO;
    p->AlphaC  = 0;
    p->AlphaD  = EPOLY_ALPHA_CD;
    p->SunPoly = 1;
    if (gEPolyRenderFn != NULL) {
        gEPolyRenderFn(p, tex, 0);
    }
}

void StuffSunGlare(eView *view)
{
    SunChunkInfoE *info  = SunInfo;
    float          size  = 0.0f;
    float          alpha = 1.0f;
    float          start, now, el, halfW, halfH, w, h, sx, sy, m;
    int32_t        phase;
    eRenderTarget *rt;
    Camera        *cam;
    bVector4       pos;
    ePoly          poly;
    int            i;

    if (bResetGlare) {
        GlareStartTime = 0.0f;
        bStartGlare    = 0;
        bResetGlare    = 0;
    }
    start = GlareStartTime;
    if (bStartGlare) {
        float t = (float)WorldTimer * GLARE_START_SECONDS;

        if (0.0f < t && start == 0.0f) {
            start          = t;
            bStartGlare    = 0;
            GlareStartTime = t;
            iGlarePhase    = 0;
        }
    }
    if (start == 0.0f) {
        return;
    }

    now   = (float)WorldTimer * GLARE_NOW_SECONDS;
    phase = iGlarePhase;
    el    = now - start;
    if (PhaseTimes[phase] < el) {
        el -= PhaseTimes[phase];
        GlareStartTime = now;
        phase = (int32_t)((uint32_t)phase + 1u) % NUM_GLARE_PHASES;
        iGlarePhase = phase;
    }
    switch (phase) {
    case 0:
        alpha = 1.0f;
        size  = el / PhaseTimes[0];
        break;
    case 1:
        alpha = 1.0f;
        size  = 1.0f;
        break;
    case 2:
        size  = 1.0f;
        alpha = 1.0f - el / PhaseTimes[2];
        break;
    case 3:
        alpha          = 0.0f;
        GlareStartTime = 0.0f;
        size           = 0.0f;
        break;
    default:
        break;
    }

    rt    = view->pRenderTarget0;
    cam   = view->pCamera;
    w     = (float)rt->ScissorW;
    h     = (float)rt->ScissorH;
    halfW = (float)(rt->ScissorW >> 1);
    halfH = (float)(rt->ScissorH >> 1);
    pos.x = cam->CurrentKey.Direction.x * GlareDist
          + cam->CurrentKey.Position.x;
    pos.y = cam->CurrentKey.Direction.y * GlareDist
          + cam->CurrentKey.Position.y;
    pos.z = cam->CurrentKey.Direction.z * GlareDist
          + cam->CurrentKey.Position.z;
    pos.w = 1.0f;
    size *= GLARE_SIZE;
    if (!project(view, &pos, halfW, halfH, &sx, &sy)) {
        return;
    }
    // The image reads the layers at SunInfo unchecked, so it reads 28 on
    // with no sun chunk. The port stops.
    if (info == NULL) {
        return;
    }
    m = largest_center(info);
    if (!on_target(sx, sy, m, w, h)) {
        return;
    }

    begin_poly(&poly);
    for (i = 0; i < SUN_NUM_LAYERS; i++) {
        const SunLayer *l   = &info->SunLayers[i];
        TextureInfo    *tex = SunTextures[l->Texture];

        if (tex == NULL || size == 0.0f) {
            continue;
        }
        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f * size,
                   size, alpha);
    }
}

void StuffSun(eView *view)
{
    SunChunkInfoE *info;
    eRenderTarget *rt;
    SunZBuffer    *zb;
    bVector4       pos;
    ePoly          poly;
    float          halfW, halfH, w, h, sx, sy, m, count;
    int32_t        sw, sh, x0, y0, x, y;
    int            i;

    StuffSunGlare(view);
    info = SunInfo;
    if (info == NULL || view->ID != EVIEW_ID_PLAYER1) {
        return;
    }
    pos.x = info->PositionX;
    pos.y = info->PositionY;
    pos.z = info->PositionZ;
    pos.w = 1.0f;
    rt    = view->pRenderTarget0;
    sw    = rt->ScissorW;
    sh    = rt->ScissorH;
    halfW = (float)(sw >> 1);
    halfH = (float)(sh >> 1);
    h     = (float)sh;
    w     = (float)sw;
    zb    = &SunZBuffers[rt->ID];
    if (!project(view, &pos, halfW, halfH, &sx, &sy)) {
        return;
    }
    m = largest_center(info);
    if (!on_target(sx, sy, m, w, h)) {
        return;
    }

    // The last frame's rect.
    count = 0.0f;
    for (y = zb->StartY; y < zb->EndY; y++) {
        for (x = zb->StartX; x < zb->EndX; x++) {
            if (zb->Buffer[y * SUN_ZBUFFER_SIZE + x] < SKY_Z) {
                count += 1.0f;
            }
        }
    }
    count *= 1.0f / 1024.0f;

    begin_poly(&poly);
    for (i = 0; i < SUN_NUM_LAYERS; i++) {
        const SunLayer *l   = &info->SunLayers[i];
        TextureInfo    *tex = SunTextures[l->Texture];

        if (tex == NULL || l->IntensityScale == 0.0f) {
            continue;
        }
        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f,
                   l->IntensityScale, count);
    }

    // This frame's rect, for the next.
    y0 = ee_trunc_w(sy - 16.0f);
    x0 = ee_trunc_w(sx - 16.0f);
    if (gETransferZBufferRectFn != NULL) {
        gETransferZBufferRectFn((uint8_t *)zb, x0, y0, SUN_ZBUFFER_SIZE,
                                SUN_ZBUFFER_SIZE);
    }
    x = (int32_t)((uint32_t)x0 + SUN_ZBUFFER_SIZE);
    y = (int32_t)((uint32_t)y0 + SUN_ZBUFFER_SIZE);
    zb->EndY   = sh < y ? (int32_t)(SUN_ZBUFFER_SIZE - ((uint32_t)y
                                                       - (uint32_t)sh))
                        : SUN_ZBUFFER_SIZE;
    zb->StartX = x0 < 0 ? (int32_t)(0u - (uint32_t)x0) : 0;
    zb->EndX   = sw < x ? (int32_t)(SUN_ZBUFFER_SIZE - ((uint32_t)x
                                                       - (uint32_t)sw))
                        : SUN_ZBUFFER_SIZE;
    zb->StartY = y0 < 0 ? (int32_t)(0u - (uint32_t)y0) : 0;
}
