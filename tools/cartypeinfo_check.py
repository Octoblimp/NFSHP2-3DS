"""Cross-check 3DS Files/source/cartypeinfo.c against a model of CarTypeInfo.

CarTypeInfo is the third piece of task 25, after CarState and Engine. It is
the car type's data record: 1376 bytes of tuning and presentation, one per
car in the game, shared by every instance. Nothing in it simulates
anything.

That makes this slice unusual, and worth being explicit about. Seven
functions is a thin edge, and they are all one-liners; what actually
matters here is the **layout**, because Wheel, Suspension, DriveTrain,
PhysicsCar and Car all index into this record and every one of them will
inherit whatever is wrong with it. So the transcript spends most of its
lines on offsets, and on reading values poked in at PS2 offsets back out
through the host struct's named fields. A field in the wrong place moves a
number, and the number is printed.

The size has an independent witness. `GetCarTypeInfo(CarType)` at
0x001801c0 is

    addiu v1,zero,1376 ; lw v0,-21184(gp) ; mult a0,a0,v1 ; addu v0,v0,a0

so the compiler emitted sizeof(CarTypeInfo) as a literal, in a different
compilation unit from the .mdebug entry the field list came from. The two
agree at 1376, which is a stronger claim than either alone.

One field is *not* in the .mdebug dump: a pointer at byte 1368 that the six
string accessors dereference. It was recovered from `lw v0,1368(a0)` in all
six and points at a record of translated-string ids, called CarSpecs here.

The model is written from the disassembly. langtab's binary search and
bStringHash are re-derived here rather than imported, so a CarTypeInfo
accessor reaching for the wrong CarSpecs slot cannot hide behind a shared
helper.

    python tools/cartypeinfo_check.py
    python tools/cartypeinfo_check.py --mutate
    python tools/cartypeinfo_check.py --dump out/cartypeinfo
"""
import argparse
import difflib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/cartypeinfo_test.c",
    "3DS Files/source/cartypeinfo.c",
    "3DS Files/source/langtab.c", "3DS Files/source/portlang.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]

CI = "3DS Files/source/cartypeinfo.c"
CH = "3DS Files/source/cartypeinfo.h"

# The host the harness is built for. Everything the model says about
# sizeof and about the tail of the record depends on this.
PTR = 8

# ------------------------------------------------------------------ floats


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def g9(x):
    """%.9g, the way C prints it."""
    s = "%.9g" % x
    return s


# ------------------------------------------------------------------ layout

# The PS2 offsets, from the .mdebug STABS entry for CarTypeInfo, with
# pCarSpecs at 1368 from the six accessors' `lw v0,1368(a0)`.
PS2_OFF = [
    ("CarTypeName", 0),
    ("BaseModelName", 32),
    ("GeometryFilename", 64),
    ("CompressedGeometryFilename", 96),
    ("DashGeometryFilename", 128),
    ("CompressedDashGeometryFilename", 160),
    ("ManufacturerName", 192),
    ("HeadlightPosition", 208),
    ("HeadlightFOV", 224),
    ("HighPerformance", 228),
    ("NumAvailableSkins", 229),
    ("CarClass", 230),
    ("OpenTop", 231),
    ("DriverRenderingOffset", 240),
    ("InCarSteeringWheelRenderingOffset", 256),
    ("CenterOfGravity", 272),
    ("Wheels", 288),
    ("Tires", 416),
    ("Body", 480),
    ("Suspension", 560),
    ("DriveTrain", 624),
    ("Engine", 688),
    ("Aero", 752),
    ("Control", 768),
    ("Sound", 816),
    ("Camera", 960),
    ("HudInfo", 1232),
    ("LocationProb", 1312),
    ("Type", 1332),
    ("UsageType", 1336),
    ("InitialLockStatus", 1340),
    ("BeACopLockStatus", 1344),
    ("AvailableSkins", 1348),
    ("Dummy", 1358),
    ("DefaultSkinNumber", 1364),
    ("pCarSpecs", 1368),
]

PS2_SIZE = 1376

NESTED_SIZE = [
    ("WheelInfo", 32),
    ("TireInfo", 32),
    ("SuspensionInfo", 32),
    ("DriveTrainInfo", 64),
    ("RigidBodyInfo", 80),
    ("AeroInfo", 16),
    ("ControlInfo", 48),
    ("EngineInfo", 64),
    ("CarSpecs", 28),
]

# Fields inside the nested records, as an absolute offset from the top of
# CarTypeInfo. Each is worked out here from the nested layout rather than
# read off the header, so a nested record that is laid out wrong on the
# host shows up as a differing offset.
NESTED_OFF = [
    ("Wheels[2].Radius", 288 + 2 * 32 + 12),
    ("Wheels[3].OffsetY", 288 + 3 * 32 + 24),
    ("Tires[1].ForceScale", 416 + 32 + 8),
    ("Body.InertiaTensor", 480 + 16),
    ("Suspension[1].Damping1", 560 + 32 + 8 + 4),
    ("Suspension[0].BumpStop1", 560 + 20 + 4),
    ("DriveTrain.GearRatios5", 624 + 32 + 5 * 4),
    ("Engine.MomentOfInertia", 688 + 12),
    ("Control.SpeedLimiter", 768 + 32),
]


# Every array member, and how many bytes it spans. An array's extent is
# part of the layout claim just as much as its offset, and the offsets
# alone do not pin it -- shortening Wheels to three and padding after it
# leaves every following offset exactly where it was.
ARRAY_SIZE = [
    ("CarTypeName", 32),
    ("BaseModelName", 32),
    ("GeometryFilename", 32),
    ("CompressedGeometryFilename", 32),
    ("DashGeometryFilename", 32),
    ("CompressedDashGeometryFilename", 32),
    ("ManufacturerName", 16),
    ("Wheels", 4 * 32),
    ("Tires", 2 * 32),
    ("Suspension", 2 * 32),
    ("Sound", 144),
    ("Camera", 272),
    ("HudInfo", 80),
    ("LocationProb", 20),
    ("AvailableSkins", 10),
    ("Dummy", 6),
    ("TireInfo.dummy", 12),
    ("SuspensionInfo.Damping", 8),
    ("SuspensionInfo.BumpStop", 8),
    ("DriveTrainInfo.FinalDrive", 8),
    ("DriveTrainInfo.GearRatios", 32),
    ("RigidBodyInfo.InertiaTensor", 64),
    ("ControlInfo.dummy", 12),
    ("EngineInfo.TorqueCurveTable", 36),
    ("EngineInfo.EngineBrakingTable", 12),
]


def host_size():
    """CarTypeInfo has exactly one pointer and it is second from last.

    DefaultSkinNumber ends at 1368, which is already 8-aligned, so the
    pointer does not push anything before it: every offset in PS2_OFF is
    also the host offset. What does change is the tail -- the pointer is
    four bytes wider, and the whole record then aligns to the pointer.
    """
    end = 1368 + PTR + 4          # pCarSpecs, then Pad1
    return (end + PTR - 1) // PTR * PTR


# ------------------------------------------------------------- string hash

def bstring_hash(s):
    """bStringHash, 0x0023b280. djb2 seeded with -1 rather than 5381."""
    h = 0xFFFFFFFF
    for ch in s.encode("latin-1"):
        h = (h * 33 + ch) & 0xFFFFFFFF
    return h


def as_s32(u):
    return u - 0x100000000 if u >= 0x80000000 else u


# -------------------------------------------------------- the string table

# The pool the harness builds. The final string has no NUL after it, so its
# length comes from the end of the pool rather than from a terminator.
POOL = (b"Honda Civic Type R\x00"
        b"Civic\x00"
        b"6.8 s\x00"
        b"300 km/h\x00"
        b"197 bhp\x00"
        b"Honda")

ID_ENTRIES = sorted([
    (100, 0), (101, 19), (102, 25), (103, 31), (104, 40), (999, 9000),
])
HASH_ENTRIES = sorted([
    (as_s32(bstring_hash("HONDA")), 48),
    (as_s32(bstring_hash("FORD")), 19),
    (as_s32(bstring_hash("")), 0),
])


def lookup(entries, key):
    """GetString, 0x0020acd0: a binary search over sorted signed keys.

    Returns (text, length) or None. An offset past the end of the pool is
    rejected, and a string that runs to the end of the pool without a NUL
    takes its length from the pool's end.
    """
    lo, hi = 0, len(entries)
    while lo < hi:
        mid = (lo + hi) // 2
        k, off = entries[mid]
        if k < key:
            lo = mid + 1
        elif k > key:
            hi = mid
        else:
            if off >= len(POOL):
                return None
            rest = POOL[off:]
            nul = rest.find(b"\x00")
            n = len(rest) if nul < 0 else nul
            return rest[:n].decode("latin-1"), n
    return None


def langtab_get(id_):
    return lookup(ID_ENTRIES, id_)


def langtab_get_english(hash_):
    return lookup(HASH_ENTRIES, hash_)


# ----------------------------------------------------------------- bRandom

def brandom(range_, seed):
    """bRandom, 0x00241cc8.

    `mfhi` after `divu v1,a0` -- so the value handed back is the *old*
    seed reduced mod range, and the state moves afterwards. A draw taken
    straight after a reseed is therefore the seed itself.
    """
    s = seed & 0xFFFFFFFF
    t = (s ^ 0x1D872B41) & 0xFFFFFFFF
    u = (t ^ (t >> 5)) & 0xFFFFFFFF
    v = (t ^ ((u << 27) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return s % (range_ & 0xFFFFFFFF), (u ^ v) & 0xFFFFFFFF


def get_random_skin(skins, nskins, seed):
    """GetRandomSkin, 0x001804c0.

    `move v0,zero` sits in the delay slot of the branch that tests
    NumAvailableSkins, so the no-skins answer is a cleared return register
    and not AvailableSkins[0]; and the seed is not touched on that path,
    because bRandom is never reached. `lb` sign-extends the skin id.
    """
    if nskins == 0:
        return 0, seed
    i, seed = brandom(nskins, seed)
    b = skins[i]
    return b - 256 if b >= 128 else b, seed


# ---------------------------------------------------------------- emitting

OUT = []


def emit(s):
    OUT.append(s)


def pad(s, n):
    return s + " " * (n - len(s)) if len(s) < n else s


def s_layout():
    emit("[layout]")
    emit("sizeof_host %d" % host_size())
    emit("slack %d" % (PTR - 4))

    for name, off in PS2_OFF:
        emit("off %s %d" % (pad(name, 34), off))

    for name, size in NESTED_SIZE:
        emit("size %s %d" % (name, size))

    for name, off in NESTED_OFF:
        emit("noff %s %d" % (pad(name, 24), off))

    for name, size in ARRAY_SIZE:
        emit("arr %s %d" % (pad(name, 28), size))

    # The harness pokes these at PS2 offsets and reads them back through
    # the named fields. The values are restated here, not recomputed, so
    # a field in the wrong place changes what the harness prints and
    # nothing changes what the model prints.
    emit("read CarTypeName CIVIC")
    emit("read ManufacturerName HONDA")
    emit("read HeadlightPosition %s %s %s"
         % (g9(f32(1.25)), g9(f32(-2.5)), g9(f32(7.5))))
    emit("read HeadlightFOV %s" % g9(f32(55.0)))
    emit("read HighPerformance 1")
    emit("read NumAvailableSkins 7")
    emit("read CarClass 3")
    emit("read OpenTop -2")
    emit("read CenterOfGravity %s %s %s"
         % (g9(f32(0.125)), g9(f32(0.25)), g9(f32(-0.5))))
    emit("read Wheels2Radius %s" % g9(f32(0.34)))
    emit("read Tires1ForceScale %s" % g9(f32(4.5)))
    emit("read BodyMass %s" % g9(f32(1400.0)))
    emit("read BodyInertia5 %s" % g9(f32(900.0)))
    emit("read Susp1Damping1 %s" % g9(f32(6.0)))
    emit("read Susp0BumpStop1 %s" % g9(f32(11.0)))
    emit("read NumGears 6")
    emit("read GearRatios5 %s" % g9(f32(0.85)))
    emit("read EngineMOI %s" % g9(f32(0.35)))
    emit("read AeroRearDownforce %s" % g9(f32(120.0)))
    emit("read SpeedLimiter %s" % g9(f32(62.5)))
    emit("read Type 9")
    emit("read UsageType 2")
    emit("read InitialLockStatus 1")
    emit("read BeACopLockStatus 0")
    emit("read Skins 3 -7 120")
    emit("read DefaultSkinNumber 5")


def show(tag, what, got):
    if got is None:
        emit("%s %s NULL" % (tag, what))
    else:
        emit("%s %s %d [%s]" % (tag, what, got[1], got[0]))


# The CarSpecs slot each accessor reads, from retail's `lw a0,N(v0)`.
#   0x00187eb8  the full name       20
#   0x00187ed8  the short name      24
#   GetCarSpec0To60                  4
#   GetCarSpecTopSpeed(units)       12 for 1, 8 for 0, id 0 otherwise
#   GetCarSpecBHP                   16
# Nothing reads slot 0, the car type.
SPEC_SLOT = {"full": 5, "short": 6, "0to60": 1, "bhp": 4}


def top_speed_id(specs, units):
    if units == 1:
        return specs[3]
    if units == 0:
        return specs[2]
    return 0


def accessors(tag, specs, manufacturer):
    for what in ("full", "short", "0to60"):
        show(tag, what, langtab_get(specs[SPEC_SLOT[what]]))
    for units in (0, 1, 2, -1):
        show(tag, "topspd%d" % units, langtab_get(top_speed_id(specs, units)))
    show(tag, "bhp", langtab_get(specs[SPEC_SLOT["bhp"]]))
    show(tag, "manuf",
         langtab_get_english(as_s32(bstring_hash(manufacturer))))


def s_strings():
    emit("[strings]")
    emit("parsed numHash %d numID %d textSize %d lang %d file %s"
         % (len(HASH_ENTRIES), len(ID_ENTRIES), len(POOL), 0, "FE_ENG.BIN"))
    emit("hash HONDA %d" % as_s32(bstring_hash("HONDA")))
    emit("hash FORD %d" % as_s32(bstring_hash("FORD")))
    emit("hash empty %d" % as_s32(bstring_hash("")))

    accessors("good", [77, 102, 103, 101, 104, 100, 101], "HONDA")
    accessors("absent", [100, 1, 2, 3, 4, 5, 6], "NOPE")
    accessors("oob", [100, 999, 999, 999, 999, 999, 999], "")
    accessors("shifted", [104, 100, 101, 102, 103, 104, 102], "FORD")
    accessors("rotated", [0, 103, 104, 100, 101, 102, 999], "HONDA")

    show("nullspecs", "manuf",
         langtab_get_english(as_s32(bstring_hash("FORD"))))

    # ManufacturerName is 16 bytes and the accessor hands it to a routine
    # that expects a C string, so a full-width name runs into whatever
    # follows -- HeadlightPosition, whose first byte the harness clears.
    emit("manuf overrun hash %d"
         % as_s32(bstring_hash("0123456789ABCDEF")))


SKINS = [3, 0, 9, 255, 249, 12, 4, 4, 0, 120]   # -1 and -7 as raw bytes


def s_skins():
    emit("[skins]")

    v, seed = get_random_skin(SKINS, 0, 12345)
    emit("none %d seed %d" % (v, seed))

    seed = 12345
    for i in range(3):
        v, seed = get_random_skin(SKINS, 1, seed)
        emit("one %d %d seed %d" % (i, v, seed))

    for nskins in (2, 6, 10):
        seed = 1
        for i in range(8):
            v, seed = get_random_skin(SKINS, nskins, seed)
            emit("draw n%d %d %d seed %d" % (nskins, i, v, seed))

    v, seed = get_random_skin(SKINS, 10, 0)
    emit("zeroseed %d seed %d" % (v, seed))
    v, seed = get_random_skin(SKINS, 10, 0xFFFFFFFF)
    emit("maxseed %d seed %d" % (v, seed))


def s_array():
    emit("[array]")
    # GetCarTypeInfo is CarTypeInfoArray + type * sizeof(CarTypeInfo), with
    # no bounds check. The harness tags each element's Type so the index
    # that came back is visible rather than assumed.
    for i in range(8):
        emit("get %d type %d index %d" % (i, 1000 + i, i))


SCENARIOS = [s_layout, s_strings, s_skins, s_array]


def model():
    del OUT[:]
    for s in SCENARIOS:
        s()
    return list(OUT)


# ----------------------------------------------------------------- running

# A mutation can turn a `for (;;)` into a loop with no exit. With no
# deadline here that mutant spins until something kills it and stalls the
# whole pass rather than being counted; the harness itself runs in well
# under a second.
HARNESS_TIMEOUT = 60
HARNESS_HUNG = -9999


def run_harness(exe, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe)], stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


def diff(a, b, quiet=False):
    d = list(difflib.unified_diff(a, b, "model", "harness", lineterm="", n=1))
    if d and not quiet:
        for ln in d[:80]:
            print(ln)
        if len(d) > 80:
            print("... %d more diff lines" % (len(d) - 80))
    return len([x for x in d if x.startswith(("+", "-"))
                and not x.startswith(("+++", "---"))])


MUTATIONS = [
    # -- the layout -------------------------------------------------------
    # Every field the physics will reach for, moved. These are the ones
    # that matter: a wrong offset here is silent at the call site and
    # wrong everywhere downstream.
    ("off-manufacturer", CH,
     "    char            ManufacturerName[16];                //  192",
     "    char            ManufacturerName[12];                //  192"
     + NL + "    char            _mpad[4];"),
    ("off-headlight-fov", CH,
     "    bVector3        HeadlightPosition;                   //  208",
     "    bVector3        HeadlightPosition;                   //  208"
     + NL + "    float           _hpad;"),
    ("off-numskins-and-class", CH,
     "    int8_t          NumAvailableSkins;                   //  229  lb"
     + NL + "    int8_t          CarClass;                            //  230  lb",
     "    int8_t          CarClass;                            //  230  lb"
     + NL + "    int8_t          NumAvailableSkins;                   //  229  lb"),
    ("off-high-performance-word", CH,
     "    int8_t          HighPerformance;                     //  228  lb",
     "    int32_t         HighPerformance;                     //  228  lb"),
    ("off-cog-before-incar", CH,
     "    bVector3        InCarSteeringWheelRenderingOffset;   //  256"
     + NL + "    bVector3        CenterOfGravity;                     //  272",
     "    bVector3        CenterOfGravity;                     //  256"
     + NL + "    bVector3        InCarSteeringWheelRenderingOffset;   //  272"),
    ("off-wheels-three", CH,
     "    WheelInfo       Wheels[4];                           //  288",
     "    WheelInfo       Wheels[3];                           //  288"
     + NL + "    uint8_t         _wpad[32];"),
    ("off-tires-one", CH,
     "    TireInfo        Tires[2];                            //  416",
     "    TireInfo        Tires[1];                            //  416"
     + NL + "    uint8_t         _tpad[32];"),
    ("off-suspension-one", CH,
     "    SuspensionInfo  Suspension[2];                       //  560",
     "    SuspensionInfo  Suspension[1];                       //  560"
     + NL + "    uint8_t         _spad[32];"),
    ("off-sound-block", CH,
     "    uint8_t         Sound[144];                          //  816  task 29",
     "    uint8_t         Sound[160];                          //  816  task 29"
     + NL + "    uint8_t         _sndpad[0];"),
    ("off-camera-block", CH,
     "    CameraInfo      Camera;                              //  960",
     "    uint8_t         Camera[256];                         //  960"
     + NL + "    uint8_t         _campad[16];"),
    ("off-hudinfo-block", CH,
     "    uint8_t         HudInfo[80];                         // 1232  task 21",
     "    uint8_t         HudInfo[64];                         // 1232  task 21"
     + NL + "    uint8_t         _hudpad[16];"),
    ("off-locationprob-block", CH,
     "    uint8_t         LocationProb[20];                    // 1312",
     "    uint8_t         LocationProb[16];                    // 1312"
     + NL + "    uint8_t         _lppad[4];"),
    ("off-skins-array", CH,
     "    int8_t          AvailableSkins[10];                  // 1348"
     + NL + "    uint8_t         Dummy[6];                            // 1358",
     "    uint8_t         Dummy[6];                            // 1348"
     + NL + "    int8_t          AvailableSkins[10];                  // 1354"),
    ("off-skins-unsigned", CH,
     "    int8_t          AvailableSkins[10];                  // 1348",
     "    uint8_t         AvailableSkins[10];                  // 1348"),
    ("off-specs-after-pad", CH,
     "    int32_t         DefaultSkinNumber;                   // 1364"
     + NL + "    const CarSpecs *pCarSpecs;                           // 1368",
     "    int32_t         DefaultSkinNumber;                   // 1364"
     + NL + "    int32_t         _dpad;" + NL
     + "    const CarSpecs *pCarSpecs;                           // 1368"),

    # -- the nested records -----------------------------------------------
    ("wheelinfo-vector3", CH,
     "    float   PositionX;   //  0" + NL
     + "    float   PositionY;   //  4" + NL
     + "    float   PositionZ;   //  8",
     "    bVector3 Position;   //  0"),
    ("wheelinfo-radius-width-swap", CH,
     "    float   Radius;      // 12" + NL + "    float   Width;       // 16",
     "    float   Width;       // 12" + NL + "    float   Radius;      // 16"),
    ("tireinfo-forcescale-late", CH,
     "    float ForceScale;                 //  8" + NL
     + "    float StaticFrictionCoefficient;  // 12",
     "    float StaticFrictionCoefficient;  //  8" + NL
     + "    float ForceScale;                 // 12"),
    ("suspinfo-damping-one", CH,
     "    float Damping[2];              //  8" + NL
     + "    float SwayBarStiffness;        // 16",
     "    float Damping[1];              //  8" + NL
     + "    float _dpad;                   // 12" + NL
     + "    float SwayBarStiffness;        // 16"),
    ("suspinfo-bumpstop-late", CH,
     "    float BumpStop[2];             // 20" + NL
     + "    float MaxRenderingCompression; // 28",
     "    float MaxRenderingCompression; // 20" + NL
     + "    float BumpStop[2];             // 24"),
    ("drivetrain-gears-at-28", CH,
     "    float   ShiftSpeed;      // 28" + NL
     + "    float   GearRatios[8];   // 32",
     "    float   GearRatios[8];   // 28" + NL
     + "    float   ShiftSpeed;      // 60"),
    ("drivetrain-finaldrive-one", CH,
     "    float   FinalDrive[2];   //  8",
     "    float   FinalDrive[1];   //  8" + NL + "    float   _fdpad;"),
    # rigidbodyinfo-tensor-at-12 used to sit here. RigidBodyInfo moved out
    # of this header into rigidbody.h during the RigidBody slice, and the
    # mutation went with it -- a checker mutates the file it owns. The
    # offsets are still claimed here: the harness prints
    # Body.InertiaTensor's absolute offset, so rigidbody.h moving a field
    # is caught by this transcript as well as by rigidbody_check's.
    ("aeroinfo-order", CH,
     "    float FrontDownforce;       //  4" + NL
     + "    float RearDownforce;        //  8",
     "    float RearDownforce;        //  4" + NL
     + "    float FrontDownforce;       //  8"),
    ("controlinfo-limiter-at-28", CH,
     "    float MaxZMomentAccExtreme; // 28" + NL
     + "    float SpeedLimiter;         // 32",
     "    float SpeedLimiter;         // 28" + NL
     + "    float MaxZMomentAccExtreme; // 32"),
    ("carspecs-no-cartype", CH,
     "    int32_t CarType;     //  0, FindCarLanguageInfo's key" + NL,
     ""),
    ("carspecs-name-order", CH,
     "    int32_t FullName;    // 20" + NL + "    int32_t ShortName;   // 24",
     "    int32_t ShortName;   // 20" + NL + "    int32_t FullName;    // 24"),
    ("carspecs-demo-layout", CH,
     "    int32_t TopSpeedKph; // 12" + NL, ""),

    # -- the accessors ------------------------------------------------------
    ("full-reads-short", CI,
     "    return langtab_get(t, ct->pCarSpecs->FullName, outLen);",
     "    return langtab_get(t, ct->pCarSpecs->ShortName, outLen);"),
    ("short-reads-full", CI,
     "    return langtab_get(t, ct->pCarSpecs->ShortName, outLen);",
     "    return langtab_get(t, ct->pCarSpecs->FullName, outLen);"),
    ("0to60-reads-topspeed", CI,
     "    return langtab_get(t, ct->pCarSpecs->ZeroTo60, outLen);",
     "    return langtab_get(t, ct->pCarSpecs->TopSpeedMph, outLen);"),
    ("topspeed-units-swapped", CI,
     "    if (units == 1)" + NL + "        id = ct->pCarSpecs->TopSpeedKph;",
     "    if (units == 1)" + NL + "        id = ct->pCarSpecs->TopSpeedMph;"),
    ("topspeed-mph-reads-bhp", CI,
     "        id = ct->pCarSpecs->TopSpeedMph;",
     "        id = ct->pCarSpecs->BHP;"),
    ("topspeed-else-mph", CI,
     "    else if (units == 0)" + NL, "    else" + NL),
    ("topspeed-nonzero-metric", CI,
     "    if (units == 1)", "    if (units != 0)"),
    ("bhp-reads-cartype", CI,
     "    return langtab_get(t, ct->pCarSpecs->BHP, outLen);",
     "    return langtab_get(t, ct->pCarSpecs->CarType, outLen);"),
    ("manuf-by-id-not-hash", CI,
     "    return langtab_get_english(t," + NL
     + "                               (int32_t)bchunk_hash(ct->ManufacturerName),"
     + NL + "                               outLen);",
     "    return langtab_get(t, (int32_t)bchunk_hash(ct->ManufacturerName),"
     + NL + "                       outLen);"),
    ("manuf-uses-cartypename", CI,
     "(int32_t)bchunk_hash(ct->ManufacturerName),",
     "(int32_t)bchunk_hash(ct->CarTypeName),"),

    # -- the skin draw --------------------------------------------------------
    ("skin-empty-returns-first", CI,
     "    if (ct->NumAvailableSkins == 0)" + NL + "        return 0;",
     "    if (ct->NumAvailableSkins == 0)" + NL
     + "        return ct->AvailableSkins[0];"),
    ("skin-no-empty-guard", CI,
     "    if (ct->NumAvailableSkins == 0)" + NL + "        return 0;",
     "    if (0)" + NL + "        return 0;"),
    ("skin-uses-default", CI,
     "    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins,",
     "    return ct->AvailableSkins[bRandomI(ct->DefaultSkinNumber,"),
    ("skin-ignores-draw", CI,
     "    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins," + NL
     + "                                       &CarTypeInfoSkinSeed)];",
     "    (void)bRandomI(ct->NumAvailableSkins, &CarTypeInfoSkinSeed);"
     + NL + "    return ct->AvailableSkins[0];"),
    ("skin-no-seed-advance", CI,
     "    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins," + NL
     + "                                       &CarTypeInfoSkinSeed)];",
     "    uint32_t tmp = CarTypeInfoSkinSeed;" + NL
     + "    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins, &tmp)];"),
    ("skin-count-off-by-one", CI,
     "bRandomI(ct->NumAvailableSkins,", "bRandomI(ct->NumAvailableSkins - 1,"),

    # -- the array ------------------------------------------------------------
    ("array-off-by-one", CI,
     "    return &CarTypeInfoArray[carType];",
     "    return &CarTypeInfoArray[carType + 1];"),
    ("array-always-first", CI,
     "    return &CarTypeInfoArray[carType];",
     "    return &CarTypeInfoArray[0];"),
]

# Nothing survives, so nothing needs arguing. Two notes on how some of
# these are caught, because "did not compile" is a weaker-looking verdict
# than it is here:
#
#   off-specs-after-pad, off-skins-array, carspecs-no-unknown0 and
#   wheelinfo-vector3 are caught by the static assert in cartypeinfo.h
#   rather than by a transcript line. That assert is part of the port, not
#   part of the test, so a build failure is the port rejecting the change
#   -- which is the outcome wanted. It is worth knowing which mutations
#   lean on it, though, because the assert only checks the offsets it
#   names; the transcript is what covers the rest.
#
#   The seven array-shrinking mutations survived the first pass. They were
#   not equivalent -- shortening Wheels to three entries and padding after
#   it leaves every following offset untouched, so the transcript simply
#   had no line that could see it. The fix was to print each array's
#   extent rather than to argue the mutations away.
EQUIVALENT = []
EXPECT_MISSING = []


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass():
    base_model = model()
    survived, missing, equivalent, caught = [], [], [], 0

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="cartypeinfo_test")
        out = Path(tmp) / "base.txt"
        run_harness(exe, out)
        if diff(base_model, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for name, rel, before, after in MUTATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        # The ported sources are CRLF and the tools are LF, so a multi-line
        # pattern written with bare newlines misses every time against a
        # source file -- silently, as a pattern that is not found rather
        # than as a mutant that survived.
        crlf = (chr(13) + NL) in text
        probe = before.replace(NL, chr(13) + NL) if crlf else before
        repl = after.replace(NL, chr(13) + NL) if crlf else after

        if probe not in text:
            missing.append(name)
            print("  %-32s PATTERN NOT FOUND" % name)
            continue
        try:
            write_source(path, text.replace(probe, repl, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES,
                                          name="cartypeinfo_test")
                except SystemExit:
                    print("  %-32s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                if run_harness(exe, out) != 0:
                    print("  %-32s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base_model, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-32s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-32s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-32s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    real = [m for m in MUTATIONS if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    # An entry whose mutant was caught is a wrong reason, not a spare one.
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing]
    unexpected = [m for m in missing if m not in EXPECT_MISSING]
    # A pattern that is not found is dropped from the denominator above, so
    # without this the tally line reads clean while a mutation never ran.
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(MUTATIONS)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in stale:
        ran = any(m[0] == name for m in MUTATIONS)
        print("  listed as equivalent but %s: %s"
              % ("caught" if ran else "names no mutation", name))
    return 1 if (holes or unexpected or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass())

    lines = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="cartypeinfo_test")
        out = Path(tmp) / "harness.txt"
        run_harness(exe, out)
        harness = out.read_text().splitlines()

        if args.dump:
            d = Path(args.dump)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.txt").write_text(NL.join(lines) + NL)
            (d / "harness.txt").write_text(NL.join(harness) + NL)
            print("wrote %s" % d)

    n = diff(lines, harness)
    print("%d scenarios, %d lines, %d differ" % (len(SCENARIOS), len(lines), n))
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
