// average -- Average, PidError and Linear, the three small filters out of
// table.cpp (retail 0x0018fbf0 .. 0x00190080).
//
// Like Table and Graph they are header-inline classes. Their out-of-line
// methods sit in the run after Graph's, just before AICarController's
// constructor. Average's buffer names "..\indep\src\table.cpp", line 167.
//
// An Average is a running mean over a ring of `nSlots` samples. The AI
// driver, the psycho driver, the AI car controller, the belt mover, the AI
// engine sound, the player's joystick port and RealController each keep
// one. A PidError is two Averages -- the integral and the derivative of an
// error signal -- and a Linear is a line through two points.
//
// Retail's Average is 16 bytes, its three counters bytes; the demo's was
// 24, with words. Every owner news its own (bMalloc(16, ...)), and
// PsychoDriver news its PidErrors too (40 bytes).
//
// DoSnapshot (0x0018fe38, 0x0018ff98) waits on ReplaySnapshot.
//
// Written up in docs/formats/average.md.
#ifndef AVERAGE_H
#define AVERAGE_H

#include <stddef.h>
#include <stdint.h>

// 16 bytes on the disc.
typedef struct Average {
    uint8_t nSlots;      // 0
    uint8_t nCurrentSlot;// 1
    uint8_t nSamples;    // 2
    float   fTotal;      // 4
    float   fAverage;    // 8
    float  *pData;       // 12
} Average;

#ifndef AVERAGE_NO_ASSERT
typedef char average_layout_check[
    (offsetof(Average, nCurrentSlot) == 1
     && offsetof(Average, nSamples) == 2
     && offsetof(Average, fTotal) == 4
     && offsetof(Average, fAverage) == 8
     && (sizeof(void *) != 4 || offsetof(Average, pData) == 12)) ? 1 : -1];
#endif

// 0x0018fbf0. Zeroes the index, the count, the total and the mean, keeps
// the low byte of `slots`, then takes a buffer of `slots` floats from
// bMalloc(slots * 4, "..\indep\src\table.cpp", 167, 16) -- the whole
// count, not the byte -- and clears it with bMemSet.
Average *average_init(Average *a, int32_t slots);

// 0x0018fc68. Deletes the buffer, and the Average too when bit 0 of
// `flags` is set.
void average_destroy(Average *a, int32_t flags);

// 0x0018fcb8. Replaces the oldest sample with `v` and recomputes the mean
// over the samples seen so far, up to nSlots.
void average_record(Average *a, float v);

// 0x0018fd50. Fills the ring with `v`, sets the sample count to zero and
// the total to match a full ring. The mean and the slot index are left
// alone.
void average_reset(Average *a, float v);

// 0x0018fda0, which AIEngineSound's ComputeRPMPitchShift calls. The same,
// but the ring counts as full and the mean is `v`.
void average_flush(Average *a, float v);

// 0x0018fdf8, new in retail, which nothing calls. The newest sample, or 0
// before the first.
float average_get_last_value(const Average *a);

// Inline: fAverage, and fTotal.
float average_get_value(const Average *a);
float average_get_total(const Average *a);

// 40 bytes on the disc.
typedef struct PidError {
    Average aIntegral;     // 0
    Average aDerivative;   // 16
    float   fCurrentError; // 32
    float   fPreviousError;// 36
} PidError;

#ifndef AVERAGE_NO_ASSERT
typedef char pid_error_layout_check[
    (sizeof(void *) != 4
     || (offsetof(PidError, aDerivative) == 16
         && offsetof(PidError, fCurrentError) == 32
         && offsetof(PidError, fPreviousError) == 36
         && sizeof(PidError) == 40)) ? 1 : -1];
#endif

// Inline everywhere (PsychoDriver's constructor news three, 0x00139808 ..
// 0x00139834): the two Averages, then both errors zero.
PidError *pid_error_init(PidError *p, int32_t integralSlots,
                         int32_t derivativeSlots);

// 0x0013ad28. Both Averages' destructors with flags 2, the derivative's
// first, then the PidError itself when bit 0 of `flags` is set.
void pid_error_destroy(PidError *p, int32_t flags);

// 0x0018ff30. Takes the new error and the time step: the integral records
// the trapezoid `dt * (prev + (err - prev) * 0.5)`, the derivative records
// `(err - prev) / dt`.
void pid_error_record(PidError *p, float err, float dt);

// 0x00190008. The current error becomes zero and the previous one `err`.
// Both Averages are reset -- to the current error, which is now zero, not
// to `err`.
void pid_error_reset(PidError *p, float err);

// 8 bytes on the disc.
typedef struct Linear {
    float m; // 0
    float b; // 4
} Linear;

// 0x00190050. The line through (x1, y1) and (x2, y2).
void linear_init(Linear *l, float x1, float y1, float x2, float y2);

// 0x00190070. m * x + b.
float linear_get_value(const Linear *l, float x);

#endif
