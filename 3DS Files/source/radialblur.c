// radialblur -- see radialblur.h.

#include "radialblur.h"

#include <stddef.h>
#include <string.h>

#include "eefpu.h"
#include "esolid.h"
#include "race.h"
#include "racecoord.h"
#include "replayscreen.h"

uint8_t RadialBlurFromAlpha[2];
uint8_t RadialBlurToAlpha[2];

// 0x0010f128's edge alpha.
#define BLUR_TO_ALPHA 160

// DisplayBlendPrevious's UVs are over 512 (lui 0x3b00, 2^-9).
#define BLUR_TEXEL (1.0f / 512.0f)

eView *radialblur_player_view(int32_t player)
{
    RaceCoordinator *rc = pRaceCoordinator;

    if (rc != NULL && rc->CurrentRCState == RCSTATE_INSTANT_REPLAY
        && rc->pReplayScreen != NULL) {
        if (((ReplayScreen *)rc->pReplayScreen)->PlayerNumber != player)
            return NULL;
        return eGetView(EVIEW_ID_PLAYER1);
    }
    return eGetView(player + 1);
}

// Retail indexes the two bytes by the view's ID less 1 unchecked; the
// player views are 1 and 2.
void radialblur_view_on(eView *view)
{
    uint32_t i;

    if (pRaceCoordinator != NULL
        && pRaceCoordinator->CurrentRCState == RCSTATE_POSTRACE)
        return;
    view->pBlendMask = pTextureInfoRadialBlur;
    i = (uint32_t)(view->ID - 1);
    if (i < 2u) {
        RadialBlurToAlpha[i]   = BLUR_TO_ALPHA;
        RadialBlurFromAlpha[i] = 0;
    }
}

void radialblur_view_off(eView *view)
{
    view->pBlendMask = NULL;
}

void radialblur_on(int32_t player)
{
    eView *view = radialblur_player_view(player);

    if (view != NULL)
        radialblur_view_on(view);
}

void radialblur_off(int32_t player)
{
    eView *view = radialblur_player_view(player);

    if (view != NULL)
        radialblur_view_off(view);
}

void radialblur_on_off_view(int32_t on, eView *view)
{
    if (on)
        radialblur_view_on(view);
    else
        radialblur_view_off(view);
}

// cvt.w.s of each times 255, stored as a byte.
void radialblur_alpha(int32_t player, float from, float to)
{
    if ((uint32_t)player >= 2u)
        return;
    RadialBlurFromAlpha[player] = (uint8_t)ee_trunc_w(ee_mul(from, 255.0f));
    RadialBlurToAlpha[player]   = (uint8_t)ee_trunc_w(ee_mul(to, 255.0f));
}

void radialblur_replay(int32_t on)
{
    radialblur_on_off_view(on, eGetView(EVIEW_ID_PLAYER1));
}

// One poly on the stack, changed between draws: each quarter keeps what
// the one before set but for the corner it moves. V2 is the middle each
// time, and the UVs stay the constructor's, so the middle is the
// texture's (1, 1).
int radialblur_mask_polys(const eView *view, ePoly polys[4])
{
    const eRenderTarget *rt;
    ePoly                p;
    int32_t              k, x0, y0, x1, y1, cx, cy;
    uint8_t              from, to;
    float                z;

    if (view->pBlendMask == NULL)
        return 0;
    if (view->ID == EVIEW_ID_PLAYER1)
        k = 0;
    else if (view->ID == EVIEW_ID_PLAYER1 + 1)
        k = 1;
    else
        return 0;
    rt = view->pRenderTarget0;
    if (rt == NULL || rt->Active == 0)
        return 0;

    memset(&p, 0, sizeof p);
    epoly_init(&p);
    z                  = rt->MaxZ;
    p.AlphaD           = EPOLY_ALPHA_CD;
    p.ApplyAspectRatio = 0;
    p.SunPoly          = 1;
    p.AlphaA           = EPOLY_ALPHA_CS;
    p.AlphaB           = EPOLY_ALPHA_CS;
    p.AlphaC           = EPOLY_ALPHA_AS;
    to   = RadialBlurToAlpha[k];
    from = RadialBlurFromAlpha[k];
    x0   = rt->ScissorX;
    y0   = rt->ScissorY;
    x1   = x0 + rt->ScissorW;
    y1   = y0 + rt->ScissorH;
    cx   = x0 + rt->ScissorW / 2;
    cy   = y0 + rt->ScissorH / 2;

    p.Vertices[0].z = z;
    p.Vertices[1].z = z;
    p.Vertices[2].z = z;
    p.Vertices[3].z = z;
    p.Colours[2][3] = from;
    p.Colours[0][3] = to;
    p.Colours[1][3] = to;
    p.Colours[3][3] = to;
    p.Vertices[0].x = (float)x0;
    p.Vertices[0].y = (float)y0;
    p.Vertices[3].x = (float)x0;
    p.Vertices[3].y = (float)cy;

    // The top left; the top right; the bottom right; the bottom left.
    p.Vertices[1].y = (float)y0;
    p.Vertices[2].x = (float)cx;
    p.Vertices[2].y = (float)cy;
    p.Vertices[1].x = (float)cx;
    polys[0] = p;
    p.Vertices[3].x = (float)x1;
    p.Vertices[0].x = (float)x1;
    polys[1] = p;
    p.Vertices[0].y = (float)y1;
    p.Vertices[1].y = (float)y1;
    polys[2] = p;
    p.Vertices[0].x = (float)x0;
    p.Vertices[3].x = (float)x0;
    polys[3] = p;
    return 4;
}

// Retail first sets the render target's TextureInfo semitransparent, so
// Render blends it; the 3DS's picture of the last frame has none.
bool radialblur_previous_poly(const eView *view, ePoly *poly)
{
    const eRenderTarget *rt;
    float                x0, y0, w, h, z, u0, v0, u1, v1;

    if (!view->Active || view->pBlendMask == NULL)
        return false;
    rt = view->pRenderTarget0;
    if (rt == NULL || rt->Active == 0)
        return false;

    memset(poly, 0, sizeof *poly);
    epoly_init(poly);
    z = rt->MaxZ;
    poly->AlphaD           = EPOLY_ALPHA_CD;
    poly->ApplyAspectRatio = 0;
    poly->SunPoly          = 1;
    poly->AlphaA           = EPOLY_ALPHA_CS;
    poly->AlphaB           = EPOLY_ALPHA_CD;
    poly->AlphaC           = EPOLY_ALPHA_AD;

    x0 = (float)rt->ScissorX;
    y0 = (float)rt->ScissorY;
    w  = (float)rt->ScissorW;
    h  = (float)rt->ScissorH;
    u0 = ee_mul(x0 + 0.5f, BLUR_TEXEL);
    v0 = ee_mul(y0 + 0.5f, BLUR_TEXEL);
    u1 = ee_mul(w - 0.5f, BLUR_TEXEL);
    v1 = ee_mul(h - 0.5f, BLUR_TEXEL);

    poly->Vertices[0].x = x0;
    poly->Vertices[0].y = y0;
    poly->Vertices[1].x = (float)(rt->ScissorX + rt->ScissorW);
    poly->Vertices[1].y = y0;
    poly->Vertices[2].x = (float)(rt->ScissorX + rt->ScissorW);
    poly->Vertices[2].y = (float)(rt->ScissorY + rt->ScissorH);
    poly->Vertices[3].x = x0;
    poly->Vertices[3].y = (float)(rt->ScissorY + rt->ScissorH);
    poly->Vertices[0].z = z;
    poly->Vertices[1].z = z;
    poly->Vertices[2].z = z;
    poly->Vertices[3].z = z;
    poly->UVs[0][0] = u0;
    poly->UVs[0][1] = v0;
    poly->UVs[1][0] = u1;
    poly->UVs[1][1] = v0;
    poly->UVs[2][0] = u1;
    poly->UVs[2][1] = v1;
    poly->UVs[3][0] = u0;
    poly->UVs[3][1] = v1;
    return true;
}
