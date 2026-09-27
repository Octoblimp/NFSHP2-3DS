#!/usr/bin/env python3
"""Cross-check 3DS Files/source/scenerycull.c against the image.

The cull half of Scenery.obj (0x0014d460 .. 0x0014e59c): IsVisible,
CullBruteForce, TreeCull, CullNodeRecursive, DrawAScenery,
WhatSectionsShouldWeDraw, CullView, BatchCullViews, DoCulling and
StuffScenery. With them, ClassifyAABB (0x0010b940) and IsBoundingBoxVisible
(0x0010bb10) from beside eModel's methods, SetupSceneryCullInfo (0x0010e370)
and eDisplayFrame's loop over the views (0x00112d18 .. 0x00112df0, run in
place), and Ecstasy.obj's frame malloc (0x0019d9e0 .. 0x0019db2c): the
buffers, their swap, their size, and the inline allocation DrawAScenery
makes.

The image is the oracle: tools/mipsemu.py runs the shipped functions out of
NFSHP2.ELF, the harness (tools/src/scenerycull_test.c) runs the port, both
walk the same script, and the two transcripts are diffed. No address is
printed; the harness's head has the naming scheme. Floats are compared as
bits, with every NaN printed as the one quiet NaN.

The sections are built straight from the script on both sides, not through
the loader, which scenery_check has checked. eModel::Render, bMalloc and
bFree are stubbed in the model and seamed or hooked in the harness, and
each prints its call.

The script covers:

  * the frame malloc: buffers of several sizes, one not a multiple of 32,
    the swap with and without a failed frame, the size query and the free;
  * ClassifyAABB on boxes inside, across and outside each plane, outside
    two planes at once, on a plane exactly, behind the eye, with -0, NaN
    and infinities, and on random boxes through random matrices;
  * DrawAScenery down every branch: the box's class, the exclusion, the
    size on the screen (behind, near, far, below 2), each LOD's clip and
    model, the objects drawn in place, the frame malloc failing, a full
    table, facades, and the 2 m raise;
  * the tree culls on made-up trees, nodes in and out and across, codes
    that push nodes, a child count past five, and code 0; IsVisible and
    the brute-force cull;
  * WhatSectionsShouldWeDraw with a zone and without, the nineties, sections
    not loaded and negative, each limit, and the zone number for view 1 and
    the others; CullView, BatchCullViews over shared sections, DoCulling
    and StuffScenery;
  * SetupSceneryCullInfo over the view ids, the view modes and the track
    directions, and eDisplayFrame's loop over the views;
  * TRACKB12: every section and zone, and DoCulling and StuffScenery from
    cameras at every zone's centre and at points over the track.

    python tools/scenerycull_check.py
    python tools/scenerycull_check.py --mutate
    python tools/scenerycull_check.py --dump out/scenerycull
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
import scenery_check as sck

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

SOURCES = [
    "tools/src/scenerycull_test.c",
    "3DS Files/source/scenerycull.c",
    "3DS Files/source/eframe.c",
    "3DS Files/source/eview.c",
    "3DS Files/source/camera.c",
    "3DS Files/source/scenery.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/race.c",
]

SC = "3DS Files/source/scenerycull.c"
EF = "3DS Files/source/eframe.h"
EFC = "3DS Files/source/eframe.c"
EVC = "3DS Files/source/eview.c"

(OP_TAG, OP_SECTION, OP_UNSECTION, OP_ZONE, OP_ZCLEAR, OP_VIEW,
 OP_CI, OP_NUMCI, OP_CLASSIFY, OP_BBVIS, OP_ISVIS, OP_DRAW, OP_BRUTE,
 OP_TREE, OP_RECURSE, OP_WHAT, OP_CULLVIEW, OP_BATCH, OP_DOCULL,
 OP_STUFF, OP_SETUP, OP_SETUPVIEWS, OP_MODE, OP_DIR, OP_ENV, OP_FALLOC,
 OP_FSWAP, OP_FFREE, OP_FSIZE, OP_FSET, OP_CURZONE, OP_DUMPG) = range(1, 33)

NSECT = 160
NMODEL = 8192
NZONE = 64
NLIGHT = 16
NVIEW = 10
GUARD = 2
MS = 32                     # the model's stride between made-up eModels

GP = 0x00328bf0
SSHL = GP - 22576
VZL = GP - 22568
CURZONE = GP - 22584
VIEWMODE = GP - 25432
ENVMAP = GP - 21656
INGAME = GP - 21960
FSIZE = GP - 20048
FPOS = GP - 20044
FEND = GP - 20040
FALLOCN = GP - 20032
FFAILED = GP - 20028
FAMOUNT = GP - 20024
FMAX = GP - 20020
FBUF = GP - 19976
FUSED = GP - 19968
TABLE = 0x002f1018
DRAWS = 0x002e8cd8
NDRAWS = 4200
VIEWS = 0x002ab230
DIRECTION = 0x0031252c

# eDisplayFrame's loop over the views, run in place: from the InGameFlag
# load to the DoCulling call, with the grand info at s7 and its count at
# 2096(sp).
SETUP_FROM = 0x00112d18
SETUP_TO = 0x00112df0

SYM = {
    "classify": "ClassifyAABB__FPC8bVector4T0PC8bMatrix4",
    "bbvis": "IsBoundingBoxVisible__FP8bVector3T0P8bMatrix4",
    "isvis": "IsVisible__20ScenerySectionHeaderP15SceneryCullInfo",
    "draw": "DrawAScenery__20ScenerySectionHeaderiP15SceneryCullInfoi",
    "brute": "CullBruteForce__20ScenerySectionHeaderP15SceneryCullInfo",
    "tree": "TreeCull__20ScenerySectionHeaderP15SceneryCullInfo",
    "recurse": "CullNodeRecursive__20ScenerySectionHeaderP15SceneryTreeNode"
               "P15SceneryCullInfoUi",
    "what": "WhatSectionsShouldWeDraw__20GrandSceneryCullInfoPsiP15Scenery"
            "CullInfo",
    "cullview": "CullView__20GrandSceneryCullInfoP15SceneryCullInfo",
    "batch": "BatchCullViews__20GrandSceneryCullInfo",
    "docull": "DoCulling__20GrandSceneryCullInfo",
    "stuff": "StuffScenery__20GrandSceneryCullInfoP5eView",
    "setup": "SetupSceneryCullInfo__FP5eViewR15SceneryCullInfo",
    "falloc": "eAllocateFrameMallocBuffers__FUi",
    "fswap": "eSwapFrameMallocBuffers__Fv",
    "ffree": "eFreeFrameMallocBuffers__Fv",
    "fsize": "eGetSizeofFrameMallocBuffers__FPi",
    "sinit": "_GLOBAL_$I$CurrentZoneNumber",
}

bits = me.f_to_bits
fbits = me.fbits_to
s32 = sck.s32
s16 = sck.s16
fx = sck.fx
u32at = sck.u32at


def f32(x):
    return fbits(bits(x))


# ---------------------------------------------------------------- script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []
        self.live = set()       # sections on the list
        self.nzones = 0

    def op(self, code, *args):
        self.words.append(code)
        for a in args:
            if isinstance(a, float):
                self.words.append(bits(a))
            else:
                self.words.append(a & M32)

    def tag(self, name):
        self.tags.append(name)
        self.op(OP_TAG, len(self.tags) - 1)

    def section(self, k, sec, kinds, insts, tree, head=False):
        """kinds: (hashes, clips, models, facades, radius) with models as
        made-up model numbers (0 for none); insts: 48-byte records; tree:
        24-byte records."""
        assert k not in self.live and k < NSECT
        ws = []
        for hashes, clips, mods, facades, radius, dummy in kinds:
            ws += list(hashes)
            ws.append((clips[0] & 0xFFFF) | ((clips[1] & 0xFFFF) << 16))
            ws.append((clips[2] & 0xFFFF) | ((dummy[0] & 0xFFFF) << 16))
            ws += list(mods)
            ws.append(facades[0] | (facades[1] << 8) | (facades[2] << 16)
                      | (dummy[1] << 24))
            ws.append(bits(radius) if isinstance(radius, float) else radius)
        for r in insts:
            assert len(r) == 48
            ws += struct.unpack("<12I", r)
        for r in tree:
            assert len(r) == 24
            ws += struct.unpack("<6I", r)
        self.op(OP_SECTION, k, sec, 1 if head else 0, len(kinds), len(insts),
                len(tree), *ws)
        self.live.add(k)

    def unsection(self, k):
        self.op(OP_UNSECTION, k)
        self.live.discard(k)

    def zone(self, number, secs, pts):
        assert self.nzones < NZONE
        self.nzones += 1
        s = list(secs) + [0] * (64 - len(secs))
        ws = [(s[i] & 0xFFFF) | ((s[i + 1] & 0xFFFF) << 16)
              for i in range(0, 64, 2)]
        p = []
        for x, y in pts:
            p += [float(x), float(y)]
        p += [0.0] * (32 - len(p))
        self.op(OP_ZONE, number, len(secs), *ws)
        self.words.append(len(pts))
        self.op_words(p)

    def zclear(self):
        self.op(OP_ZCLEAR)
        self.nzones = 0

    def op_words(self, vals):
        for v in vals:
            self.words.append(bits(v) if isinstance(v, float) else v & M32)

    def view(self, v, vid, active, rt, h, light, pos, dirn, wv, clip):
        self.op(OP_VIEW, v, vid, active, rt)
        self.op_words([float(h), light] + fl(pos, 4) + fl(dirn, 4)
                      + fl(wv, 16) + fl(clip, 16))

    def ci(self, i, view, flags, facade, clip, pos, dirn, h, first, cur,
           top):
        self.op(OP_CI, i, view, flags)
        self.op_words(fl(facade, 16) + fl(clip, 16) + fl(pos, 4)
                      + fl(dirn, 4) + [float(h)] + [first, cur, top])

    def classify(self, mn, mx, m, op=OP_CLASSIFY):
        self.op(op)
        self.op_words(fl(mn, 4) + fl(mx, 4) + fl(m, 16))


def fl(vals, n):
    """Floats, or raw bits where an int is given."""
    vals = list(vals)
    assert len(vals) == n, (len(vals), n)
    return [v if isinstance(v, int) else float(v) for v in vals]


IDENT = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
ZERO16 = [0.0] * 16


def box(mn, mx):
    return list(mn) + list(mx)


def inst(kind, flags=0, bx=(0, 0, 0, 0, 0, 0), pos=(0.0, 0.0, 0.0),
         rot=(16384, 0, 0, 0, 16384, 0, 0, 0, 16384), pad=0):
    return sck.instance(kind, flags, bx, pos, rot, pad)


def node(bx=(0, 0, 0, 0, 0, 0), codes=(), n=None):
    c = list(codes) + [0] * (5 - len(codes))
    return sck.tree_node(bx, len(codes) if n is None else n, c[:5])


def kind(models=(0, 0, 0), clips=(0, 0, 0), facades=(0, 0, 0), radius=1.0,
         hashes=(0x11, 0, 0), dummy=(0, 0)):
    return (hashes, clips, models, facades, radius, dummy)


# ---- matrices (row vectors, as the engine has them)


def mat_mul(a, b):
    out = []
    for r in range(4):
        for c in range(4):
            out.append(sum(a[4 * r + k] * b[4 * k + c] for k in range(4)))
    return out


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
    return m, fwd


def perspective(fov, aspect, near, far):
    f = 1.0 / math.tan(fov / 2)
    m = [0.0] * 16
    m[0] = f / aspect
    m[5] = f
    m[10] = (far + near) / (far - near)
    m[11] = 1.0
    m[14] = -2.0 * far * near / (far - near)
    return m


def clip_matrix(pos, yaw, pitch, fov=1.1, aspect=1.33, near=0.5, far=2000.0):
    v, fwd = look(pos, yaw, pitch)
    return [f32(x) for x in mat_mul(v, perspective(fov, aspect, near, far))], \
        [f32(x) for x in v], [f32(x) for x in fwd]


# ---------------------------------------------------------------- scenarios


def frame_section(sc):
    sc.tag("frame malloc")
    sc.op(OP_FSIZE)
    sc.op(OP_FALLOC, 256)
    sc.op(OP_FSIZE)
    sc.op(OP_FSWAP)
    sc.op(OP_FSIZE)
    sc.op(OP_FSET, 40, 128, 1, 300, 200)
    sc.op(OP_FSWAP)
    sc.op(OP_FSET, 64, 128, 1, 100, 200)
    sc.op(OP_FSWAP)
    sc.op(OP_FSET, 64, 128, 0, 900, 200)
    sc.op(OP_FSWAP)
    sc.op(OP_FSIZE)
    sc.op(OP_FFREE)
    sc.op(OP_FSIZE)
    sc.op(OP_FALLOC, 100)
    sc.op(OP_FSWAP)
    sc.op(OP_FFREE)
    sc.op(OP_FALLOC, 2621440)
    sc.op(OP_FSWAP)
    sc.op(OP_FSWAP)
    sc.op(OP_FFREE)


def rand_matrix(rnd, scale=2.0):
    return [f32(rnd.uniform(-scale, scale)) for _ in range(16)]


def classify_section(sc, rnd):
    sc.tag("ClassifyAABB")
    I = IDENT
    cases = [
        ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)),       # inside
        ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),       # on every plane
        ((-2.0, -0.5, -0.5), (0.5, 0.5, 0.5)),       # across -x
        ((1.5, -0.5, -0.5), (2.0, 0.5, 0.5)),        # beyond +x
        ((-3.0, -0.5, -0.5), (-2.0, 0.5, 0.5)),      # beyond -x
        ((-0.5, 1.5, -0.5), (0.5, 2.0, 0.5)),        # beyond +y
        ((-0.5, -3.0, -0.5), (0.5, -2.0, 0.5)),      # beyond -y
        ((-0.5, -0.5, 1.5), (0.5, 0.5, 2.0)),        # beyond +z
        ((-0.5, -0.5, -3.0), (0.5, 0.5, -2.0)),      # beyond -z
        ((1.5, 1.5, -0.5), (2.0, 2.0, 0.5)),         # beyond +x and +y
        ((1.0, -0.5, -0.5), (2.0, 0.5, 0.5)),        # touching +x
        ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),          # a point on a corner
        ((-5.0, -5.0, -5.0), (5.0, 5.0, 5.0)),       # around everything
        ((-5.0, 2.0, -5.0), (5.0, 3.0, 5.0)),        # a slab above
        ((0.5, 0.5, 0.5), (-0.5, -0.5, -0.5)),       # min above max
        ((-0.0, -0.0, -0.0), (0.0, 0.0, 0.0)),
    ]
    for mn, mx in cases:
        sc.classify(list(mn) + [0.0], list(mx) + [0.0], I)
    # w from the box: |w| grows with x, and a negative w
    wx = [1.0, 0.0, 0.0, 0.5, 0.0, 1.0, 0.0, 0.0,
          0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    for mn, mx in cases[:10]:
        sc.classify(list(mn) + [0.0], list(mx) + [0.0], wx)
    neg = list(IDENT)
    neg[15] = -1.0
    for mn, mx in cases[:10]:
        sc.classify(list(mn) + [0.0], list(mx) + [0.0], neg)
    # the w lanes of the corners are never read
    sc.classify([-0.5, -0.5, -0.5, 1e30], [0.5, 0.5, 0.5, -7.0], I)
    # NaN and infinities
    nan, inf = 0x7fc00000, 0x7f800000
    sc.classify([nan, -0.5, -0.5, 0.0], [0.5, 0.5, 0.5, 0.0], I)
    sc.classify([-0.5, -0.5, -0.5, 0.0], [inf, 0.5, 0.5, 0.0], I)
    sc.classify([-0.5, -0.5, -0.5, 0.0], [0.5, 0.5, 0.5, 0.0],
                [inf] + IDENT[1:])
    m = list(IDENT)
    m[15] = nan
    sc.classify([-0.5, -0.5, -0.5, 0.0], [0.5, 0.5, 0.5, 0.0], m)
    # the corners' sums: an edge one rounding from the plane, each way
    for dx in (1.0, 1.0 + 2 ** -23, 1.0 - 2 ** -24):
        for base in (-0.25, 0.1, 2 ** -24):
            sc.classify([base, 0.0, 0.0, 0.0], [base + dx, 0.2, 0.3, 0.0], I)
            sc.classify([0.0, base, 0.0, 0.0], [0.2, base + dx, 0.3, 0.0], I)
            sc.classify([0.0, 0.0, base, 0.0], [0.2, 0.3, base + dx, 0.0], I)
    # a sheared matrix, where x and y add into one lane
    sh = list(IDENT)
    sh[4] = 1.0
    sh[8] = 1.0
    for a in (0.25, 0.5, 0.5 + 2 ** -23, 0.75):
        sc.classify([0.0, 0.0, 0.0, 0.0], [a, a, a, 0.0], sh)
        sc.classify([-a, -a, -a, 0.0], [0.0, 0.0, 0.0, 0.0], sh)
    # the sums' order, where a rounding lands on either side of a plane.
    # The minimum's lane: ((1 + 2^24) - 2^24) is 0, 1 + (2^24 - 2^24) is 1,
    # against a w of 0.5.
    t = 2.0 ** 24
    m = [1.0, 0.0, 0.0, 0.0, t, 0.0, 0.0, 0.0,
         -t, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]
    sc.classify([1.0, 1.0, 1.0, 0.0], [1.0, 1.0, 1.0, 0.0], m)
    sc.classify([-1.0, -1.0, -1.0, 0.0], [-1.0, -1.0, -1.0, 0.0], m)
    # the far corner: (2^24 + 1) + 1 is 2^24, 2^24 + (1 + 1) is 2^24 + 2,
    # against a w of 2^24
    m = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0,
         0.0, 0.0, 0.0, 0.0, t, 0.0, 0.0, t]
    sc.classify([0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], m)
    sc.classify([0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 0.0], m)
    # random
    for _ in range(1500):
        m = rand_matrix(rnd)
        mn = [f32(rnd.uniform(-2, 2)) for _ in range(3)]
        ext = [f32(rnd.uniform(0, 2)) for _ in range(3)]
        mx = [f32(mn[j] + ext[j]) for j in range(3)]
        sc.classify(mn + [0.0], mx + [0.0], m)
    # random perspective views of random boxes
    for _ in range(800):
        pos = [rnd.uniform(-50, 50), rnd.uniform(-50, 50), rnd.uniform(0, 5)]
        clip, _, _ = clip_matrix(pos, rnd.uniform(0, 6.28),
                                 rnd.uniform(-0.3, 0.3))
        mn = [f32(rnd.uniform(-60, 60)), f32(rnd.uniform(-60, 60)),
              f32(rnd.uniform(-2, 3))]
        mx = [f32(mn[0] + rnd.uniform(0, 20)), f32(mn[1] + rnd.uniform(0, 20)),
              f32(mn[2] + rnd.uniform(0, 8))]
        sc.classify(mn + [0.0], mx + [0.0], clip)
    sc.tag("IsBoundingBoxVisible")
    for mn, mx in cases:
        sc.classify(list(mn) + [0.0], list(mx) + [0.0], I, op=OP_BBVIS)
    for _ in range(100):
        m = rand_matrix(rnd)
        mn = [f32(rnd.uniform(-2, 2)) for _ in range(3)]
        mx = [f32(mn[j] + rnd.uniform(0, 2)) for j in range(3)]
        sc.classify(mn + [0.0], mx + [0.0], m, op=OP_BBVIS)


def views_basic(sc):
    """Views 0..9 with cameras at the origin looking along +x."""
    clip, wv, fwd = clip_matrix((0.0, 0.0, 0.0), 0.0, 0.0)
    for v in range(NVIEW):
        sc.view(v, v, 1, 1, 400.0, v, (0.0, 0.0, 0.0, 1.0),
                tuple(fwd) + (0.0,), wv, clip)
    return clip, fwd


def draw_section(sc, rnd):
    sc.tag("DrawAScenery")
    sc.op(OP_FALLOC, 65536)
    clip, fwd = views_basic(sc)
    # an identity clip matrix and a camera at the origin looking along +x:
    # an object's box classifies against the unit cube.
    kinds = [
        kind((1, 0, 0)),                                # 0 one LOD
        kind((2, 3, 4), clips=(200, 50, 10)),           # 1 three LODs
        kind((5, 0, 6), clips=(200, 50, 10)),           # 2 a NULL middle
        kind((0, 0, 0)),                                # 3 no model
        kind((7, 8, 0), facades=(0, 1, 0), clips=(100, 5, 0)),  # 4 facade 1
        kind((9, 0, 0), facades=(1, 0, 0)),             # 5 facade 0
        kind((10, 0, 0), radius=-10.0),                 # 6 a negative radius
        kind((11, 0, 0), clips=(-5, 0, 0)),             # 7 a negative clip
        kind((12, 0, 0), radius=50.0),                  # 8 big
        kind((13, 14, 15), clips=(3, 2, 1), facades=(0, 0, 2)),  # 9
    ]
    inside = (0, 0, 0, 0, 0, 0)
    rots = [(16384, 0, 0, 0, 16384, 0, 0, 0, 16384),
            (0, 16384, 0, -16384, 0, 0, 0, 0, 16384),
            (11585, 11585, 0, -11585, 11585, 0, 0, 0, 16384),
            (-32768, 32767, 1, 2, 3, -1, -2, -3, 100)]
    insts = []
    for kd in range(10):
        for dist in (10.0, 3.0):
            insts.append(inst(kd, 0, inside, (dist, 0.5, 0.25),
                              rots[kd % 4]))
    # boxes: across and outside
    insts.append(inst(0, 0, (0, 0, 0, 2, 0, 0), (10.0, 0.0, 0.0)))   # 20
    insts.append(inst(0, 0, (2, 0, 0, 3, 0, 0), (10.0, 0.0, 0.0)))   # 21
    # the flags
    for fl_ in (0x01, 0x02, 0x04, 0x08, 0x10, 0x80, 0x100, 0x200, 0x300,
                0x400, 0x8000, 0xff00, 0x201):
        insts.append(inst(1, fl_, inside, (20.0, 1.0, 2.0), rots[2]))
    n_flags = len(insts)
    # behind, beside, and at distances around each clip
    for pos in ((-4.0, 0.0, 0.0), (-5.0, 0.0, 0.0), (-5.5, 0.0, 0.0),
                (-4.9, 0.1, 0.0), (0.0, 30.0, 0.0), (0.0, 0.0, 0.0),
                (5.0, 0.0, 0.0), (5.5, 0.0, 0.0), (6.0, 0.0, 0.0),
                (1000.0, 0.0, 0.0), (1e6, 0.0, 0.0), (1e30, 0.0, 0.0),
                (-1e30, 0.0, 0.0), (15.0, -3.0, 1.0)):
        insts.append(inst(1, 0, inside, pos))
    n_pos = len(insts)
    for d in (8.0, 13.0, 45.0, 50.0, 55.0, 205.0, 400.0, 405.0, 1001.0,
              2005.0, 4005.0):
        insts.append(inst(1, 0, inside, (d, 0.0, 0.0)))
        insts.append(inst(2, 0, inside, (d, 0.0, 0.0)))
        insts.append(inst(9, 0, inside, (d, 0.0, 0.0)))
    sc.section(0, 5, kinds, insts, [node(inside, [0])])

    cam = (0.0, 0.0, 0.0, 1.0)
    dirn = tuple(fwd) + (0.0,)

    def ci(flags=0, h=400.0, top=NDRAWS, cur=0, pos=cam, d=dirn, c=IDENT,
           facade=ZERO16):
        sc.ci(0, 1, flags, facade, c, pos, d, h, 0, cur, top)

    ci()
    for i in range(len(insts)):
        for cls in (1, 2):
            sc.op(OP_DRAW, 0, i, 0, cls)
    for i in (0, 1, 4, 20, 21):
        for cls in (0, 3, 4, 5, 6):
            sc.op(OP_DRAW, 0, i, 0, cls)
    # the exclusion and the raise against each view flag
    for flags in (0x01, 0x04, 0x08, 0x10, 0x80, 0x100, 0x102, 0x1ff, 0x300,
                  -1):
        ci(flags=flags)
        for i in range(20, n_flags):
            sc.op(OP_DRAW, 0, i, 0, 2)
    # H: small, zero, negative, huge
    for h in (1.0, 0.0, -400.0, 3e9, 1e20, -1e20):
        ci(h=h)
        for i in list(range(n_flags, n_pos)) + [0, 1, 2]:
            sc.op(OP_DRAW, 0, i, 0, 2)
    # the camera elsewhere, looking elsewhere
    for pos, d in (((10.0, 0.5, 0.25, 1.0), (1.0, 0.0, 0.0, 0.0)),
                   ((3.0, 0.5, 0.25, 7.0), (-1.0, 0.0, 0.0, 0.0)),
                   ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)),
                   ((5.0, 5.0, 5.0, 0.0), (0.6, 0.8, 0.0, 0.0)),
                   ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0))):
        ci(pos=pos, d=d)
        for i in range(0, 20):
            sc.op(OP_DRAW, 0, i, 0, 2)
    # a full table, and one slot short
    ci(top=10, cur=10)
    for i in (0, 1, 20 + 7, 8):
        sc.op(OP_DRAW, 0, i, 0, 2)
    ci(top=10, cur=9)
    for i in (0, 1, 20 + 7, 8):
        sc.op(OP_DRAW, 0, i, 0, 2)
    ci(top=10, cur=11)
    sc.op(OP_DRAW, 0, 0, 0, 2)
    # the frame malloc running out: 64 past the end, exactly at it, and
    # one byte short. The block stays 16-aligned, as every frame malloc's
    # is: VU0's stores drop an address's low four bits.
    ci()
    for pos, end in ((0, 64), (0, 65), (0, 128), (96, 160), (96, 161),
                     (208, 96)):
        sc.op(OP_FSET, pos, end, 0, 0, 0)
        for i in (0, 1, 20 + 7, 8):
            sc.op(OP_DRAW, 0, i, 0, 2)
    sc.op(OP_FSET, 0, 2048, 0, 0, 0)
    # random objects around a perspective camera
    kr = [kind((20 + j, 30 + j, 40 + j), clips=(300, 40, 5),
               facades=(j & 1, (j >> 1) & 1, 0), radius=float(j))
          for j in range(8)]
    ir = []
    for _ in range(300):
        p = (f32(rnd.uniform(-100, 100)), f32(rnd.uniform(-100, 100)),
             f32(rnd.uniform(-5, 10)))
        lo = [int(math.floor(p[j])) - rnd.randint(0, 6) for j in range(3)]
        hi = [int(math.ceil(p[j])) + rnd.randint(0, 6) for j in range(3)]
        r = tuple(rnd.randint(-16384, 16384) for _ in range(9))
        ir.append(inst(rnd.randrange(8), rnd.choice((0, 0, 0, 0x100, 0x200,
                                                     0x04, 0x08)),
                       tuple(lo + hi), p, r))
    sc.section(1, 6, kr, ir, [node(inside, [0])])
    for _ in range(12):
        pos = (rnd.uniform(-20, 20), rnd.uniform(-20, 20), rnd.uniform(0, 3))
        c, _, f = clip_matrix(pos, rnd.uniform(0, 6.28), rnd.uniform(-0.2, 0.2))
        sc.op(OP_FSET, 0, 30000, 0, 0, 0)
        sc.ci(0, 1, rnd.choice((16, 24, 20, 17, 0x112)), ZERO16, c,
              [f32(x) for x in pos] + [1.0], f + [0.0],
              rnd.choice((400.0, 200.0, 800.0)), 0, 0, NDRAWS)
        for i in range(len(ir)):
            sc.op(OP_DRAW, 1, i, 0, 1)
    # the size's sums and quotients, where a rounding lands a size on
    # either side of the 2 or of a far clip
    t = 2.0 ** 24
    kq = [kind((50, 0, 0)),
          kind((51, 0, 0), radius=9.62473201751709),
          kind((52, 53, 0), clips=(7, 0, 0), radius=1.1682535409927368)]
    iq = [inst(0, 0, inside, (t, 1.0, -t - 6.0)),       # dot: -6 or -4
          inst(0, 0, inside, (4519.0, 61.0, 151.0)),    # dist
          inst(1, 0, inside, (3987.37646484375, 0.0, 0.0)),  # r * H / f1
          inst(2, 0, inside, (10.336506843566895, 0.0, 0.0))]  # f1 == r
    sc.section(2, 7, kq, iq, [node(inside, [0])])
    for h, d in ((1e20, (1.0, 1.0, 1.0, 0.0)),
                 (1806.773193359375, (1.0, 0.0, 0.0, 0.0)),
                 (583.314453125, (1.0, 0.0, 0.0, 0.0)),
                 (7.0, (1.0, 0.0, 0.0, 0.0)),
                 (1806.7733154296875, (1.0, 0.0, 0.0, 0.0)),
                 (583.3145751953125, (1.0, 0.0, 0.0, 0.0)),
                 (8.0, (1.0, 0.0, 0.0, 0.0))):
        ci(h=h, d=d)
        for i in range(len(iq)):
            sc.op(OP_DRAW, 2, i, 0, 2)
    sc.unsection(0)
    sc.unsection(1)
    sc.unsection(2)
    sc.op(OP_FFREE)


def tree_section(sc, rnd):
    sc.tag("tree culls")
    sc.op(OP_FALLOC, 65536)
    clip, fwd = views_basic(sc)
    ks = [kind((1, 0, 0)), kind((2, 0, 0), facades=(1, 0, 0))]
    # objects along +x, each with a unit box around it
    insts = []
    for j in range(40):
        x = (j % 10) * 0.25 - 1.0
        y = (j // 10) * 0.5 - 1.0
        insts.append(inst(j & 1, 0x200 if j % 7 == 3 else 0,
                          (int(math.floor(x)), int(math.floor(y)), 0,
                           int(math.ceil(x)), int(math.ceil(y)), 0),
                          (5.0 + j, x, y)))
    # 0: the root over everything; its children are nodes and objects
    tree = [
        node((-3, -3, -1, 3, 3, 1), [-1, -2, 0, -3, 1]),            # 0
        node((-1, -1, 0, 1, 1, 0), [2, 3, -4, -8]),                 # 1 inside
        node((-3, -1, 0, 0, 1, 0), [4, 5, 6, -5]),                  # 2 across
        node((2, 2, 2, 3, 3, 3), [7, 8, 9]),                        # 3 outside
        node((0, 0, 0, 0, 0, 0), [10, 11, -6]),                     # 4
        node((-2, -2, -2, -1, -1, -1), [12, 13]),                   # 5 across
        node((0, 0, 0, 1, 1, 1), [14, 15, 16, 17, 18], n=7),        # 6 past 5
        node((0, 0, 0, 1, 1, 1), [19, 20, 21, 22, 23]),             # 7
        node((5, 5, 5, 6, 6, 6), [24]),         # 8 outside, under one inside
    ]
    sc.section(0, 7, ks, insts, tree)
    # a chain: each node one level deeper, the last with code 0
    chain = [node((-1, -1, -1, 1, 1, 1), [-(j + 1), j]) for j in range(30)]
    chain.append(node((-1, -1, -1, 1, 1, 1), [0, 39]))
    sc.section(1, 8, ks, insts, chain)
    # no tree at all
    sc.section(2, 9, ks, insts[:5], [])
    # a node's code one past the table's last node, into the zeroed guard
    sc.section(3, 10, ks, insts[:5], [node((-1, -1, -1, 1, 1, 1), [-2, 1]),
                                      node((0, 0, 0, 0, 0, 0), [2])])
    # a tree whose root is outside
    sc.section(4, 11, ks, insts, [node((5, 5, 5, 6, 6, 6), [0, 1, -1]),
                                  node((0, 0, 0, 0, 0, 0), [2])])

    cam = (0.0, 0.0, 0.0, 1.0)
    dirn = tuple(fwd) + (0.0,)
    for c in (IDENT, clip):
        for k in range(5):
            sc.ci(0, 1, 16, ZERO16, c, cam, dirn, 400.0, 0, 0, NDRAWS)
            sc.op(OP_ISVIS, k, 0)
            sc.op(OP_BRUTE, k, 0)
            # TreeCull and CullNodeRecursive read the table unchecked, and
            # nothing calls them on a section without one
            if k != 2:
                sc.ci(0, 1, 16, ZERO16, c, cam, dirn, 400.0, 0, 0, NDRAWS)
                sc.op(OP_TREE, k, 0)
                for nd, cls in ((0, 1), (0, 2), (1, 1), (2, 1), (2, 0),
                                (0, 5)):
                    if nd < (len(tree) if k == 0 else 1):
                        sc.ci(0, 1, 16, ZERO16, c, cam, dirn, 400.0, 0, 0,
                              NDRAWS)
                        sc.op(OP_RECURSE, k, nd, 0, cls)
    # the same with the table nearly full
    sc.ci(0, 1, 16, ZERO16, IDENT, cam, dirn, 400.0, 0, 3, 5)
    sc.op(OP_TREE, 0, 0)
    for k in range(5):
        sc.unsection(k)
    sc.op(OP_FFREE)


def sections_section(sc, rnd):
    sc.tag("WhatSectionsShouldWeDraw, CullView, BatchCullViews, DoCulling")
    sc.op(OP_FALLOC, 65536)
    clip, fwd = views_basic(sc)
    ks = [kind((1, 0, 0)), kind((2, 3, 0), clips=(100, 2, 0))]
    insts = [inst(j & 1, 0x200 if j == 2 else 0, (0, 0, 0, 0, 0, 0),
                  (5.0 + j, 0.0, 0.0)) for j in range(4)]
    tree = [node((0, 0, 0, 0, 0, 0), [0, 1, 2, 3])]
    secs = [5, 12, 90, 91, 95, 99, 100, 150, 299, 44, 0]
    for k, s in enumerate(secs):
        sc.section(k, s, ks, insts, tree if s != 44 else [],
                   head=(s >= 90))
    square = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
    far = [(100.0, 100.0), (110.0, 100.0), (110.0, 110.0), (100.0, 110.0)]
    cam = (0.0, 0.0, 0.0, 1.0)
    dirn = tuple(fwd) + (0.0,)

    def setci(i, view):
        sc.ci(i, view, 16, ZERO16, IDENT, cam, dirn, 400.0, 0, 0, NDRAWS)

    # no zones: every section below 100 on the list
    for view in (1, 2):
        setci(0, view)
        sc.op(OP_CURZONE, 7)
        for mx in (0, 1, 3, 20, 300):
            sc.op(OP_WHAT, 0, mx)
    # zones, the camera in the second
    sc.zone(3, [150, 12], far)
    sc.zone(8, [5, -1, 12, 150, 7, 299, 1000 - 1000, 44, 5], square)
    sc.zone(9, [100], square)
    for view in (1, 2, 1):
        setci(0, view)
        for mx in (0, 1, 3, 5, 6, 12, 300):
            sc.op(OP_WHAT, 0, mx)
    sc.op(OP_CURZONE, 8)
    setci(0, 1)
    sc.op(OP_WHAT, 0, 300)
    # the camera outside every zone
    sc.view(3, 3, 1, 1, 400.0, 3, (50.0, 50.0, 0.0, 1.0), dirn, IDENT, IDENT)
    setci(0, 3)
    sc.op(OP_WHAT, 0, 300)
    sc.view(1, 1, 1, 1, 400.0, 1, (50.0, 50.0, 0.0, 1.0), dirn, IDENT, IDENT)
    setci(0, 1)
    sc.op(OP_WHAT, 0, 300)
    sc.view(1, 1, 1, 1, 400.0, 1, (105.0, 105.0, 0.0, 1.0), dirn, IDENT,
            IDENT)
    sc.op(OP_WHAT, 0, 300)
    views_basic(sc)
    # CullView
    for view in (1, 3):
        setci(0, view)
        sc.op(OP_CULLVIEW, 0)
    # BatchCullViews over three cull infos, two sharing a camera
    sc.view(2, 2, 1, 1, 400.0, 2, (105.0, 105.0, 0.0, 1.0), dirn, IDENT,
            IDENT)
    for n in (0, 1, 3):
        for i, view in enumerate((1, 2, 1)):
            sc.ci(i, view, 16, ZERO16, IDENT, cam, dirn, 400.0, 0, 10 * i,
                  NDRAWS)
        sc.op(OP_NUMCI, n)
        sc.op(OP_BATCH)
    # DoCulling and StuffScenery
    for n in (0, 1, 3):
        for i, view in enumerate((1, 2, 3)):
            sc.ci(i, view, 16, ZERO16, IDENT, cam, dirn, 400.0, 0, 0, 0)
        sc.op(OP_NUMCI, n)
        sc.op(OP_FSET, 0, 30000, 0, 0, 0)
        sc.op(OP_DOCULL)
        for v in (0, 1, 2, 3):
            sc.op(OP_STUFF, v)
    # two cull infos of one view: StuffScenery draws the first
    for i in range(2):
        sc.ci(i, 1, 16, ZERO16, IDENT, cam, dirn, 400.0, 0, 0, 0)
    sc.op(OP_NUMCI, 2)
    sc.op(OP_DOCULL)
    sc.op(OP_STUFF, 1)
    sc.zclear()
    for k in range(len(secs)):
        sc.unsection(k)
    sc.op(OP_NUMCI, 0)
    sc.op(OP_FFREE)


def setup_section(sc, rnd):
    sc.tag("SetupSceneryCullInfo")
    for v in range(NVIEW):
        yaw = rnd.uniform(-3.2, 3.2)
        pos = (rnd.uniform(-9, 9), rnd.uniform(-9, 9), rnd.uniform(0, 3))
        clip, wv, fwd = clip_matrix(pos, yaw, rnd.uniform(-0.4, 0.4))
        sc.view(v, [0, 1, 2, 3, 4, 5, 9, 10, -1, 0x80000004][v], 1, 1,
                400.0, v, list(pos) + [1.0], fwd + [0.0], wv, clip)
    for d in (0, 1, 2, -1):
        sc.op(OP_DIR, d)
        for mode in (0, 1, 2, 3, 4, 5, -1):
            sc.op(OP_MODE, mode)
            for v in range(NVIEW):
                sc.op(OP_SETUP, v, v)
    sc.op(OP_DIR, 0)
    sc.op(OP_MODE, 0)
    # the facade turn from WorldViewMatrix's first row, at the axes and
    # in between
    for x, y in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0),
                 (0.0, 0.0), (-0.0, -0.0), (0.6, 0.8), (-0.6, 0.8),
                 (1e-30, -1.0), (3.0, 4.0)):
        wv = list(IDENT)
        wv[0], wv[2] = y, x
        sc.view(1, 1, 1, 1, 400.0, 1, (0.0, 0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0, 0.0), wv, IDENT)
        sc.op(OP_SETUP, 1, 0)
    sc.tag("eDisplayFrame's views")
    for v in range(NVIEW):
        sc.view(v, v, (v * 7) % 3 != 1, (v * 5) % 4 != 2, 400.0 + v, v,
                (float(v), 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 0.0), IDENT,
                IDENT)
    for env in (1, 0):
        sc.op(OP_ENV, env)
        for ig in (0, 1, 2):
            sc.op(OP_SETUPVIEWS, ig)
    for v in range(NVIEW):
        sc.view(v, v, 1, 1, 400.0, v, (0.0, 0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0, 0.0), IDENT, IDENT)
    sc.op(OP_ENV, 1)
    sc.op(OP_SETUPVIEWS, 1)
    sc.op(OP_ENV, 1)
    sc.op(OP_NUMCI, 0)


def track_section(sc, tr, rnd, quick=False):
    sc.tag("TRACKB12")
    sc.op(OP_FALLOC, 2621440)
    model_no = [1]
    secs = []
    allpos = []
    for k, (off, data) in enumerate(tr.containers):
        mis = off % 16
        kinds, insts, tree, sec = [], [], [], None
        for o, cid, csize in sck.groups(data):
            body = data[o + 8:o + 8 + csize]
            if cid == sck.HEADER:
                pad = sck.align16(mis + o + 8) - (mis + o + 8)
                sec = s32(u32at(body, pad + 8))
            elif cid == sck.INFO:
                for j in range(csize // 40):
                    r = body[40 * j:40 * j + 40]
                    hs = struct.unpack_from("<3I", r, 0)
                    clips = struct.unpack_from("<3h", r, 12)
                    dummy = struct.unpack_from("<h", r, 18)[0]
                    fac = struct.unpack_from("<4B", r, 32)
                    rad = u32at(r, 36)
                    mods = []
                    for h in hs:
                        if h:
                            mods.append(model_no[0])
                            model_no[0] += 1
                        else:
                            mods.append(0)
                    kinds.append((hs, clips, tuple(mods), fac[:3], rad,
                                  (dummy & 0xFFFF, fac[3])))
            elif cid == sck.INSTANCE:
                pad = sck.align16(mis + o + 8) - (mis + o + 8)
                n = (csize - pad) // 48
                for j in range(n):
                    r = body[pad + 48 * j:pad + 48 * j + 48]
                    insts.append(r)
                    allpos.append(struct.unpack_from("<3f", r, 16))
            elif cid == sck.TREE:
                for j in range(csize // 24):
                    tree.append(body[24 * j:24 * j + 24])
        assert model_no[0] < NMODEL
        sc.section(k, sec, kinds, insts, tree, head=(sec >= 90))
        secs.append(sec)
    zones = []
    zdata = tr.zones[1]
    for i in range(u32at(zdata, 4) // 288):
        r = zdata[8 + 288 * i:8 + 288 * (i + 1)]
        num = s32(u32at(r, 8))
        ns = s32(u32at(r, 24))
        zsecs = list(struct.unpack_from("<%dh" % ns, r, 28))
        npts = s32(u32at(r, 156))
        pts = [struct.unpack_from("<ff", r, 160 + 8 * j) for j in range(npts)]
        center = struct.unpack_from("<ff", r, 12)
        sc.zone(num, zsecs, pts)
        zones.append((num, center, pts))

    def ground(x, y):
        best, bz = None, 0.0
        for p in allpos[::7]:
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if best is None or d < best:
                best, bz = d, p[2]
        return bz

    spots = [(c[0], c[1]) for _, c, _ in zones]
    xs = [p[0] for p in allpos]
    ys = [p[1] for p in allpos]
    for _ in range(12):
        spots.append((rnd.uniform(min(xs), max(xs)),
                      rnd.uniform(min(ys), max(ys))))
    if quick:
        spots = spots[:6]
    for j, (x, y) in enumerate(spots):
        z = ground(x, y) + 2.0
        yaw = rnd.uniform(0, 6.28)
        views = (1, 2) if j % 3 == 0 else (1,)
        for v in views:
            vy = yaw + (v - 1) * 1.7
            clip, wv, fwd = clip_matrix((x, y, z), vy, rnd.uniform(-0.1, 0.1))
            sc.view(v, v, 1, 1, rnd.choice((320.0, 400.0, 560.0)), v,
                    [f32(x), f32(y), f32(z), 1.0], fwd + [0.0], wv, clip)
        sc.op(OP_DIR, j % 2)
        sc.op(OP_MODE, 3 if j % 4 == 1 else 0)
        for i, v in enumerate(views):
            sc.op(OP_SETUP, v, i)
        sc.op(OP_NUMCI, len(views))
        sc.op(OP_FSET, 0, 1310720, 0, 0, 0)
        sc.op(OP_DOCULL)
        for v in views:
            sc.op(OP_STUFF, v)
        if j % 5 == 2:
            sc.op(OP_BATCH)
    sc.op(OP_DIR, 0)
    sc.op(OP_MODE, 0)
    sc.op(OP_NUMCI, 0)
    sc.zclear()
    for k in range(len(tr.containers)):
        sc.unsection(k)
    sc.op(OP_FFREE)


def script(quick=False):
    rnd = random.Random(0x5ce11)
    sc = Script()
    frame_section(sc)
    classify_section(sc, rnd)
    draw_section(sc, rnd)
    tree_section(sc, rnd)
    sections_section(sc, rnd)
    setup_section(sc, rnd)
    track_section(sc, sck.Track(), rnd, quick)
    return sc


# ---------------------------------------------------------------- the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True)
        e.stub_bware()
        e.call("eMathInit__Fv")
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.ident = e.addr_of("eMathIdentityMatrix")
        e.call(self.fn["sinit"])
        self.mbase = e.alloc(NMODEL * MS, 16)
        self.lights = e.alloc(NLIGHT * 16, 16)
        stack = e.alloc(0x4000 + 2096, 16)
        self.grand = stack + 0x4000
        self.cams = [e.alloc(448, 16) for _ in range(NVIEW)]
        self.rts = [e.alloc(16, 16) for _ in range(NVIEW)]
        self.wvs = [e.alloc(64, 16) for _ in range(NVIEW)]
        self.clips = [e.alloc(64, 16) for _ in range(NVIEW)]
        self.sects = [None] * NSECT
        self.zones = []
        self.bufs = []
        self.tmp = e.alloc(256, 16)
        emit = self.emit

        def render(em):
            m, mat, light, flags = (em.reg[r] & M32 for r in (4, 5, 6, 7))
            emit("  render %s matrix %s light %s flags %d"
                 % (self.name(m), self.name(mat), self.name(light), flags))
            return 0

        def malloc(em):
            size, name, flags, pool = (em.reg[r] & M32 for r in (4, 5, 6, 7))
            s = bytes(em.read(name, 64)).split(b"\0")[0].decode()
            # a gap after each, so that no buffer's range reaches the next
            p = em.alloc(s32(size) + 128, 16)
            emit("  bMalloc %d %s %d %d -> B%d"
                 % (s32(size), s, s32(flags), s32(pool), len(self.bufs)))
            self.bufs.append((p, s32(size)))
            return p

        def free(em):
            emit("  bFree %s" % self.name(em.reg[4] & M32))
            return 0

        def setup_done(em):
            em.reg[me.RA] = em.RETURN

        e.stub("Render__6eModelP8bMatrix4P13eLightContextUi", render)
        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bFree__FPv", free)
        e.stub(SETUP_TO, setup_done)

    def w32(self, a, v):
        self.e.write(a, struct.pack("<I", v & M32))

    def u32(self, a):
        return self.e.u32(a)

    def emit(self, line):
        self.out.append(line)

    def call(self, name, *args):
        return s32(self.e.call(self.fn[name], *[s32(a) for a in args]))

    def ci(self, i):
        return self.grand + 208 * i

    # ---- naming

    def name(self, p):
        p &= M32
        if p == 0:
            return "null"
        if p == self.ident:
            return "I"
        if self.mbase <= p < self.mbase + NMODEL * MS:
            n, r = divmod(p - self.mbase, MS)
            return "#%d" % n if r == 0 else "#%d+%d" % (n, r)
        if DRAWS <= p <= DRAWS + 8 * NDRAWS:
            return "D[%d]" % ((p - DRAWS) // 8)
        for k, (b, size) in enumerate(self.bufs[:2]):
            if b <= p <= b + size + 64:
                return "B%d+%d" % (k, p - b)
        if self.lights <= p < self.lights + NLIGHT * 16:
            return "L%d" % ((p - self.lights) // 16)
        return "?"

    # ---- dumps

    def dump_matrix(self, label, a):
        self.emit("   %s" % label + "".join(" %08x" % fx(self.u32(a + 4 * j))
                                           for j in range(16)))

    def dump_draw(self, d):
        p = self.u32(d)
        m = self.u32(d + 4)
        self.emit("  %s %s/%d %s" % (self.name(d), self.name(p & ~3), p & 3,
                                     self.name(m)))
        if m != 0 and m != self.ident:
            self.dump_matrix("m", m)

    def dump_frame(self):
        u = self.u32
        self.emit("  frame pos %s end %s failed %d amount %d max %d alloc %d"
                  % (self.name(u(FPOS)), self.name(u(FEND)), s32(u(FFAILED)),
                     u(FAMOUNT), u(FMAX), s32(u(FALLOCN))))

    def dump_zones(self):
        u = self.u32
        parts = ["  zones:"]
        n = u(VZL)
        while n != VZL:
            parts.append(" %d" % s32(u(n + 8)))
            n = u(n)
        parts.append(" current %d" % s32(u(CURZONE)))
        self.emit("".join(parts))

    def dump_views_visible(self):
        parts = ["  views visible:"]
        for k, s in enumerate(self.sects):
            if s is not None and self.u32(s["h"] + 52):
                parts.append(" %d:%x" % (k, self.u32(s["h"] + 52)))
        self.emit("".join(parts))

    def view_index(self, v):
        if VIEWS <= v < VIEWS + 128 * NVIEW and (v - VIEWS) % 128 == 0:
            return (v - VIEWS) // 128
        return -1

    def dump_ci_head(self, i):
        c, u = self.ci(i), self.u32
        self.emit("  ci %d view %d flags %x first %s current %s top %s"
                  % (i, self.view_index(u(c + 128)), u(c + 132),
                     self.name(u(c + 136)), self.name(u(c + 140)),
                     self.name(u(c + 144))))

    def dump_ci_full(self, i):
        c, u = self.ci(i), self.u32
        self.dump_ci_head(i)
        self.dump_matrix("facade", c)
        self.dump_matrix("clip", c + 64)
        self.emit("   pos %s dir %s h %08x"
                  % (" ".join("%08x" % fx(u(c + 160 + 4 * j))
                              for j in range(4)),
                     " ".join("%08x" % fx(u(c + 176 + 4 * j))
                              for j in range(4)),
                     fx(u(c + 192))))

    def dump_new_draws(self, i, frm):
        cur = self.u32(self.ci(i) + 140)
        d = frm
        while d < cur:
            self.dump_draw(d)
            d += 8

    def dump_all(self):
        g, u = self.grand, self.u32
        n = s32(u(g + 2080))
        self.emit("  grand num %d first %s current %s top %s"
                  % (n, self.name(u(g + 2084)), self.name(u(g + 2088)),
                     self.name(u(g + 2092))))
        for i in range(min(max(n, 0), 10)):
            self.dump_ci_head(i)
            self.dump_new_draws(i, u(self.ci(i) + 136))
        self.dump_frame()
        self.dump_zones()
        self.dump_views_visible()

    # ---- the ops

    def section(self, w, i):
        e = self.e
        k, sec, head, nk, ni, nt = w[i:i + 6]
        i += 6
        h = e.alloc(64, 16)
        kinds = e.alloc(40 * (nk + 1), 16)
        insts = e.alloc(48 * (ni + 1), 16)
        tree = e.alloc(24 * (nt + GUARD), 16)
        for j in range(nk):
            r = w[i:i + 10]
            i += 10
            rec = struct.pack("<3I", *r[0:3])
            rec += struct.pack("<II", r[3], r[4])
            rec += struct.pack("<3I", *[0 if m == 0 else self.mbase + MS * m
                                        for m in r[5:8]])
            rec += struct.pack("<II", r[8], r[9])
            e.write(kinds + 40 * j, rec)
        for j in range(ni):
            e.write(insts + 48 * j, struct.pack("<12I", *w[i:i + 12]))
            i += 12
        for j in range(nt):
            e.write(tree + 24 * j, struct.pack("<6I", *w[i:i + 6]))
            i += 6
        hdr = [0] * 14
        hdr[2] = sec
        hdr[5], hdr[6] = kinds, nk
        hdr[7], hdr[8] = insts, ni
        hdr[9], hdr[10] = (tree if nt else 0), nt
        e.write(h, struct.pack("<14I", *[x & M32 for x in hdr]))
        self.w32(TABLE + 4 * sec, h)
        if head:
            nxt = self.u32(SSHL)
            self.w32(h, nxt)
            self.w32(h + 4, SSHL)
            self.w32(nxt + 4, h)
            self.w32(SSHL, h)
        else:
            prv = self.u32(SSHL + 4)
            self.w32(h + 4, prv)
            self.w32(h, SSHL)
            self.w32(prv, h)
            self.w32(SSHL + 4, h)
        self.sects[k] = {"h": h, "sec": sec, "tree": tree}
        return i

    def unsection(self, k):
        s = self.sects[k]
        h = s["h"]
        nxt, prv = self.u32(h), self.u32(h + 4)
        self.w32(prv, nxt)
        self.w32(nxt + 4, prv)
        self.w32(TABLE + 4 * s["sec"], 0)

    def zone(self, w, i):
        e = self.e
        z = e.alloc(288, 16)
        num, ns = w[i], w[i + 1]
        i += 2
        e.write(z + 8, struct.pack("<I", num))
        e.write(z + 24, struct.pack("<I", ns))
        e.write(z + 28, struct.pack("<32I", *w[i:i + 32]))
        i += 32
        e.write(z + 156, struct.pack("<I", w[i]))
        i += 1
        e.write(z + 160, struct.pack("<32I", *w[i:i + 32]))
        i += 32
        prv = self.u32(VZL + 4)
        self.w32(z + 4, prv)
        self.w32(z, VZL)
        self.w32(prv, z)
        self.w32(VZL + 4, z)
        return i

    def view(self, w, i):
        e = self.e
        v, vid, active, rt = w[i:i + 4]
        h, light = w[i + 4], w[i + 5]
        i += 6
        base = VIEWS + 128 * v
        self.w32(base, vid)
        e.write(base + 4, bytes([active & 0xFF]))
        self.w32(self.rts[v] + 8, rt)
        self.w32(base + 48, self.rts[v])
        self.w32(base + 8, h)
        self.w32(base + 108, self.lights + 16 * light)
        e.write(self.cams[v] + 64, struct.pack("<4I", *w[i:i + 4]))
        e.write(self.cams[v] + 80, struct.pack("<4I", *w[i + 4:i + 8]))
        i += 8
        self.w32(base + 56, self.cams[v])
        e.write(self.wvs[v], struct.pack("<16I", *w[i:i + 16]))
        e.write(self.clips[v], struct.pack("<16I", *w[i + 16:i + 32]))
        i += 32
        self.w32(base + 68, self.wvs[v])
        self.w32(base + 80, self.clips[v])
        return i

    def set_ci(self, w, i):
        e = self.e
        c = self.ci(w[i])
        self.w32(c + 128, VIEWS + 128 * w[i + 1])
        self.w32(c + 132, w[i + 2])
        i += 3
        e.write(c, struct.pack("<16I", *w[i:i + 16]))
        e.write(c + 64, struct.pack("<16I", *w[i + 16:i + 32]))
        i += 32
        e.write(c + 160, struct.pack("<4I", *w[i:i + 4]))
        e.write(c + 176, struct.pack("<4I", *w[i + 4:i + 8]))
        self.w32(c + 192, w[i + 8])
        i += 9
        for off in (136, 140, 144):
            self.w32(c + off, DRAWS + 8 * w[i])
            i += 1
        return i

    def setup_views(self, in_game):
        e = self.e
        self.w32(INGAME, in_game)
        e.reg[23] = self.grand                      # s7
        e.reg[me.SP] = self.grand - 16
        e.reg[3] = 9                                # v1, the delay loop's
        e.reg[me.RA] = e.RETURN
        e.run(SETUP_FROM)
        e.reg[me.SP] = e.RAM - 0x10000

    def run(self):
        e, w, emit = self.e, self.sc.words, self.emit
        i = 0
        while i < len(w):
            code = w[i]
            i += 1
            if code == OP_TAG:
                emit("[%d]" % w[i])
                i += 1
            elif code == OP_SECTION:
                i = self.section(w, i)
            elif code == OP_UNSECTION:
                self.unsection(w[i])
                i += 1
            elif code == OP_ZONE:
                i = self.zone(w, i)
            elif code == OP_ZCLEAR:
                self.w32(VZL, VZL)
                self.w32(VZL + 4, VZL)
            elif code == OP_VIEW:
                i = self.view(w, i)
            elif code == OP_CI:
                i = self.set_ci(w, i)
            elif code == OP_NUMCI:
                self.w32(self.grand + 2080, w[i])
                i += 1
            elif code in (OP_CLASSIFY, OP_BBVIS):
                t = self.tmp
                e.write(t, struct.pack("<8I", *w[i:i + 8]))
                e.write(t + 32, struct.pack("<16I", *w[i + 8:i + 24]))
                i += 24
                if code == OP_CLASSIFY:
                    emit("classify -> %d"
                         % self.call("classify", t, t + 16, t + 32))
                else:
                    emit("bbvis -> %d" % self.call("bbvis", t, t + 16, t + 32))
            elif code == OP_ISVIS:
                k, c = w[i:i + 2]
                i += 2
                emit("isvis %d ci %d -> %d"
                     % (k, c, self.call("isvis", self.sects[k]["h"],
                                        self.ci(c))))
            elif code == OP_DRAW:
                k, idx, c, cls = w[i:i + 4]
                i += 4
                frm = self.u32(self.ci(c) + 140)
                emit("draw %d %d ci %d cls %d" % (k, s32(idx), c, s32(cls)))
                self.call("draw", self.sects[k]["h"], idx, self.ci(c), cls)
                self.dump_ci_head(c)
                self.dump_new_draws(c, frm)
                self.dump_frame()
            elif code in (OP_BRUTE, OP_TREE):
                k, c = w[i:i + 2]
                i += 2
                frm = self.u32(self.ci(c) + 140)
                emit("%s %d ci %d" % ("brute" if code == OP_BRUTE else "tree",
                                      k, c))
                self.call("brute" if code == OP_BRUTE else "tree",
                          self.sects[k]["h"], self.ci(c))
                self.dump_ci_head(c)
                self.dump_new_draws(c, frm)
                self.dump_frame()
            elif code == OP_RECURSE:
                k, nd, c, cls = w[i:i + 4]
                i += 4
                frm = self.u32(self.ci(c) + 140)
                emit("recurse %d node %d ci %d cls %d" % (k, nd, c, cls))
                self.call("recurse", self.sects[k]["h"],
                          self.sects[k]["tree"] + 24 * nd, self.ci(c), cls)
                self.dump_ci_head(c)
                self.dump_new_draws(c, frm)
                self.dump_frame()
            elif code == OP_WHAT:
                c, mx = w[i:i + 2]
                i += 2
                buf = e.alloc(600, 16)
                e.write(buf, b"\xa5" * 600)
                n = self.call("what", self.grand, buf, mx, self.ci(c))
                vals = [s16(e.u16(buf + 2 * j)) for j in range(min(n, 300))]
                emit("what ci %d max %d -> %d:%s"
                     % (c, mx, n, "".join(" %d" % v for v in vals)))
                self.dump_zones()
            elif code == OP_CULLVIEW:
                c = w[i]
                i += 1
                frm = self.u32(self.ci(c) + 140)
                emit("cull view ci %d" % c)
                self.call("cullview", self.grand, self.ci(c))
                self.dump_ci_head(c)
                self.dump_new_draws(c, frm)
                self.dump_frame()
                self.dump_zones()
            elif code == OP_BATCH:
                emit("batch")
                self.call("batch", self.grand)
                self.dump_all()
            elif code == OP_DOCULL:
                emit("do culling")
                self.call("docull", self.grand)
                self.dump_all()
            elif code == OP_STUFF:
                v = w[i]
                i += 1
                emit("stuff view %d" % v)
                self.call("stuff", self.grand, VIEWS + 128 * v)
            elif code == OP_SETUP:
                v, c = w[i:i + 2]
                i += 2
                emit("setup view %d ci %d" % (v, c))
                self.call("setup", VIEWS + 128 * v, self.ci(c))
                self.dump_ci_full(c)
            elif code == OP_SETUPVIEWS:
                ig = w[i]
                i += 1
                emit("setup views %d" % ig)
                self.setup_views(ig)
                n = s32(self.u32(self.grand + 2080))
                emit("  num %d" % n)
                for j in range(n):
                    self.dump_ci_full(j)
            elif code == OP_MODE:
                self.w32(VIEWMODE, w[i])
                i += 1
            elif code == OP_DIR:
                self.w32(DIRECTION, w[i])
                i += 1
            elif code == OP_ENV:
                self.w32(ENVMAP, w[i])
                i += 1
            elif code == OP_FALLOC:
                size = w[i]
                i += 1
                emit("allocate frame %d" % size)
                self.bufs = []
                self.call("falloc", size)
                emit("  size %d buffers %s %s"
                     % (self.u32(FSIZE), self.name(self.u32(FBUF)),
                        self.name(self.u32(FBUF + 4))))
                self.dump_frame()
            elif code == OP_FSWAP:
                emit("swap frame")
                self.call("fswap")
                emit("  buffers %s %s used %d %d"
                     % (self.name(self.u32(FBUF)),
                        self.name(self.u32(FBUF + 4)),
                        s32(self.u32(FUSED)), s32(self.u32(FUSED + 4))))
                self.dump_frame()
            elif code == OP_FFREE:
                emit("free frame")
                self.call("ffree")
                emit("  size %d buffers %s %s"
                     % (self.u32(FSIZE), self.name(self.u32(FBUF)),
                        self.name(self.u32(FBUF + 4))))
                self.dump_frame()
                self.bufs = []
            elif code == OP_FSIZE:
                t = self.tmp
                self.w32(t, 0x5a5a5a5a)
                r = self.call("fsize", t)
                emit("frame size -> %d used %d" % (r, s32(self.u32(t))))
            elif code == OP_FSET:
                pos, end, failed, amount, mx = w[i:i + 5]
                i += 5
                b0 = self.u32(FBUF)
                self.w32(FPOS, b0 + pos)
                self.w32(FEND, b0 + end)
                self.w32(FFAILED, failed)
                self.w32(FAMOUNT, amount)
                self.w32(FMAX, mx)
            elif code == OP_CURZONE:
                self.w32(CURZONE, w[i])
                i += 1
            elif code == OP_DUMPG:
                emit("dump")
                self.dump_all()
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
    return hostbuild.build(tmp, SOURCES, name="scenerycull_test")


# -------------------------------------------------------------- mutations


def _m(name, old, new, rel=SC):
    return (name, rel, old, new)


MUTATIONS = [
    # ClassifyAABB
    _m("clip-x-le", "    if (lim < v->x)", "    if (lim <= v->x)"),
    _m("clip-negx-le", "    if (v->x < -lim)", "    if (v->x <= -lim)"),
    _m("clip-y-le", "    if (lim < v->y)", "    if (lim <= v->y)"),
    _m("clip-negz-le", "    if (v->z < -lim)", "    if (v->z <= -lim)"),
    _m("clip-y-bit-merge", "        f |= 0x04;", "        f |= 0x01;"),
    _m("clip-negz-bit-merge", "        f |= 0x20;", "        f |= 0x10;"),
    _m("clip-no-fabs", "    float lim = fabsf(v->w);", "    float lim = v->w;"),
    _m("c0-order", "    c0.x = ((clip->v0.x * min->x + clip->v1.x * min->y)\n"
       "            + clip->v2.x * min->z) + clip->v3.x;",
       "    c0.x = (clip->v0.x * min->x + (clip->v1.x * min->y\n"
       "            + clip->v2.x * min->z)) + clip->v3.x;"),
    _m("c0-w-row", "            + clip->v2.w * min->z) + clip->v3.w;",
       "            + clip->v2.w * min->z) + clip->v3.z;"),
    _m("dz-from-y", "    float dz = max->z - min->z;",
       "    float dz = max->z - min->y;"),
    _m("ey-row", "    vscale(&ey, &clip->v1, dy);",
       "    vscale(&ey, &clip->v2, dy);"),
    _m("c2-order", "    vadd(&c2, &c0, &ex);\n    vadd(&c2, &c2, &ey);",
       "    vadd(&c2, &ex, &ey);\n    vadd(&c2, &c0, &c2);"),
    _m("c3-ex", "    vadd(&c3, &c0, &ey);", "    vadd(&c3, &c0, &ex);"),
    _m("lo-shift", "    lo = (clipw(&c0) << 18)", "    lo = (clipw(&c0) << 17)"),
    _m("hi-drop-c3",
       "(clipw(&c2) << 6)\n         | clipw(&c3);\n\n    if",
       "(clipw(&c2) << 6)\n         | 0;\n\n    if"),
    _m("top-no-ez", "    vadd(&c1, &c1, &ez);", "    vadd(&c1, &c1, &ey);"),
    _m("two-lo-only", "    if (lo == 0 && hi == 0)", "    if (lo == 0)"),
    _m("and-drop-hi18",
       "          & hi & (hi >> 6) & (hi >> 12) & (hi >> 18) & 0x3f;",
       "          & hi & (hi >> 6) & (hi >> 12) & 0x3f;"),
    _m("and-mask", "(hi >> 18) & 0x3f;", "(hi >> 18) & 0x1f;"),
    _m("bbvis-ne", "                                 clip) != 0;",
       "                                 clip) == 2;"),
    _m("box-minz-max", "    mn.z = (float)b->BBoxMin[2];",
       "    mn.z = (float)b->BBoxMax[2];"),
    _m("box-maxx-min", "    mx.x = (float)b->BBoxMax[0];",
       "    mx.x = (float)b->BBoxMin[0];"),
    # a section
    _m("isvis-no-tree-1",
       "    if (h->SceneryTreeNodeTable == NULL)\n        return 0;",
       "    if (h->SceneryTreeNodeTable == NULL)\n        return 1;"),
    _m("isvis-eq2",
       "    return classify_box(&h->SceneryTreeNodeTable[0].BBox, ci) != 0;",
       "    return classify_box(&h->SceneryTreeNodeTable[0].BBox, ci) == 2;"),
    _m("add-le", "    if ((uintptr_t)d < (uintptr_t)ci->pTopDrawInfo) {",
       "    if ((uintptr_t)d <= (uintptr_t)ci->pTopDrawInfo) {"),
    _m("add-no-class", "((uintptr_t)m + (uint32_t)cls);",
       "((uintptr_t)m + 0u);"),
    _m("draw-classify-not2",
       "    if (cls == 1) {\n        cls = classify_box(&s->BBox, ci);",
       "    if (cls != 2) {\n        cls = classify_box(&s->BBox, ci);"),
    _m("draw-no-out-return", "        if (cls == 0)\n            return;\n    }",
       "    }"),
    _m("excl-mask",
       "    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & 0xff)",
       "    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & 0x7f)"),
    _m("excl-mask-wide",
       "    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & 0xff)",
       "    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & 0x1ff)"),
    _m("radius-plus2", "    r = info->Radius + 4.0f;",
       "    r = info->Radius + 2.0f;"),
    _m("dot-order", "    dot = (dx * ci->Direction.x + dy * ci->Direction.y)\n"
       "          + dz * ci->Direction.z;",
       "    dot = dx * ci->Direction.x + (dy * ci->Direction.y\n"
       "          + dz * ci->Direction.z);"),
    _m("dot-dy", "          + dz * ci->Direction.z;",
       "          + dy * ci->Direction.z;"),
    _m("behind-le", "    if (dot < -r) {", "    if (dot <= -r) {"),
    _m("dist-order", "sqrtf((dx * dx + dy * dy) + dz * dz);",
       "sqrtf(dx * dx + (dy * dy + dz * dz));"),
    _m("f1-plus", "        float f1 = dist - r;", "        float f1 = dist + r;"),
    _m("near-le", "        if (r < f1)", "        if (r <= f1)"),
    _m("near-order", "            f0 = r * f0 / f1;",
       "            f0 = r * (f0 / f1);"),
    _m("size-round", "        size = ee_trunc_w(f0);",
       "        size = ee_trunc_w(f0 + 0.5f);"),
    _m("size-lt1", "    if (size < 2)\n        return;",
       "    if (size < 1)\n        return;"),
    _m("size-le2", "    if (size < 2)\n        return;",
       "    if (size <= 2)\n        return;"),
    _m("lod-le", "        if (size < info->FarClipSize[k])",
       "        if (size <= info->FarClipSize[k])"),
    _m("lod-null-break",
       "        if (info->pModel[k] == NULL)\n            continue;",
       "        if (info->pModel[k] == NULL)\n            break;"),
    _m("lod-two", "    for (k = 0; k < 3; k++) {", "    for (k = 0; k < 2; k++) {"),
    _m("lod-index", "        lod = k;", "        lod = 0;"),
    _m("inplace-bit", "    if (s->ExcludeFlags & SCENERY_DRAW_IN_PLACE) {",
       "    if (s->ExcludeFlags & 0x0400) {"),
    _m("inplace-class", "        add_draw_info(ci, model, cls, NULL);",
       "        add_draw_info(ci, model, 2, NULL);"),
    _m("facade-z", "        pos.z = s->Position[2];",
       "        pos.z = s->Position[1];"),
    _m("facade-eye",
       "        scenery_create_facade_matrix(m, &pos, &ci->Position);",
       "        scenery_create_facade_matrix(m, &pos, &pos);"),
    _m("rot-scale", "        const float q = 1.0f / 16384.0f;",
       "        const float q = 1.0f / 16383.0f;"),
    _m("rot-4-5", "        m->v1.y = (float)s->Rotation[4] * q;",
       "        m->v1.y = (float)s->Rotation[5] * q;"),
    _m("rot-6", "        m->v2.x = (float)s->Rotation[6] * q;",
       "        m->v2.x = (float)s->Rotation[2] * q;"),
    _m("rot-w", "        m->v2.w = 0.0f;", "        m->v2.w = 1.0f;"),
    _m("pos-w", "    m->v3.w = 1.0f;", "    m->v3.w = 0.0f;"),
    _m("pos-y", "    m->v3.y = s->Position[1];", "    m->v3.y = s->Position[0];"),
    _m("raise-bit", "ci->ExcludeFlags & SCENERY_RAISE_2M)",
       "ci->ExcludeFlags & 0x0200)"),
    _m("raise-view",
       "    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & SCENERY_RAISE_2M)",
       "    if ((int32_t)s->ExcludeFlags & SCENERY_RAISE_2M)"),
    _m("raise-1m", "        m->v3.z = m->v3.z + 2.0f;",
       "        m->v3.z = m->v3.z + 1.0f;"),
    _m("brute-no-vis",
       "    if (!scenery_is_visible(h, ci))\n        return;\n    for", "    for"),
    _m("brute-class2", "        scenery_draw_a_scenery(h, i, ci, 1);",
       "        scenery_draw_a_scenery(h, i, ci, 2);"),
    # the trees
    _m("code-offset",
       "        ((const uint8_t *)n + offsetof(SceneryTreeNode, ChildCodes));",
       "        ((const uint8_t *)n + offsetof(SceneryTreeNode, ChildCodes)"
       " + 2);"),
    _m("node-index", "    int16_t i = (int16_t)(-(int32_t)code);",
       "    int16_t i = (int16_t)(-(int32_t)code - 1);"),
    _m("tree-root-class", "    classes[0] = 1;", "    classes[0] = 2;"),
    _m("tree-reclassify",
       "        if (cls == 1)\n            cls = (uint32_t)classify_box(&n->BBox,",
       "        if (cls != 0)\n            cls = (uint32_t)classify_box(&n->BBox,"),
    _m("tree-no-out", "        if (cls == 0)\n            continue;\n", ""),
    _m("tree-count-5", "        for (i = 0; i < n->NumChildren; i++) {",
       "        for (i = 0; i < n->NumChildren && i < 5; i++) {"),
    _m("tree-code-gt0", "            if (code >= 0) {", "            if (code > 0) {"),
    _m("tree-push-class", "                classes[top] = (uint8_t)cls;",
       "                classes[top] = 1;"),
    _m("tree-draw-class",
       "                scenery_draw_a_scenery(h, code, ci, (int32_t)cls);",
       "                scenery_draw_a_scenery(h, code, ci, 1);"),
    _m("rec-reclassify",
       "    if (cls == 1)\n        cls = (uint32_t)classify_box(&node->BBox, ci);",
       "    if (cls != 0)\n        cls = (uint32_t)classify_box(&node->BBox, ci);"),
    _m("rec-no-out", "    if (cls == 0)\n        return;\n"
       "    for (i = 0; i < node->NumChildren; i++) {",
       "    for (i = 0; i < node->NumChildren; i++) {"),
    _m("rec-count", "    for (i = 0; i < node->NumChildren; i++) {",
       "    for (i = 0; i < node->NumChildren - 1; i++) {"),
    _m("rec-code-gt0", "        if (code >= 0)\n"
       "            scenery_draw_a_scenery(h, code, ci, (int32_t)cls);",
       "        if (code > 0)\n"
       "            scenery_draw_a_scenery(h, code, ci, (int32_t)cls);"),
    _m("rec-pass-1",
       "            scenery_cull_node_recursive(h, child_node(h, code), ci, cls);",
       "            scenery_cull_node_recursive(h, child_node(h, code), ci, 1);"),
    # the views
    _m("what-lt100", "            if (h->SectionNumber < 100 && n < max)",
       "            if (h->SectionNumber <= 100 && n < max)"),
    _m("what-list-max", "            if (h->SectionNumber < 100 && n < max)",
       "            if (h->SectionNumber < 100 && n <= max)"),
    _m("what-90", "        for (s = 90; s < 100; s++) {",
       "        for (s = 91; s < 100; s++) {"),
    _m("what-99", "        for (s = 90; s < 100; s++) {",
       "        for (s = 90; s < 99; s++) {"),
    _m("what-90-max",
       "            if (ScenerySectionHeaderTable[s] != NULL && n < max)",
       "            if (ScenerySectionHeaderTable[s] != NULL)"),
    _m("what-sec-gt0", "            if (sec >= 0 && ScenerySectionHeaderTable[sec]",
       "            if (sec > 0 && ScenerySectionHeaderTable[sec]"),
    _m("what-unloaded",
       "            if (sec >= 0 && ScenerySectionHeaderTable[sec] != NULL"
       " && n < max)",
       "            if (sec >= 0 && n < max)"),
    _m("what-zone-max",
       "            if (sec >= 0 && ScenerySectionHeaderTable[sec] != NULL"
       " && n < max)",
       "            if (sec >= 0 && ScenerySectionHeaderTable[sec] != NULL"
       " && n <= max)"),
    _m("what-player-view", "    if (view->ID == EVIEW_ID_PLAYER1) {",
       "    if (view->ID != EVIEW_ID_FRONTEND) {"),
    _m("what-no-zone-0",
       "        int32_t zn = z != NULL ? z->ZoneNumber : -1;",
       "        int32_t zn = z != NULL ? z->ZoneNumber : 0;"),
    _m("what-zone-keep",
       "        if (zn != CurrentZoneNumber)\n            CurrentZoneNumber = zn;",
       "        if (zn > CurrentZoneNumber)\n            CurrentZoneNumber = zn;"),
    _m("cullview-no-tree-check",
       "        if (h == NULL || h->SceneryTreeNodeTable == NULL)",
       "        if (h == NULL)"),
    _m("batch-bit", "        uint32_t bit = 1u << v;",
       "        uint32_t bit = 1u << (v + 1);"),
    _m("batch-or", "            h->ViewsVisibleThisFrame = seen | bit;",
       "            h->ViewsVisibleThisFrame = bit;"),
    _m("batch-no-zero", "        h->ViewsVisibleThisFrame = 0;\n    }\n}",
       "    }\n}"),
    _m("batch-view-bit",
       "                if (h->ViewsVisibleThisFrame & (1u << v))",
       "                if (h->ViewsVisibleThisFrame)"),
    _m("batch-views",
       "            for (v = 0; v < g->NumCullInfos; v++) {\n                if",
       "            for (v = 0; v < 1; v++) {\n                if"),
    _m("docull-top",
       "    g->pTopDrawInfo = SceneryDrawInfoTable + SCENERY_MAX_DRAW_INFOS;",
       "    g->pTopDrawInfo = SceneryDrawInfoTable + SCENERY_MAX_DRAW_INFOS"
       " - 1;"),
    _m("docull-no-pos", "        ci->Position = cam->CurrentKey.Position;\n", ""),
    _m("docull-no-dir", "        ci->Direction = cam->CurrentKey.Direction;\n",
       ""),
    _m("docull-no-h", "        ci->H = ci->pView->H;\n", ""),
    _m("docull-no-advance",
       "        g->pCurrentDrawInfo = ci->pCurrentDrawInfo;\n", ""),
    _m("docull-first", "        ci->pFirstDrawInfo = g->pCurrentDrawInfo;",
       "        ci->pFirstDrawInfo = g->pFirstDrawInfo;"),
    _m("stuff-any-view", "        if (ci->pView != view)\n            continue;\n",
       ""),
    _m("stuff-flags", "        uint32_t flags = (p & 3) == 2 ? 4u : 0u;",
       "        uint32_t flags = (p & 3) != 0 ? 4u : 0u;"),
    _m("stuff-light", "                model_render(m, &eMathIdentityMatrix,\n"
       "                             view->WorldLightContext, flags);",
       "                model_render(m, &eMathIdentityMatrix, NULL, flags);"),
    _m("stuff-light-matrix",
       "                model_render(m, d->pMatrix, NULL, flags);",
       "                model_render(m, d->pMatrix, view->WorldLightContext,"
       " flags);"),
    _m("stuff-all", "                model_render(m, d->pMatrix, NULL, flags);\n"
       "        }\n        return;",
       "                model_render(m, d->pMatrix, NULL, flags);\n        }"),
    # the setup
    _m("setup-atan-swap", "    int32_t a = bATan(wv->v0.z, wv->v0.x);",
       "    int32_t a = bATan(wv->v0.x, wv->v0.z);"),
    _m("setup-atan-y", "    int32_t a = bATan(wv->v0.z, wv->v0.x);",
       "    int32_t a = bATan(wv->v0.y, wv->v0.x);"),
    _m("setup-rot-neg", "    eRotateZ(&m, &m, (uint16_t)a);",
       "    eRotateZ(&m, &m, (uint16_t)-a);"),
    _m("setup-clip-wv", "    ci->ClipMatrix = *clip;", "    ci->ClipMatrix = *wv;"),
    _m("setup-flags-0", "    flags = 16;", "    flags = 0;"),
    _m("setup-mode-4", "    if (mode == 3 || mode == 4)", "    if (mode == 3)"),
    _m("setup-env-hi",
       "        < (uint32_t)(EVIEW_ID_ENVMAP_HI - EVIEW_ID_ENVMAP_LO + 1))",
       "        < (uint32_t)(EVIEW_ID_ENVMAP_HI - EVIEW_ID_ENVMAP_LO))"),
    _m("setup-env-signed", "    if ((uint32_t)view->ID - EVIEW_ID_ENVMAP_LO\n"
       "        < (uint32_t)(EVIEW_ID_ENVMAP_HI - EVIEW_ID_ENVMAP_LO + 1))",
       "    if (view->ID - EVIEW_ID_ENVMAP_LO\n"
       "        < (EVIEW_ID_ENVMAP_HI - EVIEW_ID_ENVMAP_LO + 1))"),
    _m("setup-env-flags", "        flags |= 0x102;", "        flags |= 0x100;"),
    _m("setup-fwd", "        flags |= 8;", "        flags |= 0;"),
    _m("setup-back", "        flags |= 4;", "        flags |= 0;"),
    _m("setup-back-fwd",
       "    if (RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD)",
       "    if (RaceParametersTrackDirection != TRACK_DIRECTION_FORWARD)"),
    _m("views-no-zero", "    g->NumCullInfos = 0;\n    if (!in_game)",
       "    if (!in_game)"),
    _m("views-no-ingame", "    if (!in_game)\n        return;\n", ""),
    _m("views-players", "    for (id = 1; id < 4; id++) {",
       "    for (id = 1; id < 3; id++) {"),
    _m("views-rt",
       "        if (v->Active != 0 && v->pRenderTarget0->Active != 0)",
       "        if (v->Active != 0)"),
    _m("views-no-env", "    if (!EnvironmentMappingEnable)\n        return;\n", ""),
    _m("views-env-hi",
       "    for (id = EVIEW_ID_ENVMAP_LO; id <= EVIEW_ID_ENVMAP_HI; id++) {",
       "    for (id = EVIEW_ID_ENVMAP_LO; id < EVIEW_ID_ENVMAP_HI; id++) {"),
    # the frame malloc
    _m("falloc-each", "    int32_t each = (int32_t)((size >> 5) << 4);",
       "    int32_t each = (int32_t)(size >> 1);", EFC),
    _m("falloc-name", "\"eFrameMallocBuffer1\"", "\"eFrameMallocBuffer0\"", EFC),
    _m("falloc-pool",
       "    FrameMemoryBuffer[0] = bMalloc(each, \"eFrameMallocBuffer0\", 0, 16);",
       "    FrameMemoryBuffer[0] = bMalloc(each, \"eFrameMallocBuffer0\", 0, 0);",
       EFC),
    _m("falloc-half", "    uint32_t half = size >> 1;",
       "    uint32_t half = size >> 2;", EFC),
    _m("falloc-end", "    CurrentBufferEnd = FrameMemoryBuffer[0] + half;",
       "    CurrentBufferEnd = FrameMemoryBuffer[1] + half;", EFC),
    _m("falloc-pos", "    CurrentBufferPos = FrameMemoryBuffer[0];\n",
       "    CurrentBufferPos = FrameMemoryBuffer[1];\n", EFC),
    _m("ffree-which", "    bFree(FrameMemoryBuffer[1]);",
       "    bFree(FrameMemoryBuffer[0]);", EFC),
    _m("ffree-keep-1", "    FrameMemoryBuffer[1] = 0;\n", "", EFC),
    _m("ffree-keep-size", "    FrameMemoryBufferSize = 0;\n", "", EFC),
    _m("ffree-keep-pos", "    CurrentBufferPos = 0;\n", "", EFC),
    _m("ffree-keep-end", "    CurrentBufferEnd = 0;\n", "", EFC),
    _m("fswap-max-unfailed",
       "    if (FrameMallocFailed && FrameMallocMaxFailAmount"
       " < FrameMallocFailAmount)",
       "    if (FrameMallocMaxFailAmount < FrameMallocFailAmount)", EFC),
    _m("fswap-max-failed",
       "    if (FrameMallocFailed && FrameMallocMaxFailAmount"
       " < FrameMallocFailAmount)",
       "    if (FrameMallocFailed)", EFC),
    _m("fswap-used1",
       "    FrameMemoryBufferAmountUsed[1] = FrameMemoryBufferAmountUsed[0];\n",
       "", EFC),
    _m("fswap-used0",
       "    FrameMemoryBufferAmountUsed[0] = (int32_t)(CurrentBufferPos - done);",
       "    FrameMemoryBufferAmountUsed[0] = (int32_t)(CurrentBufferPos - next);",
       EFC),
    _m("fswap-buf1", "    FrameMemoryBuffer[1] = done;\n", "", EFC),
    _m("fswap-end", "    CurrentBufferEnd = next + FrameMemoryBufferSize;",
       "    CurrentBufferEnd = done + FrameMemoryBufferSize;", EFC),
    _m("fswap-failed", "    FrameMallocFailed = 0;\n", "", EFC),
    _m("fswap-amount", "    FrameMallocFailAmount = 0;\n", "", EFC),
    _m("fswap-pos", "    CurrentBufferPos = next;", "    CurrentBufferPos = done;",
       EFC),
    _m("fsize-used",
       "    *used = FrameMemoryBufferAmountUsed[0] + FrameMemoryBufferAmountUsed[1];",
       "    *used = FrameMemoryBufferAmountUsed[0];", EFC),
    _m("fsize-size", "    return (int32_t)(FrameMemoryBufferSize << 1);",
       "    return (int32_t)FrameMemoryBufferSize;", EFC),
    _m("fmalloc-le", "    if (p + n < (uintptr_t)CurrentBufferEnd) {",
       "    if (p + n <= (uintptr_t)CurrentBufferEnd) {", EF),
    _m("fmalloc-no-failed", "    FrameMallocFailed = 1;\n", "", EF),
    _m("fmalloc-amount-set", "    FrameMallocFailAmount += n;",
       "    FrameMallocFailAmount = n;", EF),
    _m("fmalloc-no-advance", "        CurrentBufferPos = (uint8_t *)(p + n);\n",
       "", EF),
    # the views table
    _m("getview-id", "    return &eViews[id];", "    return &eViews[id == 9 ? 8 : id];",
       EVC),
    _m("viewmode", "    return CurrentViewMode;", "    return CurrentViewMode & 3;",
       EVC),
]

# The facade's matrix takes the position's z, but DrawAScenery writes the
# position over the matrix's last row straight after, so z reaches nothing.
EQUIVALENT = {"facade-z"}

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
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
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
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    ap.add_argument("--quick", action="store_true",
                    help="six cameras on TRACKB12, not all")
    args = ap.parse_args()

    sc = script(quick=args.quick)
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
    ops = sum(1 for line in lines if not line.startswith(("  ", "   ", "[")))
    draws = sum(1 for line in lines if line.startswith("  D["))
    renders = sum(1 for line in lines if line.startswith("  render "))
    print("%d scenarios, %d ops, %d lines, %d differ; %d draws, %d renders"
          % (len(sc.tags), ops, len(harness), bad, draws, renders))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
