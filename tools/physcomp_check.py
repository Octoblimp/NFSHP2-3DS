"""Cross-check physcomp -- the physics component classes as objects -- against
a model of the image.

    3DS Files/source/physcomp.{c,h}   the tables, the destructors, operator
                                      new and delete, and PhysicsCar.obj's
                                      ten slot pools with InitPhysics and
                                      ClosePhysics

RigidBody, Wheel, Suspension, Engine and DriveTrain each have a checker of
their own for their arithmetic. None of those ever saw a vptr used: until
PhysicsSystem, every caller called the port's functions directly. This one
holds the rest of each class to the image:

**The tables.** Each of the seven `_vt$` records is read out of .data, and
every entry's delta, index and target are compared with the port's, the
target by its image name. The port pairs its entries with image names in
one place, the harness's registry, so a port entry in the wrong slot, or a
base entry where the class has its own, shows up as a different name.
Entries the image has and the port does not yet -- `__pure_virtual`, which
aborts, and DoSnapshot, which waits on ReplaySnapshot -- are NULL, and
PENDING below lists the second kind with its reason.

**The simple slots.** GetSize, GetState(), GetState(float *) and
SetState(float *) are a handful of instructions each. The model decodes
them -- `addiu v0,zero,N`, `addiu v0,a0,B`, and the loads and stores of
the copies, lqc2/sqc2, lwc1/swc1 and ldl/ldr pairs -- and says which state
float lands in which array slot; the harness runs the port's on a patterned
object and prints the same.

**The destructors.** Each one's listing is walked: the vptr stores it and
the destructors it calls make, the `andi` that tests the delete bit, and
the `j` to operator delete. A destroyed component carries
PhysicsComponent's vptr and a destroyed Ackerman Steering's. Wheel's runs
~SkidMaker first, which is MakeNoSkid.

**The pools.** InitPhysics is decoded call by call -- size, count, name,
memory pool, and the gp slot the result goes to -- and ClosePhysics store
by store. Each operator new and delete is decoded for the pool it uses.

The arithmetic slots -- ResolveForces, GetDerivative, ComputeAuxiliaries --
are only checked here for reaching the port function the image's name
says (the harness calls both and compares), for RigidBody and Engine, which
can be built alone. Wheel's, Suspension's and DriveTrain's need a whole
car, and physicscar_check runs them through the system walk.

    python tools/physcomp_check.py
    python tools/physcomp_check.py --mutate
    python tools/physcomp_check.py --dump out/physcomp
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
CR = chr(13)

SOURCES = [
    "tools/src/physcomp_test.c",
    "3DS Files/source/physcomp.c",
    "3DS Files/source/bslotpool.c",
    "3DS Files/source/vtable.c",
    "3DS Files/source/physicssystem.c",
    "3DS Files/source/bmem.c",
    "3DS Files/source/bticker.c",
    "3DS Files/source/p32.c",
    "3DS Files/source/rigidbody.c",
    "3DS Files/source/wheel.c",
    "3DS Files/source/suspension.c",
    "3DS Files/source/engine.c",
    "3DS Files/source/drivetrain.c",
    "3DS Files/source/steering.c",
    "3DS Files/source/carstate.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/table.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

PCC = "3DS Files/source/physcomp.c"
PCH = "3DS Files/source/physcomp.h"

ELF = bmath_check.ELF
GP = 0x00328bf0

# ============================================================= the image

ZERO, V0, V1, A0, A1, A2, A3 = 0, 2, 3, 4, 5, 6, 7
S0, S1, GPR, RA = 16, 17, 28, 31

OP_SPECIAL, OP_J, OP_JAL, OP_BEQ = 0x00, 0x02, 0x03, 0x04
OP_ADDIU, OP_ANDI, OP_ORI, OP_LUI = 0x09, 0x0c, 0x0d, 0x0f
OP_LDL, OP_LDR, OP_LW, OP_SW = 0x1a, 0x1b, 0x23, 0x2b
OP_SDL, OP_SDR, OP_LWC1, OP_SWC1 = 0x2c, 0x2d, 0x31, 0x39
OP_LQC2, OP_SQC2 = 0x36, 0x3e


def insn(addr):
    return struct.unpack("<I", ELF.read(addr, 4))[0]


class I(object):
    """One decoded instruction: the fields every format has."""

    def __init__(self, addr):
        w = insn(addr)
        self.addr = addr
        self.w = w
        self.op = w >> 26
        self.rs = (w >> 21) & 31
        self.rt = (w >> 16) & 31
        self.rd = (w >> 11) & 31
        self.sa = (w >> 6) & 31
        self.funct = w & 63
        v = w & 0xffff
        self.uimm = v
        self.imm = v - 0x10000 if v & 0x8000 else v
        self.target = ((w & 0x3ffffff) << 2) | (addr & 0xf0000000)

    def is_move(self):
        # addu / daddu / or rd, rs, zero
        return (self.op == OP_SPECIAL and self.funct in (0x21, 0x2d, 0x25)
                and self.rt == ZERO)

    def is_jr_ra(self):
        return self.op == OP_SPECIAL and self.funct == 0x08 and self.rs == RA

    def is_sll(self):
        return self.op == OP_SPECIAL and self.funct == 0x00 and self.w != 0


def sym(name):
    return ELF.syms[name][0]


_BY_ADDR = {}
for _n, (_a, _s) in ELF.syms.items():
    if _s > 0:
        _BY_ADDR.setdefault(_a, []).append(_n)


def name_at(addr):
    names = _BY_ADDR.get(addr, [])
    assert len(names) == 1, (hex(addr), names)
    return names[0]


def cstring(addr):
    return ELF.read(addr, 64).split(b"\0")[0].decode("ascii")


def body(addr):
    """The instructions from `addr` to the first `jr ra` or `j` and its
    delay slot. Branches are not followed: every function decoded here is
    straight-line up to its exit, apart from the delete bit's test."""
    out = []
    a = addr
    while True:
        i = I(a)
        out.append(i)
        if i.is_jr_ra() or i.op == OP_J:
            out.append(I(a + 4))
            return out
        a += 4
        assert a - addr < 4096, hex(addr)


MDEBUG = (ROOT / "docs" / "mdebug_structs.txt").read_text(encoding="utf-8")


def mdebug_record(name):
    m = re.search(r"^struct/class %s \(size=(\d+) bytes\).*?(?=^struct/class )"
                  % re.escape(name), MDEBUG, re.S | re.M)
    assert m, name
    return int(m.group(1)), m.group(0)


def mdebug_field_at(record, byte):
    for m in re.finditer(r"^\s+(\w+)\s+type#\d+\s+offset=(\d+)\s", record,
                         re.M):
        if int(m.group(2)) == 8 * byte:
            return m.group(1)
    return None


# ------------------------------------------------------------ the tables

TABLES = [
    "_vt$9RigidBody",
    "_vt$5Wheel",
    "_vt$10Suspension",
    "_vt$6Engine",
    "_vt$10DriveTrain",
    "_vt$24TwoWheelAckermanSteering",
    "_vt$8Steering",
]


def vt_entries(table):
    a, size = ELF.syms[table]
    return [struct.unpack("<hhI", ELF.read(a + 8 * i, 8))
            for i in range(size // 8)]


# The entries the image has and the port leaves NULL, each with why.
# `__pure_virtual` is not listed: NULL is what it is in the port, since
# vt_slot aborts on it exactly as __pure_virtual does.
PENDING = {
    "DoSnapshot__24TwoWheelAckermanSteeringP14ReplaySnapshot":
        "ReplaySnapshot is not ported; no DoSnapshot of any class is",
}


def entry_name(fn):
    if fn == 0:
        return "NULL"
    n = name_at(fn)
    if n == "__pure_virtual" or n in PENDING:
        return "NULL"
    return n


def slot_of(table, fn_name):
    hits = [8 * k for k, e in enumerate(vt_entries(table))
            if e[2] and name_at(e[2]) == fn_name]
    assert len(hits) == 1, (table, fn_name, hits)
    return hits[0]


# Each class: its table, its mdebug record, the port's name for it in the
# harness, and the port functions its arithmetic slots stand for.
CLASSES = [
    ("RigidBody", "_vt$9RigidBody"),
    ("Wheel", "_vt$5Wheel"),
    ("Suspension", "_vt$10Suspension"),
    ("Engine", "_vt$6Engine"),
    ("DriveTrain", "_vt$10DriveTrain"),
]

# The port function each image method is. Only the ones the harness
# compares against directly.
PORT = {
    "ResolveForces__9RigidBody": "rigidbody_resolve_forces",
    "GetDerivative__9RigidBodyPf": "rigidbody_get_derivative",
    "ComputeAuxiliaries__9RigidBody": "rigidbody_compute_auxiliaries",
    "GetDerivative__6EnginePf": "engine_get_derivative",
    "ComputeAuxiliaries__6Engine": "engine_compute_auxiliaries",
    "SetSteering__24TwoWheelAckermanSteeringUs": "ackerman_set_steering",
}

# ------------------------------------------------------------- the pools

INIT_PHYSICS = sym("InitPhysics__Fv")
CLOSE_PHYSICS = sym("ClosePhysics__Fv")
BNEWSLOTPOOL = sym("bNewSlotPool__FiiPCci")
BDELETESLOTPOOL = sym("bDeleteSlotPool__FP8SlotPool")
BOMALLOC = sym("bOMalloc__FP8SlotPool")
BFREE_POOL = sym("bFree__FP8SlotPoolPv")


def decode_init_physics():
    """InitPhysics call by call: (size, count as (mult, add), name, memory
    pool, gp offset of the result). The count is in terms of n, the
    number of drivers: s0 = n, and s1 = n << 2."""
    ins = body(INIT_PHYSICS)
    regs = {}          # reg -> ("n", mult, add) | ("k", value)
    calls = []
    pending = None
    k = 0
    while k < len(ins):
        i = ins[k]
        if i.op == OP_LUI:
            regs[i.rt] = ("k", i.uimm << 16)
        elif i.op == OP_LW and i.rt == S0:
            # lw s0,10260(v0), with lui v0,0x31 before it
            assert regs[i.rs][0] == "k"
            regs["n_from"] = regs[i.rs][1] + i.imm
            regs[S0] = ("n", 1, 0)
        elif i.op == OP_ADDIU and i.rs == 29:
            pass
        elif i.op == OP_ADDIU and i.rs == ZERO:
            regs[i.rt] = ("k", i.imm)
        elif i.op == OP_ADDIU:
            src = regs[i.rs]
            if src[0] == "k":
                regs[i.rt] = ("k", src[1] + i.imm)
            else:
                regs[i.rt] = ("n", src[1], src[2] + i.imm)
        elif i.is_sll():
            src = regs[i.rt]
            assert src[0] == "n"
            regs[i.rd] = ("n", src[1] << i.sa, src[2] << i.sa)
        elif i.is_move():
            regs[i.rd] = regs[i.rs]
        elif i.op == OP_JAL:
            assert i.target == BNEWSLOTPOOL, hex(i.addr)
            # The delay slot runs before the call.
            d = ins[k + 1]
            if d.op == OP_ADDIU and d.rs == ZERO:
                regs[d.rt] = ("k", d.imm)
            elif d.is_sll():
                src = regs[d.rt]
                regs[d.rd] = ("n", src[1] << d.sa, src[2] << d.sa)
            else:
                raise AssertionError(hex(d.addr))
            size, count, name, mem = (regs[A0], regs[A1], regs[A2], regs[A3])
            assert size[0] == "k" and name[0] == "k" and mem[0] == "k"
            assert count[0] == "n"
            pending = [size[1], (count[1], count[2]), cstring(name[1]),
                       mem[1], None]
            calls.append(pending)
            k += 2
            continue
        elif i.op == OP_SW and i.rs == GPR and i.rt == V0:
            assert pending is not None and pending[4] is None
            pending[4] = i.imm
        elif i.op in (0x37, 0x3f) or i.is_jr_ra():  # ld / sd / jr
            pass
        else:
            raise AssertionError("unexpected %08x at %x" % (i.w, i.addr))
        k += 1
    assert all(c[4] is not None for c in calls)
    return calls, regs["n_from"]


POOLS, N_FROM = decode_init_physics()
assert len(POOLS) == 10

# n is TheRaceParameters.NumDriverInfo.
_RP_SIZE, _RP_REC = mdebug_record("RaceParameters")
assert N_FROM == sym("TheRaceParameters") + 756
assert mdebug_field_at(_RP_REC, 756) == "NumDriverInfo"

# Every pool is in gp order, and named for the symbol in its slot.
assert [c[4] for c in POOLS] == sorted(c[4] for c in POOLS)
for _c in POOLS:
    assert name_at(GP + _c[4]) == _c[2], _c

# The slot sizes are the mdebug sizes of the ten classes, all ported.
_SIZES = {c[2]: c[0] for c in POOLS}
PORTED_CLASSES = ("RigidBody", "TwoWheelAckermanSteering", "Wheel", "Engine",
                  "DriveTrain", "Aerodynamics", "Suspension", "Mellovator",
                  "MellowMover", "NullMover")
for _cls in PORTED_CLASSES:
    assert _SIZES[_cls + "SlotPool"] == mdebug_record(_cls)[0], _cls

POOL_ORDER = [c[2] for c in POOLS]          # gp order
POOL_OF_GP = {c[4]: c[2] for c in POOLS}


def pool_count(pool, n):
    mult, add = [c[1] for c in POOLS if c[2] == pool][0]
    return mult * n + add


# SlotPoolManager::NewSlotPool rounds the slot up to a word before the
# pool sees it: `addiu v0,a1,3` (0x0023fdac), `addiu a0,zero,-4`, `and`.
_R = [I(0x0023fdac), I(0x0023fdc0)]
assert _R[0].op == OP_ADDIU and _R[0].imm == 3
assert _R[1].op == OP_ADDIU and _R[1].rs == ZERO and _R[1].imm == -4
assert I(0x0023fdcc).op == OP_SPECIAL and I(0x0023fdcc).funct == 0x24


def slot_round(n):
    return (n + _R[0].imm) & _R[1].imm


# The ten pools, every class ported. The harness prints each of their
# slots as "sizeof" when it is the port record's sizeof, rounded; each
# class's header asserts that sizeof is the mdebug size on the 3DS, and the
# asserts above hold InitPhysics's immediates to the same mdebug sizes.
PORTED_POOLS = {c + "SlotPool" for c in PORTED_CLASSES}

# bNewSlotPool starts every pool's flags at 15 (0x0023f680, `addiu
# v0,zero,15`, stored to +20 by the `sw` after it), and InitPhysics
# changes none of them.
_F = I(0x0023f680)
assert _F.op == OP_ADDIU and _F.rs == ZERO
POOL_FLAGS = _F.imm
SLOTPOOL_FLAG_ZERO_ALLOCATED_MEMORY = 2


def decode_close_physics():
    ins = body(CLOSE_PHYSICS)
    deletes, zeroes = [], []
    a0 = None
    for k, i in enumerate(ins):
        if i.op == OP_LW and i.rt == A0 and i.rs == GPR:
            a0 = i.imm
        elif i.op == OP_JAL:
            assert i.target == BDELETESLOTPOOL
            # The delay slot runs before the call.
            d = ins[k + 1]
            if d.op == OP_LW and d.rt == A0 and d.rs == GPR:
                a0 = d.imm
            deletes.append(a0)
            a0 = None
        elif i.op == OP_SW and i.rs == GPR and i.rt == ZERO:
            zeroes.append(i.imm)
    return deletes, zeroes


CLOSE_DELETES, CLOSE_ZEROES = decode_close_physics()
assert CLOSE_DELETES == [c[4] for c in POOLS]
assert sorted(CLOSE_ZEROES) == [c[4] for c in POOLS]
# The deletes all come before the first zero.
assert max(i.addr for i in body(CLOSE_PHYSICS) if i.op == OP_JAL) < min(
    i.addr for i in body(CLOSE_PHYSICS)
    if i.op == OP_SW and i.rs == GPR and i.rt == ZERO)


def new_pool(nw_name):
    """operator new: `lw a0,OFF(gp) ; jal bOMalloc`."""
    ins = body(sym(nw_name))
    lw = [i for i in ins if i.op == OP_LW and i.rt == A0 and i.rs == GPR]
    jal = [i for i in ins if i.op == OP_JAL]
    assert len(lw) == 1 and len(jal) == 1 and jal[0].target == BOMALLOC
    return POOL_OF_GP[lw[0].imm]


def delete_pool(dl_name):
    """operator delete: `move a1,a0 ; j bFree ; lw a0,OFF(gp)`."""
    ins = body(sym(dl_name))
    assert ins[0].is_move() and ins[0].rd == A1 and ins[0].rs == A0
    assert ins[1].op == OP_J and ins[1].target == BFREE_POOL
    assert ins[2].op == OP_LW and ins[2].rt == A0 and ins[2].rs == GPR
    return POOL_OF_GP[ins[2].imm]


def ctor_new_pools():
    """The pools PhysicsCar's ctor calls bOMalloc on itself -- the inlined
    news, Aerodynamics' among them."""
    a, size = ELF.syms["__10PhysicsCarP11CarTypeInfoP9CarDriverP3Car"]
    out = []
    for addr in range(a, a + size, 4):
        i = I(addr)
        if i.op == OP_JAL and i.target == BOMALLOC:
            for j in (I(addr - 4), I(addr + 4), I(addr - 8)):
                if j.op == OP_LW and j.rt == A0 and j.rs == GPR:
                    out.append(POOL_OF_GP[j.imm])
                    break
    return out


NEW = {
    "RigidBody": new_pool("__nw__9RigidBodyUi"),
    "Wheel": new_pool("__nw__5WheelUi"),
    "Suspension": new_pool("__nw__10SuspensionUi"),
    "Engine": new_pool("__nw__6EngineUi"),
    "DriveTrain": new_pool("__nw__10DriveTrainUi"),
    "Ackerman": new_pool("__nw__24TwoWheelAckermanSteeringUi"),
}
DELETE = {
    "RigidBody": delete_pool("__dl__9RigidBodyPv"),
    "Wheel": delete_pool("__dl__5WheelPv"),
    "Suspension": delete_pool("__dl__10SuspensionPv"),
    "Engine": delete_pool("__dl__6EnginePv"),
    "DriveTrain": delete_pool("__dl__10DriveTrainPv"),
    "Ackerman": delete_pool("__dl__24TwoWheelAckermanSteeringPv"),
    "Aerodynamics": delete_pool("__dl__12AerodynamicsPv"),
}
# Aerodynamics has no operator new of its own; the ctor's bOMalloc is it.
assert DELETE["Aerodynamics"] in ctor_new_pools()
NEW["Aerodynamics"] = DELETE["Aerodynamics"]
for _k in NEW:
    assert NEW[_k] == DELETE[_k], _k

# bOMalloc is the full path, SlotPool::Malloc, which clears the slot when
# the pool's flags ask it to.
_OM = body(BOMALLOC)
assert [name_at(i.target) for i in _OM if i.op == OP_JAL] == [
    "Malloc__8SlotPool"]
CLEARS = bool(POOL_FLAGS & SLOTPOOL_FLAG_ZERO_ALLOCATED_MEMORY)

# ------------------------------------------------------- the destructors

PC_DTOR = sym("_$_16PhysicsComponent")


def walk_dtor(addr, seen=None):
    """What `_$_X(this, flags)` leaves behind: the last vptr stored at
    this+8 along the chain, the mask its `andi` tests the flags with, the
    operator delete it jumps to, and the member destructors it calls with
    their a1."""
    seen = seen or set()
    seen.add(addr)
    consts = {}
    vptr, mask, delete, members = None, None, None, []
    ins = body(addr)
    for k, i in enumerate(ins):
        if i.op == OP_LUI:
            consts[i.rt] = i.uimm << 16
        elif i.op == OP_ADDIU and i.rs in consts and i.rs == i.rt:
            consts[i.rt] = (consts[i.rs] + i.imm) & 0xffffffff
        elif i.op == OP_ADDIU and i.rs == ZERO:
            consts[i.rt] = i.imm
        elif i.op == OP_SW and i.imm == 8 and i.rt in consts:
            vptr = consts[i.rt]
        elif i.op == OP_ANDI:
            mask = i.uimm
        elif i.op in (OP_JAL, OP_J):
            t = name_at(i.target)
            d = ins[k + 1] if k + 1 < len(ins) else None
            if t.startswith("_$_") and i.target not in seen:
                a1 = None
                if d is not None and d.op == OP_ADDIU and d.rt == A1:
                    a1 = d.imm
                elif d is not None and d.is_move() and d.rd == A1:
                    a1 = 0
                sub = walk_dtor(i.target, seen)
                # A member's destructor runs on this+N; only a call on
                # `this` itself can store this object's vptr.
                prev = ins[k - 1] if k else None
                on_member = (prev is not None and prev.op == OP_ADDIU
                             and prev.rt == A0 and prev.rs != ZERO)
                if on_member:
                    members.append((t, a1))
                elif sub["vptr"] is not None:
                    vptr = sub["vptr"]
            elif t.startswith("__dl__") or t == "__builtin_delete":
                delete = t
    return {"vptr": vptr, "mask": mask, "delete": delete,
            "members": members}


DTORS = {
    "RigidBody": walk_dtor(sym("_$_9RigidBody")),
    "Wheel": walk_dtor(sym("_$_5Wheel")),
    "Suspension": walk_dtor(sym("_$_10Suspension")),
    "Engine": walk_dtor(sym("_$_6Engine")),
    "DriveTrain": walk_dtor(sym("_$_10DriveTrain")),
    "Ackerman": walk_dtor(sym("_$_24TwoWheelAckermanSteering")),
    "Steering": walk_dtor(sym("_$_8Steering")),
}
for _k in ("RigidBody", "Wheel", "Suspension", "Engine", "DriveTrain",
           "Ackerman"):
    _nm = {"Ackerman": "24TwoWheelAckermanSteering"}.get(
        _k, {"RigidBody": "9RigidBody", "Wheel": "5Wheel",
             "Suspension": "10Suspension", "Engine": "6Engine",
             "DriveTrain": "10DriveTrain"}.get(_k))
    assert DTORS[_k]["delete"] == "__dl__%sPv" % _nm, (_k, DTORS[_k])
assert DTORS["Steering"]["delete"] == "__builtin_delete"
assert DTORS["Wheel"]["members"] == [("_$_9SkidMaker", 2)]

# ~SkidMaker is MakeNoSkid and then the delete bit; MakeNoSkid is
# `lw a0,0(a0) ; beq a0,zero ; j FinishedAddingSkids` and stores nothing.
_SK = body(sym("_$_9SkidMaker"))
assert [name_at(i.target) for i in _SK if i.op == OP_JAL] == [
    "MakeNoSkid__9SkidMaker"]
_MNS = [I(sym("MakeNoSkid__9SkidMaker") + 4 * k) for k in range(5)]
assert _MNS[0].op == OP_LW and _MNS[0].rt == A0 and _MNS[0].rs == A0 \
    and _MNS[0].imm == 0
assert _MNS[1].op == OP_BEQ and _MNS[1].rs == A0 and _MNS[1].rt == ZERO
assert _MNS[3].op == OP_J and name_at(_MNS[3].target) == \
    "FinishedAddingSkids__7SkidSet"
assert not any(i.op in (OP_SW, OP_SWC1, OP_SQC2) for i in _MNS)

# ~PhysicsSystem destroys its components with flags 3 (0x001924b4,
# `addiu a1,zero,3`, the jalr at 0x001924d0).
_PSD = I(0x001924b4)
assert _PSD.op == OP_ADDIU and _PSD.rs == ZERO and _PSD.rt == A1
SYSTEM_DTOR_FLAGS = _PSD.imm

# --------------------------------------------------- the simple slots


def get_size(fn):
    ins = body(fn)
    assert ins[0].is_jr_ra() and ins[1].op == OP_ADDIU and ins[1].rs == ZERO
    return ins[1].imm


def get_state(fn):
    ins = body(fn)
    assert ins[0].is_jr_ra() and ins[1].op == OP_ADDIU and ins[1].rs == A0
    return ins[1].imm


def copies(fn, src_base, dst_base):
    """The copy a GetState(float *) or SetState(float *) makes, as
    (dst byte, src byte, bytes) triples: loads from `src_base`, stores to
    `dst_base`. ldl/ldr and sdl/sdr come in pairs whose low offset is the
    ldr's or sdr's (little-endian)."""
    held = {}
    out = []
    for i in body(fn):
        if i.op == OP_LQC2 and i.rs == src_base:
            held[("vf", i.rt)] = (i.imm, 16)
        elif i.op == OP_LWC1 and i.rs == src_base:
            held[("f", i.rt)] = (i.imm, 4)
        elif i.op == OP_LDR and i.rs == src_base:
            held[("r", i.rt)] = (i.imm, 8)
        elif i.op == OP_LDL and i.rs == src_base:
            pass
        elif i.op == OP_SQC2 and i.rs == dst_base:
            s = held[("vf", i.rt)]
            out.append((i.imm, s[0], 16))
        elif i.op == OP_SWC1 and i.rs == dst_base:
            s = held[("f", i.rt)]
            out.append((i.imm, s[0], 4))
        elif i.op == OP_SDR and i.rs == dst_base:
            s = held[("r", i.rt)]
            out.append((i.imm, s[0], 8))
        elif i.op == OP_SDL and i.rs == dst_base:
            pass
        elif i.is_jr_ra() or i.w == 0:
            pass
        else:
            raise AssertionError("%s: %08x" % (name_at(fn), i.w))
    return out


# ============================================================= the model

OUT = []


def emit(s):
    OUT.append(s)


def s_tables():
    emit("== tables ==")
    for t in TABLES:
        es = vt_entries(t)
        emit("%s 0x%08x entries %d" % (t, sym(t), len(es)))
        for k, (delta, index, fn) in enumerate(es):
            emit("  +%-2d d%d i%d %s" % (8 * k, delta, index, entry_name(fn)))


def s_pools(n):
    emit("== pools %d ==" % n)
    for c in POOLS:
        name = c[2]
        size = ("sizeof" if name in PORTED_POOLS
                else str(slot_round(c[0])))
        emit("  %-24s %s slots %d size %s allocated %d flags %u"
             % (name[:-len("SlotPool")], name, pool_count(name, n), size, 0,
                POOL_FLAGS))
    emit("  closed, %d null" % len(CLOSE_ZEROES))


def counts(tag, alloc):
    emit("  %s %s" % (tag, " ".join(str(alloc[p]) for p in POOL_ORDER[:7])))


def s_new():
    emit("== new ==")
    alloc = {p: 0 for p in POOL_ORDER}
    counts("before", alloc)
    order = ["RigidBody", "Wheel", "Suspension", "Engine", "DriveTrain",
             "Ackerman", "Aerodynamics"]
    for k in order:
        alloc[NEW[k]] += 1
    counts("after new", alloc)
    for k in order:
        # A dirtied slot, cleared by the full path when the flags ask.
        assert CLEARS
        emit("  %-12s nonzero bytes %d" % (k, 0))

    def gone(tag, *names):
        for nm in names:
            alloc[DELETE[nm]] -= 1
        counts(tag, alloc)

    gone("aero gone", "Aerodynamics")
    gone("wheel gone", "Wheel")
    gone("body, engine gone", "RigidBody", "Engine")
    gone("all gone", "Ackerman", "DriveTrain", "Suspension")
    # The free list is last in, first out (bslotpool_check holds it).
    emit("  reuse same slot")


def s_simple():
    for cls, table in CLASSES:
        emit("== slots %s ==" % cls)
        es = vt_entries(table)
        size_fn = es[2][2]
        state_fn = es[3][2]
        get_fn = es[4][2]
        set_fn = es[5][2]
        assert name_at(size_fn).startswith("GetSize__")
        assert name_at(get_fn).endswith("Pf")
        emit("  size %d" % get_size(size_fn))
        base = get_state(state_fn)
        emit("  state %s" % (mdebug_field_at(mdebug_record(cls)[1], base)
                             or "elsewhere"))
        # GetState(float *): a0 is the object, a1 the array.
        moves = {}
        for dst, src, n in copies(get_fn, A0, A1):
            for k in range(0, n, 4):
                moves[(dst + k) // 4] = (src + k - base) // 4
        for i in sorted(moves):
            emit("  get a %d <- %d" % (i, moves[i]))
        moves = {}
        for dst, src, n in copies(set_fn, A1, A0):
            for k in range(0, n, 4):
                moves[(dst + k - base) // 4] = (src + k) // 4
        for i in sorted(moves):
            emit("  set s %d <- %d" % (i, moves[i]))


def dtor_line(name, flags, d, freed=True):
    emit("  %-10s flags %d  vptr 0x%08x  freed %d"
         % (name, flags, d["vptr"], 1 if (freed and flags & d["mask"])
            else 0))


def s_dtors():
    emit("== dtors ==")
    for f in range(4):
        for k in ("RigidBody", "Wheel", "Suspension", "Engine",
                  "DriveTrain", "Ackerman"):
            dtor_line(k, f, DTORS[k])
    emit("  left " + " ".join(["0"] * 7))
    for f in (0, 2):
        emit("  %-10s flags %d  vptr 0x%08x"
             % ("Steering", f, DTORS["Steering"]["vptr"]))
    dtor_line("Wheel", 2, DTORS["Wheel"])
    emit("  no set: seam calls 0")
    dtor_line("Wheel", 3, DTORS["Wheel"])
    emit("  set: seam calls 1 with the set, pSkidSet kept")


def s_same():
    emit("== same ==")
    rb, en = "_vt$9RigidBody", "_vt$6Engine"
    for m, tail in (("ResolveForces__9RigidBody", ""),
                    ("GetDerivative__9RigidBodyPf", ", body same"),
                    ("ComputeAuxiliaries__9RigidBody", "")):
        emit("  RigidBody +%d same as %s%s" % (slot_of(rb, m), PORT[m], tail))
    # Engine's slot 48 is the base's, `jr ra ; nop`.
    base = sym("ResolveForces__16PhysicsComponent")
    b = body(base)
    assert len(b) == 2 and b[0].is_jr_ra() and b[1].w == 0
    emit("  Engine +%d leaves it same"
         % slot_of(en, "ResolveForces__16PhysicsComponent"))
    for m, tail in (("GetDerivative__6EnginePf", ", engine same"),
                    ("ComputeAuxiliaries__6Engine", "")):
        emit("  Engine +%d same as %s%s" % (slot_of(en, m), PORT[m], tail))
    m = "SetSteering__24TwoWheelAckermanSteeringUs"
    emit("  Ackerman +%d same as %s"
         % (slot_of("_vt$24TwoWheelAckermanSteering", m), PORT[m]))


def s_system():
    emit("== system ==")
    sizes = {cls: get_size(vt_entries(t)[2][2]) for cls, t in CLASSES}
    total = 0
    # PhysicsCar's order; physicscar_check holds the ctor to it.
    order = (["RigidBody"] + ["Wheel", "Suspension"] * 4
             + ["Engine", "DriveTrain"])
    for cls in order:
        total += sizes[cls]
        emit("  + %-10s Size %d" % (cls, total))
    alloc = {p: 0 for p in POOL_ORDER}
    for cls in order:
        alloc[NEW[cls]] += 1
    counts("built", alloc)
    for cls in order:
        if SYSTEM_DTOR_FLAGS & DTORS[cls]["mask"]:
            alloc[DELETE[cls]] -= 1
    counts("after ~PhysicsSystem", alloc)


SCENARIOS = [
    s_tables,
    lambda: s_pools(3),
    lambda: s_pools(1),
    s_new,
    s_simple,
    s_dtors,
    s_same,
    s_system,
]


def model():
    del OUT[:]
    for s in SCENARIOS:
        s()
    return list(OUT)


# ============================================================ the harness

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
# (name, file, before, after), or (name, file, [(before, after, count)]).

MUTATIONS = [
    # -- the tables -------------------------------------------------------
    ("vt-wheel-get-set-swapped", PCC,
     [("    { 0, 0, (VtFn)vt_Wheel_GetState_Pf }," + NL
       + "    { 0, 0, (VtFn)vt_Wheel_SetState_Pf },",
       "    { 0, 0, (VtFn)vt_Wheel_SetState_Pf }," + NL
       + "    { 0, 0, (VtFn)vt_Wheel_GetState_Pf },", 1)]),
    ("vt-rigidbody-base-resolve", PCC,
     "    { 0, 0, (VtFn)vt_RigidBody_ResolveForces },",
     "    { 0, 0, (VtFn)physicscomponent_resolve_forces },"),
    ("vt-suspension-own-resolve", PCC,
     "    { 0, 0, (VtFn)vt_Suspension_GetState_Pf }," + NL
     + "    { 0, 0, (VtFn)vt_Suspension_SetState_Pf }," + NL
     + "    { 0, 0, (VtFn)physicscomponent_resolve_forces },",
     "    { 0, 0, (VtFn)vt_Suspension_GetState_Pf }," + NL
     + "    { 0, 0, (VtFn)vt_Suspension_SetState_Pf }," + NL
     + "    { 0, 0, (VtFn)vt_Suspension_ComputeAuxiliaries },"),
    ("vt-engine-deriv-null", PCC,
     "    { 0, 0, (VtFn)vt_Engine_GetDerivative_Pf },",
     "    { 0, 0, NULL },"),
    ("vt-drivetrain-delta", PCC,
     "    { 0, 0, (VtFn)vt_DriveTrain_ComputeAuxiliaries },",
     "    { 4, 0, (VtFn)vt_DriveTrain_ComputeAuxiliaries },"),
    ("vt-ackerman-snapshot-filled", PCC,
     "    { 0, 0, (VtFn)vt_Ackerman_SetSteering }," + NL
     + "    { 0, 0, NULL },",
     "    { 0, 0, (VtFn)vt_Ackerman_SetSteering }," + NL
     + "    { 0, 0, (VtFn)vt_Ackerman_SetSteering },"),
    ("vt-steering-not-pure", PCC,
     "    { 0, 0, (VtFn)vt_Steering_dtor }," + NL + "    { 0, 0, NULL },",
     "    { 0, 0, (VtFn)vt_Steering_dtor }," + NL
     + "    { 0, 0, (VtFn)vt_Ackerman_SetSteering },"),
    ("vt-engine-at-drivetrain", PCC,
     "    vt_install(ENGINE_VTABLE, engine_vt, ENGINE_VT_ENTRIES);",
     "    vt_install(ENGINE_VTABLE, drivetrain_vt, ENGINE_VT_ENTRIES);"),
    ("vt-rigidbody-short", PCC,
     "    vt_install(RIGIDBODY_VTABLE, rigidbody_vt, RIGIDBODY_VT_ENTRIES);",
     "    vt_install(RIGIDBODY_VTABLE, rigidbody_vt, 8);"),
    ("vt-no-steering", PCC,
     "    vt_install(STEERING_VTABLE, steering_vt, STEERING_VT_ENTRIES);"
     + NL, ""),

    # -- the thunks -------------------------------------------------------
    ("th-rb-aux-is-resolve", PCC,
     "void vt_RigidBody_ComputeAuxiliaries(void *self)" + NL + "{" + NL
     + "    rigidbody_compute_auxiliaries((RigidBody *)self);",
     "void vt_RigidBody_ComputeAuxiliaries(void *self)" + NL + "{" + NL
     + "    rigidbody_resolve_forces((RigidBody *)self);"),
    ("th-rb-size-state-floats", PCC,
     "    return rigidbody_get_size((const RigidBody *)self);",
     "    return RIGIDBODY_STATE_USED;"),
    ("th-rb-state-velocity", PCC,
     "    return (float *)rigidbody_get_state((RigidBody *)self);",
     "    return (float *)&((RigidBody *)self)->Velocity;"),
    ("th-engine-deriv-skipped", PCC,
     "    (void)engine_get_derivative((Engine *)self, out);" + NL,
     "    (void)self; (void)out;" + NL),
    ("th-engine-aux-skipped", PCC,
     "    engine_compute_auxiliaries((Engine *)self);" + NL + "}",
     "    (void)self;" + NL + "}"),
    ("th-wheel-set-is-get", PCC,
     "    wheel_set_state_array((Wheel *)self, a);",
     "    wheel_get_state_array((const Wheel *)self, a);"),
    ("th-susp-get-one", PCC,
     "    suspension_get_state_array((const Suspension *)self, a);",
     "    a[0] = ((Suspension *)self)->State.z;"),
    ("th-drivetrain-size-engine", PCC,
     "    return drivetrain_get_size((const DriveTrain *)self);",
     "    return 2;"),
    ("th-ackerman-steer-none", PCC,
     "    ackerman_set_steering((TwoWheelAckermanSteering *)self, bam);",
     "    (void)self; (void)bam;"),

    # -- the destructors --------------------------------------------------
    ("dt-rb-delete-bit-two", PCC,
     "    rigidbody_fini(rb);" + NL + "    if (flags & 1)",
     "    rigidbody_fini(rb);" + NL + "    if (flags & 2)"),
    ("dt-wheel-no-base", PCC,
     "    skidmaker_destroy(&w->TheSkidMaker, 2);" + NL
     + "    physicscomponent_fini(w);" + NL,
     "    skidmaker_destroy(&w->TheSkidMaker, 2);" + NL),
    ("dt-wheel-no-skid", PCC,
     "    skidmaker_destroy(&w->TheSkidMaker, 2);" + NL, ""),
    ("dt-susp-never-deletes", PCC,
     "    if (flags & 1)" + NL + "        suspension_delete(s);", ""),
    ("dt-engine-own-vptr-last", PCC,
     "    e->_vtable = ENGINE_VTABLE;" + NL
     + "    physicscomponent_fini(e);",
     "    physicscomponent_fini(e);" + NL
     + "    e->_vtable = ENGINE_VTABLE;"),
    ("dt-engine-no-own-vptr", PCC,
     "    e->_vtable = ENGINE_VTABLE;" + NL
     + "    physicscomponent_fini(e);",
     "    physicscomponent_fini(e);"),
    ("dt-drivetrain-wrong-delete", PCC,
     "        drivetrain_delete(d);", "        engine_delete(d);"),
    ("dt-ackerman-no-fini", PCC,
     "    ackerman_fini(a);" + NL, ""),
    ("dt-steering-no-fini", PCC,
     "    steering_fini(s);" + NL + "    if (flags & 1)" + NL
     + "        bFree(s);",
     "    if (flags & 1)" + NL + "        bFree(s);"),
    ("sk-inverted", PCC,
     "    if (sm->pSkidSet != NULL) {",
     "    if (sm->pSkidSet == NULL && gSkidSetFinishedAddingFn) {"),
    ("sk-clears-set", PCC,
     "        gSkidSetFinishedAddingFn(sm->pSkidSet);",
     "        gSkidSetFinishedAddingFn(sm->pSkidSet);" + NL
     + "        sm->pSkidSet = NULL;"),

    # -- new and delete ---------------------------------------------------
    ("nw-wheel-susp-pool", PCC,
     "    return (Wheel *)bSlotOMalloc(WheelSlotPool);",
     "    return (Wheel *)bSlotOMalloc(SuspensionSlotPool);"),
    ("nw-engine-fast-path", PCC,
     "    return (Engine *)bSlotOMalloc(EngineSlotPool);",
     "    return (Engine *)bSlotMalloc(EngineSlotPool);"),
    ("nw-aero-rb-pool", PCC,
     "    return (Aerodynamics *)bSlotOMalloc(AerodynamicsSlotPool);",
     "    return (Aerodynamics *)bSlotOMalloc(RigidBodySlotPool);"),
    ("dl-engine-drivetrain-pool", PCC,
     "void engine_delete(void *p)      { bSlotFree(EngineSlotPool, p); }",
     "void engine_delete(void *p)      { bSlotFree(DriveTrainSlotPool, p); }"),
    ("dl-ackerman-rb-pool", PCC,
     "    bSlotFree(TwoWheelAckermanSteeringSlotPool, p);",
     "    bSlotFree(RigidBodySlotPool, p);"),

    # -- the pools --------------------------------------------------------
    ("pl-rb-spare-31", PCC,
     "    RigidBodySlotPool = bNewSlotPool((int)sizeof(RigidBody), n + 32,",
     "    RigidBodySlotPool = bNewSlotPool((int)sizeof(RigidBody), n + 31,"),
    ("pl-wheel-2n", PCC,
     "    WheelSlotPool = bNewSlotPool((int)sizeof(Wheel), n * 4,",
     "    WheelSlotPool = bNewSlotPool((int)sizeof(Wheel), n * 2,"),
    ("pl-susp-n", PCC,
     "    SuspensionSlotPool = bNewSlotPool((int)sizeof(Suspension), n * 4,",
     "    SuspensionSlotPool = bNewSlotPool((int)sizeof(Suspension), n,"),
    ("pl-ackerman-4n", PCC,
     "        bNewSlotPool((int)sizeof(TwoWheelAckermanSteering), n,",
     "        bNewSlotPool((int)sizeof(TwoWheelAckermanSteering), n * 4,"),
    ("pl-nullmover-n-plus-1", PCC,
     "    NullMoverSlotPool = bNewSlotPool((int)sizeof(NullMover), n,",
     "    NullMoverSlotPool = bNewSlotPool((int)sizeof(NullMover), n + 1,"),
    ("pl-name-engine", PCC,
     "                                  \"EngineSlotPool\", PHYSICS_MEMORY_POOL);",
     "                                  \"EnginePool\", PHYSICS_MEMORY_POOL);"),
    ("pl-close-keeps-wheel", PCC,
     "    WheelSlotPool = NULL;" + NL, ""),
    ("pl-close-keeps-mellow", PCC,
     "    MellowMoverSlotPool = NULL;" + NL, ""),
    ("pl-wheel-sized-as-suspension", PCC,
     "    WheelSlotPool = bNewSlotPool((int)sizeof(Wheel), n * 4,",
     "    WheelSlotPool = bNewSlotPool((int)sizeof(Suspension), n * 4,"),
    ("pl-nullmover-size", PCC,
     "    NullMoverSlotPool = bNewSlotPool((int)sizeof(NullMover), n,",
     "    NullMoverSlotPool = bNewSlotPool((int)sizeof(MellowMover), n,"),
    ("pl-mellovator-sized-as-mover", PCC,
     "    MellovatorSlotPool = bNewSlotPool((int)sizeof(Mellovator), n,",
     "    MellovatorSlotPool = bNewSlotPool((int)sizeof(MellowMover), n,"),
    ("h-nullmover-size", "3DS Files/source/carmodes.h",
     "    CarState *pState;      // 8",
     "    CarState *pState;      // 8" + NL + "    int32_t   _extra;"),
]


# Mutations no transcript can tell apart from the original, each with why.
EQUIVALENT = {
    "dt-engine-no-own-vptr":
        "~Engine's own vptr store is overwritten by ~PhysicsComponent's "
        "with no call in between that could dispatch through it; the "
        "image makes it because g++ 2.9x always resets the vptr on entry "
        "to a destructor, and nothing in Engine's chain is virtual",
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
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="physcomp_test")
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
                    exe = hostbuild.build(tmp, SOURCES, name="physcomp_test")
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
                    equivalent.append(name)
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
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="physcomp_test")
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    if rc != 0:
        print("harness exited %d" % rc)
        bad += 1
    for k, why in sorted(PENDING.items()):
        print("pending: %s -- %s" % (k, why))
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(harness), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
