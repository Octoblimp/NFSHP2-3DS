// eefpu -- the R5900 FPU's float-to-int conversion, its divide by zero and
// its square root of a negative, as the port spells them.
//
// Not a port of any object. bmath.h and emath.h are faithful ports of
// bMath.obj and eMath.obj and own no invented functions, so a helper that
// several classes need in order to agree with the console lives here
// instead. Car was the first caller and PhysicsCar::UpdateCar the second,
// which is when it moved out of car.c.

#ifndef EEFPU_H
#define EEFPU_H

#include <math.h>
#include <stdint.h>
#include <string.h>

// `cvt.w.s`, all of it.
//
// Truncation toward zero is the easy half and a C cast already does it. The
// other half is what happens off the ends: the R5900 saturates *by the sign
// of the source*, 0x7fffffff for a value at or above 2^31 and 0x80000000 for
// one below -2^31. A bare C cast does not reproduce that -- the conversion is
// undefined behaviour in C, and the three targets disagree about it in
// practice. ARM's `vcvt.s32.f32` saturates by sign and so agrees with the
// R5900; x86-64's `cvttss2si` returns 0x80000000 for *either* overflow, so
// the host build of this port would disagree with both the console and the
// handheld on a positive one.
//
// So it is written out. tools/camera_check.py's `trunc_w` is the same
// function on the model side and has been since the camera slice. The
// negative threshold there is spelled `<= -2147483649.0`, which selects the
// same set of float32 values as `< -2147483648.0f` does here: the next
// float32 below -2^31 is -2147483904, and nothing lies between them.
static inline int32_t ee_trunc_w(float x)
{
    if (x != x)                     // no NaN reaches the EE FPU; defined anyway
        return 0;
    if (x >= 2147483648.0f)
        return (int32_t)0x7fffffff;
    if (x < -2147483648.0f)
        return (int32_t)0x80000000;
    return (int32_t)x;
}

// `div.s` by zero.
//
// IEEE gives an infinity, or a NaN for 0/0. The R5900 has neither: it gives
// FLT_MAX signed by the XOR of the operands' signs, whatever the dividend,
// and reads a denormal divisor as a zero on the way in. Every other
// quotient is the plain one -- the EE rounds toward zero where the port
// rounds to nearest, and that difference is accepted everywhere else.
//
// The port spells a divide this way only where the image is seen dividing
// by zero on a path the game takes. tools/mipsemu.py's `eediv` is the same
// function on the model side, and its `eediv_pcs` is how the sites are
// found: so far the two share divides in DriveTrain::ApplyClutchTorque,
// where a driven pair standing still is 0/0 on every frame the car sits in
// gear.
static inline float ee_div(float a, float b)
{
    uint32_t ab, bb;

    memcpy(&bb, &b, sizeof bb);
    if ((bb & 0x7f800000u) == 0) {
        uint32_t r;
        float q;
        memcpy(&ab, &a, sizeof ab);
        r = ((ab ^ bb) & 0x80000000u) | 0x7f7fffffu;
        memcpy(&q, &r, sizeof q);
        return q;
    }
    return a / b;
}

// `sqrt.s` of a negative.
//
// IEEE gives a NaN. The R5900 takes the root of the magnitude and raises
// its invalid flag, which nothing in the game reads. -0.0 is not below
// zero and keeps its sign, as it does on both. tools/mipsemu.py's `eesqrt`
// is the model's side, and its `eesqrt_pcs` finds the sites. The first is
// DynamicCollisionBody::TrackPolygonCheck: `sqrt(1 - d*d)` of a dot
// product of two unit vectors that rounds a little past one, where the
// console gets a small root and an IEEE machine a NaN that fails every
// test the polygon is put to.
static inline float ee_sqrt(float x)
{
    return x < 0.0f ? sqrtf(-x) : sqrtf(x);
}

#endif
