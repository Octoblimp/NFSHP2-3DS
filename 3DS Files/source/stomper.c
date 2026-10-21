// stomper -- the render eggs: see stomper.h.

#include "stomper.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "carrenderinfo.h"
#include "eastereggs.h"
#include "eview.h"
#include "radialblur.h"
#include "weatherman.h"

Stomper *pStomper;

int32_t OverrideAnimatedDriverLOD;
int32_t nBoneScale = -1;
float   vBoneScale[4] = { 1.0f, 1.0f, 1.0f, 0.0f };

// The lists, by the demo's names where it has them (sRadialBlur,
// sCutiePetootie); the others are the port's. Each is retail's, entry for
// entry, at the address given.

// 0x0031d410: Motion Blur.
static const StompEntry sRadialBlur[] = {
    { STOMP_FUNCTION_INT, { .pFuncInt = radialblur_on_off }, { .nData = 0 } },
    { STOMP_END,          { NULL },                          { 0 } },
};

// 0x0031d440: Black & White.
static const StompEntry sBlackAndWhite[] = {
    { STOMP_INT32, { .pData = &ForceBlackAndWhite }, { .nData = 1 } },
    { STOMP_END,   { NULL },                         { 0 } },
};

// 0x0031d6a8: Heavy Fog.
static const StompEntry sHeavyFog[] = {
    { STOMP_INT32, { .pData = &WeatherHeavyFog }, { .nData = 1 } },
    { STOMP_END,   { NULL },                      { 0 } },
};

// 0x0031d4b0: the driver's big head. The demo's sCutiePetootie pokes
// OverrideAnimatedDriverLOD 0 and the bones 4.0 instead, and has no
// ForceRenderDriver.
static const StompEntry sBigHead[] = {
    { STOMP_INT32, { .pData = &OverrideAnimatedDriverLOD }, { .nData = 1 } },
    { STOMP_INT32, { .pData = &ForceRenderDriver },         { .nData = 1 } },
    { STOMP_INT32, { .pData = &nBoneScale },                { .nData = 15 } },
    { STOMP_FLOAT, { .pData = &vBoneScale[0] },             { .fData = 5.5f } },
    { STOMP_FLOAT, { .pData = &vBoneScale[1] },             { .fData = 5.5f } },
    { STOMP_FLOAT, { .pData = &vBoneScale[2] },             { .fData = 5.5f } },
    { STOMP_END,   { NULL },                                { 0 } },
};

// 0x0031d508: R/C Car. The demo's scales the car by 0.6, 0.7 and 1.1.
static const StompEntry sCutiePetootie[] = {
    { STOMP_FLOAT,  { .pData = &CarRenderMatrix.v0.x }, { .fData = 0.5f } },
    { STOMP_FLOAT,  { .pData = &CarRenderMatrix.v1.y }, { .fData = 0.5f } },
    { STOMP_FLOAT,  { .pData = &CarRenderMatrix.v2.z }, { .fData = 0.5f } },
    { STOMP_NESTED, { .pNested = sBigHead },            { 0 } },
    { STOMP_END,    { NULL },                           { 0 } },
};

// 0x0031d6c0: Chrome Cars.
static const StompEntry sChrome[] = {
    { STOMP_INT32, { .pData = &EnvPassAlphaA },   { .nData = 2 } },
    { STOMP_INT32, { .pData = &EnvPassAlphaB },   { .nData = 2 } },
    { STOMP_INT32, { .pData = &EnvPassAlphaC },   { .nData = 1 } },
    { STOMP_INT32, { .pData = &EnvPassAlphaD },   { .nData = 0 } },
    { STOMP_INT32, { .pData = &EnvPassAlphaFix }, { .nData = 128 } },
    { STOMP_END,   { NULL },                      { 0 } },
};

// The demo's seven, which nothing sets: see stomper.h.
static const StompEntry sNotPorted[] = {
    { STOMP_END, { NULL }, { 0 } },
};

const StompEntry *const StomperTable[STOMPER_NUM] = {
    NULL,
    sNotPorted, sNotPorted, sNotPorted, sNotPorted,
    sNotPorted, sNotPorted, sNotPorted,
    sRadialBlur,
    sBlackAndWhite,
    sHeavyFog,
    sCutiePetootie,
    sChrome,
};

// Each case keeps the old value at the save's width, then pokes the new;
// a word of the stack goes to each, whatever its width.
uint8_t *stompentry_set(const StompEntry *s, uint8_t *save)
{
    switch (s->nType) {
    case STOMP_INT8: {
        uint8_t v = (uint8_t)s->v.nData;

        memcpy(save, s->u.pData, 1);
        memcpy(s->u.pData, &v, 1);
        return save + 4;
    }
    case STOMP_INT16: {
        uint16_t v = (uint16_t)s->v.nData;

        memcpy(save, s->u.pData, 2);
        memcpy(s->u.pData, &v, 2);
        return save + 4;
    }
    case STOMP_INT32:
        memcpy(save, s->u.pData, 4);
        memcpy(s->u.pData, &s->v.nData, 4);
        return save + 4;
    case STOMP_FLOAT:
        memcpy(save, s->u.pData, 4);
        memcpy(s->u.pData, &s->v.fData, 4);
        return save + 4;
    case STOMP_FUNCTION_INT: {
        int32_t v = s->u.pFuncInt(1, s->v.nData);

        memcpy(save, &v, 4);
        return save + 4;
    }
    case STOMP_FUNCTION_FLOAT: {
        float f = s->u.pFuncFloat(1, s->v.fData);

        memcpy(save, &f, 4);
        return save + 4;
    }
    case STOMP_NESTED:
        return stompentry_set_all(s->u.pNested, save);
    default:
        return save;
    }
}

uint8_t *stompentry_clear(const StompEntry *s, uint8_t *save)
{
    switch (s->nType) {
    case STOMP_INT8:
        memcpy(s->u.pData, save, 1);
        return save + 4;
    case STOMP_INT16:
        memcpy(s->u.pData, save, 2);
        return save + 4;
    case STOMP_INT32:
    case STOMP_FLOAT:
        memcpy(s->u.pData, save, 4);
        return save + 4;
    case STOMP_FUNCTION_INT: {
        int32_t v;

        memcpy(&v, save, 4);
        s->u.pFuncInt(0, v);
        return save + 4;
    }
    case STOMP_FUNCTION_FLOAT: {
        float f;

        memcpy(&f, save, 4);
        s->u.pFuncFloat(0, f);
        return save + 4;
    }
    case STOMP_NESTED:
        return stompentry_clear_all(s->u.pNested, save);
    default:
        return save;
    }
}

// Both walk forward: a list that pokes one global twice puts back, last,
// what its second poke saved, so the global keeps the first poke's value.
// Retail's do the same.
uint8_t *stompentry_set_all(const StompEntry *s, uint8_t *save)
{
    for (; s->nType != STOMP_END; s++)
        save = stompentry_set(s, save);
    return save;
}

uint8_t *stompentry_clear_all(const StompEntry *s, uint8_t *save)
{
    for (; s->nType != STOMP_END; s++)
        save = stompentry_clear(s, save);
    return save;
}

Stomper *stomper_construct(Stomper *s)
{
    s->bEnabled = 1;
    s->pStack   = bMalloc(STOMPER_STACK_SIZE, "Stomper Stack", 0, 16);
    s->nCurrent = STOMPER_NONE;
    return s;
}

void stomper_destroy(Stomper *s, int32_t flags)
{
    bFree(s->pStack);
    if (flags & 1)
        bFree(s);
}

void stomper_clear(Stomper *s)
{
    if ((uint32_t)(s->nCurrent - 1) < STOMPER_NUM - 1)
        stompentry_clear_all(StomperTable[s->nCurrent], s->pStack);
    s->nCurrent = STOMPER_NONE;
}

void stomper_set(Stomper *s, int32_t e)
{
    if ((uint32_t)(e - 1) < STOMPER_NUM - 1) {
        stompentry_set_all(StomperTable[e], s->pStack);
        s->nCurrent = e;
    }
}

void stomper_clear_set(Stomper *s, int32_t e)
{
    stomper_clear(s);
    stomper_set(s, e);
}

void stomper_suspend(Stomper *s)
{
    int32_t e = s->nCurrent;

    stomper_clear(s);
    s->nCurrent = e;
}

void stomper_resume(Stomper *s)
{
    stomper_set(s, s->nCurrent);
}

void InitStomper(void)
{
    pStomper = stomper_construct(bMalloc(sizeof(Stomper), "Stomper", 0, 16));
}

void CloseStomper(void)
{
    if (pStomper != NULL)
        stomper_destroy(pStomper, 3);
    pStomper = NULL;
}

void ResetRenderEggs(void)
{
    if (pStomper != NULL)
        stomper_clear(pStomper);
}

void SetRenderEggFromEasterEggs(void)
{
    const EasterEggCode *c;

    if (pStomper == NULL)
        return;
    c = TheEasterEggs.Codes;
    if (c[0].On)
        stomper_set(pStomper, STOMPER_MOTION_BLUR);
    else if (c[1].On)
        stomper_set(pStomper, STOMPER_BLACK_AND_WHITE);
    else if (c[2].On)
        stomper_set(pStomper, STOMPER_HEAVY_FOG);
    else if (c[3].On)
        stomper_set(pStomper, STOMPER_RC_CAR);
    else if (c[4].On)
        stomper_set(pStomper, STOMPER_BLACK_AND_WHITE);
    else if (c[8].On)
        stomper_set(pStomper, STOMPER_CHROME);
}

void SuspendRenderEggs(void)
{
    if (pStomper != NULL)
        stomper_suspend(pStomper);
}

void ResumeRenderEggs(void)
{
    if (pStomper != NULL)
        stomper_resume(pStomper);
}

void DisableRenderEggs(void)
{
    Stomper *s = pStomper;

    if (s != NULL) {
        stomper_clear(s);
        s->bEnabled = 0;
    }
}

void EnableRenderEggs(void)
{
    if (pStomper != NULL)
        pStomper->bEnabled = 1;
}
