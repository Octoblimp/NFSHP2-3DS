#!/usr/bin/env python3
"""Cross-check 3DS Files/source/sky.c (Sky.obj) and sun.c (Sun.obj's data
half) against the retail image itself, run in mipsemu.

The model is the image: SkyInitModel, SkyLoader, SkyUnloader, StuffSky,
Sky.obj's static constructor and destructor, LoaderSun, UnloaderSun,
SunTrackLoader and SunTrackUnloader run as shipped, with every callee but
memset stubbed. Each stub prints its name and its arguments, and the few
that the state depends on do the same small thing on both sides:

    FindSceneryInstance / FindSceneryInfo   the scenario's SKYDOME and
                                            SKYDOME_ENVMAP, when present
    eModel::Init                            NameHash = the name, Solid = solid
    eModel::UnInit                          NameHash = 0, Solid = NULL
    eIdentity                               the identity
    GetTextureInfo                          t0..t4 for the sun's names the
                                            scenario has, else the default
                                            when asked for and there is one

The harness links sky.c and sun.c with the same stubs and prints the same
lines. After each step both dump the two models' names and solids, both
matrices bit for bit, DrawSky, the six LOD models the two kinds hold,
SunInfo (as an offset into the chunk), SunPosition, SunTextures, the
rendering order of the six textures, and SunGlareInfo, which each scenario
starts as 0x5a bytes.

Retail's image is stripped, so its addresses here are read off its code;
each one retail_model's map pairs with the demo's is checked against it.
Sky.obj is the demo's, moved. LoaderSun fills SunGlareInfo too.

Scenarios: either dome, both, or neither; each kind's LOD models in every
mask; rotations at the int16 ends and positions of every kind of float;
the loader, the unloader and SkyInitModel on its own, in orders the game
does not use; StuffSky for every view ID with DrawSky on and off, and with
the render seam NULL (the model's Render is silent then); the sun chunk at
each misalignment, every version, and the wrong type, and retail
TRACKB12's own as the disc has it; the sun's names found, missing with the
default, and missing with none.

    python tools/sky_check.py
    python tools/sky_check.py --mutate [--only a,b]
    python tools/sky_check.py --dump out/sky
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
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/sky_test.c"
SKC = "3DS Files/source/sky.c"
SKH = "3DS Files/source/sky.h"
SUC = "3DS Files/source/sun.c"
SUH = "3DS Files/source/sun.h"
SOURCES = [HARNESS, SKC, SUC]

HARNESS_TIMEOUT = 60

# ================================================================ the image

# Retail's, read off its code.
GP = 0x003358f0
SKY_MODEL = 0x002dc410
SKY_M = 0x002dc430
ENV_MODEL = 0x002dc470
ENV_M = 0x002dc490
DRAW_SKY = GP - 24044
SUN_INFO = GP - 23584
SUN_POS = 0x002e03c0
SUN_TEX = 0x002ef5b8
GLARE_INFO = 0x002ef4c0              # SunGlareInfo

SKY_INIT_MODEL = 0x0011c450
SKY_LOADER = 0x0011c5f8
SKY_UNLOADER = 0x0011c6b8
STUFF_SKY = 0x0011c6f8
SKY_DTOR = 0x0011c768
SKY_CTOR = 0x0011c798
LOADER_SUN = 0x00124f30
UNLOADER_SUN = 0x00125188
SUN_TRACK_LOADER = 0x001251c0
SUN_TRACK_UNLOADER = 0x00125290

FIND_INSTANCE = 0x0014f130
FIND_INFO = 0x0014f0d0
EMODEL_INIT = 0x0010c558
EMODEL_UNINIT = 0x0010c5b0
EIDENTITY = 0x0011b1b0
EMODEL_RENDER = 0x0010dc80
EMODEL_DELETE = 0x00114cf0
GET_TEXTURE_INFO = 0x001abf48

# The ones the map pairs, and the demo's twins. LoaderSun has none.
DEMO_CODE = {
    SKY_INIT_MODEL: 0x0011cc70, SKY_LOADER: 0x0011ce18,
    SKY_UNLOADER: 0x0011ced8, STUFF_SKY: 0x0011cf18, SKY_DTOR: 0x0011cf88,
    SKY_CTOR: 0x0011cfb8, UNLOADER_SUN: 0x00123da8,
    SUN_TRACK_LOADER: 0x00123de0, SUN_TRACK_UNLOADER: 0x00123ea0,
    FIND_INSTANCE: 0x0014c800, FIND_INFO: 0x0014c7a0,
    EMODEL_INIT: 0x0010b230, EMODEL_UNINIT: 0x0010b288,
    EIDENTITY: 0x0011ba18, EMODEL_RENDER: 0x0010c7c8,
    EMODEL_DELETE: 0x00114918, GET_TEXTURE_INFO: 0x001a19b0,
}
DEMO_DATA = {
    SKY_MODEL: 0x002dc600, SKY_M: 0x002dc620, ENV_MODEL: 0x002dc660,
    ENV_M: 0x002dc680, DRAW_SKY: 0x00322c28, SUN_INFO: 0x00322da0,
    SUN_TEX: 0x002e76f0,
}

SKYDOME = 0xbe43edbb
SKYDOME_ENVMAP = 0x72923c81
HASHES = (SKYDOME, SKYDOME_ENVMAP)
SUN_HASHES = (0x47beb4b6, 0xd4d26c59, 0x1744b82d, 0xad3c5239, 0xd4d80a65)
SUN_CHUNK = 0x00034202

# Where the model puts the objects a scenario names.
INST = (0x01000000, 0x01000040)
INFO = (0x01000080, 0x010000c0)
LOD = 0x01000100                     # six, 32 apart
SOLID = 0x01000200
JUNK = 0x01000210
TEX = 0x01001000                     # t0..t4 and the default, 256 apart
VIEW = 0x01002000
CHUNK = 0x01003000                   # 16-aligned; the scenario adds 0..12


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


class Scenario(object):
    def __init__(self, ops, draw=1, null=0, views=(1, 2, 3, 0, 4, 9, -1, 10),
                 sky=None, env=None, chunk=None, mis=0, found=0x1f,
                 default=1, order=3):
        self.ops = ops
        self.draw = draw
        self.null = null
        self.views = list(views)
        assert len(self.views) == 8
        self.objs = [sky, env]
        self.chunk = chunk if chunk is not None else sun_chunk(2, mis)
        self.mis = mis
        self.found = found
        self.default = default
        self.order = order

    def lines(self):
        out = []
        for k, o in enumerate(self.objs):
            if o is None:
                o = Obj(present=0)
            out.append("O %d %d %d %s %s" % (
                k, o.present, o.mask, " ".join(str(r) for r in o.rot),
                " ".join("%x" % p for p in o.pos)))
        out.append("C %d %s" % (self.mis, self.chunk.hex()))
        out.append("T %d %d %d" % (self.found, self.default, self.order))
        out.append("S %d %d %s %s" % (self.draw, self.null,
                                      " ".join(str(v) for v in self.views),
                                      self.ops))
        return out


class Obj(object):
    def __init__(self, present=1, mask=7, rot=(16384, 0, 0, 0, 16384, 0, 0,
                                                0, 16384),
                 pos=(0.0, 0.0, 0.0)):
        self.present = present
        self.mask = mask
        self.rot = list(rot)
        self.pos = [p if isinstance(p, int) else fbits(p) for p in pos]


def sun_chunk(version, mis, pos=(-16384.0, 800.0, 6000.0), cid=SUN_CHUNK,
              fill=0x11):
    """A 0x34202 chunk as the disc has it, for a chunk `mis` past 16: the
    SunChunkInfoE at the next 16 after the header, the filler before it."""
    off = ((mis + 8 + 15) & ~15) - mis
    info = struct.pack("<i", version)
    info += b"".join(struct.pack("<I", p if isinstance(p, int) else fbits(p))
                     for p in pos)
    info += struct.pack("<3f", 1.5, -2.5, 3.25)
    for i in range(6):
        info += struct.pack("<ii4f4Bif", i % 5, i & 1, 1.0, 60.0 + i,
                            0.0, -1.0, 0xff, 0xc8, 0x64, 0x80, i * 7, 0.5)
    assert len(info) == 244
    body = bytes([fill]) * (off - 8) + info
    return struct.pack("<II", cid, len(body)) + body


RETAIL_B12 = ROOT / "extracted-retail" / "TRACKS" / "TRACKB12.BUN"


def disc_chunk(path=RETAIL_B12):
    """The track's one 0x34202 chunk as the disc has it, and how far past
    16 it sits."""
    b = path.read_bytes()
    found = [i for i in range(0, len(b) - 8, 4)
             if struct.unpack_from("<I", b, i)[0] == SUN_CHUNK
             and struct.unpack_from("<I", b, i + 4)[0] == 256]
    assert len(found) == 1, (path, found)
    i = found[0]
    return b[i:i + 8 + 256], i % 16


def script():
    S, O = Scenario, Obj
    ident = (16384, 0, 0, 0, 16384, 0, 0, 0, 16384)
    odd = (-32768, 32767, 1, -1, 12345, -16384, 8192, -7, 2)
    turned = (0, 0, -16384, 0, 16384, 0, 16384, 0, 0)
    nan = 0x7fc00001
    b12, b12_mis = disc_chunk()
    sc = [
        # The game's order: both domes, the End then the Begin.
        S("LRU", sky=O(pos=(10.5, -200.0, 3e5)), env=O(rot=turned,
          pos=(1.0, 2.0, 3.0))),
        # SKYDOME alone: the envmap views get it too.
        S("LRUR", sky=O(rot=odd, pos=(-0.0, 1e-40, nan))),
        # SKYDOME_ENVMAP alone, and neither.
        S("LRU", env=O(rot=odd, pos=(7.0, 8.0, 9.0))),
        S("LRU"),
        # Every mask of each kind's LODs.
        S("L", sky=O(mask=0), env=O(mask=1)),
        S("L", sky=O(mask=2), env=O(mask=3)),
        S("L", sky=O(mask=4), env=O(mask=5)),
        S("L", sky=O(mask=6), env=O(mask=0)),
        S("L", sky=O(mask=5), env=O(mask=6)),
        # SkyInitModel on its own, and on a name with no object.
        S("abc", sky=O(rot=odd, pos=(1.0, -1.0, 0.5)),
          env=O(rot=ident, pos=(4.0, 5.0, 6.0))),
        S("bac", sky=O(mask=0)),
        S("cab"),
        # The statics.
        S("I"), S("D"), S("ILUD", sky=O(), env=O()),
        # StuffSky: every view, off, and the seam NULL.
        S("R", views=(-2, -1, 0, 1, 2, 3, 4, 5)),
        S("R", views=(6, 7, 8, 9, 10, 0x7fffffff, -0x80000000, 256)),
        S("dR", sky=O()),
        S("LR", draw=0, sky=O(), env=O()),
        S("LR", draw=-1, sky=O()),
        S("LR", draw=2, env=O()),
        S("LRU", null=1, sky=O(), env=O()),
        # The sun chunk: each misalignment, each version, the wrong type.
        S("SsS", mis=0), S("SsS", mis=4), S("SsS", mis=8), S("SsS", mis=12),
        S("S", chunk=sun_chunk(1, 0), mis=0),
        S("S", chunk=sun_chunk(3, 4), mis=4),
        S("S", chunk=sun_chunk(0, 8), mis=8),
        S("S", chunk=sun_chunk(-1, 12), mis=12),
        S("S", chunk=sun_chunk(0x102, 0), mis=0),
        S("SXx", chunk=sun_chunk(2, 4, pos=(-0.0, nan, 1e-39)), mis=4),
        S("XxS", chunk=sun_chunk(2, 8, fill=0), mis=8),
        S("S", chunk=sun_chunk(2, 0, cid=0x00034203), mis=0),
        S("s", chunk=sun_chunk(2, 0, cid=0x80034202), mis=0),
        S("S", chunk=sun_chunk(2, 4, cid=0x80034202), mis=4),
        S("Ss", chunk=sun_chunk(2, 8, cid=0x00044202), mis=8),
        S("SSs", chunk=sun_chunk(1, 12), mis=12),
        # Retail TRACKB12's own, and its textures.
        S("STtsXS", chunk=b12, mis=b12_mis),
        # The sun's textures: all found, some, none with the default.
        S("Tt"),
        S("Tt", found=0x15, order=0),
        S("T", found=0x0a, order=255),
        S("T", found=0, order=9),
        S("Tt", found=0, default=0, order=4),
        S("T", found=0x1b, default=0, order=6),
        # The whole of it, twice.
        S("SLTRtUsSLTRtUs", sky=O(), env=O(rot=odd), mis=4, found=0x0f),
    ]
    return sc


class BigEmu(retail_model.RetailEmu):
    RAM = 128 << 20


class Model(object):
    def __init__(self):
        self.out = []
        self.e = BigEmu(ieee=True)
        self.sc = None
        e = self.e
        for r, d in DEMO_CODE.items():
            assert e.map.by_demo[d][2] == r, (hex(d), hex(r))
        for r, d in DEMO_DATA.items():
            assert e.data(d) == r, (hex(d), hex(r))
        e.stub(FIND_INSTANCE, self.find_instance)
        e.stub(FIND_INFO, self.find_info)
        e.stub(EMODEL_INIT, self.init)
        e.stub(EMODEL_UNINIT, self.uninit)
        e.stub(EIDENTITY, self.identity)
        e.stub(EMODEL_RENDER, self.render)
        e.stub(EMODEL_DELETE, self.delete)
        e.stub(GET_TEXTURE_INFO, self.get_texture_info)

    def emit(self, s):
        self.out.append(s)

    def label(self, a):
        a &= M32
        names = {0: "null", SKY_MODEL: "sky", ENV_MODEL: "env",
                 SKY_M: "skyM", ENV_M: "envM", INST[0]: "isky",
                 INST[1]: "ienv", INFO[0]: "fsky", INFO[1]: "fenv",
                 SOLID: "solid", JUNK: "junk"}
        if a in names:
            return names[a]
        for i in range(6):
            if a == LOD + 32 * i:
                return "m%d" % i
            if a == TEX + 256 * i:
                return "dflt" if i == 5 else "t%d" % i
        base = CHUNK + self.sc.mis
        if base <= a < base + 512:
            return "c+%d" % (a - base)
        return "x%08x" % a

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    # ---- the stubs ---------------------------------------------------------

    def find(self, name, table):
        h = self.arg(0)
        r = 0
        for k in (0, 1):
            o = self.sc.objs[k]
            if o is not None and o.present and h == HASHES[k]:
                r = table[k]
        self.emit("  %s %08x -> %s" % (name, h, self.label(r)))
        return r

    def find_instance(self, em):
        return self.find("FindSceneryInstance", INST)

    def find_info(self, em):
        return self.find("FindSceneryInfo", INFO)

    def init(self, em):
        m, h = self.arg(0), self.arg(1)
        self.emit("  Init %s %08x" % (self.label(m), h))
        em.put32(m + 8, h)
        em.put32(m + 12, SOLID)

    def uninit(self, em):
        m = self.arg(0)
        self.emit("  UnInit %s" % self.label(m))
        em.put32(m + 8, 0)
        em.put32(m + 12, 0)

    def identity(self, em):
        m = self.arg(0)
        self.emit("  eIdentity %s" % self.label(m))
        for i in range(16):
            em.put32(m + 4 * i, fbits(1.0) if i % 5 == 0 else 0)

    def render(self, em):
        if self.sc.null:
            return
        self.emit("  Render %s %s %s %u" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2)), self.arg(3)))

    def delete(self, em):
        self.emit("  ~eModel %s %d" % (self.label(self.arg(0)),
                                       s32(self.arg(1))))

    def get_texture_info(self, em):
        h, use_default = self.arg(0), s32(self.arg(1))
        r = 0
        for i, sh in enumerate(SUN_HASHES):
            if h == sh and (self.sc.found >> i & 1):
                r = TEX + 256 * i
        if r == 0 and use_default and self.sc.default:
            r = TEX + 256 * 5
        if self.arg(2) != 0:
            self.emit("  GetTextureInfo include_unloaded %d"
                      % s32(self.arg(2)))
        self.emit("  GetTextureInfo %08x %d -> %s" % (h, use_default,
                                                      self.label(r)))
        return r

    # ---- the state ---------------------------------------------------------

    def dump(self):
        e = self.e
        self.emit("  = sky %08x %s env %08x %s draw %d" % (
            e.u32(SKY_MODEL + 8), self.label(e.u32(SKY_MODEL + 12)),
            e.u32(ENV_MODEL + 8), self.label(e.u32(ENV_MODEL + 12)),
            s32(e.u32(DRAW_SKY))))
        for name, m in (("skyM", SKY_M), ("envM", ENV_M)):
            self.emit("  %s %s" % (name, " ".join(
                "%08x" % e.u32(m + 4 * i) for i in range(16))))
        self.emit("  lods " + " ".join(
            "%08x %s" % (e.u32(LOD + 32 * i + 8),
                         self.label(e.u32(LOD + 32 * i + 12)))
            for i in range(6)))
        self.emit("  sun %s pos %08x %08x %08x tex %s ord %s" % (
            self.label(e.u32(SUN_INFO)), e.u32(SUN_POS), e.u32(SUN_POS + 4),
            e.u32(SUN_POS + 8),
            " ".join(self.label(e.u32(SUN_TEX + 4 * i)) for i in range(5)),
            " ".join(str(e.u8(TEX + 256 * i + 41)) for i in range(6))))
        self.emit("  glare %s" % bytes(e.mem[GLARE_INFO:GLARE_INFO
                                             + 244]).hex())

    def reset(self, sc):
        e = self.e
        e.put32(SKY_MODEL + 8, 0x0bad0001)
        e.put32(SKY_MODEL + 12, JUNK)
        e.put32(ENV_MODEL + 8, 0x0bad0002)
        e.put32(ENV_MODEL + 12, JUNK)
        for i in range(16):
            e.put32(SKY_M + 4 * i, 0x7f000000 + i)
            e.put32(ENV_M + 4 * i, 0x7e000000 + i)
        for i in range(6):
            e.put32(LOD + 32 * i + 8, 0x1000 + i)
            e.put32(LOD + 32 * i + 12, JUNK)
        e.put32(DRAW_SKY, sc.draw)
        e.put32(SUN_INFO, 0)
        e.put32(SUN_POS, fbits(1.0))
        e.put32(SUN_POS + 4, fbits(2.0))
        e.put32(SUN_POS + 8, fbits(3.0))
        for i in range(5):
            e.put32(SUN_TEX + 4 * i, 0)
        e.write(GLARE_INFO, bytes([0x5a]) * 244)
        for i in range(6):
            e.mem[TEX + 256 * i + 41] = sc.order & 0xff
        for k in (0, 1):
            o = sc.objs[k] or Obj(present=0)
            a = INST[k]
            e.write(a, bytes(48))
            for j in range(3):
                e.put32(a + 16 + 4 * j, o.pos[j])
            e.write(a + 28, struct.pack("<9h", *o.rot))
            f = INFO[k]
            e.write(f, bytes(40))
            e.put32(f, HASHES[k])
            for j in range(3):
                e.put32(f + 20 + 4 * j,
                        LOD + 32 * (3 * k + j) if o.mask >> j & 1 else 0)
        e.write(CHUNK, bytes(512))
        e.write(CHUNK + sc.mis, sc.chunk)

    def run(self, scenarios):
        e = self.e
        # The one value no scenario sets: DrawSky as the image starts.
        self.emit("DrawSky starts %d" % s32(e.u32(DRAW_SKY)))
        for k, sc in enumerate(scenarios):
            self.sc = sc
            self.reset(sc)
            chunk = CHUNK + sc.mis
            self.emit("scenario %d %s" % (k, sc.ops))
            for o in sc.ops:
                self.emit(" %s" % o)
                if o == "I":
                    e.call(SKY_CTOR, limit=10000)
                elif o == "D":
                    e.call(SKY_DTOR, limit=10000)
                elif o == "L":
                    e.call(SKY_LOADER, limit=10000)
                elif o == "U":
                    e.call(SKY_UNLOADER, limit=10000)
                elif o in "abc":
                    m, mat, h = {
                        "a": (SKY_MODEL, SKY_M, SKYDOME),
                        "b": (ENV_MODEL, ENV_M, SKYDOME_ENVMAP),
                        "c": (SKY_MODEL, SKY_M, 0x12345678)}[o]
                    self.emit("  -> %d" % e.call(SKY_INIT_MODEL, m, mat, h,
                                                 limit=10000))
                elif o == "R":
                    for v in sc.views:
                        e.put32(VIEW, v)
                        self.emit("  view %d" % v)
                        e.call(STUFF_SKY, VIEW, limit=10000)
                elif o == "S":
                    self.emit("  -> %d" % e.call(LOADER_SUN, chunk,
                                                 limit=10000))
                elif o == "s":
                    self.emit("  -> %d" % e.call(UNLOADER_SUN, chunk,
                                                 limit=10000))
                elif o in "Xx":
                    cid = e.u32(chunk)
                    e.put32(chunk, cid ^ 1)
                    self.emit("  -> %d" % e.call(
                        LOADER_SUN if o == "X" else UNLOADER_SUN, chunk,
                        limit=10000))
                    e.put32(chunk, cid)
                elif o == "T":
                    e.call(SUN_TRACK_LOADER, limit=10000)
                elif o == "t":
                    e.call(SUN_TRACK_UNLOADER, limit=10000)
                elif o == "d":
                    e.put32(DRAW_SKY, 0)
                self.dump()
        return self.out


def model(scenarios):
    return Model().run(scenarios)


# ================================================================ the build


def build_harness(tmp, name="sky_test"):
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
    return NL.join(l for s in scenarios for l in s.lines()) + NL


diff = pcc.diff

# ============================================================ the mutations

# SkyInitModel from its Init to its return, for the mutation that moves the
# Init to the end.
INIT_REST = """    r = inst->Rotation;
    matrix->v0.x = (float)r[0] * ROTATION_UNIT;
    matrix->v0.y = (float)r[1] * ROTATION_UNIT;
    matrix->v0.z = (float)r[2] * ROTATION_UNIT;
    matrix->v0.w = 0.0f;
    matrix->v1.x = (float)r[3] * ROTATION_UNIT;
    matrix->v1.y = (float)r[4] * ROTATION_UNIT;
    matrix->v1.z = (float)r[5] * ROTATION_UNIT;
    matrix->v1.w = 0.0f;
    matrix->v2.x = (float)r[6] * ROTATION_UNIT;
    matrix->v2.y = (float)r[7] * ROTATION_UNIT;
    matrix->v2.z = (float)r[8] * ROTATION_UNIT;
    matrix->v2.w = 0.0f;
    matrix->v3.x = inst->Position[0];
    matrix->v3.y = inst->Position[1];
    matrix->v3.z = inst->Position[2];
    matrix->v3.w = 1.0f;

    // The image does not check the kind: an object of the name means a
    // kind whose first LOD has it.
    info = scenery_find_info(name_hash);
    for (i = 0; i < 3; i++) {
        if (info->pModel[i] != NULL) {
            emodel_uninit(info->pModel[i]);
        }
    }
"""

MUTATIONS = [
    # SkyInitModel.
    ("init_no_find", SKC,
     "    SceneryInstance *inst = scenery_find_instance_by_hash(name_hash);",
     "    SceneryInstance *inst = scenery_find_instance_by_hash(0);"),
    ("init_missing_no_uninit", SKC,
     "    if (inst == NULL) {\n        emodel_uninit(model);\n",
     "    if (inst == NULL) {\n"),
    ("init_missing_no_identity", SKC,
     "        emodel_uninit(model);\n        eIdentity(matrix);\n",
     "        emodel_uninit(model);\n"),
    ("init_missing_identity_first", SKC,
     "        emodel_uninit(model);\n        eIdentity(matrix);\n",
     "        eIdentity(matrix);\n        emodel_uninit(model);\n"),
    ("init_missing_returns_1", SKC,
     "        eIdentity(matrix);\n        return 0;", "        eIdentity(matrix);\n        return 1;"),
    ("init_found_returns_0", SKC,
     "    }\n    return 1;\n}", "    }\n    return 0;\n}"),
    ("init_no_init", SKC,
     "    emodel_init(model, name_hash);\n    r = inst->Rotation;",
     "    r = inst->Rotation;"),
    ("init_wrong_name", SKC,
     "    emodel_init(model, name_hash);\n    r = inst->Rotation;",
     "    emodel_init(model, 0);\n    r = inst->Rotation;"),
    ("init_after_lods", SKC,
     "    emodel_init(model, name_hash);\n" + INIT_REST + "    return 1;",
     INIT_REST + "    emodel_init(model, name_hash);\n    return 1;"),
    ("rot_unit_2_13", SKC,
     "#define ROTATION_UNIT (1.0f / 16384.0f)",
     "#define ROTATION_UNIT (1.0f / 8192.0f)"),
    ("rot_transposed", SKC,
     "    matrix->v0.y = (float)r[1] * ROTATION_UNIT;",
     "    matrix->v0.y = (float)r[3] * ROTATION_UNIT;"),
    ("rot_row1_x", SKC,
     "    matrix->v1.x = (float)r[3] * ROTATION_UNIT;",
     "    matrix->v1.x = (float)r[4] * ROTATION_UNIT;"),
    ("rot_row2_z", SKC,
     "    matrix->v2.z = (float)r[8] * ROTATION_UNIT;",
     "    matrix->v2.z = (float)r[7] * ROTATION_UNIT;"),
    ("rot_unsigned", SKC,
     "    matrix->v1.z = (float)r[5] * ROTATION_UNIT;",
     "    matrix->v1.z = (float)(uint16_t)r[5] * ROTATION_UNIT;"),
    ("rot_w0_kept", SKC,
     "    matrix->v0.w = 0.0f;\n", ""),
    ("rot_w1_one", SKC,
     "    matrix->v1.w = 0.0f;", "    matrix->v1.w = 1.0f;"),
    ("rot_w2_kept", SKC,
     "    matrix->v2.w = 0.0f;\n", ""),
    ("pos_swapped", SKC,
     "    matrix->v3.y = inst->Position[1];\n    matrix->v3.z = inst->Position[2];",
     "    matrix->v3.y = inst->Position[2];\n    matrix->v3.z = inst->Position[1];"),
    ("pos_x_zero", SKC,
     "    matrix->v3.x = inst->Position[0];", "    matrix->v3.x = 0.0f;"),
    ("pos_w_kept", SKC,
     "    matrix->v3.w = 1.0f;\n", ""),
    ("pos_w_zero", SKC,
     "    matrix->v3.w = 1.0f;", "    matrix->v3.w = 0.0f;"),
    ("lods_two", SKC,
     "    for (i = 0; i < 3; i++) {\n        if (info->pModel[i]",
     "    for (i = 0; i < 2; i++) {\n        if (info->pModel[i]"),
    ("lods_from_1", SKC,
     "    for (i = 0; i < 3; i++) {\n        if (info->pModel[i]",
     "    for (i = 1; i < 3; i++) {\n        if (info->pModel[i]"),
    ("lods_kept", SKC,
     "            emodel_uninit(info->pModel[i]);\n", ""),
    ("lods_first_only", SKC,
     "            emodel_uninit(info->pModel[i]);",
     "            emodel_uninit(info->pModel[0]);"),
    ("lods_info_other_name", SKC,
     "    info = scenery_find_info(name_hash);",
     "    info = scenery_find_info(SKY_HASH_SKYDOME);"),
    # SkyLoader and SkyUnloader.
    ("loader_no_sky", SKC,
     "    SkyInitModel(&SkydomeModel, &SkydomeLocalWorld, SKY_HASH_SKYDOME);\n", ""),
    ("loader_env_first", SKC,
     "    SkyInitModel(&SkydomeModel, &SkydomeLocalWorld, SKY_HASH_SKYDOME);\n"
     "    if (!SkyInitModel(&SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld,\n"
     "                      SKY_HASH_SKYDOME_ENVMAP)) {",
     "    if (!SkyInitModel(&SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld,\n"
     "                      SKY_HASH_SKYDOME_ENVMAP)) {\n"
     "    SkyInitModel(&SkydomeModel, &SkydomeLocalWorld, SKY_HASH_SKYDOME);"),
    ("loader_env_hash", SKH,
     "#define SKY_HASH_SKYDOME_ENVMAP  0x72923c81u",
     "#define SKY_HASH_SKYDOME_ENVMAP  0x72923c80u"),
    ("loader_sky_hash", SKH,
     "#define SKY_HASH_SKYDOME         0xbe43edbbu",
     "#define SKY_HASH_SKYDOME         0xbe43edbau"),
    ("loader_fallback_always", SKC,
     "    if (!SkyInitModel(&SkydomeEnvmapModel", "    if (1 | SkyInitModel(&SkydomeEnvmapModel"),
    ("loader_fallback_never", SKC,
     "    if (!SkyInitModel(&SkydomeEnvmapModel", "    if (0 & SkyInitModel(&SkydomeEnvmapModel"),
    ("loader_fallback_no_init", SKC,
     "        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME);\n", ""),
    ("loader_fallback_env_name", SKC,
     "        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME);",
     "        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME_ENVMAP);"),
    ("loader_fallback_no_copy", SKC,
     "        SkydomeEnvmapLocalWorld = SkydomeLocalWorld;\n", ""),
    ("loader_fallback_copy_first", SKC,
     "        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME);\n"
     "        SkydomeEnvmapLocalWorld = SkydomeLocalWorld;",
     "        SkydomeEnvmapLocalWorld = SkydomeLocalWorld;\n"
     "        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME);"),
    ("unloader_no_sky", SKC,
     "    emodel_uninit(&SkydomeModel);\n    eIdentity(&SkydomeLocalWorld);\n", ""),
    ("unloader_env_first", SKC,
     "    emodel_uninit(&SkydomeModel);\n    eIdentity(&SkydomeLocalWorld);\n"
     "    emodel_uninit(&SkydomeEnvmapModel);\n    eIdentity(&SkydomeEnvmapLocalWorld);",
     "    emodel_uninit(&SkydomeEnvmapModel);\n    eIdentity(&SkydomeEnvmapLocalWorld);\n"
     "    emodel_uninit(&SkydomeModel);\n    eIdentity(&SkydomeLocalWorld);"),
    ("unloader_no_env_identity", SKC,
     "    eIdentity(&SkydomeEnvmapLocalWorld);\n}", "}"),
    ("unloader_identity_first", SKC,
     "    emodel_uninit(&SkydomeModel);\n    eIdentity(&SkydomeLocalWorld);\n",
     "    eIdentity(&SkydomeLocalWorld);\n    emodel_uninit(&SkydomeModel);\n"),
    # StuffSky.
    ("stuff_ignores_drawsky", SKC,
     "    if (!DrawSky || gEModelRenderFn == NULL) {",
     "    if (gEModelRenderFn == NULL) {"),
    ("stuff_drawsky_positive", SKC,
     "    if (!DrawSky || gEModelRenderFn == NULL) {",
     "    if (DrawSky <= 0 || gEModelRenderFn == NULL) {"),
    ("stuff_views_1_2", SKC,
     "    if ((uint32_t)(view->ID - 1) < 3u) {", "    if ((uint32_t)(view->ID - 1) < 2u) {"),
    ("stuff_views_0_3", SKC,
     "    if ((uint32_t)(view->ID - 1) < 3u) {", "    if ((uint32_t)view->ID < 4u) {"),
    ("stuff_views_signed", SKC,
     "    if ((uint32_t)(view->ID - 1) < 3u) {", "    if (view->ID - 1 < 3) {"),
    ("stuff_swapped", SKC,
     "        gEModelRenderFn(&SkydomeModel, &SkydomeLocalWorld, NULL, 0);",
     "        gEModelRenderFn(&SkydomeEnvmapModel, &SkydomeLocalWorld, NULL, 0);"),
    ("stuff_env_matrix", SKC,
     "        gEModelRenderFn(&SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld, NULL,",
     "        gEModelRenderFn(&SkydomeEnvmapModel, &SkydomeLocalWorld, NULL,"),
    ("stuff_flags_4", SKC,
     "        gEModelRenderFn(&SkydomeModel, &SkydomeLocalWorld, NULL, 0);",
     "        gEModelRenderFn(&SkydomeModel, &SkydomeLocalWorld, NULL, 4);"),
    ("stuff_seam_unguarded", SKC,
     "    if (!DrawSky || gEModelRenderFn == NULL) {",
     "    if (!DrawSky) {"),
    # The statics.
    ("ctor_keeps_sky_solid", SKC,
     "    SkydomeModel.Solid          = NULL;\n", ""),
    ("ctor_keeps_env_name", SKC,
     "    SkydomeEnvmapModel.NameHash = 0;\n", ""),
    ("dtor_sky_first", SKC,
     "    emodel_delete(&SkydomeEnvmapModel, 2);\n    emodel_delete(&SkydomeModel, 2);",
     "    emodel_delete(&SkydomeModel, 2);\n    emodel_delete(&SkydomeEnvmapModel, 2);"),
    ("dtor_flags_3", SKC,
     "    emodel_delete(&SkydomeModel, 2);", "    emodel_delete(&SkydomeModel, 3);"),
    ("drawsky_0", SKC,
     "int32_t  DrawSky = 1;", "int32_t  DrawSky = 0;"),
    # The sun chunk.
    ("sun_type", SUH,
     "#define SUN_CHUNK_ID      0x00034202u", "#define SUN_CHUNK_ID      0x00034203u"),
    ("sun_version_1", SUH,
     "#define SUN_INFO_VERSION  2", "#define SUN_INFO_VERSION  1"),
    ("sun_no_align", SUC,
     "    info = (SunChunkInfoE *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
     "    info = (SunChunkInfoE *)(chunk + 8);"),
    ("sun_align_8", SUC,
     "    info = (SunChunkInfoE *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
     "    info = (SunChunkInfoE *)(((uintptr_t)chunk + 8 + 7) & ~(uintptr_t)7);"),
    ("sun_align_from_chunk", SUC,
     "    info = (SunChunkInfoE *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);",
     "    info = (SunChunkInfoE *)(((uintptr_t)chunk + 15) & ~(uintptr_t)15);"),
    ("sun_info_after_check", SUC,
     "    SunInfo = info;\n    if (info->Version != SUN_INFO_VERSION) {\n        forget_sun();\n    } else {",
     "    if (info->Version != SUN_INFO_VERSION) {\n        forget_sun();\n    } else {\n        SunInfo = info;"),
    ("sun_bad_keeps_info", SUC,
     "static void forget_sun(void)\n{\n    SunInfo       = NULL;\n",
     "static void forget_sun(void)\n{\n"),
    ("sun_bad_keeps_pos", SUC,
     "    SunPosition.z = 0.0f;\n    SunPosition.y = 0.0f;\n}",
     "    SunPosition.z = 0.0f;\n}"),
    ("sun_pos_shadow", SUC,
     "        SunPosition.x = info->PositionX;", "        SunPosition.x = info->CarShadowPositionX;"),
    ("sun_pos_yz", SUC,
     "        SunPosition.y = info->PositionY;\n        SunPosition.z = info->PositionZ;",
     "        SunPosition.y = info->PositionZ;\n        SunPosition.z = info->PositionY;"),
    ("sun_bad_returns_0", SUC,
     "        forget_sun();\n    } else {", "        forget_sun();\n        return 0;\n    } else {"),
    ("sun_unloader_any_type", SUC,
     "int unloader_sun(uint8_t *chunk)\n{\n    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {\n        return 0;\n    }",
     "int unloader_sun(uint8_t *chunk)\n{"),
    ("sun_unloader_keeps", SUC,
     "    }\n    forget_sun();\n    return 1;", "    }\n    return 1;"),
    ("sun_loader_type_low16", SUC,
     "    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {\n        return 0;\n    }\n    // The chunk's",
     "    if ((bchunk_u32(chunk) & 0xffff) != (SUN_CHUNK_ID & 0xffff)) {\n        return 0;\n    }\n    // The chunk's"),
    # The sun's textures.
    ("tex_no_default", SUC,
     "        SunTextures[i] = GetTextureInfo(kSunTextureHashes[i], 1, 0);",
     "        SunTextures[i] = GetTextureInfo(kSunTextureHashes[i], 0, 0);"),
    # Retail's third argument (task 36): loaded textures only.
    ("tex_include_unloaded", SUC,
     "        SunTextures[i] = GetTextureInfo(kSunTextureHashes[i], 1, 0);",
     "        SunTextures[i] = GetTextureInfo(kSunTextureHashes[i], 1, 1);"),
    ("tex_four", SUC,
     "    for (i = 0; i < NUM_SUN_TEXTURES; i++) {\n        SunTextures[i] = GetTextureInfo",
     "    for (i = 0; i < NUM_SUN_TEXTURES - 1; i++) {\n        SunTextures[i] = GetTextureInfo"),
    ("tex_hash_ring", SUC,
     "    0xd4d80a65u,    // SUNRING", "    0xd4d80a64u,    // SUNRING"),
    ("tex_hash_halo_major", SUC,
     "    0xd4d26c59u,    // SUNHALO\n    0x1744b82du,    // SUNMAJORRAYS",
     "    0x1744b82du,    // SUNMAJORRAYS\n    0xd4d26c59u,    // SUNHALO"),
    ("tex_order_6", SUC,
     "#define SUN_RENDERING_ORDER 7", "#define SUN_RENDERING_ORDER 6"),
    ("tex_no_order", SUC,
     "            SunTextures[i]->RenderingOrder = SUN_RENDERING_ORDER;\n", ""),
    ("tex_order_first_only", SUC,
     "            SunTextures[i]->RenderingOrder = SUN_RENDERING_ORDER;",
     "            SunTextures[0]->RenderingOrder = SUN_RENDERING_ORDER;"),
    ("tex_null_unguarded", SUC,
     "        if (SunTextures[i] != NULL) {\n            SunTextures[i]->RenderingOrder",
     "        if (1) {\n            SunTextures[i]->RenderingOrder"),
    ("tex_unload_four", SUC,
     "    for (i = 0; i < NUM_SUN_TEXTURES; i++) {\n        SunTextures[i] = NULL;",
     "    for (i = 1; i < NUM_SUN_TEXTURES; i++) {\n        SunTextures[i] = NULL;"),
    ("tex_unload_keeps", SUC,
     "        SunTextures[i] = NULL;\n", ""),
    # SunGlareInfo: LoaderSun fills it afresh for any version, and the
    # unloader leaves it be.
    ("glare_fill_none", SUC,
     "    fill_glare_info();\n    return 1;", "    return 1;"),
    ("glare_fill_good_only", SUC,
     "        SunPosition.z = info->PositionZ;\n    }\n    fill_glare_info();",
     "        SunPosition.z = info->PositionZ;\n        fill_glare_info();\n    }"),
    ("glare_fill_before_type", SUC,
     "    SunChunkInfoE *info;\n\n    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {",
     "    SunChunkInfoE *info;\n\n    fill_glare_info();\n    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {"),
    ("glare_unloader_clears", SUC,
     "    }\n    forget_sun();\n    return 1;",
     "    }\n    forget_sun();\n    memset(&SunGlareInfo, 0, sizeof SunGlareInfo);\n    return 1;"),
    ("glare_fill_no_memset", SUC,
     "    memset(g, 0, sizeof *g);\n", ""),
    ("glare_fill_version_0", SUC,
     "    g->Version = SUN_INFO_VERSION;", "    g->Version = 0;"),
    ("glare_fill_position", SUC,
     "    g->Version = SUN_INFO_VERSION;",
     "    g->Version = SUN_INFO_VERSION;\n    g->PositionX = 1.0f;"),
    ("glare_fill_blend", SUC,
     "    l->AlphaType        = SUNALPHA_ADD;", "    l->AlphaType        = SUNALPHA_BLEND;"),
    ("glare_fill_alpha_255", SUC,
     "    l->Colour[3]        = 128;", "    l->Colour[3]        = 255;"),
    ("glare_fill_halo", SUC,
     "    glare_layer(&g->SunLayers[1], SUNTEX_CENTER,",
     "    glare_layer(&g->SunLayers[1], SUNTEX_HALO,"),
    ("glare_fill_track_colour", SUC,
     "                130, 159, 122, 0, 0.0f);", "                130, 110, 25, 0, 0.0f);"),
    ("glare_fill_track_intensity", SUC,
     "    glare_layer(&g->SunLayers[3], SUNTEX_MAJORRAYS, 0.3f,",
     "    glare_layer(&g->SunLayers[3], SUNTEX_MAJORRAYS, 0.32f,"),
    ("glare_fill_offsets_swapped", SUC,
     "    glare_layer(&g->SunLayers[2], SUNTEX_MAJORRAYS, 0.7f, 800.0f, -9.0f,\n                28.0f,",
     "    glare_layer(&g->SunLayers[2], SUNTEX_MAJORRAYS, 0.7f, 800.0f, 28.0f,\n                -9.0f,"),
    ("glare_fill_no_angle", SUC,
     "                9.0f, 166, 119, 72, 16384, 0.2f);",
     "                9.0f, 166, 119, 72, 0, 0.2f);"),
    ("glare_fill_no_sweep", SUC,
     "                28.0f, 159, 122, 75, 0, 0.2f);",
     "                28.0f, 159, 122, 75, 0, 0.0f);"),
    ("glare_fill_three", SUC,
     "    glare_layer(&g->SunLayers[3], SUNTEX_MAJORRAYS, 0.3f, 800.0f, 28.0f,\n                9.0f, 166, 119, 72, 16384, 0.2f);\n",
     ""),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = {
    # The copy is a plain store, and eModel::Init neither reads nor writes
    # the matrices, so which comes first cannot show.
    "loader_fallback_copy_first",
    # The image stores SunInfo in the delay slot before the version check,
    # and the bad-version path clears it again, so storing it only on the
    # good path leaves the same state.
    "sun_info_after_check",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model(sc)
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

    sc = script()
    lines = model(sc)
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
