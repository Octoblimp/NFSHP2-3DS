// emodelanim -- eModel's rigid animation timing (emodel.h, the last
// section): GetRigidAnimation, GetRigidAnimationTime and
// SetRigidAnimationFrameNumber. A file apart from emodel.c because these
// read the world clock, which emodel.c's checkers do not link.
//
// The fern shaker (fernshaker.c) is the first caller. Cross-check:
// tools/eventmgr_check.py, which runs the image's three under its shakes.

#include "emodel.h"

#include <stdint.h>

#include "esolid.h"
#include "realtime.h"

eRigidAnimation *emodel_get_rigid_animation(const eModel *m)
{
    const eSolid *s = (const eSolid *)m->Solid;

    if (s == NULL)
        return NULL;
    return (eRigidAnimation *)(void *)s->pRigidAnimation;
}

// NumFrames and FrameRateScale are loaded signed (lh, lb).
static int32_t animation_length(const eModel *m)
{
    const eRigidAnimation *a = (const eRigidAnimation *)(const void *)
        ((const eSolid *)m->Solid)->pRigidAnimation;

    return (int32_t)(int16_t)a->NumFrames * (int32_t)(int8_t)a->FrameRateScale;
}

int32_t emodel_get_rigid_animation_time(const eModel *m)
{
    uint32_t start = (uint16_t)m->RigidAnimationStartTime;
    int32_t  t, len;

    if (start == 0)
        return -1;
    t = (int32_t)(((uint32_t)WorldTimeFrames - start) & 0x3fffu);
    len = animation_length(m);
    if ((start & 0x4000u) != 0)
        return t % len;
    return t < len ? t : -1;
}

void emodel_set_rigid_animation_frame_number(eModel *m, int32_t frame)
{
    uint32_t t = ((uint32_t)WorldTimeFrames - (uint32_t)frame * 2u) & 0x3fffu;

    m->RigidAnimationStartTime = (int16_t)(t | 0x8000u);
}
