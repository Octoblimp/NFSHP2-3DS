#!/usr/bin/env python3
"""Cross-check TASKS 72d-1, the replay's DoSnapshots for the race's setup,
the clock, the joystick types, the camera shakers, the NIS player, the
traffic, the track graph, the race and the player, against the retail
image, SLES_507.31.

**What is checked**: RideInfo, DriverInfo, cPlayerSettings and
RaceParameters (with its drivers), WorldTimeDoSnapshot, JoystickDoSnapshot,
tShaker and SnapshotCameraShakers, NisManager, TrafficCar (through its
table and direct), TrafficTeleporter, tTrackGraph, RacingCar, Race and
Player. Each is taken, restored over other values, checksummed and
verified.

**The layouts** are the port's headers, parsed by carsnap_check.py (which
this imports and extends): every field at the offset its comment gives,
retail's where the port's order differs (DriverInfo). The harness,
tools/src/racesnap_test.c, gets the same field list as a generated table
of offsetof and sizeof, so each side writes and dumps a field at its own
offset, and a pointer prints as the object and field it points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot, the snapshots, Average's and the world's
pointer move, and CarMover's empty DoSnapshot. Recorded on both sides, as
lines both print: GetCharacterInfo (a place in the `chars` block), the NIS
player's Load, ServiceResourceLoading, StopAnimating and StartAnimating,
and Player::SetInputMode. The globals (the clock's seven words, the
joystick types, the shakers and their envelope, TheRaceParameters,
pCurrentWorld and pCurrentRace) are set up by ops of their own on both
sides.

What the linked port files reach outside the snapshots is stubbed by
tools/src/racesnap_stubs.c and racesnap_stubdata.c, which `--stubs` writes
from the link's undefined symbols; each stubbed function stops the run
with an UNREACHED line.

    python tools/racesnap_check.py
    python tools/racesnap_check.py --stubs
    python tools/racesnap_check.py --fields [CLASS]
    python tools/racesnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/racesnap_check.py --dump out/racesnap
"""
import argparse
import os
import re
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carsnap_check as csc             # noqa: E402
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import retail_model                     # noqa: E402
from carsnap_check import (fill, fl, i32, i16, i8, cycle, flatten,  # noqa
                           one, alloc_size)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "racesnap_test.c"
STUBS = ROOT / "tools" / "src" / "racesnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "racesnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in (
    "replay.c", "p32.c", "vtable.c",
    "raceparams.c", "playersettings.c", "realtime.c", "joyevent.c",
    "shake.c", "nismanager.c", "trafficcar.c", "traffictele.c",
    "trackgraph.c", "racecore.c", "playersnap.c", "average.c", "world.c",
    "bticker.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
P_CURRENT_RACE = GP - 22272
WORLD_TIME = GP - 19576                 # the clock's seven words
JOYSTICK_TYPES = GP - 21920
SHAKE_ENVELOPE = GP - 21848
CAMERA_SHAKERS = 0x002fa820
THE_RACE_PARAMETERS = 0x0031a898
TRAFFICCAR_VTABLE = 0x002b2190

S_CHARINFO = 0x001d9590
S_SET_INPUT_MODE = 0x001776b0
S_NIS_LOAD = 0x001b1568
S_NIS_SERVICE = 0x00199788
S_NIS_STOP = 0x001b2a70
S_NIS_START = 0x001b2840

WORLD_SIZE = 1024

# ================================================================ the layout

csc.HEADERS.update({
    "Average": "average.h", "DriverInfo": "car.h",
    "cPlayerSettings": "playersettings.h",
    "tGlobalDisplaySettings": "race.h", "RaceParameters": "race.h",
    "RacingCar": "race.h", "Race": "race.h",
    "tShaker": "shake.h", "NisManager": "nismanager.h",
    "TrafficCar": "trafficcar.h", "TrafficTeleporter": "traffictele.h",
    "tTrackGraph": "trackgraph.h", "tTrackGraphEdge": "trackgraph.h",
    "Player": "player.h",
})
csc.MACROS.update({"TRAFFIC_ROUTES_EACH": 10, "RACE_MAX_RACING_CARS": 8,
                   "RACE_MAX_BOUNDARIES": 5, "TRACKGRAPH_MAX_VERTICES": 100,
                   # Retail's 400, cut to keep the dumps short: no script
                   # graph has more than 16.
                   "TRACKGRAPH_MAX_EDGES": 16})
for _t in ("eTrackDirection", "DriverType", "eRaceStage", "JoystickPort"):
    csc.TYPES[_t] = (4, False)
csc.SKIP_TYPES.update({"NISOverlayManager", "NisRenderInfo", "eModel",
                       "tTrackGraphVertex"})
csc.RETAIL_SIZE.update({"tGlobalDisplaySettings": 8, "tShaker": 32,
                        "DriverInfo": 24, "Average": 16})
# The port keeps the demo's DriverInfo order; retail's offsets.
csc.RETAIL_OFF.update({
    ("DriverInfo", "EliminatedRank"): 0,
    ("DriverInfo", "UniqueDriverNumber"): 1,
    ("DriverInfo", "CharacterNumber"): 2, ("DriverInfo", "SkillLevel"): 3,
    ("DriverInfo", "StartingPosition"): 4,
    ("DriverInfo", "TheDriverType"): 8,
    ("DriverInfo", "CurrentRideInfo"): 12,
    ("DriverInfo", "pCharacterInfo"): 20,
})

# FIELD_RE reads no function pointer: Player's callback, a pointer.
_struct_body = csc.struct_body


def _player_body(name):
    body, size = _struct_body(name)
    if name == "Player":
        body = re.sub(r"void\s*\(\*NisFinishedCallback\)\(int32_t\);",
                      "void *NisFinishedCallback;", body)
    return body, size


csc.struct_body = _player_body

# The records a script can make, in the order of the generated table.
CLASSES = ["Car", "Average", "RideInfo", "DriverInfo", "cPlayerSettings",
           "RaceParameters", "tShaker", "NisManager", "TrafficCar",
           "TrafficTeleporter", "tTrackGraph", "RacingCar", "Race",
           "Player"]

# ============================================================ the scenarios


def sc_setup():
    out = one("RideInfo", "rideinfo", "ri",
              change=["set|ri|SkinNumber|" + i8(0x7c)])
    out += one("cPlayerSettings", "playersettings", "pss",
               change=["set|pss|TransmissionType|" + i8(0x81)])
    # The character block GetCharacterInfo answers into.
    out += ["newb|chars|4096"]
    for k, (ch, rch) in enumerate(((5, -1), (-1, 0x7f), (-128, 3))):
        d = "dri%d" % k
        fix = ["set|%s|CharacterNumber|%s" % (d, i8(ch))]
        out += ["# driverinfo %d" % k, "new|%s|DriverInfo" % d]
        out += fill(d, "DriverInfo", "a") + fix
        out += cycle(["call|driverinfo|" + d], ["dump|" + d],
                     fill(d, "DriverInfo", "b") +
                     ["set|%s|CharacterNumber|%s" % (d, i8(rch)),
                      "link|%s|pCharacterInfo|0|-" % d],
                     ["set|%s|SkillLevel|%s" % (d, i8(0x55))])
    # RaceParameters: its drivers, none and all fourteen.
    out += ["new|drvt|DriverInfo|14"]
    chars = (3, -1, 12, 0, -1, 7, 99, -1, 1, 2, -1, 40, 8, -2)

    def drivers(seed):
        o = []
        for i in range(14):
            o += fill("drvt[%d]" % i, "DriverInfo", seed)
            o += ["set|drvt[%d]|CharacterNumber|%s" % (i, i8(chars[i]))]
        return o
    for k, n in enumerate((3, 0, 14)):
        r = "rp%d" % k
        fix = ["set|%s|NumDriverInfo|%s" % (r, i32(n)),
               "link|%s|pDriverInfoTable|drvt|-" % r]
        out += ["# raceparams %d" % k, "new|%s|RaceParameters" % r]
        out += fill(r, "RaceParameters", "a") + fix + drivers("a%d" % k)
        out += cycle(["call|raceparams|" + r], ["dump|" + r, "dump|drvt"],
                     fill(r, "RaceParameters", "b") + fix +
                     drivers("b%d" % k),
                     ["set|%s|TrafficDensity|%s" % (r, fl(0.125))])
    return out


WT_A = (0x11223344, 2.5, 777, 31, 0.0625, 0.5, 9)
WT_B = (0x0badf00d, -7.75, -3, 1000, 0.03125, 0.25, -40)


def wt(words):
    t, sec, w, fr, el, elf, loop = words
    return "wtset|" + (i32(t) + fl(sec) + i32(w) + i32(fr) + fl(el) +
                       fl(elf) + i32(loop))


def sc_globals():
    out = ["# worldtime", wt(WT_A)]
    # The cycle's timer op sets WorldTimer and WorldLoopCounter first.
    took = (1234,) + WT_A[1:6] + (56,)
    changed = took[:4] + (0.75,) + took[5:]
    out += cycle(["gcall|worldtime"], ["wtdump"], [wt(WT_B)], [wt(changed)])
    out += ["# joystick", "global|joy", "setb|joy|0|a5ff"]
    out += cycle(["gcall|joystick"], ["dump|joy"], ["setb|joy|0|0102"],
                 ["setb|joy|1|07"])
    out += ["# shakers", "global|env", "global|shakers"]
    for k, (a0, a1, r0, r1) in enumerate((("env", "0", "0", "chars"),
                                          ("chars", "env", "0", "0"))):
        lk = ["link|shakers[0]|pAmplitude|%s|-" % a0,
              "link|shakers[1]|pAmplitude|%s|-" % a1]
        rl = ["link|shakers[0]|pAmplitude|%s|-" % r0,
              "link|shakers[1]|pAmplitude|%s|-" % r1]
        out += ["# shakers %d" % k]
        out += fill("shakers[0]", "tShaker", "a%d" % k) + \
            fill("shakers[1]", "tShaker", "a%d" % k) + lk
        out += cycle(["gcall|shakers"], ["dump|shakers", "dump|env"],
                     fill("shakers[0]", "tShaker", "b%d" % k) +
                     fill("shakers[1]", "tShaker", "b%d" % k) + rl,
                     ["set|shakers[1]|fFrequency|" + fl(3.5)])
    # One alone.
    out += ["# tshaker"]
    out += cycle(["call|tshaker|shakers[1]"], ["dump|shakers"],
                 fill("shakers[1]", "tShaker", "c") +
                 ["link|shakers[1]|pAmplitude|env|-"])
    return out


def sc_world():
    out = ["# the world"]
    for c, num in (("c0", 2), ("c1", 5), ("c2", 300), ("c3", 44),
                   ("c4", 200)):
        out += ["new|%s|Car" % c, "set|%s|DriverNumber|%s" % (c, i16(num))]
    out += ["world|c0,c1,c2,c3,c4"]
    return out


NIS_KEEP = ("LoadedNisNumber", "LoadingNisNumber", "NisNumber", "Playing")


def nis_lines(m, playing, loaded, nis, car, other):
    return ["set|%s|Playing|%s" % (m, i32(playing)),
            "set|%s|LoadedNisNumber|%s" % (m, i32(loaded)),
            "set|%s|LoadingNisNumber|%s" % (m, i32(-1)),
            "set|%s|NisNumber|%s" % (m, i32(nis)),
            "link|%s|PlayerCar|%s|-" % (m, car),
            "link|%s|OtherCar|%s|-" % (m, other)]


def sc_nis():
    out = []
    # Playing with its NIS loaded; playing one not loaded (a load and the
    # service); not playing; a word whose byte is 0.
    cases = ((1, 3, 3, 1, 3, 3), (1, 2, 3, 1, 2, 3), (0, 4, 3, 0, 1, 3),
             (0x100, 3, 3, 0x100, 5, 5))
    for k, (pl, ld, nis, rpl, rld, rnis) in enumerate(cases):
        m = "nm%d" % k
        out += ["# nismanager %d" % k, "new|%s|NisManager" % m]
        out += fill(m, "NisManager", "a", NIS_KEEP) + \
            nis_lines(m, pl, ld, nis, "c1", ("0", "c2", "c4", "c0")[k])
        refill = fill(m, "NisManager", "b", NIS_KEEP) + \
            nis_lines(m, rpl, rld, rnis, "c3", "0")
        out += cycle(["call|nismanager|" + m], ["dump|" + m], refill,
                     ["set|%s|CamNumber|%s" % (m, i32(66))])
    return out


def sc_traffic():
    fix = ["vt|tc|Mover._vtable|TrafficCar", "link|tc|pCar|c0|-"]
    out = ["# trafficcar", "new|tc|TrafficCar"] + \
        fill("tc", "TrafficCar", "a") + fix
    out += cycle(["vcall|tc|Mover._vtable|24"], ["dump|tc"],
                 fill("tc", "TrafficCar", "b") + fix,
                 ["set|tc|Speed|" + fl(12.5)])
    out += cycle(["call|trafficcar|tc"], ["dump|tc"],
                 fill("tc", "TrafficCar", "c") + fix,
                 ["set|tc|Position|" + fl(1.0, -2.0)])
    out += one("TrafficTeleporter", "traffictele", "tt",
               change=["set|tt|TimeUntilTeleport|" + fl(4.0)])
    return out


def graph_lines(g, n, seed):
    out = ["set|%s|nNumEdges|%s" % (g, i32(n))]
    vals = (1, 0, 0x100, 1, 0, 0, 0x80000000, 1)
    for i in range(16):
        out += ["set|%s|Edge[%d].bCloakable|%s"
                % (g, i, i32(vals[(i + seed) % len(vals)]))]
    return out


def sc_trackgraph():
    out = []
    for k, n in enumerate((12, 16, 0)):
        g = "tg%d" % k
        out += ["# trackgraph %d" % k, "new|%s|tTrackGraph" % g]
        out += fill(g, "tTrackGraph", "a") + graph_lines(g, n, k)
        out += cycle(["call|trackgraph|" + g], ["dump|" + g],
                     fill(g, "tTrackGraph", "b") + graph_lines(g, n, k),
                     ["set|%s|bHasCloakedEdge|%s" % (g, i32(0x5a))])
    return out


def sc_race():
    out = ["# racingcar", "global|trp", "new|rce|Race", "race|rce"]
    for k, (rt, fin) in enumerate(((2, 2), (2, -1), (2, 5), (0, 2),
                                   (0x102, 1))):
        r = "rcar%d" % k
        fix = ["set|trp|RaceType|" + i32(rt),
               "set|rce|FinishLineBoundaryNumber|" + i8(fin)]
        out += ["# racingcar %d" % k, "new|%s|RacingCar" % r] + fix
        out += fill(r, "RacingCar", "a") + ["link|%s|pCar|c%d|-" % (r, k)]
        out += cycle(["call|racingcar|" + r], ["dump|" + r],
                     fill(r, "RacingCar", "b"),
                     ["set|%s|CurrentLapNumberExact|%s" % (r, fl(1.5))])
    perms = ((3, 0, 7, 1, 2, 6, 5, 4), (0, 1, 2, 3, 4, 5, 6, 7),
             (7, 7, 0, 2, 2, 1, 6, 3))

    def links(race, perm):
        return ["link|%s|pRacingCars[%d]|%s|RacingCarTable[%d]"
                % (race, i, race, p) for i, p in enumerate(perm)]
    for k, (n, rt) in enumerate(((3, 2), (8, 0), (0, 2))):
        race = "race%d" % k
        fix = ["set|%s|NumRacingCars|%s" % (race, i32(n)),
               "set|%s|FinishLineBoundaryNumber|%s" % (race, i8(1 + k)),
               "set|trp|RaceType|" + i32(rt)]
        out += ["# race %d" % k, "new|%s|Race" % race, "race|" + race]
        out += fill(race, "Race", "a") + fix + links(race, perms[k])
        out += cycle(["call|race|" + race], ["dump|" + race],
                     fill(race, "Race", "b") + fix +
                     links(race, perms[(k + 1) % 3]),
                     ["set|%s|NumLapsInRace|%s" % (race, i32(0x77))])
    return out


def sc_player():
    out = ["# player", "newb|pavd|1024", "new|pav|Average",
           "new|pnm|NisManager", "new|pl|Player"]

    def setup(seed, slots, playing, nis):
        o = fill("pl", "Player", seed)
        o += ["link|pl|pAverageSpeedRatio|pav|-",
              "link|pl|pNisManager|pnm|-", "link|pl|MyCar|c1|-"]
        o += fill("pav", "Average", seed) + \
            ["set|pav|nSlots|" + i8(slots), "link|pav|pData|pavd|-"]
        o += ["setb|pavd|0|" + fl(*[(i * 7 % 23 - 11) / 4.0 + len(seed)
                                     for i in range(slots)])]
        o += fill("pnm", "NisManager", seed, NIS_KEEP) + \
            nis_lines("pnm", playing, nis, nis, "c4", "c0")
        return o
    out += setup("a", 6, 1, 2)
    out += cycle(["call|player|pl"],
                 ["dump|pl", "dump|pav", "dump|pavd", "dump|pnm"],
                 setup("bb", 3, 0, 5),
                 ["set|pl|bLookBack|" + i32(0x200)])
    return out


def script():
    return (sc_setup() + sc_globals() + sc_world() + sc_nis() +
            sc_traffic() + sc_trackgraph() + sc_race() + sc_player())


# =================================================================== model

# The retail functions each `call` names.
FNS = {
    "rideinfo": 0x00188518, "driverinfo": 0x00188690,
    "raceparams": 0x001ed6f8, "playersettings": 0x001ee030,
    "tshaker": 0x00156220, "nismanager": 0x001b11f8,
    "trafficcar": 0x00167a60, "traffictele": 0x00222780,
    "trackgraph": 0x0024e318, "racingcar": 0x00146c90,
    "race": 0x001477d0, "player": 0x00175db0,
}

# The ones with no object.
GFNS = {"worldtime": 0x001a36c0, "joystick": 0x001544f8,
        "shakers": 0x001564d0}


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        self.vt["TrafficCar"] = TRAFFICCAR_VTABLE
        self.vtname = {v: k for k, v in self.vt.items()}
        self.world = e.alloc(WORLD_SIZE, align=16)
        e.write(self.world, bytes(WORLD_SIZE))
        e.put32(P_CURRENT_WORLD, 0)
        e.put32(P_CURRENT_RACE, 0)
        self.nis_last = 0
        e.stub(S_CHARINFO, self.charinfo)
        e.stub(S_SET_INPUT_MODE, self.setinputmode)
        e.stub(S_NIS_LOAD, self.nisload)
        e.stub(S_NIS_SERVICE, self.nisservice)
        e.stub(S_NIS_STOP, lambda em: self.log1("nisstop"))
        e.stub(S_NIS_START, lambda em: self.log1("nisstart"))

    # ---- the stubs

    def charinfo(self, em):
        n = s32(self.arg(0))
        self.emit("charinfo %d" % n)
        return self.byid["chars"].base + 16 * (n & 0xff)

    def setinputmode(self, em):
        self.emit("setinputmode %s %d" % (self.label(self.arg(0)),
                                          s32(self.arg(1))))
        return 0

    def nisload(self, em):
        m, n = self.arg(0), s32(self.arg(1))
        self.emit("nisload %s %d" % (self.label(m), n))
        self.e.put32(m + 16, n & M32)
        self.nis_last = m
        return 0

    def nisservice(self, em):
        self.emit("nisservice")
        self.e.put32(self.nis_last + 16, M32)
        return 0

    # ---- the script

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "link":
            ob, at = self.ref(a[1])
            f = self.field(ob.cls, a[2])
            assert f.kind == "ptr", a
            if a[3] == "0":
                v = 0
            else:
                ob2, at2 = self.ref(a[3])
                v = at2 if a[4] == "-" else at2 + csc.path_off(ob2.cls, a[4])
            e.put32(at + f.roff, v)
        elif o == "global":
            g = a[1]
            if g == "joy":
                self.register("joy", JOYSTICK_TYPES, None, 1, 2, 2)
            elif g == "env":
                self.register("env", SHAKE_ENVELOPE, None, 1, 4, 4)
            elif g == "shakers":
                n = alloc_size("tShaker")
                self.register("shakers", CAMERA_SHAKERS, "tShaker", 2, n,
                              2 * n)
            elif g == "trp":
                n = alloc_size("RaceParameters")
                self.register("trp", THE_RACE_PARAMETERS, "RaceParameters",
                              1, n, n)
            else:
                raise ValueError(a)
        elif o == "world":
            e.write(self.world, bytes(WORLD_SIZE))
            cars = [] if a[1] == "-" else a[1].split(",")
            e.put32(self.world + 28, len(cars))
            for i, c in enumerate(cars):
                e.put32(self.world + 44 + 4 * i, self.ref(c)[1])
            e.put32(P_CURRENT_WORLD, self.world)
        elif o == "race":
            e.put32(P_CURRENT_RACE, self.ref(a[1])[1])
        elif o == "wtset":
            data = bytes.fromhex(a[1])
            assert len(data) == 28, a
            e.write(WORLD_TIME, data)
        elif o == "wtdump":
            self.emit("wt = " + e.read(WORLD_TIME, 28).hex())
        elif o == "call":
            ob, at = self.ref(a[2])
            self.call(FNS[a[1]], at, S)
        elif o == "gcall":
            self.call(GFNS[a[1]], S)
        elif o == "vcall":
            ob, at = self.ref(a[1])
            f = self.field(ob.cls, a[2])
            assert f.kind == "vptr", a
            vptr = e.u32(at + f.roff)
            slot = int(a[3])
            delta = s32(e.u16(vptr + slot) << 16) >> 16
            self.call(e.u32(vptr + slot + 4), at + delta, S)
        elif o == "dumpp":
            ob, at = self.ref(a[1])
            if a[2] == "-":
                p = at
            else:
                p = at + self.field(ob.cls, a[2]).roff
            self.emit("%s %s -> %s" % (a[1], a[2], self.label(e.u32(p))))
        else:
            csc.Model.op(self, a)


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ============================================================ the harness

def c_fields():
    csc.CLASSES = CLASSES
    return csc.c_fields().replace("tools/carsnap_check.py",
                                  "tools/racesnap_check.py")


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "racesnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="racesnap_test"):
    return hostbuild.build(tmp, sources(tmp), name=name)


run_harness = csc.run_harness
diff = csc.diff
write_script = csc.write_script


# ================================================================ the stubs

class _BuildFailed(Exception):
    pass


def link_errors():
    """Build without the stub files: the symbols the link misses, and any
    error that is not one of those."""
    saved = hostbuild._fail
    box = {}

    def fail(err, what, quiet=False):
        box["err"] = err
        raise _BuildFailed(what)
    hostbuild._fail = fail
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                hostbuild.build(tmp, sources(tmp, stubs=False),
                                name="racesnap_test", quiet=True)
            except _BuildFailed:
                pass
    finally:
        hostbuild._fail = saved
    err = box.get("err", "")
    syms = sorted(set(re.findall(r"undefined reference to `([^']+)'", err)))
    other = [ln for ln in err.splitlines()
             if re.search(r"\berror\b", ln) and "undefined reference" not in ln
             and "ld returned" not in ln]
    return syms, other, err


def find_extern(name):
    """The header and `extern` declaration of a symbol, or None."""
    pat = re.compile(r"^\s*extern\s+([^;()]*?\b%s\b[^;]*);" % re.escape(name),
                     re.M)
    fpat = re.compile(r"^\s*extern\s+([^;]*\(\s*\*\s*%s\s*\)[^;]*);"
                      % re.escape(name), re.M)
    for h in sorted(SRC.glob("*.h")):
        text = h.read_text(encoding="utf-8", errors="replace")
        m = fpat.search(text) or pat.search(text)
        if m:
            return h.name, m.group(1).strip()
    return None


def write_stubs():
    for p in (STUBS, STUBDATA):
        if p.exists():
            p.unlink()
    syms, other, err = link_errors()
    if other:
        sys.stderr.write(err)
        sys.exit("the build fails on more than missing symbols")
    data, funcs, heads = [], [], set()
    for s in syms:
        found = find_extern(s)
        if found:
            heads.add(found[0])
            data.append(found[1] + ";")
        else:
            funcs.append(s)
    hd = ["// Generated by `tools/racesnap_check.py --stubs`. Do not edit.",
          "//"]
    with open(STUBDATA, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The data the linked port files name and nothing linked "
            "defines,", "// zero."] + [""] +
            ['#include "%s"' % h for h in sorted(heads)] + [""] + data) + NL)
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The functions the linked port files call and nothing linked",
            "// defines: each stops the run, which the transcript shows.",
            "", "#include <stdio.h>", "#include <stdlib.h>", "",
            "static void racesnap_unreached(const char *name)", "{",
            '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
            "    exit(3);", "}", ""] +
            ['void %s(void) { racesnap_unreached("%s"); }' % (f, f)
             for f in funcs]) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


MUTATIONS = [
    # -- the race's setup ---------------------------------------------------
    M("ri-type-word", "raceparams.c",
      "    ReplaySnapshot_MoveData(s, &r->Type, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &r->Type, 4, -1, 0);"),
    M("ri-dash-gone", "raceparams.c",
      "    ReplaySnapshot_MoveChar(s, &r->HasDash, 1);\n", ""),
    M("di-rank-gone", "raceparams.c",
      "    ReplaySnapshot_MoveChar(s, &d->EliminatedRank, 1);\n", ""),
    M("di-skill-start-swapped", "raceparams.c",
      "    ReplaySnapshot_MoveChar(s, &d->SkillLevel, 1);\n"
      "    ReplaySnapshot_MoveChar(s, &d->StartingPosition, 1);",
      "    ReplaySnapshot_MoveChar(s, &d->StartingPosition, 1);\n"
      "    ReplaySnapshot_MoveChar(s, &d->SkillLevel, 1);"),
    M("di-ride-gone", "raceparams.c",
      "    ride_info_do_snapshot(&d->CurrentRideInfo, s);\n", ""),
    M("di-char-before-ride", "raceparams.c",
      "    ride_info_do_snapshot(&d->CurrentRideInfo, s);\n"
      "    ReplaySnapshot_MoveChar(s, &d->CharacterNumber, 1);",
      "    ReplaySnapshot_MoveChar(s, &d->CharacterNumber, 1);\n"
      "    ride_info_do_snapshot(&d->CurrentRideInfo, s);"),
    M("di-lookup-always", "raceparams.c",
      "    if (d->CharacterNumber != -1 && s->RestoringSnapshotFlag)",
      "    if (s->RestoringSnapshotFlag)"),
    M("di-lookup-on-take", "raceparams.c",
      "    if (d->CharacterNumber != -1 && s->RestoringSnapshotFlag)",
      "    if (d->CharacterNumber != -1)"),
    M("rp-track-word", "raceparams.c",
      "    ReplaySnapshot_MoveInt(s, &rp->TrackNumber, 1);",
      "    ReplaySnapshot_MoveInt(s, &rp->TrackNumber, 4);"),
    M("rp-density-gone", "raceparams.c",
      "    ReplaySnapshot_MoveFloat(s, &rp->TrafficDensity);\n", ""),
    M("rp-timetrial-gone", "raceparams.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&rp->TimeTrialTime.PackedTime);\n",
      ""),
    M("rp-start1-gone", "raceparams.c",
      "    ReplaySnapshot_MoveChar(s, &rp->PlayerStartPosition[1], 1);\n", ""),
    M("rp-cams-swapped", "raceparams.c",
      "    ReplaySnapshot_MoveChar(s, &rp->GlobalDisplaySettings.JumpCams, 1);\n"
      "    ReplaySnapshot_MoveChar(s, &rp->GlobalDisplaySettings.ZoneCams, 1);",
      "    ReplaySnapshot_MoveChar(s, &rp->GlobalDisplaySettings.ZoneCams, 1);\n"
      "    ReplaySnapshot_MoveChar(s, &rp->GlobalDisplaySettings.JumpCams, 1);"),
    M("rp-oncoming-again-gone", "raceparams.c",
      "    ReplaySnapshot_MoveData(s, &rp->TrafficOncoming, 1, -1, 0);\n", ""),
    M("rp-new624-gone", "raceparams.c",
      "    ReplaySnapshot_MoveInt(s, &rp->New624, 1);\n", ""),
    M("rp-copstrength-word", "raceparams.c",
      "    ReplaySnapshot_MoveData(s, &rp->CopStrength, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &rp->CopStrength, 4, -1, 0);"),
    M("rp-settings-one", "raceparams.c",
      "    player_settings_do_snapshot(&rp->PlayerSettings[1], s);\n", ""),
    M("rp-scale1-gone", "raceparams.c",
      "    ReplaySnapshot_MoveFloat(s, &rp->BoostScale[1]);\n", ""),
    M("rp-drivers-byte", "raceparams.c",
      "    ReplaySnapshot_MoveInt(s, &rp->NumDriverInfo, 4);",
      "    ReplaySnapshot_MoveInt(s, &rp->NumDriverInfo, 1);"),
    M("rp-drivers-one-less", "raceparams.c",
      "    for (i = 0; i < rp->NumDriverInfo; i++)\n"
      "        driver_info_do_snapshot",
      "    for (i = 0; i + 1 < rp->NumDriverInfo; i++)\n"
      "        driver_info_do_snapshot"),
    M("ps-style-gone", "playersettings.c",
      "    ReplaySnapshot_MoveChar(s, &ps->DrivingStyle, 1);\n", ""),
    M("ps-gender-is-pov", "playersettings.c",
      "    ReplaySnapshot_MoveChar(s, &ps->PreferredGender, 1);",
      "    ReplaySnapshot_MoveChar(s, &ps->DriveCameraPOVIndex, 1);"),
    # -- the clock, the joystick, the shakers -------------------------------
    M("wt-timer-gone", "realtime.c",
      "    ReplaySnapshot_MoveData(s, &WorldTimer, 4, -1, 0);\n", ""),
    M("wt-loop-frames-swapped", "realtime.c",
      "    ReplaySnapshot_MoveInt(s, &WorldLoopCounter, 4);\n"
      "    ReplaySnapshot_MoveInt(s, &WorldTimeFrames, 4);",
      "    ReplaySnapshot_MoveInt(s, &WorldTimeFrames, 4);\n"
      "    ReplaySnapshot_MoveInt(s, &WorldLoopCounter, 4);"),
    M("wt-elapsed-moved", "realtime.c",
      "    ReplaySnapshot_VerifyFloat(s, &WorldTimeElapsed);",
      "    ReplaySnapshot_MoveFloat(s, &WorldTimeElapsed);"),
    M("wt-elapsed-frame-gone", "realtime.c",
      "    ReplaySnapshot_MoveFloat(s, &WorldTimeElapsedFrame);\n", ""),
    M("joy-one-byte", "joyevent.c",
      "    ReplaySnapshot_MoveData(s, CurrentJoystickTypes, 2, -1, 0);",
      "    ReplaySnapshot_MoveData(s, CurrentJoystickTypes, 1, -1, 0);"),
    M("sh-envelope-kept", "shake.c",
      "        sh->pAmplitude = shaking != 0 ? &ShakeAmplitudeEnvelope : NULL;",
      "        sh->pAmplitude = shaking != 0 ? sh->pAmplitude : NULL;"),
    M("sh-not-restored", "shake.c",
      "    if (s->RestoringSnapshotFlag)\n        sh->pAmplitude",
      "    if (0)\n        sh->pAmplitude"),
    M("sh-shake-gone", "shake.c",
      "    ReplaySnapshot_MoveVector3(s, &sh->vShake);\n", ""),
    M("sh-time-duration-swapped", "shake.c",
      "    ReplaySnapshot_MoveFloat(s, &sh->fTime);\n"
      "    ReplaySnapshot_MoveFloat(s, &sh->fDuration);",
      "    ReplaySnapshot_MoveFloat(s, &sh->fDuration);\n"
      "    ReplaySnapshot_MoveFloat(s, &sh->fTime);"),
    M("sh-frequency-gone", "shake.c",
      "    ReplaySnapshot_MoveFloat(s, &sh->fFrequency);\n", ""),
    M("shs-one", "shake.c",
      "    for (i = 0; i < 2; i++)\n        tshaker_do_snapshot",
      "    for (i = 0; i < 1; i++)\n        tshaker_do_snapshot"),
    # -- the NIS player -----------------------------------------------------
    M("nis-no-stop", "nismanager.c",
      "    if (s->RestoringSnapshotFlag && gNisStopAnimatingFn != NULL)",
      "    if (0 && gNisStopAnimatingFn != NULL)"),
    M("nis-end-gone", "nismanager.c",
      "    ReplaySnapshot_MoveInt(s, &m->EndTime, 4);\n", ""),
    M("nis-number-byte", "nismanager.c",
      "    ReplaySnapshot_MoveInt(s, &m->NisNumber, 4);",
      "    ReplaySnapshot_MoveInt(s, &m->NisNumber, 1);"),
    M("nis-other-gone", "nismanager.c",
      "    world_do_pointer_snapshot(pCurrentWorld, s, &m->OtherCar);\n", ""),
    M("nis-playing-word", "nismanager.c",
      "    ReplaySnapshot_MoveInt(s, &m->Playing, 1);",
      "    ReplaySnapshot_MoveInt(s, &m->Playing, 4);"),
    M("nis-modes-swapped", "nismanager.c",
      "    ReplaySnapshot_MoveData(s, &m->OtherCarMovementModeBeforeNIS, 1, -1, 0);\n"
      "    ReplaySnapshot_MoveData(s, &m->PlayerCarMovementModeBeforeNIS, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &m->PlayerCarMovementModeBeforeNIS, 1, -1, 0);\n"
      "    ReplaySnapshot_MoveData(s, &m->OtherCarMovementModeBeforeNIS, 1, -1, 0);"),
    M("nis-start-not-playing", "nismanager.c",
      "    if (s->RestoringSnapshotFlag && m->Playing != 0) {",
      "    if (s->RestoringSnapshotFlag) {"),
    M("nis-load-always", "nismanager.c",
      "    if (m->LoadedNisNumber != m->NisNumber) {",
      "    if (1) {"),
    M("nis-no-service", "nismanager.c",
      "            gNisManagerLoadFn(m, m->NisNumber);\n"
      "        nismanager_ensure_nis_is_loaded(m);",
      "            gNisManagerLoadFn(m, m->NisNumber);"),
    # -- the traffic --------------------------------------------------------
    M("tc-position-half", "trafficcar.c",
      "    ReplaySnapshot_MoveData(s, &m->Position, 8, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &m->Position, 4, -1, 0);"),
    M("tc-angle-speed-swapped", "trafficcar.c",
      "    ReplaySnapshot_MoveFloat(s, &m->Angle);\n"
      "    ReplaySnapshot_MoveFloat(s, &m->Speed);",
      "    ReplaySnapshot_MoveFloat(s, &m->Speed);\n"
      "    ReplaySnapshot_MoveFloat(s, &m->Angle);"),
    M("tc-roll-gone", "trafficcar.c",
      "    ReplaySnapshot_MoveFloat(s, &m->Roll);\n", ""),
    M("tt-time-gone", "traffictele.c",
      "    ReplaySnapshot_MoveFloat(s, &t->TimeUntilTeleport);\n", ""),
    M("tt-last-byte", "traffictele.c",
      "    ReplaySnapshot_MoveUInt(s, (uint32_t *)&t->LastCar, 4);",
      "    ReplaySnapshot_MoveUInt(s, (uint32_t *)&t->LastCar, 1);"),
    # -- the track graph ----------------------------------------------------
    M("tg-flag-gone", "trackgraph.c",
      "    ReplaySnapshot_MoveBool(s, &g->bHasCloakedEdge, 1);\n", ""),
    M("tg-every-edge", "trackgraph.c",
      "        if (g->Edge[i].bCloakable != 0)\n", ""),
    M("tg-edges-one-less", "trackgraph.c",
      "    for (i = 0; i < g->nNumEdges; i++)",
      "    for (i = 0; i + 1 < g->nNumEdges; i++)"),
    M("tg-cloakable-byte", "trackgraph.c",
      "        if (g->Edge[i].bCloakable != 0)",
      "        if ((uint8_t)g->Edge[i].bCloakable != 0)"),
    # -- the race -----------------------------------------------------------
    M("rc-region-byte", "racecore.c",
      "    ReplaySnapshot_MoveShort(s, &rc->CurrentBoundaryRegion, 2);",
      "    ReplaySnapshot_MoveShort(s, &rc->CurrentBoundaryRegion, 1);"),
    M("rc-order-gone", "racecore.c",
      "    ReplaySnapshot_MoveChar(s, &rc->FinishingOrder, 1);\n", ""),
    M("rc-newboundary-moved", "racecore.c",
      "    ReplaySnapshot_MoveChar(s, &rc->CompletedNewLap, 1);\n",
      "    ReplaySnapshot_MoveChar(s, &rc->CompletedNewLap, 1);\n"
      "    ReplaySnapshot_MoveChar(s, &rc->CrossedNewBoundary, 1);\n"),
    M("rc-reason-gone", "racecore.c",
      "    ReplaySnapshot_MoveShort(s, &rc->FinishReason, 2);\n", ""),
    M("rc-finished-lap-gone", "racecore.c",
      "    ReplaySnapshot_MoveFloat(s, &rc->FinishedLapNumberExact);\n", ""),
    M("rc-timers-always", "racecore.c",
      "    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL) {",
      "    if (1) {"),
    M("rc-crossing-first", "racecore.c",
      "        ReplaySnapshot_MoveTimer(s, timer_at(rc->BoundaryCrossingTimes,\n"
      "                                    pCurrentRace->FinishLineBoundaryNumber));",
      "        ReplaySnapshot_MoveTimer(s, timer_at(rc->BoundaryCrossingTimes,\n"
      "                                    0));"),
    M("rc-running-start", "racecore.c",
      "        ReplaySnapshot_MoveTimer(s, timer_at(rc->RunningTimes,\n"
      "                                    pCurrentRace->FinishLineBoundaryNumber));",
      "        ReplaySnapshot_MoveTimer(s, timer_at(rc->RunningTimes,\n"
      "                                    pCurrentRace->StartLineBoundaryNumber));"),
    M("race-stage-word", "racecore.c",
      "    ReplaySnapshot_MoveData(s, &r->RaceStage, 1, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &r->RaceStage, 4, -1, 0);"),
    M("race-countdown-gone", "racecore.c",
      "    ReplaySnapshot_MoveInt(s, &r->StartCountdownTimeFrames, 4);\n", ""),
    M("race-racetime-gone", "racecore.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&r->RaceTime.PackedTime);\n",
      ""),
    M("race-count-moved", "racecore.c",
      "    ReplaySnapshot_VerifyInt(s, &r->NumRacingCars, 1);",
      "    ReplaySnapshot_MoveInt(s, &r->NumRacingCars, 1);"),
    M("race-finished-gone", "racecore.c",
      "    ReplaySnapshot_MoveInt(s, &r->NumRacingCarsFinished, 1);\n", ""),
    M("race-one-less", "racecore.c",
      "    for (i = 0; i < r->NumRacingCars; i++) {",
      "    for (i = 0; i + 1 < r->NumRacingCars; i++) {"),
    M("race-index-kept", "racecore.c",
      "        r->pRacingCars[i] = &r->RacingCarTable[index];\n", ""),
    M("race-index-first", "racecore.c",
      "        racing_car_do_snapshot(&r->RacingCarTable[i], s);\n"
      "        // The image",
      "        // The image"),
    M("race-laps-moved", "racecore.c",
      "    ReplaySnapshot_VerifyInt(s, &r->NumLapsInRace, 1);",
      "    ReplaySnapshot_MoveInt(s, &r->NumLapsInRace, 1);"),
    # -- the player ---------------------------------------------------------
    M("pl-finished-byte", "playersnap.c",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->TimeFinishedRacing, 4);",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->TimeFinishedRacing, 1);"),
    M("pl-animlength-word", "playersnap.c",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->FinishAnimationLength, 2);",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->FinishAnimationLength, 4);"),
    M("pl-credits-half", "playersnap.c",
      "    ReplaySnapshot_MoveData(s, p->nZoneCredits, 8, 8, 0);",
      "    ReplaySnapshot_MoveData(s, p->nZoneCredits, 4, 4, 0);"),
    M("pl-zone-timers-half", "playersnap.c",
      "    ReplaySnapshot_MoveData(s, p->tAutoZoneTimers, 32, -1, 0);",
      "    ReplaySnapshot_MoveData(s, p->tAutoZoneTimers, 16, -1, 0);"),
    M("pl-glue-gone", "playersnap.c",
      "    ReplaySnapshot_MoveInt(s, &p->nGlueCount, 1);",
      "    (void)0;"),
    M("pl-average-gone", "playersnap.c",
      "    average_do_snapshot(p->pAverageSpeedRatio, s);",
      "    (void)0;"),
    M("pl-maxratio-gone", "playersnap.c",
      "    ReplaySnapshot_MoveFloat(s, &p->fMaxSpeedRatio);",
      "    (void)0;"),
    M("pl-prompt-twice", "playersnap.c",
      "&p->LastTimeCarInTrouble);   // 172",
      "&p->TimeToDisplayResetPrompt);   // 172"),
    M("pl-troublespeed-gone", "playersnap.c",
      "    ReplaySnapshot_MoveFloat(s, &p->fTroubleSpeed);",
      "    (void)0;"),
    M("pl-controls-byte", "playersnap.c",
      "    ReplaySnapshot_MoveData(s, &p->DrivingControls, 4, -1, 0);",
      "    ReplaySnapshot_MoveData(s, &p->DrivingControls, 1, -1, 0);"),
    M("pl-ticket-gone", "playersnap.c",
      "    ReplaySnapshot_MoveInt(s, &p->TicketNisIndex, 4);",
      "    (void)0;"),
    M("pl-callback-gone", "playersnap.c",
      "    ReplaySnapshot_MoveData(s, (void *)&p->NisFinishedCallback, 4, -1, 0);",
      "    (void)0;"),
    M("pl-param-byte", "playersnap.c",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->NisFinishedCallbackParam, 4);",
      "    ReplaySnapshot_MoveInt(s, (int32_t *)&p->NisFinishedCallbackParam, 1);"),
    M("pl-nis-gone", "playersnap.c",
      "    nismanager_do_snapshot(p->pNisManager, s);",
      "    (void)0;"),
    M("pl-lookback-gone", "playersnap.c",
      "    ReplaySnapshot_MoveBool(s, &p->bLookBack, 1);",
      "    (void)0;"),
    M("pl-muffle-gone", "playersnap.c",
      "    ReplaySnapshot_MoveBool(s, &p->bZoneMuffleSound, 1);",
      "    (void)0;"),
    M("pl-no-input-mode", "playersnap.c",
      "    if (s->RestoringSnapshotFlag)\n        player_set_input_mode(p, 0);",
      "    if (0)\n        player_set_input_mode(p, 0);"),
    M("pl-input-mode-one", "playersnap.c",
      "        player_set_input_mode(p, 0);",
      "        player_set_input_mode(p, 1);"),
    M("pl-freeze-gone", "playersnap.c",
      "    ReplaySnapshot_MoveFloat(s, &p->fFreezeZoneDelayTimer);",
      "    (void)0;"),
]

EQUIVALENT = {}


def mutate_pass(only=None, jobs=None):
    lines = script()
    base = model_cached(lines)
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    with tempfile.TemporaryDirectory() as d:
        sc = write_script(d, lines)
        gen = Path(d) / "gen"
        gen.mkdir()
        srcs = sources(gen)
        with tempfile.TemporaryDirectory() as bt:
            exe = hostbuild.build(bt, srcs, name="racesnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "racesnap_test",
            lambda exe, out: mutpar.run_exe([exe, sc], out, limit),
            base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--dump", metavar="PREFIX")
    ap.add_argument("--fields", metavar="CLASS", nargs="?", const="*")
    ap.add_argument("--stubs", action="store_true")
    args = ap.parse_args()

    if args.stubs:
        write_stubs()
        return 0

    if args.fields:
        for cls in CLASSES:
            if args.fields not in ("*", cls):
                continue
            print("%s (retail %d)" % (cls, alloc_size(cls)))
            for f in flatten(cls):
                print("  %4d %3d %-4s %s" % (f.roff, f.size, f.kind, f.path))
        return 0

    if args.mutate:
        only = set(args.only.split(",")) if args.only else None
        sys.exit(mutate_pass(only, args.jobs))

    lines = script()
    model = model_cached(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        sc = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sc, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(model) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(model, harness)
    print("%d script lines, %d model lines, %d harness lines, %d differ"
          % (len(lines), len(model), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
