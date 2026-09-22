# Graph

A piecewise-linear curve over an array of `bVector2` knees sorted by x.
Two methods, eight bytes, and no object file of its own: like `Table` it is
a header-inline class, so its code is emitted into whichever compilation
unit used it — which is why `Graph::Graph` and `Graph::GetValue` sit at
`0x00187440` and `0x00187450`, immediately after `Table`'s five, rather
than in a `Graph.obj`.

Ported to `3DS Files/source/graph.{c,h}`. It is the first of the two small
prerequisites task 25 owes before `Car`.

## Who reads one

Fifteen call sites read a `Graph`, and sixteen build one:

| Caller | What the curve is |
|---|---|
| `Car::CalculateDraftFactor` | draft strength against distance |
| `Car::MaybeRumble` | rumble against speed |
| `Car::CalculateNewCatchupMultipliers` | catch-up against the gap |
| `Car::GetPostCollisionYawControlBoost` | yaw authority after a hit |
| `PhysicsCar::JumpStabilizer` | pitch correction in the air |
| `MellowMover::JumpStabilizer` | the same, for the arcade mover |
| `Mellovator::GetDerivative` | the force-feedback curve |
| `AICarController::GetGlueSpeed` | rubber-band speed |
| `AICarController::CalculateDistanceAndPositionBoost` | two curves |
| `BeltMover::SlideCoef` | slide against speed |
| `Scanner_Analog` | the analog stick response |
| `PreviewComet::Render` | three curves |

Four of those are `Car`'s, which is why this comes first.

## The record

```c
typedef struct Graph {
    const bVector2 *pPoints;   // 0
    int32_t         NumPoints; // 4
} Graph;                       // 8
```

Eight bytes on the PS2. `Graph::Graph` is four instructions —
`sw a1,0(a0); move v0,a0; jr ra; sw a2,4(a0)` — and it **aliases** the
array rather than copying it. Every one of the sixteen call sites hands it
a static `bVector2[]` in its own compilation unit, so the points outlive
the `Graph`; nothing here copies or frees them.

This is the first record in the port whose size assert needs a round-up
rather than the usual `+ (sizeof(void *) - 4)`. On a 64-bit host the
pointer forces eight-byte alignment on the whole record, so the `int32_t`
at the end is followed by four bytes of tail padding and `sizeof` comes out
16, not 12. The offsets are what the claim is really about and they are
exact on both, so the assert checks those directly and states the size as a
round-up to `sizeof(void *)`.

## GetValue, arm by arm

```c
if (n < 2)              return p[0].y;
if (x <= p[0].x)        return p[0].y;
if (p[n - 1].x <= x)    return p[n - 1].y;
for (i = 0; i < n - 1; i++)
    if (p[i].x <= x && x < p[i + 1].x) {
        dx = p[i + 1].x - p[i].x;
        dy = p[i + 1].y - p[i].y;
        if (fabsf(dx) > 9.99999997e-07f)
            return p[i].y + (x - p[i].x) / dx * dy;
        return p[i].y + dy * 0.5f;
    }
return p[0].y;
```

Four things are read off the listing rather than assumed, and each of them
is a different float if it is transcribed the obvious way instead.

**The bracket on a segment is half-open, and not the way round you would
guess.** `p[i].x <= x` at `0x001874c4` is a `c.le.s` and `x < p[i+1].x` at
`0x001874d8` is a `c.lt.s`. A sample landing exactly on an interior knee
therefore belongs to the segment that **starts** there and blends at 0,
rather than ending the segment before it and blending at 1. The answer is
the same either way while the curve is continuous — which is exactly why
the asymmetry is easy to get wrong and hard to notice.

**The interpolation divides before it multiplies.** `0x0018752c` is
`div.s; mul.s; add.s`: `(x - p[i].x) / dx * dy`. The algebraically
identical `(x - p[i].x) * dy / dx` rounds in a different place, and the
transcript carries a fixture where the two differ.

**The degenerate arm returns the midpoint.** When two knees are closer
together in x than the epsilon, `0x0018750c` is `mul.s dy,0.5` and then
`add.s p[i].y` — the average of the two y values, not either endpoint.

**Fewer than two points reads `p[0]` without checking there is one.**
`slti v0,v1,2` at `0x00187454` falls straight through to `lwc1 $f0,4(a0)`.
A `Graph` over an empty array reads off the front of it: a real
out-of-bounds read in the shipped game, the same flavour as
`Table::GetValue`'s and `DriveTarget::GetAngle`'s. Kept, and modelled.

## The epsilon

`lwc1 $f6,-30256(gp)` with `_gp` at `0x00328bf0` is `0x003215c0`, which
holds `0x358637bd` — `9.99999997e-07f`. The checker reads it out of the
ELF by address rather than copying it from the header, so a typo in
`GRAPH_EPSILON` shows as a diff rather than as two files agreeing with each
other.

Worth writing down, because it cost a mutation: **`1e-6f` is the same
float.** It rounds to `0x358637bd` exactly, so a mutation that replaces
the spelled-out constant with `1e-6f` is a no-op and could never be caught.
It was rewritten as one ulp up, `1.00000011e-06f` / `0x358637be`, which is
the smallest change that is a change.

## Two arms that cannot be reached

`0.5` is built with `lui at,0x3f00` rather than loaded, and there are three
separate `jr ra` sites that all return `p[0].y`. One of them — the
`blez v0` at `0x001874a4`, taken when `n - 1 <= 0` — is unreachable,
because `n >= 2` is already known by then. The port keeps the shape the
object has.

The `return p[0].y` after the loop is unreachable too, and that takes an
argument rather than an observation. Past the low early-out,
`x > p[0].x`, so `p[0].x <= x` holds. Past the high one, `p[n-1].x > x`,
so `p[n-1].x <= x` does not. A predicate that is true at index 0 and false
at index n-1 flips somewhere in between, and that flip **is** a match:
`p[i].x <= x` and `x < p[i+1].x`. The walk therefore always returns at or
before `i == n - 2`, whatever order the array is in. There is no NaN to
reach the fallthrough with either — the EE's FPU has no NaN or infinity at
all.

## Cross-check

```
python tools/graph_check.py            # 16 scenarios, 151 lines, 0 differ
python tools/graph_check.py --mutate   # 25 mutations, 21 caught, 4 equivalent
```

`tools/graph_check.py` models the class from the disassembly, not from the
C, and takes its float layer from `bvector_check` so the rounding is the
machine's and not Python's.

### The seven the first pass left

Two were real holes, four are equivalent, and one mutation was itself a
no-op.

**`gr-count-is-int16` — a real hole.** Narrowing `NumPoints` to sixteen
bits changes neither offset, and on a host whose pointer forces the
alignment it does not change `sizeof` either, so the layout scenario could
not see it; and no curve in the transcript has more than four knees, so no
lookup could. Killed by a scenario that stores counts the field has to be
32 bits wide to hold — 70000, 2147483647, -2147483648 — and reads them
straight back without indexing anything.

**`gr-low-strict` — a real hole, and a sharp one.** Making
`x <= p[0].x` strict does **not** change the answer anywhere the array is
ordinary: the early-out stops firing, but the walk then lands on segment 0
with a numerator of exactly zero and interpolates back to `p[0].y`. It
takes a **duplicate x at the front of the array** to separate them —
`{1, 2}, {1, 8}, {3, 10}` sampled at exactly 1.0. The real code returns 2
from the early-out; the strict version skips segment 0 (whose right edge is
the same x, so `x < p[1].x` fails), lands on segment 1, and returns 8.

**`gr-eps-1e-6f` — the mutation was the problem.** See above; rewritten as
`gr-eps-one-ulp-up` and caught by a segment whose dx is exactly
`0x358637be`.

#### The four that survive

Each is argued in the checker's `EQUIVALENT` dict rather than left as a
number in the tally, and the import asserts that every name there is a
mutation that exists.

* **`gr-few-points-is-1`** — `n < 2` narrowed to `n < 1`. The two differ
  only at `n == 1`, and at `n == 1` every path out of the function returns
  `p[0].y`: `p[n-1]` **is** `p[0]`, so the high early-out returns it, the
  low one returns it, and a walk bounded by `n - 1 == 0` falls straight
  through to the last return. No input can separate them.
* **`gr-walk-runs-to-n`** and **`gr-fallthrough-last`** — both rest on the
  unreachability argument above. The walk always matches at or before
  `i == n - 2`, so the extra iteration never runs and the post-loop return
  is dead code.
* **`gr-eps-no-abs`** — dropping the `fabsf`. The arm is only reached when
  `p[i].x <= x` and `x < p[i+1].x`, which makes `p[i].x < p[i+1].x`, which
  makes `dx` positive — and exactly positive, since subtracting two floats
  that close is exact. The absolute value is a no-op every time the code
  runs.
