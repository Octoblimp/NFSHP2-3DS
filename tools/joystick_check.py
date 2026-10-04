#!/usr/bin/env python3
"""Cross-check the joystick layer against the image itself, run in mipsemu.

    3DS Files/source/joyevent.c    Joystick.obj: the nodes, the queue, the
                                   eleven scanners, the config lookups,
                                   GenerateJoyEvents
    3DS Files/source/joypad.c      JoystickPS2.obj's ring of pad reads
    3DS Files/source/joylog.c      Joylog's two accessors
    3DS Files/source/replay.c      ReplayManager's two, as seams
    3DS Files/source/scannertab.c  the three tables (gen_scanner_tables.py)

**The script.** Every scenario is a list of ops -- register a handler, set
a pad, read it into the ring, run a frame, call one scanner on one buffer,
look a config up -- written once here. The model runs each op on the
image; the harness (tools/src/joystick_test.c) reads the same ops out of a
file and runs them on the port. Both print the same lines, so the scenario
logic exists in one place and the two sides can only disagree about what
the code under test does.

**What is stubbed on the image**, and why each is fair:

  * The platform reads. scePadRead copies the op's 32 bytes;
    ReadRegularController answers the 3DS rule (the mode byte on a good
    read, -1 otherwise), which is the settled answer of the PS2's libpad
    state machine and all joypad.c keeps of it; UpdateLogitechWheels does
    nothing and GetWheelDevice answers NULL, because the 3DS has no wheel;
    PlatformInitJoystick sets the flag and the two port states.
  * The slot pool. bNewSlotPool, bOMalloc, bFree and bDeleteSlotPool log,
    and hand out fresh 0xa5-filled blocks that are never reused, so a field
    AddJoyHandler forgets shows up on both sides alike. The harness defines
    the same four in place of bslotpool.c.
  * ReplayManager::GetData / AddData, which the port has as seams: both
    sides pop the same scripted values and log what they are given.
  * bRepeat::RemoveData / AddData under the real Joylog accessors, over a
    fake bRepeat that never runs out. So the image's own Joylog decides
    when to call them, which is what the port's two functions claim to
    copy.
  * The handlers: eight fake entry points that log their arguments. h6
    removes a handler and h7 adds one, from inside the dispatch -- the
    image calls back into its own RemoveJoyHandler / AddJoyHandler there.

Graph, bStrCmp, TypeChangedHandler and everything in Joystick.obj run as
shipped.

**Scenarios.** Every lookup over every event and a spread of types and
user configurations; the calibration calls; each scanner fed long,
run-length-coded button and stick sequences, from the table's own rows and
from fuzzed ones; and a play session through GenerateJoyEvents: type
detection and flicker, mode changes, the ring filling and overflowing,
handlers added and removed mid-frame, a queue past 256, the replay and the
joylog in each of their states, and the teardown.

    python tools/joystick_check.py
    python tools/joystick_check.py --mutate
    python tools/joystick_check.py --dump out/joystick
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_scanner_tables
import hostbuild
import physicscar_check as pcc
from mipsemu import Emu, M32, s32

ROOT = pcc.ROOT
NL = pcc.NL
HARNESS = "tools/src/joystick_test.c"
JEC = "3DS Files/source/joyevent.c"
JPC = "3DS Files/source/joypad.c"
JLC = "3DS Files/source/joylog.c"
RPC = "3DS Files/source/replay.c"
JC = "3DS Files/source/joystick.c"
SOURCES = [HARNESS, JEC, JPC, JLC, RPC,
           "3DS Files/source/p32.c",
           "3DS Files/source/realtime.c",
           "3DS Files/source/bticker.c",
           "3DS Files/source/timer.c",
           "3DS Files/source/scannertab.c",
           "3DS Files/source/joystick.c",
           "3DS Files/source/graph.c"]

HARNESS_TIMEOUT = 300

# ================================================================ the image

GP = 0x00328bf0
JOYARR = 0x002f1558             # JoystickArray[2], 204 bytes each
JOYSZ = 204
QUEUE = 0x002f16f0              # TheQueuedJoystickEvents
SCANTAB = 0x002dc6c0            # ScannerConfigTable, 32 bytes a row
RING = 0x002de480               # PadRingData[2][32], 84 bytes a read
CURTYPES = 0x00323448           # CurrentJoystickTypes[2]
G_POOL = GP - 22456             # EventNodeSlotPool
G_REPLAY = GP - 23008           # pReplayManager
G_FRAME = GP - 20264            # FrameCounter
G_REAL = GP - 20256             # RealTimer
G_JL_REPLAYING = GP - 21256
G_JL_CAPTURING = GP - 21252
G_JL_REPEAT = GP - 21248
G_TOP = GP - 24328
G_BOT = GP - 24324
G_PREP = GP - 24320
G_INIT = GP - 24316
G_PORTSTATE = GP - 24296
assert G_REPLAY == 0x00323210 and G_REAL == 0x00323cd0

# Joystick, EventNode, QueuedJoystickEvent, ReplayManager: the offsets
# joyevent.h and replay.h name.
J_CAL, CAL_SZ = 8, 44
J_PORT, J_CUR, J_PREV, J_DET, J_USER = 184, 188, 192, 196, 200
N_EVENT, N_CFG, N_HANDLER, N_OBJ, N_PREV, N_FIRST, N_USER = (
    8, 12, 16, 20, 24, 28, 32)
RM_REPLAYING, RM_PAUSED, RM_FANCY, RM_FNUM, RM_NFANCY, RM_TABLE = (
    0, 20, 28, 32, 36, 40)

STATIC_INIT = 0x00152588        # _GLOBAL_$I$EventNodeSlotPool
TYPE_CHANGED_HANDLER = 0x001512f8

SYM = {
    "init": "InitJoystick__Fv",
    "close": "CloseJoystick__Fv",
    "add": "AddJoyHandler__F12JoystickPort8JoyEventPF12JoystickPort8JoyEventUcPv_vPv",
    "remove": "RemoveJoyHandler__F12JoystickPort8JoyEvent",
    "isadded": "IsJoyHandlerAdded__F12JoystickPort8JoyEvent",
    "read": "ReadJoystickData__Fv",
    "frame": "GenerateJoyEvents__Fv",
    "setuser": "SetJoystickUserConfiguration__F12JoystickPorti",
    "calset": "SetJoystickCalibration__F12JoystickPortiUcUc",
    "calget": "GetJoystickCalibration__F12JoystickPortiPUcT2",
    "deadzone": "GetJoystickDeadzone__F12JoystickPorti",
    "choosedz": "ChooseDeadZoneAndHysterysis__FP25AnalogJoystickCalibrationii",
    "find": "FindScannerConfig__F8JoyEventii",
    "findname": "FindScannerConfig__FPcii",
    "avail": "DetermineAvailableJoystickConfigurations__FPiii",
    "choosecfg": "ChooseJoystickConfigurationNumber__Fii",
    "bname": "GetJoystickButtonName__F12JoystickPort8JoyEvent",
    "bchar": "GetJoystickButtonChar__F12JoystickPort8JoyEvent",
    "bevent": "GetJoystickButtonEvent__F12JoystickPortPc",
    "configurable": "IsConfigurableRacingEvent__F8JoyEvent",
    "evname": "GetJoyEventName__F8JoyEvent",
    "makelog": "MakeLoggedJoystickEvent__F8JoyEventUc12JoystickPort",
    "addlog": "AddLoggedJoystickEvent__FUiR20QueuedJoystickEventsi",
    "getlog": "GetLoggedJoystickEvent__FiR20QueuedJoystickEvents",
    "qremove": "RemoveEvent__20QueuedJoystickEventsi8JoyEvent",
    "gettype": "GetJoystickType__F12JoystickPort",
    "wheel": "IsJoystickTypeWheel__F12JoystickPort",
    "stiff": "DoesJoystickHaveStiffThrottle__F12JoystickPort",
    "plugged": "IsJoystickPluggedIn__F12JoystickPort",
    "getuser": "GetJoystickUserConfiguration__F12JoystickPort",
    "destroy": "_$_8Joystick",
}

SCANNERS = ["TypeChanged", "DigitalAnyButton", "DigitalDown",
            "DigitalDownPlus", "DigitalUpOrDown", "DigitalUpOrDownPlus",
            "DigitalDoublePress", "DigitalRepeat", "DigitalSteer",
            "DigitalAnalog", "Analog"]
SCANNER_SUFFIX = gen_scanner_tables.SCANNER_SUFFIX

# Above the image's heap, below the stack: the stand-ins' fixed addresses.
FAKE_FN = 0x01E20000            # handler k at FAKE_FN + 16 k
FAKE_POOL = 0x01E30000
FAKE_REPEAT = 0x01E30100        # the joylog's bRepeat
RM_ADDR = 0x01E30400            # the ReplayManager, 12468 bytes
CFG_ADDR = 0x01E34000           # the scratch ScannerConfig
DATA_ADDR = 0x01E34100
DATA2_ADDR = 0x01E34200
NODE_ADDR = 0x01E34400          # scratch node k at NODE_ADDR + 64 k
NAME_ADDR = 0x01E35000          # NAMES[i] at NAME_ADDR + 64 i
OUT_ADDR = 0x01E36000           # out-parameters
N_HANDLERS = 8
H_TC, H_NULL = 8, 9

# ================================================================== the ops

(OP_TAG, OP_INIT, OP_CLOSE, OP_ADD, OP_REMOVE, OP_ISADDED, OP_PAD, OP_READ,
 OP_CLOCK, OP_FRAME, OP_DUMP, OP_SETUSER, OP_CALSET, OP_CALGET, OP_CHOOSEDZ,
 OP_FIND, OP_FINDNAME, OP_AVAIL, OP_CHOOSECFG, OP_BUTTON, OP_BUTTONEV,
 OP_CONFIGURABLE, OP_EVNAME, OP_MAKELOG, OP_ADDLOG, OP_GETLOG, OP_REPLAY,
 OP_FEED, OP_JOYLOG, OP_NODE, OP_SCAN, OP_SETJOY, OP_QRESET, OP_QREMOVE,
 OP_CURTYPE, OP_TYPEQ, OP_RING, OP_DESTROY) = range(38)

# Fixed argument counts; OP_SCAN is 10 + 8 + 1 (+ 8 when its last flag is 1).
ARGS = {OP_TAG: 1, OP_INIT: 0, OP_CLOSE: 0, OP_ADD: 4, OP_REMOVE: 2,
        OP_ISADDED: 2, OP_PAD: 9, OP_READ: 1, OP_CLOCK: 2, OP_FRAME: 0,
        OP_DUMP: 1, OP_SETUSER: 2, OP_CALSET: 4, OP_CALGET: 2,
        OP_CHOOSEDZ: 4, OP_FIND: 3, OP_FINDNAME: 3, OP_AVAIL: 2,
        OP_CHOOSECFG: 2, OP_BUTTON: 2, OP_BUTTONEV: 2, OP_CONFIGURABLE: 1,
        OP_EVNAME: 1, OP_MAKELOG: 3, OP_ADDLOG: 1, OP_GETLOG: 1,
        OP_REPLAY: 14, OP_FEED: 2, OP_JOYLOG: 3, OP_NODE: 5, OP_SETJOY: 4,
        OP_QRESET: 0, OP_QREMOVE: 2, OP_CURTYPE: 2, OP_TYPEQ: 1, OP_RING: 0,
        OP_DESTROY: 1}


def words(pad):
    """A 256-bit pad as eight little-endian words."""
    return [(pad >> (32 * i)) & M32 for i in range(8)]


def pad_bytes(ws):
    return b"".join(struct.pack("<I", w) for w in ws)


# ================================================================ the tables


def table():
    events, _, rows, valid, _ = gen_scanner_tables.read_all()
    ev = dict(events)
    out = []
    for r in rows:
        out.append(dict(nums=r["nums"], ev=ev[r["ev"]],
                        sc=SCANNERS.index(r["sc"][len("Scanner_"):])
                        if r["sc"] else None,
                        x1=r["x1"], x2=r["x2"], s1=r["s1"], s2=r["s2"],
                        param=r["param"], dev=r["dev"], vdr=r["vdr"],
                        name=r["name"]))
    return ev, out, valid


# ============================================================ the scenarios

# DualShock 2 buttons, bytes 2-3 of the buffer, active low.
BUTTONS = list(range(16, 32))
STICKS = [32, 40, 48, 56]               # bytes 4-7, 128 the centre
PRESSURES = [64 + 8 * i for i in range(12)]   # bytes 8-19
DURS = [1, 1, 1, 2, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 20, 24, 25, 26, 30,
        40, 48, 49, 50, 51, 52, 60, 100]
INTERESTING = [0, 1, 2, 6, 7, 8, 9, 10, 60, 100, 126, 127, 128, 129, 130,
               150, 200, 245, 246, 247, 248, 249, 250, 253, 254, 255]
TYPES = [-1, 0, 7, 21, 22, 35, 65, 83, 115, 121, 255]


def set_bits(pad, pos, width, value):
    mask = ((1 << width) - 1) << pos
    return (pad & ~mask) | ((value << pos) & mask) & ((1 << 256) - 1)


class Field(object):
    """One button or one byte of the pad, held for a random while."""

    def __init__(self, rnd, pos, width, value, pressed_short=False,
                 durs=DURS):
        self.rnd, self.pos, self.width = rnd, pos, width
        self.value = value
        self.durs = durs
        self.left = rnd.choice(durs)
        self.pressed_short = pressed_short

    def step(self):
        self.left -= 1
        if self.left > 0:
            return
        r = self.rnd
        if self.width == 1:
            self.value ^= 1
        elif r.random() < 0.8:
            self.value = r.choice(INTERESTING)
        else:
            self.value = r.randrange(256)
        self.left = r.choice(self.durs)
        # Active-low buttons: presses (0) short, releases longer.
        if self.pressed_short and self.width == 1 and self.value == 1:
            self.left += r.choice([0, 5, 20, 60])


FAST = [1, 1, 1, 2, 2, 3, 4, 6, 9, 30]

# DoublePress's windows: a first press, a gap and a second press each of
# 2..11 frames, and the lengths either side of each edge.
# Weighted towards the windows, with each edge's neighbours either side.
PRESS = [1, 2, 3, 5, 10, 11, 12, 30, 49]
GAP = [1, 2, 3, 6, 10, 11, 12, 48]
PRESS2 = [2, 3, 4, 7, 11, 12, 13, 50]


class Timeline(object):
    """One button driven press, gap, press, rest, over and over."""

    def __init__(self, rnd, pos, pressed):
        self.rnd, self.pos, self.width = rnd, pos, 1
        self.pressed = pressed & 1
        self.seq = []
        self.value = self.pressed ^ 1

    def step(self):
        if not self.seq:
            r = self.rnd
            for n, down in ((r.choice(PRESS), 1), (r.choice(GAP), 0),
                            (r.choice(PRESS2), 1),
                            (r.choice([1, 2, 5, 20]), 0)):
                self.seq.extend([self.pressed if down else self.pressed ^ 1]
                                * n)
        self.value = self.seq.pop(0)


class Group(object):
    """A run of bits, all set, all clear, or anything, for AnyButton."""

    def __init__(self, rnd, pos, width):
        self.rnd, self.pos, self.width = rnd, pos, max(1, min(width, 32))
        self.value = (1 << self.width) - 1
        self.left = 1

    def step(self):
        self.left -= 1
        if self.left > 0:
            return
        r = self.rnd
        self.value = r.choice([(1 << self.width) - 1, 0,
                               r.getrandbits(self.width),
                               ((1 << self.width) - 1)
                               ^ (1 << r.randrange(self.width))])
        self.left = r.choice(DURS)


class Script(object):
    def __init__(self):
        self.ops = []
        self.tags = []
        self.names = []

    def op(self, code, *args):
        self.ops.append((code,) + tuple(int(a) for a in args))

    def tag(self, s):
        self.tags.append(s)
        self.op(OP_TAG, len(self.tags) - 1)

    def name(self, s):
        if s not in self.names:
            self.names.append(s)
        return self.names.index(s)

    def encode(self):
        out = []

        def strs(lst):
            out.append(len(lst))
            for s in lst:
                b = s.encode("latin-1")
                out.append(len(b))
                out.extend(b)

        strs(self.tags)
        strs(self.names)
        flat = []
        for o in self.ops:
            flat.extend(o)
        out.append(len(flat))
        out.extend(flat)
        return struct.pack("<%di" % len(out),
                           *[s32(v & M32) for v in out])


def scenario_tables(sc, ev, rows, valid):
    sc.tag("tables")
    for e in range(-2, 136):
        sc.op(OP_EVNAME, e)
    for e in range(-2, 141):
        sc.op(OP_CONFIGURABLE, e)
    cfgs = {}
    for typ, nums, _ in valid:
        cfgs.setdefault(typ, [n for n in nums if n])
    combos = []
    for typ in TYPES:
        users = [0, -1, 99] + cfgs.get(typ, [])
        for u in users:
            combos.append((typ, u))
    for typ in TYPES:
        for mx in (0, 1, 3, 5, 10):
            sc.op(OP_AVAIL, typ, mx)
    for typ, u in combos:
        sc.op(OP_CHOOSECFG, typ, u)
    for typ, u in combos:
        for e in range(-1, 133):
            sc.op(OP_FIND, e, typ, u)
    names = sorted(set(r["name"] for r in rows if r["name"]))
    names += ["", "NOPE", "START ", "start", "L"]
    for typ in TYPES:
        us = [0, 99] + cfgs.get(typ, [])[:1] + cfgs.get(typ, [])[-1:]
        for u in us:
            for n in names:
                sc.op(OP_FINDNAME, sc.name(n), typ, u)
            sc.op(OP_FINDNAME, -1, typ, u)
    for e, v, p in [(0, 0, 0), (5, 1, 0), (131, 255, 1), (93, 128, 1),
                    (300, 7, 1), (-1, 0, 0), (40, 200, 0)]:
        sc.op(OP_MAKELOG, e, v, p)


def scenario_calibration(sc, rnd):
    sc.tag("calibration")
    for port in (0, 1):
        for dev in range(4):
            sc.op(OP_CALGET, port, dev)
    for typ in TYPES:
        for dev in (-1, 0, 1, 2, 3, 4, 5):
            sc.op(OP_CHOOSEDZ, rnd.randrange(2), rnd.randrange(4), typ, dev)
            sc.op(OP_DUMP, 0)
    for lo, hi in [(0, 255), (10, 245), (200, 50), (128, 128), (255, 0),
                   (1, 254)]:
        port, dev = rnd.randrange(2), rnd.randrange(4)
        sc.op(OP_CALSET, port, dev, lo, hi)
        sc.op(OP_CALGET, port, dev)
    sc.op(OP_DUMP, 0)
    sc.op(OP_DUMP, 1)


def fuzz_cfg(rnd, kind):
    def xr():
        return rnd.choice([0, 1, 1, 1, rnd.randrange(256)])

    if kind in (9, 10):
        s1 = rnd.choice(STICKS + PRESSURES + [rnd.randrange(256)])
    else:
        s1 = rnd.choice(BUTTONS + [0, rnd.randrange(256)])
    s2 = rnd.choice([0, 0] + BUTTONS + [rnd.randrange(256)])
    param = rnd.choice([0, 0, 1, 2, 3, 16, 255, rnd.randrange(256)])
    if kind == 6 and rnd.random() < 0.5:
        s2 = 0
    return dict(x1=xr(), x2=xr(), s1=s1, s2=s2, param=param,
                dev=rnd.randrange(4), ev=rnd.randrange(1, 132))


def scenario_scanners(sc, rnd, rows):
    sc.tag("scanners")
    fc = 1000
    for kind in range(len(SCANNERS)):
        mine = [r for r in rows if r["sc"] == kind]
        combos = [r for r in mine if r["s2"]]
        rest = [r for r in mine if not r["s2"]]
        rnd.shuffle(combos)
        rnd.shuffle(rest)
        picks = combos[:6] + rest[:max(2, 10 - len(combos[:6]))]
        cfgs = [dict(x1=r["x1"], x2=r["x2"], s1=r["s1"], s2=r["s2"],
                     param=r["param"], dev=r["dev"], ev=r["ev"])
                for r in picks]
        cfgs += [fuzz_cfg(rnd, kind) for _ in range(10 if kind == 6 else 6)]
        for ci, c in enumerate(cfgs):
            sc.tag("scan %s %d" % (SCANNERS[kind], ci))
            port = rnd.randrange(2)
            if kind == 10:
                sc.op(OP_CHOOSEDZ, port, c["dev"], rnd.choice(TYPES),
                      c["dev"])
                lo, hi = rnd.choice([(0, 255), (0, 255), (12, 240),
                                     (rnd.randrange(128),
                                      128 + rnd.randrange(128)),
                                     (140, 100)])
                sc.op(OP_CALSET, port, c["dev"], lo, hi)
                sc.op(OP_DUMP, port)
            slot = rnd.randrange(4)
            if rnd.random() < 0.7:
                sc.op(OP_NODE, slot, c["ev"], 0, 1, 0)
            else:
                sc.op(OP_NODE, slot, c["ev"],
                      rnd.choice([0, 1, 2, 128, 255, 0x8000 | 5,
                                  rnd.randrange(1 << 16),
                                  rnd.randrange(1 << 32)]),
                      rnd.choice([0, 0, 1, 7]),
                      rnd.choice([0, 1, 2, 11, 12, 49, 50, 51, 61, 62, 99,
                                  100, 101, 111, 112, 148, 149, 150, 1200,
                                  rnd.randrange(1 << 20)]))
            pad = rnd.getrandbits(256)
            fields = []
            if kind == 1:
                fields.append(Group(rnd, c["s1"], c["param"] & 31))
            elif kind in (9, 10):
                fields.append(Field(rnd, c["s1"], 8, rnd.choice(INTERESTING),
                                    durs=FAST))
                if c["s2"]:
                    fields.append(Field(rnd, c["s2"], 8 if kind == 9 else 1,
                                        rnd.choice(INTERESTING)
                                        if kind == 9 else 1, durs=FAST))
            elif kind == 6:
                # The second button held (so a combo can arm), the first on
                # a timeline through the counter's windows.
                if c["s1"]:
                    fields.append(Timeline(rnd, c["s1"], c["x1"] ^ 1))
                if c["s2"]:
                    fields.append(Field(rnd, c["s2"], 1, (c["x2"] ^ 1) & 1,
                                        durs=[200]))
            else:
                # The second button is a combo's modifier: held for longer.
                if c["s1"]:
                    fields.append(Field(rnd, c["s1"], 1, rnd.randrange(2),
                                        pressed_short=True))
                if c["s2"]:
                    fields.append(Field(rnd, c["s2"], 1, rnd.randrange(2),
                                        durs=[5, 10, 20, 30, 40, 60]))
            prev = None
            for step in range(300 if kind == 6 else 110):
                if kind == 0 and step % 10 == 0:
                    sc.op(OP_SETJOY, port,
                          rnd.choice([-1, 0, 121, 255, 256 + 121, 65, 65]),
                          -1, 0)
                for f in fields:
                    f.step()
                    pad = set_bits(pad, f.pos, f.width, f.value)
                if rnd.random() < 0.05:
                    keep = 0
                    for f in fields:
                        keep |= ((1 << f.width) - 1) << f.pos
                    pad = (pad & keep) | (rnd.getrandbits(256) & ~keep)
                fc += rnd.choice([1] * 8 + [0, 2, 7, 26])
                d = words(pad)
                if prev is None or rnd.random() < 0.2:
                    d2 = words(rnd.getrandbits(256))
                    tail = [1] + d2
                else:
                    tail = [0]
                sc.op(OP_SCAN, kind, slot, c["x1"], c["x2"], c["s1"],
                      c["s2"], c["param"], c["dev"], fc, port, *(d + tail))
                prev = d


def scenario_edges(sc, rnd):
    """Walks over the edges the random runs reach too seldom to pin: every
    pair of stick values either side of DigitalAnalog's 8 and 248, the
    small moves onto and off Analog's 0, 128 and 255, each DoublePress
    window's lengths either side of its ends, and a digital row whose first
    button is shift 0 ("none", read as held)."""
    sc.tag("edges")
    fc = [50000]
    port = 0

    def scan(kind, slot, c, pad, step=1):
        fc[0] += step
        sc.op(OP_SCAN, kind, slot, c["x1"], c["x2"], c["s1"], c["s2"],
              c["param"], c["dev"], fc[0], port, *(words(pad) + [0]))

    # DigitalAnalog: from each `o`, held long enough to have fired and
    # repeated, to each `n`, on either axis, for either end.
    edge = [0, 7, 8, 9, 10, 128, 246, 247, 248, 249, 255]
    for param in (1, 2):
        for axis in (0, 1):
            sc.tag("edges: DigitalAnalog param %d axis %d" % (param, axis))
            c = dict(x1=0, x2=0, s1=48, s2=56, param=param, dev=0, ev=19)
            sc.op(OP_NODE, 0, c["ev"], 0, 1, 0)
            pos = c["s2"] if axis else c["s1"]
            base = set_bits(set_bits(0x7900, 48, 8, 128), 56, 8, 128)
            for o in edge:
                for n in edge:
                    hold = 28 if (o < 8 or o >= 248) else 2
                    for _ in range(hold):
                        scan(9, 0, c, set_bits(base, pos, 8, o))
                    for _ in range(2):
                        scan(9, 0, c, set_bits(base, pos, 8, n))
            # And from centre to each `o` that fires, held through the fire
            # and 25 frames more -- one short of the first repeat -- so the
            # first `n` frame is the one the repeat timer lapses on, and `n`
            # alone decides between a repeat and nothing. The 28-frame hold
            # above has always just repeated by then, which left the
            # repeat's own `n < 8` and `n >= 248` unpinned at 8 and 247.
            for o in edge:
                if not (o < 8 or o >= 248):
                    continue
                for n in edge:
                    scan(9, 0, c, base)
                    for _ in range(26):
                        scan(9, 0, c, set_bits(base, pos, 8, o))
                    for _ in range(2):
                        scan(9, 0, c, set_bits(base, pos, 8, n))

    # Analog: every pair of a small set of raw bytes, for each fold, at
    # the steer's hysteresis (4) and the pedals' (12), straight and with
    # the rows' bit-0 flip.
    small = [0, 1, 2, 4, 5, 11, 12, 13, 107, 108, 127, 128, 129, 148, 149,
             243, 250, 251, 253, 254, 255]
    for dev in (1, 2):
        sc.op(OP_CHOOSEDZ, port, dev, 121, dev)
        sc.op(OP_CALSET, port, dev, 0, 255)
        for param in (0, 1, 2):
            for x1 in (0, 1):
                sc.tag("edges: Analog dev %d param %d xor %d"
                       % (dev, param, x1))
                c = dict(x1=x1, x2=0, s1=112, s2=0, param=param, dev=dev,
                         ev=113)
                sc.op(OP_NODE, 1, c["ev"], 0, 1, 0)
                for o in small:
                    for n in small:
                        scan(10, 1, c, set_bits(0x7900, 112, 8, o))
                        scan(10, 1, c, set_bits(0x7900, 112, 8, n))
    sc.op(OP_DUMP, port)

    # DoublePress: a press of a, a gap of g, a press of b, a rest, with
    # each on and either side of its window's ends. Cross, no combo.
    sc.tag("edges: DoublePress")
    c = dict(x1=1, x2=0, s1=30, s2=0, param=0, dev=0, ev=92)
    sc.op(OP_NODE, 2, c["ev"], 0, 1, 0)
    up = set_bits(0x7900, 16, 16, 0xffff)
    down = set_bits(up, 30, 1, 0)
    for a in (1, 2, 11, 12):
        for g in (2, 3, 12, 13):
            for b in (2, 3, 12, 13, 49, 50, 51):
                for pad, n in ((down, a), (up, g), (down, b), (up, 3)):
                    for _ in range(n):
                        scan(6, 2, c, pad)

    # Shift 0 as the first button: "none", held, whatever byte 0 holds --
    # which here is 0, so reading bit 0 of it would say released.
    for kind in (2, 4, 7):
        sc.tag("edges: %s shift 0" % SCANNERS[kind])
        c = dict(x1=0, x2=0, s1=0, s2=30, param=0, dev=0, ev=9)
        sc.op(OP_NODE, 3, c["ev"], 0, 1, 0)
        for i in range(40):
            scan(kind, 3, c, set_bits(up, 30, 1, (i // 5) & 1))


class Player(object):
    """The pads of a play session: a DualShock 2 per port, every button and
    byte on its own run-length clock."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.mode = [(0, 0x79), (0, 0)]
        self.fields = []
        for port in (0, 1):
            fs = [Field(rnd, b, 1, 1, pressed_short=True) for b in BUTTONS]
            fs += [Field(rnd, s, 8, 128) for s in STICKS]
            fs += [Field(rnd, p, 8, 0) for p in PRESSURES]
            self.fields.append(fs)
        self.frozen = [False, False]

    def pad(self, port):
        b0, b1 = self.mode[port]
        p = b0 | (b1 << 8)
        for f in self.fields[port]:
            p = set_bits(p, f.pos, f.width, f.value)
        return p

    def step(self, port):
        if not self.frozen[port]:
            for f in self.fields[port]:
                f.step()


def scenario_play(sc, rnd, ev, rows):
    sc.tag("play: init")
    # The scanner scenarios left types behind; a boot has none.
    sc.op(OP_SETJOY, 0, -1, -1, 0)
    sc.op(OP_SETJOY, 1, -1, -1, 0)
    sc.op(OP_RING)
    sc.op(OP_TYPEQ, 0)
    # Before the pads are opened a read does nothing.
    sc.op(OP_PAD, 0, *words(0x7901))
    sc.op(OP_READ, 2)
    sc.op(OP_RING)
    sc.op(OP_INIT)
    sc.op(OP_DUMP, 0)
    sc.op(OP_DUMP, 1)
    sc.op(OP_TYPEQ, 0)
    sc.op(OP_TYPEQ, 1)
    sc.op(OP_READ, 1)
    sc.op(OP_RING)
    # One frame drains that read and the next finds the ring empty: the
    # 31 slots never read keep their zeroes, not -1 for a pad unplugged.
    sc.op(OP_FRAME)
    sc.op(OP_FRAME)
    sc.op(OP_RING)

    all_events = sorted(set(r["ev"] for r in rows) - {ev["JOY_EVENT_TYPE_CHANGED"]})
    registered = {0: [], 1: []}

    def add(port, e, hid, obj):
        sc.op(OP_ADD, port, e, hid, obj)
        registered[port].append(e)

    sc.tag("play: register")
    for e in all_events:
        add(0, e, e % 6, e)
    for e in rnd.sample(all_events, 24):
        add(1, e, (e + 3) % 6, 1000 + e)
    start = ev["JOY_EVENT_START"]
    for h in (1, 2, 3):
        add(0, start, h, 500 + h)
    add(0, ev["JOY_EVENT_SELECT"], H_TC, 0)
    add(0, ev["JOY_EVENT_EXIT_DEMO_DISC"], H_NULL, 0)
    # The track marker's double press is a combo, and a combo's first
    # button reads as pressed only on the frame it goes down, so its
    # counter can never hold 102..111 and it never fires. h7 goes on the
    # START + SELECT combo as well, which does.
    add(0, ev["JOY_EVENT_EXIT_DEMO_DISC"], 7,
        (1 << 8) | ev["JOY_EVENT_MENU_SQUARE"])
    # h6 on MENU_L1 takes MENU_SELECT's first handler away mid-frame; h7
    # on the double press adds one for MENU_SQUARE on port 1.
    menu_select = ev["JOY_EVENT_MENU_SELECT"]
    add(0, ev["JOY_EVENT_MENU_L1"], 6, (0 << 8) | menu_select)
    add(0, ev["JOY_EVENT_TOGGLE_TRACK_MARKER"], 7,
        (1 << 8) | ev["JOY_EVENT_MENU_SQUARE"])
    for e in (start, ev["JOY_EVENT_STEER"], 131, 0):
        for p in (0, 1):
            sc.op(OP_ISADDED, p, e)
    sc.op(OP_DUMP, 0)
    sc.op(OP_DUMP, 1)

    pl = Player(rnd)
    frame = [0]
    real = [100000]

    def one_frame(reads=None, dump=False):
        frame[0] += 1
        real[0] += rnd.choice([66, 66, 67, 67, 133, 0, -500])
        sc.op(OP_CLOCK, frame[0], real[0])
        n = reads if reads is not None else rnd.choice([1] * 12 + [0, 2, 2, 3,
                                                                  5])
        for _ in range(n):
            for port in (0, 1):
                pl.step(port)
                sc.op(OP_PAD, port, *words(pl.pad(port)))
            sc.op(OP_READ, 1)
        sc.op(OP_FRAME)
        if dump:
            sc.op(OP_DUMP, 0)
            sc.op(OP_DUMP, 1)

    # Modes for port 0 and port 1, stretch by stretch: (b0, b1, frames).
    segments = [
        ((0, 0x79), (0, 0), 14, "detect"),
        ((0, 0x79), (0, 0), 260, "dualshock"),
        ((0xff, 0x79), (0, 0), 4, "flicker bad read"),
        ((0, 0x79), (0, 0x73), 40, "port 1 plugged"),
        ((0, 0x41), (0, 0x73), 60, "digital"),
        ((0, 0x00), (0, 0x73), 12, "mode 0"),
        ((0, 0x53), (0, 0x73), 40, "mode 0x53"),
        ((0, 0x23), (1, 0x73), 50, "negcon, port 1 unplugged"),
        ((0, 0x73), (0, 0x79), 60, "analog"),
        ((0, 0x79), (0, 0x79), 200, "dualshock again"),
    ]
    remover_armed = False
    for si, (m0, m1, n, name) in enumerate(segments):
        sc.tag("play: " + name)
        pl.mode = [m0, m1]
        if si == 5:
            sc.op(OP_SETUSER, 0, 33)
            sc.op(OP_SETUSER, 1, 22)
        if si == 6:
            sc.op(OP_SETUSER, 0, 99)
        if si == 7:
            # Each valid for the type its port turns to next, so the
            # reconnect reads them.
            sc.op(OP_SETUSER, 0, 22)
            sc.op(OP_SETUSER, 1, 32)
        for i in range(n):
            one_frame(dump=(i == n - 1 or i % 64 == 63))
            if si == 4 and i == 0:
                # 0x41 read 1..8 times, 0x79 still believed: a node added
                # now connects for the believed type, not the one coming.
                one_frame(reads=3)
                add(0, ev["JOY_EVENT_THROTTLE_ANALOG"], 1, 4000)
                sc.op(OP_DUMP, 0)
            k = rnd.random()
            if k < 0.03 and registered[0]:
                e = rnd.choice(registered[0])
                sc.op(OP_REMOVE, 0, e)
                registered[0].remove(e)
                sc.op(OP_ISADDED, 0, e)
            elif k < 0.05:
                e = rnd.choice(all_events)
                add(rnd.randrange(2), e, rnd.randrange(6), 2000 + e)
            elif k < 0.06:
                sc.op(OP_REMOVE, 1, rnd.choice(all_events))
            if not remover_armed and si == 1 and i == 100:
                # h6 on the event it removes, so the rest of that event's
                # queue entries this frame are cleared.
                add(0, menu_select, 6, (0 << 8) | menu_select)
                remover_armed = True
        sc.op(OP_RING)

    sc.tag("play: ring overflow")
    one_frame(reads=35, dump=True)
    sc.op(OP_RING)
    # Reads not yet drained: each one's slot is cleared, type and all.
    for _ in range(5):
        sc.op(OP_PAD, 0, *words(pl.pad(0)))
        sc.op(OP_READ, 1)
    sc.op(OP_RING)
    one_frame(reads=0)
    one_frame(reads=31)
    sc.op(OP_RING)

    sc.tag("play: queue overflow")
    # 25 more nodes for SHIFTUP on port 1, a DualShock 2 in config 30,
    # where it is R2 unless TRIANGLE: toggled every read, 31 reads.
    shiftup = ev["JOY_EVENT_SHIFTUP"]
    for k in range(25):
        add(1, shiftup, k % 6, 3000 + k)
    for i in range(31):
        pl.fields[1][25 - 16].value = i & 1         # R2, bit 25
        pl.fields[1][28 - 16].value = 1             # TRIANGLE released
        pl.frozen[1] = True
        sc.op(OP_PAD, 1, *words(pl.pad(1)))
        sc.op(OP_PAD, 0, *words(pl.pad(0)))
        sc.op(OP_READ, 1)
    frame[0] += 1
    sc.op(OP_CLOCK, frame[0], real[0])
    sc.op(OP_FRAME)
    pl.frozen[1] = False
    sc.op(OP_QREMOVE, 1, shiftup)
    sc.op(OP_GETLOG, 0)
    sc.op(OP_GETLOG, 255)
    sc.op(OP_QRESET)
    for logged in (start, start | (1 << 8), start | (1 << 16),
                   131 | (200 << 8), shiftup | (7 << 8) | (1 << 16),
                   ev["JOY_EVENT_STEER"] | (128 << 8)):
        sc.op(OP_ADDLOG, logged)
    for i in range(4):
        sc.op(OP_GETLOG, i)
    sc.op(OP_QREMOVE, 0, start)
    sc.op(OP_QRESET)

    def feed(which, vals):
        for v in vals:
            sc.op(OP_FEED, which, v)

    def replay(present, replaying=0, paused=0, fancy=0, fnum=0, nfancy=0,
               tab=()):
        t = bytes(tab) + bytes(32 - len(tab))
        sc.op(OP_REPLAY, present, replaying, paused, fancy, fnum, nfancy,
              *struct.unpack("<8I", t))

    steer = ev["JOY_EVENT_STEER"]
    # A node for event 0, which no row scans: only a logged event reaches
    # it, and the fancy table's zeros must not.
    add(0, 0, 5, 4242)
    sc.tag("replay: recording")
    replay(1)
    for _ in range(12):
        one_frame()
    sc.tag("replay: playing back")
    replay(1, replaying=1)
    feed(0, [2, start | (1 << 8), steer | (40 << 8), 0, 1,
             start | (1 << 16), 3, 131, shiftup | (1 << 16),
             ev["JOY_EVENT_SELECT"] | (9 << 8)])
    for _ in range(6):
        one_frame()
    sc.tag("replay: paused this frame")
    replay(1, replaying=1, paused=1)
    for _ in range(3):
        one_frame()
    sc.tag("replay: fancy")
    replay(1, replaying=1, fancy=1, fnum=0, nfancy=5,
           tab=[start, 0, steer, 131, ev["JOY_EVENT_SELECT"], 77])
    feed(0, [1, start, 0, 0, 2, steer, start | (1 << 16), 0])
    for _ in range(8):
        one_frame(dump=False)
    replay(1, replaying=0, fancy=0, fnum=3, nfancy=2)
    for _ in range(2):
        one_frame()
    replay(0)
    one_frame()

    sc.tag("joylog")
    sc.op(OP_JOYLOG, 1, 0, 0)
    for _ in range(3):
        one_frame()
    sc.op(OP_RING)
    sc.op(OP_JOYLOG, 1, 0, 1)
    feed(1, [2, start | (1 << 8), steer | (1 << 16), 0, 1, shiftup])
    for _ in range(4):
        one_frame()
    sc.op(OP_JOYLOG, 0, 1, 1)
    for _ in range(4):
        one_frame()
    sc.op(OP_JOYLOG, 0, 1, 0)
    one_frame()
    sc.op(OP_JOYLOG, 0, 0, 1)
    one_frame()
    sc.op(OP_JOYLOG, 1, 1, 1)
    feed(1, [1, start])
    one_frame()
    replay(1)
    one_frame()
    replay(0)
    sc.op(OP_JOYLOG, 0, 0, 0)
    one_frame(dump=True)

    sc.tag("buttons")
    names = sorted(set(r["name"] for r in rows if r["name"])) + ["", "X"]
    for typ in (121, 115, 65, 35, 21, 255, 7):
        for user in (0, 31, 99):
            sc.op(OP_CURTYPE, 0, typ)
            sc.op(OP_SETUSER, 0, user)
            sc.op(OP_TYPEQ, 0)
            for e in range(-1, 133):
                sc.op(OP_BUTTON, 0, e)
            for n in names:
                sc.op(OP_BUTTONEV, 0, sc.name(n))
            sc.op(OP_BUTTONEV, 0, -1)

    # Every type code through the two type questions RealDriver and
    # PhysicsCar ask.
    sc.tag("type codes")
    for typ in range(256):
        sc.op(OP_CURTYPE, 1, typ)
        sc.op(OP_TYPEQ, 1)

    sc.tag("teardown")
    sc.op(OP_DESTROY, 1)
    sc.op(OP_DUMP, 1)
    sc.op(OP_CLOSE)
    sc.op(OP_DUMP, 0)
    sc.op(OP_TYPEQ, 0)
    sc.op(OP_TYPEQ, 1)
    sc.op(OP_DESTROY, 0)
    sc.op(OP_DUMP, 0)


def script():
    rnd = random.Random(0x10E7)
    ev, rows, valid = table()
    sc = Script()
    sc.tag("static")
    sc.op(OP_DUMP, 0)
    sc.op(OP_DUMP, 1)
    sc.op(OP_RING)
    scenario_tables(sc, ev, rows, valid)
    scenario_calibration(sc, rnd)
    scenario_scanners(sc, rnd, rows)
    scenario_edges(sc, rnd)
    scenario_play(sc, rnd, ev, rows)
    return sc


# ================================================================ the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = Emu(ieee=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.scanner = [e.addr_of("Scanner_" + s + SCANNER_SUFFIX)
                        for s in SCANNERS]
        self.blocks = {}
        self.pads = [bytes(32), bytes(32)]
        self.feeds = [[], []]
        self.data2 = [0] * 8

        emit = self.emit

        def new_pool(em):
            name = self.cstr(em.reg[6] & M32)
            emit("pool new slot %d n %d name %s mp %d"
                 % (s32(em.reg[4]), s32(em.reg[5]), name, s32(em.reg[7])))
            return FAKE_POOL

        def pool_name(p):
            return "ok" if p == FAKE_POOL else ("null" if p == 0 else "?")

        def omalloc(em):
            pool = em.reg[4] & M32
            p = em.alloc(64, 16)
            em.mem[p:p + 64] = b"\xa5" * 64
            self.blocks[p] = len(self.blocks)
            emit("  alloc #%d pool %s" % (self.blocks[p], pool_name(pool)))
            return p

        def ofree(em):
            pool, p = em.reg[4] & M32, em.reg[5] & M32
            emit("  free #%s pool %s" % (self.blocks.get(p, "?"),
                                         pool_name(pool)))
            if p in self.blocks:
                em.mem[p:p + 36] = b"\xdd" * 36

        def del_pool(em):
            emit("pool delete %s" % pool_name(em.reg[4] & M32))

        e.stub("bNewSlotPool__FiiPCci", new_pool)
        e.stub("bOMalloc__FP8SlotPool", omalloc)
        e.stub("bFree__FP8SlotPoolPv", ofree)
        e.stub("bDeleteSlotPool__FP8SlotPool", del_pool)

        def platform_init(em):
            em.put32(G_PORTSTATE, 0)
            em.put32(G_PORTSTATE + 4, 0)
            em.put32(G_INIT, 1)

        e.stub("PlatformInitJoystick__Fv", platform_init)
        e.stub("PlatformCloseJoystick__Fv", lambda em: None)
        e.stub("UpdateLogitechWheels__Fv", lambda em: None)
        e.stub("GetWheelDevice__Fi", lambda em: 0)

        def pad_read(em):
            port, buf = s32(em.reg[4]), em.reg[6] & M32
            em.mem[buf:buf + 32] = self.pads[port]
            return 1

        def read_regular(em):
            d = em.reg[5] & M32
            b0, b1 = em.mem[d], em.mem[d + 1]
            return -1 if (b0 != 0 or b1 == 0) else b1

        e.stub("scePadRead", pad_read)
        e.stub("ReadRegularController__FiP7JoyDataRi", read_regular)

        def pop(which):
            f = self.feeds[which]
            return f.pop(0) if f else 0

        def rm_get(em):
            rm, bits, ch = em.reg[4] & M32, s32(em.reg[5]), s32(em.reg[6])
            v = pop(0)
            emit("  rm get bits %d ch %d%s -> %d"
                 % (bits, ch, "" if rm == RM_ADDR else " rm?", v))
            return v

        def rm_add(em):
            rm = em.reg[4] & M32
            emit("  rm add %d bits %d ch %d%s"
                 % (s32(em.reg[5]), s32(em.reg[6]), s32(em.reg[7]),
                    "" if rm == RM_ADDR else " rm?"))

        e.stub("GetData__13ReplayManagerii", rm_get)
        e.stub("AddData__13ReplayManageriii", rm_add)

        def rep_remove(em):
            v = pop(1)
            emit("  jl get bits %d ch %d%s -> %d"
                 % (s32(em.reg[5]), s32(em.reg[6]),
                    "" if em.reg[4] & M32 == FAKE_REPEAT else " rep?", v))
            return v

        def rep_add(em):
            emit("  jl add %d bits %d ch %d%s"
                 % (s32(em.reg[5]), s32(em.reg[6]), s32(em.reg[7]),
                    "" if em.reg[4] & M32 == FAKE_REPEAT else " rep?"))

        e.stub("RemoveData__7bRepeatii", rep_remove)
        e.stub("AddData__7bRepeatiii", rep_add)
        # The fake bRepeat never runs out: RemoveData's end test wants
        # word 36 below word 32 and word 40 clear, AddData's wants word 8
        # below 8 * word 20 - 68.
        e.put32(FAKE_REPEAT + 32, 1000)
        e.put32(FAKE_REPEAT + 20, 1000)

        for k in range(N_HANDLERS):
            e.stub(FAKE_FN + 16 * k, self.handler(k))

        for i, n in enumerate(sc.names):
            b = n.encode("latin-1") + b"\0"
            e.write(NAME_ADDR + 64 * i, b)

        e.call(STATIC_INIT)

    # ---- helpers ------------------------------------------------------------

    def emit(self, s):
        self.out.append(s)

    def cstr(self, p):
        if p == 0:
            return "(null)"
        end = self.e.mem.index(b"\0", p)
        return self.e.mem[p:end].decode("latin-1")

    def nested(self, fn, *args):
        """Call back into the image from inside a stub, leaving the caller's
        registers as they were."""
        e = self.e
        regs, fpr = list(e.reg), list(e.fpr)
        hilo = (e.hi, e.lo, e.hi1, e.lo1, e.fcc)
        limit, icount = e.limit, e.icount
        e.call(fn, *args)
        e.reg[:] = regs
        e.fpr[:] = fpr
        e.hi, e.lo, e.hi1, e.lo1, e.fcc = hilo
        e.limit, e.icount = limit, icount

    def handler(self, k):
        def h(em):
            port, ev = s32(em.reg[4]), s32(em.reg[5])
            val, obj = em.reg[6] & 0xff, em.reg[7] & M32
            self.emit("  call h%d port %d ev %d val %d obj %d"
                      % (k, port, ev, val, obj))
            if k == 6:
                self.nested(self.fn["remove"], (obj >> 8) & 0xff, obj & 0xff)
            elif k == 7:
                self.nested(self.fn["add"], (obj >> 8) & 0xff, obj & 0xff,
                            FAKE_FN, 0x77)
        return h

    def hname(self, a):
        if a == 0:
            return "null"
        if a == TYPE_CHANGED_HANDLER:
            return "tc"
        if FAKE_FN <= a < FAKE_FN + 16 * N_HANDLERS and not a & 15:
            return "h%d" % ((a - FAKE_FN) // 16)
        return "?"

    def hid_addr(self, hid):
        if hid == H_TC:
            return TYPE_CHANGED_HANDLER
        if hid == H_NULL:
            return 0
        return FAKE_FN + 16 * hid

    def cfg_row(self, p):
        if p == 0:
            return -1
        if SCANTAB <= p < SCANTAB + 32 * 231 and not (p - SCANTAB) % 32:
            return (p - SCANTAB) // 32
        return -2

    def f32bits(self, a):
        return self.e.u32(a)

    # ---- the prints -----------------------------------------------------------

    def dump(self, port):
        e = self.e
        j = JOYARR + JOYSZ * port
        self.emit("joy %d port %d cur %d prev %d det %d user %d"
                  % (port, s32(e.u32(j + J_PORT)), s32(e.u32(j + J_CUR)),
                     s32(e.u32(j + J_PREV)), s32(e.u32(j + J_DET)),
                     s32(e.u32(j + J_USER))))
        for i in range(4):
            c = j + J_CAL + CAL_SZ * i
            knees = " ".join("%08x" % e.u32(c + 4 * k) for k in range(8))
            self.emit("  cal %d hyst %d n %d %s %s"
                      % (i, e.u8(c + 40), s32(e.u32(c + 36)),
                         "self" if e.u32(c + 32) == c else "other", knees))
        l = e.u32(j)
        n = 0
        while l != j and n < 400:
            self.emit("  node ev %d cfg %d pv %d ft %d up %d h %s obj %d"
                      % (s32(e.u32(l + N_EVENT)), self.cfg_row(e.u32(l + N_CFG)),
                         e.u32(l + N_PREV), s32(e.u32(l + N_FIRST)),
                         s32(e.u32(l + N_USER)),
                         self.hname(e.u32(l + N_HANDLER)), e.u32(l + N_OBJ)))
            l = e.u32(l)
            n += 1
        # The back links, as a count: a Prev that is wrong shows here.
        l = e.u32(j + 4)
        m = 0
        while l != j and m < 400:
            l = e.u32(l + 4)
            m += 1
        self.emit("  nodes %d back %d" % (n, m))

    def queue(self):
        e = self.e
        n = s32(e.u32(QUEUE))
        self.emit("queue %d" % n)
        for i in range(min(n, 256)):
            q = QUEUE + 4 + 12 * i
            self.emit("  q port %d ev %d data %04x h %s obj %d"
                      % (e.u8(q + 2), e.u8(q + 3), e.u16(q),
                         self.hname(e.u32(q + 4)), e.u32(q + 8)))

    def ring(self):
        e = self.e
        self.emit("ring top %d bot %d prep %d init %d"
                  % (s32(e.u32(G_TOP)), s32(e.u32(G_BOT)), s32(e.u32(G_PREP)),
                     s32(e.u32(G_INIT))))
        for port in (0, 1):
            ts = []
            for i in range(32):
                d = RING + 2688 * port + 84 * i
                ts.append("%d/%d" % (s32(e.u32(d + 36)), s32(e.u32(d + 40))))
            self.emit("  types %d %s" % (port, " ".join(ts)))

    def after_frame(self):
        e = self.e
        self.queue()
        self.emit("ring top %d bot %d prep %d"
                  % (s32(e.u32(G_TOP)), s32(e.u32(G_BOT)), s32(e.u32(G_PREP))))
        # Retail also stamps TheDemoDiscManager.LastActivityTime here, which
        # only the demo disc reads; the port has no demo disc.
        self.emit("types %d %d jl %d %d"
                  % (e.u8(CURTYPES), e.u8(CURTYPES + 1),
                     s32(e.u32(G_JL_REPLAYING)), s32(e.u32(G_JL_CAPTURING))))
        if e.u32(G_REPLAY):
            self.emit("rm fnum %d" % s32(e.u32(RM_ADDR + RM_FNUM)))

    # ---- the interpreter ------------------------------------------------------

    def run(self):
        e, fn, emit = self.e, self.fn, self.emit
        for o in self.sc.ops:
            code, a = o[0], o[1:]
            if code == OP_TAG:
                emit("[%s]" % self.sc.tags[a[0]])
            elif code == OP_INIT:
                emit("init")
                e.call(fn["init"])
            elif code == OP_CLOSE:
                emit("close")
                e.call(fn["close"])
            elif code == OP_ADD:
                emit("add port %d ev %d h%d obj %d" % a)
                e.call(fn["add"], a[0], a[1], self.hid_addr(a[2]), a[3])
            elif code == OP_REMOVE:
                emit("remove port %d ev %d" % a)
                e.call(fn["remove"], a[0], a[1])
            elif code == OP_ISADDED:
                emit("added port %d ev %d -> %d"
                     % (a[0], a[1], e.call(fn["isadded"], a[0], a[1])))
            elif code == OP_PAD:
                self.pads[a[0]] = pad_bytes([w & M32 for w in a[1:]])
            elif code == OP_READ:
                for _ in range(a[0]):
                    e.call(fn["read"])
            elif code == OP_CLOCK:
                e.put32(G_FRAME, a[0])
                e.put32(G_REAL, a[1])
            elif code == OP_FRAME:
                emit("frame %d" % s32(e.u32(G_FRAME)))
                e.call(fn["frame"])
                self.after_frame()
            elif code == OP_DUMP:
                self.dump(a[0])
            elif code == OP_SETUSER:
                e.call(fn["setuser"], a[0], a[1])
                emit("user %d -> %d" % (a[0], e.call(fn["getuser"], a[0])))
            elif code == OP_CALSET:
                e.call(fn["calset"], *a)
            elif code == OP_CALGET:
                e.call(fn["calget"], a[0], a[1], OUT_ADDR, OUT_ADDR + 1)
                dz = e.call(fn["deadzone"], a[0], a[1])
                emit("cal get %d %d lo %d hi %d dz %d"
                     % (a[0], a[1], e.u8(OUT_ADDR), e.u8(OUT_ADDR + 1),
                        dz & 0xff))
            elif code == OP_CHOOSEDZ:
                port, cal, typ, dev = a
                c = JOYARR + JOYSZ * port + J_CAL + CAL_SZ * cal
                e.call(fn["choosedz"], c, typ, dev)
                emit("dz %d %d type %d dev %d hyst %d k1 %08x k2 %08x"
                     % (port, cal, typ, dev, e.u8(c + 40), e.u32(c + 8),
                        e.u32(c + 16)))
            elif code == OP_FIND:
                p = e.call(fn["find"], *a) & M32
                emit("find %d %d %d -> %d" % (a + (self.cfg_row(p),)))
            elif code == OP_FINDNAME:
                ptr = 0 if a[0] < 0 else NAME_ADDR + 64 * a[0]
                p = e.call(fn["findname"], ptr, a[1], a[2]) & M32
                emit("findname %d %d %d -> %d" % (a + (self.cfg_row(p),)))
            elif code == OP_AVAIL:
                e.mem[OUT_ADDR:OUT_ADDR + 64] = b"\xee" * 64
                n = e.call(fn["avail"], OUT_ADDR, a[1], a[0])
                vals = [s32(e.u32(OUT_ADDR + 4 * i)) for i in range(12)]
                emit("avail %d %d -> %d %s"
                     % (a[0], a[1], n, " ".join("%d" % v for v in vals)))
            elif code == OP_CHOOSECFG:
                emit("choose %d %d -> %d" % (a + (e.call(fn["choosecfg"], *a),)))
            elif code == OP_BUTTON:
                p = e.call(fn["bname"], *a) & M32
                c = e.call(fn["bchar"], *a)
                emit("button %d %d -> \"%s\" %d" % (a + (self.cstr(p), c)))
            elif code == OP_BUTTONEV:
                ptr = 0 if a[1] < 0 else NAME_ADDR + 64 * a[1]
                emit("bevent %d %d -> %d"
                     % (a + (e.call(fn["bevent"], a[0], ptr),)))
            elif code == OP_CONFIGURABLE:
                emit("configurable %d -> %d"
                     % (a[0], e.call(fn["configurable"], a[0])))
            elif code == OP_EVNAME:
                p = e.call(fn["evname"], a[0]) & M32
                emit("evname %d -> %s" % (a[0], self.cstr(p)))
            elif code == OP_MAKELOG:
                emit("makelog %d %d %d -> %08x"
                     % (a + (e.call(fn["makelog"], *a) & M32,)))
            elif code == OP_ADDLOG:
                e.call(fn["addlog"], a[0], QUEUE, 1)
                emit("addlog %08x -> %d" % (a[0] & M32, s32(e.u32(QUEUE))))
            elif code == OP_GETLOG:
                emit("getlog %d -> %08x"
                     % (a[0], e.call(fn["getlog"], a[0], QUEUE) & M32))
            elif code == OP_REPLAY:
                present, rep, paused, fancy, fnum, nfancy = a[:6]
                e.put32(G_REPLAY, RM_ADDR if present else 0)
                e.put32(RM_ADDR + RM_REPLAYING, rep)
                e.put32(RM_ADDR + RM_PAUSED, paused)
                e.put32(RM_ADDR + RM_FANCY, fancy)
                e.put32(RM_ADDR + RM_FNUM, fnum)
                e.put32(RM_ADDR + RM_NFANCY, nfancy)
                e.write(RM_ADDR + RM_TABLE,
                        pad_bytes([w & M32 for w in a[6:14]]))
            elif code == OP_FEED:
                self.feeds[a[0]].append(a[1])
            elif code == OP_JOYLOG:
                e.put32(G_JL_REPLAYING, a[0])
                e.put32(G_JL_CAPTURING, a[1])
                e.put32(G_JL_REPEAT, FAKE_REPEAT if a[2] else 0)
            elif code == OP_NODE:
                slot, ev, prev, first, user = a
                n = NODE_ADDR + 64 * slot
                e.mem[n:n + 64] = bytes(64)
                e.put32(n + N_EVENT, ev)
                e.put32(n + N_CFG, CFG_ADDR)
                e.put32(n + N_PREV, prev)
                e.put32(n + N_FIRST, first)
                e.put32(n + N_USER, user)
            elif code == OP_SCAN:
                kind, slot, x1, x2, s1, s2, param, dev, fc, port = a[:10]
                data = [w & M32 for w in a[10:18]]
                if a[18]:
                    self.data2 = [w & M32 for w in a[19:27]]
                n = NODE_ADDR + 64 * slot
                c = CFG_ADDR
                e.mem[c:c + 32] = bytes(32)
                e.put32(c + 8, e.u32(n + N_EVENT))
                e.put32(c + 12, self.scanner[kind])
                e.mem[c + 16:c + 23] = bytes([x1, x2, s1, s2, param, dev, 0])
                e.put32(G_FRAME, fc)
                e.write(DATA_ADDR, pad_bytes(data))
                e.write(DATA2_ADDR, pad_bytes(self.data2))
                r = e.call(self.scanner[kind], n, DATA_ADDR, DATA2_ADDR, c,
                           JOYARR + JOYSZ * port) & 0xffff
                emit("scan %d -> %04x pv %d ft %d up %d"
                     % (fc, r, e.u32(n + N_PREV), s32(e.u32(n + N_FIRST)),
                        s32(e.u32(n + N_USER))))
                self.data2 = data
            elif code == OP_SETJOY:
                j = JOYARR + JOYSZ * a[0]
                e.put32(j + J_CUR, a[1])
                e.put32(j + J_PREV, a[2])
                e.put32(j + J_DET, a[3])
            elif code == OP_QRESET:
                e.put32(QUEUE, 0)
            elif code == OP_QREMOVE:
                e.call(fn["qremove"], QUEUE, a[0], a[1])
                emit("qremove %d %d" % a)
                self.queue()
            elif code == OP_CURTYPE:
                e.mem[CURTYPES + a[0]] = a[1] & 0xff
            elif code == OP_TYPEQ:
                emit("typeq %d type %d plugged %d user %d wheel %d stiff %d"
                     % (a[0], e.call(fn["gettype"], a[0]),
                        e.call(fn["plugged"], a[0]),
                        e.call(fn["getuser"], a[0]),
                        e.call(fn["wheel"], a[0]),
                        e.call(fn["stiff"], a[0])))
            elif code == OP_RING:
                self.ring()
            elif code == OP_DESTROY:
                emit("destroy %d" % a[0])
                e.call(fn["destroy"], JOYARR + JOYSZ * a[0], 2)
            else:
                raise SystemExit("unknown op %d" % code)
        return self.out


def model(sc=None):
    return Model(sc or script()).run()


# ================================================================ the build


def build_harness(tmp, name="joystick_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, ops_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(ops_path)], stdout=fh,
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


def harness_lines(exe, sc, tmp, name="harness"):
    ops = Path(tmp) / "ops.bin"
    if not ops.exists():
        ops.write_bytes(sc.encode())
    out = Path(tmp) / (name + ".txt")
    rc = run_harness(exe, ops, out)
    return rc, out.read_text().splitlines()


diff = pcc.diff

# ============================================================ the mutations

STC = "3DS Files/source/scannertab.c"
MUTATIONS = [
    # -- the queue --------------------------------------------------------------
    ("addevent-cap", JEC, "if (q->NumEvents >= JOY_MAX_QUEUED_EVENTS)",
     "if (q->NumEvents >= JOY_MAX_QUEUED_EVENTS - 1)"),
    ("addevent-port", JEC, "e->Port = (uint8_t)port;", "e->Port = 0;"),
    ("addevent-event", JEC, "e->Event = (uint8_t)node->Event;", "e->Event = 0;"),
    ("addevent-obj", JEC, "e->HandlerObject = node->HandlerObject;",
     "e->HandlerObject = NULL;"),
    ("removeevent-port", JEC,
     "if ((int32_t)e->Port == port && e->Event == (uint8_t)ev)",
     "if (e->Event == (uint8_t)ev)"),
    ("removeevent-or", JEC,
     "if ((int32_t)e->Port == port && e->Event == (uint8_t)ev)",
     "if ((int32_t)e->Port == port || e->Event == (uint8_t)ev)"),

    # -- type detection and the scan --------------------------------------------
    ("gen-prevtype", JEC, "if (type != joy->PreviousType) {", "if (0) {"),
    ("gen-det-10", JEC, "if (++joy->NumValidTypeDetections < 10)",
     "if (++joy->NumValidTypeDetections < 9)"),
    ("gen-det-reset", JEC, "            joy->PreviousType = type;" + NL
     + "            joy->NumValidTypeDetections = 0;",
     "            joy->PreviousType = type;"),
    ("gen-believe", JEC, "        joy->CurrentType = type;" + NL, ""),
    ("gen-choose-dz", JEC, "for (i = 0; i < JOY_CALIBRATIONS; i++)" + NL
     + "            ChooseDeadZoneAndHysterysis(",
     "for (i = 1; i < JOY_CALIBRATIONS; i++)" + NL
     + "            ChooseDeadZoneAndHysterysis("),
    ("gen-choose-dz-dev", JEC,
     "&joy->AnalogJoystickCalibrationTable[i], type, i);",
     "&joy->AnalogJoystickCalibrationTable[i], type, 1);"),
    ("gen-reconnect", JEC,
     "            Joystick_ConnectEventNodeConfig(joy, (EventNode *)l);",
     "            (void)l;"),
    ("gen-scan-null", JEC, "if (cfg == NULL || cfg->Scanner == NULL)",
     "if (cfg == NULL)"),
    ("gen-replay-skip", JEC, "if (replaying && !cfg->ValidDuringReplay)",
     "if (0)"),
    ("gen-replay-flag", JEC, "pReplayManager->ReplayingFlag != 0;",
     "pReplayManager->CapturingFlag != 0;"),
    ("gen-count", JEC, "            count++;" + NL, ""),
    ("gen-add-port", JEC,
     "QueuedJoystickEvents_AddEvent(q, joy->PortNumber, v, node);",
     "QueuedJoystickEvents_AddEvent(q, 0, v, node);"),

    # -- nodes ------------------------------------------------------------------
    ("connect-first", JEC, "    node->FirstTime = 1;", "    node->FirstTime = 0;"),
    ("connect-prev", JEC, "    node->FirstTime = 1;" + NL
     + "    node->PreviousValue = 0;",
     "    node->FirstTime = 1;" + NL + "    node->PreviousValue = 1;"),
    ("connect-user", JEC, "joy->UserConfigurationNumber);", "0);"),
    ("connect-type", JEC,
     "node->Config = FindScannerConfig(node->Event, joy->CurrentType,",
     "node->Config = FindScannerConfig(node->Event, joy->PreviousType,"),
    ("destroy-nofree", JEC, "        EventNode_Destroy((EventNode *)l, 3);",
     "        EventNode_Destroy((EventNode *)l, 2);"),
    ("nodedestroy-flag", JEC, "    if (flags & 1)" + NL
     + "        bSlotFree(EventNodeSlotPool, node);",
     "    if (flags & 4)" + NL + "        bSlotFree(EventNodeSlotPool, node);"),

    # -- the static initialiser and the calibration ------------------------------
    ("static-knee1", JEC, "cal->vData[1].x = 128.0f;", "cal->vData[1].x = 127.0f;"),
    ("static-knee3y", JEC, "cal->vData[3].y = 255.0f;", "cal->vData[3].y = 254.0f;"),
    ("static-graph-n", JEC, "graph_init(&cal->gCalibration, cal->vData, 4);",
     "graph_init(&cal->gCalibration, cal->vData, 3);"),
    ("static-hyst", JEC, "            cal->HysterysisAmount = 0;",
     "            cal->HysterysisAmount = 1;"),
    ("static-type", JEC, "        joy->CurrentType = -1;",
     "        joy->CurrentType = 0;"),
    ("static-prevtype", JEC, "        joy->PreviousType = -1;",
     "        joy->PreviousType = 0;"),
    ("calset-swap", JEC, "    cal->vData[3].x = (float)hi;" + NL
     + "    cal->vData[0].x = (float)lo;",
     "    cal->vData[3].x = (float)lo;" + NL + "    cal->vData[0].x = (float)hi;"),
    ("calget-lo", JEC, "*lo = (uint8_t)(int32_t)cal->vData[0].x;",
     "*lo = (uint8_t)(int32_t)cal->vData[1].x;"),
    ("calget-hi", JEC, "*hi = (uint8_t)(int32_t)cal->vData[3].x;",
     "*hi = (uint8_t)(int32_t)cal->vData[2].x;"),
    ("deadzone-128", JEC, "vData[2].x - 128.0f)", "vData[2].x - 127.0f)"),
    ("choosedz-hyst", JEC, "uint32_t hyst = 12;", "uint32_t hyst = 11;"),
    ("choosedz-dz", JEC, "uint32_t dz = 20;", "uint32_t dz = 21;"),
    ("choosedz-type", JEC, "        if (v->JoystickType != type)" + NL
     + "            continue;" + NL + "        if (dev == 1) {",
     "        if (v->JoystickType == type)" + NL + "            continue;" + NL
     + "        if (dev == 1) {"),
    ("choosedz-break", JEC, "            hyst = v->SteerHysterysis;" + NL
     + "        }" + NL + "    }",
     "            hyst = v->SteerHysterysis;" + NL + "        }" + NL
     + "        break;" + NL + "    }"),
    ("choosedz-steer-dz", JEC, "dz = v->SteerDeadZoneSize;",
     "dz = v->ThrottleDeadZoneSize;"),
    ("choosedz-steer-hyst", JEC, "            hyst = v->SteerHysterysis;" + NL
     + "        } else if (dev == 2) {",
     "            hyst = v->ThrottleHysterysis;" + NL
     + "        } else if (dev == 2) {"),
    ("choosedz-dev2", JEC, "        } else if (dev == 2) {",
     "        } else if (dev == 3) {"),
    ("choosedz-throttle", JEC, "dz = v->ThrottleDeadZoneSize;" + NL
     + "            hyst = v->ThrottleHysterysis;",
     "dz = v->ThrottleDeadZoneSize;" + NL + "            hyst = v->SteerHysterysis;"),
    ("choosedz-brake-dz", JEC, "dz = v->BrakeDeadZoneSize;",
     "dz = v->SteerDeadZoneSize;"),
    ("choosedz-else", JEC, "        } else {" + NL
     + "            hyst = v->SteerHysterysis;",
     "        } else {" + NL + "            hyst = v->ThrottleHysterysis;"),
    ("choosedz-else-dz", JEC, "        } else {" + NL
     + "            hyst = v->SteerHysterysis;",
     "        } else {" + NL + "            dz = v->SteerDeadZoneSize;" + NL
     + "            hyst = v->SteerHysterysis;"),
    ("choosedz-knee2", JEC, "(float)(int32_t)dz + 128.0f",
     "(float)(int32_t)dz + 127.0f"),
    ("choosedz-knee1", JEC, "128.0f - (float)(int32_t)dz;",
     "127.0f - (float)(int32_t)dz;"),

    # -- logged events --------------------------------------------------------
    ("makelog-port", JEC, "((uint32_t)port << 16)", "((uint32_t)port << 15)"),
    ("makelog-value", JEC, "((uint32_t)value << 8)", "((uint32_t)value << 9)"),
    ("addlog-port", JEC, "(int32_t)(logged >> 16)", "(int32_t)(logged >> 17)"),
    ("addlog-mask", JEC, "(JoyEvent)(logged & 0xff)", "(JoyEvent)(logged & 0x7f)"),
    ("addlog-value", JEC,
     "QueuedJoystickEvents_AddEvent(q, port, (uint16_t)logged, node);",
     "QueuedJoystickEvents_AddEvent(q, port, (uint16_t)(logged & 0xff), node);"),
    ("getlog-port", JEC, "((uint32_t)e->Port << 16) | e->EventData",
     "(uint32_t)e->EventData"),

    # -- GenerateJoyEvents ------------------------------------------------------
    ("gen-queue-reset", JEC, "    q->NumEvents = 0;" + NL
     + "    if (Joylog_ReplayingFlag) {", "    if (Joylog_ReplayingFlag) {"),
    ("gen-count-bits", JEC, "#define LOG_COUNT_BITS 8", "#define LOG_COUNT_BITS 9"),
    ("gen-event-bits", JEC, "#define LOG_EVENT_BITS 19", "#define LOG_EVENT_BITS 18"),
    ("gen-joylog-branch", JEC, "    if (Joylog_ReplayingFlag) {", "    if (0) {"),
    ("gen-joylog-channel", JEC, "n = Joylog_GetData(LOG_COUNT_BITS, 1);",
     "n = Joylog_GetData(LOG_COUNT_BITS, 0);"),
    ("gen-joylog-ev-channel", JEC,
     "(uint32_t)Joylog_GetData(LOG_EVENT_BITS, 1), q, 1);",
     "(uint32_t)Joylog_GetData(LOG_EVENT_BITS, 0), q, 1);"),
    ("gen-joylog-add-count", JEC, "Joylog_AddData(n, LOG_COUNT_BITS, 1);",
     "Joylog_AddData(n + 1, LOG_COUNT_BITS, 1);"),
    ("gen-joylog-add-channel", JEC, "                           LOG_EVENT_BITS, 1);",
     "                           LOG_EVENT_BITS, 0);"),
    ("gen-fancy-skip", JEC, "|| !pReplayManager->FancyReplayInProgress)", "|| 1)"),
    ("gen-fancy-never", JEC, "|| !pReplayManager->FancyReplayInProgress)", "|| 0)"),
    ("gen-ports", JEC, "            for (port = 0; port < JOYSTICK_PORTS; port++) {",
     "            for (port = 0; port < 1; port++) {"),
    ("gen-fancy-inc", JEC, "rm->FancyJoyEventTable[rm->FancyJoyEventNumber++]",
     "rm->FancyJoyEventTable[rm->FancyJoyEventNumber]"),
    ("gen-fancy-cmp", JEC, "if (rm->FancyJoyEventNumber < rm->NumFancyJoyEvents)",
     "if (rm->FancyJoyEventNumber <= rm->NumFancyJoyEvents)"),
    ("gen-fancy-zero", JEC, "            if (ev != 0)" + NL, "            if (1)" + NL),
    ("gen-fancy-value", JEC, "MakeLoggedJoystickEvent(ev, 1, 0)",
     "MakeLoggedJoystickEvent(ev, 0, 0)"),
    ("gen-fancy-port", JEC, "MakeLoggedJoystickEvent(ev, 1, 0)",
     "MakeLoggedJoystickEvent(ev, 1, 1)"),
    ("gen-rm-paused", JEC, "if (!rm->ReplayingFlag || rm->ReplayPausedThisFrame)",
     "if (!rm->ReplayingFlag)"),
    ("gen-rm-replaying", JEC,
     "if (!rm->ReplayingFlag || rm->ReplayPausedThisFrame)",
     "if (rm->ReplayingFlag || rm->ReplayPausedThisFrame)"),
    ("gen-rm-channel", JEC,
     "ReplayManager_AddData(pReplayManager, n, LOG_COUNT_BITS, 0);",
     "ReplayManager_AddData(pReplayManager, n, LOG_COUNT_BITS, 1);"),
    ("gen-rm-ev-bits", JEC, "                                      LOG_EVENT_BITS, 0);",
     "                                      LOG_COUNT_BITS, 0);"),
    ("gen-rm-get-bits", JEC, "n = ReplayManager_GetData(rm, LOG_COUNT_BITS, 0);",
     "n = ReplayManager_GetData(rm, LOG_EVENT_BITS, 0);"),
    ("gen-dispatch-null", JEC, "        if (e->Handler != NULL)" + NL,
     "        if (1)" + NL),
    ("gen-dispatch-value", JEC, "(uint8_t)(e->EventData >> 8), e->HandlerObject);",
     "(uint8_t)(e->EventData >> 7), e->HandlerObject);"),
    ("gen-dispatch-port", JEC, "e->Handler(e->Port, e->EventData & 0xff,",
     "e->Handler(0, e->EventData & 0xff,"),

    # -- registration and type monitoring -----------------------------------------
    ("add-fn", JEC, "    node->Handler = fn;", "    node->Handler = NULL;"),
    ("add-obj", JEC, "    node->HandlerObject = obj;",
     "    node->HandlerObject = NULL;"),
    ("add-backlink", JEC, "    node->Link.Prev = tail;",
     "    node->Link.Prev = &joy->EventNodeList;"),
    ("add-headprev", JEC, "    joy->EventNodeList.Prev = &node->Link;" + NL, ""),
    ("add-user", JEC, "    node->UserParam = 0;" + NL
     + "    Joystick_ConnectEventNodeConfig(joy, node);",
     "    Joystick_ConnectEventNodeConfig(joy, node);"),
    ("add-connect", JEC, "    node->UserParam = 0;" + NL
     + "    Joystick_ConnectEventNodeConfig(joy, node);",
     "    node->UserParam = 0;"),
    ("remove-queue", JEC,
     "    QueuedJoystickEvents_RemoveEvent(&TheQueuedJoystickEvents, port, ev);"
     + NL, ""),
    ("remove-nofree", JEC, "    EventNode_Destroy(node, 3);",
     "    EventNode_Destroy(node, 2);"),
    ("remove-fwd", JEC, "    node->Link.Prev->Next = node->Link.Next;" + NL, ""),
    ("remove-backlink", JEC, "    node->Link.Next->Prev = node->Link.Prev;" + NL,
     ""),
    ("typechanged-handler", JEC, "CurrentJoystickTypes[port] = value;",
     "CurrentJoystickTypes[port] = (uint8_t)(value + 1);"),
    ("plugged", JEC, "return CurrentJoystickTypes[port] != 0xff;",
     "return CurrentJoystickTypes[port] != 0;"),
    ("monitor-reset", JEC, "        CurrentJoystickTypes[p] = 0xff;" + NL
     + "        AddJoyHandler", "        CurrentJoystickTypes[p] = 0;" + NL
     + "        AddJoyHandler"),
    ("monitor-handler", JEC,
     "AddJoyHandler(p, JOY_EVENT_TYPE_CHANGED, TypeChangedHandler, NULL);",
     "AddJoyHandler(p, JOY_EVENT_TYPE_CHANGED, TestJoyHandler, NULL);"),
    ("monitor-close-reset", JEC, "        CurrentJoystickTypes[p] = 0xff;" + NL
     + "        RemoveJoyHandler", "        RemoveJoyHandler"),
    ("monitor-close-remove", JEC,
     "        RemoveJoyHandler(p, JOY_EVENT_TYPE_CHANGED);" + NL, ""),
    ("init-portnumber", JEC, "JoystickArray[p].PortNumber = p;",
     "JoystickArray[p].PortNumber = 0;"),
    ("init-pool-n", JEC, "bNewSlotPool(sizeof(EventNode), 96,",
     "bNewSlotPool(sizeof(EventNode), 95,"),
    ("init-pool-mp", JEC, "\"EventNodeSlotPool\", 16);", "\"EventNodeSlotPool\", 15);"),
    ("init-platform", JEC, "    PlatformInitJoystick();" + NL, ""),
    ("init-monitor", JEC, "    InitJoystickTypeMonitoring();" + NL, ""),
    ("close-delete", JEC, "    bDeleteSlotPool(EventNodeSlotPool);" + NL, ""),
    ("close-null", JEC, "    EventNodeSlotPool = NULL;" + NL, ""),
    ("close-monitor", JEC, "    CloseJoystickTypeMonitoring();" + NL
     + "    PlatformCloseJoystick();", "    PlatformCloseJoystick();"),
    ("evname-bound", JEC, "for (i = 0; i < JOY_EVENT_NAMES; i++)",
     "for (i = 0; i < JOY_EVENT_NAMES - 1; i++)"),
    ("evname-missing", JEC, "\"JOY_EVENT_MISSING_NAME!\"",
     "\"JOY_EVENT_MISSING_NAME\""),

    # -- the scanners ---------------------------------------------------------
    ("tc-uint8", JEC, "uint32_t t = (uint8_t)joy->CurrentType;",
     "uint32_t t = (uint32_t)joy->CurrentType;"),
    ("tc-first", JEC, [("if (t != node->PreviousValue || node->FirstTime) {",
                        "if (t != node->PreviousValue) {", 1)]),
    ("tc-value", JEC, [("return (uint16_t)(node->Event + (t << 8));",
                        "return (uint16_t)(node->Event + (t << 7));", 1)]),
    ("anybutton-mask", JEC, "(1u << (cfg->Param & 31)) - 1",
     "(1u << (cfg->Param & 15)) - 1"),
    ("anybutton-flip", JEC, "cfg->Xor1 ? 0xffffffffu : 0", "(uint32_t)cfg->Xor1"),
    ("anybutton-first", JEC, [("    if (node->FirstTime) {" + NL
                               + "        node->FirstTime = 0;" + NL
                               + "        node->PreviousValue = v;" + NL
                               + "    }" + NL,
                               "    if (node->FirstTime) {" + NL
                               + "        node->FirstTime = 0;" + NL
                               + "    }" + NL, 1)]),
    ("anybutton-release", JEC, [("    if (v == 0)" + NL + "        return 0;" + NL,
                                 "", 1)]),
    ("pressed-shift1", JEC, "    if (cfg->Shift1)" + NL + "        b1 =",
     "    if (1)" + NL + "        b1 ="),
    ("pressed-shift2", JEC, "    if (cfg->Shift2) {" + NL + "        b2 =",
     "    if (1) {" + NL + "        b2 ="),
    ("pressed-xor1", JEC,
     "        b1 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 1;",
     "        b1 = pad_word(data, cfg->Shift1) & 1;"),
    ("pressed-xor2", JEC,
     "        b2 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;",
     "        b2 = pad_word(data, cfg->Shift2) & 1;"),
    ("pressed-combo", JEC, "        if (cfg->Xor2) {", "        if (0) {"),
    ("pressed-combo-b2", JEC, "            if (b2 ^ p2)" + NL
     + "                b2 = 0;" + NL, ""),
    ("pressed-combo-b1", JEC, "b1 = b1 & (b1 ^ p1);", "b1 = b1 | (b1 ^ p1);"),
    ("pressed-combo-p1", JEC,
     "uint32_t p1 = (pad_word(data2, cfg->Shift1) ^ cfg->Xor1) & 1;",
     "uint32_t p1 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 1;"),
    ("pressed-combo-p2", JEC,
     "uint32_t p2 = (pad_word(data2, cfg->Shift2) ^ cfg->Xor2) & 1;",
     "uint32_t p2 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;"),
    ("value-param", JEC, "return cfg->Param ? cfg->Param : 1;", "return 1;"),
    ("value-param0", JEC, "return cfg->Param ? cfg->Param : 1;",
     "return cfg->Param ? cfg->Param : 2;"),
    ("down-first", JEC, "digital_value(data, data2, cfg);" + NL + NL
     + "    (void)joy;" + NL + "    if (node->FirstTime) {",
     "digital_value(data, data2, cfg);" + NL + NL
     + "    (void)joy;" + NL + "    if (0) {"),
    ("down-release", JEC, "    if (v == 0)" + NL + "        return 0;" + NL
     + "    return (uint16_t)(node->Event + (v << 8));" + NL + "}" + NL + NL
     + "uint16_t Scanner_DigitalDownPlus",
     "    return (uint16_t)(node->Event + (v << 8));" + NL + "}" + NL + NL
     + "uint16_t Scanner_DigitalDownPlus"),
    ("downplus", JEC, "    return Scanner_DigitalDown(node, data, data2, cfg, joy);",
     "    return Scanner_DigitalUpOrDown(node, data, data2, cfg, joy);"),
    ("upordown-first", JEC, "if (v != node->PreviousValue || node->FirstTime) {",
     "if (v != node->PreviousValue) {"),
    ("upordownplus", JEC,
     "    return Scanner_DigitalUpOrDown(node, data, data2, cfg, joy);",
     "    return Scanner_DigitalDown(node, data, data2, cfg, joy);"),
    ("dp-p1", JEC, "        if (!p)" + NL + "            c = ((uint32_t)(c - 2)",
     "        if (p)" + NL + "            c = ((uint32_t)(c - 2)"),
    ("dp-window1", JEC, "((uint32_t)(c - 2) < 10) ? 50 : 0",
     "((uint32_t)(c - 2) < 11) ? 50 : 0"),
    ("dp-window1-lo", JEC, "((uint32_t)(c - 2) < 10) ? 50 : 0",
     "((uint32_t)(c - 1) < 10) ? 50 : 0"),
    ("dp-limit1", JEC, "        limit = 48;", "        limit = 49;"),
    ("dp-window2", JEC, "((uint32_t)(c - 52) < 10) ? 100 : 0",
     "((uint32_t)(c - 51) < 10) ? 100 : 0"),
    ("dp-window2-width", JEC, "((uint32_t)(c - 52) < 10) ? 100 : 0",
     "((uint32_t)(c - 52) < 11) ? 100 : 0"),
    ("dp-99", JEC, "        else if (c == 99)" + NL + "            c = 0;",
     "        else if (c == 99)" + NL + "            c = 1;"),
    ("dp-99-lt", JEC, "        if (c < 99)" + NL + "            c++;",
     "        if (c <= 99)" + NL + "            c++;"),
    ("dp-window3", JEC, "(uint32_t)(c - 102) < 10", "(uint32_t)(c - 102) < 9"),
    ("dp-window3-lo", JEC, "(uint32_t)(c - 102) < 10", "(uint32_t)(c - 101) < 10"),
    ("dp-release3", JEC, "            c = 0;" + NL + "        }" + NL
     + "        limit = 148;", "        }" + NL + "        limit = 148;"),
    ("dp-limit3", JEC, "        limit = 148;", "        limit = 147;"),
    ("dp-150", JEC, "    }" + NL + "    node->UserParam = c;",
     "    } else" + NL + "        c = 0;" + NL + "    node->UserParam = c;"),
    ("dp-fire-value", JEC, "return fire ? (uint16_t)node->Event : 0;",
     "return fire ? (uint16_t)(node->Event + 256) : 0;"),
    ("repeat-first", JEC, "        node->FirstTime = 0;" + NL
     + "        node->PreviousValue = 0;" + NL + "    }" + NL + "    if (!p) {",
     "        node->FirstTime = 0;" + NL + "        node->PreviousValue = 1;" + NL
     + "    }" + NL + "    if (!p) {"),
    ("repeat-release", JEC, "        node->PreviousValue = 0;" + NL
     + "        return (uint16_t)node->Event;",
     "        return (uint16_t)node->Event;"),
    ("repeat-held", JEC, "if (node->PreviousValue - 1 < 2) {",
     "if (node->PreviousValue - 1 < 1) {"),
    ("repeat-cmp", JEC, "        if (node->UserParam < FrameCounter) {",
     "        if (node->UserParam <= FrameCounter) {"),
    ("repeat-6", JEC, "            node->UserParam = FrameCounter + 6;",
     "            node->UserParam = FrameCounter + 5;"),
    ("repeat-512", JEC, "(uint16_t)(node->Event + 512)",
     "(uint16_t)(node->Event + 768)"),
    ("repeat-25", JEC, "    node->PreviousValue = 1;" + NL
     + "    node->UserParam = FrameCounter + 25;",
     "    node->PreviousValue = 1;" + NL + "    node->UserParam = FrameCounter + 24;"),
    ("steer-both", JEC, "t = b2 ? 128 : 0;", "t = b2 ? 255 : 0;"),
    ("steer-first-only", JEC, "t = b2 ? 128 : 0;", "t = b2 ? 128 : 1;"),
    ("steer-none", JEC, "t = b2 ? 255 : 128;", "t = b2 ? 255 : 127;"),
    ("steer-first", JEC, "t = b2 ? 255 : 128;" + NL
     + "    if (t != node->PreviousValue || node->FirstTime) {",
     "t = b2 ? 255 : 128;" + NL + "    if (t != node->PreviousValue) {"),
    ("steer-xor2", JEC,
     "uint32_t b2 = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;",
     "uint32_t b2 = pad_word(data, cfg->Shift2) & 1;"),
    ("da-first-return", JEC, "        node->PreviousValue = (t4 << 8) | t2;" + NL
     + "        return 0;" + NL, "        node->PreviousValue = (t4 << 8) | t2;" + NL),
    ("da-t4", JEC, "uint32_t t4 = 128;", "uint32_t t4 = 127;"),
    ("da-shift2", JEC, "    if (cfg->Shift2)" + NL + "        t4 =",
     "    if (0)" + NL + "        t4 ="),
    ("da-t2-mask", JEC,
     "uint32_t t2 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 0xff;",
     "uint32_t t2 = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 0x7f;"),
    ("da-p1-9", JEC, "            if (o >= 9) {", "            if (o >= 8) {"),
    ("da-p1-fire", JEC, "                if (n < 8)" + NL + "                    goto fire;",
     "                if (n < 9)" + NL + "                    goto fire;"),
    ("da-p1-else", JEC, "            } else if (o < 8) {",
     "            } else if (o <= 8) {"),
    ("da-p1-release", JEC, "                if (n >= 9)" + NL,
     "                if (n >= 10)" + NL),
    ("da-p1-repeat", JEC, "if (n < 8 && node->UserParam < FrameCounter)",
     "if (n < 8 && node->UserParam <= FrameCounter)"),
    ("da-p1-repeat-n", JEC, "if (n < 8 && node->UserParam < FrameCounter)",
     "if (n < 9 && node->UserParam < FrameCounter)"),
    ("da-param2", JEC, "        } else if (cfg->Param == 2) {" + NL
     + "            if (o < 247) {",
     "        } else if (cfg->Param == 3) {" + NL + "            if (o < 247) {"),
    ("da-p2-247", JEC, "            if (o < 247) {", "            if (o <= 247) {"),
    ("da-p2-fire", JEC, "                if (n >= 248)" + NL
     + "                    goto fire;",
     "                if (n >= 247)" + NL + "                    goto fire;"),
    ("da-p2-else", JEC, "            } else if (o >= 248) {",
     "            } else if (o >= 247) {"),
    ("da-p2-release", JEC, "                if (n < 247)" + NL,
     "                if (n < 246)" + NL),
    ("da-p2-repeat", JEC, "if (n >= 248 && node->UserParam < FrameCounter)",
     "if (n >= 249 && node->UserParam < FrameCounter)"),
    ("da-fire-25", JEC, "    node->UserParam = FrameCounter + 25;" + NL
     + "    return (uint16_t)(node->Event + 256);" + NL + "repeat:",
     "    node->UserParam = FrameCounter + 26;" + NL
     + "    return (uint16_t)(node->Event + 256);" + NL + "repeat:"),
    ("da-repeat-6", JEC, "    node->UserParam = FrameCounter + 6;" + NL
     + "    return (uint16_t)(node->Event + 256);" + NL + "}",
     "    node->UserParam = FrameCounter + 7;" + NL
     + "    return (uint16_t)(node->Event + 256);" + NL + "}"),
    ("da-repeat-value", JEC, "    node->UserParam = FrameCounter + 6;" + NL
     + "    return (uint16_t)(node->Event + 256);" + NL + "}",
     "    node->UserParam = FrameCounter + 6;" + NL
     + "    return (uint16_t)(node->Event + 512);" + NL + "}"),
    ("da-axis-order", JEC, "(int32_t)(i ? (old >> 8) & 0xff : old & 0xff);",
     "(int32_t)(i ? old & 0xff : (old >> 8) & 0xff);"),
    ("da-one-axis", JEC, "    for (i = 0; i < 2; i++) {" + NL
     + "        int32_t o =", "    for (i = 0; i < 1; i++) {" + NL
     + "        int32_t o ="),
    ("analog-xor1", JEC,
     "uint32_t raw = (pad_word(data, cfg->Shift1) ^ cfg->Xor1) & 0xff;",
     "uint32_t raw = pad_word(data, cfg->Shift1) & 0xff;"),
    ("analog-dev", JEC,
     "&joy->AnalogJoystickCalibrationTable[cfg->AnalogDeviceNumber];",
     "&joy->AnalogJoystickCalibrationTable[0];"),
    ("analog-trunc", JEC,
     "v = (uint8_t)(int32_t)graph_get_value(&cal->gCalibration, (float)raw);",
     "v = (uint8_t)(int32_t)(graph_get_value(&cal->gCalibration, (float)raw)"
     " + 0.5f);"),
    ("analog-p1", JEC, "v = (v < 127 ? 127 - v : 0) << 1;",
     "v = (v < 128 ? 128 - v : 0) << 1;"),
    ("analog-p1-255", JEC, [("        if (v == 254)" + NL + "            v = 255;" + NL,
                             "", 1)]),
    ("analog-param2", JEC, "    } else if (cfg->Param == 2) {" + NL
     + "        v = (v > 128", "    } else if (cfg->Param == 3) {" + NL
     + "        v = (v > 128"),
    ("analog-p2", JEC, "v = (v > 128 ? v - 128 : 0) << 1;",
     "v = (v > 127 ? v - 127 : 0) << 1;"),
    ("analog-p2-255", JEC, "v = (v > 128 ? v - 128 : 0) << 1;" + NL
     + "        if (v == 254)" + NL + "            v = 255;",
     "v = (v > 128 ? v - 128 : 0) << 1;"),
    ("analog-first", JEC, "        node->PreviousValue = v;" + NL
     + "        return (uint16_t)(node->Event + (v << 8));" + NL + "    }" + NL
     + "    if (cfg->Shift2)",
     "        node->PreviousValue = v;" + NL + "        return 0;" + NL + "    }"
     + NL + "    if (cfg->Shift2)"),
    ("analog-enable", JEC, "    if (!enable)" + NL + "        return 0;" + NL, ""),
    ("analog-enable-xor", JEC,
     "enable = (pad_word(data, cfg->Shift2) ^ cfg->Xor2) & 1;",
     "enable = pad_word(data, cfg->Shift2) & 1;"),
    ("analog-h0", JEC, "if (v == 0 || v == 128 || v == 255)",
     "if (v == 0 || v == 255)"),
    ("analog-h0-0", JEC, "if (v == 0 || v == 128 || v == 255)",
     "if (v == 128 || v == 255)"),
    ("analog-h0-255", JEC, "if (v == 0 || v == 128 || v == 255)",
     "if (v == 0 || v == 128)"),
    ("analog-hyst-lo", JEC, "if (v + h < node->PreviousValue ||",
     "if (v + h <= node->PreviousValue ||"),
    ("analog-hyst-hi", JEC, "|| node->PreviousValue + h < v) {",
     "|| node->PreviousValue + h <= v) {"),

    # -- configurations ---------------------------------------------------------
    ("setuser", JEC, "JoystickArray[port].UserConfigurationNumber = n;",
     "JoystickArray[port].UserConfigurationNumber = n + 1;"),
    ("avail-type", JEC, "        if (v->JoystickType != type)" + NL
     + "            continue;" + NL + "        for (j = 0; j < 10; j++) {",
     "        if (v->JoystickType == type)" + NL + "            continue;" + NL
     + "        for (j = 0; j < 10; j++) {"),
    ("avail-max", JEC, "if (c != 0 && n < max)", "if (c != 0)"),
    ("avail-zero", JEC, "if (c != 0 && n < max)", "if (n < max)"),
    ("avail-none", JEC, "        return n;" + NL + "    }" + NL + "    return 0;",
     "        return n;" + NL + "    }" + NL + "    return -1;"),
    ("choosecfg-zero", JEC, "    if (n == 0)" + NL + "        return 0;" + NL
     + "    for (i = 0; i < n; i++)",
     "    if (n == 0)" + NL + "        return user;" + NL + "    for (i = 0; i < n; i++)"),
    ("choosecfg-match", JEC, "        if (buf[i] == user)" + NL
     + "            return user;", "        if (buf[i] == user)" + NL
     + "            return buf[0];"),
    ("choosecfg-first", JEC, "    return buf[0];" + NL + "}",
     "    return buf[n - 1];" + NL + "}"),
    ("find-event", JEC, "        if (s->Event != ev)", "        if (s->Event == ev)"),
    ("find-cfg0", JEC, "                if (ev == JOY_EVENT_TYPE_CHANGED)" + NL,
     "                if (1)" + NL),
    ("find-cfg0-continue", JEC, "                    return s;" + NL
     + "                continue;" + NL, "                    return s;" + NL),
    ("find-zero", JEC, "            c = s->ConfigurationNumbers[j];" + NL
     + "            if (c == 0)" + NL + "                continue;" + NL,
     "            c = s->ConfigurationNumbers[j];" + NL),
    ("find-all", JEC, [("            if (c == -1 || c == cfg)" + NL,
                        "            if (c == cfg)" + NL, 1)]),
    ("find-j8", JEC, [("for (j = 0; j < 8; j++) {", "for (j = 0; j < 7; j++) {", 1)]),
    ("findname-zero", JEC, "            int32_t c = s->ConfigurationNumbers[j];" + NL
     + NL + "            if (c == 0)" + NL + "                continue;" + NL,
     "            int32_t c = s->ConfigurationNumbers[j];" + NL + NL),
    ("findname-null", JEC, "        if (s->ButtonName == NULL || name == NULL" + NL,
     "        if (s->ButtonName == NULL" + NL),
    ("findname-rowname", JEC, "        if (s->ButtonName == NULL || name == NULL" + NL,
     "        if (name == NULL" + NL),
    ("findname-all", JEC, "            if (c == -1 || c == cfg)" + NL
     + "                return s;" + NL + "        }" + NL + "    }" + NL
     + "    return NULL;" + NL + "}" + NL + NL + "const char *GetJoystickButtonName",
     "            if (c == cfg)" + NL + "                return s;" + NL + "        }"
     + NL + "    }" + NL + "    return NULL;" + NL + "}" + NL + NL
     + "const char *GetJoystickButtonName"),
    ("button-empty", JEC, "        return \"\";", "        return \"-\";"),
    ("button-rowname", JEC, "    if (s == NULL || s->ButtonName == NULL)" + NL
     + "        return \"\";", "    if (s == NULL)" + NL + "        return \"\";"),
    ("button-user", JEC, [("GetJoystickType(port), GetJoystickUserConfiguration(port));",
                           "GetJoystickType(port), 0);", 1)]),
    ("button-char", JEC, "return s ? s->ButtonChar : 0;",
     "return s ? s->ButtonChar : -1;"),
    ("bchar-user", JEC, "int32_t GetJoystickButtonChar(JoystickPort port, JoyEvent ev)"
     + NL + "{" + NL + "    const ScannerConfig *s = FindScannerConfig(" + NL
     + "        ev, GetJoystickType(port), GetJoystickUserConfiguration(port));",
     "int32_t GetJoystickButtonChar(JoystickPort port, JoyEvent ev)"
     + NL + "{" + NL + "    const ScannerConfig *s = FindScannerConfig(" + NL
     + "        ev, GetJoystickType(port), 0);"),
    ("bevent-configurable", JEC, "        || !IsConfigurableRacingEvent(s->Event))",
     "        )"),
    ("bevent-user", JEC,
     "name, GetJoystickType(port), GetJoystickUserConfiguration(port));",
     "name, GetJoystickType(port), 0);"),
    ("configurable-horn", JEC, "    case JOY_EVENT_HONK_HORN:" + NL, ""),
    ("configurable-hud", JEC, "    case JOY_EVENT_CYCLE_HUD:" + NL, ""),
    ("configurable-steer", JEC, "    case JOY_EVENT_STEER:" + NL, ""),
    ("configurable-default", JEC, "    default:" + NL + "        return 0;",
     "    default:" + NL + "        return 1;"),

    # -- the ring ---------------------------------------------------------------
    ("read-uninit", JPC, "    if (!JoypadInitialised)" + NL + "        return;" + NL,
     ""),
    ("read-full", JPC, "    if (next == JoystickRingBufferBottom)" + NL
     + "        return;" + NL, ""),
    ("read-slot", JPC, "JoyData *d = &PadRingData[port][JoystickRingBufferTop];",
     "JoyData *d = &PadRingData[port][next];"),
    ("read-advance", JPC, "    JoystickRingBufferTop = next;" + NL, ""),
    ("advance-mask", JPC, "(JoystickRingBufferBottom + 1)" + NL
     + "                               & (JOYPAD_RING - 1);",
     "(JoystickRingBufferBottom + 1)" + NL + "                               & 15;"),
    ("prepare-top", JPC,
     "    JoystickRingBufferPreparedTop = JoystickRingBufferTop;" + NL, ""),
    ("prepare-empty", JPC, "    if (i == JoystickRingBufferPreparedTop)" + NL
     + "        return;" + NL, ""),
    ("prepare-type", JPC, "ReadRegularController(port, d, &JoypadPortState[port]);",
     "121;"),
    ("prepare-wheel", JPC, "d->LogitechDeviceID = -1;", "d->LogitechDeviceID = 0;"),
    ("prepare-one", JPC, "    } while (i != JoystickRingBufferPreparedTop);",
     "    } while (0);"),
    ("typeanddata-cur", JPC, "JoyData *cur = &PadRingData[port][b];",
     "JoyData *cur = &PadRingData[port][(b + 1) & (JOYPAD_RING - 1)];"),
    ("typeanddata-data2", JPC,
     "PadRingData[port][(b - 1) & (JOYPAD_RING - 1)].ThePadData",
     "PadRingData[port][b].ThePadData"),
    ("rrc-b0", JPC, "if (b[0] != 0 || b[1] == 0)", "if (b[1] == 0)"),
    ("rrc-b1", JPC, "if (b[0] != 0 || b[1] == 0)", "if (b[0] != 0)"),
    ("rrc-value", JPC, "    return b[1];", "    return b[2];"),
    ("platforminit-flag", JPC, "JoypadInitialised = 1;", "JoypadInitialised = 0;"),
    ("platforminit-state", JPC, "        JoypadPortState[port] = 0;",
     "        JoypadPortState[port] = 1;"),

    # -- the joylog -------------------------------------------------------------
    ("jl-get-null", JLC, "    if (Joylog_pRepeat == NULL)" + NL
     + "        return 0;" + NL, ""),
    ("jl-add-capturing", JLC,
     "if (Joylog_pRepeat == NULL || !Joylog_CapturingFlag)",
     "if (Joylog_pRepeat == NULL)"),
    ("jl-add-repeat", JLC, "if (Joylog_pRepeat == NULL || !Joylog_CapturingFlag)",
     "if (!Joylog_CapturingFlag)"),

    # -- the generated tables ---------------------------------------------------
    ("tab-repeat-shift", STC, [("Scanner_DigitalRepeat, 1, 0, 20, 0, 0, 0, 1,",
                                "Scanner_DigitalRepeat, 1, 0, 21, 0, 0, 0, 1,", 1)]),
    ("tab-valid-dz", STC, "{ 121, { 30, 31, 32, 33, 34, 0, 0, 0, 0, 0 }, 4, 20,",
     "{ 121, { 30, 31, 32, 33, 34, 0, 0, 0, 0, 0 }, 4, 19,"),
    ("tab-valid-cfg", STC, "{ 115, { 20, 21, 22, 23, 24,",
     "{ 115, { 21, 20, 22, 23, 24,"),

    # -- the type questions -----------------------------------------------------
    ("stiff-83", JC, "    case 83:" + NL, ""),
    ("stiff-115", JC, "    case 115:" + NL, ""),
    ("stiff-121", JC, "    case 121:" + NL, ""),
    ("stiff-extra", JC, "    case 121:" + NL, "    case 121:" + NL + "    case 65:" + NL),
    ("stiff-true", JC, [("    case 121:" + NL + "        return 1;" + NL
                         + "    default:" + NL + "        return 0;",
                         "    case 121:" + NL + "        return 1;" + NL
                         + "    default:" + NL + "        return 1;", 1)]),
    ("wheel-21", JC, "    case 21:" + NL, ""),
    ("wheel-22", JC, "    case 22:" + NL, ""),
    ("wheel-35", JC, "    case 35:" + NL, ""),
    ("tab-name", STC, "{ JOY_EVENT_START, \"JOY_EVENT_START\" },",
     "{ JOY_EVENT_START, \"JOY_EVENT_STAR\" },"),
]

# Mutants no transcript can tell from the original, each for a reason that
# is a fact about the tables or the callers rather than about the scenarios.
EQUIVALENT = {
    # ValidJoystickConfigurationTable lists each type once, so the last
    # matching row is also the first.
    "choosedz-break": "each type has one row",
    # FindScannerConfig tests cfg == 0 before it reads a row's numbers, so
    # c == 0 never equals cfg and the skip only saves the compare.
    "find-zero": "cfg is nonzero by then",
    # The image's ReadRegularController is a stand-in, and the port's never
    # reads the state: scePad's per-port state machine is not ported.
    "platforminit-state": "nothing reads the port state",
    # Retail's one reader of GenerateEventsFromScanners' count is the demo
    # disc's activity stamp in GenerateJoyEvents, which the port leaves out.
    "gen-count": "no caller reads the count",
}


def mutate_pass(only=None):
    sc = script()
    base = model(sc)
    caught = 0
    survived = []
    missing = []
    equivalent = []
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    opsdir = tempfile.TemporaryDirectory()
    ops = Path(opsdir.name) / "ops.bin"
    ops.write_bytes(sc.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, ops, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel = m[0], m[1]
        edits = m[2] if len(m) == 3 else [(m[2], m[3], 1)]
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        new = text
        ok = True
        for before, after, count in edits:
            probe = before.replace(NL, "\r\n") if crlf else before
            repl = after.replace(NL, "\r\n") if crlf else after
            if new.count(probe) < count:
                ok = False
                break
            new = new.replace(probe, repl, count)
        if not ok:
            missing.append(name)
            print("  %-44s PATTERN NOT FOUND" % name)
            continue
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
                if run_harness(exe, ops, out) != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction" % name)
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
    opsdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    # --only leaves the others unrun, so only the ones that ran are judged.
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
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

    sc = script()
    lines = model(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        rc, harness = harness_lines(exe, sc, tmp)

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc.ops), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
