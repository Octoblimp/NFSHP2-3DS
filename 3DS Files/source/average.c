// average -- see average.h and docs/formats/average.md.
#include "average.h"

#include <string.h>

#include "bmem.h"
#include "eefpu.h"

// ----------------------------------------------------------------- Average

// 0x00187550.
Average *average_init(Average *a, int32_t slots)
{
    int32_t size = (int32_t)((uint32_t)slots << 2);

    a->nCurrentSlot = 0;
    a->nSamples     = 0;
    a->fTotal       = 0.0f;
    a->fAverage     = 0.0f;
    a->nSlots       = slots;
    a->pData = bMalloc(size, "..\\indep\\src\\table.cpp", 120, 16);
    memset(a->pData, 0, (size_t)(uint32_t)size);
    return a;
}

// 0x001875c8. __builtin_delete is `j bFree`.
void average_destroy(Average *a, int32_t flags)
{
    bFree(a->pData);
    if (flags & 1)
        bFree(a);
}

// 0x00187618.
void average_record(Average *a, float v)
{
    int32_t slots = a->nSlots;
    int32_t n     = a->nSamples;
    int32_t cur;
    float  *slot;

    if (n < slots) {
        n = n + 1;
        a->nSamples = n;
    }

    // The new sample goes into the total before the oldest comes out: two
    // roundings, in that order.
    a->fTotal = a->fTotal + v;
    cur  = a->nCurrentSlot;
    slot = &a->pData[cur];
    a->nCurrentSlot = cur + 1;
    a->fTotal = a->fTotal - *slot;
    *slot = v;

    // `div.s` by the sample count, which is zero only for a ring of no
    // slots.
    a->fAverage = ee_div(a->fTotal, (float)n);

    if (!(cur + 1 < slots))
        a->nCurrentSlot = 0;
}

// 0x00187698.
void average_reset(Average *a, float v)
{
    int32_t i;

    for (i = 0; i < a->nSlots; i++)
        a->pData[i] = v;
    // The count goes to zero while the total still counts every slot, so
    // the next Record divides a full ring's sum by one. The only caller,
    // PidError::Reset, passes zero, where it makes no difference.
    a->nSamples = 0;
    a->fTotal   = v * (float)a->nSlots;
}

// 0x001876e0.
void average_flush(Average *a, float v)
{
    int32_t i;

    for (i = 0; i < a->nSlots; i++)
        a->pData[i] = v;
    a->fAverage = v;
    a->nSamples = a->nSlots;
    a->fTotal   = v * (float)a->nSlots;
}

float average_get_value(const Average *a)
{
    return a->fAverage;
}

float average_get_total(const Average *a)
{
    return a->fTotal;
}

// ---------------------------------------------------------------- PidError

PidError *pid_error_init(PidError *p, int32_t integralSlots,
                         int32_t derivativeSlots)
{
    average_init(&p->aIntegral, integralSlots);
    average_init(&p->aDerivative, derivativeSlots);
    p->fCurrentError  = 0.0f;
    p->fPreviousError = 0.0f;
    return p;
}

// 0x00138f28. The derivative's destructor runs first.
void pid_error_destroy(PidError *p, int32_t flags)
{
    average_destroy(&p->aDerivative, 2);
    average_destroy(&p->aIntegral, 2);
    if (flags & 1)
        bFree(p);
}

// 0x001877f8.
void pid_error_record(PidError *p, float err, float dt)
{
    float prev  = p->fCurrentError;
    float delta;

    p->fCurrentError  = err;
    delta             = err - prev;
    p->fPreviousError = prev;
    average_record(&p->aIntegral, dt * (prev + delta * 0.5f));
    average_record(&p->aDerivative, ee_div(delta, dt));
}

// 0x001878b0. `lwc1 $f20,48(s0)` reads the current error back after the
// zero has been stored to it.
void pid_error_reset(PidError *p, float err)
{
    float zero;

    p->fCurrentError  = 0.0f;
    p->fPreviousError = err;
    zero = p->fCurrentError;
    average_reset(&p->aIntegral, zero);
    average_reset(&p->aDerivative, zero);
}

// ------------------------------------------------------------------ Linear

// 0x001878f8.
void linear_init(Linear *l, float x1, float y1, float x2, float y2)
{
    float m = ee_div(y2 - y1, x2 - x1);

    l->m = m;
    l->b = y1 - m * x1;
}

// 0x00187918.
float linear_get_value(const Linear *l, float x)
{
    return l->m * x + l->b;
}
