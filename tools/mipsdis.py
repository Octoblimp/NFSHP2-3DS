#!/usr/bin/env python3
"""A small MIPS III / R5900 disassembler for `PS2 Files/NFSHP2.ELF`.

Enough of the EE instruction set to read bWare's scalar game-logic code
without a MIPS toolchain: MIPS I/II/III integer ops (including the 64-bit
`ld`/`sd`/`daddu` that SN's compiler emits for every register save and
every register-to-register move), the COP1 FPU, and the branch-likely
forms. MMI (the EE's 128-bit multimedia ops) and the COP2/VU transfers are
printed as `mmi`/`cop2` with their raw word -- they appear in the geometry
code that feeds VU1, not in the logic this is meant for.

Symbols come from `.symtab`, which this ELF still has in full, so functions
can be disassembled by their (GNU C++ v2 mangled) name:

    python tools/mipsdis.py LoaderFlailerChunk__FP6bChunk
    python tools/mipsdis.py --grep Flailer            # find a symbol
    python tools/mipsdis.py --addr 0x0013d890 --count 40

Branch and jump targets are annotated with the symbol they land in, so
`jal` sites read as names, and branch targets inside the listing are
marked with `>`.
"""
import argparse
import os
import re
import struct
import sys

ELF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "PS2 Files", "NFSHP2.ELF")

REG = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
       "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
       "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
       "t8", "t9", "k0", "k1", "gp", "sp", "s8", "ra"]

# opcode -> mnemonic, for the I/J-type encodings
OPS = {
    0x02: "j", 0x03: "jal", 0x04: "beq", 0x05: "bne", 0x06: "blez",
    0x07: "bgtz", 0x08: "addi", 0x09: "addiu", 0x0a: "slti", 0x0b: "sltiu",
    0x0c: "andi", 0x0d: "ori", 0x0e: "xori", 0x0f: "lui",
    0x14: "beql", 0x15: "bnel", 0x16: "blezl", 0x17: "bgtzl",
    0x18: "daddi", 0x19: "daddiu", 0x1a: "ldl", 0x1b: "ldr",
    0x20: "lb", 0x21: "lh", 0x22: "lwl", 0x23: "lw", 0x24: "lbu",
    0x25: "lhu", 0x26: "lwr", 0x27: "lwu", 0x28: "sb", 0x29: "sh",
    0x2a: "swl", 0x2b: "sw", 0x2c: "sdl", 0x2d: "sdr", 0x2e: "swr",
    0x2f: "cache", 0x31: "lwc1", 0x33: "pref", 0x36: "lqc2", 0x37: "ld",
    0x39: "swc1", 0x3e: "sqc2", 0x3f: "sd",
}
# SPECIAL (opcode 0) funct -> mnemonic
SPECIAL = {
    0x00: "sll", 0x02: "srl", 0x03: "sra", 0x04: "sllv", 0x06: "srlv",
    0x07: "srav", 0x08: "jr", 0x09: "jalr", 0x0a: "movz", 0x0b: "movn",
    0x0c: "syscall", 0x0d: "break", 0x0f: "sync", 0x10: "mfhi",
    0x11: "mthi", 0x12: "mflo", 0x13: "mtlo", 0x14: "dsllv",
    0x16: "dsrlv", 0x17: "dsrav", 0x18: "mult", 0x19: "multu",
    0x1a: "div", 0x1b: "divu", 0x1c: "dmult", 0x1d: "dmultu",
    0x1e: "ddiv", 0x1f: "ddivu", 0x20: "add", 0x21: "addu", 0x22: "sub",
    0x23: "subu", 0x24: "and", 0x25: "or", 0x26: "xor", 0x27: "nor",
    0x2a: "slt", 0x2b: "sltu", 0x2c: "dadd", 0x2d: "daddu", 0x2e: "dsub",
    0x2f: "dsubu", 0x38: "dsll", 0x3a: "dsrl", 0x3b: "dsra",
    0x3c: "dsll32", 0x3e: "dsrl32", 0x3f: "dsra32",
}
# REGIMM (opcode 1) rt -> mnemonic
REGIMM = {0x00: "bltz", 0x01: "bgez", 0x02: "bltzl", 0x03: "bgezl",
          0x10: "bltzal", 0x11: "bgezal", 0x12: "bltzall", 0x13: "bgezall"}
# COP1 funct -> mnemonic
COP1_FN = {
    0x00: "add", 0x01: "sub", 0x02: "mul", 0x03: "div", 0x04: "sqrt",
    0x05: "abs", 0x06: "mov", 0x07: "neg", 0x0c: "round.w",
    0x0d: "trunc.w", 0x0e: "ceil.w", 0x0f: "floor.w", 0x18: "adda",
    0x1c: "madd", 0x1d: "msub", 0x20: "cvt.s", 0x24: "cvt.w",
    0x30: "c.f", 0x32: "c.eq", 0x34: "c.lt", 0x36: "c.le",
}
COP1_FMT = {0x10: "s", 0x11: "d", 0x14: "w"}
UNARY = ("sqrt", "abs", "mov", "neg", "cvt.s", "cvt.w",
         "round.w", "trunc.w", "ceil.w", "floor.w")
# opcodes whose target is pc-relative
REL_BRANCH = set(range(0x04, 0x08)) | set(range(0x14, 0x18))


class Elf(object):
    """Just enough ELF to map addresses to bytes and to symbol names."""

    def __init__(self, path=ELF):
        self.data = open(path, "rb").read()
        d = self.data
        shoff = struct.unpack_from("<I", d, 0x20)[0]
        shentsize, shnum, _shstrndx = struct.unpack_from("<3H", d, 0x2e)
        self.secs = []
        for i in range(shnum):
            f = struct.unpack_from("<10I", d, shoff + i * shentsize)
            self.secs.append(dict(zip(
                ("name", "type", "flags", "addr", "off", "size",
                 "link", "info", "align", "entsize"), f)))
        self.syms = {}      # name -> (addr, size)
        self.by_addr = {}   # addr -> name
        for s in self.secs:
            if s["type"] != 2:            # SHT_SYMTAB
                continue
            strtab = self.secs[s["link"]]
            for i in range(s["size"] // 16):
                o = s["off"] + i * 16
                nameoff, val, size = struct.unpack_from("<3I", d, o)
                p = strtab["off"] + nameoff
                n = d[p:d.index(b"\0", p)].decode("latin-1")
                if n:
                    self.syms[n] = (val, size)
                    self.by_addr.setdefault(val, n)
        self.sorted_syms = sorted((v, k) for k, (v, _s) in self.syms.items())

    def read(self, addr, n):
        for s in self.secs:
            if s["type"] == 8:            # SHT_NOBITS, no file bytes
                continue
            if s["addr"] and s["addr"] <= addr < s["addr"] + s["size"]:
                o = s["off"] + addr - s["addr"]
                return self.data[o:o + n]
        return b""

    def _index(self, addr):
        """Index into sorted_syms of the last symbol at or before `addr`."""
        lo, hi, found = 0, len(self.sorted_syms) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.sorted_syms[mid][0] <= addr:
                found, lo = mid, mid + 1
            else:
                hi = mid - 1
        return found

    def label(self, addr):
        """The symbol containing `addr`, as `name` or `name+0x1c`."""
        exact = self.by_addr.get(addr)
        if exact:
            return exact
        i = self._index(addr)
        if i is None:
            return None
        base, name = self.sorted_syms[i]
        if base <= addr < base + max(self.syms[name][1], 4):
            return "%s+0x%x" % (name, addr - base)
        return None

    def extent(self, name):
        """Bytes to disassemble for `name`.

        `.symtab`'s `st_size` is not reliable in this ELF -- SN's linker
        records 144 bytes for `RenderFlailerText`, whose body runs to the
        next symbol nearly 1.5KB later -- so take whichever is larger, the
        recorded size or the gap to the next symbol address.
        """
        addr, size = self.syms[name]
        i = self._index(addr)
        nxt = addr + size
        for j in range(i + 1, len(self.sorted_syms)):
            if self.sorted_syms[j][0] > addr:
                nxt = self.sorted_syms[j][0]
                break
        return max(size, nxt - addr, 8)


def _fpu(w):
    rs, ft, fs, fd, fn = ((w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31,
                          (w >> 6) & 31, w & 63)
    if rs == 0x00:
        return "mfc1   %s,$f%d" % (REG[ft], fs)
    if rs == 0x02:
        return "cfc1   %s,$f%d" % (REG[ft], fs)
    if rs == 0x04:
        return "mtc1   %s,$f%d" % (REG[ft], fs)
    if rs == 0x06:
        return "ctc1   %s,$f%d" % (REG[ft], fs)
    if rs == 0x08:
        return "bc1%s" % {0: "f", 1: "t", 2: "fl", 3: "tl"}.get(ft, "?")
    fmt, name = COP1_FMT.get(rs), COP1_FN.get(fn)
    if fmt is None or name is None:
        return "cop1   0x%08x" % w
    if name.startswith("c."):
        return "%-6s $f%d,$f%d" % (name + "." + fmt, fs, ft)
    if name in UNARY:
        return "%-6s $f%d,$f%d" % (name + "." + fmt, fd, fs)
    return "%-6s $f%d,$f%d,$f%d" % (name + "." + fmt, fd, fs, ft)


def decode(w, addr, elf=None):
    """One instruction word -> (text, branch target or None)."""
    op = w >> 26
    rs, rt, rd = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    sa, fn = (w >> 6) & 31, w & 63
    imm = w & 0xFFFF
    simm = imm - 0x10000 if imm & 0x8000 else imm

    if w == 0:
        return "nop", None
    if op == 0:
        name = SPECIAL.get(fn)
        if name is None:
            return "special 0x%08x" % w, None
        if name in ("jr", "mthi", "mtlo"):
            return "%-6s %s" % (name, REG[rs]), None
        if name == "jalr":
            return "%-6s %s,%s" % (name, REG[rd], REG[rs]), None
        if name in ("mfhi", "mflo"):
            return "%-6s %s" % (name, REG[rd]), None
        if name in ("mult", "multu", "div", "divu", "dmult", "dmultu",
                    "ddiv", "ddivu"):
            return "%-6s %s,%s" % (name, REG[rs], REG[rt]), None
        if name in ("syscall", "break", "sync"):
            return name, None
        if name.startswith(("sll", "srl", "sra", "dsll", "dsrl", "dsra")) \
                and not name.endswith("v"):
            return "%-6s %s,%s,%d" % (name, REG[rd], REG[rt], sa), None
        # `daddu rd,rs,zero` is how SN's compiler spells a register move
        if name in ("daddu", "addu", "or") and rt == 0:
            return "move   %s,%s" % (REG[rd], REG[rs]), None
        return "%-6s %s,%s,%s" % (name, REG[rd], REG[rs], REG[rt]), None
    if op == 1:
        tgt = addr + 4 + simm * 4
        return "%-6s %s,0x%08x" % (REGIMM.get(rt, "regimm"), REG[rs], tgt), tgt
    if op == 0x11:
        return _fpu(w), None
    if op in (0x12, 0x13):
        return "cop2   0x%08x" % w, None
    if op == 0x1c:
        return "mmi    0x%08x" % w, None

    name = OPS.get(op)
    if name is None:
        return "op%-4d 0x%08x" % (op, w), None
    if op in (0x02, 0x03):                      # j / jal
        tgt = (addr & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        s = elf.label(tgt) if elf else None
        return "%-6s 0x%08x%s" % (name, tgt, "  <%s>" % s if s else ""), tgt
    if op in REL_BRANCH:
        tgt = addr + 4 + simm * 4
        if op == 0x04 and rs == 0 and rt == 0:
            return "b      0x%08x" % tgt, tgt
        if op in (0x06, 0x07, 0x16, 0x17):
            return "%-6s %s,0x%08x" % (name, REG[rs], tgt), tgt
        return "%-6s %s,%s,0x%08x" % (name, REG[rs], REG[rt], tgt), tgt
    if op == 0x0f:
        return "%-6s %s,0x%04x" % (name, REG[rt], imm), None
    if op in (0x31, 0x39):                      # lwc1 / swc1
        return "%-6s $f%d,%d(%s)" % (name, rt, simm, REG[rs]), None
    if op in (0x36, 0x3e):                      # lqc2 / sqc2
        return "%-6s vf%d,%d(%s)" % (name, rt, simm, REG[rs]), None
    if 0x20 <= op <= 0x3f or op in (0x1a, 0x1b):
        return "%-6s %s,%d(%s)" % (name, REG[rt], simm, REG[rs]), None
    return "%-6s %s,%s,%d" % (name, REG[rt], REG[rs], simm), None


def disassemble(elf, addr, count, out=sys.stdout):
    words = elf.read(addr, count * 4)
    if not words:
        print("no section covers 0x%08x" % addr, file=out)
        return
    decoded, targets = [], set()
    for i in range(0, len(words) - 3, 4):
        w = struct.unpack_from("<I", words, i)[0]
        text, tgt = decode(w, addr + i, elf)
        decoded.append((addr + i, text))
        if tgt is not None and addr <= tgt < addr + count * 4:
            targets.add(tgt)
    for a, text in decoded:
        print("%s %08x  %s" % (">" if a in targets else " ", a, text), file=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", help="a .symtab symbol name")
    ap.add_argument("--elf", default=ELF)
    ap.add_argument("--addr", help="disassemble from this address instead")
    ap.add_argument("--count", type=int, default=0,
                    help="instructions (default: the symbol's whole size)")
    ap.add_argument("--grep", help="list symbols matching this regex and exit")
    a = ap.parse_args()

    elf = Elf(a.elf)
    if a.grep:
        rx = re.compile(a.grep, re.I)
        for name in sorted(elf.syms):
            if rx.search(name):
                addr, size = elf.syms[name]
                print("%08x %6d  %s" % (addr, size, name))
        return 0
    if a.addr:
        disassemble(elf, int(a.addr, 0), a.count or 32)
        return 0
    if not a.symbol:
        ap.error("give a symbol, --addr or --grep")
    if a.symbol not in elf.syms:
        print("no symbol %r (try --grep)" % a.symbol, file=sys.stderr)
        return 1
    addr = elf.syms[a.symbol][0]
    size = elf.extent(a.symbol)
    print("--- %s @ 0x%08x (%d bytes) ---" % (a.symbol, addr, size))
    disassemble(elf, addr, a.count or size // 4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
