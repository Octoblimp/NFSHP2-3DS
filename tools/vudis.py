"""COP2 / VU0 macro-mode decoding for tools/mipsdis.py.

The EE runs VU0 in two ways. Micro mode is a program uploaded to VU0's own
memory; macro mode is the one bWare's C++ uses everywhere, where VU
instructions sit in the EE's own instruction stream as COP2 opcodes and the
compiler schedules them like any other. mipsdis printed those as
`cop2 0x4be20858` because the geometry code only ever used them to feed VU1
and the words did not need reading. The camera, the car sim and the collision
code are a different matter: every vector operation in them is a COP2 word,
so a listing without these decoded is a listing of nothing.

Encoding, following the EE core manual:

    31..26  010010            COP2
    25      CO                1 = a VU instruction, 0 = a transfer or branch
    24..21  X Y Z W           the destination field mask
    20..16  ft                (also vit, and the *destination* of ITOF/FTOI)
    15..11  fs                (also vis)
    10..6   fd                (also the 5-bit immediate of VIADDI)
    5..0    function

Functions 0x3c..0x3f are an escape into a second table, indexed the way the
hardware does it -- `(w & 3) | ((w >> 4) & 0x7c)` -- which interleaves the
low two function bits with bits 10..6 rather than concatenating them. Get
that wrong and VNOP decodes as VISWR, which is how you end up believing the
compiler emitted a store into a register it never read.

    python tools/vudis.py --self-check
    python tools/vudis.py 0x4be20858 0x4a6103be
"""
import sys

VF = ["vf%02d" % i for i in range(32)]
VI = ["vi%02d" % i for i in range(32)]
BC = "xyzw"


def _base_table():
    """function -> (mnemonic, form) for the CO == 1 instructions below 0x3c."""
    t = {}
    for i, name in enumerate(("vadd", "vsub", "vmadd", "vmsub", "vmax",
                              "vmini", "vmul")):
        for b in range(4):
            t[i * 4 + b] = (name + BC[b], "bc")
    t[0x1c] = ("vmulq", "q")
    t[0x1d] = ("vmaxi", "i")
    t[0x1e] = ("vmuli", "i")
    t[0x1f] = ("vminii", "i")
    t[0x20] = ("vaddq", "q")
    t[0x21] = ("vmaddq", "q")
    t[0x22] = ("vaddi", "i")
    t[0x23] = ("vmaddi", "i")
    t[0x24] = ("vsubq", "q")
    t[0x25] = ("vmsubq", "q")
    t[0x26] = ("vsubi", "i")
    t[0x27] = ("vmsubi", "i")
    t[0x28] = ("vadd", "ft")
    t[0x29] = ("vmadd", "ft")
    t[0x2a] = ("vmul", "ft")
    t[0x2b] = ("vmax", "ft")
    t[0x2c] = ("vsub", "ft")
    t[0x2d] = ("vmsub", "ft")
    t[0x2e] = ("vopmsub", "ft")
    t[0x2f] = ("vmini", "ft")
    t[0x30] = ("viadd", "int")
    t[0x31] = ("visub", "int")
    t[0x32] = ("viaddi", "iaddi")
    t[0x34] = ("viand", "int")
    t[0x35] = ("vior", "int")
    t[0x38] = ("vcallms", "callms")
    t[0x39] = ("vcallmsr", "callmsr")
    return t


def _special2_table():
    """The 0x3c..0x3f escape table, indexed as the hardware indexes it."""
    t = {}
    for i, name in enumerate(("vadda", "vsuba", "vmadda", "vmsuba")):
        for b in range(4):
            t[i * 4 + b] = (name + BC[b], "acc_bc")
    for i, q in enumerate(("0", "4", "12", "15")):
        t[0x10 + i] = ("vitof" + q, "cvt")
        t[0x14 + i] = ("vftoi" + q, "cvt")
    for b in range(4):
        t[0x18 + b] = ("vmula" + BC[b], "acc_bc")
    t[0x1c] = ("vmulaq", "acc_q")
    t[0x1d] = ("vabs", "cvt")
    t[0x1e] = ("vmulai", "acc_i")
    t[0x1f] = ("vclipw", "clip")
    t[0x20] = ("vaddaq", "acc_q")
    t[0x21] = ("vmaddaq", "acc_q")
    t[0x22] = ("vaddai", "acc_i")
    t[0x23] = ("vmaddai", "acc_i")
    t[0x24] = ("vsubaq", "acc_q")
    t[0x25] = ("vmsubaq", "acc_q")
    t[0x26] = ("vsubai", "acc_i")
    t[0x27] = ("vmsubai", "acc_i")
    t[0x28] = ("vadda", "acc_ft")
    t[0x29] = ("vmadda", "acc_ft")
    t[0x2a] = ("vmula", "acc_ft")
    t[0x2c] = ("vsuba", "acc_ft")
    t[0x2d] = ("vmsuba", "acc_ft")
    t[0x2e] = ("vopmula", "acc_ft")
    t[0x2f] = ("vnop", "none")
    t[0x30] = ("vmove", "cvt")
    t[0x31] = ("vmr32", "cvt")
    t[0x34] = ("vlqi", "lqi")
    t[0x35] = ("vsqi", "sqi")
    t[0x36] = ("vlqd", "lqd")
    t[0x37] = ("vsqd", "sqd")
    t[0x38] = ("vdiv", "div")
    t[0x39] = ("vsqrt", "sqrt")
    t[0x3a] = ("vrsqrt", "div")
    t[0x3b] = ("vwaitq", "none")
    t[0x3c] = ("vmtir", "mtir")
    t[0x3d] = ("vmfir", "mfir")
    t[0x3e] = ("vilwr", "ilwr")
    t[0x3f] = ("viswr", "ilwr")
    t[0x40] = ("vrnext", "rnext")
    t[0x41] = ("vrget", "rnext")
    t[0x42] = ("vrinit", "rinit")
    t[0x43] = ("vrxor", "rinit")
    return t


BASE = _base_table()
SPECIAL2 = _special2_table()


def dest(w):
    """The XYZW mask as the assembler spells it. Bit 24 is x, bit 21 is w."""
    s = "".join(c for i, c in enumerate("xyzw") if w & (1 << (24 - i)))
    return s or "none"


def decode(w):
    """One COP2 word -> a string, or None if the word is not COP2 at all."""
    if (w >> 26) != 0x12:
        return None
    ft, fs, fd = (w >> 16) & 0x1f, (w >> 11) & 0x1f, (w >> 6) & 0x1f
    if not (w >> 25) & 1:
        return _transfer(w, ft, fs)

    fn = w & 0x3f
    if fn >= 0x3c:
        entry = SPECIAL2.get((w & 3) | ((w >> 4) & 0x7c))
    else:
        entry = BASE.get(fn)
    if entry is None:
        return "cop2   0x%08x" % w
    name, form = entry
    d = dest(w)
    fsf, ftf = (w >> 21) & 3, (w >> 23) & 3

    if form == "bc":
        return "%-9s %s,%s,%s%s" % (name + "." + d, VF[fd], VF[fs],
                                    VF[ft], BC[fn & 3])
    if form == "ft":
        return "%-9s %s,%s,%s" % (name + "." + d, VF[fd], VF[fs], VF[ft])
    if form in ("q", "i"):
        return "%-9s %s,%s,%s" % (name + "." + d, VF[fd], VF[fs], form.upper())
    if form == "acc_bc":
        return "%-9s ACC,%s,%s%s" % (name + "." + d, VF[fs], VF[ft], BC[w & 3])
    if form == "acc_ft":
        return "%-9s ACC,%s,%s" % (name + "." + d, VF[fs], VF[ft])
    if form in ("acc_q", "acc_i"):
        return "%-9s ACC,%s,%s" % (name + "." + d, VF[fs], form[-1].upper())
    if form == "cvt":                       # ft is the destination here
        return "%-9s %s,%s" % (name + "." + d, VF[ft], VF[fs])
    if form == "clip":
        return "%-9s %s,%sw" % (name + ".xyz", VF[fs], VF[ft])
    if form == "int":
        return "%-9s %s,%s,%s" % (name, VI[fd], VI[fs], VI[ft])
    if form == "iaddi":
        imm = fd - 32 if fd & 0x10 else fd
        return "%-9s %s,%s,%d" % (name, VI[ft], VI[fs], imm)
    if form == "none":
        return name
    if form == "div":
        return "%-9s Q,%s%s,%s%s" % (name, VF[fs], BC[fsf], VF[ft], BC[ftf])
    if form == "sqrt":
        return "%-9s Q,%s%s" % (name, VF[ft], BC[ftf])
    if form in ("lqi", "lqd"):
        step = "++" if form == "lqi" else "--"
        return "%-9s %s,(%s%s)" % (name + "." + d, VF[ft], VI[fs], step)
    if form in ("sqi", "sqd"):
        step = "++" if form == "sqi" else "--"
        return "%-9s %s,(%s%s)" % (name + "." + d, VF[fs], VI[ft], step)
    if form == "mtir":
        return "%-9s %s,%s%s" % (name, VI[ft], VF[fs], BC[fsf])
    if form == "mfir":
        return "%-9s %s,%s" % (name + "." + d, VF[ft], VI[fs])
    if form == "ilwr":
        return "%-9s %s,(%s)" % (name + "." + d, VI[ft], VI[fs])
    if form == "callms":
        return "%-9s 0x%04x" % (name, (w >> 6) & 0x7fff)
    if form == "callmsr":
        return "%-9s CMSAR0" % name
    if form == "rnext":
        return "%-9s %s,R" % (name + "." + d, VF[ft])
    if form == "rinit":
        return "%-9s R,%s%s" % (name, VF[fs], BC[fsf])
    return "cop2   0x%08x" % w


_GPR = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
        "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
        "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
        "t8", "t9", "k0", "k1", "gp", "sp", "s8", "ra"]


def _transfer(w, ft, fs):
    """CO == 0: the GPR/VU moves and the coprocessor branch."""
    rs, rt = (w >> 21) & 0x1f, ft
    tail = ".i" if w & 1 else ""
    if rs == 1:
        return "%-9s %s,%s" % ("qmfc2" + tail, _GPR[rt], VF[fs])
    if rs == 5:
        return "%-9s %s,%s" % ("qmtc2" + tail, _GPR[rt], VF[fs])
    if rs == 2:
        return "%-9s %s,%s" % ("cfc2" + tail, _GPR[rt], VI[fs])
    if rs == 6:
        return "%-9s %s,%s" % ("ctc2" + tail, _GPR[rt], VI[fs])
    if rs == 8:
        off = w & 0xffff
        if off & 0x8000:
            off -= 0x10000
        name = ("bc2f", "bc2t", "bc2fl", "bc2tl")[rt & 3]
        return "%-9s %+d" % (name, 4 + off * 4)
    return "cop2   0x%08x" % w


# Words lifted straight out of Camera::SetCameraMatrix (0x00153ba0), with what
# the scalar code around them proves they have to be: a scalar broadcast and
# multiply, a negate through vf00, an inverse square root with its wait, and
# the three-term dot product that feeds it. If a table edit breaks one of
# these the decoder is wrong in a way that would otherwise only turn up much
# later, as a misreading of the game.
SELF_CHECK = [
    (0x48a21000, "qmtc2     v0,vf02"),
    (0x4be20858, "vmulx.xyzw vf01,vf01,vf02x"),
    (0x4be200ac, "vsub.xyzw vf02,vf00,vf02"),
    (0x4a6103be, "vrsqrt    Q,vf00w,vf01x"),
    (0x4a0003bf, "vwaitq"),
    (0x4b000060, "vaddq.x   vf01,vf00,Q"),
    (0x4a0002ff, "vnop"),
    (0x4be118d8, "vmulx.xyzw vf03,vf03,vf01x"),
    (0x4bc3192a, "vmul.xyz  vf04,vf03,vf03"),
    (0x4b042041, "vaddy.x   vf01,vf04,vf04y"),
    (0x4b040842, "vaddz.x   vf01,vf01,vf04z"),
    (0x4be2086c, "vsub.xyzw vf01,vf01,vf02"),
    (0x4be110a8, "vadd.xyzw vf02,vf02,vf01"),
    (0x4be3086c, "vsub.xyzw vf01,vf01,vf03"),
    (0x4be41098, "vmulx.xyzw vf02,vf02,vf04x"),
    (0x4be40858, "vmulx.xyzw vf01,vf01,vf04x"),
]


def self_check():
    bad = 0
    for w, want in SELF_CHECK:
        got = decode(w)
        if got != want:
            print("0x%08x -> %r, expected %r" % (w, got, want))
            bad += 1
    if bad:
        print("%d of %d wrong" % (bad, len(SELF_CHECK)))
        return 1
    print("vudis: %d words decode as expected" % len(SELF_CHECK))
    return 0


def survey():
    """Decode every COP2 word in .text and report what the game actually uses.

    The self-check proves sixteen words; this proves there is no hole in the
    tables, because a function code with no entry prints as the raw word and
    is counted here. It also says which instructions matter: an opcode the
    disc never emits is one nobody has to get right."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mipsdis
    import struct as _s

    elf = mipsdis.Elf()
    # SHF_EXECINSTR, with file bytes behind it: the one .text of this image.
    sec = [x for x in elf.secs
           if x["flags"] & 4 and x["type"] != 8 and x["size"]][0]
    blob = elf.read(sec["addr"], sec["size"])
    words = _s.unpack("<%dI" % (len(blob) // 4), blob[:len(blob) // 4 * 4])
    hist, raw = {}, 0
    for w in words:
        if (w >> 26) != 0x12:
            continue
        t = decode(w)
        if t.startswith("cop2   0x"):
            raw += 1
            hist["<undecoded>"] = hist.get("<undecoded>", 0) + 1
            continue
        hist[t.split()[0].split(".")[0]] = hist.get(t.split()[0].split(".")[0], 0) + 1
    total = sum(hist.values())
    for name, n in sorted(hist.items(), key=lambda kv: -kv[1]):
        print("  %-10s %6d" % (name, n))
    print("%d COP2 words in .text, %d distinct mnemonics, %d undecoded"
          % (total, len(hist), raw))
    return 1 if raw else 0


def main(argv):
    if "--self-check" in argv:
        return self_check()
    if "--survey" in argv:
        return survey()
    if not argv:
        print(__doc__)
        return 0
    for a in argv:
        w = int(a, 0)
        print("0x%08x  %s" % (w, decode(w)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
