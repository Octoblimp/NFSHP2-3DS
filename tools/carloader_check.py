#!/usr/bin/env python3
"""Cross-check 3DS Files/source/carloader.c, retail's CarLoader, against
the retail image itself, run in mipsemu.

The model is the image. InitCarLoader (0x001b0260), CloseCarLoader
(0x001b0290), LoadedSkin's constructor (0x001b02b8) and GetUsedTextures
(0x001b02f8), LoadedCar's constructor (0x001b0470), FindLoadedCar
(0x001b04b0), FindLoadedSkin (0x001b0518), Load (0x001b0560), IsLoaded
(0x001b06f8), Unload (0x001b07e0), UnloadEverything (0x001b08c0),
RemoveUnusedCarsAndSkins (0x001b09b0), BeginLoading (0x001b0b00),
LoadingDoneCallback (0x001b0c30), ~CarLoader (0x001b0cf8), the static
constructor (0x001b0d68) and the bridge (0x001b0da0) run as shipped, and
so do what runs under them: GetNumSkins (0x001884b8), GetSkinNumber
(0x001884d8), GetUsedCarTextureInfo (0x00188790), the destructors,
bStrCpy, bStrCmp, bSPrintf and bStringHash. The harness
(tools/src/carloader_test.c) runs the port over the same script, and the
two transcripts are diffed.

Stubbed on both sides, each printing its arguments: the slot pool's four
calls (the slots are the stub's, handed out lowest first and filled with
0xcd), LoadResourceFile and UnloadResourceFile, ServiceResourceLoading,
and TexturePack's LoadTexturesFromFile and UnloadTexturesFromFile. The
loads queue their completion and the bridge's parameter; the script's D,
or ServiceResourceLoading, runs the oldest. Two fake callbacks stand for
BeginLoading's: cb prints, and cb2 prints and calls BeginLoading with cb,
from inside LoadingDoneCallback.

The cars are GLOBALB.BUN's own 64 records, some changed by the script (a
car as a cop, a car without skins). The ops act on TheCarLoader or a
second loader, so a port that reached for the global where retail uses
`this` would differ. After each op the transcript holds the loader, both
of its lists and every link's back pointer.

    python tools/carloader_check.py
    python tools/carloader_check.py --mutate [--only a,b]
    python tools/carloader_check.py --dump out/carloader
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carinfo_check as cic
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/carloader_test.c"
CL = "3DS Files/source/carloader.c"
CTI = "3DS Files/source/cartypeinfo.c"
SOURCES = [HARNESS, CL] + ["3DS Files/source/" + f for f in (
    "cartypeinfo.c", "langtab.c", "bmath.c", "bmathtab.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
INIT = 0x001b0260
CLOSE = 0x001b0290
SKIN_CTOR = 0x001b02b8
USED_TEX = 0x001b02f8
FIND_CAR = 0x001b04b0
FIND_SKIN = 0x001b0518
LOAD = 0x001b0560
IS_LOADED = 0x001b06f8
UNLOAD = 0x001b07e0
UNLOAD_ALL = 0x001b08c0
REMOVE = 0x001b09b0
BEGIN = 0x001b0b00
DONE = 0x001b0c30
DTOR = 0x001b0cf8
SINIT = 0x001b0d68
BRIDGE = 0x001b0da0
THE = 0x00313a38                  # TheCarLoader

NEW_POOL = 0x00257c10
DEL_POOL = 0x00257c48
O_MALLOC = 0x00257c80
POOL_FREE = 0x00257ca0
LOAD_RES = 0x00199640
UNLOAD_RES = 0x00199728
SERVICE = 0x00199788
LOAD_TEX = 0x001acc98
UNLOAD_TEX = 0x001acd90
B_DELETE = 0x00114e98
DEMO_DISC = 0x002effe0

G_POOL = GP - 18888               # LoadedCarSlotPool
G_PACK = GP - 21436               # pCarTexturePack
G_ARRAY = GP - 20616              # CarTypeInfoArray
LANG = 0x0031c1c8                 # TheLanguageManager.CurrLanguage

REC = 1376
NUM_TYPES = 64
REC_BASE = 0x01000000
SLOT_BASE = 0x01100000
SLOT_STRIDE = 64
NSLOT = 160
RIDE = 0x01200000
SKIN = 0x01200100
NAMEBUF = 0x01200200
TEX = 0x01201000
NTEX = 600
SCRATCH = 0x01210000
POOL_TOK = 0x01300000
PACK_TOK = 0x01300100
RF_BASE = 0x01310000
MAXRF = 256
CB = 0x01320000
CB2 = 0x01320010
MAX_SERVICES = 50
LIMIT = 50000000

# CarTypeInfo, the console's offsets.
NUM_SKINS = 229
USAGE = 1336
AVAILABLE = 1348


# ============================================================ the scenarios

def ride(t, i=0, k=1, d=0, v=0):
    return "%d %d %d %d %d" % (t, i, k, d, v)


def L(*a):
    return "L " + ride(*a)


def U(*a):
    return "U " + ride(*a)


def Q(req, *a):
    return "Q %s %d" % (ride(*a), req)


def T(r, num, mx, fe=0, keep=0):
    return "T %s %d %d %d %d" % (ride(*r), num, mx, fe, keep)


def s_boot():
    return [
        # The static constructor over a loader that holds something: every
        # word is its own.
        "P a5",
        "C",
        "I",
        "FC 0 0", "FS 0 5", "FN " + b"CARS\\CORVETTE\\GEOMETRY.LZC".hex(),
        Q(1, 0, 0, 5), Q(0, 0, 0, 5),
        U(0, 0, 5),
        "E", "M",
        # Nothing loading and nothing to load.
        "Y",
        "G 0",
        "S rr 0", "S fe 1",
        "P 00",
        "C",
        "X",
        "I",
    ]


def s_share():
    return [
        "C",
        # The Corvette and its HP share a body; the first's answer is 0.
        L(0, 0, 5), L(1, 0, 6), L(0, 1, 5),
        # The Spider has a dash; without one it shares the skin.
        L(21, 0, 1, 1), L(21, 1, 1, 0),
        # A skin first wanted without its dash, then with it.
        L(23, 0, 1, 0), L(23, 1, 1, 1),
        # The F50 HP shares the F50's body and dash.
        L(24, 0, 3, 1),
        # A dash for a car with no dash file: an entry with no name.
        L(0, 2, 5, 1),
        Q(1, 0, 0, 5), Q(0, 0, 0, 5), Q(1, 0, 0, 9), Q(1, 21, 0, 1, 1),
        Q(1, 22, 0, 1, 1), Q(1, 2, 0, 5, 1), Q(7, 0, 0, 5), Q(1, 23, 0, 1, 1),
        Q(1, 25, 0, 1, 1),
        "FC 0 0", "FC 21 1", "FC 0 1", "FC 22 0", "FS 21 1", "FS 21 2",
        "FS 1 6", "FS 5 6",
        "FN " + b"CARS\\CORVETTE\\GEOMETRY".hex(),
        "FN " + b"CARS\\CORVETTE\\GEOMETRY.LZC".hex(),
        "FN " + b"CARS\\CORVETTE\\GEOMETRY.BIN".hex(),
        "FN ",
        U(1, 0, 6), U(1, 0, 6),
        U(0, 0, 5), U(0, 1, 5), U(0, 2, 5, 1),
        U(21, 0, 1, 1),
        U(9, 0, 1),
        "E",
        "G 0",
    ]


def s_round_robin():
    return [
        "C",
        L(0, 0, 5), L(2, 0, 6), L(21, 0, 1, 1),
        "G 1",
        # A second BeginLoading while one is in progress keeps its callback.
        "G 0",
        Q(0, 0, 0, 5), Q(1, 0, 0, 5),
        "D", "D", "D",
        Q(0, 0, 0, 5),
        # The skins are in: the bodies and the dash, one file at a time.
        "D", "D", "D", "D",
        Q(0, 0, 0, 5), Q(0, 21, 0, 1, 1),
        "D",
        "G 0",
        # A loaded car unloads its file and its textures.
        U(2, 0, 6),
        L(2, 0, 6),
        "G 2",
        "D", "D",
        # Replaced while loading: the last one given wins.
        L(5, 0, 1),
        "G 1", "G 2",
        "D", "D",
        # Unloaded while its file is loading: it stays until it is in.
        L(7, 0, 2),
        "G 0", "D",
        U(7, 0, 2),
        "D",
        U(0, 0, 5),
        # A skin unloaded while its textures load.
        L(9, 0, 4),
        "G 1",
        U(9, 0, 4),
        "D", "D",
        "E",
    ]


def s_everything():
    return [
        "C",
        L(0, 0, 5), L(13, 0, 8, 1),
        "G 1", "D", "D", "D",
        # A body loading and the rest loaded: the service brings it in.
        "E",
        L(4, 0, 1), L(31, 0, 2),
        "G 0",
        # A skin loading.
        "E",
        L(17, 0, 1), L(17, 1, 1),
        "G 0", "D",
        "E",
    ]


def s_wide():
    return [
        "C",
        "S rr 0", "S fe 1",
        L(0, 0, 5), L(1, 0, 6), L(0, 0, 1), L(21, 0, 3, 1),
        # Every skin not loaded, in one load.
        "G 1", "D",
        L(2, 0, 2), L(3, 0, 7),
        "G 0", "D", "D", "D", "D", "D", "D",
        "S fe 0",
        U(1, 0, 6), U(21, 0, 3, 1),
        "S fe 1",
        U(0, 0, 5),
        # Every skin a car has.
        L(0, 0, -1), L(4, 0, -1), "S lang 0",
        "G 0", "D",
        "S lang 3", U(4, 0, -1),
        L(4, 0, -1), "G 0", "D",
        "S lang -1", L(32, 0, -1), "G 0", "D",
        "S lang 0",
        "E",
    ]


def s_wrap():
    return [
        "C",
        # The skin is still loading when its last instance goes, and the
        # second Unload finds it: its count goes below 0.
        L(0, 0, 5), L(1, 0, 6),
        "G 0",
        U(0, 0, 5), U(0, 0, 5),
        "D",
        U(0, 0, 5),
        "D", "D",
        "E",
        # A dash loading when its last ride goes twice: the dash's count
        # goes below 0, and the dash stays once it is in.
        L(21, 0, 1, 1), L(21, 0, 1, 0),
        "G 0", "D", "D",
        U(21, 0, 1, 1), U(21, 0, 1, 1),
        "D", "M",
        "E",
        # 128 instances of one ride: the answer as a signed byte.
    ] + [L(11, 0, 1)] * 130 + [
        U(11, 0, 1),
        "E",
    ]


def s_textures():
    corvette = (0, 0, 5)
    hp = (1, 0, 6)
    return [
        T(corvette, 0, 512),
        T(corvette, -1, 512, 0, 1),
        T(hp, -1, 512, 0, 1),
        T(corvette, 0, 512, 1),
        T(corvette, 4, 512, 1),
        T(corvette, 0, 3),
        T(corvette, 0, 0),
        T(corvette, 5, 3),
        T(corvette, 3, 3),
        T(corvette, 0, -1),
        T((0, 0, -1), 0, 512),
        T((0, 0, -1), 0, 20),
        T((0, 0, -1), 2, 40, 1),
        T((21, 0, 2, 1), 0, 512),
        T((21, 0, 2, 1), 0, 512, 1),
        T((13, 0, -1, 1), 0, 512, 1),
        T((13, 0, 0), 0, 512),
        T((13, 0, 100), 0, 512),
        T((13, 0, -7), 0, 512),
        "S lang 0", T((4, 0, -1), 0, 512),
        "S lang 2", T((4, 0, -1), 0, 512),
        "S lang -1", T((33, 0, -1), 0, 512),
        "S lang 0",
        T((49, 0, -1), 0, 512),
        T((57, 0, -1, 0, 1), 0, 512, 0),
    ]


def s_records():
    return [
        # No skins, and fewer than none.
        "A 0 %d 00" % NUM_SKINS, T((0, 0, -1), 0, 512),
        "A 0 %d ff" % NUM_SKINS, T((0, 0, -1), 0, 512),
        "A 0 %d 05" % NUM_SKINS,
        # The Corvette as a cop: one skin, the language's.
        "A 0 %d 01000000" % USAGE, T((0, 0, -1), 0, 512),
        "S lang 1", T((0, 0, -1), 0, 512),
        "S lang 0",
        "A 0 %d 02000000" % USAGE, T((0, 0, -1), 0, 512),
        # A cop with no skins of its own still has one.
        "A 0 %d 00" % NUM_SKINS, "A 0 %d 01000000" % USAGE,
        T((0, 0, -1), 0, 512),
        "A 0 %d 05" % NUM_SKINS,
        "A 0 %d 00000000" % USAGE,
        # The Viper's six skins all one skin, and three repeats.
        "A 2 %d 03030303030300000000" % AVAILABLE, T((2, 0, -1), 0, 512),
        "A 2 %d 07010701070100000000" % AVAILABLE, T((2, 0, -1), 0, 512),
        "A 2 %d 03" % NUM_SKINS, T((2, 0, -1), 0, 512),
        "A 2 %d 05060201040300000000" % AVAILABLE,
        "A 2 %d 06" % NUM_SKINS,
        # The cop's skin through the loader.
        "C", "A 0 %d 01000000" % USAGE,
        L(0, 0, -1), "G 0", "D", "S lang 4", U(0, 0, -1),
        "S lang 0", "A 0 %d 00000000" % USAGE,
        "E",
    ]


def s_second():
    return [
        "C",
        L(0, 0, 5),
        "W 1",
        "P 5a",
        "N",
        "S fe 1",
        L(0, 0, 5), L(23, 0, 2, 1),
        "G 2",
        "D", "D", "D", "D",
        U(0, 0, 5),
        "S rr 0",
        L(2, 0, 3), L(3, 0, 7),
        "G 0", "D",
        Q(1, 2, 0, 3), Q(0, 2, 0, 3),
        "FC 2 0", "FS 3 7",
        # The destructor frees every entry, loaded or not.
        "Z",
        "W 0",
        "G 1", "D", "D",
        "Z",
        "C",
    ]


def s_crowd():
    out = ["C", "S rr 0"]
    out += [L(t, 0, -1 if t % 9 == 0 else 1) for t in range(NUM_TYPES)]
    out += ["G 1", "D", "D", "D"]
    out += [U(t, 0, -1 if t % 9 == 0 else 1) for t in range(0, NUM_TYPES, 3)]
    out += ["E"]
    out += ["S rr 1"]
    out += [L(t, 0, 1, 1) for t in range(0, NUM_TYPES, 7)]
    out += ["G 0", "D", "D", "Y", "M", "E"]
    return out


def s_queries():
    return [
        "C",
        # A body and a skin without the dash the ride asks for.
        L(21, 0, 1, 0),
        Q(1, 21, 0, 1, 1), Q(0, 21, 0, 1, 1),
        "G 0", "D", "D",
        Q(0, 21, 0, 1, 0), Q(0, 21, 0, 1, 1),
        # The dash wanted after the rest is in: its entry, not yet loaded.
        L(21, 1, 1, 1),
        Q(1, 21, 0, 1, 1), Q(0, 21, 0, 1, 1), Q(0, 21, 0, 1, 0),
        "G 0", "D",
        Q(0, 21, 0, 1, 1),
        # A loaded body under a skin not yet loaded.
        L(0, 0, 5), "G 0", "D", "D",
        L(1, 0, 6),
        Q(0, 1, 0, 6), Q(1, 1, 0, 6), Q(0, 0, 0, 5),
        "G 0", "D",
        Q(0, 1, 0, 6),
        "E",
        # A body unloaded while it loads, with the next one waiting: the
        # unload comes before the next load starts.
        L(2, 0, 1), L(21, 0, 1),
        "G 0", "D", "D",
        U(2, 0, 1),
        "D", "D",
        "E",
    ]


def script():
    recs = cic.car_records(cic.globalb_chunks()[cic.CAR_CHUNK])
    return [["R " + bytes(recs).hex(), "C", "I"] + s for s in (
        s_boot(), s_share(), s_round_robin(), s_everything(), s_wide(),
        s_wrap(), s_textures(), s_records(), s_second(), s_crowd(),
        s_queries())]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        self.cur = THE
        self.used = [False] * NSLOT
        self.pend = []
        self.nrf = 0
        self.services = 0
        self.last_ret = 0
        e.put32(DEMO_DISC, 0)
        e.put32(G_POOL, 0)
        e.put32(G_PACK, PACK_TOK)
        e.put32(LANG, 0)
        e.write(THE, bytes(32))
        for a, fn in ((NEW_POOL, self.s_new_pool), (DEL_POOL, self.s_del_pool),
                      (O_MALLOC, self.s_omalloc), (POOL_FREE, self.s_free),
                      (LOAD_RES, self.s_load_res),
                      (UNLOAD_RES, self.s_unload_res),
                      (SERVICE, self.s_service), (LOAD_TEX, self.s_load_tex),
                      (UNLOAD_TEX, self.s_unload_tex),
                      (B_DELETE, self.s_delete), (CB, self.s_cb),
                      (CB2, self.s_cb2)):
            e.stub(a, fn)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    def s8(self, a):
        v = self.e.u8(a)
        return v - 256 if v & 0x80 else v

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    # ---- the labels ------------------------------------------------------

    def nm(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        named = {POOL_TOK: "pool", PACK_TOK: "pack", THE: "L0", SCRATCH: "L1",
                 THE + 16: "L0.cars", THE + 24: "L0.skins",
                 SCRATCH + 16: "L1.cars", SCRATCH + 24: "L1.skins"}
        if a in named:
            return named[a]
        if (SLOT_BASE <= a < SLOT_BASE + SLOT_STRIDE * NSLOT
                and (a - SLOT_BASE) % SLOT_STRIDE == 0):
            return "#%d" % ((a - SLOT_BASE) // SLOT_STRIDE)
        if RF_BASE <= a < RF_BASE + MAXRF:
            return "rf%d" % (a - RF_BASE)
        return "?"

    def cnm(self, a):
        return {0: "NULL", CB: "cb", CB2: "cb2"}.get(a & M32, "?")

    def dnm(self, a):
        return {0: "NULL", BRIDGE: "bridge"}.get(a & M32, "?")

    # ---- nested calls ----------------------------------------------------

    def nested(self, fn, *args):
        """Call into the image from inside a stub, and put back what the
        stub's caller had."""
        e = self.e
        kept = (list(e.reg), list(e.fpr), e.hi, e.lo, e.hi1, e.lo1, e.sa,
                e.fcc, e.limit, e.icount)
        try:
            e.call(fn, *args, limit=LIMIT)
        finally:
            e.reg[:] = kept[0]
            e.fpr[:] = kept[1]
            (e.hi, e.lo, e.hi1, e.lo1, e.sa, e.fcc, e.limit,
             e.icount) = kept[2:]

    def complete(self, inside):
        if not self.pend:
            self.emit("  nothing pending")
            return
        cb, param = self.pend.pop(0)
        if cb:
            if inside:
                self.nested(cb, param)
            else:
                self.e.call(cb, param, limit=LIMIT)

    # ---- the stubs -------------------------------------------------------

    def hashes(self, a, n):
        return "".join(" %08x" % self.e.u32(a + 4 * i) for i in range(n))

    def s_new_pool(self, em):
        self.emit("  newpool %d %d %s %d" % (
            s32(self.arg(0)), s32(self.arg(1)), self.cstr(self.arg(2)),
            s32(self.arg(3))))
        return POOL_TOK

    def s_del_pool(self, em):
        self.emit("  delpool %s" % self.nm(self.arg(0)))

    def s_omalloc(self, em):
        for i in range(NSLOT):
            if not self.used[i]:
                self.used[i] = True
                a = SLOT_BASE + SLOT_STRIDE * i
                self.e.write(a, b"\xcd" * SLOT_STRIDE)
                self.emit("  omalloc %s -> #%d" % (self.nm(self.arg(0)), i))
                return a
        raise SystemExit("slots full")

    def s_free(self, em):
        a = self.arg(1)
        self.emit("  free %s %s" % (self.nm(self.arg(0)), self.nm(a)))
        if SLOT_BASE <= a < SLOT_BASE + SLOT_STRIDE * NSLOT:
            self.used[(a - SLOT_BASE) // SLOT_STRIDE] = False

    def s_load_res(self, em):
        if self.nrf >= MAXRF:
            raise SystemExit("too many files")
        self.emit("  loadres %s %d %d %s %s -> rf%d" % (
            self.cstr(self.arg(0)), s32(self.arg(1)), s32(self.arg(2)),
            self.dnm(self.arg(3)), self.nm(self.arg(4)), self.nrf))
        self.pend.append((self.arg(3), self.arg(4)))
        self.nrf += 1
        return RF_BASE + self.nrf - 1

    def s_unload_res(self, em):
        self.emit("  unloadres %s" % self.nm(self.arg(0)))

    def s_service(self, em):
        self.emit("  service")
        self.services += 1
        if self.services > MAX_SERVICES:
            self.emit("service spin")
            raise SystemExit("ServiceResourceLoading spins")
        if self.pend:
            self.complete(True)

    def s_load_tex(self, em):
        n = s32(self.arg(2))
        self.emit("  loadtex %s %d %s %s:%s" % (
            self.nm(self.arg(0)), n, self.dnm(self.arg(3)),
            self.nm(self.arg(4)), self.hashes(self.arg(1), n)))
        self.pend.append((self.arg(3), self.arg(4)))

    def s_unload_tex(self, em):
        n = s32(self.arg(2))
        self.emit("  unloadtex %s %d:%s" % (
            self.nm(self.arg(0)), n, self.hashes(self.arg(1), n)))

    def s_delete(self, em):
        self.emit("  delete %s" % self.nm(self.arg(0)))

    def s_cb(self, em):
        self.emit("  callback")

    def s_cb2(self, em):
        self.emit("  callback2")
        self.nested(BEGIN, self.cur, CB)

    # ---- the print -------------------------------------------------------

    def print_state(self):
        e = self.e
        cl = self.cur
        self.emit("st %s cb=%s rr=%d fe=%d lip=%d pool=%s pack=%s" % (
            self.nm(cl), self.cnm(e.u32(cl)), s32(e.u32(cl + 4)),
            s32(e.u32(cl + 8)), s32(e.u32(cl + 12)),
            self.nm(e.u32(G_POOL)), self.nm(e.u32(G_PACK))))
        head = cl + 16
        n, k = e.u32(head), 0
        while n != head and n != 0 and k < NSLOT:
            self.emit("car %s n=%d ld=%d ok=%d pad=%d rf=%s prev=%s name=%s"
                      % (self.nm(n), self.s8(n + 8), self.s8(n + 9),
                         self.s8(n + 10), e.u8(n + 11),
                         self.nm(e.u32(n + 12)), self.nm(e.u32(n + 4)),
                         bytes(e.mem[n + 16:n + 48]).hex()))
            n, k = e.u32(n), k + 1
        if n == 0:
            self.emit("cars null")
        elif k == NSLOT:
            self.emit("cars loop")
        self.emit("cars end prev=%s" % self.nm(e.u32(head + 4)))
        head = cl + 24
        n, k = e.u32(head), 0
        while n != head and n != 0 and k < NSLOT:
            self.emit("skin %s type=%d inst=%d skin=%d dash=%d dmg=%d n=%d "
                      "ld=%d ok=%d prev=%s" % (
                          self.nm(n), s32(e.u32(n + 8)), self.s8(n + 12),
                          self.s8(n + 13), self.s8(n + 14), self.s8(n + 15),
                          self.s8(n + 16), self.s8(n + 17), self.s8(n + 18),
                          self.nm(e.u32(n + 4))))
            n, k = e.u32(n), k + 1
        if n == 0:
            self.emit("skins null")
        elif k == NSLOT:
            self.emit("skins loop")
        self.emit("skins end prev=%s" % self.nm(e.u32(head + 4)))

    # ---- the ops ---------------------------------------------------------

    def put_ride(self, t):
        e = self.e
        e.put32(RIDE, int(t[0]) & M32)
        e.write(RIDE + 4, bytes(int(x) & 0xff for x in t[1:5]))

    def op_textures(self, t):
        e = self.e
        num, mx, fe, keep = (int(x) for x in t[5:9])
        self.put_ride(t)
        e.write(SKIN, b"\xcd" * 20)
        e.call(SKIN_CTOR, SKIN, RIDE, limit=LIMIT)
        if not keep:
            e.write(TEX, b"\xee" * (4 * NTEX))
        if num == -1:
            num = self.last_ret
        ret = e.call(USED_TEX, SKIN, TEX, num, mx, fe, limit=LIMIT)
        self.last_ret = ret
        self.emit("T -> %d type=%d inst=%d skin=%d dash=%d dmg=%d n=%d ld=%d "
                  "ok=%d" % (ret, s32(e.u32(SKIN + 8)), self.s8(SKIN + 12),
                             self.s8(SKIN + 13), self.s8(SKIN + 14),
                             self.s8(SKIN + 15), self.s8(SKIN + 16),
                             self.s8(SKIN + 17), self.s8(SKIN + 18)))
        lim = max(min(max(ret, num) + 2, NTEX), 0)
        self.emit("tex" + self.hashes(TEX, lim))

    def op_find(self, op, t):
        e = self.e
        if op == "FC":
            a = REC_BASE + REC * int(t[1]) + (160 if int(t[2]) else 96)
            r = e.call(FIND_CAR, self.cur, a, limit=LIMIT)
        elif op == "FS":
            r = e.call(FIND_SKIN, self.cur, int(t[1]), int(t[2]),
                       limit=LIMIT)
        else:
            name = bytes.fromhex(t[1]) if len(t) > 1 else b""
            e.write(NAMEBUF, name + b"\0")
            r = e.call(FIND_CAR, self.cur, NAMEBUF, limit=LIMIT)
        self.emit("found %s" % self.nm(r))

    def run(self, scenarios):
        e = self.e
        for n, sc in enumerate(scenarios):
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:40])
                t = ln.split()
                op = t[0]
                self.services = 0
                show = True
                cl = self.cur
                if op == "R":
                    e.write(REC_BASE, bytes.fromhex(t[1]))
                    e.put32(G_ARRAY, REC_BASE)
                    show = False
                elif op == "A":
                    e.write(REC_BASE + REC * int(t[1]) + int(t[2]),
                            bytes.fromhex(t[3]))
                    show = False
                elif op == "S":
                    v = int(t[2]) & M32
                    e.put32({"rr": cl + 4, "fe": cl + 8, "lang": LANG}[t[1]],
                            v)
                elif op == "W":
                    self.cur = SCRATCH if t[1] == "1" else THE
                elif op == "P":
                    e.write(cl, bytes([int(t[1], 16)]) * 32)
                    show = False
                elif op == "C":
                    e.call(SINIT, limit=LIMIT)
                elif op == "N":
                    # Retail's constructor is inline in the static one,
                    # which writes these words to TheCarLoader.
                    e.write(cl, struct.pack("<8I", 0, 1, 0, 0, cl + 16,
                                            cl + 16, cl + 24, cl + 24))
                elif op == "I":
                    e.call(INIT, limit=LIMIT)
                elif op == "X":
                    e.call(CLOSE, limit=LIMIT)
                elif op == "L":
                    self.put_ride(t[1:])
                    self.emit("L -> %d" % e.call(LOAD, cl, RIDE,
                                                 limit=LIMIT))
                elif op == "U":
                    self.put_ride(t[1:])
                    e.call(UNLOAD, cl, RIDE, limit=LIMIT)
                elif op == "Q":
                    self.put_ride(t[1:])
                    self.emit("Q -> %d" % e.call(IS_LOADED, cl, RIDE,
                                                 int(t[6]), limit=LIMIT))
                elif op == "E":
                    e.call(UNLOAD_ALL, cl, limit=LIMIT)
                elif op == "M":
                    e.call(REMOVE, cl, limit=LIMIT)
                elif op == "Y":
                    e.call(DONE, cl, limit=LIMIT)
                elif op == "Z":
                    e.call(DTOR, cl, 2, limit=LIMIT)
                elif op == "G":
                    e.call(BEGIN, cl, (0, CB, CB2)[int(t[1])], limit=LIMIT)
                elif op == "D":
                    self.complete(False)
                elif op == "T":
                    self.op_textures(t[1:])
                    show = False
                elif op in ("FC", "FS", "FN"):
                    self.op_find(op, t)
                else:
                    raise SystemExit("bad op %r" % (t,))
                if show:
                    self.print_state()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="carloader_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
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


# ============================================================ the mutations


def M(name, before, after, rel=CL):
    return (name, rel, before, after)


MUTATIONS = [
    # The lists.
    M("add_tail_last", "    last->next = n;", "    last->next = list;"),
    M("add_tail_head", "    list->prev = n;", "    list->prev = last;"),
    M("add_tail_prev", "    n->prev = last;", "    n->prev = list;"),
    M("add_tail_next", "    n->next = list;" + NL + "}",
      "    n->next = last;" + NL + "}"),
    M("unlink_prev", "    prev->next = next;", "    prev->next = n;"),
    M("unlink_next", "    next->prev = prev;", "    next->prev = n;"),
    M("delete_none", "    bSlotFree(LoadedCarSlotPool, p);", "    (void)p;"),

    # The lifetime.
    M("ctor_callback", "    cl->pCallback = NULL;" + NL + "    cl->LoadedCarList.prev",
      "    cl->LoadedCarList.prev"),
    M("ctor_round_robin", "    cl->RoundRobinFlag = 1;",
      "    cl->RoundRobinFlag = 0;"),
    M("ctor_front_end", "    cl->InFrontEndFlag = 0;",
      "    cl->InFrontEndFlag = 1;"),
    M("ctor_lip", "    cl->LoadingInProgress = 0;" + NL + "}",
      "    cl->LoadingInProgress = 1;" + NL + "}"),
    M("ctor_skins_prev", "    cl->LoadedSkinList.prev = &cl->LoadedSkinList;",
      "    cl->LoadedSkinList.prev = &cl->LoadedCarList;"),
    M("ctor_cars_next", "    cl->LoadedCarList.next = &cl->LoadedCarList;",
      "    cl->LoadedCarList.next = &cl->LoadedSkinList;"),
    M("sinit_none", "    carloader_construct(&TheCarLoader);", "    ;"),
    M("dtor_no_skins",
      "    while ((n = cl->LoadedSkinList.next) != &cl->LoadedSkinList) {" + NL
      + "        unlink_node(n);" + NL + "        delete_entry(n);" + NL
      + "    }" + NL, ""),
    M("dtor_cars_kept",
      "        delete_entry(n);" + NL + "    }" + NL + "}" + NL,
      "    }" + NL + "}" + NL),
    M("dtor_cars_first",
      "    while ((n = cl->LoadedSkinList.next) != &cl->LoadedSkinList) {",
      "    while ((n = cl->LoadedCarList.next) != &cl->LoadedCarList) {"
      + NL + "        unlink_node(n);" + NL + "        delete_entry(n);"
      + NL + "    }" + NL
      + "    while ((n = cl->LoadedSkinList.next) != &cl->LoadedSkinList) {"),
    M("init_slots", "bNewSlotPool(48, 42,", "bNewSlotPool(48, 40,"),
    M("init_memory_pool", "\"LoadedCarSlotPool\", 16);",
      "\"LoadedCarSlotPool\", 0);"),
    M("close_kept", "    LoadedCarSlotPool = NULL;", ""),

    # LoadedSkin.
    M("skin_ctor_count", "    s->NumInstances = 0;" + NL + "    s->Loading = 0;",
      "    s->Loading = 0;"),
    M("skin_ctor_loading", "    s->Loading = 0;" + NL + "    s->Loaded = 0;"
      + NL + "    return s;", "    s->Loaded = 0;" + NL + "    return s;"),
    M("skin_ctor_loaded", "    s->Loaded = 0;" + NL + "    return s;",
      "    return s;"),
    M("skin_ctor_ride", "    s->TheRideInfo = *ri;",
      "    s->TheRideInfo.Type = ri->Type;"
      + NL + "    s->TheRideInfo.SkinNumber = ri->SkinNumber;"),
    M("tex_every_skin", "SkinNumber == -1) {", "SkinNumber < 0) {"),
    M("tex_num_skins", "i < cartypeinfo_get_num_skins(ct); i++)",
      "i <= cartypeinfo_get_num_skins(ct); i++)"),
    M("tex_skin_kept", "        s->TheRideInfo.SkinNumber = -1;" + NL
      + "        return num;", "        return num;"),
    M("tex_every_max", "            num = loadedskin_get_used_textures(s, tex, "
      "num, max,", "            num = loadedskin_get_used_textures(s, tex, "
      "num, CARLOADER_MAX_TEXTURES,"),
    M("tex_every_fe", "num, max," + NL + "                                   "
      "            in_front_end);", "num, max," + NL
      + "                                               0);"),
    M("tex_fe", "&s->TheRideInfo," + NL + "                                   "
      "       in_front_end);", "&s->TheRideInfo," + NL
      + "                                          0);"),
    M("tex_no_dedupe", "            if (tex[j] == h) {", "            if (0) {"),
    M("tex_dedupe_short", "for (j = 0; j < num; j++)",
      "for (j = 0; j < num - 1; j++)"),
    M("tex_cap", "if (!(num < max))", "if (num > max)"),
    M("tex_cap_continue", "            return num;" + NL
      + "        tex[num++] = h;", "            continue;" + NL
      + "        tex[num++] = h;"),
    M("tex_append_skip", "        tex[num++] = h;", "        tex[num] = h;"),

    # LoadedCar and the lookups.
    M("car_ctor_count", "    c->NumInstances = 0;" + NL + "    c->Loading = 0;",
      "    c->Loading = 0;"),
    M("car_ctor_loading", "    c->Loading = 0;" + NL + "    c->Loaded = 0;"
      + NL + "    c->pResourceFile", "    c->Loaded = 0;" + NL
      + "    c->pResourceFile"),
    M("car_ctor_loaded", "    c->Loaded = 0;" + NL + "    c->pResourceFile = "
      "NULL;", "    c->pResourceFile = NULL;"),
    M("car_ctor_file", "    c->pResourceFile = NULL;" + NL + "    return c;",
      "    return c;"),
    M("find_car_prefix", "strcmp(c->GeometryFilename, name) == 0",
      "strncmp(c->GeometryFilename, name, 16) == 0"),
    M("find_skin_any_type", "s->TheRideInfo.Type == type && ", ""),
    M("find_skin_any_skin", " && s->TheRideInfo.SkinNumber == skin)", ")"),

    # Load, IsLoaded and Unload.
    M("load_body_plain", "car = want_car(cl, ct->CompressedGeometryFilename);",
      "car = want_car(cl, ct->GeometryFilename);"),
    M("load_dash_plain", "        want_car(cl, ct->CompressedDashGeometryFilename);",
      "        want_car(cl, ct->DashGeometryFilename);"),
    M("load_dash_always", "    if (ri->HasDash)" + NL + "        want_car(cl, ",
      "    want_car(cl, "),
    M("load_dash_not_kept", "        skin->TheRideInfo.HasDash = 1;", ""),
    M("load_skin_count", "    skin->NumInstances++;", ""),
    M("want_count", "    c->NumInstances++;" + NL + "    return c;",
      "    return c;"),
    M("load_answer_after", "return car->NumInstances - 1;",
      "return car->NumInstances;"),
    M("load_answer_unsigned", "return car->NumInstances - 1;",
      "return (uint8_t)car->NumInstances - 1;"),
    M("loaded_body_any", "    if (c == NULL || (!requested && !c->Loaded))"
      + NL + "        return 0;", "    if (c == NULL)" + NL
      + "        return 0;"),
    M("loaded_no_dash", "    if (ri->HasDash) {" + NL + "        c = ",
      "    if (0) {" + NL + "        c = "),
    M("loaded_dash_any", "        if (c == NULL || (!requested && "
      "!c->Loaded))", "        if (c == NULL)"),
    M("loaded_skin_null", "    if (s == NULL)" + NL + "        return 0;"
      + NL + "    if (requested)", "    if (requested)"),
    M("loaded_requested", "    if (requested)" + NL + "        return 1;"
      + NL, ""),
    M("loaded_skin_any", "return s->Loaded != 0;", "return 1;"),
    M("unload_loaded", "if (!carloader_is_loaded(cl, ri, 1))",
      "if (!carloader_is_loaded(cl, ri, 0))"),
    M("unload_dash_always", "    if (ri->HasDash)" + NL
      + "        carloader_find_loaded_car(cl, ct->CompressedDash",
      "    carloader_find_loaded_car(cl, ct->CompressedDash"),
    M("unload_skin_kept", "    carloader_find_loaded_skin(cl, ri->Type, "
      "ri->SkinNumber)->NumInstances--;", ""),
    M("unload_no_remove", "    carloader_remove_unused_cars_and_skins(cl);"
      + NL + "}" + NL + NL + "void carloader_unload_everything",
      "}" + NL + NL + "void carloader_unload_everything"),

    # UnloadEverything and RemoveUnusedCarsAndSkins.
    M("everything_cars", "        ((LoadedCar *)(void *)n)->NumInstances = 0;",
      "        ;"),
    M("everything_skins", "        ((LoadedSkin *)(void *)n)->NumInstances = "
      "0;", "        ;"),
    M("everything_first_remove", "    carloader_remove_unused_cars_and_skins"
      "(cl);" + NL + "    // What was loading", "    // What was loading"),
    M("everything_cars_only", "    while (cl->LoadedCarList.next != "
      "&cl->LoadedCarList" + NL + "           || cl->LoadedSkinList.next != "
      "&cl->LoadedSkinList) {", "    while (cl->LoadedCarList.next != "
      "&cl->LoadedCarList) {"),
    M("everything_spin", "        gServiceResourceLoadingFn();" + NL
      + "        carloader_remove_unused_cars_and_skins(cl);",
      "        gServiceResourceLoadingFn();"),
    M("remove_car_negative", "        if (c->NumInstances != 0)",
      "        if (c->NumInstances > 0)"),
    M("remove_car_loaded", "        if (c->Loaded) {", "        if (0) {"),
    M("remove_car_loaded_kept", "            c->Loaded = 0;" + NL + "        }",
      "        }"),
    M("remove_car_loading", "        if (!c->Loading) {" + NL
      + "            unlink_node(node);", "        {" + NL
      + "            unlink_node(node);"),
    M("remove_skin_negative", "        if (s->NumInstances != 0)",
      "        if (s->NumInstances > 0)"),
    M("remove_skin_loaded", "        if (s->Loaded) {", "        if (0) {"),
    M("remove_skin_loaded_kept", "            s->Loaded = 0;" + NL + "        }",
      "        }"),
    M("remove_skin_loading", "        if (!s->Loading) {", "        {"),
    M("remove_fe", "cl->InFrontEndFlag);" + NL + "            s->Loaded = 0;",
      "0);" + NL + "            s->Loaded = 0;"),
    M("remove_empty_unload", "    if (n != 0 && gUnloadTexturesFromFileFn",
      "    if (gUnloadTexturesFromFileFn"),
    M("max_textures", "#define CARLOADER_MAX_TEXTURES 512",
      "#define CARLOADER_MAX_TEXTURES 511"),

    # BeginLoading.
    M("begin_callback_null", "    if (callback != NULL)" + NL
      + "        cl->pCallback = callback;", "    cl->pCallback = callback;"),
    M("begin_callback_late", "    if (callback != NULL)" + NL
      + "        cl->pCallback = callback;" + NL
      + "    if (cl->LoadingInProgress)" + NL + "        return;",
      "    if (cl->LoadingInProgress)" + NL + "        return;" + NL
      + "    if (callback != NULL)" + NL + "        cl->pCallback = callback;"),
    M("begin_no_guard", "    if (cl->LoadingInProgress)" + NL
      + "        return;" + NL, ""),
    M("begin_skin_loading", "        if (!s->Loading && !s->Loaded) {",
      "        if (!s->Loaded) {"),
    M("begin_skin_loaded", "        if (!s->Loading && !s->Loaded) {",
      "        if (!s->Loading) {"),
    M("begin_skin_flag", "            s->Loading = 1;" + NL
      + "            any = 1;", "            any = 1;"),
    M("begin_rr_ignored", "        if (any && cl->RoundRobinFlag)",
      "        if (any)"),
    M("begin_rr_never", "        if (any && cl->RoundRobinFlag)" + NL
      + "            break;", ""),
    M("begin_fe", "cl->InFrontEndFlag);" + NL + "        }",
      "0);" + NL + "        }"),
    M("begin_tex_lip", "        cl->LoadingInProgress = 1;" + NL
      + "        if (gLoadTexturesFromFileFn", "        if (gLoadTextures"
      "FromFileFn"),
    M("begin_tex_param", "                                    (intptr_t)cl);"
      + NL + "        return;", "                                    "
      "(intptr_t)&TheCarLoader);" + NL + "        return;"),
    M("begin_tex_falls", "                                    (intptr_t)cl);"
      + NL + "        return;" + NL + "    }", "                         "
      "           (intptr_t)cl);" + NL + "    }"),
    M("begin_car_loading", "        if (!c->Loading && !c->Loaded) {",
      "        if (!c->Loaded) {"),
    M("begin_car_loaded", "        if (!c->Loading && !c->Loaded) {",
      "        if (!c->Loading) {"),
    M("begin_car_lip", "            cl->LoadingInProgress = 1;" + NL
      + "            c->Loading = 1;", "            c->Loading = 1;"),
    M("begin_car_flag", "            c->Loading = 1;" + NL
      + "            c->pResourceFile", "            c->pResourceFile"),
    M("begin_car_type", "#define CARLOADER_RESOURCE_TYPE 5",
      "#define CARLOADER_RESOURCE_TYPE 4"),
    M("begin_car_arg", "#define CARLOADER_RESOURCE_ARG  8",
      "#define CARLOADER_RESOURCE_ARG  0"),
    M("begin_car_param", "                                         "
      "(intptr_t)cl);", "                                         "
      "(intptr_t)&TheCarLoader);"),
    M("begin_every_car", "                                         "
      "(intptr_t)cl);" + NL + "            return;",
      "                                         (intptr_t)cl);"),
    M("begin_car_file", "            c->pResourceFile = gCarLoadResourceFileFn"
      " == NULL ? NULL" + NL + "                : ",
      "            if (gCarLoadResourceFileFn != NULL)" + NL
      + "                (void)"),

    # LoadingDoneCallback and the bridge.
    M("done_skin_loading", "            s->Loading = 0;" + NL
      + "            s->Loaded = 1;", "            s->Loaded = 1;"),
    M("done_skin_loaded", "            s->Loading = 0;" + NL
      + "            s->Loaded = 1;", "            s->Loading = 0;"),
    M("done_car_loading", "            c->Loading = 0;" + NL
      + "            c->Loaded = 1;", "            c->Loaded = 1;"),
    M("done_car_loaded", "            c->Loading = 0;" + NL
      + "            c->Loaded = 1;", "            c->Loading = 0;"),
    M("done_lip", "    cl->LoadingInProgress = 0;" + NL
      + "    carloader_remove", "    carloader_remove"),
    M("done_no_remove", "    carloader_remove_unused_cars_and_skins(cl);"
      + NL + "    carloader_begin_loading(cl, NULL);",
      "    carloader_begin_loading(cl, NULL);"),
    M("done_begin_first", "    carloader_remove_unused_cars_and_skins(cl);"
      + NL + "    carloader_begin_loading(cl, NULL);",
      "    carloader_begin_loading(cl, NULL);" + NL
      + "    carloader_remove_unused_cars_and_skins(cl);"),
    M("done_no_begin", "    carloader_begin_loading(cl, NULL);" + NL
      + "    if (", "    if ("),
    M("done_callback_always", "    if (!cl->LoadingInProgress && "
      "cl->pCallback != NULL) {", "    if (cl->pCallback != NULL) {"),
    M("done_callback_kept", "        cl->pCallback = NULL;" + NL
      + "        cb();", "        cb();"),
    M("done_callback_cleared_late", "        cl->pCallback = NULL;" + NL
      + "        cb();", "        cb();" + NL + "        cl->pCallback = "
      "NULL;"),
    M("bridge_global", "carloader_loading_done_callback((CarLoader *)param);",
      "carloader_loading_done_callback(&TheCarLoader);"),

    # CarTypeInfo's two getters.
    M("num_skins_cop", "    if (ct->UsageType == CAR_USAGE_TYPE_COP)" + NL
      + "        return 1;" + NL + "    return ct->NumAvailableSkins;",
      "    return ct->NumAvailableSkins;", CTI),
    M("skin_number_cop", "    if (ct->UsageType == CAR_USAGE_TYPE_COP) {"
      + NL + "        int32_t lang", "    if (0) {" + NL
      + "        int32_t lang", CTI),
    M("skin_number_lang", "return lang != 0 ? 2 : 1;",
      "return lang > 0 ? 2 : 1;", CTI),
    M("skin_number_lang_swapped", "return lang != 0 ? 2 : 1;",
      "return lang != 0 ? 1 : 2;", CTI),
    M("skin_number_wrap", "AvailableSkins[i % ct->NumAvailableSkins]",
      "AvailableSkins[i]", CTI),
]

EQUIVALENT = {
    "tex_cap_continue":
        "nothing follows the stop: past the cap every texture is either "
        "found and skipped or not appended, so both return the same count",
    "remove_car_loaded_kept":
        "a loaded car is never loading -- BeginLoading only starts one "
        "that is not loaded -- so it is freed just after, and the pool "
        "fills its slot again before any reuse",
    "remove_skin_loaded_kept":
        "as remove_car_loaded_kept, for a skin",
    "begin_skin_loading":
        "a skin is only ever loading while LoadingInProgress is set, and "
        "the guard returns first; LoadingDoneCallback clears every "
        "Loading before it clears the flag",
    "begin_car_loading":
        "as begin_skin_loading, for a car",
    "everything_spin":
        "the service completes a load through LoadingDoneCallback, which "
        "runs RemoveUnusedCarsAndSkins itself; with every count 0 nothing "
        "new starts, so the loop's own call never finds anything left",
    "skin_number_wrap":
        "the loader's only caller keeps i below NumAvailableSkins, and the "
        "getter has no other caller",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    hostbuild.recover()
    m = Model()
    sc = script()
    base = m.run(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for mut in todo:
        name, rel, before, after = mut
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-36s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-36s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-36s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-36s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-36s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-36s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-36s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    m = Model()
    sc = script()
    lines = m.run(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
