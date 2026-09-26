"""Cross-check 3DS Files/source/drivetarget.c against the shipped image.

drivetarget_check.py checks the port against a Python model written from
the disassembly. The model and the port are two readings of one listing,
and two readings can share a mistake. FillWithCurrentAcceleration's first
test (0x0020a074..0x0020a088) is `c.lt.s` of 0.75|v| against |a|, then
`bc1f` past StraightLinePredict. Both the model and the port had it
negated, and they agreed. realcontroller_check.py found it because it runs
the image. This checker gives the rest of DriveTarget.obj the same
treatment.

It found a second shared misreading on its first run. StraightLinePredict's
fast arm (0x001c3394) is an inline VU0 normalise ending in
`vmulx.xyzw`, so Velocity's pad lane is divided by |v.xyz| along with the
other three. The model and the port both copied it across unscaled. `fn
slp fast` and `fn slp at1` printed a pad of 17.1520863 from the image and
22 from the port. realcontroller_check runs that image too, but prints
only x, y and z.

**The scenarios are drivetarget_check's, and the model is not.** Every
scenario, every fixture (the `fi` ones included) and every line format is
imported from drivetarget_check unchanged. What changes is underneath
them. Each function the scenarios call is replaced by a wrapper that:

  - writes the Python records into mipsemu at the image's own offsets;
  - calls the shipped function at its address; and
  - reads the records back.

The model's code does not run at all. `PATCH` names every function
drivetarget_check writes from the listing, and an import-time check fails
if it gains one that `PATCH` does not replace. What still runs in Python
is what the harness also does in C: the memsets, the fixtures' stores and
the prints.

The functions covered are:

  - Resample, EstimateScore, CalculateMaxSpeed and GetFirstPoint;
  - InterpolatePoint, ShiftLeft and ShiftRight;
  - both copies, SetPoint and the four AddPointToTarget overloads;
  - Clear, Fill, Blend, Dump and the constructor and destructor;
  - GetAngle, CalculateTime and RecalculateLength;
  - GetRouteAndRoutePoint;
  - the three free functions, and DrivingLocation::IsClear;
  - the static initialiser, which computes MinDistanceToPointSquared.

That is 0x002086f8..0x0020a840 without the two DoSnapshots, plus the
out-of-line copy constructor at 0x001da210.

**STACK-W.** Five sites build a stack bVector3 whose w lane is never
written, then copy all sixteen bytes into the record with lqc2/sqc2:

  - the two narrow AddPointToTargets;
  - the narrow SetPoint;
  - StraightLinePredict's slow arm (its dir); and
  - Blend's `blended`.

On the console those lanes hold whatever the stack held. The port writes
0.0f. Neither value is more faithful than the other, so the lanes must not
be compared.

**Two runs, two poisons.** They are not skipped by position either. A
skip by position would also hide a pad lane the image does compute. So
the transcript is produced twice:

  - Every DriveTarget entry point fills the 8 KB below sp with a poison
    word before its first instruction runs.
  - Each top-level call also fills VU0's registers and ACC with it.
  - The first run uses one poison and the second run another.

A token that differs between the two runs depends on memory nobody
wrote, and the merged transcript shows it as `*`. A `*` matches whatever
the port prints on the index-aligned line. Every other token must be
equal.

The two runs are also checked against each other. A `*` is only allowed
in a pad-lane column, and the pdt and pv3 wrappers record which column
that is for each line they print. A difference anywhere else would mean
the image's control flow or geometry reads garbage, and the run stops and
says so. The count of masked lanes is printed, so a scenario that starts
reaching a new STACK-W site shows up as a changed number.

**The divides are the EE's.** The oracle is `Emu(ieee=True, eediv=True)`.
A division by zero gives FLT_MAX, as on the console, where IEEE gives an
infinity. The run reports which divide sites, if any, took that path. The
port has none of them spelled with ee_div, so any site that does take it
is a disagreement to explain.

**What is not the image:**

  - The Car and CarState are the fields DriveTarget reads, written at
    their PS2 offsets into a zeroed 2016-byte block. car_set zeroes the
    block again, as the harness's memset does.
  - The three routes are 115752-byte zeroed records with RouteNumber at
    +10. TheTrackRouteManager's table at +16 is rewritten from
    drivetarget_check's TRM before every call.
  - WorldTimer and CameraFollowDefaultCar are rewritten from
    drivetarget_check's globals before every call.
  - pPlayer, when set, points at a dummy block. Blend only tests it
    against zero (`lw v0,24(s3) ; bne`).

Usage:

    python tools/drivetarget_image_check.py
    python tools/drivetarget_image_check.py --mutate
    python tools/drivetarget_image_check.py --mutate --only NAME,NAME
    python tools/drivetarget_image_check.py --dump out/drivetarget_image
"""
import argparse
import difflib
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import drivetarget_check as DT
from mipsemu import Emu, SP, f_to_bits, fbits_to

ROOT = DT.ROOT
NL = DT.NL
SOURCES = DT.SOURCES
MUTATIONS = DT.MUTATIONS
HARNESS_HUNG = DT.HARNESS_HUNG
run_harness = DT.run_harness

# ------------------------------------------------------------- the image

SYM = dict(
    ahead="IsPointAheadOfCar__FP8bVector2P3Carf",
    look="CalculateLookAheadDistance__FP3Car",
    slp="StraightLinePredict__FP3CarP11DriveTarget",
    copy="__11DriveTargetRC11DriveTarget",
    init="__11DriveTarget",
    dtor="_$_11DriveTarget",
    assign="__as__11DriveTargetR11DriveTarget",
    angle="GetAngle__11DriveTargeti",
    clear="Clear__11DriveTargetP3Carf",
    interp="InterpolatePoint__11DriveTargetP3CarfP8bVector3",
    add2dl="AddPointToTarget__11DriveTargetP8bVector2P15DrivingLocationbP3Car",
    add3dl="AddPointToTarget__11DriveTargetP8bVector3P15DrivingLocationbP3Car",
    add2="AddPointToTarget__11DriveTargetP8bVector2ScsScbP3Car",
    add3="AddPointToTarget__11DriveTargetP8bVector3ScsScbP3Car",
    first="GetFirstPoint__11DriveTargetP8CarState",
    resample="Resample__11DriveTargetP3Car",
    dump="Dump__11DriveTargetP3Carbi",
    score="EstimateScore__11DriveTargetP3Car",
    maxspeed="CalculateMaxSpeed__11DriveTargetP3CarP8bVector2T2T2ffPf",
    lateral="GetMaxLateralAcceleration__11DriveTargetP3Car",
    time="CalculateTime__11DriveTargetfff",
    fill="FillWithCurrentAcceleration__11DriveTargetP3Car",
    blend="BlendWithCurrentAcceleration__11DriveTargetP3Car",
    sright="ShiftRight__11DriveTargeti",
    sleft="ShiftLeft__11DriveTargetib",
    set2="SetPoint__11DriveTargetiP8bVector2ScsScf",
    set3="SetPoint__11DriveTargetiP8bVector3ScsScf",
    length="RecalculateLength__11DriveTarget",
    route="GetRouteAndRoutePoint__11DriveTargetiPP10TrackRoutePP15TrackRoutePoint",
    isclear="IsClear__15DrivingLocation",
    sinit="_GLOBAL_$I$__11DriveTarget",
)

# DriveTarget.obj's text, from the constructor up to OBB's first method.
OBJ_LO, OBJ_HI = 0x002086F8, 0x0020A840

# The PS2 layouts: drivetarget.h, car.h, carstate.h and trackroute.h all
# state these as CAR_AT / CARSTATE_AT / static asserts on the handheld.
DT_SIZE = 528
CAR_SIZE = 2016
CAR_DRIVER, CAR_PLAYER, CAR_STATE = 10, 24, 64
CS_POS, CS_VEL, CS_ACC = 32, 48, 64
CS_ANGLE, CS_FWD, CS_VMAG, CS_MVALID = 868, 892, 896, 1008
ROUTE_SIZE = 115752
ROUTE_NUMBER, ROUTE_POINTS, POINT_SIZE = 10, 1064, 112
TRM_TABLE = 16          # two bTLists, then pTrackRoutes[100]
N_ROUTES = 100

STACK_TOP = Emu.RAM - 0x10000
SCRUB = 0x2000
CALL_LIMIT = 5000000

# -777.0 and 333.25. Finite, so a garbage lane cannot turn into a NaN
# whose payload the Python float round trip would not keep. They are also
# unlike any fixture's numbers.
POISONS = (0xC4424000, 0x43A6A000)

# The out-pointers GetRouteAndRoutePoint is handed start as this, so a
# path that does not write them shows up instead of reading as null.
UNWRITTEN = 0xDDDDDDDD


class Image(object):
    """One Emu, and the address each Python record lives at inside it."""

    def __init__(self, poison):
        e = self.e = Emu(ieee=True, eediv=True)
        e.stub_bware()
        e.stub("__builtin_delete", self._delete)
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.g_timer = e.addr_of("WorldTimer")
        self.g_camdef = e.addr_of("CameraFollowDefaultCar")
        self.g_minsq = e.addr_of("DriveTargetMinDistanceToPointSquared")
        self.g_trm = e.addr_of("TheTrackRouteManager") + TRM_TABLE
        self.poison = poison
        self.fillb = struct.pack("<I", poison) * (SCRUB // 4)
        self.at = {}            # id(record) -> address
        self.obj = {}           # address -> record
        self.keep = []          # so no id() is ever handed out twice
        self.cars = {}          # id(CarState) -> the Car it sits in
        self.calls = 0

        # The members that never read `this` -- CalculateTime,
        # GetMaxLateralAcceleration, CalculateMaxSpeed -- get a record of
        # their own, and the vectors and outputs get fixed scratch.
        self.this = e.alloc(DT_SIZE, 16)
        self.vec = [e.alloc(16, 16) for _ in range(3)]
        self.outf = e.alloc(16, 16)
        self.loc = e.alloc(16, 16)
        self.outr = e.alloc(16, 16)
        self.player = e.alloc(64, 16)

        for r in (DT.ROUTE_A, DT.ROUTE_B, DT.ROUTE_C):
            a = self.place(r, ROUTE_SIZE)
            struct.pack_into("<h", e.mem, a + ROUTE_NUMBER, r.RouteNumber)

        # Every entry point in the object and the four outside it. A hook
        # runs before the instruction at its address, which is before the
        # frame is allocated, so what it overwrites is below sp and free.
        entries = set(self.fn[k] for k in ("ahead", "look", "slp", "copy"))
        for name, v in e.elf.syms.items():
            if OBJ_LO <= v[0] < OBJ_HI:
                entries.add(v[0])
        for a in entries:
            e.hook(a, self._scrub)

    # ---- plumbing -------------------------------------------------------

    def _scrub(self, e):
        sp = e.reg[SP] & 0xFFFFFFFF
        e.mem[sp - SCRUB:sp] = self.fillb

    def _delete(self, e):
        raise AssertionError("operator delete: no scenario frees a "
                             "DriveTarget")

    def place(self, o, size):
        a = self.at.get(id(o))
        if a is None:
            a = self.e.alloc(size, 16)
            self.e.mem[a:a + size] = bytes(size)
            self.at[id(o)] = a
            self.obj[a] = o
            self.keep.append(o)
        return a

    def sync(self):
        e = self.e
        e.put32(self.g_timer, DT.WORLD_TIMER)
        e.put32(self.g_camdef, DT.CAM_DEFAULT)
        tbl = [0 if r is None else self.at[id(r)] for r in DT.TRM.pTrackRoutes]
        assert len(tbl) == N_ROUTES
        struct.pack_into("<%dI" % N_ROUTES, e.mem, self.g_trm, *tbl)

    def call(self, key, ints=(), floats=()):
        e = self.e
        self.sync()
        e.reg[SP] = STACK_TOP
        e.mem[STACK_TOP - SCRUB:STACK_TOP] = self.fillb
        for i in range(1, 32):
            e.vf[i] = [self.poison] * 4
        e.acc = [self.poison] * 4
        for i, v in enumerate(floats):
            e.fpr[12 + i] = f_to_bits(v)
        self.calls += 1
        r = e.call(self.fn[key], *ints, limit=CALL_LIMIT)
        assert e.reg[SP] & 0xFFFFFFFF == STACK_TOP, "unbalanced stack"
        return r

    def f0(self):
        return fbits_to(self.e.fpr[0])

    # ---- the records ----------------------------------------------------

    def put_dt(self, t):
        a = self.place(t, DT_SIZE)
        m = self.e.mem
        m[a] = t.NumPoints & 0xFF
        m[a + 1:a + 16] = bytes(t.pad0)
        for i in range(DT.MAX_POINTS):
            struct.pack_into("<4f", m, a + 16 + 16 * i, *t.P[i])
        struct.pack_into("<20f", m, a + 336, *t.S)
        struct.pack_into("<20b", m, a + 416, *t.R)
        struct.pack_into("<20h", m, a + 436, *t.RPN)
        struct.pack_into("<20b", m, a + 476, *t.DL)
        struct.pack_into("<ib", m, a + 496, t.TType, t.Pick)
        m[a + 501:a + 504] = bytes(t.pad1)
        struct.pack_into("<iif", m, a + 504, t.CalcT, t.BlendT, t.Length)
        m[a + 516:a + 528] = bytes(t.pad2)
        return a

    def get_dt(self, t):
        a = self.at[id(t)]
        m = self.e.mem
        t.NumPoints = DT.i8(m[a])
        t.pad0 = bytearray(m[a + 1:a + 16])
        t.P = [list(struct.unpack_from("<4f", m, a + 16 + 16 * i))
               for i in range(DT.MAX_POINTS)]
        t.S = list(struct.unpack_from("<20f", m, a + 336))
        t.R = list(struct.unpack_from("<20b", m, a + 416))
        t.RPN = list(struct.unpack_from("<20h", m, a + 436))
        t.DL = list(struct.unpack_from("<20b", m, a + 476))
        t.TType, t.Pick = struct.unpack_from("<ib", m, a + 496)
        t.pad1 = bytearray(m[a + 501:a + 504])
        t.CalcT, t.BlendT, t.Length = struct.unpack_from("<iif", m, a + 504)
        t.pad2 = bytearray(m[a + 516:a + 528])

    def put_car(self, c):
        if c is None:
            return 0
        a = self.place(c, CAR_SIZE)
        self.cars[id(c.State)] = c
        m = self.e.mem
        s = c.State
        b = a + CAR_STATE
        struct.pack_into("<h", m, a + CAR_DRIVER, c.DriverNumber)
        struct.pack_into("<I", m, a + CAR_PLAYER,
                         0 if c.pPlayer is None else self.player)
        struct.pack_into("<4f", m, b + CS_POS, *s.Position)
        struct.pack_into("<4f", m, b + CS_VEL, *s.Velocity)
        struct.pack_into("<4f", m, b + CS_ACC, *s.Acceleration)
        struct.pack_into("<H", m, b + CS_ANGLE, s.Angle & 0xFFFF)
        struct.pack_into("<ff", m, b + CS_FWD, s.ForwardSpeed,
                         s.VelocityMagnitude)
        struct.pack_into("<i", m, b + CS_MVALID, s.MatrixValid)
        return a

    def get_car(self, c):
        if c is None:
            return
        a = self.at[id(c)]
        m = self.e.mem
        s = c.State
        b = a + CAR_STATE
        c.DriverNumber = struct.unpack_from("<h", m, a + CAR_DRIVER)[0]
        s.Position = list(struct.unpack_from("<4f", m, b + CS_POS))
        s.Velocity = list(struct.unpack_from("<4f", m, b + CS_VEL))
        s.Acceleration = list(struct.unpack_from("<4f", m, b + CS_ACC))
        s.Angle = struct.unpack_from("<H", m, b + CS_ANGLE)[0]
        s.ForwardSpeed, s.VelocityMagnitude = struct.unpack_from(
            "<ff", m, b + CS_FWD)
        s.MatrixValid = struct.unpack_from("<i", m, b + CS_MVALID)[0]

    def zero_car(self, c):
        a = self.place(c, CAR_SIZE)
        self.cars[id(c.State)] = c
        self.e.mem[a:a + CAR_SIZE] = bytes(CAR_SIZE)

    def put_loc(self, loc):
        r = 0 if loc.pRoute is None else self.at[id(loc.pRoute)]
        p = 0
        if loc.pRoutePoint is not None:
            # Every point a scenario names is in ROUTE_B's table, which is
            # where the harness takes its &gRouteB.TrackRoutePointTable[n].
            p = (self.at[id(DT.ROUTE_B)] + ROUTE_POINTS
                 + POINT_SIZE * loc.pRoutePoint)
        struct.pack_into("<IIb3x", self.e.mem, self.loc, r, p,
                         loc.DrivingLine)
        return self.loc

    def put_vec(self, k, v):
        struct.pack_into("<%df" % len(v), self.e.mem, self.vec[k], *v)
        return self.vec[k]

    # ---- the functions, with drivetarget_check's signatures ----------------

    def is_point_ahead_of_car(self, p, car, thresh):
        v = self.put_vec(0, p[:2])
        c = self.put_car(car)
        r = self.call("ahead", (v, c), (thresh,))
        self.get_car(car)
        return r

    def calculate_look_ahead_distance(self, car):
        c = self.put_car(car)
        self.call("look", (c,))
        self.get_car(car)
        return self.f0()

    def straight_line_predict(self, car, t):
        c = self.put_car(car)
        a = self.put_dt(t)
        self.call("slp", (c, a))
        self.get_car(car)
        self.get_dt(t)

    def init(self, t):
        a = self.put_dt(t)
        r = self.call("init", (a,))
        self.get_dt(t)
        return self.obj[r & 0xFFFFFFFF]

    def destroy(self, t):
        a = self.put_dt(t)
        self.call("dtor", (a, 0))
        self.get_dt(t)
        return t

    def assign(self, dst, src):
        a = self.put_dt(dst)
        b = self.put_dt(src)
        r = self.call("assign", (a, b))
        self.get_dt(dst)
        self.get_dt(src)
        return self.obj[r & 0xFFFFFFFF]

    def copy_ctor(self, dst, src):
        a = self.put_dt(dst)
        b = self.put_dt(src)
        self.call("copy", (a, b))
        self.get_dt(dst)
        self.get_dt(src)
        return dst

    def same_bytes(self, a, b):
        """The harness's memcmp, over the two records as the image holds
        them."""
        x, y = self.put_dt(a), self.put_dt(b)
        m = self.e.mem
        return 1 if m[x:x + DT_SIZE] == m[y:y + DT_SIZE] else 0

    def get_angle(self, t, i):
        a = self.put_dt(t)
        r = self.call("angle", (a, i))
        self.get_dt(t)
        return r

    def calculate_time(self, a, b, c):
        self.call("time", (self.this,), (a, b, c))
        return self.f0()

    def get_max_lateral_acceleration(self):
        self.call("lateral", (self.this, 0))
        return self.f0()

    def recalculate_length(self, t):
        a = self.put_dt(t)
        self.call("length", (a,))
        self.get_dt(t)

    def get_route_and_route_point(self, t, i):
        a = self.put_dt(t)
        m = self.e.mem
        struct.pack_into("<II", m, self.outr, UNWRITTEN, UNWRITTEN)
        rc = self.call("route", (a, i, self.outr, self.outr + 4))
        self.get_dt(t)
        rp, pp = struct.unpack_from("<II", m, self.outr)
        if UNWRITTEN in (rp, pp):
            raise AssertionError("GetRouteAndRoutePoint(%d) left an out "
                                 "pointer unwritten" % i)
        route = None if rp == 0 else self.obj[rp]
        point = None
        if pp:
            off = pp - rp - ROUTE_POINTS
            assert rp and off % POINT_SIZE == 0, (rp, pp)
            point = off // POINT_SIZE
        return rc, route, point

    def get_first_point(self, t, cs):
        car = self.cars[id(cs)]
        a = self.put_dt(t)
        c = self.put_car(car)
        r = self.call("first", (a, c + CAR_STATE))
        self.get_dt(t)
        self.get_car(car)
        return r

    def set_point3(self, t, i, p, route, rpn, dl, speed):
        a = self.put_dt(t)
        v = self.put_vec(0, p)
        self.call("set3", (a, i, v, route, rpn, dl), (speed,))
        self.get_dt(t)

    def set_point2(self, t, i, p, route, rpn, dl, speed):
        a = self.put_dt(t)
        v = self.put_vec(0, p[:2])
        self.call("set2", (a, i, v, route, rpn, dl), (speed,))
        self.get_dt(t)

    def shift_right(self, t, n):
        a = self.put_dt(t)
        self.call("sright", (a, n))
        self.get_dt(t)

    def shift_left(self, t, n, recalc):
        a = self.put_dt(t)
        self.call("sleft", (a, n, recalc))
        self.get_dt(t)

    def add_point3(self, t, p, route, rpn, dl, check, car):
        a = self.put_dt(t)
        v = self.put_vec(0, p)
        c = self.put_car(car)
        self.call("add3", (a, v, route, rpn, dl, check, c))
        self.get_dt(t)
        self.get_car(car)

    def add_point2(self, t, p, route, rpn, dl, check, car):
        a = self.put_dt(t)
        v = self.put_vec(0, p[:2])
        c = self.put_car(car)
        self.call("add2", (a, v, route, rpn, dl, check, c))
        self.get_dt(t)
        self.get_car(car)

    def add_point3_dl(self, t, p, loc, check, car):
        a = self.put_dt(t)
        v = self.put_vec(0, p)
        c = self.put_car(car)
        self.call("add3dl", (a, v, self.put_loc(loc), check, c))
        self.get_dt(t)
        self.get_car(car)

    def add_point2_dl(self, t, p, loc, check, car):
        a = self.put_dt(t)
        v = self.put_vec(0, p[:2])
        c = self.put_car(car)
        self.call("add2dl", (a, v, self.put_loc(loc), check, c))
        self.get_dt(t)
        self.get_car(car)

    def interpolate_point(self, t, car, dist, out):
        a = self.put_dt(t)
        c = self.put_car(car)
        struct.pack_into("<4f", self.e.mem, self.outf, *out)
        r = self.call("interp", (a, c, self.outf), (dist,))
        self.get_dt(t)
        self.get_car(car)
        out[:] = struct.unpack_from("<4f", self.e.mem, self.outf)
        return r

    def clear(self, t, car, speed):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("clear", (a, c), (speed,))
        self.get_dt(t)
        self.get_car(car)

    def resample(self, t, car):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("resample", (a, c))
        self.get_dt(t)
        self.get_car(car)

    def calculate_max_speed(self, car, p0, p1, p2, dist, speed, out):
        c = self.put_car(car)
        v0 = self.put_vec(0, p0[:2])
        v1 = self.put_vec(1, p1[:2])
        v2 = self.put_vec(2, p2[:2])
        struct.pack_into("<f", self.e.mem, self.outf, out)
        r = self.call("maxspeed", (self.this, c, v0, v1, v2, self.outf),
                      (dist, speed))
        self.get_car(car)
        return r, struct.unpack_from("<f", self.e.mem, self.outf)[0]

    def estimate_score(self, t, car):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("score", (a, c))
        self.get_dt(t)
        self.get_car(car)
        return self.f0()

    def fill_with_current_acceleration(self, t, car):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("fill", (a, c))
        self.get_dt(t)
        self.get_car(car)

    def blend_with_current_acceleration(self, t, car):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("blend", (a, c))
        self.get_dt(t)
        self.get_car(car)

    def dump(self, t, car, check_camera):
        a = self.put_dt(t)
        c = self.put_car(car)
        self.call("dump", (a, c, check_camera, 0))
        self.get_dt(t)
        self.get_car(car)

    def static_init(self):
        self.call("sinit")
        DT.MIN_DIST_SQ = fbits_to(self.e.u32(self.g_minsq))

    def is_clear(self, loc):
        return self.call("isclear", (self.put_loc(loc),))

    # The one fixture with a side the image has to see: the harness's
    # car_set is a memset of the whole Car before the stores.
    def car_set(self, c, *args):
        ORIG["car_set"](c, *args)
        self.zero_car(c)


# Everything drivetarget_check models from the listing, plus the harness's
# memcmp and the car fixture's memset.
PATCH = [
    "is_point_ahead_of_car", "calculate_look_ahead_distance",
    "straight_line_predict", "init", "destroy", "assign", "copy_ctor",
    "same_bytes", "get_angle", "calculate_time",
    "get_max_lateral_acceleration", "recalculate_length",
    "get_route_and_route_point", "get_first_point", "set_point3",
    "set_point2", "shift_right", "shift_left", "add_point3", "add_point2",
    "add_point3_dl", "add_point2_dl", "interpolate_point", "clear",
    "resample", "calculate_max_speed", "estimate_score",
    "fill_with_current_acceleration", "blend_with_current_acceleration",
    "dump", "static_init", "is_clear", "car_set",
]
ORIG = {n: getattr(DT, n) for n in PATCH + ["pdt", "pv3"]}


def _modelled():
    """drivetarget_check's functions whose docstring opens by citing the
    image address they were written from."""
    rx = re.compile(r"0x00[0-9a-f]{6}")
    out = []
    for name, f in vars(DT).items():
        if callable(f) and getattr(f, "__module__", None) == DT.__name__ \
                and not isinstance(f, type) and f.__doc__ \
                and rx.search(f.__doc__.strip().splitlines()[0]):
            out.append(name)
    return out


_missing = sorted(set(_modelled()) - set(PATCH))
assert not _missing, "model functions this checker does not replace: %s" \
    % _missing


# ----------------------------------------------------------- the transcript

# Line index -> the space-split column the pad lane prints in, filled by
# the pdt and pv3 wrappers as they print.
PADTOK = {}
SLOT = re.compile(r"\[\d\d\]")


def pdt(tag, t, n):
    start = len(DT.OUT)
    ORIG["pdt"](tag, t, n)
    for i in range(start + 1, len(DT.OUT)):
        toks = DT.OUT[i].split(" ")
        k = next(j for j, x in enumerate(toks) if SLOT.fullmatch(x))
        PADTOK[i] = k + 4


def pv3(tag, v):
    ORIG["pv3"](tag, v)
    PADTOK[len(DT.OUT) - 1] = len(DT.OUT[-1].split(" ")) - 1


def image_run(poison):
    img = Image(poison)
    PADTOK.clear()
    try:
        for n in PATCH:
            setattr(DT, n, getattr(img, n))
        DT.pdt, DT.pv3 = pdt, pv3
        lines = DT.model()
    finally:
        for n, f in ORIG.items():
            setattr(DT, n, f)
    return lines, dict(PADTOK), img


class Garbage(Exception):
    pass


def merge(a, b, padtok):
    """The two poisoned runs, as one transcript with `*` for every token
    that differs between them. Only a pad lane may."""
    if len(a) != len(b):
        raise Garbage("the two poisoned runs printed %d and %d lines: the "
                      "image's control flow reads unwritten memory"
                      % (len(a), len(b)))
    out, masked, stray = [], [], []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            out.append(x)
            continue
        tx, ty = x.split(" "), y.split(" ")
        if len(tx) != len(ty):
            stray.append((i, x, y))
            out.append(x)
            continue
        row = []
        for j, (u, v) in enumerate(zip(tx, ty)):
            if u == v:
                row.append(u)
            elif padtok.get(i) == j:
                row.append("*")
                masked.append(i)
            else:
                row.append(u)
                stray.append((i, x, y))
        out.append(" ".join(row))
    if stray:
        msg = ["a non-pad token depends on unwritten memory:"]
        for i, x, y in stray[:10]:
            msg.append("  %d: %s" % (i, x))
            msg.append("  %d: %s" % (i, y))
        raise Garbage(NL.join(msg))
    return out, masked


def image_model(verbose=False):
    a, padtok, ia = image_run(POISONS[0])
    b, _, ib = image_run(POISONS[1])
    lines, masked = merge(a, b, padtok)
    info = dict(calls=ia.calls, masked=masked,
                eediv=sorted(ia.e.eediv_pcs | ib.e.eediv_pcs))
    if verbose:
        tags = {}
        for i in masked:
            tag = lines[i].split(" [")[0]
            tags[tag] = tags.get(tag, 0) + 1
        print("%d image calls per run, %d pad lanes masked as STACK-W"
              % (ia.calls, len(masked)))
        for tag in sorted(tags):
            print("  %-24s %d" % (tag, tags[tag]))
        if info["eediv"]:
            print("divides that took the EE's zero-divisor path: %s"
                  % " ".join("%08x" % p for p in info["eediv"]))
    return lines, info


def unmask(img, port):
    """A `*` matches whatever the port printed in that column, on a line
    whose every other token is the same."""
    out = []
    for i, x in enumerate(img):
        tx = x.split(" ")
        if "*" in tx and i < len(port):
            tp = port[i].split(" ")
            if len(tp) == len(tx) and all(u == "*" or u == v
                                          for u, v in zip(tx, tp)):
                out.append(port[i])
                continue
        out.append(x)
    return out


def diff(img, port, quiet=False):
    d = list(difflib.unified_diff(unmask(img, port), port, "image", "port",
                                  lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


# ------------------------------------------------------------ the mutations

# drivetarget_check's arguments are about the port's source and still
# hold. The ones added here are the mutants that only this checker lets
# live, and why.
EQUIVALENT = dict(DT.EQUIVALENT)
EQUIVALENT.update({
})

_unknown = sorted(set(EQUIVALENT) - set(m[0] for m in MUTATIONS))
assert not _unknown, "EQUIVALENT names no mutation uses: %s" % _unknown

write_source = hostbuild.write_source


def mutate_pass(only=None):
    base, _ = image_model()
    survived, missing, caught = [], [], 0
    equivalent_survivors = []

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetarget_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        if only is not None and name not in only:
            continue
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")

        # The ported sources are CRLF and the tools are LF; a pattern
        # written with bare newlines would miss every CRLF file silently.
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
                                          name="drivetarget_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-34s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-34s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
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

    real = [m for m in MUTATIONS
            if m[0] not in missing and (only is None or m[0] in only)]
    holes = [s for s in survived if s not in EQUIVALENT]
    # Judged from the survivors, so a listed mutant that failed to compile,
    # crashed or hung counts as caught here too, not only one the diff saw.
    argued_but_caught = [n for n in EQUIVALENT
                         if n not in equivalent_survivors
                         and n not in missing
                         and (only is None or n in only)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of them"
              % (len(missing), len(real)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent_survivors), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    # An argument for a mutant the image then tells apart is an argument
    # that was wrong, or a port that is not the image. Either way, say so.
    for name in argued_but_caught:
        print("  argued equivalent, but caught: %s" % name)
    return 1 if (holes or missing or argued_but_caught) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAMES",
                    help="comma-separated mutation names to run alone")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        only = set(args.only.split(",")) if args.only else None
        if only:
            unknown = sorted(only - set(m[0] for m in MUTATIONS))
            if unknown:
                print("no such mutation: %s" % ", ".join(unknown))
                sys.exit(2)
        sys.exit(mutate_pass(only))

    lines, info = image_model(verbose=True)
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="drivetarget_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        port = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.mkdir(parents=True, exist_ok=True)
        (d / "image.txt").write_text(NL.join(lines) + NL)
        (d / "port.txt").write_text(NL.join(port) + NL)
        print("wrote %s" % d)

    n = diff(lines, port)
    print("%d scenarios, %d lines, %d pad lanes masked, %d differ"
          % (len(DT.SCENARIOS), len(lines), len(info["masked"]), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
