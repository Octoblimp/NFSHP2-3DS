#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carrender.c (CarRenderInfo::Render and
what it calls of Car.obj's own) against the retail image itself, run in
mipsemu.

The model is the image: Render (0x00120ef8) runs as shipped, with
UpdateLightStateTextures, CalculateTireBlur, the part culler's pass,
sh_Setup, convex_hull, smooth_shadow_corners, ch2d, make_chain, cmpl and
cmph, and everything else it calls that is pure: eMulMatrix, the two
eMulVectors, eIdentity, eRotateZ and eSin, bIdentity, bInvertMatrix,
bMulMatrix and its vector form, bBoundingBoxIsInside, bSinCos, bATan,
qsort, memset, bMemCpy, eModel's GetRigidAnimation, GetPivotMatrix and
ReplaceLightMaterial, eSolid::GetBoundingBox and the damage's item level
(0x00124d38). eMathInit and the two static constructors that make the
(0, 0, 0, 1) the vector forms add onto run first.

Every other callee is a stub that prints its name and its arguments, and
the harness's stand-ins print the same: GetPixelSize, eGetCurrentViewMode,
ClassifyAABB, BiasMatrixForZSorting (which moves the matrix, so what it
touched shows later), elSetupLightContext (which writes a count, a word
and a sunlight intensity into the context), GetElevation (a plane, a
normal, and a found that misses on a pattern), GetSkinInfo,
GetVisibleTotalDamage, eSolid::ReplaceLightMaterial,
eModel::ReconnectTextureTable, eModel::Render, eRenderLightFlare, the
animated driver's pair, and the ten strip builders (Begin answers from a
bit pattern).

A pointer prints by what it is -- the frame buffer's as F+offset, the
world's by name, the hull statics by index -- and a vertex handed to a
strip by its xyz, since the stacks are not the same. After each render
the frame's position and failure count, the tweakables Render writes, the
light direction's xyz (its w is the stack's), the ground point and normal,
the culler's states, the lamp textures, the wipers' start times and the
hull arrays are printed.

Where the two may differ by design:

- a collision body of more than 64 points, which retail casts into the
  arrays past hullVertArray1's end and the port stops at 64. No scenario
  has one;
- a camera on the car's origin, where Render's bias is 0 / 0, a NaN whose
  bits the two need not agree on. No scenario has one.

    python tools/carrender_check.py
    python tools/carrender_check.py --mutate [--only a,b]
    python tools/carrender_check.py --dump out/carrender
"""
import argparse
import math
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
from mipsemu import M32, f32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/carrender_test.c"
CRC = "3DS Files/source/carrender.c"
SOURCES = [HARNESS, CRC] + ["3DS Files/source/" + f for f in (
    "emath.c", "bmatrix.c", "bmath.c", "bmathtab.c", "bvector.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
RENDER = 0x00120ef8
EMATH_INIT = 0x0011b138
EMATH_CTOR = 0x0011bf70           # 0x002dc400 = (0, 0, 0, 1)
BMATRIX_CTOR = 0x0025afa8         # 0x00320a60 = (0, 0, 0, 1)
CULL_INIT = 0x00124528            # the part culler's table

PIXEL = 0x00107600
VIEWMODE = 0x00107cd8
CLASSIFY = 0x0010ccb0
BIAS = 0x001074b8
SOLID_RLM = 0x0010c4b0
MODEL_RENDER = 0x0010dc80
RECONNECT = 0x0010c680
SKININFO = 0x00188180
ELSETUP = 0x00115978
FLARE = 0x001164f0
ELEV = 0x00152070
VISDMG = 0x001b50c8
DRV_RENDER = 0x001a9a30
DRV_QUEUED = 0x001a9fb8
STRIPS = [  # (address, name, kind)
    (0x00110488, "eb", "begin"), (0x001107d0, "ev", "vertex"),
    (0x001107e0, "ec", "colour"), (0x001107f8, "euv", "uv"),
    (0x00110608, "ee", "end"),
    (0x00110848, "xb", "begin"), (0x001109f8, "xv", "vertex"),
    (0x00110a40, "xc", "colour"), (0x00110a68, "xuv", "uv"),
    (0x00110878, "xe", "end"),
]

CAR_RENDER_MATRIX = 0x002e0270
HACK_MAN = 0x002d70f0
CULL_TABLE = 0x002dfd40
CS_LIGHT = 0x00332920
HULL_NORMAL = 0x00332930
HULL_ORIGIN = 0x00332940
HULL3 = 0x00332950
HULL2 = 0x00333550
HULL1 = 0x00333950
HULLP = 0x00333d50

G_ENV = GP - 25040
G_PQLM = GP - 23712
G_QLM = GP - 24224
G_NORM = GP - 23768
G_FHEAD = GP - 23760
G_FBRAKE = GP - 23756
G_FREV = GP - 23752
G_FCOP = GP - 23748
G_FDRV = GP - 23744
G_FCLOD = GP - 23696
G_FTLOD = GP - 23692
G_EDGE = GP - 23764
G_CSEFE = GP - 23740
G_ONEOVERZ = GP - 13420
G_SUN = GP - 23584
G_TRACK = GP - 21952
G_FLOW = GP - 21420
G_WTF = GP - 19564
G_FPOS = GP - 19388
G_FEND = GP - 19384
G_FFAIL = GP - 19372
G_FAMT = GP - 19368

# The world's, in the model.
CAR = 0x01100000
CAR_SIZE = 2400
DMG = 0x01101000
RIDE = 0x01101200
DRVINFO = 0x01101300
CARDRV = 0x01101400
COLBODY = 0x01102000
POLY = 0x01102100
VERTS = 0x01103000
ANIM = 0x01104000
CTI = 0x01110000
CTI_SIZE = 1376
VIEW = 0x01120000
CAM = 0x01121000
WVM = 0x01122000
WSCM = 0x01122100
POS = 0x01123000
BODYM = 0x01123100
TIREM = 0x01123200
BRAKEM = 0x01123400
SUN = 0x01124000
TRACK = 0x01125000
SKINLM = 0x01126000
SHADOW = 0x01126100
RAMP = 0x01126200
RI = 0x01200000
RI_SIZE = 2352
SOLIDS = 0x01210000
SOLID_STRIDE = 0x100
RIGID = 0x01218000
LFS = 0x01220000
FRAME = 0x01800000
FRAME_SIZE = 0x10000

PATTERN = 0xa5
STACK_FILL = 0x77

# The render info's models Render draws, by the port's names, and where
# retail has them.
MODELS = ([("Body%d" % i, 64 + 24 * i) for i in range(4)]
          + [("Tire%d%d" % (l, e), 160 + 48 * l + 24 * e)
             for l in range(3) for e in range(2)]
          + [("TireBlur%d" % i, 304 + 24 * i) for i in range(2)]
          + [("Brake%d" % i, 352 + 24 * i) for i in range(2)]
          + [("Wiper%d" % i, 400 + 24 * i) for i in range(2)]
          + [("Mirror%d" % i, 448 + 24 * i) for i in range(2)]
          + [("Plate%d" % i, 496 + 24 * i) for i in range(2)]
          + [("Scuffs", 544)])
NMODELS = len(MODELS)
ALL_SOLIDS = (1 << NMODELS) - 1

# The flares' names, and some that are none of them.
FLARE_HASHES = [0xacec665c, 0x4ae7f96f, 0x7efcf06f, 0x34970013, 0x5f09c5e2,
                0xbea9aee6, 0x944e5339, 0xa7e6ea53, 0xa532fc46, 0x1e4150b4,
                0xe662c161, 0xb4348dba]
OTHER_HASHES = [0x12345678, 0x00000000, 0xacec665d]


def em_f(w):
    return struct.unpack("<f", struct.pack("<I", w & M32))[0]


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def hexw(ws):
    return " ".join("%08x" % (w & M32) for w in ws)


# ============================================================ the scenarios


def ident():
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def rot(yaw, pitch=0.0, roll=0.0, t=(0.0, 0.0, 0.0), w=1.0):
    """Rows of R = Rz(yaw) Ry(pitch) Rx(roll), then a translation row."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    m = [[cy * cp, sy * cp, -sp],
         [cy * sp * sr - sy * cr, sy * sp * sr + cy * cr, cp * sr],
         [cy * sp * cr + sy * sr, sy * sp * cr - cy * sr, cp * cr]]
    out = []
    for r in m:
        out += [f32(x) for x in r] + [0.0]
    return out + [f32(t[0]), f32(t[1]), f32(t[2]), w]


class Sc(object):
    """One call of Render, and the world it sees."""

    def __init__(self, cull, **kw):
        self.flow = 6
        self.wtf = 1000
        self.sw = dict(env=1, pqlm=0, norm=0, fh=0, fb=0, fr=0, fc=0,
                       fdrv=0, fclod=-1, ftlod=-1, csefe=0.01, edge=1.1)
        self.track = 1              # TimeOfDay, or None
        self.sun = (-16384.0, 1200.0, 7000.0)
        self.frame = (0, FRAME_SIZE)
        self.crm = ident()
        self.cull = [list(c) for c in cull]
        self.pos = (10.0, -20.0, 1.5, 1.0)
        self.body = rot(0.3, 0.02, -0.01)
        self.tm = [rot(0.0, 0.5 * k, 0.0, (1.3 - 2.6 * (k >> 1), 0.78
                                           - 1.56 * ((k + 1) >> 1 & 1),
                                           0.32)) for k in range(4)]
        self.bm = [rot(0.1 * k, 0.0, 0.0, (1.3 - 2.6 * (k >> 1), 0.7, 0.3))
                   for k in range(4)]
        self.extra = 0
        self.forced = 0
        self.view_id = 1
        self.cam = (14.0, -23.0, 3.0, 1.0)
        self.wvm = [0.5 + 0.125 * k for k in range(16)]
        self.wscm = [1.0 - 0.0625 * k for k in range(16)]
        self.px = 150
        self.vm = 0
        self.cls = 1
        self.vd = 0.5
        self.queued = 0
        self.emask = 0xffffffff
        self.exmask = 0xffffffff
        self.sunl = [0.8]
        # the ground: base + x*ax + y*ay, found unless k % mod == off
        self.elev = (1.25, 0.0078125, -0.00390625, 0, 0,
                     (0.0625, -0.03125, 0.99, 0.0))
        self.car = dict(dtype=1, cd=(0x0400, 0.0), colbody=1, dmg=0,
                        anim=0, enabled=1, copl=0, headl=0, won=0, woff=0,
                        wstate=0, gear=2, nwheels=4,
                        wav=(10.0, 12.0, 14.0, 16.0),
                        spos=(10.0, -20.0, 1.5, 1.0))
        self.verts = box_verts(2.2, 0.9, 0.6)
        self.opentop = 0
        self.ctype = 3
        self.drvoff = (0.2, 0.4, 0.5, 0.0)
        self.wheels = [(1.3, 0.78, 0.32, 0.33), (1.3, -0.78, 0.32, 0.33),
                       (-1.35, -0.78, 0.32, 0.35), (-1.35, 0.78, 0.32, 0.35)]
        self.rtype = 5
        self.skin = 2
        self.aabb = ((-2.3, -1.0, -0.2, 0.0), (2.4, 1.0, 1.4, 0.0))
        self.solids = ALL_SOLIDS
        self.wanim = 3
        self.pivots = [rot(0.1, 0.0, 0.0, (0.5, 0.3, 1.0)),
                       rot(-0.1, 0.0, 0.0, (0.5, -0.3, 1.0))]
        self.rst = (0x1234, -2)
        self.shadow = 1
        self.ramp = 1
        self.skinlm = 1
        self.timebase = 3
        self.broken = 0
        self.hl = (0x11110000, 0x11110001, 0x11110002)
        self.bl = (0x22220000, 0x22220001, 0x22220002)
        self.dnew = (0x11110000, 0x11110000, 0x22220000, 0x22220000)
        self.points = [(0.1 * k, -0.05 * k, 0.3, 0.0) for k in range(14)]
        self.states = [(k, 2 * k, 1, 7) for k in range(14)]
        self.flares = list(FLARE_HASHES)
        for k, v in kw.items():
            if not hasattr(self, k):
                raise KeyError(k)
            setattr(self, k, v)

    def lines(self):
        s = self.sw
        f = [fb(x) for x in (s["csefe"], s["edge"])]
        out = ["S", "g %x %x %x %x %x %x %x %x %x %x %x %x %x %x" % (
            self.flow & M32, self.wtf & M32, s["env"], s["pqlm"], s["norm"],
            s["fh"], s["fb"], s["fr"], s["fc"], s["fdrv"], s["fclod"] & M32,
            s["ftlod"] & M32, f[0], f[1])]
        out.append("t %d %x" % (self.track is not None,
                                (self.track or 0) & 0xffff))
        out.append("u %d %s" % (self.sun is not None,
                                hexw(fb(x) for x in (self.sun or (0, 0, 0)))))
        out.append("f %x %x" % self.frame)
        out.append("m " + hexw(fb(x) for x in self.crm))
        for i, c in enumerate(self.cull):
            out.append("c %d %x %x %s" % (i, c[0] & M32, c[1] & M32,
                                          hexw(fb(x) for x in c[2:18])))
        out.append("a %s %s %s %s %x %x" % (
            hexw(fb(x) for x in self.pos), hexw(fb(x) for x in self.body),
            hexw(fb(x) for m in self.tm for x in m),
            hexw(fb(x) for m in self.bm for x in m), self.extra & M32,
            self.forced & M32))
        out.append("v %x %s %s %s" % (
            self.view_id & M32, hexw(fb(x) for x in self.cam),
            hexw(fb(x) for x in self.wvm), hexw(fb(x) for x in self.wscm)))
        out.append("r %x %x %x %08x %x %x %x %d %s" % (
            self.px & M32, self.vm & M32, self.cls & M32, fb(self.vd),
            self.queued & M32, self.emask, self.exmask, len(self.sunl),
            hexw(fb(x) for x in self.sunl)))
        e = self.elev
        out.append("e %s %x %x %s" % (hexw(fb(x) for x in e[:3]), e[3], e[4],
                                      hexw(fb(x) for x in e[5])))
        c = self.car
        if c is None:
            out.append("k 0")
        else:
            cd = c["cd"]
            out.append("k 1 %x %d %x %08x %d %d %x %d %x %x %x %x %x %x %x "
                       "%x %x %s %s" % (
                           c["dtype"] & M32, cd is not None,
                           (cd or (0, 0))[0] & 0xffff, fb((cd or (0, 0.0))[1]),
                           c["colbody"], c["dmg"] is not None,
                           (c["dmg"] or 0) & M32, c["anim"] is not None,
                           (c["anim"] or 0) & M32, c["enabled"] & M32,
                           c["copl"] & M32, c["headl"] & M32, c["won"] & M32,
                           c["woff"] & M32, c["wstate"] & M32,
                           c["gear"] & M32, c["nwheels"] & M32,
                           hexw(fb(x) for x in c["wav"]),
                           hexw(fb(x) for x in c["spos"])))
        out.append("x %d %s" % (len(self.verts), hexw(
            fb(x) for v in self.verts for x in v)))
        out.append("i %x %x %s %s" % (
            self.opentop & 0xff, self.ctype & M32,
            hexw(fb(x) for x in self.drvoff),
            hexw(fb(x) for w in self.wheels for x in w)))
        out.append("d %x %x" % (self.rtype & M32, self.skin & 0xff))
        out.append("o %s %s %x %x %s %s %x %x %x %x %x %x %x %s %s %s" % (
            hexw(fb(x) for x in self.aabb[0]),
            hexw(fb(x) for x in self.aabb[1]), self.solids, self.wanim,
            hexw(fb(x) for x in self.pivots[0]),
            hexw(fb(x) for x in self.pivots[1]),
            self.rst[0] & 0xffff, self.rst[1] & 0xffff, self.shadow,
            self.ramp, self.skinlm, self.timebase & M32, self.broken & M32,
            hexw(self.hl), hexw(self.bl), hexw(self.dnew)))
        for i in range(14):
            out.append("p %d %s %s" % (i, hexw(fb(x) for x in self.points[i]),
                                       hexw(self.states[i])))
        out.append("l %d %s" % (len(self.flares), hexw(self.flares)))
        out.append("G")
        return out


def box_verts(x, y, z, n=8, jitter=None):
    """A box's corners, and more points round its middle."""
    out = []
    for i in range(8):
        out.append(((x if i & 1 else -x), (y if i & 2 else -y),
                    (z if i & 4 else -z * 0.5)))
    rnd = jitter
    for i in range(n - 8):
        a = 2 * math.pi * i / max(1, n - 8)
        r = 1.0 if rnd is None else rnd.uniform(0.7, 1.0)
        out.append((x * r * math.cos(a), y * r * math.sin(a),
                    z * (0.5 - (i % 3) * 0.25)))
    return [tuple(f32(c) for c in v) for v in out[:n]]


# Culler entries by kind: always seen, never seen, one plane either side.
SEEN = [0, 0] + [0.0] * 16
NEVER = [1, 1, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
         -1e6, 0.0, 0.0, 0.0]


def script(table):
    rnd = random.Random(0x5ade)
    sc = []

    def mk(**kw):
        return Sc(kw.pop("cull", table), **kw)

    def cull_with(**parts):
        t = [list(c) for c in table]
        for k, v in parts.items():
            t[int(k[1:])] = list(v)
        return t

    base = mk()
    sc.append(base)
    # The early outs: too small, each frame malloc, the box off screen.
    for px in (3, 4, 5, -1):
        sc.append(mk(px=px))
    sc.append(mk(px=5, vm=3))
    sc.append(mk(px=6, vm=3))
    # The frame's position is always a quadword's: retail's lq and sq drop
    # an address's low four bits.
    for left in (0, 1, 287, 288, 289, 352, 353, 416, 417, 480, 481, 544,
                 545, 1632, 1633, 1696, 1697, 2849, 2913):
        sc.append(mk(frame=(FRAME_SIZE - 0x1000, FRAME_SIZE - 0x1000 + left)))
        sc.append(mk(frame=(FRAME_SIZE - 0x1000, FRAME_SIZE - 0x1000 + left),
                     car=dict(base.car, anim=0, wstate=1), px=400))
    for size in (0, 287, 288, 289, 352, 353, 481):
        sc.append(mk(frame=(0, size)))
    sc.append(mk(cls=0))
    sc.append(mk(cls=2))
    # The camera inside the car, and just outside it.
    for cam in ((10.1, -20.1, 1.6, 1.0), (10.0, -20.0, 0.9, 1.0),
                (10.0, -20.0, 3.4, 1.0), (13.5, -20.0, 1.6, 1.0),
                (10.0, -17.0, 1.2, 1.0)):
        for vid in (0, 1, 2):
            sc.append(mk(cam=cam, view_id=vid, px=300))
    sc.append(mk(cam=(10.1, -20.1, 1.6, 1.0), px=100))
    for cx in (12.8, 13.5, 14.2):
        sc.append(mk(body=ident(), cam=(cx, -20.0, 2.0, 1.0),
                     aabb=((-4.0, -1.5, -0.5, 0.0), (4.0, 1.5, 2.0, 0.0))))
    # The levels of detail, a body missing, the forced levels.
    for px in (500, 121, 120, 119, 46, 45, 44, 21, 20, 19, 18, 17, 10):
        sc.append(mk(px=px))
    for missing in (1, 2, 4, 8, 6, 12):
        for px in (150, 100, 30, 10):
            sc.append(mk(px=px, solids=ALL_SOLIDS & ~missing))
    for lod in (0, 1, 2, 3):
        sc.append(mk(sw=dict(base.sw, fclod=lod), px=30))
    for px in (45, 60, 100):
        sc.append(mk(sw=dict(base.sw, fclod=2), px=px))
        sc.append(mk(sw=dict(base.sw, ftlod=lod), px=200))
    # In the air, from underneath, at the last level.
    for nw in (0, 1, 4):
        for s2 in (0, 1):
            st = list(base.states)
            st[12] = (1, 1, s2, 1)
            sc.append(mk(px=10, states=st, car=dict(base.car, nwheels=nw)))
    # The env map.
    sc.append(mk(sw=dict(base.sw, env=0)))
    sc.append(mk(px=17))
    # The query flag.
    sc.append(mk(sw=dict(base.sw, pqlm=1)))
    # The time of day, no track, traffic.
    for tod in (0, 1, 2, 3, 4, 5, -1, None):
        sc.append(mk(track=tod))
        sc.append(mk(track=tod, car=dict(base.car, dtype=3)))
    # The lights forced, by the flags and the switches.
    for forced in range(16):
        sc.append(mk(forced=forced, track=2))
    for k in ("fh", "fb", "fr", "fc"):
        sc.append(mk(sw=dict(base.sw, **{k: 1})))
        sc.append(mk(sw=dict(base.sw, **{k: 1}), car=None))
    # The headlights, the brake, reverse.
    for hl in (0, 1, 2):
        for dt in (1, 3):
            sc.append(mk(car=dict(base.car, headl=hl, dtype=dt)))
    for br in (0.0, 0.05, 0.0500001, 0.3, 1.0, -1.0):
        sc.append(mk(car=dict(base.car, cd=(0x0400, br))))
        sc.append(mk(car=dict(base.car, cd=(0x0400, br), dtype=3)))
    sc.append(mk(car=dict(base.car, cd=None)))
    for gear in (0, 1, -1):
        sc.append(mk(car=dict(base.car, gear=gear)))
    # The cop lights, through the frames.
    for copl in (0, 1, 2, -1):
        for wtf in range(0, 34, 3):
            sc.append(mk(car=dict(base.car, copl=copl), wtf=wtf,
                         timebase=wtf * 7))
    # Broken lights.
    for b in range(32):
        sc.append(mk(broken=b, forced=15, car=dict(base.car, copl=1)))
    # Flares none of the names, and none at all.
    sc.append(mk(flares=OTHER_HASHES + FLARE_HASHES[:3]))
    sc.append(mk(flares=[]))
    # The driver.
    for anim in (None, 0, 1):
        for en in (0, 1):
            sc.append(mk(car=dict(base.car, anim=anim, enabled=en)))
    for vid in (2, 3, 4):
        sc.append(mk(view_id=vid, car=dict(base.car, anim=0)))
    for ot in (0, 1):
        for vm in (0, 3):
            for px in (40, 50, 51, 75, 76, 100, 101, 144, 145, 151, 301,
                       1000):
                sc.append(mk(opentop=ot, vm=vm, px=px,
                             car=dict(base.car, anim=0)))
    for q in (0, 1):
        for cam in ((4.0, -24.0, 2.0, 1.0), (13.0, -18.0, 2.0, 1.0),
                    (-30.0, -32.0, 5.0, 1.0), (7.28, -25.35, 2.0, 1.0)):
            for px in (140, 160, 310, 1000):
                sc.append(mk(queued=q, cam=cam, px=px,
                             car=dict(base.car, anim=0)))
    sc.append(mk(sw=dict(base.sw, fdrv=1), px=20, car=dict(base.car, anim=0)))
    sc.append(mk(frame=(0x100, 0x100 + 481 + 64),
                 car=dict(base.car, anim=0)))
    # The hull shadow: the body's points, the sun, the ground.
    for n in (0, 1, 2, 3, 8, 12, 17, 40, 64):
        sc.append(mk(verts=box_verts(2.2, 0.9, 0.6, max(n, 8))[:n]))
    for sl in (0.0, 0.39, 0.4, 0.41, 0.7, 0.99, 1.0, 1.01, 2.0, -1.0):
        sc.append(mk(sunl=[sl]))
        sc.append(mk(sunl=[sl], px=30))
    for sun in (None, (0.0, 0.0, 100.0), (-100.0, 0.0, 1.0),
                (10.0, -20.0, -5.0), (1e4, -3e4, 50.0), (10.0, -20.0, 1.5)):
        sc.append(mk(sun=sun))
    for mod, off in ((2, 0), (2, 1), (3, 1), (5, 4), (1, 0)):
        sc.append(mk(elev=base.elev[:3] + (mod, off) + base.elev[5:]))
    for e in ((5.0, 0.0, 0.0), (1.25, 0.5, 0.25), (1.25, -2.0, 1.0),
              (-3.0, 0.0625, 0.0)):
        sc.append(mk(elev=e + base.elev[3:]))
    for n in ((0.0, 0.0, 1.0, 0.0), (0.3, 0.3, 0.9, 0.5),
              (0.0, 0.0, -1.0, 0.0), (0.9, 0.0, 0.1, 0.0)):
        sc.append(mk(elev=base.elev[:5] + (n,)))
    for ax, ay in ((3.0, 0.0), (0.0, -4.0), (2.0, 2.0), (1.5, 0.5)):
        ln = math.sqrt(ax * ax + ay * ay + 1.0)
        sc.append(mk(elev=(1.25, ax, ay, 0, 0,
                           (-ax / ln, -ay / ln, 1.0 / ln, 0.0))))
    for flow in (3, 6, 0):
        for car in (None, base.car, dict(base.car, colbody=0)):
            sc.append(mk(flow=flow, car=car))
    sc.append(mk(ramp=0))
    sc.append(mk(shadow=0))
    sc.append(mk(ramp=0, shadow=0))
    sc.append(mk(solids=ALL_SOLIDS & ~1))
    sc.append(mk(view_id=3))
    for em in (0, 0x55555555, 0xaaaaaaaa, 0x0000ffff, 0xfffffffe):
        sc.append(mk(emask=em, exmask=~em & M32))
        sc.append(mk(emask=em, exmask=em, flow=3))
    # The grid: in the air, the shadow part seen or not.
    for nw in (0, 3, 4):
        for c in (SEEN, NEVER):
            sc.append(mk(car=dict(base.car, nwheels=nw),
                         cull=cull_with(p13=c)))
    sc.append(mk(car=None, cull=cull_with(p13=NEVER)))
    for csefe in (0.01, -0.5, 3.0):
        sc.append(mk(flow=3, sw=dict(base.sw, csefe=csefe)))
    # The damage: mirrors, plates, scuffs.
    for bits in (0, 1, 2, 3, 4, 8, 12, 0x10, 0x20, 0x40, 0x80, 0xf0, 0xff,
                 0xffffffff):
        sc.append(mk(car=dict(base.car, dmg=bits)))
    for vd in (0.0, 0.02, 0.0200001, 1.0):
        sc.append(mk(vd=vd, car=dict(base.car, dmg=0)))
        sc.append(mk(vd=vd, car=dict(base.car, dmg=0), px=100))
    # The plates' and the tyres' and the brakes' culling.
    for p in range(14):
        sc.append(mk(cull=cull_with(**{"p%d" % p: NEVER})))
    sc.append(mk(cull=[list(NEVER) for _ in range(14)]))
    sc.append(mk(cull=[list(NEVER) for _ in range(14)], flow=3))
    sc.append(mk(cull=[list(SEEN) for _ in range(14)]))
    # Steering, which turns the front wheels into view.
    for st in (0, 1000, 1092, 1093, 1094, 5000, 64443, 64444, 64445, 65535):
        sc.append(mk(car=dict(base.car, cd=(st, 0.0)),
                     cull=[list(NEVER) for _ in range(14)]))
    # The blur: the wheels' speeds, the levels.
    for wav in ((0.0, 0.0, 0.0, 0.0), (5.0, -5.0, 5.01, -4.99),
                (50.0, 60.0, -70.0, 80.0), (0.05, 0.06, 0.055, 1.0)):
        for px in (150, 50, 30):
            sc.append(mk(car=dict(base.car, wav=wav), px=px))
    # The brakes: none, the levels.
    sc.append(mk(solids=ALL_SOLIDS & ~(1 << 14)))
    for px in (50, 45, 44):
        sc.append(mk(px=px))
    # The wipers.
    for ws, won, woff, wtf in ((1, 0, 0, 5), (0, 5, 10, 4), (0, 5, 10, 5),
                               (0, 5, 10, 9), (0, 5, 10, 10),
                               (0, 0x7ffff, 0x80000, 0x7ffff),
                               (0, -5, 3, 0), (0, 0x12345, 0x12346, 0x12345)):
        for px in (41, 40):
            sc.append(mk(car=dict(base.car, wstate=ws, won=won, woff=woff),
                         wtf=wtf, px=px))
    for wa in (0, 1, 2):
        sc.append(mk(car=dict(base.car, wstate=1), wanim=wa))
    sc.append(mk(car=dict(base.car, wstate=1),
                 solids=ALL_SOLIDS & ~(3 << 16)))
    # The lamp textures: broken, changed or not.
    for dn in ((0x11110002, 0x11110002, 0x22220002, 0x22220002),
               (0x11110001, 0x11110000, 0x22220001, 0x22220000),
               (1, 2, 3, 4), (0x11110000, 0x11110001, 0x22220001,
                              0x22220002)):
        for tod in (1, 2):
            for br in (0.0, 1.0):
                sc.append(mk(dnew=dn, track=tod,
                             car=dict(base.car, cd=(0, br), copl=1)))
    # The culler: normalised, and each flag.
    for norm in (0, 1):
        t = []
        for i in range(14):
            planes = [rnd.uniform(-2, 2) for _ in range(12)]
            t.append([i % 3, i % 4] + planes
                     + [rnd.uniform(-1, 1) for _ in range(4)])
        sc.append(mk(cull=t, sw=dict(base.sw, norm=norm)))
    # Extras as long as the eye's reach, so that whether the planes were
    # normalised decides which side the eye is on.
    r2 = random.Random(0xc011)
    for _ in range(3):
        t = []
        for i in range(14):
            planes = [r2.uniform(-2, 2) for _ in range(12)]
            t.append([i % 2, 1 + i % 3] + planes
                     + [r2.uniform(-8, 8) for _ in range(4)])
        for norm in (0, 1):
            sc.append(mk(cull=t, sw=dict(base.sw, norm=norm)))
    # A car square to the axes and a sun straight along y: points share
    # an x, and three stand on a line, which cmpl and make_chain split.
    for sun in ((10.0, -15.0, 100.0), (10.0, -35.0, 60.0),
                (10.0, -20.0 + 1e-3, 100.0), (-50.0, -20.0, 100.0)):
        for n in (8, 12, 16):
            sc.append(mk(body=ident(), sun=sun,
                         verts=box_verts(2.2, 0.9, 0.6, n)))
    # A car render matrix, and the front end's car.
    sc.append(mk(crm=rot(0.5, 0.1, 0.0, (0.25, 0.5, -0.125), 1.0)))
    sc.append(mk(crm=[0.5 * x for x in rot(0.2)]))
    sc.append(mk(flow=3, car=None, px=400))
    sc.append(mk(flow=3, car=None, px=400, cam=(12.0, -21.0, 1.8, 1.0)))
    sc.append(mk(flow=3, px=400))
    # The extra flags.
    for extra in (1, 2, 0x80000000, 0xffffffff):
        sc.append(mk(extra=extra, car=dict(base.car, dmg=0, anim=0)))

    # And at random.
    for _ in range(160):
        sc.append(random_sc(rnd, table))
    return sc


def random_sc(rnd, table):
    def f(a, b):
        return f32(rnd.uniform(a, b))

    def maybe(p, v, other):
        return v if rnd.random() < p else other

    pos = (f(-500, 500), f(-500, 500), f(-5, 30), 1.0)
    d = f(3.0, 40.0)
    a = rnd.uniform(0, 2 * math.pi)
    cam = (f32(pos[0] + d * math.cos(a)), f32(pos[1] + d * math.sin(a)),
           f32(pos[2] + rnd.uniform(-1, 6)), 1.0)
    car = None
    if rnd.random() < 0.85:
        car = dict(dtype=rnd.choice((1, 2, 3, 4)),
                   cd=maybe(0.9, (rnd.randrange(65536),
                                  rnd.choice((0.0, f(0, 1), 0.04, 1.0))),
                            None),
                   colbody=maybe(0.9, 1, 0),
                   dmg=maybe(0.5, rnd.randrange(1 << 32), None),
                   anim=maybe(0.6, rnd.choice((0, 0, 1)), None),
                   enabled=rnd.choice((0, 1, 1)),
                   copl=rnd.choice((0, 0, 1, 2)), headl=rnd.choice((0, 1)),
                   won=rnd.randrange(2000), woff=rnd.randrange(2000),
                   wstate=rnd.choice((0, 0, 1)),
                   gear=rnd.choice((0, 1, 2, 3)),
                   nwheels=rnd.choice((0, 2, 4, 4)),
                   wav=tuple(f(-80, 80) for _ in range(4)),
                   spos=(f32(pos[0] + rnd.uniform(-0.1, 0.1)),
                         f32(pos[1] + rnd.uniform(-0.1, 0.1)),
                         f32(pos[2] + rnd.uniform(-0.1, 0.1)), 1.0))
    cull = [list(c) for c in table]
    for i in range(14):
        r = rnd.random()
        if r < 0.1:
            cull[i] = list(SEEN)
        elif r < 0.2:
            cull[i] = list(NEVER)
    bx, by, bz = f(1.6, 2.6), f(0.7, 1.1), f(0.3, 0.8)
    n = rnd.choice((0, 3, 8, 8, 12, 20, 32, 64))
    verts = box_verts(bx, by, bz, max(n, 8), rnd)[:n]
    rnd.shuffle(verts)
    return Sc(
        cull, flow=rnd.choice((6, 6, 6, 3)), wtf=rnd.randrange(100000),
        sw=dict(env=maybe(0.95, 1, 0), pqlm=maybe(0.9, 0, 1),
                norm=maybe(0.8, 0, 1), fh=maybe(0.9, 0, 1),
                fb=maybe(0.9, 0, 1), fr=maybe(0.9, 0, 1),
                fc=maybe(0.9, 0, 1), fdrv=maybe(0.9, 0, 1),
                fclod=maybe(0.9, -1, rnd.randrange(4)),
                ftlod=maybe(0.9, -1, rnd.randrange(3)),
                csefe=maybe(0.8, 0.01, f(-1, 1)), edge=f(1.0, 1.5)),
        track=maybe(0.9, rnd.randrange(6), None),
        sun=maybe(0.9, (f(-2e4, 2e4), f(-2e4, 2e4), f(-100, 1e4)), None),
        frame=maybe(0.9, (0, FRAME_SIZE),
                    (0x2000, 0x2000 + rnd.randrange(3200))),
        crm=maybe(0.9, ident(), rot(f(-1, 1), f(-0.1, 0.1))),
        pos=pos,
        body=rot(rnd.uniform(-3, 3), rnd.uniform(-0.3, 0.3),
                 rnd.uniform(-0.3, 0.3)),
        tm=[rot(0.0, rnd.uniform(-3, 3), rnd.uniform(-0.1, 0.1),
                (f(-1.5, 1.5), f(-1, 1), f(0, 0.5))) for _ in range(4)],
        bm=[rot(rnd.uniform(-0.5, 0.5), 0.0, 0.0,
                (f(-1.5, 1.5), f(-1, 1), f(0, 0.5))) for _ in range(4)],
        extra=rnd.choice((0, 0, 1, 2, 0x100)), forced=maybe(0.8, 0,
                                                            rnd.randrange(16)),
        view_id=rnd.choice((0, 1, 1, 2, 3)), cam=cam,
        wvm=[f(-2, 2) for _ in range(16)], wscm=[f(-2, 2) for _ in range(16)],
        px=rnd.choice((2, 10, 19, 25, 40, 60, 100, 130, 200, 400, 1200)),
        vm=maybe(0.8, 0, 3), cls=maybe(0.9, 1, 0), vd=f(0, 0.1),
        queued=rnd.choice((0, 1)), emask=rnd.randrange(1 << 32),
        exmask=rnd.randrange(1 << 32),
        sunl=[f(-0.2, 1.4) for _ in range(rnd.randrange(1, 4))],
        elev=(f(-2, 30), f(-0.05, 0.05), f(-0.05, 0.05),
              rnd.choice((0, 0, 3, 7)), rnd.randrange(3),
              (f(-0.3, 0.3), f(-0.3, 0.3), f(0.8, 1.0), f(-1, 1))),
        car=car, verts=verts, opentop=rnd.choice((0, 0, 1)),
        ctype=rnd.randrange(40),
        drvoff=(f(-0.5, 0.5), f(-0.6, 0.6), f(0, 0.8), f(-1, 1)),
        wheels=[(f(1.0, 1.6), f(0.6, 0.9), f(0.2, 0.4), f(0.3, 0.4)),
                (f(1.0, 1.6), f(-0.9, -0.6), f(0.2, 0.4), f(0.3, 0.4)),
                (f(-1.6, -1.0), f(-0.9, -0.6), f(0.2, 0.4), f(0.3, 0.4)),
                (f(-1.6, -1.0), f(0.6, 0.9), f(0.2, 0.4), f(0.3, 0.4))],
        rtype=rnd.randrange(40), skin=rnd.randrange(-2, 10),
        aabb=((-bx, -by, -bz * 0.5, 0.0), (bx, by, bz * 2, 0.0)),
        solids=maybe(0.7, ALL_SOLIDS, rnd.randrange(1 << NMODELS)),
        wanim=rnd.randrange(4),
        pivots=[rot(f(-1, 1), 0.0, 0.0, (f(0, 1), f(-0.5, 0.5), f(0.5, 1.5)))
                for _ in range(2)],
        rst=(rnd.randrange(65536), rnd.randrange(65536)),
        shadow=maybe(0.9, 1, 0), ramp=maybe(0.9, 1, 0),
        skinlm=maybe(0.9, 1, 0), timebase=rnd.randrange(1 << 16),
        broken=maybe(0.7, 0, rnd.randrange(32)),
        dnew=tuple(rnd.choice((0x11110000, 0x11110001, 0x11110002,
                               0x22220000, 0x22220001, 0x22220002, 7))
                   for _ in range(4)),
        points=[(f(-2, 2), f(-1, 1), f(-0.5, 1.5), f(-1, 1))
                for _ in range(14)],
        states=[(rnd.randrange(100), rnd.randrange(100), rnd.randrange(2),
                 rnd.randrange(1 << 32)) for _ in range(14)],
        flares=rnd.sample(FLARE_HASHES + OTHER_HASHES,
                          rnd.randrange(len(FLARE_HASHES) + 1)))


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True)
        e = self.e
        stubs = {
            PIXEL: self.pixel, VIEWMODE: self.viewmode,
            CLASSIFY: self.classify, BIAS: self.bias,
            SOLID_RLM: self.solid_rlm, MODEL_RENDER: self.model_render,
            RECONNECT: self.reconnect, SKININFO: self.skininfo,
            ELSETUP: self.elsetup, FLARE: self.flare, ELEV: self.elev,
            VISDMG: self.visdmg, DRV_RENDER: self.drv_render,
            DRV_QUEUED: self.drv_queued,
        }
        for a, fn in stubs.items():
            e.stub(a, fn)
        for a, name, kind in STRIPS:
            e.stub(a, self.strip_fn(name, kind))
        self.fill_stack()
        e.call(EMATH_INIT, limit=10000)
        e.call(EMATH_CTOR, limit=1000)
        e.call(BMATRIX_CTOR, limit=1000)
        e.call(CULL_INIT, limit=100000)
        self.table = self.read_table()
        self.names = {}

    def read_table(self):
        e = self.e
        t = []
        for i in range(14):
            a = CULL_TABLE + 80 * i
            t.append([s32(e.u32(a + 8)), s32(e.u32(a + 12))]
                     + [e.u32(a + 16 + 4 * j) for j in range(16)])
        return t

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8, 9, 10, 11)[i]] & M32

    def fill_stack(self):
        sp = self.e.reg[29] & M32
        self.e.write(sp - 16384, bytes([STACK_FILL]) * 16384)

    def w(self, a):
        return self.e.u32(a)

    def ws(self, a, n):
        return hexw(self.e.u32(a + 4 * i) for i in range(n))

    # ---- the labels ------------------------------------------------------

    def reg(self, a, name):
        self.names[a & M32] = name

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if FRAME <= a < FRAME + FRAME_SIZE + 0x1000:
            return "F+%x" % (a - FRAME)
        for base, n, name in ((HULL3, 192, "h3"), (HULL2, 64, "h2"),
                              (HULL1, 64, "h1")):
            if base <= a < base + 16 * n and (a - base) % 16 == 0:
                return "%s[%d]" % (name, (a - base) // 16)
        return self.names.get(a, "-")

    def register(self):
        self.names = {}
        r = self.reg
        r(CAR, "car")
        r(CAR + 1312, "topo")
        r(DMG, "dmg")
        r(DMG + 8, "bd")
        r(ANIM, "drv")
        r(VIEW, "view")
        r(CAM, "cam")
        r(WVM, "wvm")
        r(WSCM, "wscm")
        r(HACK_MAN, "hack")
        r(POS, "pos")
        r(BODYM, "body")
        for k in range(4):
            r(TIREM + 64 * k, "tm%d" % k)
            r(BRAKEM + 64 * k, "bm%d" % k)
        r(SKINLM, "skinlm")
        r(SHADOW, "shadow")
        r(RAMP, "ramp")
        r(RI, "ri")
        r(RI + 16, "aabbmin")
        r(RI + 32, "aabbmax")
        for name, off in MODELS:
            r(RI + off, name)
        for k in range(NMODELS):
            r(SOLIDS + SOLID_STRIDE * k, "s" + MODELS[k][0])
        for k in range(64):
            r(LFS + 80 * k, "lf%d" % k)
        r(CTI, "cti")
        r(CTI + 240, "drvoff")
        for k in range(4):
            r(CTI + 288 + 32 * k, "wheel%d" % k)
        r(HULL_ORIGIN, "hO")
        r(HULL_NORMAL, "hN")
        r(CS_LIGHT, "cs")

    # ---- the stubs -------------------------------------------------------

    def pixel(self, em):
        self.emit("  px %s %s %08x -> %d" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            em.fpr[12] & M32, s32(self.sc.px)))
        return s32(self.sc.px)

    def viewmode(self, em):
        self.emit("  vm -> %d" % self.sc.vm)
        return s32(self.sc.vm)

    def classify(self, em):
        self.emit("  cls %s %s %s -> %d" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.ws(self.arg(2), 16), self.sc.cls))
        return s32(self.sc.cls)

    def bias(self, em):
        m = self.arg(1)
        self.emit("  bias %s %s %s %08x" % (
            self.label(self.arg(0)), self.label(m), self.ws(m, 16),
            em.fpr[12] & M32))
        # Moved, so that what it touched shows downstream.
        z = em_f(self.w(m + 56))
        self.e.put32(m + 56, f_to_bits(f32(z + 0.125)))
        wv = em_f(self.w(m + 60))
        self.e.put32(m + 60, f_to_bits(f32(wv + em.f(12))))

    def solid_rlm(self, em):
        self.emit("  rlm %s %08x %s" % (self.label(self.arg(0)), self.arg(1),
                                        self.label(self.arg(2))))

    def light_words(self, lc):
        if lc == 0:
            return "null"
        return "%s %s %s %s" % (self.label(lc), self.ws(lc, 1),
                                self.ws(lc + 60, 1), self.ws(lc + 212, 1))

    def model_render(self, em):
        mdl, m, lc, fl = (self.arg(i) for i in range(4))
        self.emit("  mr %s %04x %s %s | %s | %x" % (
            self.label(mdl), self.e.u16(mdl + 22), self.label(m),
            self.ws(m, 16), self.light_words(lc), fl))

    def reconnect(self, em):
        self.emit("  rtt %s" % self.label(self.arg(0)))

    def skininfo(self, em):
        self.emit("  skin %d %d %d" % (s32(self.arg(0)), s32(self.arg(1)),
                                       s32(self.arg(2))))
        return 0

    def elsetup(self, em):
        lc, lw, hack, eye, view = (self.arg(i) for i in range(5))
        self.emit("  lc %s %s %s %s | %s %s q %d" % (
            self.label(lc), self.label(lw), self.ws(lw, 16),
            self.label(hack), self.ws(eye, 4), self.label(view),
            s32(self.e.u32(G_QLM))))
        k = self.nlc
        self.nlc += 1
        self.e.put32(lc, k)
        self.e.put32(lc + 60, 0x100 * k + 0x55)
        sl = self.sc.sunl
        self.e.put32(lc + 212, fb(sl[k % len(sl)]))

    def flare(self, em):
        self.emit("  flare %s %s %s %08x" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2)), em.fpr[12] & M32))

    def elev(self, em):
        tc, pt, ter, nrm, fnd = (self.arg(i) for i in range(5))
        x, y, z = (struct.unpack("<f", struct.pack("<I", self.w(pt + 4 * i)))
                   [0] for i in range(3))
        base, ax, ay, mod, off, n = self.sc.elev
        t1 = f32(x * f32(ax))
        t2 = f32(y * f32(ay))
        t3 = f32(t1 + t2)
        el = f32(f32(base) + t3)
        k = self.nel
        self.nel += 1
        found = 0 if mod and k % mod == off else 1
        self.emit("  el %s %s %s %s %s %s -> %08x %d" % (
            self.label(tc), self.label(pt), self.ws(pt, 3), self.label(ter),
            self.label(nrm), self.label(fnd), f_to_bits(el), found))
        if nrm:
            for i in range(4):
                self.e.put32(nrm + 4 * i, fb(n[i]))
        if fnd:
            self.e.put32(fnd, found)
        em.set_f(0, el)

    def visdmg(self, em):
        self.emit("  vdmg %s -> %08x" % (self.label(self.arg(0)),
                                          fb(self.sc.vd)))
        em.set_f(0, f32(self.sc.vd))

    def drv_render(self, em):
        d, m, lc, fl, lod = (self.arg(i) for i in range(5))
        self.emit("  dr %s %s %s %s %x %d" % (
            self.label(d), self.label(m), self.ws(m, 16), self.label(lc), fl,
            s32(lod)))

    def drv_queued(self, em):
        self.emit("  dq %s -> %d" % (self.label(self.arg(0)), self.sc.queued))
        return s32(self.sc.queued)

    def strip_fn(self, name, kind):
        def fn(em):
            if kind == "begin":
                tex, n, m = self.arg(0), self.arg(1), self.arg(2)
                mask = self.sc.emask if name == "eb" else self.sc.exmask
                k = self.nstrip[name]
                self.nstrip[name] = k + 1
                r = (mask >> (k % 32)) & 1
                self.emit("  %s %s %d %s %s -> %d" % (
                    name, self.label(tex), s32(n), self.label(m),
                    self.ws(m, 16), r))
                return r
            if kind == "vertex":
                self.emit("  %s %s" % (name, self.ws(self.arg(0), 3)))
            elif kind == "colour":
                self.emit("  %s %08x" % (name, self.arg(0)))
            elif kind == "uv":
                self.emit("  %s %08x %08x" % (name, em.fpr[12] & M32,
                                               em.fpr[13] & M32))
            else:
                self.emit("  " + name)
            return None
        return fn

    # ---- the world -------------------------------------------------------

    def fill(self, a, n, v=PATTERN):
        self.e.write(a, bytes([v]) * n)

    def put(self, a, v):
        self.e.put32(a, fb(v))

    def puts(self, a, vs):
        for i, v in enumerate(vs):
            self.put(a + 4 * i, v)

    def put16(self, a, v):
        self.e.mem[a:a + 2] = struct.pack("<H", v & 0xffff)

    def world(self, sc):
        e = self.e
        self.register()
        self.nlc = self.nel = 0
        self.nstrip = {"eb": 0, "xb": 0}
        s = sc.sw
        for a, v in ((G_ENV, s["env"]), (G_PQLM, s["pqlm"]), (G_QLM, 0),
                     (G_NORM, s["norm"]), (G_FHEAD, s["fh"]),
                     (G_FBRAKE, s["fb"]), (G_FREV, s["fr"]),
                     (G_FCOP, s["fc"]), (G_FDRV, s["fdrv"]),
                     (G_FCLOD, s["fclod"]), (G_FTLOD, s["ftlod"]),
                     (G_CSEFE, s["csefe"]), (G_EDGE, s["edge"]),
                     (G_FLOW, sc.flow), (G_WTF, sc.wtf),
                     (G_FFAIL, 0), (G_FAMT, 0)):
            self.put(a, v)
        self.fill(TRACK, 128)
        if sc.track is None:
            self.put(G_TRACK, 0)
        else:
            self.put(G_TRACK, TRACK)
            self.put16(TRACK + 68, sc.track)
        self.fill(SUN, 64)
        if sc.sun is None:
            self.put(G_SUN, 0)
        else:
            self.put(G_SUN, SUN)
            self.puts(SUN + 16, sc.sun)
        self.fill(FRAME, FRAME_SIZE)
        self.put(G_FPOS, FRAME + sc.frame[0])
        self.put(G_FEND, FRAME + sc.frame[1])
        self.puts(CAR_RENDER_MATRIX, sc.crm)
        for i, c in enumerate(sc.cull):
            a = CULL_TABLE + 80 * i
            self.put(a + 8, c[0])
            self.put(a + 12, c[1])
            self.puts(a + 16, c[2:18])
        # the arguments
        self.puts(POS, sc.pos)
        self.puts(BODYM, sc.body)
        for k in range(4):
            self.puts(TIREM + 64 * k, sc.tm[k])
            self.puts(BRAKEM + 64 * k, sc.bm[k])
        # the view
        self.fill(VIEW, 128)
        self.put(VIEW, sc.view_id)
        self.put(VIEW + 56, CAM)
        self.put(VIEW + 68, WVM)
        self.put(VIEW + 80, WSCM)
        self.fill(CAM, 160)
        self.puts(CAM + 64, sc.cam)
        self.puts(WVM, sc.wvm)
        self.puts(WSCM, sc.wscm)
        # the car
        self.fill(CAR, CAR_SIZE)
        c = sc.car
        if c is not None:
            self.fill(DRVINFO, 32)
            self.put(CAR + 20, DRVINFO)
            self.put(DRVINFO + 8, c["dtype"])
            self.fill(CARDRV, 600)
            if c["cd"] is None:
                self.put(CAR + 44, 0)
            else:
                self.put(CAR + 44, CARDRV)
                self.put16(CARDRV + 528, c["cd"][0])
                self.put(CARDRV + 536, c["cd"][1])
            self.put(CAR + 52, COLBODY if c["colbody"] else 0)
            self.puts(CAR + 96, c["spos"])
            self.puts(CAR + 752, c["wav"])
            self.put(CAR + 956, c["nwheels"])
            self.put(CAR + 968, c["gear"])
            self.put(CAR + 1196, c["enabled"])
            self.fill(ANIM, 128)
            if c["anim"] is None:
                self.put(CAR + 1204, 0)
            else:
                self.put(CAR + 1204, ANIM)
                self.put(ANIM + 100, c["anim"])
            self.put(CAR + 2056, c["copl"])
            self.put(CAR + 2100, c["headl"])
            self.put(CAR + 2108, c["won"])
            self.put(CAR + 2112, c["woff"])
            self.put(CAR + 2116, c["wstate"])
            self.fill(DMG, 256)
            if c["dmg"] is None:
                self.put(CAR + 2120, 0)
            else:
                self.put(CAR + 2120, DMG)
                self.put(DMG + 204, c["dmg"])
        self.fill(COLBODY, 64)
        self.put(COLBODY + 8, POLY)
        self.fill(POLY, 48)
        self.put16(POLY + 16, len(sc.verts))
        self.put(POLY + 32, VERTS)
        self.fill(VERTS, 20 * 64)
        for i, v in enumerate(sc.verts):
            self.puts(VERTS + 20 * i + 4, v)
        # the type and the ride
        self.fill(CTI, CTI_SIZE)
        e.mem[CTI + 231] = sc.opentop & 0xff
        self.puts(CTI + 240, sc.drvoff)
        for k, wv in enumerate(sc.wheels):
            self.puts(CTI + 288 + 32 * k, wv)
        self.put(CTI + 1332, sc.ctype)
        self.fill(RIDE, 8)
        self.put(RIDE, sc.rtype)
        e.mem[RIDE + 5] = sc.skin & 0xff
        # the render info
        self.fill(RI, RI_SIZE)
        self.put(RI, CAR if c is not None else 0)
        self.put(RI + 4, RIDE)
        self.put(RI + 8, CTI)
        self.puts(RI + 16, sc.aabb[0])
        self.puts(RI + 32, sc.aabb[1])
        for k, (name, off) in enumerate(MODELS):
            a = RI + off
            sa = SOLIDS + SOLID_STRIDE * k
            self.fill(sa, SOLID_STRIDE)
            self.puts(sa + 64, (-1.0, -0.5, -0.25, 0.0, 1.0, 0.5, 0.25, 0.0))
            self.put(sa + 168, 0)
            self.put(a + 12, sa if sc.solids >> k & 1 else 0)
            if name.startswith("Wiper"):
                w = int(name[-1])
                self.puts(sa + 96, sc.pivots[w])
                self.put(sa + 168, RIGID + 16 * w if sc.wanim >> w & 1
                         else 0)
                self.put16(a + 22, sc.rst[w])
        self.puts(RI + 812, sc.hl)
        self.puts(RI + 824, sc.bl)
        self.put(RI + 860, SHADOW if sc.shadow else 0)
        self.put(RI + 864, RAMP if sc.ramp else 0)
        self.put(RI + 868, SKINLM if sc.skinlm else 0)
        nodes = [LFS + 80 * k for k in range(len(sc.flares))]
        for k, hsh in enumerate(sc.flares):
            self.fill(nodes[k], 80)
            self.put(nodes[k] + 8, hsh)
        prev = RI + 872
        for n in nodes:
            self.put(prev, n)
            self.put(n + 4, prev)
            prev = n
        self.put(prev, RI + 872)
        self.put(RI + 876, prev)
        self.put(RI + 880, sc.timebase)
        self.put(RI + 884, sc.broken)
        for i in range(4):
            self.put(RI + 1376 + 28 * (8 + i) + 4, sc.dnew[i])
        for i in range(14):
            a = RI + 1888 + 32 * i
            self.puts(a, sc.points[i])
            self.puts(a + 16, sc.states[i])

    # ---- the dump --------------------------------------------------------

    def dump(self):
        e = self.e
        L = self.label
        out = ["  end %s fail %d %x qlm %d edge %08x oz %08x" % (
            L(e.u32(G_FPOS)), s32(e.u32(G_FFAIL)), e.u32(G_FAMT),
            s32(e.u32(G_QLM)), e.u32(G_EDGE), e.u32(G_ONEOVERZ))]
        out.append("  cs %s hO %s hN %s" % (
            self.ws(CS_LIGHT, 3), self.ws(HULL_ORIGIN, 4),
            self.ws(HULL_NORMAL, 4)))
        out.append("  cull " + " ".join(
            self.ws(RI + 1888 + 32 * i + 16, 4) for i in range(14)))
        out.append("  dmg " + " ".join(
            self.ws(RI + 1376 + 28 * (8 + i) + 4, 1) for i in range(4)))
        out.append("  wst %04x %04x" % (e.u16(RI + 400 + 22),
                                        e.u16(RI + 424 + 22)))
        out.append("  h1 " + " ".join(self.ws(HULL1 + 16 * i, 2)
                                      for i in range(12)))
        out.append("  h2 " + " ".join(self.ws(HULL2 + 16 * i, 3)
                                      for i in range(12)))
        out.append("  h3 " + " ".join(self.ws(HULL3 + 16 * i, 4)
                                      for i in range(24)))
        out.append("  hp " + " ".join(L(e.u32(HULLP + 4 * i))
                                      for i in range(13)))
        for s in out:
            self.emit(s)

    def initial(self):
        """The image's own values of what the scenarios set: the
        tweakables, the cop lights' patterns and the level-of-detail
        sizes."""
        e = self.e
        ws = [e.u32(a) for a in (G_ENV, G_PQLM, G_NORM, G_FHEAD, G_FBRAKE,
                                 G_FREV, G_FCOP, G_FDRV, G_FCLOD, G_FTLOD,
                                 G_EDGE, G_CSEFE)]
        tabs = [(0x002e01e8, 16), (GP - 23736, 8), (GP - 23728, 8),
                (GP - 23720, 8), (0x002e01b8, 16), (0x002e01c8, 16),
                (0x002e01d8, 16)]
        self.emit("I %s %s %s" % (
            hexw(ws), " ".join(bytes(e.mem[a:a + n]).hex() for a, n in tabs),
            self.ws(0x002ad0e8, 4)))

    def run(self, scenarios):
        self.initial()
        for n, sc in enumerate(scenarios):
            self.sc = sc
            self.world(sc)
            self.emit("R %d" % n)
            self.fill_stack()
            self.e.call(RENDER, RI, VIEW, POS, BODYM, TIREM, BRAKEM,
                        sc.extra & M32, sc.forced & M32, limit=20000000)
            self.dump()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="carrender_test"):
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
    # ---- the helpers
    ("h_fe", CRC, "        && gTrackFlowGameFlow->current == BGF_IN_FRONTEND;",
     "        && gTrackFlowGameFlow->current == 6;"),
    ("h_tod_track", CRC, "    if (CurrentTrackInfo == NULL)\n        return 0;",
     "    if (CurrentTrackInfo == NULL)\n        return 1;"),
    ("h_tod_3", CRC, "    return t == 2 || t == 4 || t == 3;",
     "    return t == 2 || t == 4;"),
    ("h_rlm_solid", CRC,
     "    if (m->Solid != NULL)\n        esolid_replace_light_material",
     "        esolid_replace_light_material"),
    ("h_dot_order", CRC,
     "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
     "    return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    ("h_hidden_word", CRC,
     "    memcpy(&w, (const uint8_t *)d + 100, sizeof w);",
     "    memcpy(&w, (const uint8_t *)d + 96, sizeof w);"),
    ("h_item_shift", CRC,
     "    return (cd->BreakableCarItemDamageAmounts >> (2 * item)) & 3;",
     "    return (cd->BreakableCarItemDamageAmounts >> item) & 3;"),

    # ---- the tables and the tweakables' starting values
    ("tab_head", CRC,
     "uint8_t CopLightsHeadlights[16] = { 1, 1, 1, 1, 1, 1, 1, 1,",
     "uint8_t CopLightsHeadlights[16] = { 1, 1, 1, 1, 1, 1, 1, 0,"),
    ("tab_blue", CRC,
     "uint8_t CopLightsBlue[8]  = { 0, 0, 1, 1, 1, 1, 0, 0 };",
     "uint8_t CopLightsBlue[8]  = { 0, 0, 1, 1, 1, 1, 1, 0 };"),
    ("tab_red_slow", CRC,
     "                                   1, 1, 0, 0, 0, 0, 0, 0 };",
     "                                   1, 1, 0, 0, 0, 0, 0, 1 };"),
    ("tab_white_slow", CRC,
     "uint8_t CopLightsWhiteSlow[16] = { 0, 0, 1, 1, 0, 0, 0, 0,",
     "uint8_t CopLightsWhiteSlow[16] = { 0, 0, 1, 1, 1, 0, 0, 0,"),
    ("tab_lod", CRC,
     "const float CarLodPixelSizes[4] = { 120.0f, 45.0f, 20.0f, 0.0f };",
     "const float CarLodPixelSizes[4] = { 120.0f, 45.0f, 19.0f, 0.0f };"),
    ("tab_nearest", CRC,
     "    2, 2, 1, 1, 2, 2, 1, 1, 3, 3, 0, 0, 3, 3, 0, 0,",
     "    2, 2, 1, 1, 2, 2, 1, 1, 3, 3, 0, 0, 3, 3, 0, 1,"),
    ("init_env", CRC, "int32_t EnableEnvMap = 1;", "int32_t EnableEnvMap;"),
    ("init_car_lod", CRC, "int32_t ForceCarLOD = -1;",
     "int32_t ForceCarLOD = 0;"),
    ("init_edge", CRC, "float FancyCarShadowEdgeMult = 1.1f;",
     "float FancyCarShadowEdgeMult = 1.4f;"),
    ("init_fe_z", CRC, "float CarShadowElevationFE = 0.01f;",
     "float CarShadowElevationFE = 0.02f;"),

    # ---- UpdateLightStateTextures
    ("lst_on_both", CRC,
     "            left = right = 1;\n        } else if (car->CopLights != 0) {",
     "            left = 1;\n        } else if (car->CopLights != 0) {"),
    ("lst_traffic", CRC,
     "        if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)\n"
     "            on ^= 1;\n        if (on) {\n            left",
     "        if (car->MyDriver->TheDriverType == DRIVER_TYPE_COP)\n"
     "            on ^= 1;\n        if (on) {\n            left"),
    ("lst_wig_right", CRC, "            right = !wig;", "            right = wig;"),
    ("lst_wig_frame", CRC,
     "            int wig = CopLightsHeadlights[frame & 15] != 0;",
     "            int wig = CopLightsHeadlights[frame & 7] != 0;"),
    ("lst_night", CRC, "    if (night || ForceHeadlights)",
     "    if (ForceHeadlights)"),
    ("lst_force_head", CRC, "    if (night || ForceHeadlights)",
     "    if (night)"),
    ("lst_broken8", CRC,
     "    if (t[8].NewNameHash != u->ReplaceHeadlightHash[2]\n",
     "    if (1\n"),
    ("lst_same9", CRC, "        && t[9].NewNameHash != h) {", "        ) {"),
    ("lst_brake_thresh", CRC,
     "             && 0.05f < car->pCarDriver->Brake);",
     "             && 0.05f <= car->pCarDriver->Brake);"),
    ("lst_force_brake", CRC, "    brake = ForceBrakelights\n",
     "    brake = 0\n"),
    ("lst_brake11", CRC,
     "    if (t[11].NewNameHash != u->ReplaceBrakelightHash[2]",
     "    if (t[11].NewNameHash != u->ReplaceBrakelightHash[1]"),
    ("lst_changed", CRC, "    if (changed) {\n        emodel_reconnect",
     "    if (1) {\n        emodel_reconnect"),
    ("lst_reconnect2", CRC,
     "        emodel_reconnect_texture_table(&ri->Body[2]);",
     "        emodel_reconnect_texture_table(&ri->Body[3]);"),

    # ---- CalculateTireBlur
    ("blur_abs", CRC,
     "    b = fabsf(ri->pCar->State.WheelAngularVelocity[wheel]) * 0.02f;",
     "    b = ri->pCar->State.WheelAngularVelocity[wheel] * 0.02f;"),
    ("blur_clamp", CRC, "    if (1.0f < b)\n        b = 1.0f;\n    return b;",
     "    return b;"),
    ("blur_nocar", CRC, "    if (ri->pCar == NULL)\n        return 0.0f;",
     "    if (ri->pCar == NULL)\n        return 1.0f;"),

    # ---- the culler
    ("cull_n", CRC, "        if (n > 0) {", "        if (n > 1) {"),
    ("cull_any_start", CRC, "                seen = info->Flag8 == 0 ? 0 : 1;",
     "                seen = 1;"),
    ("cull_flag_other", CRC,
     "            if (info->Flag8 == 0 || info->Flag8 == 1) {",
     "            if (1) {"),
    ("cull_norm", CRC, "                    if (CarPartCullerNormalise) {",
     "                    if (0) {"),
    ("cull_norm_w", CRC, "                        p.z *= r;\n",
     ""),
    ("cull_extra", CRC, "                    s = dot3(&d, &p) - extra[k];",
     "                    s = dot3(&d, &p) - extra[0];"),
    ("cull_count", CRC,
     "            part->State[1]++;\n        else\n            part->State[0]++;",
     "            part->State[1]++;\n        else\n            part->State[1]++;"),
    ("cull_state2", CRC, "        part->State[2] = seen;",
     "        part->State[2] = 1;"),
    ("cull_d", CRC, "            d.y = eye->y - part->Point.y;",
     "            d.y = eye->y;"),

    # ---- sh_Setup
    ("sh_nosun_x", CRC, "        sx = -16384.0f;", "        sx = 16384.0f;"),
    ("sh_nosun_z", CRC, "        sz = 7000.0f;", "        sz = 700.0f;"),
    ("sh_sun_y", CRC, "        sy = SunInfo->CarShadowPositionY;",
     "        sy = SunInfo->CarShadowPositionX;"),
    ("sh_limit", CRC, "    if ((uint32_t)a < 4600u) {",
     "    if ((uint32_t)a < 4000u) {"),
    ("sh_limit_angle", CRC, "        bSinCos(&s, &c, 4600);",
     "        bSinCos(&s, &c, 4000);"),
    ("sh_len_sign", CRC, "        cs_lightV.z = -len * s;",
     "        cs_lightV.z = len * s;"),
    ("sh_f_abs", CRC, "        f = fabsf(x) + fabsf(y);",
     "        f = fabsf(x) + y;"),
    ("sh_x_cos", CRC, "        cs_lightV.x = ((x / f) * len) * c;",
     "        cs_lightV.x = ((x / f) * len) * s;"),
    ("sh_y_orig", CRC, "        cs_lightV.y = ((y / f) * len) * c;",
     "        cs_lightV.y = ((x / f) * len) * c;"),
    ("sh_oneoverz", CRC,
     "    cs_OneOverZ = cs_lightV.z == 0.0f ? 0.0f : 1.0f / cs_lightV.z;",
     "    cs_OneOverZ = 1.0f / cs_lightV.z;"),
    ("sh_atan", CRC, "              -cs_lightV.z);", "              cs_lightV.z);"),

    # ---- cmpl, cmph, make_chain, ch2d
    ("cmpl_y", CRC, "    d = b->y - a->y;", "    d = a->y - b->y;"),
    ("cmpl_x", CRC,
     "    if (0.0f < d)\n        return 1;\n    if (d < 0.0f)\n        return -1;\n"
     "    d = b->y",
     "    if (0.0f < d)\n        return -1;\n    if (d < 0.0f)\n        return 1;\n"
     "    d = b->y"),
    ("cmph_args", CRC, "    return cmp_low(pb, pa);",
     "    return cmp_low(pa, pb);"),
    ("chain_collinear", CRC,
     "                  - (vi->y - vj->y) * (vk->x - vj->x) <= 0.0f))",
     "                  - (vi->y - vj->y) * (vk->x - vj->x) < 0.0f))"),
    ("chain_s", CRC, "    int32_t i, j, s = 1;", "    int32_t i, j, s = 0;"),
    ("chain_i", CRC, "    for (i = 2; i < n; i++) {\n        bVector3 *t;",
     "    for (i = 1; i < n; i++) {\n        bVector3 *t;"),
    ("chain_j", CRC, "        for (j = s; j >= 1; j--) {",
     "        for (j = s; j >= 2; j--) {"),
    ("ch2d_wrap", CRC, "    P[n] = P[0];", "    P[n] = P[1];"),
    ("ch2d_count", CRC,
     "    return u + make_chain(P + u, n - u + 1, cmp_high);",
     "    return u + make_chain(P + u, n - u, cmp_high);"),

    # ---- convex_hull
    ("hull_z", CRC, "        out->z = z;\n", "        out->z = 0.0f;\n"),
    ("hull_lift", CRC,
     "        e = topology_get_elevation(tc, out, NULL, NULL, &found) + lift;",
     "        e = topology_get_elevation(tc, out, NULL, NULL, &found);"),
    ("hull_found", CRC, "        if (found && fabsf(e - z) <= 4.0f) {",
     "        if (fabsf(e - z) <= 4.0f) {"),
    ("hull_4", CRC, "        if (found && fabsf(e - z) <= 4.0f) {",
     "        if (found && fabsf(e - z) <= 40.0f) {"),
    ("hull_1p5", CRC, "            if (s < 1.5f) {\n                out++;",
     "            if (s < 15.0f) {\n                out++;"),
    ("hull_abs", CRC,
     "            if (s < 0.0f)\n                s = -s;\n            if (s < 1.5f) {\n"
     "                out++;",
     "            if (s < 1.5f) {\n                out++;"),
    ("hull_count", CRC, "    *count = n - dropped;", "    *count = n;"),
    ("hull_origin", CRC, "            d.y = out->y - hull_Origin.y;",
     "            d.y = out->y;"),

    # ---- smooth_shadow_corners
    ("smooth_third", CRC, "        cur->x = (h[j].x - h[i].x) * 0.333f;",
     "        cur->x = (h[j].x - h[i].x) * 0.334f;"),
    ("smooth_wrap", CRC, "        int32_t j = i + 1 == n ? 0 : i + 1;",
     "        int32_t j = i + 1 == n ? i : i + 1;"),
    ("smooth_prev0", CRC, "    e[1].x = (h[0].x - h[n - 1].x) * 0.333f;",
     "    e[1].x = (h[0].x - h[n - 2].x) * 0.333f;"),
    ("smooth_mid", CRC, "        sm[out + 1].x = d.x * 0.333f + h[i].x;",
     "        sm[out + 1].x = d.x * 0.5f + h[i].x;"),
    ("smooth_first", CRC, "        sm[out].x = h[i].x - prev->x;",
     "        sm[out].x = h[i].x + prev->x;"),
    ("smooth_swap", CRC, "        const bVector3 *prev = &e[(i & 1) ^ 1];",
     "        const bVector3 *prev = &e[i & 1];"),
    ("smooth_last", CRC, "        sm[out + 2].z = h[i].z + cur->z;",
     "        sm[out + 2].z = h[i].z;"),

    # ---- the hull shadow
    ("edge_mult", CRC, "    o->x = k * (p->x - c->x) + c->x;",
     "    o->x = (p->x - c->x) + c->x;"),
    ("edge_z", CRC, "    o->z = p->z;\n", "    o->z = c->z;\n"),
    ("edge_uv", CRC,
     "    strip_uv(&gExStripFns, 0.155f, 0.0f);\n    strip_uv(&gExStripFns, 1.0f, 0.0f);",
     "    strip_uv(&gExStripFns, 0.155f, 0.0f);\n    strip_uv(&gExStripFns, 0.0f, 0.0f);"),
    ("edge_order", CRC,
     "    strip_vertex(&gExStripFns, p);\n    strip_vertex(&gExStripFns, &l);",
     "    strip_vertex(&gExStripFns, &l);\n    strip_vertex(&gExStripFns, p);"),
    ("hs_085", CRC, "        q.x = v[i].CompressedPosition[0] * 0.85f;",
     "        q.x = v[i].CompressedPosition[0] * 0.8f;"),
    ("hs_0275", CRC,
     "        q.z = (v[i].CompressedPosition[2] + 0.275f) * 1.0f;",
     "        q.z = v[i].CompressedPosition[2] + 0.2f;"),
    ("hs_h", CRC, "        h = 0.0f + (0.0f - (p.z - position->z)) * k;",
     "        h = (p.z - position->z) * k;"),
    ("hs_cast_y", CRC, "        hullVertArray1[i].y = p.y + h * cs_lightV.y;",
     "        hullVertArray1[i].y = p.y + h * cs_lightV.x;"),
    ("hs_lift", CRC, "                           hull_Origin.z + 0.06f, 0.06f);",
     "                           hull_Origin.z + 0.06f, 0.07f);"),
    ("hs_z", CRC, "                           hull_Origin.z + 0.06f, 0.06f);",
     "                           hull_Origin.z + 0.07f, 0.06f);"),
    ("hs_min3", CRC, "    if (count < 3)\n        return;\n\n    {",
     "    if (count < 4)\n        return;\n\n    {"),
    ("hs_centre", CRC,
     "        const bVector3 *a1 = &hullVertArray3[count / 2];",
     "        const bVector3 *a1 = &hullVertArray3[count / 2 + 1];"),
    ("hs_sun_lo_mult", CRC, "        FancyCarShadowEdgeMult = 1.4f;",
     "        FancyCarShadowEdgeMult = 1.3f;"),
    ("hs_sun_lo_alpha", CRC,
     "        FancyCarShadowEdgeMult = 1.4f;\n        alpha = 0.0f;",
     "        FancyCarShadowEdgeMult = 1.4f;"),
    ("hs_sun_hi", CRC, "    } else if (1.0f < s) {\n        FancyCarShadowEdgeMult = 1.1f;",
     "    } else if (0.9f < s) {\n        FancyCarShadowEdgeMult = 1.1f;"),
    ("hs_mult", CRC, "        FancyCarShadowEdgeMult = f * -0.29999995f + 1.4f;",
     "        FancyCarShadowEdgeMult = f * -0.3f + 1.4f;"),
    ("hs_alpha", CRC, "        alpha = f * alpha;", "        alpha = f * 80.0f;"),
    ("hs_lod2", CRC, "    if (body_lod == 2) {", "    if (body_lod >= 1) {"),
    ("hs_lod_clamp", CRC,
     "        if (1.0f < f)\n            f = 1.0f;\n        else if (f < 0.0f)",
     "        if (2.0f < f)\n            f = 1.0f;\n        else if (f < 0.0f)"),
    ("hs_quads", CRC, "    for (i = 0; i < (count & ~1) - 1; i += 2) {",
     "    for (i = 0; i < (count & ~1) - 2; i += 2) {"),
    ("hs_quad_wrap", CRC,
     "        strip_vertex(&gEStripFns, &hullVertArray3[(i + 2) % count]);",
     "        strip_vertex(&gEStripFns, &hullVertArray3[i + 2]);"),
    ("hs_quad_uv", CRC,
     "        strip_uv(&gEStripFns, 0.0f, 0.0f);\n        strip_uv(&gEStripFns, 0.155f, 0.0f);\n"
     "        strip_uv(&gEStripFns, 0.155f, 0.0f);\n        strip_end",
     "        strip_uv(&gEStripFns, 0.0f, 0.0f);\n        strip_uv(&gEStripFns, 0.155f, 0.0f);\n"
     "        strip_uv(&gEStripFns, 0.0f, 0.0f);\n        strip_end"),
    ("hs_quad_fail", CRC,
     "        if (!strip_begin(&gEStripFns, ri->ShadowRampTexture, 4,\n"
     "                         biased_identity))\n            continue;",
     "        if (!strip_begin(&gEStripFns, ri->ShadowRampTexture, 4,\n"
     "                         biased_identity))\n            break;"),
    ("hs_tex", CRC, "        if (!strip_begin(&gEStripFns, ri->ShadowRampTexture, 4,",
     "        if (!strip_begin(&gEStripFns, ri->ShadowTexture, 4,"),
    ("hs_odd", CRC, "    if ((count & 1)\n", "    if (!(count & 1)\n"),
    ("hs_odd_n", CRC,
     "        && strip_begin(&gEStripFns, ri->ShadowRampTexture, 3,",
     "        && strip_begin(&gEStripFns, ri->ShadowRampTexture, 4,"),
    ("hs_seg_len", CRC, "        int32_t len = seg < 3 ? n : count - first;",
     "        int32_t len = n;"),
    ("hs_seg_n", CRC,
     "        if (!strip_begin(&gExStripFns, ri->ShadowRampTexture, (len + 1) * 2,",
     "        if (!strip_begin(&gExStripFns, ri->ShadowRampTexture, len * 2,"),
    ("hs_seg_fail", CRC, "            first += n;\n            continue;",
     "            continue;"),
    ("hs_seg_close", CRC,
     "        shadow_edge_pair(&hullVertArray3[j < count ? j : 0], &centre,",
     "        shadow_edge_pair(&hullVertArray3[j < count ? j : 1], &centre,"),

    # ---- the grid shadow
    ("gr_fx", CRC,
     "    float fy = fe ? 1.0f : 0.95f, fx = fe ? 1.115f : 0.95f;",
     "    float fy = fe ? 1.0f : 0.95f, fx = fe ? 1.0f : 0.95f;"),
    ("gr_fy", CRC,
     "    float fy = fe ? 1.0f : 0.95f, fx = fe ? 1.115f : 0.95f;",
     "    float fy = 0.95f, fx = fe ? 1.115f : 0.95f;"),
    ("gr_third", CRC, "    const float third = 0.33333334f;",
     "    const float third = 0.3333333f;"),
    ("gr_z", CRC, "            p->z = position->z;\n", "            p->z = 0.0f;\n"),
    ("gr_uv", CRC, "            uv[r * 4 + c][0] = u;",
     "            uv[r * 4 + c][0] = v;"),
    ("gr_centre", CRC,
     "    centre.x = centre.y = centre.z = centre.pad = 0.0f;\n"
     "    eMulVector3(&centre, local_world, &centre);",
     "    centre.x = centre.y = centre.z = centre.pad = 0.0f;"),
    ("gr_topo", CRC, "    if (!fe && topo != NULL) {", "    if (!fe) {"),
    ("gr_rz", CRC, "            rz = -1.0f / nrm[i].z;",
     "            rz = 1.0f / nrm[i].z;"),
    ("gr_nearest", CRC, "                int32_t w = kGridNearestWheel[i];",
     "                int32_t w = kGridNearestWheel[15 - i];"),
    ("gr_wfound", CRC, "                if (found[w]) {", "                if (1) {"),
    ("gr_plane", CRC,
     "                         + (p->y - wp[w].y) * nrm[w].y;",
     "                         + (p->y - wp[w].y) * nrm[w].x;"),
    ("gr_borrowed", CRC, "                    f = 1;\n", ""),
    ("gr_inner", CRC,
     "            if (((i ^ (i >> 1)) & 5) == 5)\n                p->z += 0.08f;",
     "            if (((i ^ (i >> 1)) & 5) == 4)\n                p->z += 0.08f;"),
    ("gr_4", CRC,
     "            if (f && fabsf(p->z - hull_Origin.z) <= 4.0f) {",
     "            if (f && fabsf(p->z - hull_Origin.z) <= 40.0f) {"),
    ("gr_1p5", CRC, "                if (t < 1.5f) {\n                    centre.z",
     "                if (t < 15.0f) {\n                    centre.z"),
    ("gr_centre_z", CRC, "                    centre.z = p->z;\n", ""),
    ("gr_004", CRC, "                    p->z += 0.04f;\n",
     "                    p->z += 0.05f;\n"),
    ("gr_fail_z", CRC, "            p->z = centre.z + 0.04f;\n",
     "            p->z = centre.z;\n"),
    ("gr_fails", CRC, "            fails[i / 4]++;", "            fails[i % 4]++;"),
    ("gr_fe_z", CRC, "            P[i].z = CarShadowElevationFE;\n",
     "            P[i].z = 0.01f;\n"),
    ("gr_fe_inner", CRC,
     "                P[i].z = CarShadowElevationFE + 0.08f;",
     "                P[i].z = CarShadowElevationFE + 0.04f;"),
    ("gr_lo", CRC, "    lo = fe ? 92.0f : 70.0f;", "    lo = fe ? 92.0f : 60.0f;"),
    ("gr_hi", CRC, "    hi = fe ? 92.0f : 140.0f;", "    hi = fe ? 92.0f : 130.0f;"),
    ("gr_fe_a", CRC, "    lo = fe ? 92.0f : 70.0f;", "    lo = fe ? 90.0f : 70.0f;"),
    ("gr_lerp", CRC, "        a = lo + (hi - lo) * ((s - 0.4f) / 0.6f);",
     "        a = lo + (hi - lo) * ((s - 0.4f) / 0.5f);"),
    ("gr_sun_hi", CRC, "    else if (1.0f < s)\n        a = hi;",
     "    else if (0.9f < s)\n        a = hi;"),
    ("gr_rows", CRC, "        if (!(fails[r] + fails[r + 1] < 4))",
     "        if (!(fails[r] + fails[r + 1] < 3))"),
    ("gr_strip_n", CRC,
     "        if (!strip_begin(&gExStripFns, ri->ShadowTexture, 8,",
     "        if (!strip_begin(&gExStripFns, ri->ShadowTexture, 7,"),
    ("gr_order", CRC, "            strip_vertex(&gExStripFns, &P[(r + 1) * 4 + c]);",
     "            strip_vertex(&gExStripFns, &P[r * 4 + c]);"),

    # ---- the cop flares
    ("cop_hl_broken", CRC, "        return (broken & 1) ? 0.0f : 1.0f;",
     "        return (broken & 2) ? 0.0f : 1.0f;"),
    ("cop_hr_wig", CRC, "    if (hash == HASH_HEADLIGHT_RIGHT && !wig)",
     "    if (hash == HASH_HEADLIGHT_RIGHT && wig)"),
    ("cop_fast", CRC, "    int fast = car != NULL && car->CopLights == 2;",
     "    int fast = car != NULL && car->CopLights == 1;"),
    ("cop_red", CRC, "        table = fast ? CopLightsRed : CopLightsRedSlow;",
     "        table = fast ? CopLightsRedSlow : CopLightsRed;"),
    ("cop_blue", CRC, "        table = fast ? CopLightsBlue : CopLightsBlueSlow;",
     "        table = fast ? CopLightsBlue : CopLightsRedSlow;"),
    ("cop_white", CRC, "        table = fast ? CopLightsWhite : CopLightsWhiteSlow;",
     "        table = fast ? CopLightsBlue : CopLightsWhiteSlow;"),
    ("cop_index", CRC,
     "    return table[fast ? (frame & 7) : ((frame >> 1) & 15)] ? 1.0f : 0.0f;",
     "    return table[fast ? (frame & 7) : (frame & 15)] ? 1.0f : 0.0f;"),

    # ---- the light flares
    ("lf_traffic", CRC, "        base_rear = 0.7f;", "        base_rear = 0.75f;"),
    ("lf_night", CRC, "        base_front = 0.75f;", "        base_front = 0.7f;"),
    ("lf_else", CRC, "    else if (lights_on_time_of_day())\n        base_front",
     "    if (lights_on_time_of_day())\n        base_front"),
    ("lf_force_head", CRC, "    if (ForceHeadlights)\n        forced |= 1;", ""),
    ("lf_force_brake", CRC, "    if (ForceBrakelights)\n        forced |= 2;", ""),
    ("lf_force_rev", CRC, "    if (ForceReverselights)\n        forced |= 4;", ""),
    ("lf_force_cop", CRC, "    if (ForceCoplights)\n        forced |= 8;", ""),
    ("lf_frame", CRC,
     "    frame = ri->CarTimebaseStart + (uint32_t)WorldTimeFrames;\n\n    hl_right",
     "    frame = (uint32_t)WorldTimeFrames;\n\n    hl_right"),
    ("lf_head_forced", CRC, "        hl_right += 1.0f;\n        hl_left = hl_right;",
     "        hl_right += 1.0f;"),
    ("lf_head_on", CRC, "            hl_right = base_front + 1.0f;",
     "            hl_right = base_front + 0.5f;"),
    ("lf_head_traffic", CRC,
     "        if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)\n"
     "            on ^= 1;\n        if (on) {\n            hl_right",
     "        if (on) {\n            hl_right"),
    ("lf_brake_forced", CRC, "        bm = base_rear + 1.0f;", "        bm = 1.0f;"),
    ("lf_brake_br", CRC, "        br += 1.0f;\n        bl = bm;", "        bl = bm;"),
    ("lf_brake_thresh", CRC,
     "    } else if (driver != NULL && 0.05f < driver->Brake) {",
     "    } else if (driver != NULL && 0.05f <= driver->Brake) {"),
    ("lf_brake16", CRC, "        float x = driver->Brake * 16.0f;",
     "        float x = driver->Brake * 8.0f;"),
    ("lf_rev_gear", CRC,
     "    if ((forced & 4) || (car != NULL && car->State.CurrentGear == 0)) {",
     "    if ((forced & 4) || (car != NULL && car->State.CurrentGear == 1)) {"),
    ("lf_rev_rl", CRC, "        rr += 1.0f;\n        rl = rr;", "        rr += 1.0f;"),
    ("lf_cop", CRC,
     "    cop = (forced & 8) || (car != NULL && car->CopLights != 0);",
     "    cop = (forced & 8);"),
    ("lf_cop_forced", CRC,
     "    cop = (forced & 8) || (car != NULL && car->CopLights != 0);",
     "    cop = car != NULL && car->CopLights != 0;"),
    ("lf_broken_hl", CRC, "    if (broken & 1)\n        hl_left = 0.0f;", ""),
    ("lf_broken_hr", CRC, "    if (broken & 2)\n        hl_right = 0.0f;", ""),
    ("lf_broken_bl", CRC, "    if (broken & 4)\n        bl = 0.0f;",
     "    if (broken & 8)\n        bl = 0.0f;"),
    ("lf_broken_br", CRC, "    if (broken & 8)\n        br = 0.0f;", ""),
    ("lf_broken_bm", CRC, "    if (broken & 16)\n        bm = 0.0f;", ""),
    ("lf_broken_rl", CRC, "    if (broken & 4)\n        rl = 0.0f;", ""),
    ("lf_broken_rr", CRC, "    if (broken & 8)\n        rr = 0.0f;", ""),
    ("lf_case_hr", CRC,
     "        case HASH_FLARE_HEADLIGHT_RIGHT:    f = hl_right; break;",
     "        case HASH_FLARE_HEADLIGHT_RIGHT:    f = hl_left;  break;"),
    ("lf_case_bm", CRC,
     "        case HASH_FLARE_BRAKELIGHT_MIDDLE:  f = bm;       break;",
     "        case HASH_FLARE_BRAKELIGHT_MIDDLE:  f = bl;       break;"),
    ("lf_case_br", CRC,
     "        case HASH_FLARE_BRAKELIGHT_RIGHT:   f = br;       break;",
     "        case HASH_FLARE_BRAKELIGHT_RIGHT:   f = bm;       break;"),
    ("lf_case_rr", CRC,
     "        case HASH_FLARE_REVERSELIGHT_RIGHT: f = rr;       break;",
     "        case HASH_FLARE_REVERSELIGHT_RIGHT: f = rl;       break;"),
    ("lf_default", CRC, "            if (cop)\n                f = cop_flare",
     "            if (1)\n                f = cop_flare"),
    ("lf_pos", CRC, "        if (0.0f < f) {\n            if (1.0f < f)",
     "        if (0.0f <= f) {\n            if (1.0f < f)"),
    ("lf_clamp", CRC, "            if (1.0f < f)\n                f = 1.0f;\n            if (gERender",
     "            if (gERender"),

    # ---- the driver
    ("dr_need50", CRC, "    float need = 50.0f;", "    float need = 51.0f;"),
    ("dr_opentop", CRC, "    if (!cti->OpenTop)\n", "    if (cti->OpenTop)\n"),
    ("dr_100", CRC,
     "        need = eGetCurrentViewMode() == 3 ? 100.0f : 75.0f;",
     "        need = eGetCurrentViewMode() == 3 ? 101.0f : 75.0f;"),
    ("dr_75", CRC,
     "        need = eGetCurrentViewMode() == 3 ? 100.0f : 75.0f;",
     "        need = eGetCurrentViewMode() == 3 ? 100.0f : 76.0f;"),
    ("dr_force", CRC, "    if (!ForceRenderDriver && !(need < size))",
     "    if (!(need < size))"),
    ("dr_hidden", CRC, "    if (animated_driver_hidden(drv) != 0)\n        return;", ""),
    ("dr_malloc", CRC,
     "    m = eframe_malloc(64);\n    if (m == NULL)\n        return;\n\n"
     "    *m = *biased_local_world;",
     "    m = eframe_malloc(80);\n    if (m == NULL)\n        return;\n\n"
     "    *m = *biased_local_world;"),
    ("dr_off", CRC, "    m->v3.x += off.x;", "    m->v3.x += off.y;"),
    ("dr_w", CRC, "    m->v3.w = 1.0f;\n\n    behind", "\n    behind"),
    ("dr_rot", CRC, "    rot.v3.x = rot.v3.y = rot.v3.z = 0.0f;",
     "    rot.v3.x = rot.v3.y = 0.0f;"),
    ("dr_behind", CRC, "    behind.x = -1.0f;", "    behind.x = 1.0f;"),
    ("dr_cd", CRC, "    cd.z = cam->z - car->State.Position.z;",
     "    cd.z = cam->z;"),
    ("dr_along", CRC, "    if (0.9f < along) {", "    if (0.5f < along) {"),
    ("dr_999", CRC,
     "        if (999.0f < size || (300.0f < size && queued))",
     "        if (1000.0f < size || (300.0f < size && queued))"),
    ("dr_300q", CRC,
     "        if (999.0f < size || (300.0f < size && queued))",
     "        if (999.0f < size || (310.0f < size && queued))"),
    ("dr_300", CRC, "        if (300.0f < size || (150.0f < size && queued))",
     "        if (310.0f < size || (150.0f < size && queued))"),
    ("dr_150", CRC, "        if (300.0f < size || (150.0f < size && queued))",
     "        if (300.0f < size || (160.0f < size && queued))"),
    ("dr_view", CRC,
     "    if (car != NULL && car->pAnimatedDriver != NULL && view->ID != 3",
     "    if (car != NULL && car->pAnimatedDriver != NULL && view->ID != 2"),
    ("dr_enabled", CRC, "        && car->DriverRenderingEnabled)\n", "        )\n"),

    # ---- Render: the start
    ("r_view3", CRC,
     "    if (eGetCurrentViewMode() == 3)\n        pixels = (int32_t)((float)pixels * 0.7f);",
     "    if (eGetCurrentViewMode() == 2)\n        pixels = (int32_t)((float)pixels * 0.7f);"),
    ("r_07", CRC, "        pixels = (int32_t)((float)pixels * 0.7f);",
     "        pixels = (int32_t)((float)pixels * 0.75f);"),
    ("r_min4", CRC, "    if (pixels < 4)\n        return;", "    if (pixels < 5)\n        return;"),
    ("r_malloc_order", CRC,
     "    light_context = eframe_malloc(288);\n    local_world = eframe_malloc(64);",
     "    local_world = eframe_malloc(64);\n    light_context = eframe_malloc(288);"),
    ("r_malloc_test", CRC,
     "        || biased_local_world == NULL || biased_identity == NULL)",
     "        || biased_local_world == NULL)"),
    ("r_crm", CRC, "    eMulMatrix(local_world, &CarRenderMatrix, local_world);",
     "    eMulMatrix(local_world, local_world, &CarRenderMatrix);"),
    ("r_lw_w", CRC,
     "    local_world->v3.w = 1.0f;\n\n    eMulMatrix(&local_to_screenclip",
     "    local_world->v3.w = 0.0f;\n\n    eMulMatrix(&local_to_screenclip"),
    ("r_classify", CRC,
     "                              &local_to_screenclip) == 0)\n        return;",
     "                              &local_to_screenclip) == 2)\n        return;"),
    ("r_eye_w", CRC, "    eye4.w = 1.0f;", "    eye4.w = 0.0f;"),
    ("r_qlm_set", CRC, "    if (PrintQueryLightMat)\n        QueryLightMat = 1;", ""),
    ("r_qlm_clear", CRC, "    if (PrintQueryLightMat)\n        QueryLightMat = 0;", ""),
    ("r_hack", CRC,
     "    set_up_light_context(light_context, local_world, &hack_man_matrix, &eye4,",
     "    set_up_light_context(light_context, local_world, view->WorldViewMatrix, &eye4,"),
    ("r_skin_default", CRC, "                                    ri->pRideInfo->SkinNumber, 1);",
     "                                    ri->pRideInfo->SkinNumber, 0);"),
    ("r_skin_type", CRC, "    (void)cartypeinfo_get_skin_info(ri->pCarTypeInfo->Type,",
     "    (void)cartypeinfo_get_skin_info(ri->pRideInfo->Type,"),
    ("r_env18", CRC,
     "    disable_env = disable_env_tires = (EnableEnvMap == 0 || size < 18.0f);",
     "    disable_env = disable_env_tires = (EnableEnvMap == 0 || size < 17.0f);"),
    ("r_env", CRC,
     "    disable_env = disable_env_tires = (EnableEnvMap == 0 || size < 18.0f);",
     "    disable_env = disable_env_tires = (size < 18.0f);"),
    ("r_lod_first", CRC,
     "    if (size < CarLodPixelSizes[0] && ri->Body[1].Solid != NULL) {",
     "    if (size < CarLodPixelSizes[0]) {"),
    ("r_lod_next", CRC, "                 && ri->Body[body_lod + 1].Solid != NULL);",
     "                 && ri->Body[body_lod].Solid != NULL);"),
    ("r_lod_le", CRC, "        } while (size < CarLodPixelSizes[body_lod]\n",
     "        } while (size <= CarLodPixelSizes[body_lod]\n"),
    ("r_lod_tire", CRC, "            body_lod++;\n            tire_lod++;",
     "            body_lod++;"),
    ("r_air_wheels", CRC,
     "    if (body_lod >= 3 && car != NULL && car->State.nWheelsTouchingGround == 0",
     "    if (body_lod >= 3 && car != NULL && car->State.nWheelsTouchingGround <= 1"),
    ("r_air_under", CRC,
     "        && ri->PartCuller[CULLABLE_CAR_PART_UNDERNEATH].State[2])",
     "        && ri->PartCuller[CULLABLE_CAR_PART_SHADOW].State[2])"),
    ("r_air_lod", CRC, "        body_lod = 2;\n    if (ForceCarLOD",
     "        body_lod = 1;\n    if (ForceCarLOD"),
    ("r_force_car", CRC, "    if (ForceCarLOD != -1)\n        body_lod = ForceCarLOD;", ""),
    ("r_force_tire", CRC, "    if (ForceTireLOD != -1)\n        tire_lod = ForceTireLOD;", ""),
    ("r_inside_dist", CRC,
     "    if (body_lod == 0 && dist < 4.0f && view->ID == 1) {",
     "    if (body_lod == 0 && dist < 3.0f && view->ID == 1) {"),
    ("r_inside_id", CRC,
     "    if (body_lod == 0 && dist < 4.0f && view->ID == 1) {",
     "    if (body_lod == 0 && dist < 4.0f && view->ID != 2) {"),
    ("r_inside_lod", CRC,
     "    if (body_lod == 0 && dist < 4.0f && view->ID == 1) {",
     "    if (body_lod <= 1 && dist < 4.0f && view->ID == 1) {"),
    ("r_inside_up", CRC, "        eye.z += 0.5f;\n", "        eye.z += 0.25f;\n"),
    ("r_inside_down", CRC, "        eye.z -= 0.5f;\n", ""),
    ("r_dist_z", CRC,
     "    dz = camera->CurrentKey.Position.z - local_world->v3.z;",
     "    dz = 0.0f;"),
    ("r_bias_z", CRC, "    biased_local_world->v3.z += 0.01f;",
     "    biased_local_world->v3.z += 0.02f;"),
    ("r_bias_order", CRC,
     "    eview_bias_matrix_for_z_sorting(view, biased_local_world, bias);\n"
     "    eview_bias_matrix_for_z_sorting(view, biased_identity, bias);",
     "    eview_bias_matrix_for_z_sorting(view, biased_identity, bias);\n"
     "    eview_bias_matrix_for_z_sorting(view, biased_local_world, bias);"),
    ("r_bi_pos", CRC, "    biased_identity->v3.x = position->x;",
     "    biased_identity->v3.x = 0.0f;"),
    ("r_bi_w", CRC, "    biased_identity->v3.w = 1.0f;", "    biased_identity->v3.w = 0.0f;"),
    ("r_pre", CRC, "    pre_translate.v3.x = -position->x;",
     "    pre_translate.v3.x = position->x;"),
    ("r_pre_order", CRC,
     "    eMulMatrix(biased_identity, &pre_translate, biased_identity);",
     "    eMulMatrix(biased_identity, biased_identity, &pre_translate);"),
    ("r_cull_eye", CRC, "    carrenderinfo_cull_parts(ri->PartCuller, &eye);",
     "    carrenderinfo_cull_parts(ri->PartCuller, (const bVector3 *)&eye4);"),
    ("r_body_flags", CRC, "    body_flags = disable_env | extra_render_flags;",
     "    body_flags = extra_render_flags;"),

    # ---- Render: the shadows' conditions
    ("sc_topo", CRC, "    if (topo != NULL)\n        hull_Origin.z", "    if (0)\n        hull_Origin.z"),
    ("sc_hull_lod", CRC,
     "    if (body_lod < 3 && !fe && colbody != NULL && body0_solid != NULL",
     "    if (body_lod < 2 && !fe && colbody != NULL && body0_solid != NULL"),
    ("sc_hull_fe", CRC,
     "    if (body_lod < 3 && !fe && colbody != NULL && body0_solid != NULL",
     "    if (body_lod < 3 && colbody != NULL && body0_solid != NULL"),
    ("sc_hull_body0", CRC,
     "    if (body_lod < 3 && !fe && colbody != NULL && body0_solid != NULL",
     "    if (body_lod < 3 && !fe && colbody != NULL"),
    ("sc_hull_ramp", CRC,
     "        && ri->ShadowRampTexture != NULL && view->ID != 3)",
     "        && view->ID != 3)"),
    ("sc_hull_view", CRC,
     "        && ri->ShadowRampTexture != NULL && view->ID != 3)",
     "        && ri->ShadowRampTexture != NULL)"),
    ("sc_grid_tex", CRC, "    if (body0_solid != NULL && ri->ShadowTexture != NULL\n",
     "    if (body0_solid != NULL\n"),
    ("sc_grid_wheels", CRC,
     "        && !(car != NULL && car->State.nWheelsTouchingGround == 4",
     "        && !(car != NULL && car->State.nWheelsTouchingGround >= 3"),
    ("sc_grid_cull", CRC,
     "             && !ri->PartCuller[CULLABLE_CAR_PART_SHADOW].State[2]))",
     "             && !ri->PartCuller[CULLABLE_CAR_PART_UNDERNEATH].State[2]))"),

    # ---- Render: the body, mirrors, plates and scuffs
    ("b_rlm_hash", CRC, "        model_replace_light_material(m, HASH_CARSKIN,\n",
     "        model_replace_light_material(m, HASH_CARSKIN + 1,\n"),
    ("b_mirror_lod", CRC, "    if (body_lod < 2) {\n        int32_t k;",
     "    if (body_lod < 3) {\n        int32_t k;"),
    ("b_mirror_dmg", CRC,
     "            if (car_damage != NULL && !(item_level(car_damage, k) < 2))",
     "            if (car_damage != NULL && !(item_level(car_damage, k) < 3))"),
    ("b_mirror_item", CRC,
     "            if (car_damage != NULL && !(item_level(car_damage, k) < 2))",
     "            if (car_damage != NULL && !(item_level(car_damage, 1 - k) < 2))"),
    ("b_mirror_rlm", CRC,
     "            model_replace_light_material(&ri->SideMirrors[k], HASH_CARSKIN,",
     "            model_replace_light_material(&ri->SideMirrors[0], HASH_CARSKIN,"),
    ("b_plate_lod", CRC, "    if (body_lod < 3) {\n        int32_t k;",
     "    if (body_lod < 2) {\n        int32_t k;"),
    ("b_plate_cull", CRC,
     "            if (!ri->PartCuller[CULLABLE_CAR_PART_SIDE_FRONT + k].State[2])",
     "            if (!ri->PartCuller[CULLABLE_CAR_PART_SIDE_REAR - k].State[2])"),
    ("b_plate_item", CRC,
     "            if (car_damage != NULL && !(item_level(car_damage, 2 + k) < 2))",
     "            if (car_damage != NULL && !(item_level(car_damage, 2 + k) < 1))"),
    ("b_scuff_lod", CRC, "    if (body_lod < 2 && car_damage != NULL\n",
     "    if (body_lod < 3 && car_damage != NULL\n"),
    ("b_scuff_thresh", CRC,
     "        && 0.02f < bodydamage_get_visible_total_damage(&car_damage->TheBodyDamage))",
     "        && 0.02f <= bodydamage_get_visible_total_damage(&car_damage->TheBodyDamage))"),
    ("b_scuff_flags", CRC,
     "        model_render(&ri->Scuffs, biased_local_world, NULL,\n                     extra_render_flags);",
     "        model_render(&ri->Scuffs, biased_local_world, NULL,\n                     body_flags);"),

    # ---- Render: turned
    ("t_signed", CRC,
     "        float deg = (float)(int32_t)driver->Steering * 0.0054931640625f;",
     "        float deg = (float)(int16_t)driver->Steering * 0.0054931640625f;"),
    ("t_lo", CRC, "        turned = 6.0f < deg && deg < 354.0f;",
     "        turned = 5.0f < deg && deg < 354.0f;"),
    ("t_hi", CRC, "        turned = 6.0f < deg && deg < 354.0f;",
     "        turned = 6.0f < deg && deg < 350.0f;"),

    # ---- Render: the tyres and the blur
    ("ty_lod", CRC, "    if (body_lod < 3) {\n        bMatrix4 *M = eframe_malloc(256);",
     "    if (body_lod < 4) {\n        bMatrix4 *M = eframe_malloc(256);"),
    ("ty_malloc", CRC,
     "        bMatrix4 *M = eframe_malloc(256);\n        eLightContext *LC = eframe_malloc(1152);\n\n"
     "        if (M != NULL && LC != NULL) {\n            uint32_t v0",
     "        eLightContext *LC = eframe_malloc(1152);\n        bMatrix4 *M = eframe_malloc(256);\n\n"
     "        if (M != NULL && LC != NULL) {\n            uint32_t v0"),
    ("ty_fe", CRC, "            if (fe)\n                v0 = v1 = v2 = v3 = 1;", ""),
    ("ty_turned", CRC, "            if (turned)\n                v0 = v1 = 1;", ""),
    ("ty_tl", CRC, "            tl = tire_lod < 3 ? tire_lod : 2;",
     "            tl = tire_lod < 2 ? tire_lod : 1;"),
    ("ty_R", CRC, "            eRotateZ(&R, &R, 0x8000);", "            eRotateZ(&R, &R, 0x4000);"),
    ("ty_v0_pre", CRC,
     "                render_wheel_part(&ri->Tires[tl][0], &M[0], &LC[0], &R,",
     "                render_wheel_part(&ri->Tires[tl][0], &M[0], &LC[0], NULL,"),
    ("ty_v3_pre", CRC,
     "                render_wheel_part(&ri->Tires[tl][1], &M[3], &LC[3], &R,",
     "                render_wheel_part(&ri->Tires[tl][1], &M[3], &LC[3], NULL,"),
    ("ty_v2_rear", CRC,
     "                render_wheel_part(&ri->Tires[tl][1], &M[2], &LC[2], NULL,",
     "                render_wheel_part(&ri->Tires[tl][0], &M[2], &LC[2], NULL,"),
    ("ty_v1_mat", CRC, "                                  &tire_matrices[1], biased_local_world,",
     "                                  &tire_matrices[2], biased_local_world,"),
    ("ty_v1_cull", CRC,
     "            uint32_t v1 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_FR].State[2];",
     "            uint32_t v1 = ri->PartCuller[CULLABLE_CAR_PART_TIRE_FL].State[2];"),
    ("ty_flags", CRC, "            uint32_t tflags = disable_env_tires | extra_render_flags;",
     "            uint32_t tflags = extra_render_flags;"),
    ("wp_order", CRC, "        eMulMatrix(&t, pre, part);", "        eMulMatrix(&t, part, pre);"),
    ("wp_hack", CRC, "    set_up_light_context(lc, m, view->WorldViewMatrix, eye, view);",
     "    set_up_light_context(lc, m, &hack_man_matrix, eye, view);"),
    ("bl_tl", CRC, "            if (tl < 2 && !in_front_end()) {",
     "            if (tl < 3 && !in_front_end()) {"),
    ("bl_fe", CRC, "            if (tl < 2 && !in_front_end()) {",
     "            if (tl < 2) {"),
    ("bl_malloc", CRC, "                eLightContext *B = eframe_malloc(1152);",
     "                eLightContext *B = eframe_malloc(1168);"),
    ("bl_flags", CRC, "                    uint32_t bflags = extra_render_flags | 1;",
     "                    uint32_t bflags = extra_render_flags;"),
    ("bl_copy", CRC, "                    memcpy(B, LC, 1152);", "                    memcpy(B, LC, 288);"),
    ("bl_left", CRC,
     "                    if (ri->PartCuller[CULLABLE_CAR_PART_TIRE_BLURS_LEFT].State[2]) {",
     "                    if (ri->PartCuller[CULLABLE_CAR_PART_TIRE_BLURS_RIGHT].State[2]) {"),
    ("bl_right", CRC,
     "                    if (ri->PartCuller[CULLABLE_CAR_PART_TIRE_BLURS_RIGHT].State[2]) {",
     "                    if (1) {"),
    ("bl_90", CRC,
     "                        float b0 = carrenderinfo_calculate_tire_blur(ri, 0) * 90.0f;",
     "                        float b0 = carrenderinfo_calculate_tire_blur(ri, 0) * 80.0f;"),
    ("bl_b3", CRC,
     "                        float b3 = carrenderinfo_calculate_tire_blur(ri, 3) * 90.0f;",
     "                        float b3 = carrenderinfo_calculate_tire_blur(ri, 2) * 90.0f;"),
    ("bl_thresh", CRC, "                        if (v1 && 0.1f < b1) {",
     "                        if (v1 && 0.2f < b1) {"),
    ("bl_v3", CRC, "                        if (v3 && 0.1f < b3) {",
     "                        if (0.1f < b3) {"),
    ("bl_alpha", CRC, "                            B[3].LocalColourMatrix.v3.w = b3;",
     "                            B[3].LocalColourMatrix.v3.z = b3;"),
    ("bl_model", CRC,
     "                            model_render(&ri->TireBlur[1], &M[2], &B[2], bflags);",
     "                            model_render(&ri->TireBlur[0], &M[2], &B[2], bflags);"),

    # ---- Render: the brakes
    ("br_solid", CRC, "    if (ri->Brakes[0].Solid != NULL && body_lod < 2) {",
     "    if (body_lod < 2) {"),
    ("br_lod", CRC, "    if (ri->Brakes[0].Solid != NULL && body_lod < 2) {",
     "    if (ri->Brakes[0].Solid != NULL && body_lod < 3) {"),
    ("br_turned", CRC, "        if (turned || in_front_end())\n            w0 = w1 = 1;",
     "        if (in_front_end())\n            w0 = w1 = 1;"),
    ("br_fe", CRC, "        if (turned || in_front_end())\n            w0 = w1 = 1;",
     "        if (turned)\n            w0 = w1 = 1;"),
    ("br_any", CRC, "        if (w0 | w3 | w2 | w1) {", "        if (w0 | w3 | w2) {"),
    ("br_malloc", CRC,
     "            eLightContext *LC = eframe_malloc(1152);\n\n            if (M != NULL && LC != NULL) {\n"
     "                // The left",
     "            eLightContext *LC = eframe_malloc(1024);\n\n            if (M != NULL && LC != NULL) {\n"
     "                // The left"),
    ("br_F", CRC, "                    F.v1.y = -1.0f;", "                    F.v1.y = 1.0f;"),
    ("br_w03", CRC, "                if (w0 | w3) {", "                if (w0) {"),
    ("br_flags", CRC,
     "                                          extra_render_flags);\n                    if (w3)",
     "                                          0);\n                    if (w3)"),
    ("br_w2_model", CRC,
     "                    render_wheel_part(&ri->Brakes[1], &M[2], &LC[2], NULL,",
     "                    render_wheel_part(&ri->Brakes[0], &M[2], &LC[2], NULL,"),

    # ---- Render: the wipers
    ("wi_size", CRC, "    if (40.0f < size && car != NULL", "    if (41.0f < size && car != NULL"),
    ("wi_state", CRC, "        && (car->WiperState\n", "        && (0\n"),
    ("wi_on", CRC, "            || ((int32_t)car->WiperOnTime <= WorldTimeFrames",
     "            || ((int32_t)car->WiperOnTime < WorldTimeFrames"),
    ("wi_off", CRC, "                && WorldTimeFrames < (int32_t)car->WiperOffTime))) {",
     "                && WorldTimeFrames <= (int32_t)car->WiperOffTime))) {"),
    ("wi_signed", CRC, "            || ((int32_t)car->WiperOnTime <= WorldTimeFrames",
     "            || (car->WiperOnTime <= (uint32_t)WorldTimeFrames"),
    ("wi_anim", CRC, "            if (solid == NULL || solid->pRigidAnimation == NULL)",
     "            if (solid == NULL)"),
    ("wi_start", CRC, "                (int16_t)((car->WiperOnTime & 0x3fff) | 0xc000);",
     "                (int16_t)((car->WiperOnTime & 0x1fff) | 0xc000);"),
    ("wi_order", CRC,
     "            w->RigidAnimationStartTime =\n"
     "                (int16_t)((car->WiperOnTime & 0x3fff) | 0xc000);\n"
     "            m = eframe_malloc(64);\n            if (m == NULL)\n                continue;\n",
     "            m = eframe_malloc(64);\n            if (m == NULL)\n                continue;\n"
     "            w->RigidAnimationStartTime =\n"
     "                (int16_t)((car->WiperOnTime & 0x3fff) | 0xc000);\n"),
    ("wi_pivot", CRC, "            bMulMatrix(m, biased_local_world, &solid->PivotMatrix);",
     "            bMulMatrix(m, &solid->PivotMatrix, biased_local_world);"),
    ("wi_flags", CRC, "            model_render(w, m, NULL, 0);",
     "            model_render(w, m, NULL, extra_render_flags);"),
]

# Mutations that change nothing any scenario can see, and why.
EQUIVALENT = {
    # From i = 1 the first pass sets V[1] against itself: the cross
    # product is 0 * a - 0 * b, 0 for every finite point, so j runs down
    # to 0, s stays 1 and V[1] is swapped with itself.
    "chain_i": "i = 1 swaps V[1] with itself for finite points",
    # smooth_shadow_corners gives three points a corner, so count is 3n and
    # the last strip's count - first is n as well.
    "hs_seg_len": "count is always 3n, so the last third is n too",
    # base_rear is 0 or 0.7, so base_rear + 1 is at least 1. bm and bl,
    # which copies it, are only two flares' intensities, clamped to 1.
    "lf_brake_forced": "base_rear + 1 and 1 both clamp to 1",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script(m.table)
    base = m.run(sc)
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

    for mut in todo:
        name, rel, before, after = mut
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

    m = Model()
    sc = script(m.table)
    lines = m.run(sc)
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
