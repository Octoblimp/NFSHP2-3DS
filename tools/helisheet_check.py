#!/usr/bin/env python3
"""Cross-check 3DS Files/source/helisheet.c, the helicopter's sheet,
against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: LoaderHeliSheet (0x001ebd20),
UnloaderHeliSheet (0x001ebd80) and HeliSheet::FindZValue (0x001ebad8),
with HeliPoly's PointInPoly (0x001eb6a8) and ZValue (0x001eb840) under
it. Nothing is stubbed. The harness (tools/src/helisheet_test.c) runs
helisheet.c and p32.c and prints the same lines.

**The chunks** are every distinct 0x80034800 container in the card's
TRACKB*.BUN, fifteen of them, each copied to the same offset from a
16-byte boundary on both sides: its own file's, which is where the game
holds it, and for one sheet the other three too, since the polygons start
at the next 16 and the count is the size less that padding.

**Compared** are what the loader and unloader return and leave in
TheHeliSheet and the sheet (its offset in the chunk, the polygons' and
the count); and for each FindZValue, what it returns, the height and the
flag bits it writes (or the sentinel it left), and the three recent
polygons after.

**The script** loads each sheet and asks for the centre of every polygon,
the corners and edge midpoints of some, and points at random over the
sheet and past its ends; runs of points that hit the recent three in each
slot and miss them; NULL height and flag pointers; NaNs; and, on a sheet
it edits, an empty sheet, polygons of no corners and of five, a recent
index below 0, buckets that start past the point and the wrong chunk id.

    python tools/helisheet_check.py
    python tools/helisheet_check.py --mutate [--only a,b]
    python tools/helisheet_check.py --dump out/helisheet
"""
import argparse
import hashlib
import os
import random
import struct
import subprocess
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
SD = Path(os.environ.get("APPDATA", "")) / "Azahar" / "sdmc" / "NFSHP2"

HARNESS = "tools/src/helisheet_test.c"
HELI = "3DS Files/source/helisheet.c"
SOURCES = [HARNESS, HELI, "3DS Files/source/p32.c"]
HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = retail_model.RETAIL_GP
G_SHEET = GP - 17128                    # TheHeliSheet
F_LOAD = 0x001ebd20
F_UNLOAD = 0x001ebd80
F_FIND = 0x001ebad8

CHUNK_ID = 0x80034800
SENTINEL = 0xa5a5a5a5
ROOM = 0x14000                          # the largest chunk is 80308 bytes


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def F(f):
    return "%08x" % fbits(f)


# =============================================================== the chunks

def sheet_chunks():
    """Each distinct sheet container on the card: (track, bytes, the
    file offset's misalignment), the bytes counting the header."""
    out, seen = [], set()
    key = struct.pack("<I", CHUNK_ID)
    for p in sorted((SD / "TRACKS").glob("TRACKB*.BUN")):
        b = p.read_bytes()
        i = b.find(key)
        while i >= 0 and i % 4:
            i = b.find(key, i + 1)
        if i < 0:
            continue
        size = struct.unpack_from("<I", b, i + 4)[0]
        c = b[i:i + 8 + size]
        h = hashlib.sha1(c).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append((p.stem, c, i % 16))
    return out


def polys_of(c, mis):
    """The polygons as the loader finds them at this misalignment: a list
    of (offset in the chunk, corners, count, minx, maxx)."""
    d = 8
    v = d + struct.unpack_from("<I", c, d + 4)[0]
    pad = (-(mis + v + 16)) % 16
    first = v + 16 + pad
    n = (struct.unpack_from("<I", c, v + 12)[0] - pad) >> 6
    out = []
    for k in range(n):
        o = first + 64 * k
        if o + 64 > len(c):
            break
        pts = [struct.unpack_from("<3f", c, o + 16 * j) for j in range(4)]
        np = struct.unpack_from("<b", c, o + 44)[0]
        out.append((o, pts, np, struct.unpack_from("<f", c, o + 12)[0],
                    struct.unpack_from("<f", c, o + 28)[0]))
    return out


# ================================================================ the model

class Model(object):
    def __init__(self):
        self.e = e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.base = e.alloc(ROOM + 64, align=128)
        self.pt = e.alloc(16, align=16)
        self.zf = e.alloc(16, align=16)
        self.chunk = self.base
        self.out = []

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        if self.chunk <= v < self.chunk + ROOM:
            return "C+%d" % (v - self.chunk)
        return "?%08x" % v

    def sheet(self):
        return self.e.u32(G_SHEET)

    def recent(self):
        s = self.sheet()
        return " ".join("%d" % struct.unpack_from("<h", self.e.mem,
                                                  s + 2 + 2 * i)[0]
                        for i in range(3))

    def op(self, a):
        e = self.e
        k = a[0]
        if k == "chunk":
            data = Path(a[1]).read_bytes()
            mis = int(a[2])
            e.write(self.base, bytes(ROOM + 64))
            self.chunk = self.base + mis
            e.write(self.chunk, data)
        elif k == "load":
            r = e.call(F_LOAD, self.chunk)
            s = self.sheet()
            if r and s:
                n = struct.unpack_from("<h", e.mem, s)[0]
                self.emit("load -> %d sheet %s polys %s n %d" % (
                    r, self.sym(s), self.sym(e.u32(s + 8)), n))
            else:
                self.emit("load -> %d sheet %s" % (r, self.sym(s)))
        elif k == "unload":
            r = e.call(F_UNLOAD, self.chunk)
            self.emit("unload -> %d sheet %s" % (r, self.sym(self.sheet())))
        elif k == "id":
            e.put32(self.chunk, int(a[1], 16))
        elif k == "p16":
            struct.pack_into("<h", e.mem, self.chunk + int(a[1]), int(a[2]))
        elif k == "p8":
            e.mem[self.chunk + int(a[1])] = int(a[2]) & 0xff
        elif k == "p32":
            e.put32(self.chunk + int(a[1]), int(a[2], 16))
        elif k == "find":
            e.put32(self.pt, int(a[1], 16))
            e.put32(self.pt + 4, int(a[2], 16))
            e.put32(self.zf, SENTINEL)
            e.put32(self.zf + 4, SENTINEL)
            r = e.call(F_FIND, self.sheet(), self.pt,
                       self.zf if a[3] == "1" else 0,
                       self.zf + 4 if a[4] == "1" else 0)
            self.emit("find %s %s -> %d z %08x f %08x recent %s" % (
                a[1], a[2], r, e.u32(self.zf), e.u32(self.zf + 4),
                self.recent()))
        else:
            raise ValueError("bad op %r" % a)

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    m = Model()
    out = m.run(lines)
    if m.e.eediv_pcs or m.e.eesqrt_pcs:
        print("note: the EE's divide at %s, its root at %s" % (
            " ".join("%08x" % p for p in sorted(m.e.eediv_pcs)),
            " ".join("%08x" % p for p in sorted(m.e.eesqrt_pcs))))
    return out


# ================================================================== script

NAN = float("nan")


def find(x, y, z=1, f=1):
    return "find|%s|%s|%d|%d" % (F(x), F(y), z, f)


def find_bits(xb, yb, z=1, f=1):
    return "find|%08x|%08x|%d|%d" % (xb, yb, z, f)


def centre(pts, n):
    k = 3 if n == 3 else 4
    return (sum(p[0] for p in pts[:k]) / k, sum(p[1] for p in pts[:k]) / k)


def sheet_points(c, mis, rng):
    out = []
    ps = polys_of(c, mis)
    for i, (o, pts, n, mn, mx) in enumerate(ps):
        out.append(find(*centre(pts, n)))
        if i % 9 == 0:
            k = 3 if n == 3 else 4
            for j in range(k):
                a, b = pts[j], pts[(j + 1) % k]
                out.append(find(a[0], a[1]))
                out.append(find((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            if n == 4:
                # on the diagonal from the third corner to the first
                out.append(find((pts[0][0] + pts[2][0]) / 2,
                                (pts[0][1] + pts[2][1]) / 2))
    xs = [p[3] for p in ps] + [p[4] for p in ps]
    ys = [q[1] for p in ps for q in p[1][:4]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    wx, wy = x1 - x0, y1 - y0
    for _ in range(160):
        out.append(find(rng.uniform(x0 - 0.05 * wx, x1 + 0.05 * wx),
                        rng.uniform(y0 - 0.05 * wy, y1 + 0.05 * wy)))
    out.append(find(x0, (y0 + y1) / 2))
    out.append(find(x1, (y0 + y1) / 2))
    out.append(find(x0 - 1000.0, y0))
    out.append(find(x1 + 1000.0, y1))
    return out, ps


def recents(ps):
    """Runs that hit the recent three in each slot, and miss them."""
    out = []
    pick = [centre(p[1], p[2]) for p in ps[::max(1, len(ps) // 5)]][:5]
    a, b, c, d = pick[0], pick[1], pick[2], pick[3]
    for seq in ((a, a, a), (a, b, a), (a, b, c, a), (a, b, c, b),
                (a, b, c, c), (a, b, c, d, a), (d, c, b, a, d, c, b, a)):
        out += [find(*p) for p in seq]
    out.append(find(a[0], a[1], 0, 1))
    out.append(find(b[0], b[1], 1, 0))
    out.append(find(c[0], c[1], 0, 0))
    out.append(find(1e9, 1e9, 0, 0))
    out.append(find(NAN, a[1]))
    out.append(find(a[0], NAN))
    out.append(find(NAN, NAN))
    out.append(find_bits(0x7f800000, 0))
    out.append(find_bits(0xff800000, 0))
    return out


def edits(c, mis):
    """A sheet edited for the cases the files never hold."""
    ps = polys_of(c, mis)
    hdr = 16                            # the sheet, in the chunk
    o0, pts0, n0, _mn, _mx = ps[0]
    o5 = ps[5][0]
    a = centre(pts0, n0)
    b = centre(ps[5][1], ps[5][2])
    out = ["chunk|%s|%d" % ("@", mis), "load"]
    # a recent index below 0, and past the end
    out += ["p16|%d|-1" % (hdr + 2), "p16|%d|0" % (hdr + 4),
            "p16|%d|%d" % (hdr + 6, len(ps) - 1), find(*a), find(*b)]
    # no corners: in range is in
    out += ["p8|%d|0" % (o5 + 44), find(*b), find(b[0], b[1] + 1e5)]
    # five corners, the fifth the next polygon's first
    out += ["p8|%d|5" % (o5 + 44), find(*b), find(b[0] + 0.01, b[1])]
    # three corners on a quad
    out += ["p8|%d|3" % (o5 + 44), find(*b)]
    # a negative count
    out += ["p8|%d|-2" % (o5 + 44), find(*b)]
    out += ["p8|%d|4" % (o5 + 44)]
    # the bucket under the point starting past it, then before the sheet
    for bk in range(0, 256, 17):
        out.append("p16|%d|%d" % (hdr + 24 + 2 * bk, len(ps) - 1))
    out += [find(*a), find(*b)]
    for bk in range(256):
        out.append("p16|%d|%d" % (hdr + 24 + 2 * bk, 0))
    out += [find(*a), find(*b), find(ps[-1][1][0][0], ps[-1][1][0][1])]
    # no width to look back by
    out += ["p32|%d|%08x" % (hdr + 20, fbits(0.0)), find(*b)]
    # an empty sheet: nothing found, nothing written
    out += ["p16|%d|0" % hdr, find(*a), find(*b)]
    # the wrong id loads and unloads nothing; the right one forgets it
    out += ["id|00034800", "load", "unload", "id|%08x" % CHUNK_ID,
            "unload", "load", "unload"]
    return out


def bounds(c, mis):
    """The search's edges, each on a sheet edited so that only that edge
    tells the answer."""
    ps = polys_of(c, mis)
    n = len(ps)
    hdr = 16
    smin = struct.unpack_from("<f", c, hdr + 12)[0]
    far = n // 2

    def buckets(v):
        return ["p16|%d|%d" % (hdr + 24 + 2 * bk, v) for bk in range(256)]

    def recent(r):
        return ["p16|%d|%d" % (hdr + 2 + 2 * i, r) for i in range(3)]

    def width(w):
        return ["p32|%d|%08x" % (hdr + 20, fbits(w))]

    out = []
    # The last bucket, not the one before: every x past a sheet one wide,
    # bucket 254 past the end and 255 the first, and no width to look back.
    out += ["chunk|@|%d" % mis, "load",
            "p32|%d|%08x" % (hdr + 16, fbits(smin + 1.0))]
    out += buckets(n)[:255] + ["p16|%d|0" % (hdr + 24 + 2 * 255)]
    out += width(0.0) + recent(far)
    for p in ps[1::max(1, n // 7)]:
        out.append(find(*centre(p[1], p[2])))
    out.append("unload")
    # A polygon's least x is in the forward run: its least corner, with
    # the run starting at it and nothing behind.
    out += ["chunk|@|%d" % mis, "load"] + width(0.0)
    for k in range(3, n, max(1, n // 9)):
        o, pts, np_, mn, mx = ps[k]
        least = [q for q in pts[:3 if np_ == 3 else 4]
                 if fbits(q[0]) == fbits(mn)]
        if not least:
            continue
        out += buckets(k) + recent(0 if k > n // 2 else n - 1)
        out.append(find(*least[0][:2]))
    out.append("unload")
    # A polygon x - MaxWidth reaches exactly is in the backward run: the
    # run starts past it, and the width is cut to the point's distance.
    out += ["chunk|@|%d" % mis, "load"]
    for k in range(5, n - 1, max(1, n // 9)):
        o, pts, np_, mn, mx = ps[k]
        cx, cy = centre(pts, np_)
        x = bitsf(fbits(cx))
        w = bitsf(fbits(x - mn))
        if bitsf(fbits(x - w)) != mn:
            continue
        out += buckets(k + 1) + width(w) + recent(0 if k > n // 2 else n - 1)
        out.append(find(x, cy))
    out.append("unload")
    # The backward run starts before the forward run's start: with every
    # bucket past the end, a polygon there that holds every x is not
    # looked at.
    end = ps[-1][0] + 64
    assert end + 64 <= ROOM - 16
    out += ["chunk|@|%d" % mis, "load"] + buckets(n) + recent(0)
    out += ["p32|%d|%08x" % (end + 12, 0xff800000),
            "p32|%d|%08x" % (end + 28, 0x7f800000),
            "p8|%d|0" % (end + 44), "p8|%d|90" % (end + 45)]
    cx, cy = centre(ps[far][1], ps[far][2])
    out += [find(cx, 1e9, 0, 1), find(cx, -1e9, 0, 1),
            find(*centre(ps[far][1], ps[far][2]))]
    out.append("unload")
    return out


def script(chunks, files):
    rng = random.Random(0x4e11)
    out = []
    for (track, c, mis), path in zip(chunks, files):
        out += ["chunk|%s|%d" % (path, mis), "load"]
        pts, ps = sheet_points(c, mis, rng)
        out += pts
        out += recents(ps)
        out.append("unload")
    track, c, mis = chunks[0]
    for m in range(16):
        if m % 4 == 0 and m != mis:
            out += ["chunk|%s|%d" % (files[0], m), "load"]
            ps = polys_of(c, m)
            out += [find(*centre(p[1], p[2])) for p in ps[::23]]
            out.append("unload")
    out += [x.replace("@", files[0]) for x in edits(c, mis)]
    for (track, c, mis), path in list(zip(chunks, files))[:3]:
        out += [x.replace("@", path) for x in bounds(c, mis)]
    return out


# ================================================================= running

def build_harness(tmp, name="helisheet_test"):
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


def write_inputs(d):
    chunks = sheet_chunks()
    if not chunks:
        sys.exit("no TRACKB*.BUN on the card at %s" % SD)
    files = []
    for i, (track, c, mis) in enumerate(chunks):
        p = Path(d) / ("%s.bin" % track)
        p.write_bytes(c)
        files.append(str(p))
    lines = script(chunks, files)
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

H = HELI
MUTATIONS = [
    # ---- PointInPoly
    ("pip_minx_le", H, "if (x < p->MinX || p->MaxX < x)",
     "if (x <= p->MinX || p->MaxX < x)"),
    ("pip_maxx_le", H, "if (x < p->MinX || p->MaxX < x)",
     "if (x < p->MinX || p->MaxX <= x)"),
    ("pip_no_range", H, "if (x < p->MinX || p->MaxX < x)", "if (0)"),
    ("pip_ge0", H, "* dy > 0.0f)", "* dy >= 0.0f)"),
    ("pip_sign", H, "* dy > 0.0f)", "* dy < 0.0f)"),
    ("pip_edge_swap", H, "(b[1] - a[1]) * dx - (b[0] - a[0]) * dy",
     "(b[0] - a[0]) * dx - (b[1] - a[1]) * dy"),
    ("pip_wrap", H, "corner(p, (i + 1) % n)", "corner(p, i + 1)"),
    ("pip_empty_out", H, "    }\n    return 1;\n}\n\n// HeliPoly::ZValue",
     "    }\n    return n > 0;\n}\n\n// HeliPoly::ZValue"),
    ("pip_count_u8", H, "    n = p->NumPoints;\n",
     "    n = (uint8_t)p->NumPoints;\n"),
    # ---- ZValue
    ("zv_tri_4", H, "if (p->NumPoints == 3) {", "if (p->NumPoints != 4) {"),
    ("zv_side_lt", H, "if (side <= 0.0f) {", "if (side < 0.0f) {"),
    ("zv_side_flip", H, "if (side <= 0.0f) {", "if (side > 0.0f) {"),
    ("zv_diag", H, "(p->P0[1] - p->P2[1]) * (x - p->P2[0])",
     "(p->P0[1] - p->P2[1]) * (x - p->P0[0])"),
    ("zv_half_p1", H, "            b = p->P3;\n", "            b = p->P1;\n"),
    ("zv_half_a", H, "            a = p->P2;\n            b = p->P3;\n"
     "            c = p->P0;\n",
     "            a = p->P0;\n            b = p->P3;\n"
     "            c = p->P2;\n"),
    ("zv_cross_x", H, "n[0] = e1[1] * e2[2] - e2[1] * e1[2];",
     "n[0] = e2[1] * e1[2] - e1[1] * e2[2];"),
    ("zv_cross_z", H, "n[2] = e1[0] * e2[1] - e2[0] * e1[1];",
     "n[2] = e1[0] * e2[1] + e2[0] * e1[1];"),
    ("zv_len_order", H,
     "q = 1.0f / sqrtf((n[0] * n[0] + n[1] * n[1]) + n[2] * n[2]);",
     "q = 1.0f / sqrtf(n[0] * n[0] + (n[1] * n[1] + n[2] * n[2]));"),
    ("zv_no_norm", H, "    n[0] *= q;\n    n[1] *= q;\n    n[2] *= q;\n",
     ""),
    ("zv_plane_a", H,
     "d = (p->P0[0] * n[0] + p->P0[1] * n[1]) + p->P0[2] * n[2];",
     "d = (a[0] * n[0] + a[1] * n[1]) + a[2] * n[2];"),
    ("zv_d_order", H,
     "d = (p->P0[0] * n[0] + p->P0[1] * n[1]) + p->P0[2] * n[2];",
     "d = p->P0[0] * n[0] + (p->P0[1] * n[1] + p->P0[2] * n[2]);"),
    ("zv_out_order", H, "return (d - (n[0] * x + n[1] * y)) / n[2];",
     "return ((d - n[0] * x) - n[1] * y) / n[2];"),
    # ---- FindZValue
    ("fz_empty", H, "    if (s->NumPolys == 0)\n        return 0;\n", ""),
    ("fz_recent_2", H, "for (i = 0; i < 3; i++) {\n        int32_t k = s",
     "for (i = 0; i < 2; i++) {\n        int32_t k = s"),
    ("fz_no_recent", H, "        if (helipoly_point_in_poly(&poly[k], pt)) {"
     "\n            found = k;\n            slot = i;",
     "        if (0) {\n            found = k;\n            slot = i;"),
    ("fz_bucket_255", H, "        if (b > 255)\n            b = 255;\n",
     "        if (b > 254)\n            b = 254;\n"),
    ("fz_bucket_no_lo", H, "        if (b < 0)\n            b = 0;\n", ""),
    ("fz_bucket_scale", H, "* 256.0f);", "* 255.0f);"),
    ("fz_bucket_round", H,
     "b = ee_trunc_w((x - s->MinX) / (s->MaxX - s->MinX) * 256.0f);",
     "b = ee_trunc_w((x - s->MinX) / (s->MaxX - s->MinX) * 256.0f + 0.5f);"),
    ("fz_fwd_lt", H, "poly[k].MinX <= x; k++)", "poly[k].MinX < x; k++)"),
    ("fz_fwd_all", H, "k < s->NumPolys && poly[k].MinX <= x; k++)",
     "k < s->NumPolys; k++)"),
    ("fz_back_from", H, "for (k = start - 1; k >= 0", "for (k = start; k >= 0"),
    ("fz_back_lt", H, "x - s->MaxWidth <= poly[k].MinX;",
     "x - s->MaxWidth < poly[k].MinX;"),
    ("fz_back_none", H, "k >= 0 && x - s->MaxWidth <= poly[k].MinX;",
     "k >= 0 && 0;"),
    ("fz_back_gt0", H, "for (k = start - 1; k >= 0 &&",
     "for (k = start - 1; k > 0 &&"),
    ("fz_no_z", H, "    if (z != NULL)\n        *z = ",
     "    if (z != NULL && 0)\n        *z = "),
    ("fz_no_flags", H, "        *flags = poly[found].Flags;",
     "        *flags = 0;"),
    ("fz_slot_miss", H, "    if (slot < 0)\n        slot = 2;\n",
     "    if (slot < 0)\n        slot = 3;\n"),
    ("fz_mtf_up", H, "for (i = slot - 1; i >= 0; i--)",
     "for (i = 0; i < slot; i++)"),
    ("fz_no_front", H, "    s->Recent[0] = (int16_t)found;\n", ""),
    # ---- the loader
    ("ld_id", H, "    if (bchunk_u32(chunk) != HELISHEET_CHUNK_ID)\n"
     "        return 0;\n    d = chunk + 8;",
     "    if (0)\n        return 0;\n    d = chunk + 8;"),
    ("ld_sheet_at", H, "s = (HeliSheet *)(void *)(d + 8);",
     "s = (HeliSheet *)(void *)(d + 16);"),
    ("ld_no_set", H, "    TheHeliSheet = s;\n", ""),
    ("ld_v", H, "v = d + bchunk_u32(d + 4);", "v = d + 8 + bchunk_u32(d + 4);"),
    ("ld_align", H, "((uintptr_t)v + 31) & ~(uintptr_t)15",
     "((uintptr_t)v + 16) & ~(uintptr_t)15"),
    ("ld_no_pad", H, "    size -= (uint32_t)(p - (v + 16));\n", ""),
    ("ld_size_at", H, "size = bchunk_u32(v + 12);", "size = bchunk_u32(v + 8);"),
    ("ld_shift", H, "(int16_t)(size >> 6)", "(int16_t)(size >> 5)"),
    ("ul_id", H, "    if (bchunk_u32(chunk) != HELISHEET_CHUNK_ID)\n"
     "        return 0;\n    TheHeliSheet = NULL;",
     "    TheHeliSheet = NULL;"),
    ("ul_keep", H, "    TheHeliSheet = NULL;\n    return 1;",
     "    return 1;"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "helisheet_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
