#!/usr/bin/env python3
r"""What retail_match.py masks, compared: the values a paired function loads.

retail_match.py calls two functions `same` when their bodies agree once each
link-dependent field is cleared: a jal's target, a lui's immediate, every
gp offset and every low half added to a lui'd register. Those are also where
a build's constants live, so a `same` function can load a different float,
read a different table or call a different function and still be `same`.

This walks every pair out/retail_syms.txt places, instruction by
instruction (a `same` pair one for one, any other by aligning the masked
words), and at each masked slot compares what it stands for:

- a call or jump: retail's target is the pair of the demo's;
- a lui that feeds an mtc1, or an ori and then an mtc1: the float or word it
  builds;
- a load from gp, or from a lui'd address: the bytes it reads;
- an address taken (addiu from gp or a lui): the demo object that holds it,
  word by word against the same span in retail, words that hold an address
  in both left out.

The data is each image's file contents, so a writable global compares by its
initial value.

Usage:
    python tools/retail_consts.py                          # every pair
    python tools/retail_consts.py --grep "Mellow|AIDriver"  # names matching
    python tools/retail_consts.py --kind same               # one kind only
"""
import argparse
import bisect
import difflib
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retail_match as rm  # noqa: E402

SYMS = rm.ROOT / "out" / "retail_syms.txt"

LOAD_SIZE = {32: 1, 36: 1, 33: 2, 37: 2, 34: 4, 35: 4, 38: 4, 39: 4,
             49: 4, 53: 8, 55: 8, 30: 16, 54: 16}
ADDR_OPS = {9, 25, 13}                    # addiu daddiu ori
JR_LIKE = {8, 9}                          # jr jalr


def simm(w):
    v = w & 0xffff
    return v - 0x10000 if v & 0x8000 else v


def load_pairs():
    pairs = []
    for line in open(SYMS):
        if line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 7 or f[0].startswith("-") or f[4].startswith("-"):
            continue
        pairs.append((int(f[4], 16), int(f[5]), int(f[0], 16), int(f[1]),
                      f[2], f[6]))
    return pairs


def dest_of(w):
    """The general register `w` writes, or None, as mask_stream decides."""
    op = w >> 26
    rs = (w >> 21) & 31
    rt = (w >> 16) & 31
    if op == 3:
        return 31
    if op == 0:
        funct = w & 63
        if funct in rm.R_NO_DEST:
            return None
        return (w >> 11) & 31
    if op in rm.RT_WRITERS or op == 15:
        return rt
    if op == 17 and rs in (0, 2):
        return rt
    if op == 18 and rs in (1, 2):
        return rt
    if op == 28:
        return (w >> 11) & 31
    return None


def addresses(words, start):
    """Per word: the full address it loads from or takes, if a lui or gp
    built its base, as ('gp', off) or ('abs', addr); and per lui the
    constant it builds when the value goes to an mtc1 or an ori."""
    out = [None] * len(words)
    hi = {}      # reg -> upper half
    full = {}    # reg -> full address an addiu finished
    reset = -1
    for i, w in enumerate(words):
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        if op == 15:
            hi[rt] = (w & 0xffff) << 16
            full.pop(rt, None)
        elif op in rm.LO_OPS:
            if rs == rm.GP_REG:
                out[i] = ("gp", simm(w))
            elif rs in hi:
                out[i] = ("abs", (hi[rs] + simm(w)) & 0xffffffff)
            elif rs in full and op in LOAD_SIZE:
                out[i] = ("abs", (full[rs] + simm(w)) & 0xffffffff)
            d = rt if op in rm.RT_WRITERS else None
            if d is not None:
                hi.pop(d, None)
                full.pop(d, None)
                if op in ADDR_OPS and out[i] and out[i][0] == "abs" and op != 13:
                    full[d] = out[i][1]
        else:
            if op == 0 and (w & 63) in (0x21, 0x2d) and \
                    (rs in hi or rt in hi):
                d = (w >> 11) & 31
                hi[d] = hi.get(rs, hi.get(rt))
                full.pop(d, None)
            else:
                d = dest_of(w)
                if d is not None:
                    hi.pop(d, None)
                    full.pop(d, None)
        if op == 2 or (op == 0 and (w & 63) in JR_LIKE):
            reset = i + 1
        if i == reset:
            hi.clear()
            full.clear()
    return out


def lui_constant(words, i):
    """The value a lui at `i` builds when it is a constant: ('f', bits) for
    one an mtc1 takes, ('w', word) for an ori's; None for an address."""
    w = words[i]
    reg = (w >> 16) & 31
    val = (w & 0xffff) << 16
    for k in range(i + 1, min(i + 8, len(words))):
        x = words[k]
        op = x >> 26
        rs = (x >> 21) & 31
        rt = (x >> 16) & 31
        if op == 17 and rs == 4 and rt == reg:          # mtc1 reg
            return ("f", val)
        if op == 13 and rs == reg:                      # ori r,reg,lo
            val |= x & 0xffff
            reg = rt
            continue
        if op == 18 and rs == 5 and rt == reg:          # ctc2 / qmtc2-ish
            return ("w", val)
        uses = (rs == reg) or (op in (0, 28) and rt == reg) or \
            (op in (4, 5) and rt == reg)
        if uses:
            return ("w", val) if (words[i + 1] >> 26) == 13 else None
        if dest_of(x) == reg:
            return None
    return None


def fmt(kind, b):
    if kind == "f" or len(b) == 4:
        u = struct.unpack("<I", b)[0] if isinstance(b, bytes) else b
        f = struct.unpack("<f", struct.pack("<I", u))[0]
        return f"{u:08x} ({f:.9g}, {struct.unpack('<i', struct.pack('<I', u))[0]})"
    return b.hex()


def looks_like_pointer(v):
    return 0x00100000 <= v < 0x02000000


class Sweep(object):
    def __init__(self):
        self.demo = rm.Image(rm.DEMO)
        self.retail = rm.Image(rm.RETAIL)
        self.gp_d = rm.find_gp(self.demo)
        self.gp_r = rm.find_gp(self.retail)
        self.pairs = load_pairs()
        self.fmap = {d: r for d, _ds, r, _rs, _k, _n in self.pairs}
        self.rinv = {r: d for d, _ds, r, _rs, _k, _n in self.pairs}
        self.obj_addr = [a for a, _s, _n in self.demo.objects]
        self.names = {d: n for d, _ds, _r, _rs, _k, n in self.pairs}

    def words(self, img, a, n):
        k = (a - img.text_addr) // 4
        return img.text[k:k + n // 4], img.masked[k:k + n // 4]

    def obj_of(self, a):
        k = bisect.bisect_right(self.obj_addr, a) - 1
        if k >= 0:
            oa, os_, name = self.demo.objects[k]
            if oa <= a < oa + max(os_, 1):
                return oa, os_, name
        return None

    def full_addr(self, img, ref):
        kind, v = ref
        if kind == "gp":
            gp = self.gp_d if img is self.demo else self.gp_r
            return (gp + v) & 0xffffffff
        return v

    def compare_span(self, ad, ar, n):
        bd = self.demo.read(ad, n)
        br = self.retail.read(ar, n)
        if len(bd) < n or len(br) < n:
            return None
        if bd == br:
            return []
        diffs = []
        for o in range(0, n - n % 4, 4):
            wd = struct.unpack_from("<I", bd, o)[0]
            wr = struct.unpack_from("<I", br, o)[0]
            if wd != wr and not (looks_like_pointer(wd) and
                                 looks_like_pointer(wr)):
                diffs.append((o, wd, wr))
        if n % 4 and bd[n - n % 4:] != br[n - n % 4:]:
            diffs.append((n - n % 4, bd[n - n % 4:], br[n - n % 4:]))
        return diffs

    def function(self, da, ds, ra, rs_, kind):
        dw, dm = self.words(self.demo, da, ds)
        rw, rmk = self.words(self.retail, ra, rs_)
        if dm == rmk:
            amap = {i: i for i in range(len(dw))}
        else:
            sm = difflib.SequenceMatcher(None, list(dm), list(rmk),
                                         autojunk=False)
            amap = {}
            for b in sm.get_matching_blocks():
                for k in range(b.size):
                    amap[b.a + k] = b.b + k
        dref = addresses(dw, da)
        rref = addresses(rw, ra)
        found = []
        seen_obj = set()
        for i, j in sorted(amap.items()):
            wd, wr = dw[i], rw[j]
            op = wd >> 26
            if op in (2, 3):
                td = ((wd & 0x3ffffff) << 2) | (da & 0xf0000000)
                tr = ((wr & 0x3ffffff) << 2) | (ra & 0xf0000000)
                if da <= td < da + ds:
                    if amap.get((td - da) // 4) != (tr - ra) // 4:
                        found.append((i, "jump", f"{td - da:+#x}",
                                      f"{tr - ra:+#x}"))
                    continue
                exp = self.fmap.get(td)
                back = self.rinv.get(tr)
                if (exp is not None and exp != tr) or \
                        (back is not None and back != td):
                    found.append((i, "call", self.names.get(td, f"{td:08x}"),
                                  self.names.get(back, f"{tr:08x}")
                                  if back else f"{tr:08x}"))
                continue
            if op == 15:
                cd = lui_constant(dw, i)
                cr = lui_constant(rw, j)
                if cd and cr and cd != cr:
                    found.append((i, "literal", fmt("f", cd[1]),
                                  fmt("f", cr[1])))
                elif cd and not cr and (wd & 0xffff) != (wr & 0xffff):
                    found.append((i, "literal?", fmt("f", cd[1]),
                                  f"lui {wr & 0xffff:#06x}"))
                continue
            if dref[i] is None or rref[j] is None:
                continue
            ad = self.full_addr(self.demo, dref[i])
            ar = self.full_addr(self.retail, rref[j])
            if op in LOAD_SIZE:
                n = LOAD_SIZE[op]
                d = self.compare_span(ad, ar, n)
                if d:
                    found.append((i, f"load {n}", fmt("x", self.demo.read(ad, n)),
                                  fmt("x", self.retail.read(ar, n))
                                  + "  " + self.where(ad)))
            elif op in ADDR_OPS:
                o = self.obj_of(ad)
                if o is None:
                    continue
                oa, os_, name = o
                if (oa, ar - (ad - oa)) in seen_obj or os_ <= 0:
                    continue
                seen_obj.add((oa, ar - (ad - oa)))
                d = self.compare_span(oa, ar - (ad - oa), min(os_, 0x4000))
                if d:
                    shown = ", ".join(
                        f"+{o_:#x} {v1:08x}->{v2:08x}" if isinstance(v1, int)
                        else f"+{o_:#x}" for o_, v1, v2 in d[:6])
                    more = f" (+{len(d) - 6} more)" if len(d) > 6 else ""
                    found.append((i, "object", f"{name} [{os_}]",
                                  shown + more))
        return found

    def where(self, a):
        o = self.obj_of(a)
        sec = self.demo.section_of(a) or "?"
        if o:
            return f"{o[2]}+{a - o[0]:#x} {sec}"
        return sec


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--grep", help="only demo names this regex finds")
    ap.add_argument("--kind", help="only pairs of this retail_syms kind")
    args = ap.parse_args()
    s = Sweep()
    pat = re.compile(args.grep) if args.grep else None
    total = 0
    funcs = 0
    for da, ds, ra, rs_, kind, name in s.pairs:
        if pat and not pat.search(name):
            continue
        if args.kind and kind != args.kind:
            continue
        found = s.function(da, ds, ra, rs_, kind)
        if not found:
            continue
        funcs += 1
        total += len(found)
        print(f"{name}  ({kind}, demo {da:08x}, retail {ra:08x})")
        for i, what, dv, rv in found:
            print(f"    +{i * 4:#05x} {what:8} demo {dv}")
            print(f"    {'':6} {'':8} retail {rv}")
    print(f"# {total} differences in {funcs} functions")


if __name__ == "__main__":
    main()
