#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pursuit.c, tPursuit's making and
unmaking, against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own copmgr.obj: the new 0x002244e0 (a pursuit
out of the slot pool and onto the list) and so tPursuit's constructor
(0x00228fc8) with GetTopSpeed, tPursuitHistory's and the roadblock state
machine's constructors and the barricades' (0x0024ef88) under it, and
SwitchPursuitState (0x00229fe8) with its state time (0x00229f70) and
PossibleCallSupervisor; DoStateTransition, GetSpeedMPHOrKPH,
ReleaseAllCops with the chopper's release (0x0022a310), DisbandRoadBlock
with DeleteRoadBlockSpikeStrips and the barrels' fade (0x0024f1e0),
RemoveCopFromPursuit, IsCopInPursuit, RemovePrimarySpeaker,
RoadBlockEncounteredRecently, SelectPrimaryCop, the two speakers,
IsPlayerInvolved, the one-liners (0x0022d210 to 0x0022d338),
RequestPursuit (0x00225078), and DeletePursuit (0x00224560) into the
destructor (0x00229198) and the barricades' (0x0024efd8). Then
tPursuit::Update (0x00229288) and what it calls: NotInChasingState,
Level0SubStates, ShouldPursuitBeCalledOff, UpdateDriveTargets with
tPursuitHistory::Update, the roadblock state machine's Update, the
barrels' count down (0x0024f268), DoEarlyChaseCollisionCheck,
IsChasedCarStoppable, and the manager's IsCopNearby, FindLandmark and
DidRecentlyCollideWithCop. Then the roadblocks: UpdateRoadBlocks
(0x00229b58, run straight rather than through the Update's stub),
MonitorRoadBlock, RoadBlockDefeated and the roadblock state machine's
RequestRoadBlock, with GetRealDistanceAroundTrack (Car+2036) and
GetForwardTrackDistance as shipped. The cop
manager's speakers, GetNumTickets, the free id, bRandom, bStringHash,
IsReplayDemoMode and the cops' IsAIControlled run as shipped. The harness
(tools/src/pursuit_test.c) runs pursuit.c, barricade.c, copmgr.c,
copmanager.c, vtable.c and bmath.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides: the
slot pool's alloc and free, bMalloc (a block of 0xcd) and
__builtin_delete, DriveTarget's constructor and destructor,
GetAccelerationTable and Table::GetValue (huge below a cut speed, then a
scripted value), Player::StartScore and LoadNextNis, the cop speech
manager's raise calls and tPursuit's own three speeches, tAICop's
ReturnToPatrol, tCop's SetPursuit and SetDesiredLogicState (which store
as well), Chopper::FollowThisCar, tSpikeStrip::BlinkBlinkPoof,
FindCollisionBody (a body for most ids), FindSmokeableInfo and the
barrel's delete (0x0021ef88). For the Update also: Car::IsBlinking,
IsPoofed, CausedRecentCollision and GetRoutePoint, DidTheseCarsCollide,
IsFreeRun, Player::IsNisPlaying, IsPointInPoly (a slab from the first
vertex's x to the second's), DriveTarget's AddPoint2, ShiftLeft and
SetPoint2 (which store as well), tPursuit's Declare, Backup and
BeginCollision speeches, the speech manager's raisePursuitCopHit and
raiseSuspectCrashTraffic, CreatePullover, CreateRoadBlock (which sets the
pursuit's roadblock from a scripted one), UpdateRoadBlocks and
UpdateChopper. For the roadblocks also: the five roadblock speeches and
tPursuit's RoadblockFailedSpeech, RealDriver::ForceEBrakeStop(float),
Player::RequestZone (a scripted answer per player),
PlayBustRoadBlock, ReplayManager::RegisterInterestingEvent and
World::Random (a scripted answer). DemoDiscManager.bActive is 0. Each
car's controller is a block whose e-brake timer (592) `rbdump` prints.

**Compared** are the stubs' logs and, on `dump`, every field of a pursuit
at retail's offsets but the drive targets, its barricades', the manager's lists, speakers, timers and seed, the
cops' pursuits and logic states, and the bodies the fade marked; on
`tdump` the drive targets' points, and on `mvdump` the cop movers' base
speeds.

    python tools/pursuit_check.py
    python tools/pursuit_check.py --mutate [--only a,b]
    python tools/pursuit_check.py --dump out/pursuit
"""
import argparse
import os
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

HARNESS = "tools/src/pursuit_test.c"
PURSUIT = "3DS Files/source/pursuit.c"
BARRICADE = "3DS Files/source/barricade.c"
COPMGR = "3DS Files/source/copmgr.c"
SOURCES = [HARNESS, PURSUIT, BARRICADE, COPMGR,
           "3DS Files/source/copmanager.c", "3DS Files/source/vtable.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
TRACKLEN = 0x0031bc38                   # TheTrackPathManager.TrackLength
G_POOL = GP - 15644                     # PursuitSlotPool
G_COPMGR = GP - 15620
G_SPEECH = GP - 15624
G_SPAWN = GP - 15600                    # fRoadBlockSpawnTime
G_RC = GP - 22216                       # pRaceCoordinator
G_WORLD = GP - 22120                    # pCurrentWorld
G_SEED = GP - 14472                     # bDefaultSeed

F_NEW = 0x002244e0
F_REQ = 0x00225078
F_SUPER = 0x002253e8
F_DEL = 0x00224560
F_DSS = 0x00227be8
F_DTOR = 0x00229198
F_RBR = 0x00229dd8
F_SEL = 0x00229ed0
F_STATETIME = 0x00229f70
F_SWITCH = 0x00229fe8
F_TRANS = 0x0022a190
F_SPEED = 0x0022a220
F_RELEASE = 0x0022a260
F_SPK1 = 0x0022ab30
F_SPK2 = 0x0022ab70
F_PI = 0x0022bbd8
F_DISBAND = 0x0022c5a0
F_REMOVE = 0x0022c740
F_ISIN = 0x0022c920
F_RPS = 0x0022c990
F_TOP = 0x00231338
F_BFADE = 0x0024f1e0
F_ONE = {"addcop": 0x0022d210, "numcops": 0x0022d230, "id": 0x0022d238,
         "rbstate": 0x0022d240, "dir": 0x0022d248, "chst": 0x0022d250,
         "over": 0x0022d258, "called": 0x0022d268, "needed": 0x0022d270,
         "other": 0x0022d2a8, "primcar": 0x0022d2c0, "prim": 0x0022d2e0,
         "allowed": 0x0022d2f0, "disallowall": 0x0022d300,
         "disallow": 0x0022d308, "allow": 0x0022d320,
         "landmark": 0x0022d330, "hud": 0x0022d338}

S_OMALLOC = 0x00257c80
S_SLOTFREE = 0x00257ca0
S_MALLOC = 0x002577c0
S_DELETE = 0x00114e98
S_DT_CTOR = 0x0021b918
S_DT_DTOR = 0x0021b988
S_ACCTAB = 0x00188dd8
S_GETVALUE = 0x0018f838
S_SCORE = 0x0017e3b0
S_NIS = 0x001761e8
S_PATROL = 0x00230cb0
S_SETPURSUIT = 0x0022d530
S_DESIRED = 0x0022d538
S_FINDBODY = 0x001d6ee8
S_FINDSMOKE = 0x0021f8f8
S_BARREL_DEL = 0x0021ef88
S_FOLLOW = 0x001e7f80
S_POOF = 0x00241880
S_SPEECH = {0x0022afb8: "start", 0x0022b288: "join", 0x0022b788: "backoff",
            0x0022ad30: "declare", 0x0022acc0: "backup"}
S_RAISE2 = {0x0020aa90: "tow", 0x0020a9b0: "crash", 0x0020aa00: "flat"}
S_SUPERREQ = 0x0020b4b0

# The Update's.
F_UPDATE = 0x00229288
F_NIC = 0x002295c8
F_LEVEL0 = 0x002295d8
F_CALLOFF = 0x0022c2d0
F_RBSMU = 0x0022cdd8
F_BCOUNT = 0x0024f268
F_UDT = 0x0022a360
F_HIST = 0x0022cf90
F_EARLY = 0x0022aba0
F_STOP = 0x0022bea0
F_NEAR = 0x00225d30
F_COLL = 0x002286b8
S_BLINK = 0x00133130
S_POOFED = 0x00133260
S_CAUSED = 0x00231118
S_COLLIDE = 0x00231268
S_FREERUN = 0x001ee390
S_ROUTEPT = 0x001332d8
S_NISPLAYING = 0x00176520
S_INPOLY = 0x001cb1f0
S_ADDPT = 0x0021c1c8
S_SHIFTL = 0x0021d928
S_SETPT = 0x0021da08
S_PULLOVER = 0x00226f30
S_CREATERB = 0x00229e30
S_UPDATERBS = 0x00229b58
S_UPDATECHOPPER = 0x00229678
S_COLLSPEECH = 0x0022aef8
S_COPHIT = 0x0020a3e0
S_TRAFFIC = 0x0020b758
G_LANDMARKS = GP - 15656
G_DT = GP - 19560                       # WorldTimeElapsed
NLANDMARKS = 4

# The roadblocks'.
F_URB = S_UPDATERBS
F_MRB = 0x0022c390
F_RBD = 0x00229970
F_RRB = 0x0022cc38
S_TIREBLOW = 0x0020b460
S_RBFAILED = 0x0022b3f8
S_RBSPEECH = {0x0020b190: "another", 0x0020b2f0: "spikereq",
              0x0020b140: "rbreq"}
S_RBNA = 0x0020b7e8
S_BUST = 0x001e5688
S_EBRAKE = 0x0013b558
S_ZONE = 0x00177c88
S_REPLAY = 0x0013e270
S_RANDOM = 0x0014e520
G_REPLAY = GP - 22440                   # pReplayManager
DEMO_ACTIVE = 0x002effe0                # DemoDiscManager.bActive

VT_AICOP = 0x002bd698
VT_PLAYERCOP = 0x002bd6c0

RP_FIELDS = {"RaceType": 32, "Point2Point": 40, "NumLaps": 44,
             "NumPlayerCars": 48, "bTickets": 608, "bRoadBlocks": 612,
             "bHelicopter": 620, "New624": 624, "BeACop": 628}
RP_UNITS = 749

MGR_SIZE = 10516
PURSUIT_SIZE = 1600
WORLD_SIZE = 5936
CAR_SIZE = 2304
CAR_INDEX, CAR_CTI, CAR_RIDE, CAR_DRIVER, CAR_PLAYER, CAR_RACING = (
    8, 12, 16, 20, 24, 28)
CAR_CTRL, CAR_MODE, CAR_CDRIVER, CAR_MOVER = 32, 36, 44, 48
CAR_POS, CAR_VELOCITY, CAR_UPZ = 96, 112, 184
CAR_FWD, CAR_VELMAG, CAR_BLOWN, CAR_JRF = 960, 964, 2124, 2140
CAR_DAT = 2036                          # GetRealDistanceAroundTrack's
PDRIVER_SIZE, PDRIVER_EBRAKE, RPT_SIZE = 640, 592, 112
RACING_SIZE = 48
CTI_SIZE, CTI_MASS, CTI_DRAG = 1024, 480, 752
NCARS, NCOPS, NRBS, NSTRIPS, NCHOPPERS, NBODIES = 6, 8, 4, 6, 2, 16
COP_SIZE, RB_SIZE, STRIP_SIZE, CHOPPER_SIZE, BODY_SIZE = (128, 120, 32,
                                                          1024, 1136)

MFIELDS = {"diff": 10476, "beacop": 10336, "super": 10348, "busy": 312,
           "pcidx": 12, "head": 10324, "tail": 10328, "full": 10332,
           "ncops": 8, "nrb": 0}
PFIELDS = {"state": 1484, "ncops": 1476, "chst": 1580, "primary": 1496,
           "secondary": 1500, "backup": 1516, "maxchase": 8,
           "rbtimer": 1532, "flags": 1588, "landmark": 1504,
           "rbstate": 1560, "rbsmt": 1564, "sub": 1488, "timer": 1524,
           "hit": 1512, "catch": 1520, "top": 1544, "dir": 1548,
           "dirt": 1552, "n1556": 1556, "dbtimer": 1528, "rbcount": 1584,
           "rbflags": 1568}


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


def fl(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.emu(retail=True, ieee=True)
        self.out = []
        self.names = {}
        self.pursuits = []
        self.blocks = 0
        a = lambda n: e.alloc(n, align=16)      # noqa: E731
        self.m = a(MGR_SIZE)
        e.put32(G_COPMGR, self.m)
        self.names[self.m + 44] = "M.plist"
        self.names[self.m + 80] = "M.slist"
        self.world = a(WORLD_SIZE)
        e.write(self.world, bytes(WORLD_SIZE))
        e.put32(G_WORLD, self.world)
        self.rc = a(64)
        e.write(self.rc, bytes(64))
        e.put32(G_RC, self.rc)
        self.pool = a(16)
        self.names[self.pool] = "pool"
        e.put32(G_POOL, self.pool)
        e.put32(G_SPEECH, a(16))
        self.smoke = a(64)
        self.tabtok = a(16 * 8)
        self.cut = [0] * 8
        self.low = [0] * 8
        self.cars, self.drivers, self.movers, self.routepts = [], [], [], []
        self.pdrivers = []
        for k in range(NCARS):
            c, cti, ride, racing = (a(CAR_SIZE), a(CTI_SIZE), a(16),
                                    a(RACING_SIZE))
            drv, mover, rpt = a(16), a(128), a(32)
            for p, n in ((c, CAR_SIZE), (cti, CTI_SIZE), (ride, 16),
                         (racing, RACING_SIZE), (drv, 16), (mover, 128),
                         (rpt, 32)):
                e.write(p, bytes(n))
            e.put32(c + CAR_CTI, cti)
            e.put32(c + CAR_RIDE, ride)
            e.put32(c + CAR_RACING, racing)
            e.put32(c + CAR_DRIVER, drv)
            e.put32(c + CAR_MOVER, mover)
            pd = a(PDRIVER_SIZE)
            e.put32(c + CAR_CDRIVER, pd)
            self.names[pd] = "D%d" % k
            self.pdrivers.append(pd)
            self.names[c] = "A%d" % k
            self.cars.append(c)
            self.drivers.append(drv)
            self.movers.append(mover)
            self.routepts.append(rpt)
        self.landmarks = a(4 + 60 * NLANDMARKS)
        e.write(self.landmarks, bytes(4 + 60 * NLANDMARKS))
        e.put32(G_LANDMARKS, self.landmarks)
        self.scratch = a(32)
        self.players = []
        for k in range(2):
            p = a(16)
            self.names[p] = "P%d" % k
            self.players.append(p)

        def many(n, size, fmt):
            out = []
            for k in range(n):
                p = a(size)
                e.write(p, bytes(size))
                self.names[p] = fmt % k
                out.append(p)
            return out
        self.cops = many(NCOPS, COP_SIZE, "C%d")
        self.rbs = many(NRBS, RB_SIZE, "R%d")
        self.strips = many(NSTRIPS, STRIP_SIZE, "S%d")
        self.choppers = many(NCHOPPERS, CHOPPER_SIZE, "H%d")
        self.bodies = many(NBODIES, BODY_SIZE, "Y%d")
        self.rbpts = many(NRBS, RPT_SIZE, "RQ%d")
        self.replay = a(16)
        self.names[self.replay] = "RM"
        e.put32(G_REPLAY, self.replay)
        e.put32(DEMO_ACTIVE, 0)

        for addr, fn in ((S_OMALLOC, self.s_omalloc),
                         (S_SLOTFREE, self.s_slotfree),
                         (S_MALLOC, self.s_malloc),
                         (S_DELETE, self.log1("delete")),
                         (S_DT_CTOR, self.s_dt_ctor),
                         (S_DT_DTOR, self.log1("dt destroy")),
                         (S_ACCTAB, self.s_acctab),
                         (S_GETVALUE, self.s_getvalue),
                         (S_SCORE, self.s_score), (S_NIS, self.s_nis),
                         (S_PATROL, self.log1("patrol")),
                         (S_SETPURSUIT, self.s_setpursuit),
                         (S_DESIRED, self.s_desired),
                         (S_FINDBODY, self.s_findbody),
                         (S_FINDSMOKE, lambda em: self.smoke),
                         (S_BARREL_DEL, self.s_barrel_del),
                         (S_FOLLOW, self.s_follow),
                         (S_POOF, self.log1("poof")),
                         (S_SUPERREQ, self.s_superreq),
                         (S_BLINK, self.percar("blink", "blink")),
                         (S_POOFED, self.percar("poofed", "poofed")),
                         (S_CAUSED, self.s_caused),
                         (S_COLLIDE, self.s_collide),
                         (S_FREERUN, self.s_freerun),
                         (S_ROUTEPT, self.s_routept),
                         (S_NISPLAYING, self.s_nisplaying),
                         (S_INPOLY, self.s_inpoly),
                         (S_ADDPT, self.s_addpt),
                         (S_SHIFTL, self.s_shiftl),
                         (S_SETPT, self.s_setpt),
                         (S_PULLOVER, self.s_pullover),
                         (S_CREATERB, self.s_createrb),
                         (S_UPDATERBS, self.log1("updaterbs")),
                         (S_UPDATECHOPPER, self.log1("updatechopper")),
                         (S_COLLSPEECH, self.s_collspeech),
                         (S_COPHIT, self.speech2("cophit")),
                         (S_TRAFFIC, self.speech2("traffic")),
                         (S_TIREBLOW, self.speech2("tireblow")),
                         (S_RBFAILED, self.s_rbfailed),
                         (S_RBNA, self.s_rbna), (S_BUST, self.s_bust),
                         (S_EBRAKE, self.s_ebrake), (S_ZONE, self.s_zone),
                         (S_REPLAY, self.s_replay),
                         (S_RANDOM, self.s_random)):
            e.stub(addr, fn)
        for addr, what in S_RBSPEECH.items():
            e.stub(addr, self.speech2(what))
        for addr, what in S_SPEECH.items():
            e.stub(addr, self.log1("speech " + what))
        for addr, what in S_RAISE2.items():
            e.stub(addr, self.raise2(what))
        self.reset()

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        if v == 0xcdcdcdcd:
            return "cd"
        return self.names.get(v, "?")

    # ---- stubs

    def log1(self, what):
        def fn(em):
            self.emit("  %s %s" % (what, self.sym(em.reg[4])))
        return fn

    def s_omalloc(self, em):
        e = self.e
        p = e.alloc(PURSUIT_SIZE, align=16)
        e.write(p, b"\xcd" * PURSUIT_SIZE)
        u = len(self.pursuits)
        self.names[p] = "U%d" % u
        self.names[p + 48] = "U%d.far" % u
        self.names[p + 576] = "U%d.near" % u
        self.pursuits.append(p)
        self.emit("  slotalloc %s -> U%d" % (self.sym(em.reg[4]), u))
        return p

    def s_slotfree(self, em):
        self.emit("  slotfree %s %s" % (self.sym(em.reg[4]),
                                        self.sym(em.reg[5])))

    def s_malloc(self, em):
        e = self.e
        size = s32(em.reg[4])
        p = e.alloc(size, align=16)
        e.write(p, b"\xcd" * size)
        n = "B%d" % self.blocks
        self.blocks += 1
        self.names[p] = n
        self.emit("  malloc %d %s %d %d -> %s" % (
            size, self.cstr(em.reg[5] & M32), s32(em.reg[6]),
            s32(em.reg[7]), n))
        return p

    def s_dt_ctor(self, em):
        self.emit("  dt init %s" % self.sym(em.reg[4]))
        return em.reg[4]

    def s_acctab(self, em):
        t = s32(em.reg[4])
        self.emit("  acctab %d" % t)
        return self.tabtok + 16 * (t & 7)

    def s_getvalue(self, em):
        k = ((em.reg[4] & M32) - self.tabtok) // 16
        v = em.fpr[12] & M32
        r = self.low[k] if v >= self.cut[k] else 0x7f000000
        self.emit("  accel T%d %08x -> %08x" % (k, v, r))
        em.fpr[0] = r

    def s_score(self, em):
        self.emit("  score %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_nis(self, em):
        self.emit("  nis %s %s %s %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            s32(em.reg[7])))

    def s_setpursuit(self, em):
        c, p = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  setpursuit %s %s" % (self.sym(c), self.sym(p)))
        self.e.put32(c, p)

    def s_desired(self, em):
        c, s = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  desired %s %d" % (self.sym(c), s32(s)))
        self.e.put32(c + 16, s)

    def s_findbody(self, em):
        i = s32(em.reg[4])
        b = self.bodies[i] if 0 <= i < NBODIES and i % 3 != 2 else 0
        self.emit("  findbody %d -> %s" % (i, self.sym(b)))
        return b

    def s_barrel_del(self, em):
        ok = "" if em.reg[5] & M32 == self.smoke else " ?info"
        self.emit("  barrel delete %d%s" % (s32(em.reg[4]), ok))

    def s_follow(self, em):
        self.emit("  follow %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))

    def raise2(self, what):
        def fn(em):
            self.emit("  speech %s %08x %08x" % (what, em.reg[5] & M32,
                                                 em.reg[6] & M32))
        return fn

    def s_superreq(self, em):
        self.emit("  speech super %08x" % (em.reg[5] & M32))

    # ---- the Update's stubs

    def carno(self, v):
        v &= M32
        return self.cars.index(v) if v in self.cars else -1

    def percar(self, what, attr):
        def fn(em):
            r = getattr(self, attr)[self.carno(em.reg[4])]
            self.emit("  %s %s -> %d" % (what, self.sym(em.reg[4]), r))
            return r
        return fn

    def s_caused(self, em):
        k = self.caused[self.carno(em.reg[4])]
        r = self.cars[k] if k >= 0 else 0
        self.emit("  caused %s -> %s" % (self.sym(em.reg[4]), self.sym(r)))
        return r

    def s_collide(self, em):
        ka, kb = self.carno(em.reg[4]), self.carno(em.reg[5])
        r = 1 if ka >= 0 and kb >= 0 and (ka, kb) in self.collides else 0
        self.emit("  collide %s %s -> %d" % (self.sym(em.reg[4]),
                                            self.sym(em.reg[5]), r))
        return r

    def s_freerun(self, em):
        ok = "" if em.reg[4] & M32 == RP else " ?rp"
        self.emit("  freerun%s -> %d" % (ok, self.freerun))
        return self.freerun

    def s_routept(self, em):
        self.emit("  routept %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))
        return self.routepts[self.carno(em.reg[4])]

    def s_nisplaying(self, em):
        k = self.players.index(em.reg[4] & M32)
        self.emit("  nisplaying %s -> %d" % (self.sym(em.reg[4]),
                                             self.nisplay[k]))
        return self.nisplay[k]

    def s_inpoly(self, em):
        e = self.e
        p, poly = em.reg[4] & M32, em.reg[5] & M32
        px, py, x0 = e.u32(p), e.u32(p + 4), e.u32(poly)
        r = 1 if fl(x0) <= fl(px) < fl(e.u32(poly + 8)) else 0
        self.emit("  inpoly %08x %08x %08x %d -> %d" % (
            px, py, x0, s32(em.reg[6]), r))
        return r

    def s_addpt(self, em):
        e = self.e
        t, p = em.reg[4] & M32, em.reg[5] & M32
        n = s8(e.u8(t))
        k = n if 0 <= n < 20 else 0
        self.emit("  addpt %s %08x %08x %d %d %d %d %s" % (
            self.sym(t), e.u32(p), e.u32(p + 4), s8(em.reg[6]),
            s16(em.reg[7]), s8(em.reg[8]), s32(em.reg[9]),
            self.sym(em.reg[10])))
        e.put32(t + 16 + 16 * k, e.u32(p))
        e.put32(t + 20 + 16 * k, e.u32(p + 4))
        e.write(t, bytes([(k + 1) & 0xff]))

    def s_shiftl(self, em):
        e = self.e
        t, n = em.reg[4] & M32, s32(em.reg[5])
        self.emit("  shiftl %s %d %d" % (self.sym(t), n, s32(em.reg[6])))
        cnt = s8(e.u8(t))
        i = 0
        while i + n < cnt:
            e.put32(t + 16 + 16 * i, e.u32(t + 16 + 16 * (i + n)))
            e.put32(t + 20 + 16 * i, e.u32(t + 20 + 16 * (i + n)))
            i += 1
        e.write(t, bytes([(cnt - n) & 0xff]))

    def s_setpt(self, em):
        e = self.e
        t, i, p = em.reg[4] & M32, s32(em.reg[5]), em.reg[6] & M32
        self.emit("  setpt %s %d %08x %08x %d %d %d %08x" % (
            self.sym(t), i, e.u32(p), e.u32(p + 4), s8(em.reg[7]),
            s16(em.reg[8]), s8(em.reg[9]), em.fpr[12] & M32))
        if 0 <= i < 20:
            e.put32(t + 16 + 16 * i, e.u32(p))
            e.put32(t + 20 + 16 * i, e.u32(p + 4))

    def s_pullover(self, em):
        self.emit("  pullover %s %s %s %d" % (
            "M" if em.reg[4] & M32 == self.m else "?", self.sym(em.reg[5]),
            self.sym(em.reg[6]), s32(em.reg[7])))

    def s_createrb(self, em):
        p = em.reg[4] & M32
        self.emit("  createrb %s" % self.sym(p))
        self.e.put32(p + 20, self.rbs[self.nextrb] if self.nextrb >= 0
                     else 0)

    def s_collspeech(self, em):
        self.emit("  speech coll %s %s" % (self.sym(em.reg[4]),
                                           self.sym(em.reg[5])))

    def speech2(self, what):
        def fn(em):
            self.emit("  speech %s %08x %d" % (what, em.reg[5] & M32,
                                               s32(em.reg[6])))
        return fn

    # ---- the roadblocks' stubs

    def s_rbfailed(self, em):
        self.emit("  speech rbfailed %s %d" % (self.sym(em.reg[4]),
                                               s32(em.reg[5])))

    def s_rbna(self, em):
        self.emit("  speech rbna %08x" % (em.reg[5] & M32))

    def s_bust(self, em):
        pos = em.reg[4] & M32
        self.emit("  bust %08x %08x" % (self.e.u32(pos),
                                        self.e.u32(pos + 4)))

    def s_ebrake(self, em):
        self.emit("  ebrakestop %s %08x" % (self.sym(em.reg[4]),
                                            em.fpr[12] & M32))

    def s_zone(self, em):
        k = self.players.index(em.reg[4] & M32)
        self.emit("  zone %s %d %d %d %d -> %d" % (
            self.sym(em.reg[4]), s32(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8]), self.zone[k]))
        return self.zone[k]

    def s_replay(self, em):
        self.emit("  replay %s %08x %s" % (self.sym(em.reg[4]),
                                           em.fpr[12] & M32,
                                           self.cstr(em.reg[5] & M32)))

    def s_random(self, em):
        ok = "" if em.reg[4] & M32 == self.world else " ?w"
        self.emit("  random%s %d -> %d" % (ok, s32(em.reg[5]), self.rand))
        return self.rand

    def rbdump(self):
        e = self.e
        self.emit("RB nrb %d eb%s" % (
            s32(e.u32(self.m)),
            "".join(" %08x" % e.u32(d + PDRIVER_EBRAKE)
                    for d in self.pdrivers)))

    def cstr(self, a):
        b = self.e.read(a, 64)
        return b.split(b"\0")[0].decode("latin-1")

    # ---- the dumps

    def dump(self, u):
        e = self.e
        p = self.pursuits[u]
        w = lambda o: e.u32(p + o)              # noqa: E731
        i = lambda o: s32(e.u32(p + o))         # noqa: E731
        sy = lambda o: self.sym(w(o))           # noqa: E731
        o = self.emit
        o("U%d node %s %s max %d %d chased %s rb %s chopper %s cops %s %s "
          "pad %s" % (u, sy(0), sy(4), i(8), i(12), sy(16), sy(20), sy(24),
                      sy(28), sy(32), e.read(p + 36, 12).hex()))
        h = p + 1104
        o("U%d hist %d v %s t %s vptr %08x" % (
            u, s32(e.u32(h)),
            " ".join("%08x" % e.u32(h + 4 + 4 * k) for k in range(60)),
            " ".join("%08x" % e.u32(h + 244 + 4 * k) for k in range(30)),
            e.u32(h + 364)))
        o("U%d bar %s ncops %d id %d pad %s state %d sub %d hud %d "
          "spk %08x %08x lm %d joined %d hit %d backup %d" % (
              u, sy(1472), i(1476), s8(e.u8(p + 1480)),
              e.read(p + 1481, 3).hex(), i(1484), i(1488), i(1492),
              w(1496), w(1500), i(1504), i(1508), i(1512), i(1516)))
        o("U%d f %s" % (u, " ".join("%08x" % w(1520 + 4 * k)
                                    for k in range(10))))
        o("U%d rbsm %d %08x %08x %d %s chst %d rbc %d flags %08x vptr %08x "
          "pad %s" % (u, i(1560), w(1564), w(1568), i(1572), sy(1576),
                      i(1580), i(1584), w(1588), w(1592),
                      e.read(p + 1596, 4).hex()))
        b = w(1472)
        if b not in (0, 0xcdcdcdcd):
            o("%s ids %s t %s vptr %08x" % (
                self.sym(b),
                " ".join(str(s16(e.u16(b + 2 * k))) for k in range(10)),
                " ".join("%08x" % e.u32(b + 20 + 4 * k) for k in range(10)),
                e.u32(b + 60)))

    def mdump(self):
        e = self.e
        m = self.m
        w = lambda o: e.u32(m + o)              # noqa: E731
        self.emit("M plist %s %s byid %s spk %s %d %d %d beacop %08x "
                  "super %08x busy %d spawn %08x" % (
                      self.sym(w(44)), self.sym(w(48)),
                      " ".join(self.sym(w(52 + 4 * k)) for k in range(6)),
                      " ".join("%08x" % w(10308 + 4 * k) for k in range(4)),
                      s32(w(10324)), s32(w(10328)), s32(w(10332)),
                      w(10336), w(10348), s32(w(312)), e.u32(G_SPAWN)))
        self.emit("M timers %s st %s seed %08x" % (
            " ".join("%08x" % w(10356 + 4 * k) for k in range(8)),
            " ".join("%08x" % w(10388 + 4 * k) for k in range(8)),
            e.u32(G_SEED)))

    def cdump(self):
        e = self.e
        self.emit("C %s rb %s" % (
            " ".join("%s/%d" % (self.sym(e.u32(c)), s32(e.u32(c + 16)))
                     for c in self.cops),
            " ".join("%s/%s" % (self.sym(e.u32(r)), self.sym(e.u32(r + 4)))
                     for r in self.rbs)))

    def fades(self):
        e = self.e
        hit = []
        for k, b in enumerate(self.bodies):
            if e.u8(b + 1123):
                hit.append(str(k))
                e.write(b + 1123, b"\0")
        self.emit("fades" + "".join(" " + h for h in hit))

    def tdump(self, u):
        e = self.e
        p = self.pursuits[u]
        parts = ["T"]
        for off in (48, 576):
            t = p + off
            n = s8(e.u8(t))
            parts.append("%s %d" % (self.sym(t), n))
            for i in range(min(n, 20)):
                parts.append("%08x %08x" % (e.u32(t + 16 + 16 * i),
                                            e.u32(t + 20 + 16 * i)))
        self.emit(" ".join(parts))

    def mvdump(self):
        self.emit("MV" + "".join(" %08x" % self.e.u32(mv + 52)
                                 for mv in self.movers))

    # ---- the ops

    def reset(self):
        e = self.e
        m = self.m
        e.write(m, bytes(MGR_SIZE))
        for lst in (m + 44, m + 80):
            e.put32(lst, lst)
            e.put32(lst + 4, lst)
        e.put32(m + 12, M32)
        for c in self.cops:
            e.write(c, bytes(COP_SIZE))
        for r in self.rbs:
            e.write(r, bytes(RB_SIZE))
        for b in self.bodies:
            e.write(b, bytes(BODY_SIZE))
        self.blink = [0] * NCARS
        self.poofed = [0] * NCARS
        self.caused = [-1] * NCARS
        self.nisplay = [0, 0]
        self.collides = set()
        self.freerun = 0
        self.nextrb = -1
        e.put32(self.landmarks, 0)
        for d in self.pdrivers:
            e.write(d, bytes(PDRIVER_SIZE))
        self.zone = [0, 0]
        self.rand = 0

    def cop(self, s):
        k = int(s, 0)
        return self.cops[k] if k >= 0 else 0

    def car(self, s):
        k = int(s, 0)
        return self.cars[k] if k >= 0 else 0

    def u(self, p):
        return self.pursuits.index(p) if p in self.pursuits else -1

    def listed(self):
        """The pursuits on the manager's list, in its order."""
        e = self.e
        lst = self.m + 44
        out, n = [], e.u32(lst)
        while n != lst and len(out) < 64:
            out.append(n)
            n = e.u32(n)
        return out

    def pursuit_tok(self, s):
        """U<n>'s number, or L<k>, the k-th on the manager's list."""
        if s.startswith("L"):
            ps = self.listed()
            k = int(s[1:])
            return ps[k] if k < len(ps) else 0
        try:
            k = int(s, 0)
        except ValueError:
            return 0
        return self.pursuits[k] if 0 <= k < len(self.pursuits) else 0

    def op(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        m = self.m
        p = self.pursuit_tok(a[1]) if len(a) > 1 else 0
        call = lambda f, *args: e.call(f, *args, limit=2000000)  # noqa
        if o == "reset":
            self.reset()
        elif o == "rp":
            if a[1] == "Units":
                e.write(RP + RP_UNITS, bytes([v(2) & 0xff]))
            else:
                e.put32(RP + RP_FIELDS[a[1]], v(2))
        elif o == "g" and a[1] == "freerun":
            self.freerun = s32(v(2))
        elif o == "g" and a[1] == "nextrb":
            self.nextrb = s32(v(2))
        elif o == "g" and a[1] == "rand":
            self.rand = s32(v(2))
        elif o == "g":
            g = {"tracklen": TRACKLEN, "rc": self.rc, "seed": G_SEED,
                 "copcarpos": self.world + 36, "dt": G_DT,
                 "landmarks": self.landmarks, "spawn": G_SPAWN}[a[1]]
            e.put32(g, v(2))
        elif o == "m":
            f = a[1]
            k = int(f[-1]) if f[-1].isdigit() else 0
            if f in MFIELDS:
                e.put32(m + MFIELDS[f], v(2))
            elif f.startswith("spk"):
                e.put32(m + 10308 + 4 * k, v(2))
            elif f.startswith("pur"):
                e.put32(m + 10356 + 4 * k, v(2))
            elif f.startswith("stt"):
                e.put32(m + 10388 + 4 * k, v(2))
            elif f.startswith("tix"):
                e.write(m + 88 + 28 * k + 8, bytes([v(2) & 0xff]))
            elif f.startswith("act"):
                e.put32(m + 88 + 28 * k + 12, v(2))
            elif f.startswith("mcop"):
                e.put32(m + 16 + 4 * k, self.cop(a[2]))
            else:
                raise ValueError(f)
        elif o == "car":
            k = int(a[1])
            c = self.cars[k]
            pl = int(a[3])
            e.write(c + CAR_INDEX, struct.pack("<h", s16(v(2))))
            e.put32(c + CAR_PLAYER, self.players[pl] if pl >= 0 else 0)
            e.put32(c + CAR_POS, v(4))
            e.put32(c + CAR_POS + 4, v(5))
            e.put32(c + CAR_FWD, v(6))
            e.write(c + CAR_BLOWN, bytes([v(7) & 0xff]))
            e.write(e.u32(c + CAR_RACING) + 18, struct.pack("<h", s16(v(8))))
            e.put32(e.u32(c + CAR_RIDE), v(9))
            cti = e.u32(c + CAR_CTI)
            e.put32(cti + CTI_DRAG, v(10))
            e.put32(cti + CTI_MASS, v(11))
        elif o == "car2":
            k = int(a[1])
            c = self.cars[k]
            e.put32(c + CAR_VELMAG, v(2))
            e.put32(c + CAR_VELOCITY, v(3))
            e.put32(c + CAR_VELOCITY + 4, v(4))
            e.put32(c + CAR_UPZ, v(5))
            e.put32(c + CAR_JRF, v(6))
            e.put32(self.drivers[k] + 8, v(7))
            e.put32(c + CAR_MODE, v(8))
            e.put32(e.u32(c + CAR_RACING) + 32, v(9))
        elif o == "car3":
            c = self.cars[int(a[1])]
            e.put32(c + CAR_CTRL, v(2))
            e.put32(c + CAR_DAT, v(3))
            e.put32(c + CAR_POS + 8, v(4))
        elif o == "pcar":
            e.put32(self.players[int(a[1])] + 4, self.car(a[2]))
        elif o == "zone":
            self.zone[int(a[1])] = s32(v(2))
        elif o == "rb2":
            k = int(a[1])
            r, q = self.rbs[k], self.rbpts[k]
            e.put32(r + 68, v(2))
            e.put32(r + 72, v(3))
            e.put32(r + 44, v(4))
            e.put32(r + 100, v(5))
            e.put32(r + 36, q)
            e.put32(q, v(6))
            e.put32(q + 4, v(7))
            e.put32(q + 12, v(8))
            e.put32(q + 16, v(9))
        elif o == "urb":
            st = e.stubs.pop(F_URB)
            try:
                call(F_URB, p)
            finally:
                e.stubs[F_URB] = st
            self.emit("urb U%d" % self.u(p))
        elif o == "mrb":
            self.emit("mrb U%d -> %d" % (self.u(p), s32(call(F_MRB, p))))
        elif o == "rbd":
            call(F_RBD, p, v(2))
            self.emit("rbd U%d %d" % (self.u(p), v(2)))
        elif o == "rrb":
            call(F_RRB, p + 1560)
            self.emit("rrb U%d" % self.u(p))
        elif o == "eb":
            e.put32(self.pdrivers[int(a[1])] + PDRIVER_EBRAKE, v(2))
        elif o == "rbdump":
            self.rbdump()
        elif o == "cflags":
            k = int(a[1])
            self.blink[k], self.poofed[k] = s32(v(2)), s32(v(3))
            self.caused[k] = s32(v(4))
        elif o == "rpdir":
            r = self.routepts[int(a[1])]
            e.put32(r + 12, v(2))
            e.put32(r + 16, v(3))
        elif o == "collide":
            pair = (int(a[1]), int(a[2]))
            if v(3):
                self.collides.add(pair)
            else:
                self.collides.discard(pair)
        elif o == "nisp":
            self.nisplay[int(a[1])] = s32(v(2))
        elif o == "cstate":
            e.put32(self.cops[int(a[1])] + 16, v(2))
        elif o == "mover":
            e.put32(self.movers[int(a[1])] + 52, v(2))
        elif o == "lm":
            lm = self.landmarks + 4 + 60 * int(a[1])
            e.put32(lm, v(2))
            e.put32(lm + 4, v(3))
            e.put32(lm + 12, v(4))
            e.put32(lm + 52, v(5))
        elif o == "tset":
            t = p + (48 if a[2] == "far" else 576)
            e.write(t, bytes([v(3) & 0xff]))
            i = 0
            while 5 + 2 * i < len(a):
                e.put32(t + 16 + 16 * i, v(4 + 2 * i))
                e.put32(t + 20 + 16 * i, v(5 + 2 * i))
                i += 1
        elif o == "btimer":
            e.put32(e.u32(p + 1472) + 20 + 4 * int(a[2]), v(3))
        elif o == "upd":
            self.emit("upd U%d -> %d" % (self.u(p), s32(call(F_UPDATE, p))))
        elif o == "nic":
            self.emit("nic U%d -> %d" % (self.u(p), s32(call(F_NIC, p))))
        elif o == "l0":
            call(F_LEVEL0, p)
            self.emit("l0 U%d" % self.u(p))
        elif o == "calloff":
            self.emit("calloff U%d -> %d" % (self.u(p),
                                             s32(call(F_CALLOFF, p))))
        elif o == "rbsmu":
            call(F_RBSMU, p + 1560)
            self.emit("rbsmu U%d" % self.u(p))
        elif o == "bcount":
            e.fpr[12] = v(2)
            call(F_BCOUNT, e.u32(p + 1472))
            self.emit("bcount U%d %08x" % (self.u(p), v(2)))
        elif o == "udt":
            e.fpr[12] = v(2)
            call(F_UDT, p)
            self.emit("udt U%d" % self.u(p))
        elif o == "hist":
            sc = self.scratch
            for j in range(4):
                e.put32(sc + 8 + 4 * j, v(2 + j))
            e.fpr[12] = v(6)
            call(F_HIST, sc, p + 1104, sc + 8, sc + 16)
            self.emit("hist U%d -> %08x %08x" % (self.u(p), e.u32(sc),
                                                 e.u32(sc + 4)))
        elif o == "early":
            call(F_EARLY, p)
            self.emit("early U%d" % self.u(p))
        elif o == "stop":
            self.emit("stop U%d -> %d" % (self.u(p), s32(call(F_STOP, p))))
        elif o == "near":
            e.fpr[12] = v(2)
            r = call(F_NEAR, m, self.car(a[1]))
            self.emit("near %s %08x -> %d" % (self.sym(self.car(a[1])),
                                              v(2), s32(r)))
        elif o == "coll":
            r = call(F_COLL, m, self.car(a[1]))
            self.emit("coll %s -> %d" % (self.sym(self.car(a[1])), s32(r)))
        elif o == "tdump":
            self.tdump(self.u(p))
        elif o == "mvdump":
            self.mvdump()
        elif o == "acc":
            k = int(a[1])
            self.cut[k], self.low[k] = v(2), v(3)
        elif o == "cop":
            c = self.cops[int(a[1])]
            e.put32(c, 0)
            e.put32(c + 4, self.car(a[3]))
            e.put32(c + 16, 0)
            e.put32(c + 28, VT_AICOP if a[2] == "ai" else VT_PLAYERCOP)
        elif o == "rb":
            r = self.rbs[int(a[1])]
            e.put32(r, self.cop(a[2]))
            e.put32(r + 4, self.cop(a[3]))
            e.put32(r + 104, v(4))
            e.put32(r + 116, v(5))
        elif o == "strip":
            s = self.strips[int(a[1])]
            e.put32(s + 24, v(2))
            lst = m + 80
            prev = e.u32(lst + 4)
            e.put32(s, lst)
            e.put32(s + 4, prev)
            e.put32(prev, s)
            e.put32(lst + 4, s)
        elif o == "chopper":
            e.put32(self.choppers[int(a[1])] + 960, v(2))
        elif o == "pset":
            f, val = a[2], v(3)
            k = s32(val)
            if f in PFIELDS:
                e.put32(p + PFIELDS[f], val)
            elif f in ("cop0", "cop1"):
                e.put32(p + (28 if f == "cop0" else 32),
                        self.cops[k] if k >= 0 else 0)
            elif f == "rb":
                e.put32(p + 20, self.rbs[k] if k >= 0 else 0)
            elif f == "chopper":
                e.put32(p + 24, self.choppers[k] if k >= 0 else 0)
            elif f == "chased":
                e.put32(p + 16, self.cars[k] if k >= 0 else 0)
            else:
                raise ValueError(f)
        elif o == "barrel":
            b = e.u32(p + 1472)
            e.write(b + 2 * int(a[2]), struct.pack("<h", s16(v(3))))
        elif o == "new":
            q = call(F_NEW, m, v(1), self.car(a[2])) & M32
            if len(a) > 3 and self.u(q) != int(a[3]):
                raise ValueError("new made U%d, the script says U%s"
                                 % (self.u(q), a[3]))
            self.emit("new %d %s -> %s" % (s32(v(1)),
                                           self.sym(self.car(a[2])),
                                           self.sym(q)))
        elif o == "req":
            r = call(F_REQ, m, self.cop(a[1]), self.car(a[2]))
            self.emit("req %s %s -> %d" % (self.sym(self.cop(a[1])),
                                           self.sym(self.car(a[2])), r))
        elif o == "sw":
            call(F_SWITCH, p, v(2))
            self.emit("sw U%d %d" % (self.u(p), s32(v(2))))
        elif o == "st":
            e.fpr[12] = v(1)
            call(F_STATETIME)
            self.emit("st %08x -> %08x" % (v(1), e.fpr[0] & M32))
        elif o == "trans":
            self.emit("trans U%d -> %d" % (self.u(p), call(F_TRANS, p)))
        elif o == "speed":
            call(F_SPEED, p)
            self.emit("speed U%d -> %08x" % (self.u(p), e.fpr[0] & M32))
        elif o == "release":
            call(F_RELEASE, p)
            self.emit("release U%d" % self.u(p))
        elif o == "disband":
            call(F_DISBAND, p, v(2))
            self.emit("disband U%d %d" % (self.u(p), v(2)))
        elif o == "remove":
            r = call(F_REMOVE, p, self.cop(a[2]))
            self.emit("remove U%d %s -> %d" % (self.u(p),
                                               self.sym(self.cop(a[2])), r))
        elif o == "isin":
            r = call(F_ISIN, p, self.cop(a[2]))
            self.emit("isin U%d %s -> %d" % (self.u(p),
                                             self.sym(self.cop(a[2])), r))
        elif o == "rps":
            call(F_RPS, p, v(2))
            self.emit("rps U%d %d" % (self.u(p), v(2)))
        elif o == "rbr":
            self.emit("rbr U%d -> %d" % (self.u(p), call(F_RBR, p)))
        elif o == "sel":
            call(F_SEL, p)
            self.emit("sel U%d" % self.u(p))
        elif o in ("spk1", "spk2"):
            r = call(F_SPK1 if o == "spk1" else F_SPK2, p) & M32
            self.emit("%s U%d -> %08x" % (o, self.u(p), r))
        elif o == "pi":
            self.emit("pi U%d -> %d" % (self.u(p), call(F_PI, p)))
        elif o == "super":
            call(F_SUPER, m, p)
            self.emit("super U%d" % self.u(p))
        elif o == "del":
            call(F_DEL, m, p)
            self.emit("del U%d" % self.u(p))
        elif o == "dtor":
            call(F_DTOR, p, v(2))
            self.emit("dtor U%d %d" % (self.u(p), v(2)))
        elif o == "top":
            call(F_TOP, self.car(a[1]))
            self.emit("top %s -> %08x" % (self.sym(self.car(a[1])),
                                          e.fpr[0] & M32))
        elif o == "dss":
            call(F_DSS, m, s32(v(1)))   # an int: sign-extended
            self.emit("dss %d" % s32(v(1)))
        elif o == "bfade":
            e.fpr[12] = v(2)
            call(F_BFADE, e.u32(p + 1472))
            self.emit("bfade U%d %08x" % (self.u(p), v(2)))
        elif o == "ol":
            self.one_liner(a[1], self.pursuit_tok(a[2]),
                           a[3] if len(a) > 3 else None)
        elif o == "dump":
            self.dump(self.u(p))
        elif o == "ldump":
            for q in self.listed():
                self.dump(self.u(q))
        elif o == "mdump":
            self.mdump()
        elif o == "cdump":
            self.cdump()
        elif o == "fades":
            self.fades()
        else:
            raise ValueError(o)

    def one_liner(self, f, p, arg):
        e = self.e
        r = e.call(F_ONE[f], p, self.arg_for(f, arg), limit=1000)
        if f in ("addcop", "disallowall", "disallow", "allow"):
            self.emit(f)
        elif f == "dir":
            self.emit("dir %08x" % (e.fpr[0] & M32))
        elif f == "other":
            self.emit("other %s" % self.sym(r))
        else:
            self.emit("%s %d" % (f, r))

    def arg_for(self, f, arg):
        if arg is None:
            return 0
        if f in ("addcop", "other", "prim"):
            return self.cop(arg)
        if f == "primcar":
            return self.car(arg)
        return int(arg, 0) & M32

    def run(self, lines):
        for line in lines:
            self.op(line.split("|"))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================== script

INF, NAN = float("inf"), float("nan")


def car(k, index, player, x=0.0, y=0.0, vel=0.0, blown=0, finish=0,
        typ=0, drag=0.4, mass=1500.0):
    return "car|%d|%d|%d|%s|%s|%s|%d|%d|%d|%s|%s" % (
        k, index, player, F(x), F(y), F(vel), blown, finish, typ, F(drag),
        F(mass))


def rp(**kw):
    return ["rp|%s|%d" % (k, v) for k, v in kw.items()]


def m(**kw):
    out = []
    for k, v in kw.items():
        out.append("m|%s|%s" % (k, F(v) if isinstance(v, float) else v))
    return out


def pset(u, **kw):
    out = []
    for k, v in kw.items():
        out.append("pset|%d|%s|%s" % (u, k, F(v) if isinstance(v, float)
                                      else v))
    return out


def speakers(*data, head=0, tail=0, full=1):
    s = ["m|spk%d|0x%x" % (k, d) for k, d in enumerate(data)]
    return s + ["m|head|%d" % head, "m|tail|%d" % tail, "m|full|%d" % full]


def car2(k, velmag=0.0, vx=0.0, vy=0.0, upz=1.0, jrf=0, drv=0, mode=0,
         lapx=0.0):
    """The fields the Update reads past car()'s: VelocityMagnitude, the
    velocity, the body's up z, JustResetFrames, the driver's type, the
    movement mode and FinishedLapNumberExact."""
    return "car2|%d|%s|%s|%s|%s|%d|%d|%d|%s" % (
        k, F(velmag), F(vx), F(vy), F(upz), jrf, drv, mode, F(lapx))


def cars2_std():
    # The players' drivers 0, the AI cars' AI racers.
    return [car2(k, drv=0 if k < 2 else 2) for k in range(NCARS)]


def cflags(k, blink=0, poof=0, caused=-1):
    return "cflags|%d|%d|%d|%d" % (k, blink, poof, caused)


def dt(t):
    return "g|dt|%s" % F(t)


def tgt(n, last2=()):
    """A drive target's count and points: k, -k up to the last two."""
    xy = []
    for i in range(max(0, n - len(last2) // 2)):
        xy += [float(i), float(-i)]
    xy += list(last2)
    return "|".join([str(n)] + [F(c) for c in xy])


class Script(object):
    """The ops, with the pursuits' numbers kept as the stubs hand them
    out."""

    def __init__(self):
        self.s = []
        self.n = 0

    def add(self, *ops):
        for o in ops:
            if isinstance(o, list):
                self.s += o
            else:
                self.s.append(o)

    def new(self, pid, car_k, dump=True):
        u = self.n
        self.n += 1
        self.add("new|%d|%d|%d" % (pid, car_k, u))
        if dump:
            self.add("dump|%d" % u, "mdump")
        return u

    def base(self, **kw):
        """A fresh manager: medium difficulty, speakers 0x10.. queued, the
        supervisor timer off, one player, roadblocks on, the race running."""
        self.add("reset", m(diff=1, beacop="0x77", super=0.0))
        self.add(speakers(0x10, 0x11, 0x12, 0x13))
        self.add(rp(Point2Point=0, NumLaps=3, NumPlayerCars=1,
                    bRoadBlocks=1, BeACop=0, Units=0))
        self.add("g|rc|0", "g|copcarpos|0", "g|tracklen|%s" % F(5000.0))
        for k, v in kw.items():
            self.add(m(**{k: v}))


def cars_std():
    # A0 the player, A1 a second player, A2-A5 AI cars.
    return [car(0, 0, 0, 0.0, 0.0, 30.0, typ=0, drag=2.0, mass=1000.0),
            car(1, 1, 1, 100.0, 0.0, 12.5, typ=1),
            car(2, 2, -1, 10.0, 10.0, 44.0, typ=2),
            car(3, 3, -1, -40.0, 5.0, 0.0, typ=3),
            car(4, 4, -1, 25.0, -25.0, 61.0, typ=4, drag=2.0, mass=1000.0),
            car(5, 7, -1, 0.0, 0.0, 1.0, typ=5)]


def script():
    S = Script()
    S.add("g|seed|0x12345678")
    # The tables: 0 low past 50, 1 never low, 2 a NaN, 3 at once, 4 low
    # past 80, 5 an infinity past 30, 6 low at exactly 100 km/h, 7 -0.
    for k, cut, low in ((0, F(50.0), F(0.0)), (1, "0xffffffff", F(0.0)),
                        (2, "0", "0x7fc00000"), (3, "0", F(-1.0)),
                        (4, F(80.0), F(5.0)), (5, F(30.0), F(INF)),
                        (6, F(27.77777862548828), F(0.0)),
                        (7, F(60.0), "0x80000000")):
        S.add("acc|%d|%s|%s" % (k, cut, low))
    S.add(cars_std())
    S.add("cop|0|ai|2", "cop|1|ai|3", "cop|2|player|1", "cop|3|ai|4",
          "cop|4|ai|5", "cop|5|player|0", "cop|6|ai|-1", "cop|7|ai|2")

    # ---- the top speeds
    for k in range(NCARS):
        S.add("top|%d" % k)
    for typ in range(8):
        for drag, mass in ((0.4, 1500.0), (2.0, 1000.0), (0.0, 1.0),
                           (1.0, 0.0), (-1.0, 1.0), (NAN, 1.0)):
            S.add(car(5, 7, -1, typ=typ, drag=drag, mass=mass), "top|5")
    S.add(car(5, 7, -1, 0.0, 0.0, 1.0, typ=5))

    # ---- the constructor: difficulty, Be A Cop, player, AI, none, demo
    S.base()
    for diff in (0, 1, 2):
        S.add(m(diff=diff))
        S.new(diff, 0)
        S.new(diff + 3, 2)
    S.base()
    S.add(rp(BeACop=1))
    S.new(0, 0)
    S.new(1, 3)
    S.new(-1, -1)
    S.add(rp(BeACop=0))
    S.new(2, -1)
    S.add("g|rc|8")
    S.new(3, 2)
    S.new(4, 0)
    S.add(m(super=-50.0))
    S.new(5, 1)
    S.add(speakers(0x20, 0x21, 0x22, 0x23, head=1, tail=1, full=0))
    S.new(0, 0)                          # the speakers empty
    S.add("g|rc|0", "g|seed|0x00000001")
    S.add("mdump")

    # ---- the state times
    for p2p, laps, length in ((0, 3, 5000.0), (1, 3, 5000.0),
                              (0, 1, 13999.999), (0, 1, 14000.0),
                              (0, 7, 6000.0), (0, 9, 6000.0),
                              (1, 9, 42000.001), (0, 0, 1e9),
                              (0, -3, 20000.0), (0, 2, NAN), (0, 2, INF),
                              (0, 2, -INF), (1, 0, 30000.0)):
        S.add(rp(Point2Point=p2p, NumLaps=laps),
              "g|tracklen|%s" % F(length))
        for f in (30.0, 20.0, 40.0, 300.0, 10.0, 100000.0, 0.0, -1.0, NAN):
            S.add("st|%s" % F(f))
    S.add(rp(Point2Point=0, NumLaps=3), "g|tracklen|%s" % F(5000.0))

    # ---- the states, each way in
    for beacop in (0, 1):
        for chased in (0, 2):
            S.base(super=-50.0)
            S.add(rp(BeACop=beacop))
            u = S.new(1, chased, dump=False)
            for st in (0, 1, 2, 3, 4, 3, 2, 1, 0):
                S.add("sw|%d|%d" % (u, st), "dump|%d" % u)
            S.add(pset(u, flags=0))
            for st in (4, 1, 0, 3):
                S.add("sw|%d|%d" % (u, st), "dump|%d" % u)
            # Straight to LEVEL2 with nothing allowed and no backup yet.
            S.add(pset(u, flags=0, backup=0), "sw|%d|2" % u, "dump|%d" % u)
            S.add("sw|%d|5" % u, "dump|%d" % u, "mdump", "cdump")
    # The supervisor's gates.
    for rc in (0, 4, 5, 7, 9, 8, 3):
        for timer in (-50.0, -50.0009, -49.999, -50.002, -51.0, 7.0, NAN):
            for rb in (0, 1):
                for seed in (1, 2, 0x12345678, 0xdeadbeef):
                    S.base(super=timer)
                    S.add(rp(bRoadBlocks=rb), "g|seed|0x%x" % seed)
                    u = S.new(0, 0, dump=False)
                    S.add("g|rc|%d" % rc, "sw|%d|2" % u, "mdump")
                    S.add(m(super=timer), "sw|%d|3" % u, "mdump",
                          "g|rc|0")
    S.base(super=-50.0)
    u = S.new(0, 3, dump=False)
    S.add("super|%d" % u, "mdump")
    S.add(pset(u, primary="0x5"), "super|%d" % u, "mdump")
    S.add(m(super=-50.0), pset(u, primary="0x5", rb=1), "rb|1|-1|-1|0|0x99",
          "super|%d" % u, "mdump")
    S.add(m(super=-50.0), "g|seed|7", pset(u, chased=0), "super|%d" % u,
          "mdump")
    for seed in range(6):
        S.add(m(super=-50.0), "g|seed|%d" % seed, pset(u, rb=-1),
              "super|%d" % u, "mdump")
    # The give-up, with and without a player, on each car index.
    for k in range(NCARS):
        S.base()
        S.add("m|pur%d|%s" % (k if k < 5 else 7, F(3.0)))
        u = S.new(2, k, dump=False)
        S.add("cop|0|ai|2", "cop|2|player|1", pset(u, ncops=2, cop0=0,
                                                   cop1=2))
        S.add("sw|%d|5" % u, "dump|%d" % u, "mdump", "cdump")

    # ---- the transitions
    S.base()
    u = S.new(0, 2, dump=False)
    for st in (0, 1, 2, 3, 4, 5, 6, -1):
        S.add(pset(u, state=st), "trans|%d" % u, "dump|%d" % u)
    S.add(pset(u, state=0), "trans|%d" % u, "trans|%d" % u,
          "trans|%d" % u, "trans|%d" % u, "dump|%d" % u)

    # ---- the speeds
    S.base()
    u0 = S.new(0, 0, dump=False)
    u2 = S.new(1, 2, dump=False)
    for units in (0, 1, -1, 2):
        S.add(rp(Units=units))
        for vel in (0.0, 30.0, -12.5, 1e30, NAN, INF):
            S.add(car(0, 0, 0, vel=vel, typ=0, drag=2.0, mass=1000.0),
                  car(2, 2, -1, 10.0, 10.0, vel, typ=2),
                  "speed|%d" % u0, "speed|%d" % u2)
    S.add(rp(Units=0), cars_std())

    # ---- releasing the cops
    for ncops, c0, c1 in ((0, -1, -1), (1, 0, -1), (1, 2, -1), (2, 0, 1),
                          (2, 2, 0), (2, 0, 2), (2, -1, 1), (1, -1, -1),
                          (2, 3, 3)):
        for chopper, word in ((-1, 0), (0, 0), (1, 5)):
            S.base()
            S.add("cop|0|ai|2", "cop|1|ai|3", "cop|2|player|1",
                  "cop|3|ai|4")
            u = S.new(0, 0, dump=False)
            S.add(m(busy=1), "chopper|1|%d" % word)
            S.add(pset(u, ncops=ncops, cop0=c0, cop1=c1, chopper=chopper,
                       chst=2))
            S.add("release|%d" % u, "dump|%d" % u, "mdump", "cdump")
    # With a roadblock too.
    S.base()
    S.add("cop|0|ai|2", "cop|1|ai|3", "cop|3|ai|4", "rb|0|1|3|4|0x31",
          "strip|0|4", "strip|1|2", "strip|2|4")
    u = S.new(0, 0, dump=False)
    S.add(pset(u, ncops=1, cop0=0, rb=0), "release|%d" % u, "dump|%d" % u,
          "mdump", "cdump", "fades")
    # Its cop near the chased car: released with no ask to join.
    S.base()
    S.add(car(3, 3, -1, 5.0, -5.0, typ=3), "cop|1|ai|3", "rb|0|1|-1|4|0x31")
    u = S.new(0, 0, dump=False)
    S.add(pset(u, rb=0), "release|%d" % u, "dump|%d" % u, "mdump", "cdump",
          cars_std())

    # ---- disbanding
    for chased in (0, 2):
        for beacop in (0, 1):
            for players in (1, 2):
                for secondary, room in (("0x5", 0), ("0x44", 0),
                                        ("0x5", 1), ("0x44", 1)):
                    for b in (0, 1):
                        S.base()
                        S.add(rp(BeACop=beacop, NumPlayerCars=players))
                        S.add("cop|0|ai|2", "cop|1|ai|3", "cop|3|ai|4",
                              "rb|1|0|3|7|0x31", "strip|0|7", "strip|1|3",
                              "strip|2|7", "strip|3|-1")
                        u = S.new(3, chased, dump=False)
                        if room:
                            S.add(speakers(0x10, 0x11, 0x12, 0x13, head=1,
                                           tail=3, full=0))
                        S.add(pset(u, rb=1, secondary=secondary,
                                   rbstate=2))
                        S.add("barrel|%d|0|4" % u, "barrel|%d|3|5" % u,
                              "barrel|%d|9|0" % u, "barrel|%d|5|-7" % u)
                        S.add("disband|%d|%d" % (u, b), "dump|%d" % u,
                              "mdump", "cdump", "fades")
    # The distances to the chased car, and the asks that follow.
    for x, y, ox, oy in ((0.0, 0.0, 0.0, 0.0), (29.99, 0.0, 0.0, 0.0),
                         (30.0, 0.0, 0.0, 0.0), (21.2, 21.2, 0.0, 0.0),
                         (21.3, 21.3, 0.0, 0.0), (NAN, 0.0, 0.0, 0.0),
                         (-29.0, -5.0, 0.0, 0.0), (3.0, -20.0, 40.0, -7.0),
                         (-25.0, 12.0, -60.0, 33.0)):
        for give_up in (0, 1):
            S.base()
            S.add(car(0, 0, 0, ox, oy, 30.0, typ=0, drag=2.0, mass=1000.0))
            S.add(car(3, 3, -1, ox + x, oy + y, typ=3),
                  car(4, 4, -1, ox - x, oy + y, typ=4, drag=2.0,
                      mass=1000.0))
            S.add("cop|1|ai|3", "cop|3|ai|4", "rb|2|1|3|9|0x51")
            u = S.new(0, 0, dump=False)
            S.add(pset(u, rb=2))
            if give_up:
                S.add(pset(u, state=5))
            S.add("disband|%d|1" % u, "dump|%d" % u, "mdump", "cdump")
    S.add(cars_std())
    # A cop only in the roadblock's second place, and an empty one.
    S.base()
    S.add("cop|3|ai|4", "rb|0|-1|3|1|0x61", "rb|1|-1|-1|2|0x62")
    u = S.new(0, 0, dump=False)
    S.add(pset(u, rb=0), "disband|%d|1" % u, "dump|%d" % u, "cdump")
    S.add(pset(u, rb=1), "disband|%d|0" % u, "dump|%d" % u, "cdump",
          "mdump")
    S.add("disband|%d|1" % u, "dump|%d" % u)

    # ---- removing a cop, and looking for one
    S.base()
    S.add("cop|0|ai|2", "cop|1|ai|3", "cop|2|player|1", "cop|3|ai|4")
    for ncops, c0, c1, rb, who in ((2, 0, 1, -1, 0), (2, 0, 1, -1, 1),
                                   (2, 0, 1, -1, 3), (1, 0, 1, -1, 1),
                                   (2, 0, 1, 0, 2), (2, 0, 1, 0, 3),
                                   (2, -1, 1, -1, 1), (0, 0, 1, 0, 0),
                                   (2, 1, 1, -1, 1), (2, 0, 1, 0, -1),
                                   (2, -1, 1, -1, -1), (2, 0, -1, 0, -1),
                                   (3, 0, 1, -1, 1), (-1, 0, 1, 0, 2)):
        u = S.new(0, 2, dump=False)
        S.add("rb|0|2|3|1|0x7", pset(u, ncops=ncops, cop0=c0, cop1=c1,
                                      rb=rb))
        S.add("isin|%d|%d" % (u, who), "remove|%d|%d" % (u, who),
              "isin|%d|%d" % (u, who), "dump|%d" % u, "cdump")
    # A cop both chasing and in the roadblock, and one in both its places.
    for ncops, c0, c1, rbcops, who in ((2, 0, 2, "2|3", 2),
                                       (1, 3, -1, "3|2", 3),
                                       (0, -1, -1, "3|3", 3),
                                       (1, 0, -1, "1|1", 1)):
        u = S.new(0, 2, dump=False)
        S.add("rb|0|%s|1|0x7" % rbcops, pset(u, ncops=ncops, cop0=c0,
                                             cop1=c1, rb=0))
        S.add("remove|%d|%d" % (u, who), "isin|%d|%d" % (u, who),
              "dump|%d" % u, "cdump")

    # ---- the primary speaker
    for chased in (0, 2):
        for blown in (0, 1, 0x80):
            for chst in (0, 1):
                for timer in (0.0, 11.0, 11.0001, 26.0, 26.001):
                    S.base(diff=1)
                    S.add(car(0, 0, 0, blown=blown, typ=0, drag=2.0,
                              mass=1000.0),
                          car(2, 2, -1, 10.0, 10.0, 44.0, blown=blown,
                              typ=2))
                    u = S.new(0, chased, dump=False)
                    S.add(pset(u, chst=chst, rbtimer=timer), "rbr|%d" % u)
    S.add(cars_std())
    for secondary, ncops in (("0x5", 0), ("0x5", 1), ("0x5", 2),
                             ("0x44", 0), ("0x44", 3)):
        for b in (0, 1):
            for seed in (1, 2, 3, 5, 0xcafe):
                S.base()
                S.add("g|seed|0x%x" % seed)
                u = S.new(0, 0, dump=False)
                S.add(pset(u, secondary=secondary, ncops=ncops,
                           rbtimer=0.0))
                S.add("rps|%d|%d" % (u, b), "dump|%d" % u, "mdump")
    S.base()
    u = S.new(0, 2, dump=False)
    S.add("rps|%d|1" % u, "dump|%d" % u, "mdump")
    S.add(car(0, 0, 0, blown=1, typ=0, drag=2.0, mass=1000.0))
    u = S.new(1, 0, dump=False)
    S.add("rps|%d|1" % u, "dump|%d" % u, "mdump", cars_std())

    # ---- the primary cop
    S.base()
    S.add("cop|0|ai|2", "cop|1|ai|3", "cop|3|ai|4", "cop|4|ai|5")
    for c0, c1, cx, cy in ((0, 1, 0.0, 0.0), (1, 0, 0.0, 0.0),
                           (0, 3, 0.0, 0.0), (3, 0, 0.0, 0.0),
                           (0, -1, 0.0, 0.0), (-1, 1, 0.0, 0.0),
                           (3, 4, 0.0, 0.0), (4, 3, 0.0, 0.0),
                           (0, 3, -14.0, 7.5), (0, 3, -14.0, 7.6),
                           (1, 4, 1000.0, 0.0), (1, 4, NAN, 0.0)):
        S.add(car(0, 0, 0, cx, cy, typ=0, drag=2.0, mass=1000.0))
        u = S.new(0, 0, dump=False)
        S.add(pset(u, cop0=c0, cop1=c1), "sel|%d" % u, "dump|%d" % u)
    # The second's distance by its own y; and 40 against 10, exactly 30.
    S.add(car(0, 0, 0, -40.0, 0.0, typ=0, drag=2.0, mass=1000.0))
    u = S.new(0, 0, dump=False)
    S.add(pset(u, cop0=3, cop1=1), "sel|%d" % u, "dump|%d" % u)
    S.add(car(0, 0, 0, 0.0, 0.0, typ=0, drag=2.0, mass=1000.0),
          car(2, 2, -1, 0.0, 40.0, 44.0, typ=2),
          car(4, 4, -1, 0.0, 10.0, 61.0, typ=4, drag=2.0, mass=1000.0))
    for c0, c1 in ((0, 3), (3, 0)):
        u = S.new(0, 0, dump=False)
        S.add(pset(u, cop0=c0, cop1=c1), "sel|%d" % u, "dump|%d" % u)
    S.add(cars_std())

    # ---- the speakers, and who is involved
    S.base()
    u = S.new(0, 2, dump=False)
    S.add(pset(u, primary="0x5", secondary="0x5"), "spk1|%d" % u,
          "spk2|%d" % u, "rb|3|-1|-1|0|0x93", pset(u, rb=3), "spk1|%d" % u)
    S.add(pset(u, primary="0x4"), "spk1|%d" % u, pset(u, primary="0x6"),
          "spk1|%d" % u, pset(u, secondary="0x0"), "spk2|%d" % u)
    S.add(pset(u, primary="0x5", rb=-1), speakers(1, 2, 3, 4, head=2,
                                                   tail=2, full=0),
          "spk1|%d" % u, "spk2|%d" % u, speakers(9, 8, 7, 6, head=3),
          "spk1|%d" % u, "spk2|%d" % u)
    for beacop in (0, 1):
        S.add(rp(BeACop=beacop), "pi|%d" % u, pset(u, chased=0),
              "pi|%d" % u, pset(u, chased=2))
    S.add(rp(BeACop=0))

    # ---- the one-liners
    S.base()
    u = S.new(4, 0, dump=False)
    S.add("cop|0|ai|2", "cop|1|ai|3")
    S.add("ol|numcops|%d" % u, "ol|addcop|%d|0" % u, "ol|numcops|%d" % u,
          "ol|addcop|%d|1" % u, "ol|numcops|%d" % u, "ol|id|%d" % u,
          "ol|rbstate|%d" % u, "ol|dir|%d" % u, "ol|chst|%d" % u,
          "ol|over|%d" % u, "ol|called|%d" % u, "ol|landmark|%d" % u,
          "ol|hud|%d" % u, "dump|%d" % u)
    for c in (0, 1, 2, -1):
        S.add("ol|other|%d|%d" % (u, c), "ol|prim|%d|%d" % (u, c))
    for k in (2, 3, 0, -1):
        S.add("ol|primcar|%d|%d" % (u, k))
    S.add(pset(u, cop0=-1), "ol|primcar|%d|-1" % u, "ol|primcar|%d|2" % u,
          "ol|other|%d|-1" % u, pset(u, cop0=0))
    for ncops, maxc, backup in ((0, 0, 0), (1, 2, 1), (1, 2, 0), (2, 2, 1),
                                (1, 1, 1), (3, 2, 1), (-1, 0, 0)):
        S.add(pset(u, ncops=ncops, maxchase=maxc, backup=backup),
              "ol|needed|%d" % u, "ol|called|%d" % u)
    for st in (0, 4, 5, 6):
        S.add(pset(u, state=st), "ol|over|%d" % u)
    S.add(pset(u, flags="0x20f"))
    for bit in ("0x1", "0x4", "0x10", "0x200", "0xffffffff", "0"):
        S.add("ol|allowed|%d|%s" % (u, bit))
    S.add("ol|disallow|%d|0x5" % u, "ol|allowed|%d|0xffffffff" % u,
          "ol|allow|%d|0x80000000" % u, "ol|allowed|%d|0xffffffff" % u,
          "ol|disallow|%d|0x30" % u, "ol|allowed|%d|0xffffffff" % u,
          "ol|allow|%d|0x80000002" % u, "ol|allowed|%d|0xffffffff" % u,
          "ol|disallowall|%d" % u, "ol|allowed|%d|0xffffffff" % u,
          pset(u, landmark=-7), "ol|landmark|%d" % u, "dump|%d" % u)
    for rbstate, chst in ((1, 2), (2, 1), (-1, 3)):
        S.add(pset(u, rbstate=rbstate, chst=chst), "ol|rbstate|%d" % u,
              "ol|chst|%d" % u)

    # ---- deleting, and the destructor
    for chased, secondary, barrels, room in (
            (0, "0x5", (), 0), (0, "0x44", ((0, 0), (3, 7)), 0),
            (2, "0x44", ((0, 3), (3, 4), (6, 5)), 0),
            (1, "0x5", ((0, 1),), 0), (0, "0x5", ((9, 6), (4, -2)), 1),
            (0, "0x44", (), 1), (2, "0x5", ((9, 1),), 1),
            (2, "0x44", (), 1)):
        S.base()
        S.add("cop|0|ai|2", "cop|2|player|1", "cop|3|ai|4",
              "rb|0|3|-1|2|0x71", "strip|0|2")
        if room:
            S.add(speakers(0x10, 0x11, 0x12, 0x13, head=2, tail=3, full=0))
        u = S.new(2, chased, dump=False)
        v = S.new(3, 4, dump=False)
        S.add(pset(u, ncops=2, cop0=0, cop1=2, rb=0, secondary=secondary))
        for slot, bid in barrels:
            S.add("barrel|%d|%d|%d" % (u, slot, bid))
        S.add("del|%d" % u, "dump|%d" % u, "dump|%d" % v, "mdump",
              "cdump", "fades")
        S.add("del|%d" % v, "dump|%d" % v, "mdump")
    # A player's chase with no roadblock and no secondary speaker.
    S.base()
    S.add(speakers(0x10, 0x11, 0x12, 0x13, head=2, tail=3, full=0))
    u = S.new(2, 0, dump=False)
    S.add(pset(u, primary="0x33"), "del|%d" % u, "dump|%d" % u, "mdump")
    S.base()
    u = S.new(1, 0, dump=False)
    S.add("dtor|%d|0" % u, "dump|%d" % u, "mdump")
    u = S.new(5, 2, dump=False)
    S.add("barrel|%d|1|9" % u, "dtor|%d|2" % u, "dump|%d" % u, "mdump")
    u = S.new(-1, 3, dump=False)
    S.add("mdump", "del|%d" % u, "dump|%d" % u, "mdump")
    S.add("del|-1", "mdump")

    # ---- the spike strips and the barrels' fade
    S.base()
    for k, rid in enumerate((3, -1, 3, 0, 7, 3)):
        S.add("strip|%d|%d" % (k, rid))
    for i in (3, -1, 0, 5, 7, 3):
        S.add("dss|%d" % i)
    u = S.new(0, 0, dump=False)
    for slot, bid in ((0, 0), (1, 1), (2, 2), (4, 15), (6, 16), (7, -2),
                      (9, 13)):
        S.add("barrel|%d|%d|%d" % (u, slot, bid))
    for t in (2.0, 0.0, -1.0, NAN, 1e30):
        S.add("bfade|%d|%s" % (u, F(t)), "dump|%d" % u, "fades")
    S.add("mdump")

    # The Update's, before RequestPursuit makes pursuits the numbering
    # above does not count.
    update_script(S)

    # ---- asking for a chase
    def asks(beacop, players, copcarpos=0):
        S.base()
        S.add(rp(BeACop=beacop, NumPlayerCars=players),
              "g|copcarpos|%d" % copcarpos, "m|tix0|3", "m|tix1|-2",
              "m|tix2|5", "m|tix7|1")
        S.add("cop|0|ai|2", "cop|1|ai|3", "cop|2|player|1", "cop|3|ai|4",
              "cop|4|ai|5", "cop|5|player|0", "cop|6|ai|-1", "cop|7|ai|2")

    def reqs(*pairs):
        for c, k in pairs:
            S.add("req|%d|%d" % (c, k), "mdump")

    sweep = ((0, 0), (1, 0), (3, 0), (1, 2), (3, 2), (4, 3), (0, 4),
             (4, 4), (7, 5), (6, 5), (0, 1), (1, 1), (3, 1), (2, 1))
    for beacop, players, ccp in ((0, 1, 0), (0, 1, 3), (0, 1, 2),
                                 (0, 1, 4), (0, 2, 0), (0, 3, 5),
                                 (0, 0, 0)):
        asks(beacop, players, ccp)
        reqs(*sweep)
        S.add("ldump", "cdump")
    # A chase given up on, and the second cop on an AI car.
    asks(0, 1)
    reqs((0, 2))
    S.add("pset|L0|state|5")
    reqs((1, 2), (1, 3), (3, 3), (4, 4), (4, 5))
    S.add("ldump", "cdump")
    # The player's second cop: only once the first called for backup, and
    # not with the World's CopCarPos at 3 or more.
    asks(0, 1)
    reqs((0, 0), (1, 0))
    S.add("pset|L0|backup|1")
    reqs((1, 0), (3, 0))
    S.add("pset|L0|ncops|1", "g|copcarpos|3")
    reqs((3, 0))
    S.add("pset|L0|ncops|0")
    reqs((3, 0))
    S.add("ldump", "cdump")
    # A finished car, and each finish reason.
    for reason in (1, -1, 0x100, 0):
        asks(0, 1)
        S.add(car(3, 3, -1, -40.0, 5.0, finish=reason, typ=3))
        reqs((1, 3))
        S.add("ldump")
    S.add(cars_std())
    # Be A Cop: only the player's cop, a new chase each time.
    for pcidx, slot_cop in ((2, 5), (2, 0), (-1, 5), (6, 2)):
        asks(1, 1)
        S.add("m|pcidx|%d" % pcidx, "m|mcop2|%d" % slot_cop,
              "m|mcop6|%d" % slot_cop)
        reqs((5, 3), (5, 3), (0, 3), (2, 0), (5, 1))
        S.add("ldump", "cdump")
    # Split screen.
    asks(0, 2)
    reqs((0, 0), (1, 0), (3, 2), (4, 3), (4, 2), (7, 1), (1, 1))
    S.add("pset|L1|ncops|0")
    reqs((4, 2), (4, 3))
    S.add("ldump", "cdump")

    return S.s


def update_script(S):
    """tPursuit::Update and the calls under it."""
    # ---- NotInChasingState and the level-0 speeches
    S.base()
    S.add(cars_std(), cars2_std())
    u = S.new(0, 0, dump=False)
    for st in (0, 1, 2, 3, 4, 5, 6, -1, 0x7fffffff):
        S.add(pset(u, state=st), "nic|%d" % u)
    for sub in (0, 1, 2, 3, -1):
        for timer in (16.0, 15.999, 3.0, 2.999, 0.0, -5.0, NAN, 20.0):
            S.add(pset(u, sub=sub, timer=timer), "l0|%d" % u, "dump|%d" % u)

    # ---- ShouldPursuitBeCalledOff
    for blown, p2p, free, laps, lapx, length in (
            (0, 0, 0, 4, 2.0, 1000.0), (0, 0, 0, 4, 1.999, 1000.0),
            (1, 0, 0, 4, 3.0, 1000.0), (0x80, 0, 0, 4, 3.0, 1000.0),
            (0, 1, 0, 4, 3.0, 1000.0), (0, 0, 1, 4, 3.0, 1000.0),
            (0, 0, 0, 3, 2.9, 1000.0), (0, 0, 0, 5, 3.0, 1000.0),
            (0, 0, 0, 10, 9.6, 5000.0), (0, 0, 0, 10, 9.5, 4000.0),
            (0, 0, 0, 4, NAN, 1000.0), (0, 0, 0, 4, 3.0, NAN),
            (0, 0, 0, 4, 5.0, 1000.0), (0, 0, 0, 4, 0.0, INF),
            (0, 0, 0, -1, 0.0, 1.0), (0, 0, 0, 7, 6.0, 2000.0),
            (0, 0, 0, 7, 6.0, 2000.25)):
        S.base()
        S.add(rp(Point2Point=p2p, NumLaps=laps), "g|freerun|%d" % free,
              "g|tracklen|%s" % F(length))
        S.add(car(0, 0, 0, blown=blown, typ=0, drag=2.0, mass=1000.0),
              car2(0, lapx=lapx))
        u = S.new(0, 0, dump=False)
        S.add("calloff|%d" % u)
    S.add(cars_std(), cars2_std())

    # ---- the roadblock's state machine
    S.base()
    u = S.new(0, 0, dump=False)
    for state in (0, 1, 2, -1):
        for timer in (1.0, 0.5, 0.25, 0.0, -1.0, NAN):
            for d in (0.5, 0.25, 0.0):
                for nrb in (-1, 0):
                    S.add(pset(u, rbstate=state, rbsmt=timer, rb=-1), dt(d),
                          "g|nextrb|%d" % nrb, "rbsmu|%d" % u, "dump|%d" % u)

    # ---- the barrels counting down
    S.base()
    u = S.new(0, 0, dump=False)
    for slot, bid in ((0, 0), (1, 1), (2, 2), (3, -2), (4, 4), (5, 5),
                      (6, 6), (8, 8), (9, 9)):
        S.add("barrel|%d|%d|%d" % (u, slot, bid))
    for slot, t in ((0, 0.5), (1, 0.25), (2, -1.0), (3, 0.1), (4, NAN),
                    (5, 0.0), (6, 1e30), (7, 0.1), (8, -0.0), (9, 0.2)):
        S.add("btimer|%d|%d|%s" % (u, slot, F(t)))
    for d in (0.25, 0.0, 0.1, 0.25, NAN, -1.0, 0.5, 1e31):
        S.add("bcount|%d|%s" % (u, F(d)), "dump|%d" % u)

    # ---- the history
    S.base()
    u = S.new(0, 0, dump=False)
    for k in range(33):
        S.add("hist|%d|%s|%s|%s|%s|%s" % (u, F(k * 1.5), F(-k), F(k + 0.25),
                                          F(2.0 * k), F(0.03125 * (k + 1))))
        if k in (0, 1, 28, 29, 30, 32):
            S.add("dump|%d" % u)

    # ---- the drive targets
    S.base()
    S.add(car(0, 0, 0, 12.5, -3.0, typ=0, drag=2.0, mass=1000.0),
          car2(0, vx=4.0, vy=-2.5), dt(0.0333))
    u = S.new(0, 0, dump=False)
    fars = (tgt(0), tgt(1, (7.0, 7.0)), tgt(2, (0.0, 0.0, 19.99, 0.0)),
            tgt(2, (0.0, 0.0, 20.0, 0.0)), tgt(2, (0.0, 0.0, 12.0, 16.0)),
            tgt(3, (0.0, 0.0, 0.0, 20.5)), tgt(20, (0.0, 0.0, 30.0, 0.0)),
            tgt(20, (0.0, 0.0, 5.0, 0.0)), tgt(19, (0.0, 0.0, 25.0, 0.0)),
            tgt(2, (NAN, 0.0, 0.0, 0.0)), tgt(2, (3.0, 1.0, 3.0, 1.0)),
            "-51")
    nears = (tgt(0), tgt(1, (7.0, 7.0)), tgt(2, (0.0, 0.0, 1.0, 0.0)),
             tgt(2, (0.0, 0.0, 1.0000001, 0.0)), tgt(20, (0.0, 0.0, 2.0, 0.0)),
             tgt(20, (0.0, 0.0, 0.5, 0.0)), tgt(2, (0.0, 1.0, 0.0, 0.0)),
             tgt(2, (0.0, 0.0, INF, 0.0)), tgt(2, (0.0, 0.0, 0.0, -1.5)),
             "-51", tgt(19, (0.0, 0.0, 0.0, 3.0)))
    for far in fars:
        S.add("tset|%d|far|%s" % (u, far),
              "tset|%d|near|%s" % (u, tgt(2, (0.0, 0.0, 3.0, 0.0))),
              "udt|%d|%s" % (u, F(123.0)), "tdump|%d" % u, "dump|%d" % u)
    for near in nears:
        S.add("tset|%d|far|%s" % (u, tgt(2, (0.0, 0.0, 3.0, 0.0))),
              "tset|%d|near|%s" % (u, near),
              "udt|%d|%s" % (u, F(-1.0)), "tdump|%d" % u, "dump|%d" % u)
    # Frames on, the car moving 0.7 m each: the near target keeps the
    # last point until it is a metre on, the far one until 20.
    S.add("tset|%d|far|0" % u, "tset|%d|near|0" % u)
    for k in range(40):
        S.add(car(0, 0, 0, 12.5 + 0.7 * k, -3.0 + 0.35 * k, typ=0, drag=2.0,
                  mass=1000.0), "udt|%d|0" % u)
    S.add("tdump|%d" % u, "dump|%d" % u, cars_std(), cars2_std())

    # ---- the early chase collision check
    for chased, sub, hit, cop0, caused, state in (
            (2, 1, 0, 0, 3, 0), (0, 1, 1, 0, 3, 0), (0, 1, 0, 0, -1, 0),
            (0, 0, 0, 0, 3, 0), (0, 0, 0, -1, 2, 2), (0, 1, 0, 0, 2, 0),
            (0, 1, 0, -1, 3, 0), (0, 1, 0, 0, 3, 0), (0, 1, 0, 1, 4, 0),
            (0, 1, 0, 1, 4, 1), (0, 1, 0, 1, 4, 3), (0, 2, 0, 0, 2, 3),
            (0, 1, 0, 0, 5, 0), (0, -1, 0, 1, 1, 0), (1, 3, 0, 0, 2, 1)):
        S.base()
        S.add(cars_std(), cars2_std(), car2(3, drv=4), car2(1, drv=4))
        S.add("cop|0|ai|2", "cop|1|ai|3")
        u = S.new(0, chased, dump=False)
        S.add(pset(u, sub=sub, hit=hit, cop0=cop0, state=state, landmark=7),
              cflags(chased, caused=caused), "early|%d" % u, "dump|%d" % u,
              "mdump")
    S.add(cars2_std())

    # ---- IsCopNearby and DidRecentlyCollideWithCop
    S.base()
    S.add(cars_std(), cars2_std())
    S.add("cop|0|ai|2", "cop|1|ai|3", "cop|2|player|1", "cop|3|ai|4",
          "cop|4|ai|5", "cop|6|ai|-1")
    S.add(m(ncops=5), "m|mcop0|1", "m|mcop1|2", "m|mcop2|0", "m|mcop3|3",
          "m|mcop4|4")
    for st in range(-1, 10):
        for c in (0, 1, 2, 3, 4):
            S.add("cstate|%d|%d" % (c, st))
        for k, d in ((0, 200.0), (0, 20.0), (0, 14.142136), (0, 14.142135),
                     (0, 0.0), (3, 30.0), (1, 1.0)):
            S.add("near|%d|%s" % (k, F(d)))
    for states in ((3, 7, 1, 8, 0), (0, 0, 0, 0, 8), (6, 6, 6, 6, 6),
                   (9, 2, 5, 4, 7)):
        for c, st in enumerate(states):
            S.add("cstate|%d|%d" % (c, st))
        for nis in (0, 1):
            S.add("nisp|1|%d" % nis)
            for k, d in ((0, 200.0), (0, 101.0), (0, 20.0), (0, 0.0),
                         (5, 1.0), (2, NAN)):
                S.add("near|%d|%s" % (k, F(d)))
    S.add("nisp|1|0")
    S.add(rp(BeACop=1), "m|pcidx|2", "m|mcop2|0")
    for k, d in ((0, 14.142136), (0, 14.142135), (5, 14.2), (2, 0.0),
                 (3, 60.0), (1, 90.0), (1, 90.000001), (0, NAN)):
        S.add("near|%d|%s" % (k, F(d)))
    S.add(rp(BeACop=0), m(ncops=5), "m|mcop2|0")
    for pairs in ((), ((0, 3),), ((0, 4),), ((0, 2), (0, 3)), ((2, 5),),
                  ((0, 5), (0, 1)), ((3, 0),)):
        for i, j in pairs:
            S.add("collide|%d|%d|1" % (i, j))
        for k in (0, 2, 3):
            S.add("coll|%d" % k)
        for i, j in pairs:
            S.add("collide|%d|%d|0" % (i, j))
    S.add("collide|0|5|1", m(ncops=6), "m|mcop5|6", "coll|0")
    S.add(m(ncops=0), "coll|0", m(ncops=-1), "coll|0")

    stoppable_script(S)
    update_frames_script(S)


def stop_base(S, chased=0, beacop=0, players=1, diff=1):
    """A chase of A{chased} for IsChasedCarStoppable, C0 (on A2, in
    HOT_PURSUIT) its first cop and the manager's only one; Be A Cop's
    player cop C2, on A1."""
    S.base(diff=diff)
    S.add(rp(BeACop=beacop, NumPlayerCars=players, bTickets=1))
    S.add(cars_std(), cars2_std(), "cop|0|ai|2", "cop|2|player|1",
          m(ncops=1), "m|mcop0|0", "m|pcidx|2", "m|mcop2|2", "cstate|0|6")
    u = S.new(0, chased, dump=False)
    S.add(pset(u, cop0=0, catch=2.0), dt(0.5))
    return u


def at(u, ops):
    """The ops with pset(0, ...)'s pursuit made U{u}."""
    out = []
    for o in ops:
        for x in (o if isinstance(o, list) else [o]):
            out.append(x.replace("pset|0|", "pset|%d|" % u))
    return out


def stops(S, u, n):
    for _ in range(n):
        S.add("stop|%d" % u, "dump|%d" % u)


def stoppable_script(S):
    # ---- the gates
    for gate in ("rp|bTickets|0", "m|act0|1", "m|act1|1", "cflags|0|0|1|-1",
                 "car|0|0|0|0x0|0x0|0x0|0|2|0|0x40000000|0x447a0000",
                 "m|act7|1"):
        u = stop_base(S)
        S.add(car(2, 2, -1, 5.0, 0.0, typ=2), car2(0, velmag=4.0), gate)
        stops(S, u, 2)
    for gate in ("m|act7|1", "m|act5|1"):
        u = stop_base(S, chased=5)
        S.add(car(2, 2, -1, 5.0, 0.0, typ=2), car2(5, velmag=4.0, drv=2),
              gate)
        stops(S, u, 2)

    # ---- not Be A Cop: the catch timer runs down beside a slow car
    for prep in ((), (car(2, 2, -1, 10.0, 0.0, typ=2),),
                 (car(2, 2, -1, 10.001, 0.0, typ=2),),
                 ("collide|0|2|1",), (car2(0, velmag=4.47),),
                 (car2(0, velmag=4.4703),), (car2(0, velmag=4.4704),),
                 (car2(0, velmag=4.7),),
                 (car2(0, velmag=-50.0),), (car2(0, velmag=NAN),),
                 (pset(0, n1556=0.0),), (pset(0, n1556=-0.0),),
                 (pset(0, n1556=0.001),), (pset(0, n1556=NAN),),
                 (dt(1.0), "collide|0|2|1"), (dt(0.98), "collide|0|2|1"),
                 (dt(0.0),), (dt(-0.25),), (pset(0, catch=NAN),),
                 (car(0, 0, 0, blown=1, typ=0, drag=2.0, mass=1000.0),
                  car2(0, velmag=0.05)),
                 (car(0, 0, 0, blown=0x80, typ=0, drag=2.0, mass=1000.0),
                  car2(0, velmag=0.0999)),
                 (car(0, 0, 0, blown=1, typ=0, drag=2.0, mass=1000.0),
                  car2(0, velmag=0.1)),
                 (cflags(0, blink=1),), (cflags(0, blink=1),
                                         car2(0, velmag=4.0, jrf=2)),
                 (car2(0, velmag=4.0, upz=0.1),),
                 (car2(0, velmag=4.48, upz=0.1),),
                 (car2(0, velmag=4.0, upz=0.10000001),),
                 (car2(0, velmag=40.0, upz=-1.0),),
                 (car2(0, velmag=0.0, upz=-1.0),)):
        u = stop_base(S)
        S.add(car(2, 2, -1, 5.0, 0.0, typ=2), car2(0, velmag=4.0))
        S.add(at(u, prep))
        stops(S, u, 5)
    # No first cop: an AI racer counts as near, a player does not.
    for chased, drv in ((0, 0), (2, 2), (2, 4), (0, 2)):
        u = stop_base(S, chased=chased)
        S.add(pset(u, cop0=-1), car2(chased, velmag=4.0, drv=drv))
        stops(S, u, 5)
    # An AI car blinking.
    u = stop_base(S, chased=2)
    S.add(car2(2, velmag=40.0, drv=2), cflags(2, blink=1))
    stops(S, u, 1)
    u = stop_base(S, chased=2)
    S.add(car(2, 2, -1, 5.0, 0.0, typ=2), car2(2, velmag=40.0, drv=2),
          cflags(2, blink=1), m(ncops=0))
    stops(S, u, 1)

    # ---- Be A Cop: the player's cop on A1, the chased car A0 at 0, 0
    def bac(prep, diff=1, players=1, n=6, chased=0):
        u = stop_base(S, chased=chased, beacop=1, players=players, diff=diff)
        S.add(car(1, 1, 1, 5.0, 0.0, 2.0, typ=1), car2(1, velmag=2.0),
              car2(chased, velmag=3.0, drv=0 if chased < 2 else 2))
        S.add(at(u, prep))
        stops(S, u, n)

    bac(())
    for diff, v in ((0, 8.9), (0, 8.95), (1, 6.7054), (1, 6.71), (2, 6.0)):
        bac((car2(0, velmag=v),), diff=diff)
    for players, x, v in ((2, 10.5, 9.0), (1, 10.5, 3.0), (2, 11.0, 3.0),
                          (2, 10.999, 10.05), (2, 5.0, 10.06),
                          (3, 10.5, 3.0), (2, 0.0, 10.058)):
        bac((car(1, 1, 1, x, 0.0, 2.0, typ=1), car2(0, velmag=v)),
            players=players)
    for prep in ((car2(1, velmag=6.705409),), (car2(1, velmag=6.7054),),
                 (car2(1, velmag=NAN),), (car(1, 1, 1, 10.0, 0.0, typ=1),),
                 (car(1, 1, 1, 9.999, 0.0, typ=1),),
                 (car(1, 1, 1, NAN, 0.0, typ=1),),
                 (pset(0, catch=1.8),), (pset(0, catch=1.8),
                                         car(1, 1, 1, 50.0, 0.0, typ=1)),
                 (pset(0, catch=NAN),), (dt(0.0),), (dt(3.0),),
                 (car(0, 0, 0, blown=1, typ=0, drag=2.0, mass=1000.0),
                  car2(0, velmag=0.05)),
                 (car(0, 0, 0, blown=1, typ=0, drag=2.0, mass=1000.0),
                  car2(0, velmag=0.1)),
                 (car2(0, velmag=4.0, upz=0.1),),
                 (car2(0, velmag=4.47, upz=0.1, drv=0),),
                 (car2(0, velmag=40.0, upz=0.1),),
                 (car2(0, velmag=40.0),),
                 (cflags(0, blink=1),),
                 (cflags(0, blink=1), car2(0, velmag=40.0, jrf=1)),
                 (cflags(0, blink=1), car2(0, velmag=40.0, jrf=1),
                  car2(1, velmag=7.0)),
                 (cflags(0, blink=1), car2(0, velmag=40.0),
                  car(1, 1, 1, 29.0, 0.0, typ=1))):
        bac(prep)
    # A chased AI car blinking: within 30 m of A2 at 10, 10.
    for x in (29.99, 30.0, 35.0, 12.0, NAN):
        bac((cflags(2, blink=1), car2(2, velmag=40.0, drv=2),
             car(1, 1, 1, 10.0 + x, 10.0, typ=1)), chased=2, n=2)


def update_frames_script(S):
    """The Update itself, frame by frame."""
    def setup(chased=0, beacop=0, players=1, laps=3):
        S.base()
        S.add(rp(BeACop=beacop, NumPlayerCars=players, NumLaps=laps,
                 bTickets=1, RaceType=0))
        S.add(cars_std(), cars2_std(), car2(2, drv=2, mode=5),
              car2(3, drv=2, mode=0), car2(4, drv=2, mode=5))
        S.add("lm|0|4|%s|%s|7" % (F(0.0), F(10.0)),
              "lm|1|5|%s|%s|3" % (F(-50.0), F(-30.0)),
              "lm|2|6|%s|%s|9" % (F(5.0), F(20.0)), "g|landmarks|3")
        S.add("cop|0|ai|2", "cop|1|ai|3", "cop|3|ai|4", "cop|2|player|1",
              m(ncops=2), "m|mcop0|0", "m|mcop1|1", "m|pcidx|2",
              "m|mcop2|2")
        for k in range(NCARS):
            S.add("mover|%d|%s" % (k, F(-1.0)))
        u = S.new(0, chased, dump=False)
        S.add(pset(u, ncops=2, cop0=0, cop1=1), "cstate|0|6", "cstate|1|6",
              dt(0.5))
        return u

    def frames(u, n):
        for _ in range(n):
            S.add("upd|%d" % u, "dump|%d" % u, "tdump|%d" % u, "mvdump",
                  "cdump", "mdump")

    # A plain chase: the state timer runs out into a transition.
    u = setup()
    S.add(pset(u, timer=0.6))
    frames(u, 3)
    # Run out to exactly 0, and given up with the timer out.
    for st, timer in ((0, 0.5), (5, 0.25), (5, 0.5), (5, 1.0)):
        u = setup()
        S.add(pset(u, state=st, timer=timer))
        frames(u, 2)
    # The barrels fading out frame by frame.
    u = setup()
    for slot, bid, t in ((0, 3, 0.75), (2, 5, 0.25), (9, 7, -1.0)):
        S.add("barrel|%d|%d|%d" % (u, slot, bid),
              "btimer|%d|%d|%s" % (u, slot, F(t)))
    frames(u, 3)
    # The timer stands still with no cops below LEVEL3, and runs at 3.
    for st, ncops in ((0, 0), (2, 0), (3, 0), (1, 1)):
        u = setup()
        S.add(pset(u, state=st, ncops=ncops, timer=0.75))
        frames(u, 2)
    # Split screen and a finished car: over at once.
    for players, reason in ((2, 1), (2, 0), (1, 1), (0, 1), (3, -1)):
        u = setup(players=players)
        S.add(car(0, 0, 0, 7.0, 0.0, 30.0, finish=reason, typ=0, drag=2.0,
                  mass=1000.0))
        frames(u, 1)
    # A blown tyre counts New1556 down.
    u = setup()
    S.add(car(0, 0, 0, 7.0, 0.0, 30.0, blown=2, typ=0, drag=2.0,
              mass=1000.0), car2(0, velmag=30.0))
    frames(u, 2)
    # A race of type 3 ends with the car's finish.
    for reason in (0, 1):
        u = setup()
        S.add(rp(RaceType=3), car(0, 0, 0, 7.0, 0.0, 30.0, finish=reason,
                                  typ=0, drag=2.0, mass=1000.0))
        frames(u, 1)
    # Called off near the end of a long race.
    for lapx in (3.5, 2.0):
        u = setup(laps=4)
        S.add("g|tracklen|%s" % F(1000.0), car2(0, lapx=lapx))
        frames(u, 2)
    # The top speed: past it, the movers of the cops in COP_MOVEMENT
    # take it.
    for fwd in (30.0, 100.0, -5.0, NAN):
        u = setup()
        S.add(car(0, 0, 0, 7.0, 0.0, fwd, typ=0, drag=2.0, mass=1000.0),
              pset(u, top=40.0))
        frames(u, 1)
    u = setup()
    S.add(pset(u, ncops=1, cop0=1, cop1=0))
    frames(u, 1)
    # Caught: slow beside the first cop.
    for state in (2, 4, 5, 0):
        u = setup()
        S.add(car(2, 2, -1, 9.0, 0.0, typ=2), car2(0, velmag=1.0),
              pset(u, state=state, catch=0.25))
        frames(u, 2)
    # The roadblock called for, set, and the level-0 speech.
    for st, timer, nrb in ((1, 0.25, 0), (1, 0.75, 0), (1, 0.5, -1),
                           (2, 0.5, 0), (0, 0.5, 0)):
        u = setup()
        S.add(pset(u, rbstate=st, rbsmt=timer, timer=10.0), "g|nextrb|%d" %
              nrb)
        frames(u, 2)
    # LEVEL1 and up: the early check only at 0 and 1.
    for st in (1, 2, 3, 5, 6):
        u = setup()
        S.add(pset(u, state=st, sub=1, timer=50.0),
              cflags(0, caused=4))
        frames(u, 1)
    # The landmarks under the car.
    for x in (7.0, 15.0, -40.0, -100.0, 10.0, NAN):
        u = setup()
        S.add(car(0, 0, 0, x, 0.0, 30.0, typ=0, drag=2.0, mass=1000.0))
        frames(u, 1)
    # Be A Cop: one player, then two with the chase's direction.
    u = setup(beacop=1)
    frames(u, 2)
    for vx, rdx, cdir, dirt in ((-3.0, 1.0, 1.0, 7.6), (-3.0, 1.0, 1.0, 0.0),
                                (3.0, 1.0, 1.0, 7.9), (0.0, 1.0, -1.0, 7.5),
                                (3.0, -1.0, -1.0, 2.0), (NAN, 1.0, 1.0, 7.6),
                                (-3.0, 1.0, 0.0, 7.5), (2.0, 1.0, -1.0, 9.0),
                                (-0.1, 1.0, 1.0, 7.6), (-0.125, 1.0, 1.0, 7.6),
                                (-0.125, 1.0, -1.0, 7.6)):
        u = setup(beacop=1, players=2)
        S.add(car2(0, vx=vx, vy=0.5), "rpdir|0|%s|%s" % (F(rdx), F(0.25)),
              pset(u, dir=cdir, dirt=dirt))
        frames(u, 2)
    # Be A Cop caught.
    u = setup(beacop=1)
    S.add(car(1, 1, 1, 5.0, 0.0, 2.0, typ=1), car2(1, velmag=2.0),
          car2(0, velmag=1.0), pset(u, catch=0.25))
    frames(u, 2)
    S.add(cars_std(), cars2_std())

    rb_script(S)


def car3(k, ctrl=None, dat=0.0, z=0.0):
    """The control mode (REAL for the players, AI for the rest), the
    distance around the track and the height."""
    if ctrl is None:
        ctrl = 1 if k < 2 else 2
    return "car3|%d|%d|%s|%s" % (k, ctrl, F(dat), F(z))


def rb2(k, x=50.0, y=0.0, width=12.0, dat=1000.0, rpx=40.0, rpy=0.0,
        dx=1.0, dy=0.0):
    """A roadblock's spot, road width and distance around the track, and
    its route point's position and direction."""
    return "rb2|%d|%s" % (k, "|".join(F(f) for f in (
        x, y, width, dat, rpx, rpy, dx, dy)))


def c0(x=0.0, y=0.0, vel=30.0, blown=0):
    """A0, the player's car, moved."""
    return car(0, 0, 0, x, y, vel, blown=blown, typ=0, drag=2.0,
               mass=1000.0)


def rb_script(S):
    """The roadblocks: RequestRoadBlock, MonitorRoadBlock,
    RoadBlockDefeated and UpdateRoadBlocks. The roadblock R0's cops C3
    and C4 ride A3 and A4, more than 30 from where the chased car goes,
    so that DisbandRoadBlock asks for no pursuit."""
    def setup(chased=0, beacop=0, players=1, laps=3, p2p=0, rb=True):
        S.base()
        S.add(rp(BeACop=beacop, NumPlayerCars=players, NumLaps=laps,
                 Point2Point=p2p, bTickets=1, RaceType=0, bHelicopter=0,
                 New624=0))
        S.add(cars_std(), cars2_std(), "pcar|0|0", "pcar|1|1")
        S.add([car3(k) for k in range(NCARS)])
        S.add("cop|3|ai|3", "cop|4|ai|4", "rb|0|3|4|2|0x71", rb2(0))
        u = S.new(0, chased, dump=False)
        if rb:
            S.add(pset(u, rb=0))
        S.add(dt(0.5), "g|spawn|%s" % F(20.0), pset(u, dir=1.0))
        return u

    def after(u):
        S.add("dump|%d" % u, "rbdump")

    # ---- RequestRoadBlock
    for beacop in (0, 1):
        u = setup(beacop=beacop)
        for st in (1, -1, 2):
            S.add(pset(u, rbstate=st), "rrb|%d" % u)
            after(u)
        cases = []
        for sf in (0, 1, 3, 2):
            for beh in (0, 0x10, 0x18, 8, 0xffffffff):
                cases.append((sf, beh, 0.0, 3))
        for sup in (0.001, 0.0011, -0.001, -0.0011, NAN, INF, 0.00099):
            for sf, beh in ((0, 0), (0, 0x10), (1, 0)):
                cases.append((sf, beh, sup, 3))
        for nrb in (0, 1, -1, 7):
            cases += [(0, 8, 0.0, nrb), (1, 8, 0.0, nrb)]
        for sf, beh, sup, nrb in cases:
            S.add(pset(u, rbstate=0, rbsmt=-1.0, rbflags=sf, flags=beh),
                  m(super=sup, nrb=nrb), "rrb|%d" % u)
            after(u)
        # The speaker: the primary's, the roadblock's, the manager's.
        for prim, rb in (("0x33", 0), ("0x0", 0), ("0x0", -1),
                         ("0xffffffff", -1), ("0xffffffff", 0)):
            S.add(pset(u, rbstate=0, rbflags=0, flags=0, primary=prim,
                       rb=rb), "rrb|%d" % u)
            after(u)

    # ---- MonitorRoadBlock
    u = setup()
    for x, y in ((50.0, 0.0), (55.0, 0.0), (55.0001, 0.0), (56.0, 0.0),
                 (61.9, 0.0), (62.0, 0.0), (70.0, 0.0), (45.0, 0.0),
                 (44.0, 0.0), (56.0, 5.0), (56.0, 11.9), (56.0, -6.0),
                 (NAN, 0.0)):
        for d in (1.0, -1.0, 0.0, NAN, 2.0):
            S.add(c0(x, y), pset(u, dir=d), "mrb|%d" % u)
    for x in (55.0, 56.0, 60.0, 44.0):
        for w in (12.0, 6.0, 0.0, NAN):
            S.add(rb2(0, width=w, dx=0.6, dy=0.8, rpy=-3.0), c0(x, 1.0),
                  "mrb|%d" % u)
    # The roadblock off its route point's line, the road along x: only
    # the along-the-road parts count.
    for x in (5.0, 6.0, 4.0, 15.0, 16.0, -5.0, -6.0):
        for d in (1.0, -1.0):
            S.add(rb2(0, x=0.0, y=10.0, width=20.0, rpx=0.0, rpy=0.0),
                  c0(x, 10.0), pset(u, dir=d), "mrb|%d" % u)
    S.add(pset(u, dir=1.0))
    S.add(rb2(0), c0(56.0, 0.0, blown=1), "mrb|%d" % u, c0(56.0, 0.0),
          "mrb|%d" % u, "rbdump")
    # The cops' cars hit: the e-brake, the zone and the bust.
    for ctrl, mode in ((1, 1), (2, 1), (2, 4), (2, 0), (2, 5), (2, 6),
                       (0, 1), (3, 4), (4, 1)):
        for pair in ((0, 3), (0, 4), (3, 0)):
            S.add(car3(0, ctrl=ctrl), "eb|0|0",
                  car2(0, drv=0, mode=mode), "collide|%d|%d|1" % pair,
                  "mrb|%d" % u, "rbdump", "collide|%d|%d|0" % pair)
    S.add(car3(0), car2(0, drv=0, mode=1), "collide|0|3|1",
          "collide|0|4|1")
    for fwd in (30.0, 17.88109016418457, 17.881092, -30.0, -17.0, NAN,
                INF):
        for zone in (0, 1, -1):
            S.add(c0(56.0, 0.0, fwd), "zone|0|%d" % zone, "mrb|%d" % u)
    S.add("collide|0|3|0", "collide|0|4|0")
    for c_a, c_b in ((-1, 4), (3, -1), (-1, -1)):
        S.add("rb|0|%d|%d|2|0x71" % (c_a, c_b), "collide|0|4|1",
              "collide|0|3|1", c0(56.0, 0.0), "mrb|%d" % u)
    S.add("collide|0|3|0", "collide|0|4|0")
    # A chase of an AI car: no player, no brake.
    u = setup(chased=2)
    S.add(car(2, 2, -1, 56.0, 0.0, 44.0, typ=2), "collide|2|3|1",
          "mrb|%d" % u, "rbdump")

    # ---- RoadBlockDefeated
    def defeat(u, b=1, **kw):
        S.add(pset(u, **kw), "rbd|%d|%d" % (u, b))
        after(u)

    for chased, beacop in ((0, 0), (2, 0), (2, 1), (0, 1)):
        u = setup(chased=chased, beacop=beacop)
        for b in (0, 1):
            defeat(u, b)
        for n in range(-1, 8):
            for heli in (0, 1):
                S.add(rp(bHelicopter=heli))
                defeat(u, rbcount=n, flags=0)
    # Called off near the end of a long race: a player's car only.
    for chased, lapx, beacop in ((0, 3.8, 0), (0, 2.0, 0), (2, 3.8, 1),
                                 (0, 3.8, 1)):
        u = setup(chased=chased, laps=4, beacop=beacop)
        S.add(car2(chased, lapx=lapx, drv=0 if chased < 2 else 2))
        defeat(u)
        S.add("mdump")
    # The replay event: the first cop's car near the dodging car, fast.
    for vm, x3, z3 in ((25.0, 19.9, 0.0), (25.0, 20.0, 0.0),
                       (20.0, 10.0, 0.0), (20.0001, 10.0, 0.0),
                       (NAN, 10.0, 0.0), (25.0, 12.0, 15.9),
                       (25.0, 12.0, 16.0), (25.0, NAN, 0.0),
                       (25.0, -19.0, -5.0)):
        u = setup()
        S.add(car2(0, velmag=vm), car(3, 3, -1, x3, 0.0, 0.0, typ=3),
              car3(3, z=z3))
        defeat(u)
    u = setup()
    S.add(car2(0, velmag=25.0), car(3, 3, -1, 5.0, 0.0, 0.0, typ=3))
    defeat(u, rb=-1)
    S.add("rb|0|-1|3|2|0x71")
    defeat(u, rb=0)
    # The player's own car, not the chased one, is the one measured.
    u = setup()
    S.add(car2(0, velmag=25.0), car2(5, velmag=1.0),
          car(3, 3, -1, 5.0, 0.0, 0.0, typ=3), "pcar|0|5")
    defeat(u)
    S.add("pcar|0|0")
    # Following backwards: a longer wait, two laps or two times in three.
    for beacop, sub, p2p, laps, rnd, n624 in (
            (0, 6, 0, 2, 0, 0), (0, 6, 0, 3, 0, 1), (0, 6, 0, 3, 1, 1),
            (0, 6, 0, 3, 2, 1), (0, 6, 0, 3, -1, 1), (0, 6, 0, 3, 0, 0),
            (0, 6, 1, 2, 0, 1), (0, 6, 1, 2, 5, 1), (0, 6, 1, 1, 0, 0),
            (0, 5, 0, 2, 0, 1), (0, 7, 0, 2, 0, 1), (1, 6, 0, 2, 0, 1),
            (0, 6, 0, 3, 0x7fffffff, 1)):
        u = setup(beacop=beacop, laps=laps, p2p=p2p)
        S.add("g|rand|%d" % rnd, rp(New624=n624))
        defeat(u, sub=sub, rbtimer=3.0, flags=0x8)

    # ---- UpdateRoadBlocks
    def urb(u, n=1):
        for _ in range(n):
            S.add("urb|%d" % u)
            after(u)
        S.add("cdump", "fades", "mdump")

    # No roadblock: the spawn timer, and a call for one with behaviour 8.
    for beacop, rbs, chased, blown, timer, flags in (
            (0, 1, 0, 0, 3.0, 0), (0, 1, 0, 0, 0.2, 0), (0, 1, 0, 0, 0.5, 0),
            (0, 1, 0, 0, NAN, 8), (0, 1, 0, 0, 0.5, 8), (0, 1, 0, 0, 0.6, 8),
            (0, 0, 0, 0, 0.5, 8), (0, 1, 0, 1, 0.5, 8), (0, 1, 2, 0, 0.5, 8),
            (1, 0, 2, 1, 9.0, 8), (1, 1, 0, 0, 9.0, 0), (0, 1, 0, 0, -2.0, 8),
            (0, 1, 0, 0, 0.5, 0xfffffff7)):
        u = setup(chased=chased, beacop=beacop, rb=False)
        S.add(rp(bRoadBlocks=rbs))
        if blown:
            S.add(car(chased, chased, 0 if chased < 2 else -1, 0.0, 0.0,
                      30.0, blown=blown, typ=chased))
        S.add(pset(u, rbtimer=timer, flags=flags))
        urb(u, 2)
    # A spawn timer of -0 stays -0 with no time gone.
    u = setup(rb=False)
    S.add(pset(u, rbtimer=-0.0), dt(0.0))
    urb(u)
    # A blown tyre: the roadblock goes, with the speech for an AI racer in
    # Be A Cop.
    for chased, beacop, drv in ((0, 0, 0), (2, 0, 2), (2, 1, 2), (2, 1, 1),
                                (0, 1, 2)):
        u = setup(chased=chased, beacop=beacop)
        S.add(car(chased, chased, 0 if chased < 2 else -1, 0.0, 0.0, 30.0,
                  blown=2, typ=chased),
              car2(chased, drv=drv), pset(u, dbtimer=5.0, flags=8))
        urb(u)
    # A roadblock cop near the car when it goes: it asks to chase.
    u = setup()
    S.add(car(4, 4, -1, 20.0, 0.0, 61.0, typ=4, drag=2.0, mass=1000.0),
          c0(0.0, 0.0, blown=2), pset(u, dbtimer=5.0))
    urb(u)
    u = setup()
    S.add(car(4, 4, -1, 40.0, 0.0, 61.0, typ=4, drag=2.0, mass=1000.0),
          c0(56.0, 0.0), pset(u, dbtimer=5.0))
    urb(u)
    u = setup()
    S.add(car(4, 4, -1, 10.0, 0.0, 61.0, typ=4, drag=2.0, mass=1000.0),
          car3(0, dat=1101.0), pset(u, dbtimer=0.5))
    urb(u)
    # Got by: defeated, disbanded and the spawn timer started again.
    for flags in (0, 8):
        u = setup()
        S.add(c0(56.0, 0.0), pset(u, dbtimer=5.0, flags=flags))
        urb(u, 2)
    # Got by in Be A Cop, behaviour 8: asked for again at once.
    u = setup(beacop=1)
    S.add(c0(56.0, 0.0), pset(u, dbtimer=5.0, flags=8), m(nrb=2))
    urb(u, 2)
    # The disband timer, and the car far past the roadblock.
    for d, dat, dbt in ((1.0, 1100.0, 0.5), (1.0, 1101.0, 0.5),
                        (1.0, 2100.0, 0.5), (1.0, 2099.99, 0.5),
                        (1.0, 1101.0, 0.50001), (1.0, 1101.0, 0.0),
                        (1.0, 1101.0, -3.0), (1.0, 1101.0, NAN),
                        (-1.0, 900.0, 0.5), (-1.0, 899.0, 0.5),
                        (-1.0, 4000.0, 0.5), (NAN, 899.0, 0.5),
                        (0.0, 1101.0, 0.5), (1.0, NAN, 0.5),
                        (1.0, 6200.0, 0.5), (2.0, 1101.0, 0.5),
                        (2.0, 899.0, 0.5)):
        u = setup()
        S.add(car3(0, dat=dat), pset(u, dir=d, dbtimer=dbt, flags=8))
        urb(u, 2)


# ================================================================== build

def build_harness(tmp, name="pursuit_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

P = PURSUIT
B = BARRICADE
C = COPMGR
MUTATIONS = [
    # ---- the small records
    ("hist_count", P,
     "    h->nCount = 0;\n    return h;",
     "    h->nCount = 1;\n    return h;"),
    ("hist_time", P,
     "        h->fTime[i] = 0.0f;\n",
     "        h->fTime[i] = 1.0f;\n"),
    ("hist_29", P,
     "    for (i = 0; i < 30; i++) {\n        h->v2Velocity",
     "    for (i = 0; i < 29; i++) {\n        h->v2Velocity"),
    ("hist_dtor_free", P,
     "    h->vptr = TPURSUITHISTORY_VTABLE;\n    if (flags & 1)",
     "    h->vptr = TPURSUITHISTORY_VTABLE;\n    if (flags & 2)"),
    ("rbsm_pursuit", P,
     "    s->pPursuit = p;\n",
     "    s->pPursuit = NULL;\n"),
    ("rbsm_state", P,
     "    s->State = ERBS_NONE;\n    s->SpeechFlags = 0;",
     "    s->State = (eRoadBlockState)1;\n    s->SpeechFlags = 0;"),
    ("rbsm_flags", P,
     "    s->SpeechFlags = 0;\n",
     "    s->SpeechFlags = 1;\n"),
    ("rbsm_count", P,
     "    s->nRoadBlockCount = 0;\n    return s;",
     "    s->nRoadBlockCount = 1;\n    return s;"),
    ("rbsm_dtor_free", P,
     "{\n    if (flags & 1)\n        bFree(s);",
     "{\n    if (flags & 2)\n        bFree(s);"),
    ("rbsm_disband_state", P,
     "{\n    s->State = ERBS_NONE;\n}",
     "{\n    s->State = (eRoadBlockState)1;\n}"),

    # ---- GetTopSpeed
    ("top_start", P,
     "    float              v = 27.77777862548828f;",
     "    float              v = 27.0f;"),
    ("top_limit", P,
     "    while (v < 111.11111450195312f) {",
     "    while (v < 110.0f) {"),
    ("top_drag_once", P,
     "        if (a < v * v * ti->Aero.Drag / ti->Body.Mass)",
     "        if (a < v * ti->Aero.Drag / ti->Body.Mass)"),
    ("top_mass_times", P,
     "        if (a < v * v * ti->Aero.Drag / ti->Body.Mass)",
     "        if (a < v * v * ti->Aero.Drag * ti->Body.Mass)"),
    ("top_le", P,
     "        if (a < v * v * ti->Aero.Drag / ti->Body.Mass)",
     "        if (a <= v * v * ti->Aero.Drag / ti->Body.Mass)"),
    ("top_step", P,
     "        v = v + 1.388888955116272f;",
     "        v = v + 1.5f;"),
    ("top_no_less_step", P,
     "    return v - 1.388888955116272f;",
     "    return v;"),

    # ---- the constructor
    ("reserve_empty_0", P,
     "        return 0x41a00000u;",
     "        return 0;"),
    ("reserve_full_ignored", P,
     "    if (d->Full == 0 && d->Tail == d->Head)",
     "    if (d->Tail == d->Head)"),
    ("ctor_id", P,
     "    p->nPursuitId = id;",
     "    p->nPursuitId = (int8_t)(id + 1);"),
    ("ctor_ncops", P,
     "    p->nNumCops = 0;\n    p->nHUDPursuitLevel = 0;",
     "    p->nNumCops = 1;\n    p->nHUDPursuitLevel = 0;"),
    ("ctor_rbcount", P,
     "    p->nRoadblockCount = 0;",
     "    p->nRoadblockCount = 1;"),
    ("ctor_catch", P,
     "    p->nRoadblockCount = 0;\n    p->fCatchCarTimer = 2.0f;",
     "    p->nRoadblockCount = 0;\n    p->fCatchCarTimer = 2.5f;"),
    ("ctor_disband", P,
     "    p->fRoadBlockDisbandTimer = 3.5f;",
     "    p->fRoadBlockDisbandTimer = 3.0f;"),
    ("ctor_spawn_easy", P,
     "fRoadBlockSpawnTimes[pCopManager->nDifficultyLevel];",
     "fRoadBlockSpawnTimes[0];"),
    ("ctor_spawn_table", P,
     "{ 20.0f, 15.0f, 10.0f }",
     "{ 20.0f, 15.0f, 12.0f }"),
    ("ctor_spawntimer", P,
     "    p->fRoadBlockSpawnTimer = 0.0f;\n    p->fChopperAttackTimer",
     "    p->fRoadBlockSpawnTimer = 1.0f;\n    p->fChopperAttackTimer"),
    ("ctor_chopper_attack", P,
     "    p->fChopperAttackTimer = 10.0f;",
     "    p->fChopperAttackTimer = 12.0f;"),
    ("ctor_chopper_next", P,
     "    p->fChopperNextAttackTime = 12.0f;",
     "    p->fChopperNextAttackTime = 10.0f;"),
    ("ctor_secondary", P,
     "    p->SecondaryCopSpeaker = COP_SPEAKER_NONE;\n    p->Cops[1] = NULL;",
     "    p->SecondaryCopSpeaker = 1;\n    p->Cops[1] = NULL;"),
    ("ctor_cops1", P,
     "    p->Cops[1] = NULL;\n    p->Cops[0] = NULL;",
     "    p->Cops[0] = NULL;"),
    ("ctor_cops0", P,
     "    p->Cops[1] = NULL;\n    p->Cops[0] = NULL;",
     "    p->Cops[1] = NULL;"),
    ("ctor_landmark", P,
     "    p->CurrentLandmark = 0;",
     "    p->CurrentLandmark = 1;"),
    ("ctor_joined", P,
     "    p->bAlreadyJoined = 0;",
     "    p->bAlreadyJoined = 1;"),
    ("ctor_hit", P,
     "    p->bAlreadyBeenHit = 0;",
     "    p->bAlreadyBeenHit = 1;"),
    ("ctor_backup", P,
     "    p->bAlreadyCalledForBackup = 0;\n    p->pRoadBlock",
     "    p->bAlreadyCalledForBackup = 1;\n    p->pRoadBlock"),
    ("ctor_rb", P,
     "    p->pRoadBlock = NULL;\n    p->BehaviourFlags = 0;",
     "    p->BehaviourFlags = 0;"),
    ("ctor_flags", P,
     "    p->BehaviourFlags = 0;\n    p->pChopper",
     "    p->BehaviourFlags = 0x100;\n    p->pChopper"),
    ("ctor_chopper", P,
     "    p->pChopper = NULL;\n    p->ChopperState = ECS_NO_CHOPPER;\n    // With",
     "    p->ChopperState = ECS_NO_CHOPPER;\n    // With"),
    ("ctor_chst", P,
     "    p->ChopperState = ECS_NO_CHOPPER;\n    // With",
     "    p->ChopperState = (eChopperState)1;\n    // With"),
    ("ctor_no_topspeed", P,
     "        p->fChasedCarTopSpeed = get_top_speed(p->pChasedCar);",
     "        p->fChasedCarTopSpeed = 0.0f;"),
    ("ctor_beacop_ignored", P,
     "        if (TheRaceParameters.BeACop != 0)\n"
     "            p->PrimaryCopSpeaker = pCopManager->BeACopId;",
     "        if (0)\n"
     "            p->PrimaryCopSpeaker = pCopManager->BeACopId;"),
    ("ctor_ai_reserves", P,
     "        else if (p->pChasedCar->pPlayer != NULL)\n"
     "            p->PrimaryCopSpeaker = reserve_speaker_in_ctor();",
     "        else\n"
     "            p->PrimaryCopSpeaker = reserve_speaker_in_ctor();"),
    ("ctor_demo_level2", P,
     "        tpursuit_switch_state(p, EPS_LEVEL3);\n    else",
     "        tpursuit_switch_state(p, EPS_LEVEL2);\n    else"),
    ("ctor_level1", P,
     "    else\n        tpursuit_switch_state(p, EPS_LEVEL0);",
     "    else\n        tpursuit_switch_state(p, EPS_LEVEL1);"),
    ("ctor_chasedir_timer", P,
     "    p->fChaseDirectionTimer = 0.0f;\n    p->fChaseDirection = 1.0f;",
     "    p->fChaseDirectionTimer = 1.0f;\n    p->fChaseDirection = 1.0f;"),
    ("ctor_chasedir", P,
     "    p->fChaseDirection = 1.0f;",
     "    p->fChaseDirection = -1.0f;"),
    ("ctor_new1556", P,
     "    p->New1556 = 10.0f;",
     "    p->New1556 = 12.0f;"),
    ("ctor_bmalloc_align", P,
     "                                    0, 16));",
     "                                    0, 0));"),

    # ---- the destructor
    ("dtor_no_release", P,
     "    p->vptr = TPURSUIT_VTABLE;\n    tpursuit_release_all_cops(p);",
     "    p->vptr = TPURSUIT_VTABLE;"),
    ("dtor_ai_releases", P,
     "    if (p->pChasedCar->pPlayer != NULL) {\n"
     "        copmanager_release_cop_speaker(pCopManager, p->PrimaryCopSpeaker);",
     "    if (1) {\n"
     "        copmanager_release_cop_speaker(pCopManager, p->PrimaryCopSpeaker);"),
    ("dtor_secondary_always", P,
     "        if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE)\n"
     "            copmanager_release_cop_speaker(pCopManager,\n",
     "        if (1)\n"
     "            copmanager_release_cop_speaker(pCopManager,\n"),
    ("dtor_id", P,
     "    p->nPursuitId = -2;",
     "    p->nPursuitId = -1;"),
    ("dtor_bar_keep", P,
     "        ((DtorFn)e->fn)(vt_this(b, e), 3);",
     "        ((DtorFn)e->fn)(vt_this(b, e), 2);"),
    ("dtor_rbsm_flags", P,
     "    trbsm_destruct(&p->RoadBlockStateMachine, 2);",
     "    trbsm_destruct(&p->RoadBlockStateMachine, 3);"),
    ("dtor_hist_flags", P,
     "    tpursuithistory_destruct(&p->History, 2);",
     "    tpursuithistory_destruct(&p->History, 3);"),
    ("dtor_dt_order", P,
     "    drivetarget_destroy(&p->NearDriveTarget);\n"
     "    drivetarget_destroy(&p->FarDriveTarget);",
     "    drivetarget_destroy(&p->FarDriveTarget);\n"
     "    drivetarget_destroy(&p->NearDriveTarget);"),
    ("dtor_no_free", P,
     "    if (flags & 1)\n        bSlotFree(PursuitSlotPool, p);",
     "    if (flags & 2)\n        bSlotFree(PursuitSlotPool, p);"),

    # ---- the states
    ("state_p2p", P,
     "    if (TheRaceParameters.Point2Point == 0)",
     "    if (TheRaceParameters.Point2Point != 0)"),
    ("state_laps", P,
     "    float laps = 1.0f;",
     "    float laps = 2.0f;"),
    ("state_hi", P,
     "    if (42000.0f < len)\n        len = 42000.0f;",
     "    if (40000.0f < len)\n        len = 40000.0f;"),
    ("state_lo", P,
     "    if (len < 14000.0f)\n        len = 14000.0f;",
     "    if (len < 15000.0f)\n        len = 15000.0f;"),
    ("state_quarter", P,
     "len * 1.7857142665889114e-05f + 0.25f",
     "len * 1.7857142665889114e-05f + 0.5f"),
    ("state_scale", P,
     "len * 1.7857142665889114e-05f + 0.25f",
     "len * 1.8e-05f + 0.25f"),
    ("table_level0", P,
     "    30.0f, 20.0f, 40.0f, 300.0f, 10.0f, 100000.0f",
     "    20.0f, 20.0f, 40.0f, 300.0f, 10.0f, 100000.0f"),
    ("table_level3", P,
     "    30.0f, 20.0f, 40.0f, 300.0f, 10.0f, 100000.0f",
     "    30.0f, 20.0f, 40.0f, 200.0f, 10.0f, 100000.0f"),
    ("table_giveup", P,
     "    30.0f, 20.0f, 40.0f, 300.0f, 10.0f, 100000.0f",
     "    30.0f, 20.0f, 40.0f, 300.0f, 10.0f, 10000.0f"),
    ("sw_l0_hud", P,
     "        p->nHUDPursuitLevel = 1;\n        p->PursuitSubState = LSS_NONE;",
     "        p->nHUDPursuitLevel = 2;\n        p->PursuitSubState = LSS_NONE;"),
    ("sw_l0_sub", P,
     "        p->PursuitSubState = LSS_NONE;\n",
     "        p->PursuitSubState = LSS_PURSUIT_FOLLOW;\n"),
    ("sw_l0_flags", P,
     "        p->BehaviourFlags |= 0x2u;",
     "        p->BehaviourFlags |= 0x3u;"),
    ("sw_l1_flags", P,
     "        p->BehaviourFlags |= 0x3u;",
     "        p->BehaviourFlags |= 0x1u;"),
    ("sw_l1_sub", P,
     "        p->PursuitSubState = LSS_PURSUIT_FOLLOW;",
     "        p->PursuitSubState = LSS_FOLLOW_OFFSET;"),
    ("sw_l1_backup", P,
     "        p->PursuitSubState = LSS_PURSUIT_FOLLOW;\n"
     "        p->bAlreadyCalledForBackup = 1;\n",
     "        p->PursuitSubState = LSS_PURSUIT_FOLLOW;\n"),
    ("sw_l1_hud", P,
     "        p->nHUDPursuitLevel = 2;",
     "        p->nHUDPursuitLevel = 3;"),
    ("sw_l2_flags", P,
     "        p->BehaviourFlags |= 0x7u;",
     "        p->BehaviourFlags |= 0x6u;"),
    ("sw_l2_backup", P,
     "        p->BehaviourFlags |= 0x7u;\n        p->bAlreadyCalledForBackup = 1;",
     "        p->BehaviourFlags |= 0x7u;"),
    ("sw_l2_hud", P,
     "        p->nHUDPursuitLevel = 3;",
     "        p->nHUDPursuitLevel = 2;"),
    ("sw_l2_sub", P,
     "        p->PursuitSubState = LSS_FOLLOW_OFFSET;\n",
     "        p->PursuitSubState = LSS_FOLLOW_BACKWARDS;\n"),
    ("sw_l2_nosuper", P,
     "        p->PursuitSubState = LSS_FOLLOW_OFFSET;\n"
     "        copmanager_possible_call_supervisor(pCopManager, p);\n",
     "        p->PursuitSubState = LSS_FOLLOW_OFFSET;\n"),
    ("sw_l3_flags", P,
     "        p->BehaviourFlags |= 0x20fu;",
     "        p->BehaviourFlags |= 0x00fu;"),
    ("sw_l3_backup", P,
     "        p->BehaviourFlags |= 0x20fu;\n        p->bAlreadyCalledForBackup = 1;",
     "        p->BehaviourFlags |= 0x20fu;"),
    ("sw_l3_hud", P,
     "        p->nHUDPursuitLevel = 4;",
     "        p->nHUDPursuitLevel = 3;"),
    ("sw_l3_sub", P,
     "        p->PursuitSubState = LSS_FOLLOW_BACKWARDS;\n",
     "        p->PursuitSubState = LSS_FOLLOW_OFFSET;\n"),
    ("sw_l3_nosuper", P,
     "        p->PursuitSubState = LSS_FOLLOW_BACKWARDS;\n"
     "        copmanager_possible_call_supervisor(pCopManager, p);\n",
     "        p->PursuitSubState = LSS_FOLLOW_BACKWARDS;\n"),
    ("sw_caught_hud", P,
     "    case EPS_SPEEDER_CAUGHT:\n        p->nHUDPursuitLevel = 0;",
     "    case EPS_SPEEDER_CAUGHT:\n        p->nHUDPursuitLevel = 1;"),
    ("sw_giveup_hud", P,
     "    case EPS_END_PURSUIT_GIVE_UP:\n        p->nHUDPursuitLevel = 0;",
     "    case EPS_END_PURSUIT_GIVE_UP:\n        p->nHUDPursuitLevel = 1;"),
    ("sw_giveup_no_speech", P,
     "            if (gPursuitBackOffSpeechFn != NULL)\n",
     "            if (0)\n"),
    ("sw_giveup_no_score", P,
     "            player_start_score(pl, SCORING_BEAT_THE_COPS);\n",
     ""),
    ("sw_giveup_score", P,
     "            player_start_score(pl, SCORING_BEAT_THE_COPS);\n",
     "            player_start_score(pl, SCORING_BEAT_THE_COPS + 1);\n"),
    ("sw_giveup_pursuable", P,
     "        pCopManager->fPursuableTimer[car->CarIndex] = 999999.0f;",
     "        pCopManager->fPursuableTimer[car->CarIndex] = 99999.0f;"),
    ("sw_giveup_trap", P,
     "        pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] = 999999.0f;\n"
     "        tpursuit_release_all_cops(p);",
     "        pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] = 99999.0f;\n"
     "        tpursuit_release_all_cops(p);"),
    ("sw_giveup_norelease", P,
     "        pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] = 999999.0f;\n"
     "        tpursuit_release_all_cops(p);\n",
     "        pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] = 999999.0f;\n"),

    # ---- DoStateTransition
    ("trans_l0", P,
     "        to = EPS_LEVEL1;",
     "        to = EPS_LEVEL2;"),
    ("trans_l1", P,
     "        to = EPS_LEVEL2;\n        break;",
     "        to = EPS_LEVEL3;\n        break;"),
    ("trans_resets_same", P,
     "    if (to != s && !over)",
     "    if (!over)"),
    ("trans_caught", P,
     "        to = EPS_SPEEDER_CAUGHT;",
     "        to = EPS_LEVEL3;"),
    ("trans_over", P,
     "    case EPS_END_PURSUIT_GIVE_UP:\n        over = 1;",
     "    case EPS_END_PURSUIT_GIVE_UP:\n        over = 0;"),

    # ---- GetSpeedMPHOrKPH
    ("speed_kph", P,
     "        return v * 3.5999999046325684f;",
     "        return v * 3.5f;"),
    ("speed_mph", P,
     "    return v * 2.236999988555908f;",
     "    return v * 2.2f;"),
    ("speed_ai_units", P,
     "    if (car->pPlayer != NULL\n",
     "    if (1\n"),
    ("speed_units", P,
     "        && TheRaceParameters.GlobalDisplaySettings.Units != 0)",
     "        && TheRaceParameters.GlobalDisplaySettings.Units == 0)"),

    # ---- ReleaseAllCops and the chopper
    ("chopper_960", P,
     "    if (gChopperNew960Fn(p->pChopper) != 0)",
     "    if (gChopperNew960Fn(p->pChopper) == 0)"),
    ("chopper_busy", P,
     "    pCopManager->bChopperBusy = 0;",
     "    pCopManager->bChopperBusy = 1;"),
    ("chopper_follow", P,
     "    gChopperFollowThisCarFn(p->pChopper, NULL);",
     "    gChopperFollowThisCarFn(p->pChopper, p->pChasedCar);"),
    ("chopper_state", P,
     "    p->ChopperState = ECS_NO_CHOPPER;\n    p->pChopper = NULL;\n}",
     "    p->pChopper = NULL;\n}"),
    ("chopper_ptr", P,
     "    p->ChopperState = ECS_NO_CHOPPER;\n    p->pChopper = NULL;\n}",
     "    p->ChopperState = ECS_NO_CHOPPER;\n}"),
    ("release_both", P,
     "    for (i = 0; i < p->nNumCops; i++) {\n        tCop          *c",
     "    for (i = p->nNumCops - 1; i >= 0; i--) {\n        tCop          *c"),
    ("release_ai_test", P,
     "        if (((IsAIControlledFn)e->fn)(vt_this(c, e)) != 0)",
     "        if (((IsAIControlledFn)e->fn)(vt_this(c, e)) == 0)"),
    ("release_no_remove", P,
     "        tpursuit_remove_cop_from_pursuit(p, c);\n        e = vt_slot",
     "        e = vt_slot"),
    ("release_no_disband", P,
     "    tpursuit_disband_road_block(p, 0);\n    release_chopper(p);",
     "    release_chopper(p);"),
    ("release_disband_b", P,
     "    tpursuit_disband_road_block(p, 0);",
     "    tpursuit_disband_road_block(p, 1);"),
    ("release_no_chopper", P,
     "    tpursuit_disband_road_block(p, 0);\n    release_chopper(p);",
     "    tpursuit_disband_road_block(p, 0);"),

    # ---- DisbandRoadBlock
    ("disband_one", P,
     "    for (i = 0; i < 2; i++) {\n        tCop *c = (tCop *)",
     "    for (i = 0; i < 1; i++) {\n        tCop *c = (tCop *)"),
    ("disband_no_remove", P,
     "        tpursuit_remove_cop_from_pursuit(p, c);\n"
     "        taicop_return_to_patrol((tAICop *)(void *)c);\n        if (b) {",
     "        taicop_return_to_patrol((tAICop *)(void *)c);\n        if (b) {"),
    ("disband_no_patrol", P,
     "        taicop_return_to_patrol((tAICop *)(void *)c);\n        if (b) {",
     "        if (b) {"),
    ("disband_b", P,
     "        if (b) {\n            Car  *ch",
     "        if (!b) {\n            Car  *ch"),
    ("disband_dist", P,
     "            if (sqrtf(dx * dx + dy * dy) < 30.0f",
     "            if (sqrtf(dx * dx + dy * dy) < 25.0f"),
    ("disband_dy", P,
     "            float dy = ch->State.Position.y - mine->State.Position.y;",
     "            float dy = ch->State.Position.x - mine->State.Position.y;"),
    ("disband_ignore_request", P,
     "                && copmanager_request_pursuit(pCopManager, c, ch) != 0)",
     "                && (copmanager_request_pursuit(pCopManager, c, ch), 1))"),
    ("disband_no_hot", P,
     "                tcop_set_desired_logic_state(c, LS_HOT_PURSUIT);",
     "                ;"),
    ("disband_pi", P,
     "    if (tpursuit_is_player_involved(p)) {",
     "    if (1) {"),
    ("disband_ai_secondary", P,
     "        if (p->pChasedCar->pPlayer != NULL\n"
     "            && p->SecondaryCopSpeaker == COP_SPEAKER_NONE",
     "        if (1\n"
     "            && p->SecondaryCopSpeaker == COP_SPEAKER_NONE"),
    ("disband_secondary_set", P,
     "            && p->SecondaryCopSpeaker == COP_SPEAKER_NONE\n",
     "            && p->SecondaryCopSpeaker != COP_SPEAKER_NONE\n"),
    ("disband_split", P,
     "            && TheRaceParameters.NumPlayerCars == 1)",
     "            && TheRaceParameters.NumPlayerCars >= 1)"),
    ("disband_spk", P,
     "            p->SecondaryCopSpeaker = p->pRoadBlock->CopSpeaker;",
     "            p->SecondaryCopSpeaker = 7;"),
    ("disband_strip_id", P,
     "        pCopManager, p->pRoadBlock->nIndexIntoLoadedData);",
     "        pCopManager, p->pRoadBlock->nIndexIntoLoadedData + 1);"),
    ("disband_fade_t", P,
     "    barricademanager_fade(p->pBarricades, 2.0f);",
     "    barricademanager_fade(p->pBarricades, 3.0f);"),
    ("disband_rb_kept", P,
     "    p->pRoadBlock = NULL;\n    trbsm_disband_road_block",
     "    trbsm_disband_road_block"),
    ("disband_no_rbsm", P,
     "    trbsm_disband_road_block(&p->RoadBlockStateMachine);\n}",
     "}"),

    # ---- RemoveCopFromPursuit and IsCopInPursuit
    ("remove_no_null", P,
     "    if (c == NULL)\n        return 0;\n    for (i = 0; i < p->nNumCops",
     "    for (i = 0; i < p->nNumCops"),
    ("remove_no_dec", P,
     "        p->nNumCops--;\n",
     ""),
    ("remove_no_shift", P,
     "        if (p->Cops[0] == NULL) {\n            p->Cops[0] = p->Cops[1];",
     "        if (0) {\n            p->Cops[0] = p->Cops[1];"),
    ("remove_shift_keep", P,
     "            p->Cops[1] = NULL;\n        }\n        found = 1;",
     "        }\n        found = 1;"),
    ("remove_rb_too", P,
     "    if (!found && p->pRoadBlock != NULL) {",
     "    if (p->pRoadBlock != NULL) {"),
    ("remove_rb_one", P,
     "        for (i = 0; i < 2 && !found; i++) {",
     "        for (i = 0; i < 1 && !found; i++) {"),
    ("remove_rb_both", P,
     "        for (i = 0; i < 2 && !found; i++) {",
     "        for (i = 0; i < 2; i++) {"),
    ("remove_rb_clear", P,
     "                rb->cops[i] = NULL;\n",
     ""),
    ("remove_no_setp", P,
     "    if (found)\n        tcop_set_pursuit(c, NULL);",
     "    if (0)\n        tcop_set_pursuit(c, NULL);"),
    ("remove_ret", P,
     "    return found;\n}\n\nint32_t tpursuit_is_cop_in_pursuit",
     "    return 1;\n}\n\nint32_t tpursuit_is_cop_in_pursuit"),
    ("isin_two", P,
     "    for (i = 0; i < p->nNumCops; i++)\n        if (p->Cops[i] == c)",
     "    for (i = 0; i < 2; i++)\n        if (p->Cops[i] == c)"),
    ("isin_rb0", P,
     "            if ((const tCop *)(const void *)p->pRoadBlock->cops[i] == c)",
     "            if ((const tCop *)(const void *)p->pRoadBlock->cops[0] == c)"),
    ("isin_no_rb", P,
     "    if (p->pRoadBlock != NULL)\n        for (i = 0; i < 2; i++)",
     "    if (0)\n        for (i = 0; i < 2; i++)"),

    # ---- RemovePrimarySpeaker
    ("rps_ai", P,
     "    if (p->pChasedCar->pPlayer == NULL)\n        return;\n"
     "    if (tpursuit_road_block",
     "    if (tpursuit_road_block"),
    ("rps_recent", P,
     "    if (tpursuit_road_block_encountered_recently(p))\n        return;",
     "    if (0)\n        return;"),
    ("rps_no_release", P,
     "    copmanager_release_cop_speaker(pCopManager, was);\n",
     ""),
    ("rps_secondary_kept", P,
     "        p->PrimaryCopSpeaker = p->SecondaryCopSpeaker;\n"
     "        p->SecondaryCopSpeaker = COP_SPEAKER_NONE;",
     "        p->PrimaryCopSpeaker = p->SecondaryCopSpeaker;"),
    ("rps_lt1", P,
     "    } else if (p->nNumCops < 2) {",
     "    } else if (p->nNumCops < 1) {"),
    ("rps_current", P,
     "        p->PrimaryCopSpeaker = copmanager_reserve_cop_speaker(pCopManager);\n"
     "    }\n    if (b) {",
     "        p->PrimaryCopSpeaker = copmanager_get_current_cop_speaker(pCopManager);\n"
     "    }\n    if (b) {"),
    ("rps_b", P,
     "    if (b) {\n        if ((uint32_t)bRandomI",
     "    if (!b) {\n        if ((uint32_t)bRandomI"),
    ("rps_tow_odds", P,
     "bRandomI(10, &bDefaultSeed) < 2u",
     "bRandomI(10, &bDefaultSeed) < 3u"),
    ("rps_tow_range", P,
     "bRandomI(10, &bDefaultSeed) < 2u",
     "bRandomI(5, &bDefaultSeed) < 2u"),
    ("rps_tow_args", P,
     "                gSpeechRaiseCrashTowFn(was, p->PrimaryCopSpeaker);",
     "                gSpeechRaiseCrashTowFn(p->PrimaryCopSpeaker, was);"),
    ("rps_crash_args", P,
     "            gSpeechRaiseCrashFn(was, p->PrimaryCopSpeaker);",
     "            gSpeechRaiseCrashFn(was, was);"),
    ("rps_flat_args", P,
     "        gSpeechRaiseFlatTireFn(was, p->PrimaryCopSpeaker);",
     "        gSpeechRaiseFlatTireFn(p->PrimaryCopSpeaker, was);"),

    # ---- RoadBlockEncounteredRecently and SelectPrimaryCop
    ("rbr_blown_bit0", P,
     "    if ((int8_t)p->pChasedCar->BlownTireBits != 0)",
     "    if ((p->pChasedCar->BlownTireBits & 1) != 0)"),
    ("rbr_double", P,
     "        t = t + t;",
     "        t = t + 4.0f;"),
    ("rbr_chopper_state", P,
     "    if (p->ChopperState == ECS_CHOPPER_REQUESTED)",
     "    if (p->ChopperState != ECS_CHOPPER_REQUESTED)"),
    ("rbr_four", P,
     "    return t - 4.0f < p->fRoadBlockSpawnTimer;",
     "    return t - 3.0f < p->fRoadBlockSpawnTimer;"),
    ("rbr_le", P,
     "    return t - 4.0f < p->fRoadBlockSpawnTimer;",
     "    return t - 4.0f <= p->fRoadBlockSpawnTimer;"),
    ("rbr_global", P,
     "    t = fRoadBlockSpawnTime;\n",
     "    t = 20.0f;\n"),
    ("sel_null_a", P,
     "    if (a == NULL || b == NULL)\n        return;",
     "    if (b == NULL)\n        return;"),
    ("sel_null_b", P,
     "    if (a == NULL || b == NULL)\n        return;",
     "    if (a == NULL)\n        return;"),
    ("sel_30", P,
     "    if (30.0f < da - db) {",
     "    if (20.0f < da - db) {"),
    ("sel_le", P,
     "    if (30.0f < da - db) {",
     "    if (30.0f <= da - db) {"),
    ("sel_dir", P,
     "    if (30.0f < da - db) {",
     "    if (30.0f < db - da) {"),
    ("sel_by", P,
     "    dy = car->State.Position.y - cb->State.Position.y;",
     "    dy = car->State.Position.y - cb->State.Position.x;"),
    ("sel_ax", P,
     "    dx = car->State.Position.x - ca->State.Position.x;",
     "    dx = car->State.Position.x - ca->State.Position.y;"),
    ("sel_swap_half", P,
     "        p->Cops[1] = a;\n        p->Cops[0] = b;",
     "        p->Cops[0] = b;"),

    # ---- the speakers
    ("spk_primary", P,
     "    if (p->PrimaryCopSpeaker != COP_SPEAKER_NONE)\n",
     "    if (0)\n"),
    ("spk_rb", P,
     "    if (p->pRoadBlock != NULL)\n        return p->pRoadBlock->CopSpeaker;",
     "    if (0)\n        return p->pRoadBlock->CopSpeaker;"),
    ("spk_current", P,
     "        return p->pRoadBlock->CopSpeaker;\n"
     "    return copmanager_get_current_cop_speaker(pCopManager);",
     "        return p->pRoadBlock->CopSpeaker;\n    return 0;"),
    ("spk2_secondary", P,
     "    if (p->SecondaryCopSpeaker != COP_SPEAKER_NONE)\n"
     "        return p->SecondaryCopSpeaker;",
     "    if (0)\n        return p->SecondaryCopSpeaker;"),
    ("spk2_current", P,
     "        return p->SecondaryCopSpeaker;\n"
     "    return copmanager_get_current_cop_speaker(pCopManager);",
     "        return p->SecondaryCopSpeaker;\n    return 0;"),
    ("pi_no_beacop", P,
     "    return p->pChasedCar->pPlayer != NULL || TheRaceParameters.BeACop != 0;",
     "    return p->pChasedCar->pPlayer != NULL;"),
    ("pi_no_player", P,
     "    return p->pChasedCar->pPlayer != NULL || TheRaceParameters.BeACop != 0;",
     "    return TheRaceParameters.BeACop != 0;"),

    # ---- the one-liners
    ("ol_addcop_slot", P,
     "    p->Cops[p->nNumCops] = c;\n    p->nNumCops++;\n}\n",
     "    p->Cops[0] = c;\n    p->nNumCops++;\n}\n"),
    ("ol_addcop_noinc", P,
     "    p->Cops[p->nNumCops] = c;\n    p->nNumCops++;\n}\n",
     "    p->Cops[p->nNumCops] = c;\n}\n"),
    ("ol_numcops", P,
     "    return p->nNumCops;\n}",
     "    return p->nMaxChaseCops;\n}"),
    ("ol_id", P,
     "    return p->nPursuitId;",
     "    return p->nPursuitId + 1;"),
    ("ol_rbstate", P,
     "    return p->RoadBlockStateMachine.State;",
     "    return (eRoadBlockState)0;"),
    ("ol_dir", P,
     "    return p->fChaseDirection;",
     "    return p->fChaseDirectionTimer;"),
    ("ol_chst", P,
     "    return p->ChopperState;",
     "    return ECS_NO_CHOPPER;"),
    ("ol_over", P,
     "    return p->PursuitState == EPS_END_PURSUIT_GIVE_UP;",
     "    return p->PursuitState == EPS_SPEEDER_CAUGHT;"),
    ("ol_called", P,
     "    return p->bAlreadyCalledForBackup;\n}",
     "    return p->bAlreadyJoined;\n}"),
    ("ol_needed_zero", P,
     "    if (p->nNumCops == 0)\n        return 1;",
     "    if (p->nNumCops == 0)\n        return 0;"),
    ("ol_needed_le", P,
     "    return p->nNumCops < p->nMaxChaseCops && p->bAlreadyCalledForBackup",
     "    return p->nNumCops <= p->nMaxChaseCops && p->bAlreadyCalledForBackup"),
    ("ol_needed_nobackup", P,
     "    return p->nNumCops < p->nMaxChaseCops && p->bAlreadyCalledForBackup != 0;",
     "    return p->nNumCops < p->nMaxChaseCops;"),
    ("ol_other", P,
     "    return p->Cops[0] == c ? p->Cops[1] : p->Cops[0];",
     "    return p->Cops[1] == c ? p->Cops[0] : p->Cops[1];"),
    ("ol_primcar", P,
     "    return p->Cops[0] != NULL && p->Cops[0]->pMyCar == car;",
     "    return p->Cops[0] != NULL && p->Cops[0]->pMyCar != car;"),
    ("ol_primcar_null", P,
     "    return p->Cops[0] != NULL && p->Cops[0]->pMyCar == car;",
     "    return p->Cops[0] == NULL || p->Cops[0]->pMyCar == car;"),
    ("ol_prim", P,
     "    return p->Cops[0] == c;",
     "    return p->Cops[1] == c;"),
    ("ol_allowed", P,
     "    return (int32_t)(p->BehaviourFlags & a);",
     "    return (p->BehaviourFlags & a) != 0;"),
    ("ol_disallowall", P,
     "    p->BehaviourFlags = 0;\n}",
     "    p->BehaviourFlags = 1;\n}"),
    ("ol_disallow", P,
     "    p->BehaviourFlags &= ~a;",
     "    p->BehaviourFlags ^= a;"),
    ("ol_allow", P,
     "    p->BehaviourFlags |= a;",
     "    p->BehaviourFlags ^= a;"),
    ("ol_landmark", P,
     "    return p->CurrentLandmark;",
     "    return p->CurrentLandmark + 1;"),
    ("ol_hud", P,
     "    return p->nHUDPursuitLevel;",
     "    return p->nHUDPursuitLevel + 1;"),

    # ---- NewPursuit
    ("new_id_pos", P,
     "    if ((int8_t)id >= 0)\n",
     "    if ((int8_t)id > 0)\n"),
    ("new_byid0", P,
     "        m->PursuitsById[(int8_t)id] = p;",
     "        m->PursuitsById[0] = p;"),
    ("new_id_arg", P,
     "    tpursuit_construct(p, (int8_t)id, car);",
     "    tpursuit_construct(p, (int8_t)(id + 1), car);"),
    ("new_prev", P,
     "    p->Node.Prev = tail;",
     "    p->Node.Prev = list;"),
    ("new_next", P,
     "    p->Node.Next = list;",
     "    p->Node.Next = tail;"),
    ("new_no_listprev", P,
     "    list->Prev = &p->Node;\n",
     ""),
    ("new_no_tailnext", P,
     "    tail->Next = &p->Node;\n",
     ""),

    # ---- RequestPursuit
    ("req_finished_pos", P,
     "    if (car->pRacingCar->FinishReason != 0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0) {",
     "    if (car->pRacingCar->FinishReason > 0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0) {"),
    ("req_finished_byte", P,
     "    if (car->pRacingCar->FinishReason != 0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0) {",
     "    if ((int8_t)car->pRacingCar->FinishReason != 0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0) {"),
    ("req_beacop_any", P,
     "        if (c == copmanager_get_player_cop(m)) {",
     "        if (1) {"),
    ("req_beacop_chase", P,
     "            maxChase = 1;\n            maxBlock = 2;\n            ok = 1;",
     "            maxChase = 2;\n            maxBlock = 2;\n            ok = 1;"),
    ("req_beacop_block", P,
     "            maxChase = 1;\n            maxBlock = 2;\n            ok = 1;",
     "            maxChase = 1;\n            maxBlock = 1;\n            ok = 1;"),
    ("req_ai_count", P,
     "            if (q->pChasedCar->pPlayer == NULL)\n                ai++;",
     "            if (q->pChasedCar->pPlayer != NULL)\n                ai++;"),
    ("req_giveup", P,
     "    if (p != NULL && p->PursuitState == EPS_END_PURSUIT_GIVE_UP)",
     "    if (p != NULL && p->PursuitState == EPS_SPEEDER_CAUGHT)"),
    ("req_split", P,
     "    if (TheRaceParameters.NumPlayerCars >= 2) {",
     "    if (TheRaceParameters.NumPlayerCars > 2) {"),
    ("req_split_chase", P,
     "            maxChase = 1;\n            if (car->pPlayer != NULL) {",
     "            maxChase = 2;\n            if (car->pPlayer != NULL) {"),
    ("req_split_block", P,
     "                maxBlock = 1;\n                ok = found ? p->nNumCops < 1 : 1;",
     "                maxBlock = 2;\n                ok = found ? p->nNumCops < 1 : 1;"),
    ("req_split_player_ok", P,
     "                ok = found ? p->nNumCops < 1 : 1;",
     "                ok = found ? p->nNumCops < 2 : 1;"),
    ("req_split_ai_block", P,
     "                maxBlock = 0;\n                ok = found ? p->nNumCops < 1 : ai == 0;",
     "                maxBlock = 1;\n                ok = found ? p->nNumCops < 1 : ai == 0;"),
    ("req_split_ai_new", P,
     "                ok = found ? p->nNumCops < 1 : ai == 0;",
     "                ok = found ? p->nNumCops < 1 : ai < 2;"),
    ("req_split_ai_found", P,
     "                ok = found ? p->nNumCops < 1 : ai == 0;",
     "                ok = found ? p->nNumCops < 2 : ai == 0;"),
    ("req_ccp4", P,
     "            maxChase = pCurrentWorld->CopCarPos < 3 ? 2 : 1;",
     "            maxChase = pCurrentWorld->CopCarPos < 4 ? 2 : 1;"),
    ("req_ccp2", P,
     "            maxChase = pCurrentWorld->CopCarPos < 3 ? 2 : 1;",
     "            maxChase = pCurrentWorld->CopCarPos < 2 ? 2 : 1;"),
    ("req_player_block", P,
     "            maxChase = pCurrentWorld->CopCarPos < 3 ? 2 : 1;\n"
     "            maxBlock = 2;",
     "            maxChase = pCurrentWorld->CopCarPos < 3 ? 2 : 1;\n"
     "            maxBlock = 1;"),
    ("req_player_first", P,
     "            if (!found || p->nNumCops == 0)",
     "            if (!found)"),
    ("req_player_max", P,
     "                ok = p->nNumCops < maxChase\n",
     "                ok = p->nNumCops <= maxChase\n"),
    ("req_player_backup", P,
     "                     && p->bAlreadyCalledForBackup != 0;",
     "                     && p->bAlreadyCalledForBackup == 0;"),
    ("req_ai_chase", P,
     "            maxChase = 1;\n            maxBlock = 0;\n            // The demo",
     "            maxChase = 2;\n            maxBlock = 0;\n            // The demo"),
    ("req_ai_block", P,
     "            maxBlock = 0;\n            // The demo",
     "            maxBlock = 1;\n            // The demo"),
    ("req_ai_one", P,
     "            ok = found ? p->nNumCops < 1 : ai < 2;",
     "            ok = found ? p->nNumCops < 1 : ai < 1;"),
    ("req_ai_three", P,
     "            ok = found ? p->nNumCops < 1 : ai < 2;",
     "            ok = found ? p->nNumCops < 1 : ai < 3;"),
    ("req_ai_found", P,
     "            ok = found ? p->nNumCops < 1 : ai < 2;",
     "            ok = found ? p->nNumCops < 2 : ai < 2;"),
    ("req_new_id0", P,
     "        p = copmanager_new_pursuit(m, copmanager_find_free_pursuit_id(m),",
     "        p = copmanager_new_pursuit(m, 0,"),
    ("req_no_start_speech", P,
     "        if (gPursuitStartSpeechFn != NULL)\n",
     "        if (0)\n"),
    ("req_pl_chased", P,
     "        pl = (TheRaceParameters.BeACop != 0 ? c->pMyCar\n"
     "                                             : p->pChasedCar)->pPlayer;",
     "        pl = p->pChasedCar->pPlayer;"),
    ("req_pl_cop", P,
     "        pl = (TheRaceParameters.BeACop != 0 ? c->pMyCar\n"
     "                                             : p->pChasedCar)->pPlayer;",
     "        pl = c->pMyCar->pPlayer;"),
    ("req_no_nis", P,
     "        if (pl != NULL) {\n            Car    *mine",
     "        if (0) {\n            Car    *mine"),
    ("req_nis_cop", P,
     "                gPlayerLoadNextNisFn(pl, p->pChasedCar, mine, tickets);",
     "                gPlayerLoadNextNisFn(pl, p->pChasedCar, NULL, tickets);"),
    ("req_nis_tickets", P,
     "            int32_t tickets = copmanager_get_num_tickets(m, p->pChasedCar);",
     "            int32_t tickets = 0;"),
    ("req_no_join", P,
     "    } else if (gPursuitJoinSpeechFn != NULL) {",
     "    } else if (0) {"),
    ("req_maxchase", P,
     "    p->nMaxChaseCops = maxChase;",
     "    p->nMaxChaseCops = maxChase + 1;"),
    ("req_maxblock", P,
     "    p->nMaxRoadBlockCops = maxBlock;",
     "    p->nMaxRoadBlockCops = maxBlock + 1;"),
    ("req_slot0", P,
     "    p->Cops[p->nNumCops] = c;\n    p->nNumCops++;\n    tcop_set_pursuit",
     "    p->Cops[0] = c;\n    p->nNumCops++;\n    tcop_set_pursuit"),
    ("req_no_inc", P,
     "    p->Cops[p->nNumCops] = c;\n    p->nNumCops++;\n    tcop_set_pursuit",
     "    p->Cops[p->nNumCops] = c;\n    tcop_set_pursuit"),
    ("req_no_setp", P,
     "    tcop_set_pursuit(c, p);\n    return ok;",
     "    return ok;"),
    ("req_ret2", P,
     "    tcop_set_pursuit(c, p);\n    return ok;",
     "    tcop_set_pursuit(c, p);\n    return 2;"),

    # ---- PossibleCallSupervisor
    ("super_replay", P,
     "    if (copmanager_replaying())\n        return;",
     "    if (0)\n        return;"),
    ("super_eps", P,
     "<= 0.0010000000474974513f",
     "<= 0.01f"),
    ("super_lt", P,
     "<= 0.0010000000474974513f",
     "< 0.0010000000474974513f"),
    ("super_minus50", P,
     "fabsf(m->fSupervisorTimer - -50.0f)",
     "fabsf(m->fSupervisorTimer - -49.0f)"),
    ("super_rb", P,
     "    if (TheRaceParameters.bRoadBlocks == 0)\n        return;",
     "    if (0)\n        return;"),
    ("super_ai", P,
     "    if (p->pChasedCar->pPlayer == NULL)\n        return;\n"
     "    if (bRandomI(2",
     "    if (bRandomI(2"),
    ("super_odds", P,
     "    if (bRandomI(2, &bDefaultSeed) != 0)",
     "    if (bRandomI(2, &bDefaultSeed) == 0)"),
    ("super_range", P,
     "    if (bRandomI(2, &bDefaultSeed) != 0)",
     "    if (bRandomI(3, &bDefaultSeed) != 0)"),
    ("super_set", P,
     "    m->fSupervisorTimer = 7.0f;",
     "    m->fSupervisorTimer = 8.0f;"),
    ("super_spk2", P,
     "        uint32_t s = tpursuit_get_cop_speaker(p);",
     "        uint32_t s = tpursuit_get_secondary_cop_speaker(p);"),

    # ---- BarricadeManager
    ("bar_ctor_barrel", B,
     "        b->nBarrel[i] = -1;\n        b->fFadeTimer[i] = -1.0f;\n",
     "        b->nBarrel[i] = 0;\n        b->fFadeTimer[i] = -1.0f;\n"),
    ("bar_ctor_timer", B,
     "        b->fFadeTimer[i] = -1.0f;\n    }\n    return b;",
     "        b->fFadeTimer[i] = 0.0f;\n    }\n    return b;"),
    ("bar_ctor_short", B,
     "    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {\n        b->nBarrel[i] = -1;",
     "    for (i = 0; i < BARRICADE_MAX_BARRELS - 1; i++) {\n"
     "        b->nBarrel[i] = -1;"),
    ("bar_dtor_neg", B,
     "        if (b->nBarrel[i] == -1)\n            continue;\n"
     "        if (gBarricadeDeleteBarrelFn",
     "        if (b->nBarrel[i] < 0)\n            continue;\n"
     "        if (gBarricadeDeleteBarrelFn"),
    ("bar_dtor_short", B,
     "    b->vptr = BARRICADEMANAGER_VTABLE;\n"
     "    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {\n"
     "        if (b->nBarrel[i] == -1)",
     "    b->vptr = BARRICADEMANAGER_VTABLE;\n"
     "    for (i = 0; i < BARRICADE_MAX_BARRELS - 1; i++) {\n"
     "        if (b->nBarrel[i] == -1)"),
    ("bar_dtor_free", B,
     "    if (flags & 1)\n        bFree(b);",
     "    if (flags & 2)\n        bFree(b);"),
    ("bar_fade_neg", B,
     "        if (b->nBarrel[i] == -1)\n            continue;\n"
     "        b->fFadeTimer[i] = t;",
     "        if (b->nBarrel[i] < 0)\n            continue;\n"
     "        b->fFadeTimer[i] = t;"),
    ("bar_fade_t", B,
     "        b->fFadeTimer[i] = t;",
     "        b->fFadeTimer[i] = t + 1.0f;"),
    ("bar_fade_nobody", B,
     "        if (body != NULL) {",
     "        if (0) {"),
    ("bar_fade_find", B,
     "        body = collisionbody_find(b->nBarrel[i]);",
     "        body = collisionbody_find(i);"),

    # ---- DeleteRoadBlockSpikeStrips
    ("dss_ne", C,
     "        if (s->nRoadBlockID == i) {",
     "        if (s->nRoadBlockID != i) {"),
    ("dss_first", C,
     "            gSpikeStripBlinkBlinkPoofFn(s);\n        }\n        n = next;",
     "            gSpikeStripBlinkBlinkPoofFn(s);\n            break;\n        }\n"
     "        n = next;"),

    # ---- BarricadeManager's count down
    ("bcd_skip_id", B,
     "        if (b->nBarrel[i] == -1 || b->fFadeTimer[i] == -1.0f)",
     "        if (b->fFadeTimer[i] == -1.0f)"),
    ("bcd_skip_t", B,
     "        if (b->nBarrel[i] == -1 || b->fFadeTimer[i] == -1.0f)",
     "        if (b->nBarrel[i] == -1)"),
    ("bcd_dt", B,
     "        b->fFadeTimer[i] -= dt;",
     "        b->fFadeTimer[i] -= dt * 2.0f;"),
    ("bcd_le", B,
     "        if (b->fFadeTimer[i] < 0.0f) {",
     "        if (b->fFadeTimer[i] <= 0.0f) {"),
    ("bcd_timer", B,
     "            b->fFadeTimer[i] = -1.0f;\n            b->nBarrel[i] = -1;",
     "            b->nBarrel[i] = -1;"),
    ("bcd_id", B,
     "            b->fFadeTimer[i] = -1.0f;\n            b->nBarrel[i] = -1;",
     "            b->fFadeTimer[i] = -1.0f;"),

    # ---- Level0SubStates
    ("l0_16", P,
     "        if (p->fPursuitStateTimer < 16.0f) {",
     "        if (p->fPursuitStateTimer <= 16.0f) {"),
    ("l0_sub1", P,
     "            p->PursuitSubState = 1;",
     "            p->PursuitSubState = 2;"),
    ("l0_3", P,
     "        if (p->fPursuitStateTimer < 3.0f) {",
     "        if (p->fPursuitStateTimer <= 3.0f) {"),
    ("l0_sub2", P,
     "            p->PursuitSubState = 2;",
     "            p->PursuitSubState = 3;"),
    ("l0_else", P,
     "    } else if (p->PursuitSubState == 1) {",
     "    }\n    if (p->PursuitSubState == 1) {"),
    ("l0_nodeclare", P,
     "            if (gPursuitDeclareSpeechFn != NULL)\n"
     "                gPursuitDeclareSpeechFn(p);\n",
     ""),

    # ---- ShouldPursuitBeCalledOff
    ("co_blown", P,
     "    if ((int8_t)car->BlownTireBits != 0)\n        return 0;\n"
     "    if (TheRaceParameters.Point2Point != 0)",
     "    if ((int8_t)car->BlownTireBits > 1)\n        return 0;\n"
     "    if (TheRaceParameters.Point2Point != 0)"),
    ("co_p2p", P,
     "    if (TheRaceParameters.Point2Point != 0)\n        return 0;",
     "    if (0)\n        return 0;"),
    ("co_free", P,
     "    if (race_parameters_is_free_run(&TheRaceParameters))\n"
     "        return 0;",
     "    if (0 && race_parameters_is_free_run(&TheRaceParameters))\n"
     "        return 0;"),
    ("co_4", P,
     "    if (TheRaceParameters.NumLapsInRace < 4)",
     "    if (TheRaceParameters.NumLapsInRace < 3)"),
    ("co_2000", P,
     "    return left * TheTrackPathManager.TrackLength <= 2000.0f;",
     "    return left * TheTrackPathManager.TrackLength < 2000.0f;"),
    ("co_lap", P,
     "           - car->pRacingCar->FinishedLapNumberExact;",
     "           - car->pRacingCar->FinishedLapNumberExact * 0.5f;"),

    # ---- tPursuitHistory::Update
    ("hu_28", P,
     "    for (i = 29; i > 0; i--) {",
     "    for (i = 28; i > 0; i--) {"),
    ("hu_time", P,
     "        h->fTime[i] = h->fTime[i - 1];\n    }",
     "    }"),
    ("hu_dt", P,
     "    h->fTime[0] = dt;",
     "    h->fTime[0] = 0.0f;"),
    ("hu_vy", P,
     "    h->v2Velocity[0].y = vel->y;",
     "    h->v2Velocity[0].y = vel->x;"),
    ("hu_count", P,
     "    if (h->nCount != 30)\n        h->nCount++;",
     "    if (h->nCount != 31)\n        h->nCount++;"),
    ("hu_out", P,
     "        h->nCount++;\n    *out = *pos;",
     "        h->nCount++;\n    out->x = pos->y;\n    out->y = pos->x;"),

    # ---- UpdateDriveTargets
    ("ft_n2", P,
     "    if (n >= 2) {\n        const bVector3 *a",
     "    if (n >= 3) {\n        const bVector3 *a"),
    ("ft_dy", P,
     "        float dy = b->y - a->y;",
     "        float dy = 0.0f;"),
    ("ft_strict", P,
     "        if (strict ? !(apart < d) : !(apart <= d)) {",
     "        if (!(apart <= d)) {"),
    ("ft_loose", P,
     "        if (strict ? !(apart < d) : !(apart <= d)) {",
     "        if (!(apart < d)) {"),
    ("ft_setidx", P,
     "            drivetarget_set_point2(t, n - 1, pos, -1, -1, -1, 0.0f);",
     "            drivetarget_set_point2(t, n - 2, pos, -1, -1, -1, 0.0f);"),
    ("ft_noret", P,
     "            drivetarget_set_point2(t, n - 1, pos, -1, -1, -1, 0.0f);\n"
     "            return;",
     "            drivetarget_set_point2(t, n - 1, pos, -1, -1, -1, 0.0f);"),
    ("ft_19", P,
     "        if (n == 20)\n            drivetarget_shift_left(t, 1, 1);",
     "        if (n == 19)\n            drivetarget_shift_left(t, 1, 1);"),
    ("ft_shift2", P,
     "            drivetarget_shift_left(t, 1, 1);",
     "            drivetarget_shift_left(t, 2, 1);"),
    ("ft_add0", P,
     "    drivetarget_add_point2(t, pos, -1, -1, -1, 0, NULL);",
     "    drivetarget_add_point2(t, pos, -1, -1, -1, 1, NULL);"),
    ("udt_far", P,
     "    follow_target(&p->FarDriveTarget, &pos, 20.0f, 0);",
     "    follow_target(&p->FarDriveTarget, &pos, 21.0f, 0);"),
    ("udt_near", P,
     "    follow_target(&p->NearDriveTarget, &pos, 1.0f, 1);",
     "    follow_target(&p->NearDriveTarget, &pos, 2.0f, 1);"),
    ("udt_hist_dt", P,
     "                           WorldTimeElapsed);\n"
     "    follow_target(&p->NearDriveTarget",
     "                           dt);\n"
     "    follow_target(&p->NearDriveTarget"),
    ("udt_hist_vel", P,
     "                               &car->State.Velocity,",
     "                               &car->State.Position,"),
    ("udt_nohist", P,
     "    tpursuithistory_update(&p->History, &out,",
     "    if (0) tpursuithistory_update(&p->History, &out,"),

    # ---- tRoadBlockStateMachine::Update
    ("rb_none", P,
     "    if (s->State == ERBS_NONE)\n        return;\n"
     "    s->fStateTimer -= WorldTimeElapsed;",
     "    s->fStateTimer -= WorldTimeElapsed;"),
    ("rb_clamp", P,
     "        s->fStateTimer = 0.0f;\n    if (s->State != ERBS_CALLED",
     "        s->fStateTimer = 0.5f;\n    if (s->State != ERBS_CALLED"),
    ("rb_noclamp", P,
     "    if (s->fStateTimer <= 0.0f)\n        s->fStateTimer = 0.0f;",
     "    if (s->fStateTimer < -1.0f)\n        s->fStateTimer = 0.0f;"),
    ("rb_state1", P,
     "    if (s->State != ERBS_CALLED_FOR_ROAD_BLOCK || s->fStateTimer",
     "    if (s->State == ERBS_NONE || s->fStateTimer"),
    ("rb_timer", P,
     "|| s->fStateTimer != 0.0f)\n        return;",
     ")\n        return;"),
    ("rb_set", P,
     "    if (s->pPursuit->pRoadBlock != NULL)\n"
     "        s->State = ERBS_ROAD_BLOCK_SET;",
     "    s->State = ERBS_ROAD_BLOCK_SET;"),
    ("rb_setstate", P,
     "        s->State = ERBS_ROAD_BLOCK_SET;",
     "        s->State = ERBS_NONE;"),

    # ---- DoEarlyChaseCollisionCheck
    ("ec_player", P,
     "    if (p->pChasedCar->pPlayer == NULL || p->bAlreadyBeenHit != 0)",
     "    if (p->bAlreadyBeenHit != 0)"),
    ("ec_hit", P,
     "    if (p->pChasedCar->pPlayer == NULL || p->bAlreadyBeenHit != 0)",
     "    if (p->pChasedCar->pPlayer == NULL)"),
    ("ec_set", P,
     "    p->bAlreadyBeenHit = 1;\n    if (p->PursuitSubState == 0) {",
     "    if (p->PursuitSubState == 0) {"),
    ("ec_sub0", P,
     "    if (p->PursuitSubState == 0) {\n"
     "        if (gPursuitBeginCollisionSpeechFn",
     "    if (p->PursuitSubState == 1) {\n"
     "        if (gPursuitBeginCollisionSpeechFn"),
    ("ec_sub0_ret", P,
     "            gPursuitBeginCollisionSpeechFn(p, hit);\n        return;",
     "            gPursuitBeginCollisionSpeechFn(p, hit);"),
    ("ec_cop0", P,
     "    if (p->Cops[0] != NULL && hit == p->Cops[0]->pMyCar) {",
     "    if (p->Cops[0] != NULL && hit != p->Cops[0]->pMyCar) {"),
    ("ec_landmark", P,
     "            gSpeechRaisePursuitCopHitFn(s, p->CurrentLandmark);",
     "            gSpeechRaisePursuitCopHitFn(s, 0);"),
    ("ec_cophit_l3", P,
     "            gSpeechRaisePursuitCopHitFn(s, p->CurrentLandmark);\n"
     "        tpursuit_switch_state(p, EPS_LEVEL2);",
     "            gSpeechRaisePursuitCopHitFn(s, p->CurrentLandmark);\n"
     "        tpursuit_switch_state(p, EPS_LEVEL3);"),
    ("ec_coptype", P,
     "    if (hit->MyDriver->TheDriverType == DRIVER_TYPE_COP) {",
     "    if (hit->MyDriver->TheDriverType != DRIVER_TYPE_COP) {"),
    ("ec_cop_l3", P,
     "DRIVER_TYPE_COP) {\n        tpursuit_switch_state(p, EPS_LEVEL2);",
     "DRIVER_TYPE_COP) {\n        tpursuit_switch_state(p, EPS_LEVEL3);"),
    ("ec_traffic", P,
     "        gSpeechRaiseSuspectCrashTrafficFn(s, 0);",
     "        gSpeechRaiseSuspectCrashTrafficFn(s, 1);"),
    ("ec_l0", P,
     "    if (p->PursuitState == EPS_LEVEL0)\n"
     "        tpursuit_switch_state(p, EPS_LEVEL1);",
     "    tpursuit_switch_state(p, EPS_LEVEL1);"),

    # ---- IsCopNearby and DidRecentlyCollideWithCop
    ("d2_dy", P,
     "    float dy = a->State.Position.y - b->State.Position.y;",
     "    float dy = 0.0f;"),
    ("nb_bac", P,
     "    if (TheRaceParameters.BeACop != 0) {\n"
     "        tCop *pc = copmanager_get_player_cop(m);",
     "    if (0) {\n"
     "        tCop *pc = copmanager_get_player_cop(m);"),
    ("nb_bac_le", P,
     "        return distance_2d(pc->pMyCar, car) <= d;",
     "        return distance_2d(pc->pMyCar, car) < d;"),
    ("nb_le", P,
     "        if (distance_2d(cc, car) <= d)",
     "        if (distance_2d(cc, car) < d)"),
    ("nb_found", P,
     "    for (i = 0; i < m->nNumCops && !found; i++) {",
     "    for (i = 0; i < m->nNumCops; i++) {"),
    ("nb_disabled", P,
     "        case LS_DISABLED:\n", ""),
    ("nb_trap", P,
     "        case LS_SPEED_TRAP:\n", ""),
    ("nb_rb", P,
     "        case LS_ROAD_BLOCK:\n", ""),
    ("nb_patrol", P,
     "        case LS_DRIVING_ON_PATROL:\n", ""),
    ("nb_hot", P,
     "        case LS_HOT_PURSUIT:\n", ""),
    ("nb_guard", P,
     "        case LS_GUARD_LOCATION:\n", ""),
    ("nb_default", P,
     "        default:\n            continue;\n        }\n        cc = ",
     "        default:\n            break;\n        }\n        cc = "),
    ("nb_nis", P,
     "        if (cc->pPlayer != NULL && player_is_nis_playing(cc->pPlayer))",
     "        if (cc->pPlayer != NULL && 0)"),
    ("dc_hit", P,
     "    for (i = 0; i < m->nNumCops && !hit; i++)",
     "    for (i = 0; i < m->nNumCops; i++)"),
    ("dc_order", P,
     "        if (did_these_cars_collide(car, m->Cops[i]->pMyCar))",
     "        if (did_these_cars_collide(m->Cops[i]->pMyCar, car))"),

    # ---- IsChasedCarStoppable, Be A Cop's half
    ("up_z", P,
     "    return car->State.BodyMatrix.v2.z <= 0.10000000149011612f",
     "    return car->State.BodyMatrix.v2.z < 0.10000000149011612f"),
    ("up_or", P,
     "    return car->State.BodyMatrix.v2.z <= 0.10000000149011612f\n"
     "           && car",
     "    return car->State.BodyMatrix.v2.z <= 0.10000000149011612f\n"
     "           || car"),
    ("up_10", P,
     "           && car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f;",
     "           && car->State.VelocityMagnitude * PURSUIT_MPH < 11.0f;"),
    ("bac_d", P,
     "    d = distance_2d(car, pc->pMyCar);",
     "    d = distance_2d(car, pc->pMyCar) * 0.5f;"),
    ("bac_blink_pl", P,
     "        && (car->pPlayer != NULL ? car->JustResetFrames != 0 : d < 30.0f)) {",
     "        && (car->pPlayer == NULL ? car->JustResetFrames != 0 : d < 30.0f)) {"),
    ("bac_30", P,
     " : d < 30.0f)) {",
     " : d < 40.0f)) {"),
    ("bac_rad2", P,
     "            radius = radius * 1.100000023841858f;",
     "            radius = radius * 1.5f;"),
    ("bac_rad_np", P,
     "        if (TheRaceParameters.NumPlayerCars == 2)\n            radius",
     "        if (TheRaceParameters.NumPlayerCars != 2)\n            radius"),
    ("bac_dr", P,
     "        if (d < radius) {",
     "        if (d <= radius + 1.0f) {"),
    ("bac_blown", P,
     "            if ((int8_t)car->BlownTireBits != 0\n"
     "                && car->State.VelocityMagnitude < 0.10000000149011612f) {",
     "            if (0) {"),
    ("bac_upset", P,
     "            } else if (is_upset(car)) {\n                stop = 1;",
     "            } else if (0) {\n                stop = 1;"),
    ("bac_diff", P,
     "fBeACopCatchSpeeds[pCopManager->nDifficultyLevel];",
     "fBeACopCatchSpeeds[0];"),
    ("bac_slow2", P,
     "                    slow = slow * 1.5f;",
     "                    slow = slow * 2.0f;"),
    ("bac_slow", P,
     "                if (car->State.VelocityMagnitude < slow) {",
     "                if (car->State.VelocityMagnitude * 2.0f < slow) {"),
    ("bac_timing0", P,
     "                    timing = 0;\n", ""),
    ("bac_catch", P,
     "                    if (p->fCatchCarTimer < 0.0f)",
     "                    if (p->fCatchCarTimer < 0.5f)"),
    ("bac_pcspeed", P,
     "        return pc->pMyCar->State.VelocityMagnitude < 6.705409049987793f;",
     "        return pc->pMyCar->State.VelocityMagnitude < 7.5f;"),
    ("bac_stop1", P,
     "        return pc->pMyCar->State.VelocityMagnitude < 6.705409049987793f;",
     "        return 1;"),
    ("bac_timing", P,
     "    if (timing) {\n        p->fCatchCarTimer += WorldTimeElapsed;",
     "    if (1) {\n        p->fCatchCarTimer += WorldTimeElapsed;"),
    ("bac_cap", P,
     "        if (2.0f < p->fCatchCarTimer)\n            p->fCatchCarTimer = 2.0f;",
     "        if (3.0f < p->fCatchCarTimer)\n            p->fCatchCarTimer = 3.0f;"),
    ("bac_pc_order", P,
     "    d = distance_2d(car, pc->pMyCar);",
     "    d = distance_2d(car, car);"),

    # ---- IsChasedCarStoppable
    ("st_tickets", P,
     "    if (TheRaceParameters.bTickets == 0)\n        return 0;",
     "    if (0)\n        return 0;"),
    ("st_pull", P,
     "    if (pl[car->CarIndex].bActive != 0)",
     "    if (pl[0].bActive != 0)"),
    ("st_poof", P,
     "    if (car_is_poofed(car))\n        return 0;",
     "    if (car_is_poofed(car))\n        return 1;"),
    ("st_finish", P,
     "    if (car->pRacingCar->FinishReason != 0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0)\n        return be_a_cop",
     "    if (0)\n        return 0;\n"
     "    if (TheRaceParameters.BeACop != 0)\n        return be_a_cop"),
    ("st_bac", P,
     "    if (TheRaceParameters.BeACop != 0)\n"
     "        return be_a_cop_stoppable(p, car);",
     "    if (0)\n"
     "        return be_a_cop_stoppable(p, car);"),
    ("st_1556", P,
     "    if (p->New1556 <= 0.0f)",
     "    if (p->New1556 < 0.0f)"),
    ("st_cop0", P,
     "    if (p->Cops[0] != NULL)\n        near =",
     "    if (p->Cops[0] == NULL)\n        near ="),
    ("st_radius", P,
     "        near = copmanager_is_cop_nearby(pCopManager, car,\n"
     "                                        PURSUIT_CAPTURE_RADIUS);",
     "        near = copmanager_is_cop_nearby(pCopManager, car,\n"
     "                                        12.0f);"),
    ("st_airacer", P,
     "        near = car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER;",
     "        near = car->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER;"),
    ("st_10", P,
     "    if (car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f && near) {",
     "    if (car->State.VelocityMagnitude * PURSUIT_MPH < 11.0f && near) {"),
    ("st_near", P,
     "    if (car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f && near) {",
     "    if (car->State.VelocityMagnitude * PURSUIT_MPH < 10.0f) {"),
    ("st_catch0", P,
     "        if (p->fCatchCarTimer <= 0.0f)\n            stop = 1;",
     "        if (p->fCatchCarTimer < 0.0f)\n            stop = 1;"),
    ("st_catch1", P,
     "        else if (p->fCatchCarTimer <= 1.0f\n",
     "        else if (p->fCatchCarTimer < 1.0f\n"),
    ("st_coll", P,
     "                 && copmanager_did_recently_collide_with_cop(pCopManager,",
     "                 || copmanager_did_recently_collide_with_cop(pCopManager,"),
    ("st_reset", P,
     "        p->fCatchCarTimer = 2.0f;\n    }\n    if ((int8_t)",
     "        p->fCatchCarTimer = 1.0f;\n    }\n    if ((int8_t)"),
    ("st_blown", P,
     "        && car->State.VelocityMagnitude < 0.10000000149011612f)\n"
     "        return 1;",
     "        && car->State.VelocityMagnitude < 0.2f)\n"
     "        return 1;"),
    ("st_blown_any", P,
     "    if ((int8_t)car->BlownTireBits != 0\n"
     "        && car->State.VelocityMagnitude < 0.10000000149011612f)\n"
     "        return 1;",
     "    if (car->State.VelocityMagnitude < 0.10000000149011612f)\n"
     "        return 1;"),
    ("st_blink_pl", P,
     "        && (car->pPlayer == NULL || car->JustResetFrames != 0))",
     "        && (car->pPlayer != NULL || car->JustResetFrames != 0))"),
    ("st_jrf", P,
     "        && (car->pPlayer == NULL || car->JustResetFrames != 0))",
     "        && (car->pPlayer == NULL))"),
    ("st_upset", P,
     "    if (is_upset(car))\n        stop = 1;\n    return stop;",
     "    return stop;"),

    # ---- the chase direction (Be A Cop, two players)
    ("cd_find", P,
     "    const TrackRoutePoint *rp = car_get_route_point(car, 1);",
     "    const TrackRoutePoint *rp = car_get_route_point(car, 0);"),
    ("cd_dy", P,
     "                + car->State.Velocity.y * rp->Direction.y;",
     "                + 0.0f;"),
    ("cd_ge", P,
     "    float dir = 0.0f <= dot ? 1.0f : -1.0f;",
     "    float dir = 0.0f < dot ? 1.0f : -1.0f;"),
    ("cd_same", P,
     "    if (0.0f < dir * p->fChaseDirection) {",
     "    if (0.0f <= dir * p->fChaseDirection) {"),
    ("cd_reset", P,
     "        p->fChaseDirectionTimer = 0.0f;\n        return;",
     "        return;"),
    ("cd_8", P,
     "    if (8.0f <= p->fChaseDirectionTimer) {",
     "    if (8.0f < p->fChaseDirectionTimer) {"),
    ("cd_reset2", P,
     "        p->fChaseDirectionTimer = 0.0f;\n        p->fChaseDirection = dir;",
     "        p->fChaseDirection = dir;"),
    ("cd_dir", P,
     "        p->fChaseDirection = dir;",
     "        p->fChaseDirection = 1.0f;"),

    # ---- tPursuit::Update
    ("u_count", P,
     "    barricademanager_count_down(p->pBarricades, WorldTimeElapsed);",
     ""),
    ("u_lm", P,
     "    p->CurrentLandmark = lm != NULL ? lm->LandmarkType : 0;",
     "    p->CurrentLandmark = lm != NULL ? lm->LandmarkType : -1;"),
    ("u_lm_type", P,
     "    p->CurrentLandmark = lm != NULL ? lm->LandmarkType : 0;",
     "    p->CurrentLandmark = lm != NULL ? 1 : 0;"),
    ("u_blown", P,
     "    if ((int8_t)car->BlownTireBits != 0)\n"
     "        p->New1556 -= WorldTimeElapsed;",
     "    p->New1556 -= WorldTimeElapsed;"),
    ("u_np1", P,
     "    if (TheRaceParameters.NumPlayerCars != 1\n",
     "    if (TheRaceParameters.NumPlayerCars != 2\n"),
    ("u_fin", P,
     "        && car->pRacingCar->FinishReason != 0)\n        return 1;",
     "        && 1)\n        return 1;"),
    ("u_bac", P,
     "    if (TheRaceParameters.BeACop != 0) {\n"
     "        if (TheRaceParameters.NumPlayerCars == 2)",
     "    if (0) {\n"
     "        if (TheRaceParameters.NumPlayerCars == 2)"),
    ("u_bac2", P,
     "        if (TheRaceParameters.NumPlayerCars == 2)\n"
     "            update_chase_direction(p, car);",
     "        if (TheRaceParameters.NumPlayerCars != 2)\n"
     "            update_chase_direction(p, car);"),
    ("u_top_vm", P,
     "        if (p->fChasedCarTopSpeed < car->State.ForwardSpeed)\n"
     "            p->fChasedCarTopSpeed = car->State.ForwardSpeed;",
     "        if (p->fChasedCarTopSpeed < car->State.VelocityMagnitude)\n"
     "            p->fChasedCarTopSpeed = car->State.VelocityMagnitude;"),
    ("u_top_le", P,
     "        if (p->fChasedCarTopSpeed < car->State.ForwardSpeed)",
     "        if (p->fChasedCarTopSpeed > car->State.ForwardSpeed)"),
    ("u_cops", P,
     "        for (i = 0; i < p->nNumCops; i++) {\n            Car *cc",
     "        for (i = 0; i < 1; i++) {\n            Car *cc"),
    ("u_mode", P,
     "            if (cc->TheMovementMode == COP_MOVEMENT)",
     "            if (cc->TheMovementMode != COP_MOVEMENT)"),
    ("u_mover", P,
     "                ((CopMover *)(void *)cc->pCarMover)->fBaseMaxSpeed =\n"
     "                    p->fChasedCarTopSpeed;",
     "                ((CopMover *)(void *)cc->pCarMover)->fBaseMaxSpeed =\n"
     "                    car->State.ForwardSpeed;"),
    ("u_udt", P,
     "        tpursuit_update_drive_targets(p, WorldTimeElapsed);\n", ""),
    ("u_spc", P,
     "        tpursuit_select_primary_cop(p);\n", ""),
    ("u_rt3", P,
     "        if (TheRaceParameters.RaceType == 3)",
     "        if (TheRaceParameters.RaceType == 2)"),
    ("u_rt3_over", P,
     "            over = p->pChasedCar->pRacingCar->FinishReason != 0;",
     "            over = 0;"),
    ("u_calloff", P,
     "            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);\n"
     "            over = 1;",
     "            over = 1;"),
    ("u_calloff_over", P,
     "            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);\n"
     "            over = 1;",
     "            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);"),
    ("u_tcond", P,
     "        } else if (p->nNumCops != 0 || p->PursuitState >= EPS_LEVEL3) {",
     "        } else if (p->nNumCops != 0) {"),
    ("u_l3", P,
     "|| p->PursuitState >= EPS_LEVEL3) {",
     "|| p->PursuitState > EPS_LEVEL3) {"),
    ("u_telse", P,
     "        } else if (p->nNumCops != 0 || p->PursuitState >= EPS_LEVEL3) {",
     "        }\n        if (p->nNumCops != 0 || p->PursuitState >= EPS_LEVEL3) {"),
    ("u_trans_le", P,
     "        if (p->fPursuitStateTimer <= 0.0f && tpursuit_do_state_transition(p))",
     "        if (p->fPursuitStateTimer < 0.0f && tpursuit_do_state_transition(p))"),
    ("u_trans_over", P,
     "&& tpursuit_do_state_transition(p))\n            over = 1;",
     "&& tpursuit_do_state_transition(p))\n            over = 0;"),
    ("u_chasing", P,
     "    if (!tpursuit_not_in_chasing_state(p)) {",
     "    if (1) {"),
    ("u_over_early", P,
     "        if (over)\n            return over;\n        if (tpursuit_is_chased",
     "        if (tpursuit_is_chased"),
    ("u_pull_arg", P,
     "gCopManagerCreatePulloverFn(pCopManager, p, p->pChasedCar, 1);",
     "gCopManagerCreatePulloverFn(pCopManager, p, p->pChasedCar, 0);"),
    ("u_caught", P,
     "            tpursuit_switch_state(p, EPS_SPEEDER_CAUGHT);",
     "            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);"),
    ("u_release", P,
     "            tpursuit_release_all_cops(p);\n        }\n    }",
     "        }\n    }"),
    ("u_caught_over", P,
     "            over = 1;\n            tpursuit_switch_state(p, EPS_SPEEDER_CAUGHT);",
     "            tpursuit_switch_state(p, EPS_SPEEDER_CAUGHT);"),
    ("u_rbsm", P,
     "    trbsm_update(&p->RoadBlockStateMachine);\n", ""),
    ("u_rbs", P,
     "    if (gPursuitUpdateRoadBlocksFn != NULL)\n"
     "        gPursuitUpdateRoadBlocksFn(p);\n", ""),
    ("u_chop", P,
     "    if (gPursuitUpdateChopperFn != NULL)\n"
     "        gPursuitUpdateChopperFn(p);\n", ""),
    ("u_bac_ret", P,
     "    if (TheRaceParameters.BeACop != 0)\n        return 0;\n    switch",
     "    switch"),
    ("u_l0", P,
     "        tpursuit_level0_sub_states(p);\n", ""),
    ("u_l0_ec", P,
     "        tpursuit_level0_sub_states(p);\n"
     "        tpursuit_do_early_chase_collision_check(p);\n",
     "        tpursuit_level0_sub_states(p);\n"),
    ("u_l1_ec", P,
     "    case EPS_LEVEL1:\n        tpursuit_do_early_chase_collision_check(p);\n",
     "    case EPS_LEVEL1:\n"),
    ("u_give", P,
     "    case EPS_END_PURSUIT_GIVE_UP:\n        return 1;",
     "    case EPS_END_PURSUIT_GIVE_UP:\n        return 0;"),
    ("u_default", P,
     "    default:\n        return 0;\n    }\n}",
     "    default:\n        return 1;\n    }\n}"),
    # ---- 12i-1, the roadblocks
    ("rr_state", P,
     "    if (s->State != ERBS_NONE)\n        return;\n    if (s->SpeechFlags & 1u) {",
     "    if (s->State != ERBS_NONE && 0)\n        return;\n    if (s->SpeechFlags & 1u) {"),
    ("rr_flag1", P,
     "    if (s->SpeechFlags & 1u) {",
     "    if (s->SpeechFlags & 2u) {"),
    ("rr_another_bac", P,
     "        if (TheRaceParameters.BeACop != 0) {\n            spk = tpursuit_get_cop_speaker(p);",
     "        if (TheRaceParameters.BeACop == 0) {\n            spk = tpursuit_get_cop_speaker(p);"),
    ("rr_quiet_le", P,
     "<= 0.0010000000474974513f;",
     "< 0.0010000000474974513f;"),
    ("rr_quiet_abs", P,
     "return fabsf(pCopManager->fSupervisorTimer) <=",
     "return (pCopManager->fSupervisorTimer) <="),
    ("rr_spike_bit", P,
     "        if (p->BehaviourFlags & 0x10u) {\n            if (gSpeechRaiseSpikeStripRequestFn",
     "        if (p->BehaviourFlags & 0x08u) {\n            if (gSpeechRaiseSpikeStripRequestFn"),
    ("rr_spike_swap", P,
     "                gSpeechRaiseSpikeStripRequestFn(spk, supervisor_quiet());",
     "                gSpeechRaiseRoadblockRequestFn(spk, supervisor_quiet());"),
    ("rr_set_flag", P,
     "        s->SpeechFlags |= 1u;",
     "        s->SpeechFlags |= 2u;"),
    ("rr_clear8", P,
     "        p->BehaviourFlags &= ~8u;",
     "        p->BehaviourFlags &= ~0x10u;"),
    ("rr_nrb_test", P,
     "if (pCopManager->nBeACopNumRoadBlocks != 0) {",
     "if (pCopManager->nBeACopNumRoadBlocks > 0) {"),
    ("rr_nrb_dec", P,
     "            pCopManager->nBeACopNumRoadBlocks--;",
     "            pCopManager->nBeACopNumRoadBlocks -= 0;"),
    ("rr_na_id", P,
     "gSpeechRaiseDispatchRoadBlockNAFn(pCopManager->BeACopId);",
     "gSpeechRaiseDispatchRoadBlockNAFn(0);"),
    ("rr_refused", P,
     "            refused = 1;",
     "            refused = 0;"),
    ("rr_timer", P,
     "        s->fStateTimer = 8.0f;",
     "        s->fStateTimer = 7.0f;"),
    ("rr_state1", P,
     "        s->State = ERBS_CALLED_FOR_ROAD_BLOCK;\n        s->fStateTimer = 8.0f;",
     "        s->State = (eRoadBlockState)2;\n        s->fStateTimer = 8.0f;"),
    ("mr_blown", P,
     "    if ((int8_t)car->BlownTireBits != 0)\n        return 0;\n    pl = car->pPlayer;",
     "    if (0)\n        return 0;\n    pl = car->pPlayer;"),
    ("mr_pl", P,
     "    if (pl != NULL) {\n        for (i = 0; i < 2; i++) {",
     "    if (pl == NULL) {\n        for (i = 0; i < 2; i++) {"),
    ("mr_loop1", P,
     "    if (pl != NULL) {\n        for (i = 0; i < 2; i++) {",
     "    if (pl != NULL) {\n        for (i = 0; i < 1; i++) {"),
    ("mr_collide_args", P,
     "!did_these_cars_collide(p->pChasedCar, c->pMyCar))",
     "!did_these_cars_collide(c->pMyCar, p->pChasedCar))"),
    ("mr_real", P,
     "            if (car->TheControlMode == REAL_CONTROL) {",
     "            if (car->TheControlMode != REAL_CONTROL) {"),
    ("mr_ebrake_t", P,
     "(struct RealDriver *)(void *)car->pCarDriver, 5.0f);",
     "(struct RealDriver *)(void *)car->pCarDriver, 4.0f);"),
    ("mr_ai", P,
     "            } else if (car->TheControlMode == AI_CONTROL\n",
     "            } else if (car->TheControlMode == TRAFFIC_CONTROL\n"),
    ("mr_phys", P,
     "&& (car->TheMovementMode == PHYSICS_MOVEMENT\n",
     "&& (car->TheMovementMode == COP_MOVEMENT\n"),
    ("mr_mellow", P,
     "|| car->TheMovementMode == MELLOW_MOVEMENT)) {",
     "|| car->TheMovementMode == BELT_MOVEMENT)) {"),
    ("mr_ai_t", P,
     "->EBrakeTimer =\n                    4.0f;",
     "->EBrakeTimer =\n                    5.0f;"),
    ("mr_mph", P,
     "if (17.88109016418457f < fabsf(car->State.ForwardSpeed)",
     "if (17.88109016418457f <= fabsf(car->State.ForwardSpeed)"),
    ("mr_abs", P,
     "17.88109016418457f < fabsf(car->State.ForwardSpeed)",
     "17.88109016418457f < (car->State.ForwardSpeed)"),
    ("mr_zone_args", P,
     "&& player_request_zone(pl, 1, 0, 1, 1)",
     "&& player_request_zone(pl, 1, 1, 1, 1)"),
    ("mr_zone_test", P,
     "&& player_request_zone(pl, 1, 0, 1, 1)",
     "&& !player_request_zone(pl, 1, 0, 1, 1)"),
    ("mr_break", P,
     "                    &p->pChasedCar->State.Position);\n            break;",
     "                    &p->pChasedCar->State.Position);\n            continue;"),
    ("mr_width", P,
     "if (!(sqrtf(dx * dx + dy * dy) < rb->fRoadWidth))",
     "if (!(sqrtf(dx * dx + dy * dy) <= rb->fRoadWidth))"),
    ("mr_dx", P,
     "    dx = rb->v2Position.x - car->State.Position.x;\n    dy = rb->v2Position.y",
     "    dx = rb->v2Position.y - car->State.Position.x;\n    dy = rb->v2Position.y"),
    ("mr_dy", P,
     "    dy = rb->v2Position.y - car->State.Position.y;\n    if (!(sqrtf",
     "    dy = rb->v2Position.y - car->State.Position.x;\n    if (!(sqrtf"),
    ("mr_mine_x", P,
     "mine = (car->State.Position.x - rp->Position.x) * rp->Direction.x",
     "mine = (car->State.Position.x - rp->Position.x) * rp->Direction.y"),
    ("mr_mine_y", P,
     "         + (car->State.Position.y - rp->Position.y) * rp->Direction.y;",
     "         + (car->State.Position.y - rp->Position.x) * rp->Direction.y;"),
    ("mr_theirs_x", P,
     "theirs = (rb->v2Position.x - rp->Position.x) * rp->Direction.x",
     "theirs = (rb->v2Position.x - rp->Position.y) * rp->Direction.x"),
    ("mr_theirs_y", P,
     "           + (rb->v2Position.y - rp->Position.y) * rp->Direction.y;",
     "           + (rb->v2Position.y - rp->Position.y) * rp->Direction.x;"),
    ("mr_5", P,
     "return 5.0f < p->fChaseDirection * (mine - theirs);",
     "return 5.0f <= p->fChaseDirection * (mine - theirs);"),
    ("mr_dir", P,
     "return 5.0f < p->fChaseDirection * (mine - theirs);",
     "return 5.0f < (mine - theirs);"),
    ("rd_involved", P,
     "    if (tpursuit_is_player_involved(p)) {\n        pl = p->pChasedCar->pPlayer;",
     "    if (!tpursuit_is_player_involved(p)) {\n        pl = p->pChasedCar->pPlayer;"),
    ("rd_calloff_pl", P,
     "if (pl != NULL && tpursuit_should_pursuit_be_called_off(p)) {",
     "if (tpursuit_should_pursuit_be_called_off(p)) {"),
    ("rd_give", P,
     "            tpursuit_switch_state(p, EPS_END_PURSUIT_GIVE_UP);\n        } else {",
     "            tpursuit_switch_state(p, (ePursuitState)4);\n        } else {"),
    ("rd_failed_b", P,
     "gPursuitRoadblockFailedSpeechFn(p, b);",
     "gPursuitRoadblockFailedSpeechFn(p, 1);"),
    ("rd_score_pl", P,
     "            if (pl != NULL) {\n                player_start_score(pl, SCORING_DODGE_ROADBLOCK);",
     "            if (pl == NULL) {\n                player_start_score(pl, SCORING_DODGE_ROADBLOCK);"),
    ("rd_score", P,
     "player_start_score(pl, SCORING_DODGE_ROADBLOCK);",
     "player_start_score(pl, SCORING_DODGE_ROADBLOCK + 1);"),
    ("rd_beacop", P,
     "            if (TheRaceParameters.BeACop == 0\n                && p->PursuitSubState == LSS_FOLLOW_BACKWARDS) {",
     "            if (TheRaceParameters.BeACop != 0\n                && p->PursuitSubState == LSS_FOLLOW_BACKWARDS) {"),
    ("rd_sub", P,
     "                && p->PursuitSubState == LSS_FOLLOW_BACKWARDS) {",
     "                && p->PursuitSubState == LSS_FOLLOW_BACKWARDS + 1) {"),
    ("rd_p2p", P,
     "                           ? 1 : TheRaceParameters.NumLapsInRace;",
     "                           ? 2 : TheRaceParameters.NumLapsInRace;"),
    ("rd_p2p_test", P,
     "                laps = TheRaceParameters.Point2Point != 0\n",
     "                laps = TheRaceParameters.Point2Point == 0\n"),
    ("rd_laps2", P,
     "                if (laps == 2\n",
     "                if (laps == 3\n"),
    ("rd_rand_range", P,
     "world_random_i(pCurrentWorld, 3) < 2u",
     "world_random_i(pCurrentWorld, 4) < 2u"),
    ("rd_rand_lt", P,
     "world_random_i(pCurrentWorld, 3) < 2u",
     "world_random_i(pCurrentWorld, 3) < 3u"),
    ("rd_rand_signed", P,
     "((uint32_t)world_random_i(pCurrentWorld, 3) < 2u",
     "((int32_t)world_random_i(pCurrentWorld, 3) < 2"),
    ("rd_n624", P,
     "&& TheRaceParameters.New624 != 0)) {",
     "&& TheRaceParameters.New624 == 0)) {"),
    ("rd_or", P,
     "                if (laps == 2\n                    ||",
     "                if (laps == 2\n                    &&"),
    ("rd_add", P,
     "                    p->fRoadBlockSpawnTimer += fRoadBlockSpawnTime;",
     "                    p->fRoadBlockSpawnTimer = fRoadBlockSpawnTime;"),
    ("rd_0x20", P,
     "                    p->BehaviourFlags |= 0x20u;",
     "                    p->BehaviourFlags |= 0x40u;"),
    ("rd_5", P,
     "    if (p->nRoadblockCount >= 5)\n",
     "    if (p->nRoadblockCount > 5)\n"),
    ("rd_0x80", P,
     "    if (p->nRoadblockCount >= 5)\n        p->BehaviourFlags |= 0x80u;",
     "    if (p->nRoadblockCount >= 5)\n        p->BehaviourFlags |= 0x08u;"),
    ("rd_3", P,
     "    else if (p->nRoadblockCount < 3)\n",
     "    else if (p->nRoadblockCount <= 3)\n"),
    ("rd_0x40", P,
     "    else if (p->nRoadblockCount < 3)\n        p->BehaviourFlags |= 0x40u;",
     "    else if (p->nRoadblockCount < 3)\n        p->BehaviourFlags |= 0x20u;"),
    ("rd_heli", P,
     "    else if (TheRaceParameters.bHelicopter != 0)\n",
     "    else if (TheRaceParameters.bHelicopter == 0)\n"),
    ("rd_0x110", P,
     "        p->BehaviourFlags |= 0x110u;",
     "        p->BehaviourFlags |= 0x100u;"),
    ("rp_cop0", P,
     "    if (rb == NULL || rb->cops[0] == NULL)\n        return;",
     "    if (rb == NULL || rb->cops[1] == NULL)\n        return;"),
    ("rp_vel", P,
     "    if (!(20.0f < car->State.VelocityMagnitude))",
     "    if (!(20.0f <= car->State.VelocityMagnitude))"),
    ("rp_car", P,
     "    car = pl->MyCar;\n",
     "    car = p->pChasedCar;\n"),
    ("rp_cop", P,
     "    cop = ((const tCop *)(const void *)rb->cops[0])->pMyCar;",
     "    cop = ((const tCop *)(const void *)rb->cops[1])->pMyCar;"),
    ("rp_dist", P,
     "if (sqrtf(dx * dx + dy * dy + dz * dz) < 20.0f",
     "if (sqrtf(dx * dx + dy * dy + dz * dz) <= 20.0f"),
    ("rp_dz", P,
     "if (sqrtf(dx * dx + dy * dy + dz * dz) < 20.0f",
     "if (sqrtf(dx * dx + dy * dy) < 20.0f"),
    ("rp_value", P,
     "ReplayManager_RegisterInterestingEvent(pReplayManager, 10.0f,",
     "ReplayManager_RegisterInterestingEvent(pReplayManager, 11.0f,"),
    ("ur_blown", P,
     "        if ((int8_t)car->BlownTireBits != 0) {\n            if (car->MyDriver",
     "        if ((int8_t)car->BlownTireBits == 0) {\n            if (car->MyDriver"),
    ("ur_ai", P,
     "car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER\n                && TheRaceParameters.BeACop != 0\n                && gSpeechRaiseSpikeStripTireBlowFn",
     "car->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER\n                && TheRaceParameters.BeACop != 0\n                && gSpeechRaiseSpikeStripTireBlowFn"),
    ("ur_bac", P,
     "                && TheRaceParameters.BeACop != 0\n                && gSpeechRaiseSpikeStripTireBlowFn",
     "                && TheRaceParameters.BeACop == 0\n                && gSpeechRaiseSpikeStripTireBlowFn"),
    ("ur_tb_args", P,
     "gSpeechRaiseSpikeStripTireBlowFn(pCopManager->BeACopId, 0);",
     "gSpeechRaiseSpikeStripTireBlowFn(pCopManager->BeACopId, 1);"),
    ("ur_tb_disband", P,
     "BeACopId, 0);\n            tpursuit_disband_road_block(p, 1);",
     "BeACopId, 0);\n            tpursuit_disband_road_block(p, 0);"),
    ("ur_monitor_b", P,
     "if (p->pRoadBlock != NULL && tpursuit_monitor_road_block(p))\n        road_block_passed(p, 1);",
     "if (p->pRoadBlock != NULL && tpursuit_monitor_road_block(p))\n        road_block_passed(p, 0);"),
    ("rbp_timer", P,
     "    p->fRoadBlockSpawnTimer = fRoadBlockSpawnTime;\n    if ((int8_t)p->pChasedCar->BlownTireBits == 0)",
     "    p->fRoadBlockSpawnTimer = 0.0f;\n    if ((int8_t)p->pChasedCar->BlownTireBits == 0)"),
    ("rbp_blown", P,
     "    if ((int8_t)p->pChasedCar->BlownTireBits == 0)\n        tpursuit_road_block_defeated(p, b);",
     "    if ((int8_t)p->pChasedCar->BlownTireBits != 0)\n        tpursuit_road_block_defeated(p, b);"),
    ("rbp_disband", P,
     "        tpursuit_road_block_defeated(p, b);\n    tpursuit_disband_road_block(p, 1);",
     "        tpursuit_road_block_defeated(p, b);\n    tpursuit_disband_road_block(p, 0);"),
    ("ur_dt", P,
     "t = p->fRoadBlockDisbandTimer - WorldTimeElapsed;",
     "t = p->fRoadBlockDisbandTimer + WorldTimeElapsed;"),
    ("ur_le", P,
     "        if (!(t <= 0.0f))\n            return;",
     "        if (!(t < 0.0f))\n            return;"),
    ("ur_zero", P,
     "        p->fRoadBlockDisbandTimer = 0.0f;\n        rbd",
     "        p->fRoadBlockDisbandTimer = 1.0f;\n        rbd"),
    ("ur_dir1", P,
     "        if (p->fChaseDirection == 1.0f)\n",
     "        if (p->fChaseDirection > 0.0f)\n"),
    ("ur_fwd1", P,
     "d = get_forward_track_distance(rbd + 100.0f, dat);",
     "d = get_forward_track_distance(dat, rbd + 100.0f);"),
    ("ur_fwd1_100", P,
     "d = get_forward_track_distance(rbd + 100.0f, dat);",
     "d = get_forward_track_distance(rbd + 10.0f, dat);"),
    ("ur_fwd2", P,
     "d = get_forward_track_distance(dat + 100.0f, rbd);",
     "d = get_forward_track_distance(rbd + 100.0f, dat);"),
    ("ur_08", P,
     "if (!(TheTrackPathManager.TrackLength * 0.800000011920929f < d))",
     "if (!(TheTrackPathManager.TrackLength * 0.800000011920929f <= d))"),
    ("ur_08_val", P,
     "TheTrackPathManager.TrackLength * 0.800000011920929f < d",
     "TheTrackPathManager.TrackLength * 0.7f < d"),
    ("ur_far_b", P,
     "        road_block_passed(p, 0);\n",
     "        road_block_passed(p, 1);\n"),
    ("ur_bac_zero", P,
     "    } else if (TheRaceParameters.BeACop != 0) {\n        p->fRoadBlockSpawnTimer = 0.0f;",
     "    } else if (TheRaceParameters.BeACop != 0) {\n        p->fRoadBlockSpawnTimer = 1.0f;"),
    ("ur_bac_else", P,
     "    } else if (TheRaceParameters.BeACop != 0) {\n        p->fRoadBlockSpawnTimer = 0.0f;",
     "    } else if (TheRaceParameters.BeACop == 0) {\n        p->fRoadBlockSpawnTimer = 0.0f;"),
    ("ur_spawn_dt", P,
     "t = p->fRoadBlockSpawnTimer - WorldTimeElapsed;",
     "t = p->fRoadBlockSpawnTimer + WorldTimeElapsed;"),
    ("ur_spawn_lt", P,
     "        if (t < 0.0f)\n            p->fRoadBlockSpawnTimer = 0.0f;",
     "        if (t <= 0.0f)\n            p->fRoadBlockSpawnTimer = 0.0f;"),
    ("ur_req_rb", P,
     "    if (p->pRoadBlock != NULL || !(p->BehaviourFlags & 8u))\n        return;",
     "    if (p->pRoadBlock != NULL || !(p->BehaviourFlags & 0x10u))\n        return;"),
    ("ur_req_has_rb", P,
     "    if (p->pRoadBlock != NULL || !(p->BehaviourFlags & 8u))\n        return;",
     "    if (!(p->BehaviourFlags & 8u))\n        return;"),
    ("ur_req_bac", P,
     "    if (TheRaceParameters.BeACop != 0\n        || (TheRaceParameters.bRoadBlocks != 0",
     "    if (TheRaceParameters.BeACop == 0\n        || (TheRaceParameters.bRoadBlocks != 0"),
    ("ur_req_rbs", P,
     "        || (TheRaceParameters.bRoadBlocks != 0\n",
     "        || (TheRaceParameters.bRoadBlocks == 0\n"),
    ("ur_req_blown", P,
     "            && (int8_t)p->pChasedCar->BlownTireBits == 0\n            && tpursuit_is_player_involved(p)",
     "            && (int8_t)p->pChasedCar->BlownTireBits != 0\n            && tpursuit_is_player_involved(p)"),
    ("ur_req_pi", P,
     "            && tpursuit_is_player_involved(p)\n            && p->fRoadBlockSpawnTimer <= 0.0f))",
     "            && p->fRoadBlockSpawnTimer <= 0.0f))"),
    ("ur_req_le", P,
     "            && p->fRoadBlockSpawnTimer <= 0.0f))",
     "            && p->fRoadBlockSpawnTimer < 0.0f))"),
    ("ur_has_rb", P,
     "    if (p->pRoadBlock != NULL && tpursuit_monitor_road_block(p))",
     "    if (p->pRoadBlock != NULL && !tpursuit_monitor_road_block(p))"),
]

EQUIVALENT = {
    "super_lt": "the timer less -50 is exact within 25 of -50 (Sterbenz), "
                "so a multiple of 2^-18, which 0.001f is not; further off "
                "it is 25 or more: never equal",
    "bar_dtor_free": "the barricades' one caller, the pursuit's "
                     "destructor, passes 3",
    "remove_rb_too": "the roadblock's loop runs only while !found, so a "
                     "cop found in Cops skips it either way",
    "ur_req_has_rb": "with a roadblock, UpdateRoadBlocks either returns "
                     "or disbands it before the request, so the test "
                     "always sees NULL there",
}


def mutate_pass(only=None, jobs=None):
    todo = [mu for mu in MUTATIONS if only is None or mu[0] in only]
    if only:
        unknown = set(only) - {mu[0] for mu in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
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
        todo, SOURCES, "pursuit_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
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

    lines = script()
    got = model(lines)
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
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
