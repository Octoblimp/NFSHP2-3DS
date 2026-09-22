"""Cross-check 3DS Files/source/car.c against a model of Car, first slice.

Car is the hub of task 25 -- eighty methods, 22876 bytes, a 2016-byte
record -- and it is not the physics. The simulation lives in the movers
that `SetMovementMode` constructs; Car owns the state they write into and
hands everything else off. Thirty-four of the eighty make no call outside
the class at all.

This checker covers the seventeen of those that also need no vtable: the
three empty ones, the blinking, the two effect gates, the debug checksum,
the two wheel aggregates, the forward acceleration, the horn request, the
wiper window and the borrowed steering angle. What is left and what each
piece waits on is listed at the bottom of car.c.

Six things in this slice are easy to transcribe wrongly, and none of them
shows in the shape of the code:

**GetWheelTraction pairs the diagonals, not the axles.** 0x001330e0 adds
916 to 928 and 920 to 924 -- WheelTractionUsage[0] with [3] and [1] with
[2]. Front-and-rear gives the same answer on a symmetric car and a
different one on every asymmetric slide, and the transcript carries two
fixtures that separate them.

**IsBlinking has two sentinels, not one.** 0 is the obvious one; the
other is 0x7fffffff, built with `lui 0x7fff; ori 0xffff` at 0x00131650
and tested with `xor`/`sltu` rather than a branch, which is exactly how
it gets read past. PleaseResetMeLater writes it.

**ShouldVisualEffectsBeGenerated tests the driver type first.** The
traffic-car test at 0x00134144 comes before the poof test and before
RenderingEnabled is loaded, so a traffic car answers false whatever its
other two fields say.

**HonkAndOrBlinkHeadlights sums `On + Off + On`, with the OLD
durations.** 0x0013252c adds Off to On and 0x00132534 adds On again, all
before the new values are stored. Two thirds of a cycle, or the new
durations, is a different guard.

**GetForwardAcceleration below the threshold returns a magnitude.** The
`c.lt.s` at 0x00133dc0 sends speeds under 0.1 to a plain `sqrt` of the
acceleration's squared length -- unsigned, so a car braking hard at a
standstill reports a positive forward acceleration. Above it, the answer
is a dot with the normalized velocity and can go negative.

**TurnWipersOnForDuration is a window merge with two branch-likelies in
it.** 0x001319d4 and 0x001319e0 are `bnel`/`beql`, whose delay slots run
only when taken, and both delay slots load WiperOffTime. Reading them as
ordinary branches puts the load on the wrong side and the merge picks the
wrong end.

The two world clocks and the tick constant come out of the ELF by
address, not out of the header, so a typo in CAR_TICK_SECONDS diffs
rather than the two files agreeing with each other.

    python tools/car_check.py
    python tools/car_check.py --mutate
    python tools/car_check.py --dump out/car
"""
import argparse
import difflib
import math
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
import carstate_check

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

# car.c's only call out of the class is Car::WorldToCar's tail call into
# CarState, so the CarState slice and the four files under it come along.
# They are not under test here -- carstate_check owns them -- but linking the
# real ones rather than stubbing them is what makes the forwarder's fixtures
# mean anything.
SOURCES = [
    "tools/src/car_test.c",
    "3DS Files/source/car.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/emath.c",
]

CH = "3DS Files/source/car.h"
CC = "3DS Files/source/car.c"
TH = "3DS Files/source/topology.h"

PTR = 8                       # the host, not the port
SLACK = PTR - 4

f32 = bmath_check.f32
bits = bmath_check.bits
fadd = bvector_check.fadd
fsub = bvector_check.fsub
fmul = bvector_check.fmul
fdiv = bvector_check.fdiv

HARNESS_TIMEOUT = 300
HARNESS_HUNG = -9999


# ------------------------------------------------------------- the image

GP = 0x00328bf0


def gpword(off):
    return struct.unpack("<I", bmath_check.ELF.read(GP + off, 4))[0]


# `lwc1 $f2,-32020(gp)` in IsBlinking and `lwc1 $f2,-31992(gp)` in
# HonkAndOrBlinkHeadlights are the same constant at two addresses: the
# WorldTimer tick in seconds. Read both and require them to agree, because
# the claim the port makes is that one #define covers both call sites.
TICK_A = gpword(-32020)
TICK_B = gpword(-31992)
assert TICK_A == TICK_B == 0x3983126f, (hex(TICK_A), hex(TICK_B))
TICK = bits(TICK_A)

# `lwc1 $f1,-31920(gp)` in GetForwardAcceleration.
SPEED_EPS = bits(gpword(-31920))
assert gpword(-31920) == 0x3dcccccd, hex(gpword(-31920))

# WorldTimer at 0x00323cf0 and WorldTimeFrames at 0x00323cfc, both named in
# .symtab. Car reaches them as gp-20224 and gp-20212; the assert is what
# makes a mistyped displacement in the model diff.
assert GP - 20224 == 0x00323cf0, hex(GP - 20224)
assert GP - 20212 == 0x00323cfc, hex(GP - 20212)

# `lui at,0x4000` in BlinkBlinkPoof, `lui at,0x3f00` in GetWheelTraction,
# `lui at,0x4780` in CalculateDebugChecksum, `addiu v1,zero,82` and
# `addiu v0,v0,81` in TurnWipersOnForDuration.
TWO = bits(0x40000000)
HALF = bits(0x3f000000)
SCALE = bits(0x47800000)
QUARTER = bits(0x3e800000)
WIPER_PERIOD = 82
BLINK_NEVER = 0x7fffffff


# --------------------------------------------------------------- output

OUT = []


def emit(s):
    OUT.append(s)


def g9(x):
    return "%.9g" % x


def i32(v):
    """A 32-bit wrapping signed integer, which is what `subu` produces and
    `cvt.s.w` then reads."""
    v &= 0xffffffff
    return v - 0x100000000 if v & 0x80000000 else v


def trunc_w(x):
    """cvt.w.s on the R5900: truncate toward zero, saturate by the sign of
    the source. Character for character camera_check.py's, which the camera
    slice wrote first; see the note above car_trunc_w in car.c for why the
    negative threshold can be spelled either way."""
    if x != x:
        return 0
    if x >= 2147483648.0:
        return 0x7fffffff
    if x <= -2147483649.0:
        return -0x80000000
    return int(x)


# ---------------------------------------------------------------- model
#
# Every function below is written from the listing at the address in its
# docstring. None of them reads car.c.


def is_blinking(timer, now, duration):
    """0x00131640."""
    # 0x00131648  beq v1,zero      -- and the 0x7fffffff test after it
    if timer == 0 or timer == BLINK_NEVER:
        return 0
    # 0x0013166c  subu; cvt.s.w; mul.s
    dt = f32(float(i32(now - timer)))
    elapsed = fmul(dt, TICK)
    # 0x00131684  c.lt.s $f0,$f1
    return 1 if elapsed < duration else 0


def debug_checksum(px, py):
    """0x00130ee0."""
    s = fadd(px, py)
    return trunc_w(fmul(s, SCALE))


def wheels_on_ground(touching):
    """0x00133128. `lb` then `bnel`, so any non-zero byte counts."""
    n = f32(0.0)
    for i in range(4):
        if touching[i] != 0:
            n = fadd(n, QUARTER)
    return n


def wheel_traction(u):
    """0x001330e0. 916 with 928, 920 with 924 -- the diagonals."""
    a = fmul(fadd(u[0], u[3]), HALF)
    b = fmul(fadd(u[1], u[2]), HALF)
    # 0x00133108  c.lt.s $f1,$f2; bc1f with `mov.s $f0,$f1` in the delay slot
    return b if a < b else a


def should_sound(poofed, rendering):
    """0x00134188."""
    if poofed != 0:
        return 0
    return 1 if rendering != 0 else 0


def should_visual(driver_type, poofed, rendering):
    """0x00134130. The driver-type test comes first."""
    if driver_type == 3:
        return 0
    if poofed != 0:
        return 0
    return 1 if rendering != 0 else 0


def forward_acceleration(mag, v, a):
    """0x00133db8."""
    # 0x00133dc0  c.lt.s $f0,$f1  -- VelocityMagnitude < 0.1
    if mag < SPEED_EPS:
        # 0x00133dd0  vmul.xyz then two vadd, then sqrt.s
        s = fadd(fadd(fmul(a[0], a[0]), fmul(a[1], a[1])), fmul(a[2], a[2]))
        return f32(math.sqrt(s))

    # 0x00133df8  the same squared length, of the velocity this time
    len2 = fadd(fadd(fmul(v[0], v[0]), fmul(v[1], v[1])), fmul(v[2], v[2]))
    # 0x00133e0c  vrsqrt Q,vf00w,vf01x -- a divide by a square root, not an
    # estimate -- then `vaddq.x vf01,vf00,Q`, where vf00.x is 0.
    inv = fdiv(f32(1.0), f32(math.sqrt(len2)))
    nx = fmul(v[0], inv)
    ny = fmul(v[1], inv)
    nz = fmul(v[2], inv)
    # 0x00133e2c  the dot, summed x then y then z
    return fadd(fadd(fmul(nx, a[0]), fmul(ny, a[1])), fmul(nz, a[2]))


def honk(car, now, on, off, blink, hk, two):
    """0x00132508. `car` is a dict and is updated in place."""
    dt = f32(float(i32(now - car["start"])))
    elapsed = fmul(dt, TICK)
    # 0x0013252c  add.s $f0,$f3,$f0 then 0x00132534 add.s $f0,$f0,$f3
    cycle = fadd(fadd(car["on"], car["off"]), car["on"])
    # 0x00132538  c.lt.s $f0,$f1  -- cycle < elapsed
    if cycle < elapsed:
        car["two"] = two
        car["start"] = now
        car["on"] = on
        car["off"] = off
        car["blink"] = blink
        car["honk"] = hk


def wipers(state, on_time, off_time, now, req_on, req_off):
    """0x001319c0. Returns the new (on_time, off_time).

    The two branch-likelies at 0x001319d4 and 0x001319e0 both carry
    `lw v1,1932(a0)` in their delay slots, so WiperOffTime is loaded on
    the taken side only; the not-taken paths reload it at 0x00131a0c and
    0x00131a10.
    """
    if state != 0:
        return on_time, off_time

    start = i32(on_time)

    if start < now:
        # 0x001319f4, reached with v1 already loaded
        end = i32(off_time)
        if not (now < end):
            start = req_on
            on_time = req_on
    else:
        # 0x001319dc
        if req_on < start:
            start = req_on
            on_time = req_on
        end = i32(off_time)

    # 0x00131a10 / 0x001319fc  slt v0,v1,a2
    if end < req_off:
        off_time = req_off
        end = req_off

    # 0x00131a28  addiu v0,v0,81; div by 82; mult by 82; addu
    span = i32(end - start)
    q = mips_div(i32(span + (WIPER_PERIOD - 1)), WIPER_PERIOD)
    off_time = i32(i32(q * WIPER_PERIOD) + start)
    return on_time, off_time


def mips_div(a, b):
    """MIPS `div` truncates toward zero, unlike Python's floor division."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


# -------------------------------------------------------- the transcript


def model():
    del OUT[:]

    # -- layout -------------------------------------------------------------
    #
    # The PS2 offsets are the .mdebug ones, each re-derived from a load or a
    # store in the listing; the slack counts are the pointer widenings at or
    # before the field. On ARM every term is zero and these are the console's
    # offsets exactly.
    def at(n, k):
        return n + k * SLACK

    emit("[layout]")
    emit("  %-28s %d" % ("slack", SLACK))
    emit("  %-28s %d" % ("sizeof Car", at(2016, 154)))
    emit("  %-28s %d" % ("sizeof CarNode", 2 * PTR))
    emit("  %-28s %d" % ("sizeof CarState", at(1024, 2)))
    emit("  %-28s %d" % ("sizeof TopologyCoordinate", at(560, 128)))
    emit("  %-28s %d" % ("sizeof TrackPathCoordinate", at(40, 4)))
    emit("  %-28s %d" % ("sizeof OverrideRenderingPos", 96))
    emit("  %-28s %d" % ("sizeof DriverInfo", at(20, 1)))
    emit("  %-28s %d" % ("sizeof RideInfo", 8))

    for name, ps2, k in (
            ("off CarIndex", 8, 2), ("off DriverNumber", 10, 2),
            ("off pCarTypeInfo", 12, 3), ("off MyDriver", 20, 5),
            ("off pPlayer", 24, 6), ("off TheControlMode", 32, 8),
            ("off TheMovementMode", 36, 8), ("off pCarController", 40, 8),
            ("off pCarDriver", 44, 9), ("off pCarMover", 48, 10),
            ("off pDynamicCollisionBody", 52, 11), ("off State", 64, 12),
            ("off DispGear", 1088, 14), ("off FrictionBoost", 1092, 14),
            ("off DraftFactor", 1096, 14), ("off vOldVel", 1120, 14),
            ("off RenderingEnabled", 1160, 14),
            ("off pRenderInfo", 1168, 14),
            ("off TheOverrideRendering", 1184, 16),
            ("off TheTopologyCoordinate", 1280, 16),
            ("off TheTrackPathCoordinate", 1840, 144),
            ("off CopLights", 1880, 148),
            ("off SignalLightState", 1884, 148),
            ("off HeadlightsAndHornStart", 1904, 148),
            ("off TheSirenMode", 1924, 148),
            ("off WiperOnTime", 1928, 148),
            ("off WiperOffTime", 1932, 148),
            ("off WiperState", 1936, 148),
            ("off pCarDamage", 1940, 149),
            ("off BlownTireBits", 1944, 150),
            ("off NumBlownTires", 1945, 150),
            ("off pBaseCarSound", 1952, 150),
            ("off ResetMe", 1956, 151),
            ("off BlinkTimer", 1960, 151),
            ("off BlinkDuration", 1964, 151),
            ("off LastInTroughPosition", 1968, 151),
            ("off bPoofed", 1976, 151),
            ("off bVisibleOnTrackMap", 1980, 151),
            ("off NumTimesSkidding", 1984, 151),
            ("off RoadBumpBits", 1988, 151),
            ("off pCaffeineObj", 1992, 152),
            ("off LeaveCarTrails", 2000, 154),
            ("off ForceBuzzTime", 2004, 154),
            ("off fAngleToCamera", 2008, 154)):
        emit("  %-28s %d" % (name, at(ps2, k)))

    emit("  %-28s %d" % ("off ORP GeometryPosition", 64))
    emit("  %-28s %d" % ("off ORP OverrideViewBits", 80))
    emit("  %-28s %d" % ("off DriverInfo DriverType", 4))
    emit("  %-28s %d" % ("off DriverInfo RideInfo", 8))
    emit("  %-28s %d" % ("off CarDriver Steering", 528))

    emit("  %-28s %d" % ("enum REAL_CONTROL", 1))
    emit("  %-28s %d" % ("enum COP_CONTROL", 4))
    emit("  %-28s %d" % ("enum PHYSICS_MOVEMENT", 1))
    emit("  %-28s %d" % ("enum BELT_MOVEMENT", 6))
    emit("  %-28s %d" % ("enum SIGNAL_LIGHT_ALL_ON", 3))
    emit("  %-28s %d" % ("enum SIREN_MODE_BROKEN", 4))
    emit("  %-28s %d" % ("enum DRIVER_TYPE_TRAFFIC", 3))
    emit("  %-28s %d" % ("enum DRIVER_TYPE_SUPER_COP", 5))
    emit("  %-28s %s" % ("tick seconds", g9(TICK)))
    emit("  %-28s %08x" % ("tick bits", TICK_A))
    emit("  %-28s %d" % ("wiper period", WIPER_PERIOD))

    # -- stubs --------------------------------------------------------------
    emit("[stubs]")
    emit("  %-28s %d" % ("bytes changed", 0))

    # -- blinking -----------------------------------------------------------
    now_list = [0, 1, 4000, 2147483647, -2147483648, -1]
    stamp_list = [0, 1, 2000, 2147483647, -2147483648, -1, 12345]
    dur_list = [f32(0.0), f32(0.25), f32(1.0), f32(3.0), f32(-1.0)]

    emit("[blink]")
    for now in now_list:
        for stamp in stamp_list:
            for dur in dur_list:
                emit("  now %-12d stamp %-12d dur %-10s -> %d"
                     % (now, stamp, g9(dur), is_blinking(stamp, now, dur)))

    emit("[blink start/stop]")
    for now in now_list:
        dur = f32(1.5)
        emit("  start now %-12d timer %-12d dur %s blinking %d"
             % (now, now, g9(dur), is_blinking(now, now, dur)))
        emit("    after stop timer %d blinking %d"
             % (0, is_blinking(0, now, dur)))

    emit("[blink poof]")
    for now in now_list:
        emit("  now %-12d timer %-12d dur %s map %d poofed %d"
             % (now, now, g9(TWO), 0, 1))

    # -- checksum -----------------------------------------------------------
    xs = [f32(0.0), f32(1.0), f32(-1.0), f32(0.5), f32(-0.5),
          f32(32767.5), f32(-32767.5), f32(0.0000152587890625),
          f32(1e10), f32(-1e10)]
    ys = [f32(0.0), f32(2.0), f32(-2.0), f32(0.25), f32(-0.25),
          f32(0.5), f32(-0.5), f32(0.0000076293945312),
          f32(1.0), f32(1.0)]

    emit("[checksum]")
    for x in xs:
        for y in ys:
            emit("  x %-18s y %-18s -> %d"
                 % (g9(x), g9(y), debug_checksum(x, y)))

    # The three conversion boundaries. 32768 * 65536 is exactly 2^31 and
    # saturates; 32767.998046875 * 65536 is 2147483520, the largest float32
    # below it, and does not; -32768 * 65536 is exactly -2^31, which IS
    # representable and so converts rather than saturating.
    edges = [
        ("hi exactly 2^31", f32(32768.0)),
        ("hi one ulp under", f32(32767.998046875)),
        ("hi far over", f32(1e30)),
        ("lo exactly -2^31", f32(-32768.0)),
        ("lo one ulp under", f32(-32768.00390625)),
        ("nan", struct.unpack("<f", struct.pack("<I", 0x7fc00000))[0]),
    ]
    emit("[checksum edges]")
    for name, x in edges:
        emit("  %-20s -> %d" % (name, debug_checksum(x, f32(0.0))))

    # -- wheels on ground ---------------------------------------------------
    # The tick, pinned to the bit. 4000 * 0x3983126f is exactly 1.0 and
    # 4000 * 0x3983126e is 0.99999994, so a duration of 1.0 answers no on
    # the image's word and yes one ulp below it. The honk goes the other
    # way round, because its guard is `cycle < elapsed` rather than
    # `elapsed < duration` and the two call sites read different gp
    # displacements for what the port asserts is one constant.
    emit("[blink tick]")
    emit("  dt 4000 dur 1 -> %d" % is_blinking(1, 4001, f32(1.0)))
    emit("  dt 4000 dur 0.99999994 -> %d"
         % is_blinking(1, 4001, f32(0.99999994)))

    emit("[honk tick]")
    _c = {"start": 0, "on": f32(0.0), "off": f32(0.99999994),
          "blink": 0, "honk": 0, "two": 0}
    honk(_c, 4000, f32(0.75), f32(0.125), 1, 1, 1)
    emit("  cycle 0.99999994 -> honk %d on %s" % (_c["honk"], g9(_c["on"])))

    emit("[wheels on ground]")
    for mask in range(16):
        t = [(mask >> i) & 1 for i in range(4)]
        emit("  mask %2d -> %s" % (mask, g9(wheels_on_ground(t))))

    emit("[wheels on ground non-bool]")
    for v in (-1, 2, 127, -128):
        emit("  all %-5d -> %s" % (v, g9(wheels_on_ground([v] * 4))))

    # -- wheel traction -----------------------------------------------------
    us = [
        [f32(0.0), f32(0.0), f32(0.0), f32(0.0)],
        [f32(1.0), f32(0.0), f32(0.0), f32(0.0)],
        [f32(0.0), f32(1.0), f32(0.0), f32(0.0)],
        [f32(0.25), f32(0.75), f32(0.5), f32(0.125)],
        [f32(1.0), f32(0.5), f32(0.5), f32(0.0)],
        [f32(-1.0), f32(0.5), f32(0.25), f32(2.0)],
    ]
    emit("[wheel traction]")
    for u in us:
        emit("  u %s %s %s %s -> %s"
             % (g9(u[0]), g9(u[1]), g9(u[2]), g9(u[3]),
                g9(wheel_traction(u))))

    # -- the gates ----------------------------------------------------------
    emit("[effect gates]")
    for t in range(6):
        for p in range(2):
            for r in (-1, 0, 1):
                emit("  type %d poof %d render %-3d -> sound %d visual %d"
                     % (t, p, r, should_sound(p, r), should_visual(t, p, r)))

    # -- forward acceleration ----------------------------------------------
    mags = [f32(0.0), f32(0.0999999940395355), f32(0.100000001490116),
            f32(0.100000008940697), f32(1.0), f32(50.0), f32(-5.0)]
    vs = [
        [f32(1.0), f32(0.0), f32(0.0)],
        [f32(0.0), f32(1.0), f32(0.0)],
        [f32(3.0), f32(4.0), f32(0.0)],
        [f32(-2.0), f32(1.0), f32(2.0)],
        [f32(0.25), f32(0.0), f32(-0.25)],
    ]
    accs = [
        [f32(1.0), f32(2.0), f32(3.0)],
        [f32(-1.0), f32(0.0), f32(0.0)],
        [f32(0.0), f32(0.0), f32(0.0)],
        [f32(7.5), f32(-2.5), f32(0.125)],
        [f32(-0.5), f32(-0.5), f32(-0.5)],
    ]
    emit("[forward acceleration]")
    for mag in mags:
        for vi, v in enumerate(vs):
            for ai, a in enumerate(accs):
                emit("  mag %-20s v%d a%d -> %s"
                     % (g9(mag), vi, ai, g9(forward_acceleration(mag, v, a))))

    # -- horn ---------------------------------------------------------------
    nows = [0, 4000, 40000, -1]
    starts = [0, 1000, 40000, -4000]
    old_ons = [f32(0.0), f32(0.5), f32(2.0)]
    old_offs = [f32(0.0), f32(0.25), f32(1.0)]

    emit("[honk]")
    for now in nows:
        for st in starts:
            for oon in old_ons:
                for ooff in old_offs:
                    car = {"start": st, "on": oon, "off": ooff,
                           "blink": 0, "honk": 0, "two": 0}
                    honk(car, now, f32(0.75), f32(0.125), 1, 1, 1)
                    emit("  now %-12d start %-12d old %s %s"
                         % (now, st, g9(oon), g9(ooff)))
                    emit("    -> start %-12d on %s off %s blink %d "
                         "honk %d two %d"
                         % (car["start"], g9(car["on"]), g9(car["off"]),
                            car["blink"], car["honk"], car["two"]))

    emit("[honk drop]")
    car = {"start": 0, "on": f32(5.0), "off": f32(5.0),
           "blink": 9, "honk": 8, "two": 7}
    honk(car, 0, f32(0.75), f32(0.125), 1, 1, 1)
    emit("  blink %d honk %d two %d on %s off %s start %d"
         % (car["blink"], car["honk"], car["two"],
            g9(car["on"]), g9(car["off"]), car["start"]))

    # -- wipers -------------------------------------------------------------
    frames = [0, 100, 500, -50]
    on_times = [0, 50, 100, 300, 1000]
    off_times = [0, 60, 200, 400, 900]
    req_ons = [20, 100, 600]
    req_offs = [80, 300, 700]

    emit("[wipers]")
    for now in frames:
        for a in on_times:
            for b in off_times:
                for c in req_ons:
                    for d in req_offs:
                        on, off = wipers(0, a, b, now, c, d)
                        emit("  f %-6d on %-6d off %-6d req %-5d %-5d "
                             "-> %d %d" % (now, a, b, c, d, on, off))

    emit("[wipers busy]")
    for state in (1, -1, 2, 2147483647):
        on, off = wipers(state, 7, 9, 100, 20, 80)
        emit("  state %-12d -> on %d off %d" % (state, on, off))

    # -- the forwarder ------------------------------------------------------
    #
    # `Car::WorldToCar` is `j CarState::WorldToCar; addiu a0,a0,64`, so the
    # only thing it can get wrong is the 64. The transform itself is the
    # CarState slice's and is reused from its model rather than restated
    # here -- restating it would test this file against itself.
    #
    # MatrixValid is printed alongside the answer because it is what makes
    # the *offset* observable: GetTransformMatrix sets it on the CarState it
    # was handed, so a forwarder that passed the wrong address would leave
    # the flag at Car+64 clear even if the numbers happened to agree.
    emit("[world to car]")
    for ang, vel, pos, q in (
            (0, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0), (1.0, 0.0)),
            (0, (0.0, 0.0, 0.0, 0.0), (10.0, -5.0), (12.5, -1.25)),
            (16384, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0), (1.0, 2.0)),
            (8192, (0.0, 0.0, 0.0, 0.0), (-3.0, 7.0), (0.5, 0.25)),
            (0, (3.0, 4.0, 0.0, 0.0), (0.0, 0.0), (1.0, 0.0)),
            (49152, (0.0, 0.0, 0.0, 0.0), (100.0, 100.0), (99.0, 101.0)),
    ):
        s = carstate_check.State()
        s.Angle = ang
        s.Velocity = [f32(v) for v in vel]
        s.Position = [f32(pos[0]), f32(pos[1]), f32(0.0), f32(0.0)]
        s.ForwardSpeed = f32(1.0)
        s.MatrixValid = 0
        r = carstate_check.world_to_car2(s, [f32(q[0]), f32(q[1])])
        emit("  ang %-6d pos %-8s %-8s q %-8s %-8s -> %-14s %-14s valid %d"
             % (ang, g9(f32(pos[0])), g9(f32(pos[1])),
                g9(f32(q[0])), g9(f32(q[1])), g9(r[0]), g9(r[1]),
                s.MatrixValid))

    # -- steering -----------------------------------------------------------
    emit("[steering]")
    for bam in (0, 1, 16384, 32767, 32768, 49152, 65535, 12345):
        emit("  bam %-8d -> %d" % (bam, bam))

    return list(OUT)


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
    ("car-index-is-int32", CH,
     "    int16_t           CarIndex;                 // 8",
     "    int32_t           CarIndex;                 // 8"),
    ("car-hole56-short", CH,
     "    uint8_t           _hole56[8];               // 56   to align State",
     "    uint8_t           _hole56[4];               // 56   to align State"),
    ("car-hole1108-short", CH,
     "    uint8_t           _hole1108[12];            // 1108 to align vOldVel",
     "    uint8_t           _hole1108[8];             // 1108 to align vOldVel"),
    ("car-rendering-is-int32", CH,
     "    int8_t            RenderingEnabled;         // 1160",
     "    int32_t           RenderingEnabled;         // 1160"),
    ("car-blowntire-is-int32", CH,
     "    uint8_t           BlownTireBits;            // 1944",
     "    uint32_t          BlownTireBits;            // 1944"),
    ("car-lastintrough-is-v3", CH,
     "    bVector2          LastInTroughPosition;     // 1968",
     "    bVector3          LastInTroughPosition;     // 1968"),
    ("car-node-one-link", CH,
     "    struct CarNode *prev;  // 4",
     "    /* removed */"),
    ("orp-geom-at-68", CH,
     "    bVector3 GeometryPosition;  // 64",
     "    uint32_t _gap;              // 64" + NL +
     "    bVector3 GeometryPosition;  // 68"),
    ("driverinfo-type-at-8", CH,
     "    DriverType     TheDriverType;       // 4",
     "    uint32_t       _gap;                // 4" + NL +
     "    DriverType     TheDriverType;       // 8"),
    ("topology-table-127", TH,
     "#define TOPOLOGY_MAX_POLYGONS 128",
     "#define TOPOLOGY_MAX_POLYGONS 127"),
    ("topology-bbox-is-v3", TH,
     "    bVector2      InterestBBoxMin;                       // 0",
     "    bVector3      InterestBBoxMin;                       // 0"),

    # -- the enums ----------------------------------------------------------
    ("enum-traffic-is-2", CH,
     "#define DRIVER_TYPE_TRAFFIC_CAR ((DriverType)3)",
     "#define DRIVER_TYPE_TRAFFIC_CAR ((DriverType)2)"),
    ("enum-cop-control-3", CH,
     "#define COP_CONTROL     ((ControlMode)4)",
     "#define COP_CONTROL     ((ControlMode)3)"),
    ("enum-belt-is-5", CH,
     "#define BELT_MOVEMENT      ((MovementMode)6)",
     "#define BELT_MOVEMENT      ((MovementMode)5)"),
    ("enum-siren-broken-3", CH,
     "#define SIREN_MODE_BROKEN ((SirenMode)4)",
     "#define SIREN_MODE_BROKEN ((SirenMode)3)"),

    # -- the tick -----------------------------------------------------------
    # Not `1.0f / 4000.0f`: that rounds to 0x3983126e, one ulp below the
    # image's 0x3983126f, so it IS a change -- but it is worth spelling as
    # the wrong-but-plausible constant rather than as an arbitrary one.
    ("tick-is-quarter-milli", CC,
     "#define CAR_TICK_SECONDS 0.000250000012f",
     "#define CAR_TICK_SECONDS 0.00024999999f"),
    ("tick-is-one-over-4000", CC,
     "#define CAR_TICK_SECONDS 0.000250000012f",
     "#define CAR_TICK_SECONDS (1.0f / 4000.0f)"),
    ("wiper-period-81", CC,
     "#define CAR_WIPER_PERIOD_FRAMES 82",
     "#define CAR_WIPER_PERIOD_FRAMES 81"),

    # -- the stubs ----------------------------------------------------------
    ("stub-fake-engine-writes", CC,
     "void car_fake_engine_task(Car *c)" + NL + "{" + NL + "    (void)c;",
     "void car_fake_engine_task(Car *c)" + NL + "{" + NL + "    c->ResetMe = 1;"),
    ("stub-event-writes", CC,
     "void car_event_handler(Car *c, void *event)" + NL + "{" + NL +
     "    (void)c;",
     "void car_event_handler(Car *c, void *event)" + NL + "{" + NL +
     "    c->bPoofed = 1;"),
    ("stub-print-writes", CC,
     "void car_print_above(Car *c, const char *text, int colour)" + NL +
     "{" + NL + "    (void)c;",
     "void car_print_above(Car *c, const char *text, int colour)" + NL +
     "{" + NL + "    c->NumTimesSkidding = 1;"),

    # -- the blinking -------------------------------------------------------
    ("blink-one-sentinel", CC,
     "    if (t == 0 || t == 0x7fffffff)",
     "    if (t == 0)"),
    ("blink-only-sentinel", CC,
     "    if (t == 0 || t == 0x7fffffff)",
     "    if (t == 0x7fffffff)"),
    ("blink-sentinel-off-by-one", CC,
     "    if (t == 0 || t == 0x7fffffff)",
     "    if (t == 0 || t == 0x7ffffffe)"),
    ("blink-compare-le", CC,
     "    return elapsed < c->BlinkDuration;",
     "    return elapsed <= c->BlinkDuration;"),
    ("blink-compare-reversed", CC,
     "    return elapsed < c->BlinkDuration;",
     "    return c->BlinkDuration < elapsed;"),
    ("blink-elapsed-unsigned", CC,
     "    elapsed = (float)(int32_t)((uint32_t)WorldTimer - (uint32_t)t)",
     "    elapsed = (float)(uint32_t)((uint32_t)WorldTimer - (uint32_t)t)"),
    ("blink-elapsed-backwards", CC,
     "    elapsed = (float)(int32_t)((uint32_t)WorldTimer - (uint32_t)t)",
     "    elapsed = (float)(int32_t)((uint32_t)t - (uint32_t)WorldTimer)"),
    ("blink-start-no-stamp", CC,
     "    c->BlinkDuration = duration;" + NL + "    c->BlinkTimer = WorldTimer;",
     "    c->BlinkDuration = duration;"),
    ("blink-stop-sentinel", CC,
     "    c->BlinkTimer = 0;" + NL + "}",
     "    c->BlinkTimer = 0x7fffffff;" + NL + "}"),
    ("poof-one-second", CC,
     "    car_start_blinking(c, 2.0f);",
     "    car_start_blinking(c, 1.0f);"),
    ("poof-map-stays", CC,
     "    c->bVisibleOnTrackMap = 0;" + NL + "    c->bPoofed = 1;",
     "    c->bPoofed = 1;"),
    ("poof-no-poof", CC,
     "    c->bVisibleOnTrackMap = 0;" + NL + "    c->bPoofed = 1;",
     "    c->bVisibleOnTrackMap = 0;"),

    # -- the checksum -------------------------------------------------------
    ("checksum-scale-32768", CC,
     "    return car_trunc_w(s * 65536.0f);",
     "    return car_trunc_w(s * 32768.0f);"),
    ("checksum-rounds", CC,
     "    return car_trunc_w(s * 65536.0f);",
     "    return car_trunc_w(s * 65536.0f + 0.5f);"),

    # -- the conversion ----------------------------------------------------
    ("trunc-no-pos-saturation", CC,
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x7fffffff;" + NL,
     ""),
    ("trunc-pos-saturates-low", CC,
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x7fffffff;",
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x80000000;"),
    ("trunc-pos-threshold-strict", CC,
     "    if (x >= 2147483648.0f)",
     "    if (x > 2147483648.0f)"),
    ("trunc-no-neg-saturation", CC,
     "    if (x < -2147483648.0f)" + NL +
     "        return (int32_t)0x80000000;" + NL,
     ""),
    ("trunc-neg-threshold-le", CC,
     "    if (x < -2147483648.0f)",
     "    if (x <= -2147483648.0f)"),
    ("trunc-no-nan-arm", CC,
     "    if (x != x)                     // no NaN reaches the EE FPU; "
     "defined anyway" + NL + "        return 0;" + NL,
     ""),
    ("trunc-nan-returns-low", CC,
     "        return 0;" + NL + "    if (x >= 2147483648.0f)",
     "        return (int32_t)0x80000000;" + NL + "    if (x >= 2147483648.0f)"),
    ("checksum-x-only", CC,
     "    float s = c->State.Position.x + c->State.Position.y;",
     "    float s = c->State.Position.x;"),
    ("checksum-subtracts", CC,
     "    float s = c->State.Position.x + c->State.Position.y;",
     "    float s = c->State.Position.x - c->State.Position.y;"),
    ("checksum-uses-geometry", CC,
     "    float s = c->State.Position.x + c->State.Position.y;",
     "    float s = c->State.GeometryPosition.x + c->State.GeometryPosition.y;"),

    # -- the wheel aggregates ----------------------------------------------
    ("wog-half-each", CC,
     "            n = n + 0.25f;",
     "            n = n + 0.5f;"),
    ("wog-three-wheels", CC,
     "    for (i = 0; i < 4; i++)" + NL +
     "        if (c->State.WheelTouchingGround[i] != 0)",
     "    for (i = 0; i < 3; i++)" + NL +
     "        if (c->State.WheelTouchingGround[i] != 0)"),
    ("wog-tests-positive", CC,
     "        if (c->State.WheelTouchingGround[i] != 0)",
     "        if (c->State.WheelTouchingGround[i] > 0)"),
    ("traction-axles-not-diagonals", CC,
     "    float a = (u[0] + u[3]) * 0.5f;" + NL +
     "    float b = (u[1] + u[2]) * 0.5f;",
     "    float a = (u[0] + u[1]) * 0.5f;" + NL +
     "    float b = (u[2] + u[3]) * 0.5f;"),
    ("traction-takes-min", CC,
     "    return (a < b) ? b : a;",
     "    return (a < b) ? a : b;"),
    ("traction-no-half", CC,
     "    float a = (u[0] + u[3]) * 0.5f;",
     "    float a = (u[0] + u[3]);"),

    # -- the gates ----------------------------------------------------------
    ("sound-ignores-poof", CC,
     "    if (car_is_poofed(c))" + NL + "        return 0;" + NL + NL +
     "    return c->RenderingEnabled != 0;" + NL + "}" + NL + NL +
     "// 0x00134130.",
     "    return c->RenderingEnabled != 0;" + NL + "}" + NL + NL +
     "// 0x00134130."),
    ("visual-type-after-poof", CC,
     "    if (c->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)" + NL +
     "        return 0;" + NL + NL + "    if (car_is_poofed(c))",
     "    if (car_is_poofed(c))"),
    ("visual-type-is-cop", CC,
     "    if (c->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)",
     "    if (c->MyDriver->TheDriverType == DRIVER_TYPE_COP)"),
    ("visual-type-not-equal", CC,
     "    if (c->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)",
     "    if (c->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR)"),

    # -- the forward acceleration ------------------------------------------
    ("fa-threshold-le", CC,
     "    if (c->State.VelocityMagnitude < 0.1f)",
     "    if (c->State.VelocityMagnitude <= 0.1f)"),
    ("fa-threshold-one", CC,
     "    if (c->State.VelocityMagnitude < 0.1f)",
     "    if (c->State.VelocityMagnitude < 1.0f)"),
    ("fa-slow-uses-velocity", CC,
     "        return sqrtf(a->x * a->x + a->y * a->y + a->z * a->z);",
     "        return sqrtf(v->x * v->x + v->y * v->y + v->z * v->z);"),
    ("fa-slow-no-sqrt", CC,
     "        return sqrtf(a->x * a->x + a->y * a->y + a->z * a->z);",
     "        return a->x * a->x + a->y * a->y + a->z * a->z;"),
    ("fa-normalizes-acceleration", CC,
     "    len2 = v->x * v->x + v->y * v->y + v->z * v->z;",
     "    len2 = a->x * a->x + a->y * a->y + a->z * a->z;"),
    ("fa-dot-drops-z", CC,
     "    return nx * a->x + ny * a->y + nz * a->z;",
     "    return nx * a->x + ny * a->y;"),
    ("fa-divides-not-rsqrt", CC,
     "    inv  = 1.0f / sqrtf(len2);",
     "    inv  = 1.0f / len2;"),

    # -- the horn -----------------------------------------------------------
    ("honk-cycle-on-plus-off", CC,
     "    float cycle = c->HeadlightsAndHornOnDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornOnDuration;",
     "    float cycle = c->HeadlightsAndHornOnDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration;"),
    ("honk-cycle-two-offs", CC,
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornOnDuration;",
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration;"),
    ("honk-guard-le", CC,
     "    if (cycle < elapsed) {",
     "    if (cycle <= elapsed) {"),
    ("honk-guard-reversed", CC,
     "    if (cycle < elapsed) {",
     "    if (elapsed < cycle) {"),
    ("honk-no-stamp", CC,
     "        c->HeadlightsAndHornStartTime   = WorldTimer;",
     "        c->HeadlightsAndHornStartTime   = 0;"),
    ("honk-swaps-durations", CC,
     "        c->HeadlightsAndHornOnDuration  = onDuration;" + NL +
     "        c->HeadlightsAndHornOffDuration = offDuration;",
     "        c->HeadlightsAndHornOnDuration  = offDuration;" + NL +
     "        c->HeadlightsAndHornOffDuration = onDuration;"),
    ("honk-drops-two", CC,
     "        c->WantTwoHonksAndOrBlinks      = two;",
     "        c->WantTwoHonksAndOrBlinks      = 0;"),
    ("honk-elapsed-unsigned", CC,
     "    float elapsed = (float)(int32_t)((uint32_t)WorldTimer",
     "    float elapsed = (float)(uint32_t)((uint32_t)WorldTimer"),

    # -- the wipers ---------------------------------------------------------
    ("wipers-ignores-state", CC,
     "    if (c->WiperState != 0)" + NL + "        return;",
     "    if (0)" + NL + "        return;"),
    ("wipers-start-le-now", CC,
     "    if (start < now) {",
     "    if (start <= now) {"),
    ("wipers-start-gt-now", CC,
     "    if (start < now) {",
     "    if (now < start) {"),
    ("wipers-keeps-old-window", CC,
     "        if (!(now < end)) {" + NL +
     "            start = on;" + NL +
     "            c->WiperOnTime = on;" + NL +
     "        }",
     "        if (now < end) {" + NL +
     "            start = on;" + NL +
     "            c->WiperOnTime = on;" + NL +
     "        }"),
    ("wipers-later-request-wins", CC,
     "        if (on < start) {",
     "        if (start < on) {"),
    ("wipers-extend-le", CC,
     "    if (end < off) {",
     "    if (off < end) {"),
    ("wipers-round-down", CC,
     "    c->WiperOffTime = (span + (CAR_WIPER_PERIOD_FRAMES - 1))",
     "    c->WiperOffTime = (span)"),
    ("wipers-round-from-zero", CC,
     "                      / CAR_WIPER_PERIOD_FRAMES * CAR_WIPER_PERIOD_FRAMES" + NL +
     "                      + start;",
     "                      / CAR_WIPER_PERIOD_FRAMES * CAR_WIPER_PERIOD_FRAMES;"),
    ("wipers-span-backwards", CC,
     "    span = end - start;",
     "    span = start - end;"),

    # -- the forwarder ------------------------------------------------------
    ("w2c-offset-zero", CC,
     "    carstate_world_to_car2(&c->State, out, in);",
     "    carstate_world_to_car2((CarState *)c, out, in);"),
    ("w2c-args-swapped", CC,
     "    carstate_world_to_car2(&c->State, out, in);",
     "    carstate_world_to_car2(&c->State, (bVector2 *)in, out);"),

    # -- the steering -------------------------------------------------------
    ("steering-signed", CC,
     "uint16_t car_get_steering(Car *c)" + NL + "{" + NL +
     "    return c->pCarDriver->Steering;",
     "uint16_t car_get_steering(Car *c)" + NL + "{" + NL +
     "    return (uint16_t)(int16_t)c->pCarDriver->Steering;"),
]

EQUIVALENT = {
    # -2^31 is its own saturation value: it is exactly representable as both
    # a float32 and an int32, so clamping it and converting it give the same
    # word. The boundary can be spelled either way and no fixture can tell.
    "trunc-neg-threshold-le":
        "saturating exactly -2^31 yields the value the conversion already "
        "yields",

    # This one is equivalent *on this host*, and that is the whole point of
    # naming it. x86-64's `cvttss2si` returns 0x80000000 for every value it
    # cannot represent, so deleting the negative arm changes nothing the
    # harness can observe -- while on the R5900 and on ARM the arm and the
    # instruction already agree too. What the arm buys is not a different
    # answer but a defined one: without it the conversion is UB, and a
    # compiler that constant-folds it is entitled to produce anything at all.
    # The positive arm, by contrast, is a real behaviour change on this host
    # and its three mutations are all caught.
    "trunc-no-neg-saturation":
        "x86 cvttss2si already returns 0x80000000 below range; the arm "
        "removes undefined behaviour rather than changing a result",

    # `1.0f / 4000.0f` and the literal are the same float32 word, 0x3983126f:
    # the correctly-rounded float32 of 1/4000 is the image's constant exactly.
    # car.c used to claim in a comment that the quotient came out one ulp low.
    # It does not, and this mutation is what said so -- it survived with a
    # clean transcript because there was nothing to catch. The genuinely
    # different word is 0x3983126e, which `tick-is-quarter-milli` spells and
    # the two [*-tick] boundary scenarios catch.
    "tick-is-one-over-4000":
        "the quotient rounds to the image's own word; the two spellings are "
        "bit-identical",

    # `Steering` is a uint16_t. Casting a 16-bit value to int16_t and back to
    # uint16_t reproduces every bit of it -- the sign extension the detour
    # introduces is truncated away again by the return type. The mutation is
    # the identity, which is the point: it documents that the `lhu` in the
    # listing is load-and-return with nothing in between, and that a reader
    # who "fixes" the signedness here changes nothing.
    "steering-signed":
        "a uint16_t round-tripped through int16_t is the identity",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

_seen = set()
for _m in MUTATIONS:
    assert _m[0] not in _seen, _m[0]
    _seen.add(_m[0])


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="car_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="car_test")
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
        exe = hostbuild.build(tmp, SOURCES, name="car_test")
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
