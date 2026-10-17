#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carinfo.c, retail's carinfo.cpp, against the
retail image itself, run in mipsemu.

The model is the image. Retail's static constructor (0x001890c8), with
AccelerationTable's constructor (0x00188d68) under it, LoaderCarInfo
(0x00187f98), UnloaderCarInfo (0x00188128), GetAccelerationTable
(0x00188dd8) and MakeAccelerationTable (0x00188df0) run as shipped, and
under them CalculateShiftPoints (0x0018ac38) and Table's constructor,
GetValue and SetMinMax. Only bMalloc (0x002577c0) is stubbed, on both
sides: it prints its arguments and, after the op, what the allocation
holds. The harness (tools/src/carinfo_test.c) runs the port over the same
script, and the two transcripts are diffed.

The chunks are GLOBAL/GLOBALB.BUN's own two, the car records at each of
the four word alignments, the records changed type by type (the gears,
the split, the engine, the curve, the mass and the radius, and one whose
RPM lands on its up point exactly) under several drivetrain globals, and
chunks of other ids and sizes. The constructor runs at boot over zeroed
tables and again over tables filled with a pattern. Before some loads
the model fills the stack with a pattern, which the harness never sees:
MakeAccelerationTable's shift points live on its stack, so a table that
read one CalculateShiftPoints had not written would differ.

After each op the transcript holds the globals, every bMalloc and each of
the 64 tables that changed since it was last printed. A float prints as
its bits.

    python tools/carinfo_check.py
    python tools/carinfo_check.py --mutate [--only a,b]
    python tools/carinfo_check.py --dump out/carinfo
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/carinfo_test.c"
CI = "3DS Files/source/carinfo.c"
SOURCES = [HARNESS, CI] + ["3DS Files/source/" + f for f in (
    "cartypeinfo.c", "langtab.c", "portlang.c", "drivetrain.c", "engine.c", "wheel.c",
    "vtable.c",
    "replay.c", "p32.c",
    "suspension.c", "steering.c", "rigidbody.c", "carstate.c", "emath.c",
    "bmatrix.c", "table.c", "bvector.c", "bmath.c", "bmathtab.c")]

HARNESS_TIMEOUT = 120
GLOBALB = ROOT / "extracted-retail" / "GLOBAL" / "GLOBALB.BUN"

# ================================================================ the image

GP = 0x003358f0
LOADER = 0x00187f98
UNLOADER = 0x00188128
GET_TABLE = 0x00188dd8
MAKE_TABLE = 0x00188df0
SINIT = 0x001890c8
FIND_LANG = 0x00187e80
INIT_CAR_INFO = 0x00188d08
LANG_TABLE = 0x0030d578           # CarLanguageInfo, 50 rows of 28
LANG_ROW = 28
BMALLOC = 0x002577c0
TABLES = 0x0030daf0               # TheCarTypeAccelerationTable
TABLE_STRIDE = 148
NUM_TYPES = 64
DEMO_DISC = 0x002effe0            # TheDemoDiscManager.bActive

G_ARRAY = GP - 20616              # CarTypeInfoArray
G_SKINS = GP - 20612              # SkinInfoTable
G_NSKINS = GP - 20608             # NumSkinInfo
G_UP = GP - 20548                 # gShiftUpDetune
G_DOWN = GP - 20544               # gShiftDownDetune
G_METHOD = GP - 20540             # gGearShiftMethod
GLOBALS = {"up": G_UP, "down": G_DOWN, "method": G_METHOD}

CHUNK_BASE = 0x01000000
CHUNK_SPAN = 0x40000
MAKE_T = 0x01e00000               # the M op's Table
MAKE_ENTRIES = MAKE_T + 0x100
STACK_FILL = 0x8000

REC = 1376                        # CarTypeInfo
CAR_CHUNK = 0x00034600
SKIN_CHUNK = 0x00034601

# CarTypeInfo, retail's offsets.
R0_RADIUS = 288 + 12              # Wheels[0].Radius
R2_RADIUS = 288 + 2 * 32 + 12     # Wheels[2].Radius
MASS = 480                        # Body.Mass
DT = 624                          # DriveTrain
DT_SHIFT_UP, DT_FD0, DT_FD1, DT_SPLIT = DT + 0, DT + 8, DT + 12, DT + 16
DT_NGEARS, DT_RATIOS = DT + 24, DT + 32
EN = 688                          # Engine
EN_IDLE, EN_RED, EN_MAX, EN_CURVE = EN + 0, EN + 4, EN + 8, EN + 16


def fb(v):
    return f_to_bits(v)


# ================================================================ the data

def globalb_chunks():
    """GLOBALB's 0x34600 and 0x34601, each as its header and payload."""
    data = GLOBALB.read_bytes()
    out = {}
    off = 0
    while off + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, off)
        if cid in (CAR_CHUNK, SKIN_CHUNK):
            out[cid] = data[off:off + 8 + size]
        off += 8 + size
    return out


def car_records(chunk):
    """The 64 records, from the first 16-byte boundary past the header."""
    return bytearray(chunk[16:16 + NUM_TYPES * REC])


def r_line(k, mis, header, records):
    return "K %d %d r %s" % (k, mis, (header + bytes(records)).hex())


def p_line(k, mis, data):
    return "K %d %d p %s" % (k, mis, bytes(data).hex())


def put_f(recs, i, off, v):
    struct.pack_into("<f", recs, i * REC + off, v)


def put_i(recs, i, off, v):
    struct.pack_into("<i", recs, i * REC + off, v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def rpm_at_step(k):
    """The RPM the walk's k'th step leaves over a radius, final drive and
    ratio of 1, each operation rounded to single as the EE rounds it."""
    step, per_rads = f32(1.38888896), f32(9.54930401)
    speed = 0.0
    for _ in range(k):
        speed = f32(speed + step)
    return f32(speed * per_rads)


def made_up(recs):
    """The 64 records changed type by type. Each type keeps its own car's
    data but for what the case names; none divides by zero, and none has
    at most one gear with a MaxRPM at or below 0, which the port leaves
    out (carinfo.h)."""
    r = bytearray(recs)
    curve_up = [10.0 * (k + 1) for k in range(9)]
    curve_neg = [-50.0, -20.0, 0.0, 30.0, 80.0, 30.0, 0.0, -20.0, -50.0]
    cases = [
        # 0..6: every gear count from 0 to 6 on the Corvette.
        lambda i: put_i(r, i, DT_NGEARS, 0),
        lambda i: put_i(r, i, DT_NGEARS, 1),
        lambda i: put_i(r, i, DT_NGEARS, 2),
        lambda i: put_i(r, i, DT_NGEARS, 3),
        lambda i: put_i(r, i, DT_NGEARS, 4),
        lambda i: put_i(r, i, DT_NGEARS, 5),
        lambda i: put_i(r, i, DT_NGEARS, -1),
        # 7..10: the split, with the front and the rear apart.
        lambda i: (put_f(r, i, DT_SPLIT, 0.0), put_f(r, i, DT_FD0, 4.5),
                   put_f(r, i, R0_RADIUS, 0.28)),
        lambda i: (put_f(r, i, DT_SPLIT, 0.25), put_f(r, i, DT_FD0, 4.5),
                   put_f(r, i, R0_RADIUS, 0.28)),
        lambda i: (put_f(r, i, DT_SPLIT, 0.5), put_f(r, i, DT_FD1, 2.0),
                   put_f(r, i, R2_RADIUS, 0.4)),
        lambda i: (put_f(r, i, DT_SPLIT, 1.0), put_f(r, i, DT_FD0, 9.0),
                   put_f(r, i, R0_RADIUS, 0.9)),
        # 11..13: a red line out of reach, so the walk ends at 500 km/h.
        lambda i: put_f(r, i, EN_MAX, 100000.0),
        lambda i: (put_f(r, i, EN_MAX, 100000.0),
                   put_i(r, i, DT_NGEARS, 1)),
        lambda i: (put_f(r, i, EN_MAX, 40000.0),
                   put_f(r, i, DT_FD0, 1.0), put_f(r, i, DT_FD1, 1.0)),
        # 14..16: a narrow engine that shifts nearly every step.
        lambda i: (put_f(r, i, EN_IDLE, 500.0), put_f(r, i, EN_MAX, 700.0)),
        lambda i: (put_f(r, i, EN_IDLE, 900.0), put_f(r, i, EN_MAX, 1000.0),
                   put_f(r, i, DT_FD1, 12.0)),
        lambda i: (put_f(r, i, EN_IDLE, 3000.0), put_f(r, i, EN_MAX, 2000.0)),
        # 17..19: the curve rising, through zero, and flat.
        lambda i: [put_f(r, i, EN_CURVE + 4 * k, v)
                   for k, v in enumerate(curve_up)],
        lambda i: [put_f(r, i, EN_CURVE + 4 * k, v)
                   for k, v in enumerate(curve_neg)],
        lambda i: [put_f(r, i, EN_CURVE + 4 * k, 250.0) for k in range(9)],
        # 20..23: the ratios -- a first all but neutral, a reversed one,
        # a top gear of 0 (CalculateShiftPoints only divides by the gears
        # below it), a ladder that climbs.
        lambda i: put_f(r, i, DT_RATIOS + 8, 0.01),
        lambda i: put_f(r, i, DT_RATIOS + 12, -1.5),
        lambda i: put_f(r, i, DT_RATIOS + 28, 0.0),
        lambda i: [put_f(r, i, DT_RATIOS + 4 * (k + 2), 0.5 + 0.5 * k)
                   for k in range(6)],
        # 24..27: the mass and the radius.
        lambda i: put_f(r, i, MASS, 0.05),
        lambda i: put_f(r, i, MASS, 40.0),
        lambda i: (put_f(r, i, R2_RADIUS, 0.05)),
        lambda i: (put_f(r, i, R2_RADIUS, 2.5), put_f(r, i, MASS, -1.25)),
        # 28..31: the interpolated up points, read under method 0.
        lambda i: put_f(r, i, DT_SHIFT_UP, -0.5),
        lambda i: put_f(r, i, DT_SHIFT_UP, 0.0),
        lambda i: (put_f(r, i, DT_SHIFT_UP, 2.0), put_f(r, i, EN_RED, 9000.0)),
        lambda i: (put_f(r, i, DT_SHIFT_UP, -3.0), put_i(r, i, DT_NGEARS, 2)),
        # 32: the RPM landing on an up point exactly -- one gear, whose up
        # point is MaxRPM, over a drivetrain of ones, and MaxRPM the RPM
        # the third step leaves.
        lambda i: (put_i(r, i, DT_NGEARS, 1), put_f(r, i, DT_SPLIT, 0.0),
                   put_f(r, i, DT_FD0, 1.0), put_f(r, i, R0_RADIUS, 1.0),
                   put_f(r, i, DT_RATIOS + 8, 1.0),
                   put_f(r, i, EN_IDLE, 10.0),
                   put_f(r, i, EN_MAX, rpm_at_step(3))),
    ]
    for i, case in enumerate(cases):
        case(i)
    return r


def other_chunks():
    """Chunks no loader of these two takes, and the skin chunk's sizes."""
    junk = bytes(range(64))
    out = []
    for cid, size in [(0, 64), (0x00034602, 64), (0x80034600, 64),
                      (0x00034700, 64), (0x000345ff, 64), (0x01034600, 64)]:
        out.append(struct.pack("<II", cid, size) + junk)
    skins = []
    for size in (0, 63, 64, 64 * 3 + 5, 0xffffffc0, 0x80000000, 0x7fffffff):
        skins.append(struct.pack("<II", SKIN_CHUNK, size) + junk)
    return out, skins


# ============================================================ the scenarios


def s_boot(ch):
    car, skin = ch[CAR_CHUNK], ch[SKIN_CHUNK]
    recs = car_records(car)
    return [
        "C",
        "G 0", "G 1", "G 31", "G 63",
        r_line(0, 0, car[:8], recs),
        p_line(1, 0, skin),
        # Skins first, as GLOBALB has them after the cars: neither touches
        # the other's globals.
        "L 1",
        "L 0",
        "U 1",
        "U 0",
        # Made again over the same records: new samples, the same tables.
        "L 0",
        "L 1",
        # The constructor over tables that hold something: every word it
        # owns is its own, the last entry's 0 too.
        "P a5a5a5a5",
        "C",
    ]


def s_align(ch):
    car = ch[CAR_CHUNK]
    recs = car_records(car)
    out = []
    for k, mis in ((2, 4), (3, 8), (4, 12)):
        out += [r_line(k, mis, car[:8], recs), "L %d" % k, "U %d" % k]
    return out


def s_other(ch):
    out = []
    others, skins = other_chunks()
    for i, c in enumerate(others):
        out += [p_line(5, 4 * (i % 4), c), "L 5", "U 5"]
    for i, c in enumerate(skins):
        out += [p_line(6, 4 * (i % 4), c), "L 6", "U 6"]
    return out


def s_made_up(ch):
    car = ch[CAR_CHUNK]
    recs = made_up(car_records(car))
    up, down = fb(0.95), fb(0.95)
    return [
        r_line(7, 0, car[:8], recs),
        "F deadbeef",
        "L 7",
        # First's up point at or below 0 starts in second.
        "S up %08x" % fb(0.0), "F 7f7fffff", "L 7",
        "S up %08x" % fb(-1.0), "L 7",
        "S up %08x" % fb(1.5), "F 00000000", "L 7",
        "S up %08x" % fb(0.25), "L 7",
        "S up %08x" % up,
        "S down %08x" % fb(0.5), "L 7",
        "S down %08x" % down,
        # The dead arm, ShiftUpPoint's: the up points unscaled.
        "S method 0", "F ffffffff", "L 7",
        "S up %08x" % fb(0.0), "L 7",
        "S method 1", "S up %08x" % up,
        "U 7",
    ]


def s_residue(ch):
    car = ch[CAR_CHUNK]
    recs = car_records(car)
    out = [r_line(8, 0, car[:8], recs)]
    for pat in ("00000000", "ffffffff", "7f7fffff", "3f800000", "c3480000",
                "45fa0000", "00800000"):
        out += ["F " + pat, "L 8"]
    return out


def s_make(ch):
    car = ch[CAR_CHUNK]
    recs = made_up(car_records(car))
    out = [r_line(9, 0, car[:8], recs)]
    for rec, n in ((0, 32), (0, 2), (0, 3), (7, 7), (11, 5), (14, 40),
                   (27, 9), (32, 0), (45, -3), (52, 16)):
        out.append("M 9 %d %d" % (rec, n))
    return out


def s_language(ch):
    """InitCarInfo over GLOBALB's records, and every type's row."""
    car = ch[CAR_CHUNK]
    recs = car_records(car)
    out = [r_line(0, 0, car[:8], recs), r_line(4, 12, car[:8], recs),
           "L 0", "I"]
    out += ["Q %d" % t for t in range(-3, 70)]
    out += ["Q %d" % t for t in (0x7fffffff, -0x80000000, 1000)]
    # Again over records loaded at another alignment.
    out += ["L 4", "I", "U 4", "U 0"]
    return out


def script():
    ch = globalb_chunks()
    return [s_boot(ch), s_align(ch), s_other(ch), s_made_up(ch),
            s_residue(ch), s_make(ch), s_language(ch)]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.mallocs = []
        self.shown = [None] * NUM_TYPES
        self.chunks = {}
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(BMALLOC, self.rec_malloc)
        e.put32(DEMO_DISC, 0)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        for k, (c, rec) in self.chunks.items():
            base = CHUNK_BASE + CHUNK_SPAN * k
            if base <= a < base + CHUNK_SPAN:
                return "chunk%d%+d" % (k, a - c)
        return "?"

    def rec_malloc(self, em):
        size = s32(em.reg[4])
        p = em.alloc(max(size, 1), align=16)
        self.mallocs.append((p, size, self.cstr(em.reg[5] & M32),
                             s32(em.reg[6]), s32(em.reg[7])))
        return p

    # ---- the prints ------------------------------------------------------

    def print_mallocs(self):
        e = self.e
        for p, size, name, line, pool in self.mallocs:
            w = [e.u32(p + 4 * j) for j in range(size // 4)]
            n = 0
            for j, x in enumerate(w):
                if x:
                    n = j + 1
            self.emit("m %d %s %d %d %d:%s" % (
                size, name, line, pool, n,
                "".join(" %08x" % x for x in w[:n])))
        self.mallocs = []

    def print_tables(self):
        e = self.e
        for i in range(NUM_TYPES):
            a = TABLES + TABLE_STRIDE * i
            t = a + 128
            ptab = e.u32(t)
            s = "".join(" %08x" % e.u32(a + 4 * j) for j in range(32))
            s += " %s %d %08x %08x %08x" % (
                "own" if ptab == a else self.label(ptab), s32(e.u32(t + 4)),
                e.u32(t + 8), e.u32(t + 12), e.u32(t + 16))
            if s != self.shown[i]:
                self.emit("T %d%s" % (i, s))
                self.shown[i] = s

    def print_globals(self, op, k, ret):
        e = self.e
        self.emit("%s %d -> %d array=%s skins=%s n=%d" % (
            op, k, ret, self.label(e.u32(G_ARRAY)),
            self.label(e.u32(G_SKINS)), s32(e.u32(G_NSKINS))))

    # ---- the ops ---------------------------------------------------------

    def op_chunk(self, t):
        e = self.e
        k, mis, kind, data = int(t[1]), int(t[2]), t[3], bytes.fromhex(t[4])
        c = CHUNK_BASE + CHUNK_SPAN * k + mis
        e.write(c - mis, bytes(CHUNK_SPAN))
        if kind == "r":
            e.write(c, data[:8])
            rec = (c + 23) & ~15
            e.write(rec, data[8:])
        else:
            e.write(c, data)
            rec = None
        self.chunks[k] = (c, rec)

    def op_make(self, k, rec, n):
        e = self.e
        e.put32(MAKE_T, MAKE_ENTRIES)
        e.put32(MAKE_T + 4, n)
        e.put32(MAKE_T + 8, fb(1.0))
        e.put32(MAKE_T + 12, fb(2.0))
        e.put32(MAKE_T + 16, fb(3.0))
        for i in range(64):
            e.put32(MAKE_ENTRIES + 4 * i, fb(7.0))
        e.call(MAKE_TABLE, MAKE_T, self.chunks[k][1] + REC * rec,
               limit=2000000)
        self.print_mallocs()
        ptab = e.u32(MAKE_T)
        self.emit("t %s %d %08x %08x %08x:%s" % (
            "own" if ptab == MAKE_ENTRIES else "other",
            s32(e.u32(MAKE_T + 4)), e.u32(MAKE_T + 8), e.u32(MAKE_T + 12),
            e.u32(MAKE_T + 16),
            "".join(" %08x" % e.u32(MAKE_ENTRIES + 4 * i)
                    for i in range(min(max(n, 0), 64)))))

    def run(self, scenarios):
        e = self.e
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:40])
                t = ln.split()
                op = t[0]
                if op == "K":
                    self.op_chunk(t)
                elif op == "C":
                    e.call(SINIT, limit=200000)
                    self.print_mallocs()
                    self.print_tables()
                elif op in ("L", "U"):
                    k = int(t[1])
                    ret = e.call(LOADER if op == "L" else UNLOADER,
                                 self.chunks[k][0], limit=20000000)
                    self.print_globals(op, k, ret)
                    self.print_mallocs()
                    self.print_tables()
                elif op == "M":
                    self.op_make(int(t[1]), int(t[2]), int(t[3]))
                elif op == "G":
                    k = int(t[1])
                    d = s32(e.call(GET_TABLE, k) - (TABLES + 128))
                    q = int(d / TABLE_STRIDE)
                    self.emit("G %d = %d r%d" % (k, q, d - q * TABLE_STRIDE))
                elif op == "S":
                    e.put32(GLOBALS[t[1]], int(t[2], 16))
                elif op == "F":
                    sp = e.reg[29] & M32
                    e.write(sp - STACK_FILL,
                            bytes.fromhex(t[1]) * (STACK_FILL // 4))
                elif op == "I":
                    e.call(INIT_CAR_INFO, limit=2000000)
                    arr = e.u32(G_ARRAY)
                    for i in range(NUM_TYPES):
                        p = e.u32(arr + REC * i + 1368)
                        self.emit("i %d %d" % (
                            i, s32(p - LANG_TABLE) // LANG_ROW))
                elif op == "Q":
                    k = int(t[1])
                    p = e.call(FIND_LANG, k & M32)
                    self.emit("q %d = %d: %s" % (
                        k, s32(p - LANG_TABLE) // LANG_ROW,
                        " ".join(str(s32(e.u32(p + 4 * j)))
                                 for j in range(7))))
                elif op == "P":
                    w = int(t[1], 16)
                    for i in range(NUM_TYPES):
                        a = TABLES + TABLE_STRIDE * i
                        for j in list(range(32)) + [33, 34, 35, 36]:
                            e.put32(a + 4 * j, w)
                    self.print_tables()
                else:
                    raise SystemExit("bad op %r" % (t,))
        return self.out


# ================================================================ the build


def build_harness(tmp, name="carinfo_test"):
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


def M(name, before, after, rel=CI):
    return (name, rel, before, after)


MUTATIONS = [
    # -- the constants and the allocation
    M("speed-step", "K_SPEED_STEP    1.38888896f", "K_SPEED_STEP    1.38888f"),
    M("speed-max", "K_SPEED_MAX     138.888901f", "K_SPEED_MAX     138.0f"),
    M("rpm-per-rads", "K_RPM_PER_RADS  9.54930401f",
      "K_RPM_PER_RADS  9.55f"),
    M("default-max", "K_DEFAULT_MAX   55.5555573f", "K_DEFAULT_MAX   55.5f"),
    M("default-accel", "K_DEFAULT_ACCEL 4.0f", "K_DEFAULT_ACCEL 4.5f"),
    M("samples-100", "#define MAX_SAMPLES 101", "#define MAX_SAMPLES 100"),
    M("malloc-size", "bMalloc(MAX_SAMPLES * (int)sizeof(float),",
      "bMalloc(MAX_SAMPLES * 2 * (int)sizeof(float),"),
    M("malloc-file", r'"..\\indep\\src\\carinfo.cpp"',
      r'"..\\indep\\src\\carinfo.c"'),
    M("malloc-line", "#define CARINFO_LINE 815", "#define CARINFO_LINE 816"),
    M("malloc-pool", "#define CARINFO_POOL 16", "#define CARINFO_POOL 0"),
    # -- the constructors and the getter
    M("ctor-31-entries", "a->Data, 32, 0.0f, K_DEFAULT_MAX);",
      "a->Data, 31, 0.0f, K_DEFAULT_MAX);"),
    M("ctor-min-1", "a->Data, 32, 0.0f, K_DEFAULT_MAX);",
      "a->Data, 32, 1.0f, K_DEFAULT_MAX);"),
    M("ctor-fill-from-29", "for (i = 30; i >= 0; i--)",
      "for (i = 29; i >= 0; i--)"),
    M("ctor-fill-to-1", "for (i = 30; i >= 0; i--)",
      "for (i = 30; i >= 1; i--)"),
    M("ctor-last-kept", "    a->Data[31] = 0.0f;\n", ""),
    M("ctor-last-four", "    a->Data[31] = 0.0f;",
      "    a->Data[31] = K_DEFAULT_ACCEL;"),
    M("sinit-63", "i < CARINFO_NUM_TYPES; i++)\n        acceleration_table_init",
      "i < CARINFO_NUM_TYPES - 1; i++)\n        acceleration_table_init"),
    M("get-neighbour", "[type].mTable;", "[type ^ 1].mTable;"),
    # -- the drivetrain's numbers
    M("split-flipped", "float split = dt->TorqueSplit;",
      "float split = 1.0f - dt->TorqueSplit;"),
    M("drive-swapped",
      "(1.0f - split) * dt->FinalDrive[0] + split * dt->FinalDrive[1];",
      "(1.0f - split) * dt->FinalDrive[1] + split * dt->FinalDrive[0];"),
    M("drive-front-only",
      "(1.0f - split) * dt->FinalDrive[0] + split * dt->FinalDrive[1];",
      "dt->FinalDrive[0];"),
    M("radius-wheel-1", "(1.0f - split) * ct->Wheels[0].Radius",
      "(1.0f - split) * ct->Wheels[1].Radius"),
    M("radius-wheel-3", "split * ct->Wheels[2].Radius",
      "split * ct->Wheels[3].Radius"),
    M("radius-swapped", "(1.0f - split) * ct->Wheels[0].Radius" + NL
      + "           + split * ct->Wheels[2].Radius;",
      "split * ct->Wheels[0].Radius" + NL
      + "           + (1.0f - split) * ct->Wheels[2].Radius;"),
    M("mass-one", "mass = ct->Body.Mass;", "mass = 1.0f;"),
    M("detune-down", "down, gShiftUpDetune);", "down, gShiftDownDetune);"),
    M("detune-constant", "down, gShiftUpDetune);", "down, 0.95f);"),
    M("torque-8", "TorqueCurveTable, 9, ei->IdleRPM",
      "TorqueCurveTable, 8, ei->IdleRPM"),
    M("torque-to-redline", "9, ei->IdleRPM, ei->MaxRPM);",
      "9, ei->IdleRPM, ei->RedLineRPM);"),
    # -- the walk
    M("speed-from-step", "    speed = 0.0f;" + NL,
      "    speed = K_SPEED_STEP;" + NL),
    M("rpm-from-max", "    rpm = 0.0f;" + NL, "    rpm = ei->MaxRPM;" + NL),
    M("start-in-neutral", "    gear = FIRST_GEAR;" + NL,
      "    gear = FIRST_GEAR - 1;" + NL),
    M("start-below-zero", "if (up[FIRST_GEAR] <= 0.0f) {",
      "if (up[FIRST_GEAR] < 0.0f) {"),
    M("start-always-first", "if (up[FIRST_GEAR] <= 0.0f) {", "if (0) {"),
    M("start-skips-two", "        gear = FIRST_GEAR + 1;" + NL,
      "        gear = FIRST_GEAR + 2;" + NL),
    M("start-check-short", "        if (!(gear < dt->NumGears + 2))" + NL
      + "            goto sampled;",
      "        if (!(gear < dt->NumGears + 1))" + NL
      + "            goto sampled;"),
    M("torque-at-speed", "a = table_get_value(&torque, rpm) * drive;",
      "a = table_get_value(&torque, speed) * drive;"),
    M("ratio-first-gear", "a = a * dt->GearRatios[gear];",
      "a = a * dt->GearRatios[FIRST_GEAR];"),
    M("no-radius", "        a = a / radius;" + NL, ""),
    M("mass-times", "a = a / mass;", "a = a * mass;"),
    M("stop-before-sample",
      "        samples[n++] = a;" + NL + "        if (!(speed < K_SPEED_MAX))"
      + NL + "            break;" + NL,
      "        if (!(speed < K_SPEED_MAX))" + NL + "            break;" + NL
      + "        samples[n++] = a;" + NL),
    M("stop-past-max", "        if (!(speed < K_SPEED_MAX))",
      "        if (!(speed <= K_SPEED_MAX))"),
    M("never-stop", "        if (!(speed < K_SPEED_MAX))" + NL
      + "            break;" + NL + "        rpm", "        rpm"),
    M("rpm-no-drive",
      "rpm = speed / radius * drive * dt->GearRatios[gear] * K_RPM_PER_RADS;",
      "rpm = speed / radius * dt->GearRatios[gear] * K_RPM_PER_RADS;"),
    M("rpm-first-ratio",
      "rpm = speed / radius * drive * dt->GearRatios[gear] * K_RPM_PER_RADS;",
      "rpm = speed / radius * drive * dt->GearRatios[FIRST_GEAR]"
      " * K_RPM_PER_RADS;"),
    M("shift-past", "if (up[gear] <= rpm) {", "if (up[gear] < rpm) {"),
    M("shift-by-down", "if (up[gear] <= rpm) {", "if (down[gear] <= rpm) {"),
    M("shift-two", "            gear++;" + NL, "            gear += 2;" + NL),
    M("top-one-short", "            if (!(gear < dt->NumGears + 2))" + NL
      + "                break;",
      "            if (!(gear < dt->NumGears + 1))" + NL
      + "                break;"),
    # -- the table
    M("last-sample-kept", "    samples[n - 1] = 0.0f;" + NL, ""),
    M("first-sample-zeroed", "    samples[n - 1] = 0.0f;",
      "    samples[0] = 0.0f;"),
    M("accel-one-short", "table_init(&accel, samples, n, 0.0f, speed);",
      "table_init(&accel, samples, n - 1, 0.0f, speed);"),
    M("accel-to-500", "table_init(&accel, samples, n, 0.0f, speed);",
      "table_init(&accel, samples, n, 0.0f, K_SPEED_MAX);"),
    M("range-from-step", "range = speed - 0.0f;",
      "range = speed - K_SPEED_STEP;"),
    M("resample-over-n", "/ (float)(t->NumEntries - 1);",
      "/ (float)(t->NumEntries);"),
    M("resample-from-1", "for (i = 0; i < t->NumEntries; i++) {",
      "for (i = 1; i < t->NumEntries; i++) {"),
    M("range-to-500", "    table_set_min_max(t, 0.0f, speed);",
      "    table_set_min_max(t, 0.0f, K_SPEED_MAX);"),
    M("range-kept", "    table_set_min_max(t, 0.0f, speed);" + NL, ""),
    # -- the loader
    M("id-from-size", "    memcpy(&id, chunk, 4);",
      "    memcpy(&id, chunk + 4, 4);"),
    M("records-plus-16", "(((uintptr_t)chunk + 23) & ~(uintptr_t)15)",
      "(((uintptr_t)chunk + 16) & ~(uintptr_t)15)"),
    M("records-unaligned", "(((uintptr_t)chunk + 23) & ~(uintptr_t)15)",
      "((uintptr_t)chunk + 16)"),
    M("records-mask-7", "(((uintptr_t)chunk + 23) & ~(uintptr_t)15)",
      "(((uintptr_t)chunk + 23) & ~(uintptr_t)7)"),
    M("loader-63", "i < CARINFO_NUM_TYPES; i++)" + NL
      + "            make_acceleration_table",
      "i < CARINFO_NUM_TYPES - 1; i++)" + NL
      + "            make_acceleration_table"),
    M("loader-first-record", "&CarTypeInfoArray[i]);",
      "&CarTypeInfoArray[0]);"),
    M("loader-cars-answer-0", "&CarTypeInfoArray[i]);" + NL
      + "        return 1;", "&CarTypeInfoArray[i]);" + NL
      + "        return 0;"),
    M("skins-past-16", "(SkinInfo *)(void *)(chunk + 8);",
      "(SkinInfo *)(void *)(chunk + 16);"),
    M("skins-over-32", "NumSkinInfo = (int32_t)(size >> 6);",
      "NumSkinInfo = (int32_t)(size >> 5);"),
    M("skins-signed", "NumSkinInfo = (int32_t)(size >> 6);",
      "NumSkinInfo = (int32_t)size >> 6;"),
    M("skins-answer-0", "(int32_t)(size >> 6);" + NL + "        return 1;",
      "(int32_t)(size >> 6);" + NL + "        return 0;"),
    M("skins-any-id",
      "    if (id == CARINFO_SKIN_CHUNK) {" + NL + "        uint32_t size;",
      "    if (id != 0) {" + NL + "        uint32_t size;"),
    M("loader-takes-all", "    return 0;" + NL + "}" + NL + NL
      + "int unloader_car_info", "    return 1;" + NL + "}" + NL + NL
      + "int unloader_car_info"),
    # -- the unloader
    M("unload-keeps-array", "        CarTypeInfoArray = NULL;" + NL, ""),
    M("unload-cars-answer-0", "CarTypeInfoArray = NULL;" + NL
      + "        return 1;", "CarTypeInfoArray = NULL;" + NL
      + "        return 0;"),
    M("unload-resets-tables", "CarTypeInfoArray = NULL;" + NL
      + "        return 1;", "CarTypeInfoArray = NULL;" + NL
      + "        carinfo_static_init();" + NL + "        return 1;"),
    M("unload-keeps-skins", "        SkinInfoTable = NULL;" + NL, ""),
    M("unload-keeps-count", "        NumSkinInfo = 0;" + NL, ""),
    M("unload-skin-id",
      "    if (id == CARINFO_SKIN_CHUNK) {" + NL + "        SkinInfoTable = NULL;",
      "    if (id == CARINFO_SKIN_CHUNK + 1) {" + NL
      + "        SkinInfoTable = NULL;"),
    M("unload-takes-all", "        NumSkinInfo = 0;" + NL + "        return 1;"
      + NL + "    }" + NL + "    return 0;", "        NumSkinInfo = 0;" + NL
      + "        return 1;" + NL + "    }" + NL + "    return 1;"),

    # -- FindCarLanguageInfo and InitCarInfo -------------------------------
    M("find-misses-last-row",
      "    for (i = 0; i < CARINFO_NUM_LANGUAGE_INFO; i++)",
      "    for (i = 0; i < CARINFO_NUM_LANGUAGE_INFO - 1; i++)"),
    M("find-skips-first-row",
      "    for (i = 0; i < CARINFO_NUM_LANGUAGE_INFO; i++)",
      "    for (i = 1; i < CARINFO_NUM_LANGUAGE_INFO; i++)"),
    M("find-falls-back-last",
      "    return &CarLanguageInfoTable[0];",
      "    return &CarLanguageInfoTable[CARINFO_NUM_LANGUAGE_INFO - 1];"),
    M("find-falls-back-null", "    return &CarLanguageInfoTable[0];",
      "    return NULL;"),
    M("find-last-match",
      "            return &CarLanguageInfoTable[i];",
      "            return &CarLanguageInfoTable[i - (i > 0)];"),
    M("table-row-swapped",
      "    {   1,  42002,  43002,  43102,  44002,  41200,  41400 },",
      "    {   1,  42002,  43002,  43102,  44002,  41400,  41200 },"),
    M("table-fallback-row",
      "    {  -1,  42002,  43002,  43102,  44002,  41100,  41300 },",
      "    {  -1,  42003,  43002,  43102,  44002,  41100,  41300 },"),
    M("init-misses-last-type",
      "    for (i = 0; i < CARINFO_NUM_TYPES; i++)" + NL
      + "        ((CarTypeInfo *)",
      "    for (i = 0; i < CARINFO_NUM_TYPES - 1; i++)" + NL
      + "        ((CarTypeInfo *)"),
    M("init-off-by-one", "            find_car_language_info(i);",
      "            find_car_language_info(i + 1);"),
]

EQUIVALENT = {
    # The walk's speeds are the same sums of the step for every car, from
    # 0: the 100th is 138.888733 (0x430ae384) and the 101st 140.277618, so
    # none is the cap, 138.888901, and `<=` stops where `<` does.
    "stop-past-max": "no speed the walk reaches is the cap exactly",
    # The first row is type -1's and also the fallback, so a search that
    # never looks at it still answers it for -1.
    "find-skips-first-row": "row 0 is both -1's and the fallback",
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
    sc = script()
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
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-36s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-36s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
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
    sc = script()
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
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
