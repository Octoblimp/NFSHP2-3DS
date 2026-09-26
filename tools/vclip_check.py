#!/usr/bin/env python3
"""Cross-check 3DS Files/source/vclip.c against VClip.obj in the image.

VClip.obj is 0x001c5d90 .. 0x001ca008: the V-Clip closest-feature walk the
collision system runs between two convex polyhedra, and the polyhedron,
feature, transform and clip classes it is built from. The image is the
oracle. tools/mipsemu.py runs the shipped functions out of NFSHP2.ELF, the
harness (tools/src/vclip_test.c) runs the port, both walk the same script,
and the two transcripts are diffed.

The records hold pointers, so the host's layouts are wider than the
handheld's and neither side can be handed the other's memory. Both build
the same polyhedra through the same calls -- NewVoronoiPlanes, NewVertex,
NewEdge, NewFace, the neighbour stores, SetVoronoiPlanes -- and every
feature in the transcript is named by polyhedron, kind and index, worked
out from the arrays' bounds on each side. Floats are compared as bits.

The script covers:

  * the polyhedron: the constructor, both Inits, the New* calls to and
    past their limits, NewEdge's truncation and int16 wrap, the Voronoi
    planes of boxes, tetrahedra, pyramids, octahedra and wafers, both
    Moves, GetNextEdgeInFace, the feature codes, the conversion to
    indices and back, MemoryImageLoad, Close and the destructor;
  * the transform, all four of its forms, over matrices with junk in the
    lanes a rotation leaves zero, and fDistBetween;
  * the three clips, driven directly over the Voronoi planes of real
    features with segments laid across them, from a fresh clip and from
    one carried over, with segments that end within rounding of the
    touch limits;
  * VClip itself: exact contacts between axis-aligned boxes (face, edge
    and vertex touching, coincident, nested), random poses of every pair
    of shapes from every kind of starting feature, and coherent runs where
    each call starts from the last one's answer;
  * VClip's checks one step at a time (OP_CHECK, set up as VClip sets
    them up). The walk settles on the same pair whichever way a step
    goes, so some of a step is only seen here: VV and VF either side of
    the touch distance, VE, EE and EF penetration with and without a
    distance left from an earlier call, parallel and near-parallel
    edges, and edges exactly parallel to a face's edge along a stored
    direction that is not quite unit length;
  * the Caffeine plots and the witness's destructor, through stubs that
    log each Espresso call; and the Print walk's one store.

What the fourth lanes of the contact points hold is masked in two cases,
on both sides alike: VV's two points and a penetrating VE's vertex point
are stored from a quadword whose fourth lane the image never wrote (see
vclip.c's head). Before each VClip both lanes are set to 7.0, so every
other lane VClip leaves alone is still compared.

    python tools/vclip_check.py
    python tools/vclip_check.py --mutate
    python tools/vclip_check.py --dump out/vclip
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF
M128 = (1 << 128) - 1

SOURCES = [
    "tools/src/vclip_test.c",
    "3DS Files/source/vclip.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/espresso.c",
]

VC = "3DS Files/source/vclip.c"

(OP_TAG, OP_POLY_CTOR, OP_POLY_ALLOC, OP_POLY_ARRAYS, OP_NEW_PLANES,
 OP_NEW_VERTEX, OP_NEW_EDGE, OP_NEW_FACE, OP_SET_NB, OP_SET_VORONOI,
 OP_SET_VORONOI_ONE, OP_DUMP_POLY, OP_MOVE_VERTEX, OP_MOVE_FACE,
 OP_NEXT_EDGE, OP_GET_CODE, OP_GET_FEATURE, OP_POKE_TYPE, OP_TO_INDICES,
 OP_TO_POINTERS, OP_DUMP_RAW, OP_MEMIMAGE_LOAD, OP_UNLOAD, OP_CLOSE,
 OP_DESTROY, OP_WIT_INIT, OP_WIT_SET, OP_VCLIP, OP_WIT_DESTROY,
 OP_WIT_PLOT, OP_POLY_PLOT, OP_ESP_NULL, OP_MESH_FACE, OP_XFORM, OP_XVEC,
 OP_XPT, OP_XVECP, OP_DIST, OP_XF_SET, OP_XF_EDGE, OP_XF_VERTEX,
 OP_CLIP_INIT, OP_CLIP_SET, OP_CLIP_PLANES, OP_CLIP_VERT, OP_CLIP_FACE,
 OP_FLAGS, OP_PRINT, OP_DUMP_WIT, OP_CHECK) = range(1, 51)

NPOLY = 8
NWIT = 8
NO_REF = M32
CP_SENTINEL = 0x40e00000

SIZE_V, SIZE_E, SIZE_F, SIZE_PL = 20, 12, 24, 24
KIND_SIZE = (SIZE_V, SIZE_E, SIZE_F)
KIND_CHAR = "vef"

G_PRINT_THIS_TIME = 0x00324448
G_PLOT_CLOSEST = 0x00324438
G_PRINTING = 0x00324358

bits = me.f_to_bits
fbits = me.fbits_to


def f32(v):
    return fbits(bits(v))


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def s8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def ref(poly, kind, idx):
    return (poly << 24) | (kind << 16) | idx


# ---------------------------------------------------------------- geometry
#
# Row vectors, as bWare has them: a point p of a polyhedron placed by (R, t)
# is at p.x * R.v0 + p.y * R.v1 + p.z * R.v2 + t in the world.


def vsub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def vadd(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def vscale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def vnorm(a):
    n = math.sqrt(vdot(a, a))
    return vscale(a, 1.0 / n)


class Shape(object):
    """A convex polyhedron as vertices and face loops, with the topology
    VCPolyhedron wants: each edge's tail and head, and the two faces
    across it."""

    def __init__(self, name, verts, faces):
        self.name = name
        self.verts = [[f32(c) for c in v] for v in verts]
        centre = vscale([sum(v[i] for v in self.verts) for i in range(3)],
                        1.0 / len(self.verts))
        loops = []
        for loop in faces:
            n = self._newell(loop)
            fc = vscale([sum(self.verts[i][k] for i in loop)
                         for k in range(3)], 1.0 / len(loop))
            if vdot(n, vsub(fc, centre)) < 0:
                loop = list(reversed(loop))
            loops.append(list(loop))
        self.faces = loops
        self.edges = []            # (tail, head, face1, face2)
        where = {}
        for fi, loop in enumerate(loops):
            for k in range(len(loop)):
                a, b = loop[k], loop[(k + 1) % len(loop)]
                if (b, a) in where:
                    ei = where[(b, a)]
                    t, h, f1, _ = self.edges[ei]
                    self.edges[ei] = (t, h, f1, fi)
                    where[(a, b)] = ei
                else:
                    where[(a, b)] = len(self.edges)
                    self.edges.append((a, b, fi, None))
        for e in self.edges:
            assert e[3] is not None, (name, e)
        self.face_edges = []
        for loop in loops:
            self.face_edges.append([where[(loop[k], loop[(k + 1) % len(loop)])]
                                    for k in range(len(loop))])
        self.vert_edges = [[ei for ei, e in enumerate(self.edges)
                            if v in (e[0], e[1])]
                           for v in range(len(self.verts))]
        self.normals = []
        for loop in loops:
            n = vnorm(self._newell(loop))
            n = [f32(c) for c in n]
            d = f32(vdot(n, self.verts[loop[0]]))
            self.normals.append((n, d))
        self.dirs = [[f32(c) for c in vnorm(vsub(self.verts[h],
                                                 self.verts[t]))]
                     for t, h, _, _ in self.edges]

    def _newell(self, loop):
        n = [0.0, 0.0, 0.0]
        for k in range(len(loop)):
            a = self.verts[loop[k]]
            b = self.verts[loop[(k + 1) % len(loop)]]
            n[0] += (a[1] - b[1]) * (a[2] + b[2])
            n[1] += (a[2] - b[2]) * (a[0] + b[0])
            n[2] += (a[0] - b[0]) * (a[1] + b[1])
        return n

    def counts(self):
        np_ = (sum(len(x) for x in self.vert_edges) + 4 * len(self.edges)
               + sum(len(x) for x in self.face_edges))
        return len(self.verts), len(self.edges), len(self.faces), np_

    def max_face(self):
        return max(len(x) for x in self.face_edges)


def box(hx, hy, hz, name="box"):
    v = [[sx * hx, sy * hy, sz * hz] for sx in (-1, 1) for sy in (-1, 1)
         for sz in (-1, 1)]
    idx = {(sx, sy, sz): i for i, (sx, sy, sz) in enumerate(
        (a, b, c) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1))}

    def q(*c):
        return [idx[x] for x in c]
    faces = [
        q((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
        q((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),
        q((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)),
        q((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
        q((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
        q((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),
    ]
    return Shape(name, v, faces)


def tetra(s=1.0):
    v = [[s, s, s], [s, -s, -s], [-s, s, -s], [-s, -s, s]]
    return Shape("tetra", v, [[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]])


def pyramid(b=1.0, h=1.5):
    v = [[-b, -b, 0], [b, -b, 0], [b, b, 0], [-b, b, 0], [0, 0, h]]
    return Shape("pyramid", v, [[0, 3, 2, 1], [0, 1, 4], [1, 2, 4],
                                [2, 3, 4], [3, 0, 4]])


def octa(s=1.0):
    v = [[s, 0, 0], [-s, 0, 0], [0, s, 0], [0, -s, 0], [0, 0, s],
         [0, 0, -s]]
    faces = []
    for a in (0, 1):
        for b in (2, 3):
            for c in (4, 5):
                faces.append([a, b, c])
    return Shape("octa", v, faces)


def wafer(n=6, r=1.0, h=0.25, twist=0.0):
    v = []
    for z in (-h, h):
        for k in range(n):
            a = 2 * math.pi * k / n + twist
            v.append([r * math.cos(a), r * math.sin(a), z])
    faces = [list(range(n)), list(range(n, 2 * n))]
    for k in range(n):
        faces.append([k, (k + 1) % n, n + (k + 1) % n, n + k])
    return Shape("wafer%d" % n, v, faces)


# ---------------------------------------------------------------- matrices


def identity():
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]]


def rotation(axis, angle):
    x, y, z = vnorm(axis)
    c, s = math.cos(angle), math.sin(angle)
    t = 1 - c
    m = [[t * x * x + c, t * x * y + s * z, t * x * z - s * y, 0.0],
         [t * x * y - s * z, t * y * y + c, t * y * z + s * x, 0.0],
         [t * x * z + s * y, t * y * z - s * x, t * z * z + c, 0.0],
         [0.0, 0.0, 0.0, 1.0]]
    return [[f32(c_) for c_ in row] for row in m]


def rand_rotation(rnd):
    axis = [rnd.gauss(0, 1) for _ in range(3)]
    if vdot(axis, axis) < 1e-6:
        axis = [0.0, 0.0, 1.0]
    return rotation(axis, rnd.uniform(-math.pi, math.pi))


def mwords(m):
    return [bits(c) for row in m for c in row]


def vwords(v, pad=0.0):
    return [bits(v[0]), bits(v[1]), bits(v[2]), bits(pad)]


def place(shape_pt, m, t):
    """A local point in the world, for laying the scenes out."""
    return [shape_pt[0] * m[0][k] + shape_pt[1] * m[1][k]
            + shape_pt[2] * m[2][k] + t[k] for k in range(3)]


def solve_t(m, local, world):
    """The translation that puts `local` of a shape turned by m at `world`."""
    p = place(local, m, [0, 0, 0])
    return [f32(world[k] - p[k]) for k in range(3)]


def bv(sx, sy, sz):
    """A box's vertex index from its signs."""
    return (sx > 0) * 4 + (sy > 0) * 2 + (sz > 0)


def edge_of(shape, a, b):
    for i, (t, h, _, _) in enumerate(shape.edges):
        if {t, h} == {a, b}:
            return i
    raise KeyError((a, b))


def face_of(shape, n):
    return max(range(len(shape.faces)),
               key=lambda i: vdot(shape.normals[i][0], n))


# ---------------------------------------------------------------- the script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []
        self.shapes = {}          # poly -> Shape
        self.plane_base = {}      # poly -> {("v"|"e"|"f", i): first plane}

    def op(self, code, *args):
        self.words.append(code)
        for a in args:
            if isinstance(a, (list, tuple)):
                self.words.extend(x & M32 for x in a)
            else:
                self.words.append(a & M32)

    def tag(self, name):
        self.op(OP_TAG, len(self.tags))
        self.tags.append(name)

    def build(self, pi, shape, arrays=False, slack=(0, 0, 0, 0), dump=True,
              voronoi=True):
        nv, ne, nf, np_ = shape.counts()
        mx = [nv + slack[0], ne + slack[1], nf + slack[2], np_ + slack[3]]
        self.op(OP_POLY_CTOR, pi)
        self.op(OP_POLY_ARRAYS if arrays else OP_POLY_ALLOC, pi, *mx)
        base = {}
        nxt = 0
        for i, v in enumerate(shape.verts):
            n = len(shape.vert_edges[i])
            self.op(OP_NEW_PLANES, pi, n)
            base[("v", i)] = nxt
            self.op(OP_NEW_VERTEX, pi, vwords(v, 0.0), n, nxt)
            nxt += n
        for i, d in enumerate(shape.dirs):
            self.op(OP_NEW_PLANES, pi, 4)
            base[("e", i)] = nxt
            self.op(OP_NEW_EDGE, pi, vwords(d, 0.0), 4, nxt)
            nxt += 4
        for i, (n, d) in enumerate(shape.normals):
            k = len(shape.face_edges[i])
            self.op(OP_NEW_PLANES, pi, k)
            base[("f", i)] = nxt
            self.op(OP_NEW_FACE, pi, vwords(n, 0.0), bits(d), k, nxt)
            nxt += k
        for i in range(len(shape.verts)):
            for k, ei in enumerate(shape.vert_edges[i]):
                self.op(OP_SET_NB, pi, base[("v", i)] + k, ref(pi, 1, ei))
        for i, (t, h, f1, f2) in enumerate(shape.edges):
            b = base[("e", i)]
            self.op(OP_SET_NB, pi, b + 0, ref(pi, 0, t))
            self.op(OP_SET_NB, pi, b + 1, ref(pi, 0, h))
            self.op(OP_SET_NB, pi, b + 2, ref(pi, 2, f1))
            self.op(OP_SET_NB, pi, b + 3, ref(pi, 2, f2))
        for i in range(len(shape.faces)):
            for k, ei in enumerate(shape.face_edges[i]):
                self.op(OP_SET_NB, pi, base[("f", i)] + k, ref(pi, 1, ei))
        if voronoi:
            self.op(OP_SET_VORONOI, pi)
        if dump:
            self.op(OP_DUMP_POLY, pi)
        self.shapes[pi] = shape
        self.plane_base[pi] = base

    def vclip(self, w, m1, t1, m2, t2, p1=(0.0,), p2=(0.0,)):
        self.op(OP_VCLIP, w, mwords(m1), vwords(t1, p1[0]), mwords(m2),
                vwords(t2, p2[0]))

    def check(self, w, kind, swap, m1, t1, m2, t2):
        self.op(OP_CHECK, w, kind, swap, mwords(m1), vwords(t1), mwords(m2),
                vwords(t2))

    def features(self, pi):
        s = self.shapes[pi]
        return ([ref(pi, 0, i) for i in range(len(s.verts))]
                + [ref(pi, 1, i) for i in range(len(s.edges))]
                + [ref(pi, 2, i) for i in range(len(s.faces))])


SHAPES = [
    lambda: box(1.0, 1.0, 1.0),
    lambda: box(2.0, 0.5, 0.25, "slab"),
    lambda: tetra(1.0),
    lambda: pyramid(1.0, 1.5),
    lambda: octa(1.2),
    lambda: wafer(6, 1.0, 0.25),
    lambda: wafer(5, 1.3, 0.6, 0.3),
    lambda: box(0.1, 0.1, 3.0, "rod"),
]


def api_section(sc):
    sc.tag("constructor, Init with no room")
    sc.op(OP_POLY_CTOR, 0)
    sc.op(OP_POLY_ALLOC, 0, 0, 0, 0, 0)
    sc.op(OP_NEW_PLANES, 0, 0)
    sc.op(OP_NEW_PLANES, 0, 1)
    sc.op(OP_NEW_VERTEX, 0, vwords([1, 2, 3]), 0, NO_REF)
    sc.op(OP_NEW_EDGE, 0, vwords([1, 0, 0]), 0, NO_REF)
    sc.op(OP_NEW_FACE, 0, vwords([0, 0, 1]), bits(1.0), 0, NO_REF)
    sc.op(OP_DUMP_POLY, 0)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_CLOSE, 0)

    sc.tag("the New calls to their limits")
    sc.op(OP_POLY_CTOR, 0)
    sc.op(OP_POLY_ALLOC, 0, 3, 12, 3, 10)
    for n in (4, 0, 3, 2, 1, 1):
        sc.op(OP_NEW_PLANES, 0, n)
    sc.op(OP_NEW_VERTEX, 0, vwords([1.5, -2.25, 1e-3], 9.0), 3, 0)
    sc.op(OP_NEW_VERTEX, 0, vwords([-0.0, 0.0, 1e30]), 200, 4)
    sc.op(OP_NEW_VERTEX, 0, vwords([7, 8, 9]), -3, NO_REF)
    sc.op(OP_NEW_VERTEX, 0, vwords([7, 8, 9]), 1, 1)
    for k, d in enumerate(([1.0, 0.0, 0.0], [0.6, -0.8, 0.0], [3.99993896484375, 4.0, -4.0],
              [-4.1, 5.0, 8.0], [0.5 / 8192, -0.5 / 8192, -1.5 / 8192],
              [-1.0 / 8192, 1.0 / 8192, 0.99999994], [-0.0, 1e-9, -1e-9],
              [0.577350269, 0.577350269, -0.577350269],
              [2.0000002, -2.9999998, 3.9999998],
              [1e6, -1e6, 0.1], [0.1, 0.2, 0.3], [-0.30000001, 0.7, 0.9])):
        sc.op(OP_NEW_EDGE, 0, vwords(d), (4, 2, 200, -1)[k % 4], 2)
    sc.op(OP_NEW_EDGE, 0, vwords([1, 1, 1]), 4, 2)
    sc.op(OP_NEW_FACE, 0, vwords([0, 0.6, 0.8], 5.0), bits(-2.5), 5, 0)
    sc.op(OP_NEW_FACE, 0, vwords([1, 0, 0]), bits(0.0), 127, NO_REF)
    sc.op(OP_NEW_FACE, 0, vwords([0, 1, 0]), bits(0.5), 130, NO_REF)
    sc.op(OP_NEW_FACE, 0, vwords([1, 0, 0]), bits(0.0), 1, NO_REF)
    sc.op(OP_DUMP_POLY, 0)
    sc.op(OP_DESTROY, 0, 0)
    sc.op(OP_DESTROY, 0, 1)

    sc.tag("Init with arrays, then Init again")
    sc.op(OP_POLY_CTOR, 1)
    sc.op(OP_POLY_ARRAYS, 1, 2, 2, 2, 5)
    sc.op(OP_NEW_PLANES, 1, 5)
    sc.op(OP_NEW_PLANES, 1, 1)
    sc.op(OP_NEW_VERTEX, 1, vwords([1, 1, 1]), 2, 0)
    sc.op(OP_DUMP_POLY, 1)
    sc.op(OP_CLOSE, 1)
    sc.op(OP_POLY_ARRAYS, 1, 70000, 0x7fff, 0, 0)
    sc.op(OP_POLY_ALLOC, 1, 1, 2, 3, 4)
    sc.op(OP_DUMP_POLY, 1)
    sc.op(OP_NEW_PLANES, 1, 3)
    sc.op(OP_NEW_VERTEX, 1, vwords([1, 1, 1]), 3, 0)
    sc.op(OP_CLOSE, 1)
    # Close leaves the counts; Init clears them, and sizes its arrays from
    # the int16 maxima it stored, not the ints it was passed.
    sc.op(OP_POLY_ALLOC, 1, 0x10001, 0x10002, 0x10003, 0x10005)
    sc.op(OP_DUMP_POLY, 1)
    sc.op(OP_DESTROY, 1, 3)

    sc.tag("Close straight after the constructor")
    sc.op(OP_POLY_CTOR, 2)
    sc.op(OP_CLOSE, 2)


def shapes_section(sc, rnd):
    for k, mk in enumerate(SHAPES):
        s = mk()
        sc.tag("the Voronoi planes of a %s" % s.name)
        sc.build(k % 4, s, arrays=(k % 2 == 1), slack=(k % 3, 1, 0, 2))

    sc.tag("one feature at a time, in the wrong order")
    s = box(1.0, 0.75, 0.5)
    sc.build(0, s, voronoi=False, dump=False)
    for ei in range(len(s.edges)):
        sc.op(OP_SET_VORONOI_ONE, ref(0, 1, ei))
    sc.op(OP_DUMP_POLY, 0)
    for fi in range(len(s.faces)):
        sc.op(OP_SET_VORONOI_ONE, ref(0, 2, fi))
    for ei in range(len(s.edges)):
        sc.op(OP_SET_VORONOI_ONE, ref(0, 1, ei))
    for vi in range(len(s.verts)):
        sc.op(OP_SET_VORONOI_ONE, ref(0, 0, vi))
    sc.op(OP_DUMP_POLY, 0)

    sc.tag("the planes of a skewed solid")
    v = [[rnd.uniform(-1, 1) * 0.3 + sx, rnd.uniform(-1, 1) * 0.3 + sy,
          rnd.uniform(-1, 1) * 0.3 + sz]
         for sx, sy, sz in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]
    sc.build(2, Shape("skew", v, [[0, 1, 2], [0, 3, 1], [0, 2, 3],
                                   [1, 3, 2]]))

    sc.tag("Move")
    sc.build(1, pyramid(1.0, 1.5), dump=False)
    for vi, d in ((0, [0.1, -0.2, 0.3]), (4, [0.0, 0.0, -0.5]),
                  (2, [1e-8, 1e8, -0.0]), (0, [-0.1, 0.2, -0.3])):
        sc.op(OP_MOVE_VERTEX, ref(1, 0, vi), vwords(d, 3.0))
    for fi, d in ((0, [0.1, -0.2, 0.3]), (3, [0.0, 0.0, -0.5]),
                  (1, [5.0, 5.0, 5.0]), (4, [-1e-7, 2.0, 1e-3])):
        sc.op(OP_MOVE_FACE, ref(1, 2, fi), vwords(d, 3.0))
    sc.op(OP_SET_VORONOI, 1)
    sc.op(OP_DUMP_POLY, 1)

    sc.tag("GetNextEdgeInFace")
    s = sc.shapes[1]
    for vi in range(len(s.verts)):
        for fi in range(len(s.faces)):
            sc.op(OP_NEXT_EDGE, ref(1, 0, vi), NO_REF, ref(1, 2, fi))
            for ei in s.vert_edges[vi]:
                sc.op(OP_NEXT_EDGE, ref(1, 0, vi), ref(1, 1, ei),
                      ref(1, 2, fi))
        sc.op(OP_NEXT_EDGE, ref(1, 0, vi), ref(1, 1, 0), ref(1, 2, 0))


def codes_section(sc):
    sc.tag("feature codes")
    sc.build(3, box(1.0, 2.0, 3.0), dump=False)
    for r in sc.features(3) + [NO_REF]:
        sc.op(OP_GET_CODE, 3, r)
    for t in (3, -1, 15, 16, 0x7f):
        sc.op(OP_POKE_TYPE, ref(3, 0, 5), t)
        sc.op(OP_GET_CODE, 3, ref(3, 0, 5))
    sc.op(OP_POKE_TYPE, ref(3, 0, 5), 0)
    for code in [(i << 4) | t for t in range(3) for i in (0, 1, 5)] + [
            0xffffffff, 0x3, 0x14, 0x5f, 0xf, 0xfffffffe, 0x0, 0x52,
            0xb1, 0x71]:
        sc.op(OP_GET_FEATURE, 3, code)

    sc.tag("to indices and back")
    sc.op(OP_TO_INDICES, 3)
    sc.op(OP_TO_POINTERS, 3)
    sc.op(OP_DUMP_POLY, 3)

    sc.tag("a memory image")
    sc.build(4, octa(1.0), arrays=True, dump=False)
    sc.op(OP_TO_INDICES, 4)
    sc.op(OP_POLY_CTOR, 5)
    sc.op(OP_MEMIMAGE_LOAD, 5, 4)
    sc.op(OP_SET_VORONOI, 5)
    sc.op(OP_DUMP_POLY, 5)
    sc.op(OP_UNLOAD, 5)
    sc.op(OP_POLY_CTOR, 4)

    sc.tag("a memory image of allocated arrays")
    sc.build(6, wafer(5, 1.0, 0.5), dump=False)
    sc.op(OP_TO_INDICES, 6)
    sc.op(OP_POLY_CTOR, 7)
    sc.op(OP_MEMIMAGE_LOAD, 7, 6)
    sc.op(OP_DUMP_POLY, 7)
    sc.op(OP_DESTROY, 7, 1)
    sc.op(OP_POLY_CTOR, 6)

    sc.tag("unloading what Init allocated")
    sc.build(6, tetra(1.0), dump=False)
    sc.op(OP_POLY_PLOT, 6, mwords(identity()))
    sc.op(OP_UNLOAD, 6)
    sc.op(OP_UNLOAD, 6)


JUNK_M = [[0.25, -0.5, 0.75, 3.0], [1.5, 0.125, -2.0, -7.0],
          [-0.3, 0.6, 0.9, 11.0], [4.0, -5.0, 6.0, 0.5]]


def transform_section(sc, rnd):
    sc.tag("the transform")
    mats = [identity(), rotation([0, 0, 1], 0.5), rotation([1, 2, 3], 2.0),
            JUNK_M, [[f32(rnd.uniform(-2, 2)) for _ in range(4)]
                     for _ in range(4)]]
    vecs = [[1.0, 2.0, 3.0, 4.0], [0.0, 0.0, 0.0, 0.0], [-1.5, 0.25, 8.0, -1.0],
            [1e-3, -1e3, 0.5, 9.0], [-0.0, -0.0, -0.0, -0.0]]
    for _ in range(12):
        a, b = rnd.choice(mats), rnd.choice(mats)
        ta = [f32(rnd.uniform(-5, 5)) for _ in range(4)]
        tb = [f32(rnd.uniform(-5, 5)) for _ in range(4)]
        sc.op(OP_XFORM, mwords(a), vwords(ta, ta[3]), mwords(b),
              vwords(tb, tb[3]))
        for v in vecs + [[f32(rnd.uniform(-3, 3)) for _ in range(4)]]:
            sc.op(OP_XVEC, vwords(v, v[3]))
            sc.op(OP_XPT, vwords(v, v[3]))
            sc.op(OP_XVECP, vwords(v, v[3]))

    sc.tag("fDistBetween")
    for a, b in (([0, 0, 0, 0], [0, 0, 0, 0]), ([1, 2, 3, 9], [4, 6, 3, -9]),
                 ([-0.0, 0, 0, 0], [0, -0.0, 0, 0]),
                 ([1e-20, 0, 0, 0], [0, 0, 0, 0]),
                 ([1e20, 1e20, 0, 0], [0, 0, 0, 0])):
        sc.op(OP_DIST, vwords(a, a[3]), vwords(b, b[3]))
    for _ in range(20):
        a = [f32(rnd.uniform(-10, 10)) for _ in range(4)]
        b = [f32(rnd.uniform(-10, 10)) for _ in range(4)]
        sc.op(OP_DIST, vwords(a, a[3]), vwords(b, b[3]))


def clip_section(sc, rnd):
    sc.tag("transformed features")
    pi = 0
    sc.build(pi, box(1.0, 1.0, 1.0), dump=False)
    s = sc.shapes[pi]
    base = sc.plane_base[pi]
    for m, t in ((identity(), [0, 0, 0]), (JUNK_M, [1, -2, 3]),
                 (rotation([1, 1, 0], 0.7), [0.5, 0.5, -0.5])):
        sc.op(OP_XFORM, mwords(m), vwords(t, 2.0), mwords(identity()),
              vwords([0, 0, 0]))
        for ei in (0, 3, 7):
            sc.op(OP_XF_EDGE, ref(pi, 1, ei))
        sc.op(OP_XF_VERTEX, ref(pi, 0, 2))

    def segment(scale=2.5):
        h = [f32(rnd.uniform(-scale, scale)) for _ in range(3)]
        t = [f32(rnd.uniform(-scale, scale)) for _ in range(3)]
        if rnd.random() < 0.3:
            # through the box's centre region
            t = [f32(-c) for c in h]
        e = [f32(h[k] - t[k]) for k in range(3)]
        pads = [f32(rnd.choice([0.0, 1.0, -2.5])) for _ in range(3)]
        return h, t, e, pads

    sc.tag("the clips")
    for n in range(260):
        h, t, e, pads = segment()
        sc.op(OP_XF_SET, vwords(h, pads[0]), vwords(t, pads[1]),
              vwords(e, pads[2]))
        sc.op(OP_CLIP_INIT)
        which = rnd.random()
        if which < 0.3:
            vi = rnd.randrange(len(s.verts))
            sc.op(OP_CLIP_PLANES, pi, base[("v", vi)], 3)
        elif which < 0.55:
            fi = rnd.randrange(len(s.faces))
            sc.op(OP_CLIP_PLANES, pi, base[("f", fi)], 4)
            sc.op(OP_CLIP_INIT)
            sc.op(OP_CLIP_FACE, pi, base[("f", fi)], 4, NO_REF)
        elif which < 0.8:
            ei = rnd.randrange(len(s.edges))
            b = base[("e", ei)]
            sc.op(OP_CLIP_VERT, pi, b, 2, 0, vwords([0, 0, 0]))
            sc.op(OP_CLIP_FACE, pi, b + 2, 2, NO_REF)
            if rnd.random() < 0.5:
                fi = s.edges[ei][2]
                sc.op(OP_CLIP_INIT)
                sc.op(OP_CLIP_FACE, pi, b + 2, 2, ref(pi, 2, fi))
        else:
            vi = rnd.randrange(len(s.verts))
            v = s.verts[vi]
            if rnd.random() < 0.5:
                v = [f32(c + rnd.uniform(-0.01, 0.01)) for c in v]
            sc.op(OP_CLIP_VERT, pi, base[("v", vi)], 3, 1,
                  vwords(v, rnd.choice([0.0, 5.0])))

    sc.tag("the clips at their touch limits")
    # Segments that end on, or a hair off, a vertex or a face, so the
    # squared-distance and plane-distance tests go each way.
    for n in range(120):
        ei = rnd.randrange(len(s.edges))
        tv, hv, f1, f2 = s.edges[ei]
        b = base[("e", ei)]
        end = s.verts[rnd.choice((tv, hv))]
        off = rnd.choice([0.0, 1e-6, 2e-3, 3e-3, 4e-3, 1e-2, 0.1, 5e-5,
                          2e-4])
        far = [f32(rnd.uniform(-3, 3)) for _ in range(3)]
        near = [f32(end[k] + rnd.choice([-1, 1]) * off) for k in range(3)]
        if rnd.random() < 0.5:
            h, t = near, far
        else:
            h, t = far, near
        e = [f32(h[k] - t[k]) for k in range(3)]
        sc.op(OP_XF_SET, vwords(h), vwords(t), vwords(e))
        sc.op(OP_CLIP_INIT)
        sc.op(OP_CLIP_VERT, pi, b, 2, 0, vwords([0, 0, 0]))
        sc.op(OP_CLIP_FACE, pi, b + 2, 2, NO_REF)

    sc.tag("a clip carried over")
    for n in range(30):
        h, t, e, pads = segment(1.5)
        sc.op(OP_XF_SET, vwords(h), vwords(t), vwords(e))
        lmin = f32(rnd.uniform(0.05, 0.45))
        lmax = f32(rnd.uniform(0.55, 0.95))
        sc.op(OP_CLIP_SET, bits(lmin), bits(lmax), ref(pi, 0, rnd.randrange(8)),
              ref(pi, 2, rnd.randrange(6)), rnd.choice([0, 1]))
        ei = rnd.randrange(len(s.edges))
        sc.op(OP_CLIP_FACE, pi, base[("e", ei)] + 2, 2, NO_REF)


def clip_limits_section(sc):
    """Clips carried over onto a vertex and onto faces, and segments that
    end within rounding of the touch limits. Its own sequence, so the rest
    of the script stays as it was."""
    rnd = random.Random(5)
    pi = 0
    sc.build(pi, box(1.0, 1.0, 1.0), dump=False)
    s = sc.shapes[pi]
    base = sc.plane_base[pi]
    v7, v0 = ref(pi, 0, 7), ref(pi, 0, 0)
    sc.tag("a clip carried onto a vertex")
    sc.op(OP_XF_SET, vwords([-0.5, 1, 1]), vwords([1.5, 1, 1]),
          vwords([-2, 0, 0]))
    for lmin, nmin, nmax in ((0.25, v7, v0), (0.2495, v7, v0),
                             (0.248, v7, v0), (0.25, v7, ref(pi, 0, 6))):
        sc.op(OP_CLIP_SET, bits(f32(lmin)), bits(0.75), nmin, nmax, 0)
        sc.op(OP_CLIP_VERT, pi, 0, 0, 0, vwords([0, 0, 0]))

    sc.tag("clips carried over, any neighbours")
    allf = sc.features(pi)
    verts = [ref(pi, 0, k) for k in range(8)]
    for n in range(300):
        h = [f32(rnd.uniform(-1.5, 1.5)) for _ in range(3)]
        tl = [f32(rnd.uniform(-1.5, 1.5)) for _ in range(3)]
        e = [f32(h[k] - tl[k]) for k in range(3)]
        sc.op(OP_XF_SET, vwords(h), vwords(tl), vwords(e))
        lmin = f32(rnd.uniform(0.05, 0.45))
        lmax = f32(rnd.uniform(0.55, 0.95))
        ei = rnd.randrange(len(s.edges))
        if rnd.random() < 0.6:
            sc.op(OP_CLIP_SET, bits(lmin), bits(lmax), rnd.choice(allf),
                  rnd.choice(allf), rnd.choice([0, 1]))
            face = rnd.choice([NO_REF] * 3 + [ref(pi, 2, k)
                                              for k in range(6)])
            sc.op(OP_CLIP_FACE, pi, base[("e", ei)] + 2, 2, face)
        else:
            sc.op(OP_CLIP_SET, bits(lmin), bits(lmax),
                  rnd.choice(verts + [NO_REF]),
                  rnd.choice(verts + [NO_REF]), rnd.choice([0, 1]))
            sc.op(OP_CLIP_VERT, pi, base[("e", ei)], rnd.choice([0, 2]),
                  0, vwords([0, 0, 0]))

    sc.tag("an edge's face planes with the face given")
    for n in range(300):
        ei = rnd.randrange(len(s.edges))
        tv, hv, f1, f2 = s.edges[ei]
        m = [(s.verts[tv][k] + s.verts[hv][k]) / 2 for k in range(3)]
        d = s.dirs[ei]
        n1, n2 = s.normals[f1][0], s.normals[f2][0]

        def pt():
            a, b, c = (rnd.uniform(-0.6, 1.2), rnd.uniform(-0.6, 1.2),
                       rnd.uniform(-0.8, 0.8))
            return [f32(m[k] + a * n1[k] + b * n2[k] + c * d[k])
                    for k in range(3)]
        h, tl = pt(), pt()
        e = [f32(h[k] - tl[k]) for k in range(3)]
        sc.op(OP_XF_SET, vwords(h), vwords(tl), vwords(e))
        sc.op(OP_CLIP_INIT)
        face = rnd.choice([f1, f2, rnd.randrange(6)])
        sc.op(OP_CLIP_FACE, pi, base[("e", ei)] + 2, 2, ref(pi, 2, face))

    # CheckVertex's limit is a squared distance of 1e-5 and the face's a
    # height of 1e-4; these cross each within a few ulps of it.
    sc.tag("vertex planes within rounding of the touch limit")
    r0 = math.sqrt(1e-5)
    for n in range(400):
        ei = rnd.randrange(len(s.edges))
        tv, hv, f1, f2 = s.edges[ei]
        end = rnd.choice((0, 1))
        V = s.verts[(tv, hv)[end]]
        d = s.dirs[ei] if end == 0 else [-c for c in s.dirs[ei]]
        n1, n2 = s.normals[f1][0], s.normals[f2][0]
        ang = rnd.uniform(0, 2 * math.pi)
        r = r0 * (1 + rnd.uniform(-4e-5, 4e-5))
        off = [math.cos(ang) * n1[k] + math.sin(ang) * n2[k] for k in range(3)]
        q = [V[k] + r * off[k] for k in range(3)]
        w = vnorm([d[k] + rnd.uniform(-0.8, 0.8) for k in range(3)])
        a, b = rnd.uniform(0.1, 1.5), rnd.uniform(0.1, 1.5)
        inside = [f32(q[k] + a * w[k]) for k in range(3)]
        outside = [f32(q[k] - b * w[k]) for k in range(3)]
        h, tl = (inside, outside) if rnd.random() < 0.5 else (outside, inside)
        e = [f32(h[k] - tl[k]) for k in range(3)]
        sc.op(OP_XF_SET, vwords(h), vwords(tl), vwords(e))
        sc.op(OP_CLIP_INIT)
        sc.op(OP_CLIP_VERT, pi, base[("e", ei)], 2, 0, vwords([0, 0, 0]))
    sc.tag("face planes within rounding of the touch limit")
    for n in range(400):
        ei = rnd.randrange(len(s.edges))
        tv, hv, f1, f2 = s.edges[ei]
        m = [(s.verts[tv][k] + s.verts[hv][k]) / 2 for k in range(3)]
        d = s.dirs[ei]
        n1, n2 = s.normals[f1][0], s.normals[f2][0]
        if rnd.random() < 0.5:
            n1, n2, fx = n2, n1, f2
        else:
            fx = f1
        hgt = 1e-4 * (1 + rnd.uniform(-2e-3, 2e-3))
        c = rnd.uniform(-0.8, 0.8)
        q = [m[k] + hgt * n1[k] + c * d[k] for k in range(3)]
        w = vnorm([n2[k] + rnd.uniform(-0.8, 0.8) for k in range(3)])
        a, b = rnd.uniform(0.1, 1.5), rnd.uniform(0.1, 1.5)
        inside = [f32(q[k] + a * w[k]) for k in range(3)]
        outside = [f32(q[k] - b * w[k]) for k in range(3)]
        h, tl = (inside, outside) if rnd.random() < 0.5 else (outside, inside)
        e = [f32(h[k] - tl[k]) for k in range(3)]
        sc.op(OP_XF_SET, vwords(h), vwords(tl), vwords(e))
        sc.op(OP_CLIP_INIT)
        sc.op(OP_CLIP_FACE, pi, base[("e", ei)] + 2, 2,
              rnd.choice([NO_REF, ref(pi, 2, fx)]))


def contact_section(sc):
    sc.tag("unit boxes, exact contacts")
    sc.build(0, box(1.0, 1.0, 1.0), dump=False)
    sc.build(1, box(1.0, 1.0, 1.0), dump=False)
    I = identity()
    places = [[2.5, 0, 0], [2, 0, 0], [2, 2, 0], [2, 2, 2], [1.5, 0, 0],
              [0, 0, 0], [0.25, 0.1, 0], [3, 3, 3], [-2, 0.5, 0.5],
              [2, 1, 0], [2, 0.5, 0.25], [0, 0, -2], [1.9999999, 0, 0],
              [2.0000002, 2, 0], [0.5, 0.5, 0.5], [0, 0, 5]]
    for p in places:
        for f1, f2 in ((ref(0, 0, 0), ref(1, 0, 0)),
                       (ref(0, 2, 0), ref(1, 2, 1)),
                       (ref(0, 1, 3), ref(1, 1, 5)),
                       (ref(0, 0, 7), ref(1, 2, 4))):
            sc.op(OP_WIT_INIT, 0, 0, 1)
            sc.op(OP_WIT_SET, 0, f1, f2)
            sc.vclip(0, I, [0, 0, 0], I, p)

    sc.tag("a box turned onto its edge and vertex")
    r45 = rotation([0, 0, 1], math.pi / 4)
    rv = rotation([1, -1, 0], math.atan(math.sqrt(2)))
    for m, p in ((r45, [1 + math.sqrt(2), 0, 0]), (r45, [2.5, 0, 0]),
                 (r45, [2.2, 0.3, 0.5]), (rv, [0, 0, 1 + math.sqrt(3)]),
                 (rv, [0, 0, 2.8]), (rv, [0.1, 0.1, 2.6]),
                 (r45, [0, 2.3, 0]), (rv, [0, 0, 2.0])):
        p = [f32(c) for c in p]
        sc.op(OP_WIT_INIT, 1, 0, 1)
        for _ in range(2):
            sc.vclip(1, I, [0, 0, 0], m, p)
            sc.vclip(1, m, p, I, [0, 0, 0])

    sc.tag("parallel edges")
    sc.build(2, box(2.0, 0.1, 0.1, "bar"), dump=False)
    for p in ([0, 0.3, 0], [0.5, 0.3, 0.001], [0, 0.2, 0.2], [3, 0.25, 0.25],
              [1.0, 0.2, 0.0], [0, 0, 0.2]):
        for f1, f2 in ((ref(2, 1, 0), ref(2, 1, 0)), (ref(2, 1, 4),
                                                      ref(2, 1, 9))):
            sc.op(OP_WIT_INIT, 2, 2, 2)
            sc.op(OP_WIT_SET, 2, f1, f2)
            sc.vclip(2, I, [0, 0, 0], I, [f32(c) for c in p])


def steps_section(sc):
    """VClip's checks one at a time, where the walk would hide which way a
    step went."""
    I = identity()
    # VV either side of the touch limit: two plates 2^-18 thick, so the gap
    # is exact.
    sc.tag("VV either side of the touch limit")
    hx = 2.0 ** -18
    sc.build(0, box(hx, 1.0, 1.0, "plate"), dump=False)
    sc.build(1, box(hx, 1.0, 1.0, "plate"), dump=False)
    sc.op(OP_WIT_INIT, 0, 0, 1)
    for gap in (1e-5, 5e-6, 1e-5 * 1.0000001, 2e-5, 0.0):
        t2 = [f32(2 * hx + f32(gap)), 2.0, 2.0]
        sc.op(OP_WIT_SET, 0, ref(0, 0, bv(1, 1, 1)), ref(1, 0, bv(-1, -1, -1)))
        sc.check(0, CK_VV, 0, I, [0, 0, 0], I, t2)
        sc.op(OP_WIT_SET, 0, ref(0, 0, bv(1, 1, 1)), ref(1, 0, bv(-1, -1, -1)))
        sc.vclip(0, I, [0, 0, 0], I, t2)

    sc.build(0, box(1.0, 1.0, 1.0), dump=False)
    sc.build(1, box(1.0, 1.0, 1.0), dump=False)
    sa, sb = sc.shapes[0], sc.shapes[1]
    top = face_of(sa, [0, 0, 1])
    sc.tag("VF either side of the touch limit")
    sc.op(OP_WIT_INIT, 1, 1, 0)
    for gap in (0.5, 5e-5, 0.5, 5e-7, 0.5, 2e-4, 0.5, 9.9e-5, 0.5, -5e-5):
        t1 = [f32(0.3 + 1), f32(0.2 + 1), f32(1 + gap + 1)]
        sc.op(OP_WIT_SET, 1, ref(1, 0, bv(-1, -1, -1)), ref(0, 2, top))
        sc.check(1, CK_VF, 0, I, t1, I, [0, 0, 0])

    sc.tag("VE: a turned box's edge across a corner")
    r45 = rotation([0, 0, 1], math.pi / 4)
    eB = edge_of(sb, bv(-1, -1, -1), bv(-1, 1, -1))
    sc.op(OP_WIT_INIT, 2, 0, 1)
    u = 0.001 / math.sqrt(2)
    for lift in (0.5, 0.0, 0.5, 0.002, 0.5, -0.0005):
        t2 = solve_t(r45, [-1, 0, -1], [1 + u, 1 + u, 1.001 + lift])
        sc.op(OP_WIT_SET, 2, ref(0, 0, bv(1, 1, 1)), ref(1, 1, eB))
        sc.check(2, CK_VE, 0, I, [0, 0, 0], r45, t2)
        sc.op(OP_WIT_SET, 2, ref(0, 0, bv(1, 1, 1)), ref(1, 1, eB))
        sc.vclip(2, I, [0, 0, 0], r45, t2)

    # Each after a VClip from further off, so a distance is there to keep
    sc.tag("EE: a turned box's corner on an edge")
    gA = edge_of(sa, bv(1, -1, 1), bv(1, 1, 1))
    eB2 = edge_of(sb, bv(-1, -1, -1), bv(1, -1, -1))
    sc.op(OP_WIT_INIT, 3, 0, 1)
    far = solve_t(r45, [-1, -1, -1], [1.0005, 0.0, 1.501])
    for lift in (0.0, 0.0015, 0.01):
        sc.op(OP_WIT_SET, 3, ref(0, 1, gA), ref(1, 1, eB2))
        sc.vclip(3, I, [0, 0, 0], r45, far)
        t2 = solve_t(r45, [-1, -1, -1], [1.0005, 0.0, 1.001 + lift])
        sc.op(OP_WIT_SET, 3, ref(0, 1, gA), ref(1, 1, eB2))
        sc.check(3, CK_EE, 0, I, [0, 0, 0], r45, t2)
        sc.op(OP_WIT_SET, 3, ref(1, 1, eB2), ref(0, 1, gA))
        sc.check(3, CK_EE, 1, I, [0, 0, 0], r45, t2)

    sc.tag("EF: a turned box's edge past a face's corner")
    rm = rotation([0, 0, 1], -math.pi / 4)
    sc.op(OP_WIT_INIT, 4, 0, 1)
    for delta, lift in ((0.0007, 0.5), (0.0007, 0.0), (0.0007, 0.5),
                        (0.0015, 0.0), (0.5, 0.0), (0.0003, 0.0)):
        t2 = solve_t(rm, [0, -1, -1], [1 + delta, 1 + delta, 1.0 + lift])
        sc.op(OP_WIT_SET, 4, ref(0, 2, top), ref(1, 1, eB2))
        sc.check(4, CK_EF, 1, I, [0, 0, 0], rm, t2)
        sc.op(OP_WIT_SET, 4, ref(0, 2, top), ref(1, 1, eB2))
        sc.vclip(4, I, [0, 0, 0], rm, t2)

    # The edge is P2's, so the check's first feature is F2: swapped
    sc.tag("EF: an edge beside a face, parallel and near parallel")
    sc.build(1, box(0.25, 1.5, 0.25, "stick"), dump=False)
    eS = edge_of(sc.shapes[1], bv(-1, -1, -1), bv(-1, 1, -1))
    sc.op(OP_WIT_INIT, 5, 0, 1)
    cases = []
    for th in (0.0, 1e-4, 1e-3, 0.02, 0.05, 0.08, -0.05):
        for x, z in ((1.01, 1.0), (1.25, 1.125), (1.2, 1.0001), (1.2, 1.1),
                     (1.05, 1.02), (1.3, 1.0003), (1.7, 1.001)):
            cases.append((th, x, z))
    for x in (1.1, 1.3000001, 1.9000001, 1.0100001, 1.5000001):
        for z in (1.0001, 1.001, 1.01, 1.1):
            cases.append((0.0, x, z))
    for th, x, z in cases:
        m = rotation([1, 0, 0], th) if th else I
        t1 = solve_t(m, [-0.25, 0, -0.25], [x, 0, z])
        sc.op(OP_WIT_SET, 5, ref(0, 2, top), ref(1, 1, eS))
        sc.check(5, CK_EF, 1, I, [0, 0, 0], m, t1)

    sc.tag("EE: bars side by side, parallel and near parallel")
    sc.build(0, box(2.0, 0.1, 0.1, "bar"), dump=False)
    sc.build(1, box(2.0, 0.1, 0.1, "bar"), dump=False)
    sbar = sc.shapes[0]
    eA = edge_of(sbar, bv(-1, 1, 1), bv(1, 1, 1))
    eBb = edge_of(sbar, bv(-1, -1, -1), bv(1, -1, -1))
    sc.op(OP_WIT_INIT, 6, 0, 1)
    for th in (0.0, 1e-4, 5e-4, 1e-3, 2e-3, 1e-2, 3e-2, 0.06, 0.09):
        m = rotation([0, 1, 1], th) if th else I
        for px, g in ((0.0, 0.1), (0.5, 0.1), (-1.3, 0.05), (1.9, 0.2)):
            t2 = solve_t(m, [0, -0.1, -0.1], [px, 0.1 + g, 0.1 + g])
            sc.op(OP_WIT_SET, 6, ref(0, 1, eA), ref(1, 1, eBb))
            sc.check(6, CK_EE, 0, I, [0, 0, 0], m, t2)

    # An octahedron's edges run along diagonals, stored as 5793 * 2^-13,
    # which is not unit length. An edge of a second octahedron laid beside
    # one of a face's edges is then parallel to it exactly as stored, and
    # which point of that edge's line CheckEdgeFace starts from moves both
    # the parallel lean and the foot on the line.
    sc.tag("EF: an edge exactly parallel to a face's diagonal edge")
    rnd = random.Random(11)
    sc.build(0, octa(1.0), dump=False)
    sa = sc.shapes[0]
    sc.op(OP_WIT_INIT, 7, 0, 1)
    for size in (0.5, 0.25, 1.0, 0.75):
        sc.build(1, octa(size), dump=False)
        sb = sc.shapes[1]
        for n in range(200):
            fi = rnd.randrange(len(sa.faces))
            gi = rnd.choice(sa.face_edges[fi])
            tg, hg, _, _ = sa.edges[gi]
            u = sa.dirs[gi]
            ei = rnd.choice([k for k, d in enumerate(sb.dirs)
                             if abs(abs(vdot(d, u)) - 1) < 1e-6])
            te, he, _, _ = sb.edges[ei]
            nrm = sa.normals[fi][0]
            out = vnorm(vcross(u, nrm))
            fc = [sum(sa.verts[i][k] for i in sa.faces[fi]) / 3
                  for k in range(3)]
            if vdot(out, vsub(sa.verts[tg], fc)) < 0:
                out = vscale(out, -1)
            glen = vdot(vsub(sa.verts[hg], sa.verts[tg]), u)
            elen = abs(vdot(vsub(sb.verts[he], sb.verts[te]), u))
            if rnd.random() < 0.5:
                # an end of e just either side of an end of g
                dl = rnd.uniform(-6e-4, 6e-4)
                along = (elen / 2 + dl if rnd.random() < 0.5
                         else glen - elen / 2 - dl)
            else:
                along = rnd.uniform(-0.3, glen + 0.3)
            d1 = rnd.choice((rnd.uniform(1e-5, 4e-4), rnd.uniform(1e-3, 0.05)))
            d2 = rnd.choice((rnd.uniform(-1e-4, 4e-4), rnd.uniform(0, 0.05),
                             0.0))
            target = [sa.verts[tg][k] + along * u[k] + d1 * out[k]
                      + d2 * nrm[k] for k in range(3)]
            emid = [(sb.verts[te][k] + sb.verts[he][k]) / 2 for k in range(3)]
            t2 = [f32(target[k] - emid[k]) for k in range(3)]
            sc.op(OP_WIT_SET, 7, ref(0, 2, fi), ref(1, 1, ei))
            sc.check(7, CK_EF, 1, I, [0, 0, 0], I, t2)


def walk_section(sc):
    sc.tag("a walk longer than the step limit")
    # A small box beside a hundred-sided wafer, starting from the far side:
    # the walk goes round the rim a feature at a time, which takes more than
    # the 80 steps one call allows, so the call stops mid-walk and the next
    # carries on from there.
    sc.build(0, wafer(100, 10.0, 0.5), dump=False)
    sc.build(1, box(0.2, 0.2, 0.2), dump=False)
    I = identity()
    for p, f1, f2 in (([-11.0, 0.3, 0.1], ref(0, 0, 0), ref(1, 0, 0)),
                      ([0.5, -10.8, 0.0], ref(0, 0, 0), ref(1, 0, 0)),
                      ([-10.7, -0.2, 2.0], ref(0, 2, 2), ref(1, 1, 3)),
                      ([-11.0, 0.3, 0.1], ref(0, 1, 0), ref(1, 2, 0)),
                      ([-10.9, 0.05, -1.0], ref(0, 2, 60), ref(1, 0, 7))):
        sc.op(OP_WIT_INIT, 3, 0, 1)
        sc.op(OP_WIT_SET, 3, f1, f2)
        for _ in range(4):
            sc.vclip(3, I, [0, 0, 0], I, [f32(c) for c in p])


def random_section(sc, rnd, count):
    sc.tag("random poses")
    shapes = [mk() for mk in SHAPES]
    order = list(range(len(shapes)))
    for k in range(4):
        sc.build(4 + k, shapes[order[k]], dump=False)
    for k in range(4):
        sc.build(k, shapes[order[4 + k]], dump=False)
    for n in range(count):
        a, b = rnd.randrange(NPOLY), rnd.randrange(NPOLY)
        m1 = rand_rotation(rnd) if rnd.random() < 0.8 else identity()
        m2 = rand_rotation(rnd)
        if rnd.random() < 0.1:
            m1 = [row[:] for row in m1]
            m1[3] = [f32(rnd.uniform(-1, 1)) for _ in range(3)] + [1.0]
        if rnd.random() < 0.05:
            m2 = [row[:] for row in m2]
            for r in range(3):
                m2[r][3] = f32(rnd.uniform(-0.5, 0.5))
        t1 = [f32(rnd.uniform(-5, 5)) for _ in range(3)]
        d = rnd.choice([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 8.0])
        dirn = vnorm([rnd.gauss(0, 1) for _ in range(3)])
        t2 = [f32(t1[k] + dirn[k] * d) for k in range(3)]
        w = rnd.randrange(NWIT)
        sc.op(OP_WIT_INIT, w, a, b)
        if rnd.random() < 0.6:
            # A face against a face is a pair no check takes (VClip spins
            # out its 80 steps); a few of those are plenty.
            fa, fb_ = rnd.choice(sc.features(a)), rnd.choice(sc.features(b))
            while (((fa >> 16) & 0xFF) == 2 and ((fb_ >> 16) & 0xFF) == 2
                   and rnd.random() < 0.9):
                fb_ = rnd.choice(sc.features(b))
            sc.op(OP_WIT_SET, w, fa, fb_)
        sc.vclip(w, m1, t1, m2, t2)
        # coherence: the next few calls start from this one's answer
        for _ in range(rnd.choice([0, 0, 1, 3])):
            t2 = [f32(c + rnd.uniform(-0.2, 0.2)) for c in t2]
            m2 = rotation([rnd.gauss(0, 1) for _ in range(3)],
                          rnd.uniform(-0.3, 0.3)) if rnd.random() < 0.3 \
                else m2
            sc.vclip(w, m1, t1, m2, t2)


def plot_section(sc):
    sc.tag("plots")
    sc.build(0, box(1.0, 1.0, 1.0), dump=False)
    sc.build(1, tetra(1.0), dump=False)
    sc.build(2, pyramid(1.0, 1.0), dump=False)
    m = rotation([1, 2, 3], 0.4)
    m = [row[:] for row in m]
    m[3] = [1.5, -2.0, 0.25, 1.0]
    sc.op(OP_POLY_PLOT, 0, mwords(m))
    sc.op(OP_POLY_PLOT, 0, mwords(JUNK_M))
    sc.op(OP_POLY_PLOT, 2, mwords(m))
    sc.op(OP_ESP_NULL, 1)
    sc.op(OP_POLY_PLOT, 1, mwords(m))
    sc.op(OP_POLY_PLOT, 1, mwords(m))
    sc.op(OP_DUMP_POLY, 1)
    for r in sc.features(0) + sc.features(1) + sc.features(2):
        sc.op(OP_MESH_FACE, r, mwords(m))
    sc.build(3, wafer(8, 1.0, 0.2), dump=False)
    sc.op(OP_MESH_FACE, ref(3, 2, 0), mwords(m))
    sc.op(OP_MESH_FACE, ref(3, 2, 1), mwords(JUNK_M))
    sc.op(OP_MESH_FACE, ref(3, 2, 2), mwords(m))

    sc.op(OP_WIT_INIT, 0, 0, 1)
    sc.op(OP_WIT_PLOT, 0, mwords(m), mwords(JUNK_M))
    sc.op(OP_WIT_SET, 0, ref(0, 1, 2), ref(1, 2, 3))
    sc.op(OP_WIT_PLOT, 0, mwords(JUNK_M), mwords(m))
    sc.op(OP_WIT_DESTROY, 0, 0)
    sc.op(OP_WIT_DESTROY, 0, 0)
    sc.op(OP_ESP_NULL, 2)
    sc.op(OP_WIT_INIT, 1, 2, 0)
    sc.op(OP_WIT_PLOT, 1, mwords(m), mwords(m))
    sc.op(OP_ESP_NULL, 1)
    sc.op(OP_WIT_PLOT, 1, mwords(m), mwords(m))
    sc.op(OP_WIT_DESTROY, 1, 1)
    sc.op(OP_CLOSE, 0)
    sc.op(OP_CLOSE, 2)

    sc.tag("the debug switches")
    sc.build(0, box(1.0, 1.0, 1.0), dump=False)
    sc.op(OP_PRINT, 1)
    sc.op(OP_FLAGS, 1, 0)
    sc.op(OP_WIT_INIT, 2, 1, 0)
    sc.vclip(2, identity(), [0, 0, 0], identity(), [3, 0.5, 0])
    sc.op(OP_FLAGS, 0, 1)
    sc.op(OP_WIT_INIT, 2, 0, 1)
    sc.vclip(2, identity(), [0, 0, 0], identity(), [3, 0.5, 0])
    sc.op(OP_FLAGS, 0, 0)


def script(count=900):
    rnd = random.Random(20260925)
    sc = Script()
    api_section(sc)
    shapes_section(sc, rnd)
    codes_section(sc)
    transform_section(sc, rnd)
    clip_section(sc, rnd)
    contact_section(sc)
    walk_section(sc)
    random_section(sc, rnd, count)
    plot_section(sc)
    # after the rest, each on its own sequence, so the sections above see
    # the same numbers they always did
    clip_limits_section(sc)
    steps_section(sc)
    return sc


# ================================================================ the model

SYM = {
    "ctor": "__12VCPolyhedron",
    "init_alloc": "Init__12VCPolyhedroniiii",
    "init_arrays":
        "Init__12VCPolyhedronP8VCVertexiP6VCEdgeiP6VCFaceiP14VCVoronoiPlanei",
    "dtor": "_$_12VCPolyhedron",
    "close": "Close__12VCPolyhedron",
    "mi_load": "MemoryImageLoad__12VCPolyhedronP8VCVertexiP6VCEdgeiP6VCFacei"
               "P14VCVoronoiPlanei",
    "mi_unload": "MemoryImageUnload__12VCPolyhedron",
    "new_planes": "NewVoronoiPlanes__12VCPolyhedroni",
    "new_vertex": "NewVertex__12VCPolyhedronP8bVector3iP14VCVoronoiPlane",
    "new_edge": "NewEdge__12VCPolyhedronP8bVector3iP14VCVoronoiPlane",
    "new_face": "NewFace__12VCPolyhedronP8bVector3fiP14VCVoronoiPlane",
    "mesh_face": "CreateUserMeshFace__9VCFeatureP11FloatVectorP8bMatrix4",
    "poly_plot": "PlotToCaffeine__12VCPolyhedronP8bMatrix4",
    "wit_plot": "PlotToCaffeine__9VCWitnessP8bMatrix4T1",
    "poly_voronoi": "SetVoronoiPlanes__12VCPolyhedron",
    "v_voronoi": "SetVoronoiPlanes__8VCVertex",
    "e_voronoi": "SetVoronoiPlanes__6VCEdge",
    "f_voronoi": "SetVoronoiPlanes__6VCFace",
    "next_edge": "GetNextEdgeInFace__8VCVertexP6VCEdgeP6VCFace",
    "v_move": "Move__8VCVertexP8bVector3",
    "f_move": "Move__6VCFaceP8bVector3",
    "get_code": "GetFeatureCode__12VCPolyhedronP9VCFeature",
    "get_feature": "GetFeature__12VCPolyhedronUi",
    "to_indices": "ConvertToIndicies__12VCPolyhedron",
    "to_pointers": "ConvertToPointers__12VCPolyhedron",
    "print": "Print__12VCPolyhedron",
    "wit_ctor": "__9VCWitnessP12VCPolyhedronT1",
    "wit_dtor": "_$_9VCWitness",
    "vclip": "VClip__9VCWitnessP8bMatrix4P8bVector3T1T2",
    "x_ctor": "__11VCTransformP8bMatrix4P8bVector3T1T2",
    "x_vec_p": "TransformVector__11VCTransformP8bVector3T1",
    "x_vec": "TransformVector__11VCTransformG8fVector3",
    "x_pt": "TransformPoint__11VCTransformG8fVector3",
    "xf_vertex": "TransformVertex__20VCTransformedFeatureP11VCTransformP8VCVertex",
    "xf_edge": "TransformEdge__20VCTransformedFeatureP11VCTransformP6VCEdge",
    "clip_ctor": "__13VCVoronoiClip",
    "clip_planes": "ClipPlanes__13VCVoronoiClipP20VCTransformedFeature"
                   "P14VCVoronoiPlanei",
    "clip_vert": "ClipVertexPlanes__13VCVoronoiClipP20VCTransformedFeature"
                 "P8bVector3P14VCVoronoiPlanei",
    "clip_face": "ClipFacePlanes__13VCVoronoiClipP20VCTransformedFeature"
                 "P6VCFaceP14VCVoronoiPlanei",
    "dist": "fDistBetween__FG8fVector3T0",
    "check_vv":
        "CheckVertexVertex__9VCWitnessP11VCTransformT1P20VCTransformedFeatureT3",
    "check_ve":
        "CheckVertexEdge__9VCWitnessP11VCTransformT1P20VCTransformedFeatureT3",
    "check_vf":
        "CheckVertexFace__9VCWitnessP11VCTransformT1P20VCTransformedFeatureT3",
    "check_ee":
        "CheckEdgeEdge__9VCWitnessP11VCTransformT1P20VCTransformedFeatureT3",
    "check_ef":
        "CheckEdgeFace__9VCWitnessP11VCTransformT1P20VCTransformedFeatureT3",
}

# OP_CHECK's kinds, in the harness's order.
CHECKS = ("check_vv", "check_ve", "check_vf", "check_ee", "check_ef")
CK_VV, CK_VE, CK_VF, CK_EE, CK_EF = range(5)

KINDS = ("vertices", "edges", "faces", "planes")
RECS = (SIZE_V, SIZE_E, SIZE_F, SIZE_PL)


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.polys = [e.alloc(48, 16) for _ in range(NPOLY)]
        self.wits = [e.alloc(80, 16) for _ in range(NWIT)]
        self.X = e.alloc(64, 16)
        self.XF = e.alloc(64, 16)
        self.C = e.alloc(32, 16)
        self.scratch = e.alloc(512, 16)
        self.step = [e.alloc(64, 16) for _ in range(4)]   # x12 x21 xf1 xf2
        self.mesh = e.alloc(12 * 128, 16)
        self.dead = [False] * NPOLY
        self.tainted = [[False, False] for _ in range(NWIT)]
        self.allocs = []
        self.next_handle = 1
        self.null_creates = 0
        emit = self.out.append

        def malloc(em):
            size, pool = s32(em.reg[4]), s32(em.reg[5])
            k = len(self.allocs) % 4
            p = em.alloc(max(size, 16), 16)
            if size % RECS[k]:
                emit("  malloc #%d %s %d bytes? pool %d"
                     % (len(self.allocs), KINDS[k], size, pool))
            else:
                emit("  malloc #%d %s x%d pool %d"
                     % (len(self.allocs), KINDS[k], size // RECS[k], pool))
            self.allocs.append(p)
            return p

        def free(em):
            p = em.reg[4] & M32
            if p == 0:
                emit("  free null")
                return 0
            if p in self.allocs:
                i = self.allocs.index(p)
                emit("  free #%d" % i)
                self.allocs[i] = None
            elif p in self.polys:
                emit("  free poly %d" % self.polys.index(p))
            elif p in self.wits:
                emit("  free wit %d" % self.wits.index(p))
            else:
                emit("  free ?")
            return 0

        e.stub("bMalloc__Fii", malloc)
        e.stub("bFree__FPv", free)

        def cstr(a):
            s = []
            while e.mem[a]:
                s.append(chr(e.mem[a]))
                a += 1
            return "".join(s)

        def create(em):
            layer, typ = cstr(em.reg[4] & M32), cstr(em.reg[5] & M32)
            if self.null_creates > 0:
                self.null_creates -= 1
                h = 0
            else:
                h = self.next_handle
                self.next_handle += 1
            emit("  esp create %s %s -> %d" % (layer, typ, h))
            return h

        def delete(em):
            emit("  esp delete %d" % (em.reg[4] & M32))

        def mesh(em):
            emit("  esp mesh %d %d" % (em.reg[4] & M32, s32(em.reg[5])))

        def face(em):
            a = em.reg[6] & M32
            emit("  esp face %d %d " % (em.reg[4] & M32, s32(em.reg[5]))
                 + " ".join("%08x" % em.u32(a + 4 * k) for k in range(12)))

        def pos(em):
            a = em.reg[5] & M32
            emit("  esp pos %d " % (em.reg[4] & M32)
                 + " ".join("%08x" % em.u32(a + 4 * k) for k in range(3)))

        e.stub("espCreateObject__FPCcT0", create)
        e.stub("espDeleteObject__FUi", delete)
        e.stub("espCreateUserMesh__FUii", mesh)
        e.stub("espSetUserMeshFace__FUiiP11FloatVector", face)
        e.stub("espSetObjectPosition__FUiP11FloatVector", pos)

    # ---- memory helpers

    def s16at(self, a):
        return s16(self.e.u16(a))

    def put_words(self, a, ws):
        for k, w in enumerate(ws):
            self.e.put32(a + 4 * k, w)

    def call(self, name, *args):
        return self.e.call(self.fn[name], *args)

    def ptr(self, name, *args):
        self.e.call(self.fn[name], *args)
        return self.e.reg[2] & M32

    # ---- naming

    def in_array(self, a, base, count, size):
        if base == 0 or count <= 0 or a < base or a >= base + count * size:
            return None
        if (a - base) % size:
            return -1
        return (a - base) // size

    def name_feature(self, a):
        if a == 0:
            return "null"
        e = self.e
        for i, p in enumerate(self.polys):
            if self.dead[i]:
                continue
            for k, (boff, moff) in enumerate(((32, 24), (36, 26), (40, 28))):
                idx = self.in_array(a, e.u32(p + boff), self.s16at(p + moff),
                                    KIND_SIZE[k])
                if idx is not None:
                    if idx < 0:
                        return "p%d.%s?" % (i, KIND_CHAR[k])
                    return "p%d.%s%d" % (i, KIND_CHAR[k], idx)
        return "?"

    def name_planes(self, p, a):
        if a == 0:
            return "null"
        idx = self.in_array(a, self.e.u32(p + 44), self.s16at(p + 30),
                            SIZE_PL)
        if idx is not None and idx >= 0:
            return "pl%d" % idx
        return "?"

    def name_poly(self, a):
        if a == 0:
            return "null"
        if a in self.polys:
            return "%d" % self.polys.index(a)
        return "?"

    def resolve(self, r):
        if r == NO_REF:
            return 0
        p = self.polys[(r >> 24) & 7]
        kind = (r >> 16) & 0xFF
        idx = r & 0xFFFF
        if kind == 0:
            return self.e.u32(p + 32) + idx * SIZE_V
        if kind == 1:
            return self.e.u32(p + 36) + idx * SIZE_E
        return self.e.u32(p + 40) + idx * SIZE_F

    # ---- dumps

    def dump_poly(self, i):
        e, p, out = self.e, self.polys[i], self.out
        num = [self.s16at(p + 16 + 2 * k) for k in range(4)]
        mx = [self.s16at(p + 24 + 2 * k) for k in range(4)]
        arr = [e.u32(p + 32 + 4 * k) for k in range(4)]
        out.append("  poly %d num %d %d %d %d max %d %d %d %d dyn %d obj %d "
                   "arr %s" % tuple([i] + num + mx + [s32(e.u32(p + 8)),
                                                       e.u32(p + 12),
                                                       "".join("1" if a else "0"
                                                               for a in arr)]))
        if arr[0]:
            for k in range(num[0]):
                a = arr[0] + k * SIZE_V
                out.append("  v%d t%d n%d %s pos %08x %08x %08x"
                           % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                              self.name_planes(p, e.u32(a + 16)),
                              e.u32(a + 4), e.u32(a + 8), e.u32(a + 12)))
        if arr[1]:
            for k in range(num[1]):
                a = arr[1] + k * SIZE_E
                out.append("  e%d t%d n%d %s dir %d %d %d"
                           % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                              self.name_planes(p, e.u32(a + 8)),
                              self.s16at(a + 2), self.s16at(a + 4),
                              self.s16at(a + 6)))
        if arr[2]:
            for k in range(num[2]):
                a = arr[2] + k * SIZE_F
                out.append("  f%d t%d n%d %s plane %08x %08x %08x %08x"
                           % (k, s8(e.mem[a]), s8(e.mem[a + 1]),
                              self.name_planes(p, e.u32(a + 20)),
                              e.u32(a + 4), e.u32(a + 8), e.u32(a + 12),
                              e.u32(a + 16)))
        if arr[3]:
            for k in range(num[3]):
                a = arr[3] + k * SIZE_PL
                out.append("  pl%d %08x %08x %08x %08x nb %s"
                           % (k, e.u32(a + 4), e.u32(a + 8), e.u32(a + 12),
                              e.u32(a + 16), self.name_feature(e.u32(a + 20))))

    def dump_raw(self, i):
        e, p = self.e, self.polys[i]
        num = [self.s16at(p + 16 + 2 * k) for k in range(4)]
        arr = [e.u32(p + 32 + 4 * k) for k in range(4)]
        parts = []
        for k, (size, off) in enumerate(((SIZE_V, 16), (SIZE_E, 8),
                                         (SIZE_F, 20), (SIZE_PL, 20))):
            parts.append("".join(" %x" % e.u32(arr[k] + j * size + off)
                                 for j in range(num[k])))
        self.out.append("  raw %d" % i + " |".join(parts))

    def dump_wit(self, i, status):
        e, w = self.e, self.wits[i]
        f1, f2 = e.u32(w + 4), e.u32(w + 8)
        t1 = s8(e.mem[f1]) if f1 else -1
        t2 = s8(e.mem[f2]) if f2 else -1
        ss = s32(e.u32(w))
        m1, m2 = self.tainted[i]
        if t1 == 0 and t2 == 0 and status in (1, 2):
            m1 = m2 = True
        if status == 2 and (t1, t2) in ((0, 1), (1, 0)):
            if ss == 1:
                m1 = True
            else:
                m2 = True
        self.tainted[i] = [m1, m2]

        def cp(a, masked):
            return "%08x %08x %08x %s" % (
                e.u32(a), e.u32(a + 4), e.u32(a + 8),
                "--------" if masked else "%08x" % e.u32(a + 12))
        self.out.append(
            "  wit %d ss %d f1 %s f2 %s p %s %s cp1 %s cp2 %s dist %08x "
            "obj %d %d" % (i, ss, self.name_feature(f1),
                           self.name_feature(f2),
                           self.name_poly(e.u32(w + 12)),
                           self.name_poly(e.u32(w + 16)),
                           cp(w + 32, m1), cp(w + 48, m2), e.u32(w + 64),
                           e.u32(w + 68), e.u32(w + 72)))

    def vtext(self, label, ws):
        return " %s %08x %08x %08x %08x" % ((label,) + tuple(ws))

    def dump_xf(self):
        e, a = self.e, self.XF
        self.out.append(
            "  xf %s" % self.name_feature(e.u32(a))
            + self.vtext("head", [e.u32(a + 16 + 4 * k) for k in range(4)])
            + self.vtext("tail", [e.u32(a + 32 + 4 * k) for k in range(4)])
            + self.vtext("edge", [e.u32(a + 48 + 4 * k) for k in range(4)]))

    def dump_clip(self):
        e, c = self.e, self.C
        self.out.append("  clip %08x %08x %s %s %d"
                        % (e.u32(c), e.u32(c + 4),
                           self.name_feature(e.u32(c + 8)),
                           self.name_feature(e.u32(c + 12)),
                           s32(e.u32(c + 16))))

    # ---- the run

    def run(self):
        e, w, out = self.e, self.sc.words, self.out
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        def args(n):
            nonlocal i
            i += n
            return w[i - n:i]

        def quad(ws):
            return ws[0] | (ws[1] << 32) | (ws[2] << 64) | (ws[3] << 96)

        def lanes(v):
            return [(v >> (32 * k)) & M32 for k in range(4)]

        S = self.scratch
        while i < len(w):
            op = arg()
            if op == OP_TAG:
                out.append("[%d]" % arg())
            elif op == OP_POLY_CTOR:
                pi = arg()
                r = self.ptr("ctor", self.polys[pi])
                out.append("ctor %d -> %s" % (pi, self.name_poly(r)))
                self.dead[pi] = False
                self.dump_poly(pi)
            elif op == OP_POLY_ALLOC:
                pi = arg()
                a = [s32(x) for x in args(4)]
                out.append("alloc %d %d %d %d %d" % tuple([pi] + a))
                self.call("init_alloc", self.polys[pi], *a)
                self.dump_poly(pi)
            elif op == OP_POLY_ARRAYS:
                pi = arg()
                a = [s32(x) for x in args(4)]
                out.append("arrays %d %d %d %d %d" % tuple([pi] + a))
                arrs = [e.alloc((a[k] + 1) * RECS[k], 16) for k in range(4)]
                e.put32(e.reg[29], a[3])
                self.call("init_arrays", self.polys[pi], arrs[0], a[0],
                          arrs[1], a[1], arrs[2], a[2], arrs[3])
                self.dump_poly(pi)
            elif op == OP_NEW_PLANES:
                pi = arg()
                n = s32(arg())
                p = self.polys[pi]
                r = self.ptr("new_planes", p, n)
                out.append("planes %d -> %s num %d"
                           % (n, self.name_planes(p, r), self.s16at(p + 22)))
            elif op in (OP_NEW_VERTEX, OP_NEW_EDGE):
                pi = arg()
                v = args(4)
                n = s32(arg())
                pl = arg()
                p = self.polys[pi]
                self.put_words(S, v)
                pla = 0 if pl == NO_REF else e.u32(p + 44) + pl * SIZE_PL
                if op == OP_NEW_VERTEX:
                    r = self.ptr("new_vertex", p, S, n, pla)
                    out.append("vertex -> %s" % self.name_feature(r))
                else:
                    r = self.ptr("new_edge", p, S, n, pla)
                    out.append("edge -> %s" % self.name_feature(r))
            elif op == OP_NEW_FACE:
                pi = arg()
                v = args(4)
                d = arg()
                n = s32(arg())
                pl = arg()
                p = self.polys[pi]
                self.put_words(S, v)
                pla = 0 if pl == NO_REF else e.u32(p + 44) + pl * SIZE_PL
                e.fpr[12] = d
                r = self.ptr("new_face", p, S, n, pla)
                out.append("face -> %s" % self.name_feature(r))
            elif op == OP_SET_NB:
                pi = arg()
                idx = arg()
                r = arg()
                p = self.polys[pi]
                e.put32(e.u32(p + 44) + idx * SIZE_PL + 20, self.resolve(r))
            elif op == OP_SET_VORONOI:
                pi = arg()
                out.append("set voronoi %d" % pi)
                self.call("poly_voronoi", self.polys[pi])
            elif op == OP_SET_VORONOI_ONE:
                a = self.resolve(arg())
                out.append("set voronoi %s" % self.name_feature(a))
                t = s8(e.mem[a])
                self.call("v_voronoi" if t == 0 else
                          "e_voronoi" if t == 1 else "f_voronoi", a)
            elif op == OP_DUMP_POLY:
                self.dump_poly(arg())
            elif op in (OP_MOVE_VERTEX, OP_MOVE_FACE):
                a = self.resolve(arg())
                self.put_words(S, args(4))
                out.append("move %s" % self.name_feature(a))
                self.call("v_move" if op == OP_MOVE_VERTEX else "f_move", a, S)
            elif op == OP_NEXT_EDGE:
                v, last, f = (self.resolve(x) for x in args(3))
                r = self.ptr("next_edge", v, last, f)
                out.append("next edge %s %s %s -> %s"
                           % (self.name_feature(v), self.name_feature(last),
                              self.name_feature(f), self.name_feature(r)))
            elif op == OP_GET_CODE:
                p = self.polys[arg()]
                a = self.resolve(arg())
                r = self.ptr("get_code", p, a)
                out.append("code %s -> %08x" % (self.name_feature(a), r))
            elif op == OP_GET_FEATURE:
                p = self.polys[arg()]
                code = arg()
                r = self.ptr("get_feature", p, code)
                out.append("feature %08x -> %s"
                           % (code, self.name_feature(r)))
            elif op == OP_POKE_TYPE:
                a = self.resolve(arg())
                e.mem[a] = arg() & 0xFF
            elif op == OP_TO_INDICES:
                pi = arg()
                out.append("to indices %d" % pi)
                self.call("to_indices", self.polys[pi])
                self.dump_raw(pi)
            elif op == OP_TO_POINTERS:
                pi = arg()
                out.append("to pointers %d" % pi)
                self.call("to_pointers", self.polys[pi])
            elif op == OP_DUMP_RAW:
                self.dump_raw(arg())
            elif op == OP_MEMIMAGE_LOAD:
                d, s = arg(), arg()
                src = self.polys[s]
                out.append("memimage %d from %d" % (d, s))
                self.dead[s] = True
                num = [self.s16at(src + 16 + 2 * k) for k in range(4)]
                arr = [e.u32(src + 32 + 4 * k) for k in range(4)]
                e.put32(e.reg[29], num[3])
                self.call("mi_load", self.polys[d], arr[0], num[0], arr[1],
                          num[1], arr[2], num[2], arr[3])
                self.dump_poly(d)
            elif op == OP_UNLOAD:
                pi = arg()
                out.append("unload %d" % pi)
                self.call("mi_unload", self.polys[pi])
                self.dump_poly(pi)
            elif op == OP_CLOSE:
                pi = arg()
                out.append("close %d" % pi)
                self.call("close", self.polys[pi])
                self.dump_poly(pi)
            elif op == OP_DESTROY:
                pi = arg()
                flags = s32(arg())
                out.append("destroy %d %d" % (pi, flags))
                self.call("dtor", self.polys[pi], flags)
                self.dump_poly(pi)
            elif op == OP_WIT_INIT:
                wi, a, b = arg(), arg(), arg()
                out.append("witness %d %d %d" % (wi, a, b))
                self.call("wit_ctor", self.wits[wi], self.polys[a],
                          self.polys[b])
                self.dump_wit(wi, -1)
            elif op == OP_WIT_SET:
                wi = arg()
                e.put32(self.wits[wi] + 4, self.resolve(arg()))
                e.put32(self.wits[wi] + 8, self.resolve(arg()))
            elif op == OP_VCLIP:
                wi = arg()
                self.put_words(S, args(16))
                self.put_words(S + 64, args(4))
                self.put_words(S + 128, args(16))
                self.put_words(S + 192, args(4))
                wa = self.wits[wi]
                e.put32(wa + 44, CP_SENTINEL)
                e.put32(wa + 60, CP_SENTINEL)
                self.tainted[wi] = [False, False]
                st = self.call("vclip", wa, S, S + 64, S + 128, S + 192)
                out.append("vclip %d -> %d printing %s"
                           % (wi, st, self.name_poly(e.u32(G_PRINTING))))
                self.dump_wit(wi, st)
            elif op == OP_DUMP_WIT:
                self.dump_wit(arg(), -1)
            elif op == OP_CHECK:
                wi, kind, swap = arg(), arg(), arg()
                self.put_words(S, args(16))
                self.put_words(S + 64, args(4))
                self.put_words(S + 128, args(16))
                self.put_words(S + 192, args(4))
                x12, x21, xf1, xf2 = self.step
                self.put_words(xf1, [0] * 16)
                self.put_words(xf2, [0] * 16)
                self.call("x_ctor", x12, S + 128, S + 192, S, S + 64)
                self.call("x_ctor", x21, S, S + 64, S + 128, S + 192)
                wa = self.wits[wi]
                e.put32(wa, 2 if swap else 1)
                e.put32(wa + 44, CP_SENTINEL)
                e.put32(wa + 60, CP_SENTINEL)
                self.tainted[wi] = [False, False]
                if swap:
                    st = self.call(CHECKS[kind], wa, x21, x12, xf2, xf1)
                else:
                    st = self.call(CHECKS[kind], wa, x12, x21, xf1, xf2)
                out.append("check %d %d %d -> %d" % (wi, kind, swap, st))
                self.dump_wit(wi, st)
            elif op == OP_WIT_DESTROY:
                wi = arg()
                flags = s32(arg())
                out.append("wit destroy %d %d" % (wi, flags))
                self.call("wit_dtor", self.wits[wi], flags)
                self.dump_wit(wi, -1)
            elif op == OP_WIT_PLOT:
                wi = arg()
                self.put_words(S, args(16))
                self.put_words(S + 64, args(16))
                out.append("wit plot %d" % wi)
                self.call("wit_plot", self.wits[wi], S, S + 64)
                self.dump_wit(wi, -1)
            elif op == OP_POLY_PLOT:
                pi = arg()
                self.put_words(S, args(16))
                out.append("poly plot %d" % pi)
                self.call("poly_plot", self.polys[pi], S)
                out.append("  obj %d" % e.u32(self.polys[pi] + 12))
            elif op == OP_ESP_NULL:
                self.null_creates = s32(arg())
            elif op == OP_MESH_FACE:
                a = self.resolve(arg())
                self.put_words(S, args(16))
                for k in range(128):
                    for j in range(3):
                        e.put32(self.mesh + 12 * k + 4 * j, 0x7f7f0001 + k)
                n = 4
                if s8(e.mem[a]) == 2 and s8(e.mem[a + 1]) > 4:
                    n = s8(e.mem[a + 1])
                self.call("mesh_face", a, self.mesh, S)
                out.append("mesh %s " % self.name_feature(a) + " ".join(
                    "%08x" % e.u32(self.mesh + 4 * k) for k in range(3 * n)))
            elif op == OP_XFORM:
                self.put_words(S, args(16))
                self.put_words(S + 64, args(4))
                self.put_words(S + 128, args(16))
                self.put_words(S + 192, args(4))
                out.append("xform")
                self.call("x_ctor", self.X, S, S + 64, S + 128, S + 192)
                out.append("  x " + " ".join("%08x" % e.u32(self.X + 4 * k)
                                             for k in range(16)))
            elif op in (OP_XVEC, OP_XPT):
                v = args(4)
                e.reg[5] = quad(v)
                e.call(self.fn["x_vec" if op == OP_XVEC else "x_pt"], self.X)
                out.append(("xvec" if op == OP_XVEC else "xpt")
                           + self.vtext("->", lanes(e.reg[2] & M128)))
            elif op == OP_XVECP:
                self.put_words(S, args(4))
                self.put_words(S + 16, [0x7f7f7f7f] * 4)
                self.call("x_vec_p", self.X, S + 16, S)
                out.append("xvecp" + self.vtext(
                    "->", [e.u32(S + 16 + 4 * k) for k in range(4)]))
            elif op == OP_DIST:
                a, b = args(4), args(4)
                e.reg[4] = quad(a)
                e.reg[5] = quad(b)
                e.call(self.fn["dist"])
                out.append("dist -> %08x" % (e.reg[2] & M32))
            elif op == OP_XF_SET:
                self.put_words(self.XF, [0, 0, 0, 0])
                self.put_words(self.XF + 16, args(12))
            elif op in (OP_XF_EDGE, OP_XF_VERTEX):
                a = self.resolve(arg())
                if op == OP_XF_EDGE:
                    out.append("xf edge")
                    self.call("xf_edge", self.XF, self.X, a)
                else:
                    out.append("xf vertex")
                    self.call("xf_vertex", self.XF, self.X, a)
                self.dump_xf()
            elif op == OP_CLIP_INIT:
                out.append("clip init")
                self.call("clip_ctor", self.C)
                self.dump_clip()
            elif op == OP_CLIP_SET:
                lmin, lmax = arg(), arg()
                nmin, nmax = self.resolve(arg()), self.resolve(arg())
                self.put_words(self.C, [lmin, lmax, nmin, nmax, arg()])
            elif op == OP_CLIP_PLANES:
                p = self.polys[arg()]
                first = arg()
                n = s32(arg())
                pl = e.u32(p + 44) + first * SIZE_PL
                r = self.call("clip_planes", self.C, self.XF, pl, n)
                out.append("clip planes -> %d" % r)
                self.dump_clip()
            elif op == OP_CLIP_VERT:
                p = self.polys[arg()]
                first = arg()
                n = s32(arg())
                has = arg()
                self.put_words(S, args(4))
                pl = e.u32(p + 44) + first * SIZE_PL
                r = self.ptr("clip_vert", self.C, self.XF, S if has else 0,
                             pl, n)
                out.append("clip vert -> %s" % self.name_feature(r))
                self.dump_clip()
            elif op == OP_CLIP_FACE:
                p = self.polys[arg()]
                first = arg()
                n = s32(arg())
                f = self.resolve(arg())
                pl = e.u32(p + 44) + first * SIZE_PL
                r = self.ptr("clip_face", self.C, self.XF, f, pl, n)
                out.append("clip face -> %s" % self.name_feature(r))
                self.dump_clip()
            elif op == OP_FLAGS:
                e.put32(G_PRINT_THIS_TIME, arg())
                e.put32(G_PLOT_CLOSEST, arg())
            elif op == OP_PRINT:
                pi = arg()
                self.call("print", self.polys[pi])
                out.append("print %d printing %s"
                           % (pi, self.name_poly(e.u32(G_PRINTING))))
            else:
                raise SystemExit("op %d" % op)
        return out


def model(sc):
    return Model(sc).run()


# ---------------------------------------------------------------- running

HARNESS_TIMEOUT = 120
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
                print(line)
    return bad


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.

VH = "3DS Files/source/vclip.h"


def _m(name, old, new, rel=VC):
    return (name, rel, old, new)


def _lines(*ls):
    return NL.join(ls)


MUTATIONS = [
    # ------------------------------------------------ the helpers
    _m("vpos-pad", _lines("    r.z = v->CompressedPosition[2];",
                          "    r.pad = 0.0f;"),
       _lines("    r.z = v->CompressedPosition[2];", "    r.pad = 1.0f;")),
    _m("dir-scale", "VC_DIRECTION_SCALE    1.22070312e-04f",
       "VC_DIRECTION_SCALE    1.2207e-04f", VH),
    _m("dir-y-from-z",
       "r.y = (float)e->CompressedDirection[1] * VC_DIRECTION_SCALE;",
       "r.y = (float)e->CompressedDirection[2] * VC_DIRECTION_SCALE;"),
    _m("dot3-regrouped", "return (a->x * b->x + a->y * b->y) + a->z * b->z;",
       "return a->x * b->x + (a->y * b->y + a->z * b->z);"),
    _m("normal-dot-regrouped",
       _lines("return (pl->CompressedNormal[0] * v->x"
              " + pl->CompressedNormal[1] * v->y)",
              "        + pl->CompressedNormal[2] * v->z;"),
       _lines("return pl->CompressedNormal[0] * v->x"
              " + (pl->CompressedNormal[1] * v->y",
              "        + pl->CompressedNormal[2] * v->z);")),
    _m("plane-dist-plus",
       "return normal_dot(pl, p) - pl->CompressedPlaneDistance;",
       "return normal_dot(pl, p) + pl->CompressedPlaneDistance;"),
    _m("len-sq-regrouped", "return (d->x * d->x + d->y * d->y) + d->z * d->z;",
       "return d->x * d->x + (d->y * d->y + d->z * d->z);"),
    _m("zero-minus-negates", "    r.x = 0.0f - v->x;", "    r.x = -v->x;"),
    _m("point-at-z-from-head", "r.z = xe->Edge.z * lambda + xe->Tail.z;",
       "r.z = xe->Edge.z * lambda + xe->Head.z;"),
    _m("point-at-rounding", "r.x = xe->Edge.x * lambda + xe->Tail.x;",
       "r.x = xe->Head.x - xe->Edge.x * (1.0f - lambda);"),
    _m("lane-combine-regrouped", "return (r0 * v->x + r1 * v->y) + r2 * v->z;",
       "return r0 * v->x + (r1 * v->y + r2 * v->z);"),
    _m("first-swapped", "return w->SwitchState == 1 ? w->F1 : w->F2;",
       "return w->SwitchState == 2 ? w->F1 : w->F2;"),
    _m("second-swapped", "return w->SwitchState == 2 ? w->F1 : w->F2;",
       "return w->SwitchState == 1 ? w->F1 : w->F2;"),
    _m("set-first-swapped", _lines("    if (w->SwitchState == 1)",
                                   "        w->F1 = f;"),
       _lines("    if (w->SwitchState == 2)", "        w->F1 = f;")),
    _m("set-second-swapped", _lines("    if (w->SwitchState == 2)",
                                    "        w->F1 = f;"),
       _lines("    if (w->SwitchState == 1)", "        w->F1 = f;")),
    _m("first-cp-swapped", "return w->SwitchState == 1 ? &w->CP1 : &w->CP2;",
       "return w->SwitchState == 1 ? &w->CP2 : &w->CP1;"),
    _m("second-cp-swapped", "return w->SwitchState == 2 ? &w->CP1 : &w->CP2;",
       "return w->SwitchState == 2 ? &w->CP2 : &w->CP1;"),
    _m("set-xyz-no-z", _lines("    dst->y = src->y;", "    dst->z = src->z;"),
       "    dst->y = src->y;"),

    # ------------------------------------------------ the transform
    _m("dist-no-sqrt", "    return sqrtf(len_sq(&d));", "    return len_sq(&d);"),
    _m("xinit-regrouped", "m.v3.x = (m.v3.x + startt->x) - endt->x;",
       "m.v3.x = m.v3.x + (startt->x - endt->x);"),
    _m("xinit-no-start-row", "m.v3.y = (m.v3.y + startt->y) - endt->y;",
       "m.v3.y = startt->y - endt->y;"),
    _m("xinit-w-zero", _lines("    m.v3.w = 1.0f;",
                              "    bTransposeMatrix(&inv, endr);"),
       _lines("    m.v3.w = 0.0f;", "    bTransposeMatrix(&inv, endr);")),
    _m("xinit-no-transpose", "    bTransposeMatrix(&inv, endr);",
       "    inv = *endr;"),
    _m("xinit-mul-swapped", "bMulMatrix(&x->Matrix, &inv, &m);",
       "bMulMatrix(&x->Matrix, &m, &inv);"),
    _m("xvecp-w-zero", _lines("    m.v3.w = 1.0f;",
                              "    bMulMatrixVec3(out, &m, in);"),
       _lines("    m.v3.w = 0.0f;", "    bMulMatrixVec3(out, &m, in);")),
    _m("xvecp-keeps-x", _lines("    m.v3.x = 0.0f;", "    m.v3.y = 0.0f;"),
       "    m.v3.y = 0.0f;"),
    _m("xvec-pad-zero",
       _lines("    r.pad = lane_combine(m->v0.w, m->v1.w, m->v2.w, &v);",
              "    return r;"),
       _lines("    r.pad = 0.0f;", "    return r;")),
    _m("xvec-y-by-x-row",
       "r.y = lane_combine(m->v0.y, m->v1.y, m->v2.y, &v);",
       "r.y = lane_combine(m->v0.x, m->v1.y, m->v2.y, &v);"),
    _m("xpt-no-trans-x",
       "r.x = lane_combine(m->v0.x, m->v1.x, m->v2.x, &v) + m->v3.x;",
       "r.x = lane_combine(m->v0.x, m->v1.x, m->v2.x, &v);"),
    _m("xpt-trans-w-one",
       "r.pad = lane_combine(m->v0.w, m->v1.w, m->v2.w, &v) + m->v3.w;",
       "r.pad = lane_combine(m->v0.w, m->v1.w, m->v2.w, &v) + 1.0f;"),
    _m("xf-vertex-as-vector",
       "tf->Head = vctransform_transform_point(x, vpos(&v->Feature));",
       "tf->Head = vctransform_transform_vector(x, vpos(&v->Feature));"),
    _m("xf-vertex-no-feature", "    tf->pFeature = &v->Feature;",
       "    tf->pFeature = NULL;"),
    _m("xf-edge-no-feature", "    tf->pFeature = &e->Feature;",
       "    tf->pFeature = NULL;"),
    _m("xf-edge-ends-swapped",
       "h = vctransform_transform_point(x, vpos(e->pPlanes[1].Neighbor));",
       "h = vctransform_transform_point(x, vpos(e->pPlanes[0].Neighbor));"),
    _m("xf-edge-pad", "    tf->Edge.pad = h.pad;",
       "    tf->Edge.pad = h.pad - t.pad;"),

    # ------------------------------------------------ the clips
    _m("ci-lambda-max", "    c->LambdaMax = 1.0f;", "    c->LambdaMax = 2.0f;"),
    _m("ci-penetration", _lines("    c->Penetration = 0;", "}"),
       _lines("    c->Penetration = 1;", "}")),
    _m("cp-both-out-min-only",
       _lines("                c->NeighborMin = pl->Neighbor;",
              "                c->NeighborMax = pl->Neighbor;",
              "                return 0;"),
       _lines("                c->NeighborMin = pl->Neighbor;",
              "                return 0;")),
    _m("cp-dt-le", "        if (dt < 0.0f) {", "        if (dt <= 0.0f) {"),
    _m("cp-dh-le", "            if (dh < 0.0f) {",
       "            if (dh <= 0.0f) {"),
    _m("cp-lambda-rounding", "            lambda = dt / (dt - dh);",
       "            lambda = dt * (1.0f / (dt - dh));"),
    _m("cp-min-le", "            if (c->LambdaMin < lambda) {",
       "            if (c->LambdaMin <= lambda) {"),
    _m("cp-min-no-exit", _lines("                if (c->LambdaMax < lambda)",
                                "                    return 0;", ""), ""),
    _m("cp-max-le", "            if (lambda < c->LambdaMax) {",
       "            if (lambda <= c->LambdaMax) {"),
    _m("cp-max-no-exit", _lines("                if (lambda < c->LambdaMin)",
                                "                    return 0;", ""), ""),
    _m("cp-max-no-neighbor",
       _lines("                c->LambdaMax = lambda;",
              "                c->NeighborMax = pl->Neighbor;"),
       "                c->LambdaMax = lambda;"),

    _m("cv-stops-on-empty", "    (void)vcclip_clip_planes(c, xedge, planes, n);",
       _lines("    if (!vcclip_clip_planes(c, xedge, planes, n))",
              "        return NULL;")),
    _m("cv-no-same-exit",
       _lines("    if (nmin != NULL && nmin == c->NeighborMax)",
              "        return nmin;", "", "    if (nmin != NULL) {"),
       "    if (nmin != NULL) {"),
    _m("cv-min-touch", "VC_VERTEX_MIN_TOUCH   9.99999975e-06f",
       "VC_VERTEX_MIN_TOUCH   9.99999975e-08f", VH),
    _m("cv-max-touch", "VC_VERTEX_MAX_TOUCH   9.99999975e-06f",
       "VC_VERTEX_MAX_TOUCH   9.99999975e-08f", VH),
    _m("cv-min-touch-returns",
       _lines("            c->Penetration = 1;",
              "        else if (0.0f < dot3(&xedge->Edge, &d))"),
       _lines("            { c->Penetration = 1; return NULL; }",
              "        else if (0.0f < dot3(&xedge->Edge, &d))")),
    _m("cv-min-dot-flipped", "        else if (0.0f < dot3(&xedge->Edge, &d))",
       "        else if (dot3(&xedge->Edge, &d) < 0.0f)"),
    _m("cv-min-vert-ignored", "vp = vert != NULL ? *vert : vpos(nmin);",
       "vp = vpos(nmin);"),
    _m("cv-min-at-max", _lines("    if (nmin != NULL) {",
                               "        p = point_at(xedge, c->LambdaMin);"),
       _lines("    if (nmin != NULL) {",
              "        p = point_at(xedge, c->LambdaMax);")),
    _m("cv-nmax-unchecked", _lines("    if (nmax == NULL)", "        return NULL;",
                                   "    p = point_at(xedge, c->LambdaMax);"),
       "    p = point_at(xedge, c->LambdaMax);"),
    _m("cv-max-touch-goes-on",
       _lines("        c->Penetration = 1;", "        return NULL;", "    }",
              "    if (dot3(&xedge->Edge, &d) < 0.0f)"),
       _lines("        c->Penetration = 1;", "    }",
              "    if (dot3(&xedge->Edge, &d) < 0.0f)")),
    _m("cv-max-dot-flipped", _lines("    if (dot3(&xedge->Edge, &d) < 0.0f)",
                                    "        return nmax;"),
       _lines("    if (0.0f < dot3(&xedge->Edge, &d))", "        return nmax;")),
    _m("cv-max-vert-ignored", "vp = vert != NULL ? *vert : vpos(nmax);",
       "vp = vpos(nmax);"),

    _m("cf-no-same-exit",
       _lines("    if (nmin != NULL && nmin == c->NeighborMax)",
              "        return nmin;", "", "    // An empty clip"),
       "    // An empty clip"),
    _m("cf-empty-ignored", "    if (r == 0) {", "    if (r == 7) {"),
    _m("cf-empty-min-face-no-exit",
       _lines("            if (c->NeighborMax->Type == VCFEATURE_EDGE)",
              "                return nmin;", ""), ""),
    _m("cf-empty-max-face-no-exit",
       _lines("            if (nmin->Type == VCFEATURE_EDGE)",
              "                return c->NeighborMax;", ""), ""),
    _m("cf-fallback-min", _lines("        if (nmin->Type == VCFEATURE_FACE) {",
                                 "            fallback = 1;"),
       _lines("        if (nmin->Type == VCFEATURE_FACE) {",
              "            fallback = 0;")),
    _m("cf-fallback-max",
       _lines("        } else if (c->NeighborMax->Type == VCFEATURE_FACE) {",
              "            fallback = 1;"),
       _lines("        } else if (c->NeighborMax->Type == VCFEATURE_FACE) {",
              "            fallback = 0;")),
    _m("cf-min-not-face",
       "    if (nmin != NULL && nmin->Type == VCFEATURE_FACE) {",
       "    if (nmin != NULL) {"),
    _m("cf-min-face-arg-ignored",
       "f = face != NULL ? face : (const VCFace *)nmin;",
       "f = (const VCFace *)nmin;"),
    _m("cf-min-touch-signed", "        if (fabsf(dist) < VC_FACE_MIN_TOUCH) {",
       "        if (dist < VC_FACE_MIN_TOUCH) {"),
    _m("cf-min-touch", "VC_FACE_MIN_TOUCH     9.99999975e-05f",
       "VC_FACE_MIN_TOUCH     9.99999975e-07f", VH),
    _m("cf-min-sign",
       "            if (0.0f < dist * normal_dot(&f->Plane, &xedge->Edge))",
       "            if (dist * normal_dot(&f->Plane, &xedge->Edge) < 0.0f)"),
    _m("cf-min-no-fallback", _lines("            if (fallback)",
                                    "                return c->NeighborMax;",
                                    ""), ""),
    _m("cf-max-not-face",
       "    if (nmax == NULL || nmax->Type != VCFEATURE_FACE)",
       "    if (nmax == NULL)"),
    _m("cf-max-face-arg-ignored",
       "f = face != NULL ? face : (const VCFace *)nmax;",
       "f = (const VCFace *)nmax;"),
    _m("cf-max-touch-signed", "    if (fabsf(dist) < VC_FACE_MAX_TOUCH) {",
       "    if (dist < VC_FACE_MAX_TOUCH) {"),
    _m("cf-max-touch", "VC_FACE_MAX_TOUCH     9.99999975e-05f",
       "VC_FACE_MAX_TOUCH     9.99999975e-07f", VH),
    _m("cf-max-touch-goes-on",
       _lines("        c->Penetration = 1;", "        return NULL;", "    }",
              "    if (dist * normal_dot"),
       _lines("        c->Penetration = 1;", "    }",
              "    if (dist * normal_dot")),
    _m("cf-max-sign",
       _lines("    if (dist * normal_dot(&f->Plane, &xedge->Edge) < 0.0f)",
              "        return nmax;"),
       _lines("    if (0.0f < dist * normal_dot(&f->Plane, &xedge->Edge))",
              "        return nmax;")),
    _m("cf-max-no-fallback", "    return fallback ? nmin : NULL;",
       "    return NULL;"),

    # ------------------------------------------------ the witness
    _m("wi-pads-zeroed", _lines("    w->CP1.z = 0.0f;", ""),
       _lines("    w->CP1.z = 0.0f;", "    w->CP1.pad = 0.0f;", "")),
    _m("wi-f1-from-p2", "    w->F1 = (VCFeature *)p1->pVertices;",
       "    w->F1 = (VCFeature *)p2->pVertices;"),
    _m("wi-p2-is-p1", "    w->P2 = p2;", "    w->P2 = p1;"),
    _m("wi-switch-state", "    w->SwitchState = 0;", "    w->SwitchState = 1;"),
    _m("wi-distance", _lines("    w->Distance = 0.0f;",
                             "    w->pCaffeineObj1 = NULL;"),
       _lines("    w->Distance = 1.0f;", "    w->pCaffeineObj1 = NULL;")),
    _m("wd-tests-obj2", "    if (w->pCaffeineObj1 != NULL) {",
       "    if (w->pCaffeineObj2 != NULL) {"),
    _m("wd-one-delete", _lines("        esp_delete_object(w->pCaffeineObj2);",
                               ""), ""),
    _m("wd-no-free", _lines("    if (flags & 1)", "        bFree(w);"),
       "    (void)flags;"),
    _m("wd-obj1-kept",
       _lines("        w->pCaffeineObj1 = NULL;", "        w->pCaffeineObj2 = NULL;",
              "    }", "    if (flags & 1)", "        bFree(w);"),
       _lines("        w->pCaffeineObj2 = NULL;", "    }", "    if (flags & 1)",
              "        bFree(w);")),

    _m("vv-b-le",
       "        if (plane_dist(&b->pPlanes[i].Plane, &xf1->Head) < 0.0f) {",
       "        if (plane_dist(&b->pPlanes[i].Plane, &xf1->Head) <= 0.0f) {"),
    _m("vv-moves-first", "            set_second(w, b->pPlanes[i].Neighbor);",
       "            set_first(w, b->pPlanes[i].Neighbor);"),
    _m("vv-b-by-x12", "    vctf_transform_vertex(xf2, x21, b);",
       "    vctf_transform_vertex(xf2, x12, b);"),
    _m("vv-a-le",
       "        if (plane_dist(&a->pPlanes[i].Plane, &xf2->Head) < 0.0f) {",
       "        if (plane_dist(&a->pPlanes[i].Plane, &xf2->Head) <= 0.0f) {"),
    _m("vv-moves-second", "            set_first(w, a->pPlanes[i].Neighbor);",
       "            set_second(w, a->pPlanes[i].Neighbor);"),
    _m("vv-dist-wrong-frame", "    d = sub3(&pa, &xf2->Head);",
       "    d = sub3(&pa, &xf1->Head);"),
    _m("vv-no-sqrt", "    w->Distance = sqrtf(len_sq(&d));" + NL
       + "    *first_cp(w) = pa;",
       "    w->Distance = len_sq(&d);" + NL + "    *first_cp(w) = pa;"),
    _m("vv-cp1-transformed", "    *first_cp(w) = pa;",
       "    *first_cp(w) = xf1->Head;"),
    _m("vv-cp2-transformed", "    *second_cp(w) = vpos(&b->Feature);",
       "    *second_cp(w) = xf2->Head;"),
    _m("vv-touch-zero", "return VC_VV_TOUCH < w->Distance ? 1 : 2;",
       "return 0.0f < w->Distance ? 1 : 2;"),
    _m("vv-touch-le", "return VC_VV_TOUCH < w->Distance ? 1 : 2;",
       "return VC_VV_TOUCH <= w->Distance ? 1 : 2;"),

    _m("ve-two-planes", "    for (i = 0; i < 4; i++) {",
       "    for (i = 0; i < 2; i++) {"),
    _m("ve-le",
       "        if (plane_dist(&e->pPlanes[i].Plane, &xf1->Head) < 0.0f) {",
       "        if (plane_dist(&e->pPlanes[i].Plane, &xf1->Head) <= 0.0f) {"),
    _m("ve-moves-first", "            set_second(w, e->pPlanes[i].Neighbor);",
       "            set_first(w, e->pPlanes[i].Neighbor);"),
    _m("ve-edge-by-x12", "    vctf_transform_edge(xf2, x21, e);",
       "    vctf_transform_edge(xf2, x12, e);"),
    _m("ve-no-vertex",
       "    r = vcclip_clip_vertex_planes(&clip, xf2, &vp, v->pPlanes,",
       "    r = vcclip_clip_vertex_planes(&clip, xf2, NULL, v->pPlanes,"),
    _m("ve-clip-moves-second", _lines("        set_first(w, r);",
                                      "        return 0;"),
       _lines("        set_second(w, r);", "        return 0;")),
    _m("ve-pen-ignored", _lines("    if (clip.Penetration) {",
                                "        w->Distance = 0.0f;",
                                "        *first_cp(w) = vp;"),
       _lines("    if (0) {", "        w->Distance = 0.0f;",
              "        *first_cp(w) = vp;")),
    _m("ve-pen-no-distance", _lines("        w->Distance = 0.0f;",
                                    "        *first_cp(w) = vp;"),
       "        *first_cp(w) = vp;"),
    _m("ve-pen-cp2-vertex",
       _lines("        *second_cp(w) = xf1->Head;", "        return 2;", "    }",
              "", "    *first_cp(w) = vpos(&v->Feature);"),
       _lines("        *second_cp(w) = vp;", "        return 2;", "    }", "",
              "    *first_cp(w) = vpos(&v->Feature);")),
    _m("ve-cp1-transformed", "    *first_cp(w) = vpos(&v->Feature);",
       "    *first_cp(w) = xf1->Head;"),
    _m("ve-from-head", _lines("    tail = vpos(e->pPlanes[0].Neighbor);",
                              "    dir = edge_dir(e);"),
       _lines("    tail = vpos(e->pPlanes[1].Neighbor);",
              "    dir = edge_dir(e);")),
    _m("ve-offset-reversed", "    d = sub3(&xf1->Head, &tail);",
       "    d = sub3(&tail, &xf1->Head);"),
    _m("ve-dist-to-tail", "    d = sub3(&xf1->Head, second_cp(w));",
       "    d = sub3(&xf1->Head, &tail);"),

    _m("vf-last-violated", "        if (d < least) {", "        if (d < 0.0f) {"),
    _m("vf-violated-le", "        if (d < least) {", "        if (d <= least) {"),
    _m("vf-touch-signed", "    if (fabsf(h) < VC_VF_TOUCH) {",
       "    if (h < VC_VF_TOUCH) {"),
    _m("vf-touch", "VC_VF_TOUCH           9.99999975e-05f",
       "VC_VF_TOUCH           9.99999975e-07f", VH),
    _m("vf-touch-no-distance",
       _lines("        w->Distance = 0.0f;", "        set_xyz(first_cp(w), &pv);"),
       "        set_xyz(first_cp(w), &pv);"),
    _m("vf-touch-cp1-whole",
       _lines("        set_xyz(first_cp(w), &pv);",
              "        *second_cp(w) = xf1->Head;"),
       _lines("        *first_cp(w) = pv;", "        *second_cp(w) = xf1->Head;")),
    _m("vf-other-from-head", "        VCFeature *other = e->pPlanes[0].Neighbor;",
       "        VCFeature *other = e->pPlanes[1].Neighbor;"),
    _m("vf-edge-behind-only",
       "if ((h < 0.0f && h < o) || (0.0f < h && o < h)) {",
       "if (h < 0.0f && h < o) {"),
    _m("vf-edge-front-only",
       "if ((h < 0.0f && h < o) || (0.0f < h && o < h)) {",
       "if (0.0f < h && o < h) {"),
    _m("vf-edge-moves-second", "            set_first(w, &e->Feature);",
       "            set_second(w, &e->Feature);"),
    _m("vf-out-sign", "        *second_cp(w) = along(&q, &n, -h);",
       "        *second_cp(w) = along(&q, &n, h);"),
    _m("vf-out-pad-kept", _lines("        q = xf1->Head;", "        q.pad = 0.0f;",
                                 "        *second_cp(w) = along(&q, &n, -h);"),
       _lines("        q = xf1->Head;",
              "        *second_cp(w) = along(&q, &n, -h);")),
    _m("vf-out-cp1-whole", _lines("    if (0.0f < h) {",
                                  "        set_xyz(first_cp(w), &pv);"),
       _lines("    if (0.0f < h) {", "        *first_cp(w) = pv;")),
    _m("vf-out-distance", "        w->Distance = h;", "        w->Distance = -h;"),
    _m("vf-out-status", _lines("        w->Distance = h;", "        return 1;"),
       _lines("        w->Distance = h;", "        return 2;")),
    _m("vf-search-own-poly", "p = w->SwitchState == 2 ? w->P1 : w->P2;",
       "p = w->SwitchState == 1 ? w->P1 : w->P2;"),
    _m("vf-search-le", "        if (best < fd) {", "        if (best <= fd) {"),
    _m("vf-search-no-move", _lines("            set_second(w, &face->Feature);",
                                   ""), ""),
    _m("vf-search-always-2", "    return best < 0.0f ? 2 : 1;", "    return 2;"),
    _m("vf-search-first-face", "    n = plane_normal(&bf->Plane);",
       "    n = plane_normal(&f->Plane);"),
    _m("vf-search-sign", "    *second_cp(w) = along(&q, &n, -best);",
       "    *second_cp(w) = along(&q, &n, best);"),
    _m("vf-search-distance", "    w->Distance = best;",
       "    w->Distance = -best;"),

    _m("sub-vert-swapped",
       _lines("edge->pPlanes, 2);", "    if (r != NULL) {",
              "        if (which == w->SwitchState)"),
       _lines("edge->pPlanes, 2);", "    if (r != NULL) {",
              "        if (which != w->SwitchState)")),
    _m("sub-vert-pen-ignored",
       _lines("    if (clip.Penetration) {", "        w->Distance = 0.0f;",
              "        return 2;", "    }",
              "    r = vcclip_clip_face_planes"),
       "    r = vcclip_clip_face_planes"),
    _m("sub-vert-pen-no-distance",
       _lines("        w->Distance = 0.0f;", "        return 2;", "    }",
              "    r = vcclip_clip_face_planes"),
       _lines("        return 2;", "    }", "    r = vcclip_clip_face_planes")),
    _m("sub-face-reinit",
       "    r = vcclip_clip_face_planes(&clip, xf, NULL, &edge->pPlanes[2], 2);",
       _lines("    vcclip_init(&clip);",
              "    r = vcclip_clip_face_planes(&clip, xf, NULL,"
              " &edge->pPlanes[2], 2);")),
    _m("sub-face-swapped",
       _lines("&edge->pPlanes[2], 2);", "    if (r != NULL) {",
              "        if (which == w->SwitchState)"),
       _lines("&edge->pPlanes[2], 2);", "    if (r != NULL) {",
              "        if (which != w->SwitchState)")),
    _m("sub-face-pen-ignored",
       _lines("    if (clip.Penetration) {", "        w->Distance = 0.0f;",
              "        return 2;", "    }", "    return 1;"),
       "    return 1;"),

    _m("coe-offset-reversed", "    diff = sub3(&ot, &tail);",
       "    diff = sub3(&tail, &ot);"),
    _m("coe-dbc-z-unscaled", "    dbc.z = odir->z * c;", "    dbc.z = odir->z;"),
    _m("coe-perp-reversed", "    perp = sub3(&da, &dbc);",
       "    perp = sub3(&dbc, &da);"),
    _m("coe-den-plus", "    den = 1.0f - c2;", "    den = 1.0f + c2;"),
    _m("coe-never-parallel", "    if (den < parallel)", "    if (den < 0.0f)"),
    _m("coe-parallel-ends", "        return 0.0f < num ? head : tail;",
       "        return 0.0f < num ? tail : head;"),
    _m("coe-no-low-clamp", _lines("    if (lambda < 0.0f) {",
                                  "        lambda = 0.0f;"),
       _lines("    if (lambda < -1e30f) {", "        lambda = 0.0f;")),
    _m("coe-no-high-clamp", _lines("        if (len < lambda)",
                                   "            lambda = len;", ""), ""),
    _m("coe-unit-length", "        len = vc_dist_between(&head, &tail);",
       "        len = 1.0f;"),
    _m("fol-from-head", "    bVector3 bt = vpos(b->pPlanes[0].Neighbor);",
       "    bVector3 bt = vpos(b->pPlanes[1].Neighbor);"),
    _m("fol-offset-reversed", "    bVector3 d = sub3(p, &bt);",
       "    bVector3 d = sub3(&bt, p);"),
    _m("ee-parallel", "VC_EE_PARALLEL        9.99999997e-07f",
       "VC_EE_PARALLEL        9.99999997e-03f", VH),
    _m("ef-parallel", "VC_EF_PARALLEL        9.99999997e-07f",
       "VC_EF_PARALLEL        9.99999997e-03f", VH),

    _m("ee-sub1-which", "r = vcwitness_sub_check_edge_edge(w, xf1, b, 2);",
       "r = vcwitness_sub_check_edge_edge(w, xf1, b, 1);"),
    _m("ee-sub1-goes-on",
       _lines("    r = vcwitness_sub_check_edge_edge(w, xf1, b, 2);",
              "    if (r != 1)", "        return r;"),
       "    r = vcwitness_sub_check_edge_edge(w, xf1, b, 2);"),
    _m("ee-b-by-x12", "    vctf_transform_edge(xf2, x21, b);",
       "    vctf_transform_edge(xf2, x12, b);"),
    _m("ee-sub2-which", "r = vcwitness_sub_check_edge_edge(w, xf2, a, 1);",
       "r = vcwitness_sub_check_edge_edge(w, xf2, a, 2);"),
    _m("ee-db-by-x12", "    db = vctransform_transform_vector(x21, edge_dir(b));",
       "    db = vctransform_transform_vector(x12, edge_dir(b));"),
    _m("ee-from-b-head",
       "    *cpa = closest_on_edge(a, &xf2->Tail, &db, VC_EE_PARALLEL);",
       "    *cpa = closest_on_edge(a, &xf2->Head, &db, VC_EE_PARALLEL);"),
    _m("ee-p-by-x21", _lines("    p = vctransform_transform_point(x12, cp);",
                             "    cpb = second_cp(w);"),
       _lines("    p = vctransform_transform_point(x21, cp);",
              "    cpb = second_cp(w);")),
    _m("ee-dist-to-head", "    w->Distance = vc_dist_between(&p, &cp);",
       "    w->Distance = vc_dist_between(&p, &xf1->Head);"),

    _m("ef-clip-inverted",
       "    if (vcclip_clip_planes(&clip, xf1, f->pPlanes, f->Feature.NumPlanes)) {",
       "    if (!vcclip_clip_planes(&clip, xf1, f->pPlanes,"
       " f->Feature.NumPlanes)) {"),
    _m("ef-pmax-at-min", "        bVector3 pmax = point_at(xf1, clip.LambdaMax);",
       "        bVector3 pmax = point_at(xf1, clip.LambdaMin);"),
    _m("ef-cross-strict", "        if (dmin * dmax <= 0.0f) {",
       "        if (dmin * dmax < 0.0f) {"),
    _m("ef-cross-no-distance", _lines("        if (dmin * dmax <= 0.0f) {",
                                      "            w->Distance = 0.0f;"),
       "        if (dmin * dmax <= 0.0f) {"),
    _m("ef-toward-flipped",
       "        if (0.0f < dmin * normal_dot(&f->Plane, &xf1->Edge)) {",
       "        if (dmin * normal_dot(&f->Plane, &xf1->Edge) < 0.0f) {"),
    _m("ef-nmin-moves-first", _lines("            if (clip.NeighborMin != NULL)",
                                     "                set_second(w, clip.NeighborMin);"),
       _lines("            if (clip.NeighborMin != NULL)",
              "                set_first(w, clip.NeighborMin);")),
    _m("ef-min-end-head", "                set_first(w, e->pPlanes[0].Neighbor);",
       "                set_first(w, e->pPlanes[1].Neighbor);"),
    _m("ef-nmax-moves-first", _lines("            if (clip.NeighborMax != NULL)",
                                     "                set_second(w, clip.NeighborMax);"),
       _lines("            if (clip.NeighborMax != NULL)",
              "                set_first(w, clip.NeighborMax);")),
    _m("ef-max-end-tail", "                set_first(w, e->pPlanes[1].Neighbor);",
       "                set_first(w, e->pPlanes[0].Neighbor);"),
    _m("ef-edges-by-x12", "        vctf_transform_edge(&tf, x21, g);",
       "        vctf_transform_edge(&tf, x12, g);"),
    _m("ef-dg-by-x12", "        dg = vctransform_transform_vector(x21, edge_dir(g));",
       "        dg = vctransform_transform_vector(x12, edge_dir(g));"),
    _m("ef-from-g-head",
       "        q = closest_on_edge(e, &tf.Tail, &dg, VC_EF_PARALLEL);",
       "        q = closest_on_edge(e, &tf.Head, &dg, VC_EF_PARALLEL);"),
    _m("ef-dist-wrong-frame", "        dist = vc_dist_between(&p, &qg);",
       "        dist = vc_dist_between(&q, &qg);"),
    _m("ef-clip2-face-planes",
       "        r2 = vcclip_clip_vertex_planes(&clip2, xf1, NULL, g->pPlanes, 2);",
       "        r2 = vcclip_clip_vertex_planes(&clip2, xf1, NULL,"
       " &g->pPlanes[2], 2);"),
    _m("ef-pen-ignored", _lines("        if (clip2.Penetration)",
                                "            return 2;"),
       "        (void)clip2;"),
    _m("ef-pen-sets-distance",
       "            return 2;               // Distance is left as it was",
       "            { w->Distance = 0.0f; return 2; }"),
    _m("ef-first-edge-only", "        if (i == 0 || dist < least) {",
       "        if (i == 0) {"),
    _m("ef-nearest-le", "        if (i == 0 || dist < least) {",
       "        if (i == 0 || dist <= least) {"),
    _m("ef-region-ignored",
       _lines("    if (best_r2 != NULL)", "        set_second(w, best_r2);",
              "    else", "        set_second(w, (VCFeature *)best_g);"),
       "    set_second(w, (VCFeature *)best_g);"),
    _m("ef-region-moves-first", "        set_second(w, best_r2);",
       "        set_first(w, best_r2);"),

    _m("vc-x12-backwards", "    vctransform_init(&x12, r2, t2, r1, t1);",
       "    vctransform_init(&x12, r1, t1, r2, t2);"),
    _m("vc-x21-backwards", "    vctransform_init(&x21, r1, t1, r2, t2);",
       "    vctransform_init(&x21, r2, t2, r1, t1);"),
    _m("vc-vv-state", _lines("        case 0x00000u:",
                             "            w->SwitchState = 1;"),
       _lines("        case 0x00000u:", "            w->SwitchState = 2;")),
    _m("vc-ve-state", _lines("        case 0x10000u:",
                             "            w->SwitchState = 1;"),
       _lines("        case 0x10000u:", "            w->SwitchState = 2;")),
    _m("vc-ev-state", _lines("        case 0x00001u:",
                             "            w->SwitchState = 2;"),
       _lines("        case 0x00001u:", "            w->SwitchState = 1;")),
    _m("vc-vf-state", _lines("        case 0x20000u:",
                             "            w->SwitchState = 1;"),
       _lines("        case 0x20000u:", "            w->SwitchState = 2;")),
    _m("vc-fv-state", _lines("        case 0x00002u:",
                             "            w->SwitchState = 2;"),
       _lines("        case 0x00002u:", "            w->SwitchState = 1;")),
    _m("vc-ee-state", _lines("        case 0x10001u:",
                             "            w->SwitchState = 1;"),
       _lines("        case 0x10001u:", "            w->SwitchState = 2;")),
    _m("vc-ef-state", _lines("        case 0x20001u:",
                             "            w->SwitchState = 1;"),
       _lines("        case 0x20001u:", "            w->SwitchState = 2;")),
    _m("vc-fe-state", _lines("        case 0x10002u:",
                             "            w->SwitchState = 2;"),
       _lines("        case 0x10002u:", "            w->SwitchState = 1;")),
    _m("vc-ev-unswapped",
       "status = vcwitness_check_vertex_edge(w, &x21, &x12, &xf2, &xf1);",
       "status = vcwitness_check_vertex_edge(w, &x12, &x21, &xf1, &xf2);"),
    _m("vc-fv-unswapped",
       "status = vcwitness_check_vertex_face(w, &x21, &x12, &xf2, &xf1);",
       "status = vcwitness_check_vertex_face(w, &x12, &x21, &xf1, &xf2);"),
    _m("vc-fe-unswapped",
       "status = vcwitness_check_edge_face(w, &x21, &x12, &xf2, &xf1);",
       "status = vcwitness_check_edge_face(w, &x12, &x21, &xf1, &xf2);"),
    _m("vc-print-p1-twice", "        vcpoly_print(w->P2);",
       "        vcpoly_print(w->P1);"),
    _m("vc-print-always", "    if (PrintThisTime) {", "    if (1) {"),
    _m("vc-runs-on", "        if (status != 0 || !(i < VC_MAX_ITERATIONS))",
       "        if (!(i < VC_MAX_ITERATIONS))"),
    _m("vc-step-limit", "VC_MAX_ITERATIONS     80",
       "VC_MAX_ITERATIONS     79", VH),
    _m("vc-step-limit-le", "        if (status != 0 || !(i < VC_MAX_ITERATIONS))",
       "        if (status != 0 || !(i <= VC_MAX_ITERATIONS))"),
    _m("vc-code-shift", "            + ((uint32_t)(int32_t)w->F2->Type << 16);",
       "            + ((uint32_t)(int32_t)w->F2->Type << 8);"),

    _m("wp-no-mesh1", _lines("        esp_create_user_mesh(w->pCaffeineObj1, 1);",
                             ""), ""),
    _m("wp-tests-obj2", _lines("        if (w->pCaffeineObj1 == NULL)",
                               "            return;"),
       _lines("        if (w->pCaffeineObj2 == NULL)", "            return;")),
    _m("wp-f2-by-m1", "    vcfeature_create_user_mesh_face(w->F2, buf, m2);",
       "    vcfeature_create_user_mesh_face(w->F2, buf, m1);"),
    _m("wp-face-index", "    esp_set_user_mesh_face(w->pCaffeineObj2, 0, buf);",
       "    esp_set_user_mesh_face(w->pCaffeineObj2, 1, buf);"),
    _m("wp-position-row",
       "    esp_set_object_position(w->pCaffeineObj1, (bVector3 *)&m1->v3);",
       "    esp_set_object_position(w->pCaffeineObj1, (bVector3 *)&m1->v2);"),

    # ------------------------------------------------ the features
    _m("vsv-flip-inverted", "        if (e->pPlanes[1].Neighbor != &v->Feature)",
       "        if (e->pPlanes[1].Neighbor == &v->Feature)"),
    _m("vsv-d-zero", "        pl->Plane.CompressedPlaneDistance = dot3(&p, &n);",
       "        pl->Plane.CompressedPlaneDistance = 0.0f;"),
    _m("gne-last-kept", _lines("        if (e == (VCFeature *)last)",
                               "            continue;", ""), ""),
    _m("gne-first-plane-only", _lines("        for (j = 0; j < nf; j++) {",
                                      "            if (face->pPlanes[j].Neighbor == e)"),
       _lines("        for (j = 0; j < 1 && j < nf; j++) {",
              "            if (face->pPlanes[j].Neighbor == e)")),
    _m("vmove-z-by-y",
       "v->CompressedPosition[2] = v->CompressedPosition[2] + d->z;",
       "v->CompressedPosition[2] = v->CompressedPosition[2] + d->y;"),
    _m("efp-not-negated", "            bVector3 n = zero_minus(&fn);",
       "            bVector3 n = fn;"),
    _m("efp-d-at-origin", "            pl->Plane.CompressedPlaneDistance = dot3(head, &n);",
       "            pl->Plane.CompressedPlaneDistance = 0.0f;"),
    _m("efp-wrong-slot", "    VCVoronoiPlane *pl = &e->pPlanes[k];",
       "    VCVoronoiPlane *pl = &e->pPlanes[2];"),
    _m("esv-tail-is-head", "    tail = vpos(pl[0].Neighbor);",
       "    tail = vpos(pl[1].Neighbor);"),
    _m("esv-head-not-negated", "    set_normal(&pl[1].Plane, &nd);",
       "    set_normal(&pl[1].Plane, &d);"),
    _m("esv-head-d-unnegated",
       "    pl[1].Plane.CompressedPlaneDistance = dot3(&head, &nd);",
       "    pl[1].Plane.CompressedPlaneDistance = dot3(&head, &d);"),
    _m("esv-face-d-at-tail", "    edge_face_plane(e, 2, &head);",
       "    edge_face_plane(e, 2, &tail);"),
    _m("esv-no-face3", _lines("    edge_face_plane(e, 3, &head);", ""), ""),
    _m("fsv-cross-x-flipped", "        c.x = fn.y * d.z - d.y * fn.z;",
       "        c.x = d.y * fn.z - fn.y * d.z;"),
    _m("fsv-through-head",
       "        VCVertex *tail = (VCVertex *)e->pPlanes[0].Neighbor;",
       "        VCVertex *tail = (VCVertex *)e->pPlanes[1].Neighbor;"),
    _m("fsv-d-at-origin",
       "        pl->Plane.CompressedPlaneDistance = dot3(&c, &tp);",
       "        pl->Plane.CompressedPlaneDistance = 0.0f;"),
    _m("fsv-other-from-head", "        other = e2->pPlanes[0].Neighbor;",
       "        other = e2->pPlanes[1].Neighbor;"),
    _m("fsv-flip-inverted", "        if (plane_dist(&pl->Plane, &op) < 0.0f) {",
       "        if (0.0f < plane_dist(&pl->Plane, &op)) {"),
    _m("fsv-flip-keeps-d",
       "            pl->Plane.CompressedPlaneDistance = dot3(&n, &tp);",
       "            pl->Plane.CompressedPlaneDistance = dot3(&c, &tp);"),
    _m("fmove-sign", _lines("    f->Plane.CompressedPlaneDistance ="
                            " f->Plane.CompressedPlaneDistance",
                            "        + ((d->x"),
       _lines("    f->Plane.CompressedPlaneDistance ="
              " f->Plane.CompressedPlaneDistance",
              "        - ((d->x")),
    _m("mc-untranslated", "    out->x = v.x - m->v3.x;", "    out->x = v.x;"),
    _m("mc-unrotated", "    bMulMatrixVec3(&v, m, &v);", "    (void)m;"),
    _m("mesh-edge-reversed",
       _lines("        mesh_corner(&out[0], e->pPlanes[0].Neighbor, m);",
              "        mesh_corner(&out[1], e->pPlanes[1].Neighbor, m);"),
       _lines("        mesh_corner(&out[0], e->pPlanes[1].Neighbor, m);",
              "        mesh_corner(&out[1], e->pPlanes[0].Neighbor, m);")),
    _m("mesh-face-head-first",
       _lines("            const VCFeature *head = e->pPlanes[1].Neighbor;",
              "            const VCFeature *tail = e->pPlanes[0].Neighbor;"),
       _lines("            const VCFeature *head = e->pPlanes[0].Neighbor;",
              "            const VCFeature *tail = e->pPlanes[1].Neighbor;")),
    _m("mesh-face-count-one", "        count = face->Feature.NumPlanes;",
       "        count = 1;"),
    _m("mesh-no-pad", _lines("    for (k = count; k < 4; k++)",
                             "        out[k] = out[k - 1];"),
       "    (void)k;"),
    _m("mesh-pad-first", "        out[k] = out[k - 1];",
       "        out[k] = out[0];"),

    # ------------------------------------------------ the polyhedron
    _m("pi-dyn", _lines("    p->DynamicallyAllocated = 1;",
                        "    p->NumVertices = 0;"),
       _lines("    p->DynamicallyAllocated = 0;", "    p->NumVertices = 0;")),
    _m("pi-max-planes", "    p->MaxPlanes = 0;", "    p->MaxPlanes = 1;"),
    _m("pia-counts-kept", _lines("    p->NumPlanes = 0;",
                                 "    p->MaxVertices = (int16_t)max_vertices;"),
       "    p->MaxVertices = (int16_t)max_vertices;"),
    _m("pia-size-from-arg", "        p->MaxVertices * (int)sizeof(VCVertex)",
       "        max_vertices * (int)sizeof(VCVertex)"),
    _m("pia-edges-by-faces", "        p->MaxEdges * (int)sizeof(VCEdge)",
       "        p->MaxFaces * (int)sizeof(VCEdge)"),
    _m("pia-dyn", _lines("    p->DynamicallyAllocated = 1;", "}"),
       _lines("    p->DynamicallyAllocated = 0;", "}")),
    _m("piarr-dyn", _lines("    p->DynamicallyAllocated = 0;",
                           "    p->NumVertices = 0;"),
       _lines("    p->DynamicallyAllocated = 1;", "    p->NumVertices = 0;")),
    _m("piarr-planes-dropped", "    p->pPlanes = planes;", "    p->pPlanes = NULL;"),
    _m("pd-no-free", _lines("    vcpoly_close(p);", "    if (flags & 1)",
                            "        bFree(p);"),
       _lines("    vcpoly_close(p);", "    (void)flags;")),
    _m("pd-no-close", _lines("    vcpoly_close(p);", "    if (flags & 1)"),
       "    if (flags & 1)"),
    _m("pc-always-frees", "    if (p->DynamicallyAllocated) {", "    if (1) {"),
    _m("pc-frees-null", _lines("        if (p->pVertices != NULL)",
                               "            bFree(p->pVertices);"),
       "        bFree(p->pVertices);"),
    _m("pc-planes-not-freed", _lines("        if (p->pPlanes != NULL)",
                                     "            bFree(p->pPlanes);", ""), ""),
    _m("pc-vertices-kept", _lines("        p->pVertices = NULL;",
                                  "        p->pEdges = NULL;"),
       "        p->pEdges = NULL;"),
    _m("pc-dyn-kept", _lines("        p->DynamicallyAllocated = 0;", "    }",
                             "    if (p->pCaffeineObj != NULL) {"),
       _lines("    }", "    if (p->pCaffeineObj != NULL) {")),
    _m("pc-obj-kept", _lines("        esp_delete_object(p->pCaffeineObj);",
                             "        p->pCaffeineObj = NULL;"),
       "        esp_delete_object(p->pCaffeineObj);"),
    _m("mil-no-plane-count", _lines("    p->NumPlanes = (int16_t)num_planes;",
                                    "    vcpoly_convert_to_pointers(p);"),
       "    vcpoly_convert_to_pointers(p);"),
    _m("mil-no-convert", _lines("    p->NumPlanes = (int16_t)num_planes;",
                                "    vcpoly_convert_to_pointers(p);"),
       "    p->NumPlanes = (int16_t)num_planes;"),
    _m("unload-keeps", _lines("void vcpoly_memory_image_unload(VCPolyhedron *p)",
                              "{", "    vcpoly_close(p);"),
       _lines("void vcpoly_memory_image_unload(VCPolyhedron *p)", "{",
              "    (void)p;")),
    _m("nvp-le", "    if (p->MaxPlanes < p->NumPlanes + n)",
       "    if (p->MaxPlanes <= p->NumPlanes + n)"),
    _m("nvp-normal", "        r[i].Plane.CompressedNormal[2] = 1.0f;",
       "        r[i].Plane.CompressedNormal[2] = 0.0f;"),
    _m("nvp-distance", "        r[i].Plane.CompressedPlaneDistance = 0.0f;",
       "        r[i].Plane.CompressedPlaneDistance = 1.0f;"),
    _m("nv-full-early", "    if (!(p->NumVertices < p->MaxVertices))",
       "    if (!(p->NumVertices < p->MaxVertices - 1))"),
    _m("nv-type", "    v->Feature.Type = VCFEATURE_VERTEX;",
       "    v->Feature.Type = VCFEATURE_EDGE;"),
    _m("nv-planes-clamped", "    v->Feature.NumPlanes = (int8_t)n;",
       "    v->Feature.NumPlanes = (int8_t)(n > 127 ? 127 : n);"),
    _m("ne-full-early", "    if (!(p->NumEdges < p->MaxEdges))",
       "    if (!(p->NumEdges < p->MaxEdges - 1))"),
    _m("ne-type", "    e->Feature.Type = VCFEATURE_EDGE;",
       "    e->Feature.Type = VCFEATURE_FACE;"),
    _m("ne-rounded", "(int16_t)ee_trunc_w(dir->x * VC_DIRECTION_UNSCALE);",
       "(int16_t)ee_trunc_w(dir->x * VC_DIRECTION_UNSCALE + 0.5f);"),
    _m("ne-y-from-x", "(int16_t)ee_trunc_w(dir->y * VC_DIRECTION_UNSCALE);",
       "(int16_t)ee_trunc_w(dir->x * VC_DIRECTION_UNSCALE);"),
    _m("ne-planes", "    e->Feature.NumPlanes = (int8_t)n;",
       "    e->Feature.NumPlanes = 4;"),
    _m("nf-full-early", "    if (!(p->NumFaces < p->MaxFaces))",
       "    if (!(p->NumFaces < p->MaxFaces - 1))"),
    _m("nf-d-negated", "    f->Plane.CompressedPlaneDistance = d;",
       "    f->Plane.CompressedPlaneDistance = -d;"),
    _m("nf-planes-clamped", "    f->Feature.NumPlanes = (int8_t)n;",
       "    f->Feature.NumPlanes = (int8_t)(n > 127 ? 127 : n);"),
    _m("pp-mesh-after-test",
       _lines("        esp_create_user_mesh(p->pCaffeineObj, p->NumFaces);",
              "        if (p->pCaffeineObj == NULL)", "            return;"),
       _lines("        if (p->pCaffeineObj == NULL)", "            return;",
              "        esp_create_user_mesh(p->pCaffeineObj, p->NumFaces);")),
    _m("pp-face-index", "        esp_set_user_mesh_face(p->pCaffeineObj, i, buf);",
       "        esp_set_user_mesh_face(p->pCaffeineObj, 0, buf);"),
    _m("pp-position-row",
       "    esp_set_object_position(p->pCaffeineObj, (bVector3 *)&m->v3);",
       "    esp_set_object_position(p->pCaffeineObj, (bVector3 *)&m->v2);"),
    _m("psv-edges-before-faces",
       _lines("    for (i = 0; i < p->NumFaces; i++)",
              "        vcface_set_voronoi_planes(&p->pFaces[i]);",
              "    for (i = 0; i < p->NumEdges; i++)",
              "        vcedge_set_voronoi_planes(&p->pEdges[i]);"),
       _lines("    for (i = 0; i < p->NumEdges; i++)",
              "        vcedge_set_voronoi_planes(&p->pEdges[i]);",
              "    for (i = 0; i < p->NumFaces; i++)",
              "        vcface_set_voronoi_planes(&p->pFaces[i]);")),
    _m("psv-no-vertices", _lines("    for (i = 0; i < p->NumVertices; i++)",
                                 "        vcvertex_set_voronoi_planes("
                                 "&p->pVertices[i]);", ""), ""),
    _m("gfc-null-unchecked", _lines("    if (f == NULL)",
                                    "        return VC_NO_FEATURE;", ""), ""),
    _m("gfc-shift",
       "        return ((uint32_t)((VCVertex *)f - p->pVertices) << 4)",
       "        return ((uint32_t)((VCVertex *)f - p->pVertices) << 3)"),
    _m("gfc-edge-type",
       "        return ((uint32_t)((VCEdge *)f - p->pEdges) << 4) | VCFEATURE_EDGE;",
       "        return ((uint32_t)((VCEdge *)f - p->pEdges) << 4) | VCFEATURE_FACE;"),
    _m("gfc-bad-type-zero", _lines("    default:", "        return VC_NO_FEATURE;"),
       _lines("    default:", "        return 0;")),
    _m("gf-no-none-test", _lines("    if (code == VC_NO_FEATURE)",
                                 "        return NULL;", "    idx"), "    idx"),
    _m("gf-type-mask", "    switch (code & 0xfu) {", "    switch (code & 0x3u) {"),
    _m("gf-index-shift", "    idx = code >> 4;", "    idx = code >> 3;"),
    _m("pidx-scale", "        (d / (intptr_t)sizeof(VCVoronoiPlane));",
       "        (d / (intptr_t)sizeof(VCVoronoiPlane) + 1);"),
    _m("pptr-off-by-one",
       "    return &p->pPlanes[(int32_t)(uint32_t)(uintptr_t)idx];",
       "    return &p->pPlanes[(int32_t)(uint32_t)(uintptr_t)idx + 1];"),
    _m("cti-no-faces",
       "        p->pFaces[i].pPlanes = plane_index(p, p->pFaces[i].pPlanes);",
       "        (void)0;"),
    _m("cti-code-off",
       "        p->pPlanes[i].Neighbor = (VCFeature *)(uintptr_t)code;",
       "        p->pPlanes[i].Neighbor = (VCFeature *)(uintptr_t)(code + 1);"),
    _m("ctp-no-edges",
       "        p->pEdges[i].pPlanes = plane_pointer(p, p->pEdges[i].pPlanes);",
       "        (void)0;"),
    _m("print-no-store", _lines("    pPrintingPolygon = p;", ""), ""),
]

EQUIVALENT = {
    "gf-no-none-test":
        "0xffffffff's type nibble is 15, which the switch's default answers "
        "with NULL anyway; the test is the image's and costs nothing",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

write_source = hostbuild.write_source


def mutate_pass(sc):
    base_model = model(sc)
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = hostbuild.build(tmp, SOURCES, name="vclip_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="vclip_test")
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
    # An entry whose mutant was caught is a wrong reason, not a spare one.
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
    ap.add_argument("--count", type=int, default=900,
                    help="random VClip poses (default 900)")
    args = ap.parse_args()

    sc = script(args.count)
    if args.mutate:
        sys.exit(mutate_pass(sc))

    lines = model(sc)
    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.txt"
        write_script(sc, sp)
        exe = hostbuild.build(tmp, SOURCES, name="vclip_test")
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sp, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    ops = sum(1 for line in lines if not line.startswith(("  ", "[")))
    statuses = {}
    for line in lines:
        if line.startswith("vclip "):
            st = line.split(" -> ")[1].split()[0]
            statuses[st] = statuses.get(st, 0) + 1
    print("%d scenarios, %d ops, %d lines, %d differ; vclip statuses %s"
          % (len(sc.tags), ops, len(harness), bad,
             " ".join("%s:%d" % kv for kv in sorted(statuses.items()))))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
