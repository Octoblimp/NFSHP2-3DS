// steering -- see steering.h.

#include "steering.h"

#include "bmath.h"
#include "replay.h"

void steering_init(Steering *s, const CarTypeInfo *cti)
{
    s->CTI = cti;
    s->_vtable = STEERING_VTABLE;
    // SteeringMatrix is deliberately not written: see steering.h.
}

void steering_fini(Steering *s)
{
    s->_vtable = STEERING_VTABLE;
}

bMatrix4 *steering_get_matrix(const Steering *s, int32_t wheel)
{
    // `sll a1,a1,6` -- the index is scaled by 64 with no bounds check, so
    // this is plain pointer arithmetic and a bad index walks off the end.
    return s->SteeringMatrix + wheel;
}

TwoWheelAckermanSteering *ackerman_init(TwoWheelAckermanSteering *a,
                                        const CarTypeInfo *cti)
{
    // The base constructor is inlined rather than called: the listing
    // writes CTI and the vtable itself.
    a->base.CTI = cti;
    a->base._vtable = ACKERMAN_VTABLE;

    // `addiu a2,a0,16` before the loop, `sw a2,4(a0)` after it. The
    // matrices themselves are left as they were found.
    a->base.SteeringMatrix = &a->AckermanMatrix[0];

    return a;
}

void ackerman_fini(TwoWheelAckermanSteering *a)
{
    a->base._vtable = ACKERMAN_VTABLE;

    // `jal _$_8Steering` with a1 = 0, which writes the *base's* vtable
    // over the one just stored. A destroyed object ends up carrying
    // Steering's vtable, not this class's -- so do not collapse these
    // two writes into one.
    steering_fini(&a->base);
}

void ackerman_compute_auxiliaries(TwoWheelAckermanSteering *a)
{
    (void)a;   // jr ra ; nop
}

// Writes a rotation about Z into `m`: bIdentity, then m[0] and m[5] to
// the cosine, m[1] to the sine and m[4] to its negative.
//
// The cosine comes from bSinF(angle + pi/2) rather than a cosine call,
// and the pi/2 is the image's own one-ulp-high constant, so this is not
// interchangeable with bCosBam or with cosf.
static void ackerman_rotate_z(bMatrix4 *m, float angle)
{
    float c, s;

    bIdentity(m);

    c = bSinF(angle + STEERING_IMAGE_HALF_PI);
    s = bSinF(angle);

    m->v0.x = c;
    m->v0.y = s;
    m->v1.x = -s;
    m->v1.y = c;
}

void ackerman_set_steering(TwoWheelAckermanSteering *a, uint16_t bam)
{
    const CarTypeInfo *cti = a->base.CTI;
    float rad, wheelbase, track, inner, outer, first, second;

    // `andi a1,a1,0xffff` then `cvt.s.w`: the BAM is zero-extended, so
    // rad starts in [0, 2pi) and never negative.
    rad = (float)(int32_t)bam * STEERING_BAM_TO_RADIANS;

    // Both subtractions are computed before the branch -- the second one
    // is in the branch's delay slot and the branch is a plain bc1f, not
    // a likely one, so it happens either way.
    wheelbase = cti->Wheels[0].PositionX - cti->Wheels[3].PositionX;
    track     = cti->Wheels[0].PositionY - cti->Wheels[1].PositionY;

    // The fold, with the image's own pi and 2pi rather than the
    // library's. One-sided: a rad below -pi cannot occur, because rad
    // came from an unsigned BAM.
    if (STEERING_IMAGE_PI < rad)
        rad -= STEERING_IMAGE_TWO_PI;

    // Ackerman with tan(x) ~ x: cot(outer) = cot(inner) + Track/Wheelbase
    // becomes outer = (W * inner) / (W + T * inner). The magnitude is
    // taken first, so the divide always sees a non-negative inner.
    inner = (rad < 0.0f) ? -rad : rad;
    outer = (wheelbase * inner) / (wheelbase + track * inner);

    if (rad < 0.0f) {
        // `f23 = -f12 ; f22 = -f0` -- turning one way, matrix 1 takes
        // the full angle and matrix 0 the reduced one.
        first  = -outer;
        second = -inner;
    } else {
        first  = inner;
        second = outer;
    }

    ackerman_rotate_z(&a->AckermanMatrix[0], first);
    ackerman_rotate_z(&a->AckermanMatrix[1], second);
}

// ---------------------------------------------------------------- the replay

// 0x001a5d10.
void ackerman_do_snapshot(TwoWheelAckermanSteering *a, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "TwoWheelAckermanSteering");
    ReplaySnapshot_MoveMatrix(s, &a->AckermanMatrix[0]);
    ReplaySnapshot_EndNamedSection(s);
}
