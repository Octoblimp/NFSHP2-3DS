"""A retail vtable's first eight entries: each 8-byte entry's this-delta
pair and its function, with the function's label.

    python tools/retail_vtable.py 0x002b7ad0 [0x...]
"""
import struct
import sys

import mipsdis
import retaildis


def main():
    elf = mipsdis.Elf(retaildis.RETAIL)
    retaildis.load(elf, retaildis.SYMS)
    for a in [int(x, 16) for x in sys.argv[1:]]:
        print("table %08x" % a)
        for i in range(8):
            h, d, fn = struct.unpack("<hhI", elf.read(a + 8 * i, 8))
            print("  %3d  %d %d %08x  %s" % (8 * i, h, d, fn,
                                             elf.label(fn) if fn else ""))


if __name__ == "__main__":
    main()
