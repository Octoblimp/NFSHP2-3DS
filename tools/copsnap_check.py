#!/usr/bin/env python3
"""Cross-check TASKS 72e, the cops' part of the replay's snapshot, against
the retail image, SLES_507.31.

**What is checked**: 72e-1's DroppedSpikes' (0x001bef90) and Rocket's
(0x001bf910) DoSnapshots, tSpikeStrip's (0x00241898) and the Chopper's
(0x001e7d08); 72e-2's tPursuit's (0x0022a548), tPlayerCop's (0x0022d7e8)
and tAICop's (0x0022dd20), with what they call in copsnap.c: tCop's
(0x0022d440), the history's, the roadblock state machine's, the barrels'
and the cop manager's pursuit, cop and radar trap pointers. Each is taken,
restored over other values, checksummed and verified. Source checks hold
munition.c's DroppedSpikes and Rocket tables to the new DoSnapshots in
slot 16, main.c to binding the chopper's, and cop.c's tPlayerCop and
tAICop tables to theirs in slot 32.

**The layouts** are the port's headers, parsed by carsnap_check.py (which
this imports and extends). The harness, tools/src/copsnap_test.c, gets the
same field list as a generated table of offsetof and sizeof, so each side
writes and dumps a field at its own offset, and a pointer prints as the
object and field it points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot and the functions above. Recorded on both sides,
as lines both print: Smokeable's snapshot, World's car pointer and plain
pointer, the route manager's route and point pointers,
TrackPathCoordinate's snapshot, the strip's Init, the chopper's
RemoveChopperFromWorld and ClearVariables, the cop manager's roadblock
pointer (TASKS 72c's), the pursuit's IsCopInPursuit (0x0022c920, which
returns what the script says) and DriveTarget's snapshot. The globals are
set by ops of their own on both sides.

What the linked port files reach outside that is stubbed by
tools/src/copsnap_stubs.c and copsnap_stubdata.c, which `--stubs` writes
from the link's undefined symbols; each stubbed function stops the run with
an UNREACHED line.

    python tools/copsnap_check.py
    python tools/copsnap_check.py --stubs
    python tools/copsnap_check.py --fields [CLASS]
    python tools/copsnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/copsnap_check.py --dump out/copsnap
"""
import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carsnap_check as csc             # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import retail_model                     # noqa: E402
from carsnap_check import (fill, fl, i32, i8, cycle, flatten,  # noqa: E402
                           alloc_size, mat)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "copsnap_test.c"
STUBS = ROOT / "tools" / "src" / "copsnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "copsnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in ("replay.c", "p32.c", "copsnap.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
P_COP_MANAGER = GP - 15620
TRACK_ROUTE_MANAGER = 0x00314438
COPMANAGER_SIZE = 10516
CAR_SIZE = 2224

# ================================================================ the layout

csc.HEADERS.update({
    "SmokeableInfo": "smokeable.h", "SmokeableSpawner": "smokeable.h",
    "Smokeable": "smokeable.h", "Munition": "munition.h",
    "DroppedSpikes": "munition.h", "Rocket": "munition.h",
    "tSpikeStrip": "copmanager.h", "Chopper": "chopper.h",
    "tCop": "copmanager.h", "tPlayerCop": "cop.h", "tAICop": "cop.h",
    "tSpeedTrap": "copmanager.h", "tRoadBlock": "copmanager.h",
    "tPursuit": "copmanager.h", "tPursuitHistory": "copmanager.h",
    "tRoadBlockStateMachine": "copmanager.h",
    "BarricadeManager": "barricade.h",
    "NearestRoutePointInfo": "airoute.h", "DriveTarget": "drivetarget.h",
})
csc.TYPES.update({"ChopperPlan": (4, False), "ChopperMoveMode": (4, False),
                  "ChopperAttackType": (4, False),
                  "eLogicState": (4, False), "eLogicSubState": (4, False),
                  "ePursuitState": (4, False), "eChopperState": (4, False),
                  "eRoadBlockState": (4, False)})
csc.SKIP_TYPES.update({"WorldObject", "RigidBodyInfo", "TrackListNode",
                       "tPursuitNode", "tSpikeStripRenderElement"})
csc.MACROS.update({"BARRICADE_MAX_BARRELS": 10,
                   "DRIVETARGET_MAX_POINTS": 20})
csc.RETAIL_SIZE.update({"tSpikeStrip": 2304, "tCop": 32, "tPursuit": 1600,
                        "NearestRoutePointInfo": 8, "DriveTarget": 528})

# The records a script can make, in the order of the generated table.
CLASSES = ["DroppedSpikes", "Rocket", "tSpikeStrip", "Chopper",
           "tPlayerCop", "tAICop", "tSpeedTrap", "tRoadBlock", "tPursuit",
           "BarricadeManager"]

# ============================================================ the scenarios


def sc_spikes():
    out = ["# droppedspikes", "new|ds|DroppedSpikes"]
    for k, (a, b) in enumerate(((1, 0), (0, 1))):
        out += ["# droppedspikes %d" % k]
        out += fill("ds", "DroppedSpikes", "a%d" % k, ("DeploySpikes",))
        out += ["set|ds|DeploySpikes|" + i32(a)]
        out += cycle(["call|spikes|ds"], ["dump|ds"],
                     fill("ds", "DroppedSpikes", "b%d" % k, ("DeploySpikes",))
                     + ["set|ds|DeploySpikes|" + i32(0x100 + b)],
                     ["set|ds|DeploySpikes|" + i32(a ^ 1)])
    return out


def sc_rocket():
    out = ["# rocket", "newb|car0|16", "newb|car1|16", "newb|wld|16",
           "curworld|wld", "new|rk|Rocket"]
    for k, (t, rt) in enumerate((("car0", "car1"), ("0", "car0"),
                                 ("car1", "0"))):
        out += ["# rocket %d" % k]
        out += fill("rk", "Rocket", "a%d" % k)
        out += ["link|rk|Target|%s|-" % t]
        out += cycle(["call|rocket|rk"], ["dump|rk"],
                     fill("rk", "Rocket", "b%d" % k) +
                     ["link|rk|Target|%s|-" % rt],
                     ["set|rk|Yaw|" + fl(-12.5 * (k + 1))])
    out += ["curworld|0", "# rocket, no world"]
    out += cycle(["call|rocket|rk"], ["dump|rk"], fill("rk", "Rocket", "c"))
    return out


def sc_strip():
    out = ["# spikestrip", "new|ss|tSpikeStrip"]
    for k in range(2):
        keep = ("bIsBlinking",)
        out += ["# spikestrip %d" % k]
        out += fill("ss", "tSpikeStrip", "a%d" % k, keep)
        out += ["set|ss|bIsBlinking|" + i32(k)]
        out += cycle(["call|strip|ss"], ["dump|ss"],
                     fill("ss", "tSpikeStrip", "b%d" % k, keep) +
                     ["set|ss|bIsBlinking|" + i32(0x10000 + (k ^ 1))],
                     ["set|ss|nRoadBlockID|" + i32(77 + k)])
    return out


# The pointers a chopper holds: (field, take's, restore's).
CHOPPER_LINKS = (("CurrentCar", "car0", "car1"),
                 ("ChopperRoute", "rt0", "rt1"),
                 ("ChopperPoint", "pt0", "0"),
                 ("TargetRoute", "rt1", "0"),
                 ("TargetPoint", "pt1", "pt2"),
                 ("OldCarRoute", "0", "rt0"),
                 ("OldCarPoint", "pt2", "pt0"))


def sc_chopper():
    out = ["# chopper", "newb|rt0|16", "newb|rt1|16", "newb|pt0|16",
           "newb|pt1|16", "newb|pt2|16", "curworld|wld",
           "new|h|Chopper"]
    # The plan taken, the plan the restore lands on before it reads (its
    # low byte is overwritten), and the matrix's codes.
    cases = ((0, 0x0302, 2, 0), (6, 0, 1, 2), (6, 0x0100, 0, 1),
             (3, 6, 0, 2), (5, 0x0206, 1, 1))
    for k, (plan, rplan, m1, m2) in enumerate(cases):
        keep = ("Plan", "Matrix")
        out += ["# chopper %d" % k]
        out += fill("h", "Chopper", "a%d" % k, keep)
        out += ["set|h|Plan|" + i32(plan), "set|h|Matrix|" + mat(m1)]
        out += ["link|h|%s|%s|-" % (f, a) for f, a, _b in CHOPPER_LINKS]
        refill = fill("h", "Chopper", "b%d" % k, keep)
        refill += ["set|h|Plan|" + i32(rplan),
                   "set|h|Matrix|" + mat(m2, 0.5)]
        refill += ["link|h|%s|%s|-" % (f, b) for f, _a, b in CHOPPER_LINKS]
        out += cycle(["call|chopper|h"], ["dump|h"], refill,
                     ["set|h|GroundZ|" + fl(3.75 + k)])
    return out


# ------------------------------------------------------------------ 72e-2

def sc_cops_setup():
    """The cop manager, three cops in its Cops (0, 1 and 4), four pursuits
    (ids 0, 3, -2 gone, 2; all but the gone one in PursuitsById), two
    roadblocks, the barrels, a player's car and another, and a world with
    a chopper."""
    out = ["# cops", "copmgr|cm", "newb|pl|16", "newb|heli|16",
           "newb|heli2|16", "newcar|carp|pl", "newcar|carn|0",
           "newworld|wld2|heli", "curworld|wld2",
           "new|pc|tPlayerCop", "new|ac0|tAICop", "new|ac1|tAICop",
           "new|pur|tPursuit", "new|pur2|tPursuit", "new|pur3|tPursuit",
           "new|pur4|tPursuit", "new|rb|tRoadBlock", "new|rb2|tRoadBlock",
           "new|bm|BarricadeManager"]
    for ref, n in (("pc", 0), ("ac0", 1), ("ac1", 4)):
        out += ["set|%s|Base.nCopNumber|%s" % (ref, i32(n)),
                "mcop|%d|%s" % (n, ref)]
    for ref, n, slot in (("pur", 0, 0), ("pur2", 3, 3), ("pur3", -2, None),
                         ("pur4", 2, 2)):
        out += ["set|%s|nPursuitId|%s" % (ref, i8(n))]
        if slot is not None:
            out += ["mpur|%d|%s" % (slot, ref)]
    return out


# What a pursuit holds, taken and then restored over: the chased car, the
# roadblock, its two cops, the chopper and the chase's cops. The restore's
# roadblock is NULL where the take's is: its pointer is recorded, and a
# restore onto one would read cops from where none were written.
PURSUIT_CASES = (
    (("carp", "rb", ("ac0", "0"), "heli2", ("ac1", "pc")),
     ("carp", "rb", ("pc", "ac1"), "0", ("0", "ac0"))),
    (("carn", "0", None, "0", ()),
     ("carn", "0", None, "heli2", ("pc", "ac0"))),
    (("carp", "rb2", ("0", "0"), "heli", ("0",)),
     ("carp", "rb2", ("ac0", "ac1"), "heli", ("pc", "pc"))),
    (("carn", "rb", ("ac1", "ac1"), "heli2", ("pc",)),
     ("carp", "rb", ("0", "0"), "0", ("ac0", "ac1"))),
)

PURSUIT_KEEP = ("nPursuitId", "nNumCops")


def pursuit_links(case):
    chased, rb, rbcops, heli, cops = case
    out = ["link|pur|pChasedCar|%s|-" % chased,
           "link|pur|pRoadBlock|%s|-" % rb,
           "link|pur|pChopper|%s|-" % heli,
           "link|pur|pBarricades|bm|-",
           "set|pur|nNumCops|" + i32(len(cops))]
    cs = list(cops) + ["0"] * (2 - len(cops))
    out += ["link|pur|Cops[%d]|%s|-" % (i, c) for i, c in enumerate(cs)]
    if rbcops:
        out += ["link|%s|cops[%d]|%s|-" % (rb, i, c)
                for i, c in enumerate(rbcops)]
    return out


def sc_pursuit():
    out = ["# pursuit"]
    changes = (["set|pur|nPursuitId|" + i8(5)],
               ["set|pur|fCatchCarTimer|" + fl(2.5)],
               ["set|pur|History.nCount|" + i32(7)],
               ["set|pur|RoadBlockStateMachine.SpeechFlags|" + i32(0x40)])
    for k, (a, b) in enumerate(PURSUIT_CASES):
        rbs = sorted({a[1], b[1]} - {"0"})
        out += ["# pursuit %d" % k, "set|pur|nPursuitId|" + i8(0)]
        out += fill("pur", "tPursuit", "a%d" % k, PURSUIT_KEEP)
        out += fill("bm", "BarricadeManager", "a%d" % k)
        for r in rbs:
            out += fill(r, "tRoadBlock", "a%d" % k)
        out += ["link|pur|RoadBlockStateMachine.pPursuit|pur2|-"]
        out += pursuit_links(a)
        refill = fill("pur", "tPursuit", "b%d" % k, PURSUIT_KEEP)
        refill += fill("bm", "BarricadeManager", "b%d" % k)
        for r in rbs:
            refill += fill(r, "tRoadBlock", "b%d" % k)
        refill += ["link|pur|RoadBlockStateMachine.pPursuit|0|-"]
        refill += pursuit_links(b)
        dumps = ["dump|pur", "dump|bm"] + ["dump|" + r for r in rbs]
        out += cycle(["call|pursuit|pur"], dumps, refill, changes[k])
    out += ["set|pur|nPursuitId|" + i8(0)]
    return out


# A cop's pursuit taken, the restore's, the id pur4 has at the restore,
# and what IsCopInPursuit says. pur2's 0 drops it as the take runs; pur3's
# id is -2; pur4 goes (-2) before the restore finds it by its id 2.
COP_CASES = (("pur", "pur2", None, 1), ("pur2", "pur", None, 0),
             ("0", "pur", None, 1), ("pur3", "pur", None, 1),
             ("pur4", "0", -2, 1))

COP_KEEP = ("Base.nCopNumber",)


def sc_playercop():
    out = ["# playercop"]
    for k, (p, rp, rid, inc) in enumerate(COP_CASES):
        out += ["# playercop %d" % k, "incop|%d" % inc,
                "set|pur4|nPursuitId|" + i8(2)]
        out += fill("pc", "tPlayerCop", "a%d" % k, COP_KEEP)
        out += ["link|pc|Base.pMyPursuit|%s|-" % p,
                "link|pc|Base.pMyCar|carp|-"]
        refill = fill("pc", "tPlayerCop", "b%d" % k, COP_KEEP)
        refill += ["link|pc|Base.pMyPursuit|%s|-" % rp,
                   "link|pc|Base.pMyCar|carn|-"]
        if rid is not None:
            refill += ["set|pur4|nPursuitId|" + i8(rid)]
        out += cycle(["call|playercop|pc"], ["dump|pc"], refill,
                     ["set|pc|bPrevCopLightState|" + i32(k + 2)])
    out += ["set|pur4|nPursuitId|" + i8(2)]
    return out


# An AI cop's radar trap taken, the restore's, and the trap's cop before;
# its pursuit; what IsCopInPursuit says.
AICOP_CASES = (("cmt[2]", "cmt[1]", "ac1", "pur2", 1),
               ("0", "cmt[3]", "pc", "pur", 1),
               ("cmt[0]", "0", "0", "0", 0),
               ("cmt[3]", "cmt[3]", "ac0", "pur", 0))


def sc_aicop():
    out = ["# aicop"]
    for k, (tr, rtr, tc, p, inc) in enumerate(AICOP_CASES):
        out += ["# aicop %d" % k, "incop|%d" % inc]
        out += fill("ac0", "tAICop", "a%d" % k, COP_KEEP)
        out += ["link|ac0|Base.pMyPursuit|%s|-" % p,
                "link|ac0|Base.pMyCar|carn|-",
                "link|ac0|pMySpeedTrap|%s|-" % tr,
                "link|ac0|RouteInfo.Route|rt%d|-" % (k % 2),
                "link|ac0|RouteInfo.Point|pt%d|-" % (k % 3)]
        out += ["link|cmt[%d]|cop|%s|-" % (i, tc) for i in range(4)]
        refill = fill("ac0", "tAICop", "b%d" % k, COP_KEEP)
        refill += ["link|ac0|Base.pMyPursuit|pur|-",
                   "link|ac0|Base.pMyCar|carp|-",
                   "link|ac0|pMySpeedTrap|%s|-" % rtr,
                   "link|ac0|RouteInfo.Route|rt1|-",
                   "link|ac0|RouteInfo.Point|pt2|-"]
        refill += ["link|cmt[%d]|cop|pc|-" % i for i in range(4)]
        out += cycle(["call|aicop|ac0"], ["dump|ac0", "dump|cmt"], refill,
                     ["set|ac0|fFlankSide|" + fl(9.5 + k)])
    return out


def script():
    return (sc_spikes() + sc_rocket() + sc_strip() + sc_chopper()
            + sc_cops_setup() + sc_pursuit() + sc_playercop() + sc_aicop())


# =================================================================== model

# The retail functions each `call` names.
FNS = {"spikes": 0x001bef90, "rocket": 0x001bf910, "strip": 0x00241898,
       "chopper": 0x001e7d08, "pursuit": 0x0022a548,
       "playercop": 0x0022d7e8, "aicop": 0x0022dd20}

# The recorded snapshots: (object, snapshot) in a0 and a1.
SNAP_STUBS = {"smokeable": 0x002208a0, "tpcoord": 0x00208768,
              "drivetarget": 0x0021ba50}
S_CAR_POINTER = 0x00130910          # World::DoCarPointerSnapshot
S_ROUTE_POINTER = 0x001c2b30        # TrackRouteManager's, TrackRoute **
S_POINT_POINTER = 0x001c2bc8        # TrackRoutePoint **, TrackRoute *
S_STRIP_INIT = 0x002414e8           # tSpikeStrip::Init
S_REMOVE_CHOPPER = 0x001e84a8       # Chopper::RemoveChopperFromWorld
S_CLEAR_VARIABLES = 0x001e7c38      # Chopper::ClearVariables
S_WORLD_POINTER = 0x0014d550        # World::DoPointerSnapshot(Car **)
S_RB_POINTER = 0x00224358           # tCopManager's, tRoadBlock **
S_IS_COP_IN_PURSUIT = 0x0022c920    # tPursuit::IsCopInPursuit


def _s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        e.put32(P_CURRENT_WORLD, 0)
        e.put32(P_COP_MANAGER, 0)
        self.copmgr = 0
        self.incop = 0
        self.register("trm", TRACK_ROUTE_MANAGER, None, 1, 4, 4)
        for what, addr in SNAP_STUBS.items():
            e.stub(addr, self.snaprec(what))
        e.stub(S_CAR_POINTER, self.car_pointer)
        e.stub(S_ROUTE_POINTER, self.route_pointer)
        e.stub(S_POINT_POINTER, self.point_pointer)
        e.stub(S_STRIP_INIT, self.strip_init)
        e.stub(S_REMOVE_CHOPPER, self.plain1("removechopper"))
        e.stub(S_CLEAR_VARIABLES, self.plain1("clearvariables"))
        e.stub(S_WORLD_POINTER, self.world_pointer)
        e.stub(S_RB_POINTER, self.rb_pointer)
        e.stub(S_IS_COP_IN_PURSUIT, self.is_cop_in_pursuit)

    def where(self):
        # The section, and where the data stands: a move swapped with a
        # recorded call shows only there.
        return "%s at=%d" % (csc.Model.where(self),
                             _s32(self.e.u32(self.S + 336)))

    # ---- the stubs

    def snaprec(self, what):
        def fn(em):
            self.emit("%s %s s=%s %s" % (what, self.label(self.arg(0)),
                                         self.snaparg(self.arg(1)),
                                         self.where()))
            return 0
        return fn

    def plain1(self, what):
        def fn(em):
            self.emit("%s %s %s" % (what, self.label(self.arg(0)),
                                    self.where()))
            return 0
        return fn

    def car_pointer(self, em):
        self.emit("carptr w=%s pp=%s s=%s %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.snaparg(self.arg(2)), self.where()))
        return 0

    def route_pointer(self, em):
        self.emit("routeptr m=%s s=%s pp=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.where()))
        return 0

    def point_pointer(self, em):
        self.emit("pointptr m=%s s=%s pp=%s route=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.label(self.arg(3)), self.where()))
        return 0

    def world_pointer(self, em):
        self.emit("worldptr w=%s s=%s pp=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.where()))
        return 0

    def rb_pointer(self, em):
        self.emit("rbptr m=%s s=%s pp=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.where()))
        return 0

    def is_cop_in_pursuit(self, em):
        self.emit("incop p=%s c=%s -> %d %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)), self.incop,
            self.where()))
        return self.incop & M32

    def strip_init(self, em):
        self.emit("stripinit %s a=%s b=%s id=%d life=%08x %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2)), _s32(self.arg(3)),
            self.e.fpr[12] & M32, self.where()))
        return 0

    # ---- the script

    def addr(self, r):
        return 0 if r == "0" else self.ref(r)[1]

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "curworld":
            e.put32(P_CURRENT_WORLD, self.addr(a[1]))
        elif o == "copmgr":
            base = e.alloc(COPMANAGER_SIZE, align=16)
            e.write(base, bytes(COPMANAGER_SIZE))
            e.put32(P_COP_MANAGER, base)
            self.copmgr = base
            self.register(a[1] + "t", base + 8260, "tSpeedTrap", 4, 28,
                          4 * 28)
            self.register(a[1], base, None, 1, COPMANAGER_SIZE,
                          COPMANAGER_SIZE)
        elif o == "mcop":
            e.put32(self.copmgr + 16 + 4 * int(a[1]), self.addr(a[2]))
        elif o == "mpur":
            e.put32(self.copmgr + 52 + 4 * int(a[1]), self.addr(a[2]))
        elif o == "newcar":
            base = e.alloc(CAR_SIZE, align=16)
            e.write(base, bytes(CAR_SIZE))
            e.put32(base + 24, self.addr(a[2]))
            self.register(a[1], base, None, 1, CAR_SIZE, CAR_SIZE)
        elif o == "newworld":
            base = e.alloc(64, align=16)
            e.write(base, bytes(64))
            e.put32(base + 24, self.addr(a[2]))
            self.register(a[1], base, None, 1, 64, 64)
        elif o == "incop":
            self.incop = int(a[1])
        elif o == "call":
            self.call(FNS[a[1]], self.ref(a[2])[1], S)
        else:
            csc.Model.op(self, a)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ============================================================ the harness

def c_fields():
    csc.CLASSES = CLASSES
    return csc.c_fields().replace("tools/carsnap_check.py",
                                  "tools/copsnap_check.py")


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "copsnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="copsnap_test"):
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
                                name="copsnap_test", quiet=True)
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
    hd = ["// Generated by `tools/copsnap_check.py --stubs`. Do not edit.",
          "//"]
    with open(STUBDATA, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The data the linked port files name and nothing linked "
            "defines,", "// zero."] + [""] +
            ['#include "%s"' % h for h in sorted(heads)] + [""] + data) + NL)
    body = ["// The functions the linked port files call and nothing linked",
            "// defines: each stops the run, which the transcript shows."]
    if funcs:
        body += ["", "#include <stdio.h>", "#include <stdlib.h>", "",
                 "static void copsnap_unreached(const char *name)", "{",
                 '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
                 "    exit(3);", "}", ""]
        body += ['void %s(void) { copsnap_unreached("%s"); }' % (f, f)
                 for f in funcs]
    else:
        body += ["//", "// None: the harness defines every one.", "",
                 "typedef int copsnap_stubs_empty;"]
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + body) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ======================================================= the source checks

def table_check():
    """munition.c's DroppedSpikes and Rocket tables hold the new
    DoSnapshots in slot 16, and main.c binds the chopper's."""
    text = (SRC / "munition.c").read_text(encoding="utf-8")
    bad = 0
    for table, fn in (("droppedspikes_vt", "droppedspikes_do_snapshot"),
                      ("rocket_vt", "rocket_do_snapshot")):
        m = re.search(r"static const VtEntry %s\[\w+\] =\s*MUNITION_VT\("
                      r"\s*\w+,\s*(\w+)," % table, text)
        if not m or m.group(1) != fn:
            print("%s slot 16 is %s, not %s"
                  % (table, m.group(1) if m else "?", fn))
            bad += 1
    main = (SRC / "main.c").read_text(encoding="utf-8")
    if not re.search(r"^\s*gChopperDoSnapshotFn\s*=\s*chopper_do_snapshot;",
                     main, re.M):
        print("main.c does not bind gChopperDoSnapshotFn")
        bad += 1
    cop = (SRC / "cop.c").read_text(encoding="utf-8")
    for table, fn in (("tplayercop_vt", "tplayercop_do_snapshot"),
                      ("taicop_vt", "taicop_do_snapshot")):
        m = re.search(r"static const VtEntry %s\[\] = \{(.*?)\};" % table,
                      cop, re.S)
        slots = re.findall(r"\(VtFn\)(\w+)", m.group(1)) if m else []
        if len(slots) < 4 or slots[3] != fn:
            print("cop.c's %s slot 32 is %s, not %s"
                  % (table, slots[3] if len(slots) > 3 else "?", fn))
            bad += 1
    return bad


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


_texts = {}


def L(rel, needle):
    """The whole line of `rel` holding `needle`, with its newline; there
    must be one."""
    if rel not in _texts:
        _texts[rel] = (SRC / rel).read_text(encoding="utf-8")
    lines = [ln for ln in _texts[rel].splitlines(True) if needle in ln]
    assert len(lines) == 1, (rel, needle, len(lines))
    return lines[0]


def gone(name, needle, rel="copsnap.c"):
    return M(name, rel, L(rel, needle), "")


def swap(name, n1, n2, rel="copsnap.c"):
    a, c = L(rel, n1), L(rel, n2)
    return M(name, rel, a + c, c + a)


def sub(name, needle, before, after, rel="copsnap.c"):
    line = L(rel, needle)
    assert line.count(before) == 1, (name, before)
    return M(name, rel, line, line.replace(before, after))


MUTATIONS = [
    # -- DroppedSpikes ------------------------------------------------------
    sub("ds-section-noobj", '"DroppedSpikes"',
        "BeginSection(s, d, ", "BeginSection(s, NULL, "),
    sub("ds-section-name", '"DroppedSpikes"', '"DroppedSpikes"', '"Spikes"'),
    gone("ds-deploy-gone", "&d->DeploySpikes"),
    sub("ds-deploy-wide", "&d->DeploySpikes", "DeploySpikes, 1)",
        "DeploySpikes, 4)"),
    M("ds-smokeable-first", "copsnap.c",
      L("copsnap.c", "&d->DeploySpikes") + "    smokeable_do_snapshot(b, s);" + NL,
      "    smokeable_do_snapshot(b, s);" + NL + L("copsnap.c", "&d->DeploySpikes")),
    M("ds-smokeable-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// The yaw",
      "    ReplaySnapshot_EndSection(s);\n}\n\n// The yaw"),
    M("ds-end-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// The yaw",
      "    smokeable_do_snapshot(b, s);\n}\n\n// The yaw"),
    # -- Rocket -------------------------------------------------------------
    sub("rk-section-noobj", '"Rocket"', "BeginSection(s, r, ",
        "BeginSection(s, NULL, "),
    gone("rk-yaw-gone", "&r->Yaw"),
    gone("rk-target-gone", "&r->Target"),
    swap("rk-target-first", "&r->Yaw", "&r->Target"),
    sub("rk-world-null", "&r->Target", "pCurrentWorld", "NULL"),
    M("rk-smokeable-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// ---",
      "    ReplaySnapshot_EndSection(s);\n}\n\n// ---"),
    # -- tSpikeStrip --------------------------------------------------------
    sub("ss-section-name", '"tSpikeStrip"', '"tSpikeStrip"', '"SpikeStrip"'),
    gone("ss-start-gone", "MoveVector2(s, &t->v2Start)"),
    swap("ss-ends-swapped", "MoveVector2(s, &t->v2Start)",
         "MoveVector2(s, &t->v2End)"),
    sub("ss-id-short", "MoveInt(s, &t->nRoadBlockID", "nRoadBlockID, 4)",
        "nRoadBlockID, 2)"),
    gone("ss-life-gone", "MoveFloat(s, &t->fLifetime)"),
    M("ss-init-taking", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)" + NL + "        tspikestrip_init(",
      "    if (s->TakingSnapshotFlag)" + NL + "        tspikestrip_init("),
    M("ss-init-always", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)\n        tspikestrip_init(",
      "    if (1)\n        tspikestrip_init("),
    sub("ss-init-ends-swapped", "tspikestrip_init(t,",
        "&t->v2Start, &t->v2End", "&t->v2End, &t->v2Start"),
    sub("ss-init-id", "tspikestrip_init(t,", "t->nRoadBlockID", "0"),
    M("ss-init-life", "copsnap.c",
      "                         t->fLifetime);",
      "                         t->fBlinkTimer);"),
    gone("ss-blink-gone", "&t->bIsBlinking"),
    sub("ss-blink-wide", "&t->bIsBlinking", "bIsBlinking, 1)",
        "bIsBlinking, 4)"),
    M("ss-blink-before-init", "copsnap.c",
      L("copsnap.c", "MoveFloat(s, &t->fLifetime)") +
      "    if (s->RestoringSnapshotFlag)\n"
      "        tspikestrip_init(t, &t->v2Start, &t->v2End, t->nRoadBlockID,\n"
      "                         t->fLifetime);\n" +
      L("copsnap.c", "&t->bIsBlinking"),
      L("copsnap.c", "MoveFloat(s, &t->fLifetime)") +
      L("copsnap.c", "&t->bIsBlinking") +
      "    if (s->RestoringSnapshotFlag)\n"
      "        tspikestrip_init(t, &t->v2Start, &t->v2End, t->nRoadBlockID,\n"
      "                         t->fLifetime);\n"),
    gone("ss-timer-gone", "&t->fBlinkTimer"),
    # -- Chopper ------------------------------------------------------------
    sub("ch-section-name", '"Chopper"', '"Chopper"', '"Helicopter"'),
    M("ch-remove-taking", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)" + NL + "        chopper_remove_from_world(",
      "    if (s->TakingSnapshotFlag)" + NL + "        chopper_remove_from_world("),
    gone("ch-remove-gone", "chopper_remove_from_world(h);"),
    sub("ch-plan-wide", "&h->Plan", "Plan, 1, -1, 0)", "Plan, 4, -1, 0)"),
    sub("ch-plan-whole-word", "&h->Plan", "Plan, 1, -1, 0)", "Plan, 1, 4, 0)"),
    sub("ch-donuts-5", "CHOPPLAN_EATING_DONUTS", "CHOPPLAN_EATING_DONUTS",
        "CHOPPLAN_END_CHASE"),
    sub("ch-donuts-byte", "CHOPPLAN_EATING_DONUTS", "h->Plan ==",
        "(uint8_t)h->Plan =="),
    sub("ch-clear-taking-only", "s->TakingSnapshotFlag || s->Restoring",
        " || s->RestoringSnapshotFlag", ""),
    sub("ch-clear-restoring-only", "s->TakingSnapshotFlag || s->Restoring",
        "s->TakingSnapshotFlag || ", ""),
    sub("ch-clear-checksum", "s->TakingSnapshotFlag || s->Restoring",
        "s->TakingSnapshotFlag", "s->TakingChecksumFlag"),
    gone("ch-clear-gone", "chopper_clear_variables(h);"),
    M("ch-donuts-no-end", "copsnap.c",
      "            chopper_clear_variables(h);\n"
      "        ReplaySnapshot_EndNamedSection(s);\n",
      "            chopper_clear_variables(h);\n"),
    gone("ch-think-gone", "&h->TimeUntilThink"),
    gone("ch-car-gone", "&h->CurrentCar"),
    sub("ch-car-world-null", "&h->CurrentCar", "pCurrentWorld", "NULL"),
    gone("ch-movemode-gone", "&h->MoveMode"),
    sub("ch-movemode-wide", "&h->MoveMode", "MoveMode, 1, -1", "MoveMode, 4, -1"),
    gone("ch-route-gone", "&h->ChopperRoute)"),
    sub("ch-point-target-route", "h->ChopperRoute);     //  740",
        "h->ChopperRoute", "h->TargetRoute"),
    sub("ch-targetpoint-null-route", "h->TargetRoute);      //  748",
        "h->TargetRoute", "NULL"),
    sub("ch-route-target", "&h->ChopperRoute)", "&h->ChopperRoute",
        "&h->TargetRoute"),
    gone("ch-oldroute-gone", "&h->OldCarRoute)"),
    M("ch-oldpoint-gone", "copsnap.c",
      "    trmgr_do_point_pointer_snapshot_in_route(m, s, &h->OldCarPoint,\n"
      "                                             h->OldCarRoute);      //  800\n",
      ""),
    gone("ch-tp-gone", "trackpath_coord_do_snapshot(&h->TP, s);"),
    swap("ch-tp-after-pos", "trackpath_coord_do_snapshot(&h->TP, s);",
         "&h->CurrentPos"),
    gone("ch-pos-gone", "&h->CurrentPos"),
    gone("ch-matrix-gone", "&h->Matrix"),
    gone("ch-speed-gone", "&h->Speed"),
    gone("ch-accel-gone", "&h->Acceleration"),
    swap("ch-rolls-swapped", "&h->Roll)", "&h->DesiredRoll)"),
    gone("ch-yaw-gone", "&h->Yaw"),
    swap("ch-pitches-swapped", "&h->Pitch)", "&h->DesiredPitch)"),
    gone("ch-rotrate-gone", "&h->RotRate"),
    gone("ch-zvel-gone", "&h->ZVelocity"),
    gone("ch-groundz-gone", "&h->GroundZ"),
    gone("ch-dust-gone", "&h->EmitDust"),
    sub("ch-dust-wide", "&h->EmitDust", "EmitDust, 1)", "EmitDust, 4)"),
    gone("ch-targetdist-gone", "&h->TargetDistance"),
    swap("ch-targetdist-before-dust", "&h->EmitDust", "&h->TargetDistance"),
    gone("ch-bombrun-gone", "&h->BombRunType"),
    sub("ch-bombrun-wide", "&h->BombRunType", "BombRunType, 1, -1",
        "BombRunType, 4, -1"),
    sub("ch-salvos-short", "&h->NumSalvosReleased",
        "NumSalvosReleased, 4)", "NumSalvosReleased, 2)"),
    gone("ch-nextsalvo-gone", "&h->TimeUntilNextSalvo"),
    gone("ch-launcher-gone", "&h->NextLauncher"),
    gone("ch-timeout-gone", "&h->Timeout"),
    swap("ch-timeout-stuck-swapped", "&h->Timeout", "&h->StuckTime"),
    gone("ch-total-gone", "&h->TotalSalvos"),
    sub("ch-total-short", "&h->TotalSalvos", "TotalSalvos, 4)",
        "TotalSalvos, 2)"),
    M("ch-end-gone", "copsnap.c",
      L("copsnap.c", "&h->TotalSalvos") +
      "    ReplaySnapshot_EndNamedSection(s);\n",
      L("copsnap.c", "&h->TotalSalvos")),
    # -- the cop manager's pointers (72e-2) ---------------------------------
    M("pp-restore-taking", "copsnap.c",
      "    int8_t c = -1;\n\n    if (s->RestoringSnapshotFlag) {",
      "    int8_t c = -1;\n\n    if (s->TakingSnapshotFlag) {"),
    M("pp-null-kept", "copsnap.c",
      "        *pp = NULL;\n        if (c >= 0)",
      "        if (c >= 0)"),
    sub("pp-zero-is-none", "if (c >= 0)", "c >= 0", "c > 0"),
    M("pp-no-return", "copsnap.c",
      "            *pp = m->PursuitsById[c];\n        return;\n",
      "            *pp = m->PursuitsById[c];\n"),
    sub("pp-id-zero", "c = (*pp)->nPursuitId;", "(*pp)->nPursuitId", "0"),
    sub("cp-number-gone", "n = (*pp)->nCopNumber;", "(*pp)->nCopNumber",
        "n"),
    sub("cp-next-cop", "*pp = m->Cops[n];", "Cops[n]", "Cops[n + 1]"),
    M("cp-stored-4", "copsnap.c",
      "        n = (*pp)->nCopNumber;\n    ReplaySnapshot_MoveInt(s, &n, 1);",
      "        n = (*pp)->nCopNumber;\n    ReplaySnapshot_MoveInt(s, &n, 4);"),
    M("cp-zero-is-none", "copsnap.c",
      "        if (n >= 0)\n            *pp = m->Cops[n];",
      "        if (n > 0)\n            *pp = m->Cops[n];"),
    M("cp-null-kept", "copsnap.c",
      "        *pp = NULL;\n        if (n >= 0)\n            *pp = m->Cops[n];",
      "        if (n >= 0)\n            *pp = m->Cops[n];"),
    M("cp-restore-checksum", "copsnap.c",
      "    ReplaySnapshot_MoveInt(s, &n, 1);\n"
      "    if (s->RestoringSnapshotFlag) {\n        *pp = NULL;\n"
      "        if (n >= 0)\n            *pp = m->Cops[n];",
      "    ReplaySnapshot_MoveInt(s, &n, 1);\n"
      "    if (s->TakingChecksumFlag) {\n        *pp = NULL;\n"
      "        if (n >= 0)\n            *pp = m->Cops[n];"),
    sub("st-index-off", "n = (int32_t)(*pp - m->SpeedTraps);",
        "*pp - m->SpeedTraps", "*pp - m->SpeedTraps + 1"),
    sub("st-next", "*pp = &m->SpeedTraps[n];", "[n]", "[n + 1]"),
    M("st-stored-4", "copsnap.c",
      "        n = (int32_t)(*pp - m->SpeedTraps);\n"
      "    ReplaySnapshot_MoveInt(s, &n, 1);",
      "        n = (int32_t)(*pp - m->SpeedTraps);\n"
      "    ReplaySnapshot_MoveInt(s, &n, 4);"),
    M("st-null-kept", "copsnap.c",
      "        *pp = NULL;\n        if (n >= 0)\n"
      "            *pp = &m->SpeedTraps[n];",
      "        if (n >= 0)\n            *pp = &m->SpeedTraps[n];"),
    # -- the history ---------------------------------------------------------
    sub("hi-count-wide", "&h->nCount", "nCount, 1)", "nCount, 4)"),
    sub("hi-29", "for (i = 0; i < 30; i++) {", "< 30", "< 29"),
    swap("hi-time-first", "&h->v2Velocity[i]", "&h->fTime[i]"),
    gone("hi-time-gone", "&h->fTime[i]"),
    # -- the roadblock's state machine ---------------------------------------
    sub("sm-state-wide", "&sm->State", "State, 1, -1", "State, 4, -1"),
    gone("sm-timer-gone", "&sm->fStateTimer"),
    sub("sm-speech-short", "&sm->SpeechFlags", "SpeechFlags, 4)",
        "SpeechFlags, 2)"),
    swap("sm-count-first", "&sm->SpeechFlags", "&sm->nRoadBlockCount"),
    gone("sm-count-gone", "&sm->nRoadBlockCount"),
    gone("sm-pursuit-gone", "sm->pPursuit = p;"),
    sub("sm-pursuit-restoring", "sm->pPursuit = p;", "sm->pPursuit = p;",
        "if (s->RestoringSnapshotFlag) sm->pPursuit = p;"),
    # -- the barrels ---------------------------------------------------------
    sub("bm-section-name", '"BarricadeManager"', '"BarricadeManager"',
        '"Barricades"'),
    swap("bm-id-first", "&b->fFadeTimer[i]", "&b->nBarrel[i]"),
    sub("bm-id-byte", "&b->nBarrel[i]", "nBarrel[i], 2)", "nBarrel[i], 1)"),
    sub("bm-nine", "for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {",
        "BARRICADE_MAX_BARRELS", "BARRICADE_MAX_BARRELS - 1"),
    gone("bm-timer-gone", "&b->fFadeTimer[i]"),
    M("bm-end-gone", "copsnap.c",
      "        ReplaySnapshot_MoveShort(s, &b->nBarrel[i], 2);            //"
      "    0\n    }\n    ReplaySnapshot_EndNamedSection(s);\n",
      "        ReplaySnapshot_MoveShort(s, &b->nBarrel[i], 2);            //"
      "    0\n    }\n"),
    # -- the pursuit ---------------------------------------------------------
    sub("pu-section-noobj", '"tPursuit"', "BeginSection(s, p, ",
        "BeginSection(s, NULL, "),
    gone("pu-verify-gone", "&p->nPursuitId, 1)"),
    sub("pu-verify-moves", "&p->nPursuitId, 1)", "VerifyChar", "MoveChar"),
    gone("pu-car-gone", "&p->pChasedCar)"),
    sub("pu-car-world-null", "&p->pChasedCar)", "pCurrentWorld", "NULL"),
    M("pu-roadblock-gone", "copsnap.c",
      "    copmanager_do_road_block_pointer_snapshot(pCopManager, s,\n"
      "                                              &p->pRoadBlock);"
      "     //   20\n", ""),
    gone("pu-rb-speaker-gone", "&p->pRoadBlock->CopSpeaker"),
    sub("pu-rb-one-cop", "        for (i = 0; i < 2; i++)", "< 2", "< 1"),
    sub("pu-rb-same-cop", "(tCop **)&p->pRoadBlock->cops[i]", "cops[i]",
        "cops[0]"),
    swap("pu-speakers-swapped", "&p->PrimaryCopSpeaker",
         "&p->SecondaryCopSpeaker"),
    swap("pu-maxcops-swapped", "&p->nMaxChaseCops", "&p->nMaxRoadBlockCops"),
    gone("pu-rbcount-gone", "&p->nRoadblockCount"),
    sub("pu-chopper-byte", "MoveInt(s, &chopper, 4)", "chopper, 4)",
        "chopper, 1)"),
    gone("pu-chopper-null-kept", "        p->pChopper = NULL;"),
    sub("pu-chopper-world-null", "p->pChopper = pCurrentWorld->Helicopter;",
        "pCurrentWorld->Helicopter", "NULL"),
    M("pu-chopper-taking", "copsnap.c",
      "    ReplaySnapshot_MoveInt(s, &chopper, 4);"
      "                        //   24\n    if (s->RestoringSnapshotFlag) {",
      "    ReplaySnapshot_MoveInt(s, &chopper, 4);"
      "                        //   24\n    if (s->TakingSnapshotFlag) {"),
    sub("pu-chopper-flag-inverted", "chopper = p->pChopper != NULL;",
        "!= NULL", "== NULL"),
    swap("pu-attack-swapped", "&p->fChopperAttackTimer",
         "&p->fChopperNextAttackTime"),
    sub("pu-chopperstate-wide", "&p->ChopperState", "ChopperState, 1, -1",
        "ChopperState, 4, -1"),
    sub("pu-numcops-byte", "&p->nNumCops, 4)", "nNumCops, 4)",
        "nNumCops, 1)"),
    sub("pu-cops-both", "for (i = 0; i < p->nNumCops; i++)",
        "i < p->nNumCops", "i < 2"),
    swap("pu-states-swapped", "&p->PursuitState,", "&p->PursuitSubState,"),
    sub("pu-landmark-wide", "&p->CurrentLandmark", "CurrentLandmark, 1, -1",
        "CurrentLandmark, 4, -1"),
    swap("pu-spawn-first", "&p->fPursuitStateTimer",
         "&p->fRoadBlockSpawnTimer"),
    swap("pu-catch-first", "&p->fRoadBlockDisbandTimer",
         "&p->fCatchCarTimer"),
    gone("pu-direction-gone", "&p->fChaseDirection)"),
    gone("pu-1556-gone", "&p->New1556"),
    swap("pu-bools-swapped", "&p->bAlreadyJoined", "&p->bAlreadyBeenHit"),
    sub("pu-backup-wide", "&p->bAlreadyCalledForBackup",
        "bAlreadyCalledForBackup, 1)", "bAlreadyCalledForBackup, 4)"),
    gone("pu-topspeed-gone", "&p->fChasedCarTopSpeed"),
    gone("pu-behaviour-gone", "&p->BehaviourFlags"),
    sub("pu-hud-wide", "&p->nHUDPursuitLevel", "nHUDPursuitLevel, 1)",
        "nHUDPursuitLevel, 4)"),
    swap("pu-targets-swapped", "&p->FarDriveTarget", "&p->NearDriveTarget"),
    gone("pu-near-gone", "&p->NearDriveTarget"),
    M("pu-history-always", "copsnap.c",
      "    if (p->pChasedCar->pPlayer != NULL)\n",
      "    if (1)\n"),
    M("pu-history-inverted", "copsnap.c",
      "    if (p->pChasedCar->pPlayer != NULL)\n",
      "    if (p->pChasedCar->pPlayer == NULL)\n"),
    M("pu-machine-gone", "copsnap.c",
      "    troadblockstatemachine_do_snapshot(&p->RoadBlockStateMachine, s,\n"
      "                                       p);                         //"
      " 1560\n", ""),
    sub("pu-machine-null", "                                       p);",
        "p);", "NULL);"),
    gone("pu-barrels-gone", "barricademanager_do_snapshot(p->pBarricades"),
    M("pu-end-gone", "copsnap.c",
      "    barricademanager_do_snapshot(p->pBarricades, s);"
      "               // 1472\n    ReplaySnapshot_EndSection(s);\n",
      "    barricademanager_do_snapshot(p->pBarricades, s);"
      "               // 1472\n"),
    # -- tCop ----------------------------------------------------------------
    sub("tc-section-name", 'BeginNamedSection(s, "tCop")', '"tCop"', '"Cop"'),
    M("tc-pursuit-first", "copsnap.c",
      L("copsnap.c", "&c->pMyCar);") +
      L("copsnap.c", "copmanager_do_pursuit_pointer_snapshot(pCopManager") +
      L("copsnap.c", "&c->pMyPursuit);"),
      L("copsnap.c", "copmanager_do_pursuit_pointer_snapshot(pCopManager") +
      L("copsnap.c", "&c->pMyPursuit);") + L("copsnap.c", "&c->pMyCar);")),
    M("tc-check-gone", "copsnap.c",
      "    if (c->pMyPursuit != NULL) {\n"
      "        if (!tpursuit_is_cop_in_pursuit(c->pMyPursuit, c))\n"
      "            c->pMyPursuit = NULL;\n"
      "        else if (c->pMyPursuit->nPursuitId < 0)\n"
      "            c->pMyPursuit = NULL;\n    }\n", ""),
    M("tc-check-restoring", "copsnap.c",
      "    if (c->pMyPursuit != NULL) {\n",
      "    if (c->pMyPursuit != NULL && s->RestoringSnapshotFlag) {\n"),
    sub("tc-incop-inverted", "if (!tpursuit_is_cop_in_pursuit(",
        "if (!tpursuit", "if (tpursuit"),
    M("tc-id-check-gone", "copsnap.c",
      "            c->pMyPursuit = NULL;\n"
      "        else if (c->pMyPursuit->nPursuitId < 0)\n"
      "            c->pMyPursuit = NULL;\n",
      "            c->pMyPursuit = NULL;\n"),
    sub("tc-id-zero-gone", "else if (c->pMyPursuit->nPursuitId < 0)",
        "< 0", "<= 0"),
    swap("tc-states-swapped", "&c->LogicSubState,", "&c->DesiredLogicState,"),
    sub("tc-state-wide", "&c->LogicState,", "LogicState, 1, -1",
        "LogicState, 4, -1"),
    gone("tc-desiredsub-gone", "&c->DesiredLogicSubState,"),
    # -- tPlayerCop ----------------------------------------------------------
    sub("pc-section-noobj", '"tPlayerCop"', "BeginSection(s, c, ",
        "BeginSection(s, NULL, "),
    M("pc-base-gone", "copsnap.c",
      '    ReplaySnapshot_BeginSection(s, c, "tPlayerCop");\n'
      "    tcop_do_snapshot(&c->Base, s);\n",
      '    ReplaySnapshot_BeginSection(s, c, "tPlayerCop");\n'),
    sub("pc-selection-wide", "&c->nPrevSelection[i]",
        "nPrevSelection[i], 1)", "nPrevSelection[i], 4)"),
    swap("pc-timer-first", "&c->nPrevSelection[i]",
         "&c->fPrevSelectionTimer[i]"),
    M("pc-one-selection", "copsnap.c",
      "    for (i = 0; i < 2; i++) {\n"
      "        ReplaySnapshot_MoveInt(s, &c->nPrevSelection[i], 1);",
      "    for (i = 0; i < 1; i++) {\n"
      "        ReplaySnapshot_MoveInt(s, &c->nPrevSelection[i], 1);"),
    gone("pc-light-gone", "&c->bPrevCopLightState"),
    sub("pc-light-wide", "&c->bPrevCopLightState", "LightState, 1)",
        "LightState, 4)"),
    # -- tAICop --------------------------------------------------------------
    sub("ac-section-name", 'BeginSection(s, c, "tCop")', '"tCop"',
        '"tAICop"'),
    M("ac-base-gone", "copsnap.c",
      '    ReplaySnapshot_BeginSection(s, c, "tCop");\n'
      "    tcop_do_snapshot(&c->Base, s);\n",
      '    ReplaySnapshot_BeginSection(s, c, "tCop");\n'),
    M("ac-trap-gone", "copsnap.c",
      "    copmanager_do_speed_trap_pointer_snapshot(pCopManager, s,\n"
      "                                              &c->pMySpeedTrap);"
      "   //   36\n", ""),
    sub("ac-roadblock-wide", "&c->nMyRoadBlockIndex",
        "nMyRoadBlockIndex, 1)", "nMyRoadBlockIndex, 4)"),
    swap("ac-physics-swapped", "&c->fSecondsInPhysicsMode",
         "&c->fMovementModeSwitchDelay"),
    sub("ac-line-byte", "&c->nDrivingLineIndex", "nDrivingLineIndex, 4)",
        "nDrivingLineIndex, 1)"),
    gone("ac-substate-gone", "&c->fSubStateTimer"),
    swap("ac-48-swapped", "&c->New48.x", "&c->New48.y"),
    gone("ac-dloffset-gone", "&c->MyDLOffset.y"),
    swap("ac-64-swapped", "&c->New64", "&c->New68"),
    gone("ac-flank-gone", "&c->fFlankSide"),
    gone("ac-route-gone", "&c->RouteInfo.Route);"),
    sub("ac-point-null-route", "c->RouteInfo.Route);  //   80",
        "c->RouteInfo.Route", "NULL"),
    sub("ac-trapcop-taking", "if (s->RestoringSnapshotFlag && c->pMySpeedTrap",
        "RestoringSnapshotFlag", "TakingSnapshotFlag"),
    sub("ac-trapcop-always", "if (s->RestoringSnapshotFlag && c->pMySpeedTrap",
        "s->RestoringSnapshotFlag && ", ""),
    sub("ac-trapcop-null", "c->pMySpeedTrap->cop = &c->Base;", "&c->Base",
        "NULL"),
    gone("ac-32-gone", "&c->New32"),
    swap("ac-line-before-delay", "&c->fMovementModeSwitchDelay",
         "&c->nDrivingLineIndex"),
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
            exe = hostbuild.build(bt, srcs, name="copsnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "copsnap_test",
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

    bad = table_check()
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
    print("%d script lines, %d model lines, %d harness lines, %d differ; "
          "tables %s" % (len(lines), len(model), len(harness), n,
                         "bad" if bad else "ok"))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
