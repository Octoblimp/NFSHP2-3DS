#!/usr/bin/env python3
"""Cross-check 3DS Files/source/eventmgr.c (the event manager), fernshaker.c
(the fern shakers), emodelanim.c (eModel's rigid animation timing) and
carevents.c (Car::TriggerEvents, Player::TriggerVisibleDrivingLine) against
the retail image itself, run in mipsemu (TASKS 73).

The model is the image. EventManager.obj (0x001ba078 .. 0x001ba6f8), the
FernShaker half of FernShaker.obj (0x001d9b58 .. 0x001da588), eModel's
GetRigidAnimation (0x0010c8f0), SetRigidAnimationFrameNumber (0x0010c910)
and GetRigidAnimationTime (0x0010dae8), Car::TriggerEvents (0x001335c0) and
Player::TriggerVisibleDrivingLine (0x00180b78) run as shipped, with
bStringHash and ~bTList<AcidEmitter> under them. The harness
(tools/src/eventmgr_test.c) runs the port over the same script, and the two
transcripts are diffed.

Stubbed on both sides, each printing what it is given:
  - the slot pools (bNewSlotPool, bDeleteSlotPool, bMalloc(SlotPool *),
    bOMalloc, bFree(SlotPool *, void *), bIsSlotPoolFull): a pool hands out
    its lowest free slot, filled with 0xcd, and frees without touching it;
  - bMalloc(int, const char *, int, int) and bFree(void *), blocks of 0xab;
  - bGetTicker and bGetTickerDifference, a tick that steps by a few 1024s
    and a difference of whole 1024ths;
  - vAABBTree::QueryLeaf, which answers the leaf the script gives the tree;
  - the WorldObject's constructor and destructor; the constructor gives
    the object the first scripted model of the name as its pModel;
  - afxGetEmitters (1 to 3 emitters by the hash's low bits),
    TriggerEmitter and the AcidEmitter's destructor;
  - ReplayManager::RegisterInterestingEvent and VisibleDrivingLine's
    constructor;
  - four event handlers, which print the event and then do what the script
    asks of them: lock or unlock it, add an event, remove one, remove a
    handler or add one, through the image's own functions (the port's on
    the harness side).

The records the code reads -- the chunks, the Car, the Player, the models,
solids and animations, the scenery sections -- are built at retail's
offsets on the model side and as the port's structs on the harness side,
each from the same script. After every op both sides print the whole state:
the stats, the handlers, the queue, the packs, the shakers, the instances'
ExcludeFlags, the models' animation starts and a hash of the emitters.

The script avoids what retail does not survive: UnloaderEventManager spins
forever on a chunk whose first child is not a header; an unloaded header
that was never linked unlinks through zeros; a fern code whose section is
past ScenerySectionHeaderTable is read past it; a looping animation of
length 0 divides by 0. A float prints as its bits.

    python tools/eventmgr_check.py
    python tools/eventmgr_check.py --mutate [--only a,b]
    python tools/eventmgr_check.py --dump out/eventmgr
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/eventmgr_test.c"
EMC = "3DS Files/source/eventmgr.c"
FSC = "3DS Files/source/fernshaker.c"
EMA = "3DS Files/source/emodelanim.c"
CEV = "3DS Files/source/carevents.c"
# emodelanim.c's Render setup, which these scenarios never reach, takes
# bMulMatrix and the frame malloc's words.
SOURCES = [HARNESS, EMC, FSC, EMA, CEV, "3DS Files/source/bmatrix.c",
           "3DS Files/source/eframe.c"]

HARNESS_TIMEOUT = 120
LIMIT = 20000000

# ================================================================ the image

GP = 0x003358f0
# EventManager.obj.
EM_INIT = 0x001ba078
EM_CLOSE = 0x001ba0c8
EM_LOADER = 0x001ba100
EM_UNLOADER = 0x001ba248
EM_ADD_HANDLER = 0x001ba2d0
EM_REMOVE_HANDLER = 0x001ba3a8
EM_ADD_EVENT = 0x001ba430
EM_REMOVE_EVENT = 0x001ba4b8
EM_LOCK = 0x001ba500
EM_UNLOCK = 0x001ba510
EM_PROCESS = 0x001ba520
EM_TRIGGER = 0x001ba6f8
EM_SINIT = 0x001ba9c8             # _GLOBAL_$I$EventSlotPool
# FernShaker.obj.
FLATTEN_FERN = 0x001d9b58
INIT_FS = 0x001da0f8
FLUSH_FS = 0x001da1b0
CLOSE_FS = 0x001da200
SHAKE_FERN = 0x001da270
# eModel.
GET_ANIM = 0x0010c8f0
SET_FRAME = 0x0010c910
GET_TIME = 0x0010dae8
# Car and Player.
CAR_TRIGGER_EVENTS = 0x001335c0
PLAYER_TVDL = 0x00180b78
# The stand-ins.
BNEWSLOTPOOL = 0x00257c10
BDELETESLOTPOOL = 0x00257c48
BMALLOC_POOL = 0x00257c60
BOMALLOC = 0x00257c80
BFREE_POOL = 0x00257ca0
BISFULL = 0x00257d10
BMALLOC = 0x002577c0
BFREE = 0x00257850
TICKER = 0x00250f38
TICKDIFF = 0x00250f48
QUERY_LEAF = 0x001b9fd8
WO_CTOR = 0x001cd760
WO_DTOR = 0x001cd828
AFX = 0x001272e0
TRIG_EMITTER = 0x00127700
EMITTER_DELETE = 0x00124e20
INTERESTING = 0x0013e270
VDL_CTOR = 0x00174ec0

# The image's globals.
G_EVENT_POOL = GP - 18624
G_HANDLER_POOL = GP - 18620
G_EMPTY_PACKS = GP - 18616
G_PACKS = GP - 18608
G_HANDLERS = GP - 18600
G_MASTER = GP - 18592
G_CURQ = GP - 18584
G_CURRENT = GP - 18580
STATS = 0x00313fb0
TRIGGER_ARRAY = 0x00313fc8
NUM_TRIGGER_SLOTS = 41
G_FS_TABLE = GP - 17664
G_FS_COUNT = GP - 17660
G_FS_POOL = GP - 17656
G_FS_LIST = GP - 17648
G_WTF = GP - 19564                # WorldTimeFrames
G_WLC = GP - 19552                # WorldLoopCounter
G_REPLAY = GP - 22440             # pReplayManager
G_RACECOORD = GP - 22216          # pRaceCoordinator
RACE_PARAMS = 0x0031a898          # TheRaceParameters
G_WO_POOL = GP - 18112            # WorldObjectSlotPool
SCENERY_TABLE = 0x002f8fe8        # ScenerySectionHeaderTable
WORLD_EFFECTS = 0x002ef640

# The blobs.
POOL_H = 0x01000000               # pool k's handle at POOL_H + 16 * k
POOL_MEM = 0x01010000             # its slot i at + 0x4000 * k + 0x100 * i
POOL_SLOTS = 64
MAX_POOLS = 8
MALLOC = 0x01040000               # bMalloc's block k at + 0x1000 * k
MAX_BLOCKS = 8
CHUNK = 0x01050000                # chunk c at + 0x1000 * c
MAX_CHUNKS = 16
LEAF = 0x01070000                 # tree c.j's leaf at + 48 * (4c + j)
EM = 0x01080000                   # emitter i at + 0x100 * i
NUM_EM = 64
MODEL = 0x010a0000                # model i at + 0x20 * i
SOLID = 0x010a1000                # solid i at + 0x100 * i
ANIM = 0x010a2000                 # animation i at + 0x80 * i
SECT = 0x010a3000                 # the j-th section's header at + 0x40 * j
INFO = 0x010a4000                 # its infos at + 0x400 * j
INST = 0x010b0000                 # its instances at + 0x1000 * j
NUM_MODELS, NUM_SOLIDS, NUM_ANIMS, NUM_SECTS = 16, 8, 8, 8
CAR = 0x010c0000                  # car k at + 0x1000 * k
PLAYER = 0x010c4000
VDL_PRE = 0x010c5000              # a line the player already has
REPLAY_MGR = 0x010c6000
RACE_COORD = 0x010c7000
HANDLER_FN = 0x010d0000           # handler k's code at + 0x10 * k
NUM_HANDLERS = 4
VEL = 0x010d1000
AT = 0x010d1010

# Retail's records.
EV_REF, EV_ID, EV_TRIG, EV_CAR, EV_P0 = 8, 12, 16, 20, 24
H_FN, H_MASK, H_REF, H_TIME = 8, 12, 16, 20
FS_CODE, FS_START, FS_INST, FS_WO, FS_INFO = 8, 12, 16, 20, 24
WO_MODEL = 8
C_PLAYER, C_GEOM, C_VEL, C_VMAG = 24, 80, 112, 964
P_VDL, P_WRONG = 228, 760
RP_DIR, RP_TRAINING = 12, 76
PACK_SIZE, TREE_SIZE, TRIGGER_SIZE = 24, 16, 32
SLOT_LABELS = {36: "event", 24: "handler", 28: "fernshaker", 96: "wo"}
BLOCK_LABELS = {48: "fstable"}

CHILD_TYPES = {"h": 0x36001, "H": 0x36001, "t": 0x36002, "a": 0x36003,
               "x": 0x36004, "y": 0x00036000, "z": 0x80036002}


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def bhash(s):
    h = 0xFFFFFFFF
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


def fnv(words):
    h = 0x811c9dc5
    for w in words:
        h = ((h ^ (w & M32)) * 16777619) & M32
    return h


def lw_init(i):
    """Emitter i's LocalWorld before anything places it."""
    return [0.25 * ((i * 7 + k * 3) % 11) - 1.0 for k in range(16)]


IV_INIT = (5.0, 6.0, 7.0, 8.0)


def afx_count(h):
    return 1 + (h & 3) % 3


def align16(o):
    return (o + 8 + 15) & ~15


# ============================================================ the scenarios

HASH_A = bhash("BUSHSHAKE_A")
HASH_B = bhash("BUSHSHAKE_B")
HASH_OTHER = bhash("PALMSWAY")


def hx(v):
    return "%08x" % fb(v)


def tr(eid, param, x, y, z, r):
    return "T %08x %08x %s %s %s %s" % (eid, param, hx(x), hx(y), hx(z),
                                         hx(r))


def te(x, y, z):
    return "TE %s %s %s" % (hx(x), hx(y), hx(z))


def sf(code, vx, vy, vz, pad=9.5):
    return "SF %08x %s %s %s %s" % (code, hx(vx), hx(vy), hx(vz), hx(pad))


def cs(k, pos, vel, vmag, player):
    return "CS %d %s %s %s %d" % (k, " ".join(hx(v) for v in pos),
                                  " ".join(hx(v) for v in vel), hx(vmag),
                                  player)


def s_queue():
    out = ["I"]
    # The handlers: one function twice keeps its first mask; no function and
    # no mask are refused.
    out += ["H 0 00010000", "H 1 00000003", "H 0 00000001", "HN 00000001",
            "H 2 00000000", "H 3 ffffffff"]
    out += ["E 00010003", "E 00010005", "E 00020000", "E 00000004", "P",
            "D"]
    # Locked, an event outlives its pass, and goes after the new ones.
    out += ["E 00000001", "LK 0", "P", "E 00000004", "P", "UL 0", "P"]
    out += ["AC 1 lock", "E 00000001", "E 00000002", "P", "AC 1", "P",
            "UL 0", "UL 1", "P"]
    # Locked twice, unlocked once: still kept. Removed while locked.
    out += ["E 00010000", "LK 0", "LK 0", "UL 0", "P", "X 0", "P"]
    # Unlocked below 0: kept, until locked back to 0.
    out += ["E 00000001", "UL 0", "P", "LK 0", "P"]
    # Added while handling: onto the pass's own queue, handled next pass,
    # after the locked.
    out += ["AC 0 add:00010001 add:00000008", "E 00010000", "E 00000001",
            "LK 1", "P", "AC 0", "UL 1", "P", "P"]
    # Removing the event being handled does nothing; removing a later one
    # (not the next, which the walk has already read) takes it out.
    out += ["AC 3 rm:self", "E 00000008", "P", "AC 3"]
    out += ["E 00000002", "E 00000002", "E 00000002", "E 00000002",
            "AC 1 once:rm:2", "P", "AC 1"]
    # A handler takes itself off, or adds one, while the event is handled;
    # the walk reads the next handler after the call.
    out += ["AC 3 rmh:3", "E 00000008", "P", "AC 3", "E 00000008", "P"]
    out += ["AC 1 once:addh:2:00000002", "E 00000002", "P", "AC 1",
            "E 00000002", "P"]
    out += ["AC 2 once:rmh:2 once:rmh:1 once:lock", "E 00000002",
            "E 00000001", "P", "AC 2", "P", "UL 0", "P"]
    # The handlers off, one at a time; ones not there.
    out += ["R 0", "R 0", "R 0", "R 2", "R 3", "R 1", "R 1"]
    out += ["H 3 00000006", "H 3 00000001", "H 1 80000000"]
    # The event pool runs out at 60.
    out += ["E 40000000"] * 61
    out += ["P", "E 40000000", "E 40000000", "X 0", "X 1", "P"]
    # An id of 0 matches nothing.
    out += ["E 00000000", "P"]
    # Closed and made again; the handlers stay on their list.
    out += ["IX", "I", "E 00000006", "P"]
    # A handler removes the next event, which the walk has read already:
    # the walk goes on through the freed event, and the queue is left
    # naming freed ones, as the image leaves it. Nothing runs after it.
    out += ["E 00000002", "E 00000002", "E 00000002", "AC 3 once:rm:1",
            "P", "AC 3"]
    return out

def chunk_triggers(n, x, y, z, r, eid=0x10001, base=0):
    return [tr(eid, base + i, x + i, y, z, r) for i in range(n)]


def s_triggers():
    out = ["I", "H 0 ffffffff"]
    # c0: six triggers, a tree and the array: linked.
    out += [tr(0x10001, 0x100, 10.0, 0.0, 0.0, 2.0),
            tr(0x10002, 0x101, 11.0, 0.0, 0.0, 2.0),
            tr(0x10003, 0x102, 30.0, 0.0, 0.0, 2.0),
            tr(0x10004, 0x103, 10.0, 1.5, 0.0, 2.0),
            tr(0x00008, 0x104, 10.0, 0.0, -1.0, 1.0),
            tr(0x10005, 0x105, 10.0, 0.0, 1.9, 1.0),
            "K 1 6 hta"]
    # c1: the array and the tree before the header: neither taken, and the
    # header alone goes on the empty list.
    out += chunk_triggers(3, 0.0, 0.0, 0.0, 5.0) + ["K 1 3 ath"]
    # c2: version 2 -- nothing linked, 1 returned.
    out += chunk_triggers(1, 0.0, 0.0, 0.0, 5.0) + ["K 2 1 hta"]
    # c3: no triggers counted; c4: no array.
    out += chunk_triggers(2, 0.0, 0.0, 0.0, 5.0) + ["K 1 0 hta"]
    out += ["K 1 2 ht"]
    # c5: children nobody takes, skipped.
    out += [tr(0x10001, 0x500, 10.0, 0.0, 0.0, 3.0),
            tr(0x10006, 0x501, 9.0, 0.0, 0.0, 3.0), "K 1 2 hxtya"]
    # c6: two headers; the second has the tree and the array.
    out += [tr(0x10007, 0x600, 10.0, 0.0, 0.0, 0.5), "K 1 1 hHta"]
    # Not the event manager's: 0 from both.
    out += ["KN", "K0"]
    # The leaves: c0's tree answers three of its six.
    out += ["Q 0.0 3 0 2 5", te(10.0, 0.0, 1.0)]
    out += ["Q 0.0 6 0 1 2 3 4 5", te(10.0, 0.0, 0.0), "P"]
    out += [te(11.5, 0.5, 0.25), te(10.0, 2.0, 0.0), te(-10.0, 0.0, 0.0),
            "P"]
    # c5's and c6's leaves; c5's second tree is its only one.
    out += ["Q 5.0 2 1 0", "Q 6.0 1 0", te(10.0, 0.0, 0.0), "P"]
    # A distance of exactly the radius is outside; a NaN is outside.
    out += ["Q 0.0 1 0", te(12.0, 0.0, 0.0), te(8.0, 0.0, 0.0),
            te(10.0, 2.0, 0.0), te(0x7fc00000, 0.0, 0.0),
            te(10.0, 0x7fc00000, 0.0), te(11.999999, 0.0, 0.0), "P"]
    # No leaf, and a parent (a count above 0).
    out += ["Q 0.0 none", te(10.0, 0.0, 0.0), "Q 0.0 parent",
            te(10.0, 0.0, 0.0), "P"]
    # Five packs of ten: the forty-slot cap, and then the event pool runs
    # out under it.
    for c in range(5):
        out += chunk_triggers(10, 100.0, 0.0, 0.0, 50.0, base=0x1000 * c)
        out += ["K 1 10 hta"]
    for c in range(9, 14):
        out += ["Q %d.0 10 0 1 2 3 4 5 6 7 8 9" % c]
    out += [te(100.0, 0.0, 0.0), te(104.0, 0.0, 0.0), "P",
            te(100.0, 0.0, 0.0), "P"]
    # The cap inside a leaf: 5 + 10 + 10 + 10, then c13's leaf stops
    # after its fifth.
    out += ["Q 9.0 5 0 1 2 3 4", te(100.0, 0.0, 0.0), "P"]
    # A sphere whose edge the sum's order decides: (1 + s) + s rounds to
    # 1 + 2 ulps, not inside a radius squared of 1 + 2 ulps, where
    # 1 + (s + s) would be. Then a pack with triggers and no tree.
    out += [tr(0x10009, 0x999, 10.0, 0.0, 0.0, 0x3f800001), "K 1 1 hta",
            "Q 14.0 1 0", te(11.0, 0x39807358, 0x39807358), "P"]
    out += chunk_triggers(1, 0.0, 0.0, 0.0, 5.0) + ["K 1 1 ha"]
    # Unloaded: c0 off the list, c3 off the empty one, c2 never on one;
    # then c9 and c11, and the walk again. Not the event manager's (c7),
    # and an empty one (c8).
    out += ["U 0", "U 3", "U 2", "U 9", "U 11", te(100.0, 0.0, 0.0), "P"]
    out += ["U 7", "U 8"]
    return out


INST_ROT = [
    [16384, 0, 0, 0, 16384, 0, 0, 0, 16384],
    [0, 16384, 0, -16384, 0, 0, 0, 0, 16384],
    [11585, 0, -11585, 0, 16384, 0, 11585, 0, 11585],
    [-16384, 0, 0, 0, -16384, 0, 0, 0, 16384],
    [8192, 14189, 0, -14189, 8192, 0, 0, 0, 16384],
    [16384, 0, 0, 0, 0, 16384, 0, -16384, 0],
    [1, -2, 3, -4, 5, -6, 7, -8, 9],
    [-32768, 32767, 0, 100, -100, 200, 0, 0, 1],
]


def fn_op(sec, inst, info, x, y, z, rot, excl):
    return "FN %d %d %d %s %s %s %s %04x" % (
        sec, inst, info, hx(x), hx(y), hx(z), " ".join(str(r) for r in rot),
        excl)


def scenery():
    out = ["FA 0 40 2 %08x" % HASH_A, "FA 1 31 1 %08x" % HASH_B,
           "FA 2 20 255 %08x" % HASH_OTHER, "FA 3 0 1 %08x" % HASH_A,
           "FA 4 65535 3 %08x" % HASH_B]
    out += ["FS 0 0", "FS 1 1", "FS 2 2", "FS 3 -1", "FS 4 3", "FS 5 4"]
    out += ["FM 0 %08x 0 0" % bhash("BUSH_A_01"),
            "FM 1 %08x 1 0" % bhash("BUSH_B_01"),
            "FM 2 %08x 2 0" % bhash("PALM_01"),
            "FM 3 %08x 3 0" % bhash("ROCK_01"),
            "FM 4 %08x -1 0" % bhash("GHOST_01"),
            "FM 5 %08x 0 0" % bhash("BUSH_A_01"),
            "FM 6 %08x 5 0" % bhash("BUSH_B_02"),
            "FM 7 %08x 4 0" % bhash("BUSH_A_00")]
    out += ["FH 5 8 8"]
    for info, model in enumerate([0, 1, 2, 3, 4, -1, 6, 7]):
        out.append("FI 5 %d %d" % (info, model))
    for i in range(8):
        out.append(fn_op(5, i, i, 100.0 + i, -2.5 * i, 0.125 * i,
                         INST_ROT[i], [0, 0x10, 0x400, 0xffef, 0, 0, 1, 0][i]))
    # A section of forty of the same bush, for the pool's limit.
    out += ["FH 6 1 40", "FI 6 0 0"]
    for i in range(40):
        out.append(fn_op(6, i, 0, 3.0 * i, 1.0, 2.0, INST_ROT[i % 8], 0))
    # A section with no instances.
    out += ["FH 7 1 0", "FI 7 0 0"]
    return out


def s_ferns():
    out = ["I", "WT 1000", "WL 100000"] + scenery() + ["F"]
    code = lambda s, i: (s << 16) | i
    # Too slow: a shaker, the bush hidden, no animation started.
    out += [sf(code(5, 0), 1.0, 1.5, 0.5)]
    # Exactly 5 mph: still too slow.
    out += [sf(code(5, 0), 0x400f7f6d, 0.0, 0.0)]
    # Fast enough: the animation starts at frame 0 and the leaves fly.
    out += [sf(code(5, 0), 3.0, 0.0, 0.0), sf(code(5, 0), 5.0, 2.0, -1.0)]
    # The order of the sum shows in the shake's last bit.
    out += [sf(code(5, 0), 0x3f840b33, 0x40bdad05, 0x40b9098e)]
    # Over 30 mph: the middle frame, and the shake held at 1.
    out += [sf(code(5, 1), 20.0, 0.0, 0.0), "WT 1010",
            sf(code(5, 1), 0.0, -14.0, 1.0)]
    # Another bush's animation and none's; no solid; no model; a section
    # with no instances, and one not loaded.
    out += [sf(code(5, 2), 10.0, 0.0, 0.0), sf(code(5, 3), 10.0, 0.0, 0.0),
            sf(code(5, 4), 10.0, 0.0, 0.0), sf(code(5, 5), 10.0, 0.0, 0.0),
            sf(code(7, 0), 10.0, 0.0, 0.0), sf(code(9, 0), 10.0, 0.0, 0.0),
            sf(code(5, 6), 15.0, 7.0, 7.0), sf(code(5, 7), 0.0, 0.0, 30.0)]
    # The animation runs out and starts again.
    for t in (1020, 1080, 1081, 1082, 1100, 1200, 1239, 1240, 1241, 1242):
        out += ["WT %d" % t, sf(code(5, 0), 4.0, 0.0, 0.0),
                sf(code(5, 1), 14.0, 0.0, 0.0)]
    # The shakers age out at 241 frames, at the next ShakeFern: those made
    # at 1010 go at 1300, and the one made again then at 1541, not 1540.
    out += ["WT 1300", sf(code(5, 6), 0.0, 0.0, 0.0), "WT 1540",
            sf(code(5, 7), 0.0, 0.0, 0.0), "WT 1541",
            sf(code(5, 7), 0.0, 0.0, 0.0), "WT 9999",
            sf(code(5, 0), 0.0, 0.0, 0.0)]
    # The clock wraps; the age is signed.
    out += ["WT 2147483600", sf(code(5, 0), 3.0, 0.0, 0.0),
            sf(code(5, 1), 3.0, 0.0, 0.0), "WT -2147483600",
            sf(code(5, 2), 3.0, 0.0, 0.0), "WT 2147483000",
            sf(code(5, 2), 3.0, 0.0, 0.0)]
    # The pool's 32: the thirty-third does nothing.
    out += ["WT 20000", "FF"]
    for i in range(34):
        out.append(sf(code(6, i), 3.0 + i, 0.0, 0.0))
    out += [sf(code(6, 3), 30.0, 0.0, 0.0), "WT 20241",
            sf(code(6, 39), 3.0, 0.0, 0.0), sf(code(6, 38), 3.0, 0.0, 0.0)]
    # Flushed, closed with shakers out, made again, closed twice.
    out += ["FF", sf(code(5, 0), 3.0, 0.0, 0.0), sf(code(5, 1), 3.0, 0.0, 0.0),
            "FX", "F", sf(code(5, 0), 3.0, 0.0, 0.0), "FX", "FX", "F",
            "FL 00050000"]
    # The timing alone.
    for m, start in ((0, 0), (0, 0x8000 | 990), (0, 0xc000 | 990),
                     (0, 0x4000 | 990), (1, 0xc000 | 100), (2, 0x8000 | 995),
                     (2, 0xc000 | 995), (6, 0xc000 | 1),
                     (7, 0x8000 | 1000), (7, 0x8000), (0, 0xffff),
                     (6, 0x8000 | 990)):
        for t in (1000, 1012, 1039, 1040, 1041, 17383, 17385, -5):
            out += ["MS %d %04x" % (m, start), "WT %d" % t, "GT %d" % m]
    # A start of 0 when the clock's low 14 bits fall inside model 0's 80
    # frames: still not playing.
    for t in (5, 79, 80, 16390):
        out += ["MS 0 0000", "WT %d" % t, "GT 0"]
    for m in (0, 3, 4, 7):
        out.append("GA %d" % m)
    for t, frame in ((1000, 0), (1000, 7), (1000, 600), (5, 10),
                     (16384, -3), (-1, 8191), (99, 0x40000001)):
        out += ["WT %d" % t, "SN 1 %d" % frame, "GT 1"]
    return out


def s_cars():
    out = ["I", "WT 3000", "WL 100001", "H 0 ffffffff"] + scenery() + ["F"]
    code = lambda s, i: (s << 16) | i
    line = lambda ln, secs, d: (ln << 16) | (secs << 8) | d
    # The car's triggers: bushes, lines either way, and others.
    out += [tr(0x10003, code(5, 0), 0.0, 0.0, 0.0, 5.0),
            tr(0x10003, code(5, 1), 2.0, 0.0, 0.0, 5.0),
            tr(0x10005, line(3, 4, 0), 0.0, 0.0, 0.0, 5.0),
            tr(0x10005, line(9, 0, 1), 0.0, 0.0, 0.0, 5.0),
            tr(0x10005, line(0xffff, 255, 2), 0.0, 0.0, 0.0, 5.0),
            tr(0x10001, 0x77, 0.0, 0.0, 0.0, 5.0),
            tr(0x00004, 0x78, 0.0, 0.0, 0.0, 5.0),
            tr(0x10003, code(5, 6), 0.0, 0.0, 0.0, 5.0),
            tr(0x10005, line(1, 0, 0), 0.0, 0.0, 0.0, 5.0),
            tr(0x10003, code(6, 5), 0.0, 0.0, 0.0, 5.0),
            "K 1 10 hta"]
    out += ["PL 0 0", "RP 0 0", "RC 3"]
    # Nothing hit: the point is 0.15 s ahead of GeometryPosition.
    out += ["Q 0.0 2 0 1",
            cs(0, (40.0, 0.0, 0.0, 77.0), (10.0, 0.0, 0.0, 66.0), 10.0, 1),
            "CT 0", "P"]
    out += [cs(0, (-1.5, 0.0, 0.0, 77.0), (10.0, 0.0, 0.0, 66.0), 10.0, 1),
            "CT 0", "P"]
    # Two bushes: shaken, and the replay told every fourth loop over 30.
    for wl, vmag in ((100001, 31.0), (100002, 31.0), (100003, 31.0),
                     (100004, 31.0), (100005, 30.0), (100005, 0x7fc00000),
                     (-3, 45.0), (1, 45.0)):
        out += ["WL %d" % wl,
                cs(0, (-1.5, 0.5, 0.25, 0.0), (10.0, -2.0, 3.0, 0.5), vmag, 1),
                "CT 0", "P"]
    # No player: shaken, nothing told.
    out += ["WL 100001", cs(0, (-1.5, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 0.0),
                            50.0, 0), "CT 0", "P"]
    # The others: removed at once, never handled.
    out += ["Q 0.0 2 5 6", cs(1, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0),
                               99.0, 1), "CT 1", "P"]
    # The driving lines: the race's direction, over 40, not the wrong way;
    # the training lines off, so nothing yet.
    out += ["Q 0.0 4 2 4 3 8"]
    out += [cs(1, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), 41.0, 1),
            "CT 1", "P"]
    out += ["RP 0 1", "RC 2", "CT 1", "P", "RC 3"]
    for d in (0, 1, 2, -1):
        out += ["RP %d 1" % d, "CT 1", "P", "PL 0 0"]
    out += ["RP 0 1", "PL 1 0", "CT 1", "P", "PL 0 1", "CT 1", "P",
            "PL 0 0"]
    out += [cs(1, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), 40.0, 1),
            "CT 1", "P",
            cs(1, (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), 40.001, 0),
            "CT 1", "P"]
    # The line by itself: 5 s for 0, none twice.
    out += ["PL 0 0", "VD 7 00000000", "VD 8 3f800000", "PL 0 0",
            "VD 8 bf800000", "PL 0 0", "RC 1", "VD 9 40000000", "RC 3",
            "RP 0 0", "VD 9 40000000", "RP 0 1", "VD 9 80000000"]
    # Everything at once, with the event pool nearly out.
    out += ["PL 0 0", "Q 0.0 10 0 1 2 3 4 5 6 7 8 9"]
    out += ["E 40000000"] * 52
    out += [cs(0, (-1.5, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 1.0), 45.0, 1),
            "WL 100005", "CT 0", "P"]
    out += [cs(0, (-1.5, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 1.0), 45.0, 1),
            "CT 0", "CT 0", "P"]
    # No player: the bushes still shake, and a line stops nothing.
    out += [cs(0, (-1.5, 0.0, 0.0, 0.0), (10.0, 0.0, 0.0, 1.0), 45.0, 0),
            "CT 0", "P", "FX"]
    return out


def script():
    return [s_queue(), s_triggers(), s_ferns(), s_cars()]


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        e = self.e
        e.stub(BNEWSLOTPOOL, self.st_newpool)
        e.stub(BDELETESLOTPOOL, self.st_delpool)
        e.stub(BMALLOC_POOL, lambda em: self.st_alloc("m"))
        e.stub(BOMALLOC, lambda em: self.st_alloc("o"))
        e.stub(BFREE_POOL, self.st_free_slot)
        e.stub(BISFULL, self.st_isfull)
        e.stub(BMALLOC, self.st_malloc)
        e.stub(BFREE, self.st_free)
        e.stub(TICKER, self.st_ticker)
        e.stub(TICKDIFF, self.st_tickdiff)
        e.stub(QUERY_LEAF, self.st_query)
        e.stub(WO_CTOR, self.st_wo_ctor)
        e.stub(WO_DTOR, self.st_wo_dtor)
        e.stub(AFX, self.st_afx)
        e.stub(TRIG_EMITTER, self.st_trigger)
        e.stub(EMITTER_DELETE, self.st_emdel)
        e.stub(INTERESTING, self.st_interesting)
        e.stub(VDL_CTOR, self.st_vdl)
        for k in range(NUM_HANDLERS):
            e.stub(HANDLER_FN + 0x10 * k,
                   (lambda kk: (lambda em: self.st_handler(kk)))(k))
        self.out = []
        self.reset()

    # ---- state -----------------------------------------------------------

    def reset(self):
        e = self.e
        e.write(0x01000000, bytes(0x00d2000))
        self.pools = []
        self.nblocks = 0
        self.nchunks = 0
        self.ticks = 0
        self.nem = 0
        self.actions = [[] for _ in range(NUM_HANDLERS)]
        self.chunks = []            # per chunk: (base, packs, trees, arrays)
        self.models = {}            # model index -> name hash
        self.sects = {}             # section number -> j
        self.ninst = {}             # section number -> instances
        self.defined_inst = []      # (sec, inst) in the order defined
        e.call(EM_SINIT, limit=1000)
        for g in (G_EVENT_POOL, G_HANDLER_POOL, G_CURRENT, G_FS_TABLE,
                  G_FS_COUNT, G_FS_POOL, G_WTF, G_WLC):
            e.put32(g, 0)
        e.put32(G_CURQ, G_MASTER)
        e.write(STATS, bytes(20))
        e.write(TRIGGER_ARRAY, bytes(4 * NUM_TRIGGER_SLOTS))
        e.put32(G_FS_LIST, G_FS_LIST)
        e.put32(G_FS_LIST + 4, G_FS_LIST)
        e.write(SCENERY_TABLE, bytes(4 * 300))
        e.write(RACE_PARAMS, bytes(80))
        e.put32(G_REPLAY, REPLAY_MGR)
        e.put32(G_RACECOORD, RACE_COORD)
        e.put32(G_WO_POOL, self.newpool(96, 40, "WorldObjects", 0))
        for i in range(NUM_EM):
            self.init_emitter(i)

    def emit(self, s):
        self.out.append(s)

    def arg(self, i):
        return self.e.reg[(4, 5, 6, 7, 8)[i]] & M32

    def w(self, a):
        return self.e.u32(a)

    def h16(self, a):
        return self.e.u16(a)

    def put16(self, a, v):
        self.e.write(a, struct.pack("<H", v & 0xffff))

    def cstr(self, a):
        s = bytearray()
        while True:
            b = self.e.u8(a + len(s))
            if b == 0:
                return s.decode("latin-1")
            s.append(b)

    def init_emitter(self, i):
        a = EM + 0x100 * i
        for k, v in enumerate(lw_init(i)):
            self.e.put32(a + 48 + 4 * k, fb(v))
        for k, v in enumerate(IV_INIT):
            self.e.put32(a + 112 + 4 * k, fb(v))

    def nested(self, addr, *args):
        e = self.e
        saved = (list(e.reg), list(e.fpr))
        e.call(addr, *args, limit=LIMIT)
        v = e.reg[2] & M32
        e.reg[:] = saved[0]
        e.fpr[:] = saved[1]
        return v

    # ---- labels ----------------------------------------------------------

    def pool_of(self, h):
        if h == 0:
            return None
        return (h - POOL_H) // 16

    def pool_label(self, h):
        if h == 0:
            return "NULL"
        return "pool%d" % self.pool_of(h)

    def slot_of(self, a):
        if POOL_MEM <= a < POOL_MEM + 0x4000 * MAX_POOLS:
            k, i = divmod(a - POOL_MEM, 0x4000)
            if i % 0x100 == 0:
                return k, i // 0x100
        return None

    def label(self, a):
        a &= M32
        if a == 0:
            return "NULL"
        s = self.slot_of(a)
        if s is not None:
            name = self.pools[s[0]]["name"]
            return "%s%d" % ({"EventSlotPool": "e", "EventHandlerSlotPool": "hs",
                              "FernShakerSlotPool": "fs",
                              "WorldObjects": "wo"}.get(name, "?"), s[1])
        if HANDLER_FN <= a < HANDLER_FN + 0x10 * NUM_HANDLERS:
            return "h%d" % ((a - HANDLER_FN) // 0x10)
        table = self.w(G_FS_TABLE)
        if table and table <= a < table + 16 * 4 and (a - table) % 16 == 0:
            return "fi%d" % ((a - table) // 16)
        if MALLOC <= a < MALLOC + 0x1000 * MAX_BLOCKS:
            k, o = divmod(a - MALLOC, 0x1000)
            return "blk%d+%d" % (k, o)
        for c, ch in enumerate(self.chunks):
            for kind, recs in (("p", ch["packs"]), ("t", ch["trees"])):
                for j, r in enumerate(recs):
                    if a == r:
                        return "c%d.%s%d" % (c, kind, j)
            for j, (r, n) in enumerate(ch["arrays"]):
                if r <= a < r + TRIGGER_SIZE * max(n, 1) and \
                        (a - r) % TRIGGER_SIZE == 0:
                    return "c%d.a%d.t%d" % (c, j, (a - r) // TRIGGER_SIZE)
        if EM <= a < EM + 0x100 * NUM_EM and (a - EM) % 0x100 == 0:
            return "em%d" % ((a - EM) // 0x100)
        if MODEL <= a < MODEL + 0x20 * NUM_MODELS:
            return "m%d" % ((a - MODEL) // 0x20)
        if ANIM <= a < ANIM + 0x80 * NUM_ANIMS:
            return "an%d" % ((a - ANIM) // 0x80)
        for sec, j in self.sects.items():
            base = INST + 0x1000 * j
            if base <= a < base + 0x1000 and (a - base) % 48 == 0:
                return "s%d.%d" % (sec, (a - base) // 48)
        if a == CAR or a == CAR + 0x1000:
            return "car%d" % ((a - CAR) // 0x1000)
        if a == PLAYER:
            return "player"
        if a == VDL_PRE:
            return "oldline"
        if a == REPLAY_MGR:
            return "replay"
        if a == WORLD_EFFECTS:
            return "world"
        return "?%08x" % a

    # ---- the pools -------------------------------------------------------

    def newpool(self, size, n, name, mem):
        k = len(self.pools)
        if k >= MAX_POOLS or n > POOL_SLOTS:
            raise SystemExit("pool table full")
        self.pools.append({"size": size, "n": n, "name": name,
                           "used": [False] * n, "dead": False})
        self.emit("newpool pool%d name=%s n=%d size=%s mem=%d" % (
            k, name, n, SLOT_LABELS.get(size, "%d" % size), mem))
        return POOL_H + 16 * k

    def st_newpool(self, em):
        return self.newpool(s32(self.arg(0)), s32(self.arg(1)),
                            self.cstr(self.arg(2)), s32(self.arg(3)))

    def st_delpool(self, em):
        h = self.arg(0)
        self.emit("delpool %s" % self.pool_label(h))
        if h:
            p = self.pools[self.pool_of(h)]
            p["dead"] = True
            p["used"] = [False] * p["n"]

    def alloc(self, h, how):
        k = self.pool_of(h)
        p = self.pools[k]
        for i in range(p["n"]):
            if not p["used"][i]:
                p["used"][i] = True
                a = POOL_MEM + 0x4000 * k + 0x100 * i
                self.e.write(a, b"\xcd" * p["size"])
                self.emit("alloc%s pool%d slot=%d" % (how, k, i))
                return a
        self.emit("alloc%s pool%d full" % (how, k))
        return 0

    def st_alloc(self, how):
        return self.alloc(self.arg(0), how)

    def free_slot(self, h, a, quiet=False):
        k = self.pool_of(h)
        s = self.slot_of(a)
        if not quiet:
            self.emit("free %s %s" % (self.pool_label(h), self.label(a)))
        if s is not None and s[0] == k:
            self.pools[k]["used"][s[1]] = False

    def st_free_slot(self, em):
        self.free_slot(self.arg(0), self.arg(1))

    def st_isfull(self, em):
        p = self.pools[self.pool_of(self.arg(0))]
        return 1 if all(p["used"]) else 0

    def st_malloc(self, em):
        size = s32(self.arg(0))
        k = self.nblocks
        self.nblocks += 1
        self.emit("bMalloc size=%s name=%s flags=%d pool=%d -> blk%d" % (
            BLOCK_LABELS.get(size, "%d" % size), self.cstr(self.arg(1)),
            s32(self.arg(2)), s32(self.arg(3)), k))
        a = MALLOC + 0x1000 * k
        self.e.write(a, b"\xab" * size)
        return a

    def st_free(self, em):
        self.emit("bFree %s" % self.label(self.arg(0)))

    # ---- the clock -------------------------------------------------------

    def st_ticker(self, em):
        self.ticks = (self.ticks + 1024 * (1 + self.ticks // 1024 % 3)) & M32
        return self.ticks

    def st_tickdiff(self, em):
        d = (self.arg(1) - self.arg(0)) & M32
        self.e.fpr[0] = fb(float(d // 1024))

    # ---- the tree --------------------------------------------------------

    def st_query(self, em):
        t = self.arg(0)
        lab = self.label(t)
        na = "ok" if self.w(t) == t + TREE_SIZE else "bad"
        self.emit("query %s x=%08x y=%08x z=%08x na=%s" % (
            lab, self.e.fpr[12] & M32, self.e.fpr[13] & M32,
            self.e.fpr[14] & M32, na))
        for c, ch in enumerate(self.chunks):
            for j, r in enumerate(ch["trees"]):
                if r == t:
                    spec = ch["leaf"].get(j)
                    if spec is None:
                        return 0
                    return LEAF + 48 * (4 * c + j)
        return 0

    # ---- the world objects and the effects -------------------------------

    def st_wo_ctor(self, em):
        o, h, m, light = self.arg(0), self.arg(1), self.arg(2), self.arg(3)
        self.emit("wo new %s hash=%08x light=%d m=%s" % (
            self.label(o), h, light,
            " ".join("%08x" % self.w(m + 4 * k) for k in range(16))))
        model = 0
        for i in sorted(self.models):
            if self.models[i] == h:
                model = MODEL + 0x20 * i
                break
        if o:
            self.e.put32(o + WO_MODEL, model)
        return o

    def st_wo_dtor(self, em):
        o, flags = self.arg(0), s32(self.arg(1))
        self.emit("wo delete %s flags=%d" % (self.label(o), flags))
        if flags & 1:
            self.free_slot(self.w(G_WO_POOL), o, quiet=True)

    def st_afx(self, em):
        lst, h = self.arg(0), self.arg(1)
        n = afx_count(h)
        self.emit("afx list=%s hash=%08x n=%d" % (self.label(lst - 8), h, n))
        for _ in range(n):
            i = self.nem
            self.nem += 1
            a = EM + 0x100 * i
            prev = self.w(lst + 4)
            self.e.put32(a, lst)
            self.e.put32(a + 4, prev)
            self.e.put32(prev, a)
            self.e.put32(lst + 4, a)

    def st_trigger(self, em):
        a = self.arg(1)
        self.emit("trigger sys=%s e=%s step=%08x car=%s lw=%s iv=%s" % (
            self.label(self.arg(0)), self.label(a), self.e.fpr[12] & M32,
            self.label(self.arg(2)),
            " ".join("%08x" % self.w(a + 48 + 4 * k) for k in range(16)),
            " ".join("%08x" % self.w(a + 112 + 4 * k) for k in range(4))))

    def st_emdel(self, em):
        self.emit("emitter delete %s flags=%d" % (self.label(self.arg(0)),
                                                  s32(self.arg(1))))

    def st_interesting(self, em):
        self.emit("interesting rm=%s value=%08x what=%s" % (
            self.label(self.arg(0)), self.e.fpr[12] & M32,
            self.cstr(self.arg(1))))

    def st_vdl(self, em):
        self.emit("vdl new mem=%s player=%s line=%d secs=%08x" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            s32(self.arg(2)), self.e.fpr[12] & M32))
        return self.arg(0)

    # ---- the handlers ----------------------------------------------------

    def st_handler(self, k):
        ev = self.arg(0)
        self.emit("handler h%d ev=%s id=%08x" % (k, self.label(ev),
                                                 self.w(ev + EV_ID)))
        for act in list(self.actions[k]):
            if act.startswith("once:"):
                self.actions[k].remove(act)
                act = act[5:]
            f = act.split(":")
            if f[0] == "lock":
                self.nested(EM_LOCK, ev)
            elif f[0] == "unlock":
                self.nested(EM_UNLOCK, ev)
            elif f[0] == "add":
                v = self.nested(EM_ADD_EVENT, int(f[1], 16))
                self.emit("  added %s" % self.label(v))
            elif f[0] == "rm":
                a = ev if f[1] == "self" else self.event_addr(int(f[1]))
                self.nested(EM_REMOVE_EVENT, a)
            elif f[0] == "rmh":
                self.nested(EM_REMOVE_HANDLER, HANDLER_FN + 0x10 * int(f[1]))
            elif f[0] == "addh":
                v = self.nested(EM_ADD_HANDLER, HANDLER_FN + 0x10 * int(f[1]),
                                int(f[2], 16))
                self.emit("  addh -> %d" % s32(v))
            else:
                raise SystemExit("bad action %r" % act)

    def event_addr(self, slot):
        h = self.w(G_EVENT_POOL)
        return POOL_MEM + 0x4000 * self.pool_of(h) + 0x100 * slot

    # ---- the chunks ------------------------------------------------------

    def build_chunk(self, version, ntrig, order, triggers):
        c = self.nchunks
        self.nchunks += 1
        base = CHUNK + 0x1000 * c
        e = self.e
        e.write(base, bytes(0x1000))
        ch = {"base": base, "packs": [], "trees": [], "arrays": [],
              "leaf": {}}
        o = 8
        for k in order:
            t = CHILD_TYPES[k]
            r = align16(o)
            if k in "hH":
                rec = struct.pack("<IIiiII", 0, 0, version if k == "h" else 1,
                                  ntrig, 0, 0)
                ch["packs"].append(base + r)
            elif k == "t":
                rec = bytes(TREE_SIZE) + bytes(48)
                ch["trees"].append(base + r)
            elif k == "a":
                rec = b"".join(triggers)
                ch["arrays"].append((base + r, len(triggers)))
            else:
                rec = b"\x5a" * 8
            e.put32(base + o, t)
            e.put32(base + o + 4, r - (o + 8) + len(rec))
            e.write(base + r, rec)
            o = r + len(rec)
        e.put32(base, 0x80036000)
        e.put32(base + 4, o - 8)
        self.chunks.append(ch)
        return base

    # ---- the dump --------------------------------------------------------

    def walk(self, head, cap=80):
        out = []
        n = self.w(head)
        while n != head and len(out) < cap:
            out.append(n)
            n = self.w(n)
        return out

    def dump(self):
        e = self.e
        st = [s32(self.w(STATS + 4 * k)) for k in range(5)]
        cq = self.w(G_CURQ)
        self.emit("  st ne=%d nh=%d ppt=%08x hwq=%d hwh=%d cq=%s cur=%s "
                  "pools=%s,%s" % (
                      st[0], st[1], self.w(STATS + 8), st[3], st[4],
                      "master" if cq == G_MASTER else "?%08x" % cq,
                      self.label(self.w(G_CURRENT)),
                      self.pool_label(self.w(G_EVENT_POOL)),
                      self.pool_label(self.w(G_HANDLER_POOL))))
        hs = []
        for h in self.walk(G_HANDLERS):
            hs.append("%s:%s/%08x/%d/%08x" % (
                self.label(h), self.label(self.w(h + H_FN)),
                self.w(h + H_MASK), s32(self.w(h + H_REF)),
                self.w(h + H_TIME)))
        self.emit("  hl " + " ".join(hs))
        evs = []
        for ev in self.walk(G_MASTER):
            evs.append("%s/%08x/%d/%s/%s/%08x/%08x/%08x" % (
                self.label(ev), self.w(ev + EV_ID), s32(self.w(ev + EV_REF)),
                self.label(self.w(ev + EV_TRIG)),
                self.label(self.w(ev + EV_CAR)), self.w(ev + EV_P0),
                self.w(ev + EV_P0 + 4), self.w(ev + EV_P0 + 8)))
        self.emit("  mq " + " ".join(evs))
        self.emit("  pk %s | %s" % (
            " ".join(self.label(p) for p in self.walk(G_PACKS)),
            " ".join(self.label(p) for p in self.walk(G_EMPTY_PACKS))))
        fs = []
        for s in self.walk(G_FS_LIST):
            fs.append("%s/%08x/%d/%s/%s/%s" % (
                self.label(s), self.w(s + FS_CODE), s32(self.w(s + FS_START)),
                self.label(self.w(s + FS_INST)), self.label(self.w(s + FS_WO)),
                self.label(self.w(s + FS_INFO))))
        table = self.w(G_FS_TABLE)
        n = s32(self.w(G_FS_COUNT))
        self.emit("  fs pool=%s n=%d table=%s %s" % (
            self.pool_label(self.w(G_FS_POOL)), n, self.label(table),
            " ".join(fs)))
        if table and 0 < n <= 4:
            fi = []
            for i in range(n):
                a = table + 16 * i
                fi.append("%08x/%08x/[%s]" % (
                    self.w(a), self.w(a + 4),
                    " ".join(self.label(x) for x in self.walk(a + 8))))
            self.emit("  fi " + " ".join(fi))
        fx = []
        for sec, i in self.defined_inst:
            a = INST + 0x1000 * self.sects[sec] + 48 * i
            fx.append("%x" % self.h16(a + 14))
        for i in sorted(self.models):
            fx.append("m%d=%04x" % (i, self.h16(MODEL + 0x20 * i + 22)))
        self.emit("  fx " + " ".join(fx))
        words = []
        for i in range(self.nem):
            a = EM + 0x100 * i
            words += [self.w(a + 48 + 4 * k) for k in range(16)]
            words += [self.w(a + 112 + 4 * k) for k in range(4)]
        self.emit("  em %d %08x" % (self.nem, fnv(words)))

    # ---- the ops ---------------------------------------------------------

    def op(self, t):
        e = self.e
        c = t[0]
        if c == "Z":
            self.reset()
        elif c == "I":
            e.call(EM_INIT, limit=LIMIT)
        elif c == "IX":
            e.call(EM_CLOSE, limit=LIMIT)
        elif c == "H":
            r = e.call(EM_ADD_HANDLER, HANDLER_FN + 0x10 * int(t[1]),
                       int(t[2], 16), limit=LIMIT)
            self.emit("add handler -> %d" % r)
        elif c == "HN":
            r = e.call(EM_ADD_HANDLER, 0, int(t[1], 16), limit=LIMIT)
            self.emit("add handler -> %d" % r)
        elif c == "R":
            e.call(EM_REMOVE_HANDLER, HANDLER_FN + 0x10 * int(t[1]),
                   limit=LIMIT)
        elif c == "E":
            r = e.call(EM_ADD_EVENT, int(t[1], 16), limit=LIMIT)
            self.emit("add event -> %s" % self.label(r))
        elif c == "X":
            e.call(EM_REMOVE_EVENT, self.event_addr(int(t[1])), limit=LIMIT)
        elif c == "LK":
            e.call(EM_LOCK, self.event_addr(int(t[1])), limit=LIMIT)
        elif c == "UL":
            e.call(EM_UNLOCK, self.event_addr(int(t[1])), limit=LIMIT)
        elif c == "P":
            e.call(EM_PROCESS, limit=LIMIT)
        elif c == "AC":
            self.actions[int(t[1])] = t[2:]
        elif c == "D":
            pass
        elif c == "T":
            self.pending.append(struct.pack(
                "<IIIIIIII", 0x1234 + len(self.pending), int(t[1], 16),
                int(t[2], 16), 0xdead, int(t[3], 16), int(t[4], 16),
                int(t[5], 16), int(t[6], 16)))
        elif c == "K":
            base = self.build_chunk(int(t[1]), int(t[2]), t[3], self.pending)
            self.pending = []
            r = e.call(EM_LOADER, base, limit=LIMIT)
            self.emit("load c%d -> %d" % (self.nchunks - 1, r))
        elif c in ("KN", "K0"):
            base = self.build_chunk(0, 0, "", [])
            if c == "KN":
                e.put32(base, 0x80036001)
            r = e.call(EM_LOADER, base, limit=LIMIT)
            self.emit("load c%d -> %d" % (self.nchunks - 1, r))
        elif c == "U":
            r = e.call(EM_UNLOADER, self.chunks[int(t[1])]["base"],
                       limit=LIMIT)
            self.emit("unload c%s -> %d" % (t[1], r))
        elif c == "Q":
            cc, j = (int(x) for x in t[1].split("."))
            ch = self.chunks[cc]
            leaf = LEAF + 48 * (4 * cc + j)
            e.write(leaf, bytes(48))
            if t[2] == "none":
                ch["leaf"].pop(j, None)
            else:
                ch["leaf"][j] = True
                if t[2] == "parent":
                    e.write(leaf + 14, struct.pack("<h", 2))
                else:
                    n = int(t[2])
                    e.write(leaf + 14, struct.pack("<h", -n))
                    for i, x in enumerate(t[3:]):
                        e.write(leaf + 28 + 2 * i, struct.pack("<h", int(x)))
        elif c == "TE":
            for k in range(3):
                e.put32(AT + 4 * k, int(t[1 + k], 16))
            r = e.call(EM_TRIGGER, AT, limit=LIMIT)
            self.emit("trigger events -> %s [%s]" % (
                "array" if r == TRIGGER_ARRAY else self.label(r),
                " ".join(self.label(self.w(TRIGGER_ARRAY + 4 * k))
                         for k in range(NUM_TRIGGER_SLOTS))))
        elif c == "CS":
            a = CAR + 0x1000 * int(t[1])
            for k in range(4):
                e.put32(a + C_GEOM + 4 * k, int(t[2 + k], 16))
                e.put32(a + C_VEL + 4 * k, int(t[6 + k], 16))
            e.put32(a + C_VMAG, int(t[10], 16))
            e.put32(a + C_PLAYER, PLAYER if int(t[11]) else 0)
        elif c == "CT":
            e.call(CAR_TRIGGER_EVENTS, CAR + 0x1000 * int(t[1]), limit=LIMIT)
        elif c == "PL":
            e.put32(PLAYER + P_VDL, VDL_PRE if int(t[1]) else 0)
            e.put32(PLAYER + P_WRONG, int(t[2]))
        elif c == "RP":
            e.put32(RACE_PARAMS + RP_DIR, int(t[1]))
            e.put32(RACE_PARAMS + RP_TRAINING, int(t[2]))
        elif c == "RC":
            e.put32(RACE_COORD, int(t[1]))
        elif c == "WL":
            e.put32(G_WLC, int(t[1]))
        elif c == "WT":
            e.put32(G_WTF, int(t[1]))
        elif c == "VD":
            e.fpr[12] = int(t[2], 16)
            e.call(PLAYER_TVDL, PLAYER, int(t[1]), limit=LIMIT)
            self.emit("line %s" % self.label(self.w(PLAYER + P_VDL)))
        elif c == "FA":
            a = ANIM + 0x80 * int(t[1])
            e.write(a, bytes(0x80))
            e.write(a, struct.pack("<HBBI", int(t[2]) & 0xffff, 0,
                                   int(t[3]) & 0xff, int(t[4], 16)))
        elif c == "FS":
            a = SOLID + 0x100 * int(t[1])
            e.write(a, bytes(0x100))
            an = int(t[2])
            e.put32(a + 168, 0 if an < 0 else ANIM + 0x80 * an)
        elif c == "FM":
            i = int(t[1])
            a = MODEL + 0x20 * i
            e.write(a, bytes(0x20))
            e.put32(a + 8, int(t[2], 16))
            so = int(t[3])
            e.put32(a + 12, 0 if so < 0 else SOLID + 0x100 * so)
            self.put16(a + 22, int(t[4]))
            self.models[i] = int(t[2], 16)
        elif c == "MS":
            self.put16(MODEL + 0x20 * int(t[1]) + 22, int(t[2], 16))
        elif c == "FH":
            sec, ninfo, ninst = int(t[1]), int(t[2]), int(t[3])
            j = len(self.sects)
            self.sects[sec] = j
            self.ninst[sec] = ninst
            h = SECT + 0x40 * j
            e.write(h, bytes(0x40))
            e.write(INFO + 0x400 * j, bytes(0x400))
            e.write(INST + 0x1000 * j, bytes(0x1000))
            e.put32(h + 20, INFO + 0x400 * j)
            e.put32(h + 24, ninfo)
            e.put32(h + 28, INST + 0x1000 * j if ninst else 0)
            e.put32(h + 32, ninst)
            e.put32(SCENERY_TABLE + 4 * sec, h)
        elif c == "FI":
            j = self.sects[int(t[1])]
            m = int(t[3])
            e.put32(INFO + 0x400 * j + 40 * int(t[2]) + 20,
                    0 if m < 0 else MODEL + 0x20 * m)
        elif c == "FN":
            sec, i = int(t[1]), int(t[2])
            a = INST + 0x1000 * self.sects[sec] + 48 * i
            e.write(a, bytes(48))
            e.write(a + 12, struct.pack("<hH", int(t[3]), int(t[16], 16)))
            for k in range(3):
                e.put32(a + 16 + 4 * k, int(t[4 + k], 16))
            for k in range(9):
                e.write(a + 28 + 2 * k, struct.pack("<h", int(t[7 + k])))
            self.defined_inst.append((sec, i))
        elif c == "F":
            e.call(INIT_FS, limit=LIMIT)
        elif c == "FF":
            e.call(FLUSH_FS, limit=LIMIT)
        elif c == "FX":
            e.call(CLOSE_FS, limit=LIMIT)
        elif c == "FL":
            e.call(FLATTEN_FERN, int(t[1], 16), limit=LIMIT)
        elif c == "SF":
            for k in range(4):
                e.put32(VEL + 4 * k, int(t[2 + k], 16))
            e.call(SHAKE_FERN, int(t[1], 16), VEL, limit=LIMIT)
        elif c == "GA":
            r = e.call(GET_ANIM, MODEL + 0x20 * int(t[1]), limit=LIMIT)
            self.emit("anim %s" % self.label(r))
        elif c == "GT":
            r = e.call(GET_TIME, MODEL + 0x20 * int(t[1]), limit=LIMIT)
            self.emit("time %d" % r)
        elif c == "SN":
            e.call(SET_FRAME, MODEL + 0x20 * int(t[1]), int(t[2]),
                   limit=LIMIT)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for n, sc in enumerate(scenarios):
            if n:
                self.reset()
            self.pending = []
            self.emit("B %d" % n)
            for ln in sc:
                self.emit("> " + ln[:60])
                self.op(ln.split())
                self.dump()
        return self.out


# ================================================================ the build


def build_harness(tmp, name="eventmgr_test"):
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


def M(name, rel, before, after):
    return (name, rel, before, after)


MUTATIONS = [
    # ---- eventmgr.c: the module and the loader
    M("event-pool-60", EMC,
      "bNewSlotPool((int)sizeof(emEvent), 60,",
      "bNewSlotPool((int)sizeof(emEvent), 59,"),
    M("handler-pool-20", EMC,
      "bNewSlotPool((int)sizeof(emEventHandler), 20,",
      "bNewSlotPool((int)sizeof(emEventHandler), 21,"),
    M("loader-not-ours", EMC,
      "        return 0;\n    end = next_chunk(c);",
      "        return 1;\n    end = next_chunk(c);"),
    M("tree-before-pack", EMC,
      "            if (pack != NULL) {\n                vAABBTree",
      "            if (1) {\n                vAABBTree"),
    M("tree-node-array", EMC,
      "tree->NodeArray = (vAABB *)(tree + 1);",
      "tree->NodeArray = (vAABB *)(void *)tree;"),
    M("version-stops-0", EMC,
      "            if (pack->Version != 1)\n                return 1;",
      "            if (pack->Version != 1)\n                return 0;"),
    M("version-2-taken", EMC,
      "            if (pack->Version != 1)",
      "            if (pack->Version < 1)"),
    M("array-before-pack", EMC,
      "            if (pack != NULL)\n                pack->EventTriggerArray",
      "            if (1)\n                pack->EventTriggerArray"),
    M("link-no-count", EMC,
      "        if (pack->NumEventTriggers != 0 && pack->EventTree != NULL",
      "        if (pack->EventTree != NULL"),
    M("link-no-tree", EMC,
      "pack->NumEventTriggers != 0 && pack->EventTree != NULL",
      "pack->NumEventTriggers != 0"),
    M("link-no-array", EMC,
      "            && pack->EventTriggerArray != NULL)",
      "            )"),
    M("empty-on-list", EMC,
      "add_tail(&EmptyEventTriggerPackList, &pack->Node);",
      "add_tail(&EventTriggerPackList, &pack->Node);"),
    M("unload-not-ours", EMC,
      "        return 0;\n    if (g != next_chunk(c)",
      "        return 1;\n    if (g != next_chunk(c)"),
    M("unload-any-version", EMC,
      "        if (pack->Version == 1)\n            unlink_node",
      "        if (1)\n            unlink_node"),
    # ---- the handlers
    M("handler-null-taken", EMC,
      "if (fn == NULL || mask == 0)",
      "if (mask == 0)"),
    M("handler-mask-0-taken", EMC,
      "if (fn == NULL || mask == 0)",
      "if (fn == NULL)"),
    M("handler-again-no-count", EMC,
      "            h->ReferenceCount++;\n            return 1;",
      "            return 1;"),
    M("handler-again-0", EMC,
      "            h->ReferenceCount++;\n            return 1;",
      "            h->ReferenceCount++;\n            return 0;"),
    M("handler-count-2", EMC,
      "    h->ReferenceCount = 1;",
      "    h->ReferenceCount = 2;"),
    M("handler-at-head", EMC,
      "    add_tail(&EventHandlerList, &h->Node);",
      "    h->Node.next = EventHandlerList.next;\n"
      "    h->Node.prev = &EventHandlerList;\n"
      "    EventHandlerList.next->prev = &h->Node;\n"
      "    EventHandlerList.next = &h->Node;"),
    M("handler-not-counted", EMC,
      "    EventManagerStats.NumEventHandlers++;\n",
      ""),
    M("handler-hwm", EMC,
      "    if (EventManagerStats.EventHandlersHighWaterMark\n        <",
      "    if (EventManagerStats.EventHandlersHighWaterMark\n        >"),
    M("remove-handler-any-count", EMC,
      "if (--h->ReferenceCount == 0) {",
      "if ((h->ReferenceCount = 0) == 0) {"),
    M("remove-handler-not-counted", EMC,
      "                EventManagerStats.NumEventHandlers--;\n",
      ""),
    # ---- the events
    M("event-not-cleared", EMC,
      "    memset(e, 0, sizeof *e);\n",
      ""),
    M("event-on-master", EMC,
      "    add_tail(CurrentEventQueue, &e->Node);",
      "    add_tail(&MasterEventQueue, &e->Node);"),
    M("event-not-counted", EMC,
      "    EventManagerStats.NumEvents++;\n",
      ""),
    M("remove-current", EMC,
      "    if (e == CurrentlyHandlingEvent)\n        return;\n",
      ""),
    M("remove-not-counted", EMC,
      "    EventManagerStats.NumEvents--;\n",
      ""),
    M("lock-2", EMC,
      "    e->ReferenceCount++;\n}",
      "    e->ReferenceCount += 2;\n}"),
    M("unlock-2", EMC,
      "    e->ReferenceCount--;",
      "    e->ReferenceCount -= 2;"),
    # ---- emProcessAllEvents
    M("process-no-own-queue", EMC,
      "    CurrentEventQueue = &added;\n",
      ""),
    M("process-next-after", EMC,
      "        unlink_node(n);\n        CurrentlyHandlingEvent = NULL;",
      "        next = n->next;\n"
      "        unlink_node(n);\n        CurrentlyHandlingEvent = NULL;"),
    M("process-not-unlinked", EMC,
      "        unlink_node(n);\n        CurrentlyHandlingEvent = NULL;",
      "        CurrentlyHandlingEvent = NULL;"),
    M("process-any-mask", EMC,
      "if ((id & h->StreamMask) != 0) {",
      "if (1) {"),
    M("process-time-set", EMC,
      "h->TotalTime += bGetTickerDifference",
      "h->TotalTime = bGetTickerDifference"),
    M("process-time-backwards", EMC,
      "bGetTickerDifference(t0, bGetTicker())",
      "bGetTickerDifference(bGetTicker(), t0)"),
    M("process-current-kept", EMC,
      "        CurrentlyHandlingEvent = NULL;\n        if",
      "        if"),
    M("process-free-at-most-0", EMC,
      "        if (e->ReferenceCount == 0)\n            bSlotFree",
      "        if (e->ReferenceCount <= 0)\n            bSlotFree"),
    M("process-locked-last", EMC,
      "    move_all(&locked);\n    move_all(&added);",
      "    move_all(&added);\n    move_all(&locked);"),
    M("process-queue-not-reset", EMC,
      "    move_all(&added);\n    CurrentEventQueue = &MasterEventQueue;",
      "    move_all(&added);"),
    # ---- emTriggerEvents
    M("trigger-count-sign", EMC,
      "count = -leaf->NumChildren;",
      "count = leaf->NumChildren;"),
    M("trigger-no-leaf", EMC,
      "        if (leaf == NULL)\n            continue;\n",
      ""),
    M("trigger-edge-inside", EMC,
      "+ dz * dz < t->Radius * t->Radius",
      "+ dz * dz <= t->Radius * t->Radius"),
    M("trigger-sum-order", EMC,
      "if ((dx * dx + dy * dy) + dz * dz <",
      "if (dx * dx + (dy * dy + dz * dz) <"),
    M("trigger-cap-39", EMC,
      "&TriggerEventArray[EM_MAX_TRIGGERED_EVENTS];",
      "&TriggerEventArray[EM_MAX_TRIGGERED_EVENTS - 1];"),
    M("trigger-no-pack-cap", EMC,
      "         n != &EventTriggerPackList && out < limit; n = n->next) {",
      "         n != &EventTriggerPackList; n = n->next) {"),
    M("trigger-no-leaf-cap", EMC,
      "for (i = 0; i < count && out < limit; i++) {",
      "for (i = 0; i < count; i++) {"),
    M("trigger-null-skipped", EMC,
      "                *out++ = e;\n                if (e != NULL)",
      "                if (e != NULL)\n                    *out++ = e;\n"
      "                if (e != NULL)"),
    M("trigger-null-trigger", EMC,
      "                if (e != NULL)\n                    e->pEventTrigger = t;",
      "                if (1)\n                    e->pEventTrigger = t;"),
    M("trigger-none-array", EMC,
      "    if (out == TriggerEventArray)\n        return NULL;\n",
      ""),
    M("trigger-no-terminator", EMC,
      "    *out = NULL;\n    return TriggerEventArray;",
      "    return TriggerEventArray;"),
    # ---- fernshaker.c
    M("fs-pool-32", FSC,
      "bNewSlotPool((int)sizeof(FernShaker), 32,",
      "bNewSlotPool((int)sizeof(FernShaker), 33,"),
    M("fs-infos-1", FSC,
      "    NumFernShakerInfos = 2;",
      "    NumFernShakerInfos = 1;"),
    M("fs-cookie-1", FSC,
      "*(int32_t *)(void *)block = 2;",
      "*(int32_t *)(void *)block = 1;"),
    M("fs-second-name", FSC,
      "fern_shaker_info_init(&pFernShakerInfoTable[1], \"BUSHSHAKE_B\",",
      "fern_shaker_info_init(&pFernShakerInfoTable[1], \"BUSHSHAKE_A\","),
    M("fsi-emitter-flags", FSC,
      "acid_emitter_delete((AcidEmitter *)n, 3);",
      "acid_emitter_delete((AcidEmitter *)n, 1);"),
    M("fsi-always-freed", FSC,
      "    if ((flags & 1) != 0)\n        bFree(info);",
      "    bFree(info);"),
    M("close-forwards", FSC,
      "        while (info != pFernShakerInfoTable) {\n"
      "            info--;\n"
      "            fern_shaker_info_destroy(info, 0);\n"
      "        }",
      "        {\n"
      "            int32_t i;\n\n"
      "            for (i = 0; i < *(int32_t *)(void *)block; i++)\n"
      "                fern_shaker_info_destroy(pFernShakerInfoTable + i, 0);\n"
      "            (void)info;\n"
      "        }"),
    M("close-frees-table", FSC,
      "        bFree(block);",
      "        bFree(pFernShakerInfoTable);"),
    M("close-table-kept", FSC,
      "    pFernShakerInfoTable = NULL;\n    NumFernShakerInfos = 0;",
      "    NumFernShakerInfos = 0;"),
    M("close-no-flush", FSC,
      "    flush_fern_shakers();\n    bDeleteSlotPool",
      "    bDeleteSlotPool"),
    M("close-pool-kept", FSC,
      "    FernShakerSlotPool = NULL;\n}",
      "}"),
    M("ctor-start-0", FSC,
      "    s->StartTime = WorldTimeFrames;\n    s->SceneryCode = code;",
      "    s->StartTime = 0;\n    s->SceneryCode = code;"),
    M("ctor-no-instance-test", FSC,
      "    if (h == NULL || h->pSceneryInstance == NULL)",
      "    if (h == NULL)"),
    M("ctor-no-model-test", FSC,
      "if (model == NULL || emodel_get_rigid_animation(model) == NULL)",
      "if (emodel_get_rigid_animation(model) == NULL)"),
    M("ctor-no-anim-test", FSC,
      "if (model == NULL || emodel_get_rigid_animation(model) == NULL)",
      "if (model == NULL)"),
    M("ctor-exclude-bit", FSC,
      "ExcludeFlags |= 0x10;",
      "ExcludeFlags |= 0x20;"),
    M("ctor-lit", FSC,
      "        &m, 0);",
      "        &m, 1);"),
    M("ctor-wo-malloc", FSC,
      "bSlotOMalloc(WorldObjectSlotPool)",
      "bSlotMalloc(WorldObjectSlotPool)"),
    M("matrix-w-1", FSC,
      "        row[i]->w = 0.0f;",
      "        row[i]->w = 1.0f;"),
    M("matrix-scale", FSC,
      "const float k = 1.0f / 16384.0f;",
      "const float k = 1.0f / 16383.0f;"),
    M("matrix-pos-w-0", FSC,
      "    m->v3.w = 1.0f;",
      "    m->v3.w = 0.0f;"),
    M("matrix-columns", FSC,
      "row[i]->y = (float)inst->Rotation[3 * i + 1] * k;",
      "row[i]->y = (float)inst->Rotation[i + 3] * k;"),
    M("destroy-bit-kept", FSC,
      "ExcludeFlags &= 0xffef;",
      "ExcludeFlags &= 0xffff;"),
    M("destroy-wo-flags", FSC,
      "worldobject_destruct(s->pWorldObject, 3);",
      "worldobject_destruct(s->pWorldObject, 1);"),
    M("destroy-never-freed", FSC,
      "    if ((flags & 1) != 0)\n        bSlotFree(FernShakerSlotPool, s);",
      "    if (0)\n        bSlotFree(FernShakerSlotPool, s);"),
    M("shake-mph", FSC,
      "FernSpeedToMph   = 2.23f;",
      "FernSpeedToMph   = 2.24f;"),
    M("shake-5-inclusive", FSC,
      "if (!(5.0f < speed))",
      "if (!(5.0f <= speed))"),
    M("shake-sum-order", FSC,
      "sqrtf((vel->x * vel->x + vel->y * vel->y) + vel->z * vel->z)",
      "sqrtf(vel->x * vel->x + (vel->y * vel->y + vel->z * vel->z))"),
    M("shake-30-inclusive", FSC,
      "        if (30.0f < speed)",
      "        if (30.0f <= speed)"),
    M("shake-quarter", FSC,
      "anim->NumFrames * 0.5f)",
      "anim->NumFrames * 0.25f)"),
    M("shake-rounded", FSC,
      "frame = ee_trunc_w((float)(int16_t)anim->NumFrames * 0.5f);",
      "frame = ee_trunc_w((float)(int16_t)anim->NumFrames * 0.5f + 0.5f);"),
    M("shake-unsigned-frames", FSC,
      "(float)(int16_t)anim->NumFrames",
      "(float)anim->NumFrames"),
    M("shake-start-kept", FSC,
      "        s->StartTime = WorldTimeFrames;\n        emodel_set",
      "        emodel_set"),
    M("shake-not-clamped", FSC,
      "    if (1.0f < shake)\n        shake = 1.0f;\n",
      ""),
    M("shake-not-floored", FSC,
      "    if (shake < 0.0f)\n        shake = 0.0f;\n",
      ""),
    M("shake-per-mph", FSC,
      "FernShakePerMph  = 0.04f;",
      "FernShakePerMph  = 0.05f;"),
    M("shake-no-info-test", FSC,
      "if (!(0.0f < shake) || s->pFernShakerInfo == NULL)",
      "if (!(0.0f < shake))"),
    M("shake-iv-w-1", FSC,
      "e->InheritVelocity.w = 0.0f;",
      "e->InheritVelocity.w = 1.0f;"),
    M("shake-not-placed", FSC,
      "        e->LocalWorld = m;\n",
      ""),
    M("shake-positive", FSC,
      "e, -shake, NULL);",
      "e, shake, NULL);"),
    M("shake-car", FSC,
      "e, -shake, NULL);",
      "e, -shake, (void *)s);"),
    M("age-241-exclusive", FSC,
      "            >= FERN_SHAKER_LIFETIME) {",
      "            > FERN_SHAKER_LIFETIME) {"),
    M("age-unsigned", FSC,
      "        if ((int32_t)((uint32_t)WorldTimeFrames",
      "        if ((uint32_t)((uint32_t)WorldTimeFrames"),
    M("find-other", FSC,
      "if (((FernShaker *)n)->SceneryCode == code)",
      "if (((FernShaker *)n)->SceneryCode == (code ^ 1u))"),
    M("full-not-tested", FSC,
      "        if (bIsSlotPoolFull(FernShakerSlotPool))\n            return;\n",
      ""),
    M("shaker-at-head", FSC,
      "        add_tail(&FernShakerList, &s->Node);",
      "        s->Node.next = FernShakerList.next;\n"
      "        s->Node.prev = &FernShakerList;\n"
      "        FernShakerList.next->prev = &s->Node;\n"
      "        FernShakerList.next = &s->Node;"),
    M("shaker-omalloc", FSC,
      "bSlotMalloc(FernShakerSlotPool)",
      "bSlotOMalloc(FernShakerSlotPool)"),
    # ---- emodelanim.c
    M("anim-null-solid", EMA,
      "    if (s == NULL)\n        return NULL;\n",
      ""),
    M("len-unsigned-frames", EMA,
      "(int32_t)(int16_t)a->NumFrames",
      "(int32_t)a->NumFrames"),
    M("len-unsigned-scale", EMA,
      "(int32_t)(int8_t)a->FrameRateScale",
      "(int32_t)a->FrameRateScale"),
    M("time-start-0", EMA,
      "    if (start == 0)\n        return -1;\n",
      ""),
    M("time-mask-15", EMA,
      "    t = (int32_t)(((uint32_t)WorldTimeFrames - start) & 0x3fffu);",
      "    t = (int32_t)(((uint32_t)WorldTimeFrames - start) & 0x7fffu);"),
    M("time-loop-bit", EMA,
      "if ((start & 0x4000u) != 0)",
      "if ((start & 0x8000u) != 0)"),
    M("time-end-inclusive", EMA,
      "return t < len ? t : -1;",
      "return t <= len ? t : -1;"),
    M("frame-one-a-frame", EMA,
      "(uint32_t)frame * 2u",
      "(uint32_t)frame * 1u"),
    M("frame-loop-bit", EMA,
      "(int16_t)(t | 0x8000u);",
      "(int16_t)(t | 0xc000u);"),
    M("frame-mask-15", EMA,
      "* 2u) & 0x3fffu;",
      "* 2u) & 0x7fffu;"),
    # ---- carevents.c
    M("look-ahead", CEV,
      "CarEventLookAhead = 0.15f;",
      "CarEventLookAhead = 0.25f;"),
    M("look-ahead-y", CEV,
      "    at.y = st->GeometryPosition.y + st->Velocity.y * CarEventLookAhead;",
      "    at.y = st->GeometryPosition.y;"),
    M("events-null", CEV,
      "    if (events == NULL)\n        return;\n",
      ""),
    M("fern-name", CEV,
      "uint32_t code = e->pEventTrigger->Parameter;",
      "uint32_t code = e->pEventTrigger->NameHash;"),
    M("fern-position", CEV,
      "shake_fern(code, &st->Velocity);",
      "shake_fern(code, &st->GeometryPosition);"),
    M("fern-loop-parity", CEV,
      "((WorldLoopCounter + 3) & 3) == 0",
      "(WorldLoopCounter & 3) == 0"),
    M("fern-no-player-test", CEV,
      "            if (c->pPlayer != NULL && ((WorldLoopCounter",
      "            if (((WorldLoopCounter"),
    M("fern-30-inclusive", CEV,
      "&& 30.0f < st->VelocityMagnitude)",
      "&& 30.0f <= st->VelocityMagnitude)"),
    M("fern-value", CEV,
      "interesting(2.0f, \"FlattenFern\");",
      "interesting(1.0f, \"FlattenFern\");"),
    M("line-no-player-test", CEV,
      "            if (p == NULL)\n                continue;\n",
      ""),
    M("line-no-player-stops", CEV,
      "            if (p == NULL)\n                continue;\n",
      "            if (p == NULL)\n                break;\n"),
    M("line-forward-backward", CEV,
      "        return !backward;",
      "        return backward;"),
    M("line-other-direction", CEV,
      "    default:\n        return 0;",
      "    default:\n        return 1;"),
    M("line-direction-bit", CEV,
      "(parameter & 0xffu) != 0;",
      "(parameter & 0x1u) != 0;"),
    M("line-40-inclusive", CEV,
      "&& 40.0f < st->VelocityMagnitude && p->bWrongWay == 0)",
      "&& 40.0f <= st->VelocityMagnitude && p->bWrongWay == 0)"),
    M("line-wrong-way", CEV,
      " && p->bWrongWay == 0)",
      ")"),
    M("line-number", CEV,
      "(int32_t)(parameter >> 16)",
      "(int32_t)(parameter >> 15)"),
    M("line-seconds", CEV,
      "((parameter >> 8) & 0xffu)",
      "((parameter >> 8) & 0x7fu)"),
    M("line-5-seconds", CEV,
      "        seconds = 5.0f;",
      "        seconds = 4.0f;"),
    M("line-training", CEV,
      "    if (!TheRaceParameters.TrainingLinesEnabled)\n        return;\n",
      ""),
    M("line-state", CEV,
      "!= RCSTATE_RACE_IN_PROGRESS)",
      "== RCSTATE_RACE_IN_PROGRESS)"),
    M("line-again", CEV,
      "    if (p->pVisibleDrivingLine != NULL)\n        return;\n",
      ""),
    M("line-pool", CEV,
      "\"VisibleDrivingLine\", 0, 16);",
      "\"VisibleDrivingLine\", 0, 0);"),
    M("line-not-kept", CEV,
      "    p->pVisibleDrivingLine = gVisibleDrivingLineCtorFn(",
      "    (void)gVisibleDrivingLineCtorFn("),
    M("others-kept", CEV,
      "        } else {\n            em_remove_event(e);\n        }",
      "        }"),
]

EQUIVALENT = {
    # Speed times 2.23f steps over 30.0 (13.452914f gives 29.999998, the
    # next float 30.000002), so `30 <` and `30 <=` see the same speeds.
    "shake-30-inclusive": "no float speed is 30.0 mph exactly",
    # The test before it lets only speeds over 5 through, and
    # (speed - 5) * 0.04 of the smallest such is 1.9e-8, not 0.
    "shake-not-floored": "the shake is never below 0",
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
    handled = sum(1 for ln in lines if ln.startswith("handler "))
    shakes = sum(1 for ln in lines if ln.startswith("trigger sys"))
    print("%d scenarios, %d ops, %d lines, %d handled, %d emitters "
          "triggered, %d differ" % (len(sc), ops, len(harness), handled,
                                    shakes, n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
