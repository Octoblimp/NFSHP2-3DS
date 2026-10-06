"""A retail vtable's entries, eight unless -n says how many: each 8-byte
entry's this-delta pair and its function, with the function's label.

    python tools/retail_vtable.py 0x002b7ad0 [0x...]
    python tools/retail_vtable.py -n 18 0x002b4d90
"""
import struct
import sys

import mipsdis
import retaildis


def main():
    args = sys.argv[1:]
    n = 8
    if len(args) >= 2 and args[0] == "-n":
        n = int(args[1])
        args = args[2:]
    elf = mipsdis.Elf(retaildis.RETAIL)
    retaildis.load(elf, retaildis.SYMS)
    for a in [int(x, 16) for x in args]:
        print("table %08x" % a)
        for i in range(n):
            h, d, fn = struct.unpack("<hhI", elf.read(a + 8 * i, 8))
            print("  %3d  %d %d %08x  %s" % (8 * i, h, d, fn,
                                             elf.label(fn) if fn else ""))


if __name__ == "__main__":
    main()
