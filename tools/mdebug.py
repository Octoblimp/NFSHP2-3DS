#!/usr/bin/env python3
r"""Read the ECOFF symbolic debug tables in NFSHP2.ELF's .mdebug section.

The layouts are the 32-bit external records of binutils' include/coff/sym.h
and ecoff.h:

  HDRR  96 bytes: magic 0x7009, vstamp, then 23 counts and file offsets
  FDR   72 bytes: one per source file
  PDR   52 bytes: one per procedure
  SYMR  12 bytes: iss, value, and a word of st:6 sc:5 reserved:1 index:20

Offsets in the header are from the start of the ELF file.

What the rest of the tools want from it is the procedure list: every
function the compiler emitted, statics included, with its address. .symtab
leaves the statics out, so a function's body there runs on through any
static that follows it.

Usage:
    python tools/mdebug.py                 # summary
    python tools/mdebug.py --procs         # every procedure
    python tools/mdebug.py --file Car.cpp  # one file's symbols
"""
import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELF = ROOT / "PS2 Files" / "NFSHP2.ELF"

HDR_FIELDS = ("ilineMax", "cbLine", "cbLineOffset", "idnMax", "cbDnOffset",
              "ipdMax", "cbPdOffset", "isymMax", "cbSymOffset", "ioptMax",
              "cbOptOffset", "iauxMax", "cbAuxOffset", "issMax", "cbSsOffset",
              "issExtMax", "cbSsExtOffset", "ifdMax", "cbFdOffset", "crfd",
              "cbRfdOffset", "iextMax", "cbExtOffset")
FDR_FIELDS = ("adr", "rss", "issBase", "cbSs", "isymBase", "csym",
              "ilineBase", "cline", "ioptBase", "copt", "ipdFirst", "cpd",
              "iauxBase", "caux", "rfdBase", "crfd", "bits", "cbLineOffset",
              "cbLine")
PDR_FIELDS = ("adr", "isym", "iline", "regmask", "regoffset", "iopt",
              "fregmask", "fregoffset", "frameoffset", "framereg", "pcreg",
              "lnLow", "lnHigh", "cbLineOffset")

ST_NAMES = {0: "nil", 1: "global", 2: "static", 3: "param", 4: "local",
            5: "label", 6: "proc", 7: "block", 8: "end", 9: "member",
            10: "typedef", 11: "file", 14: "staticproc", 15: "constant"}
ST_PROC, ST_STATICPROC = 6, 14
CODE_MASK = 0x8F300          # a stab carried in an ECOFF symbol
N_FUN = 0x24


class MDebug(object):
    def __init__(self, path=ELF):
        self.data = d = Path(path).read_bytes()
        shoff = struct.unpack_from("<I", d, 0x20)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<3H", d, 0x2e)
        secs = [struct.unpack_from("<10I", d, shoff + i * shentsize)
                for i in range(shnum)]
        strsec = secs[shstrndx]
        self.off = None
        for f in secs:
            o = strsec[4] + f[0]
            if d[o:d.index(b"\0", o)] == b".mdebug":
                self.off = f[4]
        if self.off is None:
            raise SystemExit("%s has no .mdebug" % path)
        magic, vstamp = struct.unpack_from("<2H", d, self.off)
        if magic != 0x7009:
            raise SystemExit("bad .mdebug magic %#x" % magic)
        self.hdr = dict(zip(HDR_FIELDS,
                            struct.unpack_from("<23I", d, self.off + 4)))
        h = self.hdr
        self.fdrs = []
        for i in range(h["ifdMax"]):
            o = h["cbFdOffset"] + 72 * i
            v = struct.unpack_from("<10I2H7I", d, o)
            self.fdrs.append(dict(zip(FDR_FIELDS, v)))
        for f in self.fdrs:
            f["name"] = self.lstr(f, f["rss"])

    def lstr(self, fdr, iss):
        o = self.hdr["cbSsOffset"] + fdr["issBase"] + iss
        e = self.data.index(b"\0", o)
        return self.data[o:e].decode("latin-1")

    def syms(self, fdr):
        """(st, sc, index, value, name) of each local symbol of a file."""
        h = self.hdr
        for k in range(fdr["csym"]):
            o = h["cbSymOffset"] + 12 * (fdr["isymBase"] + k)
            iss, value, bits = struct.unpack_from("<3I", self.data, o)
            st = bits & 0x3f
            sc = (bits >> 6) & 0x1f
            index = bits >> 12
            yield st, sc, index, value, self.lstr(fdr, iss)

    def pdrs(self, fdr):
        h = self.hdr
        for k in range(fdr["cpd"]):
            o = h["cbPdOffset"] + 52 * (fdr["ipdFirst"] + k)
            v = struct.unpack_from("<9I2h3I", self.data, o)
            yield dict(zip(PDR_FIELDS, v))

    def procedures(self):
        """[(address, name, file, static)] from the proc symbols, deduped."""
        out = {}
        for f in self.fdrs:
            for st, sc, index, value, name in self.syms(f):
                if st in (ST_PROC, ST_STATICPROC):
                    out.setdefault(value, (value, name, f["name"],
                                           st == ST_STATICPROC))
                elif index & 0xfff00 == CODE_MASK and index - CODE_MASK == N_FUN:
                    # a stab N_FUN: "name:F..." global, "name:f..." static
                    nm, _, rest = name.partition(":")
                    if nm and rest[:1] in ("F", "f"):
                        out.setdefault(value, (value, nm, f["name"],
                                               rest[:1] == "f"))
        return sorted(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ELF))
    ap.add_argument("--procs", action="store_true")
    ap.add_argument("--file")
    a = ap.parse_args()
    m = MDebug(a.elf)
    h = m.hdr
    print("files %d, procedures %d, local symbols %d, externals %d"
          % (h["ifdMax"], h["ipdMax"], h["isymMax"], h["iextMax"]))
    if a.file:
        for f in m.fdrs:
            if a.file.lower() in f["name"].lower():
                print("== %s  adr %08x  %d syms  %d procs"
                      % (f["name"], f["adr"], f["csym"], f["cpd"]))
                for st, sc, index, value, name in m.syms(f):
                    print("  %-10s sc %2d idx %05x %08x %s"
                          % (ST_NAMES.get(st, st), sc, index, value, name[:100]))
    procs = m.procedures()
    statics = sum(1 for p in procs if p[3])
    print("procedures found: %d (%d static)" % (len(procs), statics))
    if a.procs:
        for addr, name, fn, static in procs:
            print("%08x %s %s  (%s)" % (addr, "s" if static else "g", name, fn))


if __name__ == "__main__":
    main()
