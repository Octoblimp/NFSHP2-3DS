"""Cross-check 3DS Files/source/graph.c against a model of Graph.

Graph is the first of the two small prerequisites task 25 owes before Car:
four Car methods build one, and eleven other call sites across PhysicsCar,
MellowMover, Mellovator, the AI controller, the belt mover, the analog
scanner and the preview comet read one.

It is two methods and eight bytes, and it would be dull except that four
of its decisions are easy to transcribe wrongly and none of them is
visible in the shape of the code:

**The bracket on a segment is half-open, and not the way round you would
guess.** `p[i].x <= x` is a `c.le.s` at 0x001874c4 and `x < p[i+1].x` is a
`c.lt.s` at 0x001874d8, so a sample landing exactly on an interior knee
belongs to the segment that STARTS there, and takes a blend of 0 rather
than a blend of 1 off the segment before it. Turning either test round
changes which two knees the answer comes from.

**The interpolation divides before it multiplies.** 0x0018752c is
`div.s; mul.s; add.s`, i.e. `(x - p[i].x) / dx * dy`. Writing the
algebraically identical `(x - p[i].x) * dy / dx` rounds once in a
different place, and the transcript carries a fixture where that is a
different float.

**The degenerate arm returns the midpoint.** When two knees are closer
together in x than 9.99999997e-07, 0x0018750c multiplies dy by 0.5 and
adds p[i].y -- the average of the two y values, not either one of them.

**Fewer than two points reads p[0] without checking there is one.** The
`slti v0,v1,2` at 0x00187454 falls straight through to `lwc1 $f0,4(a0)`.
A Graph over an empty array reads off the front of it: a real
out-of-bounds read in the shipped game, the same flavour as
`Table::GetValue`'s and `DriveTarget::GetAngle`'s. The transcript
exercises n = 1 rather than n = 0, because a model and a harness can agree
about p[0] and cannot agree about whatever is in front of an array.

The epsilon comes out of the ELF by address rather than being copied from
the header, so a typo in `GRAPH_EPSILON` diffs instead of the two files
agreeing with each other.

    python tools/graph_check.py
    python tools/graph_check.py --mutate
    python tools/graph_check.py --dump out/graph
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import bmath_check
import bvector_check

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/graph_test.c",
    "3DS Files/source/graph.c",
]

GH = "3DS Files/source/graph.h"
GC = "3DS Files/source/graph.c"

PTR = 8                       # the host, not the port
SLACK = PTR - 4

f32 = bmath_check.f32
bits = bmath_check.bits
fadd = bvector_check.fadd
fsub = bvector_check.fsub
fmul = bvector_check.fmul
fdiv = bvector_check.fdiv
fabs32 = bvector_check.fabs32

# ------------------------------------------------------------- the image

# gp is 0x00328bf0 and GetValue loads its epsilon with `lwc1 $f6,-30256(gp)`.
GP = 0x00328bf0
EPS_ADDR = GP - 30256
assert EPS_ADDR == 0x003215c0, hex(EPS_ADDR)
EPS = bits(struct.unpack("<I", bmath_check.ELF.read(EPS_ADDR, 4))[0])

# 0x001874b4: `lui at,0x3f00`, built in the instruction rather than loaded.
HALF = bits(0x3f000000)

# --------------------------------------------------------------- output

OUT = []


def emit(s):
    OUT.append(s)


def g9(x):
    return "%.9g" % x


# ---------------------------------------------------------------- model


def graph_get_value(points, n, x):
    """Graph::GetValue, 0x00187450, arm by arm."""
    x = f32(x)

    # 0x00187454  slti v0,v1,2
    if n < 2:
        return points[0][1]

    # 0x00187468  c.le.s $f5,$f0   -- x <= p[0].x
    if x <= points[0][0]:
        return points[0][1]

    # 0x00187488  c.le.s $f0,$f5   -- p[n-1].x <= x
    if points[n - 1][0] <= x:
        return points[n - 1][1]

    i = 0
    while i < n - 1:
        # 0x001874c4  c.le.s, inclusive on the left
        # 0x001874d8  c.lt.s, exclusive on the right
        if points[i][0] <= x and x < points[i + 1][0]:
            dx = fsub(points[i + 1][0], points[i][0])
            dy = fsub(points[i + 1][1], points[i][1])

            # 0x001874fc  c.lt.s $f6,$f1  -- eps < |dx|, strict
            if EPS < fabs32(dx):
                # 0x0018752c  div.s ; mul.s ; add.s
                return fadd(points[i][1],
                            fmul(fdiv(fsub(x, points[i][0]), dx), dy))
            # 0x0018750c  mul.s dy,0.5 ; add.s
            return fadd(points[i][1], fmul(dy, HALF))
        i += 1

    # 0x00187524  lwc1 $f0,4(a0) -- p[0].y, not p[n-1].y
    return points[0][1]


# -------------------------------------------------------------- scenarios

# Every fixture float is its own decimal literal on both sides. Nothing
# here is computed from another fixture float, so the two sides cannot
# disagree about the inputs -- only about what Graph does with them.


def run(tag, points, n, xs):
    emit("[%s] n %d" % (tag, n))
    for j in range(len(points)):
        emit("  p%d %s %s" % (j, g9(points[j][0]), g9(points[j][1])))
    for x in xs:
        # The label is the float32, not the Python double it was spelled
        # as: the harness prints the value it actually holds, and a label
        # that disagreed would be a diff about printf rather than about
        # Graph.
        emit("  at %-14s -> %s"
             % (g9(f32(x)), g9(graph_get_value(points, n, x))))


def ramp():
    return [(f32(0.0), f32(0.0)), (f32(1.0), f32(10.0)),
            (f32(2.0), f32(30.0)), (f32(4.0), f32(-10.0))]


def model():
    del OUT[:]

    emit("[layout]")
    # Eight on the PS2. On this host the pointer forces its own
    # alignment on the record, so the int32 at the end is followed by
    # tail padding -- which is why this is a round-up and not the usual
    # one slack term per pointer.
    emit("sizeof Graph %d" % (((PTR + 4 + PTR - 1) // PTR) * PTR))
    emit("off pPoints 0")
    emit("off NumPoints %d" % PTR)
    emit("eps %s" % g9(EPS))
    emit("eps bits %08x" % struct.unpack("<I", struct.pack("<f", EPS))[0])
    emit("half %s" % g9(HALF))

    # Every arm of the walk, on a curve whose segments have different
    # slopes and one that goes back down.
    p = ramp()
    run("ramp", p, 4,
        [-5.0, -0.0000001, 0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 3.999,
         4.0, 4.0000005, 100.0])

    # The knee tests, spelled out. 1.0 and 2.0 are interior knees, so each
    # belongs to the segment starting there -- the answer is that knee's
    # own y, reached through the divide with a numerator of exactly zero
    # rather than through an early-out.
    run("knees", p, 4, [1.0, 2.0])

    # Fewer than two points. n = 1 rather than n = 0: both sides can agree
    # about p[0], and neither can agree about what is in front of the
    # array.
    run("one point", [(f32(7.0), f32(3.25))], 1, [-1.0, 7.0, 99.0])

    # Two points is the smallest real curve.
    run("two points", [(f32(-2.0), f32(1.0)), (f32(2.0), f32(-3.0))], 2,
        [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0])

    # A segment narrower than the epsilon: the answer is the midpoint of
    # the two y values, and neither endpoint.
    tight = [(f32(0.0), f32(0.0)),
             (f32(1.0), f32(4.0)),
             (f32(1.0000005), f32(6.0)),
             (f32(3.0), f32(8.0))]
    run("tight", tight, 4, [0.5, 1.0, 1.00000025, 1.0000003, 2.0])

    # dx exactly at the epsilon. The test is strict, so this is the
    # midpoint arm too -- one ulp wider and it is not. The pair is spelled
    # at a magnitude where the epsilon is exactly representable as a
    # difference: at zero it is, and near 1.0 it is not.
    at_eps = [(f32(-1.0), f32(0.0)),
              (f32(0.0), f32(2.0)),
              (f32(9.99999997e-07), f32(6.0)),
              (f32(1.0), f32(8.0))]
    run("dx at eps", at_eps, 4,
        [-0.5, 0.0, 5e-07, 9.9e-07, 9.99999997e-07, 0.5])

    # Two knees at exactly the same x: dx is 0, which is inside the
    # epsilon, so the midpoint again -- and a zero divide is never
    # reached.
    same = [(f32(0.0), f32(0.0)),
            (f32(1.0), f32(4.0)),
            (f32(1.0), f32(10.0)),
            (f32(2.0), f32(12.0))]
    run("same x", same, 4, [0.5, 1.0, 1.5])

    # The divide's rounding, on purpose. Along a segment whose dy does not
    # divide evenly, (x - x0) / dx * dy and (x - x0) * dy / dx are
    # different floats, which is what pins the order of the two
    # operations.
    order = [(f32(0.0), f32(0.0)),
             (f32(3.0), f32(7.0)),
             (f32(10.0), f32(1.0))]
    run("order", order, 3,
        [1.0, 1.1000000238418579, 2.0, 2.9000000953674316,
         3.0, 5.0, 7.0, 9.0])

    # An unsorted array. The two early-outs bracket x against p[0] and
    # p[n-1], and then no segment contains it, so the walk falls off the
    # end and returns p[0].y -- not the last point's, and not the
    # nearest.
    unsorted = [(f32(0.0), f32(100.0)),
                (f32(8.0), f32(1.0)),
                (f32(2.0), f32(2.0)),
                (f32(10.0), f32(3.0))]
    run("unsorted", unsorted, 4, [1.0, 5.0, 9.0])

    # Negative x, so the compares are not all in the same quadrant.
    neg = [(f32(-8.0), f32(-4.0)),
           (f32(-4.0), f32(2.0)),
           (f32(-1.0), f32(-6.0)),
           (f32(0.0), f32(0.0))]
    run("negative", neg, 4, [-9.0, -8.0, -6.0, -4.0, -2.5, -1.0, -0.5, 0.0])

    # A flat segment: dy is 0, dx is wide, and the divide still runs.
    flat = [(f32(0.0), f32(5.0)),
            (f32(10.0), f32(5.0)),
            (f32(20.0), f32(9.0))]
    run("flat", flat, 3, [0.0, 5.0, 10.0, 15.0, 20.0])

    # NumPoints smaller than the array. The three early-outs and the walk
    # all read n, so the tail is invisible -- including a tail whose x
    # would have bracketed the sample.
    run("short count", p, 2, [-1.0, 0.5, 1.0, 1.5, 3.0])

    # The count's width, stored and read back without a lookup. Nothing
    # else in the transcript can tell a 32-bit NumPoints from a 16-bit one
    # -- the offsets and the sizeof are the same either way on a host whose
    # pointer forces the alignment, and no curve here has more than four
    # knees. These do not index anything; they only prove the field is
    # wide enough to hold them.
    emit("[count width] n 0")
    for c in (70000, -70000, 32768, 2147483647, -2147483648):
        emit("  store %-12d -> %d" % (c, c))

    # The first segment degenerate, and the sample sitting exactly on the
    # first knee. The low early-out is `x <= p[0].x`, a c.le.s: it fires
    # and the answer is p[0].y. Made strict, it does not fire, and the
    # walk then skips segment 0 (whose right edge is the same x), lands on
    # segment 1 and returns p[1].y instead. Everywhere else the two agree,
    # because a strict test that misses lands on a segment whose numerator
    # is exactly zero and interpolates back to the same point -- so it
    # takes a duplicate x at the FRONT of the array to separate them.
    dup_front = [(f32(1.0), f32(2.0)),
                 (f32(1.0), f32(8.0)),
                 (f32(3.0), f32(10.0))]
    run("dup front", dup_front, 3, [0.0, 1.0, 2.0, 3.0, 4.0])

    # dx one ulp above the epsilon: 0x358637be against the image's
    # 0x358637bd. The real code divides, an epsilon one ulp higher takes
    # the midpoint. Spelled from zero, where the difference of the two
    # knees is exactly the literal.
    ulp_over = [(f32(-1.0), f32(0.0)),
                (f32(0.0), f32(2.0)),
                (f32(1.00000011e-06), f32(6.0)),
                (f32(1.0), f32(8.0))]
    run("dx one ulp over", ulp_over, 4, [0.0, 5e-07, 1.0000001e-06])

    return list(OUT)


# ---------------------------------------------------------------- running

# A mutation can turn the walk into a loop with no exit. With no deadline
# here that mutant spins until something kills it and stalls the whole
# pass rather than being counted; the harness runs in well under a second.
HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line)
    return bad


# -------------------------------------------------------------- mutations

MUTATIONS = [
    # -- the layout ---------------------------------------------------------
    ("gr-count-is-int16", GH,
     "    int32_t         NumPoints; // 4",
     "    int16_t         NumPoints; // 4" + NL + "    int16_t         _pad;"),

    # -- the early-outs -----------------------------------------------------
    ("gr-few-points-is-1", GC,
     "    if (n < 2) return p[0].y;",
     "    if (n < 1) return p[0].y;"),
    ("gr-few-points-returns-x", GC,
     "    if (n < 2) return p[0].y;",
     "    if (n < 2) return p[0].x;"),
    ("gr-low-strict", GC,
     "    if (x <= p[0].x) return p[0].y;",
     "    if (x < p[0].x) return p[0].y;"),
    ("gr-high-strict", GC,
     "    if (p[n - 1].x <= x) return p[n - 1].y;",
     "    if (p[n - 1].x < x) return p[n - 1].y;"),
    ("gr-high-returns-first", GC,
     "    if (p[n - 1].x <= x) return p[n - 1].y;",
     "    if (p[n - 1].x <= x) return p[0].y;"),
    ("gr-high-off-by-one", GC,
     "    if (p[n - 1].x <= x) return p[n - 1].y;",
     "    if (p[n - 2].x <= x) return p[n - 2].y;"),

    # -- the walk -----------------------------------------------------------
    ("gr-walk-runs-to-n", GC,
     "    for (i = 0; i < n - 1; i++) {",
     "    for (i = 0; i < n; i++) {"),
    ("gr-left-strict", GC,
     "        if (p[i].x <= x && x < p[i + 1].x) {",
     "        if (p[i].x < x && x < p[i + 1].x) {"),
    ("gr-right-inclusive", GC,
     "        if (p[i].x <= x && x < p[i + 1].x) {",
     "        if (p[i].x <= x && x <= p[i + 1].x) {"),
    ("gr-fallthrough-last", GC,
     "    return p[0].y;" + NL + "}",
     "    return p[n - 1].y;" + NL + "}"),

    # -- the arithmetic -----------------------------------------------------
    ("gr-dx-reversed", GC,
     "            float dx = p[i + 1].x - p[i].x;",
     "            float dx = p[i].x - p[i + 1].x;"),
    ("gr-dy-reversed", GC,
     "            float dy = p[i + 1].y - p[i].y;",
     "            float dy = p[i].y - p[i + 1].y;"),
    ("gr-eps-inclusive", GC,
     "            if (fabsf(dx) > GRAPH_EPSILON) {",
     "            if (fabsf(dx) >= GRAPH_EPSILON) {"),
    ("gr-eps-no-abs", GC,
     "            if (fabsf(dx) > GRAPH_EPSILON) {",
     "            if (dx > GRAPH_EPSILON) {"),
    ("gr-eps-is-zero", GH,
     "#define GRAPH_EPSILON 9.99999997e-07f",
     "#define GRAPH_EPSILON 0.0f"),
    # Not `1e-6f`: that rounds to 0x358637bd, which is the image's own
    # value bit for bit, so the mutation was a no-op and could never have
    # been caught. One ulp up is the smallest change that is a change.
    ("gr-eps-one-ulp-up", GH,
     "#define GRAPH_EPSILON 9.99999997e-07f",
     "#define GRAPH_EPSILON 1.00000011e-06f"),
    ("gr-mul-before-div", GC,
     "                return p[i].y + (x - p[i].x) / dx * dy;",
     "                return p[i].y + (x - p[i].x) * dy / dx;"),
    ("gr-blend-from-right", GC,
     "                return p[i].y + (x - p[i].x) / dx * dy;",
     "                return p[i + 1].y + (x - p[i].x) / dx * dy;"),
    ("gr-blend-numerator", GC,
     "                return p[i].y + (x - p[i].x) / dx * dy;",
     "                return p[i].y + (p[i + 1].x - x) / dx * dy;"),
    ("gr-degenerate-left", GC,
     "            return p[i].y + dy * 0.5f;",
     "            return p[i].y;"),
    ("gr-degenerate-right", GC,
     "            return p[i].y + dy * 0.5f;",
     "            return p[i + 1].y;"),
    ("gr-degenerate-quarter", GC,
     "            return p[i].y + dy * 0.5f;",
     "            return p[i].y + dy * 0.25f;"),

    # -- the constructor ----------------------------------------------------
    ("gr-init-drops-count", GC,
     "    g->NumPoints = count;",
     "    g->NumPoints = 0;"),
    ("gr-init-count-minus-one", GC,
     "    g->NumPoints = count;",
     "    g->NumPoints = count - 1;"),
]

EQUIVALENT = {
    # `n < 2` widened to `n < 1`. The two differ only at n == 1, and at
    # n == 1 every path out of the function returns p[0].y: p[n-1] IS
    # p[0], so the high early-out returns it, the low one returns it, and
    # a walk with a bound of n - 1 == 0 falls straight through to the
    # `return p[0].y` at the end. No input can separate them.
    "gr-few-points-is-1":
        "at n == 1 the high early-out, the low early-out and the "
        "fallthrough all return p[0].y, because p[n-1] is p[0]",

    # The walk's bound. Reaching i == n - 1 at all would need the loop to
    # find no segment containing x, and it always finds one: past the low
    # early-out x > p[0].x, so p[0].x <= x; past the high one
    # p[n-1].x > x, so p[n-1].x <= x is false. A predicate true at 0 and
    # false at n-1 flips somewhere, and that flip IS a match. The extra
    # iteration is unreachable, out-of-order array or not.
    "gr-walk-runs-to-n":
        "the walk always matches at or before i == n - 2, so the extra "
        "iteration is unreachable",

    # The same argument from the other end: the `return p[0].y` after the
    # loop is dead code. Changing what it returns cannot be observed.
    # (On hardware there is no NaN to reach it with either -- the EE's FPU
    # has no NaN or infinity at all.)
    "gr-fallthrough-last":
        "the post-loop return is unreachable for the same reason, so what "
        "it returns cannot be observed",

    # fabsf around dx. The arm is only reached when p[i].x <= x and
    # x < p[i+1].x, which makes p[i].x < p[i+1].x, which makes dx
    # positive -- and exactly positive, because subtracting two floats
    # that close is exact. The absolute value is a no-op every time the
    # code runs.
    "gr-eps-no-abs":
        "the arm is only reached when p[i].x < p[i+1].x, so dx is already "
        "positive and fabsf is a no-op",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="graph_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")

        # The ported sources are CRLF and the tools are LF, so a multi-line
        # pattern written with bare newlines misses every time against a
        # source file -- silently, as a pattern that is not found rather
        # than as a mutant that survived.
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-32s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="graph_test")
                except SystemExit:
                    print("  %-32s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-32s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-32s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-32s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-32s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-32s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # A pattern that is not found is dropped from the denominator below, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    return 1 if (holes or missing) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="graph_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ"
          % (sum(1 for line in lines if line.startswith("[")),
             len(harness), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
