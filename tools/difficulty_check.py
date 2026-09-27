#!/usr/bin/env python3
"""Cross-check 3DS Files/source/difficultyinfo.c and .h against the retail
image, SLES_507.31.

**The calls.** The model runs retail's LoaderDifficultyInfo (0x0012ff68)
and UnloaderDifficultyInfo (0x0012ffb0) out of the image in
retail_model.RetailEmu, bMemCpy and all, and the harness
(tools/src/difficulty_test.c) runs difficultyinfo.c's. The chunks are:

  - retail GLOBALB.BUN's own 0x34b00;
  - that chunk under five other ids, each one bit or one byte off, the
    container bit among them;
  - a chunk whose every payload byte is its own;
  - the demo's GLOBALB.BUN chunk, 744 bytes, which the loader reads 248
    bytes past;
  - a chunk whose size field says 0.

Each chunk has 256 bytes of a pattern after it, which is what a copy that
runs past it reads. Between the loads the table is filled with a pattern,
so a load that should not copy shows. After each load the table is printed
field by field: the harness by name, the model at the offsets of LAYOUT.
The model also fails if the image writes anywhere but the table and the
stack. The harness prints the port's layout too, which must be LAYOUT.

**The image.** Retail's ELF has no .mdebug, so LAYOUT is taken from the
code that reads the table, and FACTS holds it to that code:

  - each fact is an instruction at its address in a named function, with
    the number it carries (an immediate, a lui/addiu pair's address less
    the table's, or a shift's scale) and the layout expression it must
    equal;
  - the scan finds every function that forms an address in the table's
    992 bytes, and the list must be READERS.

What this shows is in docs/formats/difficulty-info.md. In short, retail's
table is the demo's with DecideBoostFactor's two position tables moved in
at 240, and a second SkillLevelDistribution for races with no cops.

The catchup, the table's one reader in the port, is checked by
carmode_check on the demo image. It reads only TwoPlayerCatchup, whose four
knees are the same on both discs.

    python tools/difficulty_check.py
    python tools/difficulty_check.py --mutate [--only a,b]
    python tools/difficulty_check.py --dump out/difficulty
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mipsdis                          # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import s32                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/difficulty_test.c"
DIC = "3DS Files/source/difficultyinfo.c"
DIH = "3DS Files/source/difficultyinfo.h"
SOURCES = [HARNESS, DIC]
HARNESS_TIMEOUT = 20

DEMO_DIFF = 0x002e81c0                 # TheDifficultyInfo, the demo's
RETAIL_DIFF = 0x002f0080               # and retail's
SIZE = 992
DEMO_SIZE = 744
CHUNK = 0x00034b00
RETAIL_BUN = ROOT / "extracted-retail" / "GLOBAL" / "GLOBALB.BUN"
DEMO_BUN = ROOT / "extracted" / "GLOBAL" / "GLOBALB.BUN"
LOADER = "LoaderDifficultyInfo__FP6bChunk"
UNLOADER = "UnloaderDifficultyInfo__FP6bChunk"
TAIL = 256

# The port's layout, as the harness prints it, and the model's, which
# FACTS holds to retail's readers: (name, offset, size).
LAYOUT = [
    ("DifficultyInfo", 0, 992),
    ("DifficultyInfo.AIDistanceBoostLoSkill", 0, 56),
    ("DifficultyInfo.AIDistanceBoostHiSkill", 56, 56),
    ("DifficultyInfo.AIPositionBoostLoSkill", 112, 64),
    ("DifficultyInfo.AIPositionBoostHiSkill", 176, 64),
    ("DifficultyInfo.PositionRatioOverOne", 240, 64),
    ("DifficultyInfo.PositionRatioUnderOne", 304, 64),
    ("DifficultyInfo.AISkillLevel", 368, 280),
    ("DifficultyInfo.AINonExplicitMode", 648, 300),
    ("DifficultyInfo.TwoPlayerCatchup", 948, 32),
    ("DifficultyInfo.Misc", 980, 12),
    ("SkillLevelEntry", 0, 28),
    ("SkillLevelEntry.TakeSignChance", 0, 12),
    ("SkillLevelEntry.CollisionAvoidanceChance", 12, 4),
    ("SkillLevelEntry.SpeedFactor", 16, 4),
    ("SkillLevelEntry.SlowFactor", 20, 4),
    ("SkillLevelEntry.RoutePointVariance", 24, 1),
    ("SkillLevelEntry.pad", 25, 1),
    ("NonExplicitModeData", 0, 300),
    ("NonExplicitModeData.BoostScale", 0, 60),
    ("NonExplicitModeData.SkillLevelDistribution", 60, 240),
    ("MiscData", 0, 12),
    ("MiscData.RoutePointChangeFrequency", 0, 4),
    ("MiscData.BoostCalculationFrequency", 4, 4),
    ("MiscData.MaxDistanceForBoost", 8, 4),
]
OFF = {n: o for n, o, _s in LAYOUT}
SZ = {n: s for n, _o, s in LAYOUT}


def off(name):
    return OFF[name]


def size(name):
    return SZ[name]


# ================================================================ the calls

def pattern(k, n):
    return bytes((k * 37 + i * 11 + 5) & 0xff for i in range(n))


def disc_chunk(path, want_size):
    """The one 0x34b00 in a bundle, header and payload."""
    b = open(path, "rb").read()
    found = []

    def walk(o, end):
        while o + 8 <= end:
            cid, n = struct.unpack_from("<II", b, o)
            if cid == CHUNK:
                found.append(o)
            if cid & 0x80000000:
                walk(o + 8, o + 8 + n)
            o += 8 + n
    walk(0, len(b))
    assert len(found) == 1, (path, found)
    o = found[0]
    assert struct.unpack_from("<II", b, o) == (CHUNK, want_size)
    return b[o:o + 8 + want_size]


def with_id(c, cid):
    return struct.pack("<I", cid) + c[4:]


def chunks():
    r = disc_chunk(RETAIL_BUN, SIZE)
    d = disc_chunk(DEMO_BUN, DEMO_SIZE)
    tail = pattern(9, TAIL)
    return [
        r + tail,                                                # 0
        with_id(r, CHUNK ^ 1) + tail,                            # 1
        with_id(r, CHUNK ^ 0x100) + tail,                        # 2
        with_id(r, CHUNK ^ 0x10000) + tail,                      # 3
        with_id(r, CHUNK | 0x80000000) + tail,                   # 4
        with_id(r, 0) + tail,                                    # 5
        struct.pack("<II", CHUNK, SIZE) + bytes(
            (i * 7 + 3) & 0xff for i in range(SIZE)) + tail,     # 6
        d + tail,                                                # 7
        struct.pack("<II", CHUNK, 0) + pattern(6, SIZE) + tail,  # 8
    ]


BAD = (1, 2, 3, 4, 5)


def script():
    ops = ["Y", "P 1", "D"]
    ops += ["U %d" % k for k in range(9)]
    for k in BAD:
        ops += ["L %d" % k, "D"]
    ops += ["L 0", "D", "P 2", "L 6", "D", "P 3", "L 7", "D",
            "P 4", "L 8", "D", "L 0", "D"]
    for k in BAD:
        ops += ["L %d" % k]
    ops += ["D", "U 0"]
    return ops


class Model(object):
    def __init__(self, cs):
        e = retail_model.RetailEmu(ieee=True)
        self.e = e
        self.base = e.data(DEMO_DIFF)
        assert self.base == RETAIL_DIFF, hex(self.base)
        self.chunk = []
        for c in cs:
            p = e.alloc(len(c), 64)
            e.write(p, c)
            self.chunk.append(p)

    def call(self, sym, arg):
        e = self.e
        before = bytes(e.mem)
        sp = e.reg[29]
        r = e.call(sym, arg, limit=100000)
        a, b = self.base, self.base + SIZE
        lo = sp - 0x1000
        after = e.mem
        if (before[:a] != after[:a] or before[b:lo] != after[b:lo]
                or before[sp:] != after[sp:]):
            raise SystemExit("%s wrote outside the table" % sym)
        return r

    def dump(self):
        b = self.e.read(self.base, SIZE)
        out = []

        def words(name, o, n):
            ws = struct.unpack_from("<%dI" % n, b, o)
            out.append(name + "".join(" %08x" % w for w in ws))
        for f, n in (("AIDistanceBoostLoSkill", 14),
                     ("AIDistanceBoostHiSkill", 14),
                     ("AIPositionBoostLoSkill", 16),
                     ("AIPositionBoostHiSkill", 16),
                     ("PositionRatioOverOne", 16),
                     ("PositionRatioUnderOne", 16)):
            words(f, off("DifficultyInfo." + f), n)
        for i in range(10):
            o = off("DifficultyInfo.AISkillLevel") + i * size("SkillLevelEntry")
            t = o + off("SkillLevelEntry.TakeSignChance")
            ws = struct.unpack_from("<3I", b, t) + tuple(
                struct.unpack_from("<I", b, o + off("SkillLevelEntry." + f))[0]
                for f in ("CollisionAvoidanceChance", "SpeedFactor",
                          "SlowFactor"))
            v = o + off("SkillLevelEntry.RoutePointVariance")
            p = o + off("SkillLevelEntry.pad")
            out.append("AISkillLevel[%d] %s %02x %02x %02x%02x" % (
                i, " ".join("%08x" % w for w in ws), b[v], b[p], b[o + 26],
                b[o + 27]))
        nx = off("DifficultyInfo.AINonExplicitMode")
        bs = nx + off("NonExplicitModeData.BoostScale")
        for i in range(3):
            words("BoostScale[%d]" % i, bs + 20 * i, 5)
        sd = nx + off("NonExplicitModeData.SkillLevelDistribution")
        for c in range(2):
            for s in range(3):
                words("SkillLevelDistribution[%d][%d]" % (c, s),
                      sd + 120 * c + 40 * s, 10)
        words("TwoPlayerCatchup", off("DifficultyInfo.TwoPlayerCatchup"), 8)
        m = off("DifficultyInfo.Misc")
        out.append("Misc " + " ".join(
            "%08x" % struct.unpack_from("<I", b, m + off("MiscData." + f))[0]
            for f in ("RoutePointChangeFrequency", "BoostCalculationFrequency",
                      "MaxDistanceForBoost")))
        return out

    def run(self, ops):
        out = []
        for op in ops:
            if op == "Y":
                out.extend("layout %s %d %d" % x for x in LAYOUT)
            elif op.startswith("P "):
                self.e.write(self.base, pattern(int(op[2:]), SIZE))
            elif op.startswith("L "):
                k = int(op[2:])
                out.append("L %d -> %d" % (k, self.call(LOADER, self.chunk[k])))
            elif op.startswith("U "):
                k = int(op[2:])
                out.append("U %d -> %d" % (k, self.call(UNLOADER,
                                                         self.chunk[k])))
            elif op == "D":
                out.extend(self.dump())
        return out


def model(cs, ops):
    m = Model(cs)
    return m, m.run(ops)


# ================================================================ the image

# Every function that forms an address in the table.
READERS = [
    "CalculateDistanceAndPositionBoost__15AICarControllerP9RacingCarT1PfT3",
    "CalculateNewCatchupMultipliers__3Car",
    "DecideBoostFactor__15AICarController",
    "ExecuteCurrentAction__15AICarController",
    "LoaderDifficultyInfo__FP6bChunk",
    "SetupCarsForRace__16FrontendDatabase",
    "ShouldWeAvoidThisCar__8AIDriverP3Carf",
    "SignPostDecision__15AICarControllerP8SignpostPiP15DrivingLocation",
    "StartDemoDiscGame__16FrontendDatabase",
    "StartRace__16FrontendDatabase",
    "StartSkipFEGame__16FrontendDatabase",
]

LDI, UDI = "LoaderDifficultyInfo__FP6bChunk", "UnloaderDifficultyInfo__FP6bChunk"
CATCH = "CalculateNewCatchupMultipliers__3Car"
AVOID = "ShouldWeAvoidThisCar__8AIDriverP3Carf"
SIGN = "SignPostDecision__15AICarControllerP8SignpostPiP15DrivingLocation"
DECIDE = "DecideBoostFactor__15AICarController"
CDPB = "CalculateDistanceAndPositionBoost__15AICarControllerP9RacingCarT1PfT3"
EXEC = "ExecuteCurrentAction__15AICarController"
SKIP = "StartSkipFEGame__16FrontendDatabase"
DEMO = "StartDemoDiscGame__16FrontendDatabase"
START = "StartRace__16FrontendDatabase"
SETUP = "SetupCarsForRace__16FrontendDatabase"

SKL = "off('DifficultyInfo.AISkillLevel') + off('SkillLevelEntry.%s')"
MSC = "off('DifficultyInfo.Misc') + off('MiscData.%s')"
NXM = "off('DifficultyInfo.AINonExplicitMode') + off('NonExplicitModeData.%s')"

# (function, address, instruction, kind, claim). kind is how the number is
# read from the instruction: "text" none, "imm" its immediate, "abs" a lui
# 0x002f's address plus the immediate less the table's, "shl" 1 << its
# shift. claim is a layout expression the number must equal.
FACTS = [
    (LDI, 0x0012ff74, "lui    v0,0x0003", "text", None),
    (LDI, 0x0012ff78, "ori    v0,v0,0x4b00", "text", None),
    (LDI, 0x0012ff7c, "lw     v1,0(a1)", "text", None),
    (LDI, 0x0012ff88, "lui    a0,0x002f", "text", None),
    (LDI, 0x0012ff8c, "addiu  a1,a1,8", "text", None),
    (LDI, 0x0012ff90, "addiu  a0,a0,128", "abs", "off('DifficultyInfo')"),
    (LDI, 0x0012ff98, "addiu  a2,zero,992", "imm", "size('DifficultyInfo')"),
    (LDI, 0x0012ff9c, "addiu  v0,zero,1", "text", None),
    (UDI, 0x0012ffb0, "lw     v0,0(a0)", "text", None),
    (UDI, 0x0012ffb4, "lui    v1,0x0003", "text", None),
    (UDI, 0x0012ffb8, "ori    v1,v1,0x4b00", "text", None),
    (UDI, 0x0012ffbc, "xor    v0,v0,v1", "text", None),
    (UDI, 0x0012ffc4, "sltiu  v0,v0,1", "text", None),
    (CATCH, 0x00135230, "lui    a1,0x002f", "text", None),
    (CATCH, 0x00135238, "addiu  a1,a1,1076", "abs",
     "off('DifficultyInfo.TwoPlayerCatchup')"),
    (CATCH, 0x00135248, "addiu  a2,zero,4", "imm",
     "size('DifficultyInfo.TwoPlayerCatchup') // 8"),
    (AVOID, 0x0013082c, "addiu  a2,zero,28", "imm", "size('SkillLevelEntry')"),
    (AVOID, 0x00130830, "lui    v1,0x002f", "text", None),
    (AVOID, 0x00130838, "addiu  v1,v1,128", "abs", "off('DifficultyInfo')"),
    (AVOID, 0x00130850, "lwc1   $f1,380(v1)", "imm",
     SKL % "CollisionAvoidanceChance"),
    (SIGN, 0x00191fd0, "addiu  v1,zero,28", "imm", "size('SkillLevelEntry')"),
    (SIGN, 0x00191fd4, "lui    v0,0x002f", "text", None),
    (SIGN, 0x00191fdc, "addiu  v0,v0,496", "abs", SKL % "TakeSignChance"),
    (SIGN, 0x00191fe8, "lwc1   $f0,0(s0)", "imm", "0"),
    (SIGN, 0x00191ff8, "lwc1   $f0,4(s0)", "imm",
     "size('SkillLevelEntry.TakeSignChance') // 3"),
    (DECIDE, 0x00192994, "lui    s4,0x002f", "text", None),
    (DECIDE, 0x0019299c, "addiu  v1,s4,128", "abs", "off('DifficultyInfo')"),
    (DECIDE, 0x001929a0, "lwc1   $f1,984(v1)", "imm",
     MSC % "BoostCalculationFrequency"),
    (DECIDE, 0x00192b94, "addiu  v0,zero,28", "imm", "size('SkillLevelEntry')"),
    (DECIDE, 0x00192b98, "addiu  s3,s4,128", "abs", "off('DifficultyInfo')"),
    (DECIDE, 0x00192bb0, "lwc1   $f23,388(v0)", "imm", SKL % "SlowFactor"),
    # Position 1 is the first row, so the base is one row back.
    (DECIDE, 0x00192bf4, "addiu  v0,s3,232", "imm",
     "off('DifficultyInfo.PositionRatioOverOne') - 8"),
    (DECIDE, 0x00192bf8, "addiu  v0,s3,296", "imm",
     "off('DifficultyInfo.PositionRatioUnderOne') - 8"),
    (DECIDE, 0x00192bfc, "sll    a1,s0,3", "shl",
     "size('DifficultyInfo.PositionRatioOverOne') // 8"),
    (DECIDE, 0x00192c14, "addiu  a2,zero,2", "imm",
     "size('DifficultyInfo.PositionRatioUnderOne') // 8 // 4"),
    (CDPB, 0x00192d4c, "lui    v0,0x002f", "text", None),
    (CDPB, 0x00192d54, "addiu  s5,v0,128", "abs",
     "off('DifficultyInfo.AIDistanceBoostLoSkill')"),
    (CDPB, 0x00192d58, "lwc1   $f0,988(s5)", "imm", MSC % "MaxDistanceForBoost"),
    (CDPB, 0x00192d6c, "move   a1,s5", "text", None),
    (CDPB, 0x00192d7c, "addiu  a2,zero,7", "imm",
     "size('DifficultyInfo.AIDistanceBoostLoSkill') // 8"),
    (CDPB, 0x00192d84, "addiu  a1,s5,56", "imm",
     "off('DifficultyInfo.AIDistanceBoostHiSkill')"),
    (CDPB, 0x00192d90, "addiu  a2,zero,7", "imm",
     "size('DifficultyInfo.AIDistanceBoostHiSkill') // 8"),
    (CDPB, 0x00192e9c, "lwc1   $f15,176(v0)", "imm",
     "off('DifficultyInfo.AIPositionBoostHiSkill')"),
    (CDPB, 0x00192ea4, "lwc1   $f13,112(v1)", "imm",
     "off('DifficultyInfo.AIPositionBoostLoSkill')"),
    (EXEC, 0x00193434, "lui    s3,0x002f", "text", None),
    (EXEC, 0x00193440, "addiu  a1,s3,128", "abs", "off('DifficultyInfo')"),
    (EXEC, 0x0019344c, "lwc1   $f1,980(a1)", "imm",
     MSC % "RoutePointChangeFrequency"),
    (EXEC, 0x00193470, "addiu  v0,zero,28", "imm", "size('SkillLevelEntry')"),
    (EXEC, 0x0019347c, "lbu    s0,392(v0)", "imm", SKL % "RoutePointVariance"),
    (SKIP, 0x00184cbc, "lui    a1,0x002f", "text", None),
    (SKIP, 0x00184ccc, "addiu  a1,a1,128", "abs", "off('DifficultyInfo')"),
    (SKIP, 0x00184cec, "addiu  a1,a1,648", "imm",
     "off('DifficultyInfo.AINonExplicitMode')"),
    (DEMO, 0x00184f14, "addiu  a0,zero,20", "imm",
     "size('NonExplicitModeData.BoostScale') // 3"),
    (DEMO, 0x00184f1c, "lui    v1,0x002f", "text", None),
    (DEMO, 0x00184f24, "addiu  v1,v1,128", "abs", "off('DifficultyInfo')"),
    (DEMO, 0x00184f48, "lwc1   $f0,648(v1)", "imm", NXM % "BoostScale"),
    (START, 0x00185158, "lui    s2,0x002f", "text", None),
    (START, 0x001851b0, "addiu  v0,zero,20", "imm",
     "size('NonExplicitModeData.BoostScale') // 3"),
    (START, 0x001851b4, "addiu  t0,s2,128", "abs", "off('DifficultyInfo')"),
    (START, 0x001851e4, "lwc1   $f0,648(t0)", "imm", NXM % "BoostScale"),
    # TheRaceParameters.nMaxCops < 1 picks the second set.
    (SETUP, 0x00185a94, "lw     v0,604(s0)", "text", None),
    (SETUP, 0x00185aa4, "slti   s2,v0,1", "text", None),
    (SETUP, 0x00185aa8, "lw     v1,756(s0)", "text", None),
    (SETUP, 0x00185aac, "addiu  a1,zero,40", "imm",
     "size('NonExplicitModeData.SkillLevelDistribution') // 6"),
    (SETUP, 0x00185ab0, "addiu  v0,zero,120", "imm",
     "size('NonExplicitModeData.SkillLevelDistribution') // 2"),
    (SETUP, 0x00185ab4, "lui    t1,0x002f", "text", None),
    (SETUP, 0x00185ac0, "addiu  a0,t1,128", "abs", "off('DifficultyInfo')"),
    (SETUP, 0x00185ad0, "lwc1   $f0,708(a0)", "imm",
     NXM % "SkillLevelDistribution"),
]

# Opcodes that take a base register and a signed offset.
BASED = {0x09, 0x1a, 0x1b, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25,
         0x26, 0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x31, 0x36,
         0x37, 0x39, 0x3e, 0x3f}


def references(elf, base, n):
    """Every function with a lui and then an addiu, load or store off that
    register, within 24 words, landing in [base, base + n)."""
    found = set()
    for s in elf.secs:
        if s["type"] != 1 or not (s["flags"] & 4) or not s["addr"]:
            continue
        d = elf.data[s["off"]:s["off"] + s["size"]]
        k = len(d) // 4
        ws = struct.unpack("<%dI" % k, d[:4 * k])
        for i, w in enumerate(ws):
            if w >> 26 != 0x0f:
                continue
            rt, hi = (w >> 16) & 31, (w & 0xffff) << 16
            for j in range(i + 1, min(k, i + 24)):
                x = ws[j]
                op, rs_, rt_ = x >> 26, (x >> 21) & 31, (x >> 16) & 31
                if op in BASED and rs_ == rt:
                    imm = x & 0xffff
                    a = (hi + imm - (0x10000 if imm & 0x8000 else 0)) & 0xffffffff
                    if base <= a < base + n:
                        pc = s["addr"] + 4 * j
                        found.add((elf.label(pc) or "?%08x" % pc).split("+")[0])
                if op == 0 and ((x >> 11) & 31) == rt:
                    break
                if op in (0x09, 0x0d, 0x0f, 0x20, 0x23, 0x24, 0x37) and rt_ == rt:
                    break
    return found


def image_facts(e, layout=None):
    """[(ok, line)]. layout, if given, is the harness's, and the claims are
    evaluated over it; otherwise over LAYOUT."""
    lay = layout if layout is not None else {n: (o, s) for n, o, s in LAYOUT}
    env = {"off": lambda n: lay[n][0], "size": lambda n: lay[n][1]}
    elf = e.elf
    out = []
    for fn, a, text, kind, claim in FACTS:
        w = struct.unpack("<I", elf.read(a, 4))[0]
        got = mipsdis.decode(w, a, None)[0]
        where = (elf.label(a) or "?").split("+")[0]
        line = "fact %08x %-22s %s" % (a, got, fn.split("__")[0])
        ok = got == text and where == fn
        if kind != "text":
            imm = s32(((w & 0xffff) ^ 0x8000) - 0x8000)
            if kind == "imm":
                v = imm
            elif kind == "abs":
                v = 0x002f0000 + imm - RETAIL_DIFF
            else:
                v = 1 << ((w >> 6) & 31)
            want = eval(claim, env)
            ok = ok and v == want
            line += " %d = %s" % (v, claim)
        if got != text:
            line += " (expected %s)" % text
        if where != fn:
            line += " (in %s)" % where
        out.append((ok, line))
    found = references(elf, RETAIL_DIFF, SIZE)
    for nm in sorted(found | set(READERS)):
        ok = nm in found and nm in READERS
        out.append((ok, "reader %s%s" % (
            nm, "" if ok else (" MISSING" if nm not in found else " UNLISTED"))))
    return out


def harness_layout(lines):
    lay = {}
    for l in lines:
        if l.startswith("layout "):
            _, n, o, s = l.split()
            lay[n] = (int(o), int(s))
    return lay


# ============================================================== the harness

def build_harness(tmp, name="difficulty_test"):
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


def encode(cs, ops):
    lines = ["C %d %d %s" % (k, len(c), c.hex()) for k, c in enumerate(cs)]
    return NL.join(lines + ops) + NL


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    ("dl-no-id-test", DIC,
     "    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)" + NL + "        return 0;"
     + NL, ""),
    ("dl-id", DIH, "#define DIFFICULTYINFO_CHUNK 0x00034b00u",
     "#define DIFFICULTYINFO_CHUNK 0x00034b01u"),
    ("dl-id-low-half", DIC, "    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)",
     "    if ((chunk_id(chunk) & 0xffff) != (DIFFICULTYINFO_CHUNK & 0xffff))"),
    ("dl-id-no-container", DIC,
     "    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)",
     "    if ((chunk_id(chunk) & 0x7fffffffu) != DIFFICULTYINFO_CHUNK)"),
    ("dl-id-byte", DIC, "    memcpy(&id, chunk, 4);",
     "    id = chunk[0] | (uint32_t)chunk[1] << 8 | (uint32_t)chunk[2] << 16;"),
    ("dl-answers-0", DIC, "    return 1;", "    return 0;"),
    ("dl-header-4", DIC, "chunk + 8,", "chunk + 4,"),
    ("dl-header-12", DIC, "chunk + 8,", "chunk + 12,"),
    ("dl-short", DIC, "sizeof TheDifficultyInfo);",
     "sizeof TheDifficultyInfo - 4);"),
    ("dl-demo-size", DIC, "sizeof TheDifficultyInfo);", "744);"),
    ("dl-chunk-size", DIC,
     "    memcpy(&TheDifficultyInfo, chunk + 8, sizeof TheDifficultyInfo);",
     "    {" + NL + "        uint32_t n;" + NL + NL
     + "        memcpy(&n, chunk + 4, 4);" + NL
     + "        memcpy(&TheDifficultyInfo, chunk + 8," + NL
     + "               n < sizeof TheDifficultyInfo ? n"
     + " : sizeof TheDifficultyInfo);" + NL + "    }"),
    ("dl-clears-first", DIC,
     "    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)" + NL + "        return 0;",
     "    memset(&TheDifficultyInfo, 0, sizeof TheDifficultyInfo);" + NL
     + "    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)" + NL + "        return 0;"),
    ("ul-inverted", DIC, "    return chunk_id(chunk) == DIFFICULTYINFO_CHUNK;",
     "    return chunk_id(chunk) != DIFFICULTYINFO_CHUNK;"),
    ("ul-always", DIC, "    return chunk_id(chunk) == DIFFICULTYINFO_CHUNK;",
     "    return 1;"),
    ("ul-clears", DIC, "    return chunk_id(chunk) == DIFFICULTYINFO_CHUNK;",
     "    if (chunk_id(chunk) == DIFFICULTYINFO_CHUNK)" + NL
     + "        memset(&TheDifficultyInfo, 0, sizeof TheDifficultyInfo);" + NL
     + "    return chunk_id(chunk) == DIFFICULTYINFO_CHUNK;"),
    # The layout: each is a struct the size check alone would pass.
    ("ly-ratios-swapped", DIH,
     "    float               PositionRatioOverOne[8][2]; // 240" + NL
     + "    float               PositionRatioUnderOne[8][2];// 304",
     "    float               PositionRatioUnderOne[8][2];// 240" + NL
     + "    float               PositionRatioOverOne[8][2]; // 304"),
    ("ly-ratios-after-skill", DIH,
     "    float               PositionRatioOverOne[8][2]; // 240" + NL
     + "    float               PositionRatioUnderOne[8][2];// 304" + NL
     + "    SkillLevelEntry     AISkillLevel[10];           // 368",
     "    SkillLevelEntry     AISkillLevel[10];           // 368" + NL
     + "    float               PositionRatioOverOne[8][2]; // 240" + NL
     + "    float               PositionRatioUnderOne[8][2];// 304"),
    # [OpponentStrength][cops] rather than [cops][OpponentStrength].
    ("ly-distribution-index", DIH,
     "    float    SkillLevelDistribution[2][3][10];  //  60",
     "    float    SkillLevelDistribution[3][2][10];  //  60"),
    ("ly-distribution-first", DIH,
     "    float    BoostScale[3][5];                  //   0" + NL
     + "    float    SkillLevelDistribution[2][3][10];  //  60",
     "    float    SkillLevelDistribution[2][3][10];  //  60" + NL
     + "    float    BoostScale[3][5];                  //   0"),
    ("ly-catchup-misc", DIH,
     "    bVector2            TwoPlayerCatchup[4];        // 948" + NL
     + "    MiscData            Misc;                       // 980",
     "    MiscData            Misc;                       // 980" + NL
     + "    bVector2            TwoPlayerCatchup[4];        // 948"),
    ("ly-misc-order", DIH,
     "    float    RoutePointChangeFrequency;         //  0" + NL
     + "    float    BoostCalculationFrequency;         //  4",
     "    float    BoostCalculationFrequency;         //  4" + NL
     + "    float    RoutePointChangeFrequency;         //  0"),
    ("ly-skill-order", DIH,
     "    float    SpeedFactor;                       // 16" + NL
     + "    float    SlowFactor;                        // 20",
     "    float    SlowFactor;                        // 20" + NL
     + "    float    SpeedFactor;                       // 16"),
    ("ly-variance-pad", DIH,
     "    uint8_t  RoutePointVariance;                // 24" + NL
     + "    uint8_t  pad;                               // 25",
     "    uint8_t  pad;                               // 25" + NL
     + "    uint8_t  RoutePointVariance;                // 24"),
    ("ly-boost-lo-hi", DIH,
     "    bVector2            AIDistanceBoostLoSkill[7];  //   0" + NL
     + "    bVector2            AIDistanceBoostHiSkill[7];  //  56",
     "    bVector2            AIDistanceBoostHiSkill[7];  //  56" + NL
     + "    bVector2            AIDistanceBoostLoSkill[7];  //   0"),
]

# Mutations that survive because they change nothing the image can tell.
EQUIVALENT = set()


def strip_check(text):
    """The header without its layout check, so a layout mutation reaches
    the transcript rather than stopping the build."""
    a = text.find("typedef char difficultyinfo_layout_check[")
    b = text.find("];", a)
    return text[:a] + text[b + 2:]


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    cs, sc = chunks(), script()
    _m, base = model(cs, sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(cs, sc))
    hpath = ROOT / DIH
    htext = hpath.read_text(encoding="utf-8", newline="")
    try:
        # The layout check would stop every layout mutation at the build.
        hostbuild.write_source(hpath, strip_check(htext))
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
    finally:
        try:
            hostbuild.write_source(hpath, htext)
        except OSError:
            sys.exit("could not restore %s -- its layout check is stripped. "
                     "Put it back before trusting anything printed above."
                     % DIH)
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

    cs, sc = chunks(), script()
    m, lines = model(cs, sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(cs, sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()
    # The facts over LAYOUT and over the port's own layout: the first holds
    # the model to the image, the second the port.
    facts = image_facts(m.e)
    port = image_facts(m.e, harness_layout(harness))

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    pbad = [l for ok, l in port if not ok]
    for l in bad:
        print("image: " + l)
    for l in pbad:
        print("port: " + l)
    nf = sum(1 for _ok, l in facts if l.startswith("fact "))
    nr = sum(1 for _ok, l in facts if l.startswith("reader "))
    n = diff(lines, harness)
    print("image: %d facts, %d readers, %d wrong" % (nf, nr, len(bad)))
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad or pbad) else 0)


if __name__ == "__main__":
    main()
