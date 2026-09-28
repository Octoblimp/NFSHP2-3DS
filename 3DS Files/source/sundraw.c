// sundraw -- see sundraw.h.

#include "sundraw.h"

#include "bmath.h"
#include "camera.h"
#include "eefpu.h"
#include "emath.h"
#include "epoly.h"
#include "realtime.h"

SunZBuffer SunZBuffers[NUM_SUN_ZBUFFERS];   // 0x002e03d0

float   SunPosX;                            // gp-23580
float   SunPosY;                            // gp-23576
float   GlareDist = 1.0f;                   // gp-23572
int32_t bStartGlare;                        // gp-23568
int32_t bResetGlare;                        // gp-23564
Timer   GlareStartTime;                     // gp-23560
int32_t iGlarePhase;                        // gp-23556

float PhaseTimes[NUM_GLARE_PHASES] = {      // 0x002ad128
    0.05f, 0.2f, 0.65f, 5.0f
};

void (*gETransferZBufferRectFn)(uint8_t *dst, int x, int y, int w, int h);

// RealTimer's ticks in seconds, gp-32140 and gp-32136: one for the start
// and one for how long it has run.
#define GLARE_START_SECONDS 0.00025f
#define GLARE_NOW_SECONDS   0.00025f

// gp-32132: the glare's largest size, over the layers'.
#define GLARE_SIZE 1.9f

// The screen is 4096 pixels across, with the render target at the middle.
#define SCREEN_OFFSET 2048.0f

// A pixel counts as open sky with a Z, the word's low 24 bits, under this.
#define SKY_Z 2u
#define Z_MASK 0x00ffffffu

// The z of StuffSun's first layer, which the GS's GEQUAL passes only over
// a Z of 0 or 1: the sky.
#define SKY_ONLY_Z 1.0f

// Timer's two values that mean it is not set, as Car's blink has them.
static int timer_is_set(const Timer *t)
{
    return t->PackedTime != 0 && t->PackedTime != 0x7fffffffu;
}

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

static void set_z(ePoly *p, float z)
{
    p->Vertices[0].z = z;
    p->Vertices[1].z = z;
    p->Vertices[2].z = z;
    p->Vertices[3].z = z;
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
    const SunChunkInfoE *info  = &SunGlareInfo;
    float                size  = 0.0f;
    float                alpha = 1.0f;
    float                el, halfW, halfH, w, h, sx, sy, m, maxz;
    int32_t              now, phase;
    eRenderTarget       *rt;
    Camera              *cam;
    bVector4             pos;
    ePoly                poly;
    int                  i;

    if (bResetGlare) {
        GlareStartTime.PackedTime = 0;
        bStartGlare               = 0;
        bResetGlare               = 0;
    }
    if (bStartGlare && 0.0f < (float)RealTimer * GLARE_START_SECONDS
        && !timer_is_set(&GlareStartTime)) {
        bStartGlare               = 0;
        GlareStartTime.PackedTime = (uint32_t)RealTimer;
        iGlarePhase               = 0;
    }
    if (!timer_is_set(&GlareStartTime)) {
        return;
    }

    now   = RealTimer;
    phase = iGlarePhase;
    el    = (float)(int32_t)((uint32_t)now - GlareStartTime.PackedTime)
          * GLARE_NOW_SECONDS;
    if (PhaseTimes[phase] < el) {
        el -= PhaseTimes[phase];
        GlareStartTime.PackedTime = (uint32_t)now;
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
        alpha                     = 0.0f;
        GlareStartTime.PackedTime = 0;
        size                      = 0.0f;
        break;
    default:
        break;
    }

    rt    = view->pRenderTarget0;
    cam   = view->pCamera;
    maxz  = rt->MaxZ;
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
    m = largest_center(info);
    if (!on_target(sx, sy, m, w, h)) {
        return;
    }

    begin_poly(&poly);
    set_z(&poly, maxz);
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
    float          halfW, halfH, w, h, sx, sy, m, count, maxz;
    int32_t        sw, sh, x0, y0, x, y, startX, endX, startY, endY;
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
    maxz  = rt->MaxZ;
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
            if ((zb->Buffer[y * SUN_ZBUFFER_SIZE + x] & Z_MASK) < SKY_Z) {
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
        set_z(&poly, i == 0 ? SKY_ONLY_Z : maxz);
        draw_layer(&poly, l, tex, sx, sy, m, w + m, l->Size * 0.5f,
                   l->IntensityScale, count);
    }

    // This frame's rect, for the next: 32 by 32 around the sun, moved onto
    // the target at 0 and at 33 short of its size.
    x0     = ee_trunc_w(sx - 16.0f);
    y0     = ee_trunc_w(sy - 16.0f);
    startX = 0;
    startY = 0;
    endX   = SUN_ZBUFFER_SIZE;
    endY   = SUN_ZBUFFER_SIZE;
    if (x0 < 0) {
        endX = (int32_t)((uint32_t)x0 + SUN_ZBUFFER_SIZE);
        x0   = 0;
    }
    if ((int32_t)((uint32_t)sw - 33u) < x0) {
        startX = (int32_t)((uint32_t)x0 + 1u - ((uint32_t)sw - 32u));
        x0     = (int32_t)((uint32_t)sw - 33u);
    }
    if (y0 < 0) {
        endY = (int32_t)((uint32_t)y0 + SUN_ZBUFFER_SIZE);
        y0   = 0;
    }
    if ((int32_t)((uint32_t)sh - 33u) < y0) {
        startY = (int32_t)((uint32_t)y0 + 1u - ((uint32_t)sh - 32u));
        y0     = (int32_t)((uint32_t)sh - 33u);
    }
    zb->EndX   = endX;
    zb->StartY = startY;
    zb->StartX = startX;
    zb->EndY   = endY;
    if (gETransferZBufferRectFn != NULL) {
        gETransferZBufferRectFn((uint8_t *)zb, x0, y0, SUN_ZBUFFER_SIZE,
                                SUN_ZBUFFER_SIZE);
    }
}
