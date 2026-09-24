# Average, PidError, Linear -- table.cpp's three filters

    table.cpp    0x00187550 .. 0x00187928    Average, PidError, Linear
                 0x00138f28                  PidError's destructor

These are three small classes. Like Table and Graph
(`docs/formats/car-graph.md`), they are header-inline. Their out-of-line
methods land in the run after `Graph::GetValue` and before
AICarController's constructor. Average's buffer names
`..\indep\src\table.cpp`, line 120.

The port is `3DS Files/source/average.{c,h}`. It is cross-checked by
`tools/average_check.py` against `tools/src/average_test.c`, with the image
itself running in mipsemu as the oracle. Everything is ported except the
two `DoSnapshot`s (0x00187730, 0x00187860), which wait on ReplaySnapshot.

## Average, 24 bytes

A running mean over a ring of `nSlots` samples.

| Off | Field |
|----:|-------|
| 0 | nSlots |
| 4 | nCurrentSlot: where the next sample goes |
| 8 | nSamples: how many the mean is over, up to nSlots |
| 12 | fTotal |
| 16 | fAverage |
| 20 | pData: `nSlots` floats |

Owners, and each one's slot count:

| Owner | Slots |
|-------|-------|
| RealController (offset 40) | 8 |
| AICarController | 10 and 5 |
| PsychoDriver, three PidErrors | 15/5, 15/5, 6/3 |
| AIDriver | 5 |
| Player's JoystickPort | 10 |
| BeltMover | 30 |
| AIEngineSound | 60 |

**The constructor** (0x00187550) zeroes the index, the count, the total and
the mean. It stores `nSlots`, then takes `bMalloc(nSlots * 4, "..\indep\src\
table.cpp", 120, 16)` and clears it with `bMemSet`.

**The destructor** (0x001875c8) deletes the buffer, then the Average when
bit 0 of the flags is set.

**Record(v)** (0x00187618) does five things in order:

1. If `nSamples < nSlots`, it counts one more sample.
2. It adds `v` to the total and stores that sum.
3. It takes the oldest sample (the slot at the index) off the total, then
   writes `v` into that slot.
4. It sets the mean to `total / nSamples`.
5. It steps the index, and wraps it to zero once `index + 1` reaches
   `nSlots`.

Two roundings happen in step 2 and step 3, in that order. At a total of
2^24 that is a different float from `total + (v - old)`, and the checker
has that case. The divide is the EE's `div.s`. A ring of no slots never
counts a sample, so every Record divides by zero and gets FLT_MAX with the
XOR of the signs. It also reads and writes the one word past its empty
buffer.

**Reset(v)** (0x00187698) fills the ring with `v` and sets the total to
`v * nSlots`. It sets the *count* to zero, and leaves the mean and the
index alone. The next Record then divides a whole ring's total by one. The
one caller, PidError::Reset, always passes zero, where that does no harm.

**Flush(v)** (0x001876e0) fills the ring the same way, but the ring counts
as full: the mean is `v` and the count is `nSlots`. The index is left
alone. The one caller is AIEngineSound::ComputeRPMPitchShift.

## PidError, 56 bytes

| Off | Field |
|----:|-------|
| 0 | aIntegral (Average) |
| 24 | aDerivative (Average) |
| 48 | fCurrentError |
| 52 | fPreviousError |

**The constructor** is inline wherever a PidError is built. PsychoDriver's
three copies (from 0x001376cc) construct both Averages, then store zero into
both errors.

**The destructor** (0x00138f28, out in PsychoDriver's object) destroys the
derivative first, then the integral, both with flags 2. It then deletes the
PidError itself when bit 0 of the flags is set.

**Record(err, dt)** (0x001877f8) moves the current error to the previous
one and stores `err` as the current one. With `delta = err - prev`:

- the integral records the trapezoid `dt * (prev + delta * 0.5)`;
- the derivative records `delta / dt`, which is the EE's divide for a zero
  step.

**Reset(err)** (0x001878b0) stores zero as the current error and `err` as
the previous one. It then reads the current error back (`lwc1 $f20,48(s0)`)
and resets both Averages to that value, which is zero, not `err`.

## Linear, 8 bytes

`m` at 0 and `b` at 4.

- **Init(x1, y1, x2, y2)** (0x001878f8): `m = (y2 - y1) / (x2 - x1)` by
  `div.s`, then `b = y1 - m * x1`.
- **GetValue(x)** (0x00187918): `m * x + b`, a multiply and an add, not
  fused.

## Checking it

    python tools/average_check.py
    python tools/average_check.py --mutate

Every fresh block is filled with 0xcd on both sides, plus 16 bytes of slack.
That makes the constructor's clear visible, and gives a ring of no slots the
same junk to read past its end on both sides. The scenarios cover:

- a ring of eight through two wraps;
- the constructor over junk fields;
- rings of one slot and of none;
- Reset and Flush over a partly filled ring, then Records after them;
- the 2^24 ordering case;
- the counters poked past full, below zero and into the slack, and a ring
  shrunk under a live index;
- a ring of forty through 130 random samples;
- every flag combination of both destructors;
- PidErrors with zero and negative steps;
- Linear through vertical, degenerate and wide lines.
