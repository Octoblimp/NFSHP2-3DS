# Average, PidError, Linear -- table.cpp's three filters

    table.cpp    0x0018fbf0 .. 0x00190080    Average, PidError, Linear
                 0x0013ad28                  PidError's destructor

These are three small classes. Like Table and Graph
(`docs/formats/car-graph.md`), they are header-inline. Their out-of-line
methods land in the run after `Graph::GetValue` and before
AICarController's constructor. Average's buffer names
`..\indep\src\table.cpp`, line 167 (the demo's said 120).

The port is `3DS Files/source/average.{c,h}`. It is cross-checked by
`tools/average_check.py` against `tools/src/average_test.c`, with the
retail image itself running in mipsemu as the oracle. Everything is ported.
The two `DoSnapshot`s (0x0018fe38, 0x0018ff98) came with the replay, TASKS
72c, and `tools/aisnap_check.py` checks them.

Retail made the Average smaller: 16 bytes with its three counters as
bytes, where the demo had 24 with words. PidError shrank with it, from 56
bytes to 40. Every owner but AIEngineSound news its Averages, and
PsychoDriver news its PidErrors too.

## Average, 16 bytes

A running mean over a ring of `nSlots` samples.

| Off | Field |
|----:|-------|
| 0 | nSlots, a byte |
| 1 | nCurrentSlot, a byte: where the next sample goes |
| 2 | nSamples, a byte: how many the mean is over, up to nSlots |
| 4 | fTotal |
| 8 | fAverage |
| 12 | pData: `nSlots` floats |

Owners, and each one's slot count:

| Owner | Slots |
|-------|-------|
| RealController (offset 40) | 8 |
| AICarController (580 and 692) | 10 and 5 |
| PsychoDriver, three PidErrors (604, 608, 612) | 15/5, 15/5, 6/3 |
| AIDriver | 5 |
| Player's JoystickPort | 10 |
| BeltMover | 30 |
| AIEngineSound (inline at 236) | 20 |

**The constructor** (0x0018fbf0) zeroes the index, the count, the total
and the mean. It stores the low byte of the slot count, then takes
`bMalloc(nSlots * 4, "..\indep\src\table.cpp", 167, 16)` by the whole
count and clears it with `bMemSet`. A ring of 256 slots or more keeps a
buffer of all of them and a count of the low byte: 300 keeps 44, and 256
keeps none.

**The destructor** (0x0018fc68) deletes the buffer, then the Average when
bit 0 of the flags is set.

**Record(v)** (0x0018fcb8) does five things in order:

1. If `nSamples < nSlots`, it counts one more sample.
2. It adds `v` to the total and stores that sum.
3. It takes the oldest sample (the slot at the index) off the total, then
   writes `v` into that slot.
4. It sets the mean to `total / nSamples`.
5. It stores the index's step as a byte, and wraps it to zero once that
   byte reaches `nSlots`. At an index of 255 the step's byte is already 0,
   so the wrap's test makes no difference there.

Two roundings happen in step 2 and step 3, in that order. At a total of
2^24 that is a different float from `total + (v - old)`, and the checker
has that case. The divide is the EE's `div.s`. A ring of no slots never
counts a sample, so every Record divides by zero and gets FLT_MAX with the
XOR of the signs. It also reads and writes the one word past its empty
buffer.

**Reset(v)** (0x0018fd50) fills the ring with `v` and sets the total to
`v * nSlots`. It sets the *count* to zero, and leaves the mean and the
index alone. The next Record then divides a whole ring's total by one. The
one caller, PidError::Reset, always passes zero, where that does no harm.

**Flush(v)** (0x0018fda0) fills the ring the same way, but the ring counts
as full: the mean is `v` and the count is `nSlots`. The index is left
alone. The one caller is AIEngineSound::ComputeRPMPitchShift.

**GetLastValue()** (0x0018fdf8) is new in retail, and nothing calls it.
It answers 0 before the first sample, else the slot before the index, or
the ring's last slot when the index is at 0.

## PidError, 40 bytes

| Off | Field |
|----:|-------|
| 0 | aIntegral (Average) |
| 16 | aDerivative (Average) |
| 32 | fCurrentError |
| 36 | fPreviousError |

**The constructor** is inline wherever a PidError is built. PsychoDriver's
three copies (from 0x00139808) news 40 bytes, constructs both Averages,
then stores zero into both errors.

**The destructor** (0x0013ad28, out in PsychoDriver's object) destroys the
derivative first, then the integral, both with flags 2. It then deletes the
PidError itself when bit 0 of the flags is set.

**Record(err, dt)** (0x0018ff30) moves the current error to the previous
one and stores `err` as the current one. With `delta = err - prev`:

- the integral records the trapezoid `dt * (prev + delta * 0.5)`;
- the derivative records `delta / dt`, which is the EE's divide for a zero
  step.

**Reset(err)** (0x00190008) stores zero as the current error and `err` as
the previous one. It then reads the current error back (`lwc1 $f20,32(s0)`)
and resets both Averages to that value, which is zero, not `err`.

## Linear, 8 bytes

`m` at 0 and `b` at 4.

- **Init(x1, y1, x2, y2)** (0x00190050): `m = (y2 - y1) / (x2 - x1)` by
  `div.s`, then `b = y1 - m * x1`.
- **GetValue(x)** (0x00190070): `m * x + b`, a multiply and an add, not
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
- the counters poked past full, as bytes over the count (253, 254 of 255)
  and into the slack, and a ring shrunk under a live index;
- a ring of forty through 130 random samples;
- rings of 300 and 256 slots, whose counts keep the low byte, with the
  index at 255;
- GetLastValue before any sample, through a wrap and at each index;
- every flag combination of both destructors;
- PidErrors with zero and negative steps;
- Linear through vertical, degenerate and wide lines.

The check gives 552 ops, 972 lines, 0 differ. Its mutation pass has 73
mutations: 72 caught and 1 equivalent (rec-wrap-byte: without the byte in
the wrap's test the two differ only at an index of 255, where the stored
step is 0 either way).

RealController's checker still runs the demo's image, whose Average names
line 120; its harness shows the port's 167 as 120.
