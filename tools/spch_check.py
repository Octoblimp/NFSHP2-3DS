#!/usr/bin/env python3
"""Cross-check the SPCH library (3DS Files/source/spch*.c) against the
retail image, SLES_507.31.

**The model** is retail's SPP2A380.A (0x00290720 .. 0x00295afc) run in
retail_model.RetailEmu: the public SPCH_ calls and most of the iSPCH_
ones, called directly. SPCHDBG_print and SPCHDBG_abortmessage are
replaced by fakes that format their message (a small printf) and print
it; SPCHLOG_*, the debug log that the port drops, and the sprintf that
feeds it are silent. The harness (tools/src/spch_test.c) runs the port,
with its abort and print vectors printing the same way.

**The fakes**, the same on both sides, each printing what it is handed:
the sample request (the request's fields), the rule test (the event
word, the rule, the value and the dat; it answers what the script set
for the rule, 1 by default, and can xor the word), the rule set (the
same, no answer), the event rule (the script's queue, then 1), the
reparm (the parameters; the script's queue can change one and answers,
then -1) and the clock (the script's tick, silent: the log asks it too).

**The data** is synthetic events and banks built here, each shaped to
reach a path the retail data never takes -- the template subbanks, the
cycle bits, the match parameters (254 and 255), the constant rules, the
set rules, the exact-match mask, the follow groups, the append chains,
the filter and its short sentences, the repeat limits, aliases and the
aborts -- and then retail's own EVENTS.EVT and ENGLISHBAN.PCK, with
events added and played on parameters that its phrases accept.

**The dumps** are semantic: the globals, the queue, the choice, the pick
context, the bank table and each bank's cycle bits and repeat queue,
with pointers as blob+offset.

    python tools/spch_check.py
    python tools/spch_check.py --mutate [--only a,b]
    python tools/spch_check.py --dump out/spch
"""
import argparse
import os
import re
import struct
import subprocess
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

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/spch_test.c"
SRCDIR = "3DS Files/source/"
SPCH, BANK, EVNT, PICK, RULE = (SRCDIR + x for x in (
    "spch.c", "spchbank.c", "spchevnt.c", "spchpick.c", "spchrule.c"))
SOURCES = [HARNESS, SPCH, BANK, EVNT, PICK, RULE]
SPCHI = SRCDIR + "spchi.h"
HARNESS_TIMEOUT = 120
LIMIT = 20000000

EVT_FILE = ROOT / "extracted-retail" / "SOUND" / "SPEECH" / "EVENTS.EVT"
PCK_FILE = ROOT / "extracted-retail" / "SOUND" / "SPEECH" / "ENGLISHBAN.PCK"

MAGIC = 0x01789a34

F = {
    "bind": 0x00290720, "adddb": 0x00290858, "resolve": 0x002908a8,
    "extvecs": 0x002908c8, "rate": 0x00290920, "rulecb": 0x002909a0,
    "reparmcb": 0x00290a08, "erulecb": 0x00290a38, "init": 0x00290a68,
    "deinit": 0x00290b48, "bankmemsize": 0x00290bd8, "bankmem": 0x00290be0,
    "bankptr": 0x00290c18, "findbank": 0x00290cc8, "findsub": 0x00290d58,
    "tsbb": 0x00290df8, "freebank": 0x00290e60, "bqadd": 0x00290e90,
    "bqtime": 0x00290f58, "setcyc": 0x00291018, "addbank": 0x002910e8,
    "slot": 0x00291518, "chkl": 0x002916a0, "event": 0x002916d0,
    "eventv": 0x002919d0, "chev": 0x00291dd8, "clearq": 0x00291f08,
    "checkq": 0x00291fc0, "clrev": 0x00291fd8, "clrold": 0x00292188,
    "erulecall": 0x00292328, "playlast": 0x00292358, "play": 0x002923e0,
    "playsp": 0x00292488, "choose": 0x00292490, "choosesp": 0x002925f0,
    "filter": 0x00292610, "datinfo": 0x00292678,
    "matchp": 0x00292738, "getmp": 0x00292750, "clrmp": 0x002927b0,
    "ms": 0x002927c8, "gpb": 0x002928d0, "ccb": 0x00292a08,
    "testbit": 0x00292a70, "ctb": 0x00292aa8, "se": 0x00292b70,
    "csm": 0x00292c38, "convt": 0x00292e08, "slen": 0x00292e70,
    "decw": 0x00292f18, "order": 0x00292f40, "repeat": 0x002930b0,
    "srs": 0x002930f8, "bpid": 0x00293140, "sgc": 0x002931e0,
    "rpp": 0x002933d0, "rsp": 0x00293450, "itc": 0x00293520,
    "css": 0x002935a8, "pps": 0x00293668, "smc": 0x00293950,
    "crs": 0x00293a70, "msr": 0x00293c00, "initspi": 0x00293dd8,
    "initch": 0x00293de8, "save": 0x00293e70, "onech": 0x00293f90,
    "playch": 0x00293fb8, "tvp": 0x00294128, "csent": 0x00294178,
    "cs1": 0x00294570, "preload": 0x00294638, "evlog": 0x00294648,
    "deevlog": 0x002946d8, "saveevlog": 0x002946f0,
    "sue": 0x002950a0, "ruleid": 0x00295138, "rset": 0x002951b8,
    "grs": 0x00295310, "csr": 0x002954f8, "eacr": 0x00295520,
    "seedr": 0x00295610, "findrand": 0x00295680, "addrand": 0x00295728,
    "initrand": 0x00295770, "rand": 0x002957b0, "unpack": 0x002958f0,
    "ifg": 0x00291a50,
}

PRINT, ABORT, SPRINTF = 0x00294f18, 0x00294fa8, 0x00297b40
SPCHLOG = (0x002947a0, 0x00294818, 0x00294880, 0x002948e8, 0x00294980,
           0x00294a18, 0x00294ab0, 0x00294b58, 0x00294bb0, 0x00294c18,
           0x00294d38, 0x00294dd8, 0x00294de0, 0x00294de8, 0x00294df0,
           0x00294df8, 0x00294e00, 0x00294e08, 0x00294ea0)

G = {
    "aes": 0x0032b240, "ps": 0x0032b244, "choice": 0x0032b290,
    "mpid": 0x0032b700, "mpv": 0x0032b704, "init": 0x0032b720,
    "banks": 0x0032b724, "nb": 0x0032b728, "cc": 0x0032b730,
    "cbs": 0x0032b740, "ext": 0x0032b758, "dats": 0x0032b768,
    "queue": 0x0032b7a8, "ingame": 0x0032be10, "game": 0x0032be50,
    "rate": 0x0032be54, "filter": 0x0032be58, "pre": 0x0032be78,
    "lt": 0x0032be7c, "lst": 0x0032be80, "seed": 0x0032be88,
    "ri": 0x0032bea0, "rq": 0x0032bea8,
}
SLOT0 = G["queue"] + 100
SLOT_SIZE = 96
PARTS = G["choice"] + 12
CHOSEN = G["choice"] + 396
CHOSEN_SIZE = 92

FMT = re.compile(r"%(-?[0-9]*)(l?)([dusxc%])")


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def esc(s):
    return s.replace(NL, "\\n")


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.blobs = []                 # (name, base, size)
        self.table = 0
        self.table_n = 0
        self.clk = 0
        self.rt = [1] * 256
        self.rtmod = self.rsmod = 0
        self.er = []
        self.rp = []

        cb = e.alloc(64)
        self.REQ, self.RTEST, self.RSET = cb, cb + 8, cb + 16
        self.ERULE, self.REPARM, self.TICK = cb + 24, cb + 32, cb + 40
        e.stub(self.REQ, self.cb_request)
        e.stub(self.RTEST, self.cb_rule_test)
        e.stub(self.RSET, self.cb_rule_set)
        e.stub(self.ERULE, self.cb_event_rule)
        e.stub(self.REPARM, self.cb_reparm)
        e.stub(self.TICK, lambda em: s32(self.clk))
        e.stub(PRINT, lambda em: self.msg("print", em))
        e.stub(ABORT, lambda em: self.msg("abort", em))
        e.stub(SPRINTF, self.sprintf)
        for a in SPCHLOG:
            e.stub(a, lambda em: 0)

        self.ctx = e.alloc(200)
        self.pair = e.alloc(16)
        self.parms = e.alloc(96)
        self.w = e.alloc(16)
        self.evbuf = e.alloc(96)
        self.rec = e.alloc(64)
        self.order = e.alloc(512)
        self.fb = e.alloc(16)
        self.fd = e.alloc(16)
        self.fl = e.alloc(128)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=512):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def cfmt(self, fmt, regs):
        e = self.e
        out = []
        pos = 0
        k = 0
        for m in FMT.finditer(fmt):
            out.append(fmt[pos:m.start()])
            pos = m.end()
            c = m.group(3)
            if c == "%":
                out.append("%")
                continue
            v = e.reg[regs[k]] & M32 if k < len(regs) else 0
            k += 1
            if c == "d":
                s = str(s32(v))
            elif c == "u":
                s = str(v)
            elif c == "x":
                s = "%x" % v
            elif c == "s":
                s = self.cstr(v)
            else:
                s = chr(v & 0xff)
            w = m.group(1)
            if w:
                s = s.rjust(int(w)) if w[0] != "-" else s.ljust(-int(w))
            out.append(s)
        out.append(fmt[pos:])
        return "".join(out)

    def msg(self, kind, em):
        a = em.reg[4] & M32
        s = self.cfmt(self.cstr(a), (5, 6, 7, 8, 9, 10, 11)) if a else ""
        self.emit("  %s: %s" % (kind, esc(s)))
        return 0

    def sprintf(self, em):
        self.e.mem[em.reg[4] & M32] = 0
        return 0

    # ---- the blobs

    def add_blob(self, name, data):
        e = self.e
        p = e.alloc(len(data) + 64, 64)
        e.mem[p:p + len(data) + 64] = bytes(data) + bytes(64)
        self.blobs.append((name, p, len(data)))

    def blob(self, name):
        for nm, p, n in self.blobs:
            if nm == name:
                return p, n
        raise KeyError(name)

    def at(self, name, off):
        return self.blob(name)[0] + int(off, 0)

    def pname(self, a):
        a &= M32
        if a == 0:
            return "0"
        for nm, p, n in self.blobs:
            if p <= a < p + n:
                return "%s+%x" % (nm, a - p)
        return "?"

    # ---- the fakes

    def cb_request(self, em):
        e = self.e
        r = em.reg[4] & M32
        v = struct.unpack_from("<7i", e.mem, r)
        self.emit("  req bank=%d off=%d size=%d ev=%08x ch=%d sub=%d dat=%d"
                  % (v[0], v[1], v[2], v[3] & M32, v[4], v[5], v[6]))
        return 0

    def cb_rule_test(self, em):
        e = self.e
        p = em.reg[4] & M32
        rule = s32(em.reg[5] & M32)
        v = self.rt[rule & 0xff]
        self.emit("  rtest ev=%08x rule=%d val=%d dat=%d -> %d" % (
            e.u32(p), rule, s32(em.reg[6] & M32), s32(em.reg[7] & M32), v))
        e.put32(p, e.u32(p) ^ self.rtmod)
        return s32(v & M32)

    def cb_rule_set(self, em):
        e = self.e
        p = em.reg[4] & M32
        self.emit("  rset ev=%08x rule=%d val=%d dat=%d" % (
            e.u32(p), s32(em.reg[5] & M32), s32(em.reg[6] & M32),
            s32(em.reg[7] & M32)))
        e.put32(p, e.u32(p) ^ self.rsmod)
        return 0

    def cb_event_rule(self, em):
        v = self.er.pop(0) if self.er else 1
        self.emit("  erule ev=%08x -> %d" % (self.e.u32(em.reg[4] & M32), v))
        return s32(v & M32)

    def cb_reparm(self, em):
        e = self.e
        k = s32(em.reg[4] & M32)
        p = em.reg[5] & M32
        ps = ",".join("%x" % e.u32(p + 4 * i) for i in range(20))
        v = -1
        if self.rp:
            v, idx, val = self.rp.pop(0)
            if idx >= 0:
                e.put32(p + 4 * idx, val)
        self.emit("  reparm k=%d p=%s -> %d" % (k, ps, v))
        return s32(v & M32)

    # ---- the dumps

    def dump_state(self):
        e = self.e
        u = e.u32
        banks = u(G["banks"])
        self.emit("  st init=%d aes=%d ps=%d mp=%d,%d banks=%s nb=%d cc=%d "
                  "game=%d rate=%d pre=%u lt=%u lst=%u" % (
                      u(G["init"]) == MAGIC, s32(u(G["aes"])),
                      s32(u(G["ps"])), s32(u(G["mpid"])), s32(u(G["mpv"])),
                      "0" if banks == 0 else
                      "table" if banks == self.table else "?",
                      s32(u(G["nb"])), s32(u(G["cc"])), s32(u(G["game"])),
                      s32(u(G["rate"])), u(G["pre"]), u(G["lt"]),
                      e.u16(G["lst"])))
        cb = [1 if u(G["cbs"] + 4 * i) else 0 for i in range(5)]
        self.emit("  cb req=%d test=%d set=%d erule=%d reparm=%d tick=%d" % (
            cb[0], cb[1], cb[2], cb[3], cb[4],
            1 if u(G["ext"] + 8) else 0))
        self.emit("  dats" + "".join(
            " %s:%u" % (self.pname(u(G["dats"] + 8 * i)),
                        u(G["dats"] + 8 * i + 4)) for i in range(8)))
        self.emit("  ingame" + "".join(
            " %08x:%d" % (u(G["ingame"] + 8 * i),
                          s32(u(G["ingame"] + 8 * i + 4))) for i in range(8)))
        self.emit("  filter" + "".join(
            " %d" % s32(u(G["filter"] + 4 * i)) for i in range(8)))
        self.emit("  seed" + "".join(
            " %08x" % u(G["seed"] + 4 * i) for i in range(6))
            + " ri=%d" % s32(u(G["ri"])))
        self.emit("  rq" + "".join(
            " %04x:%04x" % (e.u16(G["rq"] + 4 * i), e.u16(G["rq"] + 4 * i + 2))
            for i in range(32)))

    def dump_queue(self):
        e = self.e
        u = e.u32
        q = G["queue"]

        def row(off):
            return ",".join("%d" % s32(u(q + off + 4 * i)) for i in range(8))
        self.emit("  q np=%s la=%s lh=%s bump=%d" % (
            row(0), row(32), row(64), s32(u(q + 96))))
        for i in range(16):
            s = SLOT0 + SLOT_SIZE * i
            self.emit("  slot %d t=%u st=%u a=%d ch=%d app=%d nx=%d ev=%s p=%s"
                      % (i, u(s), e.u16(s + 4), e.mem[s + 6], e.mem[s + 7],
                         s16(e.u16(s + 8)), s16(e.u16(s + 10)),
                         self.pname(u(s + 12)),
                         ",".join("%x" % u(s + 16 + 4 * k)
                                  for k in range(20))))

    def dump_choice(self):
        e = self.e
        u = e.u32
        c = G["choice"]
        self.emit("  ch c=%d n=%d np=%d" % (s32(u(c)), s32(u(c + 4)),
                                           s32(u(c + 8))))
        for i in range(48):
            p = PARTS + 8 * i
            b, s, smp, pad = (s16(e.u16(p)), s16(e.u16(p + 2)),
                              e.u16(p + 4), e.u16(p + 6))
            if b != -1 or s != -1 or smp or pad:
                self.emit("  part %d b=%d s=%d smp=%d pad=%d" % (
                    i, b, s, smp, pad))
        for i in range(8):
            p = CHOSEN + CHOSEN_SIZE * i
            ps = [u(p + 12 + 4 * k) for k in range(20)]
            vals = (u(p), u(p + 4), e.mem[p + 8], e.mem[p + 9],
                    e.mem[p + 10], e.mem[p + 11])
            if not any(vals) and not any(ps):
                continue
            self.emit("  chosen %d ev=%s sent=%s si=%d v=%d b10=%d b11=%d p=%s"
                      % (i, self.pname(vals[0]), self.pname(vals[1]),
                         vals[2], vals[3], vals[4], vals[5],
                         ",".join("%x" % x for x in ps)))

    def dump_ctx(self):
        e = self.e
        c = self.ctx
        es = []
        for i in range(12):
            p = c + 8 * i
            es.append("%d/%d/%d/%d/%d/%d" % (
                s16(e.u16(p)), s16(e.u16(p + 2)), e.mem[p + 4], e.mem[p + 5],
                e.mem[p + 6], e.mem[p + 7]))
        self.emit("  ctx nph=%d np=%d e=%s p=%s" % (
            e.mem[c + 96], e.mem[c + 97], ",".join(es),
            bytes(e.mem[c + 98:c + 198]).hex()))

    def dump_table(self):
        e = self.e
        n = 0
        tot = 0
        for i in range(self.table_n):
            p = e.u32(self.table + 4 * i)
            if p == 0:
                continue
            n += 1
            nm = self.pname(p)
            if nm.startswith("pck+"):
                tot = (tot + (i + 1) * int(nm[4:], 16)) & M32
            else:
                self.emit("  btab %d=%s" % (i, nm))
        self.emit("  btab n=%d pck=%08x" % (n, tot))

    def bank_at(self, h):
        return self.e.u32(self.e.u32(G["banks"]) + 4 * h)

    def dump_bank(self, h):
        e = self.e
        b = self.bank_at(h)
        fl, n, ql = e.mem[b + 4], e.mem[b + 5], e.mem[b + 6]
        c = b + 12 + n * ((fl & 15) + 2) + ((fl & 0x70) >> 3)
        q = c + (((n + 7) >> 3) + 1 if fl & 0x80 else 0)
        cyc = bytes(e.mem[c:c + 1 + ((n + 7) >> 3)]).hex() if fl & 0x80 else ""
        qq = bytes(e.mem[q:q + 1 + ql]).hex() if ql else ""
        self.emit("  bank %d %s cyc=%s q=%s" % (h, self.pname(b), cyc, qq))

    # ---- the ops

    def call(self, name, *args):
        # Retail leaves some locals unset (the dat's ID in the rule sets
        # and the requests); the port's are 0, as retail's read on a
        # zeroed stack.
        sp = self.e.reg[29] & M32
        self.e.mem[sp - 0x1000:sp] = bytes(0x1000)
        # The registers are 64-bit: a 32-bit argument goes in sign-extended.
        return self.e.call(F[name], *[s32(x & M32) for x in args],
                           limit=LIMIT)

    def put_parms(self, a, f, start):
        for i in range(20):
            v = int(f[start + i], 0) if start + i < len(f) else 0
            self.e.put32(a + 4 * i, v & M32)

    def op(self, f):
        e = self.e
        o = f[0]

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def B(k):
            return self.at(f[k], f[k + 1])

        def eq(v):
            self.emit("  = %d" % v)

        if o == "blob":
            self.add_blob(f[1], bytes.fromhex(f[2]))
        elif o == "file":
            self.add_blob(f[1], Path(f[2]).read_bytes())
        elif o == "init":
            # The harness's abort and print vectors are set before each
            # init; retail's are never called (their functions are
            # stubbed), so any address shows whether init clears them.
            v = G["ext"]
            e.put32(v, ABORT)
            e.put32(v + 4, PRINT)
            eq(self.call("init", self.REQ if i(1) else 0, i(2), i(3)))
            self.emit("  vecs abort=%d print=%d" % (e.u32(v) != 0,
                                                    e.u32(v + 4) != 0))
        elif o == "vecs":
            v = self.call("extvecs") & M32
            e.put32(v + 8, self.TICK if i(1) else 0)
        elif o == "rulecb":
            self.call("rulecb", self.RTEST if i(1) else 0,
                      self.RSET if i(2) else 0)
        elif o == "reparmcb":
            self.call("reparmcb", self.REPARM if i(1) else 0)
        elif o == "erulecb":
            self.call("erulecb", self.ERULE if i(1) else 0)
        elif o == "bankmem":
            n = i(1)
            self.table_n = n
            self.table = e.alloc(4 * (n + 1))
            e.mem[self.table:self.table + 4 * (n + 1)] = b"\xa5" * (4 * (n + 1))
            self.emit("  size=%d" % (self.call("bankmemsize", n) // 4))
            self.call("bankmem", n, self.table)
        elif o == "addbank":
            eq(self.call("addbank", B(1)))
        elif o == "pckput":
            p, _n = self.blob(f[1])
            for k in range(i(2)):
                e.put32(self.table + 4 * k, p + e.u32(p + 16 * k + 4))
        elif o == "pckadd":
            p, _n = self.blob(f[1])
            for k in range(i(2), i(2) + i(3)):
                self.emit("  %d = %d" % (k, self.call(
                    "addbank", p + e.u32(p + 16 * k + 4))))
        elif o == "put":
            e.put32(self.table + 4 * i(1), B(2))
        elif o == "freebank":
            self.call("freebank", i(1))
        elif o == "bankptr":
            self.emit("  = %s" % self.pname(self.call("bankptr", i(1))))
        elif o == "adddb":
            eq(self.call("adddb", B(1), i(3)))
        elif o == "resolve":
            eq(self.call("resolve", B(1)))
        elif o == "datinfo":
            e.put32(self.fb, 0)
            e.put32(self.fb + 8, 0)
            self.call("datinfo", B(1), self.fb, self.fb + 8)
            self.emit("  = %u %u" % (e.u32(self.fb), e.u32(self.fb + 8)))
        elif o == "rate":
            eq(self.call("rate", i(1), i(2), i(3)))
        elif o in ("deinit", "deevlog", "saveevlog", "clearq", "initch",
                   "clrmp"):
            self.call(o)
        elif o == "evlog":
            eq(self.call("evlog", 0, 0, 0))
        elif o == "tick":
            self.clk = i(1) & M32
        elif o == "rt":
            self.rt[i(1) & 0xff] = i(2)
        elif o == "rtdef":
            self.rt = [i(1)] * 256
        elif o == "rtmod":
            self.rtmod = i(1) & M32
        elif o == "rsmod":
            self.rsmod = i(1) & M32
        elif o == "er":
            self.er.append(i(1))
        elif o == "rp":
            self.rp.append((i(1), i(2), i(3) & M32))
        elif o == "event":
            self.put_parms(self.evbuf, f, 1)
            eq(self.call("event", self.evbuf))
        elif o == "eventv":
            # Retail takes the varargs past the sixth off the caller's
            # stack, a doubleword each, and leaves the parameters past the
            # count as its own stack has them: zeroed, by call().
            sp = e.reg[29] & M32
            for k in range(9, 22):
                struct.pack_into("<q", e.mem, sp + 8 * (k - 9), s32(i(k) & M32))
            eq(self.call("eventv", *[i(k) for k in range(1, 9)]))
        elif o in ("checkq", "playlast", "play", "choose", "chev", "chkl",
                   "cs1", "onech", "playch", "getmp", "convt"):
            eq(self.call(o, i(1)))
        elif o in ("playsp", "choosesp"):
            eq(self.call(o))
        elif o == "filter":
            self.call("filter", i(1), i(2))
        elif o == "preload":
            self.call("preload", i(1))
        elif o == "slot":
            eq(self.call("slot", i(1), i(2), i(3)))
        elif o in ("clrev", "clrold"):
            self.call(o, i(1))
        elif o == "csent":
            eq(self.call("csent", self.parms))
        elif o == "erulecall":
            eq(self.call("erulecall", self.w))
            self.emit("  w=%08x" % e.u32(self.w))
        elif o == "parms":
            self.put_parms(self.parms, f, 1)
        elif o == "w":
            e.put32(self.w, i(1))
        elif o == "ctx0":
            e.mem[self.ctx:self.ctx + 198] = bytes(198)
        elif o == "ctxe":
            p = self.ctx + 8 * i(1)
            struct.pack_into("<hhBBB", e.mem, p, s16(i(2)), s16(i(3)),
                             i(4) & 0xff, i(5) & 0xff, i(6) & 0xff)
        elif o == "ctxp":
            for k in range(2, len(f)):
                e.mem[self.ctx + 98 + i(1) + k - 2] = i(k) & 0xff
        elif o == "ctxn":
            e.mem[self.ctx + 96] = i(1) & 0xff
            e.mem[self.ctx + 97] = i(2) & 0xff
        elif o == "ctxd":
            self.dump_ctx()
        elif o == "pair":
            struct.pack_into("<hhBBB", e.mem, self.pair, s16(i(1)), s16(i(2)),
                             i(3) & 0xff, i(4) & 0xff, i(5) & 0xff)
        elif o == "ms":
            u = self.call("unpack", self.bank_at(i(1)), i(2), self.rec)
            r = self.call("ms", i(1), self.rec, B(3), self.parms)
            self.emit("  = %d %d" % (u, r))
        elif o == "gpb":
            eq(self.call("gpb", B(1), self.parms, self.pair))
            self.emit("  pair %d %d" % (s16(e.u16(self.pair)),
                                        s16(e.u16(self.pair + 2))))
        elif o in ("ctb", "se"):
            self.emit("  = %u" % (self.call(o, self.pair, self.bank_at(i(1)),
                                            i(2)) & M32))
        elif o == "csm":
            eq(self.call("csm", self.ctx, self.pair, B(1), self.parms))
        elif o == "slen":
            eq(self.call("slen", B(1), self.ctx))
        elif o == "decw":
            eq(self.call("decw", i(1)))
        elif o == "order":
            ev = B(1)
            e.mem[self.order:self.order + 512] = b"\xee" * 512
            self.call("order", ev, self.order)
            self.emit("  =" + "".join(" %d" % e.mem[self.order + k]
                                      for k in range(e.mem[ev + 6])))
        elif o in ("repeat", "srs"):
            eq(self.call(o, B(1), i(3)))
        elif o == "bpid":
            eq(self.call("bpid", i(1), i(2)))
        elif o == "sgc":
            eq(self.call("sgc", self.ctx, B(1), self.parms, i(3), i(4), i(5)))
        elif o == "rpp":
            self.call("rpp", self.ctx + 98 + i(1), i(2))
        elif o == "rsp":
            self.call("rsp", B(1), self.ctx)
        elif o == "itc":
            eq(self.call("itc", B(1), self.ctx))
        elif o == "css":
            eq(self.call("css", B(1), self.ctx, i(3)))
        elif o == "pps":
            eq(self.call("pps", self.ctx, B(1), self.ctx + 8 * i(3)))
        elif o == "smc":
            eq(self.call("smc", self.ctx, B(1), i(3), i(4)))
        elif o == "crs":
            self.call("crs", self.w, B(1), self.at(f[1], f[3]), i(4))
            self.emit("  w=%08x" % e.u32(self.w))
        elif o == "msr":
            eq(self.call("msr", B(1), self.w, i(3)))
        elif o == "initspi":
            self.call("initspi", self.ctx)
        elif o == "save":
            self.call("save", self.ctx, i(1), B(2), self.at(f[2], f[4]), i(5),
                      self.parms)
        elif o == "tvp":
            eq(self.call("tvp", i(1), i(2), i(3)))
        elif o == "matchp":
            self.call("matchp", i(1), i(2))
        elif o in ("sue", "ruleid"):
            eq(self.call(o, B(1), i(3)))
        elif o == "rset":
            self.call("rset", self.w, B(1), i(3), self.parms)
            self.emit("  w=%08x" % e.u32(self.w))
        elif o == "grs":
            e.mem[self.fb] = 0xee
            rs = self.call("grs", self.w, B(1), self.parms, self.fb) & M32
            self.emit("  = %u %u w=%08x" % (rs, e.mem[self.fb], e.u32(self.w)))
        elif o == "csr":
            eq(self.call("csr", i(1), i(2), B(3)))
        elif o == "rand":
            eq(self.call("rand", i(1), i(2)))
        elif o == "eacr":
            self.emit("  = %08x" % (self.call("eacr") & M32))
        elif o == "seedr":
            self.call("seedr", i(1))
        elif o == "seed":
            for k in range(6):
                e.put32(G["seed"] + 4 * k, i(1 + k) & M32)
        elif o == "findrand":
            eq(self.call("findrand", i(1), i(2), i(3)))
        elif o == "addrand":
            self.call("addrand", i(1), i(2))
        elif o == "initrand":
            self.call("initrand", i(1))
        elif o == "unpack":
            r = self.call("unpack", self.bank_at(i(1)), i(2), self.rec)
            v = struct.unpack_from("<3i4B", e.mem, self.rec)
            self.emit("  = %d size=%d off=%d np=%d p=%d,%d,%d,%d" % (
                (r,) + v))
        elif o == "testbit":
            self.emit("  = %u" % (self.call("testbit", B(1), i(3)) & M32))
        elif o == "ccb":
            self.call("ccb", self.bank_at(i(1)), i(2))
        elif o == "setcyc":
            self.call("setcyc", self.bank_at(i(1)))
        elif o == "bqadd":
            self.call("bqadd", self.bank_at(i(1)), i(2))
        elif o == "bqtime":
            eq(self.call("bqtime", self.bank_at(i(1)), i(2)))
        elif o == "findbank":
            eq(self.call("findbank", i(1)))
        elif o == "findsub":
            eq(self.call("findsub", i(1), i(2)))
        elif o == "tsbb":
            eq(self.call("tsbb", i(1), i(2)))
        elif o == "poke":
            k = f[1]
            if k == "ingame":
                e.put32(G["ingame"] + 8 * i(2), i(3) & M32)
                e.put32(G["ingame"] + 8 * i(2) + 4, i(4) & M32)
            elif k == "la":
                e.put32(G["queue"] + 32 + 4 * i(2), i(3) & M32)
            elif k == "lh":
                e.put32(G["queue"] + 64 + 4 * i(2), i(3) & M32)
            elif k == "bump":
                e.put32(G["queue"] + 96, i(2) & M32)
            elif k == "lst":
                struct.pack_into("<H", e.mem, G["lst"], i(2) & 0xffff)
            elif k in G:
                e.put32(G[k], i(2) & M32)
            else:
                self.emit("  unknown poke %s" % k)
        elif o == "pokenext":
            struct.pack_into("<h", e.mem, SLOT0 + SLOT_SIZE * i(1) + 10,
                             s16(i(2)))
        elif o == "ifg":
            n = i(2)
            for k in range(n):
                struct.pack_into("<H", e.mem, self.fl + 2 * k, i(3 + k) & 0xffff)
            e.put32(self.fd, n & M32)
            e.put32(self.fd + 4, self.fl)
            eq(self.call("ifg", i(1), self.fd))
        elif o == "state":
            self.dump_state()
        elif o == "q":
            self.dump_queue()
        elif o == "chd":
            self.dump_choice()
        elif o == "btab":
            self.dump_table()
        elif o == "bank":
            self.dump_bank(i(1))
        elif o == "hexb":
            a = B(1)
            self.emit("  " + bytes(e.mem[a:a + i(3)]).hex())
        else:
            self.emit("  unknown op %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            if line.startswith("blob|"):
                self.emit("> blob|" + line.split("|")[1])
            else:
                self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    m = Model()
    out = m.run(lines)
    return out, m.e


# ================================================================== data

def u16b(v):
    return struct.pack("<H", v & 0xffff)


def pad4(b):
    while len(b) & 3:
        b.append(0)
    return b


def phrase(bank, ptype=0, sparm=0, nrules=0, refs=(0, 0, 0, 0),
           consts=(255, 255, 255, 255), masks=(0, 0, 0, 0), extra=(0, 0, 0)):
    """A phrase: its bank ID, the bank type (0 by ID, 1 by the subbank
    parameter sparm names, 2 by template index), its rules' references
    and masks and its constant rules."""
    b = bytearray(u16b(bank))
    b += bytes([sparm & 0xff, ptype & 0xff, nrules & 0xff]) + bytes(extra)
    b += bytes(r & 0xff for r in refs) + bytes(c & 0xff for c in consts)
    for m in masks:
        b += struct.pack("<I", m & M32)
    return bytes(b)


def sentence(phrases, weight=1, rmask=0, rvals=0, short=0):
    return (weight, rmask, rvals, short, list(phrases))


def event(eid, sentences, rules=(), life=0, pri=10, repeat=0, prob=100,
          flags=0, b11=0, mask=None, follow=None):
    """An event: sentences (from sentence()), rules (id, parm, type), the
    exact-match mask (u32, then a u16 a sentence) for flag 8 and the
    follow group (u16 IDs) for flag 0x10."""
    n6, n7 = len(sentences), len(rules)
    if mask is not None:
        flags |= 8
    if follow is not None:
        flags |= 0x10
    b = bytearray(u16b(eid) + u16b(life) + u16b(pri))
    b += bytes([n6, n7 & 0xff, repeat & 0xff, prob & 0xff, flags, b11])
    soff = len(b)
    b += bytes(2 * n6)
    pad4(b)
    for r in rules:
        b += bytes(x & 0xff for x in r)
    pad4(b)
    if mask is not None:
        b += struct.pack("<I", mask[0] & M32)
        for v in mask[1]:
            b += u16b(v)
        pad4(b)
    if follow is not None:
        b += bytes([len(follow), 0])
        for v in follow:
            b += u16b(v)
        pad4(b)
    for k, (wt, rm, rv, sh, phs) in enumerate(sentences):
        pad4(b)
        so = len(b)
        struct.pack_into("<H", b, soff + 2 * k, so // 4)
        b += bytes([wt & 0xff, rm & 0xff, rv & 0xff,
                    ((len(phs) << 2) | sh) & 0xff])
        po = len(b)
        b += bytes(len(phs))
        pad4(b)
        for j, ph in enumerate(phs):
            b[po + j] = (len(b) - so) // 4
            b += ph
    pad4(b)
    return bytes(b)


def evt(events, a=0, b=0, flen=100, fpri=500, version=0x0803):
    """An event dat: dat IDs a (byte 8) and b (byte 9), the filter's
    length and priority, then the events."""
    d = bytearray(u16b(version))
    d += bytes(6) + bytes([a, b]) + bytes(6)
    d += u16b(len(events)) + bytes(2) + u16b(flen) + u16b(fpri)
    t = len(d)
    d += bytes(2 * len(events))
    pad4(d)
    for k, ev in enumerate(events):
        pad4(d)
        struct.pack_into("<H", d, t + 2 * k, len(d) // 4)
        d += ev
    return bytes(d)


def word(eid, a=0, b=0):
    return (eid & 0xffff) | (b << 16) | (a << 24)


def bank(bid, samples, sub=0, np=2, qlen=0, unit=0, end=None,
         subbanks=0xffff, parm_ids=(), cycle=None, template=b"",
         qinit=None):
    """A bank: samples as (offset in units, parms) or ("alias", target,
    parms); parm_ids as (parm, id); cycle as its length."""
    n = len(samples)
    fl = (np & 15) | ((len(parm_ids) & 7) << 4) | (0x80 if cycle is not None
                                                    else 0)
    if end is None:
        end = 1 + max([s[0] for s in samples if s[0] != "alias"] or [0])
    b = bytearray(u16b(bid) + u16b(sub))
    b += bytes([fl, n, qlen, unit]) + u16b(end) + u16b(subbanks)
    for s in samples:
        if s[0] == "alias":
            b += bytes([0x80, s[1]])
            ps = s[2]
        else:
            b += bytes([(s[0] >> 8) & 0x7f, s[0] & 0xff])
            ps = s[1]
        b += bytes((list(ps) + [0] * np)[:np])
    for p, i in parm_ids:
        b += struct.pack(">H", ((p & 7) << 13) | (i & 0x1fff))
    if cycle is not None:
        b += bytes([cycle]) + bytes((n + 7) >> 3)
    if qlen:
        b += bytes(qinit) if qinit is not None else bytes([0] + [255] * qlen)
    b += bytes(template)
    return bytes(b)


# =============================================================== script

def hexline(name, data):
    return "blob|%s|%s" % (name, data.hex())


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def ev_off(dat, eid):
    for k in range(u16(dat, 16)):
        o = u16(dat, 24 + 2 * k) * 4
        if u16(dat, o) == eid:
            return o
    raise KeyError(eid)


def sent_off(dat, eid, s):
    eo = ev_off(dat, eid)
    return eo + u16(dat, eo + 12 + 2 * s) * 4


def ph_off(dat, eid, s, p):
    so = sent_off(dat, eid, s)
    return so + dat[so + 4 + p] * 4


ALL = 0xffffffff
A1, B1D = 0x21, 0x05                    # dat1's IDs: channel 0
A2, B2D = 0x21, 0x06                    # dat2's: channel 1


def W1(eid):
    return word(eid, A1, B1D)


def W2(eid):
    return word(eid, A2, B2D)


# The banks, in the order they are added: their handles.
BANKS = [
    ("b1", bank(0x7001, [(0, [0, 0]), (3, [1, 0]), (7, [2, 1]),
                         (12, [3, 1])], np=2, qlen=2, end=20)),
    ("b2a", bank(0x7002, [(0, [0]), (5, [1])], sub=0, np=1)),
    ("b2b", bank(0x7002, [(0, [0]), (2, [1]), (9, [2])], sub=1, np=1,
                 qlen=1)),
    ("b3", bank(0x7003, [(0, [0]), (2, [1]), (5, [2]), (9, [3])], np=1,
                qlen=1, unit=1, end=12, subbanks=3,
                template=bytes([0xc3, 0x06]))),
    ("b4", bank(0x7004, [(2 * k, []) for k in range(10)], np=0, cycle=3)),
    ("b4z", bank(0x7005, [(0, []), (1, []), (2, [])], np=0, cycle=0)),
    ("b5", bank(0x7006, [(0, [0, 1]), (4, [1, 2]), (8, [2, 3]),
                         (12, [3, 0]), (16, [1, 1])], np=2, qlen=3)),
    ("b6a", bank(0x7007, [(0, [1]), (3, [2]), (6, [3])], np=1,
                 parm_ids=[(0, 0x1055)])),
    ("b6b", bank(0x7008, [(0, [3]), (2, [2]), (4, [1]), (6, [4]),
                          (8, [2])], np=1, parm_ids=[(0, 0x1055)])),
    ("b6c", bank(0x7009, [(0, [1, 2]), (2, [2, 3])], np=2,
                 parm_ids=[(1, 0x1066), (0, 0x77)])),
    ("b7", bank(0x700a, [(0, [0, 0]), ("alias", 0, [1, 1]), (5, [2, 2]),
                         ("alias", 2, [3, 3]), (9, [0, 1])], np=2,
                end=14)),
    ("b7bad", bank(0x700b, [("alias", 5, [0]), ("alias", 0, [0]),
                            (3, [0])], np=1, end=6)),
    ("b9", bank(0x700c, [(0, [40, 3]), (2, [1, 1]), (4, [32, 0])],
                np=2)),
    ("b6d", bank(0x700d, [(0, [255]), (2, [255])], np=1,
                 parm_ids=[(0, 0x1055)])),
    ("b8", bank(0x700e, [(0, [1, 2, 3, 4, 5]), (3, [6, 7, 8, 9, 10])],
                np=5)),
    ("b10", bank(0x700f, [(k, []) for k in range(120)], np=0)),
    ("bq1", bank(0x7011, [(0, [0])], np=1, qlen=2, qinit=[2, 255, 255])),
    ("bq2", bank(0x7012, [(0, [0])], np=1, qlen=2, qinit=[0, 255, 7])),
    ("b11", bank(0x7010, [(0, [0]), (1, [1])], np=1, qlen=1)),
    ("b12", bank(0x7013, [(0, [1]), (2, [2]), (4, [3])], np=1,
                 parm_ids=[(0, 0x1055)], cycle=2, qlen=2, subbanks=2,
                 template=bytes([0x15]))),
]
H = {}
for _k, (_nm, _b) in enumerate(n for n in BANKS if n[0] not in ("bq1",
                                                                  "bq2")):
    H[_nm] = _k


def P(bid=0x7001, **kw):
    return phrase(bid, **kw)


def S(phs, **kw):
    return sentence(phs, **kw)


def dat1():
    p1 = P()
    rs = (P(0x7006, nrules=2, refs=(1, 2, 0, 7), masks=(ALL, ALL, 0, 0)))
    evs = [
        event(1, [S([p1], weight=1), S([p1, p1], weight=0x23),
                  S([p1], weight=0)], repeat=2),
        event(2, [S([P(0x7002, ptype=1, sparm=1)], weight=2),
                  S([P(0x7002, ptype=1, sparm=25)], weight=1),
                  S([P(0x7002, ptype=1, sparm=20)], weight=0)]),
        event(3, [S([P(0x7003, ptype=2, sparm=2)], weight=2),
                  S([P(0x7001, ptype=2, sparm=2)], weight=1),
                  S([P(0x7001, ptype=3)], weight=1)]),
        event(4, [S([P(0x7004)])]),
        event(5, [S([P(0x7006, nrules=2, refs=(1, 0, 0, 0),
                       masks=(0xf, 0x6, 0, 0))], weight=1),
                  S([P(0x7006, nrules=2, refs=(3, 4, 0, 0),
                       masks=(0xff, 0xff, 0, 0))], weight=0)]),
        event(6, [S([P(0x7007, nrules=1, refs=(254, 0, 0, 0),
                       masks=(ALL, 0, 0, 0)),
                     P(0x7008, nrules=1, refs=(255, 0, 0, 0),
                       masks=(ALL, 0, 0, 0))], weight=1),
                  S([P(0x7009, nrules=2, refs=(0, 255, 0, 0),
                       masks=(ALL, ALL, 0, 0))], weight=0)]),
        event(7, [S([P(0x7009, nrules=2, refs=(0, 255, 0, 0),
                       masks=(ALL, ALL, 0, 0))])]),
        event(8, [S([P(0x7006, nrules=2, refs=(1, 2, 0, 0),
                       masks=(ALL, ALL, 0, 0), consts=(0, 255, 2, 255))],
                    weight=1),
                  S([P(0x7006, nrules=2, refs=(1, 2, 0, 0),
                       masks=(ALL, ALL, 0, 0), consts=(9, 1, 255, 255)),
                     rs], weight=0)],
              rules=[(10, 1, 0), (11, 2, 3), (12, 3, 4), (13, 5, 1),
                     (14, 0, 0), (15, 6, 0), (16, 7, 3)]),
        event(9, [S([p1], weight=1, rmask=0x80, rvals=0x80),
                  S([p1], weight=1, rmask=0x50, rvals=0x40),
                  S([p1], weight=0)],
              rules=[(20, 1, 1), (21, 2, 2), (22, 0, 5), (23, 3, 4),
                     (24, 4, 0)]),
        event(10, [S([p1]), S([p1]), S([p1]), S([p1])],
              mask=(0xc9 | (1 << 30), [3, 1, 0, 0x8002])),
        event(11, [S([p1])], follow=[12, 13], pri=10),
        event(12, [S([p1])], pri=5),
        event(13, [S([p1])], pri=5),
        event(14, [S([p1])], pri=50),
        event(15, [S([p1])], follow=[], pri=10),
        event(16, [S([p1]), S([p1])], mask=(0, [0, 0]), follow=[12],
              rules=[(30, 1, 4)], pri=10),
        event(20, [S([p1])], flags=0x20),
        event(21, [S([p1, p1], short=0), S([p1, p1], short=1),
                   S([p1, p1], short=2), S([p1, p1], short=3)],
              flags=1, pri=100),
        event(22, [S([p1, p1], weight=1), S([P(0x7006), p1], weight=1)],
              flags=1, pri=600),
        event(23, [S([p1])], prob=0),
        event(24, [S([p1])], prob=50),
        event(25, [S([p1])], pri=30),
        event(26, [S([p1])], flags=4, pri=1),
        event(27, [S([p1])], life=5),
        event(28, []),
        event(29, [S([p1] * 13)]),
        event(30, [S([P(0x7001, nrules=5)])]),
        event(31, [S([P(0x700c, nrules=1, masks=(ALL, 0, 0, 0))])]),
        event(32, [S([P(0x7eee)], weight=1), S([p1], weight=0)]),
        event(33, [S([p1])], repeat=1),
        event(34, [S([p1])], pri=100),
        event(35, [S([P(0x700f)])]),
        event(36, [S([p1])], rules=[(40 + k, 1, 1) for k in range(9)]),
        event(38, [S([P(0x700a), P(0x700a)])]),
        event(40, [S([p1, p1, p1, p1, p1], weight=3),
                   S([P(0x7006), P(0x7002, ptype=1, sparm=1),
                      P(0x7003, ptype=2, sparm=2)], weight=2)], pri=20),
        event(41, [S([P(0x700e)])]),
        event(37, [S([p1])], prob=-1),
        event(42, [S([p1])], flags=1, pri=500),
        event(43, [S([P(0x7006, nrules=4, masks=(ALL, ALL, ALL, ALL))])]),
        event(44, [S([p1, P(0x7007, nrules=1, refs=(254, 0, 0, 0),
                            masks=(ALL, 0, 0, 0)),
                      P(0x7008, nrules=1, refs=(255, 0, 0, 0),
                        masks=(ALL, 0, 0, 0))])]),
        event(45, [S([P(0x7009, nrules=2, refs=(0, 254, 0, 0),
                       masks=(ALL, ALL, 0, 0)),
                     P(0x7009, nrules=2, refs=(0, 255, 0, 0),
                       masks=(ALL, ALL, 0, 0))])]),
        event(46, [S([P(0x7009, nrules=2, refs=(254, 255, 0, 0),
                       masks=(ALL, ALL, 0, 0))])]),
        event(47, [S([p1], weight=1, rmask=0x80, rvals=0x80),
                   S([p1], weight=0)], rules=[(50, 0, 4)]),
        event(48, [S([p1])], pri=11),
        event(49, [S([p1])], pri=0),
        event(50, [S([p1])], mask=(0, [0]), follow=[12]),
        event(51, [S([p1])], prob=99, pri=1),
        event(52, [S([P(0x7003, ptype=2, sparm=20),
                      P(0x7006, nrules=1, refs=(20, 0, 0, 0),
                        masks=(ALL, 0, 0, 0))])], rules=[(60, 20, 0)]),
        event(53, [S([P(0x7001, consts=(0, 254, 255, 1))])],
              rules=[(70, 1, 0), (71, 2, 0)]),
        event(54, [S([p1] * 12)]),
        event(55, [S([p1], rmask=0x01, rvals=0)]),
        event(57, [S([P(0x700b)])]),
        event(0x105, [S([P(0x7002, ptype=1, sparm=1)])]),
    ]
    return evt(evs, a=A1, b=B1D, flen=8, fpri=500)


def dat2():
    p1 = P()
    evs = [
        event(1, [S([p1])], pri=100),
        event(2, [S([p1])], life=3, pri=100),
        event(3, [S([p1])], pri=10),
        event(4, [S([p1])], flags=0x20),
        event(5, [S([p1])], flags=0x20, life=2),
        event(6, [S([p1], short=1)]),
    ]
    return evt(evs, a=A2, b=B2D, flen=50, fpri=10)


def retail_parms(evt_b, pck_b):
    """For each retail event, parameters that its phrases accept: 0xff..
    (every bit) for the rules' references, a subbank its bank has for a
    subbank parameter, varied by the event's index."""
    subs = {}
    for k in range(struct.unpack_from("<I", pck_b, 0)[0]):
        o = struct.unpack_from("<I", pck_b, 16 * k + 4)[0]
        subs.setdefault(u16(pck_b, o), []).append(u16(pck_b, o + 2))
    out = []
    for k in range(u16(evt_b, 16)):
        eo = u16(evt_b, 24 + 2 * k) * 4
        p = [ALL] * 20
        p[0] = u16(evt_b, eo)
        for s in range(evt_b[eo + 6]):
            so = eo + u16(evt_b, eo + 12 + 2 * s) * 4
            for j in range(evt_b[so + 3] >> 2):
                po = so + evt_b[so + 4 + j] * 4
                if evt_b[po + 3] == 1 and 0 < evt_b[po + 2] < 20 \
                        and p[evt_b[po + 2]] == ALL:
                    ss = sorted(set(subs.get(u16(evt_b, po), [0])))
                    p[evt_b[po + 2]] = ss[(k + s) % len(ss)]
        out.append(p)
    return out


def script():
    L = []
    a = L.append
    d1, d2 = dat1(), dat2()

    def ln(*f):
        a("|".join(str(x) for x in f))

    def ev(w, *parms):
        ln("event", "0x%08x" % w, *parms)

    def E1(eid, *parms):
        ev(W1(eid), *parms)

    def eo1(eid):
        return ("dat1", "0x%x" % ev_off(d1, eid))

    def so1(eid, s):
        return ("dat1", "0x%x" % sent_off(d1, eid, s))

    def po1(eid, s, p):
        return ("dat1", "0x%x" % ph_off(d1, eid, s, p))

    def parms(*p):
        ln("parms", *p)

    # ---- before SPCH_Init
    a("state")
    ln("rulecb", 1, 1)
    ln("reparmcb", 1)
    ln("erulecb", 1)
    a("state")
    a("deinit")
    a("evlog")
    ln("bankptr", 0)
    ln("findbank", 0x7001)
    ln("findsub", 0x7001, 0)
    ln("tsbb", 0, 0)
    ln("freebank", 0)
    for nm, b in BANKS:
        a(hexline(nm, b))
    ln("addbank", "b1", 0)
    ln("bankmem", 4)
    ln("bankptr", 0)
    ln("addbank", "b11", 0)
    ln("bankptr", 0)
    a("btab")
    for r, bits, mode in ((22050, 16, 0), (22050, 4, 1), (-5, 3, 2),
                          (32000, 4, 2), (7, 1, 0), (-1, 1, 1),
                          (44100, 8, 3), (0x7fffffff, 4, 0)):
        ln("rate", r, bits, mode)
    ln("convt", 1000)
    a("eacr")
    ln("seedr", 0x12345678)
    for _ in range(3):
        a("eacr")
    ln("seed", 7, 0, 0, 0, 0, ALL)
    a("eacr")
    a("eacr")
    ln("seed", 7, 5, 6, 0, 1, ALL)
    a("eacr")
    ln("seed", 9, 5, ALL, 0, 0, ALL)
    a("eacr")
    ln("seed", 9, 0, 3, 4, 0xfffffff0, 0x20)
    a("eacr")
    ln("initrand", 3)
    a("state")
    for k in range(5):
        ln("addrand", k * 3, 7)
    for v, n, key in ((6, 5, 7), (0, 5, 7), (12, 5, 7), (12, 2, 7),
                      (3, 0, 7), (6, 40, 7), (6, 5, 8), (6, 33, 7),
                      (0x10006, 5, 0x10007), (99, 32, 7)):
        ln("findrand", v, n, key)
    for k in range(34):
        ln("addrand", k, 9 if k & 1 else 7)
    a("state")
    for v, n, key in ((33, 32, 9), (32, 40, 7), (2, 16, 7), (1, 32, 9)):
        ln("findrand", v, n, key)
    for k in range(32):
        ln("addrand", k, 5)
    for v, n in ((0, 32), (0, 40), (1, 32), (0, 31), (31, 1)):
        ln("findrand", v, n, 5)
    ln("initrand", 3)
    for rng, key in ((1, 5), (2, 5), (2, 5), (2, 5), (5, 9), (100, -1),
                     (0, 3), (-3, 7), (21, 4), (3, 0x10004)):
        ln("rand", rng, key)
    for _ in range(40):
        ln("rand", 5, 9)
    for _ in range(30):
        ln("rand", 24, 2)
    # Four values a range apart: every try is among the last ten.
    for _ in range(12):
        ln("rand", 0x40000000, 11)
    a("state")

    # ---- SPCH_Init, the banks and the dats
    ln("init", 1, 3, 22050)
    a("state")
    a("evlog")
    ln("vecs", 1)
    ln("rulecb", 1, 1)
    a("state")
    ln("bankmem", 24)
    for nm, _b in BANKS:
        ln("addbank", nm, 0)
    a("btab")
    for k in range(len(H)):
        ln("bank", k)
    a(hexline("dat1", d1))
    a(hexline("dat2", d2))
    a(hexline("datv", evt([event(1, [S([P()])])], a=0x30, b=1,
                          version=0x0702)))
    a(hexline("datdup", evt([event(1, [S([P()])])], a=A1, b=B1D)))
    a(hexline("dat3", evt([event(1, [S([P()])], pri=3)], a=0x22, b=1)))
    a(hexline("dat4", evt([event(2, [S([P()])], pri=3)], a=0x23, b=B1D)))
    ln("adddb", "dat4", 0, 2)
    ln("adddb", "dat1", 0, 0)
    ln("adddb", "dat2", 0, 1)
    ln("adddb", "datv", 0, 2)
    ln("adddb", "datdup", 0, 3)
    ln("adddb", "dat3", 0, 8)
    ln("adddb", "dat3", 0, -1)
    ln("resolve", "dat3", 0)
    ln("datinfo", "dat1", 0)
    ln("datinfo", "dat2", 0)
    ln("convt", 1000)
    ln("convt", -441)
    ln("convt", 0x7fffff)
    a("state")

    # ---- the banks' insides
    for h, n in ((0, 5), (H["b7"], 6), (H["b7bad"], 3), (H["b8"], 2),
                 (H["b3"], 4), (H["b6c"], 2)):
        for k in range(n):
            ln("unpack", h, k)
    for i in (0x7002, 0x17002, 0x7eee, 0x7010, 0x700f):
        ln("findbank", i)
    for i, s in ((0x7002, 1), (0x7002, 0x10001), (0x7002, 5), (0x7002, 0),
                 (0x7001, 0), (0x7001, 1)):
        ln("findsub", i, s)
    for h, v in ((3, 0), (3, 2), (3, 3), (3, -1), (0, 0), (-1, 0),
                 (H["b10"], 0)):
        ln("tsbb", h, v)
    ln("bankptr", 3)
    ln("bankptr", 23)
    for s in range(4):
        ln("bqtime", 0, s)
    for s in (2, 3, 1, 1):
        ln("bqadd", 0, s)
        ln("bank", 0)
        for t in range(4):
            ln("bqtime", 0, t)
    ln("bqadd", 1, 0)
    ln("bqtime", 1, 0)
    ln("put", 20, "bq1", 0)
    ln("bqtime", 20, 1)
    ln("bqadd", 20, 0)
    ln("bank", 20)
    ln("put", 21, "bq2", 0)
    ln("bqtime", 21, 7)
    ln("bqtime", 21, 0)
    for g in (4, 5, 3, 7, 0x7fffffff, -1):
        ln("poke", "game", g)
        ln("setcyc", H["b4"])
        ln("bank", H["b4"])
    ln("setcyc", H["b4z"])
    for k in (0, 9, 7, 8, 3):
        ln("ccb", H["b4"], k)
        ln("bank", H["b4"])
    ln("poke", "game", 3)
    a(hexline("bits", bytes([0xa5, 0x3c, 0x81])))
    for k in (0, 1, 2, 5, 7, 8, 10, 13, 15, 16, 23):
        ln("testbit", "bits", 0, k)
    ln("testbit", "bits", 1, 3)
    ln("bank", H["b12"])
    for sm in (2, 0, 1):
        ln("bqadd", H["b12"], sm)
        ln("bqtime", H["b12"], sm)
        ln("bank", H["b12"])
    for sub in (-1, 0, 1):
        ln("pair", H["b12"], sub, 0, 0, 0)
        for idx in range(3):
            ln("se", H["b12"], idx)
    ln("ccb", H["b12"], 2)
    ln("bank", H["b12"])
    ln("ccb", H["b4"], -7)
    ln("bank", H["b4"])

    # ---- matching and the phrase banks
    parms(0, 0x6, 0, 0xff, 0x2)
    for k in range(5):
        ln("ms", H["b5"], k, *po1(5, 0, 0))
        ln("ms", H["b5"], k, *po1(5, 1, 0))
    for k in range(3):
        ln("ms", H["b9"], k, *po1(31, 0, 0))
    ln("ms", H["b5"], 0, *po1(43, 0, 0))
    ln("ms", 0, 0, *po1(30, 0, 0))
    ln("ms", H["b6d"], 0, *po1(6, 0, 0))
    for p1 in (0, 1, 7, 0x10001):
        parms(0, p1, 2)
        ln("gpb", *po1(2, 0, 0))
        ln("gpb", *po1(2, 1, 0))
        ln("gpb", *po1(2, 2, 0))
    for p2 in (0, 2, 3, -1):
        parms(0, 0, p2)
        ln("gpb", *po1(3, 0, 0))
        ln("gpb", *po1(3, 1, 0))
        ln("gpb", *po1(3, 2, 0))
    ln("gpb", *po1(32, 0, 0))
    # A reference of 20: retail reads the word past the parameters, which
    # the checker leaves 0.
    for k in range(2):
        ln("ms", H["b5"], k, *po1(52, 0, 1))
    ln("gpb", *po1(52, 0, 0))
    for sub, idx in ((0, 0), (0, 1), (0, 2), (1, 2), (1, 3), (2, 0),
                     (2, 1), (2, 2), (3, 0), (-1, 0), (-1, 2), (-1, 3)):
        ln("pair", 3, sub, 0, 0, 0)
        ln("ctb", 3, idx)
        ln("se", 3, idx)
    ln("pair", 4, -1, 0, 0, 0)
    for idx in range(11):
        ln("se", H["b4"], idx)
    ln("se", H["b4"], 11)
    ln("pair", 0, -1, 0, 0, 0)
    ln("se", 0, 4)
    ln("se", 0, 5)

    # ---- choosing samples
    a("ctx0")
    ln("pair", 0, -1, 0, 0, 0)
    parms(0)
    ln("csm", *po1(1, 0, 0))
    a("ctxd")
    ln("pair", H["b5"], -1, 0, 0, 0)
    parms(0, 0x6, 0, 0xff, 0x2)
    ln("csm", *po1(5, 0, 0))
    ln("csm", *po1(5, 1, 0))
    a("ctxd")
    ln("pair", 3, 1, 0, 0, 0)
    ln("csm", *po1(3, 0, 0))
    ln("pair", 3, 2, 0, 0, 0)
    ln("csm", *po1(3, 0, 0))
    a("ctxd")
    ln("bqadd", 0, 0)
    ln("bqadd", 0, 2)
    a("ctx0")
    ln("pair", 0, -1, 0, 0, 0)
    ln("csm", *po1(1, 0, 0))
    a("ctxd")
    ln("pair", H["b10"], -1, 0, 0, 0)
    ln("csm", *po1(35, 0, 0))
    a("ctxd")
    a("ctx0")
    ln("csm", *po1(35, 0, 0))
    a("ctxd")
    a("ctx0")
    ln("pair", H["b7bad"], -1, 0, 0, 0)
    ln("csm", *po1(57, 0, 0))
    a("ctxd")
    ln("pair", 0, -1, 0, 0, 0)
    a("ctx0")
    ln("ctxp", 97, 1, 2, 3)
    ln("ctxn", 0, 98)
    ln("csm", *po1(1, 0, 0))
    a("ctxd")

    # ---- lengths, weights, order
    a("ctx0")
    ln("ctxe", 0, 0, -1, 0, 4, 1)
    ln("ctxe", 1, 0, -1, 4, 2, 5)
    ln("ctxp", 0, 0, 1, 2, 3, 3, 0)
    ln("slen", *so1(1, 0))
    ln("slen", *so1(1, 1))
    for b in (0, 1, 0x1f, 0x20, 0x23, 0x3f, 0x5a, 0xe1, 0xff, 0x123):
        ln("decw", b)
    for eid in (1, 9, 10, 21, 40, 28):
        for _ in range(3):
            ln("order", *eo1(eid))
    ln("poke", "ingame", 0, W1(1), 1)
    ln("repeat", *eo1(1), 0)
    ln("poke", "ingame", 0, W1(1), 2)
    ln("repeat", *eo1(1), 0)
    ln("repeat", *eo1(1), 1)
    ln("repeat", *eo1(2), 0)
    ln("repeat", *eo1(33), 0)
    ln("poke", "ingame", 0, W1(1) | 0xffff0000, 3)
    ln("repeat", *eo1(1), 0)
    ln("poke", "ingame", 0, 0xffff, 0)
    for s in range(4):
        for mode in (0, 1, 2, 3):
            ln("srs", *so1(21, s), mode)
    for h, p in ((H["b6c"], 0), (H["b6c"], 1), (H["b6c"], 2),
                 (H["b6a"], 0), (0, 0), (H["b6c"], -1)):
        ln("bpid", h, p)

    # ---- sentence choices
    parms(W1(1))
    for eid, s, rs, fb, mode in ((1, 0, 0, 0, 0), (1, 1, 0, 0, 0),
                                 (21, 1, 0, 0, 2), (21, 1, 0, 0, 1),
                                 (21, 2, 0, 0, 2), (21, 3, 0, 0, 0),
                                 (9, 0, 0, 0, 0), (9, 0, 0x80, 0, 0),
                                 (9, 0, 0, 0x80, 0), (9, 1, 0x40, 0, 0),
                                 (9, 1, 0x50, 0, 0), (9, 1, 0x50, 0x10, 0),
                                 (9, 1, 0x150, 0x100, 0),
                                 (29, 0, 0, 0, 0), (32, 0, 0, 0, 0),
                                 (40, 0, 0, 0, 0)):
        a("ctx0")
        ln("sgc", *so1(eid, s), rs, fb, mode)
        a("ctxd")
    parms(W1(40), 1, 2)
    a("ctx0")
    ln("sgc", *so1(40, 1), 0, 0, 0)
    a("ctxd")
    for c in range(3):
        ln("rsp", *so1(40, 1))
        a("ctxd")
    a("ctx0")
    ln("sgc", *so1(40, 0), 0, 0, 0)
    a("ctxd")
    ln("rsp", *so1(40, 0))
    a("ctxd")
    ln("ctxp", 0, 10, 11, 12, 13, 14, 15, 16)
    for st, n in ((0, 7), (2, 5), (0, 1), (0, 0), (1, 2)):
        ln("rpp", st, n)
        a("ctxd")
    a("ctx0")
    ln("ctxe", 0, 0, -1, 0, 2, 0)
    ln("ctxe", 1, 0, -1, 2, 3, 2)
    for _ in range(7):
        ln("itc", *so1(1, 1))
        a("ctxd")
    ln("itc", *so1(1, 0))
    a("ctxd")

    # ---- short sentences and the picks
    a("ctx0")
    ln("ctxe", 0, 0, -1, 0, 4, 3)
    ln("ctxe", 1, 0, -1, 4, 4, 7)
    ln("ctxp", 0, 3, 2, 1, 0, 3, 2, 1, 0)
    for mx in (100, 18, 17, 14, 7, 6, 0):
        ln("css", *so1(1, 1), mx)
        a("ctxd")
    a("ctx0")
    ln("ctxe", 0, H["b6a"], -1, 0, 3, 0)
    ln("ctxe", 1, H["b6b"], -1, 3, 5, 3)
    ln("ctxp", 0, 0, 1, 2, 0, 1, 2, 3, 4)
    for _ in range(6):
        ln("pps", *po1(6, 0, 0), 0)
        a("state")
        ln("pps", *po1(6, 0, 1), 1)
        a("ctxd")
    ln("matchp", 0x55, 0)
    ln("pps", *po1(6, 0, 1), 1)
    ln("matchp", 0x54, 4)
    ln("pps", *po1(6, 0, 1), 1)
    ln("ctxe", 1, H["b6b"], -1, 3, 0, 3)
    ln("pps", *po1(6, 0, 1), 1)
    ln("ctxe", 1, H["b6b"], -1, 3, 101, 3)
    ln("pps", *po1(6, 0, 1), 1)
    a("ctxd")
    ln("ctxe", 2, H["b6c"], -1, 0, 2, 0)
    ln("pps", *po1(7, 0, 0), 2)
    ln("ctxe", 3, H["b6d"], -1, 0, 2, 0)
    ln("pps", *po1(6, 0, 0), 3)
    a("state")
    ln("ctxe", 4, 0, -1, 0, 3, 0)
    for _ in range(3):
        ln("pps", *po1(1, 0, 0), 4)
    a("ctxd")
    ln("ctxp", 0, *[k % 5 for k in range(50)])
    ln("ctxp", 50, *[k % 5 for k in range(50, 100)])
    ln("ctxe", 1, H["b6b"], -1, 0, 100, 0)
    ln("pps", *po1(6, 0, 1), 1)
    a("ctxd")
    a("ctx0")
    ln("ctxe", 0, 0, -1, 0, 2, 0)
    ln("ctxe", 1, H["b6a"], -1, 2, 3, 2)
    ln("ctxe", 2, H["b6b"], -1, 5, 5, 5)
    ln("ctxp", 0, 1, 0, 2, 1, 0, 4, 3, 2, 1, 0)
    for _ in range(3):
        ln("pps", *po1(44, 0, 1), 1)
        ln("pps", *po1(44, 0, 2), 2)
        a("ctxd")
        a("state")
    ln("ctxe", 3, H["b6c"], -1, 0, 2, 0)
    ln("ctxe", 4, H["b6c"], -1, 0, 2, 1)
    for _ in range(2):
        ln("pps", *po1(45, 0, 0), 3)
        ln("pps", *po1(45, 0, 1), 4)
        a("ctxd")
        a("state")
    ln("pps", *po1(46, 0, 0), 3)
    a("state")
    a("ctx0")
    ln("ctxe", 0, H["b6a"], -1, 0, 3, 0)
    ln("ctxe", 1, H["b6b"], -1, 3, 4, 3)
    ln("ctxp", 0, 0, 1, 2, 0, 1, 2, 3)
    for mode, mx in ((0, 0), (0, 0), (2, 5), (1, 100), (1, 4), (1, 0)):
        ln("smc", *so1(6, 0), mode, mx)
        a("ctxd")
    ln("ctxe", 1, H["b6b"], -1, 3, 0, 3)
    ln("smc", *so1(6, 0), 0, 0)
    ln("ctxe", 0, H["b6c"], -1, 0, 2, 0)
    ln("smc", *so1(7, 0), 0, 0)

    # ---- the choice, its rules and its requests
    a("initch")
    a("chd")
    a("ctx0")
    ln("ctxe", 0, H["b5"], -1, 0, 2, 1)
    ln("ctxe", 1, H["b5"], -1, 2, 2, 2)
    ln("ctxp", 0, 1, 3, 4, 0)
    parms(W1(8), 0x7, 0xe, 0, 0, 0x30)
    ln("save", 0, *eo1(8)[0:2], so1(8, 0)[1], 0)
    a("chd")
    ln("save", 0, *eo1(8)[0:2], so1(8, 1)[1], 1)
    a("chd")
    ln("save", 1, *eo1(8)[0:2], so1(8, 0)[1], 0)
    ln("onech", 0)
    ln("onech", 1)
    ln("w", W1(8))
    ln("crs", *eo1(8), so1(8, 0)[1], 0)
    ln("crs", *eo1(8), so1(8, 1)[1], 1)
    ln("rsmod", 0x00010000)
    ln("crs", *eo1(8), so1(8, 1)[1], 1)
    ln("rsmod", 0)
    ln("w", W1(8))
    ln("msr", *so1(8, 0), 0)
    ln("msr", *so1(8, 1), 1)
    ln("bank", H["b5"])
    ln("w", 0x55667788)
    ln("msr", *so1(8, 0), 0)
    for si in (0, 1):
        ln("w", W1(8))
        ln("rset", *eo1(8), si)
    ln("w", 0x12345678)
    ln("rset", *eo1(8), 0)
    ln("playch", 1)
    a("chd")
    ln("save", 0, *eo1(8)[0:2], so1(8, 0)[1], 0)
    ln("playch", 0)
    a("chd")
    a("state")
    for k in range(9):
        ln("save", 2, *eo1(1)[0:2], so1(1, 1)[1], 1)
    a("chd")
    ln("playch", 2)
    a("ctx0")
    ln("ctxn", 13, 0)
    ln("save", 2, *eo1(29)[0:2], so1(29, 0)[1], 0)
    a("chd")
    ln("playch", 3)
    a("chd")
    a("initch")
    for k in range(4):
        ln("save", 3, *eo1(54)[0:2], so1(54, 0)[1], 0)
    a("chd")
    a("initch")
    ln("onech", -1)
    a("initspi")
    a("ctxd")
    for mask, v, i in ((1, 0, 0), (1, 5, 0), (2, -1, 0), (2, 0, 0),
                       (3, 1, 0), (0, 1, 0), (4, 1, 1), (8, -1, 1),
                       (8, 3, 1), (1 << 30, 1, 15), (1 << 31, 7, 15),
                       (1, -1, 0), (2, -5, 0), (2, 0x7fffffff, 0),
                       (1, 1, 16), (4, 1, 17)):
        ln("tvp", mask, v, i)
    ln("matchp", 5, 9)
    ln("getmp", 5)
    ln("getmp", 6)
    a("clrmp")
    ln("getmp", -1)
    a("state")
    for p in (0, 1, 2, 3, 7, 25):
        ln("sue", *so1(8, 0), p)
        ln("sue", *so1(8, 1), p)
        ln("sue", *so1(2, 1), p)
    for i in (0, 4, 7, 8, -1):
        ln("ruleid", *eo1(8), i)

    # ---- the event's rules
    parms(W1(9), 0, 5, 0, 7)
    for setup in ([], [("rt", 20, 0)], [("rt", 21, -1)], [("rt", 22, 3)],
                  [("rt", 24, -5)], [("rtmod", 0x01000000)],
                  [("rtmod", 0), ("rtdef", 0)], [("rtdef", -1)]):
        for s in setup:
            ln(*s)
        ln("w", W1(9))
        ln("grs", *eo1(9))
    ln("rtdef", 1)
    parms(W1(9), 9, 0, 3, 0)
    ln("grs", *eo1(9))
    parms(W1(36), 1)
    ln("w", W1(36))
    ln("grs", *eo1(36))
    ln("rt", 40, 0)
    ln("grs", *eo1(36))
    ln("rt", 40, 1)
    ln("w", W1(1))
    ln("grs", *eo1(1))
    parms(W1(47))
    ln("w", W1(47))
    ln("grs", *eo1(47))
    for a_, b_ in ((0, 0), (0x80, 0), (0, 0x80), (0x40, 0), (0x50, 0),
                   (0x40, 0x10), (0x140, 0x100), (0xc0, 0x40)):
        ln("csr", a_, b_, *so1(9, 0))
        ln("csr", a_, b_, *so1(9, 1))
    ln("rulecb", 0, 0)
    ln("w", W1(9))
    ln("grs", *eo1(9))
    ln("rset", *eo1(8), 0)
    ln("crs", *eo1(8), so1(8, 0)[1], 0)
    ln("rulecb", 1, 1)
    parms(W1(52))
    ln("w", W1(52))
    ln("rset", *eo1(52), 0)

    # ---- the queue: adding events
    ln("tick", 100)
    a("q")
    E1(1)
    E1(1, 5, 6, 7)
    ln("eventv", W1(2), 3, 1, 2, 3, 4, 5, 6)
    ln("eventv", W1(3), 0)
    ln("eventv", W1(4), 6, -1, -2, -3, -4, -5, -6)
    ev(word(1, 0x77, 0x77))
    E1(99)
    E1(0x105)
    ln("eventv", W1(2), 19, *range(1, 20))
    a("q")
    a("state")
    ln("checkq", 0)
    ln("checkq", 1)
    ln("chkl", 0)
    ln("chkl", 1)
    for k, v in (("la", -1), ("la", 16), ("lh", -1), ("lh", 16)):
        ln("poke", "la", 0, 0)
        ln("poke", "lh", 0, 0)
        ln("poke", k, 0, v)
        ln("chkl", 0)
    ln("poke", "la", 0, -1)
    ln("poke", "lh", 0, -1)
    ln("poke", "aes", 1)
    E1(1)
    a("state")
    ln("poke", "ps", 1)
    ln("play", 0)
    a("state")
    a("clearq")
    a("q")
    a("state")

    # ---- choosing and playing
    ln("tick", 200)
    for k in range(4):
        E1(1)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
        a("state")
    a("q")
    ln("bank", 0)
    for p1 in (0, 1, 7, 1, 0x10001):
        E1(2, p1)
        ln("play", 0)
    ln("bank", H["b2b"])
    for p2 in (0, 1, 2, 3, 2, 1):
        E1(3, 0, p2)
        ln("play", 0)
    ln("bank", H["b3"])
    for k in range(6):
        E1(4)
        ln("play", 0)
        ln("bank", H["b4"])
    ln("poke", "cc", 0)
    ln("poke", "game", 1)
    ln("setcyc", H["b4"])
    for k in range(3):
        E1(4)
        ln("play", 0)
    ln("bank", H["b4"])
    ln("poke", "cc", 1)
    for p in ((0x6, 0, 0, 0), (0x2, 0, 0, 0), (0x1, 0, 0xff, 0xff),
              (0, 0, 0x1, 0x2), (0, 0, 0, 0), (0xf, 0, 0x8, 0x1)):
        E1(5, *p)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
    ln("bank", H["b5"])
    for k in range(5):
        E1(6)
        ln("play", 0)
        a("state")
    E1(7)
    ln("play", 0)
    for p in ((0x7, 0xe, 0, 0, 0x30), (0x2, 0x8, 1, 0, 0),
              (0x10, 0x10, 0, 0, 0)):
        E1(8, *p)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
    ln("rsmod", 0x00000002)
    E1(8, 0x7, 0xe)
    ln("play", 0)
    ln("rsmod", 0)
    for p, setup in (((0, 5, 0, 7), []), ((3, 5, 0, 7), []),
                     ((3, 5, 1, 7), []), ((3, 5, 1, 7), [("rt", 20, 0)]),
                     ((3, 5, 1, 7), [("rt", 21, 0)]),
                     ((3, 5, 0, 7), [("rt", 21, -1)]),
                     ((3, 5, 0, 7), [("rtdef", 0)]),
                     ((3, 5, 0, 7), [("rtdef", -1)]),
                     ((3, 5, 0, 7), [("rtdef", 1), ("rtmod", 0x00000001)])):
        for s in setup:
            ln(*s)
        E1(9, *p)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
    ln("rtmod", 0)
    ln("rtdef", 1)
    for p in ((1, 0), (0, 0), (1, -1), (0, -1), (5, 3), (0, 3)):
        E1(10, *p)
        ln("play", 0)
    E1(10, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1)
    ln("play", 0)
    E1(10, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1)
    ln("play", 0)
    E1(36, 1)
    ln("play", 0)
    for eid in (43, 44, 44, 44, 45, 45, 46):
        E1(eid)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
        a("state")
    a("clearq")
    E1(44)
    ln("choose", 0)
    ln("w", W1(53))
    for ps in (0, 1, 2):
        ln("crs", *eo1(53), so1(53, 0)[1], ps)
    ln("play", 0)
    E1(55)
    ln("choose", 0)
    a("chd")
    ln("play", 0)
    ln("filter", 0, 0)
    ln("filter", 2, 1)
    ev(W2(6))
    ln("choose", 1)
    a("chd")
    ln("play", 1)
    ln("filter", 0, 1)
    ev(W2(6))
    ln("play", 1)
    a("clearq")
    E1(1)
    ln("play", 0)
    ev(word(1, 0x22, 1))
    ln("play", 0)
    a("state")
    ev(word(2, 0x23, B1D))
    ln("play", 2)
    a("state")
    E1(38)
    ln("play", 0)
    ln("bank", H["b7"])
    E1(41)
    ln("play", 0)
    for k in range(4):
        E1(40, 1, 2)
        ln("choose", 0)
        a("chd")
        ln("play", 0)
    ln("bank", 0)
    a("state")

    # ---- the follow groups
    ln("tick", 300)
    E1(11)
    ln("play", 0)
    E1(14)
    E1(12)
    a("q")
    ln("chev", 0)
    ln("play", 0)
    E1(14)
    ln("chev", 0)
    ln("play", 0)
    E1(11)
    ln("play", 0)
    E1(14)
    ln("chev", 0)
    ln("play", 0)
    E1(15)
    ln("play", 0)
    E1(14)
    E1(13)
    ln("chev", 0)
    ln("play", 0)
    ln("play", 0)
    E1(16, 1)
    ln("play", 0)
    E1(14)
    E1(13)
    E1(12)
    ln("tick", 301)
    E1(13)
    a("q")
    ln("chev", 0)
    ln("play", 0)
    ln("play", 0)
    a("clearq")

    # ---- appends
    ln("tick", 400)
    E1(20)
    E1(1)
    E1(20)
    E1(20)
    a("q")
    ln("choose", 0)
    a("chd")
    ln("play", 0)
    a("q")
    E1(1)
    E1(20)
    E1(20)
    ln("play", 0)
    E1(1)
    E1(20)
    E1(25)
    E1(20)
    a("q")
    ln("clrev", 3)
    a("q")
    ln("clrev", 0)
    a("q")
    ln("clrev", 0)
    a("q")
    ln("clrev", 16)
    ln("clrev", -1)
    ln("clrev", 1)
    a("clearq")
    a("q")
    E1(1)
    E1(25)
    ln("clrev", 0)
    ln("clrev", 0)
    a("q")
    ln("play", 0)
    a("clearq")
    E1(2, 7)
    E1(20, 7)
    ln("choose", 0)
    a("chd")
    a("clearq")
    a("q")
    a("state")

    # ---- the filter, bumps, the stay flag and old events
    ln("tick", 500)
    for f, ch in ((1, 0), (2, 0), (0, 0)):
        ln("filter", f, ch)
        for k in range(3):
            E1(21)
            ln("choose", 0)
            a("chd")
            ln("play", 0)
            E1(22)
            ln("choose", 0)
            a("chd")
            ln("play", 0)
    ln("filter", 1, 0)
    E1(21)
    E1(1)
    ln("chev", 0)
    ln("play", 0)
    a("q")
    a("clearq")
    ln("filter", 0, 0)
    E1(25)
    E1(1)
    E1(26)
    ln("tick", 501)
    E1(1)
    a("q")
    ln("clrold", 0)
    a("q")
    ln("clrold", 3)
    a("q")
    a("state")
    a("clearq")
    E1(26)
    E1(1)
    E1(34)
    E1(1)
    a("q")
    ln("chev", 0)
    ln("play", 0)
    a("q")
    a("state")
    a("clearq")
    for f, eid in ((0, 22), (1, 34), (1, 22), (2, 22), (2, 34), (2, 21),
                   (2, 21), (0, 34), (0, 34)):
        ln("filter", f, 0)
        E1(eid)
        E1(1)
        ln("choose", 0)
        a("chd")
        a("q")
        ln("play", 0)
        a("clearq")
    ln("filter", 0, 0)
    ln("poke", "bump", 0)

    # ---- probabilities, lifetimes, preload
    ln("tick", 600)
    for k in range(100):
        E1(23)
        E1(24)
        if k % 8 == 7:
            a("clearq")
    for k in range(3):
        E1(37)
    a("q")
    a("clearq")
    ln("filter", 1, 0)
    E1(42)
    E1(21)
    ln("chev", 0)
    ln("play", 0)
    a("clearq")
    ln("filter", 0, 0)
    E1(12)
    E1(13)
    ln("clrev", 0)
    ln("tick", 650)
    E1(12)
    a("q")
    ln("chev", 0)
    ln("play", 0)
    a("clearq")
    ln("tick", 700)
    E1(27)
    E1(1)
    ln("tick", 704)
    ln("chev", 0)
    ln("tick", 705)
    ln("chev", 0)
    a("q")
    ln("tick", 706)
    a("q")
    ln("chev", 0)
    a("q")
    ln("play", 0)
    E1(27)
    ln("preload", 10)
    ln("chev", 0)
    a("q")
    ln("preload", 0)
    a("state")
    a("clearq")

    # ---- the event rule, the reparm, play last
    ln("erulecb", 1)
    ln("er", 0)
    ln("er", 1)
    E1(1)
    E1(34)
    ln("play", 0)
    a("q")
    ln("er", 0)
    ln("er", 5)
    E1(1)
    ln("play", 0)
    ln("w", W1(1))
    ln("er", 3)
    a("erulecall")
    E1(1)
    ln("play", 0)
    a("q")
    ln("erulecb", 0)
    a("erulecall")
    a("clearq")
    ln("reparmcb", 1)
    E1(1)
    ln("play", 0)
    E1(2, 7)
    ln("play", 0)
    ln("rp", 0, 1, 7)
    E1(2, 7)
    ln("play", 0)
    ln("rp", 1, 1, 1)
    E1(2, 7)
    ln("play", 0)
    ln("rp", 2, 1, 9)
    ln("rp", 0, 1, 0)
    E1(2, 7)
    ln("play", 0)
    ln("rp", 1, 1, 7)
    ln("rp", 1, -1, 0)
    ln("rp", 3, 1, 1)
    E1(2, 7)
    ln("play", 0)
    ln("rp", 0, 2, 0)
    E1(3, 0, 5)
    ln("play", 0)
    E1(28)
    ln("play", 0)
    ln("reparmcb", 0)
    E1(28)
    a("q")
    ln("cs1", 0)
    ln("cs1", 1)
    a("chd")
    a("clearq")
    ln("playlast", 0)
    E1(1)
    ln("playlast", 0)
    E1(2, 7)
    ln("playlast", 0)
    E1(1)
    E1(2, 7)
    ln("playlast", 0)
    a("q")
    a("clearq")
    E1(28)
    E1(1)
    ln("playlast", 0)
    a("q")
    a("state")
    ln("playsp")
    E1(1)
    ln("choosesp")
    a("chd")
    ln("playsp")
    E1(1)
    ln("play", 1)
    ln("choose", 1)
    a("clearq")
    parms(W1(1))
    ln("csent")
    a("chd")
    ln("csent")
    a("chd")
    a("initch")
    parms(W1(28))
    ln("csent")
    parms(word(1, 0x77, 0x77))
    ln("csent")
    parms(W1(99))
    ln("csent")
    parms(W1(10), 1, 0)
    ln("csent")
    a("initch")
    parms(W1(1))
    ln("poke", "ingame", 0, W1(1), 2)
    ln("csent")
    ln("poke", "ingame", 0, 0xffff, 0)

    # ---- the aborts in the sentences
    for eid in (29, 30, 31, 35, 32):
        E1(eid)
        ln("play", 0)
    a("state")

    # ---- the queue full
    a("clearq")
    ln("tick", 800)
    for k in range(16):
        ev(W2(1))
    a("q")
    ev(W2(1))
    E1(1)
    ln("slot", 10, 0, 0)
    ln("slot", 100, 1, 0)
    ln("slot", 99, 1, 0)
    ln("slot", 100, 1, 1)
    a("q")
    a("clearq")
    for k in range(15):
        E1(34)
    ev(W2(3))
    ev(W2(4))
    a("q")
    a("state")
    a("clearq")
    for k in range(14):
        E1(34)
    ev(W2(3))
    ev(W2(3))
    ev(W2(4))
    a("q")
    a("clearq")
    for k in range(16):
        E1(12)
    ev(W2(1))
    a("q")
    a("clearq")
    ev(W2(4))
    ev(W2(2))
    for k in range(15):
        E1(34)
    ln("tick", 803)
    ev(W2(1))
    a("q")
    a("clearq")
    ln("tick", 800)
    ev(W2(2))
    for k in range(15):
        E1(34)
    ln("tick", 804)
    ev(W2(1))
    a("q")
    ln("tick", 900)
    ln("slot", 0, 3, 0)
    a("q")
    ln("play", 1)
    ln("play", 0)
    a("q")
    a("clearq")
    ln("vecs", 0)
    E1(1)
    ln("play", 0)
    ln("vecs", 1)
    a("state")

    # ---- the event search's ties, the full queue's lives and appends
    a("clearq")
    ln("filter", 0, 0)
    ln("filter", 0, 1)
    ln("tick", 1000)
    ev(W2(1))
    E1(1, 1)
    ln("choose", 0)
    a("q")
    a("chd")
    ln("play", 0)
    a("clearq")
    ln("tick", 1010)
    E1(49)
    ln("tick", 1015)
    ln("chev", 0)
    ln("tick", 1009)
    ln("chev", 0)
    a("clearq")
    ln("tick", 1020)
    E1(14)
    E1(1, 1)
    ln("play", 0)
    E1(1, 2)
    a("q")
    ln("chev", 0)
    ln("choose", 0)
    a("q")
    ln("play", 0)
    a("clearq")
    ln("tick", 1030)
    E1(26, 1)
    ln("tick", 1031)
    E1(1)
    ln("tick", 1033)
    E1(26, 3)
    ln("play", 0)
    ln("tick", 1035)
    E1(26, 2)
    ln("tick", 1040)
    ln("chev", 0)
    a("clearq")
    ln("tick", 1050)
    E1(1)
    ln("tick", 1051)
    E1(51)
    ln("choose", 0)
    a("q")
    ln("play", 0)
    a("clearq")
    E1(1)
    ln("choose", 0)
    E1(14)
    ln("choose", 0)
    a("chd")
    ln("play", 0)
    a("clearq")
    ln("tick", 1070)
    E1(50)
    ln("play", 0)
    E1(14)
    E1(12)
    ln("chev", 0)
    a("clearq")
    ln("tick", 1100)
    for k in range(13):
        ev(W2(1))
    E1(25)
    E1(14)
    E1(20)
    a("q")
    E1(20)
    a("q")
    E1(20)
    a("q")
    a("state")
    a("clearq")
    ln("tick", 1200)
    for k in range(15):
        E1(42)
    ev(W2(2))
    ln("tick", 1210)
    ev(W2(4))
    a("q")
    a("clearq")
    ln("tick", 1300)
    ev(W2(1))
    ev(W2(5))
    ev(W2(2))
    for k in range(13):
        E1(42)
    ln("tick", 1303)
    ev(word(2, 0x23, B1D))
    a("q")
    ln("tick", 1304)
    ev(word(2, 0x23, B1D))
    a("q")
    a("clearq")
    ln("tick", 1400)
    for k in range(15):
        ev(W2(1))
    E1(48)
    E1(1)
    a("q")
    a("clearq")
    E1(14)
    E1(1)
    ln("pokenext", 0, 1)
    ln("clrev", 0)
    a("q")
    ln("pokenext", 0, -1)
    a("clearq")
    for eid, lst in ((0x1000c, (12, 13)), (13, (12, 13)), (0xd00, (12, 13)),
                     (12, (12,)), (5, (12, 13))):
        ln("ifg", eid, len(lst), *lst)

    # ---- deinit, a second init
    E1(1)
    ln("choose", 0)
    E1(3)
    E1(4)
    ln("preload", 5)
    ln("filter", 2, 0)
    ln("filter", 3, 7)
    ln("poke", "bump", 1)
    ln("poke", "lt", 77)
    ln("poke", "lst", 3)
    a("deinit")
    a("state")
    a("deinit")
    ln("addbank", "b1", 0)
    E1(1)
    ln("init", 0, 7, 0)
    a("state")
    a("q")
    a("chd")
    ln("vecs", 1)
    a("state")
    ln("bankptr", 0)
    ln("bankmem", 2)
    ln("addbank", "b1", 0)
    ln("addbank", "b11", 0)
    ln("addbank", "b2a", 0)
    a("btab")
    ln("freebank", 0)
    ln("bankptr", 0)
    ln("addbank", "b2a", 0)
    a("btab")
    for k in range(9):
        nm = "datx%d" % k
        a(hexline(nm, evt([event(1, [S([P(0x7002, ptype=1, sparm=1)])])],
                          a=0x40, b=k)))
        ln("adddb", nm, 0, k & 7)
    a("state")
    ln("convt", 5)
    ev(word(1, 0x40, 3), 0)
    ln("play", 3)
    ln("rate", 1000, 8, 0)
    ev(word(1, 0x40, 3), 0)
    ln("choose", 3)
    a("chd")
    ln("play", 3)
    a("state")
    ln("init", 1, 7, 0)
    a("state")
    ln("bankmem", 0)
    ln("findbank", 0x7001)
    ln("addbank", "b1", 0)
    a("deinit")
    ln("bankmem", 4)
    ln("addbank", "b1", 0)
    ln("adddb", "dat3", 0, 0)
    a("deinit")
    a("state")
    a("btab")

    # ---- retail's data
    evt_b, pck_b = EVT_FILE.read_bytes(), PCK_FILE.read_bytes()
    nb = struct.unpack_from("<I", pck_b, 0)[0]
    ln("init", 1, 5, 22050)
    ln("vecs", 1)
    ln("rulecb", 1, 1)
    ln("bankmem", nb + 8)
    ln("file", "evt", EVT_FILE)
    ln("file", "pck", PCK_FILE)
    ln("adddb", "evt", 0, 0)
    ln("pckput", "pck", nb)
    ln("pckadd", "pck", 0, 9)
    a("btab")
    a("state")
    rp = retail_parms(evt_b, pck_b)
    ln("tick", 1000)
    for k, p in enumerate(rp):
        if k % 3 == 0:
            ev(*p)
            ln("play", 0)
        elif k % 3 == 1:
            q = list(p)
            for j in range(1, 20):
                if q[j] == ALL and (j + k) % 4 == 0:
                    q[j] = 1 << ((j + k) % 6)
            ev(*q)
            ln("choose", 0)
            a("chd")
            ln("play", 0)
        ln("tick", 1001 + k)
    for k in range(0, len(rp), 7):
        ev(*rp[k])
        ln("play", 0)
    a("state")
    a("q")
    a("deinit")
    return L


# ================================================================= build

def build_harness(tmp, name="spch_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)],
                               stdout=fh, stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def model_cached(lines):
    """model(lines)'s transcript, or its last one when nothing it reads
    has changed. Nothing past the mutations' header is the model's."""
    return mutpar.model_cached(lines, lambda sc: model(sc)[0],
                               cut=MUTATIONS_HEADER)


def _m(name, before, after, rel=PICK):
    return (name, rel, before, after)


MUTATIONS = [
    # ---- spch.c
    _m("print-vec", "        gSpch.ext.print(buf);", '        printf("%s", buf);',
       SPCH),
    _m("abort-vec", "        gSpch.ext.abort(buf);",
       "        gSpch.ext.print(buf);", SPCH),
    _m("tick-vec", "return gSpch.ext.gettick();",
       "return gSpch.ext.gettick() + 1;", SPCH),
    _m("tick-print", '    spchi_print("gettick vector not installed.");\n',
       "", SPCH),
    _m("tick-none", '    spchi_print("gettick vector not installed.");\n    return 0;',
       '    spchi_print("gettick vector not installed.");\n    return 1;', SPCH),
    _m("datinfo-swap", "    *a = dat[8];\n    *b = dat[9];",
       "    *a = dat[9];\n    *b = dat[8];", SPCH),
    _m("bind-version", "spch_u16(dat) != 0x803", "spch_u16(dat) != 0x802",
       SPCH),
    _m("bind-dup-a", "d[9] == b && d[8] == a", "d[9] == b", SPCH),
    _m("bind-dup-b", "d[9] == b && d[8] == a", "d[8] == a", SPCH),
    _m("bind-dup-ret", 'same project and dat IDs.");\n            return 0;',
       'same project and dat IDs.");', SPCH),
    _m("bind-slot-order",
       "    for (i = 0; i < SPCH_EVENT_DATS; i++) {\n"
       "        if (gSpch.eventDats[i].dat == NULL) {",
       "    for (i = SPCH_EVENT_DATS - 1; i >= 0; i--) {\n"
       "        if (gSpch.eventDats[i].dat == NULL) {", SPCH),
    _m("bind-channel", "gSpch.eventDats[i].channel = channel;",
       "gSpch.eventDats[i].channel = 0;", SPCH),
    _m("bind-ret", "gSpch.eventDats[i].channel = channel;\n            return 1;",
       "gSpch.eventDats[i].channel = channel;\n            return 2;", SPCH),
    _m("bind-full-ret", "SPCH_EVENT_DATS);\n    return 0;",
       "SPCH_EVENT_DATS);\n    return 1;", SPCH),
    _m("adddb-channel", "if (channel >= SPCH_CHANNELS) {",
       "if (channel > SPCH_CHANNELS) {", SPCH),
    _m("adddb-ret", "(long)SPCH_CHANNELS);\n        return 0;",
       "(long)SPCH_CHANNELS);\n        return 1;", SPCH),
    _m("resolve-channel", "return spch_add_event_db(dat, 0);",
       "return spch_add_event_db(dat, 1);", SPCH),
    _m("ingame-count", "gSpch.inGame[i].count = 0;",
       "gSpch.inGame[i].count = 1;", SPCH),
    _m("ingame-word", "(gSpch.inGame[i].word & 0xffff0000u) | 0xffff",
       "0xffff", SPCH),
    _m("ingame-n",
       "    for (i = 0; i < SPCH_CHANNELS; i++) {\n"
       "        gSpch.inGame[i].count = 0;",
       "    for (i = 0; i < SPCH_CHANNELS - 1; i++) {\n"
       "        gSpch.inGame[i].count = 0;", SPCH),
    _m("rate-round", "v = (v < 0 ? v + 7 : v) >> 3;", "v = v >> 3;", SPCH),
    _m("rate-mode1", "return v / 10;", "return v / 9;", SPCH),
    _m("rate-mode2", "return v * 2 / 7;", "return v * 2 / 8;", SPCH),
    _m("rate-which", "    if (mode == 1)\n        return v / 10;",
       "    if (mode == 3)\n        return v / 10;", SPCH),
    _m("rulecb-check",
       'call SPCH_Init first.\\n");\n        return;\n    }\n    gSpch.ruleSet',
       'call SPCH_Init first.\\n");\n    }\n    gSpch.ruleSet', SPCH),
    _m("rulecb-set", "    gSpch.ruleSet = set;", "    gSpch.ruleSet = NULL;",
       SPCH),
    _m("rulecb-test", "    gSpch.ruleTest = test;",
       "    gSpch.ruleTest = NULL;", SPCH),
    _m("ext-abort", "    gSpch.ext.abort = NULL;\n", "", SPCH),
    _m("ext-tick", "    gSpch.ext.gettick = NULL;\n", "", SPCH),
    _m("ext-print", "    gSpch.ext.print = NULL;\n", "", SPCH),
    _m("cb-request", "    gSpch.request = NULL;\n    gSpch.ruleSet = NULL;",
       "    gSpch.ruleSet = NULL;", SPCH),
    _m("cb-ruleset", "    gSpch.ruleSet = NULL;\n    gSpch.ruleTest = NULL;\n}",
       "    gSpch.ruleTest = NULL;\n}", SPCH),
    _m("cb-ruletest", "    gSpch.ruleTest = NULL;\n}\n\nvoid spch_init_reparm",
       "}\n\nvoid spch_init_reparm", SPCH),
    _m("reparmcb-check",
       'SPCH_InitReparmCallback - call SPCH_Init first.\\n");\n        return;',
       'SPCH_InitReparmCallback - call SPCH_Init first.\\n");', SPCH),
    _m("reparmcb-set", "    gSpch.reparm = fn;", "    gSpch.reparm = NULL;",
       SPCH),
    _m("erulecb-check",
       'SPCH_InitEventRuleCallback - call SPCH_Init first.\\n");\n        return;',
       'SPCH_InitEventRuleCallback - call SPCH_Init first.\\n");', SPCH),
    _m("erulecb-set", "    gSpch.eventRule = fn;",
       "    gSpch.eventRule = NULL;", SPCH),
    _m("init-order",
       "    spchi_init_callbacks();\n    spchi_init_ext_vecs();\n"
       "    gSpch.request = request;",
       "    spchi_init_ext_vecs();\n    gSpch.request = request;\n"
       "    spchi_init_callbacks();", SPCH),
    _m("init-vecs", "    spchi_init_callbacks();\n    spchi_init_ext_vecs();\n",
       "    spchi_init_callbacks();\n", SPCH),
    _m("init-rate", "gSpch.dataRate = rate;", "gSpch.dataRate = rate + 1;",
       SPCH),
    _m("init-game", "gSpch.gameNum = game;", "gSpch.gameNum = game + 1;",
       SPCH),
    _m("init-random", "spchi_init_random(game);",
       "spchi_init_random(game + 1);", SPCH),
    _m("init-choice",
       "    spchi_init_sentence_choice();\n    spch_set_pre_load_ticks(0);",
       "    spch_set_pre_load_ticks(0);", SPCH),
    _m("init-preload", "    spch_set_pre_load_ticks(0);\n", "", SPCH),
    _m("init-filter", "gSpch.filter[i] = 0;", "gSpch.filter[i] = 1;", SPCH),
    _m("init-filter-n", "for (i = SPCH_CHANNELS - 1; i >= 0; i--)",
       "for (i = SPCH_CHANNELS - 1; i > 0; i--)", SPCH),
    _m("init-dats", "    spchi_init_event_dat();\n    spchi_init_in_game();",
       "    spchi_init_in_game();", SPCH),
    _m("init-ingame", "    spchi_init_in_game();\n    spchi_init_banks();",
       "    spchi_init_banks();", SPCH),
    _m("init-banks", "    spchi_init_banks();\n    spchi_init_event_queue();",
       "    spchi_init_event_queue();", SPCH),
    _m("init-queue",
       "    spchi_init_event_queue();\n    gSpch.initialized = SPCH_MAGIC;",
       "    gSpch.initialized = SPCH_MAGIC;", SPCH),
    _m("init-ret", "    gSpch.initialized = SPCH_MAGIC;\n    return 1;",
       "    gSpch.initialized = SPCH_MAGIC;\n    return 0;", SPCH),
    _m("deinit-check", '"SPCH_Deinit - not initialized.");\n        return;',
       '"SPCH_Deinit - not initialized.");', SPCH),
    _m("deinit-magic", "    gSpch.initialized = 0;\n", "", SPCH),
    _m("deinit-cb", "    gSpch.initialized = 0;\n    spchi_init_callbacks();",
       "    gSpch.initialized = 0;", SPCH),
    _m("deinit-banks",
       "    spchi_dispose_banks();\n    spchi_init_event_dat();\n    spch_save",
       "    spchi_init_event_dat();\n    spch_save", SPCH),
    _m("deinit-dats", "    spchi_init_event_dat();\n    spch_save_evlog();",
       "    spch_save_evlog();", SPCH),
    _m("evlog-check", 'before SPCH_InitEvlog\\n");\n        return 0;',
       'before SPCH_InitEvlog\\n");\n        return 1;', SPCH),
    _m("evlog-ret", "    return 1;\n}\n\nvoid spch_deinit_evlog",
       "    return 0;\n}\n\nvoid spch_deinit_evlog", SPCH),

    # ---- spchbank.c
    _m("initbanks-n",
       "void spchi_init_banks(void)\n{\n    gSpch.banks = NULL;\n"
       "    gSpch.numBanks = 0;",
       "void spchi_init_banks(void)\n{\n    gSpch.banks = NULL;\n"
       "    gSpch.numBanks = 1;", BANK),
    _m("dispose-banks",
       "void spchi_dispose_banks(void)\n{\n    gSpch.banks = NULL;\n",
       "void spchi_dispose_banks(void)\n{\n", BANK),
    _m("memsize", "return n * (int32_t)sizeof(uint8_t *);",
       "return (n + 1) * (int32_t)sizeof(uint8_t *);", BANK),
    _m("bankmem-n", "    gSpch.numBanks = n;\n    gSpch.banks = table;",
       "    gSpch.numBanks = n - 1;\n    gSpch.banks = table;", BANK),
    _m("bankmem-clear", "            table[i] = NULL;", "            ;", BANK),
    _m("bankptr-magic",
       "if (gSpch.initialized != SPCH_MAGIC || gSpch.banks == NULL)",
       "if (gSpch.banks == NULL)", BANK),
    _m("bankptr-null",
       "if (gSpch.initialized != SPCH_MAGIC || gSpch.banks == NULL)",
       "if (gSpch.initialized != SPCH_MAGIC)", BANK),
    _m("free-first",
       "    for (i = 0; i < gSpch.numBanks; i++)\n"
       "        if (gSpch.banks[i] == NULL)",
       "    for (i = 1; i < gSpch.numBanks; i++)\n"
       "        if (gSpch.banks[i] == NULL)", BANK),
    _m("free-none", "    return -1;\n}\n\nint32_t spchi_find_bank(",
       "    return -2;\n}\n\nint32_t spchi_find_bank(", BANK),
    _m("find-mask", "    id &= 0xffff;\n    if (gSpch.banks",
       "    if (gSpch.banks", BANK),
    _m("find-null-ret",
       "        return -1;\n    }\n    for (i = 0; i < gSpch.numBanks; i++) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id)\n",
       "        return 0;\n    }\n    for (i = 0; i < gSpch.numBanks; i++) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id)\n", BANK),
    _m("find-order",
       "    for (i = 0; i < gSpch.numBanks; i++) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id)\n",
       "    for (i = gSpch.numBanks - 1; i >= 0; i--) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id)\n", BANK),
    _m("fsub-mask", "    sub &= 0xffff;\n", "", BANK),
    _m("fsub-sub", "spch_u16(b + 2) == sub", "spch_u16(b + 2) >= sub", BANK),
    _m("fsub-id", "spch_u16(b) == id && spch_u16(b + 2) == sub",
       "spch_u16(b + 2) == sub", BANK),
    _m("fsub-null-ret",
       "        return -1;\n    }\n    for (i = 0; i < gSpch.numBanks; i++) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id && spch_u16(b + 2) == sub)",
       "        return -2;\n    }\n    for (i = 0; i < gSpch.numBanks; i++) {\n"
       "        const uint8_t *b = gSpch.banks[i];\n\n"
       "        if (b != NULL && spch_u16(b) == id && spch_u16(b + 2) == sub)",
       BANK),
    _m("tsbb-null-ret",
       'TestSubBankBounds - bank mem not initialized.");\n        return 0;',
       'TestSubBankBounds - bank mem not initialized.");\n        return 1;',
       BANK),
    _m("tsbb-neg", "    if (handle < 0)\n        return 0;",
       "    if (handle < 0)\n        return 1;", BANK),
    _m("tsbb-ffff", "if (n == 0xffff)", "if (n == 0xfffe)", BANK),
    _m("tsbb-lt", "return v < n;", "return v <= n;", BANK),
    _m("tsbb-off", "n = spch_u16(gSpch.banks[handle] + 10);",
       "n = spch_u16(gSpch.banks[handle] + 8);", BANK),
    _m("freebank-set", "    gSpch.banks[handle] = NULL;", "    ;", BANK),
    _m("aq-len0", "    if (b[6] == 0)\n        return;\n", "", BANK),
    _m("aq-bound", "if (idx < b[6])\n        q[1 + idx]",
       "if (idx <= b[6])\n        q[1 + idx]", BANK),
    _m("aq-slot", "q[1 + idx] = (uint8_t)sample;",
       "q[idx] = (uint8_t)sample;", BANK),
    _m("aq-wrap", "    if (idx >= b[6])\n        idx = 0;",
       "    if (idx > b[6])\n        idx = 0;", BANK),
    _m("aq-step", "idx = (idx + 1) & 0xff;", "idx = (idx + 2) & 0xff;", BANK),
    _m("aq-store", "q[0] = (uint8_t)idx;", "q[0] = (uint8_t)(idx ^ 1);",
       BANK),
    _m("tq-j", "    j = q[0] - 1;", "    j = q[0];", BANK),
    _m("tq-wrap", "            j = n - 1;", "            j = n - 2;", BANK),
    _m("tq-ret", "            return a + 1;", "            return a;", BANK),
    _m("tq-val", "if (q[1 + j] == sample)", "if (q[j] == sample)", BANK),
    _m("cyc-len0", "    if (len == 0) {", "    if (len == 1) {", BANK),
    _m("cyc-g", "g = (uint32_t)gSpch.gameNum % len;",
       "g = (uint32_t)gSpch.gameNum % (len + 1);", BANK),
    _m("cyc-start", "start = g * n / len;", "start = (g * n + 1) / len;",
       BANK),
    _m("cyc-cnt", "cnt = (g * n + n) / len - start;",
       "cnt = (g * n + n) / len - start + 1;", BANK),
    _m("cyc-p", "p = c + 1 + (start >> 3);", "p = c + (start >> 3);", BANK),
    _m("cyc-bit", "bit = start & 7;", "bit = start & 3;", BANK),
    _m("cyc-wrap", "if (++bit == 8) {", "if (++bit == 7) {", BANK),
    _m("cyc-or", "*p |= (uint8_t)(1u << bit);", "*p = (uint8_t)(1u << bit);",
       BANK),
    _m("add-null-ret",
       'iSPCH_AddBank - bank mem not initialized.");\n        return -1;',
       'iSPCH_AddBank - bank mem not initialized.");\n        return 0;', BANK),
    _m("add-q-check", "    if (b[6] != 0) {\n        const uint8_t *q",
       "    if (0) {\n        const uint8_t *q", BANK),
    _m("add-q0", "        if (q[0] != 0) {", "        if (0) {", BANK),
    _m("add-q255", "if (q[1 + i] != 255) {", "if (q[1 + i] == 0) {", BANK),
    _m("add-q-n", "for (i = 0; i < b[6]; i++) {",
       "for (i = 0; i < b[6] - 1; i++) {", BANK),
    _m("add-full-ret", 'out of bank mem.\\n");\n        return k;',
       'out of bank mem.\\n");\n        return 0;', BANK),
    _m("add-cycle", "    if (b[4] & 0x80)\n        spchi_set_cycle_bits(b);",
       "    if (b[4] & 0x40)\n        spchi_set_cycle_bits(b);", BANK),
    _m("add-set", "    gSpch.banks[k] = b;\n", "", BANK),
    _m("sample-size0", "    r->size = 0;\n", "    r->size = 1;\n", BANK),
    _m("sample-off0", "    r->offset = -1;\n", "    r->offset = 0;\n", BANK),
    _m("sample-np0", "    r->numParms = 0;\n", "    r->numParms = 1;\n", BANK),
    _m("sample-parms0", "memset(r->parms, 255, sizeof(r->parms));",
       "memset(r->parms, 0, sizeof(r->parms));", BANK),
    _m("unpack-np", "np = b[4] & 0xf,", "np = b[4] & 0x3,", BANK),
    _m("unpack-unit", "int32_t unit = (b[7] + 1) << 8, end;",
       "int32_t unit = (b[7] + 2) << 8, end;", BANK),
    _m("unpack-idx",
       '    if (!((int32_t)idx < n)) {\n        spchi_abort("UnPackSample',
       '    if (!((int32_t)idx <= n)) {\n        spchi_abort("UnPackSample',
       BANK),
    _m("unpack-numparms", "r->numParms = np;", "r->numParms = np - 1;", BANK),
    _m("unpack-parms", "r->parms[i] = e[2 + i];", "r->parms[i] = e[1 + i];",
       BANK),
    _m("unpack-alias-bit", "    if (e[0] & 0x80) {\n        idx = e[1];",
       "    if (e[0] & 0x40) {\n        idx = e[1];", BANK),
    _m("unpack-alias-idx", "        idx = e[1];", "        idx = e[1] + 1;",
       BANK),
    _m("unpack-alias-oob",
       'alias resolved out of bounds.\\n");\n        return 0;',
       'alias resolved out of bounds.\\n");\n        return 1;', BANK),
    _m("unpack-alias-alias",
       '    if (e[0] & 0x80) {\n        spchi_abort("iSPCH_UnpackSample - alias resolved to another',
       '    if (e[0] & 0x40) {\n        spchi_abort("iSPCH_UnpackSample - alias resolved to another',
       BANK),
    _m("unpack-off", "r->offset = ((e[0] << 8) + e[1]) * unit;",
       "r->offset = ((e[0] << 7) + e[1]) * unit;", BANK),
    _m("unpack-end", "end = spch_u16(b + 8) * unit;",
       "end = spch_u16(b + 6) * unit;", BANK),
    _m("unpack-next-alias", "        if (!(e[0] & 0x80)) {",
       "        if (1) {", BANK),
    _m("unpack-next-off", "            end = ((e[0] << 8) + e[1]) * unit;",
       "            end = ((e[0] << 8) + e[1] + 1) * unit;", BANK),
    _m("unpack-nobreak",
       "            break;\n        }\n    }\n    r->size = end - r->offset;",
       "        }\n    }\n    r->size = end - r->offset;", BANK),
    _m("unpack-size", "r->size = end - r->offset;",
       "r->size = end - r->offset + 1;", BANK),

    # ---- spchevnt.c
    _m("sed-count", "uint32_t n = spch_u16(dat + 16), k;",
       "uint32_t n = spch_u16(dat + 16) - 1, k;", EVNT),
    _m("sed-off", "dat + spch_u16(dat + 24 + 2 * k) * 4;",
       "dat + spch_u16(dat + 22 + 2 * k) * 4;", EVNT),
    _m("sed-id", "        if (spch_u16(ev) == id)\n            return ev;",
       "        if (spch_u16(ev) >= id)\n            return ev;", EVNT),
    _m("fedi-a", "d[9] == req[2] && d[8] == req[3]", "d[9] == req[2]", EVNT),
    _m("fedi-b", "d[9] == req[2] && d[8] == req[3]", "d[8] == req[3]", EVNT),
    _m("fedi-out", "*out = &gSpch.eventDats[i];",
       "*out = &gSpch.eventDats[0];", EVNT),
    _m("fe-id", "return spchi_search_event_dat(e->dat, spch_u16(req));",
       "return spchi_search_event_dat(e->dat, req[0]);", EVNT),
    _m("fec-channel", "*out = (int32_t)e->channel;", "*out = 0;", EVNT),
    _m("gdi-id", "*out = e->dat[9];", "*out = e->dat[8];", EVNT),
    _m("ied-dat", "        gSpch.eventDats[i].dat = NULL;\n", "", EVNT),
    _m("gfl-off", "return spch_u16(e->dat + 20);",
       "return spch_u16(e->dat + 22);", EVNT),
    _m("ieq-pending", "        q->numPending[i] = 0;\n        q->lastAdded",
       "        q->numPending[i] = 1;\n        q->lastAdded", EVNT),
    _m("ieq-added", "        q->lastAdded[i] = -1;",
       "        q->lastAdded[i] = 0;", EVNT),
    _m("ieq-head", "        q->lastHead[i] = -1;",
       "        q->lastHead[i] = 0;", EVNT),
    _m("ieq-bump", "    q->bumpFilter = 0;\n    // isAppend",
       "    // isAppend", EVNT),
    _m("ieq-active", "        s->active = 0;\n        s->tick = 0;",
       "        s->tick = 0;", EVNT),
    _m("ieq-tick", "        s->tick = 0;\n", "", EVNT),
    _m("ieq-ev", "        s->ev = NULL;\n", "", EVNT),
    _m("ieq-channel", "        s->channel = 255;", "        s->channel = 0;",
       EVNT),
    _m("ieq-subtick", "        s->subTick = 0;\n", "", EVNT),
    _m("ieq-parms", "            s->parms[k] = 0;", "            s->parms[k] = 1;",
       EVNT),
    _m("ieq-lasttick", "    gSpch.lastTick = 0;\n", "", EVNT),
    _m("ieq-lastsub", "    gSpch.lastSubTick = 0;\n}", "}", EVNT),
    _m("fes-free-order",
       "    for (i = 0; i < SPCH_SLOTS; i++)\n        if (!q->slot[i].active)",
       "    for (i = SPCH_SLOTS - 1; i >= 0; i--)\n        if (!q->slot[i].active)",
       EVNT),
    _m("fes-start", "        start = q->lastHead[channel];",
       "        start = q->lastAdded[channel];", EVNT),
    _m("fes-append", "    if (append)\n        start", "    if (!append)\n        start",
       EVNT),
    _m("fes-life-isappend",
       "if (s->isAppend == 0 && life != 0 && life < now - s->tick",
       "if (life != 0 && life < now - s->tick", EVNT),
    _m("fes-life0", "life != 0 && life < now - s->tick",
       "life < now - s->tick", EVNT),
    _m("fes-life-lt", "life != 0 && life < now - s->tick",
       "life != 0 && life <= now - s->tick", EVNT),
    _m("fes-life-start", "            && i != start) {\n            spchi_clear_event(i);",
       "            ) {\n            spchi_clear_event(i);", EVNT),
    _m("fes-life-clear", "            spchi_clear_event(i);\n            return i;",
       "            return i;", EVNT),
    _m("fes-pri", "pri >= spch_u16(s->ev + 4)", "pri > spch_u16(s->ev + 4)",
       EVNT),
    _m("fes-pri-isappend", "if (s->isAppend == 0 && pri >= spch_u16(s->ev + 4)",
       "if (pri >= spch_u16(s->ev + 4)", EVNT),
    _m("fes-pri-channel", "&& s->channel == channel && i != start) {",
       "&& i != start) {", EVNT),
    _m("fes-pri-start", "&& s->channel == channel && i != start) {",
       "&& s->channel == channel) {", EVNT),
    _m("fes-pri-pending", "            q->numPending[s->channel]--;\n            return i;",
       "            return i;", EVNT),
    _m("fes-fail", "    return -1;\n}\n\nint32_t spchi_check_last_event_index",
       "    return 0;\n}\n\nint32_t spchi_check_last_event_index", EVNT),
    _m("cle-head", "return (uint32_t)gSpch.queue.lastHead[channel] < SPCH_SLOTS\n        &&",
       "return 1\n        &&", EVNT),
    _m("cle-added",
       "SPCH_SLOTS\n        && (uint32_t)gSpch.queue.lastAdded[channel] < SPCH_SLOTS;",
       "SPCH_SLOTS;", EVNT),
    _m("ae-reenter",
       "        gSpch.addEventStatus = 0;\n        return 0;\n    }\n    gSpch.addEventStatus = 1;",
       "        return 0;\n    }\n    gSpch.addEventStatus = 1;", EVNT),
    _m("ae-app-bit", "app = (ev[10] >> 5) & 1;", "app = (ev[10] >> 4) & 1;",
       EVNT),
    _m("ae-app-check", "        if (!spchi_check_last_event_index(ch)) {",
       "        if (0) {", EVNT),
    _m("ae-app-pri", "pri = spch_u16(q->slot[head].ev + 4);",
       "pri = spch_u16(ev + 4);", EVNT),
    _m("ae-prob", "if ((int8_t)ev[9] < spchi_rand(100, -1)) {",
       "if ((int8_t)ev[9] <= spchi_rand(100, -1)) {", EVNT),
    _m("ae-prob-sign", "if ((int8_t)ev[9] < spchi_rand(100, -1)) {",
       "if (ev[9] < spchi_rand(100, -1)) {", EVNT),
    _m("ae-prob-key", "spchi_rand(100, -1)", "spchi_rand(100, 0)", EVNT),
    _m("ae-pri", "        pri = spch_u16(ev + 4);\n    }",
       "        pri = spch_u16(ev + 4) + 1;\n    }", EVNT),
    _m("ae-slot-app", "k = spchi_find_event_slot(pri, ch, app);",
       "k = spchi_find_event_slot(pri, ch, 0);", EVNT),
    _m("ae-full-app",
       "            spchi_clear_event(head);\n            spchi_abort(",
       "            spchi_abort(", EVNT),
    _m("ae-tick-eq", "if (t == gSpch.lastTick)", "if (t != gSpch.lastTick)",
       EVNT),
    _m("ae-sub-reset", "        gSpch.lastSubTick = 0;\n    gSpch.lastTick = t;",
       "        gSpch.lastSubTick = 1;\n    gSpch.lastTick = t;", EVNT),
    _m("ae-lasttick", "    gSpch.lastTick = t;\n", "", EVNT),
    _m("ae-channel", "s->channel = (uint8_t)ch;", "s->channel = 0;", EVNT),
    _m("ae-tick", "    s->tick = t;\n", "    s->tick = 0;\n", EVNT),
    _m("ae-next", "    s->next = -1;\n", "    s->next = 0;\n", EVNT),
    _m("ae-subtick", "s->subTick = gSpch.lastSubTick;", "s->subTick = 0;",
       EVNT),
    _m("ae-isappend", "s->isAppend = (int16_t)app;", "s->isAppend = 0;",
       EVNT),
    _m("ae-link", "q->slot[last].next = (int16_t)k;",
       "q->slot[head].next = (int16_t)k;", EVNT),
    _m("ae-parms", "        s->parms[i] = parms[i];",
       "        s->parms[i] = parms[i] & 0xffffff;", EVNT),
    _m("ae-pending", "    if (!app)\n        q->numPending[ch]++;",
       "    q->numPending[ch]++;", EVNT),
    _m("ae-active", "    s->active = 1;\n", "", EVNT),
    _m("ae-added", "    q->lastAdded[ch] = k;\n", "", EVNT),
    _m("ae-head", "    if (!app)\n        q->lastHead[ch] = k;",
       "    q->lastHead[ch] = k;", EVNT),
    _m("ae-ret", "    gSpch.addEventStatus = 0;\n    return 1;",
       "    gSpch.addEventStatus = 0;\n    return 2;", EVNT),
    _m("aev-id", "    buf[0] = id;", "    buf[0] = id & 0xffff;", EVNT),
    _m("aev-count", "for (i = 1; i <= count && i < SPCH_EVENT_PARMS; i++)",
       "for (i = 1; i < count && i < SPCH_EVENT_PARMS; i++)", EVNT),
    _m("aev-max", "for (i = 1; i <= count && i < SPCH_EVENT_PARMS; i++)",
       "for (i = 1; i <= count && i < SPCH_EVENT_PARMS - 1; i++)", EVNT),
    _m("ifg-mask", "    id &= 0xffff;\n    if (fd == NULL) {",
       "    if (fd == NULL) {", EVNT),
    _m("ifg-count", "if (fd->count <= 0)", "if (fd->count < 0)", EVNT),
    _m("ifg-loop", "for (i = 0; i < fd->count; i++)",
       "for (i = 0; i < fd->count - 1; i++)", EVNT),
    _m("ifg-stride", "spch_u16(fd->list + 2 * i) == id",
       "spch_u16(fd->list + i) == id", EVNT),
    _m("ces-preload", "uint32_t now = spchi_gettick() + gSpch.preLoadTicks;",
       "uint32_t now = spchi_gettick();", EVNT),
    _m("ces-bestage", "uint32_t bestAge = 0xffffffffu, bestSub = 0;",
       "uint32_t bestAge = 0, bestSub = 0;", EVNT),
    _m("ces-bestpri", "int32_t best = -1, bestPri = 0, i;",
       "int32_t best = -1, bestPri = -1, i;", EVNT),
    _m("ces-isappend",
       "if (!s->active || s->channel != channel || s->isAppend != 0)",
       "if (!s->active || s->channel != channel)", EVNT),
    _m("ces-channel",
       "if (!s->active || s->channel != channel || s->isAppend != 0)",
       "if (!s->active || s->isAppend != 0)", EVNT),
    _m("ces-fd", "        if (fd != NULL)\n            inGroup",
       "        if (0)\n            inGroup", EVNT),
    _m("ces-age", "age = now - s->tick;", "age = now - s->tick + 1;", EVNT),
    _m("ces-life0", "        if (life != 0)\n            expired = life < age;",
       "        expired = life < age;", EVNT),
    _m("ces-life-lt", "expired = life < age;", "expired = life <= age;", EVNT),
    _m("ces-filter1", "if (gSpch.filter[channel] == 1 && (ev[10] & 1)) {",
       "if (gSpch.filter[channel] >= 1 && (ev[10] & 1)) {", EVNT),
    _m("ces-filter-bit", "if (gSpch.filter[channel] == 1 && (ev[10] & 1)) {",
       "if (gSpch.filter[channel] == 1) {", EVNT),
    _m("ces-filter-pri", "filtered = spch_u16(ev + 4) < spch_u16(e->dat + 22);",
       "filtered = spch_u16(ev + 4) <= spch_u16(e->dat + 22);", EVNT),
    _m("ces-filter-off", "filtered = spch_u16(ev + 4) < spch_u16(e->dat + 22);",
       "filtered = spch_u16(ev + 4) < spch_u16(e->dat + 20);", EVNT),
    _m("ces-filter-word", "memcpy(word, &s->parms[0], 4);",
       "memcpy(word, &s->parms[1], 4);", EVNT),
    _m("ces-expired-clear",
       "        if (expired) {\n            spchi_clear_event(i);\n",
       "        if (expired) {\n", EVNT),
    _m("ces-group", "if (!inGroup || filtered)", "if (filtered)", EVNT),
    _m("ces-filtered", "if (!inGroup || filtered)", "if (!inGroup)", EVNT),
    _m("ces-pri", "if (bestPri < pri) {", "if (bestPri <= pri) {", EVNT),
    _m("ces-tie-age", "                   && (age < bestAge\n",
       "                   && (age <= bestAge\n", EVNT),
    _m("ces-tie-sub", "bestSub < s->subTick", "bestSub > s->subTick", EVNT),
    _m("ces-tie-bestage",
       "            best = i;\n            bestAge = age;\n            bestSub = s->subTick;\n        }\n    }",
       "            best = i;\n            bestSub = s->subTick;\n        }\n    }",
       EVNT),
    _m("ces-pri-bestage",
       "            bestPri = pri;\n            bestAge = age;\n",
       "            bestPri = pri;\n", EVNT),
    _m("ces-pri-bestsub",
       "            bestAge = age;\n            bestSub = s->subTick;\n        } else if",
       "            bestAge = age;\n        } else if", EVNT),
    _m("ce-flag", "if (ev != NULL && (ev[10] & 0x10)) {",
       "if (ev != NULL && (ev[10] & 0x20)) {", EVNT),
    _m("ce-sentences", "const uint8_t *p = ev + 12 + ((n6 * 2 + 3) & ~3)",
       "const uint8_t *p = ev + 12 + ((n6 * 2 + 1) & ~3)", EVNT),
    _m("ce-rules", "+ ((n7 * 3 + 3) & ~3);", "+ ((n7 * 3) & ~3);", EVNT),
    _m("ce-mask", "                p += (n6 * 2 + 7) & ~3;",
       "                p += (n6 * 2 + 4) & ~3;", EVNT),
    _m("ce-mask-flag", "            if (ev[10] & 8)\n                p +=",
       "            if (ev[10] & 4)\n                p +=", EVNT),
    _m("ce-count", "fd.count = p[0];", "fd.count = p[1];", EVNT),
    _m("ce-list", "fd.list = p + 2;", "fd.list = p + 1;", EVNT),
    _m("ce-retry", "    if (use && r < 0)\n", "    if (r < -1)\n", EVNT),
    _m("ceq-active",
       "            q->slot[i].active = 0;\n            q->numPending[q->slot[i].channel]--;",
       "            q->numPending[q->slot[i].channel]--;", EVNT),
    _m("ceq-pending", "            q->numPending[q->slot[i].channel]--;\n", "",
       EVNT),
    _m("ceq-discrepancy", "if (q->numPending[i] != 0) {",
       "if (q->numPending[i] > 0) {", EVNT),
    _m("ceq-ingame", "    spchi_init_in_game();\n}\n\nint32_t spch_check",
       "}\n\nint32_t spch_check", EVNT),
    _m("chkq", "return gSpch.queue.numPending[channel];",
       "return gSpch.queue.numPending[channel] > 0;", EVNT),
    _m("clr-oob", "    if ((uint32_t)i >= SPCH_SLOTS) {",
       "    if (i >= SPCH_SLOTS) {", EVNT),
    _m("clr-isappend", "    if (s->isAppend) {", "    if (s->isAppend > 1) {",
       EVNT),
    _m("clr-active", "    ch = s->channel;\n    s->active = 0;",
       "    ch = s->channel;", EVNT),
    _m("clr-head", "    if (q->lastHead[ch] == i)\n", "    if (0)\n", EVNT),
    _m("clr-added", "    if (q->lastAdded[ch] == i)\n", "    if (0)\n", EVNT),
    _m("clr-chain-isappend", "if (a->isAppend == 0 || !a->active) {",
       "if (!a->active) {", EVNT),
    _m("clr-chain-active", "if (a->isAppend == 0 || !a->active) {",
       "if (a->isAppend == 0) {", EVNT),
    _m("clr-chain-break",
       'append index points to invalid event.\\n");\n            break;',
       'append index points to invalid event.\\n");\n            return;', EVNT),
    _m("clr-chain-added", "        if (q->lastAdded[ch] == n)\n",
       "        if (0)\n", EVNT),
    _m("clr-chain-next", "        n = a->next;\n", "        n = -1;\n", EVNT),
    _m("clr-chain-clear", "        n = a->next;\n        a->active = 0;",
       "        n = a->next;", EVNT),
    _m("clr-pending", "    q->numPending[ch]--;\n    if (q->numPending[ch] < 0) {",
       "    if (q->numPending[ch] < 0) {", EVNT),
    _m("clr-neg", "    if (q->numPending[ch] < 0) {\n        q->numPending[ch] = 0;",
       "    if (q->numPending[ch] < -1) {\n        q->numPending[ch] = 0;", EVNT),
    _m("coe-bump0", "    q->bumpFilter = 0;\n    for", "    for", EVNT),
    _m("coe-self", "if (i == k || !s->active", "if (!s->active", EVNT),
    _m("coe-active", "if (i == k || !s->active || s->channel != ch",
       "if (i == k || s->channel != ch", EVNT),
    _m("coe-channel", "|| s->channel != ch || s->isAppend != 0)",
       "|| s->isAppend != 0)", EVNT),
    _m("coe-isappend", "|| s->channel != ch || s->isAppend != 0)",
       "|| s->channel != ch)", EVNT),
    _m("coe-older", "if (s->tick < t0 || (s->tick == t0 && s->subTick < sub0)) {",
       "if (s->tick < t0) {", EVNT),
    _m("coe-older-tick", "if (s->tick < t0 || (s->tick == t0",
       "if (s->tick <= t0 || (s->tick == t0", EVNT),
    _m("coe-stay", "if (!(s->ev[10] & 4))", "if (!(s->ev[10] & 2))", EVNT),
    _m("coe-prob", "} else if ((int8_t)s->ev[9] == 100) {",
       "} else if ((int8_t)s->ev[9] != 0) {", EVNT),
    _m("coe-bump", "            q->bumpFilter = 1;", "            q->bumpFilter = 2;",
       EVNT),
    _m("cer-null", "    if (gSpch.eventRule == NULL)\n        return 1;",
       "    if (gSpch.eventRule == NULL)\n        return 0;", EVNT),
    _m("cer-call", "return gSpch.eventRule(event);",
       "return gSpch.eventRule(event) != 0;", EVNT),
    _m("ple-isc", "    h = gSpch.queue.lastHead[channel];\n    spchi_init_sentence_choice();",
       "    h = gSpch.queue.lastHead[channel];", EVNT),
    _m("ple-clear",
       "    r = spchi_choose_single_sentence(h);\n    spchi_clear_event(h);",
       "    r = spchi_choose_single_sentence(h);", EVNT),
    _m("ple-play", "    if (r)\n        return spchi_play_chosen(channel);",
       "    if (r > 1)\n        return spchi_play_chosen(channel);", EVNT),
    _m("ple-ret", "return gSpch.queue.numPending[gSpch.queue.slot[h].channel];",
       "return 0;", EVNT),
    _m("play-reenter",
       '"Tried to re-enter SPCH_Play.");\n        gSpch.playStatus = 0;',
       '"Tried to re-enter SPCH_Play.");', EVNT),
    _m("play-one", "    if (spchi_one_chosen(channel))\n        r =",
       "    if (0)\n        r =", EVNT),
    _m("play-choose",
       "    else if (spch_choose(channel))\n        r = spchi_play_chosen(channel);",
       "    else\n        r = spch_choose(channel);", EVNT),
    _m("play-status", "    gSpch.playStatus = 0;\n    return r;",
       "    return r;", EVNT),
    _m("playspeech", "return spch_play(0);", "return spch_play(1);", EVNT),
    _m("choose-erule", "if (spchi_callback_event_rule(&word) == 1)",
       "if (spchi_callback_event_rule(&word) != 0)", EVNT),
    _m("choose-word", "word = q->slot[k].parms[0];",
       "word = q->slot[k].parms[1];", EVNT),
    _m("choose-old", "    spchi_clear_old_events(k);\n", "", EVNT),
    _m("choose-isc",
       "    spchi_clear_old_events(k);\n    spchi_init_sentence_choice();",
       "    spchi_clear_old_events(k);", EVNT),
    _m("choose-chain", "        s = q->slot[s].next;", "        s = -1;", EVNT),
    _m("choose-r", "} while (s != -1 && r != 0);", "} while (s != -1);", EVNT),
    _m("choose-clear", "} while (s != -1 && r != 0);\n    spchi_clear_event(k);",
       "} while (s != -1 && r != 0);", EVNT),
    _m("choosespeech", "return spch_choose(0);", "return spch_choose(1);",
       EVNT),
    _m("filter-set", "gSpch.filter[channel] = setting;",
       "gSpch.filter[channel] = setting & 1;", EVNT),

    # ---- spchpick.c
    _m("sentence-at", "return ev + spch_u16(ev + 12 + 2 * s) * 4;",
       "return ev + spch_u16(ev + 12 + 2 * s) * 4 + 4;", PICK),
    _m("phrase-at", "return sent + sent[4 + i] * 4;",
       "return sent + sent[4] * 4;", PICK),
    _m("smp-id", "    gSpch.lastMatchParmId = id;\n", "", PICK),
    _m("smp-value", "    gSpch.lastMatchParmValue = v;\n", "", PICK),
    _m("gmp-id", "if (gSpch.lastMatchParmId == id)",
       "if (gSpch.lastMatchParmId != id)", PICK),
    _m("gmp-print", '    spchi_print("Match parm not set.");\n', "", PICK),
    _m("gmp-none", '    spchi_print("Match parm not set.");\n    return 0;',
       '    spchi_print("Match parm not set.");\n    return -1;', PICK),
    _m("cmp-id", "gSpch.lastMatchParmId = -1;", "gSpch.lastMatchParmId = 0;",
       PICK),
    _m("cmp-value", "    gSpch.lastMatchParmValue = 0;\n}",
       "    gSpch.lastMatchParmValue = 1;\n}", PICK),
    _m("msd-head", "(long)handle, (long)(int8_t)ph[4]);",
       "(long)handle, (long)ph[5]);", PICK),
    _m("msd-numparms", '    spchi_print("numParms: %ld - ", (long)rec->numParms);\n',
       "", PICK),
    _m("msd-loop", "for (i = 0; i < rec->numParms && i < SPCH_SAMPLE_PARMS; i++)",
       "for (i = 1; i < rec->numParms && i < SPCH_SAMPLE_PARMS; i++)", PICK),
    _m("ms-nrules", "if (nr >= 5) {", "if (nr >= 6) {", PICK),
    _m("ms-v32", "if (v >= 32) {", "if (v >= 33) {", PICK),
    _m("ms-v32-dprint", "            match_sample_dprint(handle, rec, ph);\n",
       "", PICK),
    _m("ms-v32-ret", "spch_u16(ph));\n            return 0;",
       "spch_u16(ph));\n            return 1;", PICK),
    _m("ms-mask", "if (!(bit & spch_u32(ph + 16 + 4 * t)))",
       "if (!(bit & spch_u32(ph + 16)))", PICK),
    _m("ms-ref", "ref = ph[8 + t];", "ref = ph[8];", PICK),
    _m("ms-ref0", "if (ref == 0 || ref == 254 || ref == 255)",
       "if (ref == 254 || ref == 255)", PICK),
    _m("ms-ref254", "if (ref == 0 || ref == 254 || ref == 255)",
       "if (ref == 0 || ref == 255)", PICK),
    _m("ms-ref255", "if (ref == 0 || ref == 254 || ref == 255)",
       "if (ref == 0 || ref == 254)", PICK),
    _m("ms-pv20", "pv = ref < SPCH_EVENT_PARMS ? parms[ref] : 0;",
       "pv = ref < SPCH_EVENT_PARMS ? parms[ref] : ~0u;", PICK),
    _m("ms-pv-bit", "if (!(pv & bit))", "if (!pv)", PICK),
    _m("gpb-sub0", "    out->sub = -1;\n    out->bank = -1;",
       "    out->sub = 0;\n    out->bank = -1;", PICK),
    _m("gpb-type0", "out->bank = (int16_t)spchi_find_bank(id);",
       "out->bank = (int16_t)spchi_find_bank(id + 1);", PICK),
    _m("gpb-parm20", "if (p >= SPCH_EVENT_PARMS) {",
       "if (p > SPCH_EVENT_PARMS) {", PICK),
    _m("gpb-parm20-print",
       '            spchi_print("iSPCH_GetPhraseBank - subBankID index = %ld - out of bounds\\n",\n                        (long)p);\n',
       "", PICK),
    _m("gpb-type1-sub",
       "out->bank = (int16_t)spchi_find_sub_bank(id, parms[p] & 0xffff);",
       "out->bank = (int16_t)spchi_find_bank(id);", PICK),
    _m("gpb-type1-parm",
       "out->bank = (int16_t)spchi_find_sub_bank(id, parms[p] & 0xffff);",
       "out->bank = (int16_t)spchi_find_sub_bank(id, parms[1] & 0xffff);",
       PICK),
    _m("gpb-type2-v20", "v = p < SPCH_EVENT_PARMS ? parms[p] : 0;",
       "v = p < SPCH_EVENT_PARMS ? parms[p] : 1;", PICK),
    _m("gpb-type2-sub", "            out->sub = (int16_t)v;",
       "            out->sub = 0;", PICK),
    _m("gpb-type2-fail", "        else\n            b = -1;", "", PICK),
    _m("gpb-type2-case", "    case 2:\n        b = spchi_find_bank(id);",
       "    case 3:\n        b = spchi_find_bank(id);", PICK),
    _m("gpb-type1-case", "    case 1:\n        if (p >= SPCH_EVENT_PARMS) {",
       "    case 4:\n        if (p >= SPCH_EVENT_PARMS) {", PICK),
    _m("gpb-ret", "return out->bank > -1;", "return out->bank > 0;", PICK),
    _m("ccb-c", "    c[1 + q] &= ", "    c[q] &= ", PICK),
    _m("ccb-bit", "(uint8_t)~(1u << ((uint32_t)(i - 8 * q) & 31))",
       "(uint8_t)~(1u << ((uint32_t)(i - 8 * q) & 3))", PICK),
    _m("ccb-q", "    int32_t q = i / 8;\n\n    c[1 + q]",
       "    int32_t q = i >> 3;\n\n    c[1 + q]", PICK),
    _m("tb-mask", "return p[q] & ((1u << ((uint32_t)(i - 8 * q) & 31)) & 0xff);",
       "return p[q] & ((1u << ((uint32_t)(i - 8 * q) & 31)) & 0x7f);", PICK),
    _m("tb-q", "    int32_t q = i / 8;\n\n    return p[q]",
       "    int32_t q = i >> 3;\n\n    return p[q]", PICK),
    _m("cts-oob", "if (!(pair->sub < (int32_t)spch_u16(b + 10))) {",
       "if (!(pair->sub <= (int32_t)spch_u16(b + 10))) {", PICK),
    _m("cts-oob-ret", "spch_u16(b));\n        return 0;\n    }\n    t = spch_bank_queue(b);",
       "spch_u16(b));\n        return 1;\n    }\n    t = spch_bank_queue(b);", PICK),
    _m("cts-queue", "        t += b[6] + 1;", "        t += b[6];", PICK),
    _m("cts-idx", "return spchi_test_bit(t, b[5] * pair->sub + idx);",
       "return spchi_test_bit(t, b[5] * pair->sub + idx + 1);", PICK),
    _m("se-oob", "    if (b[5] < idx) {", "    if (b[5] <= idx) {", PICK),
    _m("se-sub", "    if (pair->sub != -1) {\n        r =",
       "    if (pair->sub > 0) {\n        r =", PICK),
    _m("se-template0", "        if (r == 0)\n            return 0;\n", "", PICK),
    _m("se-cycle", "r = spchi_test_bit(spch_bank_cycle(b) + 1, idx);",
       "r = spchi_test_bit(spch_bank_cycle(b), idx);", PICK),
    _m("se-cycle-flag", "    if (b[4] & 0x80)\n        r = spchi_test_bit",
       "    if (b[4] & 0x40)\n        r = spchi_test_bit", PICK),
    _m("asp-limit", "if (ctx->numPicks < SPCH_PICKS) {",
       "if (ctx->numPicks < SPCH_PICKS - 1) {", PICK),
    _m("asp-ret", "        return 1;\n    }\n    spchi_abort(\"iSPCH_AddSampleToValidPicks",
       "        return 2;\n    }\n    spchi_abort(\"iSPCH_AddSampleToValidPicks", PICK),
    _m("asp-fail", 'ran out of pick space\\n");\n    return 0;',
       'ran out of pick space\\n");\n    return 1;', PICK),
    _m("cs-unpack",
       "        if (!spchi_unpack_sample(b, (uint32_t)s, &rec))\n            continue;\n",
       "        spchi_unpack_sample(b, (uint32_t)s, &rec);\n", PICK),
    _m("cs-match", "        if (!spchi_match_sample(bi, &rec, ph, parms))\n            continue;\n",
       "", PICK),
    _m("cs-exists", "        if (!spchi_sample_exists(pair, b, s))\n            continue;\n",
       "", PICK),
    _m("cs-queued", "        if (q > 0) {", "        if (q > 1) {", PICK),
    _m("cs-best", "            if (bq < q) {", "            if (q < bq || bq == 0) {",
       PICK),
    _m("cs-fallback-cnt", "if (cnt == 0 && best != -1)", "if (best != -1)",
       PICK),
    _m("cs-fallback-best", "if (cnt == 0 && best != -1)", "if (cnt == 0)",
       PICK),
    _m("cvt-rate0", "    if (gSpch.dataRate == 0) {", "    if (gSpch.dataRate < 0) {",
       PICK),
    _m("cvt", "return x * 100 / gSpch.dataRate;",
       "return (x * 100 + 50) / gSpch.dataRate;", PICK),
    _m("sl-nph", "int32_t nph = sent[3] >> 2, i, sum = 0;",
       "int32_t nph = sent[3] >> 3, i, sum = 0;", PICK),
    _m("sl-cur", "ctx->picks[e->cur], &rec))\n            sum",
       "ctx->picks[e->start], &rec))\n            sum", PICK),
    _m("sl-sum", "sum += rec.size;", "sum = rec.size;", PICK),
    _m("dw-table", "1, 4, 16, 64, 256, 1024, 4096, 16384",
       "1, 4, 16, 64, 256, 1024, 4096, 16385", PICK),
    _m("dw-shift", "multiple[(b & 0xff) >> 5]", "multiple[(b & 0x7f) >> 5]",
       PICK),
    _m("dw-low", "(int32_t)(b & 0x1f)", "(int32_t)(b & 0xf)", PICK),
    _m("os-total", "        total += w[i];", "        total = w[i];", PICK),
    _m("os-rand-key", "r = spchi_rand(total, -1);", "r = spchi_rand(total, 0);",
       PICK),
    _m("os-w0", "            r -= w[0];\n            if (r >= 0)",
       "            r -= w[0];\n            if (r > 0)", PICK),
    _m("os-ws", "                    if (r < 0)\n                        break;",
       "                    if (r <= 0)\n                        break;", PICK),
    _m("os-w-zero", "        total -= w[s];\n        w[s] = 0;",
       "        total -= w[s];", PICK),
    _m("os-zero-weight",
       "        if (spchi_decode_weight(sentence_at(ev, i)[0]) == 0)\n            order[c++]",
       "        if (0)\n            order[c++]", PICK),
    _m("re-id", "if (spch_u16(ev) == (uint16_t)g->word && (int8_t)ev[8] > 0)",
       "if ((int8_t)ev[8] > 0)", PICK),
    _m("re-limit0", "(uint16_t)g->word && (int8_t)ev[8] > 0)",
       "(uint16_t)g->word && (int8_t)ev[8] >= 0)", PICK),
    _m("re-count", "return g->count < (int8_t)ev[8];",
       "return g->count <= (int8_t)ev[8];", PICK),
    _m("srs-0", "    case 0:\n        return 1;\n    case 1:",
       "    case 0:\n        return mode < 3;\n    case 1:", PICK),
    _m("srs-1", "        return mode == 2;", "        return mode >= 1;", PICK),
    _m("srs-2", "        return mode != 2;", "        return mode == 0;", PICK),
    _m("srs-3", "    }\n    return 0;\n}\n\n// The bank's ID",
       "    }\n    return 1;\n}\n\n// The bank's ID", PICK),
    _m("bpid-n", "int32_t n = (b[4] & 0x70) >> 4, i;",
       "int32_t n = (b[4] & 0x70) >> 5, i;", PICK),
    _m("bpid-p", "p = b + 12 + b[5] * ((b[4] & 0xf) + 2);",
       "p = b + 12 + b[5] * ((b[4] & 0xf) + 1);", PICK),
    _m("bpid-w", "uint32_t w = (uint32_t)(p[0] << 8) | p[1];",
       "uint32_t w = (uint32_t)(p[1] << 8) | p[0];", PICK),
    _m("bpid-parm", "if ((int32_t)(w >> 13) == parm)",
       "if ((int32_t)(w >> 12) == parm)", PICK),
    _m("bpid-id", "return (int32_t)(w & 0x1fff);",
       "return (int32_t)(w & 0xfff);", PICK),
    _m("bpid-none", "    }\n    return -1;\n}\n\n// The sentence's rules",
       "    }\n    return 0;\n}\n\n// The sentence's rules", PICK),
    _m("sgc-nph", "if (nph >= SPCH_PICK_PHRASES + 1) {",
       "if (nph >= SPCH_PICK_PHRASES + 2) {", PICK),
    _m("sgc-short", "    if (!spchi_short_rule_status(sent, mode))\n        return 0;\n",
       "", PICK),
    _m("sgc-rules",
       "    if (!spchi_check_sentence_rules(rs & 0xff, fb & 0xff, sent))\n        return 0;\n",
       "", PICK),
    _m("sgc-fb", "spchi_check_sentence_rules(rs & 0xff, fb & 0xff, sent)",
       "spchi_check_sentence_rules(rs & 0xff, 0, sent)", PICK),
    _m("sgc-nph-set", "    ctx->nph = (uint8_t)nph;", "    ctx->nph = 0;", PICK),
    _m("sgc-start", "        e->start = ctx->numPicks;", "        e->start = 0;",
       PICK),
    _m("sgc-c0", "        if (c == 0)\n            return 0;\n", "", PICK),
    _m("sgc-cnt", "        e->cnt = (uint8_t)c;", "        e->cnt = (uint8_t)(c - 1);",
       PICK),
    _m("rpp-n", "for (i = 0; i < n / 2; i++) {", "for (i = 0; i < (n + 1) / 2; i++) {",
       PICK),
    _m("rpp-key", "j = spchi_rand(n, n);", "j = spchi_rand(n, 0);", PICK),
    _m("rpp-swap", "        arr[j] = t;\n", "", PICK),
    _m("rsp-n", "for (k = 0; k < e->cnt >> 1; k++) {",
       "for (k = 0; k < (e->cnt + 1) >> 1; k++) {", PICK),
    _m("rsp-key", "            j = spchi_rand(e->cnt, e->bank);\n            t = p[k];",
       "            j = spchi_rand(e->cnt, -1);\n            t = p[k];", PICK),
    _m("rsp-swap", "            p[j] = t;\n", "", PICK),
    _m("rsp-start", "uint8_t *p = ctx->picks + e->start, t;",
       "uint8_t *p = ctx->picks, t;", PICK),
    _m("itc-i", "int32_t i = (sent[3] >> 2) - 1;", "int32_t i = (sent[3] >> 2) - 2;",
       PICK),
    _m("itc-lt", "if (e->cur < e->start + e->cnt)",
       "if (e->cur <= e->start + e->cnt)", PICK),
    _m("itc-reset", "        e->cur = e->start;\n        i--;", "        i--;", PICK),
    _m("css-cur", "ctx->e[i].cur = ctx->e[i].start;", "ctx->e[i].cur = 0;", PICK),
    _m("css-len", "if (spchi_sentence_length(sent, ctx) < maxLen)",
       "if (spchi_sentence_length(sent, ctx) <= maxLen)", PICK),
    _m("mb-255", "    if (p == 255) {", "    if (p == 254) {", PICK),
    _m("mb-bit", "    return 1u << (p & 31);", "    return 2u << (p & 31);", PICK),
    _m("pps-254", "        if (ref == 254) {", "        if (ref == 253) {", PICK),
    _m("pps-254-key", "            r = spchi_rand(e->cnt, e->bank);\n            e->cur",
       "            r = spchi_rand(e->cnt, -1);\n            e->cur", PICK),
    _m("pps-254-cur", "            e->cur = (uint8_t)(e->start + r);\n            idx",
       "            e->cur = (uint8_t)e->start;\n            idx", PICK),
    _m("pps-254-idx", "idx = (e->start + r) & 0xff;", "idx = e->start;", PICK),
    _m("pps-254-pid", "pid = spchi_get_bank_parm_id(e->bank, t);",
       "pid = spchi_get_bank_parm_id(e->bank, 0);", PICK),
    _m("pps-254-set", "spchi_set_match_parm(pid, (int32_t)match_bit(&rec, t));",
       "spchi_set_match_parm(pid, (int32_t)match_bit(&rec, 0));", PICK),
    _m("pps-254-found", "            found = 1;\n        } else if (ref == 255) {",
       "        } else if (ref == 255) {", PICK),
    _m("pps-255", "} else if (ref == 255) {", "} else if (ref == 254) {", PICK),
    _m("pps-255-mv", "mv = spchi_get_match_parm(spchi_get_bank_parm_id(e->bank, t));",
       "mv = spchi_get_match_parm(spchi_get_bank_parm_id(e->bank, 0));", PICK),
    _m("pps-255-n", "if (n >= SPCH_PICKS + 1) {", "if (n >= SPCH_PICKS) {", PICK),
    _m("pps-255-shuffle",
       "            spchi_randomize_phrase_picks(ctx->picks + e->start, n);\n", "",
       PICK),
    _m("pps-255-k", "for (k = 0; k < n; k++) {\n                idx",
       "for (k = 1; k < n; k++) {\n                idx", PICK),
    _m("pps-255-and", "if (match_bit(&rec, t) & (uint32_t)mv) {",
       "if (match_bit(&rec, t) | (uint32_t)mv) {", PICK),
    _m("pps-255-last",
       "                    e->cur = (uint8_t)idx;\n                    found = 1;\n",
       "                    e->cur = (uint8_t)idx;\n                    found = 1;\n                    break;\n",
       PICK),
    _m("pps-t", "        t++;\n    }\n    if (found)", "        t += 2;\n    }\n    if (found)",
       PICK),
    _m("pps-found", "    if (found)\n        return 1;", "    if (found)\n        return 2;",
       PICK),
    _m("pps-any", "    if (any)\n        return 0;", "    if (any)\n        return 1;",
       PICK),
    _m("pps-rand", "    r = spchi_rand(e->cnt, e->bank);\n    e->cur = (uint8_t)(e->start + r);\n    return 1;",
       "    r = 0;\n    e->cur = (uint8_t)(e->start + r);\n    return 1;", PICK),
    _m("pps-loop", "while (t < nr && !found) {", "while (t < nr) {", PICK),
    _m("smc-clear", "    spchi_clear_match_parm_value();\n", "", PICK),
    _m("smc-mode", "    if (mode == 1) {\n        spchi_randomize_sentence_picks",
       "    if (mode >= 1) {\n        spchi_randomize_sentence_picks", PICK),
    _m("smc-shuffle", "        spchi_randomize_sentence_picks(sent, ctx);\n", "",
       PICK),
    _m("smc-cnt0", "        if (e->cnt == 0) {", "        if (e->cnt == 1) {", PICK),
    _m("smc-pps",
       "        if (!spchi_pick_phrase_sample(ctx, phrase_at(sent, i), e))\n            return 0;",
       "        spchi_pick_phrase_sample(ctx, phrase_at(sent, i), e);", PICK),
    _m("crs-255", "            if (ph[12 + j] == 255)",
       "            if (ph[12 + j] >= 254)", PICK),
    _m("crs-rid", "rid = spchi_get_rule_id(ev, ph[12 + j]);", "rid = ph[12 + j];",
       PICK),
    _m("crs-ps", "const SpchPart *part = &gSpch.choice.parts[i + ps];",
       "const SpchPart *part = &gSpch.choice.parts[i];", PICK),
    _m("crs-value", "(int32_t)(1u << (rec.parms[j] & 31)), d);",
       "(int32_t)rec.parms[j], d);", PICK),
    _m("crs-dat",
       "    spchi_get_dat_id((const uint8_t *)event, &d);\n    for (i = 0; i < nph; i++) {\n        const uint8_t *ph",
       "    for (i = 0; i < nph; i++) {\n        const uint8_t *ph", PICK),
    _m("crs-j", "        for (j = 0; j < 4; j++) {\n            if (ph[12 + j]",
       "        for (j = 0; j < 3; j++) {\n            if (ph[12 + j]", PICK),
    _m("msr-dat",
       "    spchi_get_dat_id((const uint8_t *)event, &d);\n    spchi_find_event_channel",
       "    spchi_find_event_channel", PICK),
    _m("msr-channel", "    spchi_find_event_channel((const uint8_t *)event, &ch);\n",
       "", PICK),
    _m("msr-ps", "const SpchPart *part = &gSpch.choice.parts[ps + i];",
       "const SpchPart *part = &gSpch.choice.parts[i];", PICK),
    _m("msr-clearcycle", "if ((b[4] & 0x80) && gSpch.clearCycle)",
       "if (b[4] & 0x80)", PICK),
    _m("msr-cycle-flag", "if ((b[4] & 0x80) && gSpch.clearCycle)",
       "if (gSpch.clearCycle)", PICK),
    _m("msr-sub-off",
       "off += part->sub * (int32_t)(spch_u16(b + 8) * ((b[7] + 1) << 8));",
       "off += part->sub * (int32_t)(spch_u16(b + 8) << 8);", PICK),
    _m("msr-bank", "req.bank = part->bank;", "req.bank = 0;", PICK),
    _m("msr-offset", "req.offset = off;", "req.offset = rec.offset;", PICK),
    _m("msr-size", "req.size = rec.size;", "req.size = rec.size + 1;", PICK),
    _m("msr-total", "total += rec.size;", "total = rec.size;", PICK),
    _m("msr-event", "req.event = *event;", "req.event = *event & 0xffff;",
       PICK),
    _m("msr-req-channel", "req.channel = ch;", "req.channel = 0;", PICK),
    _m("msr-subbank", "req.subBank = spch_u16(b + 2);",
       "req.subBank = part->sub;", PICK),
    _m("msr-datid", "req.datId = d;", "req.datId = 0;", PICK),
    _m("msr-queue", "        spchi_bank_add_to_queue(b, s);\n", "", PICK),
    _m("msr-ret", "return spchi_convert_time(total);", "return total;", PICK),
    _m("ispi-nph", "    ctx->nph = 0;\n    ctx->numPicks = 0;",
       "    ctx->numPicks = 0;", PICK),
    _m("ispi-numpicks", "    ctx->nph = 0;\n    ctx->numPicks = 0;",
       "    ctx->nph = 0;", PICK),
    _m("isc-channel", "c->channel = -1;", "c->channel = 0;", PICK),
    _m("isc-numchosen", "c->numChosen = 0;", "c->numChosen = 1;", PICK),
    _m("isc-numparts", "c->numParts = 0;", "c->numParts = 1;", PICK),
    _m("isc-ev", "        c->chosen[i].ev = NULL;\n", "", PICK),
    _m("isc-sent", "        c->chosen[i].sent = NULL;\n", "", PICK),
    _m("isc-sentidx", "        c->chosen[i].sentIdx = 0;\n", "", PICK),
    _m("isc-valid", "        c->chosen[i].valid = 0;\n", "", PICK),
    _m("isc-part-bank", "c->parts[i].bank = -1;", "c->parts[i].bank = 0;",
       PICK),
    _m("isc-part-sub", "c->parts[i].sub = -1;", "c->parts[i].sub = 0;", PICK),
    _m("isc-part-sample", "c->parts[i].sample = 0;", "c->parts[i].sample = 1;",
       PICK),
    _m("isc-parts-n", "for (i = 0; i < SPCH_PARTS; i++) {",
       "for (i = 0; i < SPCH_PARTS - 1; i++) {", PICK),
    _m("scs-channel", "if (c->channel >= 0 && c->channel != channel) {",
       "if (c->channel > 0 && c->channel != channel) {", PICK),
    _m("scs-channel-ret", 'channel mismatch.");\n        return;',
       'channel mismatch.");', PICK),
    _m("scs-toomany", "    if (t >= SPCH_CHOSEN) {", "    if (t > SPCH_CHOSEN) {",
       PICK),
    _m("scs-parts", "if (c->numParts + nph > SPCH_PARTS) {",
       "if (c->numParts + nph >= SPCH_PARTS) {", PICK),
    _m("scs-channel-set", "    c->channel = channel;\n    s = &c->chosen[t];",
       "    s = &c->chosen[t];", PICK),
    _m("scs-idx", "s->sentIdx = (uint8_t)idx;", "s->sentIdx = 0;", PICK),
    _m("scs-parms", "memcpy(s->parms, req, sizeof(s->parms));",
       "memcpy(s->parms, req, sizeof(s->parms) - 4);", PICK),
    _m("scs-valid", "    s->valid = 1;", "    s->valid = 0;", PICK),
    _m("scs-part-bank", "p->bank = ctx->e[i].bank;", "p->bank = ctx->e[0].bank;",
       PICK),
    _m("scs-part-sub", "p->sub = ctx->e[i].sub;", "p->sub = -1;", PICK),
    _m("scs-part-sample", "p->sample = ctx->picks[ctx->e[i].cur];",
       "p->sample = ctx->picks[ctx->e[i].start];", PICK),
    _m("scs-numparts", "c->numParts += nph;", "c->numParts += 1;", PICK),
    _m("oc-channel",
       "return gSpch.choice.channel == channel && gSpch.choice.numChosen > 0;",
       "return gSpch.choice.numChosen > 0;", PICK),
    _m("oc-count",
       "return gSpch.choice.channel == channel && gSpch.choice.numChosen > 0;",
       "return gSpch.choice.channel == channel;", PICK),
    _m("pc-none", "    if (!spchi_one_chosen(channel)) {\n        spchi_init_sentence_choice();",
       "    if (!spchi_one_chosen(channel)) {", PICK),
    _m("pc-cap", "    if (n > SPCH_CHOSEN)\n        n = SPCH_CHOSEN;\n", "", PICK),
    _m("pc-word", "uint32_t w = s->parms[0];", "uint32_t w = s->parms[1];", PICK),
    _m("pc-ruleset", "        spchi_rule_set(&w, s->ev, s->sentIdx, s->parms);\n",
       "", PICK),
    _m("pc-construle", "        spchi_constant_rule_set(&w, s->ev, s->sent, ps);\n",
       "", PICK),
    _m("pc-requests", "        spchi_make_sample_requests(s->sent, &w, ps);\n", "",
       PICK),
    _m("pc-ps", "ps += s->sent[3] >> 2;", "ps += 1;", PICK),
    _m("pc-first", "        if (i == 0) {\n            SpchInGame",
       "        if (i >= 0) {\n            SpchInGame", PICK),
    _m("pc-same", "if ((uint16_t)w == (uint16_t)g->word)", "if (w == g->word)",
       PICK),
    _m("pc-word-set", "                g->word = w;\n", "", PICK),
    _m("pc-count1", "                g->count = 1;", "                g->count = 0;",
       PICK),
    _m("pc-isc", "    spchi_init_sentence_choice();\n    return ps;",
       "    return ps;", PICK),
    _m("tvp-shift", "switch ((mask >> ((uint32_t)(2 * i) & 31)) & 3) {",
       "switch ((mask >> ((uint32_t)i & 31)) & 3) {", PICK),
    _m("tvp-1", "        return v != 0;", "        return v > 0;", PICK),
    _m("tvp-2", "        return v != -1;", "        return v >= 0;", PICK),
    _m("tvp-3", "    }\n    return 0;\n}\n\n// A sentence for the event",
       "    }\n    return 1;\n}\n\n// A sentence for the event", PICK),
    _m("csn-noevent", "    if (ev == NULL)\n        return 0;\n    if (!spchi_find_event_channel",
       "    if (ev == NULL)\n        return -1;\n    if (!spchi_find_event_channel",
       PICK),
    _m("csn-repeat", "    if (!spchi_repeat_event(ev, ch))\n        return 0;\n", "",
       PICK),
    _m("csn-filter-ch", "f = gSpch.filter[ch];", "f = gSpch.filter[0];", PICK),
    _m("csn-bump-cap", "if (gSpch.queue.bumpFilter == 1 && ++f >= 3)",
       "if (gSpch.queue.bumpFilter == 1 && ++f > 3)", PICK),
    _m("csn-bump-inc", "if (gSpch.queue.bumpFilter == 1 && ++f >= 3)",
       "if (gSpch.queue.bumpFilter == 1 && f >= 3)", PICK),
    _m("csn-filterable", "if (!(ev[10] & 1) && f == 1)", "if (f == 1)", PICK),
    _m("csn-filterable-f", "if (!(ev[10] & 1) && f == 1)",
       "if (!(ev[10] & 1) && f >= 1)", PICK),
    _m("csn-flen", "fl = spchi_get_filter_length((const uint8_t *)&w);",
       "fl = spchi_get_filter_length((const uint8_t *)&w) * 2;", PICK),
    _m("csn-grs", "rs = spchi_get_rule_settings(&w, ev, req, &fb);",
       "rs = spchi_get_rule_settings(&w, ev, req, &fb) | 1;", PICK),
    _m("csn-none", "    if (n <= 0)\n        return -1;",
       "    if (n <= 0)\n        return 0;", PICK),
    _m("csn-mask-flag", "    if (ev[10] & 8) {\n        mp =",
       "    if (ev[10] & 4) {\n        mp =", PICK),
    _m("csn-mask-at", "(((int8_t)ev[7] * 3 + 3) & ~3);",
       "(((int8_t)ev[7] * 3) & ~3);", PICK),
    _m("csn-mask-16", "for (i = 0, bit = 1; i < 16; i++, bit <<= 1)",
       "for (i = 0, bit = 1; i < 15; i++, bit <<= 1)", PICK),
    _m("csn-mask-parm", "(int32_t)req[1 + i], i))", "(int32_t)req[i], i))",
       PICK),
    _m("csn-k", "for (k = 0; k < n && r == 0; k++) {",
       "for (k = 0; k < n; k++) {", PICK),
    _m("csn-order", "int32_t s = order[k], g;", "int32_t s = k, g;", PICK),
    _m("csn-valid", "spch_u16(mp + 4 + 2 * s) != valid",
       "spch_u16(mp + 4 + 2 * s) > valid", PICK),
    _m("csn-valid-at", "spch_u16(mp + 4 + 2 * s) != valid",
       "spch_u16(mp + 2 + 2 * s) != valid", PICK),
    _m("csn-ispi", "        spchi_init_sentence_pick_info(&ctx);\n", "", PICK),
    _m("csn-g", "        if (g > 0) {", "        if (g >= 0) {", PICK),
    _m("csn-save", "            if (r)\n                spchi_save_chosen_sentence",
       "            if (0)\n                spchi_save_chosen_sentence", PICK),
    _m("csn-save-idx", "spchi_save_chosen_sentence(&ctx, ch, ev, sent, s, req);",
       "spchi_save_chosen_sentence(&ctx, ch, ev, sent, k, req);", PICK),
    _m("css1-r0", "if (r == 0 && gSpch.reparm != NULL)",
       "if (r <= 0 && gSpch.reparm != NULL)", PICK),
    _m("css1-k", "s = gSpch.reparm(k, p);", "s = gSpch.reparm(0, p);", PICK),
    _m("css1-s", "            if (s >= 0)\n                r =",
       "            if (s > 0)\n                r =", PICK),
    _m("css1-break-r", "if (r != 0 || s <= 0)", "if (s <= 0)", PICK),
    _m("css1-ret", "return r > -1 ? r : 0;", "return r;", PICK),
    _m("preload", "gSpch.preLoadTicks = ticks;", "gSpch.preLoadTicks = ticks / 2;",
       PICK),

    # ---- spchrule.c
    _m("rules-at", "return ev + 12 + ((ev[6] * 2 + 3) & 0x3fc);",
       "return ev + 12 + ((ev[6] * 2 + 1) & 0x3fc);", RULE),
    _m("sup-nph", "int32_t nph = sent[3] >> 2, i, j;",
       "int32_t nph = (sent[3] >> 2) - 1, i, j;", RULE),
    _m("sup-phrase", "const uint8_t *ph = sent + sent[4 + i] * 4;",
       "const uint8_t *ph = sent + sent[4] * 4;", RULE),
    _m("sup-sparm", "        if (ph[2] == p)", "        if (ph[3] == p)", RULE),
    _m("sup-j", "for (j = 0; j < 4; j++)\n            if (ph[8 + j] == p)",
       "for (j = 0; j < 3; j++)\n            if (ph[8 + j] == p)", RULE),
    _m("sup-ref", "if (ph[8 + j] == p)", "if (ph[12 + j] == p)", RULE),
    _m("gri-oob", "    if (i >= 8) {", "    if (i >= 9) {", RULE),
    _m("gri-oob-ret", 'ruleindex out of bounds.");\n        return -1;',
       'ruleindex out of bounds.");\n        return 0;', RULE),
    _m("gri-id", "return event_rules(ev)[3 * i];",
       "return event_rules(ev)[3 * i + 1];", RULE),
    _m("rs-dat", "    spchi_get_dat_id((const uint8_t *)event, &d);\n    sent =",
       "    sent =", RULE),
    _m("rs-sentence", "sent = ev + spch_u16(ev + 12 + 2 * si) * 4;",
       "sent = ev + spch_u16(ev + 12) * 4;", RULE),
    _m("rs-n", "    n = (int8_t)ev[7];", "    n = (int8_t)ev[7] - 1;", RULE),
    _m("rs-type3", "if (r[2] != 0 && r[2] != 3)", "if (r[2] != 0)", RULE),
    _m("rs-type0", "if (r[2] != 0 && r[2] != 3)", "if (r[2] != 3)", RULE),
    _m("rs-uses", "if (spchi_sentence_uses_parm(sent, parm))", "if (1)", RULE),
    _m("rs-id", "gSpch.ruleSet(event, r[0],", "gSpch.ruleSet(event, r[1],",
       RULE),
    _m("rs-value20", "(int32_t)(parm < SPCH_EVENT_PARMS ? parms[parm] : 0), d);",
       "(int32_t)(parm < SPCH_EVENT_PARMS ? parms[parm] : 1), d);", RULE),
    _m("rs-parm", "uint32_t parm = r[1];", "uint32_t parm = r[0];", RULE),
    _m("grs-p20", "for (p = 1; p <= SPCH_EVENT_PARMS; p++) {",
       "for (p = 1; p < SPCH_EVENT_PARMS; p++) {", RULE),
    _m("grs-p1", "for (p = 1; p <= SPCH_EVENT_PARMS; p++) {",
       "for (p = 2; p <= SPCH_EVENT_PARMS; p++) {", RULE),
    _m("grs-last-value", "                value = 0;", "                value = 1;",
       RULE),
    _m("grs-last-skip", "                if (r[1] != 0)\n                    continue;",
       "                if (0)\n                    continue;", RULE),
    _m("grs-parm", "                if (r[1] != p)\n                    continue;",
       "                if (r[1] > p)\n                    continue;", RULE),
    _m("grs-value", "value = (int32_t)req[p];", "value = (int32_t)req[p - 1];",
       RULE),
    _m("grs-bit", "bit = (1u << ((uint32_t)(7 - j) & 31)) & 0xff;",
       "bit = (1u << ((uint32_t)(7 - j) & 7)) & 0xff;", RULE),
    _m("grs-bit-order", "bit = (1u << ((uint32_t)(7 - j) & 31)) & 0xff;",
       "bit = (1u << ((uint32_t)j & 31)) & 0xff;", RULE),
    _m("grs-type4", "            if (r[2] == 4) {", "            if (r[2] == 3) {",
       RULE),
    _m("grs-type4-req", "                if (req[r[1]] != 0)",
       "                if (value != 0)", RULE),
    _m("grs-nocb", "? gSpch.ruleTest(event, r[0], value, d) : -1;",
       "? gSpch.ruleTest(event, r[0], value, d) : 0;", RULE),
    _m("grs-cb-id", "gSpch.ruleTest(event, r[0], value, d)",
       "gSpch.ruleTest(event, r[1], value, d)", RULE),
    _m("grs-cb-dat", "gSpch.ruleTest(event, r[0], value, d)",
       "gSpch.ruleTest(event, r[0], value, 0)", RULE),
    _m("grs-pos", "                if (v > 0)\n                    s2 = bit;",
       "                if (v >= 0)\n                    s2 = bit;", RULE),
    _m("grs-neg", "                else if (v < 0)\n                    fb |= bit;",
       "                else\n                    fb |= bit;", RULE),
    _m("grs-res", "res = (res | s2) & 0xff;", "res = s2;", RULE),
    _m("grs-fb", "*outFb = (uint8_t)fb;", "*outFb = 0;", RULE),
    _m("grs-dat", "    spchi_get_dat_id((const uint8_t *)event, &d);\n    for (p = 1;",
       "    for (p = 1;", RULE),
    _m("csr-fb", "return ((sent[2] ^ (a & 0xff)) & sent[1] & ~(b & 0xff)) == 0;",
       "return ((sent[2] ^ (a & 0xff)) & sent[1]) == 0;", RULE),
    _m("csr-mask", "return ((sent[2] ^ (a & 0xff)) & sent[1] & ~(b & 0xff)) == 0;",
       "return ((sent[2] ^ (a & 0xff)) & ~(b & 0xff)) == 0;", RULE),
    _m("csr-values", "return ((sent[2] ^ (a & 0xff)) & sent[1] & ~(b & 0xff)) == 0;",
       "return ((sent[1] ^ (a & 0xff)) & sent[1] & ~(b & 0xff)) == 0;", RULE),
    _m("rand-c1", "c = a < s[5] || a < s[4];", "c = a < s[5];", RULE),
    _m("rand-c2", "    c = a < old;\n    s[3] = a;", "    c = 0;\n    s[3] = a;",
       RULE),
    _m("rand-c3", "    c = a < old;\n    s[2] = a;", "    c = 0;\n    s[2] = a;",
       RULE),
    _m("rand-c4", "    c = a < old;\n    s[1] = a;", "    c = 0;\n    s[1] = a;",
       RULE),
    _m("rand-s5", "    s[5]++;\n", "", RULE),
    _m("rand-s0", "a = a + s[0] + c;", "a = a + s[0];", RULE),
    _m("rand-wrap", "if (s[5] == 0 && ++s[4] == 0", "if (s[5] == 1 && ++s[4] == 0",
       RULE),
    _m("rand-wrap-s3", "++s[4] == 0 && ++s[3] == 0", "++s[4] == 0 && s[3] == 0",
       RULE),
    _m("rand-wrap-ret", "        a = ++s[0];", "        a = s[0];", RULE),
    _m("seed-0", "s[0] = x + 0xf22d0e56u;", "s[0] = x + 0xf22d0e57u;", RULE),
    _m("seed-1", "s[1] = s[0] + 0x96041893u;", "s[1] = s[0] + 0x96041892u;",
       RULE),
    _m("seed-2", "s[2] = s[1] + 0x3df3b646u;", "s[2] = s[1] + 0x3df3b647u;",
       RULE),
    _m("seed-3", "s[3] = s[2] + 0x40dde76du;", "s[3] = s[1] + 0x40dde76du;",
       RULE),
    _m("seed-4", "s[4] = s[3] + 0x97327ae1u;", "s[4] = s[3] + 0x97327ae0u;",
       RULE),
    _m("seed-5", "s[5] = s[4] + 0xd1a9fbe7u;", "s[5] = s[4] + 0xd1a9fbe6u;",
       RULE),
    _m("friq-n", "    if (n >= SPCH_RAND_QUEUE + 1)\n        n = SPCH_RAND_QUEUE;",
       "    if (n >= SPCH_RAND_QUEUE)\n        n = SPCH_RAND_QUEUE - 1;", RULE),
    _m("friq-val", "    val &= 0xffff;\n", "", RULE),
    _m("friq-key", "    key &= 0xffff;\n", "", RULE),
    _m("friq-it", "for (it = 0; it < SPCH_RAND_QUEUE + 1; it++) {",
       "for (it = 0; it < SPCH_RAND_QUEUE; it++) {", RULE),
    _m("friq-cnt", "        if (cnt >= n)\n            break;",
       "        if (cnt > n)\n            break;", RULE),
    _m("friq-k", "if (gSpch.randArr[j].key == key) {", "if (1) {", RULE),
    _m("friq-ret", "return cnt - 1;", "return cnt;", RULE),
    _m("friq-wrap", "            j += SPCH_RAND_QUEUE;",
       "            j += SPCH_RAND_QUEUE - 1;", RULE),
    _m("friq-none", "    return -1;\n}\n\nvoid spchi_add_rand_to_queue",
       "    return -2;\n}\n\nvoid spchi_add_rand_to_queue", RULE),
    _m("arq-wrap", "if (++gSpch.randIndex >= SPCH_RAND_QUEUE)",
       "if (++gSpch.randIndex >= SPCH_RAND_QUEUE - 1)", RULE),
    _m("arq-val", "gSpch.randArr[gSpch.randIndex].val = (uint16_t)v;",
       "gSpch.randArr[gSpch.randIndex].val = (uint16_t)(v + 1);", RULE),
    _m("arq-key", "gSpch.randArr[gSpch.randIndex].key = (uint16_t)key;",
       "gSpch.randArr[gSpch.randIndex].key = 0;", RULE),
    _m("ir-val", "gSpch.randArr[i].val = 0xffff;", "gSpch.randArr[i].val = 0;",
       RULE),
    _m("ir-key", "gSpch.randArr[i].key = 0xffff;", "gSpch.randArr[i].key = 0;",
       RULE),
    _m("ir-index", "    gSpch.randIndex = 0;" + NL + "    spchi_eac",
       "    gSpch.randIndex = 1;" + NL + "    spchi_eac", RULE),
    _m("ir-seed", "spchi_eac_seed_random((uint32_t)game + ((uint32_t)game << 16));",
       "spchi_eac_seed_random((uint32_t)game);", RULE),
    _m("randin", "return ((spchi_eac_random() >> 16) * (uint32_t)range) >> 16;",
       "return ((spchi_eac_random() >> 15) * (uint32_t)range) >> 17;", RULE),
    _m("rand-m", "int32_t m = range / 2, q, bq = -1, tries = 0;",
       "int32_t m = range / 3, q, bq = -1, tries = 0;", RULE),
    _m("rand-m10", "    if (m >= 11)\n        m = 10;",
       "    if (m >= 10)\n        m = 9;", RULE),
    _m("rand-key", "uint32_t k = (uint32_t)key & 0xffff, s1, s0;",
       "uint32_t k = (uint32_t)key & 0xff, s1, s0;", RULE),
    _m("rand-first", "    s1 = rand_in(range);\n", "    s1 = 0;\n", RULE),
    _m("rand-fresh", "        if (q == -1) {\n            s1 = s0;\n",
       "        if (q == -1) {\n", RULE),
    _m("rand-bq", "        if (bq < q) {", "        if (bq <= q) {", RULE),
    _m("rand-bq-s1", "            bq = q;\n            s1 = s0;",
       "            bq = q;", RULE),
    _m("rand-tries", "if (++tries >= 32)", "if (++tries >= 31)", RULE),
    _m("rand-queue", "spchi_add_rand_to_queue(s1, k);",
       "spchi_add_rand_to_queue(s0, k);", RULE),
    _m("rand-ret", "return (int32_t)s0;", "return (int32_t)s1;", RULE),

    # ---- spchi.h
    _m("hdr-u16", "return (uint16_t)(p[0] | (p[1] << 8));",
       "return (uint16_t)(p[0] | (p[1] << 7));", SPCHI),
    _m("hdr-u32", "| ((uint32_t)p[3] << 24);", "| ((uint32_t)p[3] << 23);",
       SPCHI),
    _m("hdr-u32-b2", "((uint32_t)p[2] << 16)", "((uint32_t)p[2] << 15)", SPCHI),
    _m("hdr-cycle-es", "uint32_t es = (b[4] & 0xfu) + 2;",
       "uint32_t es = (b[4] & 0xfu) + 1;", SPCHI),
    _m("hdr-cycle-ids", "((b[4] & 0x70u) >> 3)", "((b[4] & 0x70u) >> 4)",
       SPCHI),
    _m("hdr-queue", "c + ((b[5] + 7) >> 3) + 1 : c;", "c + ((b[5] + 7) >> 3) : c;",
       SPCHI),
    _m("hdr-queue-flag", "return (b[4] & 0x80) ? c", "return (b[4] & 0x40) ? c",
       SPCHI),
    _m("hdr-slots", "#define SPCH_SLOTS       16", "#define SPCH_SLOTS       15",
       SPCHI),
    _m("hdr-randq", "#define SPCH_RAND_QUEUE  32", "#define SPCH_RAND_QUEUE  31",
       SPCHI),
    _m("hdr-picks", "#define SPCH_PICKS       100", "#define SPCH_PICKS       99",
       SPCHI),
]

EQUIVALENT = {
    "rand-c1": "a = s5 + s4 wraps exactly when a < s5, and then a < s4 too",
    "friq-it": "the 33rd pass revisits the newest slot, which the first "
               "pass returned for if it matched",
    "rand-bq": "two tries at the same distance back are the same value, the "
               "first match from the newest fixing the distance",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines = script()
    scp = write_script(indir.name, lines)
    base = model_cached(lines)
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
    result = mutpar.run_pass(
        todo, SOURCES, "spch_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, result)


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

    lines = script()
    got, e = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
