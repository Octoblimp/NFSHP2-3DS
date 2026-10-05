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
`sq`), and `mtsab` with `qfsrv`, which MV3's motion copy reads unaligned
rows with. Anything else raises, rather than quietly computing the wrong
thing.

The car simulation needed more, and `Emu(ieee=True)` is how it asks for it:
the scalar FPU in full (`sqrt.s`, `abs.s`, `neg.s`, the compares and the
four `bc1` branches, `max.s`/`min.s`), the VU0 macro-mode instructions the
physics uses -- `lqc2`/`sqc2`, `qmfc2`/`qmtc2`, the lane-wise arithmetic,
the ACC forms behind every matrix multiply, `vopmula`/`vopmsub` for cross
products, and `vrsqrt` into Q -- and the four MMI ops bIdentity is made of.
VClip added `vmuli` with the `ctc2` that loads I, and the `pextuw` and
`prot3w` it unpacks a vector's lanes with. The scenery cull added
`vclipw` and the `ctc2`/`cfc2` that seed and read the clip flags, vi18.

**The float model is IEEE single, not the EE's.** The EE rounds toward zero
and has no infinities, NaNs or denormals; the port runs on an ARM11 and on
the host, which are IEEE round-to-nearest. An oracle for the port has to
check the *algorithm and its operation order* -- which operands, in which
order, rounded where -- and that is what an IEEE interpreter of the
shipped instruction stream does. Each operation is computed in a Python
double and rounded once to float32, which is exact for add, sub, mul, div
and sqrt. Division by zero gives a signed infinity (NaN for 0/0), overflow
gives an infinity, and `cvt.w.s` saturates by sign as eefpu.h's ee_trunc_w
does. Without `ieee=True` the old codec behaviour is kept exactly: a divide
by zero gives 0.0 and an overflow raises.

`Emu(ieee=True, eediv=True)` makes the one exception the car needs: a
`div.s` or `vdiv` by zero -- or by a denormal, which the EE reads as zero --
gives the EE's answer, +/-FLT_MAX by the XOR of the signs, 0/0 included,
where IEEE has an infinity or a NaN. That is eefpu.h's ee_div. A stopped
driven pair divides 0 by 0 every frame the car sits in gear, and the
console carries on where an IEEE machine goes NaN. `eediv_pcs` collects
each instruction that took the path, so a checker can say which sites the
port has to spell with ee_div.

`eesqrt=True` is the same for a square root: `sqrt.s`, `vsqrt` and
`vrsqrt` of a negative take the root of its magnitude, as the EE does
(raising an invalid flag nothing reads), where IEEE has a NaN. That is
eefpu.h's ee_sqrt, and `eesqrt_pcs` collects the sites. DynamicCollisionBody
::TrackPolygonCheck is the first: `sqrt(1 - d*d)` of a dot product that
rounds past one.

Library calls are stubbed rather than executed: `bMalloc` hands out blocks
from a bump allocator, `bMemSet`/`bMemCpy` run natively, and the tickers
return zero. That keeps the allocator, the assert path and bPrintf -- ~50
functions of it -- out of the way.

    emu = Emu()
    emu.stub_bware()
    p = emu.alloc(64)
    emu.call("bMemSet", p, 0x41, 64)
    print(emu.read(p, 64))

`emu.hook(sym, fn)` runs `fn(emu)` just before the instruction at `sym` and
then carries on, where `emu.stub` replaces the function outright; a hook on
an entry point can, say, zero a stack frame the shipped code leaves
uninitialised.

Arguments go in a0-a3 then t0-t3: SN's compiler builds this ELF with the
MIPS EABI, not o32, so the fifth argument is a register and not a stack slot.
"""
import math
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


# ---- float32 as bit patterns ------------------------------------------------

F_INF, F_NINF, F_NAN = 0x7F800000, 0xFF800000, 0x7FC00000
F_ONE = 0x3F800000


def fbits_to(b):
    """A float32 bit pattern -> a Python float."""
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def f_to_bits(v):
    """A Python float -> the float32 bit pattern it rounds to (nearest-even).
    An overflow is an infinity of the right sign, as IEEE has it."""
    try:
        return struct.unpack("<I", struct.pack("<f", v))[0]
    except OverflowError:
        return F_INF if v > 0 else F_NINF


def f32(v):
    """Round a Python float to the nearest float32, as a Python float."""
    return fbits_to(f_to_bits(v))


def ieee_div(a, b):
    if b == 0.0:
        if a == 0.0 or a != a:
            return float("nan")
        neg = (math.copysign(1.0, a) < 0) != (math.copysign(1.0, b) < 0)
        return float("-inf") if neg else float("inf")
    return a / b


def ee_div_zero(a_bits, b_bits):
    """The EE's quotient for a zero (or denormal) divisor, as bits: FLT_MAX
    signed by the XOR of the operands' signs, whatever the dividend."""
    return ((a_bits ^ b_bits) & 0x80000000) | 0x7F7FFFFF


def ieee_sqrt(a):
    if a != a or a < 0.0:
        return float("nan")
    return math.sqrt(a)            # sqrt(-0.0) is -0.0, as IEEE has it


def ee_trunc_w(v):
    """`cvt.w.s`: truncate, saturating by the sign of the source. The same
    function as eefpu.h's ee_trunc_w and camera_check's trunc_w."""
    if v != v:
        return 0
    if v >= 2147483648.0:
        return 0x7FFFFFFF
    if v < -2147483648.0:
        return -0x80000000
    return int(v)


class Emu(object):
    """A flat 32 MB PS2 with one thread and no kernel."""

    RAM = 32 << 20
    RETURN = 0x0FFFFFF0        # sentinel return address: run() stops here

    def __init__(self, path=ELF, ieee=False, eediv=False, eesqrt=False):
        self.elf = Elf(path)
        self.ieee = ieee
        self.eediv = eediv
        self.eediv_pcs = set()
        self.eesqrt = eesqrt
        self.eesqrt_pcs = set()
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
        self.sa = 0                                 # SA, qfsrv's shift in bits
        self.fcc = False                            # the COP1 condition bit
        # VU0: 32 four-lane registers as bit patterns, vf00 fixed at
        # (0, 0, 0, 1); the accumulator; and Q.
        self.vf = [[0, 0, 0, 0] for _ in range(32)]
        self.vf[0] = [0, 0, 0, F_ONE]
        self.acc = [0, 0, 0, 0]
        self.q = 0
        self.i = 0                 # vi21, the I register, as a bit pattern
        self.clip = 0              # vi18, the clip flags: four sets of six
        self.stubs = {}
        self.hooks = {}
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

    def hook(self, sym, fn):
        """Run `fn(emu)` before the instruction at `sym`, then carry on."""
        self.hooks[self.addr_of(sym)] = fn

    def f(self, i):
        """FPR i as a Python float."""
        return fbits_to(self.fpr[i])

    def set_f(self, i, v):
        self.fpr[i] = f_to_bits(v)

    def _sqrt_arg(self, v, pc):
        """A root's operand: its magnitude when `eesqrt` and it is below
        zero, as the EE takes it. -0.0 is not below zero and keeps its
        sign; a NaN stays one."""
        if self.eesqrt and v < 0.0:
            self.eesqrt_pcs.add(pc)
            return -v
        return v

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
            if self.hooks:
                h = self.hooks.get(pc)
                if h is not None:
                    h(self)
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
            if rt == 0x18:                            # mtsab: a byte shift
                self.sa = ((reg[rs] ^ imm) & 15) * 8
                return None
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
            r = self._cop1(w, rs, rt, rd, sa, fn, pc, simm)
            reg[0] = 0
            return r
        elif op == 0x12:                              # COP2 (VU0 macro)
            self._cop2(w, rs, rt, rd, sa, fn, pc)
        elif op == 0x36:                              # lqc2
            a = (s32(reg[rs]) + simm) & ~15
            self._vput(rt, list(struct.unpack_from("<4I", self.mem, a)), 15)
        elif op == 0x3e:                              # sqc2
            a = (s32(reg[rs]) + simm) & ~15
            struct.pack_into("<4I", self.mem, a, *self.vf[rt])
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

    def _cop1(self, w, rs, rt, rd, sa, fn, pc, simm):
        f = lambda i: struct.unpack("<f", struct.pack("<I", self.fpr[i]))[0]
        ieee = self.ieee
        if ieee:
            def put(i, v):
                self.fpr[i] = f_to_bits(v)
        else:
            def put(i, v):
                self.fpr[i] = struct.unpack("<I", struct.pack("<f", v))[0]
        if rs == 0x00:                                # mfc1
            self.reg[rt] = s32(self.fpr[rd]) & M64
        elif rs == 0x04:                              # mtc1
            self.fpr[rd] = self.reg[rt] & M32
        elif rs == 0x08:                              # bc1f/t, bc1fl/tl
            take = self.fcc if rt & 1 else not self.fcc
            if take:
                return (pc + 4 + simm * 4) & M32, False
            return ((pc + 8) & M32, True) if rt & 2 else None
        elif rs == 0x10:                              # single
            if fn == 0x00:
                put(sa, f(rd) + f(rt))
            elif fn == 0x01:
                put(sa, f(rd) - f(rt))
            elif fn == 0x02:
                put(sa, f(rd) * f(rt))
            elif fn == 0x03:
                if self.eediv and not self.fpr[rt] & 0x7F800000:
                    self.eediv_pcs.add(pc)
                    self.fpr[sa] = ee_div_zero(self.fpr[rd], self.fpr[rt])
                elif ieee:
                    put(sa, ieee_div(f(rd), f(rt)))
                else:
                    put(sa, f(rd) / f(rt) if f(rt) else 0.0)
            elif fn == 0x04:                          # sqrt.s fd, ft
                put(sa, ieee_sqrt(self._sqrt_arg(f(rt), pc)))
            elif fn == 0x05:                          # abs.s
                self.fpr[sa] = self.fpr[rd] & 0x7FFFFFFF
            elif fn == 0x06:
                self.fpr[sa] = self.fpr[rd]
            elif fn == 0x07:                          # neg.s
                self.fpr[sa] = self.fpr[rd] ^ 0x80000000
            elif fn == 0x24:                          # cvt.w.s
                if ieee:
                    self.fpr[sa] = ee_trunc_w(f(rd)) & M32
                else:
                    self.fpr[sa] = int(f(rd)) & M32
            elif fn == 0x28:                          # max.s
                a, b = f(rd), f(rt)
                self.fpr[sa] = self.fpr[rt] if a < b else self.fpr[rd]
            elif fn == 0x29:                          # min.s
                a, b = f(rd), f(rt)
                self.fpr[sa] = self.fpr[rt] if b < a else self.fpr[rd]
            elif fn == 0x30:                          # c.f.s
                self.fcc = False
            elif fn == 0x32:                          # c.eq.s
                self.fcc = f(rd) == f(rt)
            elif fn == 0x34:                          # c.lt.s
                self.fcc = f(rd) < f(rt)
            elif fn == 0x36:                          # c.le.s
                self.fcc = f(rd) <= f(rt)
            else:
                raise MipsError("cop1.s 0x%02x at 0x%08x" % (fn, pc))
        elif rs == 0x14:                              # word
            if fn == 0x20:                            # cvt.s.w
                put(sa, float(s32(self.fpr[rd])))
            else:
                raise MipsError("cop1.w 0x%02x at 0x%08x" % (fn, pc))
        else:
            raise MipsError("cop1 rs=0x%02x at 0x%08x" % (rs, pc))
        return None

    # ---- COP2: VU0 in macro mode -----------------------------------------
    #
    # Lane arithmetic is IEEE single, one rounding per operation, which is
    # what the port's C does lane by lane. A multiply-add is two roundings --
    # the product, then the sum -- because the port is built with
    # -ffp-contract=off and so never fuses one.

    def _vput(self, i, lanes, mask):
        """Write the lanes whose bit is set in `mask` (8 = x ... 1 = w);
        vf00 is read-only."""
        if i == 0:
            return
        r = self.vf[i]
        for k in range(4):
            if mask & (8 >> k):
                r[k] = lanes[k] & M32

    def _acc_put(self, lanes, mask):
        for k in range(4):
            if mask & (8 >> k):
                self.acc[k] = lanes[k] & M32

    def _cop2(self, w, rs, rt, rd, sa, fn, pc):
        ft, fs, fd = rt, rd, sa
        if not (w >> 25) & 1:
            if rs == 1:                               # qmfc2
                v = self.vf[fs]
                self.reg[ft] = v[0] | (v[1] << 32) | (v[2] << 64) | (v[3] << 96)
            elif rs == 5:                             # qmtc2
                x = self.reg[ft]
                self._vput(fs, [(x >> (32 * k)) & M32 for k in range(4)], 15)
            elif rs == 6 and fs == 21:                # ctc2 rt, vi21 (I)
                self.i = self.reg[ft] & M32
            elif rs == 6 and fs == 18:                # ctc2 rt, vi18 (clip)
                self.clip = self.reg[ft] & 0xFFFFFF
            elif rs == 2 and fs == 18:                # cfc2 rt, vi18 (clip)
                self.reg[ft] = self.clip
            else:
                raise MipsError("cop2 transfer rs=0x%02x at 0x%08x" % (rs, pc))
            return
        mask = (w >> 21) & 15
        F = fbits_to
        B = f_to_bits
        S, T = list(self.vf[fs]), list(self.vf[ft])

        def lanes(op, a, b):
            return [B(op(F(a[k]), F(b[k]))) for k in range(4)]

        add = lambda x, y: x + y
        sub = lambda x, y: x - y
        mul = lambda x, y: x * y

        def vmax(x, y):
            return y if x < y else x

        def vmin(x, y):
            return y if y < x else x

        def madd(acc, x, y):
            return [B(F(acc[k]) + F(B(F(x[k]) * F(y[k])))) for k in range(4)]

        def msub(acc, x, y):
            return [B(F(acc[k]) - F(B(F(x[k]) * F(y[k])))) for k in range(4)]

        if fn < 0x3c:
            if fn < 0x1c:                             # the .bc forms
                kind, bc = fn >> 2, fn & 3
                Tb = [T[bc]] * 4
                if kind == 0:
                    r = lanes(add, S, Tb)
                elif kind == 1:
                    r = lanes(sub, S, Tb)
                elif kind == 2:                       # vmadd.bc
                    r = madd(self.acc, S, Tb)
                elif kind == 3:                       # vmsub.bc
                    r = msub(self.acc, S, Tb)
                elif kind == 4:
                    r = lanes(vmax, S, Tb)
                elif kind == 5:
                    r = lanes(vmin, S, Tb)
                else:
                    r = lanes(mul, S, Tb)
                self._vput(fd, r, mask)
            elif fn == 0x1c:                          # vmulq
                self._vput(fd, lanes(mul, S, [self.q] * 4), mask)
            elif fn == 0x1e:                          # vmuli
                self._vput(fd, lanes(mul, S, [self.i] * 4), mask)
            elif fn == 0x20:                          # vaddq
                self._vput(fd, lanes(add, S, [self.q] * 4), mask)
            elif fn == 0x24:                          # vsubq
                self._vput(fd, lanes(sub, S, [self.q] * 4), mask)
            elif fn == 0x28:
                self._vput(fd, lanes(add, S, T), mask)
            elif fn == 0x29:
                self._vput(fd, madd(self.acc, S, T), mask)
            elif fn == 0x2a:
                self._vput(fd, lanes(mul, S, T), mask)
            elif fn == 0x2b:
                self._vput(fd, lanes(vmax, S, T), mask)
            elif fn == 0x2c:
                self._vput(fd, lanes(sub, S, T), mask)
            elif fn == 0x2d:
                self._vput(fd, msub(self.acc, S, T), mask)
            elif fn == 0x2e:                          # vopmsub
                Sr = [S[1], S[2], S[0], 0]
                Tr = [T[2], T[0], T[1], 0]
                self._vput(fd, msub(self.acc, Sr, Tr), mask & 14)
            elif fn == 0x2f:
                self._vput(fd, lanes(vmin, S, T), mask)
            else:
                raise MipsError("vu0 fn 0x%02x at 0x%08x" % (fn, pc))
            return

        idx = (w & 3) | ((w >> 4) & 0x7C)
        acc = self.acc
        if idx < 0x10:                                # vadda/vsuba/vmadda/vmsuba .bc
            kind, bc = idx >> 2, w & 3
            Tb = [T[bc]] * 4
            r = (lanes(add, S, Tb), lanes(sub, S, Tb), madd(acc, S, Tb),
                 msub(acc, S, Tb))[kind]
            self._acc_put(r, mask)
        elif 0x18 <= idx < 0x1c:                      # vmula.bc
            self._acc_put(lanes(mul, S, [T[w & 3]] * 4), mask)
        elif idx == 0x1f:                             # vclipw.xyz
            # Six flags, +x -x +y -y +z -z from bit 0, each lane against
            # |ft.w|, shifted in below the three older sets.
            lim = abs(F(T[3]))
            flags = 0
            for k in range(3):
                v = F(S[k])
                flags |= (lim < v) << (2 * k)
                flags |= (v < -lim) << (2 * k + 1)
            self.clip = ((self.clip << 6) | flags) & 0xFFFFFF
        elif idx == 0x1d:                             # vabs
            self._vput(ft, [x & 0x7FFFFFFF for x in S], mask)
        elif idx == 0x28:
            self._acc_put(lanes(add, S, T), mask)
        elif idx == 0x29:
            self._acc_put(madd(acc, S, T), mask)
        elif idx == 0x2a:
            self._acc_put(lanes(mul, S, T), mask)
        elif idx == 0x2c:
            self._acc_put(lanes(sub, S, T), mask)
        elif idx == 0x2d:
            self._acc_put(msub(acc, S, T), mask)
        elif idx == 0x2e:                             # vopmula
            Sr = [S[1], S[2], S[0], 0]
            Tr = [T[2], T[0], T[1], 0]
            self._acc_put(lanes(mul, Sr, Tr), mask & 14)
        elif idx == 0x2f:                             # vnop
            pass
        elif idx == 0x30:                             # vmove
            self._vput(ft, S, mask)
        elif idx == 0x31:                             # vmr32: rotate lanes
            self._vput(ft, [S[1], S[2], S[3], S[0]], mask)
        elif idx in (0x38, 0x3a):                     # vdiv / vrsqrt
            fsf, ftf = (w >> 21) & 3, (w >> 23) & 3
            a, b = F(S[fsf]), F(T[ftf])
            if idx == 0x3a:
                b = F(B(ieee_sqrt(self._sqrt_arg(b, pc))))
            if self.eediv and not B(b) & 0x7F800000:
                self.eediv_pcs.add(pc)
                self.q = ee_div_zero(S[fsf], B(b))
            else:
                self.q = B(ieee_div(a, b))
        elif idx == 0x39:                             # vsqrt
            self.q = B(ieee_sqrt(self._sqrt_arg(F(T[(w >> 23) & 3]), pc)))
        elif idx == 0x3b:                             # vwaitq
            pass
        elif idx == 0x14:                             # vftoi0
            self._vput(ft, [ee_trunc_w(F(x)) & M32 for x in S], mask)
        else:
            raise MipsError("vu0 special 0x%02x at 0x%08x" % (idx, pc))

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
        if fn in (0x00, 0x01):                        # madd / maddu
            # HI:LO's low words as one 64-bit accumulator, plus the
            # product; each half goes back sign-extended, and rd gets LO.
            acc = ((self.hi & M32) << 32) | (self.lo & M32)
            a, b = (s32(reg[rs]), s32(reg[rt])) if fn == 0x00 else \
                   (reg[rs] & M32, reg[rt] & M32)
            acc = (acc + a * b) & M64
            self.lo, self.hi = s32(acc) & M64, s32(acc >> 32) & M64
            if rd:
                reg[rd] = self.lo
        elif fn == 0x28 and sa == 0x03:               # pminw
            reg[rd] = self._pack_words(
                [min(a, b) for a, b in zip(self._words(reg[rs]),
                                           self._words(reg[rt]))])
        elif fn in (0x18, 0x19):                      # mult1 / multu1
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
        elif fn == 0x08 and sa == 0x12:               # pextlw
            a, b = self._words(reg[rs]), self._words(reg[rt])
            reg[rd] = self._pack_words([b[0], a[0], b[1], a[1]])
        elif fn == 0x28 and sa == 0x12:               # pextuw
            a, b = self._words(reg[rs]), self._words(reg[rt])
            reg[rd] = self._pack_words([b[2], a[2], b[3], a[3]])
        elif fn == 0x09 and sa == 0x1f:               # prot3w
            b = self._words(reg[rt])
            reg[rd] = self._pack_words([b[1], b[2], b[0], b[3]])
        elif fn == 0x09 and sa == 0x1e:               # pexew
            b = self._words(reg[rt])
            reg[rd] = self._pack_words([b[2], b[1], b[0], b[3]])
        elif fn == 0x29 and sa == 0x1e:               # pexcw
            b = self._words(reg[rt])
            reg[rd] = self._pack_words([b[0], b[2], b[1], b[3]])
        elif fn == 0x29 and sa == 0x12:               # por
            reg[rd] = (reg[rs] | reg[rt]) & M128
        elif fn == 0x29 and sa == 0x13:               # pnor
            reg[rd] = ~(reg[rs] | reg[rt]) & M128
        elif fn == 0x09 and sa == 0x12:               # pand
            reg[rd] = reg[rs] & reg[rt] & M128
        elif fn == 0x09 and sa == 0x13:               # pxor
            reg[rd] = (reg[rs] ^ reg[rt]) & M128
        elif fn == 0x08 and sa == 0x03:               # pmaxw
            reg[rd] = self._pack_words(
                [max(a, b) for a, b in zip(self._words(reg[rs]),
                                           self._words(reg[rt]))])
        elif fn == 0x09 and sa == 0x08:               # pmfhi
            reg[rd] = self.hi & M128
        elif fn == 0x09 and sa == 0x09:               # pmflo
            reg[rd] = self.lo & M128
        elif fn == 0x28 and sa == 0x1b:               # qfsrv
            # rs:rt as 256 bits, shifted right by SA, the low 128 kept:
            # with mtsab, 16 bytes from an unaligned address.
            reg[rd] = ((((reg[rs] & M128) << 128) | (reg[rt] & M128))
                       >> self.sa) & M128
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
