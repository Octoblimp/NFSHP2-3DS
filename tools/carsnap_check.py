#!/usr/bin/env python3
"""Cross-check TASKS 72b, the replay's DoSnapshots for the cars and their
physics, against the retail image, SLES_507.31.

**What is checked**: RigidBody, Wheel, Suspension, Engine, DriveTrain,
Aerodynamics, TwoWheelAckermanSteering, PhysicsCar (and CarMover's empty
one), CarState, BodyDamage, CarDamage, CollisionBody (and
StaticCollisionBody's jump to it), TrackPolygonCollisionBody,
DynamicCollisionBody, CarCollisionBody, CollisionBodyWitness, VCWitness,
Collision, TrackPathCoordinate (and TrackPathManager's pointer move),
CarController and Car. Each is taken, restored over other values,
checksummed and verified, alone and as the trees the game builds: a
PhysicsCar with its body, steering, four wheels and suspensions, engine,
drivetrain and aerodynamics, and a Car with that mover, its CarDamage,
CarCollisionBody, CarState and track path coordinate.

**The layouts** are the port's headers, parsed here: every field at the
offset its comment gives, which is retail's but where a map below says
otherwise (CarState after Odometer, the witness's Collision, the whole
Car). The harness gets the same field list as a generated table of
offsetof and sizeof, so each side writes and dumps a field at its own
offset, and a pointer prints as the object and field it points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot, the snapshots themselves, CarCollisionBody's
SetupPhysicsPointers, GetPosition, UpdatePosition and SetBBoxMinMax (the
body alone in CollisionBodyList), the damage's ApplyDamage (no damage
models), VClip's feature codes, CarState's CalculateWheelMatrices (with
the wheels' suspension heights and WheelInfo's word at 24 zero, where
retail and the port part, TASKS 73), bIdentity and bSPrintf. Recorded on
both sides, as lines both print: a recording vtable (the RigidBody's
ComputeAuxiliaries, the controller's DoSnapshot, the CarController's
driver), ClearInterestBBox, SetControlMode, SetMovementMode, SwitchSkin,
UpdateCarReplacementTextures, AnimatedDriver::DoSnapshot, and the new
Collision (bOMalloc and the constructor in retail, gCollisionNewFn in the
port). bBreak counts, as replay_breaks does.

**A disc replay's cars** (TASKS 72h-2b): retail gives every car but
traffic an AnimatedDriver, and the port none, so while a disc replay plays
the port moves the driver's section itself (car.h,
gCarSnapshotRetailDrivers). The model's car has a real driver for the call
alone (`rdriver`), and retail's AnimatedDriver::DoSnapshot runs for real;
its restore's CancelAllAnimations is stubbed silently, with no animations
to cancel. The harness's car has none, and the flag. A racer, a traffic
car and a racer with the flag clear.

    python tools/carsnap_check.py
    python tools/carsnap_check.py --fields
    python tools/carsnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/carsnap_check.py --dump out/carsnap
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "carsnap_test.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in (
    "carsnap.c", "replay.c", "p32.c", "vtable.c",
    "rigidbody.c", "wheel.c", "suspension.c", "engine.c", "drivetrain.c",
    "aerodynamics.c", "steering.c", "physcomp.c", "physicscar.c",
    "physicssystem.c", "carstate.c", "cardamage.c", "estripdata.c",
    "collisionbody.c", "carcollisionbody.c", "contact.c", "vclip.c",
    "collision.c", "trackpath.c", "carcontroller.c",
    "table.c", "bslotpool.c", "bmem.c", "bticker.c", "emath.c",
    "bmatrix.c", "bvector.c", "bmath.c", "bmathtab.c")]

GP = retail_model.RETAIL_GP
WORLD_TIMER = GP - 19576
WORLD_LOOP = GP - 19552

SNAP_SIZE = 38232
DATA = 344
DATA_SIZE = 37888
F_INIT = 0x0013cce8
S_BBREAK = 0x00250ab0
LIMIT = 4000000

# ================================================================ the layout
#
# Which header holds each record. The trees' records and the ones nested in
# them; a record not here and not in TYPES is an error, so nothing is
# dumped by guess.

HEADERS = {
    "RigidBodyState": "rigidbody.h", "RigidBody": "rigidbody.h",
    "WheelState": "wheel.h", "SkidMaker": "wheel.h", "Wheel": "wheel.h",
    "SuspensionState": "suspension.h", "Suspension": "suspension.h",
    "EngineState": "engine.h", "Engine": "engine.h",
    "DriveTrainState": "drivetrain.h", "DriveTrain": "drivetrain.h",
    "Aerodynamics": "aerodynamics.h",
    "Steering": "steering.h", "TwoWheelAckermanSteering": "steering.h",
    "CarMover": "physicscar.h", "PhysicsSystem": "physicssystem.h",
    "PhysicsCar": "physicscar.h",
    "CarState": "carstate.h",
    "BodyDamageModel": "cardamage.h", "BodyDamage": "cardamage.h",
    "CarDamage": "cardamage.h",
    "CollisionBodyNode": "collisionbody.h",
    "CollisionBody": "collisionbody.h",
    "StaticCollisionBody": "collisionbody.h",
    "TrackPolygonCollisionBody": "collisionbody.h",
    "DynamicCollisionBody": "collisionbody.h",
    "CarCollisionBody": "collisionbody.h",
    "CollisionBodyWitness": "collisionbody.h",
    "VCFeature": "vclip.h", "VCWitness": "vclip.h",
    "VCPolyhedron": "vclip.h", "VCVertex": "vclip.h", "VCEdge": "vclip.h",
    "VCFace": "vclip.h",
    "Collision": "collision.h",
    "TrackPathCoordinate": "trackpath.h", "TrackPathPoint": "trackpath.h",
    "CarController": "carcontroller.h",
    "RideInfo": "car.h",
    "Car": "car.h",
}

# Plain types: size, and whether its words are floats (for the fills).
TYPES = {
    "float": (4, True), "int32_t": (4, False), "uint32_t": (4, False),
    "int": (4, False), "int16_t": (2, False), "uint16_t": (2, False),
    "int8_t": (1, False), "uint8_t": (1, False), "char": (1, False),
    "bVector2": (8, True), "bVector3": (16, True), "bVector4": (16, True),
    "bMatrix4": (64, True), "VCPlane": (16, True),
    "Timer": (4, False), "TerrainType": (4, False), "Gear": (4, False),
    "ClutchState": (4, False), "ControlMode": (4, False),
    "MovementMode": (4, False), "SirenMode": (4, False),
    "SignalLightStateEnum": (4, False),
}

# Records nothing here reads or writes, left out of the fills and dumps:
# list links the snapshots never follow, tables, the wafer.
SKIP_TYPES = {"bNode", "CarNode", "CollisionBodyWitnessNode", "CollisionNode",
              "VCPolyhedronNode", "Table", "WaferPolyhedron",
              "TopologyCoordinate", "OverrideRenderingPosition"}

# Array lengths the headers spell as macros.
MACROS = {"BODYDAMAGE_ZONES": 32, "BODYDAMAGE_MODELS": 4,
          "CARDAMAGE_ITEMS": 15, "ACKERMAN_MATRICES": 2}

# Retail's offset where it is not the port's comment's.
RETAIL_OFF = {
    ("CarState", "DistanceMoved"): 876,
    ("CarState", "TractionUsage"): 880, ("CarState", "SkidLeft"): 884,
    ("CarState", "SkidRight"): 888,
    ("CarState", "nWheelsTouchingGround"): 892,
    ("CarState", "ForwardSpeed"): 896,
    ("CarState", "VelocityMagnitude"): 900,
    ("CarState", "CurrentGear"): 904, ("CarState", "Throttle"): 908,
    ("CarState", "RPM"): 912, ("CarState", "RedLineSyncRPM"): 916,
    ("CarState", "ClutchEngaged"): 920, ("CarState", "DriverMode"): 924,
    ("CarState", "BoostFactor"): 928, ("CarState", "BurnOutState"): 932,
    ("CarState", "BurnOutTime"): 936, ("CarState", "BurnOutTraction"): 940,
    ("CarState", "BurnOutAllow"): 944,
    ("CarState", "RelCoordMatrix"): 960, ("CarState", "MatrixValid"): 1024,
    ("CollisionBodyWitness", "pCollision"): 108,
    # The port keeps the demo's two floats where they were and puts
    # retail's Timer after them.
    ("PhysicsCar", "FlippedTimer"): 108, ("PhysicsCar", "FrictionBoost"): 112,
    ("PhysicsCar", "YawControlMultiplier"): 116,
}

# Car: retail's offset for each field the checker writes or reads; the
# others are left out.
CAR_MAP = {
    "CarIndex": 8, "DriverNumber": 10, "pCarTypeInfo": 12, "pRideInfo": 16,
    "TheControlMode": 32, "TheMovementMode": 36, "pCarController": 40,
    "pCarDriver": 44, "pCarMover": 48, "pDynamicCollisionBody": 52,
    "State": 64,
    "DispGear": 1104, "FrictionBoost": 1108, "DraftFactor": 1112,
    "fTractionBoostOverride": 1116, "fDamageBoostOverride": 1120,
    "vOldPos": 1136, "OldSpeed": 1184, "AirTimeSwitch": 1188,
    "RenderingEnabled": 1192, "DriverRenderingEnabled": 1196,
    "pRenderInfo": 1200, "pAnimatedDriver": 1204,
    "TheTrackPathCoordinate": 2016,
    "CopLights": 2056, "SignalLightState": 2060, "NitroEffectFlag": 2064,
    "WantToBlinkHeadlights": 2068, "WantToHonkHorn": 2072,
    "WantTwoHonksAndOrBlinks": 2076, "HeadlightsAndHornStartTime": 2080,
    "HeadlightsAndHornOnDuration": 2084,
    "HeadlightsAndHornSecondOnDuration": 2088,
    "HeadlightsAndHornOffDuration": 2092, "ForceHeadlightsOn": 2096,
    "HeadlightsState": 2100, "TheSirenMode": 2104, "WiperOnTime": 2108,
    "WiperOffTime": 2112, "WiperState": 2116, "pCarDamage": 2120,
    "BlownTireBits": 2124, "NumBlownTires": 2125,
    "fBlownTireControllerRumbleTimer": 2128, "pBaseCarSound": 2132,
    "ResetMe": 2136, "JustResetFrames": 2140, "BlinkTimer": 2144,
    "BlinkDuration": 2148, "LastInTroughPosition": 2152, "bPoofed": 2160,
    "bVisibleOnTrackMap": 2164, "NumTimesSkidding": 2168,
    "RoadBumpBits": 2172, "pCaffeineObj": 2176, "ForceBuzzTime": 2188,
    "InDeepWaterRegistered": 2196,
}

# Retail sizes where no closing comment gives one.
RETAIL_SIZE = {"CarState": 1040, "Car": 2224, "Engine": 92,
               "TrackPathCoordinate": 40, "TrackPathPoint": 20,
               "TwoWheelAckermanSteering": 144, "CarMover": 8,
               "Steering": 12, "WheelState": 8, "SuspensionState": 8,
               "EngineState": 4, "DriveTrainState": 4, "SkidMaker": 4}

# The records a script can make, in the order of the generated table.
CLASSES = ["RigidBody", "Wheel", "Suspension", "Engine", "DriveTrain",
           "Aerodynamics", "TwoWheelAckermanSteering", "PhysicsCar",
           "CarState", "BodyDamage", "CarDamage", "CollisionBody",
           "TrackPolygonCollisionBody", "DynamicCollisionBody",
           "CarCollisionBody", "CollisionBodyWitness", "VCWitness",
           "VCPolyhedron", "VCVertex", "VCEdge", "VCFace", "Collision",
           "TrackPathCoordinate", "TrackPathPoint", "CarController",
           "RideInfo", "Car"]

FIELD_RE = re.compile(
    r"^\s*(?:const\s+)?(?:struct\s+|enum\s+)?(\w+)\s*(\*?)\s*(?:const\s+)?"
    r"(\w+)\s*(?:\[(\w+)\])?\s*;\s*(?://\s*(\d+))?")


class Raw(object):
    """A declaration line: type, pointer, name, array length, the comment's
    offset (None when the comment has none)."""
    def __init__(self, ctype, ptr, name, dim, off):
        self.ctype, self.ptr, self.name, self.dim, self.off = (
            ctype, ptr, name, dim, off)


class Field(object):
    """A flattened field: its path (also the C member designator), retail
    offset, retail size, kind (raw / ptr / vptr) and whether its words are
    floats."""
    def __init__(self, path, roff, size, kind, isfloat=False):
        self.path, self.roff, self.size, self.kind, self.isfloat = (
            path, roff, size, kind, isfloat)


_texts = {}


def _text(h):
    if h not in _texts:
        _texts[h] = (SRC / h).read_text(encoding="utf-8")
    return _texts[h]


def struct_body(name):
    """The lines between a record's braces, and its closing comment's size
    (or None)."""
    text = _text(HEADERS[name])
    m = re.search(r"^(?:typedef\s+)?struct\s+%s\s*\{(.*?)^\}\s*(\w*)\s*;"
                  r"[ \t]*(?://\s*(\d+))?" % name, text, re.S | re.M)
    if not m:
        m2 = re.search(r"^\}\s*%s\s*;[ \t]*(?://\s*(\d+))?" % name, text,
                       re.M)
        assert m2, name
        start = text.rfind("typedef struct", 0, m2.start())
        brace = text.index("{", start)
        return text[brace + 1:m2.start()], (int(m2.group(1))
                                             if m2.group(1) else None)
    return m.group(1), int(m.group(3)) if m.group(3) else None


def parse(name):
    body, size = struct_body(name)
    out = []
    depth = 0
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith(("//", "#")):
            continue
        if s.startswith(("struct", "union")) and s.endswith("{"):
            raise ValueError("%s: nested record in %s" % (s, name))
        code = s.split("//")[0]
        if ";" not in code:
            continue
        fm = FIELD_RE.match(ln)
        if not fm:
            raise ValueError("%s: cannot parse %r" % (name, ln))
        ctype, star, fname, dim, off = fm.groups()
        d = None
        if dim is not None:
            d = int(dim) if dim.isdigit() else MACROS[dim]
        out.append(Raw(ctype, bool(star), fname, d,
                       None if off is None else int(off)))
    del depth
    return out, size


def type_size(ctype):
    if ctype in TYPES:
        return TYPES[ctype][0]
    return record_size(ctype)


_sizes = {}


def record_size(name):
    if name in RETAIL_SIZE:
        return RETAIL_SIZE[name]
    if name not in _sizes:
        raws, size = parse(name)
        if size is None:
            raise ValueError("no retail size for %s" % name)
        _sizes[name] = size
    return _sizes[name]


_flat = {}


def flatten(name):
    """Every field of the record, nested records opened, at retail's
    offsets relative to the record."""
    if name in _flat:
        return _flat[name]
    raws, _ = parse(name)
    out = []
    off = 0
    for r in raws:
        if r.off is not None:
            off = r.off
        size1 = 4 if r.ptr else (None if r.ctype in SKIP_TYPES
                                 else type_size(r.ctype))
        n = r.dim or 1
        here = off
        if size1 is not None:
            off = here + size1 * n
        if name == "Car":
            if r.name not in CAR_MAP:
                continue
            here = CAR_MAP[r.name]
        else:
            here = RETAIL_OFF.get((name, r.name), here)
        if r.name.startswith(("_pad", "_hole", "_tail", "_head")):
            continue
        if r.ctype in SKIP_TYPES and not r.ptr:
            continue
        if r.name == "_vtable":
            out.append(Field(r.name, here, 4, "vptr"))
        elif r.ptr:
            if r.dim:
                for i in range(n):
                    out.append(Field("%s[%d]" % (r.name, i), here + 4 * i,
                                     4, "ptr"))
            else:
                out.append(Field(r.name, here, 4, "ptr"))
        elif r.ctype in TYPES:
            out.append(Field(r.name, here, size1 * n, "raw",
                             TYPES[r.ctype][1]))
        elif r.ctype in HEADERS:
            sub = flatten(r.ctype)
            for i in range(n):
                pfx = "%s[%d]" % (r.name, i) if r.dim else r.name
                for f in sub:
                    out.append(Field(pfx + "." + f.path,
                                     here + size1 * i + f.roff, f.size,
                                     f.kind, f.isfloat))
        else:
            raise ValueError("%s.%s: type %s is not known"
                             % (name, r.name, r.ctype))
    _flat[name] = out
    return out


def path_off(cls, path):
    """A field's retail offset, or a nested record's: its first field's."""
    best = None
    for f in flatten(cls):
        if f.path == path:
            return f.roff
        if f.path.startswith((path + ".", path + "[")):
            best = f.roff if best is None else min(best, f.roff)
    if best is None:
        raise KeyError("%s.%s" % (cls, path))
    return best


def alloc_size(name):
    """Retail's size for an object of the record."""
    try:
        return record_size(name)
    except ValueError:
        end = max(f.roff + f.size for f in flatten(name))
        return (end + 15) & ~15


# ================================================================ the fills

def fill_bytes(f, rng):
    if f.isfloat:
        return b"".join(struct.pack("<f", rng.randint(-96, 96) / 8.0)
                        for _ in range(f.size // 4))
    if f.size == 4:
        if rng.random() < 0.7:
            v = rng.randint(-2, 9)
        else:
            v = rng.getrandbits(32)
        return struct.pack("<I", v & M32)
    if f.size == 2:
        v = rng.randint(-2, 9) if rng.random() < 0.7 else rng.getrandbits(16)
        return struct.pack("<H", v & 0xffff)
    return bytes(rng.getrandbits(8) for _ in range(f.size))


def fill(ref, cls, seed, keep=()):
    """`set` lines for every raw field of the object but those whose path
    starts with one of `keep`, from a generator seeded by the object and
    the seed."""
    rng = random.Random("%s:%s:%s" % (seed, ref, cls))
    out = []
    for f in flatten(cls):
        if f.kind != "raw":
            continue
        data = fill_bytes(f, rng)
        if any(f.path == k or f.path.startswith(k + ".")
               or f.path.startswith(k + "[") for k in keep):
            continue
        out.append("set|%s|%s|%s" % (ref, f.path, data.hex()))
    return out


def fl(*vs):
    return b"".join(struct.pack("<f", v) for v in vs).hex()


def i32(v):
    return struct.pack("<I", v & M32).hex()


def i16(v):
    return struct.pack("<H", v & 0xffff).hex()


def i8(v):
    return bytes([v & 0xff]).hex()


def mat(kind, k=1.0):
    """A matrix whose MoveMatrix code is `kind`: 1 a rotation, 2 with a
    translation, 0 neither."""
    rows = [(k, 0.5, -0.25, 0.0), (0.125, k, 0.75, 0.0),
            (-0.5, 0.375, k, 0.0), (0.0, 0.0, 0.0, 1.0)]
    if kind == 2:
        rows[3] = (3.5, -2.0, 0.25, 1.0)
    elif kind == 0:
        rows[2] = (-0.5, 0.375, k, 0.5)
    elif kind == 3:                     # a -0 in w: still code 1
        rows[0] = (k, 0.5, -0.25, -0.0)
    return fl(*[x for r in rows for x in r])


# ============================================================ the scenarios

MODES = (("take", "1|0|0|0"), ("restore", "0|1|0|0"),
         ("checksum", "0|0|1|0"), ("verify", "0|0|0|1"))


def cycle(call, dumps, refill, change=(), name="Replay", timer="1234|56"):
    """Take, restore over other values, checksum, verify the same values,
    then verify after `change`: each mode's snapshot and the objects."""
    out = ["timer|" + timer, "sinit|" + name, "sflags|1|0|0|0"]
    out += call + ["sdump"] + dumps
    out += refill
    out += ["srewind", "sflags|0|1|0|0"] + call + ["sdump"] + dumps
    out += ["sinit|Check", "sflags|0|0|1|0"] + call + ["sdump"] + dumps
    out += ["srewind", "sflags|0|0|0|1"] + call + ["sdump"] + dumps
    if change:
        out += list(change)
        out += ["srewind", "sflags|0|0|0|1"] + call + ["sdump"] + dumps
    out += ["sinit|None", "sflags|0|0|0|0"] + call + ["sdump"] + dumps
    return out


def one(cls, fn, ref, extra=(), keep=(), change=(), seed="a"):
    """A record alone."""
    out = ["# %s %s" % (fn, ref), "new|%s|%s" % (ref, cls)]
    out += fill(ref, cls, seed, keep) + list(extra)
    out += cycle(["call|%s|%s" % (fn, ref)], ["dump|" + ref],
                 fill(ref, cls, seed + "b", keep) + list(extra), change)
    return out


def sc_components():
    out = []
    rec = "vt|rb|_vtable|rec"
    out += one("RigidBody", "rigidbody", "rb", [rec],
               change=["set|rb|State.MotionDampingFactor|" + fl(7.25)])
    # Still: P and L zero, one of them -0, then a moving body.
    still = ["set|rb2|State.P|" + fl(-0.0, -0.0, -0.0, 5.0),
             "set|rb2|State.L|" + fl(-0.0, -0.0, -0.0, -3.0),
             "vt|rb2|_vtable|rec"]
    out += one("RigidBody", "rigidbody", "rb2", still,
               change=["set|rb2|State.L|" + fl(0.0, 0.0, 0.125, 0.0)])
    out += one("Wheel", "wheel", "wh",
               change=["set|wh|LastSign|" + i32(3)])
    out += one("Suspension", "suspension", "su",
               change=["set|su|State.v|" + fl(-1.5)])
    out += one("Engine", "engine", "en",
               change=["set|en|NitroFlag|" + i32(1)])
    # Gears that do and do not fit a byte; Shifting past a bool.
    gears = ["set|dt|DesiredGear|" + i32(5), "set|dt|SportGear|" + i32(-1),
             "set|dt|Shifting|" + i32(2)]
    out += one("DriveTrain", "drivetrain", "dt", gears,
               change=["set|dt|ShiftUpRPM|" + fl(*range(9))])
    out += one("Aerodynamics", "aero", "ae")
    for k, ref in ((1, "ak1"), (2, "ak2"), (0, "ak0"), (3, "ak3")):
        out += one("TwoWheelAckermanSteering", "ackerman", ref,
                   ["set|%s|AckermanMatrix|%s%s" % (ref, mat(k), mat(2)),
                    "vt|%s|base._vtable|Ackerman" % ref],
                   change=["set|%s|AckermanMatrix|%s%s"
                           % (ref, mat(k, 0.5), mat(0))])
    return out


def wheelinfo_lines(ref):
    """The car type's four wheels: positions, radius, width, number, and the
    word at 24 zero."""
    out = []
    for i in range(4):
        x = (-1.0 if i & 1 else 1.0) * 0.875
        y = (1.5 if i < 2 else -1.25)
        data = (fl(x, y, 0.375, 0.34375, 0.25) + i32(i) + i32(0) + i32(0))
        out.append("setb|%s|%d|%s" % (ref, 288 + 32 * i, data))
    out.append("setb|%s|272|%s" % (ref, fl(0.0, 0.125, 0.5, 0.0)))
    return out


def carstate_extra(ref, path=""):
    p = path
    return ["set|%s|%sWheelSuspensionHeight|%s" % (ref, p, fl(0, 0, 0, 0)),
            "set|%s|%sBodyMatrix|%s" % (ref, p, mat(2)),
            "set|%s|%sWheelTouchingGround|%s" % (ref, p, "01ff0200"),
            "set|%s|%sCurrentGear|%s" % (ref, p, i32(4)),
            "set|%s|%sClutchEngaged|%s" % (ref, p, i32(1)),
            # x is 0x3f8000a5: bits in the low nibble, which the snapshot
            # clears, and in the one above it, which it keeps.
            "set|%s|%sPosition|%s" % (ref, p,
                                      "a500803f000000400000c0bf00000000"),
            "link|%s|%spCarInfo|cti|-" % (ref, p)]


def sc_carstate():
    out = ["# carstate", "newb|cti|512"] + wheelinfo_lines("cti")
    keep = ("pCarInfo",)
    out += ["new|cs|CarState"] + fill("cs", "CarState", "a") + \
        carstate_extra("cs")
    out += cycle(["call|carstate|cs"], ["dump|cs"],
                 fill("cs", "CarState", "b") + carstate_extra("cs"),
                 ["set|cs|Odometer|" + fl(99.5)])
    del keep
    # A BodyMatrix of each other code, a gear that does not fit.
    for k in (0, 1):
        ref = "cs%d" % k
        extra = carstate_extra(ref) + [
            "set|%s|BodyMatrix|%s" % (ref, mat(k)),
            "set|%s|CurrentGear|%s" % (ref, i32(300))]
        out += ["new|%s|CarState" % ref] + fill(ref, "CarState", "c") + extra
        out += cycle(["call|carstate|" + ref], ["dump|" + ref],
                     fill(ref, "CarState", "d") + extra)
    return out


def damage_extra(ref, path=""):
    p = path
    return ["set|%s|%sNumBodyDamageModels|%s" % (ref, p, i32(0))]


def sc_damage():
    out = ["# bodydamage", "new|bd|BodyDamage"]
    out += fill("bd", "BodyDamage", "a") + damage_extra("bd")
    out += cycle(["call|bodydamage|bd"], ["dump|bd"],
                 fill("bd", "BodyDamage", "b") + damage_extra("bd"),
                 ["set|bd|CompressedTotalDamage|" + i16(7)])
    # A CarDamage on a car whose render info is recorded; the items' bits
    # the same as applied, and not.
    out += ["# cardamage", "new|dcar|Car", "newb|ri|64",
            "link|dcar|pRenderInfo|ri|-"]
    for k, (items, applied) in enumerate(((0x12345678, 0x12345678),
                                          (0x00c30000, 0x00010203),
                                          (0, 0xffffffff))):
        ref = "cd%d" % k
        extra = damage_extra(ref, "TheBodyDamage.") + [
            "set|%s|BreakableCarItemDamageAmounts|%s" % (ref, i32(items)),
            "set|%s|AppliedBreakableCarItemDamageAmounts|%s"
            % (ref, i32(applied)),
            "link|%s|pCar|dcar|-" % ref]
        out += ["new|%s|CarDamage" % ref] + fill(ref, "CarDamage", "a") + \
            extra
        out += cycle(["call|cardamage|" + ref], ["dump|" + ref],
                     fill(ref, "CarDamage", "b") + extra,
                     ["set|%s|BreakableCarItemDamageAmounts|%s"
                      % (ref, i32(items ^ 0x40))])
    return out


def body_extra(ref, path=""):
    p = path
    return ["set|%s|%sCollisionsDisabled|%s" % (ref, p, i8(3)),
            "set|%s|%sActiveCollisionDetection|%s" % (ref, p, i8(1))]


def sc_bodies():
    out = ["# collisionbody", "new|bod|CollisionBody",
           "vt|bod|_vtable|CollisionBody"]
    out += fill("bod", "CollisionBody", "a") + body_extra("bod")
    out += cycle(["call|collisionbody|bod"], ["dump|bod"],
                 fill("bod", "CollisionBody", "b") + body_extra("bod"),
                 ["set|bod|ID|" + i16(77)])
    # Bits past four in each half.
    out += ["# staticbody", "new|sb|CollisionBody",
            "vt|sb|_vtable|Static"]
    sx = ["set|sb|CollisionsDisabled|" + i8(0x1f),
          "set|sb|ActiveCollisionDetection|" + i8(0x12)]
    out += fill("sb", "CollisionBody", "c") + sx
    out += cycle(["call|staticbody|sb"], ["dump|sb"],
                 fill("sb", "CollisionBody", "d"),
                 ["set|sb|Type|" + i8(9)])
    out += ["# trackpolygon", "new|tp|TrackPolygonCollisionBody",
            "vt|tp|Static.Body._vtable|TrackPolygon"]
    out += fill("tp", "TrackPolygonCollisionBody", "a") + \
        body_extra("tp", "Static.Body.")
    out += cycle(["call|trackpolygon|tp"], ["dump|tp"],
                 fill("tp", "TrackPolygonCollisionBody", "b"),
                 ["set|tp|Static.Body.BBoxMax|" + fl(1.0, 2.0)])
    out += ["# dynamic", "new|dy|DynamicCollisionBody", "newb|tc|64",
            "vt|dy|Body._vtable|Dynamic", "link|dy|pTC|tc|-"]
    out += fill("dy", "DynamicCollisionBody", "a") + \
        body_extra("dy", "Body.")
    out += cycle(["call|dynamic|dy"], ["dump|dy"],
                 fill("dy", "DynamicCollisionBody", "b"),
                 ["set|dy|CylinderRadius|" + fl(4.5)])
    return out


def sc_witness():
    out = ["# vcwitness: polyhedra with features",
           "new|poly|VCPolyhedron|2",
           "new|vx|VCVertex|4", "new|ed|VCEdge|5", "new|fa|VCFace|3",
           "new|vx2|VCVertex|2", "new|ed2|VCEdge|2", "new|fa2|VCFace|4"]
    for ref, n, t in (("vx", 4, 0), ("ed", 5, 1), ("fa", 3, 2),
                      ("vx2", 2, 0), ("ed2", 2, 1), ("fa2", 4, 2)):
        for i in range(n):
            out.append("set|%s[%d]|Feature.Type|%s" % (ref, i, i8(t)))
            out.append("set|%s[%d]|Feature.NumPlanes|%s" % (ref, i, i8(i)))
    for i, (v, e, f) in enumerate((("vx", "ed", "fa"),
                                   ("vx2", "ed2", "fa2"))):
        out += ["link|poly[%d]|pVertices|%s|-" % (i, v),
                "link|poly[%d]|pEdges|%s|-" % (i, e),
                "link|poly[%d]|pFaces|%s|-" % (i, f)]
    feats = [("vx[2]", "fa2[3]"), ("ed[4]", "vx2[1]"), ("fa[1]", "ed2[0]"),
             ("0", "fa2[0]"), ("vx[0]", "0")]
    for k, (f1, f2) in enumerate(feats):
        ref = "vw%d" % k
        links = ["link|%s|P1|poly[0]|-" % ref, "link|%s|P2|poly[1]|-" % ref,
                 "link|%s|F1|%s|%s" % (ref, f1, "-" if f1 != "0" else "-"),
                 "link|%s|F2|%s|-" % (ref, f2)]
        other = ["link|%s|F1|fa[0]|-" % ref, "link|%s|F2|ed2[1]|-" % ref]
        out += ["new|%s|VCWitness" % ref] + fill(ref, "VCWitness", "a") + \
            links
        out += cycle(["call|vcwitness|" + ref], ["dump|" + ref],
                     fill(ref, "VCWitness", "b") + other,
                     ["set|%s|Distance|%s" % (ref, fl(0.5))])
    # The CollisionBodyWitness: without a Collision; with one; a restore
    # that makes one; a restore that finds none over one.
    out += ["# cbwitness", "new|b1|CollisionBody", "new|b2|CollisionBody",
            "set|b1|NumCollisions|" + i8(3), "set|b2|NumCollisions|" + i8(127),
            "stats|5|5"]
    for k, has in enumerate((False, True)):
        ref = "w%d" % k
        links = ["link|%s|Witness.P1|poly[0]|-" % ref,
                 "link|%s|Witness.P2|poly[1]|-" % ref,
                 "link|%s|Witness.F1|ed[1]|-" % ref,
                 "link|%s|Witness.F2|fa2[2]|-" % ref,
                 "link|%s|pBody1|b1|-" % ref, "link|%s|pBody2|b2|-" % ref]
        coll = []
        if has:
            coll = ["new|co%d|Collision" % k] + fill("co%d" % k, "Collision",
                                                     "a") + \
                ["link|%s|pCollision|co%d|-" % (ref, k)]
        out += ["new|%s|CollisionBodyWitness" % ref] + \
            fill(ref, "CollisionBodyWitness", "a") + links + coll
        # Restore over no Collision: the restore makes a new one.
        refill = fill(ref, "CollisionBodyWitness", "b") + links + \
            ["link|%s|pCollision|0|-" % ref]
        out += cycle(["call|cbwitness|" + ref],
                     ["dump|" + ref, "dumpn", "dumpg"], refill)
    out += ["# collision", "new|cl|Collision"] + fill("cl", "Collision", "a")
    out += cycle(["call|collision|cl"], ["dump|cl"],
                 fill("cl", "Collision", "b"),
                 ["set|cl|TotalImpulseMagnitude|" + fl(2.0)])
    return out


def sc_trackpath():
    out = ["# trackpath", "new|tpp|TrackPathPoint|6"]
    for i in range(6):
        out += fill("tpp[%d]" % i, "TrackPathPoint", "a")
    out += ["tpm|tpp"]
    for k, pt in enumerate(("tpp[3]", "0", "tpp[0]", "tpp[5]")):
        ref = "tc%d" % k
        lk = ["link|%s|pTrackPoint|%s|-" % (ref, pt)]
        out += ["new|%s|TrackPathCoordinate" % ref] + \
            fill(ref, "TrackPathCoordinate", "a") + lk
        out += cycle(["call|tpcoord|" + ref], ["dump|" + ref],
                     fill(ref, "TrackPathCoordinate", "b") +
                     ["link|%s|pTrackPoint|tpp[1]|-" % ref],
                     ["link|%s|pTrackPoint|tpp[2]|-" % ref])
    # Points before the manager's first: -2 taken, -1 put back by the
    # refill, both NULL on the way back.
    out += ["tpm|tpp[2]", "new|tc4|TrackPathCoordinate"] + \
        fill("tc4", "TrackPathCoordinate", "a") + \
        ["link|tc4|pTrackPoint|tpp[0]|-"]
    out += cycle(["call|tpcoord|tc4"], ["dump|tc4"],
                 ["link|tc4|pTrackPoint|tpp[1]|-"])
    return out


def sc_controller():
    out = ["# carcontroller", "newb|drv|4096", "new|ctl|CarController",
           "drvvt|drv|rec", "link|ctl|Driver|drv|-",
           "vt|ctl|_vtable|rec"]
    out += cycle(["call|carcontroller|ctl"], ["dump|ctl"], [])
    return out


def physicscar(pfx, car=None, seed="a"):
    """A PhysicsCar `pfx` and its components; with `car`, its car and the
    car's state."""
    p = pfx
    out = ["new|%s|PhysicsCar" % p, "new|%srb|RigidBody" % p,
           "new|%sak|TwoWheelAckermanSteering" % p,
           "new|%swh|Wheel|4" % p, "new|%ssu|Suspension|4" % p,
           "new|%sen|Engine" % p, "new|%sdt|DriveTrain" % p,
           "new|%sae|Aerodynamics" % p]
    out += physicscar_fill(pfx, seed)
    out += ["vt|%s|Mover._vtable|PhysicsCar" % p,
            "vt|%s|Vehicle._vtable|PhysicsCarVehicle" % p,
            "vt|%srb|_vtable|rec" % p,
            "vt|%sak|base._vtable|Ackerman" % p,
            "link|%s|pBody|%srb|-" % (p, p),
            "link|%s|pSteering|%sak|-" % (p, p),
            "link|%s|pEngine|%sen|-" % (p, p),
            "link|%s|pDriveTrain|%sdt|-" % (p, p),
            "link|%s|pAerodynamics|%sae|-" % (p, p)]
    for i in range(4):
        out += ["link|%s|pWheel[%d]|%swh[%d]|-" % (p, i, p, i),
                "link|%s|pSuspension[%d]|%ssu[%d]|-" % (p, i, p, i)]
    if car:
        out += ["link|%s|pCar|%s|-" % (p, car),
                "link|%s|State|%s|State" % (p, car)]
    return out


def physicscar_fill(p, seed):
    out = fill(p, "PhysicsCar", seed)
    out += fill(p + "rb", "RigidBody", seed)
    out += fill(p + "ak", "TwoWheelAckermanSteering", seed)
    out += ["set|%sak|AckermanMatrix|%s%s" % (p, mat(1), mat(2))]
    for i in range(4):
        out += fill("%swh[%d]" % (p, i), "Wheel", seed)
        out += fill("%ssu[%d]" % (p, i), "Suspension", seed)
    out += fill(p + "en", "Engine", seed)
    out += fill(p + "dt", "DriveTrain", seed)
    out += fill(p + "ae", "Aerodynamics", seed)
    return out


def physicscar_dumps(p):
    out = ["dump|" + p, "dump|%srb" % p, "dump|%sak" % p, "dump|%swh" % p,
           "dump|%ssu" % p, "dump|%sen" % p, "dump|%sdt" % p,
           "dump|%sae" % p]
    return out


def sc_physicscar():
    out = ["# physicscar"] + physicscar("pc")
    out += cycle(["call|physicscar|pc"], physicscar_dumps("pc"),
                 physicscar_fill("pc", "b"),
                 ["set|pcwh[2]|State.w|" + fl(12.5)])
    out += ["# carmover"]
    out += cycle(["call|carmover|pc"], ["dump|pc"], [])
    return out


def car_fixed(c, mode=1, anim=True, skin=None, physics=True):
    """The car's links and the fields its callees read; without `physics`,
    the collision body's physics pointers NULL."""
    out = ["link|%s|pRideInfo|%sride|-" % (c, c),
           "link|%s|pCarController|%sctl|-" % (c, c),
           "link|%s|pCarMover|%spc|-" % (c, c),
           "link|%s|pDynamicCollisionBody|%sccb|-" % (c, c),
           "link|%s|pCarDamage|%scd|-" % (c, c),
           "link|%s|pRenderInfo|%sri|-" % (c, c),
           "link|%s|pAnimatedDriver|%s|-" % (c, ("%sad" % c) if anim
                                              else "0"),
           "set|%s|TheMovementMode|%s" % (c, i32(mode)),
           "set|%s|TheControlMode|%s" % (c, i32(2)),
           "link|%sccb|pCar|%s|-" % (c, c),
           "set|%sccb|Dynamic.PhysicsMode|%s" % (c, i32(1)),
           "set|%sccb|Dynamic.CylinderRadius|%s" % (c, fl(2.5)),
           "link|%sccb|Dynamic.pTC|%stc|-" % (c, c),
           # What setup_physics_pointers makes, which only a restore runs.
           "link|%sccb|Dynamic.pSystem|%s" % (c, ("%spc|Vehicle" % c)
                                               if physics else "0"),
           "link|%sccb|Dynamic.pBody|%s" % (c, ("%spcrb|-" % c)
                                             if physics else "0"),
           "link|%scd|pCar|%s|-" % (c, c),
           "vt|%sctl|_vtable|rec" % c]
    out += carstate_extra(c, "State.")
    out += damage_extra("%scd" % c, "TheBodyDamage.")
    out += body_extra("%sccb" % c, "Dynamic.Body.")
    if skin is not None:
        out += ["set|%sride|SkinNumber|%s" % (c, i8(skin))]
    return out


def car_fill(c, seed):
    out = fill(c, "Car", seed)
    out += fill(c + "ride", "RideInfo", seed)
    out += fill(c + "ccb", "CarCollisionBody", seed)
    out += fill(c + "cd", "CarDamage", seed)
    out += physicscar_fill(c + "pc", seed)
    return out


def car_dumps(c):
    return (["dump|" + c, "dump|%sride" % c, "dump|%sccb" % c,
             "dump|%scd" % c] + physicscar_dumps(c + "pc") +
            ["dumpg"])


def sc_car():
    out = []
    for c, anim, skins, idx in (("ca", True, (3, 3), (5, 2)),
                                ("cb", False, (1, -2), (-7, 300)),
                                ("cc", True, (0, 9), (12, 0))):
        out += ["# car " + c, "new|%s|Car" % c, "new|%sride|RideInfo" % c,
                "new|%sctl|CarController" % c,
                "new|%sccb|CarCollisionBody" % c, "new|%scd|CarDamage" % c,
                "newb|%sri|64" % c, "newb|%sad|64" % c, "newb|%stc|64" % c]
        out += physicscar(c + "pc", c)
        out += ["vt|%sccb|Dynamic.Body._vtable|CarCollisionBody" % c,
                "cblist|%sccb" % c, "maxw|" + fl(1.0)]
        ids = ["set|%s|CarIndex|%s" % (c, i16(idx[0])),
               "set|%s|DriverNumber|%s" % (c, i16(idx[1]))]
        out += car_fill(c, "a") + car_fixed(c, anim=anim, skin=skins[0]) + ids
        refill = car_fill(c, "b") + \
            car_fixed(c, anim=anim, skin=skins[1], physics=False) + ids
        out += cycle(["call|car|" + c], car_dumps(c), refill,
                     ["set|%s|OldSpeed|%s" % (c, fl(-4.0))])
    # A disc replay's cars (TASKS 72h-2b): retail's with its driver, run
    # for real, against the port's with none and the stand-in's section; a
    # traffic car, which has no driver in retail either; and the flag off.
    for c, usage, flag, idx in (("cd", 0, 1, (2, 1)), ("ce", 2, 1, (6, 4)),
                                ("cf", 1, 0, (3, 7))):
        out += ["# car %s usage %d flag %d" % (c, usage, flag),
                "new|%s|Car" % c, "new|%sride|RideInfo" % c,
                "new|%sctl|CarController" % c,
                "new|%sccb|CarCollisionBody" % c, "new|%scd|CarDamage" % c,
                "newb|%sri|64" % c, "newb|%sad|144" % c,
                "newb|%stc|64" % c, "newb|%sti|2048" % c]
        out += physicscar(c + "pc", c)
        out += ["vt|%sccb|Dynamic.Body._vtable|CarCollisionBody" % c,
                "cblist|%sccb" % c, "maxw|" + fl(1.0)]
        ids = ["set|%s|CarIndex|%s" % (c, i16(idx[0])),
               "set|%s|DriverNumber|%s" % (c, i16(idx[1])),
               "link|%s|pCarTypeInfo|%sti|-" % (c, c),
               "usage|%sti|%d" % (c, usage),
               "rdriver|%s|%sad|%d" % (c, c, flag)]
        out += car_fill(c, "a") + car_fixed(c, anim=False, skin=2) + ids
        refill = car_fill(c, "b") + \
            car_fixed(c, anim=False, skin=4, physics=False) + ids
        out += cycle(["call|car|" + c], car_dumps(c), refill,
                     ["set|%s|OldSpeed|%s" % (c, fl(9.5))])
    return out


def script():
    return (sc_components() + sc_carstate() + sc_damage() + sc_bodies() +
            sc_witness() + sc_trackpath() + sc_controller() +
            sc_physicscar() + sc_car())


# =================================================================== model

# The retail functions each `call` names.
FNS = {
    "rigidbody": 0x0019ca70, "wheel": 0x001a3f60, "suspension": 0x001a5ed0,
    "engine": 0x0018a8e8, "drivetrain": 0x0018af10, "aero": 0x001add48,
    "ackerman": 0x001a5d10, "physicscar": 0x00137450,
    "carmover": 0x001309f0, "carstate": 0x001c0270,
    "bodydamage": 0x001b4c58, "cardamage": 0x001b5638,
    "collisionbody": 0x001d6a98, "staticbody": 0x001d8760,
    "trackpolygon": 0x001d8918, "dynamic": 0x001d7050,
    "carcollisionbody": 0x001d8058, "cbwitness": 0x001d6168,
    "vcwitness": 0x001d0948, "collision": 0x0021e760,
    "tpcoord": 0x00208768, "carcontroller": 0x001c00d0, "car": 0x00130ff0,
}

# Retail's tables; CarCollisionBody's has no symbol and is made from
# Dynamic's.
VT_RETAIL = {
    "Ackerman": 0x002b5d18, "PhysicsCar": 0x002aeac8,
    "PhysicsCarVehicle": 0x002aeaa8, "CollisionBody": 0x002b8ae8,
    "Static": 0x002b8a18, "TrackPolygon": 0x002b8948,
    "Dynamic": 0x002b8878,
}
VT_CARBODY_DO_SNAPSHOT = 0x001d8058
VT_CARBODY_GET_POSITION = 0x001d8f30

COLLISION_BODY_LIST = 0x00331370
MAX_WIDTH = 0x00331378
COLLISION_STATS = 0x00319e90
TRACK_PATH_MANAGER = 0x0031bc38

S_CLEAR_BBOX = 0x00151cd0
S_SET_CONTROL = 0x00131410
S_SET_MOVEMENT = 0x00131618
S_SWITCH_SKIN = 0x0011e588
S_REPLACE_TEX = (0x0011ff60, 0x0011ff68)
S_ANIM_DRIVER = 0x001a9770
S_CANCEL_ANIMATIONS = 0x001a9b30
# CarTypeInfo's UsageType, which Car::AssignAnimatedDriver (0x001334a8)
# tests: traffic (2) gets no driver.
CARTYPEINFO_USAGE = 1336
CAR_ANIMATED_DRIVER = 1204
S_OMALLOC = 0x00257c80
S_COLLISION_CTOR = 0x0021e620
COLLISION_SIZE = 112


class Obj(object):
    def __init__(self, oid, base, cls, n, stride, size):
        self.id, self.base, self.cls, self.n, self.stride, self.size = (
            oid, base, cls, n, stride, size)


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.breaks = 0
        self.objs = []
        self.byid = {}
        self.names = {}
        self.ncoll = 0
        self.S = e.alloc(SNAP_SIZE, align=16)
        e.write(self.S, bytes(SNAP_SIZE))
        e.put32(WORLD_TIMER, 0)
        e.put32(WORLD_LOOP, 0)
        e.stub(S_BBREAK, self.bbreak)
        self.vt = dict(VT_RETAIL)
        # The recording table: 32 slots, each its own stub.
        rec = e.alloc(32 * 8, align=16)
        for k in range(1, 32):
            fn = e.alloc(8, align=8)
            e.write(rec + 8 * k, b"\0\0\0\0" + struct.pack("<I", fn))
            e.stub(fn, self.recorder(8 * k))
        self.vt["rec"] = rec
        car = e.alloc(208, align=16)
        e.write(car, e.read(VT_RETAIL["Dynamic"], 208))
        e.put32(car + 16 + 4, VT_CARBODY_DO_SNAPSHOT)
        e.put32(car + 24 + 4, VT_CARBODY_GET_POSITION)
        e.write(car + 16, b"\0\0\0\0")
        e.write(car + 24, b"\0\0\0\0")
        self.vt["CarCollisionBody"] = car
        self.vtname = {v: k for k, v in self.vt.items()}
        e.stub(S_CLEAR_BBOX, lambda em: self.log1("clearbbox"))
        e.stub(S_SET_CONTROL, lambda em: self.log2("setcontrol"))
        e.stub(S_SET_MOVEMENT, lambda em: self.log2("setmovement"))
        e.stub(S_SWITCH_SKIN, lambda em: self.log2("switchskin"))
        for a in S_REPLACE_TEX:
            e.stub(a, lambda em: self.log1("replacetex"))
        e.stub(S_ANIM_DRIVER, self.animdriver)
        # A real driver's restore cancels its animations; it has none, and
        # the port's stand-in has nothing to cancel.
        e.stub(S_CANCEL_ANIMATIONS, lambda em: 0)
        self.real_drivers = {}
        e.stub(S_OMALLOC, self.omalloc)
        e.stub(S_COLLISION_CTOR, self.collision_ctor)
        self.register("cblist", COLLISION_BODY_LIST, None, 1, 8, 8)

    # ---- the stubs

    def emit(self, s):
        self.out.append(s)

    def bbreak(self, em):
        self.breaks += 1
        return 0

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def log1(self, what):
        self.emit("%s %s" % (what, self.label(self.arg(0))))
        return 0

    def log2(self, what):
        self.emit("%s %s %d" % (what, self.label(self.arg(0)),
                                s32(self.arg(1))))
        return 0

    def snaparg(self, a):
        return "snap" if a == self.S else "?"

    def where(self):
        e, S = self.e, self.S
        d = s32(e.mem[S + 64] << 24) >> 24
        if d < 0:
            return "depth=%d top=-" % d
        p = e.u32(S + 76 + 16 * d)
        # Live, so a name in the caller's frame is still there to read.
        return "depth=%d top=%s" % (d, self.cstr(p, live=True) if p else "-")

    def recorder(self, slot):
        def fn(em):
            line = "rec vt%d this=%s" % (slot, self.label(self.arg(0)))
            if slot in (16, 24):
                line += " s=" + self.snaparg(self.arg(1))
            self.emit(line + " " + self.where())
            return 0
        return fn

    def animdriver(self, em):
        if self.arg(0) in self.real_drivers.values():
            return self.real_animdriver()
        self.emit("animdriver %s s=%s %s" % (self.label(self.arg(0)),
                                             self.snaparg(self.arg(1)),
                                             self.where()))
        return 0

    def real_animdriver(self):
        """Retail's AnimatedDriver::DoSnapshot itself, run under its stub:
        the call's ra, and the outer run's count, kept."""
        e = self.e
        ra, limit, icount = e.reg[31], e.limit, e.icount
        stub = e.stubs.pop(S_ANIM_DRIVER)
        try:
            e.call(S_ANIM_DRIVER, self.arg(0), self.arg(1), limit=LIMIT)
        finally:
            e.stubs[S_ANIM_DRIVER] = stub
        e.reg[31], e.limit, e.icount = ra, limit, icount
        return None

    def omalloc(self, em):
        a = self.e.alloc(COLLISION_SIZE, align=16)
        self.e.write(a, bytes(COLLISION_SIZE))
        self.register("N%d" % self.ncoll, a, "Collision", 1, COLLISION_SIZE,
                      COLLISION_SIZE)
        self.ncoll += 1
        return a

    def collision_ctor(self, em):
        self.emit("newcollision w=%s pt=%s" % (self.label(self.arg(1)),
                                               self.label(self.arg(2))))
        return self.arg(0)

    # ---- objects

    def register(self, oid, base, cls, n, stride, size):
        assert oid not in self.byid, "object made twice: " + oid
        o = Obj(oid, base, cls, n, stride, size)
        self.objs.append(o)
        self.byid[oid] = o

    def ref(self, r):
        """`id` or `id[i]`: the object and the element's address."""
        m = re.match(r"^(\w+)(?:\[(\d+)\])?$", r)
        o = self.byid[m.group(1)]
        i = int(m.group(2)) if m.group(2) else 0
        assert i < o.n, r
        return o, o.base + i * o.stride

    def field(self, cls, path):
        for f in flatten(cls):
            if f.path == path:
                return f
        raise KeyError("%s.%s" % (cls, path))

    def label(self, p):
        p &= M32
        if p == 0:
            return "0"
        if p == self.S:
            return "snap"
        for o in self.objs:
            if o.base <= p < o.base + o.size:
                off = p - o.base
                i, k = off // o.stride, off % o.stride
                name = o.id + ("[%d]" % i if o.n > 1 else "")
                if k == 0:
                    return name
                if o.cls:
                    for f in flatten(o.cls):
                        if f.roff <= k < f.roff + f.size:
                            return "%s.%s%s" % (
                                name, f.path,
                                "+%d" % (k - f.roff) if k != f.roff else "")
                return "%s+%d" % (name, k)
        return "?"

    def cstr(self, a, n=64, live=False):
        sp = self.e.reg[29] & M32
        if not live and sp - 0x40000 <= a < sp + 0x1000:
            return "<stack>"
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def name(self, s):
        if s not in self.names:
            a = self.e.alloc(len(s) + 1, align=4)
            self.e.write(a, s.encode("latin-1") + b"\0")
            self.names[s] = a
        return self.names[s]

    # ---- dumps

    def dump_obj(self, oid):
        o = self.byid[oid]
        e = self.e
        for i in range(o.n):
            base = o.base + i * o.stride
            name = o.id + ("[%d]" % i if o.n > 1 else "")
            if not o.cls:
                self.emit("%s = %s" % (name, e.read(base, o.stride).hex()))
                continue
            for f in flatten(o.cls):
                a = base + f.roff
                if f.kind == "raw":
                    self.emit("%s.%s = %s" % (name, f.path,
                                              e.read(a, f.size).hex()))
                elif f.kind == "ptr":
                    self.emit("%s.%s -> %s" % (name, f.path,
                                               self.label(e.u32(a))))
                else:
                    v = e.u32(a)
                    self.emit("%s.%s = vt:%s" % (
                        name, f.path, self.vtname.get(v, "%08x" % v)))

    def sdump(self):
        e, S = self.e, self.S
        g = lambda o: s32(e.u32(S + o))
        b = lambda o: s32(e.mem[S + o] << 24) >> 24
        nm = e.read(S + 8, 32).split(b"\0")[0].decode("latin-1")
        self.emit("snap name=%s t=%d et=%d blt=%d elt=%d flags=%d,%d,%d,%d "
                  "depth=%d ovf=%d secnum=%u pd=%d tiv=%08x pos=%d size=%d "
                  "breaks=%d" % (
                      nm, g(40), g(44), g(48), g(52), b(60), b(61), b(62),
                      b(63), b(64), b(65), e.u16(S + 66), g(68),
                      e.u32(S + 332), g(336), g(340), self.breaks))
        for i in range(16):
            a = S + 76 + 16 * i
            p = e.u32(a)
            if not p and not e.u32(a + 4) and not e.u32(a + 8) \
                    and not e.u32(a + 12):
                continue
            self.emit("sec %d name=%s obj=%s num=%u nmd=%u err=%d size=%d"
                      % (i, self.cstr(p) if p else "-",
                         self.label(e.u32(a + 4)), e.u16(a + 8),
                         e.mem[a + 10], s32(e.mem[a + 11] << 24) >> 24,
                         s32(e.u32(a + 12))))
        n = max(0, min(max(g(336), g(340)), 4096))
        data = e.read(S + DATA, DATA_SIZE)
        self.emit("data fnv=%08x" % fnv(data))
        for k in range(0, n, 64):
            self.emit("d %d %s" % (k, data[k:min(n, k + 64)].hex()))

    def dumpg(self):
        e = self.e
        self.emit("globals stats=%d,%d maxw=%08x cblist=%s,%s" % (
            s32(e.u32(COLLISION_STATS + 4)), s32(e.u32(COLLISION_STATS + 40)),
            e.u32(MAX_WIDTH), self.label(e.u32(COLLISION_BODY_LIST)),
            self.label(e.u32(COLLISION_BODY_LIST + 4))))

    # ---- the script

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "new":
            cls = a[2]
            n = int(a[3]) if len(a) > 3 else 1
            stride = alloc_size(cls)
            base = e.alloc(stride * n, align=16)
            e.write(base, bytes(stride * n))
            self.register(a[1], base, cls, n, stride, stride * n)
        elif o == "newb":
            n = int(a[2])
            base = e.alloc(n, align=16)
            e.write(base, bytes(n))
            self.register(a[1], base, None, 1, n, n)
        elif o == "set":
            ob, at = self.ref(a[1])
            f = self.field(ob.cls, a[2])
            data = bytes.fromhex(a[3])
            assert len(data) == f.size, (a, f.size)
            e.write(at + f.roff, data)
        elif o == "setb":
            ob, at = self.ref(a[1])
            e.write(at + int(a[2]), bytes.fromhex(a[3]))
        elif o == "drvvt":
            # CarDriver's vptr, at 556.
            ob, at = self.ref(a[1])
            e.put32(at + 556, self.vt[a[2]])
        elif o == "link":
            ob, at = self.ref(a[1])
            f = self.field(ob.cls, a[2])
            assert f.kind == "ptr", a
            if a[3] == "0":
                v = 0
            else:
                ob2, at2 = self.ref(a[3])
                v = at2 if a[4] == "-" else at2 + path_off(ob2.cls, a[4])
            e.put32(at + f.roff, v)
        elif o == "vt":
            ob, at = self.ref(a[1])
            f = self.field(ob.cls, a[2])
            assert f.kind == "vptr", a
            e.put32(at + f.roff, self.vt[a[3]])
        elif o == "cblist":
            ob, at = self.ref(a[1])
            e.put32(COLLISION_BODY_LIST, at)
            e.put32(COLLISION_BODY_LIST + 4, at)
            e.put32(at, COLLISION_BODY_LIST)
            e.put32(at + 4, COLLISION_BODY_LIST)
        elif o == "tpm":
            ob, at = self.ref(a[1])
            e.put32(TRACK_PATH_MANAGER + 20, at)
        elif o == "stats":
            e.put32(COLLISION_STATS + 4, int(a[1]))
            e.put32(COLLISION_STATS + 40, int(a[2]))
        elif o == "maxw":
            e.write(MAX_WIDTH, bytes.fromhex(a[1]))
        elif o == "timer":
            e.put32(WORLD_TIMER, int(a[1]))
            e.put32(WORLD_LOOP, int(a[2]))
        elif o == "sinit":
            self.call(F_INIT, S, self.name(a[1]))
        elif o == "sflags":
            for k in range(4):
                e.mem[S + 60 + k] = int(a[1 + k]) & 0xff
        elif o == "srewind":
            e.put32(S + 340, e.u32(S + 336))
            e.put32(S + 336, 0)
        elif o == "sdump":
            self.sdump()
        elif o == "call":
            ob, at = self.ref(a[2])
            # The real driver for the call alone, so the dumps show the
            # port's car, which has none.
            drv = self.real_drivers.get(at) if a[1] == "car" else None
            if drv is not None:
                e.put32(at + CAR_ANIMATED_DRIVER, drv)
            self.call(FNS[a[1]], at, S)
            if drv is not None:
                e.put32(at + CAR_ANIMATED_DRIVER, 0)
        elif o == "dump":
            self.dump_obj(a[1])
        elif o == "dumpn":
            for ob in self.objs:
                if re.match(r"^N\d+$", ob.id):
                    self.dump_obj(ob.id)
        elif o == "dumpg":
            self.dumpg()
        elif o == "usage":
            ob, at = self.ref(a[1])
            e.put32(at + CARTYPEINFO_USAGE, int(a[2]))
        elif o == "rdriver":
            # Retail's car has the driver the port's has not: one for each
            # car but traffic, while the port's flag says a disc replay.
            ob, at = self.ref(a[1])
            ob2, drv = self.ref(a[2])
            usage = s32(e.u32(e.u32(at + 12) + CARTYPEINFO_USAGE))
            if int(a[3]) and usage != 2:
                self.real_drivers[at] = drv
            else:
                self.real_drivers.pop(at, None)
        else:
            raise ValueError(o)

    def call(self, f, *args):
        return self.e.call(f, *[s32(x & M32) for x in args], limit=LIMIT)

    def run(self, lines):
        e = self.e
        for line in lines:
            if line.startswith("#"):
                self.emit(line)
                continue
            self.emit("> " + line)
            sp = e.reg[29]
            top = sp & M32
            e.mem[top - 0x4000:top] = bytes(0x4000)
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def fnv(data):
    h = 0x811c9dc5
    for c in data:
        h = ((h ^ c) * 0x01000193) & M32
    return h


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ============================================================ the harness

def c_fields():
    """The generated head of the harness: every class's field table, the
    raw fields' sizes asserted."""
    g = ["// Generated by tools/carsnap_check.py. Do not edit.",
         "#define CS_GENERATED 1", ""]
    w = g.append
    for cls in CLASSES:
        rows = []
        for f in flatten(cls):
            k = {"raw": "R", "ptr": "P", "vptr": "V"}[f.kind]
            if f.kind == "raw":
                w('_Static_assert(sizeof(((%s *)0)->%s) == %d, '
                  '"%s.%s");' % (cls, f.path, f.size, cls, f.path))
            rows.append('    {"%s", offsetof(%s, %s), sizeof(((%s *)0)->%s), '
                        "'%s'}," % (f.path, cls, f.path, cls, f.path, k))
        w("static const CsField csf_%s[] = {" % cls)
        g.extend(rows)
        w("};")
    w("static const CsClass cs_classes[] = {")
    for cls in CLASSES:
        w('    {"%s", sizeof(%s), csf_%s, (int)(sizeof csf_%s / '
          'sizeof csf_%s[0])},' % (cls, cls, cls, cls, cls))
    w("};")
    w("#define CS_NCLASSES %d" % len(CLASSES))
    w("")
    return NL.join(g) + NL


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "carsnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d):
    return [str(harness_source(d))] + PORT


def build_harness(tmp, name="carsnap_test"):
    return hostbuild.build(tmp, sources(tmp), name=name)


def run_harness(exe, sc_path, out_path, timeout=120):
    rc = mutpar.run_exe([exe, sc_path], out_path, timeout)
    if rc == mutpar.HUNG:
        print("harness hung, killed after %d s" % timeout)
    elif rc != 0:
        print("harness exited %d" % rc)
    return rc


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_bytes((NL.join(lines) + NL).encode("latin-1"))
    return sc


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


MUTATIONS = [
    # -- the components ---------------------------------------------------
    M("rb-still-never", "rigidbody.c",
      "        still = 1;", "        still = 0;"),
    M("rb-w-zero", "rigidbody.c",
      "        st->R.v3.w = 1.0f;", "        st->R.v3.w = 0.0f;"),
    M("rb-damping-off", "rigidbody.c",
      "        rb->MotionDamping = 1;", "        rb->MotionDamping = 0;"),
    M("rb-still-p-kept", "rigidbody.c",
      "        st->P.x = 0.0f;", "        st->P.x = st->P.x;"),
    M("rb-no-auxiliaries", "rigidbody.c",
      "        ((PhysicsVoidFn)e->fn)(vt_this(rb, e));\n    }\n"
      "    ReplaySnapshot_EndNamedSection(s);",
      "        (void)e;\n    }\n    ReplaySnapshot_EndNamedSection(s);"),
    M("rb-damping-factor", "rigidbody.c",
      "    ReplaySnapshot_MoveFloat(s, &st->MotionDampingFactor);\n", ""),
    M("wh-lastsign-byte", "wheel.c",
      "    ReplaySnapshot_MoveInt(s, &w->LastSign, 4);",
      "    ReplaySnapshot_MoveInt(s, &w->LastSign, 1);"),
    M("wh-a-w-swapped", "wheel.c",
      "    ReplaySnapshot_MoveFloat(s, &w->State.a);\n"
      "    ReplaySnapshot_MoveFloat(s, &w->State.w);",
      "    ReplaySnapshot_MoveFloat(s, &w->State.w);\n"
      "    ReplaySnapshot_MoveFloat(s, &w->State.a);"),
    M("wh-traction-boost-one", "wheel.c",
      "        w->TractionBoost = 0.0f;\n        w->CatchupFrictionMultiplier",
      "        w->TractionBoost = 1.0f;\n        w->CatchupFrictionMultiplier"),
    M("wh-damage-kept", "wheel.c",
      "        w->Damage = 0.0f;\n    }\n\n    ReplaySnapshot_EndNamedSection",
      "    }\n\n    ReplaySnapshot_EndNamedSection"),
    M("su-z-v-swapped", "suspension.c",
      "    ReplaySnapshot_MoveFloat(snap, &s->State.z);\n"
      "    ReplaySnapshot_MoveFloat(snap, &s->State.v);",
      "    ReplaySnapshot_MoveFloat(snap, &s->State.v);\n"
      "    ReplaySnapshot_MoveFloat(snap, &s->State.z);"),
    M("su-force-kept", "suspension.c",
      "        s->Force = 0.0f;\n        memset(&s->Position",
      "        memset(&s->Position"),
    M("su-touching", "suspension.c",
      "        s->TouchingGround = 0;\n        s->GroundForce = 0.0f;\n    }\n"
      "    ReplaySnapshot_EndNamedSection(snap);",
      "        s->TouchingGround = 1;\n        s->GroundForce = 0.0f;\n    }\n"
      "    ReplaySnapshot_EndNamedSection(snap);"),
    M("en-catchup-kept", "engine.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        e->CatchupTorqueMultiplier = 0.0f;",
      "    if (s->RestoringSnapshotFlag)\n"
      "        e->CatchupTorqueMultiplier = 0.0f;"),
    M("en-nitro-int", "engine.c",
      "    ReplaySnapshot_MoveBool(s, &e->NitroFlag, 1);",
      "    ReplaySnapshot_MoveBool(s, &e->NitroFlag, 4);"),
    M("en-throttle-torque-swapped", "engine.c",
      "    ReplaySnapshot_MoveFloat(s, &e->Throttle);\n"
      "    ReplaySnapshot_MoveFloat(s, &e->RoadTorque);",
      "    ReplaySnapshot_MoveFloat(s, &e->RoadTorque);\n"
      "    ReplaySnapshot_MoveFloat(s, &e->Throttle);"),
    M("dt-gear-byte", "drivetrain.c",
      "    ReplaySnapshot_MoveData(s, &d->CurrentGear, 4, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &d->CurrentGear, 1, -1, 0);"),
    M("dt-shifting-byte", "drivetrain.c",
      "    ReplaySnapshot_MoveInt(s, &d->Shifting, 4);",
      "    ReplaySnapshot_MoveInt(s, &d->Shifting, 1);"),
    M("dt-shift-up-second", "drivetrain.c",
      "    ReplaySnapshot_MoveFloat(s, &d->ShiftUpRPM[0]);",
      "    ReplaySnapshot_MoveFloat(s, &d->ShiftUpRPM[1]);"),
    M("dt-clutch-state-gone", "drivetrain.c",
      "    ReplaySnapshot_MoveData(s, &d->CurrentClutchState, 4, -1, 0);\n",
      ""),
    M("ae-restore-only", "aerodynamics.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {\n"
      "        a->GroundEffect = 0.0f;",
      "    if (s->RestoringSnapshotFlag) {\n        a->GroundEffect = 0.0f;"),
    M("ae-boost-kept", "aerodynamics.c",
      "        a->Boost        = 0.0f;\n        a->Throttle", "        a->Throttle"),
    M("ak-second-matrix", "steering.c",
      "    ReplaySnapshot_MoveMatrix(s, &a->AckermanMatrix[0]);",
      "    ReplaySnapshot_MoveMatrix(s, &a->AckermanMatrix[1]);"),

    # -- PhysicsCar -------------------------------------------------------
    M("pc-friction-gone", "physicscar.c",
      "    ReplaySnapshot_MoveFloat(s, &pc->FrictionBoost);\n"
      "    rigidbody_do_snapshot(pc->pBody, s);",
      "    rigidbody_do_snapshot(pc->pBody, s);"),
    M("pc-wheel-after-suspension", "physicscar.c",
      "        wheel_do_snapshot(pc->pWheel[i], s);\n"
      "        suspension_do_snapshot(pc->pSuspension[i], s);",
      "        suspension_do_snapshot(pc->pSuspension[i], s);\n"
      "        wheel_do_snapshot(pc->pWheel[i], s);"),
    M("pc-drivetrain-first", "physicscar.c",
      "    engine_do_snapshot(pc->pEngine, s);\n"
      "    drivetrain_do_snapshot(pc->pDriveTrain, s);",
      "    drivetrain_do_snapshot(pc->pDriveTrain, s);\n"
      "    engine_do_snapshot(pc->pEngine, s);"),
    M("pc-lurchs-byte", "physicscar.c",
      "    ReplaySnapshot_MoveInt(s, &pc->LurchsLeft, 4);",
      "    ReplaySnapshot_MoveInt(s, &pc->LurchsLeft, 1);"),
    M("pc-flipped-gone", "physicscar.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&pc->FlippedTimer.PackedTime);\n",
      ""),
    M("pc-brake-timers-swapped", "physicscar.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&pc->BrakeStandTimer.PackedTime);",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&pc->BrakeStandTimerStart.PackedTime);"),
    M("pc-yaw-gone", "physicscar.c",
      "    ReplaySnapshot_MoveFloat(s, &pc->YawControlMultiplier);\n", ""),

    # -- CarState ---------------------------------------------------------
    M("cs-position-mask-byte", "carstate.c",
      "        bits &= 0xfffffff0u;", "        bits &= 0xffffff00u;"),
    M("cs-position-mask-restore-only", "carstate.c",
      "    if (snap->TakingSnapshotFlag || snap->RestoringSnapshotFlag) {\n"
      "        uint32_t bits;",
      "    if (snap->RestoringSnapshotFlag) {\n        uint32_t bits;"),
    M("cs-zforce-bottomout-swapped", "carstate.c",
      "        ReplaySnapshot_MoveFloat(snap, &s->WheelZForce[i]);\n"
      "        ReplaySnapshot_MoveFloat(snap, &s->WheelBottomOutMagnitude[i]);",
      "        ReplaySnapshot_MoveFloat(snap, &s->WheelBottomOutMagnitude[i]);\n"
      "        ReplaySnapshot_MoveFloat(snap, &s->WheelZForce[i]);"),
    M("cs-crossed-zero", "carstate.c",
      "            s->CrossedWheelTerrain[i] = 1;",
      "            s->CrossedWheelTerrain[i] = 0;"),
    M("cs-skid-left-kept", "carstate.c",
      "        s->SkidLeft = 0.0f;\n", ""),
    M("cs-gear-int", "carstate.c",
      "    ReplaySnapshot_MoveData(snap, &s->CurrentGear, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(snap, &s->CurrentGear, 4, -1, 0);"),
    M("cs-clutch-int", "carstate.c",
      "    ReplaySnapshot_MoveInt(snap, &s->ClutchEngaged, 1);",
      "    ReplaySnapshot_MoveInt(snap, &s->ClutchEngaged, 4);"),
    M("cs-burnout-byte", "carstate.c",
      "    ReplaySnapshot_MoveInt(snap, &s->BurnOutState, 4);",
      "    ReplaySnapshot_MoveInt(snap, &s->BurnOutState, 1);"),
    M("cs-relcoord-kept", "carstate.c",
      "        bIdentity(&s->RelCoordMatrix);\n", ""),
    M("cs-matrix-valid", "carstate.c",
      "        s->MatrixValid = 0;", "        s->MatrixValid = 1;"),
    M("cs-wheels-counted", "carstate.c",
      "            s->nWheelsTouchingGround += s->WheelTouchingGround[i];",
      "            s->nWheelsTouchingGround += 1;"),
    M("cs-no-wheel-matrices", "carstate.c",
      "        carstate_calculate_wheel_matrices(s);\n    }\n"
      "    ReplaySnapshot_EndNamedSection(snap);",
      "    }\n    ReplaySnapshot_EndNamedSection(snap);"),
    M("cs-odometer-gone", "carstate.c",
      "    ReplaySnapshot_MoveFloat(snap, &s->Odometer);\n", ""),

    # -- damage -----------------------------------------------------------
    M("bd-one-zone-short", "cardamage.c",
      "    ReplaySnapshot_MoveData(s, b->CompressedDamageAmounts, BODYDAMAGE_ZONES,\n"
      "                            BODYDAMAGE_ZONES, 0);",
      "    ReplaySnapshot_MoveData(s, b->CompressedDamageAmounts,\n"
      "                            BODYDAMAGE_ZONES - 1, BODYDAMAGE_ZONES, 0);"),
    M("bd-apply-on-take", "cardamage.c",
      "    if (s->RestoringSnapshotFlag)\n        bodydamage_apply_damage(b);",
      "    if (s->TakingSnapshotFlag)\n        bodydamage_apply_damage(b);"),
    M("bd-total-gone", "cardamage.c",
      "    ReplaySnapshot_MoveUShort(s, &b->CompressedTotalDamage, 2);\n", ""),
    M("cd-items-short", "cardamage.c",
      "    ReplaySnapshot_MoveUInt(s, &d->BreakableCarItemDamageAmounts, 4);",
      "    ReplaySnapshot_MoveUInt(s, &d->BreakableCarItemDamageAmounts, 2);"),
    M("cd-no-apply", "cardamage.c",
      "    if (s->RestoringSnapshotFlag)\n        cardamage_apply_damage(d);",
      "    if (0)\n        cardamage_apply_damage(d);"),
    M("cd-body-after-items", "cardamage.c",
      "    bodydamage_do_snapshot(&d->TheBodyDamage, s);\n"
      "    ReplaySnapshot_MoveUInt(s, &d->BreakableCarItemDamageAmounts, 4);",
      "    ReplaySnapshot_MoveUInt(s, &d->BreakableCarItemDamageAmounts, 4);\n"
      "    bodydamage_do_snapshot(&d->TheBodyDamage, s);"),

    # -- the bodies -------------------------------------------------------
    M("cbody-low-three-bits", "collisionbody.c",
      "        b->CollisionsDisabled = (int8_t)(bits & 15);",
      "        b->CollisionsDisabled = (int8_t)(bits & 7);"),
    M("cbody-high-from-three", "collisionbody.c",
      "        b->ActiveCollisionDetection = (int8_t)(bits >> 4);",
      "        b->ActiveCollisionDetection = (int8_t)(bits >> 3);"),
    M("cbody-pack-three", "collisionbody.c",
      "                         + ((uint8_t)b->ActiveCollisionDetection << 4));",
      "                         + ((uint8_t)b->ActiveCollisionDetection << 3));"),
    M("cbody-id-byte", "collisionbody.c",
      "    ReplaySnapshot_VerifyShort(s, &b->ID, 2);",
      "    ReplaySnapshot_VerifyShort(s, &b->ID, 1);"),
    M("cbody-type-gone", "collisionbody.c",
      "    ReplaySnapshot_VerifyChar(s, &b->Type, 1);\n", ""),
    M("tpbody-bbox-min-gone", "collisionbody.c",
      "    collisionbody_do_snapshot(b, s);\n"
      "    ReplaySnapshot_VerifyVector2(s, &b->BBoxMin);\n",
      "    collisionbody_do_snapshot(b, s);\n"),
    M("dyn-mode-int", "collisionbody.c",
      "    ReplaySnapshot_MoveInt(s, &d->PhysicsMode, 1);",
      "    ReplaySnapshot_MoveInt(s, &d->PhysicsMode, 4);"),
    M("dyn-no-clear-bbox", "collisionbody.c",
      "    if (taking)\n        topology_clear_interest_bbox(d->pTC);",
      "    if (0)\n        topology_clear_interest_bbox(d->pTC);"),
    M("dyn-radius-unverified", "collisionbody.c",
      "    ReplaySnapshot_VerifyFloat(s, &d->CylinderRadius);\n", ""),
    M("dyn-backup-time-kept", "collisionbody.c",
      "        d->BackupTime = 0.0f;\n        memset(&d->BackupRotation",
      "        memset(&d->BackupRotation"),
    M("dyn-backup-velocity-kept", "collisionbody.c",
      "        memset(&d->BackupVelocity, 0, sizeof d->BackupVelocity);\n"
      "    }\n    ReplaySnapshot_EndSection(s);",
      "    }\n    ReplaySnapshot_EndSection(s);"),
    M("ccb-car-index", "carcollisionbody.c",
      "    index = (int8_t)c->pCar->DriverNumber;",
      "    index = (int8_t)c->pCar->CarIndex;"),
    M("ccb-no-setup", "carcollisionbody.c",
      "    if (s->RestoringSnapshotFlag)\n"
      "        carcollisionbody_setup_physics_pointers(c);",
      "    if (0)\n        carcollisionbody_setup_physics_pointers(c);"),
    M("ccb-position-restore-only", "carcollisionbody.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        dynamiccollisionbody_update_position(&c->Dynamic);",
      "    if (s->RestoringSnapshotFlag)\n"
      "        dynamiccollisionbody_update_position(&c->Dynamic);"),
    M("ccb-bbox-max-gone", "carcollisionbody.c",
      "    ReplaySnapshot_VerifyVector2(s, &b->BBoxMax);\n", ""),
    M("ccb-collision-time-gone", "carcollisionbody.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastCollisionTime.PackedTime);\n",
      ""),
    M("ccb-times-order", "carcollisionbody.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastCollisionTime.PackedTime);\n"
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastPenetrationTime.PackedTime);\n",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastPenetrationTime.PackedTime);\n"
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastCollisionTime.PackedTime);\n"),

    # -- the witnesses and the Collision ----------------------------------
    M("vcw-not-looked-up", "vclip.c",
      "    if (s->RestoringSnapshotFlag) {\n"
      "        w->F1 = vcpoly_get_feature(w->P1, code1);",
      "    if (0) {\n        w->F1 = vcpoly_get_feature(w->P1, code1);"),
    M("vcw-f2-from-code1", "vclip.c",
      "        w->F2 = vcpoly_get_feature(w->P2, code2);",
      "        w->F2 = vcpoly_get_feature(w->P2, code1);"),
    M("vcw-switch-byte", "vclip.c",
      "    ReplaySnapshot_MoveInt(s, &w->SwitchState, 4);",
      "    ReplaySnapshot_MoveInt(s, &w->SwitchState, 1);"),
    M("vcw-distance-gone", "vclip.c",
      "    ReplaySnapshot_MoveFloat(s, &w->Distance);\n", ""),
    M("vcw-code2-from-p1", "vclip.c",
      "    code2 = vcpoly_get_feature_code(w->P2, w->F2);",
      "    code2 = vcpoly_get_feature_code(w->P1, w->F2);"),
    M("cbw-always-has", "contact.c",
      "    has = w->pCollision != NULL;", "    has = 1;"),
    M("cbw-no-begin", "contact.c",
      "        if (s->RestoringSnapshotFlag)\n"
      "            cbwitness_begin_collision(w, NULL);",
      "        if (0)\n            cbwitness_begin_collision(w, NULL);"),
    M("cbw-witness-after", "contact.c",
      "    vcwitness_do_snapshot(&w->Witness, s);\n"
      "    has = w->pCollision != NULL;\n"
      "    ReplaySnapshot_MoveChar(s, &has, 1);",
      "    has = w->pCollision != NULL;\n"
      "    ReplaySnapshot_MoveChar(s, &has, 1);\n"
      "    vcwitness_do_snapshot(&w->Witness, s);"),
    M("coll-last-contact-gone", "collision.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastContactTime.PackedTime);\n",
      ""),
    M("coll-points-swapped", "collision.c",
      "    ReplaySnapshot_MoveVector3(s, &c->InitialContactPoint);\n"
      "    ReplaySnapshot_MoveVector3(s, &c->CurrentContactPoint);",
      "    ReplaySnapshot_MoveVector3(s, &c->CurrentContactPoint);\n"
      "    ReplaySnapshot_MoveVector3(s, &c->InitialContactPoint);"),
    M("coll-magnitude-gone", "collision.c",
      "    ReplaySnapshot_MoveFloat(s, &c->TotalImpulseMagnitude);\n", ""),

    # -- the track path and the controller --------------------------------
    M("tpm-negative-kept", "trackpath.c",
      "    else if (index < 0)\n        *pp = NULL;",
      "    else if (index < -5)\n        *pp = NULL;"),
    M("tpm-index-byte", "trackpath.c",
      "    ReplaySnapshot_MoveShort(s, &index, 2);",
      "    ReplaySnapshot_MoveShort(s, &index, 1);"),
    M("tpc-spline-ratio-swapped", "trackpath.c",
      "    ReplaySnapshot_MoveFloat(s, &c->SplineParam);\n"
      "    ReplaySnapshot_MoveFloat(s, &c->RatioAroundTrack);",
      "    ReplaySnapshot_MoveFloat(s, &c->RatioAroundTrack);\n"
      "    ReplaySnapshot_MoveFloat(s, &c->SplineParam);"),
    M("tpc-direction-gone", "trackpath.c",
      "    ReplaySnapshot_MoveVector2(s, &c->PathDirection);\n"
      "    ReplaySnapshot_EndNamedSection(s);",
      "    ReplaySnapshot_EndNamedSection(s);"),
    M("ctl-wrong-slot", "carcontroller.c",
      "    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DO_SNAPSHOT);",
      "    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_DO_SNAPSHOT + 8);"),

    # -- the Car ----------------------------------------------------------
    M("car-name-driver", "carsnap.c",
      '    snprintf(name, sizeof name, "Car%d", c->CarIndex);',
      '    snprintf(name, sizeof name, "Car%d", c->DriverNumber);'),
    M("car-coplights-gone", "carsnap.c",
      "    ReplaySnapshot_MoveData(s, &c->CopLights, 1, -1, 0);          // 2056\n",
      ""),
    M("car-headlights-swapped", "carsnap.c",
      "    ReplaySnapshot_MoveBool(s, &c->HeadlightsState, 1);           // 2100\n"
      "    ReplaySnapshot_MoveBool(s, &c->ForceHeadlightsOn, 1);         // 2096",
      "    ReplaySnapshot_MoveBool(s, &c->ForceHeadlightsOn, 1);         // 2096\n"
      "    ReplaySnapshot_MoveBool(s, &c->HeadlightsState, 1);           // 2100"),
    M("car-blown-count-gone", "carsnap.c",
      "    ReplaySnapshot_MoveChar(s, (int8_t *)&c->NumBlownTires, 1);   // 2125\n",
      ""),
    M("car-no-damage", "carsnap.c",
      "    if (c->pCarDamage != NULL)                                    // 2120",
      "    if (c->pCarDamage == NULL)                                    // 2120"),
    M("car-modes-not-cleared", "carsnap.c",
      "        car_set_control_mode(c, 0);\n        car_set_movement_mode(c, 0);\n",
      ""),
    M("car-skin-always", "carsnap.c",
      "        if (skin != c->pRideInfo->SkinNumber)",
      "        if (1)"),
    M("car-skin-before-restore", "carsnap.c",
      "    skin = c->pRideInfo->SkinNumber;\n"
      "    ReplaySnapshot_MoveChar(s, &c->pRideInfo->SkinNumber, 1);",
      "    ReplaySnapshot_MoveChar(s, &c->pRideInfo->SkinNumber, 1);\n"
      "    skin = c->pRideInfo->SkinNumber;"),
    M("car-state-before-mover", "carsnap.c",
      "    ((CarSnapshotFn)e->fn)(vt_this(c->pCarMover, e), s);\n"
      "    carstate_do_snapshot(&c->State, s);",
      "    carstate_do_snapshot(&c->State, s);\n"
      "    ((CarSnapshotFn)e->fn)(vt_this(c->pCarMover, e), s);"),
    M("car-no-animated-driver", "carsnap.c",
      "    if (c->pAnimatedDriver != NULL) {                             // 1204",
      "    if (0) {                                                      // 1204"),
    M("car-retail-driver-flag-ignored", "carsnap.c",
      "    } else if (gCarSnapshotRetailDrivers != NULL && *gCarSnapshotRetailDrivers\n",
      "    } else if (gCarSnapshotRetailDrivers != NULL\n"),
    M("car-retail-driver-traffic", "carsnap.c",
      "               && c->pCarTypeInfo->UsageType != 2) {",
      "               && c->pCarTypeInfo->UsageType != 3) {"),
    M("car-retail-driver-never", "carsnap.c",
      "               && c->pCarTypeInfo->UsageType != 2) {",
      "               && 0) {"),
    M("car-retail-driver-byte", "carsnap.c",
      "        int8_t backwards[2] = {0, 0};",
      "        int8_t backwards[2] = {0, 1};"),
    M("car-retail-driver-one-byte", "carsnap.c",
      "        ReplaySnapshot_MoveChar(s, &backwards[1], 1);\n",
      ""),
    M("car-retail-driver-no-section", "carsnap.c",
      "        ReplaySnapshot_BeginNamedSection(s, \"AnimatedDriver\");\n",
      ""),
    M("car-gear-speed-swapped", "carsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &c->OldSpeed);                    // 1184\n"
      "    ReplaySnapshot_MoveData(s, &c->DispGear, 1, -1, 0);           // 1104",
      "    ReplaySnapshot_MoveData(s, &c->DispGear, 1, -1, 0);           // 1104\n"
      "    ReplaySnapshot_MoveFloat(s, &c->OldSpeed);                    // 1184"),
    M("car-reset-low-three", "carsnap.c",
      "        c->ResetMe = bits & 15;", "        c->ResetMe = bits & 7;"),
    M("car-reset-frames-from-three", "carsnap.c",
      "        c->JustResetFrames = bits >> 4;",
      "        c->JustResetFrames = bits >> 3;"),
    M("car-reset-pack-three", "carsnap.c",
      "                         + ((uint8_t)c->JustResetFrames << 4));",
      "                         + ((uint8_t)c->JustResetFrames << 3));"),
    M("car-blink-timer-short", "carsnap.c",
      "    ReplaySnapshot_MoveData(s, &c->BlinkTimer, 4, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &c->BlinkTimer, 2, -1, 0);"),
    M("car-skids-three", "carsnap.c",
      "    ReplaySnapshot_MoveData(s, c->NumTimesSkidding, 4, 4, 0);",
      "    ReplaySnapshot_MoveData(s, c->NumTimesSkidding, 3, 4, 0);"),
    M("car-draft-kept", "carsnap.c",
      "        c->DraftFactor = 0.0f;", "        c->DraftFactor = c->DraftFactor;"),
    M("car-damage-boost-gone", "carsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &c->fDamageBoostOverride);        // 1120\n",
      ""),
    M("car-path-gone", "carsnap.c",
      "    trackpath_coord_do_snapshot(&c->TheTrackPathCoordinate, s);   // 2016\n",
      ""),
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
        t0 = time.time()
        with tempfile.TemporaryDirectory() as bt:
            exe = hostbuild.build(bt, srcs, name="carsnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "carsnap_test",
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
    args = ap.parse_args()

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
