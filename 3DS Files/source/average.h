// average -- Average, PidError and Linear, the three small filters out of
// table.cpp (0x00187550 .. 0x00187918).
//
// Like Table and Graph they are header-inline classes. Their out-of-line
// methods sit in the run after Graph's, just before AICarController's
// constructor. Average's allocation names "..\indep\src\table.cpp".
//
// An Average is a running mean over a ring of `nSlots` samples. The AI
// driver, the psycho driver, the AI car controller, the belt mover, the AI
// engine sound, the player's joystick port and RealController each keep
// one. A PidError is two Averages -- the integral and the derivative of an
// error signal -- and a Linear is a line through two points.
//
// DoSnapshot (0x00187730, 0x00187860) waits on ReplaySnapshot.
//
// Written up in docs/formats/average.md.
#ifndef AVERAGE_H
#define AVERAGE_H

#include <stdint.h>

// 24 bytes on the disc.
typedef struct Average {
    int32_t nSlots;      // 0
    int32_t nCurrentSlot;// 4
    int32_t nSamples;    // 8
    float   fTotal;      // 12
    float   fAverage;    // 16
    float  *pData;       // 20
} Average;

// 0x00187550. Zeroes the counters and the sums, then takes a cleared
// buffer of `slots` floats from bMalloc(slots * 4, "..\indep\src\table.cpp",
// 120, 16).
Average *average_init(Average *a, int32_t slots);

// 0x001875c8. Frees the buffer, and the Average too when bit 0 of `flags`
// is set.
void average_destroy(Average *a, int32_t flags);

// 0x00187618. Replaces the oldest sample with `v` and recomputes the mean
// over the samples seen so far, up to nSlots.
void average_record(Average *a, float v);

// 0x00187698. Fills the ring with `v`, sets the total to match and the
// sample count to zero. The mean and the slot index are left alone.
void average_reset(Average *a, float v);

// 0x001876e0. The same, but the ring counts as full and the mean is `v`.
void average_flush(Average *a, float v);

// Inline: fAverage, and fTotal.
float average_get_value(const Average *a);
float average_get_total(const Average *a);

// 56 bytes on the disc.
typedef struct PidError {
    Average aIntegral;     // 0
    Average aDerivative;   // 24
    float   fCurrentError; // 48
    float   fPreviousError;// 52
} PidError;

// Inline everywhere (PsychoDriver's constructor builds three): the two
// Averages, then both errors zero.
PidError *pid_error_init(PidError *p, int32_t integralSlots,
                         int32_t derivativeSlots);

// 0x00138f28. Both Averages' destructors with flags 2, then the PidError
// itself when bit 0 of `flags` is set.
void pid_error_destroy(PidError *p, int32_t flags);

// 0x001877f8. Takes the new error and the time step: the integral records
// the trapezoid `dt * (prev + (err - prev) * 0.5)`, the derivative records
// `(err - prev) / dt`.
void pid_error_record(PidError *p, float err, float dt);

// 0x001878b0. The current error becomes zero and the previous one `err`.
// Both Averages are reset -- to the current error, which is now zero, not
// to `err`.
void pid_error_reset(PidError *p, float err);

// 8 bytes on the disc.
typedef struct Linear {
    float m; // 0
    float b; // 4
} Linear;

// 0x001878f8. The line through (x1, y1) and (x2, y2).
void linear_init(Linear *l, float x1, float y1, float x2, float y2);

// 0x00187918. m * x + b.
float linear_get_value(const Linear *l, float x);

#endif
