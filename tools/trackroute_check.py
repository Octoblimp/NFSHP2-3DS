"""Cross-check 3DS Files/source/trackroute.c against a model of TrackRoute.obj.

TrackRoute.obj (0x001b6f60..0x001b9428) is the track's centreline: a list of
routes, each a run of 112-byte points carrying position, width, slope, the
twenty-one driving lines the AI follows, and a flag word that packs six
fields into thirty-two bits. The signposts hang off it, and the whole thing
arrives as a memory image -- the loader casts the chunk's bytes to TrackRoute
and never copies them -- so a field at the wrong offset is not a compile
error, it is a route that loads and then reads nonsense.

That is why the model here is a byte image too. Every record is a bytearray
with accessors at the offsets the disassembly's loads and stores use, rather
than a Python object with named attributes: an offset that disagrees with the
port moves a line in the transcript instead of hiding behind a field name.

The model is written from the disassembly. Its float and bounding-box layer
is imported from bvector_check, itself a model of bVector.obj written from
the ELF, so the chain of custody for every number here runs back to an
address rather than to another port.

Everything is float32. The EE has no double.

    python tools/trackroute_check.py
    python tools/trackroute_check.py --mutate     # break the C and re-diff
    python tools/trackroute_check.py --dump out/trackroute
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
from bvector_check import (FLT_MAX, bNormalize2, bScaleAdd2, box_expand,
                           box_init, box_inside, f32, fadd, fdiv, fmul, fneg,
                           fsqrt, fsub)

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/trackroute_test.c",
    "3DS Files/source/trackroute.c",
    "3DS Files/source/trackpath.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
    "3DS Files/source/bchunk.c",
]


def g9(x):
    return "%.9g" % x


# ------------------------------------------------------------- the constants
#
# Read out of the ELF at the addresses the listings load from, not guessed.

INV_POINT_SPACING = f32(0.0416666679084301)   # .lit4 0x003219f8
NO_LINE_TIME = f32(999.0)                     # .lit4 0x003219fc
POINT_SPACING = f32(24.0)                     # 0x41c00000
Q16 = f32(0.0000152587890625)                 # 2**-16, both line scales

TRP_SIGN_MASK = 0x000000ff
TRP_ROADBLOCK_SHIFT = 8
TRP_ROADBLOCK_MASK = 0x00003f00
TRP_NO_HELISHEET = 0x00004000
TRP_POSTED = 0x00008000
TRP_TERRAIN_SHIFT = 16
TRP_TERRAIN_MASK = 0x003f0000
TRP_RADARTRAP_SHIFT = 22
TRP_RADARTRAP_MASK = 0x0fc00000
TRP_POSTED_BACKWARDS = 0x10000000
NUM_DRIVING_LINES = 21

DLI_IS_VALID = 0x01
DLI_IS_FAKE = 0x02

TROUTE_MEMORY_IMAGE_LOADED = 0x01
TROUTE_REVERSED = 0x02
TRACK_ROUTE_RACING = 0
TRACK_ROUTE_TRAFFIC = 1
MAX_POINTS = 1024
MAX_ROUTES = 100

TRFIND_AHEAD_ONLY = 0x01
TRFIND_POSTED_ONLY = 0x02
TRFIND_NO_HELISHEET = 0x04
TRFIND_SKIP_RACING = 0x08
TRFIND_SKIP_TRAFFIC = 0x10
TRFIND_BY_TRACK_DISTANCE = 0x20

SIGNPOST_SIGN_MASK = 0x07
SIGNPOST_BACKWARDS = 0x08
SIGNPOST_NO_STAKEOUT = 0x10
SIGNPOST_HAIRPIN = 0x20
SIGNPOST_CLOAKED = 0x40

CHUNK_TRACK_ROUTES = 0x00034121
CHUNK_TRACK_SIGNPOSTS = 0x00034122

SZ_POINT = 112
SZ_INFO = 48
SZ_SIGN = 8
SZ_ROUTE = 115752
OFF_INFOS = 40
OFF_BBOX = 1048
OFF_POINTS = 1064


# ------------------------------------------------------------ byte accessors
#
# One property per field, at the offset the listing's load or store uses.
# Writes round to float32 and wrap integers the way the store does; reads come
# straight back out of the bytes.

def _fprop(off):
    def get(self):
        return struct.unpack_from("<f", self.buf, self.off + off)[0]

    def put(self, v):
        struct.pack_into("<f", self.buf, self.off + off, f32(v))
    return property(get, put)


def _iprop(fmt, off, lo, span):
    def get(self):
        return struct.unpack_from(fmt, self.buf, self.off + off)[0]

    def put(self, v):
        struct.pack_into(fmt, self.buf, self.off + off, (v - lo) % span + lo)
    return property(get, put)


def _u32(off):
    return _iprop("<I", off, 0, 1 << 32)


def _i32(off):
    return _iprop("<i", off, -(1 << 31), 1 << 32)


def _i16(off):
    return _iprop("<h", off, -(1 << 15), 1 << 16)


def _u16(off):
    return _iprop("<H", off, 0, 1 << 16)


def _u8(off):
    return _iprop("<B", off, 0, 1 << 8)


class Rec(object):
    """A record overlaid on somebody else's bytes, which is how they arrive."""
    __slots__ = ("buf", "off")

    def __init__(self, buf, off):
        self.buf = buf
        self.off = off

    def same(self, other):
        return (other is not None and self.buf is other.buf and
                self.off == other.off)


class Point(Rec):
    """TrackRoutePoint, 112 bytes."""
    __slots__ = ()
    PosX = _fprop(0)
    PosY = _fprop(4)
    Elevation = _fprop(8)
    DirX = _fprop(12)
    DirY = _fprop(16)
    Length = _fprop(20)
    LeftWidth = _fprop(24)
    RightWidth = _fprop(28)
    BankSlope = _fprop(32)
    ForwardSlope = _fprop(36)
    DistanceAroundTrack = _fprop(40)
    Bits = _u32(44)
    RouteNumber = _u8(111)

    def dlo(self, i):
        return struct.unpack_from("<h", self.buf, self.off + 48 + i * 2)[0]

    def set_dlo(self, i, v):
        struct.pack_into("<h", self.buf, self.off + 48 + i * 2,
                         (v + 32768) % 65536 - 32768)

    def dls(self, i):
        return self.buf[self.off + 90 + i]

    def set_dls(self, i, v):
        self.buf[self.off + 90 + i] = v & 0xff

    # The six fields packed into the flag word.
    def sign_number(self):
        return self.Bits & TRP_SIGN_MASK

    def road_block_number(self):
        return (self.Bits & TRP_ROADBLOCK_MASK) >> TRP_ROADBLOCK_SHIFT

    def radar_trap_number(self):
        return (self.Bits & TRP_RADARTRAP_MASK) >> TRP_RADARTRAP_SHIFT

    def terrain_type(self):
        return (self.Bits & TRP_TERRAIN_MASK) >> TRP_TERRAIN_SHIFT

    def is_posted(self):
        return 1 if self.Bits & TRP_POSTED else 0

    def pos(self):
        return (self.PosX, self.PosY)


class LineInfo(Rec):
    """DrivingLineInfo, 48 bytes."""
    __slots__ = ()
    Flags = _u32(0)
    LineTime = _fprop(4)

    def name(self):
        raw = bytes(self.buf[self.off + 8:self.off + 48]).split(b"\0")[0]
        return raw.decode("latin-1")

    def set_name(self, s):
        b = bytearray(40)
        b[:len(s)] = s.encode("latin-1")
        self.buf[self.off + 8:self.off + 48] = b


class Sign(Rec):
    """Signpost, 8 bytes."""
    __slots__ = ()
    NewRoute = _u8(0)
    Flags = _u8(1)
    NewPoint = _u16(2)
    Distance = _fprop(4)


class Route(Rec):
    """TrackRoute, 115752 bytes. The two node links are never dereferenced."""
    __slots__ = ()
    Version = _i16(8)
    RouteNumber = _i16(10)
    Type = _i32(12)
    NumPoints = _i32(16)
    MaxPoints = _i32(20)
    Flags = _u32(24)
    CurrentlyTuningDrivingLine = _i32(28)
    fStartDistance = _fprop(32)
    fEndDistance = _fprop(36)
    BBoxMinX = _fprop(OFF_BBOX + 0)
    BBoxMinY = _fprop(OFF_BBOX + 4)
    BBoxMaxX = _fprop(OFF_BBOX + 8)
    BBoxMaxY = _fprop(OFF_BBOX + 12)

    def point(self, i):
        return Point(self.buf, self.off + OFF_POINTS + i * SZ_POINT)

    def line(self, i):
        return LineInfo(self.buf, self.off + OFF_INFOS + i * SZ_INFO)

    def bbox(self):
        return ([self.BBoxMinX, self.BBoxMinY],
                [self.BBoxMaxX, self.BBoxMaxY])

    def set_bbox(self, mn, mx):
        self.BBoxMinX = mn[0]
        self.BBoxMinY = mn[1]
        self.BBoxMaxX = mx[0]
        self.BBoxMaxY = mx[1]


# ----------------------------------------------------------------- the world
#
# The three globals TrackRoute.obj reaches for, plus the manager.


class Coord(object):
    """TrackPathCoordinate, 0x001f5c90. Only the distance is read here."""

    def __init__(self):
        self.PosX = 0.0
        self.PosY = 0.0
        self.DistanceAroundTrack = 0.0
        self.RatioAroundTrack = 0.0


class State(object):
    pass


S = State()


def reset_state():
    S.TrackLength = 0.0
    S.DistanceFn = None
    S.SignBuf = None
    S.SignBase = 0
    S.NumSignposts = 0
    S.pTrackRoutes = [None] * MAX_ROUTES
    S.Racing = []
    S.Traffic = []
    S.rng = 0


def sign(i):
    return Sign(S.SignBuf, S.SignBase + i * SZ_SIGN)


def coord_update_position(c, pos):
    """0x001f5dd0. QuickSpline is not ported; the seam stands in for it."""
    c.PosX, c.PosY = pos
    if S.DistanceFn is not None:
        c.DistanceAroundTrack = S.DistanceFn(pos)
        c.RatioAroundTrack = (fdiv(c.DistanceAroundTrack, S.TrackLength)
                              if S.TrackLength != 0.0 else f32(0.0))


def compare_distances(a, b):
    """0x001f5b70. Signed, wrapped into half a lap either way."""
    length = S.TrackLength
    d = fsub(a, b)
    if d < fmul(fneg(length), 0.5):
        return fadd(d, length)
    if fmul(length, 0.5) < d:
        return fsub(d, length)
    return d


# ------------------------------------------------------------- route points

def trpoint_init(p):
    """0x001b7290. Byte store then word read-modify-write, in that order."""
    b = (p.Bits & 0xffffff00) | 0xff | 0x0fc03f00
    b &= 0xffffffff ^ (TRP_NO_HELISHEET | TRP_POSTED | TRP_POSTED_BACKWARDS)
    p.Bits = b
    p.BankSlope = 0.0
    p.ForwardSlope = 0.0


def trpoint_get_position2(p, d, l):
    """0x001b72e0."""
    perp = (p.DirY, fneg(p.DirX))
    o = bScaleAdd2(p.pos(), perp, l)
    return bScaleAdd2(o, (p.DirX, p.DirY), d)


def trpoint_get_position3(p, d, l):
    """0x001b7358. Two VU0 fmas over four lanes; the fourth lane's inputs
    are stack slots the original never writes, so pad is left alone."""
    lx, ly, lz = p.DirY, fneg(p.DirX), p.BankSlope
    ax, ay, az = p.DirX, p.DirY, p.ForwardSlope
    x = fadd(fmul(lx, l), p.PosX)
    y = fadd(fmul(ly, l), p.PosY)
    z = fadd(fmul(lz, l), p.Elevation)
    return (fadd(fmul(ax, d), x), fadd(fmul(ay, d), y),
            fadd(fmul(az, d), z))


def trpoint_set_width(p, left, right):
    """0x001b73e0."""
    if 64.0 < left:
        left = f32(64.0)
    if left < 1.0:
        left = f32(1.0)
    if 64.0 < right:
        right = f32(64.0)
    if right < 1.0:
        right = f32(1.0)
    p.RightWidth = right
    p.LeftWidth = left


def trpoint_get_signpost(p):
    """0x001b7448."""
    return sign(p.Bits & TRP_SIGN_MASK)


def trpoint_swap_point_data(a, b):
    """0x001b7460. Forty-eight bytes: Position through Bits, and no more."""
    ta = bytes(a.buf[a.off:a.off + 48])
    tb = bytes(b.buf[b.off:b.off + 48])
    a.buf[a.off:a.off + 48] = tb
    b.buf[b.off:b.off + 48] = ta


def trpoint_reverse_point(p):
    """0x001b74c0."""
    x, y, z = trpoint_get_position3(p, p.Length, f32(0.0))
    p.PosX = x
    p.PosY = y
    p.Elevation = z
    p.DirX = fneg(p.DirX)
    p.DirY = fneg(p.DirY)
    left = p.LeftWidth
    right = p.RightWidth
    p.RightWidth = left
    p.ForwardSlope = fneg(p.ForwardSlope)
    p.BankSlope = fneg(p.BankSlope)
    p.LeftWidth = right
    p.DistanceAroundTrack = fsub(S.TrackLength, p.DistanceAroundTrack)
    for i in range(10):
        o, s = p.dlo(i), p.dls(i)
        p.set_dlo(i, p.dlo(i + 10))
        p.set_dls(i, p.dls(i + 10))
        p.set_dlo(i + 10, o)
        p.set_dls(i + 10, s)


def trpoint_reverse_traffic_route_point(p):
    """0x001b75d8."""
    p.DistanceAroundTrack = fsub(S.TrackLength, p.DistanceAroundTrack)


def trpoint_get_distance_away(p, pos, d):
    """0x001b75f0. The larger of the plane distance and the along-track one,
    the latter with one point spacing of slack taken off."""
    dx = fsub(p.PosX, pos[0])
    dy = fsub(p.PosY, pos[1])
    plane = fsqrt(fadd(fmul(dx, dx), fmul(dy, dy)))
    along = compare_distances(p.DistanceAroundTrack, d)
    along = fsub(fneg(along) if along < 0.0 else along, POINT_SPACING)
    return along if plane < along else plane


def trpoint_get_driving_line_offset(p, line):
    """Inlined at every call site. Q8, read as a shift and a 2**-16 scale."""
    return fmul(f32(p.dlo(line) << 8), Q16)


def trpoint_get_driving_line_speed(p, line):
    """Inlined likewise. Whole units, by the same route."""
    return fmul(f32(p.dls(line) << 16), Q16)


# -------------------------------------------------------------------- routes

def troute_get_point_number(r, p):
    """0x001b7818, a pointer difference the compiler turned into a divide."""
    return (p.off - (r.off + OFF_POINTS)) // SZ_POINT


def troute_init(r, number):
    """0x001b7660."""
    for i in range(MAX_POINTS):
        trpoint_init(r.point(i))
    r.RouteNumber = number
    r.Version = 1
    if number < 50:
        r.Type = TRACK_ROUTE_RACING
    elif number < 70:
        r.Type = TRACK_ROUTE_TRAFFIC
    else:
        r.Type = TRACK_ROUTE_RACING
    r.Flags = r.Flags & ~(TROUTE_MEMORY_IMAGE_LOADED | TROUTE_REVERSED)
    r.MaxPoints = MAX_POINTS
    r.NumPoints = 0
    r.CurrentlyTuningDrivingLine = 0
    for i in range(NUM_DRIVING_LINES):
        troute_erase_driving_line(r, i)
    mn, mx = box_init(2)
    r.set_bbox(mn, mx)


def troute_add_point(r, pos, elevation, left_width, right_width):
    """0x001b7760."""
    if r.NumPoints >= r.MaxPoints:
        return None
    route_number = r.RouteNumber & 0xff
    p = r.point(r.NumPoints)
    r.NumPoints = r.NumPoints + 1
    p.RouteNumber = route_number
    p.PosX = pos[0]
    p.PosY = pos[1]
    p.Elevation = elevation
    p.LeftWidth = left_width
    p.RightWidth = right_width
    mn, mx = r.bbox()
    box_expand(mn, mx, [p.PosX, p.PosY], 2)
    r.set_bbox(mn, mx)
    p.Length = f32(4.0)
    if r.NumPoints >= 2:
        prev = r.point(r.NumPoints - 2)
        troute_calculate_point_direction(r, prev)
        p.DirX = prev.DirX
        p.DirY = prev.DirY
    else:
        p.DirY = f32(0.0)
        p.DirX = f32(1.0)
        p.ForwardSlope = f32(0.0)
    return p


def troute_get_relative_point(r, p, forward):
    """0x001b7858."""
    i = troute_get_point_number(r, p)
    if forward:
        return r.point(i + 1) if i + 1 < r.NumPoints else None
    return None if i == 0 else r.point(i - 1)


def troute_calculate_point_direction(r, p):
    """0x001b78d8. The slope is written to both points: the store into the
    next one is the delay slot of the call to bNormalize, so it lands before
    the direction is unitised and the value is the same either way."""
    i = troute_get_point_number(r, p)
    if i >= r.NumPoints - 1:
        return 0
    nxt = r.point(i + 1)
    p.DirX = fsub(nxt.PosX, p.PosX)
    p.DirY = fsub(nxt.PosY, p.PosY)
    length = fsqrt(fadd(fmul(p.DirX, p.DirX), fmul(p.DirY, p.DirY)))
    p.Length = length
    slope = fdiv(fsub(nxt.Elevation, p.Elevation), length)
    p.ForwardSlope = slope
    nxt.ForwardSlope = slope
    nx, ny = bNormalize2((p.DirX, p.DirY))
    p.DirX = nx
    p.DirY = ny
    length = p.Length
    if POINT_SPACING < length:
        return 1
    if length < 4.0:
        return 1
    return 0


def troute_move_point(r, p, pos):
    """0x001b79e0. Elevation comes from pos->x, which is the shipped bug."""
    i = troute_get_point_number(r, p)
    if i < 0:
        return 1
    if i >= r.NumPoints:
        return 1
    p.PosX = pos[0]
    p.PosY = pos[1]
    p.Elevation = pos[0]
    n = troute_calculate_point_direction(r, p)
    if i > 0:
        n += troute_calculate_point_direction(r, r.point(i - 1))
    return n


def troute_find_closest_point(r, pos, radius, flags, distance_around):
    """0x001b7a90."""
    best = None
    by_track = flags & TRFIND_BY_TRACK_DISTANCE
    mn, mx = r.bbox()
    if not box_inside(mn, mx, list(pos), radius, 2):
        return None

    i = 0
    while i < r.NumPoints:
        p = r.point(i)
        if by_track:
            dist = trpoint_get_distance_away(p, pos, distance_around)
        else:
            dx = fsub(p.PosX, pos[0])
            dy = fsub(p.PosY, pos[1])
            dist = fsqrt(fadd(fmul(dx, dx), fmul(dy, dy)))
        dot = fneg(fadd(fmul(fsub(pos[0], p.PosX), p.DirX),
                        fmul(fsub(pos[1], p.PosY), p.DirY)))

        while True:
            if (flags & TRFIND_AHEAD_ONLY) and not 0.0 < dot:
                break
            if not dist < radius:
                break
            if (flags & TRFIND_POSTED_ONLY) and not p.Bits & TRP_POSTED:
                break
            if (flags & TRFIND_NO_HELISHEET) and p.Bits & TRP_NO_HELISHEET:
                break
            best = p
            radius = dist
            break

        # Consecutive points are no more than a spacing apart, so nothing
        # closer than dist can hide in the next dist/24 - 2 of them.
        skip = int(f32(dist * INV_POINT_SPACING)) - 2
        if skip > 0:
            i += skip
        i += 1
    return best


def troute_find_closest_point_ahead(r, pos, start):
    """0x001b7c78. The index runs one ahead of the pointer, so the last
    point never qualifies."""
    if pos is None or start is None:
        return None
    n = r.NumPoints
    i = troute_get_point_number(r, start)
    at = i
    while True:
        i += 1
        p = r.point(at)
        dot = fneg(fadd(fmul(fsub(pos[0], p.PosX), p.DirX),
                        fmul(fsub(pos[1], p.PosY), p.DirY)))
        if not dot < 0.0:
            break
        if i >= n:
            break
        at += 1
    return r.point(at) if i < n else None


def troute_erase_driving_line(r, line):
    """0x001b7d28."""
    for i in range(r.NumPoints):
        p = r.point(i)
        p.set_dlo(line, 0)
        p.set_dls(line, 0)
    info = r.line(line)
    info.Flags = info.Flags & ~(DLI_IS_VALID | DLI_IS_FAKE)
    info.LineTime = NO_LINE_TIME
    info.set_name("")


def troute_has_driving_line_data(r):
    """0x001b8200. The halfway point, lines zero and one, and nothing else."""
    mid = r.point(r.NumPoints // 2)
    for k in range(2):
        if 30.0 < trpoint_get_driving_line_speed(mid, k):
            return 1
    return 0


def troute_reverse_route(r):
    """0x001b8280."""
    n = r.NumPoints
    for i in range(n // 2):
        trpoint_swap_point_data(r.point(i), r.point(n - 1 - i))
    for i in range(r.NumPoints):
        trpoint_reverse_point(r.point(i))
    for i in range(10):
        a = r.line(i)
        b = r.line(i + 10)
        ta = bytes(a.buf[a.off:a.off + SZ_INFO])
        tb = bytes(b.buf[b.off:b.off + SZ_INFO])
        a.buf[a.off:a.off + SZ_INFO] = tb
        b.buf[b.off:b.off + SZ_INFO] = ta
    r.Flags = ((r.Flags & ~TROUTE_REVERSED) |
               ((~(r.Flags >> 1) & 1) << 1)) & 0xffffffff


def troute_reverse_traffic_route(r):
    """0x001b84e8."""
    for i in range(r.NumPoints):
        trpoint_reverse_traffic_route_point(r.point(i))


def troute_set_first_and_last(r):
    """0x001b8548. Point zero seeds the did-we-jump test but never lands in
    a bucket, so a one-point route comes out empty."""
    mn = [S.TrackLength, S.TrackLength]
    mx = [f32(0.0), f32(0.0)]
    half = fmul(S.TrackLength, 0.5)
    bucket = 0
    wrapped = 0

    coord = Coord()
    coord_update_position(coord, r.point(0).pos())
    prev = coord.DistanceAroundTrack

    for i in range(1, r.NumPoints):
        coord_update_position(coord, r.point(i).pos())
        d = coord.DistanceAroundTrack
        gap = fsub(d, prev)
        if gap < 0.0:
            gap = fneg(gap)
        if half < gap:
            wrapped = 1
            bucket ^= 1
        prev = d
        if mx[bucket] < d:
            mx[bucket] = d
        if d < mn[bucket]:
            mn[bucket] = d

    if wrapped:
        r.fStartDistance = mn[0] if mn[0] > mn[1] else mn[1]
        r.fEndDistance = mx[0] if mx[0] < mx[1] else mx[1]
    else:
        r.fStartDistance = mn[0]
        r.fEndDistance = mx[0]


def troute_distance_is_within_route(r, d):
    """0x001b86c8."""
    after = r.fStartDistance <= d
    before = d <= r.fEndDistance
    if r.fStartDistance < r.fEndDistance:
        return 1 if after and before else 0
    return 1 if after or before else 0


# --------------------------------------------------------------- the manager

def trmgr_init():
    """0x001b8738. Both bTLists point at themselves; empty says the same."""
    S.pTrackRoutes = [None] * MAX_ROUTES
    S.Racing = []
    S.Traffic = []


def trmgr_unlink(r):
    for lst in (S.Racing, S.Traffic):
        for i in range(len(lst)):
            if lst[i].same(r):
                del lst[i]
                return


def trmgr_add_route_to_right_list(r):
    """0x001b87e8. Two equality tests, not a default branch: a Type that is
    neither lands in the slot table and nowhere else."""
    S.pTrackRoutes[r.RouteNumber] = r
    if r.Type == TRACK_ROUTE_RACING:
        if len(S.Racing) < MAX_ROUTES:
            S.Racing.append(r)
    elif r.Type == TRACK_ROUTE_TRAFFIC:
        if len(S.Traffic) < MAX_ROUTES:
            S.Traffic.append(r)


def trmgr_loader(chunk, off):
    """0x001b8848. Each record is a TrackRoute with the unused tail of its
    point table cut off, so the stride shrinks by 112 for every missing
    point. Nothing is copied."""
    size = struct.unpack_from("<I", chunk, off + 4)[0]
    p = off + 8
    end = off + 8 + size
    while p < end:
        r = Route(chunk, p)
        trmgr_add_route_to_right_list(r)
        p += (SZ_ROUTE - (MAX_POINTS - r.NumPoints) * SZ_POINT) & 0xffffffff


def trmgr_unloader():
    """0x001b88e8. Memory images are unlinked and never freed."""
    for i in range(MAX_ROUTES):
        r = S.pTrackRoutes[i]
        if r is None:
            continue
        trmgr_unlink(r)
        S.pTrackRoutes[i] = None


def trmgr_find_closest_point(pos, radius, flags, distance_around):
    """0x001b8ce0. Two passes; the matching skip flag turns a pass into no
    list at all."""
    best = None
    for pass_ in range(2):
        if pass_ == 0:
            if flags & TRFIND_SKIP_RACING:
                continue
            lst = S.Racing
        else:
            if flags & TRFIND_SKIP_TRAFFIC:
                continue
            lst = S.Traffic
        for r in lst:
            p = troute_find_closest_point(r, pos, radius, flags,
                                          distance_around)
            if p is None:
                continue
            if flags & TRFIND_BY_TRACK_DISTANCE:
                radius = trpoint_get_distance_away(p, pos, distance_around)
            else:
                dx = fsub(p.PosX, pos[0])
                dy = fsub(p.PosY, pos[1])
                radius = fsqrt(fadd(fmul(dx, dx), fmul(dy, dy)))
            best = p
    return best


def trmgr_reverse_routes():
    """0x001b8a00. Slots 50..69 are traffic; everything else below 70 is not."""
    for i in range(70):
        r = S.pTrackRoutes[i]
        if r is None:
            continue
        if i >= 50:
            troute_reverse_traffic_route(r)
        else:
            troute_reverse_route(r)


# ------------------------------------------------------------------ signposts

def signpost_get_new_route(s):
    """0x001b6f60. The guard is a bltz on a zero-extended byte, so the NULL
    return is unreachable."""
    return S.pTrackRoutes[s.NewRoute]


def signpost_get_new_route_point(s):
    """0x001b6f88."""
    r = signpost_get_new_route(s)
    if r is None:
        return None
    return r.point(s.NewPoint)


def signpost_is_racing_route(s):
    """0x001b7080."""
    return 1 if s.NewRoute < 50 else 0


def signpost_reverse_signs():
    """0x001b6fc8."""
    for i in range(S.NumSignposts):
        s = sign(i)
        if not signpost_is_racing_route(s):
            continue
        r = signpost_get_new_route(s)
        s.NewPoint = r.NumPoints - s.NewPoint - 1
        s.Flags = ((s.Flags & ~SIGNPOST_BACKWARDS) |
                   ((~(s.Flags >> 3) & 1) << 3)) & 0xff


def signpost_set_distances():
    """0x001b7090. Two hops, not one: the sign's own target point is read
    only for *its* signpost, and the distance comes from that second sign's
    target point. On track 12 the signs are paired, so a pair shares one."""
    coord = Coord()
    for i in range(S.NumSignposts):
        s = sign(i)
        p = signpost_get_new_route_point(s)
        if p is None:
            continue
        if (p.Bits & TRP_SIGN_MASK) >= S.NumSignposts:
            continue
        other = trpoint_get_signpost(p)
        target = signpost_get_new_route_point(other)
        if target is None:
            continue
        coord_update_position(coord, target.pos())
        s.Distance = coord.DistanceAroundTrack


def signpost_get_index(d):
    """0x001b7120."""
    for i in range(S.NumSignposts):
        if not sign(i).Distance < d:
            return i
    return 0


def signposts_present():
    """0x001b8f20."""
    return 1 if S.SignBuf is not None else 0


def signpost_test_consistency():
    """0x001b7168. The loop runs and nothing is kept: the asserts it fed
    went out with NDEBUG."""
    coord = Coord()
    for i in range(S.NumSignposts):
        p = signpost_get_new_route_point(sign(i))
        if p is None:
            continue
        coord_update_position(coord, p.pos())


# -------------------------------------------------------------------- sorting

def heap_sort(arr, cmp):
    """0x001b8f30. Numerical Recipes heapsort, one for one, including the
    one-based indexing and the held-out slot."""
    n = len(arr)
    if n < 2:
        return
    l = n // 2 + 1
    ir = n
    while True:
        if l >= 2:
            l -= 1
            rra = arr[l - 1]
        else:
            rra = arr[ir - 1]
            arr[ir - 1] = arr[0]
            ir -= 1
            if ir == 1:
                arr[0] = rra
                break
        i = l
        j = l + l
        while j <= ir:
            if j < ir and cmp(arr[j - 1], arr[j]) < 0.0:
                j += 1
            if cmp(rra, arr[j - 1]) < 0.0:
                arr[i - 1] = arr[j - 1]
                i = j
                j += j
            else:
                j = ir + 1
        arr[i - 1] = rra


def compare_signposts(a, b):
    """0x001b9170. The elements are pointers paired with an index, so the
    compare dereferences once."""
    return fsub(sign(a[0]).Distance, sign(b[0]).Distance)


# ---------------------------------------------------------------- chunk hooks

def track_routes_loader(chunk, off=0):
    """0x001b8e60."""
    kind = struct.unpack_from("<I", chunk, off)[0]
    if kind == CHUNK_TRACK_ROUTES:
        trmgr_loader(chunk, off)
        return 1
    if kind == CHUNK_TRACK_SIGNPOSTS:
        S.SignBuf = chunk
        S.SignBase = off + 8
        S.NumSignposts = struct.unpack_from("<I", chunk, off + 4)[0] >> 3
        return 1
    return 0


def track_routes_unloader(chunk, off=0):
    """0x001b8ec8."""
    kind = struct.unpack_from("<I", chunk, off)[0]
    if kind == CHUNK_TRACK_ROUTES:
        trmgr_unloader()
        return 1
    if kind == CHUNK_TRACK_SIGNPOSTS:
        S.SignBuf = None
        S.SignBase = 0
        S.NumSignposts = 0
        return 1
    return 0


def init_track_routes(forward):
    """0x001b9188."""
    if not forward:
        trmgr_reverse_routes()
        signpost_reverse_signs()

    for n in range(MAX_ROUTES):
        r = S.pTrackRoutes[n]
        if r is not None:
            troute_set_first_and_last(r)

    signpost_set_distances()

    if S.NumSignposts == 0:
        return

    pairs = [[i, i] for i in range(S.NumSignposts)]
    heap_sort(pairs, compare_signposts)

    remap = [0] * 256
    for i in range(S.NumSignposts):
        remap[pairs[i][1] & 0xff] = i & 0xff

    for n in range(MAX_ROUTES):
        r = S.pTrackRoutes[n]
        if r is None:
            continue
        for j in range(r.NumPoints):
            p = r.point(j)
            s = p.Bits & TRP_SIGN_MASK
            if s == TRP_SIGN_MASK:
                continue
            p.Bits = (p.Bits & ~TRP_SIGN_MASK) | remap[s]

    sorted_signs = [bytes(sign(e[0]).buf[sign(e[0]).off:
                                         sign(e[0]).off + SZ_SIGN])
                    for e in pairs]
    for i, raw in enumerate(sorted_signs):
        base = S.SignBase + i * SZ_SIGN
        S.SignBuf[base:base + SZ_SIGN] = raw


def close_track_routes():
    """0x001b9428. Empty on the disc too."""


# -------------------------------------------------------------------- output

class Out(object):
    def __init__(self):
        self.lines = []

    def __call__(self, s):
        self.lines.append(s)


def ppoint(o, tag, p):
    o("  %s pos %s %s elev %s dir %s %s len %s"
      % (tag, g9(p.PosX), g9(p.PosY), g9(p.Elevation), g9(p.DirX),
         g9(p.DirY), g9(p.Length)))
    o("    w %s %s slope %s %s dist %s bits %08x"
      % (g9(p.LeftWidth), g9(p.RightWidth), g9(p.BankSlope),
         g9(p.ForwardSlope), g9(p.DistanceAroundTrack), p.Bits))
    o("    sign %d rb %d rt %d terr %d posted %d nohel %d pb %d rnum %d"
      % (p.sign_number(), p.road_block_number(), p.radar_trap_number(),
         p.terrain_type(), p.is_posted(),
         1 if p.Bits & TRP_NO_HELISHEET else 0,
         1 if p.Bits & TRP_POSTED_BACKWARDS else 0, p.RouteNumber))


def plines(o, p):
    o("    off" + "".join(" %d" % p.dlo(i) for i in range(NUM_DRIVING_LINES)))
    o("    spd" + "".join(" %d" % p.dls(i) for i in range(NUM_DRIVING_LINES)))


def proute(o, tag, r):
    o("route %s n %d ver %d type %d pts %d max %d flags %08x tune %d"
      % (tag, r.RouteNumber, r.Version, r.Type, r.NumPoints, r.MaxPoints,
         r.Flags, r.CurrentlyTuningDrivingLine))
    o("  span %s %s bbox %s %s %s %s"
      % (g9(r.fStartDistance), g9(r.fEndDistance), g9(r.BBoxMinX),
         g9(r.BBoxMinY), g9(r.BBoxMaxX), g9(r.BBoxMaxY)))
    for i in range(NUM_DRIVING_LINES):
        d = r.line(i)
        o("  line %2d flags %08x time %s name %s"
          % (i, d.Flags, g9(d.LineTime), d.name()[:20]))
    for i in range(r.NumPoints):
        ppoint(o, "p%d" % i, r.point(i))


def plist(o, tag, lst):
    o("  list %s:" % tag + "".join(" %d" % r.RouteNumber for r in lst))


def plists(o):
    plist(o, "racing", S.Racing)
    plist(o, "traffic", S.Traffic)


def psigns(o, tag):
    o("signposts %s n %d" % (tag, S.NumSignposts))
    for i in range(S.NumSignposts):
        s = sign(i)
        o("  %2d route %d point %d sign %d back %d nostake %d hairpin %d"
          " cloak %d dist %s"
          % (i, s.NewRoute, s.NewPoint, s.Flags & SIGNPOST_SIGN_MASK,
             1 if s.Flags & SIGNPOST_BACKWARDS else 0,
             1 if s.Flags & SIGNPOST_NO_STAKEOUT else 0,
             1 if s.Flags & SIGNPOST_HAIRPIN else 0,
             1 if s.Flags & SIGNPOST_CLOAKED else 0, g9(s.Distance)))


# ----------------------------------------------------------------- the harness

def rseed(s):
    S.rng = s


def frand(scale):
    S.rng = (S.rng * 1103515245 + 12345) & 0xffffffff
    u = fsub(fmul(f32(S.rng >> 8), f32(1.0 / 8388608.0)), 1.0)
    return fmul(u, scale)


def test_distance(p):
    """The stand-in for QuickSpline: a linear ramp wrapped into the lap,
    built only out of add, multiply and compare so it is bit-identical."""
    length = S.TrackLength
    if not length > 0.0:
        return f32(0.0)
    t = fadd(fmul(p[0], 0.5), fmul(p[1], 0.25))
    guard = 0
    while guard < 64 and t < 0.0:
        t = fadd(t, length)
        guard += 1
    guard = 0
    while guard < 64 and not t < length:
        t = fsub(t, length)
        guard += 1
    return t


def dirty(buf, off, n, seed):
    """The fill pattern, bit 6 of every fourth byte cleared so no float read
    out of it is a NaN -- a NaN prints three different ways across libcs."""
    for i in range(n):
        b = (seed + i * 37) & 0xff
        if (i & 3) == 3:
            b &= 0xbf
        buf[off + i] = b


def build_route(r, number, n, ox, oy, turn):
    troute_init(r, number)
    for i in range(n):
        t = f32(i)
        x = fadd(fadd(ox, fmul(t, 20.0)), fmul(fmul(t, t), turn))
        y = fsub(fadd(oy, fmul(t, 6.0)), fmul(fmul(fmul(t, t), turn), 0.5))
        lw = fadd(6.0, frand(f32(1.0)))
        rw = fadd(7.0, frand(f32(1.0)))
        troute_add_point(r, (x, y), fmul(t, 1.5), lw, rw)


def emit_route(chunk, off, r):
    n = SZ_ROUTE - (MAX_POINTS - r.NumPoints) * SZ_POINT
    chunk[off:off + n] = r.buf[r.off:r.off + n]
    tmp = Route(chunk, off)
    tmp.Flags = tmp.Flags | TROUTE_MEMORY_IMAGE_LOADED
    return n


# ------------------------------------------------------------------ scenarios

def s_point(o, g):
    buf = bytearray(SZ_POINT)
    p = Point(buf, 0)
    o("scenario point")

    dirty(buf, 0, SZ_POINT, 0x11)
    trpoint_init(p)
    ppoint(o, "ctor", p)
    plines(o, p)

    dirty(buf, 0, SZ_POINT, 0xa3)
    trpoint_init(p)
    ppoint(o, "ctor2", p)

    for i in range(SZ_POINT):
        buf[i] = 0
    trpoint_init(p)
    p.PosX = 10.0
    p.PosY = -4.0
    p.Elevation = 2.5
    p.DirX = f32(0.600000024)
    p.DirY = f32(0.800000012)
    p.Length = 21.0
    p.BankSlope = 0.125
    p.ForwardSlope = -0.0625
    p.DistanceAroundTrack = 900.0

    for i in range(-2, 3):
        d = fmul(f32(i), 13.0)
        l = fmul(f32(i), -3.5)
        pad = f32(12345.0)
        a = trpoint_get_position2(p, d, l)
        b = trpoint_get_position3(p, d, l)
        o("  at %s %s -> 2d %s %s 3d %s %s %s pad %s"
          % (g9(d), g9(l), g9(a[0]), g9(a[1]), g9(b[0]), g9(b[1]), g9(b[2]),
             g9(pad)))

    widths = [f32(x) for x in (-5.0, 0.5, 1.0, 7.25, 64.0, 100.0)]
    for a in widths:
        for b in widths:
            trpoint_set_width(p, a, b)
            o("  width %s %s -> %s %s"
              % (g9(a), g9(b), g9(p.LeftWidth), g9(p.RightWidth)))

    for i in range(NUM_DRIVING_LINES):
        p.set_dlo(i, (i - 10) * 271)
        p.set_dls(i, i * 12 + 3)
    for i in range(NUM_DRIVING_LINES):
        o("  line %2d off %s spd %s"
          % (i, g9(trpoint_get_driving_line_offset(p, i)),
             g9(trpoint_get_driving_line_speed(p, i))))

    p.Bits = (0x2a | (17 << TRP_ROADBLOCK_SHIFT) | (9 << TRP_TERRAIN_SHIFT) |
              (41 << TRP_RADARTRAP_SHIFT) | TRP_POSTED | TRP_POSTED_BACKWARDS)
    ppoint(o, "bits", p)
    p.Bits = 0xffffffff
    ppoint(o, "allbits", p)


def s_build(o, g):
    r = g.routes[0]
    o("scenario build")
    rseed(0x13572468)
    dirty(r.buf, 0, SZ_ROUTE, 0x5c)
    build_route(r, 3, 9, f32(-100.0), f32(40.0), f32(0.75))
    proute(o, "built", r)

    for i in range(r.NumPoints):
        p = r.point(i)
        f = troute_get_relative_point(r, p, 1)
        b = troute_get_relative_point(r, p, 0)
        o("  rel %d fwd %d back %d"
          % (i, troute_get_point_number(r, f) if f else -1,
             troute_get_point_number(r, b) if b else -1))

    for i in range(r.NumPoints):
        rc = troute_calculate_point_direction(r, r.point(i))
        o("  calc %d -> %d len %s" % (i, rc, g9(r.point(i).Length)))

    for i in range(4):
        idx = i * 3
        vx = frand(f32(50.0))
        vy = frand(f32(50.0))
        vz = frand(f32(10.0))
        if idx >= r.NumPoints:
            idx = r.NumPoints - 1
        rc = troute_move_point(r, r.point(idx), (vx, vy, vz))
        o("  move %d to %s %s %s -> %d" % (idx, g9(vx), g9(vy), g9(vz), rc))
        ppoint(o, "moved", r.point(idx))

    o("  move oob -> %d"
      % troute_move_point(r, r.point(r.NumPoints + 2),
                          (f32(1.0), f32(2.0), f32(3.0))))

    r.MaxPoints = r.NumPoints + 2
    for i in range(4):
        x = frand(f32(30.0))
        y = frand(f32(30.0))
        got = troute_add_point(r, (x, y), f32(1.0), f32(3.0), f32(4.0))
        o("  add -> %s" % ("point" if got else "null"))
    o("  pts %d max %d" % (r.NumPoints, r.MaxPoints))

    s = g.routes[4]
    dirty(s.buf, 0, SZ_ROUTE, 0x1d)
    troute_init(s, 12)
    troute_add_point(s, (f32(3.0), f32(-7.0)), f32(2.0), f32(5.0), f32(6.0))
    ppoint(o, "lone", s.point(0))
    o("  lone calc %d" % troute_calculate_point_direction(s, s.point(0)))


def s_driving_lines(o, g):
    r = g.routes[1]
    o("scenario driving lines")
    rseed(0x2468ace0)
    dirty(r.buf, 0, SZ_ROUTE, 0x77)
    build_route(r, 5, 6, f32(0.0), f32(0.0), f32(-0.25))

    for i in range(r.NumPoints):
        p = r.point(i)
        for j in range(NUM_DRIVING_LINES):
            p.set_dlo(j, (i * 31 + j * 7) - 200)
            p.set_dls(j, i * 5 + j * 3)
    for i in range(NUM_DRIVING_LINES):
        info = r.line(i)
        info.Flags = DLI_IS_VALID | (DLI_IS_FAKE if i & 1 else 0)
        info.LineTime = fadd(60.0, f32(i))
        info.set_name("DRIVER%d" % i)

    o("  has %d" % troute_has_driving_line_data(r))
    r.point(r.NumPoints // 2).set_dls(0, 31)
    o("  has31 %d" % troute_has_driving_line_data(r))
    r.point(r.NumPoints // 2).set_dls(0, 30)
    o("  has30 %d" % troute_has_driving_line_data(r))
    r.point(r.NumPoints // 2).set_dls(1, 200)
    o("  has200 %d" % troute_has_driving_line_data(r))

    troute_erase_driving_line(r, 4)
    o("  erased 4")
    for i in range(r.NumPoints):
        plines(o, r.point(i))
    for i in range(NUM_DRIVING_LINES):
        d = r.line(i)
        o("  line %2d flags %08x time %s name %s"
          % (i, d.Flags, g9(d.LineTime), d.name()[:20]))


def s_reverse(o, g):
    r = g.routes[2]
    o("scenario reverse")
    S.TrackLength = f32(4000.0)
    rseed(0x0badf00d)
    dirty(r.buf, 0, SZ_ROUTE, 0x2b)
    build_route(r, 7, 7, f32(200.0), f32(-50.0), f32(0.5))
    for i in range(r.NumPoints):
        p = r.point(i)
        p.DistanceAroundTrack = fmul(f32(i), 133.0)
        p.BankSlope = frand(f32(0.5))
        for j in range(NUM_DRIVING_LINES):
            p.set_dlo(j, i * 100 + j)
            p.set_dls(j, i * 10 + j)
    for i in range(NUM_DRIVING_LINES):
        info = r.line(i)
        info.Flags = i + 1
        info.LineTime = fmul(f32(i), 2.5)
        info.set_name("L%d" % i)
    proute(o, "before", r)

    trpoint_reverse_point(r.point(1))
    o("  one point reversed")
    ppoint(o, "p1", r.point(1))
    plines(o, r.point(1))

    troute_reverse_route(r)
    proute(o, "reversed", r)
    troute_reverse_route(r)
    proute(o, "unreversed", r)

    trpoint_swap_point_data(r.point(0), r.point(3))
    o("  swapped 0 and 3")
    ppoint(o, "p0", r.point(0))
    plines(o, r.point(0))
    ppoint(o, "p3", r.point(3))
    plines(o, r.point(3))

    troute_reverse_traffic_route(r)
    o("  traffic reversed")
    for i in range(r.NumPoints):
        o("  dist %d %s" % (i, g9(r.point(i).DistanceAroundTrack)))


def s_find(o, g):
    r = g.routes[3]
    o("scenario find")
    S.TrackLength = f32(3000.0)
    rseed(0xfeedbeef)
    dirty(r.buf, 0, SZ_ROUTE, 0x40)
    build_route(r, 9, 24, f32(-50.0), f32(-50.0), f32(0.3))
    for i in range(r.NumPoints):
        p = r.point(i)
        p.DistanceAroundTrack = fmul(f32(i), 61.0)
        bits = p.Bits & ~(TRP_POSTED | TRP_NO_HELISHEET)
        if i % 3 == 0:
            bits |= TRP_POSTED
        if i % 4 == 0:
            bits |= TRP_NO_HELISHEET
        p.Bits = bits

    for f in range(8):
        flags = ((TRFIND_AHEAD_ONLY if f & 1 else 0) |
                 (TRFIND_POSTED_ONLY if f & 2 else 0) |
                 (TRFIND_NO_HELISHEET if f & 4 else 0))
        for k in range(6):
            radius = fadd(20.0, fmul(f32(k), 40.0))
            qx = frand(f32(400.0))
            qy = frand(f32(400.0))
            p = troute_find_closest_point(r, (qx, qy), radius, flags,
                                          f32(0.0))
            o("  find flags %d r %s at %s %s -> %d"
              % (flags, g9(radius), g9(qx), g9(qy),
                 troute_get_point_number(r, p) if p else -1))

    for i in range(6):
        d = fmul(f32(i), 250.0)
        qx = frand(f32(400.0))
        qy = frand(f32(400.0))
        p = troute_find_closest_point(r, (qx, qy), f32(400.0),
                                      TRFIND_BY_TRACK_DISTANCE, d)
        o("  findd d %s at %s %s -> %d"
          % (g9(d), g9(qx), g9(qy),
             troute_get_point_number(r, p) if p else -1))
        o("  away %s"
          % g9(trpoint_get_distance_away(r.point(3), (qx, qy), d)))

    far = troute_find_closest_point(r, (f32(100000.0), f32(100000.0)),
                                    f32(10.0), 0, f32(0.0))
    o("  far -> %d" % (1 if far else 0))

    mid = r.point(r.NumPoints // 2)
    q = (mid.PosX, mid.PosY)
    for i in range(r.NumPoints):
        p = troute_find_closest_point_ahead(r, q, r.point(i))
        o("  ahead from %d -> %d"
          % (i, troute_get_point_number(r, p) if p else -1))
    mn, _mx = r.bbox()
    o("  ahead null %d %d"
      % (1 if troute_find_closest_point_ahead(r, None, r.point(0)) else 0,
         1 if troute_find_closest_point_ahead(r, tuple(mn), None) else 0))


def s_span(o, g):
    r = g.routes[3]
    o("scenario span")
    S.TrackLength = f32(900.0)
    S.DistanceFn = test_distance

    troute_set_first_and_last(r)
    o("  span %s %s" % (g9(r.fStartDistance), g9(r.fEndDistance)))
    for i in range(12):
        d = fmul(f32(i), 80.0)
        o("  within %s -> %d" % (g9(d), troute_distance_is_within_route(r, d)))

    s = g.routes[4]
    rseed(0x600dbeef)
    dirty(s.buf, 0, SZ_ROUTE, 0x91)
    build_route(s, 11, 5, f32(0.0), f32(0.0), f32(0.0))
    troute_set_first_and_last(s)
    o("  nowrap span %s %s" % (g9(s.fStartDistance), g9(s.fEndDistance)))
    for i in range(12):
        d = fmul(f32(i), 80.0)
        o("  nowrap within %s -> %d"
          % (g9(d), troute_distance_is_within_route(s, d)))

    w = g.routes[4]
    dirty(w.buf, 0, SZ_ROUTE, 0x3e)
    troute_init(w, 13)
    for k in range(3):
        troute_add_point(w, (fmul(f32(k), 600.0), f32(0.0)), f32(0.0),
                         f32(5.0), f32(5.0))
    troute_set_first_and_last(w)
    o("  wide span %s %s" % (g9(w.fStartDistance), g9(w.fEndDistance)))

    for i in range(-6, 7):
        a = fadd(450.0, fmul(f32(i), 100.0))
        o("  cmp %s -> %s" % (g9(a), g9(compare_distances(a, f32(450.0)))))

    S.DistanceFn = None


def s_load(o, g):
    o("scenario load")
    rseed(0x0c0ffee)
    at = 8
    nums = (2, 4, 50, 61)
    for i in range(4):
        dirty(g.routes[i].buf, 0, SZ_ROUTE, 0x30 + i)
        build_route(g.routes[i], nums[i], 3 + i * 2, fmul(f32(i), 100.0),
                    fmul(f32(i), -30.0), f32(0.2))
        at += emit_route(g.chunk, at, g.routes[i])
    used = at - 8
    struct.pack_into("<I", g.chunk, 0, CHUNK_TRACK_ROUTES)
    struct.pack_into("<I", g.chunk, 4, used)
    o("  payload %d bytes" % used)

    trmgr_init()
    plists(o)
    o("  loader -> %d" % track_routes_loader(g.chunk))
    plists(o)
    for i in range(MAX_ROUTES):
        r = S.pTrackRoutes[i]
        if r is not None:
            o("  slot %d n %d pts %d flags %08x"
              % (i, r.RouteNumber, r.NumPoints, r.Flags))

    fl = (0, TRFIND_SKIP_RACING, TRFIND_SKIP_TRAFFIC,
          TRFIND_SKIP_RACING | TRFIND_SKIP_TRAFFIC)
    for i in range(4):
        for _k in range(4):
            qx = frand(f32(400.0))
            qy = frand(f32(400.0))
            pt = trmgr_find_closest_point((qx, qy), f32(500.0), fl[i],
                                          f32(0.0))
            o("  mfind flags %d at %s %s -> %s %d"
              % (fl[i], g9(qx), g9(qy), "rnum" if pt else "null",
                 pt.RouteNumber if pt else -1))

    o("  unloader -> %d" % track_routes_unloader(g.chunk))
    plists(o)
    for i in range(MAX_ROUTES):
        if S.pTrackRoutes[i] is not None:
            o("  leftover %d" % i)

    struct.pack_into("<I", g.chunk, 0, 0x00034999)
    o("  foreign load %d unload %d"
      % (track_routes_loader(g.chunk), track_routes_unloader(g.chunk)))
    struct.pack_into("<I", g.chunk, 0, CHUNK_TRACK_ROUTES)

    # The signpost chunk: no count field anywhere, just the size divided.
    sc = bytearray(8 + 3 * SZ_SIGN)
    struct.pack_into("<I", sc, 0, CHUNK_TRACK_SIGNPOSTS)
    struct.pack_into("<I", sc, 4, 3 * SZ_SIGN)
    for k in range(3 * SZ_SIGN):
        sc[8 + k] = (k * 11 + 1) & 0xff
    rc = track_routes_loader(sc)
    o("  sign chunk load %d n %d present %d"
      % (rc, S.NumSignposts, signposts_present()))
    psigns(o, "from chunk")
    rc = track_routes_unloader(sc)
    o("  sign chunk unload %d n %d present %d"
      % (rc, S.NumSignposts, signposts_present()))


def s_sort(o, g):
    o("scenario sort")
    rseed(0xa5a5f00f)
    for n in (0, 1, 2, 3, 7, 16, 17):
        v = [frand(f32(100.0)) for _ in range(n)]
        o("  in %d:" % n + "".join(" %s" % g9(x) for x in v))
        heap_sort(v, fsub)
        o("  out %d:" % n + "".join(" %s" % g9(x) for x in v))
    v = [f32(x) for x in (2.0, 1.0, 2.0, 1.0, 2.0, 1.0)]
    heap_sort(v, fsub)
    o("  ties:" + "".join(" %s" % g9(x) for x in v))

    # Ties with the elements told apart, which is the only way the sift-down
    # sibling choice shows up at all: two equal floats print the same.
    vals = (3.0, 1.0, 2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0)
    t = [[f32(x), i] for i, x in enumerate(vals)]
    heap_sort(t, lambda a, b: fsub(a[0], b[0]))
    o("  tagged:" + "".join(" %s/%d" % (g9(e[0]), e[1]) for e in t))


def s_signs(o, g):
    o("scenario signs")
    S.TrackLength = f32(900.0)
    S.DistanceFn = test_distance

    rseed(0x77777777)
    at = 8
    nums = (1, 2, 50, 51)
    for i in range(4):
        dirty(g.routes[i].buf, 0, SZ_ROUTE, 0x50 + i)
        build_route(g.routes[i], nums[i], 6 + i, fmul(f32(i), 90.0),
                    fmul(f32(i), 45.0), f32(0.4))
        at += emit_route(g.chunk, at, g.routes[i])
    struct.pack_into("<I", g.chunk, 0, CHUNK_TRACK_ROUTES)
    struct.pack_into("<I", g.chunk, 4, at - 8)
    trmgr_init()
    track_routes_loader(g.chunk)

    o("  signposts present %d" % signposts_present())
    S.SignBuf = g.signs
    S.SignBase = 0
    S.NumSignposts = 8
    route = (1, 2, 2, 1, 1, 50, 50, 51)
    for i in range(8):
        s = sign(i)
        s.NewRoute = route[i]
        s.NewPoint = 1 + i // 2
        s.Flags = (i & 7) | ((i & 1) << 3)
        s.Distance = f32(0.0)
    for i in range(8):
        p = signpost_get_new_route_point(sign(i))
        if p is None:
            continue
        p.Bits = (p.Bits & ~TRP_SIGN_MASK) | (i ^ 1)
    o("  signposts present %d" % signposts_present())
    psigns(o, "initial")

    for i in range(8):
        r = signpost_get_new_route(sign(i))
        p = signpost_get_new_route_point(sign(i))
        o("  sign %d route %d point %d racing %d"
          % (i, r.RouteNumber if r else -1,
             troute_get_point_number(r, p) if p else -1,
             signpost_is_racing_route(sign(i))))

    signpost_set_distances()
    psigns(o, "distances")

    for i in range(-1, 12):
        d = fmul(f32(i), 90.0)
        o("  index %s -> %d" % (g9(d), signpost_get_index(d)))

    signpost_reverse_signs()
    psigns(o, "reversed")
    signpost_reverse_signs()
    psigns(o, "unreversed")

    signpost_test_consistency()
    o("  consistency ran")

    S.DistanceFn = None


def s_init(o, g):
    o("scenario init")
    S.TrackLength = f32(900.0)
    S.DistanceFn = test_distance

    for i in range(8):
        sign(i).Distance = f32(0.0)
    init_track_routes(1)
    psigns(o, "after init fwd")
    for i in range(MAX_ROUTES):
        r = S.pTrackRoutes[i]
        if r is None:
            continue
        o("  route %d span %s %s"
          % (r.RouteNumber, g9(r.fStartDistance), g9(r.fEndDistance)))
        for j in range(r.NumPoints):
            o("    p%d sign %d" % (j, r.point(j).sign_number()))

    init_track_routes(0)
    psigns(o, "after init rev")
    for i in range(MAX_ROUTES):
        r = S.pTrackRoutes[i]
        if r is None:
            continue
        o("  route %d flags %08x span %s %s"
          % (r.RouteNumber, r.Flags, g9(r.fStartDistance),
             g9(r.fEndDistance)))

    close_track_routes()
    o("  closed")
    S.DistanceFn = None


SCENARIOS = [
    ("point", s_point), ("build", s_build),
    ("driving lines", s_driving_lines), ("reverse", s_reverse),
    ("find", s_find), ("span", s_span), ("load", s_load), ("sort", s_sort),
    ("signs", s_signs), ("init", s_init),
]


class Statics(object):
    """The harness statics, which live as long as the run does."""

    def __init__(self):
        self.routes = [Route(bytearray(SZ_ROUTE), 0) for _ in range(5)]
        self.chunk = bytearray(65536)
        self.signs = bytearray(8 * SZ_SIGN)


def model():
    reset_state()
    o = Out()
    g = Statics()
    o("sizes route %d point %d info %d sign %d"
      % (SZ_ROUTE, SZ_POINT, SZ_INFO, SZ_SIGN))
    for _name, fn in SCENARIOS:
        fn(o, g)
    return o.lines


# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_c(exe):
    # No pipe: a runaway harness cannot be drained and cannot be killed
    # reliably from Windows, which is how geometry_check deadlocked.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.txt"
        with open(path, "w", newline=NL) as fh:
            try:
                rc = subprocess.run([str(exe)], stdout=fh,
                                    stderr=subprocess.DEVNULL,
                                    timeout=HARNESS_TIMEOUT).returncode
            except subprocess.TimeoutExpired:
                sys.exit("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        if rc != 0:
            sys.exit("harness exited %d" % rc)
        with open(path, "r", newline=NL) as fh:
            return fh.read().split(NL)[:-1]


def diff(a, b, limit=40):
    bad = 0
    shown = 0
    for line in difflib.unified_diff(a, b, "port", "model", n=0, lineterm=""):
        if line[:1] in ("-", "+") and line[:3] not in ("---", "+++"):
            bad += 1
            if shown < limit:
                print(line)
                shown += 1
    return shown, bad // 2 if bad else 0


# ----------------------------------------------------------------- mutations
#
# One per behavioural claim the module makes. A mutation that does not move a
# line is either an untested rule or an equivalent mutant, and the difference
# has to be worked out rather than assumed -- see CONTINUE.md.

TR = "3DS Files/source/trackroute.c"

MUTATIONS = [
    ("ctor-sign-not-set", TR,
     "    p->Bits = ((p->Bits & ~0xffu) | 0xffu) | 0x0fc03f00u;",
     "    p->Bits = (p->Bits & ~0xffu) | 0x0fc03f00u;"),
    ("ctor-posted-kept", TR,
     "    p->Bits &= ~(TRP_NO_HELISHEET | TRP_POSTED | TRP_POSTED_BACKWARDS);",
     "    p->Bits &= ~(TRP_NO_HELISHEET | TRP_POSTED);"),
    ("ctor-slopes-kept", TR,
     "    p->BankSlope    = 0.0f;\n    p->ForwardSlope = 0.0f;",
     "    p->BankSlope    = 0.0f;"),
    ("pos2-perp-flipped", TR,
     "    perp.x = p->Direction.y;\n    perp.y = -p->Direction.x;",
     "    perp.x = -p->Direction.y;\n    perp.y = p->Direction.x;"),
    ("pos2-order-swapped", TR,
     "    bScaleAdd2(o, &p->Position, &perp, l);\n"
     "    bScaleAdd2(o, o, &p->Direction, d);",
     "    bScaleAdd2(o, &p->Position, &p->Direction, d);\n"
     "    bScaleAdd2(o, o, &perp, l);"),
    ("pos3-pad-written", TR,
     "    o->z = az * d + o->z;",
     "    o->z = az * d + o->z;\n    o->pad = 0.0f;"),
    ("pos3-bank-ignored", TR,
     "    float lz = p->BankSlope;",
     "    float lz = 0.0f;"),
    ("width-hi-clamp", TR,
     "    if (64.0f < left)  left  = 64.0f;",
     "    if (65.0f < left)  left  = 65.0f;"),
    ("width-lo-clamp", TR,
     "    if (right < 1.0f)  right = 1.0f;",
     "    if (right < 0.0f)  right = 0.0f;"),
    ("swap-56-bytes", TR,
     "    uint8_t tmp[48];\n\n    memcpy(tmp, a, 48);\n"
     "    memcpy(a, b, 48);\n    memcpy(b, tmp, 48);",
     "    uint8_t tmp[56];\n\n    memcpy(tmp, a, 56);\n"
     "    memcpy(a, b, 56);\n    memcpy(b, tmp, 56);"),
    ("reverse-no-step", TR,
     "    trpoint_get_position3(p, &moved, p->Length, 0.0f);",
     "    trpoint_get_position3(p, &moved, 0.0f, 0.0f);"),
    ("reverse-widths-kept", TR,
     "    p->RightWidth   = left;",
     "    p->RightWidth   = right;"),
    ("reverse-lines-kept", TR,
     "    for (i = 0; i < 10; ++i) {\n"
     "        int16_t o = p->DrivingLineOffsets[i];",
     "    for (i = 0; i < 0; ++i) {\n"
     "        int16_t o = p->DrivingLineOffsets[i];"),
    ("distance-away-no-slack", TR,
     "    along = (along < 0.0f ? -along : along) - TR_POINT_SPACING;",
     "    along = (along < 0.0f ? -along : along);"),
    ("distance-away-takes-min", TR,
     "    return plane < along ? along : plane;",
     "    return plane < along ? plane : along;"),
    ("line-offset-scale", TR,
     "    return (float)((int32_t)p->DrivingLineOffsets[line] << 8) * "
     "0.0000152587890625f;",
     "    return (float)((int32_t)p->DrivingLineOffsets[line] << 9) * "
     "0.0000152587890625f;"),
    ("line-speed-scale", TR,
     "    return (float)((int32_t)p->DrivingLineSpeeds[line] << 16) * "
     "0.0000152587890625f;",
     "    return (float)((int32_t)p->DrivingLineSpeeds[line] << 15) * "
     "0.0000152587890625f;"),
    ("init-type-racing-range", TR,
     "    r->Type        = routeNumber < 50 ? TRACK_ROUTE_RACING",
     "    r->Type        = routeNumber < 5 ? TRACK_ROUTE_RACING"),
    ("init-type-traffic-range", TR,
     "                   : (routeNumber < 70 ? TRACK_ROUTE_TRAFFIC",
     "                   : (routeNumber < 60 ? TRACK_ROUTE_TRAFFIC"),
    ("init-flags-wiped", TR,
     "    r->Flags      &= ~(TROUTE_MEMORY_IMAGE_LOADED | TROUTE_REVERSED);",
     "    r->Flags       = 0;"),
    ("addpoint-max-off-by-one", TR,
     "    if (r->NumPoints >= r->MaxPoints) return 0;",
     "    if (r->NumPoints > r->MaxPoints) return 0;"),
    ("addpoint-length-seed", TR,
     "    p->Length = 4.0f;",
     "    p->Length = 24.0f;"),
    ("addpoint-first-direction", TR,
     "        p->Direction.y  = 0.0f;\n        p->Direction.x  = 1.0f;",
     "        p->Direction.y  = 1.0f;\n        p->Direction.x  = 0.0f;"),
    ("relpoint-forward-edge", TR,
     "        if (i + 1 < r->NumPoints) return &r->TrackRoutePointTable[i + 1];",
     "        if (i + 1 <= r->NumPoints) return &r->TrackRoutePointTable[i + 1];"),
    ("calcdir-slope-not-shared", TR,
     "    p->ForwardSlope    = slope;\n    next->ForwardSlope = slope;",
     "    p->ForwardSlope    = slope;"),
    ("calcdir-upper-range", TR,
     "    if (TR_POINT_SPACING < len) return 1;",
     "    if (34.0f < len) return 1;"),
    ("movepoint-elevation-fixed", TR,
     "    p->Elevation  = pos->x;",
     "    p->Elevation  = pos->z;"),
    ("movepoint-skips-previous", TR,
     "    if (i > 0)\n        n += troute_calculate_point_direction(\n"
     "                 r, &r->TrackRoutePointTable[i - 1]);",
     "    (void)0;"),
    ("find-no-bbox-early-out", TR,
     "    if (!bBoundingBoxIsInside2(&r->BBoxMin, &r->BBoxMax, pos, radius))\n"
     "        return 0;",
     "    (void)0;"),
    ("find-radius-not-tightened", TR,
     "            best   = p;\n            radius = dist;",
     "            best   = p;"),
    ("find-skip-heuristic", TR,
     "        skip = (int)(dist * TR_INV_POINT_SPACING) - 2;",
     "        skip = (int)(dist * TR_INV_POINT_SPACING) - 1;"),
    ("find-ahead-sense", TR,
     "            if ((flags & TRFIND_AHEAD_ONLY) && !(0.0f < dot)) break;",
     "            if ((flags & TRFIND_AHEAD_ONLY) && !(dot < 0.0f)) break;"),
    ("ahead-last-point-counts", TR,
     "    return i < n ? p : 0;",
     "    return i <= n ? p : 0;"),
    ("erase-line-time", TR,
     "    info->LineTime = TR_NO_LINE_TIME;",
     "    info->LineTime = 0.0f;"),
    ("hasline-threshold", TR,
     "        if (30.0f < trpoint_get_driving_line_speed(mid, k)) return 1;",
     "        if (29.0f < trpoint_get_driving_line_speed(mid, k)) return 1;"),
    ("hasline-lines-checked", TR,
     "    for (k = 0; k < 2; ++k)",
     "    for (k = 0; k < 1; ++k)"),
    ("reverse-route-flag-toggle", TR,
     "    r->Flags = (r->Flags & ~TROUTE_REVERSED) |\n"
     "               ((~(r->Flags >> 1) & 1u) << 1);",
     "    r->Flags |= TROUTE_REVERSED;"),
    ("setfirstlast-half-lap", TR,
     "    float half = TheTrackPathManager.TrackLength * 0.5f;",
     "    float half = TheTrackPathManager.TrackLength * 0.25f;"),
    ("setfirstlast-wrapped-pick", TR,
     "        r->fStartDistance = mn[0] > mn[1] ? mn[0] : mn[1];",
     "        r->fStartDistance = mn[0] < mn[1] ? mn[0] : mn[1];"),
    ("within-wrapped-and", TR,
     "    return after || before;",
     "    return after && before;"),
    ("within-order", TR,
     "    int after  = r->fStartDistance <= d;",
     "    int after  = d <= r->fStartDistance;"),
    ("loader-fixed-stride", TR,
     "        p += (uint32_t)sizeof(TrackRoute) -\n"
     "             (uint32_t)(TRACK_ROUTE_MAX_POINTS - r->NumPoints) *\n"
     "                 (uint32_t)sizeof(TrackRoutePoint);",
     "        p += (uint32_t)sizeof(TrackRoute);"),
    ("unloader-keeps-slot", TR,
     "        m->pTrackRoutes[i] = 0;",
     "        (void)0;"),
    ("mgr-find-one-pass", TR,
     "    for (pass = 0; pass < 2; ++pass) {",
     "    for (pass = 0; pass < 1; ++pass) {"),
    ("reverse-routes-traffic-split", TR,
     "        if (i >= 50) troute_reverse_traffic_route(r);",
     "        if (i >= 60) troute_reverse_traffic_route(r);"),
    ("signpost-racing-limit", TR,
     "    return s->NewRoute < 50;",
     "    return s->NewRoute < 60;"),
    ("signpost-reverse-point", TR,
     "        s->NewPoint = (uint16_t)(r->NumPoints - s->NewPoint - 1);",
     "        s->NewPoint = (uint16_t)(r->NumPoints - s->NewPoint);"),
    ("signpost-distance-one-hop", TR,
     "        trackpath_coord_update_position(&coord, &target->Position);",
     "        trackpath_coord_update_position(&coord, &p->Position);"),
    ("signpost-index-sense", TR,
     "        if (!(SignpostArray[i].Distance < d)) return (int)i;",
     "        if (SignpostArray[i].Distance < d) return (int)i;"),
    ("signpost-chunk-shift", TR,
     "        NumSignposts  = bchunk_u32(chunk + 4) >> 3;",
     "        NumSignposts  = bchunk_u32(chunk + 4) >> 2;"),
    ("heapsort-tie-order", TR,
     "                cmp(ra + (j - 1) * size, ra + j * size) < 0.0f)",
     "                cmp(ra + (j - 1) * size, ra + j * size) <= 0.0f)"),
    ("init-no-remap", TR,
     "            p->Bits = (p->Bits & ~TRP_SIGN_MASK) | remap[sign];",
     "            (void)sign;"),
    ("init-remaps-none-sign", TR,
     "            if (sign == TRP_SIGN_MASK) continue;",
     "            (void)0;"),
]

# Mutants that do not move a line because they cannot. Each one is an
# argument, not an excuse.
#
#   find-no-bbox-early-out -- the bounding box holds every point on the
#   route, so a query outside it grown by `radius` is further than `radius`
#   from all of them in at least one axis, and therefore further than
#   `radius` in the plane. The track-distance metric cannot rescue such a
#   point either: GetDistanceAway returns the larger of the plane distance
#   and the along-track one, so it is never below the plane distance. The
#   test can only ever save the loop, never change what it returns.
EQUIVALENT = ["find-no-bbox-early-out"]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(py_lines):
    survived = []
    originals = {}
    paths = {}
    for _n, rel, _o, _r in MUTATIONS:
        if rel not in originals:
            paths[rel] = ROOT / rel
            # newline="" so the CRLF the ported sources carry survives the
            # round trip. write_source writes with newline="" too, so a
            # universal-newlines read here would quietly rewrite every
            # mutated file to LF and leave it that way after the restore.
            originals[rel] = paths[rel].read_text(encoding="utf-8",
                                                  newline="")
    try:
        for name, rel, old, new in MUTATIONS:
            src = paths[rel]
            text = originals[rel]

            # A multi-line pattern written with bare newlines misses every
            # time against a CRLF source -- and here that reads as "hits 0
            # times, skipped", which counts as a survivor rather than as a
            # mutation that never ran.
            crlf = (chr(13) + NL) in text
            old = old.replace(NL, chr(13) + NL) if crlf else old
            new = new.replace(NL, chr(13) + NL) if crlf else new

            if text.count(old) != 1:
                print("  %-30s pattern hits %d times, skipped"
                      % (name, text.count(old)))
                survived.append(name)
                continue
            write_source(src, text.replace(old, new, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="trackroute_test")
                except SystemExit:
                    print("  %-30s did not compile (counts as caught)" % name)
                    write_source(src, text)
                    continue
                try:
                    got = run_c(exe)
                except SystemExit:
                    print("  %-30s crashed the harness (caught)" % name)
                    write_source(src, text)
                    continue
            write_source(src, text)
            _d, bad = diff(got, py_lines, limit=0)
            if bad:
                print("  %-30s caught, %d lines" % (name, bad))
            elif name in EQUIVALENT:
                print("  %-30s survived, equivalent by construction" % name)
                survived.append(name)
            else:
                print("  %-30s SURVIVED" % name)
                survived.append(name)
    finally:
        for rel, text in originals.items():
            try:
                write_source(paths[rel], text)
            except OSError:
                sys.exit("could not restore %s -- it still holds a mutation. "
                         "Put the original line back before trusting "
                         "anything printed above." % rel)
    return survived


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mutate", action="store_true",
                    help="break the C a rule at a time and re-diff")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    a = ap.parse_args()

    ours = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="trackroute_test")
        port = run_c(exe)

    if a.dump:
        for tag, lines in (("port", port), ("model", ours)):
            with open("%s.%s.txt" % (a.dump, tag), "w", newline=NL) as fh:
                fh.write(NL.join(lines) + NL)

    _d, bad = diff(port, ours)
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(port), bad))
    rc = 1 if bad else 0

    if a.mutate:
        if bad:
            print("not mutating while the baseline differs")
            return rc
        print("mutations:")
        survived = mutate_pass(ours)
        holes = [s for s in survived if s not in EQUIVALENT]
        print("%d mutations, %d caught, %d equivalent, %d unexplained"
              % (len(MUTATIONS), len(MUTATIONS) - len(survived),
                 len(survived) - len(holes), len(holes)))
        for s in holes:
            print("  SURVIVED: %s" % s)
        rc |= 1 if holes else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
