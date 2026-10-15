#!/usr/bin/env python3
"""Cross-check 3DS Files/source/speechmgr.c against the retail image,
SLES_507.31.

**The model** is retail's own speech manager run in retail_model.RetailEmu:
speech::mgr_t's constructor (0x0020b868, which builds nfsFsm's states,
conditions, actions and transitions, 0x0020c770), getInstance, update,
FlushQueue, AllocateVoices, fade, Mute, pushSpeechEvent and the raise
functions (0x00209ef0 .. 0x0020b868); fsm, state_t and transition
(0x0020bf00 .. 0x0020c750); action_t's and actionHelicopter_t's execute,
the conditions and every action (0x0020bdf8 .., 0x0020daa0 ..
0x0020f7c0); speechContext_t's getters and ShuffleCopIds (0x0020f820 ..
0x0020fac8); Speech::ConvertSpeed (0x00223528, with the soft-float
fptoui); and RaceCoordinator::IsReplayDemoMode. The harness
(tools/src/speechmgr_test.c) runs speechmgr.c's.

**The fakes**, the same on both sides, each printing what it is handed:
SpeechNoise's getInstance, IsRadioNoise (the script's flag),
StartRadioNoise and StopRadioNoise (which set it), StartHelicopterNoise,
StopHelicopterNoise and BeginSquelchNoise; SPCH_AddEventV; bRandom,
answering the script's numbers in turn (0 once they run out); the wedge
(gp-19016, absent or a status) and its Fade, Mute and ClearEventQueue;
and the race coordinator (gp-22216, absent or a state). bMalloc hands the
machine's constructor zeroed blocks and prints nothing, for the port
builds no machine.

**The script** constructs and asks for the instance; raises each event
with the ids unshuffled and shuffled; walks every event from the ready
state, and every state on event 1, over contexts that turn each
condition both ways; fills the queue past full; flushes; updates with no
wedge, a wedge playing, paused, idle and stopped, the radio on and off,
and in each race state; runs every raise function, and ConvertSpeed
across its range and on NaN and the infinities; and fades and mutes with
and without the wedge.

    python tools/speechmgr_check.py
    python tools/speechmgr_check.py --mutate [--only a,b]
    python tools/speechmgr_check.py --dump out/speechmgr
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
from mipsemu import ARGREGS, M32, s32   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/speechmgr_test.c"
SMC = "3DS Files/source/speechmgr.c"
SOURCES = [HARNESS, SMC]
HARNESS_TIMEOUT = 30
LIMIT = 2000000

GP = retail_model.RETAIL_GP
F = {
    "inst": 0x00209ef0, "update": 0x00209ff8, "flush": 0x0020a230,
    "alloc": 0x0020a288, "fade": 0x0020a290, "mute": 0x0020a2b0,
    "push": 0x0020a2e8, "ctor": 0x0020b868, "conv": 0x00223528,
}
SIZE = 1464
INSTANCE = 0x00334418
WEDGEP, RCP, DEBUGFLAG = GP - 19016, GP - 22216, GP - 16420
INSTGUARD = GP - 16416
TABLES = (0x0031bc70, 0x0031bc60, 0x0031bc50)

# The raise functions: name, address, argument kinds (u/i an integer
# register, f the float register).
RAISES = {
    "pcophit": (0x0020a3e0, "ui"),
    "bpcophitrun": (0x0020a430, "ui"),
    "bpgeneral": (0x0020a480, "u"),
    "bperratic": (0x0020a4c0, "u"),
    "bpnoid": (0x0020a500, "u"),
    "bphitruntraffic": (0x0020a590, "ui"),
    "bpidgeneral": (0x0020a5e0, "uii"),
    "bpidspecific": (0x0020a640, "uiii"),
    "bpagain": (0x0020a6b0, "uii"),
    "bpidrepeated": (0x0020a710, "uiii"),
    "bpspeed": (0x0020a7f0, "uf"),
    "backupreq": (0x0020a850, "u"),
    "backupconfirm": (0x0020a890, "uu"),
    "backupreqloc": (0x0020a8e0, "ui"),
    "crash": (0x0020a9b0, "uu"),
    "flattire": (0x0020aa00, "uu"),
    "crashtow": (0x0020aa90, "uu"),
    "avoidance": (0x0020ab40, "u"),
    "subjectloc": (0x0020ab80, "uii"),
    "suspectfound": (0x0020ac40, "uii"),
    "tactichit": (0x0020acf0, "uu"),
    "tacticdivert": (0x0020ad40, "u"),
    "tacticcutoff": (0x0020ad80, "u"),
    "reckless": (0x0020adc0, "ui"),
    "racercaught": (0x0020ae00, "uii"),
    "superbackoff": (0x0020ae60, ""),
    "copbackoff": (0x0020ae68, "ui"),
    "carstopped": (0x0020aeb8, "ui"),
    "radioarrest": (0x0020af08, "u"),
    "rotorrequest": (0x0020af50, "ui"),
    "rotorconfirm": (0x0020afa0, ""),
    "rotorlocation": (0x0020afa8, "i"),
    "rotorchatter": (0x0020afe8, "i"),
    "rotorspikefailed": (0x0020b028, "ui"),
    "rotortraffic": (0x0020b078, ""),
    "rbfailavoid": (0x0020b080, "uiu"),
    "rbfailthrough": (0x0020b0e0, "uiu"),
    "rbrequest": (0x0020b140, "ui"),
    "anotherrb": (0x0020b190, "ui"),
    "rbset": (0x0020b1e0, "uii"),
    "rbsetting": (0x0020b240, "ui"),
    "spikefail": (0x0020b290, "uiu"),
    "spikerequest": (0x0020b2f0, "ui"),
    "spikeset": (0x0020b340, "uii"),
    "spikesetleft": (0x0020b3a0, "uii"),
    "spikesetright": (0x0020b400, "uii"),
    "tireblow": (0x0020b460, "ui"),
    "superrequest": (0x0020b4b0, "u"),
    "superinitiate": (0x0020b4f0, "ufiii"),
    "currentspeed": (0x0020b5d8, "uf"),
    "crashtraffic": (0x0020b758, "ui"),
    "lookout": (0x0020b7a8, "i"),
    "rbna": (0x0020b7e8, "u"),
    "helina": (0x0020b828, "u"),
}


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def num(s):
    return int(s, 0)


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.m = e.alloc(SIZE + 64, 16)
        e.mem[self.m:self.m + SIZE] = b"\0" * SIZE
        self.noise = e.alloc(64, 16)
        self.wedge = e.alloc(2240, 16)
        self.rc = e.alloc(64, 16)
        self.radio = 0
        self.rand = []
        e.put32(WEDGEP, 0)
        e.put32(RCP, 0)
        e.put32(DEBUGFLAG, 0)

        e.stub(0x002577c0, self.b_malloc)
        e.stub(0x00114e98, lambda em: 0)            # __builtin_delete
        e.stub(0x00296220, lambda em: 0)            # atexit
        e.stub(0x001b0188, lambda em: self.noise)   # SpeechNoise::getInstance
        e.stub(0x002159b8, self.is_radio)
        e.stub(0x002159a0, self.noise_say("radio on", 1))
        e.stub(0x002159b0, self.noise_say("radio off", 0))
        e.stub(0x00215930, self.noise_say("heli on"))
        e.stub(0x00215958, self.noise_say("heli off"))
        e.stub(0x002159c0, self.noise_say("squelch"))
        e.stub(0x002919d0, self.spch)
        e.stub(0x0025a488, self.b_random)
        e.stub(0x00205da8, self.w_fade)
        e.stub(0x00205e00, self.w_mute)
        e.stub(0x00206190, self.w_clear)
        e.stub(0x0025d2c8, lambda em: 0)            # bRefreshTweaker

    def emit(self, s):
        self.out.append(s)

    def b_malloc(self, em):
        n = s32(em.reg[4])
        p = self.e.alloc(max(n, 4) + 16, 16)
        self.e.mem[p:p + n] = b"\0" * n
        return p

    def nname(self, a):
        return "noise" if (a & M32) == self.noise else "?"

    def wname(self, a):
        return "wedge" if (a & M32) == self.wedge else "?"

    def noise_say(self, text, radio=None):
        def stub(em):
            self.emit("  %s %s" % (text, self.nname(em.reg[4])))
            if radio is not None:
                self.radio = radio
            return 0
        return stub

    def is_radio(self, em):
        self.emit("  isradio %s -> %d" % (self.nname(em.reg[4]), self.radio))
        return self.radio

    def spch(self, em):
        n = s32(em.reg[5])
        args = []
        for k in range(n):
            if 2 + k < len(ARGREGS):
                args.append("%x" % (em.reg[ARGREGS[2 + k]] & M32))
            else:
                args.append("?")
        self.emit("  spch %d %d:%s" % (em.reg[4] & M32, n,
                                       "".join(" " + a for a in args)))
        return 1

    def b_random(self, em):
        n = s32(em.reg[4])
        r = self.rand.pop(0) if self.rand else 0
        if n > 0:
            r %= n
        self.emit("  rand %d -> %d" % (n, r))
        return r

    def w_fade(self, em):
        self.emit("  fade %s %08x" % (self.wname(em.reg[4]), em.fpr[12]))
        return 0

    def w_mute(self, em):
        self.emit("  wmute %s %d" % (self.wname(em.reg[4]), em.reg[5] & 0xff))
        return 0

    def w_clear(self, em):
        self.emit("  clearq %s" % self.wname(em.reg[4]))
        return 1

    def call(self, addr, *args):
        return self.e.call(addr, *args, limit=LIMIT)

    def state_of(self, m):
        cur = self.e.u32(m)
        if cur == 0:
            return -1
        return (cur - (m + 16)) // 32

    def dump(self):
        e, m = self.e, self.m
        q = [s32(e.u32(m + 1192 + 4 * k)) for k in range(4)]
        self.emit(
            "  st=%d q=%d,%d %d,%d r=%d w=%d full=%d nc=%d cc=%d sp=%d" % (
                self.state_of(m), q[0], q[1], q[2], q[3],
                s32(e.u32(m + 1208)), s32(e.u32(m + 1212)),
                s32(e.u32(m + 1216)), s32(e.u32(m + 1220)),
                s32(e.u32(m + 1224)), s32(e.u32(m + 1452))))
        for k in range(4):
            c = m + 1228 + 56 * k
            self.emit("  c%d %s" % (k, " ".join(
                "%x" % e.u32(c + 4 * i) for i in range(14))))
        self.emit("  ids %s" % " ".join(
            "%x" % e.u32(t + 4 * i) for t in TABLES for i in range(4)))

    def raise_op(self, f):
        if f[1] not in RAISES:
            self.emit("  ? %s" % f[1])
            return False
        addr, kinds = RAISES[f[1]]
        ints = [self.m]
        for k, kind in enumerate(kinds):
            v = num(f[2 + k])
            if kind == "f":
                self.e.fpr[12] = v & M32
            else:
                ints.append(v & M32)
        self.call(addr, *ints)
        return True

    def op(self, f):
        e, m, o = self.e, self.m, f[0]
        if o == "ctor":
            self.call(F["ctor"], m)
        elif o == "inst":
            a = self.call(F["inst"]) & M32
            b = self.call(F["inst"]) & M32
            self.emit("  inst %d st=%d nc=%d sp=%d" % (
                1 if a == b == INSTANCE else 0, self.state_of(a),
                s32(e.u32(a + 1220)), s32(e.u32(a + 1452))))
            return
        elif o == "update":
            self.call(F["update"], m)
        elif o == "push":
            self.call(F["push"], m, num(f[1]) & M32)
        elif o == "flush":
            self.call(F["flush"], m)
        elif o == "alloc":
            self.call(F["alloc"], m)
        elif o == "fade":
            e.fpr[12] = num(f[1]) & M32
            self.call(F["fade"], m)
        elif o == "mute":
            self.call(F["mute"], m, num(f[1]) & M32)
        elif o == "r":
            if not self.raise_op(f):
                return
        elif o == "conv":
            e.fpr[12] = num(f[1]) & M32
            v = self.call(F["conv"], 0)
            self.emit("  conv %08x -> %d" % (num(f[1]) & M32, v))
            return
        elif o == "wedge":
            if f[1] == "none":
                e.put32(WEDGEP, 0)
            else:
                e.put32(WEDGEP, self.wedge)
                e.put32(self.wedge + 120, num(f[1]) & M32)
            return
        elif o == "rc":
            if f[1] == "none":
                e.put32(RCP, 0)
            else:
                e.put32(RCP, self.rc)
                e.put32(self.rc, num(f[1]) & M32)
            return
        elif o == "radio":
            self.radio = num(f[1])
            return
        elif o == "rand":
            self.rand = [num(x) for x in f[1:]]
            return
        elif o == "ctx":
            e.put32(m + 1228 + 56 * num(f[1]) + num(f[2]), num(f[3]) & M32)
            return
        elif o == "state":
            e.put32(m, m + 16 + 32 * num(f[1]))
            return
        elif o == "curr":
            e.put32(m + 1224, num(f[1]) & M32)
            return
        elif o == "next":
            e.put32(m + 1220, num(f[1]) & M32)
            return
        elif o == "nd":
            self.dump()
            return
        else:
            self.emit("  ? %s" % o)
            return
        self.dump()

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    m = Model()
    out = m.run(lines)
    return out, m.e


# ================================================================ script

# The contexts' words, by offset.
UNIT, TARGET, LOC, ARR, LEVEL, SUP = 0, 4, 8, 12, 16, 20
APPROX, EXACT, COLOR, SPEED, RACE, DIR, RBL, BOOL = (24, 28, 32, 36, 40,
                                                     44, 48, 52)
EVENTS = list(range(-1, 73)) + [100, 255, 256 + 32]


def script():
    L = []
    a = L.append

    def fill(k, unit, target, loc, sup, rbl, level=1, flag=0, base=0):
        vals = {UNIT: unit, TARGET: target, LOC: loc, ARR: 1 + (k & 1),
                LEVEL: level, SUP: sup, APPROX: 1 + k, EXACT: 0x40 << k,
                COLOR: 0x100 >> k, SPEED: 0x10 << k, RACE: 1 << k,
                DIR: 0x20 >> k, RBL: rbl, BOOL: flag}
        for off, v in sorted(vals.items()):
            a("ctx|%d|%d|0x%x" % (k, off, (v + base) & M32))

    def fill_all(**kw):
        for k in range(4):
            fill(k, **kw)

    def settle(n=3):
        for _ in range(n):
            a("update")

    # The constructor, and the instance.
    a("ctor")
    a("inst")

    # Unshuffled ids are 0; a raise and its sentence.
    a("r|bpgeneral|1")
    settle()
    a("r|crash|2|3")
    settle(2)

    # The shuffle, three ways.
    a("rand|3|2|1|5|4|3|2|1")
    a("alloc")
    a("rand|0|0|0|0|0|0|0|0")
    a("alloc")
    a("rand|1|1|1|1|1|1|1|1")
    a("alloc")
    a("rand|2|0|1|3|1|2|0|1")
    a("alloc")

    # Every event from the ready state, over contexts that turn each
    # condition both ways: the supervisor (0, 1, 2), the location, the
    # target's to id (target 0 .. 4, the last past the table), the road
    # block, the arrest level, the chatter flag; the random draws both
    # ways.
    variants = [
        dict(unit=0, target=1, loc=0x30, sup=0, rbl=0, level=1, flag=0),
        dict(unit=1, target=0, loc=0, sup=1, rbl=0x55, level=2, flag=1),
        dict(unit=2, target=4, loc=0x7, sup=2, rbl=0x9, level=3, flag=2),
        dict(unit=3, target=3, loc=0, sup=1, rbl=0, level=0, flag=0),
        dict(unit=5, target=2, loc=0x11, sup=0, rbl=0x21, level=1, flag=1),
    ]
    for vi, v in enumerate(variants):
        fill_all(**v)
        for ev in EVENTS:
            a("rand|%d|%d" % (vi & 1, (vi >> 1) & 1))
            a("push|%d" % ev)
            settle(3 if ev not in (8, 9, 14) else 4)

    # Every state on event 1, with each context as the current one.
    fill(0, unit=1, target=2, loc=0x40, sup=1, rbl=0x12)
    fill(1, unit=2, target=0, loc=0, sup=0, rbl=0)
    fill(2, unit=0, target=7, loc=0x3, sup=3, rbl=0x8, level=2, flag=1)
    fill(3, unit=3, target=1, loc=0, sup=0xffffffff, rbl=0, level=4)
    for k in range(4):
        a("curr|%d" % k)
        for st in range(25):
            a("rand|%d" % (k & 1))
            a("state|%d" % st)
            a("update")
    a("state|0")

    # The queue: two in, a third dropped (its context written all the
    # same), then out in order.
    a("r|bperratic|1")
    a("r|bpnoid|2")
    a("r|backupreq|3")
    a("r|crashtow|0|1")
    settle(5)
    # Flushed: the machine back to ready mid-exchange, the queue emptied.
    a("r|tactichit|1|2")
    a("r|crash|2|3")
    a("update")
    a("flush")
    a("update")
    a("r|flattire|2|3")
    a("r|tacticdivert|0")
    a("flush")
    settle(2)
    a("next|3")
    a("r|tacticcutoff|1")
    a("r|tacticcutoff|2")
    settle(3)

    # The wedge and the radio: no wedge, idle, paused, playing, stopped,
    # odd states; the radio already on or off.
    for w in ("none", "1", "8", "2", "32", "0", "5"):
        for radio in (0, 1):
            a("wedge|%s" % w)
            a("radio|%d" % radio)
            a("update")
            a("r|backupreq|1")
            a("update")
            a("update")
            a("flush")
    a("wedge|none")
    a("radio|0")

    # The race coordinator's states: no speech in the replays and after.
    for st in ("none", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
               "10"):
        a("rc|%s" % st)
        a("r|superrequest|2")
        a("push|60")
        a("update")
        a("state|1")
        a("update")
        a("flush")
    a("rc|none")
    a("state|0")

    # The raise functions, each twice: once taken, once over a full queue.
    fill_all(unit=0, target=0, loc=0, sup=0, rbl=0, level=0, flag=0)
    speeds = [fbits(x) for x in (150.0, 99.0, 341.0, 220.5)]
    args = {
        "u": ["1", "3", "0", "5"], "i": ["0x40", "0", "7", "-1"],
        "f": ["0x%x" % s for s in speeds],
    }
    for name in RAISES:
        kinds = RAISES[name][1]
        for rep in range(4):
            vals = []
            for k, kind in enumerate(kinds):
                vals.append(args[kind][(rep + k) % 4])
            a("|".join(["r", name] + vals))
            if rep == 1:
                a("r|bpgeneral|2")
                a("r|bpgeneral|3")
                a("|".join(["r", name] + vals[::-1]))
            settle(4)

    # ConvertSpeed.
    for x in (0.0, -5.0, 99.99, 100.0, 100.001, 119.99, 120.0, 139.9,
              140.0, 200.0, 299.0, 320.0, 339.99, 340.0, 340.001, 1000.0):
        a("conv|0x%08x" % fbits(x))
    for b in (0x7fc00000, 0xffc00000, 0x7f800000, 0xff800000, 0x00000001,
              0x80000000, 0x7f7fffff):
        a("conv|0x%08x" % b)

    # Fade and mute, with and without the wedge.
    for w in ("none", "2"):
        a("wedge|%s" % w)
        a("fade|0x%08x" % fbits(0.5))
        a("fade|0x%08x" % fbits(1.0))
        a("mute|1")
        a("mute|0")
    a("wedge|none")

    # The constructor again, over a used manager: the contexts and
    # currContext stay.
    a("state|5")
    a("r|crash|1|2")
    a("curr|2")
    a("ctor")
    return L


# ================================================================= build

def build_harness(tmp, name="speechmgr_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)],
                               stdout=fh, stderr=subprocess.PIPE, text=True,
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

MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def model_cached(lines):
    """model(lines)'s transcript, or its last one when nothing it reads
    has changed. Nothing past the mutations' header is the model's."""
    return mutpar.model_cached(lines, lambda sc: model(sc)[0],
                               cut=MUTATIONS_HEADER)


def _m(name, before, after, rel=SMC):
    return (name, rel, before, after)


def _source():
    return (ROOT / SMC).read_bytes().decode("latin-1").replace("\r\n", NL)


def _say_mutations(src):
    """Each action's sentence: its event id, and its parameters (reversed,
    or one more than they are, or one where there were none)."""
    out = []
    for line in src.split(NL):
        s = line.strip()
        if not s.startswith("spch_add_event_v("):
            continue
        inner = s[len("spch_add_event_v("):-2]
        parts = [p.strip() for p in inner.split(",")]
        ev, cnt, args = parts[0], parts[1], parts[2:]
        out.append(_m("say-id-%s" % ev, s, s.replace(
            "spch_add_event_v(%s," % ev, "spch_add_event_v(%s," % (
                int(ev) + 1000), 1)))
        # The from and to ids are the same (speechcontext_shuffle_cop_ids),
        # so FROM, COP, TO reversed would say the same; rotate those.
        same = {"TO": "FROM", "TTO": "TFROM"}
        if len(args) >= 2 and [same.get(a, a) for a in args] == \
                [same.get(a, a) for a in args[::-1]]:
            new = args[1:] + args[:1]
        elif len(args) >= 2:
            new = args[::-1]
        elif len(args) == 1:
            new = ["%s + 1" % args[0]]
        elif len(args) == 0:
            new = None
        else:
            new = args[:-1] + ["7"]
        if new is None:
            after = "spch_add_event_v(%s, 1, 7);" % ev
        else:
            after = "spch_add_event_v(%s, %s, %s);" % (ev, cnt,
                                                       ", ".join(new))
        out.append(_m("say-arg-%s" % ev, s, after))
    return out


def _table_mutations(src):
    """Each transition's event, state, condition and action, and the order
    of each two-transition state's."""
    out = []
    lines = src.split(NL)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("static const SpeechTransition k"):
            tab = ln.split()[3].split("[")[0]
            j = i + 1
            rows = []
            while not lines[j].startswith("};"):
                rows.append(lines[j])
                j += 1
            for k, row in enumerate(rows):
                before = NL.join([ln] + rows[:k + 1])
                f = [x.strip() for x in row.strip()[1:-2].split(",")]
                ev, dst, cnd, act = f

                def put(g, f=f, before=before, k=k):
                    return NL.join([ln] + rows[:k] + [
                        "    { %s, %s, %s, %s }," % tuple(g)])
                g = list(f)
                g[0] = "%2d" % (int(ev) + 100)
                out.append(_m("t-%s-%d-ev" % (tab, k), before, put(g)))
                g = list(f)
                g[1] = "S(DISPATCH_CONFIRM)" if dst == "S(READY)" \
                    else "S(READY)"
                out.append(_m("t-%s-%d-dest" % (tab, k), before, put(g)))
                g = list(f)
                g[2] = "C_SUP_ACTIVE" if cnd == "C_NULL" else "C_NULL"
                out.append(_m("t-%s-%d-cond" % (tab, k), before, put(g)))
                g = list(f)
                g[3] = "A_DISPATCH_TERMINATE" if act == "A_NULL" \
                    else "A_NULL"
                out.append(_m("t-%s-%d-act" % (tab, k), before, put(g)))
            if len(rows) == 2:
                out.append(_m("t-%s-order" % tab, NL.join([ln] + rows),
                              NL.join([ln, rows[1], rows[0]])))
            i = j
        i += 1
    return out


def _raise_mutations(src):
    """Each raise function's event, and each of its stores dropped."""
    out = []
    for part in src.split("\nvoid speechmgr_raise_")[1:]:
        body = "void speechmgr_raise_" + part.split("\n}\n")[0] + "\n}"
        name = part.split("(")[0]
        ev = body.split("speechmgr_push_speech_event(m, ")[1].split(")")[0]
        out.append(_m("raise-%s-ev" % name, body, body.replace(
            "speechmgr_push_speech_event(m, %s)" % ev,
            "speechmgr_push_speech_event(m, %d)" % (int(ev) + 100))))
        for k, ln in enumerate(body.split(NL)):
            if ln.startswith("    c->"):
                out.append(_m("raise-%s-store%d" % (name, k), body,
                              body.replace(ln + NL, "", 1)))
        if "NEXT;" in body:
            out.append(_m("raise-%s-ctx" % name, body, body.replace(
                "NEXT;", "SpeechContext *c = &m->contexts[0]")))
    return out


_SRC = _source()

MUTATIONS = _say_mutations(_SRC) + _table_mutations(_SRC) + \
    _raise_mutations(_SRC) + [
    # The conditions.
    _m("cond-sup", "        return c->isSupervisorActive;",
       "        return c->isSupervisorActive == 1;"),
    _m("cond-notsup", "return c->isSupervisorActive ^ 1;",
       "return !c->isSupervisorActive;"),
    _m("cond-loc", "return c->copUnitLocation != 0;", "return 1;"),
    _m("cond-target", "return speechcontext_get_target_to_id(c) != 0;",
       "return speechcontext_get_to_id(c) != 0;"),
    _m("cond-target-unit", "return speechcontext_get_target_to_id(c) != 0;",
       "return c->copTargetUnitId != 0;"),
    _m("cond-null", "    default:\n        return 1;\n    }\n}",
       "    default:\n        return 0;\n    }\n}"),

    # The machine.
    _m("fsm-event", "if (t[i].event == event && condition_is_true",
       "if (t[i].event == (uint8_t)event && condition_is_true"),
    _m("fsm-cond", "condition_is_true(t[i].cond, c) != 0) {",
       "condition_is_true(t[i].cond, c) == 0) {"),
    _m("fsm-dest", "            m->state = t[i].dest;\n", ""),
    _m("fsm-first", "            m->state = t[i].dest;\n            return;",
       "            m->state = t[i].dest;"),
    _m("fsm-order", "            action_execute(t[i].action, c);\n"
       "            m->state = t[i].dest;",
       "            m->state = t[i].dest;\n"
       "            action_execute(t[i].action, c);"),
    _m("ex-squelch",
       "    speechnoise_begin_squelch_noise(speechnoise_get_instance());\n", ""),
    _m("ex-heli-order",
       "    speechnoise_begin_squelch_noise(speechnoise_get_instance());\n"
       "    if (a == A_ROTOR_LOCATION",
       "    if (a == A_ROTOR_LOCATION"),
    _m("ex-heli-loc", "if (a == A_ROTOR_LOCATION || a == A_ROTOR_CHATTER",
       "if (a == A_ROTOR_CHATTER"),
    _m("ex-heli-chatter", "if (a == A_ROTOR_LOCATION || a == A_ROTOR_CHATTER",
       "if (a == A_ROTOR_LOCATION"),
    _m("ex-heli-traffic", "|| a == A_ROTOR_TRAFFIC || a == A_ROTOR_SPIKE_FAILED)",
       "|| a == A_ROTOR_SPIKE_FAILED)"),
    _m("ex-heli-spike", "|| a == A_ROTOR_TRAFFIC || a == A_ROTOR_SPIKE_FAILED)",
       "|| a == A_ROTOR_TRAFFIC)"),
    _m("ex-heli-gone",
       "        speechnoise_start_helicopter_noise(speechnoise_get_instance());\n"
       "    action_say", "        ;\n    action_say"),
    _m("say-sup", "#define SUP     (c->isSupervisorActive != 0)",
       "#define SUP     (c->isSupervisorActive)"),
    _m("say-rbl-test", "        if (RBL != 0 && bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(71,",
       "        if (bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(71,"),
    _m("say-rbl-rand", "        if (RBL != 0 && bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(71,",
       "        if (RBL != 0 && bRandomI(2, bViewSeed) == 1)\n"
       "            spch_add_event_v(71,"),
    _m("say-spike-test", "        if (RBL != 0 && bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(170,",
       "        if (bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(170,"),
    _m("say-spike-n", "        if (RBL != 0 && bRandomI(2, bViewSeed) == 0)\n"
       "            spch_add_event_v(170,",
       "        if (RBL != 0 && bRandomI(3, bViewSeed) == 0)\n"
       "            spch_add_event_v(170,"),
    _m("say-racing", "        if (LOC != 0)\n            spch_add_event_v(83",
       "        if (1)\n            spch_add_event_v(83"),
    _m("say-caught-1", "if (c->arrestLevel == 1)", "if (c->arrestLevel == 3)"),
    _m("say-caught-2", "else if (c->arrestLevel == 2)",
       "else if (c->arrestLevel == 3)"),
    _m("say-chatter", "c->boolParam != 0 ? 128 : 4", "c->boolParam == 1 ? 128 : 4"),
    _m("say-rbset", "        if (RBL == 0)\n            spch_add_event_v(172",
       "        if (RBL == 1)\n            spch_add_event_v(172"),
    _m("say-left", "        if (RBL == 0)\n            spch_add_event_v(174",
       "        if (RBL == 1)\n            spch_add_event_v(174"),
    _m("say-right", "        if (RBL == 0)\n            spch_add_event_v(175",
       "        if (RBL == 1)\n            spch_add_event_v(175"),
    _m("say-set", "        if (RBL == 0)\n            spch_add_event_v(173",
       "        if (RBL == 1)\n            spch_add_event_v(173"),

    # update.
    _m("up-off", "    if (speech_off())\n        return;\n    w = ",
       "    w = "),
    _m("up-wedge", "    playing = w != NULL && w->status",
       "    playing = w == NULL || w->status"),
    _m("up-paused", "w->status != SEDWEDGE_PAUSED\n", "1\n"),
    _m("up-idle", "&& w->status != SEDWEDGE_IDLE;", ";"),
    _m("up-radio-test",
       "        if (!speechnoise_is_radio_noise(speechnoise_get_instance()))\n"
       "            speechnoise_start_radio_noise",
       "        speechnoise_start_radio_noise"),
    _m("up-radio-on",
       "            speechnoise_start_radio_noise(speechnoise_get_instance());\n",
       ""),
    _m("up-sp-playing", "        m->previousSedPlaybackState = 1;\n        return;",
       "        m->previousSedPlaybackState = 0;\n        return;"),
    _m("up-return", "        m->previousSedPlaybackState = 1;\n        return;",
       "        m->previousSedPlaybackState = 1;"),
    _m("up-off-test",
       "    if (speechnoise_is_radio_noise(speechnoise_get_instance())) {\n",
       "    if (1) {\n"),
    _m("up-radio-off",
       "    if (speechnoise_is_radio_noise(speechnoise_get_instance())) {\n"
       "        speechnoise_stop_radio_noise(speechnoise_get_instance());\n",
       "    if (speechnoise_is_radio_noise(speechnoise_get_instance())) {\n"),
    _m("up-heli-off",
       "        speechnoise_stop_helicopter_noise(speechnoise_get_instance());\n"
       "    }\n    if (m->state",
       "    }\n    if (m->state"),
    _m("up-ready", "    if (m->state != SPEECH_STATE_READY) {",
       "    if (m->state > SPEECH_STATE_DISPATCH_CONFIRM) {"),
    _m("up-event1", "fsm_handle_event(m, 1, &m->contexts[m->currContext]);",
       "fsm_handle_event(m, 2, &m->contexts[m->currContext]);"),
    _m("up-curr-ctx", "fsm_handle_event(m, 1, &m->contexts[m->currContext]);",
       "fsm_handle_event(m, 1, &m->contexts[0]);"),
    _m("up-sp-mid", "fsm_handle_event(m, 1, &m->contexts[m->currContext]);\n"
       "        m->previousSedPlaybackState = 1;",
       "fsm_handle_event(m, 1, &m->contexts[m->currContext]);\n"
       "        m->previousSedPlaybackState = 0;"),
    _m("up-empty-full", "} else if (!m->full && m->read == m->write) {",
       "} else if (m->read == m->write) {"),
    _m("up-empty-rw", "} else if (!m->full && m->read == m->write) {",
       "} else if (!m->full) {"),
    _m("up-sp0", "        m->previousSedPlaybackState = 0;\n    } else {",
       "        m->previousSedPlaybackState = 1;\n    } else {"),
    _m("up-read-wrap", "m->read = m->read + 1 == SPEECHMGR_QUEUE ? 0 : m->read + 1;",
       "m->read = m->read + 1 == SPEECHMGR_QUEUE ? 1 : m->read + 1;"),
    _m("up-read", "        m->read = m->read + 1 == SPEECHMGR_QUEUE ? 0 : m->read + 1;\n",
       ""),
    _m("up-full0", "        m->full = 0;\n        m->currContext", "        m->currContext"),
    _m("up-curr", "        m->currContext = e.contextNum;\n", ""),
    _m("up-pop-ctx", "fsm_handle_event(m, e.event, &m->contexts[e.contextNum]);",
       "fsm_handle_event(m, e.event, &m->contexts[0]);"),
    _m("up-pop-ev", "fsm_handle_event(m, e.event, &m->contexts[e.contextNum]);",
       "fsm_handle_event(m, 1, &m->contexts[e.contextNum]);"),
    _m("up-sp-pop", "&m->contexts[e.contextNum]);\n        m->previousSedPlaybackState = 1;",
       "&m->contexts[e.contextNum]);\n        m->previousSedPlaybackState = 0;"),

    # The race coordinator's states.
    _m("off-null", "    if (rc == NULL)\n        return 0;",
       "    if (rc == NULL)\n        return 1;"),
    _m("off-4", "return s == RCSTATE_INSTANT_REPLAY ||",
       "return s == RCSTATE_PAUSE ||"),
    _m("off-7", "|| s == RCSTATE_POSTRACE\n", "|| s == RCSTATE_PRERACE\n"),
    _m("off-5", "|| s == RCSTATE_AUTO_REPLAY\n", "|| s == RCSTATE_AI_DEMO_MODE\n"),
    _m("off-demo", "|| racecoordinator_is_replay_demo_mode(rc);", ";"),

    # FlushQueue.
    _m("fl-state", "    m->state = SPEECH_STATE_READY;\n    m->full = 0;\n"
       "    m->write = m->read;", "    m->full = 0;\n    m->write = m->read;"),
    _m("fl-full", "    m->full = 0;\n    m->write = m->read;",
       "    m->write = m->read;"),
    _m("fl-write", "    m->write = m->read;", "    m->read = m->write;"),
    _m("fl-radio", "    m->write = m->read;\n"
       "    speechnoise_stop_radio_noise(speechnoise_get_instance());\n",
       "    m->write = m->read;\n"),
    _m("fl-heli", "    speechnoise_stop_helicopter_noise(speechnoise_get_instance());\n"
       "    w = sedwedge_sound_instance();\n    if (w != NULL)\n"
       "        sedwedge_clear_event_queue(w);",
       "    w = sedwedge_sound_instance();\n    if (w != NULL)\n"
       "        sedwedge_clear_event_queue(w);"),
    _m("fl-clear", "    if (w != NULL)\n        sedwedge_clear_event_queue(w);",
       "    if (w == NULL)\n        sedwedge_clear_event_queue(w);"),

    # AllocateVoices, fade, Mute.
    _m("alloc-gone", "    (void)m;\n    speechcontext_shuffle_cop_ids();",
       "    (void)m;"),
    _m("fade-gone", "        sedwedge_fade(w, level);", "        ;"),
    _m("fade-level", "        sedwedge_fade(w, level);",
       "        sedwedge_fade(w, 1.0f);"),
    _m("fade-null", "    (void)m;\n    if (w != NULL)\n        sedwedge_fade",
       "    (void)m;\n    if (w == NULL)\n        sedwedge_fade"),
    _m("mute-on", "sedwedge_mute(w, on != 0);", "sedwedge_mute(w, on == 0);"),
    _m("mute-null", "    (void)m;\n    if (w != NULL)\n        sedwedge_mute",
       "    (void)m;\n    if (w == NULL)\n        sedwedge_mute"),

    # pushSpeechEvent and getNextContext.
    _m("push-off", "    if (speech_off())\n        return;\n    if (m->full)",
       "    if (m->full)"),
    _m("push-full", "    if (m->full)\n        return;\n", ""),
    _m("push-event", "m->queue[m->write].event = event;",
       "m->queue[m->write].event = event + 1;"),
    _m("push-ctx", "m->queue[m->write].contextNum = m->nextContext;",
       "m->queue[m->write].contextNum = 0;"),
    _m("push-wrap", "m->write = m->write + 1 == SPEECHMGR_QUEUE ? 0 : m->write + 1;",
       "m->write = m->write + 1 == SPEECHMGR_QUEUE ? 1 : m->write + 1;"),
    _m("push-full-set", "m->full = m->write == m->read;", "m->full = 0;"),
    _m("push-next", "m->nextContext = m->nextContext + 1 == SPEECHMGR_CONTEXTS\n",
       "m->nextContext = m->nextContext + 1 == 3\n"),
    _m("push-next-gone",
       "    m->nextContext = m->nextContext + 1 == SPEECHMGR_CONTEXTS\n"
       "                     ? 0 : m->nextContext + 1;\n", ""),
    _m("next-ctx", "    return &m->contexts[m->nextContext];",
       "    return &m->contexts[m->currContext];"),

    # The constructor.
    _m("ct-full", "    m->full = 0;\n    m->read = 0;", "    m->full = 1;\n    m->read = 0;"),
    _m("ct-read", "    m->read = 0;\n    m->write = 0;", "    m->read = 1;\n    m->write = 0;"),
    _m("ct-write", "    m->write = 0;\n    m->previousSedPlaybackState = 0;",
       "    m->write = 1;\n    m->previousSedPlaybackState = 0;"),
    _m("ct-sp", "    m->previousSedPlaybackState = 0;\n    m->state",
       "    m->previousSedPlaybackState = 1;\n    m->state"),
    _m("ct-state", "    m->state = SPEECH_STATE_READY;\n    m->nextContext = 0;",
       "    m->state = SPEECH_STATE_DISPATCH_CONFIRM;\n    m->nextContext = 0;"),
    _m("ct-next", "    m->state = SPEECH_STATE_READY;\n    m->nextContext = 0;",
       "    m->state = SPEECH_STATE_READY;\n    m->nextContext = 2;"),

    # speechContext_t.
    _m("id-range", "return unit < 4 ? table[unit] : 0;",
       "return unit < 3 ? table[unit] : 0;"),
    _m("id-past", "return unit < 4 ? table[unit] : 0;",
       "return unit < 4 ? table[unit] : 1;"),
    _m("id-cop", "    return id_of(gCopIdTable, c->copUnitId);",
       "    return id_of(gFromIdTable, c->copUnitId);"),
    _m("id-tcop", "    return id_of(gCopIdTable, c->copTargetUnitId);",
       "    return id_of(gCopIdTable, c->copUnitId);"),
    _m("id-from", "    return id_of(gFromIdTable, c->copUnitId);",
       "    return id_of(gFromIdTable, c->copTargetUnitId);"),
    _m("id-tfrom", "    return id_of(gFromIdTable, c->copTargetUnitId);",
       "    return id_of(gCopIdTable, c->copTargetUnitId);"),
    _m("id-to", "    return id_of(gToIdTable, c->copUnitId);",
       "    return id_of(gToIdTable, c->copTargetUnitId);"),
    _m("id-tto", "    return id_of(gToIdTable, c->copTargetUnitId);",
       "    return id_of(gCopIdTable, c->copTargetUnitId);"),
    _m("sh-n", "    while (n >= 2) {", "    while (n >= 3) {"),
    _m("sh-range", "bRandomI((int32_t)n, bViewSeed);",
       "bRandomI((int32_t)n - 1, bViewSeed);"),
    _m("sh-swap", "        a[0] = a[r];\n", ""),
    _m("sh-swap2", "        a[r] = t;\n", ""),
    _m("sh-step", "        n--;\n        a++;", "        n--;"),
    _m("sh-cop0", "    gCopIdTable[0] = 2;", "    gCopIdTable[0] = 1;"),
    _m("sh-cop3", "    gCopIdTable[3] = 32;", "    gCopIdTable[3] = 16;"),
    _m("sh-cop-n", "    shuffle_array(gCopIdTable, 4);",
       "    shuffle_array(gCopIdTable, 3);"),
    _m("sh-from", "uint32_t from[6] = { 1, 2, 4, 8, 16, 32 };",
       "uint32_t from[6] = { 1, 2, 4, 8, 16, 64 };"),
    _m("sh-from-n", "    shuffle_array(from, 6);", "    shuffle_array(from, 4);"),
    _m("sh-order", "    shuffle_array(gCopIdTable, 4);\n    shuffle_array(from, 6);",
       "    shuffle_array(from, 6);\n    shuffle_array(gCopIdTable, 4);"),
    _m("sh-fromtab", "        gFromIdTable[i] = from[i];",
       "        gFromIdTable[i] = from[i + 2];"),
    _m("sh-totab", "        gToIdTable[i] = from[i];",
       "        gToIdTable[i] = from[3 - i];"),

    # ConvertSpeed.
    _m("cv-low", "    if (speed < 100.0f)\n        return 0;",
       "    if (speed <= 100.0f)\n        return 0;"),
    _m("cv-low0", "    if (speed < 100.0f)\n        return 0;",
       "    if (speed < 100.0f)\n        return 1;"),
    _m("cv-high", "    if (340.0f < speed)\n        return 4096;",
       "    if (340.0f <= speed)\n        return 4096;"),
    _m("cv-high-v", "    if (340.0f < speed)\n        return 4096;",
       "    if (340.0f < speed)\n        return 8192;"),
    _m("cv-base", "x = (speed - 100.0f) * 0.05f;", "x = (speed - 99.0f) * 0.05f;"),
    _m("cv-k", "x = (speed - 100.0f) * 0.05f;", "x = (speed - 100.0f) / 20.0f;"),
    _m("cv-nan", "    if (x != x)\n        return 1;", "    if (x != x)\n        return 0;"),
]

EQUIVALENT = {
    "fsm-order":
        "the action is handed only the context, never the manager, so "
        "whether the state changes before or after it is the same",
    "cv-high":
        "at 340 itself, (340 - 100) * 0.05 is 12.0, and 1 << 12 is the "
        "4096 the test returns",
    "cv-k":
        "(speed - 100) * 0.05f and / 20.0f round alike over 0 .. 240, "
        "the only range that reaches them; both truncate to the same "
        "whole number",
}


for _tab in ("kDispatchOrSuperConfirm", "kRoadblockRequest2",
             "kSpikeStripRequest2", "kUpdateReckless2", "kRotorRequest2",
             "kCopBreakingPursuit"):
    EQUIVALENT["t-%s-1-cond" % _tab] = (
        "the first transition's condition is the supervisor test the "
        "second's is not (isSupervisorActive or its ^ 1), so the second "
        "is reached only when its own condition holds; C_NULL, or the "
        "other test, is the same there")


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines = script()
    scp = write_script(indir.name, lines)
    base = model_cached(lines)
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
    result = mutpar.run_pass(
        todo, SOURCES, "speechmgr_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, result)


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
    got, e = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL,
                                           encoding="latin-1")
        d.with_suffix(".harness").write_text(NL.join(harness) + NL,
                                             encoding="latin-1")

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
