"""Retail's gp-relative words, as a float, an int and hex, with the
symbol each falls in when retail_syms.txt places one there.

    python tools/retail_gp.py -29940 -29936 gp-20136
"""
import struct
import sys

import mipsdis
import retaildis


def main():
    elf = mipsdis.Elf(retaildis.RETAIL)
    retaildis.load(elf, retaildis.SYMS)
    for t in sys.argv[1:]:
        off = int(t[2:] if t.startswith("gp") else t, 0)
        a = (retaildis.GP + off) & 0xFFFFFFFF
        w = elf.read(a, 4)
        f, = struct.unpack("<f", w)
        i, = struct.unpack("<i", w)
        print("gp%+d  %08x  %08x  %-14r %d  %s" % (
            off, a, i & 0xFFFFFFFF, f, i, elf.by_addr.get(a, "")))


if __name__ == "__main__":
    main()
