#!/usr/bin/env python3
"""Cross-check 3DS Files/source/dmreplay.c, the attract mode's replays,
against the retail image, SLES_507.31 (TASKS 72h-2a).

**The model** is retail's DemoModeReplay (0x0013ee08 .. 0x0013f6c0) on
TheDemoModeReplay (0x002f0960), run in retail_model.RetailEmu: the
constructor, slot 29's loader and unloader (through their wrappers), the
filenames, the resource file's load, unload and callback,
ConsiderLaunching, Launch, RestoreRaceParametersSnapshot, the demo's
begin, test, service and end, Service, the recording and the erase. Under
them run Timer::SetTime, bSPrintf and bList::TraversebList. The harness
(tools/src/dmreplay_test.c) runs dmreplay.c.

**The stubs** print what they are asked, on both sides. The ReplayManager
is a fake of eight slots, each with a name and its four times, held in
order: FindSnapshot, TakeSnapshot (which can fail), DeleteSnapshot by
name and by snapshot, RestoreSnapshot by name and the sort. Then the
coordinator's PostMessage, RaceParameters' InitWithDefaults and
DoSnapshot (which moves DataPosition on 52 and sets
TakingSnapshotFlag, so the restore's clear shows), LoadResourceFile,
FindResourceFile and UnloadResourceFile over a count of files,
bFileExists, bRandom, Save and bRefreshTweaker.

**What is made equal by hand.** Retail's ConsiderLaunching asks
TheDemoDiscManager first (0x002effe0), which the model keeps 0, as the
retail disc does. RestoreRaceParametersSnapshot reads the list's first
with no test, so the script calls it only with a snapshot on the list.
Retail calls the manager and the coordinator with no test, and the port
answers "none" without them: the script always has both. Launch with no
info reads 0 from low memory, which the model zeroes, and so unloads, as
the port does.

**The script** runs the constructor; every filename index over the
edges; the loader and unloader over each type and the list's orders;
the resource file over the counts; ConsiderLaunching over the files,
the tweaker, the draw and bFileExists; Launch over the info; the
restore; the demo's service forward and back over the snapshots;
TestGoesOn over the ends, the erase and the lengths; Service over the
recording, the erase's three seconds, a failed take and the tweakers;
the recording's 30 loops; the erase; and then random states and calls.

    python tools/dmreplay_check.py
    python tools/dmreplay_check.py --mutate [--only a,b] [--jobs N]
    python tools/dmreplay_check.py --dump out/dmreplay
"""
import argparse
import os
import random
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

HARNESS = "tools/src/dmreplay_test.c"
_S = "3DS Files/source/"
DMR = _S + "dmreplay.c"
SOURCES = [HARNESS, DMR, _S + "bprintf.c", _S + "timer.c", _S + "p32.c"]

GP = retail_model.RETAIL_GP
TDMR = 0x002f0960               # TheDemoModeReplay
DEMO_DISC = 0x002effe0          # TheDemoDiscManager.bActive
RP = 0x0031a898                 # TheRaceParameters
RP_DEMO = RP + 28               # ReplayDemoMode
WORLD_LOOP = GP - 19552
WORLD_TIMER = GP - 19576
P_RM = GP - 22440               # pReplayManager
P_RC = GP - 22216               # pRaceCoordinator

F = dict(
    ctor=0x0013ee08, loader=0x0013ef70, unloader=0x0013ef98,
    base=0x0013efc0, genname=0x0013efe0,
    loadres=0x0013f070, unloadres=0x0013f0c0, cb=0x0013f110,
    consider=0x0013f120, launch=0x0013f1c0, restore=0x0013f220,
    begin=0x0013f288, numsnaps=0x0013f2c8, cantest=0x0013f2d0,
    begintest=0x0013f300, goeson=0x0013f310, servicedemo=0x0013f430,
    end=0x0013f4f0, service=0x0013f500, beginrec=0x0013f660,
    endrec=0x0013f670, erase=0x0013f6c0)
RETURNS = {"consider", "numsnaps", "cantest", "goeson"}
ARGS = {"servicedemo", "service", "endrec"}

S_FIND = 0x0013e5c8             # ReplayManager::FindSnapshot
S_SORT = 0x0013e690
S_RESTORE_NAMED = 0x0013e748
S_DELETE_NAMED = 0x0013e790
S_DELETE = 0x0013e7d8
S_TAKE = 0x0013e9f0
S_POST = 0x001496d8             # RaceCoordinator::PostMessage
S_RP_INIT = 0x001ed5c8          # RaceParameters::InitWithDefaults
S_RP_SNAP = 0x001ed6f8          # RaceParameters::DoSnapshot
S_LOADRES = 0x00199640          # LoadResourceFile
S_UNLOADRES = 0x00199728        # UnloadResourceFile
S_FINDRES = 0x00199890          # FindResourceFile
S_EXISTS = 0x002545b8           # bFileExists
S_RANDOM = 0x0025a488           # bRandom(int)
S_SAVE = 0x0013f7e8             # DemoModeReplay::Save
S_REFRESH = 0x0025d2c8          # bRefreshTweaker

SLOTS = 8
SLOT_SIZE = 400
CHUNKS = 6
CHUNK_SIZE = 8 + 400
LOW = 4096

T_INFO, T_SNAP, T_REPEAT = 0x39100, 0x39101, 0x39102
OTHER_TYPES = (0, 0x39103, 0x390ff, 0x80039100, 0x39000)

NAMES = ("DEMO_MODE_SNAPSHOT", "REPLAY_MANAGER_STATE", "OTHER")
DMS, RMS, OTH = 0, 1, 2

FIELDS = ("ctor wt wlc active loading loaded file rec erase recsnap playnum "
          "playsnap twfile twsave twerase info repeat rpdemo takefail "
          "exists rand nres iver inew8").split()
NOSLOT = (-1, 0, 0, 0, 0)

EDGES = (0, 1, -1, 2, 5, 6, 7, 0x7fffffff, -0x80000000)


# ---------------------------------------------------------------- the script

def base_state(**kw):
    st = dict(ctor=0, wt=40000, wlc=600, active=0, loading=0, loaded=0,
              file=0, rec=0, erase=0, recsnap=-1, playnum=0, playsnap=-1,
              twfile=-1, twsave=0, twerase=0, info=-1, repeat=-1, rpdemo=0,
              takefail=0, exists=1, rand=2, nres=0, iver=8, inew8=1,
              slots=[NOSLOT] * SLOTS)
    for k, v in kw.items():
        assert k in st, k
        st[k] = v
    return st


def slot(name, t=0, end=0, begin=0, endloop=0):
    return (name, t, end, begin, endloop)


def demo_slots(*spec):
    s = list(spec) + [NOSLOT] * (SLOTS - len(spec))
    return s[:SLOTS]


class Script(object):
    def __init__(self):
        self.ops = []
        self.on_list = set()

    def state(self, **kw):
        st = base_state(**kw)
        if st["ctor"]:
            self.on_list = set()
        self.ops.append(("state", st))

    def load(self, k, t):
        if t == T_SNAP:
            assert k != 0 and k not in self.on_list
            self.on_list.add(k)
        self.ops.append(("load", (k, t)))

    def unload(self, k, t):
        if t == T_SNAP:
            self.on_list.discard(k)
        self.ops.append(("unload", (k, t)))

    def base(self, i):
        self.ops.append(("base", i))

    def ctor(self):
        self.on_list = set()
        self.ops.append(("ctor", None))

    def call(self, name, arg=None):
        if name == "restore":
            assert self.on_list
        self.ops.append(("call", (name, arg)))


def script():
    sc = Script()

    # The constructor, over a state with every word set, and then each
    # call on a fresh object.
    sc.state(ctor=1)
    sc.load(1, T_SNAP)
    sc.load(2, T_SNAP)
    sc.state(active=1, loading=1, loaded=1, file=3, rec=1, erase=1,
             recsnap=2, playnum=4, playsnap=1, twfile=2, twsave=1,
             twerase=1, info=0, repeat=4, slots=demo_slots(slot(DMS)))
    sc.ctor()
    sc.state(ctor=1)
    sc.call("numsnaps")
    for i in EDGES + (3, 4, -2, 0x100):
        sc.base(i)

    # The loader and unloader.
    sc.state(ctor=1)
    sc.load(0, T_INFO)
    sc.load(4, T_REPEAT)
    for k in (1, 2, 3):
        sc.load(k, T_SNAP)
    for t in OTHER_TYPES:
        sc.load(5, t)
        sc.unload(5, t)
    sc.unload(2, T_SNAP)
    sc.unload(2, T_SNAP)
    sc.load(2, T_SNAP)
    sc.unload(1, T_SNAP)
    sc.unload(3, T_SNAP)
    sc.unload(2, T_SNAP)
    sc.unload(5, T_SNAP)
    sc.load(5, T_SNAP)
    sc.load(3, T_SNAP)
    sc.load(1, T_SNAP)
    sc.unload(0, T_INFO)
    sc.unload(4, T_REPEAT)
    sc.load(1, T_INFO)
    sc.load(3, T_REPEAT)
    sc.unload(1, T_INFO)
    sc.unload(5, T_SNAP)
    sc.unload(1, T_SNAP)
    sc.unload(3, T_SNAP)
    sc.unload(4, T_INFO)

    # The resource file.
    for loaded in (0, 1, 7):
        for nres in (0, 1, 3):
            for f in (0, 1, 3, 5, 6, -1):
                sc.state(loaded=loaded, nres=nres, file=f, loading=loaded ^ 1)
                sc.call("loadres")
                sc.call("unloadres")
    sc.state(loading=1, loaded=0)
    sc.call("cb")

    # ConsiderLaunching.
    for f in (0, 1, 2, 4, 5, 6, 9, -1, -3, 0x7fffffff):
        for tw in (-1, 0, 3, 5, 6, -2):
            for ex in (1, 0):
                sc.state(file=f, twfile=tw, exists=ex, rand=(f + tw) % 5)
                sc.call("consider")
    for r in (0, 1, 4, 5, -1, 0x7fffffff):
        sc.state(file=0, rand=r)
        sc.call("consider")

    # Launch.
    for info in (0, -1):
        for iver, inew8 in ((8, 1), (8, 0), (7, 1), (8, 2), (9, 1), (0, 0)):
            for loaded, nres in ((1, 1), (0, 1), (1, 0)):
                sc.state(info=info, iver=iver, inew8=inew8, loaded=loaded,
                         nres=nres)
                sc.call("launch")

    # The restore, from the list's first.
    sc.state(ctor=1)
    sc.load(2, T_SNAP)
    sc.load(1, T_SNAP)
    for rp in (0, 1, 5):
        sc.state(rpdemo=rp)
        sc.call("restore")
    sc.unload(2, T_SNAP)
    sc.call("restore")
    sc.load(3, T_SNAP)
    sc.call("restore")
    sc.unload(1, T_SNAP)
    sc.call("restore")

    # The demo: begin, test, service forward and back, end.
    mixes = [
        demo_slots(),
        demo_slots(slot(DMS, 100, 9000, 10, 70)),
        demo_slots(slot(RMS), slot(DMS, 100, 9000, 10, 70),
                   slot(DMS, 9000, 20000, 70, 200)),
        demo_slots(slot(DMS, 1), slot(OTH), slot(DMS, 2), slot(RMS),
                   slot(DMS, 3), slot(DMS, 4)),
    ]
    for sl in mixes:
        for pn in (-1, 0, 1, 2, 3, 5, -3, 0x7fffffff):
            for fn in ("servicedemo", "servicedemo0", "begin", "begintest"):
                sc.state(slots=sl, playnum=pn, playsnap=0)
                if fn == "servicedemo":
                    sc.call("servicedemo", 1)
                elif fn == "servicedemo0":
                    sc.call("servicedemo", 0)
                else:
                    sc.call(fn)
        sc.state(slots=sl, playnum=2, playsnap=1, active=1)
        sc.call("cantest")
        sc.call("end")

    # TestGoesOn.
    for erase in (0, 1):
        for wlc in (69, 70, 71, 300):
            for t0, t1 in ((100, 9000), (100, 9001), (100, 8099),
                           (100, 8100), (0, 7999), (5000, 4000),
                           (-0x80000000, 0x7fffffff)):
                for wt in (4000, 4099, 4100, 4101, 4500, 4549, 4550, 4551,
                           8000, 9000, 20000):
                    sl = demo_slots(slot(DMS, t0, t1, 10, 70),
                                    slot(RMS),
                                    slot(DMS, 9000, 20000, 70, 200))
                    sc.state(slots=sl, playnum=0, playsnap=0, erase=erase,
                             wlc=wlc, wt=wt)
                    sc.call("goeson")
    for erase in (0, 1):
        for pn in (0, 1):
            sl = demo_slots(slot(DMS, 0, 100000, 10, 70))
            sc.state(slots=sl, playnum=pn, playsnap=0, erase=erase,
                     wlc=70, wt=50000)
            sc.call("goeson")
            sc.state(slots=sl, playnum=pn, playsnap=-1, erase=erase)
            sc.call("goeson")

    # Service.
    for arg in (0, 1):
        for rec, recsnap in ((0, -1), (1, -1), (1, 2), (0, 2)):
            for erase, playsnap in ((0, -1), (1, -1), (1, 0), (0, 0)):
                for wt in (11999, 12099, 12100, 12101, 30000):
                    for fail in (0, 1):
                        sl = demo_slots(slot(DMS, 100, 50000, 3, 400),
                                        slot(RMS, 50, 60, 1, 2),
                                        slot(DMS, 7, 8, 1, 2))
                        sc.state(slots=sl, rec=rec, recsnap=recsnap,
                                 erase=erase, playsnap=playsnap, wt=wt,
                                 wlc=wt // 67, takefail=fail)
                        sc.call("service", arg)
    for tws, twe in ((1, 0), (0, 1), (1, 1), (5, -1)):
        sl = demo_slots(slot(DMS), slot(RMS), slot(DMS), slot(OTH))
        sc.state(slots=sl, twsave=tws, twerase=twe, playsnap=0, recsnap=2,
                 rec=1)
        sc.call("service", 0)
    for arg in (2, -1):
        sl = demo_slots(slot(DMS, 100, 200, 1, 2))
        sc.state(slots=sl, rec=1, erase=1, playsnap=0, wt=500)
        sc.call("service", arg)

    # The recording.
    for recsnap in (-1, 0):
        for wlc in (39, 40, 41, 42, 1000, -0x80000000):
            sl = demo_slots(slot(DMS, 0, 0, 10, 0), slot(RMS))
            sc.state(slots=sl, rec=1, recsnap=recsnap, wlc=wlc)
            sc.call("endrec", 1)
    sc.state()
    sc.call("beginrec")

    # The erase.
    for sl in mixes + [demo_slots(slot(RMS), slot(RMS), slot(DMS))]:
        sc.state(slots=sl, rec=1, recsnap=0, playsnap=1)
        sc.call("erase")

    # Random states and calls.
    rnd = random.Random(72082)
    calls = sorted(F.keys() - {"ctor", "loader", "unloader", "base",
                               "genname"})
    for _ in range(400):
        sl = []
        for k in range(SLOTS):
            if rnd.random() < 0.55:
                t0 = rnd.choice((0, rnd.randrange(0, 60000),
                                 rnd.getrandbits(32) - (1 << 31)))
                sl.append(slot(rnd.choice((DMS, DMS, RMS, OTH)), t0,
                               t0 + rnd.choice((0, 7999, 8000, 30000,
                                                rnd.randrange(-500, 90000))),
                               rnd.randrange(0, 500), rnd.randrange(0, 900)))
            else:
                sl.append(NOSLOT)
        ptrs = [-1] + [k for k in range(SLOTS) if sl[k][0] >= 0] + \
               [100 + k for k in sorted(sc.on_list)]
        sc.state(
            ctor=1 if rnd.random() < 0.05 else 0,
            wt=rnd.choice((rnd.randrange(0, 90000),
                           rnd.getrandbits(32) - (1 << 31))),
            wlc=rnd.randrange(-5, 1200), active=rnd.randrange(2),
            loading=rnd.randrange(2), loaded=rnd.randrange(2),
            file=rnd.randrange(-2, 8), rec=rnd.randrange(2),
            erase=rnd.randrange(2), recsnap=rnd.choice(ptrs),
            playnum=rnd.randrange(-2, 6), playsnap=rnd.choice(ptrs),
            twfile=rnd.randrange(-2, 7), twsave=rnd.randrange(2),
            twerase=rnd.choice((0, 0, 1)), info=rnd.choice((-1, 0)),
            repeat=rnd.choice((-1, 4)), rpdemo=rnd.randrange(2),
            takefail=rnd.choice((0, 0, 1)), exists=rnd.randrange(2),
            rand=rnd.randrange(0, 5), nres=rnd.randrange(0, 3),
            iver=rnd.choice((8, 8, 7)), inew8=rnd.choice((1, 1, 0)),
            slots=sl)
        for _ in range(rnd.randrange(1, 5)):
            c = rnd.random()
            if c < 0.12:
                k = rnd.randrange(1, CHUNKS)
                if k in sc.on_list:
                    sc.unload(k, T_SNAP)
                else:
                    sc.load(k, T_SNAP)
            elif c < 0.16:
                k = rnd.randrange(CHUNKS)
                t = rnd.choice((T_INFO, T_REPEAT) + OTHER_TYPES)
                (sc.load if rnd.randrange(2) else sc.unload)(k, t)
            else:
                name = rnd.choice(calls)
                if name == "restore" and not sc.on_list:
                    name = "end"
                sc.call(name, rnd.choice((0, 1, 1, 2)) if name in ARGS
                        else None)
    return sc.ops


def to_s32(v):
    return s32(v & M32)


def write_script(tmp, ops):
    lines = []
    for kind, v in ops:
        if kind == "state":
            w = [str(to_s32(v[f])) for f in FIELDS]
            for s in v["slots"]:
                w += [str(to_s32(x)) for x in s]
            lines.append("state " + " ".join(w))
        elif kind in ("load", "unload"):
            lines.append("%s %d %d" % (kind, v[0], v[1] & M32))
        elif kind == "base":
            lines.append("base %d" % to_s32(v))
        elif kind == "ctor":
            lines.append("ctor")
        else:
            name, arg = v
            lines.append("call %s" % name if arg is None
                         else "call %s %d" % (name, to_s32(arg)))
    path = Path(tmp) / "script.txt"
    path.write_text(NL.join(lines) + NL)
    return path


# ================================================================ the model

def s8(v):
    return v - 256 if v & 0x80 else v


class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu()
        self.out = []
        self.slots = self.zalloc(SLOTS * SLOT_SIZE)
        self.chunks = [self.zalloc(CHUNK_SIZE) for _ in range(CHUNKS)]
        self.rm = self.zalloc(16)
        self.rc = self.zalloc(16)
        self.rf = self.zalloc(256)
        self.buf = self.zalloc(256)
        self.slot_name = [-1] * SLOTS
        self.order = []
        self.takefail = self.exists = self.rand = self.nres = 0
        e.put32(P_RM, self.rm)
        e.put32(P_RC, self.rc)
        e.put32(DEMO_DISC, 0)
        for a, fn in ((S_FIND, self.find), (S_TAKE, self.take),
                      (S_DELETE_NAMED, self.delete_named),
                      (S_DELETE, self.delete),
                      (S_RESTORE_NAMED, self.restore_named),
                      (S_SORT, self.sort), (S_POST, self.post),
                      (S_RP_INIT, self.rp_init), (S_RP_SNAP, self.rp_snap),
                      (S_LOADRES, self.loadres), (S_FINDRES, self.findres),
                      (S_UNLOADRES, self.unloadres), (S_EXISTS, self.fexists),
                      (S_RANDOM, self.random), (S_SAVE, self.save),
                      (S_REFRESH, self.refresh)):
            e.stub(a, fn)

    def zalloc(self, n):
        p = self.e.alloc(n, 16)
        self.e.write(p, bytes(n))
        return p

    def cstr(self, a, n=256):
        if a == 0:
            return "NULL"
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def slot_addr(self, k):
        return self.slots + SLOT_SIZE * k

    def body(self, k):
        return self.chunks[k] + 8

    def label(self, p):
        if p == 0:
            return "NULL"
        for k in range(SLOTS):
            if p == self.slot_addr(k):
                return "S%d" % k
        for k in range(CHUNKS):
            if p == self.body(k):
                return "C%d" % k
        return "?"

    def slot_of(self, p):
        for k in range(SLOTS):
            if p == self.slot_addr(k):
                return k
        return -1

    def name_code(self, a):
        n = self.cstr(a)
        return NAMES.index(n) if n in NAMES[:2] else OTH, n

    def rm_tag(self):
        return "" if self.arg(0) == self.rm else " rm?"

    def remove(self, k):
        self.order = [i for i in self.order if i != k]
        self.slot_name[k] = -1

    # ---- the stubs

    def find(self, e):
        code, n = self.name_code(self.arg(1))
        k = s32(self.arg(2))
        hit = [i for i in self.order if self.slot_name[i] == code]
        s = self.slot_addr(hit[k]) if 0 <= k < len(hit) else 0
        self.out.append("  find%s %s %d %s" % (
            self.rm_tag(), n if code == OTH else NAMES[code], k,
            self.label(s)))
        return s

    def take(self, e):
        code, n = self.name_code(self.arg(1))
        s = 0
        if not self.takefail:
            free = [k for k in range(SLOTS) if self.slot_name[k] < 0]
            if free:
                k = free[0]
                s = self.slot_addr(k)
                self.slot_name[k] = code
                self.order.append(k)
                wt, wlc = e.u32(WORLD_TIMER), e.u32(WORLD_LOOP)
                for off, v in ((40, wt), (44, wt), (48, wlc), (52, wlc)):
                    e.put32(s + off, v)
        self.out.append("  take%s %s %s" % (
            self.rm_tag(), n if code == OTH else NAMES[code], self.label(s)))
        return s

    def delete_named(self, e):
        code, n = self.name_code(self.arg(1))
        for k in self.order:
            if self.slot_name[k] == code:
                self.out.append("  delete%s %s S%d" % (self.rm_tag(),
                                                       NAMES[code], k))
                self.remove(k)
                return 1
        self.out.append("  delete%s %s none" % (
            self.rm_tag(), n if code == OTH else NAMES[code]))
        return 0

    def delete(self, e):
        s = self.arg(1)
        self.out.append("  delete%s %s" % (self.rm_tag(), self.label(s)))
        k = self.slot_of(s)
        if k >= 0:
            self.remove(k)

    def restore_named(self, e):
        code, n = self.name_code(self.arg(1))
        self.out.append("  restore%s %s" % (
            self.rm_tag(), n if code == OTH else NAMES[code]))
        return 1

    def sort(self, e):
        code, n = self.name_code(self.arg(1))
        self.out.append("  sort%s %s" % (
            self.rm_tag(), n if code == OTH else NAMES[code]))

    def post(self, e):
        p = self.arg(2)
        k = self.slot_of(p)
        self.out.append("  post%s %d %s" % (
            "" if self.arg(0) == self.rc else " rc?", s32(self.arg(1)),
            "S%d" % k if k >= 0 else "?"))

    def rp_init(self, e):
        self.out.append("  rp init%s" % ("" if self.arg(0) == RP else " ?"))

    def rp_snap(self, e):
        s = self.arg(1)
        pos = s32(e.u32(s + 336))
        self.out.append("  rp snap%s %s pos %d take %d restore %d" % (
            "" if self.arg(0) == RP else " ?", self.label(s), pos,
            s8(e.u8(s + 60)), s8(e.u8(s + 61))))
        e.put32(s + 336, pos + 52)
        e.write(s + 60, bytes([7]))

    def loadres(self, e):
        self.out.append("  loadres %s %d %d %s %s" % (
            self.cstr(self.arg(0)), s32(self.arg(1)), s32(self.arg(2)),
            "cb" if self.arg(3) == F["cb"] else "?",
            "this" if self.arg(4) == TDMR else "?"))
        return 0

    def findres(self, e):
        self.out.append("  findres %d %d" % (s32(self.arg(0)), self.nres))
        return self.rf + 16 * self.nres if self.nres > 0 else 0

    def unloadres(self, e):
        self.out.append("  unloadres R%d" % ((self.arg(0) - self.rf) // 16))
        self.nres -= 1

    def fexists(self, e):
        self.out.append("  exists %s" % self.cstr(self.arg(0)))
        return 1 if self.exists else 0

    def random(self, e):
        self.out.append("  random %d" % s32(self.arg(0)))
        return self.rand

    def save(self, e):
        self.out.append("  save")

    def refresh(self, e):
        self.out.append("  refresh")

    # ---- the dump

    def w(self, off):
        return s32(self.e.u32(TDMR + off))

    def dump(self):
        e = self.e
        self.out.append(
            "  obj %d %d %d file %d rec %d erase %d %s play %d %s tw %d %d %d"
            " info %s repeat %s rpdemo %d nres %d" % (
                self.w(0), self.w(4), self.w(8), self.w(12), self.w(16),
                self.w(20), self.label(self.w(24) & M32), self.w(28),
                self.label(self.w(32) & M32), self.w(36), self.w(40),
                self.w(44), self.label(self.w(48) & M32),
                self.label(self.w(52) & M32), s32(e.u32(RP_DEMO)), self.nres))
        line = "  slots"
        for k in self.order:
            a = self.slot_addr(k)
            line += " S%d:%d:%d:%d:%d:%d" % (
                k, self.slot_name[k], s32(e.u32(a + 40)), s32(e.u32(a + 44)),
                s32(e.u32(a + 48)), s32(e.u32(a + 52)))
        self.out.append(line)
        head = TDMR + 56
        if e.u32(head) == 0 and e.u32(head + 4) == 0:
            self.out.append("  list none")
            return
        line = "  list"
        a, prev = e.u32(head), head
        i = 0
        while a != head and i < 16:
            line += " %s:%d:%d:%d:%d:%d%s" % (
                self.label(a), s32(e.u32(a + 56)), s32(e.u32(a + 336)),
                s32(e.u32(a + 340)), s8(e.u8(a + 60)), s8(e.u8(a + 61)),
                "" if e.u32(a + 4) == prev else ":prev?")
            prev, a = a, e.u32(a)
            i += 1
        line += "" if e.u32(head + 4) == prev else " tail?"
        self.out.append(line)

    # ---- the ops

    def ptr(self, v):
        if v < 0:
            return 0
        if v >= 100:
            return self.body(v - 100)
        return self.slot_addr(v)

    def state(self, st):
        e = self.e
        e.write(0, bytes(LOW))
        if st["ctor"]:
            e.call(F["ctor"], TDMR)
        e.put32(WORLD_TIMER, st["wt"])
        e.put32(WORLD_LOOP, st["wlc"])
        for off, v in ((0, st["active"]), (4, st["loading"]),
                       (8, st["loaded"]), (12, st["file"]), (16, st["rec"]),
                       (20, st["erase"]), (24, self.ptr(st["recsnap"])),
                       (28, st["playnum"]), (32, self.ptr(st["playsnap"])),
                       (36, st["twfile"]), (40, st["twsave"]),
                       (44, st["twerase"]),
                       (48, self.body(st["info"]) if st["info"] >= 0 else 0),
                       (52, self.body(st["repeat"])
                        if st["repeat"] >= 0 else 0)):
            e.put32(TDMR + off, v)
        e.put32(RP_DEMO, st["rpdemo"])
        self.takefail = st["takefail"]
        self.exists = st["exists"]
        self.rand = st["rand"]
        self.nres = st["nres"]
        e.put32(self.body(0), st["iver"])
        e.put32(self.body(0) + 8, st["inew8"])
        self.order = []
        for k, (name, t0, t1, b, el) in enumerate(st["slots"]):
            a = self.slot_addr(k)
            self.slot_name[k] = name
            for off, v in ((40, t0), (44, t1), (48, b), (52, el)):
                e.put32(a + off, v)
            if name >= 0:
                self.order.append(k)
        self.out.append("state")
        self.dump()

    def chunk(self, k, t, unload):
        e = self.e
        e.put32(self.chunks[k], t)
        r = e.call(F["unloader" if unload else "loader"], self.chunks[k])
        self.out.append("%s C%d %d" % ("unload" if unload else "load", k,
                                       t & M32))
        self.out.append("  ret %d" % r)
        self.dump()

    def base(self, i):
        e = self.e
        p = e.call(F["base"], TDMR, i) & M32
        e.write(self.buf, bytes(64))
        e.call(F["genname"], TDMR, self.buf, i)
        self.out.append("base %d %s [%s]" % (to_s32(i), self.cstr(p),
                                             self.cstr(self.buf)))

    def call(self, name, arg):
        self.out.append("call %s%s" % (name, "" if arg is None
                                       else " %d" % to_s32(arg)))
        args = (TDMR,) if arg is None else (TDMR, arg)
        r = self.e.call(F[name], *args)
        self.out.append("  ret %d" % (r if name in RETURNS else 0))
        self.dump()

    def run(self, ops):
        for kind, v in ops:
            if kind == "state":
                self.state(v)
            elif kind == "load":
                self.chunk(v[0], v[1], 0)
            elif kind == "unload":
                self.chunk(v[0], v[1], 1)
            elif kind == "base":
                self.base(v)
            elif kind == "ctor":
                self.e.call(F["ctor"], TDMR)
                self.out.append("ctor")
                self.dump()
            else:
                self.call(*v)
        self.out.append("faults 0")
        return self.out


def model(ops):
    return Model().run(ops)


# ---------------------------------------------------------------- running

diff = pcc.diff


def run_harness(exe, script, out, timeout=120):
    return mutpar.run_exe([exe, script], out, timeout)


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern
# is spelled to match code and not a comment.

def M(name, before, after):
    return (name, DMR, before, after)


MUTATIONS = [
    # -- the constructor
    M("ctor-tw", "    d->TweakerSnapshotFileNumber = -1;\n    list_init",
      "    d->TweakerSnapshotFileNumber = 0;\n    list_init"),
    M("ctor-no-list", "    list_init((ReplayLink *)(void *)DemoModeReplay_SnapshotList);\n",
      ""),
    M("ctor-active", "    DemoModeReplayActiveFlag = 0;\n    d->LoadingFlag = 0;",
      "    d->LoadingFlag = 0;"),
    M("ctor-file", "    d->CurrentSnapshotFileNumber = 0;\n    d->WantTo",
      "    d->WantTo"),
    M("ctor-erase", "    DemoModeReplay_WantToBeErasingSnapshot = 0;\n"
      "    DemoModeReplay_pCurrentRecordingSnapshot = NULL;\n    DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n    d->Tweaker",
      "    DemoModeReplay_pCurrentRecordingSnapshot = NULL;\n    DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n    d->Tweaker"),
    M("ctor-repeat", "    d->pInfo = NULL;\n    DemoModeReplay_pRepeat = 0;",
      "    d->pInfo = NULL;"),
    # -- the loader and unloader
    M("load-info-at", "TheDemoModeReplay.pInfo = (const DemoModeReplayInfo *)(chunk + 8);",
      "TheDemoModeReplay.pInfo = (const DemoModeReplayInfo *)(chunk + 16);"),
    M("load-no-mil", "        s->MemoryImageLoadedFlag = 1;\n", ""),
    M("load-head", "list_add_tail(demo_list(), (ReplayLink *)(void *)s);",
      "{ ReplayLink *l = demo_list(), *h = link_at(l->Next); h->Prev = p32_of(s);"
      " ((ReplayLink *)(void *)s)->Next = p32_of(h); ((ReplayLink *)(void *)s)->Prev = p32_of(l);"
      " l->Next = p32_of(s); }"),
    M("load-repeat-at", "DemoModeReplay_pRepeat = p32_of(chunk + 8);",
      "DemoModeReplay_pRepeat = p32_of(chunk);"),
    M("load-ret0", "    if (type == CHUNK_REPEAT) {\n        DemoModeReplay_pRepeat = p32_of(chunk + 8);\n        return 1;",
      "    if (type == CHUNK_REPEAT) {\n        DemoModeReplay_pRepeat = p32_of(chunk + 8);\n        return 0;"),
    M("load-other-1", "        DemoModeReplay_pRepeat = p32_of(chunk + 8);\n        return 1;\n    }\n    return 0;",
      "        DemoModeReplay_pRepeat = p32_of(chunk + 8);\n        return 1;\n    }\n    return 1;"),
    M("unload-no-test", "        if (list_has(demo_list(), n))\n            list_unlink(n);",
      "        list_unlink(n);"),
    M("unload-info", "        TheDemoModeReplay.pInfo = NULL;\n", ""),
    M("unload-repeat", "        DemoModeReplay_pRepeat = 0;\n        return 1;",
      "        return 1;"),
    M("unload-other-1", "        DemoModeReplay_pRepeat = 0;\n        return 1;\n    }\n    return 0;",
      "        DemoModeReplay_pRepeat = 0;\n        return 1;\n    }\n    return 1;"),
    M("has-first", "    for (a = link_at(l->Next); a != l; a = link_at(a->Next))\n        if (a == n)\n            return 1;\n    return 0;",
      "    a = link_at(l->Next);\n    return a == n;"),
    # -- the filenames
    M("base-6", "if ((uint32_t)i >= DEMO_MODE_REPLAY_NUM_FILES)",
      "if ((uint32_t)i > DEMO_MODE_REPLAY_NUM_FILES)"),
    M("base-signed", "if ((uint32_t)i >= DEMO_MODE_REPLAY_NUM_FILES)",
      "if (i >= DEMO_MODE_REPLAY_NUM_FILES)"),
    M("base-1", "        i = 0;\n    return DemoModeReplayFilenames[i];",
      "        i = 1;\n    return DemoModeReplayFilenames[i];"),
    M("name-swap", "    \"JUL23\\\\T12YellowSpider.bin\",\n    \"JUL23\\\\T62OrangeF1LM.bin\",",
      "    \"JUL23\\\\T62OrangeF1LM.bin\",\n    \"JUL23\\\\T12YellowSpider.bin\","),
    M("genname-dir", "\"REPLAY\\\\%s\"", "\"REPLAY/%s\""),
    # -- the resource file
    M("loadres-flag", "    TheDemoModeReplay.LoadingFlag = 1;\n", ""),
    M("loadres-type", "load_resource_file(name, RESOURCE_FILE_REPLAY, 0,",
      "load_resource_file(name, RESOURCE_FILE_REPLAY, 1,"),
    M("unloadres-test", "    if (!TheDemoModeReplay.LoadedFlag)\n        return;\n", ""),
    M("unloadres-flag", "        unload_resource_file(rf);\n    TheDemoModeReplay.LoadedFlag = 0;",
      "        unload_resource_file(rf);"),
    M("unloadres-once", "    while ((rf = find_resource_file_by_type(RESOURCE_FILE_REPLAY)) != NULL)",
      "    if ((rf = find_resource_file_by_type(RESOURCE_FILE_REPLAY)) != NULL)"),
    M("cb-loading", "    TheDemoModeReplay.LoadingFlag = 0;\n    TheDemoModeReplay.LoadedFlag = 1;",
      "    TheDemoModeReplay.LoadedFlag = 1;"),
    # -- ConsiderLaunching
    M("consider-always-random", "    if (d->CurrentSnapshotFileNumber != 0)\n",
      "    if (0)\n"),
    M("consider-random-0", "add32(bRandomI(5, &bDefaultSeed), 1)",
      "bRandomI(5, &bDefaultSeed)"),
    M("consider-random-6", "bRandomI(5, &bDefaultSeed)", "bRandomI(6, &bDefaultSeed)"),
    M("consider-tw-gt", "if (d->TweakerSnapshotFileNumber >= 0)",
      "if (d->TweakerSnapshotFileNumber > 0)"),
    M("consider-wrap-gt", "if (d->CurrentSnapshotFileNumber >= DEMO_MODE_REPLAY_NUM_FILES)",
      "if (d->CurrentSnapshotFileNumber > DEMO_MODE_REPLAY_NUM_FILES)"),
    M("consider-wrap-0", "        d->CurrentSnapshotFileNumber = 1;\n    dmreplay_generate",
      "        d->CurrentSnapshotFileNumber = 0;\n    dmreplay_generate"),
    M("consider-no-exists", "if (name[0] == 0 || bFileSizeName(name) < 0)",
      "if (name[0] == 0)"),
    M("consider-size-0", "bFileSizeName(name) < 0", "bFileSizeName(name) <= 1000"),
    M("consider-no-load", "    dmreplay_load_resource_file();\n    return 1;", "    return 1;"),
    # -- Launch
    M("launch-ver", "info->VersionNumber == 8", "info->VersionNumber >= 8"),
    M("launch-new8", "info->New8 == 1)", "info->New8 != 0)"),
    M("launch-no-unload", "    else\n        dmreplay_unload_resource_file();\n}",
      "}"),
    # -- the restore
    M("restore-pos", "    s->DataPosition = 0;\n    s->RestoringSnapshotFlag = 1;",
      "    s->RestoringSnapshotFlag = 1;"),
    M("restore-flag", "    s->RestoringSnapshotFlag = 1;\n    race_parameters_init",
      "    race_parameters_init"),
    M("restore-no-init", "    race_parameters_init_with_defaults(&TheRaceParameters);\n", ""),
    M("restore-demo", "    TheRaceParameters.ReplayDemoMode = 1;\n", ""),
    M("restore-size", "    s->SizeofData = s->DataPosition;\n", ""),
    M("restore-take", "    s->TakingSnapshotFlag = 0;\n}", "}"),
    M("restore-last", "    s = (ReplaySnapshot *)(void *)link_at(l->Next);",
      "    s = (ReplaySnapshot *)(void *)link_at(l->Prev);"),
    # -- the demo
    M("begin-num", "void dmreplay_begin_demo_mode(void)\n{\n    TheDemoModeReplay.PlayingSnapshotNumber = -1;",
      "void dmreplay_begin_demo_mode(void)\n{\n    TheDemoModeReplay.PlayingSnapshotNumber = 0;"),
    M("begin-no-restore", "        replaymgr_restore_snapshot_named(pReplayManager,\n"
      "                                         REPLAY_MANAGER_STATE_NAME);",
      "        ;"),
    M("begin-back", "                                         REPLAY_MANAGER_STATE_NAME);\n    dmreplay_service_demo_mode(1);",
      "                                         REPLAY_MANAGER_STATE_NAME);\n    dmreplay_service_demo_mode(0);"),
    M("numsnaps", "    return DEMO_MODE_REPLAY_NUM_FILES;\n}", "    return 5;\n}"),
    M("cantest-1", "    return find_demo(0) != NULL;", "    return find_demo(1) != NULL;"),
    M("begintest-num", "void dmreplay_begin_demo_mode_test(void)\n{\n    TheDemoModeReplay.PlayingSnapshotNumber = -1;",
      "void dmreplay_begin_demo_mode_test(void)\n{\n    TheDemoModeReplay.PlayingSnapshotNumber = 0;"),
    M("svc-fwd-skip", "        s = find_demo(add32(d->PlayingSnapshotNumber, 1));\n        if (s == NULL)\n            return;",
      "        s = find_demo(add32(d->PlayingSnapshotNumber, 1));"),
    M("svc-fwd-2", "        s = find_demo(add32(d->PlayingSnapshotNumber, 1));",
      "        s = find_demo(add32(d->PlayingSnapshotNumber, 2));"),
    M("svc-back-ge", "} else if (d->PlayingSnapshotNumber > 0) {",
      "} else if (d->PlayingSnapshotNumber >= 0) {"),
    M("svc-back-keep", "        s = find_demo(d->PlayingSnapshotNumber - 1);\n        d->PlayingSnapshotNumber--;",
      "        s = find_demo(d->PlayingSnapshotNumber - 1);\n        if (s != NULL)\n            d->PlayingSnapshotNumber--;"),
    M("svc-first-1", "    } else {\n        s = find_demo(0);", "    } else {\n        s = find_demo(1);"),
    M("svc-no-play", "    DemoModeReplay_pCurrentPlayingSnapshot = s;\n    if (pRaceCoordinator",
      "    if (pRaceCoordinator"),
    M("svc-msg", "RC_MOVE_REPLAY,\n", "RC_QUIT_RACE,\n"),
    M("end-active", "    DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n    DemoModeReplayActiveFlag = 0;",
      "    DemoModeReplay_pCurrentPlayingSnapshot = NULL;"),
    M("end-num", "    TheDemoModeReplay.PlayingSnapshotNumber = 0;\n}", "}"),
    # -- TestGoesOn
    M("goes-gt", "if (s != NULL && WorldLoopCounter >= s->EndLoopTime)",
      "if (s != NULL && WorldLoopCounter > s->EndLoopTime)"),
    M("goes-next-1", "        if (s == NULL)\n            return 0;\n    }\n    if (!Demo",
      "        if (s == NULL)\n            return 1;\n    }\n    if (!Demo"),
    M("goes-erase-0", "        return 1;\n    t = (float)", "        return 0;\n    t = (float)"),
    M("goes-len", "    if (t < 2.0f) {", "    if (t <= 2.0f) {"),
    M("goes-len-3", "    if (t < 2.0f) {", "    if (t < 3.0f) {"),
    M("goes-no-delete", "        delete_snapshot(DemoModeReplay_pCurrentPlayingSnapshot);\n        TheDemo",
      "        TheDemo"),
    M("goes-num", "        TheDemoModeReplay.PlayingSnapshotNumber =\n            sub32(TheDemoModeReplay.PlayingSnapshotNumber, 1);\n",
      ""),
    M("goes-half", "timer_set_time(&half, t * 0.5f);", "timer_set_time(&half, t * 0.25f);"),
    M("goes-half-le", "if (sub32(s->EndTime, (int32_t)half.PackedTime) < WorldTimer) {",
      "if (sub32(s->EndTime, (int32_t)half.PackedTime) <= WorldTimer) {"),
    M("goes-half-from", "if (sub32(s->EndTime, (int32_t)half.PackedTime) < WorldTimer) {",
      "if (add32(s->Time, (int32_t)half.PackedTime) < WorldTimer) {"),
    M("goes-end-loop", "            DemoModeReplay_pCurrentPlayingSnapshot->EndLoopTime =\n                WorldLoopCounter;\n",
      ""),
    M("goes-end-time", "            DemoModeReplay_pCurrentPlayingSnapshot->EndTime = WorldTimer;\n", ""),
    M("goes-keep", "            DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n        }\n    }",
      "        }\n    }"),
    M("goes-tail-1", "    dmreplay_service_demo_mode(1);\n    return 0;\n}",
      "    dmreplay_service_demo_mode(1);\n    return 1;\n}"),
    M("goes-tail-back", "    dmreplay_service_demo_mode(1);\n    return 0;\n}",
      "    dmreplay_service_demo_mode(0);\n    return 0;\n}"),
    M("goes-wrap", "    t = (float)sub32(s->EndTime, s->Time) * SECONDS_PER_TICK;",
      "    t = ((float)s->EndTime - (float)s->Time) * SECONDS_PER_TICK;"),
    # -- Service
    M("svc-arg", "    if (snapshot_this_loop) {", "    if (1) {"),
    M("svc-rec-test", "        if (d->WantToBeRecordingSnapshot\n            && DemoModeReplay_pCurrentRecordingSnapshot == NULL) {",
      "        if (d->WantToBeRecordingSnapshot) {"),
    M("svc-rec-nodelete", "            delete_named(REPLAY_MANAGER_STATE_NAME);\n            take(",
      "            take("),
    M("svc-rec-norms", "            take(REPLAY_MANAGER_STATE_NAME);\n            DemoModeReplay_pCurrentRecordingSnapshot =",
      "            DemoModeReplay_pCurrentRecordingSnapshot ="),
    M("svc-rec-name", "            DemoModeReplay_pCurrentRecordingSnapshot =\n                take(DEMO_MODE_SNAPSHOT_NAME);",
      "            DemoModeReplay_pCurrentRecordingSnapshot =\n                take(REPLAY_MANAGER_STATE_NAME);"),
    M("svc-erase-gt", "if (WorldTimer < add32(s->Time, (int32_t)three.PackedTime)) {",
      "if (WorldTimer > add32(s->Time, (int32_t)three.PackedTime)) {"),
    M("svc-erase-le", "if (WorldTimer < add32(s->Time, (int32_t)three.PackedTime)) {",
      "if (WorldTimer <= add32(s->Time, (int32_t)three.PackedTime)) {"),
    M("svc-erase-2s", "timer_set_time(&three, 3.0f);", "timer_set_time(&three, 2.0f);"),
    M("svc-erase-noend", "                    s->EndLoopTime = end_loop;\n", ""),
    M("svc-erase-endtime", "                    s->EndTime = end_time;\n", ""),
    M("svc-erase-nosort", "                    replaymgr_sort_snapshots(pReplayManager,\n"
      "                                             DEMO_MODE_SNAPSHOT_NAME);",
      "                    ;"),
    M("svc-erase-sort-if", "                if (pReplayManager != NULL)\n                    replaymgr_sort",
      "                if (s != NULL)\n                    replaymgr_sort"),
    M("svc-rec-end", "        DemoModeReplay_pCurrentRecordingSnapshot->EndLoopTime =\n            WorldLoopCounter;\n",
      ""),
    M("svc-rec-endtime", "        DemoModeReplay_pCurrentRecordingSnapshot->EndTime = WorldTimer;\n", ""),
    M("svc-save-keep", "            gDemoModeReplaySaveFn();\n        d->TweakerSaveSnapshotFile = 0;",
      "            gDemoModeReplaySaveFn();"),
    M("svc-save-norefresh", "        d->TweakerSaveSnapshotFile = 0;\n        refresh_tweaker();",
      "        d->TweakerSaveSnapshotFile = 0;"),
    M("svc-erase-tw-keep", "        dmreplay_erase_recorded_snapshots();\n        d->TweakerEraseRecordedSnapshots = 0;",
      "        dmreplay_erase_recorded_snapshots();"),
    M("svc-erase-tw-norefresh", "        d->TweakerEraseRecordedSnapshots = 0;\n        refresh_tweaker();",
      "        d->TweakerEraseRecordedSnapshots = 0;"),
    # -- the recording and the erase
    M("rec-1", "    TheDemoModeReplay.WantToBeRecordingSnapshot = 1;\n}",
      "    TheDemoModeReplay.WantToBeRecordingSnapshot = 2;\n}"),
    M("endrec-flag", "    (void)keep;\n    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;",
      "    (void)keep;"),
    M("endrec-30", "if (sub32(WorldLoopCounter, s->BeginLoopTime) < 31)",
      "if (sub32(WorldLoopCounter, s->BeginLoopTime) < 30)"),
    M("endrec-keep", "        delete_snapshot(s);\n    DemoModeReplay_pCurrentRecordingSnapshot = NULL;\n}",
      "        delete_snapshot(s);\n}"),
    M("endrec-wrap", "if (sub32(WorldLoopCounter, s->BeginLoopTime) < 31)",
      "if ((int64_t)WorldLoopCounter - s->BeginLoopTime < 31)"),
    M("erase-once", "    while (delete_named(DEMO_MODE_SNAPSHOT_NAME))\n        ;",
      "    delete_named(DEMO_MODE_SNAPSHOT_NAME);"),
    M("erase-no-rms", "        ;\n    delete_named(REPLAY_MANAGER_STATE_NAME);", "        ;"),
    M("erase-wantrec", "    DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n"
      "    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;\n",
      "    DemoModeReplay_pCurrentPlayingSnapshot = NULL;\n"),
    M("erase-play", "    delete_named(REPLAY_MANAGER_STATE_NAME);\n    DemoModeReplay_pCurrentPlayingSnapshot = NULL;",
      "    delete_named(REPLAY_MANAGER_STATE_NAME);"),
    M("erase-rec", "    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;\n"
      "    DemoModeReplay_pCurrentRecordingSnapshot = NULL;\n}\n",
      "    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;\n}\n"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    ops = script()
    with tempfile.TemporaryDirectory() as data:
        sp = write_script(data, ops)
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="dmreplay_test")
            out = Path(tmp) / "base.txt"
            t0 = time.monotonic()
            rc = run_harness(exe, sp, out)
            took = time.monotonic() - t0
            base = out.read_text(encoding="latin-1").splitlines()
            if rc != 0 or diff(model(ops), base, quiet=True):
                print("base already differs -- fix that before mutating")
                return 1
            print("base: %d lines, 0 differ" % len(base), flush=True)
        limit = mutpar.timeout_for(took)
        tally = mutpar.run_pass(
            todo, SOURCES, "dmreplay_test",
            lambda exe, out: run_harness(exe, sp, out, limit),
            base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    ops = script()
    want = model(ops)
    with tempfile.TemporaryDirectory() as data:
        sp = write_script(data, ops)
        with tempfile.TemporaryDirectory() as tmp:
            exe = hostbuild.build(tmp, SOURCES, name="dmreplay_test")
            out = Path(tmp) / "out.txt"
            rc = run_harness(exe, sp, out)
            got = out.read_text(encoding="latin-1").splitlines()
    if args.dump:
        d = Path(args.dump)
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.txt").write_text(NL.join(want) + NL)
        (d / "harness.txt").write_text(NL.join(got) + NL)
    n = diff(want, got)
    calls = sum(1 for k, _v in ops if k == "call")
    print("dmreplay: %d ops, %d calls, %d lines, %d differ%s"
          % (len(ops), calls, len(want), n, "" if rc == 0 else ", exit %d" % rc))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
