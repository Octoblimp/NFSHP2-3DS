#!/usr/bin/env python3
"""Cross-check 3DS Files/source/collisionbody.c against CollisionBody.obj in
the image -- the first slice, everything in the object that does not move,
the second, DynamicCollisionBody, CarCollisionBody, and the contacts.

The first is the NumberAllocator, InitCollisionBody and CloseCollisionBody, the
statistics, the CollisionBody base class (its constructor and destructor,
the list sorted on BBoxMax.x, the widest-body bookkeeping, the debug name,
the ID table, the collision flags and the two bounding-box tests),
StaticCollisionBody and its twenty-two virtual methods, the
TrackPolygonCollisionBody built on the tree's polygons, the
CollisionBodyWitness bookkeeping (its constructor and destructor, the pair
bit field, EndCollision, HasExpired, EliminateAllWitnesses and
DoesWitnessExist), IsYawControlInducingCollisionBody, the three virtual
tables and the two static initialisers. The second is DynamicCollisionBody's
constructor and destructor, BuildBoundingVolumes, UpdatePosition, BeginMove,
the two interpolations and Backup, the RigidBody and PhysicsSystem
pass-throughs, GetLocalCollisionBodies, MaybeCreateWitnesses,
CreateTrackPolygonCollisionBodies, TrackPolygonCheck, the inline methods and
its table. CarCollisionBody is carcollisionbody.c: its constructor on the
disc's volume and on the box, its destructor, the pool, the getters, Move,
ApplyImpulse, AddDamage, AnimateCollisionReaction, the constants, its
inline accessors and its table. The contacts are contact.c: InitContact and
CloseContact, RemoveContacts, ContactTimeSorting and bList::AddSorted, all of
Contact (its constructor, FindContactTime, Crowbar, Resolve, the contact
point and normal, the planar contact point, the point velocity, the
denominator term, CollisionImpulse, its inline destructor and delete), and
the witness's FindWaferNormal, GetCollision, BeginCollision and
TestForContact.

The model is the image: tools/mipsemu.py runs the shipped functions out of
NFSHP2.ELF with bWare's slot pools, track.cpp's tree and polyhedra.cpp's
wafers beneath them, the harness (tools/src/collisionbody_test.c) runs the
port with track.c, polyhedra.c and vclip.c beneath it, both walk the same
op script, and the two transcripts are diffed. Every float goes both ways
as its bits.

**Labels, not pointers.** H0..H15 are bodies made in the checker's memory,
Tn, Wn, Kn and Pn slot n of the TrackPolygon-body, witness, car-body and
TrackPolygon pools (Tn.poly is a body's wafer), #n the nth block bMalloc
handed out, na the checker's own NumberAllocator, poly0..poly3 stand-in
polyhedra (only their vertex pointer is read) and C1..C4 stand-in
Collisions. The list heads are blist and wlist, and ZeroVector,
IdentityMatrix and ZeroMatrix are named.

**The heap.** bMalloc's blocks are 0xa5 where the request reaches, so a
field the code does not write shows. Two requests are short -- the
NumberAllocator's bit field (MaxNumbers >> 3 bytes for MaxNumbers numbers)
and the witness bit field (5304 bytes for 206 * 206 bits) -- and the image
reads and writes the byte past each, inside bMalloc's round-up on the
console. The model leaves that byte zero, and the port asks for it and
zeroes it (COLLISIONBODY_SHORT_SLACK); the harness prints the port's size
less the slack. No block is ever freed on either side, so a stale pointer
labels the same on both.

**The pools.** Each pool name has one fixed block, zeroed at every
allocation, on both sides; slots are labelled by number, which is what
agrees (the host's are wider). Both log every pool allocation, free and
bPrintf (the pools keep WARN_IF_NONEMPTY_DELETE).

**Seams.** A Collision is not ported: EndCollision's destructor call is the
port's gCollisionDestroyFn, and the model stubs ~Collision; both log it.
Nor is Smokeable: ConvertToSmokeable is gConvertToSmokeableFn on one side and
a stub on the other, both answering from the script's SMOKE map.

**The dynamic bodies.** D0..D3 are DynamicCollisionBodies in the checker's
memory. The class leaves GetPosition, GetVelocity, GetRotation and
AreCollisionsEnabled pure, so a body runs its methods on testA -- the class's
table with those four slots pointed at logging stubs, each with a `this`
delta of 8 the callers must add -- or testB, which is testA with Interpolate
stubbed too. The stubs answer S0..S3, each a position, a velocity and a
rotation the script sets. PS0 is a PhysicsSystem whose table's
ComputeAuxiliaries logs, RB0 and RB1 RigidBodies the script fills word by
word, TC0 a TopologyCoordinate over the TrackPolygon pool's slots, and
dpoly0, dpoly1 stand-in polyhedra with up to eight vertices.

**The cars.** CAR0..CAR2 are stand-in Cars -- only the fields a car's body
reads, at the image's offsets in the model and in a real Car in the harness
-- each with a CarTypeInfo whose BaseModelName is DIABLO, BUS or NOSUCHCAR.
PP0 and PP1 are stand-in PipelinePolyhedrons linked into the list, hashed
as DIABLO_CV and BUS_CV, PP1 with its centre of gravity not yet fixed.
Car::Move, IsBlinking, IsPoofed and SetToPhysicsMode are stubs on one side
and the harness's on the other, answering from the script; CarDamage,
PortRumbleImpact, tCopManager, AnimatedDriver and StartForceImpact are
stubs against the port's five seams. All of them log. PL0, M0 (a
PhysicsCar, M0.sys its PhysicsSystem, RB1 its RigidBody), M1 (a
MellowMover on RB0), AD0, DMG0, RC0 and COP0 are what the cars and the
globals point at. A dump lists the PipelinePolyhedrons and their corners,
and a car's body its box's, so the centre-of-gravity move shows.
G_SEAMS leaves the port's rumble and force seams NULL, as the 3DS build
does, and quiets the model's two stubs: a NULL seam skips the call and
nothing else.

**The contacts.** E0..E3 are DynamicCollisionBodies on testC, the class's
table with the nineteen slots a contact calls pointed at logging stubs
(`this` delta 8 again), answering from what the script sets for each: a
position, a velocity, a rotation, the current velocities, an inertia tensor
inverse, the maximum backup, the mass inverse, the bounciness, the friction,
whether it moves and whether it blinks. Interpolate backs the position up
along the velocity, ApplyImpulse adds the mass inverse of the impulse to the
current velocity, and ConsiderImpulse answers a queue the script fills, then
1. B0..B3 are RectPolyhedra for their shapes. Xn is slot n of the contact
pool and clist the list TestForContact sorts into; the script names a
contact by slot, by its place on clist, or as the one it made last, since
the pool's free list runs last-in first-out. A Collision is still not
ported: BeginCollision's constructor and CollisionImpulse's AddImpulse are
the port's gCollisionNewFn and gCollisionAddImpulseFn, stubs in the model,
and both log.

**sqrt.s and divisions.** The model runs with mipsemu's eesqrt, the port
with ee_sqrt: TrackPolygonCheck's root is the one site that may take a
negative, and the script makes it do so. The model runs with eediv too, the
port with ee_div: CollisionImpulse's friction divides by the slide, which is
zero for a car dropped straight onto flat ground, and the script drops one.
No other division or vrsqrt may see a zero.

**The tables.** DoSnapshot is not ported (the replay is not), so slot 16
prints as DoSnapshot on both sides; every other entry prints as the image
names it.

    python tools/collisionbody_check.py
    python tools/collisionbody_check.py --mutate [--only NAME,...]
    python tools/collisionbody_check.py --dump out/collisionbody
"""
import argparse
import difflib
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
from hostbuild import write_source
import mipsemu as me

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)
M32 = 0xFFFFFFFF

CBC = "3DS Files/source/collisionbody.c"
CBH = "3DS Files/source/collisionbody.h"
HARNESS = "tools/src/collisionbody_test.c"
SOURCES = [HARNESS, CBC] + ["3DS Files/source/" + s for s in (
    "track.c", "polyhedra.c", "vclip.c", "bslotpool.c", "bmem.c",
    "bmatrix.c", "bvector.c", "bmath.c", "bmathtab.c", "emath.c", "p32.c",
    "bchunk.c", "vtable.c", "espresso.c", "bticker.c", "terraintype.c",
    "terraintypetab.c", "rigidbody.c", "table.c", "carcollisionbody.c",
    "race.c", "copmanager.c", "contact.c")]
CCB = "3DS Files/source/carcollisionbody.c"
RCC = "3DS Files/source/race.c"
CTC = "3DS Files/source/contact.c"

TRACKB12 = ROOT / "extracted" / "TRACKS" / "TRACKB12.BUN"
POLY_CHUNK = 0x7fbe68

# ---------------------------------------------------------------- the image

GP = 0x00328bf0
STATS = 0x00311ca0                  # TheCollisionStats
ZV, IM, ZM = 0x00311cf0, 0x00311d00, 0x00311d40
TABLE = GP - 18400                  # pCollisionBodyTable
BLIST = GP - 18392                  # CollisionBodyList
MAXW = GP - 18384                   # MaxCollisionBodyWidthX
ALLOC = GP - 18356                  # pCollisionBodyNumberAllocator
WLIST = GP - 18352                  # CollisionBodyWitnessList
WBITS = GP - 18316                  # pWitnessExistanceBitField
POOL_TPCB, POOL_CAR, POOL_WIT = GP - 18312, GP - 18308, GP - 18304
POOL_TP = 0x00323424                # TrackPolygonSlotPool
TREE = 0x002f14c8                   # TheTopologyTree
VT_BASE, VT_STATIC, VT_TP = 0x0029bf48, 0x0029be78, 0x0029bda8
VT_DYN = 0x0029bcd8
VT_CAR = 0x0029bc08
PPLIST = 0x00324a30                 # PipelinePolyhedronList
G_BORING_AT = GP - 23156            # BoringAIForCameraTuningOn
G_WILLIAMS_AT = GP - 16016          # WilliamsAITuningMode
G_RC_AT = GP - 22720                # pRaceCoordinator
G_COP_AT = GP - 16500               # pCopManager
G_TIMER_AT = GP - 20224             # WorldTimer
G_LOOP_AT = GP - 20200              # WorldLoopCounter
G_PRINT_AT = 0x00324448             # PrintThisTime
POOL_CONTACT = GP - 18460           # ContactSlotPool
G_THRESH_AT = GP - 18456            # ContactThreshold
G_BIAS_AT = GP - 18448              # WaferBias
G_MINFACTOR_AT = GP - 18436         # MinimumContactImpulseFactor
G_MINSPEED_AT = GP - 18432          # MinimumContactImpulseSpeed
G_SCRAPE_AT = GP - 18424            # MaxFrictionScrapeSpeed
IMPULSE_DIV = 0x001cb278            # CollisionImpulse's -k / vtl
CT_ZERO_W = (0x001ca30c, 172)       # FindContactTime's lqc2, the w lane
CT_UP_W = (0x001cac54, 28)          # FindPlanarCollisionContactPoint's
TPCHECK_SQRT = 0x001cd668           # TrackPolygonCheck's sqrt.s
VT_ENTRIES = 26
HEADER = 48

POOLS = (
    ("TrackPolygonCollisionBodySlotPool", POOL_TPCB, 160, 1080),
    ("CarCollisionBodySlotPool", POOL_CAR, 14, 336),
    ("CollisionBodyWitnessSlotPool", POOL_WIT, 256, 112),
    ("TrackPolygonSlotPool", POOL_TP, 1024, 128),
    ("ContactSlotPool", POOL_CONTACT, 32, 64),
)
SHORT = ("NumberAllocator", "CollisionBodyWitnessBitField")
MAX_BODIES = 206
BITFIELD_BYTES = 5304

SYM = dict(
    sinit="_GLOBAL_$I$TheCollisionStats",
    sclose="_GLOBAL_$D$TheCollisionStats",
    init="InitCollisionBody__Fv",
    close="CloseCollisionBody__Fv",
    inittree="InitTree__12TopologyTree",
    closetree="CloseTree__12TopologyTree",
    ttloader="Loader__12TopologyTreeP6bChunk",
    na_set="SetMaxNumbers__15NumberAllocatori",
    na_alloc="AllocateNumber__15NumberAllocator",
    na_allocn="AllocateNumber__15NumberAllocatori",
    na_free="FreeNumber__15NumberAllocatori",
    na_dtor="_$_15NumberAllocator",
    base_ctor="__13CollisionBodyi17CollisionBodyType",
    base_dtor="_$_13CollisionBody",
    static_ctor="__19StaticCollisionBodyi17CollisionBodyType",
    static_dtor="_$_19StaticCollisionBody",
    tp_new="__nw__25TrackPolygonCollisionBodyUi",
    tp_ctor="__25TrackPolygonCollisionBodyiP19TopologyTreePolygon",
    tp_dtor="_$_25TrackPolygonCollisionBody",
    tp_gettp="GetTrackPolygon__25TrackPolygonCollisionBody",
    setbox="SetBBoxMinMax__13CollisionBodyPC8bVector2T1",
    updw="UpdateMaxCollisionBodyWidth__13CollisionBodyf",
    flip="CollisionBodyFlipFunction__FP5bNodeT0",
    name="SetDebugName__13CollisionBodyPCc",
    find="FindCollisionBody__13CollisionBodyi",
    nextid="GetNextCollisionBodyID__13CollisionBody",
    getcoll="GetCollision__13CollisionBodyi",
    enable="EnableCollisions__13CollisionBody",
    disable="DisableCollisions__13CollisionBody",
    bbox="DoBoundingBoxCheck__13CollisionBodyPC8bVector2T1f",
    bboxb="DoBoundingBoxCheck__13CollisionBodyP13CollisionBodyf",
    omalloc="bOMalloc__FP8SlotPool",
    wit_ctor="__20CollisionBodyWitnessP13CollisionBodyT1",
    wit_dtor="_$_20CollisionBodyWitness",
    wit_end="EndCollision__20CollisionBodyWitness",
    expired="HasExpired__20CollisionBodyWitness",
    exists="DoesWitnessExist__20CollisionBodyWitnessP13CollisionBodyT1",
    yaw="IsYawControlInducingCollisionBody__FP13CollisionBody",
    elim="EliminateAllWitnesses__20CollisionBodyWitness",
    g_max="GetBBoxMax__13CollisionBody",
    g_min="GetBBoxMin__13CollisionBody",
    g_nc="GetNumCollisions__13CollisionBody",
    g_poly="GetPoly__13CollisionBody",
    g_name="GetDebugName__13CollisionBody",
    g_act="DoesActiveCollisionDetection__13CollisionBody",
    g_id="GetID__13CollisionBody",
    g_dyn="IsDynamic__13CollisionBody",
    coll_dtor="_$_9Collision",
    dyn_ctor="__20DynamicCollisionBodyi17CollisionBodyTypeP18TopologyCoordinate",
    dyn_dtor="_$_20DynamicCollisionBody",
    dyn_build="BuildBoundingVolumes__20DynamicCollisionBody",
    dyn_update="UpdatePosition__20DynamicCollisionBody",
    dyn_begin="BeginMove__20DynamicCollisionBodyf",
    dyn_interp="Interpolate__20DynamicCollisionBodyP8bVector3P8bMatrix4f",
    dyn_interpv="InterpolateVelocity__20DynamicCollisionBodyP8bVector3f",
    dyn_backup="Backup__20DynamicCollisionBodyf",
    dyn_testvel="GetTestImpulseVelocities__20DynamicCollisionBodyR8bVector3T1T1T1",
    dyn_local="GetLocalCollisionBodies__20DynamicCollisionBodyfPP13CollisionBodyT2",
    dyn_witnesses="MaybeCreateWitnesses__20DynamicCollisionBody",
    dyn_createtp="CreateTrackPolygonCollisionBodies__20DynamicCollisionBody",
    dyn_tpcheck="TrackPolygonCheck__20DynamicCollisionBodyP12TrackPolygon",
    dyn_bbox="GetBoundingBox__20DynamicCollisionBodyP8bVector3T1",
    tp_assign="AssignTrackPolygon__12TopologyTreeP19TopologyTreePolygon",
    smokeable="ConvertToSmokeable__FP13CollisionBody",
    ccb_new="__nw__16CarCollisionBodyUi",
    ccb_ctor="__16CarCollisionBodyP3Car",
    ccb_dtor="_$_16CarCollisionBody",
    ccb_damage="AddDamage__16CarCollisionBodyP8bVector3f",
    ccb_anim="AnimateCollisionReaction__16CarCollisionBodyP8bVector3f",
    ccb_setyaw="SetLastYawControlCollisionTime__16CarCollisionBodyR5Timer",
    ccb_setpen="SetLastPenetrationTime__16CarCollisionBodyR5Timer",
    ccb_getyaw="GetLastYawControlCollisionTime__16CarCollisionBody",
    ccb_getpen="GetLastPenetrationTime__16CarCollisionBody",
    ccb_getcar="GetCar__16CarCollisionBody",
    rectpoly="__14RectPolyhedronffffff",
    ct_init="InitContact__Fv",
    ct_close="CloseContact__Fv",
    ct_ctor="__7ContactP13CollisionBodyT1P20CollisionBodyWitness",
    ct_dtor="_$_7Contact",
    ct_time="FindContactTime__7Contact",
    ct_crowbar="Crowbar__7Contactf",
    ct_resolve="Resolve__7Contact",
    ct_point="FindContactPointAndNormal__7ContactP8bVector3T1",
    ct_planar="FindPlanarCollisionContactPoint__7ContactP8bVector3",
    ct_cpv="GetContactPointVelocity__FP8bVector3T0T0T0",
    ct_denom="DenominatorTerm__FP8bMatrix4P8bVector3T1",
    ct_impulse="CollisionImpulse__7Contact",
    ct_remove="RemoveContacts__7ContactPt6bTList1Z7ContactP13CollisionBody",
    ct_sort="ContactTimeSorting__7ContactP7ContactT1",
    ct_wafer="FindWaferNormal__FP8bVector3P25TrackPolygonCollisionBodyP20DynamicCollisionBody",
    ct_getcoll="GetCollision__20CollisionBodyWitnessP8bVector3",
    ct_begin="BeginCollision__20CollisionBodyWitnessP8bVector3",
    ct_test="TestForContact__20CollisionBodyWitnessPt6bTList1Z7Contact",
    coll_ctor="__9CollisionP20CollisionBodyWitnessP8bVector3",
    coll_impulse="AddImpulse__9CollisionP8bVector3T1f",
)

# ------------------------------------------------------------------ the ops

(OP_TAG, OP_STATIC_INIT, OP_STATIC_CLOSE, OP_INIT, OP_CLOSE,
 OP_TREE_INIT, OP_TREE_CLOSE, OP_TREE_LOAD, OP_FILL_H, OP_BASE_NEW,
 OP_STATIC_NEW, OP_TP_NEW, OP_VDEL, OP_DTOR, OP_SET_POLY, OP_SETBOX,
 OP_RAWBOX, OP_UPDW, OP_SETMAXW, OP_FLIP, OP_NAME, OP_FIND, OP_NEXTID,
 OP_GETCOLL, OP_ENABLE, OP_DISABLE, OP_BBOX, OP_BBOXB, OP_SETB,
 OP_NA_SET, OP_NA_ALLOC, OP_NA_ALLOCN, OP_NA_FREE, OP_NA_DESTROY,
 OP_NA_DUMP, OP_WIT_NEW, OP_WIT_DEL, OP_WIT_SETCOLL, OP_WIT_END,
 OP_EXPIRED, OP_EXISTS, OP_YAW, OP_ELIM, OP_VCALL, OP_VTDUMP, OP_DUMP,
 OP_STAT, OP_TPPOKE, OP_ACCESS) = range(1, 50)
(OP_DYN_NEW, OP_DYN_SETVT, OP_DYN_POKE, OP_DYN_PTRS, OP_DYN_SIDE, OP_DPOLY,
 OP_DYN_SETPOLY, OP_DYN_BUILD, OP_DYN_UPDATE, OP_DYN_BEGIN, OP_DYN_INTERP,
 OP_DYN_INTERPV, OP_DYN_BACKUP, OP_DYN_TESTVEL, OP_RB_SET, OP_RB_DUMP,
 OP_DYN_LOCAL, OP_DYN_WITNESSES, OP_DYN_CREATE_TP, OP_DYN_TPCHECK,
 OP_TP_ASSIGN, OP_TP_GEOM, OP_TC_SET, OP_SMOKE, OP_DYN_DTOR, OP_DYN_BBOX,
 OP_TP_FILL) = range(50, 77)
(OP_CAR_NEW, OP_CAR_DTOR, OP_CAR_FIELD, OP_CAR_SIDE, OP_CAR_COG, OP_GLOBAL,
 OP_PP, OP_CAR_MOVE, OP_CAR_APPLY, OP_CAR_DAMAGE, OP_CAR_ANIM, OP_CAR_TIMES,
 OP_CAR_STPM) = range(77, 90)
(OP_E_STATE, OP_E_QUEUE, OP_BOX, OP_BOX_SET, OP_TP_VERTS, OP_CT_INIT,
 OP_CT_CLOSE, OP_CT_TEST, OP_CT_RESOLVE, OP_CT_REMOVE, OP_CT_DUMP,
 OP_CT_NEW, OP_CT_TIME, OP_CT_CROWBAR, OP_CT_POINT, OP_CT_PLANAR,
 OP_CT_IMPULSE, OP_CT_CPV, OP_CT_DENOM, OP_CT_WAFER, OP_CT_SORT,
 OP_CT_GETCOLL, OP_CT_BEGIN, OP_CT_DEL, OP_CT_POKE, OP_CT_LINK,
 OP_WIT_CP) = range(90, 117)

NH, NPOLY, NCOLL = 16, 4, 4
REF_T = 0x100
REF_D = 0x200
ND, NDPOLY, NDVERT, NRB = 4, 2, 8, 2
D_BYTES = 256
RB_FIRST, RB_END = 16, 384          # the RigidBody words RB_SET writes
RB_WORDS = (RB_END - RB_FIRST) // 4
SIDE_WORDS = 24                     # a position, a velocity, a rotation
TC_TOTAL, TC_TABLE = 544, 32
REF_K = 0x300
NCAR, NPP, NPPVERT = 3, 2, 8
CAR_BYTES, CTI_BYTES = 2048, 400
CAR_SLOT = 336
# The Car fields a car's body reads, by image offset.
CAR_DRIVER, CAR_CTI, CAR_PLAYER, CAR_MODE, CAR_MOVER = 10, 12, 24, 36, 48
CAR_POS, CAR_VEL, CAR_ROT = 96, 112, 144
CAR_ANIM, CAR_TC, CAR_DAMAGE = 1172, 1280, 1940
CTI_NAME, CTI_COG = 32, 272
CAR_NAMES = ("DIABLO", "BUS", "NOSUCHCAR")
# CAR_FIELD's fields, and GLOBAL's globals.
(CF_DRIVER, CF_NAME, CF_PLAYER, CF_MODE, CF_MOVER, CF_ANIM, CF_DAMAGE,
 CF_BLINK, CF_POOF) = range(9)
(G_BORING, G_WILLIAMS, G_RC, G_STATE, G_COP, G_TIMER, G_PORT,
 G_SEAMS, G_PRINT, G_LOOP, G_THRESH, G_BIAS, G_MINFACTOR, G_MINSPEED,
 G_SCRAPE) = range(15)
# CT_POKE's fields: the backup time, CrowbarVector's lanes, LoopFound.
XF_BT, XF_CV, XF_LF = 0, 1, 5
MAX_WALK = 400
# The contact bodies: car-sized, on testC, with what its stubs answer.
REF_E = 0x400
NE, NBOX, NEQ = 4, 4, 8
E_BYTES = 352
E_VEC_WORDS = 48                    # pos, vel, rot, cv, cw, inertia
E_POS, E_VEL, E_ROT, E_CV, E_CW, E_INERTIA = 0, 16, 32, 96, 112, 128
CT_BYTES = 64
REF_LIST = 0x100                    # a contact: the nth on clist
REF_NEWEST = 0x200                  # a contact: CT_NEW's last

# Virtual slots, by byte offset.
(VT_DESTROY, VT_SNAPSHOT, VT_GETPOS, VT_GETVEL, VT_GETROT, VT_SETPOS,
 VT_MAXBACKUP, VT_MOVE, VT_BACKUP, VT_INTERP, VT_RECOMPUTE, VT_CURVEL,
 VT_TESTVEL, VT_PHYSMODE, VT_CONSIDER, VT_APPLY, VT_ENABLED, VT_TERRAIN,
 VT_MASSINV, VT_INERTIA, VT_MOVEABLE, VT_ENERGY, VT_BLINKING, VT_BOUNCE,
 VT_FRICTION) = range(8, 208, 8)
STATIC_SLOTS = [s for s in range(32, 208, 8) if s != VT_TERRAIN]
TP_SLOTS = [VT_GETPOS] + list(range(32, 208, 8))

# The body fields SETB pokes, by image offset.
F_TYPE, F_DYN, F_NW, F_DIS, F_NC, F_ACT = 12, 13, 16, 17, 18, 19

bits = me.f_to_bits
fbits = me.fbits_to


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def s8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def T(s):
    return REF_T + s


def D(k):
    return REF_D + k


def K(s):
    return REF_K + s


def E(k):
    return REF_E + k


# ---------------------------------------------------------------- the script


class Script(object):
    def __init__(self):
        self.words = []
        self.tags = []
        self.ntps = 0                   # TP_ASSIGNs so far: the next's index

    def op(self, code, *args):
        self.words.append(code)
        if code == OP_TP_ASSIGN:
            self.ntps += 1
        for a in args:
            if isinstance(a, float):
                self.words.append(bits(a))
            else:
                self.words.append(a & M32)

    def tag(self, name):
        self.tags.append(name)
        self.op(OP_TAG, len(self.tags) - 1)

    def name(self, b, raw):
        raw = (raw + bytes(48))[:48]
        self.op(OP_NAME, b, *struct.unpack("<12I", raw))

    def dump(self):
        self.op(OP_DUMP)


def poly_chunk():
    d = TRACKB12.read_bytes()
    t, s = struct.unpack_from("<II", d, POLY_CHUNK)
    assert t == 0x34132
    return d[POLY_CHUNK:POLY_CHUNK + 8 + s]


def pick_polys(chunk):
    """Polygon indices for the TrackPolygon bodies: a floor triangle, a
    quad, a wall, a ceiling and two of other terrains."""
    n = (len(chunk) - 8) // 32
    want = {}
    for i in range(n):
        o = 8 + 32 * i
        _used, _mm, ty, fl = chunk[o:o + 4]
        for key, ok in (("floor", fl == 0), ("quad", fl & 0x10 and not fl & 2),
                        ("wall", fl & 2), ("ceiling", fl & 8),
                        ("terrain%d" % ty, fl == 0x10)):
            if ok and key not in want:
                want[key] = i
    picks = [want["floor"], want["quad"], want["wall"], want["ceiling"]]
    seen = set(chunk[8 + 32 * i + 2] for i in picks)
    for k in sorted(want, key=want.get):
        if k.startswith("terrain") and len(picks) < 7:
            ty = int(k[7:])
            if ty not in seen and want[k] not in picks:
                seen.add(ty)
                picks.append(want[k])
    return picks


def boot_section(sc):
    sc.tag("boot: the image's data before the static initialiser")
    sc.op(OP_VTDUMP)
    sc.dump()
    sc.op(OP_STATIC_INIT)
    sc.dump()
    for h in range(NH):
        sc.op(OP_FILL_H, h, 0xa5)


def na_section(sc):
    sc.tag("NumberAllocator")
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_ALLOC)                  # Max 0: -1
    sc.op(OP_NA_SET, 20)
    sc.op(OP_NA_DUMP)
    for _ in range(3):
        sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_ALLOCN, 5)              # not the lowest
    sc.op(OP_NA_ALLOCN, 4)
    sc.op(OP_NA_ALLOCN, 3)              # the lowest, with 4 and 5 taken
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_FREE, 1)
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_FREE, 7)                # above the lowest
    sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_ALLOCN, 1)              # again, taken
    sc.op(OP_NA_DUMP)
    for _ in range(16):
        sc.op(OP_NA_ALLOC)              # to the top, then -1
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_FREE, 19)
    sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_FREE, 0)
    sc.op(OP_NA_FREE, 0)
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_SET, 206)               # the old field freed
    for i in (200, 205, 199, 0):
        sc.op(OP_NA_ALLOCN, i)          # 200.. live in the slack byte
    sc.op(OP_NA_DUMP)
    for i in range(1, 200):
        sc.op(OP_NA_ALLOCN, i)
    sc.op(OP_NA_DUMP)
    for _ in range(6):
        sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_FREE, 203)
    sc.op(OP_NA_ALLOC)
    for n in (7, 8, 9, 1):
        sc.op(OP_NA_SET, n)
        for _ in range(n + 1):
            sc.op(OP_NA_ALLOC)
        sc.op(OP_NA_DUMP)
    sc.op(OP_NA_SET, 0)
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_SET, 0)                 # nothing to free
    sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_SET, 12)
    sc.op(OP_NA_ALLOC)
    sc.op(OP_NA_DESTROY, 2)
    sc.op(OP_NA_DUMP)
    sc.op(OP_NA_SET, 30)
    sc.op(OP_NA_DESTROY, 3)             # the allocator itself goes too
    sc.op(OP_NA_DUMP)


def init_section(sc):
    sc.tag("InitCollisionBody")
    sc.op(OP_INIT)
    sc.dump()
    sc.op(OP_NEXTID)


def bodies_section(sc):
    sc.tag("static bodies: constructors, the table and the list")
    sc.op(OP_STATIC_NEW, 0, 5, 1)
    sc.op(OP_STATIC_NEW, 1, -1, 2)
    sc.op(OP_BASE_NEW, 2, 0, 0)
    sc.op(OP_NEXTID)
    sc.op(OP_STATIC_NEW, 3, 205, 3)
    sc.op(OP_STATIC_NEW, 4, 1, 4)
    sc.op(OP_NEXTID)
    sc.dump()
    for i in (5, 0, 1, 2, 205, 204):
        sc.op(OP_FIND, i)
    for h in (0, 1, 2, 3):
        sc.op(OP_ACCESS, h)

    sc.tag("a second body on a taken ID")
    sc.op(OP_STATIC_NEW, 5, 5, 0)
    sc.op(OP_FIND, 5)
    sc.dump()
    sc.op(OP_VDEL, 5, 3)                # frees 5 under H0
    sc.op(OP_FIND, 5)
    sc.op(OP_NEXTID)
    sc.dump()

    sc.tag("destructors, virtual and not")
    sc.op(OP_STATIC_NEW, 6, 2, 1)
    sc.op(OP_STATIC_NEW, 7, 3, 2)
    sc.op(OP_STATIC_NEW, 8, -1, 1)
    sc.op(OP_BASE_NEW, 9, 6, 1)
    sc.dump()
    sc.op(OP_VDEL, 6, 2)                # no free
    sc.op(OP_DTOR, 7, 0, 1)             # the base's alone: static count stays
    sc.op(OP_DTOR, 8, 1, 0)
    sc.op(OP_VDEL, 9, 3)                # CollisionBody's own table
    sc.op(OP_NEXTID)
    for h in (6, 7, 8, 9):              # each left with the base's table
        sc.op(OP_ACCESS, h)
    sc.dump()


def box_section(sc, rnd):
    sc.tag("SetBBoxMinMax: the sort and the widest")
    for h, id_ in ((10, 10), (11, 11), (12, 12), (13, -1)):
        sc.op(OP_STATIC_NEW, h, id_, 1)
    sc.dump()
    sc.op(OP_SETBOX, 10, 0.0, 0.0, 10.0, 5.0)
    sc.dump()
    sc.op(OP_SETBOX, 11, -4.0, 1.0, 20.0, 2.0)
    sc.op(OP_SETBOX, 12, 5.0, -3.0, 10.0, 8.0)      # ties 10 on max x
    sc.op(OP_SETBOX, 13, 9.0, 9.0, 10.0, 9.5)       # ties, ID -1
    sc.dump()
    sc.op(OP_SETBOX, 0, 1.0, 1.0, 30.0, 3.0)
    sc.op(OP_SETBOX, 1, 1.0, 1.0, -30.0, 3.0)       # inverted
    sc.op(OP_SETBOX, 12, 6.0, -2.0, 10.0, 9.0)      # max x the same
    sc.dump()
    sc.op(OP_SETBOX, 11, -4.0, 1.0, 12.0, 2.0)      # narrowing, not widest
    sc.op(OP_SETBOX, 0, 1.0, 1.0, 3.0, 3.0)         # the widest narrows
    sc.dump()
    sc.op(OP_SETBOX, 1, -100.0, 0.0, 100.0, 1.0)
    sc.op(OP_SETBOX, 1, -0.0, 0.0, 0.0, 1.0)
    sc.dump()
    for _ in range(24):
        h = rnd.choice((0, 1, 2, 3, 4, 10, 11, 12, 13))
        x0 = float(rnd.randint(-40, 40))
        w = float(rnd.choice((0, 1, 2, 5, 8, 20, 60)))
        y0 = float(rnd.randint(-10, 10))
        sc.op(OP_SETBOX, h, x0, y0, x0 + w, y0 + rnd.choice((0.5, 4.0)))
    sc.dump()

    sc.tag("UpdateMaxCollisionBodyWidth on its own")
    sc.op(OP_RAWBOX, 10, 0.0, 0.0, 4.0, 1.0)
    sc.op(OP_SETMAXW, 3.0)
    sc.op(OP_UPDW, 10, 4.0)             # the same width
    sc.op(OP_UPDW, 10, 5.0)             # wider, past the widest
    sc.dump()
    sc.op(OP_SETMAXW, 50.0)
    sc.op(OP_UPDW, 10, 6.0)             # wider, not past it
    sc.op(OP_SETMAXW, 4.0)
    sc.op(OP_UPDW, 10, 2.0)             # was the widest: the others'
    sc.dump()
    sc.op(OP_SETMAXW, 9.0)
    sc.op(OP_UPDW, 10, 2.0)             # narrower, was not the widest
    sc.op(OP_SETMAXW, 4.0)
    sc.op(OP_UPDW, 10, -1.0)
    sc.op(OP_SETMAXW, 2.0)              # a widest below this body's width,
    sc.op(OP_UPDW, 10, 3.0)             # as a recompute can leave it
    sc.dump()

    sc.tag("the flip function")
    sc.op(OP_RAWBOX, 10, 0.0, 0.0, 4.0, 1.0)
    sc.op(OP_RAWBOX, 11, 0.0, 0.0, 4.0, 1.0)
    sc.op(OP_RAWBOX, 12, 0.0, 0.0, 5.0, 1.0)
    sc.op(OP_RAWBOX, 13, 0.0, 0.0, -0.0, 1.0)
    sc.op(OP_RAWBOX, 1, 0.0, 0.0, 0.0, 1.0)
    for a, b in ((10, 11), (11, 10), (10, 12), (12, 10), (10, 10),
                 (13, 1), (1, 13), (13, 10), (0, 13)):
        sc.op(OP_FLIP, a, b)
    sc.dump()
    sc.op(OP_SETBOX, 10, -1.0, 0.0, 4.0, 1.0)      # max x as it was: stays
    sc.op(OP_SETBOX, 12, 0.0, 0.0, 5.0, 2.0)
    sc.dump()

    sc.tag("the debug name")
    sc.name(10, b"abc\0")
    sc.op(OP_DUMP)
    sc.name(10, b"x" * 39 + b"\0")
    sc.name(11, b"y" * 40)
    sc.name(12, b"0123456789" * 4 + b"ABCDEFGH")
    sc.name(13, b"ab\0junkjunk")
    sc.name(0, b"\0zzzz")
    sc.dump()


def flags_section(sc):
    sc.tag("collisions enabled and disabled; the bounding-box tests")
    sc.op(OP_DISABLE, 10)
    sc.op(OP_DISABLE, 10)
    sc.op(OP_ENABLE, 10)
    sc.op(OP_ENABLE, 10)
    sc.op(OP_ENABLE, 10)                # stays at 0
    sc.op(OP_VCALL, 10, VT_ENABLED)
    sc.op(OP_DISABLE, 10)
    sc.op(OP_VCALL, 10, VT_ENABLED)
    sc.op(OP_SETB, 11, F_DIS, 127)
    sc.op(OP_DISABLE, 11)               # to -128
    sc.op(OP_VCALL, 11, VT_ENABLED)
    sc.op(OP_ENABLE, 11)                # -128 is not 0
    sc.op(OP_SETB, 12, F_DIS, 0xff)
    sc.op(OP_ENABLE, 12)
    sc.op(OP_VCALL, 12, VT_ENABLED)
    sc.op(OP_ENABLE, 12)
    sc.dump()
    sc.op(OP_RAWBOX, 10, 0.0, 0.0, 4.0, 2.0)
    sc.op(OP_RAWBOX, 11, 4.0, 2.0, 6.0, 3.0)        # touching at a corner
    sc.op(OP_RAWBOX, 12, 4.5, -1.0, 6.0, 3.0)
    sc.op(OP_RAWBOX, 13, -1.0, 2.5, 1.0, 3.0)
    for (x0, y0, x1, y1, m) in ((1, 1, 2, 2, 0), (4, 2, 5, 3, 0),
                                (4.25, 0, 5, 1, 0), (4.25, 0, 5, 1, 0.25),
                                (4.25, 0, 5, 1, 0.125), (-3, 0, -0.5, 1, 0.5),
                                (-3, 0, -0.5, 1, 0.25), (0, 2.5, 1, 3, 0),
                                (0, 2.5, 1, 3, 0.5), (0, -3, 1, -0.5, 0.5),
                                (0, -3, 1, -0.5, 0.75), (5, 5, -5, -5, 0),
                                (0, 0, 4, 2, -0.5), (1, 1, 3, 1.5, -0.5)):
        sc.op(OP_BBOX, 10, float(x0), float(y0), float(x1), float(y1),
              float(m))
    for a, b in ((10, 11), (11, 10), (10, 12), (12, 10), (10, 13), (13, 10),
                 (11, 12)):
        for m in (0.0, 0.5, -0.25):
            sc.op(OP_BBOXB, a, b, m)


def vcall_section(sc, bodies):
    sc.tag("the static bodies' virtual methods")
    sc.op(OP_VTDUMP)
    for b in bodies:
        for s in STATIC_SLOTS:
            sc.op(OP_VCALL, b, s)


def tree_section(sc, chunk, picks):
    sc.tag("the tree, and TrackPolygon bodies")
    sc.op(OP_TREE_INIT)
    words = struct.unpack("<%dI" % (len(chunk) // 4), chunk)
    sc.op(OP_TREE_LOAD, len(words), *words)
    sc.dump()
    ids = (25, 20, 26, 21, 22, -1, 23)
    for k, p in enumerate(picks):
        sc.op(OP_TP_NEW, ids[k], p)
    sc.op(OP_TP_NEW, 24, picks[0])      # the same polygon again
    sc.op(OP_NEXTID)
    sc.dump()
    for s in range(len(picks) + 1):
        sc.op(OP_ACCESS, T(s))
        sc.op(OP_YAW, T(s))
    for s in TP_SLOTS:
        sc.op(OP_VCALL, T(1), s)
    for s in (VT_GETPOS, VT_TERRAIN, VT_ENABLED):
        for k in range(len(picks) + 1):
            sc.op(OP_VCALL, T(k), s)

    sc.tag("the TrackPolygon's flags and terrain, poked")
    # the TrackPolygons are the pool's first slots, in the order made
    sc.op(OP_TPPOKE, 0, 10, 0x02)
    sc.op(OP_TPPOKE, 1, 10, 0xfd)
    sc.op(OP_TPPOKE, 2, 11, 0x85)
    sc.op(OP_TPPOKE, 3, 11, 0x7f)
    for s in range(4):
        sc.op(OP_YAW, T(s))
        sc.op(OP_VCALL, T(s), VT_TERRAIN)

    sc.tag("IsYawControlInducingCollisionBody over the types")
    for t in (-128, -1, 0, 1, 2, 4, 5, 127):
        sc.op(OP_SETB, 13, F_TYPE, t)
        sc.op(OP_YAW, 13)
    sc.op(OP_SETB, 13, F_TYPE, 1)


def witness_section(sc):
    # A witness's pair bit is ID1 * 206 + ID2, so an ID of -1 lands before
    # the field. The game never joins one: the only negative IDs are a
    # VirginSmokeable's, and MaybeCreateWitnesses converts those first. Nor
    # does it join a body to itself, whose last witness would destroy a
    # track body twice.
    sc.tag("witnesses: the constructor, the bit field and the list")
    sc.op(OP_STATIC_NEW, 14, 14, 1)
    sc.op(OP_STATIC_NEW, 6, 204, 1)
    for h, k in ((0, 0), (1, 1), (2, 1), (3, 2), (4, 3), (6, 3), (10, 0),
                 (11, 1), (12, 2), (13, 3), (14, 0)):
        sc.op(OP_SET_POLY, h, k)
    sc.op(OP_WIT_NEW, 0, 4)             # W0: IDs 5 and 1
    sc.op(OP_WIT_NEW, 3, 6)             # W1: 205 and 204, the slack byte
    sc.op(OP_WIT_NEW, 2, 0)             # W2: ID 0, a base body
    sc.op(OP_WIT_NEW, 0, T(1))          # W3
    sc.op(OP_WIT_NEW, T(2), 4)          # W4
    sc.op(OP_WIT_NEW, T(0), T(1))       # W5
    sc.op(OP_WIT_NEW, 10, 11)           # W6
    sc.dump()
    for a, b in ((0, 4), (4, 0), (3, 6), (6, 3), (3, 3), (0, 3), (1, 0),
                 (0, 1), (0, T(1)), (T(1), 0), (T(0), T(1)), (T(1), T(7)),
                 (13, 13)):
        sc.op(OP_EXISTS, a, b)

    sc.tag("HasExpired")
    sc.op(OP_RAWBOX, 10, 0.0, 0.0, 4.0, 2.0)
    sc.op(OP_RAWBOX, 11, 1.0, 1.0, 6.0, 3.0)
    sc.op(OP_SETB, 10, F_DIS, 0)
    sc.op(OP_SETB, 11, F_DIS, 0)
    sc.op(OP_EXPIRED, 6)                # neither active
    sc.op(OP_SETB, 11, F_ACT, 1)
    sc.op(OP_EXPIRED, 6)
    sc.op(OP_SETB, 11, F_ACT, 0)
    sc.op(OP_SETB, 10, F_ACT, 0xff)
    sc.op(OP_EXPIRED, 6)
    sc.op(OP_DISABLE, 10)
    sc.op(OP_EXPIRED, 6)
    sc.op(OP_ENABLE, 10)
    sc.op(OP_DISABLE, 11)
    sc.op(OP_EXPIRED, 6)
    sc.op(OP_ENABLE, 11)
    for box in ((5.0, 0.0, 6.0, 1.0), (4.0, 2.0, 6.0, 3.0),
                (4.5, 0.0, 6.0, 1.0), (-2.0, -2.0, -0.5, 3.0),
                (-2.0, -2.0, 0.0, 3.0), (0.0, 2.5, 1.0, 3.0),
                (0.0, -3.0, 1.0, -0.25), (0.0, -3.0, 1.0, 0.0)):
        sc.op(OP_RAWBOX, 11, *box)
        sc.op(OP_EXPIRED, 6)
    sc.op(OP_RAWBOX, 11, 1.0, 1.0, 6.0, 3.0)
    sc.op(OP_WIT_SETCOLL, 6, 1)
    sc.op(OP_RAWBOX, 11, 50.0, 50.0, 60.0, 60.0)
    sc.op(OP_EXPIRED, 6)                # a collision: never
    sc.op(OP_WIT_SETCOLL, 6, 0)
    sc.op(OP_EXPIRED, 6)
    sc.op(OP_RAWBOX, 11, 1.0, 1.0, 6.0, 3.0)
    sc.op(OP_EXPIRED, 3)                # a track polygon's
    sc.op(OP_ACCESS, 10)                # act -1 and dis 0: the accessors apart

    sc.tag("GetCollision and EndCollision")
    sc.op(OP_SETB, 0, F_NC, 3)
    sc.op(OP_WIT_SETCOLL, 0, 1)
    sc.op(OP_WIT_SETCOLL, 2, 2)
    sc.op(OP_WIT_SETCOLL, 3, 3)
    for i in (-1, 0, 1, 2, 3, 4):
        sc.op(OP_GETCOLL, 0, i)
    sc.op(OP_SETB, 0, F_NC, 1)
    sc.op(OP_GETCOLL, 0, 1)
    sc.op(OP_SETB, 4, F_NC, 5)
    for i in range(4):
        sc.op(OP_GETCOLL, 4, i)
    sc.op(OP_WIT_SETCOLL, 4, 4)
    sc.op(OP_WIT_SETCOLL, 0, 0)
    sc.op(OP_GETCOLL, 4, 0)             # W0 has none now: W4's
    sc.op(OP_GETCOLL, 4, 1)
    sc.op(OP_WIT_SETCOLL, 0, 1)
    sc.op(OP_WIT_SETCOLL, 4, 0)
    sc.op(OP_WIT_END, 0)
    sc.op(OP_WIT_END, 0)                # again: no Collision to destroy
    sc.op(OP_ACCESS, 0)
    sc.op(OP_ACCESS, 4)
    sc.dump()

    sc.tag("witness destructors, and the track bodies they take along")
    sc.op(OP_WIT_DEL, 2, 3)             # ends its collision first
    sc.op(OP_WIT_DEL, 4, 3)             # T2's last: T2 goes
    sc.dump()
    sc.op(OP_WIT_DEL, 5, 2)             # T0 keeps nothing, T1 keeps W3
    sc.op(OP_WIT_DEL, 1, 0)             # H3 is static of type 3: it goes,
    sc.op(OP_EXISTS, 6, 3)              # and its pair bits with it
    sc.dump()
    sc.op(OP_WIT_NEW, 12, 14)
    sc.op(OP_WIT_NEW, 14, 12)
    sc.op(OP_WIT_NEW, 12, T(3))
    sc.op(OP_WIT_NEW, T(4), 14)
    sc.op(OP_WIT_NEW, T(6), T(3))
    sc.dump()
    sc.op(OP_VDEL, 12, 3)               # its witnesses first
    sc.dump()
    sc.op(OP_STAT, 0, 40)
    sc.op(OP_STAT, 9, 41)
    sc.op(OP_WIT_NEW, 10, 14)           # the highest stays
    sc.op(OP_STAT, 2, 60)
    sc.op(OP_STAT, 11, 20)
    sc.op(OP_STATIC_NEW, 15, 30, 1)     # the highest follows
    sc.dump()
    sc.op(OP_ELIM)
    sc.dump()


def teardown_section(sc, picks):
    # EliminateAllWitnesses took the track bodies with witnesses along;
    # T5 and T7 never had one, and the new body takes the slot at the head
    # of the free list, T3.
    sc.tag("witnesses and bodies left for the exit-time destructors")
    sc.op(OP_TP_NEW, 27, picks[1])
    sc.op(OP_WIT_NEW, 0, 4)
    sc.op(OP_WIT_NEW, 10, T(7))
    sc.op(OP_WIT_NEW, T(3), 11)
    sc.op(OP_DTOR, T(5), 2, 2)          # the destructor, the slot kept
    sc.op(OP_ACCESS, T(5))
    sc.dump()
    sc.op(OP_STATIC_CLOSE)
    sc.dump()

    sc.tag("CloseCollisionBody, CloseTree, and again from the top")
    sc.op(OP_CLOSE)
    sc.op(OP_TREE_CLOSE)
    sc.dump()
    sc.op(OP_STATIC_INIT)
    sc.op(OP_INIT)
    sc.op(OP_TREE_INIT)
    sc.op(OP_STATIC_NEW, 5, -1, 1)
    sc.op(OP_SETBOX, 5, 0.0, 0.0, 10.0, 1.0)
    sc.op(OP_SETBOX, 5, 0.0, 0.0, 5.0, 1.0)        # the widest of none: 0
    sc.dump()
    sc.op(OP_TP_NEW, 0, picks[2])
    sc.op(OP_NEXTID)
    sc.dump()
    sc.op(OP_CLOSE)                     # a slot still held
    sc.dump()


# ------------------------------------------------- the dynamic bodies' script

NAN = float("nan")
IDENT = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
         (0.0, 0.0, 0.0, 1.0))
ROT0 = ((1.0, 0.0, 0.0, 0.5), (0.0, 1.0, 0.0, -0.5), (0.0, 0.0, 1.0, 0.25),
        (0.0, 0.0, 0.0, 1.0))


def side(pos, vel, rot):
    """DYN_SIDE's 24 words: a position, a velocity, a rotation, every lane."""
    return [float(v) for v in list(pos) + list(vel) + [x for r in rot for x in r]]


def rb_words(rnd, mass):
    """RB_SET's words, image offsets 16 .. 383: Mass and Mass_inv as asked,
    MotionDamping and IsHP as words, every other one a small float."""
    w = []
    for off in range(RB_FIRST, RB_END, 4):
        if off in (272, 276):
            w.append(rnd.randint(0, 1))
        elif off == 280:
            w.append(float(mass))
        elif off == 284:
            w.append(1.0 / mass)
        else:
            w.append(rnd.randint(-24, 24) / 8.0)
    return w


def boxes(sc, spec):
    for r, box in spec:
        sc.op(OP_SETBOX, r, *[float(v) for v in box])


def dyn_setup_section(sc):
    # The first slice's teardown left CloseCollisionBody's state behind;
    # the tree goes too, so the TrackPolygons start again at slot 0.
    sc.tag("DynamicCollisionBody: the constructor, the destructor, the table")
    sc.op(OP_TREE_CLOSE)
    sc.op(OP_STATIC_INIT)
    sc.op(OP_INIT)
    sc.op(OP_TREE_INIT)
    sc.op(OP_VTDUMP)
    for k in range(ND):
        sc.op(OP_FILL_H, D(k), 0xa5)
    sc.op(OP_DYN_NEW, D(0), 40, 1, 1)
    sc.op(OP_DYN_NEW, D(1), 41, 4, 1)
    sc.op(OP_DYN_NEW, D(2), -1, 1, 0)
    sc.op(OP_NEXTID)
    sc.dump()
    for k in range(3):
        sc.op(OP_ACCESS, D(k))
    sc.op(OP_DYN_DTOR, D(2), 0)
    sc.op(OP_ACCESS, D(2))              # the base's table left behind
    sc.op(OP_DYN_NEW, D(2), 42, 1, 1)
    sc.op(OP_STAT, 13, 9)               # the highest stays
    sc.op(OP_VDEL, D(2), 3)             # the table's destructor, and freed
    sc.op(OP_DYN_NEW, D(2), 43, 5, 1)
    sc.op(OP_DYN_NEW, D(3), 44, 1, 1)
    sc.op(OP_STAT, 13, 2)
    sc.op(OP_DYN_DTOR, D(3), 2)
    sc.op(OP_DYN_NEW, D(3), 44, 1, 1)   # the highest follows
    sc.dump()


def dyn_physics_section(sc, rnd):
    sc.tag("the RigidBody and PhysicsSystem pass-throughs, on the class's table")
    sc.op(OP_RB_SET, 0, *rb_words(rnd, 2.0))
    sc.op(OP_RB_SET, 1, *rb_words(rnd, 0.25))
    sc.op(OP_DYN_PTRS, D(0), 1, 0)
    sc.op(OP_DYN_PTRS, D(1), 1, 1)
    sc.op(OP_DYN_POKE, D(0), 100, 0.375)
    sc.op(OP_DYN_POKE, D(0), 84, 7)
    for s in (VT_MAXBACKUP, VT_RECOMPUTE, VT_CURVEL, VT_PHYSMODE, VT_MASSINV,
              VT_INERTIA, VT_ENERGY, VT_BLINKING):
        sc.op(OP_VCALL, D(0), s)
    for s in (VT_CURVEL, VT_MASSINV, VT_INERTIA, VT_ENERGY):
        sc.op(OP_VCALL, D(1), s)
    sc.op(OP_DYN_TESTVEL, D(0))
    sc.op(OP_DYN_TESTVEL, D(1))
    sc.op(OP_VCALL, D(0), VT_APPLY)
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_VCALL, D(0), VT_ENERGY)
    sc.op(OP_DYN_TESTVEL, D(0))
    sc.op(OP_RB_DUMP, 1)
    sc.dump()


def dyn_volumes_section(sc):
    sc.tag("BuildBoundingVolumes")
    verts = ((1.0, 2.0, 3.0), (-2.0, 0.5, -1.0), (0.5, -3.0, 4.0),
             (3.0, 1.0, -2.0), (-1.0, -1.0, 0.5), (0.0, 0.0, -5.0),
             (-2.5, 2.5, 0.0), (0.25, 0.25, 0.25))
    sc.op(OP_DPOLY, 0, 8, 8, *[c for v in verts for c in v])
    sc.op(OP_DYN_SETPOLY, D(0), 0)
    sc.op(OP_DYN_BUILD, D(0))
    sc.op(OP_DYN_BBOX, D(0))
    sc.op(OP_DYN_SETPOLY, D(1), 1)
    for num, vs in (
            (3, ((-1.0, -2.0, -3.0), (4.0, 5.0, 6.0), (-0.5, 7.0, -8.0))),
            (2, ((0.5, 0.5, 9.0), (6.0, -6.0, 1.0), (40.0, 40.0, 40.0))),
            (0, ()),
            (-3, ((50.0, 50.0, 50.0),)),
            (3, ((1.0, 1.0, 1.0), (NAN, 2.0, 3.0), (-4.0, -4.0, -4.0))),
            (1, ((3.0, 4.0, 12.0),)),
            (2, ((-3.0, -4.0, -12.0), (0.0, 0.0, 0.0)))):
        sc.op(OP_DPOLY, 1, num, len(vs), *[c for v in vs for c in v])
        sc.op(OP_DYN_BUILD, D(1))
        sc.op(OP_DYN_BBOX, D(1))
    sc.dump()

    sc.tag("UpdatePosition")
    sc.op(OP_DYN_SETVT, D(0), 1)
    sc.op(OP_DYN_SETVT, D(1), 1)
    sc.op(OP_DYN_SIDE, D(0), *side((12.0, 2.0, 1.0, 9.0), (1, 2, 3, 4), ROT0))
    sc.op(OP_DYN_SIDE, D(1), *side((-3.0, 0.5, 7.0, 0.0), (0, 0, 0, 0), ROT0))
    sc.op(OP_DYN_UPDATE, D(0))
    sc.op(OP_DYN_UPDATE, D(1))
    sc.dump()
    sc.op(OP_DYN_POKE, D(1), 216, 0.5)
    sc.op(OP_DYN_UPDATE, D(1))          # narrower: the widest recomputed
    sc.dump()


def dyn_move_section(sc):
    sc.tag("BeginMove, Interpolate and InterpolateVelocity")
    rot_a = ((0.0, 1.0, 0.0, 0.125), (-1.0, 0.0, 0.0, 0.25),
             (0.0, 0.0, 1.0, -0.5), (4.0, 5.0, 6.0, 1.0))
    rot_b = ((0.5, 1.5, 0.0, -0.125), (-1.5, 0.5, 0.25, 0.75),
             (0.0, -0.25, 2.0, 1.5), (8.0, -3.0, 6.5, 2.0))
    sc.op(OP_DYN_SIDE, D(0),
          *side((12.0, 2.0, 1.0, 0.5), (3.0, -1.0, 0.25, -2.0), rot_a))
    sc.op(OP_DYN_BEGIN, D(0), 0.75)
    sc.dump()
    sc.op(OP_DYN_SIDE, D(0),
          *side((14.0, 1.0, 1.5, 1.5), (-1.0, 3.0, 0.75, 6.0), rot_b))
    for t in (0.0, 0.125, 0.5, 0.75, 1.0, -0.25):
        sc.op(OP_DYN_INTERP, D(0), t)
        sc.op(OP_DYN_INTERPV, D(0), t)
    # 0x358637bd is 1e-6, the threshold: below it the body as it is
    for bt in (0.0, -0.0, -1.0, fbits(0x358637bc), fbits(0x358637bd),
               0.0078125):
        sc.op(OP_DYN_POKE, D(0), 100, bt)
        sc.op(OP_DYN_INTERP, D(0), 2.5e-7)
        sc.op(OP_DYN_INTERPV, D(0), 2.5e-7)
    sc.op(OP_DYN_POKE, D(0), 100, 0.5)
    sc.op(OP_VCALL, D(0), VT_INTERP)

    sc.tag("Backup, through the table's Interpolate")
    sc.op(OP_DYN_BACKUP, D(0), 0.125)
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_VCALL, D(0), VT_BACKUP)
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_DYN_SETVT, D(0), 2)        # testB: Interpolate is a stub
    sc.op(OP_DYN_BACKUP, D(0), 0.375)
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_VCALL, D(0), VT_INTERP)
    sc.op(OP_DYN_POKE, D(0), 100, 0.0)
    sc.op(OP_DYN_BACKUP, D(0), 0.375)   # the velocity as it is
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_DYN_SETVT, D(0), 1)
    sc.op(OP_DYN_POKE, D(0), 100, 0.5)

    sc.tag("the slots testA fills, and SetPosition through them")
    for s in (VT_GETPOS, VT_GETVEL, VT_GETROT, VT_ENABLED, VT_SETPOS,
              VT_MAXBACKUP, VT_BLINKING):
        sc.op(OP_VCALL, D(0), s)
    sc.op(OP_DISABLE, D(0))
    sc.op(OP_VCALL, D(0), VT_ENABLED)
    sc.op(OP_ENABLE, D(0))
    sc.op(OP_ACCESS, D(0))
    sc.dump()


def dyn_local_section(sc):
    sc.tag("GetLocalCollisionBodies")
    for h in range(8):
        sc.op(OP_STATIC_NEW, h, h + 1, 1)
    for h in range(NH):                 # a witness reads its polyhedron
        sc.op(OP_SET_POLY, h, h % NPOLY)
    boxes(sc, ((0, (0, 0, 5, 4)), (1, (8, 0, 9.5, 4)), (2, (9, 1, 10, 2)),
               (3, (11, 5, 12, 6)), (7, (11, -3, 13, -0.5)),
               (D(0), (10, 0, 14, 4)), (4, (13, 4, 16, 5)),
               (5, (14.5, 0, 17, 4)), (6, (14, 0, 20, 4)),
               (D(1), (30, 0, 31, 4))))
    sc.dump()
    for m in (0.0, 0.5, 10.0, 1e8, -1.0, -3.0):
        sc.op(OP_DYN_LOCAL, D(0), m)
    sc.op(OP_DYN_LOCAL, D(1), 0.0)
    sc.op(OP_DYN_LOCAL, D(1), 30.0)


def dyn_witness_section(sc):
    sc.tag("MaybeCreateWitnesses: the boxes, the range, the flags")
    sc.op(OP_STATIC_NEW, 15, 45, 1)
    boxes(sc, ((15, (12, -2, 12.5, 0)),))   # its top on D0's bottom
    sc.op(OP_TC_SET, 0)
    sc.op(OP_SETMAXW, 6.0)
    sc.op(OP_DYN_WITNESSES, D(0))
    sc.dump()
    sc.op(OP_DYN_WITNESSES, D(0))       # every one there already
    sc.op(OP_DISABLE, D(0))
    sc.op(OP_DYN_WITNESSES, D(0))       # not even the track
    sc.op(OP_ENABLE, D(0))

    sc.tag("MaybeCreateWitnesses: a list out of order, a body disabled")
    sc.op(OP_ELIM)
    sc.op(OP_RAWBOX, 4, 13.0, 0.0, 9.0, 4.0)       # after D0, ends before it
    sc.op(OP_RAWBOX, 3, 11.0, 0.0, 9.9, 4.0)       # the walk back stops here
    sc.op(OP_RAWBOX, 7, 11.0, 0.5, 13.0, 1.0)
    sc.op(OP_DISABLE, 6)
    sc.op(OP_DYN_WITNESSES, D(0))
    sc.dump()

    sc.tag("MaybeCreateWitnesses: virgin smokeables")
    sc.op(OP_ELIM)
    sc.op(OP_ENABLE, 6)
    boxes(sc, ((3, (11, 5, 12, 6)), (4, (13, 4, 16, 5)),
               (7, (11, -3, 13, -0.5))))
    sc.op(OP_STATIC_NEW, 8, -1, 2)      # to H9, which comes first
    sc.op(OP_STATIC_NEW, 9, 10, 1)
    sc.op(OP_STATIC_NEW, 10, -1, 2)     # to H11, which comes after
    sc.op(OP_STATIC_NEW, 11, 12, 1)
    sc.op(OP_STATIC_NEW, 12, -1, 2)     # to nothing
    sc.op(OP_STATIC_NEW, 13, -1, 2)     # to H0, which misses D0
    boxes(sc, ((8, (12, 1, 13, 2)), (9, (11.5, 2, 12.5, 3)),
               (10, (11, 0, 11.8, 1)), (11, (12.6, 0, 13.5, 1)),
               (12, (10.5, 3, 11, 4)), (13, (12, 3.5, 12.25, 3.75))))
    sc.op(OP_SMOKE, 8, 9)
    sc.op(OP_SMOKE, 10, 11)
    sc.op(OP_SMOKE, 12, -1)
    sc.op(OP_SMOKE, 13, 0)
    sc.op(OP_DYN_WITNESSES, D(0))
    sc.dump()


def dyn_tp_section(sc, rnd):
    sc.tag("CreateTrackPolygonCollisionBodies: which polygons, in what order")
    sc.op(OP_ELIM)
    # D0 upright at (12, 2, 1): base 1, top 2, radius 1.5
    sc.op(OP_DYN_SIDE, D(0), *side((12.0, 2.0, 1.0, 1.0), (0, 0, 0, 0),
                                   IDENT))
    sc.op(OP_DYN_POKE, D(0), 208, 1.0)
    sc.op(OP_DYN_POKE, D(0), 212, 2.0)
    sc.op(OP_DYN_POKE, D(0), 216, 1.5)
    polys = (250, 251, 252, 253, 254, 255, 210, 230, 240)
    for p in polys:
        sc.op(OP_TP_ASSIGN, p)          # P0 .. P8
    geo = ((10, 0, 14, 4, 0.5),         # P0 passes
           (10, 0, 14, 4, -0.5),        # P1 fails the check
           (5, 0, 9, 4, 0.5),           # P2 ends before D0
           (15, 0, 18, 4, 0.5),         # P3 starts after it
           (11, -3, 12, -1, 0.5),       # P4 below it
           (11, 5, 12, 6, 0.5),         # P5 above it
           (9, 3, 10, 5, 2.5),          # P6 at a corner, behind: the top
           (12, 1, 13, 2, 0.5),         # P7 passes
           (11, 1, 12, 2, 0.5))         # P8 passes, but has a body
    for s, (x0, y0, x1, y1, pd) in enumerate(geo):
        sc.op(OP_TP_GEOM, s, float(x0), float(y0), float(x1), float(y1),
              0.0, 0.0, 1.0, float(pd))
    sc.op(OP_TP_NEW, 60, polys[8])
    sc.op(OP_TC_SET, 9, *range(9))
    sc.op(OP_DYN_CREATE_TP, D(0))
    sc.dump()
    sc.op(OP_DYN_CREATE_TP, D(0))       # none left to make
    sc.op(OP_DYN_WITNESSES, D(0))       # the track bodies among them
    sc.dump()

    sc.tag("MaybeCreateWitnesses reads the widest after the track bodies")
    sc.op(OP_ELIM)
    sc.op(OP_TP_ASSIGN, 220)            # P9, 30 wide
    sc.op(OP_TP_GEOM, 9, 10.0, 0.0, 40.0, 4.0, 0.0, 0.0, 1.0, 0.5)
    sc.op(OP_STATIC_NEW, 14, 14, 1)
    sc.op(OP_SETBOX, 14, 13.0, 0.0, 26.0, 4.0)
    sc.op(OP_TC_SET, 1, 9)
    sc.op(OP_SETMAXW, 2.0)              # stale: H14 alone is 13 wide
    sc.op(OP_DYN_WITNESSES, D(0))
    sc.dump()

    sc.tag("MaybeCreateWitnesses trusts the widest: wider bodies are missed")
    sc.op(OP_ELIM)
    sc.op(OP_TC_SET, 0)
    sc.op(OP_SETMAXW, 2.0)              # the walk stops at the first past 16
    sc.op(OP_DYN_WITNESSES, D(0))
    sc.dump()

    sc.tag("CreateTrackPolygonCollisionBodies: past 48, and the pool full")
    sc.op(OP_ELIM)
    first, many = 10, 52
    for k in range(many):
        sc.op(OP_TP_ASSIGN, 300 + k)    # P10 .. P61
    for k in range(many):
        sc.op(OP_TP_GEOM, first + k, 10.0 + k % 4, float(k % 3),
              11.0 + k % 4, 1.0 + k % 3, 0.0, 0.0, 1.0, 0.5)
    order = list(range(first, first + many))
    rnd.shuffle(order)
    sc.op(OP_TC_SET, many, *order)
    sc.op(OP_DYN_CREATE_TP, D(0))       # the first 48 in pTC's order
    sc.dump()
    sc.op(OP_TP_ASSIGN, 400)            # P62, far off
    sc.op(OP_TP_GEOM, 62, 1000.0, 1000.0, 1001.0, 1001.0, 0.0, 0.0, 1.0, 0.0)
    sc.op(OP_TP_FILL, 400, 158)
    for k in range(5):
        sc.op(OP_TP_ASSIGN, 360 + k)    # P63 .. P67
        sc.op(OP_TP_GEOM, 63 + k, 12.0, 1.0, 13.0, 2.0, 0.0, 0.0, 1.0, 0.5)
    sc.op(OP_TC_SET, 5, 67, 66, 65, 64, 63)
    sc.op(OP_DYN_CREATE_TP, D(0))       # two made, then full
    sc.op(OP_DYN_CREATE_TP, D(0))       # full at once
    sc.dump()


def dyn_tpcheck_section(sc):
    sc.tag("TrackPolygonCheck: the plane against the cylinder")
    sc.op(OP_DYN_POKE, D(1), 208, 1.0)
    sc.op(OP_DYN_POKE, D(1), 212, 2.0)
    sc.op(OP_DYN_POKE, D(1), 216, 1.5)
    cases = (
        # row 2 of the rotation, the position, the normal, the distance
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 0.5),        # the base: .5 < 1
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), -0.5),       # 1.5 < 1, no
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 2.5),        # behind: the top
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 3.5),
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 0.0),        # 1 < 1, no
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 3.0),        # 2 < 2, no
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), 1.0),        # on the plane: the base
        ((0, 0, -1), (0, 0, 1), (0, 0, 1), 0.5),       # facing away: the top
        ((0, 0, -1), (0, 0, 1), (0, 0, 1), -0.5),
        ((0.6, 0, 0.8), (0, 0, 1), (0, 0, 1), -0.5),   # .8 + .6 * 1.5 = 1.7
        ((0.6, 0, 0.8), (0, 0, 1), (0, 0, 1), -0.75),
        ((0, 0, 1.25), (0, 0, 1), (0, 0, 1), -1.25),   # the root of -0.5625
        ((0, 0, 1.25), (0, 0, 1), (0, 0, 1), -1.5),
        ((0.8, 0.6, 0), (1, 2, 0), (0.6, 0.8, 0), 1.0),  # the base
        ((0.8, 0.6, 0), (1, 2, 0), (0.6, 0.8, 0), 4.0),  # behind: the top
        ((0.8, 0.6, 0), (1, 2, 0), (0.6, 0.8, 0), 5.0),
        ((0, 0, 1), (NAN, 0, 1), (0, 0, 1), 0.5),
        ((0, 0, 1), (0, 0, 1), (0, 0, 1), NAN),
        ((0, NAN, 1), (0, 0, 1), (0, 0, 1), 0.5),
        # (1.5 + b) + c rounds to 1.5, not below: 1.5 < 1.5, no
        ((1, -1, 0), (1.5, -2.0 ** -24, -2.0 ** -24), (1, 1, 1), 0.0),
        # (1 + b) + c rounds to an up of 1: no lean, and 1 < 1, no
        ((1, -2.0 ** -25, -2.0 ** -25), (1, 0, 0), (1, 1, 1), 0.0))
    for row2, pos, n, pd in cases:
        rot = (ROT0[0], ROT0[1], tuple(row2) + (0.5,), ROT0[3])
        sc.op(OP_DYN_SIDE, D(1), *side(tuple(pos) + (0.0,), (0, 0, 0, 0),
                                       rot))
        sc.op(OP_TP_GEOM, 0, 0.0, 0.0, 1.0, 1.0,
              *[float(c) for c in n], float(pd))
        sc.op(OP_DYN_TPCHECK, D(1), 0)
    sc.op(OP_DYN_POKE, D(1), 208, 0.0)
    rot = (ROT0[0], ROT0[1], (0.0, 0.0, 1.0, 0.5), ROT0[3])
    sc.op(OP_DYN_SIDE, D(1), *side((0.0, 0.0, 1.0, 0.0), (0, 0, 0, 0), rot))
    sc.op(OP_TP_GEOM, 0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0)
    sc.op(OP_DYN_TPCHECK, D(1), 0)      # on the plane with no base: 0 < 0


def dyn_teardown_section(sc):
    sc.tag("a dynamic body's destructor takes its witnesses along")
    sc.op(OP_WIT_NEW, D(1), 9)
    sc.op(OP_WIT_NEW, 2, D(1))
    sc.op(OP_DYN_DTOR, D(1), 0)
    sc.dump()

    sc.tag("the exit-time destructors, CloseCollisionBody and CloseTree")
    sc.op(OP_STATIC_CLOSE)
    sc.dump()
    sc.op(OP_CLOSE)
    sc.op(OP_TREE_CLOSE)
    sc.dump()


# ------------------------------------------------------- CarCollisionBody


def bhash(s):
    """bStringHash, 0x0023b280: djb2 seeded with -1."""
    h = M32
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


def flat(vs):
    return [float(c) for v in vs for c in v]


def rb_words_rot(rnd, minv, rot):
    """rb_words with Mass_inv as given and State.R (32 .. 95) `rot`."""
    w = rb_words(rnd, 1.0)
    w[(284 - RB_FIRST) // 4] = minv
    for i in range(16):
        w[(32 - RB_FIRST) // 4 + i] = float(rot[i // 4][i % 4])
    return w


ROT_Z = ((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
         (0.0, 0.0, 0.0, 1.0))


def car_setup_section(sc):
    sc.tag("CarCollisionBody: the constructor, on the disc's volume and a box")
    pp0 = ((2.0, 1.0, 0.5), (-2.25, 1.0, 0.5), (2.0, -1.0, 0.5),
           (-2.25, -1.0, 0.5), (0.5, 0.0, 1.25), (-0.5, 0.25, -0.25))
    pp1 = ((5.0, 1.5, 1.0), (-5.0, 1.5, 1.0), (5.0, -1.5, -0.5),
           (-5.0, -1.5, -0.5))
    sc.op(OP_PP, 0, bhash("DIABLO_CV"), 1, len(pp0), *flat(pp0))
    sc.op(OP_PP, 1, bhash("BUS_CV"), 0, len(pp1), *flat(pp1))
    rot_c = ((0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0),
             (0.0, 0.0, 1.0, 0.0), (20.0, 2.0, 1.0, 1.0))
    cars = ((3, 0, (20.0, 2.0, 1.0, 1.0), IDENT, (0.25, -0.5, 0.125, 0.0)),
            (-7, 2, (24.0, 2.5, 1.0, 0.0), ROT0, (0.0, 0.0, 0.0, 0.0)),
            (11, 1, (26.0, -1.0, 0.5, 0.0), rot_c, (0.25, -0.5, 0.125, 2.0)))
    for k, (drv, name, pos, rot, cog) in enumerate(cars):
        sc.op(OP_CAR_FIELD, k, CF_DRIVER, drv)
        sc.op(OP_CAR_FIELD, k, CF_NAME, name)
        sc.op(OP_CAR_SIDE, k, *side(pos, (1.0, -2.0, 0.5, 0.0), rot))
        sc.op(OP_CAR_COG, k, *[float(c) for c in cog])
    sc.op(OP_GLOBAL, G_TIMER, 123456)
    sc.op(OP_CAR_NEW, 0)                # PP0, fixed already
    sc.op(OP_CAR_NEW, 1)                # no volume: the box
    sc.op(OP_GLOBAL, G_TIMER, -5)
    sc.op(OP_CAR_NEW, 2)                # PP1, moved to the centre of gravity
    sc.dump()
    for s in range(3):
        sc.op(OP_ACCESS, K(s))
    sc.op(OP_CAR_TIMES, K(0), 0x12345678, 0x9abcdef0)
    sc.op(OP_CAR_TIMES, K(2), 7, 0)

    sc.tag("CarCollisionBody's destructor: the box goes, the disc's stays")
    sc.op(OP_CAR_DTOR, K(1), 0)         # the box destroyed, the slot kept
    sc.op(OP_VDEL, K(2), 3)             # through the table, and freed
    sc.dump()
    sc.op(OP_CAR_NEW, 2)                # K2 again, and PP1 fixed now
    sc.dump()                           # two cars, and the highest still 3
    sc.op(OP_CAR_NEW, 1)                # K3, a second box
    sc.dump()

    sc.tag("CarCollisionBody's destructor: a volume unloaded since, and none")
    sc.op(OP_CAR_FIELD, 0, CF_NAME, 2)  # CAR0's `_CV` gone: PP0 destroyed
    sc.op(OP_CAR_DTOR, K(0), 1)
    sc.op(OP_CAR_NEW, 0)                # K0 again, on a box
    sc.op(OP_DYN_POKE, K(0), 8, 0)      # and then no volume at all
    sc.op(OP_CAR_DTOR, K(0), 1)
    sc.op(OP_CAR_FIELD, 0, CF_NAME, 0)
    sc.op(OP_CAR_NEW, 0)                # K0 on PP0 again
    sc.dump()


def car_methods_section(sc, rnd):
    sc.tag("CarCollisionBody: the getters on rails and in physics mode")
    sc.op(OP_RB_SET, 0, *rb_words(rnd, 2.0))
    for s in (VT_GETPOS, VT_GETVEL, VT_GETROT):
        sc.op(OP_VCALL, K(0), s)
    sc.op(OP_DYN_PTRS, K(0), 1, 0)
    sc.op(OP_DYN_POKE, K(0), 84, 1)
    for s in (VT_GETPOS, VT_GETVEL, VT_GETROT):
        sc.op(OP_VCALL, K(0), s)

    sc.tag("CarCollisionBody: the constants, the mass and the inertia")
    for s in (VT_CONSIDER, VT_TERRAIN, VT_MOVEABLE, VT_BOUNCE, VT_FRICTION,
              VT_MASSINV, VT_INERTIA, VT_MAXBACKUP, VT_CURVEL, VT_TESTVEL,
              VT_ENERGY, VT_RECOMPUTE, VT_SETPOS, VT_INTERP, VT_BACKUP):
        sc.op(OP_VCALL, K(0), s)
    sc.dump()
    # 0x3f44ec4f is the bound itself, 1 / 1.3
    for minv in (4.0, fbits(0x3f44ec4f), fbits(0x3f44ec50), fbits(0x3f44ec4e),
                 0.0, -1.0, NAN, float("inf")):
        sc.op(OP_RB_SET, 1, *rb_words_rot(rnd, minv, ROT0))
        sc.op(OP_DYN_PTRS, K(0), 1, 1)
        sc.op(OP_VCALL, K(0), VT_MASSINV)
        sc.op(OP_VCALL, K(0), VT_INERTIA)
    sc.dump()

    sc.tag("CarCollisionBody: AreCollisionsEnabled and IsBlinking")
    for g in (G_BORING, G_WILLIAMS):
        for v in (1, -1, 0):
            sc.op(OP_GLOBAL, g, v)
            sc.op(OP_VCALL, K(0), VT_ENABLED)
    sc.op(OP_DISABLE, K(0))
    sc.op(OP_VCALL, K(0), VT_ENABLED)
    sc.op(OP_GLOBAL, G_WILLIAMS, 1)
    sc.op(OP_VCALL, K(0), VT_ENABLED)
    sc.op(OP_GLOBAL, G_WILLIAMS, 0)
    sc.op(OP_ENABLE, K(0))
    sc.op(OP_VCALL, K(0), VT_ENABLED)
    for bl, po in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0), (0, 2)):
        sc.op(OP_CAR_FIELD, 0, CF_BLINK, bl)
        sc.op(OP_CAR_FIELD, 0, CF_POOF, po)
        sc.op(OP_VCALL, K(0), VT_BLINKING)
    sc.op(OP_CAR_FIELD, 0, CF_POOF, 0)


def car_move_section(sc):
    sc.tag("CarCollisionBody::Move: a step the car finishes, and one it does not")
    sc.op(OP_DYN_POKE, K(0), 84, 0)
    sc.op(OP_DYN_PTRS, K(0), 0, -1)
    steps = ((0.25, (0.25,)), (0.25, (0.125, 0.125)), (0.25, (0.3,)),
             (0.25, (NAN,)), (0.3, (0.1, 0.2)), (0.5, (-0.0, 0.5)),
             (0.0, (-1.0, 1.0)), (0.0, (0.0,)), (NAN, (0.125,)),
             (0.25, (fbits(0x3e7fffff), 0.0)))
    for t, rets in steps:
        sc.op(OP_CAR_MOVE, K(0), t, len(rets), *rets)
    sc.dump()

    sc.tag("Move into physics mode: SetupPhysicsPointers finds the mover's")
    sc.op(OP_CAR_FIELD, 0, CF_MODE, 1)
    sc.op(OP_CAR_FIELD, 0, CF_MOVER, 1)
    sc.op(OP_DYN_POKE, K(0), 84, 1)
    sc.op(OP_DYN_PTRS, K(0), 1, 0)      # BeginMove reads RB0, the update RB1
    sc.op(OP_CAR_MOVE, K(0), 0.25, 2, 0.0625, 0.1875)
    sc.dump()
    sc.op(OP_CAR_FIELD, 0, CF_MODE, 2)  # neither physics nor mellow: none
    sc.op(OP_CAR_STPM, K(0), -1)
    sc.op(OP_CAR_FIELD, 0, CF_MODE, 4)  # mellow: M1's, at the same offsets
    sc.op(OP_CAR_FIELD, 0, CF_MOVER, 2)
    sc.op(OP_CAR_STPM, K(0), -1)
    sc.op(OP_CAR_FIELD, 0, CF_MODE, 1)
    sc.op(OP_CAR_FIELD, 0, CF_MOVER, 1)
    sc.op(OP_DYN_POKE, K(0), 84, 0)     # on rails: the pointers cleared
    sc.op(OP_CAR_STPM, K(0), -1)
    sc.dump()

    sc.tag("SetToPhysicsMode through the table: another car's body, or not")
    sc.op(OP_DYN_POKE, K(0), 84, 1)
    for o in (K(2), D(0), -1, K(3)):
        sc.op(OP_CAR_STPM, K(0), o)
    sc.op(OP_VCALL, K(0), VT_PHYSMODE)
    sc.dump()


def car_impulse_section(sc, rnd):
    sc.tag("ApplyImpulse: the scale, the length, the damage and the reaction")
    sc.op(OP_RB_SET, 0, *rb_words_rot(rnd, 0.5, ROT_Z))
    sc.op(OP_DYN_PTRS, K(0), 1, 0)
    sc.op(OP_DYN_POKE, K(0), 84, 1)
    for f in (CF_PLAYER, CF_ANIM, CF_DAMAGE):
        sc.op(OP_CAR_FIELD, 0, f, 1)
    sc.op(OP_GLOBAL, G_RC, 1)
    sc.op(OP_GLOBAL, G_STATE, 3)
    sc.op(OP_GLOBAL, G_COP, 1)
    sc.op(OP_GLOBAL, G_PORT, 1)
    at = (0.5, -0.25, 0.75, 1.0)
    for j in ((1.0, 2.0, 0.5, 0.25),       # 2.29: the damage alone
              (3.0, 4.0, 0.0, -1.0),       # 5: the light flinch
              (30.0, 1.0, 0.0, 0.0), (-30.0, 1.0, 0.0, 0.0),
              (1.0, 30.0, 0.0, 0.0), (1.0, -30.0, 0.0, 0.0),
              (12.0, 16.0, 0.0, 0.0),      # 20 exactly: not past it
              (0.0, 0.0, 4.0, 0.0),        # 4 exactly
              (4.5, 0.1, 0.2, 0.0),        # the sum's order shows in the root
              (2000.0, 0.0, 0.0, 0.0)):    # past RigidBody's 1000
        sc.op(OP_CAR_APPLY, K(0), *(list(j) + list(at)))
    sc.op(OP_RB_DUMP, 0)
    sc.op(OP_RB_SET, 1, *rb_words_rot(rnd, 4.0, ROT0))
    sc.op(OP_DYN_PTRS, K(0), 1, 1)
    sc.op(OP_CAR_APPLY, K(0), *([26.0, 0.0, 0.0, 3.0] + list(at)))
    sc.op(OP_CAR_APPLY, K(0), *([130.0, 0.0, 0.0, 3.0] + list(at)))
    sc.op(OP_CAR_APPLY, K(0), *([10.0, 20.0, -15.0, 3.0] + list(at)))
    sc.op(OP_RB_DUMP, 1)
    sc.dump()


def car_damage_section(sc):
    sc.tag("AddDamage: the rumble in each race state")
    at = [1.0, 2.0, 3.0, 1.0]
    for st in list(range(-1, 11)) + [0x7fffffff, -0x80000000]:
        sc.op(OP_GLOBAL, G_STATE, st)
        sc.op(OP_CAR_DAMAGE, K(0), *(at + [10.0]))
    sc.tag("AddDamage: no race, no player, no damage, no cop manager")
    sc.op(OP_GLOBAL, G_STATE, 3)
    sc.op(OP_GLOBAL, G_RC, 0)
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [2.5]))
    sc.op(OP_GLOBAL, G_RC, 1)
    sc.op(OP_CAR_FIELD, 0, CF_PLAYER, 0)
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [2.5]))
    sc.op(OP_CAR_FIELD, 0, CF_PLAYER, 1)
    sc.op(OP_CAR_FIELD, 0, CF_DAMAGE, 0)
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [NAN]))
    sc.op(OP_CAR_FIELD, 0, CF_DAMAGE, 1)
    sc.op(OP_GLOBAL, G_COP, 0)
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [-0.0]))
    sc.op(OP_GLOBAL, G_COP, 1)
    sc.op(OP_GLOBAL, G_PORT, 3)
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [1e30]))
    sc.tag("AddDamage and the reaction with the port's two seams unset")
    sc.op(OP_GLOBAL, G_SEAMS, 1)        # no rumble
    sc.op(OP_CAR_DAMAGE, K(0), *(at + [10.0]))
    sc.op(OP_GLOBAL, G_SEAMS, 2)        # no force impact
    sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, 25.0)
    sc.op(OP_GLOBAL, G_SEAMS, 0)


def car_anim_section(sc, rnd):
    sc.tag("AnimateCollisionReaction: which flinch, past 20 and past 4")
    sc.op(OP_RB_SET, 0, *rb_words_rot(rnd, 0.5, IDENT))
    sc.op(OP_DYN_PTRS, K(0), 1, 0)
    dirs = ((1.0, 0.5, 0.0, 0.0), (-1.0, 0.5, 0.0, 0.0),
            (0.5, 1.0, 0.0, 0.0), (0.5, -1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0, 0.0), (-1.0, -1.0, 0.0, 0.0),
            (1.0, -1.0, 0.0, 0.0), (-1.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0), (-0.0, -0.0, 1.0, 0.0),
            (NAN, 1.0, 0.0, 0.0), (1.0, NAN, 0.0, 0.0))
    for j in dirs:
        sc.op(OP_CAR_ANIM, K(0), *(list(j) + [25.0]))
    # 0x41a00001 is one ulp past 20, 0x40800001 one past 4
    for amt in (fbits(0x41a00001), 20.0, 10.0, fbits(0x40800001), 4.0, 3.0,
                NAN, -25.0, float("inf")):
        sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, amt)

    sc.tag("AnimateCollisionReaction: a turned car; no driver; no player")
    sc.op(OP_RB_SET, 0, *rb_words_rot(rnd, 0.5, ROT0))
    for j in dirs[:4]:
        sc.op(OP_CAR_ANIM, K(0), *(list(j) + [25.0]))
    sc.op(OP_CAR_FIELD, 0, CF_ANIM, 0)
    sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, 25.0)
    sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, 10.0)
    sc.op(OP_CAR_FIELD, 0, CF_ANIM, 1)
    sc.op(OP_CAR_FIELD, 0, CF_PLAYER, 0)
    sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, 25.0)
    sc.op(OP_CAR_ANIM, K(0), 1.0, 0.5, 0.0, 0.0, 10.0)
    sc.op(OP_CAR_FIELD, 0, CF_PLAYER, 1)


def car_teardown_section(sc):
    sc.tag("CarCollisionBody: the rest go, but K2, left to the exit")
    sc.op(OP_CAR_DTOR, K(0), 1)
    sc.op(OP_VDEL, K(3), 1)
    sc.dump()


# ---------------------------------------------------------------- Contact

ZEROM = ((0.0,) * 4,) * 4
NEWEST = REF_NEWEST


def LP(n):
    """A contact operand: the nth on clist."""
    return REF_LIST + n


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, s, 0.0, 0.0), (-s, c, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0))


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0, 0.0), (0.0, c, s, 0.0), (0.0, -s, c, 0.0),
            (0.0, 0.0, 0.0, 1.0))


class EBody(object):
    """What testC's stubs answer for one contact body, as E_STATE sends it."""

    def __init__(self, k):
        self.k = k
        self.pos = (0.0, 0.0, 0.0, 0.0)
        self.vel = (0.0, 0.0, 0.0, 0.0)
        self.rot = IDENT
        self.cv = (0.0, 0.0, 0.0, 0.0)
        self.cw = (0.0, 0.0, 0.0, 0.0)
        self.inertia = ZEROM
        self.maxbackup, self.minv = 1.0, 1.0
        self.bounce, self.friction = 0.1, 0.5
        self.moveable, self.blinking = 1, 0

    def put(self, sc, **kw):
        for k, v in kw.items():
            assert hasattr(self, k), k
            setattr(self, k, v)
        sc.op(OP_E_STATE, self.k,
              *(flat([self.pos, self.vel]) + flat(self.rot)
                + flat([self.cv, self.cw]) + flat(self.inertia)
                + [float(self.maxbackup), float(self.minv),
                   float(self.bounce), float(self.friction)]),
              self.moveable, self.blinking)


def tp_body(sc, id_, poly, verts, normal, bbox=(-8.0, -8.0, 8.0, 8.0)):
    """A TrackPolygon body on tree polygon `poly`, its wafer on `verts`."""
    k = sc.ntps
    sc.op(OP_TP_ASSIGN, poly)
    sc.op(OP_TP_VERTS, k, *flat([tuple(v) + (0.0,) * (4 - len(v))
                                 for v in verts]))
    sc.op(OP_TP_GEOM, k, *[float(c) for c in bbox],
          *[float(c) for c in normal], 0.0)
    sc.op(OP_TP_NEW, id_, poly)
    return k


def inertia(rnd):
    return tuple(tuple(rnd.uniform(0.2, 0.6) if i == j
                       else rnd.uniform(-0.05, 0.05) if i < 3 and j < 3
                       else 0.0 for j in range(4)) for i in range(4))


def vec4(rnd, lo=-2.0, hi=2.0):
    return tuple(rnd.uniform(lo, hi) for _ in range(4))


# The witnesses, in the order contact_setup_section makes them.
W_EE, W_TE, W_ET, W_EE2, W_T1E, W_ET1 = range(6)


def contact_setup_section(sc, chunk):
    sc.tag("contacts: InitContact, the bodies and their witnesses")
    sc.op(OP_STATIC_INIT)
    sc.op(OP_INIT)
    sc.op(OP_TREE_INIT)
    words = struct.unpack("<%dI" % (len(chunk) // 4), chunk)
    sc.op(OP_TREE_LOAD, len(words), *words)
    sc.op(OP_CT_DUMP)                   # no pool yet
    sc.op(OP_CT_INIT)
    sc.op(OP_CT_DUMP)
    for k, box in enumerate(((1.0, -1.0, 0.5, -0.5, 0.25, -0.25),
                             (0.5, -0.5, 0.5, -0.5, 0.5, -0.5),
                             (0.5, -0.5, 0.5, -0.5, 0.25, -0.25),
                             (0.75, -0.25, 0.3, -0.6, 0.4, -0.2))):
        sc.op(OP_BOX, k, *[float(c) for c in box])
    es = [EBody(k) for k in range(NE)]
    for k in range(NE):
        sc.op(OP_FILL_H, E(k), 0xa5)
        sc.op(OP_DYN_NEW, E(k), 10 + k, 0, 0)
        sc.op(OP_DYN_SETVT, E(k), 3)
        sc.op(OP_BOX_SET, E(k), k)
        es[k].put(sc)
    es[1].put(sc, pos=(5.0, 0.0, 0.0, 0.0))
    es[2].put(sc, pos=(0.0, 0.0, 3.0, 0.0))
    es[3].put(sc, pos=(0.0, 0.0, 3.0, 0.0))
    # T0 a flat quad at z = 0, facing up; T1 a triangle through the origin
    # facing up and towards -y
    tp_body(sc, 20, 450, ((-4, -4, 0), (4, -4, 0), (4, 4, 0), (-4, 4, 0)),
            (0.0, 0.0, 1.0))
    tp_body(sc, 21, 451, ((-4, -4, -3), (4, -4, -3), (0, 4, 3), (0, 4, 3)),
            (0.0, -0.6, 0.8))
    sc.op(OP_WIT_NEW, E(0), E(1))       # W0
    sc.op(OP_WIT_NEW, T(0), E(2))       # W1: a track body first
    sc.op(OP_WIT_NEW, E(3), T(0))       # W2: a track body second
    sc.op(OP_WIT_NEW, E(2), E(3))       # W3
    sc.op(OP_WIT_NEW, T(1), E(1))       # W4
    sc.op(OP_WIT_NEW, E(3), T(1))       # W5
    sc.dump()
    return es


def contact_test_section(sc, es):
    sc.tag("TestForContact: the bisection finds them touching")
    sc.op(OP_GLOBAL, G_TIMER, 1234)
    sc.op(OP_GLOBAL, G_LOOP, 7)
    es[1].put(sc, pos=(1.2, 0.0, 0.0, 0.0), vel=(-2.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_CT_DUMP)
    sc.dump()

    sc.tag("TestForContact: apart, and PrintThisTime cleared")
    es[1].put(sc, pos=(5.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_GLOBAL, G_PRINT, 1)
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_GLOBAL, G_PRINT, 5)
    es[1].put(sc, pos=(1.2, 0.0, 0.0, 0.0))
    sc.op(OP_GLOBAL, G_TIMER, 2000)
    sc.op(OP_GLOBAL, G_LOOP, 8)
    sc.op(OP_CT_TEST, W_EE)             # the same time: after the first
    sc.op(OP_CT_DUMP)

    sc.tag("TestForContact: a blinking car goes through, and is stamped")
    sc.op(OP_GLOBAL, G_TIMER, 3000)
    es[0].put(sc, blinking=1)
    sc.op(OP_CT_TEST, W_EE)
    es[0].put(sc, blinking=0)
    es[1].put(sc, blinking=1)
    sc.op(OP_GLOBAL, G_TIMER, 3100)
    sc.op(OP_CT_TEST, W_EE)
    sc.dump()
    sc.op(OP_SETB, E(1), F_TYPE, 1)     # not a car
    sc.op(OP_GLOBAL, G_TIMER, 3200)
    sc.op(OP_CT_TEST, W_EE)
    sc.dump()                           # E1 kept 3100
    sc.op(OP_SETB, E(1), F_TYPE, 0)
    sc.op(OP_SETB, E(0), F_TYPE, 2)
    sc.op(OP_GLOBAL, G_TIMER, 3300)
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_SETB, E(0), F_TYPE, 0)
    sc.dump()
    sc.op(OP_SETB, E(1), F_DYN, 0)      # not both dynamic: a contact
    sc.op(OP_GLOBAL, G_TIMER, 3400)
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_SETB, E(1), F_DYN, 1)
    sc.op(OP_SETB, E(0), F_DYN, 0)
    sc.op(OP_GLOBAL, G_TIMER, 3500)
    sc.op(OP_CT_TEST, W_EE)
    sc.op(OP_SETB, E(0), F_DYN, 1)
    es[1].put(sc, blinking=0)
    sc.op(OP_CT_DUMP)
    sc.dump()

    sc.tag("TestForContact: what stirs the yaw control")
    sc.op(OP_GLOBAL, G_TIMER, 4000)
    sc.op(OP_SETB, E(1), F_TYPE, 0xff)  # -1: nothing stirs it
    sc.op(OP_CT_TEST, W_EE)
    sc.dump()                           # and E1, not a car, is not stamped
    sc.op(OP_SETB, E(0), F_TYPE, 1)
    sc.op(OP_SETB, E(1), F_TYPE, 0)
    sc.op(OP_GLOBAL, G_TIMER, 4100)
    sc.op(OP_CT_TEST, W_EE)             # only E1 is a car
    sc.op(OP_SETB, E(0), F_TYPE, 0)
    sc.dump()
    # E2 into T0 from above, E3 likewise from below it
    es[2].put(sc, pos=(0.5, 0.25, 0.2, 0.0), vel=(0.0, 0.0, -1.0, 0.0))
    es[3].put(sc, pos=(-0.5, 0.25, -0.1, 0.0), vel=(0.5, 0.0, 1.0, 0.0),
              maxbackup=0.25)
    sc.op(OP_TPPOKE, 0, 10, 0x02)       # T0's polygon stirs it
    sc.op(OP_GLOBAL, G_TIMER, 4200)
    sc.op(OP_GLOBAL, G_LOOP, 9)
    sc.op(OP_CT_TEST, W_TE)
    sc.op(OP_CT_TEST, W_ET)
    sc.dump()
    sc.op(OP_TPPOKE, 0, 10, 0xfd)       # and now does not
    sc.op(OP_GLOBAL, G_TIMER, 4300)
    sc.op(OP_CT_TEST, W_TE)
    sc.op(OP_CT_TEST, W_ET)
    sc.op(OP_CT_DUMP)
    sc.dump()


def contact_list_section(sc, es):
    sc.tag("RemoveContacts")
    sc.op(OP_CT_REMOVE, E(3))           # the last
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_REMOVE, 5)              # on none of them
    sc.op(OP_CT_REMOVE, E(0))           # the first run of them
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_REMOVE, T(0))
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_REMOVE, E(2))           # an empty list
    sc.op(OP_CT_DUMP)

    sc.tag("AddSorted: the longest backup first, a tie after")
    es[1].put(sc, pos=(1.2, 0.0, 0.0, 0.0), vel=(-2.0, 0.0, 0.0, 0.0))
    for bt in (0.5, 0.3, 0.1):
        sc.op(OP_CT_NEW, W_EE)
        sc.op(OP_CT_POKE, NEWEST, XF_BT, float(bt))
        sc.op(OP_CT_LINK, NEWEST)
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_TEST, W_EE)             # 0.15625: before the 0.1
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_POKE, LP(0), XF_BT, 0.15625)
    sc.op(OP_CT_TEST, W_EE)             # after both ties, before the 0.1
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_POKE, LP(4), XF_BT, 0.2)
    sc.op(OP_CT_TEST, W_EE)             # at the tail
    sc.op(OP_CT_POKE, LP(0), XF_BT, 0.125)
    sc.op(OP_CT_TEST, W_EE)             # at the head
    sc.op(OP_CT_DUMP)

    sc.tag("ContactTimeSorting")
    for a, b in ((0, 1), (1, 0), (1, 2), (2, 1), (1, 1), (0, 6)):
        sc.op(OP_CT_SORT, LP(a), LP(b))
    sc.op(OP_CT_POKE, LP(1), XF_BT, 0x7fc00000)    # a NaN
    sc.op(OP_CT_POKE, LP(2), XF_BT, 0x80000000)    # -0 against 0
    sc.op(OP_CT_POKE, LP(3), XF_BT, 0.0)
    for a, b in ((1, 0), (0, 1), (2, 3), (3, 2)):
        sc.op(OP_CT_SORT, LP(a), LP(b))
    sc.op(OP_CT_REMOVE, E(1))
    sc.op(OP_CT_DUMP)

    sc.tag("the contact's destructor and its delete")
    sc.op(OP_CT_NEW, W_EE)
    sc.op(OP_CT_DEL, NEWEST, 0)         # a bTNode's: nothing
    sc.op(OP_CT_DEL, NEWEST, 2)
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_DEL, NEWEST, 1)
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_NEW, W_EE)              # the same slot again
    sc.op(OP_CT_DEL, NEWEST, 3)
    sc.op(OP_CT_DUMP)


def contact_time_section(sc, es):
    sc.tag("FindContactTime: eight steps and Crowbar")
    es[1].put(sc, pos=(1.25, 0.0, 0.0, 0.0), vel=(0.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_NEW, W_EE)              # overlapping by 0.25: three steps
    sc.op(OP_CT_DUMP)
    for m0, m1 in ((1, 0), (0, 1), (0, 0)):
        es[0].put(sc, moveable=m0)
        es[1].put(sc, moveable=m1)
        sc.op(OP_CT_TIME, NEWEST)
    es[0].put(sc, moveable=1)
    es[1].put(sc, moveable=1)
    es[1].put(sc, pos=(0.4, 0.1, 0.05, 0.0))        # deep: thirteen or so
    sc.op(OP_CT_TIME, NEWEST)
    es[1].put(sc, moveable=0)
    sc.op(OP_CT_TIME, NEWEST)                       # twenty, and not apart
    es[1].put(sc, moveable=1)
    # off the axis, turned, and with the fourth lanes set
    es[0].put(sc, pos=(0.25, -0.5, 0.125, 1.0), rot=rot_z(30.0))
    es[1].put(sc, pos=(1.25, 0.25, 0.375, 3.0), rot=rot_x(20.0))
    sc.op(OP_CT_TIME, NEWEST)
    es[0].put(sc, pos=(0.0, 0.0, 0.0, 0.0), rot=IDENT)
    es[1].put(sc, pos=(1.25, 0.0, 0.0, 0.0), rot=IDENT)

    sc.tag("FindContactTime: the shorter backup, and the threshold")
    es[1].put(sc, pos=(1.2, 0.0, 0.0, 0.0), vel=(-2.0, 0.0, 0.0, 0.0))
    for mb0, mb1 in ((0.5, 2.0), (2.0, 0.375), (0.125, 0.125)):
        es[0].put(sc, maxbackup=mb0)
        es[1].put(sc, maxbackup=mb1)
        sc.op(OP_CT_TIME, NEWEST)
    es[0].put(sc, maxbackup=1.0)
    es[1].put(sc, maxbackup=1.0)
    sc.op(OP_GLOBAL, G_THRESH, 0.0)     # never close enough: all eight
    sc.op(OP_CT_TIME, NEWEST)
    sc.op(OP_GLOBAL, G_THRESH, 0.25)
    sc.op(OP_CT_TIME, NEWEST)
    sc.op(OP_GLOBAL, G_THRESH, 0.05)
    es[0].put(sc, vel=(0.5, 0.25, 0.0, 0.0))
    sc.op(OP_CT_TIME, NEWEST)
    es[0].put(sc, vel=(0.0, 0.0, 0.0, 0.0))

    sc.tag("Crowbar: along the line of centres")
    es[1].put(sc, pos=(1.25, 0.1, -0.05, 0.0), vel=(0.0, 0.0, 0.0, 0.0))
    for t in (0.0, 0.5, 1.0):
        sc.op(OP_CT_CROWBAR, NEWEST, float(t))
    es[1].put(sc, vel=(1.0, 0.5, 0.0, 0.0))
    sc.op(OP_CT_CROWBAR, NEWEST, 0.5)   # back at t they are apart: at once
    sc.op(OP_CT_CROWBAR, NEWEST, 0.0)
    es[1].put(sc, vel=(0.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_DEL, NEWEST, 1)

    sc.tag("FindContactTime and Crowbar against a track polygon")
    es[2].put(sc, pos=(0.5, 0.25, 0.13, 0.0), vel=(0.0, 0.0, 0.0, 0.0),
              maxbackup=1.0)
    sc.op(OP_CT_NEW, W_TE)              # up off T0 in three steps
    es[2].put(sc, pos=(0.5, 0.25, -0.2, 0.0))
    sc.op(OP_CT_TIME, NEWEST)           # below, but within the bias: up
    sc.op(OP_GLOBAL, G_BIAS, 0.125)
    sc.op(OP_CT_TIME, NEWEST)           # past it: down
    sc.op(OP_GLOBAL, G_BIAS, 0.5)
    es[2].put(sc, pos=(0.5, 0.25, 0.0625, 0.0), vel=(0.0, 0.0, -1.0, 0.0))
    sc.op(OP_CT_TIME, NEWEST)
    sc.op(OP_CT_CROWBAR, NEWEST, 0.25)
    sc.op(OP_CT_DEL, NEWEST, 1)
    es[3].put(sc, pos=(-0.5, 0.25, 0.1, 0.0), vel=(0.0, 0.0, 0.0, 0.0),
              maxbackup=1.0)
    sc.op(OP_CT_NEW, W_ET)              # the track body second
    es[3].put(sc, pos=(-0.5, 0.25, -0.15, 1.0))
    sc.op(OP_CT_TIME, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)
    es[1].put(sc, pos=(0.5, 0.0, 0.25, 0.0))
    sc.op(OP_CT_NEW, W_T1E)             # the leaning triangle, first
    es[1].put(sc, pos=(0.5, -1.0, -0.5, 0.0))
    sc.op(OP_CT_TIME, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)
    es[3].put(sc, pos=(0.25, 0.5, 0.25, 0.0))
    sc.op(OP_CT_NEW, W_ET1)             # and second
    es[3].put(sc, moveable=0)
    sc.op(OP_CT_TIME, NEWEST)           # nothing moves: twenty steps
    es[3].put(sc, moveable=1)
    sc.op(OP_CT_DEL, NEWEST, 1)
    sc.op(OP_CT_DUMP)


def contact_wafer_section(sc, es):
    sc.tag("FindWaferNormal: the face's normal, towards the body")
    for z in (1.0, 0.0, -0.25, -0.5, -0.75, -0.4999999):
        es[2].put(sc, pos=(0.5, 0.5, z, 7.0))
        sc.op(OP_CT_WAFER, T(0), E(2))
    sc.op(OP_GLOBAL, G_BIAS, -0.25)
    for z in (0.5, 0.25, 0.125):
        es[2].put(sc, pos=(0.5, 0.5, z, 0.0))
        sc.op(OP_CT_WAFER, T(0), E(2))
    sc.op(OP_GLOBAL, G_BIAS, 0.5)
    for p in ((0.0, 1.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, -0.625),
              (2.0, -3.0, -3.0), (0.0, 0.5, -0.25)):
        es[2].put(sc, pos=tuple(p) + (0.0,))
        sc.op(OP_CT_WAFER, T(1), E(2))


def contact_point_section(sc, es, rnd):
    sc.tag("FindContactPointAndNormal: between two dynamic bodies")
    es[0].put(sc, pos=(0.0, 0.0, 0.0, 0.0))
    es[1].put(sc, pos=(5.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_NEW, W_EE)
    cases = (
        ((0, 0, 0, 0), IDENT, (1, 0, 0, 0), (2, 0, 0, 0), IDENT,
         (-0.9, 0, 0, 0)),
        ((0.5, -1, 2, 1), rot_z(30.0), (1, 0.5, 0, 0), (2, 1, 1.5, 0),
         rot_x(45.0), (-0.5, 0.25, -0.75, 0)),
        ((1, 1, 1, 0), IDENT, (0.5, 0.5, 0.5, 0), (2, 2, 2, 0), IDENT,
         (-0.5, -0.5, -0.5, 0)),       # the closest points one: the centres
        ((1, 1, 1, 0), IDENT, (0.5, 0.5, 0.5, 0), (2, 2, 2, 0), IDENT,
         (-0.5, -0.5, -0.4999997, 0)),  # 3e-8 apart: still the centres
        ((1, 1, 1, 0), IDENT, (0.5, 0.5, 0.5, 0), (2, 2, 2, 0), IDENT,
         (-0.5, -0.5, -0.499995, 0)))   # 5e-6: the points
    for p1, r1, cp1, p2, r2, cp2 in cases:
        es[0].put(sc, pos=tuple(float(c) for c in p1), rot=r1)
        es[1].put(sc, pos=tuple(float(c) for c in p2), rot=r2)
        sc.op(OP_WIT_CP, W_EE, *[float(c) for c in cp1],
              *[float(c) for c in cp2])
        sc.op(OP_CT_POINT, NEWEST)
    for _ in range(6):
        es[0].put(sc, pos=vec4(rnd, -3, 3), rot=rot_z(rnd.uniform(0, 360)))
        es[1].put(sc, pos=vec4(rnd, -3, 3), rot=rot_x(rnd.uniform(0, 360)))
        sc.op(OP_WIT_CP, W_EE, *vec4(rnd), *vec4(rnd))
        sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_SETB, E(0), F_DYN, 0)      # E0 read as a track body: its box
    sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_SETB, E(0), F_DYN, 1)
    sc.op(OP_SETB, E(1), F_DYN, 0)
    sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_SETB, E(1), F_DYN, 1)
    sc.op(OP_CT_DEL, NEWEST, 1)

    sc.tag("FindContactPointAndNormal: a track body's wafer")
    es[2].put(sc, pos=(0.5, 0.25, 3.0, 0.0), vel=(0.0, 0.0, 0.0, 0.0))
    es[3].put(sc, pos=(-0.5, 0.25, 3.0, 0.0), vel=(0.0, 0.0, 0.0, 0.0))
    sc.op(OP_CT_NEW, W_TE)
    sc.op(OP_WIT_CP, W_TE, 0.5, 0.25, 0.0, 0.0, 0.0, 0.0, -0.25, 1.0)
    sc.op(OP_CT_POINT, NEWEST)
    es[2].put(sc, pos=(0.5, 0.25, -1.0, 0.0))
    sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)
    sc.op(OP_CT_NEW, W_ET)
    sc.op(OP_WIT_CP, W_ET, 0.0, 0.0, -0.25, 0.0, -0.5, 0.25, 0.0, 0.0)
    sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)
    sc.op(OP_CT_NEW, W_ET1)
    sc.op(OP_WIT_CP, W_ET1, 0.1, 0.2, -0.3, 0.0, 0.0, 0.0, 0.0, 0.0)
    sc.op(OP_CT_POINT, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)

    sc.tag("FindPlanarCollisionContactPoint")
    es[0].put(sc, pos=(0.0, 0.0, 0.0, 0.0), rot=IDENT)
    es[1].put(sc, pos=(5.0, 0.0, 0.0, 0.0), rot=IDENT)
    sc.op(OP_CT_NEW, W_EE)
    for p1, p2, pt in (((0, 0, 0, 0), (2, 0, 0, 0), (1, 0.5, 0.75, 0)),
                       ((0, 0, 0, 1), (1, 1, 1, 3), (0.5, 0.25, 2, 5)),
                       ((1, -2, 0.5, 0), (-1, 3, -0.5, 0), (0, 0, 0, 0))):
        es[0].put(sc, pos=tuple(float(c) for c in p1))
        es[1].put(sc, pos=tuple(float(c) for c in p2))
        sc.op(OP_CT_PLANAR, NEWEST, *[float(c) for c in pt])
    for _ in range(5):
        es[0].put(sc, pos=vec4(rnd, -3, 3))
        es[1].put(sc, pos=vec4(rnd, -3, 3))
        sc.op(OP_CT_PLANAR, NEWEST, *vec4(rnd, -3, 3))
    sc.op(OP_CT_DEL, NEWEST, 1)

    sc.tag("GetContactPointVelocity and DenominatorTerm")
    sc.op(OP_CT_CPV, 1.0, 2.0, 3.0, 4.0, 0.5, -0.25, 2.0, 8.0,
          -1.0, 3.0, 0.5, 16.0)
    # x + (y + z) is 0 here and (x + y) + z is 1
    sc.op(OP_CT_DENOM, *flat(IDENT), 1e8, 0.0, 0.0, 0.0, 1.0, -1.0, 1.0,
          0.0)
    for _ in range(8):
        sc.op(OP_CT_CPV, *vec4(rnd), *vec4(rnd), *vec4(rnd))
        sc.op(OP_CT_DENOM, *flat(tuple(vec4(rnd) for _ in range(4))),
              *vec4(rnd), *vec4(rnd))


def contact_collision_section(sc, es):
    sc.tag("GetCollision and BeginCollision")
    sc.op(OP_WIT_SETCOLL, W_EE, 0)
    sc.op(OP_STAT, 1, 10)               # NumCollisions
    sc.op(OP_STAT, 10, 5)               # HighestNumCollisions
    sc.op(OP_CT_GETCOLL, W_EE, 1.0, 2.0, 3.0, 4.0)     # begun
    sc.op(OP_CT_GETCOLL, W_EE, 5.0, 6.0, 7.0, 8.0)     # there already
    sc.op(OP_WIT_SETCOLL, W_EE, 3)
    sc.op(OP_CT_GETCOLL, W_EE, 5.0, 6.0, 7.0, 8.0)
    sc.op(OP_STAT, 1, 3)                # below the highest
    sc.op(OP_SETB, E(0), F_NC, 127)
    sc.op(OP_SETB, E(1), F_NC, 255)
    sc.op(OP_CT_BEGIN, W_EE, -1.0, 0.5, 0.25, 0.0)
    sc.dump()
    sc.op(OP_STAT, 1, 10)               # level with it
    sc.op(OP_CT_BEGIN, W_TE, 0.0, 0.0, 0.0, 0.0)
    sc.op(OP_SETB, E(0), F_NC, 0)
    sc.op(OP_SETB, E(1), F_NC, 0)
    sc.dump()


def impulse(sc, es, w, s1, s2, cp1, cp2, q1=(), q2=(), setcoll=0):
    """One CollisionImpulse on a new contact of witness w: the two bodies'
    states, the closest points and what ConsiderImpulse answers."""
    if s1 is not None:
        es[s1[0]].put(sc, **s1[1])
    if s2 is not None:
        es[s2[0]].put(sc, **s2[1])
    sc.op(OP_CT_NEW, w)
    sc.op(OP_WIT_CP, w, *[float(c) for c in cp1], *[float(c) for c in cp2])
    for k, q in ((s1, q1), (s2, q2)):
        if k is not None:
            sc.op(OP_E_QUEUE, k[0], len(q), *[float(v) for v in q])
    sc.op(OP_WIT_SETCOLL, w, setcoll)
    sc.op(OP_CT_IMPULSE, NEWEST)
    sc.op(OP_CT_DEL, NEWEST, 1)


def contact_impulse_section(sc, es, rnd):
    sc.tag("CollisionImpulse: two cars, one round")
    base0 = dict(pos=(0.0, 0.0, 0.0, 0.0), vel=(3.0, 0.5, 0.0, 0.0),
                 rot=IDENT, cv=(1.0, 0.25, 0.0, 0.0),
                 cw=(0.0, 0.0, 0.5, 0.0), inertia=inertia(rnd), minv=1.0,
                 bounce=0.1, friction=0.5, moveable=1)
    base1 = dict(pos=(2.0, 0.0, 0.0, 0.0), vel=(-3.0, 0.0, 0.0, 0.0),
                 rot=IDENT, cv=(-1.0, -0.5, 0.125, 0.0),
                 cw=(0.25, 0.0, -0.25, 0.0), inertia=inertia(rnd),
                 minv=0.5, bounce=0.2, friction=0.6, moveable=1)
    cp = ((1.0, 0.1, 0.0, 0.0), (-0.9, 0.1, 0.0, 0.0))
    impulse(sc, es, W_EE, (0, base0), (1, base1), *cp)
    sc.dump()
    # parting already: nothing but the collision
    impulse(sc, es, W_EE, (0, dict(cv=(-1.0, 0.0, 0.0, 0.0))),
            (1, dict(cv=(1.0, 0.0, 0.0, 0.0))), *cp)
    # the other way about: the second body bouncier, lighter, rougher
    impulse(sc, es, W_EE, (0, dict(base0, bounce=0.3, minv=0.25,
                                   friction=0.7)),
            (1, dict(base1)), *cp)

    sc.tag("CollisionImpulse: the floor under a slow impulse")
    still = (0.0, 0.0, 0.0, 0.0)
    # sliding past each other and not closing: vn is 0, and that is enough
    impulse(sc, es, W_EE, (0, dict(base0, cv=(0.5, 1.0, 0.0, 0.0), cw=still)),
            (1, dict(base1, cv=(0.5, -1.0, 0.25, 0.0), cw=still)), *cp)
    # closing at 0.2: the floor is 0.3 over the heavier side, its speed
    # factor held at 1
    impulse(sc, es, W_EE, (0, dict(base0, cv=(0.1, 0.0, 0.0, 0.0), cw=still)),
            (1, dict(base1, cv=(-0.1, 0.0, 0.0, 0.0), cw=still)), *cp)
    # and over a larger mass inverse of 0.5, not 1
    impulse(sc, es, W_EE, (0, dict(base0, cv=(0.1, 0.0, 0.0, 0.0), cw=still,
                                   minv=0.5)),
            (1, dict(base1, cv=(-0.1, 0.0, 0.0, 0.0), cw=still,
                     minv=0.25)), *cp)
    impulse(sc, es, W_EE, (0, dict(base0, cv=(0.004, 0.0, 0.0, 0.0),
                                   cw=(0.0, 0.0, 0.0, 0.0))),
            (1, dict(base1, cv=(-0.004, 0.001, 0.0, 0.0),
                     cw=(0.0, 0.0, 0.0, 0.0))), *cp)
    sc.op(OP_GLOBAL, G_MINSPEED, 0.0078125)
    sc.op(OP_GLOBAL, G_MINFACTOR, 0.125)
    impulse(sc, es, W_EE, (0, dict(base0)), (1, dict(base1)), *cp)
    impulse(sc, es, W_EE, (0, dict(base0, cv=(0.004, 0.0, 0.0, 0.0))),
            (1, dict(base1, cv=(-0.004, 0.001, 0.0, 0.0))), *cp)
    sc.op(OP_GLOBAL, G_MINSPEED, 0.1)
    sc.op(OP_GLOBAL, G_MINFACTOR, 0.3)

    sc.tag("CollisionImpulse: what ConsiderImpulse says")
    ee = ((0, dict(base0)), (1, dict(base1)))
    for q1, q2 in (((0.5,), (0.5,)),            # two rounds
                   ((1.0,), (-57575.0,)),       # the second vetoes
                   ((-57575.0,), (0.25,)),      # the first
                   ((-0.5,), (1.0,)),           # negative: the last round
                   ((0.75,), (-0.25,)),
                   ((-0.5,), (-0.25,)),         # both, and the second stays
                   ((0.75,), (0.4,)),
                   ((0.5, 0.5, 0.5), (0.9, 0.9, 0.9)),
                   ((-1.0,), (1.0,)),
                   ((1.25,), (2.0,)),           # more than all of it
                   ((0.0,), (0.5,))):
        impulse(sc, es, W_EE, *ee, *cp, q1=q1, q2=q2)

    sc.tag("CollisionImpulse: friction, and a car scraping")
    impulse(sc, es, W_EE, (0, dict(base0, friction=0.3)),
            (1, dict(base1, friction=0.1)), *cp)       # the rougher
    # something that cannot move against a car: 0.1, and past 30 pulled
    for v in ((40.0, 5.0, 2.0, 0.0), (20.0, 0.0, 0.0, 0.0),
              (29.0, 8.0, 1.0, 0.0), (-50.0, 0.0, -10.0, 1.0)):
        impulse(sc, es, W_EE, (0, dict(base0, minv=0.0)),
                (1, dict(base1, friction=0.3, vel=v)), *cp)
        impulse(sc, es, W_EE, (0, dict(base0, friction=0.3, vel=v)),
                (1, dict(base1, minv=0.0)), *cp)
    impulse(sc, es, W_EE, (0, dict(base0, minv=0.0, friction=0.3)),
            (1, dict(base1, friction=0.3, vel=(40.0, 0.0, 0.0, 0.0))),
            *cp)                                       # both cars
    impulse(sc, es, W_EE, (0, dict(base0, minv=0.0, friction=0.3,
                                   vel=(40.0, 0.0, 0.0, 0.0))),
            (1, dict(base1, friction=0.2)), *cp)       # not a car
    impulse(sc, es, W_EE, (0, dict(base0, friction=0.5)),
            (1, dict(base1, minv=0.0, friction=0.3,
                     vel=(40.0, 0.0, 0.0, 0.0))), *cp)  # the other way
    impulse(sc, es, W_EE, (0, dict(base0, friction=0.3,
                                   vel=(40.0, 0.0, 0.0, 0.0))),
            (1, dict(base1, minv=0.0, friction=0.3)), *cp,
            q1=(0.5,), q2=(0.5,))                      # two rounds pulled
    # a slide slower than MaxFrictionScrapeSpeed fades the friction
    impulse(sc, es, W_EE, (0, dict(base0, cv=(1.0, 0.0, 0.0, 0.0),
                                   cw=(0.0, 0.0, 0.0, 0.0))),
            (1, dict(base1, cv=(-1.0, 0.25, 0.0, 0.0),
                     cw=(0.0, 0.0, 0.0, 0.0))), *cp)
    sc.op(OP_GLOBAL, G_SCRAPE, 4.0)
    impulse(sc, es, W_EE, (0, dict(base0)), (1, dict(base1)), *cp)
    sc.op(OP_GLOBAL, G_SCRAPE, 1.0)

    sc.tag("CollisionImpulse: a car on a track polygon")
    sc.op(OP_GLOBAL, G_LOOP, 12)
    drop = dict(pos=(0.5, 0.25, 0.25, 0.0), vel=(0.0, 0.0, -2.0, 0.0),
                rot=IDENT, cv=(0.0, 0.0, -2.0, 0.0),
                cw=(0.0, 0.0, 0.0, 0.0), inertia=inertia(rnd), minv=0.5,
                bounce=0.1, friction=0.3, moveable=1)
    tcp = ((0.5, 0.25, 0.0, 0.0), (0.0, 0.0, -0.25, 0.0))
    # straight down on the flat: no slide, and -0 / 0
    impulse(sc, es, W_TE, None, (2, drop), *tcp)
    impulse(sc, es, W_TE, None, (2, dict(drop, vel=(35.0, 1.0, -2.0, 0.0),
                                         cv=(3.0, 1.0, -2.0, 0.0),
                                         cw=(0.5, -0.25, 0.125, 0.0))),
            *tcp)
    impulse(sc, es, W_TE, None, (2, dict(drop, friction=0.5,
                                         cv=(3.0, 1.0, -2.0, 0.0))), *tcp)
    impulse(sc, es, W_ET, (3, dict(drop, pos=(-0.5, 0.25, 0.25, 0.0),
                                   vel=(-31.0, 2.0, 0.0, 0.0),
                                   cv=(-2.0, 0.5, -1.0, 0.0),
                                   cw=(0.0, 0.25, 0.0, 0.0))), None,
            (0.0, 0.0, -0.25, 0.0), (-0.5, 0.25, 0.0, 0.0))
    impulse(sc, es, W_ET1, (3, dict(drop, pos=(0.25, 0.5, 0.5, 0.0),
                                    vel=(0.0, 5.0, 0.0, 0.0),
                                    cv=(0.0, 1.0, -1.0, 0.0))), None,
            (0.0, 0.0, -0.25, 0.0), (0.25, 0.5, 0.375, 0.0),
            setcoll=2)                                 # a collision on it
    for _ in range(6):
        s0 = dict(base0, pos=vec4(rnd, -1, 1), cv=vec4(rnd), cw=vec4(rnd),
                  vel=vec4(rnd, -40, 40), inertia=inertia(rnd),
                  minv=rnd.choice((0.0, 0.25, 1.0)),
                  bounce=rnd.uniform(0, 0.5),
                  friction=rnd.choice((0.3, 0.5)))
        s1 = dict(base1, pos=vec4(rnd, 1, 3), cv=vec4(rnd), cw=vec4(rnd),
                  vel=vec4(rnd, -40, 40), inertia=inertia(rnd),
                  minv=0.5 if s0["minv"] == 0.0 else rnd.choice((0.0, 0.5)),
                  bounce=rnd.uniform(0, 0.5),
                  friction=rnd.choice((0.3, 0.6)))
        impulse(sc, es, W_EE, (0, s0), (1, s1), vec4(rnd, -1, 1),
                vec4(rnd, -1, 1), q1=(rnd.uniform(0.2, 1.0),),
                q2=(rnd.uniform(0.2, 1.0),))
    sc.dump()


def contact_resolve_section(sc, es):
    sc.tag("Resolve: back, apart, the impulse, and on again")
    es[0].put(sc, pos=(0.0, 0.0, 0.0, 0.0), vel=(0.0, 0.0, 0.0, 0.0),
              cv=(1.0, 0.0, 0.0, 0.0), cw=(0.0, 0.0, 0.0, 0.0), minv=1.0)
    es[1].put(sc, pos=(1.25, 0.0, 0.0, 0.0), vel=(0.0, 0.0, 0.0, 0.0),
              cv=(-1.0, 0.0, 0.0, 0.0), cw=(0.0, 0.0, 0.0, 0.0), minv=1.0)
    sc.op(OP_WIT_SETCOLL, W_EE, 0)
    sc.op(OP_CT_TEST, W_EE)             # crowbarred apart
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_RESOLVE, LP(0))
    for m0, m1 in ((0, 1), (1, 0), (0, 0)):
        es[0].put(sc, moveable=m0)
        es[1].put(sc, moveable=m1)
        sc.op(OP_CT_POKE, LP(0), XF_CV + 3, 0.5)
        sc.op(OP_CT_POKE, LP(0), XF_BT, 0.25)
        sc.op(OP_CT_RESOLVE, LP(0))
    es[0].put(sc, moveable=1)
    es[1].put(sc, moveable=1)
    es[2].put(sc, pos=(0.5, 0.25, 0.13, 0.0), vel=(0.0, 0.0, -1.0, 0.0),
              cv=(0.5, 0.0, -1.0, 0.0), friction=0.3)
    sc.op(OP_WIT_SETCOLL, W_TE, 0)
    sc.op(OP_CT_TEST, W_TE)
    sc.op(OP_CT_DUMP)
    sc.op(OP_CT_RESOLVE, LP(1))
    sc.dump()
    sc.op(OP_CT_REMOVE, E(0))
    sc.op(OP_CT_REMOVE, E(2))
    sc.op(OP_CT_DUMP)


def contact_teardown_section(sc):
    sc.tag("contacts: CloseContact and the rest")
    sc.op(OP_CT_CLOSE)
    sc.op(OP_CT_DUMP)
    sc.op(OP_STATIC_CLOSE)
    sc.op(OP_CLOSE)
    sc.op(OP_TREE_CLOSE)
    sc.dump()


def contact_section(sc, chunk, rnd):
    es = contact_setup_section(sc, chunk)
    contact_test_section(sc, es)
    contact_list_section(sc, es)
    contact_time_section(sc, es)
    contact_wafer_section(sc, es)
    contact_point_section(sc, es, rnd)
    contact_collision_section(sc, es)
    contact_impulse_section(sc, es, rnd)
    contact_resolve_section(sc, es)
    contact_teardown_section(sc)


def script():
    rnd = random.Random(0xc011)
    sc = Script()
    chunk = poly_chunk()
    picks = pick_polys(chunk)
    sc.picks = picks
    boot_section(sc)
    na_section(sc)
    init_section(sc)
    bodies_section(sc)
    box_section(sc, rnd)
    flags_section(sc)
    vcall_section(sc, (0, 10, 1))
    tree_section(sc, chunk, picks)
    witness_section(sc)
    teardown_section(sc, picks)
    dyn_setup_section(sc)
    dyn_physics_section(sc, rnd)
    dyn_volumes_section(sc)
    dyn_move_section(sc)
    dyn_local_section(sc)
    dyn_witness_section(sc)
    dyn_tp_section(sc, rnd)
    dyn_tpcheck_section(sc)
    car_setup_section(sc)
    car_methods_section(sc, rnd)
    car_move_section(sc)
    car_impulse_section(sc, rnd)
    car_damage_section(sc)
    car_anim_section(sc, rnd)
    car_teardown_section(sc)
    dyn_teardown_section(sc)
    contact_section(sc, chunk, rnd)
    return sc


# ----------------------------------------------------------------- the model


class Model(object):
    def __init__(self, sc):
        self.sc = sc
        self.out = []
        e = self.e = me.Emu(ieee=True, eediv=True, eesqrt=True)
        e.stub_bware()
        self.fn = {k: e.addr_of(v) for k, v in SYM.items()}
        self.h = [e.alloc(96, 16) for _ in range(NH)]
        self.polys = [e.alloc(48, 16) for _ in range(NPOLY)]
        self.pverts = [e.alloc(40, 16) for _ in range(NPOLY)]
        for p, v in zip(self.polys, self.pverts):
            e.put32(p + 32, v)
        self.colls = [e.alloc(16, 16) for _ in range(NCOLL)]
        self.na = e.alloc(16, 16)
        self.pools = {}                 # name -> (block, size)
        for name, _var, n, slot in POOLS:
            size = HEADER + n * slot + 64
            self.pools[name] = (e.alloc(size, 16), size)
        self.blocks = []
        self.chunk = e.alloc(8 * 1024 * 1024, 16) + 8
        self.scr = e.alloc(0x400, 16)
        self.outv = self.scr            # four vectors
        self.outm = self.scr + 64
        self.inv = self.scr + 128       # two vectors
        self.vmin, self.vmax = self.scr + 160, self.scr + 176
        self.name = self.scr + 192
        for k, v in enumerate(((1.0, 2.0, 3.0, 4.0),
                               (-5.0, 6.0, -7.0, 8.0))):
            for j in range(4):
                e.put32(self.inv + 16 * k + 4 * j, bits(v[j]))
        self.stubs()
        self.dyn_init()
        self.car_init()
        self.ct_init()
        for pat in (r"bNewSlotPool__FiiPCci$", r"TrackPositionMarkerList$",
                    r"RectEdgesNearFaces$"):
            done = e.run_ctors(pat)
            assert len(done) == 1, (pat, done)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, p):
        end = self.e.mem.index(b"\0", p)
        return self.e.mem[p:end].decode("latin-1")

    def stubs(self):
        e = self.e

        def arg(i):
            return e.reg[4 + i] & M32

        def malloc(em):
            size, name = s32(arg(0)), self.cstr(arg(1))
            flags, pool = s32(arg(2)), s32(arg(3))
            if name in self.pools:
                p, n = self.pools[name]
                assert size <= n, (name, size)
                e.mem[p:p + n] = bytes(n)
                self.emit("  pool alloc %s mp %d" % (name, pool))
                return p
            p = e.alloc(size + 32, 16)
            e.mem[p:p + size] = b"\xa5" * size
            if name in SHORT:
                self.emit("  malloc #%d %s %d fl %d mp %d"
                          % (len(self.blocks), name, size, flags, pool))
            else:
                self.emit("  malloc #%d %s fl %d mp %d"
                          % (len(self.blocks), name, flags, pool))
            self.blocks.append(p)
            return p

        def free(em):
            p = arg(0)
            for name, (b, _n) in self.pools.items():
                if p == b:
                    self.emit("  pool free %s" % name)
                    return 0
            self.emit("  free %s" % self.label(p))
            return 0

        def printf(em):
            self.emit("  printf")
            return 0

        def brk(em):
            raise AssertionError("the script reaches bBreak")

        # CarCollisionBody's box, the one two-argument bMalloc: (2800, 16),
        # the size and the pool. The port names it for the hook.
        def malloc2(em):
            size, pool = s32(arg(0)), s32(arg(1))
            assert size == 2800, size
            p = e.alloc(size + 32, 16)
            e.mem[p:p + size] = b"\xa5" * size
            self.emit("  malloc #%d RectPolyhedron fl 0 mp %d"
                      % (len(self.blocks), pool))
            self.blocks.append(p)
            return p

        def coll_dtor(em):
            self.emit("  ~collision %s %d" % (self.label(arg(0)),
                                              s32(arg(1))))
            return 0

        e.stub("bMalloc__FiPCcii", malloc)
        e.stub("bMalloc__Fii", malloc2)
        e.stub("bFree__FPv", free)
        e.stub("bPrintf__FPCce", printf)
        e.stub("bBreak__Fv", brk)
        e.stub(SYM["coll_dtor"], coll_dtor)

    def dyn_init(self):
        """D0..D3 and what they stand on: S0..S3, dpoly0 and dpoly1, RB0 and
        RB1, TC0, PS0 and its table, and testA and testB."""
        e = self.e
        self.d = [e.alloc(D_BYTES + 16, 16) for _ in range(ND)]
        self.side = [e.alloc(SIDE_WORDS * 4, 16) for _ in range(ND)]
        self.dpolys = [e.alloc(48, 16) for _ in range(NDPOLY)]
        self.dverts = [e.alloc(20 * NDVERT, 16) for _ in range(NDPOLY)]
        for p, v in zip(self.dpolys, self.dverts):
            e.put32(p + 32, v)
        self.rb = [e.alloc(400, 16) for _ in range(NRB)]
        self.tc = e.alloc(560, 16)
        self.ps = e.alloc(16, 16)
        self.smoke = {}
        self.tps = []                   # TP_ASSIGN's TrackPolygons, in order
        self.lp = self.scr + 256        # GetLocalCollisionBodies' two outputs

        def arg(i):
            return e.reg[4 + i] & M32

        def which(this):
            return self.d.index(this - 8)

        def getter(name, off):
            def fn(em):
                k = which(arg(0))
                self.emit("  %s D%d" % (name, k))
                return self.side[k] + off
            return fn

        def enabled(em):
            b = arg(0) - 8
            self.emit("  enabled %s" % self.label(b))
            return 1 if e.mem[b + 17] == 0 else 0

        def interp(em):
            k, t = which(arg(0)), e.fpr[12] & M32
            self.emit("  interp D%d t %08x" % (k, t))
            nt = t ^ 0x80000000
            f = [bits(float(v)) for v in range(13)]
            vals = [t, nt, f[3], f[4],
                    t, f[1], f[2], f[3], f[4], t, f[5], f[6],
                    f[7], f[8], t, f[9], f[10], f[11], f[12], nt]
            e.write(arg(1), struct.pack("<4I", *vals[:4]))
            e.write(arg(2), struct.pack("<16I", *vals[4:]))
            return 0

        def aux(em):
            self.emit("  aux %s" % self.label(arg(0) - 4))
            return 0

        def smokeable(em):
            b = arg(0)
            to = self.smoke.get(b, b)
            self.emit("  smokeable %s -> %s" % (self.label(b), self.label(to)))
            return to

        def stub_at(fn):
            a = e.alloc(8, 8)
            e.stub(a, fn)
            return a

        e.stub(SYM["smokeable"], smokeable)
        slots = ((VT_GETPOS, getter("getpos", 0)),
                 (VT_GETVEL, getter("getvel", 16)),
                 (VT_GETROT, getter("getrot", 32)),
                 (VT_ENABLED, enabled))
        stubs = [(s, stub_at(fn)) for s, fn in slots]
        s_interp = stub_at(interp)
        self.vt_test = []
        for extra in ((), ((VT_INTERP, s_interp),)):
            vt = e.alloc(8 * VT_ENTRIES, 16)
            e.write(vt, e.read(VT_DYN, 8 * VT_ENTRIES))
            for s, a in stubs + list(extra):
                e.write(vt + s, struct.pack("<hhI", 8, 0, a))
            self.vt_test.append(vt)
        self.vtnames = {self.vt_test[0]: "testA", self.vt_test[1]: "testB"}
        self.dyn_tables = (VT_DYN, self.vt_test[0], self.vt_test[1], VT_CAR)
        self.ps_vt = e.alloc(24, 16)
        e.write(self.ps_vt + 16, struct.pack("<hhI", 4, 0, stub_at(aux)))
        e.put32(self.ps + 12, self.ps_vt)

    def car_init(self):
        """CAR0..CAR2, their CarTypeInfos, PL0, M0, AD0, DMG0, RC0, COP0,
        PP0 and PP1; and the stubs for Car's four calls and the five
        seams."""
        e = self.e
        self.cars = [e.alloc(CAR_BYTES, 16) for _ in range(NCAR)]
        self.ctis = [e.alloc(CTI_BYTES, 16) for _ in range(NCAR)]
        for c, t in zip(self.cars, self.ctis):
            e.put32(c + CAR_CTI, t)
        self.pl0, self.m0, self.m1, self.ad0, self.dmg0, self.cop0 = (
            e.alloc(64, 16) for _ in range(6))
        self.rc0 = e.alloc(144, 16)
        e.put32(self.m0 + 24, self.rb[1])
        e.put32(self.m1 + 24, self.rb[0])
        self.pps = [e.alloc(96, 16) for _ in range(NPP)]
        self.ppverts = [e.alloc(20 * NPPVERT, 16) for _ in range(NPP)]
        for p, v in zip(self.pps, self.ppverts):
            e.put32(p + 32, v)
        self.pp_linked = [False] * NPP
        self.blink = [0] * NCAR
        self.poof = [0] * NCAR
        self.seams_off = 0              # G_SEAMS: 1 the rumble, 2 the force
        self.move_q = []
        self.cv = self.scr + 320        # CAR_APPLY's two vectors
        self.tbuf = self.scr + 352      # CAR_TIMES's Timer

        def arg(i):
            return e.reg[4 + i] & M32

        def f12():
            return e.fpr[12] & M32

        def car(a):
            return self.cars.index(a)

        def move(em):
            k, t = car(arg(0)), f12()
            r = self.move_q.pop(0) if self.move_q else t
            self.emit("  car-move CAR%d t %08x -> %08x" % (k, t, r))
            e.fpr[0] = r

        def blinking(em):
            k = car(arg(0))
            self.emit("  car-blinking CAR%d -> %d" % (k, self.blink[k]))
            return self.blink[k]

        def poofed(em):
            k = car(arg(0))
            self.emit("  car-poofed CAR%d -> %d" % (k, self.poof[k]))
            return self.poof[k]

        def stpm(em):
            self.emit("  car-stpm %s them %s" % (self.label(arg(0)),
                                                 self.label(arg(1))))

        def add_damage(em):
            self.emit("  add-damage %s at %s amount %08x"
                      % (self.label(arg(0)), self.words(arg(1), 4), f12()))

        def rumble(em):
            if not self.seams_off & 1:
                self.emit("  rumble port %d amount %08x"
                          % (s32(arg(0)), f12()))

        def monitor(em):
            self.emit("  monitor-impact %s %s amount %08x"
                      % (self.label(arg(0)), self.label(arg(1)), f12()))

        def begin(em):
            self.emit("  begin-collision %s type %d prio %d"
                      % (self.label(arg(0)), s32(arg(1)), s32(arg(2))))

        def force(em):
            if not self.seams_off & 2:
                self.emit("  force-impact %s dir %s amount %08x"
                          % (self.label(arg(0)), self.words(arg(1), 4),
                             f12()))

        for sym, fn in (("Move__3Carf", move), ("IsBlinking__3Car", blinking),
                        ("IsPoofed__3Car", poofed),
                        ("SetToPhysicsMode__3CarP3Car", stpm),
                        ("AddDamage__9CarDamagePC8bVector3f", add_damage),
                        ("PortRumbleImpact__Fif", rumble),
                        ("MonitorImpact__11tCopManagerP3Carf", monitor),
                        ("BeginCollision__14AnimatedDriver"
                         "19DriverAnimationTypei", begin),
                        ("StartForceImpact__3CarG8bVector3f", force)):
            e.stub(sym, fn)

    def ct_init(self):
        """E0..E3 and what testC's stubs answer for them, testC, B0..B3 and
        clist; and the stubs for Collision's two calls."""
        e = self.e
        self.ebody = [e.alloc(E_BYTES, 16) for _ in range(NE)]
        self.es = [e.alloc(4 * E_VEC_WORDS, 16) for _ in range(NE)]
        for p in self.ebody + self.es:
            e.write(p, bytes(E_BYTES if p in self.ebody else 4 * E_VEC_WORDS))
        self.escal = [dict(maxbackup=0, minv=0, bounce=0, friction=0,
                           moveable=0, blinking=0) for _ in range(NE)]
        self.eq = [[] for _ in range(NE)]
        self.eqat = [0] * NE
        self.boxes = [e.alloc(2800, 16) for _ in range(NBOX)]
        self.clist = e.alloc(16, 16)
        e.put32(self.clist, self.clist)
        e.put32(self.clist + 4, self.clist)
        self.ncoll_made = 0
        self.newest = 0                 # the contact CT_NEW made last
        self.ctv = self.scr + 384       # CT_CPV's and CT_DENOM's inputs
        self.ctm = self.scr + 448

        def arg(i):
            return e.reg[4 + i] & M32

        def f12():
            return e.fpr[12] & M32

        def which(this):
            return self.ebody.index(this - 8)

        def getter(name, off):
            def fn(em):
                k = which(arg(0))
                self.emit("  e-%s E%d" % (name, k))
                return self.es[k] + off
            return fn

        def setpos(em):
            k = which(arg(0))
            self.emit("  e-setpos E%d %s" % (k, self.words(arg(1), 4)))
            e.write(self.es[k] + E_POS, e.read(arg(1), 16))
            return 0

        def fscal(name, field):
            def fn(em):
                k = which(arg(0))
                r = self.escal[k][field]
                self.emit("  e-%s E%d -> %08x" % (name, k, r))
                e.fpr[0] = r
            return fn

        def iscal(name):
            def fn(em):
                k = which(arg(0))
                r = self.escal[k][name]
                self.emit("  e-%s E%d -> %d" % (name, k, r))
                return r
            return fn

        def timed(name):
            def fn(em):
                self.emit("  e-%s E%d %08x" % (name, which(arg(0)), f12()))
                return 0
            return fn

        # Where the body was t ago: the position less t of the velocity,
        # lane by lane, and the rotation as it is.
        def interp(em):
            k, t = which(arg(0)), f12()
            self.emit("  e-interp E%d t %08x" % (k, t))
            s, tf = self.es[k], fbits(t)
            out = []
            for j in range(4):
                p = fbits(e.u32(s + E_POS + 4 * j))
                v = fbits(e.u32(s + E_VEL + 4 * j))
                out.append(bits(p - me.f32(tf * v)))
            e.write(arg(1), struct.pack("<4I", *out))
            e.write(arg(2), e.read(s + E_ROT, 64))
            return 0

        def aux(em):
            self.emit("  e-aux E%d" % which(arg(0)))
            return 0

        def curvel(em):
            k = which(arg(0))
            self.emit("  e-curvel E%d" % k)
            e.write(arg(1), e.read(self.es[k] + E_CV, 16))
            e.write(arg(2), e.read(self.es[k] + E_CW, 16))
            return 0

        def physmode(em):
            self.emit("  e-physmode E%d them %s" % (which(arg(0)),
                                                    self.label(arg(1))))
            return 0

        def consider(em):
            k = which(arg(0))
            if self.eqat[k] < len(self.eq[k]):
                r = self.eq[k][self.eqat[k]]
                self.eqat[k] += 1
            else:
                r = bits(1.0)
            self.emit("  e-consider E%d j %s at %s -> %08x"
                      % (k, self.words(arg(1), 4), self.words(arg(2), 4), r))
            e.fpr[0] = r

        # The velocity takes the mass inverse of the impulse, lane by lane.
        def apply(em):
            k = which(arg(0))
            self.emit("  e-apply E%d j %s at %s"
                      % (k, self.words(arg(1), 4), self.words(arg(2), 4)))
            s, m = self.es[k], fbits(self.escal[k]["minv"])
            for j in range(4):
                c = fbits(e.u32(s + E_CV + 4 * j))
                x = me.f32(m * fbits(e.u32(arg(1) + 4 * j)))
                e.put32(s + E_CV + 4 * j, bits(c + x))
            return 0

        def coll_new(em):
            assert arg(0) == 0, "%08x" % arg(0)   # CollisionSlotPool's bOMalloc
            c = self.colls[self.ncoll_made % NCOLL]
            self.ncoll_made += 1
            self.emit("  collision-new %s at %s -> %s"
                      % (self.label(arg(1)), self.words(arg(2), 4),
                         self.label(c)))
            return c

        def coll_impulse(em):
            self.emit("  collision-impulse %s at %s j %s scrape %08x"
                      % (self.label(arg(0)), self.words(arg(1), 4),
                         self.words(arg(2), 4), f12()))
            return 0

        def stub_at(fn):
            a = e.alloc(8, 8)
            e.stub(a, fn)
            return a

        slots = ((VT_GETPOS, getter("getpos", E_POS)),
                 (VT_GETVEL, getter("getvel", E_VEL)),
                 (VT_GETROT, getter("getrot", E_ROT)),
                 (VT_SETPOS, setpos),
                 (VT_MAXBACKUP, fscal("maxbackup", "maxbackup")),
                 (VT_MOVE, timed("move")),
                 (VT_BACKUP, timed("backup")),
                 (VT_INTERP, interp),
                 (VT_RECOMPUTE, aux),
                 (VT_CURVEL, curvel),
                 (VT_PHYSMODE, physmode),
                 (VT_CONSIDER, consider),
                 (VT_APPLY, apply),
                 (VT_MASSINV, fscal("massinv", "minv")),
                 (VT_INERTIA, getter("inertia", E_INERTIA)),
                 (VT_MOVEABLE, iscal("moveable")),
                 (VT_BLINKING, iscal("blinking")),
                 (VT_BOUNCE, fscal("bounce", "bounce")),
                 (VT_FRICTION, fscal("friction", "friction")))
        vt = self.vt_testc = e.alloc(8 * VT_ENTRIES, 16)
        e.write(vt, e.read(VT_DYN, 8 * VT_ENTRIES))
        for s, fn in slots:
            e.write(vt + s, struct.pack("<hhI", 8, 0, stub_at(fn)))
        self.vtnames[vt] = "testC"
        self.dyn_tables = (VT_DYN, self.vt_test[0], self.vt_test[1], vt,
                           VT_CAR)
        e.stub(SYM["coll_ctor"], coll_new)
        e.stub(SYM["coll_impulse"], coll_impulse)

        # Two quadwords the image loads with a lane it never wrote, which the
        # port writes zero: FindContactTime's zero vector and
        # FindPlanarCollisionContactPoint's up.
        def zero_at(off):
            def fn(em):
                e.put32((e.reg[29] + off) & M32, 0)
            return fn

        e.hook(CT_ZERO_W[0], zero_at(CT_ZERO_W[1]))
        e.hook(CT_UP_W[0], zero_at(CT_UP_W[1]))

    def vtname(self, vt):
        return self.vtnames.get(vt, "%08x" % vt)

    # ---- labels -----------------------------------------------------------

    def in_pool(self, var, a):
        e = self.e
        p = e.u32(var)
        if p == 0:
            return None
        n, size = s32(e.u32(p + 36)), s32(e.u32(p + 40))
        d = a - (p + HEADER)
        if d < 0 or d >= n * size:
            return None
        return d // size, d % size

    def label(self, a):
        a &= M32
        if a == 0:
            return "null"
        named = {BLIST: "blist", WLIST: "wlist", ZV: "ZeroVector",
                 IM: "IdentityMatrix", ZM: "ZeroMatrix", self.na: "na"}
        if a in named:
            return named[a]
        if a in self.h:
            return "H%d" % self.h.index(a)
        if a in self.polys:
            return "poly%d" % self.polys.index(a)
        if a in self.colls:
            return "C%d" % (self.colls.index(a) + 1)
        if a in self.d:
            return "D%d" % self.d.index(a)
        for k, s in enumerate(self.side):
            for off, f in ((0, "pos"), (16, "vel"), (32, "rot")):
                if a == s + off:
                    return "S%d.%s" % (k, f)
        if a in self.dpolys:
            return "dpoly%d" % self.dpolys.index(a)
        for k, rb in enumerate(self.rb):
            if a == rb:
                return "RB%d" % k
            if a == rb + 288:
                return "RB%d.inv" % k
        for k, rb in enumerate(self.rb):
            for off, f in ((16, "x"), (32, "r"), (144, "v")):
                if a == rb + off:
                    return "RB%d.%s" % (k, f)
        if a == self.tc:
            return "TC0"
        if a == self.ps:
            return "PS0"
        for k, c in enumerate(self.cars):
            for off, f in ((0, ""), (CAR_TC, ".tc"), (CAR_POS, ".pos"),
                           (CAR_VEL, ".vel"), (CAR_ROT, ".rot")):
                if a == c + off:
                    return "CAR%d%s" % (k, f)
        named = {self.pl0: "PL0", self.m0: "M0", self.m0 + 8: "M0.sys",
                 self.m1: "M1", self.m1 + 8: "M1.sys", self.ad0: "AD0",
                 self.dmg0: "DMG0", self.rc0: "RC0", self.cop0: "COP0"}
        if a in named:
            return named[a]
        if a in self.pps:
            return "PP%d" % self.pps.index(a)
        if a == self.clist:
            return "clist"
        if a in self.ebody:
            return "E%d" % self.ebody.index(a)
        if a in self.boxes:
            return "B%d" % self.boxes.index(a)
        r = self.in_pool(POOL_CONTACT, a)
        if r is not None:
            return "X%d%s" % (r[0], "+?" if r[1] else "")
        r = self.in_pool(POOL_CAR, a)
        if r is not None and r[1] == 272:
            return "K%d.sit" % r[0]
        r = self.in_pool(POOL_TPCB, a)
        if r is not None:
            i, off = r
            return ("T%d" % i if off == 0 else "T%d.poly" % i if off == 88
                    else "T%d+?" % i)
        for var, c in ((POOL_WIT, "W"), (POOL_CAR, "K"), (POOL_TP, "P")):
            r = self.in_pool(var, a)
            if r is not None:
                return "%s%d%s" % (c, r[0], "+?" if r[1] else "")
        if a in self.blocks:
            return "#%d" % self.blocks.index(a)
        return "?"

    def body(self, r):
        if r < NH:
            return self.h[r]
        if REF_D <= r < REF_D + ND:
            return self.d[r - REF_D]
        if REF_E <= r < REF_E + NE:
            return self.ebody[r - REF_E]
        if REF_K <= r < REF_K + 14:
            p = self.e.u32(POOL_CAR)
            assert p, r
            return p + HEADER + CAR_SLOT * (r - REF_K)
        p = self.e.u32(POOL_TPCB)
        assert REF_T <= r < REF_T + 160 and p, r
        return p + HEADER + 1080 * (r - REF_T)

    def witness(self, s):
        return self.e.u32(POOL_WIT) + HEADER + 112 * s

    # ---- dumps ------------------------------------------------------------

    def words(self, a, n):
        return " ".join("%08x" % self.e.u32(a + 4 * k) for k in range(n))

    def bytes_line(self, pre, a, n):
        self.emit(pre + "".join(" %02x" % b for b in self.e.read(a, n)))

    def pool_dump(self, name, var):
        e = self.e
        p = e.u32(var)
        if p == 0:
            self.emit("  pool %s null" % name)
            return
        self.emit("  pool %s flags %d alloc %d most %d slots %d total %d "
                  "free %s" % (name, e.u32(p + 20), s32(e.u32(p + 24)),
                               s32(e.u32(p + 28)), s32(e.u32(p + 36)),
                               s32(e.u32(p + 44)), self.label(e.u32(p + 16))))

    def feature(self, f, p):
        e = self.e
        if f == 0:
            return "null"
        if p and p + 36 <= len(e.mem):
            v = e.u32(p + 32)
            if v and f == v:
                return "v0"
        return "?"

    def body_dump(self, b):
        e, L = self.e, self.label
        self.emit("  body %s vt %s type %d dyn %d id %d nw %d dis %d nc %d "
                  "act %d bb %s poly %s caff %s"
                  % (L(b), self.vtname(e.u32(b + 80)), s8(e.u8(b + 12)),
                     s8(e.u8(b + 13)),
                     s16(e.u16(b + 14)), s8(e.u8(b + 16)), s8(e.u8(b + 17)),
                     s8(e.u8(b + 18)), s8(e.u8(b + 19)), self.words(b + 20, 4),
                     L(e.u32(b + 8)), L(e.u32(b + 76))))
        name = e.read(b + 36, 40)
        self.emit("    name" + "".join((" " if i % 8 == 0 else "")
                                       + "%02x" % name[i] for i in range(40)))
        if e.u32(b + 80) in self.dyn_tables:
            self.dyn_dump(b)
            return
        if e.u32(b + 80) != VT_TP:
            return
        w = b + 88
        num = [s16(e.u16(w + 16 + 2 * k)) for k in range(4)]
        mx = [s16(e.u16(w + 24 + 2 * k)) for k in range(4)]
        arr = [e.u32(w + 32 + 4 * k) for k in range(4)]
        self.emit("    tp %s wafer num %d %d %d %d max %d %d %d %d dyn %d "
                  "caff %s arr %s %s %s %s"
                  % tuple([L(e.u32(b + 84))] + num + mx
                          + [s32(e.u32(w + 8)), L(e.u32(w + 12)),
                             "va" if arr[0] == w + 48 else "?",
                             "ea" if arr[1] == w + 128 else "?",
                             "fa" if arr[2] == w + 176 else "?",
                             "pa" if arr[3] == w + 224 else "?"]))
        nv = num[0] if 0 <= num[0] <= 4 else 0
        nf = num[2] if 0 <= num[2] <= 2 else 0
        for k in range(nv):
            self.emit("    v%d %s" % (k, self.words(w + 48 + 20 * k + 4, 3)))
        for k in range(nf):
            self.emit("    f%d %s" % (k, self.words(w + 176 + 24 * k + 4, 4)))

    def dyn_dump(self, b):
        e, L = self.e, self.label
        self.emit("    dyn pm %d tc %s sys %s rb %s bt %08x"
                  % (s32(e.u32(b + 84)), L(e.u32(b + 88)), L(e.u32(b + 92)),
                     L(e.u32(b + 96)), e.u32(b + 100)))
        self.emit("    brot %s" % self.words(b + 112, 16))
        self.emit("    bpos %s bvel %s" % (self.words(b + 176, 4),
                                          self.words(b + 192, 4)))
        self.emit("    cyl %s r %08x lbb %s %s"
                  % (self.words(b + 208, 3), e.u32(b + 220),
                     self.words(b + 224, 4), self.words(b + 240, 4)))
        if b in self.d:
            self.emit("    side %s" % self.words(self.side[self.d.index(b)],
                                                 SIDE_WORDS))
        if b in self.ebody:
            s = self.es[self.ebody.index(b)]
            self.emit("    e pen %08x yaw %08x" % (e.u32(b + 260),
                                                   e.u32(b + 264)))
            self.emit("    epos %s cv %s" % (self.words(s + E_POS, 8),
                                            self.words(s + E_CV, 8)))
        if e.u32(b + 80) == VT_CAR:
            self.emit("    car %s pen %08x yaw %08x"
                      % (L(e.u32(b + 256)), e.u32(b + 260), e.u32(b + 264)))
            self.emit("    sit %s" % self.words(b + 272, 16))
            p = e.u32(b + 8)
            if p in self.blocks:        # the box: its corners and faces
                for k in range(8):
                    self.emit("    v%d %s" % (k, self.words(p + 48 + 20 * k
                                                            + 4, 3)))
                for k in range(6):
                    self.emit("    f%d %s" % (k, self.words(p + 352 + 24 * k
                                                            + 4, 4)))

    def witness_dump(self, w):
        e, L = self.e, self.label
        v = w + 16
        p1, p2 = e.u32(v + 12), e.u32(v + 16)
        self.emit("  wit %s b1 %s b2 %s coll %s ss %d f1 %s f2 %s p1 %s p2 %s "
                  "cp %s %s dist %08x caff %s %s"
                  % (L(w), L(e.u32(w + 96)), L(e.u32(w + 100)),
                     L(e.u32(w + 104)), s32(e.u32(v)),
                     self.feature(e.u32(v + 4), p1),
                     self.feature(e.u32(v + 8), p2), L(p1), L(p2),
                     self.words(v + 32, 3), self.words(v + 48, 3),
                     e.u32(v + 64), L(e.u32(v + 68)), L(e.u32(v + 72))))

    def walk(self, head, off):
        e, out = self.e, []
        n = e.u32(head + off)
        while n != head and len(out) < MAX_WALK:
            out.append(n)
            n = e.u32(n + off)
        return out

    def dump(self):
        e, L = self.e, self.label
        self.emit("dump")
        self.emit("  zv %s" % self.words(ZV, 4))
        self.emit("  im %s" % self.words(IM, 16))
        self.emit("  zm %s" % self.words(ZM, 16))
        self.emit("  stats %s" % " ".join("%d" % s32(e.u32(STATS + 4 * k))
                                          for k in range(18)))
        self.emit("  maxw %08x" % e.u32(MAXW))
        self.emit("  heads %s %s %s %s"
                  % (L(e.u32(BLIST)), L(e.u32(BLIST + 4)), L(e.u32(WLIST)),
                     L(e.u32(WLIST + 4))))
        table, alloc, wbits = e.u32(TABLE), e.u32(ALLOC), e.u32(WBITS)
        self.emit("  ptrs table %s alloc %s wbits %s"
                  % (L(table), L(alloc), L(wbits)))
        if table:
            self.emit("  table" + "".join(
                " %d:%s" % (i, L(e.u32(table + 4 * i)))
                for i in range(MAX_BODIES) if e.u32(table + 4 * i)))
        if alloc:
            mx, fld = s32(e.u32(alloc)), e.u32(alloc + 4)
            self.emit("  alloc max %d lowest %d field %s"
                      % (mx, s32(e.u32(alloc + 8)), L(fld)))
            if fld and mx > 0:
                self.bytes_line("   ", fld, (mx >> 3) + 1)
        if wbits:
            data = e.read(wbits, BITFIELD_BYTES + 1)
            pairs = []
            for i, byte in enumerate(data):
                if byte:
                    for j in range(8):
                        if byte & (1 << j):
                            k = 8 * i + j
                            pairs.append(" %d,%d" % (k // MAX_BODIES,
                                                     k % MAX_BODIES))
            self.emit("  wbits" + "".join(pairs))
        for name, var in (("tpcb", POOL_TPCB), ("car", POOL_CAR),
                          ("wit", POOL_WIT), ("tp", POOL_TP)):
            self.pool_dump(name, var)
        if e.u32(BLIST):
            fwd, back = self.walk(BLIST, 0), self.walk(BLIST, 4)
            self.emit("  list" + "".join(" " + L(b) for b in fwd) + " |"
                      + "".join(" " + L(b) for b in back))
            for b in fwd:
                self.body_dump(b)
        if e.u32(WLIST):
            fwd, back = self.walk(WLIST, 0), self.walk(WLIST, 4)
            self.emit("  wlist" + "".join(" " + L(w) for w in fwd) + " |"
                      + "".join(" " + L(w) for w in back))
            for w in fwd:
                self.witness_dump(w)
        if e.u32(POOL_TP):
            for n in self.walk(TREE + 32, 0):
                self.emit("  tp %s ref %d fl %d ty %d cb %s"
                          % (L(n), e.u8(n + 8), e.u8(n + 10), e.u8(n + 11),
                             L(e.u32(n + 16))))
        if any(self.pp_linked):
            self.emit("  pplist" + "".join(" " + L(p)
                                          for p in self.walk(PPLIST, 0))
                      + " |" + "".join(" " + L(p)
                                       for p in self.walk(PPLIST, 4)))
            for k, p in enumerate(self.pps):
                if not self.pp_linked[k]:
                    continue
                n = s16(e.u16(p + 16))
                self.emit("  pp PP%d hash %08x fixed %d n %d va %s"
                          % (k, e.u32(p + 48), s32(e.u32(p + 84)), n,
                             "ok" if e.u32(p + 32) == self.ppverts[k]
                             else "?"))
                for j in range(min(max(n, 0), NPPVERT)):
                    self.emit("    v%d %s" % (j, self.words(
                        self.ppverts[k] + 20 * j + 4, 3)))

    def vt_dump(self):
        e = self.e
        for vt in (VT_BASE, VT_STATIC, VT_TP, VT_DYN, VT_CAR):
            self.emit("vt %08x %d" % (vt, VT_ENTRIES))
            for i in range(VT_ENTRIES):
                a = vt + 8 * i
                fn = e.u32(a + 4)
                if fn == 0:
                    name = "0"
                else:
                    name = e.elf.by_addr.get(fn, "?")
                    if name.startswith("DoSnapshot__"):
                        name = "DoSnapshot"
                self.emit("  %d %d %d %s" % (8 * i, s16(e.u16(a)),
                                             s16(e.u16(a + 2)), name))

    # ---- calls ------------------------------------------------------------

    def call(self, name, *args):
        return self.e.call(self.fn[name], *[s32(a) for a in args])

    def ret_f(self):
        return self.e.fpr[0] & M32

    def vcall(self, b, slot):
        e, L = self.e, self.label
        ent = e.u32(b + 80) + slot
        this, fn = b + s16(e.u16(ent)), e.u32(ent + 4)
        e.write(self.outv, b"\x5a" * 128)
        head = "vcall %s %d -> " % (L(b), slot)

        def go(*args):
            return e.call(fn, *[s32(a) for a in args])

        def vec(k):
            return "  out%d %s" % (k, self.words(self.outv + 16 * k, 4))

        if slot in (VT_GETPOS, VT_GETVEL, VT_GETROT, VT_INERTIA):
            self.emit(head + L(go(this)))
        elif slot == VT_SETPOS:
            go(this, self.inv)
            self.emit(head + "ok")
        elif slot in (VT_MAXBACKUP, VT_MASSINV, VT_BOUNCE, VT_FRICTION):
            go(this)
            self.emit(head + "%08x" % self.ret_f())
        elif slot in (VT_MOVE, VT_BACKUP):
            e.fpr[12] = bits(0.25)
            go(this)
            self.emit(head + "ok")
        elif slot == VT_INTERP:
            e.fpr[12] = bits(0.5)
            go(this, self.outv, self.outm)
            self.emit(head + "ok")
            self.emit(vec(0))
            self.emit("  outm %s" % self.words(self.outm, 16))
        elif slot == VT_RECOMPUTE:
            go(this)
            self.emit(head + "ok")
        elif slot == VT_CURVEL:
            go(this, self.outv, self.outv + 16)
            self.emit(head + "ok")
            for k in range(2):
                self.emit(vec(k))
        elif slot == VT_TESTVEL:
            go(this, self.outv, self.outv + 16, self.outv + 32,
               self.outv + 48)
            self.emit(head + "ok")
            for k in range(4):
                self.emit(vec(k))
        elif slot == VT_PHYSMODE:
            go(this, self.h[0])
            self.emit(head + "ok")
        elif slot in (VT_CONSIDER, VT_ENERGY):
            go(this, self.inv, self.inv + 16)
            self.emit(head + "%08x" % self.ret_f())
        elif slot == VT_APPLY:
            go(this, self.inv, self.inv + 16)
            self.emit(head + "ok")
        elif slot in (VT_ENABLED, VT_TERRAIN, VT_MOVEABLE, VT_BLINKING):
            self.emit(head + "%d" % s32(go(this)))
        else:
            raise AssertionError("vcall of slot %d" % slot)

    def put_vec2(self, a, x, y):
        self.e.put32(a, x)
        self.e.put32(a + 4, y)

    # ---- the run ----------------------------------------------------------

    def run(self):
        e, w, emit, L = self.e, self.sc.words, self.emit, self.label
        i = 0

        def arg():
            nonlocal i
            i += 1
            return w[i - 1]

        def args(n):
            nonlocal i
            i += n
            return w[i - n:i]

        while i < len(w):
            code = arg()
            if code == OP_TAG:
                emit("[%d]" % arg())
            elif code == OP_STATIC_INIT:
                emit("static init")
                self.call("sinit")
            elif code == OP_STATIC_CLOSE:
                emit("static close")
                self.call("sclose")
            elif code == OP_INIT:
                emit("init")
                self.call("init")
            elif code == OP_CLOSE:
                emit("close")
                self.call("close")
            elif code == OP_TREE_INIT:
                emit("tree init")
                self.call("inittree", TREE)
            elif code == OP_TREE_CLOSE:
                emit("tree close")
                self.call("closetree", TREE)
            elif code == OP_TREE_LOAD:
                n = arg()
                e.write(self.chunk, struct.pack("<%dI" % n, *args(n)))
                r = self.call("ttloader", TREE, self.chunk)
                emit("tree load -> %d polys %d" % (r, s32(e.u32(TREE + 20))))
            elif code == OP_FILL_H:
                h, v = args(2)
                e.write(self.body(h), bytes([v]) * (84 if h < NH else D_BYTES))
            elif code in (OP_BASE_NEW, OP_STATIC_NEW):
                h, id_, ty = args(3)
                r = self.call("base_ctor" if code == OP_BASE_NEW
                              else "static_ctor", self.h[h], id_, ty)
                emit("%s new H%d %d %d -> %s"
                     % ("base" if code == OP_BASE_NEW else "static", h,
                        s32(id_), s32(ty), L(r)))
            elif code == OP_TP_NEW:
                id_, p = args(2)
                emit("tp new %d poly %d" % (s32(id_), p))
                m = self.call("tp_new", 1080) & M32
                emit("  new %s" % L(m))
                if m:
                    r = self.call("tp_ctor", m, id_,
                                  e.u32(TREE + 16) + 32 * p)
                    emit("  -> %s" % L(r))
            elif code == OP_VDEL:
                r, fl = args(2)
                b = self.body(r)
                emit("vdel %s %d" % (L(b), s32(fl)))
                ent = e.u32(b + 80) + VT_DESTROY
                e.call(e.u32(ent + 4), s32(b + s16(e.u16(ent))), s32(fl))
            elif code == OP_DTOR:
                r, kind, fl = args(3)
                b = self.body(r)
                emit("dtor %s %d %d" % (L(b), kind, s32(fl)))
                self.call(("base_dtor", "static_dtor", "tp_dtor")[kind], b, fl)
            elif code == OP_SET_POLY:
                h, k = args(2)
                e.put32(self.body(h) + 8, self.polys[k])
            elif code == OP_SETBOX:
                r, x0, y0, x1, y1 = args(5)
                b = self.body(r)
                self.put_vec2(self.vmin, x0, y0)
                self.put_vec2(self.vmax, x1, y1)
                emit("setbox %s %08x %08x %08x %08x" % (L(b), x0, y0, x1, y1))
                self.call("setbox", b, self.vmin, self.vmax)
            elif code == OP_RAWBOX:
                r = arg()
                b = self.body(r)
                for k, v in enumerate(args(4)):
                    e.put32(b + 20 + 4 * k, v)
            elif code == OP_UPDW:
                r, wb = args(2)
                b = self.body(r)
                e.fpr[12] = wb
                self.call("updw", b)
                emit("updw %s %08x -> %08x" % (L(b), wb, e.u32(MAXW)))
            elif code == OP_SETMAXW:
                e.put32(MAXW, arg())
            elif code == OP_FLIP:
                a, b = (self.body(x) for x in args(2))
                emit("flip %s %s -> %d" % (L(a), L(b),
                                           s32(self.call("flip", a, b))))
            elif code == OP_NAME:
                r = arg()
                e.write(self.name, struct.pack("<12I", *args(12)))
                b = self.body(r)
                emit("name %s" % L(b))
                self.call("name", b, self.name)
            elif code == OP_FIND:
                k = arg()
                emit("find %d -> %s" % (s32(k), L(self.call("find", k))))
            elif code == OP_NEXTID:
                emit("nextid -> %d" % s32(self.call("nextid")))
            elif code == OP_GETCOLL:
                r, k = args(2)
                b = self.body(r)
                emit("getcoll %s %d -> %s"
                     % (L(b), s32(k), L(self.call("getcoll", b, k))))
            elif code in (OP_ENABLE, OP_DISABLE):
                b = self.body(arg())
                emit("%s %s" % ("enable" if code == OP_ENABLE else "disable",
                                L(b)))
                self.call("enable" if code == OP_ENABLE else "disable", b)
            elif code == OP_BBOX:
                r, x0, y0, x1, y1, m = args(6)
                b = self.body(r)
                self.put_vec2(self.vmin, x0, y0)
                self.put_vec2(self.vmax, x1, y1)
                e.fpr[12] = m
                res = s32(self.call("bbox", b, self.vmin, self.vmax))
                emit("bbox %s %08x %08x %08x %08x %08x -> %d"
                     % (L(b), x0, y0, x1, y1, m, res))
            elif code == OP_BBOXB:
                ra, rb, m = args(3)
                a, b = self.body(ra), self.body(rb)
                e.fpr[12] = m
                res = s32(self.call("bboxb", a, b))
                emit("bboxb %s %s %08x -> %d" % (L(a), L(b), m, res))
            elif code == OP_SETB:
                r, off, v = args(3)
                e.mem[self.body(r) + off] = v & 0xFF
            elif code == OP_NA_SET:
                n = arg()
                emit("na set %d" % s32(n))
                self.call("na_set", self.na, n)
            elif code == OP_NA_ALLOC:
                emit("na alloc -> %d" % s32(self.call("na_alloc", self.na)))
            elif code == OP_NA_ALLOCN:
                n = arg()
                emit("na allocn %d" % s32(n))
                self.call("na_allocn", self.na, n)
            elif code == OP_NA_FREE:
                n = arg()
                emit("na free %d" % s32(n))
                self.call("na_free", self.na, n)
            elif code == OP_NA_DESTROY:
                fl = arg()
                emit("na destroy %d" % s32(fl))
                self.call("na_dtor", self.na, fl)
            elif code == OP_NA_DUMP:
                mx, fld = s32(e.u32(self.na)), e.u32(self.na + 4)
                emit("na max %d lowest %d field %s"
                     % (mx, s32(e.u32(self.na + 8)), L(fld)))
                if fld and mx > 0:
                    self.bytes_line("   ", fld, (mx >> 3) + 1)
            elif code == OP_WIT_NEW:
                a, b = (self.body(x) for x in args(2))
                emit("wit new %s %s" % (L(a), L(b)))
                m = self.call("omalloc", e.u32(POOL_WIT)) & M32
                emit("  new %s" % L(m))
                emit("  -> %s" % L(self.call("wit_ctor", m, a, b)))
            elif code == OP_WIT_DEL:
                s, fl = args(2)
                wt = self.witness(s)
                emit("wit del %s %d" % (L(wt), s32(fl)))
                self.call("wit_dtor", wt, fl)
            elif code == OP_WIT_SETCOLL:
                s, k = args(2)
                e.put32(self.witness(s) + 104, self.colls[k - 1] if k else 0)
            elif code == OP_WIT_END:
                wt = self.witness(arg())
                emit("wit end %s" % L(wt))
                self.call("wit_end", wt)
            elif code == OP_EXPIRED:
                wt = self.witness(arg())
                emit("expired %s -> %d" % (L(wt),
                                           s32(self.call("expired", wt))))
            elif code == OP_EXISTS:
                a, b = (self.body(x) for x in args(2))
                emit("exists %s %s -> %d"
                     % (L(a), L(b), s32(self.call("exists", a, b))))
            elif code == OP_YAW:
                b = self.body(arg())
                emit("yaw %s -> %d" % (L(b), s32(self.call("yaw", b))))
            elif code == OP_ELIM:
                emit("elim")
                self.call("elim")
            elif code == OP_VCALL:
                r, slot = args(2)
                self.vcall(self.body(r), slot)
            elif code == OP_VTDUMP:
                self.vt_dump()
            elif code == OP_DUMP:
                self.dump()
            elif code == OP_STAT:
                k, v = args(2)
                e.put32(STATS + 4 * k, v)
            elif code == OP_TPPOKE:
                s, off, v = args(3)
                e.mem[e.u32(POOL_TP) + HEADER + 128 * s + off] = v & 0xFF
            elif code == OP_ACCESS:
                b = self.body(arg())
                c = self.call
                line = ("access %s vt %s max %s min %s nc %d poly %s name %s "
                        "act %d id %d dyn %d"
                        % (L(b), self.vtname(e.u32(b + 80)),
                           "ok" if c("g_max", b) & M32 == b + 28
                           else "?",
                           "ok" if c("g_min", b) & M32 == b + 20 else "?",
                           s32(c("g_nc", b)), L(c("g_poly", b)),
                           "name" if c("g_name", b) & M32 == b + 36 else "?",
                           s32(c("g_act", b)), s32(c("g_id", b)),
                           s32(c("g_dyn", b))))
                if e.u32(b + 80) == VT_TP:
                    line += " tp %s" % L(c("tp_gettp", b))
                emit(line)
            elif code >= OP_E_STATE:
                self.ct_op(code, arg, args)
            elif code >= OP_CAR_NEW:
                self.car_op(code, arg, args)
            elif code >= OP_DYN_NEW:
                self.dyn_op(code, arg, args)
            else:
                raise AssertionError("bad op %d at word %d" % (code, i - 1))
        return self.out

    def dyn_op(self, code, arg, args):
        e, emit, L = self.e, self.emit, self.label

        def vec(k):
            emit("  out%d %s" % (k, self.words(self.outv + 16 * k, 4)))

        def fill():
            e.write(self.outv, b"\x5a" * 128)

        def poly(p):
            return e.u32(TREE + 16) + 32 * p

        if code == OP_DYN_NEW:
            r, id_, ty, tc = args(4)
            b, tcp = self.body(r), self.tc if tc else 0
            res = self.call("dyn_ctor", b, id_, ty, tcp)
            emit("dyn new %s %d %d %s -> %s"
                 % (L(b), s32(id_), s32(ty), L(tcp), L(res)))
        elif code == OP_DYN_SETVT:
            r, k = args(2)
            e.put32(self.body(r) + 80, self.dyn_tables[k])
        elif code == OP_DYN_POKE:
            r, off, v = args(3)
            e.put32(self.body(r) + off, v)
        elif code == OP_DYN_PTRS:
            r, sy, rb = args(3)
            b = self.body(r)
            e.put32(b + 92, self.ps if sy else 0)
            e.put32(b + 96, self.rb[rb] if s32(rb) >= 0 else 0)
        elif code == OP_DYN_SIDE:
            r = arg()
            e.write(self.side[r - REF_D],
                    struct.pack("<%dI" % SIDE_WORDS, *args(SIDE_WORDS)))
        elif code == OP_DPOLY:
            k, num, cnt = args(3)
            struct.pack_into("<h", e.mem, self.dpolys[k] + 16, s16(num))
            for j in range(cnt):
                e.write(self.dverts[k] + 20 * j + 4,
                        struct.pack("<3I", *args(3)))
        elif code == OP_DYN_SETPOLY:
            r, k = args(2)
            e.put32(self.body(r) + 8, self.dpolys[k])
        elif code in (OP_DYN_BUILD, OP_DYN_UPDATE, OP_DYN_WITNESSES):
            b = self.body(arg())
            name, fn = {OP_DYN_BUILD: ("build", "dyn_build"),
                        OP_DYN_UPDATE: ("update", "dyn_update"),
                        OP_DYN_WITNESSES: ("witnesses", "dyn_witnesses")}[code]
            emit("dyn %s %s" % (name, L(b)))
            self.call(fn, b)
        elif code in (OP_DYN_BEGIN, OP_DYN_BACKUP):
            r, t = args(2)
            b = self.body(r)
            emit("dyn %s %s %08x"
                 % ("begin" if code == OP_DYN_BEGIN else "backup", L(b), t))
            e.fpr[12] = t
            self.call("dyn_begin" if code == OP_DYN_BEGIN else "dyn_backup", b)
        elif code == OP_DYN_INTERP:
            r, t = args(2)
            b = self.body(r)
            fill()
            emit("dyn interp %s %08x" % (L(b), t))
            e.fpr[12] = t
            self.call("dyn_interp", b, self.outv, self.outm)
            vec(0)
            emit("  outm %s" % self.words(self.outm, 16))
        elif code == OP_DYN_INTERPV:
            r, t = args(2)
            b = self.body(r)
            fill()
            emit("dyn interpv %s %08x" % (L(b), t))
            e.fpr[12] = t
            self.call("dyn_interpv", b, self.outv)
            vec(0)
        elif code == OP_DYN_TESTVEL:
            b = self.body(arg())
            fill()
            emit("dyn testvel %s" % L(b))
            self.call("dyn_testvel", b, self.outv, self.outv + 16, self.inv,
                      self.inv + 16)
            vec(0)
            vec(1)
        elif code == OP_RB_SET:
            k = arg()
            e.write(self.rb[k] + RB_FIRST,
                    struct.pack("<%dI" % RB_WORDS, *args(RB_WORDS)))
        elif code == OP_RB_DUMP:
            k = arg()
            emit("rb RB%d" % k)
            for o in range(RB_FIRST, RB_END, 32):
                emit("  %d %s" % (o, self.words(self.rb[k] + o,
                                                min(8, (RB_END - o) // 4))))
        elif code == OP_DYN_LOCAL:
            r, m = args(2)
            b = self.body(r)
            e.write(self.lp, b"\x5a" * 8)
            e.fpr[12] = m
            self.call("dyn_local", b, self.lp, self.lp + 4)
            emit("dyn local %s %08x -> %s %s"
                 % (L(b), m, L(e.u32(self.lp)), L(e.u32(self.lp + 4))))
        elif code == OP_DYN_CREATE_TP:
            b = self.body(arg())
            emit("dyn create tp %s" % L(b))
            emit("  -> %d" % s32(self.call("dyn_createtp", b)))
        elif code == OP_DYN_TPCHECK:
            r, k = args(2)
            b, tp = self.body(r), self.tps[k]
            emit("dyn tpcheck %s %s" % (L(b), L(tp)))
            emit("  -> %d" % s32(self.call("dyn_tpcheck", b, tp)))
        elif code == OP_TP_ASSIGN:
            p = arg()
            tp = self.call("tp_assign", TREE, poly(p)) & M32
            self.tps.append(tp)
            emit("tp assign %d -> %s" % (p, L(tp)))
        elif code == OP_TP_GEOM:
            k = arg()
            tp = self.tps[k]
            v = args(8)
            e.write(tp + 20, struct.pack("<4I", *v[:4]))
            e.write(tp + 112, struct.pack("<4I", *v[4:]))
        elif code == OP_TC_SET:
            n = arg()
            e.put32(self.tc + TC_TOTAL, n)
            for j, k in enumerate(args(n)):
                e.put32(self.tc + TC_TABLE + 4 * j, self.tps[k])
        elif code == OP_SMOKE:
            fr, to = args(2)
            self.smoke[self.body(fr)] = self.body(to) if s32(to) >= 0 else 0
        elif code == OP_DYN_DTOR:
            r, fl = args(2)
            b = self.body(r)
            emit("dyn dtor %s %d" % (L(b), s32(fl)))
            self.call("dyn_dtor", b, fl)
        elif code == OP_DYN_BBOX:
            b = self.body(arg())
            fill()
            emit("dyn bbox %s" % L(b))
            self.call("dyn_bbox", b, self.outv, self.outv + 16)
            vec(0)
            vec(1)
        elif code == OP_TP_FILL:
            p, n = args(2)
            pool, made = e.u32(POOL_TPCB), 0
            while s32(e.u32(pool + 24)) < n:
                m = self.call("tp_new", 1080) & M32
                assert m, "TP_FILL past the pool"
                self.call("tp_ctor", m, -1, poly(p))
                made += 1
            emit("tp fill %d %d -> %d" % (p, n, made))
        else:
            raise AssertionError("bad op %d" % code)


    def car_op(self, code, arg, args):
        e, emit, L = self.e, self.emit, self.label

        def through(b, slot, *a):
            ent = e.u32(b + 80) + slot
            return e.call(e.u32(ent + 4), s32(b + s16(e.u16(ent))),
                          *[s32(x) for x in a])

        if code == OP_CAR_NEW:
            k = arg()
            emit("car new CAR%d" % k)
            m = self.call("ccb_new", CAR_SLOT) & M32
            emit("  new %s" % L(m))
            if m:
                emit("  -> %s" % L(self.call("ccb_ctor", m, self.cars[k])))
        elif code == OP_CAR_DTOR:
            r, fl = args(2)
            b = self.body(r)
            emit("car dtor %s %d" % (L(b), s32(fl)))
            self.call("ccb_dtor", b, fl)
        elif code == OP_CAR_FIELD:
            k, f, v = args(3)
            c = self.cars[k]
            if f == CF_DRIVER:
                struct.pack_into("<h", e.mem, c + CAR_DRIVER, s16(v))
            elif f == CF_NAME:
                e.write(self.ctis[k] + CTI_NAME,
                        (CAR_NAMES[v].encode() + bytes(32))[:32])
            elif f == CF_PLAYER:
                e.put32(c + CAR_PLAYER, self.pl0 if v else 0)
            elif f == CF_MODE:
                e.put32(c + CAR_MODE, v)
            elif f == CF_MOVER:
                e.put32(c + CAR_MOVER, (0, self.m0, self.m1)[v])
            elif f == CF_ANIM:
                e.put32(c + CAR_ANIM, self.ad0 if v else 0)
            elif f == CF_DAMAGE:
                e.put32(c + CAR_DAMAGE, self.dmg0 if v else 0)
            elif f == CF_BLINK:
                self.blink[k] = s32(v)
            elif f == CF_POOF:
                self.poof[k] = s32(v)
            else:
                raise AssertionError("car field %d" % f)
        elif code == OP_CAR_SIDE:
            c = self.cars[arg()]
            w = args(SIDE_WORDS)
            e.write(c + CAR_POS, struct.pack("<8I", *w[:8]))
            e.write(c + CAR_ROT, struct.pack("<16I", *w[8:]))
        elif code == OP_CAR_COG:
            k = arg()
            e.write(self.ctis[k] + CTI_COG, struct.pack("<4I", *args(4)))
        elif code == OP_GLOBAL:
            g, v = args(2)
            if g == G_RC:
                e.put32(G_RC_AT, self.rc0 if v else 0)
            elif g == G_COP:
                e.put32(G_COP_AT, self.cop0 if v else 0)
            elif g == G_STATE:
                e.put32(self.rc0, v)
            elif g == G_PORT:
                e.put32(self.pl0 + 8, v)
            elif g == G_SEAMS:
                self.seams_off = v
            else:
                e.put32({G_BORING: G_BORING_AT, G_WILLIAMS: G_WILLIAMS_AT,
                         G_TIMER: G_TIMER_AT, G_PRINT: G_PRINT_AT,
                         G_LOOP: G_LOOP_AT, G_THRESH: G_THRESH_AT,
                         G_BIAS: G_BIAS_AT, G_MINFACTOR: G_MINFACTOR_AT,
                         G_MINSPEED: G_MINSPEED_AT,
                         G_SCRAPE: G_SCRAPE_AT}[g], v)
        elif code == OP_PP:
            k, h, fixed, n = args(4)
            p = self.pps[k]
            e.put32(p + 48, h)
            e.put32(p + 84, fixed)
            struct.pack_into("<h", e.mem, p + 16, s16(n))
            for j in range(n):
                e.write(self.ppverts[k] + 20 * j + 4,
                        struct.pack("<3I", *args(3)))
            if not self.pp_linked[k]:   # at the tail, as the loader links
                tail = e.u32(PPLIST + 4)
                e.put32(p + 4, tail)
                e.put32(tail, p)
                e.put32(PPLIST + 4, p)
                e.put32(p, PPLIST)
                self.pp_linked[k] = True
        elif code == OP_CAR_MOVE:
            r, t, n = args(3)
            self.move_q = list(args(n))
            b = self.body(r)
            emit("car move %s %08x" % (L(b), t))
            e.fpr[12] = t
            through(b, VT_MOVE)
            self.move_q = []
        elif code == OP_CAR_APPLY:
            b = self.body(arg())
            e.write(self.cv, struct.pack("<8I", *args(8)))
            emit("car apply %s" % L(b))
            through(b, VT_APPLY, self.cv, self.cv + 16)
        elif code in (OP_CAR_DAMAGE, OP_CAR_ANIM):
            b = self.body(arg())
            e.write(self.cv, struct.pack("<4I", *args(4)))
            amt = arg()
            emit("car %s %s %08x" % ("damage" if code == OP_CAR_DAMAGE
                                     else "anim", L(b), amt))
            e.fpr[12] = amt
            self.call("ccb_damage" if code == OP_CAR_DAMAGE else "ccb_anim",
                      b, self.cv)
        elif code == OP_CAR_TIMES:
            r, pen, yaw = args(3)
            b = self.body(r)
            e.put32(self.tbuf, pen)
            self.call("ccb_setpen", b, self.tbuf)
            e.put32(self.tbuf, yaw)
            self.call("ccb_setyaw", b, self.tbuf)
            emit("car times %s -> pen %08x yaw %08x car %s"
                 % (L(b), self.call("ccb_getpen", b) & M32,
                    self.call("ccb_getyaw", b) & M32,
                    L(self.call("ccb_getcar", b))))
        elif code == OP_CAR_STPM:
            r, o = args(2)
            b = self.body(r)
            ob = self.body(o) if s32(o) >= 0 else 0
            emit("car stpm %s %s" % (L(b), L(ob)))
            through(b, VT_PHYSMODE, ob)
            emit("  -> sys %s rb %s" % (L(e.u32(b + 92)), L(e.u32(b + 96))))
        else:
            raise AssertionError("bad op %d" % code)


    def ct_op(self, code, arg, args):
        e, emit, L = self.e, self.emit, self.label

        def x_of(x):
            if x == REF_NEWEST and self.newest:
                return self.newest
            if REF_LIST <= x < REF_NEWEST:
                fwd = self.walk(self.clist, 0)
                assert x - REF_LIST < len(fwd), x
                return fwd[x - REF_LIST]
            p = e.u32(POOL_CONTACT)
            assert x < REF_LIST and p, x
            return p + HEADER + CT_BYTES * x

        def vec(k):
            emit("  out%d %s" % (k, self.words(self.outv + 16 * k, 4)))

        def fill():
            e.write(self.outv, b"\x5a" * 64)

        def put(a, n):
            e.write(a, struct.pack("<%dI" % n, *args(n)))

        if code == OP_E_STATE:
            k = arg()
            w = args(E_VEC_WORDS + 6)
            e.write(self.es[k], struct.pack("<%dI" % E_VEC_WORDS,
                                            *w[:E_VEC_WORDS]))
            s = w[E_VEC_WORDS:]
            self.escal[k] = dict(maxbackup=s[0], minv=s[1], bounce=s[2],
                                 friction=s[3], moveable=s32(s[4]),
                                 blinking=s32(s[5]))
        elif code == OP_E_QUEUE:
            k, n = args(2)
            assert n <= NEQ, n
            self.eq[k] = list(args(n))
            self.eqat[k] = 0
        elif code == OP_BOX:
            k = arg()
            for j, v in enumerate(args(6)):
                e.fpr[12 + j] = v
            self.call("rectpoly", self.boxes[k])
        elif code == OP_BOX_SET:
            r, k = args(2)
            e.put32(self.body(r) + 8, self.boxes[k])
        elif code == OP_TP_VERTS:
            put(self.tps[arg()] + 48, 16)
        elif code == OP_CT_INIT:
            emit("ct init")
            self.call("ct_init")
        elif code == OP_CT_CLOSE:
            emit("ct close")
            self.call("ct_close")
        elif code == OP_CT_TEST:
            wv = arg()
            emit("ct test W%d" % wv)
            self.call("ct_test", self.witness(wv), self.clist)
            emit("  print %d" % s32(e.u32(G_PRINT_AT)))
        elif code == OP_CT_RESOLVE:
            c = x_of(arg())
            emit("ct resolve %s" % L(c))
            self.call("ct_resolve", c)
        elif code == OP_CT_REMOVE:
            b = self.body(arg())
            emit("ct remove %s" % L(b))
            self.call("ct_remove", self.clist, b)
        elif code == OP_CT_DUMP:
            emit("ct dump")
            fwd, back = self.walk(self.clist, 0), self.walk(self.clist, 4)
            emit("  clist" + "".join(" " + L(c) for c in fwd) + " |"
                 + "".join(" " + L(c) for c in back))
            for c in fwd:
                emit("  contact %s bt %08x b1 %s b2 %s wit %s cv %s lf %d"
                     % (L(c), e.u32(c + 8), L(e.u32(c + 12)),
                        L(e.u32(c + 16)), L(e.u32(c + 20)),
                        self.words(c + 32, 4), s32(e.u32(c + 48))))
            self.pool_dump("contact", POOL_CONTACT)
        elif code == OP_CT_NEW:
            wv = arg()
            w = self.witness(wv)
            emit("ct new W%d" % wv)
            c = self.call("omalloc", e.u32(POOL_CONTACT)) & M32
            emit("  new %s" % L(c))
            self.newest = c
            r = self.call("ct_ctor", c, e.u32(w + 96), e.u32(w + 100), w)
            emit("  -> %s" % L(r))
        elif code == OP_CT_TIME:
            c = x_of(arg())
            emit("ct time %s" % L(c))
            self.call("ct_time", c)
            emit("  -> %08x cv %s" % (self.ret_f(), self.words(c + 32, 4)))
        elif code == OP_CT_CROWBAR:
            x, t = args(2)
            c = x_of(x)
            emit("ct crowbar %s %08x" % (L(c), t))
            e.fpr[12] = t
            self.call("ct_crowbar", c)
            emit("  cv %s" % self.words(c + 32, 4))
        elif code == OP_CT_POINT:
            c = x_of(arg())
            emit("ct point %s" % L(c))
            fill()
            self.call("ct_point", c, self.outv, self.outv + 16)
            vec(0)
            vec(1)
        elif code == OP_CT_PLANAR:
            c = x_of(arg())
            fill()
            put(self.outv, 4)
            emit("ct planar %s" % L(c))
            self.call("ct_planar", c, self.outv)
            vec(0)
        elif code == OP_CT_IMPULSE:
            c = x_of(arg())
            emit("ct impulse %s" % L(c))
            self.call("ct_impulse", c)
        elif code == OP_CT_CPV:
            put(self.ctv, 12)
            fill()
            emit("ct cpv")
            self.call("ct_cpv", self.outv, self.ctv, self.ctv + 16,
                      self.ctv + 32)
            vec(0)
        elif code == OP_CT_DENOM:
            put(self.ctm, 16)
            put(self.ctv, 8)
            self.call("ct_denom", self.ctm, self.ctv, self.ctv + 16)
            emit("ct denom -> %08x" % self.ret_f())
        elif code == OP_CT_WAFER:
            t, d = self.body(arg()), self.body(arg())
            emit("ct wafer %s %s" % (L(t), L(d)))
            fill()
            self.call("ct_wafer", self.outv, t, d)
            vec(0)
        elif code == OP_CT_SORT:
            c, d = (x_of(x) for x in args(2))
            emit("ct sort %s %s -> %d"
                 % (L(c), L(d), s32(self.call("ct_sort", c, d))))
        elif code in (OP_CT_GETCOLL, OP_CT_BEGIN):
            wv = arg()
            w = self.witness(wv)
            put(self.ctv, 4)
            if code == OP_CT_GETCOLL:
                emit("ct getcoll W%d" % wv)
                r = self.call("ct_getcoll", w, self.ctv)
            else:
                emit("ct begin W%d" % wv)
                self.call("ct_begin", w, self.ctv)
                r = e.u32(w + 104)
            emit("  -> %s" % L(r))
        elif code == OP_CT_DEL:
            x, flags = args(2)
            c = x_of(x)
            emit("ct del %s %d" % (L(c), s32(flags)))
            self.call("ct_dtor", c, flags)
        elif code == OP_CT_POKE:
            x, f, v = args(3)
            assert f <= XF_LF, f
            e.put32(x_of(x) + (8 if f == XF_BT else 48 if f == XF_LF
                               else 32 + 4 * (f - XF_CV)), v)
        elif code == OP_CT_LINK:
            c = x_of(arg())
            tail = e.u32(self.clist + 4)
            e.put32(c + 4, tail)
            e.put32(c, self.clist)
            e.put32(tail, c)
            e.put32(self.clist + 4, c)
        elif code == OP_WIT_CP:
            w = self.witness(arg())
            put(w + 48, 4)
            put(w + 64, 4)
        else:
            raise AssertionError("bad op %d" % code)


def model(sc):
    m = Model(sc)
    lines = m.run()
    # CollisionImpulse's -k / vtl is ee_div in the port: a contact with no
    # slide at all divides by zero there, and the script has one.
    if m.e.eediv_pcs - {IMPULSE_DIV}:
        sys.exit("the model divided by zero at %s -- the ports follow IEEE "
                 "there; keep the script clear of it"
                 % " ".join("%08x" % p for p in sorted(m.e.eediv_pcs
                                                       - {IMPULSE_DIV})))
    if IMPULSE_DIV not in m.e.eediv_pcs:
        sys.exit("the script never gives CollisionImpulse a contact with no "
                 "slide")
    stray = m.e.eesqrt_pcs - {TPCHECK_SQRT}
    if stray:
        sys.exit("the model took the root of a negative at %s, where the port "
                 "uses sqrtf" % " ".join("%08x" % p for p in sorted(stray)))
    if TPCHECK_SQRT not in m.e.eesqrt_pcs:
        sys.exit("the script never gives TrackPolygonCheck's root a negative")
    return lines


# ---------------------------------------------------------------- running

# The whole script runs in a second or two; a mutant that loses a body off
# the list or keeps one on it after its destructor walks forever.
HARNESS_TIMEOUT = 30
HARNESS_HUNG = -9999


def write_script(sc, path):
    Path(path).write_bytes(struct.pack("<%dI" % len(sc.words), *sc.words))


def run_harness(exe, script_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(script_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def diff(model_lines, harness_lines, quiet=False):
    bad = 0
    for line in difflib.unified_diff(model_lines, harness_lines,
                                     "model", "harness", lineterm="", n=1):
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            bad += 1
            if not quiet and bad <= 40:
                print(line)
    return bad


def build(tmp):
    return hostbuild.build(tmp, SOURCES, name="collisionbody_test")


# -------------------------------------------------------------- mutations
#
# (name, file, old, new). Each replaces the first match, so every pattern is
# spelled to match code and not a comment.


def _m(name, old, new, rel=CBC):
    return (name, rel, old, new)


MUTATIONS = [
    # the static initialiser and the exit-time destructors
    _m("sinit_zero_vector", "    ZeroVector.y = 0.0f;",
       "    ZeroVector.y = 1.0f;"),
    _m("sinit_witness_head", "    CollisionBodyWitnessList.next = WITNESS_END;",
       "    CollisionBodyWitnessList.next = NULL;"),
    _m("sclose_witness_flags",
       "        cbwitness_destroy(w, 3);\n    }\n    while",
       "        cbwitness_destroy(w, 2);\n    }\n    while"),
    _m("sclose_body_flags", "        body_virtual_destroy(b, 3);\n    }\n}",
       "        body_virtual_destroy(b, 2);\n    }\n}"),
    _m("sclose_no_witness_unlink",
       "        wnode(w->Link.prev)->next = w->Link.next;\n"
       "        wnode(w->Link.next)->prev = w->Link.prev;\n"
       "        cbwitness_destroy(w, 3);",
       "        cbwitness_destroy(w, 3);"),
    _m("sclose_no_body_unlink",
       "        body_unlink(b);\n        body_virtual_destroy(b, 3);",
       "        body_virtual_destroy(b, 3);"),

    # NumberAllocator
    _m("na_set_keeps_max",
       "        na->MaxNumbers = 0;\n        if (na->pAllocatedBitField",
       "        if (na->pAllocatedBitField"),
    _m("na_set_no_free", "            bFree(na->pAllocatedBitField);",
       "            ;"),
    _m("na_set_zero_test", "    if (n == 0)\n        return;",
       "    if (n < 0)\n        return;"),
    _m("na_set_bytes_round", "    bytes = n >> 3;", "    bytes = (n + 7) >> 3;"),
    _m("na_set_clear_short",
       "    memset(na->pAllocatedBitField, 0, (size_t)bytes);",
       "    memset(na->pAllocatedBitField, 0, (size_t)bytes / 2);"),
    _m("na_set_lowest", "    na->LowestFreeNumber = 0;\n}",
       "    na->LowestFreeNumber = 1;\n}"),
    _m("na_alloc_ge", "    if (i >= na->MaxNumbers)\n        return -1;",
       "    if (i > na->MaxNumbers)\n        return -1;"),
    _m("na_alloc_returns", "    numberallocator_allocate_number(na, i);\n    return i;",
       "    numberallocator_allocate_number(na, i);\n    return i + 1;"),
    _m("na_allocn_eq", "    if (na->LowestFreeNumber == i) {",
       "    if (na->LowestFreeNumber <= i) {"),
    _m("na_allocn_from_i", "        int32_t j = i + 1;", "        int32_t j = i;"),
    _m("na_allocn_past_top", "        while (j < na->MaxNumbers",
       "        while (j <= na->MaxNumbers"),
    _m("na_allocn_scan_bit", "(1 << (j & 7))) != 0)", "(1 << (j & 7))) == 0)"),
    _m("na_allocn_toggles",
       "    na->pAllocatedBitField[i >> 3] |= (uint8_t)(1 << (i & 7));",
       "    na->pAllocatedBitField[i >> 3] ^= (uint8_t)(1 << (i & 7));"),
    _m("na_free_bit", "&= (uint8_t)~(1 << (i & 7));",
       "&= (uint8_t)~(2 << (i & 7));"),
    _m("na_free_lowest", "    if (i < na->LowestFreeNumber)",
       "    if (i > na->LowestFreeNumber)"),
    _m("na_destroy_flag",
       "    numberallocator_set_max_numbers(na, 0);\n    if (flags & 1)",
       "    numberallocator_set_max_numbers(na, 0);\n    if (flags & 2)"),

    # InitCollisionBody and CloseCollisionBody
    _m("init_car_slots", "(int)sizeof(CarCollisionBody), 14,",
       "(int)sizeof(CarCollisionBody), 13,"),
    _m("init_tpcb_slots", "        (int)sizeof(TrackPolygonCollisionBody), 160,",
       "        (int)sizeof(TrackPolygonCollisionBody), 159,"),
    _m("init_witness_slots", "        (int)sizeof(CollisionBodyWitness), 256,",
       "        (int)sizeof(CollisionBodyWitness), 255,"),
    _m("init_car_pool_mp", "\"CarCollisionBodySlotPool\", 16);",
       "\"CarCollisionBodySlotPool\", 15);"),
    _m("init_pool_order",
       "    CarCollisionBodySlotPool = bNewSlotPool(\n"
       "        (int)sizeof(CarCollisionBody), 14, \"CarCollisionBodySlotPool\", 16);\n"
       "    TrackPolygonCollisionBodySlotPool = bNewSlotPool(\n"
       "        (int)sizeof(TrackPolygonCollisionBody), 160,\n"
       "        \"TrackPolygonCollisionBodySlotPool\", 16);",
       "    TrackPolygonCollisionBodySlotPool = bNewSlotPool(\n"
       "        (int)sizeof(TrackPolygonCollisionBody), 160,\n"
       "        \"TrackPolygonCollisionBodySlotPool\", 16);\n"
       "    CarCollisionBodySlotPool = bNewSlotPool(\n"
       "        (int)sizeof(CarCollisionBody), 14, \"CarCollisionBodySlotPool\", 16);"),
    _m("init_na_flags", "\"CollisionBodyNumberAllocator\", 0, 16);",
       "\"CollisionBodyNumberAllocator\", 1, 16);"),
    # either of these alone is redundant: without MaxNumbers, SetMaxNumbers
    # frees the NULL field; without the field, it never looks at it
    _m("init_na_junk",
       "    na->MaxNumbers = 0;\n    na->pAllocatedBitField = NULL;\n",
       ""),
    _m("init_na_numbers",
       "    numberallocator_set_max_numbers(na, COLLISIONBODY_MAX_BODIES);",
       "    numberallocator_set_max_numbers(na, COLLISIONBODY_MAX_BODIES - 1);"),
    _m("init_table_half", "    memset(pCollisionBodyTable, 0, table);",
       "    memset(pCollisionBodyTable, 0, table / 2);"),
    _m("init_identity", "    bIdentity(&IdentityMatrix);",
       "    memset(&IdentityMatrix, 0, sizeof IdentityMatrix);"),
    _m("init_no_zero_matrix", "    memset(&ZeroMatrix, 0, sizeof ZeroMatrix);",
       "    ;"),
    _m("init_wbits_short",
       "    memset(pWitnessExistanceBitField, 0, COLLISIONBODY_BITFIELD_BYTES);",
       "    memset(pWitnessExistanceBitField, 0, COLLISIONBODY_BITFIELD_BYTES - 1);"),
    _m("init_wbits_slack",
       "    memset(pWitnessExistanceBitField + COLLISIONBODY_BITFIELD_BYTES, 0,\n"
       "           COLLISIONBODY_SHORT_SLACK);",
       "    ;"),
    _m("close_pool_order",
       "    bDeleteSlotPool(TrackPolygonCollisionBodySlotPool);\n"
       "    bDeleteSlotPool(CarCollisionBodySlotPool);",
       "    bDeleteSlotPool(CarCollisionBodySlotPool);\n"
       "    bDeleteSlotPool(TrackPolygonCollisionBodySlotPool);"),
    _m("close_na_flags",
       "        numberallocator_destroy(pCollisionBodyNumberAllocator, 3);",
       "        numberallocator_destroy(pCollisionBodyNumberAllocator, 2);"),
    _m("close_keeps_table", "    bFree(pCollisionBodyTable);\n", "    ;\n"),
    _m("close_keeps_tpcb_pool", "    TrackPolygonCollisionBodySlotPool = NULL;\n",
       "    ;\n"),
    _m("close_keeps_wbits",
       "        bFree(pWitnessExistanceBitField);\n    pWitnessExistanceBitField = NULL;",
       "        bFree(pWitnessExistanceBitField);"),

    # CollisionBody: the constructor
    _m("ctor_vtable", "    b->_vtable = COLLISIONBODY_VTABLE;\n    b->Type = (int8_t)type;",
       "    b->_vtable = STATICCOLLISIONBODY_VTABLE;\n    b->Type = (int8_t)type;"),
    _m("ctor_id_gt", "    if (id >= 0) {", "    if (id > 0) {"),
    _m("ctor_number", "                                        (int16_t)id);",
       "                                        (int16_t)id + 1);"),
    _m("ctor_no_table", "        pCollisionBodyTable[b->ID] = b;\n", "        ;\n"),
    _m("stats_highest", "    if (*highest < *count)", "    if (*highest > *count)"),
    _m("ctor_name", "    b->DebugName[0] = 0;", "    b->DebugName[0] = 1;"),
    _m("ctor_head_prev", "    bnode(head)->prev = b;", "    bnode(head)->prev = head;"),
    _m("ctor_seed", "#define BBOX_SEED              (-9999999.0f)",
       "#define BBOX_SEED              (-9999998.0f)"),
    _m("ctor_bbmax_y", "    b->BBoxMax.y = BBOX_SEED;", "    b->BBoxMax.y = 0.0f;"),
    _m("ctor_caffeine", "    b->pCaffeineObj = NULL;\n    b->BBoxMin.x", "    b->BBoxMin.x"),
    _m("ctor_disabled", "    b->CollisionsDisabled = 0;\n", ""),
    _m("ctor_collisions", "    b->NumCollisions = 0;\n", ""),
    _m("ctor_witnesses", "    b->NumWitnesses = 0;\n", ""),
    _m("ctor_active", "    b->ActiveCollisionDetection = 0;\n", ""),

    # CollisionBody: the destructor
    _m("dtor_vtable",
       "    b->_vtable = COLLISIONBODY_VTABLE;\n    TheCollisionStats.NumCollisionBodies--;",
       "    TheCollisionStats.NumCollisionBodies--;"),
    _m("dtor_stats", "    TheCollisionStats.NumCollisionBodies--;\n", ""),
    _m("dtor_width", "    collisionbody_update_max_width(b, 0.0f);\n", ""),
    _m("dtor_unlink", "    body_unlink(b);\n\n    if (b->NumWitnesses", "\n    if (b->NumWitnesses"),
    _m("dtor_keeps_witnesses", "    if (b->NumWitnesses != 0) {", "    if (0) {"),
    _m("dtor_witness_body1", "            if (w->pBody1 == b || w->pBody2 == b)",
       "            if (w->pBody1 == b)"),
    _m("dtor_witness_flags", "                cbwitness_destroy(w, 3);\n            w = next;",
       "                cbwitness_destroy(w, 2);\n            w = next;"),
    _m("dtor_id_gt", "    if (b->ID >= 0) {", "    if (b->ID > 0) {"),
    _m("dtor_keeps_table", "        pCollisionBodyTable[b->ID] = NULL;\n", ""),
    _m("dtor_keeps_number",
       "        numberallocator_free_number(pCollisionBodyNumberAllocator, b->ID);\n", ""),
    _m("dtor_flags", "    if (flags & 1)\n        bFree(b);", "    if (flags & 2)\n        bFree(b);"),

    # the flip function
    _m("flip_after_le", "    if (b->BBoxMax.x < a->BBoxMax.x)\n        return 1;",
       "    if (b->BBoxMax.x <= a->BBoxMax.x)\n        return 1;"),
    _m("flip_before_le", "    if (a->BBoxMax.x < b->BBoxMax.x)\n        return 0;",
       "    if (a->BBoxMax.x <= b->BBoxMax.x)\n        return 0;"),
    _m("flip_id_le", "    return b->ID < a->ID;", "    return b->ID <= a->ID;"),
    _m("flip_id_swapped", "    return b->ID < a->ID;", "    return a->ID < b->ID;"),

    # UpdateMaxCollisionBodyWidth
    _m("width_cur_y", "    float cur = b->BBoxMax.x - b->BBoxMin.x;",
       "    float cur = b->BBoxMax.y - b->BBoxMin.y;"),
    _m("width_no_same_test", "    if (w == cur)\n        return;\n", ""),
    _m("width_wider_test", "    if (cur < w && MaxCollisionBodyWidthX < w) {",
       "    if (cur < w && MaxCollisionBodyWidthX > w) {"),
    _m("width_wider_any", "    if (cur < w && MaxCollisionBodyWidthX < w) {",
       "    if (MaxCollisionBodyWidthX < w) {"),
    _m("width_was_widest", "!(cur == MaxCollisionBodyWidthX))",
       "!(cur <= MaxCollisionBodyWidthX))"),
    _m("width_counts_self", "        if (o == b)\n            continue;\n", ""),
    _m("width_start", "    widest = 0.0f;", "    widest = -1.0f;"),
    _m("width_widest_gt", "        if (widest < ow)", "        if (widest > ow)"),
    _m("width_other_y", "        ow = o->BBoxMax.x - o->BBoxMin.x;",
       "        ow = o->BBoxMax.x - o->BBoxMin.y;"),

    # SetBBoxMinMax
    _m("box_width_y", "    collisionbody_update_max_width(b, max->x - min->x);",
       "    collisionbody_update_max_width(b, max->y - min->y);"),
    _m("box_min_y", "    y = min->y;\n    x = min->x;", "    y = min->x;\n    x = min->x;"),
    _m("box_no_shortcut", "    if (old == max->x)\n        return;\n", ""),
    _m("box_next_flip",
       "        if (next == BODY_END || !collisionbody_flip_function(b, next))",
       "        if (next == BODY_END || !collisionbody_flip_function(next, b))"),
    _m("box_one_step", "            continue;\n        }\n        if (next == BODY_END",
       "            return;\n        }\n        if (next == BODY_END"),
    _m("box_pp_link", "            bnode(pp)->next = b;", "            bnode(pp)->next = prev;"),
    _m("box_nn_link", "            bnode(nn)->prev = b;", "            bnode(nn)->prev = next;"),

    # the ID, the name, the collisions, the flags
    _m("nextid_max", "    return (uint16_t)pCollisionBodyNumberAllocator->LowestFreeNumber;",
       "    return (uint16_t)pCollisionBodyNumberAllocator->MaxNumbers;"),
    _m("name_size", "    b_strncpy(b->DebugName, name, (int32_t)sizeof b->DebugName);",
       "    b_strncpy(b->DebugName, name, 32);"),
    _m("name_unterminated", "    b->DebugName[sizeof b->DebugName - 1] = 0;\n", ""),
    _m("strncpy_past_nul", "        if (src[i] == 0)\n            break;\n", ""),
    _m("getcoll_le", "    if (!(i < b->NumCollisions))", "    if (!(i <= b->NumCollisions))"),
    _m("getcoll_counts_none", "        if (w->pCollision == NULL)\n            continue;\n", ""),
    _m("getcoll_body1", "        if (w->pBody1 != b && w->pBody2 != b)",
       "        if (w->pBody1 != b)"),
    _m("getcoll_ge", "        if (n == i)\n            return w->pCollision;",
       "        if (n >= i)\n            return w->pCollision;"),
    _m("enable_positive", "    if (b->CollisionsDisabled != 0)",
       "    if (b->CollisionsDisabled > 0)"),
    _m("disable_two", "(int8_t)(b->CollisionsDisabled + 1);",
       "(int8_t)(b->CollisionsDisabled + 2);"),
    _m("blinking", "int32_t collisionbody_is_blinking(CollisionBody *b)\n{\n    (void)b;\n    return 0;",
       "int32_t collisionbody_is_blinking(CollisionBody *b)\n{\n    (void)b;\n    return 1;"),

    # the two bounding-box tests
    _m("bbox_min_x_lt", "    return b->BBoxMin.x <= max->x + margin",
       "    return b->BBoxMin.x < max->x + margin"),
    _m("bbox_max_x_lt", "        && min->x - margin <= b->BBoxMax.x",
       "        && min->x - margin < b->BBoxMax.x"),
    _m("bbox_min_y_lt", "        && b->BBoxMin.y <= max->y + margin",
       "        && b->BBoxMin.y < max->y + margin"),
    _m("bbox_max_y_lt", "        && min->y - margin <= b->BBoxMax.y;",
       "        && min->y - margin < b->BBoxMax.y;"),
    _m("bbox_margin_sign", "    return b->BBoxMin.x <= max->x + margin",
       "    return b->BBoxMin.x <= max->x - margin"),
    _m("bboxb_min_x_lt", "    return b->BBoxMin.x <= other->BBoxMax.x + margin",
       "    return b->BBoxMin.x < other->BBoxMax.x + margin"),
    _m("bboxb_max_y_lt", "        && other->BBoxMin.y - margin <= b->BBoxMax.y;",
       "        && other->BBoxMin.y - margin < b->BBoxMax.y;"),
    _m("bboxb_margin", "        && other->BBoxMin.x - margin <= b->BBoxMax.x",
       "        && other->BBoxMin.x + margin <= b->BBoxMax.x"),

    # StaticCollisionBody
    _m("static_stats", "    stats_up(&TheCollisionStats.NumStaticCollisionBodies,",
       "    stats_up(&TheCollisionStats.NumCollisionBodies,"),
    _m("static_vtable", "    s->Body._vtable = STATICCOLLISIONBODY_VTABLE;\n    s->Body.Dynamic = 0;",
       "    s->Body.Dynamic = 0;"),
    _m("static_dynamic", "    s->Body.Dynamic = 0;\n", ""),
    _m("static_dtor_stats", "    TheCollisionStats.NumStaticCollisionBodies--;\n", ""),
    _m("static_dtor_vtable",
       "    s->Body._vtable = STATICCOLLISIONBODY_VTABLE;\n"
       "    TheCollisionStats.NumStaticCollisionBodies--;",
       "    TheCollisionStats.NumStaticCollisionBodies--;"),
    _m("static_velocity", "    return &ZeroVector;\n}\n\nbMatrix4 *staticcollisionbody_get_rotation",
       "    return (bVector3 *)&ZeroMatrix;\n}\n\nbMatrix4 *staticcollisionbody_get_rotation"),
    _m("static_rotation", "    return &IdentityMatrix;", "    return &ZeroMatrix;"),
    _m("static_backup_time", "    return 1000.0f;", "    return 100.0f;"),
    _m("static_interp_matrix", "    bMatrix4 m = IdentityMatrix;", "    bMatrix4 m = ZeroMatrix;"),
    _m("static_interp_pos", "    *rot = m;\n    *pos = ZeroVector;", "    *rot = m;"),
    _m("static_curvel_w", "    *w = ZeroVector;\n}\n\n// Four", "}\n\n// Four"),
    _m("static_testvel_a", "    *w = ZeroVector;\n}\n\nvoid staticcollisionbody_set_to_physics_mode",
       "    *w = ZeroVector;\n    *a = ZeroVector;\n}\n\n"
       "void staticcollisionbody_set_to_physics_mode"),
    _m("static_consider", "    return 1.0f;", "    return 0.0f;"),
    _m("static_enabled_le", "    return b->CollisionsDisabled == 0;",
       "    return b->CollisionsDisabled <= 0;"),
    _m("static_mass_inverse",
       "staticcollisionbody_get_mass_inverse(CollisionBody *b)\n{\n    (void)b;\n    return 0.0f;",
       "staticcollisionbody_get_mass_inverse(CollisionBody *b)\n{\n    (void)b;\n    return 1.0f;"),
    _m("static_inertia", "    return &ZeroMatrix;", "    return &IdentityMatrix;"),
    _m("static_moveable",
       "staticcollisionbody_is_moveable(CollisionBody *b)\n{\n    (void)b;\n    return 0;",
       "staticcollisionbody_is_moveable(CollisionBody *b)\n{\n    (void)b;\n    return 1;"),
    _m("static_energy", "    (void)impulse;\n    return 0.0f;", "    (void)impulse;\n    return 1.0f;"),
    _m("static_bounciness", "#define STATIC_BOUNCINESS      0.1f",
       "#define STATIC_BOUNCINESS      0.2f"),
    _m("static_friction", "#define STATIC_FRICTION        0.3f",
       "#define STATIC_FRICTION        0.4f"),

    # TrackPolygonCollisionBody
    _m("tp_type", "    staticcollisionbody_init(&t->Static, id, TRACK_POLYGON_COLLISION_BODY);",
       "    staticcollisionbody_init(&t->Static, id, 2);"),
    _m("tp_vtable", "    b->_vtable = TRACKPOLYGONCOLLISIONBODY_VTABLE;\n", ""),
    _m("tp_stats", "    stats_up(&TheCollisionStats.NumTrackPolygonCollisionBodies,",
       "    stats_up(&TheCollisionStats.NumStaticCollisionBodies,"),
    _m("tp_poly", "    b->pPoly = &t->Wafer.Poly;\n", ""),
    _m("tp_name_index", "(char *)TheTopologyTree.pPolygonTable) >> 5));",
       "(char *)TheTopologyTree.pPolygonTable) >> 4));"),
    _m("tp_name_format", "\"TrackPolygon%d\"", "\"TrackPolygon %d\""),
    _m("tp_no_back_pointer", "    tp->pCollisionBody = t;\n", ""),
    _m("tp_box", "&t->pTP->BBoxMin, &t->pTP->BBoxMax);", "&t->pTP->BBoxMin, &t->pTP->BBoxMin);"),
    _m("tp_dtor_vtable", "    t->Static.Body._vtable = TRACKPOLYGONCOLLISIONBODY_VTABLE;\n", ""),
    _m("tp_dtor_back_pointer", "    tp->pCollisionBody = NULL;\n", ""),
    _m("tp_dtor_unassign", "    topotree_unassign(&TheTopologyTree, tp);\n", ""),
    _m("tp_dtor_stats", "    TheCollisionStats.NumTrackPolygonCollisionBodies--;\n", ""),
    _m("tp_dtor_static_flags", "    staticcollisionbody_destroy(&t->Static, 0);",
       "    staticcollisionbody_destroy(&t->Static, 1);"),
    _m("tp_dtor_flags", "    if (flags & 1)\n        trackpolygoncollisionbody_delete(t);",
       "    if (flags & 2)\n        trackpolygoncollisionbody_delete(t);"),
    _m("tp_position", "trackpolygoncollisionbody_get_position(CollisionBody *b)\n"
       "{\n    (void)b;\n    return &ZeroVector;",
       "trackpolygoncollisionbody_get_position(CollisionBody *b)\n"
       "{\n    (void)b;\n    return (bVector3 *)&IdentityMatrix;"),
    _m("tp_terrain_unsigned", "    return (int8_t)((TrackPolygonCollisionBody *)b)->pTP->TheTerrainType;",
       "    return (uint8_t)((TrackPolygonCollisionBody *)b)->pTP->TheTerrainType;"),

    # CollisionBodyWitness
    _m("pair_bit_stride", "    return a->ID * COLLISIONBODY_MAX_BODIES + b->ID;",
       "    return a->ID * (COLLISIONBODY_MAX_BODIES - 1) + b->ID;"),
    _m("pair_bit_swapped", "    return a->ID * COLLISIONBODY_MAX_BODIES + b->ID;",
       "    return b->ID * COLLISIONBODY_MAX_BODIES + a->ID;"),
    _m("wit_stats", "    stats_up(&TheCollisionStats.NumCollisionBodyWitnesses,",
       "    stats_up(&TheCollisionStats.NumCollisions,"),
    _m("wit_tail_next", "    wnode(tail)->next = w;\n", ""),
    _m("wit_prev", "    w->Link.prev = tail;", "    w->Link.prev = WITNESS_END;"),
    _m("wit_collision", "    w->pCollision = NULL;\n\n    k = pair_bit", "\n    k = pair_bit"),
    _m("wit_first_bit",
       "    k = pair_bit(b1, b2);\n    pWitnessExistanceBitField[k >> 3] |= (uint8_t)(1 << (k & 7));\n",
       "    k = pair_bit(b1, b2);\n"),
    _m("wit_second_order", "    k = pair_bit(w->pBody2, w->pBody1);\n    pWitnessExistanceBitField[k >> 3] |=",
       "    k = pair_bit(w->pBody1, w->pBody2);\n    pWitnessExistanceBitField[k >> 3] |="),
    _m("wit_witnesses", "(int8_t)(w->pBody1->NumWitnesses + 1);",
       "(int8_t)(w->pBody1->NumWitnesses + 2);"),
    _m("wdel_stats", "    TheCollisionStats.NumCollisionBodyWitnesses--;\n", ""),
    _m("wdel_no_end", "    if (w->pCollision != NULL)\n        cbwitness_end_collision(w);\n", ""),
    _m("wdel_no_unlink",
       "    wnode(w->Link.prev)->next = w->Link.next;\n"
       "    wnode(w->Link.next)->prev = w->Link.prev;\n"
       "    w->pBody1->NumWitnesses",
       "    wnode(w->Link.next)->prev = w->Link.prev;\n"
       "    w->pBody1->NumWitnesses"),
    _m("wdel_witnesses", "    w->pBody1->NumWitnesses = (int8_t)(w->pBody1->NumWitnesses - 1);\n", ""),
    _m("wdel_first_bit",
       "    k = pair_bit(w->pBody1, w->pBody2);\n"
       "    pWitnessExistanceBitField[k >> 3] &= (uint8_t)~(1 << (k & 7));\n",
       "    k = pair_bit(w->pBody1, w->pBody2);\n"),
    _m("wdel_ends_swapped",
       "    maybe_destroy_track_body(&w->pBody1);\n    maybe_destroy_track_body(&w->pBody2);",
       "    maybe_destroy_track_body(&w->pBody2);\n    maybe_destroy_track_body(&w->pBody1);"),
    _m("maybe_any_type",
       "    if (b->Type != TRACK_POLYGON_COLLISION_BODY || b->NumWitnesses != 0)",
       "    if (b->NumWitnesses != 0)"),
    _m("maybe_flags", "        body_virtual_destroy(b, 3);\n    *end = NULL;",
       "        body_virtual_destroy(b, 2);\n    *end = NULL;"),
    _m("maybe_keeps_end", "    *end = NULL;\n", ""),
    _m("wdel_flags", "    if (flags & 1)\n        cbwitness_delete(w);",
       "    if (flags & 2)\n        cbwitness_delete(w);"),
    _m("end_flags", "        gCollisionDestroyFn(w->pCollision, 3);",
       "        gCollisionDestroyFn(w->pCollision, 2);"),
    _m("end_keeps_collision", "    w->pCollision = NULL;\n    TheCollisionStats.NumCollisions--;",
       "    TheCollisionStats.NumCollisions--;"),
    _m("end_stats", "    TheCollisionStats.NumCollisions--;\n", ""),
    _m("end_body2", "    w->pBody2->NumCollisions = (int8_t)(w->pBody2->NumCollisions - 1);\n", ""),
    _m("expired_collision", "    if (w->pCollision != NULL)\n        return 0;\n", ""),
    _m("expired_x_lt", "&& b2->BBoxMin.x <= b1->BBoxMax.x", "&& b2->BBoxMin.x < b1->BBoxMax.x"),
    _m("expired_x_lt2", "    if (!(b1->BBoxMin.x <= b2->BBoxMax.x", "    if (!(b1->BBoxMin.x < b2->BBoxMax.x"),
    _m("expired_y_lt", "          && b1->BBoxMin.y <= b2->BBoxMax.y",
       "          && b1->BBoxMin.y < b2->BBoxMax.y"),
    _m("expired_y_lt2", "          && b2->BBoxMin.y <= b1->BBoxMax.y))",
       "          && b2->BBoxMin.y < b1->BBoxMax.y))"),
    _m("expired_active_or", "    if (b1->ActiveCollisionDetection == 0\n        &&",
       "    if (b1->ActiveCollisionDetection == 0\n        ||"),
    _m("expired_no_enabled1", "    if (!are_collisions_enabled(b1))\n        return 1;\n", ""),
    _m("expired_enabled2_b1", "    if (!are_collisions_enabled(w->pBody2))",
       "    if (!are_collisions_enabled(b1))"),
    _m("yaw_negative", "    if (b->Type < 0)\n        return 0;\n", ""),
    _m("yaw_le", "    if (b->Type < TRACK_POLYGON_COLLISION_BODY)\n        return 1;",
       "    if (b->Type <= TRACK_POLYGON_COLLISION_BODY)\n        return 1;"),
    _m("yaw_bit", "& TRACKPOLY_VERTICAL) != 0;", "& TRACKPOLY_UPSIDE_DOWN) != 0;"),
    _m("yaw_others", "    return 0;\n}\n\nvoid cbwitness_eliminate_all",
       "    return 1;\n}\n\nvoid cbwitness_eliminate_all"),
    _m("elim_flags", "            cbwitness_destroy(w, 3);\n}", "            cbwitness_destroy(w, 2);\n}"),

    # the tables
    _m("vt_base_blinking", "    E(collisionbody_is_blinking),                   // 184",
       "    PURE,                                           // 184"),
    _m("vt_static_terrain", "    STATIC_SLOTS(staticcollisionbody_destroy, PURE, PURE)",
       "    STATIC_SLOTS(staticcollisionbody_destroy, PURE,\n"
       "                 E(trackpolygoncollisionbody_get_terrain_type))"),
    _m("vt_friction_bounciness",
       "    E(staticcollisionbody_get_bounciness),                          \\\n"
       "    E(staticcollisionbody_get_friction)",
       "    E(staticcollisionbody_get_friction),                            \\\n"
       "    E(staticcollisionbody_get_bounciness)"),
    _m("vt_install_static", "    vt_install(STATICCOLLISIONBODY_VTABLE, staticcollisionbody_vt,",
       "    vt_install(STATICCOLLISIONBODY_VTABLE, trackpolygoncollisionbody_vt,"),

    # the header's accessors
    _m("get_id_unsigned", "    return b->ID;\n", "    return (uint16_t)b->ID;\n", CBH),
    _m("get_num_collisions", "    return b->NumCollisions;\n", "    return b->NumWitnesses;\n",
       CBH),
    _m("is_dynamic", "    return b->Dynamic;\n", "    return b->Type;\n", CBH),
    _m("active_detection", "    return b->ActiveCollisionDetection;\n",
       "    return b->CollisionsDisabled;\n", CBH),

    # DynamicCollisionBody: the box test the image inlines
    _m("dyn_box_x_lt", "    return b->BBoxMin.x <= max->x && min->x <= b->BBoxMax.x",
       "    return b->BBoxMin.x < max->x && min->x <= b->BBoxMax.x"),
    _m("dyn_box_x_lt2", " && min->x <= b->BBoxMax.x\n        && b->BBoxMin.y",
       " && min->x < b->BBoxMax.x\n        && b->BBoxMin.y"),
    _m("dyn_box_y_lt", "        && b->BBoxMin.y <= max->y && min->y <= b->BBoxMax.y;",
       "        && b->BBoxMin.y < max->y && min->y <= b->BBoxMax.y;"),
    _m("dyn_box_y_lt2", " && min->y <= b->BBoxMax.y;", " && min->y < b->BBoxMax.y;"),
    _m("dyn_box_no_y",
       "\n        && b->BBoxMin.y <= max->y && min->y <= b->BBoxMax.y;", ";"),

    # the constructor and destructor
    _m("dyn_init_stats",
       "    stats_up(&TheCollisionStats.NumDynamicCollisionBodies,\n"
       "             &TheCollisionStats.HighestNumDynamicCollisionBodies);\n", ""),
    _m("dyn_init_vtable", "    d->Body._vtable = DYNAMICCOLLISIONBODY_VTABLE;\n    d->pTC = tc;",
       "    d->pTC = tc;"),
    _m("dyn_init_tc", "    d->pTC = tc;", "    d->pTC = NULL;"),
    _m("dyn_init_dynamic", "    d->Body.Dynamic = 1;", "    d->Body.Dynamic = 0;"),
    _m("dyn_init_system", "    d->pSystem = NULL;\n    d->pBody = NULL;", "    d->pBody = NULL;"),
    _m("dyn_init_body", "    d->pBody = NULL;\n    d->PhysicsMode = 0;", "    d->PhysicsMode = 0;"),
    _m("dyn_init_mode", "    d->PhysicsMode = 0;\n    return d;", "    return d;"),
    _m("dyn_dtor_vtable",
       "    d->Body._vtable = DYNAMICCOLLISIONBODY_VTABLE;\n"
       "    TheCollisionStats.NumDynamicCollisionBodies--;",
       "    TheCollisionStats.NumDynamicCollisionBodies--;"),
    _m("dyn_dtor_stats", "    TheCollisionStats.NumDynamicCollisionBodies--;\n", ""),
    _m("dyn_dtor_flags", "    collisionbody_destroy(&d->Body, flags);",
       "    collisionbody_destroy(&d->Body, flags & 2);"),

    # BuildBoundingVolumes
    _m("dyn_bv_margin", "#define CYLINDER_MARGIN        0.05f", "#define CYLINDER_MARGIN        0.5f"),
    _m("dyn_bv_last_vertex", "    for (i = 0; i < n; i++, v++) {\n        float x = v->CompressedPosition[0];",
       "    for (i = 0; i < n - 1; i++, v++) {\n        float x = v->CompressedPosition[0];"),
    _m("dyn_bv_r2_has_z", "        float r2 = sqrtf(xy);", "        float r2 = sqrtf(xy + z * z);"),
    _m("dyn_bv_r3_no_z", "        float r3 = sqrtf(xy + z * z);", "        float r3 = sqrtf(xy);"),
    _m("dyn_bv_radius_gt", "        if (radius < r3)", "        if (r3 < radius)"),
    _m("dyn_bv_cylinder_r3", "        if (cylinder < r2)\n            cylinder = r2;",
       "        if (cylinder < r3)\n            cylinder = r3;"),
    _m("dyn_bv_top_y", "        if (top < z)\n            top = z;", "        if (top < y)\n            top = y;"),
    _m("dyn_bv_base_y", "        else if (z < base)\n            base = z;",
       "        else if (y < base)\n            base = y;"),
    _m("dyn_bv_hix_y", "        if (hix < x)\n            hix = x;", "        if (hix < y)\n            hix = y;"),
    _m("dyn_bv_lox_y", "        else if (x < lox)\n            lox = x;",
       "        else if (x < lox)\n            lox = y;"),
    _m("dyn_bv_hiy_x", "        if (hiy < y)\n            hiy = y;", "        if (hiy < x)\n            hiy = x;"),
    _m("dyn_bv_loy_z", "        else if (y < loy)\n            loy = y;",
       "        else if (z < loy)\n            loy = z;"),
    _m("dyn_bv_hiz_y", "        if (hiz < z)\n            hiz = z;", "        if (hiz < y)\n            hiz = y;"),
    _m("dyn_bv_loz_x", "        else if (z < loz)\n            loz = z;",
       "        else if (x < loz)\n            loz = x;"),
    _m("dyn_bv_base_sign", "    d->CylinderBaseHeight = CYLINDER_MARGIN - base;",
       "    d->CylinderBaseHeight = base + CYLINDER_MARGIN;"),
    _m("dyn_bv_top_margin", "    d->CylinderTopHeight = top + CYLINDER_MARGIN;",
       "    d->CylinderTopHeight = top;"),
    _m("dyn_bv_cylinder_radius", "    d->CylinderRadius = cylinder + CYLINDER_MARGIN;",
       "    d->CylinderRadius = radius + CYLINDER_MARGIN;"),
    _m("dyn_bv_sphere_cylinder", "    d->Radius = radius;", "    d->Radius = cylinder;"),
    _m("dyn_bv_min_x", "    d->LocalBBMin.x = lox;", "    d->LocalBBMin.x = loy;"),
    _m("dyn_bv_min_z", "    d->LocalBBMin.z = loz;", "    d->LocalBBMin.z = 0.0f;"),
    _m("dyn_bv_max_y", "    d->LocalBBMax.y = hiy;", "    d->LocalBBMax.y = hix;"),
    _m("dyn_bv_max_z", "    d->LocalBBMax.z = hiz;", "    d->LocalBBMax.z = hiy;"),

    # UpdatePosition
    _m("dyn_up_radius", "    float r = d->CylinderRadius;\n    bVector2 min, max;",
       "    float r = d->Radius;\n    bVector2 min, max;"),
    _m("dyn_up_min_x", "    min.x = p->x - r;", "    min.x = p->x + r;"),
    _m("dyn_up_min_y", "    min.y = p->y - r;", "    min.y = p->x - r;"),
    _m("dyn_up_max_y", "    max.y = p->y + r;", "    max.y = p->y - r;"),
    _m("dyn_up_max_x", "    max.x = p->x + r;", "    max.x = p->y + r;"),

    # BeginMove
    _m("dyn_begin_rotation", "    d->BackupRotation = m;\n", ""),
    _m("dyn_begin_position", "    d->BackupPosition = *body_get_position(&d->Body);",
       "    d->BackupPosition = *body_get_velocity(&d->Body);"),
    _m("dyn_begin_velocity", "    d->BackupVelocity = *body_get_velocity(&d->Body);\n", ""),
    _m("dyn_begin_order",
       "    d->BackupPosition = *body_get_position(&d->Body);\n"
       "    d->BackupVelocity = *body_get_velocity(&d->Body);",
       "    d->BackupVelocity = *body_get_velocity(&d->Body);\n"
       "    d->BackupPosition = *body_get_position(&d->Body);"),
    _m("dyn_begin_time", "    d->BackupTime = t;", "    d->BackupTime = 0.5f;"),

    # the interpolations
    _m("dyn_min_backup", "#define MIN_BACKUP_TIME        1e-6f", "#define MIN_BACKUP_TIME        1e-5f"),
    _m("dyn_interp_le", "    if (d->BackupTime < MIN_BACKUP_TIME) {\n        bMatrix4 m;",
       "    if (d->BackupTime <= MIN_BACKUP_TIME) {\n        bMatrix4 m;"),
    _m("dyn_interp_keep_pos", "        *pos = *p;", "        *pos = d->BackupPosition;"),
    _m("dyn_interp_keep_rot", "        m = *r;", "        m = d->BackupRotation;"),
    _m("dyn_interp_dp_reversed", "    lanes_sub(dp, p, &d->BackupPosition);",
       "    lanes_sub(dp, &d->BackupPosition, p);"),
    _m("dyn_interp_d3_row2", "    lanes_sub(d3, &r->v3, &d->BackupRotation.v3);",
       "    lanes_sub(d3, &r->v2, &d->BackupRotation.v3);"),
    _m("dyn_interp_f", "    f = (d->BackupTime - t) / d->BackupTime;\n    lanes_blend(pos",
       "    f = t / d->BackupTime;\n    lanes_blend(pos"),
    _m("dyn_interp_pos_back", "    lanes_blend(pos, dp, f, &d->BackupPosition);",
       "    lanes_blend(pos, dp, f, p);"),
    _m("dyn_interp_v2_d1", "    lanes_blend(&rot->v2, d2, f, &d->BackupRotation.v2);",
       "    lanes_blend(&rot->v2, d1, f, &d->BackupRotation.v2);"),
    _m("dyn_interp_v0_back", "    lanes_blend(&rot->v0, d0, f, &d->BackupRotation.v0);",
       "    lanes_blend(&rot->v0, d0, f, &d->BackupRotation.v1);"),
    _m("dyn_lanes_blend_add", "        r[i] = d[i] * f + b[i];", "        r[i] = d[i] * f - b[i];"),
    _m("dyn_lanes_blend_pad", "    memcpy(out, r, sizeof r);", "    memcpy(out, r, 3 * sizeof r[0]);"),
    _m("dyn_lanes_sub", "        d[i] = a[i] - b[i];", "        d[i] = b[i] - a[i];"),
    _m("dyn_interpv_le", "    if (d->BackupTime < MIN_BACKUP_TIME) {\n        *out",
       "    if (d->BackupTime <= MIN_BACKUP_TIME) {\n        *out"),
    _m("dyn_interpv_keep", "        *out = *body_get_velocity(&d->Body);",
       "        *out = d->BackupVelocity;"),
    _m("dyn_interpv_f", "    f = (d->BackupTime - t) / d->BackupTime;\n    v = body_get_velocity",
       "    f = (d->BackupTime + t) / d->BackupTime;\n    v = body_get_velocity"),
    _m("dyn_interpv_back", "    lanes_blend(out, dv, f, &d->BackupVelocity);",
       "    lanes_blend(out, dv, f, v);"),

    # Backup and the pass-throughs
    _m("dyn_backup_direct", "    ((VtInterpolateFn)e->fn)(vt_this(b, e), &pos, &rot, t);",
       "    dynamiccollisionbody_interpolate(b, &pos, &rot, t);"),
    _m("dyn_backup_vel_time", "    dynamiccollisionbody_interpolate_velocity(d, &vel, t);",
       "    dynamiccollisionbody_interpolate_velocity(d, &vel, 0.0f);"),
    _m("dyn_backup_mass_inv", "    m = rb->Mass;", "    m = rb->Mass_inv;"),
    _m("dyn_backup_y", "    vel.y = vel.y * m;\n", ""),
    _m("dyn_backup_pad", "    vel.pad = vel.pad * m;\n", ""),
    _m("dyn_backup_x_vel", "    memcpy(&rb->State.X, &pos, sizeof rb->State.X);",
       "    memcpy(&rb->State.X, &vel, sizeof rb->State.X);"),
    _m("dyn_backup_no_r", "    memcpy(&rb->State.R, &rot, sizeof rb->State.R);\n", ""),
    _m("dyn_backup_p_pos", "    memcpy(&rb->State.P, &vel, sizeof rb->State.P);",
       "    memcpy(&rb->State.P, &pos, sizeof rb->State.P);"),
    _m("dyn_aux_this", "    ((PhysicsVoidFn)e->fn)(vt_this(s, e));", "    ((PhysicsVoidFn)e->fn)(s);"),
    _m("dyn_curvel_v", "    memcpy(v, &rb->Velocity, sizeof *v);",
       "    memcpy(v, &rb->AngularVelocity, sizeof *v);"),
    _m("dyn_curvel_w", "    memcpy(w, &rb->AngularVelocity, sizeof *w);",
       "    memcpy(w, &rb->Velocity, sizeof *w);"),
    _m("dyn_testvel_vw", "(bVector4 *)v, (bVector4 *)w,", "(bVector4 *)w, (bVector4 *)v,"),
    _m("dyn_testvel_j_at",
       "                           (const bVector4 *)j, (const bVector4 *)at);\n}\n\nvoid "
       "dynamiccollisionbody_get_local",
       "                           (const bVector4 *)at, (const bVector4 *)j);\n}\n\nvoid "
       "dynamiccollisionbody_get_local"),

    # GetLocalCollisionBodies
    _m("dyn_local_lo_plus", "    float lo = b->BBoxMin.x - margin;", "    float lo = b->BBoxMin.x + margin;"),
    _m("dyn_local_lo_lt", " && lo <= (*first)->BBoxMax.x)", " && lo < (*first)->BBoxMax.x)"),
    _m("dyn_local_first_min", " && lo <= (*first)->BBoxMax.x)", " && lo <= (*first)->BBoxMin.x)"),
    _m("dyn_local_hi_minus", "    hi = b->BBoxMax.x + margin;", "    hi = b->BBoxMax.x - margin;"),
    _m("dyn_local_hi_lt", " && (*last)->BBoxMin.x <= hi)", " && (*last)->BBoxMin.x < hi)"),
    _m("dyn_local_last_max", " && (*last)->BBoxMin.x <= hi)", " && (*last)->BBoxMax.x <= hi)"),

    # MaybeCreateWitnesses
    _m("dyn_mcw_disabled",
       "    if (!are_collisions_enabled(b))\n        return;\n"
       "    dynamiccollisionbody_create_track_polygon_collision_bodies(d);",
       "    dynamiccollisionbody_create_track_polygon_collision_bodies(d);"),
    _m("dyn_mcw_no_tp", "        return;\n    dynamiccollisionbody_create_track_polygon_collision_bodies(d);\n",
       "        return;\n"),
    _m("dyn_mcw_lo_lt", "    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMax.x)",
       "    while (lo != BODY_END && b->BBoxMin.x < lo->BBoxMax.x)"),
    _m("dyn_mcw_lo_min", "    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMax.x)",
       "    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMin.x)"),
    _m("dyn_mcw_reach_first",
       "    dynamiccollisionbody_create_track_polygon_collision_bodies(d);\n\n"
       "    // Back to the first body that ends before this one starts; then on to\n"
       "    // the first that ends past this one's end by more than the widest body\n"
       "    // is wide, which is read after the track polygons' bodies are made.\n"
       "    lo = b->Link.prev;\n"
       "    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMax.x)\n"
       "        lo = lo->Link.prev;\n"
       "    reach = b->BBoxMax.x + MaxCollisionBodyWidthX;\n",
       "    reach = b->BBoxMax.x + MaxCollisionBodyWidthX;\n"
       "    dynamiccollisionbody_create_track_polygon_collision_bodies(d);\n"
       "    lo = b->Link.prev;\n"
       "    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMax.x)\n"
       "        lo = lo->Link.prev;\n"),
    _m("dyn_mcw_reach_no_width", "    reach = b->BBoxMax.x + MaxCollisionBodyWidthX;",
       "    reach = b->BBoxMax.x;"),
    _m("dyn_mcw_end_lt", "    while (end != BODY_END && end->BBoxMax.x <= reach)",
       "    while (end != BODY_END && end->BBoxMax.x < reach)"),
    _m("dyn_mcw_end_min", "    while (end != BODY_END && end->BBoxMax.x <= reach)",
       "    while (end != BODY_END && end->BBoxMin.x <= reach)"),
    _m("dyn_mcw_from_b", "    for (o = lo->Link.next; o != end; o = next) {",
       "    for (o = b->Link.next; o != end; o = next) {"),
    _m("dyn_mcw_self", "        if (o == b || !box_touches(b, &o->BBoxMin, &o->BBoxMax))",
       "        if (!box_touches(b, &o->BBoxMin, &o->BBoxMax))"),
    _m("dyn_mcw_no_box", "        if (o == b || !box_touches(b, &o->BBoxMin, &o->BBoxMax))",
       "        if (o == b)"),
    _m("dyn_mcw_exists", "        if (cbwitness_does_witness_exist(b, o))\n            continue;\n", ""),
    _m("dyn_mcw_other_enabled", "        if (!are_collisions_enabled(o))\n            continue;\n", ""),
    _m("dyn_mcw_smoke_ne", "        if (o->Type == VIRGIN_SMOKEABLE_COLLISION_BODY)",
       "        if (o->Type != VIRGIN_SMOKEABLE_COLLISION_BODY)"),
    _m("dyn_mcw_smoke_null", "        if (other == NULL\n            ||", "        if (0\n            ||"),
    _m("dyn_mcw_smoke_box", "            || !box_touches(b, &other->BBoxMin, &other->BBoxMax))",
       "            || !box_touches(b, &o->BBoxMin, &o->BBoxMax))"),
    _m("dyn_mcw_witness_o", "        cbwitness_init(witness_new(), b, other);",
       "        cbwitness_init(witness_new(), b, o);"),
    _m("dyn_mcw_witness_order", "        cbwitness_init(witness_new(), b, other);",
       "        cbwitness_init(witness_new(), other, b);"),

    # CreateTrackPolygonCollisionBodies
    _m("dyn_ctp_taken", "        if (tp->pCollisionBody != NULL)\n            continue;\n", ""),
    _m("dyn_ctp_no_box", "        if (!box_touches(b, &tp->BBoxMin, &tp->BBoxMax))\n            continue;\n", ""),
    _m("dyn_ctp_no_check", "        if (!dynamiccollisionbody_track_polygon_check(d, tp))\n            continue;\n",
       ""),
    _m("dyn_ctp_cap", "#define DYN_MAX_TRACK_POLYGONS 48", "#define DYN_MAX_TRACK_POLYGONS 47"),
    _m("dyn_ctp_none", "    if (n == 0)\n        return 0;\n", ""),
    _m("dyn_ctp_sort_down", "            if (near[i + 1]->pPolygon < near[i]->pPolygon) {",
       "            if (near[i]->pPolygon < near[i + 1]->pPolygon) {"),
    _m("dyn_ctp_sort_one_pass", "    } while (swaps != 0);", "    } while (0);"),
    _m("dyn_ctp_sort_short", "        for (i = 0; i < n - 1; i++) {", "        for (i = 0; i < n - 2; i++) {"),
    _m("dyn_ctp_full_n", "        if (bIsSlotPoolFull(TrackPolygonCollisionBodySlotPool))\n            return i;",
       "        if (bIsSlotPoolFull(TrackPolygonCollisionBodySlotPool))\n            return n;"),
    _m("dyn_ctp_first_poly", "        p = near[i]->pPolygon;", "        p = near[0]->pPolygon;"),
    _m("dyn_ctp_id", "        id = collisionbody_get_next_id();", "        id = -1;"),
    _m("dyn_ctp_return", "    return n;\n}\n\n// The two heights", "    return 0;\n}\n\n// The two heights"),

    # TrackPolygonCheck
    _m("dyn_tpc_top", "    float h = d->CylinderBaseHeight;", "    float h = d->CylinderTopHeight;"),
    _m("dyn_tpc_sphere", "    float h = d->CylinderBaseHeight;\n    float r = d->CylinderRadius;",
       "    float h = d->CylinderBaseHeight;\n    float r = d->Radius;"),
    _m("dyn_tpc_row1", "(rot->v2.x * n->x + rot->v2.y * n->y) + rot->v2.z * n->z",
       "(rot->v1.x * n->x + rot->v1.y * n->y) + rot->v1.z * n->z"),
    _m("dyn_tpc_up_assoc", "(rot->v2.x * n->x + rot->v2.y * n->y) + rot->v2.z * n->z",
       "rot->v2.x * n->x + (rot->v2.y * n->y + rot->v2.z * n->z)"),
    _m("dyn_tpc_sqrtf", "    float s = ee_sqrt(1.0f - up * up);", "    float s = sqrtf(1.0f - up * up);"),
    _m("dyn_tpc_dist_assoc", "((p->x * n->x + p->y * n->y) + p->z * n->z)",
       "(p->x * n->x + (p->y * n->y + p->z * n->z))"),
    _m("dyn_tpc_plane_plus", "                 - tp->PlaneDistance;", "                 + tp->PlaneDistance;"),
    _m("dyn_tpc_top_gt", "    if (up * dist < 0.0f)", "    if (up * dist > 0.0f)"),
    _m("dyn_tpc_le", "    return fabsf(dist) < fabsf(up) * h + s * r;",
       "    return fabsf(dist) <= fabsf(up) * h + s * r;"),
    _m("dyn_tpc_signed_up", "    return fabsf(dist) < fabsf(up) * h + s * r;",
       "    return fabsf(dist) < up * h + s * r;"),
    _m("dyn_tpc_signed_dist", "    return fabsf(dist) < fabsf(up) * h + s * r;",
       "    return dist < fabsf(up) * h + s * r;"),
    _m("dyn_tpc_no_s", "    return fabsf(dist) < fabsf(up) * h + s * r;",
       "    return fabsf(dist) < fabsf(up) * h + r;"),
    _m("dyn_tpc_order",
       "    bMatrix4 *rot = body_get_rotation(b);\n"
       "    float up = (rot->v2.x * n->x + rot->v2.y * n->y) + rot->v2.z * n->z;\n"
       "    float s = ee_sqrt(1.0f - up * up);\n"
       "    bVector3 *p = body_get_position(b);\n",
       "    bVector3 *p = body_get_position(b);\n"
       "    bMatrix4 *rot = body_get_rotation(b);\n"
       "    float up = (rot->v2.x * n->x + rot->v2.y * n->y) + rot->v2.z * n->z;\n"
       "    float s = ee_sqrt(1.0f - up * up);\n"),

    # ChangeInEnergy and the inline methods
    _m("dyn_energy_sign", "    return after - rigidbody_get_energy(d->pBody);",
       "    return rigidbody_get_energy(d->pBody) - after;"),
    _m("dyn_energy_j_at", "        d->pBody, (const bVector4 *)j, (const bVector4 *)at);",
       "        d->pBody, (const bVector4 *)at, (const bVector4 *)j);"),
    _m("dyn_bbox_min", "    *min = d->LocalBBMin;", "    *min = d->LocalBBMax;"),
    _m("dyn_bbox_max", "    *max = d->LocalBBMax;", "    *max = d->LocalBBMin;"),
    _m("dyn_apply_j_at",
       "    rigidbody_apply_impulse(((DynamicCollisionBody *)b)->pBody,\n"
       "                            (const bVector4 *)j, (const bVector4 *)at);",
       "    rigidbody_apply_impulse(((DynamicCollisionBody *)b)->pBody,\n"
       "                            (const bVector4 *)at, (const bVector4 *)j);"),
    _m("dyn_tensor_is_rotation", "->pBody)->I_body_inv;", "->pBody)->State.R;"),
    _m("dyn_mass_inv_is_mass", "->pBody)->Mass_inv;", "->pBody)->Mass;"),
    _m("dyn_max_backup_zero", "    return ((DynamicCollisionBody *)b)->BackupTime;", "    return 0.0f;"),
    _m("dyn_set_position_none", "    bVector3 *to = body_get_position(b);\n\n    *to = *p;",
       "    bVector3 *to = body_get_position(b);\n\n    (void)to;"),

    # DynamicCollisionBody's table
    _m("dyn_vt_dtor", "    E(dynamiccollisionbody_destroy),", "    E(collisionbody_destroy),"),
    _m("dyn_vt_backup_interp",
       "    E(dynamiccollisionbody_backup),\n    E(dynamiccollisionbody_interpolate),",
       "    E(dynamiccollisionbody_interpolate),\n    E(dynamiccollisionbody_backup),"),
    _m("dyn_vt_velocities",
       "    E(dynamiccollisionbody_get_current_velocities),\n"
       "    E(dynamiccollisionbody_get_test_impulse_velocities),",
       "    E(dynamiccollisionbody_get_test_impulse_velocities),\n"
       "    E(dynamiccollisionbody_get_current_velocities),"),
    _m("dyn_vt_mass_tensor",
       "    E(dynamiccollisionbody_get_mass_inverse),\n"
       "    E(dynamiccollisionbody_get_inertia_tensor_inverse),",
       "    E(dynamiccollisionbody_get_inertia_tensor_inverse),\n"
       "    E(dynamiccollisionbody_get_mass_inverse),"),
    _m("dyn_vt_position_backup_time",
       "    E(dynamiccollisionbody_set_position),\n"
       "    E(dynamiccollisionbody_get_max_backup_time),",
       "    E(dynamiccollisionbody_get_max_backup_time),\n"
       "    E(dynamiccollisionbody_set_position),"),
    _m("dyn_vt_blinking",
       "    E(dynamiccollisionbody_change_in_energy),\n    E(collisionbody_is_blinking),",
       "    E(dynamiccollisionbody_change_in_energy),\n    PURE,"),
    _m("dyn_vt_apply_impulse", "    E(dynamiccollisionbody_apply_impulse),\n    PURE, PURE,",
       "    PURE,\n    PURE, PURE,"),
    _m("dyn_install", "    vt_install(DYNAMICCOLLISIONBODY_VTABLE, dynamiccollisionbody_vt,",
       "    vt_install(DYNAMICCOLLISIONBODY_VTABLE, staticcollisionbody_vt,"),

    # its layout
    _m("dyn_system_body_swapped",
       "    void     *pSystem;                          //  92  a PhysicsSystem\n"
       "    void     *pBody;                            //  96  a RigidBody",
       "    void     *pBody;                            //  96  a RigidBody\n"
       "    void     *pSystem;                          //  92  a PhysicsSystem", CBH),
    _m("dyn_no_quadword_pad", "    uint8_t   _pad104[8];                       // 104  the quadword round-up\n",
       "", CBH),

    # ---- CarCollisionBody (carcollisionbody.c, and its inlines in the header)

    # the table and its install
    _m("ccb_vt_destroy", "    E(carcollisionbody_destroy),",
       "    E(dynamiccollisionbody_destroy),", CCB),
    _m("ccb_vt_position", "    E(carcollisionbody_get_position),",
       "    E(carcollisionbody_get_velocity),", CCB),
    _m("ccb_vt_velocity", "    E(carcollisionbody_get_velocity),\n    E(carcollisionbody_get_rotation),",
       "    E(carcollisionbody_get_position),\n    E(carcollisionbody_get_rotation),", CCB),
    _m("ccb_vt_rotation", "    E(carcollisionbody_get_rotation),",
       "    E(staticcollisionbody_get_rotation),", CCB),
    _m("ccb_vt_move", "    E(carcollisionbody_move),",
       "    E(staticcollisionbody_move),", CCB),
    _m("ccb_vt_physics_mode", "    E(carcollisionbody_set_to_physics_mode),",
       "    E(dynamiccollisionbody_set_to_physics_mode),", CCB),
    _m("ccb_vt_consider", "    E(carcollisionbody_consider_impulse),",
       "    E(staticcollisionbody_consider_impulse),", CCB),
    _m("ccb_vt_apply", "    E(carcollisionbody_apply_impulse),",
       "    E(dynamiccollisionbody_apply_impulse),", CCB),
    _m("ccb_vt_enabled", "    E(carcollisionbody_are_collisions_enabled),",
       "    E(staticcollisionbody_are_collisions_enabled),", CCB),
    _m("ccb_vt_terrain", "    E(carcollisionbody_get_terrain_type),",
       "    PURE,", CCB),
    _m("ccb_vt_mass_inverse", "    E(carcollisionbody_get_mass_inverse),",
       "    E(dynamiccollisionbody_get_mass_inverse),", CCB),
    _m("ccb_vt_inertia", "    E(carcollisionbody_get_inertia_tensor_inverse),",
       "    E(dynamiccollisionbody_get_inertia_tensor_inverse),", CCB),
    _m("ccb_vt_moveable", "    E(carcollisionbody_is_moveable),",
       "    E(staticcollisionbody_is_moveable),", CCB),
    _m("ccb_vt_blinking", "    E(carcollisionbody_is_blinking),",
       "    E(collisionbody_is_blinking),", CCB),
    _m("ccb_vt_bounce_friction",
       "    E(carcollisionbody_get_bounciness),\n    E(carcollisionbody_get_friction),",
       "    E(carcollisionbody_get_friction),\n    E(carcollisionbody_get_bounciness),", CCB),
    _m("ccb_vt_inherited",
       "    E(dynamiccollisionbody_set_position),\n    E(dynamiccollisionbody_get_max_backup_time),",
       "    E(staticcollisionbody_set_position),\n    E(dynamiccollisionbody_get_max_backup_time),", CCB),
    _m("ccb_install", "    vt_install(CARCOLLISIONBODY_VTABLE, carcollisionbody_vt,\n"
       "               COLLISIONBODY_VT_ENTRIES);",
       "    vt_install(CARCOLLISIONBODY_VTABLE, carcollisionbody_vt,\n"
       "               COLLISIONBODY_VT_ENTRIES - 1);", CCB),

    # the constants
    _m("ccb_mass_max", "#define CAR_MASS_INVERSE_MAX 0.769230783f",
       "#define CAR_MASS_INVERSE_MAX 0.76923084f", CCB),
    _m("ccb_inertia_scale", "#define CAR_INERTIA_SCALE    0.4f",
       "#define CAR_INERTIA_SCALE    0.41f", CCB),
    _m("ccb_damage_scale", "#define CAR_DAMAGE_SCALE     0.03f",
       "#define CAR_DAMAGE_SCALE     0.031f", CCB),
    _m("ccb_friction", "#define CAR_FRICTION         0.3f",
       "#define CAR_FRICTION         0.31f", CCB),
    _m("ccb_bounciness", "#define CAR_BOUNCINESS       0.1f",
       "#define CAR_BOUNCINESS       0.11f", CCB),
    _m("ccb_hard_impact", "#define CAR_HARD_IMPACT      20.0f",
       "#define CAR_HARD_IMPACT      19.999998f", CCB),
    _m("ccb_soft_impact", "#define CAR_SOFT_IMPACT      4.0f",
       "#define CAR_SOFT_IMPACT      3.9999998f", CCB),
    _m("ccb_box_xmax", "#define CAR_BOX_XMAX  2.165f", "#define CAR_BOX_XMAX  2.166f", CCB),
    _m("ccb_box_xmin", "#define CAR_BOX_XMIN -2.217f", "#define CAR_BOX_XMIN -2.218f", CCB),
    _m("ccb_box_ymax", "#define CAR_BOX_YMAX  0.971f", "#define CAR_BOX_YMAX  0.972f", CCB),
    _m("ccb_box_ymin", "#define CAR_BOX_YMIN -0.971f", "#define CAR_BOX_YMIN -0.972f", CCB),
    _m("ccb_box_zmax", "#define CAR_BOX_ZMAX  0.624f", "#define CAR_BOX_ZMAX  0.625f", CCB),
    _m("ccb_box_zmin", "#define CAR_BOX_ZMIN -0.2f", "#define CAR_BOX_ZMIN -0.21f", CCB),
    _m("ccb_box_y_order", "                                     CAR_BOX_YMAX, CAR_BOX_YMIN,",
       "                                     CAR_BOX_YMIN, CAR_BOX_YMAX,", CCB),

    # the constructor
    _m("ccb_ctor_no_count", "    s->NumCarCollisionBodies++;\n", "", CCB),
    _m("ccb_ctor_highest_always",
       "    if (s->HighestNumCarCollisionBodies < s->NumCarCollisionBodies)\n",
       "", CCB),
    _m("ccb_ctor_highest_le",
       "    if (s->HighestNumCarCollisionBodies < s->NumCarCollisionBodies)\n",
       "    if (s->HighestNumCarCollisionBodies <= s->NumCarCollisionBodies)\n", CCB),
    _m("ccb_ctor_no_active", "    body->ActiveCollisionDetection = 1;",
       "    body->ActiveCollisionDetection = 0;", CCB),
    _m("ccb_ctor_no_clear",
       "    d->pSystem = NULL;\n    d->pBody = NULL;\n    b->LastPenetrationTime",
       "    b->LastPenetrationTime", CCB),
    _m("ccb_ctor_pen_stamp", "    b->LastPenetrationTime.PackedTime = (uint32_t)WorldTimer;",
       "    b->LastPenetrationTime.PackedTime = 0;", CCB),
    _m("ccb_ctor_yaw_stamp", "    b->LastYawControlCollisionTime.PackedTime = (uint32_t)WorldTimer;",
       "    b->LastYawControlCollisionTime.PackedTime = 0;", CCB),
    _m("ccb_ctor_name", '"Car%d", car->DriverNumber', '"Car%d", car->DriverNumber + 1', CCB),
    _m("ccb_ctor_name_case", '"Car%d"', '"car%d"', CCB),
    _m("ccb_cv_suffix", '"%s_CV"', '"%s_cv"', CCB),
    _m("ccb_ctor_no_center", "                                  &car->pCarTypeInfo->CenterOfGravity);",
       "                                  NULL);", CCB),
    _m("ccb_ctor_never_pp", "    if (pp != NULL) {\n        body->pPoly",
       "    if (0) {\n        body->pPoly", CCB),
    _m("ccb_ctor_no_volumes", "    dynamiccollisionbody_build_bounding_volumes(d);\n", "", CCB),
    _m("ccb_ctor_no_update",
       "    dynamiccollisionbody_update_position(d);\n    return b;",
       "    return b;", CCB),

    # the destructor
    _m("ccb_dtor_no_count", "    TheCollisionStats.NumCarCollisionBodies--;\n", "", CCB),
    _m("ccb_dtor_vtable",
       "    body->_vtable = CARCOLLISIONBODY_VTABLE;\n    TheCollisionStats",
       "    TheCollisionStats", CCB),
    _m("ccb_dtor_find_inverted",
       "    if (find_pipeline_polyhedron(cv_hash(b->pCar), NULL) == NULL",
       "    if (find_pipeline_polyhedron(cv_hash(b->pCar), NULL) != NULL", CCB),
    _m("ccb_dtor_no_poly_test", "\n        && body->pPoly != NULL)", ")", CCB),
    _m("ccb_dtor_poly_flags", "        vcpoly_destroy(body->pPoly, 3);",
       "        vcpoly_destroy(body->pPoly, 2);", CCB),
    _m("ccb_dtor_base_flags", "    dynamiccollisionbody_destroy(&b->Dynamic, 0);",
       "    dynamiccollisionbody_destroy(&b->Dynamic, 1);", CCB),
    _m("ccb_dtor_free_flag", "    if (flags & 1)\n        carcollisionbody_delete(b);",
       "    if (flags & 2)\n        carcollisionbody_delete(b);", CCB),

    # the getters
    _m("ccb_position_pm",
       "    if (c->Dynamic.PhysicsMode != 0)\n        return (bVector3 *)&car_rb(c)->State.X;",
       "    if (c->Dynamic.PhysicsMode == 0)\n        return (bVector3 *)&car_rb(c)->State.X;", CCB),
    _m("ccb_velocity_pm",
       "    if (c->Dynamic.PhysicsMode != 0)\n        return (bVector3 *)&car_rb(c)->Velocity;",
       "    if (c->Dynamic.PhysicsMode == 0)\n        return (bVector3 *)&car_rb(c)->Velocity;", CCB),
    _m("ccb_rotation_pm",
       "    if (c->Dynamic.PhysicsMode != 0)\n        return &car_rb(c)->State.R;",
       "    if (c->Dynamic.PhysicsMode == 0)\n        return &car_rb(c)->State.R;", CCB),
    _m("ccb_position_car", "    return &c->pCar->State.Position;",
       "    return &c->pCar->State.Velocity;", CCB),
    _m("ccb_velocity_car", "    return &c->pCar->State.Velocity;",
       "    return &c->pCar->State.Position;", CCB),
    _m("ccb_rotation_car", "    return &c->pCar->State.BodyMatrix;",
       "    return &car_rb(c)->State.R;", CCB),
    _m("ccb_consider", "    return 1.0f;\n}", "    return 0.5f;\n}", CCB),
    _m("ccb_terrain", "    return TERRAIN_TYPE_CAR;", "    return TERRAIN_TYPE_CAR + 1;", CCB),
    _m("ccb_moveable", "    return 1;\n}\n\nfloat carcollisionbody_get_bounciness",
       "    return 0;\n}\n\nfloat carcollisionbody_get_bounciness", CCB),

    # Move
    _m("ccb_move_le", "    if (done < t) {", "    if (done <= t) {", CCB),
    _m("ccb_move_never", "    if (done < t) {", "    if (0) {", CCB),
    _m("ccb_move_rest", "        car_move(c->pCar, t - done);",
       "        car_move(c->pCar, t);", CCB),
    _m("ccb_move_rest_reversed", "        car_move(c->pCar, t - done);",
       "        car_move(c->pCar, done - t);", CCB),
    _m("ccb_move_other", "        ((VtSetToPhysicsModeFn)e->fn)(vt_this(b, e), NULL);",
       "        ((VtSetToPhysicsModeFn)e->fn)(vt_this(b, e), b);", CCB),
    _m("ccb_move_no_begin", "    dynamiccollisionbody_begin_move(&c->Dynamic, t);\n", "", CCB),
    _m("ccb_move_no_update",
       "        car_move(c->pCar, t - done);\n    }\n    dynamiccollisionbody_update_position(&c->Dynamic);",
       "        car_move(c->pCar, t - done);\n    }", CCB),

    # ApplyImpulse
    _m("ccb_ai_clamp_le", "    if (CAR_MASS_INVERSE_MAX < rb->Mass_inv)",
       "    if (CAR_MASS_INVERSE_MAX <= rb->Mass_inv)", CCB),
    _m("ccb_ai_clamp_always", "    if (CAR_MASS_INVERSE_MAX < rb->Mass_inv)",
       "    if (1)", CCB),
    _m("ccb_ai_clamp_never", "    if (CAR_MASS_INVERSE_MAX < rb->Mass_inv)",
       "    if (0)", CCB),
    _m("ccb_ai_clamp_ratio", "        f = CAR_MASS_INVERSE_MAX / rb->Mass_inv;",
       "        f = rb->Mass_inv / CAR_MASS_INVERSE_MAX;", CCB),
    _m("ccb_ai_x_unscaled", "    s.x = j->x * f;", "    s.x = j->x;", CCB),
    _m("ccb_ai_y_unscaled", "    s.y = j->y * f;", "    s.y = j->y;", CCB),
    _m("ccb_ai_z_unscaled", "    s.z = j->z * f;", "    s.z = j->z;", CCB),
    _m("ccb_ai_pad_unscaled", "    s.pad = j->pad * f;", "    s.pad = j->pad;", CCB),
    _m("ccb_ai_inertia_scale", "(const bVector4 *)at, CAR_INERTIA_SCALE);",
       "(const bVector4 *)at, 1.0f);", CCB),
    _m("ccb_ai_unscaled_impulse", "    rigidbody_apply_impulse_scaled(rb, (const bVector4 *)&s,",
       "    rigidbody_apply_impulse_scaled(rb, (const bVector4 *)j,", CCB),
    _m("ccb_ai_sum_order", "    amount = sqrtf((s.x * s.x + s.y * s.y) + s.z * s.z);",
       "    amount = sqrtf(s.x * s.x + (s.y * s.y + s.z * s.z));", CCB),
    _m("ccb_ai_no_z", "    amount = sqrtf((s.x * s.x + s.y * s.y) + s.z * s.z);",
       "    amount = sqrtf(s.x * s.x + s.y * s.y);", CCB),
    _m("ccb_ai_damage_at", "    carcollisionbody_add_damage(c, at, amount);",
       "    carcollisionbody_add_damage(c, j, amount);", CCB),
    _m("ccb_ai_anim_j", "    carcollisionbody_animate_collision_reaction(c, &s, amount);",
       "    carcollisionbody_animate_collision_reaction(c, j, amount);", CCB),
    _m("ccb_ai_order",
       "    carcollisionbody_add_damage(c, at, amount);\n"
       "    carcollisionbody_animate_collision_reaction(c, &s, amount);",
       "    carcollisionbody_animate_collision_reaction(c, &s, amount);\n"
       "    carcollisionbody_add_damage(c, at, amount);", CCB),

    # the frame
    _m("ccb_frame_no_transpose", "    bMulMatrixVec3(out, &rt, at);",
       "    bMulMatrixVec3(out, &car_rb(b)->State.R, at);", CCB),

    # AddDamage
    _m("ccb_ad_damage_scale", "                              amount * CAR_DAMAGE_SCALE);",
       "                              amount);", CCB),
    _m("ccb_ad_damage_world", "        gCarDamageAddDamageFn(car->pCarDamage, &local,",
       "        gCarDamageAddDamageFn(car->pCarDamage, at,", CCB),
    _m("ccb_ad_no_damage_test", "    if (car->pCarDamage != NULL) {", "    if (1) {", CCB),
    _m("ccb_ad_no_player_test",
       "    if (car->pPlayer != NULL && pRaceCoordinator != NULL) {",
       "    if (pRaceCoordinator != NULL) {", CCB),
    _m("ccb_ad_no_rc_test",
       "    if (car->pPlayer != NULL && pRaceCoordinator != NULL) {",
       "    if (car->pPlayer != NULL) {", CCB),
    _m("ccb_ad_tests_swapped",
       "    if (car->pPlayer != NULL && pRaceCoordinator != NULL) {",
       "    if (pRaceCoordinator != NULL && car->pPlayer != NULL) {", CCB),
    _m("ccb_ad_instant_replay", "        if (st != RCSTATE_INSTANT_REPLAY && st != RCSTATE_POSTRACE",
       "        if (st != RCSTATE_POSTRACE", CCB),
    _m("ccb_ad_postrace", "        if (st != RCSTATE_INSTANT_REPLAY && st != RCSTATE_POSTRACE",
       "        if (st != RCSTATE_INSTANT_REPLAY", CCB),
    _m("ccb_ad_auto_replay", "            && st != RCSTATE_AUTO_REPLAY\n", "", CCB),
    _m("ccb_ad_replay_demo",
       "            && !racecoordinator_is_replay_demo_mode(pRaceCoordinator)\n", "", CCB),
    _m("ccb_ad_ai_demo_wide", "                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 2u",
       "                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 3u", CCB),
    _m("ccb_ad_ai_demo_narrow", "                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 2u",
       "                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 1u", CCB),
    _m("ccb_ad_ai_demo_gone",
       "            && (uint32_t)racecoordinator_get_current_state(pRaceCoordinator)\n"
       "                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 2u\n", "", CCB),
    _m("ccb_ad_no_rumble_seam_test", "\n            && gPortRumbleImpactFn != NULL)", ")", CCB),
    _m("ccb_ad_rumble_port", "            gPortRumbleImpactFn(car->pPlayer->JoyPort, amount);",
       "            gPortRumbleImpactFn(0, amount);", CCB),
    _m("ccb_ad_rumble_scaled", "            gPortRumbleImpactFn(car->pPlayer->JoyPort, amount);",
       "            gPortRumbleImpactFn(car->pPlayer->JoyPort, amount * CAR_DAMAGE_SCALE);", CCB),
    _m("ccb_ad_no_cop_test", "    if (pCopManager != NULL) {", "    if (1) {", CCB),
    _m("ccb_ad_cop_never", "    if (pCopManager != NULL) {", "    if (0) {", CCB),
    _m("ccb_ad_cop_scaled", "        gCopManagerMonitorImpactFn(pCopManager, b->pCar, amount);",
       "        gCopManagerMonitorImpactFn(pCopManager, b->pCar, amount * CAR_DAMAGE_SCALE);", CCB),

    # AnimateCollisionReaction
    _m("ccb_an_no_driver", "    if (ad != NULL) {", "    if (0) {", CCB),
    _m("ccb_an_hard_le", "        if (CAR_HARD_IMPACT < amount) {",
       "        if (CAR_HARD_IMPACT <= amount) {", CCB),
    _m("ccb_an_soft_le", "        } else if (CAR_SOFT_IMPACT < amount) {",
       "        } else if (CAR_SOFT_IMPACT <= amount) {", CCB),
    _m("ccb_an_no_light", "        } else if (CAR_SOFT_IMPACT < amount) {",
       "        } else if (0) {", CCB),
    _m("ccb_an_axis_le", "            if (fabsf(local.y) < fabsf(local.x))",
       "            if (fabsf(local.y) <= fabsf(local.x))", CCB),
    _m("ccb_an_axis_signed", "            if (fabsf(local.y) < fabsf(local.x))",
       "            if (local.y < fabsf(local.x))", CCB),
    _m("ccb_an_axis_x_signed", "            if (fabsf(local.y) < fabsf(local.x))",
       "            if (fabsf(local.y) < local.x)", CCB),
    _m("ccb_an_axis_z", "            if (fabsf(local.y) < fabsf(local.x))",
       "            if (fabsf(local.z) < fabsf(local.x))", CCB),
    _m("ccb_an_x_le", "                type = 0.0f < local.x ?",
       "                type = 0.0f <= local.x ?", CCB),
    _m("ccb_an_y_le", "                type = 0.0f < local.y ?",
       "                type = 0.0f <= local.y ?", CCB),
    _m("ccb_an_back_front",
       "                type = 0.0f < local.x ? DRIVER_ANIMATION_TYPE_COLLISION_BACK\n"
       "                                      : DRIVER_ANIMATION_TYPE_COLLISION_FRONT;",
       "                type = 0.0f < local.x ? DRIVER_ANIMATION_TYPE_COLLISION_FRONT\n"
       "                                      : DRIVER_ANIMATION_TYPE_COLLISION_BACK;", CCB),
    _m("ccb_an_left_right",
       "                type = 0.0f < local.y ? DRIVER_ANIMATION_TYPE_COLLISION_LEFT\n"
       "                                      : DRIVER_ANIMATION_TYPE_COLLISION_RIGHT;",
       "                type = 0.0f < local.y ? DRIVER_ANIMATION_TYPE_COLLISION_RIGHT\n"
       "                                      : DRIVER_ANIMATION_TYPE_COLLISION_LEFT;", CCB),
    _m("ccb_an_hard_priority", "            begin_collision(ad, type, 3);",
       "            begin_collision(ad, type, 2);", CCB),
    _m("ccb_an_light_priority",
       "            begin_collision(ad, DRIVER_ANIMATION_TYPE_COLLISION_LIGHT, 2);",
       "            begin_collision(ad, DRIVER_ANIMATION_TYPE_COLLISION_LIGHT, 3);", CCB),
    _m("ccb_an_no_player_test",
       "    if (b->pCar->pPlayer != NULL && CAR_SOFT_IMPACT < amount) {",
       "    if (CAR_SOFT_IMPACT < amount) {", CCB),
    _m("ccb_an_force_le",
       "    if (b->pCar->pPlayer != NULL && CAR_SOFT_IMPACT < amount) {",
       "    if (b->pCar->pPlayer != NULL && CAR_SOFT_IMPACT <= amount) {", CCB),
    _m("ccb_an_force_hard",
       "    if (b->pCar->pPlayer != NULL && CAR_SOFT_IMPACT < amount) {",
       "    if (b->pCar->pPlayer != NULL && CAR_HARD_IMPACT < amount) {", CCB),
    _m("ccb_an_no_force_seam_test",
       "        if (gCarStartForceImpactFn != NULL) {", "        if (1) {", CCB),
    _m("ccb_an_force_world", "        to_car_frame(b, &local, j);\n        if (gCarStartForceImpactFn",
       "        local = *j;\n        if (gCarStartForceImpactFn", CCB),

    # the rest of the table's own
    _m("ccb_enabled_no_boring",
       "    if (BoringAIForCameraTuningOn != 0 || WilliamsAITuningMode != 0)",
       "    if (WilliamsAITuningMode != 0)", CCB),
    _m("ccb_enabled_no_williams",
       "    if (BoringAIForCameraTuningOn != 0 || WilliamsAITuningMode != 0)",
       "    if (BoringAIForCameraTuningOn != 0)", CCB),
    _m("ccb_enabled_and",
       "    if (BoringAIForCameraTuningOn != 0 || WilliamsAITuningMode != 0)",
       "    if (BoringAIForCameraTuningOn != 0 && WilliamsAITuningMode != 0)", CCB),
    _m("ccb_enabled_inverted", "    return b->CollisionsDisabled == 0;",
       "    return b->CollisionsDisabled != 0;", CCB),
    _m("ccb_mi_clamp_le", "    if (CAR_MASS_INVERSE_MAX < m)",
       "    if (CAR_MASS_INVERSE_MAX <= m)", CCB),
    _m("ccb_mi_clamp_nan", "    if (CAR_MASS_INVERSE_MAX < m)",
       "    if (!(m <= CAR_MASS_INVERSE_MAX))", CCB),
    _m("ccb_mi_no_clamp", "    if (CAR_MASS_INVERSE_MAX < m)", "    if (0)", CCB),
    _m("ccb_it_w_unscaled", "    o->w = v->w * CAR_INERTIA_SCALE;", "    o->w = v->w;", CCB),
    _m("ccb_it_row_source", "    scale_row(&out->v1, &in->v1);",
       "    scale_row(&out->v1, &in->v0);", CCB),
    _m("ccb_it_v3_scaled", "    out->v3 = in->v3;", "    scale_row(&out->v3, &in->v3);", CCB),
    _m("ccb_it_v2_unscaled", "    scale_row(&out->v2, &in->v2);", "    out->v2 = in->v2;", CCB),
    _m("ccb_blink_and", "    return car_is_blinking(car) || car_is_poofed(car);",
       "    return car_is_blinking(car) && car_is_poofed(car);", CCB),
    _m("ccb_blink_eager", "    return car_is_blinking(car) || car_is_poofed(car);",
       "    return car_is_blinking(car) | car_is_poofed(car);", CCB),
    _m("ccb_blink_order", "    return car_is_blinking(car) || car_is_poofed(car);",
       "    return car_is_poofed(car) || car_is_blinking(car);", CCB),

    # SetupPhysicsPointers and SetToPhysicsMode
    _m("ccb_spp_no_clear",
       "    d->pSystem = NULL;\n    d->pBody = NULL;\n    if (d->PhysicsMode == 0)",
       "    if (d->PhysicsMode == 0)", CCB),
    _m("ccb_spp_no_pm_test", "    if (d->PhysicsMode == 0)\n        return;\n", "", CCB),
    _m("ccb_spp_no_physics_test",
       "    if (car->TheMovementMode != PHYSICS_MOVEMENT\n"
       "        && car->TheMovementMode != MELLOW_MOVEMENT)",
       "    if (car->TheMovementMode != MELLOW_MOVEMENT)", CCB),
    _m("ccb_spp_no_mellow_test",
       "    if (car->TheMovementMode != PHYSICS_MOVEMENT\n"
       "        && car->TheMovementMode != MELLOW_MOVEMENT)",
       "    if (car->TheMovementMode != PHYSICS_MOVEMENT)", CCB),
    _m("ccb_spp_which_mover", "    if (car->TheMovementMode == PHYSICS_MOVEMENT) {",
       "    if (car->TheMovementMode != PHYSICS_MOVEMENT) {", CCB),
    _m("ccb_spp_physics_body", "        d->pBody = pc->pBody;", "        d->pBody = NULL;", CCB),
    _m("ccb_spp_mellow_system", "        d->pSystem = &mm->Vehicle;", "        d->pSystem = NULL;", CCB),
    _m("ccb_stpm_type", "    if (other != NULL && other->Type == 0)",
       "    if (other != NULL && other->Type != 0)", CCB),
    _m("ccb_stpm_no_type", "    if (other != NULL && other->Type == 0)",
       "    if (other != NULL)", CCB),
    _m("ccb_stpm_no_other", "    car_set_to_physics_mode(b->pCar, them);",
       "    car_set_to_physics_mode(b->pCar, NULL);", CCB),
    _m("ccb_stpm_no_setup",
       "    car_set_to_physics_mode(b->pCar, them);\n    carcollisionbody_setup_physics_pointers(b);",
       "    car_set_to_physics_mode(b->pCar, them);", CCB),

    # the inline accessors, and the layout
    _m("ccb_set_yaw_field", "    b->LastYawControlCollisionTime = *t;",
       "    b->LastPenetrationTime = *t;", CBH),
    _m("ccb_set_pen_field", "    b->LastPenetrationTime = *t;",
       "    b->LastYawControlCollisionTime = *t;", CBH),
    _m("ccb_get_yaw_field", "    return b->LastYawControlCollisionTime;",
       "    return b->LastPenetrationTime;", CBH),
    _m("ccb_get_pen_field", "    return b->LastPenetrationTime;",
       "    return b->LastYawControlCollisionTime;", CBH),
    _m("ccb_get_car", "    return b->pCar;\n}", "    return NULL;\n}", CBH),
    _m("ccb_timers_swapped",
       "    Timer     LastPenetrationTime;              // 260\n"
       "    Timer     LastYawControlCollisionTime;      // 264",
       "    Timer     LastYawControlCollisionTime;      // 264\n"
       "    Timer     LastPenetrationTime;              // 260", CBH),
    _m("ccb_no_quadword_pad",
       "    uint8_t   _pad268[4];                       // 268  the quadword round-up\n",
       "", CBH),

    # Contact's lanes and the VU's odd corners
    _m("ct_add_pad", "    o->pad = a->pad + b->pad;", "    o->pad = a->pad;",
       CTC),
    _m("ct_sub_pad", "    o->pad = a->pad - b->pad;", "    o->pad = a->pad;",
       CTC),
    _m("ct_sub_y", "    o->y = a->y - b->y;", "    o->y = b->y - a->y;", CTC),
    _m("ct_scale_pad", "    o->pad = v->pad * s;", "    o->pad = v->pad;", CTC),
    _m("ct_vf00_w", "    o->pad = 1.0f - v->pad;", "    o->pad = 0.0f - v->pad;",
       CTC),
    _m("ct_vf00_negate", "    o->y = 0.0f - v->y;", "    o->y = -v->y;", CTC),
    _m("ct_dot_order", "    return (a->x * b->x + a->y * b->y) + a->z * b->z;",
       "    return a->x * b->x + (a->y * b->y + a->z * b->z);", CTC),
    _m("ct_cross_pad", "    d->pad = a->pad;", "    d->pad = b->pad;", CTC),
    _m("ct_cross_x", "    float x = a->y * b->z - b->y * a->z;",
       "    float x = b->y * a->z - a->y * b->z;", CTC),
    _m("ct_min_is_max", "    return ft < fs ? ft : fs;",
       "    return ft < fs ? fs : ft;", CTC),
    _m("ct_max_is_min", "    return fs < ft ? ft : fs;",
       "    return fs < ft ? fs : ft;", CTC),

    # the pool and the list
    _m("ct_pool_slots", "bNewSlotPool((int)sizeof(Contact), 32,",
       "bNewSlotPool((int)sizeof(Contact), 16,", CTC),
    _m("ct_pool_flags", "\"ContactSlotPool\", 16);", "\"ContactSlotPool\", 0);",
       CTC),
    _m("ct_close_keeps_pool", "    ContactSlotPool = NULL;\n", "", CTC),
    _m("ct_delete_no_free", "    bSlotFree(ContactSlotPool, p);", "", CTC),
    _m("ct_destroy_flag", "    if (flags & 1)\n        contact_delete(c);",
       "    if (flags & 2)\n        contact_delete(c);", CTC),
    _m("ct_remove_only_b1",
       "        if (c->pBody1 == b || c->pBody2 == b) {",
       "        if (c->pBody1 == b) {", CTC),
    _m("ct_remove_only_b2",
       "        if (c->pBody1 == b || c->pBody2 == b) {",
       "        if (c->pBody2 == b) {", CTC),
    _m("ct_remove_no_prev_link",
       "            cnode(c->Link.prev)->next = next;\n", "", CTC),
    _m("ct_remove_no_next_link",
       "            cnode(next)->prev = c->Link.prev;\n", "", CTC),
    _m("ct_remove_no_free", "            contact_destroy(c, 3);",
       "            contact_destroy(c, 2);", CTC),
    _m("ct_sort_le", "    return b->BackupTime < a->BackupTime ? 0 : 1;",
       "    return b->BackupTime <= a->BackupTime ? 0 : 1;", CTC),
    _m("ct_sort_swapped", "    return b->BackupTime < a->BackupTime ? 0 : 1;",
       "    return a->BackupTime < b->BackupTime ? 0 : 1;", CTC),
    _m("ct_sort_nan", "    return b->BackupTime < a->BackupTime ? 0 : 1;",
       "    return !(a->BackupTime <= b->BackupTime) ? 0 : 1;", CTC),
    _m("ct_sorted_args", "        if (fn(node, n) == 0) {",
       "        if (fn(n, node) == 0) {", CTC),
    _m("ct_sorted_not", "        if (fn(node, n) == 0) {",
       "        if (fn(node, n) != 0) {", CTC),
    _m("ct_sorted_no_prev_next",
       "            cnode(prev)->next = node;\n            n->Link.prev = node;",
       "            n->Link.prev = node;", CTC),
    _m("ct_sorted_no_n_prev", "            n->Link.prev = node;\n", "", CTC),
    _m("ct_sorted_tail_no_prev_next",
       "    prev = list->prev;\n    cnode(prev)->next = node;",
       "    prev = list->prev;", CTC),
    _m("ct_sorted_tail_no_head_prev", "    list->prev = node;\n", "", CTC),
    _m("ct_sorted_tail_next", "    node->Link.next = end;",
       "    node->Link.next = prev;", CTC),

    # the constructor and FindContactTime
    _m("ct_init_swapped", "    c->pBody1 = b1;\n    c->pBody2 = b2;",
       "    c->pBody1 = b2;\n    c->pBody2 = b1;", CTC),
    _m("ct_init_no_time", "    c->BackupTime = contact_find_contact_time(c);",
       "    contact_find_contact_time(c);\n    c->BackupTime = 0.0f;", CTC),
    _m("ct_init_loop", "    c->LoopFound = WorldLoopCounter;",
       "    c->LoopFound = 0;", CTC),
    _m("ct_time_keeps_crowbar", "    c->CrowbarVector = zero;\n", "", CTC),
    _m("ct_time_zero_pad",
       "    zero.pad = 0.0f;                    // never written on the PS2",
       "    zero.pad = 1.0f;", CTC),
    _m("ct_time_longer_backup", "    hi = min_s(b, a);", "    hi = max_s(b, a);",
       CTC),
    _m("ct_time_quarter", "        t = lo + (hi - lo) * 0.5f;",
       "        t = lo + (hi - lo) * 0.25f;", CTC),
    _m("ct_time_seven_steps", "    for (i = 0; i < BISECTION_STEPS; i++) {",
       "    for (i = 0; i < BISECTION_STEPS - 1; i++) {", CTC),
    _m("ct_time_pen_hi", "            lo = t;\n", "            hi = t;\n", CTC),
    _m("ct_time_no_threshold",
       "        else if (c->pWitness->Witness.Distance < ContactThreshold)",
       "        else if (0)", CTC),
    _m("ct_time_crowbar_apart",
       "    if (r == VCLIP_PENETRATION)\n        contact_crowbar(c, t);",
       "    if (r != VCLIP_PENETRATION)\n        contact_crowbar(c, t);", CTC),

    # FindWaferNormal and Crowbar
    _m("ct_wafer_face", "    const VCFace *face = t->Static.Body.pPoly->pFaces;",
       "    const VCFace *face = t->Static.Body.pPoly->pFaces + 1;", CTC),
    _m("ct_wafer_bias_sign",
       "    if (face->Plane.CompressedPlaneDistance - WaferBias < dot3(&n, p)) {",
       "    if (face->Plane.CompressedPlaneDistance + WaferBias < dot3(&n, p)) {",
       CTC),
    _m("ct_wafer_tie",
       "    if (face->Plane.CompressedPlaneDistance - WaferBias < dot3(&n, p)) {",
       "    if (face->Plane.CompressedPlaneDistance - WaferBias <= dot3(&n, p)) {",
       CTC),
    _m("ct_wafer_negate", "        out->x = 0.0f - n.x;", "        out->x = -n.x;",
       CTC),
    _m("ct_wafer_pad", "        out->pad = n.pad;", "        out->pad = 1.0f;", CTC),
    _m("ct_crowbar_no_t1",
       "    if (c->pBody1->Type == TRACK_POLYGON_COLLISION_BODY) {",
       "    if (0) {", CTC),
    _m("ct_crowbar_no_flip", "        vf00_less(&n, &n);\n", "", CTC),
    _m("ct_crowbar_dir", "        lanes_sub(&n, &pos2, &pos1);",
       "        lanes_sub(&n, &pos1, &pos2);", CTC),
    _m("ct_crowbar_start", "    s = 0.0f;\n    for", "    s = CROWBAR_STEP;\n    for",
       CTC),
    _m("ct_crowbar_step", "        s = s + CROWBAR_STEP;",
       "        s = s + CROWBAR_STEP * 2.0f;", CTC),
    _m("ct_crowbar_nineteen", "    for (i = 0; i < CROWBAR_STEPS; i++) {",
       "    for (i = 0; i < CROWBAR_STEPS - 1; i++) {", CTC),
    _m("ct_crowbar_m1",
       "        if (is_moveable(c->pBody1))\n            lanes_sub(&p1, &p1, &cv);",
       "        if (is_moveable(c->pBody1))\n            lanes_add(&p1, &p1, &cv);",
       CTC),
    _m("ct_crowbar_m2",
       "        if (is_moveable(c->pBody2))\n            lanes_add(&p2, &p2, &cv);",
       "        if (is_moveable(c->pBody2))\n            lanes_sub(&p2, &p2, &cv);",
       CTC),
    _m("ct_crowbar_no_store", "            c->CrowbarVector = cv;\n", "", CTC),

    # Resolve
    _m("ct_resolve_mode_self", "    set_to_physics_mode(c->pBody1, c->pBody2);",
       "    set_to_physics_mode(c->pBody1, c->pBody1);", CTC),
    _m("ct_resolve_m1",
       "        lanes_sub(&p1, &p1, &c->CrowbarVector);",
       "        lanes_add(&p1, &p1, &c->CrowbarVector);", CTC),
    _m("ct_resolve_m2",
       "        lanes_add(&p2, &p2, &c->CrowbarVector);",
       "        lanes_sub(&p2, &p2, &c->CrowbarVector);", CTC),
    _m("ct_resolve_no_aux",
       "    recompute_auxilliaries(c->pBody2);\n    contact_collision_impulse(c);",
       "    contact_collision_impulse(c);", CTC),
    _m("ct_resolve_no_impulse", "    contact_collision_impulse(c);\n", "", CTC),
    _m("ct_resolve_move", "    body_move(c->pBody2, c->BackupTime);",
       "    body_move(c->pBody2, 0.0f);", CTC),

    # FindContactPointAndNormal and FindPlanarCollisionContactPoint
    _m("ct_point_cp2", "&c->pWitness->Witness.CP2);",
       "&c->pWitness->Witness.CP1);", CTC),
    _m("ct_point_half", "    lanes_scale(point, point, 0.5f);",
       "    lanes_scale(point, point, 0.25f);", CTC),
    _m("ct_point_b1_dynamic", "    if (c->pBody1->Dynamic == 0) {",
       "    if (c->pBody1->Dynamic != 0) {", CTC),
    _m("ct_point_no_flip", "        vf00_less(normal, normal);\n", "", CTC),
    _m("ct_point_dir", "        lanes_sub(normal, &b, &a);",
       "        lanes_sub(normal, &a, &b);", CTC),
    _m("ct_point_min_len_up", "        if (len < MIN_NORMAL_LENGTH) {",
       "        if (len < 1e-5f) {", CTC),
    _m("ct_point_min_len_down", "        if (len < MIN_NORMAL_LENGTH) {",
       "        if (len < 1e-7f) {", CTC),
    _m("ct_point_centres_dir", "            lanes_sub(normal, q2, q1);",
       "            lanes_sub(normal, q1, q2);", CTC),
    _m("ct_point_scale", "            lanes_scale(normal, normal, 1.0f / len);",
       "            lanes_scale(normal, normal, 0.5f / len);", CTC),
    _m("ct_planar_sign", "    lanes_scale(&e, &d, -dot3(&d, &up));",
       "    lanes_scale(&e, &d, dot3(&d, &up));", CTC),
    _m("ct_planar_up_pad",
       "    up.pad = 0.0f;                      // never written on the PS2",
       "    up.pad = 1.0f;", CTC),
    _m("ct_planar_no_normalise", "    normalize4(&e);\n    q1", "    q1", CTC),
    _m("ct_planar_body2",
       "    q1 = get_position(c->pBody1);\n    lanes_sub(&r",
       "    q1 = get_position(c->pBody2);\n    lanes_sub(&r", CTC),
    _m("ct_planar_r", "    lanes_sub(&r, point, q1);",
       "    lanes_sub(&r, q1, point);", CTC),
    _m("ct_planar_out", "    lanes_add(point, &e, point);",
       "    lanes_sub(point, point, &e);", CTC),
    _m("ct_cpv_cross", "    vu_cross(&x, w, r);", "    vu_cross(&x, r, w);", CTC),
    _m("ct_cpv_sub", "    lanes_add(out, v, &x);", "    lanes_sub(out, v, &x);",
       CTC),
    _m("ct_denom_first", "    vu_cross(&t, a, n);", "    vu_cross(&t, n, a);", CTC),
    _m("ct_denom_second", "    vu_cross(&s, &u, a);", "    vu_cross(&s, a, &u);",
       CTC),
    _m("ct_denom_dot", "    return dot3(n, &s);", "    return dot3(n, &t);", CTC),

    # CollisionImpulse
    _m("ct_imp_r1", "    lanes_sub(&r1, &point, get_position(c->pBody1));",
       "    lanes_sub(&r1, get_position(c->pBody1), &point);", CTC),
    _m("ct_imp_r2", "    lanes_sub(&r2, &point, get_position(c->pBody2));",
       "    lanes_sub(&r2, &point, get_position(c->pBody1));", CTC),
    _m("ct_imp_cpv_r", "        get_contact_point_velocity(&vp1, &v1, &w1, &r1);",
       "        get_contact_point_velocity(&vp1, &v1, &w1, &r2);", CTC),
    _m("ct_imp_vrel", "        lanes_sub(&vrel, &vp2, &vp1);",
       "        lanes_sub(&vrel, &vp1, &vp2);", CTC),
    _m("ct_imp_vt", "        lanes_scale(&vt, &normal, -vn);",
       "        lanes_scale(&vt, &normal, vn);", CTC),
    _m("ct_imp_touching", "        if (0.0f <= vn)", "        if (0.0f < vn)", CTC),
    _m("ct_imp_bounce_min", "        e = max_s(get_bounciness(c->pBody2), e);",
       "        e = min_s(get_bounciness(c->pBody2), e);", CTC),
    _m("ct_imp_mass2", "        m2 = get_mass_inverse(c->pBody2);",
       "        m2 = get_mass_inverse(c->pBody1);", CTC),
    _m("ct_imp_num", "        num = -(e + 1.0f) * vn;", "        num = -e * vn;",
       CTC),
    _m("ct_imp_denom_m", "        denom = m1 + m2;", "        denom = m1;", CTC),
    _m("ct_imp_denom_r1",
       "get_inertia_tensor_inverse(c->pBody1), &r1, &normal);",
       "get_inertia_tensor_inverse(c->pBody1), &r2, &normal);", CTC),
    _m("ct_imp_denom_r2",
       "get_inertia_tensor_inverse(c->pBody2), &r2, &normal);",
       "get_inertia_tensor_inverse(c->pBody2), &r1, &normal);", CTC),
    _m("ct_imp_mmax_min", "        mmax = max_s(m2, m1);",
       "        mmax = min_s(m2, m1);", CTC),
    _m("ct_imp_cap_two", "        if (1.0f < k)\n            k = 1.0f;",
       "        if (2.0f < k)\n            k = 2.0f;", CTC),
    _m("ct_imp_floor_ceiling", "        if (j < jmin)\n            j = jmin;",
       "        if (jmin < j)\n            j = jmin;", CTC),
    _m("ct_imp_jmin_times",
       "        jmin = k * MinimumContactImpulseFactor / mmax;",
       "        jmin = k * MinimumContactImpulseFactor * mmax;", CTC),
    _m("ct_imp_consider_order",
       "        cn2 = consider_impulse(c->pBody2, &jv, &r2);\n"
       "        vf00_less(&jv, &jv);\n"
       "        cn1 = consider_impulse(c->pBody1, &jv, &r1);",
       "        vf00_less(&jv, &jv);\n"
       "        cn1 = consider_impulse(c->pBody1, &jv, &r1);\n"
       "        vf00_less(&jv, &jv);\n"
       "        cn2 = consider_impulse(c->pBody2, &jv, &r2);", CTC),
    _m("ct_imp_consider_unturned",
       "        vf00_less(&jv, &jv);\n        cn1", "        cn1", CTC),
    _m("ct_imp_no_veto1",
       "        if (cn1 == CONSIDER_IMPULSE_VETO)\n            return;\n", "", CTC),
    _m("ct_imp_no_veto2",
       "        if (cn2 == CONSIDER_IMPULSE_VETO)\n            return;\n", "", CTC),
    _m("ct_imp_neg1_kept", "            cn1 = -cn1;", "            cn1 = cn1;", CTC),
    _m("ct_imp_neg2_kept", "            cn2 = -cn2;", "            cn2 = cn2;", CTC),
    _m("ct_imp_neg_both", "        else if (cn2 < 0.0f)", "        if (cn2 < 0.0f)",
       CTC),
    _m("ct_imp_never_negative", "        negative = 1;\n", "        negative = 0;\n",
       CTC),
    _m("ct_imp_least_max", "        least = min_s(cn2, cn1);",
       "        least = max_s(cn2, cn1);", CTC),
    _m("ct_imp_mu_min", "        mu = max_s(fr2, fr1);", "        mu = min_s(fr2, fr1);",
       CTC),
    _m("ct_imp_scrape1_any",
       "        if (m1 == 0.0f && fr2 == CAR_FRICTION) {",
       "        if (m1 == 0.0f) {", CTC),
    _m("ct_imp_scrape1_moving",
       "        if (m1 == 0.0f && fr2 == CAR_FRICTION) {",
       "        if (fr2 == CAR_FRICTION) {", CTC),
    _m("ct_imp_scrape2_any",
       "        } else if (m2 == 0.0f && fr1 == CAR_FRICTION) {",
       "        } else if (m2 == 0.0f) {", CTC),
    _m("ct_imp_scrape2_moving",
       "        } else if (m2 == 0.0f && fr1 == CAR_FRICTION) {",
       "        } else if (fr1 == CAR_FRICTION) {", CTC),
    _m("ct_imp_scraper1", "            scraper = c->pBody2;",
       "            scraper = c->pBody1;", CTC),
    _m("ct_imp_scraper2", "            scraper = c->pBody1;\n            mu",
       "            scraper = c->pBody2;\n            mu", CTC),
    _m("ct_imp_scrape1_mu", "            mu = SCRAPE_FRICTION;\n        } else",
       "            mu = CAR_FRICTION;\n        } else", CTC),
    _m("ct_imp_scrape2_mu", "            mu = SCRAPE_FRICTION;\n        }\n",
       "            mu = CAR_FRICTION;\n        }\n", CTC),
    _m("ct_imp_fade_above", "        if (vtl < MaxFrictionScrapeSpeed)",
       "        if (MaxFrictionScrapeSpeed < vtl)", CTC),
    _m("ct_imp_fade_times",
       "            k = k * (vtl / MaxFrictionScrapeSpeed);",
       "            k = k * (vtl * MaxFrictionScrapeSpeed);", CTC),
    _m("ct_imp_friction_sign", "        lanes_scale(&f, &vt, ee_div(-k, vtl));",
       "        lanes_scale(&f, &vt, ee_div(k, vtl));", CTC),
    _m("ct_imp_jv_stale",
       "        lanes_scale(&jv, &normal, j);\n        lanes_add(&jt, &jv, &f);",
       "        lanes_add(&jt, &jv, &f);", CTC),
    _m("ct_imp_jt_sub", "        lanes_add(&jt, &jv, &f);",
       "        lanes_sub(&jt, &jv, &f);", CTC),
    _m("ct_imp_jn_negate", "        vf00_less(&jn, &jt);",
       "        lanes_scale(&jn, &jt, -1.0f);", CTC),
    _m("ct_imp_pull_below", "            if (PULL_MIN_SPEED < speed) {",
       "            if (speed < PULL_MIN_SPEED) {", CTC),
    _m("ct_imp_pull_dead_factor", "                pull = PULL_FACTOR;\n",
       "                pull = 0.0f;\n", CTC),
    _m("ct_imp_pull_no_limit",
       "                if (speed * PULL_FACTOR < PULL_LIMIT)",
       "                if (0)", CTC),
    _m("ct_imp_pull_limit_flat", "                    pull = PULL_LIMIT / speed;",
       "                    pull = PULL_LIMIT;", CTC),
    _m("ct_imp_pull_keeps_z", "                vel.z = 0.0f;\n", "", CTC),
    _m("ct_imp_pull_branch", "                if (m1 == vel.z) {",
       "                if (m1 != vel.z) {", CTC),
    _m("ct_imp_len_from_jn", "                    len = sqrtf(dot3(&jt, &jt));",
       "                    len = sqrtf(dot3(&jn, &jn));", CTC),
    _m("ct_imp_pull_jt_sub", "                    lanes_add(&jt, &jt, &vel);",
       "                    lanes_sub(&jt, &jt, &vel);", CTC),
    _m("ct_imp_lever2_never",
       "                    if (1.0f < speed + len)\n"
       "                        lanes_scale(&r2",
       "                    if (0)\n"
       "                        lanes_scale(&r2", CTC),
    _m("ct_imp_lever2_always",
       "                    if (1.0f < speed + len)\n"
       "                        lanes_scale(&r2",
       "                    if (1)\n"
       "                        lanes_scale(&r2", CTC),
    _m("ct_imp_lever2_factor",
       "lanes_scale(&r2, &r2,\n"
       "                                    len / (speed * LEVER_FACTOR + len));",
       "lanes_scale(&r2, &r2,\n"
       "                                    len / (speed + len));", CTC),
    _m("ct_imp_pull_jn_sub", "                    lanes_add(&jn, &jn, &vel);",
       "                    lanes_sub(&jn, &jn, &vel);", CTC),
    _m("ct_imp_lever1_never",
       "                    if (1.0f < speed + len)\n"
       "                        lanes_scale(&r1",
       "                    if (0)\n"
       "                        lanes_scale(&r1", CTC),
    _m("ct_imp_lever1_factor",
       "lanes_scale(&r1, &r1,\n"
       "                                    len / (speed * LEVER_FACTOR + len));",
       "lanes_scale(&r1, &r1,\n"
       "                                    len / (speed + len));", CTC),
    _m("ct_imp_apply_order",
       "        apply_impulse(c->pBody2, &jt, &r2);\n"
       "        apply_impulse(c->pBody1, &jn, &r1);",
       "        apply_impulse(c->pBody1, &jn, &r1);\n"
       "        apply_impulse(c->pBody2, &jt, &r2);", CTC),
    _m("ct_imp_apply_jt", "        apply_impulse(c->pBody1, &jn, &r1);",
       "        apply_impulse(c->pBody1, &jt, &r1);", CTC),
    _m("ct_imp_collision_jn", "        add_impulse(coll, &point, &jt, vtl);",
       "        add_impulse(coll, &point, &jn, vtl);", CTC),
    _m("ct_imp_collision_k", "        add_impulse(coll, &point, &jt, vtl);",
       "        add_impulse(coll, &point, &jt, k);", CTC),
    _m("ct_imp_least_ge", "        if (least == 1.0f)\n            return;",
       "        if (1.0f <= least)\n            return;", CTC),
    _m("ct_imp_negative_goes_on", "        if (negative)\n            return;\n",
       "", CTC),

    # the witness's three
    _m("ct_getcoll_always",
       "    if (w->pCollision == NULL)\n        cbwitness_begin_collision(w, pt);",
       "    cbwitness_begin_collision(w, pt);", CTC),
    _m("ct_begin_nc1",
       "    w->pBody1->NumCollisions = (int8_t)(w->pBody1->NumCollisions + 1);",
       "    w->pBody1->NumCollisions = (int8_t)(w->pBody1->NumCollisions + 2);",
       CTC),
    _m("ct_begin_nc2",
       "    w->pBody2->NumCollisions = (int8_t)(w->pBody2->NumCollisions + 1);",
       "", CTC),
    _m("ct_begin_no_highest",
       "    if (TheCollisionStats.HighestNumCollisions < n)",
       "    if (0)", CTC),
    _m("ct_begin_highest_less",
       "        TheCollisionStats.HighestNumCollisions = n;",
       "        TheCollisionStats.HighestNumCollisions = n - 1;", CTC),
    _m("ct_begin_no_count", "    TheCollisionStats.NumCollisions = n;\n", "", CTC),
    _m("ct_begin_drops_collision", "    w->pCollision = gCollisionNewFn(w, pt);",
       "    gCollisionNewFn(w, pt);", CTC),
    _m("ct_test_keeps_print", "    if (PrintThisTime)\n        PrintThisTime = 0;\n",
       "", CTC),
    _m("ct_test_apart", "    if (r != VCLIP_PENETRATION)\n        return;",
       "    if (r == 0)\n        return;", CTC),
    _m("ct_test_blink_b1_only",
       "    if (is_blinking(w->pBody1) || is_blinking(w->pBody2)) {",
       "    if (is_blinking(w->pBody1)) {", CTC),
    _m("ct_test_blink_dyn_b2",
       "        if (w->pBody1->Dynamic != 0 && w->pBody2->Dynamic != 0) {",
       "        if (w->pBody2->Dynamic != 0) {", CTC),
    _m("ct_test_blink_dyn_b1",
       "        if (w->pBody1->Dynamic != 0 && w->pBody2->Dynamic != 0) {",
       "        if (w->pBody1->Dynamic != 0) {", CTC),
    _m("ct_test_blink_stamp1_any",
       "            if (w->pBody1->Type == CAR_COLLISION_BODY)\n"
       "                ((CarCollisionBody *)w->pBody1)->LastPenetrationTime",
       "            if (1)\n"
       "                ((CarCollisionBody *)w->pBody1)->LastPenetrationTime",
       CTC),
    _m("ct_test_blink_stamp2_any",
       "            if (w->pBody2->Type == CAR_COLLISION_BODY)\n"
       "                ((CarCollisionBody *)w->pBody2)->LastPenetrationTime",
       "            if (1)\n"
       "                ((CarCollisionBody *)w->pBody2)->LastPenetrationTime",
       CTC),
    _m("ct_test_blink_goes_on",
       "                    .PackedTime = (uint32_t)WorldTimer;\n            return;",
       "                    .PackedTime = (uint32_t)WorldTimer;", CTC),
    _m("ct_test_yaw1_any",
       "    if (w->pBody1->Type == CAR_COLLISION_BODY\n        && is_yaw",
       "    if (1\n        && is_yaw", CTC),
    _m("ct_test_yaw1_always",
       "        && is_yaw_control_inducing_collision_body(w->pBody2))",
       "        && 1)", CTC),
    _m("ct_test_yaw2_any",
       "    if (w->pBody2->Type == CAR_COLLISION_BODY\n        && is_yaw",
       "    if (1\n        && is_yaw", CTC),
    _m("ct_test_yaw2_always",
       "        && is_yaw_control_inducing_collision_body(w->pBody1))",
       "        && 1)", CTC),
    _m("ct_test_yaw_field",
       "        ((CarCollisionBody *)w->pBody1)->LastYawControlCollisionTime",
       "        ((CarCollisionBody *)w->pBody1)->LastPenetrationTime", CTC),
    _m("ct_test_swapped",
       "contact_init(contact_new(), w->pBody1, w->pBody2, w));",
       "contact_init(contact_new(), w->pBody2, w->pBody1, w));", CTC),
]

# Mutations no script can catch, each with the reason.
EQUIVALENT = {
    "ct_imp_pull_dead_factor":
        "the pull is only worked out past 30, where speed times -0.025 is "
        "below -0.75 and so always under PULL_LIMIT's -0.4: the -0.025 it "
        "starts at is always replaced by -0.4 / speed",
    "ct_imp_lever2_always":
        "the lever arm is only shortened past 30, where 1 < speed + len "
        "always holds",
    "ct_imp_len_from_jn":
        "jn is vf00 less jt, so its first three lanes are jt's negated, and "
        "the length squares them",
    "sclose_no_witness_unlink":
        "~bTList takes the witness off the list and then its destructor "
        "does it again from the witness's own links, which the first did "
        "not touch, so the second writes the same two pointers",
    "sclose_no_body_unlink":
        "the same for a body: ~CollisionBody unlinks it again",
    "na_allocn_past_top":
        "bit MaxNumbers is never set -- nothing allocates past the top and "
        "every field starts zeroed -- so looking one bit further stops at "
        "the same place",
    "init_no_zero_matrix":
        "nothing writes ZeroMatrix, so it is zero before InitCollisionBody "
        "zeroes it again",
    "width_no_same_test":
        "a width equal to the current one fails the widening test and "
        "then returns at !(w < cur) anyway",
    "static_dtor_vtable":
        "~CollisionBody overwrites the table pointer before anything reads "
        "it",
    "tp_dtor_vtable":
        "the same: ~StaticCollisionBody and then ~CollisionBody overwrite it",
    "wit_collision":
        "the witness pool zeroes every slot it hands out, and a witness is "
        "only ever built in one",
    "maybe_keeps_end":
        "nothing reads a destroyed witness: it is off the list, and with "
        "flags 3 its slot is freed straight after and zeroed before it is "
        "handed out again",
    "dyn_dtor_vtable":
        "~CollisionBody overwrites the table pointer before anything reads "
        "it",
    "dyn_ctp_none":
        "with nothing kept, the sort's one pass and the loop that makes the "
        "bodies both run no times, and n, 0, is returned",
    "ccb_ctor_highest_le":
        "at an equal count the highest is stored over itself",
    "ccb_ctor_no_clear":
        "DynamicCollisionBody's constructor has cleared pSystem and pBody "
        "already",
    "ccb_dtor_vtable":
        "~DynamicCollisionBody overwrites the table pointer before anything "
        "reads it",
    "ccb_ai_clamp_le":
        "at the bound, f is the bound over itself, 1 exactly",
    "ccb_ad_tests_swapped":
        "both tests are loads, and nothing between them writes",
    "ccb_ad_replay_demo":
        "IsReplayDemoMode is state 9, and the AI demo test's unsigned range "
        "shuts out 8 and 9 after it",
    "ccb_ad_ai_demo_narrow":
        "a range of state 8 alone leaves 9, which IsReplayDemoMode has shut "
        "out before it",
    "ccb_an_x_le":
        "the x branch is only taken when |y| < |x|, so x is neither zero "
        "nor a NaN in it",
    "ccb_mi_clamp_le":
        "at the bound, the bound is stored over itself",
    "ccb_spp_which_mover":
        "PhysicsCar and MellowMover both hold the PhysicsSystem and the "
        "RigidBody pointer at the same offsets, on the host as on the "
        "console, so either cast reads the same two pointers",
}


def mutate_pass(sc, base_model, only=None):
    survived, missing, equivalent, caught = [], [], [], 0
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only is not None:
        unknown = sorted(set(only) - {m[0] for m in MUTATIONS})
        if unknown:
            sys.exit("no such mutation: " + " ".join(unknown))

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.bin"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, sp, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in todo:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-28s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                sp = Path(tmp) / "script.bin"
                write_script(sc, sp)
                try:
                    exe = build(tmp)
                except SystemExit:
                    print("  %-28s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, sp, out)
                if rc == HARNESS_HUNG:
                    print("  %-28s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-28s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-28s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-28s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-28s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    # --only leaves the others unrun, so only the ones that ran are judged.
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally below is over %d of %d"
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
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    sc = script()
    lines = model(sc)
    if args.mutate:
        sys.exit(mutate_pass(sc, lines,
                             args.only.split(",") if args.only else None))

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "script.bin"
        write_script(sc, sp)
        exe = build(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, sp, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)

    bad = diff(lines, harness)
    ops = sum(1 for line in lines if not line.startswith(("  ", "[")))
    dumps = sum(1 for line in lines if line == "dump")
    print("%d scenarios, %d ops, %d lines, %d dumps, %d differ; TrackPolygon "
          "bodies on TRACKB12 polygons %s"
          % (len(sc.tags), ops, len(harness), dumps, bad,
             " ".join("%d" % p for p in sc.picks)))
    sys.exit(1 if (bad or rc) else 0)


if __name__ == "__main__":
    main()
