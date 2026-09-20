#!/usr/bin/env python3
r"""Recover bWare's chunk-type -> Loader*() dispatch table from NFSHP2.ELF.

`LoadChunks(bChunk *c, int len)` (0x0018f878) just calls

    TraverseChunks(c, c + len, LoaderTable, 0x1f)

so `LoaderTable` (0x003081d0, 124 bytes) is an array of 31 `int (*)(bChunk *)`
function pointers. Each loader opens with its own type guard, e.g.

    LoaderNisInfo:  if (chunk->Type != 0x37010) return 0;

so reading the table and then decoding the `lui`/`ori` (or `addiu`) pair at
the top of each target gives the complete chunk-type -> asset-kind map
without needing a decompiler. That is what this script does: it reads the
ELF's program headers directly, so no MIPS toolchain and no Ghidra run are
involved.

Usage:
    python tools/chunk_loader_table.py "PS2 Files/NFSHP2.ELF"
"""
import struct
import sys
from pathlib import Path

LOADER_TABLE = 0x003081D0
UNLOADER_TABLE = 0x00308250
TABLE_ENTRIES = 31


class Elf:
    def __init__(self, path):
        self.buf = Path(path).read_bytes()
        b = self.buf
        phoff, = struct.unpack_from("<I", b, 0x1C)
        phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
        self.segs = []
        for i in range(phnum):
            o = phoff + i * phentsize
            p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIIII", b, o)
            if p_type == 1:
                self.segs.append((p_vaddr, p_offset, p_filesz))
        # symbols
        shoff, = struct.unpack_from("<I", b, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", b, 0x2E)
        secs = []
        for i in range(shnum):
            o = shoff + i * shentsize
            secs.append(struct.unpack_from("<IIIIIIIIII", b, o))
        self.syms = {}
        for s in secs:
            if s[1] != 2:  # SHT_SYMTAB
                continue
            stroff = secs[s[6]][4]
            for o in range(s[4], s[4] + s[5], 16):
                st_name, st_value, st_size, st_info, _, st_shndx = \
                    struct.unpack_from("<IIIBBH", b, o)
                if not st_value:
                    continue
                end = b.index(b"\0", stroff + st_name)
                name = b[stroff + st_name:end].decode("latin-1")
                # Several symbols share an address here (`gcc2_compiled.`,
                # per-object file markers); the FUNC/OBJECT one is the
                # useful name, so let it win regardless of table order.
                if (st_info & 0xF) in (1, 2) or st_value not in self.syms:
                    self.syms[st_value] = name

    def read(self, vaddr, n):
        for base, off, size in self.segs:
            if base <= vaddr < base + size:
                o = off + (vaddr - base)
                return self.buf[o:o + n]
        raise KeyError("vaddr 0x%08x not mapped" % vaddr)

    def u32(self, vaddr):
        return struct.unpack_from("<I", self.read(vaddr, 4))[0]


def guard_constants(elf, vaddr, limit=32, depth=2, ptr_init=(4,)):
    """Decode every chunk-type constant a Loader*() compares chunk->Type to.

    Four of the table slots are one-line thunks of the shape

        move a1, a0 ; lui a0, hi ; jal Loader__12CameraLoader ; addiu a0, a0, lo

    that forward to a C++ member function, so the guard actually lives in the
    callee -- hence the `jal` follow. Note what that thunk does to the
    argument registers: the callee's `this` takes a0 and the `bChunk *` moves
    to a1, so which register holds the chunk has to be carried across the
    call, not assumed.

    A loader may accept more than one type, so this follows the value rather
    than stopping at the first literal: track which register holds the `lw`
    from `chunk->Type`, track what each other register was loaded with, and
    emit a constant only where a branch actually compares the two.
    `LoaderFontInfo` is why this matters -- it takes 0x00030200 (accepted and
    ignored) *and* 0x00015010 (the real on-disc font chunk), and stopping at
    the first constant reported only the dead one. Anchoring on the `lw` is
    what keeps record sizes and loop counters out of the results, and the
    branch set has to include the EE's likely forms (`beql`/`bnel`), which
    are what several of these guards actually use.
    """
    words = struct.unpack("<%dI" % limit, elf.read(vaddr, limit * 4))
    upper, const = {}, {}
    ptr, typereg = set(ptr_init), set()  # a0 is the bChunk * on entry
    found, jal = [], None

    def _clobber(r):
        const.pop(r, None)
        upper.pop(r, None)  # noqa: F821 -- rebound on each block rollback
        typereg.discard(r)
        ptr.discard(r)

    def note(a, b):
        if a in typereg and b in const and const[b] not in found:
            found.append(const[b])

    snap = (dict(upper), dict(const))
    arm = skip = False
    for w in words:
        op, rs, rt, rd = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        imm, funct = w & 0xFFFF, w & 0x3F
        if skip:
            # Delay slot of an unconditional branch: it runs only on the path
            # that branch takes, so it must not be folded into the fall-through
            # state. `LoaderFontInfo` puts `addiu v0,zero,1` there.
            skip = False
            continue
        if op == 0x02 or (op == 0x04 and rs == 0 and rt == 0):   # j / b
            # End of the "this type matched" block. Everything since the last
            # guard branch belonged to that accepted path, not to the chain of
            # comparisons, so roll the register state back before reading the
            # next guard -- otherwise `LoaderTrackGeometry`'s `addiu v0,zero,1`
            # eats the `lui v0,0x0003` that 0x00034201 is built from.
            upper, const = dict(snap[0]), dict(snap[1])
            skip = True
            continue
        if op == 0x0F:                       # lui rt, imm
            _clobber(rt)
            upper[rt] = imm << 16
        elif op == 0x0D and rs in upper:     # ori rt, rs, imm
            hi = upper[rs]                   # read before rt == rs is cleared
            _clobber(rt)
            const[rt] = hi | imm
        elif op == 0x09:                     # addiu rt, rs, imm
            _clobber(rt)
            if rs == 0 and 0 < imm < 0x8000:
                const[rt] = imm
        elif op == 0x23:                     # lw rt, imm(rs)
            was_ptr = rs in ptr
            _clobber(rt)
            if imm == 0 and was_ptr:
                typereg.add(rt)              # rt = chunk->Type
        elif op == 0x00 and funct in (0x21, 0x25, 0x2D) and rt == 0:
            if rs in ptr:                    # move rd, rs  (rs is the chunk *)
                ptr.add(rd)
        elif op in (0x04, 0x05, 0x14, 0x15):  # beq / bne and their likely forms
            note(rs, rt)
            note(rt, rs)
            arm = True                       # snapshot after the delay slot
        elif op == 0x03 and jal is None:     # jal target
            jal = ((vaddr + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        if arm and op not in (0x04, 0x05, 0x14, 0x15):
            snap, arm = (dict(upper), dict(const)), False
    if found:
        return found
    if jal is not None and depth > 0:
        args = tuple(r for r in sorted(ptr) if 4 <= r <= 7) or (4,)
        return guard_constants(elf, jal, limit, depth - 1, args)
    return []


def main():
    elf = Elf(sys.argv[1] if len(sys.argv) > 1 else "PS2 Files/NFSHP2.ELF")
    for label, table in (("LoaderTable", LOADER_TABLE),
                         ("UnloaderTable", UNLOADER_TABLE)):
        print("== %s @ 0x%08x ==" % (label, table))
        for i in range(TABLE_ENTRIES):
            fp = elf.u32(table + i * 4)
            name = elf.syms.get(fp, "sub_%08x" % fp)
            cids = guard_constants(elf, fp) if fp else []
            print("  [%2d] 0x%08x  %-42s %s"
                  % (i, fp, name,
                     " ".join("type=0x%08x" % c for c in cids)))


if __name__ == "__main__":
    main()
