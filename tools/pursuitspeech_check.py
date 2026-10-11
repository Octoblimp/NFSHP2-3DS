#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pursuitspeech.c, tPursuit's speech (14-10a),
and speechconv.c against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: tPursuit's GetChasedCarColour
(0x0022aa20), GetExactDescription (0x0022aa50), the supervisor's test
(0x0022aaf0), RaiseBackupSpeech (0x0022acc0), DeclarePursuitSpeech
(0x0022ad30), BeginPursuitCollisionSpeech (0x0022aef8), StartPursuitSpeech
(0x0022afb8), JoinPursuitSpeech (0x0022b288), RoadblockFailedSpeech
(0x0022b3f8), RoadBlockSetSpeech (0x0022b5d0), CopBackOffSpeech
(0x0022b788), AITicketSpeech (0x0022b840), SuperInitiates (0x0022b908)
and Be A Cop's change of target (0x0022cb30),
with Speech::ConvertCarType (0x002232f8) and its table run for real. The
harness (tools/src/pursuitspeech_test.c) runs the port and prints the same
lines.

**The stubs**, logged and answered by the same rule on both sides:
GetSkinInfo (the one skin), tPursuit's GetCopSpeaker (a counter),
IsPlayerInvolved (the car's player or Be A Cop), GetSpeedMPHOrKPH (a
queue, then an answer), SwitchPursuitState (which sets the state), the
manager's GetCurrentCopSpeaker, NextCopSpeaker and ReserveCopSpeaker
(counters), GetNumTickets, FindLandmark (the one landmark, or none),
CarCausedRecentCollision, bRandom (a queue, then an answer), the speech
manager's FlushQueue, Chopper::FollowThisCar and the 30 raise functions. The car types'
UsageType, the language and the race coordinator's state are memory both
sides read.

**Compared** are the stubs' logs, the three queries' answers and, after
each call, the pursuit's state, sub-state, speakers and two flags.

    python tools/pursuitspeech_check.py
    python tools/pursuitspeech_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
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

HARNESS = "tools/src/pursuitspeech_test.c"
PSP = "3DS Files/source/pursuitspeech.c"
CONV = "3DS Files/source/speechconv.c"
SOURCES = [HARNESS, PSP, CONV]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
RP_FIELDS = {"BeACop": 628, "Players": 48}
G_LANG = 0x0031c1c8                     # CurrLanguage
G_COPMGR = GP - 15620                   # pCopManager
G_SPEECH = GP - 15624                   # the speech manager
G_RC = GP - 22216                       # pRaceCoordinator
G_CTI = GP - 20616                      # CarTypeInfos

F = {
    "colour": 0x0022aa20, "exact": 0x0022aa50, "cansup": 0x0022aaf0,
    "backup": 0x0022acc0, "declare": 0x0022ad30, "collspeech": 0x0022aef8,
    "start": 0x0022afb8, "join": 0x0022b288, "rbfail": 0x0022b3f8,
    "rbset": 0x0022b5d0, "backoff": 0x0022b788, "ticket": 0x0022b840,
    "super": 0x0022b908, "change": 0x0022cb30,
}
RETURNS = ("colour", "exact", "cansup")
F_CONV = 0x002232f8                     # Speech::ConvertCarType

S_SKIN = 0x00188180
S_SPEAKER = 0x0022ab30
S_INVOLVED = 0x0022bbd8
S_SPEED = 0x0022a220
S_SWITCH = 0x00229fe8
S_CUR = 0x002254e8
S_NEXT = 0x00225550
S_RESERVE = 0x002255b8
S_TICKETS = 0x00228520
S_LANDMARK = 0x00228a58
S_COLL = 0x00231118
S_RANDOM = 0x0025a488
S_FLUSH = 0x0020a230
S_FOLLOW = 0x001e7f80                   # Chopper::FollowThisCar

# The raises: the address, the harness's name and the arguments after the
# manager, i an int register in turn and f a float one.
RAISES = (
    (0x0020a5e0, "id_general", "iii"),
    (0x0020a640, "id_specific", "iiii"),
    (0x0020a710, "id_repeated", "iiii"),
    (0x0020a6b0, "again", "iii"),
    (0x0020a4c0, "erratic", "i"),
    (0x0020a480, "general", "i"),
    (0x0020a500, "no_id", "i"),
    (0x0020ab40, "avoidance", "i"),
    (0x0020a430, "cop_hit_run", "ii"),
    (0x0020a590, "hit_run_traffic", "ii"),
    (0x0020a850, "backup_request", "i"),
    (0x0020a8e0, "backup_request_location", "ii"),
    (0x0020a890, "backup_confirm", "ii"),
    (0x0020ac40, "suspect_found", "iii"),
    (0x0020b028, "rotor_spike_failed", "ii"),
    (0x0020b290, "spike_strip_failure", "iii"),
    (0x0020b0e0, "rb_failure_through", "iii"),
    (0x0020b080, "rb_failure_avoid", "iii"),
    (0x0020b190, "request_another", "ii"),
    (0x0020b340, "spike_set", "iii"),
    (0x0020b400, "spike_set_right", "iii"),
    (0x0020b3a0, "spike_set_left", "iii"),
    (0x0020b240, "rb_setting", "ii"),
    (0x0020b1e0, "rb_set", "iii"),
    (0x0020ae68, "cop_back_off", "ii"),
    (0x0020ae60, "super_back_off", ""),
    (0x0020af08, "radio_arrest", "i"),
    (0x0020aeb8, "car_stopped", "ii"),
    (0x0020a7f0, "speed_raise", "if"),
    (0x0020b4f0, "super_initiate", "ifiii"),
)

MGR_SIZE, PURSUIT_SIZE, CAR_SIZE, CTI_SIZE = 10516, 1600, 2304, 1376
NP, NCARS, NRB, NTYPES, QN = 3, 4, 2, 73, 16
CTI_USAGE = 1336
SK_PAINT, LM_TYPE = 40, 52
RB_SIDE, RB_POS, RB_SPEAKER = 48, 68, 116
C_RIDE, C_DRIVER, C_PLAYER = 16, 20, 24
D_TYPE = 8                              # retail's DriverInfo.TheDriverType
P_FIELDS = ((16, "chased"), (20, "rb"), (1476, "ncops"), (1484, "state"),
            (1488, "sub"), (1496, "prim"), (1500, "sec"), (1504, "lm"),
            (1508, "joined"), (1512, "hit"), (1580, "chopper"),
            (1588, "flags"))


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def Fx(f):
    return "0x%08x" % fbits(f)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True)
        self.out = []
        self.names = {}

        def block(n, nm):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            if nm:
                self.names[p] = nm
            return p
        self.m = block(MGR_SIZE, "M")
        e.put32(G_COPMGR, self.m)
        self.speech = block(16, "SP")
        e.put32(G_SPEECH, self.speech)
        self.rc = block(16, "RC")
        e.put32(G_RC, self.rc)
        cti = block(NTYPES * CTI_SIZE, None)
        self.cti = cti + 2 * CTI_SIZE
        e.put32(G_CTI, self.cti)
        self.skin = block(64, "SK")
        self.lm = block(64, "L")
        self.chopper = block(16, "H")
        self.lm_on = 0
        self.player = block(16, "PL")
        self.rbs = [block(128, "RB%d" % k) for k in range(NRB)]
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.rides = [block(16, "R%d" % k) for k in range(NCARS)]
        self.drivers = [block(32, "D%d" % k) for k in range(NCARS)]
        for c, r, d in zip(self.cars, self.rides, self.drivers):
            e.put32(c + C_RIDE, r)
            e.put32(c + C_DRIVER, d)
        self.spk = self.cur = self.res = 0
        self.tickets = 0
        self.coll = -1
        self.randq, self.randqi, self.rand = [], 0, 0
        self.speedq, self.speedqi, self.speed = [], 0, 0
        for addr, fn in ((S_SKIN, self.s_skin),
                         (S_SPEAKER, self.s_speaker),
                         (S_INVOLVED, self.s_involved),
                         (S_SPEED, self.s_speed),
                         (S_SWITCH, self.s_switch),
                         (S_CUR, self.s_cur),
                         (S_NEXT, self.s_next),
                         (S_RESERVE, self.s_reserve),
                         (S_TICKETS, self.s_tickets),
                         (S_LANDMARK, self.s_landmark),
                         (S_COLL, self.s_coll),
                         (S_RANDOM, self.s_random),
                         (S_FLUSH, self.s_flush),
                         (S_FOLLOW, self.s_follow)):
            e.stub(addr, fn)
        for addr, nm, args in RAISES:
            e.stub(addr, self.raiser(nm, args))

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def mgr_ok(self, em):
        return "" if em.reg[4] & M32 == self.speech else " ?mgr"

    # ---- stubs

    def raiser(self, nm, args):
        def fn(em):
            ir, fr, vals = 5, 12, []
            for k in args:
                if k == "i":
                    vals.append("%d" % s32(em.reg[ir]))
                    ir += 1
                else:
                    vals.append("%08x" % (em.fpr[fr] & M32))
                    fr += 1
            self.emit("  %s%s%s" % (nm, self.mgr_ok(em),
                                    "".join(" " + v for v in vals)))
        return fn

    def s_skin(self, em):
        self.emit("  skin %d %d %d -> SK" % (
            s32(em.reg[4]), s32(em.reg[5]), s32(em.reg[6])))
        return self.skin

    def s_speaker(self, em):
        r = self.spk
        self.spk = (self.spk + 1) & M32
        self.emit("  speaker %s -> %08x" % (self.sym(em.reg[4]), r))
        return r

    def s_involved(self, em):
        e = self.e
        p = em.reg[4] & M32
        car = e.u32(p + 16)
        r = int(e.u32(car + C_PLAYER) != 0
                or e.u32(RP + RP_FIELDS["BeACop"]) != 0)
        self.emit("  involved %s -> %d" % (self.sym(p), r))
        return r

    def s_speed(self, em):
        if self.speedqi < len(self.speedq):
            r = self.speedq[self.speedqi]
            self.speedqi += 1
        else:
            r = self.speed
        self.emit("  speed %s -> %08x" % (self.sym(em.reg[4]), r))
        em.fpr[0] = r

    def s_switch(self, em):
        p = em.reg[4] & M32
        self.emit("  switch %s %d" % (self.sym(p), s32(em.reg[5])))
        self.e.put32(p + 1484, em.reg[5] & M32)

    def s_cur(self, em):
        self.emit("  cur %s -> %08x" % (self.sym(em.reg[4]), self.cur))
        return self.cur

    def s_next(self, em):
        self.emit("  next %s" % self.sym(em.reg[4]))
        self.cur = (self.cur + 1) & M32

    def s_reserve(self, em):
        r = self.res
        self.res = (self.res + 1) & M32
        self.emit("  reserve %s -> %08x" % (self.sym(em.reg[4]), r))
        return r

    def s_tickets(self, em):
        self.emit("  tickets %s %s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.tickets))
        return self.tickets

    def s_landmark(self, em):
        pos = em.reg[4] & M32
        r = self.lm if self.lm_on else 0
        self.emit("  landmark %08x %08x -> %s" % (
            self.e.u32(pos), self.e.u32(pos + 4), self.sym(r)))
        return r

    def s_coll(self, em):
        r = self.cars[self.coll] if self.coll >= 0 else 0
        self.emit("  collision %s -> %s" % (self.sym(em.reg[4]),
                                            self.sym(r)))
        return r

    def s_random(self, em):
        if self.randqi < len(self.randq):
            r = self.randq[self.randqi]
            self.randqi += 1
        else:
            r = self.rand
        self.emit("  random %d -> %d" % (s32(em.reg[4]), r))
        return r

    def s_follow(self, em):
        self.emit("  follow %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))

    def s_flush(self, em):
        self.emit("  flush%s" % self.mgr_ok(em))

    # ---- dumps

    def pdump(self, k):
        e = self.e
        p = self.ps[k]
        self.emit("U%d state %d sub %d prim %08x sec %08x joined %d hit %d"
                  % (k, s32(e.u32(p + 1484)), s32(e.u32(p + 1488)),
                     e.u32(p + 1496), e.u32(p + 1500),
                     s32(e.u32(p + 1508)), s32(e.u32(p + 1512))))

    # ---- ops

    def idx(self, lst, s):
        k = int(s, 0)
        return lst[k] if k >= 0 else 0

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        if o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "lang":
            e.put32(G_LANG, v(1))
        elif o == "rc":
            e.put32(self.rc, v(1))
        elif o == "m":
            e.put32(self.m + (10336 if a[1] == "beacopid" else 10348), v(2))
        elif o == "cti":
            e.put32(self.cti + int(a[1], 0) * CTI_SIZE + CTI_USAGE, v(2))
        elif o == "skin":
            e.put32(self.skin + SK_PAINT, v(1))
        elif o == "lm":
            self.lm_on = int(a[1], 0) >= 0
            e.put32(self.lm + LM_TYPE, v(2))
        elif o == "ride":
            r = self.rides[int(a[1])]
            e.put32(r, v(2))
            e.write(r + 5, bytes([v(3) & 0xff]))
        elif o == "car":
            k = int(a[1])
            e.put32(self.cars[k] + C_PLAYER, self.player if v(2) else 0)
            e.put32(self.drivers[k] + D_TYPE, v(3))
        elif o == "rb":
            b = self.rbs[int(a[1])]
            e.put32(b + RB_SIDE, v(2))
            e.put32(b + RB_POS, v(3))
            e.put32(b + RB_POS + 4, v(4))
            e.put32(b + RB_SPEAKER, v(5))
        elif o == "p":
            p = self.ps[int(a[1])]
            e.put32(p + 16, self.idx(self.cars, a[2]))
            e.put32(p + 20, self.idx(self.rbs, a[3]))
            for j, (off, _) in enumerate(P_FIELDS[2:]):
                e.put32(p + off, v(4 + j))
        elif o == "spk":
            self.spk = v(1)
        elif o == "cur":
            self.cur = v(1)
        elif o == "res":
            self.res = v(1)
        elif o == "tickets":
            self.tickets = s32(v(1))
        elif o == "coll":
            self.coll = int(a[1], 0)
        elif o == "randq":
            self.randq = [s32(v(j)) for j in range(1, len(a))][:QN]
            self.randqi = 0
        elif o == "rand":
            self.rand = s32(v(1))
        elif o == "speedq":
            self.speedq = [v(j) for j in range(1, len(a))][:QN]
            self.speedqi = 0
        elif o == "speed":
            self.speed = v(1)
        elif o == "chop":
            e.put32(self.ps[int(a[1])] + 24,
                    self.chopper if v(2) else 0)
        elif o == "conv":
            r = e.call(F_CONV, v(1), limit=200000)
            self.emit("conv %d -> %d" % (s32(v(1)), s32(r)))
        elif o in F:
            k = int(a[1])
            args = [self.ps[k]]
            if o == "collspeech":
                args.append(self.cars[int(a[2])])
            elif o == "rbfail":
                args.append(v(2))
            elif o == "change":
                args.append(self.cars[int(a[2])])
            r = e.call(F[o], *args, limit=200000)
            if o == "change":
                self.emit("chased U%d %s" % (
                    k, self.sym(e.u32(self.ps[k] + 16))))
            if o in RETURNS:
                self.emit("%s U%d -> %d" % (o, k, s32(r)))
            self.emit("%s U%d" % (o, k))
            self.pdump(k)
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def pset(k, chased=0, rb=0, ncops=1, state=0, sub=0, prim=5, sec=5, lm=0,
         joined=0, hit=0, chopper=0, flags=0):
    return "p|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d|0x%x" % (
        k, chased, rb, ncops, state, sub, prim, sec, lm, joined, hit,
        chopper, flags)


SUPS = (0.0, 0.001, -0.001, 0.0010001, -0.0010001, 5.0, -50.0, -0.0)


def base():
    return ["rp|BeACop|0", "rp|Players|1", "lang|0", "rc|0",
            "m|beacopid|7", "m|super|%s" % Fx(5.0), "skin|3", "lm|-1|0",
            "ride|0|0|0", "ride|1|2|1", "ride|2|15|0", "ride|3|30|2",
            "car|0|1|1", "car|1|0|2", "car|2|0|4", "car|3|1|3",
            "cti|0|0", "cti|2|0", "cti|15|0", "cti|30|1",
            "rb|0|2|%s|%s|1" % (Fx(10.0), Fx(-20.0)),
            "rb|1|1|%s|%s|2" % (Fx(-5.5), Fx(7.25)),
            "spk|0x10", "cur|0x20", "res|0x30", "tickets|0", "coll|-1",
            "randq", "rand|0", "speedq", "speed|%s" % Fx(80.0)]


def query_cases():
    # Speech::ConvertCarType on its own: every type, and past both ends.
    out = ["conv|%d" % t for t in list(range(-5, 76))
           + [0x7fffffff, -0x80000000, 255, 256, -67]]
    # GetExactDescription over every type, usage and language; the colour
    # with the skin numbers' sign.
    for t in range(-2, 71):
        for usage in (0, 1, 2):
            for lang in (0, 1, 2, 3, -1):
                out += ["ride|0|%d|0" % t, "cti|%d|%d" % (t, usage),
                        "lang|%d" % lang, pset(0), "exact|0"]
    out += base()
    for skin in (0, 1, 5, 127, -1, -128, 200):
        for paint in (0, 3, -1, 0x12345):
            out += ["ride|0|7|%d" % skin, "skin|%d" % paint, "colour|0"]
    # The supervisor's test: a car told and not, by the chase's state.
    for t, usage, lang in ((0, 0, 0), (15, 0, 0), (5, 0, 1), (5, 0, 0),
                           (30, 1, 1), (22, 0, 0)):
        for state in range(-2, 8):
            out += base() + ["ride|0|%d|0" % t, "cti|%d|%d" % (t, usage),
                             "lang|%d" % lang, pset(0, state=state),
                             "cansup|0"]
    return out


def backup_cases():
    out = []
    for chased in (0, 1):
        for lm in (0, 4, -3):
            for beacop in (0, 1):
                out += base() + ["rp|BeACop|%d" % beacop,
                                 pset(0, chased=chased, lm=lm), "backup|0"]
    return out


def declare_cases():
    out = []
    for chased in (0, 1):
        for beacop in (0, 1):
            for t, lang in ((0, 0), (15, 0), (5, 2), (5, 0), (30, 0)):
                for r in list(range(40)) + [40, -1]:
                    out += base() + [
                        "rp|BeACop|%d" % beacop, "ride|%d|%d|3" % (chased, t),
                        "lang|%d" % lang, "randq|%d" % r,
                        pset(0, chased=chased), "declare|0"]
    return out


def collision_cases():
    out = []
    for lm in (0, 6):
        for car in (0, 1, 2, 3):
            for dtype in (0, 1, 2, 3, 4, 5, -4, 0x104):
                for state in (0, 1, 2, 3, -1):
                    out += base() + ["car|%d|0|%d" % (car, dtype),
                                     pset(0, lm=lm, state=state),
                                     "collspeech|0|%d" % car]
    return out


def start_cases():
    out = []
    speeds = (Fx(100.0), Fx(100.00001), Fx(99.99999), Fx(150.0),
              Fx(-200.0))
    for beacop in (0, 1):
        for chased in (0, 1):
            for rcs in (0, 7, 8, 9, 10):
                for t in (0, 15, 30):
                    out += base() + [
                        "rp|BeACop|%d" % beacop, "rc|%d" % rcs,
                        "ride|%d|%d|1" % (chased, t),
                        pset(0, chased=chased), "start|0"]
    # A player's chase with no Be A Cop: the collision, the tickets and
    # their draw, the speed and its draw, erratic or general.
    for t in (0, 15):
        for coll in (-1, 1, 2):
            for tickets in (0, 1, 2, -1):
                for r1 in (7, 8, 0):
                    for sp in speeds:
                        for r2 in (6, 7):
                            for r3 in (0, 1):
                                rq = ([r1] if tickets > 0 else []) + [r2, r3]
                                out += base() + [
                                    "ride|0|%d|1" % t, "coll|%d" % coll,
                                    "tickets|%d" % tickets,
                                    "randq|" + "|".join(str(x) for x in rq),
                                    "speedq|%s|%s" % (sp, Fx(123.5)),
                                    pset(0, chased=0, state=0), "start|0"]
    return out


def join_cases():
    out = []
    for chased in (0, 1):
        for prim in (5, 2, 0):
            for lm in (0, 3):
                for t in (0, 15):
                    for sup in (0.0, 5.0, 0.001, -0.0010001):
                        out += base() + [
                            "ride|%d|%d|1" % (chased, t),
                            "m|super|%s" % Fx(sup),
                            pset(0, chased=chased, prim=prim, lm=lm),
                            "join|0"]
    for joined in (0, 1, -1):
        for state in (-1, 0, 1, 3):
            for sec in (5, 1, 6):
                for players in (1, 2, 0):
                    out += base() + [
                        "rp|Players|%d" % players,
                        pset(0, chased=0, prim=1, joined=joined, state=state,
                             sec=sec), "join|0"]
    return out


def rbfail_cases():
    out = []
    for flags in (0, 0x10, 0xffffffef, 0xffffffff, 0x20):
        for chopper in (3, 2, 0):
            for r in (0, 1, 2):
                for b in (0, 1, -1, 2):
                    for beacop in (0, 1):
                        for sup in (0.0, 5.0, -0.001):
                            for spk in (0, 1, 3):
                                out += base() + [
                                    "rp|BeACop|%d" % beacop,
                                    "m|super|%s" % Fx(sup), "spk|%d" % spk,
                                    "randq|%d" % r,
                                    pset(0, rb=r % 2, chopper=chopper,
                                         flags=flags),
                                    "rbfail|0|%d" % b]
    return out


def rbset_cases():
    out = []
    for flags in (0, 0x10, 0xffffffef, 0xffffffff):
        for lmv in (-1, 0, 9):
            for r in (0, 2, 3, 19):
                for side in (0, 1, 2, 3):
                    for sup in (0.0, 5.0):
                        out += base() + [
                            "lm|%d|%d" % (lmv, max(lmv, 0) + 5),
                            "m|super|%s" % Fx(sup), "randq|%d" % r,
                            "rb|1|%d|%s|%s|3" % (side, Fx(1.5), Fx(-2.5)),
                            pset(0, rb=1, flags=flags), "rbset|0"]
    return out


def backoff_cases():
    out = []
    for ncops in (0, 1, 2, -1):
        for sup in SUPS:
            for r in (0, 1, 3):
                out += base() + ["m|super|%s" % Fx(sup), "randq|%d" % r,
                                 pset(0, ncops=ncops), "backoff|0"]
    return out


def ticket_cases():
    out = []
    for rcs in (0, 7, 8, 9, 10):
        for beacop in (0, 1):
            for t in (0, 15, 30):
                for r in (0, 1, 2):
                    out += base() + ["rc|%d" % rcs, "rp|BeACop|%d" % beacop,
                                     "ride|1|%d|0" % t, "randq|%d" % r,
                                     pset(0, chased=1), "ticket|0"]
    return out


def super_cases():
    out = []
    for t in (0, 15, 30, 2):
        for lm in (0, 8):
            for sp in (Fx(0.0), Fx(250.5), Fx(-1.0)):
                out += base() + ["ride|0|%d|4" % t, "skin|%d" % (t + 1),
                                 "speed|%s" % sp, pset(0, lm=lm), "super|0"]
    return out


def change_cases():
    """Be A Cop's change of target: each car (one the cops can tell, one
    they cannot, a cop car), with and without a helicopter, in and out
    of Be A Cop, with each language for the cars only some can tell."""
    out = []
    for beacop in (0, 1):
        for chop in (0, 1):
            for k, chased in ((0, 0), (1, 2), (2, -1)):
                for t in range(NCARS):
                    out += base() + ["rp|BeACop|%d" % beacop,
                                     pset(k, chased=chased),
                                     "chop|%d|%d" % (k, chop),
                                     "change|%d|%d" % (k, t)]
    for lang in range(4):
        for t in (5, 13, 22, 66):
            out += base() + ["lang|%d" % lang, "ride|2|%d|3" % t,
                             "m|beacopid|0x1234", "rp|BeACop|1",
                             pset(0, chased=1), "change|0|2",
                             "chop|0|1", "change|0|1"]
    return out


OPS = ("colour", "exact", "cansup", "backup", "declare", "start", "join",
       "rbfail", "rbset", "backoff", "ticket", "super")


def random_runs(rng):
    """Chases over time: the methods in any order on three chases, with
    the speakers, flags and state carried from one call to the next."""
    out = base()
    for k in range(NP):
        out.append(pset(k, chased=rng.randrange(NCARS), rb=rng.randrange(2)))
    for _ in range(3000):
        r = rng.random()
        if r < 0.05:
            t = rng.choice((0, 2, 5, 6, 13, 15, 16, 22, 30, 43, 48, 49, 66,
                            67))
            out.append("ride|%d|%d|%d" % (rng.randrange(NCARS), t,
                                          rng.randrange(-2, 6)))
        elif r < 0.08:
            out.append("cti|%d|%d" % (rng.randrange(-2, 71),
                                      rng.choice((0, 0, 1, 2))))
        elif r < 0.11:
            out.append("lang|%d" % rng.randrange(5))
        elif r < 0.14:
            out.append("car|%d|%d|%d" % (rng.randrange(NCARS),
                                         rng.randrange(2),
                                         rng.randrange(6)))
        elif r < 0.17:
            out.append("m|super|%s" % Fx(rng.choice(SUPS)))
        elif r < 0.19:
            out.append("rp|BeACop|%d" % (rng.random() < 0.3))
        elif r < 0.21:
            out.append("rp|Players|%d" % rng.choice((1, 1, 2)))
        elif r < 0.23:
            out.append("rc|%d" % rng.choice((0, 0, 3, 8, 9)))
        elif r < 0.26:
            out.append("randq|" + "|".join(
                str(rng.randrange(40)) for _ in range(rng.randrange(1, 5))))
        elif r < 0.28:
            out.append("rand|%d" % rng.randrange(10))
        elif r < 0.30:
            out.append("speedq|" + "|".join(
                Fx(rng.uniform(0, 300)) for _ in range(2)))
        elif r < 0.32:
            out.append("tickets|%d" % rng.randrange(-1, 3))
        elif r < 0.34:
            out.append("coll|%d" % rng.randrange(-1, NCARS))
        elif r < 0.36:
            out.append("lm|%d|%d" % (rng.choice((-1, 0)), rng.randrange(12)))
        elif r < 0.39:
            k = rng.randrange(NP)
            out.append(pset(k, chased=rng.randrange(NCARS),
                            rb=rng.randrange(2), ncops=rng.randrange(3),
                            state=rng.randrange(-1, 5),
                            sub=rng.randrange(3),
                            prim=rng.choice((5, 5, 0, 1, 2, 3)),
                            sec=rng.choice((5, 5, 0, 3)),
                            lm=rng.choice((0, 0, 2, 7)),
                            joined=rng.randrange(2), hit=rng.randrange(2),
                            chopper=rng.randrange(4),
                            flags=rng.choice((0, 0x10, 0x30, 0xff))))
        else:
            o = rng.choice(OPS + ("collspeech", "rbfail", "change"))
            k = rng.randrange(NP)
            if o == "collspeech":
                out.append("collspeech|%d|%d" % (k, rng.randrange(NCARS)))
            elif o == "change":
                out += ["chop|%d|%d" % (k, rng.randrange(2)),
                        "change|%d|%d" % (k, rng.randrange(NCARS))]
            elif o == "rbfail":
                out.append("rbfail|%d|%d" % (k, rng.randrange(2)))
            else:
                out.append("%s|%d" % (o, k))
    return out


def script():
    return (query_cases() + backup_cases() + declare_cases()
            + collision_cases() + start_cases() + join_cases()
            + rbfail_cases() + rbset_cases() + backoff_cases()
            + ticket_cases() + super_cases() + change_cases()
            + random_runs(random.Random(0x14a)))


# ================================================================= running

def build_harness(tmp, name="pursuitspeech_test"):
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


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

P = PSP
C = CONV


CONV_FN = "int32_t speech_convert_car_type(int32_t carType)\n{\n"


def _conv_mutations():
    """Each entry of speechconv.c's car type table changed on its own: a
    set bit moved up one, a 0 made 1. The file's other tables are
    racespeech_check.py's."""
    out = []
    lines = (ROOT / CONV).read_text().splitlines()
    first = next(i for i, ln in enumerate(lines)
                 if ln.startswith("static const uint32_t kCarTypeDescription"))
    last = next(i for i in range(first, len(lines)) if lines[i] == "};")
    for i in range(first + 1, last):
        ln = lines[i]
        if "//" not in ln or not ln.lstrip().startswith(("0x", "0,")):
            continue
        body, row = ln.split("//")
        row = int(row)
        vals = [x.strip() for x in body.split(",") if x.strip()]
        # The rows from the table's name down, so that a row the other
        # tables share is still one place.
        head = NL.join(lines[first:i]) + NL
        for j, x in enumerate(vals):
            n = int(x, 0)
            new = "0x%08x" % (n << 1 if n else 1)
            parts = [y for y in vals]
            parts[j] = new
            after = body.replace(body.strip(), ", ".join(parts) + ",")
            out.append(("cv-t%d" % (row + j), C, head + ln,
                        head + after + "//" + ln.split("//")[1]))
    return out


def _case_mutations():
    """Each case label dropped, and a neighbour added to each group."""
    lang = "    case 5: case 6: case 13: case 14: case 43: case 44:"
    none = "    case 15: case 16: case 22:"
    out = []
    for grp, nm in ((lang, "lang"), (none, "none")):
        labels = grp.strip().split(": ")
        labels = [x.rstrip(":") for x in labels]
        for k, lab in enumerate(labels):
            rest = labels[:k] + labels[k + 1:]
            out.append(("ex-%s-drop%s" % (nm, lab.split()[1]), P, grp,
                        "    " + ": ".join(rest) + ":"))
    out.append(("ex-lang-add7", P, lang, lang + " case 7:"))
    out.append(("ex-lang-add4", P, lang, "    case 4:" + lang[3:]))
    out.append(("ex-none-add23", P, none, none + " case 23:"))
    out.append(("ex-none-add21", P, none, "    case 21:" + none[3:]))
    return out


SPEC_ARGS = ("speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, "
             "exact,\n                                                  "
             "colour);")
MUTATIONS = _conv_mutations() + _case_mutations() + [
    # ---- speechconv.c's bounds
    ("cv-lo", C, CONV_FN + "    if (carType < 0 || carType >= 67)",
     CONV_FN + "    if (carType < 1 || carType >= 67)"),
    ("cv-hi48", C, CONV_FN + "    if (carType < 0 || carType >= 67)",
     CONV_FN + "    if (carType < 0 || carType >= 48)"),
    ("cv-ret", C, CONV_FN + "    if (carType < 0 || carType >= 67)\n"
     "        return 0;", CONV_FN + "    if (carType < 0 || carType >= 67)\n"
     "        return 1;"),
    # ---- the shared tests
    ("sup-le", P, "<= 0.001f;", "< 0.001f;"),
    ("sup-val", P, "<= 0.001f;", "<= 0.002f;"),
    ("sup-abs", P, "fabsf(pCopManager->fSupervisorTimer)",
     "pCopManager->fSupervisorTimer"),
    ("demo-lo", P, "- RCSTATE_AI_DEMO_MODE) < 2u;",
     "- RCSTATE_AI_DEMO_MODE) < 1u;"),
    ("demo-hi", P, "- RCSTATE_AI_DEMO_MODE) < 2u;",
     "- RCSTATE_AI_DEMO_MODE) < 3u;"),
    ("demo-base", P, "- RCSTATE_AI_DEMO_MODE) < 2u;",
     "- RCSTATE_POSTRACE) < 2u;"),
    ("demo-signed", P, "    return (uint32_t)(pRaceCoordinator->"
     "CurrentRCState\n                      - RCSTATE_AI_DEMO_MODE) < 2u;",
     "    return (int32_t)(pRaceCoordinator->CurrentRCState\n"
     "                      - RCSTATE_AI_DEMO_MODE) < 2;"),
    ("rnd-seed", P, "bRandomI(n, &bDefaultSeed)", "bRandomI(n, NULL)"),
    # ---- GetChasedCarColour
    ("col-def", P, "ride->SkinNumber, 1)", "ride->SkinNumber, 0)"),
    ("col-skin", P, "ride->SkinNumber, 1)", "(uint8_t)ride->SkinNumber, 1)"),
    ("col-type", P, "cartypeinfo_get_skin_info(ride->Type,",
     "cartypeinfo_get_skin_info(0,"),
    # ---- GetExactDescription
    ("ex-cop", P, "UsageType == CAR_USAGE_TYPE_COP)",
     "UsageType != CAR_USAGE_TYPE_RACING)"),
    ("ex-copval", P, "        return 0x10000000;", "        return 0x1000000;"),
    ("ex-copoff", P, "    if (cartypeinfo_get(type)->UsageType == "
     "CAR_USAGE_TYPE_COP)\n        return 0x10000000;\n", ""),
    ("ex-lang1", P, "        if (lang == 1 || lang == 2)",
     "        if (lang == 2)"),
    ("ex-lang2", P, "        if (lang == 1 || lang == 2)",
     "        if (lang == 1)"),
    ("ex-lang3", P, "        if (lang == 1 || lang == 2)",
     "        if (lang == 1 || lang == 3)"),
    ("ex-lang-ge", P, "        if (lang == 1 || lang == 2)",
     "        if (lang >= 1)"),
    ("ex-lang-null", P, "gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0",
     "0"),
    ("ex-lang-ret", P, "            return PURSUIT_NO_DESCRIPTION;\n"
     "        break;", "            return 0;\n        break;"),
    ("ex-fall", P, "            return PURSUIT_NO_DESCRIPTION;\n        break;\n"
     "    case 15", "            return PURSUIT_NO_DESCRIPTION;\n    case 15"),
    ("ex-none-ret", P, "    case 15: case 16: case 22:\n        return "
     "PURSUIT_NO_DESCRIPTION;", "    case 15: case 16: case 22:\n        "
     "return 0;"),
    ("ex-conv", P, "    return speech_convert_car_type(type);",
     "    return speech_convert_car_type(type + 1);"),
    # ---- the supervisor's test
    ("cs-noid", P, "== PURSUIT_NO_DESCRIPTION)\n        return 0;",
     "== PURSUIT_NO_DESCRIPTION)\n        return 1;"),
    ("cs-lo", P, "(p->PursuitState - EPS_LEVEL2) < 2u;",
     "(p->PursuitState - EPS_LEVEL1) < 2u;"),
    ("cs-hi", P, "(p->PursuitState - EPS_LEVEL2) < 2u;",
     "(p->PursuitState - EPS_LEVEL2) < 3u;"),
    ("cs-signed", P, "    return (uint32_t)(p->PursuitState - EPS_LEVEL2) "
     "< 2u;", "    return (p->PursuitState - EPS_LEVEL2) < 2;"),
    # ---- RaiseBackupSpeech
    ("bk-player", P, "    if (p->pChasedCar->pPlayer == NULL)\n        "
     "return;\n    if (p->CurrentLandmark != 0) {",
     "    if (p->pChasedCar->pPlayer != NULL)\n        "
     "return;\n    if (p->CurrentLandmark != 0) {"),
    ("bk-player-off", P, "    if (p->pChasedCar->pPlayer == NULL)\n        "
     "return;\n    if (p->CurrentLandmark != 0) {",
     "    if (p->CurrentLandmark != 0) {"),
    ("bk-lm", P, "    if (p->CurrentLandmark != 0) {\n        uint32_t speaker",
     "    if (p->CurrentLandmark > 0) {\n        uint32_t speaker"),
    ("bk-loc", P, "speechmgr_raise_backup_request_location(mgr, speaker,\n"
     "                                                p->CurrentLandmark);",
     "speechmgr_raise_backup_request_location(mgr, speaker, 0);"),
    ("bk-spk", P, "speechmgr_raise_backup_request(mgr, "
     "tpursuit_get_cop_speaker(p));", "speechmgr_raise_backup_request(mgr, "
     "0);"),
    # ---- DeclarePursuitSpeech
    ("dc-inv", P, "    if (!tpursuit_is_player_involved(p))\n        return;",
     "    if (tpursuit_is_player_involved(p))\n        return;"),
    ("dc-noid", P, "    if (exact == PURSUIT_NO_DESCRIPTION) {\n        speaker",
     "    if (exact == 0) {\n        speaker"),
    ("dc-noid-approx", P, "id_general(mgr, speaker, 1, colour);\n        "
     "return;\n    }\n    r = random_below(40);", "id_general(mgr, speaker, "
     "0, colour);\n        return;\n    }\n    r = random_below(40);"),
    ("dc-noid-order", P, "        speaker = tpursuit_get_cop_speaker(p);\n"
     "        colour = tpursuit_get_chased_car_colour(p);\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);\n"
     "        return;\n    }\n    r", "        colour = "
     "tpursuit_get_chased_car_colour(p);\n        speaker = "
     "tpursuit_get_cop_speaker(p);\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);\n"
     "        return;\n    }\n    r"),
    ("dc-40", P, "    r = random_below(40);", "    r = random_below(41);"),
    ("dc-r0", P, "    if (r == 0) {", "    if (r == 1) {"),
    ("dc-17lo", P, "    } else if (r < 17) {", "    } else if (r < 16) {"),
    ("dc-17hi", P, "    } else if (r < 17) {", "    } else if (r < 18) {"),
    ("dc-26lo", P, "    } else if (r < 26) {", "    } else if (r < 25) {"),
    ("dc-26hi", P, "    } else if (r < 26) {", "    } else if (r < 27) {"),
    ("dc-36lo", P, "    } else if (r < 36) {", "    } else if (r < 35) {"),
    ("dc-36hi", P, "    } else if (r < 36) {", "    } else if (r < 37) {"),
    ("dc-rep-b", P, "id_repeated(mgr, speaker, 0, exact,",
     "id_repeated(mgr, speaker, 1, exact,"),
    ("dc-rep-args", P, "id_repeated(mgr, speaker, 0, exact,\n"
     "                                                  colour);",
     "id_repeated(mgr, speaker, 0, colour,\n"
     "                                                  exact);"),
    ("dc-rep-raise", P, "speechmgr_raise_begin_pursuit_id_repeated(",
     "speechmgr_raise_begin_pursuit_id_specific("),
    ("dc-spec-b", P, "    } else if (r < 17) {\n        speaker = "
     "tpursuit_get_cop_speaker(p);\n        colour = "
     "tpursuit_get_chased_car_colour(p);\n        " + SPEC_ARGS,
     "    } else if (r < 17) {\n        speaker = "
     "tpursuit_get_cop_speaker(p);\n        colour = "
     "tpursuit_get_chased_car_colour(p);\n        "
     + SPEC_ARGS.replace("speaker, 0,", "speaker, 1,")),
    ("dc-gen-approx", P, "    } else if (r < 26) {\n        speaker = "
     "tpursuit_get_cop_speaker(p);\n        colour = "
     "tpursuit_get_chased_car_colour(p);\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);",
     "    } else if (r < 26) {\n        speaker = "
     "tpursuit_get_cop_speaker(p);\n        colour = "
     "tpursuit_get_chased_car_colour(p);\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 0, colour);"),
    ("dc-avoid", P, "speechmgr_raise_cop_pursuit_avoidance(mgr,",
     "speechmgr_raise_begin_pursuit_no_id(mgr,"),
    ("dc-noid-raise", P, "        speechmgr_raise_begin_pursuit_no_id(mgr, "
     "tpursuit_get_cop_speaker(p));", "        "
     "speechmgr_raise_begin_pursuit_erratic(mgr, "
     "tpursuit_get_cop_speaker(p));"),
    # ---- BeginPursuitCollisionSpeech
    ("cl-lm", P, "    if (p->CurrentLandmark != 0) {\n        "
     "speechmgr_raise_begin_pursuit_general(mgr,", "    if "
     "(p->CurrentLandmark == 0) {\n        "
     "speechmgr_raise_begin_pursuit_general(mgr,"),
    ("cl-lm-raise", P, "    if (p->CurrentLandmark != 0) {\n        "
     "speechmgr_raise_begin_pursuit_general(mgr,", "    if "
     "(p->CurrentLandmark != 0) {\n        "
     "speechmgr_raise_begin_pursuit_erratic(mgr,"),
    ("cl-type", P, "TheDriverType == DRIVER_TYPE_COP)",
     "TheDriverType == DRIVER_TYPE_SUPER_COP)"),
    ("cl-type-ne", P, "TheDriverType == DRIVER_TYPE_COP)",
     "TheDriverType != DRIVER_TYPE_COP)"),
    ("cl-hitrun-loc", P, "cop_hit_run(mgr, speaker,\n"
     "                                                  p->CurrentLandmark);",
     "cop_hit_run(mgr, speaker,\n"
     "                                                  "
     "p->CurrentLandmark + 1);"),
    ("cl-l2", P, "        tpursuit_switch_state(p, EPS_LEVEL2);\n        "
     "return;", "        tpursuit_switch_state(p, EPS_LEVEL3);\n        "
     "return;"),
    ("cl-l2-off", P, "        tpursuit_switch_state(p, EPS_LEVEL2);\n        "
     "return;", "        return;"),
    ("cl-ret", P, "        tpursuit_switch_state(p, EPS_LEVEL2);\n        "
     "return;\n", "        tpursuit_switch_state(p, EPS_LEVEL2);\n"),
    ("cl-traffic", P, "speechmgr_raise_begin_pursuit_hit_run_traffic(mgr, "
     "speaker,", "speechmgr_raise_begin_pursuit_cop_hit_run(mgr, speaker,"),
    ("cl-traffic-loc", P, "hit_run_traffic(mgr, speaker,\n"
     "                                                  p->CurrentLandmark);",
     "hit_run_traffic(mgr, speaker,\n"
     "                                                  "
     "p->CurrentLandmark - 1);"),
    ("cl-l0", P, "    if (p->PursuitState == EPS_LEVEL0)\n",
     "    if (p->PursuitState <= EPS_LEVEL0)\n"),
    ("cl-l1", P, "    if (p->PursuitState == EPS_LEVEL0)\n        "
     "tpursuit_switch_state(p, EPS_LEVEL1);", "    if (p->PursuitState == "
     "EPS_LEVEL0)\n        tpursuit_switch_state(p, EPS_LEVEL2);"),
    # ---- StartPursuitSpeech
    ("st-flush", P, "    if (TheRaceParameters.BeACop != 0)\n        "
     "speechmgr_flush_queue(mgr);", "    if (TheRaceParameters.BeACop == 0)\n"
     "        speechmgr_flush_queue(mgr);"),
    ("st-flush-off", P, "    if (TheRaceParameters.BeACop != 0)\n        "
     "speechmgr_flush_queue(mgr);\n", ""),
    ("st-inv", P, "    if (!tpursuit_is_player_involved(p)) {",
     "    if (tpursuit_is_player_involved(p)) {"),
    ("st-demo", P, "        if (in_demo())\n            return;\n", ""),
    ("st-ai-noid", P, "        if (exact == PURSUIT_NO_DESCRIPTION) {\n"
     "            speaker = tpursuit_get_cop_speaker(p);",
     "        if (exact != PURSUIT_NO_DESCRIPTION) {\n"
     "            speaker = tpursuit_get_cop_speaker(p);"),
    ("st-ai-gen-spk", P, "            speaker = tpursuit_get_cop_speaker(p);\n"
     "            colour = tpursuit_get_chased_car_colour(p);\n"
     "            speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, "
     "colour);\n        } else {", "            speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);\n"
     "            colour = tpursuit_get_chased_car_colour(p);\n"
     "            speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, "
     "colour);\n        } else {"),
    ("st-ai-gen-approx", P, "            speechmgr_raise_begin_pursuit_"
     "id_general(mgr, speaker, 1, colour);\n        } else {",
     "            speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 0, "
     "colour);\n        } else {"),
    ("st-ai-spec-spk", P, "            speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);\n"
     "            colour = tpursuit_get_chased_car_colour(p);",
     "            speaker = tpursuit_get_cop_speaker(p);\n"
     "            colour = tpursuit_get_chased_car_colour(p);"),
    ("st-ai-order", P, "            speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);\n"
     "            colour = tpursuit_get_chased_car_colour(p);",
     "            colour = tpursuit_get_chased_car_colour(p);\n"
     "            speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);"),
    ("st-ai-b", P, "id_specific(mgr, speaker, 0, exact,\n"
     "                                                      colour);\n"
     "        }\n", "id_specific(mgr, speaker, 1, exact,\n"
     "                                                      colour);\n"
     "        }\n"),
    ("st-ai-next", P, "        copmanager_next_cop_speaker(pCopManager);\n"
     "        return;\n    }\n", "        return;\n    }\n"),
    ("st-bac", P, "    if (TheRaceParameters.BeACop != 0) {\n        speaker "
     "= tpursuit_get_cop_speaker(p);", "    if (TheRaceParameters.BeACop == "
     "0) {\n        speaker = tpursuit_get_cop_speaker(p);"),
    ("st-bac-noid", P, "        if (exact == PURSUIT_NO_DESCRIPTION)\n"
     "            speechmgr_raise_begin_pursuit_id_general",
     "        if (exact != PURSUIT_NO_DESCRIPTION)\n"
     "            speechmgr_raise_begin_pursuit_id_general"),
    ("st-bac-b", P, "        else\n            "
     "speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,",
     "        else\n            "
     "speechmgr_raise_begin_pursuit_id_specific(mgr, speaker, 1, exact,"),
    ("st-bac-ret", P, "        return;\n    }\n    hit = car_caused",
     "    }\n    hit = car_caused"),
    ("st-coll-car", P, "car_caused_recent_collision(p->pChasedCar);",
     "car_caused_recent_collision(NULL);"),
    ("st-coll-never", P, "    if (hit != NULL) {", "    if (hit != NULL && 0) {"),
    ("st-coll-sub", P, "        p->PursuitSubState = 1;",
     "        p->PursuitSubState = 2;"),
    ("st-coll-sub-off", P, "        p->PursuitSubState = 1;\n", ""),
    ("st-coll-hit", P, "        p->bAlreadyBeenHit = 1;\n", ""),
    ("st-coll-ret", P, "        p->bAlreadyBeenHit = 1;\n        return;\n",
     "        p->bAlreadyBeenHit = 1;\n"),
    ("st-tk-ge", P, "p->pChasedCar) > 0) {", "p->pChasedCar) >= 0) {"),
    ("st-tk-1", P, "p->pChasedCar) > 0) {", "p->pChasedCar) > 1) {"),
    ("st-tk-l1", P, "        tpursuit_switch_state(p, EPS_LEVEL1);\n"
     "        if (random_below(10)", "        tpursuit_switch_state(p, "
     "EPS_LEVEL2);\n        if (random_below(10)"),
    ("st-tk-l1-off", P, "        tpursuit_switch_state(p, EPS_LEVEL1);\n"
     "        if (random_below(10)", "        if (random_below(10)"),
    ("st-tk-7", P, "random_below(10) < 8u &&", "random_below(10) < 7u &&"),
    ("st-tk-9", P, "random_below(10) < 8u &&", "random_below(10) < 9u &&"),
    ("st-tk-range", P, "random_below(10) < 8u &&", "random_below(9) < 8u &&"),
    ("st-tk-noid", P, "&& exact != PURSUIT_NO_DESCRIPTION) {",
     "&& exact == PURSUIT_NO_DESCRIPTION) {"),
    ("st-tk-noid-off", P, "8u && exact != PURSUIT_NO_DESCRIPTION) {",
     "8u) {"),
    ("st-tk-order", P, "        if (random_below(10) < 8u && exact != "
     "PURSUIT_NO_DESCRIPTION) {", "        if (exact != "
     "PURSUIT_NO_DESCRIPTION && random_below(10) < 8u) {"),
    ("st-again-args", P, "            speechmgr_raise_begin_pursuit_again(mgr, "
     "speaker, exact, colour);\n            return;\n        }\n    }",
     "            speechmgr_raise_begin_pursuit_again(mgr, speaker, colour, "
     "exact);\n            return;\n        }\n    }"),
    ("st-again-ret", P, "            speechmgr_raise_begin_pursuit_again(mgr, "
     "speaker, exact, colour);\n            return;\n        }\n    }",
     "            speechmgr_raise_begin_pursuit_again(mgr, speaker, exact, "
     "colour);\n        }\n    }"),
    ("st-sp-le", P, "    if (100.0f < tpursuit_get_speed_mph_or_kph(p)",
     "    if (100.0f <= tpursuit_get_speed_mph_or_kph(p)"),
    ("st-sp-val", P, "    if (100.0f < tpursuit_get_speed_mph_or_kph(p)",
     "    if (99.0f < tpursuit_get_speed_mph_or_kph(p)"),
    ("st-sp-6", P, "&& random_below(10) < 7u) {", "&& random_below(10) < 6u) {"),
    ("st-sp-8", P, "&& random_below(10) < 7u) {", "&& random_below(10) < 8u) {"),
    ("st-sp-order", P, "    if (100.0f < tpursuit_get_speed_mph_or_kph(p)\n"
     "        && random_below(10) < 7u) {", "    if (random_below(10) < 7u\n"
     "        && 100.0f < tpursuit_get_speed_mph_or_kph(p)) {"),
    ("st-sp-twice", P, "speechmgr_raise_begin_pursuit_speed(mgr, speaker,\n"
     "                                            "
     "tpursuit_get_speed_mph_or_kph(p));", "speechmgr_raise_begin_pursuit_"
     "speed(mgr, speaker, 123.5f);"),
    ("st-sp-ret", P, "        return;\n    }\n    if (random_below(2) == 0)",
     "    }\n    if (random_below(2) == 0)"),
    ("st-2", P, "    if (random_below(2) == 0)\n", "    if (random_below(2) "
     "!= 0)\n"),
    ("st-2r", P, "    if (random_below(2) == 0)\n", "    if (random_below(3) "
     "== 0)\n"),
    ("st-err", P, "        speechmgr_raise_begin_pursuit_erratic(mgr,\n"
     "                                              "
     "tpursuit_get_cop_speaker(p));\n    else", "        "
     "speechmgr_raise_begin_pursuit_no_id(mgr,\n"
     "                                              "
     "tpursuit_get_cop_speaker(p));\n    else"),
    # ---- JoinPursuitSpeech
    ("jn-player", P, "    if (p->pChasedCar->pPlayer == NULL)\n        "
     "return;\n    if (p->PrimaryCopSpeaker", "    if (p->pChasedCar->"
     "pPlayer != NULL)\n        return;\n    if (p->PrimaryCopSpeaker"),
    ("jn-prim", P, "    if (p->PrimaryCopSpeaker == COP_SPEAKER_NONE) {",
     "    if (p->PrimaryCopSpeaker != COP_SPEAKER_NONE) {"),
    ("jn-prim-set", P, "        p->PrimaryCopSpeaker = speaker;\n", ""),
    ("jn-res", P, "        speaker = copmanager_reserve_cop_speaker("
     "pCopManager);\n        p->PrimaryCopSpeaker", "        speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);\n        "
     "p->PrimaryCopSpeaker"),
    ("jn-lm", P, "        if (p->CurrentLandmark != 0) {\n            "
     "speechmgr_raise_suspect_found", "        if (p->CurrentLandmark == 0) {"
     "\n            speechmgr_raise_suspect_found"),
    ("jn-sf-sup", P, "speechmgr_raise_suspect_found(mgr, speaker, "
     "supervisor_on(),", "speechmgr_raise_suspect_found(mgr, speaker, 0,"),
    ("jn-sf-loc", P, "                                          "
     "p->CurrentLandmark);\n            return;", "0);\n            return;"),
    ("jn-sf-spk", P, "speechmgr_raise_suspect_found(mgr, speaker,",
     "speechmgr_raise_suspect_found(mgr, 0,"),
    ("jn-sf-ret", P, "p->CurrentLandmark);\n            return;\n        }\n"
     "        exact", "p->CurrentLandmark);\n        }\n        exact"),
    ("jn-noid", P, "        if (exact != PURSUIT_NO_DESCRIPTION) {\n"
     "            speaker = tpursuit_get_cop_speaker(p);",
     "        if (exact == PURSUIT_NO_DESCRIPTION) {\n"
     "            speaker = tpursuit_get_cop_speaker(p);"),
    ("jn-again-spk", P, "            speaker = tpursuit_get_cop_speaker(p);\n"
     "            colour = tpursuit_get_chased_car_colour(p);\n"
     "            speechmgr_raise_begin_pursuit_again(mgr, speaker, exact, "
     "colour);\n        } else {", "            colour = "
     "tpursuit_get_chased_car_colour(p);\n"
     "            speechmgr_raise_begin_pursuit_again(mgr, speaker, exact, "
     "colour);\n        } else {"),
    ("jn-gen", P, "            speechmgr_raise_begin_pursuit_general(mgr,\n"
     "                                                  "
     "tpursuit_get_cop_speaker(p));", "            "
     "speechmgr_raise_begin_pursuit_erratic(mgr,\n"
     "                                                  "
     "tpursuit_get_cop_speaker(p));"),
    ("jn-ret", P, "        return;\n    }\n    if (p->bAlreadyJoined != 0)",
     "    }\n    if (p->bAlreadyJoined != 0)"),
    ("jn-joined", P, "    if (p->bAlreadyJoined != 0)\n",
     "    if (p->bAlreadyJoined > 0)\n"),
    ("jn-joined-off", P, "    if (p->bAlreadyJoined != 0)\n        return;\n",
     ""),
    ("jn-state-lt", P, "    if (p->PursuitState <= EPS_LEVEL0)",
     "    if (p->PursuitState < EPS_LEVEL0)"),
    ("jn-state-1", P, "    if (p->PursuitState <= EPS_LEVEL0)",
     "    if (p->PursuitState <= EPS_LEVEL1)"),
    ("jn-state-eq", P, "    if (p->PursuitState <= EPS_LEVEL0)",
     "    if (p->PursuitState == EPS_LEVEL0)"),
    ("jn-set", P, "    p->bAlreadyJoined = 1;\n", ""),
    ("jn-set2", P, "    p->bAlreadyJoined = 1;\n", "    p->bAlreadyJoined = 2;\n"),
    ("jn-sec", P, "    if (p->SecondaryCopSpeaker == COP_SPEAKER_NONE\n",
     "    if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE\n"),
    ("jn-players", P, "        && TheRaceParameters.NumPlayerCars == 1) {",
     "        && TheRaceParameters.NumPlayerCars < 2) {"),
    ("jn-players-off", P, "\n        && TheRaceParameters.NumPlayerCars == 1) {",
     ") {"),
    ("jn-sec-set", P, "        p->SecondaryCopSpeaker = speaker;\n", ""),
    ("jn-sec-res", P, "        speaker = copmanager_reserve_cop_speaker("
     "pCopManager);\n        p->SecondaryCopSpeaker", "        speaker = "
     "copmanager_get_current_cop_speaker(pCopManager);\n        "
     "p->SecondaryCopSpeaker"),
    ("jn-next", P, "        copmanager_next_cop_speaker(pCopManager);\n    }\n"
     "    target", "    }\n    target"),
    ("jn-confirm", P, "speechmgr_raise_backup_confirm(mgr, speaker, target);",
     "speechmgr_raise_backup_confirm(mgr, target, speaker);"),
    # ---- RoadblockFailedSpeech
    ("rf-flag", P, "    if (p->BehaviourFlags & 0x10u) {\n        if "
     "(p->ChopperState", "    if (p->BehaviourFlags & 0x20u) {\n        if "
     "(p->ChopperState"),
    ("rf-chop", P, "        if (p->ChopperState == ECS_CHOPPER_ATTACKING\n",
     "        if (p->ChopperState == ECS_CHOPPER_INFLIGHT\n"),
    ("rf-chop-off", P, "        if (p->ChopperState == ECS_CHOPPER_ATTACKING\n"
     "            && random_below(3) == 0) {", "        if (random_below(3) "
     "== 0) {"),
    ("rf-3r", P, "            && random_below(3) == 0) {",
     "            && random_below(2) == 0) {"),
    ("rf-3ne", P, "            && random_below(3) == 0) {",
     "            && random_below(3) != 0) {"),
    ("rf-order", P, "        if (p->ChopperState == ECS_CHOPPER_ATTACKING\n"
     "            && random_below(3) == 0) {", "        if (random_below(3) "
     "== 0\n            && p->ChopperState == ECS_CHOPPER_ATTACKING) {"),
    ("rf-rotor-args", P, "speechmgr_raise_rotor_spike_failed(mgr, "
     "(uint32_t)sup,\n                                               "
     "speaker != 0);", "speechmgr_raise_rotor_spike_failed(mgr, speaker,\n"
     "                                               sup);"),
    ("rf-rotor-bool", P, "                                               "
     "speaker != 0);", "                                               "
     "speaker);"),
    ("rf-rotor-sup", P, "speechmgr_raise_rotor_spike_failed(mgr, "
     "(uint32_t)sup,", "speechmgr_raise_rotor_spike_failed(mgr, 0,"),
    ("rf-spike-target", P, "speechmgr_raise_spike_strip_failure(mgr, "
     "rb->CopSpeaker, sup,", "speechmgr_raise_spike_strip_failure(mgr, 1, "
     "sup,"),
    ("rf-spike-sup", P, "speechmgr_raise_spike_strip_failure(mgr, "
     "rb->CopSpeaker, sup,", "speechmgr_raise_spike_strip_failure(mgr, "
     "rb->CopSpeaker, 0,"),
    ("rf-spike-raise", P, "speechmgr_raise_spike_strip_failure(mgr,",
     "speechmgr_raise_road_block_failure_through(mgr,"),
    ("rf-through-gt", P, "    } else if (through != 0) {",
     "    } else if (through > 0) {"),
    ("rf-through-1", P, "    } else if (through != 0) {",
     "    } else if (through == 1) {"),
    ("rf-through-raise", P, "speechmgr_raise_road_block_failure_through(mgr, "
     "rb->CopSpeaker, sup,\n", "speechmgr_raise_road_block_failure_avoid(mgr, "
     "rb->CopSpeaker, sup,\n"),
    ("rf-through-sup", P, "speechmgr_raise_road_block_failure_through(mgr, "
     "rb->CopSpeaker, sup,\n", "speechmgr_raise_road_block_failure_through("
     "mgr, rb->CopSpeaker, 1,\n"),
    ("rf-through-spk", P, "speechmgr_raise_road_block_failure_through(mgr, "
     "rb->CopSpeaker, sup,\n                                                   "
     "speaker);", "speechmgr_raise_road_block_failure_through(mgr, "
     "rb->CopSpeaker, sup,\n                                                   "
     "rb->CopSpeaker);"),
    ("rf-avoid-args", P, "speechmgr_raise_road_block_failure_avoid(mgr, "
     "rb->CopSpeaker, sup,\n                                                 "
     "speaker);", "speechmgr_raise_road_block_failure_avoid(mgr, speaker, "
     "sup,\n                                                 "
     "rb->CopSpeaker);"),
    ("rf-avoid-sup", P, "speechmgr_raise_road_block_failure_avoid(mgr, "
     "rb->CopSpeaker, sup,", "speechmgr_raise_road_block_failure_avoid(mgr, "
     "rb->CopSpeaker, !sup,"),
    ("rf-beacop", P, "    if (TheRaceParameters.BeACop == 0)\n        "
     "speechmgr_raise_request_another_roadblock", "    if "
     "(TheRaceParameters.BeACop != 0)\n        "
     "speechmgr_raise_request_another_roadblock"),
    ("rf-another-spk", P, "                                                  "
     "p->pRoadBlock->CopSpeaker,\n", "                                       "
     "           speaker,\n"),
    ("rf-another-sup", P, "                                                  "
     "supervisor_on());\n}", "                                             "
     "     0);\n}"),
    # ---- RoadBlockSetSpeech
    ("rs-pos", P, "copmgr_find_landmark(&rb->v2Position);",
     "copmgr_find_landmark(&rb->v2EscapeLane);"),
    ("rs-lm-off", P, "        location = lm->LandmarkType;\n", ""),
    ("rs-loc0", P, "    int32_t location = 0;", "    int32_t location = 1;"),
    ("rs-20", P, "    r = random_below(20);", "    r = random_below(21);"),
    ("rs-flag", P, "    if (p->BehaviourFlags & 0x10u) {\n        if (r < 3u)",
     "    if (p->BehaviourFlags & 0x20u) {\n        if (r < 3u)"),
    ("rs-ra2", P, "        if (r < 3u)\n            speechmgr_raise_spike_strip"
     "_set(", "        if (r < 2u)\n            speechmgr_raise_spike_strip"
     "_set("),
    ("rs-ra4", P, "        if (r < 3u)\n            speechmgr_raise_spike_strip"
     "_set(", "        if (r < 4u)\n            speechmgr_raise_spike_strip"
     "_set("),
    ("rs-side1", P, "        else if (rb->nSpikeSide == 2)",
     "        else if (rb->nSpikeSide == 1)"),
    ("rs-side-ge", P, "        else if (rb->nSpikeSide == 2)",
     "        else if (rb->nSpikeSide >= 2)"),
    ("rs-spike-loc", P, "speechmgr_raise_spike_strip_set(mgr, rb->CopSpeaker, "
     "location,", "speechmgr_raise_spike_strip_set(mgr, rb->CopSpeaker, 0,"),
    ("rs-spike-sup", P, "speechmgr_raise_spike_strip_set(mgr, rb->CopSpeaker, "
     "location,\n                                            "
     "supervisor_on());", "speechmgr_raise_spike_strip_set(mgr, "
     "rb->CopSpeaker, location,\n                                            "
     "0);"),
    ("rs-right-left", P, "speechmgr_raise_spike_strip_set_right(mgr,",
     "speechmgr_raise_spike_strip_set_left(mgr,"),
    ("rs-right-sup", P, NL + " " * 50 + "location, supervisor_on());",
     NL + " " * 50 + "location, 1);"),
    ("rs-left-sup", P, NL + " " * 49 + "location, supervisor_on());",
     NL + " " * 49 + "location, 1);"),
    ("rs-left-loc", P, NL + " " * 49 + "location, supervisor_on());",
     NL + " " * 49 + "0, supervisor_on());"),
    ("rs-rb4", P, "    } else if (r < 3u) {", "    } else if (r < 4u) {"),
    ("rs-rb2", P, "    } else if (r < 3u) {", "    } else if (r < 2u) {"),
    ("rs-setting-sup", P, "speechmgr_raise_road_block_setting(mgr, "
     "rb->CopSpeaker,\n                                           "
     "supervisor_on());", "speechmgr_raise_road_block_setting(mgr, "
     "rb->CopSpeaker,\n                                           0);"),
    ("rs-setting-raise", P, "speechmgr_raise_road_block_setting(mgr, "
     "rb->CopSpeaker,\n                                           "
     "supervisor_on());", "speechmgr_raise_road_block_set(mgr, "
     "rb->CopSpeaker,\n                                           "
     "supervisor_on(), location);"),
    ("rs-set-args", P, "speechmgr_raise_road_block_set(mgr, rb->CopSpeaker, "
     "supervisor_on(),\n                                       location);",
     "speechmgr_raise_road_block_set(mgr, rb->CopSpeaker, location,\n"
     "                                       supervisor_on());"),
    # ---- CopBackOffSpeech
    ("bo-0", P, "    if (p->nNumCops == 0\n", "    if (p->nNumCops <= 0\n"),
    ("bo-sup", P, "        || (supervisor_on() && random_below(4) != 0)) {",
     "        || (random_below(4) != 0)) {"),
    ("bo-4eq", P, "random_below(4) != 0)) {", "random_below(4) == 0)) {"),
    ("bo-3", P, "random_below(4) != 0)) {", "random_below(3) != 0)) {"),
    ("bo-order", P, "        || (supervisor_on() && random_below(4) != 0)) {",
     "        || (random_below(4) != 0 && supervisor_on())) {"),
    ("bo-sup2", P, "speechmgr_raise_cop_back_off(mgr, speaker, "
     "supervisor_on());", "speechmgr_raise_cop_back_off(mgr, speaker, 0);"),
    ("bo-ret", P, "        speechmgr_raise_super_back_off(mgr);\n        "
     "return;\n", "        speechmgr_raise_super_back_off(mgr);\n"),
    ("bo-spk", P, "speechmgr_raise_cop_back_off(mgr, speaker,",
     "speechmgr_raise_cop_back_off(mgr, 0,"),
    # ---- AITicketSpeech
    ("tk-demo", P, "    if (in_demo())\n        return;\n    if "
     "(TheRaceParameters.BeACop != 0) {\n        speaker = pCopManager->"
     "BeACopId;", "    if (TheRaceParameters.BeACop != 0) {\n        "
     "speaker = pCopManager->BeACopId;"),
    ("tk-bac", P, "    if (TheRaceParameters.BeACop != 0) {\n        speaker "
     "= pCopManager->BeACopId;", "    if (TheRaceParameters.BeACop == 0) {\n"
     "        speaker = pCopManager->BeACopId;"),
    ("tk-id", P, "        speaker = pCopManager->BeACopId;",
     "        speaker = 0;"),
    ("tk-next", P, "        copmanager_next_cop_speaker(pCopManager);\n    }\n"
     "    exact", "    }\n    exact"),
    ("tk-3ne", P, "    if (random_below(3) == 0 || exact",
     "    if (random_below(3) != 0 || exact"),
    ("tk-2", P, "    if (random_below(3) == 0 || exact",
     "    if (random_below(2) == 0 || exact"),
    ("tk-noid", P, "|| exact == PURSUIT_NO_DESCRIPTION)\n        "
     "speechmgr_raise_radio_arrest", "|| exact == 0)\n        "
     "speechmgr_raise_radio_arrest"),
    ("tk-order", P, "    if (random_below(3) == 0 || exact == "
     "PURSUIT_NO_DESCRIPTION)", "    if (exact == PURSUIT_NO_DESCRIPTION || "
     "random_below(3) == 0)"),
    ("tk-stopped", P, "speechmgr_raise_car_stopped(mgr, speaker, exact);",
     "speechmgr_raise_car_stopped(mgr, speaker, 0);"),
    ("tk-arrest", P, "        speechmgr_raise_radio_arrest(mgr, speaker);",
     "        speechmgr_raise_radio_arrest(mgr, 0);"),
    # ---- SuperInitiates
    ("su-order", P, "    uint32_t speaker = tpursuit_get_cop_speaker(p);\n"
     "    float speed = tpursuit_get_speed_mph_or_kph(p);", "    float speed "
     "= tpursuit_get_speed_mph_or_kph(p);\n    uint32_t speaker = "
     "tpursuit_get_cop_speaker(p);"),
    ("su-loc", P, "    int32_t location = p->CurrentLandmark;",
     "    int32_t location = 0;"),
    ("su-exact", P, "speechmgr_raise_super_initiate(mgr, speaker, speed, "
     "location, exact,", "speechmgr_raise_super_initiate(mgr, speaker, "
     "speed, location, 0,"),
    ("su-colour", P, "location, exact,\n                                   colour);",
     "location, exact,\n                                   exact);"),
    # ---- the change of target
    ("ct-chased", P, "    p->pChasedCar = car;\n    if (p->pChopper",
     "    if (p->pChopper"),
    ("ct-chopper", P, "        gChopperFollowThisCarFn(p->pChopper, NULL);",
     "        gChopperFollowThisCarFn(p->pChopper, car);"),
    ("ct-nochop", P, "        gChopperFollowThisCarFn(p->pChopper, NULL);",
     ""),
    ("ct-speaker", P, "    speaker = TheRaceParameters.BeACop != 0 ? "
     "pCopManager->BeACopId", "    speaker = TheRaceParameters.BeACop == 0 ? "
     "pCopManager->BeACopId"),
    ("ct-order", P, "    exact = tpursuit_get_exact_description(p);\n"
     "    colour = tpursuit_get_chased_car_colour(p);\n    mgr",
     "    colour = tpursuit_get_chased_car_colour(p);\n"
     "    exact = tpursuit_get_exact_description(p);\n    mgr"),
    ("ct-general", P, "        speechmgr_raise_begin_pursuit_id_general(mgr, "
     "speaker, 1, colour);\n    else\n", "        speechmgr_raise_begin_"
     "pursuit_id_general(mgr, speaker, 0, colour);\n    else\n"),
    ("ct-specific", P, "speaker, 1, colour);\n    else\n        speechmgr_"
     "raise_begin_pursuit_id_specific(mgr, speaker, 0, exact,",
     "speaker, 1, colour);\n    else\n        speechmgr_"
     "raise_begin_pursuit_id_specific(mgr, speaker, 1, exact,"),
    ("ct-test", P, "    if (exact == PURSUIT_NO_DESCRIPTION)\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);\n"
     "    else", "    if (exact == 0)\n        "
     "speechmgr_raise_begin_pursuit_id_general(mgr, speaker, 1, colour);\n"
     "    else"),
    ("su-speed", P, "speechmgr_raise_super_initiate(mgr, speaker, speed,",
     "speechmgr_raise_super_initiate(mgr, speaker, 0.0f,"),
]

EQUIVALENT = {
    "ct-order": "GetExactDescription reads the language and the car type "
                "and does nothing the paint's GetSkinInfo could be ordered "
                "against",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "pursuitspeech_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
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
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
