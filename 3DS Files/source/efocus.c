// efocus -- see efocus.h.

#include "efocus.h"

#include <string.h>

#include "camera.h"
#include "eefpu.h"
#include "efog.h"

int32_t DrawDepthOfField = 1;
int32_t FocusPrintPalette;
float   FocusAlphaMin;
float   FocusAlphaMax = 128.0f;
float   FocalDistance;
float   DepthOfField;
int32_t JitterBlend = 64;
int32_t FocusJitterSamples = 2;
int32_t FocusRampLength = 24;
float   FocusFirstPrevious = -3.40282347e+38f;

int32_t FocusJitter[6][2] = {
    { 0, 0 }, { 32, 32 }, { 32, 0 }, { 32, 32 }, { 0, 32 }, { 0, 0 },
};

uint32_t FocusPalettes[4][256];

void (*gEDofAttachFn)(eView *view, const uint32_t *palette,
                      const EFocusBand *band);
void (*gEDofBlurFn)(void);

// ------------------------------------------------------------ the helpers

static uint32_t bits_of(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

uint32_t *GetFocusPalette(eView *view)
{
    uint32_t n = (uint32_t)(view->ID - 1);

    return n < 4 ? FocusPalettes[n] : NULL;
}

uint32_t MapScreenZToPaletteIndex(float z)
{
    return bits_of(z) >> 12 & 0xffu;
}

float MapPaletteIndexToScreenZ(uint32_t i)
{
    uint32_t u = bits_of(ZRanges[1].ZMin) | (i & 0xffu) << 12;
    float    f;

    memcpy(&f, &u, sizeof f);
    return f;
}

float MapScreenZToViewZ(float near, float far, float sz)
{
    float span = far - near;
    float a    = near * far * (ZRanges[1].ZMax - ZRanges[1].ZMin) / span;
    float b    = (-ZRanges[1].ZMax * near + ZRanges[1].ZMin * far) / span;

    return a / (sz - b);
}

// -------------------------------------------------------------- the palette

// A ramp's entry a of len: from the minimum to the maximum by a / len.
static uint32_t ramp_entry(int32_t a, int32_t len, float range)
{
    float v = FocusAlphaMin + (float)a / (float)len * range;

    return (uint32_t)ee_trunc_w(v) << 24 | 0x808080u;
}

static int create(eView *view, uint32_t *palette, EFocusBand *band)
{
    float    d[256];
    uint32_t lin[256];
    Camera  *cam;
    float    near, far, focal, dof, half, nearEdge, farEdge, prev, range;
    uint32_t maxC, minC;
    int32_t  len, t0, t1, a, k;

    if (view == NULL || palette == NULL) {
        return 0;
    }
    cam   = view->pCamera;
    near  = view->NearZ;
    far   = view->FarZ;
    focal = cam->CurrentKey.FocalDistance;
    dof   = cam->CurrentKey.DepthOfField;
    // Each index's view depth, nearest first: d[255 - i] for index i.
    for (k = 0; k < 256; k++) {
        d[255 - k] = MapScreenZToViewZ(near, far,
                                       MapPaletteIndexToScreenZ((uint32_t)k));
    }
    len = FocusRampLength;
    if (FocalDistance != 0.0f) {
        focal = FocalDistance;
    }
    if (DepthOfField != 0.0f) {
        dof = DepthOfField;
    }
    range = FocusAlphaMax - FocusAlphaMin;
    if (dof == 0.0f && focal == 0.0f) {
        memset(palette, 0, 256 * sizeof *palette);
        return 0;
    }

    // The band's edges: the last entries at which d[] reaches each.
    half     = dof * 0.5f;
    farEdge  = focal + half;
    nearEdge = focal - half;
    prev     = FocusFirstPrevious;
    t0       = 0;
    t1       = 255;
    for (k = 0; k < 256; k++) {
        if (prev < nearEdge && nearEdge <= d[k]) {
            t0 = k;
        }
        if (prev < farEdge && farEdge <= d[k]) {
            t1 = k;
        }
        prev = d[k];
    }

    // The minimum inside the band and the maximum out of it, then the
    // ramps, rising away from each edge, over what they reach; read back
    // to front.
    maxC = (uint32_t)ee_trunc_w(FocusAlphaMax) << 24 | 0x808080u;
    minC = (uint32_t)ee_trunc_w(FocusAlphaMin) << 24 | 0x808080u;
    for (k = 0; k < 256; k++) {
        lin[255 - k] = k < t0 || t1 < k ? maxC : minC;
    }
    for (a = 1; a < len; a++) {
        if ((uint32_t)(t0 - a) < 256u) {
            lin[255 - (t0 - a)] = ramp_entry(a, len, range);
        }
    }
    for (a = 1; a < len; a++) {
        if ((uint32_t)(t1 + a) < 256u) {
            lin[255 - (t1 + a)] = ramp_entry(a, len, range);
        }
    }
    // The image's print of each index's screen Z is stripped to the calls.
    if (FocusPrintPalette) {
        for (k = 0; k < 256; k++) {
            (void)MapPaletteIndexToScreenZ((uint32_t)k);
        }
        FocusPrintPalette = 0;
    }
    RemapLinearIntoClut8(palette, lin);
    if (band != NULL) {
        band->Near = t0;
        band->Far  = t1;
    }
    return 1;
}

int CreateFocusPalette(eView *view, uint32_t *palette)
{
    return create(view, palette, NULL);
}

// ------------------------------------------------------------ the attach

int eattach_depth_of_field(void)
{
    EFocusBand band[2];
    int        made[2] = { 0, 0 };
    int        any     = 0;
    int32_t    id;

    if (!DrawDepthOfField) {
        return 0;
    }
    // The palettes, which the image sends up as CLUTs whatever came back.
    for (id = 1; id < 3; id++) {
        eView    *view = eGetView(id);
        uint32_t *pal;

        if (!view->Active) {
            continue;
        }
        pal = GetFocusPalette(view);
        if (pal == NULL) {
            continue;
        }
        made[id - 1] = create(view, pal, &band[id - 1]);
        any |= made[id - 1];
    }
    if (!any) {
        return 0;
    }
    // Each view's pass, then the blur's.
    for (id = 1; id < 3; id++) {
        eView    *view = eGetView(id);
        uint32_t *pal;

        if (!view->Active) {
            continue;
        }
        pal = GetFocusPalette(view);
        if (pal == NULL) {
            continue;
        }
        if (gEDofAttachFn != NULL) {
            gEDofAttachFn(view, pal, made[id - 1] ? &band[id - 1] : NULL);
        }
    }
    if (gEDofBlurFn != NULL) {
        gEDofBlurFn();
    }
    return 1;
}

// ----------------------------------------------------- the PICA's side

uint8_t efocus_pica_byte(uint32_t gsAlpha)
{
    return gsAlpha >= 128u ? 255u : (uint8_t)((gsAlpha * 255u + 64u) / 128u);
}

// The palette's alpha at the PS2's index j: its entry's top byte.
static uint32_t entry_alpha(const uint32_t *palette, uint32_t j)
{
    return palette[efog_clut_index(j)] >> 24;
}

static void constant_step(EFocusStep *s, uint32_t gsAlpha)
{
    memset(s, 0, sizeof *s);
    s->Alpha = efocus_pica_byte(gsAlpha);
}

// x = sat(w F) for F = 255 / (2 len): B is twice the index, so w over 255
// is the distance in entries over 127.5. F is Times (1, 2 or 4) by 4 to the
// Quads by 1 + K / 255, or K / 255 alone for an F under 1. The quads are
// taken while F is past 8 and the stages allow. The PICA scales w by Times
// where it makes it, so the last stage's product drops less than one; a K
// of 0 with a Times needs no product.
//
// Only the step, a length under 1 and so an F of 255, is past 8 when the
// quads run out: with both terms and the INTERPOLATE, two are left. Its w
// is 0 or 1 / 255 and up, so any F of 255 and past gives its x: the
// product's stage is one more quad, for 256.
static void step_scale(EFocusStep *s, int32_t len, int quadsLeft)
{
    float f = len >= 1 ? 255.0f / (2.0f * (float)len) : 255.0f;
    float k;

    s->Quads = 0;
    while (f > 8.0f && s->Quads < quadsLeft) {
        f *= 0.25f;
        s->Quads++;
    }
    if (f > 8.0f) {
        s->Quads++;
        s->Times = 4;
        s->K     = 0;
        return;
    }
    if (f >= 1.0f) {
        s->Times = f > 4.0f ? 4 : f > 2.0f ? 2 : 1;
        k        = f / (float)s->Times - 1.0f;
    } else {
        s->Times = 0;
        k        = f;
    }
    s->K = (uint8_t)ee_trunc_w(k * 255.0f + 0.5f);
}

// The indices lo .. hi, whose B is twice the index past `base`: the alpha
// there if it is one throughout, else the ramps about the band.
static void region_step(const uint32_t *palette, const EFocusBand *band,
                        uint32_t lo, uint32_t hi, int32_t base,
                        EFocusStep *s)
{
    uint32_t first = entry_alpha(palette, lo);
    uint32_t j;
    int32_t  far, near;
    int      both, stages;

    for (j = lo + 1; j <= hi; j++) {
        if (entry_alpha(palette, j) != first) {
            break;
        }
    }
    if (j > hi || band == NULL) {
        constant_step(s, first);
        return;
    }
    memset(s, 0, sizeof *s);
    s->Ramp = 1;
    s->Min  = efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMin) & 0xffu);
    s->Max  = efocus_pica_byte((uint32_t)ee_trunc_w(FocusAlphaMax) & 0xffu);
    // The band's indices are far .. near: the far edge is the lower.
    far      = 255 - band->Far;
    near     = 255 - band->Near;
    s->FarB  = (int16_t)(2 * (far - base));
    s->NearB = (int16_t)(2 * (near - base) + 1);
    // The stages: the sum (one term, or two and their add), the product,
    // and the INTERPOLATE where the alpha is not 0 to 255; the quads in
    // what is left of six. Where both terms are made, each takes the first
    // quad as its stage's scale: the far is past 0 only short of FarB and
    // the near only past NearB, so one at most is.
    both   = s->FarB > 0 && s->NearB < 255;
    stages = (both ? 3 : 1) + 1 + (s->Min != 0 || s->Max != 255);
    step_scale(s, FocusRampLength, 6 - stages + both);
}

static int same_step(const EFocusStep *a, const EFocusStep *b)
{
    return !a->Ramp && !b->Ramp && a->Alpha == b->Alpha;
}

void efocus_plan(const uint32_t *palette, const EFocusBand *band,
                 EFocusPlan *plan)
{
    static const float at[3] = { 0.0f, 1.0f / 256.0f, 2.0f / 256.0f };
    EFocusStep         step[3];
    uint32_t           j;
    int                n;

    memset(plan, 0, sizeof *plan);
    for (j = 0; j < 256; j++) {
        if (palette[j] >> 24 != 0) {
            break;
        }
    }
    if (j == 256) {
        return;
    }
    region_step(palette, band, 0, 127, 0, &step[0]);
    region_step(palette, band, 128, 255, 128, &step[1]);
    constant_step(&step[2], entry_alpha(palette, 255));
    for (n = 0; n < 3; n++) {
        if (plan->Count > 0
            && same_step(&plan->Step[plan->Count - 1], &step[n])) {
            continue;
        }
        plan->Step[plan->Count] = step[n];
        plan->At[plan->Count]   = at[n];
        plan->Count++;
    }
}

// The combiners' sums as the PICA's bytes: saturated at each stage, and a
// product over 255 taken down.
static uint32_t sat8(int32_t v)
{
    return v < 0 ? 0u : v > 255 ? 255u : (uint32_t)v;
}

static uint32_t step_alpha(const EFocusStep *s, uint32_t d24)
{
    int32_t  b = (int32_t)(d24 >> 8 & 0xffu);
    uint32_t w = 0, x;
    int      q;

    if (!s->Ramp) {
        return s->Alpha;
    }
    if (s->FarB > 0) {
        w += sat8(s->FarB - b);
    }
    if (s->NearB < 255) {
        w += sat8(b - s->NearB);
    }
    w = sat8((int32_t)(w * (s->Times ? s->Times : 1u)));
    for (q = 0; q < s->Quads; q++) {
        w = sat8((int32_t)w * 4);
    }
    if (s->Times) {
        x = sat8((int32_t)(w + w * s->K / 255u));
    } else {
        x = w * s->K / 255u;
    }
    return (s->Max * x + s->Min * (255u - x)) / 255u;
}

float efocus_pica_alpha(const EFocusPlan *plan, uint32_t d24)
{
    float depth = (float)d24 / 16777215.0f;
    int   n, at = 0;

    if (plan->Count == 0) {
        return 0.0f;
    }
    for (n = 1; n < plan->Count; n++) {
        if (plan->At[n] <= depth) {
            at = n;
        }
    }
    return (float)step_alpha(&plan->Step[at], d24) / 255.0f;
}
