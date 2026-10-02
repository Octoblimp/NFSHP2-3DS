// carinfo -- retail's carinfo.cpp: the loader and unloader of the two car
// data chunks in GLOBAL\GLOBALB.BUN, and the car types' acceleration
// tables. Decompiled in docs/formats/car-info.md.
//
//   LoaderCarInfo              0x00187f98  (the demo's 0x0017fff8)
//   UnloaderCarInfo            0x00188128  (0x00180180)
//   AccelerationTable's ctor   0x00188d68  (0x00180d00)
//   GetAccelerationTable       0x00188dd8  (0x00180d70)
//   MakeAccelerationTable      0x00188df0  (0x00180d88)
//   the static constructor     0x001890c8  (0x00181060)
//
// tools/carinfo_check.py runs each of them out of the retail image in
// RetailEmu, over GLOBALB's own chunks and made-up ones, and diffs the
// globals, the 64 tables and what MakeAccelerationTable allocates.

#ifndef CARINFO_H
#define CARINFO_H

#include <stdint.h>

#include "cartypeinfo.h"
#include "table.h"

// The two chunks. 0x34600 is the CarTypeInfo records, from the first
// 16-byte boundary past the header; 0x34601 is the SkinInfo records,
// straight after it.
#define CARINFO_CHUNK      0x00034600u
#define CARINFO_SKIN_CHUNK 0x00034601u

// Retail has 64 car types (the demo had 66): LoaderCarInfo's loop and the
// static constructor's both count 64, and GLOBALB's chunk holds 64.
#define CARINFO_NUM_TYPES 64

// 148 bytes in the image: the entries, then the Table over them.
typedef struct AccelerationTable {
    float Data[32];     //   0
    Table mTable;       // 128
} AccelerationTable;

// TheCarTypeAccelerationTable, 0x0030daf0: one per car type.
extern AccelerationTable TheCarTypeAccelerationTable[CARINFO_NUM_TYPES];

// AccelerationTable::AccelerationTable, 0x00188d68. The Table first, over
// its own 32 entries from 0 to 55.555557 (200 km/h in metres a second),
// then the entries: 4.0 in the first 31 and 0 in the last.
void acceleration_table_init(AccelerationTable *a);

// _GLOBAL_$I$FindCarLanguageInfo__F7CarType, 0x001890c8 (the demo's
// 0x00181060): the constructor over each of the 64, first to last.
void carinfo_static_init(void);

// GetAccelerationTable(CarType), 0x00188dd8: the type's Table, 148 bytes a
// type, with no bounds check. GetTopSpeed (0x00231338) and
// CalculateMaxAcceleration (0x001cce50) are its other callers.
Table *get_acceleration_table(int32_t type);

// MakeAccelerationTable(Table *, CarTypeInfo *), 0x00188df0.
//
// It walks the speed from 0 in steps of 1.388889 (5 km/h) and, gear by
// gear from first, takes the engine's torque at the RPM the last step left
// through the torque curve's Table and the drivetrain to an acceleration:
// torque * final drive * gear ratio / wheel radius / mass. The final drive
// and the radius are the front's and the rear's mixed by TorqueSplit. A
// gear changes up once the RPM reaches its up point from
// CalculateShiftPoints (scaled by gShiftUpDetune, 0.95), and the walk
// stops at 138.88889 (500 km/h) or past the top gear. Its samples, the
// last zeroed, make a Table from 0 to the last speed, which `t`'s entries
// then sample evenly; `t`'s range becomes that 0 to the last speed.
//
// The top gear's up point is the engine's MaxRPM, which CalculateShiftPoints
// puts at NumGears + 1, so the walk leaves the top gear at the red line.
// Every up point it reads is this car's.
//
// The samples go into a bMalloc of 404 bytes ("..\indep\src\carinfo.cpp",
// line 815, pool 16) that is never freed: 25856 bytes for the 64 types,
// once, at boot.
void make_acceleration_table(Table *t, const CarTypeInfo *ct);

// LoaderCarInfo, 0x00187f98. 0x34600 points CarTypeInfoArray at the
// records and makes each type's acceleration table; 0x34601 points
// SkinInfoTable straight past the header, and NumSkinInfo is the chunk's
// size over 64. Either answers 1. Any other chunk answers 0.
//
// Retail then, for an active demo disc (0x002effe0), clears the first
// byte of the GeometryFilename of every type not on the demo's list of
// twelve. The port leaves it out, as it leaves the demo disc out
// everywhere.
int loader_car_info(uint8_t *chunk);

// UnloaderCarInfo, 0x00188128. 0x34600 zeroes CarTypeInfoArray, 0x34601
// SkinInfoTable and NumSkinInfo; either answers 1. The acceleration tables
// keep what they were made with.
int unloader_car_info(uint8_t *chunk);

#endif
