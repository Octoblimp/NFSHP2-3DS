#!/usr/bin/env python3
"""Disassembles the stripped retail ELF under the demo's names.

mipsdis.py labels calls from the ELF's own .symtab, which retail does not
have. This fills it from out/retail_syms.txt (`retail_match.py --out`), so
a `jal` into a matched function reads as the demo's name.

  python tools/retaildis.py Start__Q25sound7jukeboxb   # by demo name
  python tools/retaildis.py --addr 0x001aeab0 --count 120
  python tools/retaildis.py --callers 0x001aeab0
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mipsdis  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RETAIL = ROOT / "PS2 Files" / "Full Game" / "SLES_507.31"
SYMS = ROOT / "out" / "retail_syms.txt"


def load(elf, path):
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or line.startswith("-"):
            continue
        f = line.split()
        if len(f) < 7 or f[2] == "new":
            continue
        addr, size = int(f[0], 16), int(f[1])
        name = f[6]
        elf.syms[name] = (addr, size)
        elf.by_addr.setdefault(addr, name)
    elf.sorted_syms = sorted((v, k) for k, (v, _s) in elf.syms.items())


GP = 0x003358f0   # retail_model.RETAIL_GP


def refs(elf, target):
    """Every load, store or address-of that reaches `target`.

    A gp-relative access names it outright; anything else is a `lui` then
    an `addiu`/load/store off the same register, which this pairs up the
    way the compiler emits them -- the `lui` a few instructions earlier,
    nothing in between rewriting the register. Good enough for globals; a
    pointer handed around in registers leaves no trace to find.
    """
    import struct
    out = []
    for s in elf.secs:
        if s["type"] == 8 or not s["addr"] or not (s["flags"] & 0x4):
            continue
        blob = elf.data[s["off"]:s["off"] + s["size"]]
        hi = {}                      # register -> (upper half, site)
        for i in range(0, len(blob) - 3, 4):
            w = struct.unpack_from("<I", blob, i)[0]
            addr = s["addr"] + i
            op, rs, rt = w >> 26, (w >> 21) & 31, (w >> 16) & 31
            imm = w & 0xFFFF
            simm = imm - 0x10000 if imm & 0x8000 else imm
            if op == 0x0f:                         # lui
                hi[rt] = (imm << 16, addr)
                continue
            mem = op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x27, 0x28, 0x29,
                         0x2b, 0x31, 0x37, 0x39, 0x3f, 0x1e, 0x1f)
            if mem or op == 0x09:                  # loads/stores, addiu
                if rs == 28 and (GP + simm) & 0xFFFFFFFF == target:
                    out.append((addr, elf.label(addr)))
                elif rs in hi and addr - hi[rs][1] <= 64 and \
                        (hi[rs][0] + simm) & 0xFFFFFFFF == target:
                    out.append((addr, elf.label(addr)))
            # whatever the instruction writes ends that register's pairing:
            # rt for a load or an immediate op, rd for SPECIAL; a store
            # writes nothing
            if op in (0x28, 0x29, 0x2b, 0x39, 0x3f, 0x1f):
                continue
            hi.pop((w >> 11) & 31 if op == 0 else rt, None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", help="a demo function name")
    ap.add_argument("--addr")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--callers", metavar="ADDR")
    ap.add_argument("--refs", metavar="ADDR",
                    help="who reads or writes this global (or gp%%+d)")
    a = ap.parse_args()

    elf = mipsdis.Elf(str(RETAIL))
    load(elf, SYMS)
    if a.refs:
        t = a.refs
        target = GP + int(t[2:], 0) if t.startswith("gp") else int(t, 0)
        for site, who in refs(elf, target & 0xFFFFFFFF):
            w = int.from_bytes(elf.read(site, 4), "little")
            print("  %08x  %-40s %s" % (site, who,
                                        mipsdis.decode(w, site, elf)[0]))
        return 0
    if a.callers:
        for site, who in mipsdis.callers(elf, int(a.callers, 0)):
            print("  %08x  %s" % (site, who))
        return 0
    if a.addr:
        addr = int(a.addr, 0)
        n = a.count or 64
        if not a.count and addr in elf.by_addr:
            n = elf.syms[elf.by_addr[addr]][1] // 4
        print("--- %s @ 0x%08x ---" % (elf.by_addr.get(addr, "?"), addr))
        mipsdis.disassemble(elf, addr, n)
        return 0
    if not a.symbol or a.symbol not in elf.syms:
        print("no retail placement for %r" % a.symbol, file=sys.stderr)
        return 1
    addr, size = elf.syms[a.symbol]
    print("--- %s @ 0x%08x (%d bytes) ---" % (a.symbol, addr, size))
    mipsdis.disassemble(elf, addr, a.count or size // 4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
