#!/usr/bin/env python3
"""A small R5900 interpreter, for running bWare's own code as an oracle.

`tools/mipsdis.py` is enough to *read* the PS2 code; this runs it. Some of
what is left in `NFSHP2.ELF` -- the MV3 video codec above all -- is dense
fixed-point arithmetic where a hand transcription is a guess until something
checks it. Loading the ELF into a flat memory image and calling the shipped
function directly turns that guess into a test.

Only what the asset code needs is implemented: the MIPS III integer set, the
64-bit loads/stores SN's compiler emits, the EE's second multiplier
(`mult1`/`mfhi1`/`mflo1`), and the handful of 128-bit MMI ops the IDCT uses
(`pmulth`, `pcpyld`, `pcpyud`, `pcpyh`, `pmaxw`, `pmfhi`, `pmflo`, `lq`,
`sq`). COP1 is there only because the codec accumulates profiling timers in
floats. Anything else raises, rather than quietly computing the wrong thing.

Library calls are stubbed rather than executed: `bMalloc` hands out blocks
from a bump allocator, `bMemSet`/`bMemCpy` run natively, and the tickers
return zero. That keeps the allocator, the assert path and bPrintf -- ~50
functions of it -- out of the way.

    emu = Emu()
    emu.stub_bware()
    p = emu.alloc(64)
    emu.call("bMemSet", p, 0x41, 64)
    print(emu.read(p, 64))

Arguments go in a0-a3 then t0-t3: SN's compiler builds this ELF with the
MIPS EABI, not o32, so the fifth argument is a register and not a stack slot.
"""
import struct
import sys

from mipsdis import ELF, Elf

M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF
M128 = (1 << 128) - 1

# a0-a3 then t0-t3, the EABI integer argument registers
ARGREGS = (4, 5, 6, 7, 8, 9, 10, 11)
SP, RA = 29, 31


def s32(x):
    x &= M32
    return x - 0x100000000 if x & 0x80000000 else x


def s64(x):
    x &= M64
    return x - (1 << 64) if x & (1 << 63) else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


class MipsError(Exception):
    pass


class Emu(object):
    """A flat 32 MB PS2 with one thread and no kernel."""

    RAM = 32 << 20
    RETURN = 0x0FFFFFF0        # sentinel return address: run() stops here

    def __init__(self, path=ELF):
        self.elf = Elf(path)
        self.mem = bytearray(self.RAM)
        for s in self.elf.secs:
            if not s["addr"] or not (s["flags"] & 2):
                continue
            if s["type"] == 8:                      # .bss, already zero
                continue
            a, n = s["addr"], s["size"]
            self.mem[a:a + n] = self.elf.data[s["off"]:s["off"] + n]
        self.reg = [0] * 32
        self.fpr = [0] * 32                         # raw 32-bit bit patterns
        self.hi = self.lo = self.hi1 = self.lo1 = 0
        self.stubs = {}
        self.watch = {}            # addr -> hit count, filled by watch_calls()
        self.icount = 0
        self.limit = 0
        # gp is set up by the boot code, which we never run
        gp = self.elf.syms.get("_gp")
        self.reg[28] = gp[0] if gp else 0
        # stack at the top of RAM, heap above .bss
        self.reg[SP] = self.RAM - 0x10000
        self._heap = self._heap_base = self._top_of_image()

    def _top_of_image(self):
        top = 0
        for s in self.elf.secs:
            if s["addr"] and (s["flags"] & 2):
                top = max(top, s["addr"] + s["size"])
        return (top + 0xFFF) & ~0xFFF

    # ---- memory -----------------------------------------------------------

    def read(self, addr, n):
        return bytes(self.mem[addr:addr + n])

    def write(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def u8(self, a):
        return self.mem[a]

    def u16(self, a):
        return struct.unpack_from("<H", self.mem, a)[0]

    def u32(self, a):
        return struct.unpack_from("<I", self.mem, a)[0]

    def put32(self, a, v):
        struct.pack_into("<I", self.mem, a, v & M32)

    def alloc(self, size, align=64):
        self._heap = (self._heap + align - 1) & ~(align - 1)
        p, self._heap = self._heap, self._heap + size
        if self._heap >= self.reg[SP] - 0x10000:
            raise MipsError("emulated heap exhausted")
        return p

    def reset_heap(self):
        self._heap = self._heap_base

    # ---- symbols ----------------------------------------------------------

    def addr_of(self, sym):
        if isinstance(sym, int):
            return sym
        if sym not in self.elf.syms:
            raise MipsError("no symbol %r" % sym)
        return self.elf.syms[sym][0]

    def stub(self, sym, fn):
        """Run `fn(emu)` instead of the code at `sym`; its return value, if
        not None, becomes v0."""
        self.stubs[self.addr_of(sym)] = fn

    def stub_bware(self):
        """Replace the bWare runtime with native equivalents."""
        def malloc(e):
            return e.alloc(s32(e.reg[ARGREGS[0]]))

        def memset(e):
            a, v, n = (s32(e.reg[r]) for r in ARGREGS[:3])
            e.mem[a:a + n] = bytes([v & 0xFF]) * n
            return a

        def memcpy(e):
            d, s, n = (s32(e.reg[r]) for r in ARGREGS[:3])
            e.mem[d:d + n] = e.mem[s:s + n]
            return d

        for name in ("bMalloc__Fii", "bMalloc__FiPCcii", "bLargestMalloc__Fi"):
            if name in self.elf.syms:
                self.stub(name, malloc)
        self.stub("bMemSet", memset)
        # bMemCpy shares its address with the `gcc2_compiled.` marker symbol
        self.stub(0x002380c8, memcpy)
        for name in ("bFree__FPv", "bGetTicker__Fv"):
            if name in self.elf.syms:
                self.stub(name, lambda e: 0)
        if "bGetTickerDifference__FUiUi" in self.elf.syms:
            self.stub("bGetTickerDifference__FUiUi", lambda e: 0)

    def run_ctors(self, pattern):
        """Run the `_GLOBAL_$I$*` static initialisers whose name matches.

        The boot code we never execute is what normally runs these, and some
        of them are the only place a global is given its value -- the codec's
        `OffsetClamp`, for one, which is otherwise a null pointer.
        """
        import re
        rx = re.compile(pattern)
        done = []
        for name in sorted(self.elf.syms):
            if name.startswith("_GLOBAL_$I$") and rx.search(name):
                self.call(name)
                done.append(name)
        return done

    def watch_calls(self, *syms):
        """Count how often each symbol is entered during the next run."""
        self.watch = dict.fromkeys((self.addr_of(s) for s in syms), 0)
        return self.watch

    def watch_report(self):
        return {(self.elf.label(a) or hex(a)): n
                for a, n in sorted(self.watch.items()) if True}

    # ---- execution --------------------------------------------------------

    def call(self, sym, *args, **kw):
        """Call `sym` with `args` in the EABI argument registers; returns v0
        sign-extended to 32 bits."""
        for i, v in enumerate(args):
            self.reg[ARGREGS[i]] = v & M64
        self.reg[RA] = self.RETURN
        self.run(self.addr_of(sym), **kw)
        return s32(self.reg[2])

    def run(self, pc, limit=0):
        self.limit = limit
        self.icount = 0
        reg = self.reg
        reg[0] = 0
        while pc != self.RETURN:
            if pc in self.watch:
                self.watch[pc] += 1
            stub = self.stubs.get(pc)
            if stub is not None:
                v = stub(self)
                if v is not None:
                    reg[2] = v & M64
                pc = reg[RA] & M32
                continue
            w = struct.unpack_from("<I", self.mem, pc)[0]
            npc = self._step(w, pc)
            self.icount += 1
            if self.limit and self.icount > self.limit:
                raise MipsError("instruction limit at 0x%08x" % pc)
            if npc is None:
                pc += 4
                continue
            target, annul = npc
            # the delay slot runs before the branch takes effect, unless this
            # is a branch-likely that was not taken
            if not annul:
                d = struct.unpack_from("<I", self.mem, pc + 4)[0]
                if d:
                    if self._step(d, pc + 4) is not None:
                        raise MipsError("branch in a delay slot at 0x%08x" % pc)
                    self.icount += 1
            pc = target
            reg[0] = 0
        return self

    # ---- one instruction --------------------------------------------------
    #
    # Returns None for a straight-line instruction, or (target, annul) when
    # control transfers; `annul` says to skip the delay slot.

    def _step(self, w, pc):
        reg = self.reg
        op = w >> 26
        rs, rt, rd = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        sa, fn = (w >> 6) & 31, w & 63
        imm = w & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm

        if op == 0:
            r = self._special(w, fn, rs, rt, rd, sa, pc)
            reg[0] = 0
            return r
        if op == 1:                                   # REGIMM
            v = s64(reg[rs])
            take = {0x00: v < 0, 0x01: v >= 0, 0x02: v < 0, 0x03: v >= 0,
                    0x10: v < 0, 0x11: v >= 0}.get(rt)
            if take is None:
                raise MipsError("regimm 0x%02x at 0x%08x" % (rt, pc))
            if rt in (0x10, 0x11):
                reg[RA] = (pc + 8) & M64
            likely = rt in (0x02, 0x03, 0x12, 0x13)
            if take:
                return (pc + 4 + simm * 4) & M32, False
            return ((pc + 8) & M32, True) if likely else None
        if op in (2, 3):                              # j / jal
            if op == 3:
                reg[RA] = (pc + 8) & M64
            return ((pc & 0xF0000000) | ((w & 0x03FFFFFF) << 2)), False
        if op in (4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17):
            a, b = s64(reg[rs]), s64(reg[rt])
            take = {4: a == b, 5: a != b, 6: a <= 0, 7: a > 0,
                    0x14: a == b, 0x15: a != b, 0x16: a <= 0,
                    0x17: a > 0}[op]
            if take:
                return (pc + 4 + simm * 4) & M32, False
            return ((pc + 8) & M32, True) if op >= 0x14 else None

        if op == 0x08 or op == 0x09:                  # addi / addiu
            reg[rt] = s32(s32(reg[rs]) + simm) & M64
        elif op == 0x0a:
            reg[rt] = 1 if s64(reg[rs]) < simm else 0
        elif op == 0x0b:
            reg[rt] = 1 if (reg[rs] & M64) < (simm & M64) else 0
        elif op == 0x0c:
            reg[rt] = reg[rs] & imm
        elif op == 0x0d:
            reg[rt] = reg[rs] | imm
        elif op == 0x0e:
            reg[rt] = reg[rs] ^ imm
        elif op == 0x0f:
            reg[rt] = s32(imm << 16) & M64
        elif op == 0x18 or op == 0x19:                # daddi / daddiu
            reg[rt] = (s64(reg[rs]) + simm) & M64
        elif op == 0x1a:                              # ldl
            reg[rt] = self._ldl(reg[rt], s32(reg[rs]) + simm)
        elif op == 0x1b:                              # ldr
            reg[rt] = self._ldr(reg[rt], s32(reg[rs]) + simm)
        elif op == 0x1e:                              # lq
            a = (s32(reg[rs]) + simm) & ~15
            reg[rt] = int.from_bytes(self.mem[a:a + 16], "little")
        elif op == 0x1f:                              # sq
            a = (s32(reg[rs]) + simm) & ~15
            self.mem[a:a + 16] = (reg[rt] & M128).to_bytes(16, "little")
        elif op == 0x20:
            reg[rt] = (self.mem[s32(reg[rs]) + simm] ^ 0x80) - 0x80 & M64
        elif op == 0x21:
            reg[rt] = s16(self.u16(s32(reg[rs]) + simm)) & M64
        elif op == 0x23:
            reg[rt] = s32(self.u32(s32(reg[rs]) + simm)) & M64
        elif op == 0x24:
            reg[rt] = self.mem[s32(reg[rs]) + simm]
        elif op == 0x25:
            reg[rt] = self.u16(s32(reg[rs]) + simm)
        elif op == 0x27:
            reg[rt] = self.u32(s32(reg[rs]) + simm)
        elif op == 0x28:
            self.mem[s32(reg[rs]) + simm] = reg[rt] & 0xFF
        elif op == 0x29:
            struct.pack_into("<H", self.mem, s32(reg[rs]) + simm,
                             reg[rt] & 0xFFFF)
        elif op == 0x2b:
            self.put32(s32(reg[rs]) + simm, reg[rt])
        elif op == 0x2c:                              # sdl
            self._sdl(reg[rt], s32(reg[rs]) + simm)
        elif op == 0x2d:                              # sdr
            self._sdr(reg[rt], s32(reg[rs]) + simm)
        elif op == 0x37:                              # ld
            reg[rt] = struct.unpack_from("<Q", self.mem,
                                         s32(reg[rs]) + simm)[0]
        elif op == 0x3f:                              # sd
            struct.pack_into("<Q", self.mem, s32(reg[rs]) + simm,
                             reg[rt] & M64)
        elif op in (0x2f, 0x33):                      # cache / pref
            pass
        elif op == 0x31:                              # lwc1
            self.fpr[rt] = self.u32(s32(reg[rs]) + simm)
        elif op == 0x39:                              # swc1
            self.put32(s32(reg[rs]) + simm, self.fpr[rt])
        elif op == 0x11:                              # COP1
            self._cop1(w, rs, rt, rd, sa, fn, pc)
        elif op == 0x1c:                              # MMI
            self._mmi(w, rs, rt, rd, sa, fn, pc)
        else:
            raise MipsError("opcode 0x%02x at 0x%08x" % (op, pc))
        reg[0] = 0
        return None

    def _special(self, w, fn, rs, rt, rd, sa, pc):
        reg = self.reg
        if fn == 0x00:
            reg[rd] = s32((reg[rt] & M32) << sa) & M64
        elif fn == 0x02:
            reg[rd] = s32((reg[rt] & M32) >> sa) & M64
        elif fn == 0x03:
            reg[rd] = s32(s32(reg[rt]) >> sa) & M64
        elif fn == 0x04:
            reg[rd] = s32((reg[rt] & M32) << (reg[rs] & 31)) & M64
        elif fn == 0x06:
            reg[rd] = s32((reg[rt] & M32) >> (reg[rs] & 31)) & M64
        elif fn == 0x07:
            reg[rd] = s32(s32(reg[rt]) >> (reg[rs] & 31)) & M64
        elif fn == 0x08:                              # jr
            return reg[rs] & M32, False
        elif fn == 0x09:                              # jalr
            t = reg[rs] & M32
            reg[rd if rd else RA] = (pc + 8) & M64
            return t, False
        elif fn == 0x0a:
            if reg[rt] == 0:
                reg[rd] = reg[rs]
        elif fn == 0x0b:
            if reg[rt] != 0:
                reg[rd] = reg[rs]
        elif fn == 0x0d:
            raise MipsError("break at 0x%08x" % pc)
        elif fn == 0x0f:
            pass                                      # sync
        elif fn == 0x10:
            reg[rd] = self.hi & M64
        elif fn == 0x11:
            self.hi = reg[rs] & M64
        elif fn == 0x12:
            reg[rd] = self.lo & M64
        elif fn == 0x13:
            self.lo = reg[rs] & M64
        elif fn == 0x14:
            reg[rd] = (reg[rt] << (reg[rs] & 63)) & M64
        elif fn == 0x16:
            reg[rd] = (reg[rt] & M64) >> (reg[rs] & 63)
        elif fn == 0x17:
            reg[rd] = (s64(reg[rt]) >> (reg[rs] & 63)) & M64
        elif fn in (0x18, 0x19):                      # mult / multu
            a, b = (s32(reg[rs]), s32(reg[rt])) if fn == 0x18 else \
                   (reg[rs] & M32, reg[rt] & M32)
            p = a * b
            self.lo, self.hi = s32(p) & M64, s32(p >> 32) & M64
            if rd:                                    # the EE's third operand
                reg[rd] = self.lo
        elif fn in (0x1a, 0x1b):                      # div / divu
            if fn == 0x1a:
                a, b = s32(reg[rs]), s32(reg[rt])
                if b == 0:
                    q, r = (-1 if a >= 0 else 1), a
                else:
                    q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)
                    r = a - q * b
            else:
                a, b = reg[rs] & M32, reg[rt] & M32
                q, r = (M32, a) if b == 0 else (a // b, a % b)
            self.lo, self.hi = s32(q) & M64, s32(r) & M64
        elif fn in (0x20, 0x21):                      # add / addu
            reg[rd] = s32(s32(reg[rs]) + s32(reg[rt])) & M64
        elif fn in (0x22, 0x23):                      # sub / subu
            reg[rd] = s32(s32(reg[rs]) - s32(reg[rt])) & M64
        elif fn == 0x24:
            reg[rd] = reg[rs] & reg[rt] & M64
        elif fn == 0x25:
            reg[rd] = (reg[rs] | reg[rt]) & M64
        elif fn == 0x26:
            reg[rd] = (reg[rs] ^ reg[rt]) & M64
        elif fn == 0x27:
            reg[rd] = ~(reg[rs] | reg[rt]) & M64
        elif fn == 0x2a:
            reg[rd] = 1 if s64(reg[rs]) < s64(reg[rt]) else 0
        elif fn == 0x2b:
            reg[rd] = 1 if (reg[rs] & M64) < (reg[rt] & M64) else 0
        elif fn in (0x2c, 0x2d):                      # dadd / daddu
            reg[rd] = (s64(reg[rs]) + s64(reg[rt])) & M64
        elif fn in (0x2e, 0x2f):                      # dsub / dsubu
            reg[rd] = (s64(reg[rs]) - s64(reg[rt])) & M64
        elif fn == 0x38:
            reg[rd] = (reg[rt] << sa) & M64
        elif fn == 0x3a:
            reg[rd] = (reg[rt] & M64) >> sa
        elif fn == 0x3b:
            reg[rd] = (s64(reg[rt]) >> sa) & M64
        elif fn == 0x3c:
            reg[rd] = (reg[rt] << (sa + 32)) & M64
        elif fn == 0x3e:
            reg[rd] = (reg[rt] & M64) >> (sa + 32)
        elif fn == 0x3f:
            reg[rd] = (s64(reg[rt]) >> (sa + 32)) & M64
        else:
            raise MipsError("special 0x%02x at 0x%08x" % (fn, pc))
        return None

    # ---- unaligned 64-bit loads/stores ------------------------------------
    #
    # SN's compiler pairs ldl/ldr (and sdl/sdr) to move eight bytes from an
    # address it cannot prove aligned. Little-endian: `ldl` takes the high
    # bytes, `ldr` the low ones.

    def _ldl(self, old, addr):
        n = (addr & 7) + 1
        val = int.from_bytes(self.mem[addr - n + 1:addr + 1], "little")
        return ((val << ((8 - n) * 8)) | (old & ((1 << ((8 - n) * 8)) - 1))) & M64

    def _ldr(self, old, addr):
        n = 8 - (addr & 7)
        val = int.from_bytes(self.mem[addr:addr + n], "little")
        keep = old & ~((1 << (n * 8)) - 1) if n < 8 else 0
        return (val | keep) & M64

    def _sdl(self, val, addr):
        n = (addr & 7) + 1
        b = (val & M64).to_bytes(8, "little")
        self.mem[addr - n + 1:addr + 1] = b[8 - n:]

    def _sdr(self, val, addr):
        n = 8 - (addr & 7)
        b = (val & M64).to_bytes(8, "little")
        self.mem[addr:addr + n] = b[:n]

    # ---- COP1 -------------------------------------------------------------

    def _cop1(self, w, rs, rt, rd, sa, fn, pc):
        f = lambda i: struct.unpack("<f", struct.pack("<I", self.fpr[i]))[0]
        def put(i, v):
            self.fpr[i] = struct.unpack("<I", struct.pack("<f", v))[0]
        if rs == 0x00:                                # mfc1
            self.reg[rt] = s32(self.fpr[rd]) & M64
        elif rs == 0x04:                              # mtc1
            self.fpr[rd] = self.reg[rt] & M32
        elif rs == 0x10:                              # single
            if fn == 0x00:
                put(sa, f(rd) + f(rt))
            elif fn == 0x01:
                put(sa, f(rd) - f(rt))
            elif fn == 0x02:
                put(sa, f(rd) * f(rt))
            elif fn == 0x03:
                put(sa, f(rd) / f(rt) if f(rt) else 0.0)
            elif fn == 0x06:
                self.fpr[sa] = self.fpr[rd]
            elif fn == 0x24:                          # cvt.w.s
                self.fpr[sa] = int(f(rd)) & M32
            else:
                raise MipsError("cop1.s 0x%02x at 0x%08x" % (fn, pc))
        elif rs == 0x14:                              # word
            if fn == 0x20:                            # cvt.s.w
                put(sa, float(s32(self.fpr[rd])))
            else:
                raise MipsError("cop1.w 0x%02x at 0x%08x" % (fn, pc))
        else:
            raise MipsError("cop1 rs=0x%02x at 0x%08x" % (rs, pc))

    # ---- MMI --------------------------------------------------------------

    @staticmethod
    def _halves(v):
        return [s16((v >> (16 * i)) & 0xFFFF) for i in range(8)]

    @staticmethod
    def _words(v):
        return [s32((v >> (32 * i)) & M32) for i in range(4)]

    @staticmethod
    def _pack_words(ws):
        out = 0
        for i, x in enumerate(ws):
            out |= (x & M32) << (32 * i)
        return out

    def _mmi(self, w, rs, rt, rd, sa, fn, pc):
        reg = self.reg
        if fn in (0x18, 0x19):                        # mult1 / multu1
            a, b = (s32(reg[rs]), s32(reg[rt])) if fn == 0x18 else \
                   (reg[rs] & M32, reg[rt] & M32)
            p = a * b
            self.lo1, self.hi1 = s32(p) & M64, s32(p >> 32) & M64
            if rd:
                reg[rd] = self.lo1
        elif fn == 0x10:
            reg[rd] = self.hi1 & M64
        elif fn == 0x12:
            reg[rd] = self.lo1 & M64
        elif fn == 0x11:
            self.hi1 = reg[rs] & M64
        elif fn == 0x13:
            self.lo1 = reg[rs] & M64
        elif fn in (0x1a, 0x1b):                      # div1 / divu1
            if fn == 0x1a:
                a, b = s32(reg[rs]), s32(reg[rt])
                q = 0 if b == 0 else \
                    abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)
                r = a - q * b if b else a
            else:
                a, b = reg[rs] & M32, reg[rt] & M32
                q, r = (M32, a) if b == 0 else (a // b, a % b)
            self.lo1, self.hi1 = s32(q) & M64, s32(r) & M64
        elif fn == 0x08 and sa == 0x03:               # pmaxw
            reg[rd] = self._pack_words(
                [max(a, b) for a, b in zip(self._words(reg[rs]),
                                           self._words(reg[rt]))])
        elif fn == 0x09 and sa == 0x08:               # pmfhi
            reg[rd] = self.hi & M128
        elif fn == 0x09 and sa == 0x09:               # pmflo
            reg[rd] = self.lo & M128
        elif fn == 0x09 and sa == 0x0e:               # pcpyld
            reg[rd] = ((reg[rs] & M64) << 64) | (reg[rt] & M64)
        elif fn == 0x29 and sa == 0x0e:               # pcpyud
            reg[rd] = ((reg[rt] >> 64) << 64) | ((reg[rs] >> 64) & M64)
        elif fn == 0x29 and sa == 0x1b:               # pcpyh
            lo = reg[rt] & 0xFFFF
            hi = (reg[rt] >> 64) & 0xFFFF
            v = 0
            for i in range(4):
                v |= lo << (16 * i)
                v |= hi << (64 + 16 * i)
            reg[rd] = v
        elif fn == 0x09 and sa == 0x1c:               # pmulth
            a, b = self._halves(reg[rs]), self._halves(reg[rt])
            p = [a[i] * b[i] for i in range(8)]
            self.lo = ((p[5] & M32) << 96) | ((p[4] & M32) << 64) | \
                      ((p[1] & M32) << 32) | (p[0] & M32)
            self.hi = ((p[7] & M32) << 96) | ((p[6] & M32) << 64) | \
                      ((p[3] & M32) << 32) | (p[2] & M32)
            if rd:
                reg[rd] = self._pack_words([p[0], p[2], p[4], p[6]])
        else:
            raise MipsError("mmi fn=0x%02x sa=0x%02x at 0x%08x" % (fn, sa, pc))


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="run a function out of NFSHP2.ELF")
    ap.add_argument("symbol")
    ap.add_argument("args", nargs="*", help="integer arguments")
    ap.add_argument("--elf", default=ELF)
    ap.add_argument("--dump", help="ADDR:LEN to hex-dump afterwards")
    a = ap.parse_args()
    e = Emu(a.elf)
    e.stub_bware()
    v = e.call(a.symbol, *[int(x, 0) for x in a.args])
    print("v0 = %d (0x%08x)   %d instructions" % (v, v & M32, e.icount))
    if a.dump:
        addr, n = (int(x, 0) for x in a.dump.split(":"))
        d = e.read(addr, n)
        for i in range(0, len(d), 16):
            print("  %08x  %s" % (addr + i, d[i:i + 16].hex(" ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
