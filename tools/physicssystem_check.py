"""Cross-check PhysicsSystem, the ticker and p32 against a model of the image.

    3DS Files/source/physicssystem.{c,h}   PhysicsSystem.obj, 0x00192438
    3DS Files/source/bticker.{c,h}         the ticker, 0x00238d08
    3DS Files/source/p32.{c,h}             the port's 32-bit pointer slot

PhysicsSystem is a list of PhysicsComponents and an integrator over the
concatenation of their states. It has no arithmetic of its own to speak of
-- Euler is one multiply-add a float, RK4 four scaled array sums -- so what
this checker is really about is **order**: which virtual is called on which
component when, with which offset into which array, and when the walk
reads the next link. Every one of those is visible in the listing and
invisible in the shape of the code:

**Every walk asks each component its size again, after the slot call.**
GetDerivative, GetState(float *) and SetState(float *) are one loop with a
different slot at 0x0019299c / 0x00192a24 / 0x00192aac, and in all three
GetSize is the second call, not the first, so a component that changes its
size inside GetDerivative moves every component after it.

**The next link is read after the calls, not before.** `lw s0,0(s0)` at
0x001929c0 comes after both jalrs. A component that splices a new node in
after itself during the call gets that node walked. IntegrateEuler reads it
after GetState() and before writing the state (0x001925fc), and
ComputeAuxiliaries after the call (0x00192b38).

**A size that is not positive still moves the offset.** 0x001925f4 is a
`blez` around the update loop only; `addu v1,s2,s1` is on both arms. So
does every walk: nothing guards the `addu s2,s2,v0`.

**IntegrateRungeKutta re-reads Size before every array call** (`lw a2,8(s0)`
eleven times), and **takes k1 and k2 over a half step** with weights of
1/3, 2/3, 1/3 and 1/6 -- which is classical RK4 written with h = dt/2.

**AddComponent reads Size after GetSize returns.** 0x00192560. A GetSize
that moves Size itself is not overwritten.

**~PhysicsSystem stores its own vptr first**, then destroys every
component with flags 3, rereading the head after each destructor
(0x001924d8) -- so a PhysicsSystem owns and frees its components.

**bGetTickerDifference divides by 300 MHz**, not the EE's 294.912, and
converts an unsigned difference in two steps because cvt.s.w is signed:
`((d >> 1) | (d & 1))` converted and doubled. That is exactly the correctly
rounded unsigned conversion, which is why one mutation below is equivalent.

Every constant, slot, offset and size here is read from the ELF -- by
decoding the instruction at a listed address, from gp, from a vtable in
.data, or from the mdebug record -- and none from the port's headers.

    python tools/physicssystem_check.py
    python tools/physicssystem_check.py --mutate
    python tools/physicssystem_check.py --dump out/physicssystem
"""
import argparse
import difflib
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import bmath_check
import bvector_check

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
CR = chr(13)

SOURCES = [
    "tools/src/physicssystem_test.c",
    "3DS Files/source/physicssystem.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/bticker.c",
    "3DS Files/source/p32.c",
    "3DS Files/source/vtable.c",
    # ~PhysicsComponent is physicscomponent_fini, which rigidbody.c has
    # carried since the RigidBody slice; it brings its own includes.
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

PSC = "3DS Files/source/physicssystem.c"
PSH = "3DS Files/source/physicssystem.h"
TKC = "3DS Files/source/bticker.c"
TKH = "3DS Files/source/bticker.h"
P32C = "3DS Files/source/p32.c"

ELF = bmath_check.ELF
f32 = bmath_check.f32
bits = bmath_check.bits
fadd = bvector_check.fadd
fsub = bvector_check.fsub
fmul = bvector_check.fmul
fdiv = bvector_check.fdiv


def u32(x):
    return x & 0xffffffff


def s32(x):
    x = u32(x)
    return x - 0x100000000 if x & 0x80000000 else x


def g9(x):
    return "%.9g" % x


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


# ============================================================= the image

GP = 0x00328bf0

OP_ADDIU, OP_LUI, OP_LH, OP_LW, OP_SW = 0x09, 0x0f, 0x21, 0x23, 0x2b
OP_LWC1, OP_SD = 0x31, 0x3f


def insn(addr):
    return struct.unpack("<I", ELF.read(addr, 4))[0]


def imm(addr, op):
    """The signed immediate of the instruction at `addr`, which must have
    major opcode `op`, so a listing address that drifts fails here."""
    w = insn(addr)
    assert w >> 26 == op, (hex(addr), hex(w), op)
    v = w & 0xffff
    return v - 0x10000 if v & 0x8000 else v


def lui_float(addr):
    """A float built with `lui at,hi` -- the low half is zero."""
    w = insn(addr)
    assert w >> 26 == OP_LUI, hex(addr)
    return bits((w & 0xffff) << 16)


def gp_word(lwc1_addr):
    return struct.unpack("<I", ELF.read(GP + imm(lwc1_addr, OP_LWC1), 4))[0]


def slot_at(lh_addr):
    """A dispatch's slot: `lh a0,S(vt)` with `lw fn,S+4(vt)` beside it --
    after it at most sites, before it at a few (AddComponent's)."""
    s = imm(lh_addr, OP_LH)
    near = [a for a in (lh_addr + 4, lh_addr - 4) if insn(a) >> 26 == OP_LW]
    assert any(imm(a, OP_LW) == s + 4 for a in near), hex(lh_addr)
    return s


def sym(name):
    return ELF.syms[name][0]


def vt_entries(name, n):
    a = sym(name)
    return [struct.unpack("<hhI", ELF.read(a + 8 * i, 8)) for i in range(n)]


def vt_slot_of(table, n, fn_name):
    """The byte offset of the entry in `table` that points at `fn_name`."""
    want = sym(fn_name)
    hits = [8 * i for i, e in enumerate(vt_entries(table, n)) if e[2] == want]
    assert len(hits) == 1, (table, fn_name, hits)
    return hits[0]


MDEBUG = (ROOT / "docs" / "mdebug_structs.txt").read_text(encoding="utf-8")


def mdebug_record(name):
    m = re.search(r"^struct/class %s \(size=(\d+) bytes\).*?(?=^struct/class )"
                  % re.escape(name), MDEBUG, re.S | re.M)
    assert m, name
    return int(m.group(1)), m.group(0)


PS_VT = sym("_vt$13PhysicsSystem")
PC_VT = sym("_vt$16PhysicsComponent")
# The constructor builds the same address: lui v1,0x2a ; addiu v1,v1,-30968.
assert (((insn(0x00192460) & 0xffff) << 16)
        + imm(0x00192468, OP_ADDIU)) == PS_VT
# And ~PhysicsComponent its base's: lui v0,0x2a ; addiu v0,v0,-30936.
assert (((insn(0x00192438) & 0xffff) << 16)
        + imm(0x00192440, OP_ADDIU)) == PC_VT

SYS_SIZE, _SYS_REC = mdebug_record("PhysicsSystem")
PC_SIZE, _PC_REC = mdebug_record("PhysicsComponent")

OFF_SIZE = imm(0x00192bf4, OP_LW)        # GetSize: jr ra ; lw v0,8(a0)
OFF_SYS_VT = imm(0x00192470, OP_SW)      # ctor: sw v1,12(a0)
OFF_PC_VT = imm(0x0019253c, OP_LW)       # AddComponent: lw v1,8(a1)
# The mdebug record says the same, in bits.
assert "Size:/01,%d,32;" % (OFF_SIZE * 8) in _SYS_REC
assert "vf4539:148,%d" % (OFF_SYS_VT * 8) in _SYS_REC
assert "vf4508:148,%d" % (OFF_PC_VT * 8) in _PC_REC

# ~PhysicsSystem's dispatch loads the function first: lw a2,12(v1) ;
# lh a0,8(v1).
SLOT_DTOR = imm(0x001924cc, OP_LH)
assert imm(0x001924c8, OP_LW) == SLOT_DTOR + 4
assert imm(0x00192bb4, OP_LH) == SLOT_DTOR     # and ~bTList's
SLOT_GET_SIZE = slot_at(0x00192554)            # AddComponent
assert slot_at(0x001925c0) == SLOT_GET_SIZE    # IntegrateEuler
assert slot_at(0x001929b0) == SLOT_GET_SIZE    # GetDerivative
SLOT_GET_STATE = slot_at(0x001925d8)           # IntegrateEuler, GetState()
SLOT_GET_STATE_ARRAY = slot_at(0x00192a24)     # GetState(float *)
SLOT_SET_STATE_ARRAY = slot_at(0x00192aac)     # SetState(float *)
SLOT_RESOLVE = vt_slot_of("_vt$16PhysicsComponent", 9,
                          "ResolveForces__16PhysicsComponent")
SLOT_GET_DERIV = slot_at(0x0019299c)           # GetDerivative
SLOT_AUX = slot_at(0x00192b28)                 # ComputeAuxiliaries

SYS_SLOT_DTOR = vt_slot_of("_vt$13PhysicsSystem", 4, "_$_13PhysicsSystem")
SYS_SLOT_AUX = slot_at(0x00192654)             # IntegrateEuler's last call
assert slot_at(0x001927c8) == SYS_SLOT_AUX     # and RK's first
SYS_SLOT_RESOLVE = vt_slot_of("_vt$13PhysicsSystem", 4,
                              "ResolveForces__13PhysicsSystem")
assert vt_slot_of("_vt$13PhysicsSystem", 4,
                  "ComputeAuxiliaries__13PhysicsSystem") == SYS_SLOT_AUX

# The mdebug record's virtual indices, *N, are the slot over eight.
for _meth, _slot in (("GetSize", SLOT_GET_SIZE),
                     ("ResolveForces", SLOT_RESOLVE),
                     ("GetDerivative", SLOT_GET_DERIV),
                     ("ComputeAuxiliaries", SLOT_AUX)):
    assert re.search(r"%s::[^\n]*\*%d;4508" % (_meth, _slot // 8), _PC_REC), \
        _meth
assert "*%d;4508;4518" % (SLOT_GET_STATE // 8) in _PC_REC
assert ":Pf;2A*%d;4508" % (SLOT_GET_STATE_ARRAY // 8) in _PC_REC
assert "SetState::4518:Pf;2A*%d;4508" % (SLOT_SET_STATE_ARRAY // 8) in _PC_REC

# The 140: IntegrateEuler's derivative is at sp and its first register save
# at sp+560; RK's seven arrays are 560 bytes apart.
_EULER_SAVE = imm(0x0019259c, OP_SD)
_RK_Y0 = imm(0x00192734, OP_ADDIU)
assert _EULER_SAVE == _RK_Y0 == 560
assert imm(0x001927a0, OP_ADDIU) == 2 * _RK_Y0        # y
assert imm(0x00192784, OP_ADDIU) == 3 * _RK_Y0        # k1
assert imm(0x001927e4, OP_ADDIU) == 4 * _RK_Y0        # k2
assert imm(0x0019283c, OP_ADDIU) == 5 * _RK_Y0        # k3
assert imm(0x00192894, OP_ADDIU) == 6 * _RK_Y0        # k4
MAX_STATE = _RK_Y0 // 4

RK_THIRD_W = gp_word(0x0019276c)
RK_TWO_THIRDS_W = gp_word(0x001928cc)
RK_SIXTH_W = gp_word(0x001928fc)
RK_THIRD = bits(RK_THIRD_W)
RK_TWO_THIRDS = bits(RK_TWO_THIRDS_W)
RK_SIXTH = bits(RK_SIXTH_W)
RK_HALF = lui_float(0x0019277c)

TICK_HZ_W = gp_word(0x00238d58)
TICK_HZ = bits(TICK_HZ_W)
TICK_MS = lui_float(0x00238d5c)
FIX_DIV = imm(0x00238d7c, OP_ADDIU)
_w = insn(0x00238d80)
assert _w >> 26 == 0 and _w & 0x3f == 0, hex(_w)      # sll
FIX_SHIFT = (_w >> 6) & 31

# The harness's own tables, at addresses the image does not use.
FAKE_VT_A = 0x00a00000
FAKE_VT_B = 0x00a00100
FAKE_SYS_VT = 0x00b00000

# ============================================================== output

OUT = []


def emit(s):
    OUT.append(s)


# ======================================================== the ticker

class Ticks(object):
    source = False
    nxt = step = accel = 0


TK = Ticks()


def ticks(start, step, accel):
    TK.source = True
    TK.nxt, TK.step, TK.accel = start, step, accel


def tick():
    """bGetTicker. With no source installed the host's counter is 0."""
    if not TK.source:
        return 0
    v = TK.nxt
    TK.nxt = u32(TK.nxt + TK.step)
    TK.step = u32(TK.step + TK.accel)
    return v


def tick_diff(frm, to):
    """bGetTickerDifference, 0x00238d20."""
    d = u32(to - frm)                          # subu v0,a1,a0
    half = d >> 1                              # srl v1,v0,1 (delay slot)
    if d < 0x80000000:                         # bltz
        f = f32(float(d))                      # cvt.s.w
    else:
        f = f32(float((d & 1) | half))         # andi ; or ; cvt.s.w
        f = fadd(f, f)                         # add.s f2,f2,f2
    return fmul(fdiv(f, TICK_HZ), TICK_MS)     # div.s ; mul.s


def tick_fix(frm, to):
    """bGetFixTickerDifference, 0x00238d78."""
    return u32(u32(to - frm) << FIX_SHIFT) // FIX_DIV


# ======================================================== arrays

class Arrays(object):
    bases = []


ARRS = Arrays()


def arr_reset():
    ARRS.bases = []


def arr_name(arr, off):
    """The harness names a pointer by the array it first saw it in."""
    for i, (a, base) in enumerate(ARRS.bases):
        if a is arr and base <= off < base + MAX_STATE:
            return "a%d+%d" % (i, off - base)
    ARRS.bases.append((arr, off))
    return "a%d+0" % (len(ARRS.bases) - 1)


def stack_array():
    # Uninitialised on the console; a read of one of these Nones is a model
    # reading a float the harness never wrote.
    return [None] * MAX_STATE


# ======================================================== the fakes

FK_INSERT_DERIV = 1
FK_INSERT_GETSTATE = 2
FK_INSERT_AUX = 4
FK_MEDDLE = 8
FK_SHRINK = 16
FK_UNLINK_NEXT = 32
FK_DROP = 64


class Sys(object):
    def __init__(self):
        self.next = self.prev = None
        self.size = 0
        self.vt = 0xabababab


class Fake(object):
    def __init__(self, cid, size, flags, gain, bias, st0, outer=False):
        self.next = self.prev = None
        self.vt = FAKE_VT_B if outer else FAKE_VT_A
        self.id = cid
        self.size = size
        self.flags = flags
        self.gain = f32(gain)
        self.bias = f32(bias)
        self.aux = 0.0
        self.pending = None
        # st0 + (float)i * 0.25f
        self.state = [fadd(f32(st0), fmul(f32(i), 0.25)) for i in range(8)]

    @property
    def via(self):
        return "B:" if self.vt == FAKE_VT_B else ""


class G(object):
    sys = None


def node_name(n):
    return "head" if n is G.sys else "c%d" % n.id


def splice_after(f):
    z = f.pending
    n = f.next
    f.pending = None
    z.next = f.next
    z.prev = f
    n.prev = z
    f.next = z
    emit("  insert c%d after c%d" % (z.id, f.id))


def fk_get_size(f):
    emit("  %ssize c%d -> %d" % (f.via, f.id, f.size))
    if f.flags & FK_MEDDLE:
        G.sys.size = s32(G.sys.size + 100)
        emit("  meddle Size -> %d" % G.sys.size)
    return f.size


def fk_get_state(f):
    emit("  %sstate c%d" % (f.via, f.id))
    if (f.flags & FK_INSERT_GETSTATE) and f.pending:
        splice_after(f)
    return f.state, 0


def fk_get_state_array(f, arr, off):
    nm = arr_name(arr, off)
    vals = []
    for i in range(f.size):
        arr[off + i] = f.state[i]
        vals.append(" " + g9(arr[off + i]))
    emit("  %sgetstate c%d %s%s" % (f.via, f.id, nm, "".join(vals)))


def fk_set_state_array(f, arr, off):
    nm = arr_name(arr, off)
    vals = []
    for i in range(f.size):
        v = arr[off + i]
        assert v is not None, ("uninitialised read", f.id, off + i)
        f.state[i] = v
        vals.append(" " + g9(v))
    emit("  %ssetstate c%d %s%s" % (f.via, f.id, nm, "".join(vals)))
    if f.flags & FK_DROP:
        G.sys.size = s32(G.sys.size - 1)
        emit("  drop Size -> %d" % G.sys.size)


def fk_get_derivative(f, arr, off):
    nm = arr_name(arr, off)
    vals = []
    for i in range(f.size):
        a = fmul(f.gain, f.state[i])
        b = fmul(f.bias, f32(i + 1))
        c = fmul(0.25, f.aux)
        arr[off + i] = fadd(fadd(a, b), c)
        vals.append(" " + g9(arr[off + i]))
    emit("  %sderiv c%d %s%s" % (f.via, f.id, nm, "".join(vals)))
    if (f.flags & FK_SHRINK) and f.size > 0:
        f.size -= 1
        emit("  shrink c%d -> %d" % (f.id, f.size))
    if (f.flags & FK_INSERT_DERIV) and f.pending:
        splice_after(f)


def fk_aux(f):
    s = 0.0
    for i in range(f.size):
        s = fadd(s, f.state[i])
    f.aux = fadd(fmul(f.aux, 0.5), s)
    emit("  %saux c%d %s" % (f.via, f.id, g9(f.aux)))
    if (f.flags & FK_INSERT_AUX) and f.pending:
        splice_after(f)


def fk_dtor(f, flags):
    emit("  %sdtor c%d %d links %s %s sysvt %08x"
         % (f.via, f.id, flags, node_name(f.next), node_name(f.prev),
            G.sys.vt))
    if f.flags & FK_UNLINK_NEXT:
        n = f.next
        if n is not G.sys:
            np_, nn = n.prev, n.next
            np_.next = n.next
            nn.prev = n.prev
            emit("  unlink c%d" % n.id)


# ================================================ the dispatches

def c_dtor(c, flags):
    if c.vt in (FAKE_VT_A, FAKE_VT_B):
        fk_dtor(c, flags)
    elif c.vt == PC_VT:
        # ~PhysicsComponent: its own vptr, then ~bNode. The delete is not
        # something a transcript sees.
        c.vt = PC_VT
    else:
        raise AssertionError("dtor through %08x" % c.vt)


def c_get_size(c):
    assert c.vt in (FAKE_VT_A, FAKE_VT_B), "__pure_virtual"
    return fk_get_size(c)


def c_get_state(c):
    assert c.vt in (FAKE_VT_A, FAKE_VT_B), "__pure_virtual"
    return fk_get_state(c)


def c_aux(c):
    if c.vt == PC_VT:
        return                               # 0x00192bf8, jr ra
    fk_aux(c)


def c_resolve(c):
    if c.vt == PC_VT:
        return                               # 0x00192c00, jr ra
    raise AssertionError("the system never resolves a component")


def sys_aux(s):
    """The virtual ComputeAuxiliaries, through the system's own vptr."""
    if s.vt == PS_VT:
        ps_compute_auxiliaries(s)
    elif s.vt == FAKE_SYS_VT:
        emit("  derived-aux")
        ps_compute_auxiliaries(s)
    else:
        raise AssertionError("aux through %08x" % s.vt)


def sys_dtor(s, flags):
    if s.vt == PS_VT:
        ps_fini(s, flags)
    else:
        raise AssertionError("dtor through %08x" % s.vt)


# ================================================ PhysicsSystem

class Aux(object):
    time = 0.0


AUX = Aux()


def ps_init(s):
    """0x00192460: Next, vptr, Prev, Size."""
    s.next = s
    s.vt = PS_VT
    s.prev = s
    s.size = 0


def destroy_components(s):
    """The loop at 0x001924b0, and ~bTList's at 0x00192b98."""
    c = s.next
    while c is not s:
        nx = c.next                          # lw a0,0(a3)
        pv = c.prev                          # lw v0,4(a3)
        pv.next = nx                         # sw a0,0(v0)
        nx.prev = pv                         # sw v0,4(a0)
        c_dtor(c, 3)                         # addiu a1,zero,3 ; jalr
        c = s.next                           # lw v0,0(s0)


def ps_fini(s, flags):
    """0x00192480."""
    s.vt = PS_VT                             # sw v0,12(s0), first
    destroy_components(s)
    # jal ~bTList(s, 2): the same loop again, over an empty list, then
    # ~bList(2) -> ~bNode(2), and neither frees with bit 0 clear.
    destroy_components(s)
    # `andi s1,a1,1` -> __builtin_delete: not visible to a transcript.


def ps_add_component(s, c):
    """0x00192528."""
    tail = s.prev                            # lw v0,4(s0)
    # lw v1,8(a1): the vptr, before any link is written
    tail.next = c                            # sw a1,0(v0)
    s.prev = c                               # sw a1,4(s0)
    c.prev = tail                            # sw v0,4(a1)
    c.next = s                               # sw s0,0(a1)
    v = c_get_size(c)                        # jalr
    s.size = s32(s.size + v)                 # lw v1,8(s0) after the call


def walk(s, arr, fn):
    """GetDerivative / GetState(float *) / SetState(float *), 0x00192960
    and the two beside it: the slot, then GetSize, then the next link."""
    c = s.next
    n = 0
    while c is not s:
        fn(c, arr, n)
        n = s32(n + c_get_size(c))
        c = c.next


def ps_get_derivative(s, arr):
    walk(s, arr, fk_get_derivative)


def ps_get_state(s, arr):
    walk(s, arr, fk_get_state_array)


def ps_set_state(s, arr):
    walk(s, arr, fk_set_state_array)


def ps_integrate_euler(s, dt):
    """0x00192580."""
    dt = f32(dt)
    d = stack_array()
    ps_get_derivative(s, d)                  # a1 = sp
    off = 0
    c = s.next
    while c is not s:
        size = c_get_size(c)                 # 0x001925c8
        st, so = c_get_state(c)              # 0x001925e0, vptr reloaded
        nx = c.next                          # 0x001925fc / 0x00192638
        if size > 0:                         # blez s1
            for j in range(size):
                dv = d[off + j]
                assert dv is not None, ("uninitialised read", off + j)
                # lwc1 f0,d ; lwc1 f1,st ; mul.s f0,f20,f0 ; add.s f1,f1,f0
                st[so + j] = fadd(st[so + j], fmul(dt, dv))
        off = s32(off + size)                # addu v1,s2,s1 on both arms
        c = nx
    sys_aux(s)                               # 0x0019265c, the system's vptr


def array_multiply(out, oo, a, ao, sc, n):
    """0x00192688."""
    while n > 0:
        out[oo] = fmul(a[ao], sc)
        oo += 1
        ao += 1
        n -= 1


def array_add(out, oo, a, ao, b, bo, n):
    """0x001926b8."""
    while n > 0:
        out[oo] = fadd(a[ao], b[bo])
        oo += 1
        ao += 1
        bo += 1
        n -= 1


def array_multiply_and_add(out, oo, a, ao, b, bo, sc, n):
    """0x001926f0: f1 = b * s, then a + f1."""
    while n > 0:
        f1 = fmul(b[bo], sc)
        out[oo] = fadd(a[ao], f1)
        oo += 1
        ao += 1
        bo += 1
        n -= 1


def ps_integrate_runge_kutta(s, dt):
    """0x00192728. Size is `lw aN,8(s0)` again before every array call."""
    dt = f32(dt)
    d = stack_array()                        # sp
    y0 = stack_array()                       # sp+560
    y = stack_array()                        # sp+1120
    k1 = stack_array()                       # sp+1680
    k2 = stack_array()                       # sp+2240
    k3 = stack_array()                       # sp+2800
    k4 = stack_array()                       # sp+3360

    ps_get_state(s, y0)
    ps_get_derivative(s, d)
    h = fmul(dt, RK_HALF)                    # mul.s f20,f21,f20

    array_multiply(k1, 0, d, 0, h, s.size)
    array_add(y, 0, y0, 0, k1, 0, s.size)
    ps_set_state(s, y)
    sys_aux(s)
    ps_get_derivative(s, d)

    array_multiply(k2, 0, d, 0, h, s.size)
    array_add(y, 0, y0, 0, k2, 0, s.size)
    ps_set_state(s, y)
    sys_aux(s)
    ps_get_derivative(s, d)

    array_multiply(k3, 0, d, 0, dt, s.size)  # mov.s f12,f21: the full dt
    array_add(y, 0, y0, 0, k3, 0, s.size)
    ps_set_state(s, y)
    sys_aux(s)
    ps_get_derivative(s, d)

    array_multiply(k4, 0, d, 0, dt, s.size)

    array_multiply_and_add(y, 0, y0, 0, k1, 0, RK_THIRD, s.size)
    array_multiply_and_add(y, 0, y, 0, k2, 0, RK_TWO_THIRDS, s.size)
    array_multiply_and_add(y, 0, y, 0, k3, 0, RK_THIRD, s.size)
    array_multiply_and_add(y, 0, y, 0, k4, 0, RK_SIXTH, s.size)

    ps_set_state(s, y)
    sys_aux(s)


def ps_compute_auxiliaries(s):
    """0x00192af8."""
    t0 = tick()
    c = s.next
    while c is not s:
        c_aux(c)
        c = c.next                           # lw s0,0(s0) after the call
    t1 = tick()
    AUX.time = tick_diff(t0, t1)             # swc1 f0,-23232(gp)


# ======================================================== helpers

def install():
    arr_reset()
    TK.source = False


def add(s, c):
    ps_add_component(s, c)


def ring(tag, s):
    fwd, back = [], []
    c, n = s.next, 0
    while c is not s and n < 20:
        fwd.append(" c%d" % c.id)
        c, n = c.next, n + 1
    c, n = s.prev, 0
    while c is not s and n < 20:
        back.append(" c%d" % c.id)
        c, n = c.prev, n + 1
    emit("%s size %d fwd%s | back%s" % (tag, s.size, "".join(fwd),
                                         "".join(back)))


def dump_fake(f):
    emit("c%d size %d aux %s st%s"
         % (f.id, f.size, g9(f.aux), "".join(" " + g9(v) for v in f.state)))


def dump_buf(tag, b):
    emit(tag + "".join(" " + g9(v) for v in b[:8]))


def fill(v):
    return [f32(v)] * MAX_STATE


def aux_line():
    emit("AuxTime %s" % g9(AUX.time))


def heap_fake(cid, size, flags):
    return Fake(cid, size, flags, 1.0, 0.0, float(cid))


# ======================================================== scenarios

def s_layout():
    emit("[layout]")
    emit("layout %d %d %d %d %d"
         % (SYS_SIZE, OFF_SIZE, OFF_SYS_VT, PC_SIZE, OFF_PC_VT))
    emit("vt %08x %08x" % (PS_VT, PC_VT))
    emit("rk %08x %08x %08x" % (RK_THIRD_W, RK_TWO_THIRDS_W, RK_SIXTH_W))
    emit("slots %d %d %d %d %d %d %d %d | %d %d %d"
         % (SLOT_DTOR, SLOT_GET_SIZE, SLOT_GET_STATE, SLOT_GET_STATE_ARRAY,
            SLOT_SET_STATE_ARRAY, SLOT_RESOLVE, SLOT_GET_DERIV, SLOT_AUX,
            SYS_SLOT_DTOR, SYS_SLOT_AUX, SYS_SLOT_RESOLVE))
    emit("max %d" % MAX_STATE)
    emit("tick %08x" % TICK_HZ_W)


def s_add():
    emit("[add]")
    install()
    sys_ = Sys()
    G.sys = sys_
    ps_init(sys_)
    emit("init 1 %08x" % sys_.vt)
    ring("empty", sys_)

    c1 = Fake(1, 3, 0, 0.5, 0.125, 1.0)
    c2 = Fake(2, 0, 0, 1.0, 1.0, 0.0)
    o3 = Fake(3, 2, 0, -1.5, 2.0, -3.0, outer=True)
    c4 = Fake(4, 1, FK_MEDDLE, 3.0, -0.5, 7.0)

    for tag, c in (("1", c1), ("2", c2), ("3", o3), ("4", c4)):
        emit("add c" + tag)
        add(sys_, c)
        ring("r" + tag, sys_)
    emit("get_size %d" % sys_.size)


def s_walk():
    emit("[walk]")
    install()
    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    c1 = Fake(1, 3, 0, 0.5, 0.125, 1.0)
    c2 = Fake(2, 0, 0, 1.0, 1.0, 0.0)
    o3 = Fake(3, 2, 0, -1.5, 2.0, -3.0, outer=True)
    c4 = Fake(4, 1, 0, 3.0, -0.5, 7.0)
    for c in (c1, c2, o3, c4):
        add(sys_, c)
    ring("r", sys_)

    emit("get_state")
    buf = fill(99.0)
    arr_reset()
    ps_get_state(sys_, buf)
    dump_buf("buf", buf)

    emit("set_state")
    buf = [fadd(10.0, fmul(f32(i), 0.5)) for i in range(MAX_STATE)]
    arr_reset()
    ps_set_state(sys_, buf)
    for c in (c1, c2, o3, c4):
        dump_fake(c)

    emit("get_derivative")
    buf = fill(99.0)
    c1.aux = 2.0
    o3.aux = -4.0
    arr_reset()
    ps_get_derivative(sys_, buf)
    dump_buf("buf", buf)

    emit("shrink")
    s2 = Sys()
    ps_init(s2)
    G.sys = s2
    c6 = Fake(6, 2, FK_SHRINK, 1.0, 0.5, 2.0)
    c7 = Fake(7, 2, 0, -1.0, 0.25, 5.0)
    add(s2, c6)
    add(s2, c7)
    for _ in range(2):
        buf = fill(99.0)
        arr_reset()
        ps_get_derivative(s2, buf)
        dump_buf("buf", buf)
    ring("r", s2)

    emit("negative")
    s3 = Sys()
    ps_init(s3)
    G.sys = s3
    c8 = Fake(8, 3, 0, 0.75, 1.5, -1.0)
    c9 = Fake(9, -1, 0, 1.0, 1.0, 0.0)
    c10 = Fake(10, 2, 0, -2.0, 0.5, 3.0)
    for c in (c8, c9, c10):
        add(s3, c)
    ring("r", s3)
    buf = fill(99.0)
    arr_reset()
    ps_get_state(s3, buf)
    dump_buf("buf", buf)
    buf = fill(99.0)
    arr_reset()
    ps_get_derivative(s3, buf)
    dump_buf("buf", buf)
    buf = [-f32(i) for i in range(MAX_STATE)]
    arr_reset()
    ps_set_state(s3, buf)
    dump_fake(c8)
    dump_fake(c10)


def s_insert():
    emit("[insert]")
    install()

    emit("on derivative")
    s1 = Sys()
    ps_init(s1)
    G.sys = s1
    c11 = Fake(11, 2, FK_INSERT_DERIV, 1.0, 1.0, 1.0)
    c12 = Fake(12, 1, 0, 2.0, 0.0, 4.0)
    c13 = Fake(13, 2, 0, -1.0, 0.5, 6.0)
    c11.pending = c12
    add(s1, c11)
    add(s1, c13)
    buf = fill(99.0)
    arr_reset()
    ps_get_derivative(s1, buf)
    dump_buf("buf", buf)
    ring("r", s1)

    emit("on getstate")
    s2 = Sys()
    ps_init(s2)
    G.sys = s2
    c14 = Fake(14, 2, FK_INSERT_GETSTATE, 0.5, 0.25, 1.0)
    c15 = Fake(15, 0, 0, 1.0, 1.0, 9.0)
    c16 = Fake(16, 3, 0, -0.5, 1.0, 2.0)
    c14.pending = c15
    add(s2, c14)
    add(s2, c16)
    ticks(1000, 29491, 7)
    arr_reset()
    ps_integrate_euler(s2, 0.125)
    for c in (c14, c15, c16):
        dump_fake(c)
    aux_line()
    ring("r", s2)

    emit("on aux")
    s3 = Sys()
    ps_init(s3)
    G.sys = s3
    c17 = Fake(17, 1, FK_INSERT_AUX, 1.0, 0.0, 3.0)
    c18 = Fake(18, 2, 0, 1.0, 0.0, 5.0)
    c19 = Fake(19, 1, 0, 1.0, 0.0, -2.0)
    c17.pending = c18
    add(s3, c17)
    add(s3, c19)
    ticks(50, 294912, 0)
    ps_compute_auxiliaries(s3)
    aux_line()
    ring("r", s3)


def build_mixed(s):
    c20 = Fake(20, 3, 0, 0.5, 0.25, 1.0)
    o21 = Fake(21, 2, 0, -0.75, 1.0, 4.0, outer=True)
    c22 = Fake(22, -1, 0, 1.0, 1.0, 0.0)
    c23 = Fake(23, 2, 0, 2.0, -0.125, -2.0)
    for c in (c20, o21, c22, c23):
        add(s, c)
    return c20, o21, c22, c23


def s_euler():
    emit("[euler]")
    install()
    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    c20, o21, c22, c23 = build_mixed(sys_)
    ring("r", sys_)
    ticks(0xfffff000, 2949120, 1234)
    for k in range(3):
        emit("step %d" % k)
        arr_reset()
        ps_integrate_euler(sys_, 0.0166666675)
        for c in (c20, o21, c22, c23):
            dump_fake(c)
        aux_line()

    emit("derived")
    so = Sys()
    ps_init(so)
    so.vt = FAKE_SYS_VT
    G.sys = so
    e20, eo21, e22, e23 = build_mixed(so)
    ticks(77, 100000, 0)
    for k in range(2):
        emit("step %d" % k)
        arr_reset()
        ps_integrate_euler(so, -0.5)
        for c in (e20, eo21, e23):
            dump_fake(c)
        aux_line()

    emit("empty")
    empty = Sys()
    ps_init(empty)
    G.sys = empty
    ticks(5, 3000000, 0)
    ps_integrate_euler(empty, 1.0)
    aux_line()


def s_rk():
    emit("[rk]")
    install()
    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    c20, o21, c22, c23 = build_mixed(sys_)
    ticks(1, 65536, 3)
    for k in range(2):
        emit("step %d" % k)
        arr_reset()
        ps_integrate_runge_kutta(sys_, 0.0199999996)
        for c in (c20, o21, c23):
            dump_fake(c)
        aux_line()

    emit("dropper")
    s2 = Sys()
    ps_init(s2)
    G.sys = s2
    c30 = Fake(30, 2, FK_DROP, -1.25, 0.5, 1.5)
    c31 = Fake(31, 3, 0, 0.75, -0.25, -1.0)
    add(s2, c30)
    add(s2, c31)
    ticks(9, 1000, 0)
    arr_reset()
    ps_integrate_runge_kutta(s2, 0.25)
    dump_fake(c30)
    dump_fake(c31)
    ring("r", s2)

    emit("derived")
    so = Sys()
    ps_init(so)
    so.vt = FAKE_SYS_VT
    G.sys = so
    e20, eo21, e22, e23 = build_mixed(so)
    ticks(123, 4567, 89)
    arr_reset()
    ps_integrate_runge_kutta(so, 0.5)
    for c in (e20, eo21, e23):
        dump_fake(c)
    aux_line()


def s_aux():
    emit("[aux]")
    install()
    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    add(sys_, Fake(1, 2, 0, 1.0, 0.0, 0.5))
    add(sys_, Fake(2, 1, 0, 1.0, 0.0, -3.0))
    starts = (0, 0xfffff000, 0, 100, 7)
    steps = (0, 0x2000, 0x80000081, 0xffffffce, 0x7fffffff)
    for k in range(5):
        ticks(starts[k], steps[k], 0)
        ps_compute_auxiliaries(sys_)
        aux_line()
    # ResolveForces, 0x00192be8: jr ra.
    emit("resolve ok %d" % sys_.size)


def s_tables():
    emit("[tables]")
    install()

    c1 = Fake(1, 2, 0, 1.0, 0.0, 0.5)
    c1.vt = PC_VT
    c_resolve(c1)
    c_aux(c1)
    dump_fake(c1)
    c1.vt = 0x12345678
    c1.vt = PC_VT                            # ~PhysicsComponent, flags 2
    emit("dtor vt %08x" % c1.vt)
    emit("dtor freed")                       # and again with flags 3

    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    c2 = Fake(2, 1, 0, 1.0, 0.0, 6.0)
    add(sys_, c2)
    ticks(0, 2949120, 0)
    sys_aux(sys_)
    aux_line()
    # The system's ResolveForces, jr ra.
    sys_.vt = 0x0badf00d
    ps_fini(sys_, 2)                         # through PS_VT's slot 8
    emit("sys vt %08x" % sys_.vt)
    ring("r", sys_)


def s_dtor():
    emit("[dtor]")
    install()
    sys_ = Sys()
    ps_init(sys_)
    G.sys = sys_
    h40 = heap_fake(40, 1, 0)
    h41 = Fake(41, 2, 0, 1.0, 0.0, 41.0, outer=True)
    h42 = heap_fake(42, 1, FK_UNLINK_NEXT)
    h43 = heap_fake(43, 1, 0)
    h44 = heap_fake(44, 1, 0)
    for c in (h40, h41, h42, h43, h44):
        add(sys_, c)
    ring("r", sys_)
    sys_.vt = FAKE_SYS_VT
    ps_fini(sys_, 0)
    emit("vt %08x" % sys_.vt)
    ring("after", sys_)

    emit("heap")
    hs = Sys()
    ps_init(hs)
    G.sys = hs
    add(hs, heap_fake(45, 2, 0))
    ps_fini(hs, 1)
    emit("freed")


def s_arrays():
    emit("[arrays]")
    # 0.1f * (float)(i + 1) and 3.0f - 0.7f * (float)i: float literals.
    a = [fmul(f32(0.1), f32(i + 1)) for i in range(8)]
    b = [fsub(3.0, fmul(f32(0.7), f32(i))) for i in range(8)]
    for n in (-1, 0, 1, 5, 8):
        emit("n %d" % n)
        o = [77.0] * 8
        array_multiply(o, 0, a, 0, 1.5, n)
        dump_buf("mul", o)
        o = [77.0] * 8
        array_add(o, 0, a, 0, b, 0, n)
        dump_buf("add", o)
        o = [77.0] * 8
        array_multiply_and_add(o, 0, a, 0, b, 0, -0.75, n)
        dump_buf("madd", o)
    o = list(a)
    array_multiply_and_add(o, 0, o, 0, b, 0, RK_THIRD, 8)
    dump_buf("inplace", o)
    o = list(b)
    array_add(o, 0, a, 0, o, 0, 6)
    dump_buf("alias-b", o)


def s_ticker():
    emit("[ticker]")
    TK.source = False
    emit("host %d" % tick())
    pairs = [
        (0, 0), (0, 1), (0, 294912), (100, 50),
        (0xfffffff0, 0x10), (0, 0x7fffffff), (0, 0x80000000),
        (0, 0x80000001), (0, 0x80000003), (0, 0x80000081),
        (0, 0x80000080), (0, 0x80000180), (0, 0xffffffff),
        (0, 0x01000001), (0, 0x01000003), (5, 0x03ffffff),
        (0, 0x04000000), (0, 0x04000005), (1, 0xfffffe00),
        (0x12345678, 0x9abcdef0), (0, 2949120),
    ]
    for frm, to in pairs:
        f = tick_diff(frm, to)
        emit("diff %08x %08x %s %08x %d"
             % (frm, to, g9(f), fbits(f), tick_fix(frm, to)))
    ticks(0xfffffffe, 1, 0x40000000)
    for _ in range(4):
        emit("tick %08x" % tick())
    TK.source = False
    emit("host %d" % tick())


def s_p32():
    emit("[p32]")
    # NULL is handle 0; a pointer seen twice gets one handle; two pointers
    # get two; a handle goes back to its pointer; 0 goes back to NULL.
    emit("p32 0 1 1 1 1 1")


def model():
    del OUT[:]
    s_layout()
    s_add()
    s_walk()
    s_insert()
    s_euler()
    s_rk()
    s_aux()
    s_tables()
    s_dtor()
    s_arrays()
    s_ticker()
    s_p32()
    return list(OUT)


# ============================================================= running

HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line)
    return bad


# ============================================================ mutations
#
# A mutation is (name, file, before, after), or (name, file, [(before,
# after, count), ...]) when one transcription error touches several lines;
# a count of 0 replaces every occurrence.

EUL_HEAD = ("        int32_t size = get_size(c);" + NL
            + "        const VtEntry *e = vt_slot(c->_vtable, "
              "PHYSICSCOMPONENT_VT_GET_STATE);" + NL
            + "        float *st = ((PhysicsGetStateFn)e->fn)"
              "(vt_this(c, e));")
EUL_NEXT = "        PhysicsComponent *n = next(c);   // before the state is written"

DER_CALL = ("        ((PhysicsGetDerivativeFn)e->fn)(vt_this(c, e), out + n);"
            + NL + "        n += get_size(c);")

MUTATIONS = [
    # -- the constructor ----------------------------------------------------
    ("ps-init-size-one", PSC,
     "    sys->Size    = 0;",
     "    sys->Size    = 1;"),
    ("ps-init-vt-component", PSC,
     "    sys->_vtable = PHYSICSSYSTEM_VTABLE;" + NL
     + "    sys->pPrev   = p32_of(sys);",
     "    sys->_vtable = PHYSICSCOMPONENT_VTABLE;" + NL
     + "    sys->pPrev   = p32_of(sys);"),
    ("ps-init-prev-null", PSC,
     "    sys->pPrev   = p32_of(sys);",
     "    sys->pPrev   = 0;"),

    # -- the destructor -----------------------------------------------------
    ("ps-fini-no-vt", PSC,
     "    sys->_vtable = PHYSICSSYSTEM_VTABLE;" + NL
     + "    destroy_components(sys);",
     "    destroy_components(sys);"),
    ("ps-fini-vt-last", PSC,
     "    sys->_vtable = PHYSICSSYSTEM_VTABLE;" + NL
     + "    destroy_components(sys);" + NL + "    tlist_fini(sys, 2);",
     "    destroy_components(sys);" + NL + "    tlist_fini(sys, 2);" + NL
     + "    sys->_vtable = PHYSICSSYSTEM_VTABLE;"),
    ("ps-dtor-flags-1", PSC,
     "        ((PhysicsDtorFn)e->fn)(vt_this(c, e), 3);",
     "        ((PhysicsDtorFn)e->fn)(vt_this(c, e), 1);"),
    ("ps-dtor-follows-saved-next", PSC,
     "        c = first(sys);" + NL + "    }" + NL + "}" + NL + NL
     + "static void tlist_fini",
     "        c = (PhysicsComponent *)n;" + NL + "    }" + NL + "}" + NL + NL
     + "static void tlist_fini"),
    ("ps-dtor-no-prev-fix", PSC,
     "        *link_prev(n) = p32_of(p);" + NL,
     ""),
    ("ps-dtor-no-next-fix", PSC,
     "        *link_next(p) = p32_of(n);" + NL,
     ""),
    ("ps-component-dtor-no-fini", PSC,
     "    physicscomponent_fini(self);" + NL,
     ""),

    # -- AddComponent -------------------------------------------------------
    ("ps-add-size-read-first", PSC,
     "    size = ((PhysicsGetSizeFn)e->fn)(vt_this(c, e));" + NL
     + "    sys->Size = sys->Size + size;",
     "    size = sys->Size;" + NL
     + "    sys->Size = size + ((PhysicsGetSizeFn)e->fn)(vt_this(c, e));"),
    ("ps-add-no-tail-link", PSC,
     "    *link_next(tail) = p32_of(c);" + NL,
     ""),
    ("ps-add-prev-is-head", PSC,
     "    c->pPrev   = p32_of(tail);",
     "    c->pPrev   = p32_of(sys);"),
    ("ps-add-at-head", PSC,
     "    *link_next(tail) = p32_of(c);" + NL
     + "    sys->pPrev = p32_of(c);" + NL
     + "    c->pPrev   = p32_of(tail);" + NL
     + "    c->pNext   = p32_of(sys);",
     "    (void)tail;" + NL
     + "    *link_prev(p32_ptr(sys->pNext)) = p32_of(c);" + NL
     + "    c->pNext   = sys->pNext;" + NL
     + "    c->pPrev   = p32_of(sys);" + NL
     + "    sys->pNext = p32_of(c);"),

    # -- the three walks ----------------------------------------------------
    ("ps-deriv-size-first", PSC,
     DER_CALL,
     "        int32_t k = get_size(c);" + NL
     + "        ((PhysicsGetDerivativeFn)e->fn)(vt_this(c, e), out + n);"
     + NL + "        n += k;"),
    ("ps-deriv-next-first", PSC,
     DER_CALL + NL + "        c = next(c);",
     "        PhysicsComponent *nx = next(c);" + NL + DER_CALL + NL
     + "        c = nx;"),
    ("ps-getstate-setstate-slot", PSC,
     "                                   PHYSICSCOMPONENT_VT_GET_STATE_ARRAY);",
     "                                   PHYSICSCOMPONENT_VT_SET_STATE_ARRAY);"),
    ("ps-getstate-no-offset", PSC,
     "        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), out + n);",
     "        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), out);"),
    ("ps-setstate-no-offset", PSC,
     "        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), (float *)(in + n));",
     "        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), (float *)in);"),

    # -- IntegrateEuler -----------------------------------------------------
    ("ps-euler-state-first", PSC,
     EUL_HEAD,
     "        const VtEntry *e = vt_slot(c->_vtable, "
     "PHYSICSCOMPONENT_VT_GET_STATE);" + NL
     + "        float *st = ((PhysicsGetStateFn)e->fn)(vt_this(c, e));" + NL
     + "        int32_t size = get_size(c);"),
    ("ps-euler-next-before-state", PSC,
     EUL_HEAD + NL + EUL_NEXT,
     "        PhysicsComponent *n = next(c);" + NL + EUL_HEAD),
    ("ps-euler-positive-offset-only", PSC,
     "        off = off + size;",
     "        if (size > 0)" + NL + "            off = off + size;"),
    ("ps-euler-no-dt", PSC,
     "                st[j] = st[j] + dt * dp[j];",
     "                st[j] = st[j] + dp[j];"),
    ("ps-euler-offset-from-zero", PSC,
     "            const float *dp = d + off;",
     "            const float *dp = d;"),
    ("ps-euler-aux-direct", PSC,
     "        c = n;" + NL + "    }" + NL + NL
     + "    system_compute_auxiliaries(sys);",
     "        c = n;" + NL + "    }" + NL + NL
     + "    physicssystem_compute_auxiliaries(sys);"),
    ("ps-euler-no-aux", PSC,
     "        c = n;" + NL + "    }" + NL + NL
     + "    system_compute_auxiliaries(sys);",
     "        c = n;" + NL + "    }" + NL),

    # -- IntegrateRungeKutta ------------------------------------------------
    ("ps-rk-full-step", PSC,
     "    h = dt * 0.5f;",
     "    h = dt;"),
    ("ps-rk-k2-full", PSC,
     "    ArrayMultiply(k2, d, h, sys->Size);",
     "    ArrayMultiply(k2, d, dt, sys->Size);"),
    ("ps-rk-k3-half", PSC,
     "    ArrayMultiply(k3, d, dt, sys->Size);",
     "    ArrayMultiply(k3, d, h, sys->Size);"),
    ("ps-rk-k4-half", PSC,
     "    ArrayMultiply(k4, d, dt, sys->Size);",
     "    ArrayMultiply(k4, d, h, sys->Size);"),
    ("ps-rk-k2-from-y", PSC,
     "    ArrayAdd(y, y0, k2, sys->Size);",
     "    ArrayAdd(y, y, k2, sys->Size);"),
    ("ps-rk-k1-sixth", PSC,
     "    ArrayMultiplyAndAdd(y, y0, k1, third, sys->Size);",
     "    ArrayMultiplyAndAdd(y, y0, k1, PHYSICSSYSTEM_RK_SIXTH, sys->Size);"),
    ("ps-rk-textbook-weights", PSC,
     [("    ArrayMultiplyAndAdd(y, y0, k1, third, sys->Size);",
       "    ArrayMultiplyAndAdd(y, y0, k1, PHYSICSSYSTEM_RK_SIXTH, sys->Size);",
       1),
      ("    ArrayMultiplyAndAdd(y, y, k2, PHYSICSSYSTEM_RK_TWO_THIRDS, "
       "sys->Size);",
       "    ArrayMultiplyAndAdd(y, y, k2, third, sys->Size);", 1)]),
    ("ps-rk-size-cached", PSC,
     [("    float h;" + NL + NL + "    physicssystem_get_state(sys, y0);",
       "    float h;" + NL + "    int32_t cached = sys->Size;" + NL + NL
       + "    physicssystem_get_state(sys, y0);", 1),
      ("sys->Size);", "cached);", 0)]),
    ("ps-rk-state-after-deriv", PSC,
     "    physicssystem_get_state(sys, y0);" + NL
     + "    physicssystem_get_derivative(sys, d);",
     "    physicssystem_get_derivative(sys, d);" + NL
     + "    physicssystem_get_state(sys, y0);"),
    ("ps-rk-no-last-aux", PSC,
     "    physicssystem_set_state(sys, y);" + NL
     + "    system_compute_auxiliaries(sys);" + NL + "}",
     "    physicssystem_set_state(sys, y);" + NL + "}"),

    # -- ComputeAuxiliaries -------------------------------------------------
    ("ps-aux-next-first", PSC,
     "        ((PhysicsVoidFn)e->fn)(vt_this(c, e));" + NL
     + "        c = next(c);",
     "        PhysicsComponent *nx = next(c);" + NL
     + "        ((PhysicsVoidFn)e->fn)(vt_this(c, e));" + NL
     + "        c = nx;"),
    ("ps-aux-args-swapped", PSC,
     "    AuxTime = bGetTickerDifference(t0, bGetTicker());",
     "    AuxTime = bGetTickerDifference(bGetTicker(), t0);"),
    ("ps-aux-no-start-tick", PSC,
     "    uint32_t t0 = bGetTicker();",
     "    uint32_t t0 = 0;"),
    ("ps-sys-vt-aux-resolve-swapped", PSC,
     "    { 0, 0, (VtFn)vt_system_compute_auxiliaries }," + NL
     + "    { 0, 0, (VtFn)vt_system_resolve_forces },",
     "    { 0, 0, (VtFn)vt_system_resolve_forces }," + NL
     + "    { 0, 0, (VtFn)vt_system_compute_auxiliaries },"),

    # -- the three helpers --------------------------------------------------
    ("am-zero-runs", PSC,
     "void ArrayMultiply(float *out, const float *in, float s, int32_t n)"
     + NL + "{" + NL + "    if (n <= 0)",
     "void ArrayMultiply(float *out, const float *in, float s, int32_t n)"
     + NL + "{" + NL + "    if (n < 0)"),
    ("aa-subtracts", PSC,
     "        *out++ = *a++ + *b++;",
     "        *out++ = *a++ - *b++;"),
    ("madd-no-scale", PSC,
     "        float bs = *b++ * s;",
     "        float bs = *b++;"),
    ("madd-scales-a", PSC,
     "        float bs = *b++ * s;" + NL + "        *out++ = *a++ + bs;",
     "        float bs = *b++;" + NL + "        *out++ = *a++ * s + bs;"),

    # -- the header ---------------------------------------------------------
    ("ph-max-64", PSH,
     "#define PHYSICSSYSTEM_MAX_STATE 140",
     "#define PHYSICSSYSTEM_MAX_STATE 64"),
    ("ph-two-thirds-ulp-down", PSH,
     "#define PHYSICSSYSTEM_RK_TWO_THIRDS 0.666666687f",
     "#define PHYSICSSYSTEM_RK_TWO_THIRDS 0.666666627f"),
    ("ph-sixth-is-third", PSH,
     "#define PHYSICSSYSTEM_RK_SIXTH      0.166666672f",
     "#define PHYSICSSYSTEM_RK_SIXTH      0.333333343f"),
    ("ph-getstate-array-slot-40", PSH,
     "#define PHYSICSCOMPONENT_VT_GET_STATE_ARRAY     32",
     "#define PHYSICSCOMPONENT_VT_GET_STATE_ARRAY     40"),
    ("ph-size-and-vptr-swapped", PSH,
     "    int32_t  Size;      //  8  the sum of every component's GetSize"
     + NL + "    uint32_t _vtable;   // 12",
     "    uint32_t _vtable;   // 12" + NL
     + "    int32_t  Size;      //  8  the sum of every component's GetSize"),

    # -- the ticker ---------------------------------------------------------
    ("tk-no-sticky-bit", TKC,
     "        f = (float)(int32_t)((d & 1u) | half);",
     "        f = (float)(int32_t)half;"),
    ("tk-signed-only", TKC,
     "    if ((int32_t)d >= 0) {",
     "    if (1) {"),
    ("tk-unsigned-direct", TKC,
     "        f = (float)(int32_t)((d & 1u) | half);" + NL
     + "        f = f + f;",
     "        f = (float)d;"),
    ("tk-no-halving", TKC,
     "    uint32_t half = d >> 1;",
     "    uint32_t half = d;"),
    ("tk-multiply-first", TKC,
     "    return f / BTICKER_ASSUMED_HZ * 1000.0f;",
     "    return f * 1000.0f / BTICKER_ASSUMED_HZ;"),
    ("tk-divide-by-ms", TKC,
     "    return f / BTICKER_ASSUMED_HZ * 1000.0f;",
     "    return f / (BTICKER_ASSUMED_HZ / 1000.0f);"),
    ("tk-fix-shift-5", TKC,
     "    return ((to - from) << 6) / 293u;",
     "    return ((to - from) << 5) / 293u;"),
    ("tk-fix-signed", TKC,
     "    return ((to - from) << 6) / 293u;",
     "    return (uint32_t)((int32_t)((to - from) << 6) / 293);"),
    ("tk-fix-292", TKC,
     "    return ((to - from) << 6) / 293u;",
     "    return ((to - from) << 6) / 292u;"),
    ("tk-source-ignored", TKC,
     "    if (bTickerSource)" + NL + "        return bTickerSource();" + NL,
     ""),
    ("tk-hz-is-ee-clock", TKH,
     "#define BTICKER_ASSUMED_HZ 300000000.0f",
     "#define BTICKER_ASSUMED_HZ 294912000.0f"),

    # -- p32 ------------------------------------------------------------------
    ("p32-null-gets-handle", P32C,
     "    if (p == NULL)" + NL + "        return 0;" + NL,
     ""),
    ("p32-no-dedupe", P32C,
     "    for (i = 0; i < p32_count; i++) {" + NL
     + "        if (p32_table[i] == p)" + NL
     + "            return i + 1;" + NL + "    }" + NL,
     "    (void)i;" + NL),
]

EQUIVALENT = {
    # (d >> 1) | (d & 1), converted and doubled, is the textbook way to
    # convert an unsigned 32-bit integer with a signed instruction, and it
    # is exact in the sense that matters: the low bit is folded in as a
    # sticky bit, so every value rounds to the same float32 a direct
    # unsigned conversion gives. Dropping 8 bits of d against dropping 7 of
    # the folded value: the tie is bit 7 set and bits 0..6 clear in both,
    # and "above the tie" is bit 7 set and any of bits 0..6 set in both.
    # tk-no-sticky-bit is the mutation that is NOT equivalent. Checked, not
    # just argued: every low byte under ~8000 high parts plus 200000
    # random values with the top bit set, 723967 in all, 0 disagreeing.
    "tk-unsigned-direct":
        "(d >> 1) | (d & 1) keeps the sticky bit, so the two-step convert "
        "rounds exactly as a direct unsigned conversion does",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name

write_source = hostbuild.write_source


def edits_of(m):
    if isinstance(m[2], list):
        return m[2]
    return [(m[2], m[3], 1)]


def apply_mutation(text, edits):
    """The mutated text, or None when a pattern is not in the file. The
    ported sources are CRLF and these patterns LF, so each one is
    translated to the file's own newline first."""
    crlf = (CR + NL) in text
    for before, after, count in edits:
        probe = before.replace(NL, CR + NL) if crlf else before
        repl = after.replace(NL, CR + NL) if crlf else after
        if probe not in text:
            return None
        text = text.replace(probe, repl, count if count else -1)
    return text


def mutate_pass():
    base_model = model()
    survived, missing, caught = [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="physicssystem_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in MUTATIONS:
        name, rel = m[0], m[1]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        mutated = apply_mutation(text, edits_of(m))
        if mutated is None:
            missing.append(name)
            print("  %-34s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, mutated)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES,
                                          name="physicssystem_test")
                except SystemExit:
                    print("  %-34s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, out)
                if rc == HARNESS_HUNG:
                    print("  %-34s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-34s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-34s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-34s survived, equivalent by construction"
                          % name)
                else:
                    print("  %-34s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(EQUIVALENT), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    return 1 if (holes or missing) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="physicssystem_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ"
          % (sum(1 for line in lines if line.startswith("[")),
             len(harness), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
