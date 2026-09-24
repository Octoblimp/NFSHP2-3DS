"""Cross-check 3DS Files/source/{engine,table}.c against a model of the
Engine and Table objects.

Engine.obj is the second piece of task 25. The engine is a one-state
integrable -- its whole state is the crankshaft angular velocity -- and
everything else in the object exists to work out the torque that drives it:
the torque curve, the engine-braking curve, the throttle, nitro, the rev
limiter and the AI catch-up multiplier.

Table comes along because Engine cannot be modelled without it. It is a
header-inline class rather than an object file, which is why its five
methods are scattered across 0x00181xxx and 0x00187xxx instead of forming
a run.

The model is written from the disassembly. Its float layer is imported from
bvector_check -- itself a model of bVector.obj written from the ELF -- so
the chain of custody for every number runs back to an address.

Two things this transcript is watching for in particular. **State.w is
rad/s and the curves are indexed in RPM**, so a missing conversion moves
every torque. And **the rev limiter reverses torque rather than cutting
it**: past MaxRPM-100 the sign flips and the magnitude grows fifteenfold.

Everything is float32. The EE has no double.

    python tools/engine_check.py
    python tools/engine_check.py --mutate
    python tools/engine_check.py --dump out/engine
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
import bmath_check
import hostbuild
from bvector_check import f32, fadd, fdiv, fmul, fneg, fsub

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/engine_test.c",
    "3DS Files/source/engine.c",
    "3DS Files/source/table.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/emath.c",
]

EN = "3DS Files/source/engine.c"
TB = "3DS Files/source/table.c"
EH = "3DS Files/source/engine.h"


def g9(x):
    return "%.9g" % x


def bits(w):
    return struct.unpack("<f", struct.pack("<I", w))[0]


# --------------------------------------------------------------- constants
#
# Read out of the image's gp-relative pool at gp = 0x328bf0. The names are
# the image's own where .symtab gives one.

RPM_TO_RADS  = bits(0x3dd67745)   # gp-30444, 2pi/60
RADS_TO_RPM  = bits(0x4118c9f3)   # gp-30440 and gp-30436, both 60/2pi
HP_MULT      = bits(0x3f866666)   # gp-21124, TorqueHPMultiplier
MAX_RPM_EFF  = bits(0x41700000)   # gp-21128, MaxRPMEffect = 15
NEG_SCALE    = bits(0x3ecccccd)   # gp-30432, 0.4
TICK_SECONDS = bits(0x3983126f)   # gp-30428, 1/4000

NITRO_SCALE  = f32(3.0)           # 0x40400000
NITRO_SECS   = f32(4.0)           # 0x40800000
LIMIT_MARGIN = f32(100.0)         # 0x42c80000

DRIVER_PLAYER = 1


def _insn(addr):
    return struct.unpack("<I", bmath_check.ELF.read(addr, 4))[0]


# _vt$6Engine, as the ctor builds it: `lui v0,0x29` at 0x001823dc and
# `addiu v0,v0,31352` at 0x001823e4, stored by `sw v0,8(s0)` at 0x00182404.
assert _insn(0x001823dc) >> 26 == 0x0f and _insn(0x001823e4) >> 26 == 0x09
assert _insn(0x00182404) == 0xae020008          # sw v0,8(s0)
ENGINE_VTABLE = (((_insn(0x001823dc) & 0xffff) << 16)
                 + struct.unpack("<h", struct.pack("<H",
                                 _insn(0x001823e4) & 0xffff))[0])
assert ENGINE_VTABLE == bmath_check.ELF.syms["_vt$6Engine"][0]

# The two RPM scales really are the same number in two pool slots.
assert RADS_TO_RPM == bits(0x4118c9f3)


# ------------------------------------------------------------------- Table


class Table(object):
    """Table, 20 bytes. It does not own its entries -- pTable points into
    the *Info struct the constructor was handed."""

    def __init__(self):
        self.entries = None
        self.n = 0
        self.lo = f32(0.0)
        self.hi = f32(0.0)
        self.mult = f32(0.0)


def table_calc_index_multiplier(t):
    """0x00181100."""
    t.mult = fdiv(f32(float(t.n - 1)), fsub(t.hi, t.lo))


def table_set_min_max(t, lo, hi):
    """0x001810b8 -- a tail jump into CalcIndexMultiplier."""
    t.lo = lo
    t.hi = hi
    table_calc_index_multiplier(t)


def table_init(t, entries, n, lo, hi):
    """0x00187268."""
    t.entries = entries
    t.n = n
    table_set_min_max(t, lo, hi)


def table_get_value(t, arg):
    """0x00187298. Two separate clamps, not a min/max pair: the high test
    is only reached when the low one did not fire."""
    if arg < t.lo:
        arg = t.lo
    elif t.hi < arg:
        arg = t.hi

    frac = fmul(fsub(arg, t.lo), t.mult)

    # cvt.w.s truncates toward zero.
    i = int(frac)
    last = t.n - 1

    if i == last:
        return t.entries[i]

    return fadd(t.entries[i],
                fmul(fsub(t.entries[i + 1], t.entries[i]),
                     fsub(frac, f32(float(i)))))


# ------------------------------------------------------------------ Engine


class EngineInfo(object):
    def __init__(self, idle, redline, maxrpm, moi, curve, braking):
        self.IdleRPM = f32(idle)
        self.RedLineRPM = f32(redline)
        self.MaxRPM = f32(maxrpm)
        self.MomentOfInertia = f32(moi)
        self.TorqueCurveTable = [f32(x) for x in curve]
        self.EngineBrakingTable = [f32(x) for x in braking]


class Engine(object):
    __slots__ = ("head", "vtable", "w", "EI", "pCarState",
                 "TorqueCurve", "EngineBraking", "IsHP", "Throttle",
                 "RoadTorque", "ThrottleOverride", "NitroFlag",
                 "NitroBoostTimer", "CatchupTorqueMultiplier")

    def __init__(self):
        self.head = [0] * 8
        self.vtable = 0
        self.w = f32(0.0)
        self.EI = None
        self.pCarState = None
        self.TorqueCurve = Table()
        self.EngineBraking = Table()
        self.IsHP = 0
        self.Throttle = f32(0.0)
        self.RoadTorque = f32(0.0)
        self.ThrottleOverride = f32(0.0)
        self.NitroFlag = 0
        self.NitroBoostTimer = f32(0.0)
        self.CatchupTorqueMultiplier = f32(0.0)


# The image's global 4000 Hz tick, gp-20224. Loaded with lwc1 and then
# cvt.s.w, so it is an integer that gets converted -- not reinterpreted.
WORLD_TIMER = [0]


def engine_init(e, ei, cs):
    """0x001823d8. Note what it leaves alone: Throttle and RoadTorque are
    never written, so a fresh Engine inherits whatever was in the
    allocation."""
    e.vtable = ENGINE_VTABLE

    table_init(e.TorqueCurve, ei.TorqueCurveTable, 9, ei.IdleRPM, ei.MaxRPM)
    table_init(e.EngineBraking, ei.EngineBrakingTable, 3,
               ei.IdleRPM, ei.MaxRPM)

    e.EI = ei
    e.pCarState = cs

    e.CatchupTorqueMultiplier = f32(1.0)
    e.IsHP = 0
    e.NitroFlag = 0
    e.NitroBoostTimer = f32(0.0)
    e.ThrottleOverride = f32(1.0)


def engine_compute_auxiliaries(e):
    """0x00182578. Two branch-likelies in the listing; the low clamp's
    result is what the high test then sees."""
    lo = fmul(e.EI.IdleRPM, RPM_TO_RADS)
    if e.w < lo:
        e.w = lo

    hi = fmul(e.EI.MaxRPM, RPM_TO_RADS)
    if hi < e.w:
        e.w = hi

    e.RoadTorque = f32(0.0)


def engine_get_torque(e):
    """0x00182618."""
    rpm = fmul(e.w, RADS_TO_RPM)
    t = fmul(table_get_value(e.TorqueCurve, rpm), e.CatchupTorqueMultiplier)

    if e.IsHP:
        t = fmul(t, HP_MULT)

    # c.lt.s rpm, (MaxRPM-100) then bc1t to the end: the limiter runs when
    # the comparison is false, which includes a NaN rpm.
    if not (rpm < fsub(e.EI.MaxRPM, LIMIT_MARGIN)):
        t = fmul(fneg(MAX_RPM_EFF), t)

    return t


def engine_get_engine_torque(e, rpm):
    """0x00182760. The same shape as GetTorque at a caller-supplied RPM.
    The listing spells the limiter test the other way round -- (MaxRPM-100)
    <= rpm -- and orders the multiply t * -MaxRPMEffect rather than
    -MaxRPMEffect * t."""
    t = fmul(table_get_value(e.TorqueCurve, rpm), e.CatchupTorqueMultiplier)

    if e.IsHP:
        t = fmul(t, HP_MULT)

    if fsub(e.EI.MaxRPM, LIMIT_MARGIN) <= rpm:
        t = fmul(t, fneg(MAX_RPM_EFF))

    return t


def engine_get_total_engine_torque(e):
    """0x001826a0."""
    eff = fmul(e.Throttle, e.ThrottleOverride)

    drive = fmul(engine_get_torque(e), eff)
    if e.NitroFlag:
        drive = fmul(drive, NITRO_SCALE)

    braking = table_get_value(e.EngineBraking, fmul(e.w, RADS_TO_RPM))

    total = fadd(drive, fmul(fneg(braking), fsub(f32(1.0), eff)))

    # Only a player-driven car gets a negative total softened.
    if e.pCarState is not None and e.pCarState["DriverMode"] == DRIVER_PLAYER:
        if total < f32(0.0):
            total = fmul(total, NEG_SCALE)

    return total


def engine_get_derivative(e, out):
    """0x001825c8. Returns 0; the integrator takes the count from GetSize."""
    out[0] = fdiv(fadd(engine_get_total_engine_torque(e), e.RoadTorque),
                  e.EI.MomentOfInertia)
    return 0


def engine_get_angular_acceleration(e):
    """0x00183ee0 -- the same value GetDerivative writes."""
    return fdiv(fadd(engine_get_total_engine_torque(e), e.RoadTorque),
                e.EI.MomentOfInertia)


def engine_get_torque_response(e):
    """0x00183ec8."""
    return fdiv(f32(1.0), e.EI.MomentOfInertia)


def engine_decrement_nitro(e):
    """0x001827e0."""
    if not e.NitroFlag:
        return
    if fadd(e.NitroBoostTimer, NITRO_SECS) < fmul(f32(float(WORLD_TIMER[0])),
                                                  TICK_SECONDS):
        e.NitroFlag = 0


def engine_apply_torque(e, t):
    """0x00183e18."""
    e.RoadTorque = fadd(e.RoadTorque, t)


def engine_get_effective_throttle(e):
    """0x00183eb0."""
    return fmul(e.Throttle, e.ThrottleOverride)


# ------------------------------------------------------------------- dirt


class Dirt(object):
    def __init__(self):
        self.n = 0

    def f(self):
        self.n += 1
        return f32(-1000.0 - float(self.n))

    def i(self):
        self.n += 1
        return -900 - self.n


def fill_pattern(e):
    d = Dirt()
    e.head = [0xA0] * 8
    e.vtable = 0xA0A0A0A0
    e.w = d.f()
    e.EI = None
    e.pCarState = None
    e.TorqueCurve = Table()
    e.EngineBraking = Table()
    e.IsHP = d.i()
    e.Throttle = d.f()
    e.RoadTorque = d.f()
    e.ThrottleOverride = d.f()
    e.NitroFlag = d.i()
    e.NitroBoostTimer = d.f()
    e.CatchupTorqueMultiplier = d.f()


EI = EngineInfo(1000.0, 6500.0, 7000.0, 0.25,
                [120.0, 180.0, 240.0, 290.0, 320.0, 335.0, 330.0, 300.0,
                 250.0],
                [20.0, 55.0, 90.0])


# --------------------------------------------------------------- printing

OUT = []


def emit(s):
    OUT.append(s)


def print_engine(tag, e):
    emit(tag)
    emit("  head       " + "".join("%02x" % b for b in e.head))
    emit("  vtable     0x%08x" % e.vtable)
    emit("  w %s  rpm %s" % (g9(e.w), g9(fmul(e.w, RADS_TO_RPM))))
    emit("  ei %s  cs %s" % ("set" if e.EI else "null",
                             "set" if e.pCarState else "null"))
    emit("  torquecurve   n %d min %s max %s mult %s"
         % (e.TorqueCurve.n, g9(e.TorqueCurve.lo), g9(e.TorqueCurve.hi),
            g9(e.TorqueCurve.mult)))
    emit("  enginebraking n %d min %s max %s mult %s"
         % (e.EngineBraking.n, g9(e.EngineBraking.lo),
            g9(e.EngineBraking.hi), g9(e.EngineBraking.mult)))
    emit("  ishp %d throttle %s roadtorque %s override %s"
         % (e.IsHP, g9(e.Throttle), g9(e.RoadTorque),
            g9(e.ThrottleOverride)))
    emit("  nitro %d timer %s catchup %s"
         % (e.NitroFlag, g9(e.NitroBoostTimer),
            g9(e.CatchupTorqueMultiplier)))


def pad(s, n):
    return s + " " * max(0, n - len(s))


# -------------------------------------------------------------- scenarios


def s_table():
    emit("== table ==")
    nine = [f32(x) for x in (10.0, 20.0, 45.0, 80.0, 120.0, 150.0, 160.0,
                             140.0, 90.0)]
    three = [f32(x) for x in (-5.0, -12.5, -30.0)]
    one = [f32(7.25)]

    args = [f32(x) for x in (-100.0, 0.0, 800.0, 1000.0, 1000.5, 2000.0,
                             3125.0, 4000.0, 5500.0, 6999.0, 7000.0,
                             7000.5, 9000.0)]

    for name, ent, n in (("nine ", nine, 9), ("three", three, 3),
                         ("one  ", one, 1)):
        t = Table()
        table_init(t, ent, n, f32(1000.0), f32(7000.0))
        emit("  %s n %d min %s max %s mult %s"
             % (name, t.n, g9(t.lo), g9(t.hi), g9(t.mult)))
        for a in args:
            emit("    arg %s -> %s" % (pad(g9(a), 10),
                                       g9(table_get_value(t, a))))

    # An inverted range: the multiplier goes negative and the two clamps
    # stop being interchangeable, because the high test is only reached
    # when the low one did not fire.
    t = Table()
    table_init(t, nine, 9, f32(7000.0), f32(1000.0))
    emit("  inverted n %d min %s max %s mult %s"
         % (t.n, g9(t.lo), g9(t.hi), g9(t.mult)))
    for a in args:
        emit("    arg %s -> %s" % (pad(g9(a), 10), g9(table_get_value(t, a))))

    t = Table()
    table_init(t, nine, 9, f32(1000.0), f32(7000.0))
    table_set_min_max(t, f32(0.0), f32(8.0))
    emit("  rerange min %s max %s mult %s" % (g9(t.lo), g9(t.hi), g9(t.mult)))
    for i in range(10):
        a = fmul(f32(float(i)), f32(0.75))
        emit("    arg %s -> %s" % (pad(g9(a), 10), g9(table_get_value(t, a))))


def s_ctor():
    emit("== ctor ==")
    e = Engine()
    fill_pattern(e)
    engine_init(e, EI, None)
    print_engine("after ctor", e)
    emit("  uninitialised throttle %s roadtorque %s"
         % (g9(e.Throttle), g9(e.RoadTorque)))


def s_auxiliaries():
    emit("== auxiliaries ==")
    ws = [f32(x) for x in (-50.0, 0.0, 10.0, 104.719676, 104.72, 200.0,
                           500.0, 732.0, 733.037781, 1000.0)]
    for w in ws:
        e = Engine()
        fill_pattern(e)
        engine_init(e, EI, None)
        e.w = w
        e.RoadTorque = f32(123.5)
        engine_compute_auxiliaries(e)
        emit("  w %s -> w %s rpm %s roadtorque %s"
             % (pad(g9(w), 12), g9(e.w), g9(fmul(e.w, RADS_TO_RPM)),
                g9(e.RoadTorque)))

    # IdleRPM above MaxRPM. The clamps run in a fixed order and the second
    # overwrites the first, so only an inverted range shows which wins.
    for w in ws:
        e = Engine()
        fill_pattern(e)
        engine_init(e, EI_DEGENERATE, None)
        e.w = w
        e.RoadTorque = f32(123.5)
        engine_compute_auxiliaries(e)
        emit("  degenerate w %s -> w %s rpm %s"
             % (pad(g9(w), 12), g9(e.w), g9(fmul(e.w, RADS_TO_RPM))))


EI_DEGENERATE = EngineInfo(5000.0, 6500.0, 2000.0, 0.25,
                           [120.0, 180.0, 240.0, 290.0, 320.0, 335.0,
                            330.0, 300.0, 250.0],
                           [20.0, 55.0, 90.0])


def s_torque():
    emit("== torque ==")
    rpms = [f32(x) for x in (500.0, 1000.0, 1750.0, 2500.0, 3250.0, 4000.0,
                             5000.0, 6000.0, 6899.0, 6900.0, 6901.0,
                             7000.0, 8000.0)]
    catchup = [f32(1.0), f32(0.8), f32(1.25)]

    for h in (0, 1):
        for c in catchup:
            emit("  ishp %d catchup %s" % (h, g9(c)))
            for rpm in rpms:
                e = Engine()
                fill_pattern(e)
                engine_init(e, EI, None)
                e.IsHP = h
                e.CatchupTorqueMultiplier = c
                e.w = fmul(rpm, RPM_TO_RADS)
                emit("    rpm %s gettorque %s getenginetorque %s"
                     % (pad(g9(rpm), 8), pad(g9(engine_get_torque(e)), 14),
                        g9(engine_get_engine_torque(e, rpm))))


def s_total():
    emit("== total torque ==")
    rpms = [f32(x) for x in (1000.0, 2500.0, 4000.0, 6000.0, 6950.0)]
    thr = [f32(x) for x in (0.0, 0.25, 0.5, 1.0, 1.5, -0.5)]

    for m in (0, 1, 2):
        for n in (0, 1):
            emit("  drivermode %d nitro %d" % (m, n))
            for t in thr:
                for rpm in rpms:
                    e = Engine()
                    fill_pattern(e)
                    cs = {"DriverMode": m}
                    engine_init(e, EI, cs)
                    e.NitroFlag = n
                    e.Throttle = t
                    e.w = fmul(rpm, RPM_TO_RADS)
                    e.RoadTorque = f32(0.0)
                    emit("    rpm %s thr %s total %s eff %s accel %s"
                         % (pad(g9(rpm), 8), pad(g9(t), 6),
                            pad(g9(engine_get_total_engine_torque(e)), 14),
                            pad(g9(engine_get_effective_throttle(e)), 8),
                            g9(engine_get_angular_acceleration(e))))

    emit("  override sweep")
    for t in thr:
        e = Engine()
        fill_pattern(e)
        cs = {"DriverMode": 1}
        engine_init(e, EI, cs)
        e.NitroFlag = 0
        e.Throttle = f32(1.0)
        e.ThrottleOverride = t
        e.w = fmul(f32(3000.0), RPM_TO_RADS)
        e.RoadTorque = f32(0.0)
        emit("    override %s total %s eff %s"
             % (pad(g9(t), 6),
                pad(g9(engine_get_total_engine_torque(e)), 14),
                g9(engine_get_effective_throttle(e))))


def s_derivative():
    emit("== derivative ==")
    roads = [f32(x) for x in (0.0, 50.0, -50.0, 1000.0)]
    cs = {"DriverMode": 1}

    for r in roads:
        e = Engine()
        fill_pattern(e)
        engine_init(e, EI, cs)
        e.Throttle = f32(0.75)
        e.NitroFlag = 0
        e.w = fmul(f32(3500.0), RPM_TO_RADS)
        e.RoadTorque = f32(0.0)

        engine_apply_torque(e, r)
        out = [f32(-12345.0)]
        rc = engine_get_derivative(e, out)

        emit("  road %s roadtorque %s deriv %s rc %d accel %s response %s "
             "size %d"
             % (pad(g9(r), 10), pad(g9(e.RoadTorque), 10),
                pad(g9(out[0]), 14), rc,
                g9(engine_get_angular_acceleration(e)),
                g9(engine_get_torque_response(e)), 1))

    e = Engine()
    fill_pattern(e)
    engine_init(e, EI, cs)
    e.w = fmul(f32(3000.0), RPM_TO_RADS)
    e.RoadTorque = f32(0.0)
    engine_apply_torque(e, f32(10.0))
    engine_apply_torque(e, f32(2.5))
    engine_apply_torque(e, f32(-1.25))
    emit("  accumulated %s" % g9(e.RoadTorque))
    engine_compute_auxiliaries(e)
    emit("  after auxiliaries %s" % g9(e.RoadTorque))


def s_nitro():
    emit("== nitro ==")
    timers = [0, 1000, 16000, 16001, 20000, 40000]
    boosts = [f32(0.0), f32(1.0), f32(4.0)]

    for b in boosts:
        for ti in timers:
            e = Engine()
            fill_pattern(e)
            engine_init(e, EI, None)
            e.NitroFlag = 1
            e.NitroBoostTimer = b
            WORLD_TIMER[0] = ti
            engine_decrement_nitro(e)
            emit("  boost %s timer %s worldsec %s flag %d"
                 % (pad(g9(b), 6), pad("%d" % ti, 7),
                    pad(g9(fmul(f32(float(ti)), TICK_SECONDS)), 12),
                    e.NitroFlag))

    e = Engine()
    fill_pattern(e)
    engine_init(e, EI, None)
    e.NitroFlag = 0
    e.NitroBoostTimer = f32(0.0)
    WORLD_TIMER[0] = 1000000
    engine_decrement_nitro(e)
    emit("  already clear -> flag %d" % e.NitroFlag)
    WORLD_TIMER[0] = 0


def s_accessors():
    emit("== accessors ==")
    e = Engine()
    fill_pattern(e)
    engine_init(e, EI, {"DriverMode": 0})

    e.Throttle = f32(0.625)
    e.ThrottleOverride = f32(0.5)
    e.IsHP = 1
    e.NitroFlag = 1
    e.NitroBoostTimer = f32(2.25)
    e.CatchupTorqueMultiplier = f32(1.125)
    e.w = f32(300.0)

    emit("  w %s idle %s redline %s max %s"
         % (g9(e.w), g9(EI.IdleRPM), g9(EI.RedLineRPM), g9(EI.MaxRPM)))
    emit("  throttle %s eff %s ishp %d nitro %d timer %s"
         % (g9(e.Throttle), g9(engine_get_effective_throttle(e)),
            e.IsHP, e.NitroFlag, g9(e.NitroBoostTimer)))
    emit("  ei same state->w %s size %d" % (g9(e.w), 1))
    emit("  getstate %s" % g9(e.w))

    e.w = f32(456.75)
    emit("  setstate %s" % g9(e.w))

    engine_apply_torque(e, f32(3.5))
    emit("  applytorque %s response %s"
         % (g9(e.RoadTorque), g9(engine_get_torque_response(e))))


SCENARIOS = [
    ("table", s_table),
    ("ctor", s_ctor),
    ("auxiliaries", s_auxiliaries),
    ("torque", s_torque),
    ("total", s_total),
    ("derivative", s_derivative),
    ("nitro", s_nitro),
    ("accessors", s_accessors),
]


def model():
    global OUT
    OUT = []
    emit("sizes engineps2 92 table %d engineinfo 64"
         % (20 + (8 - 4) if struct.calcsize("P") == 8 else 20))
    for _, fn in SCENARIOS:
        fn()
    return OUT


# ---------------------------------------------------------------- driver


# A mutation can turn a `for (;;)` into a loop with no exit. With no
# deadline here that mutant spins until something kills it and stalls the
# whole pass rather than being counted; the harness itself runs in well
# under a second.
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
    # -- Table ---------------------------------------------------------
    ("table-mult-no-minus-one", TB,
     "t->IndexMultiplier = (float)(t->NumEntries - 1) / (t->MaxArg - t->MinArg);",
     "t->IndexMultiplier = (float)(t->NumEntries) / (t->MaxArg - t->MinArg);"),
    ("table-no-low-clamp", TB,
     "    if (arg < t->MinArg)" + NL + "        arg = t->MinArg;",
     "    if (0)" + NL + "        arg = t->MinArg;"),
    ("table-no-high-clamp", TB,
     "    else if (t->MaxArg < arg)" + NL + "        arg = t->MaxArg;",
     "    else if (0)" + NL + "        arg = t->MaxArg;"),
    ("table-clamps-independent", TB,
     "    if (arg < t->MinArg)" + NL + "        arg = t->MinArg;" + NL
     + "    else if (t->MaxArg < arg)",
     "    if (arg < t->MinArg)" + NL + "        arg = t->MinArg;" + NL
     + "    if (t->MaxArg < arg)"),
    ("table-rounds", TB, "    i    = (int32_t)frac;",
     "    i    = (int32_t)(frac + 0.5f);"),
    ("table-no-last-special", TB,
     "    if (i == last)" + NL + "        return t->pTable[i];",
     "    if (0)" + NL + "        return t->pTable[i];"),
    ("table-lerp-wrong-frac", TB,
     "* (frac - (float)i);", "* frac;"),

    # -- ctor -----------------------------------------------------------
    ("ctor-vtable-zero", EN, "    e->_vtable = ENGINE_VTABLE;",
     "    e->_vtable = 0;"),
    ("h-vtable", EH, "#define ENGINE_VTABLE 0x00297a78u",
     "#define ENGINE_VTABLE 0x00297a70u"),
    ("ctor-curve-entries", EN,
     "    table_init(&e->TorqueCurve,   ei->TorqueCurveTable,   9,",
     "    table_init(&e->TorqueCurve,   ei->TorqueCurveTable,   8,"),
    ("ctor-braking-entries", EN,
     "    table_init(&e->EngineBraking, ei->EngineBrakingTable, 3,",
     "    table_init(&e->EngineBraking, ei->EngineBrakingTable, 4,"),
    ("ctor-curve-range-redline", EN,
     "    table_init(&e->TorqueCurve,   ei->TorqueCurveTable,   9," + NL
     + "               ei->IdleRPM, ei->MaxRPM);",
     "    table_init(&e->TorqueCurve,   ei->TorqueCurveTable,   9," + NL
     + "               ei->IdleRPM, ei->RedLineRPM);"),
    ("ctor-braking-range-zero", EN,
     "    table_init(&e->EngineBraking, ei->EngineBrakingTable, 3," + NL
     + "               ei->IdleRPM, ei->MaxRPM);",
     "    table_init(&e->EngineBraking, ei->EngineBrakingTable, 3," + NL
     + "               0.0f, ei->MaxRPM);"),
    ("ctor-override-zero", EN, "    e->ThrottleOverride        = 1.0f;",
     "    e->ThrottleOverride        = 0.0f;"),
    ("ctor-catchup-zero", EN, "    e->CatchupTorqueMultiplier = 1.0f;",
     "    e->CatchupTorqueMultiplier = 0.0f;"),
    ("ctor-clears-throttle", EN,
     "    e->ThrottleOverride        = 1.0f;",
     "    e->ThrottleOverride        = 1.0f;" + NL
     + "    e->Throttle = 0.0f;"),
    ("ctor-clears-roadtorque", EN,
     "    e->ThrottleOverride        = 1.0f;",
     "    e->ThrottleOverride        = 1.0f;" + NL
     + "    e->RoadTorque = 0.0f;"),
    ("ctor-ishp-set", EN, "    e->IsHP                    = 0;",
     "    e->IsHP                    = 1;"),

    # -- auxiliaries ------------------------------------------------------
    ("aux-no-low-clamp", EN,
     "    if (e->State.w < lo)" + NL + "        e->State.w = lo;",
     "    if (0)" + NL + "        e->State.w = lo;"),
    ("aux-no-high-clamp", EN,
     "    if (hi < e->State.w)" + NL + "        e->State.w = hi;",
     "    if (0)" + NL + "        e->State.w = hi;"),
    ("aux-no-rpm-conversion", EN,
     "    float lo = e->EI->IdleRPM * ENGINE_RPM_TO_RADS;",
     "    float lo = e->EI->IdleRPM;"),
    ("aux-high-uses-redline", EN,
     "    hi = e->EI->MaxRPM * ENGINE_RPM_TO_RADS;",
     "    hi = e->EI->RedLineRPM * ENGINE_RPM_TO_RADS;"),
    ("aux-no-roadtorque-clear", EN, "    e->RoadTorque = 0.0f;" + NL + "}",
     "}"),
    ("aux-clamp-order", EN,
     "    if (e->State.w < lo)" + NL + "        e->State.w = lo;" + NL + NL
     + "    hi = e->EI->MaxRPM * ENGINE_RPM_TO_RADS;" + NL + NL
     + "    if (hi < e->State.w)" + NL + "        e->State.w = hi;",
     "    hi = e->EI->MaxRPM * ENGINE_RPM_TO_RADS;" + NL + NL
     + "    if (hi < e->State.w)" + NL + "        e->State.w = hi;" + NL + NL
     + "    if (e->State.w < lo)" + NL + "        e->State.w = lo;"),

    # -- torque -----------------------------------------------------------
    ("torque-no-rads-to-rpm", EN,
     "    float rpm = e->State.w * ENGINE_RADS_TO_RPM;",
     "    float rpm = e->State.w;"),
    ("torque-no-catchup", EN,
     "    float t   = table_get_value(&e->TorqueCurve, rpm)" + NL
     + "              * e->CatchupTorqueMultiplier;",
     "    float t   = table_get_value(&e->TorqueCurve, rpm);"),
    ("torque-hp-always", EN,
     "    if (e->IsHP)" + NL + "        t *= ENGINE_TORQUE_HP_MULTIPLIER;"
     + NL + NL + "    // Not a cut",
     "    if (1)" + NL + "        t *= ENGINE_TORQUE_HP_MULTIPLIER;"
     + NL + NL + "    // Not a cut"),
    ("torque-hp-mult-value", EH,
     "#define ENGINE_TORQUE_HP_MULTIPLIER 1.04999995f",
     "#define ENGINE_TORQUE_HP_MULTIPLIER 1.10000002f"),
    ("torque-limiter-margin", EN, "#define REV_LIMITER_MARGIN 100.0f",
     "#define REV_LIMITER_MARGIN 50.0f"),
    ("torque-limiter-cuts", EN,
     "        t = -ENGINE_MAX_RPM_EFFECT * t;",
     "        t = 0.0f;"),
    ("torque-limiter-no-negate", EN,
     "        t = -ENGINE_MAX_RPM_EFFECT * t;",
     "        t = ENGINE_MAX_RPM_EFFECT * t;"),
    ("torque-limiter-strict", EN,
     "    if (!(rpm < e->EI->MaxRPM - REV_LIMITER_MARGIN))",
     "    if (rpm > e->EI->MaxRPM - REV_LIMITER_MARGIN)"),
    ("torque-max-rpm-effect", EH,
     "#define ENGINE_MAX_RPM_EFFECT       15.0f",
     "#define ENGINE_MAX_RPM_EFFECT       12.0f"),
    ("enginetorque-uses-state", EN,
     "float engine_get_engine_torque(Engine *e, float rpm)" + NL + "{" + NL
     + "    float t = table_get_value(&e->TorqueCurve, rpm)",
     "float engine_get_engine_torque(Engine *e, float rpm)" + NL + "{" + NL
     + "    float t = table_get_value(&e->TorqueCurve,"
     " e->State.w * ENGINE_RADS_TO_RPM)"),
    ("enginetorque-limiter-lt", EN,
     "    if (e->EI->MaxRPM - REV_LIMITER_MARGIN <= rpm)",
     "    if (e->EI->MaxRPM - REV_LIMITER_MARGIN < rpm)"),

    # -- total torque -------------------------------------------------------
    ("total-no-throttle", EN,
     "    drive = engine_get_torque(e) * eff;",
     "    drive = engine_get_torque(e);"),
    ("total-nitro-scale", EN, "#define NITRO_TORQUE_SCALE 3.0f",
     "#define NITRO_TORQUE_SCALE 2.0f"),
    ("total-nitro-always", EN,
     "    if (e->NitroFlag)" + NL + "        drive *= NITRO_TORQUE_SCALE;",
     "    if (1)" + NL + "        drive *= NITRO_TORQUE_SCALE;"),
    ("total-braking-not-negated", EN,
     "    total = drive + -braking * (1.0f - eff);",
     "    total = drive + braking * (1.0f - eff);"),
    ("total-braking-scaled-by-eff", EN,
     "    total = drive + -braking * (1.0f - eff);",
     "    total = drive + -braking * eff;"),
    ("total-braking-unscaled", EN,
     "    total = drive + -braking * (1.0f - eff);",
     "    total = drive + -braking;"),
    ("total-braking-uses-torque-curve", EN,
     "    braking = table_get_value(&e->EngineBraking," + NL
     + "                              e->State.w * ENGINE_RADS_TO_RPM);",
     "    braking = table_get_value(&e->TorqueCurve," + NL
     + "                              e->State.w * ENGINE_RADS_TO_RPM);"),
    ("total-negscale-all-drivers", EN,
     "    if (e->pCarState->DriverMode == DRIVER_MODE_PLAYER) {" + NL
     + "        if (total < 0.0f)" + NL
     + "            total *= NEGATIVE_TORQUE_SCALE;" + NL + "    }",
     "    if (total < 0.0f)" + NL
     + "        total *= NEGATIVE_TORQUE_SCALE;"),
    ("total-negscale-value", EN, "#define NEGATIVE_TORQUE_SCALE 0.400000006f",
     "#define NEGATIVE_TORQUE_SCALE 0.5f"),
    ("total-negscale-positive", EN,
     "        if (total < 0.0f)" + NL
     + "            total *= NEGATIVE_TORQUE_SCALE;",
     "        if (total > 0.0f)" + NL
     + "            total *= NEGATIVE_TORQUE_SCALE;"),
    ("total-player-mode-two", EN, "#define DRIVER_MODE_PLAYER 1",
     "#define DRIVER_MODE_PLAYER 2"),

    # -- derivative / nitro ---------------------------------------------------
    ("deriv-no-roadtorque", EN,
     "    out[0] = (engine_get_total_engine_torque(e) + e->RoadTorque)" + NL
     + "           / e->EI->MomentOfInertia;",
     "    out[0] = engine_get_total_engine_torque(e)" + NL
     + "           / e->EI->MomentOfInertia;"),
    ("deriv-multiplies-moi", EN,
     "    out[0] = (engine_get_total_engine_torque(e) + e->RoadTorque)" + NL
     + "           / e->EI->MomentOfInertia;",
     "    out[0] = (engine_get_total_engine_torque(e) + e->RoadTorque)" + NL
     + "           * e->EI->MomentOfInertia;"),
    ("response-not-reciprocal", EN, "    return 1.0f / e->EI->MomentOfInertia;",
     "    return e->EI->MomentOfInertia;"),
    ("applytorque-assigns", EN, "    e->RoadTorque += t;",
     "    e->RoadTorque = t;"),
    ("nitro-seconds", EN, "#define NITRO_SECONDS      4.0f",
     "#define NITRO_SECONDS      5.0f"),
    ("nitro-tick-seconds", EN, "#define WORLD_TICK_SECONDS 0.000250000012f",
     "#define WORLD_TICK_SECONDS 0.001f"),
    ("nitro-no-flag-guard", EN,
     "    if (!e->NitroFlag)" + NL + "        return;",
     "    if (0)" + NL + "        return;"),
    ("nitro-comparison-flipped", EN,
     "    if (e->NitroBoostTimer + NITRO_SECONDS" + NL
     + "            < (float)WorldTimer * WORLD_TICK_SECONDS)",
     "    if (e->NitroBoostTimer + NITRO_SECONDS" + NL
     + "            > (float)WorldTimer * WORLD_TICK_SECONDS)"),
    ("nitro-sets-flag", EN, "        e->NitroFlag = 0;",
     "        e->NitroFlag = 1;"),

    # -- accessors --------------------------------------------------------
    ("eff-throttle-adds", EN,
     "    return e->Throttle * e->ThrottleOverride;" + NL + "}",
     "    return e->Throttle + e->ThrottleOverride;" + NL + "}"),
    ("getsize-two", EN, "int32_t engine_get_size(const Engine *e)        "
     "{ (void)e; return 1; }",
     "int32_t engine_get_size(const Engine *e)        "
     "{ (void)e; return 2; }"),
    ("redline-is-max", EN,
     "float engine_get_red_line_rpm(const Engine *e)  "
     "{ return e->EI->RedLineRPM; }",
     "float engine_get_red_line_rpm(const Engine *e)  "
     "{ return e->EI->MaxRPM; }"),
]

# Mutants that cannot move a line. Each one is an argument, not an excuse.
#
#   table-no-last-special -- dropping the `i == last` guard cannot change a
#   returned value. When the guard fires, frac - i is exactly zero, so the
#   interpolation term is (pTable[i+1] - pTable[i]) * 0.0 and the result is
#   pTable[i] either way. What the guard actually prevents is the read of
#   pTable[i+1], which is one past the end of the caller's array -- the
#   engine's curves live inside EngineInfo, so that read would pick up
#   EngineBrakingTable[0] or whatever follows. It stays equivalent only
#   while that neighbouring float is finite; an inf or NaN there would make
#   0.0 * it a NaN. The guard is a bounds check, not an arithmetic one, and
#   a transcript of returned values is the wrong instrument for it.
#
#   nitro-no-flag-guard -- the early-out is a speed optimisation with no
#   semantics behind it. With NitroFlag already zero the body either writes
#   zero over zero or does nothing at all, depending on the clock, so no
#   sequence of calls can tell the two versions apart.
EQUIVALENT = [
    "table-no-last-special",
    "nitro-no-flag-guard",
]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="engine_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="engine_test")
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
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
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
        exe = hostbuild.build(tmp, SOURCES, name="engine_test")
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
