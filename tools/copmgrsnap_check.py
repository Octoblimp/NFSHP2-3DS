#!/usr/bin/env python3
"""Cross-check TASKS 72e-3, tCopManager::DoSnapshot (0x00223b70), against the
retail image, SLES_507.31.

**What is checked**: copmgrsnap.c's copmanager_do_snapshot, taken, restored
over other values, checksummed and verified, with every part it moves: the
three counts it verifies, the roadblocks' and radar traps' cops a restore
empties, the pursuit list (a count and the ids; a restore deletes every
pursuit and makes one for each id), each cop's snapshot through its table,
the spike strip list (a count; a restore destroys every strip and makes
each again), the pullovers, the chopper's flag, the speakers' ring, the
timers up to the world's CopCarPos, Be A Cop's damage and time, and Be A
Cop's counts. A source check holds main.c to binding it to
gCopManagerDoSnapshotFn.

**The layouts** are the port's headers, parsed by carsnap_check.py, with
copsnap_check.py's records (which this imports) and the manager's own. The
harness, tools/src/copmgrsnap_test.c, gets the same field list as a
generated table of offsetof and sizeof, so each side writes and dumps a
field at its own offset, and a pointer prints as the object and field it
points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot and the function. Recorded on both sides, as
lines both print: tPursuit's and tSpikeStrip's snapshots; tPlayerCop's
and tAICop's (slot 32 of the tables at 0x002bd6c0 and 0x002bd698, which
the harness installs at those addresses); tSpikeStrip's destructor (slot 8
of 0x002be688); DeletePursuit (0x00224560), which unlinks the pursuit;
NewPursuit (0x002244e0), which makes a pursuit `P<n>` with the id at the
list's tail; bOMalloc (0x00257c80), which makes a strip `S<n>`; and the
strip's default constructor (0x00241308), which sets its table. The
globals -- pCurrentWorld's CopCarPos, TheRaceParameters.BeACop and
SpikeStripSlotPool -- are set by ops of their own on both sides.

What the linked port files reach outside that is stubbed by
tools/src/copmgrsnap_stubs.c and copmgrsnap_stubdata.c, which `--stubs`
writes from the link's undefined symbols; each stubbed function stops the
run with an UNREACHED line.

    python tools/copmgrsnap_check.py
    python tools/copmgrsnap_check.py --stubs
    python tools/copmgrsnap_check.py --fields [CLASS]
    python tools/copmgrsnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/copmgrsnap_check.py --dump out/copmgrsnap
"""
import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carsnap_check as csc             # noqa: E402
import copsnap_check as cpc             # noqa: E402  (the cops' records)
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import retail_model                     # noqa: E402
from carsnap_check import (fill, fl, i32, i8, cycle, flatten,  # noqa: E402
                           alloc_size)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "copmgrsnap_test.c"
STUBS = ROOT / "tools" / "src" / "copmgrsnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "copmgrsnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in ("replay.c", "p32.c", "copmgrsnap.c", "vtable.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
SPIKE_STRIP_POOL = GP - 15636
BEACOP = 0x0031a898 + 628           # TheRaceParameters.BeACop
TPURSUIT_SIZE = 1600
TSPIKESTRIP_SIZE = 2304
WORLD_SIZE = 64

TPLAYERCOP_VT = 0x002bd6c0
TAICOP_VT = 0x002bd698
TSPIKESTRIP_VT = 0x002be688

# ================================================================ the layout

csc.HEADERS.update({
    "tCopManager": "copmanager.h", "tCarPulloverInfo": "copmanager.h",
    "CopSpeakerDeque": "copmanager.h", "tPursuitNode": "copmanager.h",
})
# The lists' links are fields here: a pursuit's and a strip's Node, the
# manager's two heads.
csc.SKIP_TYPES.discard("tPursuitNode")
csc.MACROS.update({"COPMANAGER_MAX_COPS": 7, "COPMANAGER_MAX_PURSUITS": 6,
                   "COPMANAGER_NUM_PULLOVERS": 8,
                   "COPMANAGER_MAX_ROADBLOCKS": 64,
                   "COPMANAGER_MAX_SPEEDTRAPS": 64,
                   "COPMANAGER_NUM_CARS": 14})
csc.RETAIL_SIZE.update({"tCopManager": 10516, "tCarPulloverInfo": 28,
                        "CopSpeakerDeque": 28, "tRoadBlock": 120,
                        "tSpeedTrap": 28, "tPursuitNode": 8})
csc._flat.clear()

# The records a script can make, in the order of the generated table.
CLASSES = ["tCopManager", "tCop", "tPursuit", "tSpikeStrip"]

# ============================================================ the scenarios

# What a case's fill leaves alone: the counts and the ring it sets itself,
# and the arrays the setup filled once.
MGR_KEEP = ("nNumCops", "nNumRoadBlocks", "nNumSpeedTraps", "CopSpeakers",
            "RoadBlocks", "SpeedTraps", "RealRoadBlockIndexFromDataIndex",
            "RealSpeedTrapIndexFromDataIndex")

COPS = (("pc", TPLAYERCOP_VT), ("ac0", TAICOP_VT), ("ac1", TAICOP_VT),
        ("ac2", TAICOP_VT))


def sc_setup():
    out = ["# copmanager", "newb|pool|16", "spool|pool",
           "new|cm|tCopManager"]
    out += fill("cm", "tCopManager", "init",
                ("nNumCops", "nNumRoadBlocks", "nNumSpeedTraps",
                 "CopSpeakers"))
    for ref, vt in COPS:
        out += ["new|%s|tCop" % ref, "set|%s|vptr|%s" % (ref, i32(vt))]
    for ref in ("pa", "pb", "pc2", "pd"):
        out += ["new|%s|tPursuit" % ref]
    for ref in ("sa", "sb", "sc"):
        out += ["new|%s|tSpikeStrip" % ref,
                "set|%s|vptr|%s" % (ref, i32(TSPIKESTRIP_VT))]
    return out


def chain(lst, items):
    """The manager's list `lst` made of `items`, both ways round."""
    nodes = [("cm", lst)] + [(r, "-") for r in items]
    out = []
    for k, (o, _p) in enumerate(nodes):
        nx, pv = nodes[(k + 1) % len(nodes)], nodes[k - 1]
        f = lst + "." if o == "cm" else "Node."
        out += ["link|%s|%sNext|%s|%s" % (o, f, nx[0], nx[1]),
                "link|%s|%sPrev|%s|%s" % (o, f, pv[0], pv[1])]
    return out


def speakers(data, head, tail, full):
    return ["set|cm|CopSpeakers.Data|" + "".join(i32(v) for v in data),
            "set|cm|CopSpeakers.Head|" + i32(head),
            "set|cm|CopSpeakers.Tail|" + i32(tail),
            "set|cm|CopSpeakers.Full|" + i32(full)]


# One side of a case: the pursuits (ref, id or None), the strips, the
# cops in Cops and how many count, the roadblock and radar trap counts with
# the cops held one past them, the ring, CopCarPos and BeACop.
class Side(object):
    def __init__(self, pur, strips, cops, ncops, nrb, nst, spk, ccp,
                 beacop, rbcop=("ac0", "ac1"), stcop="ac2"):
        self.pur, self.strips, self.cops, self.ncops = pur, strips, cops, ncops
        self.nrb, self.nst, self.spk, self.ccp = nrb, nst, spk, ccp
        self.beacop, self.rbcop, self.stcop = beacop, rbcop, stcop

    def lines(self):
        out = []
        for ref, pid in self.pur:
            if pid is not None:
                out += ["set|%s|nPursuitId|%s" % (ref, i8(pid))]
        out += chain("PursuitList", [r for r, _ in self.pur])
        out += chain("SpikeStripList", self.strips)
        for i in range(7):
            c = self.cops[i] if i < len(self.cops) else "0"
            out += ["link|cm|Cops[%d]|%s|-" % (i, c)]
        out += ["set|cm|nNumCops|" + i32(self.ncops),
                "set|cm|nNumRoadBlocks|" + i32(self.nrb),
                "set|cm|nNumSpeedTraps|" + i32(self.nst)]
        for i in range(min(self.nrb + 1, 64)):
            for j in range(2):
                out += ["link|cm|RoadBlocks[%d].cops[%d]|%s|-"
                        % (i, j, self.rbcop[j])]
        for i in range(min(self.nst + 1, 64)):
            out += ["link|cm|SpeedTraps[%d].cop|%s|-" % (i, self.stcop)]
        out += speakers(*self.spk)
        out += ["world|%d" % self.ccp, "beacop|%d" % self.beacop]
        return out


# (take, restore over, the change before the last verify)
CASES = (
    (Side([("pa", 0), ("pb", 3), ("pc2", 5)], ["sa", "sb"],
          ["pc", "ac0", "ac1", "ac2"], 3, 2, 3, ([9, 4, 2, 7], 1, 3, 0), 3, 1),
     Side([("pd", None)], ["sc"], ["ac1", "pc", "ac0"], 3, 2, 3,
          ([11, 12, 13, 14], 2, 0, 1), 3, 1, ("pc", "ac2"), "ac0"),
     ["set|cm|bChopperBusy|" + i32(0x55)]),
    (Side([], [], ["pc"], 0, 0, 0, ([1, 2, 3, 4], 2, 2, 0), 0, 0),
     Side([("pa", None), ("pb", None)], ["sa", "sb", "sc"], ["pc"], 0, 0, 0,
          ([5, 5, 5, 5], 3, 1, 0), 0, 0, ("ac2", "pc"), "pc"),
     ["set|cm|nBeACopNumArrestsMade|" + i32(77)]),
    (Side([("pb", -1), ("pa", 2)], ["sc"], ["ac2", "pc", "ac1", "ac0"], 4,
          64, 64, ([1, 2, 3, 4], 0, 0, 1), 8, 2),
     Side([], [], ["ac2", "pc", "ac1", "ac0"], 4, 64, 64,
          ([7, 8, 9, 10], 1, 1, 1), 8, 2, ("ac1", "ac0"), "pc"),
     ["set|cm|CopSpeakers.Head|" + i32(2)]),
    (Side([("pc2", 4)], ["sb", "sa", "sc"], ["ac1"], 1, 5, 1,
          ([1, 5, 0, 5], 3, 2, 0), 5, 1),
     Side([("pc2", None)], ["sb"], ["ac1"], 1, 5, 1,
          ([3, 3, 3, 3], 0, 3, 0), 5, 1, ("pc", "pc"), "ac1"),
     ["set|cm|fBeACopTime|" + fl(1.5)]),
    (Side([("pd", 1), ("pa", 0), ("pb", 5), ("pc2", 2)], ["sa"],
          ["pc", "ac0"], 2, 1, 2, ([2, 0, 1, 3], 2, 1, 0), 7, 0),
     Side([("pd", None), ("pa", None)], ["sa", "sb"], ["pc", "ac0"], 2, 1, 2,
          ([4, 4, 4, 4], 3, 3, 0), 7, 0, ("ac2", "ac2"), "ac1"),
     ["set|cm|CarPullovers[3].fHoldTimer|" + fl(2.25)]),
)


def sc_cases():
    out = []
    dumps = ["dump|cm", "lists|cm"]
    for k, (a, b, change) in enumerate(CASES):
        out += ["# case %d" % k]
        out += fill("cm", "tCopManager", "a%d" % k, MGR_KEEP)
        out += a.lines()
        refill = fill("cm", "tCopManager", "b%d" % k, MGR_KEEP) + b.lines()
        out += cycle(["call|copmanager|cm"], dumps, refill, change)
    return out


def script():
    return sc_setup() + sc_cases()


# =================================================================== model

F_SNAPSHOT = 0x00223b70             # tCopManager::DoSnapshot

# The recorded snapshots: (object, snapshot) in a0 and a1.
SNAP_STUBS = {"pursuit": 0x0022a548, "strip": 0x00241898,
              "playercopsnap": 0x0022d7e8, "aicopsnap": 0x0022dd20}
S_STRIP_DTOR = 0x00241430           # _$_11tSpikeStrip, slot 8
S_STRIP_CTOR = 0x00241308           # tSpikeStrip::tSpikeStrip(void)
S_DELETE_PURSUIT = 0x00224560       # tCopManager::DeletePursuit
S_NEW_PURSUIT = 0x002244e0          # tCopManager::NewPursuit


def _s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        e.put32(P_CURRENT_WORLD, 0)
        e.put32(SPIKE_STRIP_POOL, 0)
        e.put32(BEACOP, 0)
        self.world = 0
        self.np = self.ns = 0
        for what, addr in SNAP_STUBS.items():
            e.stub(addr, self.snaprec(what))
        e.stub(S_STRIP_DTOR, self.strip_dtor)
        e.stub(S_STRIP_CTOR, self.strip_ctor)
        e.stub(S_DELETE_PURSUIT, self.delete_pursuit)
        e.stub(S_NEW_PURSUIT, self.new_pursuit)

    def where(self):
        # The section, and where the data stands: a move swapped with a
        # recorded call shows only there.
        return "%s at=%d" % (csc.Model.where(self),
                             _s32(self.e.u32(self.S + 336)))

    # ---- the stubs

    def snaprec(self, what):
        def fn(em):
            self.emit("%s %s s=%s %s" % (what, self.label(self.arg(0)),
                                         self.snaparg(self.arg(1)),
                                         self.where()))
            return 0
        return fn

    def strip_dtor(self, em):
        self.emit("stripdtor %s flags=%d %s" % (
            self.label(self.arg(0)), _s32(self.arg(1)), self.where()))
        return 0

    def strip_ctor(self, em):
        a = self.arg(0)
        self.emit("stripctor %s %s" % (self.label(a), self.where()))
        self.e.put32(a + 2288, TSPIKESTRIP_VT)
        return a

    def delete_pursuit(self, em):
        e = self.e
        p = self.arg(1)
        self.emit("delpursuit m=%s p=%s %s" % (self.label(self.arg(0)),
                                               self.label(p), self.where()))
        nx, pv = e.u32(p), e.u32(p + 4)
        e.put32(pv, nx)
        e.put32(nx + 4, pv)
        return 0

    def new_pursuit(self, em):
        e = self.e
        m, pid, car = self.arg(0), _s32(self.arg(1)), self.arg(2)
        a = e.alloc(TPURSUIT_SIZE, align=16)
        e.write(a, bytes(TPURSUIT_SIZE))
        name = "P%d" % self.np
        self.np += 1
        self.register(name, a, "tPursuit", 1, TPURSUIT_SIZE, TPURSUIT_SIZE)
        e.mem[a + 1480] = pid & 0xff
        head = m + 44
        prev = e.u32(head + 4)
        e.put32(a, head)
        e.put32(a + 4, prev)
        e.put32(prev, a)
        e.put32(head + 4, a)
        self.emit("newpursuit m=%s id=%d car=%s -> %s %s" % (
            self.label(m), pid, self.label(car), name, self.where()))
        return a

    def omalloc(self, em):
        # bOMalloc, 0x00257c80: carsnap's model stubs it, and calls this.
        e = self.e
        a = e.alloc(TSPIKESTRIP_SIZE, align=16)
        e.write(a, bytes(TSPIKESTRIP_SIZE))
        name = "S%d" % self.ns
        self.ns += 1
        self.register(name, a, "tSpikeStrip", 1, TSPIKESTRIP_SIZE,
                      TSPIKESTRIP_SIZE)
        self.emit("omalloc pool=%s -> %s %s" % (self.label(self.arg(0)),
                                                name, self.where()))
        return a

    # ---- the script

    def walk(self, what, head, ids):
        e = self.e
        parts = []
        n, k = e.u32(head), 0
        while n != head and k < 16:
            if ids:
                parts.append("%s/%d" % (self.label(n),
                                        (e.mem[n + 1480] ^ 0x80) - 0x80))
            else:
                parts.append(self.label(n))
            n, k = e.u32(n), k + 1
        self.emit("%s f:%s%s" % (what, "".join(" " + x for x in parts),
                                 " ..." if n != head else ""))
        parts = []
        n, k = e.u32(head + 4), 0
        while n != head and k < 16:
            parts.append(self.label(n))
            n, k = e.u32(n + 4), k + 1
        self.emit("%s b:%s%s" % (what, "".join(" " + x for x in parts),
                                 " ..." if n != head else ""))

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "spool":
            e.put32(SPIKE_STRIP_POOL, self.ref(a[1])[1])
        elif o == "world":
            if not self.world:
                self.world = e.alloc(WORLD_SIZE, align=16)
                e.write(self.world, bytes(WORLD_SIZE))
                self.register("wld", self.world, None, 1, WORLD_SIZE,
                              WORLD_SIZE)
            e.put32(self.world + 36, int(a[1]) & M32)
            e.put32(P_CURRENT_WORLD, self.world)
        elif o == "beacop":
            e.put32(BEACOP, int(a[1]) & M32)
        elif o == "lists":
            base = self.ref(a[1])[1]
            self.walk("plist", base + 44, True)
            self.walk("slist", base + 80, False)
        elif o == "call":
            assert a[1] == "copmanager", a
            self.call(F_SNAPSHOT, self.ref(a[2])[1], S)
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
                                  "tools/copmgrsnap_check.py")


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "copmgrsnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="copmgrsnap_test"):
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
                                name="copmgrsnap_test", quiet=True)
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


find_extern = cpc.find_extern


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
    hd = ["// Generated by `tools/copmgrsnap_check.py --stubs`. Do not edit.",
          "//"]
    with open(STUBDATA, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + [
            "// The data the linked port files name and nothing linked "
            "defines,", "// zero."] + [""] +
            ['#include "%s"' % h for h in sorted(heads)] + [""] + data) + NL)
    body = ["// The functions the linked port files call and nothing linked",
            "// defines: each stops the run, which the transcript shows."]
    if funcs:
        body += ["", "#include <stdio.h>", "#include <stdlib.h>", "",
                 "static void copmgrsnap_unreached(const char *name)", "{",
                 '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
                 "    exit(3);", "}", ""]
        body += ['void %s(void) { copmgrsnap_unreached("%s"); }' % (f, f)
                 for f in funcs]
    else:
        body += ["//", "// None: the harness defines every one.", "",
                 "typedef int copmgrsnap_stubs_empty;"]
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + body) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ======================================================= the source checks

def table_check():
    """main.c binds the manager's snapshot."""
    main = (SRC / "main.c").read_text(encoding="utf-8")
    if not re.search(r"^\s*gCopManagerDoSnapshotFn\s*=\s*"
                     r"copmanager_do_snapshot;", main, re.M):
        print("main.c does not bind gCopManagerDoSnapshotFn")
        return 1
    return 0


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


_texts = {}


def L(rel, needle):
    """The whole line of `rel` holding `needle`, with its newline; there
    must be one."""
    if rel not in _texts:
        _texts[rel] = (SRC / rel).read_text(encoding="utf-8")
    lines = [ln for ln in _texts[rel].splitlines(True) if needle in ln]
    assert len(lines) == 1, (rel, needle, len(lines))
    return lines[0]


def gone(name, needle, rel="copmgrsnap.c"):
    return M(name, rel, L(rel, needle), "")


def swap(name, n1, n2, rel="copmgrsnap.c"):
    a, c = L(rel, n1), L(rel, n2)
    return M(name, rel, a + c, c + a)


def sub(name, needle, before, after, rel="copmgrsnap.c"):
    line = L(rel, needle)
    assert line.count(before) == 1, (name, before)
    return M(name, rel, line, line.replace(before, after))


F = "copmgrsnap.c"

MUTATIONS = [
    # -- the section and the counts -----------------------------------------
    sub("cm-section-noobj", '"tCopManager"', "BeginSection(s, m, ",
        "BeginSection(s, NULL, "),
    sub("cm-section-name", '"tCopManager"', '"tCopManager"', '"CopManager"'),
    gone("cm-verify-aicops-gone", "&m->nNumAICops"),
    sub("cm-verify-aicops-move", "&m->nNumAICops", "VerifyInt", "MoveInt"),
    sub("cm-verify-rb-short", "&m->nNumRoadBlocks, 4)", "Blocks, 4)",
        "Blocks, 1)"),
    gone("cm-verify-traps-gone", "VerifyInt(s, &m->nNumSpeedTraps"),
    swap("cm-verify-order", "VerifyInt(s, &m->nNumRoadBlocks",
         "VerifyInt(s, &m->nNumSpeedTraps"),
    # -- a restore empties the roadblocks' and the traps' cops ---------------
    M("cm-clear-taking", F,
      "    if (s->RestoringSnapshotFlag) {\n"
      "        for (i = 0; i < m->nNumRoadBlocks; i++) {\n",
      "    if (s->TakingSnapshotFlag) {\n"
      "        for (i = 0; i < m->nNumRoadBlocks; i++) {\n"),
    M("cm-clear-always", F,
      "    if (s->RestoringSnapshotFlag) {\n"
      "        for (i = 0; i < m->nNumRoadBlocks; i++) {\n",
      "    if (1) {\n"
      "        for (i = 0; i < m->nNumRoadBlocks; i++) {\n"),
    sub("cm-clear-rb-le", "for (i = 0; i < m->nNumRoadBlocks; i++)",
        "i < m->", "i <= m->"),
    sub("cm-clear-rb-count", "for (i = 0; i < m->nNumRoadBlocks; i++)",
        "nNumRoadBlocks", "nNumSpeedTraps"),
    gone("cm-clear-rb0-gone", "m->RoadBlocks[i].cops[0] = NULL;"),
    gone("cm-clear-rb1-gone", "m->RoadBlocks[i].cops[1] = NULL;"),
    sub("cm-clear-rb-twice-0", "m->RoadBlocks[i].cops[1] = NULL;",
        "cops[1]", "cops[0]"),
    sub("cm-clear-st-le", "for (i = 0; i < m->nNumSpeedTraps; i++)",
        "i < m->", "i <= m->"),
    sub("cm-clear-st-count", "for (i = 0; i < m->nNumSpeedTraps; i++)",
        "nNumSpeedTraps", "nNumRoadBlocks"),
    sub("cm-clear-st-gone", "m->SpeedTraps[i].cop = NULL;",
        "m->SpeedTraps[i].cop = NULL;", ";"),
    # -- the pursuits --------------------------------------------------------
    gone("pu-count-gone", "ReplaySnapshot_MoveUChar(s, &npursuits, 1);"),
    sub("lc-from-one", "    int32_t             k = 0;", "k = 0", "k = 1"),
    M("pu-restoring-not-taking", F,
      "    if (s->RestoringSnapshotFlag) {\n        while (pl->Next != pl)\n",
      "    if (!s->TakingSnapshotFlag) {\n        while (pl->Next != pl)\n"),
    M("pu-delete-gone", F,
      "        while (pl->Next != pl)\n"
      "            copmanager_delete_pursuit(m, (tPursuit *)(void *)pl->Next);"
      "\n", ""),
    sub("pu-delete-last-first",
        "copmanager_delete_pursuit(m, (tPursuit *)(void *)pl->Next);",
        "(void *)pl->Next);", "(void *)pl->Prev);"),
    sub("pu-new-le", "for (i = 0; i < npursuits; i++) {", "i < npursuits",
        "i <= npursuits"),
    sub("pu-new-car", "copmanager_new_pursuit(m, id, NULL);", "NULL",
        "(struct Car *)(void *)m"),
    sub("pu-new-unsigned", "copmanager_new_pursuit(m, id, NULL);", "m, id,",
        "m, (uint8_t)id,"),
    M("pu-restore-id-gone", F,
      "            int8_t id;\n\n            ReplaySnapshot_MoveChar(s, &id, 1);"
      "\n            copmanager_new_pursuit",
      "            int8_t id = 0;\n\n            copmanager_new_pursuit"),
    M("pu-take-id-gone", F,
      "// 1480\n\n            ReplaySnapshot_MoveChar(s, &id, 1);\n",
      "// 1480\n\n            (void)id;\n"),
    sub("pu-take-id-field", "int8_t id = ((tPursuit *)(void *)n)->nPursuitId;",
        "nPursuitId", "nNumCops"),
    M("pu-ids-always", F,
      "    } else {\n        for (n = pl->Next; n != pl; n = n->Next) {\n",
      "    }\n    {\n        for (n = pl->Next; n != pl; n = n->Next) {\n"),
    sub("pu-snap-gone", "tpursuit_do_snapshot((tPursuit *)(void *)n, s);",
        "tpursuit_do_snapshot((tPursuit *)(void *)n, s);", "(void)n;"),
    M("pu-snap-not-taking", F,
      "    for (n = pl->Next; n != pl; n = n->Next)\n        tpursuit_do",
      "    for (n = pl->Next; n != pl && !s->TakingSnapshotFlag; n = n->Next)"
      "\n        tpursuit_do"),
    # -- the cops ------------------------------------------------------------
    sub("cops-le", "for (i = 0; i < m->nNumCops; i++) {", "i < m->",
        "i <= m->"),
    sub("cops-from-one", "for (i = 0; i < m->nNumCops; i++) {", "i = 0;",
        "i = 1;"),
    sub("cops-aicops", "for (i = 0; i < m->nNumCops; i++) {", "nNumCops",
        "nNumAICops"),
    sub("cops-slot", "vt_slot(c->vptr, TCOP_VT_SNAPSHOT)", "TCOP_VT_SNAPSHOT",
        "TCOP_VT_THINK"),
    sub("cops-null-snap", "((CopSnapshotFn)e->fn)(vt_this(c, e), s);",
        ", s);", ", NULL);"),
    # -- the spike strips ----------------------------------------------------
    gone("st-count-gone", "ReplaySnapshot_MoveInt(s, &nstrips, 4);"),
    sub("st-count-byte", "ReplaySnapshot_MoveInt(s, &nstrips, 4);",
        "nstrips, 4)", "nstrips, 1)"),
    M("st-restoring-taking", F,
      "    if (s->RestoringSnapshotFlag) {\n        while (sl->Next != sl) {\n",
      "    if (s->TakingSnapshotFlag) {\n        while (sl->Next != sl) {\n"),
    M("st-destroy-gone", F,
      "        while (sl->Next != sl) {\n"
      "            tSpikeStrip   *t = (tSpikeStrip *)(void *)sl->Next;\n"
      "            tPursuitNode  *nx = t->Node.Next, *pv = t->Node.Prev;\n"
      "            const VtEntry *e = vt_slot(t->vptr, TSPIKESTRIP_VT_DTOR);\n"
      "\n            pv->Next = nx;\n            nx->Prev = pv;\n"
      "            ((DtorFn)e->fn)(vt_this(t, e), 3);\n        }\n", ""),
    sub("st-dtor-flags", "((DtorFn)e->fn)(vt_this(t, e), 3);", ", 3);",
        ", 1);"),
    gone("st-unlink-back-gone", "            nx->Prev = pv;"),
    sub("st-make-le", "for (i = 0; i < nstrips; i++) {", "i < nstrips",
        "i <= nstrips"),
    M("st-make-at-tail", F,
      "            tPursuitNode *old = sl->Next;\n\n"
      "            sl->Next = &t->Node;\n"
      "            old->Prev = &t->Node;\n"
      "            t->Node.Next = old;\n"
      "            t->Node.Prev = sl;\n",
      "            tPursuitNode *old = sl->Prev;\n\n"
      "            sl->Prev = &t->Node;\n"
      "            old->Next = &t->Node;\n"
      "            t->Node.Prev = old;\n"
      "            t->Node.Next = sl;\n"),
    gone("st-make-prev-gone", "            t->Node.Prev = sl;"),
    M("st-ctor-skipped", F,
      "            tSpikeStrip  *t = tspikestrip_construct_default(\n"
      "                (tSpikeStrip *)bSlotOMalloc(SpikeStripSlotPool));\n",
      "            tSpikeStrip  *t =\n"
      "                (tSpikeStrip *)bSlotOMalloc(SpikeStripSlotPool);\n"),
    sub("st-pool-null", "(tSpikeStrip *)bSlotOMalloc(SpikeStripSlotPool));",
        "SpikeStripSlotPool", "NULL"),
    sub("st-snap-gone", "tspikestrip_do_snapshot((tSpikeStrip *)(void *)n, s);",
        "tspikestrip_do_snapshot((tSpikeStrip *)(void *)n, s);", "(void)n;"),
    # -- the pullovers and the chopper ---------------------------------------
    sub("po-four", "for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++) {",
        "COPMANAGER_NUM_PULLOVERS", "4"),
    gone("po-active-gone", "&p->bActive, 1)"),
    swap("po-active-nis", "&p->bActive, 1)", "&p->bPlayNIS, 1)"),
    sub("po-active-busted", "&p->bActive, 1)", "&p->bActive",
        "&p->bShouldDisplayBustedText"),
    sub("po-arrest-wide", "&p->bArrest, 1)", "bArrest, 1)", "bArrest, 4)"),
    gone("po-timer-gone", "&p->fHoldTimer);"),
    swap("po-timer-tickets", "&p->fHoldTimer);", "&p->nNumTickets, 1);"),
    gone("po-tickets-gone", "&p->nNumTickets, 1);"),
    sub("po-copindex-byte", "&p->nCopIndex, 4);", "nCopIndex, 4)",
        "nCopIndex, 1)"),
    swap("po-tickets-copindex", "&p->nNumTickets, 1);", "&p->nCopIndex, 4);"),
    gone("po-chopper-gone", "&m->bChopperBusy, 1)"),
    M("po-chopper-after-speakers", F,
      L(F, "&m->bChopperBusy, 1)") + "\n" + L(F, "speakers_do_snapshot(&m->CopSpeakers"),
      L(F, "speakers_do_snapshot(&m->CopSpeakers") + "\n" + L(F, "&m->bChopperBusy, 1)")),
    # -- the speakers ---------------------------------------------------------
    gone("sp-gone", "speakers_do_snapshot(&m->CopSpeakers, s);"),
    M("sp-restore-full-kept", F,
      "        d->Full = 0;\n        d->Tail = d->Head;\n",
      "        d->Tail = d->Head;\n"),
    M("sp-restore-tail-kept", F,
      "        d->Full = 0;\n        d->Tail = d->Head;\n",
      "        d->Full = 0;\n"),
    sub("sp-restore-stops-at-4", "while (v != 6) {", "v != 6",
        "v != 6 && v != 4"),
    M("sp-restore-falls-through", F,
      "        }\n        return;\n    }\n", "        }\n    }\n"),
    M("sp-restore-no-push", F,
      "        while (v != 6) {\n            push_head(d, v);\n",
      "        while (v != 6) {\n"),
    sub("sp-push-wrap-0", "d->Head = d->Head == 0 ? 3 : d->Head - 1;",
        "? 3 :", "? 0 :"),
    swap("sp-push-order", "d->Head = d->Head == 0 ? 3 : d->Head - 1;",
         "d->Data[d->Head] = v;"),
    sub("sp-push-never-full", "    d->Full = d->Tail == d->Head;",
        "d->Tail == d->Head", "0"),
    sub("sp-front-tail", "front = d->Data[d->Head];", "d->Head", "d->Tail"),
    sub("sp-take-wrap-0", "d->Tail = d->Tail == 0 ? 3 : d->Tail - 1;",
        "? 3 :", "? 0 :"),
    M("sp-take-full-kept", F,
      "                d->Full = 0;\n", ""),
    M("sp-take-no-push", F,
      "            push_head(d, v);\n            ReplaySnapshot_MoveUInt(s, &v, 4);"
      "\n        } while",
      "            ReplaySnapshot_MoveUInt(s, &v, 4);\n        } while"),
    M("sp-take-move-before-push", F,
      "            push_head(d, v);\n            ReplaySnapshot_MoveUInt(s, &v, 4);"
      "\n        } while",
      "            ReplaySnapshot_MoveUInt(s, &v, 4);\n            push_head(d, v);"
      "\n        } while"),
    # -- the timers, Be A Cop's and the last ----------------------------------
    sub("tm-le", "for (i = 0; i < pCurrentWorld->CopCarPos; i++) {", "i < ",
        "i <= "),
    sub("tm-count-cops", "for (i = 0; i < pCurrentWorld->CopCarPos; i++) {",
        "pCurrentWorld->CopCarPos", "m->nNumCops"),
    swap("tm-swapped", "&m->fPursuableTimer[i]);",
         "&m->fSpeedTrapSpawnTimer[i]);"),
    gone("tm-spawn-gone", "&m->fSpeedTrapSpawnTimer[i]);"),
    sub("bc-eq-one", "if (TheRaceParameters.BeACop) {", "BeACop)",
        "BeACop == 1)"),
    sub("bc-inverted", "if (TheRaceParameters.BeACop) {", "(TheRace",
        "(!TheRace"),
    sub("bc-damage-13", "for (i = 0; i < COPMANAGER_NUM_CARS; i++)",
        "COPMANAGER_NUM_CARS", "13"),
    gone("bc-time-gone", "&m->fBeACopTime);"),
    M("bc-time-always", F,
      L(F, "&m->fCarDamage[i]);") + L(F, "&m->fBeACopTime);") + "    }\n",
      L(F, "&m->fCarDamage[i]);") + "    }\n" + L(F, "&m->fBeACopTime);")),
    M("end-said-gone", F,
      L(F, "&m->bBeACopAlreadySaidLookOutForSpeeders,") +
      L(F, "// 10484"), ""),
    sub("end-said-wide", "// 10484", "1);", "4);"),
    gone("end-488-gone", "&m->New10488, 1)"),
    swap("end-roadblocks-attacks", "&m->nBeACopNumRoadBlocks, 4)",
         "&m->nBeACopNumChopperAttacks, 4)"),
    gone("end-roadblocks-gone", "&m->nBeACopNumRoadBlocks, 4)"),
    sub("end-arrests-short", "&m->nBeACopNumArrestsMade, 4)", ", 4)", ", 2)"),
    gone("end-section-gone", "ReplaySnapshot_EndSection(s);"),
]

EQUIVALENT = {
    # Taking, and either checksum, never write into the id: MoveData only
    # reads back on a restore, which returns before the ring is turned, so
    # the push sees the same id on either side of the move.
    "sp-take-move-before-push",
}


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
            exe = hostbuild.build(bt, srcs, name="copmgrsnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "copmgrsnap_test",
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

    bad = table_check()
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
    print("%d script lines, %d model lines, %d harness lines, %d differ; "
          "tables %s" % (len(lines), len(model), len(harness), n,
                         "bad" if bad else "ok"))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
