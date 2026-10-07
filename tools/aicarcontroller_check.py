#!/usr/bin/env python3
"""Cross-check 3DS Files/source/aicarcontroller.c -- the AI car controller,
step 11e-1's part of it -- against the retail image, run in mipsemu.

The model is retail's image, over drivingchoice_check.py's world: its cars,
routes, signs, list and test tables, its stubs and every one of its ops,
which this checker's script uses too. On top of them come the '%' ops,
which build a controller in place of a car's own (CTRLS + 0x400 k) and
call its methods as shipped: the constructor and destructor,
SetCurrentRoute, GetCurrentRoute and GetCurrentRoutePoint with and without
the find, GetAmountOutOfBounds, FindWhereIAm, FindClosestTrackRoute,
GetNewDrivingLine, JustReset, GetMyDriverNumber, ClearStickyDecisions,
SteerStraightAhead, ChooseNewAction, InterruptAction,
GeneratePointsToFulfillAction, GetCurrentActionType,
ForceMyCurrentAction, SetToPhysicsMode (and CarController's, which the
port now takes from retail), GetCurrentDrivingLineSpeed, ForceBoost,
ReleaseBoost, AboutToFly, SetOffBeltTimer, the exclusion's get and set,
GetCurrentDrivingLocation and DebugDisplay. Under them everything the port
has runs as shipped too: the Average's constructor and destructor,
Signpost::GetIndex, the route manager's table, DistanceIsWithinRoute,
FindClosestPoint, GetPosition, the DrivingLocation, DrivingChoice and
DrivingInformation methods, IsDriveable and all beneath it,
GetCarAhead and HighlightDrivingLine.

**The stand-ins**, each printing a line, so both sides must ask the same
questions in the same order:
  bMalloc (0x002577c0): a block of 64 bytes, filled with 0xa5, named m0,
    m1, ... in the order asked for, with the size, name, flags and pool
    printed (the port's Average record, 24 bytes on a 64-bit host, prints
    as retail's 16);
  bFree (0x00257850), which __builtin_delete jumps to: the block's name;
  Car::SetMovementMode (0x00131618): the car and the mode, which it sets;
  a test CarDriver table at DVT, drivingchoice_check's, with
    SetSteerToPoint (72) and ZeroSteeringMemory (120) added;
  a test controller table at TVT: retail's _vt$15AICarController with
    GetRouteNumbersToUse (112, pure in retail) answering the script's
    first and last route numbers and ChooseNewAction (120) the script's
    queue of fake actions;
  the fake actions, in a table at AVT whose destructor (8) and
    CalculatePointsToDrive (24) print, the second setting the action's
    PointsToDriveWillExecuteAction to the script's answer;
  drivingchoice_check's controller table at CVT, which every car the "C"
    op sets up has, now with GetCurrentRoutePoint (56) and
    GetAmountOutOfBounds (64) answering the script's point and amount: the
    model no longer stubs Car::GetRoutePoint and GetAmountOutOfBounds, which
    reach a built controller's own methods through its table.

A float prints as its bits, a NaN as "nan", and a pointer by what it is,
as drivingchoice_check names them, with these added: kn3, kl3 and kc3 car
3's controller's own list, location and choice, ke3:5 its list's sixth
entry, m4 the fifth block bMalloc handed out and fa2 the third fake
action. vK is _vt$15AICarController, vT the test table, vC
drivingchoice_check's, vB _vt$13CarController and vF the actions'.

    python tools/aicarcontroller_check.py
    python tools/aicarcontroller_check.py --mutate [--only a,b]
    python tools/aicarcontroller_check.py --dump out/aicarcontroller
"""
import argparse
import math
import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drivingchoice_check as dcc
import mutpar
from drivingchoice_check import (CARS, CAR_STRIDE, CTRLS, CTRL_STRIDE,
                                 CDRIVERS, CDRIVER_STRIDE, NCARS, PLAYERS,
                                 PLAYER_STRIDE, LIST, LOC, CHOICE, SIGNS,
                                 SIGN_SIZE, GLOBALS, DVT, CVT, PATTERN, LINES,
                                 car_at, route_at, h, f32, fb, fx, s8,
                                 World, walk_world, place_me, place_other,
                                 seen_list, decide, boxed, heading_of)
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/aicarcontroller_test.c"
AICC = "3DS Files/source/aicarcontroller.c"
CCC = "3DS Files/source/carcontroller.c"
SOURCES = [HARNESS] + dcc.SOURCES[1:] + ["3DS Files/source/" + f for f in (
    "aicarcontroller.c", "carcontroller.c", "average.c", "timer.c")]

# ================================================================ the image

AICC_VTABLE = 0x002b4d90          # _vt$15AICarController
CC_VTABLE = 0x002b7218            # _vt$13CarController
AICC_VT_BYTES = 17 * 8
NDMM = 0x0032ff40                 # nDefaultMovementMode, gp-22960

F = {
    "ctor": 0x00190140, "dtor": 0x001903a0, "sr": 0x00190670,
    "gr": 0x00190708, "gp": 0x00190760, "oob": 0x001907b8,
    "jr": 0x00190850, "dn": 0x001908f0, "fc": 0x00190900,
    "af": 0x00191130, "dd": 0x00191138, "cs": 0x00191d10,
    "gl": 0x00192488, "gpf": 0x00192668, "cn": 0x00192780,
    "ia": 0x00192788, "st": 0x00192848, "fw": 0x00192f10,
    "pm": 0x00193650, "ls": 0x001936f0, "fb": 0x00193758,
    "rb": 0x00193780, "gx": 0x00193fe0, "ex": 0x00193fe8,
    "gdl": 0x00193ff8, "cat": 0x00194000, "force": 0x00194020,
    "ob": 0x00194028, "cc": 0x001c0100,
}
BMALLOC = 0x002577c0
BFREE = 0x00257850
SET_MOVEMENT = 0x00131618

# The checker's own memory, past drivingchoice_check's.
STUB_SSTP = 0x010b3430
STUB_ZSM = 0x010b3440
STUB_RNUM = 0x010b3450
STUB_CHOOSE = 0x010b3460
STUB_ADEL = 0x010b3470
STUB_ACP = 0x010b3480
STUB_CRP = 0x010b3490
STUB_COOB = 0x010b34a0
HEAP = 0x010c0000
HEAP_BLOCK = 64
NHEAP = 16
TVT = 0x010c2100                  # the harness's addresses for the two
AVT = 0x010c2200                  # test tables
AVT_BYTES = 8 * 8
LINEVAR = 0x010c2400
OUTP = 0x010c2410
FACTS = 0x010c3000
FACT_SIZE = 608
NFACTS = 8

# The controller, by retail's offsets.
K_SIZE = 720
K_DRIVER, K_VPTR, K_LIST, K_ILOC, K_ICH = 4, 8, 12, 476, 492
K_LOC, K_CHOICE, K_NLIST, K_EXCLUDE = 504, 508, 512, 516
K_LTR, K_SECS, K_FORCE, K_ACTION = 520, 524, 528, 532
K_TIMERS = (536, 544, 552, 556, 564, 568, 572, 576, 592, 596, 688)
K_LA, K_POT, K_BS, K_PROG, K_LP, K_GLUE = 540, 548, 560, 580, 584, 588
K_GR, K_GB, K_GD, K_BOOST, K_CP, K_SIGN = 600, 604, 608, 640, 644, 648
K_STICKY, K_TS, K_DLS, K_VP = 652, 684, 692, 704
K_OB, K_RP = 568, 572
NSTICKY = 8
LIST_BYTES = 464
LIST_HL, LIST_HD = 456, 460
NC_SIZE = 28

# A fake action's vptr, answer, type and score.
A_VPTR, A_PT, A_TYPE, A_SCORE = 16, 560, 588, 592

# The car's.
C_INDEX, C_PLAYER, C_MODE = 8, 24, 36
C_BOOST, C_ANGLE, C_DIST = 992, 932, 2036
C_POS = 96

# A route's distances and box, and a sign's distance.
R_START, R_END, R_BMIN, R_BMAX = 32, 36, 1048, 1056
S_DIST = 4

VT_NAMES = {AICC_VTABLE: "vK", TVT: "vT", CVT: "vC", CC_VTABLE: "vB",
            AVT: "vF"}
PAT32 = PATTERN * 0x01010101

AIACTION_NONE = 11
PHYSICS, MELLOW, BELT = 1, 4, 6


def ctrl_at(k):
    return CTRLS + CTRL_STRIDE * k


def fact_at(i):
    return FACTS + FACT_SIZE * i if i >= 0 else 0


# ============================================================ the scenarios
#
# drivingchoice_check's ops, and these. Set up, and echoed:
# %d k dist              car k's distance around the track
# %S i dist              sign i's distance
# %NS n                  NumSignposts
# %U k s e x0 y0 x1 y1   route k's start and end distances and its box
# %a k angle             car k's angle, a bam
# %mm k mode             car k's movement mode
# %pl k p                car k's player, or none
# %bf k f                car k's BoostFactor
# %ci k i                car k's CarIndex
# %pos k x y z           car k's position
# %vp k x y z w          controller k's vPreviousLinePoint
# %cp k k2               route k's points copied over route k2's, but for
#                        each point's own route number, so that the two
#                        tie for closest
# %G mode                nDefaultMovementMode
# %v k i                 controller k's vptr: vK, vT or vC
# %dr k                  controller k's driver: car k's CarDriver
# %J k                   the list, the location and the choice copied
#                        into controller k's own
# %L k r j line t        what controller k's location points at, set
# %ch k type car x       what its choice points at, set
# %sk k w0 .. w7         its sticky decisions
# %rn k first last       what GetRouteNumbersToUse answers for it
# %q a0 a1 ..            ChooseNewAction's answers, in turn (-1 NULL)
# %fa i type score pt p0 fake action i: its type and score, what its
#                        CalculatePointsToDrive answers and its answer now
# %cur k i               controller k's CurrentAction (-1 NULL)
#
# The calls, each on controller k (a car's own, in place):
# %n k                   filled with 0xa5, then built for car k
# %x k flags             destroyed
# %K k                   dumped
# %sr k r j              SetCurrentRoute
# %gr k find / %gp k find  GetCurrentRoute / GetCurrentRoutePoint
# %oob k                 GetAmountOutOfBounds
# %fw k                  FindWhereIAm
# %fc k first last       FindClosestTrackRoute
# %gl k r j relaxed hl   GetNewDrivingLine, its line filled with 0xa5;
#                        hl -1 NULL, 0 the location, 1 its own
# %jr k                  JustReset
# %dn k                  GetMyDriverNumber
# %cs k                  ClearStickyDecisions
# %st k                  SteerStraightAhead
# %cn k type             ChooseNewAction, its out NULL
# %ia k                  InterruptAction
# %gpf k i               GeneratePointsToFulfillAction with fake action i
# %cat k / %force k type GetCurrentActionType / ForceMyCurrentAction
# %pm k car / %cc k car  SetToPhysicsMode / CarController's
# %ls k / %seam k        GetCurrentDrivingLineSpeed, direct and through
#                        the port's seam
# %fb k f / %rb k        ForceBoost / ReleaseBoost
# %af k t / %ob k secs   AboutToFly / SetOffBeltTimer
# %ex k car / %gx k      the car to exclude, set / got
# %gdl k / %dd k         GetCurrentDrivingLocation / DebugDisplay
#
# Not scripted: a find on a controller whose table is vK and whose
# location is clear (retail's slot 112 is __pure_virtual), a route number
# over 99 (retail reads on past the manager's table), FindClosestTrackRoute
# finding a route through vC (whose SetCurrentRoute is no one's), and
# GeneratePointsToFulfillAction's second CalculatePointsToDrive on a NULL
# action.

# Distances either side of the ones that matter.
SECS = (0.0, 0.5, 1.5, 2.0, 3.0, -1.0, 0.000125, 0.0001, 1e6, 1e9, -1e9,
        f32(0.1))
ANGLES = (0, 1, 0x4000, 0x8000, 0xc000, 0xffff, 12345)
INDICES = (0, 1, 7, 15, -1, 140, 32767, -32768)


def sign_ops(rnd, n):
    """n signs at rising distances, now and then two at one, and their
    count."""
    ds = []
    d = rnd.uniform(-50.0, 100.0)
    for _ in range(n):
        ds.append(f32(d))
        if rnd.random() > 0.2:
            d += rnd.uniform(1.0, 400.0)
    ops = ["%%S %d %s" % (i, h(v)) for i, v in enumerate(ds)]
    ops.append("%%NS %d" % n)
    return ops, ds


def dist_near(rnd, ds):
    """A distance around the track before, at, between or past the
    signs, or a NaN."""
    c = rnd.randrange(8)
    if not ds or c == 0:
        return h(f32(rnd.uniform(-100.0, 3000.0)))
    if c == 1:
        return h(ds[0] - 1.0)
    if c in (2, 3):
        return h(rnd.choice(ds))
    if c == 4:
        return h(ds[-1] + 1.0)
    if c == 5:
        return "7fc00000"
    i = rnd.randrange(len(ds))
    return h(f32(ds[i] + rnd.choice((-0.001, 0.001, -2.0, 2.0))))


def s_build(rnd):
    """The constructor over signs and a car's distance and index, the
    small methods, and the destructor with and without an action."""
    w = World(rnd)
    ops = []
    n = rnd.choice((0, 1, 2, 3, 8, 32))
    so, ds = sign_ops(rnd, n)
    ops += so
    ks = rnd.sample(range(4), rnd.choice((1, 2, 3)))
    for k in ks:
        w.car(k, pl=rnd.choice((0, 0, 1)))
    ops = w.ops + ops
    nfacts = rnd.randrange(1, 4)
    for i in range(nfacts):
        ops.append("%%fa %d %d %d %d %d" % (
            i, rnd.choice((0, 2, 5, 11, -1)), rnd.randrange(0, 700),
            rnd.choice((0, 1)), rnd.choice((0, 1))))
    for k in ks:
        ops.append("%%d %d %s" % (k, dist_near(rnd, ds)))
        ops.append("%%ci %d %d" % (k, rnd.choice(INDICES)))
        ops.append("%%n %d" % k)
        ops.append("%%dr %d" % k)
    for _ in range(rnd.randrange(6, 16)):
        k = rnd.choice(ks)
        c = rnd.randrange(17)
        if c == 0:
            ops.append("%%dn %d" % k)
        elif c == 1:
            ops.append("%%sk %d %s" % (k, " ".join(
                "%08x" % rnd.choice((0, 1, 2, 3, 0xffffffff,
                                     rnd.getrandbits(32)))
                for _ in range(NSTICKY))))
            ops.append("%%cs %d" % k)
        elif c == 2:
            ops.append("%%cur %d %d" % (k, rnd.randrange(-1, nfacts)))
            ops.append("%%cat %d" % k)
        elif c == 3:
            ops.append("%%force %d %d" % (k, rnd.choice((0, 2, 5, 10, 11))))
        elif c == 4:
            ops.append("%%ex %d %d" % (k, rnd.choice((-1, 0, 1, 2, 3))))
            ops.append("%%gx %d" % k)
        elif c == 5:
            ops.append("%%gdl %d" % k)
            ops.append("%%dd %d" % k)
        elif c == 6:
            ops.append("%%af %d %s" % (k, h(f32(rnd.uniform(-2.0, 5.0)))))
        elif c == 7:
            ops.append("%%ob %d %s" % (k, h(f32(rnd.choice(SECS)))))
        elif c == 8:
            ops.append("%%bf %d %s" % (k, h(f32(rnd.uniform(0.5, 3.0)))))
            ops.append("%%fb %d %s" % (k, h(f32(rnd.choice(
                (0.0, 1.0, 1.5, 2.0, -1.0))))))
        elif c == 9:
            ops.append("%%rb %d" % k)
        elif c == 10:
            ops.append("%%a %d %d" % (k, rnd.choice(ANGLES)))
            ops.append("%%st %d" % k)
        elif c == 11:
            ops.append("%%d %d %s" % (k, dist_near(rnd, ds)))
            ops.append("%%ci %d %d" % (k, rnd.choice(INDICES)))
            # Sticky decisions in use and a previous line point, which
            # JustReset clears.
            if rnd.random() < 0.6:
                ops.append("%%sk %d %s" % (k, " ".join(
                    "%08x" % rnd.choice((1, 3, 0xffffffff,
                                         rnd.getrandbits(32)))
                    for _ in range(NSTICKY))))
            if rnd.random() < 0.6:
                ops.append("%%vp %d %s" % (k, " ".join(
                    h(f32(rnd.uniform(-500.0, 500.0))) for _ in range(4))))
            ops.append("%%jr %d" % k)
        elif c in (12, 13):
            ops += physics_ops(rnd, k, ks)
        elif c == 14:
            # CarController's: on my car, whichever car it is handed.
            other = rnd.choice([-1, k, k] + ks)
            for j in sorted({k, other} - {-1}):
                ops.append("%%mm %d %d" % (j, rnd.choice((0, 1, 2, 3, 4, 5,
                                                          6))))
                ops.append("%%pl %d %d" % (j, rnd.choice((0, 1))))
            ops.append("%%cc %d %d" % (k, other))
        elif c == 15:
            ops.append("%%cn %d %d" % (k, rnd.choice((0, 2, 11))))
        else:
            ops.append("%%K %d" % k)
    for k in ks:
        ops.append("%%cur %d %d" % (k, rnd.randrange(-1, nfacts)))
        ops.append("%%x %d %d" % (k, rnd.choice((0, 1, 2, 3))))
    return ops


def physics_ops(rnd, k, ks):
    """SetToPhysicsMode from each movement mode, for my car, another or
    none, a player's or not, over each default mode."""
    other = rnd.choice([-1, k] + list(ks))
    return ["%%G %d" % rnd.choice((4, 4, 1, 6, 0, 2)),
            "%%mm %d %d" % (k, rnd.choice((0, 1, 2, 3, 4, 5, 6, 6))),
            "%%pl %d %d" % (other if other >= 0 else k,
                            rnd.choice((0, 1))),
            "G TIMER %08x" % rnd.choice((0, 1000, 0x7fffffff)),
            "%%pm %d %d" % (k, other)]


def number_zero(w):
    """Route 0 filed under number 0, the first slot FindClosestTrackRoute
    takes past its `bltz`, its signs with it."""
    old = w.rn[0]
    if 0 in w.rn.values():
        return
    for i, op in enumerate(w.ops):
        f = op.split()
        if f[0] == "U" and f[1] == "0":
            f[3] = "0"
        elif f[0] == "K" and f[2] == str(old):
            f[2] = "0"
        else:
            continue
        w.ops[i] = " ".join(f)
    w.rn[0] = 0
    for p in w.pts[0]:
        p["rn"] = 0


def route_world(rnd):
    """drivingchoice_check's walk world with its signs and decisions, my
    car (0) near a route and a few more about, their targets, the list,
    and my controller built, its table the test one."""
    w = World(rnd)
    sizes = walk_world(rnd, w, nsigns=rnd.choice((0, 2, 4)))
    if rnd.random() < 0.25:
        number_zero(w)
    w.ops += decide(rnd, w)
    kr = rnd.randrange(5)
    j0 = rnd.randrange(sizes[kr] - 4)
    line = rnd.randrange(LINES)
    place_me(rnd, w, 0, kr, j0, line,
             dn=rnd.choice((0, 1, 5)), pl=rnd.choice((0, 0, 1)))
    # Every car has a box: WillIHitThisCar reads both cars'.
    boxed(rnd, w, 0)
    others = []
    for k in range(1, rnd.choice((1, 2, 3, 4))):
        place_other(rnd, w, sizes, k, rnd.randrange(5),
                    rnd.randrange(sizes[0] // 2), span=10)
        boxed(rnd, w, k)
        others.append(k)
    w.ops += seen_list(rnd, w, others)
    w.ops.append("G CAM %08x" % rnd.choice((M32, 0, 1, 5, 0)))
    w.ops.append("G NLINES %08x" % rnd.choice((3, 3, 1, 0, 2, 4)))
    if rnd.random() < 0.5:
        w.ops.append("G TIMER %08x" % rnd.randrange(1, 100000))
    for k in range(5):
        if rnd.random() < 0.4:
            w.ops.append(route_range(rnd, k))
    so, ds = sign_ops(rnd, rnd.choice((0, 1, 4)))
    w.ops += so
    w.ops.append("%%d 0 %s" % dist_near(rnd, ds))
    w.ops += ["%n 0", "%dr 0", "%v 0 1"]
    # The list's location and choice, which "%gl" can highlight and "%J"
    # copies.
    kr = rnd.randrange(5)
    if rnd.random() < 0.2:
        w.ops.append("D -1 -1 -1 0")
    else:
        w.ops.append("D %d %d %d %08x" % (
            kr, rnd.randrange(sizes[kr]), rnd.randrange(LINES),
            rnd.choice((0, 777))))
    w.ops.append("X %d -1 %d" % (rnd.randrange(5), rnd.choice((0, 1))))
    if rnd.random() < 0.6:
        w.ops.append("%J 0")
    return w, sizes, others


def route_range(rnd, k):
    """Route k's distances, so that the first pass takes it or not, and
    now and then its box far off."""
    s = f32(rnd.uniform(0.0, 3000.0))
    e = f32(rnd.choice((s + rnd.uniform(1.0, 800.0), s - rnd.uniform(1.0,
                                                                      800.0),
                        s)))
    if rnd.random() < 0.15:
        box = (2e6, 2e6, 3e6, 3e6)
    else:
        box = (-1000.0, -1000.0, 1000.0, 1000.0)
    return "%%U %d %s %s %s" % (k, h(s), h(e), " ".join(h(f32(v))
                                                         for v in box))


def rnum(rnd, w):
    rns = sorted(w.rn.values())
    c = rnd.randrange(6)
    if c == 0:
        return 0, 99
    if c == 1:
        r = rnd.choice(rns)
        return r, r
    if c == 2:
        return rnd.choice(rns) - 1, rnd.choice(rns) + 1
    if c == 3:
        return -5, rnd.choice(rns)
    if c == 4:
        return rns[-1], rns[0]
    return rnd.randrange(0, 50), rnd.randrange(50, 100)


def s_where(rnd):
    """The route methods: SetCurrentRoute, both getters with and without
    the find, out of bounds, FindWhereIAm, FindClosestTrackRoute and the
    line speed, through the test table or drivingchoice_check's."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    me = w.cars[0]
    home = "%%pos 0 %s %s %s" % (h(f32(me["px"])), h(f32(me["py"])),
                                 h(f32(me["pz"])))
    for _ in range(rnd.randrange(5, 12)):
        c = rnd.randrange(16)
        kr = rnd.randrange(5)
        if c == 0:
            first, last = rnum(rnd, w)
            ops.append("%%rn 0 %d %d" % (first, last))
            ops.append("%fw 0")
        elif c == 1:
            first, last = rnum(rnd, w)
            ops.append("%%fc 0 %d %d" % (first, last))
        elif c == 2:
            r, j = kr, rnd.randrange(sizes[kr])
            if rnd.random() < 0.15:
                r, j = rnd.choice(((-1, j), (r, -1), (-1, -1)))
            ops.append("%%sr 0 %d %d" % (r, j))
        elif c in (3, 4):
            if rnd.random() < 0.4:
                ops.append("%L 0 -1 -1 -1 0")
                first, last = rnum(rnd, w)
                ops.append("%%rn 0 %d %d" % (first, last))
            if rnd.random() < 0.3:
                ops.append("%v 0 2")
                ops.append("%%%s 0 %d" % (rnd.choice(("gr", "gp")),
                                          rnd.choice((0, 1))))
                ops.append("%v 0 1")
            else:
                ops.append("%%%s 0 %d" % (rnd.choice(("gr", "gp")),
                                          rnd.choice((0, 1, 1))))
        elif c == 5:
            ops.append("%oob 0")
        elif c == 6:
            ops.append(loc_op(rnd, sizes))
            ops.append("%oob 0")
            ops.append(rnd.choice(("%ls 0", "%seam 0")))
        elif c == 7:
            ops.append(rnd.choice(("%ls 0", "%seam 0")))
        elif c == 8:
            ops.append(route_range(rnd, kr))
        elif c == 9:
            ops.append("%%d 0 %s" % h(f32(rnd.uniform(-100.0, 3500.0))))
        elif c == 10:
            ops.append("%K 0")
        elif c == 12:
            # Through _vt$15AICarController, whose SetCurrentRoute the
            # find takes.
            first, last = rnum(rnd, w)
            ops += ["%v 0 0", "%%fc 0 %d %d" % (first, last), "%v 0 1"]
        elif c == 13:
            # High above the routes or below them, where the height
            # decides which is closest.
            ops.append("%%pos 0 %s %s %s" % (
                h(f32(me["px"])), h(f32(me["py"])),
                h(f32(me["pz"] + rnd.choice((30.0, -30.0, 200.0, -200.0))))))
            # Over every route, so that there is a choice to make.
            if rnd.random() < 0.5:
                ops.append("%fc 0 0 99")
            else:
                ops.append("%rn 0 0 99")
                ops.append("%fw 0")
            ops.append(home)
        elif c == 14:
            # Exactly on the location's point, where the cross product is
            # zero.
            j = rnd.randrange(sizes[kr])
            p = w.pts[kr][j]
            ops.append("%%pos 0 %s %s %s" % (h(p["x"]), h(p["y"]),
                                             h(f32(me["pz"]))))
            ops.append("%%L 0 %d %d %d 0" % (kr, j, rnd.randrange(LINES)))
            ops.append("%oob 0")
            ops.append(home)
        elif c == 15:
            # Two routes alike, so the first of them in the table is the
            # closest.
            k2 = rnd.choice([x for x in range(5) if x != kr])
            ops.append("%%cp %d %d" % (kr, k2))
            lo, hi = sorted((w.rn[kr], w.rn[k2]))
            first, last = rnd.choice(((lo, hi), (0, 99),
                                      (lo - 1, min(hi + 1, 99))))
            if rnd.random() < 0.5:
                ops.append("%%fc 0 %d %d" % (first, last))
            else:
                ops.append("%%rn 0 %d %d" % (first, last))
                ops.append("%fw 0")
        else:
            ops.append("%%gl 0 %d %d %d %d" % (
                kr, rnd.randrange(sizes[kr]), rnd.choice((0, 1)),
                rnd.choice((-1, 0, 1))))
    return ops


def loc_op(rnd, sizes):
    """The location set by hand: a route's point and a line from -1 to 20,
    or clear, a point with no route. Never a route with no point, which
    the game doesn't make: IsClear tests the route alone, and every reader
    here reads the point when it is set."""
    kr = rnd.randrange(5)
    j = rnd.randrange(sizes[kr])
    c = rnd.randrange(10)
    if c == 0:
        return "%%L 0 -1 %d %d 0" % (j, rnd.randrange(LINES))
    line = rnd.choice((-1, -1, 0, 20, rnd.randrange(LINES)))
    return "%%L 0 %d %d %d %08x" % (kr, j, line, rnd.choice((0, 1234)))


def s_line(rnd):
    """GetNewDrivingLine over every count of lines to consider, from the
    location or none, highlighted or not, past cars that block lines."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    for _ in range(rnd.randrange(3, 7)):
        kr = rnd.randrange(5)
        j = rnd.randrange(sizes[kr])
        r = kr
        c = rnd.random()
        if c < 0.08:
            r = -1
        elif c < 0.16:
            j = -1
        if rnd.random() < 0.3:
            ops.append("G NLINES %08x" % rnd.choice((0, 1, 2, 3, 4)))
        if rnd.random() < 0.3:
            ops.append("G CAM %08x" % rnd.choice((M32, 0, 1, 5)))
        ops.append("%%gl 0 %d %d %d %d" % (r, j, rnd.choice((0, 1)),
                                           rnd.choice((-1, 0, 1, 1))))
    return ops


def s_relax(rnd):
    """GetNewDrivingLine and SetCurrentRoute where the switch decides: my
    car off its line and past 29.5 m/s, where a relaxed switch comes back
    0.25 m a point and any other 0.5, or comes back not at all, the clock
    well past a switch's 3 s, the grace period over, and slower cars ahead
    on the line or beside it, at distances where coming back sooner or
    later decides whether one is hit within the threshold."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    kr = rnd.randrange(5)
    j0 = rnd.randrange(sizes[kr] - 8)
    p = w.pts[kr][j0]
    cls = rnd.randint(0, 8)
    line = 2 * cls
    hd = heading_of(p)
    off = rnd.choice((-1.0, 1.0)) * rnd.choice((2.0, 2.5, 3.0, 3.5,
                                                rnd.uniform(1.5, 4.5)))
    x, y = dcc.beside(p, dcc.off_of(p, line) + off, 1.0)
    sp = rnd.choice((30.0, 35.0, 40.0, 50.0))
    w.car(0, px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
          vx=sp * math.cos(hd), vy=sp * math.sin(hd), cls=cls, dtype=2,
          ctl=rnd.choice((0, 1, 2, 4)), oob=0.0, pl=0, nw=4, fs=sp,
          dn=rnd.choice((0, 1, 5)), act=-1)
    boxed(rnd, w, 0)
    others = []
    for k in range(1, rnd.choice((2, 2, 3))):
        j = j0 + rnd.choice((1, 1, 2, 2, 3, 5))
        q = w.pts[kr][j]
        lat = dcc.off_of(q, line) + rnd.choice(
            (0.0, rnd.uniform(-1.0, 1.0), off * rnd.uniform(0.1, 0.6)))
        v = rnd.choice((5.0, 10.0, 15.0, 20.0, 25.0))
        qx, qy = dcc.beside(q, lat, rnd.uniform(-2.0, 2.0))
        qh = heading_of(q)
        w.car(k, px=qx, py=qy, bx=math.cos(qh), by=math.sin(qh), vmag=v,
              vx=v * math.cos(qh), vy=v * math.sin(qh), nw=4, pl=0,
              dtype=rnd.choice((1, 2, 3)), ctl=rnd.choice((0, 2, 3)),
              oob=0.0, fs=v, act=rnd.choice((-1, 0, 5)))
        boxed(rnd, w, k)
        # Its own target: on along the route where it is across it.
        ops.append("H %d 0 %s 0 0 0" % (k, h(f32(40.0))))
        for i in range(rnd.choice((4, 6, 8))):
            jj = min(sizes[kr] - 1, j + i)
            f = dcc.tgt_point(w, kr, jj, lat, line, sp=v).split()
            ops.append("I %d %s" % (k, " ".join(f[1:])))
        others.append(k)
    ops += seen_list(rnd, w, others)
    ops.append("G TIMER %08x" % rnd.randrange(20000, 200000))
    ops.append("G GRACE %s" % h(f32(0.0)))
    ops.append("G NLINES %08x" % rnd.choice((1, 1, 2, 3)))
    if rnd.random() < 0.5:
        ops.append("G AVOID %s" % h(f32(rnd.choice((1.0, 2.0, 3.0)))))
    ops += ["%d 0 0", "%n 0", "%dr 0", "%v 0 1",
            "D %d %d %d 00000000" % (kr, j0, line), "X 1 -1 0", "%J 0"]
    for _ in range(rnd.randrange(1, 4)):
        j = min(sizes[kr] - 1, j0 + rnd.choice((0, 0, 1)))
        ops.append("%%gl 0 %d %d 0 -1" % (kr, j))
        ops.append("%%gl 0 %d %d 1 -1" % (kr, j))
        ops.append("%L 0 -1 -1 -1 0")
        ops.append("%%sr 0 %d %d" % (kr, j))
    return ops


def s_action(rnd):
    """InterruptAction forced and not, over scores either way, and
    GeneratePointsToFulfillAction answered both ways, over each kind of
    choice and the location's line or another."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    nf = rnd.randrange(2, NFACTS + 1)
    for i in range(nf):
        ops.append("%%fa %d %d %d %d %d" % (
            i, rnd.choice((0, 1, 2, 5, 6, 10)),
            rnd.choice((0, 100, 300, 300, 500, 600, -1)),
            rnd.choice((0, 1, 1)), rnd.choice((0, 1))))
    if rnd.random() < 0.5:
        ops.append("%%sr 0 %d %d" % (0, rnd.randrange(sizes[0])))
    for _ in range(rnd.randrange(4, 10)):
        c = rnd.randrange(8)
        if c in (0, 1):
            q = [rnd.randrange(-1, nf) for _ in range(rnd.randrange(0, 4))]
            ops.append("%q " + " ".join("%d" % i for i in q) if q else "%q")
            if rnd.random() < 0.5:
                ops.append("%%force 0 %d" % rnd.choice((0, 2, 5, 11, 11)))
            ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
            if rnd.random() < 0.3:
                ops.append("%v 0 0")
                ops.append("%ia 0")
                ops.append("%v 0 1")
            else:
                ops.append("%ia 0")
        elif c in (2, 3, 4):
            i = rnd.randrange(nf)
            ops.append("%%fa %d %d %d %d %d" % (
                i, rnd.choice((0, 2, 5)), rnd.randrange(0, 700),
                rnd.choice((0, 1)), rnd.choice((0, 1))))
            # A second answer for the action ChooseNewAction hands back,
            # so that its CalculatePointsToDrive has an action to run on.
            ops.append("%%q %d" % rnd.randrange(nf))
            ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
            ops.append("%%ch 0 %d %d %d" % (
                rnd.choice((0, 1, 2, 3, 4, 4, 5, 6, 7, -1)),
                rnd.choice((-1, -1, 1)), rnd.choice((0, 1))))
            if rnd.random() < 0.5:
                ops.append(loc_op(rnd, sizes))
            ops.append("%%gpf 0 %d" % i)
        elif c == 5:
            ops.append("%cat 0")
        elif c == 6:
            ops.append("%%cn 0 %d" % rnd.choice((0, 2, 11)))
        else:
            ops.append("%K 0")
    ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
    ops.append("%%x 0 %d" % rnd.choice((0, 1, 2, 3)))
    return ops


N_BUILD = 40
N_WHERE = 30
N_LINE = 16
N_ACTION = 30
N_RELAX = 40


def script():
    rnd = random.Random(0x11e1)
    sc = []
    for _ in range(N_BUILD):
        sc.append(s_build(rnd))
    for _ in range(N_WHERE):
        sc.append(s_where(rnd))
    for _ in range(N_LINE):
        sc.append(s_line(rnd))
    for _ in range(N_ACTION):
        sc.append(s_action(rnd))
    for _ in range(N_RELAX):
        sc.append(s_relax(rnd))
    return sc


encode = dcc.encode


# ================================================================ the model


class Model(dcc.Model):
    def __init__(self):
        dcc.Model.__init__(self)
        e = self.e
        # Car::GetRoutePoint and GetAmountOutOfBounds run as shipped, into
        # the controller's table.
        del e.stubs[dcc.GET_ROUTE_POINT]
        del e.stubs[dcc.GET_OOB]
        e.stub(STUB_CRP, self.s_crp)
        e.stub(STUB_COOB, self.s_coob)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(BFREE, self.s_free)
        e.stub(SET_MOVEMENT, self.s_movement)
        e.stub(STUB_SSTP, self.s_sstp)
        e.stub(STUB_ZSM, self.s_zsm)
        e.stub(STUB_RNUM, self.s_rnum)
        e.stub(STUB_CHOOSE, self.s_choose)
        e.stub(STUB_ADEL, self.s_adel)
        e.stub(STUB_ACP, self.s_acp)
        self.vt0 = bytes(e.mem[AICC_VTABLE:AICC_VTABLE + AICC_VT_BYTES])
        self.nheap = 0
        self.fa_pt = [0] * NFACTS
        self.queue = []
        self.qi = 0
        self.rnums = {}

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        n = dcc.Model.name(self, a)
        if not n.startswith("?"):
            return n
        for k in range(NCARS):
            c = ctrl_at(k)
            if a == c + K_LIST:
                return "kn%d" % k
            if a == c + K_ILOC:
                return "kl%d" % k
            if a == c + K_ICH:
                return "kc%d" % k
            off = a - (c + K_LIST + 8)
            if 0 <= off < NC_SIZE * 16 and off % NC_SIZE == 0:
                return "ke%d:%d" % (k, off // NC_SIZE)
        if (HEAP <= a < HEAP + HEAP_BLOCK * NHEAP
                and (a - HEAP) % HEAP_BLOCK == 0):
            return "m%d" % ((a - HEAP) // HEAP_BLOCK)
        if (CDRIVERS <= a < CDRIVERS + CDRIVER_STRIDE * NCARS
                and (a - CDRIVERS) % CDRIVER_STRIDE == 0):
            return "d%d" % ((a - CDRIVERS) // CDRIVER_STRIDE)
        if (FACTS <= a < FACTS + FACT_SIZE * NFACTS
                and (a - FACTS) % FACT_SIZE == 0):
            return "fa%d" % ((a - FACTS) // FACT_SIZE)
        return n

    def vtn(self, v):
        return VT_NAMES.get(v & M32, "%08x" % (v & M32))

    def ctrl_index(self, a):
        k, off = divmod((a & M32) - CTRLS, CTRL_STRIDE)
        if off or not 0 <= k < NCARS:
            raise SystemExit("a controller that is not one of ours: %08x"
                             % (a & M32))
        return k

    def fact_index(self, a):
        i, off = divmod((a & M32) - FACTS, FACT_SIZE)
        if off or not 0 <= i < NFACTS:
            raise SystemExit("an action that is not one of ours: %08x"
                             % (a & M32))
        return i

    # ---- the stubs -------------------------------------------------------

    def s_crp(self, em):
        k = self.ctrl_index(em.reg[4])
        self.emit("  rp %s" % self.name(car_at(k)))
        return self.rp.get(k, 0)

    def s_coob(self, em):
        k = self.ctrl_index(em.reg[4])
        self.emit("  oob %s" % self.name(car_at(k)))
        em.fpr[0] = self.oob.get(k, 0)

    def s_malloc(self, em):
        r = em.reg
        size = s32(r[4])
        if self.nheap >= NHEAP or not 0 <= size <= HEAP_BLOCK:
            raise SystemExit("bMalloc: %d bytes for %s"
                             % (size, self.cstr(r[5] & M32)))
        p = HEAP + HEAP_BLOCK * self.nheap
        self.emit("  alloc m%d size %d name %s flags %d pool %d" % (
            self.nheap, size, self.cstr(r[5] & M32), s32(r[6]), s32(r[7])))
        self.nheap += 1
        self.fill(p, HEAP_BLOCK)
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_movement(self, em):
        car, mode = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  mode %s %d" % (self.name(car), s32(mode)))
        self.e.put32(car + C_MODE, mode)

    def s_sstp(self, em):
        k = self.driver_car(em)
        p = em.reg[5] & M32
        self.emit("  sstp %s %s %s" % (self.name(car_at(k)), fx(self.w(p)),
                                       fx(self.w(p + 4))))

    def s_zsm(self, em):
        self.emit("  zsm %s" % self.name(car_at(self.driver_car(em))))

    def s_rnum(self, em):
        r = em.reg
        k = self.ctrl_index(r[4])
        self.emit("  rnum %s" % self.name(r[4]))
        first, last = self.rnums.get(k, (0, 0))
        self.e.put32(r[5] & M32, first & M32)
        self.e.put32(r[6] & M32, last & M32)

    def s_choose(self, em):
        r = em.reg
        self.ctrl_index(r[4])
        if self.qi < len(self.queue):
            i = self.queue[self.qi]
            self.qi += 1
        else:
            i = -1
        self.emit("  choose %s %d" % (self.name(r[4]), s32(r[6])))
        self.e.put32(r[5] & M32, fact_at(i))

    def s_adel(self, em):
        a = em.reg[4] & M32
        self.emit("  adel %s %d" % (self.name(a), s32(em.reg[5])))
        self.fact_index(a)

    def s_acp(self, em):
        a = em.reg[4] & M32
        i = self.fact_index(a)
        self.emit("  acp %s %s" % (self.name(a), self.name(em.reg[5])))
        self.e.put32(a + A_PT, self.fa_pt[i] & M32)

    # ---- the world -------------------------------------------------------

    def reset(self):
        dcc.Model.reset(self)
        e = self.e
        e.put32(NDMM, MELLOW)
        e.mem[TVT:TVT + AICC_VT_BYTES] = self.vt0
        e.put32(TVT + 112 + 4, STUB_RNUM)
        e.put32(TVT + 120 + 4, STUB_CHOOSE)
        e.mem[AVT:AVT + AVT_BYTES] = bytes(AVT_BYTES)
        e.put32(AVT + 8 + 4, STUB_ADEL)
        e.put32(AVT + 24 + 4, STUB_ACP)
        e.put32(DVT + 72 + 4, STUB_SSTP)
        e.put32(DVT + 120 + 4, STUB_ZSM)
        e.put32(CVT + 56 + 4, STUB_CRP)
        e.put32(CVT + 64 + 4, STUB_COOB)
        e.mem[FACTS:FACTS + FACT_SIZE * NFACTS] = bytes(FACT_SIZE * NFACTS)
        self.nheap = 0
        self.fa_pt = [0] * NFACTS
        self.queue = []
        self.qi = 0
        self.rnums = {}

    # ---- the dumps -------------------------------------------------------

    def dump_avg(self, tag, a):
        a &= M32
        if a == 0 or a == PAT32:
            self.emit("  %s %s" % (tag, "null" if a == 0 else "pat"))
            return
        w, m = self.w, self.e.mem
        data = w(a + 12)
        self.emit("  %s %s slots %d cur %d n %d total %s avg %s data %s" % (
            tag, self.name(a), m[a], m[a + 1], m[a + 2], fx(w(a + 4)),
            fx(w(a + 8)), self.name(data)))
        if not (HEAP <= data < HEAP + HEAP_BLOCK * NHEAP
                and (data - HEAP) % HEAP_BLOCK == 0):
            return
        n = min(m[a], HEAP_BLOCK // 4)
        self.emit("   " + "".join(" %s" % fx(w(data + 4 * i))
                                  for i in range(n)))

    def dump_loc(self, tag, l):
        w = self.w
        self.emit("  %s %s %s %d %08x" % (tag, self.name(w(l)),
                                          self.name(w(l + 4)),
                                          s32(w(l + 8)), w(l + 12)))

    def dump_ctrl(self, k):
        w, m, nm = self.w, self.e.mem, self.name
        c = ctrl_at(k)
        lst = c + K_LIST
        self.emit("  K vt %s car %s drv %s" % (self.vtn(w(c + K_VPTR)),
                                              nm(w(c)), nm(w(c + K_DRIVER))))
        self.emit("  K list %s %d %s %s" % (nm(w(lst)), s32(w(lst + 4)),
                                            fx(w(lst + LIST_HL)),
                                            fx(w(lst + LIST_HD))))
        self.emit("   " + "".join(" %s" % nm(w(lst + 8 + NC_SIZE * i + 24))
                                  for i in range(16)))
        self.dump_loc("K iloc", c + K_ILOC)
        self.dump_choice(c + K_ICH, "K ich")
        self.emit("  K ptr %s %s %s exc %s ltr %d secs %s force %d act %s"
                  % (nm(w(c + K_LOC)), nm(w(c + K_CHOICE)),
                     nm(w(c + K_NLIST)), nm(w(c + K_EXCLUDE)),
                     s8(m[c + K_LTR]), fx(w(c + K_SECS)),
                     s32(w(c + K_FORCE)), nm(w(c + K_ACTION))))
        self.emit("  K t " + " ".join("%08x" % w(c + o) for o in K_TIMERS))
        self.emit("  K la %d pot %s bs %d lp %s glue %s gr %d gb %s boost %d "
                  "cp %s sign %d ts %d" % (
                      s32(w(c + K_LA)), fx(w(c + K_POT)), s32(w(c + K_BS)),
                      fx(w(c + K_LP)), nm(w(c + K_GLUE)), s32(w(c + K_GR)),
                      fx(w(c + K_GB)), s32(w(c + K_BOOST)),
                      nm(w(c + K_CP)), s32(w(c + K_SIGN)),
                      s32(w(c + K_TS))))
        self.emit("  K sticky" + "".join(" %08x" % w(c + K_STICKY + 4 * i)
                                         for i in range(NSTICKY)))
        self.emit("  K gd " + "".join("%02x" % m[c + K_GD + i]
                                      for i in range(32)))
        self.emit("  K vp %s" % " ".join(fx(w(c + K_VP + 4 * i))
                                         for i in range(4)))
        self.dump_avg("K prog", w(c + K_PROG))
        self.dump_avg("K dls", w(c + K_DLS))

    def dump_where(self, k):
        w = self.w
        c = ctrl_at(k)
        self.dump_loc("K at", w(c + K_LOC))
        self.emit("  K ltr %d hl %d %d" % (
            s8(self.e.mem[c + K_LTR]), s32(w(GLOBALS["HROUTE"])),
            s32(w(GLOBALS["HLINE"]))))

    def dump_facts(self):
        for i in range(NFACTS):
            a = fact_at(i)
            if self.w(a + A_VPTR):
                self.emit("  fa%d pt %d" % (i, s32(self.w(a + A_PT))))

    # ---- the ops ---------------------------------------------------------

    def hl_of(self, k, s):
        v = int(s)
        if v < 0:
            return 0
        return LOC if v == 0 else self.w(ctrl_at(k) + K_LOC)

    def pct(self, t):
        e, w = self.e, self.w
        c = t[0][1:]
        k = int(t[1]) if len(t) > 1 else 0
        a = ctrl_at(k) if 0 <= k < NCARS else ctrl_at(0)
        car = car_at(k) if 0 <= k < NCARS else 0
        if c == "d":
            e.put32(car + C_DIST, int(t[2], 16))
        elif c == "S":
            e.put32(SIGNS + SIGN_SIZE * k + S_DIST, int(t[2], 16))
        elif c == "NS":
            e.put32(GLOBALS["NSIGNS"], k & M32)
        elif c == "U":
            r = route_at(k)
            for off, v in zip((R_START, R_END, R_BMIN, R_BMIN + 4, R_BMAX,
                               R_BMAX + 4), t[2:8]):
                e.put32(r + off, int(v, 16))
        elif c == "a":
            struct.pack_into("<H", e.mem, car + C_ANGLE, int(t[2]) & 0xffff)
        elif c == "mm":
            e.put32(car + C_MODE, int(t[2]) & M32)
        elif c == "pl":
            e.put32(car + C_PLAYER,
                    PLAYERS + PLAYER_STRIDE * k if int(t[2]) else 0)
        elif c == "bf":
            e.put32(car + C_BOOST, int(t[2], 16))
        elif c == "ci":
            struct.pack_into("<h", e.mem, car + C_INDEX, int(t[2]))
        elif c == "pos":
            for i in range(3):
                e.put32(car + dcc.C_POS + 4 * i, int(t[2 + i], 16))
        elif c == "vp":
            for i in range(4):
                e.put32(a + K_VP + 4 * i, int(t[2 + i], 16))
        elif c == "cp":
            src, dst = route_at(k), route_at(int(t[2]))
            n = min(s32(w(src + 16)), s32(w(dst + 16)))
            for i in range(n):
                o = dcc.RT_HEADER + dcc.RT_POINT * i
                e.mem[dst + o:dst + o + 111] = e.mem[src + o:src + o + 111]
        elif c == "G":
            e.put32(NDMM, k & M32)
        elif c == "n":
            self.fill(a, K_SIZE)
            self.call(F["ctor"], a, car)
            self.dump_ctrl(k)
        elif c == "x":
            self.call(F["dtor"], a, int(t[2]) & M32)
            self.emit("  vt %s" % self.vtn(w(a + K_VPTR)))
        elif c == "K":
            self.dump_ctrl(k)
        elif c == "v":
            e.put32(a + K_VPTR, (AICC_VTABLE, TVT, CVT)[int(t[2])])
        elif c == "dr":
            e.put32(a + K_DRIVER, CDRIVERS + CDRIVER_STRIDE * k)
        elif c == "J":
            e.mem[a + K_LIST:a + K_LIST + LIST_BYTES] = \
                e.mem[LIST:LIST + LIST_BYTES]
            e.mem[a + K_ILOC:a + K_ILOC + 16] = e.mem[LOC:LOC + 16]
            e.mem[a + K_ICH:a + K_ICH + 12] = e.mem[CHOICE:CHOICE + 12]
        elif c == "L":
            l = w(a + K_LOC)
            e.put32(l, self.route_of(t[2]))
            e.put32(l + 4, self.point_of(t[2], t[3]))
            e.put32(l + 8, int(t[4]) & M32)
            e.put32(l + 12, int(t[5], 16))
        elif c == "ch":
            self.set_choice(w(a + K_CHOICE), t[1:])
        elif c == "sk":
            for i in range(NSTICKY):
                e.put32(a + K_STICKY + 4 * i, int(t[2 + i], 16))
        elif c == "rn":
            self.rnums[k] = (int(t[2]), int(t[3]))
        elif c == "q":
            self.queue = [int(v) for v in t[1:17]]
            self.qi = 0
        elif c == "fa":
            f = fact_at(k)
            e.mem[f:f + FACT_SIZE] = bytes(FACT_SIZE)
            e.put32(f + A_VPTR, AVT)
            e.put32(f + A_TYPE, int(t[2]) & M32)
            e.put32(f + A_SCORE, int(t[3]) & M32)
            self.fa_pt[k] = int(t[4])
            e.put32(f + A_PT, int(t[5]) & M32)
        elif c == "cur":
            e.put32(a + K_ACTION, fact_at(int(t[2])))
        elif c == "sr":
            self.call(F["sr"], a, self.route_of(t[2]),
                      self.point_of(t[2], t[3]))
            self.dump_where(k)
        elif c == "gr":
            got = self.call(F["gr"], a, int(t[2]) & M32)
            self.emit("  route %s" % self.name(got))
            self.dump_where(k)
        elif c == "gp":
            got = self.call(F["gp"], a, int(t[2]) & M32)
            self.emit("  point %s" % self.name(got))
            self.dump_where(k)
        elif c == "oob":
            self.call(F["oob"], a)
            self.emit("  oob %s" % fx(e.fpr[0]))
        elif c == "fw":
            self.call(F["fw"], a)
            self.dump_where(k)
        elif c == "fc":
            self.call(F["fc"], a, int(t[2]) & M32, int(t[3]) & M32)
            self.dump_where(k)
        elif c == "gl":
            self.fill(LINEVAR, 4)
            got = self.call(F["gl"], a, self.route_of(t[2]),
                            self.point_of(t[2], t[3]), int(t[4]) & M32,
                            LINEVAR, self.hl_of(k, t[5]))
            self.emit("  line %d %d" % (s32(got), s32(w(LINEVAR))))
            self.dump_where(k)
            self.dump_after()
        elif c == "jr":
            self.call(F["jr"], a)
            self.dump_ctrl(k)
        elif c == "dn":
            self.emit("  dnum %d" % s32(self.call(F["dn"], a)))
        elif c == "cs":
            self.call(F["cs"], a)
            self.emit("  sticky" + "".join(" %08x" % w(a + K_STICKY + 4 * i)
                                           for i in range(NSTICKY)))
        elif c == "st":
            self.call(F["st"], a)
        elif c == "cn":
            e.put32(OUTP, 0)
            self.call(F["cn"], a, OUTP, int(t[2]) & M32)
            self.emit("  chosen %s" % self.name(w(OUTP)))
        elif c == "ia":
            got = self.call(F["ia"], a)
            self.emit("  interrupt %s force %d act %s" % (
                self.name(got), s32(w(a + K_FORCE)),
                self.name(w(a + K_ACTION))))
        elif c == "gpf":
            self.call(F["gpf"], a, fact_at(int(t[2])))
            self.emit("  act %s" % self.name(w(a + K_ACTION)))
            self.dump_facts()
            self.dump_where(k)
        elif c == "cat":
            self.emit("  atype %d" % s32(self.call(F["cat"], a)))
        elif c == "force":
            self.call(F["force"], a, int(t[2]) & M32)
            self.emit("  force %d" % s32(w(a + K_FORCE)))
        elif c == "pm":
            self.call(F["pm"], a, self.car_ptr(t[2]))
            self.emit("  movement %d ob %08x rp %08x" % (
                s32(w(car + C_MODE)), w(a + K_OB), w(a + K_RP)))
        elif c == "cc":
            self.call(F["cc"], a, self.car_ptr(t[2]))
            self.emit("  movement %d" % s32(w(car + C_MODE)))
        elif c in ("ls", "seam"):
            self.call(F["ls"], a)
            self.emit("  lspeed %s" % fx(e.fpr[0]))
        elif c == "fb":
            self.call(F["fb"], a, f12=int(t[2], 16))
            self.emit("  boost %s %d" % (fx(w(car + C_BOOST)),
                                         s32(w(a + K_BOOST))))
        elif c == "rb":
            self.call(F["rb"], a)
            self.emit("  boost %s %d" % (fx(w(car + C_BOOST)),
                                         s32(w(a + K_BOOST))))
        elif c == "af":
            got = self.call(F["af"], a, f12=int(t[2], 16))
            self.emit("  fly %d" % s32(got))
        elif c == "ob":
            self.call(F["ob"], a, f12=int(t[2], 16))
            self.emit("  ob %08x" % w(a + K_OB))
        elif c == "ex":
            self.call(F["ex"], a, self.car_ptr(t[2]))
            self.emit("  exc %s" % self.name(w(a + K_EXCLUDE)))
        elif c == "gx":
            self.emit("  exc %s" % self.name(self.call(F["gx"], a)))
        elif c == "gdl":
            self.emit("  dloc %s" % self.name(self.call(F["gdl"], a)))
        elif c == "dd":
            self.call(F["dd"], a)
        else:
            raise SystemExit("bad op %r" % (t,))

    def op(self, t):
        if t[0].startswith("%"):
            self.pct(t)
        else:
            dcc.Model.op(self, t)


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="aicarcontroller_test"):
    return dcc.hostbuild.build(tmp, SOURCES, name=name)


run_harness = dcc.run_harness
diff = dcc.diff


# ============================================================ the mutations


def M(name, before, after, rel=AICC):
    return (name, rel, before, after)


MUTATIONS = [
    # The constructor.
    M("ct-vt", "    c->Base._vtable = AICARCONTROLLER_VTABLE;\n    // The NearbyCars'",
      "    // The NearbyCars'"),
    M("ct-mycar", "    list->MyCar = car;\n", ""),
    M("ct-stagger", "        (float)car->CarIndex * AICC_EVALUATION_STAGGER;",
      "        (float)car->CarIndex * -AICC_EVALUATION_STAGGER;"),
    M("ct-force", "    c->ForceCurrentAction = AIACTION_NONE;\n    c->LastTrackRouteNumber = -1;",
      "    c->ForceCurrentAction = AIACTION_DRAFT;\n    c->LastTrackRouteNumber = -1;"),
    M("ct-ltr", "    c->LastTrackRouteNumber = -1;\n    c->CurrentAction = NULL;",
      "    c->LastTrackRouteNumber = 0;\n    c->CurrentAction = NULL;"),
    M("ct-list", "    c->CurrentNearbyCarList = list;",
      "    c->CurrentNearbyCarList =\n"
      "        (NearbyCarList *)(void *)c->CurrentDrivingChoice;"),
    M("ct-lookahead", "    c->CurrentRoutePointLookahead = 0;",
      "    c->CurrentRoutePointLookahead = 1;"),
    M("ct-exclude", "    c->CarToExcludeFromCollisionPrediction = NULL;\n"
      "    c->LastBoostCalculationTime", "    c->LastBoostCalculationTime"),
    M("ct-glue", "    c->pGlueCar = NULL;\n", ""),
    M("ct-progress", "    timer_set_time(&c->ProgressTimer, AICC_PROGRESS_SECONDS);",
      "    timer_set_time(&c->ProgressTimer, AICC_OFF_BELT_SECONDS);"),
    M("ct-avg10", "                           CAR_MEMORY_POOL), 10);",
      "                           CAR_MEMORY_POOL), 11);"),
    M("ct-avg5", "                           CAR_MEMORY_POOL), 5);",
      "                           CAR_MEMORY_POOL), 4);"),
    M("ct-prev", "    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);\n"
      "    c->bBoostAllowed = 1;", "    c->bBoostAllowed = 1;"),
    M("ct-boost", "    c->bBoostAllowed = 1;\n    c->pCatchupPlayer = NULL;",
      "    c->bBoostAllowed = 0;\n    c->pCatchupPlayer = NULL;"),
    M("ct-catchup", "    c->pCatchupPlayer = NULL;",
      "    c->pCatchupPlayer = (struct Player *)(void *)c;"),
    M("ct-pot", "    c->PullOverTimeout = AICC_PULL_OVER_TIMEOUT;",
      "    c->PullOverTimeout = 0.0f;"),
    M("ct-sign", "    c->nSignpostIndex = signpost_get_index(car->TheTrackPathCoordinate\n"
      "                                               .DistanceAroundTrack);",
      "    c->nSignpostIndex = 0;"),
    M("ct-bs", "    c->BrakeStanding = 1;", "    c->BrakeStanding = 0;"),
    M("ct-tsi", "    c->TakenSignpostIndex = -1;", "    c->TakenSignpostIndex = 0;"),
    # The destructor.
    M("dt-action", "    if (c->CurrentAction != NULL)\n        delete_action(c->CurrentAction);\n"
      "    if (c->pProgress", "    if (c->pProgress"),
    M("dt-prog", "    if (c->pProgress != NULL)\n        average_destroy(c->pProgress, 3);\n",
      ""),
    M("dt-dls", "        average_destroy(c->pDeltaLineSpeed, 3);",
      "        average_destroy(c->pDeltaLineSpeed, 2);"),
    M("dt-flags", "    carcontroller_destroy(&c->Base, flags);",
      "    carcontroller_destroy(&c->Base, 0);"),
    # SetCurrentRoute.
    M("sr-null", "    if (r == NULL || p == NULL)\n        return;\n    old =",
      "    if (r == NULL)\n        return;\n    old ="),
    M("sr-ltr", "    c->LastTrackRouteNumber = old != NULL ? (int8_t)old->RouteNumber : -1;",
      "    c->LastTrackRouteNumber = old != NULL ? (int8_t)old->RouteNumber : 0;"),
    M("sr-relax", "    aicarcontroller_get_new_driving_line(c, r, p, 1, &line, NULL);",
      "    aicarcontroller_get_new_driving_line(c, r, p, 0, &line, NULL);"),
    M("sr-relax2", "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 1);",
      "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 0);"),
    M("sr-line", "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 1);",
      "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, 0, 1);"),
    # The getters' find.
    M("fic-find", "    if (find && drivinglocation_is_clear(c->CurrentDrivingLocation)) {",
      "    if (drivinglocation_is_clear(c->CurrentDrivingLocation)) {"),
    M("fic-clear", "    if (find && drivinglocation_is_clear(c->CurrentDrivingLocation)) {",
      "    if (find && !drivinglocation_is_clear(c->CurrentDrivingLocation)) {"),
    M("gr-route", "    find_if_clear(c, find);\n    return c->CurrentDrivingLocation->pRoute;",
      "    find_if_clear(c, 0);\n    return c->CurrentDrivingLocation->pRoute;"),
    M("gp-point", "    find_if_clear(c, find);\n    return c->CurrentDrivingLocation->pRoutePoint;",
      "    find_if_clear(c, 0);\n    return c->CurrentDrivingLocation->pRoutePoint;"),
    # GetAmountOutOfBounds.
    M("oob-clear", "        return 0.0f;\n    p = c->CurrentDrivingLocation->pRoutePoint;",
      "        return 1.0f;\n    p = c->CurrentDrivingLocation->pRoutePoint;"),
    M("oob-gt", "    if (0.0f < f)\n        return f - p->RightWidth;",
      "    if (0.0f <= f)\n        return f - p->RightWidth;"),
    M("oob-rw", "        return f - p->RightWidth;", "        return f - p->LeftWidth;"),
    M("oob-lw", "    return -(f + p->LeftWidth);", "    return -(f + p->RightWidth);"),
    M("oob-cross", "        - (pos->y - p->Position.y) * p->Direction.x;",
      "        + (pos->y - p->Position.y) * p->Direction.x;"),
    # FindWhereIAm.
    M("fw-clear", "    drivinglocation_clear(c->CurrentDrivingLocation);\n"
      "    e = vt_slot(c->Base._vtable, AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE);",
      "    e = vt_slot(c->Base._vtable, AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE);"),
    M("fw-swap", "    aicarcontroller_find_closest_track_route(c, first, last);",
      "    aicarcontroller_find_closest_track_route(c, last, first);"),
    # FindClosestTrackRoute.
    M("fc-pass2", "    for (pass = 0; pass < 2 && bestRoute == NULL; pass++) {",
      "    for (pass = 0; pass < 1 && bestRoute == NULL; pass++) {"),
    M("fc-found", "    for (pass = 0; pass < 2 && bestRoute == NULL; pass++) {",
      "    for (pass = 0; pass < 2; pass++) {"),
    M("fc-pass0", "            if (pass <= 0 && !troute_distance_is_within_route(r, d))",
      "            if (!troute_distance_is_within_route(r, d))"),
    M("fc-within", "            if (pass <= 0 && !troute_distance_is_within_route(r, d))",
      "            if (pass <= 0 && troute_distance_is_within_route(r, d))"),
    M("fc-neg", "            TrackRoute *r = i >= 0 ? TheTrackRouteManager.pTrackRoutes[i]",
      "            TrackRoute *r = i > 0 ? TheTrackRouteManager.pTrackRoutes[i]"),
    M("fc-last", "        for (i = first; i <= last; i++) {",
      "        for (i = first; i < last; i++) {"),
    M("fc-flags", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                AICC_ROUTE_RADIUS, TRFIND_AHEAD_ONLY, 0.0f);"),
    M("fc-flags2", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                AICC_ROUTE_RADIUS, TRFIND_POSTED_ONLY, 0.0f);"),
    M("fc-radius", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                40.0f, AICC_ROUTE_FLAGS, 0.0f);"),
    M("fc-nopoint", "            if (p == NULL)\n                continue;\n            trpoint",
      "            if (p == NULL)\n                break;\n            trpoint"),
    M("fc-dx", "            dv.x = car->State.Position.x - v.x;",
      "            dv.x = car->State.Position.y - v.x;"),
    M("fc-dz", "            dv.z = car->State.Position.z - v.z;", "            dv.z = 0.0f;"),
    M("fc-lt", "            if (dist < best && r != current) {",
      "            if (dist <= best && r != current) {"),
    M("fc-cur", "            if (dist < best && r != current) {",
      "            if (dist < best) {"),
    M("fc-best", "                best = dist;\n", ""),
    M("fc-ret", "        ((SetRouteFn)e->fn)(vt_this(c, e), bestRoute, bestPoint);\n        return;",
      "        ((SetRouteFn)e->fn)(vt_this(c, e), bestRoute, bestPoint);"),
    M("fc-cl-line", "    c->CurrentDrivingLocation->DrivingLine = -1;\n"
      "    c->CurrentDrivingLocation->LastRelaxed",
      "    c->CurrentDrivingLocation->DrivingLine = 0;\n"
      "    c->CurrentDrivingLocation->LastRelaxed"),
    M("fc-cl-time", "    c->CurrentDrivingLocation->LastRelaxedDrivingLineSwitchTime.PackedTime = 0;\n"
      "    c->CurrentDrivingLocation->pRoute = NULL;",
      "    c->CurrentDrivingLocation->pRoute = NULL;"),
    M("fc-cl-route", "    c->CurrentDrivingLocation->pRoute = NULL;\n"
      "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}",
      "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}"),
    M("fc-cl-point", "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}\n\nint",
      "}\n\nint"),
    # GetNewDrivingLine.
    M("gl-init", "    *line = drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,\n"
      "                                           c->Base.pCar);",
      "    *line = 0;"),
    M("gl-rp", "    if (r != NULL && p != NULL) {\n        DrivingChoiceType type;",
      "    if (r != NULL) {\n        DrivingChoiceType type;"),
    M("gl-n", "             type - 1 < AICarControllerNumDrivingLinesToConsider; type++) {",
      "             type - 1 <= AICarControllerNumDrivingLinesToConsider; type++) {"),
    M("gl-type", "            drivingchoice_set_choice(&ch, type, NULL, 0);",
      "            drivingchoice_set_choice(&ch, CHOICE_DRIVING_LINE_0, NULL, 0);"),
    M("gl-relax", "                &l, drivingchoice_get_driving_line(type, c->Base.pCar),\n"
      "                relaxed);", "                &l, drivingchoice_get_driving_line(type, c->Base.pCar),\n"
      "                0);"),
    M("gl-relax0", "    drivinglocation_set_route(&l, r, p, *line, relaxed);",
      "    drivinglocation_set_route(&l, r, p, *line, !relaxed);"),
    M("gl-time", "                    AIDriverAvoidCarsImpactTimeThreshold, 0.0f,",
      "                    0.5f, 0.0f,"),
    M("gl-move", "                    MOVEMENT_TOWARDS_LINE)) {",
      "                    MOVEMENT_PARALLEL_TO_LINE)) {"),
    M("gl-list", "                    c->CurrentNearbyCarList, 0.0f,",
      "                    &c->MyCurrentDrivingInformation.MyNearbyCarList, 0.0f,"),
    M("gl-found", "                found = 1;", "                found = 0;"),
    M("gl-line", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);\n"
      "                break;", "                break;"),
    M("gl-break", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);\n"
      "                break;", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);"),
    M("gl-hl", "        if (highlight != NULL)\n            ai_highlight_driving_line(highlight,",
      "        if (highlight != NULL && 0)\n            ai_highlight_driving_line(highlight,"),
    M("gl-hl-loc", "            ai_highlight_driving_line(highlight,",
      "            ai_highlight_driving_line(&l,"),
    # JustReset, GetMyDriverNumber, ClearStickyDecisions,
    # SteerStraightAhead.
    M("jr-stagger", "        (float)c->Base.pCar->CarIndex * AICC_EVALUATION_STAGGER;",
      "        (float)c->Base.pCar->CarIndex * -AICC_EVALUATION_STAGGER;"),
    M("jr-prev", "    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);\n"
      "    d = c->Base.Driver;", "    d = c->Base.Driver;"),
    M("jr-zsm", "    e = vt_slot(d->_vtable, CARDRIVER_VT_ZERO_STEERING_MEMORY);",
      "    e = vt_slot(d->_vtable, CARDRIVER_VT_CLEAR_STEERING_MEMORY);"),
    M("jr-sticky", "    aicarcontroller_clear_sticky_decisions(c);\n"
      "    c->nSignpostIndex = signpost_get_index(\n",
      "    c->nSignpostIndex = signpost_get_index(\n"),
    M("jr-sign", "    c->nSignpostIndex = signpost_get_index(\n"
      "        c->Base.pCar->TheTrackPathCoordinate.DistanceAroundTrack);",
      "    c->nSignpostIndex = 0;"),
    M("dn", "    return c->Base.pCar->DriverNumber;", "    return c->Base.pCar->CarIndex;"),
    M("cs-mask", "        c->aStickyDecisions[i] &= ~1u;\n}",
      "        c->aStickyDecisions[i] &= ~2u;\n}"),
    M("cs-n", "    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)\n"
      "        c->aStickyDecisions[i] &= ~1u;\n}",
      "    for (i = 1; i < AICC_NUM_STICKY_DECISIONS; i++)\n"
      "        c->aStickyDecisions[i] &= ~1u;\n}"),
    M("st-swap", "    float cs = bCosBam(a), sn = bSinBam(a);",
      "    float cs = bSinBam(a), sn = bCosBam(a);"),
    M("st-x", "    to.x = car->State.Position.x + cs;", "    to.x = car->State.Position.x - cs;"),
    M("st-y", "    to.y = car->State.Position.y + sn;", "    to.y = car->State.Position.y - sn;"),
    M("st-slot", "    e = vt_slot(d->_vtable, CARDRIVER_VT_SET_STEER_TO_POINT);",
      "    e = vt_slot(d->_vtable, CARDRIVER_VT_GET_STEER_TO_POINT);"),
    # InterruptAction.
    M("ia-force", "    if (c->ForceCurrentAction == AIACTION_NONE) {",
      "    if (c->ForceCurrentAction != AIACTION_NONE) {"),
    M("ia-type", "        choose_new_action(c, &a, AIACTION_NONE);",
      "        choose_new_action(c, &a, AIACTION_DRAFT);"),
    M("ia-null", "        if (a == NULL)\n            return NULL;\n", ""),
    M("ia-cur", "        if (c->CurrentAction != NULL && c->CurrentAction->Score < a->Score)",
      "        if (c->CurrentAction == NULL || c->CurrentAction->Score < a->Score)"),
    M("ia-lt", "        if (c->CurrentAction != NULL && c->CurrentAction->Score < a->Score)",
      "        if (c->CurrentAction != NULL && c->CurrentAction->Score <= a->Score)"),
    M("ia-del", "        delete_action(a);\n        return NULL;", "        return NULL;"),
    M("ia-reset", "    choose_new_action(c, &a, c->ForceCurrentAction);\n"
      "    c->ForceCurrentAction = AIACTION_NONE;",
      "    choose_new_action(c, &a, c->ForceCurrentAction);"),
    # GeneratePointsToFulfillAction.
    M("gp-ahead", "    nearbycarlist_get_car_ahead(c->CurrentNearbyCarList, c->Base.pCar);\n",
      ""),
    M("gp-will", "    if (!a->PointsToDriveWillExecuteAction) {",
      "    if (a->PointsToDriveWillExecuteAction) {"),
    M("gp-del", "        if (c->CurrentAction != NULL)\n            delete_action(c->CurrentAction);\n"
      "        c->CurrentAction = NULL;", "        c->CurrentAction = NULL;"),
    M("gp-draft", "        choose_new_action(c, &c->CurrentAction, AIACTION_DRAFT);",
      "        choose_new_action(c, &c->CurrentAction, AIACTION_NONE);"),
    M("gp-calc2", "        action_calculate_points(c->CurrentAction, info);\n    }",
      "    }"),
    M("gp-isline", "    if (drivingchoice_type_is_driving_line(type)) {",
      "    if (type != CHOICE_NONE) {"),
    M("gp-ne", "        if (line != c->CurrentDrivingLocation->DrivingLine) {",
      "        if (1) {"),
    M("gp-relax", "            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,\n"
      "                                             0);",
      "            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,\n"
      "                                             1);"),
    M("gp-hl", "            ai_highlight_driving_line(c->CurrentDrivingLocation,\n"
      "                                      aicarcontroller_get_my_driver_number(c));\n"
      "        }", "        }"),
    # The action's getter and setter.
    M("cat", "                                    : AIACTION_NONE;",
      "                                    : AIACTION_DRAFT;"),
    M("force", "    c->ForceCurrentAction = type;", "    c->ForceCurrentAction = AIACTION_NONE;"),
    # SetToPhysicsMode.
    M("pm-belt", "    if (old == BELT_MOVEMENT)", "    if (old != BELT_MOVEMENT)"),
    M("pm-belt-s", "    timer_set_time(&c->OffBeltTimer, AICC_OFF_BELT_SECONDS);",
      "    timer_set_time(&c->OffBeltTimer, AICC_REAL_PHYSICS_SECONDS);"),
    M("pm-def", "    MovementMode mode = nDefaultMovementMode;",
      "    MovementMode mode = MELLOW_MOVEMENT;"),
    M("pm-car", "    if (car != NULL && car->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;",
      "    if (car != NULL)\n        mode = PHYSICS_MOVEMENT;"),
    M("pm-mine", "    if (car != NULL && car->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;",
      "    if (mine->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;"),
    M("pm-ne", "    if (mode != old)\n        car_set_movement_mode(mine, mode);",
      "    car_set_movement_mode(mine, mode);"),
    M("pm-phys", "    if (mode == PHYSICS_MOVEMENT)\n        timer_set_time(&c->RealPhysicsTimer",
      "    if (mode != PHYSICS_MOVEMENT)\n        timer_set_time(&c->RealPhysicsTimer"),
    M("pm-rp-s", "        timer_set_time(&c->RealPhysicsTimer, AICC_REAL_PHYSICS_SECONDS);",
      "        timer_set_time(&c->RealPhysicsTimer, AICC_OFF_BELT_SECONDS);"),
    # The line speed, the boost, the exclusion.
    M("ls-clear", "        return 0.0f;\n    b = (const uint8_t *)l->pRoutePoint",
      "        return 1.0f;\n    b = (const uint8_t *)l->pRoutePoint"),
    M("ls-off", "        + offsetof(TrackRoutePoint, DrivingLineSpeeds) + l->DrivingLine;",
      "        + offsetof(TrackRoutePoint, DrivingLineSpeeds) + l->DrivingLine + 1;"),
    M("fb", "    carcontroller_force_boost(&c->Base, f);\n    c->bBoostAllowed = 0;",
      "    carcontroller_force_boost(&c->Base, f);\n    c->bBoostAllowed = 1;"),
    M("fb-f", "    carcontroller_force_boost(&c->Base, f);",
      "    carcontroller_force_boost(&c->Base, 1.0f);"),
    M("rb", "    carcontroller_release_boost(&c->Base);\n    c->bBoostAllowed = 1;",
      "    carcontroller_release_boost(&c->Base);\n    c->bBoostAllowed = 0;"),
    M("rb-call", "    carcontroller_release_boost(&c->Base);\n", ""),
    M("ob", "    timer_set_time(&c->OffBeltTimer, seconds);",
      "    timer_set_time(&c->OffBeltTimer, seconds + 1.0f);"),
    M("gx", "    return c->CarToExcludeFromCollisionPrediction;", "    return NULL;"),
    M("ex", "    c->CarToExcludeFromCollisionPrediction = car;",
      "    c->CarToExcludeFromCollisionPrediction = NULL;"),
    # The table, which the test table copies.
    M("vt-sr", "    E(aicarcontroller_set_current_route),             //  40",
      "    E(aicarcontroller_debug_display),                 //  40"),
    M("vt-fw", "    E(aicarcontroller_find_where_i_am),               //  72",
      "    E(aicarcontroller_debug_display),                 //  72"),
    # CarController::SetToPhysicsMode, retail's.
    M("cc-phys", "    if (car->TheMovementMode == PHYSICS_MOVEMENT\n"
      "        || car->TheMovementMode == MELLOW_MOVEMENT)\n        return;",
      "    if (car->TheMovementMode == MELLOW_MOVEMENT)\n        return;", rel=CCC),
    M("cc-mellow", "    if (car->TheMovementMode == PHYSICS_MOVEMENT\n"
      "        || car->TheMovementMode == MELLOW_MOVEMENT)\n        return;",
      "    if (car->TheMovementMode == PHYSICS_MOVEMENT)\n        return;", rel=CCC),
    M("cc-player", "    car_set_movement_mode(car, car->pPlayer != NULL ? PHYSICS_MOVEMENT\n"
      "                                                    : MELLOW_MOVEMENT);",
      "    car_set_movement_mode(car, MELLOW_MOVEMENT);", rel=CCC),
    M("cc-arg", "    (void)car;\n    carcontroller_physics_or_mellow(c->pCar);",
      "    carcontroller_physics_or_mellow(car != NULL ? car : c->pCar);",
      rel=CCC),
]

EQUIVALENT = {
    "sr-relax":
        "GetNewDrivingLine's relaxed switch reaches only its own location, "
        "which IsDriveable hands to BuildDriveTarget: a valid line choice "
        "is built from a copy set to its line with no switch, and an "
        "invalid one, the only target built from the location as it is, "
        "makes IsDriveable answer 0 whatever it holds (s_relax shows it).",
    "gl-relax":
        "As sr-relax: the switch on the location's line never reaches a "
        "target IsDriveable reads.",
    "gl-relax0":
        "SetRoute's switch is overwritten by SetDrivingLine's on every pass "
        "before IsDriveable reads the location, and with no pass the "
        "location is not read at all.",
    "gl-list":
        "The constructor points CurrentNearbyCarList at the controller's "
        "own list and nothing in 11e-1 moves it.",
    "gp-ahead":
        "GetCarAhead only reads; retail calls it and drops the answer.",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "aicarcontroller_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
