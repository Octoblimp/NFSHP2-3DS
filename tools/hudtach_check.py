#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudtach.c, the tach's red band, against the
retail image, SLES_507.31.

**The model** is retail's own: InitializeFlailerTachometer (0x001434a0)
with next_power_of_2 (0x0013ff60) under it, and RenderFlailerTachometer
(0x00143858). The harness (tools/src/hudtach_test.c) runs hudtach.c over
epoly.c.

**The stubs** are GetTextureInfo (0x001abf48), which Init asks for the
texture's size, and FlailerStrip::AddPoly (0x00145868), which Render asks
for each poly. AddPoly hands out blocks that retail's ePoly constructor
(0x0010f968) has filled, over a pattern; the harness's are epoly_init's.
Both log their calls, and the model checks that AddPoly is given the
bitmap's strip and TextureInfo. GetTextureInfo's answer goes in the
bitmap at 84 on the PS2, and the port keeps none, so the model clears the
word after each Init.

**Compared**, after each op, are both point lists, the bitmap's 144 bytes
-- the word at 108 as the list it names -- and every poly AddPoly handed
out, all 160 bytes.

**The script** takes both of INGAMEB's gradients as the disc has them and
turns each through every whole degree and on round past both ends, out to
INT_MIN. Past the 27 polys the table's zeros reach, the stub stops retail
and the harness's AddPoly answers NULL; then every texture size
next_power_of_2 and the unsigned conversions treat apart, odd and
negative widths after the scale, scales that saturate or are NaN, each
layer, each corner's colour, both lists, a list the bitmap does not name,
and none.

    python tools/hudtach_check.py
    python tools/hudtach_check.py --mutate [--only a,b]
    python tools/hudtach_check.py --dump out/hudtach
"""
import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flailer_check as fc              # noqa: E402
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudtach_test.c"
HUDTACH = "3DS Files/source/hudtach.c"
SOURCES = [HARNESS, HUDTACH, "3DS Files/source/epoly.c"]

F_INIT = 0x001434a0
F_RENDER = 0x00143858
F_CTOR = 0x0010f968
S_TEXINFO = 0x001abf48                  # GetTextureInfo(hash, 1, 0)
S_ADDPOLY = 0x00145868                  # FlailerStrip::AddPoly

BMP_SIZE = 144
LIST_SIZE = 180
POLY_SIZE = 160
# As many polys as the table's rows reach before its zeros end: a Render
# that wants more is cut off on both sides where AddPoly runs out.
POOL = 27

OUTSIDE = 0x39c9eead                    # HANO_RED, the chase view's
BUMPER = 0x7307c47f                     # TACHGRADIENT, the bumper view's


def F(v):
    return "%#x" % struct.unpack("<I", struct.pack("<f", v))[0]


def pattern(o):
    """The word a fresh block holds at offset o, as the harness's."""
    return (0x3f800000 + o * 16) & M32


def pool_pattern(k, o):
    return (k * 37 + o * 13 + 0x5a) & 0xff


class PoolFull(Exception):
    pass


# ================================================================== script

def disc_bitmap(name):
    """The 144 bytes of INGAMEB's bitmap `name`, as the disc has them."""
    d = (fc.SD / "GLOBAL" / "INGAMEB.BUN").read_bytes()
    key = struct.pack("<I", name)
    at = d.find(key)
    while at >= 0:
        o = at - 8
        if (o >= 0 and d[o + 40] == 2
                and struct.unpack_from("<i", d, o + 68)[0] == 10):
            return d[o:o + BMP_SIZE]
        at = d.find(key, at + 1)
    raise SystemExit("no bitmap %08x in INGAMEB" % name)


def set_bitmap(raw):
    s = []
    for o in range(0, BMP_SIZE, 4):
        w = struct.unpack_from("<I", raw, o)[0]
        if o in (84, 108):
            w = 0
        s.append("b|%d|%#x" % (o, w))
    return s


def turn(rots):
    s = []
    for r in rots:
        s += ["b|64|%#x" % (r & M32), "draw"]
    return s


# Each quarter's ends and the halves' edges, and past both ends.
EDGES = [0, 1, 2, 44, 45, 46, 47, 89, 90, 91, 134, 135, 136, 179, 180, 181,
         193, 224, 225, 226, 269, 270, 271, 314, 315, 316, 359, 360, 361,
         404, 405, 406, 449, 450, 451, 720, 1000, -1, -44, -45, -46, -90,
         -91, -360, -1000, -1800, -1889, -1980, 0x7fffffff,
         -0x80000000, -0x7fffff00]


def scenario_disc(name, w, h):
    s = set_bitmap(disc_bitmap(name))
    s += ["tex|%d|%d" % (w, h), "init|0"]
    s += turn(range(0, 361))
    s += turn(EDGES)
    return s


def scenario_sizes():
    s = ["b|48|%s" % F(510.0), "b|52|%s" % F(334.0), "b|56|%s" % F(1.0),
         "b|60|%s" % F(1.0), "byte|42|1"]
    for w, h in ((112, 112), (104, 40), (0, 0), (1, 1), (2, 2), (3, 3),
                 (4, 5), (7, 9), (64, 65), (127, 129), (255, 256),
                 (511, 513), (1024, 1023), (32767, 32767), (-1, -1),
                 (-32768, 1), (1, -32768), (-2, 3), (0, 17), (17, 0)):
        s += ["tex|%d|%d" % (w & 0xffff, h & 0xffff), "init|0"]
        s += turn([0, 30, 100, 193, 300, 360])
    return s


def scenario_scales():
    s = ["tex|112|112"]
    for sx, sy in ((1.0, 1.0), (0.5, 0.5), (2.0, 0.75), (1.37, 0.61),
                   (-1.0, -1.0), (-0.51, 1.0), (0.0, 0.0), (0.01, 3.0),
                   (1e10, 1.0), (1.0, -1e10), (float("nan"), 1.0),
                   (float("inf"), float("-inf")), (1.0, 1.0)):
        s += ["b|56|%s" % F(sx), "b|60|%s" % F(sy), "init|0"]
        s += turn([10, 120, 200])
    # Odd sizes after the scale, both signs.
    for w in (113, 111, 1, 3):
        s += ["tex|%d|%d" % (w, w), "b|56|%s" % F(-1.0), "b|60|%s" % F(1.0),
              "init|0", "b|56|%s" % F(1.0), "b|60|%s" % F(-1.0), "init|0"]
        s += turn([200])
    s += ["b|56|%s" % F(1.0), "b|60|%s" % F(1.0), "tex|112|112"]
    return s


def scenario_place():
    s = []
    for x, y in ((0.0, 0.0), (-17.75, 320.25), (1e6, -1e6), (639.5, 447.5),
                 (510.0, 334.0)):
        s += ["b|48|%s" % F(x), "b|52|%s" % F(y), "init|0"]
        s += turn([45, 200])
    for z in (0, 2, 28, 127, 0x80, 0xff, 1):
        s += ["byte|42|%d" % z, "init|0"]
        s += turn([150, 300])
    # Each corner's colour, and the poly the cut makes keeps 0x80s.
    s += ["b|88|0x11223344", "b|92|0x55667788", "b|96|0x99aabbcc",
          "b|100|0xddeeff00"]
    s += turn([0, 100, 200, 300])
    s += ["b|88|0x80808080", "b|92|0x80808080", "b|96|0x80808080",
          "b|100|0x80808080"]
    # The strip and TextureInfo words AddPoly is given.
    s += ["b|44|0x1234", "draw", "b|44|0"]
    return s


def scenario_lists():
    s = ["init|1"]
    s += turn([0, 200])
    # Render on a list the bitmap does not name, and on none.
    s += ["b|64|200", "render|0", "render|1", "render|-"]
    s += ["init|0", "draw", "init|1", "init|1", "draw"]
    # No list at all: nothing drawn, whatever the angle.
    s += ["b|108|0"]
    s += turn([0, 100, 200, 300])
    s += ["init|0", "draw"]
    return s


def script():
    s = []
    s += scenario_disc(OUTSIDE, 112, 112)
    s += scenario_disc(BUMPER, 104, 40)
    s += scenario_sizes()
    s += scenario_scales()
    s += scenario_place()
    s += scenario_lists()
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e.stub_bware()
        self.bmp = e.alloc(BMP_SIZE, align=16)
        for o in range(0, BMP_SIZE, 4):
            e.put32(self.bmp + o, pattern(o))
        e.put32(self.bmp + 84, 0)
        e.put32(self.bmp + 108, 0)
        self.lists = [e.alloc(LIST_SIZE, align=16) for _ in range(2)]
        for k, l in enumerate(self.lists):
            for o in range(0, LIST_SIZE, 4):
                e.put32(l + o, pattern(o + 256 * k))
        self.pool = [e.alloc(POLY_SIZE, align=16) for _ in range(POOL)]
        for k in range(POOL):
            self.fresh(k)
        self.texinfo = e.alloc(64, align=16)
        e.write(self.texinfo, bytes(64))
        self.handed = 0
        self.used = 0
        self.last = {}
        e.stub(S_TEXINFO, self.s_texinfo)
        e.stub(S_ADDPOLY, self.s_addpoly)

    def emit(self, s):
        self.out.append(s)

    def fresh(self, k):
        e = self.e
        a = self.pool[k]
        e.write(a, bytes(pool_pattern(k, o) for o in range(156)))
        e.put32(a + 156, 0x5a5a5a5a)
        e.call(F_CTOR, a, limit=10000)

    # ---- stubs

    def s_texinfo(self, em):
        h, kind, flags = (em.reg[i] & M32 for i in (4, 5, 6))
        if kind != 1 or flags != 0:
            raise SystemExit("GetTextureInfo(%08x, %d, %d)" % (h, kind, flags))
        self.emit("  texinfo %08x" % h)
        self.e.write(self.texinfo + 36, struct.pack("<HH", self.texw,
                                                    self.texh))
        return self.texinfo

    def s_addpoly(self, em):
        e = self.e
        strip, tex = em.reg[4] & M32, em.reg[5] & M32
        if strip != e.u32(self.bmp + 44) or tex != e.u32(self.bmp + 84):
            raise SystemExit("AddPoly(%08x, %08x)" % (strip, tex))
        k = self.handed
        if k >= POOL:
            self.emit("  addpoly full")
            raise PoolFull()
        self.emit("  addpoly %d" % k)
        self.handed += 1
        return self.pool[k]

    # ---- output

    def note(self, key, text):
        if self.last.get(key) != text:
            self.last[key] = text
            self.emit("  %s %s" % (key, text))

    def dump(self):
        e = self.e
        mem = e.mem
        for k, l in enumerate(self.lists):
            self.note("list%d" % k, bytes(mem[l:l + LIST_SIZE]).hex())
        raw = bytearray(mem[self.bmp:self.bmp + BMP_SIZE])
        w = struct.unpack_from("<I", raw, 108)[0]
        raw[108:112] = bytes(4)
        name = ("none" if w == 0 else "L0" if w == self.lists[0]
                else "L1" if w == self.lists[1] else "%08x" % w)
        self.note("bmp", raw.hex() + " list " + name)
        for k in range(self.handed):
            a = self.pool[k]
            self.emit("  poly %d %s %08x" % (k, bytes(mem[a:a + 156]).hex(),
                                             e.u32(a + 156)))

    # ---- ops

    def render(self, lst):
        # Only the polys a Render has handed out need building again.
        for k in range(self.used):
            self.fresh(k)
        self.handed = 0
        try:
            self.e.call(F_RENDER, self.bmp, lst, limit=2000000)
        except PoolFull:
            pass
        self.used = self.handed

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        self.handed = 0
        if o == "b":
            e.put32(self.bmp + v(1), v(2))
        elif o == "byte":
            e.mem[self.bmp + v(1)] = v(2) & 0xff
        elif o == "tex":
            self.texw, self.texh = v(1) & 0xffff, v(2) & 0xffff
        elif o == "init":
            e.call(F_INIT, 0, self.bmp, self.lists[v(1)], limit=100000)
            # The port keeps no TextureInfo.
            e.put32(self.bmp + 84, 0)
        elif o in ("render", "draw"):
            if o == "draw":
                lst = e.u32(self.bmp + 108)
            else:
                lst = 0 if a[1] == "-" else self.lists[v(1)]
            self.render(lst)
        else:
            raise ValueError(o)
        self.dump()

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudtach_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDTACH


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # next_power_of_2.
    M("pow2-zero-kept", "    if (n == 0) return 0;\n", ""),
    M("pow2-from-1", "    uint32_t v = 2;", "    uint32_t v = 1;"),
    M("pow2-no-minus", "    for (n = (n - 1) >> 1; n != 0; n >>= 1)", "    for (n = n >> 1; n != 0; n >>= 1)"),
    M("pow2-no-halve", "    for (n = (n - 1) >> 1; n != 0; n >>= 1)", "    for (n = n - 1; n != 0; n >>= 1)"),

    # Init.
    M("init-pw-of-h", "    pw = next_power_of_2((uint32_t)w);", "    pw = next_power_of_2((uint32_t)h);"),
    M("init-ph-of-w", "    ph = next_power_of_2((uint32_t)h);", "    ph = next_power_of_2((uint32_t)w);"),
    M("init-sw-signed", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX);", "    sw = ee_trunc_w((float)w * o->ScaleX);"),
    M("init-sh-signed", "    sh = ee_trunc_w((float)(uint32_t)h * o->ScaleY);", "    sh = ee_trunc_w((float)h * o->ScaleY);"),
    M("init-sw-scale-y", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX);", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleY);"),
    M("init-sh-scale-x", "    sh = ee_trunc_w((float)(uint32_t)h * o->ScaleY);", "    sh = ee_trunc_w((float)(uint32_t)h * o->ScaleX);"),
    M("init-sw-c-cast", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX);", "    sw = (int32_t)((float)(uint32_t)w * o->ScaleX);"),
    M("init-sw-rounded", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX);", "    sw = ee_trunc_w((float)(uint32_t)w * o->ScaleX + 0.5f);"),
    M("init-umax-plain-div", "    umax = ee_div((float)(uint32_t)w, (float)pw);", "    umax = (float)(uint32_t)w / (float)pw;"),
    M("init-umax-signed", "    umax = ee_div((float)(uint32_t)w, (float)pw);", "    umax = ee_div((float)w, (float)pw);"),
    M("init-vmax-of-w", "    vmax = ee_div((float)(uint32_t)h, (float)ph);", "    vmax = ee_div((float)(uint32_t)w, (float)ph);"),
    M("init-vmax-over-pw", "    vmax = ee_div((float)(uint32_t)h, (float)ph);", "    vmax = ee_div((float)(uint32_t)h, (float)pw);"),
    M("init-cx-shift", "    cx     = o->X + (float)(sw / 2);", "    cx     = o->X + (float)(sw >> 1);"),
    M("init-cy-shift", "    cy     = o->Y + (float)(sh / 2);", "    cy     = o->Y + (float)(sh >> 1);"),
    M("init-cx-float-half", "    cx     = o->X + (float)(sw / 2);", "    cx     = o->X + (float)sw * 0.5f;"),
    M("init-cx-of-sh", "    cx     = o->X + (float)(sw / 2);", "    cx     = o->X + (float)(sh / 2);"),
    M("init-cy-from-x", "    cy     = o->Y + (float)(sh / 2);", "    cy     = o->X + (float)(sh / 2);"),
    M("init-right-of-sh", "    right  = o->X + (float)sw;", "    right  = o->X + (float)sh;"),
    M("init-bottom-of-sw", "    bottom = o->Y + (float)sh;", "    bottom = o->Y + (float)sw;"),
    M("init-uhalf-quarter", "    uhalf  = 0.0f + umax * 0.5f;", "    uhalf  = 0.0f + umax * 0.25f;"),
    M("init-vhalf-of-u", "    vhalf  = 0.0f + vmax * 0.5f;", "    vhalf  = 0.0f + umax * 0.5f;"),
    M("init-uhalf-no-zero-add", "    uhalf  = 0.0f + umax * 0.5f;", "    uhalf  = umax * 0.5f;"),
    M("init-z-unsigned", "    z      = (float)o->Z;", "    z      = (float)(uint8_t)o->Z;"),
    M("init-z-zero", "    z      = (float)o->Z;", "    z      = 0.0f;"),
    M("init-no-token", "    b->pTachPointList = token_of(l);\n", ""),
    M("init-p0-v", "cy,     z, uhalf, vhalf);", "cy,     z, uhalf, vmax);"),
    M("init-p1-x", "    set_point(&l->Points[1], cx,    bottom,", "    set_point(&l->Points[1], o->X,  bottom,"),
    M("init-p1-v", "    set_point(&l->Points[1], cx,    bottom, z, uhalf, vmax);", "    set_point(&l->Points[1], cx,    bottom, z, uhalf, vhalf);"),
    M("init-p2-u", "    set_point(&l->Points[2], o->X,  bottom, z, 0.0f,  vmax);", "    set_point(&l->Points[2], o->X,  bottom, z, umax,  vmax);"),
    M("init-p3-y", "    set_point(&l->Points[3], o->X,  cy,", "    set_point(&l->Points[3], o->X,  bottom,"),
    M("init-p4-v", "    set_point(&l->Points[4], o->X,  o->Y,   z, 0.0f,  0.0f);", "    set_point(&l->Points[4], o->X,  o->Y,   z, 0.0f,  vmax);"),
    M("init-p5-x", "    set_point(&l->Points[5], cx,    o->Y,", "    set_point(&l->Points[5], right, o->Y,"),
    M("init-p6-u", "    set_point(&l->Points[6], right, o->Y,   z, umax,  0.0f);", "    set_point(&l->Points[6], right, o->Y,   z, uhalf, 0.0f);"),
    M("init-p7-v", "    set_point(&l->Points[7], right, cy,     z, umax,  vhalf);", "    set_point(&l->Points[7], right, cy,     z, umax,  0.0f);"),
    M("init-p8-y", "    set_point(&l->Points[8], right, bottom,", "    set_point(&l->Points[8], right, cy,"),
    M("init-p8-z", "    set_point(&l->Points[8], right, bottom, z,", "    set_point(&l->Points[8], right, bottom, 0.0f,"),
    M("init-point-order", "    p->u = u;\n    p->v = v;", "    p->u = v;\n    p->v = u;"),

    # The table.
    M("table-row0", "    { 0, 7, 8, 1 },", "    { 0, 7, 8, 2 },"),
    M("table-row1", "    { 0, 5, 6, 7 },", "    { 0, 5, 6, 8 },"),
    M("table-row2", "    { 0, 3, 4, 5 },", "    { 0, 4, 3, 5 },"),
    M("table-row3", "    { 0, 1, 2, 3 },", "    { 1, 1, 2, 3 },"),
    M("table-three-rows", "    return i >= 0 && i < 4 ? kQuarters[i] : kNoQuarter;", "    return i >= 0 && i < 3 ? kQuarters[i] : kNoQuarter;"),
    M("table-past-end-row3", "    return i >= 0 && i < 4 ? kQuarters[i] : kNoQuarter;", "    return i >= 0 && i < 4 ? kQuarters[i] : kQuarters[3];"),

    # Render's angle.
    M("angle-359", "    a = ee_trunc_w(360.0f - (float)b->Object.Rotation);", "    a = ee_trunc_w(359.0f - (float)b->Object.Rotation);"),
    M("angle-c-cast", "    a = ee_trunc_w(360.0f - (float)b->Object.Rotation);", "    a = (int32_t)(360.0f - (float)b->Object.Rotation);"),
    M("angle-int", "    a = ee_trunc_w(360.0f - (float)b->Object.Rotation);", "    a = 360 - b->Object.Rotation;"),
    M("angle-q-91", "    q = a / 90;", "    q = a / 91;"),
    M("angle-q-floor", "    q = a / 90;", "    q = a >= 0 ? a / 90 : (a - 89) / 90;"),
    M("angle-r-abs", "    r = (float)(a % 90);", "    r = (float)((a % 90 + 90) % 90);"),
    M("angle-half-ge", "    if (45.0f < r) {", "    if (45.0f <= r) {"),
    M("angle-half-46", "    if (45.0f < r) {", "    if (46.0f < r) {"),
    M("angle-no-sub", "        r = r - 45.0f;\n", ""),
    M("angle-s-kept", "        s = 1;\n", ""),
    M("angle-s-start-1", "    int32_t a, q, s = 2, i, c;", "    int32_t a, q, s = 1, i, c;"),
    M("angle-over-44", "#define ONE_OVER_45 0x1.6c16c2p-6f", "#define ONE_OVER_45 (1.0f / 44.0f)"),
    M("angle-divide", "    t = 1.0f - r * ONE_OVER_45;", "    t = 1.0f - r / 45.0f;"),
    M("angle-t-not-flipped", "    t = 1.0f - r * ONE_OVER_45;", "    t = r * ONE_OVER_45;"),
    M("render-no-list-test", "    if (list == NULL) return;\n\n", "\n"),

    # The whole quarters.
    M("full-from-0", "    for (i = 1; i < q; i++) {", "    for (i = 0; i < q; i++) {"),
    M("full-through-q", "    for (i = 1; i < q; i++) {", "    for (i = 1; i <= q; i++) {"),
    M("full-row-minus-1", "        row = quarter(i);\n        for (c = 0; c < 4; c++)\n            set_corner",
      "        row = quarter(i - 1);\n        for (c = 0; c < 4; c++)\n            set_corner"),
    M("full-three-corners", "        for (c = 0; c < 4; c++)\n            set_corner(p, c, &list->Points[row[c]]);\n        z",
      "        for (c = 0; c < 3; c++)\n            set_corner(p, c, &list->Points[row[c]]);\n        z"),
    M("full-no-z", "        z = (float)b->Object.Z;\n        for (c = 0; c < 4; c++)\n            p->Vertices[c].z = z;\n        set_alpha(p);\n        memcpy",
      "        set_alpha(p);\n        memcpy"),
    M("full-z-unsigned", "        z = (float)b->Object.Z;\n        for (c = 0; c < 4; c++)\n            p->Vertices[c].z = z;\n        set_alpha(p);",
      "        z = (float)(uint8_t)b->Object.Z;\n        for (c = 0; c < 4; c++)\n            p->Vertices[c].z = z;\n        set_alpha(p);"),
    M("full-no-alpha", "        set_alpha(p);\n        memcpy", "        memcpy"),
    M("full-grey", "        memcpy(p->Colours, b->Colors, sizeof p->Colours);", "        memset(p->Colours, 0x80, sizeof p->Colours);"),
    M("full-no-flailer", "        memcpy(p->Colours, b->Colors, sizeof p->Colours);\n        p->Flailer = 1;",
      "        memcpy(p->Colours, b->Colors, sizeof p->Colours);"),

    # The cut.
    M("cut-row-q", "    row = quarter(i);\n    set_corner(p, 0,", "    row = quarter(q);\n    set_corner(p, 0,"),
    M("cut-no-corner-0", "    set_corner(p, 0, &list->Points[row[0]]);\n", ""),
    M("cut-from-s-minus-1", "    pa = &list->Points[row[s]];", "    pa = &list->Points[row[s - 1]];"),
    M("cut-to-s", "    pb = &list->Points[row[s + 1]];", "    pb = &list->Points[row[s]];"),
    M("cut-u-of-v", "    p->UVs[1][0]     = pa->u + t * (pb->u - pa->u);", "    p->UVs[1][0]     = pa->u + t * (pb->v - pa->v);"),
    M("cut-v-kept", "    p->UVs[1][1]     = pa->v + t * (pb->v - pa->v);\n", ""),
    M("cut-x-reversed", "    p->Vertices[1].x = pa->x + t * (pb->x - pa->x);", "    p->Vertices[1].x = pb->x + t * (pa->x - pb->x);"),
    M("cut-x-two-products", "    p->Vertices[1].x = pa->x + t * (pb->x - pa->x);", "    p->Vertices[1].x = pa->x * (1.0f - t) + pb->x * t;"),
    M("cut-y-of-x", "    p->Vertices[1].y = pa->y + t * (pb->y - pa->y);", "    p->Vertices[1].y = pa->y + t * (pb->x - pa->x);"),
    M("cut-from-s", "    for (c = s + 1; c < 4; c++)\n        set_corner(p, c, &list->Points[row[c]]);",
      "    for (c = s; c < 4; c++)\n        if (c != 1) set_corner(p, c, &list->Points[row[c]]);"),
    M("cut-from-2", "    for (c = s + 1; c < 4; c++)", "    for (c = 2; c < 4; c++)"),
    M("cut-no-alpha", "    set_alpha(p);\n    z = (float)b->Object.Z;", "    z = (float)b->Object.Z;"),
    M("cut-no-z", "    z = (float)b->Object.Z;\n    for (c = 0; c < 4; c++)\n        p->Vertices[c].z = z;\n    memset",
      "    memset"),
    M("cut-bitmap-colours", "    memset(p->Colours, 0x80, sizeof p->Colours);", "    memcpy(p->Colours, b->Colors, sizeof p->Colours);"),
    M("cut-no-flailer", "    memset(p->Colours, 0x80, sizeof p->Colours);\n    p->Flailer = 1;", "    memset(p->Colours, 0x80, sizeof p->Colours);"),
    M("cut-skipped", "    // With s 2, corner 2 keeps the constructor's.\n    p = add_poly(ctx);",
      "    // With s 2, corner 2 keeps the constructor's.\n    return;\n    p = add_poly(ctx);"),

    # The Flailer's ALPHA_1.
    M("alpha-off", "    p->AlphaEnabled = 1;", "    p->AlphaEnabled = 0;"),
    M("alpha-a-cd", "    p->AlphaA       = EPOLY_ALPHA_CS;", "    p->AlphaA       = EPOLY_ALPHA_CD;"),
    M("alpha-b-zero", "    p->AlphaB       = EPOLY_ALPHA_CD;", "    p->AlphaB       = EPOLY_ALPHA_ZERO;"),
    M("alpha-c-ad", "    p->AlphaC       = 0;            // As", "    p->AlphaC       = 1;            // As"),
    M("alpha-d-zero", "    p->AlphaD       = EPOLY_ALPHA_CD;", "    p->AlphaD       = EPOLY_ALPHA_ZERO;"),
    M("alpha-fix", "    p->AlphaFix     = 0x80;", "    p->AlphaFix     = 0x7f;"),
]

EQUIVALENT = {
    "pow2-zero-kept":
        "For 0 the loop runs 31 times and 2 << 31 is 0 in 32 bits, the "
        "answer the test gives.",
    "angle-q-floor":
        "q differs only for a negative angle, where both are below 2: no "
        "whole quarter, and the cut on row 1 either way.",
    "init-uhalf-no-zero-add":
        "0 + x differs from x only for x = -0, and umax is a size over a "
        "power of two, both unsigned: never -0. Even 0/0 is the EE's "
        "+FLT_MAX.",
    "table-row0":
        "Render reads rows 1 to q, and the cut row q or 1, so row 0 is "
        "never read. It is retail's all the same.",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text(encoding="latin-1").splitlines(),
                quiet=True):
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
                n = diff(base, out.read_text(encoding="latin-1")
                         .splitlines(), quiet=True)
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
    indir.cleanup()

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

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
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
