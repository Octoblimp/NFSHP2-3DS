"""Cross-check 3DS Files/source/democam.c against the retail image's own
code.

CameraCoordinator.obj's DemoCameraCoordinator, the near-plane test it asks
and Player::BeginDemoCameras. The oracle is SLES_507.31 itself, run in
tools/mipsemu.py:

- DemoCameraCoordinator's constructor (0x0019a440), destructor
  (0x0019a4a0, through its table 0x002b52e0), Update (0x0019a4b8, called
  directly and through UpdateCameraCoordinators 0x00199bd0), both
  WillLookGoods (0x0019a988, 0x0019a9d0) and
  FindGoodLookingHighlightCamera (0x0019aad8);
- the near-plane test (0x001044c8), called directly and by Update;
- Player::BeginDemoCameras (0x00176868);
- run as shipped under them: BaseCameraCoordinator's constructor and
  destructor, the list's static constructor, the camera loader,
  CameraDataItems(char*), FindRandomCameraShake, eMulMatrix, eMulVector,
  eIsPointInPoly, bSin, bCos and bRandom over bDefaultSeed.

Stood in on both sides, each call printing a line:
  Car::IsFacingWrongWay (0x00133420), answering the car's word;
  Car::GetCarSpaceBoundingBox (0x00135170), the car's box;
  eGetCurrentViewMode (0x00107cd8), the script's mode;
  Player::ChangeCameraMover (0x00176ae8);
  the four mover constructors -- TrackCarCameraMover (0x00159130),
    BumperCameraMover (0x00158800), TrackFlyCameraMover (0x00159d08) and
    DriveCameraMover (0x0015c258) -- which print their arguments (the
    camera's data as the parser set it, the shake's words that are not
    zero) and give the mover a test table and the next of the script's
    cameras;
  a test CameraMover table (vptr at +40) whose deleting destructor (8),
    Update (16), Enable (96) and Disable (104) print; the Update can move
    the mover onto another camera;
  bMalloc (0x002577c0) and the frees (bFree 0x00257850, __builtin_delete
    0x00114e98): a block filled with 0xcd, named h0, h1, ...

The cars (their position, matrix, box, wrong-way answer and POV counts),
the World's car list, the cameras, the players, WorldTimeFrames,
TheRaceParameters.TrackDirection and aBaselineFovZ are the script's, in
test memory on the image's side and the harness's own structs on the
port's. The highlights are the retail disc's -- TRACKB11's, TRACKB43's
and TRACKB63's, with INGAMEB's shakes -- and built ones for the edges.

    python tools/democam_check.py
    python tools/democam_check.py --mutate [--only a,b] [--jobs N]
    python tools/democam_check.py --dump PREFIX
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cameracoord_check as ccc
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/democam_test.c"
DC = "3DS Files/source/democam.c"
SOURCES = [HARNESS, DC,
           "3DS Files/source/cameracoord.c",
           "3DS Files/source/emath.c",
           "3DS Files/source/bmatrix.c",
           "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c",
           "3DS Files/source/bmathtab.c",
           "3DS Files/source/bmem.c",
           "3DS Files/source/bprintf.c",
           "3DS Files/source/vtable.c"]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP

SINIT = 0x0019c058
LOADER_CAMERAS = 0x0019a398
UNLOADER_CAMERAS = 0x0019a3c0
UPDATE_ALL = 0x00199bd0
DC_CTOR = 0x0019a440
DC_UPDATE = 0x0019a4b8
DC_WLG_DATA = 0x0019a988
DC_WLG = 0x0019a9d0
DC_FIND = 0x0019aad8
NEAR_TEST = 0x001044c8
BEGIN = 0x00176868
PARSE = 0x0019b6b0
EMATH_SINIT = 0x0011bf70             # 0x002dc400 = (0, 0, 0, 1)

WRONG_WAY = 0x00133420
BBOX = 0x00135170
VIEW_MODE = 0x00107cd8
CHANGE = 0x00176ae8
TRACKCAR = 0x00159130
BUMPER = 0x00158800
TRACKFLY = 0x00159d08
DRIVE = 0x0015c258
BMALLOC = 0x002577c0
BFREE = 0x00257850
BDELETE = 0x00114e98

LOADER = 0x00310370                 # TheCameraLoader
LIST = GP - 19920                   # CameraCoordinatorList
SEED = GP - 14472                   # bDefaultSeed
WORLD_P = GP - 22120                # pCurrentWorld
FRAMES = GP - 19564                 # WorldTimeFrames
FOVZ = GP - 13424                   # aBaselineFovZ, a u16
TRACK_DIR = 0x0031a898 + 12         # TheRaceParameters.TrackDirection

# The world.
ARENA = 0x01000000
ARENA_SIZE = 4 << 20
NEAR = 0x100000
KS = 0x01E00000                     # k0..k7, 0x100 apart
NK = 8
MOVERS = 0x01E01000                 # m0..m3
NMOVERS = 4
PLAYERS = 0x01E02000                # p0, p1
CARS = 0x01E04000                   # car0..car5, 0x200 apart
NCARS = 6
INFOS = 0x01E06000                  # their CarTypeInfos, 0x400 apart
WORLD = 0x01E08000
CAMS = 0x01E09000                   # cam0..cam7, 0x100 apart
NCAMS = 8
FMVT = 0x01E0A000                   # the test mover table
FMVT_DTOR = 0x01E0A800
FMVT_UPDATE = 0x01E0A810
FMVT_ENABLE = 0x01E0A820
FMVT_DISABLE = 0x01E0A830
SLACK = 16

(OP_TAG, OP_PUT, OP_SINIT, OP_LOAD, OP_UNLOAD, OP_SEED, OP_TIME, OP_DIR,
 OP_VMODE, OP_FOVZ, OP_CARV, OP_WCLEAR, OP_WADD, OP_CAMV, OP_CAMQ,
 OP_CAMDEF, OP_UPCAM, OP_JUNKK, OP_DCNEW, OP_DCUPDATE, OP_DCDEL,
 OP_SETMOVER, OP_MCAM, OP_SETF, OP_DUMPK, OP_FIND, OP_WLG, OP_NEAR,
 OP_BEGIN, OP_PSET, OP_DUMPP, OP_UPDATEALL) = range(32)

ARGS = {OP_TAG: 1, OP_SINIT: 0, OP_LOAD: 1, OP_UNLOAD: 1, OP_SEED: 1,
        OP_TIME: 1, OP_DIR: 1, OP_VMODE: 1, OP_FOVZ: 1, OP_CARV: 3,
        OP_WCLEAR: 0, OP_WADD: 1, OP_CAMV: 3, OP_CAMQ: 1, OP_CAMDEF: 1,
        OP_UPCAM: 1, OP_JUNKK: 2, OP_DCNEW: 3, OP_DCUPDATE: 2,
        OP_DCDEL: 2, OP_SETMOVER: 2, OP_MCAM: 2, OP_SETF: 3, OP_DUMPK: 0,
        OP_FIND: 2, OP_WLG: 3, OP_NEAR: 2, OP_BEGIN: 2, OP_PSET: 3,
        OP_DUMPP: 0, OP_UPDATEALL: 1}

# OP_CARV's fields: the position (x y z pad), BodyMatrix's sixteen words,
# the box's min and max, the wrong-way answer and the POV counts.
CV_POS, CV_MAT, CV_MIN, CV_MAX = 0, 4, 20, 23
CV_WRONG, CV_FULL, CV_SPLIT = 26, 27, 28
# OP_CAMV's: the matrix's sixteen words, the eye (x y z pad), NearZ and
# FieldOfView.
KV_MAT, KV_POS, KV_NEAR, KV_FOV = 0, 16, 20, 21
# OP_SETF's, by retail offset; F_CAR is worked out.
F_DIS, F_VIEW, F_NEED, F_LOOK, F_POV, F_START, F_ACTIVE, F_VORTEX, \
    F_CAR = range(9)
SETF_OFF = (12, 16, 20, 32, 36, 40, 44, 48, None)
# OP_PSET's.
P_MYCAR, P_VIEW, P_DEMO = range(3)


def fb(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(b):
    return "%08x" % (b & M32)


# ================================================================ the script

class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []

    def op(self, code, *args):
        assert len(args) == ARGS[code], (code, args)
        self.ops.append((code,) + tuple(int(a) & M32 for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def put(self, off, data):
        data = bytes(data)
        assert 0 <= off and off + len(data) <= ARENA_SIZE, off
        self.ops.append((OP_PUT, off, len(data)) + tuple(ccc.u32s(data)))

    def encode(self):
        out = [len(self.tags)]
        for s in self.tags:
            b = s.encode("latin-1")
            out.append(len(b))
            out.extend(b)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out), *[s32(v & M32) for v in out])

    # ---- sugar -----------------------------------------------------------

    def car_pos(self, c, x, y, z):
        for i, v in enumerate((x, y, z)):
            self.op(OP_CARV, c, CV_POS + i, fb(v))

    def car_mat(self, c, rows):
        for i, v in enumerate(rows):
            self.op(OP_CARV, c, CV_MAT + i, fb(v))

    def car_box(self, c, lo, hi):
        for i in range(3):
            self.op(OP_CARV, c, CV_MIN + i, fb(lo[i]))
            self.op(OP_CARV, c, CV_MAX + i, fb(hi[i]))

    def cam_mat(self, k, rows):
        for i, v in enumerate(rows):
            self.op(OP_CAMV, k, KV_MAT + i, fb(v))

    def cam_pos(self, k, x, y, z):
        for i, v in enumerate((x, y, z)):
            self.op(OP_CAMV, k, KV_POS + i, fb(v))

    def cam_near(self, k, near, fov=9102):
        self.op(OP_CAMV, k, KV_NEAR, fb(near))
        self.op(OP_CAMV, k, KV_FOV, fov)

    def world(self, *cars):
        self.op(OP_WCLEAR)
        for c in cars:
            self.op(OP_WADD, c)

    def update(self, k, dt=1.0 / 60):
        self.op(OP_DCUPDATE, k, fb(dt))


IDENT = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def ident_at(x, y, z):
    return IDENT[:12] + (x, y, z, 1)


def rot_z(a, t=(0.0, 0.0, 0.0)):
    c, s = math.cos(a), math.sin(a)
    return (c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1)


def rand_rot(rnd, t):
    """A random rotation, its rows, with `t` as the last row."""
    q = [rnd.gauss(0, 1) for _ in range(4)]
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    w, x, y, z = (v / n for v in q)
    m = ((1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
         (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
         (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)))
    out = []
    for r in m:
        out += [r[0], r[1], r[2], 0.0]
    return tuple(out) + (t[0], t[1], t[2], 1.0)


# The track's highlights: each camera's type, Backwards and area, read off
# the chunk as the loader will place it.
def highlight_areas(ch, base):
    out = []
    for t, a, s, p in ccc.children(ch, base):
        if t != ccc.HIGHLIGHT_C:
            continue
        o = p - base
        typ = struct.unpack_from("<i", ch, o)[0]

        def w(i):
            return struct.unpack_from("<i", ch, o + 36 + 4 * i)[0]
        if typ == 0:
            nv, nf, ne = w(20), w(21), w(22)
            back = w(27)
            faces = o + 36 + 29 * 4 + 8 + 512 + ne * 32
        else:
            k = 0 if typ == 1 else 1
            nv, nf, ne, nl = w(9 + k), w(10 + k), w(11 + k), w(12 + k)
            back = w(15 + k)
            faces = (o + 36 + (16 + k) * 4 + (12 if typ == 1 else 8) + 512
                     + ne * 32 + nl * 16)
        verts = faces + nf * 16
        tris = []
        for f in range(nf):
            idx = struct.unpack_from("<3i", ch, faces + 16 * f)
            tris.append([struct.unpack_from("<2f", ch, verts + 8 * i)
                         for i in idx])
        out.append((typ, back, tris))
    return out


def centroid(tri):
    return (sum(v[0] for v in tri) / 3.0, sum(v[1] for v in tri) / 3.0)


# A built highlight: type, name, Backwards, its triangles' corners and the
# shake bank, as a camera block the parser reads.
def built_cam(typ, name, back, verts, faces, bank=0):
    nb = (name.encode("latin-1") + bytes(32))[:32]
    fov = struct.pack("<128I", *[fb(40.0 + i) for i in range(128)])
    if typ == 0:
        words = [fb(0.5)] * 29
        words[20], words[21], words[22] = len(verts), len(faces), 0
        words[23], words[24] = fb(3.0), 0
        words[25], words[26] = fb(0.25), fb(900.0)
        words[27], words[28] = back, bank
        head = struct.pack("<i", 0) + nb + struct.pack(
            "<29I", *[v & M32 for v in words]) + bytes(8)
    else:
        k = 0 if typ == 1 else 1
        words = [fb(0.75)] * (16 + k)
        words[9 + k], words[10 + k] = len(verts), len(faces)
        words[11 + k], words[12 + k] = 0, 0
        words[13 + k], words[14 + k] = fb(0.5), fb(800.0)
        words[15 + k] = back
        head = struct.pack("<i", typ) + nb + struct.pack(
            "<%dI" % (16 + k), *[v & M32 for v in words]) \
            + bytes(12 if typ == 1 else 8)
    body = head + fov
    for f in faces:
        body += struct.pack("<4i", f[0], f[1], f[2], 0)
    for v in verts:
        body += struct.pack("<2f", v[0], v[1])
    return body


def square(x0, y0, x1, y1):
    """Two triangles over the rectangle."""
    return ([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            [(0, 1, 2), (0, 2, 3)])


def built_highlights(base, cams, vortex=7):
    kids = [(ccc.VORTEX_C, struct.pack("<4I", 1, 2, 3, vortex))]
    for c in cams:
        kids.append((ccc.HIGHLIGHT_C, c))
    return ccc.build(base, ccc.HIGHLIGHTS, kids)


# ---------------------------------------------------------------- scenarios

FAR = 5000.0


def reset_world(sc):
    """Everything back as the model and the harness start it, cars at the
    origin facing +y, boxes of a car's size, cameras far off and clear."""
    sc.op(OP_SINIT)
    sc.op(OP_SEED, 0x1234abcd)
    sc.op(OP_TIME, 1)
    sc.op(OP_DIR, 0)
    sc.op(OP_VMODE, 0)
    sc.op(OP_FOVZ, 9102)
    sc.op(OP_CAMQ, -1)
    sc.op(OP_CAMDEF, 0)
    sc.op(OP_UPCAM, -1)
    for c in range(NCARS):
        sc.car_pos(c, 0.0, 0.0, 0.0)
        sc.car_mat(c, IDENT)
        sc.car_box(c, (-1.0, -2.0, -0.5), (1.0, 2.0, 0.75))
        sc.op(OP_CARV, c, CV_WRONG, 0)
        sc.op(OP_CARV, c, CV_FULL, 4)
        sc.op(OP_CARV, c, CV_SPLIT, 2)
    for k in range(NCAMS):
        sc.cam_mat(k, ident_at(0.0, 0.0, 100.0))
        sc.cam_pos(k, FAR + 10 * k, FAR, FAR)
        sc.cam_near(k, 0.5)
    sc.world(0)
    for p in range(2):
        sc.op(OP_PSET, p, P_MYCAR, p)
        sc.op(OP_PSET, p, P_VIEW, p + 1)
        sc.op(OP_PSET, p, P_DEMO, -1)
    for m in range(NMOVERS):
        sc.op(OP_MCAM, m, 0)


def near_scenarios(sc, rnd):
    # Hand-made: the car's box straddling the plane, wholly in front,
    # wholly behind, a corner on it, the FOV scaling.
    sc.tag("near plane, by hand")
    reset_world(sc)
    sc.car_box(0, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    for tz, near in ((0.0, 0.5), (10.0, 0.5), (-10.0, 0.5), (1.5, 0.5),
                     (1.5, 0.25), (-0.5, 0.5), (0.5, 0.5), (-1.5, 0.5),
                     (2.0, 1.0), (0.0, 0.0), (3.0, 4.5)):
        sc.cam_mat(1, ident_at(0.0, 0.0, tz))
        sc.cam_near(1, near)
        sc.op(OP_NEAR, 1, 0)
    # The FOV scales the plane: tan(baseline/2) / tan(fov/2).
    sc.cam_mat(1, ident_at(0.0, 0.0, 1.25))
    for fov, fovz in ((9102, 9102), (4551, 9102), (18204, 9102),
                      (9102, 4000), (16384, 9102), (12000, 7000),
                      (2, 9102), (9102, 0)):
        sc.op(OP_FOVZ, fovz)
        sc.cam_near(1, 0.5, fov)
        sc.op(OP_NEAR, 1, 0)
    sc.op(OP_FOVZ, 9102)
    # Each pair of corners next to each other in the order: a box whose
    # corners all sit on one side but one.
    sc.car_box(0, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    for ang in range(0, 360, 30):
        sc.car_mat(0, rot_z(math.radians(ang)))
        sc.cam_mat(1, rand_rot(random.Random(ang), (0.0, 0.0, 0.3)))
        sc.op(OP_NEAR, 1, 0)
    # The car's position is in its matrix's last row.
    sc.car_mat(0, IDENT)
    for z in (-5.0, -1.2, 0.0, 0.8, 5.0):
        sc.car_pos(0, 3.0, -2.0, z)
        sc.cam_mat(1, ident_at(0.0, 0.0, 0.0))
        sc.op(OP_NEAR, 1, 0)
    # Corners exactly on the plane: a sign change across them is missed, so
    # the corners' order shows. z = (x + y) / 2 and (x - y) / 2 over a unit
    # box, the plane at 0.
    sc.car_pos(0, 0.0, 0.0, 0.0)
    sc.car_box(0, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    for s in (0.5, -0.5):
        sc.cam_mat(1, (1.0, 0.0, 0.5, 0.0, 0.0, 1.0, s, 0.0,
                       0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        sc.cam_near(1, 0.0)
        sc.op(OP_NEAR, 1, 0)

    sc.tag("near plane, at random")
    reset_world(sc)
    for i in range(400):
        c = i % NCARS
        k = i % NCAMS
        lo = [rnd.uniform(-3, 0) for _ in range(3)]
        hi = [rnd.uniform(0, 3) for _ in range(3)]
        sc.car_box(c, lo, hi)
        pos = (rnd.uniform(-20, 20), rnd.uniform(-20, 20),
               rnd.uniform(-5, 5))
        sc.car_pos(c, *pos)
        sc.car_mat(c, rand_rot(rnd, (0.0, 0.0, 0.0)))
        near = rnd.choice((0.1, 0.5, 1.0, rnd.uniform(0, 4)))
        rot = rand_rot(rnd, (0.0, 0.0, 0.0))
        t = [rnd.uniform(-20, 20) for _ in range(3)]
        if i & 1:
            # The car's middle near the plane, the box often across it.
            t[2] = near - sum(pos[j] * rot[4 * j + 2] for j in range(3)) \
                + rnd.uniform(-3, 3)
        sc.cam_mat(k, rot[:12] + (t[0], t[1], t[2], 1.0))
        sc.cam_near(k, near,
                    rnd.choice((9102, 4000, 12000, rnd.randrange(1, 30000))))
        if i % 50 == 0:
            sc.op(OP_FOVZ, rnd.randrange(2000, 16000))
        sc.op(OP_NEAR, k, c)


def look_scenarios(sc, rnd):
    # WillLookGood and FindGoodLookingHighlightCamera on built highlights:
    # areas that hold the car or not, every Backwards against the track's
    # direction and the car's wrong way.
    sc.tag("find, built")
    reset_world(sc)
    v0, f0 = square(-10, -10, 10, 10)
    v1, f1 = square(20, -10, 40, 10)
    v2, f2 = square(-10, -10, 10, 10)
    cams = [built_cam(0, "Fwd0", 0, v0, f0, 1),
            built_cam(0, "Back0", 1, v0, f0, 2),
            built_cam(1, "Fwd1", 0, v1, f1),
            built_cam(2, "Back2", 1, v1, f1),
            built_cam(2, "Fwd2", 0, v2, f2),
            built_cam(1, "Back1", 7, v2, f2),
            built_cam(0, "Empty", 0, [], []),
            # A face whose corners run the other way, and one of three
            # faces holding the point.
            built_cam(0, "Odd", 0, [(50, 50), (60, 50), (55, 60), (0, 0)],
                      [(2, 1, 0), (0, 3, 1), (1, 2, 3)]),
            # Backwards neither 0 nor 1, alone on their areas.
            built_cam(1, "Back7", 7, *square(-60, -60, -40, -40)),
            built_cam(2, "BackNeg", -1, *square(-100, -60, -80, -40))]
    hl = built_highlights(0x40000, cams)
    sc.put(0x40000, hl)
    sc.op(OP_LOAD, 0x40000)
    sc.op(OP_DCNEW, 0, 1, 0)
    for pos in ((0, 0), (30, 0), (55, 53), (100, 100), (10, 0), (-10, -10),
                (10, 10), (20, 0), (9.999, -9.999), (55, 50), (-50, -50),
                (-90, -50)):
        sc.car_pos(0, pos[0], pos[1], 2.0)
        for d in (0, 1, 2, -1):
            sc.op(OP_DIR, d)
            for ww in (0, 1, 5):
                sc.op(OP_CARV, 0, CV_WRONG, ww)
                sc.op(OP_FIND, 0, 0)
        for i in range(len(cams)):
            sc.op(OP_WLG, 0, i, 0)
    sc.op(OP_DCDEL, 0, 0)
    sc.op(OP_UNLOAD, 0x40000)

    # The disc's: cars at each face's middle and between.
    for name, hl_off, fb_off in ccc.TRACKS[:1] + ccc.TRACKS[4:]:
        d = ccc.disc("TRACKS/" + name)
        hl = ccc.chunk_at(d, hl_off)
        areas = highlight_areas(hl, 0x40000)
        sc.tag("find, %s" % name)
        reset_world(sc)
        sc.put(0x40000, hl)
        sc.op(OP_LOAD, 0x40000)
        sc.op(OP_DCNEW, 1, 1, 2)
        picks = list(range(0, len(areas), max(1, len(areas) // 24)))
        for j in picks:
            typ, back, tris = areas[j]
            if not tris:
                continue
            x, y = centroid(tris[rnd.randrange(len(tris))])
            sc.car_pos(2, x, y, 10.0)
            for d_, ww in ((0, 0), (1, 0), (0, 1), (1, 1)):
                sc.op(OP_DIR, d_)
                sc.op(OP_CARV, 2, CV_WRONG, ww)
                sc.op(OP_FIND, 1, 2)
            sc.op(OP_WLG, 1, j, 2)
            sc.op(OP_WLG, 1, (j + 1) % len(areas), 2)
        sc.op(OP_DCDEL, 1, 0)
        sc.op(OP_UNLOAD, 0x40000)


def load_shakes(sc):
    if not ccc.DISC.exists():
        return
    ing = ccc.disc(ccc.INGAMEB[0])
    shakes = ccc.chunk_at(ing, 0x1e2f80)
    sc.put(0x20000, shakes)
    sc.op(OP_LOAD, 0x20000)


def update_scenarios(sc, rnd):
    v0, f0 = square(-10, -10, 10, 10)
    v1, f1 = square(20, -10, 40, 10)
    v2, f2 = square(60, -10, 80, 10)
    cams = [built_cam(0, "A0", 0, v0, f0, 1),
            built_cam(1, "B1", 0, v1, f1),
            built_cam(2, "C2", 0, v2, f2),
            built_cam(0, "A0back", 1, v0, f0, 3),
            built_cam(0, "D0", 0, v2, f2, 9)]
    hl = built_highlights(0x40000, cams, vortex=11)

    def fresh(title, seed=0x1234abcd):
        sc.tag(title)
        reset_world(sc)
        sc.op(OP_SEED, seed)
        load_shakes(sc)
        sc.put(0x40000, hl)
        sc.op(OP_LOAD, 0x40000)

    # A camera built, kept, swapped as the car drives across the areas,
    # and the drive camera between them.
    fresh("update, across the areas")
    sc.op(OP_JUNKK, 0, 0xa5)
    sc.op(OP_DCNEW, 0, 1, 0)
    sc.op(OP_DUMPK)
    t = 100
    for x in (0, 1, 5, 9, 15, 22, 30, 39, 45, 50, 61, 70, 79, 85, 95, 3,
              -5, 25):
        for step in (0, 20, 55, 56, 60):
            sc.op(OP_TIME, t + step)
            sc.car_pos(0, float(x), 0.0, 1.0)
            sc.update(0)
        t += 61
    sc.op(OP_DUMPK)
    sc.op(OP_DCDEL, 0, 3)
    sc.op(OP_DUMPK)

    # The reload mark, with the camera up only a frame.
    fresh("update, reload")
    sc.op(OP_JUNKK, 1, 0x00)
    sc.op(OP_DCNEW, 1, 2, 0)
    sc.car_pos(0, 0.0, 0.0, 1.0)
    sc.op(OP_TIME, 50)
    sc.update(1)
    for t, need, x in ((51, 0, 0.0), (52, 1, 0.0), (53, 1, 30.0),
                       (54, 5, 100.0), (55, 0, 100.0), (130, 0, 100.0),
                       (131, 1, 70.0), (132, 0, 70.0), (200, 0, 70.0)):
        sc.op(OP_TIME, t)
        sc.op(OP_SETF, 1, F_NEED, need)
        sc.car_pos(0, x, 0.0, 1.0)
        sc.update(1)
    sc.op(OP_DCDEL, 1, 3)

    # A camera built too near a car, or cutting its own: deleted, and the
    # drive camera instead. Then one gone bad while it is showing.
    fresh("update, near")
    sc.world(0, 1, 2)
    sc.car_pos(1, 500.0, 500.0, 0.0)
    sc.car_pos(2, -500.0, 0.0, 0.0)
    sc.op(OP_DCNEW, 2, 1, 0)
    sc.car_pos(0, 0.0, 0.0, 1.0)
    t = 10
    # cam1 within 5 of car1, cam2 within 2 of car2, cam3 cutting car0,
    # cam4 at 4.99 and 5.0 and 5.01, cam5 clear.
    sc.cam_pos(1, 503.0, 501.0, 0.0)
    sc.cam_pos(2, -501.0, 1.0, 0.5)
    sc.cam_mat(3, ident_at(0.0, 0.0, -1.0))
    sc.cam_pos(4, -500.0, 0.0, 4.99)
    for cam, x in ((1, 0.0), (2, 30.0), (3, 70.0), (4, 0.0), (5, 30.0),
                   (0, 70.0)):
        sc.op(OP_CAMQ, cam)
        sc.op(OP_TIME, t)
        sc.op(OP_SETF, 2, F_NEED, 1)
        sc.car_pos(0, x, 0.0, 1.0)
        sc.update(2)
        t += 100
    for z in (5.0, 5.01, 1.99, 2.0):
        sc.cam_pos(4, -500.0, 0.0, z)
        sc.op(OP_CAMQ, 4)
        sc.op(OP_TIME, t)
        sc.op(OP_SETF, 2, F_NEED, 1)
        sc.car_pos(0, 0.0, 0.0, 1.0)
        sc.update(2)
        t += 100
    # Up and showing: a car comes within 2 of the camera, or the plane
    # cuts the car, after 56 frames and before.
    sc.op(OP_CAMQ, 5)
    sc.op(OP_TIME, t)
    sc.op(OP_SETF, 2, F_NEED, 1)
    sc.update(2)
    for dt, cpos in ((10, (FAR + 50 - 1.0, FAR, FAR)),
                     (55, (FAR + 50 - 1.5, FAR, FAR)),
                     (56, (FAR + 50 - 1.5, FAR, FAR)),
                     (57, (FAR + 50 - 3.0, FAR, FAR))):
        sc.car_pos(1, *cpos)
        sc.op(OP_TIME, t + dt)
        sc.update(2)
    t += 200
    sc.car_pos(1, 500.0, 500.0, 0.0)
    sc.op(OP_CAMQ, 5)
    sc.op(OP_TIME, t)
    sc.op(OP_SETF, 2, F_NEED, 1)
    sc.update(2)
    sc.cam_mat(5, ident_at(0.0, 0.0, 0.0))
    for dt in (30, 56, 57):
        sc.op(OP_TIME, t + dt)
        sc.update(2)
    sc.cam_mat(5, ident_at(0.0, 0.0, 100.0))
    # The mover's Update moves it onto a camera too near.
    t += 200
    sc.op(OP_CAMQ, 5)
    sc.op(OP_UPCAM, 1)
    sc.cam_pos(1, 1.0, 0.0, 1.0)
    sc.op(OP_TIME, t)
    sc.op(OP_SETF, 2, F_NEED, 1)
    sc.update(2)
    sc.op(OP_UPCAM, 5)
    sc.op(OP_CAMQ, 1)
    sc.op(OP_TIME, t + 100)
    sc.op(OP_SETF, 2, F_NEED, 1)
    sc.update(2)
    sc.op(OP_DUMPK)
    sc.op(OP_DCDEL, 2, 3)

    # The drive camera's POV: none, one, several, the split screen's, and
    # the look-back flipping.
    fresh("update, drive")
    sc.op(OP_DCNEW, 3, 1, 0)
    sc.car_pos(0, 500.0, 500.0, 1.0)
    t = 10
    for full, split, vm in ((4, 2, 0), (4, 2, 3), (1, 0, 0), (1, 0, 3),
                            (0, 3, 0), (0, 0, 3), (2, 2, 1), (3, 1, 3),
                            (-1, -2, 0), (-1, -2, 3), (7, 5, 2),
                            (2, 7, 3)):
        sc.op(OP_CARV, 0, CV_FULL, full)
        sc.op(OP_CARV, 0, CV_SPLIT, split)
        sc.op(OP_VMODE, vm)
        for rep in range(4):
            sc.op(OP_TIME, t)
            sc.op(OP_SETF, 3, F_NEED, 1)
            sc.update(3)
            t += 3
    # The POV kept, then equal to the draw: each wraps.
    sc.op(OP_CARV, 0, CV_FULL, 3)
    sc.op(OP_VMODE, 0)
    for pov in (0, 1, 2, 3, -1, 7):
        for seed in (1, 2, 3, 0x7fffffff):
            sc.op(OP_SEED, seed)
            sc.op(OP_SETF, 3, F_POV, pov)
            sc.op(OP_SETF, 3, F_LOOK, seed & 3)
            sc.op(OP_SETF, 3, F_NEED, 1)
            sc.update(3)
    # The drive camera up: before 56 frames nothing, after it a highlight
    # is looked for and with none nothing changes.
    sc.op(OP_TIME, 1000)
    sc.op(OP_SETF, 3, F_NEED, 1)
    sc.update(3)
    for dt in (1, 55, 56, 57, 200):
        sc.op(OP_TIME, 1000 + dt)
        sc.update(3)
    sc.car_pos(0, 0.0, 0.0, 1.0)
    sc.op(OP_TIME, 1300)
    sc.update(3)
    # A highlight up whose area no longer holds the car, none found: the
    # drive camera.
    sc.car_pos(0, 500.0, 0.0, 1.0)
    sc.op(OP_TIME, 1400)
    sc.update(3)
    sc.op(OP_DUMPK)
    sc.op(OP_DCDEL, 3, 3)

    # Movers set by hand: the start time junk, the active camera out of
    # the way, a disabled coordinator (Update does not look).
    fresh("update, by hand")
    sc.op(OP_JUNKK, 4, 0x5c)
    sc.op(OP_DCNEW, 4, 1, 0)
    sc.op(OP_SETMOVER, 4, 2)
    sc.op(OP_MCAM, 2, 6)
    sc.car_pos(0, 0.0, 0.0, 1.0)
    sc.op(OP_TIME, 5)
    sc.update(4)
    sc.op(OP_SETF, 4, F_START, 0)
    sc.op(OP_SETF, 4, F_ACTIVE, 0)
    for t, act, x in ((40, 0, 0.0), (56, 0, 0.0), (57, 0, 30.0),
                      (100, 1, 30.0), (200, 4, 30.0), (300, 4, 70.0),
                      (400, -1, 70.0), (500, 2, 70.0)):
        sc.op(OP_SETMOVER, 4, 1)
        sc.op(OP_SETF, 4, F_START, 0)
        sc.op(OP_SETF, 4, F_ACTIVE, act)
        sc.op(OP_TIME, t)
        sc.car_pos(0, x, 0.0, 1.0)
        sc.update(4)
    sc.op(OP_SETMOVER, 4, -1)
    sc.op(OP_SETF, 4, F_DIS, 1)
    sc.op(OP_SETF, 4, F_VIEW, 2)
    sc.op(OP_SETF, 4, F_VORTEX, 99)
    sc.op(OP_SETF, 4, F_CAR, 1)
    sc.car_pos(1, 30.0, 0.0, 1.0)
    sc.op(OP_TIME, 600)
    sc.op(OP_UPDATEALL, fb(0.25))
    sc.op(OP_SETF, 4, F_DIS, 0)
    sc.op(OP_UPDATEALL, fb(0.5))
    sc.op(OP_DUMPK)
    sc.op(OP_DCDEL, 4, 3)

    # The world without the car it shows, and with cars on the camera.
    fresh("update, the world's cars")
    sc.world()
    sc.op(OP_DCNEW, 5, 1, 3)
    sc.car_pos(3, 0.0, 0.0, 1.0)
    sc.op(OP_TIME, 10)
    sc.update(5)
    sc.op(OP_TIME, 100)
    sc.update(5)
    sc.world(4, 5, 3)
    sc.car_pos(4, FAR - 1, FAR, FAR)
    sc.car_pos(5, FAR, FAR, FAR + 1.0)
    sc.op(OP_TIME, 200)
    sc.update(5)
    sc.op(OP_SETF, 5, F_NEED, 1)
    sc.op(OP_CAMQ, 2)
    sc.op(OP_TIME, 300)
    sc.update(5)
    sc.op(OP_DCDEL, 5, 3)


def disc_update_scenarios(sc, rnd):
    # The disc's highlights, a car driven through them: each camera built
    # where its area holds the car, the drive camera between.
    for name, hl_off, fb_off in ccc.TRACKS[:1] + ccc.TRACKS[4:5]:
        d = ccc.disc("TRACKS/" + name)
        hl = ccc.chunk_at(d, hl_off)
        areas = highlight_areas(hl, 0x40000)
        for direction in (0, 1):
            sc.tag("drive through %s, direction %d" % (name, direction))
            reset_world(sc)
            sc.op(OP_SEED, 0x600d5eed + direction)
            load_shakes(sc)
            sc.put(0x40000, hl)
            sc.op(OP_LOAD, 0x40000)
            sc.op(OP_DIR, direction)
            sc.world(0, 1)
            sc.op(OP_DCNEW, 0, 1, 0)
            t = 1
            for step in range(60):
                j = rnd.randrange(len(areas))
                typ, back, tris = areas[j]
                if tris and step % 5:
                    x, y = centroid(tris[rnd.randrange(len(tris))])
                else:
                    x, y = rnd.uniform(-3000, 3000), rnd.uniform(-3000, 3000)
                sc.car_pos(0, x, y, rnd.uniform(-10, 40))
                sc.car_pos(1, x + rnd.uniform(-8, 8), y + rnd.uniform(-8, 8),
                           0.0)
                sc.op(OP_CARV, 0, CV_WRONG, int(rnd.random() < 0.2))
                if step % 7 == 3:
                    sc.op(OP_CAMQ, rnd.randrange(NCAMS))
                t += rnd.choice((1, 20, 56, 57, 90))
                sc.op(OP_TIME, t)
                sc.update(0)
            sc.op(OP_DUMPK)
            sc.op(OP_DCDEL, 0, 3)
            sc.op(OP_UNLOAD, 0x40000)


def begin_scenarios(sc):
    sc.tag("begin demo cameras")
    reset_world(sc)
    v0, f0 = square(-10, -10, 10, 10)
    sc.put(0x40000, built_highlights(0x40000, [built_cam(1, "P", 0, v0,
                                                         f0)]))
    sc.op(OP_LOAD, 0x40000)
    sc.op(OP_DUMPP)
    sc.op(OP_BEGIN, 0, -1)
    sc.op(OP_DUMPP)
    sc.op(OP_BEGIN, 0, 3)
    sc.op(OP_DUMPP)
    sc.op(OP_BEGIN, 1, 4)
    sc.op(OP_DUMPP)
    sc.op(OP_DUMPK)
    sc.op(OP_UPDATEALL, fb(0.0))
    sc.op(OP_DUMPK)
    sc.op(OP_PSET, 1, P_DEMO, -1)
    sc.op(OP_PSET, 1, P_VIEW, 7)
    sc.op(OP_PSET, 1, P_MYCAR, 5)
    sc.op(OP_BEGIN, 1, -1)
    sc.op(OP_DUMPP)
    sc.op(OP_DUMPK)


def script():
    sc = Script()
    rnd = random.Random(0xdec0de)
    near_scenarios(sc, random.Random(0x9ea4))
    look_scenarios(sc, rnd)
    update_scenarios(sc, rnd)
    begin_scenarios(sc)
    if ccc.DISC.exists():
        disc_update_scenarios(sc, random.Random(0xd15c))
    return sc


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        # eMulVector adds its vector into the (0, 0, 0, 1) this one writes.
        e.call(EMATH_SINIT)
        self.heap = []                  # (addr, label)
        self.camq = []
        self.camdef = 0
        self.upcam = -1
        self.vmode = 0
        self.wrong = [0] * NCARS
        self.box = [[(0, 0, 0), (0, 0, 0)] for _ in range(NCARS)]
        e.mem[ARENA:ARENA + ARENA_SIZE] = bytes(ARENA_SIZE)
        for base, n in ((KS, 0x1000), (MOVERS, 0x1000), (PLAYERS, 0x1000),
                        (CARS, 0x2000), (INFOS, 0x2000), (WORLD, 0x100),
                        (CAMS, 0x1000), (FMVT, 0x1000)):
            e.mem[base:base + n] = bytes(n)
        for i in range(NMOVERS):
            e.put32(MOVERS + 0x100 * i + 40, FMVT)
        for i in range(NCARS):
            e.put32(CARS + 0x200 * i + 12, INFOS + 0x400 * i)
        for slot, fn in ((8, FMVT_DTOR), (16, FMVT_UPDATE),
                         (96, FMVT_ENABLE), (104, FMVT_DISABLE)):
            e.put32(FMVT + slot + 4, fn)
        e.put32(WORLD, WORLD)
        e.put32(WORLD + 4, WORLD)
        e.put32(WORLD_P, WORLD)
        self.stubs()

    def emit(self, s):
        self.out.append(s)

    def w(self, a):
        return self.e.u32(a)

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        if ARENA - NEAR <= a < ARENA + ARENA_SIZE + NEAR:
            return "a%+d" % (a - ARENA)
        if a == LIST:
            return "list"
        if a == WORLD:
            return "world"
        for name, base, n, step in (("k", KS, NK, 0x100),
                                    ("m", MOVERS, NMOVERS, 0x100),
                                    ("p", PLAYERS, 2, 0x100),
                                    ("car", CARS, NCARS, 0x200),
                                    ("cam", CAMS, NCAMS, 0x100)):
            for i in range(n):
                if a == base + step * i:
                    return "%s%d" % (name, i)
        for base, lab in self.heap:
            if a == base:
                return lab
        return "?"

    def car_no(self, a):
        return ((a & M32) - CARS) // 0x200

    # ---- the stand-ins ---------------------------------------------------

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def cstr(p):
            end = e.mem.index(b"\0", p)
            return e.mem[p:end].decode("latin-1")

        def malloc(em):
            size = s32(arg(0))
            span = max(size, 0) + SLACK
            p = e.alloc(span, align=16)
            e.mem[p:p + span] = bytes([0xcd]) * span
            lab = "h%d" % len(self.heap)
            self.heap.append((p, lab))
            self.emit("  alloc %s size %d name %s flags %d pool %d"
                      % (lab, size, cstr(arg(1)), s32(arg(2)), s32(arg(3))))
            return p

        def free(em):
            self.emit("  free %s" % self.label(arg(0)))

        def wrong_way(em):
            c = self.car_no(arg(0))
            self.emit("  wrongway %s" % self.label(arg(0)))
            return s32(self.wrong[c])

        def bbox(em):
            c = self.car_no(arg(0))
            self.emit("  bbox %s" % self.label(arg(0)))
            for p, v in ((arg(1), self.box[c][0]), (arg(2), self.box[c][1])):
                for i in range(3):
                    e.put32(p + 4 * i, v[i])

        def view_mode(em):
            self.emit("  viewmode")
            return s32(self.vmode)

        def change(em):
            self.emit("  change %s %d %d" % (self.label(arg(0)), s32(arg(1)),
                                            s32(arg(2))))

        def give_camera(m):
            cam = self.camq.pop(0) if self.camq else self.camdef
            e.put32(m + 40, FMVT)
            e.put32(m + 24, CAMS + 0x100 * cam)
            return "cam%d" % cam

        def trackcar(em):
            m = arg(0)
            self.emit("  trackcar %s view %d car %s focus %d %s"
                      % (self.label(m), s32(arg(1)), self.label(arg(2)),
                         s32(arg(5)), give_camera(m)))
            self.dump_cd("  trackcar cd", arg(3))
            sh = arg(4)
            words = ["%d:%08x" % (o, self.w(sh + o)) for o in range(0, 560, 4)
                     if self.w(sh + o)]
            self.emit("  shake" + "".join(" " + x for x in words))
            return m

        def bumper(em):
            m = arg(0)
            self.emit("  bumper %s view %d car %s %s"
                      % (self.label(m), s32(arg(1)), self.label(arg(2)),
                         give_camera(m)))
            self.dump_cd("  bumper cd", arg(3))
            return m

        def trackfly(em):
            m = arg(0)
            self.emit("  trackfly %s view %d car %s %s"
                      % (self.label(m), s32(arg(1)), self.label(arg(3)),
                         give_camera(m)))
            self.dump_cd("  trackfly cd", arg(2))
            return m

        def drive(em):
            m = arg(0)
            self.emit("  drive %s view %d car %s pov %d speed %s lag %d "
                      "back %d focus %d %s"
                      % (self.label(m), s32(arg(1)), self.label(arg(2)),
                         s32(arg(3)), fx(e.fpr[12]), s32(arg(4)),
                         s32(arg(5)), s32(arg(6)), give_camera(m)))
            return m

        def mover_dtor(em):
            self.emit("  mover dtor %s" % self.label(arg(0)))
            if arg(1) & 1:
                self.emit("  free %s" % self.label(arg(0)))

        def mover_update(em):
            m = arg(0)
            if self.upcam >= 0:
                e.put32(m + 24, CAMS + 0x100 * self.upcam)
                self.upcam = -1
            self.emit("  mover update %s %s" % (self.label(m),
                                                self.label(self.w(m + 24))))

        def mover_enable(em):
            self.emit("  mover enable %s" % self.label(arg(0)))

        def mover_disable(em):
            self.emit("  mover disable %s" % self.label(arg(0)))

        e.stub(BMALLOC, malloc)
        e.stub(BFREE, free)
        e.stub(BDELETE, free)
        e.stub(WRONG_WAY, wrong_way)
        e.stub(BBOX, bbox)
        e.stub(VIEW_MODE, view_mode)
        e.stub(CHANGE, change)
        e.stub(TRACKCAR, trackcar)
        e.stub(BUMPER, bumper)
        e.stub(TRACKFLY, trackfly)
        e.stub(DRIVE, drive)
        e.stub(FMVT_DTOR, mover_dtor)
        e.stub(FMVT_UPDATE, mover_update)
        e.stub(FMVT_ENABLE, mover_enable)
        e.stub(FMVT_DISABLE, mover_disable)

    # ---- the dumps -------------------------------------------------------

    def dump_cd(self, head, a):
        w = self.w
        typ = s32(w(a))
        s = [head]
        for off, ptr in ccc.CD_FIELDS:
            if off > 4 and not 0 <= typ <= 2:
                break
            if off in ccc.CD_TYPE2_ONLY and typ != 2:
                continue
            if off in ccc.CD_TYPE0_ONLY and typ != 0:
                continue
            v = w(a + off)
            s.append(" " + (self.label(v) if ptr else "%08x" % v))
        self.emit("".join(s))

    def coord_line(self, c):
        w = self.w
        return "  %s %s %s %s %08x %08x %08x %08x %s %08x %08x %08x %08x " \
            "%08x" % (self.label(c), self.label(w(c)), self.label(w(c + 4)),
                      self.label(w(c + 8)), w(c + 12), w(c + 16), w(c + 20),
                      w(c + 24), self.label(w(c + 28)), w(c + 32), w(c + 36),
                      w(c + 40), w(c + 44), w(c + 48))

    def dump_coordinators(self):
        w = self.w
        fwd, n, g = [], w(LIST), 0
        while n != LIST and g < 64:
            fwd.append(n)
            n, g = w(n), g + 1
        self.emit("coordinators" + "".join(" " + self.label(x)
                                           for x in fwd))
        for c in fwd:
            self.emit(self.coord_line(c))

    def dump_players(self):
        self.emit("players")
        for i in range(2):
            p = PLAYERS + 0x100 * i
            self.emit("  p%d car %s view %08x demo %s" % (
                i, self.label(self.w(p + 4)), self.w(p + 24),
                self.label(self.w(p + 216))))

    # ---- the run ---------------------------------------------------------

    def k(self, i):
        return KS + 0x100 * i

    def car(self, i):
        return 0 if s32(i) < 0 else CARS + 0x200 * (s32(i) % NCARS)

    def at(self, off):
        return 0 if s32(off) == -1 else ARENA + off

    # The ints the script hands a call go in sign-extended, as the EE's
    # registers hold them.
    def run(self, sc):
        e, w = self.e, self.w
        tags = sc.tags
        for o in sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                self.emit("[%s]" % tags[a[0]])
            elif code == OP_PUT:
                off, n = a[0], a[1]
                data = struct.pack("<%dI" % len(a[2:]), *a[2:])[:n]
                e.mem[ARENA + off:ARENA + off + n] = data
            elif code == OP_SINIT:
                e.call(SINIT)
            elif code == OP_LOAD:
                self.emit("load %s -> %d" % (self.label(self.at(a[0])),
                                             e.call(LOADER_CAMERAS,
                                                    self.at(a[0]))))
            elif code == OP_UNLOAD:
                self.emit("unload %s -> %d" % (self.label(self.at(a[0])),
                                               e.call(UNLOADER_CAMERAS,
                                                      self.at(a[0]))))
            elif code == OP_SEED:
                e.put32(SEED, a[0])
            elif code == OP_TIME:
                e.put32(FRAMES, a[0])
            elif code == OP_DIR:
                e.put32(TRACK_DIR, a[0])
            elif code == OP_VMODE:
                self.vmode = a[0]
            elif code == OP_FOVZ:
                e.mem[FOVZ:FOVZ + 2] = struct.pack("<H", a[0] & 0xffff)
            elif code == OP_CARV:
                c, f, v = a
                base = CARS + 0x200 * c
                if f < CV_MAT:
                    e.put32(base + 96 + 4 * f, v)
                elif f < CV_MIN:
                    e.put32(base + 144 + 4 * (f - CV_MAT), v)
                elif f < CV_MAX:
                    b = list(self.box[c][0])
                    b[f - CV_MIN] = v
                    self.box[c][0] = tuple(b)
                elif f < CV_WRONG:
                    b = list(self.box[c][1])
                    b[f - CV_MAX] = v
                    self.box[c][1] = tuple(b)
                elif f == CV_WRONG:
                    self.wrong[c] = v
                elif f == CV_FULL:
                    e.put32(INFOS + 0x400 * c + 960, v)
                elif f == CV_SPLIT:
                    e.put32(INFOS + 0x400 * c + 964, v)
            elif code == OP_WCLEAR:
                e.put32(WORLD, WORLD)
                e.put32(WORLD + 4, WORLD)
            elif code == OP_WADD:
                c = CARS + 0x200 * a[0]
                last = w(WORLD + 4)
                e.put32(c, WORLD)
                e.put32(c + 4, last)
                e.put32(last, c)
                e.put32(WORLD + 4, c)
            elif code == OP_CAMV:
                k, f, v = a
                base = CAMS + 0x100 * k
                if f < KV_NEAR:
                    e.put32(base + 4 * f, v)
                elif f == KV_NEAR:
                    e.put32(base + 124, v)
                else:
                    e.mem[base + 132:base + 134] = struct.pack(
                        "<H", v & 0xffff)
            elif code == OP_CAMQ:
                if s32(a[0]) < 0:
                    self.camq = []
                else:
                    self.camq.append(a[0])
            elif code == OP_CAMDEF:
                self.camdef = a[0]
            elif code == OP_UPCAM:
                self.upcam = s32(a[0])
            elif code == OP_JUNKK:
                k, b = a
                c = self.k(k)
                e.mem[c:c + 0x100] = bytes([b & 0xff]) * 0x100
            elif code == OP_DCNEW:
                k, view, car = a
                self.emit("dcnew k%d %d %s" % (k, s32(view),
                                               self.label(self.car(car))))
                r = e.call(DC_CTOR, self.k(k), s32(view), self.car(car))
                self.emit("dcnew -> %s" % self.label(r))
                self.emit(self.coord_line(self.k(k)))
            elif code == OP_DCUPDATE:
                k, dt = a
                self.emit("update k%d %08x t %d" % (k, dt, s32(w(FRAMES))))
                e.fpr[12] = dt
                e.call(DC_UPDATE, self.k(k))
                self.emit(self.coord_line(self.k(k)))
                self.emit("  seed %08x" % w(SEED))
            elif code == OP_DCDEL:
                k, flags = a
                c = self.k(k)
                self.emit("dcdel k%d %d" % (k, s32(flags)))
                vt = w(c + 24)
                delta = s32(e.u16(vt + 8) << 16) >> 16
                e.call(w(vt + 12), (c + delta) & M32, s32(flags))
            elif code == OP_SETMOVER:
                k, m = a
                e.put32(self.k(k) + 8,
                        0 if s32(m) < 0 else MOVERS + 0x100 * (m % NMOVERS))
            elif code == OP_MCAM:
                m, cam = a
                e.put32(MOVERS + 0x100 * m + 24, CAMS + 0x100 * cam)
            elif code == OP_SETF:
                k, f, v = a
                if f == F_CAR:
                    e.put32(self.k(k) + 28, self.car(v))
                else:
                    e.put32(self.k(k) + SETF_OFF[f], v)
            elif code == OP_DUMPK:
                self.dump_coordinators()
            elif code == OP_FIND:
                k, car = a
                r = e.call(DC_FIND, self.k(k), self.car(car))
                self.emit("find k%d %s -> %d" % (k, self.label(self.car(car)),
                                                 s32(r)))
            elif code == OP_WLG:
                k, idx, car = a
                data = w(LOADER + 4 + 4 * idx)
                r = e.call(DC_WLG_DATA, self.k(k), data, self.car(car))
                self.emit("wlg k%d %d %s -> %d" % (
                    k, idx, self.label(self.car(car)), s32(r)))
            elif code == OP_NEAR:
                cam, car = a
                r = e.call(NEAR_TEST, CAMS + 0x100 * cam, self.car(car))
                self.emit("near cam%d %s -> %d" % (
                    cam, self.label(self.car(car)), s32(r)))
            elif code == OP_BEGIN:
                p, car = a
                self.emit("begin p%d %s" % (p, self.label(self.car(car))))
                e.call(BEGIN, PLAYERS + 0x100 * p, self.car(car))
            elif code == OP_PSET:
                p, f, v = a
                base = PLAYERS + 0x100 * p
                if f == P_MYCAR:
                    e.put32(base + 4, self.car(v))
                elif f == P_VIEW:
                    e.put32(base + 24, v)
                else:
                    e.put32(base + 216, 0 if s32(v) < 0 else self.k(v))
            elif code == OP_DUMPP:
                self.dump_players()
            elif code == OP_UPDATEALL:
                self.emit("updateall %08x" % a[0])
                e.fpr[12] = a[0]
                e.call(UPDATE_ALL)
                self.emit("  seed %08x" % w(SEED))
            else:
                raise ValueError("op %d" % code)
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc.encode().hex().splitlines()
                               + sc.tags, lambda s: Model().run(sc),
                               cut=MUTATIONS_HEADER)


# ================================================================ the build


def build_harness(tmp, name="democam_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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

def M(name, before, after):
    return (name, DC, before, after)


MUTATIONS = [
    # -- what Update keeps a camera clear by ---------------------------------
    M("nc-shown", "#define DEMO_CAMERA_NEAR_SHOWN 2.0f",
      "#define DEMO_CAMERA_NEAR_SHOWN 1.75f"),
    M("nc-built", "#define DEMO_CAMERA_NEAR_BUILT 5.0f",
      "#define DEMO_CAMERA_NEAR_BUILT 4.5f"),
    M("dc-speed", "#define DEMO_CAMERA_LOOKBACK_SPEED 300.0f",
      "#define DEMO_CAMERA_LOOKBACK_SPEED 30.0f"),
    M("dc-split", "#define DEMO_CAMERA_SPLIT_VIEW_MODE 3",
      "#define DEMO_CAMERA_SPLIT_VIEW_MODE 2"),
    M("del-free", "    m->vtbl->Destroy(m);\n    bFree(m);", "    m->vtbl->Destroy(m);"),
    M("del-dtor", "    m->vtbl->Destroy(m);\n    bFree(m);", "    bFree(m);"),
    # -- the near-a-car loop -------------------------------------------------
    M("nc-x", "float x = eye->x - p->x,", "float x = eye->y - p->x,"),
    M("nc-y", "y = eye->y - p->y,", "y = eye->y - p->x,"),
    M("nc-z", "z = eye->z - p->z;", "z = 0.0f;"),
    M("nc-sqrt", "if (sqrtf(x * x + y * y + z * z) < d)",
      "if (x * x + y * y + z * z < d)"),
    M("nc-le", "if (sqrtf(x * x + y * y + z * z) < d)",
      "if (sqrtf(x * x + y * y + z * z) <= d)"),
    M("nc-first", "for (car = (struct Car *)w->CarList.next;",
      "for (car = (struct Car *)((struct Car *)w->CarList.next)->Link.next;"),
    M("nc-one", "         car = (struct Car *)car->Link.next) {",
      "         car = (struct Car *)(void *)&w->CarList) {"),
    M("nc-ret", "            return 1;\n    }\n    return 0;\n}\n\n// ----",
      "            return 0;\n    }\n    return 0;\n}\n\n// ----"),
    M("nc-pos", "const bVector3 *p = &car->State.Position;",
      "const bVector3 *p = &car->State.GeometryPosition;"),
    # -- the near plane ------------------------------------------------------
    M("np-row0", "world.v0 = car->State.BodyMatrix.v0;",
      "world.v0 = car->State.BodyMatrix.v1;"),
    M("np-row1", "world.v1 = car->State.BodyMatrix.v1;",
      "world.v1 = car->State.BodyMatrix.v0;"),
    M("np-row2", "world.v2 = car->State.BodyMatrix.v2;",
      "world.v2 = car->State.BodyMatrix.v1;"),
    M("np-posx", "world.v3.x = car->State.Position.x;", "world.v3.x = 0.0f;"),
    M("np-posy", "world.v3.y = car->State.Position.y;",
      "world.v3.y = car->State.Position.x;"),
    M("np-posz", "world.v3.z = car->State.Position.z;",
      "world.v3.z = car->State.Position.y;"),
    M("np-w", "world.v3.w = 1.0f;", "world.v3.w = 0.0f;"),
    M("np-order", "eMulMatrix(&m, &world, &cam->CurrentKey.Matrix);",
      "eMulMatrix(&m, &cam->CurrentKey.Matrix, &world);"),
    M("np-cx", "corner[i].x = (i & 4) ? max.x : min.x;",
      "corner[i].x = (i & 1) ? max.x : min.x;"),
    M("np-cy", "corner[i].y = (i & 2) ? max.y : min.y;",
      "corner[i].y = (i & 2) ? min.y : max.y;"),
    M("np-cz", "corner[i].z = (i & 1) ? max.z : min.z;",
      "corner[i].z = (i & 4) ? max.z : min.z;"),
    M("np-fovz", "half = (uint16_t)(aBaselineFovZ >> 1);",
      "half = (uint16_t)aBaselineFovZ;"),
    M("np-fov", "half = (uint16_t)(cam->CurrentKey.FieldOfView >> 1);",
      "half = (uint16_t)(cam->CurrentKey.FieldOfView >> 2);"),
    M("np-tb", "tb = bSinBam(half) / bCosBam(half);",
      "tb = bCosBam(half) / bSinBam(half);"),
    M("np-scale", "plane = plane * tb / tf;", "plane = plane * tf / tb;"),
    M("np-noscale", "plane = plane * tb / tf;", "(void)tb;"),
    M("np-near", "plane = cam->CurrentKey.NearZ;", "plane = 0.5f;"),
    M("np-z", "z = v.z - plane;", "z = v.y - plane;"),
    M("np-le", "if (i > 0 && z * last < 0.0f)",
      "if (i > 0 && z * last <= 0.0f)"),
    M("np-last", "            return 1;\n        last = z;", "            return 1;"),
    M("np-seven", "for (i = 0; i < 8; i++) {\n        eMulVector3",
      "for (i = 0; i < 7; i++) {\n        eMulVector3"),
    M("np-ret", "            return 1;\n        last = z;\n    }\n    return 0;",
      "            return 1;\n        last = z;\n    }\n    return 1;"),
    # -- the constructor and destructor ---------------------------------------
    M("ct-view", "camera_coordinator_init(&c->Base, viewID);",
      "camera_coordinator_init(&c->Base, 1);"),
    M("ct-vt", "    c->Base._vtable = DEMOCAMERACOORDINATOR_VTABLE;\n    c->pCar = car;",
      "    c->pCar = car;"),
    M("ct-car", "    c->pCar = car;", "    c->pCar = car + 1;"),
    M("ct-vortex", "c->CurrVortexCount = TheCameraLoader.VortexCount;",
      "c->CurrVortexCount = 0;"),
    M("ct-active", "c->CurrentlyActiveCameraData = -1;\n    c->DefaultCameraLookback = 0;",
      "c->CurrentlyActiveCameraData = 0;\n    c->DefaultCameraLookback = 0;"),
    M("ct-look", "    c->DefaultCameraLookback = 0;\n    c->DefaultCameraPOV = 0;\n    return c;",
      "    c->DefaultCameraLookback = 1;\n    c->DefaultCameraPOV = 0;\n    return c;"),
    M("ct-pov", "    c->DefaultCameraPOV = 0;\n    return c;",
      "    c->DefaultCameraPOV = 1;\n    return c;"),
    M("ct-start", "    c->DefaultCameraPOV = 0;\n    return c;",
      "    c->DefaultCameraPOV = 0;\n    c->CurrentCameraStartTime = 0;\n    return c;"),
    M("dt-vt", "    c->Base._vtable = DEMOCAMERACOORDINATOR_VTABLE;\n    camera_coordinator_destroy(&c->Base, flags);",
      "    camera_coordinator_destroy(&c->Base, flags);"),
    M("dt-flags", "camera_coordinator_destroy(&c->Base, flags);",
      "camera_coordinator_destroy(&c->Base, 0);"),
    # -- WillLookGood ------------------------------------------------------
    M("wl-pt", "(const bVector2 *)(const void *)&car->State.Position;",
      "(const bVector2 *)(const void *)&car->State.GeometryPosition;"),
    M("wl-f0", "tri[0] = cd->AreaVerts[face[0]];",
      "tri[0] = cd->AreaVerts[face[1]];"),
    M("wl-f1", "tri[1] = cd->AreaVerts[face[1]];",
      "tri[1] = cd->AreaVerts[face[0]];"),
    M("wl-f2", "tri[2] = cd->AreaVerts[face[2]];",
      "tri[2] = cd->AreaVerts[face[0]];"),
    M("wl-stride", "i++, face += 4)", "i++, face += 3)"),
    M("wl-n", "for (i = 0; i < cd->NumAreaFaces; i++, face += 4) {",
      "for (i = 0; i < cd->NumAreaFaces - 1; i++, face += 4) {"),
    M("wl-n3", "if (eIsPointInPoly(pt, tri, 3))", "if (eIsPointInPoly(pt, tri, 2))"),
    M("wl-ret", "            return 1;\n    }\n    return 0;\n}\n\nint32_t demo_camera_coordinator_will_look_good_data(",
      "            return 1;\n    }\n    return 1;\n}\n\nint32_t demo_camera_coordinator_will_look_good_data("),
    M("wld-cd", "    camera_data_items_parse(&cd, data);\n    return",
      "    camera_data_items_parse(&cd, TheCameraLoader.HighlightCameraData[0]);\n    return"),
    # -- FindGoodLookingHighlightCamera ------------------------------------
    M("fd-n", "for (i = 0; i < TheCameraLoader.NumHighlightCameras; i++) {",
      "for (i = 0; i < TheCameraLoader.NumHighlightCameras - 1; i++) {"),
    M("fd-dir", "reversed = RaceParametersTrackDirection == 1;",
      "reversed = RaceParametersTrackDirection != 0;"),
    M("fd-ww1", "        if (!car_is_facing_wrong_way(car))\n            backwards = reversed;",
      "        if (!car_is_facing_wrong_way(car))\n            backwards = 0;"),
    M("fd-ww2", "        if (car_is_facing_wrong_way(car) && !reversed)\n            backwards = 1;",
      "        if (car_is_facing_wrong_way(car))\n            backwards = 1;"),
    M("fd-ww2b", "        if (car_is_facing_wrong_way(car) && !reversed)\n            backwards = 1;",
      "        if (!reversed && car_is_facing_wrong_way(car))\n            backwards = 1;"),
    M("fd-back", "if ((backwards != 0) == (cd.Backwards != 0)",
      "if ((backwards != 0) == (cd.Backwards == 1)"),
    M("fd-noback", "if ((backwards != 0) == (cd.Backwards != 0)\n            && ",
      "if ("),
    M("fd-ret", "            return i;\n    }\n    return -1;",
      "            return i;\n    }\n    return 0;"),
    # -- the highlight's mover ---------------------------------------------
    M("bh-vortex", "    c->CurrVortexCount++;\n", ""),
    M("bh-shake", "        camera_loader_find_random_camera_shake(&TheCameraLoader,\n                                               cd.ShakeBankNumber);\n", ""),
    M("bh-bank", "                                               cd.ShakeBankNumber);",
      "                                               1);"),
    M("bh-cvs", "        shake.NumCVs = 2;\n", ""),
    M("bh-clear", "        memset(&shake, 0, sizeof shake);\n", "        memset(&shake, 0, 40);\n"),
    M("bh-tcsize", 'mem = bMalloc(1136, "TrackCarCameraMover", 0, 16);',
      'mem = bMalloc(1135, "TrackCarCameraMover", 0, 16);'),
    M("bh-tcname", 'mem = bMalloc(1136, "TrackCarCameraMover", 0, 16);',
      'mem = bMalloc(1136, "TrackCarCamera", 0, 16);'),
    M("bh-tcpool", 'mem = bMalloc(1136, "TrackCarCameraMover", 0, 16);',
      'mem = bMalloc(1136, "TrackCarCameraMover", 0, 0);'),
    M("bh-focus", "return gTrackCarCameraMoverFn(mem, viewID, car, &cd, &shake, 1);",
      "return gTrackCarCameraMoverFn(mem, viewID, car, &cd, &shake, 0);"),
    M("bh-tcview", "return gTrackCarCameraMoverFn(mem, viewID, car, &cd, &shake, 1);",
      "return gTrackCarCameraMoverFn(mem, 1, car, &cd, &shake, 1);"),
    M("bh-bmsize", 'mem = bMalloc(1116, "BumperCameraMover", 0, 16);',
      'mem = bMalloc(1136, "BumperCameraMover", 0, 16);'),
    M("bh-bmflags", 'mem = bMalloc(1116, "BumperCameraMover", 0, 16);',
      'mem = bMalloc(1116, "BumperCameraMover", 1, 16);'),
    M("bh-bmview", "return gBumperCameraMoverFn(mem, viewID, car, &cd);",
      "return gBumperCameraMoverFn(mem, 1, car, &cd);"),
    M("bh-tfsize", 'mem = bMalloc(412, "TrackFlyCameraMover", 0, 16);',
      'mem = bMalloc(1116, "TrackFlyCameraMover", 0, 16);'),
    M("bh-tfname", 'mem = bMalloc(412, "TrackFlyCameraMover", 0, 16);',
      'mem = bMalloc(412, "BumperCameraMover", 0, 16);'),
    M("bh-tfview", "return gTrackFlyCameraMoverFn(mem, viewID, &cd, car);",
      "return gTrackFlyCameraMoverFn(mem, 1, &cd, car);"),
    M("bh-swap12", "    case 1:\n        if (gBumperCameraMoverFn == NULL)",
      "    case 2:\n        if (gBumperCameraMoverFn == NULL)"),
    M("bh-type0", "    case 0: {\n        CameraShake shake;",
      "    case 3: {\n        CameraShake shake;"),
    # -- the drive camera ---------------------------------------------------
    M("dr-full", "? ti->Camera.NumSplitScreenPOVs : ti->Camera.NumFullScreenPOVs;",
      "? ti->Camera.NumSplitScreenPOVs : ti->Camera.NumSplitScreenPOVs;"),
    M("dr-split", "? ti->Camera.NumSplitScreenPOVs : ti->Camera.NumFullScreenPOVs;",
      "? ti->Camera.NumFullScreenPOVs : ti->Camera.NumFullScreenPOVs;"),
    M("dr-gt", "    if (n > 0)\n        pov = bRandomI(n, &bDefaultSeed);",
      "    if (n > 1)\n        pov = bRandomI(n, &bDefaultSeed);"),
    M("dr-rand", "pov = bRandomI(n, &bDefaultSeed);",
      "pov = bRandomI(n + 1, &bDefaultSeed);"),
    M("dr-same", "if (pov == c->DefaultCameraPOV && n > 0)",
      "if (pov == c->DefaultCameraPOV)"),
    M("dr-same2", "if (pov == c->DefaultCameraPOV && n > 0)",
      "if (pov != c->DefaultCameraPOV && n > 0)"),
    M("dr-wrap", "pov = (pov + 1) % n;", "pov = pov + 1;"),
    M("dr-keep", "    c->DefaultCameraPOV = pov;\n", ""),
    M("dr-look", "c->DefaultCameraLookback = c->DefaultCameraLookback == 0;",
      "c->DefaultCameraLookback = 1;"),
    M("dr-size", 'void *mem = bMalloc(1008, "DriveCameraMover(DCC)", 0, 16);',
      'void *mem = bMalloc(1008, "DriveCameraMover", 0, 16);'),
    M("dr-size2", 'void *mem = bMalloc(1008, "DriveCameraMover(DCC)", 0, 16);',
      'void *mem = bMalloc(1004, "DriveCameraMover(DCC)", 0, 16);'),
    M("dr-view", "            mem, c->Base.ViewID, car, c->DefaultCameraPOV,",
      "            mem, 1, car, c->DefaultCameraPOV,"),
    M("dr-pov", "            mem, c->Base.ViewID, car, c->DefaultCameraPOV,",
      "            mem, c->Base.ViewID, car, 0,"),
    M("dr-lag", "DEMO_CAMERA_LOOKBACK_SPEED, 1, c->DefaultCameraLookback, 0);",
      "DEMO_CAMERA_LOOKBACK_SPEED, 0, c->DefaultCameraLookback, 0);"),
    M("dr-back", "DEMO_CAMERA_LOOKBACK_SPEED, 1, c->DefaultCameraLookback, 0);",
      "DEMO_CAMERA_LOOKBACK_SPEED, 1, !c->DefaultCameraLookback, 0);"),
    M("dr-focus", "DEMO_CAMERA_LOOKBACK_SPEED, 1, c->DefaultCameraLookback, 0);",
      "DEMO_CAMERA_LOOKBACK_SPEED, 1, c->DefaultCameraLookback, 1);"),
    M("dr-keepm", "        c->Base.pCameraMover = gDriveCameraMoverFn(",
      "        (void)gDriveCameraMoverFn("),
    # -- Update ---------------------------------------------------------------
    M("up-clear", "    c->Base.NeedToReloadCameraData = 0;\n    if (m == NULL",
      "    if (m == NULL"),
    M("up-null", "if (m == NULL || reload != 0) {", "if (reload != 0) {"),
    M("up-reload", "if (m == NULL || reload != 0) {", "if (m == NULL) {"),
    M("up-reload2", "    int32_t reload = c->Base.NeedToReloadCameraData;",
      "    int32_t reload = 0 * c->Base.NeedToReloadCameraData;"),
    M("up-look1", "            c, car);\n        look = 1;\n    } else if",
      "            c, car);\n    } else if"),
    M("up-t1", "    } else if (WorldTimeFrames - c->CurrentCameraStartTime\n               >= DEMO_CAMERA_MIN_FRAMES) {",
      "    } else if (WorldTimeFrames - c->CurrentCameraStartTime\n               > DEMO_CAMERA_MIN_FRAMES) {"),
    M("up-t1b", "    } else if (WorldTimeFrames - c->CurrentCameraStartTime\n               >= DEMO_CAMERA_MIN_FRAMES) {",
      "    } else if (WorldTimeFrames - c->CurrentCameraStartTime\n               >= 50) {"),
    M("up-t1c", "    } else if (WorldTimeFrames - c->CurrentCameraStartTime\n               >= DEMO_CAMERA_MIN_FRAMES) {",
      "    } else if ((uint32_t)WorldTimeFrames - (uint32_t)c->CurrentCameraStartTime\n               >= DEMO_CAMERA_MIN_FRAMES) {"),
    M("up-act", "        if (active == -1\n            || !demo",
      "        if (active == 0\n            || !demo"),
    M("up-act2", "        if (active == -1\n            || !demo",
      "        if (!demo"),
    M("up-keep", "            || !demo_camera_coordinator_will_look_good_data(",
      "            || demo_camera_coordinator_will_look_good_data("),
    M("up-keepidx", "                   c, TheCameraLoader.HighlightCameraData[active], car)) {",
      "                   c, TheCameraLoader.HighlightCameraData[0], car)) {"),
    M("up-look2", "                c, car);\n            look = 1;\n            if",
      "                c, car);\n            if"),
    M("up-none", "            if (c->CurrentlyActiveCameraData == -1 && idx == -1)\n                look = 0;\n",
      ""),
    M("up-none2", "            if (c->CurrentlyActiveCameraData == -1 && idx == -1)",
      "            if (idx == -1)"),
    M("up-none3", "            if (c->CurrentlyActiveCameraData == -1 && idx == -1)",
      "            if (c->CurrentlyActiveCameraData == -1)"),
    M("up-bact", "    if (c->CurrentlyActiveCameraData != -1 && m != NULL\n",
      "    if (m != NULL\n"),
    M("up-bt", "        && WorldTimeFrames - c->CurrentCameraStartTime\n           >= DEMO_CAMERA_MIN_FRAMES) {\n        bad",
      "        && WorldTimeFrames - c->CurrentCameraStartTime\n           >= 57) {\n        bad"),
    M("up-bt2", "        && WorldTimeFrames - c->CurrentCameraStartTime\n           >= DEMO_CAMERA_MIN_FRAMES) {\n        bad",
      "        ) {\n        bad"),
    M("up-bnear", "        bad = camera_near_a_car(m->pCamera, DEMO_CAMERA_NEAR_SHOWN);\n",
      "        bad = 0;\n"),
    M("up-bplane", "        if (camera_near_plane_cuts_car(m->pCamera, c->pCar))\n            bad = 1;\n    }",
      "        if (!bad && camera_near_plane_cuts_car(m->pCamera, c->pCar))\n            bad = 1;\n    }"),
    M("up-bplane2", "        if (camera_near_plane_cuts_car(m->pCamera, c->pCar))\n            bad = 1;\n    }",
      "    }"),
    M("up-ret", "    if (!look && !bad)\n        return;", "    if (!look)\n        return;"),
    M("up-ret2", "    if (!look && !bad)\n        return;", "    if (!bad)\n        return;"),
    M("up-del", "    if (c->Base.pCameraMover != NULL) {\n        delete_mover(c->Base.pCameraMover);\n        c->Base.pCameraMover = NULL;\n    }\n",
      "    c->Base.pCameraMover = NULL;\n"),
    M("up-delnull", "        delete_mover(c->Base.pCameraMover);\n        c->Base.pCameraMover = NULL;\n",
      "        delete_mover(c->Base.pCameraMover);\n"),
    M("up-idxbad", "    if (idx != -1 && !bad) {", "    if (idx != -1) {"),
    M("up-idx", "    if (idx != -1 && !bad) {", "    if (!bad) {"),
    M("up-disable", "            n->vtbl->Disable(n);\n", ""),
    M("up-update", "            n->vtbl->Update(n);\n", ""),
    M("up-order", "            n->vtbl->Disable(n);\n            n->vtbl->Update(n);\n",
      "            n->vtbl->Update(n);\n            n->vtbl->Disable(n);\n"),
    M("up-gnear", "            good = !camera_near_a_car(n->pCamera, DEMO_CAMERA_NEAR_BUILT);",
      "            good = 1;"),
    M("up-gnear2", "            good = !camera_near_a_car(n->pCamera, DEMO_CAMERA_NEAR_BUILT);",
      "            good = !camera_near_a_car(n->pCamera, DEMO_CAMERA_NEAR_SHOWN);"),
    M("up-gplane", "            if (camera_near_plane_cuts_car(n->pCamera, c->pCar))\n                good = 0;\n",
      ""),
    M("up-gplane2", "            if (camera_near_plane_cuts_car(n->pCamera, c->pCar))\n                good = 0;\n",
      "            if (good && camera_near_plane_cuts_car(n->pCamera, c->pCar))\n                good = 0;\n"),
    M("up-keepn", "                c->Base.pCameraMover = n;\n", ""),
    M("up-enable", "                n->vtbl->Enable(n);\n", ""),
    M("up-active", "                c->CurrentlyActiveCameraData = idx;\n", ""),
    M("up-start", "                c->CurrentCameraStartTime = WorldTimeFrames;\n                return;",
      "                return;"),
    M("up-ret3", "                c->CurrentCameraStartTime = WorldTimeFrames;\n                return;",
      "                c->CurrentCameraStartTime = WorldTimeFrames;"),
    M("up-deln", "            delete_mover(n);\n", ""),
    M("up-dactive", "    build_drive_camera(c, car);\n    c->CurrentlyActiveCameraData = -1;\n",
      "    build_drive_camera(c, car);\n"),
    M("up-dstart", "    c->CurrentlyActiveCameraData = -1;\n    c->CurrentCameraStartTime = WorldTimeFrames;\n}",
      "    c->CurrentlyActiveCameraData = -1;\n}"),
    # -- BeginDemoCameras ----------------------------------------------------
    M("bg-has", "    if (p->pDemoCameraCoordinator != NULL)\n        return;\n", ""),
    M("bg-change", "    player_change_camera_mover(p, CM_NONE, 0);\n", ""),
    M("bg-change2", "player_change_camera_mover(p, CM_NONE, 0);",
      "player_change_camera_mover(p, CM_NONE, 1);"),
    M("bg-mycar", "    if (car == NULL)\n        car = p->MyCar;\n", ""),
    M("bg-mycar2", "    if (car == NULL)\n        car = p->MyCar;\n", "    car = p->MyCar;\n"),
    M("bg-size", 'mem = bMalloc(52, "DemoCameraCoordinator", 0, 16);',
      'mem = bMalloc(48, "DemoCameraCoordinator", 0, 16);'),
    M("bg-view", "                                     p->ViewID, car);",
      "                                     1, car);"),
    M("bg-keep", "    p->pDemoCameraCoordinator = (struct DemoCameraCoordinator *)\n        demo",
      "    (void)(struct DemoCameraCoordinator *)\n        demo"),
    # -- the table --------------------------------------------------------
    M("vt-dtor", "E(demo_camera_coordinator_destroy),", "E(camera_coordinator_destroy),"),
    M("vt-update", "E(demo_camera_coordinator_update),", "{ 0, 0, NULL },"),
]

EQUIVALENT = {
    # BaseCameraCoordinator's destructor stores its own table first, so
    # the demo's store before it is overwritten before anything reads it.
    "dt-vt": "the base destructor stores its table first",
    # Every path after the delete stores a new mover: a kept highlight or
    # the drive camera, whose seam main.c always binds.
    "up-delnull": "every path after the delete stores a new mover",
    # The demo destructor only stores its table, then jumps to the base's,
    # which stores its own before anything reads it (0x0019a4a0).
    "vt-dtor": "the demo destructor's only store is overwritten by the base's",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, ops, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "democam_test",
        lambda exe, out: mutpar.run_exe([exe, ops], out, limit),
        base, diff, EQUIVALENT, jobs)
    opsdir.cleanup()
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
        ops = Path(tmp) / "ops.bin"
        ops.write_bytes(sc.encode())
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, ops, out)
        harness = out.read_text().splitlines()

    if args.dump:
        Path(args.dump + ".model.txt").write_text(NL.join(lines) + NL)
        Path(args.dump + ".harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d ops, %d lines, %d differ"
          % (len(sc.ops), len(harness), bad))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
