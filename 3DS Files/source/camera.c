// camera -- Camera.obj (0x00153a20 .. 0x00154380). See camera.h.
#include <math.h>
#include <string.h>

#include "camera.h"
#include "emath.h"

// 0x3234b8. Zero on the disc.
int CameraStopUpdating = 0;

// ---------------------------------------------------------------- the ctor

// The constructor builds this on the stack and hands it to SetCameraMatrix
// twice, so Current and Previous both end up holding it:
//
//     1     0     0     0
//     0    -1     0     0
//     0     0    -1   100
//     0     0  1200     1
//
// The 100.0 sits in the fourth column, where a transform has no business
// putting anything. The decomposition below adds that column into Position
// after the transpose, so the default eye comes out at (0, 0, 1100) rather
// than the (0, 0, 1200) the translation row asks for. It is a hundred units
// of nothing in a camera that gets overwritten on the first real frame, and
// it is kept because the port's job is to be the disc.
void camera_init(Camera *c)
{
    bMatrix4 m;

    c->ElapsedTime = 1.0f;
    c->CarNotToRender = 0;
    c->RenderDash = 0;
    c->LastUpdateTime = 0x80000000u;

    c->CurrentKey.FocalDistance = 0.0f;
    c->CurrentKey.DepthOfField = 0.0f;
    c->CurrentKey.TargetDistance = 10.0f;
    c->CurrentKey.FieldOfView = 14075;
    c->CurrentKey.NearZ = 0.5f;
    c->CurrentKey.FarZ = 5000.0f;

    memset(&m, 0, sizeof m);
    m.v0.x = 1.0f;
    m.v1.y = -1.0f;
    m.v2.z = -1.0f;  m.v2.w = 100.0f;
    m.v3.z = 1200.0f; m.v3.w = 1.0f;

    camera_set_matrix(c, &m, 1.0f);
    camera_set_matrix(c, &m, 1.0f);
}

// 0x00153b10.
void camera_copy(Camera *dst, const Camera *src)
{
    dst->LastUpdateTime = 0x80000000u;
    dst->ElapsedTime = src->ElapsedTime;
    dst->CarNotToRender = src->CarNotToRender;
    dst->RenderDash = src->RenderDash;
    dst->CurrentKey = src->CurrentKey;
    dst->PreviousKey = src->PreviousKey;
    dst->VelocityKey = src->VelocityKey;
}

// ------------------------------------------------------- the decomposition

// 0x00153ba0.
//
// The debug path this leaves out: if the pointer at 0x2f2870 is non-null the
// matrix is taken from a network debug feed ("JollyRancher") instead of from
// the argument, with its translation row scaled by 0.01 and its corner forced
// to 1. That pointer is null unless a debug server answered at boot, so the
// shipped game always takes the branch below.
void camera_set_matrix(Camera *c, const bMatrix4 *m, float elapsed)
{
    bMatrix4 t;
    bVector3 row3;
    CameraParams *cur = &c->CurrentKey;
    const CameraParams *prev = &c->PreviousKey;
    CameraParams *vel = &c->VelocityKey;
    float d, k, inv;

    if (CameraStopUpdating)
        return;

    c->PreviousKey = c->CurrentKey;
    c->ElapsedTime = elapsed;
    cur->Matrix = *m;

    // The transpose with its fourth column cleared. Row 3 of the transpose is
    // the fourth COLUMN of the matrix, and it is left alone -- which is how
    // the 100.0 in the constructor's matrix reaches Position.
    eTransposeMatrix(&t, &cur->Matrix);
    t.v0.w = 0.0f;
    t.v1.w = 0.0f;
    t.v2.w = 0.0f;

    // Position = -(translation row * that). eMulVector3 forces w to 1, so
    // row 3 of the transpose is added in.
    //
    // The negate is `vsub.xyzw vf02,vf00,vf02` at 0x00153cb8 and vf00 is
    // VU0's constant (0,0,0,1), so the fourth lane comes out as 1 - w rather
    // than -w. Every lane of this record is carried because the whole
    // quadword is stored and differenced; see the note on bVector3::pad.
    // The original passes the matrix row straight in as a bVector3 *; the
    // two types have the same sixteen-byte layout and eMulVector3 forces w
    // to 1 regardless, so the copy is a type-system formality.
    row3.x = cur->Matrix.v3.x;
    row3.y = cur->Matrix.v3.y;
    row3.z = cur->Matrix.v3.z;
    row3.pad = cur->Matrix.v3.w;
    //
    // It is a subtraction from zero, not a negation: a lane that comes out
    // +0 stays +0, where -x would make it -0.
    eMulVector3(&cur->Position, &t, &row3);
    cur->Position.x = 0.0f - cur->Position.x;
    cur->Position.y = 0.0f - cur->Position.y;
    cur->Position.z = 0.0f - cur->Position.z;
    cur->Position.pad = 1.0f - cur->Position.pad;

    // Direction is the normalised third column, which the transpose has
    // already laid out as its row 2. The length is the 3D one -- vmul.xyz
    // then vaddy.x/vaddz.x -- but the scale is applied xyzw, and t.v2.w has
    // just been zeroed, so the fourth lane is 0 * k.
    d = t.v2.x * t.v2.x;
    d = d + t.v2.y * t.v2.y;
    d = d + t.v2.z * t.v2.z;
    k = 1.0f / sqrtf(d);
    cur->Direction.x = t.v2.x * k;
    cur->Direction.y = t.v2.y * k;
    cur->Direction.z = t.v2.z * k;
    cur->Direction.pad = t.v2.w * k;

    cur->Target.x = cur->Position.x + cur->Direction.x * cur->TargetDistance;
    cur->Target.y = cur->Position.y + cur->Direction.y * cur->TargetDistance;
    cur->Target.z = cur->Position.z + cur->Direction.z * cur->TargetDistance;
    cur->Target.pad = cur->Position.pad
                    + cur->Direction.pad * cur->TargetDistance;

    // Everything per second. A zero elapsed gives infinities, as on the disc.
    //
    // Only the three vector differences below can be non-zero. PreviousKey
    // was copied from CurrentKey at the top of this function and only the
    // matrix and the vectors have been rewritten since, so every scalar
    // difference is a word minus itself. See the note in camera.h.
    inv = 1.0f / elapsed;

    vel->Position.x = (cur->Position.x - prev->Position.x) * inv;
    vel->Position.y = (cur->Position.y - prev->Position.y) * inv;
    vel->Position.z = (cur->Position.z - prev->Position.z) * inv;
    vel->Position.pad = (cur->Position.pad - prev->Position.pad) * inv;

    vel->Direction.x = (cur->Direction.x - prev->Direction.x) * inv;
    vel->Direction.y = (cur->Direction.y - prev->Direction.y) * inv;
    vel->Direction.z = (cur->Direction.z - prev->Direction.z) * inv;
    vel->Direction.pad = (cur->Direction.pad - prev->Direction.pad) * inv;

    vel->Target.x = (cur->Target.x - prev->Target.x) * inv;
    vel->Target.y = (cur->Target.y - prev->Target.y) * inv;
    vel->Target.z = (cur->Target.z - prev->Target.z) * inv;
    vel->Target.pad = (cur->Target.pad - prev->Target.pad) * inv;

    vel->TargetDistance = (cur->TargetDistance - prev->TargetDistance) * inv;
    vel->FocalDistance = (cur->FocalDistance - prev->FocalDistance) * inv;
    vel->DepthOfField = (cur->DepthOfField - prev->DepthOfField) * inv;
    vel->NearZ = (cur->NearZ - prev->NearZ) * inv;
    vel->FarZ = (cur->FarZ - prev->FarZ) * inv;

    // The angular one goes through u16 subtraction first, so a camera whose
    // field of view crosses zero reports the short way round rather than a
    // 65000-BAM jump. Then int -> float -> scale -> int, truncating.
    {
        uint16_t dfov = (uint16_t)(cur->FieldOfView - prev->FieldOfView);

        vel->FieldOfView = (uint16_t)(int)((float)(int)dfov * inv);
    }
}

// ------------------------------------------------------------- accessors

void camera_set_target_distance(Camera *c, float d) { c->CurrentKey.TargetDistance = d; }
void camera_set_focal_distance(Camera *c, float d)  { c->CurrentKey.FocalDistance = d; }
void camera_set_depth_of_field(Camera *c, float d)  { c->CurrentKey.DepthOfField = d; }
void camera_set_field_of_view(Camera *c, uint16_t b){ c->CurrentKey.FieldOfView = b; }
void camera_set_near_z(Camera *c, float z)          { c->CurrentKey.NearZ = z; }
void camera_set_far_z(Camera *c, float z)           { c->CurrentKey.FarZ = z; }

void camera_compute_eye(const Camera *c, bVector4 *o)
{
    o->x = c->CurrentKey.Position.x;
    o->y = c->CurrentKey.Position.y;
    o->z = c->CurrentKey.Position.z;
    o->w = 1.0f;
}
