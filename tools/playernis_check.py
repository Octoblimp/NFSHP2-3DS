#!/usr/bin/env python3
"""Cross-check 3DS Files/source/playernis.c, a player's NIS and game state
(12l-2), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: Player's CreateRandomNisArray
(0x00181a28), PlayNextNis (0x00176308), ServiceNis (0x00176530),
DetectWrongWay (0x00181058), IsAllowedToReset (0x00181e98),
ChooseToDisplayReset (0x00181f68) and UpdateGameState (0x00180c28), and
UpdatePlayersGameState (0x00181de8); and what they call that is a few
instructions or a lookup, run as it is: IsNisPlaying (0x00176520), the
NIS table's GetNumNisInfo, GetNisInfo and GetNisInfo by type, and
Timer::SetTime. The harness (tools/src/playernis_test.c) runs
playernis.c with nisinfo.c and timer.c and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
tCopManager's GetNumTickets and IsBeingPursued (scripted), Player's
ClearZone, RequestZone (scripted) and ChangeCameraMover, RadialBlurOff,
Car's StopBlinking, GetRoute and GetRoutePoint (scripted), IsFreeRun
(scripted), NisManager's Start (it marks the manager playing, on that
camera, until 30 frames on), Stop (it clears Playing), Unload and
AllowDebugLooping (scripted), CreateNisCameraCoordinator, the overlay's
StartTicket, StartArrest and Finish, IsReplayDemoMode (scripted), bRandom
on a seed (an LCG of the script's), bATan (a queue of the script's),
CarState::GetYawAlways (scripted), Average::Record (it stores the
script's mean) and PlayBustRoadBlock; and the NIS's callback.

**Compared** are the stubs' logs and, after each call, the return value,
bResetGlare, each player's callback and its parameter, both NIS indices,
the camera coordinator, the wrong-way flag, the trouble and reset-prompt
timers, the trouble speed and its timer, the speed-ratio timer and peak,
the freeze delay, the first ten of each NIS and camera array, and each
NisManager's Playing, EndTime, CamNumber and NisNumber.

**The divergences**: none in what is compared. Retail reads a player's
NisManager without testing it, and the port does not play a NIS for a
player without one (playernis.h); every player here has one. A NIS
number past the table and a NIS of no cameras are left out of
PlayNextNis's cases: retail reads past the table and divides by zero.

    python tools/playernis_check.py
    python tools/playernis_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/playernis_test.c"
PN = "3DS Files/source/playernis.c"
SOURCES = [HARNESS, PN, "3DS Files/source/nisinfo.c",
           "3DS Files/source/timer.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
G_COPMGR = GP - 15620
G_RC = GP - 22216
G_RACE = GP - 22272
G_BYIDX = GP - 20928
G_NPL = GP - 20920
G_GLARE = GP - 23564
G_WTF = GP - 19564
G_WT = GP - 19576
G_WTE = GP - 19560
G_TABLE = GP - 18844
G_NTAB = GP - 18848
G_SEED = GP - 14472

F_CRNA = 0x00181a28
F_PNN = 0x00176308
F_SVC = 0x00176530
F_DWW = 0x00181058
F_IAR = 0x00181e98
F_CTDR = 0x00181f68
F_UGS = 0x00180c28
F_UPGS = 0x00181de8
F_PSR = 0x00182208

S_BLUR = 0x0010f1b0
S_NOBLINK = 0x00133128
S_ROUTE = 0x001332a8
S_POINT = 0x001332d8
S_DEMO = 0x001369a8
S_CAM = 0x00176ae8
S_ZONE = 0x00177c88
S_CLEARZONE = 0x00178358
S_FINISH = 0x00182948
S_ARREST = 0x001832f8
S_TICKET = 0x00183308
S_RECORD = 0x0018fcb8
S_START = 0x001b1318
S_STOP = 0x001b1388
S_ADL = 0x001b13e8
S_UNLOAD = 0x001b1658
S_COORD = 0x001b2af0
S_YAW = 0x001c08d0
S_BUST = 0x001e5688
S_FREE = 0x001ee390
S_PURSUED = 0x00227438
S_TICKETS = 0x00228520
S_RAND = 0x0025a3d0
S_ATAN = 0x0025a890

RP_BEACOP, RP_TICKETS = 628, 636
NPL, NCARS, NREC, NA, NATAN = 3, 4, 12, 10, 8
PLAYER_SIZE, CAR_SIZE, NM_SIZE = 2720, 2304, 320

# The player's fields.
P_CB, P_CAR, P_NUM, P_VIEW, P_ZONE = 0, 4, 16, 24, 88
P_FRZ, P_AVG, P_AT, P_MAX = 156, 160, 164, 168
P_TROUBLE, P_PROMPT, P_TS, P_TT = 172, 176, 180, 184
P_COORD, P_AIDX, P_TIDX, P_PARAM, P_NM = 224, 232, 236, 240, 244
P_TN, P_TC, P_AN, P_AC, P_WW, P_NIS = 248, 376, 504, 632, 760, 2560
P_MV, P_LB, P_HANG = 200, 764, 1508
# The camera mover's (CameraMover, then DriveCameraMover's).
MV_TYPE, MV_VT, MV_DLB, MV_SIZE = 8, 40, 124, 144
# Retail's car (its State 64 on, with four more bytes than the demo's
# before nWheelsTouchingGround, and its TrackPathCoordinate 32 on).
C_TYPE, C_PLAYER, C_RC, C_BODY, C_STATE = 12, 24, 28, 52, 64
C_POS, C_VX, C_VY, C_UPZ, C_ANGLE = 96, 112, 116, 184, 932
C_NW, C_FWD, C_VM, C_PDX, C_PDY = 956, 960, 964, 2040, 2044
# The NisManager's, the record's, the rest.
NM_PLAYING, NM_END, NM_NIS, NM_CAM = 68, 76, 80, 84
R_TYPE, R_NUM, R_FRAMES, R_CAMS = 32, 40, 44, 48
B_PEN, T_CLASS, AV_MEAN, RACE_TIME = 260, 230, 8, 16
RT_DLI, PT_SPEEDS = 40, 90


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def F(f):
    return "0x%08x" % fbits(f)


# ================================================================== model

class Model(object):
    def __init__(self):
        e = self.e = retail_model.RetailEmu(ieee=True, eediv=True,
                                            eesqrt=True)
        self.out = []
        self.names = {RP: "RP", G_SEED: "SEED"}

        def block(n, nm):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            if nm:
                self.names[p] = nm
            return p
        self.players = [block(PLAYER_SIZE, "P%d" % k) for k in range(NPL)]
        self.mgrs = [block(NM_SIZE, "M%d" % k) for k in range(NPL)]
        self.avgs = [block(16, "AV%d" % k) for k in range(NPL)]
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.bodies = [block(272, None) for k in range(NCARS)]
        self.types = [block(240, None) for k in range(NCARS)]
        self.rcars = [block(32, None) for k in range(NCARS)]
        self.table = block(160 * NREC, None)
        for k in range(NREC):
            self.names[self.table + 160 * k] = "N%d" % k
        self.cm = block(16, "CM")
        self.pursuit = block(16, "U")
        self.coord = block(16, "NC")
        self.rc = block(16, "RC")
        self.race = block(256, "R")
        self.route = block(40 + 48 * 21 + 8, "RT")
        self.point = block(112, "PT")
        for k in range(NPL):
            self.names[self.players[k] + P_NIS] = "P%d.nis" % k
        for k in range(NCARS):
            self.names[self.cars[k] + C_STATE] = "A%d.st" % k
            self.names[self.cars[k] + C_POS] = "A%d.pos" % k
        self.f_cb = block(16, None)
        # A camera mover per player and a spare, ResetState a stub
        # through the vtable's +88 delta, +92 function.
        self.movers = [block(MV_SIZE, "MV%d" % k)
                       for k in range(NPL + 1)]
        self.mvt = block(128, None)
        self.f_rs = block(16, None)
        e.write(self.mvt + 88, struct.pack("<h", 0))
        e.put32(self.mvt + 92, self.f_rs)
        for addr, fn in ((S_BLUR, self.s_blur),
                         (S_NOBLINK, self.s_noblink),
                         (S_ROUTE, self.s_route),
                         (S_POINT, self.s_point),
                         (S_DEMO, self.s_demo),
                         (S_CAM, self.s_cam),
                         (S_ZONE, self.s_zone),
                         (S_CLEARZONE, self.s_clearzone),
                         (S_FINISH, self.s_finish),
                         (S_ARREST, self.s_arrest),
                         (S_TICKET, self.s_ticket),
                         (S_RECORD, self.s_record),
                         (S_START, self.s_start),
                         (S_STOP, self.s_stop),
                         (S_ADL, self.s_adl),
                         (S_UNLOAD, self.s_unload),
                         (S_COORD, self.s_coord),
                         (S_YAW, self.s_yaw),
                         (S_BUST, self.s_bust),
                         (S_FREE, self.s_free),
                         (S_PURSUED, self.s_pursued),
                         (S_TICKETS, self.s_tickets),
                         (S_RAND, self.s_rand),
                         (S_ATAN, self.s_atan),
                         (self.f_cb, self.s_cb),
                         (self.f_rs, self.s_rs)):
            e.stub(addr, fn)
        self.reset()

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def reset(self):
        e = self.e
        for lst, n in ((self.players, PLAYER_SIZE), (self.mgrs, NM_SIZE),
                       (self.avgs, 16), (self.cars, CAR_SIZE),
                       (self.bodies, 272), (self.types, 240),
                       (self.rcars, 32)):
            for p in lst:
                e.write(p, bytes(n))
        for p, n in ((self.rc, 16), (self.race, 256),
                     (self.route, 40 + 48 * 21 + 8), (self.point, 112),
                     (self.table, 160 * NREC)):
            e.write(p, bytes(n))
        for p in self.movers:
            e.write(p, bytes(MV_SIZE))
            e.put32(p + MV_VT, self.mvt)
        self.rs_mode = [0] * NPL
        e.put32(RP + RP_BEACOP, 0)
        e.put32(RP + RP_TICKETS, 0)
        for k in range(NPL):
            e.put32(self.players[k] + P_NM, self.mgrs[k])
            e.put32(self.players[k] + P_AVG, self.avgs[k])
        for k in range(NCARS):
            e.put32(self.cars[k] + C_BODY, self.bodies[k])
            e.put32(self.cars[k] + C_TYPE, self.types[k])
            e.put32(self.cars[k] + C_RC, self.rcars[k])
        e.put32(G_TABLE, self.table)
        e.put32(G_NTAB, 0)
        e.put32(G_RC, self.rc)
        e.put32(G_RACE, self.race)
        e.put32(G_COPMGR, self.cm)
        e.put32(G_BYIDX, self.players[0])
        e.put32(G_BYIDX + 4, self.players[1])
        e.put32(G_NPL, 2)
        e.put32(G_WT, 0)
        e.put32(G_WTF, 0)
        e.put32(G_WTE, 0)
        e.put32(G_GLARE, 0)
        self.tickets = self.free = self.dbg = self.demo = 0
        self.pursued = self.zone_ok = 0
        self.route_on = self.point_on = 1
        self.avg_next = self.yaw = 0
        self.rnd = 0
        self.atans = []

    # ---- stubs

    def s_tickets(self, em):
        self.emit("  tickets %s %s -> %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.tickets))
        return self.tickets

    def s_clearzone(self, em):
        self.emit("  clearzone %s %d" % (self.sym(em.reg[4]),
                                         s32(em.reg[5])))

    def s_blur(self, em):
        self.emit("  blur %d" % s32(em.reg[4]))

    def s_noblink(self, em):
        self.emit("  noblink %s" % self.sym(em.reg[4]))

    def s_free(self, em):
        self.emit("  freerun %s -> %d" % (self.sym(em.reg[4]), self.free))
        return self.free

    def s_start(self, em):
        m = em.reg[4] & M32
        self.emit("  start %s %d %d %s %s" % (
            self.sym(m), s32(em.reg[5]), s32(em.reg[6]),
            self.sym(em.reg[7]), self.sym(em.reg[8])))
        e = self.e
        e.put32(m + NM_PLAYING, 1)
        e.put32(m + NM_NIS, em.reg[5])
        e.put32(m + NM_CAM, em.reg[6])
        e.put32(m + NM_END, s32(e.u32(G_WTF)) + 30)

    def s_stop(self, em):
        m = em.reg[4] & M32
        self.emit("  stop %s" % self.sym(m))
        self.e.put32(m + NM_PLAYING, 0)

    def s_unload(self, em):
        self.emit("  unload %s" % self.sym(em.reg[4]))

    def s_adl(self, em):
        self.emit("  adl %s -> %d" % (self.sym(em.reg[4]), self.dbg))
        return self.dbg

    def s_ticket(self, em):
        self.emit("  ticket %s" % self.sym(em.reg[4]))

    def s_arrest(self, em):
        self.emit("  arrest %s" % self.sym(em.reg[4]))

    def s_finish(self, em):
        self.emit("  finish %s" % self.sym(em.reg[4]))

    def s_demo(self, em):
        self.emit("  demo %s -> %d" % (self.sym(em.reg[4]), self.demo))
        return self.demo

    def s_cam(self, em):
        self.emit("  cam %s %d %d" % (self.sym(em.reg[4]), s32(em.reg[5]),
                                      s32(em.reg[6])))

    def s_coord(self, em):
        self.emit("  coord %s %d -> NC" % (self.sym(em.reg[4]),
                                           s32(em.reg[5])))
        return self.coord

    def s_rand(self, em):
        rng = s32(em.reg[4])
        self.rnd = (self.rnd * 1103515245 + 12345) & M32
        r = (self.rnd >> 16) % rng if rng > 0 else 0
        self.emit("  rand %d %s -> %d" % (rng, self.sym(em.reg[5]), r))
        return r

    def s_atan(self, em):
        r = self.atans.pop(0) if self.atans else 0
        self.emit("  atan %08x %08x -> %d" % (
            em.fpr[12] & M32, em.fpr[13] & M32, r))
        return r

    def s_yaw(self, em):
        self.emit("  yaw %s -> %08x" % (self.sym(em.reg[4]), self.yaw))
        em.fpr[0] = self.yaw

    def s_pursued(self, em):
        r = self.pursuit if self.pursued else 0
        self.emit("  pursued %s %s -> %s" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(r)))
        return r

    def s_route(self, em):
        r = self.route if self.route_on else 0
        self.emit("  route %s %d -> %s" % (self.sym(em.reg[4]),
                                           s32(em.reg[5]), self.sym(r)))
        return r

    def s_point(self, em):
        r = self.point if self.point_on else 0
        self.emit("  point %s %d -> %s" % (self.sym(em.reg[4]),
                                           s32(em.reg[5]), self.sym(r)))
        return r

    def s_record(self, em):
        a = em.reg[4] & M32
        self.emit("  record %s %08x" % (self.sym(a), em.fpr[12] & M32))
        self.e.put32(a + AV_MEAN, self.avg_next)

    def s_zone(self, em):
        self.emit("  zone %s %d %d %d %d -> %d" % (
            (self.sym(em.reg[4]),) + tuple(s32(em.reg[r])
                                           for r in (5, 6, 7, 8))
            + (self.zone_ok,)))
        return self.zone_ok

    def s_bust(self, em):
        self.emit("  bust %s" % self.sym(em.reg[4]))

    def s_rs(self, em):
        e = self.e
        m = em.reg[4] & M32
        self.emit("  resetstate %s" % self.sym(m))
        for k in range(NPL):
            p = self.players[k]
            if e.u32(p + P_MV) == m:
                mode = self.rs_mode[k]
                if mode == 1:
                    e.put32(p + P_MV, 0)
                elif mode == 2:
                    e.put32(p + P_MV, self.movers[NPL])
                elif mode in (3, 4):
                    e.put32(m + MV_TYPE, mode - 2)
                break

    def s_cb(self, em):
        self.emit("  cb %d" % s32(em.reg[4]))

    # ---- dumps

    def dump(self):
        e = self.e
        self.emit("G glare %d" % s32(e.u32(G_GLARE)))
        for k in range(NPL):
            p = self.players[k]
            cb = e.u32(p + P_CB)
            cbs = "0" if cb == 0 else "cb" if cb == self.f_cb else "?"
            self.emit("P%d cb %s par %d ai %d ti %d coord %s ww %d "
                      "trouble %08x prompt %08x ts %08x tt %08x at %08x "
                      "max %08x frz %08x" % (
                          k, cbs, s32(e.u32(p + P_PARAM)),
                          s32(e.u32(p + P_AIDX)), s32(e.u32(p + P_TIDX)),
                          self.sym(e.u32(p + P_COORD)),
                          s32(e.u32(p + P_WW)), e.u32(p + P_TROUBLE),
                          e.u32(p + P_PROMPT), e.u32(p + P_TS),
                          e.u32(p + P_TT), e.u32(p + P_AT),
                          e.u32(p + P_MAX), e.u32(p + P_FRZ)))
            self.emit("P%d" % k + "".join(
                " %d/%d/%d/%d" % tuple(s32(e.u32(p + off + 4 * j))
                                       for off in (P_TN, P_TC, P_AN, P_AC))
                for j in range(NA)))
            m = self.mgrs[k]
            self.emit("M%d play %d end %d cam %d nis %d" % (
                k, s32(e.u32(m + NM_PLAYING)), s32(e.u32(m + NM_END)),
                s32(e.u32(m + NM_CAM)), s32(e.u32(m + NM_NIS))))
        self.emit("V" + "".join(
            " %s/%d/%08x" % (self.sym(e.u32(p + P_MV)),
                             s32(e.u32(p + P_LB)), e.u32(p + P_HANG))
            for p in self.players) + "".join(
            " %d/%08x" % (s32(e.u32(m + MV_TYPE)), e.u32(m + MV_DLB))
            for m in self.movers))

    # ---- ops

    def idx(self, lst, s):
        k = int(s, 0)
        return lst[k] if k >= 0 else 0

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        sv = lambda j: s32(v(j))                # noqa: E731
        call = lambda f, *args: e.call(f, *args, limit=400000)  # noqa
        if o == "reset":
            self.reset()
            return
        if o == "rec":
            r = self.table + 160 * int(a[1])
            for j, off in enumerate((R_TYPE, R_NUM, R_FRAMES, R_CAMS)):
                e.put32(r + off, v(2 + j))
            return
        if o == "ntab":
            e.put32(G_NTAB, v(1))
            return
        if o == "rp":
            e.put32(RP + (RP_BEACOP if a[1] == "beacop" else RP_TICKETS),
                    v(2))
            return
        if o == "wt":
            e.put32(G_WT, v(1))
            e.put32(G_WTF, v(2))
            e.put32(G_WTE, v(3))
            return
        if o == "rcs":
            e.put32(self.rc, v(1))
            return
        if o == "rtime":
            e.put32(self.race + RACE_TIME, v(1))
            return
        if o == "np":
            e.put32(G_NPL, v(1))
            return
        if o == "byidx":
            e.put32(G_BYIDX + 4 * int(a[1]), self.idx(self.players, a[2]))
            return
        if o == "pl":
            p = self.players[int(a[1])]
            e.put32(p + P_CAR, self.idx(self.cars, a[2]))
            e.put32(p + P_ZONE, v(3))
            e.put32(p + P_NUM, v(4))
            e.put32(p + P_VIEW, v(5))
            e.put32(p + P_AIDX, v(6))
            e.put32(p + P_TIDX, v(7))
            e.put32(p + P_CB, self.f_cb if v(8) else 0)
            e.put32(p + P_PARAM, v(9))
            e.put32(p + P_WW, v(10))
            return
        if o == "pt":
            p = self.players[int(a[1])]
            for j, off in enumerate((P_FRZ, P_AT, P_MAX, P_TROUBLE,
                                     P_PROMPT, P_TS, P_TT)):
                e.put32(p + off, v(2 + j))
            return
        if o == "arr":
            p = self.players[int(a[1])]
            off = (P_TN, P_TC, P_AN, P_AC)[int(a[2])]
            e.put32(p + off + 4 * int(a[3]), v(4))
            return
        if o == "nm":
            m = self.mgrs[int(a[1])]
            for j, off in enumerate((NM_PLAYING, NM_END, NM_CAM, NM_NIS)):
                e.put32(m + off, v(2 + j))
            return
        if o == "car":
            k = int(a[1])
            c = self.cars[k]
            e.put32(c + C_PLAYER, self.idx(self.players, a[2]))
            e.write(c + C_ANGLE, struct.pack("<H", v(3) & 0xffff))
            e.put32(c + C_FWD, v(4))
            e.put32(c + C_VM, v(5))
            e.put32(c + C_NW, v(6))
            e.put32(c + C_VX, v(7))
            e.put32(c + C_VY, v(8))
            e.put32(c + C_UPZ, v(9))
            e.put32(c + C_PDX, v(10))
            e.put32(c + C_PDY, v(11))
            e.write(self.types[k] + T_CLASS, bytes([v(12) & 0xff]))
            e.put32(self.bodies[k] + B_PEN, v(13))
            return
        if o == "dl":
            e.put32(self.route + RT_DLI + 48 * int(a[1]), v(2))
            return
        if o == "sp":
            e.write(self.point + PT_SPEEDS + int(a[1]), bytes([v(2) & 0xff]))
            return
        if o == "mv":
            # mv|k|on|type|lb|dlb|hang|mode
            k = int(a[1])
            p, m = self.players[k], self.movers[k]
            e.put32(p + P_MV, m if v(2) else 0)
            e.put32(m + MV_TYPE, v(3))
            e.put32(p + P_LB, v(4))
            e.put32(m + MV_DLB, v(5))
            e.put32(p + P_HANG, v(6))
            self.rs_mode[k] = sv(7)
            return
        if o == "mvx":
            m = self.movers[NPL]
            e.put32(m + MV_TYPE, v(1))
            e.put32(m + MV_DLB, v(2))
            return
        if o == "atan":
            self.atans = [sv(j) for j in range(1, min(len(a), NATAN + 1))]
            return
        if o == "set":
            f, x = a[1], v(2)
            if f == "copm":
                e.put32(G_COPMGR, self.cm if x else 0)
            elif f == "glare":
                e.put32(G_GLARE, x)
            elif f == "seed":
                self.rnd = x
            elif f == "avg":
                self.avg_next = x
            elif f == "yaw":
                self.yaw = x
            elif f in ("route", "point"):
                setattr(self, f + "_on", x)
            elif f == "zone":
                self.zone_ok = s32(x)
            elif f in ("tickets", "free", "dbg", "demo", "pursued"):
                setattr(self, f, s32(x))
            else:
                raise ValueError(f)
            return

        if o == "crna":
            self.emit("crna P%s %d" % (a[1], int(a[2], 0)))
            call(F_CRNA, self.players[int(a[1])], sv(2))
        elif o == "pnn":
            self.emit("pnn P%s A%s A%s %s %d" % (
                a[1], a[2], a[3], "cb" if v(4) else "0", sv(5)))
            r = call(F_PNN, self.players[int(a[1])], self.cars[int(a[2])],
                     self.cars[int(a[3])], self.f_cb if v(4) else 0, sv(5))
            self.emit("  -> %d" % r)
        elif o == "svc":
            self.emit("svc P%s" % a[1])
            call(F_SVC, self.players[int(a[1])])
        elif o == "dww":
            self.emit("dww P%s %d" % (a[1], int(a[2], 0)))
            r = call(F_DWW, self.players[int(a[1])], sv(2))
            self.emit("  -> %d" % r)
        elif o == "iar":
            self.emit("iar P%s" % a[1])
            r = call(F_IAR, self.players[int(a[1])])
            self.emit("  -> %d" % r)
        elif o == "ctdr":
            self.emit("ctdr P%s" % a[1])
            call(F_CTDR, self.players[int(a[1])])
        elif o == "ugs":
            self.emit("ugs P%s" % a[1])
            call(F_UGS, self.players[int(a[1])])
        elif o == "upgs":
            self.emit("upgs")
            call(F_UPGS)
        elif o == "psr":
            self.emit("psr P%s" % a[1])
            call(F_PSR, self.players[int(a[1])])
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

TICKET, ARREST = 1, 2
MPH = 2.237


def car(k, player=-1, angle=0, fwd=0.0, vm=0.0, nw=4, vx=0.0, vy=0.0,
        upz=1.0, pdx=1.0, pdy=0.0, cls=0, pen=0):
    return "car|%d|%d|%d|%s|%s|%d|%s|%s|%s|%s|%s|%d|%d" % (
        k, player, angle, F(fwd), F(vm), nw, F(vx), F(vy), F(upz), F(pdx),
        F(pdy), cls, pen)


def pl(k, carn=None, zone=0, pnum=None, view=None, aidx=0, tidx=0, cb=0,
       param=0, ww=0):
    return "pl|%d|%d|%d|%d|%d|%d|%d|%d|%d|%d" % (
        k, k if carn is None else carn, zone, k if pnum is None else pnum,
        10 + k if view is None else view, aidx, tidx, cb, param, ww)


def pt(k, frz=0.0, at=0, mx=0.0, trouble=0, prompt=0, ts=0.0, tt=0):
    return "pt|%d|%s|%d|%s|%d|%d|%s|%d" % (k, F(frz), at & M32, F(mx),
                                           trouble & M32, prompt & M32,
                                           F(ts), tt & M32)


def wt(timer=0, frames=0, elapsed=0.0):
    return "wt|%d|%d|%s" % (timer & M32, frames & M32, F(elapsed))


DISC = [(ARREST, 0, 121, 2), (ARREST, 1, 154, 3), (ARREST, 2, 149, 3),
        (TICKET, 3, 141, 3), (TICKET, 4, 141, 2), (TICKET, 5, 141, 3),
        (TICKET, 6, 141, 3), (TICKET, 7, 141, 3)]


def table(recs):
    return (["rec|%d|%d|%d|%d|%d" % ((i,) + r) for i, r in enumerate(recs)]
            + ["ntab|%d" % len(recs)])


def base(recs=DISC):
    return (["reset"] + table(recs)
            + [pl(0), pl(1), pl(2), car(0, 0), car(1, 1), car(2, 2),
               car(3, -1)])


def rand_table(rng, n=None, cams0=False):
    n = rng.randrange(0, NREC + 1) if n is None else n
    lo = 0 if cams0 else 1
    return [(rng.choice((TICKET, ARREST, TICKET, ARREST, 0, 3)),
             rng.randrange(n) if n else 0, rng.randrange(1, 200),
             rng.randrange(lo, 5)) for _ in range(n)]


def crna_cases(rng):
    out = []
    for typ in (TICKET, ARREST, 0, 3, -1):
        for seed in (0, 1, 0x12345678, 0xffffffff):
            for who in (0, 2):
                out += base() + ["set|seed|%d" % seed,
                                 "crna|%d|%d" % (who, typ)]
    # Both arrays filled, one after the other, on the same seed run.
    for seed in range(20):
        out += base() + ["set|seed|%d" % (seed * 7919),
                         "crna|0|%d" % TICKET, "crna|0|%d" % ARREST,
                         "crna|1|%d" % ARREST, "crna|1|%d" % TICKET]
    # Tables of every shape, some with NISes of no cameras.
    for _ in range(300):
        recs = rand_table(rng, cams0=True)
        out += base(recs) + ["set|seed|%d" % rng.randrange(1 << 32)]
        # What was there before is kept past the count.
        for j in range(NA):
            out.append("arr|0|%d|%d|%d" % (rng.randrange(4), j,
                                           rng.randrange(-3, 50)))
        out.append("crna|0|%d" % rng.choice((TICKET, ARREST, 0, 3)))
    return out


def pnn_world(rng, recs):
    """A world where any NIS PlayNextNis can pick is in the table and has
    cameras."""
    n = len(recs)
    out = base(recs)
    for k in range(NPL):
        for w in range(4):
            for j in range(NA):
                if w in (0, 2):
                    x = rng.randrange(n)
                else:
                    x = rng.randrange(-1, 6)
                out.append("arr|%d|%d|%d|%d" % (k, w, j, x))
    return out


def pnn_cases(rng):
    out = []
    recs = DISC
    # Ticket or arrest: the tickets against the limit, a free run.
    for tickets in (0, 1, 2, 3, 4, -1):
        for limit in (0, 1, 3, 0x7fffffff):
            for free in (0, 1):
                out += pnn_world(rng, recs) + [
                    "set|tickets|%d" % tickets, "rp|tickets|%d" % limit,
                    "set|free|%d" % free,
                    pl(0, aidx=1, tidx=2), "pnn|0|0|3|1|%d" % tickets]
    # The indices: negative ones go to 0, the arrest's reads TicketNisIndex.
    for aidx in (-5, -1, 0, 1, 9):
        for tidx in (-7, -1, 0, 3, 9):
            for arrest in (0, 1):
                out += pnn_world(rng, recs) + [
                    pl(1, aidx=aidx, tidx=tidx, cb=1, param=7),
                    "set|tickets|%d" % (5 if arrest else 0),
                    "rp|tickets|3", "pnn|1|1|3|1|-2"]
    # The other player's camera: P0's other is P1, P1's and P2's are P0;
    # a missing other, an other without a playing NIS, a clash.
    for who in (0, 1, 2):
        for other_null in (0, 1):
            for playing in (0, 1):
                for clash in (0, 1):
                    w = pnn_world(rng, recs)
                    me = who
                    other = 1 if who == 0 else 0
                    cam = rng.randrange(4)
                    w += ["arr|%d|1|0|%d" % (me, cam),
                          "arr|%d|0|0|%d" % (me, rng.randrange(3, 8)),
                          pl(me, tidx=0), "rp|tickets|3",
                          "nm|%d|%d|99|%d|5" % (other, playing,
                                                cam if clash else cam + 9)]
                    if other_null:
                        w.append("byidx|%d|-1" % (0 if who != 0 else 1))
                    out += w + ["pnn|%d|%d|3|0|0" % (me, me)]
    # The wrap: the camera past the last goes to 0.
    for cams in (1, 2, 3, 4):
        for cam in range(cams + 1):
            r = [(TICKET, 0, 141, cams), (ARREST, 1, 121, cams)]
            for arrest in (0, 1):
                out += base(r) + [
                    "arr|0|1|0|%d" % cam, "arr|0|0|0|0", "arr|0|3|0|%d" % cam,
                    "arr|0|2|0|1", "nm|1|1|0|%d|0" % cam,
                    "set|tickets|%d" % arrest, "rp|tickets|1",
                    "pnn|0|0|3|1|1"]
    # The cop's player, its blur; the replays keep the camera.
    for cop_player in (-1, 1, 2):
        for st in range(10):
            for demo in (0, 1):
                out += pnn_world(rng, recs) + [
                    car(3, cop_player), "rcs|%d" % st,
                    "set|demo|%d" % demo, "pnn|0|0|3|1|3"]
    # At random.
    for _ in range(300):
        recs = rand_table(rng, rng.randrange(1, NREC + 1))
        out += pnn_world(rng, recs)
        for k in range(NPL):
            out.append(pl(k, aidx=rng.randrange(-2, NA),
                          tidx=rng.randrange(-2, NA),
                          cb=rng.randrange(2), param=rng.randrange(-9, 9)))
            out.append("nm|%d|%d|%d|%d|%d" % (
                k, rng.randrange(2), rng.randrange(100),
                rng.randrange(-1, 5), rng.randrange(8)))
        out += ["set|tickets|%d" % rng.randrange(-1, 6),
                "rp|tickets|%d" % rng.randrange(0, 5),
                "set|free|%d" % rng.randrange(2),
                "set|glare|%d" % rng.randrange(2),
                car(3, rng.choice((-1, 0, 1, 2))),
                "rcs|%d" % rng.randrange(10), "set|demo|%d" % rng.randrange(2)]
        if rng.random() < 0.2:
            out.append("byidx|%d|%d" % (rng.randrange(2),
                                        rng.choice((-1, 0, 1, 2))))
        who = rng.randrange(NPL)
        out.append("pnn|%d|%d|%d|%d|%d" % (
            who, rng.randrange(NCARS), rng.randrange(NCARS),
            rng.randrange(2), rng.randrange(-100, 100)))
    return out


def svc_cases(rng):
    out = []
    for playing in (0, 1):
        for dbg in (0, 1):
            for end in (-1, 0, 1, 50):
                for cb in (0, 1):
                    out += base() + [
                        wt(0, 0), "set|dbg|%d" % dbg,
                        "nm|0|%d|%d|2|4" % (playing, end),
                        pl(0, cb=cb, param=-3), "svc|0"]
    for st in range(10):
        for demo in (0, 1):
            out += base() + [wt(5, 100), "nm|1|1|100|1|1", pl(1, cb=1,
                                                               param=9),
                             "rcs|%d" % st, "set|demo|%d" % demo, "svc|1"]
    for _ in range(200):
        k = rng.randrange(NPL)
        out += base() + [
            wt(rng.randrange(1 << 20), rng.randrange(-5, 300)),
            "nm|%d|%d|%d|%d|%d" % (k, rng.randrange(2),
                                   rng.randrange(-5, 300),
                                   rng.randrange(4), rng.randrange(8)),
            pl(k, cb=rng.randrange(2), param=rng.randrange(-50, 50)),
            "set|dbg|%d" % (rng.random() < 0.2),
            "rcs|%d" % rng.randrange(10), "set|demo|%d" % rng.randrange(2),
            "svc|%d" % k]
    return out


def near(rng, x):
    """x, or a float a few steps either side of it."""
    b = fbits(x) + rng.randrange(-3, 4)
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def dww_cases(rng):
    out = []
    lim = 10.0 / MPH
    # The fold's edges: the heading straight on, the limit, half a turn.
    for d in (0, 1, 18203, 18204, 18205, 20023, 20024, 20025, 32767, 32768,
              32769, 45511, 45512, 45513, 47331, 47332, 47333, 65535):
        for was in (0, 1):
            for fast in (0, 1):
                for hd in (0, 20023, 20024, 45513, 45512, 32768):
                    path = 0x4000
                    angle = (path - d) & 0xffff
                    out += base() + [
                        car(0, 0, angle=angle,
                            fwd=(lim * 1.5 if fast else lim * 0.5),
                            nw=rng.choice((3, 4)), vx=1.5, vy=-2.5,
                            pdx=0.25, pdy=0.75),
                        "atan|%d|%d" % (path, (path - hd) & 0xffff),
                        "dww|0|%d" % was]
    # The speed's edge, either way.
    for f in (lim, -lim, 0.0, 4.4703, -4.4703):
        for _ in range(4):
            for was in (0, 1):
                out += base() + [
                    car(1, 1, angle=0x8000, fwd=near(rng, f),
                        nw=rng.randrange(6)),
                    "atan|0|%d" % rng.randrange(65536), "dww|1|%d" % was]
    # bATan's high bits: the path's are masked, the velocity's wrap.
    for path in (0x10000, 0x1ffff, 0xffff8000 - (1 << 32)):
        for hd in (0x18000, -1, 0x7fff):
            out += base() + [car(0, 0, angle=0, fwd=20.0, nw=4),
                             "atan|%d|%d" % (path, hd), "dww|0|0"]
    for _ in range(400):
        out += base() + [
            car(2, 2, angle=rng.randrange(65536),
                fwd=rng.uniform(-3 * lim, 3 * lim), nw=rng.randrange(5),
                vx=rng.uniform(-50, 50), vy=rng.uniform(-50, 50),
                pdx=rng.uniform(-1, 1), pdy=rng.uniform(-1, 1)),
            "atan|%d|%d" % (rng.randrange(0x20000), rng.randrange(0x20000)),
            "dww|2|%d" % rng.choice((0, 1, 2, -1))]
    return out


def iar_cases(rng):
    out = []
    lim = 60.0 / MPH
    for zone in range(8):
        for playing in (0, 1):
            out += base() + [pl(0, zone=zone), "nm|0|%d|0|0|0" % playing,
                             "iar|0"]
    for _ in range(6):
        for f in (lim, 0.0, 30.0):
            out += base() + [car(1, 1, vm=near(rng, f)), "iar|1"]
    for t in (0, 1, 19998, 19999, 20000, 20001, 20002, 0x7fffffff,
              0x80000000, 0xffffffff, 400000):
        for bac in (0, 1, 2):
            out += base() + ["rp|beacop|%d" % bac, "rtime|%d" % t, "iar|2"]
    for _ in range(200):
        out += base() + [
            pl(0, zone=rng.randrange(8)),
            "nm|0|%d|0|0|0" % (rng.random() < 0.3),
            car(0, 0, vm=rng.uniform(0, 2 * lim)),
            "rp|beacop|%d" % rng.randrange(2),
            "rtime|%d" % rng.randrange(0, 40000), "iar|0"]
    return out


def ctdr_world(rng, k, now):
    """Player k's car and timers near the trouble watch's edges, WorldTimer
    at `now`."""
    lim60, lim10 = 60.0 / MPH, 10.0 / MPH
    vm = rng.choice((near(rng, lim60), near(rng, lim10), rng.uniform(0, 60),
                     0.0, 40.0))
    pen = now - rng.choice((0, 11999, 12000, 12001, rng.randrange(40000)))
    upz = rng.choice((1.0, -0.0, -0.5, 0.25, -1e-30))
    yaw = rng.choice((50 / 57.2957763671875, -50 / 57.2957763671875, 0.0,
                      2.0, -2.0, rng.uniform(-2, 2)))
    yaw = near(rng, yaw)
    tt = now - rng.choice((0, 1999, 2000, 2001, 4000, rng.randrange(20000)))
    ts = rng.choice((near(rng, 60.0), 0.0, 80.0, 61.0, rng.uniform(0, 140)))
    trouble = rng.choice((0, 0x7fffffff, now, now - 19999, now - 20000,
                          now - 20001, now - 20002, now - 1,
                          rng.randrange(1 << 32)))
    prompt = rng.choice((0, 0x7fffffff, now, now - 11999, now - 12000,
                         now - 12001, now - 12002, rng.randrange(1 << 32)))
    return [car(k, k, vm=vm, pen=pen & M32, upz=upz,
                fwd=rng.uniform(-30, 30)),
            "set|yaw|0x%08x" % fbits(yaw),
            pt(k, trouble=trouble, prompt=prompt, ts=ts, tt=tt)]


def ctdr_cases(rng):
    out = []
    for _ in range(1500):
        now = rng.choice((0, 50000, 0x7fff0000, 0x80010000,
                          rng.randrange(1 << 31)))
        k = rng.randrange(NPL)
        out += base() + [wt(now, 0)] + ctdr_world(rng, k, now)
        out += [pl(k, zone=rng.choice((0, 0, 3, 6))),
                "nm|%d|%d|0|0|0" % (k, rng.random() < 0.15),
                "rp|beacop|%d" % (rng.random() < 0.2),
                "rtime|%d" % rng.choice((0, 30000)),
                "set|copm|%d" % (rng.random() < 0.8),
                "set|pursued|%d" % (rng.random() < 0.4),
                "ctdr|%d" % k]
    return out


def ugs_world(rng, k):
    out = []
    wte = rng.choice((1 / 30.0, 1 / 60.0, 0.0, 0.25))
    out.append(wt(rng.randrange(1 << 24), rng.randrange(1000), wte))
    tick = int(wte * 4000 + 0.5)
    at = rng.choice((0, tick - 1, tick, tick + 1, 4000, -5))
    frz = rng.choice((0.0, -1.0, near(rng, wte), wte * 2, 3.0))
    out.append(pt(k, frz=frz, at=at, mx=rng.choice((0.0, 0.5, 1.5)),
                  trouble=0, prompt=0, ts=0.0, tt=0))
    cls = rng.randrange(0, 11)
    out.append(pl(k, ww=rng.randrange(2)))
    out.append(car(k, k, vm=rng.choice((0.0, 30.0, 55.5)), cls=cls,
                   angle=rng.randrange(65536), fwd=rng.uniform(-20, 20)))
    out.append("atan|%d|%d" % (rng.randrange(65536), rng.randrange(65536)))
    if True:
        out.append("dl|%d|%d" % (cls * 2, rng.randrange(8)))
        out.append("sp|%d|%d" % (cls * 2, rng.choice((0, 1, 60, 255))))
    out += ["set|route|%d" % (rng.random() < 0.85),
            "set|point|%d" % (rng.random() < 0.85),
            "set|avg|0x%08x" % fbits(rng.choice((0.25, 1.0, 2.0, 0.0))),
            "set|zone|%d" % rng.randrange(2),
            "rcs|%d" % rng.randrange(10), "set|demo|%d" % (rng.random() < 0.2)]
    return out


def ugs_cases(rng):
    out = []
    for st in range(10):
        for demo in (0, 1):
            for at in (0, 133, 134, 4000):
                out += base() + [wt(1000, 10, 1 / 30.0),
                                 pt(0, at=at, mx=0.5), "dl|0|1", "sp|0|50",
                                 car(0, 0, vm=25.0),
                                 "set|avg|0x%08x" % fbits(0.75),
                                 "rcs|%d" % st, "set|demo|%d" % demo,
                                 "ugs|0"]
    for flags in range(8):
        for speed in (0, 1, 100, 255):
            out += base() + [wt(1000, 10, 1 / 30.0), pt(1, at=0),
                             car(1, 1, vm=30.0, cls=3),
                             "dl|6|%d" % flags, "sp|6|%d" % speed,
                             "rcs|3", "ugs|1"]
    for frz in (0.0, -0.5, 1 / 30.0, 0.05, 2.0):
        for zone in (0, 1):
            out += base() + [wt(0, 0, 1 / 30.0), pt(2, frz=frz, at=4000),
                             "set|zone|%d" % zone, "ugs|2"]
    for _ in range(400):
        k = rng.randrange(NPL)
        out += base() + ugs_world(rng, k) + ["ugs|%d" % k]
    return out


def upgs_cases(rng):
    out = []
    for npl in (-1, 0, 1, 2):
        out += base() + [wt(100, 5, 1 / 30.0), "rcs|3", "np|%d" % npl,
                         "upgs"]
    out += base() + ["byidx|0|2", "byidx|1|0", "upgs"]
    return out


def mv(k, on=1, typ=1, lb=0, dlb=0.5, hang=3.25, mode=0):
    return "mv|%d|%d|%d|%d|%s|%s|%d" % (k, on, typ, lb & M32, F(dlb),
                                      F(hang), mode)


def psr_cases(rng):
    """The reset button: the prompt and trouble timers, the camera's
    ResetState, its look back again, HangTime."""
    out = []
    for on in (0, 1):
        for typ in (0, 1, 2, 5):
            for lb in (0, 1, 2, -1):
                for mode in range(5):
                    out += base() + [
                        pt(0, trouble=12345, prompt=777),
                        "mvx|%d|%s" % (rng.choice((0, 1, 2)), F(0.25)),
                        mv(0, on, typ, lb, mode=mode), "psr|0"]
    for _ in range(150):
        k = rng.randrange(NPL)
        out += base() + [
            pt(k, trouble=rng.randrange(1 << 32),
               prompt=rng.randrange(1 << 32)),
            "mvx|%d|%s" % (rng.randrange(4), F(rng.uniform(-2, 2))),
            mv(k, rng.randrange(2), rng.randrange(4), rng.randrange(3),
               rng.uniform(-2, 2), rng.uniform(0, 9), rng.randrange(5)),
            "psr|%d" % k]
        if rng.random() < 0.5:
            out.append("psr|%d" % k)
    return out


def sequences(rng):
    """Races: the two players' NISes picked at the start, then frames of
    world time with pullovers played and serviced to their end."""
    out = []
    for run in range(40):
        recs = DISC if run % 2 == 0 else rand_table(rng,
                                                    rng.randrange(2, 9))
        out += base(recs) + ["set|seed|%d" % rng.randrange(1 << 32),
                             "rcs|3", "rp|tickets|%d" % rng.randrange(1, 4)]
        for k in (0, 1):
            out += ["crna|%d|%d" % (k, TICKET), "crna|%d|%d" % (k, ARREST)]
        now, frames = 0, 0
        for step in range(rng.randrange(20, 60)):
            now += rng.choice((133, 134, 266))
            frames += rng.choice((1, 2))
            out.append(wt(now, frames, 1 / 30.0))
            k = rng.randrange(2)
            r = rng.random()
            if r < 0.15:
                out += ["set|tickets|%d" % rng.randrange(5),
                        pl(k, aidx=rng.randrange(3), tidx=rng.randrange(3),
                           cb=0),
                        "pnn|%d|%d|3|1|%d" % (k, k, rng.randrange(5))]
            elif r < 0.5:
                out += ctdr_world(rng, k, now)
            if rng.random() < 0.1:
                out.append("rcs|%d" % rng.choice((3, 3, 4, 7)))
            out.append("upgs")
    return out


def script():
    return (crna_cases(random.Random(0xa1)) + pnn_cases(random.Random(0xa2))
            + svc_cases(random.Random(0xa3)) + dww_cases(random.Random(0xa4))
            + iar_cases(random.Random(0xa5)) + ctdr_cases(random.Random(0xa6))
            + ugs_cases(random.Random(0xa7)) + upgs_cases(random.Random(0xa8))
            + psr_cases(random.Random(0xaa))
            + sequences(random.Random(0xa9)))


# ================================================================= running

def build_harness(tmp, name="playernis_test"):
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

P = PN
MUTATIONS = [
    # ---- PlayerSelectedReset
    ("psr-prompt", P, "    p->TimeToDisplayResetPrompt.PackedTime = 0;" + NL
     + "    p->LastTimeCarInTrouble.PackedTime = 0;" + NL + "    m = ",
     "    p->LastTimeCarInTrouble.PackedTime = 0;" + NL + "    m = "),
    ("psr-trouble", P, "    p->LastTimeCarInTrouble.PackedTime = 0;" + NL
     + "    m = ", "    m = "),
    ("psr-call", P, "        m->vtbl->ResetState(m);" + NL, ""),
    ("psr-reread", P, "        m = p->pCameraMover;" + NL
     + "        if (m != NULL && m->Type == CM_DRIVE)",
     "        if (m != NULL && m->Type == CM_DRIVE)"),
    ("psr-type", P, "m->Type == CM_DRIVE)", "m->Type != CM_NONE)"),
    ("psr-lb", P, "p->bLookBack ? 1.0f : 0.0f;", "1.0f;"),
    ("psr-lb0", P, "p->bLookBack ? 1.0f : 0.0f;", "0.0f;"),
    ("psr-hang", P, "    p->HangTime = 0.0f;" + NL, ""),
    ("psr-hang-in", P, "    }" + NL + "    p->HangTime = 0.0f;" + NL,
     "        p->HangTime = 0.0f;" + NL + "    }" + NL),
    # ---- the constants
    ("k_mph", P, "#define MPH_PER_MPS     2.237f", "#define MPH_PER_MPS     2.2f"),
    ("k_deg", P, "#define DEG_PER_RAD     57.2957763671875f",
     "#define DEG_PER_RAD     57.0f"),
    ("k_tick", P, "#define SECONDS_PER_TICK 0.00025f",
     "#define SECONDS_PER_TICK 0.001f"),
    ("k_half", P, "#define HALF_TURN       32768u",
     "#define HALF_TURN       32767u"),
    ("k_slack", P, "#define WRONG_WAY_SLACK 1820u",
     "#define WRONG_WAY_SLACK 1819u"),
    ("k_limit", P, "#define WRONG_WAY_LIMIT 20024u",
     "#define WRONG_WAY_LIMIT 20025u"),
    # ---- the helpers
    ("r_inst", P, "    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE",
     "    return s == RCSTATE_PAUSE || s == RCSTATE_POSTRACE"),
    ("r_post", P, "    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE",
     "    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_AI_DEMO_MODE"),
    ("r_auto", P, "        || s == RCSTATE_AUTO_REPLAY\n",
     "        || s == RCSTATE_PRERACE\n"),
    ("r_demo", P, "\n        || racecoordinator_is_replay_demo_mode(pRaceCoordinator);",
     ";"),
    ("t_sign", P, "    return (int32_t)((uint32_t)WorldTimer - t->PackedTime);",
     "    return (int32_t)(t->PackedTime - (uint32_t)WorldTimer);"),
    ("n_play", P, "    return p->pNisManager != NULL && p->pNisManager->Playing != 0;",
     "    return p->pNisManager != NULL;"),
    # ---- CreateRandomNisArray
    ("c_n", P, "    n = get_num_nis_info(type);",
     "    n = get_num_nis_info(NIS_TYPE_TICKET);"),
    ("c_bytype", P, "        NisInfo *info = get_nis_info_by_type(i, type);",
     "        NisInfo *info = get_nis_info(i);"),
    ("c_fallback", P, "            info = get_nis_info_by_type(0, NIS_TYPE_TICKET);",
     "            info = get_nis_info_by_type(1, NIS_TYPE_TICKET);"),
    ("c_pool", P, "        pool[i] = info->NisNumber;", "        pool[i] = i;"),
    ("c_dest", P, "    if (type != NIS_TYPE_TICKET) {",
     "    if (type == NIS_TYPE_ARREST) {"),
    ("c_dest_cam", P, "        nis = p->ArrestNisNumbers;\n        cam = p->ArrestCameraNumbers;",
     "        nis = p->ArrestNisNumbers;\n        cam = p->TicketCameraNumbers;"),
    ("c_range", P, "        int32_t r = bRandomI(n - k, &bDefaultSeed);",
     "        int32_t r = bRandomI(n, &bDefaultSeed);"),
    ("c_seed", P, "        int32_t r = bRandomI(n - k, &bDefaultSeed);",
     "        int32_t r = bRandomI(n - k, (uint32_t *)pool);"),
    ("c_left", P, "        int32_t left = r + 1;", "        int32_t left = r;"),
    ("c_skip", P, "            if (pool[i] != -1)\n                left--;",
     "            left--;"),
    ("c_mark", P, "        pool[pick] = -1;", "        pool[pick] = -2;"),
    ("c_take", P, "        nis[k] = pool[pick];", "        nis[k] = pool[k];"),
    ("c_cams", P, "        cam[k] = bRandomI(get_nis_info(nis[k])->NumCameras,",
     "        cam[k] = bRandomI(get_nis_info(nis[k])->NumFrames,"),
    # ---- PlayNextNis
    ("p_cb", P, "    p->NisFinishedCallback = done;\n    p->NisFinishedCallbackParam",
     "    p->NisFinishedCallbackParam"),
    ("p_param", P, "    p->NisFinishedCallbackParam = (uint32_t)param;\n    tickets",
     "    p->NisFinishedCallbackParam = 0;\n    tickets"),
    ("p_tickets", P, "copmanager_get_num_tickets(pCopManager, car);",
     "copmanager_get_num_tickets(pCopManager, cop);"),
    ("p_clear", P, "    player_clear_zone(p, 1);", "    player_clear_zone(p, 0);"),
    ("p_blur_if", P, "    if (cop->pPlayer != NULL && gRadialBlurOffFn != NULL)",
     "    if (car->pPlayer != NULL && gRadialBlurOffFn != NULL)"),
    ("p_blur_who", P, "        gRadialBlurOffFn(cop->pPlayer->PlayerNumber);",
     "        gRadialBlurOffFn(p->PlayerNumber);"),
    ("p_blink", P, "    car_stop_blinking(car);", "    car_stop_blinking(cop);"),
    ("p_glare", P, "    bResetGlare = 1;", "    bResetGlare = 0;"),
    ("p_aidx", P, "    if (p->ArrestNisIndex < 0)", "    if (p->ArrestNisIndex < -1)"),
    ("p_tidx", P, "    if (p->TicketNisIndex < 0)", "    if (p->TicketNisIndex < -1)"),
    ("p_other", P, "    other = p != PlayerPlayersByIndex[0] ? PlayerPlayersByIndex[0]",
     "    other = p == PlayerPlayersByIndex[0] ? PlayerPlayersByIndex[0]"),
    ("p_other_play", P, "\n        && other->pNisManager->Playing != 0)", ")"),
    ("p_othercam", P, "        othercam = other->pNisManager->CamNumber;",
     "        othercam = other->pNisManager->NisNumber;"),
    ("p_none", P, "    othercam = -1;", "    othercam = 0;"),
    ("p_free", P, "    if (!race_parameters_is_free_run(&TheRaceParameters)",
     "    if (race_parameters_is_free_run(&TheRaceParameters)"),
    ("p_ge", P, "        && tickets >= TheRaceParameters.nNumTicketsBeforeArrest) {",
     "        && tickets > TheRaceParameters.nNumTicketsBeforeArrest) {"),
    ("p_acam_idx", P, "        cam = p->ArrestCameraNumbers[p->TicketNisIndex];",
     "        cam = p->ArrestCameraNumbers[p->ArrestNisIndex];"),
    ("p_anis_idx", P, "        nis = p->ArrestNisNumbers[p->TicketNisIndex];",
     "        nis = p->ArrestNisNumbers[p->ArrestNisIndex];"),
    ("p_acam_arr", P, "        cam = p->ArrestCameraNumbers[p->TicketNisIndex];",
     "        cam = p->TicketCameraNumbers[p->TicketNisIndex];"),
    ("p_tnis_arr", P, "        nis = p->TicketNisNumbers[p->TicketNisIndex];",
     "        nis = p->ArrestNisNumbers[p->TicketNisIndex];"),
    ("p_clash", P, "    if (cam == othercam)", "    if (cam != othercam)"),
    ("p_wrap", P, "        cam = (cam + 1) % get_nis_info(nis)->NumCameras;",
     "        cam = cam % get_nis_info(nis)->NumCameras;"),
    ("p_start", P, "    nismanager_start(p->pNisManager, nis, cam, car, cop);",
     "    nismanager_start(p->pNisManager, nis, cam, cop, car);"),
    ("p_overlay", P, "    if (ticket)\n        nisoverlay_start_ticket",
     "    if (!ticket)\n        nisoverlay_start_ticket"),
    ("p_replay", P, "    if (!replaying() && gNisCreateCameraCoordinatorFn != NULL) {",
     "    if (gNisCreateCameraCoordinatorFn != NULL) {"),
    ("p_camnone", P, "        player_change_camera_mover(p, CM_NONE, 0);\n"
     "        p->pNisCameraCoordinator =\n",
     "        player_change_camera_mover(p, CM_DRIVE, 0);\n"
     "        p->pNisCameraCoordinator =\n"),
    ("p_view", P, "            gNisCreateCameraCoordinatorFn(p->pNisManager, p->ViewID);",
     "            gNisCreateCameraCoordinatorFn(p->pNisManager, p->PlayerNumber);"),
    ("p_coord", P, "        p->pNisCameraCoordinator =\n"
     "            gNisCreateCameraCoordinatorFn(p->pNisManager, p->ViewID);",
     "        (void)gNisCreateCameraCoordinatorFn(p->pNisManager, p->ViewID);"),
    ("p_ret", P, "    return 1;\n}\n\nvoid player_service_nis",
     "    return 0;\n}\n\nvoid player_service_nis"),
    # ---- ServiceNis
    ("s_playing", P, "    if (m == NULL || m->Playing == 0)\n        return;",
     "    if (m == NULL)\n        return;"),
    ("s_dbg", P, "    if (nismanager_allow_debug_looping(m)) {",
     "    if (!nismanager_allow_debug_looping(m)) {"),
    ("s_dbg_cam", P, "        player_change_camera_mover(p, CM_NONE, 0);\n"
     "        p->pNisCameraCoordinator = gNisCreateCameraCoordinatorFn",
     "        player_change_camera_mover(p, CM_DRIVE, 0);\n"
     "        p->pNisCameraCoordinator = gNisCreateCameraCoordinatorFn"),
    ("s_dbg_view", P, "            ? gNisCreateCameraCoordinatorFn(m, p->ViewID) : NULL;",
     "            ? gNisCreateCameraCoordinatorFn(m, 0) : NULL;"),
    ("s_end", P, "    if (m->Playing == 0 || WorldTimeFrames < m->EndTime)",
     "    if (m->Playing == 0 || WorldTimeFrames <= m->EndTime)"),
    ("s_replay", P, "    if (!replaying())\n        player_change_camera_mover(p, CM_DRIVE, 0);",
     "    if (replaying())\n        player_change_camera_mover(p, CM_DRIVE, 0);"),
    ("s_drive", P, "        player_change_camera_mover(p, CM_DRIVE, 0);\n    nismanager_stop",
     "        player_change_camera_mover(p, CM_NONE, 0);\n    nismanager_stop"),
    ("s_stop", P, "    nismanager_stop(p->pNisManager);\n    if (p->NisFinishedCallback",
     "    if (p->NisFinishedCallback"),
    ("s_cb_param", P, "        p->NisFinishedCallback((int32_t)p->NisFinishedCallbackParam);",
     "        p->NisFinishedCallback(0);"),
    ("s_cb_clear", P, "        p->NisFinishedCallback = NULL;\n"
     "        p->NisFinishedCallbackParam = 0;\n    }\n    nismanager_unload",
     "        p->NisFinishedCallbackParam = 0;\n    }\n    nismanager_unload"),
    ("s_param_clear", P, "        p->NisFinishedCallback = NULL;\n"
     "        p->NisFinishedCallbackParam = 0;\n    }\n    nismanager_unload",
     "        p->NisFinishedCallback = NULL;\n    }\n    nismanager_unload"),
    ("s_unload", P, "    nismanager_unload(p->pNisManager);\n", ""),
    ("s_finish", P, "    nisoverlay_finish(&p->mFlailerNIS);\n", ""),
    # ---- DetectWrongWay
    ("f_mask", P, "    uint32_t d = (a - b) & 0xffffu;",
     "    uint32_t d = (a - b) & 0x7fffu;"),
    ("f_gt", P, "    if (d > HALF_TURN)", "    if (d < HALF_TURN)"),
    ("f_neg", P, "        d = (0u - d) & 0xffffu;", "        d = (65535u - d) & 0xffffu;"),
    ("f_was", P, "    if (was)\n        d = (d + WRONG_WAY_SLACK)",
     "    if (!was)\n        d = (d + WRONG_WAY_SLACK)"),
    ("w_path", P, "    uint32_t path = (uint32_t)bATan(dir->x, dir->y) & 0xffffu;",
     "    uint32_t path = (uint32_t)bATan(dir->y, dir->x) & 0xffffu;"),
    ("w_first", P, "    if (fold(path, car->State.Angle, was) < WRONG_WAY_LIMIT)",
     "    if (fold(path, car->State.Angle, was) <= WRONG_WAY_LIMIT)"),
    ("w_abs", P, "    if (fabsf(car->State.ForwardSpeed * MPH_PER_MPS) > 10.0f) {",
     "    if (car->State.ForwardSpeed * MPH_PER_MPS > 10.0f) {"),
    ("w_fwd", P, "    if (fabsf(car->State.ForwardSpeed * MPH_PER_MPS) > 10.0f) {",
     "    if (fabsf(car->State.VelocityMagnitude * MPH_PER_MPS) > 10.0f) {"),
    ("w_heading", P, "        uint32_t heading = (uint32_t)bATan(car->State.Velocity.x,\n"
     "                                           car->State.Velocity.y);",
     "        uint32_t heading = (uint32_t)bATan(car->State.Velocity.y,\n"
     "                                           car->State.Velocity.x);"),
    ("w_second", P, "        if (fold(path, heading, was) < WRONG_WAY_LIMIT)",
     "        if (fold(path, heading, 0) < WRONG_WAY_LIMIT)"),
    ("w_slow", P, "    } else if (!was) {", "    } else if (was) {"),
    ("w_was", P, "    if (was)\n        return 1;", "    if (was)\n        return 0;"),
    ("w_wheels", P, "    return car->State.nWheelsTouchingGround > 3;",
     "    return car->State.nWheelsTouchingGround >= 3;"),
    # ---- IsAllowedToReset
    ("i_zone6", P, "    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 6 && zone != 7)",
     "    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 7)"),
    ("i_zone7", P, "    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 6 && zone != 7)",
     "    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 6)"),
    ("i_table", P, "    if (PlayerZoneBlocksRequest[zone] != 0 && zone != 6 && zone != 7)",
     "    if (zone > 3 && zone != 6 && zone != 7)"),
    ("i_nis", P, "    if (nis_playing(p))\n        return 0;\n", ""),
    ("i_speed", P, "    if (p->MyCar->State.VelocityMagnitude * MPH_PER_MPS > 60.0f)",
     "    if (p->MyCar->State.VelocityMagnitude * MPH_PER_MPS >= 60.0f)"),
    ("i_speed_fwd", P, "    if (p->MyCar->State.VelocityMagnitude * MPH_PER_MPS > 60.0f)",
     "    if (p->MyCar->State.ForwardSpeed * MPH_PER_MPS > 60.0f)"),
    ("i_bac", P, "    if (TheRaceParameters.BeACop == 0)\n        return 1;",
     "    if (TheRaceParameters.BeACop != 1)\n        return 1;"),
    ("i_signed", P, "    t = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * SECONDS_PER_TICK;",
     "    t = (float)pCurrentRace->RaceTime.PackedTime * SECONDS_PER_TICK;"),
    ("i_five", P, "    return !(t < 5.0f);", "    return t > 5.0f;"),
    # ---- ChooseToDisplayReset
    ("d_speed", P, "    float speed = car->State.VelocityMagnitude * MPH_PER_MPS;",
     "    float speed = car->State.ForwardSpeed * MPH_PER_MPS;"),
    ("d_hit", P, "                    &car->pDynamicCollisionBody->LastPenetrationTime)",
     "                    &p->tTroubleSpeedTimer)"),
    ("d_s60", P, "    if (speed > 60.0f && hit < 3.0f) {",
     "    if (speed >= 60.0f && hit < 3.0f) {"),
    ("d_hit3", P, "    if (speed > 60.0f && hit < 3.0f) {",
     "    if (speed > 60.0f && hit <= 3.0f) {"),
    ("d_yaw_abs", P, "        if (fabsf(yaw * DEG_PER_RAD) > 50.0f)",
     "        if (yaw * DEG_PER_RAD > 50.0f)"),
    ("d_yaw_gt", P, "        if (fabsf(yaw * DEG_PER_RAD) > 50.0f)",
     "        if (fabsf(yaw * DEG_PER_RAD) >= 50.0f)"),
    ("d_yaw_set", P, "            p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;\n    }",
     "            ;\n    }"),
    ("d_dt", P, "    if (dt > 0.5f) {", "    if (dt >= 0.5f) {"),
    ("d_last60", P, "        if (last > 60.0f && hit < 3.0f && rate < -70.0f)",
     "        if (speed > 60.0f && hit < 3.0f && rate < -70.0f)"),
    ("d_rate", P, "        if (last > 60.0f && hit < 3.0f && rate < -70.0f)",
     "        if (last > 60.0f && hit < 3.0f && rate < -60.0f)"),
    ("d_rate_hit", P, "        if (last > 60.0f && hit < 3.0f && rate < -70.0f)",
     "        if (last > 60.0f && rate < -70.0f)"),
    ("d_rate_sign", P, "        float rate = (speed - last) / dt;",
     "        float rate = (last - speed) / dt;"),
    ("d_rate_set", P, "            p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;\n"
     "        p->tTroubleSpeedTimer", "            ;\n        p->tTroubleSpeedTimer"),
    ("d_tt", P, "        p->tTroubleSpeedTimer.PackedTime = (uint32_t)WorldTimer;\n", ""),
    ("d_ts", P, "        p->fTroubleSpeed = speed;", "        p->fTroubleSpeed = last;"),
    ("d_up_speed", P, "    if (speed < 10.0f && car->State.BodyMatrix.v2.z < 0.0f)",
     "    if (speed <= 10.0f && car->State.BodyMatrix.v2.z < 0.0f)"),
    ("d_up", P, "    if (speed < 10.0f && car->State.BodyMatrix.v2.z < 0.0f)",
     "    if (speed < 10.0f && car->State.BodyMatrix.v2.z <= 0.0f)"),
    ("d_up_set", P, "        p->LastTimeCarInTrouble.PackedTime = (uint32_t)WorldTimer;\n\n"
     "    timer_set_time", "        ;\n\n    timer_set_time"),
    ("d_five", P, "    timer_set_time(&t, 5.0f);", "    timer_set_time(&t, 4.0f);"),
    ("d_five_cmp", P, "    if ((int32_t)t.PackedTime < ticks_since(&p->LastTimeCarInTrouble))",
     "    if ((int32_t)t.PackedTime <= ticks_since(&p->LastTimeCarInTrouble))"),
    ("d_let_go", P, "        p->LastTimeCarInTrouble.PackedTime = 0;\n\n    if (timer_is_valid",
     "        ;\n\n    if (timer_is_valid"),
    ("d_valid", P, "    if (timer_is_valid(&p->LastTimeCarInTrouble)\n",
     "    if (p->LastTimeCarInTrouble.PackedTime != 0\n"),
    ("d_allowed", P, "        && player_is_allowed_to_reset(p)\n", ""),
    ("d_copm", P, "        && (pCopManager == NULL\n            || copmanager_is_being_pursued",
     "        && (copmanager_is_being_pursued"),
    ("d_pursued", P, "copmanager_is_being_pursued(pCopManager, car) == NULL)) {",
     "copmanager_is_being_pursued(pCopManager, car) != NULL)) {"),
    ("d_prompt_keep", P, "        if (!timer_is_valid(&p->TimeToDisplayResetPrompt))",
     "        if (timer_is_valid(&p->TimeToDisplayResetPrompt))"),
    ("d_prompt_ret", P, "            p->LastTimeCarInTrouble.PackedTime = 0;\n        return;\n",
     "            p->LastTimeCarInTrouble.PackedTime = 0;\n"),
    ("d_three", P, "        timer_set_time(&t, 3.0f);", "        timer_set_time(&t, 2.0f);"),
    ("d_three_cmp", P, "        if ((int32_t)t.PackedTime < since)",
     "        if ((int32_t)t.PackedTime <= since)"),
    ("d_prompt_clear", P, "            p->TimeToDisplayResetPrompt.PackedTime = 0;",
     "            p->LastTimeCarInTrouble.PackedTime = 0;"),
    ("d_prompt_valid", P, "    if (timer_is_valid(&p->TimeToDisplayResetPrompt)) {",
     "    if (1) {"),
    # ---- UpdateGameState
    ("u_svc", P, "    player_service_nis(p);\n    p->bWrongWay", "    p->bWrongWay"),
    ("u_ww", P, "player_detect_wrong_way(p, p->bWrongWay) != 0;",
     "player_detect_wrong_way(p, 0) != 0;"),
    ("u_ctdr", P, "    player_choose_to_display_reset(p);\n    // Retail",
     "    // Retail"),
    ("u_race", P, "    if (s == RCSTATE_RACE_IN_PROGRESS || replaying()) {",
     "    if (replaying()) {"),
    ("u_replay", P, "    if (s == RCSTATE_RACE_IN_PROGRESS || replaying()) {",
     "    if (s == RCSTATE_RACE_IN_PROGRESS) {"),
    ("u_elapsed", P, "        timer_set_time(&t, WorldTimeElapsed);",
     "        timer_set_time(&t, 0.0f);"),
    ("u_sub", P, "        p->tAverageSpeedTimer.PackedTime -= t.PackedTime;",
     "        p->tAverageSpeedTimer.PackedTime += t.PackedTime;"),
    ("u_lt", P, "            * SECONDS_PER_TICK < 0.0f) {",
     "            * SECONDS_PER_TICK <= 0.0f) {"),
    ("u_signed", P, "        if ((float)(int32_t)p->tAverageSpeedTimer.PackedTime",
     "        if ((float)p->tAverageSpeedTimer.PackedTime"),
    ("u_route", P, "            TrackRoute *route = car_get_route(car, 1);",
     "            TrackRoute *route = car_get_route(car, 0);"),
    ("u_route_null", P, "            if (route != NULL) {", "            if (1) {"),
    ("u_line", P, "                int32_t line = car->pCarTypeInfo->CarClass * 2;",
     "                int32_t line = car->pCarTypeInfo->CarClass;"),
    ("u_point", P, "                TrackRoutePoint *pt = car_get_route_point(car, 1);",
     "                TrackRoutePoint *pt = car_get_route_point(car, 0);"),
    ("u_f", P, "                float f = 1.0f;", "                float f = 0.0f;"),
    ("u_valid", P, "                        & (DLI_IS_VALID | DLI_IS_FAKE)) != 0) {",
     "                        & DLI_IS_VALID) != 0) {"),
    ("u_fake", P, "                        & (DLI_IS_VALID | DLI_IS_FAKE)) != 0) {",
     "                        & DLI_IS_FAKE) != 0) {"),
    ("u_div", P, "                    f = ee_div(car->State.VelocityMagnitude, limit);",
     "                    f = car->State.VelocityMagnitude / limit;"),
    ("u_vm", P, "                    f = ee_div(car->State.VelocityMagnitude, limit);",
     "                    f = ee_div(car->State.ForwardSpeed, limit);"),
    ("u_record", P, "                average_record(p->pAverageSpeedRatio, f);",
     "                average_record(p->pAverageSpeedRatio, 1.0f);"),
    ("u_max", P, "                p->fMaxSpeedRatio = fmaxf(p->fMaxSpeedRatio,\n"
     "                                          p->pAverageSpeedRatio->fAverage);",
     "                p->fMaxSpeedRatio = p->pAverageSpeedRatio->fAverage;"),
    ("u_rearm", P, "            p->tAverageSpeedTimer.PackedTime = (uint32_t)ee_trunc_w(4000.5f);",
     "            p->tAverageSpeedTimer.PackedTime = 4001u;"),
    ("u_frz", P, "    if (p->fFreezeZoneDelayTimer > 0.0f) {",
     "    if (p->fFreezeZoneDelayTimer >= 0.0f) {"),
    ("u_frz_sub", P, "        p->fFreezeZoneDelayTimer -= WorldTimeElapsed;",
     "        p->fFreezeZoneDelayTimer -= 2.0f * WorldTimeElapsed;"),
    ("u_frz_le", P, "        if (p->fFreezeZoneDelayTimer <= 0.0f) {",
     "        if (p->fFreezeZoneDelayTimer < 0.0f) {"),
    ("u_frz_zero", P, "            p->fFreezeZoneDelayTimer = 0.0f;\n", ""),
    ("u_zone", P, "            if (player_request_zone(p, 1, 0, 1, 1)",
     "            if (player_request_zone(p, 1, 1, 1, 1)"),
    ("u_bust", P, "            if (player_request_zone(p, 1, 0, 1, 1)",
     "            if (!player_request_zone(p, 1, 0, 1, 1)"),
    ("u_bust_pos", P, "                    &p->MyCar->State.Position);",
     "                    &p->MyCar->State.Velocity);"),
    # ---- UpdatePlayersGameState
    ("g_count", P, "    for (i = 0; i < PlayerNumPlayers; i++)",
     "    for (i = 0; i < 2; i++)"),
    ("g_idx", P, "        player_update_game_state(PlayerPlayersByIndex[i]);",
     "        player_update_game_state(PlayerPlayersByIndex[0]);"),
]

EQUIVALENT = {
    "k_half":
        "the one difference left between 32767 and 32768 as the fold's "
        "edge is 32768 itself, which folds to 32768",
    "c_fallback":
        "GetNisInfo by type finds each of the GetNumNisInfo it counted, so "
        "the first ticket's is never asked for",
    "d_hit3":
        "no whole number of ticks times 0.00025f is 3.0f: 12000 of them "
        "make 3.0000002",
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
        todo, SOURCES, "playernis_test",
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
