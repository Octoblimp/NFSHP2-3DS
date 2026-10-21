#!/usr/bin/env python3
"""Cross-check animdriver.c and eanim.c's posed draw against the retail
image, run in mipsemu (TASKS 83).

The model is the image: AnimatedDriver.obj's code as shipped, from the
players (BeginAnimation 0x001a9098 .. CancelAnimation 0x001aa6c0) through
the queue, the looks and drives backwards, the collisions, the steering's
frame and BuildQuaternionTable (0x001aa2f0), InitAnimatedDriver's fix-up
(0x001a9238) and Render (0x001a9a30); and under them eAnimation.obj's
solids (eFindAnimationSolid, GetRotation, SetRotation, GetRotations,
GetTranslation, GetAnimationSolid), the posed Render (0x001a6b80) and
PoseMatrixRecursive (0x001a6e00), with SplineSeek, bRandom, bSlerp, bMult,
bConjugate, bNormalize, bQuaternionToMatrix, eMulMatrix and eMulVector.
Stubbed, as the harness stubs them: eGetCurrentViewMode, GetLookbackCar
and CalculateLookbackAngle, which answer what the script says;
DetermineVisibleStrips, RenderStrips and eModel::Render, the renderer's,
which print what they are handed; and bMalloc, which fills with 0xa5 as
the harness's does. The harness (tools/src/animdriver_test.c) runs the
port's code and prints the same lines.

The script sets up, the same on both sides:

    CT type open            a car type's OpenTop
    CAR c type ride drv     car c: its type, its RideInfo's Type, and a
                            CarDriver or none
    STEER c v               car c's CarDriver's steering
    CHAR i name             character i's BodyTypeName
    DRV d car char wiggle   driver d: both players cancelled, the shift
                            animation's name, SetupSteeringFrame
    LOOK car angle cop      what GetLookbackCar and CalculateLookbackAngle
                            answer (car -1: none)
    VM m                    the view mode
    W t / WE bits / WL n    WorldTime, WorldTimeElapsed, WorldLoopCounter
    FIX f / SEED s          AnimatedDriverNeedsFixup, bDefaultSeed
    TP t k v                AnimationInfoTable row t's word k
    SOL s hash nodes frames rot trans   an eAnimationSolid on the keys
    LINK s / UNLINK s       onto eAnimationSolidList's tail, or off it
    ANIM a h1 s1 h2 s2      an eAnimation's two names and solids
    NODE a i p first next o2b.. t..     a bone of anim a's tree
    MS a n                  anim a's model on a solid with n bones
    DA d lod a / DM d lod m the driver's animation or plain model
    FL force override       ForceAnimatedDriverLOD, OverrideAnimatedDriverLOD
    BS n x y z              nBoneScale and vBoneScale
    FB pos end / VIS v / X w..   the frame malloc, the visibility, the matrix

and runs each of the functions above, printing what it answers and the
driver after it: both players (their row, start, end and pause), the two
flags, the looking-back type, the spline's words and the seed.

The keys are random unit quaternions, 16 bits a lane as the bundles have
them, on solids of the retail shapes: DRIVER_ANIM01's 42 bones and 262
frames, DRIVER_SHIFT01's 31, and the two pre-race waves. The trees are
random 42-bone trees with random bone matrices.

Checked against the image, not run: AnimationInfoTable and the steering's
wiggle against 0x003111f8 and 0x00311100, the blackball tables, and the
globals' gp offsets.

    python tools/animdriver_check.py
    python tools/animdriver_check.py --mutate [--only a,b]
    python tools/animdriver_check.py --dump out/animdriver
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from bhash import bhash

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/animdriver_test.c"
AD = "3DS Files/source/animdriver.c"
EA = "3DS Files/source/eanim.c"
SOURCES = [HARNESS, AD, EA] + ["3DS Files/source/%s.c" % n for n in (
    "banim", "bquat", "bmath", "bmathtab", "emath", "eframe", "bmatrix")]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = 0x003358f0
F = {
    "BeginAnimation": 0x001a9098,
    "ReleasePausedFrame": 0x001a9100,
    "PlayerRelease": 0x001a9160,
    "GetFrameNumber": 0x001a91b8,
    "CancelAnimation": 0x001aa6c0,
    "InitAnimatedDriver": 0x001a9238,
    "SetupSteeringFrame": 0x001a9460,
    "Render": 0x001a9a30,
    "CancelAll": 0x001a9b30,
    "ReleaseAll": 0x001a9b70,
    "BeginGearChange": 0x001a9bb0,
    "BeginDrivingBackwards": 0x001a9bb8,
    "EndDrivingBackwards": 0x001a9bd8,
    "HandleDrivingBackwards": 0x001a9c00,
    "BeginLookingBackwards": 0x001a9c40,
    "EndLookingBackwards": 0x001a9c68,
    "HandleLookingBackwards": 0x001a9cb8,
    "BeginCollision": 0x001a9e28,
    "QueueAnimation": 0x001a9ef8,
    "GetLengthOfQueued": 0x001a9fb8,
    "FindAnimation": 0x001a9ff0,
    "ReleaseAnimation": 0x001aa040,
    "CalculateSteeringFrameNumber": 0x001aa0a0,
    "QueueRandomAnimations": 0x001aa1e8,
    "BuildQuaternionTable": 0x001aa2f0,
    "Blackballed": 0x001a8f78,
    "BeginAPreRaceAnimation": 0x0019c078,
}
VIEW_MODE = 0x00107cd8          # eGetCurrentViewMode__Fv
LOOKBACK_CAR = 0x0015c680       # GetLookbackCar__FP3CarPb
LOOKBACK_ANGLE = 0x0015c5a8     # CalculateLookbackAngle__FP3CarT0PC8bMatrix4
VISIBLE = 0x0010d390            # DetermineVisibleStrips__6eModelPC8bMatrix4ii
RENDER_STRIPS = 0x0010dd58      # RenderStrips__6eModelP8bMatrix4P13eLight..T1
EMODEL_RENDER = 0x0010dc80      # Render__6eModelP8bMatrix4P13eLightContextUi
BMALLOC = 0x002577c0            # bMalloc__FiPCcii

G_WT = GP - 19568               # WorldTime
G_WE = GP - 19560               # WorldTimeElapsed
G_WL = GP - 19552               # WorldLoopCounter
G_FIX = GP - 21376              # AnimatedDriverNeedsFixup
G_FORCE = GP - 19248            # ForceAnimatedDriverLOD
G_OVERRIDE = GP - 19244         # OverrideAnimatedDriverLOD
G_SEED = GP - 14472             # bDefaultSeed
G_SOLIDS = GP - 19400           # eAnimationSolidList
G_CTI = GP - 20616              # CarTypeInfoArray
G_POS = GP - 19388              # CurrentBufferPos
G_END = GP - 19384              # CurrentBufferEnd
G_FAILED = GP - 19372           # FrameMallocFailed
G_AMOUNT = GP - 19368           # FrameMallocFailAmount
G_NBONE = GP - 19408            # nBoneScale
VBONE = 0x003110d0              # vBoneScale
TABLE = 0x003111f8              # AnimationInfoTable
WIGGLE = 0x00311100             # the steering's wiggle, 62 floats
BB_CAR = 0x00311428             # blackballed by car type, 21 pairs
BB_ROOF = 0x003114d0            # under a roof, 2
BB_COP = 0x003114e0             # for a cop, 8

DRIVERS = 0x01000000            # 160 each
CARS = 0x01001000               # 0x100 each
RIDES = 0x01001800              # 16 each
CDRV = 0x01002000               # 0x400 each, the steering at +528
CHARS = 0x01003000              # 0x80 each, BodyTypeName at +36
CTYPES = 0x01004000             # 1376 each
NUM_TYPES = 64
SOLIDS = 0x0101a000             # 96 each
ANIMS = 0x0101a400              # 80 each
ESOLIDS = 0x0101a600            # 192 each
NODES = 0x0101b000              # 0x1000 each
MODELS = 0x0101d000             # 24 each
MTX = 0x0101d100
QOUT = 0x0101d200               # 42 quaternions
TOUT = 0x0101d4c0
FRAME = 0x0101e000
FRAME_BYTES = 8192
KEYS = 0x01020000

NUM_BONES = 42


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    v &= 0xffffffff
    return v - 0x100000000 if v & 0x80000000 else v


def words(ws):
    return " ".join("%08x" % w for w in ws)


class Model(object):
    def __init__(self):
        self.e = retail_model.emu(retail=True, ieee=True)
        e = self.e
        self.view_mode = 0
        self.look = (-1, 0, 0)
        self.vis = 1
        self.out = []
        self.keys_at = KEYS
        self.rot = {}
        e.stub(VIEW_MODE, lambda e: self.view_mode)
        e.stub(LOOKBACK_CAR, self.lookback_car)
        e.stub(LOOKBACK_ANGLE, lambda e: self.look[1] & 0xffff)
        e.stub(VISIBLE, self.visible)
        e.stub(RENDER_STRIPS, self.strips)
        e.stub(EMODEL_RENDER, self.emodel)
        e.stub(BMALLOC, self.malloc)
        e.put32(G_SOLIDS, G_SOLIDS)
        e.put32(G_SOLIDS + 4, G_SOLIDS)
        e.put32(G_CTI, CTYPES)
        for t in range(NUM_TYPES):
            e.write(CTYPES + t * 1376, bytes(1376))
            e.put32(CTYPES + t * 1376 + 1332, t)
        e.put32(G_POS, FRAME)
        e.put32(G_END, FRAME + FRAME_BYTES)

    # ---- the stubs

    def malloc(self, e):
        n = s32(e.reg[4])
        p = e.alloc(n, 16)
        e.write(p, b"\xa5" * n)
        return p

    def lookback_car(self, e):
        car, _angle, cop = self.look
        e.write(e.reg[5] & 0xffffffff, bytes([cop & 0xff]))
        return 0 if car < 0 else CARS + car * 0x100

    def where(self, p):
        if FRAME <= p < FRAME + FRAME_BYTES:
            return "f+%d" % (p - FRAME)
        if p == MTX:
            return "in"
        return "?"

    def anim_of_model(self, p):
        k, r = divmod(p - 8 - ANIMS, 80)
        return k if r == 0 and 0 <= k < 2 else -1

    def visible(self, e):
        m, mtx = e.reg[4] & 0xffffffff, e.reg[5] & 0xffffffff
        self.out.append(" vis(%d,%s,%d,%d) %s" % (
            self.anim_of_model(m), self.where(mtx), s32(e.reg[6]),
            s32(e.reg[7]), words(struct.unpack("<16I", e.read(mtx, 64)))))
        return self.vis

    def strips(self, e):
        m, mtx = e.reg[4] & 0xffffffff, e.reg[5] & 0xffffffff
        bones = e.reg[8] & 0xffffffff
        solid = e.u32(m + 12)
        n = s32(e.u32(solid + 160)) if solid else 0
        s = " strips(%d,%s,%x,%x,%s)" % (
            self.anim_of_model(m), self.where(mtx), e.reg[6] & 0xffffffff,
            e.reg[7] & 0xffffffff, self.where(bones))
        if n > 0:
            s += " " + words(struct.unpack("<%dI" % (16 * n),
                                           e.read(bones, 64 * n)))
        self.out.append(s)
        return 0

    def emodel(self, e):
        m, mtx = e.reg[4] & 0xffffffff, e.reg[5] & 0xffffffff
        k, r = divmod(m - MODELS, 24)
        self.out.append(" emodel(%d,%s,%x,%x)" % (
            k if r == 0 and 0 <= k < 3 else -1, self.where(mtx),
            e.reg[6] & 0xffffffff, e.reg[7] & 0xffffffff))
        return 0

    # ---- printing

    def driver(self, d):
        e = self.e
        a = DRIVERS + d * 160
        s = " |"
        for i in range(2):
            p = a + 112 + 16 * i
            info = e.u32(p)
            k, r = divmod(info - TABLE, 36)
            row = k if r == 0 and 0 <= k < 14 else (-1 if info == 0 else -2)
            s += " p%d=%d,%d,%d,%d" % (i, row, s32(e.u32(p + 4)),
                                      s32(e.u32(p + 8)), s32(e.u32(p + 12)))
        s += " lb=%d db=%d cur=%d" % (
            s32(e.u8(a + 104) << 24) >> 24, s32(e.u8(a + 105) << 24) >> 24,
            s32(e.u32(a + 108)))
        sp = e.u32(a + 28)
        if sp:
            s += " spl=%s,%d,%d" % (
                ",".join("%08x" % e.u32(sp + o)
                         for o in (0, 4, 8, 12, 32, 36, 40)),
                s16(e.u16(sp + 44)), s16(e.u16(sp + 46)))
        s += " seed=%08x" % e.u32(G_SEED)
        return s

    def call(self, name, *args):
        return self.e.call(F[name], *args)

    # ---- the script

    def run(self, ops):
        e = self.e
        lines = []
        for op in ops:
            t = op.split()
            c = t[0]
            i = lambda k: int(t[k], 0)          # noqa: E731
            h = lambda k: int(t[k], 16)         # noqa: E731
            drv = lambda: DRIVERS + i(1) * 160  # noqa: E731
            if c == "TABLE":
                for r in range(14):
                    a = TABLE + r * 36
                    w = [e.u32(a + 4 * k) for k in range(9)]
                    name = b""
                    if w[1]:
                        while e.u8(w[1] + len(name)):
                            name += bytes([e.u8(w[1] + len(name))])
                    lines.append("TABLE %d: %d %s %08x %d %d %d %d %d %d" % (
                        r, s32(w[0]), name.decode("latin-1"), w[2],
                        *[s32(x) for x in w[3:]]))
            elif c == "CT":
                e.write(CTYPES + i(1) * 1376 + 231, bytes([i(2) & 0xff]))
            elif c == "CAR":
                car = CARS + i(1) * 0x100
                e.write(car, bytes(0x100))
                e.put32(car + 12, CTYPES + i(2) * 1376)
                e.put32(RIDES + i(1) * 16, i(3))
                e.put32(car + 16, RIDES + i(1) * 16)
                e.put32(car + 44, CDRV + i(1) * 0x400 if i(4) else 0)
            elif c == "STEER":
                e.write(CDRV + i(1) * 0x400 + 528, struct.pack("<H", i(2)))
            elif c == "CHAR":
                name = t[2].encode("latin-1")
                e.write(CHARS + i(1) * 0x80 + 36, name + bytes(24 - len(name)))
            elif c == "DRV":
                a = drv()
                e.write(a, bytes(144))
                e.put32(a, 0 if i(2) < 0 else CARS + i(2) * 0x100)
                e.put32(a + 32, 0 if i(3) < 0 else CHARS + i(3) * 0x80)
                self.call("CancelAnimation", a + 112)
                self.call("CancelAnimation", a + 128)
                e.put32(a + 96, i(4))
                e.put32(a + 92, bhash("DRIVER_SHIFT01"))
                self.call("SetupSteeringFrame", a)
                lines.append("DRV %d:%s" % (i(1), self.driver(i(1))))
            elif c == "LOOK":
                self.look = (i(1), i(2), i(3))
            elif c == "VM":
                self.view_mode = i(1)
            elif c == "W":
                e.put32(G_WT, i(1))
            elif c == "WE":
                e.put32(G_WE, h(1))
            elif c == "WL":
                e.put32(G_WL, i(1))
            elif c == "FIX":
                e.put32(G_FIX, i(1))
            elif c == "SEED":
                e.put32(G_SEED, h(1))
            elif c == "TP":
                v = h(3) if i(2) == 2 else i(3)
                e.put32(TABLE + i(1) * 36 + 4 * i(2), v)
            elif c == "SOL":
                s = SOLIDS + i(1) * 96
                rot = Path(t[5]).read_bytes()
                tr = Path(t[6]).read_bytes()
                rp = self.keys_at
                tp = (rp + len(rot) + 15) & ~15
                self.keys_at = (tp + len(tr) + 15) & ~15
                e.write(rp, rot)
                e.write(tp, tr)
                self.rot[i(1)] = (rp, len(rot))
                e.write(s, bytes(96))
                e.put32(s + 64, h(2))
                e.write(s + 68, struct.pack("<HH", i(4), i(3)))
                e.put32(s + 72, len(rot) // 8)
                e.put32(s + 76, rp)
                e.put32(s + 80, len(tr) // 16)
                e.put32(s + 84, tp)
            elif c == "LINK":
                s = SOLIDS + i(1) * 96
                last = e.u32(G_SOLIDS + 4)
                e.put32(s, G_SOLIDS)
                e.put32(s + 4, last)
                e.put32(last, s)
                e.put32(G_SOLIDS + 4, s)
            elif c == "UNLINK":
                s = SOLIDS + i(1) * 96
                nx, pv = e.u32(s), e.u32(s + 4)
                e.put32(pv, nx)
                e.put32(nx + 4, pv)
            elif c == "ANIM":
                a = ANIMS + i(1) * 80
                e.write(a, bytes(80))
                e.put32(a + 32, h(2))
                e.put32(a + 40, 0 if i(3) < 0 else SOLIDS + i(3) * 96)
                e.put32(a + 36, h(4))
                e.put32(a + 44, 0 if i(5) < 0 else SOLIDS + i(5) * 96)
            elif c == "INIT":
                self.call("InitAnimatedDriver")
                s = "INIT: fix=%d" % s32(e.u32(G_FIX))
                for r in range(14):
                    s += " %08x/%d" % (e.u32(TABLE + r * 36 + 8),
                                       s32(e.u32(TABLE + r * 36 + 16)))
                for k in sorted(self.rot):
                    rp, n = self.rot[k]
                    s += " crc%d=%08x" % (k, zlib.crc32(e.read(rp, n)))
                lines.append(s)
            elif c == "KEYS":
                s = SOLIDS + i(1) * 96
                nf = e.u16(s + 68)
                k = e.u32(s + 76) + (nf * i(2) + i(3)) * 8
                lines.append("KEYS %s %s %s: %s" % (
                    t[1], t[2], t[3],
                    " ".join("%04x" % e.u16(k + 2 * j) for j in range(4))))
            elif c in ("PB", "PP", "PR", "PC"):
                p = drv() + 112 + 16 * i(2)
                if c == "PB":
                    self.call("BeginAnimation", p, i(3), i(4))
                elif c == "PP":
                    self.call("ReleasePausedFrame", p)
                elif c == "PR":
                    self.call("PlayerRelease", p)
                else:
                    self.call("CancelAnimation", p)
                lines.append("%s %d %d:%s" % (c, i(1), i(2),
                                              self.driver(i(1))))
            elif c == "PF":
                p = drv() + 112 + 16 * i(2)
                lines.append("PF %d %d: %d" % (
                    i(1), i(2), self.call("GetFrameNumber", p)))
            elif c == "Q":
                v = self.call("QueueAnimation", drv(), i(2))
                lines.append("Q %d %d: %d%s" % (i(1), i(2), v,
                                                self.driver(i(1))))
            elif c == "LEN":
                lines.append("LEN %d: %d" % (
                    i(1), self.call("GetLengthOfQueued", drv())))
            elif c == "FIND":
                v = self.call("FindAnimation", drv(), i(2)) & 0xffffffff
                lines.append("FIND %d %d: %d" % (
                    i(1), i(2), -1 if v == 0 else (v - drv() - 112) // 16))
            elif c in ("REL", "CA", "RA", "GC", "DBB", "DBE", "DBH", "LBB",
                       "LBE", "LBH", "PRE"):
                fn = {"REL": "ReleaseAnimation", "CA": "CancelAll",
                      "RA": "ReleaseAll", "GC": "BeginGearChange",
                      "DBB": "BeginDrivingBackwards",
                      "DBE": "EndDrivingBackwards",
                      "DBH": "HandleDrivingBackwards",
                      "LBB": "BeginLookingBackwards",
                      "LBE": "EndLookingBackwards",
                      "LBH": "HandleLookingBackwards",
                      "PRE": "BeginAPreRaceAnimation"}[c]
                if c == "REL":
                    self.call(fn, drv(), i(2))
                    lines.append("REL %d %d:%s" % (i(1), i(2),
                                                   self.driver(i(1))))
                else:
                    self.call(fn, drv())
                    lines.append("%s %d:%s" % (c, i(1), self.driver(i(1))))
            elif c == "COL":
                self.call("BeginCollision", drv(), i(2), i(3))
                lines.append("COL %d %d %d:%s" % (i(1), i(2), i(3),
                                                  self.driver(i(1))))
            elif c == "SFN":
                v = self.call("CalculateSteeringFrameNumber", drv())
                lines.append("SFN %d: %d%s" % (i(1), v, self.driver(i(1))))
            elif c == "RQ":
                self.call("QueueRandomAnimations", drv(), i(2), i(3), i(4))
                lines.append("RQ %d %d %d %d:%s" % (
                    i(1), i(2), i(3), i(4), self.driver(i(1))))
            elif c == "BB":
                v = self.call("Blackballed", i(1), i(2),
                              0 if i(3) < 0 else CHARS + i(3) * 0x80)
                lines.append("BB %d %d %d: %d" % (i(1), i(2), i(3), v))
            elif c == "QT":
                a = ANIMS + i(2) * 80
                e.write(QOUT, b"\x5a" * (16 * NUM_BONES))
                e.write(TOUT, b"\x5a" * 16)
                self.call("BuildQuaternionTable", drv(), a, QOUT, TOUT)
                s = "QT %d %d: t=%s" % (i(1), i(2), ",".join(
                    "%08x" % e.u32(TOUT + 4 * k) for k in range(3)))

                def sol(p):
                    k, r = divmod(p - SOLIDS, 96)
                    return -1 if p == 0 else (k if r == 0 else -2)
                s += " anim=%08x,%d,%08x,%d" % (
                    e.u32(a + 32), sol(e.u32(a + 40)), e.u32(a + 36),
                    sol(e.u32(a + 44)))
                for k in range(NUM_BONES):
                    s += " " + ",".join("%08x" % e.u32(QOUT + 16 * k + 4 * j)
                                        for j in range(4))
                lines.append(s + self.driver(i(1)))
            elif c == "NODE":
                n = NODES + i(1) * 0x1000 + i(2) * 96
                ws = [int(x, 16) for x in t[6:25]]
                e.write(n, struct.pack("<19I", *ws)
                        + struct.pack("<4b", i(2), i(3), i(4), i(5))
                        + bytes(16))
            elif c == "MS":
                a = ANIMS + i(1) * 80
                if i(2) < 0:
                    e.put32(a + 8 + 12, 0)
                else:
                    s = ESOLIDS + i(1) * 192
                    e.put32(s + 160, i(2))
                    e.put32(s + 164, NODES + i(1) * 0x1000)
                    e.put32(a + 8 + 12, s)
            elif c == "DA":
                e.put32(drv() + 4 + 4 * i(2),
                        0 if i(3) < 0 else ANIMS + i(3) * 80)
            elif c == "DM":
                e.put32(drv() + 16 + 4 * i(2),
                        0 if i(3) < 0 else MODELS + i(3) * 24)
            elif c == "FL":
                e.put32(G_FORCE, i(1))
                e.put32(G_OVERRIDE, i(2))
            elif c == "BS":
                e.put32(G_NBONE, i(1))
                for k in range(3):
                    e.put32(VBONE + 4 * k, h(2 + k))
            elif c == "FB":
                e.put32(G_POS, FRAME + i(1))
                e.put32(G_END, FRAME + i(2))
                e.put32(G_FAILED, 0)
                e.put32(G_AMOUNT, 0)
            elif c == "VIS":
                self.vis = i(1)
            elif c == "X":
                e.write(MTX, struct.pack("<16I", *[int(x, 16) for x in t[1:17]]))
            elif c == "REN":
                self.out = []
                e.call(F["Render"], drv(), MTX, h(3), h(4), i(2))
                lines.append("REN %d %d:%s pos=%d fail=%d amt=%d%s" % (
                    i(1), i(2), "".join(self.out), e.u32(G_POS) - FRAME,
                    s32(e.u32(G_FAILED)), e.u32(G_AMOUNT), self.driver(i(1))))
            else:
                raise ValueError("unknown op %s" % c)
        return lines


# ================================================================ the script

def unit_quat(rng):
    while True:
        v = [rng.uniform(-1, 1) for _ in range(4)]
        n = math.sqrt(sum(x * x for x in v))
        if 0.1 < n <= 1.0:
            return [x / n for x in v]


def rot_blob(rng, nodes, frames):
    """Each node's frames in turn, four int16s a key, as the bundles keep
    them; the keys wander a little from frame to frame."""
    out = bytearray()
    for _n in range(nodes):
        q = unit_quat(rng)
        for _f in range(frames):
            if rng.random() < 0.3:
                q = unit_quat(rng)
            else:
                q = [x + rng.uniform(-0.05, 0.05) for x in q]
                m = math.sqrt(sum(x * x for x in q))
                q = [x / m for x in q]
            out += struct.pack("<4h", *[int(x * 32767) for x in q])
    return bytes(out)


def trans_blob(rng, frames):
    out = bytearray()
    for _f in range(frames):
        out += struct.pack("<4f", rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2),
                           rng.uniform(-0.1, 0.3), rng.choice((0.0, 1.0)))
    return bytes(out)


def rot_matrix(rng, scale=1.0, w=1.0):
    """A row-vector rotation by a random quaternion, with a translation."""
    x, y, z, w = unit_quat(rng)
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
         [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
         [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]]
    rows = [row + [0.0] for row in r]
    rows.append([rng.uniform(-scale, scale) for _ in range(3)] + [w])
    return [fbits(v) for row in rows for v in row]


SOLID_NAMES = ["DRIVER_ANIM01", "DRIVER_SHIFT01", "DRIVER_PRERACEG02",
               "DRIVER_PRERACEG14"]
SOLID_FRAMES = [262, 31, 90, 75]


def tree_ops(rng, a, n):
    parent = [-1] + [rng.randrange(i) for i in range(1, n)]
    kids = [[] for _ in range(n)]
    for i in range(1, n):
        kids[parent[i]].append(i)
    first = [k[0] if k else 0 for k in kids]
    nxt = [0] * n
    for k in kids:
        for j in range(len(k) - 1):
            nxt[k[j]] = k[j + 1]
    ops = []
    for i in range(n):
        o2b = rot_matrix(rng, 0.5)
        tr = [fbits(rng.uniform(-0.3, 0.3)) for _ in range(3)]
        ops.append("NODE %d %d %d %d %d %s" % (
            a, i, parent[i], first[i], nxt[i], words(o2b + tr)))
    return ops


def script(tmp):
    rng = random.Random(0x83b)
    ops = ["TABLE"]
    # The solids' keys, written where both sides read them.
    for s, (name, frames) in enumerate(zip(SOLID_NAMES, SOLID_FRAMES)):
        rp = Path(tmp) / ("rot%d.bin" % s)
        tp = Path(tmp) / ("trans%d.bin" % s)
        rp.write_bytes(rot_blob(rng, NUM_BONES, frames))
        tp.write_bytes(trans_blob(rng, frames))
        ops.append("SOL %d %08x %d %d %s %s" % (
            s, bhash(name), NUM_BONES, frames, rp.as_posix(), tp.as_posix()))
    # No solid linked: every row's frames 0 and no fix-up.
    ops += ["FIX 1", "INIT", "TABLE"]
    # The table's frame counts back, the solids linked, the fix-up.
    for t, nf in ((1, 30), (2, 30), (3, 30), (4, 20), (5, 20), (6, 20),
                  (7, 20), (8, 20), (9, 20), (10, 20), (11, 30)):
        ops.append("TP %d 4 %d" % (t, nf))
    ops += ["LINK 0", "LINK 1", "LINK 2", "LINK 3", "FIX 1", "INIT", "TABLE"]
    for s in range(4):
        for _ in range(6):
            ops.append("KEYS %d %d %d" % (s, rng.randrange(NUM_BONES),
                                          rng.randrange(SOLID_FRAMES[s])))
    ops += ["KEYS 0 0 30", "KEYS 0 41 30", "KEYS 0 5 231", "KEYS 0 5 260"]
    # Once fixed up, again changes nothing.
    ops += ["FIX 0", "INIT"]

    # The car types: open or not; the blackballed ones among them.
    for ty in range(NUM_TYPES):
        ops.append("CT %d %d" % (ty, rng.random() < 0.4))
    ops += ["CT 23 0", "CT 13 0", "CT 7 1", "CT 32 0", "CT 4 1"]
    ops += ["CAR 0 5 5 1", "CAR 1 23 13 1", "CAR 2 32 4 1", "CAR 3 7 21 0"]
    ops += ["STEER 0 0", "STEER 1 0", "STEER 2 0", "STEER 3 0"]
    ops += ["CHAR 0 Racer01", "CHAR 1 Cop02", "CHAR 2 Co", "CHAR 3 COp",
            "CHAR 4 Robber01"]
    ops += ["DRV 0 0 0 0", "DRV 1 1 1 17", "DRV 2 2 2 61", "DRV 3 3 3 5"]

    # BB: every type with the tables' car types and others, both modes.
    for vm in (0, 1, 2):
        ops.append("VM %d" % vm)
        for ty in range(14):
            for ct in (2, 3, 4, 7, 8, 9, 10, 12, 13, 14, 15, 16, 21, 23, 24,
                       32, 33, 47, 48, 0, 5):
                for ch in (-1, 0, 1, 2, 3, 4):
                    ops.append("BB %d %d %d" % (ty, ct, ch))
    ops.append("VM 0")

    # The players alone.
    for ty in range(14):
        for delay in (0, 1, 7, -3):
            ops += ["W %d" % (1000 + delay * 3), "PB 0 0 %d %d" % (ty, delay)]
            for dt in (0, 1, 2, 9, 30, 59, 60, 61, 199, 100001):
                ops += ["W %d" % (1000 + dt), "PF 0 0"]
            ops += ["W 1010", "PP 0 0", "PF 0 0", "W 1015", "PR 0 0",
                    "PF 0 0", "PC 0 0"]
    # A looping pause and a pause past the end.
    ops += ["TP 3 5 -1", "W 500", "PB 0 1 3 0"]
    for dt in (-200, -63, -62, -61, 0, 1, 59, 60, 61, 120, 300, 901):
        ops += ["W %d" % (500 + dt), "PF 0 1"]
    ops += ["TP 3 5 75", "TP 4 5 5", "W 600", "PB 0 1 4 0", "W 700", "PF 0 1",
            "PP 0 1", "PF 0 1", "TP 4 5 121", "PC 0 1"]
    # Release: before the start, during, after, paused.
    for start, now in ((100, 90), (100, 100), (100, 130), (100, 300)):
        for ty in (2, 3, 4, 11):
            ops += ["W %d" % start, "PB 1 0 %d 0" % ty, "W %d" % now,
                    "PR 1 0", "PF 1 0", "PC 1 0"]

    # The steering's frame: every steering form, the wiggle, no CarDriver.
    for st in (0, 1, 0x4000, 0x7fff, 0x8000, 0x8001, 0xc000, 0xffff, 0x2000,
               0xe000, 1000, 64000):
        for wt in (0, 1, 17, 61, 62, 63, 1000, -5):
            ops += ["STEER 0 %d" % st, "W %d" % wt, "SFN 0"]
    ops += ["W 33", "SFN 3", "SFN 1", "SFN 2"]
    # Looking back reads the steering through the CarDriver unchecked.
    ops += ["CAR 3 7 21 1"]

    # The queue, the looks, the drives and the collisions, as a random walk.
    wt = 2000
    names = ["Q", "LEN", "FIND", "REL", "CA", "RA", "GC", "DBB", "DBE",
             "DBH", "LBB", "LBE", "LBH", "COL", "SFN", "RQ", "PRE"]
    looks = [(-1, 0, 0), (1, 0, 0), (1, 0x8000, 1), (1, 0x4000, 0),
             (1, 0xc000, 1), (1, 0x1234, 0), (2, 0xc000, 0), (-1, 0, 1)]
    for step in range(1500):
        if rng.random() < 0.35:
            wt += rng.choice((1, 2, 2, 3, 5, 10, 30, 60, 100, 400))
            ops.append("W %d" % wt)
        if rng.random() < 0.05:
            ops.append("LOOK %d %d %d" % rng.choice(looks))
        if rng.random() < 0.05:
            ops.append("STEER %d %d" % (rng.randrange(4),
                                        rng.randrange(0x10000)))
        if rng.random() < 0.03:
            ops.append("VM %d" % rng.choice((0, 1, 1, 2)))
        d = rng.randrange(4)
        n = rng.choice(names)
        if n == "Q":
            ops.append("Q %d %d" % (d, rng.randrange(14)))
        elif n in ("FIND", "REL"):
            ops.append("%s %d %d" % (n, d, rng.randrange(14)))
        elif n == "COL":
            ops.append("COL %d %d %d" % (d, rng.randrange(6, 11),
                                         rng.randrange(5)))
        elif n == "RQ":
            first = rng.randrange(1, 14)
            ops.append("RQ %d %d %d %d" % (d, first, rng.randrange(first, 14),
                                           rng.randrange(1, 4)))
        else:
            ops.append("%s %d" % (n, d))
    # Looking back: the steering's edges, then each angle to another car.
    ops += ["LOOK -1 0 0", "LBE 0", "DBE 0", "CA 0", "LBB 0"]
    for st in (0, 40000, 1820, 1821, 1822, 5000, 32767, 40000, 32768, 32769,
               40000, 63714, 5000, 63715, 63716, 65535, 1821, 0):
        wt += 1
        ops += ["STEER 0 %d" % st, "W %d" % wt, "LBH 0"]
    for angle in (0, 1, 0x3fff, 0x4000, 0x4001, 0x8000, 0xbfff, 0xc000,
                  0xc001, 0x1234, 0xc000, 0):
        wt += 1
        ops += ["LOOK 1 %d 0" % angle, "W %d" % wt, "LBH 0"]
    ops += ["LOOK -1 0 0", "LBE 0"]
    ops += ["SEED 00000000", "RQ 0 12 13 2", "SEED ffffffff", "RQ 1 12 13 2",
            "RQ 2 5 5 3", "RQ 3 1 13 9"]
    ops += ["TP 12 4 0", "RQ 0 12 13 2", "TP 12 4 90"]

    # BuildQuaternionTable: the steering alone, each animation, blended in
    # and out, and the solids found in either slot.
    ops += ["ANIM 0 2bb7f510 0 0 -1", "ANIM 1 0 -1 0 -1"]
    ops += ["WE 3c888889", "WL 1"]
    wt += 1000
    for d in range(4):
        for ty in range(14):
            ops += ["W %d" % wt, "CA %d" % d, "PB %d 0 %d 0" % (d, ty)]
            for dt in (0, 1, 2, 4, 8, 9, 10, 20, 39, 40, 58, 59, 60, 61):
                ops += ["W %d" % (wt + dt), "QT %d %d" % (d, dt % 2)]
            wt += 300
    for step in range(600):
        wt += rng.choice((1, 2, 2, 2, 3, 7))
        ops.append("W %d" % wt)
        if rng.random() < 0.1:
            ops.append("WL %d" % rng.choice((0, 1, 119, 120, 240, 241, 7)))
        if rng.random() < 0.05:
            ops.append("WE %08x" % fbits(rng.choice((1 / 60, 1 / 30, 0.0,
                                                     0.25, 1.0))))
        if rng.random() < 0.08:
            ops.append("STEER %d %d" % (rng.randrange(4),
                                        rng.randrange(0x10000)))
        d = rng.randrange(4)
        r = rng.random()
        if r < 0.1:
            ops.append("GC %d" % d)
        elif r < 0.15:
            ops.append("LBB %d" % d)
        elif r < 0.2:
            ops.append("LBE %d" % d)
        elif r < 0.25:
            ops.append("DBB %d" % d)
        elif r < 0.3:
            ops.append("DBE %d" % d)
        elif r < 0.35:
            ops.append("COL %d %d %d" % (d, rng.randrange(6, 11),
                                         rng.randrange(5)))
        elif r < 0.38:
            ops.append("PRE %d" % d)
        elif r < 0.4:
            ops.append("LOOK %d %d %d" % rng.choice(looks))
        ops.append("QT %d %d" % (d, rng.randrange(2)))
    # Both players at once: the first active one is drawn.
    wt += 5
    ops += ["LBE 0", "DBE 0", "CA 0", "W %d" % wt, "PB 0 0 7 0",
            "PB 0 1 3 0", "W %d" % (wt + 4), "QT 0 1", "PB 0 0 11 0",
            "W %d" % (wt + 6), "QT 0 1", "CA 0"]
    # A combined row looping back to the frame before its start: w is 0.
    wt += 10
    ops += ["TP 4 3 5", "TP 4 5 -1", "W %d" % wt, "PB 0 0 4 0"]
    for dt in (36, 37, 38, 39, 40, 41, 50):
        ops += ["W %d" % (wt + dt), "QT 0 1"]
    ops += ["CA 0", "TP 4 3 111", "TP 4 5 121"]
    # A blended row so short that its fifth frame is also near its end.
    wt += 60
    ops += ["TP 7 4 6", "W %d" % wt, "PB 0 0 7 0"]
    for dt in range(13):
        ops += ["W %d" % (wt + dt), "QT 0 1"]
    ops += ["CA 0", "TP 7 4 20"]
    # No steering solid: the translation is zeroed and the rest goes on.
    # (Not a combined row, nor a look back that queues one: retail reads
    # that solid unchecked.)
    wt += 5
    ops += ["UNLINK 0", "ANIM 1 0 -1 0 -1", "W %d" % wt, "LBE 0", "DBE 0",
            "CA 0", "QT 0 1",
            "PB 0 0 11 0", "W %d" % (wt + 6), "QT 0 1", "CA 0",
            "PB 0 0 3 0", "W %d" % (wt + 12), "QT 0 1", "CA 0",
            "PB 0 0 7 0", "W %d" % (wt + 24), "QT 0 1", "LINK 0"]

    # Render: the trees, the LODs, the plain models, the visibility, the
    # frame malloc, the big head.
    ops += tree_ops(rng, 0, NUM_BONES)
    ops += tree_ops(rng, 1, NUM_BONES)
    ops += ["ANIM 0 2bb7f510 0 0 -1", "MS 0 42", "ANIM 1 0 -1 0 -1",
            "MS 1 42", "VIS 1", "FL -1 0", "BS -1 3f800000 3f800000 3f800000"]
    ops += ["DA 0 0 0", "DA 0 1 1", "DA 0 2 -1", "DM 0 2 1", "DM 0 1 0"]
    for k in range(3):
        ops.append("X " + words(rot_matrix(rng, 400.0, (1.0, 0.0, 0.5)[k])))
        for lod in (0, 1, 2):
            ops += ["FB 0 %d" % FRAME_BYTES, "W %d" % (wt + k * 10 + lod),
                    "REN 0 %d c0ffee %x" % (lod, rng.randrange(1 << 16))]
    for force, override in ((-1, 1), (0, 0), (1, 0), (2, 0), (2, 1), (0, 1),
                            (-1, 0)):
        ops += ["FL %d %d" % (force, override), "FB 0 %d" % FRAME_BYTES]
        for lod in (0, 1, 2):
            ops.append("REN 0 %d 40 1" % lod)
    ops += ["FL -1 0", "VIS 0", "FB 0 %d" % FRAME_BYTES, "REN 0 0 40 1",
            "VIS 1"]
    ops += ["DM 0 0 2", "DA 0 0 -1", "DA 0 1 -1", "FB 0 %d" % FRAME_BYTES,
            "REN 0 0 40 1", "REN 0 1 40 1", "DA 0 0 0", "DA 0 1 1",
            "DM 0 0 -1"]
    # The frame malloc: no room for the matrix, for the bones, at the edges.
    for end in (0, 63, 64, 65, 64 + 42 * 64, 64 + 42 * 64 + 1,
                64 + 42 * 64 + 2, 4000):
        ops += ["FB 16 %d" % (16 + end), "REN 0 0 40 1"]
    # The big head: each bone in turn, and none.
    for nb in (0, 1, 7, 20, 41, 42, -1):
        ops += ["BS %d %08x %08x %08x" % (nb, fbits(1.8), fbits(2.2),
                                          fbits(0.75)),
                "FB 0 %d" % FRAME_BYTES, "REN 0 0 40 1"]
    ops.append("BS -1 3f800000 3f800000 3f800000")
    # No tree, a tree of one, the animations through their states.
    ops += ["MS 0 -1", "FB 0 %d" % FRAME_BYTES, "REN 0 0 40 1", "MS 0 1",
            "REN 0 0 40 1", "MS 0 42"]
    for step in range(60):
        wt += rng.choice((1, 2, 3))
        ops += ["W %d" % wt, "FB 0 %d" % FRAME_BYTES]
        if rng.random() < 0.2:
            ops.append(rng.choice(("GC 0", "LBB 0", "LBE 0", "DBB 0", "DBE 0",
                                   "COL 0 7 2", "PRE 0")))
        ops.append("REN 0 %d 40 1" % rng.randrange(2))
    return ops


def encode(ops):
    return NL.join(ops) + NL


def model(ops):
    m = Model()
    return m, m.run(ops)


def image_facts(m):
    """What the port takes from the image without running it: its tables
    and the globals it moved from the demo."""
    e = m.e
    out = []
    src = (ROOT / AD).read_text(encoding="utf-8")

    def floats_in(name, n):
        i = src.index(name)
        body = src[src.index("{", i) + 1:src.index("};", i)]
        vals = [v.strip() for v in body.replace(NL, " ").split(",")]
        return [float(v.rstrip("f")) for v in vals if v][:n]

    wig = floats_in("SteeringWiggleTable[62]", 62)
    img = [struct.unpack("<f", e.read(WIGGLE + 4 * k, 4))[0]
           for k in range(62)]
    out.append((all(fbits(a) == fbits(b) for a, b in zip(wig, img))
                and len(wig) == 62,
                "SteeringWiggleTable is 0x00311100's 62 floats"))

    def pairs_in(name, n):
        i = src.index(name)
        body = src[src.index("{", i) + 1:src.index("};", i)]
        nums = [int(x) for x in body.replace("{", " ").replace("}", " ")
                .replace(",", " ").split()]
        return [tuple(nums[2 * k:2 * k + 2]) for k in range(n)]

    for name, addr, n, typeonly in (("BlackballedForCar[21]", BB_CAR, 21, 0),
                                    ("BlackballedUnderRoof[2]", BB_ROOF, 2, 1),
                                    ("BlackballedForCop[8]", BB_COP, 8, 0)):
        port = pairs_in(name, n)
        img = [(s32(e.u32(addr + 8 * k)), s32(e.u32(addr + 8 * k + 4)))
               for k in range(n)]
        if typeonly:
            ok = [p[0] for p in port] == [q[0] for q in img]
        else:
            ok = port == img
        out.append((ok, "%s is %08x's" % (name.split("[")[0], addr)))
    # The shift's bones: the immediates BuildQuaternionTable loads.
    i = src.index("ShiftBones[3]")
    bones = [int(x) for x in src[src.index("{", i) + 1:src.index("}", i)]
             .split(",")]
    img = [s32(e.u8(GP - 19216 + k) << 24) >> 24 for k in range(3)]
    out.append((bones == img, "ShiftBones is gp-19216's %s" % img))
    out.append((bhash("DRIVER_ANIM01") == 0x2bb7f510,
                "DRIVER_ANIM01 hashes to 0x2bb7f510"))
    return out


# ============================================================== the harness

def build_harness(tmp, name="animdriver_test"):
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


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    # ---- AnimationPlayer
    ("begin_end_frames", AD,
     "p->EndTime = p->StartTime + info->NumFrames * 2;",
     "p->EndTime = p->StartTime + info->NumFrames * 3;"),
    ("begin_pause_long", AD,
     "p->EndTime = p->StartTime + 100000;",
     "p->EndTime = p->StartTime + 10000;"),
    ("begin_delay", AD,
     "p->StartTime = WorldTime + delay;",
     "p->StartTime = WorldTime;"),
    ("release_paused_end", AD,
     "(info->BeginFrame + info->NumFrames - f) * 2;",
     "(info->BeginFrame + info->NumFrames - f) * 2 + 1;"),
    ("release_paused_keep", AD,
     "    p->PauseFrameNumber = 0;\n    p->StartTime = p->EndTime",
     "    p->StartTime = p->EndTime"),
    ("release_before_start", AD,
     "        active = !(now < p->StartTime);",
     "        active = 1;"),
    ("release_paused_only", AD,
     "if (p->EndTime - now > 0 && p->PauseFrameNumber != 0)",
     "if (p->EndTime - now > 0)"),
    ("frame_div", AD,
     "info->BeginFrame + (WorldTime - p->StartTime) / 2;",
     "info->BeginFrame + ((WorldTime - p->StartTime) >> 1);"),
    ("frame_loop", AD,
     "        if (f < info->NumFrames)\n            return f;",
     "        if (f <= info->NumFrames)\n            return f;"),
    ("frame_pause_cap", AD,
     "        f = p->PauseFrameNumber;",
     "        f = p->PauseFrameNumber - 1;"),
    ("active_end", AD,
     "return now < p->EndTime && !(now < p->StartTime);",
     "return now <= p->EndTime && !(now < p->StartTime);"),
    ("active_start", AD,
     "return now < p->EndTime && !(now < p->StartTime);",
     "return now < p->EndTime;"),
    # ---- InitAnimatedDriver
    ("init_upper", AD, "                c &= 0x5f;", "                c &= 0x7f;"),
    ("init_not_found", AD,
     "            info->NumFrames = 0;\n            continue;",
     "            continue;"),
    ("init_begin_frame", AD,
     "        if (info->BeginFrame == 0)\n            info->NumFrames",
     "        if (info->BeginFrame == 1)\n            info->NumFrames"),
    ("init_fix_flag", AD,
     "if (AnimatedDriverNeedsFixup && info->CombineWithSteering)",
     "if (info->CombineWithSteering)"),
    ("init_fix_ref", AD,
     "eanimsolid_get_rotation(solid, &q30, n, 30.0f);",
     "eanimsolid_get_rotation(solid, &q30, n, 31.0f);"),
    ("init_fix_order", AD, "bMult(&r, &inv, &qf);", "bMult(&r, &qf, &inv);"),
    ("init_fix_norm", AD,
     "                    bNormalize(&r, &r);\n", ""),
    ("init_fix_range", AD,
     "f < info->BeginFrame + info->NumFrames; f++)",
     "f < info->BeginFrame + info->NumFrames - 1; f++)"),
    ("init_fix_clear", AD,
     "    AnimatedDriverNeedsFixup = 0;\n}", "}"),
    # ---- SetupSteeringFrame
    ("spline_val", AD, "    s->val = 30.0f;", "    s->val = 29.0f;"),
    ("spline_desired", AD, "    s->valDesired = 30.0f;",
     "    s->valDesired = 31.0f;"),
    ("spline_duration", AD, "    s->duration = 0.1f;",
     "    s->duration = 0.2f;"),
    ("spline_threshold", AD, "    s->arrivalThreshold = 1.0f;",
     "    s->arrivalThreshold = 0.5f;"),
    ("spline_flags", AD, "    s->flags = 1;", "    s->flags = 0;"),
    # ---- Render
    ("render_force", AD,
     "ForceAnimatedDriverLOD < 0 ? lod",
     "ForceAnimatedDriverLOD <= 0 ? lod"),
    ("render_override", AD,
     "if (OverrideAnimatedDriverLOD != 0 && !(l < 2))",
     "if (OverrideAnimatedDriverLOD != 0 && !(l < 3))"),
    ("render_override_to", AD,
     "        l = 1;\n    if (d->pAnimations[l]",
     "        l = 0;\n    if (d->pAnimations[l]"),
    ("render_model_lod", AD,
     "gEModelRenderFn(d->pModels[l], m, light, flags);",
     "gEModelRenderFn(d->pModels[2], m, light, flags);"),
    ("render_anim_first", AD,
     "    if (d->pAnimations[l] != NULL) {",
     "    if (d->pAnimations[l] != NULL && d->pModels[l] == NULL) {"),
    # ---- the looks and the drives
    ("gear_type", AD,
     "animdriver_queue_animation(d, DRIVER_ANIM_GEAR_CHANGE);",
     "animdriver_queue_animation(d, DRIVER_ANIM_IDLE);"),
    ("dbb_flag", AD,
     "    if (!d->DrivingBackwardsFlag) {",
     "    {"),
    ("dbe_release", AD,
     "animdriver_release_animation(d, DRIVER_ANIM_DRIVING_BACKWARDS);",
     "animdriver_cancel_all(d);"),
    ("dbh_find", AD,
     "if (animdriver_find_animation(d, DRIVER_ANIM_DRIVING_BACKWARDS) == NULL)",
     "if (1)"),
    ("lbb_type", AD,
     "d->CurrentLookingBackwardsType = DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT;",
     "d->CurrentLookingBackwardsType = DRIVER_ANIM_LOOKING_BACKWARDS_LEFT;"),
    ("lbb_flag", AD,
     "    if (!d->LookingBackwardsFlag) {",
     "    {"),
    ("lbe_left", AD,
     "_RIGHT);\n        animdriver_release_animation(d, "
     "DRIVER_ANIM_LOOKING_BACKWARDS_LEFT);",
     "_RIGHT);"),
    ("lbh_angle0", AD,
     "            if (a == 0)\n                s = 0;",
     "            if (a == 1)\n                s = 0;"),
    ("lbh_quarter", AD,
     "else if (a == 0x8000 || a == 0x4000)",
     "else if (a == 0x8000)"),
    ("lbh_left", AD, "else if (a == 0xc000)", "else if (a == 0xc001)"),
    ("lbh_steer_lo", AD,
     "if ((uint32_t)(0xa0000 / 360) < st",
     "if ((uint32_t)(0xa0000 / 360) <= st"),
    ("lbh_steer_mid", AD,
     "&& st < (uint32_t)(0xb40000 / 360))",
     "&& st <= (uint32_t)(0xb40000 / 360))"),
    ("lbh_steer_hi", AD,
     "&& st < (uint32_t)(0x15e0000 / 360))",
     "&& st <= (uint32_t)(0x15e0000 / 360))"),
    ("lbh_steer_keep", AD,
     "            else\n                s = d->CurrentLookingBackwardsType;",
     "            else\n                s = 0;"),
    ("lbh_release_left", AD,
     "    if (s != DRIVER_ANIM_LOOKING_BACKWARDS_LEFT)\n"
     "        animdriver_release_animation(d, "
     "DRIVER_ANIM_LOOKING_BACKWARDS_LEFT);\n", ""),
    ("lbh_queue_find", AD,
     "if (s != 0 && animdriver_find_animation(d, s) == NULL)",
     "if (s != 0)"),
    ("lbh_store", AD,
     "    d->CurrentLookingBackwardsType = s;\n}", "}"),
    # ---- the collisions
    ("col_allow", AD,
     "if (allow == 0 || !(allow < strength))",
     "if (allow == 0 || !(allow <= strength))"),
    ("col_allow0", AD,
     "if (allow == 0 || !(allow < strength))",
     "if (!(allow < strength))"),
    ("col_light", AD,
     "? DRIVER_ANIM_COLLISION_LIGHT : type);",
     "? DRIVER_ANIM_NONE : type);"),
    ("col_ride", AD,
     "        d, animdriver_blackballed(type, d->pCar->pRideInfo->Type,",
     "        d, animdriver_blackballed(type, d->pCar->pCarTypeInfo->Type,"),
    ("col_cancel", AD,
     "    animdriver_cancel_all(d);\n    animdriver_queue_animation(\n",
     "    animdriver_queue_animation(\n"),
    # ---- the queue
    ("queue_ride", AD,
     "        && animdriver_blackballed(type, d->pCar->pRideInfo->Type,",
     "        && animdriver_blackballed(type, d->pCar->pCarTypeInfo->Type,"),
    ("queue_rem_le", AD,
     "        if (rem <= 0)\n            idx = i;",
     "        if (rem < 0)\n            idx = i;"),
    ("queue_first_free", AD,
     "        if (rem <= 0)\n            idx = i;",
     "        if (rem <= 0) {\n            if (idx < 0)\n"
     "                idx = i;\n        }"),
    ("queue_long", AD,
     "else if (!(rem < 10001))", "else if (!(rem < 100001))"),
    ("queue_best", AD,
     "        else if (best < rem)\n            best = rem;", ""),
    ("len_max", AD,
     "        if (best < rem)\n            best = rem;\n    }\n    return best;",
     "        if (best > rem)\n            best = rem;\n    }\n    return best;"),
    ("find_end", AD,
     "p->pAnimationInfo->Type == type && p->EndTime - WorldTime > 0)",
     "p->pAnimationInfo->Type == type && p->EndTime - WorldTime >= 0)"),
    ("release_anim_type", AD,
     "if (d->AnimationPlayers[i].pAnimationInfo->Type == type)",
     "if (d->AnimationPlayers[i].pAnimationInfo->Type != type)"),
    # ---- CalculateSteeringFrameNumber
    ("sfn_cardriver", AD,
     "if (d->pCar != NULL && d->pCar->pCarDriver != NULL)",
     "if (d->pCar != NULL)"),
    ("sfn_half", AD, "    if (s < 0.5f)", "    if (s <= 0.5f)"),
    ("sfn_scale", AD, "f = s * 150.0f + 30.0f;", "f = s * 140.0f + 30.0f;"),
    ("sfn_scale_hi", AD,
     "f = 30.0f - (1.0f - s) * 150.0f;", "f = 30.0f - (1.0f - s) * 140.0f;"),
    ("sfn_wiggle", AD,
     "- (uint32_t)d->SteeringWiggleNumber) % 62u]",
     "+ (uint32_t)d->SteeringWiggleNumber) % 62u]"),
    ("sfn_clamp_hi", AD,
     "    if (45.0f < f)\n        f = 45.0f;",
     "    if (44.0f < f)\n        f = 44.0f;"),
    ("sfn_clamp_lo", AD,
     "    if (f < 15.0f)\n        f = 15.0f;",
     "    if (f < 16.0f)\n        f = 16.0f;"),
    ("sfn_state", AD,
     "    if (!(f == spline->val))\n        spline->state = 2;",
     "    spline->state = 2;"),
    ("sfn_answer", AD,
     "return ee_trunc_w(spline->val);",
     "return ee_trunc_w(spline->valDesired);"),
    ("wiggle_value", AD, "1.35f, 1.37f, 1.3f,", "1.35f, 1.38f, 1.3f,"),
    # ---- QueueRandomAnimations
    ("rq_prev", AD,
     "if (t != prev && AnimationInfoTable[t].NumFrames != 0",
     "if (AnimationInfoTable[t].NumFrames != 0"),
    ("rq_frames", AD,
     "if (t != prev && AnimationInfoTable[t].NumFrames != 0",
     "if (t != prev"),
    ("rq_tries", AD,
     "if (!(queued < count) || !(tries < 1001))",
     "if (!(queued < count) || !(tries < 1000))"),
    ("rq_type", AD,
     "&& animdriver_blackballed(t, d->pCar->pCarTypeInfo->Type,",
     "&& animdriver_blackballed(t, d->pCar->pRideInfo->Type,"),
    ("rq_range", AD,
     "int32_t range = last - first + 1;", "int32_t range = last - first;"),
    ("pre_count", AD,
     "DRIVER_ANIM_PRERACEG14, 2);", "DRIVER_ANIM_PRERACEG14, 1);"),
    # ---- BuildQuaternionTable
    ("qt_lb", AD,
     "    if (d->LookingBackwardsFlag)\n"
     "        animdriver_handle_looking_backwards(d);\n", ""),
    ("qt_db", AD,
     "    if (d->DrivingBackwardsFlag)\n"
     "        animdriver_handle_driving_backwards(d);\n", ""),
    ("qt_last_active", AD,
     "            p = &d->AnimationPlayers[i];\n            break;",
     "            p = &d->AnimationPlayers[i];"),
    ("qt_duration", AD,
     "d->pSteeringFrame->duration = 0.1f;",
     "d->pSteeringFrame->duration = 0.2f;"),
    ("qt_seek", AD,
     "bspline_seek(d->pSteeringFrame, WorldTimeElapsed);",
     "bspline_seek(d->pSteeringFrame, WorldTimeElapsed * 0.5f);"),
    ("qt_idle", AD,
     "if (WorldLoopCounter % 120 == 0)", "if (WorldLoopCounter % 121 == 0)"),
    ("qt_blend_in", AD,
     "w = 0.2f * (float)(in + 1);", "w = 0.2f * (float)in;"),
    ("qt_blend_in_len", AD, "        if (in < 5) {", "        if (in < 4) {"),
    ("qt_blend_out", AD,
     "            if (out < 5)\n                w = (float)out * 0.2f;",
     "            if (out < 4)\n                w = (float)out * 0.2f;"),
    ("qt_blend_flag", AD,
     "    if (info->BlendWithSteering) {", "    if (0) {"),
    ("qt_shift_bones", AD,
     "ShiftBones[3] = { 30, 31, 32 };", "ShiftBones[3] = { 30, 31, 33 };"),
    ("qt_shift_slerp", AD,
     "bSlerp(&q[b], &q[b], &r, w);", "bSlerp(&q[b], &r, &q[b], w);"),
    ("qt_w0", AD,
     "    if (w == 0.0f)\n        return;\n", ""),
    ("qt_combine_order", AD,
     "bMult(&q[i], &q[i], &r);", "bMult(&q[i], &r, &q[i]);"),
    ("qt_full", AD, "    } else if (w == 1.0f) {", "    } else if (0) {"),
    ("qt_slerp_w", AD,
     "bSlerp(&q[i], &q[i], &r, w);", "bSlerp(&q[i], &q[i], &r, 1.0f - w);"),
    ("qt_steer_frame", AD,
     "eanimsolid_get_rotations(solid, q, (float)fr);",
     "eanimsolid_get_rotations(solid, q, (float)(fr + 1));"),
    ("qt_no_solid", AD, "        t->z = 0.0f;\n", ""),
    # ---- blackballed
    ("bb_car_type", AD,
     "            && BlackballedForCar[i].CarType == car_type)\n", ")\n"),
    ("bb_view", AD,
     "if (eGetCurrentViewMode() != 1 && cti->OpenTop == 0)",
     "if (cti->OpenTop == 0)"),
    ("bb_open", AD,
     "if (eGetCurrentViewMode() != 1 && cti->OpenTop == 0)",
     "if (eGetCurrentViewMode() != 1)"),
    ("bb_co", AD,
     "if (ci->BodyTypeName[0] != 'C' || ci->BodyTypeName[1] != 'o')",
     "if (ci->BodyTypeName[0] != 'C')"),
    ("bb_c", AD,
     "if (ci->BodyTypeName[0] != 'C' || ci->BodyTypeName[1] != 'o')",
     "if (ci->BodyTypeName[1] != 'o')"),
    ("bb_cop_type", AD,
     "            && BlackballedForCop[i].CarType == car_type)\n", ")\n"),
    ("bb_roof_row", AD, "{ 11, 0 }, { 2, 0 },", "{ 11, 0 }, { 3, 0 },"),
    ("bb_car_row", AD, "{ 11, 13 }, { 11, 14 },", "{ 11, 13 }, { 11, 12 },"),
    ("bb_cop_row", AD, "{ 10, 4 }, { 8, 33 },", "{ 10, 5 }, { 8, 33 },"),
    # ---- the table
    ("table_pause4", AD,
     "{  4, \"DRIVER_ANIM01\",     0, 111, 20, 121, 1, 1, 1 },",
     "{  4, \"DRIVER_ANIM01\",     0, 111, 20, 120, 1, 1, 1 },"),
    ("table_allow7", AD,
     "{  7, \"DRIVER_ANIM01\",     0, 131, 20,   0, 3, 1, 0 },",
     "{  7, \"DRIVER_ANIM01\",     0, 131, 20,   0, 2, 1, 0 },"),
    ("table_begin9", AD,
     "{  9, \"DRIVER_ANIM01\",     0, 171, 20,   0, 3, 1, 0 },",
     "{  9, \"DRIVER_ANIM01\",     0, 170, 20,   0, 3, 1, 0 },"),
    # ---- eAnimation
    ("key_lane", EA,
     "    q->w = (float)k[3] * KEY_SCALE;",
     "    q->w = (float)k[2] * KEY_SCALE;"),
    ("rot_index", EA,
     "int32_t i = s->NumFrames * node + ee_trunc_w(frame);",
     "int32_t i = s->NumNodes * node + ee_trunc_w(frame);"),
    ("set_rot_trunc", EA,
     "k[0] = (int16_t)ee_trunc_w(q->x * KEY_UNSCALE);",
     "k[0] = (int16_t)ee_trunc_w(q->x * KEY_UNSCALE + 0.5f);"),
    ("set_rot_lane", EA,
     "k[3] = (int16_t)ee_trunc_w(q->w * KEY_UNSCALE);",
     "k[3] = (int16_t)ee_trunc_w(q->z * KEY_UNSCALE);"),
    ("rots_base", EA,
     "        base += s->NumFrames;", "        base += s->NumNodes;"),
    ("trans_lane", EA,
     "    v->z = s->pTranslationKeys[f].z;",
     "    v->z = s->pTranslationKeys[f].y;"),
    ("solid_first_slot", EA,
     "    if (a->NameHash1 == 0) {", "    if (0) {"),
    ("solid_find_last", EA,
     "            return (eAnimationSolid *)(void *)n;",
     "            return (eAnimationSolid *)(void *)n->next;"),
    ("tree_null", EA,
     "    if (m->Solid == NULL)\n        return NULL;\n", ""),
    ("posed_frame_size", EA,
     "frame = (bMatrix4 *)eframe_malloc(64);",
     "frame = (bMatrix4 *)eframe_malloc(80);"),
    ("posed_turn", EA, "    turn.v3.z = 0.0f;\n", ""),
    ("posed_add", EA,
     "frame->v3.x = matrix->v3.x + v.x;", "frame->v3.x = matrix->v3.x - v.x;"),
    ("posed_w", EA, "    frame->v3.w = 1.0f;\n", ""),
    ("posed_vis_args", EA,
     "gEModelDetermineVisibleStripsFn(&a->Model, frame, 1, 1) == 0)",
     "gEModelDetermineVisibleStripsFn(&a->Model, frame, 1, 0) == 0)"),
    ("posed_vis_hidden", EA,
     "gEModelDetermineVisibleStripsFn(&a->Model, frame, 1, 1) == 0)",
     "gEModelDetermineVisibleStripsFn(&a->Model, frame, 1, 1) < 0)"),
    ("posed_bones_size", EA,
     "((uint32_t)tree->NumNodes << 6)", "((uint32_t)tree->NumNodes << 5)"),
    ("posed_o2b_order", EA,
     "eMulMatrix(&a->pCurrentMatrices[i], &tree->pNodes[i].ObjectToBoneSpace,\n"
     "                   &a->pCurrentMatrices[i]);",
     "eMulMatrix(&a->pCurrentMatrices[i], &a->pCurrentMatrices[i],\n"
     "                   &tree->pNodes[i].ObjectToBoneSpace);"),
    ("posed_root_node", EA,
     "eanim_pose_matrix_recursive(a, &ident, q, tree, 0);",
     "eanim_pose_matrix_recursive(a, &ident, q, tree, 1);"),
    ("pose_translation", EA,
     "    m->v3.y = n->Translation[1];", "    m->v3.y = n->Translation[0];"),
    ("pose_parent_order", EA,
     "    eMulMatrix(m, m, parent);", "    eMulMatrix(m, parent, m);"),
    ("pose_quat_node", EA,
     "    bQuaternionToMatrix(m, &q[node]);",
     "    bQuaternionToMatrix(m, &q[0]);"),
    ("pose_scale_y", EA,
     "        m->v1.y *= vBoneScale[1];", "        m->v1.y *= vBoneScale[0];"),
    ("pose_scale_z", EA,
     "        m->v2.z *= vBoneScale[2];", "        m->v2.z *= vBoneScale[1];"),
    ("pose_scale_node", EA,
     "    if (node == nBoneScale) {", "    if (node == nBoneScale + 1) {"),
    ("pose_children", EA,
     "         child = tree->pNodes[child].NextChildNodeIndex)",
     "         child = 0)"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    "qt_full":
        "At w = 1 bSlerp gives kb = sin(theta)/sin(theta) = 1 and ka = "
        "sin(0)/sin(theta) = +-0 (or 1 - t = 0 when nearly parallel), so "
        "each bone is r exactly, and r is the key GetRotations reads: the "
        "driver solids have the 42 nodes the slerp loop walks.",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    scdir = tempfile.TemporaryDirectory()
    sc = script(scdir.name)
    _m, base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scp = Path(scdir.name) / "script.txt"
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
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
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

    with tempfile.TemporaryDirectory() as tmp:
        sc = script(tmp)
        m, lines = model(sc)
        facts = image_facts(m)
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    n = diff(lines, harness)
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("%d steps, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
