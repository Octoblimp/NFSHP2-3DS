// nisoverlay -- see nisoverlay.h.

#include "nisoverlay.h"

#include <stddef.h>

#include "bmem.h"
#include "trackflow.h"

void (*gFlailerGetScaleFn)(uint32_t screen, uint32_t object, float *sx,
                           float *sy);
float (*gFlailerGetTopLeftYFn)(uint32_t screen, uint32_t object);
void (*gFlailerChunkSetScaleXFn)(struct FlailerObjectChunk *o, float sx);
void (*gFlailerChunkSetScaleYFn)(struct FlailerObjectChunk *o, float sy);
void (*gFlailerChunkSetTopLeftYFn)(struct FlailerObjectChunk *o, float y);

// FlailerScreenVisibility's INVISIBLE.
#define NISOVERLAY_SCREEN_INVISIBLE 1

// tCubic1D's constructor, inlined.
static BSpline *new_track(void)
{
    BSpline *t = (BSpline *)bMalloc(48, "NISCubicAnimation", 0, 16);

    t->duration = 1.0f;
    t->arrivalThreshold = 1.0f;
    t->flags = 1;
    t->val = 0.0f;
    t->dval = 0.0f;
    t->valDesired = 0.0f;
    t->dvalDesired = 0.0f;
    t->state = 0;
    return t;
}

NISOverlayManager *nisoverlay_init(NISOverlayManager *o)
{
    o->ScreenHash = 0;
    o->State = FLAILER_NIS_IDLE;
    o->ScaleAnimationTrack = new_track();
    o->AlphaAnimationTrack = new_track();
    o->ScaleY = 1.0f;
    o->ScaleX = 1.0f;
    o->sx = 0.0f;
    o->sy = 0.0f;
    return o;
}

void nisoverlay_destroy(NISOverlayManager *o, int32_t flags)
{
    bFree(o->ScaleAnimationTrack);
    bFree(o->AlphaAnimationTrack);
    if (flags & 1)
        bFree(o);
}

void nisoverlay_set_screen(NISOverlayManager *o, uint32_t screen)
{
    float sx = 1.0f, sy = 1.0f;

    o->ScreenHash = screen;
    if (gFlailerGetScaleFn != NULL)
        gFlailerGetScaleFn(screen, NISOVERLAY_BUSTED_OBJECT, &sx, &sy);
    o->SavedScaleX = sx;
    sx = 1.0f;
    sy = 1.0f;
    if (gFlailerGetScaleFn != NULL)
        gFlailerGetScaleFn(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT, &sx, &sy);
    o->SavedScaleY = sy;
    o->SavedTopLeftY = gFlailerGetTopLeftYFn != NULL
        ? gFlailerGetTopLeftYFn(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT)
        : 0.0f;
}

void nisoverlay_finish(NISOverlayManager *o)
{
    if (o->ScreenHash == 0)
        return;
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(o->ScreenHash,
                                      NISOVERLAY_SCREEN_INVISIBLE);
    if (o->BustedDisplay == NULL)
        return;
    if (gFlailerChunkSetScaleXFn != NULL)
        gFlailerChunkSetScaleXFn(o->BustedDisplay, o->SavedScaleX);
    if (gFlailerChunkSetScaleYFn != NULL)
        gFlailerChunkSetScaleYFn(o->BustedDisplay, o->SavedScaleY);
    if (gFlailerChunkSetTopLeftYFn != NULL)
        gFlailerChunkSetTopLeftYFn(o->BustedDisplay, o->SavedTopLeftY);
}
