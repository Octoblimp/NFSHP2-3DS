#!/usr/bin/env python3
"""Cross-check TASKS 72e, the cops' part of the replay's snapshot, against
the retail image, SLES_507.31.

**What is checked** (72e-1): DroppedSpikes' (0x001bef90) and Rocket's
(0x001bf910) DoSnapshots, tSpikeStrip's (0x00241898) and the Chopper's
(0x001e7d08). Each is taken, restored over other values, checksummed and
verified. Source checks hold munition.c's DroppedSpikes and Rocket tables
to the new DoSnapshots in slot 16, and main.c to binding the chopper's.

**The layouts** are the port's headers, parsed by carsnap_check.py (which
this imports and extends). The harness, tools/src/copsnap_test.c, gets the
same field list as a generated table of offsetof and sizeof, so each side
writes and dumps a field at its own offset, and a pointer prints as the
object and field it points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot and the four functions above. Recorded on both
sides, as lines both print: Smokeable's snapshot, World's car pointer, the
route manager's route and point pointers, TrackPathCoordinate's snapshot,
the strip's Init and the chopper's RemoveChopperFromWorld and
ClearVariables. The globals are set by ops of their own on both sides.

What the linked port files reach outside that is stubbed by
tools/src/copsnap_stubs.c and copsnap_stubdata.c, which `--stubs` writes
from the link's undefined symbols; each stubbed function stops the run with
an UNREACHED line.

    python tools/copsnap_check.py
    python tools/copsnap_check.py --stubs
    python tools/copsnap_check.py --fields [CLASS]
    python tools/copsnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/copsnap_check.py --dump out/copsnap
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
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import retail_model                     # noqa: E402
from carsnap_check import (fill, fl, i32, cycle, flatten,  # noqa: E402
                           alloc_size, mat)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "copsnap_test.c"
STUBS = ROOT / "tools" / "src" / "copsnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "copsnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in ("replay.c", "p32.c", "copsnap.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
TRACK_ROUTE_MANAGER = 0x00314438

# ================================================================ the layout

csc.HEADERS.update({
    "SmokeableInfo": "smokeable.h", "SmokeableSpawner": "smokeable.h",
    "Smokeable": "smokeable.h", "Munition": "munition.h",
    "DroppedSpikes": "munition.h", "Rocket": "munition.h",
    "tSpikeStrip": "copmanager.h", "Chopper": "chopper.h",
})
csc.TYPES.update({"ChopperPlan": (4, False), "ChopperMoveMode": (4, False),
                  "ChopperAttackType": (4, False)})
csc.SKIP_TYPES.update({"WorldObject", "RigidBodyInfo", "TrackListNode",
                       "tPursuitNode", "tSpikeStripRenderElement"})
csc.RETAIL_SIZE["tSpikeStrip"] = 2304

# The records a script can make, in the order of the generated table.
CLASSES = ["DroppedSpikes", "Rocket", "tSpikeStrip", "Chopper"]

# ============================================================ the scenarios


def sc_spikes():
    out = ["# droppedspikes", "new|ds|DroppedSpikes"]
    for k, (a, b) in enumerate(((1, 0), (0, 1))):
        out += ["# droppedspikes %d" % k]
        out += fill("ds", "DroppedSpikes", "a%d" % k, ("DeploySpikes",))
        out += ["set|ds|DeploySpikes|" + i32(a)]
        out += cycle(["call|spikes|ds"], ["dump|ds"],
                     fill("ds", "DroppedSpikes", "b%d" % k, ("DeploySpikes",))
                     + ["set|ds|DeploySpikes|" + i32(0x100 + b)],
                     ["set|ds|DeploySpikes|" + i32(a ^ 1)])
    return out


def sc_rocket():
    out = ["# rocket", "newb|car0|16", "newb|car1|16", "newb|wld|16",
           "curworld|wld", "new|rk|Rocket"]
    for k, (t, rt) in enumerate((("car0", "car1"), ("0", "car0"),
                                 ("car1", "0"))):
        out += ["# rocket %d" % k]
        out += fill("rk", "Rocket", "a%d" % k)
        out += ["link|rk|Target|%s|-" % t]
        out += cycle(["call|rocket|rk"], ["dump|rk"],
                     fill("rk", "Rocket", "b%d" % k) +
                     ["link|rk|Target|%s|-" % rt],
                     ["set|rk|Yaw|" + fl(-12.5 * (k + 1))])
    out += ["curworld|0", "# rocket, no world"]
    out += cycle(["call|rocket|rk"], ["dump|rk"], fill("rk", "Rocket", "c"))
    return out


def sc_strip():
    out = ["# spikestrip", "new|ss|tSpikeStrip"]
    for k in range(2):
        keep = ("bIsBlinking",)
        out += ["# spikestrip %d" % k]
        out += fill("ss", "tSpikeStrip", "a%d" % k, keep)
        out += ["set|ss|bIsBlinking|" + i32(k)]
        out += cycle(["call|strip|ss"], ["dump|ss"],
                     fill("ss", "tSpikeStrip", "b%d" % k, keep) +
                     ["set|ss|bIsBlinking|" + i32(0x10000 + (k ^ 1))],
                     ["set|ss|nRoadBlockID|" + i32(77 + k)])
    return out


# The pointers a chopper holds: (field, take's, restore's).
CHOPPER_LINKS = (("CurrentCar", "car0", "car1"),
                 ("ChopperRoute", "rt0", "rt1"),
                 ("ChopperPoint", "pt0", "0"),
                 ("TargetRoute", "rt1", "0"),
                 ("TargetPoint", "pt1", "pt2"),
                 ("OldCarRoute", "0", "rt0"),
                 ("OldCarPoint", "pt2", "pt0"))


def sc_chopper():
    out = ["# chopper", "newb|rt0|16", "newb|rt1|16", "newb|pt0|16",
           "newb|pt1|16", "newb|pt2|16", "curworld|wld",
           "new|h|Chopper"]
    # The plan taken, the plan the restore lands on before it reads (its
    # low byte is overwritten), and the matrix's codes.
    cases = ((0, 0x0302, 2, 0), (6, 0, 1, 2), (6, 0x0100, 0, 1),
             (3, 6, 0, 2), (5, 0x0206, 1, 1))
    for k, (plan, rplan, m1, m2) in enumerate(cases):
        keep = ("Plan", "Matrix")
        out += ["# chopper %d" % k]
        out += fill("h", "Chopper", "a%d" % k, keep)
        out += ["set|h|Plan|" + i32(plan), "set|h|Matrix|" + mat(m1)]
        out += ["link|h|%s|%s|-" % (f, a) for f, a, _b in CHOPPER_LINKS]
        refill = fill("h", "Chopper", "b%d" % k, keep)
        refill += ["set|h|Plan|" + i32(rplan),
                   "set|h|Matrix|" + mat(m2, 0.5)]
        refill += ["link|h|%s|%s|-" % (f, b) for f, _a, b in CHOPPER_LINKS]
        out += cycle(["call|chopper|h"], ["dump|h"], refill,
                     ["set|h|GroundZ|" + fl(3.75 + k)])
    return out


def script():
    return sc_spikes() + sc_rocket() + sc_strip() + sc_chopper()


# =================================================================== model

# The retail functions each `call` names.
FNS = {"spikes": 0x001bef90, "rocket": 0x001bf910, "strip": 0x00241898,
       "chopper": 0x001e7d08}

# The recorded snapshots: (object, snapshot) in a0 and a1.
SNAP_STUBS = {"smokeable": 0x002208a0, "tpcoord": 0x00208768}
S_CAR_POINTER = 0x00130910          # World::DoCarPointerSnapshot
S_ROUTE_POINTER = 0x001c2b30        # TrackRouteManager's, TrackRoute **
S_POINT_POINTER = 0x001c2bc8        # TrackRoutePoint **, TrackRoute *
S_STRIP_INIT = 0x002414e8           # tSpikeStrip::Init
S_REMOVE_CHOPPER = 0x001e84a8       # Chopper::RemoveChopperFromWorld
S_CLEAR_VARIABLES = 0x001e7c38      # Chopper::ClearVariables


def _s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        e.put32(P_CURRENT_WORLD, 0)
        self.register("trm", TRACK_ROUTE_MANAGER, None, 1, 4, 4)
        for what, addr in SNAP_STUBS.items():
            e.stub(addr, self.snaprec(what))
        e.stub(S_CAR_POINTER, self.car_pointer)
        e.stub(S_ROUTE_POINTER, self.route_pointer)
        e.stub(S_POINT_POINTER, self.point_pointer)
        e.stub(S_STRIP_INIT, self.strip_init)
        e.stub(S_REMOVE_CHOPPER, self.plain1("removechopper"))
        e.stub(S_CLEAR_VARIABLES, self.plain1("clearvariables"))

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

    def plain1(self, what):
        def fn(em):
            self.emit("%s %s %s" % (what, self.label(self.arg(0)),
                                    self.where()))
            return 0
        return fn

    def car_pointer(self, em):
        self.emit("carptr w=%s pp=%s s=%s %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.snaparg(self.arg(2)), self.where()))
        return 0

    def route_pointer(self, em):
        self.emit("routeptr m=%s s=%s pp=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.where()))
        return 0

    def point_pointer(self, em):
        self.emit("pointptr m=%s s=%s pp=%s route=%s %s" % (
            self.label(self.arg(0)), self.snaparg(self.arg(1)),
            self.label(self.arg(2)), self.label(self.arg(3)), self.where()))
        return 0

    def strip_init(self, em):
        self.emit("stripinit %s a=%s b=%s id=%d life=%08x %s" % (
            self.label(self.arg(0)), self.label(self.arg(1)),
            self.label(self.arg(2)), _s32(self.arg(3)),
            self.e.fpr[12] & M32, self.where()))
        return 0

    # ---- the script

    def addr(self, r):
        return 0 if r == "0" else self.ref(r)[1]

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o == "curworld":
            e.put32(P_CURRENT_WORLD, self.addr(a[1]))
        elif o == "call":
            self.call(FNS[a[1]], self.ref(a[2])[1], S)
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
                                  "tools/copsnap_check.py")


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "copsnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="copsnap_test"):
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
                                name="copsnap_test", quiet=True)
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
    hd = ["// Generated by `tools/copsnap_check.py --stubs`. Do not edit.",
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
                 "static void copsnap_unreached(const char *name)", "{",
                 '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
                 "    exit(3);", "}", ""]
        body += ['void %s(void) { copsnap_unreached("%s"); }' % (f, f)
                 for f in funcs]
    else:
        body += ["//", "// None: the harness defines every one.", "",
                 "typedef int copsnap_stubs_empty;"]
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + body) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ======================================================= the source checks

def table_check():
    """munition.c's DroppedSpikes and Rocket tables hold the new
    DoSnapshots in slot 16, and main.c binds the chopper's."""
    text = (SRC / "munition.c").read_text(encoding="utf-8")
    bad = 0
    for table, fn in (("droppedspikes_vt", "droppedspikes_do_snapshot"),
                      ("rocket_vt", "rocket_do_snapshot")):
        m = re.search(r"static const VtEntry %s\[\w+\] =\s*MUNITION_VT\("
                      r"\s*\w+,\s*(\w+)," % table, text)
        if not m or m.group(1) != fn:
            print("%s slot 16 is %s, not %s"
                  % (table, m.group(1) if m else "?", fn))
            bad += 1
    main = (SRC / "main.c").read_text(encoding="utf-8")
    if not re.search(r"^\s*gChopperDoSnapshotFn\s*=\s*chopper_do_snapshot;",
                     main, re.M):
        print("main.c does not bind gChopperDoSnapshotFn")
        bad += 1
    return bad


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


def gone(name, needle, rel="copsnap.c"):
    return M(name, rel, L(rel, needle), "")


def swap(name, n1, n2, rel="copsnap.c"):
    a, c = L(rel, n1), L(rel, n2)
    return M(name, rel, a + c, c + a)


def sub(name, needle, before, after, rel="copsnap.c"):
    line = L(rel, needle)
    assert line.count(before) == 1, (name, before)
    return M(name, rel, line, line.replace(before, after))


MUTATIONS = [
    # -- DroppedSpikes ------------------------------------------------------
    sub("ds-section-noobj", '"DroppedSpikes"',
        "BeginSection(s, d, ", "BeginSection(s, NULL, "),
    sub("ds-section-name", '"DroppedSpikes"', '"DroppedSpikes"', '"Spikes"'),
    gone("ds-deploy-gone", "&d->DeploySpikes"),
    sub("ds-deploy-wide", "&d->DeploySpikes", "DeploySpikes, 1)",
        "DeploySpikes, 4)"),
    M("ds-smokeable-first", "copsnap.c",
      L("copsnap.c", "&d->DeploySpikes") + "    smokeable_do_snapshot(b, s);" + NL,
      "    smokeable_do_snapshot(b, s);" + NL + L("copsnap.c", "&d->DeploySpikes")),
    M("ds-smokeable-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// The yaw",
      "    ReplaySnapshot_EndSection(s);\n}\n\n// The yaw"),
    M("ds-end-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// The yaw",
      "    smokeable_do_snapshot(b, s);\n}\n\n// The yaw"),
    # -- Rocket -------------------------------------------------------------
    sub("rk-section-noobj", '"Rocket"', "BeginSection(s, r, ",
        "BeginSection(s, NULL, "),
    gone("rk-yaw-gone", "&r->Yaw"),
    gone("rk-target-gone", "&r->Target"),
    swap("rk-target-first", "&r->Yaw", "&r->Target"),
    sub("rk-world-null", "&r->Target", "pCurrentWorld", "NULL"),
    M("rk-smokeable-gone", "copsnap.c",
      "    smokeable_do_snapshot(b, s);\n    ReplaySnapshot_EndSection(s);\n}"
      "\n\n// ---",
      "    ReplaySnapshot_EndSection(s);\n}\n\n// ---"),
    # -- tSpikeStrip --------------------------------------------------------
    sub("ss-section-name", '"tSpikeStrip"', '"tSpikeStrip"', '"SpikeStrip"'),
    gone("ss-start-gone", "MoveVector2(s, &t->v2Start)"),
    swap("ss-ends-swapped", "MoveVector2(s, &t->v2Start)",
         "MoveVector2(s, &t->v2End)"),
    sub("ss-id-short", "MoveInt(s, &t->nRoadBlockID", "nRoadBlockID, 4)",
        "nRoadBlockID, 2)"),
    gone("ss-life-gone", "MoveFloat(s, &t->fLifetime)"),
    M("ss-init-taking", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)" + NL + "        tspikestrip_init(",
      "    if (s->TakingSnapshotFlag)" + NL + "        tspikestrip_init("),
    M("ss-init-always", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)\n        tspikestrip_init(",
      "    if (1)\n        tspikestrip_init("),
    sub("ss-init-ends-swapped", "tspikestrip_init(t,",
        "&t->v2Start, &t->v2End", "&t->v2End, &t->v2Start"),
    sub("ss-init-id", "tspikestrip_init(t,", "t->nRoadBlockID", "0"),
    M("ss-init-life", "copsnap.c",
      "                         t->fLifetime);",
      "                         t->fBlinkTimer);"),
    gone("ss-blink-gone", "&t->bIsBlinking"),
    sub("ss-blink-wide", "&t->bIsBlinking", "bIsBlinking, 1)",
        "bIsBlinking, 4)"),
    M("ss-blink-before-init", "copsnap.c",
      L("copsnap.c", "MoveFloat(s, &t->fLifetime)") +
      "    if (s->RestoringSnapshotFlag)\n"
      "        tspikestrip_init(t, &t->v2Start, &t->v2End, t->nRoadBlockID,\n"
      "                         t->fLifetime);\n" +
      L("copsnap.c", "&t->bIsBlinking"),
      L("copsnap.c", "MoveFloat(s, &t->fLifetime)") +
      L("copsnap.c", "&t->bIsBlinking") +
      "    if (s->RestoringSnapshotFlag)\n"
      "        tspikestrip_init(t, &t->v2Start, &t->v2End, t->nRoadBlockID,\n"
      "                         t->fLifetime);\n"),
    gone("ss-timer-gone", "&t->fBlinkTimer"),
    # -- Chopper ------------------------------------------------------------
    sub("ch-section-name", '"Chopper"', '"Chopper"', '"Helicopter"'),
    M("ch-remove-taking", "copsnap.c",
      "    if (s->RestoringSnapshotFlag)" + NL + "        chopper_remove_from_world(",
      "    if (s->TakingSnapshotFlag)" + NL + "        chopper_remove_from_world("),
    gone("ch-remove-gone", "chopper_remove_from_world(h);"),
    sub("ch-plan-wide", "&h->Plan", "Plan, 1, -1, 0)", "Plan, 4, -1, 0)"),
    sub("ch-plan-whole-word", "&h->Plan", "Plan, 1, -1, 0)", "Plan, 1, 4, 0)"),
    sub("ch-donuts-5", "CHOPPLAN_EATING_DONUTS", "CHOPPLAN_EATING_DONUTS",
        "CHOPPLAN_END_CHASE"),
    sub("ch-donuts-byte", "CHOPPLAN_EATING_DONUTS", "h->Plan ==",
        "(uint8_t)h->Plan =="),
    sub("ch-clear-taking-only", "s->TakingSnapshotFlag || s->Restoring",
        " || s->RestoringSnapshotFlag", ""),
    sub("ch-clear-restoring-only", "s->TakingSnapshotFlag || s->Restoring",
        "s->TakingSnapshotFlag || ", ""),
    sub("ch-clear-checksum", "s->TakingSnapshotFlag || s->Restoring",
        "s->TakingSnapshotFlag", "s->TakingChecksumFlag"),
    gone("ch-clear-gone", "chopper_clear_variables(h);"),
    M("ch-donuts-no-end", "copsnap.c",
      "            chopper_clear_variables(h);\n"
      "        ReplaySnapshot_EndNamedSection(s);\n",
      "            chopper_clear_variables(h);\n"),
    gone("ch-think-gone", "&h->TimeUntilThink"),
    gone("ch-car-gone", "&h->CurrentCar"),
    sub("ch-car-world-null", "&h->CurrentCar", "pCurrentWorld", "NULL"),
    gone("ch-movemode-gone", "&h->MoveMode"),
    sub("ch-movemode-wide", "&h->MoveMode", "MoveMode, 1, -1", "MoveMode, 4, -1"),
    gone("ch-route-gone", "&h->ChopperRoute)"),
    sub("ch-point-target-route", "h->ChopperRoute);     //  740",
        "h->ChopperRoute", "h->TargetRoute"),
    sub("ch-targetpoint-null-route", "h->TargetRoute);      //  748",
        "h->TargetRoute", "NULL"),
    sub("ch-route-target", "&h->ChopperRoute)", "&h->ChopperRoute",
        "&h->TargetRoute"),
    gone("ch-oldroute-gone", "&h->OldCarRoute)"),
    M("ch-oldpoint-gone", "copsnap.c",
      "    trmgr_do_point_pointer_snapshot_in_route(m, s, &h->OldCarPoint,\n"
      "                                             h->OldCarRoute);      //  800\n",
      ""),
    gone("ch-tp-gone", "trackpath_coord_do_snapshot(&h->TP, s);"),
    swap("ch-tp-after-pos", "trackpath_coord_do_snapshot(&h->TP, s);",
         "&h->CurrentPos"),
    gone("ch-pos-gone", "&h->CurrentPos"),
    gone("ch-matrix-gone", "&h->Matrix"),
    gone("ch-speed-gone", "&h->Speed"),
    gone("ch-accel-gone", "&h->Acceleration"),
    swap("ch-rolls-swapped", "&h->Roll)", "&h->DesiredRoll)"),
    gone("ch-yaw-gone", "&h->Yaw"),
    swap("ch-pitches-swapped", "&h->Pitch)", "&h->DesiredPitch)"),
    gone("ch-rotrate-gone", "&h->RotRate"),
    gone("ch-zvel-gone", "&h->ZVelocity"),
    gone("ch-groundz-gone", "&h->GroundZ"),
    gone("ch-dust-gone", "&h->EmitDust"),
    sub("ch-dust-wide", "&h->EmitDust", "EmitDust, 1)", "EmitDust, 4)"),
    gone("ch-targetdist-gone", "&h->TargetDistance"),
    swap("ch-targetdist-before-dust", "&h->EmitDust", "&h->TargetDistance"),
    gone("ch-bombrun-gone", "&h->BombRunType"),
    sub("ch-bombrun-wide", "&h->BombRunType", "BombRunType, 1, -1",
        "BombRunType, 4, -1"),
    sub("ch-salvos-short", "&h->NumSalvosReleased",
        "NumSalvosReleased, 4)", "NumSalvosReleased, 2)"),
    gone("ch-nextsalvo-gone", "&h->TimeUntilNextSalvo"),
    gone("ch-launcher-gone", "&h->NextLauncher"),
    gone("ch-timeout-gone", "&h->Timeout"),
    swap("ch-timeout-stuck-swapped", "&h->Timeout", "&h->StuckTime"),
    gone("ch-total-gone", "&h->TotalSalvos"),
    sub("ch-total-short", "&h->TotalSalvos", "TotalSalvos, 4)",
        "TotalSalvos, 2)"),
    M("ch-end-gone", "copsnap.c",
      L("copsnap.c", "&h->TotalSalvos") +
      "    ReplaySnapshot_EndNamedSection(s);\n",
      L("copsnap.c", "&h->TotalSalvos")),
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
            exe = hostbuild.build(bt, srcs, name="copsnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "copsnap_test",
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
