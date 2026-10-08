#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carrenderinfo.c (CarRenderInfo from
retail's Car.obj), epositionmarker.c and the eModel methods it uses against
the retail image itself, run in mipsemu.

The model is the image: Car::InitRenderInfo (0x0011dc80), CarRenderInfo's
constructor (0x0011e860) and destructor (0x0011fac0), SwitchSkin,
Car::SwitchSkin (0x0011e588) with UpdateSkinTextures and
UpdateTextureInfo under it, UpdateCarReplacementTextures,
CreateCarLightFlares and the culler's InitPart run as shipped, and so does all they call that is pure or already
ported: GetSkinInfo, GetUsedCarTextureInfo, eFindPositionMarker, eFindSolid,
eModel's Init, UnInit, ReconnectSolid, ReconnectTextureTable,
ApplyReplacementTextureTable, AttachReplacementTextureTable, RenameTexture,
ReplaceLightMaterial, GetBoundingBox and destructor, the three list
destructors, bStringHash, bRandom, and the bounding-box pair. The culler's
table is the one the static constructor (0x00124528) leaves, and the
CARFX_ hashes are put beside their names as InitCarEffects puts them.

Every other callee is a stub that prints its name and its arguments:
bMalloc, bFree, bSlotOMalloc, bSlotFree, GetTextureInfo, elGetLightMaterial,
FixStripSTs, the animated driver's pair, the body damage's pair,
afxGetEmitters, AcidEmitter's destructor and eWaitUntilRenderingDone.
bSPrintf and bMemSet are done in Python. The harness links the port with
the real emodel.c, epositionmarker.c, cartypeinfo.c, bmath.c and bvector.c
and the same stubs, and prints the same lines.

Each scenario builds a world -- four car types, a skin table, solids with
texture and light-material tables, position markers, the textures that are
loaded -- makes a render info from it, by InitRenderInfo or the constructor
alone with a car or none, and then may switch its skin, update its
damage's textures, make its flares again or destroy it. After each, the
record is printed field by field in retail's order, with the lists walked,
and then the solids' tables, the textures' rendering orders, the model
list, the culler's table and the random seed.

Where the two may differ by design:

- the model's box: retail's for each model is uninitialised stack that a
  model with no solid leaves alone. The model's stack has the empty box
  where retail keeps it, which is what the port starts from;
- AABBMin's and AABBMax's w lanes, which retail subtracts from and adds to
  the stack's w beside its 0.1s; both print `*`;
- a flare whose marker's direction byte is past the table's eleven, which
  retail reads out of the CARFX_ table beside it. No scenario has one.

    python tools/carrenderinfo_check.py
    python tools/carrenderinfo_check.py --mutate [--only a,b]
    python tools/carrenderinfo_check.py --dump out/carrenderinfo
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/carrenderinfo_test.c"
CRC = "3DS Files/source/carrenderinfo.c"
CRH = "3DS Files/source/carrenderinfo.h"
EMC = "3DS Files/source/emodel.c"
EPC = "3DS Files/source/epositionmarker.c"
CTC = "3DS Files/source/cartypeinfo.c"
SOURCES = [HARNESS, CRC, EMC, EPC, CTC] + ["3DS Files/source/" + f for f in (
    "langtab.c", "bmath.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
INIT_RI = 0x0011dc80
CTOR = 0x0011e860
DTOR = 0x0011fac0
SWITCH = 0x0011fe60
CAR_SWITCH = 0x0011e588
UCRT = 0x0011ff68
FLARES = 0x00120360
INIT_PART = 0x0011d580
STATIC_INIT = 0x00124528
# bmath's static constructor: the empty box bInitializeBoundingBox copies
BMATH_INIT = 0x002598d8

BMALLOC = 0x002577c0
BFREE = 0x00257850                   # __builtin_delete and vec_delete's
BSLOT_OMALLOC = 0x00257c80
BSLOT_FREE = 0x00257ca0
GET_TEX = 0x001abf48
EL_GET_LM = 0x00116a30
FIX_STRIP = 0x0010c158
ASSIGN_DRV = 0x00133488
UNASSIGN_DRV = 0x001334f0
SET_ALEVEL = 0x001b4cd8
ADD_MODEL = 0x001b4d10
AFX_GET = 0x001272e0
ACID_DEL = 0x00124e20
WAIT_RENDER = 0x00111dd8
SPRINTF = 0x00251398
MEMSET = 0x00250340

CTI_ARRAY = GP - 20616
SKIN_TABLE = GP - 20612
NUM_SKINS = GP - 20608
POOL_EP_G = GP - 23672
POOL_LF_G = GP - 25184
TEST_RI = GP - 23664
MARKERS_G = GP - 19328
SOLIDS_G = GP - 25176
MODELS_G = GP - 25168
FLOW_STATE = GP - 21420
SEED = GP - 14472

CULL_TABLE = 0x002dfd40
CARFX_TABLE = 0x002e02b0

# The world's, in the model.
CAR = 0x01100000
CAR_SIZE = 2400
DMG = 0x01101000
DMG_SIZE = 256
RIDE = 0x01101200
RIDE2 = 0x01101210
CTIS = 0x01110000
CTI_SIZE = 1376
NCTI = 4
RI = 0x01200000
RI_SIZE = 2352
CULLER = 0x01201000
SKIN_BASE = 0x01202000
SOLIDS = 0x01210000
SOLID_STRIDE = 0x400
TEXS = 0x01300000
TEX_STRIDE = 256
TDEF = 0x01380000
LMS = 0x01390000
MARKS = 0x013a0000
EPS = 0x01400000
LFS = 0x01410000
EMS = 0x01420000
ALPHA = 0x01430000
POOL_EP = 0x01440000
POOL_LF = 0x01440100

PATTERN = 0xa5
STACK_FILL = 0x77
FLT_MAX = 0x7f7fffff
NFLT_MAX = 0xff7fffff

CTOR_FRAME = 592
INIT_RI_FRAME = 176

CARFX = ["CARFX_NONE", "CARFX_DRIVE_OVER", "CARFX_DRIVE_OVER2",
         "CARFX_SKID_SMOKE", "CARFX_TIRE_SPEW", "CARFX_BOTTOM_OUT",
         "CARFX_DAM_RADIATOR", "CARFX_DAM_ENGINE", "CARFX_BLOWN_TIRE",
         "CARFX_DRIVE_ON_FLAT_TIRE", "CARFX_NITRO", "CARFX_EXHAUST_SMOKE",
         "CARFX_BREAK_SIDE_MIRROR_LEFT", "CARFX_BREAK_SIDE_MIRROR_RIGHT",
         "CARFX_BREAK_LICENSE_PLATE_FRONT", "CARFX_BREAK_LICENSE_PLATE_RIGHT",
         "CARFX_BREAK_HEADLIGHT_LEFT", "CARFX_BREAK_HEADLIGHT_RIGHT",
         "CARFX_BREAK_BRAKELIGHT_LEFT", "CARFX_BREAK_BRAKELIGHT_RIGHT",
         "CARFX_BREAK_WINDSHIELD", "CARFX_BREAK_WINDOW_REAR",
         "CARFX_BREAK_WINDOW_LEFT_FRONT", "CARFX_BREAK_WINDOW_LEFT_REAR",
         "CARFX_BREAK_WINDOW_RIGHT_FRONT", "CARFX_BREAK_WINDOW_RIGHT_REAR"]

# The render info's models, by the port's names, and where retail has them.
MODELS = ([("Body%d" % i, 64 + 24 * i) for i in range(4)]
          + [("Tire%d%d" % (l, e), 160 + 48 * l + 24 * e)
             for l in range(3) for e in range(2)]
          + [("TireBlur%d" % i, 304 + 24 * i) for i in range(2)]
          + [("Brake%d" % i, 352 + 24 * i) for i in range(2)]
          + [("Wiper%d" % i, 400 + 24 * i) for i in range(2)]
          + [("Mirror%d" % i, 448 + 24 * i) for i in range(2)]
          + [("Plate%d" % i, 496 + 24 * i) for i in range(2)]
          + [("Scuffs", 544), ("Dashboard", 568), ("DashWindow", 592),
             ("DashWheel", 616), ("Speedo", 640), ("Tacho", 664)])
TABLES = [("Skin", 1320, 2), ("Dmg", 1376, 12), ("Dash", 1712, 1),
          ("Tire", 1740, 3), ("TireBlur", 1824, 2)]


def h(s):
    v = 0xffffffff
    for c in s.encode("latin-1"):
        v = (v * 33 + c) & 0xffffffff
    return v


def fbits(f):
    if isinstance(f, int):
        return f & M32
    return struct.unpack("<I", struct.pack("<f", f))[0]


def tok(s):
    return s if s else "-"


# ============================================================ the scenarios


class Cti(object):
    def __init__(self, base, name, usage, wheels):
        self.base, self.name, self.usage = base, name, usage
        self.wheels = [tuple(fbits(x) for x in w) for w in wheels]

    def line(self, i):
        v = [i, self.usage] + [x for w in self.wheels for x in w]
        return "C %s %s %s" % (self.base, self.name,
                               " ".join("%x" % (x & M32) for x in v))


class Solid(object):
    def __init__(self, name, tex=(), lm=(), flags=0, anim=0,
                 box=((-2.0, -1.0, -0.5), (2.0, 1.0, 1.5)),
                 pivot=(0.0, 0.0, 0.0)):
        self.name, self.tex, self.lm = name, list(tex), list(lm)
        self.flags, self.anim = flags, anim
        self.box = [fbits(x) for x in box[0] + box[1]]
        self.pivot = [fbits(x) for x in pivot]

    def line(self):
        v = [self.flags, self.anim] + self.box + self.pivot
        return "O %s %s %d %s %d %s" % (
            self.name, " ".join("%x" % x for x in v), len(self.tex),
            " ".join(self.tex), len(self.lm), " ".join(self.lm))


class Marker(object):
    def __init__(self, name, model, pos, param=0):
        self.name, self.model = name, model
        self.pos = [fbits(x) for x in pos]
        self.param = param

    def line(self):
        return "M %s %s %s %x" % (self.name, self.model,
                                  " ".join("%x" % x for x in self.pos),
                                  self.param)


class Build(object):
    """A world and a render info made in it; then `act`."""

    def __init__(self, ctis, skins, solids, markers, textures, mode=0,
                 seed=0x12345678, flow=6, dmg=1, bits=0, ride=(0, 0, 1, 1, 0),
                 cartype=None, afx=0, act=("N",)):
        self.ctis, self.skins = ctis, skins
        self.solids, self.markers, self.textures = solids, markers, textures
        self.mode, self.seed, self.flow = mode, seed, flow
        self.dmg, self.bits, self.ride = dmg, bits, ride
        self.cartype = ride[0] if cartype is None else cartype
        self.afx, self.act = afx, act

    def lines(self):
        out = ["B %x %x %x %x %x %s %x %x" % (
            self.mode, self.seed, self.flow & M32, self.dmg, self.bits,
            " ".join("%x" % (x & M32) for x in self.ride), self.cartype,
            self.afx)]
        out += [c.line(i) for i, c in enumerate(self.ctis)]
        out.append("K %d %s" % (len(self.skins), " ".join(
            "%x %x %s" % (t, s, lm) for t, s, lm in self.skins)))
        out += [s.line() for s in self.solids]
        out += [m.line() for m in self.markers]
        out.append("T %d %s" % (len(self.textures), " ".join(self.textures)))
        a = self.act
        out.append("A " + " ".join([a[0]] + ["%x" % (x & M32)
                                             for x in a[1:]]))
        return out


class Part(object):
    """InitPart on the culler with part `idx` of the table set first."""

    def __init__(self, idx, n, planes, point):
        self.idx, self.n = idx, n
        self.planes = [fbits(x) for p in planes for x in p]
        self.point = [fbits(x) for x in point]

    def lines(self):
        v = [self.idx, self.n] + self.planes + self.point
        return ["P " + " ".join("%x" % (x & M32) for x in v)]


def wheels(fx=1.3, rx=-1.35, y=0.78, z=0.32, rf=0.33, rr=0.35):
    # FL, FR, RR, RL, as the culler names them; the w is the radius.
    return [(fx, y, z, rf), (fx, -y, z, rf), (rx, -y, z, rr),
            (rx, y, z, rr)]


def ctis(w0=None):
    return [Cti("CAR_A", "CARTYPE_A", 0, w0 or wheels()),
            Cti("COPCAR", "COPTYPE", 1,
                wheels(1.4, -1.5, 0.81, 0.3, 0.36, 0.36)),
            Cti("TRAF", "TRAFTYPE", 2,
                wheels(1.1, -1.2, 0.7, 0.28, 0.3, 0.31)),
            Cti("ABCDEFGHIJKLMNOPQRSTUVWXYZ01234", "ODDTYPE", 3,
                wheels(1.25, -1.3, 0.75, 0.31, 0.32, 0.34))]


def skin_textures(b):
    return ["%s_SKIN1" % b, "%s_SKIN1B" % b, "WINDOW_FRONT", "WINDOW_REAR",
            "WINDOW_LEFT_FRONT", "WINDOW_LEFT_REAR", "WINDOW_RIGHT_FRONT",
            "WINDOW_RIGHT_REAR", "%s_HEADLIGHT_LEFT" % b,
            "%s_HEADLIGHT_RIGHT" % b, "%s_BRAKELIGHT_LEFT" % b,
            "%s_BRAKELIGHT_RIGHT" % b, "OTHER"]


def full_solids(b, drop=(), extra_flags=None):
    """A solid for every part, save the names in `drop`."""
    st = skin_textures(b)
    lm = ["CARSKIN", "CHROME", "CARSKIN"]
    names = (["%s_A" % b, "%s_B" % b, "%s_C" % b, "%s_D" % b,
              "%s_A1" % b, "%s_B1" % b, "%s_A3" % b, "%s_B3" % b,
              "%s_TIRE_FRONT_A" % b, "%s_TIRE_FRONT_B" % b,
              "%s_TIRE_FRONT_C" % b, "%s_TIRE_REAR_A" % b,
              "%s_TIRE_REAR_C" % b, "%s_BRAKE_FRONT" % b,
              "%s_WIPER_LEFT" % b, "%s_WIPER_RIGHT" % b,
              "%s_SIDE_MIRROR_LEFT" % b, "%s_SIDE_MIRROR_RIGHT" % b,
              "%s_LICENSE_PLATE_FRONT" % b, "%s_LICENSE_PLATE_REAR" % b,
              "%s_SCUFFS" % b, "%s_SCUFFS1" % b, "%s_DASH" % b,
              "%s_DASH_WHEEL" % b, "%s_DASH_WINDOW" % b,
              "%s_SPEED_NEEDLE" % b, "%s_TACH_NEEDLE" % b,
              "%s_WHEEL_BLUR_F" % b, "%s_WHEEL_BLUR_R" % b])
    out = []
    for k, n in enumerate(names):
        if n in drop:
            continue
        tex = st
        if "TIRE" in n or "BLUR" in n:
            tex = ["%s_SKIN1" % b, "%s_TIRE" % b, "%s_WHEEL_BLUR" % b]
        elif "DASH" in n or "NEEDLE" in n:
            tex = ["%s_DASHSKIN1" % b, "OTHER"]
        box = ((-2.0 - k * 0.125, -1.0 + k * 0.0625, -0.5),
               (2.0 + k * 0.25, 1.0 - k * 0.03125, 1.5 + k * 0.5))
        fl = extra_flags.get(n, (0, 0)) if extra_flags else (0, 0)
        out.append(Solid(n, tex, lm, fl[0], fl[1], box,
                         (0.25 * (k % 3), -0.125 * ((k + 1) % 2), 0.5)))
    return out


LIGHT_MARKERS = ["FLARE_HEADLIGHT_RIGHT", "FLARE_HEADLIGHT_LEFT",
                 "FLARE_BRAKELIGHT_RIGHT", "FLARE_BRAKELIGHT_LEFT",
                 "FLARE_BRAKELIGHT_MIDDLE", "FLARE_REVERSELIGHT_RIGHT",
                 "FLARE_REVERSELIGHT_LEFT", "COPLIGHTRED", "COPLIGHTBLUE",
                 "COPLIGHTWHITE", "HEADLIGHT_RIGHT", "HEADLIGHT_LEFT"]
EMITTER_MARKERS = ["LICENSE_PLATE_FRONT", "LICENSE_PLATE_REAR", "ENGINE",
                   "EXHAUST", "EXHAUST_LEFT", "EXHAUST_RIGHT", "RADIATOR",
                   "WINDOW_FRONT", "WINDOW_REAR", "WINDOW_LEFT_FRONT",
                   "WINDOW_LEFT_REAR", "WINDOW_RIGHT_FRONT",
                   "WINDOW_RIGHT_REAR", "HEADLIGHT_LEFT", "HEADLIGHT_RIGHT",
                   "BRAKELIGHT_LEFT", "BRAKELIGHT_RIGHT", "SIDE_MIRROR_LEFT",
                   "SIDE_MIRROR_RIGHT"]


def all_markers(b, rnd):
    out = []
    names = LIGHT_MARKERS + EMITTER_MARKERS + ["NOT_A_MARKER", "ENGINE"]
    for k, n in enumerate(names):
        p = (rnd.uniform(-2, 2), rnd.uniform(-1, 1), rnd.uniform(0, 1.5))
        out.append(Marker(n, b, p, rnd.randrange(1 << 32) & 0xffff00ff
                          | (rnd.randrange(11) << 8)))
        if k % 5 == 0:
            out.append(Marker(n, "SOMEONE_ELSE", p, 0x300))
    return out


def textures(b, shadow=True, ramp=True, fe=False):
    t = ["%s_SKIN2" % b, "%s_SKIN2B" % b, "WINDOW_DAMAGE0", "WINDOW",
         "%s_HEADLIGHT_DAMAGE0" % b, "%s_TIRE" % b, "CARTYPE_A_TIRE"]
    if shadow:
        t.append("%s_SHADOWFE" % b if fe else "%s_SHADOWIG" % b)
    if ramp:
        t.append("SHADOWRAMP")
    return t


SKINS = [(0, 1, "SKIN_LM_A1"), (0, 2, "SKIN_LM_A2"), (1, 1, "SKIN_LM_COP"),
         (2, 1, "SKIN_LM_TRAF"), (3, 5, "SKIN_LM_ODD")]


def script():
    rnd = random.Random(0xc4a5)
    sc = []
    bases = [c.base for c in ctis()]

    def build(t=0, **kw):
        b = bases[t]
        kw.setdefault("ride", (t, 0, 2, 1, 0))
        solids = kw.pop("solids", None)
        if solids is None:
            solids = full_solids(b)
        markers = kw.pop("markers", None)
        if markers is None:
            markers = all_markers(b, rnd)
        tex = kw.pop("tex", None)
        if tex is None:
            tex = textures(b)
        skins = kw.pop("skins", SKINS)
        cts = kw.pop("ctis", None) or ctis()
        return Build(cts, skins, solids, markers, tex, **kw)

    # Each type, each way of making one.
    for t in range(NCTI):
        for mode in (0, 1, 2):
            sc.append(build(t, mode=mode))
    # The ride: instance, skin, dash, dents.
    for inst in (0, 1, 3, -1, 127):
        for cbvd in (0, 1, 2):
            sc.append(build(0, ride=(0, inst, 1, 1, cbvd)))
        sc.append(build(2, ride=(2, inst, 1, 0, 1)))
    for skin in (0, 1, 2, 5, -1, 100):
        for hasdash in (0, 1):
            sc.append(build(0, ride=(0, 0, skin, hasdash, 0)))
    sc.append(build(3, ride=(3, 0, 5, 1, 0)))
    sc.append(build(3, ride=(3, 0, 6, 1, 0)))
    # A skin table without the ride's skin, and one with only other cars'.
    sc.append(build(0, skins=[(1, 1, "X1"), (0, 7, "X2")]))
    sc.append(build(0, skins=[(3, 3, "ONLY")]))
    # The car's type other than the ride's.
    sc.append(build(0, cartype=1))
    sc.append(build(2, cartype=0, ride=(2, 0, 1, 0, 0)))
    # No damage, and every level of every item.
    sc.append(build(0, dmg=0))
    sc.append(build(0, mode=1, dmg=0, bits=0xffffffff))
    for lvl in range(4):
        sc.append(build(0, bits=int("".join(["%d" % (lvl // 2), "%d" % (lvl % 2)]
                                           * 16), 2)))
    for item in range(15):
        for lvl in (1, 2, 3):
            sc.append(build(0, bits=lvl << (2 * item)))
    for _ in range(12):
        sc.append(build(rnd.randrange(NCTI), bits=rnd.randrange(1 << 32)))
    # Both brake lights broken, and one.
    sc.append(build(0, bits=(2 << 12) | (3 << 14)))
    sc.append(build(0, bits=(2 << 12)))
    sc.append(build(0, bits=(3 << 14) | (2 << 8) | (2 << 10)))
    # The shadow: the front end, the game, no flow, and textures missing.
    for flow in (3, 6, 0, -1, 2, 4):
        sc.append(build(0, flow=flow, tex=textures("CAR_A", fe=flow == 3)))
    sc.append(build(0, flow=3, tex=textures("CAR_A", fe=False)))
    sc.append(build(0, flow=6, tex=textures("CAR_A", shadow=False)))
    sc.append(build(0, flow=3, tex=textures("CAR_A", fe=True, ramp=False)))
    sc.append(build(0, tex=[]))
    # Solids missing: each part's fall-back, the body and mirrors' box.
    for drop in (["CAR_A_A"], ["CAR_A_A", "CAR_A_SIDE_MIRROR_LEFT"],
                 ["CAR_A_TIRE_FRONT_A", "CAR_A_TIRE_REAR_A"],
                 ["CAR_A_TIRE_REAR_A", "CAR_A_TIRE_REAR_C"],
                 ["CAR_A_BRAKE_FRONT"],
                 ["CAR_A_WHEEL_BLUR_F"], ["CAR_A_WHEEL_BLUR_R"],
                 ["CAR_A_WHEEL_BLUR_F", "CAR_A_WHEEL_BLUR_R"],
                 ["CAR_A_SIDE_MIRROR_RIGHT", "CAR_A_SIDE_MIRROR_LEFT"],
                 ["CAR_A_C", "CAR_A_D", "CAR_A_DASH"]):
        sc.append(build(0, solids=full_solids("CAR_A", drop)))
    sc.append(build(0, solids=[]))
    sc.append(build(0, solids=[], markers=[]))
    sc.append(build(2, solids=full_solids("TRAF", ["TRAF_TIRE_REAR_A"])))
    # A wheel blur for both ends, which the F and R must not replace.
    sc.append(build(0, solids=full_solids("CAR_A") + [
        Solid("CAR_A_WHEEL_BLUR", ["CAR_A_WHEEL_BLUR"], ["CARSKIN"])]))
    # Animated solids: a running start, a random one, a stopped one.
    sc.append(build(0, solids=full_solids("CAR_A", extra_flags={
        "CAR_A_A": (0x20, 1), "CAR_A_B": (0x20, 2), "CAR_A_C": (0, 1),
        "CAR_A_WIPER_LEFT": (0x20, 1)}), seed=0x9abcdef1))
    for seed in (0, 1, 0xffffffff, 0x80000000):
        sc.append(build(0, seed=seed))
    # A texture table with the old names twice, and none.
    sc.append(build(0, solids=[Solid("CAR_A_A", ["CAR_A_SKIN1"] * 3
                                     + ["WINDOW_FRONT"] * 2, ["CARSKIN"] * 4),
                               Solid("CAR_A_C", ["CAR_A_SKIN1"] * 2),
                               Solid("CAR_A_D", [], [])]))
    # The markers: none, only other cars', each alone, many in any order.
    sc.append(build(0, markers=[]))
    sc.append(build(0, markers=[Marker(n, "NOBODY", (1.0, 2.0, 3.0))
                                for n in LIGHT_MARKERS + EMITTER_MARKERS]))
    for n in LIGHT_MARKERS + EMITTER_MARKERS:
        for d in (0, 3, 10):
            sc.append(build(1, markers=[Marker(n, "COPCAR", (0.5, -0.25, 1.0),
                                               0xa5a500a5 | (d << 8))]))
    for _ in range(6):
        ms = all_markers("CAR_A", rnd)
        rnd.shuffle(ms)
        sc.append(build(0, markers=ms))
    # The wheels, in a few shapes.
    for w in (wheels(2.0, -2.0, 1.0, 0.0, 0.5, 0.5),
              wheels(1.3, -1.35, 0.78, -0.32, 0.33, 0.0),
              [(1.0, 0.5, 0.1, 0.3), (1.2, -0.6, 0.2, 0.4),
               (-1.1, -0.7, 0.3, 0.2), (-0.9, 0.8, 0.4, 0.1)],
              [(1e3, 5e2, -1e1, 3.0), (1e3, -5e2, -1e1, 3.0),
               (-1e3, -5e2, 1e1, 2.0), (-1e3, 5e2, 1e1, 2.0)]):
        sc.append(build(0, ctis=ctis(w)))
    # The emitters.
    for afx in (0, 1, 0x3ffffff, 0x2000001, 0x1555555):
        sc.append(build(0, afx=afx))

    # Then each act on one.
    for s in (0, 1, 2, 5):
        sc.append(build(0, act=("S", 0, 1, s, 1, 0)))
    sc.append(build(0, act=("S", 1, 0, 1, 0, 1)))
    sc.append(build(2, act=("S", 3, 2, 5, 1, 0)))
    # Car::SwitchSkin: the ride's skin byte set first, so the ride's own
    # skin (1, 0 below) is never the one used.
    for s in (0, 2, 5, 0x102):
        sc.append(build(0, act=("C", 0, 1, 1, 1, 0, s)))
    sc.append(build(2, act=("C", 3, 2, 0, 1, 1, 4)))
    sc.append(build(0, mode=1, act=("C", 1, 0, 1, 0, 1, 2)))
    for bits in (0, 0xffffffff, 2 << 8, (2 << 12) | (2 << 14), 0x55555555,
                 0xaaaaaaaa):
        sc.append(build(0, act=("U", bits)))
        sc.append(build(0, dmg=0, act=("U", bits)))
    sc.append(build(0, mode=2, act=("U", 0xffffffff)))
    sc.append(build(0, act=("L",)))
    sc.append(build(1, mode=2, act=("L",)))
    for flags in (0, 1, 2, 3, -1, -2):
        for alpha in (0, 1):
            sc.append(build(0, afx=0x1555555, act=("D", flags, alpha)))
    sc.append(build(0, mode=2, afx=0x3ffffff, act=("D", 3, 1)))
    sc.append(build(0, markers=[], afx=0, act=("D", 1, 0)))
    sc.append(build(2, solids=[], act=("D", 1, 0)))

    # InitPart alone, on planes about the 0.01 either side of length 1.
    def unit(x, y, z, s):
        return (x * s, y * s, z * s, 0.5 * s)
    for s in (1.0, 1.009, 1.0099999, 1.01, 1.0100001, 1.011, 0.991,
              0.9900001, 0.99, 0.9899999, 2.0, 0.5, 1e-3, 1e3):
        sc.append(Part(0, 1, [unit(0.6, 0.8, 0.0, s), (0, 0, 0, 0),
                              (0, 0, 0, 0)], (1.0, 2.0, 3.0, 4.0)))
    for n in (-1, 0, 1, 2, 3):
        sc.append(Part(13, n, [(3.0, 0, 0, 1.0), (0, 4.0, 0, 2.0),
                               (0, 0, 0.5, 3.0)], (-1.0, -2.0, 0.0, 8.0)))
    for _ in range(10):
        planes = [tuple(rnd.uniform(-2, 2) for _ in range(4))
                  for _ in range(3)]
        sc.append(Part(rnd.randrange(14), rnd.randrange(4), planes,
                       tuple(rnd.uniform(-5, 5) for _ in range(4))))
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        stubs = {
            BMALLOC: self.bmalloc, BFREE: self.bfree,
            BSLOT_OMALLOC: self.bslot_omalloc, BSLOT_FREE: self.bslot_free,
            GET_TEX: self.get_tex, EL_GET_LM: self.get_lm,
            FIX_STRIP: self.fix_strip, ASSIGN_DRV: self.assign_drv,
            UNASSIGN_DRV: self.unassign_drv, SET_ALEVEL: self.set_alevel,
            ADD_MODEL: self.add_model, AFX_GET: self.afx_get,
            ACID_DEL: self.acid_del, WAIT_RENDER: self.wait_render,
            SPRINTF: self.sprintf, MEMSET: self.memset,
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        self.fill_stack()
        e.call(BMATH_INIT, limit=1000)
        e.call(STATIC_INIT, limit=100000)
        for i, n in enumerate(CARFX):
            assert self.cstr(e.u32(CARFX_TABLE + 8 * i)) == n
            e.put32(CARFX_TABLE + 8 * i + 4, h(n))
        e.put32(POOL_EP_G, POOL_EP)
        e.put32(POOL_LF_G, POOL_LF)
        e.put32(CTI_ARRAY, CTIS)
        e.put32(TEST_RI, 0)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def cstr(self, a):
        b = bytearray()
        while self.e.u8(a + len(b)) != 0:
            b.append(self.e.u8(a + len(b)))
        return b.decode("latin-1")

    def fill_stack(self):
        sp = self.e.reg[29] & M32
        self.e.write(sp - 16384, bytes([STACK_FILL]) * 16384)
        return sp

    def empty_box(self, entry_sp):
        base = entry_sp - CTOR_FRAME
        for i in range(3):
            self.e.put32(base + 64 + 4 * i, FLT_MAX)
            self.e.put32(base + 80 + 4 * i, NFLT_MAX)

    # ---- the labels ------------------------------------------------------

    def reg(self, a, name):
        self.names[a & M32] = name

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == 0xa5a5a5a5:
            return "a5"
        n = self.names.get(a)
        if n is not None:
            return n
        return "?%08x" % a

    def register(self):
        self.names = {}
        r = self.reg
        r(CAR, "car")
        r(DMG, "dmg")
        r(DMG + 8, "bd")
        r(RIDE, "ride")
        r(RIDE2, "ride2")
        for i in range(NCTI):
            r(CTIS + CTI_SIZE * i, "cti%d" % i)
        r(RI, "ri")
        r(ALPHA, "alpha")
        r(POOL_EP, "EPPool")
        r(POOL_LF, "LFPool")
        r(TDEF, "tdef")
        r(MODELS_G, "ModelList")
        r(SOLIDS_G, "SolidList")
        r(MARKERS_G, "MarkerList")
        for name, off in MODELS:
            r(RI + off, name)
        r(RI + 872, "LFL")
        for k in range(26):
            r(RI + 888 + 8 * k, "EL%d" % k)
        for k in range(28):
            r(RI + 1096 + 8 * k, "EPL%d" % k)
        for name, off, _ in TABLES:
            r(RI + off, name)
        for k in range(64):
            r(SOLIDS + SOLID_STRIDE * k, "s%d" % k)
            r(TEXS + TEX_STRIDE * k, "t%d" % k)
            r(MARKS + 32 * k, "mk%d" % k)
            r(EMS + 16 * k, "em%d" % k)
        for k in range(256):
            r(EPS + 16 * k, "ep%d" % k)
            r(LFS + 80 * k, "lf%d" % k)
            r(LMS + 16 * k, "lm%d" % k)

    # ---- the stubs -------------------------------------------------------

    def bmalloc(self, em):
        size, name = s32(self.arg(0)), self.cstr(self.arg(1))
        flags, pool = s32(self.arg(2)), s32(self.arg(3))
        self.emit("  bMalloc %s %s %d %d -> ri" % (
            "sizeof" if size == RI_SIZE else "%d" % size, name, flags, pool))
        em.write(RI, bytes([PATTERN]) * RI_SIZE)
        return RI

    def bfree(self, em):
        self.emit("  bFree %s" % self.label(self.arg(0)))

    def bslot_omalloc(self, em):
        pool = self.arg(0)
        if pool == POOL_EP:
            a, size = EPS + 16 * self.nep, 16
            self.nep += 1
        elif pool == POOL_LF:
            a, size = LFS + 80 * self.nlf, 80
            self.nlf += 1
        else:
            raise SystemExit("bSlotOMalloc from %08x" % pool)
        em.write(a, bytes([PATTERN]) * size)
        self.emit("  bSlotOMalloc %s -> %s" % (self.label(pool),
                                               self.label(a)))
        return a

    def bslot_free(self, em):
        self.emit("  bSlotFree %s %s" % (self.label(self.arg(0)),
                                         self.label(self.arg(1))))

    def get_tex(self, em):
        hsh, dflt, inc = self.arg(0), s32(self.arg(1)), s32(self.arg(2))
        if hsh in self.tex:
            r = TEXS + TEX_STRIDE * self.tex[hsh]
        elif dflt:
            r = TDEF
        else:
            r = 0
        self.emit("  GetTextureInfo %08x %d %d -> %s" % (hsh, dflt, inc,
                                                         self.label(r)))
        return r

    def get_lm(self, em):
        hsh = self.arg(0)
        if hsh == 0:
            r = 0
        else:
            if hsh not in self.lm:
                self.lm[hsh] = len(self.lm)
            r = LMS + 16 * self.lm[hsh]
        self.emit("  elGetLightMaterial %08x -> %s" % (hsh, self.label(r)))
        return r

    def fix_strip(self, em):
        self.emit("  FixStripSTs %s" % self.label(self.arg(0)))

    def assign_drv(self, em):
        self.emit("  AssignAnimatedDriver %s %s" % (
            self.label(self.arg(0)), self.cstr(self.arg(1))))

    def unassign_drv(self, em):
        self.emit("  UnAssignAnimatedDriver %s" % self.label(self.arg(0)))

    def set_alevel(self, em):
        self.emit("  SetALevelBodyDamageInfo %s %s" % (
            self.label(self.arg(0)), self.cstr(self.arg(1))))

    def add_model(self, em):
        self.emit("  AddModel %s %s %s %d" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.cstr(self.arg(2)), s32(self.arg(3))))

    def afx_get(self, em):
        lst, hsh = self.arg(0), self.arg(1)
        self.emit("  afxGetEmitters %s %08x" % (self.label(lst), hsh))
        k = (lst - (RI + 888)) // 8
        if 0 <= k < 26 and self.sc.afx >> k & 1:
            n = EMS + 16 * self.nem
            self.nem += 1
            em.write(n, bytes([PATTERN]) * 16)
            tail = em.u32(lst + 4)
            em.put32(n, lst)
            em.put32(n + 4, tail)
            em.put32(tail, n)
            em.put32(lst + 4, n)

    def acid_del(self, em):
        self.emit("  ~AcidEmitter %s %d" % (self.label(self.arg(0)),
                                            s32(self.arg(1))))

    def wait_render(self, em):
        self.emit("  eWaitUntilRenderingDone")

    def sprintf(self, em):
        dst, fmt = self.arg(0), self.cstr(self.arg(1))
        out, i, k = [], 0, 2
        while i < len(fmt):
            c = fmt[i]
            if c != "%":
                out.append(c)
                i += 1
                continue
            conv = fmt[i + 1]
            i += 2
            v = self.arg(k)
            k += 1
            if conv == "s":
                out.append(self.cstr(v))
            elif conv == "c":
                out.append(chr(v & 0xff))
            elif conv == "d":
                out.append("%d" % s32(v))
            else:
                raise SystemExit("sprintf %%%s" % conv)
        s = "".join(out).encode("latin-1") + b"\0"
        em.write(dst, s)
        return len(s) - 1

    def memset(self, em):
        a, v, n = self.arg(0), self.arg(1), s32(self.arg(2))
        em.mem[a:a + n] = bytes([v & 0xff]) * n
        return a

    # ---- the world -------------------------------------------------------

    def link(self, sentinel, nodes):
        e = self.e
        prev = sentinel
        for n in nodes:
            e.put32(prev, n)
            e.put32(n + 4, prev)
            prev = n
        e.put32(prev, sentinel)
        e.put32(sentinel + 4, prev)

    def world(self, sc):
        e = self.e
        self.register()
        self.nep = self.nlf = self.nem = 0
        self.lm = {}
        e.write(CAR, bytes([PATTERN]) * CAR_SIZE)
        e.put32(CAR + 12, CTIS + CTI_SIZE * sc.cartype)
        e.write(DMG, bytes([PATTERN]) * DMG_SIZE)
        e.put32(DMG + 204, sc.bits)
        e.put32(CAR + 2120, DMG if sc.dmg else 0)
        e.write(RIDE, struct.pack("<i4b", sc.ride[0],
                                  *[s32(x) if -128 <= s32(x) < 128 else
                                    s32(x) - 256 for x in sc.ride[1:]]))
        e.write(RI, bytes([PATTERN]) * RI_SIZE)
        e.write(ALPHA, bytes([PATTERN]) * 16)
        for i, c in enumerate(sc.ctis):
            a = CTIS + CTI_SIZE * i
            e.write(a, bytes([PATTERN]) * CTI_SIZE)
            e.write(a, c.name.encode() + b"\0")
            e.write(a + 32, c.base.encode() + b"\0")
            e.put32(a + 1336, c.usage)
            for k, w in enumerate(c.wheels):
                for j in range(4):
                    e.put32(a + 288 + 32 * k + 4 * j, w[j])
        e.write(SKIN_BASE, bytes([PATTERN]) * 64 * max(1, len(sc.skins)))
        for k, (t, s, lm) in enumerate(sc.skins):
            e.put32(SKIN_BASE + 64 * k, t)
            e.put32(SKIN_BASE + 64 * k + 4, s)
            e.put32(SKIN_BASE + 64 * k + 44, h(lm))
        e.put32(SKIN_TABLE, SKIN_BASE)
        e.put32(NUM_SKINS, len(sc.skins))
        self.tex = {}
        for k, n in enumerate(sc.textures):
            self.tex.setdefault(h(n), k)
            e.write(TEXS + TEX_STRIDE * k, bytes([PATTERN]) * TEX_STRIDE)
        e.write(TDEF, bytes([PATTERN]) * TEX_STRIDE)
        nodes = []
        for k, s in enumerate(sc.solids):
            a = SOLIDS + SOLID_STRIDE * k
            e.write(a, bytes([PATTERN]) * SOLID_STRIDE)
            e.put32(a + 8, h(s.name))
            e.mem[a + 48:a + 50] = struct.pack("<H", s.flags)
            for j in range(3):
                e.put32(a + 64 + 4 * j, s.box[j])
                e.put32(a + 80 + 4 * j, s.box[3 + j])
                e.put32(a + 144 + 4 * j, s.pivot[j])
            if s.anim:
                e.put32(a + 168, a + 0x300)
                e.mem[a + 0x302] = 0 if s.anim == 1 else 1
            else:
                e.put32(a + 168, 0)
            e.mem[a + 172:a + 176] = struct.pack("<hh", len(s.tex),
                                                 len(s.lm))
            e.put32(a + 184, a + 0x100)
            e.put32(a + 188, a + 0x200)
            for j, t in enumerate(s.tex):
                e.put32(a + 0x100 + 8 * j, h(t))
            for j, t in enumerate(s.lm):
                e.put32(a + 0x200 + 8 * j, h(t))
            nodes.append(a)
        self.link(SOLIDS_G, nodes)
        self.link(MODELS_G, [])
        nodes = []
        for k, m in enumerate(sc.markers):
            a = MARKS + 32 * k
            e.put32(a + 8, h(m.name))
            e.put32(a + 12, h(m.model))
            for j in range(3):
                e.put32(a + 16 + 4 * j, m.pos[j])
            e.put32(a + 28, m.param)
            nodes.append(a)
        self.link(MARKERS_G, nodes)
        s = sc.flow
        e.put32(FLOW_STATE, s)
        e.put32(SEED, sc.seed)

    # ---- the dump --------------------------------------------------------

    def w(self, a):
        return "%08x" % self.e.u32(a)

    def dump(self, sc):
        e = self.e
        L = self.label
        out = ["  ri %s %s %s %s" % (L(e.u32(RI)), L(e.u32(RI + 4)),
                                     L(e.u32(RI + 8)), self.w(RI + 12))]
        box = []
        for off in (16, 32):
            box += [self.w(RI + off + 4 * i) for i in range(3)] + ["*"]
        box += [self.w(RI + 48 + 4 * i) for i in range(4)]
        out.append("  box " + " ".join(box))
        for name, off in MODELS:
            a = RI + off
            out.append("  %s %s %s %s %02x %02x %04x %s %s" % (
                name, self.w(a + 8), L(e.u32(a + 12)), L(e.u32(a + 16)),
                e.u8(a + 20), e.u8(a + 21), e.u16(a + 22), L(e.u32(a)),
                L(e.u32(a + 4))))
        out.append("  used " + " ".join(self.w(RI + 688 + 4 * i)
                                        for i in range(43)))
        out.append("  tex %s %s %s %s %s" % (
            L(e.u32(RI + 860)), L(e.u32(RI + 864)), L(e.u32(RI + 868)),
            self.w(RI + 880), self.w(RI + 884)))
        n = e.u32(RI + 872)
        fl = []
        guard = 0
        while n != RI + 872 and guard < 300:
            fl.append("%s<%s %s %02x %02x %04x %02x %s" % (
                L(n), L(e.u32(n + 4)), self.w(n + 8), e.u8(n + 12),
                e.u8(n + 13), e.u16(n + 14), e.u8(n + 16),
                " ".join(self.w(n + o) for o in range(48, 80, 4))))
            n = e.u32(n)
            guard += 1
        out.append("  flares %s | %s" % (L(e.u32(RI + 876)),
                                         " ; ".join(fl)))
        for k in range(26):
            a = RI + 888 + 8 * k
            n, ns = e.u32(a), []
            while n != a and len(ns) < 50:
                ns.append("%s<%s" % (L(n), L(e.u32(n + 4))))
                n = e.u32(n)
            out.append("  EL%d %s | %s" % (k, L(e.u32(a + 4)), " ".join(ns)))
        for k in range(28):
            a = RI + 1096 + 8 * k
            n, ns = e.u32(a), []
            while n != a and len(ns) < 50:
                ns.append("%s %s" % (L(n), " ".join(
                    self.w(n + o) for o in (4, 8, 12))))
                n = e.u32(n)
            out.append("  EPL%d %s | %s" % (k, L(e.u32(a + 4)),
                                             " ; ".join(ns)))
        for name, off, cnt in TABLES:
            for i in range(cnt):
                a = RI + off + 28 * i
                out.append("  %s%d %s %s %s %s" % (
                    name, i, self.w(a), self.w(a + 4), L(e.u32(a + 8)),
                    bytes(e.mem[a + 12:a + 28]).hex()))
        out.append("  pad1880 " + bytes(e.mem[RI + 1880:RI + 1888]).hex())
        for i in range(14):
            a = RI + 1888 + 32 * i
            out.append("  part%d %s" % (i, " ".join(self.w(a + 4 * j)
                                                     for j in range(8))))
        out.append("  alpha %s %s %s" % (
            L(e.u32(RI + 2336)), self.w(RI + 2340),
            bytes(e.mem[RI + 2344:RI + 2352]).hex()))
        self.emit_all(out)
        self.dump_world(sc)

    def dump_world(self, sc):
        e = self.e
        L = self.label
        out = []
        for k, s in enumerate(sc.solids):
            a = SOLIDS + SOLID_STRIDE * k
            out.append("  s%d tex %s | lm %s" % (
                k, " ".join("%s:%s" % (self.w(a + 0x100 + 8 * j),
                                       L(e.u32(a + 0x104 + 8 * j)))
                            for j in range(len(s.tex))),
                " ".join("%s:%s" % (self.w(a + 0x200 + 8 * j),
                                    L(e.u32(a + 0x204 + 8 * j)))
                         for j in range(len(s.lm)))))
        out.append("  order %s %02x" % (" ".join(
            "%02x" % e.u8(TEXS + TEX_STRIDE * k + 41)
            for k in range(len(sc.textures))), e.u8(TDEF + 41)))
        n, ns = e.u32(MODELS_G), []
        while n != MODELS_G and len(ns) < 100:
            ns.append("%s<%s" % (L(n), L(e.u32(n + 4))))
            n = e.u32(n)
        out.append("  models %s | %s" % (L(e.u32(MODELS_G + 4)),
                                         " ".join(ns)))
        out.append("  car %s test %s seed %s" % (
            L(e.u32(CAR + 1200)), L(e.u32(TEST_RI)), self.w(SEED)))
        self.emit_all(out)

    def dump_table(self):
        e = self.e
        out = []
        for i in range(14):
            a = CULL_TABLE + 80 * i
            out.append("  cull%d %s %s %s %s %s" % (
                i, self.w(a), self.cstr(e.u32(a + 4)), self.w(a + 8),
                self.w(a + 12), " ".join(self.w(a + 16 + 4 * j)
                                         for j in range(16))))
        self.emit_all(out)

    def emit_all(self, lines):
        for s in lines:
            self.emit(s)

    # ---- the runs --------------------------------------------------------

    def build(self, n, sc):
        e = self.e
        self.world(sc)
        self.emit("B %d" % n)
        sp = self.fill_stack()
        if sc.mode == 0:
            self.empty_box(sp - INIT_RI_FRAME)
            e.call(INIT_RI, CAR, RIDE, limit=5000000)
            ret = RI
        else:
            self.empty_box(sp)
            ret = e.call(CTOR, RI, RIDE, CAR if sc.mode == 1 else 0,
                         limit=5000000)
        self.emit("  ret %s" % self.label(ret))
        self.dump(sc)
        a = sc.act
        if a[0] == "S":
            e.write(RIDE2, struct.pack("<i4b", a[1], *[
                s32(x) if -128 <= s32(x) < 128 else s32(x) - 256
                for x in a[2:]]))
            self.emit("S")
            self.fill_stack()
            e.call(SWITCH, RI, RIDE2, limit=1000000)
        elif a[0] == "C":
            e.write(RIDE2, struct.pack("<i4b", a[1], *[
                s32(x) if -128 <= s32(x) < 128 else s32(x) - 256
                for x in a[2:6]]))
            e.put32(CAR + 16, RIDE2)
            e.put32(CAR + 1200, RI)
            self.emit("C")
            self.fill_stack()
            e.call(CAR_SWITCH, CAR, a[6] & M32, limit=1000000)
        elif a[0] == "U":
            e.put32(DMG + 204, a[1])
            self.emit("U")
            self.fill_stack()
            e.call(UCRT, RI, limit=1000000)
        elif a[0] == "L":
            self.emit("L")
            self.fill_stack()
            e.call(FLARES, RI, limit=1000000)
        elif a[0] == "D":
            if a[2]:
                e.put32(RI + 2336, ALPHA)
                e.put32(RI + 2340, 1)
            self.emit("D")
            self.fill_stack()
            e.call(DTOR, RI, a[1] & M32, limit=1000000)
        else:
            return
        self.dump(sc)

    def part(self, n, sc):
        e = self.e
        self.names = {}
        a = CULL_TABLE + 80 * sc.idx
        saved = bytes(e.mem[a:a + 80])
        e.put32(a + 12, sc.n)
        for j in range(12):
            e.put32(a + 16 + 4 * j, sc.planes[j])
        e.write(CULLER, bytes([PATTERN]) * 14 * 32)
        pt = CULLER + 0x400
        for j in range(4):
            e.put32(pt + 4 * j, sc.point[j])
        self.emit("P %d" % n)
        self.fill_stack()
        e.call(INIT_PART, CULLER, sc.idx, pt, limit=100000)
        self.emit("  planes %s" % " ".join(self.w(a + 16 + 4 * j)
                                          for j in range(12)))
        self.emit("  culler %s" % bytes(e.mem[CULLER:CULLER + 14 * 32]).hex())
        e.write(a, saved)

    def run(self, scenarios):
        self.dump_table()
        for n, sc in enumerate(scenarios):
            self.sc = sc
            if isinstance(sc, Part):
                self.part(n, sc)
            else:
                self.build(n, sc)
        self.dump_table()
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="carrenderinfo_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def encode(scenarios):
    lines = []
    for s in scenarios:
        lines += s.lines()
    return NL.join(lines) + NL


diff = pcc.diff


# ============================================================ the mutations

MUTATIONS = [
    ("cs-skin", CRC, "    c->pRideInfo->SkinNumber = (int8_t)skin;" + NL, ""),
    ("cs-ride", CRC,
     "    carrenderinfo_switch_skin(c->pRenderInfo, c->pRideInfo);",
     "    carrenderinfo_switch_skin(c->pRenderInfo, c->pRenderInfo->pRideInfo);"),
    ("cs-update", CRC,
     "    carrenderinfo_update_skin_textures(c->pRenderInfo);" + NL + "}",
     "}"),
    ("cs-order", CRC,
     "    carrenderinfo_switch_skin(c->pRenderInfo, c->pRideInfo);" + NL
     + "    carrenderinfo_update_skin_textures(c->pRenderInfo);",
     "    carrenderinfo_update_skin_textures(c->pRenderInfo);" + NL
     + "    carrenderinfo_switch_skin(c->pRenderInfo, c->pRideInfo);"),
    ("ust-skin1", CRC, "&ri->SkinReplacementTextureTable[1]);",
     "&ri->SkinReplacementTextureTable[0]);"),
    ("ust-skin0", CRC, "&ri->SkinReplacementTextureTable[0]);",
     "&ri->SkinReplacementTextureTable[1]);"),
    ("ust-dmg0", CRC, "ri, &ri->DamageableSkinReplacementTextureTable[0]);",
     "ri, &ri->DamageableSkinReplacementTextureTable[2]);"),
    ("ust-dmg1", CRC, "ri, &ri->DamageableSkinReplacementTextureTable[1]);",
     "ri, &ri->DamageableSkinReplacementTextureTable[0]);"),
    ("ust-tire", CRC, "&ri->TireReplacementTextureTable[0]);",
     "&ri->TireReplacementTextureTable[1]);"),
    ("uti-hash", CRC, "get_texture_info(t->NewNameHash, 1, 0);",
     "get_texture_info(t->OldNameHash, 1, 0);"),
    ("uti-dflt", CRC, "get_texture_info(t->NewNameHash, 1, 0);",
     "get_texture_info(t->NewNameHash, 0, 0);"),
    ("uti-inc", CRC, "get_texture_info(t->NewNameHash, 1, 0);",
     "get_texture_info(t->NewNameHash, 1, 1);"),
    # the tables
    ("flare-dir-row7", CRC, "{ 0.95f,  0.0f, 0.0f }", "{ 0.9f,  0.0f, 0.0f }"),
    ("flare-dir-row1", CRC, "{  1.0f,  0.0f, 0.0f }, { -1.0f, 0.0f, 0.0f },",
     "{  1.0f,  0.0f, 0.0f }, { 1.0f, 0.0f, 0.0f },"),
    ("win-hash-damage0", CRC, "0x0a155545u,    // WINDOW_DAMAGE0",
     "0x0a155546u,    // WINDOW_DAMAGE0"),
    ("light-bit-brake", CRC, "kBrokenLightBits[5] = { 1, 2, 4, 8, 16 };",
     "kBrokenLightBits[5] = { 1, 2, 4, 8, 32 };"),
    ("cull-rr-plane", CRC, "{ 0.447214f, 0.0f, 0.335f, 0.0f } }," + NL
     + "      { 0.1f, 0.0f, 0.05f, 0.0f } }," + NL
     + "    { CULLABLE_CAR_PART_TIRE_RL",
     "{ 0.447214f, 0.0f, 0.33f, 0.0f } }," + NL
     + "      { 0.1f, 0.0f, 0.05f, 0.0f } }," + NL
     + "    { CULLABLE_CAR_PART_TIRE_RL"),
    ("cull-under-planes", CRC, '"CULLABLE_CAR_PART_UNDERNEATH", 1, 2,',
     '"CULLABLE_CAR_PART_UNDERNEATH", 1, 1,'),
    ("cull-fl-extra", CRC, "{ -1.0f, 0.0f, 2.0f, 0.0f } }," + NL
     + "      { 0.1f, 0.0f, 0.05f, 0.0f } }," + NL
     + "    { CULLABLE_CAR_PART_TIRE_FR",
     "{ -1.0f, 0.0f, 2.0f, 0.0f } }," + NL
     + "      { 0.1f, 0.0f, 0.06f, 0.0f } }," + NL
     + "    { CULLABLE_CAR_PART_TIRE_FR"),
    ("carfx-order", CRC, '"CARFX_DAM_ENGINE", "CARFX_BLOWN_TIRE",',
     '"CARFX_BLOWN_TIRE", "CARFX_DAM_ENGINE",'),

    # the lists
    ("slist-link", CRC, "    l->Tail->next = n;" + NL, ""),
    ("slist-end", CRC, "n->next = (bSNode *)(void *)l;", "n->next = NULL;"),
    ("pos-y", CRC, "p->Y = y;", "p->Y = x;"),
    ("node-tail-next", CRC, "    tail->next = n;" + NL, "    list->next = n;" + NL),

    # InitPart
    ("part-threshold", CRC, "if (0.01f < fabsf(1.0f - sqrtf(d))) {",
     "if (0.1f < fabsf(1.0f - sqrtf(d))) {"),
    ("part-no-scale-y", CRC, "            p->y *= s;" + NL, ""),
    ("part-w", CRC, "            p->w *= s;" + NL, ""),
    ("part-point", CRC, "culler[idx].Point = *point;", "(void)point;"),

    # SwitchSkin
    ("skin-ride", CRC, "    ri->pRideInfo = ride;" + NL
     + "    cartypeinfo_get_used_car_texture_info(",
     "    cartypeinfo_get_used_car_texture_info("),
    ("skin-front-end", CRC,
     "cartypeinfo_get_used_car_texture_info(&ri->UsedTextureInfos, ride, 0);",
     "cartypeinfo_get_used_car_texture_info(&ri->UsedTextureInfos, ride, 1);"),
    ("skin-tire0", CRC,
     "ri->TireReplacementTextureTable[0].OldNameHash = u->MappedSkinHash;",
     "ri->TireReplacementTextureTable[0].OldNameHash = u->MappedSkinBHash;"),
    ("skin-dmg1-new", CRC, "        u->ReplaceSkinBHash;" + NL
     + "    ri->SkinReplacementTextureTable[0]",
     "        u->ReplaceSkinHash;" + NL
     + "    ri->SkinReplacementTextureTable[0]"),
    ("skin-skin1-new", CRC,
     "ri->SkinReplacementTextureTable[1].NewNameHash = u->ReplaceSkinBHash;",
     "ri->SkinReplacementTextureTable[1].NewNameHash = u->ReplaceSkinHash;"),

    # the damage textures
    ("dmg-level-shift", CRC, ">> (2 * item)) & 3;", ">> item) & 3;"),
    ("dmg-level-none", CRC, "ri->pCar->pCarDamage == NULL)" + NL
     + "        return 0;", "ri->pCar->pCarDamage == NULL)" + NL
     + "        return 1;"),
    ("win-item", CRC, "kWindowDamageHashes[item_damage_level(ri, 8 + i)]",
     "kWindowDamageHashes[item_damage_level(ri, 7 + i)]"),
    ("lamp-reset", CRC, "    ri->BrokenLightFlags = 0;" + NL, ""),
    ("lamp-threshold", CRC, "if (item_damage_level(ri, 4 + i) < 2) {",
     "if (item_damage_level(ri, 4 + i) < 3) {"),
    ("lamp-whole", CRC, "t[8 + i].NewNameHash = t[8 + i].OldNameHash;",
     "t[8 + i].NewNameHash = 0;"),
    ("lamp-split", CRC, "t[8 + i].NewNameHash = i < 2", "t[8 + i].NewNameHash = i < 1"),
    ("lamp-head-tex", CRC, "? ri->UsedTextureInfos.ReplaceHeadlightHash[2]",
     "? ri->UsedTextureInfos.ReplaceHeadlightHash[1]"),
    ("lamp-bit", CRC, "ri->BrokenLightFlags |= kBrokenLightBits[i];",
     "ri->BrokenLightFlags |= kBrokenLightBits[3 - i];"),
    ("lamp-both-brakes", CRC,
     "        && (ri->BrokenLightFlags & kBrokenLightBits[3]))",
     "        || (ri->BrokenLightFlags & kBrokenLightBits[3]))"),
    ("reconnect-body2", CRC, "    emodel_reconnect_texture_table(&ri->Body[2]);"
     + NL, ""),

    # the flares
    ("flare-dir-byte", CRC, "dir = (m->Param >> 8) & 0xff;",
     "dir = m->Param & 0xff;"),
    ("flare-dir-limit", CRC, "if (dir < NUM_FLARE_DIRECTIONS) {",
     "if (dir < 7) {"),
    ("flare-head-type", CRC, "case H_FLARE_HEADLIGHT_LEFT:     type = 0; break;",
     "case H_FLARE_HEADLIGHT_LEFT:     type = 1; break;"),
    ("flare-middle", CRC, "        case H_FLARE_BRAKELIGHT_MIDDLE:  type = 1; break;",
     "        case H_FLARE_BRAKELIGHT_MIDDLE:  type = 2; break;"),
    ("flare-reverse", CRC, "case H_FLARE_REVERSELIGHT_LEFT:  type = 2; break;",
     "case H_FLARE_REVERSELIGHT_LEFT:  type = 3; break;"),
    ("flare-red-flags", CRC, "type = 4; flags = 1;", "type = 4; flags = 0;"),
    ("flare-blue-type", CRC, "type = 5; flags = 1;", "type = 4; flags = 1;"),
    ("flare-white-flags", CRC, "case H_COPLIGHTWHITE:            type = 6; break;",
     "case H_COPLIGHTWHITE:            type = 6; flags = 1; break;"),
    ("flare-headlight", CRC, "case H_HEADLIGHT_RIGHT:          type = 7; break;",
     "case H_HEADLIGHT_RIGHT:          type = 8; break;"),
    ("flare-enabled", CRC, "f->Enabled = 1;", "f->Enabled = 0;"),
    ("flare-hash", CRC, "f->NameHash = m->NameHash;", "f->NameHash = 0;"),
    ("flare-pivot", CRC, "f->PositionY = m->Position[1] - ri->BodyPivot.y;",
     "f->PositionY = m->Position[1];"),
    ("flare-pad", CRC, "f->pad1 = 0.0f;", "f->pad1 = 1.0f;"),
    ("flare-dir-z", CRC, "f->DirectionZ = kFlareDirections[dir][2];",
     "f->DirectionZ = kFlareDirections[dir][1];"),

    # the constructor
    ("ctor-emitter-prev", CRC,
     "ri->EmitterList[i].next = ri->EmitterList[i].prev = &ri->EmitterList[i];",
     "ri->EmitterList[i].next = &ri->EmitterList[i];"),
    ("ctor-culler-zero", CRC,
     "    memset(ri->PartCuller, 0, sizeof ri->PartCuller);" + NL, ""),
    ("ctor-alpha", CRC, "    ri->AlphaOverridden = 0;" + NL
     + "    ri->pRideInfo = ride;", "    ri->AlphaOverridden = 1;" + NL
     + "    ri->pRideInfo = ride;"),
    ("ctor-timebase", CRC, "bRandomI(8, &bDefaultSeed)", "bRandomI(16, &bDefaultSeed)"),
    ("ctor-skin-default", CRC,
     "cartypeinfo_get_skin_info(ride->Type, ride->SkinNumber, 1);",
     "cartypeinfo_get_skin_info(ride->Type, ride->SkinNumber, 0);"),
    ("ctor-dmg-window", CRC, "t[5].OldNameHash = H_WINDOW_LEFT_REAR;",
     "t[5].OldNameHash = H_WINDOW_LEFT_FRONT;"),
    ("ctor-dmg-lights", CRC, "t[8 + i].OldNameHash = u->MappedLightHash[i];",
     "t[8 + i].OldNameHash = u->MappedLightHash[i + 1];"),
    ("ctor-dash-new", CRC,
     "ri->DashReplacementTextureTable[0].NewNameHash = u->ReplaceDashSkinHash;",
     "ri->DashReplacementTextureTable[0].NewNameHash = u->MappedDashSkinHash;"),
    ("ctor-blur-new", CRC,
     "ri->TireReplacementTextureTable[2].NewNameHash = u->ReplaceTireBlurHash;",
     "ri->TireReplacementTextureTable[2].NewNameHash = u->MappedTireBlurHash;"),
    ("ctor-light-material", CRC,
     "ri->pCarSkinLightMaterial = get_light_material(light_material);",
     "ri->pCarSkinLightMaterial = get_light_material(0);"),
    ("ctor-traffic-letter", CRC, "letter = i == 0 ? 'A' : 'A' + i - 1;",
     "letter = 'A' + i;"),
    ("ctor-dent-bodies", CRC, "            && i < 2)", "            && i < 3)"),
    ("ctor-dent-instance", CRC,
     "if (ri->pRideInfo->CanBeVertexDamaged && ri->pRideInfo->InstanceIndex"
     + NL + "            && i < 2)",
     "if (ri->pRideInfo->CanBeVertexDamaged" + NL + "            && i < 2)"),
    ("ctor-rename-traffic", CRC, "if (i >= 2 && !traffic)", "if (i >= 2)"),
    ("ctor-rename-args", CRC,
     "emodel_rename_texture(m, u->MappedSkinHash, u->MappedSkinBHash);",
     "emodel_rename_texture(m, u->MappedSkinBHash, u->MappedSkinHash);"),
    ("ctor-dmg-count", CRC, "m, ri->DamageableSkinReplacementTextureTable, 12,",
     "m, ri->DamageableSkinReplacementTextureTable, 11,"),
    ("ctor-body3-skin", CRC, "        if (i < 3)" + NL
     + "            emodel_attach_replacement_texture_table(",
     "        if (i < 4)" + NL
     + "            emodel_attach_replacement_texture_table("),
    ("ctor-tire-traffic", CRC, "        rc = rb;" + NL, ""),
    ("ctor-tire-name", CRC, 'rb = hashf(buf, "%s_TIRE_REAR_B", name);',
     'rb = hashf(buf, "%s_TIRE_REAR_A", name);'),
    ("ctor-tire-fallback", CRC, "    fall_back(&ri->Tires[2][1], fc);" + NL, ""),
    ("ctor-tire-rear-inst", CRC,
     "&ri->Tires[i][1], ri->TireReplacementTextureTable, 3, 3 + i);",
     "&ri->Tires[i][1], ri->TireReplacementTextureTable, 3, i);"),
    ("ctor-tire-rear-lm", CRC,
     "emodel_replace_light_material(&ri->Tires[i][1], H_CARSKIN,",
     "emodel_replace_light_material(&ri->Tires[i][0], H_CARSKIN,"),
    ("ctor-brake-fallback", CRC, "    fall_back(&ri->Brakes[1], fa);" + NL, ""),
    ("ctor-wiper-inst", CRC,
     "&ri->Wipers[1], ri->SkinReplacementTextureTable, 2, skin_instance++);",
     "&ri->Wipers[1], ri->SkinReplacementTextureTable, 2, skin_instance);"),
    ("ctor-wiper-lm", CRC,
     "emodel_replace_light_material(&ri->Wipers[1], H_CARSKIN, light_material);",
     "emodel_replace_light_material(&ri->Wipers[1], H_CARSKIN, 0);"),
    ("ctor-mirror-lm", CRC,
     "emodel_replace_light_material(&ri->SideMirrors[1], H_CARSKIN,",
     "emodel_replace_light_material(&ri->SideMirrors[0], H_CARSKIN,"),
    ("ctor-mirror-name", CRC, 'ra = hashf(buf, "%s_SIDE_MIRROR_RIGHT", name);',
     'ra = hashf(buf, "%s_SIDE_MIRROR_LEFT", name);'),
    ("ctor-plate-lm", CRC,
     "emodel_replace_light_material(&ri->LicensePlates[1], H_CARSKIN,",
     "emodel_replace_light_material(&ri->LicensePlates[0], H_CARSKIN,"),
    ("ctor-scuffs-inst", CRC, "    if (ri->pRideInfo->InstanceIndex)" + NL
     + "        init_model(&ri->Scuffs,", "    if (0)" + NL
     + "        init_model(&ri->Scuffs,"),
    ("ctor-dash-window", CRC, 'fc = hashf(buf, "%s_DASH_WINDOW", name);',
     'fc = hashf(buf, "%s_DASH_WIN", name);'),
    ("ctor-dash-wheel-inst", CRC,
     "&ri->DashboardWheel, ri->DashReplacementTextureTable, 1, 1);",
     "&ri->DashboardWheel, ri->DashReplacementTextureTable, 1, 0);"),
    ("ctor-dash-window-lm", CRC,
     "emodel_replace_light_material(&ri->DashboardWindow, H_CARSKIN,",
     "emodel_replace_light_material(&ri->DashboardWheel, H_CARSKIN,"),
    ("ctor-blur-shared", CRC, "init_model(&ri->TireBlur[1], fa);",
     "init_model(&ri->TireBlur[1], 0);"),
    ("ctor-blur-rear", CRC, 'fb = hashf(buf, "%s_WHEEL_BLUR_R", name);',
     'fb = hashf(buf, "%s_WHEEL_BLUR_F", name);'),
    ("ctor-blur-inst", CRC,
     "&ri->TireBlur[1], ri->TireReplacementTextureTable, 3, 7);",
     "&ri->TireBlur[1], ri->TireReplacementTextureTable, 3, 6);"),
    ("ctor-shadow-fe", CRC,
     "&& gTrackFlowGameFlow->current == BGF_IN_FRONTEND;",
     "&& gTrackFlowGameFlow->current != BGF_IN_FRONTEND;"),
    ("ctor-shadow-order", CRC, "RenderingOrder = fe ? 5 : 3;",
     "RenderingOrder = fe ? 5 : 4;"),
    ("ctor-shadow-ramp", CRC, "get_texture_info(H_SHADOWRAMP, 0, 0);",
     "get_texture_info(H_SHADOWRAMP, 1, 0);"),
    ("ctor-driver", CRC, "gCarAssignAnimatedDriverFn(ri->pCar, name);",
     "(void)0;"),
    ("ctor-alevel", CRC, "gBodyDamageSetALevelInfoFn(bd, buf);", "(void)bd;"),
    ("ctor-dent-models", CRC, "                for (i = 0; i < 3; i++) {",
     "                for (i = 0; i < 2; i++) {"),
    ("ctor-scuffs-flag", CRC, "gBodyDamageAddModelFn(bd, &ri->Scuffs, buf, 1);",
     "gBodyDamageAddModelFn(bd, &ri->Scuffs, buf, 0);"),
    ("ctor-pivot-y", CRC,
     "ri->BodyPivot.y = solid != NULL ? solid->PivotMatrix.v3.y : 0.0f;",
     "ri->BodyPivot.y = solid != NULL ? solid->PivotMatrix.v3.x : 0.0f;"),
    ("ctor-no-flares", CRC, "    carrenderinfo_create_car_light_flares(ri);"
     + NL + NL + "    // The box", "    // The box"),
    ("ctor-box-ri-init", CRC,
     "    bInitializeBoundingBox3(&ri->AABBMin, &ri->AABBMax);" + NL, ""),
    ("ctor-box-mirror1", CRC,
     "emodel_get_bounding_box(&ri->SideMirrors[1], &box_min, &box_max);",
     "(void)0;"),
    ("ctor-box-pad", CRC, "ri->AABBMax.y += 0.1f;", "ri->AABBMax.y += 0.2f;"),
    ("ctor-wheel-w", CRC, "v->w = w->Radius;", "v->w = 0.0f;"),
    ("ctor-mid-w", CRC, "d->w = (a->w + b->w) * 0.5f;", "d->w = a->w;"),
    ("ctor-blur-left", CRC, "mid4(&t4, &w[0], &w[3]);", "mid4(&t4, &w[0], &w[2]);"),
    ("ctor-side-rear", CRC, "CULLABLE_CAR_PART_SIDE_REAR, &w[2]);",
     "CULLABLE_CAR_PART_SIDE_REAR, &w[3]);"),
    ("ctor-under", CRC, "mid4(&c, &t4, &t5);", "mid4(&c, &t4, &t4);"),
    ("ctor-normal-a", CRC, "a.y = w[0].y - w[1].y;", "a.y = w[1].y - w[0].y;"),
    ("ctor-normal-b", CRC, "b.x = w[1].x - w[2].x;", "b.x = w[1].x - w[3].x;"),
    ("ctor-normal-cross", CRC, "n.y = a.z * b.x - b.z * a.x;",
     "n.y = b.z * a.x - a.z * b.x;"),
    ("ctor-normal-w", CRC, "n.w = a.w;", "n.w = b.w;"),
    ("ctor-normal-scale", CRC, "    n.z *= s;" + NL, ""),
    ("ctor-shadow-radius", CRC, "c.z += n.z * ct->Wheels[0].Radius;",
     "c.z += n.z * ct->Wheels[1].Radius;"),
    ("ctor-shadow-w", CRC, "c.w += n.w * ct->Wheels[0].Radius;", "(void)0;"),

    # the destructor
    ("del-wait", CRC, "        gEWaitUntilRenderingDoneFn();", "        (void)0;"),
    ("del-driver", CRC, "gCarUnAssignAnimatedDriverFn(ri->pCar);", "(void)0;"),
    ("del-alpha-free", CRC, "        bFree(ri->pAlphaInfo);" + NL, ""),
    ("del-alpha-flag", CRC, "        ri->AlphaOverridden = 0;" + NL + "    }", "    }"),
    ("del-pos-tail", CRC, "            if (l->Tail == n)" + NL
     + "                l->Tail = sentinel;" + NL, ""),
    ("del-pos-free", CRC, "bSlotFree(CarEmitterPositionSlotPool, n);", "(void)n;"),
    ("del-acid-flags", CRC, "gAcidEmitterDeleteFn(n, 3);", "gAcidEmitterDeleteFn(n, 1);"),
    ("del-flare-free", CRC, "bSlotFree(eLightFlareSlotPool, n);", "(void)n;"),
    ("del-model-order", CRC, "    emodel_delete(&ri->DashboardWheel, 2);" + NL
     + "    emodel_delete(&ri->DashboardWindow, 2);",
     "    emodel_delete(&ri->DashboardWindow, 2);" + NL
     + "    emodel_delete(&ri->DashboardWheel, 2);"),
    ("del-bodies", CRC, "    delete_models(ri->Body, 4, 0);" + NL, ""),
    ("del-free-flag", CRC, "    if (flags & 1)" + NL + "        bFree(ri);",
     "    if (flags & 2)" + NL + "        bFree(ri);"),

    # InitRenderInfo
    ("iri-align", CRC, 'bMalloc(sizeof(CarRenderInfo), "CarRenderInfo", 0, 16)',
     'bMalloc(sizeof(CarRenderInfo), "CarRenderInfo", 0, 0)'),
    ("iri-set", CRC, "    c->pRenderInfo = ri;" + NL, ""),
    ("iri-front", CRC, "(w[0].PositionY + w[1].PositionY) * 0.5f,",
     "(w[0].PositionY + w[2].PositionY) * 0.5f,"),
    ("iri-rear", CRC, "(w[3].PositionX + w[2].PositionX) * 0.5f,",
     "(w[3].PositionX + w[1].PositionX) * 0.5f,"),
    ("iri-right", CRC, "(w[1].PositionZ + w[2].PositionZ) * 0.5f);",
     "(w[1].PositionZ + w[2].PositionZ) * 0.25f);"),
    ("iri-wheels", CRC, "new_emitter_position(&ri->EmitterPositionList[5 + i],",
     "new_emitter_position(&ri->EmitterPositionList[4 + i],"),
    ("iri-plate-rear", CRC, "case H_LICENSE_PLATE_REAR:  l0 = 27; break;",
     "case H_LICENSE_PLATE_REAR:  l0 = 26; break;"),
    ("iri-engine", CRC, "case H_ENGINE:              l0 = 9;  break;",
     "case H_ENGINE:              l0 = 11; break;"),
    ("iri-exhaust-left", CRC, "        case H_EXHAUST_LEFT:" + NL, ""),
    ("iri-window-rear", CRC, "case H_WINDOW_RIGHT_REAR:   l0 = 17; break;",
     "case H_WINDOW_RIGHT_REAR:   l0 = 16; break;"),
    ("iri-headlight-pair", CRC, "case H_HEADLIGHT_RIGHT:     l0 = 18; l1 = 21; break;",
     "case H_HEADLIGHT_RIGHT:     l0 = 18; l1 = 20; break;"),
    ("iri-brakelight", CRC, "case H_BRAKELIGHT_LEFT:     l0 = 19; l1 = 22; break;",
     "case H_BRAKELIGHT_LEFT:     l0 = 18; l1 = 22; break;"),
    ("iri-mirror", CRC, "case H_SIDE_MIRROR_RIGHT:   l0 = 25; break;",
     "case H_SIDE_MIRROR_RIGHT:   l0 = 24; break;"),
    ("iri-pivot", CRC, "z = m->Position[2] - ri->BodyPivot.z;",
     "z = m->Position[2];"),
    ("iri-pair", CRC, "        if (l1 >= 0)" + NL, "        if (0)" + NL),
    ("iri-afx-hash", CRC, "bchunk_hash(kCarFxNames[i]));",
     "bchunk_hash(kCarFxNames[0]));"),
    ("iri-test-ri", CRC, "get_texture_info(TEST_RENDER_INFO_HASH, 1, 0);",
     "get_texture_info(TEST_RENDER_INFO_HASH, 0, 0);"),

    # the eModel methods
    ("em-attach-inst", EMC, "m->ReplacementTextureInstanceIndex = (uint8_t)instance;",
     "m->ReplacementTextureInstanceIndex = 0;"),
    ("em-attach-count", EMC, "m->NumReplacementTextures = (uint8_t)count;",
     "m->NumReplacementTextures = (uint8_t)(count - 1);"),
    ("em-attach-apply", EMC, "    emodel_apply_replacement_texture_table(m);"
     + NL + "    if (gFixStripSTsFn", "    if (gFixStripSTsFn"),
    ("em-attach-fix", EMC, "    emodel_apply_replacement_texture_table(m);"
     + NL + "    if (gFixStripSTsFn != NULL)" + NL
     + "        gFixStripSTsFn((eSolid *)m->Solid);",
     "    emodel_apply_replacement_texture_table(m);"),
    ("em-attach-guard", EMC, "    if (m->Solid == NULL)" + NL + "        return;"
     + NL + "    // Reconnecting", "    // Reconnecting"),
    ("em-rename-once", EMC, "get_texture_info(new_hash, 1, 0);" + NL
     + "            return 1;", "get_texture_info(new_hash, 1, 0);"),
    ("em-rename-lookup", EMC, "table[k].pTextureInfo = get_texture_info(new_hash, 1, 0);",
     "table[k].pTextureInfo = get_texture_info(new_hash, 0, 0);"),
    ("em-rename-hash", EMC, "table[k].NameHash = new_hash;", "(void)0;"),
    ("em-lm-match", EMC, "if (e->NameHash == old_hash)" + NL
     + "            e->LightMaterial = material;", "if (e->NameHash != old_hash)"
     + NL + "            e->LightMaterial = material;"),
    ("em-lm-lookup", EMC, "get_light_material(new_hash));",
     "get_light_material(old_hash));"),
    ("em-box-max-y", EMC, "mx->y = s->AABBMax.y;", "mx->y = s->AABBMin.y;"),
    ("em-box-min-z", EMC, "mn->z = s->AABBMin.z;", "mn->z = s->AABBMax.z;"),

    # eFindPositionMarker, by type as CarRenderInfo asks
    ("ep-from-prev", EPC, "n = prev != NULL ? prev->Node.next : PositionMarkerList.next;",
     "n = PositionMarkerList.next;"),
    ("ep-type", EPC, "} else if (m->TypeHash == type_hash) {",
     "} else if (m->TypeHash != type_hash) {"),
    ("ep-none", EPC, "    if (name_hash == 0 && type_hash == 0)" + NL
     + "        return NULL;" + NL, ""),

    # the skins and the used textures
    ("ct-skin-match", CTC,
     "if (s->TheCarType == car_type && s->SkinNumber == skin_number)",
     "if (s->TheCarType == car_type)"),
    ("ct-skin-default", CTC, "return use_default ? SkinInfoTable : NULL;",
     "return NULL;"),
    ("ct-uct-clear", CTC, "    memset(u, 0, sizeof *u);" + NL, ""),
    ("ct-uct-mapped-b", CTC, 'u->MappedSkinBHash = name_hash("%s_SKIN1B", name, 0);',
     'u->MappedSkinBHash = name_hash("%s_SKIN1", name, 0);'),
    ("ct-uct-skin-b", CTC, 'h = name_hash("%s_SKIN%dB", name, skin);',
     'h = name_hash("%s_SKIN%d", name, skin);'),
    ("ct-uct-dash", CTC, "    if (ride->HasDash) {", "    if (!ride->HasDash) {"),
    ("ct-uct-light1", CTC,
     'u->MappedLightHash[1] = name_hash("%s_HEADLIGHT_RIGHT", name, 0);',
     'u->MappedLightHash[1] = name_hash("%s_HEADLIGHT_LEFT", name, 0);'),
    ("ct-uct-head-dmg", CTC,
     'u->ReplaceHeadlightHash[2] = name_hash("%s_HEADLIGHT_DAMAGE0", name, 0);',
     'u->ReplaceHeadlightHash[2] = name_hash("%s_HEADLIGHT_ON", name, 0);'),
    ("ct-uct-brake-dmg", CTC,
     'u->ReplaceBrakelightHash[2] = name_hash("%s_BRAKELIGHT_DAMAGE0", name, 0);',
     'u->ReplaceBrakelightHash[2] = name_hash("%s_BRAKELIGHT", name, 0);'),
    ("ct-uct-reverse", CTC,
     'u->ReplaceReverselightHash[2] = name_hash("%s_REVERSELIGHT", name, 0);',
     'u->ReplaceReverselightHash[2] = name_hash("%s_REVERSELIGHT_ON", name, 0);'),
    ("ct-uct-shadow", CTC, 'h = name_hash(front_end ? "%s_SHADOWFE" : "%s_SHADOWIG", name, 0);',
     'h = name_hash("%s_SHADOWFE", name, 0);'),
    ("ct-uct-tire-own", CTC,
     'u->ReplaceTireHash = name_hash("%s_TIRE", ct->CarTypeName, 0);',
     'u->ReplaceTireHash = name_hash("%s_TIRE", name, 0);'),
    ("ct-uct-blur-own", CTC,
     'u->ReplaceTireBlurHash = name_hash("%s_WHEEL_BLUR", ct->CarTypeName, 0);',
     'u->ReplaceTireBlurHash = name_hash("%s_WHEEL_BLUR", name, 0);'),
    ("ct-uct-plate", CTC, "    u->MappedLicensePlateHash = h;" + NL, ""),
    ("ct-uct-count", CTC, "u->NumTexturesToLoad = n;", "u->NumTexturesToLoad = n - 1;"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # ReconnectTextureTable has applied the table already, and applying it
    # again writes the same pointers.
    "em-attach-apply": "the second apply writes what the first did",
    # CarRenderInfo only asks by a model's type hash, which is a
    # bStringHash of a name and never 0.
    "ep-none": "no caller here passes two zero hashes",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        edits = before if isinstance(before, list) else [(before, after)]
        new, bad = text, None
        for b, a in edits:
            probe = b.replace(NL, "\r\n") if crlf else b
            repl = a.replace(NL, "\r\n") if crlf else a
            if new.count(probe) != 1:
                bad = "NOT FOUND" if not new.count(probe) else "NOT UNIQUE"
                break
            new = new.replace(probe, repl, 1)
        if bad:
            missing.append(name)
            print("  %-44s PATTERN %s" % (name, bad))
            continue
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    sc = script()
    lines = model(sc)
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
    print("%d scenarios, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
