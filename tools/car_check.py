"""Cross-check 3DS Files/source/car.c against a model of Car, slices one to three.

Car is the hub of task 25 -- eighty methods, 22876 bytes, a 2016-byte
record -- and it is not the physics. The simulation lives in the movers
that `SetMovementMode` constructs; Car owns the state they write into and
hands everything else off. Thirty-four of the eighty make no call outside
the class at all.

Slice one is the seventeen of those that also need no vtable: the three
empty ones, the blinking, the two effect gates, the debug checksum, the
two wheel aggregates, the forward acceleration, the horn request, the
wiper window and the borrowed steering angle -- and Car::WorldToCar.
Slice two is the vtable seam, the nine dispatchers, three borrowed
fields, the draft and the static initialiser, which is run in mipsemu
rather than read. Slice three is seven methods that call out into code
ported already: where the other cars are, the post-collision yaw boost,
IsDrifting, and ComputeFakeRPM with its smooth<float>. What is left and
what each piece waits on is listed at the bottom of car.c, and the
write-up is docs/formats/car.md.

Six things in slice one are easy to transcribe wrongly, and none of them
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

**HonkAndOrBlinkHeadlights sums `(On + Off) + SecondOn`, with the OLD
durations.** Retail's 0x00134154 adds Off to On and 0x00134160 adds the
second on phase's duration, all before the new values are stored. The
demo's `On + Off + On`, two thirds of a cycle, or the new durations, is a
different guard. The honk and the headlights are retail's (0x00134130 and
0x00134198): retail takes the second duration as a third float, where the
demo's ran the first twice, and its UpdateHeadlightsAndHorn ends the gap
On after the first phase, not Off.

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
import engine_check as EN
import graph_check as GR

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

# Slice one's only call out of the class is Car::WorldToCar's tail call
# into CarState, so the CarState slice and the four files under it come
# along. Slice two adds the registry, the World pointer, and the Graph and
# Table the draft looks its answer up in. None of those is under test here
# -- each has its own checker -- but linking the real ones rather than
# stubbing them is what makes the fixtures mean anything.
SOURCES = [
    "tools/src/car_test.c",
    "3DS Files/source/car.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/world.c",
    "3DS Files/source/graph.c",
    "3DS Files/source/table.c",
]

CH = "3DS Files/source/car.h"
CC = "3DS Files/source/car.c"
# ee_trunc_w moved here from car.c when PhysicsCar became its second
# caller; its mutations moved with it.
EF = "3DS Files/source/eefpu.h"
TH = "3DS Files/source/topology.h"
CTL = "3DS Files/source/carcontroller.h"
CD = "3DS Files/source/cardriver.h"
CB = "3DS Files/source/collisionbody.h"
S3 = "3DS Files/source/sound3d.h"
WH = "3DS Files/source/world.h"
VTC = "3DS Files/source/vtable.c"
VTH = "3DS Files/source/vtable.h"

PTR = 8                       # the host, not the port
SLACK = PTR - 4

f32 = bmath_check.f32
bits = bmath_check.bits
fadd = bvector_check.fadd
fsub = bvector_check.fsub
fmul = bvector_check.fmul
fdiv = bvector_check.fdiv
fsqrt = bvector_check.fsqrt

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


def honk(car, now, on, off, second, blink, hk, two):
    """Retail's 0x00134130. `car` is a dict and is updated in place."""
    dt = f32(float(i32(now - car["start"])))
    elapsed = fmul(dt, TICK)
    # 0x00134154  add.s $f0,$f0,$f2 (On + Off), then 0x00134160
    # add.s $f0,$f0,$f4 (+ SecondOn, retail's 2088)
    cycle = fadd(fadd(car["on"], car["off"]), car["second"])
    # 0x00134164  c.lt.s $f0,$f1  -- cycle < elapsed
    if cycle < elapsed:
        car["two"] = two
        car["start"] = now
        car["on"] = on
        car["off"] = off
        car["second"] = second
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
    # 2192: the demo's 2016 with retail's 704-byte TopologyCoordinate for
    # the demo's 560, and after it retail's four new fields (car.h).
    emit("  %-28s %d" % ("sizeof Car", at(2192, 188)))
    emit("  %-28s %d" % ("sizeof CarNode", 2 * PTR))
    emit("  %-28s %d" % ("sizeof CarState", at(1024, 2)))
    emit("  %-28s %d" % ("sizeof TopologyCoordinate", at(704, 162)))
    emit("  %-28s %d" % ("sizeof TrackPathCoordinate", at(40, 4)))
    emit("  %-28s %d" % ("sizeof OverrideRenderingPos", 96))
    # 24: the demo's 20 and retail's EliminatedRank after it (car.h).
    emit("  %-28s %d" % ("sizeof DriverInfo", at(24, 2)))
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
            ("off TheTrackPathCoordinate", 1984, 178),
            ("off CopLights", 2024, 182),
            ("off SignalLightState", 2028, 182),
            ("off HeadlightsAndHornStart", 2048, 182),
            ("off TheSirenMode", 2068, 182),
            ("off WiperOnTime", 2072, 182),
            ("off WiperOffTime", 2076, 182),
            ("off WiperState", 2080, 182),
            ("off pCarDamage", 2084, 183),
            ("off BlownTireBits", 2088, 184),
            ("off NumBlownTires", 2089, 184),
            ("off pBaseCarSound", 2096, 184),
            ("off ResetMe", 2100, 185),
            ("off BlinkTimer", 2104, 185),
            ("off BlinkDuration", 2108, 185),
            ("off LastInTroughPosition", 2112, 185),
            ("off bPoofed", 2120, 185),
            ("off bVisibleOnTrackMap", 2124, 185),
            ("off NumTimesSkidding", 2128, 185),
            ("off RoadBumpBits", 2132, 185),
            ("off pCaffeineObj", 2136, 186),
            ("off LeaveCarTrails", 2144, 188),
            ("off ForceBuzzTime", 2148, 188),
            ("off fAngleToCamera", 2152, 188),
            ("off vOldPos", 2160, 188),
            ("off SecondOnDuration", 2176, 188),
            ("off JustResetFrames", 2180, 188),
            ("off InDeepWaterRegistered", 2184, 188)):
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
          "second": f32(0.0), "blink": 0, "honk": 0, "two": 0}
    honk(_c, 4000, f32(0.75), f32(0.125), f32(0.375), 1, 1, 1)
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
    # -1 is the constructor's SecondOn.
    old_seconds = [f32(0.0), f32(0.75), f32(-1.0)]

    emit("[honk]")
    for now in nows:
        for st in starts:
            for oon in old_ons:
                for ooff in old_offs:
                    for osec in old_seconds:
                        car = {"start": st, "on": oon, "off": ooff,
                               "second": osec,
                               "blink": 0, "honk": 0, "two": 0}
                        honk(car, now, f32(0.75), f32(0.125), f32(0.375),
                             1, 1, 1)
                        emit("  now %-12d start %-12d old %s %s %s"
                             % (now, st, g9(oon), g9(ooff), g9(osec)))
                        emit("    -> start %-12d on %s off %s second %s "
                             "blink %d honk %d two %d"
                             % (car["start"], g9(car["on"]), g9(car["off"]),
                                g9(car["second"]), car["blink"],
                                car["honk"], car["two"]))

    emit("[honk drop]")
    car = {"start": 0, "on": f32(5.0), "off": f32(5.0), "second": f32(5.0),
           "blink": 9, "honk": 8, "two": 7}
    honk(car, 0, f32(0.75), f32(0.125), f32(0.375), 1, 1, 1)
    emit("  blink %d honk %d two %d on %s off %s second %s start %d"
         % (car["blink"], car["honk"], car["two"],
            g9(car["on"]), g9(car["off"]), g9(car["second"]),
            car["start"]))

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

    model_slice2()
    model_slice3()
    model_refusals()
    return list(OUT)


# ================================================================ slice two
#
# Everything below reads the image three ways: gp-relative constants by
# word, instruction immediates by decoding the instruction at a listed
# address, and the static tables by *running* _GLOBAL_$I$fDraftFalloff in
# mipsemu -- constructors and all -- and reading back what it left in
# memory. None of it comes from car.c or car.h.

def insn(addr):
    return struct.unpack("<I", bmath_check.ELF.read(addr, 4))[0]


def imm(addr, op):
    """The signed 16-bit immediate of the instruction at `addr`, which must
    have major opcode `op` -- so a listing address that drifts onto the
    wrong instruction fails here rather than reading some other offset."""
    w = insn(addr)
    assert w >> 26 == op, (hex(addr), hex(w), op)
    v = w & 0xffff
    return v - 0x10000 if v & 0x8000 else v


OP_ADDIU, OP_LUI, OP_LH, OP_LW, OP_LWC1 = 0x09, 0x0f, 0x21, 0x23, 0x31


def slot_at(lh_addr):
    """A dispatch's slot: the `lh a0,S(vt)` of the delta, with the `lw` of
    the function at the next instruction reading S+4."""
    s = imm(lh_addr, OP_LH)
    assert imm(lh_addr + 4, OP_LW) == s + 4, hex(lh_addr)
    return s


# The slots, each from its call site.
SLOT_THINK = slot_at(0x001301ac)          # Think__3Carf
SLOT_ROUTE = slot_at(0x00131750)          # GetRoute__3Car
SLOT_ROUTE_POINT = slot_at(0x00131780)    # GetRoutePoint__3Car
SLOT_OOB = slot_at(0x001317b0)            # GetAmountOutOfBounds__3Car
SLOT_PHYSICS = slot_at(0x0012ff80)        # SetToPhysicsMode__3CarP3Car
SLOT_DRIVE = slot_at(0x001301e0)          # Drive__3Carf
SLOT_START_HONK = slot_at(0x00132654)     # UpdateHeadlightsAndHorn
SLOT_STOP_HONK = slot_at(0x00132690)
SLOT_IS_HONKING = slot_at(0x00132634)
assert slot_at(0x00132670) == SLOT_IS_HONKING
SLOT_SOUND_UPDATE = slot_at(0x001334a0)   # UpdateSound__3Car
SLOT_COLLISIONS = slot_at(0x001316cc)     # IsCollideable__3Car

# The vptr offsets the same sites load, and the object offsets in Car.
assert imm(0x001301a8, OP_LW) == 8        # CarController
assert imm(0x001301dc, OP_LW) == 556      # CarDriver
assert imm(0x00133494, OP_LW) == 28       # Sound3d, inside BaseCarSound
assert imm(0x001316c8, OP_LW) == 80       # CollisionBody
assert imm(0x0013019c, OP_LW) == 40       # Car::pCarController
assert imm(0x001301d8, OP_LW) == 44       # Car::pCarDriver
assert imm(0x00133488, OP_LW) == 1952     # Car::pBaseCarSound
assert imm(0x001316c4, OP_LW) == 52       # Car::pDynamicCollisionBody
assert imm(0x001301a4, 0x39) == 1096      # swc1 -> Car::DraftFactor

# The draft's constants.
DRAFT_COS_W = gpword(-32092)
DRAFT_SCALE_W = gpword(-32088)
DRAFT_EARLY_W = gpword(-32084)
DRAFT_CAP_W = gpword(-32080)
assert imm(0x00130040, OP_LWC1) == -32092
assert imm(0x00130048, OP_LWC1) == -32088
assert imm(0x00130110, OP_LWC1) == -32084
assert imm(0x00130158, OP_LWC1) == -32080
assert (DRAFT_COS_W, DRAFT_SCALE_W, DRAFT_EARLY_W, DRAFT_CAP_W) == (
    0x3f733333, 0x419ffffe, 0x3f666666, 0x3f666666)
DRAFT_COS = bits(DRAFT_COS_W)
DRAFT_SCALE = bits(DRAFT_SCALE_W)
DRAFT_EARLY = bits(DRAFT_EARLY_W)
DRAFT_CAP = bits(DRAFT_CAP_W)

# UpdateHeadlightsAndHorn's copy of the tick, the third one.
assert imm(0x0013258c, OP_LWC1) == -31988
assert gpword(-31988) == TICK_A

# GetTrackedAcceleration: `addiu v1,zero,1` is REAL_CONTROL, and the
# `lwc1 $f0,20(v0)` is TrackedController::Acceleration.
TRACKED_MODE = imm(0x0012ff44, OP_ADDIU)
assert imm(0x0012ff60, OP_LWC1) == 20

# UpdateSound's two floats are one `lui 0x3f80`.
SOUND_ARG = bits(imm(0x00133498, OP_LUI) << 16)

SYM = bmath_check.ELF.syms


def sym(name):
    return SYM[name][0]


# The car sounds' tables are retail's in the port (carsound.h, step 14-3):
# carsound.c installs them there, so the demo's addresses would name no
# table.
RETAIL_VT = {
    "_vt$12BaseCarSound": 0x002b4968,
    "_vt$18BasePlayerCarSound": 0x002b4920,
    "_vt$14BaseAICarSound": 0x002b48d8,
}


def sym_at(addr):
    names = sorted(k for k, v in SYM.items() if v[0] == addr
                   and not k.startswith("_GLOBAL_"))
    return names[0] if names else "?"


# ------------------------------------------------ the static initialiser

STATIC = (
    ("vDraftSpeedRange", 32), ("tDraftFalloff", 20),
    ("gDraftSpeedRange", 8), ("vRoadNoiseSpeedData", 16),
    ("gRoadNoiseSpeedScale", 8), ("ObjectPoints", 13 * 16),
    ("DamageAboveMatrix", 64), ("PostCollisionYawControlProfileData", 32),
    ("PostCollisionYawControlProfile", 8),
)


def run_static_init():
    import mipsemu
    e = mipsemu.Emu()
    before = sum(1 for name, n in STATIC
                 for b in e.mem[sym(name):sym(name) + n] if b)
    e.call("_GLOBAL_$I$fDraftFalloff")

    def w(a):
        return struct.unpack_from("<I", e.mem, a)[0]

    return e, w, before


def f32w(w):
    return bits(w)


# --------------------------------------------------------------- the draft

def fdivz(a, b):
    """div.s as IEEE has it, which Python's `/` does not: a zero divisor
    gives a signed infinity, or a NaN over a zero or NaN numerator."""
    if b == 0.0:
        if a == 0.0 or a != a:
            return float("nan")
        return math.copysign(float("inf"), a) * math.copysign(1.0, b)
    return fdiv(a, b)


class Draft(object):
    """The four knees, the falloff Table and the speed Graph, as the
    initialiser left them."""

    def __init__(self, w):
        base = sym("vDraftSpeedRange")
        # `lui v0,0x002f; addiu v0,v0,-31552` is vDraftSpeedRange, and the
        # two thresholds are read at +8 and +28 of it.
        assert (0x002f << 16) + imm(0x0012ffd4, OP_ADDIU) == base
        assert imm(0x0012ffe4, OP_LWC1) == 8
        assert imm(0x00130028, OP_LWC1) == 28
        self.knee = f32w(w(base + 8))
        self.cap = f32w(w(base + 28))

        g = sym("gDraftSpeedRange")
        assert GP + imm(0x001300bc, OP_ADDIU) == g
        pts = w(g)
        self.n = w(g + 4)
        self.points = [(f32w(w(pts + 8 * i)), f32w(w(pts + 8 * i + 4)))
                       for i in range(self.n)]

        t = sym("tDraftFalloff")
        assert (0x002f << 16) + imm(0x001300d0, OP_ADDIU) == t
        self.table = EN.Table()
        n = w(t + 4)
        self.table.entries = [f32w(w(w(t) + 4 * i)) for i in range(n)]
        self.table.n = n
        self.table.lo = f32w(w(t + 8))
        self.table.hi = f32w(w(t + 12))
        self.table.mult = f32w(w(t + 16))


def draft_from(D, me, other):
    """0x0012ffc8. `me` and `other` are (pos, vel, speed) triples."""
    pos0, _, _ = me
    pos1, vel, speed = other

    # c.lt.s speed, knee -> bc1t out
    if speed < D.knee:
        return 0.0

    # vsub other - c; vmul.xyz; vaddy.x; vaddz.x; sqrt.s
    d = [fsub(pos1[i], pos0[i]) for i in range(3)]
    len2 = fadd(fadd(fmul(d[0], d[0]), fmul(d[1], d[1])), fmul(d[2], d[2]))
    dist = fsqrt(len2)

    # c.lt.s cap, dist -> bc1t out
    if D.cap < dist:
        return 0.0

    # vmul.xyz; vaddy.x; vaddz.x; vrsqrt Q = 1 / sqrt; vmulx.xyzw
    v2 = fadd(fadd(fmul(vel[0], vel[0]), fmul(vel[1], vel[1])),
              fmul(vel[2], vel[2]))
    q = fdivz(1.0, fsqrt(v2))
    nv = [fmul(vel[i], q) for i in range(3)]

    dot = fadd(fadd(fmul(d[0], nv[0]), fmul(d[1], nv[1])), fmul(d[2], nv[2]))

    # div.s; sub.s; mul.s; c.lt.s f, 0 -> bc1f on
    f = fmul(fsub(fdivz(dot, dist), DRAFT_COS), DRAFT_SCALE)
    if f < 0.0:
        return 0.0

    g = GR.graph_get_value(D.points, D.n, speed)
    return EN.table_get_value(D.table, fdivz(dist, fmul(f, g)))


def draft_sum(D, me, table, n):
    """0x001300f0. `table` holds cars, `"self"` or None; None is a car the
    loop must not reach."""
    s = 0.0
    i = 0
    while i < n:
        o = table[i]
        if o != "self":
            assert o is not None, "the loop read a null CarTable entry"
            s = fadd(s, draft_from(D, me, o))
        # c.le.s early, sum -> bc1f loop
        if DRAFT_EARLY <= s:
            break
        i += 1
    # min.s
    return s if s < DRAFT_CAP else DRAFT_CAP


def gx(x):
    return "%08x" % struct.unpack("<I", struct.pack("<f", x))[0]


# The fakes' own table deltas, chosen by the harness: each class that gets
# a table gets one entry with delta 0 and one with a nonzero delta, so the
# transcript shows the adjustment being applied.
DELTA = {
    "_vt$14RealController": 0, "_vt$15AICarController": 4,
    "_vt$10NullDriver": 0, "_vt$9CarDriver": 8,
    "_vt$12BaseCarSound": 0, "_vt$14BaseAICarSound": 4,
    "_vt$16CarCollisionBody": 0, "_vt$20DynamicCollisionBody": 12,
}

ABORT_MODES = (
    ("vt-missing", "vt_slot: no entry at +8 of the vtable at 0x00123450"),
    ("vt-reset", "vt_slot: no entry at +8 of the vtable at 0x00123450"),
    ("vt-misaligned", "vt_slot: no entry at +12 of the vtable at 0x00123450"),
    ("vt-slot-zero", "vt_slot: no entry at +0 of the vtable at 0x00123450"),
    ("vt-negative", "vt_slot: no entry at +-8 of the vtable at 0x00123450"),
    ("vt-past-end", "vt_slot: no entry at +40 of the vtable at 0x00123450"),
    ("vt-null-fn", "vt_slot: no entry at +16 of the vtable at 0x00123450"),
    ("vt-full", "vt_install: more than 96 vtables [96 installed]"),
)


def model_slice2():
    def at(n, k):
        return n + k * SLACK

    def rnd(n):
        return (n + PTR - 1) // PTR * PTR

    def p(tag, v):
        emit("  %-28s %d" % (tag, v))

    # -- layout 2 -----------------------------------------------------------
    emit("[layout 2]")
    p("sizeof CarController", rnd(at(12, 2)))
    p("off CarController Driver", at(4, 1))
    p("off CarController vptr", at(8, 2))
    p("off Tracked RoutePoint", at(12, 3))
    p("off Tracked Acceleration", at(20, 4))
    p("off Tracked PrevSpeed", at(24, 4))
    p("off CarDriver vptr", 556)
    p("sizeof Sound3d", 32)
    p("off Sound3d vptr", 28)
    p("sizeof CollisionBody", rnd(at(84, 4)))
    p("off CollisionBody vptr", at(80, 4))
    p("sizeof DynamicCollisionBody", rnd(at(256, 9)))
    p("off Dynamic PhysicsMode", at(84, 5))
    # lqc2 vf1,224(v0) and lqc2 vf2,240(v0) in GetCarSpaceBoundingBox.
    assert imm(0x001334c4, 0x36) == 224 and imm(0x001334cc, 0x36) == 240
    p("off Dynamic LocalBBMin", at(224, 9))
    p("off Dynamic LocalBBMax", at(240, 9))
    # DynamicCollisionBody rounds up to a pointer before pCar.
    base = rnd(at(256, 9))
    p("sizeof CarCollisionBody", rnd(base + (336 - 256) + 4 * 0 + SLACK))
    p("off CarBody pCar", base)
    # lw v0,260(v1) in GetLastPenetrationTime.
    assert imm(0x001334e8, OP_LW) == 260
    p("off CarBody LastPenetration", base + PTR)
    p("off CarBody LastYawControl", base + PTR + 4)
    p("off CarBody InertiaTensor", base + PTR + 12)
    p("sizeof Timer", 4)
    # lw v0,28(v1) and lw a1,44(v0) in CalculateDraftFactor__3Car.
    assert imm(0x0013011c, OP_LW) == 28 and imm(0x00130130, OP_LW) == 44
    p("off World TotalNumCars", at(28, 7))
    p("off World CarTable", at(44, 7))
    p("world max cars", (100 - 44) // 4)
    # lwc1 $f3,12(v1) in IsFacingWrongWay.
    assert imm(0x001318e4, OP_LWC1) == 12
    p("off TRP Direction", 12)
    # Car+144 is State (64) + BodyMatrix; Car+960 is State + the speed.
    assert imm(0x001318d8, OP_LWC1) == 144
    assert imm(0x0012ffe0, OP_LWC1) == 960
    p("off CarState BodyMatrix", at(144 - 64, 2))
    p("off CarState VelocityMag", at(960 - 64, 2))

    for tag, name in (
            ("vt CarController", "_vt$13CarController"),
            ("vt NullController", "_vt$14NullController"),
            ("vt AICarController", "_vt$15AICarController"),
            ("vt RealController", "_vt$14RealController"),
            ("vt CarDriver", "_vt$9CarDriver"),
            ("vt NullDriver", "_vt$10NullDriver"),
            ("vt BaseCarSound", "_vt$12BaseCarSound"),
            ("vt BasePlayerCarSound", "_vt$18BasePlayerCarSound"),
            ("vt BaseAICarSound", "_vt$14BaseAICarSound"),
            ("vt CollisionBody", "_vt$13CollisionBody"),
            ("vt DynamicCollisionBody", "_vt$20DynamicCollisionBody"),
            ("vt CarCollisionBody", "_vt$16CarCollisionBody")):
        emit("  %-28s %08x" % (tag, RETAIL_VT.get(name) or sym(name)))

    p("slot Think", SLOT_THINK)
    p("slot GetCurrentRoute", SLOT_ROUTE)
    p("slot GetCurrentRoutePoint", SLOT_ROUTE_POINT)
    p("slot GetAmountOutOfBounds", SLOT_OOB)
    p("slot SetToPhysicsMode", SLOT_PHYSICS)
    p("slot Drive", SLOT_DRIVE)
    p("slot StartHonkHorn", SLOT_START_HONK)
    p("slot StopHonkHorn", SLOT_STOP_HONK)
    p("slot IsHonking", SLOT_IS_HONKING)
    p("slot Sound3d Update", SLOT_SOUND_UPDATE)
    p("slot AreCollisionsEnabled", SLOT_COLLISIONS)
    p("vt slot 104", 104 // 8)

    # -- static init --------------------------------------------------------
    e, w, before = run_static_init()
    emit("[static init]")
    p("nonzero before init", before)

    fd = sym("fDraftFalloff")
    for i in range(6):
        emit("  fDraftFalloff[%d] %08x" % (i, w(fd + 4 * i)))
    vr = sym("vDraftSpeedRange")
    for i in range(4):
        emit("  vDraftSpeedRange[%d] %08x %08x"
             % (i, w(vr + 8 * i), w(vr + 8 * i + 4)))
    t = sym("tDraftFalloff")
    emit("  tDraftFalloff table %s n %d min %08x max %08x mult %08x"
         % (sym_at(w(t)), w(t + 4), w(t + 8), w(t + 12), w(t + 16)))

    def graph(name):
        g = sym(name)
        emit("  %s points %s n %d" % (name, sym_at(w(g)), w(g + 4)))

    graph("gDraftSpeedRange")
    rn = sym("vRoadNoiseSpeedData")
    for i in range(2):
        emit("  vRoadNoiseSpeedData[%d] %08x %08x"
             % (i, w(rn + 8 * i), w(rn + 8 * i + 4)))
    graph("gRoadNoiseSpeedScale")
    op = sym("ObjectPoints")
    for i in range(13):
        emit("  ObjectPoints[%d] %s" % (i, " ".join(
            "%08x" % w(op + 16 * i + 4 * j) for j in range(4))))
    dm = sym("DamageAboveMatrix")
    for i in range(4):
        emit("  DamageAboveMatrix[%d] %s" % (i, " ".join(
            "%08x" % w(dm + 16 * i + 4 * j) for j in range(4))))
    pc = sym("PostCollisionYawControlProfileData")
    for i in range(4):
        emit("  PostCollisionYawControlProfileData[%d] %08x %08x"
             % (i, w(pc + 8 * i), w(pc + 8 * i + 4)))
    graph("PostCollisionYawControlProfile")

    D = Draft(w)

    # -- draft from ---------------------------------------------------------
    speeds = [f32(x) for x in (0.5, 0.99999994, 1.0, 1.00000012, 3.0, 5.0,
                               100.0, 150.0, 200.0)]
    rels = [[f32(x) for x in r] for r in (
        (12.0, 0.0, 0.0), (0.0, 12.0, 0.0), (-12.0, 0.0, 0.0),
        (6.0, 1.0, 0.0), (6.0, 1.97, 0.0), (6.0, 1.98, 0.0),
        (59.9, 0.0, 0.0), (60.0, 0.0, 0.0), (60.0001, 0.0, 0.0),
        (3.0, 4.0, 12.0), (0.001, 0.0, 0.0), (30.0, 0.0, -2.5),
        (0.06, 0.0197, 0.0), (0.06, 0.0198, 0.0), (1.5, 2.0, 0.0))]
    vels = [[f32(x) for x in v] for v in (
        (10.0, 0.0, 0.0), (3.0, 4.0, 0.0), (1.0, 0.5, 2.0),
        (-10.0, 0.0, 0.0))]
    origin = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0.0)

    def pd(tag, r):
        emit("  %s -> %s %s" % (tag, g9(r), gx(r)))

    emit("[draft from]")
    for s in speeds:
        for ri, r in enumerate(rels):
            for vi, v in enumerate(vels):
                pd("spd %s rel %d vel %d" % (g9(s), ri, vi),
                   draft_from(D, origin, (r, v, s)))

    emit("[draft pairs]")
    for i, pr in enumerate((
            (100.0, -50.0, 3.0, 112.0, -50.0, 3.0),
            (112.0, -50.0, 3.0, 100.0, -50.0, 3.0),
            (-7.5, 2.25, 0.0, 4.5, 2.25, 1.0),
            (1000.0, 1000.0, 0.0, 1010.0, 1005.0, 0.0))):
        pr = [f32(x) for x in pr]
        me = (pr[0:3], [f32(-3.0), 0.0, 0.0], f32(0.25))
        other = (pr[3:6], [f32(10.0), 0.0, 0.0], f32(120.0))
        pd("pair %d" % i, draft_from(D, me, other))

    # Each case turns one rounding on: dot / dist above 1 exactly at the
    # reach, and a few ulps past it; then the two groupings of the sums.
    emit("[draft rounding]")
    for i, rc in enumerate((
            (35.793, 32.2137, 35.793, 6.3, 5.67, 6.3, 200.0),
            (47.6164, 16.52, -32.5541, 9.8, 3.4, -6.7, 200.0),
            (9.3, 19.2, 20.8, 3.11, 6.4, 6.95, 100.0),
            (18.5, 4.0, -1.25, 9.0, 2.0, -0.75, 100.0))):
        rc = [f32(x) for x in rc]
        pd("round %d" % i, draft_from(D, origin, (rc[0:3], rc[3:6], rc[6])))

    fast = [f32(10.0), 0.0, 0.0]
    leaders = {
        "A": ([f32(12.0), 0.0, 0.0], fast, f32(200.0)),
        "B": ([f32(24.0), 0.0, 0.0], fast, f32(200.0)),
        "C": ([f32(48.0), 0.0, 0.0], fast, f32(200.0)),
        "D": ([0.0, f32(12.0), 0.0], fast, f32(200.0)),
        "E": ([f32(36.0), 0.0, 0.0], fast, f32(200.0)),
        "s": "self", "0": None,
    }

    def world(cars):
        return [leaders[ch] for ch in cars]

    emit("[draft sum]")
    for cars, n in (("", 0), ("s", 1), ("C", 1), ("CD", 2), ("CsC", 3),
                    ("CCC0", 4), ("A0", 2), ("BC0", 3), ("CCB", 2),
                    ("DsD", 3), ("sA0", 3), ("CsCsC", 5), ("BB", 2),
                    ("CB", 2), ("CEC", 3)):
        # c moves at 30, which the sum never reads: it skips c.
        pd('world "%s" n %d' % (cars, n),
           draft_sum(D, ([0.0, 0.0, 0.0], [f32(30.0), 0.0, 0.0], f32(30.0)),
                     world(cars), n))

    # -- the registry -------------------------------------------------------
    # Port-side: vt_install replaces on a repeat address, keeps tables
    # apart, and vt_this is a byte add.
    emit("[vtable]")
    emit("  X+8 -> 1 delta 0")
    emit("  X+16 -> 1 delta -8")
    emit("  X+8 after replace -> 2 delta 0")
    emit("  X+16 after replace -> 2 delta 16")
    emit("  Y+8 -> 3 delta 0")
    emit("  X+8 beside Y -> 2 delta 0")
    emit("  this -8 -> 24")
    emit("  this +24 -> 56")

    ctl = {0: "ctl+%d" % DELTA["_vt$14RealController"],
           1: "ctl+%d" % DELTA["_vt$15AICarController"]}

    # -- think --------------------------------------------------------------
    emit("[think]")
    for wi, (cars, n) in enumerate((("C", 1), ("BC0", 3), ("", 0))):
        for v in range(2):
            for dt in (f32(0.0166666675), 0.0, f32(-0.5)):
                emit("  world %d vt %d dt %s" % (wi, v, g9(dt)))
                # sw of the draft at 0x001301a4 precedes the jalr.
                d = draft_sum(D, origin, world(cars), n)
                emit("    Think(%s, %s) sees draft %s"
                     % (ctl[v], g9(dt), g9(d)))
                emit("    after draft %s" % g9(d))

    # -- drive --------------------------------------------------------------
    emit("[drive]")
    drv = {0: "driver+%d" % DELTA["_vt$10NullDriver"],
           1: "driver2+%d" % DELTA["_vt$9CarDriver"]}
    for v in range(2):
        for dt in (f32(0.0333333351), f32(2.5)):
            emit("  driver %d dt %s" % (v, g9(dt)))
            emit("    Drive(%s, %s)" % (drv[v], g9(dt)))

    # -- route --------------------------------------------------------------
    emit("[route]")
    for v in range(2):
        emit("  vt %d" % v)
        emit("    GetCurrentRoute(%s)" % ctl[v])
        emit("    route is g_route 1")
        emit("    GetCurrentRoutePoint(%s)" % ctl[v])
        emit("    point is g_rp 1")
        for oob in (0.0, f32(-2.5), f32(1e30)):
            emit("    GetAmountOutOfBounds(%s)" % ctl[v])
            emit("    oob %s" % g9(oob))

    # -- sound --------------------------------------------------------------
    emit("[sound]")
    emit("  no sound")
    for v, name in enumerate(("_vt$12BaseCarSound", "_vt$14BaseAICarSound")):
        emit("  vt %d" % v)
        # a1 is zeroed in the delay slot of the null test.
        emit("    Update(sound+%d, %s, 0, %s)"
             % (DELTA[name], g9(SOUND_ARG), g9(SOUND_ARG)))

    # -- collideable --------------------------------------------------------
    emit("[collideable]")
    for b, (timer, dur) in enumerate(((0, 0.0), (9000, 1.0), (1000, 1.0))):
        for v, name in enumerate(("_vt$16CarCollisionBody",
                                  "_vt$20DynamicCollisionBody")):
            for ans in (0, 1, 2, -1):
                emit("  blink %d vt %d answer %d" % (b, v, ans))
                if not is_blinking(timer, 10000, f32(dur)):
                    emit("    AreCollisionsEnabled(body+%d) = %d"
                         % (DELTA[name], ans))
                    # sltu s1,zero,v0
                    emit("    -> %d" % (1 if ans & 0xffffffff else 0))
                else:
                    emit("    -> 0")

    # -- wrong way ----------------------------------------------------------
    emit("[wrong way]")
    fwds = [[f32(x) for x in f] for f in (
        (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.6, 0.8), (1e-20, 0.0),
        (-0.6, 0.8), (0.0, -1.0))]
    dirs = [[f32(x) for x in d] for d in (
        (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (0.6, -0.8))]
    for fi, fw in enumerate(fwds):
        for di, dr in enumerate(dirs):
            emit("  fwd %d dir %d" % (fi, di))
            emit("    GetCurrentRoutePoint(%s)" % ctl[0])
            # mul.s 144*12; mul.s 148*16; add.s; c.lt.s 0, dot
            dot = fadd(fmul(fw[0], dr[0]), fmul(fw[1], dr[1]))
            emit("    -> %d" % (0 if 0.0 < dot else 1))

    # -- headlights ---------------------------------------------------------
    # Retail's 0x00134198.
    def lights(now, start, on, off, second, two, blink, hk, force, honking,
               dname, dname2=None):
        elapsed = fmul(f32(float(i32(now - start))), TICK)
        if elapsed < on:
            lit = 1
        else:
            t = fsub(elapsed, on)
            # 0x001341ec  c.lt.s $f2,$f3 -- f3 still On, where the demo's
            # 0x001325c0 compared with Off
            if t < on:
                lit = 1 if two == 0 else 0          # sltiu a0,v0,1
            else:
                # 0x0013420c  t - Off, 0x00134210  < SecondOn (2088)
                lit = 1 if fsub(t, off) < second else 0
        state = 1 if (lit and blink != 0) else (1 if force != 0 else 0)
        honk = (1 if hk != 0 else 0) if lit else 0
        emit("    IsHonking(%s) = %d" % (dname, honking))
        # The second call of each pair reloads Car::pCarDriver.
        d2 = dname2 or dname
        if honk and not honking:
            emit("    StartHonkHorn(%s)" % d2)
        elif not honk and honking:
            emit("    StopHonkHorn(%s)" % d2)
        return state

    emit("[headlights]")
    for tk in (0, 1000, 2000, 2500, 3000, 3500, 4000, 4250, 4500, 4750,
               5000, 8000, -400):
        for two in (0, 1):
            for bl in (0, 1):
                for hk in (0, 5):
                    for fo in (0, 1):
                        for hs in (0, 3):
                            emit("  t %d two %d blink %d honk %d force %d "
                                 "is %d" % (tk, two, bl, hk, fo, hs))
                            st = lights(50000 + tk, 50000, f32(0.5),
                                        f32(0.25), f32(0.375), two,
                                        7 if bl else 0, hk,
                                        2 if fo else 0, hs, drv[0])
                            emit("    lights %d" % st)

    # lw v0,24(s0); bne -> out: a player's car gets nothing.
    assert imm(0x00132578, OP_LW) == 24
    emit("[headlights player]")
    emit("  lights 9")

    emit("[headlights reload]")
    for h in (0, 1):
        emit("  honk %d" % h)
        lights(0, 0, f32(1.0), 0.0, 0.0, 0, 0, h, 0, 0 if h else 1,
               drv[0], drv[1])

    # -- bbox ---------------------------------------------------------------
    lo = [f32(x) for x in (-1.5, -2.5, -0.25, 11.0)]
    hi = [f32(x) for x in (1.5, 2.5, 1.75, -13.0)]

    def v4(tag, v):
        emit("  %s %s" % (tag, " ".join(gx(x) for x in v)))

    # lqc2 224 -> sqc2 (a1), then lqc2 240 -> sqc2 (a2): the whole
    # quadword, pad lane included, min first.
    emit("[bbox]")
    v4("min", lo)
    v4("max", hi)
    emit("[bbox alias max]")
    v4("max out", lo)
    v4("body max", lo)
    emit("[bbox alias min]")
    v4("min out", lo)
    v4("body min", hi)

    # -- penetration --------------------------------------------------------
    emit("[penetration]")
    for word in (0, 1, 0xdeadbeef, 0x80000000):
        emit("  word %08x -> %08x" % (word, word))

    # -- tracked acceleration -----------------------------------------------
    emit("[tracked acceleration]")
    for mode in (-1, 0, 1, 2, 3, 4, 5):
        for acc in (f32(3.5), -0.0):
            r = acc if mode == TRACKED_MODE else 0.0
            emit("  mode %d acc %s -> %s" % (mode, g9(acc), gx(r)))
    # beql: the controller load is annulled when the mode test fails.
    for mode in (-1, 0, 2, 3, 4, 5):
        emit("  mode %d no controller -> %s" % (mode, gx(0.0)))



# ============================================================== slice three
#
# Seven methods that call out of the class, each into a model another
# checker already holds: CarState's WorldToCar and GetYaw (carstate_check),
# bNormalize (bvector_check), Graph::GetValue (graph_check) and bToPolar
# (bmath_check). Every constant, offset and gp displacement below is tied
# to the instruction that loads it, and the tweakables and RPMTable are
# read out of the ELF by symbol.

OP_SLTI, OP_LHU, OP_SWC1 = 0x0a, 0x25, 0x39

# IsCarToLeft / IsCarToRight: `addiu a2,a1,96` is other->State.Position,
# `addiu a0,a0,64` this car's State.
for base in (0x00131ca0, 0x00131ce8):
    assert imm(base + 4, OP_ADDIU) == 96
    assert imm(base + 12, OP_ADDIU) == 64

# GetRelativeCarPosition: Velocity at Car+112, the two Positions at +96
# and +100, `lui at,0x42c8` the 100 both tests share, gp-32032 the 999.
assert imm(0x00130f2c, OP_ADDIU) == 112
assert (imm(0x00130f3c, OP_LWC1), imm(0x00130f40, OP_LWC1),
        imm(0x00130f48, OP_LWC1), imm(0x00130f50, OP_LWC1)) == (100, 100,
                                                                 96, 96)
REL_LIMIT = bits(imm(0x00130f8c, OP_LUI) << 16)
assert imm(0x00130fbc, OP_LWC1) == -32032
REL_FAR = bits(gpword(-32032))
assert imm(0x00130fcc, OP_SWC1) == 0

# IsCarInFront: both Positions, and State.Angle at 868 of Car+64.
assert (imm(0x00131d50, OP_LWC1), imm(0x00131d54, OP_LWC1),
        imm(0x00131d58, OP_LWC1), imm(0x00131d60, OP_LWC1)) == (100, 96,
                                                                 100, 96)
assert imm(0x00131d4c, OP_ADDIU) == 64
assert imm(0x00131d78, OP_LHU) == 868

# GetPostCollisionYawControlBoost: the body at Car+52, its stamp at +264,
# WorldTimer, the tick, `lui at,0x4080`, and the Graph.
assert imm(0x001341d8, OP_LW) == 52
assert imm(0x001341dc, OP_LW) == 264
assert imm(0x001341fc, OP_LW) == -20224
assert imm(0x00134200, OP_LWC1) == -31908
assert gpword(-31908) == TICK_A
YAW_CUTOFF = bits(imm(0x00134208, OP_LUI) << 16)
PCY_GRAPH = sym("PostCollisionYawControlProfile")
assert GP + imm(0x00134230, OP_ADDIU) == PCY_GRAPH

# IsDrifting: `slti v0,v0,2` on nWheelsTouchingGround, gp-31904, and
# `lui at,0x4140` against ForwardSpeed.
assert imm(0x00134268, OP_LW) == 888
DRIFT_WHEELS = imm(0x0013426c, OP_SLTI)
assert imm(0x00134284, OP_LWC1) == -31904
DRIFT_YAW = bits(gpword(-31904))
assert imm(0x00134298, OP_LWC1) == 892
DRIFT_SPEED = bits(imm(0x0013429c, OP_LUI) << 16)

# ComputeFakeRPM. Every gp load names its tweakable; the model then reads
# the tweakable's initial word from the ELF, and a fixture that pokes one
# pokes the model's copy the same way.
for addr, name in ((0x00131084, "TestSpeed"), (0x001310c4, "GearTopSpeed"),
                   (0x001310e4, "MaxSpeedInc"), (0x001310e8, "Gear1To2Speed"),
                   (0x00131104, "GearRTo1Speed"), (0x00131144, "TestRPM"),
                   (0x001311b0, "Gear2To3Speed"), (0x001311b8, "Gear3To4Speed"),
                   (0x001311c0, "Gear4To5Speed"), (0x001311c4, "Gear5To6Speed"),
                   (0x001311c8, "GearTopSpeed"), (0x001311e4, "TestRPM"),
                   (0x00131268, "MaxRPMInc"), (0x00131274, "TestRPM")):
    assert GP + imm(addr, OP_LWC1) == sym(name), (hex(addr), name)
assert imm(0x001310d8, OP_LWC1) == -32028
FAKE_CLAMP = bits(gpword(-32028))
assert imm(0x001310bc, OP_LW) == 900          # CurrentGear, in s2 = Car+64
assert imm(0x001310c0, OP_LWC1) == 896        # VelocityMagnitude
assert imm(0x001310d4, OP_LWC1) == 1152       # Car::OldSpeed
assert imm(0x001310f0, OP_SWC1) == 1152
assert imm(0x00131264, OP_LWC1) == 908        # RPM
assert imm(0x0013129c, OP_SWC1) == 908
FAKE_UNSET = bits(imm(0x00131248, OP_LUI) << 16)
assert bits(imm(0x0013127c, OP_LUI) << 16) == FAKE_UNSET
FAKE_FIRST = imm(0x00131118, OP_ADDIU)        # addiu s1,zero,2
assert insn(0x00131114) == 0x0000882d         # daddu s1,zero,zero: REVERSE
FAKE_LOOP_START = imm(0x001311b4, OP_ADDIU)   # addiu a2,zero,1
FAKE_LOOP_END = imm(0x00131230, OP_SLTI)      # slti v0,a2,6
FAKE_PAIR_BIAS = imm(0x00131158, OP_ADDIU)    # addiu a0,a2,1
FAKE_GEAR_BIAS = imm(0x00131178, OP_ADDIU)    # addiu s1,a2,2
FAKE_GEAR_CAP = imm(0x00131190, OP_ADDIU)     # addiu v1,zero,6
assert imm(0x00131194, OP_SLTI) == FAKE_GEAR_CAP + 1
RPM_TABLE = sym("RPMTable")
for hi, lo in ((0x00131130, 0x00131138), (0x00131160, 0x00131168)):
    assert (imm(hi, OP_LUI) << 16) + imm(lo, OP_ADDIU) == RPM_TABLE
# The pair past the end: RPMTable is 48 bytes, and the next symbol is the
# yaw profile's points.
assert SYM["RPMTable"][1] == 48
assert RPM_TABLE + 48 == sym("PostCollisionYawControlProfileData")

TWEAKS = ("GearRTo1Speed", "Gear1To2Speed", "Gear2To3Speed", "Gear3To4Speed",
          "Gear4To5Speed", "Gear5To6Speed", "GearTopSpeed", "MaxRPMInc",
          "MaxSpeedInc", "TestSpeed", "TestRPM")


def elf_word(addr):
    return struct.unpack("<I", bmath_check.ELF.read(addr, 4))[0]


def smooth(cur, target, rate):
    """0x00134788. add.s, c.lt.s hi,target; sub.s, c.lt.s target,lo."""
    hi = fadd(cur, rate)
    if hi < target:
        return hi
    lo = fsub(cur, rate)
    if target < lo:
        return lo
    return target


class Fake(object):
    """The tweakables, RPMTable and the yaw profile's points, as the image
    and the static initialiser leave them."""

    def __init__(self, w):
        self.T = dict((n, f32w(elf_word(sym(n)))) for n in TWEAKS)
        self.rpm = [f32w(elf_word(RPM_TABLE + 4 * i)) for i in range(12)]
        pc = sym("PostCollisionYawControlProfileData")
        self.pcy = [[f32w(w(pc + 8 * i)), f32w(w(pc + 8 * i + 4))]
                    for i in range(4)]
        # The Graph aliases the array, so a poke to the array is a poke to
        # the Graph.
        assert w(PCY_GRAPH) == pc and w(PCY_GRAPH + 4) == 4


def fake_rpm(F, car):
    """0x00131080. `car` is a dict of vm, old, gear, rpm, updated in place."""
    T = F.T
    speed = T["TestSpeed"] if 0.0 < T["TestSpeed"] else car["vm"]
    if T["GearTopSpeed"] <= speed:
        speed = fsub(T["GearTopSpeed"], FAKE_CLAMP)
    speed = smooth(car["old"], speed, T["MaxSpeedInc"])
    car["old"] = speed

    gear = car["gear"]
    rpm = 0.0
    g12 = T["Gear1To2Speed"]
    R = F.rpm
    if speed < g12:
        gear = FAKE_FIRST if T["GearRTo1Speed"] <= speed else 0
        frac = abs(speed)
        if g12 < frac:                            # bc1tl: the move is taken
            frac = g12
        rpm = fadd(R[0], fmul(fdiv(frac, g12), fsub(R[1], R[0])))
    else:
        sp = [T[n] for n in ("Gear1To2Speed", "Gear2To3Speed",
                             "Gear3To4Speed", "Gear4To5Speed",
                             "Gear5To6Speed", "GearTopSpeed")]
        # What the index reaches: RPMTable, then the eight bytes after it.
        mem = R + F.pcy[0]
        i = FAKE_LOOP_START
        while i < FAKE_LOOP_END:
            if speed < sp[i]:
                k = 2 * (i + FAKE_PAIR_BIAS)
                lo, hi = mem[k], mem[k + 1]
                gear = i + FAKE_GEAR_BIAS
                if not gear < FAKE_GEAR_CAP + 1:  # slti; movz
                    gear = FAKE_GEAR_CAP
                t = fdiv(fsub(speed, sp[i - 1]), fsub(sp[i], sp[i - 1]))
                rpm = fadd(lo, fmul(t, fsub(hi, lo)))
                break
            i += 1

    if car["gear"] == gear:
        cur = car["rpm"] if T["TestRPM"] == FAKE_UNSET else T["TestRPM"]
        rpm = smooth(cur, rpm, T["MaxRPMInc"])
    car["gear"] = gear
    car["rpm"] = rpm if T["TestRPM"] == FAKE_UNSET else T["TestRPM"]


def model_slice3():
    _, w, _ = run_static_init()
    F = Fake(w)

    # -- tweakables ---------------------------------------------------------
    emit("[fake rpm tweakables]")
    for n in TWEAKS:
        emit("  %-14s %08x" % (n, elf_word(sym(n))))
    for i in range(12):
        emit("  RPMTable[%d] %08x" % (i, elf_word(RPM_TABLE + 4 * i)))

    others = [(f32(x), f32(y)) for x, y in (
        (10.0, -5.0), (11.0, -5.0), (10.0, -4.0), (9.0, -5.0), (10.0, -6.0),
        (0.0, 0.0), (-3.0, 7.0), (1.0, 2.0), (100.0, 100.0), (12.5, -7.25),
        (-40.0, 3.5))]

    # -- left and right -----------------------------------------------------
    emit("[left right]")
    cars = ((0, 0.0, 0.0, 1.0, 10.0, -5.0), (16384, 0.0, 0.0, 1.0, 0.0, 0.0),
            (8192, 0.0, 0.0, 1.0, -3.0, 7.0), (0, 3.0, 4.0, 5.0, 1.0, 2.0),
            (49152, -2.0, 0.5, -1.0, 100.0, 100.0))
    for i, (ang, vx, vy, fs, px, py) in enumerate(cars):
        for j, q in enumerate(others):
            s = carstate_check.State()
            s.Angle = ang
            s.Velocity = [f32(vx), f32(vy), f32(0.0), f32(0.0)]
            s.ForwardSpeed = f32(fs)
            s.Position = [f32(px), f32(py), f32(0.0), f32(0.0)]
            s.MatrixValid = 0
            left = 1 if carstate_check.world_to_car2(s, list(q))[0] < 0.0 \
                else 0
            s.MatrixValid = 0
            right = 1 if 0.0 < carstate_check.world_to_car2(s, list(q))[0] \
                else 0
            emit("  car %d other %-2d -> left %d right %d"
                 % (i, j, left, right))

    # -- relative position --------------------------------------------------
    emit("[relative position]")
    rcars = ((0.0, 0.0, 1.0, 0.0), (5.0, -3.0, 3.0, 4.0), (0.0, 0.0, 0.0, 0.0),
             (-20.0, 40.0, -0.6, 2.2))
    rq = [(f32(x), f32(y)) for x, y in (
        (0.0, 0.0), (100.0, 0.0), (100.00001, 0.0), (-100.0, 0.0),
        (-100.00001, 0.0), (0.0, 100.0), (0.0, -100.00001), (50.0, 50.0),
        (99.9, -99.9), (65.0, 77.0), (-30.0, 10.0), (5.0, -3.0))]
    sentinel = f32(-12345.0)
    for i, (px, py, vx, vy) in enumerate(rcars):
        px, py, vx, vy = f32(px), f32(py), f32(vx), f32(vy)
        for j, (qx, qy) in enumerate(rq):
            n = bvector_check.bNormalize2((vx, vy))
            dy = fsub(qy, py)
            dx = fsub(qx, px)
            across = fadd(fmul(n[1], dx), fmul(bvector_check.fneg(n[0]), dy))
            along = fadd(fmul(n[0], dx), fmul(n[1], dy))
            if REL_LIMIT < abs(along) or REL_LIMIT < abs(across):
                along, lat = REL_FAR, sentinel
            else:
                lat = across
            emit("  car %d other %-2d -> along %s lateral %s null %s"
                 % (i, j, gx(along), gx(lat), gx(along)))

    # -- in front -----------------------------------------------------------
    fq = [(f32(x), f32(y)) for x, y in (
        (10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0), (10.0, 10.0),
        (-7.0, -3.0), (0.0, 0.0), (3.5, 0.25))]
    within = (0, 1, 1000, 16384, 16385, 32767, 32768, 32769, 65535)

    def in_front(ang, px, py, qx, qy, lim):
        _, a = bmath_check.bToPolar(fsub(qx, px), fsub(qy, py))
        diff = (a - ang) & 0xffff                 # subu; sll 16; sra 16
        if diff & 0x8000:
            diff -= 0x10000
        return 1 if max(diff, -diff) < lim else 0  # pmaxw; slt

    emit("[in front]")
    for ang in (0, 1000, 16384, 65000, 32768):
        for j, (qx, qy) in enumerate(fq):
            r = "".join(str(in_front(ang, 0.0, 0.0, qx, qy, lim))
                        for lim in within)
            emit("  ang %-5d other %d -> %s" % (ang, j, r))
    emit("[in front moved]")
    for i, (px, py) in enumerate(((20.0, -4.0), (-20.0, 4.0))):
        for j, (qx, qy) in enumerate(fq):
            emit("  car %d other %d -> %d %d"
                 % (i, j, in_front(0, f32(px), f32(py), qx, qy, 8192),
                    in_front(0, f32(px), f32(py), qx, qy, 32768)))

    # -- yaw boost ----------------------------------------------------------
    cases = ((0, 2000), (0x7fffffff, 0x800007cf), (1000, 1000), (1000, 1400),
             (1000, 2600), (1000, 3000), (1000, 7000), (1000, 9000),
             (1000, 16999), (1000, 17000), (1000, 500), (5, 0x7fffffff),
             (0x80000000, 0x7fffffff), (0xfffffff0, 0x00000010),
             (0x7ffffffe, 0x800007cd), (1, 2001))
    for wide in (0, 1):
        emit("[yaw boost wide profile]" if wide else "[yaw boost]")
        pts = [list(p) for p in F.pcy]
        if wide:
            pts[0][1] = f32(0.125)
            pts[3] = [f32(8.0), f32(0.5)]
        for stamp, now in cases:
            # beq v1,zero; then xor/sltu against 0x7fffffff.
            if stamp == 0 or stamp == BLINK_NEVER:
                r = 0.0
            else:
                t = fmul(f32(float(i32(now - stamp))), TICK)
                if t < YAW_CUTOFF:
                    r = GR.graph_get_value(pts, 4, t)
                else:
                    r = 0.0
            emit("  stamp %08x now %08x -> %s" % (stamp, now, gx(r)))

    # -- drifting -----------------------------------------------------------
    emit("[drifting]")
    for nw in (1, 2, 4):
        for ang in (1355, 1356, 64179, 64180, 16384):
            r = ""
            for fs in (12.0, 12.000001, 30.0, 4.9):
                s = carstate_check.State()
                s.nWheelsTouchingGround = nw
                s.Angle = ang
                s.Velocity = [f32(20.0), f32(0.0), f32(0.0), f32(0.0)]
                s.ForwardSpeed = f32(fs)
                s.VelocityMagnitude = f32(1.0)
                if nw < DRIFT_WHEELS:
                    d = 0
                elif not DRIFT_YAW < abs(carstate_check.get_yaw(s)):
                    d = 0
                else:
                    d = 1 if DRIFT_SPEED < s.ForwardSpeed else 0
                r += str(d)
            emit("  wheels %d ang %-5d -> %s" % (nw, ang, r))

    # -- smooth -------------------------------------------------------------
    emit("[smooth]")
    for c, t, rt in ((0.0, 5.0, 1.0), (0.0, 1.0, 1.0), (0.0, 0.5, 1.0),
                     (0.0, -1.0, 1.0), (0.0, -5.0, 1.0), (10.0, 10.0, 0.0),
                     (-0.0, -0.0, 0.0), (0.0, -0.0, 0.0), (0.0, 0.5, -1.0),
                     (5.0, 7.0, 1.5), (-3.25, -3.3, 0.01),
                     (1000.0, 8500.0, 50.0)):
        c, t, rt = f32(c), f32(t), f32(rt)
        emit("  %s %s %s -> %s" % (g9(c), g9(t), g9(rt), gx(smooth(c, t, rt))))

    # -- the fake engine ----------------------------------------------------
    def twice(vm, old):
        car = {"vm": f32(vm), "old": f32(old), "gear": 1,
               "rpm": f32(1000.0)}
        emit("  vm %s old %s" % (g9(car["vm"]), g9(car["old"])))
        for tag in ("first", "second"):
            fake_rpm(F, car)
            emit("  %-10s old %s gear %d rpm %s"
                 % (tag, gx(car["old"]), car["gear"], gx(car["rpm"])))

    def restore():
        F.__init__(w)

    emit("[fake rpm bands]")
    for sp in (-30.0, -25.38, -5.0, -2.00000024, -2.0, -1.0, -0.0, 0.0, 10.0, 25.3799973,
               25.38, 30.0, 40.89, 50.0, 56.47, 60.0, 72.06, 75.0,
               79.9999924, 80.0, 85.0, 89.5, 89.5099945, 89.51, 100.0):
        twice(sp, sp)

    emit("[fake rpm smoothing]")
    for vm, old in ((50.0, 20.0), (10.0, 30.0), (30.0, 29.5), (89.0, 95.0),
                    (120.0, 60.0)):
        twice(vm, old)

    emit("[fake rpm test speed]")
    F.T["TestSpeed"] = f32(45.0)
    twice(10.0, 45.0)
    F.T["TestSpeed"] = f32(-1.0)
    twice(10.0, 10.0)
    restore()

    emit("[fake rpm test rpm]")
    F.T["TestRPM"] = f32(3000.0)
    twice(30.0, 30.0)
    F.T["TestRPM"] = f32(0.0)
    twice(60.0, 60.0)
    F.T["TestRPM"] = f32(100.0)
    twice(60.0, 60.0)
    restore()

    emit("[fake rpm overread]")
    F.pcy[0] = [f32(7000.0), f32(7500.0)]
    twice(85.0, 85.0)
    restore()

    emit("[fake rpm pair one]")
    F.rpm[2] = f32(1.0)
    F.rpm[3] = f32(2.0)
    twice(30.0, 30.0)
    twice(10.0, 10.0)
    restore()

    emit("[fake rpm pair zero]")
    F.rpm[0] = f32(1500.0)
    F.rpm[1] = f32(4500.0)
    twice(10.0, 10.0)
    restore()


def model_refusals():
    # The harness runs these after the transcript, one process each.
    emit("[abort modes]")
    for mode, msg in ABORT_MODES:
        emit("  %s -> aborted: %s" % (mode, msg))


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


def run_abort_modes(exe):
    """Each of vt_slot's and vt_install's refusals, one process per mode.
    A mode passes when the process dies and its first `vt_` line on stderr
    is the refusal; one that prints "returned" did not refuse at all."""
    lines = ["[abort modes]"]
    for mode, _ in ABORT_MODES:
        try:
            r = subprocess.run([str(exe), mode], capture_output=True,
                               text=True, timeout=HARNESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            lines.append("  %s -> hung" % mode)
            continue
        msg = [ln.strip() for ln in r.stderr.splitlines()
               if ln.startswith("vt_")]
        out = r.stdout.strip()
        if r.returncode != 0 and "returned" not in out and msg:
            lines.append("  %s -> aborted: %s%s"
                         % (mode, msg[0], " [%s]" % out if out else ""))
        else:
            lines.append("  %s -> rc %d, %s" % (mode, r.returncode,
                                                 r.stdout.strip() or "-"))
    return lines


def harness_lines(exe, out_path):
    """The transcript, then the refusals. rc is the transcript run's."""
    rc = run_harness(exe, out_path)
    if rc != 0:
        return rc, out_path.read_text().splitlines()
    return rc, out_path.read_text().splitlines() + run_abort_modes(exe)


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
     "    uint8_t           BlownTireBits;            // 2088",
     "    uint32_t          BlownTireBits;            // 2088"),
    ("car-lastintrough-is-v3", CH,
     "    bVector2          LastInTroughPosition;     // 2112",
     "    bVector3          LastInTroughPosition;     // 2112"),
    ("car-node-one-link", CH,
     "    struct CarNode *prev;  // 4",
     "    /* removed */"),
    ("orp-geom-at-68", CH,
     "    bVector3 GeometryPosition;  // 64",
     "    uint32_t _gap;              // 64" + NL +
     "    bVector3 GeometryPosition;  // 68"),
    ("driverinfo-type-at-8", CH,
     "    DriverType     TheDriverType;       // 4   retail 8",
     "    uint32_t       _gap;                // 4" + NL +
     "    DriverType     TheDriverType;       // 8"),
    ("topology-table-159", TH,
     "#define TOPOLOGY_MAX_POLYGONS 160",
     "#define TOPOLOGY_MAX_POLYGONS 159"),
    ("topology-bbox-is-v3", TH,
     "    bVector2      InterestBBoxMin;                          //   0",
     "    bVector3      InterestBBoxMin;                          //   0"),

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
     "{" + NL + "    c->NumTimesSkidding[0] = 1;"),

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
     "    return ee_trunc_w(s * 65536.0f);",
     "    return ee_trunc_w(s * 32768.0f);"),
    ("checksum-rounds", CC,
     "    return ee_trunc_w(s * 65536.0f);",
     "    return ee_trunc_w(s * 65536.0f + 0.5f);"),

    # -- the conversion ----------------------------------------------------
    ("trunc-no-pos-saturation", EF,
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x7fffffff;" + NL,
     ""),
    ("trunc-pos-saturates-low", EF,
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x7fffffff;",
     "    if (x >= 2147483648.0f)" + NL +
     "        return (int32_t)0x80000000;"),
    ("trunc-pos-threshold-strict", EF,
     "    if (x >= 2147483648.0f)",
     "    if (x > 2147483648.0f)"),
    ("trunc-no-neg-saturation", EF,
     "    if (x < -2147483648.0f)" + NL +
     "        return (int32_t)0x80000000;" + NL,
     ""),
    ("trunc-neg-threshold-le", EF,
     "    if (x < -2147483648.0f)",
     "    if (x <= -2147483648.0f)"),
    ("trunc-no-nan-arm", EF,
     "    if (x != x)                     // no NaN reaches the EE FPU; "
     "defined anyway" + NL + "        return 0;" + NL,
     ""),
    ("trunc-nan-returns-low", EF,
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
     "    len2 = v->x * v->x + v->y * v->y + v->z * v->z;" + NL +
     "    inv  = 1.0f / sqrtf(len2);",
     "    len2 = v->x * v->x + v->y * v->y + v->z * v->z;" + NL +
     "    inv  = 1.0f / len2;"),

    # -- the horn -----------------------------------------------------------
    ("honk-cycle-on-plus-off", CC,
     "    float cycle = c->HeadlightsAndHornOnDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornSecondOnDuration;",
     "    float cycle = c->HeadlightsAndHornOnDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration;"),
    ("honk-cycle-two-offs", CC,
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornSecondOnDuration;",
     "                  + c->HeadlightsAndHornOffDuration" + NL +
     "                  + c->HeadlightsAndHornOffDuration;"),
    ("honk-cycle-demo", CC,
     "                  + c->HeadlightsAndHornSecondOnDuration;",
     "                  + c->HeadlightsAndHornOnDuration;"),
    ("honk-guard-le", CC,
     "    if (cycle < elapsed) {",
     "    if (cycle <= elapsed) {"),
    ("honk-guard-reversed", CC,
     "    if (cycle < elapsed) {",
     "    if (elapsed < cycle) {"),
    ("honk-no-stamp", CC,
     "        c->HeadlightsAndHornStartTime        = WorldTimer;",
     "        c->HeadlightsAndHornStartTime        = 0;"),
    ("honk-swaps-durations", CC,
     "        c->HeadlightsAndHornOnDuration       = onDuration;" + NL +
     "        c->HeadlightsAndHornOffDuration      = offDuration;",
     "        c->HeadlightsAndHornOnDuration       = offDuration;" + NL +
     "        c->HeadlightsAndHornOffDuration      = onDuration;"),
    ("honk-second-is-on", CC,
     "        c->HeadlightsAndHornSecondOnDuration = secondOnDuration;",
     "        c->HeadlightsAndHornSecondOnDuration = onDuration;"),
    ("honk-drops-second", CC,
     "        c->HeadlightsAndHornSecondOnDuration = secondOnDuration;" + NL,
     ""),
    ("honk-drops-two", CC,
     "        c->WantTwoHonksAndOrBlinks           = two;",
     "        c->WantTwoHonksAndOrBlinks           = 0;"),
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

    # ============================================================ slice two

    # -- the static initialiser ---------------------------------------------
    ("sinit-knee-2", CC,
     "    set2(&vDraftSpeedRange[1],   1.0f,  0.0f);",
     "    set2(&vDraftSpeedRange[1],   2.0f,  0.0f);"),
    ("sinit-reach-50", CC,
     "    set2(&vDraftSpeedRange[3], 150.0f, 60.0f);",
     "    set2(&vDraftSpeedRange[3], 150.0f, 50.0f);"),
    ("sinit-knee2-swapped", CC,
     "    set2(&vDraftSpeedRange[2],   5.0f, 10.0f);",
     "    set2(&vDraftSpeedRange[2],  10.0f,  5.0f);"),
    ("sinit-table-n5", CC,
     "    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 1.0f);",
     "    table_init(&tDraftFalloff, fDraftFalloff, 5, 0.0f, 1.0f);"),
    ("sinit-table-hi-2", CC,
     "    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 1.0f);",
     "    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 2.0f);"),
    ("sinit-graph-n3", CC,
     "    graph_init(&gDraftSpeedRange, vDraftSpeedRange, 4);",
     "    graph_init(&gDraftSpeedRange, vDraftSpeedRange, 3);"),
    ("sinit-graph-first", CC,
     "    set2(&vDraftSpeedRange[0],   0.0f,  0.0f);" + NL +
     "    set2(&vDraftSpeedRange[1],   1.0f,  0.0f);" + NL +
     "    set2(&vDraftSpeedRange[2],   5.0f, 10.0f);" + NL +
     "    set2(&vDraftSpeedRange[3], 150.0f, 60.0f);" + NL + NL +
     "    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 1.0f);" + NL +
     "    graph_init(&gDraftSpeedRange, vDraftSpeedRange, 4);",
     "    graph_init(&gDraftSpeedRange, vDraftSpeedRange, 4);" + NL +
     "    set2(&vDraftSpeedRange[0],   0.0f,  0.0f);" + NL +
     "    set2(&vDraftSpeedRange[1],   1.0f,  0.0f);" + NL +
     "    set2(&vDraftSpeedRange[2],   5.0f, 10.0f);" + NL +
     "    set2(&vDraftSpeedRange[3], 150.0f, 60.0f);" + NL + NL +
     "    table_init(&tDraftFalloff, fDraftFalloff, 6, 0.0f, 1.0f);"),
    ("sinit-falloff-half", CC,
     "    1.0f, 0.9f, 0.75f, 0.55f, 0.3f, 0.0f",
     "    1.0f, 0.9f, 0.75f, 0.5f, 0.3f, 0.0f"),
    ("sinit-roadnoise-typed", CC,
     "    set2(&vRoadNoiseSpeedData[0],  1.388889f, 0.0f);",
     "    set2(&vRoadNoiseSpeedData[0],  1.3888888f, 0.0f);"),
    ("sinit-roadnoise-n1", CC,
     "    graph_init(&gRoadNoiseSpeedScale, vRoadNoiseSpeedData, 2);",
     "    graph_init(&gRoadNoiseSpeedScale, vRoadNoiseSpeedData, 1);"),
    ("sinit-ring-order", CC,
     "    set3(&ObjectPoints[2],   0.0f, -3.0f, 3.0f);",
     "    set3(&ObjectPoints[2],   0.0f,  3.0f, 3.0f);"),
    ("sinit-points-pad", CC,
     "    v->y = y;" + NL + "    v->z = z;" + NL + "}" + NL + NL +
     "static void set4",
     "    v->y = y;" + NL + "    v->z = z;" + NL + "    v->pad = 1.0f;" +
     NL + "}" + NL + NL + "static void set4"),
    ("sinit-damage-w0", CC,
     "    set4(&DamageAboveMatrix[3], 0.0f, 0.0f, 1.0f, 1.0f);",
     "    set4(&DamageAboveMatrix[3], 0.0f, 0.0f, 1.0f, 0.0f);"),
    ("sinit-pcy-half", CC,
     "    set2(&PostCollisionYawControlProfileData[1], 0.4f, 1.0f);",
     "    set2(&PostCollisionYawControlProfileData[1], 0.5f, 1.0f);"),
    ("sinit-pcy-wrong-array", CC,
     "    graph_init(&PostCollisionYawControlProfile," + NL +
     "               PostCollisionYawControlProfileData, 4);",
     "    graph_init(&PostCollisionYawControlProfile," + NL +
     "               vDraftSpeedRange, 4);"),

    # -- the draft ----------------------------------------------------------
    ("draft-speed-of-self", CC,
     "    float speed = other->State.VelocityMagnitude;",
     "    float speed = c->State.VelocityMagnitude;"),
    ("draft-velocity-of-self", CC,
     "    const bVector3 *v = &other->State.Velocity;",
     "    const bVector3 *v = &c->State.Velocity;"),
    ("draft-knee-le", CC,
     "    if (speed < vDraftSpeedRange[1].x)",
     "    if (speed <= vDraftSpeedRange[1].x)"),
    ("draft-knee-index-0", CC,
     "    if (speed < vDraftSpeedRange[1].x)",
     "    if (speed < vDraftSpeedRange[0].x)"),
    ("draft-knee-index-2", CC,
     "    if (speed < vDraftSpeedRange[1].x)",
     "    if (speed < vDraftSpeedRange[2].x)"),
    ("draft-delta-backwards", CC,
     "    dx = other->State.Position.x - c->State.Position.x;",
     "    dx = c->State.Position.x - other->State.Position.x;"),
    ("draft-dist-2d", CC,
     "    dist = sqrtf((dx * dx + dy * dy) + dz * dz);",
     "    dist = sqrtf(dx * dx + dy * dy);"),
    ("draft-reach-le", CC,
     "    if (vDraftSpeedRange[3].y < dist)",
     "    if (vDraftSpeedRange[3].y <= dist)"),
    ("draft-reach-x", CC,
     "    if (vDraftSpeedRange[3].y < dist)",
     "    if (vDraftSpeedRange[3].x < dist)"),
    ("draft-len2-order", CC,
     "    len2 = (v->x * v->x + v->y * v->y) + v->z * v->z;",
     "    len2 = v->x * v->x + (v->y * v->y + v->z * v->z);"),
    ("draft-no-normalise", CC,
     "    len2 = (v->x * v->x + v->y * v->y) + v->z * v->z;" + NL +
     "    inv  = 1.0f / sqrtf(len2);",
     "    len2 = (v->x * v->x + v->y * v->y) + v->z * v->z;" + NL +
     "    inv  = 1.0f;"),
    ("draft-dot-order", CC,
     "    dot = (dx * nx + dy * ny) + dz * nz;",
     "    dot = dx * nx + (dy * ny + dz * nz);"),
    ("draft-cos-09", CC,
     "#define CAR_DRAFT_CONE_COS   0.95f",
     "#define CAR_DRAFT_CONE_COS   0.9f"),
    ("draft-scale-20", CC,
     "#define CAR_DRAFT_CONE_SCALE 19.999996f",
     "#define CAR_DRAFT_CONE_SCALE 20.0f"),
    ("draft-cone-le", CC,
     "    if (f < 0.0f)" + NL + "        return 0.0f;" + NL + NL +
     "    g = graph_get_value",
     "    if (f <= 0.0f)" + NL + "        return 0.0f;" + NL + NL +
     "    g = graph_get_value"),
    ("draft-graph-by-dist", CC,
     "    g = graph_get_value(&gDraftSpeedRange, speed);",
     "    g = graph_get_value(&gDraftSpeedRange, dist);"),
    ("draft-lookup-inverted", CC,
     "    return table_get_value(&tDraftFalloff, dist / (f * g));",
     "    return table_get_value(&tDraftFalloff, (f * g) / dist);"),

    ("sum-counts-self", CC,
     "        if (o != c)" + NL + "            sum = sum",
     "        if (1)" + NL + "            sum = sum"),
    ("sum-early-lt", CC,
     "        if (CAR_DRAFT_EARLY_OUT <= sum)",
     "        if (CAR_DRAFT_EARLY_OUT < sum)"),
    ("sum-no-early-out", CC,
     "        if (CAR_DRAFT_EARLY_OUT <= sum)" + NL + "            break;" + NL,
     ""),
    ("sum-test-inside-if", CC,
     "        if (o != c)" + NL +
     "            sum = sum + car_calculate_draft_factor_from(c, o);" + NL +
     "        if (CAR_DRAFT_EARLY_OUT <= sum)" + NL +
     "            break;",
     "        if (o != c) {" + NL +
     "            sum = sum + car_calculate_draft_factor_from(c, o);" + NL +
     "            if (CAR_DRAFT_EARLY_OUT <= sum)" + NL +
     "                break;" + NL +
     "        }"),
    ("sum-uncapped", CC,
     "    return (sum < CAR_DRAFT_CAP) ? sum : CAR_DRAFT_CAP;",
     "    return sum;"),
    ("sum-early-08", CC,
     "#define CAR_DRAFT_EARLY_OUT 0.9f",
     "#define CAR_DRAFT_EARLY_OUT 0.8f"),
    ("sum-cap-08", CC,
     "#define CAR_DRAFT_CAP       0.9f",
     "#define CAR_DRAFT_CAP       0.8f"),
    ("sum-whole-table", CC,
     "    for (i = 0; i < pCurrentWorld->TotalNumCars; i++) {",
     "    for (i = 0; i < WORLD_MAX_CARS; i++) {"),

    # -- the dispatchers ----------------------------------------------------
    ("think-draft-after", CC,
     "    c->DraftFactor = car_calculate_draft_factor(c);" + NL + NL +
     "    ctl = c->pCarController;" + NL +
     "    e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_THINK);" + NL +
     "    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), dt);",
     "    ctl = c->pCarController;" + NL +
     "    e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_THINK);" + NL +
     "    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), dt);" + NL + NL +
     "    c->DraftFactor = car_calculate_draft_factor(c);"),
    ("think-no-delta", CC,
     "    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), dt);",
     "    ((VtVoidFloatFn)e->fn)(ctl, dt);"),
    ("think-dt-zero", CC,
     "    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), dt);",
     "    ((VtVoidFloatFn)e->fn)(vt_this(ctl, e), 0.0f);"),
    ("drive-no-delta", CC,
     "    ((VtVoidFloatFn)e->fn)(vt_this(d, e), dt);",
     "    ((VtVoidFloatFn)e->fn)(d, dt);"),
    ("route-no-delta", CC,
     "    return ((VtRouteFn)e->fn)(vt_this(ctl, e), find);",
     "    return ((VtRouteFn)e->fn)(ctl, find);"),
    ("route-point-takes-route", CC,
     "                               CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);",
     "                               CARCONTROLLER_VT_GET_CURRENT_ROUTE);"),
    ("oob-no-delta", CC,
     "    return ((VtFloatFn)e->fn)(vt_this(ctl, e));",
     "    return ((VtFloatFn)e->fn)(ctl);"),
    ("sound-no-null-test", CC,
     "    if (!snd)" + NL + "        return;" + NL,
     ""),
    ("sound-short-1", CC,
     "    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 0, 1.0f);",
     "    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 1, 1.0f);"),
    ("sound-first-0", CC,
     "    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 0, 1.0f);",
     "    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 0.0f, 0, 1.0f);"),
    ("sound-no-delta", CC,
     "    ((VtSoundUpdateFn)e->fn)(vt_this(snd, e), 1.0f, 0, 1.0f);",
     "    ((VtSoundUpdateFn)e->fn)(snd, 1.0f, 0, 1.0f);"),
    ("sound-vptr-at-0", CC,
     "    e = vt_slot(((Sound3d *)snd)->_vtable, SOUND3D_VT_UPDATE);",
     "    e = vt_slot(*(uint32_t *)snd, SOUND3D_VT_UPDATE);"),
    ("collide-ignores-blink", CC,
     "    if (car_is_blinking(c))" + NL + "        return 0;" + NL + NL +
     "    b = c->pDynamicCollisionBody;",
     "    b = c->pDynamicCollisionBody;"),
    ("collide-raw-answer", CC,
     "    return ((VtBoolFn)e->fn)(vt_this(b, e)) != 0;",
     "    return ((VtBoolFn)e->fn)(vt_this(b, e));"),
    ("collide-no-delta", CC,
     "    return ((VtBoolFn)e->fn)(vt_this(b, e)) != 0;",
     "    return ((VtBoolFn)e->fn)(b) != 0;"),
    ("wrongway-le", CC,
     "    return (0.0f < dot) ? 0 : 1;",
     "    return (0.0f <= dot) ? 0 : 1;"),
    ("wrongway-side-axis", CC,
     "    const bVector4 *fwd = &c->State.BodyMatrix.v0;",
     "    const bVector4 *fwd = &c->State.BodyMatrix.v1;"),
    ("wrongway-crossed", CC,
     "    float dot = fwd->x * rp->Direction.x + fwd->y * rp->Direction.y;",
     "    float dot = fwd->x * rp->Direction.y + fwd->y * rp->Direction.x;"),

    ("lights-player-too", CC,
     "    if (c->pPlayer)" + NL + "        return;" + NL + NL +
     "    elapsed = ",
     "    elapsed = "),
    ("lights-first-le", CC,
     "    if (elapsed < on) {",
     "    if (elapsed <= on) {"),
    ("lights-gap-inverted", CC,
     "            lit = (c->WantTwoHonksAndOrBlinks == 0);",
     "            lit = (c->WantTwoHonksAndOrBlinks != 0);"),
    ("lights-gap-off", CC,
     "        if (t < on)" + NL,
     "        if (t < c->HeadlightsAndHornOffDuration)" + NL),
    ("lights-second-le", CC,
     "                   < c->HeadlightsAndHornSecondOnDuration);",
     "                   <= c->HeadlightsAndHornSecondOnDuration);"),
    ("lights-second-on", CC,
     "                   < c->HeadlightsAndHornSecondOnDuration);",
     "                   < on);"),
    ("lights-second-from-on", CC,
     "            lit = (t - c->HeadlightsAndHornOffDuration" + NL,
     "            lit = (t - on" + NL),
    ("lights-second-off", CC,
     "            lit = (t - c->HeadlightsAndHornOffDuration" + NL +
     "                   < c->HeadlightsAndHornSecondOnDuration);",
     "            lit = 0;"),
    ("lights-blink-unlit", CC,
     "    c->HeadlightsState = (lit && c->WantToBlinkHeadlights)",
     "    c->HeadlightsState = (c->WantToBlinkHeadlights != 0)"),
    ("lights-no-force", CC,
     "                         ? 1 : (c->ForceHeadlightsOn != 0);",
     "                         ? 1 : 0;"),
    ("lights-force-raw", CC,
     "                         ? 1 : (c->ForceHeadlightsOn != 0);",
     "                         ? 1 : c->ForceHeadlightsOn;"),
    ("horn-ignores-lit", CC,
     "    honk = lit ? (c->WantToHonkHorn != 0) : 0;",
     "    honk = (c->WantToHonkHorn != 0);"),
    ("horn-start-no-reload", CC,
     "        d = c->pCarDriver;" + NL +
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_START_HONK_HORN);",
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_START_HONK_HORN);"),
    ("horn-stop-no-reload", CC,
     "        d = c->pCarDriver;" + NL +
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_STOP_HONK_HORN);",
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_STOP_HONK_HORN);"),
    ("horn-start-is-stop", CC,
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_START_HONK_HORN);",
     "        e = vt_slot(d->_vtable, CARDRIVER_VT_STOP_HONK_HORN);"),
    ("horn-start-unguarded", CC,
     "        if (((VtBoolFn)e->fn)(vt_this(d, e)))" + NL +
     "            return;" + NL,
     ""),
    ("horn-stop-guard-inverted", CC,
     "        if (!((VtBoolFn)e->fn)(vt_this(d, e)))",
     "        if (((VtBoolFn)e->fn)(vt_this(d, e)))"),

    # -- the borrowed fields ------------------------------------------------
    ("bbox-max-first", CC,
     "    *min = b->Dynamic.LocalBBMin;" + NL +
     "    *max = b->Dynamic.LocalBBMax;",
     "    *max = b->Dynamic.LocalBBMax;" + NL +
     "    *min = b->Dynamic.LocalBBMin;"),
    ("bbox-no-pad", CC,
     "    *min = b->Dynamic.LocalBBMin;",
     "    min->x = b->Dynamic.LocalBBMin.x;" + NL +
     "    min->y = b->Dynamic.LocalBBMin.y;" + NL +
     "    min->z = b->Dynamic.LocalBBMin.z;"),
    ("bbox-max-is-min", CC,
     "    *max = b->Dynamic.LocalBBMax;",
     "    *max = b->Dynamic.LocalBBMin;"),
    ("penetration-is-yaw", CC,
     "    return c->pDynamicCollisionBody->LastPenetrationTime;",
     "    return c->pDynamicCollisionBody->LastYawControlCollisionTime;"),
    ("tracked-when-present", CC,
     "    if (c->TheControlMode == REAL_CONTROL)" + NL +
     "        return ((TrackedController *)",
     "    if (c->pCarController)" + NL +
     "        return ((TrackedController *)"),
    ("tracked-prev-speed", CC,
     "        return ((TrackedController *)c->pCarController)->Acceleration;",
     "        return ((TrackedController *)c->pCarController)->PrevSpeed;"),

    # -- the headers the dispatch reads -------------------------------------
    ("ctl-think-40", CTL,
     "#define CARCONTROLLER_VT_THINK                    32",
     "#define CARCONTROLLER_VT_THINK                    40"),
    ("ctl-real-vtable", CTL,
     "#define REALCONTROLLER_VTABLE    0x002a0b00u",
     "#define REALCONTROLLER_VTABLE    0x002a0b08u"),
    ("ctl-tracked-swapped", CTL,
     "    float         Acceleration;           // 20" + NL +
     "    float         PrevSpeed;              // 24",
     "    float         PrevSpeed;              // 20" + NL +
     "    float         Acceleration;           // 24"),
    ("drv-is-honking-112", CD,
     "#define CARDRIVER_VT_IS_HONKING      104",
     "#define CARDRIVER_VT_IS_HONKING      112"),
    ("cb-collisions-128", CB,
     "#define COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED      136",
     "#define COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED      128"),
    ("cb-timers-swapped", CB,
     "    Timer     LastPenetrationTime;              // 260" + NL +
     "    Timer     LastYawControlCollisionTime;      // 264",
     "    Timer     LastYawControlCollisionTime;      // 260" + NL +
     "    Timer     LastPenetrationTime;              // 264"),
    ("s3d-update-32", S3,
     "#define SOUND3D_VT_UPDATE        24",
     "#define SOUND3D_VT_UPDATE        32"),
    ("world-13-cars", WH,
     "#define WORLD_MAX_CARS    14",
     "#define WORLD_MAX_CARS    13"),

    # -- the registry -------------------------------------------------------
    ("vt-count-inclusive", VTC,
     "k >= vt_tables[i].count",
     "k > vt_tables[i].count"),
    ("vt-slot-zero-ok", VTC,
     "k <= 0 ||",
     "k < 0 ||"),
    ("vt-any-alignment", VTC,
     "slot % 8 != 0 || ",
     ""),
    ("vt-null-fn-ok", VTC,
     NL + "            || !vt_tables[i].entries[k].fn)",
     ")"),
    ("vt-install-appends", VTC,
     "    for (i = 0; i < vt_count; i++) {" + NL +
     "        if (vt_tables[i].image == image) {",
     "    for (i = 0; i < 0; i++) {" + NL +
     "        if (vt_tables[i].image == image) {"),
    ("vt-reset-keeps", VTC,
     "    vt_count = 0;",
     "    (void)vt_count;"),
    ("vt-full-early", VTC,
     "    if (vt_count == VT_MAX) {",
     "    if (vt_count == VT_MAX - 1) {"),
    ("vt-max-97", VTC,
     "#define VT_MAX 96",
     "#define VT_MAX 97"),
    ("vt-this-subtracts", VTH,
     "    return (char *)obj + e->delta;",
     "    return (char *)obj - e->delta;"),
    ("vt-slot-per-word", VTH,
     "#define VT_SLOT(S) ((S) / 8)",
     "#define VT_SLOT(S) ((S) / 4)"),
    # -- slice three: where the other cars are ------------------------------
    ("left-le", CC,
     "    return (local.x < 0.0f) ? 1 : 0;",
     "    return (local.x <= 0.0f) ? 1 : 0;"),
    ("right-le", CC,
     "    return (0.0f < local.x) ? 1 : 0;",
     "    return (0.0f <= local.x) ? 1 : 0;"),
    ("left-reads-y", CC,
     "    return (local.x < 0.0f) ? 1 : 0;",
     "    return (local.y < 0.0f) ? 1 : 0;"),
    ("right-is-left", CC,
     "    return (0.0f < local.x) ? 1 : 0;",
     "    return (local.x < 0.0f) ? 1 : 0;"),
    ("left-geometry-position", CC,
     "                           (const bVector2 *)&other->State.Position);" + NL +
     "    return (local.x < 0.0f) ? 1 : 0;",
     "                           (const bVector2 *)&other->State.GeometryPosition);" + NL +
     "    return (local.x < 0.0f) ? 1 : 0;"),
    ("right-others-frame", CC,
     "    carstate_world_to_car2(&c->State, &local," + NL +
     "                           (const bVector2 *)&other->State.Position);" + NL +
     "    return (0.0f < local.x) ? 1 : 0;",
     "    carstate_world_to_car2(&other->State, &local," + NL +
     "                           (const bVector2 *)&other->State.Position);" + NL +
     "    return (0.0f < local.x) ? 1 : 0;"),
    ("rel-along-le", CC,
     "    if (100.0f < fabsf(along) || 100.0f < fabsf(across))",
     "    if (100.0f <= fabsf(along) || 100.0f < fabsf(across))"),
    ("rel-across-le", CC,
     "    if (100.0f < fabsf(along) || 100.0f < fabsf(across))",
     "    if (100.0f < fabsf(along) || 100.0f <= fabsf(across))"),
    ("rel-along-only", CC,
     "    if (100.0f < fabsf(along) || 100.0f < fabsf(across))",
     "    if (100.0f < fabsf(along))"),
    ("rel-store-before-test", CC,
     "    if (100.0f < fabsf(along) || 100.0f < fabsf(across))" + NL +
     "        return CAR_RELATIVE_FAR;" + NL +
     "    if (lateral)" + NL +
     "        *lateral = across;" + NL,
     "    if (lateral)" + NL +
     "        *lateral = across;" + NL +
     "    if (100.0f < fabsf(along) || 100.0f < fabsf(across))" + NL +
     "        return CAR_RELATIVE_FAR;" + NL),
    ("rel-returns-across", CC,
     "        *lateral = across;" + NL + "    return along;",
     "        *lateral = across;" + NL + "    return across;"),
    ("rel-lateral-is-along", CC,
     "        *lateral = across;",
     "        *lateral = along;"),
    ("rel-across-negated", CC,
     "    across = n.y * dx + (-n.x) * dy;",
     "    across = n.x * dy - n.y * dx;"),
    ("rel-across-neg-product", CC,
     "    across = n.y * dx + (-n.x) * dy;",
     "    across = n.y * dx + -(n.x * dy);"),
    ("rel-delta-reversed", CC,
     "    dx = other->State.Position.x - c->State.Position.x;" + NL + NL +
     "    across",
     "    dx = c->State.Position.x - other->State.Position.x;" + NL + NL +
     "    across"),
    ("rel-unnormalised", CC,
     "    bNormalize2(&n, (const bVector2 *)&c->State.Velocity);",
     "    n.x = c->State.Velocity.x;" + NL + "    n.y = c->State.Velocity.y;"),
    ("rel-far-minus-one", CC,
     "#define CAR_RELATIVE_FAR 999.0f",
     "#define CAR_RELATIVE_FAR -1.0f"),
    ("front-le", CC,
     "    return (((diff < 0) ? -diff : diff) < (int32_t)angle) ? 1 : 0;",
     "    return (((diff < 0) ? -diff : diff) <= (int32_t)angle) ? 1 : 0;"),
    ("front-unsigned-turn", CC,
     "    diff = (int16_t)(uint16_t)(p.a - c->State.Angle);",
     "    diff = (uint16_t)(p.a - c->State.Angle);"),
    ("front-no-abs", CC,
     "    return (((diff < 0) ? -diff : diff) < (int32_t)angle) ? 1 : 0;",
     "    return (diff < (int32_t)angle) ? 1 : 0;"),
    ("front-turn-reversed", CC,
     "    diff = (int16_t)(uint16_t)(p.a - c->State.Angle);",
     "    diff = (int16_t)(uint16_t)(c->State.Angle - p.a);"),
    ("front-delta-reversed", CC,
     "    d.y = other->State.Position.y - c->State.Position.y;" + NL +
     "    d.x = other->State.Position.x - c->State.Position.x;",
     "    d.y = c->State.Position.y - other->State.Position.y;" + NL +
     "    d.x = c->State.Position.x - other->State.Position.x;"),
    ("front-legs-swapped", CC,
     "    d.y = other->State.Position.y - c->State.Position.y;" + NL +
     "    d.x = other->State.Position.x - c->State.Position.x;",
     "    d.x = other->State.Position.y - c->State.Position.y;" + NL +
     "    d.y = other->State.Position.x - c->State.Position.x;"),
    ("front-own-geometry", CC,
     "    d.y = other->State.Position.y - c->State.Position.y;",
     "    d.y = other->State.Position.y - c->State.GeometryPosition.y;"),

    # -- slice three: the yaw -----------------------------------------------
    ("yaw-no-zero-sentinel", CC,
     "    if (stamp == 0 || stamp == 0x7fffffffu)",
     "    if (stamp == 0x7fffffffu)"),
    ("yaw-no-max-sentinel", CC,
     "    if (stamp == 0 || stamp == 0x7fffffffu)",
     "    if (stamp == 0)"),
    ("yaw-sentinel-one-low", CC,
     "    if (stamp == 0 || stamp == 0x7fffffffu)",
     "    if (stamp == 0 || stamp == 0x7ffffffeu)"),
    ("yaw-cutoff-le", CC,
     "    if (!(t < 4.0f))",
     "    if (!(t <= 4.0f))"),
    ("yaw-cutoff-5", CC,
     "    if (!(t < 4.0f))",
     "    if (!(t < 5.0f))"),
    ("yaw-penetration-stamp", CC,
     "        c->pDynamicCollisionBody->LastYawControlCollisionTime.PackedTime;",
     "        c->pDynamicCollisionBody->LastPenetrationTime.PackedTime;"),
    ("yaw-unsigned-elapsed", CC,
     "    t = (float)(int32_t)((uint32_t)WorldTimer - stamp) * CAR_TICK_SECONDS;",
     "    t = (float)((uint32_t)WorldTimer - stamp) * CAR_TICK_SECONDS;"),
    ("yaw-wrong-graph", CC,
     "    return graph_get_value(&PostCollisionYawControlProfile, t);",
     "    return graph_get_value(&gDraftSpeedRange, t);"),
    ("drift-wheels-le", CC,
     "    if (c->State.nWheelsTouchingGround < 2)",
     "    if (c->State.nWheelsTouchingGround <= 2)"),
    ("drift-wheels-1", CC,
     "    if (c->State.nWheelsTouchingGround < 2)",
     "    if (c->State.nWheelsTouchingGround < 1)"),
    ("drift-signed-yaw", CC,
     "    if (!(CAR_DRIFT_YAW < fabsf(carstate_get_yaw(&c->State))))",
     "    if (!(CAR_DRIFT_YAW < carstate_get_yaw(&c->State)))"),
    ("drift-yaw-le", CC,
     "    if (!(CAR_DRIFT_YAW < fabsf(carstate_get_yaw(&c->State))))",
     "    if (!(CAR_DRIFT_YAW <= fabsf(carstate_get_yaw(&c->State))))"),
    ("drift-yaw-always", CC,
     "    if (!(CAR_DRIFT_YAW < fabsf(carstate_get_yaw(&c->State))))",
     "    if (!(CAR_DRIFT_YAW < fabsf(carstate_get_yaw_always(&c->State))))"),
    ("drift-speed-le", CC,
     "    return (12.0f < c->State.ForwardSpeed) ? 1 : 0;",
     "    return (12.0f <= c->State.ForwardSpeed) ? 1 : 0;"),
    ("drift-yaw-0.14", CC,
     "#define CAR_DRIFT_YAW    0.13f",
     "#define CAR_DRIFT_YAW    0.14f"),

    # -- slice three: the fake engine ---------------------------------------
    ("smooth-hi-le", CC,
     "    if (hi < target)" + NL + "        return hi;",
     "    if (hi <= target)" + NL + "        return hi;"),
    ("smooth-lo-le", CC,
     "    if (target < lo)" + NL + "        return lo;",
     "    if (target <= lo)" + NL + "        return lo;"),
    ("smooth-low-side-first", CC,
     "    float hi = cur + rate, lo;" + NL + NL +
     "    if (hi < target)" + NL + "        return hi;" + NL +
     "    lo = cur - rate;" + NL +
     "    if (target < lo)" + NL + "        return lo;",
     "    float hi = cur + rate, lo;" + NL + NL +
     "    lo = cur - rate;" + NL +
     "    if (target < lo)" + NL + "        return lo;" + NL +
     "    if (hi < target)" + NL + "        return hi;"),
    ("smooth-hi-gives-target", CC,
     "    if (hi < target)" + NL + "        return hi;",
     "    if (hi < target)" + NL + "        return target;"),
    ("fr-test-speed-le", CC,
     "    speed = (0.0f < TestSpeed) ? TestSpeed : st->VelocityMagnitude;",
     "    speed = (0.0f <= TestSpeed) ? TestSpeed : st->VelocityMagnitude;"),
    ("fr-forward-speed", CC,
     "    speed = (0.0f < TestSpeed) ? TestSpeed : st->VelocityMagnitude;",
     "    speed = (0.0f < TestSpeed) ? TestSpeed : st->ForwardSpeed;"),
    ("fr-clamp-lt", CC,
     "    if (GearTopSpeed <= speed)",
     "    if (GearTopSpeed < speed)"),
    ("fr-clamp-0.02", CC,
     "        speed = GearTopSpeed - 0.01f;",
     "        speed = GearTopSpeed - 0.02f;"),
    ("fr-speed-unsmoothed", CC,
     "    speed = car_smooth(c->OldSpeed, speed, MaxSpeedInc);" + NL,
     ""),
    ("fr-speed-smooth-args", CC,
     "    speed = car_smooth(c->OldSpeed, speed, MaxSpeedInc);",
     "    speed = car_smooth(speed, c->OldSpeed, MaxSpeedInc);"),
    ("fr-speed-by-rpm-inc", CC,
     "    speed = car_smooth(c->OldSpeed, speed, MaxSpeedInc);",
     "    speed = car_smooth(c->OldSpeed, speed, MaxRPMInc);"),
    ("fr-old-speed-unstored", CC,
     "    c->OldSpeed = speed;" + NL,
     ""),
    ("fr-reverse-lt", CC,
     "        gear = (GearRTo1Speed <= speed) ? FIRST_GEAR : REVERSE;",
     "        gear = (GearRTo1Speed < speed) ? FIRST_GEAR : REVERSE;"),
    ("fr-reverse-swapped", CC,
     "        gear = (GearRTo1Speed <= speed) ? FIRST_GEAR : REVERSE;",
     "        gear = (GearRTo1Speed <= speed) ? REVERSE : FIRST_GEAR;"),
    ("fr-signed-frac", CC,
     "        frac = fabsf(speed);",
     "        frac = speed;"),
    ("fr-frac-unclamped", CC,
     "        if (Gear1To2Speed < frac)" + NL +
     "            frac = Gear1To2Speed;" + NL,
     ""),
    ("fr-frac-clamp-le", CC,
     "        if (Gear1To2Speed < frac)",
     "        if (Gear1To2Speed <= frac)"),
    ("fr-band-le", CC,
     "            if (speed < speeds[i]) {",
     "            if (speed <= speeds[i]) {"),
    ("fr-bands-from-0", CC,
     "        for (i = 1; i < 6; i++) {",
     "        for (i = 0; i < 6; i++) {"),
    ("fr-bands-to-5", CC,
     "        for (i = 1; i < 6; i++) {",
     "        for (i = 1; i < 5; i++) {"),
    ("fr-pair-is-index", CC,
     "                pair = (i + 1 < 6) ? &RPMTable[2 * (i + 1)]",
     "                pair = (i + 1 < 6) ? &RPMTable[2 * i]"),
    ("fr-no-overread", CC,
     "                                   : &PostCollisionYawControlProfileData[0].x;",
     "                                   : &RPMTable[10];"),
    ("fr-gear-uncapped", CC,
     "                gear = (i + 2 < SIXTH_GEAR) ? (Gear)(i + 2) : FIFTH_GEAR;",
     "                gear = (Gear)(i + 2);"),
    ("fr-gear-one-past", CC,
     "                gear = (i + 2 < SIXTH_GEAR) ? (Gear)(i + 2) : FIFTH_GEAR;",
     "                gear = (i + 1 < SIXTH_GEAR) ? (Gear)(i + 1) : FIFTH_GEAR;"),
    ("fr-interp-reversed", CC,
     "                                * (pair[1] - pair[0]);",
     "                                * (pair[0] - pair[1]);"),
    ("fr-interp-over-top", CC,
     "                                 / (speeds[i] - speeds[i - 1]))",
     "                                 / speeds[i])"),
    ("fr-rpm-starts-at-rpm", CC,
     "    rpm = 0.0f;" + NL + "    if (speed < Gear1To2Speed) {",
     "    rpm = st->RPM;" + NL + "    if (speed < Gear1To2Speed) {"),
    ("fr-smooth-on-change", CC,
     "    if (st->CurrentGear == gear)",
     "    if (st->CurrentGear != gear)"),
    ("fr-smooth-from-rpm-only", CC,
     "        rpm = car_smooth((TestRPM == 100.0f) ? st->RPM : TestRPM, rpm,",
     "        rpm = car_smooth(st->RPM, rpm,"),
    ("fr-rpm-by-speed-inc", CC,
     "                         MaxRPMInc);",
     "                         MaxSpeedInc);"),
    ("fr-test-rpm-unset-0", CC,
     "    st->RPM = (TestRPM == 100.0f) ? rpm : TestRPM;",
     "    st->RPM = (TestRPM == 0.0f) ? rpm : TestRPM;"),
    ("fr-gear-unstored", CC,
     "    st->CurrentGear = gear;" + NL + "    st->RPM",
     "    st->RPM"),
    ("fr-gear-stored-first", CC,
     "    if (st->CurrentGear == gear)" + NL +
     "        rpm = car_smooth((TestRPM == 100.0f) ? st->RPM : TestRPM, rpm," + NL +
     "                         MaxRPMInc);" + NL +
     "    st->CurrentGear = gear;" + NL,
     "    st->CurrentGear = gear;" + NL +
     "    if (st->CurrentGear == gear)" + NL +
     "        rpm = car_smooth((TestRPM == 100.0f) ? st->RPM : TestRPM, rpm," + NL +
     "                         MaxRPMInc);" + NL),
    ("fr-top-band-clamped", CC,
     "        speeds[5] = GearTopSpeed;",
     "        speeds[5] = GearTopSpeed - 0.01f;"),
    ("tweak-top-speed", CC,
     "float GearTopSpeed  = 89.51f;",
     "float GearTopSpeed  = 89.5f;"),
    ("tweak-test-rpm-0", CC,
     "float TestRPM       = 100.0f;",
     "float TestRPM       = 0.0f;"),
    ("tweak-rpm-table", CC,
     "    5500.0f, 9000.0f,  6500.0f, 7200.0f,  6600.0f, 7000.0f,",
     "    5500.0f, 9000.5f,  6500.0f, 7200.0f,  6600.0f, 7000.0f,"),
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
    # -- slice two ----------------------------------------------------------
    "sinit-graph-first":
        "graph_init stores the array's address and count and reads nothing "
        "in the array, so building the Graph before the stores fill it "
        "leaves every word the same; the order is the image's, kept, not "
        "something a transcript can see",

    # At a speed of exactly 1.0 the Graph answers 0 -- 1.0 opens the
    # (1,0)-(5,10) segment -- so the lookup's argument is dist / 0 = +inf,
    # the Table clamps it to its high end and returns its last entry, 0:
    # the same 0 the early return gives. Only a leader at distance 0 could
    # tell, and that is the NaN the doc describes, which no fixture builds.
    "draft-knee-le":
        "at speed 1.0 the Graph is 0, the lookup argument +inf, and the "
        "Table's last entry 0 -- the early return's answer",
    "draft-knee-index-0":
        "the Graph is 0 at every speed up to 1.0, so a lower threshold only "
        "lets those speeds through to the same +inf lookup and the same 0",
    "draft-cone-le":
        "f == 0 makes f * g zero and the lookup argument +inf, so the Table "
        "gives its last entry, 0 -- the early return's answer",

    # The test after skipping `c` sees the sum the previous pass's test
    # already saw and let through, or the loop would have stopped; when `c`
    # comes first that sum is 0, under the early-out. Skipping the test on
    # `c` never moves the break. The listing's order is kept anyway.
    "sum-test-inside-if":
        "the test on c's pass sees the sum the previous test already let "
        "through, or 0 when c is first",
    # -- slice three --------------------------------------------------------
    # Negation is exact and IEEE rounding is symmetric in sign, so the
    # product of a negated factor and the negated product are one word.
    "rel-across-neg-product":
        "(-a) * b and -(a * b) are the same float32 for every a and b",
    # |(int16)(a - b)| and |(int16)(b - a)| agree: the two differ in sign
    # except at 0x8000, where both are -32768.
    "front-turn-reversed":
        "the magnitude of a 16-bit turn is the same measured either way",
    # No yaw GetYaw can return is exactly 0.13f: all 65536 BAM deltas,
    # folded as GetYaw folds them, were checked, and none lands on it.
    "drift-yaw-le":
        "no reachable yaw equals 0.13f; checked over all 65536 BAM deltas",
    # GetYaw differs from GetYawAlways only below a forward speed of 5, and
    # there the test against 12 fails whatever the yaw was.
    "drift-yaw-always":
        "the forward-speed test against 12 fails wherever GetYaw's gate "
        "at 5 would have answered 0",
    # At |speed| == Gear1To2Speed the clamp stores the value frac holds.
    "fr-frac-clamp-le":
        "at equality the clamp assigns the value frac already has",
    # The loop runs only when speed >= Gear1To2Speed, which is speeds[0],
    # so a pass at i = 0 can never take the band.
    "fr-bands-from-0":
        "the else branch has speed >= speeds[0], so the i = 0 test cannot "
        "pass",
    # When TestRPM is set, st->RPM is stored as TestRPM whatever the
    # smoothing computed, so where it started from cannot be seen.
    "fr-smooth-from-rpm-only":
        "with TestRPM set the smoothed value is discarded for TestRPM; the "
        "arm is dead",
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


def mutate_pass(only=None):
    base_model = model()
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="car_test")
        out = Path(tmp) / "base.txt"
        _, base = harness_lines(exe, out)
        if diff(base_model, base, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        if only and name not in only:
            continue
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
                rc, got = harness_lines(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-32s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-32s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, got, quiet=True)
                if n:
                    print("  %-32s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-32s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
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

    run = [m for m in MUTATIONS if not only or m[0] in only]
    real = [m for m in run if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (not only or n in only)]
    # A pattern that is not found is dropped from the denominator below, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(run)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAMES",
                    help="with --mutate, run only these comma-separated "
                         "mutations")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        only = set(args.only.split(",")) if args.only else None
        if only:
            unknown = only - {m[0] for m in MUTATIONS}
            if unknown:
                sys.exit("no such mutation: %s" % ", ".join(sorted(unknown)))
        sys.exit(mutate_pass(only))

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="car_test")
        out = Path(tmp) / "harness.txt"
        _, harness = harness_lines(exe, out)

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
