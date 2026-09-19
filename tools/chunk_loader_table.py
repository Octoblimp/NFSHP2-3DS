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


def guard_constant(elf, vaddr, limit=24, depth=2):
    """Decode the chunk-type constant a Loader*() compares chunk->Type against.

    Four of the table slots are one-line thunks of the shape

        move a1, a0 ; lui a0, hi ; jal Loader__12CameraLoader ; addiu a0, a0, lo

    that forward to a C++ member function, so the guard actually lives in the
    callee -- hence the `jal` follow.
    """
    words = struct.unpack("<%dI" % limit, elf.read(vaddr, limit * 4))
    upper = {}
    jal = None
    for w in words:
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:                       # lui rt, imm
            upper[rt] = imm << 16
        elif op == 0x0D and rs in upper:     # ori rt, rs, imm
            return upper[rs] | imm
        elif op == 0x09 and rs == 0 and 0 < imm < 0x8000:  # addiu rt, zero, imm
            return imm
        elif op == 0x03 and jal is None:     # jal target
            jal = ((vaddr + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
    if jal is not None and depth > 0:
        return guard_constant(elf, jal, limit, depth - 1)
    return None


def main():
    elf = Elf(sys.argv[1] if len(sys.argv) > 1 else "PS2 Files/NFSHP2.ELF")
    for label, table in (("LoaderTable", LOADER_TABLE),
                         ("UnloaderTable", UNLOADER_TABLE)):
        print("== %s @ 0x%08x ==" % (label, table))
        for i in range(TABLE_ENTRIES):
            fp = elf.u32(table + i * 4)
            name = elf.syms.get(fp, "sub_%08x" % fp)
            cid = guard_constant(elf, fp) if fp else None
            print("  [%2d] 0x%08x  %-42s %s"
                  % (i, fp, name,
                     ("type=0x%08x" % cid) if cid is not None else ""))


if __name__ == "__main__":
    main()
