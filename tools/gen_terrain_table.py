"""Emit TerrainTypeInfoTable from NFSHP2.ELF.

    3DS Files/source/terraintypetab.c   TerrainTypeInfoTable (0x00310a90)

Thirty-three 140-byte records, one per TerrainType: the terrain's name, its
skid texture, the road-noise grid, the three friction multipliers Wheel
reads, and the seven particle emitter groups with their speed windows. It
is data from end to end, so the port carries it verbatim and this script is
the only thing that writes it.

The script holds the image to the header: 33 entries because the stabs'
TerrainType enum ends at NUM_TERRAIN_TYPES:33 and _GLOBAL_$I$ hashes 4620
bytes of it (0x001ca138); every entry's Type its own index; every name the
enum's own name for that index, less the TERRAIN_TYPE_ prefix; every string
pointer non-NULL except SkidTextureName (the stabs make all nine `*2`,
char pointers); NameHash 0, since the static init fills it; the two pad
bytes 0. Every float is written so that it reads back to the same bits.

    python tools/gen_terrain_table.py            # write the file
    python tools/gen_terrain_table.py --check    # verify it is current
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mipsdis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "3DS Files", "source")
OUT_C = os.path.join(SRC, "terraintypetab.c")
STABS = os.path.join(ROOT, "docs", "mdebug_raw_strings.txt")

TABLE = 0x00310a90
STRIDE = 140
COUNT = 33

# (field, kind) in record order, four bytes each except the two byte
# fields and their pad, which are read together as one word. Kinds: s a
# string pointer (NULL allowed only where marked s0), u a hex word, i a
# signed word, f a float, b the 12..15 bytes.
FIELDS = [
    ("Name", "s"), ("NameHash", "u"), ("Type", "i"), ("bytes", "b"),
    ("SkidTextureName", "s0"),
    ("RoadNoiseGridSpacingInverse", "f"), ("RoadNoiseScale", "f"),
    ("StaticFrictionMultiplier", "f"), ("DynamicFrictionMultiplier", "f"),
    ("RollingFrictionMultiplier", "f"), ("CollisionPriority", "f"),
    ("ForceMagnitude", "f"), ("ForceFrequency", "f"),
    ("DebugTopologyColour", "u"),
    ("DriveOverEmitterGroup", "s"), ("DriveOverMinSpeed", "f"),
    ("DriveOverMaxSpeed", "f"),
    ("DriveOver2EmitterGroup", "s"), ("DriveOver2MinSpeed", "f"),
    ("DriveOver2MaxSpeed", "f"),
    ("SkidSmokeEmitterGroup", "s"), ("SkidSmokeMinSpeed", "f"),
    ("SkidSmokeMaxSpeed", "f"),
    ("TireSpewEmitterGroup", "s"), ("TireSpewMinSpeed", "f"),
    ("TireSpewMaxSpeed", "f"),
    ("BottomOutEmitterGroup", "s"), ("BottomOutMinImpact", "f"),
    ("BottomOutMaxImpact", "f"),
    ("CollisionImpactEmitterGroup", "s"), ("CollisionImpactMinForce", "f"),
    ("CollisionImpactMaxForce", "f"),
    ("CollisionScrapeEmitterGroup", "s"), ("CollisionScrapeMinSpeed", "f"),
    ("CollisionScrapeMaxSpeed", "f"),
]
assert len(FIELDS) * 4 == STRIDE


def stabs_enum(name, last):
    pat = re.compile(r"%s:t\d+=e([^;]*);" % re.escape(name))
    best = None
    with open(STABS, "r", encoding="latin-1") as fh:
        for ln in fh:
            for m in pat.finditer(ln):
                body = m.group(1)
                if last in body and (best is None or len(body) > len(best)):
                    best = body
    if best is None:
        sys.exit("no complete %s enum in %s" % (name, STABS))
    out = []
    for item in best.rstrip(",").split(","):
        k, v = item.split(":")
        out.append((k, int(v)))
    return out


def cstr(elf, addr):
    raw = elf.read(addr, 128)
    return raw[:raw.index(b"\0")].decode("latin-1")


def c_string(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def c_float(bits):
    """The shortest decimal that a C compiler reads back as `bits`."""
    want = struct.unpack("<f", struct.pack("<I", bits))[0]
    if bits & 0x7f800000 == 0x7f800000:
        sys.exit("float 0x%08x is not finite" % bits)
    for prec in range(1, 10):
        s = "%.*g" % (prec, want)
        if struct.unpack("<I", struct.pack("<f", float(s)))[0] == bits:
            break
    else:
        sys.exit("no round trip for 0x%08x" % bits)
    # repr of the decimal's double spells it plainly -- 50.0, not 5e+01 --
    # and is still the same decimal, so still the same float.
    s = repr(float(s))
    if struct.unpack("<I", struct.pack("<f", float(s)))[0] != bits:
        sys.exit("repr broke the round trip for 0x%08x" % bits)
    return s + "f"


def read_all():
    elf = mipsdis.Elf()
    enum = stabs_enum("TerrainType", "NUM_TERRAIN_TYPES:33")
    names = {v: k for k, v in enum}
    if names.get(COUNT) != "NUM_TERRAIN_TYPES":
        sys.exit("TerrainType does not end at NUM_TERRAIN_TYPES:%d" % COUNT)
    if "TerrainTypeInfoTable" in elf.syms:
        addr, size = elf.syms["TerrainTypeInfoTable"]
        if addr != TABLE or size not in (0, STRIDE * COUNT):
            sys.exit("TerrainTypeInfoTable is 0x%08x/%d" % (addr, size))

    rows = []
    for i in range(COUNT):
        raw = elf.read(TABLE + STRIDE * i, STRIDE)
        words = struct.unpack("<%dI" % (STRIDE // 4), raw)
        row = []
        for (field, kind), w in zip(FIELDS, words):
            where = "entry %d %s" % (i, field)
            if kind in ("s", "s0"):
                if w == 0:
                    if kind == "s":
                        sys.exit("%s is NULL" % where)
                    row.append((field, "NULL"))
                else:
                    row.append((field, c_string(cstr(elf, w))))
            elif kind == "u":
                row.append((field, "0x%08x" % w))
            elif kind == "i":
                row.append((field, "%d" % struct.unpack("<i", struct.pack("<I", w))[0]))
            elif kind == "f":
                row.append((field, c_float(w)))
            elif kind == "b":
                b = struct.pack("<I", w)
                if b[2] or b[3]:
                    sys.exit("%s: pad bytes are %d, %d" % (where, b[2], b[3]))
                row.append(("ShouldTireMakeRoadSound", "%d" % b[0]))
                row.append(("ShouldCameraGoThroughIt", "%d" % b[1]))
        vals = dict(row)
        if vals["NameHash"] != "0x00000000":
            sys.exit("entry %d: NameHash is %s in the ELF" % (i, vals["NameHash"]))
        if vals["Type"] != "%d" % i:
            sys.exit("entry %d: Type is %s" % (i, vals["Type"]))
        want = c_string(names[i][len("TERRAIN_TYPE_"):])
        if vals["Name"] != want:
            sys.exit("entry %d: named %s, the enum says %s"
                     % (i, vals["Name"], want))
        rows.append((names[i], row))
    return rows


def render(rows):
    out = []
    for i, (enum_name, row) in enumerate(rows):
        lines = ["    {  // %d %s" % (i, enum_name)]
        for field, val in row:
            lines.append("        .%s = %s," % (field, val))
        lines.append("    },")
        out.append("\n".join(lines))
    return """\
// Generated by tools/gen_terrain_table.py -- do not edit.
//
// TerrainTypeInfoTable (0x00310a90), read out of NFSHP2.ELF: 33 entries of
// 140 bytes, indexed by TerrainType. NameHash is 0 here as it is in the
// ELF; terraintype_static_init fills it in at boot.

#include <stddef.h>
#include <stdint.h>

#include "terraintype.h"

TerrainTypeInfo TerrainTypeInfoTable[NUM_TERRAIN_TYPES] = {
%s
};
""" % "\n".join(out)


def main():
    text = render(read_all())
    check = "--check" in sys.argv
    old = None
    if os.path.exists(OUT_C):
        with open(OUT_C, "r", newline="") as fh:
            old = fh.read()
    base = os.path.basename(OUT_C)
    if check:
        if old == text:
            print("%s is up to date" % base)
            return 0
        print("%s is STALE -- re-run tools/gen_terrain_table.py" % base)
        return 1
    with open(OUT_C, "w", newline="") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (OUT_C, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
