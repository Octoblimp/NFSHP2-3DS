// hudanim -- see hudanim.h.

#include "hudanim.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "bprintf.h"
#include "eefpu.h"
#include "flailer.h"
#include "hudrender.h"
#include "player.h"
#include "playerhud.h"
#include "race.h"
#include "raceparams.h"
#include "realtime.h"

#define TICK_SECONDS 0.00025f           // gp-26748 and the six after it

// WRONG WAY's bitmap on the HUD screen.
#define WRONG_WAY_BITMAP 0x89af1a1eu

static float now_seconds(int32_t timer)
{
    return (float)timer * TICK_SECONDS;
}

// The text's or bitmap's top left goes through an int, its scale does not.
static void place(struct FlailerObjectChunk *o, const bVector2 *pos,
                  const bVector2 *scale)
{
    o->X = (float)ee_trunc_w(pos->x);
    o->Y = (float)ee_trunc_w(pos->y);
    o->ScaleX = scale->x;
    o->ScaleY = scale->y;
}

// SetColor's word: r, g and b truncated, each in its own byte.
static uint32_t colour_word(const bVector4 *c)
{
    return (uint32_t)ee_trunc_w(c->x)
           | (uint32_t)ee_trunc_w(c->y) << 8
           | (uint32_t)ee_trunc_w(c->z) << 16;
}

static void lerp4(bVector4 *out, const bVector4 *from, const bVector4 *d,
                  float t)
{
    out->x = d->x * t + from->x;
    out->y = d->y * t + from->y;
    out->z = d->z * t + from->z;
    out->w = d->w * t + from->w;
}

static void add4(bVector4 *out, const bVector4 *a, const bVector4 *b)
{
    out->x = a->x + b->x;
    out->y = a->y + b->y;
    out->z = a->z + b->z;
    out->w = a->w + b->w;
}

// -------------------------------------------------------------- HudAnimator

void hudanim_init(HudAnimator *a)
{
    a->New68 = 0;
    a->Type = 0;
    a->pText = NULL;
    a->pBitmap = NULL;
    a->bHasString = 0;
    a->bActive = 0;
    a->bKeepVisible = 0;
    a->Colour.x = 128.0f;
    a->Colour.y = 64.0f;
    a->Colour.z = 0.0f;
    a->Colour.w = 0.0f;
    memset(&a->DeltaColour, 0, sizeof a->DeltaColour);
    a->bRealTimer = 0;
}

HudAnimator *hudanim_new(void)
{
    // The two-argument bMalloc(288, 16), which takes no name.
    HudAnimator *a = bMalloc((int)sizeof(HudAnimator), "HudAnimator", 0, 16);

    hudanim_init(a);
    return a;
}

void hudanim_delete(HudAnimator *a)
{
    bFree(a);
}

void hudanim_start_scored(HudAnimator *a, struct FlailerTextChunk *t,
                          const bVector2 *pos, const bVector2 *dpos,
                          const bVector2 *dpos2, const bVector2 *scale,
                          const bVector2 *dscale, int32_t alpha,
                          float dalpha, const bVector4 *colour,
                          const bVector2 *scale1, const bVector2 *dscale2,
                          int32_t alpha1, float dalpha2,
                          const bVector4 *dcolour, float d0, float d1,
                          float d2, const char *s, int32_t real_timer)
{
    a->Type = HUDANIM_SCORED;
    a->Phase = 0;
    if (s != NULL) {
        a->bHasString = 1;
        b_snprintf(a->String, sizeof a->String, "%s", s);
    } else {
        a->bHasString = 0;
        a->String[0] = '\0';
    }
    a->Pos = *pos;
    a->DeltaPos = *dpos;
    a->Alpha = alpha;
    a->Scale = *scale;
    a->pText = t;
    a->DeltaScale = *dscale;
    a->DeltaAlpha = dalpha;
    a->Colour3 = *colour;
    a->DeltaPos2 = *dpos2;
    a->Scale1 = *scale1;
    a->DeltaScale2 = *dscale2;
    a->Alpha1 = alpha1;
    a->DeltaAlpha2 = dalpha2;
    a->DeltaColour3 = *dcolour;
    a->Duration[0] = d0;
    a->Duration[1] = d1;
    a->Duration[2] = d2;
    a->bRealTimer = real_timer;
    a->StartSeconds = now_seconds(real_timer ? RealTimer : WorldTimer);
    a->bActive = 1;
    if (a->pText != NULL) {
        place(&a->pText->Object, &a->Pos, &a->Scale);
        flailertext_set_alpha(a->pText, a->Alpha);
        flailerobject_set_visibility(&a->pText->Object, 1);
    }
}

void hudanim_start_text(HudAnimator *a, struct FlailerTextChunk *t,
                        const bVector2 *pos, const bVector2 *dpos,
                        const bVector2 *scale, const bVector2 *dscale,
                        int32_t alpha, float dalpha, float duration)
{
    a->Pos = *pos;
    a->DeltaPos = *dpos;
    a->Scale = *scale;
    a->Alpha = alpha;
    a->pText = t;
    a->DeltaScale = *dscale;
    a->Type = HUDANIM_SIMPLE;
    a->DeltaAlpha = dalpha;
    a->Colour.x = 128.0f;
    a->Colour.y = 64.0f;
    a->Colour.z = 0.0f;
    a->Colour.w = 0.0f;
    a->DeltaColour.x = 0.0f;
    a->DeltaColour.y = 64.0f;
    a->DeltaColour.z = 128.0f;
    a->DeltaColour.w = 0.0f;
    a->Duration[0] = duration;
    a->StartSeconds = now_seconds(WorldTimer);
    a->bActive = 1;
    if (a->pText == NULL)
        return;
    place(&a->pText->Object, &a->Pos, &a->Scale);
    flailertext_set_alpha(a->pText, a->Alpha);
    flailerobject_set_visibility(&a->pText->Object, 1);
}

void hudanim_start_bitmap(HudAnimator *a, struct FlailerBitmapChunk *b,
                          const bVector2 *pos, const bVector2 *dpos,
                          const bVector2 *scale, const bVector2 *dscale,
                          int32_t alpha, float dalpha, float duration,
                          int32_t keep)
{
    a->Type = HUDANIM_SIMPLE;
    if (a->bActive)
        return;
    a->Pos = *pos;
    a->Alpha = alpha;
    a->DeltaPos = *dpos;
    a->Scale = *scale;
    a->DeltaScale = *dscale;
    a->DeltaAlpha = dalpha;
    a->Duration[0] = duration;
    a->StartSeconds = now_seconds(WorldTimer);
    a->pBitmap = b;
    a->bActive = 1;
    a->bKeepVisible = keep;
    if (b == NULL)
        return;
    place(&b->Object, &a->Pos, &a->Scale);
    flailerbitmap_set_alpha(b, a->Alpha, -1);
    flailerobject_set_visibility(&b->Object, 1);
}

int32_t hudanim_do(HudAnimator *a)
{
    float t;
    bVector2 pos, scale;
    int32_t alpha;

    if (!a->bActive)
        return 0;
    t = (now_seconds(WorldTimer) - a->StartSeconds) / a->Duration[0];
    if (1.0f < t)
        t = 1.0f;
    if (a->Type != HUDANIM_SIMPLE)
        return 0;
    pos.x = a->DeltaPos.x * t + a->Pos.x;
    pos.y = a->DeltaPos.y * t + a->Pos.y;
    alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha * t);
    scale.x = a->DeltaScale.x * t + a->Scale.x;
    scale.y = a->DeltaScale.y * t + a->Scale.y;
    if (a->pText != NULL) {
        bVector4 c;

        place(&a->pText->Object, &pos, &scale);
        flailertext_set_alpha(a->pText, alpha);
        lerp4(&c, &a->Colour, &a->DeltaColour, t);
        flailertext_set_color(a->pText, colour_word(&c));
        if (1.0f <= t) {
            flailerobject_set_visibility(&a->pText->Object, 0);
            a->bActive = 0;
        }
    } else if (a->pBitmap != NULL) {
        place(&a->pBitmap->Object, &pos, &scale);
        flailerbitmap_set_alpha(a->pBitmap, alpha, -1);
        if (1.0f <= t) {
            flailerbitmap_set_alpha(a->pBitmap,
                                    a->Alpha + ee_trunc_w(a->DeltaAlpha), -1);
            a->bActive = 0;
            if (!a->bKeepVisible)
                flailerobject_set_visibility(&a->pBitmap->Object, 0);
        }
    }
    return 0;
}

int32_t hudanim_do_scored(HudAnimator *a, const Timer *time, const char *s)
{
    float t;
    bVector2 pos, scale;
    bVector4 c;
    int32_t alpha, phase;

    if (!a->bActive)
        return 0;
    t = now_seconds((int32_t)time->PackedTime) - a->StartSeconds;
    phase = a->Phase;
    // A phase out of range divides by nothing, and starts over below.
    if (phase >= 0 && phase <= 2)
        t = t / a->Duration[phase];
    if (1.0f < t)
        t = 1.0f;
    if (a->Type != HUDANIM_SCORED)
        return 0;
    if ((uint32_t)phase >= 3)
        a->Phase = phase = 0;
    if (phase == 0) {
        pos.x = a->DeltaPos.x * t + a->Pos.x;
        pos.y = a->DeltaPos.y * t + a->Pos.y;
        scale.x = a->DeltaScale.x * t + a->Scale.x;
        scale.y = a->DeltaScale.y * t + a->Scale.y;
        lerp4(&c, &a->Colour3, &a->DeltaColour3, t);
        alpha = a->Alpha + ee_trunc_w(a->DeltaAlpha * t);
    } else if (phase == 1) {
        pos.x = a->DeltaPos.x + a->Pos.x;
        pos.y = a->DeltaPos.y + a->Pos.y;
        scale = a->Scale1;
        add4(&c, &a->DeltaColour3, &a->Colour3);
        alpha = a->Alpha1;
    } else {
        pos.x = (a->DeltaPos2.x * t + a->DeltaPos.x) + a->Pos.x;
        pos.y = (a->DeltaPos2.y * t + a->DeltaPos.y) + a->Pos.y;
        scale.x = a->DeltaScale2.x * t + a->Scale1.x;
        scale.y = a->DeltaScale2.y * t + a->Scale1.y;
        add4(&c, &a->DeltaColour3, &a->Colour3);
        alpha = a->Alpha1 + ee_trunc_w(a->DeltaAlpha2 * t);
    }
    if (a->pText == NULL)
        return 0;
    place(&a->pText->Object, &pos, &scale);
    flailertext_set_alpha(a->pText, alpha);
    flailertext_set_string(a->pText, a->bHasString ? a->String : s);
    flailertext_set_color(a->pText, colour_word(&c));
    if (!(1.0f <= t))
        return 0;
    if (phase == 2) {
        flailerobject_set_visibility(&a->pText->Object, 0);
        a->bActive = 0;
        return 1;
    }
    a->StartSeconds = a->StartSeconds + a->Duration[phase];
    a->Phase = phase + 1;
    return 0;
}

void hudanim_finish(HudAnimator *a)
{
    switch (a->Type) {
    case HUDANIM_SIMPLE:
        if (a->pText != NULL) {
            flailerobject_set_visibility(&a->pText->Object, 0);
            a->bActive = 0;
        } else if (a->pBitmap != NULL) {
            bVector2 pos, scale;

            pos.x = a->DeltaPos.x + a->Pos.x;
            pos.y = a->DeltaPos.y + a->Pos.y;
            scale.x = a->DeltaScale.x + a->Scale.x;
            scale.y = a->DeltaScale.y + a->Scale.y;
            place(&a->pBitmap->Object, &pos, &scale);
            flailerbitmap_set_alpha(a->pBitmap,
                                    a->Alpha + ee_trunc_w(a->DeltaAlpha), -1);
            a->bActive = 0;
            if (!a->bKeepVisible)
                flailerobject_set_visibility(&a->pBitmap->Object, 0);
        }
        break;
    case HUDANIM_BLINK:
        if (a->pBitmap != NULL)
            flailerbitmap_set_alpha(a->pBitmap, ee_trunc_w(a->Colour.w), -1);
        break;
    case HUDANIM_SCORED:
        if (a->pText != NULL) {
            flailerobject_set_visibility(&a->pText->Object, 0);
            a->bActive = 0;
        }
        break;
    }
}

// ------------------------------------------------------------------ Player

void player_clear_hud_animations(struct Player *p)
{
    int32_t i;

    for (i = 0; i < 20; i++) {
        if ((uint32_t)(i - 12) < 3 || i == 18)
            continue;
        if (p->pHudAnimations[i] == NULL)
            continue;
        if (i == 10 && p->pHudAnimations[10]->bActive) {
            player_add_to_total_score(p, p->strPrevScore);
            p->pHudAnimations[10]->bActive = 0;
        }
        hudanim_finish(p->pHudAnimations[i]);
    }
}

void player_hud_start_wrong_way(struct Player *p)
{
    bVector2 from, to, scale_from, scale_to;
    struct FlailerObjectChunk *o;

    from.x = 258.0f;
    from.y = 119.0f;
    to.x = -105.0f;
    to.y = -80.0f;
    if (race_parameters_is_free_run(&TheRaceParameters)) {
        to.x = -240.0f;
        to.y = -100.0f;
    }
    if ((p->CurrentHudFeatures & (HUD_LIVE_SPLIT | HUD_RACE_POSITION))
        == HUD_LIVE_SPLIT) {
        to.x = -95.0f;
        to.y = -80.0f;
    }
    to.y = to.y + from.y;
    to.x = to.x + from.x;
    scale_from.x = scale_from.y = 1.0f;
    scale_to.x = scale_to.y = 0.3f;     // gp-30372
    if (PLAYER_NUM_SHOWN() >= 2) {
        scale_from.x = scale_from.y = 0.5f;
        scale_to.x = scale_to.y = 0.25f;
        if (p->PlayerNumber == 0) {
            from.x = 258.0f;
            from.y = 125.0f;
            to.x = 128.0f;
            to.y = from.y;
        }
        if (p->PlayerNumber == 1) {
            from.x = 258.0f;
            from.y = 350.0f;
            to.x = 128.0f;
            to.y = from.y;
        }
    }
    o = flailer_find_object(p->HudScreenHash, WRONG_WAY_BITMAP,
                            FLAILER_TYPE_BITMAP);
    player_hud_start_bitmap_animation(p, 15, (struct FlailerBitmapChunk *)o,
                                      &from, &to, &scale_from, &scale_to,
                                      64, 64, 1.0f, (uint32_t)WorldTimer, 1);
}

void player_hud_start_grow_animation(struct Player *p,
                                     struct FlailerTextChunk *a,
                                     struct FlailerTextChunk *b,
                                     uint32_t time, int32_t grow)
{
    bVector2 pos, scale, to, scale_to;
    int32_t alpha;

    // Retail reads b's fields with no check.
    if (b == NULL)
        return;
    pos.x = b->Object.X;
    pos.y = b->Object.Y;
    scale.x = b->Object.ScaleX;
    scale.y = b->Object.ScaleY;
    alpha = flailertext_get_alpha(b);
    if (grow) {
        to.x = 0.0f + pos.x;
        to.y = -30.0f + pos.y;
        scale_to.x = scale_to.y = 2.0f;
        player_hud_start_text_animation(p, 0, a, &pos, &to, &scale,
                                        &scale_to, alpha, 0, 0.5f, time);
    } else {
        to.x = 0.0f + pos.x;
        to.y = 100.0f + pos.y;
        scale_to.x = scale_to.y = 0.5f;
        player_hud_start_text_animation(p, 0, a, &pos, &to, &scale,
                                        &scale_to, 0, alpha, 1.0f, time);
    }
}

void player_hud_start_speed_animation(struct Player *p,
                                      struct FlailerTextChunk *a,
                                      struct FlailerTextChunk *b,
                                      uint32_t time, int32_t grow)
{
    bVector2 pos, scale, to, scale_to;
    int32_t alpha;

    if (p->pFlailerSpeedString == NULL)
        return;
    // Retail reads b's fields with no check.
    if (b == NULL)
        return;
    pos.x = b->Object.X;
    pos.y = b->Object.Y;
    scale.x = b->Object.ScaleX;
    scale.y = b->Object.ScaleY;
    alpha = flailertext_get_alpha(b);
    if (grow) {
        float w = flailerobject_get_width_float(&b->Object);
        float h = flailerobject_get_height_float(&b->Object);
        float hw, hh;

        scale_to.x = scale_to.y = 2.0f;
        // Scaled about the centre: half the size, less half of it scaled.
        hh = h * 0.5f;
        hw = w * 0.5f;
        to.y = (hh + hh * -scale_to.y) + pos.y;
        to.x = (hw + hw * -scale_to.x) + pos.x;
    } else {
        to.x = 0.0f + pos.x;
        to.y = 100.0f + pos.y;
        scale_to.x = scale_to.y = 0.5f;
    }
    player_hud_start_text_animation(p, 1, a, &pos, &to, &scale, &scale_to,
                                    alpha, 0, 1.0f, time);
}

static HudAnimator *slot_animator(struct Player *p, int32_t slot)
{
    if (p->pHudAnimations[slot] == NULL)
        p->pHudAnimations[slot] = hudanim_new();
    return p->pHudAnimations[slot];
}

void player_hud_start_text_animation(struct Player *p, int32_t slot,
                                     struct FlailerTextChunk *t,
                                     const bVector2 *from,
                                     const bVector2 *to,
                                     const bVector2 *scale_from,
                                     const bVector2 *scale_to,
                                     int32_t alpha_from, int32_t alpha_to,
                                     float duration, uint32_t time)
{
    HudAnimator *a = slot_animator(p, slot);
    bVector2 dpos, dscale;

    (void)time;
    dpos.x = to->x - from->x;
    dpos.y = to->y - from->y;
    dscale.x = scale_to->x - scale_from->x;
    dscale.y = scale_to->y - scale_from->y;
    hudanim_start_text(a, t, from, &dpos, scale_from, &dscale, alpha_from,
                       (float)(int32_t)((uint32_t)alpha_to
                                        - (uint32_t)alpha_from),
                       duration);
}

void player_hud_start_bitmap_animation(struct Player *p, int32_t slot,
                                       struct FlailerBitmapChunk *b,
                                       const bVector2 *from,
                                       const bVector2 *to,
                                       const bVector2 *scale_from,
                                       const bVector2 *scale_to,
                                       int32_t alpha_from, int32_t alpha_to,
                                       float duration, uint32_t time,
                                       int32_t keep)
{
    HudAnimator *a = slot_animator(p, slot);
    bVector2 dpos, dscale;

    (void)time;
    dpos.x = to->x - from->x;
    dpos.y = to->y - from->y;
    dscale.x = scale_to->x - scale_from->x;
    dscale.y = scale_to->y - scale_from->y;
    hudanim_start_bitmap(a, b, from, &dpos, scale_from, &dscale, alpha_from,
                         (float)(int32_t)((uint32_t)alpha_to
                                          - (uint32_t)alpha_from),
                         duration, keep);
}

static int32_t running(const HudAnimator *a)
{
    return a != NULL && a->bActive;
}

void player_hud_do_animations(struct Player *p)
{
    Timer now;
    int32_t i;

    if (running(p->pHudAnimations[0])
        && (p->CurrentHudFeatures & HUD_RACE_POSITION))
        hudanim_do(p->pHudAnimations[0]);
    if (running(p->pHudAnimations[1])
        && (p->CurrentHudFeatures & (HUD_GAUGES | HUD_GAUGES_OUTSIDE)))
        hudanim_do(p->pHudAnimations[1]);
    for (i = 2; i <= 8; i++)
        if (running(p->pHudAnimations[i]))
            hudanim_do(p->pHudAnimations[i]);
    now.PackedTime = (uint32_t)WorldTimer;
    if (running(p->pHudAnimations[10])
        && hudanim_do_scored(p->pHudAnimations[10], &now, p->strEventScore))
        player_add_to_total_score(p, p->strEventScore);
    if (running(p->pHudAnimations[11]))
        hudanim_do_scored(p->pHudAnimations[11], &now, p->strEventTitle);
    if (running(p->pHudAnimations[12]))
        hudanim_do_scored(p->pHudAnimations[12], &now, "SCORE");
    if (running(p->pHudAnimations[13]))
        hudanim_do_scored(p->pHudAnimations[13], &now, "");
    if (running(p->pHudAnimations[15]))
        hudanim_do(p->pHudAnimations[15]);
    for (i = 16; i <= 17; i++)
        if (running(p->pHudAnimations[i]))
            hudanim_do(p->pHudAnimations[i]);
}

void player_add_to_total_score(struct Player *p, const char *s)
{
    char buf[32];

    p->TotalScore = (int32_t)((uint32_t)p->TotalScore
                              + (uint32_t)player_convert_score_string(p, s));
    if (p->TotalScore < 0)
        p->TotalScore = 0;
    b_snprintf(buf, sizeof buf, "%d", p->TotalScore);
    if (p->pFlailerScoreTotal != NULL)
        flailertext_set_string((struct FlailerTextChunk *)p->pFlailerScoreTotal,
                               buf);
}
