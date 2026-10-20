// emodelanim -- eModel's animations (emodel.h, the last two sections):
// the rigid animation's timing (GetRigidAnimation, GetRigidAnimationTime,
// SetRigidAnimationFrameNumber) and what eModel::Render plays of it and of
// a vertex animation (SetupRigidAnimation, SetupVertexAnimation and
// eRigidAnimation::GetMatrixAtTime). A file apart from emodel.c because
// these read the world clock, which emodel.c's checkers do not link.
//
// The fern shaker (fernshaker.c) starts a bush's animation, carrender.c a
// car's wipers', and eModel::ReconnectSolid every other one, looping from
// the load. Cross-checks: tools/eventmgr_check.py runs the image's timing
// under its shakes, and tools/emodelanim_check.py the image's Render setup.

#include "emodel.h"

#include <stdint.h>

#include "bmatrix.h"
#include "eframe.h"
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

// The frames are bMatrix4s from Matricies on, one after another.
void erigidanimation_get_matrix_at_time(const eRigidAnimation *a,
                                        bMatrix4 *out, int32_t time)
{
    int32_t frame = time / (int32_t)(int8_t)a->FrameRateScale
                    % (int32_t)(int16_t)a->NumFrames;

    *out = *(const bMatrix4 *)(const void *)(a->Matricies + frame * 64);
}

bMatrix4 *emodel_setup_rigid_animation(eModel *m, bMatrix4 *matrix)
{
    int32_t   t = emodel_get_rigid_animation_time(m);
    bMatrix4 *out;

    if (t < 0) {
        m->RigidAnimationStartTime = 0;
        return matrix;
    }
    out = (bMatrix4 *)eframe_malloc(64);
    if (out == NULL)
        return matrix;
    erigidanimation_get_matrix_at_time(
        (const eRigidAnimation *)(const void *)
            ((const eSolid *)m->Solid)->pRigidAnimation, out, t);
    bMulMatrix(out, matrix, out);
    return out;
}

// The product is the EE's 32-bit mult, then a signed divide by 60.
void emodel_setup_vertex_animation(eModel *m)
{
    const eVertexAnimator *va = (const eVertexAnimator *)
        ((const eSolid *)m->Solid)->pVertexAnimator;
    uint32_t start = (uint16_t)m->RigidAnimationStartTime & 0x3fffu;
    int32_t  t = (int32_t)(((uint32_t)WorldTimeFrames - start)
                           * (uint32_t)va->FrameRate) / 60;
    uint32_t k = (uint32_t)(t % va->NumSolids) % (uint32_t)va->NumSolids;

    m->Solid = va->SolidTable[k];
}

bMatrix4 *emodel_setup_animation(eModel *m, bMatrix4 *matrix)
{
    const eSolid *s = (const eSolid *)m->Solid;

    if (s == NULL)
        return matrix;
    if (s->pRigidAnimation != NULL && (uint16_t)m->RigidAnimationStartTime != 0)
        matrix = emodel_setup_rigid_animation(m, matrix);
    if (((const eSolid *)m->Solid)->pVertexAnimator != NULL)
        emodel_setup_vertex_animation(m);
    return matrix;
}
