#!/usr/bin/env python3
r"""VU1 micro-mode disassembler for the strip renderer's microprogram.

tools/vudis.py decodes COP2 words, which is VU0 in macro mode. The program
that draws every strip on the disc is VU1 code in micro mode: 64-bit
instruction pairs, an upper (FMAC) half and a lower (FDIV/LSU/IALU/branch)
half issued together. The image carries it between `vu1MicroCodeStart` and
`vu1MicroCodeEnd` (demo 0x0028a070..0x0028d4e0) as the DMA list
DownloadVUCode sends: a DMA tag, then VIF codes, the MPGs among them each
followed by its instructions and naming the VU address they load at.

So the listing is by VU address, which is what MSCAL, B and the program's
own JR targets use, with the demo's `_$` labels (its .symtab names every
routine: vuiReferenceLighter, vuiSphericalEnvMapper, ...) put where their
ELF address lands.

Encoding, following the VU user's manual:

    upper  63 I  62 E  61 M  60 D  59 T    56..53 dest  52..48 ft
           47..43 fs  42..38 fd  37..32 function -- the COP2 CO=1 table
    lower  31..25 opcode; 0x40 is the register form, whose function in
           5..0 escapes at 0x3c..0x3f the way the upper's does

With I set, the lower word is a float the upper's I operand reads (LOI).

    python tools/vu1dis.py                 # the demo's whole program
    python tools/vu1dis.py --from vuiReferenceLighter --count 80
    python tools/vu1dis.py --retail        # retail's, labels matched in
    python tools/vu1dis.py --self-check
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mipsdis                                  # noqa: E402
import vudis                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RETAIL = ROOT / "PS2 Files" / "Full Game" / "SLES_507.31"

VF, VI, BC = vudis.VF, vudis.VI, vudis.BC


def _s11(w):
    v = w & 0x7ff
    return v - 0x800 if v & 0x400 else v


def _upper(w):
    fn = w & 0x3f
    ft, fs, fd = (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31
    d = vudis.dest(w)
    if fn >= 0x3c:
        e = vudis.SPECIAL2.get((w & 3) | ((w >> 4) & 0x7c))
    else:
        e = vudis.BASE.get(fn)
    if e is None or e[1] in ("int", "iaddi", "callms", "callmsr"):
        return "upper? 0x%08x" % w
    name, form = e
    name = name[1:]                             # vmul -> mul
    if form == "bc":
        return "%s.%s %s,%s,%s%s" % (name, d, VF[fd], VF[fs], VF[ft], BC[fn & 3])
    if form == "ft":
        return "%s.%s %s,%s,%s" % (name, d, VF[fd], VF[fs], VF[ft])
    if form in ("q", "i"):
        return "%s.%s %s,%s,%s" % (name, d, VF[fd], VF[fs], form.upper())
    if form == "acc_bc":
        return "%s.%s ACC,%s,%s%s" % (name, d, VF[fs], VF[ft], BC[w & 3])
    if form == "acc_ft":
        return "%s.%s ACC,%s,%s" % (name, d, VF[fs], VF[ft])
    if form in ("acc_q", "acc_i"):
        return "%s.%s ACC,%s,%s" % (name, d, VF[fs], form[-1].upper())
    if form == "cvt" and name in ("itof0", "itof4", "itof12", "itof15",
                                  "ftoi0", "ftoi4", "ftoi12", "ftoi15", "abs"):
        return "%s.%s %s,%s" % (name, d, VF[ft], VF[fs])
    if form == "clip":
        return "clipw.xyz %s,%sw" % (VF[fs], VF[ft])
    if form == "none":
        return "nop"
    return "upper? 0x%08x" % w


_LOWER_OP = {
    0x30: "iadd", 0x31: "isub", 0x34: "iand", 0x35: "ior",
}
_LOWER_SPECIAL = {
    0x30: "move", 0x31: "mr32", 0x34: "lqi", 0x35: "sqi", 0x36: "lqd",
    0x37: "sqd", 0x38: "div", 0x39: "sqrt", 0x3a: "rsqrt", 0x3b: "waitq",
    0x3c: "mtir", 0x3d: "mfir", 0x3e: "ilwr", 0x3f: "iswr", 0x40: "rnext",
    0x41: "rget", 0x42: "rinit", 0x43: "rxor", 0x64: "mfp", 0x68: "xtop",
    0x69: "xitop", 0x6c: "xgkick", 0x70: "esadd", 0x71: "ersadd",
    0x72: "eleng", 0x73: "erleng", 0x74: "eatanxy", 0x75: "eatanxz",
    0x76: "esum", 0x78: "esqrt", 0x79: "ersqrt", 0x7a: "ercpr",
    0x7b: "waitp", 0x7c: "esin", 0x7d: "eatan", 0x7e: "eexp",
}
_BRANCH = {0x20: "b", 0x21: "bal", 0x28: "ibeq", 0x29: "ibne",
           0x2c: "ibltz", 0x2d: "ibgtz", 0x2e: "iblez", 0x2f: "ibgez"}


def _lower(w, pc):
    """`pc` is the pair's VU address in bytes, for branch targets."""
    op = w >> 25
    it, is_, fd = (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31
    ft, fs = it, is_
    d = vudis.dest(w)
    fsf, ftf = (w >> 21) & 3, (w >> 23) & 3
    if op == 0x40:
        fn = w & 0x3f
        if fn in _LOWER_OP:
            return "%s %s,%s,%s" % (_LOWER_OP[fn], VI[fd], VI[is_], VI[it])
        if fn == 0x32:
            imm = fd - 32 if fd & 0x10 else fd
            return "iaddi %s,%s,%d" % (VI[it], VI[is_], imm)
        if fn < 0x3c:
            return "lower? 0x%08x" % w
        x = (w & 3) | ((w >> 4) & 0x7c)
        name = _LOWER_SPECIAL.get(x)
        if name is None:
            return "lower? 0x%08x" % w
        if name == "move":
            if d == "none" and ft == 0 and fs == 0:
                return "nop"
            return "move.%s %s,%s" % (d, VF[ft], VF[fs])
        if name == "mr32":
            return "mr32.%s %s,%s" % (d, VF[ft], VF[fs])
        if name in ("lqi", "lqd"):
            return "%s.%s %s,(%s%s)" % (name, d, VF[ft], VI[is_],
                                        "++" if name == "lqi" else "--")
        if name in ("sqi", "sqd"):
            return "%s.%s %s,(%s%s)" % (name, d, VF[fs], VI[it],
                                        "++" if name == "sqi" else "--")
        if name in ("div", "rsqrt"):
            return "%s Q,%s%s,%s%s" % (name, VF[fs], BC[fsf], VF[ft], BC[ftf])
        if name == "sqrt":
            return "sqrt Q,%s%s" % (VF[ft], BC[ftf])
        if name in ("waitq", "waitp"):
            return name
        if name == "mtir":
            return "mtir %s,%s%s" % (VI[it], VF[fs], BC[fsf])
        if name == "mfir":
            return "mfir.%s %s,%s" % (d, VF[ft], VI[is_])
        if name in ("ilwr", "iswr"):
            return "%s.%s %s,(%s)" % (name, d, VI[it], VI[is_])
        if name in ("rnext", "rget"):
            return "%s.%s %s,R" % (name, d, VF[ft])
        if name in ("rinit", "rxor"):
            return "%s R,%s%s" % (name, VF[fs], BC[fsf])
        if name == "mfp":
            return "mfp.%s %s,P" % (d, VF[ft])
        if name in ("xtop", "xitop"):
            return "%s %s" % (name, VI[it])
        if name == "xgkick":
            return "xgkick %s" % VI[is_]
        if name in ("esadd", "ersadd", "eleng", "erleng", "esum"):
            return "%s P,%s" % (name, VF[fs])
        return "%s P,%s%s" % (name, VF[fs], BC[fsf])
    if op == 0x00:
        return "lq.%s %s,%d(%s)" % (d, VF[ft], _s11(w), VI[is_])
    if op == 0x01:
        return "sq.%s %s,%d(%s)" % (d, VF[fs], _s11(w), VI[it])
    if op == 0x04:
        return "ilw.%s %s,%d(%s)" % (d, VI[it], _s11(w), VI[is_])
    if op == 0x05:
        return "isw.%s %s,%d(%s)" % (d, VI[it], _s11(w), VI[is_])
    if op in (0x08, 0x09):
        imm = ((w >> 10) & 0x7800) | (w & 0x7ff)
        return "%s %s,%s,0x%x" % ("iaddiu" if op == 0x08 else "isubiu",
                                  VI[it], VI[is_], imm)
    if 0x10 <= op <= 0x13:
        name = ("fceq", "fcset", "fcand", "fcor")[op - 0x10]
        imm = w & 0xffffff
        return ("fcset 0x%06x" % imm if op == 0x11
                else "%s vi01,0x%06x" % (name, imm))
    if 0x14 <= op <= 0x17:
        name = ("fseq", "fsset", "fsand", "fsor")[op - 0x14]
        imm = ((w >> 10) & 0x800) | (w & 0x7ff)
        return ("fsset 0x%03x" % imm if op == 0x15
                else "%s %s,0x%03x" % (name, VI[it], imm))
    if op in (0x18, 0x1a, 0x1b):
        name = {0x18: "fmeq", 0x1a: "fmand", 0x1b: "fmor"}[op]
        return "%s %s,%s" % (name, VI[it], VI[is_])
    if op == 0x1c:
        return "fcget %s" % VI[it]
    if op in _BRANCH:
        target = pc + 8 + _s11(w) * 8
        name = _BRANCH[op]
        if op == 0x20:
            return "b 0x%04x" % target
        if op == 0x21:
            return "bal %s,0x%04x" % (VI[it], target)
        if op in (0x28, 0x29):
            return "%s %s,%s,0x%04x" % (name, VI[it], VI[is_], target)
        return "%s %s,0x%04x" % (name, VI[is_], target)
    if op == 0x24:
        return "jr %s" % VI[is_]
    if op == 0x25:
        return "jalr %s,%s" % (VI[it], VI[is_])
    return "lower? 0x%08x" % w


def decode(pair, pc):
    """One 64-bit pair, as (upper text, lower text, flags)."""
    lo, up = pair & 0xffffffff, pair >> 32
    flags = "".join(c for b, c in ((31, "I"), (30, "E"), (29, "M"),
                                   (28, "D"), (27, "T")) if up & (1 << b))
    u = _upper(up & 0x07ffffff)
    if up & (1 << 31):
        l = "loi %s" % repr(struct.unpack("<f", struct.pack("<I", lo))[0])
    else:
        l = _lower(lo, pc)
    return u, l, flags


def mpgs(blob, base):
    """(VU byte address, ELF address, code bytes) for each MPG in a DMA
    list. One 8-byte DMA tag (an END whose QWC covers the lot) and then VIF
    codes; an MPG's code starts on the next 8-byte boundary after its
    VIFcode, and the next VIFcode follows the last pair."""
    out, p = [], 8
    while p + 4 <= len(blob):
        code = struct.unpack_from("<I", blob, p)[0]
        cmd, num, imm = code >> 24 & 0x7f, code >> 16 & 0xff, code & 0xffff
        p += 4
        if cmd == 0x4a:                         # MPG
            n = num or 256
            if p % 8:
                p += 8 - p % 8
            out.append((imm * 8, base + p, blob[p:p + n * 8]))
            p += n * 8
        elif cmd == 0x20:                       # STMASK and its word
            p += 4
        elif cmd in (0x30, 0x31):               # STROW, STCOL and theirs
            p += 16
        # the rest (NOP, STCYCL, STMOD, FLUSHE, ...) carry no data
    return out


def load(retail=False):
    demo = mipsdis.Elf()
    s = demo.syms["vu1MicroCodeStart"][0]
    e = demo.syms["vu1MicroCodeEnd"][0]
    labels = {}
    for name, (a, _sz) in demo.syms.items():
        if s <= a < e and name.startswith("_$"):
            labels.setdefault(a, name[2:])
    blob = demo.read(s, e - s)
    code = {}                                   # VU address -> (pair, elf)
    lab = {}                                    # VU address -> label
    for vu, elf_at, c in mpgs(blob, s):
        for i in range(0, len(c) - 7, 8):
            code[vu + i] = (struct.unpack_from("<Q", c, i)[0], elf_at + i)
            if elf_at + i in labels:
                lab[vu + i] = labels[elf_at + i]
    if not retail:
        return code, lab
    return load_retail(code, lab)


def load_retail(dcode, dlab):
    """Retail's program, found where the demo's MPGs reappear, with each
    demo label carried to where its next few pairs match."""
    r = mipsdis.Elf(str(RETAIL))
    # Retail's code is a later build and its first pairs differ, so the
    # list is found by its VIF prologue -- STCYCL 1,1, STMOD 0, STMASK 0,
    # NOP -- after the DMA tag. Two lists have it; VU1's is the long one
    # (retail 0x002a6940, QWC 0x311; the other is two quadwords).
    pat = bytes.fromhex("0101000100000005000000200000000000000000")
    best, i = None, r.data.find(pat)
    while i >= 0:
        qwc = struct.unpack_from("<H", r.data, i - 8)[0]
        if best is None or qwc > best[0]:
            best = (qwc, i - 8)
        i = r.data.find(pat, i + 1)
    if best is None:
        raise SystemExit("retail microcode not found")
    sec = [x for x in r.secs if x["type"] != 8 and x["addr"]
           and x["off"] <= best[1] < x["off"] + x["size"]][0]
    start = sec["addr"] + best[1] - sec["off"]
    blob = r.read(start, (best[0] + 1) * 16)
    code, lab = {}, {}
    for vu, elf_at, c in mpgs(blob, start):
        if not c:
            break
        for k in range(0, len(c) - 7, 8):
            code[vu + k] = (struct.unpack_from("<Q", c, k)[0], elf_at + k)
    # labels: match 4 pairs (or fewer near the end) at each demo label
    seq = sorted(code)
    words = [code[a][0] for a in seq]
    for va, name in dlab.items():
        want = [dcode[va + 8 * j][0] for j in range(4) if va + 8 * j in dcode]
        hits = [seq[k] for k in range(len(seq) - len(want) + 1)
                if words[k:k + len(want)] == want]
        if len(hits) == 1:
            lab[hits[0]] = name
    return code, lab


def listing(code, lab, frm=None, count=None, out=sys.stdout):
    addrs = sorted(code)
    if frm is not None:
        addrs = [a for a in addrs if a >= frm]
    if count:
        addrs = addrs[:count]
    for a in addrs:
        pair, elf_at = code[a]
        if a in lab:
            out.write("%s:\n" % lab[a])
        u, l, f = decode(pair, a)
        out.write("  %04x  %08x  %-3s %-34s %s\n" % (a, elf_at, f, u, l))


SELF_CHECK = [
    # The lower NOP and the upper NOP, the pair every VU program pads with.
    ((0x000002ff << 32) | 0x8000033c, ("nop", "nop", "")),
    # loi: I set, the lower word a float.
    ((0x800002ff << 32) | 0x3f800000, ("nop", "loi 1.0", "I")),
    # E set on the pair before a program's last.
    ((0x400002ff << 32) | 0x8000033c, ("nop", "nop", "E")),
]


def self_check():
    bad = 0
    for pair, want in SELF_CHECK:
        got = decode(pair, 0)
        if got != want:
            print("0x%016x -> %r, expected %r" % (pair, got, want))
            bad += 1
    code, lab = load()
    undecoded = sum(1 for a, (p, _e) in code.items()
                    if "?" in " ".join(decode(p, a)[:2]))
    print("vu1dis: %d pairs, %d labels, %d undecoded" %
          (len(code), len(lab), undecoded))
    return 1 if bad or undecoded else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retail", action="store_true")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--count", type=int)
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args()
    if a.self_check:
        return self_check()
    code, lab = load(a.retail)
    frm = None
    if a.frm:
        named = [k for k, v in lab.items() if v == a.frm]
        frm = named[0] if named else int(a.frm, 0)
    listing(code, lab, frm, a.count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
