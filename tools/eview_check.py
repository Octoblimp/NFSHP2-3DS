#!/usr/bin/env python3
"""Cross-check 3DS Files/source/eview.c and eviewmatrix.c against the image.

eView.obj (0x00106650 .. 0x001075a8) and the words beside it in
EcstasyE.obj: the view's constructor, the static constructor's share of the
cameras and the views (0x00114098, run in place up to the texture
downloader at 0x001142ac), eInitViews, the view names, the lookups and the
current view, the movers' lists, eUpdateViewMode and MaybeChangeViewMode;
then the matrices: CalculateH (0x00103ce0), CreateViewMatricies,
eView::CalculateViewMatricies, eRenderTarget::SetupMatrixPacks, the
local-to-clip products, the z-sort bias, the three GetPixelSize,
GetScreenPosition, the screen's width and height, and
SetupWorldLightContext.

The image is the oracle: tools/mipsemu.py runs the shipped functions out of
NFSHP2.ELF, the harness (tools/src/eview_test.c) runs the port, both walk
the same script, and the two transcripts are diffed. No address is printed;
the harness's head has the naming scheme. Floats are compared as bits, with
every NaN printed as the one quiet NaN.

Retail changed four of them, so they run out of SLES_507.31 instead,
through tools/retail_model.py: CreateViewMatricies (0x0010e638), with its
Z table (0x002c9e20) and a third depth range; CalculateViewMatricies
(0x001070c0), with a ninth matrix; SetupMatrixPacks (0x00105860), with a
third pack and WorldView transposed; and SetupWorldLightContext
(0x00107900). Each runs on a copy of what it reads, and what it writes is
copied back (class Retail).

eWaitUntilRenderingDone (0x00110770) and elSetupLightContext (0x001154b8)
are stubbed in the model and seamed in the harness, and each prints its
call. The frame memory is 2 KB the script places the frame's position and
end in, filled with a pattern first so what a call leaves alone shows.

The script covers:

  * the static constructor's cameras, fields of view and views, eInitViews,
    every name and some past the ends, the lookups and the current view;
  * movers on and off each view in every order, the eight ways players 1,
    2 and the mirror can have movers or not, a list whose head reads NULL,
    and a mover taken off through the wrong view;
  * MaybeChangeViewMode across the current, rendering and tweaker modes,
    modes past 4 and below 0, odd and negative screens, shared targets and
    players without a second one;
  * CalculateH over the fields of view and the screen widths, odd and
    negative;
  * the Z table as the port starts with it, against the disc's;
  * CreateViewMatricies over random cameras, targets, screens and Z tables,
    each view id, the first mover's type, each Z buffer mode, the
    overrides, and d, d2 and e left out;
  * CalculateViewMatricies and SetupMatrixPacks with the frame memory
    running out at each allocation, one target and two, and one twice;
  * the local-to-clip products, aliased too, the bias, the three pixel
    sizes on both sides of their branches, the screen position with odd and
    negative scissors, and the light context with and without a camera and
    frame memory;
  * a frame as the game makes one: player 1 driving, the views calculated,
    lit, and asked what is on screen.

    python tools/eview_check.py
    python tools/eview_check.py --mutate
    python tools/eview_check.py --dump out/eview
"""
import argparse
import difflib
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
import mipsemu as me
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/eview_test.c",
    "3DS Files/source/eview.c",
    "3DS Files/source/eviewmatrix.c",
    "3DS Files/source/acidfx.c",
    "3DS Files/source/camera.c",
    "3DS Files/source/eframe.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmem.c",
]

EVC = "3DS Files/source/eview.c"
EVM = "3DS Files/source/eviewmatrix.c"

(OP_TAG, OP_INIT, OP_INITVIEWS, OP_DUMPVIEWS, OP_DUMPRTS, OP_NAME,
 OP_GETS, OP_CURVIEW, OP_ATTACH, OP_UNATTACH, OP_MTYPE, OP_NULLLIST,
 OP_RESETLIST, OP_UPDATEMODE, OP_SETMODES, OP_MAYBE, OP_SETRT, OP_SETVIEW,
 OP_SETCAM, OP_GLOBALS, OP_CALCH, OP_CREATE, OP_FRAME, OP_CALC, OP_MAT,
 OP_SETRTM, OP_PACKS, OP_SETVM, OP_L2C, OP_BIAS, OP_PIX, OP_PIXS, OP_PIXB,
 OP_SCREENPOS, OP_SWH, OP_LIGHT, OP_SUN, OP_SETH) = range(1, 39)

NVIEW = 10
NRT = 22
NMOVER = 8
NMAT = 8
NTCAM = 4
FRAMESZ = 2048

GP = 0x00328bf0
VIEWS = 0x002ab230
RTS = 0x002c9a20
CAMS = 0x002a9a50
IDENT = 0x002dc580
DMP = 0x002aa150
HACK = 0x002d6170
SUN = 0x002dfdf0
MAINDRAW = 0x00322860
CURMODE = 0x00322898
RENDMODE = 0x0032289c
TWEAKMODE = 0x003228a0
SWIDTH = 0x003227c8
SHEIGHT = 0x003227cc
SCREEN = 0x00322920        # CVSX CVSY CenterX CenterY
FOVMIP = 0x00325300
FOVZ = 0x00325302
FPOS = GP - 20044
FEND = GP - 20040
FFAILED = GP - 20028
FAMOUNT = GP - 20024

# Retail's four and what they touch, from their listings.
RGP = retail_model.RETAIL_GP
R_CREATE = 0x0010e638
R_CALC = 0x001070c0
R_PACKS = 0x00105860
R_LIGHT = 0x00107900
R_ELIGHT = 0x00115978
R_IDENT = 0x002dc380
R_DMP = 0x002c84d0
R_HACK = 0x002d70f0
R_SUN = 0x002e03c0
R_ZTAB = 0x002c9e20         # two of ZMin ZMax ZMin1 ZMax1 ZMin2 ZMax2
R_SWIDTH = RGP - 25108
R_SCREEN = RGP - 24736      # CVSX CVSY CenterX CenterY
R_FOVMIP = RGP - 13422
R_FOVZ = RGP - 13424
R_FPOS = RGP - 19388
R_FEND = RGP - 19384
R_FFAILED = RGP - 19372
R_FAMOUNT = RGP - 19368
R_WLC = 112                 # eView's WorldLightContext, the demo's 108
R_VU2 = 100                 # eView's VUClipScreenMatrix2
R_VIEW = 160
R_RT = 176                  # eRenderTarget, the demo's 1168
# The demo's eView has no VUClipScreenMatrix2; the model keeps it past the
# fields the demo's uses, where the port has it. The demo's eRenderTarget
# has no room for the third pack or VUClipScreen2: Model.rt2 holds them.
V_VU2 = 120

# The static constructor from its first word to the texture downloader's
# constructor, which is where eView's share ends.
SINIT = 0x00114098
SINIT_STOP = 0x001142ac
SINIT_FRAME = 160

FN = {
    "calch": 0x00103ce0,
    "getrt": 0x00104d00,
    "l2sc": 0x00106a20,
    "l2c": 0x00106a38,
    "bias": 0x00106a50,
    "attach": 0x00106b18,
    "unattach": 0x00106b38,
    "pix": 0x00106b50,
    "pixs": 0x00106b98,
    "pixb": 0x00106c90,
    "spos": 0x00106d98,
    "swidth": 0x00106e68,
    "sheight": 0x00106e80,
    "light": 0x00106e98,
    "name": 0x00107010,
    "initviews": 0x001070f8,
    "getview": 0x001071f0,
    "curview": 0x00107208,
    "setcur": 0x00107210,
    "curcam": 0x00107218,
    "curmode": 0x00107238,
    "update": 0x00107240,
    "maybe": 0x00107310,
    "wait": 0x00110770,
    "elight": 0x001154b8,
}

bits = me.f_to_bits
fbits = me.fbits_to
s32 = me.s32

CM_NONE, CM_DRIVE, CM_ORBIT, CM_BUMPER, CM_MIRROR, CM_STILL = 0, 1, 4, 5, 6, 12

# Retail's Z table: [0] for every Z buffer but PSMZ24, the demo's two
# ranges and a third; [1] for PSMZ24.
ZTAB = [0x40000010, 0x400ff000, 0x40000040, 0x400ffff0, 0x40000ff0, 0x400ffff0,
        0x40000010, 0x40800000, 0x40000040, 0x40802000, 0x40900000, 0x40f00000]
PSMZ24 = 0x31


def fx(b):
    b &= M32
    if (b & 0x7f800000) == 0x7f800000 and (b & 0x007fffff):
        return 0x7fc00000
    return b


def f32(x):
    return fbits(bits(x))


# ---------------------------------------------------------------- script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []

    def op(self, code, *args):
        self.words.append(code)
        self.op_words(args)

    def op_words(self, vals):
        for v in vals:
            self.words.append(bits(v) if isinstance(v, float) else v & M32)

    def tag(self, name):
        self.tags.append(name)
        self.op(OP_TAG, len(self.tags) - 1)

    def globals(self, sw=512, sh=448, cvsx=0.5, cvsy=0.5, cx=2048.0,
                cy=2048.0, ztab=ZTAB, mip=16384, fovz=9102, maindraw=16):
        self.op(OP_GLOBALS, sw, sh, cvsx, cvsy, cx, cy,
                *(list(ztab) + [mip, fovz, maindraw]))

    def rt(self, r, active=1, sx=0, sy=0, sw=512, sh=448, arx=1.0, ary=1.0,
           bias=1.0, zmode=0):
        self.op(OP_SETRT, r, active, sx, sy, sw, sh, arx, ary, bias, zmode)

    def view(self, v, vid, active, rt0, rt1, cam):
        self.op(OP_SETVIEW, v, vid, active, rt0, rt1, cam)

    def cam(self, c, m, pos, dirn, near, far, fov):
        self.op(OP_SETCAM, c)
        self.op_words(fl(m, 16) + fl(pos, 4) + fl(dirn, 4)
                      + [float(near), float(far), fov])

    def mat(self, k, m):
        self.op(OP_MAT, k)
        self.op_words(fl(m, 16))

    def frame(self, pos=0, end=FRAMESZ, seed=1):
        self.op(OP_FRAME, pos, end, seed)


def fl(vals, n):
    """Floats, or raw bits where an int is given."""
    vals = list(vals)
    assert len(vals) == n, (len(vals), n)
    return [v if isinstance(v, int) else float(v) for v in vals]


def look(pos, yaw, pitch):
    """World to camera, row vectors: the camera looks down its +z, with +y
    down the screen. `yaw` about the world's z, `pitch` above the
    horizon."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    fwd = (cy * cp, sy * cp, sp)
    right = (sy, -cy, 0.0)
    down = (fwd[1] * right[2] - fwd[2] * right[1],
            fwd[2] * right[0] - fwd[0] * right[2],
            fwd[0] * right[1] - fwd[1] * right[0])
    axes = (right, down, fwd)
    m = [0.0] * 16
    for c in range(3):
        for r in range(3):
            m[4 * r + c] = axes[c][r]
        m[12 + c] = -sum(pos[r] * axes[c][r] for r in range(3))
    m[15] = 1.0
    return [f32(x) for x in m], [f32(x) for x in fwd] + [0.0]


def rand_matrix(rnd, scale=2.0):
    return [f32(rnd.uniform(-scale, scale)) for _ in range(16)]


def rand_cam(sc, rnd, c, fov=None, near=None, far=None):
    pos = [f32(rnd.uniform(-2000, 2000)), f32(rnd.uniform(-2000, 2000)),
           f32(rnd.uniform(-50, 200)), 1.0]
    m, fwd = look(pos, rnd.uniform(-3.1, 3.1), rnd.uniform(-0.6, 0.6))
    if near is None:
        near = f32(rnd.choice((0.5, 0.25, 1.0, rnd.uniform(0.05, 8.0))))
    if far is None:
        far = f32(near + rnd.choice((5000.0, 1000.0, rnd.uniform(1.0, 9000.0))))
    if fov is None:
        fov = rnd.choice((9102, 16384, 12000, rnd.randrange(64, 32700),
                          rnd.randrange(32800, 65536)))
    sc.cam(c, m, pos, fwd, near, far, fov)
    return pos, fwd


# ---------------------------------------------------------------- scenarios


def s_init(sc):
    sc.tag("init")
    sc.op(OP_GETS)
    sc.op(OP_INIT)
    sc.op(OP_GETS)
    for i in [-0x80000000, -3, -2, -1] + list(range(12)) + [100, 0x7fffffff]:
        sc.op(OP_NAME, i)
    sc.op(OP_INITVIEWS)
    sc.op(OP_GETS)
    for v in (0, 3, 9, 1, -1, 2):
        sc.op(OP_CURVIEW, v)
        sc.op(OP_GETS)
    sc.op(OP_DUMPRTS, 0, NRT)


def s_movers(sc):
    sc.tag("movers")
    for k, t in enumerate((CM_DRIVE, CM_ORBIT, CM_BUMPER, CM_STILL, CM_NONE,
                           CM_MIRROR, CM_DRIVE, 17)):
        sc.op(OP_MTYPE, k, t)
    seq = [
        (OP_ATTACH, 1, 0), (OP_ATTACH, 3, 1), (OP_ATTACH, 2, 2),
        (OP_ATTACH, 1, 3), (OP_ATTACH, 0, 4), (OP_ATTACH, 4, 5),
        (OP_UNATTACH, 1, 0), (OP_UNATTACH, 2, 2), (OP_UNATTACH, 1, 3),
        (OP_UNATTACH, 3, 1), (OP_ATTACH, 2, 2), (OP_ATTACH, 3, 1),
        (OP_ATTACH, 1, 0), (OP_UNATTACH, 2, 2), (OP_ATTACH, 1, 6),
        (OP_ATTACH, 1, 7), (OP_UNATTACH, 1, 6),     # from the middle
        (OP_UNATTACH, 5, 7),                        # through the wrong view
        (OP_UNATTACH, 0, 4), (OP_UNATTACH, 4, 5), (OP_UNATTACH, 3, 1),
        (OP_UNATTACH, 1, 0),
    ]
    for code, v, m in seq:
        sc.op(code, v, m)
    # the eight ways players 1, 2 and the mirror can have movers
    for mask in range(8):
        for v in (1, 2, 3):
            sc.op(OP_RESETLIST, v)
        for i, v in enumerate((1, 2, 3)):
            if mask & (1 << i):
                sc.op(OP_ATTACH, v, i)
        sc.op(OP_SETMODES, 7, 5, 6)
        sc.op(OP_UPDATEMODE)
    # a head that reads NULL counts as empty
    sc.op(OP_RESETLIST, 1)
    sc.op(OP_RESETLIST, 2)
    sc.op(OP_RESETLIST, 3)
    sc.op(OP_ATTACH, 2, 2)
    sc.op(OP_ATTACH, 1, 0)
    sc.op(OP_NULLLIST, 1)
    sc.op(OP_UPDATEMODE)
    sc.op(OP_NULLLIST, 2)
    sc.op(OP_UPDATEMODE)
    for v in range(NVIEW):
        sc.op(OP_RESETLIST, v)
    sc.op(OP_UPDATEMODE)


def s_viewmodes(sc, rnd):
    sc.tag("view modes")
    sc.op(OP_INITVIEWS)

    def scramble():
        for r in range(NRT):
            if r in (16,):
                continue
            sc.rt(r, rnd.getrandbits(32), rnd.randrange(-900, 900),
                  rnd.randrange(-900, 900), rnd.randrange(-900, 900),
                  rnd.randrange(-900, 900), 1.5, 0.75, 1.0)

    sc.rt(16, 1, 0, 0, 640, 448)
    combos = []
    for cur in (0, 1, 2, 3, 4, 5, -1):
        for tweak in (0, 2, 3, 4, 6):
            for rend in sorted({0, cur, tweak, 9}):
                combos.append((cur, rend, tweak))
    for cur, rend, tweak in combos:
        scramble()
        sc.op(OP_SETMODES, cur, rend, tweak)
        sc.op(OP_MAYBE)
    # odd, negative and zero screens
    for w, h in ((511, 447), (-9, -7), (0, 0), (1, 1), (-1, 640)):
        sc.rt(16, 1, 3, 5, w, h)
        for mode in (1, 2, 3, 4):
            scramble()
            sc.op(OP_SETMODES, mode, 7, 0)
            sc.op(OP_MAYBE)
    sc.rt(16, 1, 0, 0, 512, 448)
    # players without a second target, and targets shared, which shows the
    # order of the stores
    shared = [
        ((1, 1, 1, 1, -1, 1), None, None),
        (None, (2, 2, 1, 2, -1, 2), None),
        ((1, 1, 1, 1, -1, 1), (2, 2, 1, 2, -1, 2), None),
        (None, None, (3, 3, 1, 1, -1, 3)),         # the mirror is player 1's
        (None, None, (3, 3, 1, 4, -1, 3)),         # the mirror is p1's second
        (None, (2, 2, 1, 1, 5, 2), None),          # player 2 on player 1's
        (None, (2, 2, 1, 2, 4, 2), None),          # p2's second is p1's
        ((1, 1, 1, 1, 16, 1), None, None),         # a second on the frame's
    ]
    for v1, v2, v3 in shared:
        sc.op(OP_INITVIEWS)
        for s in (v1, v2, v3):
            if s is not None:
                sc.view(*s)
        for mode in (0, 1, 2, 3, 4):
            scramble()
            sc.op(OP_SETMODES, mode, 8, 0)
            sc.op(OP_MAYBE)
    # the frame drawn into another target
    sc.op(OP_INITVIEWS)
    for md in (15, 18, 19, 20):
        sc.globals(maindraw=md)
        sc.rt(md, 1, 0, 0, 320 + md, 200 + md)
        for mode in (1, 3, 4):
            scramble()
            sc.op(OP_SETMODES, mode, 0, 0)
            sc.op(OP_MAYBE)
    sc.globals()
    sc.op(OP_SETMODES, 0, 0, 0)
    sc.op(OP_INITVIEWS)


def s_calch(sc, rnd):
    sc.tag("CalculateH")
    fovs = [0, 1, 2, 3, 4, 31, 32, 64, 100, 1000, 9102, 12000, 16384, 20000,
            30000, 32766, 32767, 32770, 32771, 40000, 49152, 60000, 65534,
            65535]
    fovs += [rnd.randrange(0, 65536) for _ in range(30)]
    fovs = [f for f in fovs if (f >> 1) != 16384]
    for sw in (512, 511, 640, 2, 1, 0, -1, -2, -513, 0x7fffffff,
               -0x80000000):
        sc.globals(sw=sw)
        for f in fovs:
            sc.op(OP_CALCH, f)
    sc.globals()


def rand_globals(sc, rnd):
    sc.globals(
        sw=rnd.choice((512, 640, 320, rnd.randrange(2, 2000))),
        sh=rnd.choice((448, 480, rnd.randrange(-100, 2000))),
        cvsx=f32(rnd.choice((0.5, rnd.uniform(0.2, 1.4)))),
        cvsy=f32(rnd.choice((0.5, rnd.uniform(0.2, 1.4)))),
        cx=f32(rnd.choice((2048.0, rnd.uniform(1500, 2600)))),
        cy=f32(rnd.choice((2048.0, rnd.uniform(1500, 2600)))),
        ztab=[rnd.choice((z, bits(rnd.uniform(1.0, 2.0) if j % 2 == 0
                                  else rnd.uniform(2.2, 8.0))))
              for j, z in enumerate(ZTAB)],
        mip=rnd.choice((16384, rnd.randrange(64, 32700))),
        fovz=rnd.choice((9102, rnd.randrange(64, 32700))),
        maindraw=16)


def rand_rt(sc, rnd, r):
    sc.rt(r, rnd.getrandbits(32), rnd.randrange(-50, 50),
          rnd.randrange(-50, 50),
          rnd.choice((512, 640, 511, rnd.randrange(1, 1500),
                      -rnd.randrange(1, 900))),
          rnd.choice((448, 224, 447, rnd.randrange(1, 1500),
                      -rnd.randrange(1, 900))),
          f32(rnd.choice((1.0, rnd.uniform(0.3, 2.0), -rnd.uniform(0.3, 2.0)))),
          f32(rnd.choice((1.0, rnd.uniform(0.3, 2.0)))),
          f32(rnd.uniform(-3, 3)),
          rnd.choice((0, PSMZ24, PSMZ24, 58, 50, rnd.getrandbits(32))))


def rand_view(sc, rnd, v, rt0, rt1, cam):
    vid = rnd.choice((v, 0, 1, 2, 3, 4, 9, -1, -0x80000000, 0x7fffffff))
    sc.view(v, vid, rnd.getrandbits(8), rt0, rt1, cam)
    return vid


def movers_for(sc, rnd, v):
    """Clear the view's movers and put zero to three random ones on."""
    sc.op(OP_RESETLIST, v)
    for i in range(rnd.choice((0, 0, 1, 1, 2, 3))):
        m = rnd.randrange(NMOVER)
        sc.op(OP_RESETLIST, (v + 1) % NVIEW)        # m may be on another list
        sc.op(OP_MTYPE, m, rnd.choice((CM_NONE, CM_DRIVE, CM_ORBIT, CM_BUMPER,
                                       CM_MIRROR, CM_STILL, 2, 3)))
        sc.op(OP_ATTACH, v, m)
        if (v + 1) % NVIEW != v:
            pass
    return


def overrides(rnd):
    def one():
        return rnd.choice((0.0, 0.0, 0.0, f32(rnd.uniform(0.1, 20.0)),
                           f32(rnd.uniform(100, 9000))))
    return one(), one(), one()


def s_create(sc, rnd, n=160):
    sc.tag("CreateViewMatricies")
    sc.op(OP_INITVIEWS)
    for v in range(NVIEW):
        sc.op(OP_RESETLIST, v)
    for i in range(n):
        if i % 4 == 0:
            rand_globals(sc, rnd)
        v = rnd.randrange(1, NVIEW)
        rt0 = rnd.randrange(NRT)
        rt1 = rnd.choice((-1, rnd.randrange(NRT), rt0))
        rand_rt(sc, rnd, rt0)
        if rt1 >= 0 and rt1 != rt0:
            rand_rt(sc, rnd, rt1)
        c = 4 + rnd.randrange(NTCAM)
        rand_cam(sc, rnd, c)
        rand_view(sc, rnd, v, rt0, rt1, c)
        # movers: the first decides whether players 1 and 2 are scaled
        for w in range(NVIEW):
            sc.op(OP_RESETLIST, w)
        k = rnd.choice((0, 0, 1, 1, 2))
        for j in range(k):
            m = j + 2 * (i % 3)
            sc.op(OP_MTYPE, m, rnd.choice((CM_NONE, CM_DRIVE, CM_ORBIT,
                                           CM_BUMPER, CM_MIRROR, CM_STILL)))
            sc.op(OP_ATTACH, v, m)
        nearz, farz, efarz = overrides(rnd)
        sc.op(OP_CREATE, v, rnd.randrange(8), nearz, farz, efarz)
    for w in range(NVIEW):
        sc.op(OP_RESETLIST, w)
    # every view id and mover type through one camera, so the scaling shows
    sc.globals()
    sc.rt(1, 1, 0, 0, 512, 448, 1.0, 0.875, 1.0)
    sc.rt(4, 1, 0, 0, 512, 224, 1.0, 0.875, 1.0)
    rand_cam(sc, rnd, 5, fov=12000, near=0.5, far=5000.0)
    for vid in (0, 1, 2, 3, -1, 4):
        for t in (None, CM_NONE, CM_DRIVE, CM_ORBIT, CM_BUMPER, CM_MIRROR):
            sc.op(OP_RESETLIST, 1)
            sc.view(1, vid, 1, 1, 4, 5)
            if t is not None:
                sc.op(OP_MTYPE, 0, t)
                sc.op(OP_MTYPE, 1, CM_DRIVE if t != CM_DRIVE else CM_ORBIT)
                sc.op(OP_ATTACH, 1, 1)
                sc.op(OP_ATTACH, 1, 0)
            for ov in ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 800.0, 0.0),
                       (0.0, 0.0, 300.0), (3.0, 700.0, 250.0)):
                sc.op(OP_CREATE, 1, 7, *ov)
    sc.op(OP_RESETLIST, 1)
    # each Z buffer mode, and each of d, d2 and e left out
    sc.view(1, 1, 1, 1, 4, 5)
    for zmode in (0, PSMZ24, 58, 50, 0x131, -1):
        sc.rt(1, 1, 0, 0, 512, 448, 1.0, 0.875, 1.0, zmode)
        sc.rt(4, 1, 0, 0, 512, 224, 1.0, 0.875, 1.0, PSMZ24 ^ zmode)
        for mask in range(8):
            sc.op(OP_CREATE, 1, mask, 0.0, 0.0, 0.0)
    # a head that reads NULL
    sc.view(2, 2, 1, 2, -1, 6)
    rand_cam(sc, rnd, 6, fov=16384)
    sc.rt(2, 1, 0, 0, 512, 448, 1.0, 1.0, 1.0)
    sc.op(OP_NULLLIST, 2)
    sc.op(OP_CREATE, 2, 7, 0.0, 0.0, 0.0)
    sc.op(OP_RESETLIST, 2)
    sc.op(OP_INITVIEWS)


def s_calc(sc, rnd):
    sc.tag("CalculateViewMatricies")
    sc.op(OP_INITVIEWS)
    sc.globals()
    for r in range(NRT):
        sc.rt(r, 1, 0, 0, 512, 448, 1.0, 0.875, 1.0)
    rand_cam(sc, rnd, 4, fov=9102)
    rand_cam(sc, rnd, 5, fov=16384)
    sc.view(1, 1, 1, 1, 4, 4)
    sc.view(2, 2, 1, 2, -1, 5)
    sc.view(3, 3, 1, 7, 7, 4)                     # one target twice
    # where the frame memory runs out: the block, then each pack
    ends = [FRAMESZ, 576, 577, 768, 769, 960, 961, 1152, 1153, 1344, 1345,
            1536, 1537, 1728, 1729, 0, 192, 384, 385, 576 + 385, 100]
    for v in (1, 2, 3):
        for end in ends:
            for pos in (0, 16):
                sc.frame(pos, min(FRAMESZ, end + pos), 7 + v + end)
                sc.op(OP_CALC, v, 0.0, 0.0, 0.0)
    sc.frame(FRAMESZ, FRAMESZ, 3)
    sc.op(OP_CALC, 1, 0.0, 0.0, 0.0)
    for i in range(24):
        rand_globals(sc, rnd)
        v = rnd.randrange(NVIEW)
        rt0 = rnd.randrange(NRT)
        rt1 = rnd.choice((-1, rnd.randrange(NRT)))
        rand_rt(sc, rnd, rt0)
        if rt1 >= 0 and rt1 != rt0:
            rand_rt(sc, rnd, rt1)
        c = 4 + rnd.randrange(NTCAM)
        rand_cam(sc, rnd, c)
        rand_view(sc, rnd, v, rt0, rt1, c)
        sc.op(OP_RESETLIST, v)
        sc.frame(16 * rnd.randrange(8), FRAMESZ, i)
        sc.op(OP_CALC, v, *overrides(rnd))
    sc.op(OP_INITVIEWS)


def s_packs(sc, rnd):
    sc.tag("SetupMatrixPacks")
    for k in range(NMAT):
        sc.mat(k, rand_matrix(rnd))
    for r, ms in ((0, (0, 1, 2, 3, 4, 5)), (5, (5, 6, 7, 0, 1, 2)),
                  (9, (2, 2, 2, 3, 3, 4))):
        sc.op(OP_SETRTM, r, *ms)
        for end in (FRAMESZ, 577, 576, 385, 384, 193, 192, 0):
            sc.frame(0, end, r + end)
            sc.op(OP_PACKS, r)
        sc.frame(32, 32 + 577, r)
        sc.op(OP_PACKS, r)


def s_products(sc, rnd):
    sc.tag("local to clip, bias")
    for k in range(NMAT):
        sc.mat(k, rand_matrix(rnd))
    sc.op(OP_SETVM, 5, 3, 1)
    sc.op(OP_SETVM, 5, 1, 2)
    for which in (0, 1):
        sc.op(OP_L2C, 5, which, 3, 4)
        sc.op(OP_L2C, 5, which, 4, 4)             # o is local
        sc.mat(4, rand_matrix(rnd))
    sc.op(OP_L2C, 5, 0, 1, 6)                     # o is the view's own
    sc.mat(1, rand_matrix(rnd))
    sc.op(OP_L2C, 5, 1, 2, 7)
    sc.mat(2, rand_matrix(rnd))
    # the bias
    sc.view(6, 6, 1, 6, -1, 7)
    for i in range(14):
        pos, fwd = rand_cam(sc, rnd, 7)
        m = rand_matrix(rnd, 50.0)
        sc.mat(0, m)
        s = rnd.choice((0.0, 1.0, -1.0, 0.5, 2.0, f32(rnd.uniform(-3, 3))))
        sc.op(OP_BIAS, 6, 0, s)
    sc.view(6, 6, 1, 6, -1, -1)
    sc.mat(0, rand_matrix(rnd))
    sc.op(OP_BIAS, 6, 0, 0.5)                     # no camera: nothing


def s_pixels(sc, rnd):
    sc.tag("pixel sizes")
    sc.view(6, 6, 1, 6, -1, 4)
    for h in (0.0, 256.0, 309.0, -256.0, 1e30, 5e-4):
        sc.op(OP_SETH, 6, h)
        for r, d in ((1.0, 10.0), (2.0, 1.0), (2.0, 1.0000001),
                     (2.0, 0.9999999), (0.0, 0.0), (0.0, 5.0), (-4.0, 1.0),
                     (-4.0, -3.0), (4.0, -3.0), (3.0, 1.5), (1e20, 1e-20),
                     (0.5, 1e-30), (-1.0, -0.4),
                     # at H 256, r * H / d is 1 and r * (H / d) just under
                     # it, and the other way round (found by search)
                     (f32(0.006138392724096775), f32(1.5714285373687744)),
                     (f32(0.02734374813735485), 7.0)):
            sc.op(OP_PIX, 6, r, d)
        for _ in range(8):
            sc.op(OP_PIX, 6, f32(rnd.uniform(-5, 50)), f32(rnd.uniform(0.01, 900)))
    for i in range(10):
        pos, fwd = rand_cam(sc, rnd, 4)
        sc.op(OP_SETH, 6, rnd.choice((256.0, 309.0, f32(rnd.uniform(1, 2000)))))
        for j in range(10):
            t = rnd.choice((-30.0, -2.0, -0.5, 0.0, 0.5, 3.0, 80.0,
                            rnd.uniform(-100, 100)))
            side = [rnd.uniform(-5, 5) for _ in range(3)]
            p = [f32(pos[k] + fwd[k] * t + side[k]) for k in range(3)]
            r = f32(rnd.choice((0.0, 1.0, 5.0, rnd.uniform(0, 40),
                                -rnd.uniform(0, 3))))
            sc.op(OP_PIXS, 6, *(p + [f32(rnd.uniform(-9, 9)), r]))
            half = [f32(abs(rnd.uniform(0, 12))) for _ in range(3)]
            mn = [f32(p[k] - half[k]) for k in range(3)]
            mx = [f32(p[k] + half[k]) for k in range(3)]
            if rnd.random() < 0.2:
                mn, mx = mx, mn
            sc.op(OP_PIXB, 6, *(mn + [f32(rnd.uniform(-9, 9))]
                                + mx + [f32(rnd.uniform(-9, 9))]))
        # the eye itself, and a box the eye is in
        sc.op(OP_PIXS, 6, *(pos[:3] + [1.0, 2.0]))
        sc.op(OP_PIXS, 6, *(pos[:3] + [1.0, 0.0]))
        sc.op(OP_PIXB, 6, *([pos[0] - 1, pos[1] - 1, pos[2] - 1, 0.0]
                            + [pos[0] + 1, pos[1] + 1, pos[2] + 1, 0.0]))
        sc.op(OP_PIXB, 6, *(pos[:3] + [0.0] + pos[:3] + [0.0]))


def s_screen(sc, rnd):
    sc.tag("screen position")
    for k in range(NMAT):
        sc.mat(k, rand_matrix(rnd))
    sc.view(6, 6, 1, 6, -1, 4)
    for sw, sh in ((512, 448), (511, 447), (-9, -7), (0, 0), (-1, 1),
                   (0x7fffffff, -0x80000000)):
        sc.rt(6, 1, 3, 4, sw, sh)
        sc.op(OP_SWH, 6)
        for k in (0, 3):
            sc.op(OP_SETVM, 6, 2, k)
            for _ in range(4):
                p = [f32(rnd.uniform(-10, 10)) for _ in range(3)]
                sc.op(OP_SCREENPOS, 6, *(p + [rnd.choice((1.0, 0.0, -7.0))]))
    # through a camera's own matrices
    sc.globals()
    sc.rt(6, 1, 0, 0, 512, 448, 1.0, 0.875, 1.0)
    for i in range(6):
        pos, fwd = rand_cam(sc, rnd, 4)
        sc.frame(0, FRAMESZ, i)
        sc.op(OP_CALC, 6, 0.0, 0.0, 0.0)
        for j in range(6):
            t = rnd.uniform(2, 400)
            p = [f32(pos[k] + fwd[k] * t + rnd.uniform(-t / 2, t / 2))
                 for k in range(3)]
            sc.op(OP_SCREENPOS, 6, *(p + [1.0]))


def s_light(sc, rnd):
    sc.tag("light context")
    sc.view(6, 6, 1, 6, -1, 4)
    for sun in ((100.0, 200.0, 300.0, 0.0), (1.0, 0.0, 0.0, 5.0),
                (-3.0, 4.0, -500.0, 1.0), (0.0, -2.0, 1.0, 0.0)):
        sc.op(OP_SUN, *sun)
        for i in range(3):
            rand_cam(sc, rnd, 4)
            sc.frame(16 * i, FRAMESZ, i)
            sc.op(OP_LIGHT, 6)
    sc.frame(0, 288, 9)                           # just too little
    sc.op(OP_LIGHT, 6)
    sc.frame(0, 289, 9)
    sc.op(OP_LIGHT, 6)
    sc.view(6, 6, 1, 6, -1, -1)                   # no camera
    sc.frame(0, FRAMESZ, 10)
    sc.op(OP_LIGHT, 6)
    sc.view(6, 6, 1, 6, -1, 4)


def s_game(sc, rnd):
    sc.tag("a frame")
    sc.op(OP_INIT)
    sc.op(OP_INITVIEWS)
    sc.globals()
    # player 1's target is PSMZ24, as retail's packet builder makes it
    for r in range(NRT):
        sc.rt(r, 0, 0, 0, 512, 448, 1.0, 0.875, 1.0, PSMZ24 if r == 1 else 0)
    for v in range(NVIEW):
        sc.op(OP_RESETLIST, v)
    sc.op(OP_MTYPE, 0, CM_DRIVE)
    sc.op(OP_ATTACH, 1, 0)
    sc.op(OP_MAYBE)
    sc.op(OP_SUN, 3000.0, -2000.0, 4000.0, 0.0)
    for c in (0, 1):
        pos = [f32(-120.0 + 40 * c), f32(900.0), f32(3.5), 1.0]
        m, fwd = look(pos, 0.7, -0.05)
        sc.cam(c, m, pos, fwd, 0.5, 5000.0, 9102 + 1000 * c)
    for v in (0, 1):
        # retail's 1728 bytes a view, with two targets, and the light's 288
        sc.frame(0, FRAMESZ, 42 + v)
        sc.op(OP_CALC, v, 0.0, 0.0, 0.0)
        sc.op(OP_LIGHT, v)
        sc.op(OP_SWH, v)
        for d in (5.0, 20.0, 150.0, 900.0):
            p = [f32(-120.0 + math.cos(0.7) * d), f32(900.0 + math.sin(0.7) * d),
                 1.0, 1.0]
            sc.op(OP_SCREENPOS, v, *p)
            sc.op(OP_PIXS, v, *(p + [2.0]))
            sc.op(OP_PIXB, v, *([p[0] - 2, p[1] - 1, 0.0, 0.0]
                                + [p[0] + 2, p[1] + 1, 1.5, 0.0]))
            sc.op(OP_PIX, v, 2.0, d)
    sc.op(OP_DUMPVIEWS)
    sc.op(OP_DUMPRTS, 0, 8)
    for v in range(NVIEW):
        sc.op(OP_RESETLIST, v)


def script():
    rnd = random.Random(2224)
    sc = Script()
    s_init(sc)
    s_movers(sc)
    s_viewmodes(sc, rnd)
    s_calch(sc, rnd)
    s_create(sc, rnd)
    s_calc(sc, rnd)
    s_packs(sc, rnd)
    s_products(sc, rnd)
    s_pixels(sc, rnd)
    s_screen(sc, rnd)
    s_light(sc, rnd)
    s_game(sc, rnd)
    return sc


# ---------------------------------------------------------------- the model


class Retail(object):
    """Retail's CreateViewMatricies, CalculateViewMatricies, SetupMatrixPacks
    and SetupWorldLightContext on a copy of the model's state: what each
    reads goes in and what it writes comes back. A pointer crosses to its
    twin here: the frame memory, the scratch matrices, the script's, the
    view being run, each render target, the identity, DefaultMatrixPack
    and hack_man_matrix. Retail's eRenderTarget is the demo's less its
    packets, so the targets go across field by field, and the view's first
    mover is one here with its type. The light context's
    elSetupLightContext prints the line the demo's stub would."""

    def __init__(self, m):
        self.m = m
        r = self.r = retail_model.RetailEmu(ieee=True, eediv=True)
        r.stub_bware()
        r.call("eMathInit__Fv")
        if [r.u32(R_ZTAB + 4 * j) for j in range(12)] != ZTAB:
            sys.exit("retail's Z table is not ZTAB")
        self.view = r.alloc(R_VIEW, 16)
        self.cam = r.alloc(452, 16)
        self.mover = r.alloc(48, 16)
        self.frame = r.alloc(FRAMESZ + 64, 16)
        self.scratch = r.alloc(6 * 64, 16)
        self.mats = r.alloc(64 * NMAT, 16)
        self.rts = r.alloc(R_RT * NRT, 16)
        self.k = 0
        r.stub(R_ELIGHT, self.elight)

    # ---- the twins

    def fixed(self):
        return ((IDENT, R_IDENT), (DMP, R_DMP), (HACK, R_HACK))

    def ranges(self):
        m = self.m
        return ((m.frame, self.frame, FRAMESZ + 64),
                (m.scratch, self.scratch, 6 * 64),
                (m.mats, self.mats, 64 * NMAT),
                (m.view_at(self.k), self.view, 128))

    def to_r(self, p):
        p &= M32
        if p == 0:
            return 0
        for a, b in self.fixed():
            if p == a:
                return b
        for a, b, n in self.ranges():
            if a <= p < a + n:
                return p - a + b
        if RTS <= p < RTS + 1168 * NRT and (p - RTS) % 1168 == 0:
            return self.rts + (p - RTS) // 1168 * R_RT
        sys.exit("no retail twin for %08x" % p)

    def from_r(self, p, strict=True):
        p &= M32
        if p == 0:
            return 0
        for a, b in self.fixed():
            if p == b:
                return a
        for a, b, n in self.ranges():
            if b <= p < b + n:
                return p - b + a
        if (self.rts <= p < self.rts + R_RT * NRT
                and (p - self.rts) % R_RT == 0):
            return RTS + (p - self.rts) // R_RT * 1168
        if strict:
            sys.exit("no model twin for %08x" % p)
        return None

    def name(self, p):
        q = self.from_r(p, strict=False)
        return "?" if q is None else self.m.name(q)

    def elight(self, em):
        lc, lw, hack, eye, view = (em.reg[r] & M32 for r in (4, 5, 6, 7, 8))
        self.m.emit("  light %s local %s hack %s eye %s view %s"
                    % (self.name(lc), self.name(lw), self.name(hack),
                       " ".join("%08x" % fx(em.u32(eye + 4 * j))
                                for j in range(4)), self.name(view)))

    def copy(self, src, dst, a, b, n):
        for j in range(0, n, 4):
            dst.put32(b + j, src.u32(a + j))

    # ---- the state that goes across

    def sync_globals(self):
        m, r, e = self.m, self.r, self.m.e
        r.put32(R_SWIDTH, m.u32(SWIDTH))
        self.copy(e, r, SCREEN, R_SCREEN, 16)
        for j, x in enumerate(m.ztab):
            r.put32(R_ZTAB + 4 * j, x)
        struct.pack_into("<H", r.mem, R_FOVMIP, e.u16(FOVMIP))
        struct.pack_into("<H", r.mem, R_FOVZ, e.u16(FOVZ))

    def frame_in(self):
        m, r = self.m, self.r
        self.copy(m.e, r, m.frame, self.frame, FRAMESZ + 64)
        r.put32(R_FPOS, self.to_r(m.u32(FPOS)))
        r.put32(R_FEND, self.to_r(m.u32(FEND)))
        r.put32(R_FFAILED, m.u32(FFAILED))
        r.put32(R_FAMOUNT, m.u32(FAMOUNT))

    def frame_out(self):
        m, r = self.m, self.r
        self.copy(r, m.e, self.frame, m.frame, FRAMESZ + 64)
        m.w32(FPOS, self.from_r(r.u32(R_FPOS)))
        m.w32(FEND, self.from_r(r.u32(R_FEND)))
        m.w32(FFAILED, r.u32(R_FFAILED))
        m.w32(FAMOUNT, r.u32(R_FAMOUNT))

    # (the demo's offset, retail's) in eRenderTarget
    RT_WORDS = ((8, 8), (20, 20), (24, 24), (28, 28), (32, 32), (56, 56),
                (84, 88), (88, 92), (100, 104))
    RT_PTRS = ((1136, 140), (1140, 144), (1144, 152), (1148, 156),
               (1152, 160), (1156, 164), (1160, 168))

    def rt_in(self, p):
        m, r = self.m, self.r
        q, k = self.to_r(p), (p - RTS) // 1168
        for a, b in self.RT_WORDS:
            r.put32(q + b, m.u32(p + a))
        for a, b in self.RT_PTRS:
            r.put32(q + b, self.to_r(m.u32(p + a)))
        r.put32(q + 148, self.to_r(m.rt2[k][0]))
        r.put32(q + 172, self.to_r(m.rt2[k][1]))

    def rt_out(self, p):
        m, r = self.m, self.r
        q, k = self.to_r(p), (p - RTS) // 1168
        m.w32(p + 100, r.u32(q + 104))
        for a, b in self.RT_PTRS:
            m.w32(p + a, self.from_r(r.u32(q + b)))
        m.rt2[k] = [self.from_r(r.u32(q + 148)), self.from_r(r.u32(q + 172))]

    def view_in(self, k, v):
        m, r, u = self.m, self.r, self.m.u32
        self.k = k
        self.copy(m.e, r, v, self.view, 48)
        for off in (48, 52):
            p = u(v + off)
            r.put32(self.view + off, self.to_r(p))
            if p:
                self.rt_in(p)
        cam = u(v + 56)
        if cam:
            self.copy(m.e, r, cam, self.cam, 448)
        r.put32(self.view + 56, self.cam if cam else 0)
        first = u(v + 60)
        if first == v + 60:
            first = self.view + 60
        elif first:
            r.put32(self.mover + 8, u(first + 8))
            first = self.mover
        r.put32(self.view + 60, first)
        r.put32(self.view + 64, self.view + 60)

    def view_out(self, v, mats):
        m, r = self.m, self.r
        self.copy(r, m.e, self.view + 8, v + 8, 40)
        for off in (48, 52):
            p = m.u32(v + off)
            if p:
                self.rt_out(p)
        if mats:
            for j in range(8):
                m.w32(v + 68 + 4 * j,
                      self.from_r(r.u32(self.view + 68 + 4 * j)))
            m.w32(v + V_VU2, self.from_r(r.u32(self.view + R_VU2)))

    def floats(self, fs):
        for j, x in enumerate(fs):
            self.r.fpr[12 + j] = x & M32

    # ---- the four

    def create(self, k, v, ms, mask, fs):
        m, r = self.m, self.r
        self.view_in(k, v)
        self.copy(m.e, r, m.scratch, self.scratch, 6 * 64)
        a, b, c, d, e, d2 = (s32(self.to_r(p)) for p in ms)
        self.floats(fs)
        r.call(R_CREATE, s32(self.view), a, b, c, d if mask & 1 else 0,
               d2 if mask & 4 else 0, e if mask & 2 else 0)
        self.copy(r, m.e, self.scratch, m.scratch, 6 * 64)
        self.view_out(v, False)

    def calc(self, k, v, fs):
        self.view_in(k, v)
        self.frame_in()
        self.floats(fs)
        self.r.call(R_CALC, s32(self.view))
        self.frame_out()
        self.view_out(v, True)

    def packs(self, p):
        m, r = self.m, self.r
        self.copy(m.e, r, m.mats, self.mats, 64 * NMAT)
        self.frame_in()
        self.rt_in(p)
        r.call(R_PACKS, s32(self.to_r(p)))
        self.frame_out()
        self.rt_out(p)

    def light(self, k, v):
        m, r, e = self.m, self.r, self.m.e
        self.k = k
        cam = m.u32(v + 56)
        if cam:
            self.copy(e, r, cam, self.cam, 448)
        r.put32(self.view + 56, self.cam if cam else 0)
        r.put32(self.view + R_WLC, m.u32(v + 108))
        self.copy(e, r, SUN, R_SUN, 16)
        self.frame_in()
        r.call(R_LIGHT, s32(self.view))
        self.frame_out()
        m.w32(v + 108, self.from_r(r.u32(self.view + R_WLC)))


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True)
        # The port's Camera is retail's, whose constructor puts the far
        # plane at 10000 (gp-31300 there); the demo's loads 5000 from
        # gp-31464, read only at 0x00153a8c. Everything else about the
        # camera these views read is the same on both discs.
        e.put32((e.reg[28] - 31464) & M32, me.f_to_bits(10000.0))
        e.stub_bware()
        e.call("eMathInit__Fv")
        self.movers = e.alloc(48 * NMOVER, 16)
        self.mats = e.alloc(64 * NMAT, 16)
        self.tcams = e.alloc(448 * NTCAM, 16)
        self.frame = e.alloc(FRAMESZ + 64, 16)
        self.scratch = e.alloc(6 * 64, 16)
        self.rt2 = [[0, 0] for _ in range(NRT)]    # MatrixPack2 VUClipScreen2
        self.ztab = list(ZTAB)
        self.vec = e.alloc(64, 16)
        emit = self.emit

        def sinit_stop(em):
            em.reg[me.SP] = (em.reg[me.SP] + SINIT_FRAME) & M32
            em.reg[me.RA] = em.RETURN

        def wait(em):
            emit("  wait")

        def elight(em):
            lc, lw, hack, eye, view = (em.reg[r] & M32 for r in (4, 5, 6, 7, 8))
            emit("  light %s local %s hack %s eye %s view %s"
                 % (self.name(lc), self.name(lw), self.name(hack),
                    " ".join("%08x" % fx(em.u32(eye + 4 * j))
                             for j in range(4)), self.name(view)))

        e.stub(SINIT_STOP, sinit_stop)
        e.stub(FN["wait"], wait)
        e.stub(FN["elight"], elight)
        self.rl = Retail(self)

    def emit(self, line):
        self.out.append(line)

    def u32(self, a):
        return self.e.u32(a)

    def w32(self, a, v):
        self.e.put32(a, v)

    def call(self, name, *args, **kw):
        e = self.e
        for i, v in enumerate(kw.get("f", ())):
            e.fpr[12 + i] = v & M32
        return e.call(FN[name], *[s32(a) for a in args])

    def cam_at(self, i):
        if i < 0:
            return 0
        return CAMS + 448 * i if i < 4 else self.tcams + 448 * (i - 4)

    def rt_at(self, i):
        return 0 if i < 0 else RTS + 1168 * i

    def mat_at(self, i):
        return 0 if i < 0 else self.mats + 64 * i

    def view_at(self, i):
        return VIEWS + 128 * i

    # ---- naming

    def name(self, p):
        p &= M32
        if p == 0:
            return "null"
        if p == IDENT:
            return "I"
        if p == DMP:
            return "DMP"
        if p == HACK:
            return "HM"
        if p == SUN:
            return "SUN"
        for k in range(NVIEW):
            if p == VIEWS + 128 * k:
                return "V%d" % k
            if p == VIEWS + 128 * k + 60:
                return "V%d.L" % k
        for k in range(NRT):
            if p == RTS + 1168 * k:
                return "RT%d" % k
        for k in range(4 + NTCAM):
            if p == self.cam_at(k):
                return "C%d" % k
        for k in range(NMOVER):
            if p == self.movers + 48 * k:
                return "M%d" % k
        for k in range(NMAT):
            if p == self.mats + 64 * k:
                return "X%d" % k
        if self.frame <= p <= self.frame + FRAMESZ:
            return "F+%d" % (p - self.frame)
        return "?"

    # ---- dumps

    def words(self, a, n):
        return " ".join("%08x" % fx(self.u32(a + 4 * j)) for j in range(n))

    def dump_words(self, label, a, n):
        self.emit("   %s %s" % (label, self.words(a, n)) if n else
                  "   %s" % label)

    def dump_key(self, label, k):
        u, w = self.u32, self.words
        self.dump_words(label, k, 16)
        self.emit("    pos %s dir %s tgt %s"
                  % (w(k + 64, 4), w(k + 80, 4), w(k + 96, 4)))
        self.emit("    td %08x fd %08x dof %08x near %08x far %08x fov %d pad %s"
                  % (fx(u(k + 112)), fx(u(k + 116)), fx(u(k + 120)),
                     fx(u(k + 124)), fx(u(k + 128)), self.e.u16(k + 132),
                     " ".join("%02x" % self.e.u8(k + 134 + j)
                              for j in range(10))))

    def dump_camera(self, i):
        c = self.cam_at(i)
        u = self.u32
        self.emit("  C%d" % i)
        self.dump_key("cur", c)
        self.dump_key("prev", c + 144)
        self.dump_key("vel", c + 288)
        self.emit("    elapsed %08x last %08x car %s dash %d"
                  % (fx(u(c + 432)), u(c + 436), self.name(u(c + 440)),
                     s32(u(c + 444))))

    def dump_view(self, k):
        v = self.view_at(k)
        u, n = self.u32, self.name
        self.emit("  V%d id %d active %d lb %d h %08x near %08x far %08x"
                  " bias %08x deg %08x dir %s rt0 %s rt1 %s cam %s"
                  % (k, s32(u(v)), self.e.u8(v + 4), self.e.u8(v + 5),
                     fx(u(v + 8)), fx(u(v + 12)), fx(u(v + 16)),
                     fx(u(v + 20)), fx(u(v + 24)), self.words(v + 32, 4),
                     n(u(v + 48)), n(u(v + 52)), n(u(v + 56))))
        self.emit("   list %s %s mats %s %s wq %d blend %s wlc %s bw %d"
                  % (n(u(v + 60)), n(u(v + 64)),
                     " ".join(n(u(v + 68 + 4 * j)) for j in range(8)),
                     n(u(v + V_VU2)), u(v + 100), n(u(v + 104)),
                     n(u(v + 108)), s32(u(v + 112))))

    def dump_views(self):
        for k in range(NVIEW):
            self.dump_view(k)

    def dump_rt(self, k):
        r = self.rt_at(k)
        u, n = self.u32, self.name
        self.emit("  RT%d id %d active %d sc %d %d %d %d ar %08x %08x"
                  " bias %08x z %d packs %s %s %s wc %s wv %s cs %s vu %s"
                  " vu1 %s vu2 %s"
                  % (k, s32(u(r)), u(r + 8), s32(u(r + 20)), s32(u(r + 24)),
                     s32(u(r + 28)), s32(u(r + 32)), fx(u(r + 84)),
                     fx(u(r + 88)), fx(u(r + 100)), s32(u(r + 56)),
                     n(u(r + 1136)), n(u(r + 1140)), n(self.rt2[k][0]),
                     n(u(r + 1144)), n(u(r + 1148)), n(u(r + 1152)),
                     n(u(r + 1156)), n(u(r + 1160)), n(self.rt2[k][1])))

    def dump_modes(self):
        u = self.u32
        self.emit("  mode cur %d rend %d tweak %d"
                  % (s32(u(CURMODE)), s32(u(RENDMODE)), s32(u(TWEAKMODE))))

    def dump_lists(self):
        u, n = self.u32, self.name
        for k in range(NVIEW):
            head = self.view_at(k) + 60
            parts = ["  V%d list prev %s:" % (k, n(u(head + 4)))]
            p = u(head)
            i = 0
            while p != head and i < 12:
                if p == 0:
                    parts.append(" null")
                    break
                parts.append(" %s(n %s p %s)" % (n(p), n(u(p)), n(u(p + 4))))
                p = u(p)
                i += 1
            self.emit("".join(parts))
        self.dump_modes()

    def dump_frame(self):
        u = self.u32
        self.emit("  frame pos %s end %s failed %d amount %d"
                  % (self.name(u(FPOS)), self.name(u(FEND)),
                     s32(u(FFAILED)), u(FAMOUNT)))

    def dump_frame_memory(self):
        pos = self.u32(FPOS)
        if not (self.frame <= pos <= self.frame + FRAMESZ):
            return
        used = pos - self.frame
        for o in range(0, used, 64):
            self.dump_words("F+%d" % o, self.frame + o, min(16, (used - o) // 4))

    def fill(self, a, n, seed):
        for i in range(n):
            self.w32(a + 4 * i,
                     0x4a000000 | ((seed * 0x10001 + i * 0x9e37) & 0xffffff))

    # ---- the script

    def run(self):
        e = self.e
        w = self.sc.words
        u, n, emit = self.u32, self.name, self.emit
        i = 0
        opno = 0

        def rd(k=1):
            nonlocal i
            v = w[i:i + k]
            i += k
            return v if k > 1 else v[0]

        def rdi():
            return s32(rd())

        while i < len(w):
            code = rd()
            opno += 1
            if code == OP_TAG:
                emit("tag %d" % rdi())
            elif code == OP_INIT:
                emit("init")
                e.call(SINIT)
                for c in range(4):
                    self.dump_camera(c)
                self.dump_views()
                emit("  fov mip %d z %d maindraw %s"
                     % (e.u16(FOVMIP), e.u16(FOVZ), n(u(MAINDRAW))))
                self.rl.sync_globals()
            elif code == OP_INITVIEWS:
                emit("initviews")
                self.call("initviews")
                self.dump_views()
            elif code == OP_DUMPVIEWS:
                emit("views")
                self.dump_views()
            elif code == OP_DUMPRTS:
                lo, hi = rdi(), rdi()
                emit("rts %d %d" % (lo, hi))
                for k in range(lo, hi):
                    self.dump_rt(k)
            elif code == OP_NAME:
                vid = rdi()
                p = self.call("name", vid) & M32
                s = bytes(e.read(p, 64)).split(b"\0")[0].decode()
                emit("name %d %s" % (vid, s))
            elif code == OP_GETS:
                emit("gets")
                emit(" " + "".join(" %s" % n(self.call("getview", k))
                                   for k in range(NVIEW)))
                emit(" " + "".join(" %s" % n(self.call("getrt", k))
                                   for k in range(NRT)))
                emit("  mode %d view %s camera %s"
                     % (self.call("curmode"), n(self.call("curview")),
                        n(self.call("curcam"))))
                emit("  ztab " + " ".join(
                    "%08x" % fx(self.rl.r.u32(R_ZTAB + 4 * j))
                    for j in range(12)))
            elif code == OP_CURVIEW:
                v = rdi()
                emit("curview %d" % v)
                self.call("setcur", 0 if v < 0 else self.view_at(v))
            elif code in (OP_ATTACH, OP_UNATTACH):
                v, m = rdi(), rdi()
                emit("%s V%d M%d" % ("attach" if code == OP_ATTACH
                                     else "unattach", v, m))
                self.call("attach" if code == OP_ATTACH else "unattach",
                          self.view_at(v), self.movers + 48 * m)
                self.dump_lists()
            elif code == OP_MTYPE:
                m, t = rdi(), rd()
                self.w32(self.movers + 48 * m + 8, t)
            elif code == OP_NULLLIST:
                self.w32(self.view_at(rdi()) + 60, 0)
            elif code == OP_RESETLIST:
                h = self.view_at(rdi()) + 60
                self.w32(h, h)
                self.w32(h + 4, h)
            elif code == OP_UPDATEMODE:
                emit("updatemode")
                self.call("update")
                self.dump_modes()
            elif code == OP_SETMODES:
                self.w32(CURMODE, rd())
                self.w32(RENDMODE, rd())
                self.w32(TWEAKMODE, rd())
            elif code == OP_MAYBE:
                emit("maybe")
                self.call("maybe")
                self.dump_modes()
                for k in range(NRT):
                    r = self.rt_at(k)
                    emit("  RT%d act %d sc %d %d %d %d"
                         % (k, u(r + 8), s32(u(r + 20)), s32(u(r + 24)),
                            s32(u(r + 28)), s32(u(r + 32))))
                emit("  active" + "".join(" %d" % e.u8(self.view_at(k) + 4)
                                          for k in range(NVIEW)))
            elif code == OP_SETRT:
                r = self.rt_at(rdi())
                self.w32(r + 8, rd())
                for off in (20, 24, 28, 32, 84, 88, 100, 56):
                    self.w32(r + off, rd())
            elif code == OP_SETVIEW:
                v = self.view_at(rdi())
                self.w32(v, rd())
                e.mem[v + 4] = rd() & 0xff
                self.w32(v + 48, self.rt_at(rdi()))
                self.w32(v + 52, self.rt_at(rdi()))
                self.w32(v + 56, self.cam_at(rdi()))
            elif code == OP_SETCAM:
                c = self.cam_at(rdi())
                for j in range(16):
                    self.w32(c + 4 * j, rd())
                for j in range(4):
                    self.w32(c + 64 + 4 * j, rd())
                for j in range(4):
                    self.w32(c + 80 + 4 * j, rd())
                self.w32(c + 124, rd())
                self.w32(c + 128, rd())
                struct.pack_into("<H", e.mem, c + 132, rd() & 0xffff)
            elif code == OP_GLOBALS:
                self.w32(SWIDTH, rd())
                self.w32(SHEIGHT, rd())
                for j in range(4):
                    self.w32(SCREEN + 4 * j, rd())
                self.ztab = list(rd(12))
                struct.pack_into("<H", e.mem, FOVMIP, rd() & 0xffff)
                struct.pack_into("<H", e.mem, FOVZ, rd() & 0xffff)
                self.w32(MAINDRAW, self.rt_at(rdi()))
                self.rl.sync_globals()
            elif code == OP_CALCH:
                fov = rd() & 0xffff
                self.call("calch", fov)
                emit("calch %d %08x" % (fov, fx(e.fpr[0])))
            elif code == OP_CREATE:
                k, mask = rdi(), rdi()
                fs = rd(3)
                emit("create V%d mask %d %s" % (k, mask, " ".join(
                    "%08x" % fx(x) for x in fs)))
                ms = [self.scratch + 64 * j for j in range(6)]
                for j in range(6):
                    self.fill(ms[j], 16, opno * 8 + j)
                v = self.view_at(k)
                self.rl.create(k, v, ms, mask, fs)
                for j, lab in enumerate(("a", "b", "c", "d", "e", "d2")):
                    self.dump_words(lab, ms[j], 16)
                self.dump_view(k)
                if u(v + 48):
                    emit("  rt0 bias %08x" % fx(u(u(v + 48) + 100)))
                if u(v + 52):
                    emit("  rt1 bias %08x" % fx(u(u(v + 52) + 100)))
            elif code == OP_FRAME:
                pos, end, seed = rdi(), rdi(), rd()
                self.fill(self.frame, FRAMESZ // 4, seed)
                self.w32(FPOS, self.frame + pos)
                self.w32(FEND, self.frame + end)
                self.w32(FFAILED, 0)
                self.w32(FAMOUNT, 0)
            elif code == OP_CALC:
                k = rdi()
                fs = rd(3)
                emit("calc V%d %s" % (k, " ".join("%08x" % fx(x) for x in fs)))
                v = self.view_at(k)
                self.rl.calc(k, v, fs)
                self.dump_view(k)
                for off, lab in ((48, "rt0"), (52, "rt1")):
                    r = u(v + off)
                    if r:
                        self.dump_rt((r - RTS) // 1168)
                        emit("  %s bias %08x" % (lab, fx(u(r + 100))))
                self.dump_frame()
                self.dump_frame_memory()
            elif code == OP_MAT:
                m = self.mat_at(rdi())
                for j in range(16):
                    self.w32(m + 4 * j, rd())
            elif code == OP_SETRTM:
                k = rdi()
                r = self.rt_at(k)
                for off in (1144, 1148, 1152, 1156, 1160):
                    self.w32(r + off, self.mat_at(rdi()))
                self.rt2[k][1] = self.mat_at(rdi())
            elif code == OP_PACKS:
                k = rdi()
                emit("packs RT%d" % k)
                self.rl.packs(self.rt_at(k))
                self.dump_rt(k)
                self.dump_frame()
                self.dump_frame_memory()
            elif code == OP_SETVM:
                v, slot, m = rdi(), rdi(), rdi()
                self.w32(self.view_at(v) + 68 + 4 * min(slot, 7),
                         self.mat_at(m))
            elif code == OP_L2C:
                k, which, o, l = rdi(), rdi(), rdi(), rdi()
                emit("l2c V%d %d X%d X%d" % (k, which, o, l))
                self.call("l2sc" if which == 0 else "l2c", self.view_at(k),
                          self.mat_at(o), self.mat_at(l))
                self.dump_words("o", self.mat_at(o), 16)
            elif code == OP_BIAS:
                k, m = rdi(), rdi()
                s = rd()
                emit("bias V%d X%d %08x" % (k, m, fx(s)))
                self.call("bias", self.view_at(k), self.mat_at(m), f=(s,))
                self.dump_words("m", self.mat_at(m), 16)
            elif code == OP_PIX:
                k = rdi()
                r, d = rd(2)
                res = self.call("pix", self.view_at(k), f=(r, d))
                emit("pix V%d %08x %08x -> %d" % (k, fx(r), fx(d), s32(res)))
            elif code == OP_PIXS:
                k = rdi()
                p = rd(4)
                r = rd()
                for j in range(4):
                    self.w32(self.vec + 4 * j, p[j])
                res = self.call("pixs", self.view_at(k), self.vec, f=(r,))
                emit("pixs V%d %08x %08x %08x %08x -> %d"
                     % (k, fx(p[0]), fx(p[1]), fx(p[2]), fx(r), s32(res)))
            elif code == OP_PIXB:
                k = rdi()
                mn, mx = rd(4), rd(4)
                for j in range(4):
                    self.w32(self.vec + 4 * j, mn[j])
                    self.w32(self.vec + 16 + 4 * j, mx[j])
                res = self.call("pixb", self.view_at(k), self.vec,
                                self.vec + 16)
                emit("pixb V%d %s -> %d" % (k, " ".join(
                    "%08x" % fx(x) for x in mn[:3] + mx[:3]), s32(res)))
            elif code == OP_SCREENPOS:
                k = rdi()
                p = rd(4)
                for j in range(4):
                    self.w32(self.vec + 4 * j, p[j])
                o = self.vec + 32
                self.fill(o, 4, opno)
                self.call("spos", self.view_at(k), o, self.vec)
                emit("spos V%d %s -> %s" % (k, " ".join(
                    "%08x" % fx(x) for x in p[:3]), self.words(o, 4)))
            elif code == OP_SWH:
                k = rdi()
                self.call("swidth", self.view_at(k))
                a = e.fpr[0]
                self.call("sheight", self.view_at(k))
                emit("swh V%d %08x %08x" % (k, fx(a), fx(e.fpr[0])))
            elif code == OP_LIGHT:
                k = rdi()
                v = self.view_at(k)
                emit("light V%d" % k)
                self.rl.light(k, v)
                emit("  wlc %s" % n(u(v + 108)))
                self.dump_frame()
                self.dump_frame_memory()
            elif code == OP_SUN:
                for j in range(4):
                    self.w32(SUN + 4 * j, rd())
            elif code == OP_SETH:
                v = self.view_at(rdi())
                self.w32(v + 8, rd())
            else:
                raise SystemExit("unknown op %d" % code)
        return self.out


def model(sc):
    m = Model(sc)
    lines = m.run()
    if m.e.eediv_pcs:
        sys.exit("the model divided by zero at %s -- the port follows IEEE "
                 "there; keep the script clear of it"
                 % " ".join("%08x" % p for p in sorted(m.e.eediv_pcs)))
    return lines


# ---------------------------------------------------------------- running

HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def write_script(sc, path):
    Path(path).write_text(" ".join("%x" % x for x in sc.words) + NL)


def run_harness(exe, script_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(script_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line[:400])
    return bad


def build(tmp):
    return hostbuild.build(tmp, SOURCES, name="eview_test")


# -------------------------------------------------------------- mutations


def _m(name, old, new, rel=EVM):
    return (name, rel, old, new)


MUTATIONS = [
    # eview.c: the constructors and eInitViews
    _m("construct-bias", "    v->FovBias = 1.0f;", "    v->FovBias = 0.0f;", EVC),
    _m("construct-prev", "    v->CameraMoverList.prev = &v->CameraMoverList;\n"
       "    v->FovBias = 1.0f;", "    v->FovBias = 1.0f;", EVC),
    _m("init-fovz", "    aBaselineFovZ = 9102;", "    aBaselineFovZ = 9103;", EVC),
    _m("init-fovmip", "    aBaselineFovMip = 16384;",
       "    aBaselineFovMip = 16383;", EVC),
    _m("init-views-count", "    for (i = 0; i < EVIEW_NUM_VIEWS; i++)\n"
       "        eview_construct(&eViews[i]);",
       "    for (i = 0; i < EVIEW_NUM_VIEWS - 1; i++)\n"
       "        eview_construct(&eViews[i]);", EVC),
    _m("init-camera-skip", "    camera_init(&Player2Camera);", "    (void)0;",
       EVC),
    _m("initviews-v0-active",
       "    v->Active = 1;\n    v->pCamera = &FlailerCamera;",
       "    v->Active = 0;\n    v->pCamera = &FlailerCamera;", EVC),
    _m("initviews-v0-rt1", "    v->pRenderTarget1 = eGetRenderTarget(3);",
       "    v->pRenderTarget1 = eGetRenderTarget(4);", EVC),
    _m("initviews-v1-rt1", "    v->pRenderTarget1 = eGetRenderTarget(4);",
       "    v->pRenderTarget1 = eGetRenderTarget(3);", EVC),
    _m("initviews-v3-rt", "    v->pRenderTarget0 = eGetRenderTarget(7);",
       "    v->pRenderTarget0 = eGetRenderTarget(6);", EVC),
    _m("initviews-v3-id", "    v->ID = 3;", "    v->ID = 2;", EVC),
    _m("initviews-v2-cam", "    v->pCamera = &Player2Camera;",
       "    v->pCamera = &Player1Camera;", EVC),
    # the names and the lookups
    _m("name-none", '        return "EVIEW_NONE";',
       '        return "EVIEW_UNKNOWN(?)";', EVC),
    _m("name-none-id", "    if (id == -1)", "    if (id == -2)", EVC),
    _m("name-bound", "    if (id >= 0 && id < EVIEW_NUM_VIEWS)",
       "    if (id >= 0 && id < EVIEW_NUM_VIEWS - 1)", EVC),
    _m("name-swap", '"EVIEW_ENVMAP0U", "EVIEW_ENVMAP0D"',
       '"EVIEW_ENVMAP0D", "EVIEW_ENVMAP0U"', EVC),
    _m("curcam-null",
       "    return pCurrentView != 0 ? pCurrentView->pCamera : 0;",
       "    return pCurrentView != 0 ? pCurrentView->pCamera"
       " : &FlailerCamera;", EVC),
    _m("getview", "    return &eViews[id];", "    return &eViews[id ^ 1];", EVC),
    _m("getrt", "    return &RenderTargets[id];",
       "    return &RenderTargets[id ^ 1];", EVC),
    # the movers
    _m("attach-tail", "    v->CameraMoverList.next = mover;\n"
       "    head->prev = mover;\n    mover->next = head;\n"
       "    mover->prev = &v->CameraMoverList;",
       "    bNode *tail = v->CameraMoverList.prev;\n    (void)head;\n"
       "    v->CameraMoverList.prev = mover;\n    tail->next = mover;\n"
       "    mover->prev = tail;\n    mover->next = &v->CameraMoverList;", EVC),
    _m("attach-no-update", "    mover->prev = &v->CameraMoverList;\n"
       "    eUpdateViewMode();", "    mover->prev = &v->CameraMoverList;", EVC),
    _m("unattach-no-update", "    next->prev = prev;\n    eUpdateViewMode();",
       "    next->prev = prev;", EVC),
    _m("unattach-no-back", "    next->prev = prev;\n    eUpdateViewMode();",
       "    eUpdateViewMode();", EVC),
    _m("mode-3-mirror",
       "    if (first_mover(v1) != 0 && first_mover(v2) != 0 && !eViewShowOne)",
       "    if (first_mover(v1) != 0 && first_mover(v3) != 0\n"
       "        && first_mover(v2) != 0 && !eViewShowOne)", EVC),
    _m("mode-3-alone",
       "    if (first_mover(v1) != 0 && first_mover(v2) != 0 && !eViewShowOne)",
       "    if (first_mover(v2) != 0 && !eViewShowOne)", EVC),
    _m("mode-2", "        CurrentViewMode = 2;", "        CurrentViewMode = 4;",
       EVC),
    _m("mode-1", "        CurrentViewMode = 1;", "        CurrentViewMode = 0;",
       EVC),
    _m("mode-0", "        CurrentViewMode = 0;", "        CurrentViewMode = 1;",
       EVC),
    _m("first-mover-head", "    return n != &v->CameraMoverList ? n : 0;",
       "    return n;", EVC),
    # MaybeChangeViewMode
    _m("maybe-tweak-ignored", "    if (TweakerViewMode != 0) {",
       "    if (0) {", EVC),
    _m("maybe-tweak-nowait",
       "            if (gEWaitUntilRenderingDoneFn != 0)\n"
       "                gEWaitUntilRenderingDoneFn();\n"
       "            RenderingViewMode = TweakerViewMode;",
       "            RenderingViewMode = TweakerViewMode;", EVC),
    _m("maybe-tweak-always",
       "        if (RenderingViewMode != TweakerViewMode) {",
       "        if (1) {", EVC),
    _m("maybe-wait-always",
       "    } else if (RenderingViewMode != CurrentViewMode) {",
       "    } else if (1) {", EVC),
    _m("maybe-p1b",
       "    p1b = v1->pRenderTarget1 != 0 ? v1->pRenderTarget1 : p1;",
       "    p1b = v1->pRenderTarget1 != 0 ? v1->pRenderTarget1 : p2;", EVC),
    _m("maybe-p2b",
       "    p2b = v2->pRenderTarget1 != 0 ? v2->pRenderTarget1 : p2;",
       "    p2b = v2->pRenderTarget1 != 0 ? v2->pRenderTarget1 : p1;", EVC),
    _m("maybe-wh-swap", "    h = MainDraw0Context->ScissorH;\n"
       "    w = MainDraw0Context->ScissorW;",
       "    h = MainDraw0Context->ScissorW;\n"
       "    w = MainDraw0Context->ScissorH;", EVC),
    _m("maybe-case1", "    case 0:\n    case 1:", "    case 0:\n    case 5:",
       EVC),
    _m("maybe-mirror-size",
       "        mirror->ScissorW = 256; mirror->ScissorH = 64;",
       "        mirror->ScissorW = 64; mirror->ScissorH = 256;", EVC),
    _m("maybe-mode2-mirror-off", "        mirror->Active = 1; v3->Active = 1;",
       "        mirror->Active = 0; v3->Active = 1;", EVC),
    _m("maybe-half-shift", "        half = h >> 1;", "        half = h / 2;",
       EVC),
    _m("maybe-mode4-half", "        half = w >> 1;",
       "        half = (w + 1) >> 1;", EVC),
    _m("maybe-mode3-p2y", "        p2->ScissorX = 0; p2->ScissorY = half;",
       "        p2->ScissorX = 0; p2->ScissorY = 0;", EVC),
    _m("maybe-mode4-p2x", "        p2->ScissorX = half; p2->ScissorY = 0;",
       "        p2->ScissorX = 0; p2->ScissorY = 0;", EVC),
    _m("maybe-mode3-p2b", "        p2b->ScissorX = 0; p2b->ScissorY = half;",
       "        p2b->ScissorX = 0; p2b->ScissorY = 0;", EVC),
    _m("maybe-store-order",
       "        mirror->ScissorX = 0; mirror->ScissorY = 0;\n"
       "        mirror->ScissorW = 0; mirror->ScissorH = 0;\n"
       "        p1b->ScissorH = h; p1b->ScissorW = w;\n"
       "        p1b->ScissorX = 0; p1b->ScissorY = 0;\n",
       "        p1b->ScissorH = h; p1b->ScissorW = w;\n"
       "        p1b->ScissorX = 0; p1b->ScissorY = 0;\n"
       "        mirror->ScissorX = 0; mirror->ScissorY = 0;\n"
       "        mirror->ScissorW = 0; mirror->ScissorH = 0;\n", EVC),
    _m("maybe-active-order",
       "        p1->Active = 1; v1->Active = 1;\n"
       "        p2->Active = 0; v2->Active = 0;\n"
       "        mirror->Active = 0; v3->Active = 0;",
       "        mirror->Active = 0; v3->Active = 0;\n"
       "        p1->Active = 1; v1->Active = 1;\n"
       "        p2->Active = 0; v2->Active = 0;", EVC),
    _m("maybe-mode-wrap", "    switch ((uint32_t)RenderingViewMode) {",
       "    switch ((uint32_t)RenderingViewMode % 5u) {", EVC),
    # CalculateH
    _m("tan-half", "    uint16_t half = (uint16_t)(fov >> 1);",
       "    uint16_t half = (uint16_t)((fov >> 1) + 1);"),
    _m("calch-ten", "    if (t == 0.0f)\n        return 10.0f;",
       "    if (t == 0.0f)\n        return 11.0f;"),
    _m("calch-no-check", "    if (t == 0.0f)\n        return 10.0f;",
       "    if (0)\n        return 10.0f;"),
    _m("calch-shift", "    return (float)(ScreenWidth >> 1) / t;",
       "    return (float)(ScreenWidth / 2) / t;"),
    # CreateViewMatricies
    _m("bias-rt1-skip", "    if (rt1 != 0)\n        rt1->FovBias = bias;",
       "    (void)rt1;"),
    _m("bias-inverted", "    bias = tan_bam(aBaselineFovMip) / "
       "tan_bam(cam->CurrentKey.FieldOfView);",
       "    bias = tan_bam(cam->CurrentKey.FieldOfView) / "
       "tan_bam(aBaselineFovMip);"),
    _m("fixed-drive-only",
       "                       || ((CameraMover *)first)->Type == CM_BUMPER))",
       "                       || 0))"),
    _m("fixed-mirror", "->Type == CM_BUMPER))",
       "->Type == CM_REAR_VIEW_MIRROR))"),
    _m("fixed-ignored", "    if ((uint32_t)view->ID - 1u < 2u && !fixed) {",
       "    if ((uint32_t)view->ID - 1u < 2u) {"),
    _m("scale-ids", "    if ((uint32_t)view->ID - 1u < 2u && !fixed) {",
       "    if ((uint32_t)view->ID - 1u < 3u && !fixed) {"),
    _m("scale-signed", "    if ((uint32_t)view->ID - 1u < 2u && !fixed) {",
       "    if (view->ID >= 0 && view->ID < 3 && !fixed) {"),
    _m("scale-depth", "        far = near + depth;",
       "        far = far + 0.0f * depth;"),
    _m("scale-z", "        float s = tan_bam(aBaselineFovZ) / "
       "tan_bam(cam->CurrentKey.FieldOfView);",
       "        float s = tan_bam(aBaselineFovMip) / "
       "tan_bam(cam->CurrentKey.FieldOfView);"),
    _m("near-override", "    if (nearz != 0.0f)\n        near = nearz;",
       "    (void)nearz;"),
    _m("far-override", "    if (farz != 0.0f)\n        far = farz;",
       "    (void)farz;"),
    _m("ef-override", "        if (e_farz != 0.0f)\n            ef = e_farz;",
       "        (void)e_farz;"),
    _m("viewdir", "    view->ViewDirection = cam->CurrentKey.Direction;",
       "    view->ViewDirection = cam->CurrentKey.Position;"),
    _m("fovdeg-scale", "* 0.0054931640625f;", "* 0.0055f;"),
    _m("fovdeg-signed", "(float)(int32_t)cam->CurrentKey.FieldOfView",
       "(float)(int16_t)cam->CurrentKey.FieldOfView"),
    _m("view-near", "    view->NearZ = near;", "    view->NearZ = far;"),
    _m("view-h", "    view->H = h;", "    view->H = invh;"),
    _m("ma0", "    ma[0] = rt0->AspectRatioX;", "    ma[0] = rt0->AspectRatioY;"),
    _m("ma8", "    ma[8] = CenterX / h;", "    ma[8] = CenterY / h;"),
    _m("ma10-order",
       "    ma[10] = (-z->ZMax * near + z->ZMin * far) / span / h;",
       "    ma[10] = (-z->ZMax * near + z->ZMin * far) / (span * h);"),
    _m("ma11", "    ma[11] = invh;", "    ma[11] = 0.0f;"),
    _m("ma14", "    ma[14] = nf * (z->ZMax - z->ZMin) / span / h;",
       "    ma[14] = nf * (z->ZMax - z->ZMin) / span * invh;"),
    _m("ml10", "    ml[10] = (-z->ZMax1 * near + z->ZMin1 * far) / span / h;",
       "    ml[10] = (-z->ZMax * near + z->ZMin1 * far) / span / h;"),
    _m("ml14", "    ml[14] = nf * (z->ZMax1 - z->ZMin1) / span / h;",
       "    ml[14] = nf * (z->ZMax1 - z->ZMin) / span / h;"),
    _m("m2-10", "    m2[10] = (-z->ZMax2 * near + z->ZMin2 * far) / span / h;",
       "    m2[10] = (-z->ZMax2 * near + z->ZMin1 * far) / span / h;"),
    _m("m2-14", "    m2[14] = nf * (z->ZMax2 - z->ZMin2) / span / h;",
       "    m2[14] = nf * (z->ZMax1 - z->ZMin2) / span / h;"),
    _m("z-range-any", "    return &ZRanges[rt->ZBufferMode == GS_PSMZ24];",
       "    return &ZRanges[rt->ZBufferMode != 0];", EVC),
    _m("z-range-first", "    z = eview_z_range(rt0);",
       "    z = &ZRanges[0];"),
    _m("z-table-value", "      4.5f, 7.5f },", "      4.5f, 7.0f },", EVC),
    _m("d2-from-l", "                eMulMatrix(d2, &n, &l2);",
       "                eMulMatrix(d2, &n, &l);"),
    _m("gx-clamp", "    if (gx < cx)\n        cx = gx;", "    (void)0;"),
    _m("gy-clamp", "    if (gy < cy)\n        cy = gy;", "    (void)0;"),
    _m("cx-half", "    cx = w * 0.5f;", "    cx = w * 0.6f;"),
    _m("b-pq-swap", "        mm[0] = (near + near) / (q + q);\n"
       "        mm[5] = (near + near) / (p + p);",
       "        mm[0] = (near + near) / (p + p);\n"
       "        mm[5] = (near + near) / (q + q);"),
    _m("b-mm10", "        mm[10] = (far + near) / (far - near);",
       "        mm[10] = (far - near) / (far + near);"),
    _m("b-mm14", "        mm[14] = nf * -2.0f / (far - near);",
       "        mm[14] = nf * 2.0f / (far - near);"),
    _m("b-mm15", "        mm[15] = 0.0f;\n        memcpy(b, mm, sizeof mm);",
       "        mm[15] = 1.0f;\n        memcpy(b, mm, sizeof mm);"),
    _m("b-mm11", "        mm[11] = 1.0f;\n        mm[14] = nf",
       "        mm[11] = 0.0f;\n        mm[14] = nf"),
    _m("b-clamped", "        p = near * gy / h;\n        q = near * gx / h;",
       "        p = near * cy / h;\n        q = near * cx / h;"),
    _m("c-skip", "            if (c != 0)\n                eMulMatrix(c, &n, a);",
       "            (void)0;"),
    _m("d-from-a", "                eMulMatrix(d, &n, &l);",
       "                eMulMatrix(d, &n, a);"),
    _m("cd-guard", "        if (c != 0 || d != 0) {", "        if (d != 0) {"),
    _m("mn0", "            mn[0] = 1.0f / mm[0];", "            mn[0] = mm[0];"),
    _m("mn10", "            mn[10] = 0.0f;", "            mn[10] = 1.0f;"),
    _m("mn11", "            mn[11] = 1.0f / mm[14];",
       "            mn[11] = 1.0f / mm[10];"),
    _m("mn14", "            mn[14] = 1.0f;", "            mn[14] = 0.0f;"),
    _m("mn15", "            mn[15] = -mm[10] / mm[14];",
       "            mn[15] = mm[10] / mm[14];"),
    _m("e-unclamped", "        p = near * cx / h;\n        q = near * cy / h;",
       "        p = near * gx / h;\n        q = near * gy / h;"),
    _m("e-mm14", "        mm[14] = ef * near * -2.0f / (ef - near);",
       "        mm[14] = nf * -2.0f / (ef - near);"),
    _m("e-mm10", "        mm[10] = (ef + near) / (ef - near);",
       "        mm[10] = (far + near) / (ef - near);"),
    _m("a-order", "    eMulMatrix(a, b, c);\n}", "    eMulMatrix(a, c, b);\n}"),
    _m("a-skip", "    eMulMatrix(a, b, c);\n}", "    (void)c;\n}"),
    # CalculateViewMatricies
    _m("vu-row3", "    v[4] = s[12];", "    v[4] = s[3];"),
    _m("vu-zero3", "    v[3] = 0.0f;", "    v[3] = s[15];"),
    _m("vu-inv-diag", "    v[10] = si[10];", "    v[10] = s[10];"),
    _m("vu-inv-row3", "    v[15] = si[15];", "    v[15] = s[15];"),
    _m("calc-fail-hack", "            p[i] = &eMathIdentityMatrix;",
       "            p[i] = &hack_man_matrix;"),
    _m("calc-no-invert-d", "        fInvertMatrix(&di, &d);", "        di = d;"),
    _m("calc-vu1-from-c", "        vu_clip_screen(&blk[7], &d, &di);",
       "        vu_clip_screen(&blk[7], &c, &ci);"),
    _m("calc-blk3", "        eMulMatrix(&blk[3], &blk[0], &e);",
       "        eMulMatrix(&blk[3], &blk[0], &b);"),
    _m("calc-blk2", "        eMulMatrix(&blk[2], &blk[0], &a);",
       "        eMulMatrix(&blk[2], &blk[0], &e);"),
    _m("calc-blk1-order", "        eMulMatrix(&blk[1], &blk[0], &b);",
       "        eMulMatrix(&blk[1], &b, &blk[0]);"),
    _m("calc-blk4", "        blk[4] = c;", "        blk[4] = d;"),
    _m("calc-size", "    blk = eframe_malloc(9 * sizeof(bMatrix4));",
       "    blk = eframe_malloc(8 * sizeof(bMatrix4));"),
    _m("calc-no-invert-d2", "        fInvertMatrix(&d2i, &d2);",
       "        d2i = d2;"),
    _m("calc-vu2-from-d", "        vu_clip_screen(&blk[8], &d2, &d2i);",
       "        vu_clip_screen(&blk[8], &d, &di);"),
    _m("calc-view-vu2", "    view->VUClipScreenMatrix2 = p[8];",
       "    view->VUClipScreenMatrix2 = p[7];"),
    _m("calc-viewscreen", "    view->ViewScreenMatrix = p[5];",
       "    view->ViewScreenMatrix = p[4];"),
    _m("calc-rt1-skip", "    if (rt1 != 0)\n        set_target(rt1, p);",
       "    (void)rt1;"),
    _m("calc-rt-order", "    if (rt0 != 0)\n        set_target(rt0, p);\n"
       "    if (rt1 != 0)\n        set_target(rt1, p);",
       "    if (rt1 != 0)\n        set_target(rt1, p);\n"
       "    if (rt0 != 0)\n        set_target(rt0, p);"),
    _m("st-wc", "    rt->WorldClip = p[1];", "    rt->WorldClip = p[2];"),
    _m("st-cs", "    rt->ClipScreen = p[4];", "    rt->ClipScreen = p[5];"),
    _m("st-vu1", "    rt->VUClipScreen1 = p[7];",
       "    rt->VUClipScreen1 = p[6];"),
    _m("st-vu2", "    rt->VUClipScreen2 = p[8];",
       "    rt->VUClipScreen2 = p[7];"),
    # SetupMatrixPacks
    _m("packs-lazy",
       "    eRenderTargetMatrixPack *p1 = eframe_malloc(sizeof *p1);",
       "    eRenderTargetMatrixPack *p1 = p0 ? eframe_malloc(sizeof *p1) : 0;"),
    _m("packs-p2-lazy",
       "    eRenderTargetMatrixPack *p2 = eframe_malloc(sizeof *p2);",
       "    eRenderTargetMatrixPack *p2 = p1 ? eframe_malloc(sizeof *p2) : 0;"),
    _m("packs-p1-vu",
       "    rt->MatrixPack1 = fill_pack(p1, rt, rt->VUClipScreen1);",
       "    rt->MatrixPack1 = fill_pack(p1, rt, rt->VUClipScreen);"),
    _m("packs-p2-vu",
       "    rt->MatrixPack2 = fill_pack(p2, rt, rt->VUClipScreen2);",
       "    rt->MatrixPack2 = fill_pack(p2, rt, rt->VUClipScreen1);"),
    _m("packs-default", "        return &DefaultMatrixPack;",
       "        return 0;"),
    _m("packs-wc", "    p->WorldClip = *rt->WorldClip;",
       "    p->WorldClip = *rt->WorldView;"),
    _m("packs-not-transposed",
       "    eTransposeMatrix(&p->WorldViewT, rt->WorldView);",
       "    p->WorldViewT = *rt->WorldView;"),
    # the products and the bias
    _m("l2sc-matrix",
       "    eMulMatrix(o, local, view->WorldScreenClipMatrix);",
       "    eMulMatrix(o, local, view->WorldScreenMatrix);"),
    _m("l2c-order", "    eMulMatrix(o, local, view->WorldClipMatrix);",
       "    eMulMatrix(o, view->WorldClipMatrix, local);"),
    _m("bias-nocam", "    if (cam == 0)\n        return;\n    bIdentity(&s);",
       "    bIdentity(&s);"),
    _m("bias-scale-x", "    s.v0.x = scale;", "    s.v0.x = 1.0f;"),
    _m("bias-d-x", "    d.x = (m->v3.x - cam->CurrentKey.Position.x) * scale"
       " + cam->CurrentKey.Position.x;", "    d.x = m->v3.x * scale;"),
    _m("bias-w", "    m->v3.w = 1.0f;", "    m->v3.w = m->v3.w;"),
    _m("bias-mul-order", "    eMulMatrix(m, m, &s);",
       "    eMulMatrix(m, &s, m);"),
    # the pixel sizes
    _m("pix-half", "    if (r * 0.5f < d)", "    if (r < d)"),
    _m("pix-else", "        s = view->H + view->H;", "        s = view->H;"),
    _m("pix-mul-order", "        s = r * view->H / d;",
       "        s = r * (view->H / d);"),
    _m("pixs-behind", "    if (dot < -r)\n        return 0;\n"
       "    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;\n    if (r * 0.5f",
       "    if (dot < r)\n        return 0;\n"
       "    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;\n    if (r * 0.5f"),
    _m("pixs-dist", "    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;\n"
       "    if (r * 0.5f < dist)",
       "    dist = sqrtf(dx * dx + dy * dy + dz * dz) + r;\n"
       "    if (r * 0.5f < dist)"),
    _m("pixs-dot-z", "              + dz * cam->CurrentKey.Direction.z;",
       "              + dz * cam->CurrentKey.Direction.y;"),
    _m("pixs-else", "    if (r * 0.5f < dist)\n        s = r * view->H / dist;\n"
       "    else\n        s = view->H + view->H;",
       "    if (r * 0.5f < dist)\n        s = r * view->H / dist;\n"
       "    else\n        s = view->H;"),
    _m("pixb-radius",
       "    float r = sqrtf(ex * ex + ey * ey + ez * ez) * 0.5f;",
       "    float r = sqrtf(ex * ex + ey * ey + ez * ez) * 0.25f;"),
    _m("pixb-centre",
       "    float dx = (mn->x + mx->x) * 0.5f - cam->CurrentKey.Position.x;",
       "    float dx = mn->x - cam->CurrentKey.Position.x;"),
    _m("pixb-else", "    s = view->H;\n    if (r < dist)",
       "    s = view->H + view->H;\n    if (r < dist)"),
    _m("pixb-cmp", "    if (r < dist)\n        s = r * view->H / dist;",
       "    if (r * 0.5f < dist)\n        s = r * view->H / dist;"),
    _m("pixb-behind", "    if (dot < -r)\n        return 0;\n"
       "    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;\n    s = view->H;",
       "    if (dot < 0.0f)\n        return 0;\n"
       "    dist = sqrtf(dx * dx + dy * dy + dz * dz) - r;\n    s = view->H;"),
    # the screen
    _m("spos-w", "    v.w = 1.0f;\n    eRotTransPers",
       "    v.w = p->pad;\n    eRotTransPers"),
    _m("spos-half-x", "(float)(rt->ScissorW / 2);",
       "(float)(rt->ScissorW >> 1);"),
    _m("spos-y-w", "(float)(rt->ScissorH / 2);", "(float)(rt->ScissorW / 2);"),
    _m("spos-z", "    o->z = s.z;", "    o->z = s.w;"),
    _m("spos-order",
       "    o->x = (s.x - 2048.0f) + (float)(rt->ScissorW / 2);",
       "    o->x = s.x + ((float)(rt->ScissorW / 2) - 2048.0f);"),
    _m("swh-height", "    return (float)view->pRenderTarget0->ScissorH;",
       "    return (float)view->pRenderTarget0->ScissorW;"),
    # the light context
    _m("light-noclear",
       "    view->WorldLightContext = 0;\n    cam = view->pCamera;",
       "    cam = view->pCamera;"),
    _m("light-eye-x",
       "    eye.x = cam->CurrentKey.Position.x - m->v0.z * 10.0f;",
       "    eye.x = cam->CurrentKey.Position.x - m->v0.x * 10.0f;"),
    _m("light-eye-y",
       "    eye.y = cam->CurrentKey.Position.y - m->v1.z * 10.0f;",
       "    eye.y = cam->CurrentKey.Position.y - m->v1.z * 9.0f;"),
    _m("light-eye-z",
       "    eye.z = cam->CurrentKey.Position.z - m->v2.z * 10.0f + 4.0f;",
       "    eye.z = cam->CurrentKey.Position.z - m->v2.z * 10.0f + 7.0f;"),
    _m("light-eye-w", "    eye.w = 1.0f;", "    eye.w = 0.0f;"),
    _m("light-hack", "        gElSetupLightContextFn(lc, &eMathIdentityMatrix,"
       " &hack_man_matrix,", "        gElSetupLightContextFn(lc,"
       " &hack_man_matrix, &eMathIdentityMatrix,"),
    _m("light-up", "    bVector3 up = {0.0f, 0.0f, 1.0f, 0.0f};",
       "    bVector3 up = {0.0f, 1.0f, 0.0f, 0.0f};"),
    _m("light-look-args",
       "    eCreateLookAtMatrix(&look, &SunPosition, &origin, &up);",
       "    eCreateLookAtMatrix(&look, &origin, &SunPosition, &up);"),
    _m("light-envmap", "    lc->LocalLightPositions = look;",
       "    lc->EnvMapMatrix = look;"),
    _m("light-positions", "    lc->LocalLightPositions = look;",
       "    (void)look;"),
    _m("light-size", "    lc = eframe_malloc(sizeof *lc);",
       "    lc = eframe_malloc(256);"),
]

EQUIVALENT = {
    # eRotTransPers transforms with w forced to 1, so the w GetScreenPosition
    # puts in its vector is never read.
    "spos-w",
}

write_source = hostbuild.write_source


def mutate_pass(sc, base_model):
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, sp, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                sp = Path(tmp) / "script.txt"
                write_script(sc, sp)
                try:
                    exe = build(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, sp, out)
                if rc == HARNESS_HUNG:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                k = diff(base_model, out.read_text().splitlines(), quiet=True)
                if k:
                    print("  %-28s caught, %d lines" % (name, k))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-28s SURVIVED" % name)
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
    stale = [k for k in EQUIVALENT
             if k not in equivalent and k not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for k in holes:
        print("  unexplained: %s" % k)
    for k in stale:
        ran = any(m[0] == k for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", k))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    sc = script()
    lines = model(sc)
    if args.mutate:
        sys.exit(mutate_pass(sc, lines))

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sp, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            (d / "script.txt").write_text(sp.read_text())

    bad = diff(lines, harness)
    ops = sum(1 for line in lines if not line.startswith(" "))
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc.tags), ops, len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
