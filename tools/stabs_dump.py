#!/usr/bin/env python3
"""Dump the .stab/.stabstr STABS debug info from NFSHP2.ELF into readable text.

NFSHP2.ELF (unlike the stripped PC/GameCube binaries NFSU2-3DS had to work
with) carries full a.out-style STABS debug info: struct/class layouts,
member offsets, and function signatures, compiled in by the PS2 SN Systems
toolchain. This dumper is the primary artifact for reimplementing bWare
engine types/functions on the 3DS side -- read its output instead of
guessing struct layouts from raw decompiler output.

Usage:
    python tools/stabs_dump.py "../PS2 Files/NFSHP2.ELF" > docs/stabs_dump.txt

Output format: one line per STAB entry, grouped by source file (N_SO marks
a new compilation unit). Type/variable/function stab strings use the
standard "name:type-descriptor-and-encoding" syntax; see
https://sourceware.org/gdb/onlinedocs/stabs/ for the encoding reference
when reading the dump.
"""
import struct
import sys

# N_* stab type codes (see binutils include/aout/stab_gnu.h). Values are the
# real a.out/ELF-stabs encoding, not sequential -- do not "tidy" these.
STAB_NAMES = {
    0x20: "GSYM", 0x22: "FNAME", 0x24: "FUN", 0x26: "STSYM", 0x28: "LCSYM",
    0x2a: "MAIN", 0x2c: "ROSYM", 0x30: "PC", 0x32: "NSYMS", 0x34: "NOMAP",
    0x38: "OBJ", 0x3c: "OPT", 0x40: "RSYM", 0x42: "M2C", 0x44: "SLINE",
    0x46: "DSLINE", 0x48: "BSLINE", 0x4a: "DEFD", 0x50: "EHDECL",
    0x54: "CATCH", 0x60: "SSYM", 0x64: "SO", 0x80: "LSYM", 0x82: "BINCL",
    0x84: "SOL", 0xa0: "PSYM", 0xa2: "EINCL", 0xa4: "ENTRY", 0xc0: "LBRAC",
    0xc2: "EXCL", 0xc4: "SCOPE", 0xe0: "RBRAC", 0xe2: "BCOMM", 0xe4: "ECOMM",
    0xe8: "ECOML", 0xfe: "LENG",
}
N_UNDF = 0
N_SO = 0x64


def stab_name(n_type):
    return STAB_NAMES.get(n_type, "0x%02x" % n_type)


def read_elf_section(path, name):
    with open(path, "rb") as f:
        data = f.read()
    if data[0:4] != b"\x7fELF":
        raise SystemExit("not an ELF file: %s" % path)
    ei_class = data[4]
    if ei_class != 1:
        raise SystemExit("expected 32-bit ELF (got class %d)" % ei_class)
    # ELF32 header (little-endian, as used by both PS2 MIPS and typical hosts here).
    (e_shoff,) = struct.unpack_from("<I", data, 0x20)
    (e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHH", data, 0x2e)

    def section_header(idx):
        off = e_shoff + idx * e_shentsize
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
         sh_link, sh_info, sh_addralign, sh_entsize) = struct.unpack_from(
            "<IIIIIIIIII", data, off)
        return dict(name=sh_name, type=sh_type, offset=sh_offset, size=sh_size)

    shstr_hdr = section_header(e_shstrndx)
    shstrtab = data[shstr_hdr["offset"]:shstr_hdr["offset"] + shstr_hdr["size"]]

    def sh_name_str(off):
        end = shstrtab.index(b"\x00", off)
        return shstrtab[off:end].decode("ascii", "replace")

    for idx in range(e_shnum):
        hdr = section_header(idx)
        if sh_name_str(hdr["name"]) == name:
            return data[hdr["offset"]:hdr["offset"] + hdr["size"]]
    raise SystemExit("section %s not found" % name)


def parse_stabs(stab_data, stabstr_data):
    """Yield (n_type, n_other, n_desc, n_value, string) for each STAB entry.

    Each entry is 12 bytes: u32 n_strx, u8 n_type, u8 n_other, u16 n_desc,
    u32 n_value. n_strx is an offset into the CURRENT compilation unit's
    slice of .stabstr. Each unit starts with an N_UNDF (n_type==0) header
    whose n_value gives that unit's string-table byte length; entries in
    that unit resolve n_strx against the base built up from every unit's
    length seen so far (units are laid out back-to-back in .stabstr).
    """
    entry_size = 12
    count = len(stab_data) // entry_size
    unit_base = 0
    next_unit_base = 0
    for i in range(count):
        off = i * entry_size
        n_strx, n_type, n_other, n_desc, n_value = struct.unpack_from(
            "<IBBHI", stab_data, off)
        if n_type == N_UNDF:
            unit_base = next_unit_base
            next_unit_base += n_value
            yield (n_type, n_other, n_desc, n_value, "")
            continue
        abs_off = unit_base + n_strx
        if 0 <= abs_off < len(stabstr_data):
            end = stabstr_data.find(b"\x00", abs_off)
            if end == -1:
                end = len(stabstr_data)
            s = stabstr_data[abs_off:end].decode("latin-1")
        else:
            s = "<bad strx %d>" % abs_off
        yield (n_type, n_other, n_desc, n_value, s)


def main():
    if len(sys.argv) != 2:
        print("usage: stabs_dump.py <path to ELF>", file=sys.stderr)
        raise SystemExit(2)
    elf_path = sys.argv[1]
    stab = read_elf_section(elf_path, ".stab")
    stabstr = read_elf_section(elf_path, ".stabstr")

    for n_type, n_other, n_desc, n_value, s in parse_stabs(stab, stabstr):
        tag = stab_name(n_type)
        line = "%-8s value=0x%08x desc=%-5d %s" % (tag, n_value, n_desc, s)
        print(line)


if __name__ == "__main__":
    main()
