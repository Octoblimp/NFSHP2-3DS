#!/usr/bin/env python3
"""Refuses a .3dsx that Azahar's loader would refuse.

The 3DSX loader (Citra's, which Azahar keeps) patches each relocated word
from the file and gives up on the whole program -- "Failed to load ROM
(Error 1)", before a line of the app runs -- when an absolute relocation's
word has any of its top four bits set, or a relative one a sub-type past 1.
The linker and 3dsxtool are both happy to write such a word: it is what an
address outside every segment looks like, and gcc makes one whenever it
folds `table + negative constant` into a literal. The first one found was
in bFixATan1 (bmath.c), on a path only INT32_MIN takes.

This walks the relocations the way the loader does and names the word that
would fail, with the ELF symbol it sits in when the .elf is beside it.

Usage: check_3dsx.py path/to/app.3dsx      (exit 1 on a bad word)
"""

import os
import struct
import subprocess
import sys

BASE = 0x00100000
ADDR2LINE = r"C:\devkitPro\devkitARM\bin\arm-none-eabi-addr2line.exe"


def page(x):
    return (x + 0xfff) & ~0xfff


def check(path):
    d = open(path, "rb").read()
    magic, hsize, rhsize, _ver, _flags, code, rodata, data, bss = \
        struct.unpack_from("<4sHHIIIIII", d, 0)
    if magic != b"3DSX":
        return ["not a 3DSX file"]
    ntab = rhsize // 4
    pos = hsize
    counts = []
    for _ in range(3):
        counts.append(struct.unpack_from("<%dI" % ntab, d, pos))
        pos += rhsize

    sizes = [page(code), page(rodata), page(data)]
    starts = [0, sizes[0], sizes[0] + sizes[1]]
    img = bytearray(sum(sizes))
    for seg, n in enumerate((code, rodata, data - bss)):
        img[starts[seg]:starts[seg] + n] = d[pos:pos + n]
        pos += n

    bad = []
    for seg in range(3):
        end = starts[seg] + sizes[seg]
        for tab in range(ntab):
            n = counts[seg][tab]
            if tab >= 2:
                pos += n * 4
                continue
            p = starts[seg]
            for _ in range(n):
                skip, patch = struct.unpack_from("<HH", d, pos)
                pos += 4
                if p >= end:
                    continue
                p += skip * 4
                while patch > 0 and p < end:
                    word = struct.unpack_from("<I", img, p)[0]
                    sub = word >> 28
                    if (tab == 0 and sub != 0) or (tab == 1 and sub > 1):
                        bad.append((BASE + p, word, tab))
                    p += 4
                    patch -= 1
    return bad


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    bad = check(path)
    if bad and isinstance(bad[0], str):
        print("check_3dsx: %s: %s" % (path, bad[0]))
        return 1
    elf = os.path.splitext(path)[0] + ".elf"
    for addr, word, tab in bad:
        where = ""
        if os.path.exists(elf) and os.path.exists(ADDR2LINE):
            out = subprocess.run([ADDR2LINE, "-f", "-e", elf, "0x%x" % addr],
                                 capture_output=True, text=True).stdout.split()
            if out:
                where = " in " + " ".join(out)
        print("check_3dsx: %s relocation at %08x holds %08x%s" %
              ("absolute" if tab == 0 else "relative", addr, word, where))
    if bad:
        print("check_3dsx: %d word(s) the 3DSX loader will refuse" % len(bad))
        return 1
    print("check_3dsx: relocations OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
