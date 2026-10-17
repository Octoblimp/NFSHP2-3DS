#!/usr/bin/env python3
"""Cross-check 3DS Files/source/replay.c's ReplaySnapshot and
3DS Files/source/brepeat.c's bRepeat against the retail image,
SLES_507.31 (TASKS 72a).

**The model** is retail's own code run in retail_model.RetailEmu:
ReplaySnapshot's Init, ChangeName, GetChecksum, WriteData, ReadData,
MoveData, VerifyData, BeginSection and EndSection, the inline overloads of
MoveData and VerifyData at their own addresses, BeginNamedSection and
EndNamedSection; bRepeat's WriteToLocation, ReadFromLocation,
PrepareToAddData, ShovelDataOffToCodeine, AddData, PrepareToRemoveData,
RemoveData and DoSnapshot. The snapshot (38232 bytes) and a 4096-byte
bRepeat buffer are the model's own, as they are the harness's
(tools/src/replay_test.c). PrintSectionName and PrintSpaces run as they
are; bStrCpy and bStrLen are retail's.

**The stubs**: bBreak counts, as the port's replay_breaks does;
bFunkCallASync, Codeine's host link, does nothing and answers 0.
WorldTimer and WorldLoopCounter are gp-19576 and gp-19552, written by the
script. InitChannel, inline in MarkTheBeginningOfTime, is two stores.

Before each op the model zeroes the stack below sp: a checksum that is
verified past the snapshot's end compares with whatever MoveData's frame
held, and the port compares with 0 (replay.c says so).

**The script** takes, restores, checksums and verifies through every
overload: values whose bytes past the stored ones are and are not the
sign (bBreak), stored counts over the size, -1 sizes, the data's last
byte (37887 fits, 37888 overflows, an OverflowedFlag already 5), reads
past SizeofData, checksums that verify, one that does not (one break a
section), MoveData outside every section, VerifyData in the modes that
skip it, sections nested 16 deep, their numbers, PrintDepth. For bRepeat:
four channels (repeat counts of 8, 4 and 0 bits), repeats to a full
count, repeats past other channels' items, other sizes and values, 0, 32
and 33 bits, a NULL bRepeat, the stream read back in order, on the wrong
channel and past its end, a stream filled to its limit with and without
Codeine, the shovel, both halves of DoSnapshot taken and restored, and
WriteToLocation / ReadFromLocation across bytes.

    python tools/replay_check.py
    python tools/replay_check.py --mutate [--only a,b] [--jobs N]
    python tools/replay_check.py --dump out/replay
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

NL = chr(10)

HARNESS = "tools/src/replay_test.c"
REPLAY = "3DS Files/source/replay.c"
BREPEAT = "3DS Files/source/brepeat.c"
SOURCES = [HARNESS, REPLAY, BREPEAT, "3DS Files/source/p32.c"]

GP = retail_model.RETAIL_GP
WORLD_TIMER = GP - 19576
WORLD_LOOP = GP - 19552

SNAP_SIZE = 38232
DATA = 344
DATA_SIZE = 37888
RBUF = 4096
RFILL = 0xa5

F_INIT = 0x0013cce8
F_RENAME = 0x0013cd60
F_CHECKSUM = 0x0013cd68
F_WRITE = 0x0013cda0
F_READ = 0x0013ce78
F_MOVE = 0x0013cf08
F_VERIFY = 0x0013d0d0
F_BEGIN = 0x0013d288
F_END = 0x0013d358
F_BEGIN_NAMED = 0x00139650
F_END_NAMED = 0x00139648
OVERLOADS = {
    "f": 0x001369d8, "timer": 0x001369c8, "v2": 0x001369b8,
    "v3": 0x0014eb20, "i": 0x001369e8, "u": 0x0014eb50, "s": 0x00149360,
    "us": 0x001369f8, "c": 0x00136a08, "sc": 0x00136a28, "uc": 0x0013cab0,
    "b": 0x00136a18, "vf": 0x001a3e88, "vv2": 0x001d8d48, "vv3": 0x001d8d38,
    "vi": 0x00149320, "vu": 0x00221dd8, "vs": 0x001d8d78, "vus": 0x001d8d88,
    "vsc": 0x001d8d98,
}
R_SNAPSHOT = 0x0013cb90
R_WRITE = 0x001eb050
R_READ = 0x001eb0c0
R_PREP_ADD = 0x001eb120
R_SHOVEL = 0x001eb1a8
R_ADD = 0x001eb2d8
R_PREP_REMOVE = 0x001eb498
R_REMOVE = 0x001eb4e8
S_BBREAK = 0x00250ab0
S_FUNK_ASYNC = 0x0025d048

LIMIT = 2000000

# The ops' fields that are names, not numbers.
NAMED = {"init": (1,), "rename": (1,), "set": (1,), "val": (1,),
         "ov": (1,), "begin": (2,), "bnamed": (1,)}

# Snapshot fields `set` writes: offset, bytes.
FIELDS = {"t": (40, 4), "et": (44, 4), "blt": (48, 4), "elt": (52, 4),
          "mil": (56, 4), "depth": (64, 1), "ovf": (65, 1), "secnum": (66, 2), "pd": (68, 4),
          "plc": (72, 4), "pos": (336, 4), "size": (340, 4), "tiv": (332, 4)}


# ================================================================== script

def take_values():
    """Take mode through every overload, with fills that break."""
    s = ["timer|4000|100", "init|FIRST", "dump", "flags|1|0|0|0",
         "bnamed|Car"]
    s += ["val|0102030405060708090a0b0c", "ov|f", "ov|timer", "ov|v2",
          "ov|v3"]
    s += ["val|78563412", "ov|i|4", "ov|i|2", "ov|i|3"]
    s += ["val|807f0000", "ov|i|2", "val|7f800000", "ov|i|2",
          "val|7f80ffff", "ov|i|2", "val|807fffff", "ov|i|2"]
    s += ["val|ff7f0000", "ov|i|1"]                 # fill ff, 7f breaks
    s += ["val|80ffffff", "ov|i|1", "ov|i|2"]       # fill ff, all ff
    s += ["val|80ffffff", "ov|u|1", "ov|b|1"]       # fill 0: breaks
    s += ["val|7f000000", "ov|u|1", "ov|b|2"]
    s += ["val|fe00", "ov|s|1", "ov|us|1"]
    s += ["val|feff", "ov|s|1", "ov|us|1", "ov|s|2"]
    s += ["val|81", "ov|c|1", "ov|sc|1", "ov|uc|1", "ov|c|0", "ov|uc|0"]
    s += ["val|81ff", "ov|i|0", "val|~", "ov|i|0", "ov|u|0"]
    s += ["begin|0x1234|Inner", "val|a1a2a3a4a5a6a7a8",
          "mv|3|-1|0", "mv|5|2|0", "mv|0|-1|1", "mv|2|4|1", "mv|2|4|0",
          "val|ffffffff", "mv|2|4|1", "mv|2|4|0", "mv|1|3|1",
          "wd|2|2|0", "end", "bend", "dump"]
    # VerifyData skips take and restore.
    vs = ["ov|vi|4", "ov|vf", "ov|vu|4", "ov|vs|2", "ov|vus|2",
          "ov|vv2", "ov|vv3", "ov|vsc|1"]
    s += ["val|55", "vd|1|-1|0"] + vs + ["flags|0|1|0|0", "set|size|30000",
                                         "vd|1|-1|0"] + vs + ["dump"]
    return s


def overflow():
    s = ["timer|8000|200", "init|OVF", "flags|1|0|0|0", "bnamed|Big",
         "set|pos|37880", "val|0102030405060708"]
    s += ["mv|7|-1|0", "dump", "mv|1|-1|0", "dump", "mv|0|-1|0"]
    s += ["set|ovf|5", "mv|1|-1|0", "dump", "set|ovf|-3", "mv|4|-1|0",
          "dump",
          "set|pos|37887", "set|ovf|0", "mv|0|-1|0", "mv|1|-1|0",
          "set|pos|37886", "set|ovf|0", "mv|1|-1|0", "bend", "dump"]
    return s


def restore():
    """The take's bytes read back: sign and zero fills, reads past the
    end leave the value alone."""
    s = ["timer|12|7", "init|REST", "set|size|40", "flags|0|1|0|0",
         "bnamed|Rest", "val|~"]
    for k in ("i|4", "i|1", "u|1", "s|1", "us|1", "c|1", "uc|1", "b|1",
              "f", "v3", "i|2", "u|2", "sc|1", "s|2", "v2", "timer"):
        s += ["val|" + "cc" * 16, "ov|" + k]
    for k in ("i|1", "u|1", "s|1", "us|1", "b|1", "c|1", "uc|1", "i|2",
              "u|2", "u|3", "i|3"):
        s += ["set|pos|37", "val|" + "cc" * 16, "ov|" + k]
    s += ["set|pos|36", "val|~", "rd|4|4|1", "set|pos|36", "rd|3|4|1",
          "rd|4|4|0", "rd|5|5|0",
          "set|pos|30", "rd|2|4|1", "rd|1|-1|0", "rd|0|3|0", "mv|1|3|1",
          "mv|2|-1|0", "set|size|-1", "mv|0|-1|0", "rd|0|2|1"]
    s += ["bend", "dump"]
    return s


def checksums():
    s = ["timer|400|30", "init|CK", "flags|0|0|1|0", "bnamed|A",
         "val|0102030405", "ov|vi|4", "ov|vf", "ov|v3", "end"]
    s += ["bnamed|B", "val|ff", "ov|vsc|1", "ov|c|1", "vd|0|-1|0",
          "val|00ff00ff00ff00ff00ff00ff", "ov|vv2", "ov|vv3", "ov|vu|4",
          "ov|vs|2", "ov|vus|2", "end", "dump"]
    s += ["init|CK2", "set|size|22", "flags|0|0|0|1", "bnamed|A",
          "val|0102030405", "ov|vi|4", "ov|vf", "val|0102030406", "ov|v3",
          "ov|vi|4", "dump", "end"]
    s += ["bnamed|B", "val|fe", "ov|vsc|1", "ov|vsc|1", "val|ff",
          "ov|c|1", "end", "bnamed|C", "mv|1|-1|0", "mv|0|-1|0", "end",
          "set|pos|22", "bnamed|D", "val|~", "mv|0|-1|0", "mv|0|-1|0",
          "end", "bnamed|E", "val|ff", "mv|1|-1|0", "end", "dump"]
    # Checksums of nothing, of 5 bytes and of the whole buffer.
    s += ["val|0102030405ffeeddccbbaa99887766554433221100f0e0d0c0b0a090807",
          "ck|0", "ck|1", "ck|5", "ck|32", "ck|64"]
    # Both checksum flags at once: taking wins.
    s += ["init|CK3", "flags|0|0|1|1", "bnamed|D", "val|11", "ov|vi|4",
          "end", "flags|0|0|0|0", "bnamed|E", "ov|vi|4", "ov|i|4",
          "end", "dump"]
    return s


def sections():
    s = ["timer|5|9", "init|SEC", "flags|1|0|0|0", "val|31",
         "mv|1|-1|0", "mv|1|-1|0", "dump"]
    # Sixteen deep, then out again; each section moves a byte.
    for d in range(16):
        s += ["begin|%#x|L%d" % (0x100 + d, d), "mv|1|-1|0"]
    s += ["dump"]
    for d in range(16):
        s += ["mv|2|-1|0", "end"]
    s += ["dump"]
    # A fresh first level numbers from 0 again; a second does not.
    s += ["bnamed|N0", "end", "bnamed|N1", "bnamed|N2", "end", "end",
          "dump"]
    # PrintDepth: printed from depth 1 on this loop, cleared below it.
    s += ["set|pd|1", "set|plc|9", "bnamed|P0", "bnamed|P1", "bnamed|P2",
          "end", "dump", "end", "dump", "end", "dump"]
    s += ["set|pd|0", "set|plc|8", "bnamed|Q0", "end", "dump"]
    s += ["set|pd|-5", "bnamed|Q1", "end", "dump"]
    s += ["rename|RENAMED", "dump", "timer|-4|-1", "init|X", "dump"]
    # Init clears all but the list node, EndTime and the sections.
    s += ["flags|1|1|1|1", "set|ovf|3", "set|secnum|9", "set|plc|4",
          "set|tiv|0x3f800000", "set|pos|7", "set|size|8", "set|elt|5",
          "set|mil|1", "set|et|77", "set|depth|4", "set|pd|2", "set|t|3",
          "set|blt|6", "timer|11|12", "init|Z", "dump", "rename|Z2",
          "dump", "set|depth|-1"]
    # Every mode flag up: taking wins.
    s += ["set|size|1000", "flags|1|1|1|1", "bnamed|F", "val|4142",
          "mv|2|-1|0",
          "flags|0|1|1|1", "mv|2|-1|0", "flags|0|0|1|1", "mv|2|-1|0",
          "end", "dump"]
    s += ["set|tiv|0x40490fdb", "set|secnum|65535", "set|depth|2",
          "bnamed|W", "end", "dump"]
    return s


def channels(size, nch, cod, chans):
    s = ["rprep|%d|%d|%d" % (size, nch, cod)]
    s += ["rchan|%d|%d|%d" % c for c in chans]
    return s


def repeat_adds():
    s = channels(1024, 4, 0, [(0, 8, 0), (1, 4, -1), (2, 0, 7), (3, 8, 0)])
    s += ["rdump"]
    s += ["radd|5|8|0", "radd|5|8|0", "radd|5|8|0", "radd|6|8|0",
          "radd|5|8|0", "radd|5|4|0", "radd|5|4|0"]
    s += ["radd|-1|32|1"] * 18                  # a count of 15, then anew
    s += ["radd|3|2|2", "radd|3|2|2", "radd|3|2|2"]   # 0 bits: never
    s += ["radd|9|8|3", "radd|1|1|0", "radd|9|8|3", "radd|2|2|2",
          "radd|9|8|3", "radd|9|8|3"]
    s += ["radd|0|0|0", "radd|0|0|0", "radd|7|33|3", "radd|7|33|3",
          "radd|0x80000000|32|1", "radd|0x1ff|8|0", "radd|0xff|8|0",
          "radd|0x1ff|8|0"]
    s += ["radd|4|8|0"] * 300                   # past 255 repeats
    s += ["raddnull|1|1|0", "rdump"]
    return s


def snapshots():
    """DoSnapshot both ways, taken, then the stream moved on and the
    snapshots restored."""
    s = ["timer|1|1", "init|RS", "flags|1|0|0|0", "rsnap|1", "rsnap|0",
         "dump"]
    s += ["radd|8|8|0", "radd|8|8|0", "radd|2|8|3", "rrem|8|0",
          "rdump"]
    s += ["init|RS2", "set|size|200", "flags|0|1|0|0", "rset|40|1",
          "rsnap|1", "rdump", "rsnap|0", "rdump", "dump"]
    s += ["init|RS3", "flags|0|0|1|0", "rsnap|1", "rsnap|0", "dump"]
    return s


def removes():
    s = ["rpr", "rdump"]
    want = [(8, 0)] * 5 + [(4, 0)] * 2 + [(32, 1)] * 18 + [(2, 2)] * 3
    want += [(8, 3), (1, 0), (8, 3), (2, 2), (8, 3), (8, 3)]
    want += [(0, 0), (0, 0), (33, 3), (33, 3), (32, 1), (8, 0), (8, 0),
             (8, 0)]
    s += ["rrem|%d|%d" % w for w in want]
    s += ["rrem|8|0"] * 300
    s += ["rdump"]
    s += ["rrem|8|1", "rrem|8|0", "rrem|8|3", "rdump", "rpr", "rdump"]
    # Out of step: the next item is asked on another channel.
    s += ["rpr", "rrem|8|0", "rrem|8|3", "rrem|8|0", "rrem|8|0",
          "rrem|8|0", "rrem|4|0", "rrem|32|1", "rdump"]
    return s


def fill():
    s = channels(200, 1, 0, [(0, 0, 3)])
    s += ["radd|%d|32|0" % (i * 0x01010101) for i in range(30)]
    s += ["rdump", "rpr"]
    s += ["rrem|32|0"] * 26
    s += ["rdump"]
    s += ["rset|8|1531", "radd|1|1|0", "rdump", "rset|8|1532",
          "radd|1|1|0", "rset|8|1535", "radd|1|1|0", "rset|8|1536",
          "radd|1|1|0", "rset|8|1528", "radd|-1|32|0", "rdump"]
    # Codeine: a full stream is shovelled down to its part byte.
    s += channels(200, 2, 1, [(0, 4, 0), (1, 3, 9)])
    for i in range(40):
        s += ["radd|%d|%d|%d" % (i * 77, 5 + i % 7, i % 2)]
        if i % 9 == 0:
            s += ["rdump"]
    s += ["rdump", "rshovel", "rdump"]
    s += ["rset|8|%d" % (120 * 8 + 3 * 8), "rshovel", "rdump"]
    s += ["rset|8|%d" % (120 * 8 + 19), "rshovel", "rdump"]
    s += ["rset|8|%d" % (120 * 8 + 2016 * 8 + 13), "rshovel", "rdump"]
    s += ["rset|8|%d" % (84 * 8 + 5), "rshovel", "rdump"]
    return s


def bits():
    s = channels(1024, 12, 0, [(0, 8, 0), (9, 2, 5), (15, 3, 6),
                               (11, 0, 0)])
    s += ["radd|0|0|0", "radd|0|0|0", "radd|3|4|9", "radd|3|4|9",
          "radd|0|0|11", "radd|7|8|15", "rdump", "rpr", "rrem|0|0",
          "rrem|0|0", "rrem|4|9", "rrem|4|9", "rrem|0|11", "rrem|8|15",
          "rrem|8|15", "rdump"]
    s += channels(1024, 1, 0, [(0, 8, 0)])
    s += ["rw|1000|0x12345678|32", "rr|1000|32", "rr|1003|9",
          "rw|1001|-1|1", "rr|1000|8", "rw|1007|3|2", "rr|1000|16",
          "rr|999|33", "rw|1010|5|0", "rr|1010|0", "rw|1020|0x2aaaaaaa|33",
          "rr|1020|33", "rr|1020|7", "rw|1100|0xffffffff|31",
          "rr|1100|32", "rw|2000|-2|64", "rr|2000|64", "rr|1999|1",
          "rdump"]
    return s


def script():
    return (take_values() + overflow() + restore() + checksums() +
            sections() + repeat_adds() + snapshots() + removes() + fill() +
            bits())


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.breaks = 0
        self.names = {}
        self.S = e.alloc(SNAP_SIZE)
        e.write(self.S, b"\0" * SNAP_SIZE)
        self.R = e.alloc(RBUF)
        e.write(self.R, bytes([RFILL]) * RBUF)
        self.V = e.alloc(64)
        e.write(self.V, b"\0" * 64)
        e.put32(WORLD_TIMER, 0)
        e.put32(WORLD_LOOP, 0)
        e.stub(S_BBREAK, self.bbreak)
        e.stub(S_FUNK_ASYNC, lambda em: 0)

    def emit(self, s):
        self.out.append(s)

    def bbreak(self, em):
        self.breaks += 1
        return 0

    def name(self, s):
        if s not in self.names:
            a = self.e.alloc(len(s) + 1, align=4)
            self.e.write(a, s.encode("latin-1") + b"\0")
            self.names[s] = a
        return self.names[s]

    def cstr(self, a, n=400):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def call(self, f, *args):
        return self.e.call(f, *[s32(a & M32) for a in args], limit=LIMIT)

    def value(self):
        self.emit("v %s b=%d" % (self.e.read(self.V, 16).hex(),
                                 self.breaks))

    def dump(self):
        e, S = self.e, self.S
        g = lambda o: s32(e.u32(S + o))
        b = lambda o: s32(e.mem[S + o] << 24) >> 24
        nm = e.read(S + 8, 32).split(b"\0")[0].decode("latin-1")
        self.emit("snap name=%s t=%d et=%d blt=%d elt=%d mil=%d "
                  "flags=%d,%d,%d,%d depth=%d ovf=%d secnum=%u pd=%d plc=%d "
                  "tiv=%08x pos=%d size=%d breaks=%d" % (
                      nm, g(40), g(44), g(48), g(52), g(56), b(60), b(61),
                      b(62), b(63), b(64), b(65), e.u16(S + 66), g(68),
                      g(72), e.u32(S + 332), g(336), g(340), self.breaks))
        for i in range(16):
            a = S + 76 + 16 * i
            p = e.u32(a)
            self.emit("sec %d name=%s obj=%08x num=%u nmd=%u err=%d size=%d"
                      % (i, self.cstr(p) if p else "-", e.u32(a + 4),
                         e.u16(a + 8), e.mem[a + 10],
                         s32(e.mem[a + 11] << 24) >> 24, s32(e.u32(a + 12))))
        self.emit("data %08x %s" % (fnv(e.read(S + DATA, DATA_SIZE)),
                                    e.read(S + DATA, 48).hex()))

    def rdump(self):
        e, R = self.e, self.R
        g = lambda o: s32(e.u32(R + o))
        self.emit("rep magic=%08x cnu=%d add=%d hdr=%d rem=%d bufsz=%d "
                  "nch=%d codeine=%d nadd=%d nrem=%d err=%d rt=%d" % (
                      e.u32(R), g(4), g(8), g(12), g(16), g(20), g(24),
                      g(28), g(32), g(36), g(40), g(44)))
        for c in range(min(g(24), 8)):
            o = 48 + 36 * c
            self.emit("ch %d rs=%d def=%d ads=%d arc=%d al=%d ad=%d rrc=%d "
                      "rl=%d rd=%d" % ((c,) + tuple(g(o + 4 * k)
                                                    for k in range(9))))
        at = g(12)
        if at < 0 or at > RBUF - 40:
            at = 0
        self.emit("rbuf %08x %s" % (fnv(e.read(R, RBUF)),
                                    e.read(R + at, 40).hex()))

    def op(self, a):
        e, S, R, V = self.e, self.S, self.R, self.V
        o = a[0]

        def num(i):
            return int(a[i], 0)
        n = [num(i) for i in range(1, len(a)) if o not in NAMED or
             i not in NAMED[o]]
        if o == "timer":
            e.put32(WORLD_TIMER, n[0])
            e.put32(WORLD_LOOP, n[1])
        elif o == "init":
            self.call(F_INIT, S, self.name(a[1]))
        elif o == "rename":
            self.call(F_RENAME, S, self.name(a[1]))
        elif o == "flags":
            for k in range(4):
                e.mem[S + 60 + k] = n[k] & 0xff
        elif o == "set":
            off, size = FIELDS[a[1]]
            v = int(a[2], 0) & ((1 << (8 * size)) - 1)
            e.write(S + off, v.to_bytes(size, "little"))
        elif o == "val":
            raw = b"" if a[1] == "~" else bytes.fromhex(
                a[1][:len(a[1]) // 2 * 2])
            e.write(V, (raw + b"\0" * 64)[:64])
        elif o in ("mv", "vd", "wd", "rd"):
            f = {"mv": F_MOVE, "vd": F_VERIFY, "wd": F_WRITE,
                 "rd": F_READ}[o]
            self.call(f, S, V, n[0], n[1], n[2])
            self.value()
        elif o == "ck":
            self.emit("ck %08x" % (self.call(F_CHECKSUM, S, V, n[0]) & M32))
        elif o == "ov":
            self.call(OVERLOADS[a[1]], S, V, n[0] if n else 0)
            self.value()
        elif o == "begin":
            self.call(F_BEGIN, S, n[0], self.name(a[2]))
        elif o == "bnamed":
            self.call(F_BEGIN_NAMED, S, self.name(a[1]))
        elif o == "end":
            self.call(F_END, S)
        elif o == "bend":
            self.call(F_END_NAMED, S)
        elif o == "dump":
            self.dump()
        elif o == "rprep":
            self.call(R_PREP_ADD, R, n[0], n[1], n[2])
        elif o == "rchan":
            e.put32(R + 48 + 36 * n[0], n[1])
            e.put32(R + 48 + 36 * n[0] + 4, n[2])
        elif o == "radd":
            self.emit("add %d" % self.call(R_ADD, R, n[0], n[1], n[2]))
        elif o == "raddnull":
            self.emit("add %d" % self.call(R_ADD, 0, n[0], n[1], n[2]))
        elif o == "rrem":
            self.emit("rem %d" % self.call(R_REMOVE, R, n[0], n[1]))
        elif o == "rpr":
            self.call(R_PREP_REMOVE, R)
        elif o == "rshovel":
            self.call(R_SHOVEL, R)
        elif o == "rw":
            self.call(R_WRITE, R, n[0], n[1], n[2])
        elif o == "rr":
            self.emit("rr %d" % self.call(R_READ, R, n[0], n[1]))
        elif o == "rset":
            e.put32(R + n[0], n[1])
        elif o == "rsnap":
            self.call(R_SNAPSHOT, R, S, n[0])
        elif o == "rdump":
            self.rdump()
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            top = sp & M32
            e.mem[top - 0x4000:top] = bytes(0x4000)
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def fnv(data):
    h = 0x811c9dc5
    for c in data:
        h = ((h ^ c) * 0x01000193) & M32
    return h


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="replay_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path, timeout=60):
    rc = mutpar.run_exe([exe, sc_path], out_path, timeout)
    if rc == mutpar.HUNG:
        print("harness hung, killed after %d s" % timeout)
    elif rc != 0:
        print("harness exited %d" % rc)
    return rc


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_bytes((NL.join(lines) + NL).encode("latin-1"))
    return sc


# ============================================================ the mutations

P, B, H = REPLAY, BREPEAT, "3DS Files/source/replay.h"


def M(name, before, after, rel=P):
    return (name, rel, before, after)


def MB(name, before, after):
    return (name, B, before, after)


def MH(name, before, after):
    return (name, H, before, after)


MUTATIONS = [
    # -- the section stack
    M("sec-base", "(uint8_t *)s + 76 + depth * 16",
      "(uint8_t *)s + 72 + depth * 16"),
    M("sec-stride", "(uint8_t *)s + 76 + depth * 16",
      "(uint8_t *)s + 76 + depth * 12"),

    # -- Init and ChangeName
    M("init-time", "    s->Time = WorldTimer;",
      "    s->Time = WorldLoopCounter;"),
    M("init-loop", "    s->BeginLoopTime = WorldLoopCounter;",
      "    s->BeginLoopTime = WorldTimer;"),
    M("init-depth", "    s->CurrentSectionDepth = -1;",
      "    s->CurrentSectionDepth = 0;"),
    M("init-pd", "    s->PrintDepth = -1;\n    s->SizeofData",
      "    s->PrintDepth = 0;\n    s->SizeofData"),
    M("init-size", "    s->SizeofData = 0;\n", ""),
    M("init-elt", "    s->EndLoopTime = 0;\n", ""),
    M("init-et", "    s->EndLoopTime = 0;\n",
      "    s->EndLoopTime = 0;\n    s->EndTime = 0;\n"),
    M("init-mil", "    s->MemoryImageLoadedFlag = 0;\n", ""),
    M("init-take", "    s->TakingSnapshotFlag = 0;\n", ""),
    M("init-restore", "    s->RestoringSnapshotFlag = 0;\n", ""),
    M("init-taking-ck", "    s->TakingChecksumFlag = 0;\n", ""),
    M("init-verify", "    s->VerifyingChecksumFlag = 0;\n", ""),
    M("init-ovf", "    s->OverflowedFlag = 0;\n", ""),
    M("init-secnum", "    s->CurrentSectionNumber = 0;\n    s->PrintLoopCounter",
      "    s->PrintLoopCounter"),
    M("init-plc", "    s->PrintLoopCounter = 0;\n", ""),
    M("init-tiv", "    s->TotalInterestingValue = 0.0f;\n", ""),
    M("init-pos", "    s->DataPosition = 0;\n}", "}"),
    M("init-name", "    strcpy(s->Name, name);\n    s->Time", "    s->Time"),
    M("rename", "    strcpy(s->Name, name);\n}", "    (void)name;\n}"),

    # -- GetChecksum
    M("ck-seed", "uint32_t h = 0xffffffffu;", "uint32_t h = 0;"),
    M("ck-mul", "h = h * 33u + p[i];", "h = h * 31u + p[i];"),
    M("ck-xor", "h = h * 33u + p[i];", "h = (h * 33u) ^ p[i];"),
    M("ck-signed", "    const uint8_t *p = data;\n    uint32_t h",
      "    const int8_t *p = data;\n    uint32_t h"),
    M("ck-short", "    for (i = 0; i < n; i++)\n        h = h * 33u",
      "    for (i = 0; i + 1 < n; i++)\n        h = h * 33u"),

    # -- WriteData
    M("ovf-ge", "if (pos + stored > REPLAY_SNAPSHOT_DATA_SIZE - 1) {",
      "if (pos + stored >= REPLAY_SNAPSHOT_DATA_SIZE - 1) {"),
    M("ovf-full", "if (pos + stored > REPLAY_SNAPSHOT_DATA_SIZE - 1) {",
      "if (pos + stored > REPLAY_SNAPSHOT_DATA_SIZE) {"),
    M("ovf-set", "        if (!s->OverflowedFlag)\n"
      "            s->OverflowedFlag = 1;",
      "        s->OverflowedFlag = 1;"),
    M("ovf-silent", "        if (!s->OverflowedFlag)\n"
      "            s->OverflowedFlag = 1;", ""),
    M("ovf-writes", "            s->OverflowedFlag = 1;\n        return;",
      "            s->OverflowedFlag = 1;"),
    M("write-fill-sign",
      "        fill = (is_signed && (last & 0x80)) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            if",
      "        fill = (last & 0x80) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            if"),
    M("write-fill-unsigned",
      "        fill = (is_signed && (last & 0x80)) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            if",
      "        fill = 0;\n        for (; i < size; i++)\n            if"),
    M("write-fill-bit",
      "        fill = (is_signed && (last & 0x80)) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            if",
      "        fill = (is_signed && (last & 0x40)) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            if"),
    M("write-break-each", "                replay_breaks++;\n"
      "                break;", "                replay_breaks++;"),
    M("write-no-break", "                replay_breaks++;\n"
      "                break;", "                break;"),
    M("write-first", "            if (src[i] != fill) {",
      "            if (src[size - 1] != fill) {"),
    M("write-last-first", "        last = src[i];\n"
      "        s->Data[pos++] = last;",
      "        if (i == 0)\n            last = src[i];\n"
      "        s->Data[pos++] = src[i];"),
    M("write-pos", "    s->DataPosition = pos;\n}\n\n// 0x0013ce78",
      "}\n\n// 0x0013ce78"),

    # -- ReadData
    M("read-le", "if (s->SizeofData < pos + stored)",
      "if (s->SizeofData <= pos + stored)"),
    M("read-any", "if (s->SizeofData < pos + stored)",
      "if (s->SizeofData < pos)"),
    M("read-fill-zero", "            dst[i] = fill;",
      "            dst[i] = 0;"),
    M("read-fill-sign",
      "        fill = (is_signed && (last & 0x80)) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            dst",
      "        fill = (last & 0x80) ? 0xff : 0;\n"
      "        for (; i < size; i++)\n            dst"),
    M("read-pos", "    s->DataPosition = pos;\n}\n\n// 0x0013cf08",
      "}\n\n// 0x0013cf08"),

    # -- MoveData and VerifyData
    M("move-size", "        size = stored;", "        size = stored + 1;"),
    M("move-nmd", "    sec->NumMoveData++;\n", ""),
    M("move-restore-too", "    } else if (s->RestoringSnapshotFlag) {",
      "    }\n    if (s->RestoringSnapshotFlag) {"),
    M("move-ck-first", "    if (s->TakingSnapshotFlag) {\n"
      "        ReplaySnapshot_WriteData",
      "    if (s->TakingSnapshotFlag && !s->TakingChecksumFlag) {\n"
      "        ReplaySnapshot_WriteData"),
    M("move-verify-first", "    } else if (s->TakingChecksumFlag) {",
      "    } else if (s->TakingChecksumFlag && !s->VerifyingChecksumFlag) {"),
    M("ck-write-1", "        ReplaySnapshot_WriteData(s, &h, 2, 2, 0);",
      "        ReplaySnapshot_WriteData(s, &h, 1, 2, 0);"),
    M("ck-high", "        uint16_t h = (uint16_t)ReplaySnapshot_GetChecksum("
      "s, p, stored);\n\n        ReplaySnapshot_WriteData",
      "        uint16_t h = (uint16_t)(ReplaySnapshot_GetChecksum("
      "s, p, stored) >> 16);\n\n        ReplaySnapshot_WriteData"),
    M("verify-was", "        uint16_t was = 0;",
      "        uint16_t was = 0xffff;"),
    M("verify-every", "        if (h != was && !sec->ChecksumErrorDetected) {",
      "        if (h != was) {"),
    M("verify-never", "        if (h != was && !sec->ChecksumErrorDetected) {",
      "        if (0) {"),
    M("verify-mark", "            sec->ChecksumErrorDetected = 1;\n", ""),
    M("verify-break", "            sec->ChecksumErrorDetected = 1;\n"
      "            replay_breaks++;",
      "            sec->ChecksumErrorDetected = 1;"),
    M("vd-taking",
      "    if (s->TakingChecksumFlag || s->VerifyingChecksumFlag)",
      "    if (s->VerifyingChecksumFlag)"),
    M("vd-verifying",
      "    if (s->TakingChecksumFlag || s->VerifyingChecksumFlag)",
      "    if (s->TakingChecksumFlag)"),
    M("vd-always",
      "    if (s->TakingChecksumFlag || s->VerifyingChecksumFlag)",
      "    if (1)"),

    # -- sections
    M("begin-reset", "    if (s->CurrentSectionDepth == -1)\n"
      "        s->CurrentSectionNumber = 0;\n", ""),
    M("begin-reset-always", "    if (s->CurrentSectionDepth == -1)\n"
      "        s->CurrentSectionNumber = 0;",
      "    s->CurrentSectionNumber = 0;"),
    M("begin-number", "    sec->Number = n;",
      "    sec->Number = (uint16_t)(n + 1);"),
    M("begin-count", "    s->CurrentSectionNumber = (uint16_t)(n + 1);",
      "    s->CurrentSectionNumber = n;"),
    M("begin-nmd", "    sec->NumMoveData = 0;\n", ""),
    M("begin-err", "    sec->ChecksumErrorDetected = 0;\n", ""),
    M("begin-object", "    sec->Object = p32_of(object);",
      "    sec->Object = 0;"),
    M("begin-size", "    sec->Size = pos;", "    sec->Size = 0;"),
    M("begin-name", "    sec->Name = p32_of(name);", "    sec->Name = 0;"),
    M("end-size", "    sec->Size = s->DataPosition - sec->Size;",
      "    sec->Size = s->DataPosition;"),
    M("end-depth", "    s->CurrentSectionDepth = "
      "(int8_t)(s->CurrentSectionDepth - 1);\n    if", "    if"),
    M("end-pd-le", "    if (s->CurrentSectionDepth < s->PrintDepth)",
      "    if (s->CurrentSectionDepth <= s->PrintDepth)"),
    M("end-pd-never", "    if (s->CurrentSectionDepth < s->PrintDepth)\n"
      "        s->PrintDepth = -1;", ""),
    M("end-pd-zero", "        s->PrintDepth = -1;",
      "        s->PrintDepth = 0;"),

    # -- bRepeat::DoSnapshot
    M("rsnap-name", 'ReplaySnapshot_BeginNamedSection(s, "bRepeat");',
      'ReplaySnapshot_BeginNamedSection(s, "Repeat");'),
    M("rsnap-side", "    if (adding) {\n"
      "        ReplaySnapshot_MoveInt(s, &r->AddLocation, 4);",
      "    if (!adding) {\n"
      "        ReplaySnapshot_MoveInt(s, &r->AddLocation, 4);"),
    M("rsnap-order", "        ReplaySnapshot_MoveInt(s, &r->AddLocation, 4);\n"
      "        ReplaySnapshot_MoveInt(s, &r->NumItemsAdded, 4);",
      "        ReplaySnapshot_MoveInt(s, &r->NumItemsAdded, 4);\n"
      "        ReplaySnapshot_MoveInt(s, &r->AddLocation, 4);"),
    M("rsnap-nadd", "        ReplaySnapshot_MoveInt(s, &r->NumItemsAdded, 4);\n",
      ""),
    M("rsnap-add-chans", "        for (i = 0; i < r->NumChannels; i++) {\n"
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddRepeatCount",
      "        for (i = 1; i < r->NumChannels; i++) {\n"
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddRepeatCount"),
    M("rsnap-add-data",
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddData, 4);\n", ""),
    M("rsnap-add-size",
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddData, 4);",
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddData, 4);\n"
      "            ReplaySnapshot_MoveInt(s, &r->Channel[i].AddDataSize, 4);"),
    M("rsnap-err", "        r->RemoveDataError = 0;\n", ""),
    M("rsnap-rem-loc",
      "        ReplaySnapshot_MoveInt(s, &r->RemoveLocation, 4);\n", ""),
    M("rsnap-rem-count", "            ReplaySnapshot_MoveInt("
      "s, &r->Channel[i].RemoveRepeatCount, 4);\n", ""),
    M("rsnap-rem-data", "            ReplaySnapshot_MoveInt("
      "s, &r->Channel[i].RemoveData, 4);\n", ""),
    M("rsnap-stored", "            ReplaySnapshot_MoveInt("
      "s, &r->Channel[i].RemoveLocation, 4);",
      "            ReplaySnapshot_MoveInt("
      "s, &r->Channel[i].RemoveLocation, 2);"),
    M("rsnap-unnamed", "    ReplaySnapshot_EndNamedSection(s);\n}", "}"),

    # -- the inline overloads
    MH("named-object", "    ReplaySnapshot_BeginSection(s, NULL, name);",
       "    ReplaySnapshot_BeginSection(s, (void *)name, name);"),
    MH("ov-float", "ReplaySnapshot_MoveFloat(ReplaySnapshot *s, float *p)\n"
       "{\n    ReplaySnapshot_MoveData(s, p, 4, -1, 0);",
       "ReplaySnapshot_MoveFloat(ReplaySnapshot *s, float *p)\n"
       "{\n    ReplaySnapshot_MoveData(s, p, 2, -1, 0);"),
    MH("ov-timer", "ReplaySnapshot_MoveTimer(ReplaySnapshot *s, int32_t *p)\n"
       "{\n    ReplaySnapshot_MoveData(s, p, 4, -1, 0);",
       "ReplaySnapshot_MoveTimer(ReplaySnapshot *s, int32_t *p)\n"
       "{\n    ReplaySnapshot_MoveData(s, p, 3, -1, 0);"),
    MH("ov-v2", "    ReplaySnapshot_MoveData(s, p, 8, -1, 0);",
       "    ReplaySnapshot_MoveData(s, p, 12, -1, 0);"),
    MH("ov-v3", "    ReplaySnapshot_MoveData(s, p, 12, -1, 0);",
       "    ReplaySnapshot_MoveData(s, p, 16, -1, 0);"),
    MH("ov-int-sign", "    ReplaySnapshot_MoveData(s, p, stored, 4, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 0);"),
    MH("ov-int-size", "    ReplaySnapshot_MoveData(s, p, stored, 4, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 2, 1);"),
    MH("ov-uint-sign", "int32_t stored)\n{\n"
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 0);\n}\n\n"
       "static inline void ReplaySnapshot_MoveShort",
       "int32_t stored)\n{\n"
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 1);\n}\n\n"
       "static inline void ReplaySnapshot_MoveShort"),
    MH("ov-short-sign", "    ReplaySnapshot_MoveData(s, p, stored, 2, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 2, 0);"),
    MH("ov-short-size", "    ReplaySnapshot_MoveData(s, p, stored, 2, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 1);"),
    MH("ov-ushort-sign", "    ReplaySnapshot_MoveData(s, p, stored, 2, 0);",
       "    ReplaySnapshot_MoveData(s, p, stored, 2, 1);"),
    MH("ov-char-sign", "    ReplaySnapshot_MoveData(s, p, stored, 1, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 1, 0);"),
    MH("ov-uchar-sign", "    ReplaySnapshot_MoveData(s, p, stored, 1, 0);",
       "    ReplaySnapshot_MoveData(s, p, stored, 1, 1);"),
    MH("ov-bool-size", "int32_t stored)\n{\n"
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 0);\n}\n\n"
       "static inline void ReplaySnapshot_VerifyFloat",
       "int32_t stored)\n{\n"
       "    ReplaySnapshot_MoveData(s, p, stored, 1, 0);\n}\n\n"
       "static inline void ReplaySnapshot_VerifyFloat"),
    MH("ov-vfloat", "    ReplaySnapshot_VerifyData(s, p, 4, -1, 0);",
       "    ReplaySnapshot_VerifyData(s, p, 3, -1, 0);"),
    MH("ov-vv2", "    ReplaySnapshot_VerifyData(s, p, 8, -1, 0);",
       "    ReplaySnapshot_VerifyData(s, p, 12, -1, 0);"),
    MH("ov-vv3", "    ReplaySnapshot_VerifyData(s, p, 12, -1, 0);",
       "    ReplaySnapshot_VerifyData(s, p, 8, -1, 0);"),
    MH("ov-vfloat-move", "    ReplaySnapshot_VerifyData(s, p, 4, -1, 0);",
       "    ReplaySnapshot_MoveData(s, p, 4, -1, 0);"),
    MH("ov-vint-move", "    ReplaySnapshot_VerifyData(s, p, stored, 4, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 1);"),
    MH("ov-vuint-move", "    ReplaySnapshot_VerifyData(s, p, stored, 4, 0);",
       "    ReplaySnapshot_MoveData(s, p, stored, 4, 0);"),
    MH("ov-vshort-move", "    ReplaySnapshot_VerifyData(s, p, stored, 2, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 2, 1);"),
    MH("ov-vushort-move", "    ReplaySnapshot_VerifyData(s, p, stored, 2, 0);",
       "    ReplaySnapshot_MoveData(s, p, stored, 2, 0);"),
    MH("ov-vchar-move", "    ReplaySnapshot_VerifyData(s, p, stored, 1, 1);",
       "    ReplaySnapshot_MoveData(s, p, stored, 1, 1);"),

    # -- bRepeat: the bits
    MB("w-bit", "        bit = (bit + 1) & 7;\n        if (bit == 0)\n"
       "            p++;\n    }\n}",
       "        bit = (bit + 1) & 15;\n        if (bit == 0)\n"
       "            p++;\n    }\n}"),
    MB("w-start", "    uint8_t *p = (uint8_t *)r + location / 8;",
       "    uint8_t *p = (uint8_t *)r + location / 8 + 1;"),
    MB("w-keep", "        *p = (uint8_t)((*p & ~(1 << bit))",
       "        *p = (uint8_t)((*p)"),
    MB("w-value", "| (((value >> (i & 31)) & 1) << bit));",
       "| (((value >> (i & 15)) & 1) << bit));"),
    MB("w-msb", "| (((value >> (i & 31)) & 1) << bit));",
       "| (((value >> ((bits - 1 - i) & 31)) & 1) << bit));"),
    MB("r-or", "        v |= (uint32_t)((*p >> bit) & 1) << (i & 31);",
       "        v ^= (uint32_t)((*p >> bit) & 1) << (i & 31);"),
    MB("r-start", "    const uint8_t *p = (const uint8_t *)r + location / 8;\n"
       "    int32_t bit = location & 7;",
       "    const uint8_t *p = (const uint8_t *)r + location / 8;\n"
       "    int32_t bit = location & 3;"),
    MB("r-step", "        bit = (bit + 1) & 7;\n        if (bit == 0)\n"
       "            p++;\n    }\n    return",
       "        bit = (bit + 1) & 7;\n        if (bit == 1)\n"
       "            p++;\n    }\n    return"),

    # -- PrepareToAddData and the channels
    MB("prep-magic", "    r->Magic = BREPEAT_MAGIC;\n", ""),
    MB("prep-cnu", "    r->CodeineNeedsUpdating = 0;\n", ""),
    MB("prep-rem", "    r->RemoveLocation = 0;\n", ""),
    MB("prep-nadd", "    r->NumItemsAdded = 0;\n", ""),
    MB("prep-nrem", "    r->NumItemsRemoved = 0;\n"
       "    r->RemoveDataError = 0;\n    r->HeaderSize",
       "    r->RemoveDataError = 0;\n    r->HeaderSize"),
    MB("prep-err", "    r->RemoveDataError = 0;\n    r->HeaderSize",
       "    r->HeaderSize"),
    MB("prep-header", "    r->HeaderSize = (channels - 1) * 36 + 84;",
       "    r->HeaderSize = (channels - 1) * 36 + 80;"),
    MB("prep-addloc", "    r->AddLocation = r->HeaderSize * 8;",
       "    r->AddLocation = r->HeaderSize * 8 + 4;"),
    MB("prep-nch", "    r->NumChannels = channels;",
       "    r->NumChannels = channels - 1;"),
    MB("prep-codeine", "    r->EnableCodeineCapturing = codeine;",
       "    r->EnableCodeineCapturing = 0;"),
    MB("prep-bufsz", "    r->AddBufferSize = size;",
       "    r->AddBufferSize = size - 8;"),
    MB("prep-clear-from",
       "memset((uint8_t *)r + 48, 0, (size_t)(size - 48));",
       "memset((uint8_t *)r + 52, 0, (size_t)(size - 48));"),
    MB("prep-clear-len",
       "memset((uint8_t *)r + 48, 0, (size_t)(size - 48));",
       "memset((uint8_t *)r + 48, 0, (size_t)(size - 52));"),
    MB("prep-rt", "    r->RecordingTime = 0;\n", ""),
    MB("chan-swap", "    c->RepeatSize = repeat_size;\n"
       "    c->DefaultRemoveData = default_data;",
       "    c->RepeatSize = default_data;\n"
       "    c->DefaultRemoveData = repeat_size;"),

    # -- AddData
    MB("limit-64", "* 8u - 68u", "* 8u - 64u"),
    MB("limit-72", "* 8u - 68u", "* 8u - 72u"),
    MB("add-null", "    if (r == NULL)\n        return 0;\n", ""),
    MB("add-full-le", "    if (!(r->AddLocation < add_limit(r)))\n"
       "        return 0;",
       "    if (!(r->AddLocation <= add_limit(r)))\n        return 0;"),
    MB("add-full-never", "    if (!(r->AddLocation < add_limit(r)))\n"
       "        return 0;", ""),
    MB("add-nadd", "    r->NumItemsAdded++;\n", ""),
    MB("rep-loc", "    if (c->AddLocation != 0 && c->AddDataSize == bits",
       "    if (c->AddDataSize == bits"),
    MB("rep-size", "c->AddLocation != 0 && c->AddDataSize == bits",
       "c->AddLocation != 0"),
    MB("rep-full", "!= (int32_t)((1u << (c->RepeatSize & 31)) - 1u)",
       "!= (int32_t)((1u << (c->RepeatSize & 31)) - 2u)"),
    MB("rep-full-lt", "        && c->AddRepeatCount\n"
       "               != (int32_t)",
       "        && c->AddRepeatCount + 1\n               < (int32_t)"),
    MB("rep-value", "        && c->AddData == value) {", "        ) {"),
    MB("rep-count", "        c->AddRepeatCount++;\n", ""),
    MB("rep-write", "        bRepeat_WriteToLocation(r, c->AddLocation, "
       "c->AddRepeatCount,\n                                c->RepeatSize);\n",
       ""),
    MB("new-chan-bits",
       "bRepeat_WriteToLocation(r, r->AddLocation, channel, 4);",
       "bRepeat_WriteToLocation(r, r->AddLocation, channel, 3);"),
    MB("new-chan-step", "        r->AddLocation += 4;\n        c->AddLocation",
       "        r->AddLocation += 5;\n        c->AddLocation"),
    MB("new-loc", "        c->AddLocation = r->AddLocation;\n"
       "        bRepeat_WriteToLocation(r, r->AddLocation, 0,",
       "        c->AddLocation = r->AddLocation - 4;\n"
       "        bRepeat_WriteToLocation(r, r->AddLocation, 0,"),
    MB("new-count-write", "        bRepeat_WriteToLocation("
       "r, r->AddLocation, 0, c->RepeatSize);\n", ""),
    MB("new-count-zero", "        c->AddRepeatCount = 0;\n"
       "        r->AddLocation += c->RepeatSize;",
       "        r->AddLocation += c->RepeatSize;"),
    MB("new-count-step", "        r->AddLocation += c->RepeatSize;\n"
       "        c->AddData", "        c->AddData"),
    MB("new-data", "        c->AddData = value;\n", ""),
    MB("new-value", "        bRepeat_WriteToLocation("
       "r, r->AddLocation, value, bits);\n", ""),
    MB("new-value-step", "        r->AddLocation += bits;\n", ""),
    MB("new-size", "        c->AddDataSize = bits;\n", ""),
    MB("cnu-always", "    if (r->EnableCodeineCapturing)\n"
       "        r->CodeineNeedsUpdating++;",
       "    r->CodeineNeedsUpdating++;"),
    MB("shovel-always", "    if (!(r->AddLocation < add_limit(r)) "
       "&& r->EnableCodeineCapturing)",
       "    if (!(r->AddLocation < add_limit(r)))"),
    MB("shovel-never", "        bRepeat_ShovelDataOffToCodeine(r);\n"
       "    return 1;", "    return 1;"),
    MB("add-ret", "    return 1;\n}\n\n// 0x001eb498",
       "    return 2;\n}\n\n// 0x001eb498"),

    # -- the shovel
    MB("shovel-chans", "        channel_at(r, i)->AddLocation = 0;\n    left",
       "    left"),
    MB("shovel-left", "    left = r->AddLocation - whole;", "    left = 0;"),
    MB("shovel-whole", "    int32_t whole = r->AddLocation & ~7;",
       "    int32_t whole = r->AddLocation & ~15;"),
    MB("shovel-start", "    r->AddLocation = start + left;",
       "    r->AddLocation = start;"),
    MB("shovel-move", "    if (left != 0)\n        bRepeat_WriteToLocation(",
       "    if (0)\n        bRepeat_WriteToLocation("),

    # -- PrepareToRemoveData and RemoveData
    MB("prem-nrem", "    r->NumItemsRemoved = 0;\n"
       "    r->RemoveLocation = r->HeaderSize * 8;",
       "    r->RemoveLocation = r->HeaderSize * 8;"),
    MB("prem-loc", "    r->RemoveLocation = r->HeaderSize * 8;",
       "    r->RemoveLocation = r->HeaderSize * 8 + 4;"),
    MB("prem-err", "    r->RemoveDataError = 0;\n    for", "    for"),
    MB("prem-rrc", "        channel_at(r, i)->RemoveRepeatCount = 0;\n", ""),
    MB("prem-rl", "        channel_at(r, i)->RemoveLocation = 0;\n    }",
       "    }"),
    MB("rem-loc", "    if (c->RemoveLocation != 0\n"
       "        && c->RemoveRepeatCount", "    if (c->RemoveRepeatCount"),
    MB("rem-le", "        && c->RemoveRepeatCount\n               < bRepeat",
       "        && c->RemoveRepeatCount\n               <= bRepeat"),
    MB("rem-count", "        c->RemoveRepeatCount++;\n", ""),
    MB("rem-repeat-value", "        v = c->RemoveData;",
       "        v = c->DefaultRemoveData;"),
    MB("rem-past-le",
       "    } else if (!(r->NumItemsRemoved < r->NumItemsAdded)) {",
       "    } else if (!(r->NumItemsRemoved <= r->NumItemsAdded)) {"),
    MB("rem-past-never",
       "    } else if (!(r->NumItemsRemoved < r->NumItemsAdded)) {",
       "    } else if (0) {"),
    MB("rem-past-err", "        r->RemoveDataError = 1;\n"
       "        v = c->DefaultRemoveData;\n    } else {",
       "        v = c->DefaultRemoveData;\n    } else {"),
    MB("rem-past-value", "        r->RemoveDataError = 1;\n"
       "        v = c->DefaultRemoveData;\n    } else {",
       "        r->RemoveDataError = 1;\n        v = 0;\n    } else {"),
    MB("rem-chan-bits", "        int32_t ch = bRepeat_ReadFromLocation("
       "r, r->RemoveLocation, 4);",
       "        int32_t ch = bRepeat_ReadFromLocation("
       "r, r->RemoveLocation, 3);"),
    MB("rem-chan-step", "        r->RemoveLocation += 4;\n", ""),
    MB("rem-wrong-ok", "        if (ch != channel) {", "        if (0) {"),
    MB("rem-wrong-err", "            r->RemoveDataError = 1;\n"
       "            v = c->DefaultRemoveData;\n        } else {",
       "            v = c->DefaultRemoveData;\n        } else {"),
    MB("rem-wrong-value", "            r->RemoveDataError = 1;\n"
       "            v = c->DefaultRemoveData;\n        } else {",
       "            r->RemoveDataError = 1;\n            v = ch;\n"
       "        } else {"),
    MB("rem-mark", "            c->RemoveLocation = r->RemoveLocation;\n", ""),
    MB("rem-count-zero", "            c->RemoveRepeatCount = 0;\n", ""),
    MB("rem-count-step", "            r->RemoveLocation += c->RepeatSize;\n",
       ""),
    MB("rem-data", "            c->RemoveData = v;\n", ""),
    MB("rem-value-step", "            r->RemoveLocation += bits;\n", ""),
    MB("rem-nrem", "    r->NumItemsRemoved++;\n    return v;",
       "    return v;"),
]

EQUIVALENT = {
    # A char is one byte: a fill runs only when nothing is stored, and
    # then the last byte is 0 and the fill 0 either way.
    "ov-char-sign",
    "ov-uchar-sign",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = write_script(scdir.name, sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "replay_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, sc)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
