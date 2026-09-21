"""Cross-check 3DS Files/source/cardriver.c against a model of CarDriver.

CarDriver is the fourth slice of task 25. It is the base of the driver
hierarchy -- RealDriver, PsychoDriver and NullDriver all derive from it --
and on its own it is an input record: a steering angle, three pedals, two
gears, a nitro flag, and the DriveTarget it steers through.

Most of its thirty-two out-of-line functions are empty virtual stubs, and
that is the object rather than a gap in the port. The transcript calls
every one of them anyway and checks that nothing moved, because a stub
and a missing function are the same thing at the call site and only one
of them is intentional.

Three things this transcript exists to pin down.

**SportGear is never initialised.** The DriveTarget constructor memsets
528 bytes, which stops exactly at Steering, and the stores that follow
cover every input except byte 548. The transcript constructs over two
different byte patterns and shows SportGear keeping both.

**The vtable pointer is at 556, after the data.** This image is built
with the old g++ ABI. Every class still to come in task 25 has the same
shape, and the instinct is to look for it at offset 0.

**MyDriveTarget is at offset 0**, which is the only reason SetTarget can
tail-call DriveTarget::operator= with a0 untouched and GetDriveTarget can
be `move v0,a0`. The transcript shows the aliasing rather than asserting
it.

DriveTarget's own 28 methods are *not* ported -- they are ~8.6 KB
reaching into Car, CarState and the collision predictor, and they are
their own slice. Its layout and its assignment operator are, because
CarDriver embeds one and copies it wholesale.

    python tools/cardriver_check.py
    python tools/cardriver_check.py --mutate
    python tools/cardriver_check.py --dump out/cardriver
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/cardriver_test.c",
    "3DS Files/source/cardriver.c",
]

CD = "3DS Files/source/cardriver.c"
CH = "3DS Files/source/cardriver.h"
DH = "3DS Files/source/drivetarget.h"

MAX_POINTS = 20


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def g9(x):
    return "%.9g" % x


# ------------------------------------------------------------------ layout

# CarDriver, from the .mdebug entry (size=560) and confirmed store by
# store in the constructor at 0x00134e40.
CARDRIVER_OFF = [
    ("MyDriveTarget", 0),
    ("Steering", 528),
    ("Throttle", 532),
    ("Brake", 536),
    ("EBrake", 540),
    ("DesiredGear", 544),
    ("SportGear", 548),
    ("NitroFlag", 552),
    ("_vtable", 556),
]
CARDRIVER_SIZE = 560

# DriveTarget, from the .mdebug entry (size=528). The element types are
# not in the dump; each came from an instruction, listed in drivetarget.h.
DRIVETARGET_OFF = [
    ("NumPoints", 0),
    ("Points", 16),
    ("CalculatedSpeed", 336),
    ("Route", 416),
    ("RoutePointNumber", 436),
    ("DrivingLine", 476),
    ("TType", 496),
    ("WhichPointIPicked", 500),
    ("WhichPointIPickedCalculationTime", 504),
    ("WhichPointIPickedTime", 508),
    ("Length", 512),
]
DRIVETARGET_SIZE = 528

DRIVETARGET_ARR = [
    ("Points", MAX_POINTS * 16, 16),
    ("CalculatedSpeed", MAX_POINTS * 4, 4),
    ("Route", MAX_POINTS * 1, 1),
    ("RoutePointNumber", MAX_POINTS * 2, 2),
    ("DrivingLine", MAX_POINTS * 1, 1),
]

VTABLE = 0x002924A8

# ---------------------------------------------------------------- emitting

OUT = []


def emit(s):
    OUT.append(s)


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


def s_layout():
    emit("[layout]")
    emit("sizeof CarDriver %d" % CARDRIVER_SIZE)
    emit("sizeof DriveTarget %d" % DRIVETARGET_SIZE)
    emit("sizeof Gear 4")
    for name, off in CARDRIVER_OFF:
        emit("off %s %d" % (pad("CarDriver." + name, 20), off))
    for name, off in DRIVETARGET_OFF:
        emit("off %s %d" % (pad("DriveTarget." + name, 20), off))
    for name, size, _ in DRIVETARGET_ARR:
        emit("arr %s %d" % (pad("DriveTarget." + name, 20), size))
    for name, _, stride in DRIVETARGET_ARR:
        emit("stride %s %d" % (name, stride))

    # Widths and signedness. The offsets do not pin either: a 32-bit
    # Steering with no pad after it leaves every following field exactly
    # where it was, and a uint8_t reads the same byte as an int8_t right
    # up until that byte has its top bit set.
    #
    #   Steering          sh / lhu        -> 2 bytes, unsigned
    #   NitroFlag         sw / lw         -> 4 bytes
    #   NumPoints         lb              -> 1 byte, signed
    #   Route[i]          lb  416(base+i) -> 1 byte, signed
    #   DrivingLine[i]    lb  476(base+i) -> 1 byte, signed
    #   RoutePointNumber  lh  436(base+2i)-> 2 bytes, signed
    for name, w in (("Steering", 2), ("NitroFlag", 4), ("NumPoints", 1),
                    ("Route", 1), ("DrivingLine", 1),
                    ("RoutePointNumber", 2)):
        emit("width %s %d" % (name, w))
    for name, sgn in (("Steering", 0), ("NumPoints", 1), ("Route", 1),
                      ("DrivingLine", 1), ("RoutePointNumber", 1)):
        emit("signed %s %d" % (name, sgn))
    emit("point pad %s" % g9(0.0))

    emit("alias 1")
    emit("alias get 1")


# --------------------------------------------------------- the constructor

def scribble(n, seed):
    return bytes((seed + i * 7 + 1) & 0xFF for i in range(n))


def s32(b):
    return struct.unpack("<i", b)[0]


def s_ctor():
    emit("[ctor]")

    mem = scribble(CARDRIVER_SIZE, 0)
    before = s32(mem[548:552])
    emit("sportgear before %d" % before)

    emit("vtable %08x" % VTABLE)
    emit("drivetarget zeroed 0")
    emit("steering 0")
    emit("throttle %s" % g9(0.0))
    emit("brake %s" % g9(0.0))
    emit("ebrake %s" % g9(0.0))
    emit("desiredgear 1")
    emit("nitro 0")
    # The constructor writes nothing to byte 548, so SportGear is still
    # whatever the allocation held.
    emit("sportgear after %d" % before)
    emit("sportgear unchanged 1")

    mem2 = scribble(CARDRIVER_SIZE, 99)
    before2 = s32(mem2[548:552])
    emit("second sportgear %d unchanged 1" % before2)
    emit("second desiredgear 1 nitro 0 steering 0")

    emit("fini vtable %08x" % VTABLE)
    emit("fini desiredgear 1")


# ------------------------------------------------------- the input record

BAMS = [0, 1, 0x4000, 0x8000, 0xC000, 0xFFFF]
PEDALS = [0.0, 1.0, 0.5, -1.0, 1e30, -0.0]
GEARS = [-1, 0, 1, 2, 6, 0x7FFFFFFF]
NITROS = [0, 1, 2, -1, 256, 12345, -70000]


def s_inputs():
    emit("[inputs]")

    for b in BAMS:
        # sh in, lhu out -- so the value round-trips as an unsigned 16-bit
        # number and a BAM past the half turn stays large and positive.
        emit("steering %d -> %d" % (b, b & 0xFFFF))

    for p in PEDALS:
        v = f32(p)
        emit("pedals %s %s %s" % (g9(v), g9(f32(-v)), g9(f32(v * 2.0))))

    for gr in GEARS:
        emit("gears %d %d" % (gr, -gr))

    # Four bytes written at 528, two read back: `lhu` keeps the low half.
    emit("poke32 %d" % (0xFEEDFACE & 0xFFFF))

    for n in NITROS:
        # `sw a1,552(a0)` -- the whole word, not narrowed to a bool.
        emit("nitro %d -> %d" % (n, n))

    emit("all %d %s %s %s %d %d %d"
         % (0x1234, g9(f32(0.25)), g9(f32(0.5)), g9(f32(0.75)), 3, 4, 1))


# ------------------------------------------------------------- the target

def i8(v):
    v &= 0xFF
    return v - 256 if v >= 128 else v


def i16(v):
    v &= 0xFFFF
    return v - 65536 if v >= 32768 else v


def target_fields(seed):
    return {
        "NumPoints": i8(seed + 7),
        "TType": 5 + seed,
        "WhichPointIPicked": i8(seed - 3),
        "PTime": 12345 + seed,
        "ATime": 999 - seed,
        "Length": f32(42.5 * seed),
    }


def point(seed, i):
    return (f32(seed * 100 + i), f32(f32(seed * 100 + i) + 0.5),
            f32(-(seed * 100 + i)))


def print_target(tag, seed):
    t = target_fields(seed)
    emit("%s numpoints %d ttype %d picked %d ptime %d atime %d len %s"
         % (tag, t["NumPoints"], t["TType"], t["WhichPointIPicked"],
            t["PTime"], t["ATime"], g9(t["Length"])))
    for i in range(0, MAX_POINTS, 7):
        x, y, z = point(seed, i)
        emit("%s p%d %s %s %s spd %s route %d rpn %d dl %d"
             % (tag, i, g9(x), g9(y), g9(z),
                g9(f32(f32(i * 1.25) + seed)), i8(i - 10),
                i16(1000 + i * seed), i8(3 - i)))


def s_target():
    emit("[target]")
    print_target("copied", 2)
    print_target("src9", 9)
    # The copy was by value, so refilling the source left the driver's
    # copy where it was.
    print_target("still", 2)
    emit("second copy identical 1")
    emit("inputs survive %d %s %d" % (0x0ABC, g9(f32(0.125)), 11))
    # A target with the top bit set in every byte-wide field: `lb` and
    # `lh` sign-extend, so these come back negative.
    emit("signbits %d %d %d %d %d"
         % (i8(0x80), i8(0xff), i8(0x81), i8(0xc0), i16(0x8001)))
    emit("assign returns dst 1")


# ------------------------------------------------------------- the stubs

def s_stubs():
    emit("[stubs]")
    emit("steer_to_point 1")
    emit("desired_time_to_speed %s" % g9(0.0))
    emit("desired_speed %s" % g9(0.0))
    emit("is_honking 0")
    emit("max_speed_to_target %s" % g9(0.0))
    emit("after set_steer_to_point 1")
    emit("honking after start 0")
    emit("object unchanged 1")


SCENARIOS = [s_layout, s_ctor, s_inputs, s_target, s_stubs]


def model():
    del OUT[:]
    for s in SCENARIOS:
        s()
    return list(OUT)


# ----------------------------------------------------------------- running

def run_harness(exe, out_path):
    with open(out_path, "w") as fh:
        r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                           text=True)
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def diff(a, b, quiet=False):
    d = list(difflib.unified_diff(a, b, "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


MUTATIONS = [
    # -- CarDriver's layout -------------------------------------------------
    ("cd-steering-is-32", CH,
     "    uint16_t    Steering;       // 528  a BAM; sh to write, lhu to read"
     + NL + "    uint16_t    _pad0;          // 530",
     "    uint32_t    Steering;       // 528"),
    ("cd-steering-signed", CH,
     "    uint16_t    Steering;       // 528",
     "    int16_t     Steering;       // 528"),
    ("cd-gears-swapped", CH,
     "    Gear        DesiredGear;    // 544" + NL
     + "    Gear        SportGear;      // 548",
     "    Gear        SportGear;      // 544" + NL
     + "    Gear        DesiredGear;    // 548"),
    ("cd-pedals-order", CH,
     "    float       Brake;          // 536" + NL
     + "    float       EBrake;         // 540",
     "    float       EBrake;         // 536" + NL
     + "    float       Brake;          // 540"),
    ("cd-vtable-first", CH,
     "    DriveTarget MyDriveTarget;  //   0  528 bytes, embedded not inherited",
     "    uint32_t    _vtable_first;" + NL
     + "    DriveTarget MyDriveTarget;  //   0  528 bytes, embedded not inherited"),
    ("cd-nitro-is-byte", CH,
     "    int32_t     NitroFlag;      // 552  a bool stored as a word",
     "    int8_t      NitroFlag;      // 552" + NL
     + "    uint8_t     _npad[3];"),

    # -- DriveTarget's layout -----------------------------------------------
    ("dt-points-at-4", DH,
     "    uint8_t  _pad0[15];                        //   1  (Points is 16-aligned)",
     "    uint8_t  _pad0[3];"),
    ("dt-points-are-vec4", DH,
     "    bVector3 Points[DRIVETARGET_MAX_POINTS];   //  16",
     "    bVector4 Points[DRIVETARGET_MAX_POINTS];   //  16"),
    ("dt-points-19", DH,
     "    bVector3 Points[DRIVETARGET_MAX_POINTS];   //  16",
     "    bVector3 Points[DRIVETARGET_MAX_POINTS - 1];" + NL
     + "    uint8_t  _ppad[16];"),
    ("dt-speed-and-route-swap", DH,
     "    float    CalculatedSpeed[DRIVETARGET_MAX_POINTS];  // 336" + NL
     + "    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 416",
     "    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 336" + NL
     + "    uint8_t  _rpad[60];" + NL
     + "    float    CalculatedSpeed[DRIVETARGET_MAX_POINTS];  // 416"),
    ("dt-route-is-int32", DH,
     "    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 416",
     "    int32_t  Route[DRIVETARGET_MAX_POINTS / 4];        // 416"),
    ("dt-route-unsigned", DH,
     "    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 416",
     "    uint8_t  Route[DRIVETARGET_MAX_POINTS];            // 416"),
    ("dt-rpn-is-int8", DH,
     "    int16_t  RoutePointNumber[DRIVETARGET_MAX_POINTS]; // 436" + NL
     + "    int8_t   DrivingLine[DRIVETARGET_MAX_POINTS];      // 476",
     "    int8_t   RoutePointNumber[DRIVETARGET_MAX_POINTS]; // 436" + NL
     + "    uint8_t  _qpad[20];" + NL
     + "    int8_t   DrivingLine[DRIVETARGET_MAX_POINTS];      // 476"),
    ("dt-drivingline-unsigned", DH,
     "    int8_t   DrivingLine[DRIVETARGET_MAX_POINTS];      // 476",
     "    uint8_t  DrivingLine[DRIVETARGET_MAX_POINTS];      // 476"),
    ("dt-numpoints-unsigned", DH,
     "    int8_t   NumPoints;                        //   0",
     "    uint8_t  NumPoints;                        //   0"),
    ("dt-picked-unsigned", DH,
     "    int8_t   WhichPointIPicked;                // 500",
     "    uint8_t  WhichPointIPicked;                // 500"),
    ("dt-times-swapped", DH,
     "    int32_t  WhichPointIPickedCalculationTime; // 504  loaded with lw"
     + NL + "    int32_t  WhichPointIPickedTime;            // 508"
     "  AccelerationBlendingTime",
     "    int32_t  WhichPointIPickedTime;            // 504" + NL
     + "    int32_t  WhichPointIPickedCalculationTime; // 508"),
    ("dt-length-is-int", DH,
     "    float    Length;                           // 512",
     "    int32_t  Length;                           // 512"),
    ("dt-no-tail-pad", DH,
     "    uint8_t  _pad2[12];                        // 516",
     "    uint8_t  _pad2[4];                         // 516"),
    ("dt-max-points-16", DH,
     "#define DRIVETARGET_MAX_POINTS 20",
     "#define DRIVETARGET_MAX_POINTS 16"),

    # -- the constructor ------------------------------------------------------
    ("ctor-inits-sportgear", CD,
     "    d->DesiredGear = 1;",
     "    d->DesiredGear = 1;" + NL + "    d->SportGear = 0;"),
    ("ctor-gear-zero", CD, "    d->DesiredGear = 1;", "    d->DesiredGear = 0;"),
    ("ctor-no-memset", CD,
     "    memset(&d->MyDriveTarget, 0, sizeof(DriveTarget));", ""),
    ("ctor-memset-whole-object", CD,
     "    memset(&d->MyDriveTarget, 0, sizeof(DriveTarget));",
     "    memset(d, 0, sizeof(CarDriver));"),
    ("ctor-no-vtable", CD,
     "    d->_vtable = CARDRIVER_VTABLE;" + NL + NL
     + "    // The DriveTarget constructor's memset.", ""
     + "    // The DriveTarget constructor's memset."),
    ("ctor-vtable-value", CH,
     "#define CARDRIVER_VTABLE 0x002924a8u",
     "#define CARDRIVER_VTABLE 0x002924b8u"),
    ("ctor-no-nitro-clear", CD, "    d->NitroFlag = 0;", ""),
    ("ctor-no-steering-clear", CD, "    d->Steering = 0;", ""),
    ("ctor-no-ebrake-clear", CD, "    d->EBrake   = 0.0f;", ""),
    ("fini-no-vtable", CD,
     "    d->_vtable = CARDRIVER_VTABLE;" + NL + NL
     + "    // `_$_11DriveTarget(this, 2)` follows", ""
     + "    // `_$_11DriveTarget(this, 2)` follows"),
    ("fini-clears-inputs", CD,
     "    d->_vtable = CARDRIVER_VTABLE;" + NL + NL
     + "    // `_$_11DriveTarget(this, 2)` follows",
     "    d->_vtable = CARDRIVER_VTABLE;" + NL
     + "    d->DesiredGear = 0;" + NL + NL
     + "    // `_$_11DriveTarget(this, 2)` follows"),

    # -- the input record ------------------------------------------------------
    ("get-steering-lbu-not-lhu", CD,
     "uint16_t cardriver_get_steering(const CarDriver *d)  { return d->Steering; }",
     "uint16_t cardriver_get_steering(const CarDriver *d)"
     "  { return *(const uint8_t *)&d->Steering; }"),
    ("set-brake-hits-throttle", CD,
     "void cardriver_set_brake(CarDriver *d, float f)         { d->Brake = f; }",
     "void cardriver_set_brake(CarDriver *d, float f)         { d->Throttle = f; }"),
    ("set-ebrake-hits-brake", CD,
     "void cardriver_set_ebrake(CarDriver *d, float f)        { d->EBrake = f; }",
     "void cardriver_set_ebrake(CarDriver *d, float f)        { d->Brake = f; }"),
    ("set-sport-hits-desired", CD,
     "void cardriver_set_sport_gear(CarDriver *d, Gear g)     { d->SportGear = g; }",
     "void cardriver_set_sport_gear(CarDriver *d, Gear g)     { d->DesiredGear = g; }"),
    ("get-desired-returns-sport", CD,
     "Gear     cardriver_get_desired_gear(const CarDriver *d) { return d->DesiredGear; }",
     "Gear     cardriver_get_desired_gear(const CarDriver *d) { return d->SportGear; }"),
    ("set-nitro-narrows", CD,
     "void cardriver_set_nitro(CarDriver *d, int32_t on)      { d->NitroFlag = on; }",
     "void cardriver_set_nitro(CarDriver *d, int32_t on)"
     "      { d->NitroFlag = on != 0; }"),

    # -- the target --------------------------------------------------------------
    ("assign-partial", CD,
     "    memcpy(dst, src, sizeof(DriveTarget));",
     "    memcpy(dst, src, 512);"),
    ("assign-too-much", CD,
     "    memcpy(dst, src, sizeof(DriveTarget));",
     "    memcpy(dst, src, sizeof(DriveTarget) + 8);"),
    ("assign-returns-src", CD, "    memcpy(dst, src, sizeof(DriveTarget));"
     + NL + "    return dst;",
     "    memcpy(dst, src, sizeof(DriveTarget));" + NL
     + "    return (DriveTarget *)src;"),
    ("set-target-aliases-wrong", CD,
     "    drivetarget_assign(&d->MyDriveTarget, t);",
     "    (void)t;"),

    # -- the stubs -----------------------------------------------------------------
    ("stub-steer-to-point-returns", CD,
     "    (void)d;" + NL + "    return NULL;                        // move v0,zero",
     "    return (bVector2 *)&d->MyDriveTarget.Points[0];"),
    ("stub-honking-true", CD,
     "    (void)d;" + NL + "    return 0;                           // move v0,zero",
     "    (void)d;" + NL + "    return 1;"),
    ("stub-desired-speed-one", CD,
     "float cardriver_get_desired_speed(CarDriver *d)" + NL + "{" + NL
     + "    (void)d;" + NL + "    return 0.0f;" + NL + "}",
     "float cardriver_get_desired_speed(CarDriver *d)" + NL + "{" + NL
     + "    (void)d;" + NL + "    return 1.0f;" + NL + "}"),
    ("stub-max-speed-uses-target", CD,
     "    (void)d; (void)t;" + NL + "    return 0.0f;",
     "    (void)d;" + NL + "    return t->Length;"),
    ("stub-set-steer-to-point-stores", CD,
     "    (void)d; (void)p;                   // jr ra ; nop -- the point is dropped",
     "    d->MyDriveTarget.Length = p->x;"),
    ("stub-honk-writes", CD,
     "void cardriver_start_honk_horn(CarDriver *d)  { (void)d; }",
     "void cardriver_start_honk_horn(CarDriver *d)  { d->NitroFlag = 1; }"),
    ("stub-clear-steering-writes", CD,
     "void cardriver_clear_steering_memory(CarDriver *d) { (void)d; }",
     "void cardriver_clear_steering_memory(CarDriver *d) { d->Steering = 0; }"),
]

EQUIVALENT = []
EXPECT_MISSING = []


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="cardriver_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        if before not in text:
            missing.append(name)
            print("  %-32s PATTERN NOT FOUND" % name)
            continue
        try:
            path.write_text(text.replace(before, after, 1),
                            encoding="utf-8", newline="")
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="cardriver_test")
                except SystemExit:
                    print("  %-32s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
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
            path.write_text(text, encoding="utf-8", newline="")

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    unexpected = [m for m in missing if m not in EXPECT_MISSING]
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    return 1 if (holes or unexpected) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="cardriver_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            print("wrote %s" % d)

    n = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ" % (len(SCENARIOS), len(lines), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
