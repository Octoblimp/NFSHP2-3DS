#!/usr/bin/env python3
"""Cross-check 3DS Files/source/pullover.c, the pullovers and Busted
(12l-1), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: tCopManager's CreatePullover
(0x00226f30), EndPullover (0x00225878) and its callback (0x00225868),
GetArrestingOfficer (0x00225c40) and RemoveSpeedTrapsForCar
(0x00228538); tAICop::DoneWritingTicket (0x00230c58); Player's
StartBustedDisplay (0x00228f08) and StopBustedDisplay (0x00228f00); and
what they call that is a few instructions, run as they are:
AICarController::ForcePullOver (0x001908d8) and Car::FixBlownTires
(0x00135120). The harness (tools/src/pullover_test.c) runs pullover.c
and prints the same lines.

**The stubs**, logged and answered by the same rule on both sides:
NISOverlayManager's StartBusted and Finish, Player's StartScore,
PlayNextNis, IsNisPlaying (scripted per player) and RemoveCameraMovers,
RaceParameters::IsFreeRun (scripted), the speech manager's FlushQueue,
raiseRacerCaught, the pull-over event (0x002075d8) and Be A Cop's
arrests (0x00207648), tPursuit's GetCopSpeaker (scripted),
RemoveCopFromPursuit and AITicketSpeech, tCop::SetDesiredLogicState (it
stores the state), GetBaseSpeedTrapSpawnTime (a scripted float),
RealDriver::ForceEBrakeStop, Race::FinishCar, Car's GetRoute,
GetRoutePoint (RP0, or none) and ResetToRoutePoint, GetNextRoutePoint
(RP1, and RT1 when scripted) and ResetAllDamage. The cops' IsAIControlled
and the controller's ReleaseBoost are virtual: both sides call them
through fake tables, each with its own `this` delta.

**Compared** are the stubs' logs and, after each call, both managers'
arrests, Be A Cop time and five pullover entries (all seven fields and
both timers), each car's drawing, map, lights, siren and tyres, each
controller's action and pull-over timeout, and each cop's desired state,
sub-state and timer.

**The divergences**: none in what is compared. The port's
ResetToRoutePoint has no last bool; retail passes 0, which the model
checks (" ?t0" if not). The NIS (Player::PlayNextNis) is a seam here.

    python tools/pullover_check.py
    python tools/pullover_check.py --mutate [--only a,b]
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

HARNESS = "tools/src/pullover_test.c"
PO = "3DS Files/source/pullover.c"
SOURCES = [HARNESS, PO, "3DS Files/source/vtable.c"]
HARNESS_TIMEOUT = 60

# ================================================================ the image

GP = retail_model.RETAIL_GP
RP = 0x0031a898                         # TheRaceParameters
G_COPMGR = GP - 15620                   # pCopManager
G_SPEECH = GP - 15624                   # the speech manager
G_WORLD = GP - 22120                    # pCurrentWorld
G_RACE = GP - 22272                     # pCurrentRace

F_CREATE = 0x00226f30
F_END = 0x00225878
F_CB = 0x00225868
F_GAO = 0x00225c40
F_RMT = 0x00228538
F_DONE = 0x00230c58
F_SBD = 0x00228f08
F_XBD = 0x00228f00

S_STARTBUSTED = 0x00228f10
S_FINISH = 0x00182948
S_SCORE = 0x0017e3b0
S_FREERUN = 0x001ee390
S_FLUSH = 0x0020a230
S_SPEAKER = 0x0022ab30
S_CAUGHT = 0x0020ae00
S_PULLEVENT = 0x002075d8
S_ARRESTS = 0x00207648
S_TICKET = 0x0022b840
S_REMOVE = 0x0022c740
S_STATE = 0x0022d538
S_PLAYNIS = 0x00176308
S_NISPLAYING = 0x00176520
S_BASE = 0x00224958
S_RMCAM = 0x00177430
S_EBRAKE = 0x0013b558
S_FINISHCAR = 0x00149250
S_ROUTE = 0x001332a8
S_POINT = 0x001332d8
S_NEXT = 0x001cb960
S_RESET = 0x00132f20
S_RESETDMG = 0x00228750

RP_FIELDS = {"tt": 36, "players": 48, "beacop": 628, "reset": 632,
             "tickets": 636}
MGR_SIZE, WORLD_SIZE, RACE_SIZE = 10516, 5936, 256
CAR_SIZE, CTL_SIZE, COP_SIZE, PURSUIT_SIZE = 2304, 640, 96, 1600
PLAYER_SIZE, NIS_OFF = 2720, 2560
NM, NCARS, NPL, NCOPS, NP = 2, 5, 3, 6, 2

# The manager's fields.
M_NAI, M_NCOPS, M_PCIDX, M_COPS = 4, 8, 12, 16
M_PL, PL_SIZE = 88, 28
M_PT, M_ST, M_TIME, M_ARRESTS = 10356, 10388, 10480, 10496
# The car's.
C_INDEX, C_DRIVER, C_PLAYER, C_MODE, C_CTL, C_CDRV = 8, 20, 24, 32, 40, 44
C_X, C_Y, C_DRV, C_LIGHTS, C_SIREN = 96, 100, 1196, 2056, 2104
C_BITS, C_NUM, C_RUMBLE, C_VIS = 2124, 2125, 2128, 2164
# The controller's, the cop's, the pursuit's.
K_VT, K_ACT, K_TO = 8, 528, 548
COP_CAR, COP_NUM, COP_ST, COP_SUB, COP_VT, COP_TIMER = 4, 8, 16, 20, 28, 44
U_RB, U_COPS, U_NCOPS, U_LEVEL = 20, 28, 1476, 1492

AI_DELTA, PL_DELTA, CTL_DELTA = 4, 8, 12


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
        self.names = {RP: "RP"}

        def block(n, nm):
            p = e.alloc(n, align=16)
            e.write(p, bytes(n))
            if nm:
                self.names[p] = nm
            return p
        self.block = block
        self.ms = [block(MGR_SIZE, "M%d" % k) for k in range(NM)]
        self.world = block(WORLD_SIZE, "W")
        self.race = block(RACE_SIZE, "R")
        self.speech = block(16, "SP")
        self.rb = block(16, "RB")
        self.ps = [block(PURSUIT_SIZE, "U%d" % k) for k in range(NP)]
        self.cars = [block(CAR_SIZE, "A%d" % k) for k in range(NCARS)]
        self.drivers = [block(16, "D%d" % k) for k in range(NCARS)]
        self.ctls = [block(CTL_SIZE, "K%d" % k) for k in range(NCARS)]
        self.rds = [block(16, "RD%d" % k) for k in range(NCARS)]
        self.players = [block(PLAYER_SIZE, "P%d" % k) for k in range(NPL)]
        self.cops = [block(COP_SIZE, "C%d" % k) for k in range(NCOPS)]
        self.routes = [block(16, "RT%d" % k) for k in range(2)]
        self.points = [block(16, "RP%d" % k) for k in range(2)]
        for k in range(NCARS):
            self.names[self.ctls[k] + CTL_DELTA] = "K%d+%d" % (k, CTL_DELTA)
        for k in range(NPL):
            self.names[self.players[k] + NIS_OFF] = "P%d.nis" % k
        for k in range(NCOPS):
            self.names[self.cops[k] + AI_DELTA] = "C%d+%d" % (k, AI_DELTA)
            self.names[self.cops[k] + PL_DELTA] = "C%d+%d" % (k, PL_DELTA)
        # The fake tables and the functions they hold.
        code = block(64, None)
        self.f_isai, self.f_isnot, self.f_release = code, code + 8, code + 16
        self.vt_ai = block(64, None)
        self.vt_pl = block(64, None)
        self.vt_ctl = block(128, None)
        e.write(self.vt_ai + 16, struct.pack("<hhI", AI_DELTA, 0,
                                             self.f_isai))
        e.write(self.vt_pl + 16, struct.pack("<hhI", PL_DELTA, 0,
                                             self.f_isnot))
        e.write(self.vt_ctl + 104, struct.pack("<hhI", CTL_DELTA, 0,
                                               self.f_release))
        e.put32(G_WORLD, self.world)
        e.put32(G_RACE, self.race)
        e.put32(G_SPEECH, self.speech)
        for addr, fn in ((S_STARTBUSTED, self.s_busted_on),
                         (S_FINISH, self.s_busted_off),
                         (S_SCORE, self.s_score),
                         (S_FREERUN, self.s_freerun),
                         (S_FLUSH, self.s_flush),
                         (S_SPEAKER, self.s_speaker),
                         (S_CAUGHT, self.s_caught),
                         (S_PULLEVENT, self.s_pullevent),
                         (S_ARRESTS, self.s_arrests),
                         (S_TICKET, self.s_ticket),
                         (S_REMOVE, self.s_remove),
                         (S_STATE, self.s_state),
                         (S_PLAYNIS, self.s_playnis),
                         (S_NISPLAYING, self.s_nisplaying),
                         (S_BASE, self.s_base),
                         (S_RMCAM, self.s_rmcam),
                         (S_EBRAKE, self.s_ebrake),
                         (S_FINISHCAR, self.s_finishcar),
                         (S_ROUTE, self.s_route),
                         (S_POINT, self.s_point),
                         (S_NEXT, self.s_next),
                         (S_RESET, self.s_reset),
                         (S_RESETDMG, self.s_resetdmg),
                         (self.f_isai, self.s_isai),
                         (self.f_isnot, self.s_isnot),
                         (self.f_release, self.s_release)):
            e.stub(addr, fn)
        self.reset()

    def emit(self, line):
        self.out.append(line)

    def sym(self, v):
        v &= M32
        if v == 0:
            return "0"
        return self.names.get(v, "?")

    def mgr_ok(self, em):
        return "" if em.reg[4] & M32 == self.speech else " ?mgr"

    def reset(self):
        e = self.e
        for lst, n in ((self.ms, MGR_SIZE), (self.cars, CAR_SIZE),
                       (self.drivers, 16), (self.ctls, CTL_SIZE),
                       (self.cops, COP_SIZE), (self.ps, PURSUIT_SIZE)):
            for p in lst:
                e.write(p, bytes(n))
        e.write(self.world, bytes(WORLD_SIZE))
        e.write(self.race, bytes(RACE_SIZE))
        e.write(self.rb, bytes(16))
        for off in RP_FIELDS.values():
            e.put32(RP + off, 0)
        for k in range(NCARS):
            c = self.cars[k]
            e.put32(c + C_DRIVER, self.drivers[k])
            e.put32(c + C_CTL, self.ctls[k])
            e.put32(c + C_CDRV, self.rds[k])
            e.put32(self.ctls[k] + K_VT, self.vt_ctl)
        for c in self.cops:
            e.put32(c + COP_VT, self.vt_ai)
        e.put32(G_COPMGR, self.ms[0])
        self.spk = 0
        self.free = 0
        self.base = 0
        self.nisp = [0] * NPL
        self.point_on = 1
        self.next_route = 0

    # ---- stubs

    def s_busted_on(self, em):
        self.emit("  busted_on %s" % self.sym(em.reg[4]))

    def s_busted_off(self, em):
        self.emit("  busted_off %s" % self.sym(em.reg[4]))

    def s_score(self, em):
        self.emit("  score %s %d" % (self.sym(em.reg[4]), s32(em.reg[5])))

    def s_freerun(self, em):
        self.emit("  freerun %s -> %d" % (self.sym(em.reg[4]), self.free))
        return self.free

    def s_flush(self, em):
        self.emit("  flush" + self.mgr_ok(em))

    def s_speaker(self, em):
        self.emit("  speaker %s -> %08x" % (self.sym(em.reg[4]), self.spk))
        return self.spk

    def s_caught(self, em):
        self.emit("  caught %08x %d %d%s" % (
            em.reg[5] & M32, em.reg[6] & M32, s32(em.reg[7]),
            self.mgr_ok(em)))

    def s_pullevent(self, em):
        self.emit("  pullover_event")

    def s_arrests(self, em):
        self.emit("  arrests %d %d %d %d" % tuple(
            s32(em.reg[r]) for r in (4, 5, 6, 7)))

    def s_ticket(self, em):
        self.emit("  ticket_speech %s" % self.sym(em.reg[4]))

    def s_remove(self, em):
        self.emit("  remove %s %s" % (self.sym(em.reg[4]),
                                      self.sym(em.reg[5])))
        return 1

    def s_state(self, em):
        c = em.reg[4] & M32
        self.emit("  state %s %d" % (self.sym(c), s32(em.reg[5])))
        self.e.put32(c + COP_ST, em.reg[5])

    def s_playnis(self, em):
        self.emit("  nis %s %s %s %s %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            "cb" if em.reg[7] & M32 == F_CB else "?", s32(em.reg[8])))

    def s_nisplaying(self, em):
        p = em.reg[4] & M32
        r = self.nisp[self.players.index(p)]
        self.emit("  nisplaying %s -> %d" % (self.sym(p), r))
        return r

    def s_base(self, em):
        self.emit("  base %s -> %08x" % (self.sym(em.reg[4]), self.base))
        em.fpr[0] = self.base

    def s_rmcam(self, em):
        self.emit("  rmcam %s" % self.sym(em.reg[4]))

    def s_ebrake(self, em):
        self.emit("  ebrake %s %08x" % (self.sym(em.reg[4]),
                                        em.fpr[12] & M32))

    def s_finishcar(self, em):
        self.emit("  finish %s %s %d %d %d" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), s32(em.reg[6]),
            s32(em.reg[7]), s32(em.reg[8])))

    def s_route(self, em):
        self.emit("  route %s %d -> RT0" % (self.sym(em.reg[4]),
                                            s32(em.reg[5])))
        return self.routes[0]

    def s_point(self, em):
        r = self.points[0] if self.point_on else 0
        self.emit("  point %s %d -> %s" % (self.sym(em.reg[4]),
                                           s32(em.reg[5]), self.sym(r)))
        return r

    def s_next(self, em):
        a = em.reg[4] & M32
        self.emit("  next %s %s" % (self.sym(self.e.u32(a)),
                                    self.sym(self.e.u32(a + 4))))
        self.e.put32(a + 4, self.points[1])
        if self.next_route:
            self.e.put32(a, self.routes[1])

    def s_reset(self, em):
        self.emit("  reset %s %s %s %08x %d %08x%s" % (
            self.sym(em.reg[4]), self.sym(em.reg[5]), self.sym(em.reg[6]),
            em.fpr[12] & M32, s32(em.reg[7]), em.fpr[13] & M32,
            "" if em.reg[8] & 0xff == 0 else " ?t0"))

    def s_resetdmg(self, em):
        self.emit("  resetdmg %s %s" % (self.sym(em.reg[4]),
                                        self.sym(em.reg[5])))

    def s_isai(self, em):
        self.emit("  isai %s -> 1" % self.sym(em.reg[4]))
        return 1

    def s_isnot(self, em):
        self.emit("  isai %s -> 0" % self.sym(em.reg[4]))
        return 0

    def s_release(self, em):
        self.emit("  release %s" % self.sym(em.reg[4]))

    # ---- dumps

    def dump(self):
        e = self.e
        for k, m in enumerate(self.ms):
            self.emit("M%d arrests %d time %08x" % (
                k, s32(e.u32(m + M_ARRESTS)), e.u32(m + M_TIME)))
            for i in range(NCARS):
                b = m + M_PL + PL_SIZE * i
                t = e.u8(b + 8)
                self.emit("M%d.%d cop %d hold %08x t %d a %d n %d r %d b %d "
                          "pt %08x st %08x" % (
                              k, i, s32(e.u32(b)), e.u32(b + 4),
                              t - 256 if t > 127 else t,
                              s32(e.u32(b + 12)), s32(e.u32(b + 16)),
                              s32(e.u32(b + 20)), s32(e.u32(b + 24)),
                              e.u32(m + M_PT + 4 * i),
                              e.u32(m + M_ST + 4 * i)))
        for i in range(NCARS):
            c = self.cars[i]
            self.emit("A%d drv %d vis %d lights %08x siren %d bits %d num %d "
                      "rumble %08x" % (
                          i, s32(e.u32(c + C_DRV)), s32(e.u32(c + C_VIS)),
                          e.u32(c + C_LIGHTS), s32(e.u32(c + C_SIREN)),
                          e.u8(c + C_BITS), e.u8(c + C_NUM),
                          e.u32(c + C_RUMBLE)))
            k = self.ctls[i]
            self.emit("K%d act %d to %08x" % (i, s32(e.u32(k + K_ACT)),
                                              e.u32(k + K_TO)))
        for i, c in enumerate(self.cops):
            self.emit("C%d st %d sub %d timer %08x" % (
                i, s32(e.u32(c + COP_ST)), s32(e.u32(c + COP_SUB)),
                e.u32(c + COP_TIMER)))

    # ---- ops

    def idx(self, lst, s):
        k = int(s, 0)
        return lst[k] if k >= 0 else 0

    def pname(self, s):
        k = int(s, 0)
        return "U%d" % k if k >= 0 else "0"

    def run(self, a):
        e = self.e
        o = a[0]
        v = lambda j: int(a[j], 0) & M32        # noqa: E731
        call = lambda f, *args: e.call(f, *args, limit=200000)  # noqa
        if o == "reset":
            self.reset()
            return
        if o == "rp":
            e.put32(RP + RP_FIELDS[a[1]], v(2))
            return
        if o == "race":
            e.put32(self.race + 24, v(1))
            return
        if o == "world":
            e.put32(self.world + 32, v(1))
            for j in range(NCARS):
                e.put32(self.world + 44 + 4 * j, self.idx(self.cars, a[2 + j]))
            return
        if o == "cur":
            e.put32(G_COPMGR, self.ms[int(a[1])])
            return
        if o == "m":
            m = self.ms[int(a[1])]
            e.put32(m + M_NAI, v(2))
            e.put32(m + M_NCOPS, v(3))
            e.put32(m + M_PCIDX, v(4))
            e.put32(m + M_ARRESTS, v(5))
            e.put32(m + M_TIME, v(6))
            return
        if o == "mcop":
            m = self.ms[int(a[1])]
            e.put32(m + M_COPS + 4 * int(a[2]), self.idx(self.cops, a[3]))
            return
        if o == "pl":
            b = self.ms[int(a[1])] + M_PL + PL_SIZE * int(a[2])
            e.put32(b, v(3))
            e.put32(b + 4, v(4))
            e.write(b + 8, bytes([v(5) & 0xff]))
            for j, off in enumerate((12, 16, 20, 24)):
                e.put32(b + off, v(6 + j))
            return
        if o == "tm":
            m = self.ms[int(a[1])]
            i = int(a[2])
            e.put32(m + M_PT + 4 * i, v(3))
            e.put32(m + M_ST + 4 * i, v(4))
            return
        if o == "car":
            k = int(a[1])
            c = self.cars[k]
            e.write(c + C_INDEX, struct.pack("<h", s32(v(2))))
            e.put32(self.drivers[k] + 8, v(3))
            e.put32(c + C_PLAYER, self.idx(self.players, a[4]))
            e.put32(c + C_MODE, v(5))
            e.put32(c + C_X, v(6))
            e.put32(c + C_Y, v(7))
            e.write(c + C_BITS, bytes([v(8) & 0xff, v(9) & 0xff]))
            e.put32(c + C_RUMBLE, v(10))
            e.put32(c + C_VIS, v(11))
            e.put32(c + C_DRV, v(12))
            e.put32(c + C_SIREN, v(13))
            e.put32(c + C_LIGHTS, v(14))
            return
        if o == "ctl":
            k = self.ctls[int(a[1])]
            e.put32(k + K_ACT, v(2))
            e.put32(k + K_TO, v(3))
            return
        if o == "cop":
            c = self.cops[int(a[1])]
            e.put32(c + COP_CAR, self.idx(self.cars, a[2]))
            e.put32(c + COP_NUM, v(3))
            e.put32(c + COP_ST, v(4))
            e.put32(c + COP_SUB, v(5))
            e.put32(c + COP_TIMER, v(6))
            e.put32(c + COP_VT, self.vt_ai if v(7) else self.vt_pl)
            return
        if o == "pu":
            p = self.ps[int(a[1])]
            e.put32(p + U_NCOPS, v(2))
            e.put32(p + U_COPS, self.idx(self.cops, a[3]))
            e.put32(p + U_COPS + 4, self.idx(self.cops, a[4]))
            e.put32(p + U_RB, self.rb if v(5) else 0)
            e.put32(p + U_LEVEL, v(6))
            return
        if o == "rb":
            e.put32(self.rb, self.idx(self.cops, a[1]))
            e.put32(self.rb + 4, self.idx(self.cops, a[2]))
            return
        if o == "spk":
            self.spk = v(1)
            return
        if o == "free":
            self.free = s32(v(1))
            return
        if o == "base":
            self.base = v(1)
            return
        if o == "nisp":
            self.nisp[int(a[1])] = s32(v(2))
            return
        if o == "pt":
            self.point_on = int(a[1])
            return
        if o == "nxr":
            self.next_route = int(a[1])
            return

        if o == "create":
            self.emit("create M%s %s A%s %s" % (a[1], self.pname(a[2]), a[3],
                                                a[4]))
            call(F_CREATE, self.ms[int(a[1])], self.idx(self.ps, a[2]),
                 self.cars[int(a[3])], v(4))
        elif o == "end":
            self.emit("end M%s %s" % (a[1], a[2]))
            call(F_END, self.ms[int(a[1])], v(2))
        elif o == "cb":
            self.emit("cb %s" % a[1])
            call(F_CB, v(1))
        elif o == "gao":
            r = call(F_GAO, self.ms[int(a[1])], self.idx(self.ps, a[2]))
            self.emit("gao M%s %s -> %s" % (a[1], self.pname(a[2]),
                                            self.sym(r)))
        elif o == "rmt":
            self.emit("rmt M%s A%s" % (a[1], a[2]))
            call(F_RMT, self.ms[int(a[1])], self.cars[int(a[2])])
        elif o == "done":
            self.emit("done C%s" % a[1])
            call(F_DONE, self.cops[int(a[1])])
        elif o == "sbd":
            self.emit("sbd P%s" % a[1])
            call(F_SBD, self.players[int(a[1])])
        elif o == "xbd":
            self.emit("xbd P%s" % a[1])
            call(F_XBD, self.players[int(a[1])])
        else:
            raise ValueError(o)
        self.dump()


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

AI_RACER, HUMAN_RACER, TRAFFIC = 2, 1, 3
LS_LIMBO, LS_DISABLED, LS_TRAP, LS_RB, LS_PATROL = 1, 2, 3, 4, 5
LS_HOT, LS_CAUGHT, LS_GUARD = 6, 7, 8


def car(k, index=None, dtype=AI_RACER, player=-1, mode=0, x=0.0, y=0.0,
        bits=0, num=0, rumble=0.0, vis=1, drv=1, siren=0, lights=0):
    return "car|%d|%d|%d|%d|%d|%s|%s|%d|%d|%s|%d|%d|%d|0x%x" % (
        k, k if index is None else index, dtype, player, mode, F(x), F(y),
        bits, num, F(rumble), vis, drv, siren, lights)


def cop(k, car_=-1, num=None, st=LS_HOT, sub=0, timer=0.0, ai=1):
    return "cop|%d|%d|%d|%d|%d|%s|%d" % (k, car_, k if num is None else num,
                                         st, sub, F(timer), ai)


def mset(k, nai=3, ncops=4, pcidx=3, arrests=0, t=0.0):
    return "m|%d|%d|%d|%d|%d|%s" % (k, nai, ncops, pcidx, arrests, F(t))


def plset(k, i, cop_=-1, hold=0.0, tickets=0, active=0, nis=0, arrest=0,
          busted=0):
    return "pl|%d|%d|%d|%s|%d|%d|%d|%d|%d" % (k, i, cop_, F(hold), tickets,
                                              active, nis, arrest, busted)


def pu(k, ncops=1, c0=1, c1=-1, rb=0, level=2):
    return "pu|%d|%d|%d|%d|%d|%d" % (k, ncops, c0, c1, rb, level)


def base():
    """A race: A0 and A1 racers, A2, A3 and A4 cop cars; C0, C1 and C2 the
    AI cops, C3 the player's (in Be A Cop A3 is P2's)."""
    out = ["reset", "rp|tickets|3", "rp|players|1", "rp|beacop|0",
           "rp|reset|0", "rp|tt|180000", "race|5",
           "world|2|0|1|2|3|4", "cur|0", "base|%s" % F(30.0), "spk|0x5",
           car(0, dtype=AI_RACER, x=10.0, y=20.0, bits=3, num=2, rumble=0.5,
               lights=0),
           car(1, dtype=HUMAN_RACER, player=0, x=100.0, y=-40.0),
           car(2, dtype=4, x=200.0, y=0.0, siren=2, lights=0x01010101),
           car(3, dtype=4, player=2, x=-150.0, y=60.0, siren=1,
               lights=0xffffffff),
           car(4, dtype=4, x=0.0, y=300.0, siren=2, lights=1),
           cop(0, 2), cop(1, 4), cop(2, 2, st=LS_PATROL),
           cop(3, 3, ai=0), cop(4, -1), cop(5, -1, st=LS_TRAP),
           pu(0), pu(1, ncops=0, c0=-1),
           "rb|4|5"]
    for k in range(NM):
        out.append(mset(k))
        for s, c in enumerate((0, 1, 2, 3, 4, 5)):
            out.append("mcop|%d|%d|%d" % (k, s, c))
    out += ["ctl|0|0|%s" % F(5.0), "ctl|1|0|%s" % F(5.0)]
    return out


def gao_cases():
    out = []
    pats = ((-1, -1), (1, -1), (-1, 1), (4, 5), (-1, 5))
    for pidx in (-1, 0):
        for ncops in (0, 1, 2, -1):
            for c0, c1 in pats:
                for rb in (0, 1):
                    for r0, r1 in pats:
                        out += base() + [pu(0, ncops=ncops, c0=c0, c1=c1,
                                            rb=rb), "rb|%d|%d" % (r0, r1),
                                         "gao|0|%d" % pidx]
    # The patrol and the radar traps, by the AI cops' count.
    for nai in (0, 1, 2, 3, 4, -1):
        for sts in ((6, 6, 6, 6), (3, 6, 6, 6), (6, 5, 3, 6), (6, 6, 6, 3),
                    (6, 6, 6, 5), (1, 2, 4, 7), (8, 0, 5, 3)):
            out += base() + [mset(1, nai=nai)]
            for k, st in enumerate(sts):
                out.append(cop(k, 2, st=st, ai=k != 3))
            out += ["gao|1|-1", pu(0, ncops=1, c0=-1), "gao|1|0"]
    # No cop at all: Cops[0], or none.
    for c0 in (-1, 4):
        out += base() + [mset(0, nai=0), "mcop|0|0|%d" % c0, "gao|0|-1"]
    return out


def rmt_cases(rng):
    out = []
    # The range, each way, for each player.
    for d in (0.0, 100.0, 249.99998, 250.0, 250.00002, 400.0):
        for nis in (0, 1):
            for who in (0, 1):
                for dx in (1, 0):
                    x = d if dx else 0.0
                    y = 0.0 if dx else -d
                    out += base() + [
                        "world|3|0|1|3|2|4",
                        cop(0, 2, st=LS_TRAP), cop(1, 4, st=LS_TRAP),
                        car(2, dtype=4, x=50.0, y=50.0),
                        car(4, dtype=4, x=-80.0, y=10.0),
                        car(1, dtype=HUMAN_RACER, player=0,
                            x=50.0 + x if who == 0 else 900.0,
                            y=50.0 + y if who == 0 else 900.0),
                        car(3, dtype=4, player=2,
                            x=-80.0 + x if who == 1 else -900.0,
                            y=10.0 + y if who == 1 else 900.0),
                        "nisp|%d|%d" % (0 if who == 0 else 2, nis),
                        "rmt|0|0"]
    # The cops: NULL slots, other states, the count.
    for nai in (0, 1, 2, 3, 4):
        for sts in ((3, 3, 3, 3), (6, 3, 1, 3), (3, 5, 3, 6)):
            for null in (-1, 1, 2):
                out += base() + [mset(0, nai=nai), "world|1|1|0|2|3|4",
                                 car(1, dtype=HUMAN_RACER, player=0, x=0.0,
                                     y=0.0)]
                for k, st in enumerate(sts):
                    out.append(cop(k, 2 + k % 3, st=st))
                out += [car(2, dtype=4, x=10.0, y=10.0),
                        car(3, dtype=4, x=600.0, y=0.0),
                        car(4, dtype=4, x=-245.0, y=0.0)]
                if null >= 0:
                    out.append("mcop|0|%d|-1" % null)
                out.append("rmt|0|1")
    # The timer: pCopManager's, by the car's index.
    for cur in (0, 1):
        for index in (0, 3, 4):
            out += base() + ["cur|%d" % cur, mset(0, nai=0),
                             car(0, index=index), "base|%s" % F(17.5),
                             "rmt|0|0"]
    # At random.
    for _ in range(300):
        out += base() + [mset(0, nai=rng.randrange(5)),
                         "world|%d|0|1|2|3|4" % rng.randrange(6)]
        for k in range(4):
            out.append(cop(k, 2 + rng.randrange(3),
                           st=rng.choice((3, 3, 5, 6)), ai=k != 3))
        for k in range(NCARS):
            out.append(car(k, dtype=rng.choice((2, 1, 4)),
                           player=rng.choice((-1, 0, 1, 2)),
                           x=rng.uniform(-400, 400), y=rng.uniform(-400, 400)))
        for k in range(NPL):
            out.append("nisp|%d|%d" % (k, rng.random() < 0.3))
        out.append("rmt|0|%d" % rng.randrange(NCARS))
    return out


def done_cases():
    out = []
    for st in range(9):
        for sub in (0, 3, 16, 17):
            out += base() + [cop(0, 2, st=st, sub=sub, timer=2.5), "done|0"]
    return out


def busted_cases():
    out = base()
    for k in range(NPL):
        out += ["sbd|%d" % k, "xbd|%d" % k]
    return out


def create_cases(rng):
    out = []
    # The Be A Cop matrix.
    for b in (0, 1):
        for pidx in (-1, 0):
            for dtype in (AI_RACER, HUMAN_RACER):
                for last in (0, 1):
                    for two in (0, 1):
                        for tickets in (2, 3, 4):
                            for ai in (0, 1):
                                for level in (3, 4):
                                    for arrest in (0, 1):
                                        out += base() + [
                                            "rp|beacop|1",
                                            car(0, dtype=dtype,
                                                player=0 if dtype ==
                                                HUMAN_RACER else -1),
                                            mset(0, arrests=3 if last else 1),
                                            "world|%d|0|1|2|3|4" % (
                                                2 if two else 4),
                                            cop(3, 3, ai=ai),
                                            pu(0, level=level),
                                            plset(0, 0, tickets=tickets,
                                                  arrest=arrest),
                                            "create|0|%d|0|%d" % (pidx, b)]
    # Hot Pursuit: a player or not, tickets, the free run.
    for b in (0, 1):
        for pidx in (-1, 0):
            for player in (-1, 0):
                for dtype in (AI_RACER, HUMAN_RACER, TRAFFIC):
                    for tickets in (0, 2, 3, 5, 127, -1):
                        for free in (0, 1):
                            for level in (3, 4):
                                out += base() + [
                                    car(0, dtype=dtype, player=player),
                                    pu(0, level=level),
                                    plset(0, 0, tickets=tickets),
                                    "free|%d" % free,
                                    "create|0|%d|0|%d" % (pidx, b)]
    # The arresting officer: a player cop or not.
    for c0 in (1, 3, -1):
        for b in (0, 1):
            out += base() + [car(0, dtype=HUMAN_RACER, player=0),
                             pu(0, c0=c0, ncops=1), "rb|3|-1",
                             pu(1, ncops=0, c0=-1, rb=1),
                             "create|0|0|0|%d" % b,
                             "create|0|1|1|%d" % b]
    # The player's cop by its index: C2 in A2, P1's.
    for last in (0, 1):
        for tickets in (0, 3):
            for b in (0, 1):
                out += base() + ["rp|beacop|1", mset(0, pcidx=2,
                                                     arrests=3 if last
                                                     else 1),
                                 "world|4|0|1|2|3|4",
                                 car(2, dtype=4, player=1), cop(2, 2, ai=0),
                                 plset(0, 0, tickets=tickets),
                                 "create|0|0|0|%d" % b]
    # The managers apart: m is M0, pCopManager M1, whose tickets count.
    for cur in (0, 1):
        for t0, t1 in ((0, 5), (5, 0), (3, 3)):
            for beacop in (0, 1):
                out += base() + ["cur|%d" % cur, "rp|beacop|%d" % beacop,
                                 car(0, dtype=HUMAN_RACER, player=0),
                                 plset(0, 0, tickets=t0),
                                 plset(1, 0, tickets=t1),
                                 "create|0|0|0|1", "create|0|-1|0|0"]
    # The radar traps let go are m's cops': M1 has none.
    for cur in (0, 1):
        for st in (LS_TRAP, LS_PATROL):
            out += base() + ["cur|%d" % cur, mset(1, nai=0),
                             cop(0, 2, st=st), cop(1, 4, st=LS_TRAP),
                             car(0, dtype=HUMAN_RACER, player=0),
                             "create|0|0|0|1", "create|1|0|0|1"]
    # The car's index is the entry's, not its slot.
    for index in (0, 2, 4):
        for p in (-1, 0):
            out += base() + [car(1, index=index, dtype=HUMAN_RACER,
                                 player=0),
                             "create|1|%d|1|1" % p]
    # The pull-over timeout, against what the controller has.
    for to in (5.0, 2.0, -3.0, 3.0, -1.0, 0.0):
        for pidx in (-1, 0):
            out += base() + ["ctl|0|1|%s" % F(to),
                             "create|0|%d|0|0" % pidx]
    # At random.
    for _ in range(500):
        out += rand_world(rng)
        out.append("create|%d|%d|%d|%d" % (
            rng.randrange(2), rng.choice((-1, 0, 1)), rng.randrange(2),
            rng.random() < 0.7))
    return out


def rand_world(rng):
    out = base() + [
        "rp|beacop|%d" % (rng.random() < 0.4),
        "rp|tickets|%d" % rng.randrange(5),
        "rp|reset|%d" % rng.randrange(2),
        "rp|players|%d" % rng.randrange(1, 3),
        "rp|tt|%d" % rng.choice((180000, 0, 4000, 0x90000000)),
        "race|%d" % rng.randrange(2, 6),
        "world|%d|0|1|2|3|4" % rng.randrange(1, 5),
        "cur|%d" % rng.randrange(2), "free|%d" % (rng.random() < 0.2),
        "spk|0x%x" % rng.randrange(16),
        "base|%s" % F(rng.choice((30.0, 12.5, 0.0))),
        "pt|%d" % (rng.random() < 0.8), "nxr|%d" % rng.randrange(2)]
    for k in range(NM):
        out.append(mset(k, nai=rng.randrange(4), arrests=rng.randrange(5)))
        for i in range(NCARS):
            out.append(plset(k, i, cop_=rng.choice((-1, -1, 0, 1, 3)),
                             hold=rng.uniform(-1, 7),
                             tickets=rng.randrange(-2, 6),
                             active=rng.randrange(2), nis=rng.randrange(2),
                             arrest=rng.random() < 0.3,
                             busted=rng.random() < 0.3))
    for k in (0, 1):
        out.append(car(k, index=rng.choice((k, k, 4)),
                       dtype=rng.choice((AI_RACER, HUMAN_RACER, TRAFFIC)),
                       player=rng.choice((-1, k)), mode=rng.randrange(3),
                       x=rng.uniform(-300, 300), y=rng.uniform(-300, 300),
                       bits=rng.randrange(256), num=rng.randrange(5),
                       rumble=rng.uniform(0, 2)))
        out.append("ctl|%d|%d|%s" % (k, rng.randrange(8),
                                     F(rng.uniform(-2, 6))))
    out.append(cop(3, 3, ai=rng.random() < 0.2))
    out.append(pu(0, ncops=rng.randrange(3), c0=rng.choice((1, -1, 3)),
                  c1=rng.choice((0, -1)), rb=rng.randrange(2),
                  level=rng.choice((3, 4))))
    for k in range(NPL):
        out.append("nisp|%d|%d" % (k, rng.random() < 0.3))
    return out


def end_cases(rng):
    out = []
    # The arrest matrix.
    for beacop in (0, 1):
        for dtype in (AI_RACER, HUMAN_RACER, TRAFFIC):
            for player in (-1, 0):
                for last in (0, 1):
                    for busted in (0, 1):
                        for reset in (0, 1):
                            out += base() + [
                                "rp|beacop|%d" % beacop,
                                "rp|reset|%d" % reset,
                                mset(0, arrests=3 if last else 1, t=12.0),
                                car(0, dtype=dtype, player=player, bits=3,
                                    num=2, rumble=0.5),
                                plset(0, 0, arrest=1, busted=busted,
                                      active=1),
                                "end|0|0"]
    # Tickets: the AI racer, the player's reset, the rest.
    for beacop in (0, 1):
        for dtype in (AI_RACER, HUMAN_RACER, TRAFFIC):
            for player in (-1, 0):
                for mode in (0, 1, 2):
                    for pt in (0, 1):
                        for nxr in (0, 1):
                            for busted in (0, 1):
                                out += base() + [
                                    "rp|beacop|%d" % beacop,
                                    "rp|reset|1", "pt|%d" % pt,
                                    "nxr|%d" % nxr,
                                    car(0, dtype=dtype, player=player,
                                        mode=mode),
                                    plset(0, 0, busted=busted, active=1),
                                    "end|0|0"]
    # The entry's cop: none, an AI cop, the player's, its states.
    for c in (-1, 0, 1, 3):
        for st in (LS_DISABLED, LS_CAUGHT, LS_HOT):
            for ai3 in (0, 1):
                out += base() + [cop(0, 2, st=st, sub=4), cop(1, 4, st=st),
                                 cop(3, 3, st=st, ai=ai3),
                                 plset(0, 0, cop_=c), "end|0|0"]
    # The cop car's own pullover in Be A Cop, and the lights' word.
    for i in (0, 3):
        for index in (0, 3):
            for arrest in (0, 1):
                out += base() + ["rp|beacop|1", car(3, index=index,
                                                    dtype=4, player=2,
                                                    lights=0x7f7f7f7f,
                                                    siren=2),
                                 plset(0, i, arrest=arrest, busted=1),
                                 "end|0|%d" % i]
    # The player's cop by its index: C2 in A2, P1's.
    for arrest in (0, 1):
        for busted in (0, 1):
            for player in (-1, 0):
                out += base() + ["rp|beacop|1", "rp|reset|1",
                                 mset(0, pcidx=2, arrests=1),
                                 car(2, dtype=4, player=1, siren=2,
                                     lights=0x01010101),
                                 cop(2, 2, ai=0),
                                 car(0, dtype=HUMAN_RACER, player=player),
                                 plset(0, 0, arrest=arrest, busted=busted),
                                 "end|0|0"]
    # The time limit: the Timer's 4000ths, a signed word.
    for tt in (0, 4000, 180000, 0x7fffffff, 0x80000000, 0xfffff060, 1):
        out += base() + ["rp|beacop|1", "rp|reset|1", "rp|tt|%d" % tt,
                         car(0, dtype=AI_RACER), plset(0, 0), "end|0|0"]
    # The callback ends pCopManager's.
    for cur in (0, 1):
        out += base() + ["cur|%d" % cur, plset(0, 0, active=1),
                         plset(1, 0, active=1, arrest=1), "cb|0"]
    # At random.
    for _ in range(500):
        out += rand_world(rng)
        i = rng.randrange(NCARS)
        out.append("end|%d|%d" % (rng.randrange(2), i))
    return out


def sequences(rng):
    """Races: pullovers made and ended in turn, the tickets and arrests
    counting up."""
    out = []
    for run in range(60):
        out += rand_world(rng)
        out += ["cur|0", mset(0, arrests=0), mset(1, arrests=0)]
        for i in range(NCARS):
            out.append(plset(0, i))
        for step in range(rng.randrange(10, 40)):
            r = rng.random()
            k = rng.randrange(2)
            if r < 0.45:
                out.append("create|0|%d|%d|%d" % (
                    rng.choice((-1, 0)), k, rng.random() < 0.8))
            elif r < 0.8:
                out.append("end|0|%d" % k)
            elif r < 0.9:
                out.append("cb|%d" % k)
            elif r < 0.95:
                out.append("rmt|0|%d" % k)
            else:
                out.append("gao|0|%d" % rng.choice((-1, 0)))
    return out


def script():
    return (gao_cases() + rmt_cases(random.Random(0x91)) + done_cases()
            + busted_cases() + create_cases(random.Random(0x92))
            + end_cases(random.Random(0x93)) + sequences(random.Random(0x94)))


# ================================================================= running

def build_harness(tmp, name="pullover_test"):
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

P = PO
MUTATIONS = [
    # ---- the constants
    ("k_hold", P, "#define HOLD_TIME          7.0f",
     "#define HOLD_TIME          6.0f"),
    ("k_busted_hold", P, "#define BUSTED_HOLD_TIME   2.0f",
     "#define BUSTED_HOLD_TIME   3.0f"),
    ("k_pursuable", P, "#define PURSUABLE_TIME     8.0f",
     "#define PURSUABLE_TIME     7.0f"),
    ("k_share", P, "#define TRAP_SPAWN_SHARE   0.75f",
     "#define TRAP_SPAWN_SHARE   0.5f"),
    ("k_no_timeout", P, "#define NO_TIMEOUT        -1.0f",
     "#define NO_TIMEOUT         0.0f"),
    ("k_spike", P, "#define SPIKE_TIMEOUT      3.0f",
     "#define SPIKE_TIMEOUT      4.0f"),
    ("k_speed", P, "#define RESET_SPEED       15.0f",
     "#define RESET_SPEED       10.0f"),
    ("k_dir", P, "#define RESET_DIRECTION    1.0f",
     "#define RESET_DIRECTION   -1.0f"),
    ("k_range", P, "#define TRAP_KEEP_RANGE  250.0f",
     "#define TRAP_KEEP_RANGE  200.0f"),
    ("k_timer", P, "#define TIMER_SECONDS     0.00025f",
     "#define TIMER_SECONDS     0.001f"),
    ("k_caught_n", P, "#define CAUGHT_N           4u",
     "#define CAUGHT_N           3u"),
    ("k_level", P, "#define CAUGHT_LEVEL       4",
     "#define CAUGHT_LEVEL       3"),
    # ---- the helpers
    ("h_this", P, "    return ((IsAIControlledFn)e->fn)(vt_this(c, e));",
     "    return ((IsAIControlledFn)e->fn)(c);"),
    ("h_rumble", P, "    c->fBlownTireControllerRumbleTimer = 0.0f;\n", ""),
    ("h_bits", P, "    c->BlownTireBits = 0;\n", ""),
    ("h_num", P, "    c->NumBlownTires = 0;\n", ""),
    ("h_copcar", P, "    return m->Cops[m->nPlayerCopIndex]->pMyCar;",
     "    return m->Cops[3]->pMyCar;"),
    # ---- CreatePullover
    ("c_index", P, "    int32_t           i = car->CarIndex;",
     "    int32_t           i = 0;"),
    ("c_active", P, "    pl->bActive = 1;", "    pl->bActive = 0;"),
    ("c_nis_keep", P, "    pl->bPlayNIS = 0;\n", ""),
    ("c_busted_keep", P, "    pl->bShouldDisplayBustedText = 0;\n"
     "    if (car->MyDriver", "    if (car->MyDriver"),
    ("c_arrest_reset", P, "    pl->bPlayNIS = 0;\n",
     "    pl->bPlayNIS = 0;\n    pl->bArrest = 0;\n"),
    ("c_ai", P, "== DRIVER_TYPE_AI_RACER)\n        aicarcontroller_force_pull_over"
     "(car_ai_controller(car),\n                                        p",
     "!= DRIVER_TYPE_AI_RACER)\n        aicarcontroller_force_pull_over"
     "(car_ai_controller(car),\n                                        p"),
    ("c_timeout", P, "p != NULL ? NO_TIMEOUT", "p == NULL ? NO_TIMEOUT"),
    ("c_b", P, "    if (b != 0) {\n        if (TheRaceParameters.BeACop != 0) {",
     "    if (1) {\n        if (TheRaceParameters.BeACop != 0) {"),
    ("c_bac_cop", P, "            cop = m->Cops[m->nPlayerCopIndex];",
     "            cop = m->Cops[0];"),
    ("c_bac_player", P, "            player = cop->pMyCar->pPlayer;",
     "            player = car->pPlayer;"),
    ("c_last", P, "pCurrentRace->NumRacingCars - 2 == m->nBeACopNumArrestsMade",
     "pCurrentRace->NumRacingCars - 1 == m->nBeACopNumArrestsMade"),
    ("c_two", P, "                || pCurrentWorld->AICarPos == 2) {",
     "                || pCurrentWorld->AICarPos == 3) {"),
    ("c_or", P, "m->nBeACopNumArrestsMade\n                || pCurrentWorld",
     "m->nBeACopNumArrestsMade\n                && pCurrentWorld"),
    ("c_bac_nis", P, "                pl->bPlayNIS = 1;\n            } else {",
     "            } else {"),
    ("c_busted_call", P, "                player_start_busted_display(player);\n",
     ""),
    ("c_busted_flag", P, "                pl->bShouldDisplayBustedText = 1;\n",
     ""),
    ("c_hp_player", P, "            player = car->pPlayer;\n"
     "            if (player != NULL) {", "            player = car->pPlayer;\n"
     "            if (1) {"),
    ("c_gao", P, "                cop = copmanager_get_arresting_officer(m, p);",
     "                cop = m->Cops[0];"),
    ("c_hp_nis", P, "                cop = copmanager_get_arresting_officer(m, p);\n"
     "                pl->bPlayNIS = 1;\n",
     "                cop = copmanager_get_arresting_officer(m, p);\n"),
    ("c_tickets_m", P, "        if (pCopManager->CarPullovers[i].nNumTickets",
     "        if (m->CarPullovers[i].nNumTickets"),
    ("c_tickets_gt", P, ">= TheRaceParameters.nNumTicketsBeforeArrest) {",
     "> TheRaceParameters.nNumTicketsBeforeArrest) {"),
    ("c_bac_arrest", P, "                pl->bArrest = 1;\n"
     "                player = player_cop_car(m)->pPlayer;",
     "                player = player_cop_car(m)->pPlayer;"),
    ("c_bac_score", P, "player_start_score(player, SCORING_SPEED_BUSTED);",
     "player_start_score(player, SCORING_QUOTA_FILLED);"),
    ("c_free", P, "(&TheRaceParameters)\n                       == 0) {",
     "(&TheRaceParameters)\n                       != 0) {"),
    ("c_hp_arrest", P, "                       == 0) {\n"
     "                pl->bArrest = 1;\n", "                       == 0) {\n"),
    ("c_nis", P, "    if (pl->bPlayNIS != 0) {", "    if (pl->bPlayNIS == 0) {"),
    ("c_speech_p", P, "        if (p != NULL) {\n            if (gCopSpeechFlushQueueFn",
     "        if (1) {\n            if (gCopSpeechFlushQueueFn"),
    ("c_flush", P, "                gCopSpeechFlushQueueFn();\n", ""),
    ("c_caught_arrest", P, "            if (pl->bArrest != 0) {\n"
     "                uint32_t spk", "            if (pl->bArrest == 0) {\n"
     "                uint32_t spk"),
    ("c_caught_spk", P, "                        spk, CAUGHT_N,",
     "                        spk + 1, CAUGHT_N,"),
    ("c_caught_type", P, "p->nHUDPursuitLevel == CAUGHT_LEVEL ? 1 : 2);",
     "p->nHUDPursuitLevel == CAUGHT_LEVEL ? 2 : 1);"),
    ("c_event", P, "                gSpeechPulloverEventFn();\n", ""),
    ("c_isai", P, "        if (cop_is_ai(cop) != 0) {",
     "        if (cop_is_ai(cop) == 0) {"),
    ("c_remove_p", P, "            if (p != NULL)\n"
     "                tpursuit_remove_cop_from_pursuit(p, cop);",
     "            tpursuit_remove_cop_from_pursuit(p, cop);"),
    ("c_state", P, "            tcop_set_desired_logic_state(cop, LS_CAUGHT_SPEEDER);",
     "            tcop_set_desired_logic_state(cop, LS_HOT_PURSUIT);"),
    ("c_copidx", P, "            pl->nCopIndex = cop->nCopNumber;",
     "            pl->nCopIndex = 0;"),
    ("c_nis_cop", P, "gPlayerPlayNextNisFn(player, car, cop->pMyCar,",
     "gPlayerPlayNextNisFn(player, car, car,"),
    ("c_nis_param", P, "copmanager_end_pullover_callback, i);",
     "copmanager_end_pullover_callback, 0);"),
    ("c_traps", P, "        copmanager_remove_speed_traps_for_car(m, car);\n", ""),
    ("c_traps_m", P, "        copmanager_remove_speed_traps_for_car(m, car);",
     "        copmanager_remove_speed_traps_for_car(pCopManager, car);"),
    ("c_cam_bac", P, "        if (TheRaceParameters.BeACop != 0 && car->pPlayer "
     "!= NULL)\n", "        if (car->pPlayer != NULL)\n"),
    ("c_cam_who", P, "            player_remove_camera_movers(car->pPlayer);",
     "            player_remove_camera_movers(player);"),
    ("c_ticket_b", P, "        if (p != NULL && b != 0 && gPursuitAITicketSpeechFn",
     "        if (p != NULL && gPursuitAITicketSpeechFn"),
    ("c_ticket_p", P, "        if (p != NULL && b != 0 && gPursuitAITicketSpeechFn",
     "        if (b != 0 && gPursuitAITicketSpeechFn"),
    ("c_hold_swap", P, "                             ? BUSTED_HOLD_TIME : HOLD_TIME;",
     "                             ? HOLD_TIME : BUSTED_HOLD_TIME;"),
    ("c_nocop", P, "        pl->nCopIndex = -1;\n", ""),
    ("c_count_b", P, "    if (b != 0)\n        pl->nNumTickets",
     "    if (1)\n        pl->nNumTickets"),
    ("c_count_two", P, "((uint8_t)pl->nNumTickets + 1u);",
     "((uint8_t)pl->nNumTickets + 2u);"),
    ("c_count_cur", P, "        pl->nNumTickets = (int8_t)(uint8_t)((uint8_t)"
     "pl->nNumTickets + 1u);", "        pCopManager->CarPullovers[i]"
     ".nNumTickets++;"),
    ("c_count_sat", P, "        pl->nNumTickets = (int8_t)(uint8_t)((uint8_t)"
     "pl->nNumTickets + 1u);", "        if (pl->nNumTickets < 127)\n"
     "            pl->nNumTickets++;"),
    # ---- EndPullover
    ("e_car", P, "    Car              *car = pCurrentWorld->CarTable[i];",
     "    Car              *car = pCurrentWorld->CarTable[0];"),
    ("e_active", P, "    pl->bActive = 0;", "    pl->bActive = 1;"),
    ("e_pursuable_m", P, "    m->fPursuableTimer[i] = PURSUABLE_TIME;",
     "    pCopManager->fPursuableTimer[i] = PURSUABLE_TIME;"),
    ("e_share", P, "        copmanager_get_base_speed_trap_spawn_time(m) "
     "* TRAP_SPAWN_SHARE;", "        copmanager_get_base_speed_trap_spawn_time"
     "(m);"),
    ("e_tires", P, "    fix_blown_tires(car);\n", ""),
    ("e_real", P, "    if (car->TheControlMode == REAL_CONTROL)",
     "    if (car->TheControlMode != REAL_CONTROL)"),
    ("e_ebrake", P, "                                     0.0f);",
     "                                     1.0f);"),
    ("e_cop_none", P, "    if (pl->nCopIndex != -1) {", "    if (pl->nCopIndex > 0) {"),
    ("e_cop_idx", P, "        tCop *cop = m->Cops[pl->nCopIndex];",
     "        tCop *cop = m->Cops[0];"),
    ("e_cop_ai", P, "        if (cop_is_ai(cop) != 0)\n            taicop_done",
     "        if (1)\n            taicop_done"),
    ("e_arrest", P, "    if (pl->bArrest != 0) {\n        eRaceFinishReason",
     "    if (pl->bArrest == 0) {\n        eRaceFinishReason"),
    ("e_count_cur", P, "        m->nBeACopNumArrestsMade++;",
     "        pCopManager->nBeACopNumArrestsMade++;"),
    ("e_count", P, "        m->nBeACopNumArrestsMade++;\n", ""),
    ("e_ai_pull", P, "            aicarcontroller_force_pull_over(car_ai_controller"
     "(car),\n                                            NO_TIMEOUT);\n", ";\n"),
    ("e_ai_timeout", P, "                                            NO_TIMEOUT);",
     "                                            SPIKE_TIMEOUT);"),
    ("e_lost_player", P, "            if (car->pPlayer != NULL) {\n"
     "                over = 1;", "            if (car->pPlayer == NULL) {\n"
     "                over = 1;"),
    ("e_lost_over", P, "                over = 1;\n                both = 1;",
     "                both = 1;"),
    ("e_lost_both", P, "                over = 1;\n                both = 1;\n",
     "                over = 1;\n"),
    ("e_lost_why", P, "                why = RACING_CAR_BE_THE_COP_LOST;",
     "                why = RACING_CAR_ARRESTED;"),
    ("e_over", P, "                over = pCurrentRace->NumRacingCars - 1\n",
     "                over = pCurrentRace->NumRacingCars - 2\n"),
    ("e_blink", P, "                blink = over == 0;", "                blink = over;"),
    ("e_both", P, "                both = over;", "                both = 0;"),
    ("e_pos", P, "        race_finish_car_by_car(pCurrentRace, car, -1, blink, why);",
     "        race_finish_car_by_car(pCurrentRace, car, 0, blink, why);"),
    ("e_vis", P, "        car->bVisibleOnTrackMap = 0;\n", ""),
    ("e_drv", P, "        car->DriverRenderingEnabled = 0;\n", ""),
    ("e_pp", P, "            Player *pp = copCar->pPlayer;",
     "            Player *pp = car->pPlayer;"),
    ("e_won", P, "                                   RACING_CAR_BE_THE_COP_WON);",
     "                                   RACING_CAR_BE_THE_COP_LOST);"),
    ("e_speech_players", P, "gSpeechBeACopArrestFn(TheRaceParameters."
     "NumPlayerCars, 0, 1,", "gSpeechBeACopArrestFn(1, 0, 1,"),
    ("e_speech_count", P, "                                      m->"
     "nBeACopNumArrestsMade);", "                                      m->"
     "nBeACopNumArrestsMade - 1);"),
    ("e_quota", P, "            player_start_score(pp, SCORING_QUOTA_FILLED);",
     "            player_start_score(pp, SCORING_SPEED_BUSTED);"),
    ("e_drive", P, "        ctl->ForceCurrentAction = AIACTION_JUST_DRIVE;",
     "        ctl->ForceCurrentAction = AIACTION_PULL_OVER;"),
    ("e_boost_this", P, "        ((ReleaseBoostFn)e->fn)(vt_this(ctl, e));",
     "        ((ReleaseBoostFn)e->fn)(ctl);"),
    ("e_reset_player", P, "    } else if (car->pPlayer != NULL) {",
     "    } else if (car->pPlayer == NULL) {"),
    ("e_route", P, "        at.Route = car_get_route(car, 1);",
     "        at.Route = car_get_route(car, 0);"),
    ("e_point", P, "        at.Point = car_get_route_point(car, 1);",
     "        at.Point = car_get_route_point(car, 0);"),
    ("e_next", P, "        ai_get_next_route_point(&at);\n", ""),
    ("e_blink_reset", P, "at.Point, RESET_SPEED, 1,", "at.Point, RESET_SPEED, 0,"),
    ("e_bac", P, "    if (TheRaceParameters.BeACop == 0)\n        return;",
     "    if (TheRaceParameters.BeACop != 0)\n        return;"),
    ("e_busted", P, "        if (pl->bShouldDisplayBustedText != 0)\n"
     "            player_stop_busted_display", "        if (pl->"
     "bShouldDisplayBustedText == 0)\n            player_stop_busted_display"),
    ("e_busted_who", P, "            player_stop_busted_display(copCar->pPlayer);",
     "            player_stop_busted_display(car->pPlayer);"),
    ("e_own", P, "        if (copCar->CarIndex == i)\n            return;",
     "        if (copCar->CarIndex != i)\n            return;"),
    ("e_siren", P, "        copCar->TheSirenMode = SIREN_MODE_NONE;",
     "        car->TheSirenMode = SIREN_MODE_NONE;"),
    ("e_lights", P, "        copCar->CopLights = 0;\n", ""),
    ("e_lights_word", P, "        memset(copCar->_hole2025, 0, sizeof "
     "copCar->_hole2025);\n", ""),
    ("e_over_ret", P, "        if (over != 0)\n            return;",
     "        if (over == 0)\n            return;"),
    ("e_reset_flag", P, "        if (TheRaceParameters.BeACopResetTimerAfterArrest "
     "!= 0)", "        if (TheRaceParameters.BeACopResetTimerAfterArrest == 0)"),
    ("e_tt_signed", P, "                (float)(int32_t)TheRaceParameters."
     "TimeTrialTime.PackedTime", "                (float)TheRaceParameters."
     "TimeTrialTime.PackedTime"),
    ("e_dmg_player", P, "        if (car->pPlayer != NULL) {\n"
     "            copmanager_reset_all_damage(m, car);", "        if (1) {\n"
     "            copmanager_reset_all_damage(m, car);"),
    ("e_dmg_cop", P, "            copmanager_reset_all_damage(m, copCar);\n", ""),
    ("e_cb_i", P, "    copmanager_end_pullover(pCopManager, i);",
     "    copmanager_end_pullover(pCopManager, 0);"),
    # ---- GetArrestingOfficer
    ("g_ncops", P, "        for (k = 0; k < p->nNumCops && cop == NULL; k++)",
     "        for (k = 0; k < 2 && cop == NULL; k++)"),
    ("g_first", P, "        for (k = 0; k < p->nNumCops && cop == NULL; k++)",
     "        for (k = 0; k < p->nNumCops; k++)"),
    ("g_rb_two", P, "            for (k = 0; k < 2 && cop == NULL; k++)",
     "            for (k = 0; k < 1 && cop == NULL; k++)"),
    ("g_rb_none", P, "        if (cop == NULL && p->pRoadBlock != NULL)\n"
     "            for", "        if (0)\n            for"),
    ("g_nai", P, "    for (k = 0; k < m->nNumAICops && cop == NULL; k++) {",
     "    for (k = 0; k < m->nNumCops && cop == NULL; k++) {"),
    ("g_patrol", P, "        if (c->DesiredLogicState == LS_SPEED_TRAP\n"
     "            || c->DesiredLogicState == LS_DRIVING_ON_PATROL)",
     "        if (c->DesiredLogicState == LS_SPEED_TRAP)"),
    ("g_trap", P, "        if (c->DesiredLogicState == LS_SPEED_TRAP\n",
     "        if (c->DesiredLogicState == LS_ROAD_BLOCK\n"),
    ("g_fallback", P, "    return cop != NULL ? cop : m->Cops[0];",
     "    return cop;"),
    ("g_fallback_1", P, "    return cop != NULL ? cop : m->Cops[0];",
     "    return cop != NULL ? cop : m->Cops[1];"),
    # ---- RemoveSpeedTrapsForCar
    ("r_nai", P, "    for (k = 0; k < m->nNumAICops; k++) {",
     "    for (k = 0; k < m->nNumCops; k++) {"),
    ("r_state", P, "        if (cop == NULL || cop->DesiredLogicState != "
     "LS_SPEED_TRAP)", "        if (cop == NULL || cop->DesiredLogicState != "
     "LS_DRIVING_ON_PATROL)"),
    ("r_players", P, "        for (j = 0; j < pCurrentWorld->AICarPos; j++) {",
     "        for (j = 0; j < pCurrentWorld->AICarPos - 1; j++) {"),
    ("r_nis", P, "            if (pc->pPlayer == NULL || player_is_nis_playing"
     "(pc->pPlayer))", "            if (pc->pPlayer == NULL)"),
    ("r_dx", P, "            dx = pc->State.Position.x - cop->pMyCar->State."
     "Position.x;", "            dx = pc->State.Position.x;"),
    ("r_dy", P, "            dy = pc->State.Position.y - cop->pMyCar->State."
     "Position.y;", "            dy = pc->State.Position.y - cop->pMyCar->"
     "State.Position.x;"),
    ("r_le", P, "            if (sqrtf(dx * dx + dy * dy) < TRAP_KEEP_RANGE)",
     "            if (sqrtf(dx * dx + dy * dy) <= TRAP_KEEP_RANGE)"),
    ("r_break", P, "                release = 0;\n",
     "                { release = 0; break; }\n"),
    ("r_limbo", P, "            tcop_set_desired_logic_state(cop, LS_LIMBO);",
     "            tcop_set_desired_logic_state(cop, LS_DISABLED);"),
    ("r_release", P, "        if (release != 0)", "        if (release == 0)"),
    ("r_timer_m", P, "    pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] =",
     "    m->fSpeedTrapSpawnTimer[car->CarIndex] ="),
    ("r_timer_idx", P, "    pCopManager->fSpeedTrapSpawnTimer[car->CarIndex] =",
     "    pCopManager->fSpeedTrapSpawnTimer[0] ="),
    ("r_base_m", P, "        copmanager_get_base_speed_trap_spawn_time"
     "(pCopManager);", "        copmanager_get_base_speed_trap_spawn_time(m);"),
    # ---- DoneWritingTicket
    ("d_disabled", P, "    if (c->Base.DesiredLogicState == LS_DISABLED)\n",
     "    if (c->Base.DesiredLogicState == LS_LIMBO)\n"),
    ("d_ask", P, "    if (c->Base.DesiredLogicState != LS_CAUGHT_SPEEDER)\n",
     "    if (1)\n"),
    ("d_sub", P, "    c->Base.LogicSubState = LSS_CAUGHTSPEEDER_WAITING;",
     "    c->Base.DesiredLogicSubState = LSS_CAUGHTSPEEDER_WAITING;"),
    ("d_timer", P, "    c->fSubStateTimer = 10.0f;", "    c->fSubStateTimer = 9.0f;"),
    # ---- BUSTED!
    ("b_start", P, "    nisoverlay_start_busted(&p->mFlailerNIS);",
     "    nisoverlay_finish(&p->mFlailerNIS);"),
    ("b_stop", P, "    nisoverlay_finish(&p->mFlailerNIS);",
     "    nisoverlay_start_busted(&p->mFlailerNIS);"),
]

EQUIVALENT = {
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
        todo, SOURCES, "pullover_test",
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
