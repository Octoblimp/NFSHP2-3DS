#!/usr/bin/env python3
"""Cross-check 3DS Files/source/hudcop.c, the HUD's cop parts, against the
retail image, SLES_507.31.

**The model** is retail's own: Player::UpdateRadarDetector (0x0017be70),
Player::DrawTracker (0x0017c278) and Player::UpdatePursuitMeter
(0x0017c380); and under them tCopManager::GetNumTickets,
RaceParameters::IsFreeRun, Timer::SetTime, FlailerBitmapChunk::SetColor,
FlailerObjectChunk::SetVisibility, everything tools/hudanim_check.py runs
(the bitmap's HudStartAnimation, HudDoAnimations, ClearHudAnimations) and
the Flailer runtime on INGAMEB's Flailer chunk. The harness
(tools/src/hudcop_test.c) runs hudcop.c over hudanim.c and what
hudanim_test.c links, on the same bundle.

**The stubs** are hudanim_check.py's bMalloc, and the two callees the HUD
does not own, scripted the same on both sides and logged:
tCopManager::GetRadarDetectorIntensity (the manager, the car, the answer
and the flag, which the stub always writes) and bSample::Play (the
sample and its three floats).

**Compared** are the stubs' logs and, after each op, every line that
changed: hudanim_check.py's (each Player's twenty animation slots,
TotalScore and every Flailer object's bytes), and each Player's
RadarTimer and PrevPursuitLevel.

**The script** runs the radar over every number of lights from each side
of its step, both colour rows, a flag of every kind, negative and huge
intensities, NaN and the infinities; the beep at each rate, with the
sound off, a step of 0, a negative and a huge one, and the timer's wrap;
the two swells as they run; the trackers on each side of the range and
of each turn limit, for every tracker and both players; and the pursuit
meter over every ticket count, a free run, and the levels up and down
from each to each, as the animations run.

    python tools/hudcop_check.py
    python tools/hudcop_check.py --mutate [--only a,b]
    python tools/hudcop_check.py --dump out/hudcop
"""
import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bhash                            # noqa: E402
import flailer_check as fc              # noqa: E402
import hostbuild                        # noqa: E402
import hudanim_check as ha              # noqa: E402
import physicscar_check as pcc          # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/hudcop_test.c"
HUDCOP = "3DS Files/source/hudcop.c"
SOURCES = [HARNESS, HUDCOP] + ha.SOURCES[1:]

GP = fc.GP
RP = ha.RP
G_SOUND = GP - 23056                    # SoundEnabled
G_ELAPSED = GP - 19560                  # WorldTimeElapsed
G_COPS = GP - 15620                     # pCopManager

F_RADAR = 0x0017be70
F_TRACKER = 0x0017c278
F_METER = 0x0017c380
S_INTENSITY = 0x002274a8                # GetRadarDetectorIntensity
S_PLAY = 0x00274080                     # bSample::Play

NUM_CARS = 4
CAR_SIZE = 2304
CAR_INDEX = 8                           # int16
CAR_POS = 96                            # State.Position
CAR_TURN = 2192                         # fAngleToCamera
COPS_SIZE = 1024
TICKETS = 96                            # CarPullovers[0].nNumTickets
PULLOVER = 28

PLAYER_WORDS = dict(ha.PLAYER_WORDS, prev=1104, radartimer=1408)
P_CAR = 4
P_STAR = 1072
P_LEVEL = 1076
P_X = 1092
P_TRACKER = 1112
P_LIGHT = 1176
P_BEEP = 1404
P_PPOS = 2484

HUD_SINGLE = ha.HUD_SINGLE
ALL = ha.ALL

LIGHTS = ["b:%#x" % bhash.bhash("RADAR_LIGHT%d" % (i + 1)) for i in range(12)]
TRACKERS = ["b:%#x" % bhash.bhash("TRACKER_%d" % i) for i in range(7)]
STAR = "b:0x843fd334"
LEVELS = ["b:%#x" % (0xc7509d62 + i) for i in range(4)]
XS = ["b:%#x" % (0xfc401542 + i) for i in range(3)]

TICKS = ha.TICKS
T0 = 400000
F = ha.F
STEP = 1.0 / 60                         # a frame's WorldTimeElapsed
STEP_TICKS = 67                         # Timer::SetTime(STEP)


# ================================================================== script

def common():
    s = ["load|%s" % (fc.SD / "GLOBAL/INGAMEB.BUN"), "g|np|1",
         "g|timer|%d" % T0, "g|real|123457", "g|sound|1",
         "g|elapsed|%s" % F(STEP), "rp|RaceType|1", "rp|Laps|3",
         "rp|BeACop|0"]
    for k in range(NUM_CARS):
        s += ["car|%d|index|%d" % (k, k),
              "car|%d|pos|%s" % (k, "|".join(F(v) for v in (10 + k, 20, 30))),
              "car|%d|turn|0" % k]
    for k in (1, 0):
        s += ["use|%d" % k, "pl|%d|PN|%d" % (k, k),
              "pl|%d|screen|%#x" % (k, HUD_SINGLE), "pl|%d|chf|%#x" % (k, ALL),
              "pl|%d|car|%d" % (k, k), "pl|%d|beep|1" % k,
              "pl|%d|star|%s" % (k, STAR)]
        s += ["pl|%d|level|%d|%s" % (k, i, o) for i, o in enumerate(LEVELS)]
        s += ["pl|%d|x|%d|%s" % (k, i, o) for i, o in enumerate(XS)]
        s += ["pl|%d|light|%d|%s" % (k, i, o) for i, o in enumerate(LIGHTS)]
        s += ["pl|%d|tracker|%d|%s" % (k, i, o)
              for i, o in enumerate(TRACKERS)]
        s += ["pl|%d|ppos|%d|%s|%s" % (k, i, F(100 + 37.5 * i + k),
                                       F(50 - 12.25 * i))
              for i in range(4)]
    s += ["use|0"]
    return s


def frames(t, *dts):
    s = []
    for dt in dts:
        s += ["g|timer|%d" % (t + dt), "do"]
    return s


def seam(v, flag=0):
    return "seam|%s|%d" % (F(v), flag)


def s_radar():
    t = T0 + 10000
    s = ["g|timer|%d" % t]
    # Every count of lights, each side of its step, and past both ends.
    for k, v in enumerate((0.0, 0.05, 0.09090909, 0.0909091, 0.1, 0.18181819,
                           0.25, 0.3636364, 0.5, 0.6363636, 0.7272727,
                           0.72727275, 0.8, 0.8181818, 0.81818185, 0.9,
                           0.9090909, 0.90909094, 0.95, 1.0, 1.5, 1e10,
                           -0.05, -0.1, -1.0, -1e10, -0.0, float("nan"),
                           float("inf"), float("-inf"), 0.85, 0.3)):
        t += 50
        s += ["g|timer|%d" % t, seam(v, k & 1), "radar"]
    # The flag's kinds, at five lights and at ten.
    for v in (0.5, 0.95):
        for flag in (0, 1, 2, -1, 0x100, 0):
            t += 50
            s += ["g|timer|%d" % t, seam(v, flag), "radar"]
    # The swells as they run, from lights 8 and 9 moved.
    s += ["pos|%s|%s|%s|%s|%s" % (LIGHTS[8], F(200.5), F(30.25), F(1), F(1)),
          "pos|%s|%s|%s|%s|%s" % (LIGHTS[9], F(-12), F(-7.5), F(1.5),
                                  F(0.5))]
    t += 1000
    s += ["g|timer|%d" % t, seam(0.95, 1), "radar"]
    s += frames(t, 1, 200, 400, 799, 800, 801, 1200)
    t += 2000
    s += ["g|timer|%d" % t, seam(0.82), "radar"]
    s += frames(t, 400, 1000)
    t += 2000
    s += ["g|timer|%d" % t, seam(0.5), "radar"]
    s += frames(t, 400, 1000)
    # A light that is not there.
    s += ["pl|0|light|3|none", seam(0.5), "radar", seam(0.2), "radar",
          "pl|0|light|3|%s" % LIGHTS[3]]
    # Player 1, on car 1.
    s += ["use|1", seam(0.7, 1), "radar", "use|0"]
    return s


def s_beep():
    t = T0 + 50000
    s = ["pl|0|radartimer|0"]
    # Each rate: lit 1, 5, 9 and 10, a frame at a time past two beeps.
    for lit, n in ((1, 60), (5, 40), (9, 20), (10, 18)):
        s += [seam((lit + 0.5) / 11)]
        for _ in range(n):
            t += STEP_TICKS
            s += ["g|timer|%d" % t, "radar"]
    # The sound off, then back on; no lights.
    s += ["g|sound|0", "radar", "radar", "g|sound|1", "radar", seam(0.0),
          "radar", seam(0.95), "radar"]
    # The step: none, negative, a second, a quarter, huge, and back.
    for e in (0.0, 0.0, -0.5, -0.5, 1.0, 1.0, 0.25, 0.25, 0.25, 1e6,
              -1e6, 0.0001, 0.000125, STEP):
        s += ["g|elapsed|%s" % F(e), "radar"]
    # The timer's wrap, and a timer already past the beep.
    s += ["pl|0|radartimer|0x7fffffe0", "radar",
          "pl|0|radartimer|0x7fffff00", "radar",
          "pl|0|radartimer|0x80000000", "radar",
          "pl|0|radartimer|0xffffff00", "radar", "radar", "radar",
          "pl|0|radartimer|1800", "radar", seam(0.1), "radar",
          "pl|0|radartimer|1780", "radar", "pl|0|radartimer|0"]
    # Nine lights' beep falls at 0.155 s, and 620 ticks is exactly that:
    # not past it, so no beep.
    s += [seam(9.5 / 11), "pl|0|radartimer|553", "radar",
          "pl|0|radartimer|554", "radar", "pl|0|radartimer|0"]
    return s


def tracker(k, idx, pos, turn):
    return ["car|%d|pos|%s" % (k, "|".join(F(v) for v in pos)),
            "car|%d|turn|%s" % (k, F(turn)), "tracker|%d|%d" % (k, idx)]


def s_trackers():
    s = []
    me = (10.0, 20.0, 30.0)
    s += ["car|0|pos|%s" % "|".join(F(v) for v in me)]
    i = 0
    # The range along each axis and on the slant.
    for d in ((0, 0, 0), (10, 0, 0), (0, -49.99999, 0), (0, 0, 50),
              (50.00001, 0, 0), (-100, 0, 0), (30, 40, 0), (-30, 0, -40),
              (29.999, 40, 0.01), (30.0001, 40, 0), (7, -24, 1.5),
              (1e20, 0, 0), (0, 1e-20, 0), (0.1, 0.2, 0.3),
              (3.3, 4.7, 5.1), (12.345, 0.678, 9.101), (-21.7, 13.3, 0.9),
              (0.7, -33.1, 17.9), (float("nan"), 0, 0),
              (0, float("inf"), 0)):
        pos = tuple(m + v for m, v in zip(me, d))
        s += tracker(1, i % 7, pos, 0.1)
        i += 1
    # Two places whose scale is a bit off when the three squares are added
    # in the other order.
    for pos in ((-14.902144432067871, -6.754543304443359, 16.593727111816406),
                (32.12884521484375, -2.349153518676758, 35.712013244628906)):
        s += tracker(1, i % 7, pos, 0.1)
        i += 1
    # Each turn limit, at a few distances.
    for turn in (-0.6, -0.50000006, -0.5, -0.49999997, -0.25, -0.0, 0.0,
                 0.123456, 0.25, 0.3333, 0.49999997, 0.5, 0.50000006, 0.6,
                 float("nan"), float("inf"), float("-inf"), 1e-30):
        for d in (5.5, 25.0, 49.0):
            pos = (me[0] + d, me[1], me[2])
            s += tracker(2, i % 7, pos, turn)
            i += 1
    # Every tracker, and the player's own car.
    for idx in range(7):
        s += tracker(3, idx, (me[0] - idx, me[1] + 2 * idx, me[2]),
                     -0.4 + 0.13 * idx)
    s += ["car|0|turn|%s" % F(0.2), "tracker|0|0"]
    # Player 1, whose car is car 1.
    s += ["use|1"] + tracker(2, 4, (11.0, 22.0, 33.0), -0.3) + ["use|0"]
    return s


def s_meter():
    t = T0 + 200000
    s = ["g|timer|%d" % t]
    # The tickets, at an unchanged level.
    for n in (0, 1, 2, 3, 4, 5, 127, -1, -128, 2):
        s += ["tickets|0|%d" % n, "meter|0"]
    # A free run shows none; a race with no laps but not a single race
    # shows them.
    s += ["rp|Laps|0", "meter|0", "rp|RaceType|2", "meter|0",
          "rp|RaceType|1", "rp|BeACop|1", "meter|0", "rp|BeACop|0",
          "rp|Laps|3", "meter|0"]
    # Another car's tickets are not ours.
    s += ["tickets|1|3", "tickets|0|1", "meter|0", "use|1", "meter|0",
          "use|0"]
    # Up and down, from each level to each, the animations run between.
    for a, b in ((0, 1), (1, 2), (2, 4), (4, 3), (3, 1), (1, 0), (0, 4),
                 (4, 0), (0, 3), (3, 2), (2, 0), (0, 2), (2, 1), (1, 4),
                 (4, 1), (1, 3), (3, 4), (4, 2), (2, 3), (3, 0)):
        t += 10000
        s += ["g|timer|%d" % t, "meter|%d" % b]
        s += frames(t, 1, 3000, 5999, 6000, 6001)
    # Changes faster than the animations, and the same level again.
    t += 10000
    s += ["g|timer|%d" % t, "meter|2", "g|timer|%d" % (t + 100), "meter|4",
          "g|timer|%d" % (t + 200), "meter|1", "meter|1",
          "g|timer|%d" % (t + 300), "meter|3"]
    s += frames(t, 1000, 4000, 7000)
    # A level the meter did not leave itself, both ways.
    s += ["pl|0|prev|2", "meter|2", "pl|0|prev|0", "meter|0", "clear"]
    # No pursuit star: nothing at all.
    s += ["pl|0|star|none", "tickets|0|3", "meter|2", "pl|0|star|%s" % STAR,
          "tickets|0|0", "meter|0"]
    # Player 1's meter.
    t += 10000
    s += ["use|1", "g|timer|%d" % t, "pl|1|ppos|0|%s|%s" % (F(90.5), F(-0.0)),
          "meter|3"]
    s += frames(t, 2000, 7000)
    s += ["meter|0"] + frames(t, 9000, 12000) + ["use|0"]
    return s


def script():
    s = common()
    s += s_radar()
    s += s_beep()
    s += s_trackers()
    s += s_meter()
    return s


# =================================================================== model

class Model(ha.Model):
    def __init__(self):
        ha.Model.__init__(self)
        e = self.e
        for g in (G_SOUND, G_ELAPSED):
            e.put32(g, 0)
        self.cops = e.alloc(COPS_SIZE, align=16)
        e.write(self.cops, bytes(COPS_SIZE))
        e.put32(G_COPS, self.cops)
        self.cars = [e.alloc(CAR_SIZE, align=16) for _ in range(NUM_CARS)]
        for c in self.cars:
            e.write(c, bytes(CAR_SIZE))
        self.beep = e.alloc(16, align=16)
        self.intensity = 0
        self.flag = 0
        e.stub(S_INTENSITY, self.s_intensity)
        e.stub(S_PLAY, self.s_play)

    # ---- stubs

    def car_of(self, a):
        return self.cars.index(a) if a in self.cars else -1

    def s_intensity(self, em):
        m = em.reg[4] & M32
        c = em.reg[5] & M32
        self.emit("  radar m%d C%d -> %08x flag %d" % (
            1 if m == self.cops else 0, self.car_of(c), self.intensity,
            self.flag))
        self.e.put32(em.reg[6] & M32, self.flag & M32)
        em.fpr[0] = self.intensity

    def s_play(self, em):
        s = em.reg[4] & M32
        self.emit("  play %s %08x %08x %08x" % (
            "beep" if s == self.beep else "other", em.fpr[12] & M32,
            em.fpr[13] & M32, em.fpr[14] & M32))

    # ---- output

    def dump(self):
        e = self.e
        mem = e.mem
        for n, p in enumerate(self.players):
            for i in range(ha.NUM_SLOTS):
                a = e.u32(p + ha.ANIMS + 4 * i)
                key = "p%d.anim[%d]" % (n, i)
                if a == 0:
                    self.note(key, "none")
                    continue
                k = self.allocs.index(a) if a in self.allocs else -1
                self.note(key, "a%d %s %s %s %s" % (
                    k, bytes(mem[a:a + 72]).hex(), self.name(e.u32(a + 72)),
                    self.name(e.u32(a + 76)),
                    bytes(mem[a + 80:a + ha.ANIM_SIZE]).hex()))
            self.note("p%d.TotalScore" % n, "%08x" % e.u32(p + ha.TOTAL))
            self.note("p%d.cop" % n, "radar %08x prev %d" % (
                e.u32(p + 1408), s32(e.u32(p + 1104))))
        self.dump_objects()

    # ---- ops

    def set_player(self, k, n, a):
        e = self.e
        p = self.players[k]
        if n in PLAYER_WORDS:
            e.put32(p + PLAYER_WORDS[n], int(a[0], 0) & M32)
        elif n == "car":
            e.put32(p + P_CAR, self.cars[int(a[0])])
        elif n == "beep":
            e.put32(p + P_BEEP, self.beep if int(a[0]) else 0)
        elif n == "star":
            e.put32(p + P_STAR, self.obj(a[0]))
        elif n in ("level", "x", "light", "tracker"):
            base = {"level": P_LEVEL, "x": P_X, "light": P_LIGHT,
                    "tracker": P_TRACKER}[n]
            e.put32(p + base + 4 * int(a[0]), self.obj(a[1]))
        elif n == "ppos":
            self.vec(p + P_PPOS + 8 * int(a[0]), a[1:3])
        else:
            raise ValueError(n)

    def op(self, a):
        e = self.e
        o = a[0]
        p = self.player()
        v = lambda i: int(a[i], 0) & M32      # noqa: E731
        if o == "g" and a[1] in ("sound", "elapsed"):
            e.put32(G_SOUND if a[1] == "sound" else G_ELAPSED, v(2))
        elif o == "car":
            c = self.cars[int(a[1])]
            if a[2] == "index":
                e.write(c + CAR_INDEX, struct.pack("<H", v(3) & 0xffff))
            elif a[2] == "pos":
                self.vec(c + CAR_POS, a[3:6])
            elif a[2] == "turn":
                e.put32(c + CAR_TURN, v(3))
            else:
                raise ValueError(a[2])
        elif o == "tickets":
            e.mem[self.cops + TICKETS + PULLOVER * int(a[1])] = v(2) & 0xff
        elif o == "seam":
            self.intensity = v(1)
            self.flag = s32(v(2))
        elif o == "radar":
            e.call(F_RADAR, p, limit=4000000)
        elif o == "tracker":
            e.call(F_TRACKER, p, self.cars[int(a[1])], v(2), limit=1000000)
        elif o == "meter":
            e.call(F_METER, p, v(1), limit=4000000)
        else:
            ha.Model.op(self, a)
            return
        self.dump()


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="hudcop_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


run_harness = fc.run_harness
diff = pcc.diff
write_script = fc.write_script


# ============================================================= mutations

H = HUDCOP


def M(name, before, after, rel=H):
    return (name, rel, before, after)


MUTATIONS = [
    # The radar's lights.
    M("radar-steps", "#define RADAR_STEPS         11.0f", "#define RADAR_STEPS         10.0f"),
    M("radar-lit-rounded", "    lit = ee_trunc_w(intensity * RADAR_STEPS);",
      "    lit = (int32_t)(intensity * RADAR_STEPS + 0.5f);"),
    M("radar-no-cap", "    if (lit > RADAR_MOST)\n        lit = RADAR_MOST;\n", ""),
    M("radar-cap-9", "        lit = RADAR_MOST;", "        lit = RADAR_MOST - 1;"),
    M("radar-flag-positive", "    row = flag != 0 ? 2 : 0;", "    row = flag > 0 ? 2 : 0;"),
    M("radar-flag-byte", "    row = flag != 0 ? 2 : 0;", "    row = (flag & 0xff) != 0 ? 2 : 0;"),
    M("radar-flag-ignored", "    row = flag != 0 ? 2 : 0;", "    row = 0;"),
    M("radar-lit-row", "RadarColours[row][i]);", "RadarColours[row + 1][i]);"),
    M("radar-unlit-row", "RadarColours[row + 1][i]);", "RadarColours[row][i]);"),
    M("radar-lit-le", "    for (i = 0; i < lit; i++)", "    for (i = 0; i <= lit; i++)"),
    M("radar-unlit-short", "    for (; i < RADAR_LIGHTS; i++)", "    for (; i < RADAR_LIGHTS - 1; i++)"),
    M("radar-null-light", "    if (o != NULL)\n        flailerbitmap_set_color(", "    flailerbitmap_set_color("),
    M("radar-car", "                                                           p->MyCar, &flag);",
      "                                                           NULL, &flag);"),

    # RadarColours, one reachable entry of each part of each row.
    M("colour-r0-green", "    { 0xff008800, 0xff008800, 0xff008800, 0xff008800, 0xff008800,",
      "    { 0xff008800, 0xff008800, 0xff008800, 0xff008800, 0xff008801,"),
    M("colour-r0-amber", "0xff008800,\n      0xff004488, 0xff004488, 0xff004488,",
      "0xff008800,\n      0xff004488, 0xff004488, 0xff004489,"),
    M("colour-r0-red", "      0xff000088, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004000",
      "      0xff000089, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004000"),
    M("colour-r0-red-9", "      0xff000088, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004000",
      "      0xff000088, 0xff000089, 0xff000088, 0xff000088 },\n    { 0x80004000"),
    M("colour-r1-green", "    { 0x80004000, 0x80004000,", "    { 0x80004001, 0x80004000,"),
    M("colour-r1-amber", "0x80004000,\n      0x80002240,", "0x80004000,\n      0x80002241,"),
    M("colour-r1-red", "0x80000040 },\n    { 0xff008888", "0x80000041 },\n    { 0xff008888"),
    M("colour-r2-green", "    { 0xff008888, 0xff008888,", "    { 0xff008889, 0xff008888,"),
    M("colour-r2-amber", "0xff008888,\n      0xff004488,", "0xff008888,\n      0xff004489,"),
    M("colour-r2-red", "      0xff000088, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004040",
      "      0xff000089, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004040"),
    M("colour-r2-red-9", "      0xff000088, 0xff000088, 0xff000088, 0xff000088 },\n    { 0x80004040",
      "      0xff000088, 0xff000089, 0xff000088, 0xff000088 },\n    { 0x80004040"),
    M("colour-r3-green", "    { 0x80004040, 0x80004040,", "    { 0x80004041, 0x80004040,"),
    M("colour-r3-amber", "0x80004040,\n      0x80002240,", "0x80004040,\n      0x80002241,"),
    M("colour-r3-red", "0x80000040 },\n};", "0x80000041 },\n};"),

    # The swells.
    M("swell-from-gt", "    if (lit >= RADAR_SWELL_FROM)", "    if (lit > RADAR_SWELL_FROM)"),
    M("swell-from-8", "#define RADAR_SWELL_FROM     9", "#define RADAR_SWELL_FROM     8"),
    M("swell-two-at-9", "#define RADAR_SWELL_TWO     10", "#define RADAR_SWELL_TWO      9"),
    M("swell-slot", "        swell(p, 16, 10, 8);", "        swell(p, 15, 10, 8);"),
    M("swell-light", "        swell(p, 16, 10, 8);", "        swell(p, 16, 11, 8);"),
    M("swell-off", "        swell(p, 16, 10, 8);", "        swell(p, 16, 10, 7);"),
    M("swell-two-slot", "        swell(p, 17, 11, 9);", "        swell(p, 18, 11, 9);"),
    M("swell-two-off", "        swell(p, 17, 11, 9);", "        swell(p, 17, 11, 8);"),
    M("swell-no-hide-10", "    else\n        set_vis(p->pFlailerRadarLight[10], FLAILER_OBJECT_INVISIBLE);",
      "    else\n        set_vis(p->pFlailerRadarLight[10], FLAILER_OBJECT_VISIBLE);"),
    M("swell-no-hide-11", "    else\n        set_vis(p->pFlailerRadarLight[11], FLAILER_OBJECT_INVISIBLE);",
      "    else\n        ;"),
    M("swell-by", "#define RADAR_SWELL_BY     -10.0f", "#define RADAR_SWELL_BY      -9.0f"),
    M("swell-to-y", "    to.y = at.y + RADAR_SWELL_BY;", "    to.y = at.y - RADAR_SWELL_BY;"),
    M("swell-at-y", "    at.y = b->Y;", "    at.y = b->X;"),
    M("swell-scale-to", "    bVector2 scale_to = { 2.0f, 2.0f };", "    bVector2 scale_to = { 2.0f, 1.0f };"),
    M("swell-scale-from", "    bVector2 scale_from = { 1.0f, 1.0f };",
      "    bVector2 scale_from = { 1.0f, 0.5f };"),
    M("swell-alpha-to", "128, 0, RADAR_SWELL_SECONDS,", "128, 1, RADAR_SWELL_SECONDS,"),
    M("swell-alpha-from", "128, 0, RADAR_SWELL_SECONDS,", "127, 0, RADAR_SWELL_SECONDS,"),
    M("swell-seconds", "#define RADAR_SWELL_SECONDS  0.2f", "#define RADAR_SWELL_SECONDS  0.25f"),
    M("swell-keep", "        (uint32_t)WorldTimer, 0);\n}", "        (uint32_t)WorldTimer, 1);\n}"),
    M("swell-real-timer", "        (uint32_t)WorldTimer, 0);\n}", "        (uint32_t)RealTimer, 0);\n}"),

    # The beep.
    M("beep-sound-ignored", "    if (!SoundEnabled || lit <= 0) {", "    if (lit <= 0) {"),
    M("beep-lit-zero", "    if (!SoundEnabled || lit <= 0) {", "    if (!SoundEnabled || lit < 0) {"),
    M("beep-timer-kept", "        p->RadarTimer.PackedTime = 0;\n        return;\n", "        return;\n"),
    M("beep-step-truncated", "        timer_set_time(&step, WorldTimeElapsed);",
      "        step.PackedTime = (uint32_t)(int32_t)(WorldTimeElapsed * 4000.0f);"),
    M("beep-step-replaces", "        p->RadarTimer.PackedTime += step.PackedTime;",
      "        p->RadarTimer.PackedTime = step.PackedTime;"),
    M("beep-per-light", "#define RADAR_BEEP_PER_LIGHT -0.038333334f", "#define RADAR_BEEP_PER_LIGHT -0.038f"),
    M("beep-at", "#define RADAR_BEEP_AT        0.5f", "#define RADAR_BEEP_AT        0.45f"),
    M("beep-le", "\n        < (float)(int32_t)p->RadarTimer.PackedTime", "\n        <= (float)(int32_t)p->RadarTimer.PackedTime"),
    M("beep-unsigned", "< (float)(int32_t)p->RadarTimer.PackedTime", "< (float)p->RadarTimer.PackedTime"),
    M("beep-tick", "#define TICK_SECONDS         0.00025f", "#define TICK_SECONDS         0.00026f"),
    M("beep-no-reset", "        p->RadarTimer.PackedTime = 0;\n        if (p->pRadarBeep", "        if (p->pRadarBeep"),
    M("beep-volume", "gSamplePlayFn(p->pRadarBeep, 1.0f, 0.0f, 0.0f);", "gSamplePlayFn(p->pRadarBeep, 0.5f, 0.0f, 0.0f);"),
    M("beep-pan", "gSamplePlayFn(p->pRadarBeep, 1.0f, 0.0f, 0.0f);", "gSamplePlayFn(p->pRadarBeep, 1.0f, 0.0f, 1.0f);"),
    M("beep-silent", "            gSamplePlayFn(p->pRadarBeep, 1.0f, 0.0f, 0.0f);", "            ;"),

    # The trackers.
    M("tracker-range", "#define TRACKER_RANGE     50.0f", "#define TRACKER_RANGE     49.999f"),
    M("tracker-range-lt", "    if (!(d <= TRACKER_RANGE))", "    if (!(d < TRACKER_RANGE))"),
    M("tracker-range-nan", "    if (!(d <= TRACKER_RANGE))", "    if (d > TRACKER_RANGE)"),
    M("tracker-dist-order", "    d = sqrtf((dx * dx + dy * dy) + dz * dz);", "    d = sqrtf(dx * dx + (dy * dy + dz * dz));"),
    M("tracker-dist-no-z", "    d = sqrtf((dx * dx + dy * dy) + dz * dz);", "    d = sqrtf(dx * dx + dy * dy);"),
    M("tracker-dy-x", "    dy = b->y - a->y;", "    dy = b->x - a->y;"),
    M("tracker-turn-lo", "    if (turn < -TRACKER_TURN || ", "    if (turn <= -TRACKER_TURN || "),
    M("tracker-turn-hi", "|| TRACKER_TURN < turn)", "|| TRACKER_TURN <= turn)"),
    M("tracker-turn-nan", "    if (turn < -TRACKER_TURN || TRACKER_TURN < turn)",
      "    if (!(turn >= -TRACKER_TURN && turn <= TRACKER_TURN))"),
    M("tracker-turn", "#define TRACKER_TURN       0.5f", "#define TRACKER_TURN       0.45f"),
    M("tracker-turn-own", "    turn = c->fAngleToCamera;", "    turn = p->MyCar->fAngleToCamera;"),
    M("tracker-width", "#define TRACKER_WIDTH    400.0f", "#define TRACKER_WIDTH    401.0f"),
    M("tracker-left", "#define TRACKER_LEFT        120", "#define TRACKER_LEFT        121"),
    M("tracker-x-rounded", "    t->X = (float)(ee_trunc_w((turn + TRACKER_TURN) * TRACKER_WIDTH)\n                   + TRACKER_LEFT);",
      "    t->X = (float)((int32_t)((turn + TRACKER_TURN) * TRACKER_WIDTH + 0.5f)\n                   + TRACKER_LEFT);"),
    M("tracker-x-float", "    t->X = (float)(ee_trunc_w((turn + TRACKER_TURN) * TRACKER_WIDTH)\n                   + TRACKER_LEFT);",
      "    t->X = (turn + TRACKER_TURN) * TRACKER_WIDTH + TRACKER_LEFT;"),
    M("tracker-per-unit", "#define TRACKER_PER_UNIT   0.02f", "#define TRACKER_PER_UNIT   0.021f"),
    M("tracker-no-cap", "    if (1.0f < s)\n        s = 1.0f;\n", ""),
    M("tracker-scale-y", "    t->ScaleY = s + s;", "    t->ScaleY = s;"),
    M("tracker-scale-x", "    t->ScaleX = s + s;", "    t->ScaleX = s * 3.0f;"),
    M("tracker-hidden", "    flailerobject_set_visibility(t, FLAILER_OBJECT_VISIBLE);",
      "    flailerobject_set_visibility(t, FLAILER_OBJECT_INVISIBLE);"),
    M("tracker-index", "    t = p->pFlailerTracker[index];", "    t = p->pFlailerTracker[index / 2];"),

    # The pursuit meter's tickets.
    M("meter-no-star", "    if (p->pFlailerPursuitStar == NULL)\n        return;\n", ""),
    M("meter-tickets-gt", "        if (tickets >= 4)", "        if (tickets > 4)"),
    M("meter-tickets-cap", "            tickets = PURSUIT_TICKETS;", "            tickets = 2;"),
    M("meter-free-run", "    if (race_parameters_is_free_run(&TheRaceParameters))\n        tickets = 0;\n", ""),
    M("meter-x-hidden", "        set_vis(p->pFlailerPursuitX[i], FLAILER_OBJECT_VISIBLE);",
      "        set_vis(p->pFlailerPursuitX[i], FLAILER_OBJECT_INVISIBLE);"),
    M("meter-x-kept", "    for (; i < PURSUIT_TICKETS; i++)\n        set_vis(p->pFlailerPursuitX[i], FLAILER_OBJECT_INVISIBLE);\n", ""),
    M("meter-same-level", "    if (level == prev)\n        return;\n", ""),

    # The bars in.
    M("in-from", "#define PURSUIT_IN_FROM   300.0f", "#define PURSUIT_IN_FROM   290.0f"),
    M("in-to-x", "        to.x = PURSUIT_IN_FROM + at.x;", "        to.x = at.x;"),
    M("in-to-y", "        to.y = 0.0f + at.y;", "        to.y = at.y;"),
    M("in-at-y", "        at.y = p->PursuitObjectPos[i].y;", "        at.y = p->PursuitObjectPos[i].x;"),
    M("in-scale", "#define PURSUIT_IN_SCALE    4.0f", "#define PURSUIT_IN_SCALE    3.0f"),
    M("in-scale-to", "        bVector2 scale_to = { 1.0f, 1.0f };", "        bVector2 scale_to = { 1.0f, 2.0f };"),
    M("in-alpha-from", "&scale_from, &scale_to, 0, 128, PURSUIT_IN_SECONDS,",
      "&scale_from, &scale_to, 1, 128, PURSUIT_IN_SECONDS,"),
    M("in-alpha-to", "&scale_from, &scale_to, 0, 128, PURSUIT_IN_SECONDS,",
      "&scale_from, &scale_to, 0, 127, PURSUIT_IN_SECONDS,"),
    M("in-seconds", "#define PURSUIT_IN_SECONDS  1.5f", "#define PURSUIT_IN_SECONDS  1.25f"),
    M("in-keep", "            (uint32_t)WorldTimer, 1);\n    }\n    if (level < prev) {",
      "            (uint32_t)WorldTimer, 0);\n    }\n    if (level < prev) {"),
    M("slot", "#define PURSUIT_SLOT        2", "#define PURSUIT_SLOT        3"),
    M("in-slot", "            p, i + PURSUIT_SLOT,\n            (struct FlailerBitmapChunk *)(void *)p->pFlailerPursuitLevel[i],",
      "            p, i + 1,\n            (struct FlailerBitmapChunk *)(void *)p->pFlailerPursuitLevel[i],"),
    M("in-from-next", "    for (i = prev; i < level && i < PURSUIT_BARS; i++) {",
      "    for (i = prev + 1; i < level && i < PURSUIT_BARS; i++) {"),
    M("in-through-level", "    for (i = prev; i < level && i < PURSUIT_BARS; i++) {",
      "    for (i = prev; i <= level && i < PURSUIT_BARS; i++) {"),
    M("in-bar", "(void *)p->pFlailerPursuitLevel[i],\n            &at, &to, &scale_from,",
      "(void *)p->pFlailerPursuitLevel[prev],\n            &at, &to, &scale_from,"),

    # The bars out.
    M("out-only-two", "    if (level < prev) {", "    if (level < prev - 1) {"),
    M("out-last", "        last = level - 1;", "        last = level;"),
    M("out-floor", "        if (last < 0)\n            last = 0;", "        if (last < 0)\n            last = 1;"),
    M("out-gt", "        for (i = prev - 1; i >= last; i--) {", "        for (i = prev - 1; i > last; i--) {"),
    M("out-to-x", "            to.x = PursuitOut[i].x + at.x;", "            to.x = at.x;"),
    M("out-to-y", "            to.y = PursuitOut[i].y + at.y;", "            to.y = at.y - PursuitOut[i].y;"),
    M("out-table-x", "    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 50.0f },",
      "    { 1.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 50.0f },"),
    M("out-table-3", "    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 50.0f },",
      "    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, 50.0f }, { 0.0f, 50.0f },"),
    M("out-table-4", "    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 50.0f },",
      "    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 40.0f },"),
    M("out-alpha-to", "&at, &to, &one, &one, 128, 0, 1.0f,", "&at, &to, &one, &one, 128, 1, 1.0f,"),
    M("out-alpha-from", "&at, &to, &one, &one, 128, 0, 1.0f,", "&at, &to, &one, &one, 127, 0, 1.0f,"),
    M("out-seconds", "128, 0, 1.0f, (uint32_t)WorldTimer, 1);", "128, 0, 1.5f, (uint32_t)WorldTimer, 1);"),
    M("out-keep", "128, 0, 1.0f, (uint32_t)WorldTimer, 1);", "128, 0, 1.0f, (uint32_t)WorldTimer, 0);"),
    M("out-scale", "            bVector2 one = { 1.0f, 1.0f };", "            bVector2 one = { 1.0f, 0.5f };"),
    M("out-slot", "                p, i + PURSUIT_SLOT,", "                p, i + 1,"),
    M("prev-kept", "    p->PrevPursuitLevel = level;\n", ""),
]

EQUIVALENT = {
    "swell-real-timer":
        "the bitmap's HudStartAnimation drops its timer; the animator reads "
        "WorldTimer itself",
    "in-to-y":
        "the animator keeps to - from, and (0 + y) - y is y - y for every y, "
        "-0 included (both +0)",
    "out-to-x":
        "PursuitOut's x are all 0, and the animator keeps to - from, so "
        "(0 + x) - x is x - x",
    "tracker-no-cap":
        "d is at most 50 by then, and 50 x 0.02f rounds to 1.0, not above",
    "meter-same-level":
        "at an unchanged level neither loop runs and PrevPursuitLevel takes "
        "the value it holds",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text(encoding="latin-1").splitlines(),
                quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text(encoding="latin-1")
                         .splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    indir.cleanup()

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
