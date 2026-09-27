// efog -- see efog.h.

#include "efog.h"

#include <string.h>

#include "eefpu.h"
#include "weatherman.h"

FogModeInfo FogModeInfos[4] = {
    { 0, 1, 0, 1, 128, { 0, 0, 0 }, 244.0f, 255.0f,
      128.0f, 128.0f, 192.0f, 32.0f },
    { 1, 0, 0, 2, 128, { 0, 0, 0 }, 192.0f, 255.0f,
      128.0f, 128.0f, 128.0f, 192.0f },
    { 0, 1, 0, 1, 128, { 0, 0, 0 }, 0.0f, 255.0f,
      128.0f, 128.0f, 128.0f, 128.0f },
    { 0, 1, 0, 1, 128, { 0, 0, 0 }, 0.0f, 255.0f,
      128.0f, 128.0f, 128.0f, 128.0f },
};

int32_t DrawFog = 1;
int32_t FogMode1;
int32_t FogMode2;
float   FogPower = 4.5999999046325684f;     // 0x40933333
int32_t EnableDepthIntoAlpha = 1;

uint32_t FogPalette[4][256];
uint32_t DepthUpperPalette[256];
uint32_t DepthLowerPalette[256];

void (*gEFogAttachFn)(eView *view, const uint32_t *palette,
                      const FogModeInfo *mode);

// ------------------------------------------------------------ the helpers

float fpow(float x, float y)
{
    union { float f; int32_t i; } u;
    float m = x < 0.01f ? 0.01f : x;
    float k = y * 1065353216.0f;
    float one = (float)0x3f800000;

    u.f = m;
    u.i = ee_trunc_w((float)u.i * y + (one - k));
    return u.f;
}

// Four qwords at a time in the image: of each eight, the second pair of
// two with the third.
void RemapLinearIntoClut8(uint32_t *dst, const uint32_t *src)
{
    int b;

    for (b = 0; b < 256; b += 32) {
        memcpy(dst + b,      src + b,      8 * sizeof *dst);
        memcpy(dst + b + 8,  src + b + 16, 8 * sizeof *dst);
        memcpy(dst + b + 16, src + b + 8,  8 * sizeof *dst);
        memcpy(dst + b + 24, src + b + 24, 8 * sizeof *dst);
    }
}

uint32_t *GetFogPalette(eView *view)
{
    uint32_t n = (uint32_t)(view->ID - 1);

    return n < 4 ? FogPalette[n] : NULL;
}

int32_t efog_view_mode(const eView *view)
{
    return view->ID == 1 ? FogMode1 : FogMode2;
}

// -------------------------------------------------------------- the palette

// The byte of a colour, as the float the palette's sums take.
static float colour_byte(uint32_t c, int shift)
{
    return (float)(c >> shift & 0xffu);
}

void CreateFogPalette(eView *view, uint32_t *palette)
{
    uint32_t      linear[256];
    WeatherQuery *q;
    int32_t       mode;
    float         r, g, b, amount, start;
    int           i;

    if (view == NULL || palette == NULL) {
        return;
    }
    mode   = efog_view_mode(view);
    q      = eview_get_weather_query(view);
    r      = colour_byte(q->FogColour, 0);
    g      = colour_byte(q->FogColour, 8);
    b      = colour_byte(q->FogColour, 16);
    amount = q->Fog * 128.0f;
    start  = q->FogStart;

    if (mode == 1) {
        // The alpha alone, from the amount near to none at 255, read back
        // to front. The divide is made for every entry.
        float span = 255.0f - start;

        for (i = 0; i < 256; i++) {
            float fi = (float)i;
            float t  = (fi - start) / span;
            float v;

            if (fi < start) {
                v = 1.0f;
            } else if (255.0f < fi) {
                v = 0.0f;
            } else {
                v = 1.0f - t;
            }
            linear[255 - i] = (uint32_t)ee_trunc_w(v * amount) << 24;
        }
    } else if (mode == 2) {
        // A grey ramp at half alpha, by the depth: a view of the Z.
        for (i = 0; i < 256; i++) {
            linear[i] = (uint32_t)i << 16 | (uint32_t)i << 8 | (uint32_t)i
                      | 0x80000000u;
        }
    } else if (mode == 3) {
        // The fog's colour at the one entry of its start.
        uint32_t c = ((uint32_t)ee_trunc_w(amount) & 0xffu) << 24
                   | ((uint32_t)ee_trunc_w(b) & 0xffu) << 16
                   | ((uint32_t)ee_trunc_w(g) & 0xffu) << 8
                   | ((uint32_t)ee_trunc_w(r) & 0xffu);
        int32_t  at = ee_trunc_w(start);

        memset(linear, 0, sizeof linear);
        if (at >= 0 && at < 256) {
            linear[at] = c;
        }
    } else {
        // Mode 0, and any past 3: the fog's colour, and an alpha that
        // rises from none at the start to the amount at 255 by FogPower,
        // read back to front. The image has a second curve here, from 240,
        // behind a test of 0 against 0 that is always taken.
        uint32_t rgb = ((uint32_t)ee_trunc_w(r) & 0xffu)
                     | ((uint32_t)ee_trunc_w(g) & 0xffu) << 8
                     | ((uint32_t)ee_trunc_w(b) & 0xffu) << 16;

        for (i = 0; i < 256; i++) {
            float fi = (float)i;
            float x;

            if (fi < start) {
                x = 0.0f;
            } else if (fi < 255.0f) {
                x = (fi - start) / (255.0f - start);
            } else {
                x = 1.0f;
            }
            linear[255 - i] =
                (uint32_t)ee_trunc_w(fpow(x, FogPower) * amount) << 24 | rgb;
        }
    }

    // What the nearest Z's give, 252 to 255, all the one at 255.
    linear[252] = linear[255];
    linear[254] = linear[255];
    linear[253] = linear[255];
    RemapLinearIntoClut8(palette, linear);
}

// ---------------------------------------------------------- the attaches

int eattach_depth_into_alpha(void)
{
    uint32_t upper[256], lower[256];
    int      i;

    if (!EnableDepthIntoAlpha) {
        return 0;
    }
    // The Z's high byte into the alpha's top six bits, 0xfc past 63; its
    // low byte's top two into the alpha's bottom two.
    for (i = 0; i < 256; i++) {
        upper[i] = (i & 0xc0) ? 0xff000000u : (uint32_t)i << 26;
    }
    for (i = 0; i < 256; i++) {
        lower[i] = (uint32_t)(i >> 6 & 3) << 24;
    }
    RemapLinearIntoClut8(DepthUpperPalette, upper);
    RemapLinearIntoClut8(DepthLowerPalette, lower);
    return 1;
}

int eattach_fog(void)
{
    int32_t id;

    if (!DrawFog) {
        return 0;
    }
    for (id = 1; id < 3; id++) {
        eView         *view = eGetView(id);
        eRenderTarget *rt   = view->pRenderTarget0;
        uint32_t      *pal  = GetFogPalette(view);
        int32_t        mode;

        if (!view->Active || !rt->Active || pal == NULL) {
            continue;
        }
        CreateFogPalette(view, pal);
        // The image takes the mode's FogModeInfo unbounded.
        mode = efog_view_mode(view);
        if (gEFogAttachFn != NULL) {
            gEFogAttachFn(view, pal, (uint32_t)mode < 4
                                         ? &FogModeInfos[mode] : NULL);
        }
    }
    return 1;
}

// ----------------------------------------------------- the PICA's side

uint32_t efog_depth_alpha(uint32_t z)
{
    uint32_t hi = DepthUpperPalette[efog_clut_index(z >> 8 & 0xffu)];
    uint32_t lo = DepthLowerPalette[efog_clut_index(z & 0xffu)];

    // The FRAME's masks: the first pass writes the alpha's bits 2 to 7,
    // the second its bits 0 and 1.
    return ((hi & 0xfc000000u) | (lo & 0x03000000u)) >> 24;
}

// ALPHA_1's two blends: mode 0's, the source over the frame by the
// source's alpha, and mode 1's, the frame less the source by it.
static int is_over(const FogModeInfo *m)
{
    return m->AlphaA == 0 && m->AlphaB == 1 && m->AlphaC == 0
        && m->AlphaD == 1;
}

static int is_darken(const FogModeInfo *m)
{
    return m->AlphaA == 1 && m->AlphaB == 0 && m->AlphaC == 0
        && m->AlphaD == 2;
}

int efog_colour(const uint32_t *palette, const FogModeInfo *mode,
                uint32_t *colour)
{
    uint32_t rgb  = 0;
    int      seen = 0;
    int      k;

    *colour = 0;
    if (mode == NULL || (!is_over(mode) && !is_darken(mode))) {
        return 0;
    }
    for (k = 0; k < 256; k++) {
        uint32_t c = palette[k];

        if ((c >> 24) == 0) {
            continue;
        }
        if (seen && (c & 0xffffffu) != rgb) {
            return 0;
        }
        rgb  = c & 0xffffffu;
        seen = 1;
    }
    // Mode 1's frame less a colour is the PICA's only for black.
    if (is_darken(mode) && rgb != 0) {
        return 0;
    }
    *colour = rgb;
    return 1;
}

float efog_keep(const uint32_t *palette, const FogModeInfo *mode,
                uint32_t z)
{
    uint32_t a = palette[efog_clut_index(efog_depth_alpha(z))] >> 24;

    if (mode == NULL) {
        return 1.0f;
    }
    if (is_over(mode)) {
        return 1.0f - (float)a / 128.0f;
    }
    if (is_darken(mode)) {
        return (float)a / 128.0f;
    }
    return 1.0f;
}
