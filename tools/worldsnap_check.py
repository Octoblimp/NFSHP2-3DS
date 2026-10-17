#!/usr/bin/env python3
"""Cross-check TASKS 72d-2, the top of the replay's snapshot, against the
retail image, SLES_507.31: World's and RaceCoordinator's DoSnapshots, the
cops', the smokeables' and the collision bodies'.

**What is checked**: World::DoSnapshot (0x0014d148),
RaceCoordinator::DoSnapshot (0x001498f0), SnapshotCops (0x00227cd8),
SnapshotAllSmokeables (0x0021fb30), Smokeable's (0x002208a0) and
VirginSmokeable's (0x00220128) DoSnapshots, and the SnapshotEverythings of
TrackPolygonCollisionBody (0x001d8980), CollisionBody (0x001d6e70) and
CollisionBodyWitness (0x001d6208). Each is taken, restored over other
values, checksummed and verified. A source check holds smokeable.c's two
tables to the new DoSnapshots in slot 16.

**The layouts** are the port's headers, parsed by carsnap_check.py (which
this imports and extends); World's few fields are listed here by hand. The
harness, tools/src/worldsnap_test.c, gets the same field list as a
generated table of offsetof and sizeof, so each side writes and dumps a
field at its own offset, and a pointer prints as the object and field it
points into.

**The model** is retail's own code in retail_model.RetailEmu. Run real on
both sides: ReplaySnapshot and the nine functions above. Recorded on both
sides, as lines both print: every snapshot they reach that another task
checks (the clock's, the teleporter's, the track graph's, the cars', the
cops', the chopper's, the race's, the players', the static and dynamic
bodies', the rigid body's and the witnesses'), the restore's flushes and
resets, the pools' allocations, the constructors and CreateSmokeable, the
lookups (spawner, spawner index, info, body), WorldObject::GetNameHash, and
the bodies' own tables through a recording table whose slot 208
(GetSmokeType) answers a value. The globals are set by ops of their own on
both sides.

What the linked port files reach outside that is stubbed by
tools/src/worldsnap_stubs.c and worldsnap_stubdata.c, which `--stubs`
writes from the link's undefined symbols; each stubbed function stops the
run with an UNREACHED line.

    python tools/worldsnap_check.py
    python tools/worldsnap_check.py --stubs
    python tools/worldsnap_check.py --fields [CLASS]
    python tools/worldsnap_check.py --mutate [--only a,b] [--jobs N]
    python tools/worldsnap_check.py --dump out/worldsnap
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
from carsnap_check import (fill, fl, i32, i16, i8, cycle, flatten,  # noqa
                           alloc_size, fnv)
from mipsemu import M32                 # noqa: E402

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
HARNESS = ROOT / "tools" / "src" / "worldsnap_test.c"
STUBS = ROOT / "tools" / "src" / "worldsnap_stubs.c"
STUBDATA = ROOT / "tools" / "src" / "worldsnap_stubdata.c"

_S = "3DS Files/source/"
PORT = [_S + f for f in (
    "replay.c", "p32.c", "vtable.c", "bticker.c",
    "worldsnap.c", "smokesnap.c", "bodysnap.c")]

GP = retail_model.RETAIL_GP
P_CURRENT_WORLD = GP - 22120
P_CURRENT_RACE = GP - 22272
PLAYER_NUM = GP - 20920
PLAYERS_BY_INDEX = GP - 20928
RESET_GLARE = GP - 23564
THE_TRACK_GRAPH = GP - 14840
P_COP_MANAGER = GP - 15620
BODY_LIST = csc.COLLISION_BODY_LIST     # gp-17792
WITNESS_LIST = GP - 17752
TP_POOL = GP - 17712
WITNESS_POOL = GP - 17704
AWAKE_SMOKEABLES = GP - 15864
SPAWNERS = GP - 15860
VIRGIN_POOL = GP - 15872
COLLISION_STATS = csc.COLLISION_STATS   # 0x00319e90
TOPOLOGY_TREE = 0x002f9498
WORLD_EFFECTS = 0x002ef640

VPTR = 80                               # every body's vptr
WORLDOBJECT = 1008                      # Smokeable's TheWorldObject

# ================================================================ the layout

csc.HEADERS.update({
    "SmokeableInfo": "smokeable.h", "SmokeableSpawner": "smokeable.h",
    "VirginSmokeable": "smokeable.h", "Smokeable": "smokeable.h",
    "TopologyTreePolygon": "topology.h", "TrackPolygon": "topology.h",
})
csc.TYPES["TrackPolygonNormal"] = (12, True)
csc.SKIP_TYPES.update({"WorldObject", "RigidBodyInfo", "TrackListNode"})

# World by hand: what its DoSnapshot reads and writes, and the float it
# skips. TimeScaleCallback moves as four raw bytes, so a host pointer stays
# NULL; it is a pointer here.
csc.RETAIL_SIZE["World"] = 416
csc._flat["World"] = (
    [csc.Field("Helicopter", 24, 4, "ptr"),
     csc.Field("TotalNumCars", 28, 4, "raw")] +
    [csc.Field("CarTable[%d]" % i, 44 + 4 * i, 4, "ptr") for i in range(14)] +
    [csc.Field("PlayerPositions[0]", 336, 16, "raw", True),
     csc.Field("PlayerPositions[1]", 352, 16, "raw", True),
     csc.Field("PlayerDATs", 368, 8, "raw", True),
     csc.Field("WorldRandomSeed", 376, 4, "raw"),
     csc.Field("fTimeToRemainPaused", 380, 4, "raw", True),
     csc.Field("PreviousTimeToWaste", 384, 4, "raw", True),
     csc.Field("fTimeScale", 388, 4, "raw", True),
     csc.Field("fTimeScaleTimer", 392, 4, "raw", True),
     csc.Field("TimeScaleCallback", 396, 4, "ptr"),
     csc.Field("TimeScaleCallbackParam", 400, 4, "raw"),
     csc.Field("Teleporter", 404, 4, "ptr"),
     csc.Field("CollisionPredictionID", 408, 4, "raw"),
     csc.Field("PotentialDriveTargetID", 412, 4, "raw")])

# The records a script can make, in the order of the generated table.
CLASSES = ["World", "SmokeableSpawner", "SmokeableInfo", "CollisionBody",
           "VirginSmokeable", "Smokeable", "TopologyTreePolygon",
           "TrackPolygon", "TrackPolygonCollisionBody",
           "CollisionBodyWitness"]

# What each pool's allocation makes.
POOLS = {"vpool": ("V", "VirginSmokeable"),
         "tppool": ("T", "TrackPolygonCollisionBody"),
         "witpool": ("W", "CollisionBodyWitness")}

# ============================================================ the scenarios


def body(ref, path, typ, bid):
    return ["vt|%s|%s_vtable|rec" % (ref, path),
            "set|%s|%sType|%s" % (ref, path, i8(typ)),
            "set|%s|%sID|%s" % (ref, path, i16(bid))]


def sc_setup():
    out = ["# setup", "newb|vpool|16", "newb|tppool|16", "newb|witpool|16",
           "pools|vpool|tppool|witpool",
           "new|spw|SmokeableSpawner|6", "spawners|spw",
           "new|si|SmokeableInfo|3", "new|sic|SmokeableInfo",
           "infos|si[0],si[1],si[2]",
           "new|polys|TopologyTreePolygon|8", "polytable|polys",
           "new|tpl|TrackPolygon|4", "newb|rb|64", "newb|rb2|64"]
    for i in range(6):
        out += fill("spw[%d]" % i, "SmokeableSpawner", "s")
    for r in ("si[0]", "si[1]", "si[2]", "sic"):
        out += fill(r, "SmokeableInfo", "s")
    for i in range(8):
        out += fill("polys[%d]" % i, "TopologyTreePolygon", "s")
    for i, p in enumerate((5, 0, 7, 2)):
        out += fill("tpl[%d]" % i, "TrackPolygon", "s")
        out += ["link|tpl[%d]|pPolygon|polys[%d]|-" % (i, p)]
    return out


def sc_virgin():
    fix = ["link|vs|pSmokeableSpawner|spw[2]|-"]
    out = ["# virginsmokeable", "new|vs|VirginSmokeable"]
    out += fill("vs", "VirginSmokeable", "a") + fix
    out += cycle(["call|virgin|vs"], ["dump|vs"],
                 fill("vs", "VirginSmokeable", "b") + fix)
    return out


def sc_smokeable():
    out = []
    # A spawner, none, and one back over none.
    for k, (sp, rsp) in enumerate((("spw[3]", "spw[0]"), ("0", "spw[5]"),
                                   ("spw[5]", "0"))):
        sm = "sm%d" % k
        links = ["vt|%s|Dynamic.Body._vtable|rec" % sm,
                 "link|%s|SI|sic|-" % sm,
                 "link|%s|Dynamic.pBody|%s|-" % (sm, ("rb", "rb2", "0")[k])]
        out += ["# smokeable %d" % k, "new|%s|Smokeable" % sm]
        out += fill(sm, "Smokeable", "a%d" % k) + links + \
            ["link|%s|pSmokeableSpawner|%s|-" % (sm, sp)]
        refill = fill(sm, "Smokeable", "b%d" % k) + \
            ["link|%s|pSmokeableSpawner|%s|-" % (sm, rsp)]
        change = ("set|sic|NameHash|" + i32(0x5eed0000 + k),
                  "set|%s|Dynamic.Body.BBoxMin|%s" % (sm, fl(0.5, -1.5)),
                  "set|%s|Dynamic.Body.BBoxMax|%s" % (sm, fl(8.0, 2.25)))[k]
        out += cycle(["call|smokeable|" + sm], ["dump|" + sm, "dump|sic"],
                     refill, [change])
    return out


def sc_allsmokeables():
    out = ["# allsmokeables", "new|av|VirginSmokeable|3",
           "new|asm|Smokeable|3", "new|atp|TrackPolygonCollisionBody",
           "new|acb|CollisionBody"]
    for i, sp in enumerate((1, 4, 0)):
        out += fill("av[%d]" % i, "VirginSmokeable", "a")
        out += body("av[%d]" % i, "Static.Body.", 2, -2 - i)
        out += ["link|av[%d]|pSmokeableSpawner|spw[%d]|-" % (i, sp)]
    for i, (bid, info) in enumerate(((300, "si[1]"), (-2, "sic"),
                                     (17, "si[0]"))):
        out += fill("asm[%d]" % i, "Smokeable", "a")
        out += body("asm[%d]" % i, "Dynamic.Body.", 1, bid)
        out += ["link|asm[%d]|SI|%s|-" % (i, info)]
    out += body("atp", "Static.Body.", 3, 40) + body("acb", "", 0, 3)
    chains = ("av[0],asm[0],atp,av[1],acb,asm[1],av[2],asm[2]",
              "asm[2],acb,av[1]", "-")
    for k, chain in enumerate(chains):
        out += ["# allsmokeables %d" % k, "cbchain|" + chain,
                "setb|awake|0|" + i32((5, -1, 0)[k])]
        out += cycle(["gcall|allsmokeables"], ["dump|awake"],
                     ["setb|awake|0|" + i32(77)],
                     ["setb|awake|0|" + i32(6)])
    return out


def sc_tpbodies():
    out = ["# tpbodies", "new|tpb|TrackPolygonCollisionBody|3"]
    for i, (bid, tp) in enumerate(((4, 2), (-9, 0), (1000, 3))):
        out += fill("tpb[%d]" % i, "TrackPolygonCollisionBody", "a")
        out += body("tpb[%d]" % i, "Static.Body.", 3, bid)
        out += ["link|tpb[%d]|pTP|tpl[%d]|-" % (i, tp)]
    for k, (chain, n) in enumerate((("tpb[0],av[0],tpb[1],acb,tpb[2]", 3),
                                    ("asm[0],tpb[2]", 7), ("-", 0))):
        out += ["# tpbodies %d" % k, "cbchain|" + chain,
                "setb|cstats|20|" + i32(n)]
        out += cycle(["gcall|tpbodies"], ["dump|cstats"],
                     ["setb|cstats|20|" + i32(99)],
                     ["setb|cstats|20|" + i32(n + 1)])
    return out


def sc_bodies():
    out = []
    for k, chain in enumerate(("tpb[0],av[0],asm[1],acb", "-")):
        out += ["# bodies %d" % k, "cbchain|" + chain]
        out += cycle(["gcall|bodies"], ["dump|acb"], [],
                     ["set|acb|ID|" + i16(4)] if k == 0 else [])
        out += ["set|acb|ID|" + i16(3)]
    return out


def sc_witnesses():
    out = ["# witnesses", "new|wb|CollisionBody|4",
           "new|wit|CollisionBodyWitness|3"]
    for i, bid in enumerate((3, 7, 200, -5)):
        out += ["set|wb[%d]|ID|%s" % (i, i16(bid))]
    out += ["btab|wb[0],wb[1],wb[2],wb[3]"]
    for i, (b1, b2) in enumerate(((0, 1), (3, 2), (1, 3))):
        out += fill("wit[%d]" % i, "CollisionBodyWitness", "a")
        out += ["link|wit[%d]|pBody1|wb[%d]|-" % (i, b1),
                "link|wit[%d]|pBody2|wb[%d]|-" % (i, b2)]
    for k, (chain, n) in enumerate((("wit[0],wit[1],wit[2]", 3),
                                    ("wit[1]", 0x10001), ("-", 0))):
        out += ["# witnesses %d" % k, "witchain|" + chain,
                "setb|cstats|0|" + i32(n)]
        out += cycle(["gcall|witnesses"], ["dump|cstats"],
                     ["setb|cstats|0|" + i32(42)],
                     ["setb|cstats|0|" + i32(2)])
    return out


def world_links(w, cars, tele, heli):
    out = ["set|%s|TotalNumCars|%s" % (w, i32(len(cars)))]
    for i in range(14):
        out += ["link|%s|CarTable[%d]|%s|-"
                % (w, i, cars[i] if i < len(cars) else "0")]
    return out + ["link|%s|Teleporter|%s|-" % (w, tele),
                  "link|%s|Helicopter|%s|-" % (w, heli)]


def sc_world():
    out = ["# world", "newb|car0|16", "newb|car1|16", "newb|car2|16",
           "newb|tele|16", "newb|heli|16", "newb|tg|16", "newb|cm|16",
           "new|w|World", "new|w2|World"]
    cases = (("w", ["car0", "car1", "car2"], "tele", "heli", "tg", "cm",
              "av[0],tpb[0],asm[0],acb,av[1],tpb[2]", "wit[0],wit[2]"),
             ("w2", [], "0", "0", "0", "0", "-", "-"),
             ("w", ["car2"], "0", "heli", "tg", "0", "asm[2]", "wit[1]"))
    for k, (w, cars, tele, heli, tg, cm, chain, wits) in enumerate(cases):
        keep = ("TotalNumCars",)
        nw = len(wits.split(",")) if wits != "-" else 0
        setup = ["graph|" + tg, "cops|" + cm, "cbchain|" + chain,
                 "witchain|" + wits, "setb|cstats|0|" + i32(nw),
                 "setb|cstats|20|" + i32(2), "setb|awake|0|" + i32(3),
                 "setb|glare|0|" + i32(0)]
        out += ["# world %d" % k] + setup
        out += fill(w, "World", "a%d" % k, keep) + \
            world_links(w, cars, tele, heli)
        out += cycle(["call|world|" + w],
                     ["dump|" + w, "dump|glare", "dump|awake", "dump|cstats"],
                     fill(w, "World", "b%d" % k, keep) +
                     ["setb|glare|0|" + i32(0), "setb|awake|0|" + i32(-4)],
                     ["set|%s|PotentialDriveTargetID|%s" % (w, i32(0x1234))])
    return out


def sc_racecoord():
    out = ["# racecoord", "newb|race0|16", "newb|pl0|16", "newb|pl1|16",
           "curworld|w", "currace|race0", "graph|tg", "cops|cm",
           "cbchain|asm[1],av[2]", "witchain|wit[0]",
           "setb|cstats|0|" + i32(1)]
    out += fill("w", "World", "rc", ("TotalNumCars",)) + \
        world_links("w", ["car1", "car0"], "tele", "0")
    for k, players in enumerate(("pl0", "pl1,pl0", "-")):
        out += ["# racecoord %d" % k, "players|" + players]
        out += cycle(["gcall|racecoord"], ["dump|w"],
                     fill("w", "World", "rcb", ("TotalNumCars",)),
                     ["set|w|WorldRandomSeed|" + i32(k)])
    out += ["# cops"]
    for cm in ("cm", "0"):
        out += ["cops|" + cm]
        out += cycle(["gcall|cops"], [], [])
    return out


def script():
    return (sc_setup() + sc_virgin() + sc_smokeable() + sc_allsmokeables() +
            sc_tpbodies() + sc_bodies() + sc_witnesses() + sc_world() +
            sc_racecoord())


# =================================================================== model

# The retail functions each `call` names, and the ones with no object.
FNS = {"virgin": 0x00220128, "smokeable": 0x002208a0, "world": 0x0014d148}
GFNS = {"allsmokeables": 0x0021fb30, "tpbodies": 0x001d8980,
        "bodies": 0x001d6e70, "witnesses": 0x001d6208, "cops": 0x00227cd8}
F_RACECOORD = 0x001498f0

# The recorded snapshots: (object, snapshot) in a0 and a1, or the snapshot
# alone.
SNAP_STUBS = {
    "teleporter": 0x00222780, "trackgraph": 0x0024e318, "car": 0x00130ff0,
    "copmanager": 0x00223b70, "chopper": 0x001e7d08, "race": 0x001477d0,
    "player": 0x00175db0, "staticbody": 0x001d8760,
    "dynamicbody": 0x001d7050, "rigidbody": 0x0019ca70,
    "cbwitness": 0x001d6168,
}
S_WORLDTIME = 0x001a36c0
# The ones with no arguments.
PLAIN_STUBS = {"flushclans": 0x001ab650, "flushferns": 0x001da1b0,
               "eliminatewitnesses": 0x001d6848,
               "deletesmokeables": 0x0021f508}
S_KILL_EFFECTS = 0x001276a8
S_RESET_SHAKERS = 0x00156480
S_UPDATE_POSITION = 0x001d72f0
S_GET_SPAWNER = 0x0021eff8
S_SPAWNER_INDEX = 0x0021f018
S_NAME_HASH = 0x001cd8a0
S_NEW_VIRGIN = 0x0021fee0
S_FIND_INFO = 0x0021f8f8
S_CREATE_SMOKEABLE = 0x0021ec98
S_NEW_TP_BODY = 0x001d8768
S_FIND_BODY = 0x001d6ee8
S_NEW_WITNESS = 0x001d5e90

s32 = retail_model.s32 if hasattr(retail_model, "s32") else None


def _s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Model(csc.Model):
    def __init__(self):
        csc.Model.__init__(self)
        e = self.e
        for a in (P_CURRENT_WORLD, P_CURRENT_RACE, PLAYER_NUM,
                  PLAYERS_BY_INDEX, PLAYERS_BY_INDEX + 4, THE_TRACK_GRAPH,
                  P_COP_MANAGER, BODY_LIST, BODY_LIST + 4, WITNESS_LIST,
                  WITNESS_LIST + 4, TP_POOL, WITNESS_POOL, VIRGIN_POOL,
                  SPAWNERS, AWAKE_SMOKEABLES, RESET_GLARE,
                  TOPOLOGY_TREE + 16):
            e.put32(a, 0)
        e.write(COLLISION_STATS, bytes(72))
        self.register("witlist", WITNESS_LIST, None, 1, 8, 8)
        self.register("cstats", COLLISION_STATS, None, 1, 72, 72)
        self.register("awake", AWAKE_SMOKEABLES, None, 1, 4, 4)
        self.register("glare", RESET_GLARE, None, 1, 4, 4)
        self.register("fx", WORLD_EFFECTS, None, 1, 4, 4)
        self.made = {"V": 0, "T": 0, "W": 0, "S": 0}
        self.btab = []
        self.infos = []
        # The recording table's GetSmokeType answers.
        e.stub(e.u32(self.vt["rec"] + 208 + 4), self.smoke_type)
        for what, addr in SNAP_STUBS.items():
            e.stub(addr, self.snaprec(what))
        e.stub(S_WORLDTIME, lambda em: self.emit(
            "worldtime s=%s %s" % (self.snaparg(self.arg(0)),
                                   self.where())) or 0)
        for what, addr in PLAIN_STUBS.items():
            e.stub(addr, self.plain(what))
        e.stub(S_KILL_EFFECTS, lambda em: self.emit(
            "killeffects %s %s" % (self.label(self.arg(0)),
                                   self.where())) or 0)
        e.stub(S_RESET_SHAKERS, lambda em: self.emit(
            "resetshakers glare=%d %s" % (_s32(e.u32(RESET_GLARE)),
                                          self.where())) or 0)
        e.stub(S_UPDATE_POSITION, lambda em: self.emit(
            "updateposition %s %s" % (self.label(self.arg(0)),
                                      self.where())) or 0)
        e.stub(S_GET_SPAWNER, self.get_spawner)
        e.stub(S_SPAWNER_INDEX, self.spawner_index)
        e.stub(S_NAME_HASH, self.name_hash)
        e.stub(S_NEW_VIRGIN, self.new_virgin)
        e.stub(S_FIND_INFO, self.find_info)
        e.stub(S_CREATE_SMOKEABLE, self.create_smokeable)
        e.stub(S_NEW_TP_BODY, self.new_tp_body)
        e.stub(S_FIND_BODY, self.find_body)
        e.stub(S_NEW_WITNESS, self.new_witness)

    # ---- the stubs

    def snaprec(self, what):
        def fn(em):
            self.emit("%s %s s=%s %s" % (what, self.label(self.arg(0)),
                                         self.snaparg(self.arg(1)),
                                         self.where()))
            return 0
        return fn

    def plain(self, what):
        def fn(em):
            self.emit("%s %s" % (what, self.where()))
            return 0
        return fn

    def smoke_type(self, em):
        lab = self.label(self.arg(0))
        self.emit("rec vt208 this=%s %s" % (lab, self.where()))
        return fnv(lab.encode("latin-1"))

    def get_spawner(self, em):
        i = _s32(self.arg(0))
        self.emit("getspawner %d %s" % (i, self.where()))
        base = self.e.u32(SPAWNERS)
        return 0 if i < 0 or base == 0 else base + 8 * i

    def spawner_index(self, em):
        p = self.arg(0)
        self.emit("spawnerindex %s %s" % (self.label(p), self.where()))
        if p == 0:
            return M32
        return ((p - self.e.u32(SPAWNERS)) // 8) & M32

    def name_hash(self, em):
        lab = self.label(self.arg(0) - WORLDOBJECT)
        self.emit("namehash %s %s" % (lab, self.where()))
        return fnv(lab.encode("latin-1"))

    def make(self, prefix, cls):
        n = alloc_size(cls)
        a = self.e.alloc(n, align=16)
        self.e.write(a, bytes(n))
        self.register("%s%d" % (prefix, self.made[prefix]), a, cls, 1, n, n)
        self.made[prefix] += 1
        return a

    def omalloc(self, em):
        lab = self.label(self.arg(0))
        self.emit("omalloc %s %s" % (lab, self.where()))
        return self.make(*POOLS[lab])

    def new_virgin(self, em):
        v, sp = self.arg(0), self.arg(1)
        self.emit("newvirgin %s %s %s" % (self.label(v), self.label(sp),
                                          self.where()))
        self.e.put32(v + VPTR, self.vt["rec"])
        return v

    def find_info(self, em):
        h = self.arg(0)
        self.emit("findinfo %08x %s" % (h, self.where()))
        for a in self.infos:
            if self.e.u32(a + 112) == h:
                return a
        return 0

    def create_smokeable(self, em):
        typ, bid, info, h = (self.arg(0), _s32(self.arg(1)), self.arg(2),
                             self.arg(3))
        # The image's word has garbage above the moved byte.
        self.emit("createsmokeable type=%d id=%d info=%s hash=%08x %s"
                  % (typ & 0xff, bid, self.label(info), h, self.where()))
        a = self.make("S", "Smokeable")
        self.e.put32(a + VPTR, self.vt["rec"])
        return a

    def new_tp_body(self, em):
        t, bid, p = self.arg(0), _s32(self.arg(1)), self.arg(2)
        self.emit("newtpbody %s id=%d poly=%s %s" % (
            self.label(t), bid, self.label(p), self.where()))
        self.e.put32(t + VPTR, self.vt["rec"])
        return t

    def find_body(self, em):
        bid = _s32(self.arg(0))
        self.emit("findbody %d %s" % (bid, self.where()))
        for a in self.btab:
            if _s32(self.e.u16(a + 14) << 16) >> 16 == bid:
                return a
        return 0

    def new_witness(self, em):
        w, b1, b2 = self.arg(0), self.arg(1), self.arg(2)
        self.emit("newwitness %s %s %s %s" % (
            self.label(w), self.label(b1), self.label(b2), self.where()))
        return w

    # ---- the script

    def addr(self, r):
        return 0 if r == "0" else self.ref(r)[1]

    def refs(self, s):
        return [] if s == "-" else [self.ref(x)[1] for x in s.split(",")]

    def op(self, a):
        e, S = self.e, self.S
        o = a[0]
        if o in ("cbchain", "witchain"):
            head = BODY_LIST if o == "cbchain" else WITNESS_LIST
            nodes = [head] + self.refs(a[1])
            for k, n in enumerate(nodes):
                e.put32(n, nodes[(k + 1) % len(nodes)])
                e.put32(n + 4, nodes[k - 1])
        elif o == "btab":
            self.btab = self.refs(a[1])
        elif o == "infos":
            self.infos = self.refs(a[1])
        elif o == "pools":
            e.put32(VIRGIN_POOL, self.addr(a[1]))
            e.put32(TP_POOL, self.addr(a[2]))
            e.put32(WITNESS_POOL, self.addr(a[3]))
        elif o == "spawners":
            e.put32(SPAWNERS, self.addr(a[1]))
        elif o == "polytable":
            e.put32(TOPOLOGY_TREE + 16, self.addr(a[1]))
        elif o == "curworld":
            e.put32(P_CURRENT_WORLD, self.addr(a[1]))
        elif o == "currace":
            e.put32(P_CURRENT_RACE, self.addr(a[1]))
        elif o == "players":
            ps = self.refs(a[1])
            e.put32(PLAYER_NUM, len(ps))
            for i in range(2):
                e.put32(PLAYERS_BY_INDEX + 4 * i, ps[i] if i < len(ps) else 0)
        elif o == "graph":
            e.put32(THE_TRACK_GRAPH, self.addr(a[1]))
        elif o == "cops":
            e.put32(P_COP_MANAGER, self.addr(a[1]))
        elif o == "call":
            self.call(FNS[a[1]], self.ref(a[2])[1], S)
        elif o == "gcall":
            if a[1] == "racecoord":
                self.call(F_RACECOORD, 0, S)
            else:
                self.call(GFNS[a[1]], S)
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
                                  "tools/worldsnap_check.py")


def harness_source(d):
    text = HARNESS.read_text(encoding="utf-8")
    marker = "// @FIELDS@"
    assert marker in text
    src = Path(d) / "worldsnap_test.c"
    with open(src, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(text.replace(marker, c_fields()))
    return src


def sources(d, stubs=True):
    out = [str(harness_source(d))]
    if stubs:
        out += [str(STUBS), str(STUBDATA)]
    return out + PORT


def build_harness(tmp, name="worldsnap_test"):
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
                                name="worldsnap_test", quiet=True)
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
    hd = ["// Generated by `tools/worldsnap_check.py --stubs`. Do not edit.",
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
                 "static void worldsnap_unreached(const char *name)", "{",
                 '    printf("UNREACHED %s\\n", name);', "    fflush(stdout);",
                 "    exit(3);", "}", ""]
        body += ['void %s(void) { worldsnap_unreached("%s"); }' % (f, f)
                 for f in funcs]
    else:
        body += ["//", "// None: the harness defines every one.", "",
                 "typedef int worldsnap_stubs_empty;"]
    with open(STUBS, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(hd + body) + NL)
    print("%d data, %d functions stubbed" % (len(data), len(funcs)))


# ======================================================= the source check

def table_check():
    """smokeable.c's Smokeable and VirginSmokeable tables hold the new
    DoSnapshots in slot 16, the third entry."""
    text = (SRC / "smokeable.c").read_text(encoding="utf-8")
    bad = 0
    for table, fn in (("smokeable_vt", "smokeable_do_snapshot"),
                      ("virginsmokeable_vt", "virginsmokeable_do_snapshot")):
        m = re.search(r"static const VtEntry %s\[\w+\] = \{(.*?)\};" % table,
                      text, re.S)
        rows = [r.strip() for r in m.group(1).split(NL)
                if r.strip() and not r.strip().startswith("//")]
        third = rows[2].split("//")[0].strip().rstrip(",")
        if third != "E(%s)" % fn:
            print("%s slot 16 is %s, not E(%s)" % (table, third, fn))
            bad += 1
    return bad


# ============================================================ the mutations

def M(name, rel, before, after):
    return (name, _S + rel, before, after)


MUTATIONS = [
    # -- World --------------------------------------------------------------
    M("w-seed-gone", "worldsnap.c",
      "    ReplaySnapshot_MoveUInt(s, &w->WorldRandomSeed, 4);            // 376\n",
      ""),
    M("w-paused-scale-swapped", "worldsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeToRemainPaused);          // 380\n"
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeScale);                   // 388",
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeScale);                   // 388\n"
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeToRemainPaused);          // 380"),
    M("w-waste-moved", "worldsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeScale);                   // 388",
      "    ReplaySnapshot_MoveFloat(s, &w->PreviousTimeToWaste);"),
    M("w-scaletimer-gone", "worldsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &w->fTimeScaleTimer);              // 392\n",
      ""),
    M("w-callback-gone", "worldsnap.c",
      "    ReplaySnapshot_MoveData(s, (void *)&w->TimeScaleCallback, 4, -1, 0);\n",
      ""),
    M("w-param-short", "worldsnap.c",
      "    ReplaySnapshot_MoveInt(s, &w->TimeScaleCallbackParam, 4);      // 400",
      "    ReplaySnapshot_MoveInt(s, &w->TimeScaleCallbackParam, 2);      // 400"),
    M("w-position-one", "worldsnap.c",
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[1]);         // 352\n",
      ""),
    M("w-positions-swapped", "worldsnap.c",
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[0]);         // 336\n"
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[1]);         // 352",
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[1]);         // 352\n"
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[0]);         // 336"),
    M("w-position-whole", "worldsnap.c",
      "    ReplaySnapshot_MoveVector3(s, &w->PlayerPositions[0]);         // 336",
      "    ReplaySnapshot_MoveData(s, &w->PlayerPositions[0], 16, -1, 0);"),
    M("w-dat-one", "worldsnap.c",
      "    ReplaySnapshot_MoveFloat(s, &w->PlayerDATs[1]);                // 372\n",
      ""),
    M("w-ids-swapped", "worldsnap.c",
      "    ReplaySnapshot_MoveUInt(s, &w->CollisionPredictionID, 4);      // 408\n"
      "    ReplaySnapshot_MoveUInt(s, &w->PotentialDriveTargetID, 4);     // 412",
      "    ReplaySnapshot_MoveUInt(s, &w->PotentialDriveTargetID, 4);     // 412\n"
      "    ReplaySnapshot_MoveUInt(s, &w->CollisionPredictionID, 4);      // 408"),
    M("w-flush-on-take", "worldsnap.c",
      "    if (s->RestoringSnapshotFlag) {\n        if (gFlushClansFn != NULL)",
      "    if (!s->RestoringSnapshotFlag) {\n        if (gFlushClansFn != NULL)"),
    M("w-no-clans", "worldsnap.c",
      "        if (gFlushClansFn != NULL)\n            gFlushClansFn();\n", ""),
    M("w-no-effects", "worldsnap.c",
      "        acid_system_kill_all_active_effects(&WorldEffects);\n", ""),
    M("w-no-ferns", "worldsnap.c",
      "        if (gFlushFernShakersFn != NULL)\n"
      "            gFlushFernShakersFn();\n", ""),
    M("w-no-glare", "worldsnap.c", "        bResetGlare = 1;\n", ""),
    M("w-glare-after", "worldsnap.c",
      "        bResetGlare = 1;\n        reset_camera_shakers();",
      "        reset_camera_shakers();\n        bResetGlare = 1;"),
    M("w-no-shakers", "worldsnap.c", "        reset_camera_shakers();\n", ""),
    M("w-clock-gone", "worldsnap.c", "    WorldTimeDoSnapshot(s);\n", ""),
    M("w-clock-first", "worldsnap.c",
      "    ReplaySnapshot_BeginNamedSection(s, \"World\");\n",
      "    WorldTimeDoSnapshot(s);\n"
      "    ReplaySnapshot_BeginNamedSection(s, \"World\");\n"),
    M("w-teleporter-always", "worldsnap.c",
      "    if (w->Teleporter != NULL)\n", ""),
    M("w-graph-always", "worldsnap.c", "    if (TheTrackGraph != NULL)\n", ""),
    M("w-graph-before-teleporter", "worldsnap.c",
      "    if (w->Teleporter != NULL)\n"
      "        traffic_teleporter_do_snapshot(w->Teleporter, s);\n"
      "    if (TheTrackGraph != NULL)\n"
      "        trackgraph_do_snapshot(TheTrackGraph, s);\n",
      "    if (TheTrackGraph != NULL)\n"
      "        trackgraph_do_snapshot(TheTrackGraph, s);\n"
      "    if (w->Teleporter != NULL)\n"
      "        traffic_teleporter_do_snapshot(w->Teleporter, s);\n"),
    M("w-cars-one-less", "worldsnap.c",
      "    for (i = 0; i < w->TotalNumCars; i++)\n        car_do_snapshot",
      "    for (i = 0; i + 1 < w->TotalNumCars; i++)\n        car_do_snapshot"),
    M("w-cops-gone", "worldsnap.c", "    snapshot_cops(s);\n", ""),
    M("w-chopper-gone", "worldsnap.c",
      "        gChopperDoSnapshotFn(w->Helicopter, s);\n", "        ;\n"),
    M("w-chopper-before-cops", "worldsnap.c",
      "    snapshot_cops(s);\n"
      "    if (w->Helicopter != NULL && gChopperDoSnapshotFn != NULL)\n"
      "        gChopperDoSnapshotFn(w->Helicopter, s);\n",
      "    if (w->Helicopter != NULL && gChopperDoSnapshotFn != NULL)\n"
      "        gChopperDoSnapshotFn(w->Helicopter, s);\n"
      "    snapshot_cops(s);\n"),
    M("w-eliminate-always", "worldsnap.c",
      "    if (s->RestoringSnapshotFlag)\n        cbwitness_eliminate_all();",
      "    cbwitness_eliminate_all();"),
    M("w-eliminate-gone", "worldsnap.c",
      "    if (s->RestoringSnapshotFlag)\n        cbwitness_eliminate_all();",
      "    ;"),
    M("w-smokeables-gone", "worldsnap.c", "    snapshot_all_smokeables(s);\n",
      ""),
    M("w-everythings-swapped", "worldsnap.c",
      "    trackpolygoncollisionbody_snapshot_everything(s);\n"
      "    collisionbody_snapshot_everything(s);\n",
      "    collisionbody_snapshot_everything(s);\n"
      "    trackpolygoncollisionbody_snapshot_everything(s);\n"),
    M("w-witnesses-gone", "worldsnap.c",
      "    cbwitness_snapshot_everything(s);\n", ""),
    M("w-section-early", "worldsnap.c",
      "    cbwitness_snapshot_everything(s);\n    ReplaySnapshot_EndSection(s);",
      "    ReplaySnapshot_EndSection(s);\n    cbwitness_snapshot_everything(s);"),
    M("cops-no-test", "worldsnap.c",
      "    if (pCopManager != NULL && gCopManagerDoSnapshotFn != NULL)",
      "    if (gCopManagerDoSnapshotFn != NULL)"),
    # -- RaceCoordinator ----------------------------------------------------
    M("rc-world-gone", "worldsnap.c",
      "    world_do_snapshot(pCurrentWorld, s);\n", ""),
    M("rc-race-first", "worldsnap.c",
      "    world_do_snapshot(pCurrentWorld, s);\n"
      "    race_do_snapshot(pCurrentRace, s);\n",
      "    race_do_snapshot(pCurrentRace, s);\n"
      "    world_do_snapshot(pCurrentWorld, s);\n"),
    M("rc-players-one", "worldsnap.c",
      "    for (i = 0; i < PlayerNumPlayers; i++)",
      "    for (i = 0; i < PlayerNumPlayers && i < 1; i++)"),
    M("rc-section-early", "worldsnap.c",
      "        player_do_snapshot(PlayerPlayersByIndex[i], s);\n"
      "    ReplaySnapshot_EndSection(s);",
      "        ReplaySnapshot_EndSection(s);\n"
      "    ReplaySnapshot_EndSection(s);"),
    # -- the smokeables -----------------------------------------------------
    M("vs-static-gone", "smokesnap.c",
      "    staticcollisionbody_do_snapshot(b, s);\n", ""),
    M("vs-no-section", "smokesnap.c",
      "    ReplaySnapshot_BeginNamedSection(s, \"VirginSmokeable\");\n"
      "    staticcollisionbody_do_snapshot(b, s);\n"
      "    ReplaySnapshot_EndSection(s);\n",
      "    staticcollisionbody_do_snapshot(b, s);\n"),
    M("sm-dynamic-gone", "smokesnap.c",
      "    dynamiccollisionbody_do_snapshot(b, s);\n", ""),
    M("sm-awake-gone", "smokesnap.c",
      "    ReplaySnapshot_MoveChar(s, &sm->Awake, 1);                     // 1122\n",
      ""),
    M("sm-blinking-gone", "smokesnap.c",
      "    ReplaySnapshot_MoveChar(s, &sm->Blinking, 1);                  // 1123\n",
      ""),
    M("sm-awake-blinking-swapped", "smokesnap.c",
      "    ReplaySnapshot_MoveChar(s, &sm->Awake, 1);                     // 1122\n"
      "    ReplaySnapshot_MoveChar(s, &sm->Blinking, 1);                  // 1123",
      "    ReplaySnapshot_MoveChar(s, &sm->Blinking, 1);                  // 1123\n"
      "    ReplaySnapshot_MoveChar(s, &sm->Awake, 1);                     // 1122"),
    M("sm-hash-moved", "smokesnap.c",
      "    ReplaySnapshot_VerifyUInt(s, &sm->SI->NameHash, 4);            //  272",
      "    ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);"),
    M("sm-strengths-swapped", "smokesnap.c",
      "    ReplaySnapshot_MoveFloat(s, &sm->AnchorStrength);              //  276\n"
      "    ReplaySnapshot_MoveFloat(s, &sm->BreakingStrength);            //  280",
      "    ReplaySnapshot_MoveFloat(s, &sm->BreakingStrength);            //  280\n"
      "    ReplaySnapshot_MoveFloat(s, &sm->AnchorStrength);              //  276"),
    M("sm-timers-in-order", "smokesnap.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeAwoken);       //  288\n"
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeCreated);      //  284",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeCreated);      //  284\n"
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeAwoken);       //  288"),
    M("sm-contact-gone", "smokesnap.c",
      "    ReplaySnapshot_MoveTimer(s, (int32_t *)&sm->TimeLastCarContact); // 292\n",
      ""),
    M("sm-raise-gone", "smokesnap.c",
      "    ReplaySnapshot_MoveFloat(s, &sm->GroundRaise);                 //  300\n",
      ""),
    M("sm-index-byte", "smokesnap.c",
      "        ReplaySnapshot_MoveShort(s, &index, 2);\n"
      "        sm->pSmokeableSpawner",
      "        ReplaySnapshot_MoveShort(s, &index, 1);\n"
      "        sm->pSmokeableSpawner"),
    M("sm-spawner-kept", "smokesnap.c",
      "        sm->pSmokeableSpawner = smokeable_get_spawner(index);      //  296",
      "        (void)smokeable_get_spawner(index);"),
    M("sm-rigid-gone", "smokesnap.c",
      "    rigidbody_do_snapshot((RigidBody *)sm->Dynamic.pBody, s);      //   96\n",
      ""),
    M("sm-update-always", "smokesnap.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        dynamiccollisionbody_update_position",
      "    if (1)\n        dynamiccollisionbody_update_position"),
    M("sm-update-restore-only", "smokesnap.c",
      "    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag)\n"
      "        dynamiccollisionbody_update_position",
      "    if (s->RestoringSnapshotFlag)\n"
      "        dynamiccollisionbody_update_position"),
    M("sm-bbox-one", "smokesnap.c",
      "    ReplaySnapshot_VerifyVector2(s, &b->BBoxMax);                  //   28\n",
      ""),
    M("sm-no-object", "smokesnap.c",
      "    ReplaySnapshot_BeginSection(s, sm, \"Smokeable\");",
      "    ReplaySnapshot_BeginSection(s, NULL, \"Smokeable\");"),
    M("all-awake-gone", "smokesnap.c",
      "    ReplaySnapshot_MoveInt(s, &AwakeSmokeablesCount, 4);\n", ""),
    M("all-no-delete", "smokesnap.c",
      "        delete_smokeable_collision_bodies();\n", ""),
    M("all-virgin-index-byte", "smokesnap.c",
      "            ReplaySnapshot_MoveShort(s, &index, 2);\n"
      "            body_do_snapshot(b, s);",
      "            ReplaySnapshot_MoveShort(s, &index, 1);\n"
      "            body_do_snapshot(b, s);"),
    M("all-virgin-type", "smokesnap.c",
      "            if (b->Type != VIRGIN_SMOKEABLE_COLLISION_BODY)",
      "            if (b->Type != TRACK_POLYGON_COLLISION_BODY)"),
    M("all-virgin-snap-gone", "smokesnap.c",
      "            body_do_snapshot(&v->Static.Body, s);\n", ""),
    M("all-virgin-spawner-off", "smokesnap.c",
      "                &pSmokeableSpawners[index]);",
      "                &pSmokeableSpawners[index + 1]);"),
    M("all-first-end-gone", "smokesnap.c",
      "        ReplaySnapshot_MoveShort(s, &end, 2);\n"
      "        for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {\n"
      "            Smokeable *sm",
      "        for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {\n"
      "            Smokeable *sm"),
    M("all-sm-type", "smokesnap.c",
      "            if (b->Type != SMOKEABLE_COLLISION_BODY)",
      "            if (b->Type == VIRGIN_SMOKEABLE_COLLISION_BODY)"),
    M("all-sm-type-first", "smokesnap.c",
      "            name_hash = worldobject_get_name_hash(&sm->TheWorldObject);\n"
      "            type = body_get_smoke_type(b);",
      "            type = body_get_smoke_type(b);\n"
      "            name_hash = worldobject_get_name_hash(&sm->TheWorldObject);"),
    M("all-sm-id-word", "smokesnap.c",
      "            ReplaySnapshot_MoveUShort(s, &id, 2);\n"
      "            ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);",
      "            ReplaySnapshot_MoveUShort(s, &id, 1);\n"
      "            ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);"),
    M("all-sm-hashes-swapped", "smokesnap.c",
      "            ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);\n"
      "            ReplaySnapshot_MoveUInt(s, &name_hash, 4);",
      "            ReplaySnapshot_MoveUInt(s, &name_hash, 4);\n"
      "            ReplaySnapshot_MoveUInt(s, &sm->SI->NameHash, 4);"),
    M("all-sm-type-short", "smokesnap.c",
      "            ReplaySnapshot_MoveData(s, &type, 1, -1, 0);\n"
      "            body_do_snapshot(b, s);",
      "            ReplaySnapshot_MoveData(s, &type, 2, -1, 0);\n"
      "            body_do_snapshot(b, s);"),
    M("all-sm-snap-gone", "smokesnap.c",
      "            body_do_snapshot(&sm->Dynamic.Body, s);\n", ""),
    M("all-sm-info-hash-swapped", "smokesnap.c",
      "            ReplaySnapshot_MoveUInt(s, &info_hash, 4);\n"
      "            ReplaySnapshot_MoveUInt(s, &name_hash, 4);",
      "            ReplaySnapshot_MoveUInt(s, &name_hash, 4);\n"
      "            ReplaySnapshot_MoveUInt(s, &info_hash, 4);"),
    M("all-sm-create-hash", "smokesnap.c",
      "            sm = smokeable_create(type, id, find_smokeable_info(info_hash),\n"
      "                                  name_hash);",
      "            sm = smokeable_create(type, id, find_smokeable_info(name_hash),\n"
      "                                  info_hash);"),
    # -- the bodies ---------------------------------------------------------
    M("tp-count-moved", "bodysnap.c",
      "    ReplaySnapshot_VerifyInt(\n"
      "        s, &TheCollisionStats.NumTrackPolygonCollisionBodies, 4);",
      "    ReplaySnapshot_MoveInt(\n"
      "        s, &TheCollisionStats.NumTrackPolygonCollisionBodies, 4);"),
    M("tp-type", "bodysnap.c",
      "            if (b->Type != TRACK_POLYGON_COLLISION_BODY)",
      "            if (b->Type == SMOKEABLE_COLLISION_BODY)"),
    M("tp-index-id-swapped", "bodysnap.c",
      "            ReplaySnapshot_MoveUShort(s, &index, 2);\n"
      "            id = (uint16_t)b->ID;\n"
      "            ReplaySnapshot_MoveUShort(s, &id, 2);",
      "            id = (uint16_t)b->ID;\n"
      "            ReplaySnapshot_MoveUShort(s, &id, 2);\n"
      "            ReplaySnapshot_MoveUShort(s, &index, 2);"),
    M("tp-index-byte", "bodysnap.c",
      "            ReplaySnapshot_MoveUShort(s, &index, 2);\n"
      "            id = (uint16_t)b->ID;",
      "            ReplaySnapshot_MoveUShort(s, &index, 1);\n"
      "            id = (uint16_t)b->ID;"),
    M("tp-snap-gone", "bodysnap.c",
      "            ReplaySnapshot_MoveUShort(s, &id, 2);\n"
      "            body_do_snapshot(b, s);",
      "            ReplaySnapshot_MoveUShort(s, &id, 2);"),
    M("tp-end-gone", "bodysnap.c",
      "        }\n        ReplaySnapshot_MoveUShort(s, &end, 2);\n", "        }\n"),
    M("tp-poly-off", "bodysnap.c",
      "            p = &TheTopologyTree.pPolygonTable[index];",
      "            p = &TheTopologyTree.pPolygonTable[index + 1];"),
    M("tp-restore-snap-gone", "bodysnap.c",
      "            body_do_snapshot(&t->Static.Body, s);\n", ""),
    M("cb-verify-moved", "bodysnap.c",
      "        ReplaySnapshot_VerifyUShort(s, &id, 2);",
      "        ReplaySnapshot_MoveUShort(s, &id, 2);"),
    M("cb-verify-byte", "bodysnap.c",
      "        ReplaySnapshot_VerifyUShort(s, &id, 2);",
      "        ReplaySnapshot_VerifyUShort(s, &id, 1);"),
    M("wit-count-word", "bodysnap.c",
      "        ReplaySnapshot_MoveInt(s, &TheCollisionStats.NumCollisionBodyWitnesses,\n"
      "                               2);",
      "        ReplaySnapshot_MoveInt(s, &TheCollisionStats.NumCollisionBodyWitnesses,\n"
      "                               4);"),
    M("wit-restore-count-word", "bodysnap.c",
      "        ReplaySnapshot_MoveInt(s, &n, 2);",
      "        ReplaySnapshot_MoveInt(s, &n, 4);"),
    M("wit-ids-swapped", "bodysnap.c",
      "            ReplaySnapshot_MoveInt(s, &id1, 2);\n"
      "            ReplaySnapshot_MoveInt(s, &id2, 2);\n"
      "            cbwitness_do_snapshot(w, s);",
      "            ReplaySnapshot_MoveInt(s, &id2, 2);\n"
      "            ReplaySnapshot_MoveInt(s, &id1, 2);\n"
      "            cbwitness_do_snapshot(w, s);"),
    M("wit-finds-swapped", "bodysnap.c",
      "            b1 = collisionbody_find(id1);\n"
      "            b2 = collisionbody_find(id2);",
      "            b2 = collisionbody_find(id2);\n"
      "            b1 = collisionbody_find(id1);"),
    M("wit-bodies-swapped", "bodysnap.c",
      "                                   CollisionBodyWitnessSlotPool), b1, b2);",
      "                                   CollisionBodyWitnessSlotPool), b2, b1);"),
    M("wit-snap-gone", "bodysnap.c",
      "            ReplaySnapshot_MoveInt(s, &id2, 2);\n"
      "            cbwitness_do_snapshot(w, s);\n        }\n    }",
      "            ReplaySnapshot_MoveInt(s, &id2, 2);\n        }\n    }"),
    M("wit-one-less", "bodysnap.c",
      "        for (i = 0; i < n; i++) {", "        for (i = 1; i < n; i++) {"),
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
            exe = hostbuild.build(bt, srcs, name="worldsnap_test")
            t0 = time.time()
            run_harness(exe, sc, Path(bt) / "base.txt")
        limit = mutpar.timeout_for(time.time() - t0)
        tally = mutpar.run_pass(
            todo, srcs, "worldsnap_test",
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
