# Car data (chunks `0x00034600` and `0x00034601`)

Retail's carinfo.cpp: the loader slot (16) that takes GLOBALB.BUN's two
car data chunks, and the 64 acceleration tables made from them at boot.
The port has it in `carinfo.{c,h}`; the records themselves are
`cartypeinfo.{c,h}` (car-type-info.md). Retail's ELF is stripped, so the
addresses below are retail's with the demo's beside them, and the names
are the demo's.

| | retail | demo |
|---|---:|---:|
| `LoaderCarInfo(bChunk *)` | 0x00187f98 | 0x0017fff8 |
| `UnloaderCarInfo(bChunk *)` | 0x00188128 | 0x00180180 |
| `AccelerationTable::AccelerationTable()` | 0x00188d68 | 0x00180d00 |
| `GetAccelerationTable(CarType)` | 0x00188dd8 | 0x00180d70 |
| `MakeAccelerationTable(Table *, CarTypeInfo *)` | 0x00188df0 | 0x00180d88 |
| `_GLOBAL_$I$FindCarLanguageInfo__F7CarType` | 0x001890c8 | 0x00181060, `__CTOR_LIST__` [35] |
| `TheCarTypeAccelerationTable[64]` | 0x0030daf0 | |
| `CarTypeInfoArray`, `SkinInfoTable`, `NumSkinInfo` | gp-20616, -20612, -20608 | |

## The chunks on the disc

GLOBALB.BUN has one of each, cars first:

| file offset | id | size | |
|---:|---|---:|---|
| 0x086b80 | 0x00034600 | 88072 | 8 bytes of pad, then 64 `CarTypeInfo` of 1376 |
| 0x09c390 | 0x00034601 | 15040 | 235 `SkinInfo` of 64 |

The records start at the first 16-byte boundary past the header plus 7,
which on the disc is the chunk's payload plus 8.

## The loader and the unloader

```
LoaderCarInfo(chunk)
    if chunk->id == 0x34600:
        CarTypeInfoArray = (chunk + 23) & ~15
        for type in 0..63:
            MakeAccelerationTable(GetAccelerationTable(type),
                                  &CarTypeInfoArray[type])
        if TheDemoDiscManager.bActive:          0x002effe0
            for each type not on the demo's twelve:
                its GeometryFilename[0] = 0
        return 1
    if chunk->id == 0x34601:
        SkinInfoTable = chunk + 8
        NumSkinInfo = chunk->size >> 6           unsigned
        return 1
    return 0

UnloaderCarInfo(chunk)
    0x34600: CarTypeInfoArray = 0;               return 1
    0x34601: SkinInfoTable = 0, NumSkinInfo = 0; return 1
    otherwise return 0
```

- **The records are the chunk's own bytes.** Nothing is copied, so the
  bundle must stay resident; on the 3DS the UI already holds GLOBALB for
  the life of the program, and main.c's `loadGlobalCarInfo` offers slot
  16 its chunks there at boot, in the file's order.
- **The tables are not unloaded.** The unloader zeroes the three globals
  and leaves the 64 tables as the last load made them.
- **The skin count is the size's shift, unsigned.** A size of 0xffffffc0
  counts 0x3ffffff skins, and 63 bytes count none.
- **The demo disc is left out**, as everywhere in the port.

## AccelerationTable

148 bytes: `float Data[32]` and then the `Table` over them. The
constructor builds the Table first, over its own 32 entries from 0 to
55.555557 (0x425e38e4, gp-30180: 200 km/h in metres a second), and then
fills the entries: 4.0 in Data[30] down to Data[0], and 0 in Data[31].
The static constructor runs it over each of the 64, first to last. (The
demo's made 66.)

`GetAccelerationTable(type)` is `&TheCarTypeAccelerationTable[type].mTable`
with no bounds check. Its other callers are GetTopSpeed (0x00231338) and
CalculateMaxAcceleration (0x001cce50).

## MakeAccelerationTable

```
MakeAccelerationTable(t, ct)
    dt, ei = &ct->DriveTrain, &ct->Engine
    s      = dt->TorqueSplit
    drive  = (1 - s) * dt->FinalDrive[0] + s * dt->FinalDrive[1]
    radius = (1 - s) * ct->Wheels[0].Radius + s * ct->Wheels[2].Radius
    mass   = ct->Body.Mass
    CalculateShiftPoints(dt, ei, up, down, gShiftUpDetune)
    torque = Table(ei->TorqueCurveTable, 9, ei->IdleRPM, ei->MaxRPM)
    samples = bMalloc(404, "..\indep\src\carinfo.cpp", 815, 16)

    speed = rpm = 0, n = 0, gear = FIRST_GEAR (2)
    if up[2] <= 0:
        gear = 3
        if !(gear < NumGears + 2): goto sampled
    loop:
        speed += 1.388889                         5 km/h, gp-30172
        a = torque(rpm) * drive * GearRatios[gear] / radius / mass
        samples[n++] = a
        if !(speed < 138.88890): break            500 km/h, gp-30176
        rpm = speed / radius * drive * GearRatios[gear] * 9.549304
        if up[gear] <= rpm:
            gear++
            if !(gear < NumGears + 2): break
sampled:
    samples[n - 1] = 0
    accel = Table(samples, n, 0, speed)
    for i in 0..t->NumEntries - 1:                the count read each pass
        t->Data[i] = accel(i * speed / (t->NumEntries - 1))
    t->SetMinMax(0, speed)
```

- **The torque is the RPM the step before left.** The speed step sits in
  GetValue's delay slot, so each sample takes the torque at the last
  step's RPM and the gear's ratio now: the first sample in a new gear has
  the old gear's RPM.
- **The shift points are this car's.** CalculateShiftPoints writes up[2]
  to up[NumGears] scaled by gShiftUpDetune (the drivetrain's global,
  0.95, not a constant), and then the top gear's, MaxRPM unscaled, at
  NumGears + 1 -- at 2 when NumGears is below 1. So the walk leaves the
  top gear at the red line, and every up point it reads was written by
  this call. (The six-gear cars were once thought to read a stale up[7];
  tools/carinfo_check.py runs every load under seven stack fills, and no
  table moves.)
- **At most 101 samples.** The speeds are the same sums of the step for
  every car: the 100th is 138.888733 and the 101st 140.277618, the first
  past the cap. The 404 bytes are `cvt.w.s` of 100.0, plus one, times
  four.
- **The last sample is zeroed**, so a table ends at 0 at its top speed,
  and its range is 0 to the last speed the walk reached.
- **The allocation is never freed.** 64 of them, 25856 bytes, once, at
  boot. The port keeps the leak.
- **No samples.** With at most one gear and a MaxRPM at or below 0 the
  start skips past the top gear and n is 0: the image zeroes the word
  before the allocation, bMalloc's own, and builds a Table of no entries.
  No record on the disc gets there; the port returns with `t` as it was.

## InitCarInfo and the car names

InitializeEverything runs InitCarInfo (`0x00188d08`) straight after
LoadGlobalChunks. For each of the 64 types it sets the record's
`pCarSpecs` (byte 1368) to FindCarLanguageInfo(type) (`0x00187e80`), a
row of the CarLanguageInfo table at `0x0030d578`: 50 rows of 28 bytes,
the type and then six translated-string ids (`car-type-info.md` has the
fields). The search answers the first row whose type matches, and the
first row when none does; that row is type -1's, the Corvette's ids
again. Types 49 to 63 have no row of their own.

It then tail-calls `0x00188ca8`, which asks GetNumSkins (`0x001884b8`)
of every type whose GeometryFilename is not empty and drops each answer.
The port leaves that out.

## Checked by

`tools/carinfo_check.py` runs the static constructor, the loader, the
unloader, GetAccelerationTable, MakeAccelerationTable,
FindCarLanguageInfo (every type from -3 to 69 and three far ones, with
the row's seven words) and InitCarInfo out of the retail
image in RetailEmu over GLOBALB's own two chunks at each word alignment,
the 64 records changed type by type (gear counts 0 to 6 and -1, the split,
red lines out of reach, narrow engines, rising, signed and flat torque
curves, odd ratios, the mass, the radius, the interpolated up points, and
an RPM that lands on its up point exactly), under several drivetrain
globals and stack fills, and chunks of other ids and skin sizes. It diffs
the globals, every allocation and the 64 tables against the port.
