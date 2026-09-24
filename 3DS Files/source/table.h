// table -- the Table class (ctor 0x00187268, GetValue 0x00187298,
// SetMinMax 0x001810b8, CalcIndexMultiplier 0x00181100,
// InverseLookup 0x00187330).
//
// A one-dimensional lookup table over an evenly spaced argument range, with
// linear interpolation between entries. The engine's torque curve and its
// engine-braking curve are both Tables over RPM; the suspension and the
// tyre model use them too.
//
// Table is not an object file of its own -- it is a header-inline class, so
// its five methods are emitted into whichever compilation unit used them.
// That is why the addresses above are scattered across 0x00181xxx and
// 0x00187xxx rather than forming a run.
//
// The table does NOT own its entries. pTable points into the *Info struct
// that was handed to the constructor (EngineInfo::TorqueCurveTable, and so
// on), which lives in the car type data. Nothing here copies or frees it.
//
// Layout from .mdebug, `Table (size=20)`, every offset re-derived from the
// loads in the listing. See docs/formats/car-engine.md.

#ifndef TABLE_H
#define TABLE_H

#include <stddef.h>
#include <stdint.h>

typedef struct Table {
    const float *pTable;         //  0
    int32_t      NumEntries;     //  4
    float        MinArg;         //  8
    float        MaxArg;         // 12
    float        IndexMultiplier;// 16
} Table;

#ifndef TABLE_NO_ASSERT
typedef char table_size_check[
    (sizeof(Table) == 20 + (sizeof(void *) - 4)
     && offsetof(Table, NumEntries)      == sizeof(void *) + 0
     && offsetof(Table, MinArg)          == sizeof(void *) + 4
     && offsetof(Table, MaxArg)          == sizeof(void *) + 8
     && offsetof(Table, IndexMultiplier) == sizeof(void *) + 12
     ) ? 1 : -1];
#endif

// 0x00181100. IndexMultiplier = (NumEntries - 1) / (MaxArg - MinArg).
// Called for its side effect by SetMinMax; there is no guard against
// MaxArg == MinArg or NumEntries == 0, and the original has none either.
void table_calc_index_multiplier(Table *t);

// 0x001810b8. Stores the range and recomputes the multiplier.
void table_set_min_max(Table *t, float minarg, float maxarg);

// 0x00187268. Stores the entries and the count, then SetMinMax.
void table_init(Table *t, const float *entries, int32_t n,
                float minarg, float maxarg);

// 0x00187298. Clamps the argument into [MinArg, MaxArg], scales it to a
// fractional index and interpolates. The last entry is returned exactly
// rather than interpolated against an entry one past the end.
float table_get_value(const Table *t, float arg);

// 0x00187330. The argument whose value is `value`: walks the entries for
// the first pair that straddles it and interpolates the index between
// them, as GetValue's inverse. An entry within 1e-6 of `value` answers its
// own index exactly; a value past every entry answers MaxArg's index.
//
// Two quirks kept. An exact hit on entry 0 returns the *entry*, p[0], not
// MinArg -- the listing moves $f2 into $f0 in the branch's delay slot and
// returns it. The two agree only when p[0] == MinArg, which is true of
// SteeringCurveData (0.0 over 0..1), the one table anything inverts.
// And a table that is not monotonic is walked to its first crossing
// rather than searched.
//
// RealDriver::DoSteering is its only caller in the image.
float table_inverse_lookup(const Table *t, float value);

#endif
