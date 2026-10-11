#!/usr/bin/env python3
"""Cross-check 3DS Files/source/eventrace.c, the races an event sets
(RE-6c), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: EventTrack::SetRace (0x001fec20) and
SetFromRace (0x001fed30), EventTree::SetRace (0x001fee20), and the
description's GetEventDescriptionToken (0x001f5d58),
FormatEventDescriptionToken (0x001f5dd0) and FormatEventDescription
(0x001f5f88), on TheRaceEvent (0x0031b600), TheRaceParameters (0x0031a898)
and Fred (0x002fc050). Under them run the rest of EventTree.obj (the
loader, the states, the EventInfo getters), RaceEvent::ResetResults,
CarTypeInfo::GetShortName, GetTheRightTrackLanguageID and bWare's string
functions and bSPrintf. The harness (tools/src/eventrace_test.c) runs the
port and prints the same lines.

**The data** is tools/eventtree_check.py's: the disc's two event trees
from FRONTB.BUN and the trees made up there.

**The stubs**, logged and answered by the same rule on both sides:
bMalloc and bFree (eventtree_check's), GetTranslatedString by id (a text
the script gives the id, else "S" and the id), GetTranslatedString by text
("Q" and its first 20 characters), GetTrackInfo (a table of 40 made-up
tracks, NULL past it), Timer::PrintToString ("T" and the time, after two
spaces for a time divisible by 3) and bRandom (a queue, then an answer).
The car types are a table of 256, each one's FullName 5000 and its type.
bMemCpy is native.

**Compared** are the stubs' logs and, after each SetRace, the tree's
current event, Fred's nCurrentEvent, TheRaceEvent from aOldState on, the
event's state, and TheRaceParameters up to its driver table with the
words after it; after EventTrack's two, the race parameters' head and the
word; the token found; and each description made.

**What the script keeps away from**, where retail writes past what it owns
and the port stops (eventrace.c says where): an event whose counts run
past TheRaceEvent's arrays (20 cars, 8 tracks, 8 rewards, 7 opponents), a
race knockout or tournament without a state, a translated name of 32
characters or more, a description that fills its buffer (the port's text
is retail's cut one short, so the `fmt` lines cut retail's to n - 1), and
n <= 0. Both sides print "skip" for the events.

    python tools/eventrace_check.py
    python tools/eventrace_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eventtree_check as etc           # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/eventrace_test.c"
ER = "3DS Files/source/eventrace.c"
SOURCES = [HARNESS, ER, etc.ET, "3DS Files/source/raceevent.c",
           "3DS Files/source/raceparams.c", "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 120
DATA_FILES = etc.DATA_FILES

# ================================================================ the image

GP = retail_model.RETAIL_GP
TRE = 0x0031b600                        # TheRaceEvent
RP = 0x0031a898                         # TheRaceParameters
FRED = etc.FRED
F_CUREVENT = 0x10730                    # Fred.nCurrentEvent
CT_ARRAY = GP - 20616                   # CarTypeInfoArray
TOKENS = 0x0031b200
NTRACKS = 40
TEXT = 1100
P2P = (0, 1, -1, 2)

S_TRS = 0x0021e508
S_TRACKINFO = 0x00153420
S_MEMCPY = 0x00250288

F_TRACK = 0x001fec20
F_FROM = 0x001fed30
F_SETRACE = 0x001fee20
F_TOK = 0x001f5d58
F_FTOK = 0x001f5dd0
F_FMT = 0x001f5f88

NAMES = ("$TARGET_TIME", "$NUM_LAPS", "$NUM_OPPONENTS", "$NUM_RACES",
         "$EVENTS_UNLOCKED", "$COMPLETION_TIME", "$EVENT_UNLOCKED",
         "$TRACK_NAME")
s8 = etc.s8


# ================================================================== model

class Model(etc.Model):
    def __init__(self, data):
        etc.Model.__init__(self, data)
        e = self.e

        def block(n):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            return p
        self.texts = [block(TEXT) for _ in range(8)]
        self.ktext = 0
        self.descs = {}
        self.ct = block(256 * 1376)
        self.specs = block(256 * 32)
        e.put32(CT_ARRAY, self.ct)
        for i in range(256):
            e.put32(self.ct + 1376 * i + 1368, self.specs + 32 * i)
            e.put32(self.specs + 32 * i + 20, 5000 + i)
        self.tinfo = block(NTRACKS * 164)
        for i in range(NTRACKS):
            t = self.tinfo + 164 * i
            e.write(t + 67, bytes([P2P[i & 3] & 0xff]))
            e.put32(t + 72, 3000 + 2 * i)
            e.put32(t + 76, 3001 + 2 * i)
        self.src = block(1024)
        self.buf = block(1040)
        self.word = block(16)
        self.tok = block(16)
        self.tokname = block(16)
        e.write(self.tokname, b"$X\0")

        def memcpy(em):
            d, s, n = (em.reg[r] & M32 for r in (4, 5, 6))
            em.mem[d:d + n] = em.mem[s:s + n]
            return d
        for addr, fn in ((etc.S_TR, self.s_tr2), (S_TRS, self.s_trs),
                         (S_TRACKINFO, self.s_trackinfo),
                         (etc.S_TIMER, self.s_timer2), (S_MEMCPY, memcpy)):
            e.stub(addr, fn)

    def cstr(self, a):
        e = self.e
        s = bytearray()
        while e.mem[a] != 0 and len(s) < 2048:
            s.append(e.mem[a])
            a += 1
        return s.decode("latin-1")

    def P(self, a):
        a &= M32
        if TOKENS <= a < TOKENS + 64:
            return "K%d" % ((a - TOKENS) // 8)
        return etc.Model.P(self, a)

    # ---- stubs

    def text(self, s):
        p = self.texts[self.ktext & 7]
        self.ktext += 1
        self.e.write(p, s.encode("latin-1")[:TEXT - 1] + b"\0")
        return p

    def s_tr2(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %d" % i)
        return self.text(self.descs.get(i, "S%d" % i))

    def s_trs(self, em):
        s = self.cstr(em.reg[4] & M32)
        self.emit("  trs %s" % s)
        return self.text("Q" + s[:20])

    def s_trackinfo(self, em):
        i = s32(em.reg[4])
        self.emit("  trackinfo %d" % i)
        return self.tinfo + 164 * i if 0 <= i < NTRACKS else 0

    def s_timer2(self, em):
        t = s32(self.e.u32(em.reg[4] & M32))
        self.emit("  timer %d %d" % (t, s32(em.reg[6])))
        em.write(em.reg[5] & M32, (("  " if t % 3 == 0 else "")
                                   + "T%d" % t).encode() + b"\0")
        return 0

    # ---- printing

    def rp_dump(self):
        e = self.e
        self.emit("  rp0 " + e.read(RP, 84).hex())
        self.emit("  obj " + self.cstr(RP + 84))
        self.emit("  objx " + e.read(RP + 84, 512).hex())
        self.emit("  rp1 %s %d %d %d" % (
            e.read(RP + 596, 176).hex(), s32(e.u32(RP + 776)),
            s32(e.u32(RP + 780)), s32(e.u32(RP + 784))))

    def ev_dump(self, t, ev):
        e, P = self.e, self.P
        s = e.u32(ev + 4)
        self.emit("  cur %s ce %d" % (P(e.u32(t + 92)),
                                      s32(e.u32(FRED + F_CUREVENT))))
        self.emit("  ev %s %s %s" % (P(e.u32(TRE)), P(e.u32(TRE + 4)),
                                     e.read(TRE + 8, 96).hex()))
        self.emit("  ev1 " + e.read(TRE + 104, 328).hex())
        self.emit("  st " + ("-" if s == 0 else e.read(s, 16).hex()))

    # ---- ops

    def run(self, a):
        e, P = self.e, self.P
        o = a[0]
        i = (lambda j: s32(int(a[j], 0)))   # noqa: E731
        if o == "desc":
            if a[1] == "clr":
                self.descs = {}
            elif i(1) not in self.descs and len(self.descs) < 64:
                self.descs[i(1)] = a[2]
        elif o == "rpfill":
            n = i(1)
            e.write(RP, bytes((n + 7 * k) & 0xff for k in range(772)))
            e.put32(RP + 776, (n * 101) & M32)
            e.put32(RP + 780, (n * 103) & M32)
            e.put32(RP + 784, (n * 107) & M32)
        elif o == "evfill":
            n = i(1)
            e.put32(TRE, 0)
            e.put32(TRE + 4, 0)
            e.write(TRE + 8, bytes((n + 3 * k) & 0xff for k in range(424)))
        elif o == "set":
            t = self.tree_at(i(1))
            ev = self.B + i(2)
            line = "set %s %s" % (P(t), P(ev))
            typ = s8(e.u8(ev + 41))
            if (s8(e.u8(ev + 59)) > 20 or s8(e.u8(ev + 60)) > 8
                    or s8(e.u8(ev + 62)) > 8 or s8(e.u8(ev + 63)) > 7
                    or (typ in (3, 4) and e.u32(ev + 4) == 0)):
                self.emit(line + " skip")
                return
            self.emit(line)
            b596 = e.u8(RP + 596)
            self.call(F_SETRACE, t, RP, ev)
            if 0 not in e.read(TRE + 72, 32):
                # bStrNCpy's 32 characters and no NUL; the port's name is
                # cut to 31.
                e.write(TRE + 72 + 31, b"\0")
            if 0 not in e.read(RP + 84, 512):
                # The text filled sObjective and retail's NUL went to
                # NFSRaceMode (rp+596); the port's text is cut one short.
                e.write(RP + 84 + 511, b"\0")
                e.write(RP + 596, bytes([b596]))
            self.ev_dump(t, ev)
            self.rp_dump()
        elif o == "track":
            w = int(a[1], 0) & M32
            e.put32(self.word, w)
            self.emit("track %08x" % w)
            self.call(F_TRACK, self.word, RP)
            self.emit("  rp0 " + e.read(RP, 84).hex())
        elif o == "from":
            w = int(a[1], 0) & M32
            d, c = int(a[6], 0) & M32, int(a[7], 0) & M32
            e.put32(self.word, w)
            for off, j in ((0, 2), (4, 3), (8, 4), (12, 5), (44, 8)):
                e.put32(RP + off, i(j) & M32)
            e.put32(RP + 16, d)
            e.put32(RP + 20, c)
            self.call(F_FROM, self.word, RP)
            self.emit("from %08x %d %d %d %d %08x %08x %d -> %08x" % (
                w, i(2), i(3), i(4), i(5), d, c, i(8), e.u32(self.word)))
        elif o == "tok":
            e.write(self.src, a[1].encode() + b"\0")
            self.emit("tok %s -> %s" % (a[1], P(self.call(F_TOK, self.src))))
        elif o == "ftok":
            t = self.tree_at(i(1))
            ev = self.B + i(2)
            k = i(3)
            if 0 <= k < 8:
                tok = TOKENS + 8 * k
            else:
                tok = self.tok
                e.put32(tok, k & M32)
                e.put32(tok + 4, self.tokname)
            e.write(self.buf, b"~unchanged~\0")
            self.emit("ftok %s %s %d" % (P(t), P(ev), k))
            self.call(F_FTOK, t, ev, tok, self.buf)
            self.emit("  -> " + self.cstr(self.buf))
        elif o == "fmt":
            t = self.tree_at(i(1))
            ev = self.B + i(2)
            n = i(3)
            e.write(self.src, a[4].encode() + b"\0")
            e.write(self.buf, b"\xaa" * 1040)
            self.emit("fmt %s %s %d %s" % (P(t), P(ev), n, a[4]))
            self.call(F_FMT, t, ev, self.src, self.buf, n)
            # The port's text is retail's cut to n - 1.
            self.emit("  -> " + self.cstr(self.buf)[:max(n - 1, 0)])
        else:
            etc.Model.run(self, a)


def model(lines, data):
    m = Model(data)
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

PIECES = NAMES + ("Win ", "the race ", "in under ", " laps", "$", "$$",
                  "$NUM", "$num_laps", "$TRACK_NAMES", "x", " ", "$EVENT_",
                  "100%", "%d", "  ", "$TARGET_TIME$NUM_LAPS",
                  "$EVENTS_UNLOCKED!", "Beat ", " opponents.")


def template(r, most=12):
    return "".join(r.choice(PIECES) for _ in range(r.randint(0, most)))


def word(r):
    """An EventTrack's word: every field over its range, and garbage."""
    k = r.random()
    if k < 0.3:
        return r.getrandbits(32)
    w = r.choice([r.randint(0, 45), r.randint(0, 255)])
    w |= r.getrandbits(1) << 8
    w |= r.getrandbits(1) << 9
    w |= r.randint(0, 3) << 10
    w |= r.randint(0, 3) << 12
    w |= r.randint(0, 15) << 14
    w |= r.choice([0, 100, 127, r.randint(0, 127)]) << 18
    w |= r.choice([0, 50, 100, 127, r.randint(0, 127)]) << 25
    return w


def fbits(r):
    f = r.choice([0.0, 0.01, 0.25, 0.5, 0.99, 1.0, 1.27, 1.28, 2.0, -0.01,
                  -0.5, -1.0, 0.0049, 0.0051, 0.333, 1e9, -1e9, 3.4e38,
                  -3.4e38, r.uniform(0, 1.3), r.uniform(-2, 2),
                  r.randint(0, 127) / 100.0])
    return struct.unpack("<I", struct.pack("<f", f))[0]


def token_cases():
    out = []
    for nm in NAMES:
        out += ["tok|" + nm, "tok|" + nm + "x", "tok|" + nm[:-1],
                "tok|" + nm.lower(), "tok|x" + nm]
    for s in ("", "$", "$$", "$NUM", "$NUM_", "$EVENT", "$EVENTS",
              "$EVENT_UNLOCKED", "$EVENTS_UNLOCKED", "$TRACK_NAMES",
              "$TARGET_TIME$NUM_LAPS", "TARGET_TIME", "$ TARGET_TIME",
              "$NUM_OPPONENTSS", "$NUM_RACE"):
        out.append("tok|" + s)
    return out


def track_cases(r):
    out = []
    for w in (0, 0xffffffff, 0x000000ff, 0x00000100, 0x00000200,
              0x00000c00, 0x00003000, 0x0003c000, 0x01fc0000, 0xfe000000,
              0x80000000, 0x7fffffff, 27, 39, 40, 41):
        out += ["rpfill|%d" % (w & 0xff), "track|%d" % w]
    for k in range(400):
        out += ["rpfill|%d" % r.randint(-300, 300), "track|%d" % word(r)]
    for k in range(400):
        out += ["rpfill|%d" % r.randint(0, 255)]
        out.append("from|%d|%d|%d|%d|%d|%d|%d|%d" % (
            word(r), r.choice([r.randint(0, 45), r.randint(-300, 300)]),
            r.choice([r.randint(0, 3), r.randint(-9, 9)]),
            r.choice([r.randint(0, 3), r.randint(-9, 9)]),
            r.choice([0, 1, r.randint(-5, 5)]), fbits(r), fbits(r),
            r.choice([r.randint(0, 15), r.randint(-40, 40)])))
    return out


def ok_counts(ev):
    off, num, typ, nc, nt, ng, nr, no = ev
    return nc <= 20 and nt <= 8 and nr <= 8 and no <= 7


def desc_id(d, ev):
    return struct.unpack_from("<i", d.buf, ev[0] + 180)[0]


def set_round(d, r, k, evs, other=None):
    """SetRace on each event of tree `k`, each with a description of its
    own, after the race parameters and the event are refilled."""
    out = ["desc|clr"]
    for ev in evs:
        out.append("desc|%d|%s" % (desc_id(d, ev), template(r)))
    # Track names (TrackInfo ids 3000 + 2i, 3001 + 2i) up to and past the
    # reward name's 31 characters.
    for _ in range(10):
        out.append("desc|%d|%s" % (r.randint(3000, 3079), "".join(
            r.choice("abcdefgh XYZ") for _ in range(
                r.choice([1, 20, 29, 30, 31, 31, 32, 33, 40, 60])))))
    for ev in evs:
        out += ["rpfill|%d" % r.randint(0, 255),
                "evfill|%d" % r.randint(0, 255),
                "randq|%d" % r.getrandbits(32)]
        tk = k if other is None or r.random() < 0.7 else other
        out.append("set|%d|%d" % (tk, ev[0]))
    return out


def desc_round(r, k, evs, n=None):
    out = []
    for ev in evs:
        for _ in range(2):
            out.append("fmt|%d|%d|%d|%s" % (
                k, ev[0], n if n is not None else r.choice(
                    [1, 2, 3, 5, 8, 13, 20, 40, 64, 100, 300, 511, 512]),
                template(r, 16)))
        # A token's text across the end, then a token that would ask the
        # timer if it were made.
        out.append("fmt|%d|%d|%d|$EVENTS_UNLOCKED$TARGET_TIME" % (
            k, ev[0], r.randint(2, 27)))
        for t in range(-1, 10):
            out.append("ftok|%d|%d|%d" % (k, ev[0], t))
    return out


def real_cases(d, r):
    ch, hp = d.events["ch"], d.events["hp"]
    assert all(ok_counts(ev) for ev in ch + hp)
    out = ["e3|0", "all|0", "fredclr", "ult|0", "load|%d" % d.ch,
           "load|%d" % d.hp]
    out += set_round(d, r, 0, ch) + set_round(d, r, 1, hp)
    for seed in range(6):
        out.append(etc.fred_fill(r))
        for ev in r.sample(ch + hp, 24):
            out.append("ev|put|%d|%s" % (ev[0], etc.state_bytes(r, ev[2])))
        out += set_round(d, r, 0, ch, other=1)
        out += set_round(d, r, 1, hp, other=0)
    # Tournaments whose points sit on a race's boundary, where the count
    # of opponents decides whether this is the first race.
    pts = [10, 6, 4, 3, 2, 1, 0, 0]
    for k, evs in ((0, ch), (1, hp)):
        for ev in evs:
            if ev[2] != 4:
                continue
            no = ev[7]
            for total in (0, 1, sum(pts[:no + 1]) - 1, sum(pts[:no + 1]),
                          sum(pts[:no + 2]) - 1, sum(pts[:no + 2])):
                b = bytearray(r.getrandbits(8) for _ in range(16))
                b[0:8] = bytes(8)
                for j in range(total):
                    b[r.randint(0, 7)] += 1
                out += ["ev|put|%d|%s" % (ev[0], b.hex()),
                        "rpfill|%d" % r.randint(0, 255),
                        "evfill|%d" % r.randint(0, 255),
                        "randq|%d" % r.getrandbits(32),
                        "set|%d|%d" % (k, ev[0])]
    out += desc_round(r, 0, ch) + desc_round(r, 1, hp)
    # Each event's own text, at its full size.
    for k, evs in ((0, ch), (1, hp)):
        out.append("desc|clr")
        for ev in evs:
            out.append("desc|%d|%s" % (desc_id(d, ev), template(r, 30)))
        for ev in evs:
            out += ["rpfill|9", "evfill|9", "set|%d|%d" % (k, ev[0])]
    # Texts that fill sObjective, with tokens and without.
    for k, evs in ((0, ch), (1, hp)):
        out.append("desc|clr")
        for j, ev in enumerate(evs):
            if j % 3 == 0:
                s = "y" * r.choice([509, 510, 511, 512, 513, 700])
            else:
                s = template(r, 150)[:1000]
            out.append("desc|%d|%s" % (desc_id(d, ev), s))
        for ev in evs:
            out += ["rpfill|%d" % r.randint(0, 255),
                    "evfill|%d" % r.randint(0, 255),
                    "randq|%d" % r.getrandbits(32),
                    "set|%d|%d" % (k, ev[0])]
    out += ["unload|%d" % d.ch, "fredclr", "ult|0"]
    return out


def synth_cases(d, r):
    out = []
    # H and D are the E3 trees, which load under bVersionE3.
    for e3, keys in ((0, ("A", "B")), (1, ("H", "D"))):
        out += ["e3|%d" % e3, "fredclr", "ult|0"]
        out += ["load|%d" % d.chunks[k] for k in keys]
        for k, key in enumerate(keys):
            evs = d.events[key]
            out += set_round(d, r, k, evs)
            out.append(etc.fred_fill(r))
            out += set_round(d, r, k, evs)
            out += desc_round(r, k, [ev for ev in evs if ok_counts(ev)][:8])
        out += ["unload|%d" % d.ch]
    out += ["e3|0", "fredclr", "ult|0"]
    return out


def script(d):
    r = random.Random(0x6ec)
    return token_cases() + track_cases(r) + real_cases(d, r) + \
        synth_cases(d, r)


# ================================================================= running

def build_harness(tmp, name="eventrace_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = etc.run_harness
diff = pcc.diff


def write_inputs(tmp):
    d = etc.Data()
    lines = script(d)
    sc = Path(tmp) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    dp = Path(tmp) / "data.bin"
    dp.write_bytes(d.buf)
    return d, lines, sc, dp


def model_cached(lines, buf):
    return mutpar.model_cached(lines, lambda s: model(s, buf),
                               data=DATA_FILES, cut=MUTATIONS_HEADER)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL

# ============================================================ the mutations

def _m(name, old, new, f=ER):
    return (name, f, old, new)


MUTATIONS = [
    # the helpers
    _m("er-word", "| (uint32_t)b[2] << 16", "| (uint32_t)b[2] << 17"),
    _m("er-entry-size", "(intptr_t)idx * (intptr_t)size",
       "(intptr_t)idx * 4"),
    _m("er-copy-31", "if (n > 31)\n        n = 31;",
       "if (n > 30)\n        n = 30;"),
    _m("er-copy-nul", "dst[n] = 0;", "dst[n + 1] = 0;"),
    # EventTrack::SetRace
    _m("er-tr-num", "rp->TrackNumber = t->b[0];",
       "rp->TrackNumber = t->b[1];"),
    _m("er-tr-laps-shift", "rp->NumLapsInRace = (int32_t)(w >> 14 & 0xf);",
       "rp->NumLapsInRace = (int32_t)(w >> 13 & 0xf);"),
    _m("er-tr-laps-mask", "rp->NumLapsInRace = (int32_t)(w >> 14 & 0xf);",
       "rp->NumLapsInRace = (int32_t)(w >> 14 & 0x7);"),
    _m("er-tr-weather", "(int32_t)(w >> 10 & 3)", "(int32_t)(w >> 11 & 3)"),
    _m("er-tr-tod", "(int32_t)(w >> 12 & 3)", "(int32_t)(w >> 12 & 1)"),
    _m("er-tr-dir", "(eTrackDirection)(w >> 9 & 1)",
       "(eTrackDirection)(w >> 8 & 1)"),
    _m("er-tr-dens-mask", "(w >> 18 & 0x7f)", "(w >> 18 & 0x3f)"),
    _m("er-tr-dens-scale", "(int32_t)(w >> 18 & 0x7f) * 0.01f",
       "(int32_t)(w >> 18 & 0x7f) * 0.1f"),
    _m("er-tr-onc", "(int32_t)(w >> 25) * 0.01f", "(int32_t)(w >> 24) * 0.01f"),
    _m("er-tr-ti-arg", "ti = track_get_info(t->b[0]);",
       "ti = track_get_info(t->b[1]);"),
    _m("er-tr-p2p", "if (ti != NULL)\n        rp->Point2Point",
       "if (ti != NULL && ti->Point2Point != 0)\n        rp->Point2Point"),
    # EventTrack::SetFromRace
    _m("er-from-num", "t->b[0] = (uint8_t)rp->TrackNumber;",
       "t->b[0] = 0;"),
    _m("er-from-word", "(uint8_t)rp->TrackNumber;\n    w = track_word(t->b);",
       "(uint8_t)rp->TrackNumber;\n    w = 0;"),
    _m("er-from-laps-mask", "0xfffc3fffu", "0xfff83fffu"),
    _m("er-from-laps-and", "(rp->NumLapsInRace & 0xf) << 14",
       "(rp->NumLapsInRace & 0x7) << 14"),
    _m("er-from-weather", "(rp->TrackWeather & 3) << 10",
       "(rp->TrackWeather & 3) << 11"),
    _m("er-from-tod-mask", "0xffffcfffu", "0xffffefffu"),
    _m("er-from-tod", "(rp->TrackTimeOfDay & 3) << 12",
       "(rp->TrackTimeOfDay & 1) << 12"),
    _m("er-from-dir", "(rp->TrackDirection & 1) << 9",
       "(rp->TrackDirection & 3) << 9"),
    _m("er-from-dir-mask", "0xfffffdffu", "0xffffffffu"),
    _m("er-from-dens-scale", "ee_mul(rp->TrafficDensity, 100.0f)",
       "ee_mul(rp->TrafficDensity, 10.0f)"),
    _m("er-from-dens-mask", "100.0f)) & 0x7f)", "100.0f)) & 0xff)"),
    _m("er-from-dens-clear", "0xfe03ffffu", "0xfe07ffffu"),
    _m("er-from-onc-mask", "0x01ffffffu", "0x03ffffffu"),
    _m("er-from-onc-shift", "100.0f)) << 25", "100.0f)) << 24"),
    _m("er-from-b2", "t->b[2] = (uint8_t)(w >> 16);",
       "t->b[2] = (uint8_t)(w >> 17);"),
    _m("er-from-b3", "t->b[3] = (uint8_t)(w >> 24);",
       "t->b[3] = (uint8_t)(w >> 25);"),
    # EventTree::SetRace: the copy
    _m("er-cur-event", "tree->pCurrentEvent = e;",
       "tree->pCurrentEvent = NULL;"),
    _m("er-fred-cur", "Fred.nCurrentEvent = e->nNumber;",
       "Fred.nCurrentEvent = e->nType;"),
    _m("er-name", "memcpy(ev->sName, e->sName, 32);",
       "memcpy(ev->sName, e->sName, 31);"),
    _m("er-state-size", "kZeros, (size_t)size);",
       "kZeros, (size_t)size - 1);"),
    _m("er-ptree", "ev->pTree = et;", "ev->pTree = NULL;"),
    _m("er-pstate", "ev->pState = state;", "ev->pState = NULL;"),
    _m("er-num", "ev->nNumber = e->nNumber;", "ev->nNumber = e->nNumber + 1;"),
    _m("er-type", "ev->nType = e->nType;", "ev->nType = e->nClass;"),
    _m("er-class", "ev->nClass = e->nClass;", "ev->nClass = e->nType;"),
    _m("er-ncars", "ev->nCars = e->nCars;", "ev->nCars = e->nTracks;"),
    _m("er-ntracks", "ev->nTracks = e->nTracks;", "ev->nTracks = e->nCars;"),
    _m("er-nrewards", "ev->nRewards = e->nRewards;", "ev->nRewards = 0;"),
    _m("er-init-players", "ev->nInitialPlayers = 1;",
       "ev->nInitialPlayers = 2;"),
    _m("er-nopp", "ev->nOpponents = e->nOpponents;",
       "ev->nOpponents = e->nOpponents + 1;"),
    _m("er-objective", "e->nObjective, 8), 8);",
       "e->nObjective + 1, 8), 8);"),
    _m("er-cars-bound", "i < e->nCars && i < 20;", "i < e->nCars && i < 19;"),
    _m("er-cars-idx", "et->pCars : NULL, e->aCars[i], 4)",
       "et->pCars : NULL, e->aCars[0], 4)"),
    _m("er-tracks-bound", "i < e->nTracks && i < 8;",
       "i < e->nTracks && i < 7;"),
    _m("er-tracks-idx", "et->pTracks : NULL, e->aTracks[i], 4)",
       "et->pTracks : NULL, e->aTracks[i] + 1, 4)"),
    _m("er-rewards-bound", "i < e->nRewards && i < 8;",
       "i < e->nRewards - 1 && i < 8;"),
    _m("er-rewards-size", "e->aRewards[i], 8),", "e->aRewards[i], 4),"),
    _m("er-opp-bound", "i < e->nOpponents && i < 7;",
       "i < e->nOpponents && i < 6;"),
    _m("er-opp-idx", "et->pOpponents : NULL, e->aOpponents[i],",
       "et->pOpponents : NULL, e->aOpponents[i] + 1,"),
    # the reward's name
    _m("er-rw-none", "if (e->nRewards <= 0) {", "if (e->nRewards < 0) {"),
    _m("er-rw-none-text", "translate_string(\"No reward\")",
       "translate_string(\"No reward!\")"),
    _m("er-rw-car", "} else if (r->nType == REWARD_CAR) {",
       "} else if (r->nType == 2) {"),
    _m("er-rw-car-v", "cartypeinfo_get(r->nValue1);",
       "cartypeinfo_get(r->nValue2);"),
    _m("er-rw-car-id", "translate(ct->pCarSpecs->FullName)",
       "translate(ct->pCarSpecs->FullName + 1)"),
    _m("er-rw-car-trs", "translate_string(translate(ct->pCarSpecs",
       "(translate(ct->pCarSpecs"),
    _m("er-rw-track", "} else if (r->nType == REWARD_TRACK) {",
       "} else if (r->nType == 3) {"),
    _m("er-rw-track-v", "track_get_info(r->nValue1);",
       "track_get_info(r->nValue2);"),
    _m("er-rw-track-dir", "get_the_right_track_language_id(ti, r->nValue2)",
       "get_the_right_track_language_id(ti, 0)"),
    _m("er-rw-track-null", ": 0));", ": 1));"),
    _m("er-rw-unhandled", "translate_string(\"Unhandled type\")",
       "translate_string(\"Unhandled\")"),
    # the race parameters
    _m("er-desc-id", "translate(e->mDescriptionString),",
       "translate(e->mDescriptionString + 1),"),
    _m("er-desc-n", "rp->sObjective, 512);", "rp->sObjective, 511);"),
    _m("er-hasobj", "rp->HasObjective = 1;", "rp->HasObjective = 0;"),
    _m("er-reset-results", "raceevent_reset_results(ev);", "(void)ev;"),
    _m("er-tickets", "rp->nNumTicketsBeforeArrest = 2;",
       "rp->nNumTicketsBeforeArrest = 3;"),
    _m("er-tt-zero", "rp->TimeTrialTime.PackedTime = 0;",
       "rp->TimeTrialTime.PackedTime = 1;"),
    _m("er-beacop0", "rp->BeACop = 0;", "rp->BeACop = 2;"),
    _m("er-switch", "switch (ev->nType) {", "switch (e->nClass) {"),
    _m("er-tt-type", "rp->RaceType = 2;", "rp->RaceType = 1;"),
    _m("er-tt-time",
       "rp->RaceType = 2;\n        rp->TimeTrialTime.PackedTime = "
       "(int32_t)ev->Objective.nData;",
       "rp->RaceType = 2;\n        rp->TimeTrialTime.PackedTime = 0;"),
    _m("er-lko-type", "rp->RaceType = 3;", "rp->RaceType = 1;"),
    _m("er-rko-type", "rp->RaceType = 4;", "rp->RaceType = 3;"),
    _m("er-rko-index", "if (ko_state_get_race_index(state) == 0)",
       "if (ko_state_get_race_index(state) != 0)"),
    _m("er-rko-new", "ko_state_new_seed(state);", "(void)state;"),
    _m("er-rko-seed", "rp->New780 = (int32_t)ko_state_get_seed(state);",
       "rp->New780 = 0;"),
    _m("er-tour-type", "rp->RaceType = 5;", "rp->RaceType = 4;"),
    _m("er-tour-index",
       "tournament_state_get_race_index(state, e->nOpponents) == 0",
       "tournament_state_get_race_index(state, e->nOpponents + 1) == 0"),
    _m("er-tour-new", "tournament_state_new_seed(state);", "(void)state;"),
    _m("er-tour-seed",
       "rp->New780 = (int32_t)tournament_state_get_seed(state);",
       "rp->New780 = 0;"),
    _m("er-p2p-flag", "rp->Point2Point = 1;", "rp->Point2Point = 0;"),
    _m("er-p2p-type", "rp->Point2Point = 1;\n        rp->RaceType = 1;",
       "rp->Point2Point = 1;\n        rp->RaceType = 2;"),
    _m("er-p2p-time",
       "rp->Point2Point = 1;\n        rp->RaceType = 1;\n"
       "        rp->TimeTrialTime.PackedTime = (int32_t)ev->Objective.nData;",
       "rp->Point2Point = 1;\n        rp->RaceType = 1;\n"
       "        rp->TimeTrialTime.PackedTime = 0;"),
    _m("er-bac-tickets", "rp->nNumTicketsBeforeArrest = 0;",
       "rp->nNumTicketsBeforeArrest = 2;"),
    _m("er-bac-flag", "rp->BeACop = 1;", "rp->BeACop = 0;"),
    _m("er-bac-reset", "rp->BeACopResetTimerAfterArrest = 0;",
       "rp->BeACopResetTimerAfterArrest = 1;"),
    _m("er-bac-type",
       "rp->BeACopResetTimerAfterArrest = 0;\n        rp->RaceType = 1;",
       "rp->BeACopResetTimerAfterArrest = 0;\n        rp->RaceType = 2;"),
    _m("er-bac-time",
       "rp->BeACopResetTimerAfterArrest = 0;\n        rp->RaceType = 1;\n"
       "        rp->TimeTrialTime.PackedTime = (int32_t)ev->Objective.nData;",
       "rp->BeACopResetTimerAfterArrest = 0;\n        rp->RaceType = 1;\n"
       "        rp->TimeTrialTime.PackedTime = 0;"),
    _m("er-default-type", "rp->RaceType = 1;\n        break;\n    }",
       "rp->RaceType = 0;\n        break;\n    }"),
    _m("er-players", "rp->NumPlayerCars = 1;", "rp->NumPlayerCars = 2;"),
    _m("er-maxcops", "EVENT_TREE_HOT_PURSUIT ? 6 : 0;",
       "EVENT_TREE_HOT_PURSUIT ? 5 : 0;"),
    _m("er-maxcops-tree", "tree->nType == EVENT_TREE_HOT_PURSUIT",
       "tree->nType != EVENT_TREE_HOT_PURSUIT"),
    _m("er-ai", "rp->NumAICars = e->nOpponents;",
       "rp->NumAICars = e->nOpponents - 1;"),
    _m("er-oppsel", "rp->OpponentSelect = e->nOpponentSelect;",
       "rp->OpponentSelect = 0;"),
    _m("er-copstr", "rp->CopStrength = e->eCopStrength;",
       "rp->CopStrength = 0;"),
    _m("er-btickets", "rp->bTickets = e->bTickets;",
       "rp->bTickets = e->bRoadBlocks;"),
    _m("er-broad", "rp->bRoadBlocks = e->bRoadBlocks;",
       "rp->bRoadBlocks = e->bTickets;"),
    _m("er-bspike", "rp->bSpikeStrips = e->bSpikeStrips;",
       "rp->bSpikeStrips = e->bHelicopter;"),
    _m("er-bheli", "rp->bHelicopter = e->bHelicopter;",
       "rp->bHelicopter = e->bSpikeStrips;"),
    _m("er-new624", "rp->New624 = e->New56;", "rp->New624 = 0;"),
    _m("er-bac-rb", "rp->nNumBeACopRoadBlocks = e->nNumBeACopRoadBlocks;",
       "rp->nNumBeACopRoadBlocks = e->nNumBeACopChoppers;"),
    _m("er-bac-ch", "rp->nNumBeACopChoppers = e->nNumBeACopChoppers;",
       "rp->nNumBeACopChoppers = e->nNumBeACopRoadBlocks;"),
    _m("er-training", "rp->TrainingLinesEnabled = 0;",
       "rp->TrainingLinesEnabled = 1;"),
    _m("er-damage", "rp->DamageEnabled = e->New184 != 0;",
       "rp->DamageEnabled = e->New184;"),
    _m("er-startpos", "(uint8_t)(e->nOpponents + 1);",
       "(uint8_t)(e->nOpponents);"),
    _m("er-boost0", "rp->BoostScale[0] = e->fOpponentBoostScale;",
       "rp->BoostScale[0] = 0.0f;"),
    _m("er-boost1", "rp->BoostScale[1] = e->fOpponentBoostScale;",
       "rp->BoostScale[1] = 0.0f;"),
    # the tokens
    _m("er-tok-name", "\"$NUM_RACES\"", "\"$NUM_RACE\""),
    _m("er-tok-id", "{ EVENT_TOKEN_COMPLETION_TIME, \"$COMPLETION_TIME\" }",
       "{ EVENT_TOKEN_TRACK_NAME, \"$COMPLETION_TIME\" }"),
    _m("er-tok-count", "for (i = 0; i < EVENT_TOKEN_COUNT; i++) {",
       "for (i = 0; i < EVENT_TOKEN_COUNT - 1; i++) {"),
    _m("er-tok-len", "strncmp(name, src, strlen(name)) == 0",
       "strncmp(name, src, strlen(name) - 1) == 0"),
    _m("er-ft-goal", "e->nObjective, 8);", "e->nObjective, 4);"),
    _m("er-ft-type2", "if (g->nType == 2) {", "if (g->nType == 1) {"),
    _m("er-ft-time", "t.PackedTime = (int32_t)g->nData;",
       "t.PackedTime = (int32_t)g->nData + 1;"),
    _m("er-ft-flags", "timer_print_to_string(&t, buf, 0,",
       "timer_print_to_string(&t, buf, 1,"),
    _m("er-ft-skip", "while (*p == ' ')", "while (*p == ' ' && 0)"),
    _m("er-ft-zz", "strcpy(out, \"zz:zz\");", "strcpy(out, \"zz:zy\");"),
    _m("er-ft-laps-shift", "(int)(w >> 14 & 0xf)", "(int)(w >> 15 & 0xf)"),
    _m("er-ft-laps-idx", "e->aTracks[0], 4));", "e->aTracks[1], 4));"),
    _m("er-ft-opp", "(int)e->nOpponents);", "(int)e->nOpponents + 1);"),
    _m("er-ft-races", "(int)event_info_get_race_count(e));",
       "(int)event_info_get_race_count(e) + 1);"),
    _m("er-ft-evu", "\"events x,y,z are Unlocked!\"",
       "\"events x,y,z are unlocked!\""),
    _m("er-ft-ct", "\"ff:ggg\"", "\"ff:gg\""),
    _m("er-ft-eu", "\"event x is unlocked\"", "\"event x is Unlocked\""),
    _m("er-ft-tn", "\"TRACK_NAME_HERE\"", "\"TRACK_NAME\""),
    _m("er-ft-default", "    default:\n        break;\n    }\n}",
       "    default:\n        out[0] = 0;\n        break;\n    }\n}"),
    # the description
    _m("er-fd-put", "if (pos < n - 1)\n        dst[pos] = c;",
       "if (pos < n - 2)\n        dst[pos] = c;"),
    _m("er-fd-dollar", "*src == '$' ? get_event_description_token(src)",
       "*src == '#' ? get_event_description_token(src)"),
    _m("er-fd-skip", "src += strlen(tok->sName);",
       "src += strlen(tok->sName) - 1;"),
    _m("er-fd-inner", "while (*p != 0 && pos < n)",
       "while (*p != 0 && pos < n - 1)"),
    _m("er-fd-outer", "} while (*src != 0 && pos < n);",
       "} while (*src != 0 && pos < n - 1);"),
    _m("er-fd-term", "dst[pos < n ? pos : n - 1] = 0;",
       "if (pos < n)\n        dst[pos] = 0;"),
]

EQUIVALENT = {
    "er-from-laps-mask": "the extra bit cleared is 18, the density's "
                         "lowest, which the density's own mask clears and "
                         "sets again after",
    "er-from-dens-mask": "the extra bit is 25, the oncoming share's "
                         "lowest, which the oncoming mask clears and sets "
                         "again after",
}


def _check_mutations():
    texts = {}
    for name, f, old, new in MUTATIONS:
        if f not in texts:
            texts[f] = (ROOT / f).read_text()
        n = texts[f].count(old)
        assert n == 1, "%s: %d matches" % (name, n)
        assert old != new, name
    names = [m[0] for m in MUTATIONS]
    assert len(names) == len(set(names)), "duplicate mutation names"


def mutate_pass(only=None, jobs=None):
    _check_mutations()
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    d, lines, scp, dp = write_inputs(indir.name)
    base_lines = model_cached(lines, d.buf)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, dp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "eventrace_test",
        lambda exe, out: mutpar.run_exe([exe, scp, dp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
    indir.cleanup()
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

    with tempfile.TemporaryDirectory() as tmp:
        d, lines, scp, dp = write_inputs(tmp)
        t0 = time.monotonic()
        got = model_cached(lines, d.buf)
        print("model: %.1f s" % (time.monotonic() - t0), flush=True)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, dp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        dd = Path(args.dump)
        dd.parent.mkdir(parents=True, exist_ok=True)
        dd.with_suffix(".model").write_text(NL.join(got) + NL)
        dd.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
