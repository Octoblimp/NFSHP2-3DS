// camera -- Camera.obj (0x00153a20 .. 0x00154380).
//
// The Camera is not a mover and does not decide where it is. It is told a
// matrix once a frame and pulls everything else out of it: where the eye is,
// which way it points, what it is looking at, and how fast all three are
// changing. `Camera::SetCameraMatrix` is the whole object.
//
// Three copies of the same 144-byte record are kept: this frame, last frame,
// and the per-second difference between them. The velocity record is what
// the sound code reads for doppler and what the motion blur would have read.
//
// Half of that velocity record is dead, and it is dead on the disc rather
// than here. SetCameraMatrix copies CurrentKey over PreviousKey as its very
// first act, and then recomputes only four of the ten fields -- the matrix
// and the three vectors. So when it reaches the subtractions, the two copies
// of TargetDistance, FocalDistance, DepthOfField, NearZ, FarZ and
// FieldOfView are still the same word, and all six velocities come out
// identically zero. Nothing can arrange otherwise: every writer of those six
// -- the movers, the setters below -- writes before the call, never between
// the copy and the subtraction. The arithmetic is ported anyway, including
// the u16 wrap on the field of view, because it is what the instructions
// say; just do not expect a number out of it. tools/camera_check.py proves
// it rather than asserting it -- all 44 velocity records in the transcript
// read `scal 0 0 0 0 0 fov 0` -- and lists the three mutations that cannot
// therefore be caught.
//
// Written up with addresses in docs/formats/camera.md. The port is checked by
// tools/camera_check.py.
#ifndef CAMERA_H
#define CAMERA_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

// ------------------------------------------------------------------ the data

// 144 bytes. The ten bytes after FieldOfView are padding in the original too;
// nothing reads them.
typedef struct CameraParams {
    bMatrix4 Matrix;         // 0   the view matrix, as handed in
    bVector3 Position;       // 64  the eye, in world space
    bVector3 Direction;      // 80  unit, the way it looks
    bVector3 Target;         // 96  Position + Direction * TargetDistance
    float    TargetDistance; // 112
    float    FocalDistance;  // 116
    float    DepthOfField;   // 120
    float    NearZ;          // 124
    float    FarZ;           // 128
    uint16_t FieldOfView;    // 132 a BAM, so 16384 is a right angle
    uint8_t  Pad[10];        // 134
} CameraParams;

// 448 bytes.
//
// Two parts of this are never initialised on the disc and are left that way
// here, because the port's job is to be the disc: the constructor writes
// CurrentKey's scalars and then lets SetCameraMatrix fill the rest, so
// CurrentKey.Pad is garbage, and nothing anywhere writes VelocityKey.Matrix
// -- SetCameraMatrix differences the three vectors and the six scalars and
// stops. Everything else does settle: the constructor calls SetCameraMatrix
// twice with the same matrix, so the second call differences a key against
// itself and the whole velocity record comes out zero.
typedef struct Camera {
    CameraParams CurrentKey;    // 0
    CameraParams PreviousKey;   // 144
    CameraParams VelocityKey;   // 288, per second
    float        ElapsedTime;   // 432 seconds since the previous key
    uint32_t     LastUpdateTime;// 436
    void        *CarNotToRender;// 440 a Car *, not yet a type here
    int          RenderDash;    // 444
} Camera;

// `Camera::StopUpdating` at 0x3234b8. Set by the debug camera tools; while it
// is non-zero every setter in this file and in cammover.c is a no-op, which
// is how the game freezes a camera and flies around it. Zero on the disc.
extern int CameraStopUpdating;

// ---------------------------------------------------------------- the object

// 0x00153a20. Fills all three keys with the default placement; see
// docs/formats/camera.md for the matrix it uses and the 100.0 in it.
void camera_init(Camera *c);

// 0x00153b10. The copy constructor: all three keys, plus the four scalars,
// and LastUpdateTime forced back to 0x80000000.
void camera_copy(Camera *dst, const Camera *src);

// 0x00153ba0. The one that matters.
//
//   PreviousKey = CurrentKey
//   ElapsedTime = elapsed
//   CurrentKey.Matrix = *m
//   Position  = -(m.row3 * transpose(m), with the translation column cleared)
//   Direction = normalize(column 2 of m)
//   Target    = Position + Direction * TargetDistance
//   VelocityKey = (CurrentKey - PreviousKey) / elapsed, field by field
//
// A zero `elapsed` divides by zero, exactly as the original does: the
// velocity record fills with infinities and the next call overwrites them.
void camera_set_matrix(Camera *c, const bMatrix4 *m, float elapsed);

// The trivial accessors, kept because callers in later tasks are written
// against these names. Setters are no-ops while CameraStopUpdating is set --
// except these, which are not: only SetCameraMatrix and the movers check it.
void     camera_set_target_distance(Camera *c, float d);
void     camera_set_focal_distance(Camera *c, float d);
void     camera_set_depth_of_field(Camera *c, float d);
void     camera_set_field_of_view(Camera *c, uint16_t bam);
void     camera_set_near_z(Camera *c, float z);
void     camera_set_far_z(Camera *c, float z);

// `Camera::ComputeEye` is in the class but has no symbol of its own in the
// MAP, so it was inlined at every call site. This is what those call sites
// do: CurrentKey.Position widened to four components with w = 1.
void     camera_compute_eye(const Camera *c, bVector4 *o);

#endif
