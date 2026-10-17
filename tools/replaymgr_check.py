#!/usr/bin/env python3
"""Cross-check 3DS Files/source/replaymgr.c, ReplayManager (TASKS 72f-1),
against the retail image, SLES_507.31.

**The model** is retail's own code from Replay.obj run in
retail_model.RetailEmu: the constructor (0x0013d448) and destructor, the
beginning and end of time, BeginFrame and EndFrame with every private
method they reach (the instant replay's, the lap's, the dummy's and the
checksum's snapshots, IsSnapshotTime, CheckForSpecialEvents),
DoFancyJoylogDebugging, the highlights, AddSpecialEvent, Find,
GetSnapshot, SortSnapshots (with bList::Sort and AddTail), Restore and
Delete by name, DeleteSnapshot, TakeSnapshot, RestoreSnapshot,
HandleSnapshot, DoEndSnapshot, GetData, GetSignedData and AddData. Run real
on both sides as well: ReplaySnapshot, bRepeat, Timer::SetTime, bStrCmp,
bSPrintf and bMemSet.

**The stubs**, recorded alike on both sides as lines both print: bMalloc
(0x002577c0) makes a block filled with 0xcd, numbered in order (the
manager is #0); bFree (0x00257850) prints the block; bCountFreeMemory
(0x00257988) answers what the script says; bBreak counts, as replay_breaks
does. RaceParameters::DoSnapshot (0x001ed6f8), JoystickDoSnapshot
(0x001544f8) and RaceCoordinator::DoSnapshot (0x001498f0) print their
snapshot and its modes, move its DataPosition on by the script's `grow`,
and overflow the next snapshot of a name the script gives. HandlePauseMenuReplaySpecialEvents
(0x001703e0) prints the event (and where it is in the table), and can add
one to the table; DemoModeReplay::Service (0x0013f500) prints its flag.

The globals are retail's: WorldLoopCounter, WorldTimer, WorldTimeFrames,
WorldTimeElapsed and RealLoopCounter (gp-19552, -19576, -19564, -19560,
-19580), Joylog::ReplayingFlag (gp-20668), pRaceCoordinator (gp-22216),
TheDemoModeReplay's ActiveFlag, log and list (0x002f0960, 0x002f0994,
0x002f0998, the list made empty as its constructor does) and
ChecksumSnapshotTimes (0x002f08d8).

**The script** makes and unmakes managers with and without a log, too
little memory and just enough; a demo replay's log and snapshots handed
over and back; a capture of 520 frames with instant replays turned into
highlights by their interest (overlapping and not, a full set), lap
snapshots through two doublings, dummies every 211 loops and after 30,
overflowing takes, checksums taken twice (a break), special events kept;
the end of time; a pause at the end; a replay from the first lap with the
log read back, the dummies on the capture's loops, slow motion, the
special events made again (one handler adding another), a jump back; the
highlights in turn and muted; sorts; the manager's own snapshot taken and
restored over other values with a full times table; the joylog debugging
through its four states; GetData's errors and GetSignedData's widths; a
log filled to its end and a special-event table overflowed.

    python tools/replaymgr_check.py
    python tools/replaymgr_check.py --mutate [--only a,b] [--jobs N]
    python tools/replaymgr_check.py --dump out/replaymgr
"""
import argparse
import os
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

NL = chr(10)

HARNESS = "tools/src/replaymgr_test.c"
_S = "3DS Files/source/"
MGR = _S + "replaymgr.c"
SOURCES = [HARNESS, MGR, _S + "replay.c", _S + "brepeat.c", _S + "p32.c",
           _S + "timer.c"]

GP = retail_model.RETAIL_GP
WORLD_LOOP = GP - 19552
WORLD_TIMER = GP - 19576
WORLD_FRAMES = GP - 19564
WORLD_ELAPSED = GP - 19560
REAL_LOOP = GP - 19580
JOYLOG_REPLAYING = GP - 20668
P_RACE_COORD = GP - 22216
THE_RACE_PARAMETERS = 0x0031a898
DEMO = 0x002f0960
DEMO_REPEAT = DEMO + 52
DEMO_LIST = DEMO + 56
CHECKSUM_TIMES = 0x002f08d8

RM_SIZE = 20664
SNAP_SIZE = 38232
LOG_SIZE = 0x32000
FILL = 0xcd

F_CTOR = 0x0013d448
F_DTOR = 0x0013d5c0
F_BOT = 0x0013d6f8
F_EOT = 0x0013d868
F_BEGIN_FRAME = 0x0013d880
F_END_FRAME = 0x0013e008
F_FANCY = 0x0013e078
F_BRH = 0x0013e308
F_BNRH = 0x0013e318
F_ASE = 0x0013e3f8
F_FIND = 0x0013e5c8
F_GET = 0x0013e648
F_SORT = 0x0013e690
F_RESTORE_NAMED = 0x0013e748
F_DELETE_NAMED = 0x0013e790
F_DELETE = 0x0013e7d8
F_TAKE = 0x0013e9f0
F_RESTORE = 0x0013eb38
F_GET_DATA = 0x0013eb88
F_GET_SIGNED = 0x0013ebe8
F_ADD_DATA = 0x0013ec20
F_SNAP_INIT = 0x0013cce8
R_PREP_ADD = 0x001eb120

S_MALLOC = 0x002577c0
S_FREE = 0x00257850
S_COUNT_FREE = 0x00257988
S_BBREAK = 0x00250ab0
S_RP_SNAP = 0x001ed6f8
S_JOY_SNAP = 0x001544f8
S_RC_SNAP = 0x001498f0
S_HANDLE_EVENT = 0x001703e0
S_SERVICE = 0x0013f500

# The RaceCoordinator pCurrentRaceCoordinator points at, a word nothing
# reads.
RC_FAKE = 0x00e00000

LIMIT = 20000000

# =================================================================== script


def fbits(f):
    return "0x%08x" % struct.unpack("<I", struct.pack("<f", f))[0]


class Clock(object):
    """The world's clocks, stepped a frame at a time."""

    def __init__(self, wlc, wt, wtf, rlc):
        self.wlc, self.wt, self.wtf, self.rlc = wlc, wt, wtf, rlc

    def set(self):
        return ["g|wlc|%d" % self.wlc, "g|wt|%d" % self.wt,
                "g|wtf|%d" % self.wtf, "g|rlc|%d" % self.rlc]

    def frame(self, mid=(), wt_step=2000, wtf_step=10, loop_step=1):
        s = self.set() + ["bf"] + list(mid) + ["ef"]
        self.wlc += loop_step
        self.wt += wt_step
        self.wtf += wtf_step
        self.rlc += 1
        return s


def sc_setup():
    # 0.0334375 s is 133.75 ticks: SetTime's half rounds it up.
    return ["cst|-1|-1|-1|-1", "g|rc|1", "g|wte|%s" % fbits(0.0334375),
            "g|free|0x7fffffff", "g|grow|0", "g|joy|0", "g|demo|0"]


def sc_plain():
    """No beginning of time: nothing taken, nothing captured."""
    s = ["g|wlc|40", "g|wt|300", "ctor", "dump", "take|EARLY",
         "find|EARLY|0", "get|0", "dsn|EARLY", "rsn|EARLY", "bf", "ef",
         "ad|5|8|0", "gd|8|0", "dump", "eot", "dump", "eot", "dump",
         "ase|3|4|5", "dump", "dtor|0", "dump", "ctor", "dtor|1", "dump"]
    return s


def sc_memory():
    """Too little memory for the log, then just enough."""
    need = 0xd0ad8 + 32768
    s = ["g|wlc|500", "g|wt|9000", "ctor", "g|free|%d" % (need - 1), "bot",
         "dump", "g|free|0x7fffffff", "bot", "dump", "ase|1|2|3", "dump",
         "bf", "ef", "dump", "dtor|0"]
    s += ["g|free|0", "ctor", "bot", "dump", "dtor|0"]
    s += ["g|free|%d" % need, "g|wlc|501", "g|wt|9100", "ctor", "eot", "bot",
          "dump", "bot", "dump", "dtor|0", "dump", "g|free|0x7fffffff"]
    return s


def sc_demo():
    """A demo replay's log and snapshots, handed over and back."""
    s = ["demolog", "g|wlc|7", "g|wt|70", "demosnap|DEMO_A",
         "demosnap|DEMO_B", "demosnap|DEMO_C", "g|demo|1", "ctor", "dump",
         "ase|2|3|4", "dump"]
    c = Clock(7, 70, 700, 3)
    s += c.frame(["gd|8|0", "gd|4|1"]) + ["dump", "take|X", "dump"]
    s += ["sfn|DEMO_C|0|56|4|0", "dtor|0", "dump"]
    # Again: the snapshots that came back, and the log.
    s += ["ctor", "dump", "dtor|1", "dump"]
    # With nothing left to hand over.
    s += ["ctor", "dump", "dtor|0", "dump", "g|demo|0"]
    return s


def capture_mid(i):
    """What happens in capture frame i, between BeginFrame and EndFrame."""
    m = ["ad|%d|8|0" % (i & 0xff)]
    if i % 3 == 0:
        m.append("ad|%d|4|1" % (i % 13))
    if i % 5 == 0:
        m.append("ad|%d|16|2" % (i * 997 & 0xffff))
    if i % 7 == 0:
        m.append("ad|1|8|3")
    if i in (15, 100, 101, 300):
        m.append("ase|%d|%d|%d" % (i % 4, i, -i))
    if i == 15:
        m.append("ase|9|8|7")
    return m


INTEREST = {
    # frame: (k, value) set on INSTANT_REPLAY k before the frame
    25: (0, 3.0), 55: (0, 5.0), 85: (0, 1.0), 115: (0, 0.0),
    145: (0, 7.5), 175: (0, -2.0), 205: (0, 9.0), 235: (0, 2.0),
    265: (0, 6.0), 295: (0, 6.0), 325: (0, 11.0), 355: (0, 0.5),
    385: (0, 12.0), 415: (0, 13.0), 445: (0, 4.0), 475: (0, 20.0),
    505: (0, 8.0),
}

# Snapshots that overflow, before the frame.
OVERFLOW = {59: "INSTANT_REPLAY", 149: "LAP_SNAPSHOT", 179: "LAP_SNAPSHOT",
            200: "DUMMY_SNAPSHOT", 289: "CHECKSUM0"}


def sc_capture():
    """520 frames captured from loop 1000."""
    c = Clock(1000, 40000, 6000, 77)
    s = ["ctor", "g|grow|100"] + c.set() + ["bot", "dump"]
    s += ["cst|1100|1101|1250|-1"]
    for i in range(520):
        if i in INTEREST:
            k, v = INTEREST[i]
            s.append("sfn|INSTANT_REPLAY|%d|332|4|%s" % (k, fbits(v)))
        if i == 240:
            # A highlight that ends before the next instant replay begins.
            s.append("sfn|HIGHLIGHT_SNAPSHOT|0|52|4|0")
        if i == 360:
            s.append("sfn|HIGHLIGHT_SNAPSHOT|1|52|4|0")
        if i == 290:
            s.append("cst|1300|-1|-1|1302")
        if i in OVERFLOW:
            s.append("ovfname|" + OVERFLOW[i])
        s += c.frame(capture_mid(i))
        if i % 40 == 39:
            s.append("dump")
    s += ["eot", "ase|7|7|7", "dump"]
    s += c.frame(["ad|1|8|0"]) + c.frame() + ["dump"]
    # Paused at the capture's end: replayed.
    s += ["atend|0", "f|16|1", "bf", "dump", "ef", "f|16|0", "dump"]
    return s


def replay_mid(i):
    m = ["gd|8|0"]
    if i % 3 == 0:
        m.append("gd|4|1")
    if i % 5 == 0:
        m.append("gsd|16|2")
    if i % 7 == 0:
        m.append("gd|8|3")
    return m + ["rmw"]


def sc_replay():
    """From the first lap snapshot on, over the capture's loops: slow motion
    over a snapshot's loop, a pause over a checksum's, a log error."""
    s = ["rsn|LAP_SNAPSHOT", "dump", "atsnap|LAP_SNAPSHOT|0|0",
         "cst|1061|1101|1250|1302"]
    for i in range(330):
        if i == 98:
            s.append("hadd|5|50|60")
        if i == 300:
            s.append("hadd|6|70|80")
        if i == 50:
            s.append("f|20|1")
        if i == 67:
            s.append("f|20|0")
        if i == 59:
            s.append("f|16|1")
        if i == 63:
            s.append("f|16|0")
        if i == 64:
            s.append("cst|1100|1101|1250|1302")
        if i == 200:
            s.append("f|8|1")
        s += ["~frame|%d" % i]
        if i % 40 == 39:
            s.append("dump")
    s += ["dump"]
    # Back to the first highlight, a few frames on from it, then back to
    # the start, and on.
    s += ["rsn|HIGHLIGHT_SNAPSHOT", "atsnap|HIGHLIGHT_SNAPSHOT|0|0"]
    s += ["~frame|0", "~frame|1", "dump"]
    s += ["atsnap|LAP_SNAPSHOT|0|-3", "~frame|2", "~frame|3",
          "atsnap|LAP_SNAPSHOT|0|20", "~frame|4", "dump",
          "atsnap|LAP_SNAPSHOT|0|15", "~frame|5", "dump"]
    return s


def sc_highlights():
    s = ["f|156|2", "brh", "dump"]
    for _ in range(6):
        s += ["bnrh", "dump"]
    s += ["f|12|1", "bnrh", "dump", "f|12|0", "f|16|0", "bnrh", "dump"]
    return s


def sc_lists():
    s = ["find|LAP_SNAPSHOT|0", "find|LAP_SNAPSHOT|3", "find|LAP_SNAPSHOT|40",
         "find|CHECKSUM1|0", "find|NONE|0", "get|0", "get|5", "get|200",
         "get|-1"]
    s += ["sfn|LAP_SNAPSHOT|0|48|4|99999", "sfn|LAP_SNAPSHOT|2|48|4|5",
          "sfn|LAP_SNAPSHOT|3|48|4|5", "sort|LAP_SNAPSHOT", "dump",
          "sort|HIGHLIGHT_SNAPSHOT", "sort|NONE", "dump"]
    s += ["dsn|NONE", "rsn|NONE", "dsn|INSTANT_REPLAY", "del|0", "del|300",
          "rest|LAP_SNAPSHOT|2", "rest|LAP_SNAPSHOT|300", "dump"]
    return s


def sc_state():
    """The manager's own snapshot, taken and restored over other values;
    the snapshot times, full and searched."""
    s = ["atend|0", "take|REPLAY_MANAGER_STATE", "dump",
         "f|80|5", "f|84|6", "f|168|2", "f|16560|1",
         "rsn|REPLAY_MANAGER_STATE", "dump"]
    # The times table full: one more at the end, then none.
    s += ["f|168|4095", "atend|0", "take|AT_END", "take|AT_END2", "dump",
          "atend|-5", "take|NOT_AT_END", "dump",
          "take|REPLAY_MANAGER_STATE", "f|168|3", "f|172|0",
          "rsn|REPLAY_MANAGER_STATE", "dump"]
    # Replayed frames: from the start, from a cursor on an earlier time,
    # one on the same time, one past every real time, and the last time.
    s += ["atbegin|3", "bf", "ef", "f|172|2", "atbegin|4", "bf", "ef",
          "dump"]
    s += ["f|172|3", "atbegin|30", "bf", "ef", "rmw", "dump"]
    s += ["f|172|30", "atbegin|31", "bf", "ef", "atbegin|30", "bf", "ef",
          "dump"]
    s += ["f|168|3", "f|172|0", "atbegin|29", "bf", "ef", "atbegin|30",
          "bf", "ef", "dump"]
    s += ["f|168|6", "f|176|1010", "f|180|1020", "f|184|1030", "f|188|1020",
          "f|192|1030", "f|196|1040", "f|16|0", "f|20|0"]
    for cur, d in ((3, 30), (3, 20), (0, 40), (1, 20)):
        s += ["f|172|%d" % cur, "f|164|0", "atbegin|%d" % d, "bf", "rmw",
              "ef", "dump"]
    return s


def sc_fancy():
    """DoFancyJoylogDebugging's four states."""
    s = ["g|joy|0", "atend|-1", "fancyat|1", "fancy", "dump"]
    s += ["g|joy|1", "fancyat|2", "fancy", "dump", "f|36|5"]
    s += ["fancyat|1", "fancy", "dump", "fancy",
          "dump", "fancy", "dump", "atend|0", "fancy", "dump", "f|16|1",
          "f|36|7",
          "atend|-2", "fancy", "atend|0", "fancy", "dump", "fancy", "dump",
          "f|36|12", "fancy", "dump", "f|36|13", "fancy", "dump", "fancy",
          "dump", "f|16|0"]
    return s


def sc_data():
    """GetData's widths and errors; the highlights with no highlight, then
    with no lap either."""
    s = ["atbegin|0", "bf", "gsd|0|0", "gsd|1|0", "gsd|31|1", "gsd|32|2",
         "gd|0|3", "gd|32|0", "gd|8|3", "gd|8|3", "gd|8|3", "dump", "ef",
         "gd|8|0", "dump"]
    s += ["rsn|LAP_SNAPSHOT", "dump"]
    s += ["dsn|HIGHLIGHT_SNAPSHOT"] * 6 + ["f|156|3", "bnrh", "dump"]
    s += ["dsn|LAP_SNAPSHOT"] * 10 + ["f|156|3", "bnrh", "dump"]
    s += ["dtor|1", "dump"]
    return s


def sc_full():
    """A log filled to its end, a bit at a time; a special-event table
    overflowed."""
    c = Clock(3000, 100, 100, 1)
    s = ["ctor"] + c.set() + ["bot"]
    mid = ["rset|8|1638290", "ad|5|8|0", "dump", "ad|6|8|0",
           "rset|8|1638300", "ad|5|8|0", "ad|6|8|0"]
    for k in range(40):
        mid += ["f|4|1", "f|88|0", "rset|8|%d" % (1638300 + k),
                "ad|%d|8|2" % (k + 1), "rmw"]
    s += c.frame(mid)
    s += ["dump"] + c.frame() + ["dump", "dtor|0"]
    c = Clock(4000, 100, 100, 1)
    s += ["ctor"] + c.set() + ["bot"]
    s += c.frame(["ase|%d|%d|%d" % (k & 3, k, k * 3) for k in range(257)]
                 + ["dump"])
    s += c.frame() + ["dump", "dtor|0"]
    return s


def sc_dummies():
    """A capture whose clocks stand still after its first frame: only the
    dummy snapshots, after 30 loops with none and on every 211th. Then one
    allowed no instant replays."""
    c = Clock(4200, 100, 100, 1)
    s = ["ctor"] + c.set() + ["bot"]
    for i in range(70):
        s += c.frame(wt_step=0, wtf_step=0)
        if i % 10 == 9:
            s.append("dump")
    s += ["dtor|0"]
    c = Clock(4400, 100, 100, 1)
    s += ["ctor"] + c.set() + ["bot", "f|124|0"]
    s += c.frame(wt_step=0, wtf_step=300) + ["dump"]
    s += c.frame(wt_step=0, wtf_step=300) + ["dump"]
    s += c.frame(wt_step=0, wtf_step=300) + ["dump", "dtor|0"]
    return s


def hl_set(k, tiv=None, elt=None):
    s = []
    if tiv is not None:
        s.append("sfn|HIGHLIGHT_SNAPSHOT|%d|332|4|%s" % (k, fbits(tiv)))
    if elt is not None:
        s.append("sfn|HIGHLIGHT_SNAPSHOT|%d|52|4|%d" % (k, elt))
    return s


def sc_highlight_choice():
    """Each of the instant replays' fates in turn: an instant replay every
    30 loops, the oldest's interest and the highlights' set just before."""
    c = Clock(5000, 100, 100, 1)
    s = ["ctor"] + c.set() + ["bot"]

    def to_decision(oldest_tiv, before=()):
        # 29 quiet frames, then the frame that decides.
        out = []
        for _ in range(29):
            out += c.frame(wt_step=0, wtf_step=10)
        out += list(before)
        out.append("sfn|INSTANT_REPLAY|0|332|4|%s" % fbits(oldest_tiv))
        out += c.frame(wt_step=0, wtf_step=10) + ["dump"]
        return out

    s += c.frame(wt_step=0, wtf_step=10)
    # The second instant replay, then an uninteresting oldest goes.
    s += to_decision(0.0)
    s += to_decision(0.0)
    s += to_decision(2.0)
    no_overlap = lambda n: sum((hl_set(k, elt=0) for k in range(n)), [])
    # A slot free and no overlap: kept, though the least is more.
    s += to_decision(1.0, no_overlap(1))
    s += to_decision(3.0, no_overlap(2))
    s += to_decision(4.0, no_overlap(3))
    s += to_decision(5.0, no_overlap(4))
    # Full, two least alike: the first of them goes.
    s += to_decision(6.0, no_overlap(5) + hl_set(1, tiv=2.0))
    # A slot free, one overlapping and less: it goes.
    s += ["dsn|HIGHLIGHT_SNAPSHOT", "f|148|4"]
    s += to_decision(10.0, no_overlap(4) + hl_set(1, elt=999999))
    # A slot free, one overlapping and more: the oldest goes.
    s += ["dsn|HIGHLIGHT_SNAPSHOT", "f|148|3"]
    s += to_decision(1.5, no_overlap(3) + hl_set(2, tiv=50.0, elt=999999))
    s += ["dtor|0"]
    return s


def expand(lines):
    """~frame|I: a replayed frame, on from the loop the script put
    WorldLoopCounter on. RealLoopCounter is 2 mod 4 on loop 1060, a
    snapshot's, in slow motion."""
    out = []
    for ln in lines:
        if ln.startswith("~frame|"):
            i = int(ln.split("|")[1])
            out += ["g|wt|%d" % (40000 + 2000 * i),
                    "g|wtf|%d" % (6000 + 10 * i), "g|rlc|%d" % (502 + i),
                    "bf"] + replay_mid(i) + ["ef", "step|1"]
            continue
        out.append(ln)
    return out


def script():
    return expand(sc_setup() + sc_plain() + sc_memory() + sc_demo() +
                  sc_capture() + sc_replay() + sc_highlights() + sc_lists() +
                  sc_state() + sc_fancy() + sc_data() + sc_full() +
                  sc_dummies() + sc_highlight_choice())


# =================================================================== model

def label_of(blocks, a):
    if a == 0:
        return "0"
    if a == RC_FAKE:
        return "RC"
    for i, (b, n) in enumerate(blocks):
        if b == a:
            return "#%d" % i
    for i, (b, n) in enumerate(blocks):
        if b < a < b + n:
            return "#%d+%d" % (i, a - b)
    return "?"


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.breaks = 0
        self.names = {}
        self.grow = 0
        self.ovf = None
        self.free_mem = 0x7fffffff
        self.hadd = None
        self.RM = e.alloc(RM_SIZE, align=16)
        e.write(self.RM, bytes([FILL]) * RM_SIZE)
        self.blocks = [(self.RM, RM_SIZE)]
        for a in (WORLD_LOOP, WORLD_TIMER, WORLD_FRAMES, WORLD_ELAPSED,
                  REAL_LOOP, JOYLOG_REPLAYING, P_RACE_COORD, DEMO,
                  DEMO_REPEAT):
            e.put32(a, 0)
        e.put32(DEMO_LIST, DEMO_LIST)
        e.put32(DEMO_LIST + 4, DEMO_LIST)
        e.stub(S_MALLOC, self.malloc)
        e.stub(S_FREE, self.free)
        e.stub(S_COUNT_FREE, self.count_free)
        e.stub(S_BBREAK, self.bbreak)
        e.stub(S_RP_SNAP, lambda em: self.recorded(
            "rp", self.arg(0) == THE_RACE_PARAMETERS, self.arg(1)))
        e.stub(S_JOY_SNAP, lambda em: self.recorded("joy", 1, self.arg(0)))
        e.stub(S_RC_SNAP, self.rc_snap)
        e.stub(S_HANDLE_EVENT, self.on_event)
        e.stub(S_SERVICE, self.on_service)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[4 + i] & M32

    def label(self, a):
        return label_of(self.blocks, a & M32)

    def name(self, s):
        if s not in self.names:
            a = self.e.alloc(len(s) + 1, align=4)
            self.e.write(a, s.encode("latin-1") + b"\0")
            self.names[s] = a
        return self.names[s]

    def cstr(self, a, n=64):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def i32(self, a):
        return s32(self.e.u32(a))

    def call(self, f, *args):
        return self.e.call(f, *[s32(a & M32) for a in args], limit=LIMIT)

    # ---- the stubs

    def new_block(self, size, name, flags, pool):
        e = self.e
        a = e.alloc(size + 16, align=16)
        e.write(a, bytes([FILL]) * size)
        self.emit("malloc #%d size=%d name=%s flags=%d pool=%d" % (
            len(self.blocks), size, name, flags, pool))
        self.blocks.append((a, size))
        return a

    def malloc(self, em):
        nm = self.arg(1)
        return self.new_block(s32(self.arg(0)),
                              self.cstr(nm) if nm else "-",
                              s32(self.arg(2)), s32(self.arg(3)))

    def free(self, em):
        self.emit("free %s" % self.label(self.arg(0)))
        return 0

    def count_free(self, em):
        self.emit("count pool=%d" % s32(self.arg(0)))
        return s32(self.free_mem)

    def bbreak(self, em):
        self.breaks += 1
        return 0

    def recorded(self, what, ok, s):
        e = self.e
        b = lambda o: s32(e.mem[s + o] << 24) >> 24
        self.emit("cb %s ok=%d s=%s mode=%d,%d,%d,%d pos=%d" % (
            what, 1 if ok else 0, self.label(s), b(60), b(61), b(62), b(63),
            self.i32(s + 336)))
        e.put32(s + 336, (self.i32(s + 336) + self.grow) & M32)
        if self.ovf is not None and self.cstr(s + 8, 32) == self.ovf:
            self.ovf = None
            e.mem[s + 65] = 1
        return 0

    def rc_snap(self, em):
        self.emit("cb rc arg=%s" % self.label(self.arg(0)))
        return self.recorded("rc", 1, self.arg(1))

    def on_event(self, em):
        e, RM = self.e, self.RM
        p = self.arg(0)
        t = RM + 16568
        idx = (p - t) // 16 if t <= p < t + 16 * 256 else -1
        self.emit("ev in=%d type=%d loop=%d a=%d b=%d" % (
            idx, self.i32(p), self.i32(p + 4), self.i32(p + 8),
            self.i32(p + 12)))
        if self.hadd is not None:
            n = self.i32(RM + 16560)
            for k, v in enumerate(self.hadd):
                e.put32(t + 16 * n + 4 * k, v & M32)
            e.put32(RM + 16560, n + 1)
            self.hadd = None
            self.emit("hadd n=%d" % (n + 1))
        return 0

    def on_service(self, em):
        assert self.arg(0) == DEMO
        self.emit("svc flag=%d" % s32(self.arg(1)))
        return 0

    # ---- lists

    def print_snapshot(self, a):
        e = self.e
        b = lambda o: s32(e.mem[a + o] << 24) >> 24
        nm = e.read(a + 8, 32).split(b"\0")[0].decode("latin-1")
        crc = zlib.crc32(bytes(e.mem[a + 344:a + 344 + 37888])) & M32
        self.emit("  s %s name=%s t=%d et=%d blt=%d elt=%d mil=%d "
                  "f=%d,%d,%d,%d,%d,%d tiv=%08x pos=%d size=%d crc=%08x" % (
                      self.label(a), nm, self.i32(a + 40), self.i32(a + 44),
                      self.i32(a + 48), self.i32(a + 52), self.i32(a + 56),
                      b(60), b(61), b(62), b(63), b(64), b(65),
                      e.u32(a + 332), self.i32(a + 336), self.i32(a + 340),
                      crc))

    def walk(self, what, head):
        e = self.e
        prev, n = head, e.u32(head)
        seen = []
        parts = []
        while n != head and len(seen) < 64:
            if n == 0:
                parts.append(" NULL")
                break
            parts.append(" %s%s" % (self.label(n),
                                    "" if e.u32(n + 4) == prev else "!"))
            seen.append(n)
            prev, n = n, e.u32(n)
        self.emit("%s:%s%s back=%s" % (what, "".join(parts),
                                       "" if n == head else " ...",
                                       "ok" if e.u32(head + 4) == prev
                                       else "bad"))
        for a in seen:
            self.print_snapshot(a)

    def nth(self, name, k):
        e = self.e
        head = self.RM + 112
        n = e.u32(head)
        guard = 0
        while n != head and guard < 256:
            guard += 1
            if name is None or self.cstr(n + 8, 32) == name:
                if k == 0:
                    return n
                k -= 1
            n = e.u32(n)
        return 0

    # ---- dump

    def words(self, what, base, lo, hi):
        self.emit(what + "".join(" %d" % self.i32(base + o)
                                 for o in range(lo, hi, 4)))

    def dump(self):
        e, RM = self.e, self.RM
        self.words("rm", RM, 0, 44)
        self.emit("fancy " + e.read(RM + 44, 32).hex())
        self.words("rm2", RM, 76, 100)
        self.emit("rep %s" % self.label(e.u32(RM + 100)))
        self.words("rm3", RM, 120, 176)
        n = max(0, min(self.i32(RM + 168), 24))
        self.emit("times crc=%08x%s" % (
            zlib.crc32(e.read(RM + 176, 16384)) & M32,
            "".join(" %d" % self.i32(RM + 176 + 4 * i) for i in range(n))))
        self.words("rm4", RM, 16560, 16568)
        n = max(0, min(self.i32(RM + 16560), 12))
        evs = ""
        for i in range(n):
            a = RM + 16568 + 16 * i
            evs += " %d/%d/%d/%d" % tuple(self.i32(a + 4 * k)
                                          for k in range(4))
        self.emit("events crc=%08x%s" % (
            zlib.crc32(e.read(RM + 16568, 4096)) & M32, evs))
        self.walk("free", RM + 104)
        self.walk("snaps", RM + 112)
        self.emit("demo rep=%s" % self.label(e.u32(DEMO_REPEAT)))
        self.walk("demo", DEMO_LIST)
        self.emit("glob cst=%d,%d,%d,%d joy=%d breaks=%d" % (
            self.i32(CHECKSUM_TIMES), self.i32(CHECKSUM_TIMES + 4),
            self.i32(CHECKSUM_TIMES + 8), self.i32(CHECKSUM_TIMES + 12),
            self.i32(JOYLOG_REPLAYING), self.breaks))
        r = e.u32(RM + 100)
        if r:
            self.words("log", r, 0, 48)
            self.emit("logcrc %08x" % (zlib.crc32(e.read(r, LOG_SIZE))
                                       & M32))

    # ---- ops

    def set_global(self, g, v):
        e = self.e
        addr = {"wlc": WORLD_LOOP, "wt": WORLD_TIMER, "wtf": WORLD_FRAMES,
                "wte": WORLD_ELAPSED, "rlc": REAL_LOOP,
                "joy": JOYLOG_REPLAYING, "demo": DEMO}
        if g in addr:
            e.put32(addr[g], v & M32)
        elif g == "free":
            self.free_mem = v & M32
        elif g == "grow":
            self.grow = s32(v & M32)
        elif g == "rc":
            e.put32(P_RACE_COORD, RC_FAKE if v else 0)
        else:
            raise ValueError(g)

    def set_bytes(self, base, off, n, v):
        if n == 1:
            self.e.mem[base + off] = v & 0xff
        else:
            self.e.put32(base + off, v & M32)

    def op(self, a):
        e, RM = self.e, self.RM
        o = a[0]

        def num(i):
            return s32(int(a[i], 0) & M32)
        if o == "g":
            self.set_global(a[1], num(2))
        elif o == "ovfname":
            self.ovf = a[1]
        elif o == "rmw":
            self.words("rm", RM, 0, 44)
        elif o == "cst":
            for i in range(4):
                e.put32(CHECKSUM_TIMES + 4 * i, num(1 + i) & M32)
        elif o == "f":
            self.set_bytes(RM, num(1), 4, num(2))
        elif o == "sfn":
            s = self.nth(a[1], num(2))
            if s == 0:
                self.emit("sfn none")
            else:
                self.set_bytes(s, num(3), num(4), num(5))
        elif o == "rset":
            self.set_bytes(e.u32(RM + 100), num(1), 4, num(2))
        elif o == "demosnap":
            s = self.new_block(SNAP_SIZE, "DemoSnapshot", 0, 16)
            self.call(F_SNAP_INIT, s, self.name(a[1]))
            e.put32(s + 56, 1)
            tail = e.u32(DEMO_LIST + 4)
            e.put32(tail, s)
            e.put32(DEMO_LIST + 4, s)
            e.put32(s + 4, tail)
            e.put32(s, DEMO_LIST)
        elif o == "demolog":
            r = self.new_block(LOG_SIZE, "DemoLog", 0, 16)
            self.call(R_PREP_ADD, r, LOG_SIZE, 4, 0)
            for c, (rs, df) in enumerate(((8, 0), (4, 1), (0, 0), (8, 0))):
                e.put32(r + 48 + 36 * c, rs)
                e.put32(r + 48 + 36 * c + 4, df)
            e.put32(DEMO_REPEAT, r)
        elif o == "hadd":
            self.hadd = (num(1), self.i32(WORLD_LOOP), num(2), num(3))
        elif o == "ctor":
            e.write(RM, bytes([FILL]) * RM_SIZE)
            self.emit("-> %s" % self.label(self.call(F_CTOR, RM)))
        elif o == "dtor":
            self.call(F_DTOR, RM, num(1))
        elif o in ("bot", "eot", "bf", "ef", "fancy", "brh", "bnrh"):
            self.call({"bot": F_BOT, "eot": F_EOT, "bf": F_BEGIN_FRAME,
                       "ef": F_END_FRAME, "fancy": F_FANCY, "brh": F_BRH,
                       "bnrh": F_BNRH}[o], RM)
        elif o == "ase":
            self.call(F_ASE, RM, num(1), num(2), num(3))
        elif o == "find":
            self.emit("-> %s" % self.label(
                self.call(F_FIND, RM, self.name(a[1]), num(2))))
        elif o == "get":
            self.emit("-> %s" % self.label(self.call(F_GET, RM, num(1))))
        elif o == "sort":
            self.call(F_SORT, RM, self.name(a[1]))
        elif o == "rsn":
            self.emit("-> %d" % self.call(F_RESTORE_NAMED, RM,
                                          self.name(a[1])))
        elif o == "dsn":
            self.emit("-> %d" % self.call(F_DELETE_NAMED, RM,
                                          self.name(a[1])))
        elif o == "del":
            s = self.nth(None, num(1))
            if s == 0:
                self.emit("none")
            else:
                self.call(F_DELETE, RM, s)
        elif o == "rest":
            s = self.nth(a[1], num(2))
            if s == 0:
                self.emit("none")
            else:
                self.call(F_RESTORE, RM, s)
        elif o == "take":
            self.emit("-> %s" % self.label(self.call(F_TAKE, RM,
                                                     self.name(a[1]))))
        elif o == "gd":
            self.emit("-> %d" % self.call(F_GET_DATA, RM, num(1), num(2)))
        elif o == "gsd":
            self.emit("-> %d" % self.call(F_GET_SIGNED, RM, num(1), num(2)))
        elif o == "ad":
            self.call(F_ADD_DATA, RM, num(1), num(2), num(3))
        elif o == "atend":
            e.put32(WORLD_LOOP, (self.i32(RM + 84) + num(1)) & M32)
        elif o == "atbegin":
            e.put32(WORLD_LOOP, (self.i32(RM + 80) + num(1)) & M32)
        elif o == "atsnap":
            s = self.nth(a[1], num(2))
            if s == 0:
                self.emit("atsnap none")
            else:
                e.put32(WORLD_LOOP, (self.i32(s + 48) + num(3)) & M32)
        elif o == "step":
            e.put32(WORLD_LOOP, (self.i32(WORLD_LOOP) + num(1)) & M32)
        elif o == "fancyat":
            e.put32(RM + 28, (self.i32(WORLD_LOOP) + num(1)) & M32)
        elif o == "dump":
            self.dump()
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(lines):
    return mutpar.model_cached(lines, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="replaymgr_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path, timeout=120):
    rc = mutpar.run_exe([exe, sc_path], out_path, timeout)
    if rc == mutpar.HUNG:
        print("harness hung, killed after %d s" % timeout)
    elif rc != 0:
        print("harness exited %d" % rc)
    return rc


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_bytes((NL.join(lines) + NL).encode("latin-1"))
    return sc


# ============================================================ the mutations

def M(name, before, after):
    return (name, MGR, before, after)


MUTATIONS = [
    # the lists
    M("unlink-prev", "    prev->Next = n->Next;\n", "    prev->Next = n->Prev;\n"),
    M("unlink-next", "    next->Prev = n->Prev;\n", "    next->Prev = n->Next;\n"),
    M("tail-next", "    tail->Next = p32_of(n);\n", "    tail->Next = p32_of(l);\n"),
    M("tail-prev", "    n->Prev = p32_of(tail);\n", "    n->Prev = p32_of(l);\n"),
    M("append-empty", "    if (first == other)\n        return;\n", ""),
    M("append-reset",
      "    other->Prev = p32_of(other);\n    other->Next = p32_of(other);\n",
      ""),
    M("append-first-prev", "    first->Prev = p32_of(tail);\n",
      "    first->Prev = p32_of(l);\n"),
    M("append-last-next", "    last->Next = p32_of(l);\n",
      "    last->Next = p32_of(other);\n"),
    M("sort-key",
      "return link_snap(a)->BeginLoopTime <= link_snap(b)->BeginLoopTime;",
      "return link_snap(a)->EndLoopTime <= link_snap(b)->EndLoopTime;"),
    M("sort-strict", "BeginLoopTime <= link_snap(b)",
      "BeginLoopTime < link_snap(b)"),
    M("sort-none", "    list_sort(&tmp);\n", ""),
    M("sort-onepass", "                moved = 1;\n", ""),
    M("sort-append-free", "    list_append(snap_list(rm), &tmp);\n",
      "    list_append(free_list(rm), &tmp);\n"),
    M("nfs-time", "    s->Time = 0;\n    s->EndTime = 0;\n",
      "    s->EndTime = 0;\n"),
    M("nfs-endtime", "    s->EndTime = 0;\n    list_add_tail",
      "    list_add_tail"),
    M("ufs-new", "    if (link_at(free_list(rm)->Next) == free_list(rm))\n"
      "        new_free_snapshot(rm);\n", ""),
    # the constructor
    M("ctor-lst", "    rm->LastSnapshotTime = -1;\n",
      "    rm->LastSnapshotTime = 0;\n"),
    M("ctor-spacing", "    rm->LapSnapshotSpacing = 15.0f;\n",
      "    rm->LapSnapshotSpacing = 16.0f;\n"),
    M("ctor-fancy-time", "    rm->NextFancyDebugTime = 9999999;\n",
      "    rm->NextFancyDebugTime = 9999998;\n"),
    M("ctor-begin", "    rm->BeginCapturingLoopCount = -1;\n    rm->End",
      "    rm->BeginCapturingLoopCount = 0;\n    rm->End"),
    M("ctor-end", "    rm->EndCapturingLoopCount = -1;\n",
      "    rm->EndCapturingLoopCount = 0;\n"),
    M("ctor-finished",
      "    rm->FinishedAllCapturing = 0;\n    rm->BeginningOfTime = 0;\n",
      "    rm->BeginningOfTime = 0;\n"),
    M("ctor-RemoveDataError",
      "    rm->CapturingFlag = 0;\n    rm->RemoveDataError = 0;\n",
      "    rm->CapturingFlag = 0;\n"),
    M("ctor-NextHighlightNumber",
      "    rm->NextHighlightNumber = 0;\n    rm->EndCurrentHighlightTime",
      "    rm->EndCurrentHighlightTime"),
    M("ctor-events",
      "    memset(rm->SpecialEventTable, 0, sizeof rm->SpecialEventTable);\n",
      ""),
] + [M("ctor-" + f, "\n    rm->%s = 0;\n" % f, "\n") for f in (
    "ReplayingFlag", "CapturingFlag",
    "MuteHighlightSoundFlag", "PausedFlag", "SlowMotionFlag",
    "ReplayPausedThisFrame", "BeginningOfTime", "EndOfTime",
    "NextInstantReplaySnapshotTime", "NumSnapshotsTaken",
    "SnapshotTimeCursor", "FancyReplayInProgress", "FancyJoyEventNumber",
    "NumFancyJoyEvents", "pRepeat", "MaxNumSnapshots",
    "MaxNumInstantReplaySnapshots", "MaxNumLapSnapshots",
    "MaxNumHighlightSnapshots", "NumInstantReplaySnapshots",
    "NumLapSnapshots", "NumHighlightSnapshots", "EndCurrentHighlightTime",
    "NumSpecialEvents", "LastSpecialEventNumber")] + [
    M("demo-off", "    if (DemoModeReplayActiveFlag) {\n        rm->pRepeat",
      "    if (0) {\n        rm->pRepeat"),
    M("demo-rep", "        rm->pRepeat = DemoModeReplay_pRepeat;\n", ""),
    M("demo-keep", "        DemoModeReplay_pRepeat = 0;\n", ""),
    M("demo-list", "        list_append(snap_list(rm), demo_list());\n", ""),
    M("demo-one", "        rm->MaxNumSnapshots = 1;\n",
      "        rm->MaxNumSnapshots = 2;\n"),
    M("demo-count", "\n        while (++n < rm->MaxNumSnapshots);",
      "\n        while (++n < 2);"),
    # the destructor
    M("dtor-mil", "        if (s->MemoryImageLoadedFlag) {",
      "        if (0) {"),
    M("dtor-handback", "            list_add_tail(demo_list(), snap_link(s));\n",
      ""),
    M("dtor-handback-rep",
      "                DemoModeReplay_pRepeat = rm->pRepeat;\n", ""),
    M("dtor-handback-clear", "                rm->pRepeat = 0;\n", ""),
    M("dtor-handback-always",
      "            if (rm->pRepeat != 0) {\n                DemoModeReplay_pRepeat",
      "            if (1) {\n                DemoModeReplay_pRepeat"),
    M("dtor-mil-free", "        } else {\n            bFree(s);\n        }\n",
      "        }\n"),
    M("dtor-free-list", "    while (link_at(f->Next) != f) {",
      "    while (0) {"),
    M("dtor-free-log",
      "    if (rm->pRepeat != 0)\n        bFree(p32_ptr(rm->pRepeat));\n", ""),
    M("dtor-free-log-always", "    if (rm->pRepeat != 0)\n        bFree",
      "    if (1)\n        bFree"),
    M("dtor-free-self", "    if (flags & 1)\n        bFree(rm);\n", ""),
    M("dtor-free-self-always", "    if (flags & 1)\n", "    if (1)\n"),
    # MarkTheBeginningOfTime
    M("bot-once",
      "    if (rm->BeginCapturingLoopCount != -1)\n        return;\n", ""),
    M("bot-end", "    rm->EndCapturingLoopCount = WorldLoopCounter;\n",
      "    rm->EndCapturingLoopCount = WorldLoopCounter + 1;\n"),
    M("bot-begin", "    rm->BeginCapturingLoopCount = WorldLoopCounter;\n",
      "    rm->BeginCapturingLoopCount = WorldLoopCounter + 1;\n"),
    M("bot-bot", "    rm->BeginningOfTime = WorldTimer;\n",
      "    rm->BeginningOfTime = WorldTimer + 1;\n"),
    M("bot-eot", "    rm->EndOfTime = WorldTimer;\n", ""),
    M("bot-mem-le", "- 32768 < REPLAY_MIN_FREE)", "- 32768 <= REPLAY_MIN_FREE)"),
    M("bot-mem-slack", "- 32768 < REPLAY_MIN_FREE", "- 32767 < REPLAY_MIN_FREE"),
    M("bot-mem-pool", "gBCountFreeMemoryFn(REPLAY_POOL)",
      "gBCountFreeMemoryFn(0)"),
    M("bot-mem-off", "    if (gBCountFreeMemoryFn != NULL\n",
      "    if (gBCountFreeMemoryFn == NULL\n"),
    M("bot-log-size", "    r = bMalloc(REPLAY_LOG_SIZE,",
      "    r = bMalloc(REPLAY_LOG_SIZE + 4,"),
    M("bot-log-buf", "bRepeat_PrepareToAddData(r, REPLAY_LOG_SIZE, 4, 0);",
      "bRepeat_PrepareToAddData(r, REPLAY_LOG_SIZE - 4, 4, 0);"),
    M("bot-log-ch", "bRepeat_PrepareToAddData(r, REPLAY_LOG_SIZE, 4, 0);",
      "bRepeat_PrepareToAddData(r, REPLAY_LOG_SIZE, 5, 0);"),
    M("bot-ch0", "bRepeat_InitChannel(r, 0, 8, 0);",
      "bRepeat_InitChannel(r, 0, 7, 0);"),
    M("bot-ch1", "bRepeat_InitChannel(r, 1, 4, 1);",
      "bRepeat_InitChannel(r, 1, 4, 0);"),
    M("bot-ch1-bits", "bRepeat_InitChannel(r, 1, 4, 1);",
      "bRepeat_InitChannel(r, 1, 3, 1);"),
    M("bot-ch2", "bRepeat_InitChannel(r, 2, 0, 0);",
      "bRepeat_InitChannel(r, 2, 8, 0);"),
    M("bot-ch3", "bRepeat_InitChannel(r, 3, 8, 0);",
      "bRepeat_InitChannel(r, 3, 4, 0);"),
    M("bot-max", "rm->MaxNumSnapshots = 17;", "rm->MaxNumSnapshots = 16;"),
    M("bot-maxir", "rm->MaxNumInstantReplaySnapshots = 2;",
      "rm->MaxNumInstantReplaySnapshots = 3;"),
    M("bot-maxlap", "rm->MaxNumLapSnapshots = 8;",
      "rm->MaxNumLapSnapshots = 7;"),
    M("bot-maxhl", "rm->MaxNumHighlightSnapshots = 5;",
      "rm->MaxNumHighlightSnapshots = 4;"),
    M("bot-finished",
      "    rm->FinishedAllCapturing = 0;\n    rm->MaxNumAutoReplaySnapshots",
      "    rm->MaxNumAutoReplaySnapshots"),
    M("bot-auto", "    rm->MaxNumAutoReplaySnapshots = 0;\n", ""),
    M("bot-count", "\n    while (++n < rm->MaxNumSnapshots);",
      "\n    while (++n < rm->MaxNumSnapshots - 1);"),
    # MarkTheEndOfTime
    M("eot-noop",
      "    if (!rm->FinishedAllCapturing)\n        rm->FinishedAllCapturing = 1;\n",
      ""),
    M("eot-value", "        rm->FinishedAllCapturing = 1;\n",
      "        rm->FinishedAllCapturing = 2;\n"),
    # BeginFrame
    M("bf-norepeat",
      "    if (rm->pRepeat != 0) {\n        if (DemoModeReplayActiveFlag)",
      "    {\n        if (DemoModeReplayActiveFlag)"),
    M("bf-demo",
      "        if (DemoModeReplayActiveFlag)\n            rm->ReplayingFlag = 1;",
      "        if (0)\n            rm->ReplayingFlag = 1;"),
    M("bf-pause", "                 && rm->PausedFlag)\n",
      "                 && 0)\n"),
    M("bf-finished", "                 && !rm->FinishedAllCapturing)\n",
      "                 )\n"),
    M("bf-begin-le",
      "        else if (!(WorldLoopCounter < rm->BeginCapturingLoopCount)",
      "        else if (!(WorldLoopCounter <= rm->BeginCapturingLoopCount)"),
    M("bf-end-le", "                 && WorldLoopCounter < rm->EndCapturingLoopCount)\n",
      "                 && WorldLoopCounter <= rm->EndCapturingLoopCount)\n"),
    M("bf-ir", "        maybe_take_instant_replay_snapshot(rm);\n        if",
      "        if"),
    M("bf-lap", "            maybe_take_lap_snapshot(rm);\n", ""),
    M("bf-ptf-pause",
      "        if (rm->PausedFlag)\n            rm->ReplayPausedThisFrame = 1;",
      "        if (0)\n            rm->ReplayPausedThisFrame = 1;"),
    M("bf-slowmo-mod", "RealLoopCounter % 4 != 0", "RealLoopCounter % 2 != 0"),
    M("bf-slowmo-neg", "RealLoopCounter % 4 != 0", "RealLoopCounter % 4 == 0"),
    M("bf-slowmo-off", "        else if (rm->SlowMotionFlag)\n",
      "        else if (0)\n"),
    M("bf-events", "        check_for_special_events(rm);\n", ""),
    M("bf-events-always",
      "        check_for_special_events(rm);\n    }\n    maybe_take_dummy",
      "    }\n    check_for_special_events(rm);\n    maybe_take_dummy"),
    M("bf-dummy", "    maybe_take_dummy_snapshot(rm);\n    maybe_do",
      "    maybe_do"),
    M("bf-checksum", "    maybe_do_checksum_snapshot(rm);\n    if", "    if"),
    M("bf-svc-flag", "(WorldLoopCounter == rm->LastSnapshotTime);",
      "(WorldLoopCounter != rm->LastSnapshotTime);"),
    M("bf-svc-off", "    if (gDemoModeReplayServiceFn != NULL)\n",
      "    if (0)\n"),
    # EndFrame
    M("ef-end", "        rm->EndCapturingLoopCount = WorldLoopCounter + 1;",
      "        rm->EndCapturingLoopCount = WorldLoopCounter;"),
    M("ef-cap", "        rm->CapturingFlag = 0;\n        rm->EndOfTime",
      "        rm->EndOfTime"),
    M("ef-eot",
      "        rm->EndOfTime = (int32_t)((uint32_t)WorldTimer + t.PackedTime);",
      "        rm->EndOfTime = WorldTimer;"),
    M("ef-settime", "        timer_set_time(&t, WorldTimeElapsed);",
      "        t.PackedTime = (uint32_t)(WorldTimeElapsed * 4000.0f);"),
    M("ef-ptf",
      "        rm->ReplayPausedThisFrame = 0;\n        rm->ReplayingFlag = 0;\n",
      "        rm->ReplayingFlag = 0;\n"),
    M("ef-rep",
      "        rm->ReplayPausedThisFrame = 0;\n        rm->ReplayingFlag = 0;\n",
      "        rm->ReplayPausedThisFrame = 0;\n"),
    # IsSnapshotTime
    M("ist-cursor-off", "    if (rm->SnapshotTimeCursor != 0\n",
      "    if (0\n"),
    M("ist-cursor-nz", "    if (rm->SnapshotTimeCursor != 0\n", "    if (1\n"),
    M("ist-cursor-le", "SnapshotTimeTable[rm->SnapshotTimeCursor] < t)",
      "SnapshotTimeTable[rm->SnapshotTimeCursor] <= t)"),
    M("ist-cursor-start", "        i = rm->SnapshotTimeCursor;\n",
      "        i = rm->SnapshotTimeCursor + 1;\n"),
    M("ist-cursor-set", "            rm->SnapshotTimeCursor = i;\n", ""),
    M("ist-count", "    for (; i < rm->NumSnapshotsTaken; i++)",
      "    for (; i < rm->NumSnapshotsTaken - 1; i++)"),
    # the dummy snapshots
    M("dum-ptf",
      "    if (rm->ReplayingFlag && !rm->ReplayPausedThisFrame\n",
      "    if (rm->ReplayingFlag\n"),
    M("dum-lst",
      "        && WorldLoopCounter != rm->LastSnapshotTime)\n        take",
      "        )\n        take"),
    M("dum-replay",
      "        take = is_snapshot_time(rm, WorldLoopCounter) != 0;",
      "        take = 0;"),
    M("dum-211", "WorldLoopCounter % 211 == 0", "WorldLoopCounter % 210 == 0"),
    M("dum-30", "rm->LastSnapshotTime + 30 < WorldLoopCounter",
      "rm->LastSnapshotTime + 31 < WorldLoopCounter"),
    M("dum-30-le", "rm->LastSnapshotTime + 30 < WorldLoopCounter",
      "rm->LastSnapshotTime + 30 <= WorldLoopCounter"),
    M("dum-keep",
      "        replaymgr_delete_snapshot_named(rm, \"DUMMY_SNAPSHOT\");\n", ""),
    M("dum-cap-off",
      "    if (rm->CapturingFlag) {\n        if (WorldLoopCounter % 211",
      "    if (0) {\n        if (WorldLoopCounter % 211"),
    # the instant replays and the highlights they become
    M("ir-time-le",
      "    if (WorldTimeFrames < rm->NextInstantReplaySnapshotTime)",
      "    if (WorldTimeFrames <= rm->NextInstantReplaySnapshotTime)"),
    M("ir-300", "WorldTimeFrames + 300;", "WorldTimeFrames + 310;"),
    M("ir-num0", "    if (rm->NumInstantReplaySnapshots != 0\n",
      "    if (1\n"),
    M("ir-max", "             < rm->MaxNumInstantReplaySnapshots)) {",
      "             <= rm->MaxNumInstantReplaySnapshots)) {"),
    M("hl-loop-max", "        for (k = 0; k < rm->MaxNumHighlightSnapshots; k++) {",
      "        for (k = 0; k < rm->MaxNumHighlightSnapshots - 1; k++) {"),
    M("hl-skip-null",
      "                pick = NULL;\n                continue;",
      "                continue;"),
    M("hl-skip-break",
      "                pick = NULL;\n                continue;",
      "                pick = NULL;\n                break;"),
    M("hl-overlap-le", "            if (oldest->BeginLoopTime < h->EndLoopTime) {",
      "            if (oldest->BeginLoopTime <= h->EndLoopTime) {"),
    M("hl-overlap-off", "            if (oldest->BeginLoopTime < h->EndLoopTime) {",
      "            if (0) {"),
    M("hl-min-le",
      "                || h->TotalInterestingValue < pick->TotalInterestingValue)",
      "                || h->TotalInterestingValue <= pick->TotalInterestingValue)"),
    M("hl-pos", "        if (0.0f < oldest->TotalInterestingValue",
      "        if (0.0f <= oldest->TotalInterestingValue"),
    M("hl-better-le",
      "                                    < oldest->TotalInterestingValue)) {",
      "                                    <= oldest->TotalInterestingValue)) {"),
    M("hl-del-full",
      "            if (rm->NumHighlightSnapshots == rm->MaxNumHighlightSnapshots\n",
      "            if (0\n"),
    M("hl-del-overlap",
      "                    && oldest->BeginLoopTime < pick->EndLoopTime)) {",
      "                    && 0)) {"),
    M("hl-del-overlap-le",
      "                    && oldest->BeginLoopTime < pick->EndLoopTime)) {",
      "                    && oldest->BeginLoopTime <= pick->EndLoopTime)) {"),
    M("hl-del-num",
      "                replaymgr_delete_snapshot(rm, pick);\n"
      "                rm->NumHighlightSnapshots--;\n",
      "                replaymgr_delete_snapshot(rm, pick);\n"),
    M("hl-name", "ReplaySnapshot_ChangeName(oldest, \"HIGHLIGHT_SNAPSHOT\");",
      "ReplaySnapshot_ChangeName(oldest, \"HIGHLIGHT_SNAPSHOX\");"),
    M("hl-elt", "            oldest->EndLoopTime = WorldLoopCounter;\n", ""),
    M("hl-et", "            oldest->EndTime = WorldTimer;\n", ""),
    M("hl-numir",
      "            rm->NumInstantReplaySnapshots--;\n"
      "            rm->NumHighlightSnapshots++;\n",
      "            rm->NumHighlightSnapshots++;\n"),
    M("hl-numhl", "            rm->NumHighlightSnapshots++;\n", ""),
    M("ir-del-oldest",
      "            replaymgr_delete_snapshot_named(rm, \"INSTANT_REPLAY\");\n", ""),
    M("ir-del-count",
      "            replaymgr_delete_snapshot_named(rm, \"INSTANT_REPLAY\");\n"
      "            rm->NumInstantReplaySnapshots--;\n",
      "            replaymgr_delete_snapshot_named(rm, \"INSTANT_REPLAY\");\n"),
    M("ir-count",
      "    if (replaymgr_take_snapshot(rm, \"INSTANT_REPLAY\") != NULL)\n",
      "    replaymgr_take_snapshot(rm, \"INSTANT_REPLAY\");\n"),
    # the checksums
    M("ck-4", "    for (i = 0; i < 4; i++)\n", "    for (i = 0; i < 3; i++)\n"),
    M("ck-name", "\"CHECKSUM%d\", (int)i);", "\"CHECKSUM%d\", (int)i + 1);"),
    M("ck-break", "            replay_breaks++;\n", ""),
    M("ck-dp",
      "        s = use_free_snapshot(rm, name);\n        s->DataPosition = 0;\n",
      "        s = use_free_snapshot(rm, name);\n"),
    M("ck-flag", "        s->TakingChecksumFlag = 1;\n", ""),
    M("ck-size",
      "        s->SizeofData = s->DataPosition;\n        s->TakingChecksumFlag = 0;",
      "        s->TakingChecksumFlag = 0;"),
    M("ck-flag-clear", "        s->TakingChecksumFlag = 0;\n", ""),
    M("ck-verify-ptf",
      "    } else if (rm->ReplayingFlag && !rm->ReplayPausedThisFrame) {",
      "    } else if (rm->ReplayingFlag) {"),
    M("ck-verify-dp",
      "        if (s != NULL) {\n            s->DataPosition = 0;\n",
      "        if (s != NULL) {\n"),
    M("ck-verify-flag", "            s->VerifyingChecksumFlag = 1;\n", ""),
    M("ck-verify-clear", "            s->VerifyingChecksumFlag = 0;\n", ""),
    # the lap snapshots
    M("lap-le", "              <= (float)(int32_t)((uint32_t)WorldTimer",
      "              < (float)(int32_t)((uint32_t)WorldTimer"),
    M("lap-scale", "                     * 0.00025f))",
      "                     * 0.0002f))"),
    M("lap-max", "        if (rm->NumLapSnapshots != rm->MaxNumLapSnapshots) {",
      "        if (rm->NumLapSnapshots < rm->MaxNumLapSnapshots - 1) {"),
    M("lap-count",
      "            if (replaymgr_take_snapshot(rm, \"LAP_SNAPSHOT\") != NULL)\n",
      "            replaymgr_take_snapshot(rm, \"LAP_SNAPSHOT\");\n"),
    M("lap-double", "                                 + rm->LapSnapshotSpacing;",
      "                                 + 1.0f;"),
    M("lap-keep-first",
      "\"LAP_SNAPSHOT\", k) != NULL) {\n            k++;\n",
      "\"LAP_SNAPSHOT\", k) != NULL) {\n"),
    M("lap-del-count",
      "                replaymgr_delete_snapshot(rm, s);\n"
      "                rm->NumLapSnapshots--;\n",
      "                replaymgr_delete_snapshot(rm, s);\n"),
    M("lap-once",
      "        if (!(rm->NumLapSnapshots < rm->MaxNumLapSnapshots))\n"
      "            return;\n    }\n",
      "        return;\n    }\n"),
    # DoFancyJoylogDebugging
    M("fancy-joy", "        if (Joylog_ReplayingFlag\n", "        if (1\n"),
    M("fancy-time", "WorldLoopCounter == rm->NextFancyDebugTime - 1)",
      "WorldLoopCounter == rm->NextFancyDebugTime)"),
    M("fancy-table1", "    131, 0, 0, 0, 0, 0, 4,", "    130, 0, 0, 0, 0, 0, 4,"),
    M("fancy-num1",
      "        rm->NumFancyJoyEvents = (int32_t)sizeof FancyEventsFirst;",
      "        rm->NumFancyJoyEvents = 23;"),
    M("fancy-fjn1",
      "        rm->FancyJoyEventNumber = 0;\n        }\n",
      "        }\n"),
    M("fancy-st1", "            rm->FancyReplayInProgress = 1;",
      "            rm->FancyReplayInProgress = 2;"),
    M("fancy-joy-off", "        Joylog_ReplayingFlag = 0;\n", ""),
    M("fancy-st2", "        rm->FancyReplayInProgress = 2;",
      "        rm->FancyReplayInProgress = 3;"),
    M("fancy-wait-end",
      "        if (WorldLoopCounter != rm->EndCapturingLoopCount\n"
      "            || !rm->PausedFlag)\n",
      "        if (!rm->PausedFlag)\n"),
    M("fancy-wait-pause", "            || !rm->PausedFlag)\n", "            )\n"),
    M("fancy-211", "        rm->NextFancyDebugTime += 211;",
      "        rm->NextFancyDebugTime += 210;"),
    M("fancy-del-ck0",
      "        replaymgr_delete_snapshot_named(rm, \"CHECKSUM0\");\n", ""),
    M("fancy-del-ck1",
      "        replaymgr_delete_snapshot_named(rm, \"CHECKSUM1\");\n", ""),
    M("fancy-del-ck2",
      "        replaymgr_delete_snapshot_named(rm, \"CHECKSUM2\");\n", ""),
    M("fancy-del-ck3",
      "        replaymgr_delete_snapshot_named(rm, \"CHECKSUM3\");\n", ""),
    M("fancy-cst0", "ChecksumSnapshotTimes[0] = now + 1;",
      "ChecksumSnapshotTimes[0] = now + 2;"),
    M("fancy-cst1", "ChecksumSnapshotTimes[1] = now + 52;",
      "ChecksumSnapshotTimes[1] = now + 51;"),
    M("fancy-cst2", "ChecksumSnapshotTimes[2] = now + 105;",
      "ChecksumSnapshotTimes[2] = now + 104;"),
    M("fancy-cst3", "ChecksumSnapshotTimes[3] = now + 158;",
      "ChecksumSnapshotTimes[3] = now + 157;"),
    M("fancy-st3", "        rm->FancyReplayInProgress = 3;",
      "        rm->FancyReplayInProgress = 0;"),
    M("fancy-table2", "    99, 0, 0,", "    98, 0, 0,"),
    M("fancy-num2",
      "        rm->NumFancyJoyEvents = (int32_t)sizeof FancyEventsSecond;",
      "        rm->NumFancyJoyEvents = 12;"),
    M("fancy-fjn2",
      "        rm->FancyJoyEventNumber = 0;\n    } else if (state == 3) {",
      "    } else if (state == 3) {"),
    M("fancy-wait-events",
      "        if (rm->FancyJoyEventNumber < rm->NumFancyJoyEvents)",
      "        if (rm->FancyJoyEventNumber <= rm->NumFancyJoyEvents)"),
    M("fancy-joy-on", "        Joylog_ReplayingFlag = 1;\n", ""),
    M("fancy-st0", "        rm->FancyReplayInProgress = 0;\n    }\n}",
      "    }\n}"),
    # the race's highlights
    M("brh-zero",
      "    rm->NextHighlightNumber = 0;\n    replaymgr_begin_next_race_highlight",
      "    replaymgr_begin_next_race_highlight"),
    M("bnrh-mute", "    if (rm->MuteHighlightSoundFlag) {", "    if (0) {"),
    M("bnrh-mute-pause",
      "        rm->PausedFlag = 1;\n        rm->EndCurrentHighlightTime",
      "        rm->EndCurrentHighlightTime"),
    M("bnrh-mute-end", "WorldLoopCounter + 1;\n        return;",
      "WorldLoopCounter;\n        return;"),
    M("bnrh-end", "        rm->EndCurrentHighlightTime = s->EndLoopTime;",
      "        rm->EndCurrentHighlightTime = s->BeginLoopTime;"),
    M("bnrh-next",
      "        rm->NextHighlightNumber = rm->NextHighlightNumber + 1;",
      "        rm->NextHighlightNumber = rm->NextHighlightNumber + 2;"),
    M("bnrh-wrap", "            rm->NextHighlightNumber = 0;\n    } else {",
      "    } else {"),
    M("bnrh-lap-name",
      "        s = replaymgr_find_snapshot(rm, \"LAP_SNAPSHOT\", 0);\n"
      "        if (s != NULL)\n            rm->EndCurrentHighlightTime",
      "        s = replaymgr_find_snapshot(rm, \"LAP_SNAPSHOT\", 1);\n"
      "        if (s != NULL)\n            rm->EndCurrentHighlightTime"),
    M("bnrh-lap",
      "            rm->EndCurrentHighlightTime = rm->EndCapturingLoopCount;",
      "            rm->EndCurrentHighlightTime = rm->BeginCapturingLoopCount;"),
    M("bnrh-none", "            rm->EndCurrentHighlightTime = 0;",
      "            rm->EndCurrentHighlightTime = -1;"),
    M("bnrh-lap-next",
      "            rm->EndCurrentHighlightTime = 0;\n"
      "        rm->NextHighlightNumber = 0;\n",
      "            rm->EndCurrentHighlightTime = 0;\n"),
    M("bnrh-restore",
      "    if (s != NULL)\n        replaymgr_restore_snapshot(rm, s);\n}",
      "}"),
    # the special events
    M("ase-type", "    e.Type = type;", "    e.Type = type + 1;"),
    M("ase-loop", "    e.LoopCount = WorldLoopCounter;",
      "    e.LoopCount = WorldLoopCounter + 1;"),
    M("ase-ab", "    e.A = a;\n    e.B = b;", "    e.A = b;\n    e.B = a;"),
    M("ase-begin",
      "    if (rm->BeginCapturingLoopCount != -1 && !rm->FinishedAllCapturing",
      "    if (!rm->FinishedAllCapturing"),
    M("ase-finished",
      " && !rm->FinishedAllCapturing\n        && rm->pRepeat != 0) {",
      "\n        && rm->pRepeat != 0) {"),
    M("ase-repeat", "        && rm->pRepeat != 0) {\n", "        ) {\n"),
    M("ase-256", "        if (rm->NumSpecialEvents < REPLAY_MAX_SPECIAL_EVENTS)",
      "        if (rm->NumSpecialEvents < REPLAY_MAX_SPECIAL_EVENTS - 1)"),
    M("ase-eot",
      "        else\n            replaymgr_mark_the_end_of_time(rm);\n", ""),
    M("ase-handle", "    handle_special_event(rm, &e);\n", ""),
    M("cse-none",
      "    if (n == 0)\n        return;\n    i = rm->LastSpecialEventNumber;",
      "    i = rm->LastSpecialEventNumber;"),
    M("cse-back-le",
      "           && !(rm->SpecialEventTable[i].LoopCount < WorldLoopCounter))",
      "           && !(rm->SpecialEventTable[i].LoopCount <= WorldLoopCounter))"),
    M("cse-back-off", "    while (i >= 0\n", "    while (0\n"),
    M("cse-clamp", "    if (i < 0)\n        i = 0;\n", ""),
    M("cse-start",
      "    if (i < n && !(WorldLoopCounter < rm->SpecialEventTable[i].LoopCount)) {",
      "    if (i < n) {"),
    M("cse-eq",
      "            if (rm->SpecialEventTable[i].LoopCount == WorldLoopCounter) {",
      "            if (1) {"),
    M("cse-reload", "                n = rm->NumSpecialEvents;\n", ""),
    M("cse-fwd-le",
      "                 && !(WorldLoopCounter < rm->SpecialEventTable[i].LoopCount));",
      "                 && !(WorldLoopCounter <= rm->SpecialEventTable[i].LoopCount));"),
    M("cse-last", "    if (n - 1 < i)\n", "    if (n < i)\n"),
    M("cse-store", "    rm->LastSpecialEventNumber = i;\n", ""),
    # finding, restoring and deleting
    M("find-k", "            if (k == 0)\n", "            if (k <= 1)\n"),
    M("find-name", "        if (strcmp(link_snap(n)->Name, name) == 0) {",
      "        if (strncmp(link_snap(n)->Name, name, 8) == 0) {"),
    M("get-k", "        if (k == 0)\n            return link_snap(n);\n        k--;",
      "        if (k == 1)\n            return link_snap(n);\n        k--;"),
    M("rsn-ret", "    replaymgr_restore_snapshot(rm, s);\n    return 1;",
      "    replaymgr_restore_snapshot(rm, s);\n    return 2;"),
    M("rsn-null", "        return 0;\n    replaymgr_restore_snapshot(rm, s);",
      "        return 2;\n    replaymgr_restore_snapshot(rm, s);"),
    M("dsn-ret", "    replaymgr_delete_snapshot(rm, s);\n    return 1;",
      "    replaymgr_delete_snapshot(rm, s);\n    return 2;"),
    M("dsn-null", "        return 0;\n    replaymgr_delete_snapshot(rm, s);",
      "        return 2;\n    replaymgr_delete_snapshot(rm, s);"),
    M("del-free",
      "    list_unlink(snap_link(s));\n    list_add_tail(free_list(rm), snap_link(s));\n}",
      "    list_unlink(snap_link(s));\n    list_add_tail(snap_list(rm), snap_link(s));\n}"),
    # HandleSnapshot
    M("hs-state", "    if (strcmp(s->Name, \"REPLAY_MANAGER_STATE\") == 0) {",
      "    if (0) {"),
    M("hs-state-fall", "        do_end_snapshot(rm, s);\n        return;\n",
      "        do_end_snapshot(rm, s);\n"),
    M("hs-rp", "    race_parameters_do_snapshot(&TheRaceParameters, s);\n", ""),
    M("hs-joy", "    JoystickDoSnapshot(s);\n", ""),
    M("hs-rc", "    racecoordinator_do_snapshot(pRaceCoordinator, s);",
      "    racecoordinator_do_snapshot(NULL, s);"),
    M("hs-adding-take",
      "    if ((s->TakingSnapshotFlag || s->TakingChecksumFlag)\n",
      "    if ((s->TakingChecksumFlag)\n"),
    M("hs-adding-ck",
      "    if ((s->TakingSnapshotFlag || s->TakingChecksumFlag)\n",
      "    if ((s->TakingSnapshotFlag)\n"),
    M("hs-adding-end",
      "        && WorldLoopCounter == rm->EndCapturingLoopCount)\n        bRepeat",
      "        )\n        bRepeat"),
    # DoEndSnapshot
    M("des-section", "(s, \"ReplayManager\");", "(s, \"ReplayManagex\");"),
    M("des-begin", "    ReplaySnapshot_MoveInt(s, &rm->BeginCapturingLoopCount, 4);\n",
      ""),
    M("des-end", "    ReplaySnapshot_MoveInt(s, &rm->EndCapturingLoopCount, 4);\n",
      ""),
    M("des-numst", "    ReplaySnapshot_MoveInt(s, &rm->NumSnapshotsTaken, 4);\n",
      ""),
    M("des-times", "&rm->SnapshotTimeTable[i], 4);",
      "&rm->SnapshotTimeTable[i], 2);"),
    M("des-numse", "    ReplaySnapshot_MoveInt(s, &rm->NumSpecialEvents, 4);\n",
      ""),
    M("des-events-size", "&rm->SpecialEventTable[i], 16, -1, 0);",
      "&rm->SpecialEventTable[i], 12, -1, 0);"),
    M("des-end-section", "    ReplaySnapshot_EndNamedSection(s);\n", ""),
    # TakeSnapshot and RestoreSnapshot
    M("take-begin", "    if (rm->BeginCapturingLoopCount < 0)\n",
      "    if (rm->BeginCapturingLoopCount < -1)\n"),
    M("take-time-end",
      "    if (WorldLoopCounter == rm->EndCapturingLoopCount\n"
      "        && rm->NumSnapshotsTaken",
      "    if (1\n        && rm->NumSnapshotsTaken"),
    M("take-time-max",
      "        && rm->NumSnapshotsTaken < REPLAY_MAX_SNAPSHOT_TIMES)",
      "        && rm->NumSnapshotsTaken < REPLAY_MAX_SNAPSHOT_TIMES - 1)"),
    M("take-time-over",
      "        && rm->NumSnapshotsTaken < REPLAY_MAX_SNAPSHOT_TIMES)",
      "        && rm->NumSnapshotsTaken <= REPLAY_MAX_SNAPSHOT_TIMES)"),
    M("take-lst",
      "    rm->LastSnapshotTime = WorldLoopCounter;\n    s->DataPosition = 0;\n",
      "    s->DataPosition = 0;\n"),
    M("take-dp",
      "    rm->LastSnapshotTime = WorldLoopCounter;\n    s->DataPosition = 0;\n",
      "    rm->LastSnapshotTime = WorldLoopCounter;\n"),
    M("take-flag", "    s->TakingSnapshotFlag = 1;\n", ""),
    M("take-size",
      "    s->SizeofData = s->DataPosition;\n    s->TakingSnapshotFlag = 0;",
      "    s->TakingSnapshotFlag = 0;"),
    M("take-flag-clear", "    s->TakingSnapshotFlag = 0;\n", ""),
    M("take-ovf", "    if (s->OverflowedFlag) {", "    if (0) {"),
    M("take-ovf-keep",
      "        replaymgr_delete_snapshot(rm, s);\n        return NULL;",
      "        return NULL;"),
    M("rest-dp", "    s->DataPosition = 0;\n    s->RestoringSnapshotFlag = 1;",
      "    s->RestoringSnapshotFlag = 1;"),
    M("rest-flag", "    s->RestoringSnapshotFlag = 1;\n", ""),
    M("rest-flag-clear", "    s->RestoringSnapshotFlag = 0;\n", ""),
    M("rest-err",
      "    rm->RemoveDataError = 0;\n    rm->LastSnapshotTime = WorldLoopCounter;\n",
      "    rm->LastSnapshotTime = WorldLoopCounter;\n"),
    M("rest-lst",
      "    rm->RemoveDataError = 0;\n    rm->LastSnapshotTime = WorldLoopCounter;\n",
      "    rm->RemoveDataError = 0;\n"),
    # the log
    M("gd-rep", "    if (!rm->ReplayingFlag)\n        return 0;",
      "    if (0)\n        return 0;"),
    M("gd-err", "    if (rm->RemoveDataError)\n        return 0;",
      "    if (0)\n        return 0;"),
    M("gd-err-set", "    if (r->RemoveDataError)\n        rm->RemoveDataError = 1;",
      "    if (0)\n        rm->RemoveDataError = 1;"),
    M("gsd-arith", "    return (int32_t)((v << sh) >> sh);",
      "    return (int32_t)(v << sh) >> sh;"),
    M("ad-cap",
      "    if (!rm->CapturingFlag)\n        return;\n    r = p32_ptr(rm->pRepeat);\n"
      "    bRepeat_AddData",
      "    r = p32_ptr(rm->pRepeat);\n    bRepeat_AddData"),
    M("ad-68", "r->AddBufferSize * 8 - 68))", "r->AddBufferSize * 8 - 67))"),
    M("ad-68-le", "(r->AddLocation < r->AddBufferSize",
      "(r->AddLocation <= r->AddBufferSize"),
    M("ad-eot",
      "        rm->CapturingFlag = 0;\n        replaymgr_mark_the_end_of_time(rm);",
      "        rm->CapturingFlag = 0;"),
    M("ad-cap-clear",
      "        rm->CapturingFlag = 0;\n        replaymgr_mark_the_end_of_time(rm);",
      "        replaymgr_mark_the_end_of_time(rm);"),
]

EQUIVALENT = {
    # Init has zeroed DataPosition already; retail zeroes it again.
    "ck-dp", "take-dp",
    # A section's name is a pointer kept for printing a checksum error; the
    # snapshot's data never holds it.
    "des-section",
    # With the cursor 0 the search starts at 0 either way.
    "ist-cursor-nz",
    # The cursor's entry is below t, so it is never the match.
    "ist-cursor-start",
    # Once k reaches NumHighlightSnapshots every later k does too: pick ends
    # NULL whether the walk goes on or stops.
    "hl-skip-break",
    # With a slot free a highlight is picked only by the overlap test, which
    # has BeginLoopTime below its EndLoopTime; full, it goes anyway.
    "hl-del-overlap-le",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = write_script(scdir.name, sc)
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
        todo, SOURCES, "replaymgr_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
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

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, sc)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
