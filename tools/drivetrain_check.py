"""Cross-check 3DS Files/source/drivetrain.c against a model of DriveTrain.

DriveTrain is the ninth slice of task 25, after CarState, Engine,
CarTypeInfo, CarDriver, Steering, RigidBody, Suspension and Wheel. It is
the gearbox, the clutch and the differential.

This model is written from the disassembly at 0x00182828..0x00183e10 and
from the `.mdebug` layout, not from the C. Every constant it uses is read
out of `PS2 Files/NFSHP2.ELF` by address -- the eight tuning globals in
.sdata at 0x00323970, WorldTimeElapsed at 0x00323d00, the four-entry
ClutchSpeed table at 0x00307f30, and all twenty-four slots of the object's
own literal pool at 0x00321518..0x00321574. A typo in the header shows as
a diff rather than as two files agreeing with each other.

The literal pool is read *slot by slot*, not once per distinct value. The
compiler pooled 0.001 six times and 0.999 six times, once per use site, and
drivetrain.h collapses each family into one macro. Reading them separately
is what makes that collapse a checked claim instead of an assumption.

Table and Engine come from engine_check's model rather than being written
again here: GuessClutchTorque and ModifyClutchTorque both call
GetTotalEngineTorque, and re-deriving the whole torque curve would
duplicate a model that already has its own transcript. Wheel and CarState
are local stand-ins, because DriveTrain only ever touches nine fields of
the four-hundred-byte Wheel and three of CarState.

Eight things the transcript exists to pin down.

**Two of the three differential queries halve, and they disagree about
when.** GetDifferentialAngularVelocity and
GetDifferentialAngularAcceleration only halve when both axles drive -- the
`bnel` that does it is inside the front arm and is skipped entirely when
the front arm does not run. GetDriveWheelSlippage halves
unconditionally inside its front arm, so a front-drive car reports *half*
its front wheels' mean slip. The `dv`, `da` and `ds` scenarios run all
three across rear-only, front-only and both, so the odd one out cannot
hide.

**The shift-point search scales its fallback and not its dead arm.** The
crossover arm and the MaxRPM - 200 fallback join at 0x001829a0, before the
multiply by `scale`; the interpolated arm joins at 0x001829cc, after it.
The `sp` scenarios run a crossover, a fallback, a loop that never starts,
and the interpolated arm, with `scale` set to something that is not 1.

**GearShiftMethod ships as 1.** The interpolated arm is dead code in the
shipped build. It is run anyway, from the value the ELF actually holds and
then from the other one, because the global is writable .sdata.

**The differential's torque split is clamped backwards on purpose.** A rim
whose share has fallen below the threshold is handed 0.825, not 0.175.
That is the limited slip: torque leaves the wheel that is running away.
The `ac` scenario walks a share from 0 to 1 in steps so both clamps and
the open band between them appear in order.

**BurnOutState splits diagonally.** The rear block names its first wheel
and the front block names its second, so BurnOutState 1 gives the large
share to wheels 1 and 2 and the small one to 0 and 3. The `ac` scenario
prints all four AppliedTorques for both burnout values.

**ApplyClutchTorque in NEUTRAL does not touch RoadTorque.** The early
return is before the subtraction, so a torque applied in neutral vanishes
instead of braking the engine. The `ac` scenario applies one and prints
RoadTorque either side.

**A driven pair standing still divides zero by zero.** The share is
w / (w + w'), and two stopped rims make it 0/0 on every frame a car sits in
gear. IEEE says NaN, and the NaN would go on into AppliedTorque and from
there everywhere; the R5900 says FLT_MAX, signed by the XOR of the signs,
which the clamp turns into the small share. The port divides with eefpu.h's
ee_div there, and this model with its own `ee_div`. The `ac still` scenario
runs both zeros, both mixed-sign zeros and a pair spinning opposite ways --
whose divide by an exact zero IEEE would answer with an infinity that
clamps the same, so only the zeros tell the two apart.

**Nineteen instructions of SetDesiredGear are unreachable.** The arm at
0x00183b94 needs DesiredGear and SportGear to be neither equal nor
ordered. They are two ints. The port keeps the arm; the mutation pass
records a survivor there and argues it rather than deleting the code.

Usage:

    python tools/drivetrain_check.py
    python tools/drivetrain_check.py --mutate
    python tools/drivetrain_check.py --dump out/drivetrain
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
import bmath_check as BM
import bvector_check as BV
import engine_check as EN          # its Table and its Engine

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/drivetrain_test.c",
    "3DS Files/source/drivetrain.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/replay.c", "3DS Files/source/p32.c",
    "3DS Files/source/engine.c",
    "3DS Files/source/wheel.c",       # drivetrain.c's SetState/GetRadius
    "3DS Files/source/suspension.c",  # and wheel.c's own dependencies
    "3DS Files/source/steering.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

DH = "3DS Files/source/drivetrain.h"
DC = "3DS Files/source/drivetrain.c"

# The host this runs on, not the handheld. Every PS2 offset below is stated
# in PS2 terms and widened from here, the same way the header's assert does.
PTR = 8
SLACK = PTR - 4

f32 = BV.f32
fmul, fadd, fsub, fdiv, fneg = BV.fmul, BV.fadd, BV.fsub, BV.fdiv, BV.fneg
fabs32 = BV.fabs32


def ee_div(a, b):
    """`div.s` as the R5900 has it for a zero or denormal divisor: FLT_MAX
    signed by the XOR of the operands' signs, whatever the dividend. eefpu.h's
    ee_div; mipsemu's `eediv`."""
    ab = struct.unpack("<I", struct.pack("<f", a))[0]
    bb = struct.unpack("<I", struct.pack("<f", b))[0]
    if not bb & 0x7F800000:
        r = ((ab ^ bb) & 0x80000000) | 0x7F7FFFFF
        return struct.unpack("<f", struct.pack("<I", r))[0]
    return fdiv(a, b)

ZERO = f32(0.0)
ONE = f32(1.0)
HALF = f32(0.5)


def g9(x):
    return "%.9g" % x


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


OUT = []


def emit(s):
    OUT.append(s)


def pf(tag, x):
    emit("%s %s" % (tag, g9(x)))


def pint(tag, x):
    emit("%s %d" % (tag, x))


# --------------------------------------------------------- the image's data

def elf_f(addr):
    return struct.unpack("<f", BM.ELF.read(addr, 4))[0]


def elf_i(addr):
    return struct.unpack("<i", BM.ELF.read(addr, 4))[0]


def elf_fs(addr, n):
    return [elf_f(addr + 4 * i) for i in range(n)]


# .sdata, 0x00323970..0x0032398c. The MAP file's names.
G_ENGINE_BRAKING_FACTOR = elf_f(0x00323970)
G_SHIFT_UP_DETUNE = elf_f(0x00323974)
G_SHIFT_DOWN_DETUNE = elf_f(0x00323978)
G_GEAR_SHIFT_METHOD = elf_i(0x0032397C)
G_LIMITED_SLIP = elf_f(0x00323980)
G_CLUTCH_LIMITER = elf_f(0x00323984)
G_CLUTCH_MATCHED_THRESHOLD = elf_f(0x00323988)
G_MAX_DOWN_SHIFT_OVER = elf_f(0x0032398C)

# 0x00323d00, the frame loop's, not this object's.
G_WORLD_TIME_ELAPSED = elf_f(0x00323D00)

# 0x00307f30, ClutchSpeed. Four floats in Engine.obj's .data.
CLUTCH_SPEED = elf_fs(0x00307F30, 4)

# The object's literal pool, one slot per use site. The names say which
# function reads each one; the repeats are the compiler's, not this file's.
K_DV_REAR = elf_f(0x00321518)        # GetDifferentialAngularVelocity
K_DV_FRONT = elf_f(0x0032151C)
K_DS_REAR = elf_f(0x00321520)        # GetDriveWheelSlippage
K_DS_FRONT = elf_f(0x00321524)
K_MPS_TO_MPH = elf_f(0x00321528)     # SetDifferentialAngularVelocity
K_SV_REAR = elf_f(0x0032152C)
K_SV_FRONT = elf_f(0x00321530)
K_DA_REAR = elf_f(0x00321534)        # GetDifferentialAngularAcceleration
K_DA_FRONT = elf_f(0x00321538)
K_SLIP_THROTTLE = elf_f(0x0032153C)  # ComputeAuxiliaries
K_ENGINE_PULL = elf_f(0x00321540)
K_ENGAGING_PEDAL = elf_f(0x00321544)
K_DISENGAGED_THROTTLE = elf_f(0x00321548)
K_MC_FRONT = elf_f(0x0032154C)       # ModifyClutchTorque
K_MC_REAR = elf_f(0x00321550)
K_IDLE_THROTTLE = elf_f(0x00321554)  # Idling
K_RPM_TO_RADS = elf_f(0x00321558)
K_IDLE_SLOP = elf_f(0x0032155C)
K_RADS_TO_RPM_AUTO = elf_f(0x00321560)   # SetDesiredGear, AUTOMATIC
K_CRAWL_THROTTLE_AUTO = elf_f(0x00321564)
K_RADS_TO_RPM_SPORT = elf_f(0x00321568)  # SetDesiredGear, SPORT_SHIFT
K_CRAWL_THROTTLE_SPORT = elf_f(0x0032156C)
K_RWD = elf_f(0x00321570)            # RearWheelDrive
K_FWD = elf_f(0x00321574)            # FrontWheelDrive

# Spelled inline as `lui at,0x...` plus `mtc1`, so they are written here
# rather than read: there is no pool slot to read them from.
K_LOW_SPEED_MPH = f32(40.0)          # 0x42200000
K_SHIFT_STEP = f32(50.0)             # 0x42480000
K_SHIFT_CEILING = f32(200.0)         # 0x43480000
K_CRAWL_OVER_IDLE = f32(100.0)       # 0x42c80000
K_UPSHIFT_SLIP = f32(4.0)            # 0x40800000
K_SPORT_HOLD = f32(10.0)             # 0x41200000
K_LIMITER_MARGIN = f32(300.0)        # 0x43960000

DRIVETRAIN_VTABLE = 0x00297A30

# ------------------------------------------------------------- the enums

SPORT_SHIFT = -2
AUTOMATIC = -1
REVERSE = 0
NEUTRAL = 1
FIRST_GEAR = 2
SECOND_GEAR = 3
THIRD_GEAR = 4
FOURTH_GEAR = 5
FIFTH_GEAR = 6
SIXTH_GEAR = 7
SEVENTH_GEAR = 8

CLUTCH_DISENGAGING = 0
CLUTCH_DISENGAGED = 1
CLUTCH_ENGAGING = 2
CLUTCH_ENGAGED = 3

GEAR_NAME = {-2: "SPORT", -1: "AUTO", 0: "REV", 1: "NEU", 2: "1st",
             3: "2nd", 4: "3rd", 5: "4th", 6: "5th", 7: "6th", 8: "7th"}
CLUTCH_NAME = ["Disengaging", "Disengaged", "Engaging", "Engaged"]


def gname(g):
    return GEAR_NAME.get(g, "g%d" % g)


def cname(c):
    return CLUTCH_NAME[c] if 0 <= c < 4 else "c%d" % c


# ------------------------------------------------------- the tuning globals
#
# Mutable, the way .sdata is. Scenarios move them and put them back, and
# the harness has the same eight names to move.

G = {}


def reset_globals():
    G["EngineBrakingFactor"] = f32(G_ENGINE_BRAKING_FACTOR)
    G["ShiftUpDetune"] = f32(G_SHIFT_UP_DETUNE)
    G["ShiftDownDetune"] = f32(G_SHIFT_DOWN_DETUNE)
    G["GearShiftMethod"] = G_GEAR_SHIFT_METHOD
    G["LimitedSlip"] = f32(G_LIMITED_SLIP)
    G["ClutchLimiter"] = f32(G_CLUTCH_LIMITER)
    G["ClutchMatchedThreshold"] = f32(G_CLUTCH_MATCHED_THRESHOLD)
    G["MaxDownShiftOver"] = f32(G_MAX_DOWN_SHIFT_OVER)
    G["WorldTimeElapsed"] = f32(G_WORLD_TIME_ELAPSED)


reset_globals()


# ------------------------------------------------------------- the records

class DriveTrainInfo(object):
    """64 bytes, part of CarTypeInfo. Read-only to DriveTrain."""

    def __init__(self, up_point, down_rpm, final_drive, split, stiffness,
                 num_gears, shift_speed, ratios):
        self.ShiftUpPoint = f32(up_point)        #  0
        self.ShiftDownRPM = f32(down_rpm)        #  4, unread by this object
        self.FinalDrive = [f32(x) for x in final_drive]   # 8, two of them
        self.TorqueSplit = f32(split)            # 16
        self.ClutchStiffness = f32(stiffness)    # 20
        self.NumGears = num_gears                # 24
        self.ShiftSpeed = f32(shift_speed)       # 28
        self.GearRatios = [f32(x) for x in ratios]        # 32, eight


class Wheel(object):
    """DriveTrain's whole view of a Wheel: nine fields out of four hundred
    bytes, at the offsets the listing loads them from."""

    def __init__(self, radius=0.32, moi=0.01):
        self.w = ZERO                    #  32, State.w
        self.MomentOfInertia = f32(moi)  #  36
        self.AppliedTorque = ZERO        # 264
        self.BrakeLocked = 0             # 268
        self.GroundForce0 = ZERO         # 276, GroundForce[0]
        self.TouchingGround = 0          # 341, a signed byte
        self.CurrentSlip = ZERO          # 352
        self.OldSlip = ZERO              # 356
        self.Radius = f32(radius)        # WI->Radius, through GetRadius


def make_car_state(speed=0.0, burnout=0, driver=0):
    """Three fields out of a kilobyte: VelocityMagnitude at 896,
    BurnOutState at 928, and DriverMode at 920 for the engine's benefit."""
    return {"VelocityMagnitude": f32(speed), "BurnOutState": burnout,
            "DriverMode": driver}


class DriveTrain(object):
    """calloc's view: every field zero until something writes it, which is
    what the harness allocates."""

    def __init__(self):
        self.pNext = 0
        self.pPrev = 0
        self.vtable = 0
        self.clutch = ZERO
        self.DTI = None
        self.pEngine = None
        self.pDriveWheel = [None, None, None, None]
        self.pCarState = None
        self.DesiredGear = 0
        self.CurrentGear = 0
        self.PreviousGear = 0
        self.CurrentClutchState = 0
        self.Shifting = 0
        self.DifferentialAngularVelocity = ZERO
        self.GearHoldTime = ZERO
        self.SportGear = 0
        self.ShiftUpRPM = [ZERO] * 9
        self.ShiftDownRPM = [ZERO] * 9


# ----------------------------------------------------------- the free one

def calculate_shift_points(dti, ei, up, down, scale):
    """0x00182828."""
    torque = EN.Table()
    EN.table_init(torque, ei.TorqueCurveTable, 9, ei.IdleRPM, ei.MaxRPM)

    last = dti.NumGears + 1
    i = FIRST_GEAR

    while i < last:
        ratio = dti.GearRatios[i]
        nxt = dti.GearRatios[i + 1]

        if G["GearShiftMethod"]:
            ceiling = fsub(ei.MaxRPM, K_SHIFT_CEILING)
            rpm = fmul(fadd(ei.IdleRPM, ei.MaxRPM), HALF)
            searching = 1

            # The flag is set in the entry branch's delay slot, so it is 1
            # even on the path where the loop never runs.
            if rpm < ceiling:
                while True:
                    here = EN.table_get_value(torque, rpm)
                    arg = fdiv(fmul(rpm, nxt), ratio)
                    there = fdiv(fmul(EN.table_get_value(torque, arg), nxt),
                                 ratio)

                    if here < there:
                        up[i] = rpm
                        searching = 0

                    rpm = fadd(rpm, K_SHIFT_STEP)

                    if not (rpm < ceiling and searching):
                        break

            if searching:
                up[i] = fsub(ei.MaxRPM, K_SHIFT_CEILING)

            point = fmul(up[i], scale)
        else:
            point = fadd(ei.IdleRPM,
                         fmul(dti.ShiftUpPoint,
                              fsub(ei.RedLineRPM, ei.IdleRPM)))

        up[i] = point
        down[i + 1] = fdiv(fmul(fmul(G["ShiftDownDetune"], up[i]), nxt),
                           ratio)
        i += 1

    up[i] = ei.MaxRPM


# ------------------------------------------------------------- the object

def drivetrain_init(d, dti, e, wheels, cs):
    """0x00182a60. Nine stores, a four-pointer copy and one call."""
    d.pEngine = e
    d.vtable = DRIVETRAIN_VTABLE
    d.DTI = dti

    for k in range(4):
        d.pDriveWheel[k] = wheels[k]

    d.pCarState = cs

    calculate_shift_points(dti, e.EI, d.ShiftUpRPM, d.ShiftDownRPM,
                           G["ShiftUpDetune"])

    d.DesiredGear = FIRST_GEAR
    d.clutch = ZERO
    d.CurrentClutchState = CLUTCH_ENGAGING
    d.CurrentGear = FIRST_GEAR
    d.Shifting = 0

    # PreviousGear, DifferentialAngularVelocity, GearHoldTime and SportGear
    # are not written.


def get_differential_angular_velocity(d):
    """0x00182bf0."""
    dti = d.DTI
    split = dti.TorqueSplit
    w = ZERO
    rear = K_DV_REAR <= split
    both = 1

    if rear:
        w = fmul(fmul(fadd(d.pDriveWheel[2].w, d.pDriveWheel[3].w), HALF),
                 dti.FinalDrive[1])

    if split <= K_DV_FRONT:
        w = fadd(w,
                 fmul(fmul(fadd(d.pDriveWheel[0].w, d.pDriveWheel[1].w),
                           HALF), dti.FinalDrive[0]))

        if not rear:
            both = 0

        if both:
            w = fmul(w, HALF)

    return fmul(w, dti.GearRatios[d.CurrentGear])


def get_drive_wheel_slippage(d):
    """0x00182cc0. No `both` flag: the halving is unconditional inside the
    front arm."""
    dti = d.DTI
    split = dti.TorqueSplit
    s = ZERO

    if K_DS_REAR <= split:
        s = fmul(fadd(d.pDriveWheel[2].OldSlip, d.pDriveWheel[3].OldSlip),
                 HALF)

    if split <= K_DS_FRONT:
        s = fmul(fadd(s,
                      fmul(fadd(d.pDriveWheel[0].OldSlip,
                                d.pDriveWheel[1].OldSlip), HALF)), HALF)

    return s


def share_out(d, delta, lo, hi, drive, slow):
    """The body of SetDifferentialAngularVelocity, once per driven pair."""
    a = d.pDriveWheel[lo]
    b = d.pDriveWheel[hi]

    if not a.TouchingGround and not b.TouchingGround:
        slow = 1

    ratio = fmul(d.DTI.GearRatios[d.CurrentGear], drive)

    # In the delay slot of the `beq`: before the averaging, and whether or
    # not the averaging happens.
    step = fdiv(delta, ratio)

    wa = a.w
    wb = b.w

    if slow:
        wb = fmul(fadd(wa, wb), HALF)
        wa = wb

    a.w = fadd(wa, step)
    b.w = fadd(wb, step)


def set_differential_angular_velocity(d, w):
    """0x00182d60."""
    delta = fsub(w, get_differential_angular_velocity(d))
    mph = fmul(d.pCarState["VelocityMagnitude"], K_MPS_TO_MPH)
    dti = d.DTI

    if K_SV_REAR <= dti.TorqueSplit:
        share_out(d, delta, 2, 3, dti.FinalDrive[1], mph < K_LOW_SPEED_MPH)

    if dti.TorqueSplit <= K_SV_FRONT:
        share_out(d, delta, 0, 1, dti.FinalDrive[0], mph < K_LOW_SPEED_MPH)


def wheel_acceleration(w):
    return fdiv(fsub(w.AppliedTorque, fmul(w.GroundForce0, w.Radius)),
                w.MomentOfInertia)


def get_differential_angular_acceleration(d):
    """0x00182f48."""
    dti = d.DTI
    acc = ZERO
    rear = K_DA_REAR <= dti.TorqueSplit
    both = 1

    if rear:
        acc = fmul(fmul(fadd(wheel_acceleration(d.pDriveWheel[2]),
                             wheel_acceleration(d.pDriveWheel[3])), HALF),
                   dti.FinalDrive[1])

    if dti.TorqueSplit <= K_DA_FRONT:
        acc = fadd(acc,
                   fmul(fmul(fadd(wheel_acceleration(d.pDriveWheel[0]),
                                  wheel_acceleration(d.pDriveWheel[1])),
                             HALF), dti.FinalDrive[0]))

        if not rear:
            both = 0

        if both:
            acc = fmul(acc, HALF)

    return fmul(acc, dti.GearRatios[d.CurrentGear])


def compute_auxiliaries(d):
    """0x00183100."""
    d.DifferentialAngularVelocity = get_differential_angular_velocity(d)

    e = d.pEngine
    state = d.CurrentClutchState

    if state == CLUTCH_DISENGAGING:
        e.ThrottleOverride = ZERO

        if d.clutch <= e.ThrottleOverride:
            d.CurrentClutchState = CLUTCH_DISENGAGED
            d.clutch = e.ThrottleOverride

    elif state == CLUTCH_DISENGAGED:
        d.CurrentGear = d.DesiredGear
        e.ThrottleOverride = ZERO

        if d.Shifting or K_DISENGAGED_THROTTLE < e.Throttle:
            d.Shifting = 0
            d.CurrentClutchState = CLUTCH_ENGAGING

    elif state == CLUTCH_ENGAGING:
        e.ThrottleOverride = K_ENGAGING_PEDAL

        if ONE <= d.clutch:
            d.clutch = ONE

            if clutch_matched(d) or d.CurrentGear == NEUTRAL:
                d.CurrentClutchState = CLUTCH_ENGAGED

        if idling(d):
            d.CurrentClutchState = CLUTCH_DISENGAGING

    elif state == CLUTCH_ENGAGED:
        e.ThrottleOverride = ONE

        if d.CurrentGear != NEUTRAL:
            slip = fsub(d.DifferentialAngularVelocity, e.w)
            slippage = get_drive_wheel_slippage(d)

            if K_SLIP_THROTTLE < e.Throttle and ZERO < slippage:
                d.DifferentialAngularVelocity = e.w
                set_differential_angular_velocity(d, e.w)
            else:
                e.w = fadd(e.w, fmul(slip, K_ENGINE_PULL))

            if idling(d):
                d.CurrentClutchState = CLUTCH_DISENGAGING

        if d.CurrentGear != d.DesiredGear:
            d.CurrentClutchState = CLUTCH_DISENGAGING
            d.Shifting = 1


def get_derivative(d, out):
    """0x001832f8."""
    out[0] = fmul(d.DTI.ShiftSpeed, f32(CLUTCH_SPEED[d.CurrentClutchState]))
    return 0


def split_torque(d, torque, first, second, name_first):
    """One driven pair, inside ApplyClutchTorque."""
    named = first if name_first else second
    other = second if name_first else first
    threshold = HALF

    if first.TouchingGround and second.TouchingGround:
        threshold = G["LimitedSlip"]

    if d.pCarState["BurnOutState"] == 1:
        share = fsub(ONE, threshold)
    elif d.pCarState["BurnOutState"] == 2:
        share = threshold
    else:
        share = ee_div(named.w, fadd(named.w, other.w))

        if share < threshold:
            share = fsub(ONE, fmul(G["LimitedSlip"], HALF))
        elif fsub(ONE, threshold) < share:
            share = fmul(G["LimitedSlip"], HALF)

    first_share = share if name_first else fsub(ONE, share)
    second_share = fsub(ONE, share) if name_first else share

    if not first.BrakeLocked:
        first.AppliedTorque = fadd(first.AppliedTorque,
                                   fmul(torque, first_share))

    if not second.BrakeLocked:
        second.AppliedTorque = fadd(second.AppliedTorque,
                                    fmul(torque, second_share))


def apply_clutch_torque(d, torque):
    """0x00183328."""
    if d.CurrentGear == NEUTRAL:
        return

    dti = d.DTI

    d.pEngine.RoadTorque = fsub(d.pEngine.RoadTorque, torque)

    geared = fmul(torque, dti.GearRatios[d.CurrentGear])

    split_torque(d, fmul(fmul(geared, fsub(ONE, dti.TorqueSplit)),
                         dti.FinalDrive[0]),
                 d.pDriveWheel[0], d.pDriveWheel[1], 0)
    split_torque(d, fmul(fmul(geared, dti.TorqueSplit), dti.FinalDrive[1]),
                 d.pDriveWheel[2], d.pDriveWheel[3], 1)


def guess_clutch_torque(d):
    """0x001835a8."""
    state = d.CurrentClutchState

    if state == CLUTCH_DISENGAGED:
        return

    if state in (CLUTCH_DISENGAGING, CLUTCH_ENGAGING):
        slip = fsub(d.pEngine.w, d.DifferentialAngularVelocity)

        if G["ClutchLimiter"] < slip:
            slip = G["ClutchLimiter"]
        elif slip < fneg(G["ClutchLimiter"]):
            slip = fneg(G["ClutchLimiter"])

        apply_clutch_torque(d, fmul(fmul(slip, d.DTI.ClutchStiffness),
                                    d.clutch))
        return

    if state == CLUTCH_ENGAGED:
        apply_clutch_torque(d, EN.engine_get_total_engine_torque(d.pEngine))


def modify_clutch_torque(d):
    """0x00183688."""
    if d.CurrentClutchState != CLUTCH_ENGAGED:
        return

    e = d.pEngine

    difference = fdiv(fadd(EN.engine_get_total_engine_torque(e), e.RoadTorque),
                      e.EI.MomentOfInertia)
    difference = fsub(difference, get_differential_angular_acceleration(d))

    inverse = fdiv(ONE, e.EI.MomentOfInertia)

    dti = d.DTI

    if dti.TorqueSplit <= K_MC_FRONT:
        geared = fmul(dti.FinalDrive[0], dti.GearRatios[d.CurrentGear])
        inverse = fadd(inverse,
                       fmul(fmul(fmul(fsub(ONE, dti.TorqueSplit), HALF),
                                 fmul(geared,
                                      fdiv(ONE,
                                           d.pDriveWheel[0].MomentOfInertia))),
                            geared))

    if K_MC_REAR <= dti.TorqueSplit:
        geared = fmul(dti.FinalDrive[1], dti.GearRatios[d.CurrentGear])
        inverse = fadd(inverse,
                       fmul(fmul(fmul(dti.TorqueSplit, HALF),
                                 fmul(geared,
                                      fdiv(ONE,
                                           d.pDriveWheel[2].MomentOfInertia))),
                            geared))

    apply_clutch_torque(d, fdiv(difference, inverse))


def finalize_clutch_torque(d):
    """0x00183830. `jr ra`."""


def idling(d):
    """0x00183838."""
    e = d.pEngine

    if not (e.Throttle < K_IDLE_THROTTLE):
        return 0

    return 1 if (d.DifferentialAngularVelocity
                 <= fadd(fmul(e.EI.IdleRPM, K_RPM_TO_RADS), K_IDLE_SLOP)) else 0


def clutch_matched(d):
    """0x00183888."""
    return 1 if (fabs32(fsub(d.pEngine.w, d.DifferentialAngularVelocity))
                 <= G["ClutchMatchedThreshold"]) else 0


def set_sport_gear(d, g):
    """0x001838c0."""
    if not (g < FIRST_GEAR) and not (d.DTI.NumGears + 1 < g):
        if d.SportGear == NEUTRAL:
            d.GearHoldTime = ZERO

        d.SportGear = g

    return d.SportGear


def set_desired_gear(d, g):
    """0x00183900."""
    if g == AUTOMATIC:
        current = d.CurrentGear
        d.SportGear = NEUTRAL

        if current < FIRST_GEAR:
            d.DesiredGear = FIRST_GEAR
            return g

        if d.CurrentClutchState != CLUTCH_ENGAGED:
            return g

        e = d.pEngine
        rpm = fmul(e.w, K_RADS_TO_RPM_AUTO)

        if current < THIRD_GEAR:
            if e.Throttle < K_CRAWL_THROTTLE_AUTO:
                down = fadd(e.EI.IdleRPM, K_CRAWL_OVER_IDLE)
            else:
                down = ZERO
        else:
            down = d.ShiftDownRPM[current]

        if (d.ShiftUpRPM[current] < rpm
                and current < d.DTI.NumGears + 1
                and d.pDriveWheel[0].CurrentSlip < K_UPSHIFT_SLIP
                and d.pDriveWheel[0].TouchingGround
                and d.pDriveWheel[1].CurrentSlip < K_UPSHIFT_SLIP
                and d.pDriveWheel[1].TouchingGround
                and d.pDriveWheel[2].CurrentSlip < K_UPSHIFT_SLIP
                and d.pDriveWheel[2].TouchingGround
                and d.pDriveWheel[3].CurrentSlip < K_UPSHIFT_SLIP
                and d.pDriveWheel[3].TouchingGround):
            d.DesiredGear = current + 1
            return g

        if rpm < down and not (current < FIRST_GEAR):
            d.DesiredGear = current - 1

        return g

    if g != SPORT_SHIFT:
        d.DesiredGear = g
        return g

    # ---- SPORT_SHIFT

    d.GearHoldTime = fadd(d.GearHoldTime, G["WorldTimeElapsed"])

    if d.CurrentClutchState != CLUTCH_ENGAGED:
        return g

    e = d.pEngine
    current = d.CurrentGear
    rpm = fmul(e.w, K_RADS_TO_RPM_SPORT)

    if current < THIRD_GEAR:
        if e.Throttle < K_CRAWL_THROTTLE_SPORT:
            down = fadd(e.EI.IdleRPM, K_CRAWL_OVER_IDLE)
        else:
            down = ZERO
    else:
        down = fdiv(fmul(fmul(e.EI.MaxRPM, G["MaxDownShiftOver"]),
                         d.DTI.GearRatios[current]),
                    d.DTI.GearRatios[current - 1])

    if d.DesiredGear != d.SportGear:
        d.PreviousGear = current

        if d.SportGear < d.DesiredGear:
            if down < rpm:
                d.DesiredGear = current
                d.GearHoldTime = ZERO
                d.SportGear = current
                return g

            d.GearHoldTime = ZERO
            d.DesiredGear = current - 1
            return g

        if d.DesiredGear < d.SportGear:
            d.GearHoldTime = ZERO
            d.DesiredGear = current + 1
            return g

        # 0x00183b94, unreachable. Kept so that the model and the port
        # have the same shape and a mutation on it can be argued.
        if (rpm < fadd(e.EI.IdleRPM, K_CRAWL_OVER_IDLE)
                and not (current < THIRD_GEAR)):
            d.DesiredGear = current - 1
            return AUTOMATIC

        return g

    if K_SPORT_HOLD < d.GearHoldTime:
        return AUTOMATIC

    if (d.PreviousGear < current
            and fsub(e.EI.MaxRPM, K_LIMITER_MARGIN) < rpm):
        return AUTOMATIC

    return g


# --------------------------------------------------------------- accessors

def rear_wheel_drive(d):
    return 1 if K_RWD <= d.DTI.TorqueSplit else 0


def front_wheel_drive(d):
    return 1 if d.DTI.TorqueSplit <= K_FWD else 0


def get_top_gear(d):
    return d.DTI.NumGears + 1


def is_clutch_engaged(d):
    return 1 if d.CurrentClutchState == CLUTCH_ENGAGED else 0


def set_state_gear(d, g):
    d.DesiredGear = g
    d.clutch = ONE
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.CurrentGear = g


# --------------------------------------------------------------- fixtures

def make_ei():
    """A plausible engine: idle 800, red line 6500, limiter 7000, and a
    torque curve that peaks near 4700 and then falls hard.

    The fall is what makes the crossover search do any work. The test is
    `torque(rpm) < torque(rpm * next / ratio) * next / ratio`, and with
    next/ratio around 0.7 the right-hand side is a third smaller before
    the curve is consulted at all -- so the only way the left side loses
    is for the curve to have dropped a long way between the geared probe
    and the current one. A gently falling curve crosses over in one gear
    out of five and takes the MaxRPM - 200 fallback in the rest, which
    leaves most of the loop untested."""
    return EN.EngineInfo(
        800.0, 6500.0, 7000.0, 0.25,
        [110.0, 168.0, 213.0, 246.0, 268.0, 275.0, 250.0, 195.0, 130.0],
        [0.0, 28.0, 62.0])


def make_dti(split=1.0, gears=6):
    """GearRatios is indexed by the Gear enum: 0 is reverse, 1 is neutral
    and 2..7 are first through sixth."""
    return DriveTrainInfo(0.85, 0.5, [3.1, 3.55], split, 900.0, gears, 2.5,
                          [3.2, 0.0, 2.66, 1.78, 1.3, 1.0, 0.8, 0.63])


RADII = (0.32, 0.33, 0.34, 0.35)
MOMENTS = (0.01, 0.011, 0.012, 0.013)
SPINS = (11.0, 13.0, 17.0, 19.0)


def make_wheels():
    """Four wheels with slightly different radii and inertias, so a pair
    swapped anywhere shows up as a number rather than as nothing.

    Each number is its own decimal literal on both sides. Building them as
    0.32 + 0.01 * i would round twice in C and once here: 0.32f + 0.01f is
    0.329999983, one ulp below f32(0.33). Fixtures are not the thing under
    test, so they are spelled so that the two cannot disagree."""
    return [Wheel(RADII[i], MOMENTS[i]) for i in range(4)]


def make_engine(ei, cs, throttle=0.0, w=0.0):
    e = EN.Engine()
    EN.engine_init(e, ei, cs)
    e.Throttle = f32(throttle)
    e.RoadTorque = ZERO
    e.w = f32(w)
    return e


def make_rig(split=1.0, gears=6, throttle=0.0, w=0.0, speed=0.0,
             burnout=0, driver=0):
    """One car's worth of parts, wired together and constructed."""
    ei = make_ei()
    dti = make_dti(split, gears)
    cs = make_car_state(speed, burnout, driver)
    e = make_engine(ei, cs, throttle, w)
    wheels = make_wheels()
    d = DriveTrain()
    drivetrain_init(d, dti, e, wheels, cs)
    return d, e, wheels, cs, dti, ei


# --------------------------------------------------------------- printing

def print_drivetrain(tag, d):
    pf(tag + " clutch", d.clutch)
    emit("%s gears %s %s %s sport %s" % (tag, gname(d.DesiredGear),
                                         gname(d.CurrentGear),
                                         gname(d.PreviousGear),
                                         gname(d.SportGear)))
    emit("%s clutchstate %s shifting %d" % (tag, cname(d.CurrentClutchState),
                                            d.Shifting))
    pf(tag + " diffw", d.DifferentialAngularVelocity)
    pf(tag + " hold", d.GearHoldTime)
    for i in range(9):
        emit("%s up[%d] %s down[%d] %s" % (tag, i, g9(d.ShiftUpRPM[i]),
                                           i, g9(d.ShiftDownRPM[i])))


def print_wheels(tag, wheels):
    for i, w in enumerate(wheels):
        emit("%s w%d spin %s torque %s slip %s/%s ground %d locked %d"
             % (tag, i, g9(w.w), g9(w.AppliedTorque), g9(w.CurrentSlip),
                g9(w.OldSlip), w.TouchingGround, w.BrakeLocked))


def print_engine(tag, e):
    emit("%s engine w %s throttle %s road %s over %s"
         % (tag, g9(e.w), g9(e.Throttle), g9(e.RoadTorque),
            g9(e.ThrottleOverride)))


def dump_globals(tag):
    pf(tag + " EngineBrakingFactor", G["EngineBrakingFactor"])
    pf(tag + " ShiftUpDetune", G["ShiftUpDetune"])
    pf(tag + " ShiftDownDetune", G["ShiftDownDetune"])
    pint(tag + " GearShiftMethod", G["GearShiftMethod"])
    pf(tag + " LimitedSlip", G["LimitedSlip"])
    pf(tag + " ClutchLimiter", G["ClutchLimiter"])
    pf(tag + " ClutchMatchedThreshold", G["ClutchMatchedThreshold"])
    pf(tag + " MaxDownShiftOver", G["MaxDownShiftOver"])
    pf(tag + " WorldTimeElapsed", G["WorldTimeElapsed"])


# --------------------------------------------------------------- scenarios

def s_layout():
    """The record as both toolchains see it, from PS2 offsets widened by
    one SLACK per pointer passed."""
    emit("sizeof DriveTrainState 4")
    emit("sizeof DriveTrain %d" % (148 + 7 * SLACK))

    for name, ps2, n in [("State", 12, 0), ("DTI", 16, 0), ("pEngine", 20, 1),
                         ("pDriveWheel", 24, 2), ("pCarState", 40, 6),
                         ("DesiredGear", 44, 7), ("CurrentGear", 48, 7),
                         ("PreviousGear", 52, 7),
                         ("CurrentClutchState", 56, 7), ("Shifting", 60, 7),
                         ("DifferentialAngularVelocity", 64, 7),
                         ("GearHoldTime", 68, 7), ("SportGear", 72, 7),
                         ("ShiftUpRPM", 76, 7), ("ShiftDownRPM", 112, 7)]:
        emit("off %s %d" % (pad(name, 28), ps2 + n * SLACK))

    emit("vtable 0x%08x" % DRIVETRAIN_VTABLE)

    dump_globals("image")

    for i in range(4):
        pf("ClutchSpeed[%d]" % i, f32(CLUTCH_SPEED[i]))

    pf("rpm to rads", f32(K_RPM_TO_RADS))
    pf("rads to rpm", f32(K_RADS_TO_RPM_AUTO))

    # The two words are each other's float reciprocal exactly, so this
    # prints 1. What it pins down is not the round trip but the pair: the
    # correctly rounded floats of 2pi/60 and 60/2pi are 0x3dd67750 and
    # 0x4118c9eb, and the image has 0x3dd67745 and 0x4118c9f3. A port that
    # wrote the textbook constants would still print 1 here -- but the
    # `id`, `au` and `ss` scenarios, which convert real engine speeds,
    # would move.
    pf("rpm roundtrip", fmul(f32(K_RPM_TO_RADS), f32(K_RADS_TO_RPM_AUTO)))


def check_pool():
    """The sixteen split thresholds and the four throttle limits are
    pooled once per use site, not once per value. drivetrain.c collapses
    each family into a single macro, and that collapse is only sound
    because every slot in the family holds the same word.

    This is checked rather than transcribed: the pool slots live in
    drivetrain.c's own macros, which the harness cannot see, so they
    cannot appear in the transcript. What the transcript checks instead is
    the *behaviour* each constant drives -- the `dv edge` scenario
    straddles 0.001 and 0.999 on both sides of both tests, `sv mph`
    straddles the mph conversion, and the `ca` and `au` scenarios straddle
    every throttle limit. A wrong macro moves one of those lines.

    What this function adds is the claim the transcript cannot make: that
    the image really does hold one value per family, so collapsing them is
    not hiding a difference."""
    low = [("dv_rear", K_DV_REAR), ("ds_rear", K_DS_REAR),
           ("sv_rear", K_SV_REAR), ("da_rear", K_DA_REAR),
           ("mc_rear", K_MC_REAR), ("rwd", K_RWD)]
    high = [("dv_front", K_DV_FRONT), ("ds_front", K_DS_FRONT),
            ("sv_front", K_SV_FRONT), ("da_front", K_DA_FRONT),
            ("mc_front", K_MC_FRONT), ("fwd", K_FWD)]
    throttle = [("slip", K_SLIP_THROTTLE),
                ("crawl_auto", K_CRAWL_THROTTLE_AUTO),
                ("crawl_sport", K_CRAWL_THROTTLE_SPORT)]
    idle = [("disengaged", K_DISENGAGED_THROTTLE),
            ("idling", K_IDLE_THROTTLE)]
    rads = [("auto", K_RADS_TO_RPM_AUTO), ("sport", K_RADS_TO_RPM_SPORT)]

    for family in (low, high, throttle, idle, rads):
        first = family[0]
        for name, value in family[1:]:
            if value != first[1]:
                raise SystemExit(
                    "pool slot %s is %.9g but %s is %.9g: drivetrain.c's "
                    "single macro for the family is wrong"
                    % (name, value, first[0], first[1]))


def shift_points_dump(tag, dti, ei, scale, lo, hi):
    up = [f32(-1.0)] * 9
    down = [f32(-1.0)] * 9

    calculate_shift_points(dti, ei, up, down, scale)

    if tag:
        emit(tag)

    for i in range(lo, hi):
        emit("sp up[%d] %s down[%d] %s" % (i, g9(up[i]), i, g9(down[i])))


def s_shift_points():
    """CalculateShiftPoints: the crossover arm, the fallback, the loop that
    never starts, and the interpolated arm."""
    reset_globals()
    ei = make_ei()

    for gears in (3, 6):
        dti = make_dti(1.0, gears)
        shift_points_dump("sp gears %d" % gears, dti, ei,
                          G["ShiftUpDetune"], 0, 9)

    # A scale that is not 1 and not the shipped detune, so the two arms
    # that join before the multiply are told apart from the one that does
    # not.
    dti = make_dti(1.0, 6)
    shift_points_dump("sp scaled", dti, ei, f32(0.5), 2, 8)

    # A flat torque curve never crosses over, so every gear takes the
    # MaxRPM - 200 fallback -- and the fallback is scaled.
    alt = EN.EngineInfo(800.0, 6500.0, 7000.0, 0.25, [200.0] * 9,
                        [0.0, 28.0, 62.0])
    shift_points_dump("sp fallback", dti, alt, f32(0.5), 2, 8)

    # (idle + max) / 2 is already past max - 200, so the search loop does
    # not run at all and `searching` is still the 1 the delay slot set.
    alt.IdleRPM = f32(6900.0)
    alt.RedLineRPM = f32(6950.0)
    shift_points_dump("sp noloop", dti, alt, f32(0.5), 2, 8)

    # The same narrow band with a falling curve. Here a do/while would
    # find a crossover on its first probe -- the geared argument clamps to
    # the top of the curve, where the torque is three times what it is at
    # the probe -- and write 6950, where the entry test writes the 6800
    # fallback. This is the fixture that tells the two loop shapes apart;
    # without it, replacing the entry test with `if (1)` is invisible.
    alt.TorqueCurveTable = [f32(x) for x in
                            (300.0, 260.0, 220.0, 170.0, 100.0, 80.0, 70.0,
                             65.0, 60.0)]
    shift_points_dump("sp noloop2", dti, alt, f32(0.5), 2, 8)

    # A curve that falls hard from idle, so every gear crosses over on the
    # search's very first probe. That is what pins the midpoint: the loop
    # starts at (idle + MaxRPM) / 2 = 3900 and writes it, where a loop
    # starting at (idle + RedLineRPM) / 2 = 3650 would write that instead.
    # Every other fixture here crosses over well above both, on the same
    # 50 RPM grid, so the two starts converge and the choice is invisible.
    steep = EN.EngineInfo(800.0, 6500.0, 7000.0, 0.25,
                          [400.0, 300.0, 200.0, 120.0, 70.0, 40.0, 25.0,
                           15.0, 10.0],
                          [0.0, 28.0, 62.0])
    shift_points_dump("sp steep", dti, steep, f32(0.5), 2, 8)

    # A curve that is zero everywhere. `here` and `there` are then both
    # exactly 0 at every probe, which is the one fixture that can tell
    # `here < there` from `here <= there`: the strict test never fires and
    # takes the 6800 fallback, the loose one fires on the first probe and
    # writes 3900. A flat non-zero curve cannot do this -- `there` is
    # scaled by next/ratio < 1, so it comes out strictly smaller.
    flat0 = EN.EngineInfo(800.0, 6500.0, 7000.0, 0.25, [0.0] * 9,
                          [0.0, 28.0, 62.0])
    shift_points_dump("sp zerocurve", dti, flat0, f32(0.5), 2, 8)

    # The dead arm. gGearShiftMethod is 1 in the image.
    G["GearShiftMethod"] = 0
    shift_points_dump("sp interpolated", dti, ei, f32(0.5), 2, 8)
    reset_globals()

    # NumGears 1 makes last 2, so the loop body never runs and only the
    # top-gear store happens.
    shift_points_dump("sp onegear", make_dti(1.0, 1), ei, f32(0.5), 0, 4)


def s_ctor():
    """What the constructor writes, and the four fields it does not."""
    reset_globals()
    d, e, wheels, cs, dti, ei = make_rig()
    emit("ct vtable 0x%08x" % d.vtable)
    print_drivetrain("ct", d)
    emit("ct wired %d %d %d"
         % (1 if d.DTI is dti else 0, 1 if d.pEngine is e else 0,
            1 if d.pCarState is cs else 0))
    for i in range(4):
        emit("ct wheel%d %d" % (i, 1 if d.pDriveWheel[i] is wheels[i] else 0))

    # The four fields the constructor does not write, poisoned first. A
    # record that arrives zeroed cannot tell "left alone" from "set to
    # zero", so every one of these carries a value the constructor would
    # have to go out of its way to produce.
    poisoned = DriveTrain()
    poisoned.PreviousGear = SEVENTH_GEAR
    poisoned.DifferentialAngularVelocity = f32(12.5)
    poisoned.GearHoldTime = f32(3.25)
    poisoned.SportGear = FOURTH_GEAR
    drivetrain_init(poisoned, dti, e, wheels, cs)
    emit("ct keeps prev %s sport %s" % (gname(poisoned.PreviousGear),
                                        gname(poisoned.SportGear)))
    pf("ct keeps diffw", poisoned.DifferentialAngularVelocity)
    pf("ct keeps hold", poisoned.GearHoldTime)

    # The constructor hands gShiftUpDetune to CalculateShiftPoints as the
    # scale; CalculateShiftPoints reaches for gShiftDownDetune itself when
    # it builds the down points. The image ships both at 0.95, so only a
    # run with them apart says which global reaches which multiply.
    G["ShiftUpDetune"] = f32(0.8)
    G["ShiftDownDetune"] = f32(0.6)
    det, _, _, _, _, _ = make_rig()
    for i in range(9):
        emit("ct detune up[%d] %s down[%d] %s"
             % (i, g9(det.ShiftUpRPM[i]), i, g9(det.ShiftDownRPM[i])))
    reset_globals()


def s_differential_velocity():
    """The three drive layouts, and the halving that only one arm reaches."""
    reset_globals()
    for tag, split in (("rwd", 1.0), ("fwd", 0.0), ("awd", 0.5)):
        d, e, wheels, cs, dti, ei = make_rig(split)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
        for g in (REVERSE, NEUTRAL, FIRST_GEAR, FOURTH_GEAR, SIXTH_GEAR):
            d.CurrentGear = g
            pf("dv %s %s" % (tag, gname(g)),
               get_differential_angular_velocity(d))
        emit("dv %s rwd %d fwd %d top %s"
             % (tag, rear_wheel_drive(d), front_wheel_drive(d),
                gname(get_top_gear(d))))

    # Exactly on both thresholds. 0.001 passes the rear test and also the
    # front one, so both arms run and the result halves.
    for split in (0.001, 0.999, 0.0009999, 0.9991):
        d, e, wheels, cs, dti, ei = make_rig(split)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
        d.CurrentGear = FIRST_GEAR
        emit("dv edge %s rwd %d fwd %d value %s"
             % (g9(f32(split)), rear_wheel_drive(d), front_wheel_drive(d),
                g9(get_differential_angular_velocity(d))))


def s_slippage():
    """The one that halves unconditionally."""
    reset_globals()
    for tag, split in (("rwd", 1.0), ("fwd", 0.0), ("awd", 0.5)):
        d, e, wheels, cs, dti, ei = make_rig(split)
        for i, slip in enumerate((0.25, 0.75, 1.25, 1.75)):
            wheels[i].OldSlip = f32(slip)
        pf("ds %s" % tag, get_drive_wheel_slippage(d))

    # Front-drive with both front wheels at exactly 1.0: the answer is
    # 0.5, which is the halving nobody asked for.
    d, e, wheels, cs, dti, ei = make_rig(0.0)
    wheels[0].OldSlip = ONE
    wheels[1].OldSlip = ONE
    pf("ds fwd unit", get_drive_wheel_slippage(d))


def s_set_differential():
    """SetDifferentialAngularVelocity: fast, slow, and wheels up."""
    reset_globals()
    for tag, split, speed in (("rwd fast", 1.0, 30.0), ("rwd slow", 1.0, 5.0),
                              ("fwd fast", 0.0, 30.0), ("awd fast", 0.5, 30.0),
                              ("awd slow", 0.5, 5.0)):
        d, e, wheels, cs, dti, ei = make_rig(split, speed=speed)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        pf("sv %s before" % tag, get_differential_angular_velocity(d))
        set_differential_angular_velocity(d, f32(120.0))
        print_wheels("sv " + tag, wheels)
        pf("sv %s after" % tag, get_differential_angular_velocity(d))

    # The low-speed test is `<`, so the borderline speed is not slow. The
    # speed itself is derived the same way on both sides -- one float
    # divide of 40 by the mph factor -- so the two agree about it whether
    # or not it multiplies back to exactly 40.
    for t, nudge in enumerate((0.999, 1.0, 1.001)):
        speed = fmul(fdiv(f32(40.0), f32(K_MPS_TO_MPH)), f32(nudge))
        d, e, wheels, cs, dti, ei = make_rig(1.0, speed=speed)
        for i in range(4):
            wheels[i].w = f32(SPINS[i])
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        set_differential_angular_velocity(d, f32(120.0))
        emit("sv mph%d %s w2 %s w3 %s"
             % (t, g9(fmul(speed, f32(K_MPS_TO_MPH))), g9(wheels[2].w),
                g9(wheels[3].w)))

    # Both rear wheels off the ground at speed averages them anyway; one
    # off does not.
    for lifted in ((), (2,), (2, 3)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, speed=30.0)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 0 if i in lifted else 1
        d.CurrentGear = THIRD_GEAR
        set_differential_angular_velocity(d, f32(120.0))
        emit("sv lifted%d w2 %s w3 %s"
             % (len(lifted), g9(wheels[2].w), g9(wheels[3].w)))


def s_differential_acceleration():
    reset_globals()
    for tag, split in (("rwd", 1.0), ("fwd", 0.0), ("awd", 0.5)):
        d, e, wheels, cs, dti, ei = make_rig(split)
        for i in range(4):
            wheels[i].AppliedTorque = f32(120.0 + 30.0 * i)
            wheels[i].GroundForce0 = f32(200.0 - 40.0 * i)
        d.CurrentGear = THIRD_GEAR
        pf("da %s" % tag, get_differential_angular_acceleration(d))

    # Gear by gear, so the ratio index is pinned.
    d, e, wheels, cs, dti, ei = make_rig(0.5)
    for i in range(4):
        wheels[i].AppliedTorque = f32(120.0 + 30.0 * i)
        wheels[i].GroundForce0 = f32(200.0 - 40.0 * i)
    for g in (REVERSE, NEUTRAL, FIRST_GEAR, SIXTH_GEAR):
        d.CurrentGear = g
        pf("da awd %s" % gname(g), get_differential_angular_acceleration(d))


def s_derivative():
    """ClutchSpeed, indexed by the state machine."""
    reset_globals()
    d, e, wheels, cs, dti, ei = make_rig()
    out = [f32(-1.0)]
    for state in range(4):
        d.CurrentClutchState = state
        r = get_derivative(d, out)
        emit("gd %s %s ret %d" % (cname(state), g9(out[0]), r))
    emit("gd size 1")

    # ShiftSpeed scales it, so a port that dropped the multiply shows up.
    dti.ShiftSpeed = f32(0.4)
    for state in range(4):
        d.CurrentClutchState = state
        get_derivative(d, out)
        pf("gd slow %s" % cname(state), out[0])


def s_idling_matched():
    """Two predicates, swept across their thresholds."""
    reset_globals()
    d, e, wheels, cs, dti, ei = make_rig()
    idle_rads = fadd(fmul(ei.IdleRPM, K_RPM_TO_RADS), K_IDLE_SLOP)

    for throttle in (0.0, 0.29, 0.3, 0.31, 1.0):
        e.Throttle = f32(throttle)
        for delta in (-1.0, 0.0, 1e-5, 1.0):
            d.DifferentialAngularVelocity = fadd(idle_rads, f32(delta))
            emit("id t %s d %s -> %d" % (g9(f32(throttle)), g9(f32(delta)),
                                         idling(d)))

    d.DifferentialAngularVelocity = f32(100.0)
    for w in (49.0, 50.0, 51.0, 100.0, 149.0, 150.0, 151.0):
        e.w = f32(w)
        emit("cm w %s -> %d" % (g9(f32(w)), clutch_matched(d)))

    # The threshold is a global, so move it.
    G["ClutchMatchedThreshold"] = f32(5.0)
    for w in (94.0, 95.0, 96.0):
        e.w = f32(w)
        emit("cm tight w %s -> %d" % (g9(f32(w)), clutch_matched(d)))
    reset_globals()


def s_apply_clutch_torque():
    """The differential split, both clamps, the open band, burnout and the
    neutral early-out."""
    reset_globals()

    # Walk the rear pair's spin share from 0 to 1 in percent, so the two
    # clamps and the open band between them appear in order. The share
    # itself is w2 / (w2 + w3); the label is the numerator, because a
    # ratio computed on one side in double and on the other in float is a
    # fixture disagreeing with itself.
    for num in (0.0, 20.0, 34.0, 35.0, 36.0, 50.0, 64.0, 65.0, 66.0, 100.0):
        d, e, wheels, cs, dti, ei = make_rig(1.0)
        # The front pair is spun too even though this is a rear-drive car:
        # ApplyClutchTorque splits *both* pairs whatever TorqueSplit says,
        # so two stationary front rims would divide zero by zero. That is
        # `ac still`'s subject, not this one's.
        for i in range(4):
            wheels[i].w = f32(SPINS[i])
        wheels[2].w = f32(num)
        wheels[3].w = fsub(f32(100.0), f32(num))
        for w in wheels:
            w.TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        apply_clutch_torque(d, f32(400.0))
        emit("ac share %s w2 %s w3 %s road %s"
             % (g9(f32(num)), g9(wheels[2].AppliedTorque),
                g9(wheels[3].AppliedTorque), g9(e.RoadTorque)))

    # Airborne widens the threshold to 0.5, which leaves no open band at
    # all: every share is clamped one way or the other.
    for num in (10.0, 49.0, 50.0, 51.0, 90.0):
        d, e, wheels, cs, dti, ei = make_rig(1.0)
        for i in range(4):
            wheels[i].w = f32(SPINS[i])
        wheels[2].w = f32(num)
        wheels[3].w = fsub(f32(100.0), f32(num))
        wheels[2].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        apply_clutch_torque(d, f32(400.0))
        emit("ac air %s w2 %s w3 %s"
             % (g9(f32(num)), g9(wheels[2].AppliedTorque),
                g9(wheels[3].AppliedTorque)))

    # Burnout, all four wheels, both values. This is the diagonal.
    for burnout in (0, 1, 2):
        d, e, wheels, cs, dti, ei = make_rig(0.5, burnout=burnout)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        apply_clutch_torque(d, f32(400.0))
        emit("ac burn%d %s %s %s %s"
             % (burnout, g9(wheels[0].AppliedTorque),
                g9(wheels[1].AppliedTorque), g9(wheels[2].AppliedTorque),
                g9(wheels[3].AppliedTorque)))

    # A locked wheel takes nothing and the other one still takes its own
    # share -- the split is not redistributed.
    for locked in (0, 1, 2, 3):
        d, e, wheels, cs, dti, ei = make_rig(0.5)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        wheels[locked].BrakeLocked = 1
        d.CurrentGear = THIRD_GEAR
        apply_clutch_torque(d, f32(400.0))
        emit("ac locked%d %s %s %s %s"
             % (locked, g9(wheels[0].AppliedTorque),
                g9(wheels[1].AppliedTorque), g9(wheels[2].AppliedTorque),
                g9(wheels[3].AppliedTorque)))

    # NEUTRAL returns before RoadTorque is touched.
    d, e, wheels, cs, dti, ei = make_rig(0.5)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].TouchingGround = 1
    e.RoadTorque = f32(77.0)
    d.CurrentGear = NEUTRAL
    apply_clutch_torque(d, f32(400.0))
    emit("ac neutral road %s torques %s %s %s %s"
         % (g9(e.RoadTorque), g9(wheels[0].AppliedTorque),
            g9(wheels[1].AppliedTorque), g9(wheels[2].AppliedTorque),
            g9(wheels[3].AppliedTorque)))

    # LIMITEDSLIP is one global doing two jobs: moving it moves both the
    # threshold and the clamped value.
    G["LimitedSlip"] = f32(0.2)
    d, e, wheels, cs, dti, ei = make_rig(1.0)
    for i in range(4):
        wheels[i].w = f32(SPINS[i])
    wheels[2].w = f32(10.0)
    wheels[3].w = f32(90.0)
    for w in wheels:
        w.TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    apply_clutch_torque(d, f32(400.0))
    emit("ac tightslip w2 %s w3 %s"
         % (g9(wheels[2].AppliedTorque), g9(wheels[3].AppliedTorque)))
    reset_globals()

    # A pair standing still. +0 + -0 is +0, so the mixed pairs differ only
    # in the numerator's sign: -0 over +0 is -FLT_MAX and hands the named
    # wheel the large share. The last two are an exact zero sum from
    # nonzero spins. The rear-drive rig runs with its front pair stopped,
    # the case the game hits on the grid.
    for w2, w3 in ((0.0, 0.0), (-0.0, -0.0), (0.0, -0.0), (-0.0, 0.0),
                   (5.0, -5.0), (-5.0, 5.0)):
        d, e, wheels, cs, dti, ei = make_rig(1.0)
        wheels[2].w = f32(w2)
        wheels[3].w = f32(w3)
        for w in wheels:
            w.TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        apply_clutch_torque(d, f32(400.0))
        emit("ac still %s %s -> %s %s %s %s"
             % (g9(f32(w2)), g9(f32(w3)), g9(wheels[0].AppliedTorque),
                g9(wheels[1].AppliedTorque), g9(wheels[2].AppliedTorque),
                g9(wheels[3].AppliedTorque)))


def s_guess_clutch_torque():
    """All four states, and the +-ClutchLimiter clamp."""
    reset_globals()
    for state in range(4):
        for slip in (-500.0, -300.0, -50.0, 0.0, 50.0, 300.0, 500.0):
            d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6)
            for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
                wheels[i].w = f32(spin)
                wheels[i].TouchingGround = 1
            d.CurrentGear = THIRD_GEAR
            d.CurrentClutchState = state
            d.clutch = f32(0.75)
            d.DifferentialAngularVelocity = f32(200.0)
            e.w = fadd(f32(200.0), f32(slip))
            guess_clutch_torque(d)
            emit("gc %s slip %s road %s w2 %s"
                 % (cname(state), g9(f32(slip)), g9(e.RoadTorque),
                    g9(wheels[2].AppliedTorque)))

    # The clutch scales the two moving states, so a half-in clutch carries
    # half the torque.
    for clutch in (0.0, 0.5, 1.0):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGING
        d.clutch = f32(clutch)
        d.DifferentialAngularVelocity = f32(200.0)
        e.w = f32(280.0)
        guess_clutch_torque(d)
        emit("gc clutch %s road %s" % (g9(f32(clutch)), g9(e.RoadTorque)))

    # DISENGAGED returns before it can apply anything, and the way to see
    # that is a negative zero. ApplyClutchTorque(0) is not a no-op: every
    # wheel gets `AppliedTorque + 0 * share`, and -0 + 0 is +0 in IEEE
    # 754. So a record whose torques start at -0 comes back printing "-0"
    # if the arm returned and "0" if it went through ApplyClutchTorque.
    # Every other observable -- RoadTorque, the gear, the states -- is
    # unchanged by a zero torque, which is why this one arm had nothing
    # holding it.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].TouchingGround = 1
        wheels[i].AppliedTorque = fneg(ZERO)
    d.CurrentGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_DISENGAGED
    d.clutch = f32(0.75)
    d.DifferentialAngularVelocity = f32(200.0)
    e.w = f32(500.0)
    e.RoadTorque = fneg(ZERO)
    guess_clutch_torque(d)
    emit("gc disengaged road %s" % g9(e.RoadTorque))
    print_wheels("gc disengaged", wheels)


def s_modify_clutch_torque():
    reset_globals()
    for tag, split in (("rwd", 1.0), ("fwd", 0.0), ("awd", 0.5)):
        for state in (CLUTCH_ENGAGING, CLUTCH_ENGAGED):
            d, e, wheels, cs, dti, ei = make_rig(split, throttle=0.8, w=400.0)
            for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
                wheels[i].w = f32(spin)
                wheels[i].AppliedTorque = f32(120.0 + 30.0 * i)
                wheels[i].GroundForce0 = f32(200.0 - 40.0 * i)
                wheels[i].TouchingGround = 1
            d.CurrentGear = THIRD_GEAR
            d.CurrentClutchState = state
            e.RoadTorque = f32(-60.0)
            modify_clutch_torque(d)
            emit("mc %s %s road %s torques %s %s %s %s"
                 % (tag, cname(state), g9(e.RoadTorque),
                    g9(wheels[0].AppliedTorque), g9(wheels[1].AppliedTorque),
                    g9(wheels[2].AppliedTorque), g9(wheels[3].AppliedTorque)))

    # Only pDriveWheel[0] and pDriveWheel[2] feed the inertia sum: moving
    # the odd wheels' inertia must not change the answer.
    for odd in (0.001, 0.5):
        d, e, wheels, cs, dti, ei = make_rig(0.5, throttle=0.8, w=400.0)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].AppliedTorque = f32(120.0 + 30.0 * i)
            wheels[i].GroundForce0 = f32(200.0 - 40.0 * i)
            wheels[i].TouchingGround = 1
        wheels[1].MomentOfInertia = f32(odd)
        wheels[3].MomentOfInertia = f32(odd)
        d.CurrentGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        modify_clutch_torque(d)
        emit("mc oddmoi %s road %s" % (g9(f32(odd)), g9(e.RoadTorque)))


def s_compute_auxiliaries():
    """The state machine, one arm at a time."""
    reset_globals()

    # DISENGAGING: falls out until the clutch reaches zero.
    for clutch in (1.0, 0.5, 0.0, -0.25):
        d, e, wheels, cs, dti, ei = make_rig(1.0)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_DISENGAGING
        d.clutch = f32(clutch)
        compute_auxiliaries(d)
        emit("ca out %s -> %s clutch %s over %s"
             % (g9(f32(clutch)), cname(d.CurrentClutchState), g9(d.clutch),
                g9(e.ThrottleOverride)))

    # DISENGAGED: the gear changes here, and the throttle or the shifting
    # flag brings the clutch back.
    for shifting, throttle in ((0, 0.0), (0, 0.3), (0, 0.31), (1, 0.0)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=throttle)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = THIRD_GEAR
        d.DesiredGear = FOURTH_GEAR
        d.CurrentClutchState = CLUTCH_DISENGAGED
        d.Shifting = shifting
        compute_auxiliaries(d)
        emit("ca in shift %d t %s -> %s gear %s shifting %d"
             % (shifting, g9(f32(throttle)), cname(d.CurrentClutchState),
                gname(d.CurrentGear), d.Shifting))

    # ENGAGING: the clutch arrives, the match test and the neutral escape.
    for clutch, engw, gear in ((0.5, 200.0, THIRD_GEAR),
                               (1.0, 200.0, THIRD_GEAR),
                               (1.0, 1000.0, THIRD_GEAR),
                               (1.0, 1000.0, NEUTRAL),
                               # Past 1. At exactly 1 the clamp writes the
                               # value that is already there and cannot be
                               # seen; the integrator does overshoot, so
                               # this is the case that matters.
                               (1.5, 1000.0, THIRD_GEAR)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=engw)
        for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
            wheels[i].w = f32(spin)
            wheels[i].TouchingGround = 1
        d.CurrentGear = gear
        d.DesiredGear = gear
        d.CurrentClutchState = CLUTCH_ENGAGING
        d.clutch = f32(clutch)
        compute_auxiliaries(d)
        emit("ca engaging c %s w %s %s -> %s clutch %s over %s"
             % (g9(f32(clutch)), g9(f32(engw)), gname(gear),
                cname(d.CurrentClutchState), g9(d.clutch),
                g9(e.ThrottleOverride)))

    # ENGAGING with the throttle shut and the wheels stopped, which is
    # what Idling asks for. The arm's last two instructions hand the
    # clutch straight back to DISENGAGING, and every other ENGAGING
    # fixture here is at 0.6 of throttle, where Idling is false before it
    # looks at the wheels.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.0, w=60.0)
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGING
    d.clutch = f32(0.5)
    compute_auxiliaries(d)
    emit("ca engaging idle -> %s clutch %s diffw %s idling %d"
         % (cname(d.CurrentClutchState), g9(d.clutch),
            g9(d.DifferentialAngularVelocity), idling(d)))

    # ENGAGED, no wheelspin: the engine is dragged 4% towards the
    # drivetrain.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=300.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.clutch = ONE
    compute_auxiliaries(d)
    emit("ca engaged drag -> %s" % cname(d.CurrentClutchState))
    print_engine("ca engaged drag", e)
    pf("ca engaged drag diffw", d.DifferentialAngularVelocity)

    # ENGAGED with wheelspin: the whole drivetrain is snapped to the
    # engine instead.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=300.0,
                                         speed=30.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].OldSlip = f32(0.5)
        wheels[i].TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.clutch = ONE
    compute_auxiliaries(d)
    emit("ca engaged spin -> %s" % cname(d.CurrentClutchState))
    print_engine("ca engaged spin", e)
    pf("ca engaged spin diffw", d.DifferentialAngularVelocity)
    print_wheels("ca engaged spin", wheels)

    # ENGAGED in NEUTRAL: ThrottleOverride is still written, and nothing
    # else in the arm runs.
    #
    # The pedal starts at 0.25 rather than where the constructor left it.
    # Engine::Engine writes 1.0, which is exactly what this arm writes, so
    # against a fresh engine the store is invisible and a mutant that
    # skips it in NEUTRAL survives.
    #
    # The wheels and the cached differential speed are printed because
    # that is where "nothing else runs" shows: the block this arm skips
    # writes those two and does not touch the engine's own speed on the
    # wheelspin path.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=300.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].OldSlip = f32(0.5)
        wheels[i].TouchingGround = 1
    d.CurrentGear = NEUTRAL
    d.DesiredGear = NEUTRAL
    d.CurrentClutchState = CLUTCH_ENGAGED
    e.ThrottleOverride = f32(0.25)
    compute_auxiliaries(d)
    print_engine("ca engaged neutral", e)
    pf("ca engaged neutral diffw", d.DifferentialAngularVelocity)
    print_wheels("ca engaged neutral", wheels)
    emit("ca engaged neutral -> %s" % cname(d.CurrentClutchState))

    # NEUTRAL with a shift pending. The gear test at the foot of the arm
    # sits outside the NEUTRAL guard, so this one disengages and sets
    # Shifting even though the physics above it was skipped.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=300.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].OldSlip = f32(0.5)
        wheels[i].TouchingGround = 1
    d.CurrentGear = NEUTRAL
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    e.ThrottleOverride = f32(0.25)
    compute_auxiliaries(d)
    print_engine("ca neutral shift", e)
    pf("ca neutral shift diffw", d.DifferentialAngularVelocity)
    print_wheels("ca neutral shift", wheels)
    emit("ca neutral shift -> %s shifting %d"
         % (cname(d.CurrentClutchState), d.Shifting))

    # ENGAGED with a shift pending.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.6, w=300.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
        wheels[i].TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = FOURTH_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    compute_auxiliaries(d)
    emit("ca engaged shift -> %s shifting %d"
         % (cname(d.CurrentClutchState), d.Shifting))

    # A clutch state the enum does not have falls through untouched.
    d, e, wheels, cs, dti, ei = make_rig(1.0)
    for i, spin in enumerate((11.0, 13.0, 17.0, 19.0)):
        wheels[i].w = f32(spin)
    d.CurrentGear = THIRD_GEAR
    d.CurrentClutchState = -1
    e.ThrottleOverride = f32(0.125)
    compute_auxiliaries(d)
    emit("ca bogus -> %d over %s diffw %s"
         % (d.CurrentClutchState, g9(e.ThrottleOverride),
            g9(d.DifferentialAngularVelocity)))


def s_sport_gear():
    """SetSportGear's range test and the neutral hold reset."""
    reset_globals()
    d, e, wheels, cs, dti, ei = make_rig(1.0, gears=6)
    for g in (-2, -1, 0, 1, 2, 3, 6, 7, 8, 9):
        d.SportGear = NEUTRAL
        d.GearHoldTime = f32(3.5)
        r = set_sport_gear(d, g)
        emit("sg ask %s -> %s hold %s"
             % (gname(g), gname(r), g9(d.GearHoldTime)))

    # Out of a gear that is not neutral, the hold time is left alone.
    d.SportGear = THIRD_GEAR
    d.GearHoldTime = f32(3.5)
    r = set_sport_gear(d, FOURTH_GEAR)
    emit("sg from3rd -> %s hold %s" % (gname(r), g9(d.GearHoldTime)))


def s_automatic():
    """SetDesiredGear in AUTOMATIC."""
    reset_globals()

    # Reverse and neutral both ask for first, whatever else is true.
    #
    # DesiredGear starts at fifth, not at the first the constructor left
    # there: the arm's whole effect is the store of FIRST_GEAR, and
    # against a record that already holds FIRST_GEAR the store cannot be
    # seen. Neutral is the gear that matters -- `current < FIRST_GEAR` and
    # `current < NEUTRAL` differ on exactly that one value.
    for g in (REVERSE, NEUTRAL):
        d, e, wheels, cs, dti, ei = make_rig(1.0, w=700.0)
        d.CurrentGear = g
        d.DesiredGear = FIFTH_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        r = set_desired_gear(d, AUTOMATIC)
        emit("au from %s -> %s desired %s sport %s"
             % (gname(g), gname(r), gname(d.DesiredGear), gname(d.SportGear)))

    # Not engaged: nothing happens but the SportGear reset.
    #
    # The wheels are on the ground and the engine is over third's up
    # point, so this is a frame that would upshift if the clutch test let
    # it through. Without that, the early return has nothing to prevent
    # and deleting it changes nothing.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=700.0)
    for w in wheels:
        w.TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGING
    set_desired_gear(d, AUTOMATIC)
    emit("au notengaged desired %s sport %s (rpm %s up %s)"
         % (gname(d.DesiredGear), gname(d.SportGear),
            g9(fmul(e.w, K_RADS_TO_RPM_AUTO)),
            g9(d.ShiftUpRPM[THIRD_GEAR])))

    # An upshift needs all four wheels down and under 4 of slip.
    for tag, fix in (("clean", lambda w: None),
                     ("slip0", lambda w: w[0].__setattr__("CurrentSlip",
                                                          f32(4.0))),
                     ("slip3", lambda w: w[3].__setattr__("CurrentSlip",
                                                          f32(9.0))),
                     ("air1", lambda w: w[1].__setattr__("TouchingGround",
                                                         0)),
                     ("air2", lambda w: w[2].__setattr__("TouchingGround",
                                                         0))):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=700.0)
        for w in wheels:
            w.TouchingGround = 1
        fix(wheels)
        d.CurrentGear = THIRD_GEAR
        d.DesiredGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        set_desired_gear(d, AUTOMATIC)
        emit("au up %s desired %s (rpm %s over %s)"
             % (tag, gname(d.DesiredGear),
                g9(fmul(e.w, K_RADS_TO_RPM_AUTO)),
                g9(d.ShiftUpRPM[THIRD_GEAR])))

    # Top gear cannot shift up even at the limiter.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=760.0)
    for w in wheels:
        w.TouchingGround = 1
    d.CurrentGear = SIXTH_GEAR
    d.DesiredGear = SIXTH_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    set_desired_gear(d, AUTOMATIC)
    emit("au top desired %s" % gname(d.DesiredGear))

    # Downshifts, from the table in third and above.
    for gear, w in ((FOURTH_GEAR, 120.0), (FOURTH_GEAR, 400.0),
                    (THIRD_GEAR, 120.0)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=w)
        for ww in wheels:
            ww.TouchingGround = 1
        d.CurrentGear = gear
        d.DesiredGear = gear
        d.CurrentClutchState = CLUTCH_ENGAGED
        set_desired_gear(d, AUTOMATIC)
        emit("au down %s w %s desired %s (down %s rpm %s)"
             % (gname(gear), g9(f32(w)), gname(d.DesiredGear),
                g9(d.ShiftDownRPM[gear]), g9(fmul(f32(w),
                                                  K_RADS_TO_RPM_AUTO))))

    # First and second have no table point: with the throttle nearly shut
    # they drop out just above idle, and with it open they never do.
    for gear in (FIRST_GEAR, SECOND_GEAR):
        for throttle in (0.1, 0.2, 0.9):
            d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=throttle,
                                                 w=70.0)
            for ww in wheels:
                ww.TouchingGround = 1
            d.CurrentGear = gear
            d.DesiredGear = gear
            d.CurrentClutchState = CLUTCH_ENGAGED
            set_desired_gear(d, AUTOMATIC)
            emit("au crawl %s t %s desired %s"
                 % (gname(gear), g9(f32(throttle)), gname(d.DesiredGear)))

    # Both of the automatic's thresholds, sat on exactly.
    #
    # The point is written back as the very rpm the object will compute,
    # from the same product on both sides, so the comparison is against
    # itself: `point < rpm` is false and `point <= rpm` is true, and the
    # gear that comes out says which one the image wrote. Choosing an
    # engine speed and hoping the product lands on a table entry would
    # only be true to a few ulps.
    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=700.0)
    for w in wheels:
        w.TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.ShiftUpRPM[THIRD_GEAR] = fmul(e.w, K_RADS_TO_RPM_AUTO)
    set_desired_gear(d, AUTOMATIC)
    emit("au up-exact desired %s (rpm %s up %s)"
         % (gname(d.DesiredGear), g9(fmul(e.w, K_RADS_TO_RPM_AUTO)),
            g9(d.ShiftUpRPM[THIRD_GEAR])))

    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.9, w=300.0)
    for w in wheels:
        w.TouchingGround = 1
    d.CurrentGear = FOURTH_GEAR
    d.DesiredGear = FOURTH_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.ShiftDownRPM[FOURTH_GEAR] = fmul(e.w, K_RADS_TO_RPM_AUTO)
    set_desired_gear(d, AUTOMATIC)
    emit("au down-exact desired %s (rpm %s down %s)"
         % (gname(d.DesiredGear), g9(fmul(e.w, K_RADS_TO_RPM_AUTO)),
            g9(d.ShiftDownRPM[FOURTH_GEAR])))

    # Anything that is neither mode is written straight through.
    for g in (REVERSE, NEUTRAL, FIFTH_GEAR, SEVENTH_GEAR, 42):
        d, e, wheels, cs, dti, ei = make_rig(1.0)
        r = set_desired_gear(d, g)
        emit("au direct %s -> %s desired %s"
             % (gname(g), gname(r), gname(d.DesiredGear)))


def s_sport_shift():
    """SetDesiredGear in SPORT_SHIFT."""
    reset_globals()

    # The hold timer runs off WorldTimeElapsed, which is zero in the image.
    d, e, wheels, cs, dti, ei = make_rig(1.0, w=400.0)
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.SportGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGING
    for _ in range(3):
        set_desired_gear(d, SPORT_SHIFT)
    pf("ss hold image", d.GearHoldTime)

    G["WorldTimeElapsed"] = f32(1.0 / 60.0)

    # Not engaged: the timer still runs, nothing else does.
    d, e, wheels, cs, dti, ei = make_rig(1.0, w=400.0)
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = FOURTH_GEAR
    d.SportGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGING
    r = set_desired_gear(d, SPORT_SHIFT)
    emit("ss notengaged -> %s desired %s hold %s"
         % (gname(r), gname(d.DesiredGear), g9(d.GearHoldTime)))

    # An upshift request: SportGear above DesiredGear.
    d, e, wheels, cs, dti, ei = make_rig(1.0, w=400.0)
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.SportGear = FOURTH_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.GearHoldTime = f32(2.0)
    r = set_desired_gear(d, SPORT_SHIFT)
    emit("ss up -> %s desired %s prev %s hold %s"
         % (gname(r), gname(d.DesiredGear), gname(d.PreviousGear),
            g9(d.GearHoldTime)))

    # A downshift request at a safe engine speed, and one the engine is
    # too fast for.
    for w in (150.0, 700.0):
        d, e, wheels, cs, dti, ei = make_rig(1.0, w=w)
        d.CurrentGear = FOURTH_GEAR
        d.DesiredGear = FOURTH_GEAR
        d.SportGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        d.GearHoldTime = f32(2.0)
        r = set_desired_gear(d, SPORT_SHIFT)
        emit("ss down w %s -> %s desired %s sport %s hold %s"
             % (g9(f32(w)), gname(r), gname(d.DesiredGear),
                gname(d.SportGear), g9(d.GearHoldTime)))

    # In first and second the down test is the crawl one, not the ratio.
    for throttle in (0.1, 0.9):
        d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=throttle, w=70.0)
        d.CurrentGear = SECOND_GEAR
        d.DesiredGear = SECOND_GEAR
        d.SportGear = FIRST_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        r = set_desired_gear(d, SPORT_SHIFT)
        emit("ss crawl t %s -> %s desired %s sport %s"
             % (g9(f32(throttle)), gname(r), gname(d.DesiredGear),
                gname(d.SportGear)))

    # The requested gear is in: hand back AUTOMATIC after ten seconds.
    for t, hold in enumerate((9.9, 10.0, 10.1)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, w=400.0)
        d.CurrentGear = FOURTH_GEAR
        d.DesiredGear = FOURTH_GEAR
        d.SportGear = FOURTH_GEAR
        d.PreviousGear = FOURTH_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        d.GearHoldTime = fsub(f32(hold), G["WorldTimeElapsed"])
        r = set_desired_gear(d, SPORT_SHIFT)
        emit("ss held %d -> %s" % (t, gname(r)))

    # Or immediately, after an upshift that ran into the limiter.
    # 720 is the one that matters: 6875.5 RPM is over MaxRPM - 300 and
    # under MaxRPM, so it is the only speed here that tells the margin
    # from no margin at all. 760 is over both and 400 is under both.
    for prev, w in ((THIRD_GEAR, 760.0), (THIRD_GEAR, 400.0),
                    (FIFTH_GEAR, 760.0), (THIRD_GEAR, 720.0)):
        d, e, wheels, cs, dti, ei = make_rig(1.0, w=w)
        d.CurrentGear = FOURTH_GEAR
        d.DesiredGear = FOURTH_GEAR
        d.SportGear = FOURTH_GEAR
        d.PreviousGear = prev
        d.CurrentClutchState = CLUTCH_ENGAGED
        d.GearHoldTime = ZERO
        r = set_desired_gear(d, SPORT_SHIFT)
        emit("ss limiter prev %s w %s -> %s (rpm %s max %s)"
             % (gname(prev), g9(f32(w)), gname(r),
                g9(fmul(f32(w), K_RADS_TO_RPM_SPORT)),
                g9(fsub(ei.MaxRPM, K_LIMITER_MARGIN))))

    # The refusal test sat on exactly.
    #
    # In second the down point is IdleRPM + 100 = 900 whole, and
    # 94.2477036 is the one float whose product with the object's own
    # rads-to-RPM constant is exactly 900. (It is one float: the two
    # either side of it land an ulp away.) So `down < rpm` is false and
    # `down <= rpm` is true, and the gear that comes out says which the
    # image wrote -- a refusal puts the request back at second, and
    # letting it through drops to first.
    d, e, wheels, cs, dti, ei = make_rig(1.0, w=94.2477036)
    d.CurrentGear = SECOND_GEAR
    d.DesiredGear = SECOND_GEAR
    d.SportGear = FIRST_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.GearHoldTime = f32(2.0)
    r = set_desired_gear(d, SPORT_SHIFT)
    emit("ss refuse-exact -> %s desired %s sport %s hold %s (rpm %s)"
         % (gname(r), gname(d.DesiredGear), gname(d.SportGear),
            g9(d.GearHoldTime), g9(fmul(e.w, K_RADS_TO_RPM_SPORT))))

    # gMaxDownShiftOver moves the sport downshift test.
    for over in (1.1, 0.4):
        G["MaxDownShiftOver"] = f32(over)
        d, e, wheels, cs, dti, ei = make_rig(1.0, w=400.0)
        d.CurrentGear = FOURTH_GEAR
        d.DesiredGear = FOURTH_GEAR
        d.SportGear = THIRD_GEAR
        d.CurrentClutchState = CLUTCH_ENGAGED
        r = set_desired_gear(d, SPORT_SHIFT)
        emit("ss over %s desired %s sport %s"
             % (g9(f32(over)), gname(d.DesiredGear), gname(d.SportGear)))

    reset_globals()


def s_accessors():
    reset_globals()
    d, e, wheels, cs, dti, ei = make_rig(0.5, gears=5)

    d.DesiredGear = FOURTH_GEAR
    d.CurrentGear = THIRD_GEAR
    d.PreviousGear = SECOND_GEAR
    d.SportGear = FIFTH_GEAR

    emit("ax gears %s %s %s %s top %s"
         % (gname(d.DesiredGear), gname(d.CurrentGear),
            gname(d.PreviousGear), gname(d.SportGear),
            gname(get_top_gear(d))))
    emit("ax drive rwd %d fwd %d" % (rear_wheel_drive(d),
                                     front_wheel_drive(d)))

    for state in (-1, 0, 1, 2, 3, 4):
        d.CurrentClutchState = state
        emit("ax engaged %d -> %d" % (state, is_clutch_engaged(d)))

    # GetShiftUpRPM and GetShiftDownRPM are unguarded, so REVERSE and
    # NEUTRAL read the two entries CalculateShiftPoints never wrote. The
    # harness callocs, so both read zero -- and that is the point.
    for g in range(9):
        emit("ax rpm %s up %s down %s"
             % (gname(g), g9(d.ShiftUpRPM[g]), g9(d.ShiftDownRPM[g])))

    d.CurrentClutchState = CLUTCH_ENGAGING
    out = [f32(-1.0)]
    get_derivative(d, out)
    pf("ax derivative", out[0])

    set_state_gear(d, SIXTH_GEAR)
    emit("ax setstate gear %s desired %s clutch %s state %s"
         % (gname(d.CurrentGear), gname(d.DesiredGear), g9(d.clutch),
            cname(d.CurrentClutchState)))

    d.clutch = f32(0.375)
    out = [f32(-1.0)]
    out[0] = d.clutch
    pf("ax getstate", out[0])
    d.clutch = f32(0.875)
    pf("ax setstate array", d.clutch)

    finalize_clutch_torque(d)
    emit("ax finalize clutch %s" % g9(d.clutch))

    emit("ax wired %d %d" % (1 if d.pEngine is e else 0,
                             1 if d.DTI is dti else 0))


def s_frames():
    """Twelve frames of an integrated drivetrain: the clutch sweeps, the
    state machine walks, and an upshift completes end to end."""
    reset_globals()
    G["WorldTimeElapsed"] = f32(1.0 / 60.0)

    d, e, wheels, cs, dti, ei = make_rig(1.0, throttle=0.85, w=300.0,
                                         speed=25.0)
    for i, spin in enumerate((80.0, 81.0, 84.0, 85.0)):
        wheels[i].w = f32(spin)
        wheels[i].TouchingGround = 1
    d.CurrentGear = THIRD_GEAR
    d.DesiredGear = THIRD_GEAR
    d.CurrentClutchState = CLUTCH_ENGAGED
    d.clutch = ONE

    out = [ZERO]
    dt = f32(1.0 / 60.0)

    for frame in range(12):
        compute_auxiliaries(d)
        guess_clutch_torque(d)
        modify_clutch_torque(d)
        finalize_clutch_torque(d)
        set_desired_gear(d, AUTOMATIC)

        get_derivative(d, out)
        d.clutch = fadd(d.clutch, fmul(out[0], dt))

        # A crude integrator for the rest, so the numbers move: this is
        # the harness's own arithmetic, identical on both sides, not a
        # claim about the game's.
        e.w = fadd(e.w, fmul(EN.engine_get_angular_acceleration(e), dt))
        for w in wheels:
            w.w = fadd(w.w, fmul(fdiv(w.AppliedTorque, w.MomentOfInertia),
                                 fmul(dt, f32(0.01))))
            w.AppliedTorque = ZERO
        e.RoadTorque = ZERO

        emit("fr %02d %s %s clutch %s diffw %s ew %s"
             % (frame, gname(d.CurrentGear), cname(d.CurrentClutchState),
                g9(d.clutch), g9(d.DifferentialAngularVelocity), g9(e.w)))
        print_wheels("fr %02d" % frame, wheels)

    reset_globals()


SCENARIOS = [
    ("layout", s_layout),
    ("shift-points", s_shift_points),
    ("ctor", s_ctor),
    ("differential-velocity", s_differential_velocity),
    ("slippage", s_slippage),
    ("set-differential", s_set_differential),
    ("differential-acceleration", s_differential_acceleration),
    ("derivative", s_derivative),
    ("idling-matched", s_idling_matched),
    ("apply-clutch-torque", s_apply_clutch_torque),
    ("guess-clutch-torque", s_guess_clutch_torque),
    ("modify-clutch-torque", s_modify_clutch_torque),
    ("compute-auxiliaries", s_compute_auxiliaries),
    ("sport-gear", s_sport_gear),
    ("automatic", s_automatic),
    ("sport-shift", s_sport_shift),
    ("accessors", s_accessors),
    ("frames", s_frames),
]


def model():
    global OUT
    OUT = []
    check_pool()
    reset_globals()
    for _, fn in SCENARIOS:
        fn()
    return OUT


# ------------------------------------------------------------------ driver

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
    # -- CalculateShiftPoints ------------------------------------------
    ("sp-loop-starts-at-reverse", DC,
     "    for (i = FIRST_GEAR; i < last; i++) {",
     "    for (i = REVERSE; i < last; i++) {"),
    ("sp-loop-excludes-top", DC,
     "    for (i = FIRST_GEAR; i < last; i++) {",
     "    for (i = FIRST_GEAR; i < last - 1; i++) {"),
    ("sp-last-is-numgears", DC,
     "    last = dti->NumGears + 1;", "    last = dti->NumGears;"),
    ("sp-midpoint-is-redline", DC,
     "            float rpm     = (ei->IdleRPM + ei->MaxRPM) * 0.5f;",
     "            float rpm     = (ei->IdleRPM + ei->RedLineRPM) * 0.5f;"),
    ("sp-ceiling-not-subtracted", DC,
     "            float ceiling = ei->MaxRPM - K_SHIFT_CEILING;",
     "            float ceiling = ei->MaxRPM;"),
    ("sp-step-25", DC, "                    rpm += K_SHIFT_STEP;",
     "                    rpm += K_SHIFT_STEP * 0.5f;"),
    ("sp-crossover-not-strict", DC, "                    if (here < there) {",
     "                    if (here <= there) {"),
    ("sp-crossover-reversed", DC, "                    if (here < there) {",
     "                    if (there < here) {"),
    ("sp-there-not-geared", DC,
     "                    float there = table_get_value(&torque, rpm * next / ratio)"
     + NL + "                                      * next / ratio;",
     "                    float there = table_get_value(&torque, rpm * next / ratio);"),
    ("sp-there-arg-not-geared", DC,
     "                    float there = table_get_value(&torque, rpm * next / ratio)"
     + NL + "                                      * next / ratio;",
     "                    float there = table_get_value(&torque, rpm)"
     + NL + "                                      * next / ratio;"),
    ("sp-searching-starts-clear", DC, "            int32_t searching = 1;",
     "            int32_t searching = 0;"),
    ("sp-fallback-unscaled", DC,
     "            point = up[i] * scale;",
     "            point = searching ? up[i] : up[i] * scale;"),
    ("sp-loop-is-do-while", DC, "            if (rpm < ceiling) {",
     "            if (1) {"),
    ("sp-down-no-detune", DC,
     "        down[i + 1] = gShiftDownDetune * up[i] * next / ratio;",
     "        down[i + 1] = up[i] * next / ratio;"),
    ("sp-down-writes-own-gear", DC,
     "        down[i + 1] = gShiftDownDetune * up[i] * next / ratio;",
     "        down[i] = gShiftDownDetune * up[i] * next / ratio;"),
    ("sp-down-ratio-inverted", DC,
     "        down[i + 1] = gShiftDownDetune * up[i] * next / ratio;",
     "        down[i + 1] = gShiftDownDetune * up[i] * ratio / next;"),
    ("sp-top-not-written", DC, "    up[i] = ei->MaxRPM;",
     "    (void)0;"),
    ("sp-top-is-redline", DC, "    up[i] = ei->MaxRPM;",
     "    up[i] = ei->RedLineRPM;"),
    ("sp-interp-uses-maxrpm", DC,
     "                  + dti->ShiftUpPoint * (ei->RedLineRPM - ei->IdleRPM);",
     "                  + dti->ShiftUpPoint * (ei->MaxRPM - ei->IdleRPM);"),
    ("sp-interp-scaled", DC,
     "            point = ei->IdleRPM" + NL
     + "                  + dti->ShiftUpPoint * (ei->RedLineRPM - ei->IdleRPM);",
     "            point = (ei->IdleRPM" + NL
     + "                  + dti->ShiftUpPoint * (ei->RedLineRPM - ei->IdleRPM)) * scale;"),
    ("sp-table-eight-entries", DC,
     "    table_init(&torque, ei->TorqueCurveTable, 9, ei->IdleRPM, ei->MaxRPM);",
     "    table_init(&torque, ei->TorqueCurveTable, 8, ei->IdleRPM, ei->MaxRPM);"),
    ("sp-table-spans-redline", DC,
     "    table_init(&torque, ei->TorqueCurveTable, 9, ei->IdleRPM, ei->MaxRPM);",
     "    table_init(&torque, ei->TorqueCurveTable, 9, ei->IdleRPM, ei->RedLineRPM);"),

    # -- the constructor -----------------------------------------------
    ("ct-starts-in-neutral", DC, "    d->DesiredGear = FIRST_GEAR;",
     "    d->DesiredGear = NEUTRAL;"),
    ("ct-current-starts-neutral", DC, "    d->CurrentGear = FIRST_GEAR;",
     "    d->CurrentGear = NEUTRAL;"),
    ("ct-clutch-starts-home", DC, "    d->State.clutch = 0.0f;",
     "    d->State.clutch = 1.0f;"),
    ("ct-starts-engaged", DC,
     "    d->CurrentClutchState = CLUTCH_ENGAGING;",
     "    d->CurrentClutchState = CLUTCH_ENGAGED;"),
    ("ct-shifting-set", DC, "    d->Shifting = 0;", "    d->Shifting = 1;"),
    ("ct-clears-sport-gear", DC, "    d->Shifting = 0;",
     "    d->Shifting = 0;" + NL + "    d->SportGear = NEUTRAL;"),
    ("ct-clears-hold-time", DC, "    d->Shifting = 0;",
     "    d->Shifting = 0;" + NL + "    d->GearHoldTime = 0.0f;"),
    ("ct-shift-points-unscaled", DC,
     "                                      d->ShiftDownRPM, gShiftUpDetune);",
     "                                      d->ShiftDownRPM, 1.0f);"),
    ("ct-shift-points-use-down-detune", DC,
     "                                      d->ShiftDownRPM, gShiftUpDetune);",
     "                                      d->ShiftDownRPM, gShiftDownDetune);"),
    ("ct-copies-three-wheels", DC, "    for (k = 0; k < 4; k++)",
     "    for (k = 0; k < 3; k++)"),
    ("ct-wheels-reversed", DC, "        d->pDriveWheel[k] = wheels[k];",
     "        d->pDriveWheel[k] = wheels[3 - k];"),

    # -- GetDifferentialAngularVelocity --------------------------------
    ("dv-rear-test-strict", DC,
     "    int32_t rear = (K_SPLIT_LOW <= split);",
     "    int32_t rear = (K_SPLIT_LOW < split);"),
    ("dv-front-test-strict", DC,
     "    if (split <= K_SPLIT_HIGH) {" + NL
     + "        w += ((d->pDriveWheel[0]->State.w + d->pDriveWheel[1]->State.w) * 0.5f)",
     "    if (split < K_SPLIT_HIGH) {" + NL
     + "        w += ((d->pDriveWheel[0]->State.w + d->pDriveWheel[1]->State.w) * 0.5f)"),
    ("dv-rear-uses-front-drive", DC,
     "        w = ((d->pDriveWheel[2]->State.w + d->pDriveWheel[3]->State.w) * 0.5f)"
     + NL + "                * dti->FinalDrive[1];",
     "        w = ((d->pDriveWheel[2]->State.w + d->pDriveWheel[3]->State.w) * 0.5f)"
     + NL + "                * dti->FinalDrive[0];"),
    ("dv-rear-pair-is-front", DC,
     "        w = ((d->pDriveWheel[2]->State.w + d->pDriveWheel[3]->State.w) * 0.5f)",
     "        w = ((d->pDriveWheel[0]->State.w + d->pDriveWheel[1]->State.w) * 0.5f)"),
    ("dv-always-halves", DC,
     "        if (!rear)" + NL + "            both = 0;" + NL + NL
     + "        if (both)" + NL + "            w *= 0.5f;" + NL + "    }" + NL
     + NL + "    return w * dti->GearRatios[d->CurrentGear];",
     "        if (!rear)" + NL + "            both = 0;" + NL + "    }" + NL
     + NL + "    w *= 0.5f;" + NL
     + "    return w * dti->GearRatios[d->CurrentGear];"),
    ("dv-never-halves", DC,
     "        if (both)" + NL + "            w *= 0.5f;" + NL + "    }" + NL
     + NL + "    return w * dti->GearRatios[d->CurrentGear];",
     "    }" + NL + NL + "    return w * dti->GearRatios[d->CurrentGear];"),
    ("dv-no-gear-ratio", DC,
     "    return w * dti->GearRatios[d->CurrentGear];", "    return w;"),
    ("dv-ratio-off-by-one", DC,
     "    return w * dti->GearRatios[d->CurrentGear];",
     "    return w * dti->GearRatios[d->CurrentGear - 1];"),

    # -- GetDriveWheelSlippage -----------------------------------------
    ("ds-front-not-halved", DC,
     "        s = (s + (d->pDriveWheel[0]->OldSlip + d->pDriveWheel[1]->OldSlip)"
     + NL + "                     * 0.5f) * 0.5f;",
     "        s = s + (d->pDriveWheel[0]->OldSlip + d->pDriveWheel[1]->OldSlip)"
     + NL + "                    * 0.5f;"),
    ("ds-uses-current-slip", DC,
     "        s = (d->pDriveWheel[2]->OldSlip + d->pDriveWheel[3]->OldSlip) * 0.5f;",
     "        s = (d->pDriveWheel[2]->CurrentSlip + d->pDriveWheel[3]->CurrentSlip) * 0.5f;"),
    ("ds-rear-not-halved", DC,
     "        s = (d->pDriveWheel[2]->OldSlip + d->pDriveWheel[3]->OldSlip) * 0.5f;",
     "        s = d->pDriveWheel[2]->OldSlip + d->pDriveWheel[3]->OldSlip;"),

    # -- SetDifferentialAngularVelocity --------------------------------
    ("sv-no-step", DC, "    wheel_set_state_w(a, wa + step);",
     "    wheel_set_state_w(a, wa);"),
    ("sv-pairs-swapped", DC,
     "        drivetrain_share_out(d, delta, 2, 3, dti->FinalDrive[1],",
     "        drivetrain_share_out(d, delta, 0, 1, dti->FinalDrive[1],"),
    ("sv-speed-test-reversed", DC,
     "        drivetrain_share_out(d, delta, 0, 1, dti->FinalDrive[0]," + NL
     + "                             mph < K_LOW_SPEED_MPH);",
     "        drivetrain_share_out(d, delta, 0, 1, dti->FinalDrive[0]," + NL
     + "                             K_LOW_SPEED_MPH < mph);"),
    ("sv-speed-test-inclusive", DC,
     "        drivetrain_share_out(d, delta, 2, 3, dti->FinalDrive[1]," + NL
     + "                             mph < K_LOW_SPEED_MPH);",
     "        drivetrain_share_out(d, delta, 2, 3, dti->FinalDrive[1]," + NL
     + "                             mph <= K_LOW_SPEED_MPH);"),
    ("sv-airborne-needs-one", DC,
     "    if (!a->TouchingGround && !b->TouchingGround)",
     "    if (!a->TouchingGround || !b->TouchingGround)"),
    ("sv-no-airborne-average", DC,
     "    if (!a->TouchingGround && !b->TouchingGround)" + NL
     + "        slow = 1;", "    (void)0;"),
    ("sv-delta-is-absolute", DC,
     "    float delta = w - drivetrain_get_differential_angular_velocity(d);",
     "    float delta = w;"),
    ("sv-ratio-no-final-drive", DC,
     "    ratio = d->DTI->GearRatios[d->CurrentGear] * drive;",
     "    ratio = d->DTI->GearRatios[d->CurrentGear];"),
    ("sv-average-not-halved", DC,
     "        wb = (wa + wb) * 0.5f;", "        wb = wa + wb;"),

    # -- GetDifferentialAngularAcceleration ----------------------------
    ("da-no-ground-force", DC,
     "    return (w->AppliedTorque - w->GroundForce[0] * radius)",
     "    return (w->AppliedTorque)"),
    ("da-ground-force-added", DC,
     "    return (w->AppliedTorque - w->GroundForce[0] * radius)",
     "    return (w->AppliedTorque + w->GroundForce[0] * radius)"),
    ("da-divides-by-radius", DC,
     "               / wheel_get_moment_of_inertia(w);", "               / radius;"),
    ("da-always-halves", DC,
     "        if (!rear)" + NL + "            both = 0;" + NL + NL
     + "        if (both)" + NL + "            acc *= 0.5f;" + NL + "    }"
     + NL + NL + "    return acc * dti->GearRatios[d->CurrentGear];",
     "        if (!rear)" + NL + "            both = 0;" + NL + "    }" + NL
     + NL + "    acc *= 0.5f;" + NL
     + "    return acc * dti->GearRatios[d->CurrentGear];"),

    # -- GetDerivative -------------------------------------------------
    ("gd-no-shift-speed", DC,
     "    out[0] = d->DTI->ShiftSpeed * kClutchSpeed[d->CurrentClutchState];",
     "    out[0] = kClutchSpeed[d->CurrentClutchState];"),
    ("gd-returns-one", DC, "    return 0;" + NL + "}" + NL + NL
     + "// One driven pair's share",
     "    return 1;" + NL + "}" + NL + NL + "// One driven pair's share"),
    ("gd-clutch-speed-sign", DC,
     "    DRIVETRAIN_CLUTCH_SPEED_DISENGAGING,",
     "    -DRIVETRAIN_CLUTCH_SPEED_DISENGAGING,"),
    ("gd-clutch-speed-swapped", DC,
     "    DRIVETRAIN_CLUTCH_SPEED_DISENGAGING," + NL
     + "    DRIVETRAIN_CLUTCH_SPEED_DISENGAGED," + NL
     + "    DRIVETRAIN_CLUTCH_SPEED_ENGAGING,",
     "    DRIVETRAIN_CLUTCH_SPEED_DISENGAGED," + NL
     + "    DRIVETRAIN_CLUTCH_SPEED_DISENGAGING," + NL
     + "    DRIVETRAIN_CLUTCH_SPEED_ENGAGING,"),
    ("gd-engaging-rate", DH,
     "#define DRIVETRAIN_CLUTCH_SPEED_ENGAGING    ( 1.5f)",
     "#define DRIVETRAIN_CLUTCH_SPEED_ENGAGING    ( 3.0f)"),

    # -- ApplyClutchTorque ---------------------------------------------
    ("ac-neutral-still-brakes", DC,
     "    if (d->CurrentGear == NEUTRAL)" + NL + "        return;" + NL + NL
     + "    dti = d->DTI;" + NL + NL
     + "    d->pEngine->RoadTorque -= torque;",
     "    dti = d->DTI;" + NL + NL + "    d->pEngine->RoadTorque -= torque;"
     + NL + NL + "    if (d->CurrentGear == NEUTRAL)" + NL + "        return;"),
    ("ac-road-torque-added", DC, "    d->pEngine->RoadTorque -= torque;",
     "    d->pEngine->RoadTorque += torque;"),
    ("ac-no-gear-ratio", DC,
     "    geared = torque * dti->GearRatios[d->CurrentGear];",
     "    geared = torque;"),
    ("ac-front-split-not-inverted", DC,
     "    drivetrain_split_torque(d, geared * (1.0f - dti->TorqueSplit)",
     "    drivetrain_split_torque(d, geared * (dti->TorqueSplit)"),
    ("ac-front-uses-rear-drive", DC,
     "                                   * dti->FinalDrive[0]," + NL
     + "                            d->pDriveWheel[0], d->pDriveWheel[1], 0);",
     "                                   * dti->FinalDrive[1]," + NL
     + "                            d->pDriveWheel[0], d->pDriveWheel[1], 0);"),
    ("ac-front-names-first", DC,
     "                            d->pDriveWheel[0], d->pDriveWheel[1], 0);",
     "                            d->pDriveWheel[0], d->pDriveWheel[1], 1);"),
    ("ac-rear-names-second", DC,
     "                            d->pDriveWheel[2], d->pDriveWheel[3], 1);",
     "                            d->pDriveWheel[2], d->pDriveWheel[3], 0);"),
    ("ac-threshold-always-half", DC,
     "    if (first->TouchingGround && second->TouchingGround)" + NL
     + "        threshold = gLimitedSlip;", "    (void)0;"),
    ("ac-threshold-needs-one", DC,
     "    if (first->TouchingGround && second->TouchingGround)",
     "    if (first->TouchingGround || second->TouchingGround)"),
    ("ac-clamp-not-inverted", DC,
     "        if (share < threshold)" + NL
     + "            share = 1.0f - gLimitedSlip * 0.5f;" + NL
     + "        else if (1.0f - threshold < share)" + NL
     + "            share = gLimitedSlip * 0.5f;",
     "        if (share < threshold)" + NL
     + "            share = gLimitedSlip * 0.5f;" + NL
     + "        else if (1.0f - threshold < share)" + NL
     + "            share = 1.0f - gLimitedSlip * 0.5f;"),
    ("ac-clamp-to-threshold", DC,
     "            share = 1.0f - gLimitedSlip * 0.5f;",
     "            share = 1.0f - gLimitedSlip;"),
    ("ac-share-ieee-divide", DC,
     "        share = ee_div(named->State.w, named->State.w + other->State.w);",
     "        share = named->State.w / (named->State.w + other->State.w);"),
    ("ac-clamps-independent", DC,
     "        else if (1.0f - threshold < share)",
     "        if (1.0f - threshold < share)"),
    ("ac-burnout-values-swapped", DC,
     "    if (d->pCarState->BurnOutState == 1) {" + NL
     + "        share = 1.0f - threshold;" + NL
     + "    } else if (d->pCarState->BurnOutState == 2) {" + NL
     + "        share = threshold;",
     "    if (d->pCarState->BurnOutState == 1) {" + NL
     + "        share = threshold;" + NL
     + "    } else if (d->pCarState->BurnOutState == 2) {" + NL
     + "        share = 1.0f - threshold;"),
    ("ac-brake-lock-ignored", DC,
     "    if (!first->BrakeLocked)" + NL
     + "        first->AppliedTorque += torque * first_share;",
     "    if (1)" + NL
     + "        first->AppliedTorque += torque * first_share;"),
    ("ac-torque-assigned", DC,
     "        second->AppliedTorque += torque * second_share;",
     "        second->AppliedTorque = torque * second_share;"),

    # -- GuessClutchTorque ---------------------------------------------
    ("gc-slip-reversed", DC,
     "        float slip = d->pEngine->State.w - d->DifferentialAngularVelocity;",
     "        float slip = d->DifferentialAngularVelocity - d->pEngine->State.w;"),
    ("gc-no-clutch-scale", DC,
     "            d, slip * d->DTI->ClutchStiffness * d->State.clutch);",
     "            d, slip * d->DTI->ClutchStiffness);"),
    ("gc-clamp-one-sided", DC,
     "        else if (slip < -gClutchLimiter)" + NL
     + "            slip = -gClutchLimiter;", "        (void)0;"),
    ("gc-clamp-inclusive", DC, "        if (gClutchLimiter < slip)",
     "        if (gClutchLimiter <= slip)"),
    ("gc-disengaged-applies", DC,
     "    case CLUTCH_DISENGAGED:" + NL + "        break;",
     "    case CLUTCH_DISENGAGED:" + NL
     + "        drivetrain_apply_clutch_torque(d, 0.0f);" + NL
     + "        break;"),
    ("gc-engaged-uses-road-torque", DC,
     "            d, engine_get_total_engine_torque(d->pEngine));",
     "            d, d->pEngine->RoadTorque);"),

    # -- ModifyClutchTorque --------------------------------------------
    ("mc-runs-when-engaging", DC,
     "    if (d->CurrentClutchState != CLUTCH_ENGAGED)" + NL
     + "        return;" + NL + NL + "    e = d->pEngine;" + NL + NL
     + "    // Engine::GetDerivative's expression",
     "    if (0)" + NL + "        return;" + NL + NL + "    e = d->pEngine;"
     + NL + NL + "    // Engine::GetDerivative's expression"),
    ("mc-no-road-torque", DC,
     "    difference = (engine_get_total_engine_torque(e) + e->RoadTorque)",
     "    difference = (engine_get_total_engine_torque(e))"),
    ("mc-difference-reversed", DC,
     "    difference -= drivetrain_get_differential_angular_acceleration(d);",
     "    difference = drivetrain_get_differential_angular_acceleration(d)"
     + NL + "               - difference;"),
    ("mc-front-uses-odd-wheel", DC,
     "                                    d->pDriveWheel[0])))" + NL
     + "                       * geared;",
     "                                    d->pDriveWheel[1])))" + NL
     + "                       * geared;"),
    ("mc-rear-uses-odd-wheel", DC,
     "                                    d->pDriveWheel[2])))" + NL
     + "                       * geared;",
     "                                    d->pDriveWheel[3])))" + NL
     + "                       * geared;"),
    ("mc-geared-once", DC,
     "        float geared = dti->FinalDrive[0] * dti->GearRatios[d->CurrentGear];",
     "        float geared = dti->FinalDrive[0];"),
    ("mc-split-not-halved", DC,
     "        inverse += ((1.0f - dti->TorqueSplit) * 0.5f)",
     "        inverse += ((1.0f - dti->TorqueSplit))"),
    ("mc-inverse-starts-zero", DC,
     "    inverse = 1.0f / e->EI->MomentOfInertia;", "    inverse = 0.0f;"),

    # -- Idling / ClutchMatched ----------------------------------------
    ("id-throttle-inclusive", DC,
     "    if (!(e->Throttle < K_IDLE_THROTTLE))",
     "    if (!(e->Throttle <= K_IDLE_THROTTLE))"),
    ("id-no-slop", DC,
     "               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS + K_IDLE_SLOP;",
     "               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS;"),
    ("id-compares-engine", DC,
     "    return d->DifferentialAngularVelocity" + NL
     + "               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS + K_IDLE_SLOP;",
     "    return e->State.w" + NL
     + "               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS + K_IDLE_SLOP;"),
    ("id-idle-not-converted", DC,
     "               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS + K_IDLE_SLOP;",
     "               <= e->EI->IdleRPM + K_IDLE_SLOP;"),
    ("cm-no-abs", DC,
     "    return fabsf(d->pEngine->State.w - d->DifferentialAngularVelocity)",
     "    return (d->pEngine->State.w - d->DifferentialAngularVelocity)"),
    ("cm-strict", DC, "               <= gClutchMatchedThreshold;",
     "               < gClutchMatchedThreshold;"),

    # -- ComputeAuxiliaries --------------------------------------------
    ("ca-no-cache", DC,
     "    d->DifferentialAngularVelocity =" + NL
     + "        drivetrain_get_differential_angular_velocity(d);",
     "    (void)0;"),
    ("ca-disengaging-clamps-strict", DC,
     "        if (d->State.clutch <= e->ThrottleOverride) {",
     "        if (d->State.clutch < e->ThrottleOverride) {"),
    ("ca-disengaging-pedal", DC,
     "    case CLUTCH_DISENGAGING:" + NL
     + "        e->ThrottleOverride = 0.0f;",
     "    case CLUTCH_DISENGAGING:" + NL
     + "        e->ThrottleOverride = 1.0f;"),
    ("ca-gear-changes-late", DC,
     "        d->CurrentGear = d->DesiredGear;" + NL
     + "        e->ThrottleOverride = 0.0f;",
     "        e->ThrottleOverride = 0.0f;"),
    ("ca-disengaged-throttle-strict", DC,
     "        if (d->Shifting || K_IDLE_THROTTLE < e->Throttle) {",
     "        if (d->Shifting || K_IDLE_THROTTLE <= e->Throttle) {"),
    ("ca-disengaged-ignores-shifting", DC,
     "        if (d->Shifting || K_IDLE_THROTTLE < e->Throttle) {",
     "        if (K_IDLE_THROTTLE < e->Throttle) {"),
    ("ca-engaging-pedal-full", DC,
     "        e->ThrottleOverride = K_ENGAGING_PEDAL;",
     "        e->ThrottleOverride = 1.0f;"),
    ("ca-engaging-no-neutral-escape", DC,
     "            if (drivetrain_clutch_matched(d) || d->CurrentGear == NEUTRAL)",
     "            if (drivetrain_clutch_matched(d))"),
    ("ca-engaging-no-clamp", DC,
     "        if (1.0f <= d->State.clutch) {" + NL
     + "            d->State.clutch = 1.0f;",
     "        if (1.0f <= d->State.clutch) {" + NL + "            (void)0;"),
    ("ca-engaging-no-idle-drop", DC,
     "        if (drivetrain_idling(d))" + NL
     + "            d->CurrentClutchState = CLUTCH_DISENGAGING;" + NL
     + "        break;" + NL + NL + "    case CLUTCH_ENGAGED:",
     "        break;" + NL + NL + "    case CLUTCH_ENGAGED:"),
    ("ca-engaged-pull-doubled", DC,
     "                e->State.w += slip * K_ENGINE_PULL;",
     "                e->State.w += slip * K_ENGINE_PULL * 2.0f;"),
    ("ca-engaged-pull-sign", DC,
     "                e->State.w += slip * K_ENGINE_PULL;",
     "                e->State.w -= slip * K_ENGINE_PULL;"),
    ("ca-engaged-spin-needs-both", DC,
     "            if (K_SLIP_THROTTLE < e->Throttle && 0.0f < slippage) {",
     "            if (K_SLIP_THROTTLE < e->Throttle || 0.0f < slippage) {"),
    ("ca-engaged-spin-slip-inclusive", DC,
     "            if (K_SLIP_THROTTLE < e->Throttle && 0.0f < slippage) {",
     "            if (K_SLIP_THROTTLE < e->Throttle && 0.0f <= slippage) {"),
    ("ca-engaged-no-diff-write", DC,
     "                d->DifferentialAngularVelocity = e->State.w;" + NL
     + "                drivetrain_set_differential_angular_velocity(",
     "                drivetrain_set_differential_angular_velocity("),
    ("ca-neutral-runs-physics", DC,
     "        if (d->CurrentGear != NEUTRAL) {", "        if (1) {"),
    ("ca-neutral-skips-pedal", DC,
     "        e->ThrottleOverride = 1.0f;" + NL + NL
     + "        // NEUTRAL skips every bit",
     "        if (d->CurrentGear != NEUTRAL)" + NL
     + "            e->ThrottleOverride = 1.0f;" + NL + NL
     + "        // NEUTRAL skips every bit"),
    ("ca-shift-test-inside-neutral", DC,
     "        if (d->CurrentGear != d->DesiredGear) {" + NL
     + "            d->CurrentClutchState = CLUTCH_DISENGAGING;" + NL
     + "            d->Shifting = 1;" + NL + "        }" + NL + "        break;",
     "        if (d->CurrentGear != NEUTRAL" + NL
     + "                && d->CurrentGear != d->DesiredGear) {" + NL
     + "            d->CurrentClutchState = CLUTCH_DISENGAGING;" + NL
     + "            d->Shifting = 1;" + NL + "        }" + NL + "        break;"),
    ("ca-shift-clears-shifting", DC, "            d->Shifting = 1;",
     "            d->Shifting = 0;"),

    # -- SetSportGear --------------------------------------------------
    ("sg-low-bound-neutral", DC,
     "    if (!(g < FIRST_GEAR) && !(d->DTI->NumGears + 1 < g)) {",
     "    if (!(g < NEUTRAL) && !(d->DTI->NumGears + 1 < g)) {"),
    ("sg-high-bound-numgears", DC,
     "    if (!(g < FIRST_GEAR) && !(d->DTI->NumGears + 1 < g)) {",
     "    if (!(g < FIRST_GEAR) && !(d->DTI->NumGears < g)) {"),
    ("sg-hold-always-cleared", DC,
     "        if (d->SportGear == NEUTRAL)" + NL
     + "            d->GearHoldTime = 0.0f;", "        d->GearHoldTime = 0.0f;"),
    ("sg-hold-never-cleared", DC,
     "        if (d->SportGear == NEUTRAL)" + NL
     + "            d->GearHoldTime = 0.0f;", "        (void)0;"),
    ("sg-returns-request", DC,
     "    return d->SportGear;" + NL + "}" + NL + NL
     + "Gear drivetrain_set_desired_gear",
     "    return g;" + NL + "}" + NL + NL
     + "Gear drivetrain_set_desired_gear"),

    # -- SetDesiredGear, AUTOMATIC -------------------------------------
    ("au-no-sport-reset", DC, "        d->SportGear = NEUTRAL;",
     "        (void)0;"),
    ("au-low-gear-bound", DC,
     "        if (current < FIRST_GEAR) {" + NL
     + "            d->DesiredGear = FIRST_GEAR;",
     "        if (current < NEUTRAL) {" + NL
     + "            d->DesiredGear = FIRST_GEAR;"),
    ("au-runs-when-engaging", DC,
     "        if (d->CurrentClutchState != CLUTCH_ENGAGED)" + NL
     + "            return g;" + NL + NL + "        e = d->pEngine;",
     "        if (0)" + NL + "            return g;" + NL + NL
     + "        e = d->pEngine;"),
    ("au-crawl-in-third", DC,
     "        if (current < THIRD_GEAR) {" + NL
     + "            // First and second have no table down point. With the",
     "        if (current < FOURTH_GEAR) {" + NL
     + "            // First and second have no table down point. With the"),
    ("au-crawl-open-throttle", DC,
     "            if (e->Throttle < K_SHIFT_THROTTLE)" + NL
     + "                down = e->EI->IdleRPM + K_CRAWL_OVER_IDLE;" + NL
     + "            else" + NL + "                down = 0.0f;" + NL
     + "        } else {" + NL
     + "            down = d->ShiftDownRPM[current];",
     "            down = e->EI->IdleRPM + K_CRAWL_OVER_IDLE;" + NL
     + "        } else {" + NL + "            down = d->ShiftDownRPM[current];"),
    ("au-up-test-inclusive", DC,
     "        if (d->ShiftUpRPM[current] < rpm",
     "        if (d->ShiftUpRPM[current] <= rpm"),
    ("au-up-ignores-slip", DC,
     "                && d->pDriveWheel[0]->CurrentSlip < K_UPSHIFT_SLIP" + NL
     + "                && d->pDriveWheel[0]->TouchingGround",
     "                && d->pDriveWheel[0]->TouchingGround"),
    ("au-up-ignores-ground", DC,
     "                && d->pDriveWheel[2]->CurrentSlip < K_UPSHIFT_SLIP" + NL
     + "                && d->pDriveWheel[2]->TouchingGround",
     "                && d->pDriveWheel[2]->CurrentSlip < K_UPSHIFT_SLIP"),
    ("au-up-past-top", DC,
     "                && current < d->DTI->NumGears + 1",
     "                && current < d->DTI->NumGears + 2"),
    ("au-down-into-neutral", DC,
     "        if (rpm < down && !(current < FIRST_GEAR))",
     "        if (rpm < down)"),
    ("au-down-inclusive", DC,
     "        if (rpm < down && !(current < FIRST_GEAR))",
     "        if (rpm <= down && !(current < FIRST_GEAR))"),
    ("au-rads-not-converted", DC,
     "        rpm = e->State.w * DRIVETRAIN_RADS_TO_RPM;" + NL + NL
     + "        if (current < THIRD_GEAR) {",
     "        rpm = e->State.w;" + NL + NL
     + "        if (current < THIRD_GEAR) {"),

    # -- SetDesiredGear, SPORT_SHIFT -----------------------------------
    ("ss-hold-not-accumulated", DC,
     "    d->GearHoldTime += WorldTimeElapsed;", "    (void)0;"),
    ("ss-hold-after-state-test", DC,
     "    d->GearHoldTime += WorldTimeElapsed;" + NL + NL
     + "    if (d->CurrentClutchState != CLUTCH_ENGAGED)" + NL
     + "        return g;",
     "    if (d->CurrentClutchState != CLUTCH_ENGAGED)" + NL
     + "        return g;" + NL + NL
     + "    d->GearHoldTime += WorldTimeElapsed;"),
    ("ss-down-uses-table", DC,
     "        down = e->EI->MaxRPM * gMaxDownShiftOver" + NL
     + "                   * d->DTI->GearRatios[current]" + NL
     + "                   / d->DTI->GearRatios[current - 1];",
     "        down = d->ShiftDownRPM[current];"),
    ("ss-down-ratio-inverted", DC,
     "                   * d->DTI->GearRatios[current]" + NL
     + "                   / d->DTI->GearRatios[current - 1];",
     "                   * d->DTI->GearRatios[current - 1]" + NL
     + "                   / d->DTI->GearRatios[current];"),
    ("ss-no-previous-gear", DC, "        d->PreviousGear = current;",
     "        (void)0;"),
    ("ss-refuse-inclusive", DC, "            if (down < rpm) {",
     "            if (down <= rpm) {"),
    ("ss-refuse-keeps-sport", DC,
     "                d->DesiredGear = current;" + NL
     + "                d->GearHoldTime = 0.0f;" + NL
     + "                d->SportGear = current;",
     "                d->DesiredGear = current;" + NL
     + "                d->GearHoldTime = 0.0f;"),
    ("ss-down-goes-up", DC,
     "            d->GearHoldTime = 0.0f;" + NL
     + "            d->DesiredGear = current - 1;" + NL
     + "            return g;" + NL + "        }" + NL + NL
     + "        if (d->DesiredGear < d->SportGear) {",
     "            d->GearHoldTime = 0.0f;" + NL
     + "            d->DesiredGear = current + 1;" + NL
     + "            return g;" + NL + "        }" + NL + NL
     + "        if (d->DesiredGear < d->SportGear) {"),
    ("ss-up-goes-down", DC,
     "        if (d->DesiredGear < d->SportGear) {" + NL
     + "            d->GearHoldTime = 0.0f;" + NL
     + "            d->DesiredGear = current + 1;",
     "        if (d->DesiredGear < d->SportGear) {" + NL
     + "            d->GearHoldTime = 0.0f;" + NL
     + "            d->DesiredGear = current - 1;"),
    ("ss-hold-threshold", DC, "    if (K_SPORT_HOLD < d->GearHoldTime)",
     "    if (K_SPORT_HOLD * 0.5f < d->GearHoldTime)"),
    ("ss-hold-inclusive", DC, "    if (K_SPORT_HOLD < d->GearHoldTime)",
     "    if (K_SPORT_HOLD <= d->GearHoldTime)"),
    ("ss-limiter-any-gear", DC,
     "    if (d->PreviousGear < current" + NL
     + "            && e->EI->MaxRPM - K_LIMITER_MARGIN < rpm)",
     "    if (e->EI->MaxRPM - K_LIMITER_MARGIN < rpm)"),
    ("ss-limiter-margin", DC,
     "            && e->EI->MaxRPM - K_LIMITER_MARGIN < rpm)",
     "            && e->EI->MaxRPM < rpm)"),
    ("ss-limiter-direction", DC, "    if (d->PreviousGear < current",
     "    if (current < d->PreviousGear"),
    ("ss-unreachable-arm-returns-g", DC,
     "            d->DesiredGear = current - 1;" + NL
     + "            return AUTOMATIC;" + NL + "        }" + NL + NL
     + "        return g;",
     "            d->DesiredGear = current - 1;" + NL + "        }" + NL + NL
     + "        return g;"),

    # -- accessors -----------------------------------------------------
    ("ax-top-gear-is-numgears", DC,
     "    return d->DTI->NumGears + 1;", "    return d->DTI->NumGears;"),
    ("ax-engaged-is-engaging", DC,
     "    return d->CurrentClutchState == CLUTCH_ENGAGED;",
     "    return d->CurrentClutchState == CLUTCH_ENGAGING;"),
    ("ax-rwd-test-flipped", DC,
     "    return K_SPLIT_LOW <= d->DTI->TorqueSplit;",
     "    return d->DTI->TorqueSplit <= K_SPLIT_LOW;"),
    ("ax-fwd-test-flipped", DC,
     "    return d->DTI->TorqueSplit <= K_SPLIT_HIGH;",
     "    return K_SPLIT_HIGH <= d->DTI->TorqueSplit;"),
    ("ax-shift-arrays-swapped", DC,
     "float drivetrain_get_shift_down_rpm(const DriveTrain *d, Gear g)" + NL
     + "{" + NL + "    return d->ShiftDownRPM[g];",
     "float drivetrain_get_shift_down_rpm(const DriveTrain *d, Gear g)" + NL
     + "{" + NL + "    return d->ShiftUpRPM[g];"),
    ("ax-set-state-gear-not-engaged", DC,
     "    d->CurrentClutchState = CLUTCH_ENGAGED;" + NL
     + "    d->CurrentGear = g;",
     "    d->CurrentClutchState = CLUTCH_ENGAGING;" + NL
     + "    d->CurrentGear = g;"),
    ("ax-set-state-gear-clutch-out", DC,
     "    d->State.clutch = 1.0f;" + NL
     + "    d->CurrentClutchState = CLUTCH_ENGAGED;",
     "    d->State.clutch = 0.0f;" + NL
     + "    d->CurrentClutchState = CLUTCH_ENGAGED;"),
    ("ax-size-two", DC, "    return DRIVETRAIN_STATE_FLOATS;", "    return 2;"),
    ("ax-finalize-has-a-body", DC,
     "void drivetrain_finalize_clutch_torque(DriveTrain *d)" + NL + "{" + NL
     + "    (void)d;",
     "void drivetrain_finalize_clutch_torque(DriveTrain *d)" + NL + "{" + NL
     + "    d->State.clutch = 0.25f;"),

    # -- the globals ---------------------------------------------------
    ("g-shift-method-clear", DC, "int32_t gGearShiftMethod        = 1;",
     "int32_t gGearShiftMethod        = 0;"),
    ("g-up-detune-one", DC, "float   gShiftUpDetune          = 0.949999988f;",
     "float   gShiftUpDetune          = 1.0f;"),
    ("g-down-detune-one", DC,
     "float   gShiftDownDetune        = 0.949999988f;",
     "float   gShiftDownDetune        = 1.0f;"),
    ("g-limited-slip-rounded", DC,
     "float   gLimitedSlip            = 0.349999994f;",
     "float   gLimitedSlip            = 0.34f;"),
    ("g-clutch-limiter", DC, "float   gClutchLimiter          = 300.0f;",
     "float   gClutchLimiter          = 200.0f;"),
    ("g-clutch-matched", DC,
     "float   gClutchMatchedThreshold = 50.0f;",
     "float   gClutchMatchedThreshold = 25.0f;"),
    ("g-max-down-shift-over", DC,
     "float   gMaxDownShiftOver       = 1.10000002f;",
     "float   gMaxDownShiftOver       = 1.0f;"),
    # WorldTimeElapsed's initial value is realtime.c's now, and
    # realtime_check's rt-init-welapsed; the harness here defines its own.

    # -- the header ----------------------------------------------------
    ("h-rpm-to-rads-rounded", DH,
     "#define DRIVETRAIN_RPM_TO_RADS 0.104719676f",
     "#define DRIVETRAIN_RPM_TO_RADS 0.10472f"),
    ("h-rads-to-rpm-rounded", DH,
     "#define DRIVETRAIN_RADS_TO_RPM 9.54930401f",
     "#define DRIVETRAIN_RADS_TO_RPM 9.5493f"),
    ("h-state-floats-two", DH, "#define DRIVETRAIN_STATE_FLOATS 1",
     "#define DRIVETRAIN_STATE_FLOATS 2"),
    ("h-vtable", DH, "#define DRIVETRAIN_VTABLE 0x00297a30u",
     "#define DRIVETRAIN_VTABLE 0x00297a20u"),
    ("h-neutral-is-zero", DH, "#define NEUTRAL       ((Gear)1)",
     "#define NEUTRAL       ((Gear)0)"),
    ("h-first-gear-is-one", DH, "#define FIRST_GEAR    ((Gear)2)",
     "#define FIRST_GEAR    ((Gear)1)"),
    ("h-clutch-engaged-is-two", DH,
     "#define CLUTCH_ENGAGED     ((ClutchState)3)",
     "#define CLUTCH_ENGAGED     ((ClutchState)2)"),
    ("h-slack-widens-dti", DH,
     "     && offsetof(DriveTrain, DTI)          ==  16",
     "     && offsetof(DriveTrain, DTI)          ==  16 + 1 * DRIVETRAIN_SLACK"),
    ("h-slack-is-zero", DH,
     "#define DRIVETRAIN_SLACK ((size_t)(sizeof(void *) - 4))",
     "#define DRIVETRAIN_SLACK ((size_t)0)"),
    ("h-record-is-144", DH,
     "     && sizeof(DriveTrain) == 148 + 7 * DRIVETRAIN_SLACK",
     "     && sizeof(DriveTrain) == 144 + 7 * DRIVETRAIN_SLACK"),
    ("h-shift-arrays-eight", DH, "    float     ShiftUpRPM[9];                //  76",
     "    float     ShiftUpRPM[8];                //  76"),
]

# Mutants that cannot move a line. Each one is an argument, not an excuse.
#
#   ss-unreachable-arm-returns-g -- the arm at 0x00183b94 needs DesiredGear
#   and SportGear to be neither equal nor ordered. They are two int32_t.
#   The enclosing `if` has already established that they differ, and the
#   two `slt` tests before this point cover both orderings, so a signed
#   comparison of two ints leaves no third case for control to arrive
#   through. No scenario can reach it, in the model or in the port,
#   because no *machine* can. The arm is ported rather than deleted
#   because the image has it and because deleting nineteen instructions on
#   the strength of an argument is how a port quietly stops being a port;
#   this entry is the argument written down where it can be re-read.
#
#   h-slack-is-zero -- DRIVETRAIN_SLACK only ever appears inside the layout
#   assert, and pinning it to 0 makes the assert wrong on a 64-bit host, so
#   the mutant does not compile there. It is reported as caught, not
#   survived, on this machine. It is named here so that a future run on a
#   32-bit host, where the same edit compiles and changes nothing, finds
#   the argument already written rather than discovering a hole. It is in
#   the list rather than only in this comment, so that run reports it as
#   equivalent and exits 0 instead of stopping on a hole that is not one.
#
#   gc-clamp-inclusive -- GuessClutchTorque's upper clamp is
#   `if (gClutchLimiter < slip) slip = gClutchLimiter;`. The mutant makes
#   the test inclusive, so the two differ on exactly one input: slip
#   equal to gClutchLimiter. There the mutant assigns slip the value slip
#   already holds. There is no input on which the two produce different
#   state, so no transcript can separate them.
#
#   That boundary is not merely untested -- `gc DISENGAGING slip 300` and
#   `gc ENGAGING slip 300` drive it exactly, because the fixture sets the
#   differential to 200 and the engine to 200 + slip, and gClutchLimiter
#   is 300. The scenario sits on the boundary and the mutant survives it,
#   which is the argument rather than a gap in it.
#
#   The lower clamp, `slip < -gClutchLimiter`, would be equivalent under
#   the same edit for the same reason. There is no mutation for it: what
#   MUTATIONS carries there is gc-clamp-one-sided, which deletes the arm
#   outright and is caught.
#
#   au-down-into-neutral -- the automatic's downshift is
#   `if (rpm < down && !(current < FIRST_GEAR))`, and the mutant drops the
#   second conjunct. The arm is only reached past
#   `if (current < FIRST_GEAR) { DesiredGear = FIRST_GEAR; return g; }`,
#   and nothing writes `current` in between: it is read once from
#   CurrentGear at the top. So the dropped test is true on every path that
#   can reach it. The image tests it anyway, which is why the port does
#   too -- the PS2 compiler reloaded CurrentGear and compared it again
#   rather than proving the same thing.
EQUIVALENT = [
    "ss-unreachable-arm-returns-g",
    "h-slack-is-zero",
    "gc-clamp-inclusive",
    "au-down-into-neutral",
]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0
    equivalent_survivors = []
    uncompiled = []

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetrain_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")

        # The ported sources are CRLF and the tools are LF, so a
        # multi-line pattern written with bare newlines misses every
        # time against a source file -- silently, as a pattern that is
        # not found rather than as a mutant that survives.
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-34s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES,
                                          name="drivetrain_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    uncompiled.append(name)
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-34s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-34s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    equivalent_survivors.append(name)
                    print("  %-34s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-34s SURVIVED" % name)
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

    # Count the equivalents that actually survived, not the length of the
    # list. h-slack-is-zero is in the list for a 32-bit host and is caught
    # by the compiler here, and counting it both as caught and as
    # equivalent would make caught + equivalent overshoot the total.
    equiv = [name for name, _, _, _ in MUTATIONS
             if name in EQUIVALENT and name in equivalent_survivors]
    # Any other entry whose mutant was caught is a wrong reason, not a
    # spare one. h-slack-is-zero is only judged by a build that took it:
    # the argument above is for the host where it compiles.
    stale = [n for n in EQUIVALENT
             if n not in equivalent_survivors and n not in missing
             and not (n == "h-slack-is-zero" and n in uncompiled)]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equiv), len(holes)))
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetrain_test")
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
