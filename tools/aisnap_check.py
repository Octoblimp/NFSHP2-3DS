#!/usr/bin/env python3
"""Cross-check TASKS 72c, the replay's DoSnapshots for the drivers, the AI,
the controllers, the splines and the movers, against the retail image,
SLES_507.31.

**What is checked**: Average, PidError, DriveTarget, CarDriver,
PsychoDriver, RealDriver, DrivingLocation, DrivingChoice,
NearestRoutePointInfo, NearbyCarList, DrivingInformation, AIPlan, AIAction
and its eleven actions, AIAction's pointer move (which news an action of
the type it reads back), AICarController, AIDriver, TrafficDriver,
TrackedController, RealController, CopDriver, CopMover, BeltMover,
MellowMover, Mellovator, Spline, QuickSpline and CarController through
each driver's real table. Each is taken, restored over other values,
checksummed and verified, alone and as the trees the game builds.

**The layouts** are the port's headers, parsed by carsnap_check.py (which
this imports and extends): every field at the offset its comment gives.
The harness, tools/src/aisnap_test.c, gets the same field list as a
generated table of offsetof and sizeof, so each side writes and dumps a
field at its own offset, and a pointer prints as the object and field it
points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot, the snapshots themselves, the route manager's,
the world's and the cop manager's pointer moves, the actions'
constructors, QuickSpline's SetNumControlPoints and BeltMover's empty
ClearCalculatedVariables. Recorded on both sides, as lines both print: a
recording vtable (the controllers' drivers, the RigidBody's
ComputeAuxiliaries) and the new action (bOMalloc in retail, bSlotOMalloc
in the port), a block named N0, N1, ... that a `dumpa` gives its class.
The world, the routes, the cop manager's roadblocks and the players are
set up by ops of their own on both sides.

What the linked port files reach outside the snapshots is stubbed by
tools/src/aisnap_stubs.c and aisnap_stubdata.c, which `--stubs` writes
from the link's undefined symbols; each stubbed function stops the run
with an UNREACHED line.

    python tools/aisnap_check.py
    python tools/aisnap_check.py --stubs
    python tools/aisnap_check.py --fields [CLASS]
    python tools/aisnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/aisnap_check.py --dump out/aisnap
"""
import argparse
import os
import random
import re
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carsnap_check as csc             # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import retail_model                     # noqa: E402
from carsnap_check import (fill, fl, i32, i16, i8, cycle, flatten,  # noqa
                           path_off, alloc_size)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "aisnap_test.c"
STUBS = ROOT / "tools" / "src" / "aisnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "aisnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in (
    "replay.c", "p32.c", "vtable.c",
    "average.c", "drivetarget.c", "cardriver.c", "psychodriver.c",
    "realdriver.c", "drivinglocation.c", "drivingchoice.c", "airoute.c",
    "nearbycar.c", "aiaction.c", "aiactions.c", "aicarcontroller.c",
    "aidriver.c", "trafficdriver.c", "realcontroller.c", "copdriver.c",
    "beltmover.c", "mellowmover.c", "spline.c", "quickspline.c",
    "carcontroller.c", "world.c", "trackroute.c", "copmanager.c",
    "rigidbody.c", "wheel.c", "aerodynamics.c", "physicscar.c",
    "emath.c", "bmatrix.c", "bvector.c", "bmath.c", "bmathtab.c",
    "table.c", "bmem.c", "bticker.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
P_COP_MANAGER = GP - 15620
PLAYERS_BY_NUMBER = GP - 20936
TRACK_ROUTE_MANAGER = 0x00314438
TRACK_ROUTES = TRACK_ROUTE_MANAGER + 16
S_OMALLOC = 0x00257c80

WORLD_SIZE = 1024
ROUTE_SIZE = 115752
ROUTE_POINTS = 1064
ROUTE_POINT_SIZE = 112
ROUTE_MAX_POINTS = 1024
ROADBLOCKS = 320
ROADBLOCK_SIZE = 120
COPMANAGER_SIZE = 8192
PLAYER_SIZE = 64
ACTION_SIZE = 640

# ================================================================ the layout

csc.HEADERS.update({
    "DriveTarget": "drivetarget.h",
    "CarDriver": "cardriver.h", "PsychoDriver": "psychodriver.h",
    "RealDriver": "realdriver.h",
    "Average": "average.h", "PidError": "average.h",
    "DrivingLocation": "drivinglocation.h",
    "DrivingChoice": "drivingchoice.h",
    "NearestRoutePointInfo": "airoute.h",
    "NearbyCar": "nearbycar.h",
    "NearbyCarList": "nearbycar.h", "DrivingInformation": "nearbycar.h",
    "AIPlan": "aiaction.h", "AIAction": "aiaction.h",
    "AIActionJustDrive": "aiactions.h", "AIActionDraft": "aiactions.h",
    "AIActionNudgeCar": "aiactions.h", "AIActionBlock": "aiactions.h",
    "AIActionAccidentRecovery": "aiactions.h", "AIActionPass": "aiactions.h",
    "AIActionAvoidCars": "aiactions.h", "AIActionPullOver": "aiactions.h",
    "AIActionIJustGotHit": "aiactions.h",
    "AIActionGetUnstuck": "aiactions.h",
    "AIActionAvoidRoadBlock": "aiactions.h",
    "AICarController": "aicarcontroller.h", "AIDriver": "aidriver.h",
    "TrafficDriver": "trafficdriver.h",
    "TrackedController": "carcontroller.h",
    "RealController": "realcontroller.h",
    "CopDriver": "copdriver.h", "CopMover": "copdriver.h",
    "BeltMover": "beltmover.h", "MellowMover": "mellowmover.h",
    "Mellovator": "mellowmover.h", "MellovatorState": "mellowmover.h",
    "Spline": "spline.h", "QuickSpline": "quickspline.h",
})
csc.MACROS.update({"DRIVETARGET_MAX_POINTS": 20, "NEARBYCARLIST_MAX": 16,
                   "AICC_NUM_STICKY_DECISIONS": 8,
                   "REALCONTROLLER_PREVIOUS_POINTS": 4})
for _t in ("DrivingChoiceType", "PlanStatus", "AIActionType",
           "eCopMoverState", "eCopDriverStates", "SplineType",
           "QuickSplineEndPointType", "QuickSplineBasisType",
           "JoystickPort"):
    csc.TYPES[_t] = (4, False)
csc.RETAIL_SIZE.update({"CarDriver": 560, "DriveTarget": 528, "Average": 16,
                        "MellovatorState": 16, "NearbyCar": 28,
                        "DrivingLocation": 16, "DrivingChoice": 12,
                        "PidError": 40, "AIPlan": 20,
                        "NearestRoutePointInfo": 8})

# The records a script can make, in the order of the generated table.
CLASSES = ["RigidBody", "Wheel", "Aerodynamics", "Car", "CarController",
           "Average", "PidError", "DriveTarget", "CarDriver", "PsychoDriver",
           "RealDriver", "DrivingLocation", "DrivingChoice",
           "NearestRoutePointInfo", "NearbyCarList", "DrivingInformation",
           "AIPlan", "AIAction", "AIActionJustDrive", "AIActionDraft",
           "AIActionNudgeCar", "AIActionBlock", "AIActionAccidentRecovery",
           "AIActionPass", "AIActionAvoidCars", "AIActionPullOver",
           "AIActionIJustGotHit", "AIActionGetUnstuck",
           "AIActionAvoidRoadBlock", "AICarController", "AIDriver",
           "TrafficDriver", "TrackedController", "RealController",
           "CopDriver", "CopMover", "BeltMover", "MellowMover", "Mellovator",
           "Spline", "QuickSpline"]

# The actions by type: class, `call` name, table, the pointer field.
ACTIONS = [
    (0, "AIActionPass", "pass", "Pass", "CarToPass"),
    (1, "AIActionAvoidCars", "avoidcars", "AvoidCars", "CarToAvoid"),
    (2, "AIActionDraft", "draft", "Draft", None),
    (3, "AIActionBlock", "block", "Block", "CarToBlock"),
    (4, "AIActionNudgeCar", "nudgecar", "NudgeCar", "CarToNudge"),
    (5, "AIActionJustDrive", "justdrive", "JustDrive", None),
    (6, "AIActionPullOver", "pullover", "PullOver", None),
    (7, "AIActionGetUnstuck", "getunstuck", "GetUnstuck", None),
    (8, "AIActionAvoidRoadBlock", "avoidroadblock", "AvoidRoadBlock",
     "RoadBlockToAvoid"),
    (9, "AIActionIJustGotHit", "ijustgothit", "IJustGotHit", "CarIHit"),
    (10, "AIActionAccidentRecovery", "accidentrecovery", "AccidentRecovery",
     None),
]

# ============================================================ the scenarios


def floats(n, seed):
    rng = random.Random("floats:%s" % seed)
    return fl(*[rng.randint(-96, 96) / 8.0 for _ in range(n)])


def buf(ref, nfloats, seed):
    """A block of floats, `ref`, filled."""
    return ["newb|%s|%d" % (ref, 4 * nfloats),
            "setb|%s|0|%s" % (ref, floats(nfloats, seed))]


def average_lines(a, d, slots, samples=None):
    out = ["set|%s|nSlots|%s" % (a, i8(slots)),
           "link|%s|pData|%s|-" % (a, d)]
    if samples is not None:
        out.append("set|%s|nSamples|%s" % (a, i8(samples)))
    return out


def sc_average():
    out = []
    for k, (slots, samples, rslots) in enumerate(((4, 3, 6), (5, 0, 2),
                                                  (200, 7, 9))):
        a, d = "av%d" % k, "avd%d" % k
        out += ["# average %d" % k] + buf(d, 256, d)
        out += ["new|%s|Average" % a] + fill(a, "Average", "a") + \
            average_lines(a, d, slots, samples)
        refill = fill(a, "Average", "b") + average_lines(a, d, rslots) + \
            ["setb|%s|0|%s" % (d, floats(256, d + "b"))]
        # A verify leaves the average as it is.
        out += cycle(["call|average|" + a], ["dump|" + a, "dump|" + d],
                     refill, ["setb|%s|4|%s" % (d, fl(3.25)),
                              "set|%s|fAverage|%s" % (a, fl(99.0))])
    # PidError: two averages.
    out += ["# piderror"] + buf("pei", 256, "pei") + buf("ped", 256, "ped")
    out += ["new|pe|PidError"] + fill("pe", "PidError", "a") + \
        pid_links("pe", 3, 5)
    out += cycle(["call|piderror|pe"], ["dump|pe", "dump|pei", "dump|ped"],
                 fill("pe", "PidError", "b") + pid_links("pe", 1, 7),
                 ["set|pe|fPreviousError|" + fl(-0.5)])
    return out


def dt_lines(ref, path, n, ttype=None):
    out = ["set|%s|%sNumPoints|%s" % (ref, path, i8(n))]
    if ttype is not None:
        out.append("set|%s|%sTType|%s" % (ref, path, i32(ttype)))
    return out


def sc_drivetarget():
    out = []
    for k, (n, rn) in enumerate(((3, 5), (20, -1), (-1, 2), (0, 20))):
        t = "dt%d" % k
        out += ["# drivetarget %d" % k, "new|%s|DriveTarget" % t]
        out += fill(t, "DriveTarget", "a") + dt_lines(t, "", n, 0x1203 + k)
        out += cycle(["call|drivetarget|" + t], ["dump|" + t],
                     fill(t, "DriveTarget", "b") + dt_lines(t, "", rn),
                     ["set|%s|Length|%s" % (t, fl(9.5))])
    return out


def pid(ref, seed):
    """A PidError `ref` with its two buffers."""
    return (buf(ref + "i", 8, ref + seed) + buf(ref + "d", 8, ref + seed + "d")
            + ["new|%s|PidError" % ref] + fill(ref, "PidError", seed) +
            pid_links(ref, 3, 5))


def pid_links(ref, ni, nd):
    return ["set|%s|aIntegral.nSlots|%s" % (ref, i8(ni)),
            "set|%s|aDerivative.nSlots|%s" % (ref, i8(nd)),
            "link|%s|aIntegral.pData|%si|-" % (ref, ref),
            "link|%s|aDerivative.pData|%sd|-" % (ref, ref)]


def psycho(p, seed):
    out = ["new|%s|PsychoDriver" % p]
    for e in ("b", "h", "v"):
        out += pid(p + e, seed)
    out += psycho_fill(p, seed, 3)
    return out


def psycho_fill(p, seed, n):
    out = fill(p, "PsychoDriver", seed) + dt_lines(p, "Base.MyDriveTarget.",
                                                    n)
    out += ["vt|%s|Base._vtable|PsychoDriver" % p,
            "link|%s|pBodyError|%sb|-" % (p, p),
            "link|%s|pHeadingError|%sh|-" % (p, p),
            "link|%s|pVelocityError|%sv|-" % (p, p)]
    return out


def psycho_dumps(p):
    out = ["dump|" + p]
    for e in ("b", "h", "v"):
        out += ["dump|%s%s" % (p, e), "dump|%s%si" % (p, e),
                "dump|%s%sd" % (p, e)]
    return out


def realdriver_fill(r, seed, n, port):
    return (fill(r, "RealDriver", seed) +
            dt_lines(r, "Base.MyDriveTarget.", n) +
            ["set|%s|Port|%s" % (r, i32(port)),
             "vt|%s|Base._vtable|RealDriver" % r])


def sc_drivers():
    out = []
    # CarDriver: gears that do and do not fit a signed byte.
    for k, (g, rg) in enumerate(((-3, 200), (127, -128))):
        c = "cdr%d" % k
        fix = ["set|%s|DesiredGear|%s" % (c, i32(g)),
               "vt|%s|_vtable|CarDriver" % c]
        out += ["# cardriver %d" % k, "new|%s|CarDriver" % c]
        out += fill(c, "CarDriver", "a") + dt_lines(c, "MyDriveTarget.", 2) + \
            fix
        refill = (fill(c, "CarDriver", "b") +
                  dt_lines(c, "MyDriveTarget.", 4) +
                  ["set|%s|DesiredGear|%s" % (c, i32(rg))])
        out += cycle(["call|cardriver|" + c], ["dump|" + c], refill,
                     ["set|%s|Steering|%s" % (c, i16(77))])
    out += ["# psychodriver"] + psycho("ps", "a")
    out += cycle(["call|psychodriver|ps"], psycho_dumps("ps"),
                 psycho_fill("ps", "b", 1) +
                 pid_links("psb", 2, 6) + pid_links("psh", 4, 1),
                 ["set|ps|EBrakeTimer|" + fl(2.5)])
    out += ["# realdriver", "new|rd|RealDriver"] + \
        realdriver_fill("rd", "a", 1, 0x1ff)
    out += cycle(["call|realdriver|rd"], ["dump|rd"],
                 realdriver_fill("rd", "b", 3, 2),
                 ["set|rd|JoyBrakeAnalog|" + i8(9)])
    # CarController through each table.
    out += ["# carcontroller", "new|ctl|CarController",
            "link|ctl|Driver|ps|-"]
    out += cycle(["call|carcontroller|ctl"], ["dump|ctl"] +
                 psycho_dumps("ps"),
                 psycho_fill("ps", "c", 2) + pid_links("psv", 1, 1))
    out += ["link|ctl|Driver|rd|-"]
    out += cycle(["call|carcontroller|ctl"], ["dump|ctl", "dump|rd"],
                 realdriver_fill("rd", "c", 0, -7))
    out += ["link|ctl|Driver|cdr0|-"]
    out += cycle(["call|carcontroller|ctl"], ["dump|ctl", "dump|cdr0"],
                 fill("cdr0", "CarDriver", "c") +
                 dt_lines("cdr0", "MyDriveTarget.", 1))
    return out


def sc_world():
    """The cars, the routes, the roadblocks and the players the rest
    point at."""
    out = ["# the world"]
    for c, num in (("c0", 2), ("c1", 5), ("c2", 300), ("c3", 44),
                   ("c4", 200)):
        out += ["new|%s|Car" % c, "set|%s|DriverNumber|%s" % (c, i16(num))]
    out += ["world|c0,c1,c2,c3,c4",
            "route|r0|0|12", "route|r1|3|12",
            "copmgr|rb|4",
            "player|pl0|0|0", "player|pl1|1|1",
            "newb|drv|4096", "drvvt|drv|rec"]
    return out


def loc_lines(ref, p, route, point):
    return ["link|%s|%spRoute|%s|-" % (ref, p, route),
            "link|%s|%spRoutePoint|%s|-" % (ref, p, point)]


def sc_routes():
    out = []
    # Route and point; a point with no route (taking drops it); a route
    # with no point; neither.
    cases = (("r1", "r1p[5]"), ("0", "r0p[1]"), ("r0", "0"), ("0", "0"))
    for k, (route, point) in enumerate(cases):
        d = "dl%d" % k
        out += ["# drivinglocation %d" % k, "new|%s|DrivingLocation" % d]
        out += fill(d, "DrivingLocation", "a") + loc_lines(d, "", route,
                                                             point)
        out += cycle(["call|drivinglocation|" + d], ["dump|" + d],
                     fill(d, "DrivingLocation", "b") +
                     loc_lines(d, "", "r0", "r0p[2]"),
                     ["link|%s|pRoutePoint|r1p[6]|-" % d])
    for k, (route, point) in enumerate(cases):
        d = "nr%d" % k
        lk = ["link|%s|Route|%s|-" % (d, route),
              "link|%s|Point|%s|-" % (d, point)]
        out += ["# nrpi %d" % k, "new|%s|NearestRoutePointInfo" % d] + lk
        out += cycle(["call|nrpi|" + d], ["dump|" + d],
                     ["link|%s|Route|r1|-" % d, "link|%s|Point|r1p[3]|-" % d])
    for k, point in enumerate(("r1p[4]", "0", "r0p[11]")):
        t = "tc%d" % k
        lk = ["link|%s|Base.Driver|drv|-" % t,
              "link|%s|RoutePoint|%s|-" % (t, point)]
        out += ["# tracked %d" % k, "new|%s|TrackedController" % t]
        out += fill(t, "TrackedController", "a") + lk
        out += cycle(["call|tracked|" + t], ["dump|" + t],
                     fill(t, "TrackedController", "b") +
                     ["link|%s|Base.Driver|drv|-" % t,
                      "link|%s|RoutePoint|r0p[7]|-" % t],
                     ["set|%s|PrevSpeed|%s" % (t, fl(1.75))])
    return out


def sc_choices():
    out = []
    for k, car in enumerate(("c1", "0", "c2", "c4")):
        d = "dc%d" % k
        out += ["# drivingchoice %d" % k, "new|%s|DrivingChoice" % d]
        out += fill(d, "DrivingChoice", "a") + \
            ["link|%s|pCar|%s|-" % (d, car)]
        out += cycle(["call|drivingchoice|" + d], ["dump|" + d],
                     fill(d, "DrivingChoice", "b") +
                     ["link|%s|pCar|c0|-" % d],
                     ["link|%s|pCar|c3|-" % d])
    for k, (n, rn) in enumerate(((3, 5), (16, 0), (-1, 2))):
        d = "nl%d" % k
        out += ["# nearbycarlist %d" % k, "new|%s|NearbyCarList" % d]
        out += fill(d, "NearbyCarList", "a") + \
            ["set|%s|NumCarsInArray|%s" % (d, i32(n))]
        out += cycle(["call|nearbycarlist|" + d], ["dump|" + d],
                     fill(d, "NearbyCarList", "b") +
                     ["set|%s|NumCarsInArray|%s" % (d, i32(rn))],
                     ["set|%s|MyHalfSizeD|%s" % (d, fl(0.625))])
    d = "di"
    lk = (["set|di|MyNearbyCarList.NumCarsInArray|" + i32(4)] +
          loc_lines(d, "MyDrivingLocation.", "r0", "r0p[3]") +
          ["link|di|MyDrivingChoice.pCar|c1|-"])
    out += ["# drivinginfo", "new|di|DrivingInformation"]
    out += fill(d, "DrivingInformation", "a") + lk
    out += cycle(["call|drivinginfo|di"], ["dump|di"],
                 fill(d, "DrivingInformation", "b") +
                 ["set|di|MyNearbyCarList.NumCarsInArray|" + i32(2)] +
                 loc_lines(d, "MyDrivingLocation.", "r1", "r1p[0]") +
                 ["link|di|MyDrivingChoice.pCar|c3|-"])
    return out


def action_fill(ref, cls, vt, ptr, seed, n, target, typ=None):
    out = fill(ref, cls, seed) + dt_lines(ref, "Base.PointsToDrive.", n)
    out += ["vt|%s|Base.Base._vtable|%s" % (ref, vt)]
    if typ is not None:
        out += ["set|%s|Base.Type|%s" % (ref, i32(typ))]
    if ptr:
        out += ["link|%s|%s|%s|-" % (ref, ptr, target)]
    return out


TARGETS = {"RoadBlockToAvoid": ("rb[2]", "rb[0]")}


def sc_actions():
    out = ["# aiplan", "new|plan|AIPlan"] + fill("plan", "AIPlan", "a") + \
        ["vt|plan|_vtable|AIPlan"]
    out += cycle(["call|aiplan|plan"], ["dump|plan"],
                 fill("plan", "AIPlan", "b"),
                 ["set|plan|DeltaTime|" + fl(0.25)])
    out += ["# aiaction", "new|act|AIAction"] + fill("act", "AIAction", "a")
    out += dt_lines("act", "PointsToDrive.", 2) + ["vt|act|Base._vtable|AIAction"]
    out += cycle(["call|aiaction|act"], ["dump|act"],
                 fill("act", "AIAction", "b") +
                 dt_lines("act", "PointsToDrive.", 6),
                 ["set|act|Score|" + i32(-9)])
    # The eleven, each through its own function.
    for typ, cls, fn, vt, ptr in ACTIONS:
        a = "a%s" % fn
        t1, t2 = TARGETS.get(ptr, ("c2", "c1"))
        out += ["# %s" % fn, "new|%s|%s" % (a, cls)]
        out += action_fill(a, cls, vt, ptr, "a", 3, t1, typ)
        out += cycle(["call|%s|%s" % (fn, a)], ["dump|" + a],
                     action_fill(a, cls, vt, ptr, "b", 1, t2),
                     ["set|%s|Base.DesiredSpeed|%s" % (a, fl(31.5))])
    return out


def sc_action_pointer():
    out = ["# actionptr: none", "newb|hold|16"]
    out += cycle(["call|actionptr|hold"], ["dumpp|hold|-"],
                 ["link|hold|-|aaccidentrecovery|-"])
    # Each type, restored over none: a new action of that type.
    for typ, cls, fn, vt, ptr in ACTIONS:
        h, a = "hold%d" % typ, "pa%d" % typ
        t1 = TARGETS.get(ptr, ("c1", "c1"))[0]
        out += ["# actionptr %s" % fn, "newb|%s|16" % h,
                "new|%s|%s" % (a, cls)]
        out += action_fill(a, cls, vt, ptr, "a", 2, t1, typ)
        out += ["link|%s|-|%s|-" % (h, a)]
        out += cycle(["call|actionptr|" + h], ["dumpa|%s|-|%s" % (h, cls)],
                     ["link|%s|-|0|-" % h])
    # A type past the last, restored over none (nothing) and over an
    # action (kept); a type whose word is past it but whose byte is not.
    for k, (typ, over) in enumerate(((11, "0"), (40, "pa2"), (0x103, "-"))):
        h, a = "holdx%d" % k, "px%d" % k
        out += ["# actionptr type %d" % typ, "newb|%s|16" % h,
                "new|%s|AIActionJustDrive" % a]
        out += action_fill(a, "AIActionJustDrive", "JustDrive", None, "a", 1,
                           None, typ)
        out += ["link|%s|-|%s|-" % (h, a)]
        refill = [] if over == "-" else ["link|%s|-|%s|-" % (h, over)]
        out += cycle(["call|actionptr|" + h],
                     ["dumpa|%s|-|AIActionJustDrive" % h], refill)
    return out


def aicc_lines(c, p, seed, act, player, k):
    """An AICarController at `p` in `c`: its links and the fields that
    count things."""
    cars = ("c0", "c1", "c2", "c3", "c4")
    out = ["link|%s|%sBase.Driver|drv|-" % (c, p),
           "link|%s|%sBase.pCar|%s|-" % (c, p, cars[k % 5]),
           "set|%s|%sMyCurrentDrivingInformation.MyNearbyCarList."
           "NumCarsInArray|%s" % (c, p, i32(3)),
           "link|%s|%sMyCurrentDrivingInformation.MyDrivingLocation.pRoute|"
           "%s|-" % (c, p, ("r1", "r0")[k & 1]),
           "link|%s|%sMyCurrentDrivingInformation.MyDrivingLocation."
           "pRoutePoint|%s|-" % (c, p, ("r1p[2]", "r0p[9]")[k & 1]),
           "link|%s|%sMyCurrentDrivingInformation.MyDrivingChoice.pCar|%s|-"
           % (c, p, cars[(k + 1) % 5]),
           "link|%s|%sCarToExcludeFromCollisionPrediction|%s|-"
           % (c, p, cars[(k + 3) % 5]),
           "link|%s|%sCurrentAction|%s|-" % (c, p, act),
           "link|%s|%spProgress|%sprog|-" % (c, p, c),
           "link|%s|%spGlueCar|%s|-" % (c, p, cars[(k + 2) % 5]),
           "link|%s|%spCatchupPlayer|%s|-" % (c, p, player),
           "link|%s|%spDeltaLineSpeed|%sdls|-" % (c, p, c)]
    out += average_lines(c + "prog", c + "progd", 3 + k)
    out += average_lines(c + "dls", c + "dlsd", 2 + k)
    return out


def aicc_objects(c, seed):
    out = buf(c + "progd", 16, c + "p") + buf(c + "dlsd", 16, c + "d")
    out += ["new|%sprog|Average" % c, "new|%sdls|Average" % c]
    out += fill(c + "prog", "Average", seed) + fill(c + "dls", "Average", seed)
    return out


def aicc_dumps(c, extra=()):
    return ["dump|" + c, "dump|%sprog" % c, "dump|%sdls" % c,
            "dump|%sprogd" % c, "dump|%sdlsd" % c] + list(extra)


def action_obj(ref, typ, seed):
    _, cls, fn, vt, ptr = ACTIONS[typ]
    t1 = TARGETS.get(ptr, ("c3", "c3"))[0]
    return ["new|%s|%s" % (ref, cls)] + \
        action_fill(ref, cls, vt, ptr, seed, 2, t1, typ)


def sc_controllers():
    out = []
    # AICarController: restored over an action of another type, which the
    # restore replaces with a new one of the type it took; the catchup
    # player by number, none, and one whose number's byte is negative.
    players = ("pl1", "0", "plm")
    out += ["player|plm|0|255"]
    for k, (t1, t2) in enumerate(((0, 5), (8, 9), (6, 6))):
        c = "acc%d" % k
        act, act2 = "acc%da" % k, "acc%db" % k
        out += ["# aicarcontroller %d" % k] + action_obj(act, t1, "a") + \
            action_obj(act2, t2, "b") + aicc_objects(c, "a")
        out += ["new|%s|AICarController" % c] + \
            fill(c, "AICarController", "a") + \
            aicc_lines(c, "", "a", act, players[k], k)
        refill = fill(c, "AICarController", "b") + \
            aicc_lines(c, "", "b", act2, players[(k + 1) % 3], k + 1)
        out += cycle(["call|aicarcontroller|" + c],
                     aicc_dumps(c, ["dumpa|%s|CurrentAction|%s"
                                    % (c, ACTIONS[t1][1])]),
                     refill,
                     ["set|%s|fLastProgress|%s" % (c, fl(6.5))])
    # Put back the catchup players this broke: slot 0 is plm's now.
    out += ["player|pl0b|0|0"]
    out += ["# aidriver"] + action_obj("aida", 1, "a") + \
        action_obj("aidb", 4, "b") + aicc_objects("aid", "a") + \
        buf("aidvd", 16, "aidv") + ["new|aidv|Average"] + \
        fill("aidv", "Average", "a")
    fix = ["link|aid|CarToPurposefullyNotAvoid|c4|-",
           "link|aid|pVeryStuckProgress|aidv|-"] + \
        average_lines("aidv", "aidvd", 4)
    out += ["new|aid|AIDriver"] + fill("aid", "AIDriver", "a") + \
        aicc_lines("aid", "Base.", "a", "aida", "pl1", 0) + fix
    refill = fill("aid", "AIDriver", "b") + \
        aicc_lines("aid", "Base.", "b", "aidb", "pl0b", 1) + \
        ["link|aid|CarToPurposefullyNotAvoid|c1|-",
         "link|aid|pVeryStuckProgress|aidv|-"] + \
        average_lines("aidv", "aidvd", 6)
    out += cycle(["call|aidriver|aid"],
                 aicc_dumps("aid", ["dump|aidv", "dump|aidvd",
                                    "dumpa|aid|Base.CurrentAction|"
                                    "AIActionAvoidCars"]),
                 refill,
                 ["link|aid|CarToPurposefullyNotAvoid|c0|-"])
    out += ["# trafficdriver"] + action_obj("tda", 5, "a") + \
        action_obj("tdb", 10, "b") + aicc_objects("td", "a")
    out += ["new|td|TrafficDriver"] + fill("td", "TrafficDriver", "a") + \
        aicc_lines("td", "Base.", "a", "tda", "0", 2)
    refill = fill("td", "TrafficDriver", "b") + \
        aicc_lines("td", "Base.", "b", "tdb", "pl1", 3)
    out += cycle(["call|trafficdriver|td"],
                 aicc_dumps("td", ["dumpa|td|Base.CurrentAction|"
                                   "AIActionJustDrive"]),
                 refill, ["set|td|PickLowNumberedRoutes|" + i32(0)])
    return out


def qs_lines(q, ept, cnt):
    return ["set|%s|EndPointType|%s" % (q, i32(ept)),
            "set|%s|NumControlPoints|%s" % (q, i16(cnt)),
            "link|%s|pControlPoints|%sp|-" % (q, q)]


def sc_realcontroller():
    out = ["# realcontroller"] + buf("rcqsp", 256, "rcqsp") + \
        buf("rcavd", 16, "rcavd")
    out += ["new|rcqs|QuickSpline", "new|rcav|Average", "new|rc|RealController"]
    fix = (["link|rc|Base.Base.Driver|drv|-", "link|rc|Base.RoutePoint|r1p[1]|-",
            "link|rc|LateralVelocityWRTLineAverage|rcav|-",
            "link|rc|DrivingLineSpline|rcqs|-",
            "link|rc|PreviousRoutePoints[0].Route|r0|-",
            "link|rc|PreviousRoutePoints[0].Point|r0p[4]|-",
            "link|rc|PreviousRoutePoints[1].Route|r1|-",
            "link|rc|PreviousRoutePoints[1].Point|r1p[6]|-"] +
           average_lines("rcav", "rcavd", 5))
    out += fill("rcqs", "QuickSpline", "a") + qs_lines("rcqs", 1, 5)
    out += fill("rcav", "Average", "a")
    out += fill("rc", "RealController", "a") + fix + \
        ["set|rc|NumPreviousRoutePoints|" + i32(3)]
    refill = fill("rc", "RealController", "b") + fix + \
        ["set|rc|NumPreviousRoutePoints|" + i32(4),
         "link|rc|PreviousRoutePoints[2].Route|r1|-",
         "link|rc|PreviousRoutePoints[2].Point|r1p[8]|-"] + \
        fill("rcqs", "QuickSpline", "b") + qs_lines("rcqs", 2, 7)
    out += cycle(["call|realcontroller|rc"],
                 ["dump|rc", "dump|rcqs", "dump|rcav", "dump|rcavd"],
                 refill, ["set|rc|PreviousLateralOffsetFromLine|" +
                          fl(-2.25)])
    # No previous points.
    out += ["set|rc|NumPreviousRoutePoints|" + i32(0)]
    out += cycle(["call|realcontroller|rc"], ["dump|rc", "dump|rcqs"],
                 fill("rcqs", "QuickSpline", "c") + qs_lines("rcqs", 0, 3))
    out += ["# copdriver", "new|cop|CopDriver"] + fill("cop", "CopDriver", "a")
    fix = ["link|cop|Base.Base.Driver|drv|-",
           "link|cop|Base.RoutePoint|r0p[2]|-"]
    out += fix + ["set|cop|nCopIndex|" + i32(0x181)]
    out += cycle(["call|copdriver|cop"], ["dump|cop"],
                 fill("cop", "CopDriver", "b") + fix +
                 ["link|cop|Base.RoutePoint|r1p[10]|-"],
                 ["set|cop|fPatrolSpeed|" + fl(12.0)])
    out += ["# copmover", "new|cm|CopMover"] + fill("cm", "CopMover", "a")
    out += cycle(["call|copmover|cm"], ["dump|cm"], fill("cm", "CopMover", "b"),
                 ["set|cm|aDesiredFacingAngle|" + i16(0x4000)])
    return out


def sc_movers():
    out = ["# beltmover"] + buf("bmqsp", 256, "bmqsp") + \
        buf("bmcu", 12, "bmcu") + buf("bmca", 24, "bmca") + \
        buf("bmcs", 24, "bmcs") + buf("bmavd", 16, "bmavd")
    out += ["new|bmqs|QuickSpline", "new|bmav|Average", "new|bmwh|Wheel|4",
            "new|bm|BeltMover"]
    links = (["link|bm|pSpline|bmqs|-", "link|bm|pCubicU|bmcu|-",
              "link|bm|pCubicAng|bmca|-", "link|bm|pCubicSlide|bmcs|-",
              "link|bm|pAvgAccel|bmav|-"] +
             ["link|bm|pWheels[%d]|bmwh[%d]|-" % (i, i) for i in range(4)])

    def bm_fill(seed, cnt, slots):
        o = fill("bm", "BeltMover", seed) + links
        o += fill("bmqs", "QuickSpline", seed) + qs_lines("bmqs", 1, cnt)
        o += fill("bmav", "Average", seed) + average_lines("bmav", "bmavd",
                                                           slots)
        for i in range(4):
            o += fill("bmwh[%d]" % i, "Wheel", seed)
        for b, n in (("bmcu", 12), ("bmca", 24), ("bmcs", 24)):
            o += ["setb|%s|0|%s" % (b, floats(n, b + seed))]
        return o
    out += bm_fill("a", 4, 3)
    out += cycle(["call|beltmover|bm"],
                 ["dump|bm", "dump|bmqs", "dump|bmqsp", "dump|bmcu",
                  "dump|bmca", "dump|bmcs", "dump|bmav", "dump|bmavd",
                  "dump|bmwh"],
                 bm_fill("b", 6, 5), ["setb|bmca|40|" + fl(-7.0)])
    out += ["# mellovator", "new|mel|Mellovator"] + fill("mel", "Mellovator",
                                                         "a")
    gears = ["set|mel|CurrentGear|" + i32(-2),
             "set|mel|DesiredGear|" + i32(130)]
    out += gears
    out += cycle(["call|mellovator|mel"], ["dump|mel"],
                 fill("mel", "Mellovator", "b"),
                 ["set|mel|RPM|" + fl(4500.0)])
    out += ["# mellowmover", "new|mmrb|RigidBody", "new|mmel|Mellovator",
            "new|mmae|Aerodynamics", "new|mmwh|Wheel|4", "new|mm|MellowMover"]
    links = (["link|mm|pBody|mmrb|-", "link|mm|pMellovator|mmel|-",
              "link|mm|pAerodynamics|mmae|-", "vt|mmrb|_vtable|rec"] +
             ["link|mm|pWheels[%d]|mmwh[%d]|-" % (i, i) for i in range(4)])

    def mm_fill(seed):
        o = fill("mm", "MellowMover", seed) + fill("mmrb", "RigidBody", seed)
        o += fill("mmel", "Mellovator", seed) + fill("mmae", "Aerodynamics",
                                                     seed)
        for i in range(4):
            o += fill("mmwh[%d]" % i, "Wheel", seed)
        return o + links
    out += mm_fill("a")
    out += cycle(["call|mellowmover|mm"],
                 ["dump|mm", "dump|mmrb", "dump|mmel", "dump|mmae",
                  "dump|mmwh"],
                 mm_fill("b"), ["set|mmel|Throttle|" + fl(0.5)])
    return out


def sc_splines():
    out = []
    for k, (cnt, cal, table) in enumerate(((5, 37, True), (0, 9, True),
                                           (3, 12, False))):
        s = "sp%d" % k
        out += ["# spline %d" % k] + buf(s + "cp", 256, s + "cp") + \
            buf(s + "ct", 64, s + "ct")
        lk = ["link|%s|pControlPoints|%scp|-" % (s, s)]
        if table:
            lk += ["link|%s|pCalTable|%sct|-" % (s, s)]
        out += ["new|%s|Spline" % s] + fill(s, "Spline", "a") + lk + \
            ["set|%s|NumControlPoints|%s" % (s, i32(cnt)),
             "set|%s|CalTableSize|%s" % (s, i32(cal))]
        refill = fill(s, "Spline", "b") + lk + \
            ["set|%s|NumControlPoints|%s" % (s, i32(cnt + 2)),
             "set|%s|CalTableSize|%s" % (s, i32(cal + 20)),
             "setb|%sct|0|%s" % (s, floats(64, s + "ctb"))]
        out += cycle(["call|spline|" + s],
                     ["dump|" + s, "dump|%scp" % s, "dump|%sct" % s], refill,
                     ["setb|%sct|0|%s" % (s, i8(0x5a))])
    # Each end-point type, three and four floats a point, and none.
    for k, (n, ept, cnt, rcnt) in enumerate(((3, 0, 4, 6), (4, 1, 5, 2),
                                             (3, 2, 3, 3), (4, 7, 6, 1),
                                             (3, 1, 0, 4))):
        q = "qs%d" % k
        out += ["# quickspline %d" % k] + buf(q + "p", 256, q + "p")
        out += ["new|%s|QuickSpline" % q] + fill(q, "QuickSpline", "a") + \
            qs_lines(q, ept, cnt)
        refill = fill(q, "QuickSpline", "b") + qs_lines(q, ept, rcnt) + \
            ["setb|%sp|0|%s" % (q, floats(256, q + "pb"))]
        out += cycle(["call|quickspline|%s|%d" % (q, n)],
                     ["dump|" + q, "dump|%sp" % q], refill,
                     ["setb|%sp|8|%s" % (q, fl(0.375))])
    return out


def script():
    return (sc_average() + sc_drivetarget() + sc_drivers() + sc_world() +
            sc_routes() + sc_choices() + sc_actions() + sc_action_pointer() +
            sc_controllers() + sc_realcontroller() + sc_movers() +
            sc_splines())


# =================================================================== model

# The retail functions each `call` names.
FNS = {
    "average": 0x0018fe38, "piderror": 0x0018ff98,
    "drivetarget": 0x0021ba50, "cardriver": 0x00130958,
    "psychodriver": 0x00139980, "realdriver": 0x0013aeb8,
    "drivinglocation": 0x00239cf0, "drivingchoice": 0x00241b88,
    "nrpi": 0x001cd460, "nearbycarlist": 0x001937e0,
    "drivinginfo": 0x00193ea0, "aiplan": 0x001c6088,
    "aiaction": 0x001c6198, "actionptr": 0x001c6268,
    "aicarcontroller": 0x00190438, "aidriver": 0x00130108,
    "trafficdriver": 0x0018c478, "tracked": 0x0023a0f0,
    "realcontroller": 0x0023a560, "copdriver": 0x001a2b58,
    "copmover": 0x001a0f20, "beltmover": 0x00204468,
    "mellowmover": 0x002198c8, "mellovator": 0x0021a3d8,
    "spline": 0x001892d8, "quickspline": 0x0023d208,
    "carcontroller": 0x001c00d0,
    "avoidcars": 0x001c6c48, "justdrive": 0x001c7400, "draft": 0x001c76d0,
    "pass": 0x001c7960, "nudgecar": 0x001c8078, "block": 0x001c81b0,
    "pullover": 0x001c8370, "getunstuck": 0x001c8bb8,
    "avoidroadblock": 0x001c96b8, "ijustgothit": 0x001c9cb8,
    "accidentrecovery": 0x001ca240,
}

# Retail's tables: each DoSnapshot's dataref, less 28 (a driver's slot 24)
# or 20 (an action's slot 16).
VT_RETAIL = {
    "CarDriver": 0x002ae868, "PsychoDriver": 0x002aec50,
    "RealDriver": 0x002aee30, "AIPlan": 0x002b7cd0, "AIAction": 0x002b7c90,
    "AvoidCars": 0x002b7c50, "JustDrive": 0x002b7b10, "Draft": 0x002b7bd0,
    "Pass": 0x002b7c10, "NudgeCar": 0x002b7b90, "Block": 0x002b7b50,
    "PullOver": 0x002b7ad0, "GetUnstuck": 0x002b7a50,
    "AvoidRoadBlock": 0x002b7a90, "IJustGotHit": 0x002b7a10,
    "AccidentRecovery": 0x002b79d0,
}


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        self.nact = 0
        self.vt.update(VT_RETAIL)
        self.vtname = {v: k for k, v in self.vt.items()}
        self.world = e.alloc(WORLD_SIZE, align=16)
        e.write(self.world, bytes(WORLD_SIZE))
        e.put32(P_CURRENT_WORLD, 0)
        e.put32(P_COP_MANAGER, 0)
        e.write(TRACK_ROUTES, bytes(4 * 70))
        e.write(PLAYERS_BY_NUMBER, bytes(8))

    # The new action: the pool's slot, as bytes until a dumpa names it.
    def omalloc(self, em):
        a = self.e.alloc(ACTION_SIZE, align=16)
        self.e.write(a, bytes(ACTION_SIZE))
        self.register("N%d" % self.nact, a, None, 1, ACTION_SIZE, ACTION_SIZE)
        self.nact += 1
        return a

    def ptr_at(self, r, path):
        ob, at = self.ref(r)
        if path == "-":
            return at
        f = self.field(ob.cls, path)
        assert f.kind == "ptr", (r, path)
        return at + f.roff

    def target(self, r, path):
        if r == "0":
            return 0
        ob, at = self.ref(r)
        if path == "-":
            return at
        if path.startswith("+"):
            return at + int(path[1:])
        return at + path_off(ob.cls, path)

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "link":
            e.put32(self.ptr_at(a[1], a[2]), self.target(a[3], a[4]))
        elif o == "world":
            e.write(self.world, bytes(WORLD_SIZE))
            cars = [] if a[1] == "-" else a[1].split(",")
            e.put32(self.world + 28, len(cars))
            for i, c in enumerate(cars):
                e.put32(self.world + 44 + 4 * i, self.ref(c)[1])
            e.put32(P_CURRENT_WORLD, self.world)
        elif o == "route":
            num, pts = int(a[2]), int(a[3])
            base = e.alloc(ROUTE_SIZE, align=16)
            e.write(base, bytes(ROUTE_SIZE))
            e.write(base + 10, struct.pack("<h", num))
            for i in range(pts):
                e.mem[base + ROUTE_POINTS + ROUTE_POINT_SIZE * i + 111] = \
                    num & 0xff
            e.put32(TRACK_ROUTES + 4 * num, base)
            self.register(a[1] + "p", base + ROUTE_POINTS, None,
                          ROUTE_MAX_POINTS, ROUTE_POINT_SIZE,
                          ROUTE_MAX_POINTS * ROUTE_POINT_SIZE)
            self.register(a[1], base, None, 1, ROUTE_SIZE, ROUTE_SIZE)
        elif o == "copmgr":
            n = int(a[2])
            base = e.alloc(COPMANAGER_SIZE, align=16)
            e.write(base, bytes(COPMANAGER_SIZE))
            e.put32(P_COP_MANAGER, base)
            self.register(a[1], base + ROADBLOCKS, None, n, ROADBLOCK_SIZE,
                          n * ROADBLOCK_SIZE)
        elif o == "player":
            base = e.alloc(PLAYER_SIZE, align=16)
            e.write(base, bytes(PLAYER_SIZE))
            e.put32(base + 16, int(a[3]))
            e.put32(PLAYERS_BY_NUMBER + 4 * int(a[2]), base)
            self.register(a[1], base, None, 1, PLAYER_SIZE, PLAYER_SIZE)
        elif o == "call":
            ob, at = self.ref(a[2])
            args = [at, S] + ([int(a[3])] if len(a) > 3 else [])
            self.call(FNS[a[1]], *args)
        elif o == "dumpp":
            self.emit("%s %s -> %s" % (a[1], a[2], self.label(
                e.u32(self.ptr_at(a[1], a[2])))))
        elif o == "dumpa":
            v = e.u32(self.ptr_at(a[1], a[2]))
            self.emit("%s %s -> %s" % (a[1], a[2], self.label(v)))
            for ob in self.objs:
                if v and ob.base == v:
                    if ob.cls is None:
                        ob.cls = a[3]
                    self.dump_obj(ob.id)
                    break
        else:
            csc.Model.op(self, a)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ============================================================ the harness

def c_fields():
    csc.CLASSES = CLASSES
    text = csc.c_fields().replace("tools/carsnap_check.py",
                                  "tools/aisnap_check.py")
    asserts = ['_Static_assert(sizeof(%s) <= ACTION_SLOT, "%s");'
               % (cls, cls) for _, cls, _, _, _ in ACTIONS]
    return text + NL.join(asserts) + NL


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "aisnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="aisnap_test"):
    return hostbuild.build(tmp, sources(tmp), name=name)


run_harness = csc.run_harness
diff = csc.diff
write_script = csc.write_script


# ================================================================ the stubs

class _BuildFailed(Exception):
    pass


def link_errors():
    """Build without the stub files: the symbols the link misses, and any
    error that is not one of those."""
    saved = hostbuild._fail
    box = {}

    def fail(err, what, quiet=False):
        box["err"] = err
        raise _BuildFailed(what)
    hostbuild._fail = fail
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                hostbuild.build(tmp, sources(tmp, stubs=False),
                                name="aisnap_test", quiet=True)
            except _BuildFailed:
                pass
    finally:
        hostbuild._fail = saved
    err = box.get("err", "")
    syms = sorted(set(re.findall(r"undefined reference to `([^']+)'", err)))
    other = [ln for ln in err.splitlines()
             if re.search(r"\berror\b", ln) and "undefined reference" not in ln
             and "ld returned" not in ln]
    return syms, other, err


def find_extern(name):
    """The header and `extern` declaration of a symbol, or None."""
    pat = re.compile(r"^\s*extern\s+([^;()]*?\b%s\b[^;]*);" % re.escape(name),
                     re.M)
    fpat = re.compile(r"^\s*extern\s+([^;]*\(\s*\*\s*%s\s*\)[^;]*);"
                      % re.escape(name), re.M)
    for h in sorted(SRC.glob("*.h")):
        text = h.read_text(encoding="utf-8", errors="replace")
        m = fpat.search(text) or pat.search(text)
        if m:
            return h.name, m.group(1).strip()
    return None


def write_stubs():
    for p in (STUBS, STUBDATA):
        if p.exists():
            p.unlink()
    syms, other, err = link_errors()
    if other:
        sys.stderr.write(err)
        sys.exit("the build fails on more than missing symbols")
    data, funcs, heads = [], [], set()
    for s in syms:
        found = find_extern(s)
        if found:
            heads.add(found[0])
            data.append(found[1] + ";")
        else:
            funcs.append(s)
    hd = ["// Generated by `tools/aisnap_check.py --stubs`. Do not edit.",
          "//"]
    with open(STUBDATA, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The data the linked port files name and nothing linked "
            "defines,", "// zero."] + [""] +
            ['#include "%s"' % h for h in sorted(heads)] + [""] + data) + NL)
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The functions the linked port files call and nothing linked",
            "// defines: each stops the run, which the transcript shows.",
            "", "#include <stdio.h>", "#include <stdlib.h>", "",
            "static void aisnap_unreached(const char *name)", "{",
            '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
            "    exit(3);", "}", ""] +
            ['void %s(void) { aisnap_unreached("%s"); }' % (f, f)
             for f in funcs]) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


MUTATIONS = [
    # -- Average and PidError ---------------------------------------------
    M("av-current-gone", "average.c",
      "    ReplaySnapshot_MoveUChar(s, &a->nCurrentSlot, 1);\n", ""),
    M("av-data-one-less", "average.c",
      "    for (i = 0; i < a->nSlots; i++)\n"
      "        ReplaySnapshot_MoveFloat(s, &a->pData[i]);",
      "    for (i = 0; i + 1 < a->nSlots; i++)\n"
      "        ReplaySnapshot_MoveFloat(s, &a->pData[i]);"),
    M("av-average-always", "average.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {\n"
      "        a->fAverage = 0.0f;",
      "    if (1) {\n        a->fAverage = 0.0f;"),
    M("av-average-total", "average.c",
      "            a->fAverage = ee_div(a->fTotal, (float)a->nSamples);",
      "            a->fAverage = a->fTotal;"),
    M("av-zero-kept", "average.c",
      "        a->fAverage = 0.0f;\n        if (a->nSamples != 0)",
      "        if (a->nSamples != 0)"),
    M("pe-previous-gone", "average.c",
      "    ReplaySnapshot_MoveFloat(s, &p->fPreviousError);\n", ""),
    M("pe-derivative-gone", "average.c",
      "    average_do_snapshot(&p->aDerivative, s);\n", ""),
    # -- DriveTarget -------------------------------------------------------
    M("dt-ttype-word", "drivetarget.c",
      "    ReplaySnapshot_MoveData(s, &t->TType, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &t->TType, 4, -1, 0);"),
    M("dt-picked-gone", "drivetarget.c",
      "    ReplaySnapshot_MoveChar(s, &t->WhichPointIPicked, 1);\n", ""),
    M("dt-timers-swapped", "drivetarget.c",
      "    ReplaySnapshot_MoveTimer(s, &t->WhichPointIPickedCalculationTime);\n"
      "    ReplaySnapshot_MoveTimer(s, &t->WhichPointIPickedTime);",
      "    ReplaySnapshot_MoveTimer(s, &t->WhichPointIPickedTime);\n"
      "    ReplaySnapshot_MoveTimer(s, &t->WhichPointIPickedCalculationTime);"),
    M("dt-lastpoint-gone", "drivetarget.c",
      "    ReplaySnapshot_MoveChar(s, &t->LastPointToScore, 1);\n", ""),
    M("dt-points-one-less", "drivetarget.c",
      "    for (i = 0; i < t->NumPoints; i++) {\n"
      "        ReplaySnapshot_MoveVector3(s, &t->Points[i]);",
      "    for (i = 0; i + 1 < t->NumPoints; i++) {\n"
      "        ReplaySnapshot_MoveVector3(s, &t->Points[i]);"),
    M("dt-rpn-byte", "drivetarget.c",
      "        ReplaySnapshot_MoveShort(s, &t->RoutePointNumber[i], 2);",
      "        ReplaySnapshot_MoveShort(s, &t->RoutePointNumber[i], 1);"),
    M("dt-line-gone", "drivetarget.c",
      "        ReplaySnapshot_MoveChar(s, &t->DrivingLine[i], 1);\n", ""),
    # -- the drivers --------------------------------------------------------
    M("cd-gear-unsigned", "cardriver.c",
      "    ReplaySnapshot_MoveData(s, &d->DesiredGear, 1, 4, 1);",
      "    ReplaySnapshot_MoveData(s, &d->DesiredGear, 1, 4, 0);"),
    M("cd-steer-gone", "cardriver.c",
      "    ReplaySnapshot_MoveUShort(s, &d->Steering, 2);\n", ""),
    M("cd-target-gone", "cardriver.c",
      "    drivetarget_do_snapshot(&d->MyDriveTarget, s);\n", ""),
    M("ps-steer-point-half", "psychodriver.c",
      "    ReplaySnapshot_MoveData(s, &d->SteerToPoint, 8, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &d->SteerToPoint, 4, -1, 0);"),
    M("ps-latch-gone", "psychodriver.c",
      "    ReplaySnapshot_MoveBool(s, &d->DirectionLatch, 1);\n", ""),
    M("ps-body-twice", "psychodriver.c",
      "    pid_error_do_snapshot(d->pHeadingError, s);",
      "    pid_error_do_snapshot(d->pBodyError, s);"),
    M("ps-base-gone", "psychodriver.c",
      "    cardriver_do_snapshot(&d->Base, s);\n"
      "    ReplaySnapshot_EndNamedSection(s);",
      "    ReplaySnapshot_EndNamedSection(s);"),
    M("rd-port-signed", "realdriver.c",
      "    ReplaySnapshot_MoveData(s, &d->Port, 1, 4, 0);",
      "    ReplaySnapshot_MoveData(s, &d->Port, 1, 4, 1);"),
    M("rd-forced-in-place", "realdriver.c",
      "    ReplaySnapshot_MoveInt(s, &d->ManualTransmission, 1);\n"
      "    ReplaySnapshot_MoveFloat(s, &d->ForcedEBrakeStop);",
      "    ReplaySnapshot_MoveFloat(s, &d->ForcedEBrakeStop);\n"
      "    ReplaySnapshot_MoveInt(s, &d->ManualTransmission, 1);"),
    M("rd-ebrake-analog-gone", "realdriver.c",
      "    ReplaySnapshot_MoveUChar(s, &d->JoyEBrakeAnalog, 1);\n", ""),
    M("rd-nitro-gone", "realdriver.c",
      "    ReplaySnapshot_MoveTimer(s, &d->LastNitroRequest);\n", ""),
    M("rd-reversing-gone", "realdriver.c",
      "    ReplaySnapshot_MoveBool(s, &d->Reversing, 1);\n", ""),
    M("cc-no-dispatch", "carcontroller.c",
      "    ((CarDriverDoSnapshotFn)e->fn)(vt_this(d, e), snap);",
      "    (void)e;\n    (void)snap;"),
    # -- the pointers -------------------------------------------------------
    M("w-number-short", "world.c",
      "    ReplaySnapshot_MoveInt(s, &n, 1);\n    if (s->RestoringSnapshotFlag) {\n"
      "        if (n < 0)",
      "    ReplaySnapshot_MoveInt(s, &n, 2);\n    if (s->RestoringSnapshotFlag) {\n"
      "        if (n < 0)"),
    M("w-negative-kept", "world.c",
      "        if (n < 0)\n            *pp = NULL;",
      "        if (n < 0)\n            *pp = *pp;"),
    M("tr-route-null-kept", "trackroute.c",
      "        *pp = n < 0 ? NULL : m->pTrackRoutes[n];",
      "        *pp = n < 0 ? *pp : m->pTrackRoutes[n];"),
    M("tr-inroute-byte", "trackroute.c",
      "    ReplaySnapshot_MoveInt(s, &n, 2);",
      "    ReplaySnapshot_MoveInt(s, &n, 1);"),
    M("tr-inroute-drop-kept", "trackroute.c",
      "        && n == -1)\n        *pp = NULL;",
      "        && n == -1)\n        *pp = *pp;"),
    M("tr-point-no-route", "trackroute.c",
      "            + (int32_t)((uint32_t)(int32_t)r->RouteNumber << 16);",
      "            + 0;"),
    M("tr-point-null-kept", "trackroute.c",
      "        if (v == -1) {\n            *pp = NULL;",
      "        if (v == -1) {\n            *pp = *pp;"),
    M("rb-index-next", "copmanager.c",
      "        *pp = n < 0 ? NULL : &m->RoadBlocks[n];",
      "        *pp = n < 0 ? NULL : &m->RoadBlocks[n + 1];"),
    # -- DrivingLocation, DrivingChoice, the lists -------------------------
    M("dl-line-word", "drivinglocation.c",
      "    ReplaySnapshot_MoveInt(s, &d->DrivingLine, 1);",
      "    ReplaySnapshot_MoveInt(s, &d->DrivingLine, 4);"),
    M("dl-relaxed-gone", "drivinglocation.c",
      "    ReplaySnapshot_MoveData(s, &d->LastRelaxedDrivingLineSwitchTime, 4, -1,\n"
      "                            0);\n", ""),
    M("dc-type-word", "drivingchoice.c",
      "    ReplaySnapshot_MoveData(s, &d->Type, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &d->Type, 4, -1, 0);"),
    M("dc-car-gone", "drivingchoice.c",
      "    world_do_car_pointer_snapshot(pCurrentWorld, &d->pCar, s);\n", ""),
    M("nr-point-gone", "airoute.c",
      "    trmgr_do_point_pointer_snapshot_in_route(&TheTrackRouteManager, s,\n"
      "                                             &info->Point, info->Route);\n",
      ""),
    M("nl-count-word", "nearbycar.c",
      "    ReplaySnapshot_MoveInt(s, &l->NumCarsInArray, 1);",
      "    ReplaySnapshot_MoveInt(s, &l->NumCarsInArray, 4);"),
    M("nl-halves-swapped", "nearbycar.c",
      "    ReplaySnapshot_MoveFloat(s, &l->MyHalfSizeD);\n"
      "    ReplaySnapshot_MoveFloat(s, &l->MyHalfSizeL);",
      "    ReplaySnapshot_MoveFloat(s, &l->MyHalfSizeL);\n"
      "    ReplaySnapshot_MoveFloat(s, &l->MyHalfSizeD);"),
    M("nl-record-short", "nearbycar.c",
      "        ReplaySnapshot_MoveData(s, &l->Array[i], 28, -1, 0);",
      "        ReplaySnapshot_MoveData(s, &l->Array[i], 24, -1, 0);"),
    M("di-count-kept", "nearbycar.c",
      "        d->MyNearbyCarList.NumCarsInArray = 0;\n", ""),
    M("di-half-kept", "nearbycar.c",
      "        d->MyNearbyCarList.MyHalfSizeL = 0.0f;\n", ""),
    M("di-choice-gone", "nearbycar.c",
      "    drivingchoice_do_snapshot(&d->MyDrivingChoice, s);\n", ""),
    # -- AIPlan, AIAction and the actions ----------------------------------
    M("ap-expiry-gone", "aiaction.c",
      "    ReplaySnapshot_MoveData(s, &p->ExpiryTimer, 4, -1, 0);\n", ""),
    M("ap-status-gone", "aiaction.c",
      "    ReplaySnapshot_MoveData(s, &p->Status, 1, -1, 0);\n", ""),
    M("aa-tolerance-in-place", "aiaction.c",
      "    ReplaySnapshot_MoveFloat(s, &a->DesiredSpeedTolerance);\n"
      "    ReplaySnapshot_MoveFloat(s, &a->TimeToGetToDesiredSpeed);",
      "    ReplaySnapshot_MoveFloat(s, &a->TimeToGetToDesiredSpeed);\n"
      "    ReplaySnapshot_MoveFloat(s, &a->DesiredSpeedTolerance);"),
    M("aa-execute-gone", "aiaction.c",
      "    ReplaySnapshot_MoveBool(s, &a->PointsToDriveWillExecuteAction, 1);\n",
      ""),
    M("aa-score-byte", "aiaction.c",
      "    ReplaySnapshot_MoveInt(s, &a->Score, 4);",
      "    ReplaySnapshot_MoveInt(s, &a->Score, 1);"),
    M("aa-plan-gone", "aiaction.c",
      "    aiplan_do_snapshot(&a->Base, s);\n", ""),
    M("ac-avoid-car-gone", "aiactions.c", "    CAR_PTR(&a->CarToAvoid);\n", ""),
    M("ac-avoid-minlife-gone", "aiactions.c",
      "    ReplaySnapshot_MoveFloat(s, &a->MinLifetime);\n", ""),
    M("ac-justdrive-timer-gone", "aiactions.c",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionJustDrive");\n'
      "    aiaction_do_snapshot(&a->Base, s);\n"
      "    TIMER(a->LastDecisionReevaluationTime);\n",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionJustDrive");\n'
      "    aiaction_do_snapshot(&a->Base, s);\n"),
    M("ac-draft-base-gone", "aiactions.c",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionDraft");\n'
      "    aiaction_do_snapshot(&a->Base, s);\n",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionDraft");\n'),
    M("ac-pass-amount-gone", "aiactions.c",
      "    ReplaySnapshot_MoveFloat(s, &a->AmountToProjectIntoFuture);\n", ""),
    M("ac-pass-car-gone", "aiactions.c", "    CAR_PTR(&a->CarToPass);\n", ""),
    M("ac-nudge-car-gone", "aiactions.c", "    CAR_PTR(&a->CarToNudge);\n", ""),
    M("ac-block-car-gone", "aiactions.c", "    CAR_PTR(&a->CarToBlock);\n", ""),
    M("ac-pullover-new620-gone", "aiactions.c",
      "    ReplaySnapshot_MoveBool(s, &a->New620, 1);\n", ""),
    M("ac-pullover-timeout-gone", "aiactions.c",
      "    ReplaySnapshot_MoveFloat(s, &a->PullOverTimeout);\n", ""),
    M("ac-unstuck-effect-gone", "aiactions.c",
      "    ReplaySnapshot_MoveBool(s, &a->MinimumLifetimeInEffect, 1);\n", ""),
    M("ac-roadblock-gone", "aiactions.c",
      "    copmanager_do_road_block_pointer_snapshot(\n"
      "        pCopManager, s, (tRoadBlock **)&a->RoadBlockToAvoid);\n", ""),
    M("ac-hit-car-gone", "aiactions.c", "    CAR_PTR(&a->CarIHit);\n", ""),
    M("ac-recovery-reset-gone", "aiactions.c",
      "    ReplaySnapshot_MoveBool(s, &a->HaveResetYet, 1);\n", ""),
    M("ac-recovery-own-name", "aiactions.c",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionIJustGotHit");\n'
      "    aiaction_do_snapshot(&a->Base, s);\n    TIMER(a->MyCreationTime);",
      '    ReplaySnapshot_BeginNamedSection(s, "AIActionAccidentRecovery");\n'
      "    aiaction_do_snapshot(&a->Base, s);\n    TIMER(a->MyCreationTime);"),
    M("ptr-have-ignored", "aiactions.c",
      "    if (have != 0) {", "    if (1) {"),
    M("ptr-type-word", "aiactions.c",
      "        ReplaySnapshot_MoveData(s, &type, 1, -1, 0);",
      "        ReplaySnapshot_MoveData(s, &type, 4, -1, 0);"),
    M("ptr-draft-not-new", "aiactions.c",
      "            case AIACTION_DRAFT:\n"
      "                a = &aidraft_init(aiaction_new(), 0, 0.0f)->Base;\n",
      "            case AIACTION_DRAFT:\n"),
    M("ptr-block-type", "aiactions.c",
      "            case AIACTION_BLOCK:\n                a = &aiblock_init",
      "            case AIACTION_BLOCK + 100:\n                a = &aiblock_init"),
    M("ptr-restore-kept", "aiactions.c", "            *pp = a;\n", ""),
    # -- the controllers ----------------------------------------------------
    M("acc-force-word", "aicarcontroller.c",
      "    ReplaySnapshot_MoveData(s, &c->ForceCurrentAction, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &c->ForceCurrentAction, 4, -1, 0);"),
    M("acc-lastroute-gone", "aicarcontroller.c",
      "    ReplaySnapshot_MoveChar(s, &c->LastTrackRouteNumber, 1);\n", ""),
    M("acc-info-gone", "aicarcontroller.c",
      "    drivinginformation_do_snapshot(&c->MyCurrentDrivingInformation, s);\n",
      ""),
    M("acc-action-gone", "aicarcontroller.c",
      "    aiaction_do_pointer_snapshot(&c->CurrentAction, s);\n", ""),
    M("acc-exclude-gone", "aicarcontroller.c",
      "    world_do_pointer_snapshot(pCurrentWorld, s,\n"
      "                              &c->CarToExcludeFromCollisionPrediction);\n",
      ""),
    M("acc-progress-twice", "aicarcontroller.c",
      "    average_do_snapshot(c->pDeltaLineSpeed, s);",
      "    average_do_snapshot(c->pProgress, s);"),
    M("acc-prevline-short", "aicarcontroller.c",
      "    ReplaySnapshot_MoveData(s, &c->vPreviousLinePoint, 16, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &c->vPreviousLinePoint, 12, -1, 0);"),
    M("acc-glue-gone", "aicarcontroller.c",
      "    world_do_pointer_snapshot(pCurrentWorld, s, &c->pGlueCar);\n", ""),
    M("acc-player-negative-kept", "aicarcontroller.c",
      "        c->pCatchupPlayer = player < 0 ? NULL : PlayerPlayersByNumber[player];",
      "        c->pCatchupPlayer = player < 0 ? c->pCatchupPlayer : "
      "PlayerPlayersByNumber[player];"),
    M("acc-player-not-restored", "aicarcontroller.c",
      "    if (s->RestoringSnapshotFlag)\n        c->pCatchupPlayer",
      "    if (0)\n        c->pCatchupPlayer"),
    M("acc-boost-gone", "aicarcontroller.c",
      "    ReplaySnapshot_MoveBool(s, &c->bBoostAllowed, 1);\n", ""),
    M("acc-sticky-half", "aicarcontroller.c",
      "    ReplaySnapshot_MoveData(s, c->aStickyDecisions, 32, -1, 0);",
      "    ReplaySnapshot_MoveData(s, c->aStickyDecisions, 16, -1, 0);"),
    M("acc-last-timer-gone", "aicarcontroller.c",
      "    ReplaySnapshot_MoveTimer(\n"
      "        s, (int32_t *)&c->LastTimeNonGetUnstuckActionWasCalled.PackedTime);\n",
      ""),
    M("aid-car-gone", "aidriver.c",
      "    world_do_car_pointer_snapshot(pCurrentWorld, &d->CarToPurposefullyNotAvoid,\n"
      "                                  s);\n", ""),
    M("aid-timer-gone", "aidriver.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&d->VeryStuckProgressTimer.PackedTime);\n",
      ""),
    M("aid-stuck-gone", "aidriver.c",
      "    average_do_snapshot(d->pVeryStuckProgress, s);\n", ""),
    M("td-flag-gone", "trafficdriver.c",
      "    ReplaySnapshot_MoveBool(s, &d->PickLowNumberedRoutes, 1);\n", ""),
    M("td-base-gone", "trafficdriver.c",
      "    aicarcontroller_do_snapshot(&d->Base, s);\n", ""),
    M("tc-driver-gone", "realcontroller.c",
      "    carcontroller_do_snapshot(&c->Base, s);\n"
      "    trmgr_do_point_pointer_snapshot",
      "    trmgr_do_point_pointer_snapshot"),
    M("tc-point-gone", "realcontroller.c",
      "    trmgr_do_point_pointer_snapshot(&TheTrackRouteManager, s, &c->RoutePoint);\n",
      ""),
    M("tc-prevspeed-gone", "realcontroller.c",
      "    ReplaySnapshot_MoveFloat(s, &c->PrevSpeed);\n", ""),
    M("rc-spline-kept", "realcontroller.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        quickspline_set_num_control_points(c->DrivingLineSpline, 0);",
      "    if (0)\n"
      "        quickspline_set_num_control_points(c->DrivingLineSpline, 0);"),
    M("rc-average-gone", "realcontroller.c",
      "    average_do_snapshot(c->LateralVelocityWRTLineAverage, s);\n", ""),
    M("rc-count-byte", "realcontroller.c",
      "    ReplaySnapshot_MoveInt(s, &c->NumPreviousRoutePoints, 4);",
      "    ReplaySnapshot_MoveInt(s, &c->NumPreviousRoutePoints, 1);"),
    M("rc-points-one-less", "realcontroller.c",
      "    for (i = 0; i < c->NumPreviousRoutePoints; i++)\n"
      "        nrpi_do_snapshot",
      "    for (i = 0; i + 1 < c->NumPreviousRoutePoints; i++)\n"
      "        nrpi_do_snapshot"),
    M("rc-tracked-gone", "realcontroller.c",
      "    trackedcontroller_do_snapshot(&c->Base, s);\n", ""),
    M("cop-section-named", "copdriver.c",
      '    ReplaySnapshot_BeginSection(s, c, "CopDriver");',
      '    ReplaySnapshot_BeginNamedSection(s, "CopDriver");'),
    M("cop-tracked-gone", "copdriver.c",
      "    trackedcontroller_do_snapshot(&c->Base, s);\n", ""),
    M("cop-state-word", "copdriver.c",
      "    ReplaySnapshot_MoveData(s, &c->State, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &c->State, 4, -1, 0);"),
    M("cop-substate-gone", "copdriver.c",
      "    ReplaySnapshot_MoveData(s, &c->SubState, 1, -1, 0);\n", ""),
    M("cop-steer-gone", "copdriver.c",
      "    ReplaySnapshot_MoveVector2(s, &c->v2SteerTarget);\n", ""),
    M("cop-index-word", "copdriver.c",
      "    ReplaySnapshot_MoveInt(s, &c->nCopIndex, 1);",
      "    ReplaySnapshot_MoveInt(s, &c->nCopIndex, 4);"),
    # -- the movers ---------------------------------------------------------
    M("cm-facing-gone", "copdriver.c",
      "    ReplaySnapshot_MoveUShort(s, &m->aDesiredFacingAngle, 2);\n", ""),
    M("cm-speeds-swapped", "copdriver.c",
      "    ReplaySnapshot_MoveFloat(s, &m->fBaseMaxSpeed);\n"
      "    ReplaySnapshot_MoveFloat(s, &m->fDesiredSpeed);",
      "    ReplaySnapshot_MoveFloat(s, &m->fDesiredSpeed);\n"
      "    ReplaySnapshot_MoveFloat(s, &m->fBaseMaxSpeed);"),
    M("cm-state-word", "copdriver.c",
      "    ReplaySnapshot_MoveData(s, &m->State, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &m->State, 4, -1, 0);"),
    M("cm-airborne-gone", "copdriver.c",
      "    ReplaySnapshot_MoveBool(s, &m->bIsAirborne, 1);\n", ""),
    M("cm-new64-gone", "copdriver.c",
      "    ReplaySnapshot_MoveFloat(s, &m->New64);\n", ""),
    M("bm-scale-gone", "beltmover.c",
      "    ReplaySnapshot_MoveFloat(s, &m->fScale);\n", ""),
    M("bm-sliding-gone", "beltmover.c",
      "    ReplaySnapshot_MoveBool(s, &m->bSliding, 1);\n", ""),
    M("bm-cubicu-short", "beltmover.c",
      "    ReplaySnapshot_MoveData(s, m->pCubicU, 48, -1, 0);",
      "    ReplaySnapshot_MoveData(s, m->pCubicU, 32, -1, 0);"),
    M("bm-slide-gone", "beltmover.c",
      "    ReplaySnapshot_MoveData(s, m->pCubicSlide, 96, -1, 0);\n", ""),
    M("bm-spline-four", "beltmover.c",
      "    quickspline_do_snapshot(m->pSpline, s, 3);",
      "    quickspline_do_snapshot(m->pSpline, s, 4);"),
    M("bm-average-gone", "beltmover.c",
      "    average_do_snapshot(m->pAvgAccel, s);\n", ""),
    M("bm-wheels-three", "beltmover.c",
      "    for (i = 0; i < 4; i++)\n        wheel_do_snapshot(m->pWheels[i], s);",
      "    for (i = 0; i < 3; i++)\n        wheel_do_snapshot(m->pWheels[i], s);"),
    M("mm-body-gone", "mellowmover.c",
      "    rigidbody_do_snapshot(mm->pBody, s);\n", ""),
    M("mm-mellovator-gone", "mellowmover.c",
      "    mellovator_do_snapshot(mm->pMellovator, s);\n", ""),
    M("mm-aero-gone", "mellowmover.c",
      "    aerodynamics_do_snapshot(mm->pAerodynamics, s);\n", ""),
    M("mm-wheels-three", "mellowmover.c",
      "    for (i = 0; i < 4; i++)\n        wheel_do_snapshot(mm->pWheels[i], s);",
      "    for (i = 0; i < 3; i++)\n        wheel_do_snapshot(mm->pWheels[i], s);"),
    M("mel-state-half", "mellowmover.c",
      "    ReplaySnapshot_MoveData(s, &m->State, 16, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &m->State, 8, -1, 0);"),
    M("mel-slip-gone", "mellowmover.c",
      "        ReplaySnapshot_MoveVector2(s, &m->WheelSlip[i]);\n", ""),
    M("mel-locked-word", "mellowmover.c",
      "        ReplaySnapshot_MoveInt(s, &m->BrakeLocked[i], 1);",
      "        ReplaySnapshot_MoveInt(s, &m->BrakeLocked[i], 4);"),
    M("mel-gear-unsigned", "mellowmover.c",
      "    ReplaySnapshot_MoveData(s, &m->CurrentGear, 1, 4, 1);",
      "    ReplaySnapshot_MoveData(s, &m->CurrentGear, 1, 4, 0);"),
    M("mel-desired-unsigned", "mellowmover.c",
      "    ReplaySnapshot_MoveData(s, &m->DesiredGear, 1, 4, 1);",
      "    ReplaySnapshot_MoveData(s, &m->DesiredGear, 1, 4, 0);"),
    M("mel-steer-gone", "mellowmover.c",
      "    ReplaySnapshot_MoveUShort(s, &m->Steering, 2);\n", ""),
    M("mel-friction-gone", "mellowmover.c",
      "    ReplaySnapshot_MoveFloat(s, &m->CurrentFrictionBoost);\n", ""),
    # -- the splines --------------------------------------------------------
    M("sp-type-gone", "spline.c",
      "    ReplaySnapshot_MoveInt(s, &type, 4);\n", ""),
    M("sp-points-one-less", "spline.c",
      "    for (i = 0; i < sp->NumControlPoints; i++)\n"
      "        ReplaySnapshot_MoveVector3",
      "    for (i = 0; i + 1 < sp->NumControlPoints; i++)\n"
      "        ReplaySnapshot_MoveVector3"),
    M("sp-dirty-gone", "spline.c",
      "    ReplaySnapshot_MoveInt(s, &sp->Dirty, 4);\n", ""),
    M("sp-step-gone", "spline.c",
      "    ReplaySnapshot_MoveFloat(s, &sp->CalTableStep);\n", ""),
    M("sp-table-floats", "spline.c",
      "        ReplaySnapshot_MoveData(s, sp->pCalTable, sp->CalTableSize, -1, 0);",
      "        ReplaySnapshot_MoveData(s, sp->pCalTable, sp->CalTableSize * 4, -1,"
      " 0);"),
    M("qs-count-byte", "quickspline.c",
      "    ReplaySnapshot_MoveUShort(s, &q->NumControlPoints, 2);",
      "    ReplaySnapshot_MoveUShort(s, &q->NumControlPoints, 1);"),
    M("qs-set-kept", "quickspline.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        quickspline_set_num_control_points(q, q->NumControlPoints);",
      "    if (0)\n"
      "        quickspline_set_num_control_points(q, q->NumControlPoints);"),
    M("qs-three-floats", "quickspline.c",
      "        ReplaySnapshot_MoveData(s, &q->pControlPoints[i], n * 4, -1, 0);",
      "        ReplaySnapshot_MoveData(s, &q->pControlPoints[i], 12, -1, 0);"),
    M("qs-dirty-kept", "quickspline.c",
      "    s->ControlPointsDirty = 1;\n    s->NumControlPoints = (uint16_t)n;",
      "    s->NumControlPoints = (uint16_t)n;"),
    M("qs-none-max-kept", "quickspline.c",
      "        s->MinParam = 0.0f;\n        s->MaxParam = 0.0f;\n        return;",
      "        s->MinParam = 0.0f;\n        return;"),
    M("qs-line-max", "quickspline.c",
      "        s->MaxParam = (float)(s->NumControlPoints - 1);",
      "        s->MaxParam = (float)s->NumControlPoints;"),
    M("qs-extrapolated-min", "quickspline.c",
      "        s->MinParam = QUICKSPLINE_EXTRAPOLATED_MIN;",
      "        s->MinParam = 0.0f;"),
    M("qs-other-zeroed", "quickspline.c",
      "    default:\n        // Any other type leaves the range as it was.\n"
      "        break;",
      "    default:\n        s->MaxParam = 0.0f;\n        break;"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    lines = script()
    base = model_cached(lines)
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    with tempfile.TemporaryDirectory() as d:
        sc = write_script(d, lines)
        gen = Path(d) / "gen"
        gen.mkdir()
        srcs = sources(gen)
        with tempfile.TemporaryDirectory() as bt:
            exe = hostbuild.build(bt, srcs, name="aisnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "aisnap_test",
            lambda exe, out: mutpar.run_exe([exe, sc], out, limit),
            base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--dump", metavar="PREFIX")
    ap.add_argument("--fields", metavar="CLASS", nargs="?", const="*")
    ap.add_argument("--stubs", action="store_true")
    args = ap.parse_args()

    if args.stubs:
        write_stubs()
        return 0

    if args.fields:
        for cls in CLASSES:
            if args.fields not in ("*", cls):
                continue
            print("%s (retail %d)" % (cls, alloc_size(cls)))
            for f in flatten(cls):
                print("  %4d %3d %-4s %s" % (f.roff, f.size, f.kind, f.path))
        return 0

    if args.mutate:
        only = set(args.only.split(",")) if args.only else None
        sys.exit(mutate_pass(only, args.jobs))

    lines = script()
    model = model_cached(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        sc = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sc, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(model) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(model, harness)
    print("%d script lines, %d model lines, %d harness lines, %d differ"
          % (len(lines), len(model), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
